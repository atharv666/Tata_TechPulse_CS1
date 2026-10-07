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

## 4. Seeding Demo Data, Graph Builds & Benchmarks

```bash
# 1. Seed synthetic AUTOSAR demonstration project and documents
python scripts/seed_demo_data.py

# 2. Execute explicit candidate-to-trusted graph build job
python scripts/build_graph.py

# 3. Run evaluation benchmark suite (measures precision, recall, citation coverage & latency)
python scripts/benchmark.py
```

---

## 5. Local Quality Verification Commands

Run full formatting, linting, type checks, and pytest suites locally:

```powershell
# Format and Lint check
python -m ruff format --check backend\app worker\app tests
python -m ruff check backend\app worker\app tests

# Type Check
python -m mypy --config-file backend\pyproject.toml backend\app
python -m mypy worker\app

# Pytest Test Suite
pytest -v
```

---

## 6. Project Features & UI Navigation
- **Project Selection**: Context switcher in rail navigation.
- **Dashboard**: High-level engineering posture metrics.
- **Documents & Detail**: Document library, SHA-256 checksums, version history, and ingestion.
- **Ask Architecture**: Grounded natural-language query engine with claims, citations, graph paths, and limitations.
- **Knowledge Graph Explorer**: SVG topology canvas, node/edge fact inspector, and inline review actions (`Verify`, `Reject`).
- **Semantic Impact Analysis**: Rule-driven dependency traversal with direct/indirect impact labels.
- **Human Review Queue**: Inspection queue for pending candidate facts with source evidence.
- **Revision Comparison**: Base vs Target document revision diffing.
- **Operational Audit**: Job progress states and project audit logs.
