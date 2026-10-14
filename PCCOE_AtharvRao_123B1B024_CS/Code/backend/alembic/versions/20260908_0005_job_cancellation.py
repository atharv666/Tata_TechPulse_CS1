"""Add durable cancellation state for pipeline jobs.

Revision ID: 20260908_0005
Revises: 20260907_0004
Create Date: 2026-09-08
"""

from alembic import op

revision = "20260908_0005"
down_revision = "20260907_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TYPE job_state ADD VALUE IF NOT EXISTS 'CANCELLED'")


def downgrade() -> None:
    """PostgreSQL enum values are retained to preserve historical job states."""
