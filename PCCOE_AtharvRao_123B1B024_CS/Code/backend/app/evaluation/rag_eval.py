"""Evaluate retrieval-augmented answering against a labelled question set.

What is measured (and why each number can be trusted or not):

* ``recall_at_k``      - an expected section is among the retrieved passages. Pure retrieval metric.
* ``mrr``              - reciprocal rank of the first expected section (retrieval ordering quality).
* ``context_recall``   - an expected section is anywhere in the assembled context (hits + parents).
* ``evidence_terms``   - expected terms occur in the assembled context (can the answer be written?).
* ``answer_terms``     - expected terms occur in the *answer*; only meaningful with a real LLM.
* ``citation_validity``- every citation points at a stored chunk and quotes it exactly.
* ``refusal_accuracy`` - questions the documents cannot answer return "insufficient evidence".
* ``false_refusal``    - answerable questions that were refused (the cost of strictness).

An offline run (hashed embeddings, extractive answers) checks the plumbing and the lexical channel;
semantic quality requires ``--live`` with the real embedding model.
"""

from __future__ import annotations

import json
import statistics
import time
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.schema import Chunk
from app.retrieval.answer import RagOutcome


@dataclass(frozen=True)
class EvalQuestion:
    id: str
    question: str
    answerable: bool = True
    expected_sections: tuple[str, ...] = ()
    expected_terms: tuple[str, ...] = ()
    category: str = "general"


@dataclass
class QuestionResult:
    id: str
    category: str
    answerable: bool
    refused: bool
    first_expected_rank: int | None
    in_context: bool
    evidence_terms_found: bool
    answer_terms_found: bool
    citations_valid: bool
    claims: int
    dropped_claims: int
    latency_ms: float
    rounds: int
    selected_paths: list[str] = field(default_factory=list)


