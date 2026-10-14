"""Detectors for *potential* architecture inconsistencies (AGENTS.md section 12).

Detection never judges the architecture: every finding is worded "Potential inconsistency
detected" and is a prompt for a human to look at the cited facts. Detectors are pure functions over
already-loaded rows, so they are easy to test; ``FindingsService`` stores their output.
"""

from __future__ import annotations

import hashlib
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any
from uuid import UUID

from app.canonicalization.binding import BindingProblem
from app.canonicalization.view import type_group
from app.knowledge.rules import OPPOSING_TYPES, check_relationship
from app.models.enums import ValidationState
from app.models.schema import Entity, MergeDecision, Relationship

PREFIX = "Potential inconsistency detected: "
MAX_LISTED = 10

MISSING_PROVIDER = "MISSING_PROVIDER"
MISSING_ENTITY_DEFINITION = "MISSING_ENTITY_DEFINITION"
DANGLING_RELATIONSHIP = "DANGLING_RELATIONSHIP"
POSSIBLE_DUPLICATE = "POSSIBLE_DUPLICATE"
CONFLICTING_DECLARATION = "CONFLICTING_DECLARATION"
INCONSISTENT_RELATIONSHIP_TYPE = "INCONSISTENT_RELATIONSHIP_TYPE"
UNRESOLVED_ALIAS = "UNRESOLVED_ALIAS"

GRAPH_FINDING_TYPES = (
    MISSING_PROVIDER,
    MISSING_ENTITY_DEFINITION,
    DANGLING_RELATIONSHIP,
    POSSIBLE_DUPLICATE,
    CONFLICTING_DECLARATION,
    INCONSISTENT_RELATIONSHIP_TYPE,
    UNRESOLVED_ALIAS,
)
_CONSUMING = frozenset({"REQUIRES", "USES", "CONSUMES"})


@dataclass(frozen=True)
class FindingDraft:
    finding_type: str
    severity: str  # LOW | MEDIUM | HIGH
    summary: str
    #: Stable identity of the situation within its type; the fingerprint hashes type + key.
    key: str
    details: dict[str, Any] = field(default_factory=dict)
    entity_id: UUID | None = None
    relationship_id: UUID | None = None
    confidence: Decimal | None = None

    @property
    def fingerprint(self) -> str:
        return hashlib.sha256(f"{self.finding_type}|{self.key}".encode()).hexdigest()


def _active(entities: Iterable[Entity]) -> list[Entity]:
    return [
        entity
        for entity in entities
        if entity.merged_into_id is None
        and entity.superseded_by_id is None
        and entity.validation_state is not ValidationState.REJECTED
    ]


def _live(relationships: Iterable[Relationship]) -> list[Relationship]:
    return [
        item
        for item in relationships
        if item.superseded_by_id is None
        and item.validation_state is not ValidationState.REJECTED
        and "inactive_reason" not in item.attributes
    ]


def missing_providers(
    entities: list[Entity], relationships: list[Relationship]
) -> list[FindingDraft]:
    live, names = _live(relationships), {entity.id: entity for entity in entities}
    provided = {item.target_entity_id for item in live if item.relationship_type == "PROVIDES"} | {
        item.source_entity_id for item in live if item.relationship_type == "IMPLEMENTED_BY"
    }
    consumers: dict[UUID, list[str]] = defaultdict(list)
    for item in live:
        if item.relationship_type in _CONSUMING and item.source_entity_id in names:
            consumers[item.target_entity_id].append(names[item.source_entity_id].canonical_name)
    drafts: list[FindingDraft] = []
    for entity in _active(entities):
        if entity.entity_type != "INTERFACE" or entity.id in provided:
            continue
        users = sorted(set(consumers.get(entity.id, [])))
        detail = f" It is used by {', '.join(users[:3])}." if users else ""
        drafts.append(
            FindingDraft(
                MISSING_PROVIDER,
                "HIGH" if users else "LOW",
                f"{PREFIX}interface '{entity.canonical_name}' has no provider "
                f"relationship.{detail}",
                str(entity.id),
                {"interface": entity.canonical_name, "used_by": users[:MAX_LISTED]},
                entity_id=entity.id,
                confidence=entity.confidence,
            )
        )
    return drafts


