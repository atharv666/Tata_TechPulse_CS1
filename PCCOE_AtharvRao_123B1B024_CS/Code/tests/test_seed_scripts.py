"""The demo seed/build scripts drive the real pipeline and never fabricate facts."""

from __future__ import annotations

import pytest
from app.db.session import get_session_factory
from app.models.enums import ValidationState
from app.models.schema import Document, DocumentVersion, Entity, Job, Relationship
from sqlalchemy import func, select

from scripts.build_graph import run_graph_build
from scripts.seed_demo_data import DEMO_PROJECT_NAME, seed_demo_data
from tests.support.fakes import installed_fakes

pytestmark = pytest.mark.integration


def test_seeding_only_queues_uploads_and_creates_no_facts(clean_database) -> None:
    result = seed_demo_data(run_worker=False)

    assert result.queued_jobs == 3 and result.processed_jobs == 0
    assert result.states == {"DOCUMENT_INGESTION:PENDING": 3}
    with get_session_factory()() as session:
        assert session.scalar(select(func.count()).select_from(Entity)) == 0
        assert session.scalar(select(func.count()).select_from(Relationship)) == 0


def test_seeding_is_repeatable_without_duplicates(clean_database) -> None:
    first = seed_demo_data(run_worker=False)
    again = seed_demo_data(run_worker=False)
    assert again.project_id == first.project_id
    with get_session_factory()() as session:
        assert (
            session.scalar(select(func.count()).select_from(Job)) == 3
        )  # same uploads: same jobs


def test_running_the_worker_builds_a_pending_graph_with_two_revisions(
    clean_database,
) -> None:
    with installed_fakes():
        result = seed_demo_data(run_worker=True)

    assert result.processed_jobs >= 15
    assert not any(state.endswith(":FAILED") for state in result.states)
    with get_session_factory()() as session:
        assert session.scalar(select(func.count()).select_from(Document)) == 2
        assert session.scalar(select(func.count()).select_from(DocumentVersion)) == 3
        states = set(session.scalars(select(Entity.validation_state)))
        # nothing is ever verified by the pipeline; only a person can do that
        assert states <= {ValidationState.PENDING, ValidationState.REJECTED}
        assert session.scalar(select(func.count()).select_from(Relationship)) > 5


def test_a_manual_build_is_idempotent_and_reports_what_it_did(clean_database) -> None:
    with installed_fakes():
        seed_demo_data(run_worker=True)
        outcome = run_graph_build(DEMO_PROJECT_NAME, run_worker=True)

    assert outcome["state"] == "COMPLETED"
    assert outcome["build"]["findings_opened"] == 0  # type: ignore[index]
    assert outcome["resolution"]["rule_merges"] == 0  # type: ignore[index]


def test_an_unknown_project_is_reported_not_invented(clean_database) -> None:
    with pytest.raises(LookupError, match="does not exist"):
        run_graph_build("no such project")
