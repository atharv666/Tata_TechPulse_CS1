# Curated Evidence Index

All screenshots were captured on 14 October 2026 from the running application (`Code/` snapshot, PostgreSQL 18 + pgvector,
worker, live providers) using the synthetic files in `Input_Data/`. Nothing was edited or mocked; the project was created
empty and filled only through the Documents screen. No credentials, `.env` files or machine-specific paths are visible.

## Application screens (`Screenshots/`)

| File | What it demonstrates |
| --- | --- |
| `01_dashboard_empty.png` | Empty project: dashboard with the three principles (evidence first, humans decide, findings are prompts) |
| `02_documents_dropzone.png` | Documents screen: drop zone for PDF / Word / Excel / CSV / Markdown |
| `03_ingestion_queue_started.png` | Two files added; the upload queue shows one *Processing* and one *Waiting* |
| `04_ingestion_stage_running.png` | Pipeline tracker mid-run: Parse & structure ticked **Done**, Embed passages **Running**, the rest waiting |
| `05_ingestion_second_document.png` | The second file starts only after the first finished |
| `06_ingestion_complete.png` | Both files done; all five stages ticked, 100 % |
| `07_documents_library_versions.png` | Document library with the version list of a document (version 1, SHA-256) |
| `08_documents_version2.png` | Re-upload under the same name recorded as version 2 |
| `09_dashboard_populated.png` | Dashboard counts after processing and review (documents, graph entities, awaiting review, open findings, jobs) |
| `10_ask_empty.png` / `11_ask_mode_dropdown.png` | Ask Architecture and the styled retrieval-mode selector (Hybrid / Graph only / Source only) |
| `12_ask_hybrid_answer.png` | Hybrid answer: claim with citation markers, graph fact with *Confidence 1.00 · EXPLICIT · PENDING*, source evidence with section and document status, limitations |
| `13_ask_source_table_answer.png` | Source-only answer from a table row (DID 0xF40D), cited to *3.2 Diagnostics · Approved* |
| `14_ask_refusal_insufficient_evidence.png` | An absent fact (braking torque in N·m) is refused as *Insufficient evidence* |
| `15_ask_graph_only_answer.png` | Graph-only answer with its graph fact and status |
| `16_graph_overview.png` | 3D knowledge graph: 35 nodes / 24 relationships, colour legend with counts (verified, pending, inferred, rejected) |
| `17_graph_entity_inspector.png` | Entity inspector: confidence, extraction type, validation state, 7 evidence passages, history, Verify / Edit / Reject |
| `18_graph_relationship_inspector.png` | Relationship inspector for `BrakeCommandInterface CARRIES BrakePressureSignal` with its source passage |
| `19_graph_export_menu.png` | Export menu (JSON, Excel, CSV tables) |
| `20_review_queue.png` | Review queue with source passages per candidate fact |
| `21_review_after_decisions.png` | After review: confirmation that the original extraction stays in history |
| `22_review_edit_form.png` | Edit form (name and type) with the required reason |
| `23_impact_entity_dropdown.png` / `24_impact_result.png` | Impact analysis of `WheelSpeedInterface`, 2 hops: 4 direct and 7 indirect potentially affected elements, each with its path and weakest-link status |
| `25_findings.png` | Three open findings worded "Potential inconsistency detected: …" |
| `26_comparison_setup.png` / `27_comparison_result.png` | Revision comparison v1 → v2: summary chips and the changed sections / entities / relationships |
| `28_audit.png` | Persisted background jobs (all completed) and audit history (merges, verifications, rejection) |

### Granular crops (`Screenshots/granular_screenshots/`)

`01` upload queue list · `02` tracker running · `03` tracker complete (all ticks) · `04` versions panel · `05` custom dropdown ·
`06` answer claims and status · `07` expanded citations · `08` graph-facts table · `09` entity inspector · `10` expanded evidence
passages · `11` relationship inspector · `12` review card with source passage · `13` correction form · `14` direct-impact card ·
`15` comparison summary · `16`–`19` comparison groups (document, sections, entities, relationships).

## PostgreSQL evidence (`Screenshots/psql/`)

These images are **renderings of real `psql` output**: each query was executed with the `psql` client against the database
that the screenshots above were taken from, and the transcript (prompt, query and result, unedited) was drawn into an image
with a script. They show what the application stored.

| File | Query / command | What it demonstrates |
| --- | --- | --- |
| `p01_tables_and_migration_head.png` | `\dt`, `alembic_version` | 22 tables; migration head `20261012_0012` |
| `p02_extensions.png` | `\dx` | `vector` (pgvector) and `pg_trgm` installed |
| `p03_chunks_table_vector_and_indexes.png` | `\d chunks` | `embedding vector(768)`, generated `search_vector tsvector`, HNSW (`vector_cosine_ops`) and GIN indexes, foreign keys to evidence tables |
| `p04_document_version_hierarchy.png` | counts per document version | 3 versions; sections, chunks and embedded chunks; SHA-256 |
| `p05_section_hierarchy.png` | `sections` of v1 | Section tree (levels, numbering) |
| `p06_chunks_with_parent_context.png` | `chunks` | Chunk kind, tokens, 768 dimensions, model `gemini-embedding-2`, breadcrumb (parent context) |
| `p07_entities.png` | `entities` | Entity type, extraction type, validation state, confidence; counts by state |
| `p08_relationship_provenance_chain.png` | relationship → evidence → chunk → section → version → document | The provenance path required for every graph fact |
| `p09_pgvector_cosine_top5.png` | `<=>` cosine search + `EXPLAIN` | Top-5 neighbours; the planner uses `ix_chunks_embedding_hnsw` (sequential scan disabled for the demonstration because the table is tiny) |
| `p10_lexical_tsvector_rank.png` | `ts_rank` on `search_vector` | The lexical retrieval channel |
| `p11_graph_traversal_recursive_cte.png` | the application's recursive CTE, depth 2 | Bounded, cycle-safe traversal executed by PostgreSQL |
| `p12_findings.png` | `findings` | Persisted potential inconsistencies |
| `p13_review_audit_trail.png` | `validation_events`, `audit_events` | Reviewer, state, reason, time |
| `p14_original_extraction_preserved.png` | corrected / rejected entities | The corrected original is kept (`superseded`), the new fact is `TRUSTED`, the rejected one stays `REJECTED` |
| `p15_job_pipeline.png` | `jobs` | Five pipeline stages per upload, durations, completed |
| `p16_comparison_findings.png` | `comparison_findings` | 90 stored comparison findings by type |

## Result files

| File | Content |
| --- | --- |
| `EVALUATION_RESULTS.md` | Retrieval evaluation (offline and live), end-to-end run statistics, test and static-check results |
| `raw/retrieval_eval_*.json|md` | Unedited output of `scripts/evaluate_rag.py` |
| `EVALUATION_LOG.md` | Per-workflow outcome (E1–E14) and observations |
| `GROUND_TRUTH_AND_REVIEW_PROTOCOL.md` | Expected facts and the manual scoring rules |

## Known gaps in the evidence

* No screenshot or measurement exists for live OCR (scanned documents) or for Docker Compose.
* The question set and ground truth were written by the student; they have not been independently reviewed.
* Extraction precision and recall against a labelled graph were not measured.
