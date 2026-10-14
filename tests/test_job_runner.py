"""The job runner against a real PostgreSQL database.

Regression coverage for the original worker defects: a failing job must never kill the worker, must
never leave the queue stuck behind a poison pill, and leases / retries / cancellation must work.
"""

from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

import pytest
from app.db.session import get_session_factory
from app.jobs.orchestration import JobContext, JobPartialFailure, JobRunner
from app.models.enums import JobState
from app.models.schema import Chunk, Job
from app.providers.contracts import ProviderRateLimitError
from app.repositories.jobs import JobRepository, utcnow

from tests.support.pipeline import create_project

pytestmark = pytest.mark.integration


def enqueue(
    project_id,
    job_type: str = "TEST",
    payload: dict | None = None,
    max_attempts: int = 3,
):
    with get_session_factory()() as session:
        job = JobRepository(session).enqueue(
            project_id, job_type, "alice", payload or {}, f"key:{uuid4()}", max_attempts
        )
        session.commit()
        return job.id


def load(job_id) -> Job:
    with get_session_factory()() as session:
        job = session.get(Job, job_id)
        assert job is not None
        session.expunge(job)
        return job


def runner_with(handler) -> JobRunner:
    return JobRunner(
        get_session_factory(), {"TEST": handler}, worker_id="t", lease_seconds=60
    )


def test_successful_job_is_committed_and_completed(clean_database) -> None:
    access = create_project()
    job_id = enqueue(access.project_id)

    def handler(job: Job, context: JobContext) -> None:
        context.set_detail("answer", 42)

    result = runner_with(handler).run_once()

    assert result is not None and result.state is JobState.COMPLETED
    stored = load(job_id)
    assert stored.state is JobState.COMPLETED and stored.details["answer"] == 42
    assert stored.details["progress"] == 100 and stored.finished_at is not None
    assert stored.locked_by is None


def test_empty_queue_returns_none(clean_database) -> None:
    assert runner_with(lambda job, context: None).run_once() is None


def test_failing_job_is_recorded_and_the_worker_keeps_going(clean_database) -> None:
    """The original crash: an exception raised after a failed flush killed the worker process."""
    access = create_project()
    first = enqueue(access.project_id, payload={"fail": True})
    second = enqueue(access.project_id, payload={"fail": False})

    def handler(job: Job, context: JobContext) -> None:
        if job.details["payload"]["fail"]:
            # A database error leaves the session unusable until rollback.
            context.session.add(
                Chunk(
                    project_id=job.project_id,
                    document_version_id=uuid4(),
                    section_id=uuid4(),
                    ordinal=1,
                    content="x",
                    token_count=1,
                )
            )
            context.session.flush()
        context.set_detail("ok", True)

    runner = runner_with(handler)
    outcomes = [runner.run_once(), runner.run_once()]  # neither call may raise

    assert [o.state for o in outcomes if o] == [JobState.FAILED, JobState.COMPLETED]
    failed = load(first)
    assert (
        failed.state is JobState.FAILED
        and failed.details["failure"] == "IntegrityError"
    )
    assert load(second).state is JobState.COMPLETED
    assert runner.run_once() is None  # the failed job is not re-queued: no poison pill


def test_transient_failure_is_rescheduled_not_failed(clean_database) -> None:
    access = create_project()
    job_id = enqueue(access.project_id)

    def handler(job: Job, context: JobContext) -> None:
        raise ProviderRateLimitError("rate limited", retry_after_seconds=120)

    runner = runner_with(handler)
    result = runner.run_once()

    assert result is not None and result.state is JobState.PENDING
    stored = load(job_id)
    assert stored.state is JobState.PENDING and stored.details["attempt"] == 1
    assert stored.run_after is not None and stored.run_after > utcnow() + timedelta(
        seconds=100
    )
    assert runner.run_once() is None  # not claimable before run_after

    with get_session_factory()() as session:
        session.get(Job, job_id).run_after = utcnow() - timedelta(seconds=1)  # type: ignore[union-attr]
        session.commit()
    again = runner.run_once()
    assert again is not None and load(job_id).details["attempt"] == 2


