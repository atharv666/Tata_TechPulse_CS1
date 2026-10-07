import { FormEvent, useMemo, useState } from "react";
import { getPage, post } from "./api/client";
import { DocumentManager } from "./components/DocumentDetail";
import { GraphInspector } from "./components/GraphInspector";
import { Graph3D } from "./components/Graph3D";
import { StatePanel } from "./components/StatePanel";
import { StatusBadge } from "./components/StatusBadge";
import { useApi } from "./hooks/useApi";
import type {
  Answer,
  AuditEvent,
  ComparisonFinding,
  Document,
  DocumentVersion,
  Entity,
  ImpactAnalysis,
  Job,
  Project,
  Relationship,
  ReviewItem,
} from "./types/api";
import "./workspace.css";

type Screen =
  | "dashboard"
  | "documents"
  | "ask"
  | "graph"
  | "impact"
  | "review"
  | "comparison"
  | "audit";

const navigation: Array<[Screen, string]> = [
  ["dashboard", "Dashboard"],
  ["documents", "Documents"],
  ["ask", "Ask Architecture"],
  ["graph", "Knowledge Graph"],
  ["impact", "Impact Analysis"],
  ["review", "Review Queue"],
  ["comparison", "Revision Comparison"],
  ["audit", "Audit"],
];

export function App() {
  const projects = useApi(() => getPage<Project>("/projects"), []);
  const [screen, setScreen] = useState<Screen>("dashboard");
  const [projectId, setProjectId] = useState<string>();

  const selected = projectId ?? projects.data?.items[0]?.id;

  if (projects.loading) {
    return <StatePanel kind="loading">Loading engineering workspace…</StatePanel>;
  }
  if (projects.error) {
    return (
      <StatePanel kind="error">
        Unable to load projects: {projects.error.message}
      </StatePanel>
    );
  }
  if (!selected) {
    return (
      <main className="onboarding">
        <h1>No Accessible Projects</h1>
        <p>Create a project through the backend API, then refresh this workspace.</p>
        <button onClick={projects.refresh}>Refresh Projects</button>
      </main>
    );
  }

  return (
    <div className="shell">
      <aside className="rail">
        <div className="brand">
          <b>A</b>
          <span>
            AUTOSAR
            <br />
            INTELLIGENCE
          </span>
        </div>
        <label className="project-label">
          PROJECT CONTEXT
          <select
            value={selected}
            onChange={(event) => setProjectId(event.target.value)}
          >
            {projects.data?.items.map((project) => (
              <option key={project.id} value={project.id}>
                {project.name}
              </option>
            ))}
          </select>
        </label>
        <nav>
          {navigation.map(([key, label]) => (
            <button
              key={key}
              className={screen === key ? "nav-current" : ""}
              onClick={() => setScreen(key)}
            >
              {label}
            </button>
          ))}
        </nav>
        <p className="rail-note">
          Evidence-linked engineering workspace
          <br />
          <span>Development Identity Boundary Active</span>
        </p>
      </aside>

      <main className="workspace">
        <header>
          <div>
            <p className="eyebrow">AUTOSAR Architecture Intelligence</p>
            <h1>{navigation.find(([key]) => key === screen)?.[1]}</h1>
          </div>
          <span className="live">● Backend Connected</span>
        </header>

        {screen === "dashboard" && (
          <Dashboard projectId={selected} onNavigate={setScreen} />
        )}
        {screen === "documents" && <DocumentManager projectId={selected} />}
        {screen === "ask" && <AskArchitecture projectId={selected} onOpenGraph={() => setScreen("graph")} />}
        {screen === "graph" && <GraphExplorer projectId={selected} />}
        {screen === "impact" && <ImpactAnalysisView projectId={selected} />}
        {screen === "review" && <ReviewQueueView projectId={selected} />}
        {screen === "comparison" && <ComparisonView projectId={selected} />}
        {screen === "audit" && <AuditView projectId={selected} />}
      </main>
    </div>
  );
}

