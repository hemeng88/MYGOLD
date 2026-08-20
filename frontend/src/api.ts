import type { CollectResult, CurveResponse, DaySummary, FeeRule, GoldLot, HoldingSummary, LatestQuote, MarketEvent } from "./types";

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
  rules: () => request<FeeRule>("/api/rules"),
  events: (date?: string) =>
    request<MarketEvent[]>(date ? `/api/events?date=${date}` : "/api/events"),
  holdings: () => request<HoldingSummary>("/api/holdings"),
  addLot: (payload: { grams: number; buy_price: number; bought_at: string; note?: string }) =>
    request<GoldLot>("/api/holdings/lots", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
  deleteLot: (id: number) => request<{ ok: boolean }>(`/api/holdings/lots/${id}`, { method: "DELETE" }),
};
