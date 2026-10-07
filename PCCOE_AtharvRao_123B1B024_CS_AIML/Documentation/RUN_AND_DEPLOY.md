# Running the Submitted System

## Prerequisites

- Python 3.11+ compatible with the submitted dependencies
- Node.js/npm for the frontend
- PostgreSQL with `pgvector` and `pg_trgm`
- Optional Docker Desktop for Compose deployment
- Internet connectivity and declared provider credentials only when using the selected hosted LLM/embedding providers

## Local development

1. Copy `Code/.env.example` to a local `.env` outside version control and set PostgreSQL plus approved provider credentials.
2. Apply migrations from `Code/backend`:

```powershell
python -m alembic upgrade head
```

3. Start the API:

```powershell
cd Code/backend
uvicorn app.main:app --reload
```

4. Start the worker:

```powershell
cd Code/worker
python -m worker_runner.main
```

5. Start the frontend:

```powershell
cd Code/frontend
npm install
npm run dev
```

Use the Documents screen to upload `Input_Data/BrakeController_HLD_v1.md`, monitor the persisted jobs, then use Ask Architecture after ingestion, embedding, and extraction have completed.

## Docker Compose

From `Code/`, provide a local `.env` with non-secret development values and run:

```powershell
docker compose up --build
```

The Compose definition starts PostgreSQL/pgvector, API, worker, and frontend. Do not use the development authentication mode or placeholder database password in production.

## Quality checks

```powershell
python -m ruff format --check Code/backend/app Code/tests
python -m ruff check Code/backend/app Code/tests
cd Code/backend; python -m mypy --config-file pyproject.toml
python -m pytest -c Code/backend/pyproject.toml
cd Code/frontend; npm run lint; npm run test -- --run; npm run build
```
