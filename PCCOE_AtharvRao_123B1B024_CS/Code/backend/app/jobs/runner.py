"""Worker process: poll the PostgreSQL queue and run jobs, forever and without crashing.

``python -m app.jobs.runner`` (or ``python -m worker_runner.main``) is the production entry point.
"""

from __future__ import annotations

import logging
import os
import signal
import socket
import threading
import time
from collections.abc import Callable

from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.logging import configure_logging
from app.db.session import check_database, get_session_factory
from app.jobs.orchestration import JobRunner
from app.jobs.pipeline import PipelineHandlers

logger = logging.getLogger(__name__)

STALE_CHECK_INTERVAL_SECONDS = 30.0


def default_worker_id() -> str:
    return f"{socket.gethostname()}:{os.getpid()}"


def build_runner(
    settings: Settings | None = None,
    session_factory: Callable[[], Session] | None = None,
    worker_id: str | None = None,
) -> JobRunner:
    settings = settings or get_settings()
    return JobRunner(
        session_factory or get_session_factory(),
        PipelineHandlers(settings).handlers(),
        worker_id=worker_id or default_worker_id(),
        lease_seconds=settings.worker_lease_seconds,
    )


def run_forever(
    runner: JobRunner,
    stop: threading.Event,
    poll_seconds: float,
    stale_check_seconds: float = STALE_CHECK_INTERVAL_SECONDS,
) -> None:
    """Main loop. A failure in one iteration is logged and never terminates the worker."""
    next_stale_check = 0.0
    while not stop.is_set():
        try:
            now = time.monotonic()
            if now >= next_stale_check:
                runner.recover_stale()
                next_stale_check = now + stale_check_seconds
            result = runner.run_once()
        except Exception:
            logger.exception("worker_iteration_failed")
            stop.wait(poll_seconds)
            continue
        if result is None:
            stop.wait(poll_seconds)
        else:
            logger.info(
                "job_finished",
                extra={"job_id": result.job_id, "event": f"{result.job_type}:{result.state.value}"},
            )


def wait_for_database(stop: threading.Event, poll_seconds: float) -> bool:
    """Block until the schema is usable (extensions present, embedding width matches)."""
    while not stop.is_set():
        try:
            check_database()
            return True
        except Exception as error:
            logger.warning("worker_waiting_for_database", extra={"event": type(error).__name__})
            stop.wait(max(poll_seconds, 2.0))
    return False


def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    stop = threading.Event()

    def handle_signal(signum: int, _: object) -> None:
        logger.info("worker_stopping", extra={"event": f"signal {signum}"})
        stop.set()

    signal.signal(signal.SIGINT, handle_signal)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, handle_signal)
    logger.info("worker_started")
    if wait_for_database(stop, settings.worker_poll_seconds):
        run_forever(build_runner(settings), stop, settings.worker_poll_seconds)
    logger.info("worker_stopped")


if __name__ == "__main__":
    main()
