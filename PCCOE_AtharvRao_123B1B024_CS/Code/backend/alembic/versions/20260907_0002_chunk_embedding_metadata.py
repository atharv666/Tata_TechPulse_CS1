"""Add embedding identity metadata to chunks.

Revision ID: 20260907_0002
Revises: 20260907_0001
Create Date: 2026-09-07
"""

from alembic import op

revision = "20260907_0002"
down_revision = "20260907_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Store model/version identity with every vector for compatible re-embedding."""
    op.execute("ALTER TABLE chunks ADD COLUMN IF NOT EXISTS embedding_model VARCHAR(255)")
    op.execute("ALTER TABLE chunks ADD COLUMN IF NOT EXISTS embedding_model_version VARCHAR(128)")
    op.execute("ALTER TABLE chunks ADD COLUMN IF NOT EXISTS embedded_at TIMESTAMP WITH TIME ZONE")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_chunks_embedding_identity "
        "ON chunks (project_id, document_version_id, embedding_model, embedding_model_version)"
    )


def downgrade() -> None:
    """Remove only Phase 5 metadata and its supporting index."""
    op.execute("DROP INDEX IF EXISTS ix_chunks_embedding_identity")
    op.execute("ALTER TABLE chunks DROP COLUMN IF EXISTS embedded_at")
    op.execute("ALTER TABLE chunks DROP COLUMN IF EXISTS embedding_model_version")
    op.execute("ALTER TABLE chunks DROP COLUMN IF EXISTS embedding_model")
