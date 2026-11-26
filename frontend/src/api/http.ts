import { config } from "../app/config";
import { mockFetch } from "../mocks/handlers";
import { ApiError } from "./errors";

/** edge = local station backend (Operator) ; core = central server (Supervisor, AI Leader). */
export type ApiTarget = "edge" | "core";

export async function request<T>(target: ApiTarget, path: string, init: RequestInit = {}): Promise<T> {
  if (config.mode === "mock") return mockFetch<T>(target, path, init);

  const base = target === "edge" ? config.edgeBaseUrl : config.coreBaseUrl;
  const isJson = typeof init.body === "string";
  const response = await fetch(`${base}${path}`, {
    ...init,
    headers: {
      Accept: "application/json",
      ...(isJson ? { "Content-Type": "application/json" } : {}),
      ...init.headers,
    },
  });
  if (!response.ok) {
    let detail = await response.text();
    try {
      detail = JSON.stringify(JSON.parse(detail).detail ?? detail);
    } catch {
      // not JSON: keep the raw text
    }
    throw new ApiError(response.status, detail);
  }
  return (await response.json()) as T;
}

export function query(params: Record<string, string | number | boolean | undefined | null>): string {
  const entries = Object.entries(params).filter(([, v]) => v !== undefined && v !== null);
  return entries.length ? `?${new URLSearchParams(entries.map(([k, v]) => [k, String(v)]))}` : "";
}
