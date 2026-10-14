"""Create the original relational MVP schema and PostgreSQL extensions.

This revision is a FROZEN snapshot written as explicit DDL. It deliberately does not call
``Base.metadata.create_all``: a migration must describe the schema as it was when the revision was
written, otherwise every column added later would already exist when its own migration runs (this is
exactly how revision 20260909_0006 used to fail on an empty database). Columns introduced by
revisions 0002, 0003 and 0006 are therefore absent here and added by those revisions.

Revision ID: 20260907_0001
Revises:
Create Date: 2026-09-07
"""

import sqlalchemy as sa
from pgvector.sqlalchemy import Vector
from sqlalchemy import Text
from sqlalchemy.dialects import postgresql

from alembic import op
from app.core.config import get_settings

# revision identifiers, used by Alembic.
revision = "20260907_0001"
down_revision = None
branch_labels = None
depends_on = None

_ENUM_TYPES = (
    "trust_state",
    "extraction_type",
    "validation_state",
    "job_state",
    "membership_role",
    "relationship_trust_state",
    "relationship_extraction_type",
    "relationship_validation_state",
    "comparison_state",
    "validation_event_state",
    "entity_source_classification",
    "relationship_source_classification",
)
_TABLES_IN_DROP_ORDER = (
    "relationship_evidence",
    "entity_evidence",
    "comparison_findings",
    "chunks",
    "validation_events",
    "sections",
    "comparisons",
    "relationships",
    "entity_aliases",
    "document_versions",
    "project_members",
    "jobs",
    "entities",
    "documents",
    "audit_events",
    "projects",
)


