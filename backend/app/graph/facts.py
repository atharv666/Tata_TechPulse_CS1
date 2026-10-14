"""Turn traversed edges into graph facts with their source evidence (provenance).

A relationship alone is never final-answer evidence. Every fact returned here carries the
originating passages: relationship -> evidence -> chunk -> section -> document version -> page, with
the fact's confidence, extraction type and validation state beside it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.graph.traversal import TraversedEdge
from app.models.enums import ExtractionType, ValidationState
from app.models.schema import (
    Chunk,
    Document,
    DocumentVersion,
    Entity,
    Relationship,
    RelationshipEvidence,
    Section,
)
from app.retrieval.evidence import Citation, GraphFactEvidence, GraphPathView

EVIDENCE_PER_FACT = 2


@dataclass(frozen=True)
class GraphFact:
    relationship_id: UUID
    source_id: UUID
    source_name: str
    source_type: str
    target_id: UUID
    target_name: str
    target_type: str
    relationship_type: str
    confidence: float
    extraction_type: str
    validation_state: str
    depth: int
    from_id: UUID
    to_id: UUID
    node_path: tuple[UUID, ...] = ()
    edge_path: tuple[UUID, ...] = ()
    citations: tuple[Citation, ...] = field(default_factory=tuple)

    @property
    def statement(self) -> str:
        return f"{self.source_name} {self.relationship_type} {self.target_name}"

    def to_evidence(self) -> GraphFactEvidence:
        return GraphFactEvidence(
            fact_id=str(self.relationship_id),
            source_entity=self.source_name,
            relationship_type=self.relationship_type,
            target_entity=self.target_name,
            confidence=self.confidence,
            extraction_type=ExtractionType(self.extraction_type),
            validation_state=ValidationState(self.validation_state),
            citation_ids=[citation.citation_id for citation in self.citations],
        )


class GraphFactLoader:
    def __init__(self, session: Session, project_id: UUID) -> None:
        self._session = session
        self._project_id = project_id

    def load(
        self,
        edges: list[TraversedEdge] | tuple[TraversedEdge, ...],
        document_version_id: UUID | list[UUID] | None = None,
    ) -> list[GraphFact]:
        """Facts in the order of ``edges``; a fact with no evidence in scope is still returned.

        Callers decide what to do with an unsupported fact (the impact analysis labels it
        "insufficient traceability"; the answer pipeline does not cite it).
        """
        if not edges:
            return []
        relationships = {
            row.id: row
            for row in self._session.scalars(
                select(Relationship).where(
                    Relationship.project_id == self._project_id,
                    Relationship.id.in_({edge.relationship_id for edge in edges}),
                )
            )
        }
        entity_ids = {edge.source_id for edge in edges} | {edge.target_id for edge in edges}
        entities = {
            row.id: row
            for row in self._session.scalars(
                select(Entity).where(
                    Entity.project_id == self._project_id, Entity.id.in_(entity_ids)
                )
            )
        }
        evidence = self._evidence(set(relationships), document_version_id)
        facts: list[GraphFact] = []
        for edge in edges:
            relationship = relationships.get(edge.relationship_id)
            source, target = entities.get(edge.source_id), entities.get(edge.target_id)
            if relationship is None or source is None or target is None:
                continue
            facts.append(
                GraphFact(
                    relationship_id=relationship.id,
                    source_id=source.id,
                    source_name=source.canonical_name,
                    source_type=source.entity_type,
                    target_id=target.id,
                    target_name=target.canonical_name,
                    target_type=target.entity_type,
                    relationship_type=relationship.relationship_type,
                    confidence=float(relationship.confidence),
                    extraction_type=relationship.extraction_type.value,
                    validation_state=relationship.validation_state.value,
                    depth=edge.depth,
                    from_id=edge.from_id,
                    to_id=edge.to_id,
                    node_path=edge.node_path,
                    edge_path=edge.edge_path,
                    citations=tuple(evidence.get(relationship.id, ())),
                )
            )
        return facts

    def _evidence(
        self, relationship_ids: set[UUID], document_version_id: UUID | list[UUID] | None
    ) -> dict[UUID, list[Citation]]:
        statement = (
            select(RelationshipEvidence, Chunk, Section, DocumentVersion, Document)
            .join(Chunk, Chunk.id == RelationshipEvidence.chunk_id)
            .join(Section, Section.id == Chunk.section_id)
            .join(DocumentVersion, DocumentVersion.id == Chunk.document_version_id)
            .join(Document, Document.id == DocumentVersion.document_id)
            .where(
                RelationshipEvidence.project_id == self._project_id,
                RelationshipEvidence.relationship_id.in_(relationship_ids),
            )
            .order_by(
                RelationshipEvidence.relationship_id, Chunk.document_version_id, Chunk.ordinal
            )
        )
        if isinstance(document_version_id, UUID):
            statement = statement.where(Chunk.document_version_id == document_version_id)
        elif document_version_id:
            statement = statement.where(Chunk.document_version_id.in_(document_version_id))
        found: dict[UUID, list[Citation]] = {}
        for evidence, chunk, section, version, document in self._session.execute(
            statement
        ).tuples():
            bucket = found.setdefault(evidence.relationship_id, [])
            if len(bucket) >= EVIDENCE_PER_FACT:
                continue
            bucket.append(
                Citation(
                    citation_id=f"chunk:{chunk.id}",
                    chunk_id=chunk.id,
                    document_id=document.id,
                    document_version_id=version.id,
                    document_name=document.name,
                    section_heading=section.heading,
                    section_path=section.path or "",
                    page_start=chunk.page_start,
                    page_end=chunk.page_end,
                    excerpt=evidence.excerpt,
                    role="GRAPH_EVIDENCE",
                    kind=chunk.chunk_kind,
                )
            )
        return found


def path_views(facts: list[GraphFact], names: dict[UUID, str]) -> list[GraphPathView]:
    """One path per fact: root -> ... -> the entity this fact reached."""
    by_relationship = {fact.relationship_id: fact for fact in facts}
    views: list[GraphPathView] = []
    for fact in facts:
        types = [
            by_relationship[edge_id].relationship_type
            for edge_id in fact.edge_path
            if edge_id in by_relationship
        ]
        views.append(
            GraphPathView(
                entity_ids=[str(item) for item in fact.node_path],
                entity_names=[names.get(item, "?") for item in fact.node_path],
                relationship_ids=[str(item) for item in fact.edge_path],
                relationship_types=types,
            )
        )
    return views
