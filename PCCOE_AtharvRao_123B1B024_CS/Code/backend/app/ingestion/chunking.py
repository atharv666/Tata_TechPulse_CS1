"""Structure-aware chunking: keep meaning units together, split only what must be split.

A section's content is first cut into *atoms* (a paragraph, a run of list items, a table). Atoms are
packed into chunks up to ``target_tokens``; an atom is only ever cut when it alone exceeds
``max_tokens`` - paragraphs at sentence boundaries (with a small sentence overlap), lists between
items, tables between rows with the header row repeated. A chunk never crosses a heading, so its
section (and therefore its breadcrumb) is always unambiguous.

The chunk's ``content`` is the raw source text. Hierarchy context (the ancestor headings) is stored
separately as a *breadcrumb* and is prepended only when the chunk is embedded or indexed, so the
excerpt shown to users and verified against LLM output stays an exact quotation.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.ingestion.contracts import BlockKind, NormalizedSection, ParsedBlock, SourcePosition
from app.ingestion.text import estimate_tokens, is_list_item, split_sentences


@dataclass(frozen=True)
class ChunkCandidate:
    content: str
    token_count: int
    page_start: int | None
    page_end: int | None
    kind: str = "TEXT"  # TEXT | TABLE | OCR_TEXT

    @property
    def position(self) -> SourcePosition:
        return SourcePosition(page=self.page_start)


@dataclass(frozen=True)
class _Atom:
    text: str
    tokens: int
    page: int | None
    kind: str  # text | list | table
    ocr: bool = False


@dataclass
class PlannedSection:
    """A section ready to persist: its place in the tree, its path and its chunks."""

    section: NormalizedSection
    ordinal: int
    parent_ordinal: int | None
    depth: int
    path: str
    page_start: int | None
    page_end: int | None
    chunks: list[ChunkCandidate]


def chunk_section(
    section: NormalizedSection,
    max_tokens: int,
    overlap_tokens: int,
    target_tokens: int | None = None,
) -> list[ChunkCandidate]:
    """Chunk one section's own content (children are separate sections with their own chunks)."""
    if overlap_tokens >= max_tokens:
        raise ValueError("Chunk overlap must be smaller than maximum chunk tokens.")
    target = min(target_tokens or max_tokens, max_tokens)
    atoms: list[_Atom] = []
    for block in section.content:
        atoms.extend(_split_oversized(_atoms_of(block), max_tokens, overlap_tokens))
    return _pack(atoms, target, max_tokens)


def plan_document(
    roots: list[NormalizedSection],
    max_tokens: int,
    overlap_tokens: int,
    target_tokens: int | None = None,
) -> list[PlannedSection]:
    """Flatten the tree parent-before-child with ordinals, paths, page ranges and chunks."""
    planned: list[PlannedSection] = []

    def visit(section: NormalizedSection, parent: int | None, trail: list[str]) -> None:
        ordinal = len(planned) + 1
        is_preamble = section.preamble
        path_items = trail if is_preamble else [*trail, section.display_heading]
        own_pages = [section.position.page] if section.position.page is not None else []
        own_pages += [b.position.page for b in section.content if b.position.page is not None]
        planned.append(
            PlannedSection(
                section=section,
                ordinal=ordinal,
                parent_ordinal=parent,
                depth=len(path_items),
                path=" > ".join(path_items),
                page_start=min(own_pages) if own_pages else None,
                page_end=max(own_pages) if own_pages else None,
                chunks=chunk_section(section, max_tokens, overlap_tokens, target_tokens),
            )
        )
        for child in section.children:
            visit(child, ordinal, path_items)

    for root in roots:
        visit(root, None, [])
    return planned


# --------------------------------------------------------------------------------------------
def _atoms_of(block: ParsedBlock) -> list[_Atom]:
    page = block.position.page
    if block.kind is BlockKind.TABLE:
        text = block.text.strip()
        return [_Atom(text, estimate_tokens(text), page, "table")] if text else []
    atoms: list[_Atom] = []
    items: list[str] = []
    prose: list[str] = []

    def flush_items() -> None:
        if items:
            text = "\n".join(items)
            atoms.append(_Atom(text, estimate_tokens(text), page, "list", block.ocr))
            items.clear()

    def flush_prose() -> None:
        if prose:
            text = " ".join(prose)
            atoms.append(_Atom(text, estimate_tokens(text), page, "text", block.ocr))
            prose.clear()

    for line in block.text.split("\n"):
        if not line.strip():
            continue
        if is_list_item(line):
            flush_prose()
            items.append(line.strip())
        else:
            flush_items()
            prose.append(line.strip())
    flush_items()
    flush_prose()
    return atoms


