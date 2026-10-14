import { useMemo, useState } from "react";
import { Select } from "../components/Select";
import { download, errorMessage, getAll, post } from "../api/client";
import { Graph3D } from "../components/Graph3D";
import { GraphInspector, type Selection } from "../components/GraphInspector";
import { StatePanel } from "../components/StatePanel";
import { useApi } from "../hooks/useApi";
import { ENTITY_TYPES, humanize } from "../lib/format";
import { TONE_HEX, countByTone, filterEntities, toneLabel, visibleRelationships, type Tone } from "../lib/graphView";
import type { Entity, Job, Relationship } from "../types/api";

const STATES = ["PENDING", "HUMAN_VERIFIED", "HUMAN_CORRECTED", "REJECTED"];
const TONES: Tone[] = ["green", "blue", "orange", "red"];

export function GraphScreen({ projectId }: { projectId: string }) {
  const entities = useApi(() => getAll<Entity>(`/projects/${projectId}/entities`), [projectId]);
  const relationships = useApi(() => getAll<Relationship>(`/projects/${projectId}/relationships`), [projectId]);
  const [selection, setSelection] = useState<Selection>();
  const [filter, setFilter] = useState({ query: "", type: "", state: "" });
  const [building, setBuilding] = useState(false);
  const [buildMessage, setBuildMessage] = useState<string>();

  const nodes = useMemo(() => filterEntities(entities.data?.items ?? [], filter), [entities.data, filter]);
  const edges = useMemo(() => visibleRelationships(relationships.data?.items ?? [], nodes), [relationships.data, nodes]);
  const tones = useMemo(() => countByTone(nodes), [nodes]);

  async function build() {
    setBuilding(true);
    setBuildMessage(undefined);
    try {
      const job = await post<Job>(`/projects/${projectId}/graph-build`);
      setBuildMessage(`Graph build queued (${job.state}). It resolves duplicate names, binds relationships and refreshes findings; reload to see the result.`);
    } catch (reason) {
      setBuildMessage(errorMessage(reason, "Graph build could not be queued"));
    } finally {
      setBuilding(false);
    }
  }

  async function exportAs(format: "json" | "xlsx" | "csv", table = "entities") {
    try {
      const name = format === "xlsx" ? "architecture.xlsx" : format === "json" ? "architecture.json" : `${table}.csv`;
      await download(`/projects/${projectId}/export?format=${format}&table=${table}`, name);
      setBuildMessage(`Exported ${name} (rejected facts are left out).`);
    } catch (reason) {
      setBuildMessage(errorMessage(reason, "Export failed"));
    }
  }

  function reload() {
    entities.refresh();
    relationships.refresh();
  }

  if (entities.loading || relationships.loading) return <StatePanel kind="loading">Loading the architecture graph…</StatePanel>;
  if (entities.error || relationships.error) return <StatePanel kind="error">{(entities.error ?? relationships.error)?.message}</StatePanel>;
  if (!entities.data?.items.length) {
    return (
      <section className="card empty-graph">
        <h2>The knowledge graph has not been built yet</h2>
        <StatePanel kind="empty">
          No architecture facts exist for this project. Ingest a document (extraction and the graph build run automatically) or queue a build.
        </StatePanel>
        <button onClick={() => void build()} disabled={building}>{building ? "Queuing…" : "Build graph"}</button>
        {buildMessage && <p className="action-feedback">{buildMessage}</p>}
      </section>
    );
  }

  return (
    <div className="graph-page">
      <section className="graph-hero">
        <div>
          <h2>Explore the architecture</h2>
          <p>Click a node or relationship to inspect its source evidence, confidence and review state; verify, edit or reject it there.</p>
        </div>
        <div className="graph-actions">
          <input
            className="graph-search"
            value={filter.query}
            onChange={(event) => setFilter({ ...filter, query: event.target.value })}
            placeholder="Find a component, port, interface…"
          />
          <Select
            className="select-compact"
            value={filter.type}
            onChange={(type) => setFilter({ ...filter, type })}
            options={[{ value: "", label: "All types" }, ...ENTITY_TYPES.map((type) => ({ value: type, label: humanize(type) }))]}
          />
          <Select
            className="select-compact"
            value={filter.state}
            onChange={(state) => setFilter({ ...filter, state })}
            options={[{ value: "", label: "All review states" }, ...STATES.map((state) => ({ value: state, label: humanize(state) }))]}
          />
          <button className="btn-secondary" onClick={() => void build()} disabled={building}>{building ? "Queuing…" : "Rebuild graph"}</button>
          <Select
            className="select-compact"
            value=""
            placeholder="Export…"
            onChange={(value) => {
              const [format, table] = value.split(":");
              void exportAs(format as "json" | "xlsx" | "csv", table);
            }}
            options={[
              { value: "json:all", label: "JSON", hint: "everything, with sources" },
              { value: "xlsx:all", label: "Excel", hint: "one sheet per table" },
              { value: "csv:entities", label: "Entities CSV" },
              { value: "csv:relationships", label: "Relationships CSV" },
              { value: "csv:components", label: "Components CSV" },
            ]}
          />
        </div>
      </section>
      {buildMessage && <p className="action-feedback graph-feedback">{buildMessage}</p>}
      {(entities.data.truncated || relationships.data?.truncated) && (
        <StatePanel kind="partial">
          Showing the first {entities.data.items.length} of {entities.data.total} entities. Narrow the view with the filters.
        </StatePanel>
      )}
      <section className="graph-workspace">
        <div className="card graph-stage">
          <div className="graph-stage-top">
            <div>{nodes.length} nodes · {edges.length} relationships</div>
          </div>
          <Graph3D
            nodes={nodes}
            relationships={edges}
            onSelectEntity={(id) => setSelection({ kind: "entity", id })}
            onSelectRelationship={(id) => setSelection({ kind: "relationship", id })}
          />
          <ul className="graph-legend" aria-label="Legend: colour and text">
            {TONES.map((tone) => (
              <li key={tone}>
                <i className="legend-orb" style={{ background: TONE_HEX[tone] }} /> {toneLabel(tone)} <b>({tones[tone]})</b>
              </li>
            ))}
          </ul>
        </div>
        <GraphInspector projectId={projectId} selection={selection} onActionComplete={reload} />
      </section>
    </div>
  );
}
