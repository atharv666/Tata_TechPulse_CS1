# Worker

The worker polls the PostgreSQL job queue and runs one pipeline stage per job
(`DOCUMENT_INGESTION → EMBEDDING → GRAPH_EXTRACTION → ENTITY_RESOLUTION → GRAPH_BUILD`,
plus `REEMBED`, `REVISION_COMPARISON`). The implementation lives in `backend/app/jobs`; this
directory only contains the process entry point and its Dockerfile.

Local run (from the repository root):

```powershell
python -m worker.worker_runner.main      # or: cd worker; python -m worker_runner.main
```
