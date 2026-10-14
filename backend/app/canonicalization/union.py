"""Constrained Union-Find: transitive duplicate merging that respects the hard guards.

Plain Union-Find merges A~B and B~C into {A, B, C} even when A and C must stay apart (different
version numbers, a human said they differ). Here a union is refused when any pair it would put
into one group is forbidden, and the refusal is recorded so it can be shown as a finding.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from uuid import UUID

Conflict = tuple[UUID, UUID, str]
#: Receives the members of the two groups about to be joined and returns the conflict, if any.
ConflictCheck = Callable[[list[UUID], list[UUID]], Conflict | None]


@dataclass(frozen=True)
class RefusedUnion:
    first: UUID
    second: UUID
    blocking_pair: tuple[UUID, UUID]
    reason: str


class ConstrainedUnionFind:
    def __init__(self, check: ConflictCheck) -> None:
        self._parent: dict[UUID, UUID] = {}
        self._members: dict[UUID, list[UUID]] = {}
        self._check = check
        self.refused: list[RefusedUnion] = []

    def find(self, item: UUID) -> UUID:
        if item not in self._parent:
            self._parent[item] = item
            self._members[item] = [item]
        root = item
        while self._parent[root] != root:
            root = self._parent[root]
        while self._parent[item] != root:  # path compression
            self._parent[item], item = root, self._parent[item]
        return root

    def union(self, first: UUID, second: UUID) -> bool:
        """Join the groups of two items; ``False`` when already joined or a guard forbids it."""
        first_root, second_root = self.find(first), self.find(second)
        if first_root == second_root:
            return False
        conflict = self._check(self._members[first_root], self._members[second_root])
        if conflict is not None:
            self.refused.append(
                RefusedUnion(first, second, (conflict[0], conflict[1]), conflict[2])
            )
            return False
        # The smaller group joins the larger; ties go to the smaller id, keeping it deterministic.
        if (len(self._members[first_root]), str(second_root)) < (
            len(self._members[second_root]),
            str(first_root),
        ):
            first_root, second_root = second_root, first_root
        self._parent[second_root] = first_root
        self._members[first_root].extend(self._members.pop(second_root))
        return True

    def groups(self) -> list[list[UUID]]:
        """Groups of two or more items, each sorted, themselves sorted for a stable order."""
        found = [sorted(members, key=str) for members in self._members.values() if len(members) > 1]
        return sorted(found, key=lambda members: str(members[0]))
