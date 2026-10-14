"""The evaluation harness: metric arithmetic and an offline end-to-end regression run."""

from __future__ import annotations

from pathlib import Path

import pytest
from app.core.config import get_settings
from app.evaluation.offline import ExtractiveLLM, HashedEmbedder
from app.evaluation.rag_eval import (
    QuestionResult,
    load_questions,
    render_markdown,
    summarize,
)
from app.evaluation.runner import run_evaluation
from app.providers.fake import register_fake_embedding, register_fake_llm

ROOT = Path(__file__).resolve().parents[1]
QUESTIONS = ROOT / "sample_data" / "eval" / "abs_questions.json"
DOCUMENTS = ROOT / "sample_data" / "hld"


def result(**overrides) -> QuestionResult:
    base = dict(
        id="q",
        category="c",
        answerable=True,
        refused=False,
        first_expected_rank=1,
        in_context=True,
        evidence_terms_found=True,
        answer_terms_found=True,
        citations_valid=True,
        claims=1,
        dropped_claims=0,
        latency_ms=10.0,
        rounds=1,
    )
    base.update(overrides)
    return QuestionResult(**base)


def test_summary_metrics_arithmetic() -> None:
    results = [
        result(first_expected_rank=1),
        result(first_expected_rank=4),
        result(first_expected_rank=None, refused=True, in_context=False),
        result(answerable=False, refused=True, first_expected_rank=None),
        result(
            answerable=False, refused=False, first_expected_rank=None, dropped_claims=2
        ),
    ]

    summary = summarize(results, top_k=3)

    assert summary["answerable"] == 3 and summary["unanswerable"] == 2
    assert summary["recall_at_k"] == round(
        1 / 3, 4
    )  # rank 4 is outside top-3, None is a miss
    assert summary["mrr"] == round((1 + 1 / 4) / 3, 4)
    assert summary["refusal_accuracy"] == 0.5
    assert summary["false_refusal"] == round(1 / 3, 4)
    assert summary["dropped_claim_rate"] == round(
        2 / (5 + 2), 4
    )  # 5 kept claims, 2 dropped


def test_summary_handles_empty_denominators() -> None:
    summary = summarize(
        [result(answerable=False, refused=True, first_expected_rank=None)], 8
    )
    assert summary["recall_at_k"] is None and summary["mrr"] is None
    assert summary["refusal_accuracy"] == 1.0


def test_question_set_is_well_formed() -> None:
    spec, questions = load_questions(QUESTIONS)
    ids = [q.id for q in questions]
    assert len(ids) == len(set(ids)) >= 20
    assert any(not q.answerable for q in questions)
    assert all(q.expected_sections for q in questions if q.answerable)
    for name in spec["documents"]:
        assert (DOCUMENTS / name).exists()


def test_markdown_report_lists_every_question() -> None:
    results = [result(id="a"), result(id="b", refused=True)]
    report = render_markdown("t", summarize(results, 8), results)
    assert "| a |" in report and "| b |" in report and "Recall@k" in report


@pytest.mark.integration
def test_offline_run_meets_regression_thresholds(clean_database) -> None:
    """Pins the offline numbers so a retrieval regression fails the build.

    One answerable question (abs-19, a structural "which section" question) needs semantic retrieval
    and is expected to be missed offline; the thresholds leave room for exactly that.
    """
    settings = get_settings().model_copy(update={"rag_min_dense_similarity": 0.25})
    register_fake_llm(ExtractiveLLM)
    register_fake_embedding(HashedEmbedder)
    try:
        run = run_evaluation(QUESTIONS, DOCUMENTS, settings=settings, top_k=8)
    finally:
        register_fake_llm(None)
        register_fake_embedding(None)

    summary = run.summary
    assert summary["recall_at_k"] >= 0.9
    assert summary["mrr"] >= 0.85
    assert summary["context_recall"] >= 0.9
    assert (
        summary["citation_validity"] == 1.0
    )  # every citation quotes its stored chunk exactly
    assert (
        summary["refusal_accuracy"] == 1.0
    )  # nothing is invented for unanswerable questions
    assert summary["dropped_claim_rate"] == 0.0
    missed = [r.id for r in run.results if r.answerable and r.refused]
    assert set(missed) <= {"abs-19"}
    assert run.settings_snapshot["embedding_model"] == "fake-embedding"
