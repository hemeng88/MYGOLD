import { Capacitor } from "@capacitor/core";
import type { FundDetail, FundFavorite, FundList, FundRank, FundRankRefreshResult, FundRefreshResult, FundSearchItem } from "./types";

const STORAGE_KEY = "mygold-api-base";
const NATIVE_DEFAULT = "http://49.232.222.121";

export function apiBase(): string {
  if (typeof window !== "undefined") {
    const saved = window.localStorage.getItem(STORAGE_KEY);
    if (saved) return saved.replace(/\/$/, "");
  }
  const fromEnv = String(import.meta.env.VITE_API_BASE || "").replace(/\/$/, "");
  if (fromEnv) return fromEnv;
  if (typeof window !== "undefined" && Capacitor.isNativePlatform()) return NATIVE_DEFAULT;
  return "";
}

export function setApiBase(url: string) {
  const next = url.trim().replace(/\/$/, "");
  if (next) window.localStorage.setItem(STORAGE_KEY, next);
  else window.localStorage.removeItem(STORAGE_KEY);
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${apiBase()}${path}`, init);
  } catch {
    throw new Error(`连不上 ${apiBase() || "服务器"}。点顶部「改地址」选 IP 后再试。`);
  }
  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || `请求失败 ${res.status}`);
  }
  return res.json() as Promise<T>;
}

export const api = {
  funds: () => request<FundList>("/api/funds"),
  fund: (code: string) => request<FundDetail>(`/api/funds/${code}`),
  searchFunds: (q: string) => request<FundSearchItem[]>(`/api/funds/search?q=${encodeURIComponent(q)}`),
  addFund: (code: string) =>
    request<FundFavorite>("/api/funds/favorites", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ code }),
    }),
  deleteFund: (code: string) => request<{ ok: boolean }>(`/api/funds/favorites/${code}`, { method: "DELETE" }),
  saveFundPosition: (code: string, shares: number | null, costPrice: number | null) =>
    request<FundFavorite>(`/api/funds/favorites/${code}/position`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ shares, cost_price: costPrice }),
    }),
  refreshFunds: (includeHoldings = false) =>
    request<FundRefreshResult>(`/api/funds/refresh?include_holdings=${includeHoldings}`, { method: "POST" }),
  fundRankings: (period?: string) =>
    request<FundRank>(period ? `/api/funds/rankings?period=${period}` : "/api/funds/rankings"),
  refreshFundRankings: () =>
    request<FundRankRefreshResult>("/api/funds/rankings/refresh", { method: "POST" }),
};
