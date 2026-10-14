"""Run a RAG evaluation end to end: ingest fixtures, embed, ask every question, summarise."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import select

from app.api.dependencies import CurrentUser
from app.core.config import Settings, get_settings
from app.db.session import get_session_factory
from app.evaluation.rag_eval import QuestionResult, evaluate, load_questions
from app.jobs.orchestration import JobContext, JobRunner
from app.jobs.pipeline import PipelineHandlers
from app.models.enums import JobState, MembershipRole
from app.models.schema import Job
from app.providers.factory import create_embedding_provider, create_llm_provider
from app.retrieval.answer import RagPipeline
from app.retrieval.vector import EmbeddingService
from app.schemas.api import ProjectCreate
from app.services.api import MvpApiService

EVAL_USER = "evaluation"


@dataclass
class EvaluationRun:
    title: str
    summary: dict[str, Any]
    results: list[QuestionResult]
    settings_snapshot: dict[str, Any]
    ingestion: dict[str, Any]


def _noop(job: Job, context: JobContext) -> None:
    """Retrieval evaluation stops after embedding: extraction is not part of this measurement."""
    context.progress(100, "skipped for RAG evaluation")


def run_evaluation(
    questions_path: Path, documents_dir: Path, settings: Settings | None = None, top_k: int = 8
) -> EvaluationRun:
    """Must run against a database that may be written to (use ``temporary_database``)."""
    settings = settings or get_settings()
    spec, questions = load_questions(questions_path)
    factory = get_session_factory()
    with factory() as session:
        service = MvpApiService(session, CurrentUser(EVAL_USER))
        project = service.create_project(ProjectCreate(name="rag-evaluation"))
        session.commit()
        project_id = project.id
        from app.api.dependencies import ProjectAccess

        access = ProjectAccess(project_id, EVAL_USER, MembershipRole.ADMIN)
        for name in spec["documents"]:
            path = documents_dir / name
            service.upload_document_content(access, path.name, "text/markdown", path.read_bytes())
        session.commit()

    handlers = PipelineHandlers(settings).handlers()
    handlers["GRAPH_EXTRACTION"] = _noop
    runner = JobRunner(factory, handlers, worker_id="evaluation")
    for _ in range(200):
        if runner.run_once() is None:
            break
    with factory() as session:
        failed = list(session.scalars(select(Job).where(Job.state == JobState.FAILED)))
        if failed:
            raise RuntimeError(
                f"ingestion/embedding failed: {failed[0].details.get('failure_message')}"
            )
        ingestion = {"jobs": len(list(session.scalars(select(Job))))}

    async def run() -> tuple[list[QuestionResult], dict[str, Any]]:
        with factory() as session:
            embeddings = EmbeddingService(
                create_embedding_provider(settings.embedding_settings()),
                settings.embedding_settings(),
            )
            pipeline = RagPipeline(
                session,
                project_id,
                embeddings,
                create_llm_provider(settings.llm_settings()),
                settings,
            )

            async def ask(question: str) -> Any:
                # Passage retrieval is evaluated on its own: graph facts are a separate layer.
                return await pipeline.answer(question, top_k=top_k, mode="SOURCE")

            return await evaluate(session, questions, ask, top_k)

    results, summary = asyncio.run(run())
    snapshot = {
        key: getattr(settings, key)
        for key in (
            "chunk_target_tokens",
            "chunk_max_tokens",
            "chunk_overlap_tokens",
            "rag_dense_k",
            "rag_lexical_k",
            "rag_rrf_k",
            "rag_max_chunks_per_section",
            "rag_min_dense_similarity",
            "rag_min_lexical_ratio",
            "rag_parent_lead_tokens",
            "rag_neighbor_chunks",
            "rag_max_rounds",
            "rag_claim_support_threshold",
            "embedding_model",
            "embedding_dimensions",
            "llm_model",
        )
    }
    return EvaluationRun(spec.get("name", "evaluation"), summary, results, snapshot, ingestion)
