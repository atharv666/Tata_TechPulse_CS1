# Technical Report Outline

Export the completed report as `AUTOSAR_Architecture_Intelligence_Assistant_Report.pdf` in this folder.

## 1. Title Page

- Project: AUTOSAR Architecture Intelligence Assistant
- Student name(s), PRN(s), division, guide, department, institute, academic year

## 2. Abstract and Problem Statement

Explain the need to transform unstructured AUTOSAR HLD documentation into traceable, evidence-linked architectural knowledge. State that the product is not a generic chat-with-PDF system and does not replace engineering approval.

## 3. Objectives and Scope

- Multi-format document ingestion with PDF as the priority path.
- Structure-aware chunking and source traceability.
- Candidate entity/relationship extraction using a controlled AUTOSAR taxonomy.
- PostgreSQL relational graph, pgvector retrieval, graph traversal, citations, review, impact analysis, and revision comparison.
- Explicit boundaries: candidate facts are not automatically trusted; a revision difference is not automatically a contradiction.

## 4. Development Methodology: Specification-Driven Development (SDD)

Describe the workflow used in this project:

1. Define system, data, security, retrieval, and UX constraints in project specifications.
2. Implement in staged phases with tests and implementation-status tracking.
3. Use deterministic processing where possible and model outputs only through validated provider abstractions.
4. Preserve architectural decisions as code, schema constraints, migrations, tests, and documentation.

Codex was used as a development assistant under human direction to help implement and review code against the specifications. It is not part of the submitted application runtime or an autonomous authority over architecture decisions.

## 5. System Architecture and Data Flow

```text
Source document -> parse -> hierarchy/sections -> contextual chunks
  -> embeddings (pgvector) -> candidate extraction -> validation
  -> relational graph + provenance -> review / retrieval / analysis
```

Describe React/TypeScript frontend, FastAPI API, PostgreSQL/pgvector, and durable worker jobs. Include a screenshot or recreated architecture diagram.

## 6. Implementation Details

- Ingestion, file validation, hashing, parsing, OCR fallback boundary, tables, and chunking.
- Entity taxonomy, relationship taxonomy, canonicalization, and validation states.
- Project isolation, audit, human review, and citation verification.
- API contracts, background jobs, Docker deployment, observability, and error handling.

## 7. Models, Prompts, and Data Governance

Use `../Model_Prompts_Config/MODEL_AND_CONFIGURATION.md`. Declare any external API dependency. State that source data is untrusted and isolated from system instructions, and that credentials are not submitted.

## 8. Evaluation

Use the completed `../Evaluation_Results/EVALUATION_LOG.md`, test output, screenshots, and a manually reviewed ground-truth set. Clearly distinguish measured results from qualitative demonstration observations.

## 9. Results

Show the ingestion workflow, citations, graph/provenance inspection, review actions, impact paths, and revision comparison. Every project-specific conclusion must retain source evidence.

## 10. Limitations and Future Work

- Development model calls use external APIs and require declared connectivity/credentials.
- Production identity provider, OCR engine, malware scanning, document retention, and private storage remain deployment decisions.
- Local Ollama deployment is architecturally supported but not used for this demo due to hardware limitations.
- Neo4j is deliberately excluded from this MVP; PostgreSQL is the system of record. Consider a graph read projection only if measurements prove deep traversal is a bottleneck.

## 11. Conclusion and References

Reference project specifications, AUTOSAR material where permitted, provider documentation, and all approved/synthetic data sources.
