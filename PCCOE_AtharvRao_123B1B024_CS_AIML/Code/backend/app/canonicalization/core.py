"""Conservative, deterministic entity and relationship canonicalization primitives."""

from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from enum import StrEnum
from math import sqrt
from uuid import UUID

from pydantic import BaseModel

from app.core.metrics import metrics
from app.providers.contracts import LLMMessage, LLMProvider, LLMRequest


class ResolutionState(StrEnum):
    EXACT = "EXACT"
    ALIAS = "ALIAS"
    MERGED = "MERGED"
    AMBIGUOUS = "AMBIGUOUS"
    UNRESOLVED = "UNRESOLVED"


TYPE_ALIASES = {
    "SWC": "SOFTWARE_COMPONENT",
    "SOFTWARE COMPONENT": "SOFTWARE_COMPONENT",
    "DATAELEMENT": "DATA_ELEMENT",
    "COMMUNICATION CHANNEL": "COMMUNICATION_CHANNEL",
    "DATATYPE": "DATA_TYPE",
}
RELATIONSHIP_ALIASES = {
    "USE": "USES",
    "USES": "USES",
    "UTILIZE": "USES",
    "UTILIZES": "USES",
    "REQUIRE": "REQUIRES",
    "REQUIRES": "REQUIRES",
    "PROVIDE": "PROVIDES",
    "PROVIDES": "PROVIDES",
    "CONSUME": "CONSUMES",
    "CONSUMES": "CONSUMES",
    "PRODUCE": "PRODUCES",
    "PRODUCES": "PRODUCES",
    "CARRY": "CARRIES",
    "CARRIES": "CARRIES",
    "DEPEND ON": "DEPENDS_ON",
    "DEPENDS ON": "DEPENDS_ON",
    "CONNECT TO": "CONNECTS_TO",
    "CONNECTS TO": "CONNECTS_TO",
    "PART OF": "PART_OF",
    "IMPLEMENTED BY": "IMPLEMENTED_BY",
}


def normalize_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.casefold())


def normalize_type(value: str) -> str:
    normalized = re.sub(r"[_-]+", " ", value.strip().upper())
    return TYPE_ALIASES.get(normalized, normalized.replace(" ", "_"))


def canonical_relationship_type(value: str) -> str | None:
    normalized = re.sub(r"[_-]+", " ", value.strip().upper())
    return RELATIONSHIP_ALIASES.get(normalized)


class UnionFind:
    def __init__(self) -> None:
        self._parent: dict[UUID, UUID] = {}

    def find(self, item: UUID) -> UUID:
        self._parent.setdefault(item, item)
        if self._parent[item] != item:
            self._parent[item] = self.find(self._parent[item])
        return self._parent[item]

    def union(self, first: UUID, second: UUID) -> UUID:
        first_root, second_root = self.find(first), self.find(second)
        if first_root != second_root:
            self._parent[second_root] = first_root
        return self.find(first_root)

    def groups(self) -> list[set[UUID]]:
        groups: dict[UUID, set[UUID]] = {}
        for item in self._parent:
            groups.setdefault(self.find(item), set()).add(item)
        return list(groups.values())


@dataclass(frozen=True)
class EntityCandidate:
    id: UUID
    project_id: UUID
    canonical_name: str
    entity_type: str
    aliases: tuple[str, ...] = ()
    embedding: tuple[float, ...] | None = None


@dataclass(frozen=True)
class Resolution:
    state: ResolutionState
    entity_id: UUID | None = None
    candidates: tuple[UUID, ...] = ()
    similarity: float | None = None


class AmbiguityDecision(BaseModel):
    selected_entity_id: UUID | None = None
    is_same_entity: bool


