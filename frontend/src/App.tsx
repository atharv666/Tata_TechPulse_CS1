import { Suspense, lazy, useState } from "react";
import { Select } from "./components/Select";
import { getPage } from "./api/client";
import { DocumentManager } from "./components/DocumentDetail";
import { ErrorBoundary } from "./components/ErrorBoundary";
import { StatePanel } from "./components/StatePanel";
import { useApi } from "./hooks/useApi";
import { useUploadQueue } from "./hooks/useUploadQueue";
import { AskScreen } from "./screens/AskScreen";
import { AuditScreen } from "./screens/AuditScreen";
import { ComparisonScreen } from "./screens/ComparisonScreen";
import { Dashboard, type Screen } from "./screens/Dashboard";
import { FindingsScreen } from "./screens/FindingsScreen";
import { ImpactScreen } from "./screens/ImpactScreen";
import { ReviewScreen } from "./screens/ReviewScreen";
import type { Project } from "./types/api";
import "./workspace.css";
import "./ui.css";

// three.js is large: the graph screen loads only when it is opened.
const GraphScreen = lazy(() => import("./screens/GraphScreen").then((module) => ({ default: module.GraphScreen })));

const navigation: Array<[Screen, string]> = [
  ["dashboard", "Dashboard"],
  ["documents", "Documents"],
  ["ask", "Ask Architecture"],
  ["graph", "Knowledge Graph"],
  ["impact", "Impact Analysis"],
  ["review", "Review Queue"],
  ["findings", "Findings"],
  ["comparison", "Revision Comparison"],
  ["audit", "Audit"],
];

export function App() {
  const projects = useApi(() => getPage<Project>("/projects"), []);
  const [screen, setScreen] = useState<Screen>("dashboard");
  const [projectId, setProjectId] = useState<string>();
  // The upload queue lives here so it keeps running while you look at other screens.
  const [libraryVersion, setLibraryVersion] = useState(0);
  const uploads = useUploadQueue(() => setLibraryVersion((value) => value + 1));
  const selected = projectId ?? projects.data?.items[0]?.id;

  if (projects.loading) return <StatePanel kind="loading">Loading the engineering workspace…</StatePanel>;
  if (projects.error) return <StatePanel kind="error">Unable to load projects: {projects.error.message}</StatePanel>;
  if (!selected) {
    return (
      <main className="onboarding">
        <h1>No accessible projects</h1>
        <p>Create a project through the API, then refresh this workspace.</p>
        <button onClick={projects.refresh}>Refresh</button>
      </main>
    );
  }

  const title = navigation.find(([key]) => key === screen)?.[1];
  return (
    <div className="shell">
      <aside className="rail">
        <div className="brand">
          <b>A</b>
          <span>AUTOSAR<br />INTELLIGENCE</span>
        </div>
        <label className="project-label">
          PROJECT
          <Select
            value={selected}
            onChange={setProjectId}
            options={(projects.data?.items ?? []).map((project) => ({ value: project.id, label: project.name }))}
          />
        </label>
        <nav>
          {navigation.map(([key, label]) => (
            <button key={key} className={screen === key ? "nav-current" : ""} onClick={() => setScreen(key)}>
              {label}
            </button>
          ))}
        </nav>
        <p className="rail-note">
          Evidence-linked, human-validated.
          <br />
          <span>Development identity in use</span>
        </p>
      </aside>
      <main className="workspace">
        <header>
          <div>
            <p className="eyebrow">AUTOSAR Architecture Intelligence</p>
            <h1>{title}</h1>
          </div>
        </header>
        {/* key: switching project resets every screen's state (no stale answers or selections) */}
        <ErrorBoundary key={`${selected}:${screen}`} scope={title}>
        <div>
          {screen === "dashboard" && <Dashboard projectId={selected} onNavigate={setScreen} />}
          {screen === "documents" && <DocumentManager projectId={selected} uploads={uploads} libraryVersion={libraryVersion} />}
          {screen === "ask" && <AskScreen projectId={selected} onOpenGraph={() => setScreen("graph")} />}
          {screen === "graph" && (
            <Suspense fallback={<StatePanel kind="loading">Loading the graph viewer…</StatePanel>}>
              <GraphScreen projectId={selected} />
            </Suspense>
          )}
          {screen === "impact" && <ImpactScreen projectId={selected} />}
          {screen === "review" && <ReviewScreen projectId={selected} />}
          {screen === "findings" && <FindingsScreen projectId={selected} />}
          {screen === "comparison" && <ComparisonScreen projectId={selected} />}
          {screen === "audit" && <AuditScreen projectId={selected} />}
        </div>
        </ErrorBoundary>
      </main>
    </div>
  );
}