def load_questions(path: Path) -> tuple[dict[str, Any], list[EvalQuestion]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    questions = [
        EvalQuestion(
            id=item["id"],
            question=item["question"],
            answerable=item.get("answerable", True),
            expected_sections=tuple(item.get("expected_sections", ())),
            expected_terms=tuple(item.get("expected_terms", ())),
            category=item.get("category", "general"),
        )
        for item in data["questions"]
    ]
    return data, questions


def _rank_of_expected(paths: list[str], expected: tuple[str, ...]) -> int | None:
    for index, path in enumerate(paths, start=1):
        if any(path.endswith(suffix) for suffix in expected):
            return index
    return None


def _citations_valid(session: Session, outcome: RagOutcome) -> bool:
    answer = outcome.answer
    cited = {citation.citation_id: citation for citation in answer.citations}
    for claim in answer.claims:
        if not claim.citation_ids or any(cid not in cited for cid in claim.citation_ids):
            return False
    for citation in answer.citations:
        content = session.scalar(select(Chunk.content).where(Chunk.id == citation.chunk_id))
        if content is None or citation.excerpt not in content:
            return False
    return True


async def evaluate(
    session: Session,
    questions: list[EvalQuestion],
    ask: Callable[[str], Awaitable[RagOutcome]],
    top_k: int,
) -> tuple[list[QuestionResult], dict[str, Any]]:
    results: list[QuestionResult] = []
    for item in questions:
        started = time.perf_counter()
        outcome = await ask(item.question)
        elapsed = (time.perf_counter() - started) * 1000
        rounds = outcome.trace.get("rounds", [])
        selected_paths = [
            entry["section_path"] for entry in (rounds[-1]["selected"] if rounds else [])
        ]
        context_text = " ".join(block.text for block in outcome.blocks).lower()
        answer_text = " ".join(claim.text for claim in outcome.answer.claims).lower()
        context_paths = [block.section_path for block in outcome.blocks]
        results.append(
            QuestionResult(
                id=item.id,
                category=item.category,
                answerable=item.answerable,
                refused=outcome.answer.insufficient_evidence,
                first_expected_rank=_rank_of_expected(selected_paths, item.expected_sections),
                in_context=_rank_of_expected(context_paths, item.expected_sections) is not None,
                evidence_terms_found=all(t.lower() in context_text for t in item.expected_terms),
                answer_terms_found=all(t.lower() in answer_text for t in item.expected_terms),
                citations_valid=_citations_valid(session, outcome),
                claims=len(outcome.answer.claims),
                dropped_claims=outcome.answer.dropped_claims,
                latency_ms=round(elapsed, 1),
                rounds=len(rounds),
                selected_paths=selected_paths[:top_k],
            )
        )
    return results, summarize(results, top_k)


def _ratio(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 4) if denominator else None


def summarize(results: list[QuestionResult], top_k: int) -> dict[str, Any]:
    answerable = [r for r in results if r.answerable]
    unanswerable = [r for r in results if not r.answerable]
    ranked = [r.first_expected_rank for r in answerable]
    answered = [r for r in results if not r.refused]
    latencies = sorted(r.latency_ms for r in results)
    claims = sum(r.claims for r in results)
    dropped = sum(r.dropped_claims for r in results)
    return {
        "questions": len(results),
        "answerable": len(answerable),
        "unanswerable": len(unanswerable),
        "top_k": top_k,
        "recall_at_k": _ratio(
            sum(1 for r in ranked if r is not None and r <= top_k), len(answerable)
        ),
        "mrr": round(sum(1 / r for r in ranked if r) / len(answerable), 4) if answerable else None,
        "context_recall": _ratio(sum(1 for r in answerable if r.in_context), len(answerable)),
        "evidence_terms": _ratio(
            sum(1 for r in answerable if r.evidence_terms_found), len(answerable)
        ),
        "answer_terms": _ratio(sum(1 for r in answerable if r.answer_terms_found), len(answerable)),
        "citation_validity": _ratio(sum(1 for r in answered if r.citations_valid), len(answered)),
        "refusal_accuracy": _ratio(sum(1 for r in unanswerable if r.refused), len(unanswerable)),
        "false_refusal": _ratio(sum(1 for r in answerable if r.refused), len(answerable)),
        "dropped_claim_rate": _ratio(dropped, claims + dropped),
        "latency_ms_mean": round(statistics.fmean(latencies), 1) if latencies else None,
        "latency_ms_p95": latencies[int(0.95 * (len(latencies) - 1))] if latencies else None,
    }


def render_markdown(title: str, summary: dict[str, Any], results: list[QuestionResult]) -> str:
    def pct(value: float | None) -> str:
        return "n/a" if value is None else f"{value * 100:.1f}%"

    lines = [
        f"# RAG evaluation: {title}",
        "",
        f"Questions: {summary['questions']} ({summary['answerable']} answerable, "
        f"{summary['unanswerable']} unanswerable), top-k = {summary['top_k']}",
        "",
        "| Metric | Value |",
        "| --- | ---: |",
        f"| Recall@k (expected section retrieved) | {pct(summary['recall_at_k'])} |",
        f"| MRR | {summary['mrr']} |",
        f"| Context recall (incl. parent/neighbour context) | {pct(summary['context_recall'])} |",
        f"| Evidence terms present in context | {pct(summary['evidence_terms'])} |",
        f"| Answer terms present in answer (needs a real LLM) | {pct(summary['answer_terms'])} |",
        f"| Citation validity | {pct(summary['citation_validity'])} |",
        f"| Refusal accuracy on unanswerable questions | {pct(summary['refusal_accuracy'])} |",
        f"| False refusals on answerable questions | {pct(summary['false_refusal'])} |",
        f"| Dropped (unsupported) claim rate | {pct(summary['dropped_claim_rate'])} |",
        f"| Latency mean / p95 (ms) | {summary['latency_ms_mean']} / {summary['latency_ms_p95']} |",
        "",
        "| Id | Category | Rank | Refused | Context | Evidence terms | Citations valid |",
        "| --- | --- | ---: | :---: | :---: | :---: | :---: |",
    ]
    for r in results:
        lines.append(
            f"| {r.id} | {r.category} | {r.first_expected_rank or '-'} | "
            f"{'yes' if r.refused else 'no'} | {'yes' if r.in_context else 'no'} | "
            f"{'yes' if r.evidence_terms_found else 'no'} | "
            f"{'yes' if r.citations_valid else 'no'} |"
        )
    return "\n".join(lines) + "\n"


def results_as_json(summary: dict[str, Any], results: list[QuestionResult]) -> str:
    return json.dumps(
        {"summary": summary, "results": [asdict(r) for r in results]}, indent=2, default=str
    )


def _unused(_: UUID) -> None:  # pragma: no cover - keeps UUID imported for type consumers
    return None
