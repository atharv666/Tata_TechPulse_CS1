"""Retrieval-augmented answering against a real database, over nested documents.

Each test states a property of the design (lexical + dense channels, small-to-big context, relevance
gating, verification, isolation) and demonstrates it on the synthetic ABS HLD, whose structure is:

    ABS Subsystem High-Level Design
    ├─ 1 Overview              (lead text defines the alias ABSCtrl and the ECU)
    │  ├─ 1.1 Components
    │  └─ 1.2 Interfaces
    ├─ 2 Dependencies
    └─ 3 Timing and Diagnostics
       ├─ 3.1 Timing
       └─ 3.2 Diagnostics      (DID table)
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from uuid import UUID

import pytest
from app.core.config import get_settings
from app.db.session import get_session_factory
from app.models.schema import Chunk, DocumentVersion
from app.retrieval.answer import RagPipeline
from app.retrieval.vector import EmbeddingService
from sqlalchemy import select

from tests.support.fakes import ScriptedLLM, installed_fakes
from tests.support.pipeline import V1, V2, create_project, drain, real_runner, upload

pytestmark = pytest.mark.integration

ABS = (
    Path(__file__).resolve().parents[1]
    / "sample_data"
    / "hld"
    / "03_ABS_Subsystem_HLD.md"
)


def ingest(access, *documents: tuple[str, bytes]) -> None:
    for name, content in documents:
        upload(access, name, content)
    drain(real_runner())


def ask(
    access,
    question: str,
    llm: ScriptedLLM | None = None,
    mode: str = "SOURCE",
    **overrides,
):
    """Run the real RAG pipeline for one question; returns (outcome, llm).

    Passage retrieval is what most tests here are about, so the default is ``SOURCE`` mode;
    graph behaviour is covered in ``test_graph_answers.py`` and in the tests that pass ``mode``.
    """
    llm = llm or ScriptedLLM()
    version_ids = overrides.pop("version_ids", None)
    settings = get_settings().model_copy(update=overrides)
    with installed_fakes(llm=llm) as (_llm, _embedders):
        from app.providers.factory import create_embedding_provider

        embeddings = EmbeddingService(
            create_embedding_provider(settings.embedding_settings()),
            settings.embedding_settings(),
        )
        with get_session_factory()() as session:
            pipeline = RagPipeline(
                session, access.project_id, embeddings, llm, settings
            )
            outcome = asyncio.run(
                pipeline.answer(question, document_version_ids=version_ids, mode=mode)
            )
    return outcome, llm


@pytest.fixture
def abs_project(clean_database):
    access = create_project("abs")
    with installed_fakes():
        ingest(access, ("ABS_HLD.md", ABS.read_bytes()))
    return access


def roles(outcome) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for block in outcome.blocks:
        result.setdefault(block.role, []).append(block.section_path)
    return result


# ---- lexical channel ------------------------------------------------------------------------
def test_exact_identifier_is_found_by_the_lexical_channel_alone(abs_project) -> None:
    """With the dense channel disabled, the identifier still retrieves its section."""
    outcome, _ = ask(abs_project, "P_WheelSpeed_In", rag_min_dense_similarity=2.0)

    selected = outcome.trace["rounds"][0]["selected"]
    assert selected and all(
        item["dense_similarity"] is None or item["dense_similarity"] < 2
        for item in selected
    )
    assert any("2 Dependencies" in item["section_path"] for item in selected)
    assert all(item["lexical_rank"] is not None for item in selected)
    assert outcome.answer.insufficient_evidence is False


def test_hex_identifier_in_a_table_is_retrieved_with_its_table_rows(
    abs_project,
) -> None:
    outcome, _ = ask(abs_project, "Which DID is 0xF190?", rag_min_dense_similarity=2.0)

    hits = [b for b in outcome.blocks if b.role == "HIT"]
    assert hits and "| 0xF190 | VehicleIdentificationNumber | 17 |" in hits[0].text
    assert hits[0].section_path.endswith(
        "3.2 Diagnostics"
    )  # table rows keep their section


# ---- small-to-big context --------------------------------------------------------------------
def test_hit_in_a_nested_section_gets_the_parents_lead_text_as_context(
    abs_project,
) -> None:
    outcome, _ = ask(
        abs_project, "What does SlipEstimator compute?", rag_min_dense_similarity=2.0
    )

    by_role = roles(outcome)
    assert any(path.endswith("1.1 Components") for path in by_role["HIT"])
    parent_blocks = [b for b in outcome.blocks if b.role == "PARENT_LEAD"]
    assert parent_blocks, "the parent section's lead text must be attached"
    assert parent_blocks[0].section_path.endswith("1 Overview")
    assert "ABSCtrl" in parent_blocks[0].text  # the alias is defined only in the parent
    assert outcome.blocks.index(parent_blocks[0]) < outcome.blocks.index(
        next(b for b in outcome.blocks if b.role == "HIT")
    )  # document order: parent text first


def test_parent_context_is_a_capped_slice_not_the_whole_subtree(abs_project) -> None:
    outcome, _ = ask(
        abs_project,
        "What does SlipEstimator compute?",
        rag_min_dense_similarity=2.0,
        rag_parent_lead_tokens=12,
    )
    lead = next(b for b in outcome.blocks if b.role == "PARENT_LEAD")
    assert lead.truncated and lead.tokens <= 24
    paths = {b.section_path for b in outcome.blocks}
    assert not any(
        path.endswith("3.2 Diagnostics") for path in paths
    )  # unrelated sections absent


def test_parent_context_can_be_switched_off(abs_project) -> None:
    outcome, _ = ask(
        abs_project,
        "What does SlipEstimator compute?",
        rag_min_dense_similarity=2.0,
        rag_parent_lead_tokens=0,
    )
    assert "PARENT_LEAD" not in roles(outcome)


def test_alias_defined_in_a_parent_is_reachable_through_the_lexical_hit(
    abs_project,
) -> None:
    outcome, _ = ask(abs_project, "What is ABSCtrl?", rag_min_dense_similarity=2.0)

    assert any("ABSCtrl" in b.text for b in outcome.blocks if b.role == "HIT")
    assert outcome.answer.insufficient_evidence is False
    assert any(c.section_path.endswith("1 Overview") for c in outcome.answer.citations)


# ---- relevance gate -------------------------------------------------------------------------
def test_unrelated_question_is_answered_with_insufficient_evidence(abs_project) -> None:
    llm = ScriptedLLM()
    outcome, _ = ask(abs_project, "Why is the sky blue?", llm)

    assert outcome.answer.insufficient_evidence is True
    assert outcome.answer.status == "INSUFFICIENT_EVIDENCE"
    assert outcome.answer.claims == [] and outcome.answer.citations == []
    assert outcome.blocks == []
    assert outcome.trace["rounds"][0]["decision"] == "no_relevant_evidence"
    # no answer was drafted from irrelevant text (only an optional rephrasing was attempted)
    assert all(
        "Question:" not in r.messages[1].content
        for r in llm.requests
        if len(r.messages) > 2
    )


def test_bounded_rounds_stop_when_rephrasing_yields_nothing_new(abs_project) -> None:
    llm = ScriptedLLM()
    llm.rewrites = []
    outcome, _ = ask(abs_project, "Why is the sky blue?", llm, rag_max_rounds=4)
    assert (
        len(outcome.trace["rounds"]) == 1
    )  # no rephrasing available: stop immediately


def test_second_round_with_rephrased_queries_can_rescue_a_question(abs_project) -> None:
    llm = ScriptedLLM()
    llm.rewrites = [
        "P_ValveCmd_Out"
    ]  # the model proposes the identifier the question implies
    outcome, _ = ask(
        abs_project,
        "Who talks to the pumps?",
        llm,
        rag_min_dense_similarity=2.0,
        rag_max_rounds=2,
    )

    rounds = outcome.trace["rounds"]
    assert len(rounds) == 2 and rounds[0]["decision"] == "no_relevant_evidence"
    assert (
        rounds[1]["queries"][1] == "P_ValveCmd_Out"
        and rounds[1]["decision"] == "answered"
    )
    assert any("P_ValveCmd_Out" in b.text for b in outcome.blocks)
    assert "second retrieval round" in " ".join(outcome.answer.limitations)


# ---- verification ---------------------------------------------------------------------------
def test_hallucinated_claims_are_removed_and_never_reach_the_answer(
    abs_project,
) -> None:
    llm = ScriptedLLM()
    llm.draft_override = {
        "summary": "x",
        "claims": [
            {
                "text": "AbsController REQUIRES TorqueVectoringInterface",
                "citation_ids": ["chunk:nonexistent"],
            },
        ],
        "insufficient_evidence": False,
    }
    outcome, _ = ask(
        abs_project,
        "What does AbsController require?",
        llm,
        rag_min_dense_similarity=2.0,
    )

    assert outcome.answer.insufficient_evidence is True
    assert outcome.answer.dropped_claims == 1


def test_with_the_graph_a_hallucinated_claim_is_dropped_but_the_true_fact_answers(
    abs_project,
) -> None:
    llm = ScriptedLLM()
    llm.draft_override = {
        "summary": "x",
        "claims": [
            {
                "text": "AbsController REQUIRES TorqueVectoringInterface",
                "citation_ids": ["chunk:nonexistent"],
            },
        ],
        "insufficient_evidence": False,
    }
    outcome, _ = ask(
        abs_project,
        "What does AbsController require?",
        llm,
        mode="HYBRID",
        rag_min_dense_similarity=2.0,
    )

    answer = outcome.answer
    assert answer.dropped_claims == 1
    assert [c.text for c in answer.claims] == [
        "AbsController REQUIRES WheelSpeedInterface"
    ]
    assert "TorqueVectoringInterface" not in answer.model_dump_json()
    assert answer.mode == "HYBRID" and answer.graph_facts


def test_a_claim_citing_real_text_but_stating_something_else_is_dropped(
    abs_project,
) -> None:
    llm = ScriptedLLM()
    # find a real chunk id first, then cite it for a statement it does not contain
    first, _ = ask(
        abs_project, "What does AbsController require?", rag_min_dense_similarity=2.0
    )
    cited = next(
        c.citation_id for c in first.answer.citations if "REQUIRES" in c.excerpt
    )
    llm.draft_override = {
        "summary": "x",
        "claims": [
            {
                "text": "AbsController PROVIDES WheelSpeedInterface",
                "citation_ids": [cited],
            },
            {
                "text": "AbsController requires WheelSpeedInterface",
                "citation_ids": [cited],
            },
        ],
    }
    outcome, _ = ask(
        abs_project,
        "What does AbsController require?",
        llm,
        rag_min_dense_similarity=2.0,
    )

    assert [c.text for c in outcome.answer.claims] == [
        "AbsController requires WheelSpeedInterface"
    ]
    assert outcome.answer.dropped_claims == 1
    assert any("removed" in item for item in outcome.answer.limitations)


def test_answer_exposes_confidence_with_its_basis_and_cited_context_roles(
    abs_project,
) -> None:
    outcome, _ = ask(
        abs_project, "What does SlipEstimator compute?", rag_min_dense_similarity=2.0
    )
    answer = outcome.answer

    assert answer.status == "GROUNDED" and 0 < (answer.confidence or 0) <= 1
    assert (
        "grounding indicator" in answer.confidence_basis
    )  # a number never appears without its meaning
    assert answer.limitations
    citation = answer.citations[0]
    assert citation.section_path and citation.role in {"HIT", "PARENT_LEAD", "NEIGHBOR"}


def test_retrieval_trace_records_scores_but_no_document_text(abs_project) -> None:
    outcome, _ = ask(
        abs_project, "What does SlipEstimator compute?", rag_min_dense_similarity=2.0
    )

    flat = repr(outcome.trace)
    assert (
        "slip ratio of each wheel" not in flat
    )  # ids, ranks, scores only; text stays in the DB
    first = outcome.trace["rounds"][0]
    assert {"fused_score", "matched_ratio", "relevant"} <= set(first["selected"][0])
    from app.retrieval.answer import redact_trace

    assert "SlipEstimator" not in repr(
        redact_trace(outcome.trace, store_query_text=False)
    )


# ---- isolation and filters ------------------------------------------------------------------
def test_chunks_of_another_project_are_never_retrieved(clean_database) -> None:
    mine = create_project("mine", user="alice")
    theirs = create_project("theirs", user="bob")
    with installed_fakes():
        ingest(mine, ("ABS_HLD.md", ABS.read_bytes()))
        ingest(theirs, ("ABS_HLD.md", ABS.read_bytes()))
    with get_session_factory()() as session:
        foreign = set(
            session.scalars(
                select(Chunk.id).where(Chunk.project_id == theirs.project_id)
            )
        )

    outcome, _ = ask(mine, "P_WheelSpeed_In", rag_min_dense_similarity=2.0)

    ids = {b.chunk_id for b in outcome.blocks}
    assert ids and not ids & foreign


def test_version_filter_restricts_retrieval_to_one_revision(clean_database) -> None:
    access = create_project("versions")
    with installed_fakes():
        ingest(access, ("HLD.md", V1.read_bytes()), ("HLD.md", V2.read_bytes()))
    with get_session_factory()() as session:
        versions = {
            v.version_number: v.id for v in session.scalars(select(DocumentVersion))
        }
    llm = ScriptedLLM()
    settings = get_settings().model_copy(update={"rag_min_dense_similarity": 2.0})
    with installed_fakes(llm=llm):
        from app.providers.factory import create_embedding_provider

        embeddings = EmbeddingService(
            create_embedding_provider(settings.embedding_settings()),
            settings.embedding_settings(),
        )
        with get_session_factory()() as session:
            pipeline = RagPipeline(
                session, access.project_id, embeddings, llm, settings
            )
            only_v2 = asyncio.run(
                pipeline.answer(
                    "BrakeCommandInterface_v2", document_version_ids=[versions[2]]
                )
            )
            only_v1 = asyncio.run(
                pipeline.answer(
                    "BrakeCommandInterface_v2", document_version_ids=[versions[1]]
                )
            )

    assert only_v2.blocks and all(
        b.document_version_id == versions[2] for b in only_v2.blocks
    )
    assert only_v1.answer.insufficient_evidence  # v1 never mentions the v2 interface


def test_hierarchical_context_never_crosses_documents_or_projects(abs_project) -> None:
    outcome, _ = ask(
        abs_project, "What does SlipEstimator compute?", rag_min_dense_similarity=2.0
    )
    assert {b.document_name for b in outcome.blocks} == {"ABS_HLD.md"}
    assert {b.chunk_id for b in outcome.blocks} <= {
        c for c in _all_chunk_ids(abs_project.project_id)
    }


def _all_chunk_ids(project_id: UUID) -> set[UUID]:
    with get_session_factory()() as session:
        return set(
            session.scalars(select(Chunk.id).where(Chunk.project_id == project_id))
        )
