import { describe, expect, it } from "vitest";
import { counts, current, newItem, nextToStart, withoutFinished, type QueueItem } from "./uploadQueue";

const item = (name: string, state: QueueItem["state"]): QueueItem => ({ ...newItem("p", { name, size: 1 }), state });

describe("upload queue", () => {
  it("starts the first waiting file only when nothing is running", () => {
    expect(nextToStart([item("a", "waiting"), item("b", "waiting")])?.name).toBe("a");
    expect(nextToStart([item("a", "processing"), item("b", "waiting")])).toBeUndefined();
    expect(nextToStart([item("a", "uploading"), item("b", "waiting")])).toBeUndefined();
    expect(nextToStart([item("a", "done"), item("b", "waiting")])?.name).toBe("b");
    expect(nextToStart([item("a", "failed")])).toBeUndefined();
  });

  it("a failed file does not block the ones behind it", () => {
    const items = [item("bad", "failed"), item("next", "waiting")];
    expect(nextToStart(items)?.name).toBe("next");
  });

  it("reports the running item and the tally", () => {
    const items = [item("a", "done"), item("b", "processing"), item("c", "waiting"), item("d", "failed")];
    expect(current(items)?.name).toBe("b");
    expect(counts(items)).toEqual({ waiting: 1, done: 1, failed: 1 });
  });

  it("clears finished items so the list never grows without bound", () => {
    const items = [item("a", "done"), item("b", "failed"), item("c", "processing"), item("d", "waiting")];
    expect(withoutFinished(items).map((i) => i.name)).toEqual(["c", "d"]);
  });

  it("gives every item a unique id", () => {
    expect(new Set([newItem("p", { name: "x", size: 1 }).id, newItem("p", { name: "x", size: 1 }).id]).size).toBe(2);
  });
});
