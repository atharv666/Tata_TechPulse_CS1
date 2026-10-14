"""Graph retrieval for a question: link -> plan -> bounded SQL traversal -> facts with evidence.

This is the structural half of retrieval (which entities and relationships are relevant). It is
complementary to the passage retrieval in ``app.retrieval.rag``; neither replaces the other. It
only reads: asking a question never mutates the graph.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.graph.facts import GraphFact, GraphFactLoader, path_views
from app.graph.traversal import GraphTraversal, TraversalSpec, TraversedEdge
from app.knowledge.rules import impact_directions
from app.models.schema import Entity, Finding
from app.retrieval.evidence import GraphPathView
from app.retrieval.linking import EntityLinker
from app.retrieval.planning import INCOMING, OUTGOING, QueryIntent, QueryPlan, QueryPlanner

MAX_FACTS = 40
MAX_ROOTS = 3
EDGE_LIMIT_PER_ROOT = 60


@dataclass
class RelatedFinding:
    id: UUID
    finding_type: str
    severity: str
    summary: str


@dataclass
class GraphRetrieval:
    plan: QueryPlan
    facts: list[GraphFact] = field(default_factory=list)
    paths: list[GraphPathView] = field(default_factory=list)
    truncated: bool = False
    findings: list[RelatedFinding] = field(default_factory=list)

    @property
    def found(self) -> bool:
        return bool(self.facts)

    def trace(self) -> dict[str, Any]:
        """Ids and counts only: the trace must not copy document text or the question."""
        return {
            "plan": self.plan.describe(),
            "facts": [
                {
                    "relationship_id": str(fact.relationship_id),
                    "depth": fact.depth,
                    "type": fact.relationship_type,
                    "evidence": len(fact.citations),
                }
                for fact in self.facts
            ],
            "truncated": self.truncated,
        }


class GraphRetriever:
    def __init__(self, session: Session, project_id: UUID) -> None:
        self._session = session
        self._project_id = project_id
        self._traversal = GraphTraversal(session, project_id)
        self._loader = GraphFactLoader(session, project_id)

    def retrieve(
        self,
        question: str,
        document_version_ids: list[UUID] | None = None,
        extra_depth: int = 0,
    ) -> GraphRetrieval:
        links = EntityLinker(self._session, self._project_id).link(question, MAX_ROOTS)
        plan = QueryPlanner().plan(question, links)
        if not plan.use_graph:
            return GraphRetrieval(plan)
        depth = min(3, plan.graph_depth + max(0, extra_depth))
        edges: dict[UUID, TraversedEdge] = {}
        truncated = False
        for root_id in plan.root_ids[:MAX_ROOTS]:
            result = self._traversal.traverse(self._spec(plan, root_id, depth))
            truncated = truncated or result.truncated
            for edge in result.edges:
                edges.setdefault(edge.relationship_id, edge)
        ordered = sorted(
            edges.values(), key=lambda e: (e.depth, e.relationship_type, str(e.relationship_id))
        )
        if len(ordered) > MAX_FACTS:
            truncated = True
            ordered = ordered[:MAX_FACTS]
        facts = self._loader.load(ordered, document_version_ids)
        # A fact with no evidence in the requested document scope cannot ground an answer.
        facts = [fact for fact in facts if fact.citations]
        names = self._names(facts)
        return GraphRetrieval(
            plan,
            facts,
            path_views(facts, names),
            truncated,
            self._findings(plan, facts),
        )

    @staticmethod
    def _spec(plan: QueryPlan, root_id: UUID, depth: int) -> TraversalSpec:
        if plan.intent is QueryIntent.IMPACT:
            follow_out, follow_in = impact_directions()
            return TraversalSpec(root_id, depth, follow_out, follow_in, EDGE_LIMIT_PER_ROOT)
        types = frozenset(plan.relationship_types) or None
        out_types = types if plan.direction in (OUTGOING, "BOTH") else frozenset()
        in_types = types if plan.direction in (INCOMING, "BOTH") else frozenset()
        return TraversalSpec(root_id, depth, out_types, in_types, EDGE_LIMIT_PER_ROOT)

    def _names(self, facts: list[GraphFact]) -> dict[UUID, str]:
        ids = {item for fact in facts for item in fact.node_path}
        if not ids:
            return {}
        return {
            entity_id: name
            for entity_id, name in self._session.execute(
                select(Entity.id, Entity.canonical_name).where(
                    Entity.project_id == self._project_id, Entity.id.in_(ids)
                )
            )
        }

    def _findings(self, plan: QueryPlan, facts: list[GraphFact]) -> list[RelatedFinding]:
        """Open potential inconsistencies about the entities and facts this answer relies on."""
        entity_ids = set(plan.root_ids) | {
            item for fact in facts for item in (fact.source_id, fact.target_id)
        }
        relationship_ids = {fact.relationship_id for fact in facts}
        if not entity_ids and not relationship_ids:
            return []
        rows = self._session.scalars(
            select(Finding)
            .where(
                Finding.project_id == self._project_id,
                Finding.status == "OPEN",
                (Finding.entity_id.in_(entity_ids))
                | (Finding.relationship_id.in_(relationship_ids)),
            )
            .order_by(Finding.severity, Finding.created_at)
            .limit(10)
        )
        return [RelatedFinding(row.id, row.finding_type, row.severity, row.summary) for row in rows]
