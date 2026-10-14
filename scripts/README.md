# Scripts

| Script | Purpose |
| --- | --- |
| `seed_demo_data.py` | Queue the synthetic sample HLDs through the real ingestion pipeline (`--run-worker` processes them here). Writes no facts itself. |
| `build_graph.py` | Queue an explicit graph (re)build for a project (resolution + binding + validation + findings). |
| `evaluate_rag.py` | Retrieval/answer quality on a labelled question set, in a throw-away database. |
| `check_no_secrets.py` | CI guard against committed credentials. |

All of them need the schema migrated (`alembic upgrade head`) and fail loudly otherwise.
