"""Statement-level claim verification and trace redaction."""

from __future__ import annotations

from app.retrieval.answer import redact_trace, statement_units, verify_claim

BULLETS = (
    "- `AbsController` `REQUIRES` `WheelSpeedInterface` through input port `P_WheelSpeed_In`.\n"
    "- `AbsController` `PROVIDES` `ValveCommandInterface` through output port `P_ValveCmd_Out`."
)
TABLE = (
    "| DID | Name | Length |\n| --- | --- | --- |\n"
    "| 0xF190 | VehicleIdentificationNumber | 17 |\n| 0xF18C | EcuSerialNumber | 12 |"
)


def test_swapped_arguments_across_adjacent_statements_are_rejected() -> None:
    """Both identifiers and the verb exist in the chunk, but never together in one statement."""
    assert verify_claim(
        "AbsController requires WheelSpeedInterface", [BULLETS]
    ).supported
    swapped = verify_claim("AbsController provides WheelSpeedInterface", [BULLETS])
    assert not swapped.supported


def test_identifiers_spread_over_different_statements_are_reported_as_such() -> None:
    check = verify_claim("WheelSpeedInterface ValveCommandInterface", [BULLETS])
    assert not check.supported and "different statements" in check.reason


def test_table_rows_use_their_header_as_context() -> None:
    assert verify_claim("DID 0xF190 is VehicleIdentificationNumber", [TABLE]).supported
    assert not verify_claim(
        "DID 0xF190 is EcuSerialNumber", [TABLE]
    ).supported  # wrong row
    assert verify_claim("The Length of 0xF18C is 12", [TABLE]).supported


def test_statement_units_split_lines_sentences_and_table_rows() -> None:
    text = "First fact. Second fact.\n- item\n| A | B |\n| --- | --- |\n| 1 | 2 |"
    units = statement_units(text)
    assert [unit for unit, _ in units] == [
        "First fact.",
        "Second fact.",
        "- item",
        "| 1 | 2 |",
    ]
    assert units[-1][1] == "| A | B |"


def test_breadcrumb_context_counts_for_every_statement() -> None:
    claim = "Diagnostics follows ISO 14229"
    source = ["Service 0x22 follows ISO 14229."]
    assert not verify_claim(claim, source).supported
    context = "3 Timing and Diagnostics > 3.2 Diagnostics"
    assert verify_claim(claim, source, context=context).supported


def test_redact_trace_hides_query_text_unless_enabled() -> None:
    question = "What does SlipEstimator compute?"
    trace = {"rounds": [{"queries": [question], "selected": [{"chunk_id": "x"}]}]}

    redacted = redact_trace(trace, store_query_text=False)

    assert "SlipEstimator" not in repr(redacted)
    assert redacted["rounds"][0]["queries"][0]["chars"] == len(question)
    assert redact_trace(trace, store_query_text=True) == trace
    assert trace["rounds"][0]["queries"] == [question]  # the input is never mutated


# -- regressions found with a live model ---------------------------------------------------------
def test_citation_ids_are_normalised_but_never_invented() -> None:
    from app.retrieval.answer import normalize_citation_ids

    uid = "e312b230-f430-482d-ace5-e8faadb4c771"
    assert normalize_citation_ids([uid, f"[chunk:{uid.upper()}]", f"chunk:{uid}"]) == [
        f"chunk:{uid}"
    ]
    assert normalize_citation_ids(["no id here"]) == [
        "no id here"
    ]  # still rejected later


def test_a_paraphrased_table_row_claim_is_supported_by_its_row() -> None:
    row = "| DID | Name | Length |\n| --- | --- | --- |\n| 0xF190 | VehicleIdentificationNumber | 17 |"
    check = verify_claim(
        "DID 0xF190 corresponds to VehicleIdentificationNumber.", [row]
    )
    assert check.supported
    # swapping a value is still caught: 0xF18C is not in that row
    assert not verify_claim(
        "DID 0xF18C corresponds to VehicleIdentificationNumber.", [row]
    ).supported
