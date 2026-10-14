# 02 — System Architecture

## 1. Architecture Goal

Build a staged, auditable architecture rather than a single end-to-end LLM workflow.

The system has two major phases:

### Phase A — Knowledge Construction

HLD
→ ingestion
→ structural normalization
→ contextual chunking
→ schema discovery
→ entity/relationship extraction
→ canonicalization
→ entity resolution
→ validation
→ confidence scoring
→ PostgreSQL graph + pgvector

### Phase B — Knowledge Consumption

User query
→ query understanding
→ entity linking
→ vector retrieval + graph retrieval
→ provenance expansion
→ evidence fusion
→ evidence sufficiency agent
→ optional additional retrieval
→ final LLM synthesis
→ cited answer

---

# 2. High-Level Architecture

```text
                         AUTOSAR HLD
                              |
                              v
                    DOCUMENT INGESTION
                              |
                              v
                    STRUCTURAL PARSING
                              |
                              v
                DOCUMENT / SECTION TREE
                              |
                              v
                 CONTEXT-AWARE CHUNKING
                              |
                 +------------+------------+
                 |                         |
                 v                         v
             EMBEDDING              LLM EXTRACTION
                 |                         |
                 |                  Schema Discovery
                 |                         |
                 |                  Canonicalization
                 |                         |
                 |                  Entity Resolution
                 |                         |
                 |                       Validation
                 |                         |
                 |                   Confidence Scoring
                 |                         |
                 +------------+------------+
                              |
                              v
                 POSTGRESQL + PGVECTOR
                    /        |        \
                   /         |         \
                  v          v          v
             Documents     Graph      Vectors
             Evidence      Entities   Embeddings
                          Relations
                              |
                              v
                       QUERY INTERFACE
                              |
                              v
                       QUERY PLANNER
                         /         \
                        /           \
                       v             v
                Vector Retrieval   Graph Retrieval
                       |             |
                       v             v
                Source Chunks    Graph Facts
                       |             |
                       +------+------+
                              |
                              v
                     PROVENANCE EXPANSION
                              |
                              v
                       EVIDENCE BUNDLE
                              |
                              v
                  EVIDENCE SUFFICIENCY AGENT
                         /           \
                       YES            NO
                        |              |
                        |        Additional Retrieval
                        |          /          \
                        |       Graph        Vector
                        |          \          /
                        |           +--------+
                        |                |
                        +----------------+
                              |
                              v
                       FINAL LLM SYNTHESIS
                              |
                              v
                 ANSWER + CITATIONS + GRAPH
                 PATH + CONFIDENCE + STATUS
                              |
                              v
                        HUMAN REVIEW