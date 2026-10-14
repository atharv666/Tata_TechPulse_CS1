"""Identifier-aware text preparation shared by indexing and querying.

PostgreSQL's text-search parser splits on underscores but not on camelCase, and it keeps
tokens such as ``ABS_Module/ESP_Module`` together. AUTOSAR text is full of identifiers
(``P_WheelSpeed_In``, ``BrakeCtrl``, ``Rte_Read_SpeedPort_Speed``), so both the indexed
text and the query are normalised with the *same* function here:

* every non-alphanumeric character becomes a separator;
* every identifier-like token additionally contributes its joined form (``pwheelspeedin``) and its
  words (``p wheel speed in``). A query for ``P_WheelSpeed_In`` therefore matches the exact token,
  and a query for "wheel speed in" matches the same text through the word form.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.ingestion.text import stem

TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_]+")
_WORD_PARTS = re.compile(r"[A-Z]+(?![a-z])|[A-Z]?[a-z]+|\d+")

# Small, deliberate list: question words and glue that never help find an engineering passage.
STOPWORDS = frozenset(
    "a an and are as at be been being by can could did do does for from had has have how i if in "
    "into is it its me of on or our please s shall should so than that the their them then there "
    "these they this those to was we were what when where which who whom whose why will with would "
    "you your tell show give list describe explain about".split()
)
MAX_QUERY_TERMS = 32


def is_identifier_like(token: str) -> bool:
    """True for ``snake_case``, ``camelCase``/``PascalCase`` and letter+digit tokens."""
    if "_" in token:
        return True
    if any(ch.isdigit() for ch in token) and any(ch.isalpha() for ch in token):
        return True
    return bool(re.search(r"[a-z][A-Z]", token)) or bool(re.search(r"[A-Z]{2,}[a-z]", token))


def split_identifier(token: str) -> list[str]:
    """``P_WheelSpeed_In`` -> [p, wheel, speed, in]; ``ABSModule`` -> [abs, module]."""
    parts: list[str] = []
    for chunk in token.split("_"):
        parts.extend(match.lower() for match in _WORD_PARTS.findall(chunk))
    return parts


@dataclass(frozen=True)
class LexicalTerm:
    """One query term: either a plain word or an identifier with its word-phrase alternative."""

    joined: str
    words: tuple[str, ...] = ()

    @property
    def is_identifier(self) -> bool:
        return len(self.words) > 1


def _tokens(text: str) -> list[str]:
    return TOKEN_PATTERN.findall(text)


def build_lexical_text(*parts: str | None) -> str:
    """Text for the ``tsvector`` column: separators normalised, identifier variants appended."""
    text = " ".join(part for part in parts if part)
    plain: list[str] = []
    extras: list[str] = []
    for token in _tokens(text):
        lowered = token.lower().replace("_", " ")
        plain.append(lowered)
        if is_identifier_like(token):
            words = split_identifier(token)
            joined = "".join(words)
            if joined:
                extras.append(joined)
            if len(words) > 1:
                extras.append(" ".join(words))
    return " ".join(plain + extras)


def query_terms(question: str) -> list[LexicalTerm]:
    """Distinct, ordered, stop-word-free search terms for a natural-language question."""
    terms: list[LexicalTerm] = []
    seen: set[str] = set()
    for token in _tokens(question):
        words = split_identifier(token) if is_identifier_like(token) else []
        joined = "".join(words) if words else token.lower().replace("_", "")
        if not joined or joined in seen:
            continue
        acronym = token.isupper() and len(token) >= 2  # ``DID``, ``ECU``: never a stop word
        if not words and not acronym and joined in STOPWORDS:
            continue
        if not words and len(joined) < 2:
            continue
        seen.add(joined)
        terms.append(LexicalTerm(joined=joined, words=tuple(words)))
        if len(terms) >= MAX_QUERY_TERMS:
            break
    return terms


def build_tsquery(question: str) -> str | None:
    """An OR query for ``to_tsquery``; identifiers also match their spaced word form.

    Every emitted token is strictly alphanumeric, so the string is safe to bind as a parameter.
    Returns ``None`` when the question contains no usable term (nothing for lexical search to do).
    """
    clauses: list[str] = []
    for term in query_terms(question):
        if term.is_identifier:
            phrase = " <-> ".join(term.words)
            clauses.append(f"({term.joined} | ({phrase}))")
        else:
            clauses.append(term.joined)
    return " | ".join(clauses) if clauses else None


def matched_term_ratio(question: str, lexical_text: str) -> float:
    """Share of the question's terms found in a passage (a cheap, explainable relevance signal)."""
    terms = query_terms(question)
    if not terms:
        return 0.0
    haystack = set(lexical_text.lower().split())
    stems = {stem(word) for word in haystack}
    hits = 0
    for term in terms:
        if term.is_identifier:
            found = term.joined in haystack or all(word in haystack for word in term.words)
        else:
            found = term.joined in haystack or stem(term.joined) in stems
        hits += found
    return hits / len(terms)
