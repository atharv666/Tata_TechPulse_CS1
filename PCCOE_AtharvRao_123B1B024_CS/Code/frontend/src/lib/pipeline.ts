import type { Job } from "../types/api";

/** The stages a document goes through, in order, as job types. */
export const STAGES = [
  { type: "DOCUMENT_INGESTION", label: "Parse & structure", detail: "Read the file, find sections and tables, split into passages" },
  { type: "EMBEDDING", label: "Embed passages", detail: "Compute vectors for semantic search" },
  { type: "GRAPH_EXTRACTION", label: "Extract entities", detail: "Find components, interfaces, signals and relationships" },
  { type: "ENTITY_RESOLUTION", label: "Resolve duplicates", detail: "Merge names that mean the same item" },
  { type: "GRAPH_BUILD", label: "Build graph", detail: "Bind relationships, validate, check for inconsistencies" },
] as const;

export type StageState = "pending" | "queued" | "active" | "done" | "warning" | "failed" | "cancelled";

export interface StageView {
  type: string;
  label: string;
  detail: string;
  state: StageState;
  /** 0-100 within this stage. */
  progress: number;
  message: string;
  attempt: number;
  jobId?: string;
}

export interface Chain {
  /** Id of the DOCUMENT_INGESTION job that started the chain. */
  id: string;
  createdAt: string;
  stages: StageView[];
  /** 0-100 across all stages. */
  overall: number;
  /** Nothing further will happen (everything is done, or a stage failed). */
  finished: boolean;
  failed: boolean;
}

interface Details {
  progress?: number;
  attempt?: number;
  next_job_id?: string;
  failure_message?: string;
  logs?: Array<{ message?: string }>;
  partial_failures?: unknown[];
}

const details = (job: Job): Details => job.details as Details;

function lastLog(job: Job): string {
  const logs = details(job).logs ?? [];
  return logs.length ? String(logs[logs.length - 1].message ?? "") : "";
}

export function stageOf(job: Job | undefined, spec: (typeof STAGES)[number]): StageView {
  const base = { type: spec.type, label: spec.label, detail: spec.detail, progress: 0, message: "", attempt: 0 };
  if (!job) return { ...base, state: "pending" };
  const info = details(job);
  const common = { ...base, jobId: job.id, attempt: info.attempt ?? 0 };
  switch (job.state) {
    case "COMPLETED":
      return { ...common, state: "done", progress: 100, message: lastLog(job) };
    case "RUNNING":
      return { ...common, state: "active", progress: Math.min(99, info.progress ?? 0), message: lastLog(job) };
    case "PENDING":
      return {
        ...common,
        state: "queued",
        message: (info.attempt ?? 0) > 0 ? "Waiting to retry after a temporary problem" : "Waiting for the worker",
      };
    case "CANCELLED":
      return { ...common, state: "cancelled", message: "Cancelled" };
    default: {
      // A stage that failed *after* queuing the next stage only lost some items.
      const partial = (info.partial_failures ?? []).length;
      if (info.next_job_id && partial > 0) {
        return { ...common, state: "warning", progress: 100, message: `${partial} item(s) could not be processed` };
      }
      return { ...common, state: "failed", progress: info.progress ?? 0, message: info.failure_message ?? "The stage failed" };
    }
  }
}

export function buildChain(start: Job, byId: Map<string, Job>): Chain {
  const jobs: Array<Job | undefined> = [];
  let current: Job | undefined = start;
  for (let step = 0; step < STAGES.length && current; step += 1) {
    jobs.push(current);
    const next: string | undefined = details(current).next_job_id;
    current = next ? byId.get(next) : undefined;
  }
  const stages = STAGES.map((spec, index) => stageOf(jobs[index]?.job_type === spec.type ? jobs[index] : undefined, spec));
  const stoppedAt = stages.findIndex((stage) => stage.state === "failed" || stage.state === "cancelled");
  const settled = (stage: StageView) => stage.state === "done" || stage.state === "warning";
  const done = stages.filter(settled).length;
  const running = stages.find((stage) => stage.state === "active");
  const failed = stoppedAt >= 0;
  const overall = Math.round(((done + (running ? running.progress / 100 : 0)) / STAGES.length) * 100);
  return {
    id: start.id,
    createdAt: start.created_at ?? "",
    stages,
    overall,
    failed,
    finished: failed || stages.every(settled),
  };
}

/** One chain per ingestion job, newest first. */
export function chainsFrom(jobs: Job[]): Chain[] {
  const byId = new Map(jobs.map((job) => [job.id, job]));
  return jobs
    .filter((job) => job.job_type === "DOCUMENT_INGESTION")
    .map((job) => buildChain(job, byId))
    .sort((a, b) => b.createdAt.localeCompare(a.createdAt));
}