def test_attempts_are_bounded(clean_database) -> None:
    access = create_project()
    job_id = enqueue(access.project_id, max_attempts=2)

    def handler(job: Job, context: JobContext) -> None:
        raise ProviderRateLimitError("rate limited")

    runner = runner_with(handler)
    for _ in range(2):
        runner.run_once()
        with get_session_factory()() as session:
            row = session.get(Job, job_id)
            if row is not None and row.state is JobState.PENDING:
                row.run_after = None
                session.commit()

    stored = load(job_id)
    assert stored.state is JobState.FAILED
    assert stored.details["failure"] == "ProviderRateLimitError"


def test_expired_lease_is_recovered_and_exhausted_attempts_fail(clean_database) -> None:
    access = create_project()
    recoverable = enqueue(access.project_id)
    exhausted = enqueue(access.project_id, max_attempts=1)
    with get_session_factory()() as session:
        for job_id in (recoverable, exhausted):
            job = session.get(Job, job_id)
            assert job is not None
            job.state = JobState.RUNNING
            job.locked_at = utcnow() - timedelta(hours=1)
            job.details = {**job.details, "attempt": 1}
        session.commit()

    assert runner_with(lambda job, context: None).recover_stale() == 2

    assert load(recoverable).state is JobState.PENDING
    assert load(exhausted).state is JobState.FAILED
    assert load(exhausted).details["failure"] == "LeaseExpired"


def test_cancellation_stops_a_running_job_at_the_next_checkpoint(
    clean_database,
) -> None:
    access = create_project()
    job_id = enqueue(access.project_id)

    def handler(job: Job, context: JobContext) -> None:
        context.set_detail("before", True)
        context.checkpoint(10, "unit one committed")
        # Another process (the API) requests cancellation while the job runs.
        with get_session_factory()() as other:
            JobRepository(other).request_cancellation(job.project_id, job.id)
            other.commit()
        context.checkpoint(50, "unit two")  # must raise JobCancelled
        context.set_detail("after", True)  # never reached

    result = runner_with(handler).run_once()

    assert result is not None and result.state is JobState.CANCELLED
    stored = load(job_id)
    assert stored.state is JobState.CANCELLED
    assert stored.details["before"] is True and "after" not in stored.details


def test_cancelling_a_pending_job_prevents_it_from_running(clean_database) -> None:
    access = create_project()
    job_id = enqueue(access.project_id)
    with get_session_factory()() as session:
        JobRepository(session).request_cancellation(access.project_id, job_id)
        session.commit()

    assert runner_with(lambda job, context: None).run_once() is None
    assert load(job_id).state is JobState.CANCELLED


def test_partial_failure_completes_with_recorded_failures(clean_database) -> None:
    access = create_project()
    job_id = enqueue(access.project_id)

    def handler(job: Job, context: JobContext) -> None:
        raise JobPartialFailure(
            "some items failed", [{"stage": "S", "error_type": "Boom"}]
        )

    result = runner_with(handler).run_once()

    assert result is not None and result.state is JobState.COMPLETED
    assert load(job_id).details["partial_failures"][0]["error_type"] == "Boom"


def test_unknown_job_type_fails_permanently(clean_database) -> None:
    access = create_project()
    job_id = enqueue(access.project_id, job_type="MYSTERY")

    result = runner_with(lambda job, context: None).run_once()

    assert result is not None and result.state is JobState.FAILED
    assert "No registered handler" in load(job_id).details["failure_message"]


def test_two_runners_never_claim_the_same_job(clean_database) -> None:
    access = create_project()
    enqueue(access.project_id)
    with get_session_factory()() as first, get_session_factory()() as second:
        claimed = JobRepository(first).claim_next("w1")
        assert claimed is not None
        # ``first`` still holds the row lock (uncommitted): SKIP LOCKED means nothing is left.
        assert JobRepository(second).claim_next("w2") is None
        first.commit()
        assert (
            JobRepository(second).claim_next("w2") is None
        )  # now RUNNING, not PENDING
