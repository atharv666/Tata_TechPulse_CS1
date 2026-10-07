
---

# `24_OBSERVABILITY_AND_METRICS.md`

```md
# Observability and Metrics

## 1. Purpose

The system must provide enough observability to diagnose ingestion errors, retrieval quality, model behavior, and user-facing failures.

---

# 2. Logging

Use structured logs.

Example:

```json
{
  "timestamp": "...",
  "level": "INFO",
  "event": "GRAPH_BUILD_COMPLETED",
  "project_id": "...",
  "build_id": "...",
  "duration_ms": 12345
}