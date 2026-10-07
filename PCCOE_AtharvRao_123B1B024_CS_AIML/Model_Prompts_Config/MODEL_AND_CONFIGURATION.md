# Model, RAG, and Configuration Declaration

## Architecture

The application is an evidence-backed GraphRAG-style engineering assistant. PostgreSQL is the system of record. pgvector stores chunk embeddings. Directed graph facts are stored relationally with document-version and chunk-level provenance.

## Development configuration used for the demonstration

| Capability | Provider abstraction | Selected development provider/model | Notes |
| --- | --- | --- | --- |
| Structured extraction and grounded answers | `LLMProvider` | Groq OpenAI-compatible API / `openai/gpt-oss-120b` | External internet/API dependency; credentials are not included |
| Chunk and query embeddings | `EmbeddingProvider` | Gemini native embeddings API / `gemini-embedding-2` | Explicit 768-dimensional output requested to match pgvector |
| Vector store | PostgreSQL + pgvector | 768-dimension vector column | Project-scoped search only |
| Graph representation | PostgreSQL relational tables | entities, relationships, evidence | Not Neo4j for the MVP |

## Provider substitution

Business logic calls only `LLMProvider` and `EmbeddingProvider`. The provider factory supports fake test providers, OpenAI-compatible APIs, Ollama/local providers, and the native Gemini embedding adapter. To use an approved local setup, configure for example:

```env
LLM_PROVIDER=ollama
LLM_BASE_URL=http://localhost:11434
LLM_MODEL=<validated-local-chat-model>

EMBEDDING_PROVIDER=ollama
EMBEDDING_BASE_URL=http://localhost:11434
EMBEDDING_MODEL=<validated-local-embedding-model>
EMBEDDING_DIMENSIONS=<actual-model-dimension>
```

Changing the embedding model, model version, or dimension requires explicit re-embedding. The project did not use a local model for the demonstration because the available hardware was not sufficient for a validated, responsive local deployment.

## Prompts and controls

The authoritative extraction prompts are in `Code/backend/app/extraction/prompts.py`; answer prompt construction is in `Code/backend/app/retrieval/evidence.py`.

- Source documents are treated as untrusted data and are separated from system instructions.
- Structured outputs are validated with Pydantic models.
- LLM-produced entities and relationships begin as candidate / pending facts.
- Deterministic validation, provenance checks, and human review control trusted state.
- Final answers are checked against available citations; insufficient evidence is surfaced instead of fabricating a claim.

## Secret handling

Only `Code/.env.example` is included. Fill local `.env` files outside this package with replacement credentials. Do not record API keys in the report, video, screenshots, source code, or ZIP.
