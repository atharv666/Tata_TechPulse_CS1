# Architecture Decision Records

Decisions made while making the pipeline, retrieval and graph layers correct. Each record states what
was decided and why, so later changes can be judged against the reason. Rules in `AGENTS.md` still take
priority over everything here.

---

## ADR-001 — Job execution model
**Status:** accepted

A job is claimed in a short transaction (`SELECT ... FOR UPDATE SKIP LOCKED`, a lease in `locked_at`),
the handler then runs in its **own session** and commits completed units of work through
`JobContext.checkpoint`, and the outcome is written in a **fresh transaction**. Failures are classified:
`RetryableJobError` / `ProviderTransientError` reschedule with exponential back-off (`run_after`),
`JobPartialFailure` keeps committed work and records which items failed, `JobCancelled` honours a
dedicated `cancel_requested` column. A job whose lease expired is recovered by the next poll.
The next stage is queued in the same transaction as the work that makes it runnable.

*Why:* the previous worker held one transaction for a whole document, crashed on every upload, and lost
all progress on any error. *Consequence:* handlers must be idempotent; several workers can run safely.

## ADR-002 — Schema changes only through explicit Alembic migrations
**Status:** accepted

The 0001 baseline is frozen explicit DDL. Every later change is a new migration (0007–0012 so far). A test
migrates an empty database to head and fails on any difference from the ORM (drift test). Scripts never
call `create_all`. The embedding dimension is a deployment setting checked at start-up.

## ADR-003 — Hybrid retrieval: dense + lexical, gated, then verified
**Status:** accepted

Dense vectors (pgvector HNSW, cosine) find passages that *mean* the same; PostgreSQL full-text over an
identifier-aware lexical text finds exact identifiers (`P_WheelSpeed_In`, `0xF190`). The two ranked lists
are fused with Reciprocal Rank Fusion (no score calibration needed). A passage is evidence only if it is
similar enough or shares enough of the question's terms; otherwise the answer is "insufficient evidence".
The LLM drafts atomic claims that cite numbered sources; **code** keeps a claim only if its identifiers,
numbers and acronyms co-occur in one statement of the cited text (statement-level, table rows use their
header as context). Unsupported claims are dropped and counted.

## ADR-004 — Structure-aware chunking; the hierarchy is embedded as a breadcrumb
**Status:** accepted

Documents are parsed deterministically into a section tree (PDF bookmarks → font size → validated
numbering; DOCX styles; Markdown `#`), running headers/footers and TOC dot-leaders are removed, and
chunks are built from paragraph / list / table atoms. Each chunk stores raw text (for citations) and a
`breadcrumb` (`document > ancestor headings`) that is embedded **with** the text. Parent *content* is not
embedded; at answer time only a capped lead of the nearest ancestor with text, plus neighbouring chunks,
is added as context ("small-to-big"). Identical embedding text reuses its vector (`content_hash`).

## ADR-005 — Taxonomy extension and impact propagation rules
**Status:** accepted

Added entity types `FUNCTIONAL_FLOW`, `TEST_CASE` and relationship types `PRECEDES`, `TRIGGERS`,
`SENDS_TO`, `VERIFIED_BY`, `IMPLEMENTED_BY` to cover the case study's functional flows and the
requirement/test links needed for change impact. The taxonomy stays closed. Domain/range expectations
(`knowledge/rules.py`) are **advisory**: a violation raises an `INCONSISTENT_RELATIONSHIP_TYPE` finding, it
never rejects a fact. How a change propagates per relationship type (`IMPACT_PROPAGATION`) is data, e.g.
`REQUIRES`/`USES`/`CONSUMES` propagate from the used thing to its user, `PROVIDES` both ways,
`PRECEDES`/`TRIGGERS` downstream, `VERIFIED_BY` towards tests.

## ADR-006 — OCR provider policy
**Status:** accepted

OCR sits behind an `OCRProvider` boundary. Default is none; `tesseract` runs locally; `gemini` is an
external provider and only runs when `OCR_ALLOW_EXTERNAL=true`, every external use writes an
`EXTERNAL_OCR_USED` audit event, recognised page text is cached per page image (retries never re-bill),
and text recovered by OCR is always classified `OCR_TEXT` and discounted slightly in confidence.
Confidential documents must use a local provider.

