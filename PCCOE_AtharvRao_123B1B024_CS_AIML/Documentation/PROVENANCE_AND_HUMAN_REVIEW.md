# Provenance-Based Architecture Knowledge and Human-in-the-Loop Review

## Why provenance is central

The application treats the source document as authoritative and the extracted graph as derived knowledge. A graph fact is not sufficient by itself for an engineering answer. Each entity or relationship is linked through evidence to:

```text
entity or directed relationship
  -> entity/relationship evidence
  -> chunk and excerpt
  -> section
  -> document version
  -> source document / page position where available
```

The Ask Architecture response therefore combines relational graph facts with source excerpts, document/version context, confidence, extraction type, validation status, and citations. If the evidence bundle is insufficient, the intended behavior is to say so rather than invent an architectural claim.

## Candidate facts are not automatically approved facts

LLM extraction produces schema-valid **candidate** entities and relationships. The application persists confidence separately from validation state. A high confidence value does not grant human approval.

Supported review states are:

| State | Meaning |
| --- | --- |
| `PENDING` | Candidate created by extraction or processing and awaiting review |
| `HUMAN_VERIFIED` | Reviewer has verified the fact against evidence |
| `HUMAN_CORRECTED` | Reviewer has created a corrected fact while preserving the original candidate |
| `REJECTED` | Reviewer has rejected the candidate with a reason |

## Review workflow

1. An engineer opens the review queue and inspects source evidence, confidence, extraction type, and provenance.
2. An authorized reviewer verifies, corrects, or rejects the candidate.
3. A correction does **not** overwrite the original AI candidate. The action, reviewer, timestamp, reason, and resulting fact are retained in validation/audit history.
4. Project-level authorization limits review and retrieval to the correct project.

This design supports engineering governance: the system assists analysis, while human reviewers remain responsible for acceptance of consequential architecture facts.

## How to explain the graph in the demonstration

- Nodes represent canonical, project-scoped AUTOSAR entities.
- Directed edges use a controlled relationship taxonomy such as `REQUIRES`, `PROVIDES`, `USES`, and `DEPENDS_ON`.
- Status is shown with text as well as color: green for human-verified, blue for explicit/pending, orange for inferred or lower-confidence, and red for rejected/conflict states.
- Clicking a node or edge should reveal its provenance and authorized review actions.
