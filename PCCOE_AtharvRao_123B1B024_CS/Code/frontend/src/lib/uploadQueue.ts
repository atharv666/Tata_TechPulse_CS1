/** One file in the upload queue. Only one item is ever uploading/processing at a time. */
export type QueueState = "waiting" | "uploading" | "processing" | "done" | "failed";

export interface QueueItem {
  id: string;
  projectId: string;
  name: string;
  size: number;
  state: QueueState;
  /** The ingestion job started for this file (set once uploaded). */
  jobId?: string;
  error?: string;
}

export const isBusy = (item: QueueItem): boolean => item.state === "uploading" || item.state === "processing";

/** The next file to start, or ``undefined`` while one is still being processed. */
export function nextToStart(items: QueueItem[]): QueueItem | undefined {
  if (items.some(isBusy)) return undefined;
  return items.find((item) => item.state === "waiting");
}

export const current = (items: QueueItem[]): QueueItem | undefined => items.find(isBusy);

export function counts(items: QueueItem[]): { waiting: number; done: number; failed: number } {
  return {
    waiting: items.filter((item) => item.state === "waiting").length,
    done: items.filter((item) => item.state === "done").length,
    failed: items.filter((item) => item.state === "failed").length,
  };
}

let counter = 0;
export function newItem(projectId: string, file: { name: string; size: number }): QueueItem {
  counter += 1;
  return { id: `${Date.now()}-${counter}`, projectId, name: file.name, size: file.size, state: "waiting" };
}

/** Drop finished items so the list does not grow forever; keeps waiting and running ones. */
export function withoutFinished(items: QueueItem[]): QueueItem[] {
  return items.filter((item) => item.state === "waiting" || isBusy(item));
}
