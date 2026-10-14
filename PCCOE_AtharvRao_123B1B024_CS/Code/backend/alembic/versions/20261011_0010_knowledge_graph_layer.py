"""Knowledge-graph layer: reproducible confidence, relationship candidates, merges, findings.

* entities / relationships: ``raw_confidence`` (immutable extractor value; ``confidence`` becomes
  a pure function of it), ``merged_into_id`` / ``superseded_by_id`` (soft merge and soft
  correction);
* entity_aliases: ``source``;
* relationship_candidates: relationships stated by endpoint *names*, bound to entities later, so
  extraction no longer depends on the order in which chunks are processed;
* entity_merges / merge_decisions: audit trail and decision cache for entity resolution;
* findings: persisted "potential inconsistency" records with a review state.

Existing rows are back-filled (raw_confidence = current confidence).

Revision ID: 20261011_0010
Revises: 20261010_0009
Create Date: 2026-10-11
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20261011_0010"
down_revision = "20261010_0009"
branch_labels = None
depends_on = None

JSONB = postgresql.JSONB(astext_type=sa.Text())
NOW = sa.text("now()")


def _timestamps() -> list[sa.Column]:  # type: ignore[type-arg]
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
    ]


def upgrade() -> None:
    # -- entities -------------------------------------------------------------------------
    op.add_column("entities", sa.Column("raw_confidence", sa.Numeric(4, 3), nullable=True))
    op.add_column("entities", sa.Column("merged_into_id", sa.UUID(), nullable=True))
    op.add_column("entities", sa.Column("superseded_by_id", sa.UUID(), nullable=True))
    op.execute("UPDATE entities SET raw_confidence = confidence WHERE raw_confidence IS NULL")
    op.create_foreign_key(
        op.f("fk_entities_merged_into_id_entities"),
        "entities",
        "entities",
        ["merged_into_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        op.f("fk_entities_superseded_by_id_entities"),
        "entities",
        "entities",
        ["superseded_by_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(op.f("ix_entities_merged_into_id"), "entities", ["merged_into_id"])

    # -- entity aliases -----------------------------------------------------------------------
    op.add_column(
        "entity_aliases",
        sa.Column("source", sa.String(length=16), server_default="EXPLICIT", nullable=False),
    )

    # -- relationships --------------------------------------------------------------------------
    op.add_column("relationships", sa.Column("raw_confidence", sa.Numeric(4, 3), nullable=True))
    op.add_column("relationships", sa.Column("superseded_by_id", sa.UUID(), nullable=True))
    op.execute("UPDATE relationships SET raw_confidence = confidence WHERE raw_confidence IS NULL")
    op.create_foreign_key(
        op.f("fk_relationships_superseded_by_id_relationships"),
        "relationships",
        "relationships",
        ["superseded_by_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # -- relationship candidates --------------------------------------------------------------
    op.create_table(
        "relationship_candidates",
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("chunk_id", sa.UUID(), nullable=False),
        sa.Column("source_name", sa.Text(), nullable=False),
        sa.Column("target_name", sa.Text(), nullable=False),
        sa.Column("normalized_source", sa.String(length=512), nullable=False),
        sa.Column("normalized_target", sa.String(length=512), nullable=False),
        sa.Column("relationship_type", sa.String(length=128), nullable=False),
        sa.Column("confidence", sa.Numeric(4, 3), nullable=False),
        sa.Column("extraction_type", sa.String(length=16), nullable=False),
        sa.Column("source_classification", sa.String(length=32), nullable=False),
        sa.Column("excerpt", sa.Text(), nullable=False),
        sa.Column("start_offset", sa.Integer(), nullable=True),
        sa.Column("end_offset", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=16), server_default="UNBOUND", nullable=False),
        sa.Column("relationship_id", sa.UUID(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["chunk_id"],
            ["chunks.id"],
            name=op.f("fk_relationship_candidates_chunk_id_chunks"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_relationship_candidates_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["relationship_id"],
            ["relationships.id"],
            name=op.f("fk_relationship_candidates_relationship_id_relationships"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_relationship_candidates")),
        sa.UniqueConstraint(
            "chunk_id",
            "normalized_source",
            "normalized_target",
            "relationship_type",
            name="chunk_relationship_candidate",
        ),
    )
    op.create_index(
        op.f("ix_relationship_candidates_chunk_id"), "relationship_candidates", ["chunk_id"]
    )
    op.create_index(
        op.f("ix_relationship_candidates_project_id"), "relationship_candidates", ["project_id"]
    )
    op.create_index(
        "ix_relationship_candidates_project_status",
        "relationship_candidates",
        ["project_id", "status"],
    )

    # -- entity merges ------------------------------------------------------------------------
    op.create_table(
        "entity_merges",
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("canonical_entity_id", sa.UUID(), nullable=False),
        sa.Column("merged_entity_id", sa.UUID(), nullable=False),
        sa.Column("decided_by", sa.String(length=16), nullable=False),
        sa.Column("rule", sa.String(length=64), nullable=True),
        sa.Column("similarity", sa.Numeric(4, 3), nullable=True),
        sa.Column("blocking_keys", JSONB, nullable=False),
        sa.Column("llm_model", sa.String(length=255), nullable=True),
        sa.Column("prompt_version", sa.String(length=64), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("moved", JSONB, nullable=False),
        sa.Column("actor_id", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.Column("undone_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("undone_by", sa.String(length=255), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(
            ["canonical_entity_id"],
            ["entities.id"],
            name=op.f("fk_entity_merges_canonical_entity_id_entities"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["merged_entity_id"],
            ["entities.id"],
            name=op.f("fk_entity_merges_merged_entity_id_entities"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_entity_merges_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_entity_merges")),
    )
    op.create_index(
        op.f("ix_entity_merges_canonical_entity_id"), "entity_merges", ["canonical_entity_id"]
    )
    op.create_index(
        op.f("ix_entity_merges_merged_entity_id"), "entity_merges", ["merged_entity_id"]
    )
    op.create_index(op.f("ix_entity_merges_project_id"), "entity_merges", ["project_id"])

    # -- merge decisions --------------------------------------------------------------------
    op.create_table(
        "merge_decisions",
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("pair_key", sa.String(length=64), nullable=False),
        sa.Column("entity_a_id", sa.UUID(), nullable=False),
        sa.Column("entity_b_id", sa.UUID(), nullable=False),
        sa.Column("decision", sa.String(length=12), nullable=False),
        sa.Column("confidence", sa.Numeric(4, 3), nullable=True),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("model", sa.String(length=255), nullable=True),
        sa.Column("prompt_version", sa.String(length=64), nullable=True),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(
            ["entity_a_id"],
            ["entities.id"],
            name=op.f("fk_merge_decisions_entity_a_id_entities"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["entity_b_id"],
            ["entities.id"],
            name=op.f("fk_merge_decisions_entity_b_id_entities"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_merge_decisions_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_merge_decisions")),
        sa.UniqueConstraint("project_id", "pair_key", name="project_merge_pair"),
    )
    op.create_index(op.f("ix_merge_decisions_project_id"), "merge_decisions", ["project_id"])

    # -- findings -----------------------------------------------------------------------------
    op.create_table(
        "findings",
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("finding_type", sa.String(length=64), nullable=False),
        sa.Column("severity", sa.String(length=8), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("details", JSONB, nullable=False),
        sa.Column("entity_id", sa.UUID(), nullable=True),
        sa.Column("relationship_id", sa.UUID(), nullable=True),
        sa.Column("document_version_id", sa.UUID(), nullable=True),
        sa.Column("confidence", sa.Numeric(4, 3), nullable=True),
        sa.Column("detected_by", sa.String(length=32), nullable=False),
        sa.Column("dismissed_by", sa.String(length=255), nullable=True),
        sa.Column("dismissed_reason", sa.Text(), nullable=True),
        sa.Column("dismissed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["document_version_id"],
            ["document_versions.id"],
            name=op.f("fk_findings_document_version_id_document_versions"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["entity_id"],
            ["entities.id"],
            name=op.f("fk_findings_entity_id_entities"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_findings_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["relationship_id"],
            ["relationships.id"],
            name=op.f("fk_findings_relationship_id_relationships"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_findings")),
        sa.UniqueConstraint("project_id", "fingerprint", name="project_finding_fingerprint"),
    )
    op.create_index(op.f("ix_findings_finding_type"), "findings", ["finding_type"])
    op.create_index(op.f("ix_findings_project_id"), "findings", ["project_id"])
    op.create_index("ix_findings_project_status", "findings", ["project_id", "status"])


def downgrade() -> None:
    op.drop_table("findings")
    op.drop_table("merge_decisions")
    op.drop_table("entity_merges")
    op.drop_table("relationship_candidates")
    op.drop_constraint(
        op.f("fk_relationships_superseded_by_id_relationships"), "relationships", type_="foreignkey"
    )
    op.drop_column("relationships", "superseded_by_id")
    op.drop_column("relationships", "raw_confidence")
    op.drop_column("entity_aliases", "source")
    op.drop_index(op.f("ix_entities_merged_into_id"), table_name="entities")
    op.drop_constraint(
        op.f("fk_entities_superseded_by_id_entities"), "entities", type_="foreignkey"
    )
    op.drop_constraint(op.f("fk_entities_merged_into_id_entities"), "entities", type_="foreignkey")
    op.drop_column("entities", "superseded_by_id")
    op.drop_column("entities", "merged_into_id")
    op.drop_column("entities", "raw_confidence")
