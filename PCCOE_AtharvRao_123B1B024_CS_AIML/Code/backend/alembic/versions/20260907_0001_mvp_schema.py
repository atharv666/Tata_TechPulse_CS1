"""Create the complete relational MVP schema and PostgreSQL extensions.

Revision ID: 20260907_0001
Revises:
Create Date: 2026-09-07
"""

from alembic import op
from app.models import Base

# revision identifiers, used by Alembic.
revision = "20260907_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Enable required extensions before creating all MVP tables and indexes."""
    connection = op.get_bind()
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    Base.metadata.create_all(bind=connection, checkfirst=False)


def downgrade() -> None:
    """Drop application tables only; shared database extensions are retained."""
    Base.metadata.drop_all(bind=op.get_bind(), checkfirst=False)
