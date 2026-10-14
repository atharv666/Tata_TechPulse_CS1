# Query Planner and Entity Linking

## 1. Purpose

This document defines how natural-language engineering questions are converted into a structured retrieval plan.

The system must not send the raw user question directly to the LLM and ask it to answer from memory.

Instead, the query pipeline must:

1. Understand the user query.
2. Identify relevant AUTOSAR entities.
3. Determine the requested intent.
4. Determine the required retrieval depth.
5. Execute graph and vector retrieval.
6. Build an evidence bundle.
7. Generate the final answer only from retrieved evidence.

The query planner is therefore the bridge between the conversational interface and the knowledge graph/vector store.

---

# 2. Query Processing Pipeline

```text
User Question
     |
     v
Query Normalization
     |
     v
Intent Detection
     |
     v
Entity Mention Detection
     |
     v
Entity Linking
     |
     v
Retrieval Plan
     |
     +--------------------+
     |                    |
     v                    v
Graph Retrieval      Vector Retrieval
     |                    |
     +---------+----------+
               |
               v
        Evidence Bundle
               |
               v
      Evidence Sufficiency
               |
               v
       Final LLM Response

---

> **Implementation note (current):** this specification is implemented as described in `ARCHITECTURE_DECISION_RECORDS.md` (ADR-011) and `RAG_DESIGN.md`. Where they differ, the ADRs describe what the code does.
