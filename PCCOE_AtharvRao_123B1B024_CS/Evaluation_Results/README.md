# Evaluation Evidence

| File / folder | Content |
| --- | --- |
| `EVALUATION_RESULTS.md` | **Start here.** Retrieval evaluation (offline and live providers), end-to-end run statistics, automated test and static-check results, limits |
| `EVALUATION_LOG.md` | Workflow-by-workflow outcome (E1–E14), observations and issues found |
| `GROUND_TRUTH_AND_REVIEW_PROTOCOL.md` | Expected facts, manual scoring rules and the scored demonstration results |
| `EVIDENCE_INDEX.md` | What every screenshot and database image shows |
| `Screenshots/` | 28 application screenshots, `granular_screenshots/` (19 element crops), `psql/` (16 database views) |
| `raw/` | Unedited output of `python scripts/evaluate_rag.py` (offline and `--live`) |

No single accuracy percentage is claimed. The numbers are measured on small synthetic fixtures and show that the pipeline works
end to end, where it is conservative (false refusals, dropped claims) and where it refuses correctly. Reproduce them with:

```powershell
python scripts/evaluate_rag.py                                   # offline, deterministic
python scripts/evaluate_rag.py --live --json out.json --markdown out.md   # providers from .env; synthetic documents only
```

The `psql` images are renderings of real `psql` output (see `EVIDENCE_INDEX.md`).
