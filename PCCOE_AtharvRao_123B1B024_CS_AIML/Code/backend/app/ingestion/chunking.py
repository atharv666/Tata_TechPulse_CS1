"""Hierarchy-preserving, token-bounded contextual chunking."""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.ingestion.contracts import NormalizedSection, SourcePosition

TOKEN_PATTERN = re.compile(r"\S+")


@dataclass(frozen=True)
class ChunkCandidate:
    content: str
    token_count: int
    position: SourcePosition


def chunk_section(
    section: NormalizedSection, max_tokens: int, overlap_tokens: int
) -> list[ChunkCandidate]:
    """Split only oversized section content and retain meaningful hierarchy context."""
    if overlap_tokens >= max_tokens:
        raise ValueError("Chunk overlap must be smaller than maximum chunk tokens.")
    context = f"Section: {section.heading}\n"
    text = "\n".join(block.text for block in section.content if block.text)
    if not text:
        return []
    tokens = TOKEN_PATTERN.findall(text)
    if len(tokens) <= max_tokens:
        return [ChunkCandidate(context + text, len(tokens), _section_position(section))]
    chunks: list[ChunkCandidate] = []
    step = max_tokens - overlap_tokens
    for start in range(0, len(tokens), step):
        window = tokens[start : start + max_tokens]
        if not window:
            break
        chunks.append(
            ChunkCandidate(context + " ".join(window), len(window), _section_position(section))
        )
        if start + max_tokens >= len(tokens):
            break
    return chunks


def walk_sections(sections: list[NormalizedSection]) -> list[NormalizedSection]:
    """Return parent-before-child section order for deterministic persistence."""
    result: list[NormalizedSection] = []
    for section in sections:
        result.append(section)
        result.extend(walk_sections(section.children))
    return result


def _section_position(section: NormalizedSection) -> SourcePosition:
    pages = [block.position.page for block in section.content if block.position.page is not None]
    return SourcePosition(page=min(pages) if pages else section.position.page)
