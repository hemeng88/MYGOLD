import { Capacitor } from "@capacitor/core";
import type { AIProfile, AIProfileInput, AIProfileSettings, HoldingAnalysis, SingleStockReview, StockSignals, StockPortfolioConfig, StockPortfolioJob, StockSimConfig, StockSimPeriod, StockSimView } from "./types";
import { UNAUTHORIZED_EVENT, clearToken, getToken, setToken } from "./auth";
import type { FundDetail, FundFavorite, FundList, FundRefreshResult, FundSearchItem, CountdownItem, CountdownPayload, LoginResult, MainboardDetail, MainboardList, MainboardPeriod, MainboardRefreshResult, MainboardSearchItem, Me } from "./types";

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

/** 后端错误体是 {"detail":"..."}，直接抛原文会把 JSON 弹到界面上。 */
function errorMessage(text: string, fallback: string): string {
  try {
    const parsed = JSON.parse(text);
    if (typeof parsed?.detail === "string" && parsed.detail) return parsed.detail;
  } catch {
    // 不是 JSON 就按纯文本处理
  }
  return text || fallback;
}

/**
 * isLogin 用来区分两种 401：
 * 登录接口的 401 是「密码错」，不能当成登录过期去清令牌、跳登录页，
 * 否则输错密码会看到「登录已过期」这种莫名其妙的提示。
 */
async function request<T>(path: string, init?: RequestInit, isLogin = false): Promise<T> {
  const headers = new Headers(init?.headers || {});
  const token = getToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  let res: Response;
  try {
    res = await fetch(`${apiBase()}${path}`, { ...init, headers });
  } catch (err) {
    if (init?.signal?.aborted) throw err;
    throw new Error(`连不上 ${apiBase() || "服务器"}，检查网络或服务器状态。`);
  }
  if (res.status === 401 && !isLogin) {
    // 令牌过期、被改过或账号已不存在：清掉并让 App 切回登录页
    clearToken();
    window.dispatchEvent(new Event(UNAUTHORIZED_EVENT));
    throw new Error("登录已过期，请重新登录");
  }
  if (!res.ok) {
    const text = await res.text();
    throw new Error(errorMessage(text, isLogin ? "账号或密码不对" : `请求失败 ${res.status}`));
  }
  return res.json() as Promise<T>;
}

