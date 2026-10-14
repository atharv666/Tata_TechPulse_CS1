"""Stage handlers executed by the job runner.

Every handler is idempotent (a retry or a lease recovery may run it again), commits completed
units of work through ``JobContext.checkpoint`` and queues the next stage in the same transaction
as the work that makes it runnable.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select

from app.canonicalization.resolution import EntityResolutionService, ResolutionConfig
from app.comparison.service import ComparisonRunner, finding_groups
from app.core.config import Settings
from app.extraction.service import CandidateExtractionService
from app.graph.build import GraphBuildService
from app.ingestion.service import IngestionService, Upload
from app.jobs.orchestration import JobContext, JobHandler, JobPartialFailure, RetryableJobError
from app.jobs.source_store import SourceStore
from app.models.enums import ComparisonState
from app.models.schema import Chunk, Comparison, Job, Section
from app.providers.contracts import ProviderTransientError
from app.providers.factory import create_embedding_provider, create_llm_provider
from app.repositories.vectors import VectorRepository
from app.retrieval.vector import EmbeddingService


class PipelineHandlers:
    """Registers only explicit jobs; raw document content is read from private source storage."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def handlers(self) -> dict[str, JobHandler]:
        return {
            "DOCUMENT_INGESTION": self.ingest,
            "EMBEDDING": self.embed,
            "REEMBED": self.reembed,
            "GRAPH_EXTRACTION": self.extract,
            "ENTITY_RESOLUTION": self.resolve,
            "VALIDATION": self.build_graph,
            "GRAPH_BUILD": self.build_graph,
            "REVISION_COMPARISON": self.compare,
        }

    # -- 1. ingestion ------------------------------------------------------------------------
    def ingest(self, job: Job, context: JobContext) -> None:
        payload = self._payload(job)
        context.progress(5, "Reading managed upload source")
        try:
            content = SourceStore(self._settings.document_source_dir).read(
                UUID(str(payload["source_key"]))
            )
        except (FileNotFoundError, OSError) as error:
            raise RetryableJobError("Managed upload source is temporarily unavailable.") from error
        context.progress(15, "Parsing and persisting document structure")
        persisted = IngestionService(self._settings).ingest(
            context.session,
            job.project_id,
            job.requested_by,
            Upload(
                str(payload["filename"]),
                str(payload["media_type"]) if payload.get("media_type") else None,
                content,
                str(payload["storage_uri"]),
            ),
        )
        context.set_detail("document_id", str(persisted.document.id))
        context.set_detail("document_version_id", str(persisted.version.id))
        context.set_detail("coverage", persisted.result.warnings)
        context.progress(90, "Document sections and chunks persisted")
        context.enqueue_next(
            "EMBEDDING",
            {"document_version_id": str(persisted.version.id)},
            f"embedding:{job.project_id}:{persisted.version.id}",
        )

    # -- 2. embeddings -----------------------------------------------------------------------
    async def embed(self, job: Job, context: JobContext) -> None:
        payload = self._payload(job)
        version_id = self._version_id(payload)
        await self._index(job, context, version_id, "Embedded")
        context.enqueue_next(
            "GRAPH_EXTRACTION",
            payload,
            f"extraction:{job.project_id}:{version_id or 'all'}",
        )

    async def reembed(self, job: Job, context: JobContext) -> None:
        await self._index(job, context, None, "Re-embedded")
        context.enqueue_next(
            "GRAPH_EXTRACTION", self._payload(job), f"extraction:{job.project_id}:all"
        )

    async def _index(
        self, job: Job, context: JobContext, version_id: UUID | None, verb: str
    ) -> None:
        settings = self._settings
        service = EmbeddingService(
            create_embedding_provider(settings.embedding_settings()),
            settings.embedding_settings(),
        )
        repository = VectorRepository(context.session, job.project_id)
        pending = self._count_pending(context, version_id)
        context.progress(5, f"{pending} chunk(s) need embeddings")

        def after_batch(total: int, _: int) -> None:
            percent = min(95, 5 + int(90 * total / max(pending, 1)))
            context.checkpoint(percent, f"{verb} {total}/{pending} chunks")

        result = await service.index_pending(
            repository,
            batch_size=settings.embedding_batch_size,
            document_version_id=version_id,
            after_batch=after_batch,
        )
        context.set_detail("embedded_chunks", result.indexed_count)

    def _count_pending(self, context: JobContext, version_id: UUID | None) -> int:
        settings = self._settings.embedding_settings()
        statement = select(func.count(Chunk.id)).where(
            Chunk.project_id == context.job.project_id,
            (Chunk.embedding.is_(None))
            | (Chunk.embedding_model.is_distinct_from(settings.model))
            | (Chunk.embedding_model_version.is_distinct_from(settings.model_version)),
        )
        if version_id is not None:
            statement = statement.where(Chunk.document_version_id == version_id)
        return int(context.session.scalar(statement) or 0)

    # -- 3. candidate extraction -------------------------------------------------------------
    async def extract(self, job: Job, context: JobContext) -> None:
        payload = self._payload(job)
        version_id = self._version_id(payload)
        statement = (
            select(Chunk.id)
            .join(Section, Section.id == Chunk.section_id)
            .where(Chunk.project_id == job.project_id, Chunk.extracted_at.is_(None))
            # Document order, so results do not depend on arbitrary heap/UUID ordering.
            .order_by(Section.document_version_id, Section.ordinal, Chunk.ordinal)
        )
        if version_id is not None:
            statement = statement.where(Chunk.document_version_id == version_id)
        chunk_ids = list(context.session.scalars(statement))
        extractor = CandidateExtractionService(create_llm_provider(self._settings.llm_settings()))
        failures: list[dict[str, str]] = []
        for index, chunk_id in enumerate(chunk_ids, start=1):
            context.raise_if_cancelled()
            try:
                # A savepoint isolates one chunk: a bad LLM answer rolls back only that chunk.
                with context.session.begin_nested():
                    await extractor.extract_chunk(context.session, job.project_id, chunk_id)
            except ProviderTransientError:
                context.session.rollback()
                raise  # rate limit / outage: stop, keep committed chunks, retry the rest later
            except Exception as error:
                failures.append({"stage": "GRAPH_EXTRACTION", "error_type": type(error).__name__})
            context.checkpoint(
                int(index * 95 / max(len(chunk_ids), 1)),
                f"Processed {index}/{len(chunk_ids)} chunks",
            )
        context.set_detail("extracted_chunks", len(chunk_ids) - len(failures))
        context.enqueue_next(
            "ENTITY_RESOLUTION", payload, f"resolution:{job.project_id}:{version_id or 'all'}"
        )
        if failures:
            raise JobPartialFailure("One or more chunks could not be extracted.", failures)

    # -- 4. resolution and 5. graph build ----------------------------------------------------
    async def resolve(self, job: Job, context: JobContext) -> None:
        payload = self._payload(job)
        await self._resolve_entities(job, context)
        context.enqueue_next(
            "GRAPH_BUILD",
            payload,
            f"graph-build:{job.project_id}:{payload.get('document_version_id', 'all')}",
        )

    async def _resolve_entities(self, job: Job, context: JobContext) -> None:
        settings = self._settings
        context.progress(5, "Resolving duplicate entities")
        llm = (
            create_llm_provider(settings.llm_settings())
            if settings.resolution_llm_enabled
            else None
        )
        service = EntityResolutionService(llm, ResolutionConfig.from_settings(settings))
        result = await service.resolve(
            context.session,
            job.project_id,
            job.requested_by,
            checkpoint=lambda: context.checkpoint(50, "Judged a batch of ambiguous entity pairs"),
        )
        context.set_detail(
            "resolution",
            {
                "entities": result.entities,
                "pairs_considered": result.pairs_considered,
                "blocked_by_guard": result.blocked_by_guard,
                "rule_merges": result.rule_merges,
                "llm_merges": result.llm_merges,
                "llm_pairs_judged": result.llm_pairs_judged,
                "llm_pairs_cached": result.llm_pairs_cached,
                "llm_pairs_deferred": result.llm_pairs_deferred,
                "llm_batches_failed": result.llm_batches_failed,
                "refused_unions": result.refused_unions,
            },
        )

    async def build_graph(self, job: Job, context: JobContext) -> None:
        """Bind relationships, validate and refresh findings; ``resolve: true`` re-resolves first.

        A user-requested (re)build sets ``resolve`` so it also picks up new aliases or reviewer
        decisions; the automatic chain has just run resolution and does not repeat it.
        """
        if self._payload(job).get("resolve"):
            await self._resolve_entities(job, context)
        context.progress(60, "Validating candidate graph facts")
        GraphBuildService().build(context.session, job.project_id, job.requested_by, job)
        context.progress(90, "Graph build validation completed")

    # -- revision comparison -----------------------------------------------------------------
    def compare(self, job: Job, context: JobContext) -> None:
        """Run the comparison the API queued; the job row is the only job (none is created here)."""
        comparison_id = UUID(str(self._payload(job)["comparison_id"]))
        context.progress(10, "Comparing the document versions")
        try:
            result = ComparisonRunner().execute(context.session, comparison_id)
        except Exception:
            context.session.rollback()
            comparison = context.session.get(Comparison, comparison_id)
            if comparison is not None:
                comparison.state = ComparisonState.FAILED
                context.session.commit()
            raise
        context.set_detail("comparison_id", str(comparison_id))
        context.set_detail("findings", len(result.findings))
        context.set_detail("summary", finding_groups(result.findings))
        context.progress(95, "Comparison findings stored")

    # -- helpers -----------------------------------------------------------------------------
    @staticmethod
    def _payload(job: Job) -> dict[str, object]:
        payload = job.details.get("payload", {})
        return dict(payload) if isinstance(payload, dict) else {}

    @staticmethod
    def _version_id(payload: dict[str, object]) -> UUID | None:
        value = payload.get("document_version_id")
        return UUID(str(value)) if value else None