def binding_findings(problems: list[BindingProblem]) -> list[FindingDraft]:
    """Relationship statements whose endpoints could not be bound to an entity."""
    missing: dict[str, list[BindingProblem]] = defaultdict(list)
    ambiguous: dict[str, list[BindingProblem]] = defaultdict(list)
    drafts: list[FindingDraft] = []
    for problem in problems:
        if problem.kind == "MISSING":
            missing[problem.normalized].append(problem)
        elif problem.kind == "AMBIGUOUS":
            ambiguous[problem.normalized].append(problem)
        elif problem.kind == "REJECTED":
            candidate = problem.candidate
            drafts.append(
                FindingDraft(
                    DANGLING_RELATIONSHIP,
                    "MEDIUM",
                    f"{PREFIX}the statement '{candidate.source_name} {candidate.relationship_type}"
                    f" {candidate.target_name}' refers to an entity a reviewer rejected.",
                    f"candidate:{candidate.id}",
                    _statement_details([problem]),
                    confidence=candidate.confidence,
                )
            )
    for normalized, group in sorted(missing.items()):
        name = group[0].name
        drafts.append(
            FindingDraft(
                MISSING_ENTITY_DEFINITION,
                "MEDIUM",
                f"{PREFIX}'{name}' is referenced in {len(group)} relationship statement(s) "
                "but no entity with that name is defined.",
                normalized,
                {"name": name, **_statement_details(group)},
                confidence=max(item.candidate.confidence for item in group),
            )
        )
    for normalized, group in sorted(ambiguous.items()):
        name = group[0].name
        drafts.append(
            FindingDraft(
                UNRESOLVED_ALIAS,
                "MEDIUM",
                f"{PREFIX}the name '{name}' could refer to several entities "
                f"({', '.join(group[0].matches)}) and was not bound automatically.",
                f"ambiguous:{normalized}",
                {"name": name, "matches": list(group[0].matches), **_statement_details(group)},
                confidence=max(item.candidate.confidence for item in group),
            )
        )
    return drafts


def _statement_details(group: list[BindingProblem]) -> dict[str, Any]:
    return {
        "statements": [
            {
                "source": item.candidate.source_name,
                "relationship_type": item.candidate.relationship_type,
                "target": item.candidate.target_name,
                "chunk_id": str(item.candidate.chunk_id),
                "excerpt": item.candidate.excerpt[:300],
            }
            for item in group[:MAX_LISTED]
        ]
    }


def dangling_relationships(
    entities: list[Entity], relationships: list[Relationship]
) -> list[FindingDraft]:
    """Existing relationships one of whose endpoints a reviewer has since rejected."""
    rejected = {
        entity.id: entity
        for entity in entities
        if entity.validation_state is ValidationState.REJECTED
    }
    drafts: list[FindingDraft] = []
    for item in _live(relationships):
        bad = rejected.get(item.source_entity_id) or rejected.get(item.target_entity_id)
        if bad is None:
            continue
        drafts.append(
            FindingDraft(
                DANGLING_RELATIONSHIP,
                "MEDIUM",
                f"{PREFIX}a {item.relationship_type} relationship depends on the rejected "
                f"entity '{bad.canonical_name}'.",
                f"relationship:{item.id}",
                {"rejected_entity": bad.canonical_name},
                relationship_id=item.id,
                confidence=item.confidence,
            )
        )
    return drafts


def possible_duplicates(
    entities: list[Entity], decisions: list[MergeDecision]
) -> list[FindingDraft]:
    """Pairs that look alike but were not merged: undecided, blocked or both human-reviewed."""
    active = {entity.id: entity for entity in _active(entities)}
    drafts: list[FindingDraft] = []
    for decision in decisions:
        first, second = active.get(decision.entity_a_id), active.get(decision.entity_b_id)
        if decision.decision != "UNSURE" or first is None or second is None:
            continue
        drafts.append(
            FindingDraft(
                POSSIBLE_DUPLICATE,
                "LOW",
                f"{PREFIX}'{first.canonical_name}' and '{second.canonical_name}' may be the same "
                f"{first.entity_type.lower().replace('_', ' ')}.",
                decision.pair_key,
                {
                    "entities": [first.canonical_name, second.canonical_name],
                    "reason": decision.reason,
                    "similarity": float(decision.confidence) if decision.confidence else None,
                    "state": decision.fingerprint
                    if decision.fingerprint in ("deferred", "blocked")
                    else "judged",
                },
                entity_id=first.id,
                confidence=decision.confidence,
            )
        )
    return drafts