class EntityResolver:
    """Uses blocking as a candidate reducer, never as a semantic identity proof."""

    def __init__(self, merge_threshold: float = 0.96, ambiguity_threshold: float = 0.80) -> None:
        self.merge_threshold = merge_threshold
        self.ambiguity_threshold = ambiguity_threshold

    def resolve(
        self,
        project_id: UUID,
        name: str,
        entity_type: str,
        candidates: list[EntityCandidate],
        embedding: tuple[float, ...] | None = None,
    ) -> Resolution:
        normalized_name, normalized_type = normalize_name(name), normalize_type(entity_type)
        scoped = [
            candidate
            for candidate in candidates
            if candidate.project_id == project_id
            and normalize_type(candidate.entity_type) == normalized_type
        ]
        exact = [
            candidate
            for candidate in scoped
            if normalize_name(candidate.canonical_name) == normalized_name
        ]
        if len(exact) == 1:
            metrics.increment("entity_resolution_exact")
            return Resolution(ResolutionState.EXACT, exact[0].id, (exact[0].id,), 1.0)
        aliases = [
            candidate
            for candidate in scoped
            if normalized_name in {normalize_name(alias) for alias in candidate.aliases}
        ]
        if len(aliases) == 1:
            metrics.increment("entity_resolution_alias")
            return Resolution(ResolutionState.ALIAS, aliases[0].id, (aliases[0].id,), 1.0)
        blocked = [
            candidate
            for candidate in scoped
            if self._block(normalized_name) == self._block(normalize_name(candidate.canonical_name))
        ]
        scored = [
            (
                candidate,
                self._score(
                    normalized_name,
                    normalize_name(candidate.canonical_name),
                    embedding,
                    candidate.embedding,
                ),
            )
            for candidate in blocked
        ]
        scored.sort(key=lambda item: item[1], reverse=True)
        if not scored:
            metrics.increment("entity_resolution_unresolved")
            return Resolution(ResolutionState.UNRESOLVED)
        best, score = scored[0]
        ties = [
            candidate.id
            for candidate, candidate_score in scored
            if candidate_score >= self.ambiguity_threshold
        ]
        if score >= self.merge_threshold and len(ties) == 1:
            metrics.increment("entity_resolution_merged")
            return Resolution(ResolutionState.MERGED, best.id, (best.id,), score)
        metrics.increment("entity_resolution_ambiguous")
        return Resolution(ResolutionState.AMBIGUOUS, candidates=tuple(ties), similarity=score)

    async def resolve_ambiguity_with_llm(
        self,
        provider: LLMProvider,
        name: str,
        resolution: Resolution,
        candidates: list[EntityCandidate],
    ) -> Resolution:
        """Ask an LLM only for an already-ambiguous finite candidate set; it cannot invent an ID."""
        if resolution.state is not ResolutionState.AMBIGUOUS:
            return resolution
        permitted = {
            candidate.id for candidate in candidates if candidate.id in resolution.candidates
        }
        prompt = (
            f"Resolve whether '{name}' matches one listed candidate. "
            "Return false if uncertain. Candidates: "
            + ", ".join(
                f"{candidate.id}:{candidate.canonical_name}"
                for candidate in candidates
                if candidate.id in permitted
            )
        )
        output = await provider.generate_structured(
            LLMRequest(messages=[LLMMessage(role="user", content=prompt)]), AmbiguityDecision
        )
        decision = output.data
        if decision.is_same_entity and decision.selected_entity_id in permitted:
            return Resolution(
                ResolutionState.MERGED,
                decision.selected_entity_id,
                (decision.selected_entity_id,),
                resolution.similarity,
            )
        return resolution

    @staticmethod
    def _block(normalized_name: str) -> str:
        return normalized_name[:4]

    @staticmethod
    def _score(
        left: str,
        right: str,
        left_embedding: tuple[float, ...] | None,
        right_embedding: tuple[float, ...] | None,
    ) -> float:
        lexical = SequenceMatcher(a=left, b=right).ratio()
        if (
            left_embedding is None
            or right_embedding is None
            or len(left_embedding) != len(right_embedding)
        ):
            return lexical
        dot = sum(a * b for a, b in zip(left_embedding, right_embedding, strict=True))
        magnitude = sqrt(sum(a * a for a in left_embedding)) * sqrt(
            sum(b * b for b in right_embedding)
        )
        return lexical if magnitude == 0 else (lexical + (dot / magnitude)) / 2
