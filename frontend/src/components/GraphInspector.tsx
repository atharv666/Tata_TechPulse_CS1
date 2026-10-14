import { useState } from "react";
import { Select } from "./Select";
import { errorMessage, get, post } from "../api/client";
import { useApi } from "../hooks/useApi";
import { ENTITY_TYPES, RELATIONSHIP_TYPES, humanize } from "../lib/format";
import { tone, toneLabel } from "../lib/graphView";
import type { EntityDetail, Finding, HistoryItem, Provenance, RelationshipDetail } from "../types/api";
import { StatePanel } from "./StatePanel";
import { StatusBadge } from "./StatusBadge";

export type Selection = { kind: "entity" | "relationship"; id: string } | undefined;

interface Props {
  projectId: string;
  selection: Selection;
  onActionComplete?: () => void;
}

export function GraphInspector({ projectId, selection, onActionComplete }: Props) {
  if (!selection) {
    return (
      <aside className="card inspector">
        <h2>Fact inspector</h2>
        <p className="inspector-empty">
          Select a node or a relationship on the canvas to see what the document says, where it says it, how sure the
          extraction is, and its review history.
        </p>
      </aside>
    );
  }
  return <Inspected key={`${selection.kind}:${selection.id}`} projectId={projectId} selection={selection} onActionComplete={onActionComplete} />;
}

