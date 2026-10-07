"""Complementary graph and vector retrieval orchestration without answer generation."""

from __future__ import annotations

from dataclasses import dataclass

from app.models.schema import Relationship
from app.repositories.vectors import VectorRepository, VectorSearchHit
from app.retrieval.graph import GraphRetrievalResult, GraphTraversalService
from app.retrieval.planning import QueryPlan
from app.retrieval.vector import VectorRetrievalService


@dataclass(frozen=True)
class HybridRetrievalResult:
    plan: QueryPlan
    graph: GraphRetrievalResult | None
    vector_hits: tuple[VectorSearchHit, ...]


class HybridRetrievalService:
    def __init__(self, vectors: VectorRetrievalService, graph: GraphTraversalService) -> None:
        self._vectors = vectors
        self._graph = graph

    async def retrieve(
        self,
        plan: QueryPlan,
        vector_repository: VectorRepository,
        graph_relationships: list[Relationship],
        top_k: int = 8,
    ) -> HybridRetrievalResult:
        vector_hits = await self._vectors.search(
            vector_repository, plan.normalized_query, top_k, plan.document_version_id
        )
        graph_result = None
        if plan.use_graph and plan.entity_id is not None:
            graph_result = self._graph.traverse(
                plan.entity_id,
                graph_relationships,
                plan.direction,
                plan.graph_depth,
                relationship_types=plan.relationship_types,
            )
        return HybridRetrievalResult(plan, graph_result, tuple(vector_hits))