def _split_oversized(atoms: list[_Atom], max_tokens: int, overlap: int) -> list[_Atom]:
    out: list[_Atom] = []
    for atom in atoms:
        if atom.tokens <= max_tokens:
            out.append(atom)
        elif atom.kind == "table":
            out.extend(_split_table(atom, max_tokens))
        elif atom.kind == "list":
            out.extend(_split_lines(atom, atom.text.split("\n"), max_tokens, "\n"))
        else:
            out.extend(_split_prose(atom, max_tokens, overlap))
    return out


def _split_table(atom: _Atom, max_tokens: int) -> list[_Atom]:
    lines = atom.text.split("\n")
    header = lines[:2] if len(lines) > 2 and lines[1].startswith("| ---") else []
    rows = lines[len(header) :]
    header_text = "\n".join(header)
    budget = max(max_tokens - estimate_tokens(header_text), 1)
    parts: list[_Atom] = []
    current: list[str] = []
    used = 0
    for row in rows:
        cost = estimate_tokens(row)
        if current and used + cost > budget:
            parts.append(_table_part(header_text, current, atom))
            current, used = [], 0
        current.append(row)
        used += cost
    if current:
        parts.append(_table_part(header_text, current, atom))
    return parts


def _table_part(header: str, rows: list[str], source: _Atom) -> _Atom:
    text = "\n".join([header, *rows]) if header else "\n".join(rows)
    return _Atom(text, estimate_tokens(text), source.page, "table", source.ocr)


def _split_lines(atom: _Atom, lines: list[str], max_tokens: int, joiner: str) -> list[_Atom]:
    parts: list[_Atom] = []
    current: list[str] = []
    used = 0
    for line in lines:
        cost = estimate_tokens(line)
        if current and used + cost > max_tokens:
            text = joiner.join(current)
            parts.append(_Atom(text, estimate_tokens(text), atom.page, atom.kind, atom.ocr))
            current, used = [], 0
        current.append(line)
        used += cost
    if current:
        text = joiner.join(current)
        parts.append(_Atom(text, estimate_tokens(text), atom.page, atom.kind, atom.ocr))
    return parts


def _split_prose(atom: _Atom, max_tokens: int, overlap: int) -> list[_Atom]:
    sentences: list[str] = []
    for sentence in split_sentences(atom.text) or [atom.text]:
        if estimate_tokens(sentence) > max_tokens:  # a single over-long sentence: cut by words
            words = sentence.split()
            step = max(max_tokens // 2, 1)
            sentences.extend(" ".join(words[i : i + step]) for i in range(0, len(words), step))
        else:
            sentences.append(sentence)
    parts: list[_Atom] = []
    window: list[str] = []
    used = 0
    for sentence in sentences:
        cost = estimate_tokens(sentence)
        if window and used + cost > max_tokens:
            text = " ".join(window)
            parts.append(_Atom(text, estimate_tokens(text), atom.page, "text", atom.ocr))
            # carry the trailing sentences (up to ``overlap`` tokens) into the next window
            carried: list[str] = []
            carried_cost = 0
            for previous in reversed(window):
                previous_cost = estimate_tokens(previous)
                if carried_cost + previous_cost > overlap:
                    break
                carried.insert(0, previous)
                carried_cost += previous_cost
            window, used = carried, carried_cost
        window.append(sentence)
        used += cost
    if window:
        text = " ".join(window)
        parts.append(_Atom(text, estimate_tokens(text), atom.page, "text", atom.ocr))
    return parts


def _pack(atoms: list[_Atom], target: int, max_tokens: int) -> list[ChunkCandidate]:
    groups: list[list[_Atom]] = []
    current: list[_Atom] = []
    used = 0
    for atom in atoms:
        if current and used + atom.tokens > target:
            groups.append(current)
            current, used = [], 0
        current.append(atom)
        used += atom.tokens
    if current:
        groups.append(current)
    # Do not leave a tiny trailing fragment when it fits into the previous chunk.
    if len(groups) >= 2:
        tail_tokens = sum(a.tokens for a in groups[-1])
        head_tokens = sum(a.tokens for a in groups[-2])
        if tail_tokens < target * 0.2 and head_tokens + tail_tokens <= max_tokens:
            groups[-2].extend(groups.pop())
    return [_candidate(group) for group in groups]


def _candidate(group: list[_Atom]) -> ChunkCandidate:
    content = "\n\n".join(atom.text for atom in group)
    pages = [atom.page for atom in group if atom.page is not None]
    if any(atom.ocr for atom in group):
        kind = "OCR_TEXT"
    elif all(atom.kind == "table" for atom in group):
        kind = "TABLE"
    else:
        kind = "TEXT"
    return ChunkCandidate(
        content=content,
        token_count=estimate_tokens(content),
        page_start=min(pages) if pages else None,
        page_end=max(pages) if pages else None,
        kind=kind,
    )