export const api = {
  aiProfiles: (signal?: AbortSignal) => request<AIProfileSettings>("/api/settings/ai/profiles", { signal }),
  saveAIProfile: (config: AIProfileInput, id?: string) =>
    request<AIProfile>(`/api/settings/ai/profiles${id ? "/" + encodeURIComponent(id) : ""}`, {
      method: id ? "PUT" : "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(config),
    }),
  deleteAIProfile: (id: string) => request<{ ok: boolean }>(`/api/settings/ai/profiles/${encodeURIComponent(id)}`, { method: "DELETE" }),
  testAIProfile: (id: string, action: "test" | "test-generation") =>
    request<{ ok: boolean; message: string }>(`/api/settings/ai/profiles/${encodeURIComponent(id)}/${action}`, { method: "POST" }),
  stockSignals: (signal?: AbortSignal, mode = "intraday") => request<StockSignals>(`/api/stocks/signals?mode=${mode}`, { signal }),
  stockPortfolioStatus: (signal: AbortSignal) => request<StockPortfolioJob>("/api/stocks/portfolio-study", { signal }),
  stockSimulator: (period: StockSimPeriod, signal: AbortSignal) =>
    request<StockSimView>(`/api/stocks/simulator?period=${period}`, { signal }),
  saveStockSimulator: (config: StockSimConfig) =>
    request<{ ok: boolean }>("/api/stocks/simulator/config", {
      method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(config),
    }),
  setStockSimulatorRunning: (running: boolean) =>
    request<{ ok: boolean }>("/api/stocks/simulator/run", {
      method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ running }),
    }),
  startStockPortfolio: (mode: "intraday" | "close", config: StockPortfolioConfig) =>
    request<StockPortfolioJob>(`/api/stocks/portfolio-study?mode=${mode}`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(config),
    }),
  singleStockPreview: (code: string) =>
    request<SingleStockReview>(`/api/stocks/single-analysis/${encodeURIComponent(code)}`),
  singleStockAnalysis: (code: string, snapshotId: string, profileIds: string[]) =>
    request<SingleStockReview>(`/api/stocks/single-analysis/${encodeURIComponent(code)}/analyze?${new URLSearchParams({ snapshot_id: snapshotId })}`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ profile_ids: profileIds }),
    }),
  singleStockStatus: (code: string, snapshotId: string, signal: AbortSignal) =>
    request<SingleStockReview>(`/api/stocks/single-analysis/${encodeURIComponent(code)}/status?${new URLSearchParams({ snapshot_id: snapshotId })}`, { signal }),
  refreshStockSignals: (mode = "intraday") => request<StockSignals>(`/api/stocks/signals/refresh?mode=${mode}`, { method: "POST" }),
  analyzeStockSignals: (mode: "intraday" | "close", snapshotId: string, codes: string[], profileIds: string[]) =>
    request<StockSignals>(`/api/stocks/signals/analyze?${new URLSearchParams({ mode, snapshot_id: snapshotId })}`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ codes, profile_ids: profileIds }),
    }),
  saveStockPrices: (price_min: number, price_max: number | null) => request<{ price_min: number; price_max: number | null }>("/api/stocks/signals/prices", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ price_min, price_max }) }),
  saveStockBoards: (boards: string[]) => request<{ boards: string[] }>("/api/stocks/signals/preferences", {
    method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ boards }),
  }),
  login: async (username: string, password: string) => {
    const result = await request<LoginResult>(
      "/api/auth/login",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username, password }),
      },
      true,
    );
    setToken(result.token);
    return result;
  },
  me: () => request<Me>("/api/auth/me"),
  logout: () => clearToken(),
  funds: (signal?: AbortSignal) => request<FundList>("/api/funds", { signal }),
  holdingPreview: (code: string, signal: AbortSignal) =>
    request<HoldingAnalysis>(`/api/funds/favorites/${encodeURIComponent(code)}/holding-analysis`, { signal }),
  holdingAnalysisStatus: (code: string, snapshotId: string, signal: AbortSignal) =>
    request<HoldingAnalysis>(`/api/funds/favorites/${encodeURIComponent(code)}/holding-analysis/status?${new URLSearchParams({ snapshot_id: snapshotId })}`, { signal }),
  analyzeHolding: (code: string, snapshotId: string, profileIds: string[]) =>
    request<HoldingAnalysis>(`/api/funds/favorites/${encodeURIComponent(code)}/holding-analysis/analyze?${new URLSearchParams({ snapshot_id: snapshotId })}`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ profile_ids: profileIds }),
    }),
  fund: (code: string, signal?: AbortSignal) => request<FundDetail>(`/api/funds/${code}`, { signal }),
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
  mainboard: (period: MainboardPeriod, signal?: AbortSignal) =>
    request<MainboardList>(`/api/stocks/mainboard?period=${period}`, { signal }),
  searchStocks: (q: string, signal?: AbortSignal) =>
    request<MainboardSearchItem[]>(`/api/stocks/search?q=${encodeURIComponent(q)}`, { signal }),
  mainboardDetail: (code: string, period: MainboardPeriod, signal?: AbortSignal) =>
    request<MainboardDetail>(`/api/stocks/mainboard/${encodeURIComponent(code)}?period=${period}`, { signal }),
  refreshMainboard: (includeKlines = false) =>
    request<MainboardRefreshResult>(`/api/stocks/mainboard/refresh?include_klines=${includeKlines}`, {
      method: "POST",
    }),
  countdowns: (signal?: AbortSignal) => request<CountdownItem[]>("/api/misc/countdowns", { signal }),
  addCountdown: (payload: CountdownPayload) =>
    request<CountdownItem>("/api/misc/countdowns", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
  updateCountdown: (id: number, payload: CountdownPayload) =>
    request<CountdownItem>(`/api/misc/countdowns/${id}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
  deleteCountdown: (id: number) => request<{ ok: boolean }>(`/api/misc/countdowns/${id}`, { method: "DELETE" }),
};
