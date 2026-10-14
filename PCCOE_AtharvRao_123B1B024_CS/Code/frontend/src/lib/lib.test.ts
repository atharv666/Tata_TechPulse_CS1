import { afterEach, describe, expect, it, vi } from "vitest";
import { BackendError, errorMessage, getAll, withParams } from "../api/client";
import type { ComparisonFinding, Entity, Finding, Relationship } from "../types/api";
import { groupChanges, isPotentialWording, orderGraphFindings, severityRank } from "./findings";
import { citationLabel, formatDuration, groupBy, humanize, percent, statusText, toNumber } from "./format";
import { countByTone, filterEntities, tone, toneLabel, visibleRelationships } from "./graphView";
import { PollTimeout, isFinished, pollUntil } from "./polling";

afterEach(() => vi.unstubAllGlobals());

const entity = (over: Partial<Entity> = {}): Entity => ({
  id: "e1",
  canonical_name: "BrakeController",
  entity_type: "SOFTWARE_COMPONENT",
  confidence: 0.94,
  extraction_type: "EXPLICIT",
  validation_state: "PENDING",
  trust_state: "CANDIDATE",
  ...over,
});

describe("status presentation", () => {
  it("never shows a confidence without its extraction and validation context", () => {
    expect(statusText(entity())).toBe("Confidence 0.94 · EXPLICIT · PENDING");
    expect(statusText(entity({ status_text: "from the server" }))).toBe("from the server");
  });

  it("maps validation, extraction and confidence to a colour AND a text label", () => {
    expect(tone(entity({ validation_state: "HUMAN_VERIFIED" }))).toBe("green");
    expect(tone(entity({ validation_state: "HUMAN_CORRECTED", extraction_type: "INFERRED" }))).toBe("green");
    expect(tone(entity())).toBe("blue");
    expect(tone(entity({ extraction_type: "INFERRED" }))).toBe("orange");
    expect(tone(entity({ confidence: 0.5 }))).toBe("orange");
    expect(tone(entity({ validation_state: "REJECTED", confidence: 1 }))).toBe("red");
    expect(toneLabel("blue")).toBe("Explicit, pending review");
    expect(countByTone([entity(), entity({ confidence: 0.3 }), entity({ validation_state: "REJECTED" })])).toEqual({
      green: 0,
      blue: 1,
      orange: 1,
      red: 1,
    });
  });

  it("formats numbers for people", () => {
    expect(percent(0.876)).toBe("88%");
    expect(percent(null)).toBe("—");
    expect(formatDuration(0.2)).toBe("<1 s");
    expect(formatDuration(42)).toBe("42 s");
    expect(formatDuration(300)).toBe("5 min");
    expect(humanize("MISSING_ENTITY_DEFINITION")).toBe("Missing Entity Definition");
  });

  it("labels a citation with document, section path, page and declared status", () => {
    const citation = {
      citation_id: "chunk:1",
      document_name: "HLD.pdf",
      section_heading: "Timing",
      section_path: "Doc > 3 Timing",
      page_start: 4,
      page_end: 4,
      excerpt: "x",
      document_version_id: "v1",
      document_status: "Approved",
    };
    expect(citationLabel(citation)).toBe("HLD.pdf · Doc > 3 Timing · p. 4 · Approved");
    expect(citationLabel({ ...citation, document_status: null, section_path: "", page_start: null })).toBe(
      "HLD.pdf · Timing · status not declared",
    );
  });
});

describe("decimal strings from the API", () => {
  it("are handled like numbers (this crashed the review queue)", () => {
    const asString = entity({ confidence: "0.900" as unknown as number });
    expect(statusText(asString)).toBe("Confidence 0.90 · EXPLICIT · PENDING");
    expect(percent("0.876")).toBe("88%");
    expect(tone({ ...asString, confidence: "0.500" as unknown as number })).toBe("orange");
    expect(tone(asString)).toBe("blue");
    expect(toNumber("abc")).toBeNull();
    expect(statusText(entity({ confidence: null as unknown as number }))).toContain("unknown");
  });
});

describe("graph filtering", () => {
  const nodes = [
    entity({ id: "a", canonical_name: "BrakeController" }),
    entity({ id: "b", canonical_name: "WheelSpeedInterface", entity_type: "INTERFACE" }),
    entity({ id: "c", canonical_name: "Old", validation_state: "REJECTED" }),
  ];

  it("filters by text, type and state together", () => {
    expect(filterEntities(nodes, { query: "wheel", type: "", state: "" }).map((n) => n.id)).toEqual(["b"]);
    expect(filterEntities(nodes, { query: "", type: "INTERFACE", state: "" }).map((n) => n.id)).toEqual(["b"]);
    expect(filterEntities(nodes, { query: "", type: "", state: "REJECTED" }).map((n) => n.id)).toEqual(["c"]);
    expect(filterEntities(nodes, { query: "", type: "", state: "" })).toHaveLength(3);
  });

  it("drops relationships whose endpoints are filtered out", () => {
    const edge = (id: string, source: string, target: string): Relationship => ({
      id,
      source_entity_id: source,
      target_entity_id: target,
      relationship_type: "REQUIRES",
      confidence: 0.9,
      extraction_type: "EXPLICIT",
      validation_state: "PENDING",
      trust_state: "CANDIDATE",
    });
    const kept = visibleRelationships([edge("1", "a", "b"), edge("2", "a", "c")], nodes.slice(0, 2));
    expect(kept.map((e) => e.id)).toEqual(["1"]);
  });
});

