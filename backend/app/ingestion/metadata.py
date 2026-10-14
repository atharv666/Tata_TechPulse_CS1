"""Deterministic document metadata: title, version, date, status, classification, revision history.

Sources, strongest first: format properties (PDF info dictionary, Word core properties),
``Key: value`` header lines near the top of the document, and a revision-history table.
No LLM is involved, so the values are reproducible and always traceable to text that is
in the document.
"""

from __future__ import annotations

import re
from typing import Any

from app.ingestion.contracts import BlockKind, NormalizedSection, ParsedDocument

MAX_VALUE_CHARS = 200
_SCAN_LINES = 60
_HEADER_FIELDS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "document_id",
        re.compile(r"^(?:document|doc)\.?\s*(?:id|no\.?|number)\s*[:\-]\s*(.+)$", re.I),
    ),
    (
        "version",
        re.compile(r"^(?:document\s+)?(?:version|revision|rev\.?)\s*[:\-]\s*([\w.\-]+)", re.I),
    ),
    ("date", re.compile(r"^(?:date|released?|issued|issue date)\s*[:\-]\s*(.+)$", re.I)),
    ("status", re.compile(r"^(?:document\s+)?status\s*[:\-]\s*(.+)$", re.I)),
    ("classification", re.compile(r"^classification\s*[:\-]\s*(.+)$", re.I)),
    ("author", re.compile(r"^(?:author|owner|prepared by|written by)\s*[:\-]\s*(.+)$", re.I)),
    ("title", re.compile(r"^(?:document\s+)?title\s*[:\-]\s*(.+)$", re.I)),
)
_REVISION_HEADER_KEYS = (
    ("version", ("version", "rev", "revision")),
    ("date", ("date",)),
    ("description", ("description", "change", "comment", "summary")),
    ("author", ("author", "owner", "by")),
)


def _clean(value: str) -> str:
    return " ".join(value.split())[:MAX_VALUE_CHARS]


def _leading_lines(sections: list[NormalizedSection]) -> list[str]:
    lines: list[str] = []

    def visit(section: NormalizedSection) -> None:
        for block in section.content:
            if block.kind is BlockKind.TABLE:
                continue
            lines.extend(line.strip() for line in block.text.split("\n") if line.strip())
            if len(lines) >= _SCAN_LINES:
                return
        for child in section.children:
            if len(lines) < _SCAN_LINES:
                visit(child)

    for section in sections:
        if len(lines) >= _SCAN_LINES:
            break
        visit(section)
    return lines[:_SCAN_LINES]


def _revision_history(parsed: ParsedDocument) -> list[dict[str, str]]:
    for block in parsed.blocks:
        for table in block.tables:
            if len(table.rows) < 2:
                continue
            header = [cell.strip().lower() for cell in table.rows[0]]
            mapping: dict[str, int] = {}
            for field_name, keys in _REVISION_HEADER_KEYS:
                for index, cell in enumerate(header):
                    if any(cell.startswith(key) for key in keys) and index not in mapping.values():
                        mapping[field_name] = index
                        break
            if "version" in mapping and "date" in mapping and len(mapping) >= 3:
                history = []
                for row in table.rows[1:]:
                    entry = {
                        name: _clean(row[index])
                        for name, index in mapping.items()
                        if index < len(row)
                    }
                    if any(entry.values()):
                        history.append(entry)
                return history[:100]
    return []


def extract_metadata(
    parsed: ParsedDocument, sections: list[NormalizedSection], filename: str
) -> dict[str, Any]:
    """Merge format properties with header lines; keep only non-empty, short values."""
    metadata: dict[str, Any] = {
        key: _clean(str(value)) if isinstance(value, str) else value
        for key, value in parsed.metadata.items()
        if value not in (None, "")
    }
    found: dict[str, str] = {}
    for line in _leading_lines(sections):
        for name, pattern in _HEADER_FIELDS:
            match = pattern.match(line)
            if match and name not in found:
                found[name] = _clean(match.group(1))
    for name, value in found.items():
        # Header lines in the document body are authoritative over generic file properties.
        metadata[name] = value
    if "title" not in metadata:
        first = next((s for s in sections if not s.preamble), None) or (
            sections[0] if sections else None
        )
        if first is not None:
            metadata["title"] = _clean(first.display_heading)
    history = _revision_history(parsed)
    if history:
        metadata["revision_history"] = history
    metadata["filename"] = filename
    return metadata
