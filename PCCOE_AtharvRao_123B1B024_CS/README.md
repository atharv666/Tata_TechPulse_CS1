# AUTOSAR Architecture Intelligence Assistant — Final Submission Package

**Student:** Atharv Rao | **PRN:** 123B1B024 | **Case Study:** CS1 (Tech Pulse FY-26) | **Package updated:** 14 October 2026

The system turns AUTOSAR High-Level Design documents into an evidence-linked, human-validated knowledge graph in PostgreSQL
(+ pgvector) and answers engineering questions with citations, confidence and validation status. The demonstration uses
synthetic HLD fixtures only.

## Folder map

| Folder | Content |
| --- | --- |
| `Synopsis/` | Completed synopsis (`.docx` + `.pdf`), updated to the current design and evaluation |
| `Input_Data/` | Synthetic BrakeController v1 / v2, ABS HLD and the 23-question evaluation set |
| `Code/` | Clean source snapshot: backend, worker, frontend, tests (392), scripts, migrations, specifications (`docs/`), Docker files; no secrets or caches |
| `Model_Prompts_Config/` | Providers, models, prompt version, retrieval/pipeline settings, guard-rails |
| `Evaluation_Results/` | Start with `EVALUATION_RESULTS.md`; log, ground truth, evidence index, 28 screenshots, 19 element crops, 16 PostgreSQL views, raw evaluation output |
| `Documentation/` | Technical report (`.docx` + `.pdf`), diagrams and figures, provenance/review description, run instructions, `SUBMISSION_AUDIT.md`, `Specifications/` |
| `Video/` | Demonstration script (the MP4 is recorded by the student) |
| `Declarations/` | Student declaration and faculty approval record (signatures by the people concerned) |
| `Project.zip` | The same package as one archive (scanned for secrets) |

## Where to look first

1. `Documentation/Technical_Report.pdf` — what was built, how it was evaluated, limitations.
2. `Evaluation_Results/EVALUATION_RESULTS.md` — measured results, including the failures.
3. `Evaluation_Results/Screenshots/` — the running application; `psql/` shows what is stored in PostgreSQL.
4. `Documentation/RUN_AND_DEPLOY.md` — how to run it (API, worker, frontend; `Code/README.md` has the same commands).

## External dependency declaration

The recorded configuration uses hosted Groq (`openai/gpt-oss-120b`) and Gemini (`gemini-embedding-2`, 768 D) APIs, always through
replaceable provider interfaces, and only with synthetic data. Credentials are not included. A local Ollama provider path exists
but was not used for the demonstration because the available hardware was not sufficient for a validated, responsive local run.

## Honest status

Verified on 14 October 2026: 392 backend tests (1 live test skipped), 29 frontend tests, ruff / strict mypy / eslint / tsc / build
clean, the packaged `Code/` folder passes its own tests, and a live retrieval evaluation (Recall@8 100 %, citation validity 100 %,
4 of 4 unanswerable questions refused, 10.5 % false refusals) on a small synthetic set. Not exercised: live OCR, Docker Compose,
real or scanned HLDs, extraction precision/recall. See `Documentation/SUBMISSION_AUDIT.md`.

## Actions remaining with the student

1. Faculty approval/signature on the synopsis; signatures and dates on the report, synopsis declaration and student declaration.
2. Record the 5–10 minute MP4 under `Video/`.
3. Confirm the AI-tool declaration in the report (Codex and Claude Code as coding assistants).
4. Rotate the exposed API keys and database password and remove the old archive from the git history before sharing the repository.
