# Submission Audit

**Audit date:** 14 October 2026
**Snapshot:** the `Code/` folder of this package (a clean copy of the repository made by `scripts/package_submission.py`)

## Requirements coverage

| Requirement | Submission location | Status |
| --- | --- | --- |
| Prescribed synopsis | `Synopsis/Project_Synopsis.docx` + PDF | Updated 14 Oct 2026; **faculty approval/signature still required**; the student's signature and the date on it (7 Oct 2026) are the student's to renew |
| Student declaration | `Declarations/STUDENT_DECLARATION.md` | Prepared; student signature and date required |
| Faculty approval record | `Declarations/FACULTY_APPROVAL_RECORD.md` | Prepared; faculty signature/seal required |
| Source code, tests, scripts, configuration | `Code/` | Current repository snapshot; no secrets, caches, uploads or archives |
| Approved / synthetic input data | `Input_Data/` | Synthetic BrakeController v1 and v2, ABS HLD, 23-question evaluation set |
| Model / provider / configuration declaration | `Model_Prompts_Config/` | Updated; hosted-API dependency declared |
| Evaluation evidence | `Evaluation_Results/` | Real retrieval evaluation (offline + live), end-to-end evidence, 28 application screenshots, 19 element crops, 16 PostgreSQL views, raw outputs |
| Technical report | `Documentation/Technical_Report.docx` + PDF | Updated 14 Oct 2026; **student signature/date (7 Oct 2026) to be renewed by the student** |
| Video evidence | `Video/` | Demonstration script updated; **the MP4 is still to be recorded by the student** |

## What changed since the 7 October package

* The code base was rebuilt in the areas the case study stresses: a durable job pipeline, structure-aware ingestion with OCR
  boundary, hybrid (dense + lexical) retrieval with claim verification, entity resolution with soft merges, persisted findings,
  PostgreSQL recursive-CTE traversal, impact analysis, revision comparison, structured export, a rewritten UI (upload queue,
  pipeline tracker, graph inspector, review, findings, comparison). The admin/telemetry screens were removed again.
* The earlier "9/9 synthetic benchmark" was **removed** (it built part of its evidence in memory) and replaced by
  `scripts/evaluate_rag.py`. All "9/9", "100% pass rate" and "28 focused tests" statements were removed from the package.
* Screenshots were recaptured from the running application and a database evidence set (`psql`) was added.

## Verification performed on 14 October 2026

| Check | Result |
| --- | --- |
| Backend tests, from the repository | 389 tests, exit 0, 1 skipped (live-provider test); +3 secret-scanner tests added afterwards and passed |
| Backend tests, run **from inside the packaged `Code/` folder** | 391 passed, 1 skipped (392 collected) |
| `ruff format --check` and `ruff check` (backend, worker, tests, scripts) | clean |
| `mypy` strict (`backend/app`, 113 files) | no issues |
| Frontend `tsc`, `eslint --max-warnings 0`, `vitest` (29 tests), `vite build` | all pass |
| Secret scan (`scripts/check_no_secrets.py --path Code`, and `--zip Project.zip`) | no secrets found; no `.env` in the package or the archive |
| Retrieval evaluation, live providers, 23 questions | Recall@8 100%, MRR 0.974, citation validity 100%, refusal accuracy 4/4, false refusals 10.5%, dropped claims 13.6% |

## Honest limitations

1. **Evaluation size.** 23 questions on one short synthetic document, written by the student and not independently reviewed. No
   extraction precision/recall against a labelled graph was measured. Do not quote a single accuracy percentage.
2. **Not exercised:** live OCR (Tesseract / Gemini vision), Docker Compose on this machine, large multi-hundred-page or scanned
   HLDs, local (Ollama) models, multi-user enterprise authentication (development identity only).
3. **Conservative answers.** Two answerable evaluation questions were refused because claim verification withdrew the model's
   statement; refusals and two-round answers take 20–30 s with the hosted providers.
4. **Extraction needs review.** The model proposes generic or duplicate entities (for example `ABS` and `ESP` as functions); this
   is the reason every fact stays `PENDING` until a person acts. The recorded run contains 2 verified relationships, 1 rejected
   entity and 1 correction made while testing; the remaining facts are unreviewed candidates.
5. **Hosted providers.** Groq and Gemini were used with synthetic data only. Confidential documents require local/private models
   and an approved policy.
6. **PostgreSQL images** under `Evaluation_Results/Screenshots/psql/` are renderings of real `psql` output, not terminal
   screenshots; this is stated in `EVIDENCE_INDEX.md`.

## Actions that remain with the student

* Re-sign and re-date the Technical Report and the synopsis declaration (the images in the documents still carry the signature
  and the 7 October 2026 date from the previous version).
* Obtain faculty approval/signature on the synopsis and the faculty record; sign `Declarations/STUDENT_DECLARATION.md`.
* Record the 5–10 minute MP4 (`Video/DEMONSTRATION_SCRIPT.md`) and save it under `Video/`.
* Confirm the AI-tool declaration (the report lists Claude Code in addition to Codex; the "verified by student" cell for it says
  *Student to confirm*).
* Before sharing the repository: rotate the Groq/Gemini keys and the database password that were in local `.env` files and in a
  committed archive, and remove `peoject.zip` from the git history (needs a deliberate history rewrite; nothing was rewritten
  or pushed during this work).