function Dashboard({
  projectId,
  onNavigate,
}: {
  projectId: string;
  onNavigate: (screen: Screen) => void;
}) {
  const entities = useApi(() => getPage<Entity>(`/projects/${projectId}/entities`), [projectId]);
  const documents = useApi(() => getPage<Document>(`/projects/${projectId}/documents`), [projectId]);
  const jobs = useApi(() => getPage<Job>(`/projects/${projectId}/jobs`), [projectId]);
  const review = useApi(() => getPage<ReviewItem>(`/projects/${projectId}/review-queue`), [projectId]);
  const [answerMode, setAnswerMode] = useState("HYBRID");
  const cards = [
    ["Documents", documents.data?.total ?? "—", "documents", "Source library"],
    ["Graph nodes", entities.data?.total ?? "—", "graph", "Connected facts"],
    ["Pending reviews", review.data?.total ?? "—", "review", "Human decisions"],
    ["Processing jobs", jobs.data?.total ?? "—", "audit", "Pipeline activity"],
  ] as const;

  return (
    <div className="home-page">
      <section className="welcome-panel">
        <div className="welcome-copy">
          <div className="section-kicker">AUTOSAR architecture intelligence</div>
          <h2>Hi, Engineer. <span>Welcome to GraphMind.</span></h2>
          <p>Turn complex HLD documents into a connected, evidence-backed view of your architecture. Find the facts, relationships, and dependencies that matter without losing the source context behind them.</p>
          <div className="welcome-actions"><button onClick={() => onNavigate("ask")}>Find answers <span>→</span></button><button className="btn-secondary" onClick={() => onNavigate("documents")}>Ingest a document</button></div>
        </div>
        <div className="welcome-visual"><div className="signal-orbit orbit-one" /><div className="signal-orbit orbit-two" /><div className="signal-core"><strong>{entities.data?.total ?? "—"}</strong><span>connected facts</span></div><div className="visual-caption">Grounded in your project documents</div></div>
      </section>
      <section className="home-section-heading"><div><div className="section-kicker">Project at a glance</div><h3>Architecture workspace</h3></div><span className="workspace-status">● Workspace ready</span></section>
      <section className="metrics home-metrics">
        {cards.map(([label, value, target, caption]) => <button className="metric" key={label} onClick={() => onNavigate(target as Screen)}><span>{label}</span><strong>{value}</strong><small>{caption} <b>→</b></small></button>)}
      </section>
      <section className="home-grid">
        <article className="card action-card"><div className="action-icon answer-icon">⌕</div><div><div className="section-kicker">Ask the architecture</div><h3>Get an evidence-backed answer</h3><p>Ask about components, interfaces, signals, dependencies, flows, or impact. Every answer can be traced back to graph facts and source citations.</p><button onClick={() => onNavigate("ask")}>Open Ask Architecture →</button></div></article>
        <article className="card action-card"><div className="action-icon ingest-icon">↥</div><div><div className="section-kicker">Build your knowledge base</div><h3>Ingest an HLD document</h3><p>Upload a PDF or supported source and let GraphMind extract structure, entities, relationships, provenance, and reviewable facts.</p><div className="ingest-options"><label>Preferred answer method<select value={answerMode} onChange={(event) => setAnswerMode(event.target.value)}><option value="HYBRID">Graph + source evidence</option><option value="GRAPH">Graph traversal only</option><option value="SOURCE">Source retrieval only</option></select></label><button className="btn-secondary" onClick={() => onNavigate("documents")}>Open ingestion →</button></div></div></article>
      </section>
      <section className="card home-principles"><div><div className="section-kicker">Designed for engineering decisions</div><h3>One workspace. Three perspectives.</h3></div><div className="principle-list"><div><b>01</b><span><strong>Ask</strong> questions in plain language.</span></div><div><b>02</b><span><strong>Explore</strong> the connected architecture.</span></div><div><b>03</b><span><strong>Verify</strong> every finding against evidence.</span></div></div></section>
    </div>
  );
}

