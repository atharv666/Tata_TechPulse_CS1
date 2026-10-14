import { useState } from "react";
import { Select } from "../components/Select";
import { errorMessage, getAll, post, withParams } from "../api/client";
import { StatePanel } from "../components/StatePanel";
import { useApi } from "../hooks/useApi";
import { humanize } from "../lib/format";
import { orderGraphFindings } from "../lib/findings";
import type { Finding } from "../types/api";

const TYPES = [
  "MISSING_PROVIDER",
  "MISSING_ENTITY_DEFINITION",
  "DANGLING_RELATIONSHIP",
  "POSSIBLE_DUPLICATE",
  "CONFLICTING_DECLARATION",
  "INCONSISTENT_RELATIONSHIP_TYPE",
  "UNRESOLVED_ALIAS",
];

export function FindingsScreen({ projectId }: { projectId: string }) {
  const [status, setStatus] = useState("OPEN");
  const [type, setType] = useState("");
  const findings = useApi(
    () => getAll<Finding>(withParams(`/projects/${projectId}/findings`, { status, finding_type: type })),
    [projectId, status, type],
  );
  const [reason, setReason] = useState("");
  const [message, setMessage] = useState<string>();

  async function act(finding: Finding, action: "dismiss" | "reopen") {
    if (action === "dismiss" && reason.trim().length < 3) {
      setMessage("Give a reason (at least a few words) to dismiss a finding.");
      return;
    }
    try {
      await post(`/projects/${projectId}/findings/${finding.id}/${action}`, action === "dismiss" ? { reason } : undefined);
      setMessage(action === "dismiss" ? "Dismissed. It stays dismissed across rebuilds." : "Reopened.");
      findings.refresh();
    } catch (reasonError) {
      setMessage(errorMessage(reasonError, `${action} failed`));
    }
  }

  return (
    <section className="card">
      <h2>Potential inconsistencies</h2>
      <p>
        These are prompts for engineering review, not verdicts: the system points at facts that look unusual and shows
        why. Dismiss what is intentional (with a reason); it will not come back.
      </p>
      <div className="form-row">
        <label>
          Status
          <Select
            value={status}
            onChange={setStatus}
            options={[
              { value: "OPEN", label: "Open" },
              { value: "DISMISSED", label: "Dismissed" },
              { value: "RESOLVED", label: "Resolved automatically" },
              { value: "", label: "All" },
            ]}
          />
        </label>
        <label>
          Kind
          <Select
            value={type}
            onChange={setType}
            options={[{ value: "", label: "All kinds" }, ...TYPES.map((kind) => ({ value: kind, label: humanize(kind) }))]}
          />
        </label>
        <label>
          Reason (to dismiss)
          <input value={reason} onChange={(event) => setReason(event.target.value)} />
        </label>
      </div>
      {message && <StatePanel kind="partial">{message}</StatePanel>}
      {findings.loading && <StatePanel kind="loading">Loading findings…</StatePanel>}
      {findings.error && <StatePanel kind="error">{findings.error.message}</StatePanel>}
      {findings.data && !findings.data.items.length && <StatePanel kind="empty">No findings match.</StatePanel>}
      {findings.data &&
        orderGraphFindings(findings.data.items).map((finding) => (
          <article className="impact-card" key={finding.id}>
            <div className="impact-header">
              <strong className={`sev sev-${finding.severity.toLowerCase()}`}>{finding.severity}</strong>
              <span className="impact-name">{humanize(finding.finding_type)} · {finding.status}</span>
            </div>
            <div className="impact-meta">
              <p>{finding.summary}</p>
              {finding.dismissed_reason && (
                <p className="muted">Dismissed by {finding.dismissed_by}: {finding.dismissed_reason}</p>
              )}
              <div className="action-buttons">
                {finding.status === "OPEN" && <button className="btn-secondary" onClick={() => void act(finding, "dismiss")}>Dismiss</button>}
                {finding.status === "DISMISSED" && <button className="btn-secondary" onClick={() => void act(finding, "reopen")}>Reopen</button>}
              </div>
            </div>
          </article>
        ))}
    </section>
  );
}
