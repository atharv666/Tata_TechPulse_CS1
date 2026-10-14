import type { ApiError, PageResponse } from "../types/api";

const baseUrl = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000/api/v1";
const userId = import.meta.env.VITE_USER_ID ?? "engineering-user";

export class BackendError extends Error {
  constructor(public readonly data: ApiError, public readonly status: number) {
    super(data.message);
  }
  get code(): string {
    return this.data.code;
  }
}

async function failure(response: Response): Promise<BackendError> {
  const data = await response.json().catch(() => ({ code: "NETWORK_ERROR", message: response.statusText }));
  return new BackendError(data as ApiError, response.status);
}

export async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch(`${baseUrl}${path}`, {
    ...options,
    headers: { "Content-Type": "application/json", "X-User-Id": userId, ...options.headers },
  });
  if (!response.ok) throw await failure(response);
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export const getPage = <T>(path: string) => api<PageResponse<T>>(path);
export const get = <T>(path: string) => api<T>(path);
export const post = <T>(path: string, body?: unknown) =>
  api<T>(path, { method: "POST", body: body === undefined ? undefined : JSON.stringify(body) });

/** Query-string helper that skips empty values (`?q=` would otherwise filter on nothing). */
export function withParams(path: string, params: Record<string, string | number | boolean | undefined | null>): string {
  const entries = Object.entries(params).filter(([, value]) => value !== undefined && value !== null && value !== "");
  if (!entries.length) return path;
  const query = new URLSearchParams(entries.map(([key, value]) => [key, String(value)]));
  return `${path}${path.includes("?") ? "&" : "?"}${query.toString()}`;
}

export interface AllPages<T> {
  items: T[];
  total: number;
  /** True when ``total`` exceeded the cap and only the first ``items.length`` were loaded. */
  truncated: boolean;
}

/** Follow ``offset``/``limit`` until everything (or ``cap`` items) is loaded. */
export async function getAll<T>(path: string, cap = 500, pageSize = 100): Promise<AllPages<T>> {
  const items: T[] = [];
  let total = 0;
  while (items.length < cap) {
    const page = await getPage<T>(withParams(path, { offset: items.length, limit: pageSize }));
    total = page.total;
    items.push(...page.items);
    if (!page.items.length || items.length >= page.total) break;
  }
  return { items: items.slice(0, cap), total, truncated: total > cap };
}

export async function postForm<T>(path: string, body: FormData): Promise<T> {
  const response = await fetch(`${baseUrl}${path}`, { method: "POST", headers: { "X-User-Id": userId }, body });
  if (!response.ok) throw await failure(response);
  return response.json() as Promise<T>;
}

/** Download a file through the API (the user header cannot be sent by a plain link). */
export async function download(path: string, filename: string): Promise<void> {
  const response = await fetch(`${baseUrl}${path}`, { headers: { "X-User-Id": userId } });
  if (!response.ok) throw await failure(response);
  const url = URL.createObjectURL(await response.blob());
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}

export function errorMessage(reason: unknown, fallback: string): string {
  if (reason instanceof BackendError) return `${reason.message} (${reason.code})`;
  return reason instanceof Error ? reason.message : fallback;
}