function AskArchitecture({ projectId, onOpenGraph }: { projectId: string; onOpenGraph: (nodeId?: string) => void }) {
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
      const res = await post<Answer>(`/projects/${projectId}/query`, {
        query: question,
        top_k: mode === "SOURCE" ? 12 : 8,
      });
      setAnswer(res);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Query failed");
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
              placeholder="e.g. What components consume WheelSpeedInterface? Or what interfaces are affected if BrakeController changes?"
              rows={3}
              required
            />
          </label>
          <div className="form-row">
            <label>
              Retrieval Mode
              <select value={mode} onChange={(event) => setMode(event.target.value)}>
                <option value="HYBRID">HYBRID (Graph + Source Vector)</option>
                <option value="GRAPH">GRAPH ONLY (Structural Traversal)</option>
                <option value="SOURCE">SOURCE ONLY (Vector Excerpts)</option>
              </select>
            </label>
            <button type="submit" disabled={loading}>
              {loading ? "Retrieving evidence..." : "Ask Architecture"}
            </button>
          </div>
        </form>
      </section>

      {error && <StatePanel kind="error">{error}</StatePanel>}
      {answer && <AnswerPanel answer={answer} onOpenGraph={() => onOpenGraph(answer.graph_paths?.[0]?.entity_ids?.[0])} />}
      {answer && answer.graph_paths && answer.graph_paths.length > 0 && <button className="answer-graph-link" onClick={() => onOpenGraph(answer.graph_paths?.[0]?.entity_ids?.[0])}>Open the cited path in the 3D graph →</button>}
    </>
  );
}

function AnswerPanel({ answer, onOpenGraph }: { answer: Answer; onOpenGraph?: () => void }) {
  return (
    <section className="answer">
      <div className="answer-header">
        <span className="eyebrow">{answer.status}</span>
        {answer.confidence !== undefined && (
          <span className="confidence-pill">
            Confidence: {Math.round(answer.confidence * 100)}%
          </span>
        )}
      </div>

      <h2>Grounded Architectural Answer</h2>

      {answer.insufficient_evidence ? (
        <StatePanel kind="partial">
          <strong>Insufficient Evidence:</strong> {answer.summary}
        </StatePanel>
      ) : (
        <p className="summary">{answer.summary}</p>
      )}

      {answer.claims && answer.claims.length > 0 && (
        <div className="claims-section">
          <h3>Architectural Claims</h3>
          {answer.claims.map((claim, index) => (
            <article className="claim-card" key={`${claim.text}-${index}`}>
              <div className="claim-header">
                <span className={`claim-tag ${claim.extraction_type.toLowerCase()}`}>
                  {claim.extraction_type}
                </span>
              </div>
              <p className="claim-text">{claim.text}</p>
              {claim.citation_ids.length > 0 && (
                <small className="citation-refs">
                  Cited Evidence IDs: {claim.citation_ids.join(", ")}
                </small>
              )}
            </article>
          ))}
        </div>
      )}

      {answer.citations && answer.citations.length > 0 && (
        <div className="citations-section">
          <h3>Cited Source Evidence & Excerpts</h3>
          {answer.citations.map((cit) => (
            <details key={cit.citation_id} className="citation-details">
              <summary>
                <strong>{cit.document_name}</strong> · Section: <em>{cit.section_heading}</em>
                {cit.page_start !== null ? ` (Page ${cit.page_start})` : ""}
              </summary>
              <div className="citation-body">
                <p className="cit-id">Citation ID: <code>{cit.citation_id}</code></p>
                <blockquote className="excerpt">{cit.excerpt}</blockquote>
              </div>
            </details>
          ))}
        </div>
      )}

      {answer.graph_paths && answer.graph_paths.length > 0 && (
        <div className="paths-section"><div className="answer-path-callout"><span className="path-icon">✦</span><div><strong>Answer anchored in the knowledge graph</strong><p>Trace this response back to the connected entities and relationships that support it.</p></div><button className="btn-secondary" onClick={onOpenGraph}>View in 3D</button></div>
          <h3>Graph Traversal Paths</h3>
          {answer.graph_paths.map((path, idx) => (
            <div className="path-card" key={idx}>
              <code>Path {idx + 1}: {path.entity_ids.join(" → ")}</code>
            </div>
          ))}
        </div>
      )}

      {answer.conflicts && answer.conflicts.length > 0 && (
        <StatePanel kind="partial">
          <strong>Potential Conflicts Detected:</strong> {answer.conflicts.join(" ")}
        </StatePanel>
      )}

      <div className="limitations-section">
        <h4>Evidence & Governance Limitations</h4>
        <p>
          {answer.insufficient_evidence
            ? "Evidence retrieval was insufficient to confirm full architecture validity."
            : answer.limitations
            ? answer.limitations.join(" ")
            : "Only cited source evidence supports these statements. Inferred claims require human engineering verification."}
        </p>
      </div>
    </section>
  );
}

