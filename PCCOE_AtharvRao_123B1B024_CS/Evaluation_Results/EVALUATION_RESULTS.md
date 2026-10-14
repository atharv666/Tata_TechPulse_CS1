# Evaluation Results

**Run date:** 14 October 2026 · **Data:** synthetic fixtures in `../Input_Data/` only · **Code:** the `Code/` snapshot in this package

This file replaces the earlier `BENCHMARK_RESULT.md`. The earlier "9/9" harness built part of its evidence in memory, so it
could not show retrieval or answer quality; it has been removed from the code base. The results below come from the real
pipeline (real PostgreSQL, real parser, real retrieval, and — for the live run — the real Gemini and Groq models).

## 1. Retrieval and answer evaluation (`scripts/evaluate_rag.py`)

* **Question set:** `../Input_Data/ABS_evaluation_questions.json` — 23 questions on the synthetic ABS HLD
  (19 answerable across components, aliases, interfaces, dependencies, ports, identifiers, timing, diagnostics and section
  hierarchy; 4 unanswerable). Each answerable question lists the section that must be retrieved and terms that must appear.
* **Method:** the script creates a throw-away PostgreSQL database, ingests the HLD through the real ingestion path, answers
  every question through the real answer service, and drops the database. It never touches project data.
* **Two runs:** *offline* (deterministic hashed embeddings and an extractive stand-in for the LLM: validates the pipeline and
  the lexical channel) and *live* (`--live`: `gemini-embedding-2` embeddings and `openai/gpt-oss-120b` answers).

| Metric | Offline | Live | What it means |
| --- | ---: | ---: | --- |
| Recall@8 (expected section retrieved) | 94.7 % | **100.0 %** | The section containing the answer was among the 8 passages used |
| MRR | 0.895 | **0.974** | Average of 1 / rank of the first expected section |
| Context recall (incl. parent / neighbour context) | 94.7 % | 100.0 % | Expected section present in the context given to the model |
| Evidence terms present in context | 94.7 % | 100.0 % | The needed words/values were in the context |
| Answer terms present in answer | 79.0 % | 89.5 % | Lexical check of the generated answer (a proxy, not factual correctness) |
| Citation validity | 100.0 % | **100.0 %** | Every citation in every answer points at a passage that was actually retrieved |
| Refusal accuracy on unanswerable questions | 100.0 % | **100.0 %** | 4 / 4 unanswerable questions were refused |
| False refusals on answerable questions | 5.3 % (1 / 19) | **10.5 % (2 / 19)** | Answerable question answered with "insufficient evidence" |
| Dropped (unsupported) claims | 0.0 % | 13.6 % | Generated statements removed because the cited text did not support them |
| Latency, mean / p95 | 0.22 s / 0.50 s | 13.7 s / 26.4 s | Whole answer including retrieval rounds and model calls |

Raw outputs: `raw/retrieval_eval_offline.json|md`, `raw/retrieval_eval_live.json|md`.

### What the failures were

* **Live, abs-05 *"What does ABSCtrl do?"* (alias question) and abs-19 *"In which section are the timing requirements
  described?"* were refused although the right section was retrieved (rank 1).** The model produced a statement, claim
  verification could not support it from the cited text (an alias-only paraphrase; a statement about *where* something is
  described rather than what the text says), and the answer was withdrawn after two rounds. This is the intended
  conservative behaviour, and it costs recall: 2 of 19 answerable questions. A larger labelled set is needed to tune
  `RAG_CLAIM_SUPPORT_THRESHOLD` and the answer prompt.
* **Offline, abs-19** is the same hierarchy question; the extractive stand-in has no way to answer "where".
* No unanswerable question was answered in either run (no hallucinated answers in this set).

### Limits of these numbers

23 questions on one short synthetic document (about 2 KB of text), written by the student and not independently reviewed. They show that the
pipeline works end to end and where it is conservative; they are **not** an accuracy estimate for real HLDs, multi-hundred-page
PDFs, scanned documents (OCR was not run) or other embedding/LLM models. "Answer terms present" is a word-overlap proxy.
Latency depends on the hosted providers at the time of the run.

## 2. End-to-end run in the application (evidence project)

A fresh database was migrated to head (`20261012_0012`) and used through the real UI, API and worker with the live
providers. Inputs: `BrakeController_HLD_v1.md`, `ABS_Subsystem_HLD.md`, then `BrakeController_HLD_v2.md` (same file name →
version 2). Screenshots: `Screenshots/`, database state: `Screenshots/psql/`.

| Measure | Result |
| --- | --- |
| Documents / versions / sections / chunks | 2 / 3 / 20 / 19 (all 19 chunks embedded, `vector(768)`, model `gemini-embedding-2`) |
| Jobs | 17 completed, none failed: 5 pipeline stages for each of the 3 uploads plus 2 revision comparisons. Live extraction took 31–75 s per document; the other stages 0.0–13 s |
| Entities | 41 rows → 35 live (5 rule-based merges of `COMPONENT` / `SOFTWARE_COMPONENT` variants, 1 correction superseding its original) |
| Relationships | 24 live, **each with at least one evidence row** (27 evidence rows); 22 `PENDING`, 2 `HUMAN_VERIFIED` after review |
| Review actions made through the UI | 2 verified, 1 rejected (with reason), 1 corrected (original kept, superseded); all recorded in `validation_events` |
| Findings | 3 potential inconsistencies (1 missing provider, 2 relationship-type), all `OPEN` |
| Revision comparison v1 → v2 | 90 findings: 56 removed, 18 added, 10 modified, 4 target changed, 2 renamed (including the possible rename `BrakeCommandInterface` → `BrakeCommandInterface_v2`) |
| Impact analysis `WheelSpeedInterface`, 2 hops | 4 direct and 7 indirect potentially affected elements, each with the connecting facts |

Manual review of the answers given in the UI is in `EVALUATION_LOG.md` and `GROUND_TRUTH_AND_REVIEW_PROTOCOL.md`.
Entity and relationship *extraction quality* (precision/recall against a labelled graph) has **not** been measured; the
extracted facts are candidates for human review, not validated results.

## 3. Automated tests and static checks (run 14 October 2026)

| Check | Result |
| --- | --- |
| Backend `pytest` (PostgreSQL integration tests use a throw-away database) | 392 tests collected; all passed except 1 live-provider test that is skipped unless explicitly enabled |
| `ruff format --check` / `ruff check` (backend, worker, tests, scripts) | clean |
| `mypy` (strict, `backend/app`, 113 files) | no issues |
| Frontend `tsc`, `eslint --max-warnings 0` | clean |
| Frontend `vitest` | 29 tests passed (4 files) |
| Frontend production build (`vite build`) | succeeded |
| Migration check | empty database migrates to head; a drift test compares models and migrations |

(The last complete `pytest` run had 389 tests and exit code 0 with one skipped test. Three tests for the secret scanner were
added afterwards and passed when run separately, giving 392 collected tests.)
