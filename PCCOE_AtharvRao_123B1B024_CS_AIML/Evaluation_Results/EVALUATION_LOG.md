# Evaluation Log Template

| ID | Test question / workflow | Expected evidence | Actual result | Status | Screenshot / command output |
| --- | --- | --- | --- | --- | --- |
| E1 | Ingest BrakeController HLD | Completed job, document version, chunks | _To be recorded_ | _To be recorded_ | _Filename_ |
| E2 | Which component uses WheelSpeedInterface? | Evidence-grounded answer with citations | _To be recorded_ | _To be recorded_ | _Filename_ |
| E3 | What is affected if WheelSpeedInterface changes? | Bounded graph paths and impact labels | _To be recorded_ | _To be recorded_ | _Filename_ |
| E4 | Verify or correct an extracted fact | Candidate retained; audit event recorded | _To be recorded_ | _To be recorded_ | _Filename_ |
| E5 | Compare HLD v1 and v2 | Findings retain old/new evidence; no automatic contradiction | _To be recorded_ | _To be recorded_ | _Filename_ |
| E6 | Deterministic synthetic benchmark | Nine fixture-based checks, including insufficient-evidence handling | 9/9 passed; harness pass rate 100.0%; constructed-fixture citation coverage 100.0% | Passed | `BENCHMARK_RESULT.md` |
| E7 | Provenance, graph build, impact, review, and revision tests | Candidate/evidence persistence, review history, bounded impact, revision behavior | 28 focused automated tests passed | Passed | `BENCHMARK_RESULT.md` |

## Metrics to report only after measurement

- Citation coverage: cited material claims / material claims.
- Grounded-answer pass rate: answers passing claim/citation validation / evaluated answers.
- Retrieval relevance: relevant retrieved chunks / evaluated retrieved chunks.
- Extraction precision and recall: compare extracted facts against a manually reviewed synthetic ground-truth set.
- Human-review correction rate: corrected facts / reviewed facts.

Record the ground-truth set, review criteria, exact model configuration, and date alongside any reported percentage.

The 100.0% result recorded above is a deterministic synthetic-harness pass rate. It is **not** a claim of 100% accuracy for live LLM extraction, arbitrary AUTOSAR documents, or production retrieval. Complete E1–E5 with screenshots and manually reviewed expected evidence before reporting any end-to-end accuracy percentage.