function GraphExplorer({ projectId }: { projectId: string }) {
  const entities = useApi(() => getPage<Entity>(`/projects/${projectId}/entities`), [projectId]);
  const relationships = useApi(() => getPage<Relationship>(`/projects/${projectId}/relationships`), [projectId]);
  const [selected, setSelected] = useState<Entity | Relationship>();
  const [building, setBuilding] = useState(false);
  const [buildMsg, setBuildMsg] = useState<string>();
  const [search, setSearch] = useState("");

  const nodes = entities.data?.items ?? [];
  const edges = relationships.data?.items ?? [];
  const filteredNodes = useMemo(() => {
    const query = search.trim().toLowerCase();
    return query ? nodes.filter((node) => `${node.canonical_name} ${node.entity_type}`.toLowerCase().includes(query)) : nodes;
  }, [nodes, search]);

  async function triggerGraphBuild() {
    setBuilding(true);
    setBuildMsg(undefined);
    try {
      const job = await post<Job>(`/projects/${projectId}/graph-build`);
      setBuildMsg(`Graph build job dispatched: ${job.id} (${job.state})`);
      entities.refresh();
      relationships.refresh();
    } catch (err) {
      setBuildMsg(err instanceof Error ? err.message : "Graph build failed");
    } finally {
      setBuilding(false);
    }
  }

  if (entities.loading || relationships.loading) return <StatePanel kind="loading">Loading the 3D architecture graph…</StatePanel>;
  if (entities.error || relationships.error) return <StatePanel kind="error">{entities.error?.message ?? relationships.error?.message}</StatePanel>;
  if (!nodes.length) {
    return <section className="card empty-graph"><div className="section-kicker">Knowledge Graph</div><h2>Your architecture graph is ready to be built</h2><StatePanel kind="empty">No trusted architecture facts exist for this project yet. Ingest source documents and trigger a graph build.</StatePanel><button onClick={triggerGraphBuild} disabled={building}>{building ? "Building graph…" : "Trigger graph build"}</button>{buildMsg && <p className="action-feedback">{buildMsg}</p>}</section>;
  }

  return (
    <div className="graph-page">
      <section className="graph-hero">
        <div>
          <div className="section-kicker">Live knowledge topology</div>
          <h2>Explore the architecture in 3D</h2>
          <p>Drag to orbit · scroll to zoom · click a sphere to inspect provenance and review state.</p>
        </div>
        <div className="graph-actions"><label className="graph-search"><span>⌕</span><input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Find a component, port, interface…" /></label><button className="btn-secondary" onClick={triggerGraphBuild} disabled={building}>{building ? "Building…" : "Refresh graph"}</button></div>
      </section>
      {buildMsg && <p className="action-feedback graph-feedback">{buildMsg}</p>}
      <section className="graph-workspace">
        <div className="card graph-stage">
          <div className="graph-stage-top"><div><span className="live-dot" /> {filteredNodes.length} nodes <span className="muted">·</span> {edges.length} relationships</div><div className="graph-hint">3D WebGL canvas</div></div>
          <Graph3D nodes={filteredNodes} relationships={edges} onSelect={setSelected} />
          <div className="graph-legend"><span><i className="legend-orb component" /> Components</span><span><i className="legend-orb interface" /> Interfaces</span><span><i className="legend-orb signal" /> Signals</span><span><i className="legend-line" /> Relationship</span></div>
        </div>
        <GraphInspector projectId={projectId} selectedItem={selected} onActionComplete={() => { entities.refresh(); relationships.refresh(); }} />
      </section>
    </div>
  );
}

