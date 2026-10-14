# Provenance-Based Architecture Knowledge and Human-in-the-Loop Review

## Why provenance is central

The source document is authoritative; the extracted graph is derived knowledge. A graph fact alone is not enough for an
engineering answer, so every entity and every directed relationship is linked through evidence to its origin:

```text
entity or directed relationship
  -> entity_evidence / relationship_evidence   (source classification, excerpt, offsets)
  -> chunk                                      (breadcrumb, content, embedding)
  -> section                                    (number, heading, level, page range)
  -> document version                           (version number, SHA-256, declared metadata)
  -> document                                   (name, media type)
```

The Ask Architecture answer combines graph facts with source excerpts, document/version context, confidence, extraction type
and validation status. If the evidence is insufficient the system says so instead of inventing a claim.

The chain is real, queryable data. `Evaluation_Results/Screenshots/psql/p08_relationship_provenance_chain.png` shows the join
for `BrakeController`'s relationships: each row names the source document, the section number and the evidence excerpt, and
`p14_original_extraction_preserved.png` shows how a reviewer's correction is stored.

## Extracted facts are candidates, not approved facts

LLM extraction produces schema-valid **candidate** entities and relationships (the relationship type must belong to the
controlled taxonomy and both endpoints must resolve). Confidence is stored separately from validation state, and a high
confidence value never grants approval: in the demonstration run every explicitly stated entity and relationship had confidence 1.00 and every one still started
as `PENDING`. Confidence is a pure function of stored inputs (`raw_confidence` plus corroboration), so rebuilding the graph does
not inflate it.

| Validation state | Meaning |
| --- | --- |
| `PENDING` | Created by extraction/processing; waiting for review |
| `HUMAN_VERIFIED` | A reviewer verified the fact against its evidence |
| `HUMAN_CORRECTED` | A reviewer replaced the fact; the original row stays, marked as superseded |
| `REJECTED` | A reviewer rejected the fact with a reason; it no longer appears in answers, traversal or impact analysis |

Extraction type is stored too: `EXPLICIT` (stated in the text) or `INFERRED`; the evidence row carries the source
classification (`DIRECT_TEXT`, `TABLE`, `DIAGRAM`, `MULTI_SOURCE_INFERENCE`). Inferred facts are never shown as explicit.

## Review workflow

1. The reviewer opens the Review Queue (or clicks a node/edge in the graph) and inspects evidence, confidence, extraction type
   and history.
2. They **verify**, **edit** or **reject** the candidate and must give a reason for edit and reject.
3. A correction does **not** overwrite the AI candidate. A new `TRUSTED` fact is created; the original is kept and marked as
   superseded; relationships attached to it are carried over. Each decision is written to `validation_events` (state, actor,
   reason, time) and `audit_events`.
4. Project-level authorization limits review and retrieval to the right project.

Example from the recorded demonstration (`validation_events`):

| Action | Fact | Reason recorded |
| --- | --- | --- |
| Verify | `BrakeController REQUIRES WheelSpeedInterface` | Matches section 2 of the HLD |
| Verify | `WheelSpeedInterface CARRIES WheelSpeedSignal` | Confirmed against signal catalogue |
| Reject | `ESP` (FUNCTION) | Generic function name, duplicates the ESP_Module component |
| Edit | `Brake Controller Subsystem` COMPONENT → SOFTWARE_COMPONENT | The HLD defines it as a software component, not a generic component |

These decisions were made by the student while testing; they illustrate the workflow and are not a statement that the
remaining candidate facts have been validated.

## Entity resolution and potential inconsistencies

Names that refer to the same item are merged conservatively (blocking → guards → rules → LLM only for ambiguous pairs →
constrained Union-Find). A merge is a soft merge with an audit row in `entity_merges` and can be undone. The five
rule-based merges in the demonstration project joined type variants of the same name (`COMPONENT` / `SOFTWARE_COMPONENT`).

Findings are worded as prompts for review: *"Potential inconsistency detected: interface 'VehicleStateInterface' has no
provider relationship. It is used by BrakeController."* A dismissed finding stays dismissed across graph rebuilds.

## How to explain the graph in the demonstration

* Nodes are canonical, project-scoped AUTOSAR entities; edges are directed and use the controlled taxonomy (`REQUIRES`,
  `PROVIDES`, `USES`, `CONSUMES`, `CARRIES`, `PART_OF`, `DEPENDS_ON`, `IMPLEMENTED_BY`, …).
* Status is shown by colour **and** text: green = human verified, blue = explicit and pending, orange = inferred or lower
  confidence, red = rejected. The legend under the graph shows the counts.
* Clicking a node or edge opens the inspector: evidence passages with section and source classification, validation history,
  open findings, and the Verify / Edit / Reject controls.
