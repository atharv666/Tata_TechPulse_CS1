import { getPage } from "../api/client";
import { useApi } from "../hooks/useApi";
import type { Document, Entity, Finding, Job, ReviewItem } from "../types/api";

export type Screen =
  | "dashboard"
  | "documents"
  | "ask"
  | "graph"
  | "impact"
  | "review"
  | "findings"
  | "comparison"
  | "audit";

export function Dashboard({ projectId, onNavigate }: { projectId: string; onNavigate: (screen: Screen) => void }) {
  const entities = useApi(() => getPage<Entity>(`/projects/${projectId}/entities?limit=1`), [projectId]);
  const documents = useApi(() => getPage<Document>(`/projects/${projectId}/documents?limit=1`), [projectId]);
  const jobs = useApi(() => getPage<Job>(`/projects/${projectId}/jobs?limit=1`), [projectId]);
  const review = useApi(() => getPage<ReviewItem>(`/projects/${projectId}/review-queue?limit=1`), [projectId]);
  const findings = useApi(() => getPage<Finding>(`/projects/${projectId}/findings?status=OPEN&limit=1`), [projectId]);

  const cards: Array<[string, number | string, Screen, string]> = [
    ["Documents", documents.data?.total ?? "—", "documents", "Source library"],
    ["Graph entities", entities.data?.total ?? "—", "graph", "Live facts"],
    ["Awaiting review", review.data?.total ?? "—", "review", "Human decisions"],
    ["Open findings", findings.data?.total ?? "—", "findings", "Potential inconsistencies"],
    ["Jobs", jobs.data?.total ?? "—", "audit", "Pipeline activity"],
  ];

  return (
    <div className="home-page">
      <section className="welcome-panel">
        <div className="welcome-copy">
          <h2>AUTOSAR Architecture Intelligence</h2>
          <p>
            Ask questions about your HLD documents and get answers that cite their source. Explore the extracted
            architecture, review what the AI proposed, and see what a change could affect.
          </p>
          <div className="welcome-actions">
            <button onClick={() => onNavigate("ask")}>Ask a question →</button>
            <button className="btn-secondary" onClick={() => onNavigate("documents")}>Ingest a document</button>
          </div>
        </div>
      </section>
      <section className="metrics home-metrics">
        {cards.map(([label, value, target, caption]) => (
          <button className="metric" key={label} onClick={() => onNavigate(target)}>
            <span>{label}</span>
            <strong>{value}</strong>
            <small>{caption} →</small>
          </button>
        ))}
      </section>
      <section className="card home-principles">
        <div className="principle-list">
          <div><b>01</b><span><strong>Evidence first.</strong> Every answer and every graph fact points at the passage it came from.</span></div>
          <div><b>02</b><span><strong>Humans decide.</strong> Extracted facts stay PENDING until an engineer verifies, edits or rejects them.</span></div>
          <div><b>03</b><span><strong>Findings are prompts.</strong> “Potential inconsistency detected” means look here, not “this is wrong”.</span></div>
        </div>
      </section>
    </div>
  );
}
