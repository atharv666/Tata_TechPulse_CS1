# AUTOSAR Architecture Intelligence Assistant — Submission Package

Replace `StudentName`, `PRN`, and `CSx` in this folder name before final submission.

## Package map

| Folder | Contents | Final action |
| --- | --- | --- |
| `Synopsis/` | Approved synopsis and faculty approval record | Print, obtain signatures, scan to PDF |
| `Input_Data/` | Synthetic BrakeController HLD used for the demo | Keep as the declared demo knowledge base |
| `Code/` | Sanitized runnable source, tests, migrations, scripts, and deployment files | Do not add `.env`, secrets, caches, or `node_modules` |
| `Model_Prompts_Config/` | Provider/model declaration and prompt inventory | Update only if the demo configuration changes |
| `Evaluation_Results/` | Test evidence and screenshot checklist | Add captured screenshots and completed results table |
| `Documentation/` | Technical report outline, architecture, setup, and limitations | Export final report as PDF here |
| `Video/` | Recording plan and final MP4 | Add the final 5–10 minute video |
| `Declarations/` | Student declaration and faculty approval templates | Print and sign where indicated |

## Security rule

This package intentionally excludes `.env` files and API keys. Create local configuration from `Code/.env.example`; never submit credentials, database passwords, tokens, or confidential source documents.

## Declared demonstration scope

- Input: `Input_Data/BrakeController_HLD_v1.md` (synthetic AUTOSAR-style HLD).
- System of record: PostgreSQL with pgvector; graph facts are relational and evidence-linked.
- Development LLM: Groq OpenAI-compatible API, model `openai/gpt-oss-120b`.
- Development embeddings: Google Gemini native embeddings API, model `gemini-embedding-2`, 768 dimensions.
- Local alternative: Ollama through the existing provider abstraction, subject to suitable hardware and validated model compatibility.

The model configuration is a development declaration, not an assertion that internet access is required for every component. PostgreSQL, parsing, chunking, graph traversal, validation, and the UI/backend workflow remain locally deployable.
