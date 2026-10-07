"""Record the successful candidate-extraction state of each chunk.

This revision restores the migration source corresponding to an already-deployed
database revision.  It is intentionally additive and safe for fresh databases.
"""

import sqlalchemy as sa

from alembic import op

revision = "20260909_0006"
down_revision = "20260908_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("chunks", sa.Column("extracted_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("chunks", "extracted_at")
