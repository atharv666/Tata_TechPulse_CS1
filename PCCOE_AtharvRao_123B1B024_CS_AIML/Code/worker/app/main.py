"""Controlled single-concurrency worker polling the PostgreSQL-backed durable queue."""

import asyncio
import logging
import time

from app.core.config import get_settings
from app.db.session import get_session_factory
from app.jobs.orchestration import JobExecutor
from app.jobs.pipeline import PipelineHandlers
from app.repositories.jobs import JobRepository


def main() -> None:
    """Claim one job at a time; multiple worker processes use SKIP LOCKED safely."""
    logging.basicConfig(level=logging.INFO)
    settings = get_settings()
    logger = logging.getLogger(__name__)
    logger.info("worker_started")
    while True:
        with get_session_factory()() as session:
            with session.begin():
                executor = JobExecutor(JobRepository(session), PipelineHandlers(session, settings).handlers())
                job = asyncio.run(executor.run_next())
        if job is None:
            time.sleep(settings.worker_poll_seconds)


if __name__ == "__main__":
    main()
