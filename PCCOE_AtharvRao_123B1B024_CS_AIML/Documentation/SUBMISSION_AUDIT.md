# Submission Package Audit

**Audit date:** 7 October 2026  
**Package:** `PCCOE_StudentName_PRN_CSx_AIML`

## Present and checked

| Requirement | Location | Status |
| --- | --- | --- |
| Required top-level folders | package root | Present |
| Synthetic demo HLD | `Input_Data/BrakeController_HLD_v1.md` | Present and declared |
| Source code, tests, migrations, scripts, Docker files, synthetic test fixtures | `Code/` | Present; environment secrets excluded |
| Model/provider, embedding, vector-store, prompts, local alternative declaration | `Model_Prompts_Config/MODEL_AND_CONFIGURATION.md` | Present |
| Evaluation protocol, benchmark result, screenshot log | `Evaluation_Results/` | Present; live screenshots still to be added |
| Technical report populated from supplied template | `Documentation/AUTOSAR_Architecture_Intelligence_Assistant_Technical_Report_Draft.docx` | Present; add screenshots, identity fields, and final signatures before PDF export |
| System architecture, SDD method, setup, provenance, limitations | `Documentation/` | Present |
| Video plan | `Video/DEMONSTRATION_SCRIPT.md` | Present; recording still to be added |
| Student declaration and faculty approval templates | `Declarations/` | Present; signatures still required |
| Detailed editable synopsis | `Synopsis/AUTOSAR_Architecture_Intelligence_Assistant_Detailed_Synopsis.docx` | Present; approved signed PDF still required |

## Concept coverage

The package documents deterministic ingestion, contextual chunking, pgvector embeddings, relational directed graph facts, project isolation, provenance, controlled extraction, candidate/trusted distinction, confidence and validation state, human review/audit history, hybrid retrieval, citations, bounded impact analysis, revision comparison, provider abstraction, security, observability, Docker, and SDD.

## Before ZIP submission

1. Rename the package with actual student name, PRN, and class.
2. Complete the editable synopsis/report identity fields; add the faculty-approved signed synopsis and signed declaration.
3. Capture and insert screenshots for E1–E5; complete actual results and manual review outcomes.
4. Export the completed technical report to PDF and add the final video MP4.
5. Re-run the quality checks from the exact `Code/` snapshot and save terminal output.
6. Confirm that no `.env`, credentials, database dumps, user caches, `node_modules`, or confidential documents are present.
7. Create the ZIP only after the above review.
