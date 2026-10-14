"""Typed evidence and answer contracts: citations, graph facts and the grounded answer."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from app.models.enums import ExtractionType, ValidationState


class Citation(BaseModel):
    citation_id: str
    chunk_id: UUID
    document_id: UUID
    document_version_id: UUID
    document_name: str
    section_heading: str
    page_start: int | None
    page_end: int | None
    excerpt: str
    #: Ancestor headings of the cited chunk, e.g. ``1 Overview > 1.1 Components``.
    section_path: str = ""
    #: HIT = matched text, PARENT_LEAD / NEIGHBOR = context added around a hit.
    role: str = "HIT"
    kind: str = "TEXT"
    truncated: bool = False
    #: The source document's own declared status (Approved, Draft, ...), when it states one.
    document_status: str | None = None


class GraphFactEvidence(BaseModel):
    fact_id: str
    source_entity: str
    relationship_type: str
    target_entity: str
    confidence: float = Field(ge=0, le=1)
    extraction_type: ExtractionType
    validation_state: ValidationState
    citation_ids: list[str]


class EvidenceBundle(BaseModel):
    project_id: UUID
    query: str
    citations: list[Citation]
    graph_facts: list[GraphFactEvidence]
    conflicts: list[str] = Field(default_factory=list)


class AnswerClaim(BaseModel):
    text: str = Field(min_length=1)
    citation_ids: list[str] = Field(min_length=1)
    extraction_type: ExtractionType
    #: Share of the claim's salient terms found in the cited text (deterministic check).
    support: float | None = None


class GraphPathView(BaseModel):
    entity_ids: list[str]
    entity_names: list[str]
    relationship_ids: list[str]
    relationship_types: list[str]


class RelatedFindingView(BaseModel):
    """An open potential inconsistency about something the answer relies on."""

    id: str
    finding_type: str
    severity: str
    summary: str


class GroundedAnswer(BaseModel):
    status: str
    summary: str
    claims: list[AnswerClaim] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)
    conflicts: list[str] = Field(default_factory=list)
    insufficient_evidence: bool = False
    #: Groundedness of the answer (share of claims that survived verification x their mean support).
    #: It is NOT a probability that the architecture statement is correct; see ``confidence_basis``.
    confidence: float | None = None
    confidence_basis: str = ""
    limitations: list[str] = Field(default_factory=list)
    graph_facts: list[GraphFactEvidence] = Field(default_factory=list)
    graph_paths: list[GraphPathView] = Field(default_factory=list)
    related_findings: list[RelatedFindingView] = Field(default_factory=list)
    retrieval_trace: dict[str, Any] = Field(default_factory=dict)
    mode: str = "SOURCE"
    dropped_claims: int = 0
