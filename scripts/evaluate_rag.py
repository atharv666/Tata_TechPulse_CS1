"""Evaluate retrieval-augmented answering on a labelled question set.

Runs in a throwaway database (created and dropped automatically), so it never touches project data.

    python scripts/evaluate_rag.py                 # offline: hashed embeddings + extractive answers
    python scripts/evaluate_rag.py --live          # real providers from .env (needs rotated keys)
    python scripts/evaluate_rag.py --json out.json --markdown out.md

Offline numbers validate the pipeline and the lexical channel. They say nothing about the semantic
quality of the embedding model or the answer quality of the LLM: use ``--live`` for that and tune
``RAG_*`` settings against it.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument(
        "--questions", type=Path, default=ROOT / "sample_data/eval/abs_questions.json"
    )
    parser.add_argument("--documents", type=Path, default=ROOT / "sample_data/hld")
    parser.add_argument(
        "--live", action="store_true", help="use the providers configured in .env"
    )
    parser.add_argument("--top-k", type=int, default=8)
    parser.add_argument(
        "--min-dense", type=float, default=None, help="dense similarity gate"
    )
    parser.add_argument("--json", type=Path)
    parser.add_argument("--markdown", type=Path)
    parser.add_argument("--keep-db", action="store_true")
    args = parser.parse_args()

    if not args.live:
        os.environ.update(
            LLM_PROVIDER="fake",
            EMBEDDING_PROVIDER="fake",
            EMBEDDING_MODEL="fake-embedding",
            EMBEDDING_DIMENSIONS="768",
            OCR_PROVIDER="none",
            GROQ_API_KEY="",
            GEMINI_API_KEY="",
            LLM_API_KEY="",
            EMBEDDING_API_KEY="",
        )
        os.environ.setdefault("RAG_MIN_DENSE_SIMILARITY", "0.25")
    if args.min_dense is not None:
        os.environ["RAG_MIN_DENSE_SIMILARITY"] = str(args.min_dense)

    from app.core.config import Settings
    from app.evaluation.offline import ExtractiveLLM, HashedEmbedder
    from app.evaluation.rag_eval import render_markdown, results_as_json
    from app.evaluation.runner import run_evaluation
    from app.evaluation.sandbox import temporary_database
    from app.providers.fake import register_fake_embedding, register_fake_llm

    if not args.live:
        register_fake_llm(ExtractiveLLM)
        register_fake_embedding(HashedEmbedder)
    base_url = os.environ.get("DATABASE_URL") or Settings().database_url
    if not base_url:
        print("DATABASE_URL is required (only used to create a temporary database).")
        return 2
    with temporary_database(base_url, keep=args.keep_db):
        run = run_evaluation(args.questions, args.documents, top_k=args.top_k)
    report = render_markdown(
        f"{run.title} ({'live providers' if args.live else 'offline providers'})",
        run.summary,
        run.results,
    )
    print(report)
    if args.markdown:
        args.markdown.write_text(report, encoding="utf-8")
    if args.json:
        args.json.write_text(
            results_as_json(run.summary, run.results), encoding="utf-8"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
