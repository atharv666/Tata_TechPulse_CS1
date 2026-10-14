# RAG design

How a document becomes searchable evidence and how a question becomes a cited answer. Decisions behind
each step are in `ARCHITECTURE_DECISION_RECORDS.md` (ADR-003, 004, 011, 013).

## 1. Document → chunks

```
upload -> format detection -> parse (PDF / DOCX / Markdown; OCR only for pages without a text layer)
       -> structure (section tree: number, heading, depth, path) -> clean (running header/footer, TOC)
       -> atoms (paragraph | list | table) -> chunks (~400 tokens, sentence overlap, table header repeated)
       -> metadata (title, version, status, date, classification, revision history)
```
Nested structure example:

```
ABS Subsystem HLD
├─ 1 Overview            lead text defines the alias ABSCtrl
│  ├─ 1.1 Components
│  └─ 1.2 Interfaces
├─ 2 Dependencies
└─ 3 Timing and Diagnostics
   ├─ 3.1 Timing
   └─ 3.2 Diagnostics    (DID table)
```
A chunk in 3.1 is stored as raw text for citations plus
`breadcrumb = "ABS_HLD.md > ABS Subsystem HLD > 3 Timing and Diagnostics > 3.1 Timing"`.

## 2. What is embedded and indexed

* **Embedded:** `breadcrumb + "\n" + content` (titles of every ancestor, not their text). The vector knows
  *where* the text lives, so "diagnostic timing" finds 3.1 even if the chunk never repeats the word.
* **Lexical:** an identifier-aware text (`P_WheelSpeed_In` is indexed joined *and* split) in a generated
  `tsvector` column with a GIN index.
* **Reuse:** chunks with identical embedding text share one vector (`content_hash`).
* Vector dimension and model identity are stored per chunk; changing the model requires an explicit re-embed.

## 3. Question → answer

```
question
  ├─ dense  (pgvector, cosine)        ┐ fuse (RRF) -> relevance gate -> per-section diversity
  ├─ lexical (full-text)              ┘                  -> top-k passages
  └─ graph: link entities (name, alias, near-miss) -> plan (direction, types, depth)
            -> PostgreSQL traversal -> facts + their source passages
passages + fact evidence -> small-to-big context (HIT, PARENT_LEAD, NEIGHBOR, GRAPH_EVIDENCE)
  -> LLM drafts atomic claims with citations
  -> code verifies each claim against the cited statement; unsupported claims are dropped
  -> answer (claims, citations, graph facts + status, limitations, groundedness) or "insufficient evidence"
```
* **Parent context at answer time:** only a capped lead of the nearest ancestor that has text, and
  adjacent chunks, never the whole subtree. It is labelled with its role so the answer can say a statement
  relies on parent context.
* **Modes:** `SOURCE` passages only; `GRAPH` facts only, each tied to its source passage and verified;
  `HYBRID` both. The mode actually used is echoed. A graph fact is never evidence without its passage.
* **Bounded rounds:** if no claim is verified, retrieval is retried (≤ `RAG_MAX_ROUNDS`) with a rephrased
  query and a wider graph neighbourhood; it stops when nothing new appears.
* **Groundedness** is the share of generated statements that survived verification times their mean
  support. It is *not* a probability that the architecture is correct; the basis is shown with it.

## 4. Measuring it

`python scripts/evaluate_rag.py` runs a labelled question set in a throw-away database and reports
recall@k, MRR, context recall, citation validity and refusal accuracy (offline: hashed embeddings +
extractive answers; `--live` uses the configured providers). Offline numbers validate the pipeline and
lexical channel; they say nothing about embedding or LLM quality. Tune `RAG_*` settings against `--live`.
