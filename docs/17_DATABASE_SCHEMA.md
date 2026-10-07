
---

# `17_DATABASE_SCHEMA.md`

```md
# Database Schema

## 1. Purpose

PostgreSQL is the system of record.

It stores:

- projects
- users/memberships
- documents
- document versions
- sections
- chunks
- entities
- relationships
- provenance
- validation
- review history
- audit events
- jobs
- comparisons
- embeddings

Use PostgreSQL with pgvector.

---

# 2. Core Tables

Initial schema:

```text
projects
project_members
documents
document_versions
sections
chunks

entities
entity_aliases
relationships

entity_evidence
relationship_evidence

validation_events
audit_events

jobs
comparisons
comparison_findings