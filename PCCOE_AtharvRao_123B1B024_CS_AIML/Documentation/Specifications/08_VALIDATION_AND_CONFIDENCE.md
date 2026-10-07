# `docs/08_VALIDATION_AND_CONFIDENCE.md`

```markdown
# 08 — Validation and Confidence Specification

## 1. Purpose

Define how extracted entities and relationships are validated before they become trusted architecture knowledge.

This module prevents unsupported, malformed, contradictory, or low-confidence LLM output from silently contaminating the graph.

---

# 2. Core Principle

LLM output is candidate knowledge.

It is not automatically trusted.

Pipeline:

```text
LLM Extraction
      ↓
Candidate Fact
      ↓
Validation
      ↓
Confidence
      ↓
Routing
      ├── Trusted / auto-accepted
      └── Human Review