## ADR-007 — Entity resolution
**Status:** accepted

```
active entities -> blocking keys (hash maps) -> hard guards -> deterministic scoring
  -> LLM only for ambiguous pairs (batched, bounded per run, cached) -> constrained Union-Find -> soft merge
```
* Blocking keys (normalised name, token set without type words, rare words, acronym) only *propose* pairs.
* Hard guards forbid a merge whatever proposed it: different type, different version/index numbers
  (`V1`/`V2`, `Port1`/`Port2`), opposite qualifiers (`FL`/`FR`, request/response), two human-reviewed
  entities, or a recorded "different" decision.
* An identical normalised name or an explicit alias merges without a model. Hashing is never proof of
  identity.
* The LLM sees a numbered pair with names, aliases and source excerpts and answers SAME / DIFFERENT /
  UNSURE with a confidence; SAME below `RESOLUTION_LLM_MIN_CONFIDENCE` is stored as UNSURE. It never
  names entities or touches the database. Decisions are cached against a fingerprint of the evidence.
* The constrained Union-Find refuses a union that would put a forbidden pair in one group.
* A merge is **soft**: the merged row stays (`merged_into_id`), evidence, aliases and relationships move
  to the survivor, everything moved is recorded in `entity_merges.moved`, and the merge can be undone
  (the pair is then remembered as different). A human-reviewed entity always survives.
* Embedding similarity of names is deliberately not used; source context is a better signal and is
  what the LLM judges.

## ADR-008 — Relationships are staged by name and bound after resolution
**Status:** accepted

Extraction cannot know which entities exist, so it records `relationship_candidates` (endpoint names, the
quoted evidence). After resolution the binder looks names up (canonical names and aliases) in the final
entity set, so the result no longer depends on chunk order. Unbindable candidates (unknown, ambiguous or
rejected endpoint) stay `UNBOUND` with a note and surface as findings. A statement bound to a
reviewer-rejected or superseded relationship is not resurrected on rebuild.

## ADR-009 — Findings are persisted potential inconsistencies
**Status:** accepted

Detectors (missing provider, missing entity definition, dangling relationship, possible duplicate,
conflicting declaration, unusual relationship type, alias conflict) are pure functions; a finding's
fingerprint is `hash(type, stable key)`. A build upserts by fingerprint: new → OPEN, vanished → RESOLVED,
**dismissed stays dismissed** (with who and why). Wording is always "Potential inconsistency detected:".

## ADR-010 — Confidence is derived, not accumulated
**Status:** accepted

The extractor's value is stored as `raw_confidence` and never changed; `confidence` is a pure function of
it (inferred ×0.85, OCR-only ×0.95, corroboration +0.02, no evidence → 0). Rebuilding any number of times
yields the same value, validation events are written only on change, and human-reviewed facts are never
recomputed. Everything shown to users carries extraction type and validation state next to the number.

## ADR-011 — Graph traversal is executed by PostgreSQL
**Status:** accepted

Traversal is a fixed, parameterised recursive CTE (`graph/traversal.py`): depth 1–3, edge limit, an edge
is never walked twice on a path (cycles terminate, the closing edge is reported), only live facts are
visible (not rejected, superseded, collapsed or touching merged/replaced entities). The planner chooses
root, direction, types and depth from the *grammar* of the question ("what does X require" vs "what
requires X"); no model writes SQL. Graph facts are answer evidence only together with their source passage.

## ADR-012 — (withdrawn) Admin telemetry
**Status:** withdrawn

A per-project admin view with usage events, retrieval traces and provider-call metrics was built and then removed at the owner's request. Nothing about it remains in the schema (migration 0012 drops the tables) or the API. Retrieval traces are still returned with each answer (scores and ids) but are not persisted.

## ADR-013 — Approved sources
**Status:** accepted

A document's declared `Status:` header is extracted as metadata and shown beside every citation. With
`REQUIRE_APPROVED_SOURCES=true` only versions whose status is in `APPROVED_SOURCE_STATUSES` may ground an
answer (including graph evidence); with none approved, no retrieval runs. Off by default so drafts can be
explored; citing an unapproved document then adds a limitation.
