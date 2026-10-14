"""Durable PostgreSQL-backed queue operations with project-scoped idempotency."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import or_, select, update
from sqlalchemy.orm import Session

from app.models.enums import JobState
from app.models.schema import Job

DEFAULT_MAX_ATTEMPTS = 3


def utcnow() -> datetime:
    return datetime.now(UTC)


class JobRepository:
    """All queue state transitions. Callers own the transaction boundary (commit/rollback)."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def enqueue(
        self,
        project_id: UUID,
        job_type: str,
        actor_id: str,
        payload: dict[str, Any],
        idempotency_key: str,
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    ) -> Job:
        """Queue a job unless an identical one is already waiting or running."""
        existing = self.session.scalar(
            select(Job).where(
                Job.project_id == project_id,
                Job.job_type == job_type,
                Job.state.in_((JobState.PENDING, JobState.RUNNING)),
                Job.details["idempotency_key"].as_string() == idempotency_key,
            )
        )
        if existing is not None:
            return existing
        job = Job(
            project_id=project_id,
            job_type=job_type,
            state=JobState.PENDING,
            requested_by=actor_id,
            details={
                "idempotency_key": idempotency_key,
                "payload": payload,
                "attempt": 0,
                "max_attempts": max_attempts,
                "progress": 0,
                "logs": [],
                "partial_failures": [],
            },
        )
        self.session.add(job)
        self.session.flush()
        return job

    def claim_next(self, worker_id: str) -> Job | None:
        """Lease the oldest runnable job. ``SKIP LOCKED`` lets several workers claim safely.

        The caller must commit straight away: the lease (``RUNNING`` + ``locked_*``) is what keeps
        other workers away, so the row lock is not held for the lifetime of the job.
        """
        now = utcnow()
        job = self.session.scalar(
            select(Job)
            .where(
                Job.state == JobState.PENDING,
                or_(Job.run_after.is_(None), Job.run_after <= now),
            )
            .order_by(Job.created_at, Job.id)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if job is None:
            return None
        details = dict(job.details)
        details["attempt"] = int(details.get("attempt", 0)) + 1
        details["progress"] = 0
        job.details = details
        job.state = JobState.RUNNING
        job.locked_by = worker_id
        job.locked_at = now
        job.started_at = now
        job.run_after = None
        return job

    def requeue_stale(self, lease_seconds: int) -> list[Job]:
        """Recover jobs whose worker died: back to PENDING, or FAILED once attempts are
        exhausted."""
        threshold = utcnow() - timedelta(seconds=lease_seconds)
        stale = list(
            self.session.scalars(
                select(Job)
                .where(Job.state == JobState.RUNNING, Job.locked_at < threshold)
                .with_for_update(skip_locked=True)
            )
        )
        for job in stale:
            details = dict(job.details)
            logs = list(details.get("logs", []))
            if int(details.get("attempt", 0)) >= int(
                details.get("max_attempts", DEFAULT_MAX_ATTEMPTS)
            ):
                job.state = JobState.FAILED
                job.finished_at = utcnow()
                details["failure"] = "LeaseExpired"
                logs.append(
                    {"level": "ERROR", "message": "Worker lease expired; attempts exhausted."}
                )
            else:
                job.state = JobState.PENDING
                logs.append({"level": "WARNING", "message": "Worker lease expired; job re-queued."})
            details["logs"] = logs[-100:]
            job.details = details
            job.locked_by = None
            job.locked_at = None
        return stale

    def request_cancellation(self, project_id: UUID, job_id: UUID) -> Job | None:
        """Cancel a waiting job outright; flag a running job so its handler stops at the next
        checkpoint."""
        job = self.session.scalar(select(Job).where(Job.id == job_id, Job.project_id == project_id))
        if job is None:
            return None
        if job.state is JobState.PENDING:
            job.state = JobState.CANCELLED
            job.finished_at = utcnow()
        elif job.state is JobState.RUNNING:
            # A single-column UPDATE: it cannot be lost when the worker rewrites ``details``.
            self.session.execute(update(Job).where(Job.id == job_id).values(cancel_requested=True))
            job.cancel_requested = True
        return job

    def is_cancel_requested(self, job_id: UUID) -> bool:
        """Read the committed flag directly (bypasses the identity map)."""
        return bool(self.session.scalar(select(Job.cancel_requested).where(Job.id == job_id)))
