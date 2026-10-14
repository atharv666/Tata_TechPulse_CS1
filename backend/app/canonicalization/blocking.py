"""Hash-map blocking: cheap keys that propose which entity pairs are worth comparing.

A shared key only means "compare these two", never "these are the same item". Keys are always
scoped by entity type group, and blocks that are too large to be discriminating (a word that
appears in half the names) are dropped rather than expanded into thousands of pairs.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from itertools import combinations
from uuid import UUID

from app.canonicalization.core import normalize_name
from app.canonicalization.names import acronym, core_tokens, looks_like_acronym
from app.canonicalization.view import EntityView

MIN_WORD_LENGTH = 4


def blocking_keys(entity: EntityView) -> set[str]:
    keys: set[str] = set()
    for name in entity.names:
        normalized = normalize_name(name)
        if not normalized:
            continue
        keys.add(f"n:{normalized}")
        tokens = core_tokens(name)
        if tokens:
            keys.add("t:" + "-".join(sorted(tokens)))
        for token in tokens:
            if len(token) >= MIN_WORD_LENGTH:
                keys.add(f"w:{token}")
        initials = acronym(name)
        if initials:
            keys.add(f"a:{initials}")
        if looks_like_acronym(name):
            keys.add(f"a:{normalized}")
    return {f"{entity.group}|{key}" for key in keys}


@dataclass
class BlockingResult:
    #: ``(id, id)`` (sorted) -> the keys the pair shares, kept for the merge audit trail.
    pairs: dict[tuple[UUID, UUID], set[str]] = field(default_factory=dict)
    skipped_blocks: int = 0


def candidate_pairs(entities: Iterable[EntityView], max_block_size: int = 40) -> BlockingResult:
    """All entity pairs that share a blocking key, in a deterministic structure."""
    blocks: dict[str, list[UUID]] = defaultdict(list)
    for entity in sorted(entities, key=lambda item: str(item.id)):
        for key in blocking_keys(entity):
            blocks[key].append(entity.id)
    result = BlockingResult()
    for key in sorted(blocks):
        members = blocks[key]
        if len(members) < 2:
            continue
        if len(members) > max_block_size:
            result.skipped_blocks += 1
            continue
        for first, second in combinations(members, 2):
            result.pairs.setdefault((first, second), set()).add(key.split("|", 1)[1])
    return result