def conflicting_declarations(
    entities: list[Entity], relationships: list[Relationship]
) -> list[FindingDraft]:
    drafts: list[FindingDraft] = []
    by_name: dict[str, list[Entity]] = defaultdict(list)
    for entity in _active(entities):
        by_name[entity.normalized_name].append(entity)
    for normalized, group in sorted(by_name.items()):
        if len({type_group(item.entity_type) for item in group}) > 1:
            kinds = sorted({item.entity_type for item in group})
            drafts.append(
                FindingDraft(
                    CONFLICTING_DECLARATION,
                    "MEDIUM",
                    f"{PREFIX}'{group[0].canonical_name}' is declared as more than one kind of "
                    f"element ({', '.join(kinds)}).",
                    f"types:{normalized}",
                    {"types": kinds, "entity_ids": [str(item.id) for item in group]},
                    entity_id=group[0].id,
                    confidence=min(item.confidence for item in group),
                )
            )
    names = {entity.id: entity.canonical_name for entity in entities}
    pairs: dict[tuple[UUID, UUID], dict[str, Relationship]] = defaultdict(dict)
    for item in _live(relationships):
        pairs[(item.source_entity_id, item.target_entity_id)][item.relationship_type] = item
    for (source, target), kinds_here in sorted(pairs.items(), key=lambda row: str(row[0])):
        for left, right in OPPOSING_TYPES:
            if left in kinds_here and right in kinds_here:
                drafts.append(
                    FindingDraft(
                        CONFLICTING_DECLARATION,
                        "MEDIUM",
                        f"{PREFIX}'{names.get(source)}' is stated to both {left} and {right} "
                        f"'{names.get(target)}'.",
                        f"opposing:{source}:{target}:{left}:{right}",
                        {"relationship_types": [left, right]},
                        relationship_id=kinds_here[left].id,
                        confidence=min(kinds_here[left].confidence, kinds_here[right].confidence),
                    )
                )
    return drafts


def inconsistent_relationship_types(
    entities: list[Entity], relationships: list[Relationship]
) -> list[FindingDraft]:
    """Relationship types whose endpoints are unusual for them (advisory domain/range rules)."""
    by_id = {entity.id: entity for entity in entities}
    drafts: list[FindingDraft] = []
    for item in _live(relationships):
        source, target = by_id.get(item.source_entity_id), by_id.get(item.target_entity_id)
        if source is None or target is None:
            continue
        problem = check_relationship(item.relationship_type, source.entity_type, target.entity_type)
        if problem is None:
            continue
        drafts.append(
            FindingDraft(
                INCONSISTENT_RELATIONSHIP_TYPE,
                "LOW",
                f"{PREFIX}'{source.canonical_name}' {item.relationship_type} "
                f"'{target.canonical_name}': {problem}",
                f"relationship:{item.id}",
                {
                    "source_type": source.entity_type,
                    "target_type": target.entity_type,
                    "relationship_type": item.relationship_type,
                },
                relationship_id=item.id,
                confidence=item.confidence,
            )
        )
    return drafts


def alias_conflicts(entities: list[Entity]) -> list[FindingDraft]:
    drafts: list[FindingDraft] = []
    for entity in _active(entities):
        for alias in entity.extraction_metadata.get("alias_conflicts", []):
            drafts.append(
                FindingDraft(
                    UNRESOLVED_ALIAS,
                    "LOW",
                    f"{PREFIX}the alias '{alias}' stated for '{entity.canonical_name}' already "
                    "belongs to a different entity.",
                    f"alias:{entity.id}:{alias.casefold()}",
                    {"alias": alias},
                    entity_id=entity.id,
                    confidence=entity.confidence,
                )
            )
    return drafts


def detect_all(
    entities: list[Entity],
    relationships: list[Relationship],
    decisions: list[MergeDecision],
    problems: list[BindingProblem],
) -> list[FindingDraft]:
    drafts = [
        *missing_providers(entities, relationships),
        *binding_findings(problems),
        *dangling_relationships(entities, relationships),
        *possible_duplicates(entities, decisions),
        *conflicting_declarations(entities, relationships),
        *inconsistent_relationship_types(entities, relationships),
        *alias_conflicts(entities),
    ]
    unique = {draft.fingerprint: draft for draft in drafts}
    return sorted(unique.values(), key=lambda draft: (draft.finding_type, draft.key))
