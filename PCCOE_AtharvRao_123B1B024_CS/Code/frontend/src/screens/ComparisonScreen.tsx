import { useState, type FormEvent } from "react";
import { Select } from "../components/Select";
import { errorMessage, get, getAll, getPage, post } from "../api/client";
import { StatePanel } from "../components/StatePanel";
import { useApi } from "../hooks/useApi";
import { groupChanges } from "../lib/findings";
import { citationLabel, humanize, percent } from "../lib/format";
import { isFinished, pollUntil } from "../lib/polling";
import type { ComparisonDetail, ComparisonFinding, Document, DocumentVersion, Job } from "../types/api";

const SCOPE_TITLES: Record<string, string> = {
  DOCUMENT: "Document",
  SECTION: "Sections",
  ENTITY: "Entities",
  RELATIONSHIP: "Relationships",
};

export function ComparisonScreen({ projectId }: { projectId: string }) {
  const documents = useApi(() => getPage<Document>(`/projects/${projectId}/documents`), [projectId]);
  const [documentId, setDocumentId] = useState("");
  const [versions, setVersions] = useState<DocumentVersion[]>([]);
  const [base, setBase] = useState("");
  const [target, setTarget] = useState("");
  const [status, setStatus] = useState<string>();
  const [running, setRunning] = useState(false);
  const [detail, setDetail] = useState<ComparisonDetail>();
  const [findings, setFindings] = useState<ComparisonFinding[]>([]);

  const versionOptions = versions.map((version) => ({
    value: version.id,
    label: `Version ${version.version_number}`,
    hint: version.source_label ?? undefined,
  }));

  async function chooseDocument(chosen: string) {
    setDocumentId(chosen);
    setVersions([]);
    if (!chosen) return;
    const page = await getPage<DocumentVersion>(`/projects/${projectId}/documents/${chosen}/versions`);
    setVersions(page.items);
    setBase(page.items[0]?.id ?? "");
    setTarget(page.items[page.items.length - 1]?.id ?? "");
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!base || !target) return;
    if (base === target) {
      setStatus("Choose two different versions to compare.");
      return;
    }
    setRunning(true);
    setFindings([]);
    setDetail(undefined);
    try {
      const queued = await post<Job>(`/projects/${projectId}/comparisons`, { base_version_id: base, target_version_id: target });
      const comparisonId = String((queued.details.payload as { comparison_id?: string } | undefined)?.comparison_id ?? "");
      setStatus("Comparing the two versions…");
      const finished = await pollUntil(
        () => get<ComparisonDetail>(`/projects/${projectId}/comparisons/${comparisonId}`),
        (value) => isFinished(value.state),
      );
      setDetail(finished);
      if (finished.state !== "COMPLETED") {
        setStatus(`The comparison ${finished.state.toLowerCase()}. See the job list for details.`);
        return;
      }
      const all = await getAll<ComparisonFinding>(`/projects/${projectId}/comparisons/${comparisonId}/findings`, 500);
      setFindings(all.items);
      setStatus(`${finished.finding_count} change(s) found. Differences are changes between revisions, not errors.`);
    } catch (reason) {
      setStatus(errorMessage(reason, "The comparison could not be completed"));
    } finally {
      setRunning(false);
    }
  }

  return (
    <section className="card">
      <h2>Revision comparison</h2>
      <p>Compare two versions of a document: what changed in its sections and values, and which entities and relationships were added, removed or altered, with the source passage from each version.</p>
      <form onSubmit={submit} className="comparison-form">
        <label>
          Document
          <Select
            value={documentId}
            onChange={(value) => void chooseDocument(value)}
            placeholder="Choose a document…"
            options={(documents.data?.items ?? []).map((document) => ({ value: document.id, label: document.name }))}
          />
        </label>
        {versions.length > 1 ? (
          <div className="form-row">
            <label>
              Base version
              <Select value={base} onChange={setBase} options={versionOptions} />
            </label>
            <label>
              Compared version
              <Select value={target} onChange={setTarget} options={versionOptions} />
            </label>
            <button type="submit" disabled={running}>{running ? "Comparing…" : "Compare"}</button>
          </div>
        ) : (
          versions.length === 1 && <StatePanel kind="empty">This document has one version; upload a revision to compare.</StatePanel>
        )}
      </form>
      {status && <StatePanel kind="partial">{status}</StatePanel>}
      {detail && Object.keys(detail.summary).length > 0 && (
        <p className="impact-summary">
          {Object.entries(detail.summary).map(([kind, count]) => (
            <span className="chip" key={kind}>{count} × {humanize(kind)}</span>
          ))}
        </p>
      )}
      {groupChanges(findings).map((group) => (
        <div key={group.scope} className="change-group">
          <h3>{SCOPE_TITLES[group.scope] ?? group.scope} ({group.items.length})</h3>
          {group.items.map((finding) => (
            <ChangeCard key={finding.id} finding={finding} />
          ))}
        </div>
      ))}
    </section>
  );
}

function ChangeCard({ finding }: { finding: ComparisonFinding }) {
  const { details } = finding;
  const changes = details.changes as {
    value_changes?: Array<{ old_values: string[]; new_values: string[]; old_statement: string; new_statement: string }>;
    removed?: string[];
    added?: string[];
  };
  return (
    <article className="impact-card">
      <div className="impact-header">
        <strong className={`sev sev-${details.severity.toLowerCase()}`}>{details.severity}</strong>
        <span className="impact-name">{details.summary}</span>
      </div>
      <div className="impact-meta">
        <p className="muted">
          {humanize(details.classification)} · confidence {percent(details.confidence)}
          {details.review_status !== "NOT_APPLICABLE" ? ` · ${details.review_status}` : ""}
        </p>
        {changes.value_changes?.map((change, index) => (
          <p key={index}>
            <strong>Value:</strong> {change.old_values.join(", ") || "—"} → {change.new_values.join(", ") || "—"}
            <br />
            <small className="muted">{change.old_statement} → {change.new_statement}</small>
          </p>
        ))}
        {changes.removed?.map((text) => <p key={text} className="removed">− {text}</p>)}
        {changes.added?.map((text) => <p key={text} className="added">+ {text}</p>)}
        {(["old_evidence", "new_evidence"] as const).map((side) =>
          details[side].citations.length ? (
            <details key={side} className="citation-details">
              <summary>{side === "old_evidence" ? "Source in the base version" : "Source in the compared version"}</summary>
              {details[side].citations.map((citation) => (
                <blockquote key={citation.citation_id} className="excerpt">
                  <small>{citationLabel(citation)}</small>
                  <br />
                  {citation.excerpt}
                </blockquote>
              ))}
            </details>
          ) : null,
        )}
        {details.impacts.length > 0 && (
          <details className="citation-details">
            <summary>Potentially affected ({details.impacts.length})</summary>
            <ul>
              {details.impacts.map((impact) => (
                <li key={impact.affected_entity_id ?? impact.via.join()}>
                  {impact.affected_entity_name} ({impact.affected_entity_type}) · {impact.hops} hop(s) · {impact.via.join(" → ")}
                </li>
              ))}
            </ul>
          </details>
        )}
      </div>
    </article>
  );
}
