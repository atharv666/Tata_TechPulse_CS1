"""Load the synthetic sample HLD documents into a demo project through the real pipeline.

    python scripts/seed_demo_data.py                  # create the project, queue the uploads
    python scripts/seed_demo_data.py --run-worker     # ... and process the queue in this process

What it does *not* do: it never writes entities, relationships or review decisions directly, and it
never marks anything verified. The uploads go through the same service as the API, so the worker
(or ``--run-worker``) parses, embeds, extracts, resolves and builds exactly as in production, with
the providers configured in ``.env``. Everything it produces starts as PENDING.

The database schema must already exist: run ``alembic upgrade head`` first (the script does not
create tables).
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

DEMO_PROJECT_NAME = "AUTOSAR_Demo_Project"
DEMO_USER = "engineering-user"
SAMPLE_DIRECTORY = ROOT / "sample_data" / "hld"
#: Revision 1 must be uploaded before revision 2 (both are versions of one document).
UPLOAD_ORDER = (
    ("BrakeController_HLD.md", "01_BrakeController_HLD_v1.md"),
    ("BrakeController_HLD.md", "02_BrakeController_HLD_v2.md"),
    ("ABS_Subsystem_HLD.md", "03_ABS_Subsystem_HLD.md"),
)


@dataclass(frozen=True)
class SeedResult:
    project_id: str
    queued_jobs: int
    processed_jobs: int
    states: dict[str, int]


def seed_demo_data(run_worker: bool = False, max_jobs: int = 200) -> SeedResult:
    """Create the demo project and queue (or process) the sample uploads. Needs a real database."""
    from app.api.dependencies import CurrentUser, ProjectAccess
    from app.core.config import get_settings
    from app.db.session import get_session_factory
    from app.jobs.orchestration import JobRunner
    from app.jobs.pipeline import PipelineHandlers
    from app.models.enums import MembershipRole
    from app.models.schema import Job, Project
    from app.schemas.api import ProjectCreate
    from app.services.api import MvpApiService
    from sqlalchemy import func, select

    factory = get_session_factory()
    queued = 0
    with factory() as session:
        project = session.scalar(
            select(Project).where(Project.name == DEMO_PROJECT_NAME)
        )
        service = MvpApiService(session, CurrentUser(DEMO_USER))
        if project is None:
            project = service.create_project(
                ProjectCreate(
                    name=DEMO_PROJECT_NAME,
                    description="Synthetic AUTOSAR architecture demo (no confidential data).",
                )
            )
            session.flush()
        access = ProjectAccess(project.id, DEMO_USER, MembershipRole.ADMIN)
        for name, filename in UPLOAD_ORDER:
            path = SAMPLE_DIRECTORY / filename
            try:
                service.upload_document_content(
                    access, name, "text/markdown", path.read_bytes()
                )
                session.flush()
                queued += 1
            except (
                Exception
            ) as error:  # an identical upload is already queued or ingested
                print(f"  skipped {filename}: {error}")
        session.commit()
        project_id = project.id

    processed = 0
    if run_worker:
        runner = JobRunner(
            factory,
            PipelineHandlers(get_settings()).handlers(),
            worker_id="seed-script",
        )
        while processed < max_jobs and runner.run_once() is not None:
            processed += 1

    with factory() as session:
        states = {
            f"{job_type}:{state.value}": int(total)
            for job_type, state, total in session.execute(
                select(Job.job_type, Job.state, func.count(Job.id))
                .where(Job.project_id == project_id)
                .group_by(Job.job_type, Job.state)
            )
        }
    return SeedResult(str(project_id), queued, processed, states)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument(
        "--run-worker",
        action="store_true",
        help="process the queued jobs here instead of waiting for the worker service",
    )
    args = parser.parse_args()
    try:
        result = seed_demo_data(run_worker=args.run_worker)
    except Exception as error:  # report plainly; never pretend a seed happened
        print(f"Seeding failed: {type(error).__name__}: {error}", file=sys.stderr)
        print(
            "Is DATABASE_URL set and the schema migrated (alembic upgrade head)?",
            file=sys.stderr,
        )
        return 1
    print(f"Project {DEMO_PROJECT_NAME} ({result.project_id})")
    print(
        f"  uploads queued: {result.queued_jobs}; jobs processed here: {result.processed_jobs}"
    )
    for state, total in sorted(result.states.items()):
        print(f"  {state}: {total}")
    if not args.run_worker:
        print("Start the worker (docker compose up worker) to process the queue.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
