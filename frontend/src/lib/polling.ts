export interface PollOptions {
  intervalMs?: number;
  maxAttempts?: number;
  /** Injected so tests do not wait. */
  sleep?: (ms: number) => Promise<void>;
}

export class PollTimeout extends Error {
  constructor(public readonly attempts: number) {
    super(`Still not finished after ${attempts} checks.`);
  }
}

/** Call ``load`` until ``done`` accepts the result; bounded, never an endless loop. */
export async function pollUntil<T>(
  load: () => Promise<T>,
  done: (value: T) => boolean,
  { intervalMs = 1500, maxAttempts = 120, sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms)) }: PollOptions = {},
): Promise<T> {
  for (let attempt = 1; attempt <= maxAttempts; attempt += 1) {
    const value = await load();
    if (done(value)) return value;
    if (attempt < maxAttempts) await sleep(intervalMs);
  }
  throw new PollTimeout(maxAttempts);
}

export const JOB_FINISHED = ["COMPLETED", "FAILED", "CANCELLED"];
export const isFinished = (state: string): boolean => JOB_FINISHED.includes(state);
