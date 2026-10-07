"""Controlled single-concurrency worker entry point."""

import asyncio
import logging
import sys
import time
from pathlib import Path

# The local worker is a separate process, while the shared application package
# is kept in ../backend. Docker supplies PYTHONPATH; mirror that for local use.
BACKEND_DIRECTORY = Path(__file__).resolve().parents[2] / "backend"
if str(BACKEND_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIRECTORY))

from app.core.config import get_settings
from app.db.session import get_session_factory
from app.jobs.orchestration import JobExecutor
from app.jobs.pipeline import PipelineHandlers
from app.repositories.jobs import JobRepository


def main() -> None:
    settings = get_settings()
    logger = logging.getLogger(__name__)
    logging.basicConfig(level=settings.log_level)
    logger.info("worker_started")
    while True:
        with get_session_factory()() as session, session.begin():
            executor = JobExecutor(
                JobRepository(session),
                PipelineHandlers(session, settings).handlers(),
            )
            job = asyncio.run(executor.run_next())
        if job is None:
            time.sleep(settings.worker_poll_seconds)


if __name__ == "__main__":
    main()
