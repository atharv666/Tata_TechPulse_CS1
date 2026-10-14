"""Structure-aware chunking: sizes, boundaries, tables, lists, pages and the section plan."""

from __future__ import annotations

import pytest
from app.ingestion.chunking import chunk_section, plan_document
from app.ingestion.contracts import (
    BlockKind,
    NormalizedSection,
    ParsedBlock,
    SourcePosition,
    TableData,
)
from app.ingestion.text import (
    estimate_tokens,
    render_table_markdown,
    split_sentences,
    truncate_at_sentence,
)


def section(
    *blocks: ParsedBlock, heading: str = "Interfaces", level: int = 2
) -> NormalizedSection:
    return NormalizedSection(
        heading, level, SourcePosition(page=4), content=list(blocks)
    )


def para(text: str, page: int = 4) -> ParsedBlock:
    return ParsedBlock(text, SourcePosition(page=page))


def table(rows: list[list[str]], page: int = 4) -> ParsedBlock:
    position = SourcePosition(page=page)
    return ParsedBlock(
        render_table_markdown(rows),
        position,
        [TableData(rows, position)],
        kind=BlockKind.TABLE,
    )


def test_small_section_is_one_chunk_with_raw_content_and_no_injected_heading() -> None:
    chunks = chunk_section(
        section(para("First paragraph."), para("Second paragraph.")), 800, 80
    )

    assert len(chunks) == 1
    assert chunks[0].content == "First paragraph.\n\nSecond paragraph."
    assert not chunks[0].content.startswith(
        "Section:"
    )  # the breadcrumb is stored separately
    assert chunks[0].page_start == chunks[0].page_end == 4
    assert chunks[0].kind == "TEXT"


def test_atoms_are_packed_up_to_the_target_and_never_cut_when_they_fit() -> None:
    paragraphs = [
        para(f"Sentence number {i} about the brake controller interface.")
        for i in range(12)
    ]
    chunks = chunk_section(
        section(*paragraphs), max_tokens=200, overlap_tokens=0, target_tokens=40
    )

    assert len(chunks) > 1
    assert all(c.token_count <= 200 for c in chunks)
    rebuilt = "\n\n".join(c.content for c in chunks)
    for i in range(12):
        assert (
            f"Sentence number {i} about" in rebuilt
        )  # nothing lost, nothing cut mid-paragraph


def test_oversized_paragraph_is_split_at_sentences_with_overlap() -> None:
    sentences = [f"Sentence {i} states a distinct engineering fact." for i in range(30)]
    chunks = chunk_section(
        section(para(" ".join(sentences))), max_tokens=60, overlap_tokens=12
    )

    assert len(chunks) > 2
    assert all(c.token_count <= 60 + 12 for c in chunks)
    for chunk in chunks:  # every chunk starts and ends on a sentence boundary
        assert chunk.content.startswith("Sentence ") and chunk.content.endswith("fact.")
    # overlap: the first sentence of chunk n+1 already appeared at the end of chunk n
    first_of_next = chunks[1].content.split(". ")[0]
    assert first_of_next in chunks[0].content


def test_list_items_stay_on_separate_lines_and_are_split_between_items() -> None:
    items = "\n".join(f"- `Signal{i}` is carried by the interface" for i in range(40))
    chunks = chunk_section(section(para(items)), max_tokens=80, overlap_tokens=0)

    assert len(chunks) > 1
    for chunk in chunks:
        assert all(line.startswith("- ") for line in chunk.content.split("\n") if line)
    assert sum(c.content.count("\n") + 1 for c in chunks) == 40


def test_large_table_is_split_by_rows_and_repeats_its_header() -> None:
    rows = [["Signal", "Type"]] + [[f"S{i}", "uint16"] for i in range(60)]
    chunks = chunk_section(section(table(rows)), max_tokens=100, overlap_tokens=0)

    assert len(chunks) > 1
    for chunk in chunks:
        assert chunk.kind == "TABLE"
        assert chunk.content.startswith("| Signal | Type |\n| --- | --- |")
    data_rows = [
        line
        for c in chunks
        for line in c.content.split("\n")[2:]
        if line.startswith("| S")
    ]
    assert len(data_rows) == 60


def test_ocr_text_is_flagged_on_the_chunk() -> None:
    block = ParsedBlock("Recovered from a scan.", SourcePosition(page=2), ocr=True)
    chunks = chunk_section(section(block), 800, 80)
    assert chunks[0].kind == "OCR_TEXT"


def test_page_range_spans_the_pages_of_the_chunk_content() -> None:
    chunks = chunk_section(
        section(para("On page three.", 3), para("On page five.", 5)), 800, 80
    )
    assert (chunks[0].page_start, chunks[0].page_end) == (3, 5)


def test_tiny_trailing_fragment_is_merged_into_the_previous_chunk() -> None:
    paragraphs = [para("word " * 38 + "end.") for _ in range(3)] + [para("Tail.")]
    chunks = chunk_section(
        section(*paragraphs), max_tokens=300, overlap_tokens=0, target_tokens=80
    )
    assert all(c.content != "Tail." for c in chunks)
    assert chunks[-1].content.endswith("Tail.")


def test_empty_section_produces_no_chunks_and_overlap_must_be_smaller_than_max() -> (
    None
):
    assert chunk_section(section(), 800, 80) == []
    with pytest.raises(ValueError):
        chunk_section(section(para("x")), max_tokens=10, overlap_tokens=10)


def test_plan_flattens_tree_with_ordinals_parents_paths_and_pages() -> None:
    root = NormalizedSection(
        "System", 1, SourcePosition(page=1), [para("Root text.", 1)], number="1"
    )
    child = NormalizedSection(
        "Components", 2, SourcePosition(page=2), [para("Child.", 2)], number="1.1"
    )
    grandchild = NormalizedSection(
        "Sensors", 3, SourcePosition(page=3), [para("Leaf.", 3)], number="1.1.1"
    )
    child.children.append(grandchild)
    root.children.append(child)
    preamble = NormalizedSection(
        "Document content",
        0,
        SourcePosition(page=1),
        [para("Intro.", 1)],
        preamble=True,
    )

    plan = plan_document([preamble, root], 800, 80)

    assert [p.ordinal for p in plan] == [1, 2, 3, 4]
    assert [p.parent_ordinal for p in plan] == [None, None, 2, 3]
    assert [p.path for p in plan] == [
        "",
        "1 System",
        "1 System > 1.1 Components",
        "1 System > 1.1 Components > 1.1.1 Sensors",
    ]
    assert [p.depth for p in plan] == [0, 1, 2, 3]
    assert plan[3].page_start == plan[3].page_end == 3
    assert all(len(p.chunks) == 1 for p in plan)


def test_text_helpers() -> None:
    assert estimate_tokens("P_WheelSpeed_In = 0.5;") >= 6
    assert split_sentences("The ECU is on. It sends 0.5 V to X. Done.") == [
        "The ECU is on.",
        "It sends 0.5 V to X.",
        "Done.",
    ]
    text, truncated = truncate_at_sentence(
        "One fact. Two facts. Three facts. Four facts.", 6
    )
    assert truncated and text.startswith("One fact.") and "Four" not in text


def test_stemmer_conflates_inflections_consistently() -> None:
    from app.ingestion.text import stem

    for group in (
        ("compute", "computes", "computed", "computing"),
        ("require", "requires", "required"),
        ("provide", "provides", "provided"),
        ("interface", "interfaces"),
        ("consume", "consumes", "consumed"),
    ):
        assert len({stem(word) for word in group}) == 1, group
    assert stem("provides") != stem("requires")  # different verbs must stay different
