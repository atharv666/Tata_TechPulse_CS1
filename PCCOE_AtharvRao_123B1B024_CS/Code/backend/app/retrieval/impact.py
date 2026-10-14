"""Change-impact analysis: "what could be affected if X changes?".

The traversal runs in PostgreSQL (``app.graph.traversal``) under the propagation rules in
``app.knowledge.rules`` (data, documented in ADR-005): a REQUIRES/USES/CONSUMES edge propagates a
change from the thing used to its user, a PROVIDES edge in both directions, flow edges downstream,
VERIFIED_BY towards the tests. Each affected entity is reported with its hop distance and the
chain of facts that connects it to the changed entity, and every fact on the chain carries its
source evidence. A link without source evidence for the requested version is reported as
"insufficient traceability" instead of being silently trusted.

Wording matters: results are *potentially* affected items for an engineer to assess, not verdicts.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import ConflictError, NotFoundError
from app.graph.facts import GraphFact, GraphFactLoader
from app.graph.traversal import GraphTraversal, TraversalSpec
from app.knowledge.rules import impact_directions
from app.models.enums import ExtractionType, ValidationState
from app.models.schema import Entity
from app.retrieval.evidence import Citation, GraphFactEvidence


class ImpactKind(StrEnum):
    DIRECT_IMPACT = "DIRECT_IMPACT"
    INDIRECT_IMPACT = "INDIRECT_IMPACT"
    DEPENDENCY = "DEPENDENCY"
    POTENTIAL_CONFLICT = "POTENTIAL_CONFLICT"
    INSUFFICIENT_TRACEABILITY = "UNKNOWN / INSUFFICIENT TRACEABILITY"


@dataclass(frozen=True)
class GraphPath:
    entity_ids: tuple[UUID, ...]
    relationship_ids: tuple[UUID, ...]


class ImpactSourceEvidence(BaseModel):
    fact: GraphFactEvidence
    citations: list[Citation]


class ImpactResult(BaseModel):
    kind: ImpactKind
    affected_entity_id: UUID | None
    affected_entity_name: str | None
    affected_entity_type: str | None
    path: GraphPath
    hops: int = Field(ge=1, le=3)
    #: Human-readable chain, e.g. "WheelSpeedInterface <- BrakeController (REQUIRES)".
    via: list[str] = Field(default_factory=list)
    confidence: float | None = Field(default=None, ge=0, le=1)
    extraction_type: ExtractionType | None = None
    validation_state: ValidationState | None = None
    source_evidence: list[ImpactSourceEvidence] = Field(default_factory=list)
    message: str | None = None


class ImpactAnalysisResult(BaseModel):
    root_entity_id: UUID
    root_entity_name: str = ""
    results: list[ImpactResult]
    truncated: bool
    #: Affected entities per entity type, for a quick overview.
    summary: dict[str, int] = Field(default_factory=dict)
    affected_tests: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class ImpactAnalysisService:
    def __init__(self, session: Session, project_id: UUID) -> None:
        self._session = session
        self._project_id = project_id

    def analyze(
        self,
        root_entity_id: UUID,
        document_version_id: UUID | None = None,
        depth: int = 2,
        node_limit: int = 100,
        edge_limit: int = 200,
    ) -> ImpactAnalysisResult:
        if not 1 <= depth <= 3 or node_limit < 1 or edge_limit < 1:
            raise ValueError("Impact analysis limits are outside permitted bounds.")
        root = self._root(root_entity_id)
        follow_out, follow_in = impact_directions()
        traversal = GraphTraversal(self._session, self._project_id).traverse(
            TraversalSpec(root.id, depth, follow_out, follow_in, min(edge_limit, 500))
        )
        facts = GraphFactLoader(self._session, self._project_id).load(
            traversal.edges, document_version_id
        )
        by_relationship = {fact.relationship_id: fact for fact in facts}
        affected = self._affected(root.id, facts, traversal.node_depths)
        names = self._entity_names({root.id, *affected})
        results: list[ImpactResult] = []
        truncated = traversal.truncated
        for entity_id, fact in sorted(
            affected.items(), key=lambda item: (item[1].depth, str(item[0]))
        ):
            if len(results) >= node_limit:
                truncated = True
                break
            results.append(self._result(entity_id, fact, by_relationship, names))
        summary: dict[str, int] = {}
        tests: list[str] = []
        for result in results:
            kind = result.affected_entity_type or "UNKNOWN"
            summary[kind] = summary.get(kind, 0) + 1
            if kind == "TEST_CASE" and result.affected_entity_name:
                tests.append(result.affected_entity_name)
        notes = [
            "Results are potentially affected items, not confirmed impacts; each needs "
            "engineering assessment.",
        ]
        if not results:
            notes.append("No dependent or related elements were found in the knowledge graph.")
        return ImpactAnalysisResult(
            root_entity_id=root.id,
            root_entity_name=root.canonical_name,
            results=results,
            truncated=truncated,
            summary=dict(sorted(summary.items())),
            affected_tests=sorted(tests),
            notes=notes,
        )

    # -- helpers -----------------------------------------------------------------------------
    def _root(self, entity_id: UUID) -> Entity:
        root = self._session.scalar(
            select(Entity).where(Entity.project_id == self._project_id, Entity.id == entity_id)
        )
        if root is None:
            raise NotFoundError("ENTITY_NOT_FOUND", "Impact root was not found in this project.")
        if (
            root.merged_into_id is not None
            or root.superseded_by_id is not None
            or root.validation_state is ValidationState.REJECTED
        ):
            raise ConflictError(
                "ENTITY_NOT_ACTIVE",
                "The impact root is merged, replaced or rejected; analyse the live entity.",
            )
        return root

    @staticmethod
    def _affected(
        root_id: UUID, facts: list[GraphFact], depths: dict[UUID, int]
    ) -> dict[UUID, GraphFact]:
        """For every reached entity the fact that first reached it (shortest path)."""
        reached: dict[UUID, GraphFact] = {}
        for fact in sorted(facts, key=lambda item: (item.depth, item.relationship_type)):
            if fact.to_id == root_id or fact.to_id in reached:
                continue
            if depths.get(fact.to_id) != fact.depth:
                continue
            reached[fact.to_id] = fact
        return reached

    def _entity_names(self, entity_ids: set[UUID]) -> dict[UUID, tuple[str, str]]:
        return {
            entity_id: (name, entity_type)
            for entity_id, name, entity_type in self._session.execute(
                select(Entity.id, Entity.canonical_name, Entity.entity_type).where(
                    Entity.project_id == self._project_id, Entity.id.in_(entity_ids)
                )
            )
        }

    def _result(
        self,
        entity_id: UUID,
        reaching: GraphFact,
        by_relationship: dict[UUID, GraphFact],
        names: dict[UUID, tuple[str, str]],
    ) -> ImpactResult:
        chain = [by_relationship[item] for item in reaching.edge_path if item in by_relationship]
        name, entity_type = names.get(entity_id, ("?", "UNKNOWN"))
        path = GraphPath(reaching.node_path, reaching.edge_path)
        via = [f"{fact.source_name} {fact.relationship_type} {fact.target_name}" for fact in chain]
        missing = [fact for fact in chain if not fact.citations]
        if len(chain) != len(reaching.edge_path) or missing:
            return ImpactResult(
                kind=ImpactKind.INSUFFICIENT_TRACEABILITY,
                affected_entity_id=entity_id,
                affected_entity_name=name,
                affected_entity_type=entity_type,
                path=path,
                hops=reaching.depth,
                via=via,
                message="A dependency on this path has no source evidence for this version.",
            )
        extraction = (
            ExtractionType.INFERRED
            if any(fact.extraction_type == "INFERRED" for fact in chain)
            else ExtractionType.EXPLICIT
        )
        return ImpactResult(
            kind=ImpactKind.DIRECT_IMPACT if reaching.depth == 1 else ImpactKind.INDIRECT_IMPACT,
            affected_entity_id=entity_id,
            affected_entity_name=name,
            affected_entity_type=entity_type,
            path=path,
            hops=reaching.depth,
            via=via,
            confidence=min(
                fact.confidence for fact in chain
            ),  # a chain is as strong as its weakest link
            extraction_type=extraction,
            validation_state=_weakest_validation(chain),
            source_evidence=[
                ImpactSourceEvidence(fact=fact.to_evidence(), citations=list(fact.citations))
                for fact in chain
            ],
        )


def _weakest_validation(chain: list[GraphFact]) -> ValidationState:
    states = {fact.validation_state for fact in chain}
    for state in ("PENDING", "HUMAN_CORRECTED", "HUMAN_VERIFIED"):
        if state in states:
            return ValidationState(state)
    return ValidationState.PENDING
