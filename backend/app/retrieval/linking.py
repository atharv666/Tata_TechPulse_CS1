"""Link entity mentions in a question to canonical entities (names, aliases, near-misses)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.canonicalization.core import normalize_name
from app.models.enums import ValidationState
from app.models.schema import Entity, EntityAlias

MAX_SPAN_WORDS = 5
FUZZY_CUTOFF = 0.88
FUZZY_MARGIN = 0.04
WORD = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_\-.]*[A-Za-z0-9_]|[A-Za-z0-9_]")
_IDENTIFIER_HINT = re.compile(r"[_0-9]|[a-z][A-Z]|^[A-Z]{2,}$")


@dataclass(frozen=True)
class LinkedEntity:
    entity_id: UUID
    name: str
    entity_type: str
    mention: str
    #: EXACT = the canonical name, ALIAS = a recorded alias, FUZZY = a near-miss spelling.
    method: str
    score: float
    start: int
    end: int
    #: The mention also names other entities (for example a signal and an interface).
    ambiguous: bool = False


@dataclass
class LinkResult:
    entities: list[LinkedEntity] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def ids(self) -> list[UUID]:
        return list(dict.fromkeys(item.entity_id for item in self.entities))


@dataclass(frozen=True)
class _Known:
    entity_id: UUID
    name: str
    entity_type: str
    normalized: str
    method: str


class EntityLinker:
    """Deterministic, project-scoped linking; the LLM is not involved."""

    def __init__(self, session: Session, project_id: UUID) -> None:
        self._session = session
        self._project_id = project_id

    def link(self, query: str, max_entities: int = 3) -> LinkResult:
        index = self._index()
        result = LinkResult()
        words = [(match.group(0), match.start(), match.end()) for match in WORD.finditer(query)]
        taken: list[tuple[int, int]] = []
        claimed: set[UUID] = set()
        for size in range(min(MAX_SPAN_WORDS, len(words)), 0, -1):
            for offset in range(len(words) - size + 1):
                span = words[offset : offset + size]
                start, end = span[0][1], span[-1][2]
                if any(start < taken_end and end > taken_start for taken_start, taken_end in taken):
                    continue
                normalized = normalize_name(query[start:end])
                found = index.get(normalized)
                if not found:
                    continue
                if size == 1 and len(normalized) < 2:
                    continue
                taken.append((start, end))
                mention = query[start:end]
                for known in found:
                    if known.entity_id in claimed:
                        continue
                    claimed.add(known.entity_id)
                    result.entities.append(
                        LinkedEntity(
                            known.entity_id,
                            known.name,
                            known.entity_type,
                            mention,
                            known.method,
                            1.0,
                            start,
                            end,
                            ambiguous=len({k.entity_id for k in found}) > 1,
                        )
                    )
                if len({k.entity_id for k in found}) > 1:
                    result.notes.append(
                        f"'{mention}' names several entities "
                        f"({', '.join(sorted({f'{k.name} [{k.entity_type}]' for k in found}))})."
                    )
        self._fuzzy(query, words, taken, index, claimed, result)
        result.entities.sort(key=lambda item: item.start)
        if len(result.entities) > max_entities:
            result.notes.append(
                f"The question mentions {len(result.entities)} entities; "
                f"only the first {max_entities} are used."
            )
            result.entities = result.entities[:max_entities]
        return result

    # -- near-miss spellings (identifier-like tokens only) ---------------------------------------
    @staticmethod
    def _fuzzy(
        query: str,
        words: list[tuple[str, int, int]],
        taken: list[tuple[int, int]],
        index: dict[str, list[_Known]],
        claimed: set[UUID],
        result: LinkResult,
    ) -> None:
        for word, start, end in words:
            if any(start < t_end and end > t_start for t_start, t_end in taken):
                continue
            if len(word) < 6 or not _IDENTIFIER_HINT.search(word):
                continue
            normalized = normalize_name(word)
            scored = sorted(
                (
                    (SequenceMatcher(a=normalized, b=key).ratio(), key)
                    for key in index
                    if abs(len(key) - len(normalized)) <= 3
                ),
                reverse=True,
            )
            if not scored or scored[0][0] < FUZZY_CUTOFF:
                continue
            best_score, best_key = scored[0]
            if len(scored) > 1 and best_score - scored[1][0] < FUZZY_MARGIN:
                result.notes.append(f"'{word}' is close to several names; it was not linked.")
                continue
            for known in index[best_key]:
                if known.entity_id in claimed:
                    continue
                claimed.add(known.entity_id)
                taken.append((start, end))
                result.entities.append(
                    LinkedEntity(
                        known.entity_id,
                        known.name,
                        known.entity_type,
                        word,
                        "FUZZY",
                        round(best_score, 3),
                        start,
                        end,
                    )
                )
                result.notes.append(
                    f"'{word}' was read as '{known.name}' (similarity {best_score:.2f})."
                )

    def _index(self) -> dict[str, list[_Known]]:
        entities = {
            entity.id: entity
            for entity in self._session.scalars(
                select(Entity).where(
                    Entity.project_id == self._project_id,
                    Entity.merged_into_id.is_(None),
                    Entity.superseded_by_id.is_(None),
                    Entity.validation_state != ValidationState.REJECTED,
                )
            )
        }
        index: dict[str, list[_Known]] = {}
        for entity in entities.values():
            index.setdefault(entity.normalized_name, []).append(
                _Known(entity.id, entity.canonical_name, entity.entity_type, "", "EXACT")
            )
        for alias in self._session.scalars(
            select(EntityAlias).where(EntityAlias.project_id == self._project_id)
        ):
            owner = entities.get(alias.entity_id)
            if owner is None:
                continue
            bucket = index.setdefault(alias.normalized_alias, [])
            if all(item.entity_id != owner.id for item in bucket):
                bucket.append(
                    _Known(owner.id, owner.canonical_name, owner.entity_type, "", "ALIAS")
                )
        return index
