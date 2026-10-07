"""Bounded deterministic adjacency traversal and path reconstruction."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from uuid import UUID

from app.core.metrics import metrics
from app.models.schema import Relationship


@dataclass(frozen=True)
class GraphPath:
    entity_ids: tuple[UUID, ...]
    relationship_ids: tuple[UUID, ...]


@dataclass(frozen=True)
class GraphRetrievalResult:
    relationships: tuple[Relationship, ...]
    paths: tuple[GraphPath, ...]
    truncated: bool


class GraphTraversalService:
    """Traverses supplied project-local relationship facts with strict depth/node/edge limits."""

    def traverse(
        self,
        root_id: UUID,
        relationships: list[Relationship],
        direction: str = "BOTH",
        depth: int = 1,
        node_limit: int = 250,
        edge_limit: int = 500,
        relationship_types: tuple[str, ...] = (),
    ) -> GraphRetrievalResult:
        metrics.increment("graph_traversals")
        if depth < 1 or depth > 3 or node_limit < 1 or edge_limit < 1:
            raise ValueError("Traversal limits are outside permitted bounds.")
        visited = {root_id}
        queue: deque[tuple[UUID, tuple[UUID, ...], tuple[UUID, ...], int]] = deque(
            [(root_id, (root_id,), (), 0)]
        )
        result_relationships: list[Relationship] = []
        paths: list[GraphPath] = []
        truncated = False
        while queue:
            node, node_path, edge_path, current_depth = queue.popleft()
            if current_depth == depth:
                continue
            for relationship in relationships:
                if relationship_types and relationship.relationship_type not in relationship_types:
                    continue
                next_node = self._next_node(relationship, node, direction)
                if next_node is None:
                    continue
                if len(result_relationships) >= edge_limit:
                    truncated = True
                    break
                result_relationships.append(relationship)
                next_path = node_path + (next_node,)
                next_edges = edge_path + (relationship.id,)
                paths.append(GraphPath(next_path, next_edges))
                if next_node not in visited:
                    if len(visited) >= node_limit:
                        truncated = True
                    else:
                        visited.add(next_node)
                        queue.append((next_node, next_path, next_edges, current_depth + 1))
            if truncated and len(result_relationships) >= edge_limit:
                break
        metrics.increment("graph_traversal_edges", len(result_relationships))
        if truncated:
            metrics.increment("graph_traversal_truncated")
        return GraphRetrievalResult(tuple(result_relationships), tuple(paths), truncated)

    @staticmethod
    def _next_node(relationship: Relationship, node: UUID, direction: str) -> UUID | None:
        if direction in {"OUTGOING", "BOTH"} and relationship.source_entity_id == node:
            return relationship.target_entity_id
        if direction in {"INCOMING", "BOTH"} and relationship.target_entity_id == node:
            return relationship.source_entity_id
        return None
