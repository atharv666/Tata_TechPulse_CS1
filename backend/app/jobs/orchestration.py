"""Retryable, observable execution state machine for persisted pipeline jobs."""

from __future__ import annotations

import inspect
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol
from uuid import UUID

from app.models.enums import JobState
from app.models.schema import Job


class RetryableJobError(RuntimeError):
    """A transient failure eligible for bounded retry."""


class JobPartialFailure(RuntimeError):
    """Signals completion with recoverable item-level failures recorded in job details."""

    def __init__(self, message: str, failures: list[dict[str, str]]) -> None:
        self.failures = failures
        super().__init__(message)


class JobStore(Protocol):
    def claim_next(self) -> Job | None: ...
    def request_cancellation(self, project_id: UUID, job_id: UUID) -> Job | None: ...


JobHandler = Callable[[Job, "JobContext"], object]


@dataclass
class JobContext:
    job: Job

    def progress(self, percent: int, message: str) -> None:
        if not 0 <= percent <= 100:
            raise ValueError("Job progress must be between 0 and 100.")
        details = dict(self.job.details)
        details["progress"] = percent
        self._log(details, "INFO", message)
        self.job.details = details

    def partial_failure(self, stage: str, error_type: str) -> None:
        details = dict(self.job.details)
        failures = list(details.get("partial_failures", []))
        failures.append({"stage": stage, "error_type": error_type})
        details["partial_failures"] = failures
        self.job.details = details

    def cancelled(self) -> bool:
        return bool(self.job.details.get("cancellation_requested", False))

    @staticmethod
    def _log(details: dict[str, Any], level: str, message: str) -> None:
        # Deliberately record operational metadata only; callers must never pass source content.
        logs = list(details.get("logs", []))
        logs.append({"level": level, "message": message[:512]})
        details["logs"] = logs[-100:]


class JobExecutor:
    """Executes one claimed job at a time; parallel workers safely claim different rows."""

    def __init__(self, store: JobStore, handlers: dict[str, JobHandler]) -> None:
        self._store = store
        self._handlers = handlers

    async def run_next(self) -> Job | None:
        job = self._store.claim_next()
        if job is None:
            return None
        context = JobContext(job)
        if context.cancelled():
            job.state = JobState.CANCELLED
            return job
        handler = self._handlers.get(job.job_type)
        if handler is None:
            self._fail(job, "No registered handler for job type.")
            return job
        try:
            result = handler(job, context)
            if inspect.isawaitable(result):
                await result
            if context.cancelled():
                job.state = JobState.CANCELLED
            else:
                context.progress(100, "Job completed")
                job.state = JobState.COMPLETED
        except JobPartialFailure as error:
            for failure in error.failures:
                context.partial_failure(failure["stage"], failure["error_type"])
            context.progress(100, "Job completed with partial failures")
            job.state = JobState.COMPLETED
        except RetryableJobError as error:
            details = dict(job.details)
            if int(details.get("attempt", 0)) < int(details.get("max_attempts", 3)):
                JobContext._log(details, "WARNING", f"Retry scheduled: {type(error).__name__}")
                details["last_error_type"] = type(error).__name__
                job.details = details
                job.state = JobState.PENDING
            else:
                self._fail(job, type(error).__name__)
        except Exception as error:
            self._fail(job, type(error).__name__)
        return job

    @staticmethod
    def _fail(job: Job, error_type: str) -> None:
        details = dict(job.details)
        JobContext._log(details, "ERROR", f"Job failed: {error_type}")
        details["failure"] = error_type
        job.details = details
        job.state = JobState.FAILED
