"""Nested-structure detection: the foundation every later RAG step stands on.

Several tests reproduce failures observed with the previous normaliser on real-looking PDF text:
body lines starting with a number became headings, an empty "heading" silently deleted text, nested
sections got the wrong parent, and running headers/footers leaked into the content.
"""

from __future__ import annotations

from app.ingestion.contracts import (
    BlockKind,
    NormalizedSection,
    ParsedBlock,
    ParsedDocument,
    SourcePosition,
)
from app.ingestion.normalize import normalize_document
from app.ingestion.parsers import DOCXParser, MarkdownParser, PDFParser
from app.ingestion.structure import (
    NumberingTracker,
    looks_like_heading_text,
    split_number,
)

from tests.support.documents import (
    HEADER_TEXT,
    make_docx_with_styles,
    make_nested_pdf,
    make_toc_pdf,
    make_toc_pdf_with_contents_page,
)


def walk(sections: list[NormalizedSection], depth: int = 0):
    for section in sections:
        yield depth, section
        yield from walk(section.children, depth + 1)


def outline(sections: list[NormalizedSection]) -> list[tuple[int, str]]:
    return [(depth, section.display_heading) for depth, section in walk(sections)]


def all_text(sections: list[NormalizedSection]) -> str:
    return " ".join(block.text for _, s in walk(sections) for block in s.content)


# ---- numbering rules -------------------------------------------------------------------------
def test_split_number() -> None:
    assert split_number("1.2 Interfaces") == ("1.2", "Interfaces")
    assert split_number("3. Overview") == ("3", "Overview")
    assert split_number("A.1 Glossary") == ("A.1", "Glossary")
    assert split_number("Overview") == (None, "Overview")
    assert split_number("0.00 to 320.00") == (None, "0.00 to 320.00")


def test_heading_shape_rejects_sentences_and_units() -> None:
    assert looks_like_heading_text("Wheel Speed Interface")
    assert not looks_like_heading_text(
        "channels that are sampled every 10 ms. The supply is"
    )
    assert not looks_like_heading_text("V nominal.")
    assert not looks_like_heading_text("lowercase start")
    assert not looks_like_heading_text("A " + "very long title " * 12)


def test_numbering_sequence_accepts_children_and_siblings_only() -> None:
    tracker = NumberingTracker()
    assert tracker.accepts("1", "Scope")
    tracker.accept("1")
    assert tracker.accepts("1.1", "Purpose")  # first child
    assert tracker.accepts("2", "Interfaces")  # next sibling
    assert not tracker.accepts("1.4", "Odd")  # would skip children without a 1.1
    tracker.accept("1.1")
    assert tracker.accepts("1.2", "Next")
    assert tracker.accepts("2", "Up one level")
    assert not tracker.accepts("1.1.3", "Deep jump")
    assert not tracker.accepts("9", "Far jump")


# ---- normaliser: the old failures ------------------------------------------------------------
def build(lines: list[str], structure: str = "none") -> list[NormalizedSection]:
    page = SourcePosition(page=1)
    blocks = [ParsedBlock("\n".join(lines), page)]
    return normalize_document(ParsedDocument(blocks=blocks, structure_source=structure))


def test_body_lines_that_start_with_numbers_are_not_headings_and_no_text_is_lost() -> (
    None
):
    sections = build(
        [
            "1. Brake Subsystem",
            "The controller reads wheel speed over 3 channels that are sampled every 10 ms.",
            "12 V nominal.",
            "1.1 Wheel Speed Interface",
            "The interface carries the signal.",
        ]
    )
    assert outline(sections) == [
        (0, "1 Brake Subsystem"),
        (1, "1.1 Wheel Speed Interface"),
    ]
    text = all_text(sections)
    assert "3 channels that are sampled every 10 ms" in text
    assert "12 V nominal." in text


def test_nested_sections_get_the_correct_parent_and_text_stays_in_its_section() -> None:
    sections = build(
        [
            "1 System",
            "System text.",
            "1.1 Components",
            "Component text.",
            "1.1.1 Sensors",
            "Sensor text.",
            "1.2 Interfaces",
            "Interface text.",
            "2 Diagnostics",
            "Diagnostic text.",
        ]
    )
    assert outline(sections) == [
        (0, "1 System"),
        (1, "1.1 Components"),
        (2, "1.1.1 Sensors"),
        (1, "1.2 Interfaces"),
        (0, "2 Diagnostics"),
    ]
    by_heading = {s.heading: s for _, s in walk(sections)}
    assert [b.text for b in by_heading["Sensors"].content] == ["Sensor text."]
    assert [b.text for b in by_heading["Interfaces"].content] == ["Interface text."]


def test_headings_without_content_are_kept_as_part_of_the_hierarchy() -> None:
    sections = build(["1 Parent", "1.1 Empty child", "1.2 Child with text", "Text."])
    assert (1, "1.1 Empty child") in outline(sections)