function ImpactAnalysisView({ projectId }: { projectId: string }) {
  const entities = useApi(() => getPage<Entity>(`/projects/${projectId}/entities`), [projectId]);
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
      const res = await post<ImpactAnalysis>(`/projects/${projectId}/impact`, {
        root_entity_id: root,
        depth,
        node_limit: 100,
        edge_limit: 200,
      });
      setResult(res);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Impact analysis failed");
    } finally {
      setLoading(false);
    }
  }

  return (
    <>
      <section className="card">
        <h2>Semantic Impact Analysis</h2>
        <form onSubmit={submit} className="impact-form">
          <div className="form-row">
            <label>
              Target Entity (Changed Artifact)
              <select value={root} onChange={(event) => setRoot(event.target.value)} required>
                <option value="">Select an entity to analyze</option>
                {entities.data?.items.map((entity) => (
                  <option key={entity.id} value={entity.id}>
                    {entity.canonical_name} ({entity.entity_type})
                  </option>
                ))}
              </select>
            </label>
            <label>
              Traversal Depth
              <select value={depth} onChange={(event) => setDepth(Number(event.target.value))}>
                <option value={1}>1 Hop (Direct Dependents)</option>
                <option value={2}>2 Hops (Indirect Impact)</option>
                <option value={3}>3 Hops (Extended Flow)</option>
              </select>
            </label>
            <button type="submit" disabled={loading}>
              {loading ? "Analyzing..." : "Analyze Impact"}
            </button>
          </div>
        </form>
      </section>

      {error && <StatePanel kind="error">{error}</StatePanel>}

      {result && (
        <section className="card">
          <h2>Impact Analysis Results</h2>
          {result.truncated && (
            <StatePanel kind="partial">
              Traversal reached configured bounds; results are partial.
            </StatePanel>
          )}
          {result.results.length ? (
            <div className="impact-results">
              {result.results.map((item, index) => (
                <article className="impact-card" key={`${item.affected_entity_id}-${index}`}>
                  <div className="impact-header">
                    <strong className="impact-kind">{item.kind}</strong>
                    <span className="impact-name">
                      {item.affected_entity_name ?? "Unknown"} ({item.affected_entity_type ?? "N/A"})
                    </span>
                  </div>
                  <div className="impact-meta">
                    <p>
                      <strong>Path:</strong> <code>{item.path.entity_ids.join(" → ")}</code>
                    </p>
                    <p>
                      <strong>Extraction / Validation:</strong>{" "}
                      {item.extraction_type ?? "INFERRED"} · {item.validation_state ?? "PENDING"}
                      {item.confidence !== null ? ` (${Math.round(item.confidence * 100)}%)` : ""}
                    </p>
                    {item.message && <p className="impact-msg">{item.message}</p>}
                  </div>
                </article>
              ))}
            </div>
          ) : (
            <StatePanel kind="empty">
              No impacted entities found under current dependency rules for this root entity.
            </StatePanel>
          )}
        </section>
      )}
    </>
  );
}

