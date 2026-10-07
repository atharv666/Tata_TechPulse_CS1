"""Normalized, parser-neutral document representation used before persistence."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class DocumentFormat(StrEnum):
    PDF = "pdf"
    DOCX = "docx"
    XLSX = "xlsx"
    CSV = "csv"
    MARKDOWN = "markdown"


@dataclass(frozen=True)
class SourcePosition:
    page: int | None = None
    start_offset: int | None = None
    end_offset: int | None = None


@dataclass(frozen=True)
class TableData:
    rows: list[list[str]]
    position: SourcePosition


@dataclass
class ParsedBlock:
    text: str
    position: SourcePosition
    tables: list[TableData] = field(default_factory=list)
    warning: str | None = None


@dataclass
class ParsedDocument:
    blocks: list[ParsedBlock]
    warnings: list[str] = field(default_factory=list)


@dataclass
class NormalizedSection:
    heading: str
    level: int
    position: SourcePosition
    content: list[ParsedBlock] = field(default_factory=list)
    children: list[NormalizedSection] = field(default_factory=list)


@dataclass(frozen=True)
class IngestionResult:
    checksum: str
    document_format: DocumentFormat
    sections: list[NormalizedSection]
    warnings: list[str]


class IngestionError(ValueError):
    """Expected validation, parsing, or normalization failure with a safe message."""
