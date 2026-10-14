"""Admin telemetry tables (superseded: dropped again by 20261012_0012).

The admin view these tables served was removed. The migration stays in the history because some
databases were upgraded to it; revision 0012 removes the tables.

Revision ID: 20261012_0011
Revises: 20261011_0010
Create Date: 2026-10-12
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20261012_0011"
down_revision = "20261011_0010"
branch_labels = None
depends_on = None

JSONB = postgresql.JSONB(astext_type=sa.Text())
NOW = sa.text("now()")


def _created_at() -> sa.Column:  # type: ignore[type-arg]
    return sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False)


def upgrade() -> None:
    op.create_table(
        "usage_events",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.String(length=255), nullable=False),
        sa.Column("event_type", sa.String(length=32), nullable=False),
        sa.Column("details", JSONB, nullable=False),
        _created_at(),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_usage_events_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_usage_events")),
    )
    op.create_table(
        "rag_traces",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.String(length=255), nullable=False),
        sa.Column("mode", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("rounds", sa.Integer(), nullable=False),
        sa.Column("graph_facts", sa.Integer(), nullable=False),
        sa.Column("claims", sa.Integer(), nullable=False),
        sa.Column("dropped_claims", sa.Integer(), nullable=False),
        sa.Column("citations", sa.Integer(), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("groundedness", sa.Numeric(4, 3), nullable=True),
        sa.Column("query_chars", sa.Integer(), nullable=False),
        sa.Column("query_hash", sa.String(length=16), nullable=False),
        sa.Column("trace", JSONB, nullable=False),
        _created_at(),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_rag_traces_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_rag_traces")),
    )
    op.create_table(
        "provider_calls",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=True),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("model", sa.String(length=255), nullable=False),
        sa.Column("purpose", sa.String(length=32), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("success", sa.Boolean(), nullable=False),
        sa.Column("error_type", sa.String(length=64), nullable=True),
        sa.Column("items", sa.Integer(), nullable=False),
        _created_at(),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_provider_calls_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_provider_calls")),
    )


def downgrade() -> None:
    op.drop_table("provider_calls")
    op.drop_table("rag_traces")
    op.drop_table("usage_events")
