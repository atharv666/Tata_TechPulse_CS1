"""Hard guards: conditions under which two entities must never be merged automatically.

Similar names are not identity. ``BrakeInterface_V1`` / ``BrakeInterface_V2`` or
``WheelSpeed_FL`` / ``WheelSpeed_FR`` score very high lexically and are different items. These
checks run before any merge, whether a rule or the LLM proposed it, and again for every pair a
transitive (Union-Find) merge would put in one group.
"""

from __future__ import annotations

from uuid import UUID

from app.canonicalization.names import number_tokens, opposite_qualifier
from app.canonicalization.view import EntityView, pair_key


def guard_reason(
    first: EntityView,
    second: EntityView,
    must_not_link: frozenset[str] = frozenset(),
) -> str | None:
    """Why the pair may not be merged, or ``None`` when no guard objects."""
    if first.group != second.group:
        return f"different entity types ({first.entity_type} / {second.entity_type})"
    if pair_key(first.id, second.id) in must_not_link:
        return "a reviewer or an earlier decision recorded these as different entities"
    if first.human_reviewed and second.human_reviewed:
        return "both entities were reviewed by a human; merging them needs a human decision"
    if first.normalized_names & second.normalized_names:
        return None  # a shared name/alias: digits and qualifiers agree by construction
    if number_tokens(first.name) != number_tokens(second.name):
        return "version or index numbers differ"
    if opposite_qualifier(first.name, second.name):
        return "names differ by opposite qualifiers (for example FL/FR, request/response)"
    return None


def group_conflict(
    left: list[EntityView],
    right: list[EntityView],
    must_not_link: frozenset[str] = frozenset(),
) -> tuple[UUID, UUID, str] | None:
    """First pair across two groups that a guard forbids, so a union cannot create it."""
    for first in left:
        for second in right:
            reason = guard_reason(first, second, must_not_link)
            if reason is not None:
                return first.id, second.id, reason
    return None
