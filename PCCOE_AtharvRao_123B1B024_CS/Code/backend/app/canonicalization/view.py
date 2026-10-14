"""Immutable entity snapshots, so blocking/scoring/guards stay pure and unit-testable."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from app.canonicalization.core import normalize_name

#: Entity types that may legitimately describe one item ("is it a component or an SWC?").
_TYPE_GROUPS = {"SOFTWARE_COMPONENT": "COMPONENT", "COMPONENT": "COMPONENT"}
HUMAN_STATES = frozenset({"HUMAN_VERIFIED", "HUMAN_CORRECTED"})


def type_group(entity_type: str) -> str:
    return _TYPE_GROUPS.get(entity_type, entity_type)


@dataclass(frozen=True)
class EntityView:
    id: UUID
    name: str
    entity_type: str
    aliases: tuple[str, ...] = ()
    validation_state: str = "PENDING"
    evidence_count: int = 0
    created_rank: int = 0  # stable creation order, a deterministic tie-breaker

    @property
    def group(self) -> str:
        return type_group(self.entity_type)

    @property
    def names(self) -> tuple[str, ...]:
        """The canonical name followed by every alias."""
        return (self.name, *self.aliases)

    @property
    def normalized_names(self) -> frozenset[str]:
        return frozenset(filter(None, (normalize_name(name) for name in self.names)))

    @property
    def human_reviewed(self) -> bool:
        return self.validation_state in HUMAN_STATES


def pair_key(first: UUID, second: UUID) -> str:
    """Order-independent identifier of an entity pair (stored as the decision-cache key)."""
    import hashlib

    low, high = sorted((str(first), str(second)))
    return hashlib.sha256(f"{low}|{high}".encode()).hexdigest()
