"""Deterministic similarity of two entities (lexical only; see ADR on resolution)."""

from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher

from app.canonicalization.core import normalize_name
from app.canonicalization.names import acronym, core_tokens
from app.canonicalization.view import EntityView


@dataclass(frozen=True)
class PairScore:
    similarity: float
    #: ``EXACT_NAME`` | ``ALIAS`` when a (normalized) name or alias is shared; ``None`` otherwise.
    #: Only these two are decisive enough to merge without asking a model.
    decisive: str | None = None
    reason: str = ""


def _name_similarity(left: str, right: str) -> tuple[float, str]:
    left_norm, right_norm = normalize_name(left), normalize_name(right)
    if not left_norm or not right_norm:
        return 0.0, ""
    ratio = SequenceMatcher(a=left_norm, b=right_norm).ratio()
    left_tokens, right_tokens = set(core_tokens(left)), set(core_tokens(right))
    union = left_tokens | right_tokens
    jaccard = len(left_tokens & right_tokens) / len(union) if union else 0.0
    score, reason = 0.6 * ratio + 0.4 * jaccard, "lexical"
    smaller, larger = sorted((left_tokens, right_tokens), key=len)
    if len(smaller) >= 2 and smaller < larger:
        score, reason = max(score, 0.75), "one name extends the other"
    for short, long_name in ((left, right), (right, left)):
        if acronym(long_name) and normalize_name(short) == acronym(long_name):
            score, reason = max(score, 0.8), "acronym of the other name"
    return min(score, 0.99), reason


def score_pair(first: EntityView, second: EntityView) -> PairScore:
    shared = first.normalized_names & second.normalized_names
    if shared:
        names_first = {normalize_name(first.name)}
        names_second = {normalize_name(second.name)}
        if shared & names_first & names_second:
            return PairScore(1.0, "EXACT_NAME", "identical normalized name")
        return PairScore(1.0, "ALIAS", "a name is an alias of the other entity")
    best, reason = 0.0, ""
    for left in first.names:
        for right in second.names:
            value, why = _name_similarity(left, right)
            if value > best:
                best, reason = value, why
    return PairScore(round(best, 3), None, reason)