function ReviewQueueView({ projectId }: { projectId: string }) {
  const queue = useApi(() => getPage<ReviewItem>(`/projects/${projectId}/review-queue`), [projectId]);
  const [reason, setReason] = useState("Verified by engineering review");
  const [corrName, setCorrName] = useState("");
  const [corrType, setCorrType] = useState("");
  const [correctingId, setCorrectingId] = useState<string>();
  const [message, setMessage] = useState<string>();

  async function handleVerify(item: ReviewItem) {
    try {
      const path = item.fact_kind === "ENTITY" ? "entities" : "relationships";
      await post(`/projects/${projectId}/${path}/${item.fact_id}/verify`, { reason });
      setMessage(`Verified: ${item.label}`);
      queue.refresh();
    } catch (err) {
      setMessage(err instanceof Error ? err.message : "Verify failed");
    }
  }

  async function handleReject(item: ReviewItem) {
    try {
      const path = item.fact_kind === "ENTITY" ? "entities" : "relationships";
      await post(`/projects/${projectId}/${path}/${item.fact_id}/reject`, { reason });
      setMessage(`Rejected: ${item.label}`);
      queue.refresh();
    } catch (err) {
      setMessage(err instanceof Error ? err.message : "Reject failed");
    }
  }

  async function handleCorrect(item: ReviewItem) {
    if (item.fact_kind !== "ENTITY") return;
    try {
      await post(`/projects/${projectId}/entities/${item.fact_id}/correct`, {
        canonical_name: corrName || item.label,
        entity_type: corrType || "COMPONENT",
        reason,
      });
      setMessage(`Corrected entity: ${item.label}`);
      setCorrectingId(undefined);
      queue.refresh();
    } catch (err) {
      setMessage(err instanceof Error ? err.message : "Correction failed");
    }
  }

  if (queue.loading) return <StatePanel kind="loading">Loading review candidates…</StatePanel>;
  if (queue.error) return <StatePanel kind="error">{queue.error.message}</StatePanel>;

  return (
    <section className="card">
      <h2>Human Review Queue</h2>
      <p>Inspect extracted candidate facts alongside source evidence. Correcting or verifying a fact preserves original AI extractions in audit records.</p>
      
      <label className="input-label" style={{ marginBottom: "1rem" }}>
        Review Decision Comment / Reason
        <input value={reason} onChange={(event) => setReason(event.target.value)} />
      </label>

      {message && <StatePanel kind="partial">{message}</StatePanel>}

      {queue.data?.items.length ? (
        <div className="review-list">
          {queue.data.items.map((item) => (
            <article className="review-card" key={item.fact_id}>
              <div className="review-main">
                <div className="review-header">
                  <strong>{item.label}</strong>
                  <StatusBadge fact={item} />
                </div>
                <p className="review-meta">
                  Kind: <code>{item.fact_kind}</code> | Extraction: {item.extraction_type}
                </p>
                {item.provenance.map((src, index) => (
                  <details key={index} className="review-provenance">
                    <summary>
                      Source: {src.document_name} · <em>{src.section_heading}</em>
                      {src.page_start ? ` (p. ${src.page_start})` : ""}
                    </summary>
                    <blockquote>{src.excerpt}</blockquote>
                  </details>
                ))}

                {correctingId === item.fact_id && (
                  <div className="correction-form">
                    <h4>Correct Entity Information</h4>
                    <input
                      type="text"
                      placeholder="Correct Canonical Name"
                      value={corrName}
                      onChange={(e) => setCorrName(e.target.value)}
                    />
                    <input
                      type="text"
                      placeholder="Correct Entity Type"
                      value={corrType}
                      onChange={(e) => setCorrType(e.target.value)}
                    />
                    <div className="action-buttons">
                      <button onClick={() => void handleCorrect(item)}>Submit Correction</button>
                      <button className="btn-secondary" onClick={() => setCorrectingId(undefined)}>Cancel</button>
                    </div>
                  </div>
                )}
              </div>

              <div className="review-actions">
                <button onClick={() => void handleVerify(item)}>Verify</button>
                {item.fact_kind === "ENTITY" && (
                  <button className="btn-secondary" onClick={() => {
                    setCorrectingId(item.fact_id);
                    setCorrName(item.label);
                  }}>
                    Correct
                  </button>
                )}
                <button className="danger" onClick={() => void handleReject(item)}>Reject</button>
              </div>
            </article>
          ))}
        </div>
      ) : (
        <StatePanel kind="empty">No pending candidate facts require review.</StatePanel>
      )}
    </section>
  );
}

