"""Typed review, provenance, and audit display contracts."""

from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.models.enums import ExtractionType, SourceClassification, ValidationState


class ProvenanceDisplay(BaseModel):
    chunk_id: UUID
    document_id: UUID
    document_version_id: UUID
    document_name: str
    section_heading: str
    page_start: int | None
    page_end: int | None
    source_classification: SourceClassification
    excerpt: str
    start_offset: int | None
    end_offset: int | None


class ReviewQueueItem(BaseModel):
    fact_kind: Literal["ENTITY", "RELATIONSHIP"]
    fact_id: UUID
    label: str
    confidence: Decimal = Field(ge=0, le=1)
    extraction_type: ExtractionType
    validation_state: ValidationState
    provenance: list[ProvenanceDisplay]


class ValidationHistoryItem(BaseModel):
    state: ValidationState
    actor_id: str
    reason: str | None
    created_at: datetime | None


class AuditEventDisplay(BaseModel):
    action: str
    resource_type: str
    resource_id: UUID
    actor_id: str
    details: dict[str, object]
    created_at: datetime | None
