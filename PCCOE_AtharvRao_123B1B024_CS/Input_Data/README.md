# Declared Input Data / Knowledge Base

All input is **synthetic** AUTOSAR-style High-Level Design text written for this project. No confidential customer or
employer material is included. Any additional input must be approved or synthetic and recorded here before submission.

| File | Role | Declared metadata |
| --- | --- | --- |
| `BrakeController_HLD_v1.md` | Baseline BrakeController subsystem HLD (7 sections, 7 chunks) | version 1.0.0, *Synthetic Technical Fixture* |
| `BrakeController_HLD_v2.md` | Revision of the same document (5 sections, 5 chunks): renamed interface, removed sections, new regenerative-braking content | version 2.0.0, *Synthetic Technical Fixture (Revision Update)* |
| `ABS_Subsystem_HLD.md` | Separate ABS subsystem HLD with an interfaces section, dependencies, a timing section and a diagnostics table (DIDs) | version 1.2.0, **Status: Approved** |
| `ABS_evaluation_questions.json` | 23 labelled questions (19 answerable, 4 unanswerable) for `scripts/evaluate_rag.py` | expected sections and evidence terms per question |

## How the files are used

* **Ingestion demonstration:** `BrakeController_HLD_v1.md` and `ABS_Subsystem_HLD.md` are uploaded together through the
  Documents screen (the queue processes them one at a time).
* **Revision comparison:** `BrakeController_HLD_v2.md` is uploaded **under the same file name** as v1, so the system records it
  as *version 2* of the same document (version identity is the sanitised file name per project; a byte-identical re-upload
  is rejected by SHA-256). v1 → v2 is then compared in the Revision Comparison screen. To use the files exactly as named
  here, copy `BrakeController_HLD_v2.md` to a temporary folder as `BrakeController_HLD.md` before uploading.
* **Retrieval evaluation:** `ABS_Subsystem_HLD.md` with `ABS_evaluation_questions.json` (`scripts/evaluate_rag.py`).
  The questions were written by the student from the fixture text and have not been independently reviewed.

## Ground truth

The expected facts used for manual review of the demonstration are listed in
`Evaluation_Results/GROUND_TRUTH_AND_REVIEW_PROTOCOL.md`.
