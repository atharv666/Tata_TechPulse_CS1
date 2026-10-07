# AGENTS.md

# AUTOSAR Architecture Intelligence Assistant

## 1. Project Identity

Project name:

AUTOSAR Architecture Intelligence Assistant

Project purpose:

Build an evidence-linked, human-validated AI system that transforms AUTOSAR High-Level Design (HLD) documents into a structured architectural knowledge representation and provides natural-language engineering analysis over that knowledge.

This is NOT a generic "chat with PDF" application.

The system must represent architectural entities and relationships explicitly, preserve their provenance to the original HLD, support semantic retrieval and graph traversal, expose confidence and validation state, detect potential inconsistencies, support impact analysis, and provide a human review workflow.

---

# 2. Core Product Principle

The system converts:

Unstructured automotive engineering documentation

into:

Evidence-backed architectural knowledge

and exposes that knowledge through:

- natural-language querying
- graph exploration
- relationship traversal
- architecture consistency checks
- impact analysis
- human review and correction

The system assists engineers. It does not replace engineering governance or approve architecture automatically.

---

# 3. Reference Problem Definition

The target use case is Tata Technologies Case Study 1:

AUTOSAR HLD Document Analysis Assistant.

The case study calls for:

- PDF/document ingestion
- OCR where required
- section/table/metadata extraction
- component/interface/port/signal/flow/dependency extraction
- natural-language search with citations
- document comparison
- inconsistency detection
- structured output
- human review

The system must remain evidence-based and traceable to approved source material.

---

# 4. NON-NEGOTIABLE ARCHITECTURAL PRINCIPLES

## 4.1 PostgreSQL is the system of record

Use PostgreSQL for:

- documents
- sections
- chunks
- entities
- entity mentions
- relationships
- evidence/provenance
- findings
- reviews
- audit records
- workflow state

Use pgvector for embedding storage and vector similarity search.

Do NOT introduce Neo4j for the MVP.

A future migration to a native graph database may be considered if deep multi-hop traversal becomes a demonstrated scalability bottleneck.

---

## 4.2 Graph and vector retrieval are complementary

Never treat the graph as a replacement for source-document retrieval.

Vector retrieval answers:

"Which source passages are semantically relevant?"

Graph retrieval answers:

"Which entities and relationships are structurally relevant?"

The final answer should normally combine:

- graph facts
- source evidence
- provenance
- confidence
- validation state

---

## 4.3 Every graph fact must have provenance

A node or relationship must be traceable back to source evidence.

Minimum provenance path:

graph fact
→ evidence
→ chunk
→ section
→ document
→ page/position

The system must be able to explain:

"Why does this relationship exist?"

by presenting the originating source material.

---

## 4.4 Explicit and inferred facts must be distinguished

Every extracted fact must be classified.

Supported values include:

- EXPLICIT
- INFERRED

Additional source classifications may include:

- DIRECT_TEXT
- TABLE
- DIAGRAM
- MULTI_SOURCE_INFERENCE

Never silently represent an inferred fact as if it were explicitly stated.

---

## 4.5 Every fact must have confidence

Confidence must be stored for:

- entities where appropriate
- entity matches
- relationships
- findings
- generated conclusions where appropriate

Do not expose a confidence number without also exposing useful contextual status.

Example:

Confidence: 0.94
Extraction: EXPLICIT
Validation: PENDING

---

## 4.6 Human validation is first-class

The system must support:

- PENDING
- HUMAN_VERIFIED
- HUMAN_CORRECTED
- REJECTED

At minimum.

Reviewers must be able to:

- inspect source evidence
- verify a fact
- edit a fact
- reject a fact
- record a reason/comment

Do not destroy the original AI extraction when a reviewer edits it.

Store the review/audit history.

---

## 4.7 LLMs must not directly control trusted database state

LLMs may propose:

- entities
- relationships
- schemas
- canonical matches
- interpretations
- answers

LLM output must pass through deterministic validation/application logic before becoming trusted persisted state.

