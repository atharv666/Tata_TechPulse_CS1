import { useState, type FormEvent } from "react";
import { Select } from "../components/Select";
import { errorMessage, post } from "../api/client";
import { StatePanel } from "../components/StatePanel";
import { citationLabel, percent, statusText } from "../lib/format";
import type { Answer } from "../types/api";

const MODES: Array<[string, string, string]> = [
  ["HYBRID", "Hybrid", "Graph facts and source passages together"],
  ["GRAPH", "Graph only", "Structural facts, each tied to its source passage"],
  ["SOURCE", "Source only", "Document passages only"],
];

export function AskScreen({ projectId, onOpenGraph }: { projectId: string; onOpenGraph: () => void }) {
  const [question, setQuestion] = useState("");
  const [mode, setMode] = useState("HYBRID");
  const [answer, setAnswer] = useState<Answer>();
  const [error, setError] = useState<string>();
  const [loading, setLoading] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!question.trim()) return;
    setLoading(true);
    setError(undefined);
    try {
      // The selected mode is part of the request: it decides which retrieval layers run.
      setAnswer(await post<Answer>(`/projects/${projectId}/query`, { query: question, mode }));
    } catch (reason) {
      setError(errorMessage(reason, "Query failed"));
    } finally {
      setLoading(false);
    }
  }

  return (
    <>
      <section className="card query">
        <form onSubmit={submit}>
          <label>
            Ask a project-specific architecture question
            <textarea
              value={question}
              onChange={(event) => setQuestion(event.target.value)}
              placeholder="e.g. What does BrakeController require? What could be affected if WheelSpeedInterface changes?"
              rows={3}
              maxLength={4000}
              required
            />
          </label>
          <div className="form-row">
            <label>
              Retrieval mode
              <Select value={mode} onChange={setMode} options={MODES.map(([value, label, hint]) => ({ value, label, hint }))} />
            </label>
            <button type="submit" disabled={loading}>
              {loading ? "Retrieving evidence…" : "Ask Architecture"}
            </button>
          </div>
        </form>
      </section>
      {error && <StatePanel kind="error">{error}</StatePanel>}
      {answer && <AnswerPanel answer={answer} requestedMode={mode} onOpenGraph={onOpenGraph} />}
    </>
  );
}

export function AnswerPanel({
  answer,
  requestedMode,
  onOpenGraph,
}: {
  answer: Answer;
  requestedMode?: string;
  onOpenGraph?: () => void;
}) {
  const citationNumber = new Map(answer.citations.map((citation, index) => [citation.citation_id, index + 1]));
  const modeNote =
    requestedMode && answer.mode && requestedMode !== answer.mode
      ? `Answered in ${answer.mode} mode (you asked for ${requestedMode}).`
      : undefined;

  return (
    <section className="answer">
      <div className="answer-header">
        <span className="eyebrow">
          {answer.status.replace("_", " ")}
          {answer.mode ? ` · ${answer.mode}` : ""}
        </span>
        {answer.confidence !== undefined && answer.confidence !== null && (
          <span className="confidence-pill" title={answer.confidence_basis}>
            Groundedness {percent(answer.confidence)}
          </span>
        )}
      </div>
      <h2>Grounded architectural answer</h2>
      {modeNote && <p className="mode-note">{modeNote}</p>}

      {answer.insufficient_evidence ? (
        <StatePanel kind="partial">
          <strong>Insufficient evidence.</strong> {answer.summary}
        </StatePanel>
      ) : (
        <p className="summary">{answer.summary}</p>
      )}
      {answer.confidence_basis && <p className="confidence-basis">{answer.confidence_basis}</p>}

      {answer.claims.length > 0 && (
        <div className="claims-section">
          <h3>Claims</h3>
          {answer.claims.map((claim, index) => (
            <article className="claim-card" key={`${claim.text}-${index}`}>
              <span className={`claim-tag ${claim.extraction_type.toLowerCase()}`}>{claim.extraction_type}</span>
              <p className="claim-text">
                {claim.text}{" "}
                {claim.citation_ids.map((id) => (
                  <a key={id} className="cite-marker" href={`#cite-${citationNumber.get(id)}`}>
                    [{citationNumber.get(id) ?? "?"}]
                  </a>
                ))}
              </p>
              {claim.support !== undefined && claim.support !== null && (
                <small className="muted">Verified against the cited text · support {percent(claim.support)}</small>
              )}
            </article>
          ))}
        </div>
      )}

      {answer.graph_facts && answer.graph_facts.length > 0 && (
        <div className="graph-facts">
          <h3>Graph facts</h3>
          <table className="data-table">
            <thead>
              <tr>
                <th>Fact</th>
                <th>Status</th>
                <th>Sources</th>
              </tr>
            </thead>
            <tbody>
              {answer.graph_facts.map((fact) => (
                <tr key={fact.fact_id}>
                  <td>
                    {fact.source_entity} <strong>{fact.relationship_type}</strong> {fact.target_entity}
                  </td>
                  <td>{statusText(fact)}</td>
                  <td>{fact.citation_ids.map((id) => `[${citationNumber.get(id) ?? "—"}]`).join(" ")}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {answer.graph_paths && answer.graph_paths.length > 0 && onOpenGraph && (
            <button className="btn-secondary" onClick={onOpenGraph}>
              Open the graph →
            </button>
          )}
        </div>
      )}

      {answer.related_findings && answer.related_findings.length > 0 && (
        <StatePanel kind="partial">
          <strong>Open findings about what this answer relies on</strong>
          <ul>
            {answer.related_findings.map((finding) => (
              <li key={finding.id}>
                [{finding.severity}] {finding.summary}
              </li>
            ))}
          </ul>
        </StatePanel>
      )}

      {answer.citations.length > 0 && (
        <div className="citations-section">
          <h3>Source evidence</h3>
          {answer.citations.map((citation, index) => (
            <details key={citation.citation_id} id={`cite-${index + 1}`} className="citation-details">
              <summary>
                <strong>[{index + 1}]</strong> {citationLabel(citation)}
              </summary>
              <blockquote className="excerpt">{citation.excerpt}</blockquote>
            </details>
          ))}
        </div>
      )}

      {answer.conflicts.length > 0 && (
        <StatePanel kind="partial">
          <strong>Potential conflicts:</strong> {answer.conflicts.join(" ")}
        </StatePanel>
      )}

      <div className="limitations-section">
        <h4>Limitations</h4>
        <ul>
          {(answer.limitations?.length ? answer.limitations : ["Only cited source evidence supports these statements."]).map(
            (item) => (
              <li key={item}>{item}</li>
            ),
          )}
        </ul>
        {answer.dropped_claims ? (
          <p className="muted">{answer.dropped_claims} generated statement(s) were removed because the cited text did not support them.</p>
        ) : null}
      </div>
    </section>
  );
}
