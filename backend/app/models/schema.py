"""PostgreSQL relational schema for documents, knowledge, provenance, and review history."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.config import get_settings
from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import (
    ComparisonState,
    ExtractionType,
    JobState,
    MembershipRole,
    SourceClassification,
    TrustState,
    ValidationState,
)


def enum_type(enum_class: type[Any], name: str) -> Enum:
    """Create native PostgreSQL enums with explicit, stable database names."""
    return Enum(enum_class, name=name, native_enum=True, create_constraint=True)


class Project(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "projects"
    name: Mapped[str] = mapped_column(String(255), unique=True)
    description: Mapped[str | None] = mapped_column(Text())


class ProjectMember(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "project_members"
    __table_args__ = (UniqueConstraint("project_id", "user_id", name="project_member"),)
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[str] = mapped_column(String(255), index=True)
    role: Mapped[MembershipRole] = mapped_column(enum_type(MembershipRole, "membership_role"))


class Document(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "documents"
    __table_args__ = (UniqueConstraint("project_id", "name", name="project_document_name"),)
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(512))
    media_type: Mapped[str] = mapped_column(String(128))
    storage_uri: Mapped[str] = mapped_column(Text())
    created_by: Mapped[str] = mapped_column(String(255))


class DocumentVersion(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "document_versions"
    __table_args__ = (
        UniqueConstraint("document_id", "version_number", name="document_version_number"),
    )
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    document_id: Mapped[UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )
    version_number: Mapped[int] = mapped_column(Integer())
    checksum: Mapped[str] = mapped_column(String(128))
    source_label: Mapped[str | None] = mapped_column(String(255))


class Section(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "sections"
    __table_args__ = (
        UniqueConstraint("document_version_id", "ordinal", name="version_section_ordinal"),
    )
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    document_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("document_versions.id", ondelete="CASCADE"), index=True
    )
    parent_section_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("sections.id", ondelete="SET NULL")
    )
    ordinal: Mapped[int] = mapped_column(Integer())
    heading: Mapped[str] = mapped_column(String(1024))
    level: Mapped[int] = mapped_column(Integer())
    page_start: Mapped[int | None] = mapped_column(Integer())
    page_end: Mapped[int | None] = mapped_column(Integer())


class Chunk(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "chunks"
    __table_args__ = (
        UniqueConstraint("section_id", "ordinal", name="section_chunk_ordinal"),
        Index("ix_chunks_project_document_version", "project_id", "document_version_id"),
        Index(
            "ix_chunks_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    document_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("document_versions.id", ondelete="CASCADE"), index=True
    )
    section_id: Mapped[UUID] = mapped_column(
        ForeignKey("sections.id", ondelete="CASCADE"), index=True
    )
    ordinal: Mapped[int] = mapped_column(Integer())
    content: Mapped[str] = mapped_column(Text())
    token_count: Mapped[int] = mapped_column(Integer())
    page_start: Mapped[int | None] = mapped_column(Integer())
    page_end: Mapped[int | None] = mapped_column(Integer())
    embedding: Mapped[list[float] | None] = mapped_column(
        Vector(get_settings().embedding_dimensions)
    )
    embedding_model: Mapped[str | None] = mapped_column(String(255))
    embedding_model_version: Mapped[str | None] = mapped_column(String(128))
    embedded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    extracted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Entity(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "entities"
    __table_args__ = (
        UniqueConstraint(
            "project_id", "normalized_name", "entity_type", name="project_entity_name_type"
        ),
    )
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    canonical_name: Mapped[str] = mapped_column(String(512))
    normalized_name: Mapped[str] = mapped_column(String(512))
    entity_type: Mapped[str] = mapped_column(String(128), index=True)
    trust_state: Mapped[TrustState] = mapped_column(
        enum_type(TrustState, "trust_state"), default=TrustState.CANDIDATE
    )
    extraction_type: Mapped[ExtractionType] = mapped_column(
        enum_type(ExtractionType, "extraction_type")
    )
    validation_state: Mapped[ValidationState] = mapped_column(
        enum_type(ValidationState, "validation_state"), default=ValidationState.PENDING
    )
    confidence: Mapped[Decimal] = mapped_column(Numeric(4, 3))
    extraction_metadata: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)


class EntityAlias(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "entity_aliases"
    __table_args__ = (
        UniqueConstraint("project_id", "normalized_alias", name="project_entity_alias"),
    )
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    entity_id: Mapped[UUID] = mapped_column(
        ForeignKey("entities.id", ondelete="CASCADE"), index=True
    )
    alias: Mapped[str] = mapped_column(String(512))
    normalized_alias: Mapped[str] = mapped_column(String(512))


class Relationship(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "relationships"
    __table_args__ = (
        CheckConstraint("source_entity_id <> target_entity_id", name="directed_distinct_endpoints"),
        Index("ix_relationships_project_source", "project_id", "source_entity_id"),
        Index("ix_relationships_project_target", "project_id", "target_entity_id"),
    )
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    source_entity_id: Mapped[UUID] = mapped_column(ForeignKey("entities.id", ondelete="RESTRICT"))
    target_entity_id: Mapped[UUID] = mapped_column(ForeignKey("entities.id", ondelete="RESTRICT"))
    relationship_type: Mapped[str] = mapped_column(String(128), index=True)
    trust_state: Mapped[TrustState] = mapped_column(
        enum_type(TrustState, "relationship_trust_state"), default=TrustState.CANDIDATE
    )
    extraction_type: Mapped[ExtractionType] = mapped_column(
        enum_type(ExtractionType, "relationship_extraction_type")
    )
    validation_state: Mapped[ValidationState] = mapped_column(
        enum_type(ValidationState, "relationship_validation_state"), default=ValidationState.PENDING
    )
    confidence: Mapped[Decimal] = mapped_column(Numeric(4, 3))
    attributes: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)


class EntityEvidence(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "entity_evidence"
    __table_args__ = (UniqueConstraint("entity_id", "chunk_id", name="entity_chunk_evidence"),)
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    entity_id: Mapped[UUID] = mapped_column(
        ForeignKey("entities.id", ondelete="CASCADE"), index=True
    )
    chunk_id: Mapped[UUID] = mapped_column(ForeignKey("chunks.id", ondelete="CASCADE"), index=True)
    source_classification: Mapped[SourceClassification] = mapped_column(
        enum_type(SourceClassification, "entity_source_classification")
    )
    excerpt: Mapped[str] = mapped_column(Text())
    start_offset: Mapped[int | None] = mapped_column(Integer())
    end_offset: Mapped[int | None] = mapped_column(Integer())


class RelationshipEvidence(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "relationship_evidence"
    __table_args__ = (
        UniqueConstraint("relationship_id", "chunk_id", name="relationship_chunk_evidence"),
    )
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    relationship_id: Mapped[UUID] = mapped_column(
        ForeignKey("relationships.id", ondelete="CASCADE"), index=True
    )
    chunk_id: Mapped[UUID] = mapped_column(ForeignKey("chunks.id", ondelete="CASCADE"), index=True)
    source_classification: Mapped[SourceClassification] = mapped_column(
        enum_type(SourceClassification, "relationship_source_classification")
    )
    excerpt: Mapped[str] = mapped_column(Text())
    start_offset: Mapped[int | None] = mapped_column(Integer())
    end_offset: Mapped[int | None] = mapped_column(Integer())


class ValidationEvent(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "validation_events"
    __table_args__ = (
        CheckConstraint(
            "(entity_id IS NOT NULL) <> (relationship_id IS NOT NULL)", name="one_fact_target"
        ),
    )
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    entity_id: Mapped[UUID | None] = mapped_column(ForeignKey("entities.id", ondelete="CASCADE"))
    relationship_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("relationships.id", ondelete="CASCADE")
    )
    state: Mapped[ValidationState] = mapped_column(
        enum_type(ValidationState, "validation_event_state")
    )
    actor_id: Mapped[str] = mapped_column(String(255))
    reason: Mapped[str | None] = mapped_column(Text())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AuditEvent(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "audit_events"
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    actor_id: Mapped[str] = mapped_column(String(255), index=True)
    action: Mapped[str] = mapped_column(String(128), index=True)
    resource_type: Mapped[str] = mapped_column(String(128))
    resource_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True))
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Job(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "jobs"
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    job_type: Mapped[str] = mapped_column(String(128), index=True)
    state: Mapped[JobState] = mapped_column(
        enum_type(JobState, "job_state"), default=JobState.PENDING
    )
    requested_by: Mapped[str] = mapped_column(String(255))
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)


class Comparison(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "comparisons"
    __table_args__ = (
        CheckConstraint("base_version_id <> target_version_id", name="distinct_versions"),
    )
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    base_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("document_versions.id", ondelete="RESTRICT")
    )
    target_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("document_versions.id", ondelete="RESTRICT")
    )
    state: Mapped[ComparisonState] = mapped_column(
        enum_type(ComparisonState, "comparison_state"), default=ComparisonState.PENDING
    )
    requested_by: Mapped[str] = mapped_column(String(255))


class ComparisonFinding(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "comparison_findings"
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    comparison_id: Mapped[UUID] = mapped_column(
        ForeignKey("comparisons.id", ondelete="CASCADE"), index=True
    )
    entity_id: Mapped[UUID | None] = mapped_column(ForeignKey("entities.id", ondelete="SET NULL"))
    finding_type: Mapped[str] = mapped_column(String(128), index=True)
    confidence: Mapped[Decimal] = mapped_column(Numeric(4, 3))
    summary: Mapped[str] = mapped_column(Text())
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