function ComparisonView({ projectId }: { projectId: string }) {
  const documents = useApi(() => getPage<Document>(`/projects/${projectId}/documents`), [projectId]);
  const [selectedDoc, setSelectedDoc] = useState("");
  const [versions, setVersions] = useState<DocumentVersion[]>([]);
  const [baseVer, setBaseVer] = useState("");
  const [targetVer, setTargetVer] = useState("");
  const [message, setMessage] = useState<string>();
  const [findings, setFindings] = useState<ComparisonFinding[]>([]);

  async function loadVersions(docId: string) {
    setSelectedDoc(docId);
    if (!docId) {
      setVersions([]);
      return;
    }
    const result = await getPage<DocumentVersion>(`/projects/${projectId}/documents/${docId}/versions`);
    setVersions(result.items);
    if (result.items.length >= 2) {
      setBaseVer(result.items[0].id);
      setTargetVer(result.items[1].id);
    } else if (result.items.length === 1) {
      setBaseVer(result.items[0].id);
      setTargetVer(result.items[0].id);
    }
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!baseVer || !targetVer) return;
    setFindings([]);
    try {
      const job = await post<Job>(`/projects/${projectId}/comparisons`, {
        base_version_id: baseVer,
        target_version_id: targetVer,
      });
      const compId = job.details?.comparison_id as string | undefined;
      if (compId) {
        const res = await getPage<ComparisonFinding>(`/projects/${projectId}/comparisons/${compId}/findings`);
        setFindings(res.items);
        setMessage(`Comparison completed: ${res.total} structural findings derived.`);
      } else {
        setMessage(`Comparison job ${job.id} dispatched (${job.state}). Note: Revision differences are informational findings.`);
      }
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Comparison request failed");
    }
  }

  return (
    <section className="card">
      <h2>Document Revision Comparison</h2>
      <p>
        Compare two document versions to detect entity and relationship additions, deletions, or structural renames. Differences between revisions are recorded as informational findings.
      </p>

      <form onSubmit={submit} className="comparison-form">
        <label>
          Select Document
          <select value={selectedDoc} onChange={(e) => void loadVersions(e.target.value)} required>
            <option value="">Choose document...</option>
            {documents.data?.items.map((doc) => (
              <option key={doc.id} value={doc.id}>
                {doc.name}
              </option>
            ))}
          </select>
        </label>

        {versions.length > 0 && (
          <div className="form-row">
            <label>
              Base Revision
              <select value={baseVer} onChange={(e) => setBaseVer(e.target.value)}>
                {versions.map((v) => (
                  <option key={v.id} value={v.id}>
                    Version {v.version_number} ({v.source_label ?? "v" + v.version_number})
                  </option>
                ))}
              </select>
            </label>
            <label>
              Target Revision
              <select value={targetVer} onChange={(e) => setTargetVer(e.target.value)}>
                {versions.map((v) => (
                  <option key={v.id} value={v.id}>
                    Version {v.version_number} ({v.source_label ?? "v" + v.version_number})
                  </option>
                ))}
              </select>
            </label>
            <button type="submit">Dispatch Comparison</button>
          </div>
        )}
      </form>

      {message && <StatePanel kind="partial">{message}</StatePanel>}

      {findings.length > 0 && (
        <div style={{ marginTop: "1.5rem" }}>
          <h3>Revision Comparison Findings</h3>
          <table className="data-table">
            <thead>
              <tr>
                <th>Finding Type</th>
                <th>Summary</th>
                <th>Details</th>
              </tr>
            </thead>
            <tbody>
              {findings.map((finding) => (
                <tr key={finding.id}>
                  <td><strong>{finding.finding_type}</strong></td>
                  <td>{finding.summary}</td>
                  <td><code>{JSON.stringify(finding.details)}</code></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

function AuditView({ projectId }: { projectId: string }) {
  const jobs = useApi(() => getPage<Job>(`/projects/${projectId}/jobs`), [projectId]);
  const audit = useApi(() => getPage<AuditEvent>(`/projects/${projectId}/audit`), [projectId]);

  if (jobs.loading || audit.loading) {
    return <StatePanel kind="loading">Loading audit log and job operations…</StatePanel>;
  }
  if (jobs.error || audit.error) {
    return (
      <StatePanel kind="error">
        {jobs.error?.message ?? audit.error?.message}
      </StatePanel>
    );
  }

  return (
    <div className="audit-workspace">
      <section className="card">
        <h2>Background Pipeline Jobs</h2>
        {jobs.data?.items.length ? (
          <table className="data-table">
            <thead>
              <tr>
                <th>Job Type</th>
                <th>State</th>
                <th>Progress</th>
                <th>Job ID</th>
              </tr>
            </thead>
            <tbody>
              {jobs.data.items.map((job) => (
                <tr key={job.id}>
                  <td>
                    <strong>{job.job_type}</strong>
                  </td>
                  <td>
                    <span className={`job-state state-${job.state.toLowerCase()}`}>
                      {job.state}
                    </span>
                  </td>
                  <td>{String(job.details?.progress ?? "100")}%</td>
                  <td>
                    <code>{job.id}</code>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <StatePanel kind="empty">No pipeline job activity recorded.</StatePanel>
        )}
      </section>

      <section className="card">
        <h2>Operational Audit History</h2>
        {audit.data?.items.length ? (
          <table className="data-table">
            <thead>
              <tr>
                <th>Event Type</th>
                <th>User / Actor</th>
                <th>Timestamp</th>
                <th>Event ID</th>
              </tr>
            </thead>
            <tbody>
              {audit.data.items.map((ev) => (
                <tr key={ev.id}>
                  <td>
                    <strong>{ev.action}</strong>
                  </td>
                  <td>{ev.actor_id ?? "system"}</td>
                  <td>{ev.created_at ? new Date(ev.created_at).toLocaleString() : "—"}</td>
                  <td>
                    <code>{ev.id.slice(0, 16)}…</code>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <StatePanel kind="empty">No audit events recorded for this project.</StatePanel>
        )}
      </section>
    </div>
  );
}
