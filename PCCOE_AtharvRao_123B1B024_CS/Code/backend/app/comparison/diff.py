"""Deterministic text comparison of two versions of a section (no model involved)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher

from app.ingestion.text import split_sentences

# numbers with an optional unit, and hex values: the values engineers care about changing
VALUE = re.compile(
    r"0x[0-9A-Fa-f]+|\d+(?:\.\d+)?(?:\s?(?:ms|us|s|hz|khz|mhz|kbit/s|mbit/s|v|mv|a|ma|kb|mb|%|bits?|bytes?))?",
    re.IGNORECASE,
)
PAIRING_THRESHOLD = 0.5
MAX_LISTED = 12


@dataclass(frozen=True)
class ValueChange:
    old_statement: str
    new_statement: str
    old_values: tuple[str, ...]
    new_values: tuple[str, ...]


@dataclass
class StatementDiff:
    added: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    changed: list[ValueChange] = field(default_factory=list)
    #: statements that were reworded without a changed number/identifier
    reworded: list[tuple[str, str]] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return not (self.added or self.removed or self.changed or self.reworded)


def statements(text: str) -> list[str]:
    """Statements in document order: table rows, list items and sentences, whitespace-normalised."""
    found: list[str] = []
    for raw in text.split("\n"):
        line = " ".join(raw.split())
        if not line or set(line.replace("|", "").replace("-", "").strip()) == set():
            continue
        if line.startswith("|"):
            found.append(line)
        else:
            found.extend(" ".join(piece.split()) for piece in (split_sentences(line) or [line]))
    return found


def values_in(statement: str) -> tuple[str, ...]:
    return tuple(" ".join(match.group(0).lower().split()) for match in VALUE.finditer(statement))


def diff_statements(old_text: str, new_text: str) -> StatementDiff:
    old, new = statements(old_text), statements(new_text)
    diff = StatementDiff()
    matcher = SequenceMatcher(a=old, b=new, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        removed, added = old[i1:i2], new[j1:j2]
        remaining_new = list(added)
        for before in removed:
            best = max(
                remaining_new,
                key=lambda candidate: SequenceMatcher(None, before, candidate).ratio(),
                default=None,
            )
            if (
                best is not None
                and SequenceMatcher(None, before, best).ratio() >= PAIRING_THRESHOLD
            ):
                remaining_new.remove(best)
                before_values, after_values = values_in(before), values_in(best)
                if before_values != after_values:
                    diff.changed.append(ValueChange(before, best, before_values, after_values))
                else:
                    diff.reworded.append((before, best))
            else:
                diff.removed.append(before)
        diff.added.extend(remaining_new)
    return diff
