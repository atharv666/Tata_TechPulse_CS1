"""Build the section tree from parsed blocks. No model, no guessing without validation.

Trust order for "this text is a heading":
  1. the format said so (bookmark, Word style, Markdown ``#``, PDF font): ``block.heading_level``;
  2. otherwise a *numbered* line, accepted only if it looks like a title and fits the numbering
     sequence seen so far (see ``structure.NumberingTracker``).

Invariants (each has a regression test):
  * No text is ever dropped. A heading that has no content stays in the tree.
  * Text that appears before the first heading lives in a level-0 preamble section.
  * Section nesting follows heading levels, never the order in which stray numbers appear.
"""

from __future__ import annotations

from app.ingestion.contracts import (
    BlockKind,
    NormalizedSection,
    ParsedBlock,
    ParsedDocument,
    SourcePosition,
)
from app.ingestion.structure import NumberingTracker, number_depth, split_number

PREAMBLE_TITLE = "Document content"
# Formats whose headings are authoritative: numbered body lines are never promoted to headings.
AUTHORITATIVE_STRUCTURE = frozenset({"toc", "style", "markdown"})


class _TreeBuilder:
    def __init__(self, parsed: ParsedDocument) -> None:
        self._allow_numbering_fallback = parsed.structure_source not in AUTHORITATIVE_STRUCTURE
        self._title = str(parsed.metadata.get("title") or PREAMBLE_TITLE)
        self._tracker = NumberingTracker()
        self.roots: list[NormalizedSection] = []
        self._stack: list[NormalizedSection] = []
        self._preamble: NormalizedSection | None = None

    # -- tree --------------------------------------------------------------------------------
    def _open_section(
        self, title: str, level: int, position: SourcePosition, number: str | None
    ) -> None:
        section = NormalizedSection(title, level, position, number=number)
        while self._stack and self._stack[-1].level >= level:
            self._stack.pop()
        (self._stack[-1].children if self._stack else self.roots).append(section)
        self._stack.append(section)

    def _target(self, position: SourcePosition) -> NormalizedSection:
        if self._stack:
            return self._stack[-1]
        if self._preamble is None:
            self._preamble = NormalizedSection(self._title, 0, position, preamble=True)
            self.roots.append(self._preamble)
        return self._preamble

    # -- blocks ------------------------------------------------------------------------------
    def add(self, block: ParsedBlock) -> None:
        if block.kind is BlockKind.HEADING:
            self._declared_heading(block)
        elif block.kind is BlockKind.TABLE:
            self._target(block.position).content.append(block)
        else:
            self._paragraph(block)

    def _declared_heading(self, block: ParsedBlock) -> None:
        number, title = split_number(block.text)
        title = title if title else block.text.strip()
        if not title:
            return
        if number is not None:
            self._tracker.accept(number)
        level = (
            block.heading_level
            if block.heading_level is not None
            else (number_depth(number) if number else 1)
        )
        self._open_section(title, level, block.position, number)

    def _paragraph(self, block: ParsedBlock) -> None:
        if not block.text.strip():
            return
        if not self._allow_numbering_fallback:
            self._target(block.position).content.append(block)
            return
        pending: list[str] = []

        def flush() -> None:
            if pending:
                text = "\n".join(pending)
                self._target(block.position).content.append(
                    ParsedBlock(text, block.position, ocr=block.ocr)
                )
                pending.clear()

        for line in block.text.split("\n"):
            number, title = split_number(line)
            if number is not None and self._tracker.accepts(number, title):
                flush()
                self._tracker.accept(number)
                self._open_section(title, number_depth(number), block.position, number)
            else:
                pending.append(line)
        flush()


def normalize_document(parsed: ParsedDocument) -> list[NormalizedSection]:
    """Convert parsed blocks into a section hierarchy (see module docstring for the rules)."""
    builder = _TreeBuilder(parsed)
    for block in parsed.blocks:
        builder.add(block)
    return builder.roots
