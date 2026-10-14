"""Ingestion orchestration: parse, normalise, chunk and persist one document revision atomically."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.metrics import metrics
from app.ingestion.chunking import PlannedSection, plan_document
from app.ingestion.contracts import IngestionError, IngestionResult
from app.ingestion.lexical import build_lexical_text
from app.ingestion.metadata import extract_metadata
from app.ingestion.normalize import normalize_document
from app.ingestion.ocr import CachingOCRProvider, create_ocr_provider
from app.ingestion.parsers import OCRProvider, ParserFactory
from app.ingestion.validation import content_hash, safe_filename, validate_upload
from app.models.schema import AuditEvent, Chunk, Document, DocumentVersion, OcrCache, Section
from app.repositories.documents import DocumentRepository

MAX_RECORDED_WARNINGS = 50


@dataclass(frozen=True)
class Upload:
    filename: str
    media_type: str | None
    content: bytes
    storage_uri: str


@dataclass(frozen=True)
class PersistedIngestion:
    document: Document
    version: DocumentVersion
    result: IngestionResult
    section_count: int
    chunk_count: int


class DbOcrCache:
    """Project-scoped OCR page cache backed by the ``ocr_cache`` table."""

    def __init__(self, session: Session, project_id: UUID) -> None:
        self._session = session
        self._project_id = project_id

    def get(self, key: str) -> str | None:
        return self._session.scalar(
            select(OcrCache.text).where(
                OcrCache.project_id == self._project_id, OcrCache.cache_key == key
            )
        )

    def put(self, key: str, text: str) -> None:
        self._session.execute(
            pg_insert(OcrCache)
            .values(project_id=self._project_id, cache_key=key, text=text)
            .on_conflict_do_nothing(constraint="project_ocr_cache_key")
        )


class IngestionService:
    def __init__(
        self,
        settings: Settings,
        parsers: ParserFactory | None = None,
        ocr_provider: OCRProvider | None = None,
    ) -> None:
        self._settings = settings
        self._parsers = parsers
        self._ocr_override = ocr_provider

    def _parser_factory(self, session: Session, project_id: UUID) -> ParserFactory:
        if self._parsers is not None:
            return self._parsers
        provider = self._ocr_override or create_ocr_provider(self._settings)
        if provider is not None:
            provider = CachingOCRProvider(
                provider, DbOcrCache(session, project_id), self._settings.ocr_model or ""
            )
        return ParserFactory(
            provider,
            ocr_min_chars=self._settings.ocr_min_chars,
            ocr_dpi=self._settings.ocr_dpi,
            ocr_max_pages=self._settings.ocr_max_pages,
        )

    def ingest(
        self, session: Session, project_id: UUID, actor_id: str, upload: Upload
    ) -> PersistedIngestion:
        """Parse and persist one document revision atomically.

        The caller owns the transaction: nothing is committed here, so a failure leaves no partial
        document behind. Job state is the job runner's concern, not this service's.
        """
        metrics.increment("ingestion_jobs_started")
        document_format = validate_upload(
            upload.filename, upload.media_type, upload.content, self._settings.max_upload_bytes
        )
        checksum = content_hash(upload.content)
        duplicate = session.scalar(
            select(DocumentVersion).where(
                DocumentVersion.project_id == project_id, DocumentVersion.checksum == checksum
            )
        )
        if duplicate is not None:
            metrics.increment("ingestion_jobs_failed")
            raise IngestionError("An identical source file already exists in this project.")

        doc_name = safe_filename(upload.filename)
        factory = self._parser_factory(session, project_id)
        # Parse before writing anything: a corrupt file must not create an empty document row.
        try:
            parsed = factory.parser_for(document_format).parse(upload.content)
            sections = normalize_document(parsed)
            planned = plan_document(
                sections,
                self._settings.chunk_max_tokens,
                self._settings.chunk_overlap_tokens,
                self._settings.chunk_target_tokens,
            )
        except Exception:
            metrics.increment("ingestion_jobs_failed")
            raise
        metadata = extract_metadata(parsed, sections, doc_name)

        repository = DocumentRepository(session, project_id)
        document = session.scalar(
            select(Document).where(Document.project_id == project_id, Document.name == doc_name)
        )
        if document is None:
            document = Document(
                project_id=project_id,
                name=doc_name,
                media_type=upload.media_type or "application/octet-stream",
                storage_uri=upload.storage_uri,
                created_by=actor_id,
            )
            repository.add_document(document)
            session.flush()
            version_number = 1
        else:
            latest_version = session.scalar(
                select(func.max(DocumentVersion.version_number)).where(
                    DocumentVersion.document_id == document.id
                )
            )
            version_number = (latest_version or 0) + 1

        label = f"{doc_name} v{version_number}"
        if metadata.get("version"):
            label += f" (document version {metadata['version']})"
        chunk_total = sum(len(item.chunks) for item in planned)
        version = DocumentVersion(
            project_id=project_id,
            document_id=document.id,
            version_number=version_number,
            checksum=checksum,
            source_label=label[:255],
            properties={
                **metadata,
                "structure_source": parsed.structure_source,
                "ocr_pages": parsed.ocr_pages,
                "removed_running_lines": parsed.removed_running_lines,
                "section_count": len(planned),
                "chunk_count": chunk_total,
                "warnings": parsed.warnings[:MAX_RECORDED_WARNINGS],
            },
        )
        repository.add_version(version)
        # The version row must exist before sections/chunks reference it.
        session.flush()
        self._persist(repository, project_id, version.id, doc_name, planned)
        session.flush()
        self._audit_external_ocr(session, project_id, actor_id, version, parsed.ocr_pages, factory)
        metrics.increment("ingestion_jobs_completed")
        metrics.increment("ingestion_sections", len(planned))
        metrics.increment("ingestion_warnings", len(parsed.warnings))
        return PersistedIngestion(
            document,
            version,
            IngestionResult(
                checksum,
                document_format,
                sections,
                parsed.warnings,
                metadata,
                parsed.structure_source,
                parsed.ocr_pages,
            ),
            len(planned),
            chunk_total,
        )

    @staticmethod
    def _persist(
        repository: DocumentRepository,
        project_id: UUID,
        version_id: UUID,
        document_name: str,
        planned: list[PlannedSection],
    ) -> None:
        section_ids: dict[int, UUID] = {}
        for item in planned:
            normalized = item.section
            section = Section(
                project_id=project_id,
                document_version_id=version_id,
                parent_section_id=section_ids.get(item.parent_ordinal)
                if item.parent_ordinal
                else None,
                ordinal=item.ordinal,
                heading=normalized.display_heading[:1024],
                level=normalized.level,
                number_label=normalized.number,
                path=item.path,
                depth=item.depth,
                page_start=item.page_start,
                page_end=item.page_end,
            )
            repository.add_section(section)
            section_ids[item.ordinal] = section.id
        # No ORM relationships exist between these tables, so SQLAlchemy cannot infer that chunks
        # must be inserted after their sections: flush the sections explicitly first.
        repository.session.flush()
        for item in planned:
            breadcrumb = f"{document_name} > {item.path}" if item.path else document_name
            for chunk_ordinal, candidate in enumerate(item.chunks, start=1):
                embedding_text = f"{breadcrumb}\n{candidate.content}"
                repository.add_chunk(
                    Chunk(
                        project_id=project_id,
                        document_version_id=version_id,
                        section_id=section_ids[item.ordinal],
                        ordinal=chunk_ordinal,
                        content=candidate.content,
                        token_count=candidate.token_count,
                        page_start=candidate.page_start,
                        page_end=candidate.page_end,
                        breadcrumb=breadcrumb,
                        content_hash=hashlib.sha256(embedding_text.encode("utf-8")).hexdigest(),
                        chunk_kind=candidate.kind,
                        attrs={"ocr": candidate.kind == "OCR_TEXT"},
                        lexical_text=build_lexical_text(breadcrumb, candidate.content),
                    )
                )

    @staticmethod
    def _audit_external_ocr(
        session: Session,
        project_id: UUID,
        actor_id: str,
        version: DocumentVersion,
        ocr_pages: list[int],
        factory: ParserFactory,
    ) -> None:
        """Page images sent to a third party are always auditable (counts only, never content)."""
        provider = factory.ocr_provider
        if not ocr_pages or provider is None or not provider.external:
            return
        session.add(
            AuditEvent(
                project_id=project_id,
                actor_id=actor_id,
                action="EXTERNAL_OCR_USED",
                resource_type="DOCUMENT_VERSION",
                resource_id=version.id,
                details={"provider": provider.name, "pages": len(ocr_pages)},
            )
        )
