# 01 — Project Requirements

## 1. Project

AUTOSAR Architecture Intelligence Assistant

## 2. Target Tata Technologies Use Case

Case Study 1:

AUTOSAR HLD Document Analysis Assistant.

The target system is an AI-assisted engineering application for extracting, organizing, searching and validating architectural knowledge contained in large AUTOSAR High-Level Design documents.

---

# 3. Problem

AUTOSAR High-Level Design documents can contain large amounts of architecture information including:

- software components
- interfaces
- ports
- signals
- dependencies
- functional flows
- integration logic

This information can be distributed across large documents, sections, tables and supporting artifacts.

Manual interpretation creates:

- slow document review
- difficult information discovery
- inconsistent understanding
- dependency-tracing difficulty
- limited reuse of architecture knowledge
- difficulty detecting potential inconsistencies

---

# 4. Product Objective

Create a persistent engineering knowledge system that transforms HLD documentation into:

- structured architectural entities
- structured relationships
- searchable evidence
- a navigable architecture graph
- traceable source provenance
- confidence-aware knowledge
- human-validated knowledge

The system must allow engineers to ask natural-language questions over this knowledge.

---

# 5. Primary Users

- System architects
- AUTOSAR architects
- Software developers
- Integration engineers
- Test engineers
- Engineering managers

---

# 6. Core Inputs

Initial MVP inputs:

- AUTOSAR HLD PDF
- supporting architecture documents
- interface specifications
- component catalogues
- revision information

The architecture should support additional document types later.

---

# 7. Core Outputs

The system should produce:

### 7.1 Architecture entities

Examples:

- component
- software component
- interface
- port
- signal
- functional element
- ECU
- communication element

### 7.2 Architecture relationships

Examples:

- USES
- REQUIRES
- PROVIDES
- CONSUMES
- PRODUCES
- DEPENDS_ON
- CONNECTS_TO
- CARRIES

### 7.3 Evidence

Every accepted graph fact should retain:

- document
- section
- page
- chunk
- source excerpt

### 7.4 Natural-language answers

Answers should contain:

- answer
- relevant graph path where useful
- source citations
- confidence
- extraction classification
- validation status

### 7.5 Findings

Potential:

- inconsistencies
- unresolved entities
- dangling relationships
- missing definitions
- revision conflicts

### 7.6 Impact analysis

The system should identify potentially affected entities when an architecture object changes.

---

# 8. Functional Requirements

## FR-1 Document Upload

The user can upload an approved document.

## FR-2 Document Parsing

The system extracts:

- text
- sections
- subsections
- tables
- page metadata

OCR may be added for scanned documents.

## FR-3 Structural Representation

The document must be represented hierarchically.

## FR-4 Context-Aware Chunking

Sections are chunked only when required by context/token limits.

## FR-5 Embedding

Chunks receive vector embeddings and are stored in pgvector.

## FR-6 Schema Discovery

The system can identify candidate architecture entity/relationship types from representative document content.

## FR-7 Schema Canonicalization

Equivalent relationship/type labels are merged into canonical vocabulary.

## FR-8 Entity Extraction

The LLM extracts candidate entities from context-rich chunks.

## FR-9 Relationship Extraction

The LLM extracts candidate relationships.

## FR-10 Entity Resolution

Aliases and duplicate entities are resolved into canonical entities.

## FR-11 Validation

Candidate facts are checked using deterministic validation where possible.

## FR-12 Confidence Scoring

Candidate facts receive confidence and extraction metadata.

## FR-13 Graph Persistence

Validated graph data is stored in PostgreSQL.

## FR-14 Provenance

Graph facts can be traced back to exact source evidence.

## FR-15 Graph Visualization

Users can explore architecture relationships visually.

## FR-16 Human Review

Users can:

- verify
- edit
- reject

candidate facts.

## FR-17 Natural-Language Query

Users can ask architecture questions in natural language.

## FR-18 Vector Retrieval

The query can retrieve semantically relevant document evidence.

## FR-19 Graph Retrieval

The query can resolve entities and traverse architectural relationships.

## FR-20 Hybrid Retrieval

Vector and graph evidence are combined for final reasoning.

## FR-21 Evidence Sufficiency

An agent can determine that additional evidence is required and trigger bounded additional retrieval.

## FR-22 Cited Answer

The final answer should contain source citations.

## FR-23 Consistency Analysis

The system identifies potential architecture inconsistencies.

## FR-24 Impact Analysis

The system estimates affected downstream architectural elements.

## FR-25 Revision Support

The architecture should support comparing document revisions in a later implementation stage.

---

# 9. Non-Functional Requirements

## NFR-1 Traceability

Important AI outputs must be traceable to source material.

## NFR-2 Auditability

Human corrections and validation actions must be recorded.

## NFR-3 Reproducibility

Graph construction must be repeatable.

## NFR-4 Modularity

LLM and embedding providers must be replaceable.

## NFR-5 Security

Sensitive engineering information should remain within approved boundaries in target deployment.

## NFR-6 Reliability

Invalid model output must not silently corrupt persistent graph data.

## NFR-7 Explainability

The UI must explain:

- where a fact came from
- how it was extracted
- its confidence
- whether a human validated it

---

# 10. Explicit Non-Goals

The MVP does NOT:

- automatically approve architecture
- replace human architects
- replace formal architecture governance
- modify official source HLD documents without review
- autonomously make consequential engineering decisions
- require a native graph database
- require enterprise-scale Kubernetes deployment
- require unrestricted autonomous agents

---

# 11. Product Differentiation

The solution must not be presented as merely:

"Chat with your HLD PDF."

Primary differentiators:

1. Evidence-linked architecture graph
2. Hybrid vector + graph retrieval
3. Explicit vs inferred knowledge
4. Relationship-level confidence
5. Human validation state
6. Canonical entity resolution
7. Architecture consistency analysis
8. Change impact analysis
9. Exact source provenance
10. Persistent engineering knowledge rather than a temporary chat session

---

# 12. MVP Philosophy

Build a strong vertical slice rather than implementing every enterprise-scale feature.

The MVP must convincingly demonstrate:

HLD
→ structured knowledge
→ graph + vector evidence
→ natural-language query
→ graph traversal
→ evidence grounding
→ cited response
→ human validation

Enterprise scaling features may be represented as future scope.