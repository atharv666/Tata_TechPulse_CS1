import { useState } from "react";
import { StatusBadge } from "./StatusBadge";
import { post } from "../api/client";
import type { Entity, Relationship } from "../types/api";

interface Props {
  projectId: string;
  selectedItem?: Entity | Relationship;
  onActionComplete?: () => void;
}

export function GraphInspector({ projectId, selectedItem, onActionComplete }: Props) {
  const [reason, setReason] = useState("Human verification via graph inspector");
  const [msg, setMsg] = useState<string>();
  const [submitting, setSubmitting] = useState(false);

  if (!selectedItem) {
    return (
      <aside className="card inspector">
        <h2>Fact Inspector</h2>
        <div className="inspector-empty">
          <p>Select any node (Entity) or edge (Relationship) on the knowledge graph canvas to inspect structural details, provenance, and validation status.</p>
        </div>
      </aside>
    );
  }

  const isEntity = "canonical_name" in selectedItem;

  async function handleReview(action: "verify" | "reject") {
    if (!selectedItem) return;
    setSubmitting(true);
    setMsg(undefined);
    try {
      const endpoint = isEntity
        ? `/projects/${projectId}/entities/${selectedItem.id}/${action}`
        : `/projects/${projectId}/relationships/${selectedItem.id}/${action}`;
      await post(endpoint, { reason });
      setMsg(`Action '${action}' submitted successfully.`);
      if (onActionComplete) onActionComplete();
    } catch (err) {
      setMsg(err instanceof Error ? err.message : "Review action failed");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <aside className="card inspector">
      <h2>Fact Inspector</h2>
      <div className="inspector-content">
        <div className="inspector-header">
          <span className="fact-type-tag">{isEntity ? "ENTITY NODE" : "RELATIONSHIP EDGE"}</span>
          <StatusBadge fact={selectedItem} />
        </div>

        {isEntity ? (
          <div className="fact-details">
            <h3>{selectedItem.canonical_name}</h3>
            <p><strong>Type:</strong> <code>{selectedItem.entity_type}</code></p>
            <p><strong>Trust State:</strong> {selectedItem.trust_state}</p>
            <p><strong>Confidence:</strong> {Math.round(selectedItem.confidence * 100)}%</p>
            {selectedItem.aliases && selectedItem.aliases.length > 0 && (
              <p><strong>Aliases:</strong> {selectedItem.aliases.join(", ")}</p>
            )}
          </div>
        ) : (
          <div className="fact-details">
            <h3>{selectedItem.relationship_type}</h3>
            <p><strong>Source Entity ID:</strong> <code>{selectedItem.source_entity_id}</code></p>
            <p><strong>Target Entity ID:</strong> <code>{selectedItem.target_entity_id}</code></p>
            <p><strong>Trust State:</strong> {selectedItem.trust_state}</p>
            <p><strong>Confidence:</strong> {Math.round(selectedItem.confidence * 100)}%</p>
          </div>
        )}

        <div className="inspector-provenance">
          <h4>Evidence & Provenance</h4>
          {selectedItem.evidence_excerpt ? (
            <blockquote className="evidence-excerpt">{selectedItem.evidence_excerpt}</blockquote>
          ) : (
            <p className="no-provenance">
              Linked source document evidence is accessible via the Review Queue and Cited Query evidence bundles.
            </p>
          )}
        </div>

        <div className="inspector-actions">
          <h4>Review Decisions</h4>
          <label className="input-label">
            Reviewer Note/Reason
            <input
              type="text"
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              placeholder="Reason for verification or rejection..."
            />
          </label>
          <div className="action-buttons">
            <button
              className="btn-verify"
              disabled={submitting}
              onClick={() => void handleReview("verify")}
            >
              Verify Fact
            </button>
            <button
              className="btn-reject danger"
              disabled={submitting}
              onClick={() => void handleReview("reject")}
            >
              Reject Fact
            </button>
          </div>
          {msg && <p className="action-feedback">{msg}</p>}
        </div>
      </div>
    </aside>
  );
}

