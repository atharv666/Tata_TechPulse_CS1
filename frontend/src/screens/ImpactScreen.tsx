import { useState, type FormEvent } from "react";
import { Select } from "../components/Select";
import { errorMessage, getAll, post } from "../api/client";
import { StatePanel } from "../components/StatePanel";
import { useApi } from "../hooks/useApi";
import { citationLabel, humanize, percent } from "../lib/format";
import type { Entity, ImpactAnalysis } from "../types/api";

export function ImpactScreen({ projectId }: { projectId: string }) {
  const entities = useApi(() => getAll<Entity>(`/projects/${projectId}/entities`), [projectId]);
  const [root, setRoot] = useState("");
  const [depth, setDepth] = useState(2);
  const [result, setResult] = useState<ImpactAnalysis>();
  const [error, setError] = useState<string>();
  const [loading, setLoading] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!root) return;
    setLoading(true);
    setError(undefined);
    try {
      setResult(
        await post<ImpactAnalysis>(`/projects/${projectId}/impact`, { root_entity_id: root, depth, node_limit: 100, edge_limit: 200 }),
      );
    } catch (reason) {
      setError(errorMessage(reason, "Impact analysis failed"));
    } finally {
      setLoading(false);
    }
  }

  return (
    <>
      <section className="card">
        <h2>Change impact analysis</h2>
        <p>Which elements could be affected if an entity changes? Results are potential impacts for an engineer to assess, each with the facts and source passages that connect it.</p>
        <form onSubmit={submit} className="impact-form">
          <div className="form-row">
            <label>
              Changed element
              <Select
                value={root}
                onChange={setRoot}
                placeholder="Select an entity…"
                options={(entities.data?.items ?? []).map((entity) => ({
                  value: entity.id,
                  label: entity.canonical_name,
                  hint: humanize(entity.entity_type),
                }))}
              />
            </label>
            <label>
              Hops
              <Select
                value={String(depth)}
                onChange={(value) => setDepth(Number(value))}
                options={[
                  { value: "1", label: "1 hop", hint: "direct dependents" },
                  { value: "2", label: "2 hops", hint: "indirect impact" },
                  { value: "3", label: "3 hops", hint: "extended chain" },
                ]}
              />
            </label>
            <button type="submit" disabled={loading}>
              {loading ? "Analysing…" : "Analyse impact"}
            </button>
          </div>
          {entities.data?.truncated && <small className="muted">Showing the first {entities.data.items.length} of {entities.data.total} entities; use the graph to find others.</small>}
        </form>
      </section>

      {error && <StatePanel kind="error">{error}</StatePanel>}

      {result && (
        <section className="card">
          <h2>Potentially affected by a change to {result.root_entity_name}</h2>
          {result.notes.map((note) => (
            <p className="muted" key={note}>
              {note}
            </p>
          ))}
          {result.truncated && <StatePanel kind="partial">The traversal reached its limits; results are partial.</StatePanel>}
          {Object.keys(result.summary).length > 0 && (
            <p className="impact-summary">
              {Object.entries(result.summary).map(([type, count]) => (
                <span className="chip" key={type}>
                  {count} × {type}
                </span>
              ))}
            </p>
          )}
          {result.affected_tests.length > 0 && (
            <p>
              <strong>Tests to re-run:</strong> {result.affected_tests.join(", ")}
            </p>
          )}
          {result.results.length ? (
            <div className="impact-results">
              {result.results.map((item) => (
                <article className="impact-card" key={item.affected_entity_id ?? item.via.join()}>
                  <div className="impact-header">
                    <strong className="impact-kind">{item.kind.replace("_", " ")}</strong>
                    <span className="impact-name">
                      {item.affected_entity_name ?? "Unknown"} ({item.affected_entity_type ?? "N/A"}) · {item.hops} hop{item.hops === 1 ? "" : "s"}
                    </span>
                  </div>
                  <div className="impact-meta">
                    <p>
                      <strong>Because:</strong> {item.via.join("  →  ")}
                    </p>
                    <p>
                      <strong>Weakest link:</strong> {percent(item.confidence)} · {item.extraction_type ?? "—"} · {item.validation_state ?? "—"}
                    </p>
                    {item.message && <p className="impact-msg">{item.message}</p>}
                    {item.source_evidence.map((evidence) => (
                      <details key={evidence.fact.fact_id} className="citation-details">
                        <summary>
                          {evidence.fact.source_entity} {evidence.fact.relationship_type} {evidence.fact.target_entity}
                        </summary>
                        {evidence.citations.map((citation) => (
                          <blockquote className="excerpt" key={citation.citation_id}>
                            <small>{citationLabel(citation)}</small>
                            <br />
                            {citation.excerpt}
                          </blockquote>
                        ))}
                      </details>
                    ))}
                  </div>
                </article>
              ))}
            </div>
          ) : (
            <StatePanel kind="empty">No dependent or related elements were found in the knowledge graph.</StatePanel>
          )}
        </section>
      )}
    </>
  );
}
