"""Worker handlers that invoke existing pipeline services under the durable job executor."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.extraction.service import CandidateExtractionService
from app.graph.build import GraphBuildService
from app.ingestion.service import IngestionService, Upload
from app.jobs.orchestration import JobContext, JobHandler, JobPartialFailure, RetryableJobError
from app.jobs.source_store import SourceStore
from app.models.schema import Chunk, Job
from app.providers.factory import create_embedding_provider, create_llm_provider
from app.repositories.jobs import JobRepository
from app.repositories.vectors import VectorRepository
from app.retrieval.vector import EmbeddingService


class PipelineHandlers:
    """Registers only explicit jobs; raw document content is read from private source storage."""

    def __init__(self, session: Session, settings: Settings) -> None:
        self._session = session
        self._settings = settings

    def handlers(self) -> dict[str, JobHandler]:
        return {
            "DOCUMENT_INGESTION": self.ingest,
            "OCR": self.ocr,
            "EMBEDDING": self.embed,
            "REEMBED": self.reembed,
            "GRAPH_EXTRACTION": self.extract,
            "ENTITY_RESOLUTION": self.resolve,
            "VALIDATION": self.validate,
            "GRAPH_BUILD": self.build_graph,
            "REVISION_COMPARISON": self.compare,
        }

    def ingest(self, job: Job, context: JobContext) -> None:
        payload = job.details["payload"]
        context.progress(5, "Validating document source")
        try:
            content = SourceStore(self._settings.document_source_dir).read(
                UUID(str(payload["source_key"]))
            )
        except (FileNotFoundError, OSError) as error:
            raise RetryableJobError("Managed upload source is temporarily unavailable.") from error
        persisted = IngestionService(self._settings).ingest(
            self._session,
            job.project_id,
            job.requested_by,
            Upload(
                str(payload["filename"]),
                str(payload["media_type"]) if payload.get("media_type") else None,
                content,
                str(payload["storage_uri"]),
            ),
            job,
        )
        context.progress(90, "Document sections and chunks persisted")
        self._enqueue_next(
            job,
            "EMBEDDING",
            {"document_version_id": str(persisted.version.id)},
            f"embedding:{job.project_id}:{persisted.version.id}",
        )

    def ocr(self, job: Job, context: JobContext) -> None:
        # OCR fallback is parser-owned; this records that no separate retry was needed.
        context.progress(100, "OCR fallback evaluation completed")

    async def embed(self, job: Job, context: JobContext) -> None:
        context.progress(10, "Embedding project chunks")
        service = EmbeddingService(
            create_embedding_provider(self._settings.embedding_settings()),
            self._settings.embedding_settings(),
        )
        result = await service.index_pending(VectorRepository(self._session, job.project_id))
        context.progress(90, f"Indexed {result.indexed_count} chunks")
        self._enqueue_next(
            job,
            "GRAPH_EXTRACTION",
            self._payload(job),
            f"extraction:{job.project_id}:{self._payload(job).get('document_version_id', 'all')}",
        )

    async def reembed(self, job: Job, context: JobContext) -> None:
        context.progress(10, "Re-embedding project chunks")
        service = EmbeddingService(
            create_embedding_provider(self._settings.embedding_settings()),
            self._settings.embedding_settings(),
        )
        result = await service.reembed(VectorRepository(self._session, job.project_id))
        context.progress(90, f"Re-embedded {result.indexed_count} chunks")
        self._enqueue_next(
            job,
            "GRAPH_EXTRACTION",
            self._payload(job),
            f"extraction:{job.project_id}:all",
        )

    async def extract(self, job: Job, context: JobContext) -> None:
        statement = select(Chunk).where(
            Chunk.project_id == job.project_id,
            Chunk.extracted_at.is_(None),
        )
        document_version_id = self._payload(job).get("document_version_id")
        if document_version_id:
            statement = statement.where(Chunk.document_version_id == UUID(str(document_version_id)))
        chunks = list(self._session.scalars(statement))
        extractor = CandidateExtractionService(create_llm_provider(self._settings.llm_settings()))
        failures: list[dict[str, str]] = []
        for index, chunk in enumerate(chunks, start=1):
            if context.cancelled():
                return
            try:
                await extractor.extract_chunk(self._session, job.project_id, chunk.id)
            except Exception as error:
                failures.append({"stage": "GRAPH_EXTRACTION", "error_type": type(error).__name__})
            context.progress(int(index * 90 / max(len(chunks), 1)), "Processed extraction chunk")
        if failures:
            raise JobPartialFailure("One or more chunks could not be extracted.", failures)
        self._enqueue_next(
            job,
            "ENTITY_RESOLUTION",
            self._payload(job),
            f"resolution:{job.project_id}:{document_version_id or 'all'}",
        )

    def resolve(self, job: Job, context: JobContext) -> None:
        # Candidate extraction performs exact, type-scoped reuse.  Ambiguous merges
        # are intentionally left unresolved: a worker must not silently merge facts.
        # This explicit stage provides a durable audit boundary before graph build.
        context.progress(90, "Exact candidate resolution completed; ambiguities retained")
        self._enqueue_next(
            job,
            "GRAPH_BUILD",
            self._payload(job),
            f"graph-build:{job.project_id}:{self._payload(job).get('document_version_id', 'all')}",
        )

    def validate(self, job: Job, context: JobContext) -> None:
        self.build_graph(job, context)

    def build_graph(self, job: Job, context: JobContext) -> None:
        context.progress(10, "Validating candidate graph facts")
        GraphBuildService().build(self._session, job.project_id, job.requested_by, job)
        context.progress(90, "Graph build validation completed")

    def compare(self, job: Job, context: JobContext) -> None:
        payload = job.details["payload"]
        base_id = UUID(str(payload["base_version_id"]))
        target_id = UUID(str(payload["target_version_id"]))
        context.progress(10, "Extracting revision snapshots")
        from app.api.dependencies import CurrentUser
        from app.repositories.comparisons import ComparisonRepository
        from app.retrieval.revision import ComparisonJobService
        from app.services.api import MvpApiService

        api = MvpApiService(self._session, CurrentUser(job.requested_by))
        base_snap = api._snapshot(job.project_id, base_id)
        target_snap = api._snapshot(job.project_id, target_id)
        context.progress(50, "Running revision comparison")
        repo = ComparisonRepository(self._session, job.project_id)
        comparison, _, result = ComparisonJobService().run(
            repo, job.requested_by, base_snap, target_snap
        )
        details = dict(job.details)
        details["comparison_id"] = str(comparison.id)
        details["findings"] = len(result.findings)
        job.details = details
        context.progress(100, "Revision comparison completed")

    def _enqueue_next(
        self, job: Job, job_type: str, payload: dict[str, object], idempotency_key: str
    ) -> None:
        """Advance the durable pipeline only after the preceding stage succeeds."""
        next_job = JobRepository(self._session).enqueue(
            job.project_id, job_type, job.requested_by, payload, idempotency_key
        )
        details = dict(job.details)
        details["next_job_id"] = str(next_job.id)
        details["next_job_type"] = job_type
        job.details = details

    @staticmethod
    def _payload(job: Job) -> dict[str, object]:
        payload = job.details.get("payload", {})
        return dict(payload) if isinstance(payload, dict) else {}
