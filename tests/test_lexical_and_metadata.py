"""Identifier-aware lexical preparation and deterministic metadata extraction."""

from __future__ import annotations

from app.ingestion.contracts import (
    BlockKind,
    ParsedBlock,
    ParsedDocument,
    SourcePosition,
    TableData,
)
from app.ingestion.lexical import (
    build_lexical_text,
    build_tsquery,
    matched_term_ratio,
    query_terms,
    split_identifier,
)
from app.ingestion.metadata import extract_metadata
from app.ingestion.normalize import normalize_document
from app.ingestion.parsers import MarkdownParser


def test_split_identifier_handles_snake_camel_acronyms_and_digits() -> None:
    assert split_identifier("P_WheelSpeed_In") == ["p", "wheel", "speed", "in"]
    assert split_identifier("BrakeCtrl") == ["brake", "ctrl"]
    assert split_identifier("ABSModule") == ["abs", "module"]
    assert split_identifier("ISO14229") == ["iso", "14229"]
    assert split_identifier("Rte_Read_SpeedPort_Speed") == [
        "rte",
        "read",
        "speed",
        "port",
        "speed",
    ]


def test_lexical_text_contains_joined_and_spaced_identifier_forms() -> None:
    text = build_lexical_text(
        "HLD > 1.1 Components", "`P_WheelSpeed_In` feeds ABS_Module/ESP_Module"
    )
    words = set(text.split())
    assert {"pwheelspeedin", "p", "wheelspeed", "in"} <= words  # exact + parts
    assert "wheel speed" in text  # spaced phrase for natural-language queries
    assert {
        "abs",
        "module",
        "esp",
    } <= words and "module/esp_module" not in text  # slash split


def test_tsquery_matches_exact_identifiers_and_their_spaced_form() -> None:
    query = build_tsquery("What does BrakeCtrl require?")
    assert query == "(brakectrl | (brake <-> ctrl)) | require"
    assert build_tsquery("the of a") is None  # nothing but stop words
    assert (
        build_tsquery("P_WheelSpeed_In")
        == "(pwheelspeedin | (p <-> wheel <-> speed <-> in))"
    )


def test_tsquery_only_contains_safe_alphanumeric_tokens() -> None:
    query = build_tsquery("'; DROP TABLE chunks; -- & | ! ( ) <-> :*")
    assert query is not None
    assert all(ch.isalnum() or ch in " |()<>-" for ch in query)
    assert "DROP" not in query  # lower-cased
    assert ";" not in query and "'" not in query and ":" not in query


def test_query_terms_dedupe_and_drop_stopwords() -> None:
    terms = query_terms("Which components consume WheelSpeedInterface? components!")
    assert [t.joined for t in terms] == ["components", "consume", "wheelspeedinterface"]


def test_matched_term_ratio_is_an_explainable_overlap_signal() -> None:
    passage = build_lexical_text(
        "The BrakeController provides the BrakeCommandInterface"
    )
    assert matched_term_ratio("what provides BrakeCommandInterface", passage) == 1.0
    assert matched_term_ratio("battery charging specification", passage) == 0.0


# ---- metadata -------------------------------------------------------------------------------
def test_markdown_header_lines_become_metadata() -> None:
    source = (
        "# AUTOSAR HLD: Brake Controller\nDocument Version: 1.0.0\nClassification: Synthetic\n"
        "Status: Approved\nAuthor: A. Rao\n\n## 1. Scope\nText.\n"
    )
    parsed = MarkdownParser().parse(source.encode())
    metadata = extract_metadata(parsed, normalize_document(parsed), "hld.md")

    assert metadata["version"] == "1.0.0"
    assert metadata["classification"] == "Synthetic"
    assert metadata["status"] == "Approved"
    assert metadata["author"] == "A. Rao"
    assert metadata["title"] == "AUTOSAR HLD: Brake Controller"
    assert metadata["filename"] == "hld.md"


def test_format_properties_are_kept_and_body_header_lines_override_them() -> None:
    page = SourcePosition(page=1)
    parsed = ParsedDocument(
        blocks=[
            ParsedBlock("Revision: 3.2", page),
            ParsedBlock("Overview", page, kind=BlockKind.HEADING, heading_level=1),
        ],
        metadata={
            "title": "Properties title",
            "author": "File Author",
            "page_count": 12,
        },
    )
    metadata = extract_metadata(parsed, normalize_document(parsed), "x.pdf")

    assert metadata["version"] == "3.2"
    assert metadata["page_count"] == 12
    assert metadata["title"] == "Properties title"


def test_revision_history_table_is_extracted() -> None:
    rows = [
        ["Version", "Date", "Description", "Author"],
        ["1.0", "2026-01-10", "Initial release", "AR"],
        ["1.1", "2026-02-02", "Added regen braking", "AR"],
    ]
    position = SourcePosition(page=1)
    parsed = ParsedDocument(
        blocks=[
            ParsedBlock(
                "table", position, [TableData(rows, position)], kind=BlockKind.TABLE
            )
        ]
    )
    metadata = extract_metadata(parsed, normalize_document(parsed), "x.pdf")

    assert metadata["revision_history"][1] == {
        "version": "1.1",
        "date": "2026-02-02",
        "description": "Added regen braking",
        "author": "AR",
    }
