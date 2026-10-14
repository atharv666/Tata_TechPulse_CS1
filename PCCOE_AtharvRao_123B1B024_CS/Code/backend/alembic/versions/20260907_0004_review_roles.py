"""Add review-specific project membership roles.

Revision ID: 20260907_0004
Revises: 20260907_0003
Create Date: 2026-09-07
"""

from alembic import op

revision = "20260907_0004"
down_revision = "20260907_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Extend the native membership enum without rewriting existing memberships."""
    op.execute("ALTER TYPE membership_role ADD VALUE IF NOT EXISTS 'ENGINEER'")
    op.execute("ALTER TYPE membership_role ADD VALUE IF NOT EXISTS 'REVIEWER'")
    op.execute("ALTER TYPE membership_role ADD VALUE IF NOT EXISTS 'ADMIN'")


def downgrade() -> None:
    """PostgreSQL enum values cannot be safely removed while preserving member history."""
