# Implementation Status

## Current state

A React/TypeScript workspace, FastAPI service, PostgreSQL + pgvector system of record and a PostgreSQL job
worker. The pipeline is explicit, durable and idempotent; **no automated stage assigns human verification**.

```text
upload -> DOCUMENT_INGESTION -> EMBEDDING -> GRAPH_EXTRACTION -> ENTITY_RESOLUTION -> GRAPH_BUILD
        (parse, structure,    (breadcrumb    (candidate entities,  (blocking, guards,    (bind relationships,
         chunk, OCR if needed) + content)     staged relationships) rules, LLM for        validate, confidence,
                                                                    ambiguous pairs)      findings)
questions -> hybrid retrieval (dense + lexical) + graph facts -> verified, cited answer
review / findings / comparison / impact / export
```

Design and decisions: `ARCHITECTURE_DECISION_RECORDS.md` (ADR-001…013), `RAG_DESIGN.md`.

## What changed in this phase (against the case-study audit)

| Audit finding | Resolution |
| --- | --- |
| Worker crashed on every upload; one transaction per document | Job runner: claim/lease, checkpoints, retries, partial failures, cancellation (ADR-001) |
| Embedding loop never terminated; migration failed on a fresh database | Fixed; migrations 0007–0012, drift test, hermetic throw-away test database (ADR-002) |
| Flat structure, headers/footers in text, naive chunks | Section tree, cleaning, structure-aware chunks, breadcrumb embedding (ADR-004) |
| Dense-only retrieval, ungrounded answers | Dense + lexical RRF, relevance gate, verified claims, bounded rounds (ADR-003) |
| No usable OCR | Provider boundary: local Tesseract or consent-gated Gemini vision, page cache (ADR-006) |
| Relationships depended on chunk order; entities only exactly matched | Staged relationships bound after resolution; blocking → guards → rules → LLM → constrained Union-Find, soft merges with undo (ADR-007, 008) |
| Confidence compounded on every build | `raw_confidence` + pure function (ADR-010) |
| Findings were an in-memory list | Persisted potential inconsistencies with dismissal that survives rebuilds (ADR-009) |
| Review: no validation, orphaned edges, 500 on collisions, UUID labels | Taxonomy/project validation, supersede + carried-over edges, 404/409, readable labels |
| Rejected / merged facts leaked into answers | All traversal and listings use live facts only |
| Planner direction hard-wired; Python traversal | Grammar-aware planner; PostgreSQL recursive CTE (ADR-011) |
| Impact missed PROVIDES; no flows/tests | Propagation rules as data incl. flows and tests (ADR-005) |
| Comparison missed relationship add/remove, created a stray job | Section/value diff, entity and relationship set-diff with evidence, impacts, one job, list/detail API |
| No document status / structured output | Declared status shown and optionally enforced (ADR-013); JSON/CSV/XLSX export, component report |
| Seed script wrote fabricated "verified" facts; circular benchmark | Seed queues real uploads; benchmark replaced by `evaluate_rag.py`; seed/build covered by tests |
| UI ignored the query mode, 50-item graph, UUID labels, no evidence | Rewritten screens against the new API (see README §6), paginated loading, colour + text status |

## Verification (run on this machine)

* Backend: ruff and strict mypy clean; full pytest suite passing (run `python -m pytest`; 392 tests, one
  skipped live-provider test). Integration tests run against a throw-away PostgreSQL database created
  and dropped per run, never the development database.
* Frontend: `tsc`, eslint (zero warnings), 29 Vitest tests, production build; the three.js graph screen is
  lazy-loaded.
* Retrieval evaluation (`scripts/evaluate_rag.py`, 23 questions on the synthetic ABS HLD). Offline (hashed
  embeddings, extractive stand-in): Recall@8 94.7 %, MRR 0.895, refusal accuracy 100 %. **Live** (Gemini embeddings +
  Groq gpt-oss-120b): Recall@8 100 %, MRR 0.974, citation validity 100 %, refusal accuracy 100 %, false refusals
  10.5 % (2 of 19: claim verification withdrew an alias answer and a "where is it described" answer), dropped
  claims 13.6 %, latency mean 13.7 s / p95 26.4 s. Small, student-labelled set: not an accuracy estimate.

