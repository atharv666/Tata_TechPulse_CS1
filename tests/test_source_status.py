"""Answers and the declared approval status of their source documents."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from app.core.config import get_settings
from app.db.session import get_session_factory
from app.models.schema import DocumentVersion
from app.providers.factory import create_embedding_provider
from app.retrieval.answer import RagPipeline
from app.retrieval.vector import EmbeddingService
from sqlalchemy import select

from tests.support.fakes import ScriptedLLM, installed_fakes
from tests.support.pipeline import V1, create_project, drain, real_runner, upload

pytestmark = pytest.mark.integration

ABS = (
    Path(__file__).resolve().parents[1]
    / "sample_data"
    / "hld"
    / "03_ABS_Subsystem_HLD.md"
)


@pytest.fixture
def project(clean_database):
    access = create_project("status")
    upload(access, "ABS_HLD.md", ABS.read_bytes())  # declares "Status: Approved"
    upload(access, "Brake_HLD.md", V1.read_bytes())  # declares no status
    with installed_fakes():
        drain(real_runner())
    return access


def ask(access, question: str, **overrides):
    settings = get_settings().model_copy(update=overrides)
    with installed_fakes(llm=ScriptedLLM()) as (llm, _):
        embeddings = EmbeddingService(
            create_embedding_provider(settings.embedding_settings()),
            settings.embedding_settings(),
        )
        with get_session_factory()() as session:
            pipeline = RagPipeline(
                session, access.project_id, embeddings, llm, settings
            )
            return asyncio.run(pipeline.answer(question, mode="SOURCE")).answer


def test_the_declared_status_is_extracted_and_shown_with_each_citation(project) -> None:
    with get_session_factory()() as session:
        statuses = {
            version.properties.get("title") or str(version.id): version.properties.get(
                "status"
            )
            for version in session.scalars(select(DocumentVersion))
        }
    assert sorted(str(value) for value in statuses.values()) == ["Approved", "None"]

    answer = ask(project, "What does AbsController require?")
    approved = [c for c in answer.citations if c.document_name == "ABS_HLD.md"]
    assert approved and {c.document_status for c in approved} == {"Approved"}


def test_citing_an_unapproved_document_adds_a_limitation_but_is_allowed_by_default(
    project,
) -> None:
    answer = ask(project, "What does BrakeController require?")

    assert answer.status == "GROUNDED"
    cited = {c.document_name: c.document_status for c in answer.citations}
    assert cited["Brake_HLD.md"] is None
    assert any(
        "not marked as approved (Brake_HLD.md)" in text for text in answer.limitations
    )


def test_with_approved_sources_required_only_approved_documents_ground_answers(
    project,
) -> None:
    allowed = ask(
        project, "What does AbsController require?", require_approved_sources=True
    )
    assert allowed.status == "GROUNDED"
    assert {c.document_name for c in allowed.citations} == {"ABS_HLD.md"}

    # a question about something only the unapproved document describes
    question = "ChassisControlDomain PART_OF BrakeController"
    open_scope = ask(project, question)
    assert "Brake_HLD.md" in {c.document_name for c in open_scope.citations}
    restricted = ask(project, question, require_approved_sources=True)
    assert "Brake_HLD.md" not in {c.document_name for c in restricted.citations}
    assert all(c.document_name == "ABS_HLD.md" for c in restricted.citations)


def test_when_nothing_is_approved_no_retrieval_happens_at_all(clean_database) -> None:
    access = create_project("none-approved")
    upload(access, "Brake_HLD.md", V1.read_bytes())
    with installed_fakes():
        drain(real_runner())

    answer = ask(
        access, "What does BrakeController require?", require_approved_sources=True
    )

    assert answer.status == "INSUFFICIENT_EVIDENCE"
    assert "No approved source document" in answer.summary
    assert answer.retrieval_trace["rounds"] == []
    assert any("declared status" in text for text in answer.limitations)
