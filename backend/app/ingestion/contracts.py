"""Normalized, parser-neutral document representation used before persistence."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class DocumentFormat(StrEnum):
    PDF = "pdf"
    DOCX = "docx"
    XLSX = "xlsx"
    CSV = "csv"
    MARKDOWN = "markdown"


class BlockKind(StrEnum):
    PARAGRAPH = "paragraph"
    HEADING = "heading"
    TABLE = "table"


@dataclass(frozen=True)
class SourcePosition:
    page: int | None = None
    start_offset: int | None = None
    end_offset: int | None = None


@dataclass(frozen=True)
class TableData:
    rows: list[list[str]]
    position: SourcePosition
    caption: str | None = None


@dataclass
class ParsedBlock:
    """One paragraph, heading or table, in reading order.

    ``heading_level`` / ``heading_source`` are set by a parser only when the format itself says the
    text is a heading (bookmarks, Word styles, Markdown ``#``, font size). Headings that can only be
    guessed from numbering are decided later, with validation, by the normalizer.
    """

    text: str
    position: SourcePosition
    tables: list[TableData] = field(default_factory=list)
    warning: str | None = None
    kind: BlockKind = BlockKind.PARAGRAPH
    heading_level: int | None = None
    heading_source: str | None = None
    ocr: bool = False


@dataclass
class ParsedDocument:
    blocks: list[ParsedBlock]
    warnings: list[str] = field(default_factory=list)
    #: Where the heading structure came from: toc | style | font | markdown | none.
    structure_source: str = "none"
    #: Format-level metadata (title, author, dates, ...), merged with header-line metadata later.
    metadata: dict[str, Any] = field(default_factory=dict)
    ocr_pages: list[int] = field(default_factory=list)
    removed_running_lines: int = 0


@dataclass
class NormalizedSection:
    heading: str
    level: int
    position: SourcePosition
    content: list[ParsedBlock] = field(default_factory=list)
    children: list[NormalizedSection] = field(default_factory=list)
    number: str | None = None
    #: True only for the synthetic section that holds text appearing before the first heading.
    preamble: bool = False

    @property
    def display_heading(self) -> str:
        """The heading as a reader cites it: ``1.1 Components and Interfaces``."""
        return f"{self.number} {self.heading}".strip() if self.number else self.heading

    def subtree_pages(self) -> list[int]:
        pages = [self.position.page] if self.position.page is not None else []
        pages += [b.position.page for b in self.content if b.position.page is not None]
        for child in self.children:
            pages += child.subtree_pages()
        return pages


@dataclass(frozen=True)
class IngestionResult:
    checksum: str
    document_format: DocumentFormat
    sections: list[NormalizedSection]
    warnings: list[str]
    metadata: dict[str, Any] = field(default_factory=dict)
    structure_source: str = "none"
    ocr_pages: list[int] = field(default_factory=list)


class IngestionError(ValueError):
    """Expected validation, parsing, or normalization failure with a safe message."""

    safe_to_report = True
