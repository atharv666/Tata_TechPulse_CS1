"""Rule-driven, bounded impact analysis over project-local architectural facts."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, Field

from app.models.enums import ExtractionType, ValidationState
from app.models.schema import Entity, Relationship
from app.retrieval.evidence import Citation, GraphFactEvidence
from app.retrieval.graph import GraphPath


class ImpactKind(StrEnum):
    DIRECT_IMPACT = "DIRECT_IMPACT"
    INDIRECT_IMPACT = "INDIRECT_IMPACT"
    DEPENDENCY = "DEPENDENCY"
    POTENTIAL_CONFLICT = "POTENTIAL_CONFLICT"
    INSUFFICIENT_TRACEABILITY = "UNKNOWN / INSUFFICIENT TRACEABILITY"


SUPPORTED_IMPACT_ENTITY_TYPES = frozenset(
    {
        "INTERFACE",
        "COMPONENT",
        "SOFTWARE_COMPONENT",
        "SIGNAL",
        "DATA_ELEMENT",
        "COMMUNICATION_CHANNEL",
        "FUNCTION",
        "PORT",
        "REQUIREMENT",
        "TEST",
    }
)


@dataclass(frozen=True)
class ImpactRule:
    """A semantic dependency rule, not a generic edge traversal instruction."""

    relationship_types: frozenset[str]
    direction: str = "INCOMING"


DEFAULT_IMPACT_RULES = (
    ImpactRule(frozenset({"REQUIRES", "USES", "DEPENDS_ON", "CONSUMES"}), "INCOMING"),
    ImpactRule(frozenset({"PART_OF", "IMPLEMENTED_BY"}), "INCOMING"),
    ImpactRule(frozenset({"PRODUCES", "CARRIES", "CONNECTS_TO"}), "BOTH"),
)


class ImpactSourceEvidence(BaseModel):
    fact: GraphFactEvidence
    citations: list[Citation]


class ImpactResult(BaseModel):
    kind: ImpactKind
    affected_entity_id: UUID | None
    affected_entity_name: str | None
    affected_entity_type: str | None
    path: GraphPath
    confidence: float | None = Field(default=None, ge=0, le=1)
    extraction_type: ExtractionType | None = None
    validation_state: ValidationState | None = None
    source_evidence: list[ImpactSourceEvidence] = Field(default_factory=list)
    message: str | None = None


class ImpactAnalysisResult(BaseModel):
    root_entity_id: UUID
    results: list[ImpactResult]
    truncated: bool


class ImpactAnalysisService:
    """Runs configured impact rules with strict hop/node/edge bounds and evidence checks."""

    def __init__(self, rules: tuple[ImpactRule, ...] = DEFAULT_IMPACT_RULES) -> None:
        self._rules = rules

    def analyze(
        self,
        project_id: UUID,
        root_entity_id: UUID,
        entities: list[Entity],
        relationships: list[Relationship],
        evidence: dict[UUID, ImpactSourceEvidence],
        document_version_id: UUID | None = None,
        depth: int = 2,
        node_limit: int = 100,
        edge_limit: int = 200,
    ) -> ImpactAnalysisResult:
        if depth < 1 or depth > 3 or node_limit < 1 or edge_limit < 1:
            raise ValueError("Impact analysis limits are outside permitted bounds.")
        local_entities = {
            entity.id: entity
            for entity in entities
            if entity.project_id == project_id
            and entity.entity_type in SUPPORTED_IMPACT_ENTITY_TYPES
        }
        if root_entity_id not in local_entities:
            raise ValueError("Impact root must be a supported entity in the requested project.")
        local_edges = [
            relationship
            for relationship in relationships
            if relationship.project_id == project_id
            and relationship.source_entity_id in local_entities
            and relationship.target_entity_id in local_entities
        ]
        queue: deque[tuple[UUID, tuple[UUID, ...], tuple[UUID, ...], int]] = deque(
            [(root_entity_id, (root_entity_id,), (), 0)]
        )
        visited = {root_entity_id}
        results: list[ImpactResult] = []
        edge_count = 0
        truncated = False
        while queue:
            current, entity_path, relationship_path, current_depth = queue.popleft()
            if current_depth == depth:
                continue
            for edge in local_edges:
                next_node = self._semantic_next_node(edge, current)
                if next_node is None:
                    continue
                edge_count += 1
                if edge_count > edge_limit:
                    truncated = True
                    break
                path = GraphPath(entity_path + (next_node,), relationship_path + (edge.id,))
                next_depth = current_depth + 1
                version_evidence = self._version_evidence(
                    evidence.get(edge.id), document_version_id
                )
                if version_evidence is None:
                    results.append(
                        ImpactResult(
                            kind=ImpactKind.INSUFFICIENT_TRACEABILITY,
                            affected_entity_id=next_node,
                            affected_entity_name=local_entities[next_node].canonical_name,
                            affected_entity_type=local_entities[next_node].entity_type,
                            path=path,
                            message=(
                                "Dependency is present but lacks source evidence for this version."
                            ),
                        )
                    )
                else:
                    results.append(
                        self._impact_result(
                            next_depth,
                            next_node,
                            local_entities[next_node],
                            path,
                            version_evidence,
                        )
                    )
                if next_node not in visited:
                    if len(visited) >= node_limit:
                        truncated = True
                    else:
                        visited.add(next_node)
                        queue.append(
                            (next_node, path.entity_ids, path.relationship_ids, next_depth)
                        )
            if truncated and edge_count > edge_limit:
                break
        return ImpactAnalysisResult(
            root_entity_id=root_entity_id, results=results, truncated=truncated
        )

    def _semantic_next_node(self, edge: Relationship, current: UUID) -> UUID | None:
        for rule in self._rules:
            if edge.relationship_type not in rule.relationship_types:
                continue
            if rule.direction in {"INCOMING", "BOTH"} and edge.target_entity_id == current:
                return edge.source_entity_id
            if rule.direction in {"OUTGOING", "BOTH"} and edge.source_entity_id == current:
                return edge.target_entity_id
        return None

    @staticmethod
    def _version_evidence(
        evidence: ImpactSourceEvidence | None, document_version_id: UUID | None
    ) -> ImpactSourceEvidence | None:
        if evidence is None:
            return None
        citations = (
            [
                citation
                for citation in evidence.citations
                if citation.document_version_id == document_version_id
            ]
            if document_version_id is not None
            else evidence.citations
        )
        if not citations:
            return None
        return ImpactSourceEvidence(fact=evidence.fact, citations=citations)

    @staticmethod
    def _impact_result(
        depth: int,
        entity_id: UUID,
        entity: Entity,
        path: GraphPath,
        evidence: ImpactSourceEvidence,
    ) -> ImpactResult:
        fact = evidence.fact
        return ImpactResult(
            kind=ImpactKind.DIRECT_IMPACT if depth == 1 else ImpactKind.INDIRECT_IMPACT,
            affected_entity_id=entity_id,
            affected_entity_name=entity.canonical_name,
            affected_entity_type=entity.entity_type,
            path=path,
            confidence=fact.confidence,
            extraction_type=fact.extraction_type,
            validation_state=fact.validation_state,
            source_evidence=[evidence],
        )
