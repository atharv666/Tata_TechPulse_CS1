# API Contracts

## 1. Purpose

This document defines the backend API contract for the AUTOSAR Architecture Intelligence Assistant.

The API should be implemented with FastAPI.

All request and response payloads must use typed Pydantic models.

The API layer must not contain core graph, ingestion, retrieval, or LLM business logic.

Use:

```text
API Router
    |
    v
Service Layer
    |
    v
Repository / Provider Layer

---

# Addendum: endpoints of the knowledge-graph layer

All under `/api/v1/projects/{project_id}`; errors use the common envelope (`400` validation, `403`
role, `404` not found, `409` conflict with current state, `422` request shape).

| Method & path | Role | Purpose |
| --- | --- | --- |
| `POST /query` `{query, mode: HYBRID|GRAPH|SOURCE}` | any | Grounded answer; response echoes the mode actually used, graph facts, paths, related findings, limitations |
| `GET /entities?entity_type&validation_state&q` | any | Live entities (merged/replaced hidden); `status_text` pairs confidence with status |
| `GET /entities/{id}`, `/entities/{id}/report` | any | Detail (aliases, merged duplicates, evidence, history, findings) / grouped one-page report |
| `GET /relationships?relationship_type&entity_id`, `GET /relationships/{id}` | any | List / detail with evidence |
| `POST /entities|relationships/{id}/verify|reject|correct` | reviewer | Review; reject and correct need a reason; `409` if already reviewed |
| `GET /findings?status&finding_type`, `POST /findings/{id}/dismiss|reopen` | any / reviewer | Potential inconsistencies |
| `GET /merges`, `POST /merges/{id}/undo` | any / reviewer | Entity-merge audit log and undo |
| `POST /graph-build` | engineer | Queue resolution + build (idempotent) |
| `POST /impact` | any | Bounded change-impact analysis |
| `POST /comparisons`, `GET /comparisons`, `GET /comparisons/{id}`, `GET /comparisons/{id}/findings?classification` | engineer / any | Queue and read revision comparisons |
| `GET /export?format=json|csv|xlsx&table&include_rejected` | any | Structured export with provenance |
| `GET /members`, `GET /audit` | admin / any | Membership and audit history |
