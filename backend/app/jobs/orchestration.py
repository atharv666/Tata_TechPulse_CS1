"""Durable, observable execution of persisted pipeline jobs.

Design (this replaced a single long transaction per job, which crashed the worker whenever a job
failed inside a flush and could leave half-written data committed):

* **claim** - a short transaction leases the oldest runnable job (``RUNNING`` + ``locked_*``)
  and commits.
* **execute** - the handler runs in its *own* session. It commits whole units of work (a document, a
  batch of embeddings, one chunk's extraction) through ``JobContext.checkpoint``.
* **record** - success, retry or failure is written in a *fresh* transaction, so the outcome is
  stored even when the handler's session is unusable.
* **recover** - a job whose worker died (expired lease) is re-queued or failed by ``recover_stale``.

Handlers must be idempotent: retries and lease recovery can run a stage again.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.metrics import metrics
from app.models.enums import JobState
from app.models.schema import Job
from app.providers.contracts import ProviderError, ProviderTransientError
from app.repositories.jobs import JobRepository, utcnow

logger = logging.getLogger(__name__)

MAX_RETRY_DELAY_SECONDS = 300
BASE_RETRY_DELAY_SECONDS = 5


class RetryableJobError(RuntimeError):
    """A transient failure eligible for bounded retry."""

    safe_to_report = True


class JobCancelled(RuntimeError):
    """Raised inside a handler when cancellation was requested; the runner records CANCELLED."""


class JobPartialFailure(RuntimeError):
    """Signals completion with recoverable item-level failures recorded in job details."""

    safe_to_report = True

    def __init__(self, message: str, failures: list[dict[str, str]]) -> None:
        self.failures = failures
        super().__init__(message)


JobHandler = Callable[[Job, "JobContext"], object]


class JobContext:
    """What a handler may do: report progress, commit units of work, check cancellation, chain
    jobs."""

    def __init__(self, session: Session, job: Job, worker_id: str = "local") -> None:
        self.session = session
        self.job = job
        self.worker_id = worker_id
        self._repository = JobRepository(session)

    # -- observability -----------------------------------------------------------------------
    def progress(self, percent: int, message: str | None = None) -> None:
        if not 0 <= percent <= 100:
            raise ValueError("Job progress must be between 0 and 100.")
        details = dict(self.job.details)
        details["progress"] = percent
        if message:
            details["logs"] = self._with_log(details, "INFO", message)
        self.job.details = details

    def log(self, level: str, message: str) -> None:
        """Operational metadata only; callers must never pass document content."""
        details = dict(self.job.details)
        details["logs"] = self._with_log(details, level, message)
        self.job.details = details

    def partial_failure(self, stage: str, error_type: str, detail: str | None = None) -> None:
        details = dict(self.job.details)
        failures = list(details.get("partial_failures", []))
        entry = {"stage": stage, "error_type": error_type}
        if detail:
            entry["detail"] = detail[:200]
        failures.append(entry)
        details["partial_failures"] = failures[-200:]
        self.job.details = details

    def set_detail(self, key: str, value: Any) -> None:
        details = dict(self.job.details)
        details[key] = value
        self.job.details = details

    # -- durability --------------------------------------------------------------------------
    def checkpoint(self, percent: int | None = None, message: str | None = None) -> None:
        """Commit completed work, refresh the lease and honour a pending cancellation."""
        if percent is not None:
            self.progress(percent, message)
        elif message:
            self.log("INFO", message)
        self.job.locked_at = utcnow()
        self.session.commit()
        self.raise_if_cancelled()

    def cancelled(self) -> bool:
        return self._repository.is_cancel_requested(self.job.id)

    def raise_if_cancelled(self) -> None:
        if self.cancelled():
            raise JobCancelled()

    # -- chaining ----------------------------------------------------------------------------
    def enqueue_next(self, job_type: str, payload: dict[str, object], idempotency_key: str) -> Job:
        """Queue the next stage in the same transaction as the work that makes it runnable."""
        next_job = self._repository.enqueue(
            self.job.project_id, job_type, self.job.requested_by, payload, idempotency_key
        )
        details = dict(self.job.details)
        details["next_job_id"] = str(next_job.id)
        details["next_job_type"] = job_type
        self.job.details = details
        return next_job

    @staticmethod
    def _with_log(details: dict[str, Any], level: str, message: str) -> list[dict[str, str]]:
        logs = list(details.get("logs", []))
        logs.append({"level": level, "message": message[:512]})
        return logs[-100:]


@dataclass(frozen=True)
class JobRunResult:
    job_id: UUID
    job_type: str
    state: JobState
    attempt: int
    error_type: str | None = None


async def _invoke(handler: JobHandler, job: Job, context: JobContext) -> None:
    result = handler(job, context)
    if inspect.isawaitable(result):
        await result


def _retry_delay(attempt: int, hint: float | None) -> float:
    exponential = min(
        BASE_RETRY_DELAY_SECONDS * (2 ** max(attempt - 1, 0)), MAX_RETRY_DELAY_SECONDS
    )
    return float(min(max(exponential, hint or 0.0), MAX_RETRY_DELAY_SECONDS * 4))


class JobRunner:
    """Runs one job at a time; several runners (processes) may poll the same queue safely."""

    def __init__(
        self,
        session_factory: Callable[[], Session],
        handlers: dict[str, JobHandler],
        worker_id: str = "worker",
        lease_seconds: int = 900,
    ) -> None:
        self._factory = session_factory
        self._handlers = handlers
        self._worker_id = worker_id
        self._lease_seconds = lease_seconds

    # -- queue maintenance -------------------------------------------------------------------
    def recover_stale(self) -> int:
        with self._factory() as session:
            recovered = JobRepository(session).requeue_stale(self._lease_seconds)
            session.commit()
        if recovered:
            logger.warning("jobs_recovered_after_lease_expiry", extra={"count": len(recovered)})
        return len(recovered)

    # -- execution ---------------------------------------------------------------------------
    def run_once(self) -> JobRunResult | None:
        """Claim and execute at most one job. Never raises for a job-level failure."""
        with self._factory() as session:
            job = JobRepository(session).claim_next(self._worker_id)
            if job is None:
                session.rollback()
                return None
            job_id, job_type = job.id, job.job_type
            session.commit()
        return self._execute(job_id, job_type)

    def _execute(self, job_id: UUID, job_type: str) -> JobRunResult:
        session = self._factory()
        try:
            job = session.get(Job, job_id)
            if job is None:  # deleted while queued
                return JobRunResult(job_id, job_type, JobState.FAILED, 0, "JobMissing")
            context = JobContext(session, job, self._worker_id)
            handler = self._handlers.get(job_type)
            if handler is None:
                raise _PermanentFailure("No registered handler for job type.")
            try:
                context.raise_if_cancelled()
                asyncio.run(_invoke(handler, job, context))
            except JobPartialFailure as partial:
                for failure in partial.failures:
                    context.partial_failure(
                        failure.get("stage", job_type),
                        failure.get("error_type", "Error"),
                        failure.get("detail"),
                    )
            self._finish(session, job, JobState.COMPLETED, "Job completed")
            metrics.increment(f"jobs_completed_{job_type.lower()}")
            return JobRunResult(job.id, job_type, JobState.COMPLETED, _attempt(job))
        except JobCancelled:
            session.rollback()
            return self._record_terminal(
                job_id, job_type, JobState.CANCELLED, None, "Job cancelled"
            )
        except Exception as error:
            session.rollback()
            return self._record_error(job_id, job_type, error)
        finally:
            session.close()

    @staticmethod
    def _finish(session: Session, job: Job, state: JobState, message: str) -> None:
        details = dict(job.details)
        if state is JobState.COMPLETED:
            details["progress"] = 100
        details["logs"] = JobContext._with_log(details, "INFO", message)
        job.details = details
        job.state = state
        job.finished_at = utcnow()
        job.locked_by = None
        job.locked_at = None
        session.commit()

    # -- failure recording (always a fresh transaction) --------------------------------------
    def _record_terminal(
        self, job_id: UUID, job_type: str, state: JobState, error_type: str | None, message: str
    ) -> JobRunResult:
        with self._factory() as session:
            job = session.get(Job, job_id)
            attempt = 0
            if job is not None:
                attempt = _attempt(job)
                details = dict(job.details)
                if error_type:
                    details["failure"] = error_type
                details["logs"] = JobContext._with_log(
                    details, "ERROR" if state is JobState.FAILED else "INFO", message
                )
                job.details = details
                job.state = state
                job.finished_at = utcnow()
                job.locked_by = None
                job.locked_at = None
            session.commit()
        return JobRunResult(job_id, job_type, state, attempt, error_type)

    def _record_error(self, job_id: UUID, job_type: str, error: Exception) -> JobRunResult:
        error_type = type(error).__name__
        transient = isinstance(error, RetryableJobError | ProviderTransientError)
        hint = error.retry_after_seconds if isinstance(error, ProviderTransientError) else None
        safe = getattr(error, "safe_to_report", False) or isinstance(
            error, ProviderError | ValueError
        )
        message = f"{error_type}: {error}"[:300] if safe and str(error) else error_type
        with self._factory() as session:
            job = session.get(Job, job_id)
            if job is None:
                return JobRunResult(job_id, job_type, JobState.FAILED, 0, error_type)
            attempt = _attempt(job)
            max_attempts = int(job.details.get("max_attempts", 3))
            details = dict(job.details)
            if transient and attempt < max_attempts:
                delay = _retry_delay(attempt, hint)
                details["logs"] = JobContext._with_log(
                    details, "WARNING", f"Retry {attempt}/{max_attempts} in {delay:.0f}s: {message}"
                )
                details["last_error_type"] = error_type
                job.details = details
                job.state = JobState.PENDING
                job.run_after = utcnow() + timedelta(seconds=delay)
                state = JobState.PENDING
                metrics.increment(f"jobs_retried_{job_type.lower()}")
            else:
                details["logs"] = JobContext._with_log(details, "ERROR", f"Job failed: {message}")
                details["failure"] = error_type
                details["failure_message"] = message
                job.details = details
                job.state = JobState.FAILED
                job.finished_at = utcnow()
                state = JobState.FAILED
                metrics.increment(f"jobs_failed_{job_type.lower()}")
            job.locked_by = None
            job.locked_at = None
            session.commit()
        logger.warning("job_%s", state.value.lower(), extra={"job_id": job_id, "event": error_type})
        return JobRunResult(job_id, job_type, state, attempt, error_type)


class _PermanentFailure(RuntimeError):
    safe_to_report = True


def _attempt(job: Job) -> int:
    return int(job.details.get("attempt", 0))


__all__ = [
    "JobCancelled",
    "JobContext",
    "JobHandler",
    "JobPartialFailure",
    "JobRunResult",
    "JobRunner",
    "RetryableJobError",
]