describe("findings", () => {
  const finding = (id: string, severity: string, status: string): Finding => ({
    id,
    finding_type: "MISSING_PROVIDER",
    severity,
    status,
    summary: "Potential inconsistency detected: x",
    details: {},
    entity_id: null,
    relationship_id: null,
    confidence: null,
    detected_by: "RULE",
    dismissed_by: null,
    dismissed_reason: null,
    created_at: null,
  });

  it("orders open findings first, most severe first", () => {
    const ordered = orderGraphFindings([
      finding("dismissed", "HIGH", "DISMISSED"),
      finding("low", "LOW", "OPEN"),
      finding("high", "HIGH", "OPEN"),
    ]);
    expect(ordered.map((f) => f.id)).toEqual(["high", "low", "dismissed"]);
    expect(severityRank("HIGH")).toBeLessThan(severityRank("INFO"));
  });

  it("checks the 'potential inconsistency' wording rule", () => {
    expect(isPotentialWording("Potential inconsistency detected: interface X has no provider.")).toBe(true);
    expect(isPotentialWording("The architecture is incorrect.")).toBe(false);
  });

  it("groups comparison findings by what changed, in a fixed order", () => {
    const item = (scope: ComparisonFinding["details"]["scope"], severity: string): ComparisonFinding => ({
      id: `${scope}-${severity}`,
      comparison_id: "c",
      entity_id: null,
      finding_type: "ADDED",
      confidence: 1,
      summary: scope,
      details: {
        scope,
        classification: "ADDED",
        severity,
        confidence: 1,
        summary: scope,
        changes: {},
        old_evidence: { citations: [] },
        new_evidence: { citations: [] },
        review_status: "NOT_APPLICABLE",
        impacts: [],
      },
    });
    const groups = groupChanges([item("RELATIONSHIP", "INFO"), item("SECTION", "LOW"), item("SECTION", "HIGH")]);
    expect(groups.map((g) => g.scope)).toEqual(["SECTION", "RELATIONSHIP"]);
    expect(groups[0].items.map((f) => f.details.severity)).toEqual(["HIGH", "LOW"]);
    expect(groupBy([1, 2, 3, 4], (n) => (n % 2 ? "odd" : "even"))).toEqual({ odd: [1, 3], even: [2, 4] });
  });
});

describe("polling", () => {
  it("returns as soon as the result is accepted", async () => {
    const states = ["PENDING", "RUNNING", "COMPLETED"];
    const sleep = vi.fn().mockResolvedValue(undefined);
    const result = await pollUntil(async () => states.shift() as string, isFinished, { sleep });
    expect(result).toBe("COMPLETED");
    expect(sleep).toHaveBeenCalledTimes(2);
  });

  it("gives up after a bounded number of checks", async () => {
    const load = vi.fn().mockResolvedValue("RUNNING");
    await expect(
      pollUntil(load, isFinished, { maxAttempts: 3, sleep: async () => undefined }),
    ).rejects.toBeInstanceOf(PollTimeout);
    expect(load).toHaveBeenCalledTimes(3);
  });
});

describe("api client", () => {
  const page = (items: number[], total: number) => ({
    ok: true,
    status: 200,
    json: async () => ({ items, offset: 0, limit: 2, total }),
  });

  it("skips empty query parameters", () => {
    expect(withParams("/x", { q: "", type: undefined, limit: 5, flag: false })).toBe("/x?limit=5&flag=false");
    expect(withParams("/x?a=1", { b: "2" })).toBe("/x?a=1&b=2");
    expect(withParams("/x", {})).toBe("/x");
  });

  it("loads every page and reports truncation at the cap", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(page([1, 2], 5))
      .mockResolvedValueOnce(page([3, 4], 5))
      .mockResolvedValueOnce(page([5], 5));
    vi.stubGlobal("fetch", fetchMock);
    const all = await getAll<number>("/things", 500, 2);
    expect(all).toEqual({ items: [1, 2, 3, 4, 5], total: 5, truncated: false });
    expect(String(fetchMock.mock.calls[1][0])).toContain("offset=2");

    const capped = vi.fn().mockResolvedValue(page([1, 2], 100));
    vi.stubGlobal("fetch", capped);
    const first = await getAll<number>("/things", 4, 2);
    expect(first.items).toHaveLength(4);
    expect(first.truncated).toBe(true);
  });

  it("turns backend errors into readable messages", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: false,
        status: 409,
        statusText: "Conflict",
        json: async () => ({ code: "NOT_PENDING", message: "Already reviewed." }),
      }),
    );
    const error = await getAll("/x").catch((reason: unknown) => reason);
    expect(error).toBeInstanceOf(BackendError);
    expect(errorMessage(error, "fallback")).toBe("Already reviewed. (NOT_PENDING)");
    expect(errorMessage("odd", "fallback")).toBe("fallback");
  });
});
