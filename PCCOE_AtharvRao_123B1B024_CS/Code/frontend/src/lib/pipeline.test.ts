import { describe, expect, it } from "vitest";
import type { Job } from "../types/api";
import { STAGES, buildChain, chainsFrom } from "./pipeline";

const job = (id: string, type: string, state: string, details: Record<string, unknown> = {}, created = "2026-10-13T10:00:00Z"): Job => ({
  id,
  job_type: type,
  state,
  details,
  created_at: created,
});

describe("pipeline chain", () => {
  it("shows every stage from the start, the later ones as waiting", () => {
    const chain = buildChain(job("a", "DOCUMENT_INGESTION", "PENDING"), new Map());
    expect(chain.stages.map((s) => s.type)).toEqual(STAGES.map((s) => s.type));
    expect(chain.stages.map((s) => s.state)).toEqual(["queued", "pending", "pending", "pending", "pending"]);
    expect(chain.overall).toBe(0);
    expect(chain.finished).toBe(false);
  });

  it("ticks stages off as their jobs complete and follows the next-job links", () => {
    const jobs = [
      job("a", "DOCUMENT_INGESTION", "COMPLETED", { next_job_id: "b" }),
      job("b", "EMBEDDING", "COMPLETED", { next_job_id: "c" }),
      job("c", "GRAPH_EXTRACTION", "RUNNING", { progress: 50, logs: [{ message: "Processed 3/6 chunks" }] }),
    ];
    const chain = buildChain(jobs[0], new Map(jobs.map((j) => [j.id, j])));
    expect(chain.stages.map((s) => s.state)).toEqual(["done", "done", "active", "pending", "pending"]);
    expect(chain.stages[2].progress).toBe(50);
    expect(chain.stages[2].message).toBe("Processed 3/6 chunks");
    expect(chain.overall).toBe(50); // (2 done + half of the third) / 5
    expect(chain.finished).toBe(false);
  });

  it("is finished when all five stages are done", () => {
    const types = STAGES.map((s) => s.type);
    const jobs = types.map((type, i) => job(`j${i}`, type, "COMPLETED", i < 4 ? { next_job_id: `j${i + 1}` } : {}));
    const chain = buildChain(jobs[0], new Map(jobs.map((j) => [j.id, j])));
    expect(chain.finished && !chain.failed).toBe(true);
    expect(chain.overall).toBe(100);
  });

  it("stops at a failed stage and keeps its message", () => {
    const jobs = [
      job("a", "DOCUMENT_INGESTION", "FAILED", { failure_message: "identical source file" }),
    ];
    const chain = buildChain(jobs[0], new Map([["a", jobs[0]]]));
    expect(chain.stages[0].state).toBe("failed");
    expect(chain.stages[0].message).toBe("identical source file");
    expect(chain.failed && chain.finished).toBe(true);
  });

  it("treats a stage that lost only some items as done with warnings", () => {
    const jobs = [
      job("a", "DOCUMENT_INGESTION", "COMPLETED", { next_job_id: "b" }),
      job("b", "EMBEDDING", "COMPLETED", { next_job_id: "c" }),
      job("c", "GRAPH_EXTRACTION", "FAILED", { next_job_id: "d", partial_failures: [{}, {}] }),
      job("d", "ENTITY_RESOLUTION", "RUNNING", { progress: 10 }),
    ];
    const chain = buildChain(jobs[0], new Map(jobs.map((j) => [j.id, j])));
    expect(chain.stages[2].state).toBe("warning");
    expect(chain.stages[2].message).toContain("2 item(s)");
    expect(chain.failed).toBe(false);
    expect(chain.stages[3].state).toBe("active");
  });

  it("explains a queued retry and orders chains newest first", () => {
    const retry = job("a", "DOCUMENT_INGESTION", "PENDING", { attempt: 1 }, "2026-10-13T09:00:00Z");
    const newer = job("n", "DOCUMENT_INGESTION", "RUNNING", { progress: 5 }, "2026-10-13T11:00:00Z");
    const other = job("x", "GRAPH_BUILD", "COMPLETED");
    const chains = chainsFrom([retry, newer, other]);
    expect(chains.map((c) => c.id)).toEqual(["n", "a"]);
    expect(chains[1].stages[0].message).toContain("retry");
  });
});
