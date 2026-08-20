import type { CollectResult, CurveResponse, DaySummary, LatestQuote } from "./types";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, init);
  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || `请求失败 ${res.status}`);
  }
  return res.json() as Promise<T>;
}

export const api = {
  latest: () => request<LatestQuote>("/api/quote/latest"),
  days: () => request<DaySummary[]>("/api/days"),
  curve: (date?: string) => request<CurveResponse>(date ? `/api/curve?date=${date}` : "/api/curve"),
  collect: () =>
    request<CollectResult>("/api/collect", {
      method: "POST",
    }),
};
