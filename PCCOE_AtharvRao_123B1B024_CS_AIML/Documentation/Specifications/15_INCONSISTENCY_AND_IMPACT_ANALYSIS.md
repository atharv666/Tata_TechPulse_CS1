
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