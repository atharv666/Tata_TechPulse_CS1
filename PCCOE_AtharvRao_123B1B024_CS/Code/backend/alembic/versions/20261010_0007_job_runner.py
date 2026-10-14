"""Durable job-runner columns: leases, retry scheduling, timing and a dedicated cancel flag.

Revision ID: 20261010_0007
Revises: 20260909_0006
Create Date: 2026-10-10
"""

import sqlalchemy as sa

from alembic import op

revision = "20261010_0007"
down_revision = "20260909_0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "jobs",
        sa.Column("cancel_requested", sa.Boolean(), server_default="false", nullable=False),
    )
    op.add_column("jobs", sa.Column("run_after", sa.DateTime(timezone=True), nullable=True))
    op.add_column("jobs", sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("jobs", sa.Column("locked_by", sa.String(length=128), nullable=True))
    op.add_column("jobs", sa.Column("started_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("jobs", sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True))
    # Carry over cancellations that were previously stored inside the JSON document.
    op.execute(
        "UPDATE jobs SET cancel_requested = true "
        "WHERE (details ->> 'cancellation_requested') = 'true'"
    )
    op.create_index("ix_jobs_queue", "jobs", ["state", "run_after", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_jobs_queue", table_name="jobs")
    for column in (
        "finished_at",
        "started_at",
        "locked_by",
        "locked_at",
        "run_after",
        "cancel_requested",
    ):
        op.drop_column("jobs", column)
