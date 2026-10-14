
---

# `15_REVISION_COMPARISON.md`

```md
# Revision Comparison

## 1. Purpose

AUTOSAR architecture evolves through document revisions.

The system must support comparison between document versions without silently treating the latest version as universally correct.

The purpose of revision comparison is to identify:

- added entities
- removed entities
- renamed entities
- changed relationships
- changed signals/interfaces
- changed component dependencies
- changed source statements
- potential inconsistencies

---

# 2. Revision Model

A document should have:

```text
document

---

> **Implementation note (current):** this specification is implemented as described in `ARCHITECTURE_DECISION_RECORDS.md` (ADR-005, ADR-009) and `RAG_DESIGN.md`. Where they differ, the ADRs describe what the code does.
