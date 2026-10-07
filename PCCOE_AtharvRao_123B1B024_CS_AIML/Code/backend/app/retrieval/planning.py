"""Deterministic query normalization, linking, and bounded plan creation."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

from app.canonicalization.core import (
    EntityCandidate,
    EntityResolver,
    Resolution,
    ResolutionState,
    normalize_name,
)


class QueryIntent(StrEnum):
    RELATIONSHIP_LOOKUP = "RELATIONSHIP_LOOKUP"
    DEPENDENCY = "DEPENDENCY"
    IMPACT = "IMPACT"
    SOURCE_SEARCH = "SOURCE_SEARCH"


@dataclass(frozen=True)
class QueryPlan:
    normalized_query: str
    intent: QueryIntent
    entity_name: str | None
    entity_id: UUID | None
    ambiguous_entity_ids: tuple[UUID, ...]
    direction: str
    relationship_types: tuple[str, ...]
    graph_depth: int
    use_vector: bool
    use_graph: bool
    document_version_id: UUID | None


class QueryPlanner:
    """Builds typed retrieval plans; it never executes model-authored SQL."""

    def __init__(self, resolver: EntityResolver | None = None) -> None:
        self._resolver = resolver or EntityResolver()

    def plan(
        self,
        query: str,
        project_id: UUID,
        candidates: list[EntityCandidate],
        document_version_id: UUID | None = None,
    ) -> QueryPlan:
        normalized = " ".join(query.split())
        intent = self._intent(normalized)
        mention = self._entity_mention(normalized, candidates)
        resolution = self._resolve(project_id, mention, candidates)
        direction, relationship_types = self._relationship_interpretation(normalized, intent)
        return QueryPlan(
            normalized,
            intent,
            mention,
            resolution.entity_id,
            resolution.candidates if resolution.state is ResolutionState.AMBIGUOUS else (),
            direction,
            relationship_types,
            3 if intent is QueryIntent.IMPACT else 2 if intent is QueryIntent.DEPENDENCY else 1,
            True,
            resolution.entity_id is not None,
            document_version_id,
        )

    @staticmethod
    def _intent(query: str) -> QueryIntent:
        lowered = query.casefold()
        if any(term in lowered for term in ("impact", "affected", "affect if", "change")):
            return QueryIntent.IMPACT
        if any(term in lowered for term in ("depend", "dependency", "requires")):
            return QueryIntent.DEPENDENCY
        if any(
            term in lowered for term in ("connect", "provide", "consume", "use", "relationship")
        ):
            return QueryIntent.RELATIONSHIP_LOOKUP
        return QueryIntent.SOURCE_SEARCH

    @staticmethod
    def _entity_mention(query: str, candidates: list[EntityCandidate]) -> str | None:
        lowered = normalize_name(query)
        matches = [
            candidate.canonical_name
            for candidate in candidates
            if normalize_name(candidate.canonical_name) in lowered
        ]
        return max(matches, key=len) if matches else None

    def _resolve(
        self, project_id: UUID, mention: str | None, candidates: list[EntityCandidate]
    ) -> Resolution:
        if mention is None:
            return Resolution(ResolutionState.UNRESOLVED)
        matching_types = {
            candidate.entity_type
            for candidate in candidates
            if normalize_name(candidate.canonical_name) == normalize_name(mention)
        }
        if len(matching_types) != 1:
            return Resolution(
                ResolutionState.AMBIGUOUS,
                candidates=tuple(
                    candidate.id
                    for candidate in candidates
                    if normalize_name(candidate.canonical_name) == normalize_name(mention)
                ),
            )
        return self._resolver.resolve(project_id, mention, matching_types.pop(), candidates)

    @staticmethod
    def _relationship_interpretation(
        query: str, intent: QueryIntent
    ) -> tuple[str, tuple[str, ...]]:
        lowered = query.casefold()
        if intent in {QueryIntent.DEPENDENCY, QueryIntent.IMPACT} or "depend" in lowered:
            return "INCOMING", ("DEPENDS_ON", "REQUIRES", "USES")
        if "provide" in lowered:
            return "OUTGOING", ("PROVIDES",)
        if "consume" in lowered:
            return "OUTGOING", ("CONSUMES",)
        return "BOTH", ()
