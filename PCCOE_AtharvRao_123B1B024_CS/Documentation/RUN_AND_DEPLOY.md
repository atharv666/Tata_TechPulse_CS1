# Running the Submitted System

## Prerequisites

* Python 3.11+ (developed on 3.14; `mypy` is pinned to the 3.12 grammar because of third-party stubs)
* Node.js 20+ and npm
* PostgreSQL 16+ (developed on 18) with the `vector` (pgvector) and `pg_trgm` extensions available
* Optional: Docker Desktop for Compose; Tesseract for local OCR
* Provider credentials (Groq, Gemini) only when using the hosted providers; **never** put them in the package

## Local development

1. Copy `Code/.env.example` to `Code/.env` or `Code/backend/.env` (never committed) and set `DATABASE_URL` plus the provider keys.
2. Install and migrate (from `Code/backend`):

```powershell
pip install -r requirements.txt
python -m alembic upgrade head          # creates all tables; head = 20261012_0012
```

3. Start the API:

```powershell
cd Code/backend
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

4. Start the worker in a second terminal (it runs the pipeline jobs):

```powershell
cd Code/worker
python -m worker_runner.main
```

5. Start the frontend in a third terminal:

```powershell
cd Code/frontend
npm install
npm run dev
```

Open the printed URL (default `http://localhost:5173`), create/select a project, open **Documents** and add
`Input_Data/BrakeController_HLD_v1.md` and `Input_Data/ABS_Subsystem_HLD.md`. The queue processes them one at a time; the
tracker ticks *Parse → Embed → Extract → Resolve → Build graph*. Then use Ask Architecture, the graph, Impact Analysis, the
Review Queue and Findings. To try revision comparison, upload `BrakeController_HLD_v2.md` as `BrakeController_HLD.md`
(same name = next version).

**Restart the API and the worker whenever `.env` or the code changes**; an old worker process keeps the old settings.

## Command-line helpers

```powershell
python scripts/seed_demo_data.py --run-worker      # queue the sample HLDs through the real pipeline
python scripts/build_graph.py --run-worker         # explicit (re)build of the graph
python scripts/evaluate_rag.py                     # offline retrieval evaluation (throw-away database)
python scripts/evaluate_rag.py --live              # same, with the providers from .env (synthetic documents only)
python scripts/check_no_secrets.py --path <folder> # scan a folder or --zip <archive> for credentials
```

## Docker Compose

From `Code/`, provide a local `.env` with non-secret development values and run `docker compose up --build`. The Compose
definition starts PostgreSQL/pgvector, the API, the worker and the frontend. It was not executed during this update.
Do not use development authentication (`AUTH_MODE=development`) or the placeholder database password in production.

## Quality checks

```powershell
# from Code/
python -m ruff format --check backend/app worker tests scripts
python -m ruff check backend/app worker tests scripts
python -m mypy --config-file backend/pyproject.toml backend/app
python -m pytest                                    # needs PostgreSQL; creates and drops a throw-away database
cd frontend; npm run lint; npm run test -- --run; npm run build
```

Recorded results for this snapshot are in `Documentation/SUBMISSION_AUDIT.md`.