## Live run (synthetic sample documents, configured Gemini embeddings + Groq LLM)

* A copy of the development database (at `20260909_0006`) upgraded cleanly to `20261012_0012`; an empty
  database also migrates to head.
* A fresh database processed all three sample HLDs through the real worker path: 36 entities and 24
  relationships, every relationship statement bound, nothing auto-verified, 3 findings, no provider errors.
* The real server answered 8 questions: exact-identifier, numeric, table and multi-hop questions grounded;
  out-of-domain and absent-fact questions refused.
* Two defects only a real model exposed were fixed (and covered by regression tests): models cite sources
  as bare UUIDs without `chunk:` (every such answer was dropped), and a correct paraphrase of a table row
  ("DID 0xF190 corresponds to ...") failed claim verification. The extraction prompt now states relationship
  direction conventions (it had produced reversed `CARRIES` edges and generic-phrase entities).
* Refusals take 20–30 s (two retrieval rounds plus a rephrase); answered questions take 3–12 s.
  `RAG_MIN_DENSE_SIMILARITY` (0.5) is loose for Gemini embeddings (unrelated text scores ≈0.5); tune it with
  `evaluate_rag.py --live`.
* The development database itself was **not** modified; it is still at `20260909_0006`.

## Evidence run through the real UI (14 October 2026)

A fresh database was filled through the Documents screen (v1 + ABS HLD, then v2 as version 2) and exercised through
the UI: 41 entity rows (35 live; 5 rule merges), 24 live relationships, each with evidence; review actions (2 verified,
1 rejected, 1 corrected); 3 findings; a 90-finding v1 → v2 comparison; impact analysis. Screenshots and `psql` views are
in the submission package (`Evaluation_Results/`). Two UI defects found while capturing were fixed: the 3D canvas was
sized to the window instead of its card (now follows the card, zooms to fit) and thin relationship lines were hard to
click (larger hover precision).

## Not verified / known limits

1. **Live OCR** (Gemini vision / Tesseract) has not been run. Use synthetic documents only, and rotate the exposed
   keys first. The live retrieval evaluation has been run once (see Verification).
2. The embedding model is configured as `gemini-embedding-2` (768 dimensions); confirm the intended model
   name and dimension before indexing a real project (changing it needs an explicit re-embed).
3. Entity-name embeddings are intentionally not used in resolution (ADR-007); quality on large real HLDs
   should be measured and the blocking/guard lists extended from observed false merges/misses.
4. The question planner is rule-based (grammar patterns for 14 relationship types); unusual phrasings fall
   back to the entity neighbourhood. An LLM planner could be added behind the same typed plan.
5. Revision conflict findings between versions of one entity (`REVISION_CONFLICT`) are covered by the
   comparison feature, not by a separate graph-build detector.
6. Docker Compose deployment is wired but has not been executed on this machine. Production identity
   (`AUTH_MODE=enterprise`) remains an integration boundary.

## Required actions for the repository owner

* Rotate the Groq/Gemini keys and the database password that were present in local `.env` files and in a
  committed archive; remove the archive (`peoject.zip`) from git history (needs a deliberate, coordinated
  history rewrite; nothing was rewritten or pushed by the assistant).
* Apply migrations to the development database (`alembic upgrade head`; it was at `20260909_0006`) and
  re-seed with `scripts/seed_demo_data.py --run-worker`.
* Install Tesseract if local OCR is wanted; keep `OCR_ALLOW_EXTERNAL=false` for confidential documents.
* Have an engineer review and label the evaluation questions in `sample_data/eval/abs_questions.json`.

## Decisions that still need a human

* Production identity provider, document storage/retention/malware scanning policy.
* Whether `REQUIRE_APPROVED_SOURCES` should be on for the target deployment.
* Approved embedding model and its dimension; whether hosted LLMs may be used for confidential content
  (default policy: development with synthetic data only, local/private inference as the target).
