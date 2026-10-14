import { useEffect } from "react";
import { getPage, withParams } from "../api/client";
import { useApi } from "../hooks/useApi";
import { buildChain, chainsFrom, type Chain, type StageView } from "../lib/pipeline";
import type { Job } from "../types/api";

const POLL_MS = 1500;

const ICON: Record<StageView["state"], string> = {
  pending: "",
  queued: "…",
  active: "",
  done: "✓",
  warning: "!",
  failed: "✕",
  cancelled: "–",
};

const STATE_TEXT: Record<StageView["state"], string> = {
  pending: "Waiting",
  queued: "Queued",
  active: "Running",
  done: "Done",
  warning: "Done with warnings",
  failed: "Failed",
  cancelled: "Cancelled",
};

/**
 * The stages of ONE document, each ticked off (with a short animation) the moment its job completes.
 *
 * It follows the ingestion job ``jobId`` (the file the queue is working on). With no ``jobId`` it picks
 * up an ingestion that is still running from earlier (e.g. after a page reload). Finished and failed
 * runs are never listed: there is only ever the one being processed.
 */
export function PipelineTracker({ projectId, jobId }: { projectId: string; jobId?: string }) {
  const jobs = useApi(() => getPage<Job>(withParams(`/projects/${projectId}/jobs`, { limit: 100 })), [projectId, jobId]);
  const items = jobs.data?.items ?? [];
  let chain: Chain | undefined;
  if (jobId) {
    const start = items.find((job) => job.id === jobId);
    chain = start ? buildChain(start, new Map(items.map((job) => [job.id, job]))) : undefined;
  } else {
    chain = chainsFrom(items).find((candidate) => !candidate.finished);
  }
  const busy = chain ? !chain.finished : !jobId; // with no focus keep looking for a run in progress
  const reload = jobs.reload;

  useEffect(() => {
    if (!busy) return;
    const timer = window.setInterval(reload, POLL_MS);
    return () => window.clearInterval(timer);
  }, [busy, reload]);

  // A failed run is reported once, in the upload queue; it is not drawn as a block here.
  if (!chain || chain.failed) return null;
  return <ChainView chain={chain} />;
}

function ChainView({ chain }: { chain: Chain }) {
  const label = chain.finished ? "Complete" : "Processing";
  return (
    <section className={`chain ${chain.finished ? "chain-done" : "chain-live"}`}>
      <div className="chain-head">
        <strong>{label}</strong>
        <span className="muted">{chain.overall}%</span>
      </div>
      <div className="progress" aria-hidden="true">
        <span className={`progress-fill ${chain.finished ? "" : "progress-live"}`} style={{ width: `${Math.max(chain.overall, chain.finished ? 100 : 4)}%` }} />
      </div>
      <ol className="pipeline" aria-label="Processing stages">
        {chain.stages.map((stage, index) => (
          <li key={stage.type} className={`pipe-stage pipe-${stage.state}`} aria-current={stage.state === "active" ? "step" : undefined}>
            <span className="pipe-dot" aria-hidden="true">
              {stage.state === "active" ? <i className="spinner" /> : ICON[stage.state] || index + 1}
            </span>
            <span className="pipe-name">{stage.label}</span>
            <span className="pipe-state">
              {STATE_TEXT[stage.state]}
              {stage.state === "active" ? ` · ${stage.progress}%` : ""}
            </span>
            <small className="pipe-detail">{stage.message || stage.detail}</small>
            {stage.state === "active" && (
              <span className="mini-track" aria-hidden="true">
                <span className="mini-fill" style={{ width: `${stage.progress}%` }} />
              </span>
            )}
          </li>
        ))}
      </ol>
    </section>
  );
}
