"""PostgreSQL relational schema for documents, knowledge, provenance, and review history."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Computed,
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
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
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
    #: Deterministic document metadata (title, version, status, dates, revision history) plus parse
    #: statistics (structure source, OCR pages, removed running lines, warnings).
    properties: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default="{}")


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
    #: ``1.1`` for "1.1 Components"; ``heading`` keeps the number so citations read naturally.
    number_label: Mapped[str | None] = mapped_column(String(64))
    #: Ancestor headings joined by " > " (this section last); empty for the preamble.
    path: Mapped[str] = mapped_column(Text(), default="", server_default="")
    depth: Mapped[int] = mapped_column(Integer(), default=0, server_default="0")
    page_start: Mapped[int | None] = mapped_column(Integer())
    page_end: Mapped[int | None] = mapped_column(Integer())


class OcrCache(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Recognised text per page image (project-scoped): retries never re-bill OCR."""

    __tablename__ = "ocr_cache"
    __table_args__ = (UniqueConstraint("project_id", "cache_key", name="project_ocr_cache_key"),)
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    cache_key: Mapped[str] = mapped_column(String(255))
    text: Mapped[str] = mapped_column(Text())


class Chunk(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "chunks"
    __table_args__ = (
        UniqueConstraint("section_id", "ordinal", name="section_chunk_ordinal"),
        Index("ix_chunks_project_document_version", "project_id", "document_version_id"),
        Index("ix_chunks_search_vector", "search_vector", postgresql_using="gin"),
        Index(
            "ix_chunks_embedding_identity",
            "project_id",
            "document_version_id",
            "embedding_model",
            "embedding_model_version",
        ),
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
    #: The raw source text of this chunk: what is quoted in citations and verified against answers.
    content: Mapped[str] = mapped_column(Text())
    token_count: Mapped[int] = mapped_column(Integer())
    page_start: Mapped[int | None] = mapped_column(Integer())
    page_end: Mapped[int | None] = mapped_column(Integer())
    #: ``<document> > <ancestor headings> > <heading>``: hierarchy context for embedding/indexing.
    breadcrumb: Mapped[str | None] = mapped_column(Text())
    #: SHA-256 of ``embedding_text``; identical chunks reuse an existing vector (no new call).
    content_hash: Mapped[str | None] = mapped_column(String(64), index=True)
    chunk_kind: Mapped[str] = mapped_column(String(16), default="TEXT", server_default="TEXT")
    attrs: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default="{}")
    #: Identifier-normalised text for lexical search (see ``app.ingestion.lexical``).
    lexical_text: Mapped[str | None] = mapped_column(Text())
    search_vector: Mapped[str | None] = mapped_column(
        TSVECTOR, Computed("to_tsvector('english', coalesce(lexical_text, ''))", persisted=True)
    )
    embedding: Mapped[list[float] | None] = mapped_column(
        Vector(get_settings().embedding_dimensions)
    )
    embedding_model: Mapped[str | None] = mapped_column(String(255))
    embedding_model_version: Mapped[str | None] = mapped_column(String(128))
    embedded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    extracted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    @property
    def embedding_text(self) -> str:
        """What is sent to the embedding model: hierarchy context followed by the raw text."""
        return f"{self.breadcrumb}\n{self.content}" if self.breadcrumb else self.content


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
    #: What the extractor reported. ``confidence`` is derived from it by a pure function, so
    #: rebuilding the graph any number of times yields the same value.
    raw_confidence: Mapped[Decimal | None] = mapped_column(Numeric(4, 3))
    confidence: Mapped[Decimal] = mapped_column(Numeric(4, 3))
    extraction_metadata: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    #: Set when this entity was merged into another (a soft merge: the row, its evidence trail and
    #: the AI extraction are kept, and the merge can be undone). Merged entities are inactive.
    merged_into_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("entities.id", ondelete="SET NULL"), index=True
    )
    #: Set when a reviewer's correction replaced this entity (the original stays for audit).
    superseded_by_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("entities.id", ondelete="SET NULL")
    )


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
    #: EXPLICIT = the document says so, MERGE = recorded when a duplicate was merged, HUMAN.
    source: Mapped[str] = mapped_column(String(16), default="EXPLICIT", server_default="EXPLICIT")


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
    raw_confidence: Mapped[Decimal | None] = mapped_column(Numeric(4, 3))
    confidence: Mapped[Decimal] = mapped_column(Numeric(4, 3))
    attributes: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    superseded_by_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("relationships.id", ondelete="SET NULL")
    )


