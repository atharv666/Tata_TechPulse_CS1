"""HTTP contracts for the knowledge graph: entity/relationship detail, findings and merges."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, computed_field

from app.schemas.review import ProvenanceDisplay, ValidationHistoryItem


def status_text(confidence: Decimal, extraction_type: str, validation_state: str) -> str:
    """A confidence number is never shown without its extraction and validation context."""
    return f"Confidence {float(confidence):.2f} · {extraction_type} · {validation_state}"


class FactSummary(BaseModel):
    """The shared header of an entity or a relationship."""

    confidence: Decimal
    extraction_type: str
    validation_state: str

    @computed_field  # type: ignore[prop-decorator]
    @property
    def status_text(self) -> str:
        return status_text(self.confidence, self.extraction_type, self.validation_state)


class EntityNode(FactSummary):
    id: UUID
    canonical_name: str
    entity_type: str
    trust_state: str
    raw_confidence: Decimal | None = None
    merged_into_id: UUID | None = None
    superseded_by_id: UUID | None = None


class RelationshipEdge(FactSummary):
    id: UUID
    source_entity_id: UUID
    target_entity_id: UUID
    relationship_type: str
    trust_state: str
    raw_confidence: Decimal | None = None
    superseded_by_id: UUID | None = None


class AliasDisplay(BaseModel):
    alias: str
    source: str


class MergedEntityDisplay(BaseModel):
    merge_id: UUID
    entity_id: UUID
    name: str
    decided_by: str
    similarity: Decimal | None
    reason: str | None
    created_at: datetime | None


class FindingResponse(BaseModel):
    id: UUID
    finding_type: str
    severity: str
    status: str
    summary: str
    details: dict[str, Any]
    entity_id: UUID | None
    relationship_id: UUID | None
    confidence: Decimal | None
    detected_by: str
    dismissed_by: str | None
    dismissed_reason: str | None
    created_at: datetime | None


class EndpointDisplay(BaseModel):
    id: UUID
    name: str
    entity_type: str


class EntityDetail(EntityNode):
    aliases: list[AliasDisplay]
    merged_entities: list[MergedEntityDisplay]
    evidence: list[ProvenanceDisplay]
    history: list[ValidationHistoryItem]
    relationship_count: int
    findings: list[FindingResponse]


class RelationshipDetail(RelationshipEdge):
    source: EndpointDisplay
    target: EndpointDisplay
    evidence: list[ProvenanceDisplay]
    history: list[ValidationHistoryItem]
    findings: list[FindingResponse]


class MergeResponse(BaseModel):
    id: UUID
    canonical_entity_id: UUID
    canonical_name: str
    merged_entity_id: UUID
    merged_name: str
    decided_by: str
    rule: str | None
    similarity: Decimal | None
    reason: str | None
    llm_model: str | None
    blocking_keys: list[str]
    created_at: datetime | None
    undone_at: datetime | None
    undone_by: str | None


class DismissRequest(BaseModel):
    reason: str = Field(min_length=3, max_length=2000)


class UndoMergeRequest(BaseModel):
    reason: str = Field(min_length=3, max_length=2000)


class MemberResponse(BaseModel):
    user_id: str
    role: str


class RelatedItem(FactSummary):
    """One neighbour of an entity, with the relationship that links them and its source."""

    relationship_id: UUID
    entity_id: UUID
    name: str
    entity_type: str
    #: The first source passage that states the relationship (full detail: relationship detail).
    source_document: str | None = None
    source_section: str | None = None
    source_page: int | None = None
    source_excerpt: str | None = None


class EntityReport(BaseModel):
    """A one-page structured view of a component, interface, signal or flow."""

    entity: EntityNode
    aliases: list[str]
    #: Relationships *from* this entity, grouped by type (PROVIDES, REQUIRES, USES, ...).
    outgoing: dict[str, list[RelatedItem]]
    #: Relationships *to* this entity, grouped by type (who requires it, who provides it, ...).
    incoming: dict[str, list[RelatedItem]]
    findings: list[FindingResponse]
    evidence: list[ProvenanceDisplay]
