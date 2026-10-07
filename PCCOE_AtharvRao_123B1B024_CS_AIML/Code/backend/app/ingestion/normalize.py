"""Build a section hierarchy without semantic interpretation or model calls."""

from __future__ import annotations

from app.ingestion.contracts import NormalizedSection, ParsedBlock, ParsedDocument, SourcePosition
from app.ingestion.parsers import HEADING_PATTERN, table_as_evidence


def normalize_document(parsed: ParsedDocument) -> list[NormalizedSection]:
    """Convert parsed blocks to a hierarchy based on explicit Markdown or numbered headings."""
    roots: list[NormalizedSection] = []
    stack: list[NormalizedSection] = []
    fallback = NormalizedSection("Document content", 1, SourcePosition())
    roots.append(fallback)
    for block in parsed.blocks:
        for text_block in _split_block(block):
            heading = _heading(text_block.text)
            if heading is not None:
                title, level = heading
                section = NormalizedSection(title, level, text_block.position)
                while stack and stack[-1].level >= level:
                    stack.pop()
                if stack:
                    stack[-1].children.append(section)
                else:
                    roots.append(section)
                stack.append(section)
                continue
            target = stack[-1] if stack else fallback
            if text_block.text.strip() or text_block.tables:
                target.content.append(text_block)
    return [section for section in roots if section.content or section.children]


def _split_block(block: ParsedBlock) -> list[ParsedBlock]:
    lines = block.text.splitlines() or [""]
    result = [ParsedBlock(line.strip(), block.position) for line in lines if line.strip()]
    result.extend(ParsedBlock(table_as_evidence(table), table.position) for table in block.tables)
    return result


def _heading(text: str) -> tuple[str, int] | None:
    match = HEADING_PATTERN.match(text.strip())
    if match is None:
        return None
    if match.group("hash"):
        return match.group("markdown").strip(), len(match.group("hash"))
    number = match.group("number").rstrip(".")
    return match.group("title").strip(), number.count(".") + 1
