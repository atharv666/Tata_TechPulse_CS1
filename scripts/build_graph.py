"""Queue an explicit knowledge-graph (re)build for a project, optionally running it here.

    python scripts/build_graph.py                       # demo project, queue only
    python scripts/build_graph.py --project NAME --run-worker

A build resolves duplicate entity names, binds extracted relationship statements to canonical
entities, validates facts and refreshes the findings. It is idempotent and never changes a
human-reviewed fact. Asking a question never triggers it.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

DEFAULT_PROJECT = "AUTOSAR_Demo_Project"


def run_graph_build(
    project_name: str = DEFAULT_PROJECT, run_worker: bool = False
) -> dict[str, object]:
    from app.api.dependencies import CurrentUser, ProjectAccess
    from app.core.config import get_settings
    from app.db.session import get_session_factory
    from app.jobs.orchestration import JobRunner
    from app.jobs.pipeline import PipelineHandlers
    from app.models.enums import MembershipRole
    from app.models.schema import Job, Project
    from app.services.api import MvpApiService
    from sqlalchemy import select

    factory = get_session_factory()
    with factory() as session:
        project = session.scalar(select(Project).where(Project.name == project_name))
        if project is None:
            raise LookupError(
                f"Project '{project_name}' does not exist (run seed_demo_data.py?)."
            )
        access = ProjectAccess(project.id, "engineering-user", MembershipRole.ADMIN)
        job = MvpApiService(session, CurrentUser(access.user_id)).graph_build(access)
        session.commit()
        job_id = job.id
    if run_worker:
        runner = JobRunner(
            factory,
            PipelineHandlers(get_settings()).handlers(),
            worker_id="build-script",
        )
        while runner.run_once() is not None:
            pass
    with factory() as session:
        finished = session.get(Job, job_id)
        details = dict(finished.details) if finished is not None else {}
        return {
            "job_id": str(job_id),
            "state": finished.state.value if finished is not None else "UNKNOWN",
            "resolution": details.get("resolution"),
            "build": details.get("build"),
        }


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--project", default=DEFAULT_PROJECT)
    parser.add_argument("--run-worker", action="store_true")
    args = parser.parse_args()
    try:
        outcome = run_graph_build(args.project, args.run_worker)
    except Exception as error:
        print(f"Graph build failed: {type(error).__name__}: {error}", file=sys.stderr)
        return 1
    for key, value in outcome.items():
        print(f"{key}: {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