function Inspected({ projectId, selection, onActionComplete }: Props & { selection: NonNullable<Selection> }) {
  const isEntity = selection.kind === "entity";
  const path = `/projects/${projectId}/${isEntity ? "entities" : "relationships"}/${selection.id}`;
  const detail = useApi(() => get<EntityDetail | RelationshipDetail>(path), [path]);
  const [reason, setReason] = useState("");
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState("");
  const [type, setType] = useState("");
  const [message, setMessage] = useState<string>();
  const [busy, setBusy] = useState(false);

  if (detail.loading) return <aside className="card inspector"><StatePanel kind="loading">Loading evidence…</StatePanel></aside>;
  if (detail.error || !detail.data) {
    return <aside className="card inspector"><StatePanel kind="error">{detail.error?.message ?? "Not found"}</StatePanel></aside>;
  }
  const fact = detail.data;
  const current = tone(fact);
  const pending = fact.validation_state === "PENDING";
  const replaced = Boolean(fact.superseded_by_id) || ("merged_into_id" in fact && Boolean(fact.merged_into_id));

  async function act(action: "verify" | "reject" | "correct") {
    if (action !== "verify" && !reason.trim()) {
      setMessage("A reason is required for this decision.");
      return;
    }
    setBusy(true);
    setMessage(undefined);
    try {
      const body =
        action === "correct"
          ? isEntity
            ? { canonical_name: name, entity_type: type, reason }
            : {
                source_entity_id: (fact as RelationshipDetail).source.id,
                target_entity_id: (fact as RelationshipDetail).target.id,
                relationship_type: type,
                reason,
              }
          : { reason: reason.trim() || null };
      await post(`${path}/${action}`, body);
      setMessage(`Done: ${action}. The original AI extraction is kept in the history.`);
      setEditing(false);
      onActionComplete?.();
      detail.refresh();
    } catch (reasonError) {
      setMessage(errorMessage(reasonError, "The review action failed"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <aside className="card inspector">
      <h2>Fact inspector</h2>
      <div className="inspector-header">
        <span className="fact-type-tag">{isEntity ? "ENTITY" : "RELATIONSHIP"}</span>
        <StatusBadge fact={fact} />
      </div>
      <p className={`tone-note tone-${current}`}>{toneLabel(current)}</p>

      {isEntity ? <EntityFacts entity={fact as EntityDetail} /> : <RelationshipFacts relationship={fact as RelationshipDetail} />}

      <FindingList findings={fact.findings} />
      <EvidenceList evidence={fact.evidence} />
      <History items={fact.history} />

      {pending && !replaced ? (
        <div className="inspector-actions">
          <h4>Review decision</h4>
          <label className="input-label">
            Reason (required to reject or edit)
            <input value={reason} onChange={(event) => setReason(event.target.value)} placeholder="Why?" />
          </label>
          {editing && (
            <div className="correction-form">
              {isEntity && <input value={name} onChange={(event) => setName(event.target.value)} placeholder="Corrected name" />}
              <Select
                value={type}
                onChange={setType}
                options={(isEntity ? ENTITY_TYPES : RELATIONSHIP_TYPES).map((option) => ({ value: option, label: humanize(option) }))}
              />
              <button disabled={busy} onClick={() => void act("correct")}>Save correction</button>
              <button className="btn-secondary" onClick={() => setEditing(false)}>Cancel</button>
            </div>
          )}
          <div className="action-buttons">
            <button className="btn-verify" disabled={busy} onClick={() => void act("verify")}>Verify</button>
            <button
              className="btn-secondary"
              disabled={busy}
              onClick={() => {
                setName(isEntity ? (fact as EntityDetail).canonical_name : "");
                setType(isEntity ? (fact as EntityDetail).entity_type : (fact as RelationshipDetail).relationship_type);
                setEditing(true);
              }}
            >
              Edit
            </button>
            <button className="danger" disabled={busy} onClick={() => void act("reject")}>Reject</button>
          </div>
        </div>
      ) : (
        <p className="muted">
          {replaced ? "This fact was merged into or replaced by another; review the live fact instead." : "This fact has already been reviewed."}
        </p>
      )}
      {message && <p className="action-feedback">{message}</p>}
    </aside>
  );
}

function EntityFacts({ entity }: { entity: EntityDetail }) {
  return (
    <div className="fact-details">
      <h3>{entity.canonical_name}</h3>
      <p><strong>Type:</strong> <code>{entity.entity_type}</code> · <strong>Relationships:</strong> {entity.relationship_count}</p>
      {entity.aliases.length > 0 && (
        <p><strong>Also known as:</strong> {entity.aliases.map((alias) => `${alias.alias} (${alias.source.toLowerCase()})`).join(", ")}</p>
      )}
      {entity.merged_entities.length > 0 && (
        <details>
          <summary>{entity.merged_entities.length} duplicate(s) merged into this entity</summary>
          <ul>
            {entity.merged_entities.map((merged) => (
              <li key={merged.merge_id}>
                {merged.name} — decided by {merged.decided_by}
                {merged.similarity !== null ? ` (similarity ${merged.similarity})` : ""}
                {merged.reason ? `: ${merged.reason}` : ""}
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}

function RelationshipFacts({ relationship }: { relationship: RelationshipDetail }) {
  return (
    <div className="fact-details">
      <h3>
        {relationship.source.name} <span className="rel-type">{relationship.relationship_type}</span> {relationship.target.name}
      </h3>
      <p>
        {relationship.source.entity_type} → {relationship.target.entity_type}
      </p>
    </div>
  );
}

function FindingList({ findings }: { findings: Finding[] }) {
  const open = findings.filter((finding) => finding.status === "OPEN");
  if (!open.length) return null;
  return (
    <div className="inspector-findings">
      <h4>Open findings</h4>
      <ul>
        {open.map((finding) => (
          <li key={finding.id}>[{finding.severity}] {finding.summary}</li>
        ))}
      </ul>
    </div>
  );
}

function EvidenceList({ evidence }: { evidence: Provenance[] }) {
  return (
    <div className="inspector-provenance">
      <h4>Evidence ({evidence.length})</h4>
      {evidence.length === 0 && <p className="no-provenance">No source evidence is linked to this fact.</p>}
      {evidence.map((item) => (
        <details key={item.chunk_id} className="review-provenance">
          <summary>
            {item.document_name} · <em>{item.section_heading}</em>
            {item.page_start ? ` · p. ${item.page_start}` : ""} · {item.source_classification}
          </summary>
          <blockquote className="evidence-excerpt">{item.excerpt}</blockquote>
        </details>
      ))}
    </div>
  );
}

function History({ items }: { items: HistoryItem[] }) {
  if (!items.length) return null;
  return (
    <details className="inspector-history">
      <summary>Validation history ({items.length})</summary>
      <ul>
        {items.map((item, index) => (
          <li key={index}>
            {item.state} by {item.actor_id}
            {item.reason ? ` — ${item.reason}` : ""}
          </li>
        ))}
      </ul>
    </details>
  );
}
