"""Helpers that drive the real application services and the real job runner."""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

from app.api.dependencies import CurrentUser, ProjectAccess
from app.core.config import get_settings
from app.db.session import get_session_factory
from app.jobs.orchestration import JobRunner, JobRunResult
from app.jobs.pipeline import PipelineHandlers
from app.models.enums import JobState, MembershipRole
from app.schemas.api import ProjectCreate
from app.services.api import MvpApiService

SAMPLE_DIRECTORY = Path(__file__).resolve().parents[2] / "sample_data" / "hld"
V1 = SAMPLE_DIRECTORY / "01_BrakeController_HLD_v1.md"
V2 = SAMPLE_DIRECTORY / "02_BrakeController_HLD_v2.md"


def create_project(name: str = "pipeline-test", user: str = "alice") -> ProjectAccess:
    with get_session_factory()() as session:
        project = MvpApiService(session, CurrentUser(user)).create_project(
            ProjectCreate(name=name, description="test")
        )
        session.commit()
        return ProjectAccess(project.id, user, MembershipRole.ADMIN)


def upload(
    access: ProjectAccess, filename: str, content: bytes, media: str = "text/markdown"
) -> UUID:
    with get_session_factory()() as session:
        job = MvpApiService(
            session, CurrentUser(access.user_id)
        ).upload_document_content(access, filename, media, content)
        session.commit()
        return job.id


def real_runner(**setting_overrides: object) -> JobRunner:
    """The production handler set bound to the production session factory."""
    settings = get_settings()
    if setting_overrides:
        settings = settings.model_copy(update=setting_overrides)
    return JobRunner(
        get_session_factory(),
        PipelineHandlers(settings).handlers(),
        worker_id="test-worker",
    )


def drain(runner: JobRunner, limit: int = 40) -> list[JobRunResult]:
    """Run jobs until the queue is empty (jobs scheduled for later are not claimed)."""
    results: list[JobRunResult] = []
    for _ in range(limit):
        result = runner.run_once()
        if result is None:
            return results
        results.append(result)
    raise AssertionError(f"queue did not drain within {limit} jobs: {results[-3:]}")


def states(results: list[JobRunResult]) -> list[tuple[str, str]]:
    return [(item.job_type, item.state.value) for item in results]


def all_completed(results: list[JobRunResult]) -> bool:
    return all(item.state is JobState.COMPLETED for item in results)
