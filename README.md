# AUTOSAR Architecture Intelligence Assistant

An evidence-linked, human-validated AI system that transforms AUTOSAR High-Level Design (HLD) documents into structured architectural knowledge representations and provides natural-language engineering analysis over that knowledge.

---

## 1. System Architecture

```text
React + TypeScript UI (Frontend)
       │
FastAPI API / Service Layer ─── Background Worker Pipeline
       │                              │
       ├────── PostgreSQL + pgvector ─┘
       │        (Documents, Chunks, Candidate & Trusted Facts,
       │         Provenance, Reviews, Audit, Revision Comparisons)
       │
LLMProvider / EmbeddingProvider Abstractions
```

- **PostgreSQL + pgvector** is the system of record.
- **Source documents remain authoritative**.
- **LLMs generate candidate facts only** (never issue arbitrary SQL or mutate production graph state directly).
- **Explicit and inferred facts are distinguished**.
- **Every graph fact retains full source provenance** (document, section, page, excerpt).

---

## 2. Quickstart with Docker Compose

Run the entire stack (PostgreSQL + pgvector, Backend, Worker, Frontend) with a single command:

```bash
docker compose up --build
```

### Access Ports
- **Frontend Workspace**: [http://localhost](http://localhost)
- **Backend API Docs (Swagger)**: [http://localhost:8000/docs](http://localhost:8000/docs)
- **Health Endpoint**: `GET http://localhost:8000/api/v1/health`
- **PostgreSQL**: `localhost:5432`

---

## 3. Local Development Setup

### Prerequisites
- Python 3.11+
- Node.js 20+
- PostgreSQL 16 with `pgvector` and `pg_trgm` extensions enabled

### 3.1 Backend Setup
```bash
# Navigate to backend and install dependencies
cd backend
pip install -r requirements.txt

# Run PostgreSQL database migrations
alembic upgrade head

# Start FastAPI application
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

The ingestion pipeline (parse → embed → extract → resolve → build graph) runs in a separate worker process that
claims jobs from PostgreSQL. Start it in a second terminal, from the same environment and `.env`:

```bash
cd worker
python -m worker_runner.main
```

Restart both the API and the worker after changing `.env` or pulling code (a stale worker keeps the old settings).

### 3.2 Frontend Setup
```bash
# Navigate to frontend and install dependencies
cd frontend
npm install

# Run frontend in development mode
npm run dev

# Run Vitest frontend test suite
npm run test

# Run frontend production build
npm run build
```

---

## 4. Seeding Demo Data, Graph Builds & Evaluation

```bash
alembic upgrade head                          # schema first (scripts never create tables)

# 1. Queue the synthetic sample HLDs through the real pipeline (nothing is written directly)
python scripts/seed_demo_data.py              # the worker service processes the queue
python scripts/seed_demo_data.py --run-worker # ... or process it here with the .env providers

# 2. Explicitly (re)build the graph: resolve duplicates, bind relationships, refresh findings
python scripts/build_graph.py --run-worker

# 3. Measure retrieval quality on a labelled question set (throw-away database)
python scripts/evaluate_rag.py                # offline; add --live for the configured providers
```
Everything the pipeline produces starts as PENDING; only a reviewer can verify a fact.

---

## 5. Local Quality Verification Commands

Run full formatting, linting, type checks, and pytest suites locally:

```powershell
# Format and Lint check
python -m ruff format --check backend\app worker tests scripts
python -m ruff check backend\app worker tests scripts

# Type Check
python -m mypy --config-file backend\pyproject.toml backend\app

# Pytest Test Suite
pytest -v
```

---

## 6. Project Features & UI Navigation
- **Ask Architecture**: grounded answers in `HYBRID`, `GRAPH` or `SOURCE` mode: claims with citation markers, graph facts with confidence · extraction · validation status, source status, limitations.
- **Knowledge Graph**: 3D explorer (colour *and* text for review state), filters, fact inspector with evidence, aliases, merged duplicates, history and findings; Verify / Edit / Reject with a recorded reason.
- **Impact Analysis**: bounded PostgreSQL traversal with per-relationship propagation rules; each affected element shows its hops, the chain of facts and their source passages.
- **Review Queue** and **Findings**: pending facts; "potential inconsistency" prompts that stay dismissed once dismissed.
- **Revision Comparison**: metadata, section and value changes plus entity/relationship changes with evidence from both versions.
- **Export**: JSON / CSV / Excel with provenance from the Knowledge Graph screen.
- **Documents**: a sequential upload queue (one document is processed at a time, the rest wait), a five-stage pipeline tracker that ticks each stage as its job completes, versions (same file name = next version; identical bytes are rejected), re-embedding. **Audit**: jobs and audit history.

Submission snapshot: `python scripts/package_submission.py --dest <folder>` copies a clean source tree (no `.env`, caches, uploads or archives); run `python scripts/check_no_secrets.py` on the result.

Design records: `docs/ARCHITECTURE_DECISION_RECORDS.md`, `docs/RAG_DESIGN.md`, status: `docs/IMPLEMENTATION_STATUS.md`.
