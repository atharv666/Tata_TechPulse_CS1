import { useCallback, useEffect, useRef, useState } from "react";
import { errorMessage, getPage, postForm, withParams } from "../api/client";
import { buildChain } from "../lib/pipeline";
import { current, newItem, nextToStart, withoutFinished, type QueueItem } from "../lib/uploadQueue";
import type { Job } from "../types/api";

const POLL_MS = 1500;

/**
 * A sequential upload queue that lives at the application level (so it keeps going when you switch
 * screens). Exactly one document is uploaded and processed at a time; the rest wait their turn.
 */
export function useUploadQueue(onSettled?: (projectId: string) => void) {
  const [items, setItems] = useState<QueueItem[]>([]);
  const files = useRef(new Map<string, File>());
  const starting = useRef(false);
  const settled = useRef(onSettled);
  settled.current = onSettled;

  const update = useCallback((id: string, patch: Partial<QueueItem>) => {
    setItems((all) => all.map((item) => (item.id === id ? { ...item, ...patch } : item)));
  }, []);

  const add = useCallback((projectId: string, picked: File[]) => {
    setItems((all) => {
      const added = picked.map((file) => {
        const item = newItem(projectId, file);
        files.current.set(item.id, file);
        return item;
      });
      return [...withoutFinished(all), ...added];
    });
  }, []);

  const remove = useCallback((id: string) => {
    files.current.delete(id);
    setItems((all) => all.filter((item) => item.id !== id || item.state !== "waiting"));
  }, []);

  const dismiss = useCallback((id: string) => setItems((all) => all.filter((item) => item.id !== id)), []);

  // Start the next waiting file when nothing is running.
  useEffect(() => {
    const next = nextToStart(items);
    if (!next || starting.current) return;
    const file = files.current.get(next.id);
    if (!file) {
      update(next.id, { state: "failed", error: "The file is no longer available; add it again." });
      return;
    }
    starting.current = true;
    update(next.id, { state: "uploading" });
    const form = new FormData();
    form.append("file", file, file.name);
    postForm<Job>(`/projects/${next.projectId}/documents/upload`, form)
      .then((job) => update(next.id, { state: "processing", jobId: job.id }))
      .catch((reason: unknown) => update(next.id, { state: "failed", error: errorMessage(reason, "Upload failed") }))
      .finally(() => {
        starting.current = false;
      });
  }, [items, update]);

  // Follow the running file until its last stage finishes, then let the next one start.
  const running = current(items);
  const runningId = running?.id;
  const runningJob = running?.jobId;
  const runningProject = running?.projectId;
  useEffect(() => {
    if (!runningId || !runningJob || !runningProject) return;
    let stopped = false;
    const check = async () => {
      try {
        const page = await getPage<Job>(withParams(`/projects/${runningProject}/jobs`, { limit: 100 }));
        const byId = new Map(page.items.map((job) => [job.id, job]));
        const start = byId.get(runningJob);
        if (!start || stopped) return;
        const chain = buildChain(start, byId);
        if (!chain.finished) return;
        const failedStage = chain.stages.find((stage) => stage.state === "failed" || stage.state === "cancelled");
        files.current.delete(runningId);
        update(runningId, failedStage ? { state: "failed", error: `${failedStage.label}: ${failedStage.message}` } : { state: "done" });
        settled.current?.(runningProject);
      } catch {
        /* a missed poll is retried on the next tick */
      }
    };
    void check();
    const timer = window.setInterval(() => void check(), POLL_MS);
    return () => {
      stopped = true;
      window.clearInterval(timer);
    };
  }, [runningId, runningJob, runningProject, update]);

  return { items, add, remove, dismiss };
}