Never allow arbitrary model-generated SQL.

Never let an LLM directly mutate production graph state.

---

## 4.8 LLM providers must be replaceable

All application LLM usage must go through an abstraction layer.

The application must support interchangeable providers such as:

- hosted API provider
- NVIDIA/OpenAI-compatible provider
- local Ollama provider
- future private enterprise provider

Business logic must not depend directly on a specific provider.

---

## 4.9 Embedding providers should also be abstracted

Support interchangeable embedding models such as:

- BGE
- E5
- Sentence Transformers
- future alternatives

The vector retrieval layer must not be tightly coupled to one model implementation.

---

# 5. Document Processing Principles

Documents must first be parsed deterministically.

Do not send an entire large HLD blindly into an LLM.

Pipeline:

Document
→ format detection
→ parsing
→ structural hierarchy
→ context-aware chunking
→ embeddings / semantic index
→ LLM extraction

The document hierarchy must preserve:

- document
- section
- subsection
- page
- table
- metadata

Chunking must be structure-aware.

Do not use naive fixed-size chunking as the only strategy.

A section should be split only when required by model/context limits.

Every child chunk inherits meaningful parent context.

---

# 6. Entity Resolution Principles

Entity mentions may have aliases.

Example:

PostgreSQL
Postgres
PostgreSQL DB
PSQL

may refer to one canonical entity.

Resolution pipeline:

normalization
→ blocking
→ lexical/fuzzy similarity
→ embedding similarity where useful
→ LLM decision only for ambiguous cases
→ canonical merge

Use Union-Find/disjoint-set logic where appropriate for transitive duplicate merging.

Hashing or blocking keys may be used to reduce candidate comparison cost, but hashing alone must never be treated as proof of semantic identity.

Entity matching must consider:

- normalized name
- entity type
- contextual evidence
- similarity
- document evidence

Avoid over-merging distinct entities merely because their names are similar.

---

# 7. Relationship Principles

Relationships are typed directed edges.

Example:

BrakeController
  --REQUIRES-->
WheelSpeedInterface

Use a controlled relationship taxonomy.

Do not allow unconstrained model-generated relationship types to fragment the graph.

Relationship canonicalization must occur before trusted graph insertion.

Examples may include:

- USES
- REQUIRES
- PROVIDES
- CONSUMES
- PRODUCES
- CONNECTS_TO
- DEPENDS_ON
- CARRIES
- PART_OF

The actual AUTOSAR taxonomy is defined in `05_AUTOSAR_KNOWLEDGE_MODEL.md`.

---

# 8. Retrieval Principles

A query may use:

- vector retrieval
- graph retrieval
- both

These are separate retrieval mechanisms.

Typical flow:

User query
→ query understanding/entity linking

Then in parallel:

Query embedding
→ pgvector
→ relevant source chunks

and:

Resolved entity
→ graph traversal
→ relevant graph facts

Then:

graph facts
+
source evidence
+
provenance
+
validation/confidence

→ evidence bundle

→ evidence sufficiency evaluation

→ additional retrieval if necessary

→ final LLM synthesis

---

# 9. Graph Retrieval Principles

Graph traversal must be deterministic once entities and traversal intent are resolved.

The LLM may determine:

- target entity
- intent
- relationship type
- direction
- desired traversal depth

But PostgreSQL performs the actual graph traversal.

Default traversal may be 1-hop.

Impact-analysis queries may use 2–3 hops.

Traversal must be bounded.

Avoid uncontrolled graph exploration.

---

# 10. Evidence Principles

A graph relationship alone is not sufficient final-answer evidence.

For:

Interface X
  --USES-->
Interface Y

the answer pipeline should preferably provide:

Graph fact:
Interface X USES Interface Y

AND source evidence:

Document
Section
Page
Chunk
source excerpt

AND metadata:

Confidence
Extraction type
Validation status

The graph provides structural context.

The original source provides grounding.

---

# 11. Agentic Query Principles

The system should support controlled iterative retrieval.

