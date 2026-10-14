"""Record the successful candidate-extraction state of each chunk.

Idempotent on purpose: databases that were created by the historical ``create_all`` based revision
0001 already contain this column.

Revision ID: 20260909_0006
Revises: 20260908_0005
Create Date: 2026-09-09
"""

from alembic import op

revision = "20260909_0006"
down_revision = "20260908_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE chunks ADD COLUMN IF NOT EXISTS extracted_at TIMESTAMP WITH TIME ZONE")


def downgrade() -> None:
    op.execute("ALTER TABLE chunks DROP COLUMN IF EXISTS extracted_at")
