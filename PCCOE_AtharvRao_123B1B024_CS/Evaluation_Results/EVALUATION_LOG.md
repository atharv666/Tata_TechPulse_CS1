# Evaluation Log

**Run date:** 14 October 2026 · **Environment:** local PostgreSQL 18 + pgvector, API, worker and frontend running from the
`Code/` snapshot; live providers (Groq `openai/gpt-oss-120b`, Gemini `gemini-embedding-2`); synthetic data only.
Screenshots are in `Screenshots/` (application, `granular_screenshots/` crops) and `Screenshots/psql/` (database).

Judgements below are the recorded outcome of the run measured against `GROUND_TRUTH_AND_REVIEW_PROTOCOL.md`; the student is
expected to confirm them when re-running the workflow.

| ID | Workflow / question | Expected | Recorded result | Evidence |
| --- | --- | --- | --- | --- |
| E1 | Add `BrakeController_HLD_v1.md` and `ABS_Subsystem_HLD.md` together | One document processed at a time, the other waits; each stage ticked when its job completes | **Pass.** First file *Processing*, second *Waiting*; tracker showed Parse ✓, Embed running; both finished with all five stages ticked | `03`, `04`, `05`, `06`; `granular 01–03` |
| E2 | Re-upload the revised HLD under the same file name | Recorded as version 2 of the same document | **Pass.** Two versions with different SHA-256 | `08`; `granular 04`; `psql p04` |
| E3 | Stored structure | Section tree, chunks with breadcrumb context, 768-D embeddings, HNSW + GIN indexes | **Pass.** 7 sections / 7 chunks for v1; every chunk embedded; indexes present | `psql p03`, `p04`, `p05`, `p06` |
| E4 | "What does BrakeController require?" (Hybrid) | `BrakeController REQUIRES WheelSpeedInterface`, cited | **Pass.** 1 claim, 100 % support, two citations (sections *2 Dependencies and Port Allocations* and *2 Updated Dependencies*), graph fact shown as *Confidence 1.00 · EXPLICIT · PENDING* | `12`; `granular 06–08` |
| E5 | "Which DID corresponds to the vehicle speed signal and what is its data length?" (Source only) | `0xF40D` = `VehicleSpeed`, length 1 (table row) | **Pass.** DID correct and cited to *3.2 Diagnostics (Approved)*; the length claim was verified at 60 % support (at the 0.6 threshold) | `13` |
| E6 | "What is the maximum supported braking torque of the BrakeController in newton-metres?" | Fact absent from all documents → refuse | **Pass.** *Insufficient evidence*, groundedness 0 %, nothing invented | `14` |
| E7 | "What does AbsController require?" (Graph only) | `AbsController REQUIRES WheelSpeedInterface` from the graph, with its source passage | **Pass.** 1 graph fact, claim verified at 100 % support, status *Confidence 1.00 · EXPLICIT · PENDING* | `15` |
| E8 | Inspect a node and a relationship in the graph | Evidence passages, confidence, extraction type, validation history, review controls | **Pass.** `WheelSpeedInterface`: 7 evidence passages with section and source classification; `BrakeCommandInterface CARRIES BrakePressureSignal`: 1 passage (section *3 Signal and Data Element Catalog*) + history | `17`, `18`; `granular 09–11` |
| E9 | Human review | Verify / reject / edit recorded with reason; original kept; node colour and text change | **Pass.** 2 verified, 1 rejected, 1 corrected; the corrected original is stored as superseded; the graph legend shows 1 human-reviewed node (the corrected one, green) and 1 rejected node (red); verified relationships are edges, not nodes | `20`, `21`, `22`; `granular 12–13`; `psql p13`, `p14` |
| E10 | Impact analysis `WheelSpeedInterface`, 2 hops | Direct and indirect elements, with the connecting facts and weakest link | **Pass.** 4 direct, 7 indirect; each card names the path and the weakest link's status | `23`, `24`; `granular 14`; `psql p11` |
| E11 | Findings | Wording "Potential inconsistency detected", never a verdict | **Pass.** 3 open findings; the missing-provider finding for `VehicleStateInterface` is consistent with the fixture (no provider is declared) | `25`; `psql p12` |
| E12 | Revision comparison v1 → v2 | Added / removed / renamed / changed elements with sources from both versions | **Pass.** 90 findings across document, section, entity and relationship scopes; `BrakeCommandInterface` flagged as *possibly renamed* to `BrakeCommandInterface_v2` | `26`, `27`; `granular 15–19`; `psql p16` |
| E13 | Retrieval evaluation | See `EVALUATION_RESULTS.md` | Live: Recall@8 100 %, MRR 0.97, citation validity 100 %, refusal accuracy 100 %, **false refusals 10.5 %**, dropped claims 13.6 % | `EVALUATION_RESULTS.md`, `raw/` |
| E14 | Automated tests and static checks | All pass | 392 backend tests (1 live test skipped), 29 frontend tests, ruff / mypy / eslint / tsc / build clean | `EVALUATION_RESULTS.md` §3 |

## Observations and issues found while capturing the evidence

* **Fixed during this work:** the 3D graph canvas was sized to the browser window instead of its card, which clipped nodes;
  it now follows the card and zooms to fit. A review action raised a UI error earlier when numeric fields arrived as strings;
  covered by a regression test.
* **Extraction quality is imperfect and is why review exists.** The model proposed `ABS` and `ESP` as generic `FUNCTION`
  entities that duplicate the `ABS_Module` / `ESP_Module` components (one was rejected in the run) and the rule-based
  resolver merged five type-variant duplicates. Every extracted fact remained `PENDING` until a person acted.
* **Findings are prompts, not verdicts.** The two `IMPLEMENTED_BY` findings flag that the relationship starts at a software
  component; whether that is wrong depends on the project's modelling conventions.
* **Comparison is conservative but noisy** for heavily rewritten documents: 56 removals include entities that v2 simply stops
  mentioning, which an engineer must still judge.
* **Latency:** refusals and multi-round answers take 20–30 s with the hosted models; answered questions 3–13 s.

## Interpretation

These results show that the pipeline works end to end on synthetic documents, that every graph relationship is traceable to a
source passage, and that unsupported questions are refused. They do not establish accuracy on real HLDs, on scanned
documents (OCR was not exercised) or with other models. Do not quote a single "accuracy" percentage for this system.
