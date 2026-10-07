import type { ApiError, PageResponse } from "../types/api";

const baseUrl = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000/api/v1";
const userId = import.meta.env.VITE_USER_ID ?? "engineering-user";

export class BackendError extends Error {
  constructor(public readonly data: ApiError, public readonly status: number) { super(data.message); }
}

export async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch(`${baseUrl}${path}`, {
    ...options,
    headers: { "Content-Type": "application/json", "X-User-Id": userId, ...options.headers },
  });
  if (!response.ok) {
    const data = await response.json().catch(() => ({ code: "NETWORK_ERROR", message: response.statusText }));
    throw new BackendError(data as ApiError, response.status);
  }
  return response.json() as Promise<T>;
}

export const getPage = <T>(path: string) => api<PageResponse<T>>(path);
export const post = <T>(path: string, body?: unknown) => api<T>(path, { method: "POST", body: body === undefined ? undefined : JSON.stringify(body) });

export async function postForm<T>(path: string, body: FormData): Promise<T> {
  const response = await fetch(`${baseUrl}${path}`, {
    method: "POST",
    headers: { "X-User-Id": userId },
    body,
  });
  if (!response.ok) {
    const data = await response.json().catch(() => ({ code: "NETWORK_ERROR", message: response.statusText }));
    throw new BackendError(data as ApiError, response.status);
  }
  return response.json() as Promise<T>;
}
