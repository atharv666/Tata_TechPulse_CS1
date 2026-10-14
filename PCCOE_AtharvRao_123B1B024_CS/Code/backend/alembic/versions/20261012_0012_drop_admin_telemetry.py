"""Remove the admin telemetry tables (the admin view was removed).

Nothing in the application reads or writes them any more. ``IF EXISTS`` keeps this safe for any
database state.

Revision ID: 20261012_0012
Revises: 20261012_0011
Create Date: 2026-10-14
"""

from alembic import op

revision = "20261012_0012"
down_revision = "20261012_0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for table in ("provider_calls", "rag_traces", "usage_events"):
        op.execute(f"DROP TABLE IF EXISTS {table}")


def downgrade() -> None:
    """Intentionally empty: the dropped tables belonged to a removed feature."""
