# Model, RAG, and Configuration Declaration

Snapshot: 14 October 2026 (matches the `Code/` folder in this package).

## Architecture in one paragraph

The application is an evidence-backed GraphRAG-style engineering assistant. **PostgreSQL is the system of record**
(documents, sections, chunks, entities, relationships, evidence, findings, reviews, audit, jobs). **pgvector** stores the
chunk embeddings (HNSW, cosine) and PostgreSQL full-text search (`tsvector` + GIN) provides the lexical channel. The graph is
stored relationally (no Neo4j) and traversed by a bounded PostgreSQL recursive CTE. Every graph fact is linked to a source
excerpt, chunk, section and document version. LLM output is never trusted directly: it is validated, canonicalised and
stored as a **PENDING** candidate that a human can verify, correct or reject.

## Models and providers used for the recorded demonstration

| Capability | Provider abstraction | Provider / model | Notes |
| --- | --- | --- | --- |
| Candidate extraction, ambiguous entity-merge decisions, grounded answer drafting | `LLMProvider` | Groq OpenAI-compatible API, `openai/gpt-oss-120b` | Hosted external dependency; credentials are not in this package |
| Chunk and query embeddings | `EmbeddingProvider` | Gemini native embeddings, `gemini-embedding-2`, 768 dimensions | Explicit 768-dimensional output to match the pgvector column; the model name and version are stored per chunk |
| Vector store | PostgreSQL 18 + pgvector | `vector(768)`, HNSW index with `vector_cosine_ops` | Project-scoped search only |
| Lexical retrieval | PostgreSQL full-text | `tsvector` (`english`) generated column + GIN index | Identifier-aware (`WheelSpeedInterface` also matches "wheel speed interface") |
| OCR (scanned pages) | `OCRProvider` | `none` for the demonstration; `tesseract` (local) or `gemini` (external, consent-gated) available | `OCR_ALLOW_EXTERNAL=false` by default; page results are cached |
| Graph | PostgreSQL relational tables | entities, relationships, evidence tables | Recursive CTE, depth ≤ 3, edge cap, cycle-safe |

The recorded demonstration (`Evaluation_Results/`) used only synthetic HLD fixtures (`Input_Data/`). The hosted providers
were therefore acceptable under the project's policy (development with synthetic/public data only; local or private inference
is the target for confidential documents).

## Provider substitution (no business-logic change)

Business logic calls only `LLMProvider`, `EmbeddingProvider` and `OCRProvider`. The factory supports a deterministic `fake`
provider (tests/offline evaluation), OpenAI-compatible APIs, Ollama (local) and the native Gemini embedding adapter.
A local deployment is configured, for example, like this:

```env
LLM_PROVIDER=ollama
LLM_BASE_URL=http://localhost:11434
LLM_MODEL=<validated-local-chat-model>

EMBEDDING_PROVIDER=ollama
EMBEDDING_BASE_URL=http://localhost:11434
EMBEDDING_MODEL=<validated-local-embedding-model>
EMBEDDING_DIMENSIONS=<actual-model-dimension>
```

Changing the embedding model, version or dimension requires an explicit re-embed (Documents → *Re-embed all passages*, or
`POST /projects/{id}/reembed`); chunks record which model produced each vector, and retrieval only compares vectors of the
active model. A local model was **not** used for the demonstration because the available hardware was not sufficient for a
validated, responsive local run.

## Prompts and guard-rails

| Prompt / control | Location | Version / setting |
| --- | --- | --- |
| Candidate extraction (entities, relationships, direction conventions, "named items only") | `Code/backend/app/extraction/prompts.py` | `autosar-candidate-extraction-v4` |
| Entity-merge decision for ambiguous pairs | `Code/backend/app/canonicalization/` | LLM consulted only after blocking, guards and rules; minimum confidence `0.85` |
| Answer drafting (structured claims with citations) | `Code/backend/app/retrieval/answer.py`, `evidence.py` | Output must be JSON claims that cite `chunk:<id>` identifiers |
| Claim verification | `Code/backend/app/retrieval/answer.py` | Each claim is checked against its cited text (support ≥ 0.6, linking verbs ignored, table rows handled); unsupported claims are dropped and counted |

Controls that apply to every model call:

- Source documents are treated as untrusted data and are kept separate from system instructions.
- Model output is parsed into Pydantic models; invalid output is retried and then rejected, never half-applied.
- The relationship taxonomy is controlled; model-invented relationship types cannot fragment the graph.
- Entities and relationships created from model output start as `PENDING` candidates; the pipeline never sets
  `HUMAN_VERIFIED`.
- Free-form model-written SQL does not exist. Graph traversal is a fixed, parameterised query.
- An answer without sufficient, verifiable evidence is replaced by an explicit *insufficient evidence* response.

## Retrieval and pipeline settings (defaults from `Code/backend/app/core/config.py`)

| Setting | Default | Meaning |
| --- | ---: | --- |
| `CHUNK_TARGET_TOKENS` / `CHUNK_MAX_TOKENS` / `CHUNK_OVERLAP_TOKENS` | 400 / 800 / 80 | Structure-aware chunks; a section is split only above the maximum |
| `RAG_DENSE_K` / `RAG_LEXICAL_K` / `RAG_RRF_K` | 30 / 30 / 60 | Candidates per channel and reciprocal-rank-fusion constant |
| `RAG_DEFAULT_TOP_K` | 8 | Passages used for an answer |
| `RAG_MIN_DENSE_SIMILARITY` | 0.5 | Relevance gate for the dense channel (tune with `scripts/evaluate_rag.py --live`) |
| `RAG_MAX_ROUNDS` | 2 | Bounded agentic retrieval rounds |
| `RAG_CLAIM_SUPPORT_THRESHOLD` | 0.6 | Minimum support of a claim by its cited text |
| `RESOLUTION_CANDIDATE_THRESHOLD` | 0.62 | Lexical/fuzzy similarity to consider a pair for entity resolution |
| `REQUIRE_APPROVED_SOURCES` | `false` | When `true`, only documents declaring an approved status are used |
| `OCR_PROVIDER` / `OCR_ALLOW_EXTERNAL` | `none` / `false` | Scanned-page handling and external-OCR consent |

## Secret handling

Only `Code/.env.example` is included, and it contains no keys. Local `.env` files are excluded from the package and from
git. `scripts/check_no_secrets.py` scans for credentials and was run on the packaged `Code/` folder (result in
`Documentation/SUBMISSION_AUDIT.md`). Do not record API keys in the report, video, screenshots, source code or ZIP.