class RelationshipCandidate(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A relationship stated in a chunk, by endpoint *names*, before endpoints are resolved.

    Extraction cannot know which entities exist yet (they may be defined in a later section or
    another document), so it records what the text says. The resolution stage binds the names to
    canonical entities deterministically, independent of chunk order, and anything it cannot bind
    stays ``UNBOUND`` and surfaces as a finding instead of silently disappearing.
    """

    __tablename__ = "relationship_candidates"
    __table_args__ = (
        UniqueConstraint(
            "chunk_id",
            "normalized_source",
            "normalized_target",
            "relationship_type",
            name="chunk_relationship_candidate",
        ),
        Index("ix_relationship_candidates_project_status", "project_id", "status"),
    )
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    chunk_id: Mapped[UUID] = mapped_column(ForeignKey("chunks.id", ondelete="CASCADE"), index=True)
    source_name: Mapped[str] = mapped_column(Text())
    target_name: Mapped[str] = mapped_column(Text())
    normalized_source: Mapped[str] = mapped_column(String(512))
    normalized_target: Mapped[str] = mapped_column(String(512))
    relationship_type: Mapped[str] = mapped_column(String(128))
    confidence: Mapped[Decimal] = mapped_column(Numeric(4, 3))
    extraction_type: Mapped[str] = mapped_column(String(16))
    source_classification: Mapped[str] = mapped_column(String(32))
    excerpt: Mapped[str] = mapped_column(Text())
    start_offset: Mapped[int | None] = mapped_column(Integer())
    end_offset: Mapped[int | None] = mapped_column(Integer())
    #: UNBOUND (endpoint missing or ambiguous) | BOUND (a relationship exists for it)
    status: Mapped[str] = mapped_column(String(16), default="UNBOUND", server_default="UNBOUND")
    relationship_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("relationships.id", ondelete="SET NULL")
    )
    note: Mapped[str | None] = mapped_column(Text())


class EntityMerge(UUIDPrimaryKeyMixin, Base):
    """One applied merge: who decided, why, and exactly what moved (so it can be undone)."""

    __tablename__ = "entity_merges"
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    canonical_entity_id: Mapped[UUID] = mapped_column(
        ForeignKey("entities.id", ondelete="CASCADE"), index=True
    )
    merged_entity_id: Mapped[UUID] = mapped_column(
        ForeignKey("entities.id", ondelete="CASCADE"), index=True
    )
    decided_by: Mapped[str] = mapped_column(String(16))  # RULE | ALIAS | LLM | HUMAN
    rule: Mapped[str | None] = mapped_column(String(64))
    similarity: Mapped[Decimal | None] = mapped_column(Numeric(4, 3))
    blocking_keys: Mapped[list[str]] = mapped_column(JSONB, default=list)
    llm_model: Mapped[str | None] = mapped_column(String(255))
    prompt_version: Mapped[str | None] = mapped_column(String(64))
    reason: Mapped[str | None] = mapped_column(Text())
    moved: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    actor_id: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    undone_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    undone_by: Mapped[str | None] = mapped_column(String(255))


class MergeDecision(UUIDPrimaryKeyMixin, Base):
    """A judged entity pair (including "different"), cached so reruns never re-ask the model."""

    __tablename__ = "merge_decisions"
    __table_args__ = (UniqueConstraint("project_id", "pair_key", name="project_merge_pair"),)
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    pair_key: Mapped[str] = mapped_column(String(64))
    entity_a_id: Mapped[UUID] = mapped_column(ForeignKey("entities.id", ondelete="CASCADE"))
    entity_b_id: Mapped[UUID] = mapped_column(ForeignKey("entities.id", ondelete="CASCADE"))
    decision: Mapped[str] = mapped_column(String(12))  # SAME | DIFFERENT | UNSURE
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(4, 3))
    source: Mapped[str] = mapped_column(String(16))  # LLM | RULE
    reason: Mapped[str | None] = mapped_column(Text())
    model: Mapped[str | None] = mapped_column(String(255))
    prompt_version: Mapped[str | None] = mapped_column(String(64))
    #: Hash of the evidence the decision was based on; a change invalidates the cached decision.
    fingerprint: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Finding(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A *potential* inconsistency for a human to judge; never an automatic verdict."""

    __tablename__ = "findings"
    __table_args__ = (
        UniqueConstraint("project_id", "fingerprint", name="project_finding_fingerprint"),
        Index("ix_findings_project_status", "project_id", "status"),
    )
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    finding_type: Mapped[str] = mapped_column(String(64), index=True)
    severity: Mapped[str] = mapped_column(String(8), default="MEDIUM")
    status: Mapped[str] = mapped_column(String(16), default="OPEN")  # OPEN | DISMISSED | RESOLVED
    fingerprint: Mapped[str] = mapped_column(String(64))
    summary: Mapped[str] = mapped_column(Text())
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    entity_id: Mapped[UUID | None] = mapped_column(ForeignKey("entities.id", ondelete="SET NULL"))
    relationship_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("relationships.id", ondelete="SET NULL")
    )
    document_version_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("document_versions.id", ondelete="SET NULL")
    )
    #: Confidence of the facts the finding rests on (``None`` when it rests on none).
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(4, 3))
    detected_by: Mapped[str] = mapped_column(String(32), default="RULE")
    dismissed_by: Mapped[str | None] = mapped_column(String(255))
    dismissed_reason: Mapped[str | None] = mapped_column(Text())
    dismissed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


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
    __table_args__ = (Index("ix_jobs_queue", "state", "run_after", "created_at"),)
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    job_type: Mapped[str] = mapped_column(String(128), index=True)
    state: Mapped[JobState] = mapped_column(
        enum_type(JobState, "job_state"), default=JobState.PENDING
    )
    requested_by: Mapped[str] = mapped_column(String(255))
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    # Queue mechanics. ``cancel_requested`` is its own column so that an API cancellation can never
    # be
    # overwritten by the worker rewriting the ``details`` document (and vice versa).
    cancel_requested: Mapped[bool] = mapped_column(Boolean(), default=False, server_default="false")
    run_after: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    locked_by: Mapped[str | None] = mapped_column(String(128))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


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
