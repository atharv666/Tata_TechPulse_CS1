"""Durable PostgreSQL-backed queue operations with project-scoped idempotency."""

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.enums import JobState
from app.models.schema import Job


class JobRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def enqueue(
        self,
        project_id: UUID,
        job_type: str,
        actor_id: str,
        payload: dict[str, Any],
        idempotency_key: str,
    ) -> Job:
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
        from uuid import uuid4

        job = Job(
            id=uuid4(),
            project_id=project_id,
            job_type=job_type,
            state=JobState.PENDING,
            requested_by=actor_id,
            details={
                "idempotency_key": idempotency_key,
                "payload": payload,
                "attempt": 0,
                "max_attempts": 3,
                "progress": 0,
                "logs": [],
                "partial_failures": [],
                "cancellation_requested": False,
            },
        )
        self.session.add(job)
        self.session.flush()
        return job

    def claim_next(self) -> Job | None:
        job = self.session.scalar(
            select(Job)
            .where(Job.state == JobState.PENDING)
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
        return job

    def request_cancellation(self, project_id: UUID, job_id: UUID) -> Job | None:
        job = self.session.scalar(select(Job).where(Job.id == job_id, Job.project_id == project_id))
        if job is None:
            return None
        if job.state is JobState.PENDING:
            job.state = JobState.CANCELLED
        elif job.state is JobState.RUNNING:
            details = dict(job.details)
            details["cancellation_requested"] = True
            job.details = details
        return job