def test_text_before_the_first_heading_goes_to_a_preamble_section() -> None:
    sections = build(["Intro line without a heading.", "1 First", "Body."])
    assert sections[0].level == 0 and sections[0].heading == "Document content"
    assert sections[0].content[0].text == "Intro line without a heading."
    assert sections[1].heading == "First"


def test_authoritative_structure_never_promotes_numbered_body_lines() -> None:
    page = SourcePosition(page=1)
    parsed = ParsedDocument(
        blocks=[
            ParsedBlock("Overview", page, kind=BlockKind.HEADING, heading_level=1),
            ParsedBlock("2 Hz is the sample rate", page),
        ],
        structure_source="style",
    )
    sections = normalize_document(parsed)
    assert outline(sections) == [(0, "Overview")]
    assert sections[0].content[0].text == "2 Hz is the sample rate"


# ---- PDF layout ------------------------------------------------------------------------------
def test_pdf_font_sizes_define_nested_headings_and_running_lines_are_removed() -> None:
    parsed = PDFParser().parse(make_nested_pdf())
    sections = normalize_document(parsed)

    assert parsed.structure_source == "font"
    assert outline(sections) == [
        (0, "1 Brake Subsystem"),
        (1, "1.1 Wheel Speed Interface"),
        (1, "1.2 Brake Command Interface"),
        (0, "2 Diagnostics"),
    ]
    text = all_text(sections)
    assert HEADER_TEXT not in text and "Confidential | Reference" not in text
    assert parsed.removed_running_lines >= 6  # 3 headers + 3 footers
    # the numeric body lines survive inside the right section, re-flowed into one paragraph
    first = sections[0]
    assert "3 channels that are sampled every 10 ms" in first.content[0].text
    assert "12 V nominal." in first.content[0].text
    assert "\n" not in first.content[0].text


def test_pdf_pages_are_recorded_per_block_and_section() -> None:
    sections = normalize_document(PDFParser().parse(make_nested_pdf()))
    by_heading = {s.heading: s for _, s in walk(sections)}
    assert by_heading["Brake Subsystem"].position.page == 1
    assert by_heading["Brake Command Interface"].position.page == 2
    assert by_heading["Diagnostics"].position.page == 2


def test_pdf_bookmarks_are_authoritative_even_when_headings_look_like_body_text() -> (
    None
):
    parsed = PDFParser().parse(make_toc_pdf())
    sections = normalize_document(parsed)
    assert parsed.structure_source == "toc"
    assert outline(sections) == [(0, "Introduction"), (1, "Scope"), (0, "Interfaces")]
    assert "The controller uses the WheelSpeedInterface." in all_text(sections)


def test_printed_table_of_contents_lines_are_not_indexed_as_content() -> None:
    parsed = PDFParser().parse(make_toc_pdf_with_contents_page())
    text = all_text(normalize_document(parsed))
    assert "......" not in text
    assert "Overview text about the BrakeController." in text


# ---- Word and Markdown -----------------------------------------------------------------------
def test_word_heading_styles_lists_and_tables_keep_reading_order() -> None:
    parsed = DOCXParser().parse(make_docx_with_styles())
    sections = normalize_document(parsed)

    assert parsed.structure_source == "style"
    assert outline(sections) == [
        (0, "Brake Controller HLD"),
        (1, "Architecture"),
        (2, "Components"),
        (1, "Interfaces"),
    ]
    components = next(s for _, s in walk(sections) if s.heading == "Components")
    kinds = [block.kind for block in components.content]
    assert kinds == [BlockKind.PARAGRAPH, BlockKind.TABLE, BlockKind.PARAGRAPH]
    assert components.content[0].text == "- WheelSpeedSensor\n- ABS_Module"
    assert (
        "| Speed | uint16 |" in components.content[1].text
    )  # the table is not moved to the end
    assert components.content[2].text == "Text after the table."


def test_markdown_headings_lists_tables_and_numbers() -> None:
    source = (
        "# Title\nDocument Version: 1.0\n\n## 1. Scope\nSoft wrapped\nsentence here.\n\n"
        "- item one\n- item two\n\n| A | B |\n| --- | --- |\n| 1 | 2 |\n\n### 1.1 Detail\nText.\n"
    )
    parsed = MarkdownParser().parse(source.encode())
    sections = normalize_document(parsed)

    assert outline(sections) == [(0, "Title"), (1, "1 Scope"), (2, "1.1 Detail")]
    scope = sections[0].children[0]
    assert scope.content[0].text == "Soft wrapped sentence here."
    assert scope.content[1].text == "- item one\n- item two"
    assert scope.content[2].kind is BlockKind.TABLE
    assert sections[0].children[0].children[0].number == "1.1"
