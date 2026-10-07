"""Ingestion orchestration with persistence and non-fatal coverage warnings."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.metrics import metrics
from app.ingestion.chunking import chunk_section
from app.ingestion.contracts import IngestionError, IngestionResult, NormalizedSection
from app.ingestion.normalize import normalize_document
from app.ingestion.parsers import ParserFactory
from app.ingestion.validation import content_hash, safe_filename, validate_upload
from app.models.enums import JobState
from app.models.schema import Chunk, Document, DocumentVersion, Job, Section
from app.repositories.documents import DocumentRepository


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
    job: Job
    result: IngestionResult


class IngestionService:
    def __init__(self, settings: Settings, parsers: ParserFactory | None = None) -> None:
        self._settings = settings
        self._parsers = parsers or ParserFactory()

    def ingest(
        self,
        session: Session,
        project_id: UUID,
        actor_id: str,
        upload: Upload,
        job: Job | None = None,
    ) -> PersistedIngestion:
        """Execute one explicit ingestion job and retain non-fatal warnings as coverage metadata."""
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
            raise IngestionError("An identical source file already exists in this project.")

        doc_name = safe_filename(upload.filename)
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

        version = DocumentVersion(
            project_id=project_id,
            document_id=document.id,
            version_number=version_number,
            checksum=checksum,
            source_label=f"{doc_name} v{version_number}",
        )
        repository.add_version(version)
        if job is None:
            job = Job(
                project_id=project_id,
                job_type="DOCUMENT_INGESTION",
                state=JobState.RUNNING,
                requested_by=actor_id,
                details={"checksum": checksum, "coverage": []},
            )
            session.add(job)
            session.flush()
        try:
            parsed = self._parsers.parser_for(document_format).parse(upload.content)
            sections = normalize_document(parsed)
            self._persist_sections(repository, project_id, version.id, sections)
            job.state = JobState.COMPLETED
            # Keep queue metadata (payload, opaque source key, logs and
            # cancellation state) because downstream jobs need it for an auditable
            # pipeline hand-off.
            job.details = {
                **dict(job.details),
                "checksum": checksum,
                "coverage": parsed.warnings,
                "document_id": str(document.id),
                "document_version_id": str(version.id),
            }
            metrics.increment("ingestion_jobs_completed")
            metrics.increment("ingestion_sections", len(sections))
            metrics.increment("ingestion_warnings", len(parsed.warnings))
            return PersistedIngestion(
                document,
                version,
                job,
                IngestionResult(checksum, document_format, sections, parsed.warnings),
            )
        except Exception as error:
            job.state = JobState.FAILED
            job.details = {
                **dict(job.details),
                "checksum": checksum,
                "failure": type(error).__name__,
            }
            metrics.increment("ingestion_jobs_failed")
            raise

    def _persist_sections(
        self,
        repository: DocumentRepository,
        project_id: UUID,
        version_id: UUID,
        sections: list[NormalizedSection],
        parent_id: UUID | None = None,
        ordinal_start: int = 1,
    ) -> int:
        ordinal = ordinal_start
        for normalized in sections:
            section = Section(
                project_id=project_id,
                document_version_id=version_id,
                parent_section_id=parent_id,
                ordinal=ordinal,
                heading=normalized.heading,
                level=normalized.level,
                page_start=normalized.position.page,
                page_end=normalized.position.page,
            )
            repository.add_section(section)
            repository.session.flush()
            for chunk_ordinal, candidate in enumerate(
                chunk_section(
                    normalized, self._settings.chunk_max_tokens, self._settings.chunk_overlap_tokens
                ),
                start=1,
            ):
                repository.add_chunk(
                    Chunk(
                        project_id=project_id,
                        document_version_id=version_id,
                        section_id=section.id,
                        ordinal=chunk_ordinal,
                        content=candidate.content,
                        token_count=candidate.token_count,
                        page_start=candidate.position.page,
                        page_end=candidate.position.page,
                    )
                )
            ordinal += 1
            ordinal = self._persist_sections(
                repository, project_id, version_id, normalized.children, section.id, ordinal
            )
        return ordinal
