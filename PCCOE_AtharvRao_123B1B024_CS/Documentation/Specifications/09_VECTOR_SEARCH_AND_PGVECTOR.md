# `docs/09_VECTOR_SEARCH_AND_PGVECTOR.md`

```markdown
# 09 — Vector Search and pgvector Specification

## 1. Purpose

Define the semantic retrieval system used to locate relevant source-document evidence during GraphRAG queries.

The vector layer is complementary to the architecture graph.

The vector layer retrieves source passages.

The graph layer retrieves relationships.

---

# 2. Storage Decision

Use:

```text
PostgreSQL
+
pgvector