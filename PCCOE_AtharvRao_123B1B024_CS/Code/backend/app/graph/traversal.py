"""Bounded graph traversal executed by PostgreSQL (a recursive CTE), never in Python.

The question planner decides *what* to traverse (root, direction, relationship types, depth);
this module only runs a fixed, parameterised query. Nothing here accepts model-written SQL.

Bounds: depth 1-3, a hard edge limit, and cycle protection (an edge is never walked twice on one
path, so a cycle terminates and its closing edge is still reported). Only *live* facts are
walked: relationships superseded by a reviewer or collapsed by a merge, relationships that touch
merged / replaced entities, and (unless asked) rejected facts are invisible to the traversal.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Session
from sqlalchemy.types import String

from app.core.metrics import metrics
from app.extraction.taxonomy import RELATIONSHIP_TYPES

MAX_DEPTH = 3
MAX_EDGE_LIMIT = 500

_WALK = text(
    """
    WITH RECURSIVE live AS (
        SELECT r.id, r.source_entity_id AS src, r.target_entity_id AS dst,
               r.relationship_type AS kind
        FROM relationships r
        JOIN entities s ON s.id = r.source_entity_id
        JOIN entities t ON t.id = r.target_entity_id
        WHERE r.project_id = :project_id
          AND r.superseded_by_id IS NULL
          AND NOT jsonb_exists(r.attributes, 'inactive_reason')
          AND s.merged_into_id IS NULL AND s.superseded_by_id IS NULL
          AND t.merged_into_id IS NULL AND t.superseded_by_id IS NULL
          AND (:include_rejected
               OR (r.validation_state <> 'REJECTED'
                   AND s.validation_state <> 'REJECTED'
                   AND t.validation_state <> 'REJECTED'))
    ),
    walk (rel_id, src, dst, kind, from_id, to_id, depth, node_path, edge_path) AS (
        SELECT l.id, l.src, l.dst, l.kind, :root,
               CASE WHEN l.src = :root THEN l.dst ELSE l.src END,
               1,
               ARRAY[:root, CASE WHEN l.src = :root THEN l.dst ELSE l.src END],
               ARRAY[l.id]
        FROM live l
        WHERE (l.src = :root AND l.kind = ANY(:follow_out))
           OR (l.dst = :root AND l.kind = ANY(:follow_in))
      UNION ALL
        SELECT l.id, l.src, l.dst, l.kind, w.to_id,
               CASE WHEN l.src = w.to_id THEN l.dst ELSE l.src END,
               w.depth + 1,
               w.node_path || CASE WHEN l.src = w.to_id THEN l.dst ELSE l.src END,
               w.edge_path || l.id
        FROM walk w
        JOIN live l ON (l.src = w.to_id OR l.dst = w.to_id)
        WHERE w.depth < :depth
          AND NOT (l.id = ANY(w.edge_path))
          AND ((l.src = w.to_id AND l.kind = ANY(:follow_out))
            OR (l.dst = w.to_id AND l.kind = ANY(:follow_in)))
    )
    SELECT rel_id, src, dst, kind, from_id, to_id, depth, node_path, edge_path
    FROM walk
    LIMIT :row_limit
    """
).bindparams(
    bindparam("follow_out", type_=ARRAY(String())),
    bindparam("follow_in", type_=ARRAY(String())),
)


@dataclass(frozen=True)
class TraversalSpec:
    root_id: UUID
    depth: int = 1
    #: Relationship types that may be walked from source to target / from target to source.
    #: ``None`` means every type in the controlled taxonomy.
    follow_out: frozenset[str] | None = None
    follow_in: frozenset[str] | None = None
    edge_limit: int = 200
    include_rejected: bool = False

    @staticmethod
    def both(
        root_id: UUID, types: Iterable[str] = (), depth: int = 1, edge_limit: int = 200
    ) -> TraversalSpec:
        chosen = frozenset(types) or None
        return TraversalSpec(root_id, depth, chosen, chosen, edge_limit)

    @staticmethod
    def outgoing(
        root_id: UUID, types: Iterable[str] = (), depth: int = 1, edge_limit: int = 200
    ) -> TraversalSpec:
        return TraversalSpec(root_id, depth, frozenset(types) or None, frozenset(), edge_limit)

    @staticmethod
    def incoming(
        root_id: UUID, types: Iterable[str] = (), depth: int = 1, edge_limit: int = 200
    ) -> TraversalSpec:
        return TraversalSpec(root_id, depth, frozenset(), frozenset(types) or None, edge_limit)


@dataclass(frozen=True)
class TraversedEdge:
    relationship_id: UUID
    source_id: UUID
    target_id: UUID
    relationship_type: str
    from_id: UUID  # the node the walk was standing on
    to_id: UUID  # the node it reached through this edge
    depth: int
    node_path: tuple[UUID, ...]
    edge_path: tuple[UUID, ...]


@dataclass(frozen=True)
class TraversalResult:
    root_id: UUID
    edges: tuple[TraversedEdge, ...]
    truncated: bool

    @property
    def node_depths(self) -> dict[UUID, int]:
        """Shortest hop count at which each reached node (other than the root) was first seen."""
        depths: dict[UUID, int] = {}
        for edge in self.edges:
            if edge.to_id != self.root_id:
                depths.setdefault(edge.to_id, edge.depth)
        return depths


class GraphTraversal:
    def __init__(self, session: Session, project_id: UUID) -> None:
        self._session = session
        self._project_id = project_id

    def traverse(self, spec: TraversalSpec) -> TraversalResult:
        if not 1 <= spec.depth <= MAX_DEPTH:
            raise ValueError(f"Traversal depth must be between 1 and {MAX_DEPTH}.")
        if not 1 <= spec.edge_limit <= MAX_EDGE_LIMIT:
            raise ValueError(f"Traversal edge limit must be between 1 and {MAX_EDGE_LIMIT}.")
        everything = frozenset(RELATIONSHIP_TYPES)
        follow_out = everything if spec.follow_out is None else spec.follow_out & everything
        follow_in = everything if spec.follow_in is None else spec.follow_in & everything
        rows = self._session.execute(
            _WALK,
            {
                "project_id": self._project_id,
                "root": spec.root_id,
                "depth": spec.depth,
                "follow_out": sorted(follow_out),
                "follow_in": sorted(follow_in),
                "include_rejected": spec.include_rejected,
                "row_limit": spec.edge_limit * 4 + 1,  # a safety valve; edges are de-duplicated
            },
        ).all()
        edges: dict[UUID, TraversedEdge] = {}
        for row in sorted(rows, key=lambda r: (r.depth, r.kind, str(r.rel_id))):
            if row.rel_id in edges:
                continue  # reached again through a longer path: keep the shortest
            edges[row.rel_id] = TraversedEdge(
                relationship_id=row.rel_id,
                source_id=row.src,
                target_id=row.dst,
                relationship_type=row.kind,
                from_id=row.from_id,
                to_id=row.to_id,
                depth=row.depth,
                node_path=tuple(row.node_path),
                edge_path=tuple(row.edge_path),
            )
        ordered = list(edges.values())
        truncated = len(ordered) > spec.edge_limit or len(rows) > spec.edge_limit * 4
        metrics.increment("graph_traversals")
        metrics.increment("graph_traversal_edges", min(len(ordered), spec.edge_limit))
        if truncated:
            metrics.increment("graph_traversal_truncated")
        return TraversalResult(spec.root_id, tuple(ordered[: spec.edge_limit]), truncated)
