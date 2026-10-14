"""Heading detection helpers: section numbers, plausibility of numbered headings, level rules.

Headings that a format declares itself (bookmarks, Word styles, Markdown ``#``, font size) are
trusted by the parsers. This module covers the remaining case, plain text that only
*looks* numbered, and it is deliberately skeptical: a line such as
``3 channels are sampled every 10 ms`` or ``12 V nominal.`` starts with a number but is
body text, and treating it as a heading silently destroys the section tree (and, with
the old code, deleted text).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_NUMBERED = re.compile(
    r"^(?P<number>(?:[1-9]\d{0,2}|[A-Z](?=\.\d))(?:\.\d{1,3}){0,5})\.?[ \t]+(?P<title>\S.*)$"
)
MAX_HEADING_CHARS = 110
MAX_HEADING_WORDS = 16
MAX_SIBLING_SKIP = 3


def split_number(text: str) -> tuple[str | None, str]:
    """``'1.2 Interfaces'`` -> ``('1.2', 'Interfaces')``; no number -> ``(None, text)``."""
    match = _NUMBERED.match(text.strip())
    if match is None:
        return None, text.strip()
    return match.group("number"), match.group("title").strip()


def number_depth(number: str) -> int:
    return number.count(".") + 1


def _parts(number: str) -> tuple[int, ...]:
    values: list[int] = []
    for part in number.split("."):
        values.append(int(part) if part.isdigit() else 1000 + ord(part[0].upper()))
    return tuple(values)


def looks_like_heading_text(title: str) -> bool:
    """Shape test for a heading title: short, starts like a title, does not read like a sentence."""
    title = title.strip()
    if not title or len(title) > MAX_HEADING_CHARS or len(title.split()) > MAX_HEADING_WORDS:
        return False
    if not (title[0].isupper() or title[0].isdigit() or title[0] in "`\"'("):
        return False
    if title[-1] in ".,;":
        return False
    return len(re.findall(r"[.!?](?:\s|$)", title)) <= 1


@dataclass
class NumberingTracker:
    """Accepts a numbered heading only if it fits the numbering sequence seen so far."""

    last: tuple[int, ...] = field(default_factory=tuple)

    def accepts(self, number: str, title: str) -> bool:
        if not looks_like_heading_text(title):
            return False
        candidate = _parts(number)
        if not self.last:
            return True
        depth = len(candidate)
        previous = self.last
        # first child of the previous heading: 1.1 after 1, 2.3.1 after 2.3
        if depth == len(previous) + 1 and candidate[:-1] == previous and candidate[-1] == 1:
            return True
        # next sibling of the previous heading or of one of its ancestors
        if depth <= len(previous) and candidate[: depth - 1] == previous[: depth - 1]:
            step = candidate[depth - 1] - previous[depth - 1]
            if step == 1:
                return True
            if 2 <= step <= MAX_SIBLING_SKIP:  # a skipped number (removed or unrecognised section)
                return True
        return False

    def accept(self, number: str) -> None:
        self.last = _parts(number)