def _embedding_dimensions() -> int:
    """The vector width is fixed when the database is first created (see the readiness check)."""
    return get_settings().embedding_dimensions


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.create_table(
        "projects",
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_projects")),
        sa.UniqueConstraint("name", name=op.f("uq_projects_name")),
    )
    op.create_table(
        "audit_events",
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("actor_id", sa.String(length=255), nullable=False),
        sa.Column("action", sa.String(length=128), nullable=False),
        sa.Column("resource_type", sa.String(length=128), nullable=False),
        sa.Column("resource_id", sa.UUID(), nullable=False),
        sa.Column("details", postgresql.JSONB(astext_type=Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_audit_events_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_events")),
    )
    op.create_index(op.f("ix_audit_events_action"), "audit_events", ["action"], unique=False)
    op.create_index(op.f("ix_audit_events_actor_id"), "audit_events", ["actor_id"], unique=False)
    op.create_index(
        op.f("ix_audit_events_project_id"), "audit_events", ["project_id"], unique=False
    )
    op.create_table(
        "documents",
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=512), nullable=False),
        sa.Column("media_type", sa.String(length=128), nullable=False),
        sa.Column("storage_uri", sa.Text(), nullable=False),
        sa.Column("created_by", sa.String(length=255), nullable=False),
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
            name=op.f("fk_documents_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_documents")),
        sa.UniqueConstraint("project_id", "name", name="project_document_name"),
    )
    op.create_index(op.f("ix_documents_project_id"), "documents", ["project_id"], unique=False)
    op.create_table(
        "entities",
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("canonical_name", sa.String(length=512), nullable=False),
        sa.Column("normalized_name", sa.String(length=512), nullable=False),
        sa.Column("entity_type", sa.String(length=128), nullable=False),
        sa.Column(
            "trust_state",
            sa.Enum("CANDIDATE", "TRUSTED", name="trust_state", create_constraint=True),
            nullable=False,
        ),
        sa.Column(
            "extraction_type",
            sa.Enum("EXPLICIT", "INFERRED", name="extraction_type", create_constraint=True),
            nullable=False,
        ),
        sa.Column(
            "validation_state",
            sa.Enum(
                "PENDING",
                "HUMAN_VERIFIED",
                "HUMAN_CORRECTED",
                "REJECTED",
                name="validation_state",
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("confidence", sa.Numeric(precision=4, scale=3), nullable=False),
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
            name=op.f("fk_entities_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_entities")),
        sa.UniqueConstraint(
            "project_id", "normalized_name", "entity_type", name="project_entity_name_type"
        ),
    )
    op.create_index(op.f("ix_entities_entity_type"), "entities", ["entity_type"], unique=False)
    op.create_index(op.f("ix_entities_project_id"), "entities", ["project_id"], unique=False)
    op.create_table(
        "jobs",
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("job_type", sa.String(length=128), nullable=False),
        sa.Column(
            "state",
            sa.Enum(
                "PENDING",
                "RUNNING",
                "COMPLETED",
                "FAILED",
                "CANCELLED",
                name="job_state",
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("requested_by", sa.String(length=255), nullable=False),
        sa.Column("details", postgresql.JSONB(astext_type=Text()), nullable=False),
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
            name=op.f("fk_jobs_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_jobs")),
    )
    op.create_index(op.f("ix_jobs_job_type"), "jobs", ["job_type"], unique=False)
    op.create_index(op.f("ix_jobs_project_id"), "jobs", ["project_id"], unique=False)
    op.create_table(
        "project_members",
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.String(length=255), nullable=False),
        sa.Column(
            "role",
            sa.Enum(
                "VIEWER",
                "ENGINEER",
                "REVIEWER",
                "ADMIN",
                name="membership_role",
                create_constraint=True,
            ),
            nullable=False,
        ),
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
            name=op.f("fk_project_members_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_project_members")),
        sa.UniqueConstraint("project_id", "user_id", name="project_member"),
    )
    op.create_index(
        op.f("ix_project_members_project_id"), "project_members", ["project_id"], unique=False
    )
    op.create_index(
        op.f("ix_project_members_user_id"), "project_members", ["user_id"], unique=False
    )
    op.create_table(
        "document_versions",
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("document_id", sa.UUID(), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("checksum", sa.String(length=128), nullable=False),
        sa.Column("source_label", sa.String(length=255), nullable=True),
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
            ["document_id"],
            ["documents.id"],
            name=op.f("fk_document_versions_document_id_documents"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_document_versions_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_document_versions")),
        sa.UniqueConstraint("document_id", "version_number", name="document_version_number"),
    )
    op.create_index(
        op.f("ix_document_versions_document_id"), "document_versions", ["document_id"], unique=False
    )
    op.create_index(
        op.f("ix_document_versions_project_id"), "document_versions", ["project_id"], unique=False
    )
    op.create_table(
        "entity_aliases",
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("entity_id", sa.UUID(), nullable=False),
        sa.Column("alias", sa.String(length=512), nullable=False),
        sa.Column("normalized_alias", sa.String(length=512), nullable=False),
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
            ["entity_id"],
            ["entities.id"],
            name=op.f("fk_entity_aliases_entity_id_entities"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_entity_aliases_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_entity_aliases")),
        sa.UniqueConstraint("project_id", "normalized_alias", name="project_entity_alias"),
    )
    op.create_index(
        op.f("ix_entity_aliases_entity_id"), "entity_aliases", ["entity_id"], unique=False
    )
    op.create_index(
        op.f("ix_entity_aliases_project_id"), "entity_aliases", ["project_id"], unique=False
    )
    op.create_table(
        "relationships",
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("source_entity_id", sa.UUID(), nullable=False),
        sa.Column("target_entity_id", sa.UUID(), nullable=False),
        sa.Column("relationship_type", sa.String(length=128), nullable=False),
        sa.Column(
            "trust_state",
            sa.Enum(
                "CANDIDATE", "TRUSTED", name="relationship_trust_state", create_constraint=True
            ),
            nullable=False,
        ),
        sa.Column(
            "extraction_type",
            sa.Enum(
                "EXPLICIT", "INFERRED", name="relationship_extraction_type", create_constraint=True
            ),
            nullable=False,
        ),
        sa.Column(
            "validation_state",
            sa.Enum(
                "PENDING",
                "HUMAN_VERIFIED",
                "HUMAN_CORRECTED",
                "REJECTED",
                name="relationship_validation_state",
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("confidence", sa.Numeric(precision=4, scale=3), nullable=False),
        sa.Column("attributes", postgresql.JSONB(astext_type=Text()), nullable=False),
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
        sa.CheckConstraint(
            "source_entity_id <> target_entity_id",
            name=op.f("ck_relationships_directed_distinct_endpoints"),
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_relationships_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_entity_id"],
            ["entities.id"],
            name=op.f("fk_relationships_source_entity_id_entities"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["target_entity_id"],
            ["entities.id"],
            name=op.f("fk_relationships_target_entity_id_entities"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_relationships")),
    )
    op.create_index(
        op.f("ix_relationships_project_id"), "relationships", ["project_id"], unique=False
    )
    op.create_index(
        "ix_relationships_project_source",
        "relationships",
        ["project_id", "source_entity_id"],
        unique=False,
    )
    op.create_index(
        "ix_relationships_project_target",
        "relationships",
        ["project_id", "target_entity_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_relationships_relationship_type"),
        "relationships",
        ["relationship_type"],
        unique=False,
    )
    op.create_table(
        "comparisons",
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("base_version_id", sa.UUID(), nullable=False),
        sa.Column("target_version_id", sa.UUID(), nullable=False),
        sa.Column(
            "state",
            sa.Enum(
                "PENDING", "COMPLETED", "FAILED", name="comparison_state", create_constraint=True
            ),
            nullable=False,
        ),
        sa.Column("requested_by", sa.String(length=255), nullable=False),
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
        sa.CheckConstraint(
            "base_version_id <> target_version_id", name=op.f("ck_comparisons_distinct_versions")
        ),
        sa.ForeignKeyConstraint(
            ["base_version_id"],
            ["document_versions.id"],
            name=op.f("fk_comparisons_base_version_id_document_versions"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_comparisons_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["target_version_id"],
            ["document_versions.id"],
            name=op.f("fk_comparisons_target_version_id_document_versions"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_comparisons")),
    )
    op.create_index(op.f("ix_comparisons_project_id"), "comparisons", ["project_id"], unique=False)
    op.create_table(
        "sections",
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("document_version_id", sa.UUID(), nullable=False),
        sa.Column("parent_section_id", sa.UUID(), nullable=True),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("heading", sa.String(length=1024), nullable=False),
        sa.Column("level", sa.Integer(), nullable=False),
        sa.Column("page_start", sa.Integer(), nullable=True),
        sa.Column("page_end", sa.Integer(), nullable=True),
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
            ["document_version_id"],
            ["document_versions.id"],
            name=op.f("fk_sections_document_version_id_document_versions"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["parent_section_id"],
            ["sections.id"],
            name=op.f("fk_sections_parent_section_id_sections"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_sections_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sections")),
        sa.UniqueConstraint("document_version_id", "ordinal", name="version_section_ordinal"),
    )
    op.create_index(
        op.f("ix_sections_document_version_id"), "sections", ["document_version_id"], unique=False
    )
    op.create_index(op.f("ix_sections_project_id"), "sections", ["project_id"], unique=False)
    op.create_table(
        "validation_events",
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("entity_id", sa.UUID(), nullable=True),
        sa.Column("relationship_id", sa.UUID(), nullable=True),
        sa.Column(
            "state",
            sa.Enum(
                "PENDING",
                "HUMAN_VERIFIED",
                "HUMAN_CORRECTED",
                "REJECTED",
                name="validation_event_state",
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("actor_id", sa.String(length=255), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.CheckConstraint(
            "(entity_id IS NOT NULL) <> (relationship_id IS NOT NULL)",
            name=op.f("ck_validation_events_one_fact_target"),
        ),
        sa.ForeignKeyConstraint(
            ["entity_id"],
            ["entities.id"],
            name=op.f("fk_validation_events_entity_id_entities"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_validation_events_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["relationship_id"],
            ["relationships.id"],
            name=op.f("fk_validation_events_relationship_id_relationships"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_validation_events")),
    )
    op.create_index(
        op.f("ix_validation_events_project_id"), "validation_events", ["project_id"], unique=False
    )
    op.create_table(
        "chunks",
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("document_version_id", sa.UUID(), nullable=False),
        sa.Column("section_id", sa.UUID(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("token_count", sa.Integer(), nullable=False),
        sa.Column("page_start", sa.Integer(), nullable=True),
        sa.Column("page_end", sa.Integer(), nullable=True),
        sa.Column("embedding", Vector(_embedding_dimensions()), nullable=True),
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
            ["document_version_id"],
            ["document_versions.id"],
            name=op.f("fk_chunks_document_version_id_document_versions"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_chunks_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["section_id"],
            ["sections.id"],
            name=op.f("fk_chunks_section_id_sections"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_chunks")),
        sa.UniqueConstraint("section_id", "ordinal", name="section_chunk_ordinal"),
    )
    op.create_index(
        op.f("ix_chunks_document_version_id"), "chunks", ["document_version_id"], unique=False
    )
    op.create_index(
        "ix_chunks_embedding_hnsw",
        "chunks",
        ["embedding"],
        unique=False,
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )
    op.create_index(
        "ix_chunks_project_document_version",
        "chunks",
        ["project_id", "document_version_id"],
        unique=False,
    )
    op.create_index(op.f("ix_chunks_project_id"), "chunks", ["project_id"], unique=False)
    op.create_index(op.f("ix_chunks_section_id"), "chunks", ["section_id"], unique=False)
    op.create_table(
        "comparison_findings",
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("comparison_id", sa.UUID(), nullable=False),
        sa.Column("entity_id", sa.UUID(), nullable=True),
        sa.Column("finding_type", sa.String(length=128), nullable=False),
        sa.Column("confidence", sa.Numeric(precision=4, scale=3), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("details", postgresql.JSONB(astext_type=Text()), nullable=False),
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
            ["comparison_id"],
            ["comparisons.id"],
            name=op.f("fk_comparison_findings_comparison_id_comparisons"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["entity_id"],
            ["entities.id"],
            name=op.f("fk_comparison_findings_entity_id_entities"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_comparison_findings_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_comparison_findings")),
    )
    op.create_index(
        op.f("ix_comparison_findings_comparison_id"),
        "comparison_findings",
        ["comparison_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_comparison_findings_finding_type"),
        "comparison_findings",
        ["finding_type"],
        unique=False,
    )
    op.create_index(
        op.f("ix_comparison_findings_project_id"),
        "comparison_findings",
        ["project_id"],
        unique=False,
    )
    op.create_table(
        "entity_evidence",
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("entity_id", sa.UUID(), nullable=False),
        sa.Column("chunk_id", sa.UUID(), nullable=False),
        sa.Column(
            "source_classification",
            sa.Enum(
                "DIRECT_TEXT",
                "TABLE",
                "DIAGRAM",
                "MULTI_SOURCE_INFERENCE",
                name="entity_source_classification",
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("excerpt", sa.Text(), nullable=False),
        sa.Column("start_offset", sa.Integer(), nullable=True),
        sa.Column("end_offset", sa.Integer(), nullable=True),
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
            ["chunk_id"],
            ["chunks.id"],
            name=op.f("fk_entity_evidence_chunk_id_chunks"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["entity_id"],
            ["entities.id"],
            name=op.f("fk_entity_evidence_entity_id_entities"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_entity_evidence_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_entity_evidence")),
        sa.UniqueConstraint("entity_id", "chunk_id", name="entity_chunk_evidence"),
    )
    op.create_index(
        op.f("ix_entity_evidence_chunk_id"), "entity_evidence", ["chunk_id"], unique=False
    )
    op.create_index(
        op.f("ix_entity_evidence_entity_id"), "entity_evidence", ["entity_id"], unique=False
    )
    op.create_index(
        op.f("ix_entity_evidence_project_id"), "entity_evidence", ["project_id"], unique=False
    )
    op.create_table(
        "relationship_evidence",
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("relationship_id", sa.UUID(), nullable=False),
        sa.Column("chunk_id", sa.UUID(), nullable=False),
        sa.Column(
            "source_classification",
            sa.Enum(
                "DIRECT_TEXT",
                "TABLE",
                "DIAGRAM",
                "MULTI_SOURCE_INFERENCE",
                name="relationship_source_classification",
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("excerpt", sa.Text(), nullable=False),
        sa.Column("start_offset", sa.Integer(), nullable=True),
        sa.Column("end_offset", sa.Integer(), nullable=True),
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
            ["chunk_id"],
            ["chunks.id"],
            name=op.f("fk_relationship_evidence_chunk_id_chunks"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_relationship_evidence_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["relationship_id"],
            ["relationships.id"],
            name=op.f("fk_relationship_evidence_relationship_id_relationships"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_relationship_evidence")),
        sa.UniqueConstraint("relationship_id", "chunk_id", name="relationship_chunk_evidence"),
    )
    op.create_index(
        op.f("ix_relationship_evidence_chunk_id"),
        "relationship_evidence",
        ["chunk_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_relationship_evidence_project_id"),
        "relationship_evidence",
        ["project_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_relationship_evidence_relationship_id"),
        "relationship_evidence",
        ["relationship_id"],
        unique=False,
    )


def downgrade() -> None:
    """Drop application tables and their enum types; shared extensions are retained."""
    for table in _TABLES_IN_DROP_ORDER:
        op.drop_table(table)
    for enum_name in _ENUM_TYPES:
        op.execute(f"DROP TYPE IF EXISTS {enum_name}")