Example:

Round 1:
retrieve source evidence + graph neighborhood

Evaluate sufficiency.

If insufficient:

- refine query
- expand graph traversal
- perform additional vector retrieval
- gather new evidence

Evaluate again.

Maximum rounds must be bounded.

The system must stop when:

- sufficient evidence exists
- no valuable new evidence is found
- traversal/retrieval limit is reached
- a safety/error condition occurs

Do not build an unbounded reasoning loop.

---

# 12. Consistency and Validation

The system should detect potential structural issues such as:

- missing entity definitions
- dangling relationships
- missing providers
- duplicate entities
- conflicting declarations
- inconsistent relationship types
- unresolved aliases
- stale/revision conflicts

Detection does not imply automatic correctness judgement.

Use wording such as:

"Potential inconsistency detected."

not:

"Architecture is incorrect."

Human review is required for consequential conclusions.

---

# 13. Change Impact Analysis

The system should support queries such as:

"What could be affected if Interface X changes?"

Use graph traversal to identify:

- direct dependents
- indirect dependents
- related interfaces
- signals
- functional flows
- potentially affected artifacts/tests where such links exist

Use source evidence to explain the impact.

---

# 14. Graph UI

The graph explorer should expose:

- nodes
- relationships
- provenance
- confidence
- extraction type
- validation status

Suggested visual states:

GREEN:
Human verified

BLUE:
Explicitly extracted, pending validation

ORANGE:
Inferred / lower-confidence

RED:
Potential inconsistency / rejected / validation failure

Do not rely solely on color.
Textual status must also be visible.

Clicking an entity or relationship should open its details and available source evidence.

Review actions:

- Verify
- Edit
- Reject

---

# 15. Reproducibility

Graph construction must be an explicit build operation.

Do not silently mutate the graph merely because a user asked a question.

The system should support:

- build
- rebuild
- validation
- review
- query

as separate concepts.

Graph construction should be rerunnable.

---

# 16. Security

Treat engineering documents as potentially confidential.

Architecture must support:

- project isolation
- authorization
- audit logging
- controlled document access
- local/private inference as the target deployment model

Public hosted model APIs may be used during development only with synthetic/public/non-sensitive data unless organizational policy explicitly permits otherwise.

---

# 17. Coding Standards

Use:

- Python
- FastAPI
- SQLAlchemy
- Alembic
- Pydantic
- PostgreSQL
- pgvector
- React + TypeScript
- LangGraph where agent orchestration is genuinely needed

Prefer deterministic code over LLM reasoning whenever a deterministic solution is adequate.

Every major module requires tests.

---

# 18. Agent Behaviour Rules

Before implementing a feature:

1. Read the relevant specification files.
2. Inspect existing code.
3. Respect existing architecture decisions.
4. Do not introduce new technologies without justification.
5. Do not silently change database contracts.
6. Add or update tests.
7. Run the relevant tests.
8. Report failures honestly.
9. Update implementation status.
10. Keep changes scoped to the requested phase.

Do not rebuild working modules merely because another implementation is personally preferred.

---

# 19. Implementation Order

Follow the staged implementation plan in:

`docs/20_IMPLEMENTATION_PLAN.md`

Do not implement the entire system in one uncontrolled pass.

Each phase must leave the repository in a runnable/testable state.

---

# 20. Source of Truth

When implementation decisions conflict, use this priority:

1. Current task requirements
2. `AGENTS.md`
3. Architecture Decision Records
4. Detailed specification files
5. Existing tests
6. Existing implementation
7. Agent preference

Do not invent requirements that are not specified.

When a requirement is genuinely ambiguous, identify the ambiguity before making a consequential architectural change.

---

# 21. Definition of Done

A feature is not complete merely because code exists.

A feature is complete when:

- implementation exists
- type/schema validation exists where applicable
- error handling exists
- tests exist
- tests pass
- provenance is preserved where applicable
- documentation is updated
- API/UI integration works where applicable
- no known architectural requirement has been silently violated