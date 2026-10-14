"""Pair up the sections of two document versions (numbering may have shifted between them)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from uuid import UUID

NUMBER_PREFIX = re.compile(r"^\s*(?:\d+(?:\.\d+)*\.?|[A-Z]\.)\s+")
FUZZY_THRESHOLD = 0.85


@dataclass(frozen=True)
class VersionSection:
    id: UUID
    ordinal: int
    heading: str
    path: str
    text: str
    page_start: int | None
    page_end: int | None
    first_chunk_id: UUID | None

    @property
    def key(self) -> tuple[str, ...]:
        """Headings along the path without their numbers: stable when sections are renumbered."""
        parts = [part for part in self.path.split(" > ") if part] or [self.heading]
        return tuple(NUMBER_PREFIX.sub("", part).strip().casefold() for part in parts)

    @property
    def label(self) -> str:
        return self.path or self.heading


@dataclass
class SectionMatches:
    pairs: list[tuple[VersionSection, VersionSection]]
    removed: list[VersionSection]
    added: list[VersionSection]


def _extends(first: str, second: str) -> bool:
    """One heading's words are all contained in the other's (in either direction)."""
    left, right = set(first.split()), set(second.split())
    return bool(left and right) and (left <= right or right <= left)


def match_sections(old: list[VersionSection], new: list[VersionSection]) -> SectionMatches:
    pairs: list[tuple[VersionSection, VersionSection]] = []
    old_left, new_left = list(old), list(new)

    def settle(first: VersionSection, second: VersionSection) -> None:
        pairs.append((first, second))
        old_left.remove(first)
        new_left.remove(second)

    # 1. the same heading path
    for candidate in list(old_left):
        twin = next((item for item in new_left if item.key == candidate.key), None)
        if twin is not None:
            settle(candidate, twin)
    # 2. the same final heading, when it is unambiguous on both sides
    for candidate in list(old_left):
        same_old = [item for item in old_left if item.key[-1] == candidate.key[-1]]
        same_new = [item for item in new_left if item.key[-1] == candidate.key[-1]]
        if len(same_old) == 1 and len(same_new) == 1:
            settle(candidate, same_new[0])
    # 2b. a heading that extends the other ("Timing" -> "Timing and Diagnostics") under the
    # same parent, when that pairing is unique on both sides
    for candidate in list(old_left):
        extends = [
            item
            for item in new_left
            if item.key[:-1] == candidate.key[:-1] and _extends(candidate.key[-1], item.key[-1])
        ]
        back = [
            item
            for item in old_left
            if extends
            and item.key[:-1] == extends[0].key[:-1]
            and _extends(item.key[-1], extends[0].key[-1])
        ]
        if len(extends) == 1 and len(back) == 1:
            settle(candidate, extends[0])
    # 3. a renamed heading: mutually best, sufficiently similar
    for candidate in list(old_left):
        scored = sorted(
            (
                (SequenceMatcher(None, " ".join(candidate.key), " ".join(item.key)).ratio(), item)
                for item in new_left
            ),
            key=lambda row: row[0],
            reverse=True,
        )
        if not scored or scored[0][0] < FUZZY_THRESHOLD:
            continue
        best = scored[0][1]
        reverse_best = max(
            old_left,
            key=lambda item: SequenceMatcher(None, " ".join(item.key), " ".join(best.key)).ratio(),
        )
        if reverse_best is candidate:
            settle(candidate, best)
    pairs.sort(key=lambda pair: pair[1].ordinal)
    return SectionMatches(pairs, old_left, new_left)
