
---

# `21_BACKGROUND_JOBS_AND_PIPELINES.md`

```md
# Background Jobs and Pipelines

## 1. Purpose

Large-document processing and graph construction must not block HTTP requests.

Use asynchronous background jobs.

---

# 2. Long-Running Operations

Run as jobs:

```text
document ingestion
OCR
embedding generation
graph extraction
entity resolution
graph validation
graph build
comparison
re-embedding