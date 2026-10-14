"""OCR support: per-project page cache and the OCR_TEXT evidence classification.

Revision ID: 20261010_0009
Revises: 20261010_0008
Create Date: 2026-10-10
"""

import sqlalchemy as sa

from alembic import op

revision = "20261010_0009"
down_revision = "20261010_0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ocr_cache",
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("cache_key", sa.String(length=255), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_ocr_cache_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ocr_cache")),
        sa.UniqueConstraint("project_id", "cache_key", name="project_ocr_cache_key"),
    )
    op.create_index(op.f("ix_ocr_cache_project_id"), "ocr_cache", ["project_id"], unique=False)
    op.execute("ALTER TYPE entity_source_classification ADD VALUE IF NOT EXISTS 'OCR_TEXT'")
    op.execute("ALTER TYPE relationship_source_classification ADD VALUE IF NOT EXISTS 'OCR_TEXT'")


def downgrade() -> None:
    op.drop_index(op.f("ix_ocr_cache_project_id"), table_name="ocr_cache")
    op.drop_table("ocr_cache")
    # PostgreSQL cannot drop enum values; OCR_TEXT is retained.
