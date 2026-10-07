# `docs/07_GRAPH_STORAGE_AND_PROVENANCE.md`

```markdown
# 07 — Graph Storage and Provenance Specification

## 1. Purpose

Define how the extracted AUTOSAR architecture graph and its source evidence are persisted in PostgreSQL.

The graph is represented using relational tables rather than a native graph database.

PostgreSQL is the persistent system of record.

The graph must remain:

- queryable
- auditable
- reproducible
- referentially valid
- traceable to source evidence

---

# 2. Storage Decision

Use:

```text
PostgreSQL
+
pgvector