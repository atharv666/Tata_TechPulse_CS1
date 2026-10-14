"""Pure-logic RAG pieces: rank fusion, diversification, claim verification, HNSW-independent maths."""

from __future__ import annotations

from uuid import uuid4

from app.retrieval.answer import AnswerDraft, ClaimDraft, verify_claim
from app.retrieval.rag import RetrievedChunk, reciprocal_rank_fusion, select_diverse


def chunk(section, name: str = "c") -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=uuid4(),
        document_id=uuid4(),
        document_version_id=uuid4(),
        document_name="d.md",
        section_id=section,
        section_heading=name,
        section_path=name,
        section_ordinal=1,
        chunk_ordinal=1,
        breadcrumb="d.md",
        content=name,
        lexical_text=name,
        page_start=None,
        page_end=None,
        kind="TEXT",
    )


# ---- reciprocal rank fusion ------------------------------------------------------------------
def test_rrf_rewards_agreement_between_channels() -> None:
    a, b, c = uuid4(), uuid4(), uuid4()
    scores = reciprocal_rank_fusion(
        {"dense0": [a, b, c], "lexical0": [b, c, a]},
        {"dense0": 1.0, "lexical0": 1.0},
        k=60,
    )
    ranking = sorted(scores, key=scores.get, reverse=True)  # type: ignore[arg-type]
    assert ranking[0] == b  # rank 2 + rank 1 beats rank 1 + rank 3
    assert scores[b] == 1 / 62 + 1 / 61


def test_rrf_includes_items_found_by_only_one_channel_and_honours_weights() -> None:
    dense_only, lexical_only = uuid4(), uuid4()
    scores = reciprocal_rank_fusion(
        {"dense0": [dense_only], "lexical0": [lexical_only]},
        {"dense0": 1.0, "lexical0": 2.0},
        k=10,
    )
    assert scores[lexical_only] == 2 * scores[dense_only]


def test_rrf_with_identical_scores_is_stable() -> None:
    ids = [uuid4() for _ in range(3)]
    first = reciprocal_rank_fusion({"d": ids}, {"d": 1.0}, 60)
    second = reciprocal_rank_fusion({"d": ids}, {"d": 1.0}, 60)
    assert first == second


# ---- diversity -------------------------------------------------------------------------------
def test_select_diverse_caps_chunks_per_section_then_fills_remaining_slots() -> None:
    big, other = uuid4(), uuid4()
    ordered = [chunk(big, f"big{i}") for i in range(5)] + [chunk(other, "other")]

    chosen = select_diverse(ordered, top_k=4, max_per_section=2)

    assert [c.section_heading for c in chosen] == ["big0", "big1", "other", "big2"]


def test_select_diverse_returns_what_exists_when_fewer_than_top_k() -> None:
    only = uuid4()
    chosen = select_diverse(
        [chunk(only, "a"), chunk(only, "b"), chunk(only, "c")], 8, 1
    )
    assert len(chosen) == 3  # a single big section is still returned, never emptied


# ---- claim verification ---------------------------------------------------------------------
SOURCE = (
    "BrakeController REQUIRES WheelSpeedInterface through input port P_WheelSpeed_In. "
    "The signal is sampled every 10 ms."
)


def test_claim_supported_by_cited_text() -> None:
    check = verify_claim("BrakeController requires WheelSpeedInterface", [SOURCE])
    assert check.supported and check.support == 1.0


def test_claim_with_an_invented_identifier_is_rejected_even_if_the_rest_matches() -> (
    None
):
    check = verify_claim("BrakeController requires TorqueVectoringInterface", [SOURCE])
    assert not check.supported and "torquevectoringinterface" in check.missing


def test_claim_with_a_wrong_number_is_rejected() -> None:
    assert not verify_claim("The signal is sampled every 20 ms", [SOURCE]).supported
    assert verify_claim("The signal is sampled every 10 ms", [SOURCE]).supported


def test_identifier_spacing_and_case_do_not_break_support() -> None:
    # prose that spells an identifier out as words is still supported by the identifier text
    assert verify_claim(
        "The Brake Controller requires the wheel speed interface", [SOURCE]
    ).supported


def test_a_swapped_relationship_verb_is_rejected() -> None:
    """Source says REQUIRES; claiming 'provides' with the same identifiers is a hallucination."""
    assert verify_claim(
        "BrakeController requires WheelSpeedInterface", [SOURCE]
    ).supported
    wrong = verify_claim("BrakeController provides WheelSpeedInterface", [SOURCE])
    assert not wrong.supported and wrong.support == 0.0


def test_acronym_must_appear_in_the_source() -> None:
    claim = "The ABS module consumes the signal"
    assert not verify_claim(
        claim, [SOURCE]
    ).supported  # "ABS" is not in the source at all
    assert not verify_claim(
        claim, [SOURCE + " ABS reads it."]
    ).supported  # not what it says
    assert verify_claim(
        claim, [SOURCE + " The ABS module consumes the signal."]
    ).supported


def test_unrelated_prose_is_rejected_by_word_coverage() -> None:
    check = verify_claim("Batteries charge slowly during winter", [SOURCE])
    assert not check.supported and check.support < 0.6


def test_answer_draft_schema_defaults_are_safe() -> None:
    draft = AnswerDraft()
    assert draft.claims == [] and draft.insufficient_evidence is False
    assert ClaimDraft(text="x").extraction_type == "EXPLICIT"
