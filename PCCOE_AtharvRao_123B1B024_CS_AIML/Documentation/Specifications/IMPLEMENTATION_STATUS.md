# Implementation Status

## Current state

The repository contains the AUTOSAR Architecture Intelligence Assistant MVP: a React/TypeScript workspace, FastAPI service, PostgreSQL/pgvector relational knowledge store, and PostgreSQL-backed worker queue.

The end-to-end pipeline is explicit and durable:

```text
multipart upload / JSON upload
  -> private managed source storage
  -> DOCUMENT_INGESTION
  -> EMBEDDING
  -> GRAPH_EXTRACTION
  -> ENTITY_RESOLUTION
  -> GRAPH_BUILD
  -> human review / grounded retrieval / comparison
```

Each transition creates an idempotent persisted job. Extraction and graph build retain `CANDIDATE` / `PENDING` state; no automated stage assigns human verification.

## Target architecture

```text
React + TypeScript UI
        |
FastAPI API ---- PostgreSQL job worker
        |              |
        +-- PostgreSQL + pgvector --+
            documents, chunks, graph facts, provenance,
            validation history, reviews, audit, comparisons
        |
LLMProvider / EmbeddingProvider abstractions
```

PostgreSQL remains the system of record. Graph facts are relational, directed, project-scoped, evidence-linked derived knowledge. Source documents remain authoritative. Queries never mutate the graph.

## Phase status

| Phase | Scope | Status |
| --- | --- | --- |
| 1–14 | Foundation through API, retrieval, review, impact, and comparison | Implemented |
| 15 | Durable worker queue and pipeline handlers | Implemented; pipeline chaining verified in code and job tests |
| 16 | React/TypeScript engineering workspace | Implemented; file-upload UI now uses multipart API |
| 17 | Security boundaries and project isolation | Implemented; enterprise identity provider remains an integration boundary |
| 18 | Observability and deterministic performance checks | Implemented |
| 19 | Seed/demo fixtures and evaluation scripts | Implemented; fixtures are provenance-aware where source support exists |
| 20 | Container deployment wiring | Implemented; backend and worker share managed source storage volume |

## Latest verification

Completed locally on 2026-10-07:

- `ruff check`: pass.
- `ruff format --check`: pass.
- `mypy --strict`: pass for 76 backend source files.
- Backend suite inventory: 96 non-live tests pass; 2 PostgreSQL integration tests correctly skip when no database is available.
- Frontend lint: pass.
- Frontend Vitest: 3 tests pass.
- Frontend production build: pass (with a bundle-size warning for the graph dependency).
- The supplied 17-page AUTOSAR HLD reference PDF parses with 18 detected tables and no parser warnings. Numeric table ranges are no longer misclassified as headings.
- PostgreSQL readiness (`vector` and `pg_trgm`) is verified against the local database. Alembic is at `20260909_0006` head.
- Backend readiness responds at `http://127.0.0.1:8000/api/v1/health/ready`; the Vite UI responds at `http://127.0.0.1:5173/`.
- Gemini embedding configuration uses the native embedding endpoint and explicitly requests the configured vector dimension. The Documents workspace can now queue a project-scoped re-embedding job after a model or dimension correction.
- The Groq development configuration uses `openai/gpt-oss-120b`, a current model that supports JSON Schema structured output. The former `llama-3.3-70b-versatile` model was retired by Groq in August 2026.

## Known issues / operational prerequisites

1. Provider credentials previously entered in `backend/.env` were exposed and must be revoked/rotated in their respective provider consoles. Never commit `.env`. Set replacement credentials with `LLM_API_KEY` / `EMBEDDING_API_KEY`, or provider-specific environment variables.
2. Live provider compatibility must be smoke-tested only after credentials are rotated. The OpenAI-compatible adapter preserves an API base URL's configured `/v1` prefix, preventing duplicated `/v1/v1` paths. Gemini embeddings use the native endpoint so `outputDimensionality` can match the pgvector configuration; responses with a different dimension remain intentionally rejected.
3. OCR is an injected local provider boundary. A production OCR engine and document malware scanning policy are deployment decisions still requiring approval.
4. Docker is not currently installed on this machine. Local PostgreSQL works; Compose deployment has not been executed here.
5. The frontend build bundle is approximately 1.6 MB before gzip because of the 3D graph dependency. Code splitting is a performance improvement, not a functional blocker.

## Decisions requiring explicit attention

- Approve the production identity provider for `AUTH_MODE=enterprise`; development `X-User-Id` headers are intentionally not production authentication.
- Choose and provision private document storage, retention, malware scanning, and local OCR policy for confidential engineering documents.
- Pin the approved embedding model and its actual vector dimension before creating a production index; re-embed when this identity changes.
- Keep PostgreSQL + pgvector as the MVP system of record. Do not introduce Neo4j unless measured deep traversal performance justifies a separate read projection.
