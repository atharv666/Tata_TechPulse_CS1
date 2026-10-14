"""Deterministic question understanding: intent, direction, relationship types and bounds.

The planner reads the *grammar* of the question around the linked entity, because direction
matters: "what does X require?" follows REQUIRES edges *out of* X, "what requires X?" follows them
*into* X. (An earlier version hard-wired one direction for every dependency question.) Nothing here
calls a model or writes SQL; the result is a typed plan that the graph layer executes.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum
from uuid import UUID

from app.retrieval.linking import LinkedEntity, LinkResult


class QueryIntent(StrEnum):
    RELATIONSHIP_LOOKUP = "RELATIONSHIP_LOOKUP"
    DEPENDENCY = "DEPENDENCY"
    IMPACT = "IMPACT"
    NEIGHBORHOOD = "NEIGHBORHOOD"
    SOURCE_SEARCH = "SOURCE_SEARCH"


OUTGOING, INCOMING, BOTH = "OUTGOING", "INCOMING", "BOTH"
DEPENDENCY_TYPES = ("DEPENDS_ON", "REQUIRES", "USES", "CONSUMES")


@dataclass(frozen=True)
class Phrase:
    pattern: re.Pattern[str]
    relationship_types: tuple[str, ...]
    #: True when the thing named *before* the phrase is the relationship's source
    #: ("A requires B", "A depends on B"); False for passives ("B is required by A").
    subject_is_source: bool


def _phrase(pattern: str, types: tuple[str, ...], subject_is_source: bool) -> Phrase:
    return Phrase(re.compile(pattern, re.IGNORECASE), types, subject_is_source)


PHRASES: tuple[Phrase, ...] = (
    # passives first: "required by" must not be read as the active "require"
    _phrase(r"\b(?:is|are|was|were|be)?\s*required\s+by\b", ("REQUIRES",), False),
    _phrase(r"\b(?:is|are)?\s*used\s+by\b", ("USES",), False),
    _phrase(r"\b(?:is|are)?\s*provided\s+by\b", ("PROVIDES",), False),
    _phrase(r"\b(?:is|are)?\s*consumed\s+by\b", ("CONSUMES",), False),
    _phrase(r"\b(?:is|are)?\s*produced\s+by\b", ("PRODUCES",), False),
    _phrase(r"\b(?:is|are)?\s*carried\s+by\b", ("CARRIES",), False),
    _phrase(r"\b(?:is|are)?\s*implemented\s+by\b", ("IMPLEMENTED_BY",), True),
    _phrase(r"\b(?:is|are)?\s*(?:verified|tested)\s+by\b", ("VERIFIED_BY",), True),
    _phrase(r"\b(?:is|are)?\s*triggered\s+by\b", ("TRIGGERS",), False),
    _phrase(r"\b(?:is|are)?\s*followed\s+by\b", ("PRECEDES",), True),
    _phrase(r"\b(?:is|are)?\s*preceded\s+by\b", ("PRECEDES",), False),
    _phrase(r"\b(?:is|are)?\s*sent\s+to\b", ("SENDS_TO",), True),
    # actives
    # "dependencies of X" names the dependencies *before* X, so X is the source of the edges
    _phrase(r"\bdependenc(?:y|ies)\s+(?:of|for)\b", DEPENDENCY_TYPES, False),
    _phrase(r"\bdepend(?:s|ed|ing)?\s+on\b", DEPENDENCY_TYPES, True),
    _phrase(r"\brequir(?:e|es|ed|ing)\b|\bneeds?\b", ("REQUIRES",), True),
    _phrase(r"\buses?\b|\bused\b|\busing\b|\butili[sz]es?\b", ("USES",), True),
    _phrase(r"\bprovid(?:e|es|ed|ing)\b|\boffers?\b", ("PROVIDES",), True),
    _phrase(r"\bconsum(?:e|es|ed|ing)\b", ("CONSUMES",), True),
    _phrase(r"\bproduc(?:e|es|ed|ing)\b", ("PRODUCES",), True),
    _phrase(r"\bcarr(?:y|ies|ied|ying)\b", ("CARRIES",), True),
    _phrase(r"\bconnect(?:s|ed|ing)?\s+to\b", ("CONNECTS_TO",), True),
    _phrase(r"\bpart\s+of\b|\bbelongs?\s+to\b", ("PART_OF",), True),
    _phrase(r"\bimplements?\b", ("IMPLEMENTED_BY",), False),
    _phrase(r"\btests?\b|\bverif(?:y|ies)\b", ("VERIFIED_BY",), False),
    _phrase(r"\btriggers?\b", ("TRIGGERS",), True),
    _phrase(r"\bprecedes?\b|\bbefore\b|\bprior\s+to\b", ("PRECEDES",), True),
    _phrase(r"\bafter\b|\bfollows?\b|\bcomes?\s+next\b", ("PRECEDES",), False),
    _phrase(r"\bsends?\s+to\b", ("SENDS_TO",), True),
)
DEPENDENTS = re.compile(r"\bdependents?\s+(?:of|on)\b|\bwho\s+depends\b", re.IGNORECASE)
IMPACT = re.compile(
    r"\bimpact|\baffect|\bripple|\bbreak(?:s|ing)?\b|\bchang(?:e|es|ed|ing)\b|\bmodif(?:y|ies|ied)\b"
    r"|\bupdat(?:e|es|ed|ing)\b|\bdeprecat",
    re.IGNORECASE,
)
DEEP = re.compile(
    r"\bindirect|\btransitive|\bchain\b|\bdownstream|\bupstream|\ball\s+dependenc", re.I
)


@dataclass(frozen=True)
class QueryPlan:
    normalized_query: str
    intent: QueryIntent
    roots: tuple[LinkedEntity, ...]
    direction: str
    relationship_types: tuple[str, ...]
    graph_depth: int
    use_graph: bool
    notes: tuple[str, ...] = field(default_factory=tuple)

    @property
    def root_ids(self) -> tuple[UUID, ...]:
        return tuple(dict.fromkeys(root.entity_id for root in self.roots))

    def describe(self) -> dict[str, object]:
        """What the planner decided, for the retrieval trace: ids and settings, no names or text."""
        return {
            "intent": self.intent.value,
            "direction": self.direction,
            "relationship_types": list(self.relationship_types),
            "depth": self.graph_depth,
            "linked": [
                {
                    "entity_id": str(root.entity_id),
                    "type": root.entity_type,
                    "method": root.method,
                    "score": root.score,
                    "ambiguous": root.ambiguous,
                }
                for root in self.roots
            ],
            "notes": len(self.notes),
        }


class QueryPlanner:
    """Builds typed retrieval plans; it never executes model-authored SQL."""

    def plan(self, query: str, links: LinkResult) -> QueryPlan:
        normalized = " ".join(query.split())
        roots = tuple(links.entities)
        notes = list(links.notes)
        if not roots:
            return QueryPlan(
                normalized, QueryIntent.SOURCE_SEARCH, (), BOTH, (), 1, False, tuple(notes)
            )
        if IMPACT.search(normalized):
            return QueryPlan(normalized, QueryIntent.IMPACT, roots, BOTH, (), 3, True, tuple(notes))
        depth = 2 if DEEP.search(normalized) else 1
        direction, types, intent = self._relationship(normalized, roots[0])
        if intent is QueryIntent.NEIGHBORHOOD:
            notes.append(
                "No specific relationship was asked about; showing the entity's neighbours."
            )
        return QueryPlan(normalized, intent, roots, direction, types, depth, True, tuple(notes))

    @staticmethod
    def _relationship(query: str, root: LinkedEntity) -> tuple[str, tuple[str, ...], QueryIntent]:
        if DEPENDENTS.search(query):
            return INCOMING, DEPENDENCY_TYPES, QueryIntent.DEPENDENCY
        matches = [
            (m.start(), phrase) for phrase in PHRASES for m in phrase.pattern.finditer(query)
        ]
        if matches:
            # the earliest phrase after the entity, else the first one anywhere
            matches.sort(key=lambda item: item[0])
            after = [item for item in matches if item[0] >= root.end]
            position, phrase = (after or matches)[0]
            entity_before_phrase = root.start < position
            entity_is_source = entity_before_phrase == phrase.subject_is_source
            direction = OUTGOING if entity_is_source else INCOMING
            intent = (
                QueryIntent.DEPENDENCY
                if set(phrase.relationship_types) & {"REQUIRES", "USES", "DEPENDS_ON"}
                else QueryIntent.RELATIONSHIP_LOOKUP
            )
            if phrase.relationship_types == ("CONNECTS_TO",):
                direction = BOTH
            return direction, phrase.relationship_types, intent
        return BOTH, (), QueryIntent.NEIGHBORHOOD
