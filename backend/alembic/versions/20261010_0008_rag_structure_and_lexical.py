"""Hierarchy-aware chunks and lexical search.

* sections: number label, path (ancestor headings) and depth;
* chunks: breadcrumb, content hash (vector re-use), kind, attributes, lexical text and a generated,
  GIN-indexed ``tsvector``;
* document_versions: deterministic document properties (metadata and parse statistics).

Existing rows keep working: their ``lexical_text`` is back-filled with the raw content (re-ingest
the document to get identifier-aware lexical text and breadcrumbs).

Revision ID: 20261010_0008
Revises: 20261010_0007
Create Date: 2026-10-10
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20261010_0008"
down_revision = "20261010_0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("sections", sa.Column("number_label", sa.String(length=64), nullable=True))
    op.add_column("sections", sa.Column("path", sa.Text(), server_default="", nullable=False))
    op.add_column("sections", sa.Column("depth", sa.Integer(), server_default="0", nullable=False))

    op.add_column("chunks", sa.Column("breadcrumb", sa.Text(), nullable=True))
    op.add_column("chunks", sa.Column("content_hash", sa.String(length=64), nullable=True))
    op.add_column(
        "chunks",
        sa.Column("chunk_kind", sa.String(length=16), server_default="TEXT", nullable=False),
    )
    op.add_column(
        "chunks",
        sa.Column(
            "attrs", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False
        ),
    )
    op.add_column("chunks", sa.Column("lexical_text", sa.Text(), nullable=True))
    op.execute("UPDATE chunks SET lexical_text = content WHERE lexical_text IS NULL")
    op.add_column(
        "chunks",
        sa.Column(
            "search_vector",
            postgresql.TSVECTOR(),
            sa.Computed("to_tsvector('english', coalesce(lexical_text, ''))", persisted=True),
            nullable=True,
        ),
    )
    op.create_index(op.f("ix_chunks_content_hash"), "chunks", ["content_hash"], unique=False)
    op.create_index(
        "ix_chunks_search_vector", "chunks", ["search_vector"], unique=False, postgresql_using="gin"
    )

    op.add_column(
        "document_versions",
        sa.Column(
            "properties",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="{}",
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("document_versions", "properties")
    op.drop_index("ix_chunks_search_vector", table_name="chunks", postgresql_using="gin")
    op.drop_index(op.f("ix_chunks_content_hash"), table_name="chunks")
    for column in (
        "search_vector",
        "lexical_text",
        "attrs",
        "chunk_kind",
        "content_hash",
        "breadcrumb",
    ):
        op.drop_column("chunks", column)
    for column in ("depth", "path", "number_label"):
        op.drop_column("sections", column)
