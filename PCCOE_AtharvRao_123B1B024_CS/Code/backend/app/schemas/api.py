"""Public typed HTTP contracts for the MVP resource and workflow endpoints."""

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.models.enums import MembershipRole
from app.schemas.graph import EntityNode, RelationshipEdge


class Page(BaseModel):
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=50, ge=1, le=100)


class PageResponse(BaseModel):
    items: list[Any]
    offset: int
    limit: int
    total: int


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None


class ProjectResponse(BaseModel):
    id: UUID
    name: str
    description: str | None


class MemberCreate(BaseModel):
    user_id: str = Field(min_length=1, max_length=255)
    role: MembershipRole


class DocumentUploadRequest(BaseModel):
    filename: str = Field(min_length=1)
    media_type: str | None = None
    content_base64: str = Field(min_length=1)
    storage_uri: str = Field(default="managed://api-upload")


class DocumentResponse(BaseModel):
    id: UUID
    name: str
    media_type: str
    created_by: str


class DocumentVersionResponse(BaseModel):
    id: UUID
    document_id: UUID
    version_number: int
    checksum: str
    source_label: str | None


class JobResponse(BaseModel):
    id: UUID
    job_type: str
    state: str
    details: dict[str, object]
    created_at: datetime | None = None


class EntityResponse(EntityNode):
    """List/review view of an entity; ``status_text`` always pairs confidence with its status."""


class RelationshipResponse(RelationshipEdge):
    """List/review view of a relationship."""


class ReviewDecision(BaseModel):
    reason: str | None = None


class EntityCorrection(BaseModel):
    canonical_name: str = Field(min_length=1)
    entity_type: str = Field(min_length=1)
    reason: str = Field(min_length=1)


class RelationshipCorrection(BaseModel):
    source_entity_id: UUID
    target_entity_id: UUID
    relationship_type: str = Field(min_length=1)
    reason: str = Field(min_length=1)


class QueryRequest(BaseModel):
    query: str = Field(min_length=1, max_length=4000)
    document_version_id: UUID | None = None
    #: ``None`` uses the configured default (``RAG_DEFAULT_TOP_K``).
    top_k: int | None = Field(default=None, ge=1, le=50)
    #: SOURCE = retrieval-augmented answer from document text only. HYBRID/GRAPH add graph facts
    #: (available once the graph layer is attached); the mode actually used is echoed back.
    mode: Literal["HYBRID", "GRAPH", "SOURCE"] = "HYBRID"


class ImpactRequest(BaseModel):
    root_entity_id: UUID
    document_version_id: UUID | None = None
    depth: int = Field(default=2, ge=1, le=3)
    node_limit: int = Field(default=100, ge=1, le=250)
    edge_limit: int = Field(default=200, ge=1, le=500)


class ComparisonRequest(BaseModel):
    base_version_id: UUID
    target_version_id: UUID


class ComparisonResponse(BaseModel):
    id: UUID
    base_version_id: UUID
    target_version_id: UUID
    state: str
    requested_by: str
    created_at: datetime | None = None


class ComparisonDetail(ComparisonResponse):
    finding_count: int
    #: Findings per classification (ADDED, REMOVED, MODIFIED, TARGET_CHANGED, ...).
    summary: dict[str, int]


class ComparisonFindingResponse(BaseModel):
    id: UUID
    comparison_id: UUID
    entity_id: UUID | None
    finding_type: str
    confidence: Decimal
    summary: str
    details: dict[str, Any]
