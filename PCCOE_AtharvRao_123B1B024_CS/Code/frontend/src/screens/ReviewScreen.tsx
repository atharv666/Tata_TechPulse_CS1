import { useState } from "react";
import { Select } from "../components/Select";
import { errorMessage, getAll, post } from "../api/client";
import { StatePanel } from "../components/StatePanel";
import { StatusBadge } from "../components/StatusBadge";
import { useApi } from "../hooks/useApi";
import { ENTITY_TYPES, humanize } from "../lib/format";
import type { ReviewItem } from "../types/api";

export function ReviewScreen({ projectId }: { projectId: string }) {
  const queue = useApi(() => getAll<ReviewItem>(`/projects/${projectId}/review-queue`), [projectId]);
  const [reason, setReason] = useState("");
  const [correcting, setCorrecting] = useState<string>();
  const [name, setName] = useState("");
  const [type, setType] = useState<string>(ENTITY_TYPES[0]);
  const [message, setMessage] = useState<string>();

  const path = (item: ReviewItem) => `/projects/${projectId}/${item.fact_kind === "ENTITY" ? "entities" : "relationships"}/${item.fact_id}`;

  async function decide(item: ReviewItem, action: "verify" | "reject") {
    if (action === "reject" && !reason.trim()) {
      setMessage("A reason is required to reject a fact.");
      return;
    }
    try {
      await post(`${path(item)}/${action}`, { reason: reason.trim() || null });
      setMessage(`${action === "verify" ? "Verified" : "Rejected"}: ${item.label}`);
      queue.refresh();
    } catch (reasonError) {
      setMessage(errorMessage(reasonError, `${action} failed`));
    }
  }

  async function correct(item: ReviewItem) {
    if (!reason.trim()) {
      setMessage("A reason is required to correct a fact.");
      return;
    }
    try {
      await post(`${path(item)}/correct`, { canonical_name: name, entity_type: type, reason });
      setMessage(`Corrected: ${item.label}. The original extraction stays in the history.`);
      setCorrecting(undefined);
      queue.refresh();
    } catch (reasonError) {
      setMessage(errorMessage(reasonError, "Correction failed"));
    }
  }

  if (queue.loading) return <StatePanel kind="loading">Loading review candidates…</StatePanel>;
  if (queue.error) return <StatePanel kind="error">{queue.error.message}</StatePanel>;

  return (
    <section className="card">
      <h2>Human review queue</h2>
      <p>
        Every AI-extracted fact starts as PENDING. Inspect its source passage, then verify, edit or reject it. Your
        decision is recorded with the reason; the original extraction is never overwritten.
      </p>
      <label className="input-label">
        Reason for your decision
        <input value={reason} onChange={(event) => setReason(event.target.value)} placeholder="Required to reject or edit" />
      </label>
      {message && <StatePanel kind="partial">{message}</StatePanel>}
      {queue.data?.truncated && <small className="muted">Showing the first {queue.data.items.length} of {queue.data.total}.</small>}

      {queue.data?.items.length ? (
        <div className="review-list">
          {queue.data.items.map((item) => (
            <article className="review-card" key={item.fact_id}>
              <div className="review-main">
                <div className="review-header">
                  <strong>{item.label}</strong>
                  <StatusBadge fact={item} />
                </div>
                <p className="review-meta">{item.fact_kind === "ENTITY" ? "Entity" : "Relationship"}</p>
                {item.provenance.length === 0 && <p className="no-provenance">No source evidence is linked to this fact.</p>}
                {item.provenance.map((source) => (
                  <details key={source.chunk_id} className="review-provenance">
                    <summary>
                      {source.document_name} · <em>{source.section_heading}</em>
                      {source.page_start ? ` · p. ${source.page_start}` : ""}
                    </summary>
                    <blockquote>{source.excerpt}</blockquote>
                  </details>
                ))}
                {correcting === item.fact_id && (
                  <div className="correction-form">
                    <h4>Correct this entity</h4>
                    <input value={name} onChange={(event) => setName(event.target.value)} placeholder="Corrected name" />
                    <Select value={type} onChange={setType} options={ENTITY_TYPES.map((option) => ({ value: option, label: humanize(option) }))} />
                    <div className="action-buttons">
                      <button onClick={() => void correct(item)}>Save correction</button>
                      <button className="btn-secondary" onClick={() => setCorrecting(undefined)}>Cancel</button>
                    </div>
                  </div>
                )}
              </div>
              <div className="review-actions">
                <button onClick={() => void decide(item, "verify")}>Verify</button>
                {item.fact_kind === "ENTITY" && (
                  <button
                    className="btn-secondary"
                    onClick={() => {
                      setCorrecting(item.fact_id);
                      setName(item.label.replace(/ \[[A-Z_]+\]$/, ""));
                    }}
                  >
                    Edit
                  </button>
                )}
                <button className="danger" onClick={() => void decide(item, "reject")}>Reject</button>
              </div>
            </article>
          ))}
        </div>
      ) : (
        <StatePanel kind="empty">Nothing is waiting for review.</StatePanel>
      )}
    </section>
  );
}
