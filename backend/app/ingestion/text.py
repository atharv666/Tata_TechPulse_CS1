"""Small text utilities shared by parsers, the chunker and retrieval (no I/O, no models)."""

from __future__ import annotations

import re

_TOKEN = re.compile(r"\w+|[^\w\s]")
_SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9`\"'(\[])")
LIST_MARKER = re.compile(r"^\s*(?:[-*•▪●–—]|\(?[0-9a-zA-Z]{1,3}[.)])\s+")
BULLET = re.compile(r"^\s*[-*•▪●–—]\s+")


def estimate_tokens(text: str) -> int:
    """Words plus punctuation: closer to sub-word token counts than whitespace splitting."""
    return len(_TOKEN.findall(text))


def split_sentences(text: str) -> list[str]:
    """Split prose at sentence boundaries; never splits inside identifiers or decimals."""
    pieces = [piece.strip() for piece in _SENTENCE_BOUNDARY.split(text.strip())]
    return [piece for piece in pieces if piece]


def is_list_item(line: str) -> bool:
    return bool(LIST_MARKER.match(line))


def is_bullet(line: str) -> bool:
    """Symbol bullets only; ``1. Overview`` may be a numbered heading rather than a list item."""
    return bool(BULLET.match(line))


def render_table_markdown(rows: list[list[str]]) -> str:
    """Render rows as a pipe table. The first row is treated as the header."""
    cleaned = [[" ".join(str(cell).split()) for cell in row] for row in rows if any(row)]
    if not cleaned:
        return ""
    width = max(len(row) for row in cleaned)
    padded = [row + [""] * (width - len(row)) for row in cleaned]
    lines = ["| " + " | ".join(padded[0]) + " |", "| " + " | ".join(["---"] * width) + " |"]
    lines += ["| " + " | ".join(row) + " |" for row in padded[1:]]
    return "\n".join(lines)


def stem(word: str) -> str:
    """A tiny, deterministic suffix stripper (``computes``/``computed``/``compute`` agree).

    Used only for the explainable overlap signals (relevance gating and claim verification);
    PostgreSQL's own ``english`` stemmer handles the full-text index.
    """
    w = word.lower()
    if len(w) > 4 and w.endswith("ies"):
        w = w[:-3] + "y"
    elif len(w) > 4 and w.endswith(("sses", "xes", "zes", "ches", "shes")):
        w = w[:-2]
    elif len(w) > 3 and w.endswith("s") and not w.endswith(("ss", "us", "is")):
        w = w[:-1]
    if len(w) > 5 and w.endswith("ing"):
        w = w[:-3]
    elif len(w) > 4 and w.endswith("ed"):
        w = w[:-2]
    if len(w) > 4 and w.endswith("e"):
        w = w[:-1]
    return w


def truncate_at_sentence(text: str, max_tokens: int) -> tuple[str, bool]:
    """Cut ``text`` to roughly ``max_tokens`` on a sentence (or line) boundary."""
    if estimate_tokens(text) <= max_tokens:
        return text, False
    kept: list[str] = []
    used = 0
    units = text.split("\n") if "\n" in text else split_sentences(text)
    for unit in units:
        cost = estimate_tokens(unit)
        if used and used + cost > max_tokens:
            break
        kept.append(unit)
        used += cost
        if used >= max_tokens:
            break
    joined = ("\n" if "\n" in text else " ").join(kept)
    return joined, joined != text
