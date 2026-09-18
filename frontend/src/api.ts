import { Capacitor } from "@capacitor/core";
import { UNAUTHORIZED_EVENT, clearToken, getToken, setToken } from "./auth";
import type { Exposure, FundDetail, FundFavorite, FundList, FundRank, FundRankRefreshResult, FundRefreshResult, FundSearchItem, LoginResult, Me } from "./types";

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
  exposure: (signal?: AbortSignal) => request<Exposure>("/api/funds/exposure", { signal }),
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
  fundRankings: (period?: string, signal?: AbortSignal) =>
    request<FundRank>(period ? `/api/funds/rankings?period=${period}` : "/api/funds/rankings", { signal }),
  refreshFundRankings: () =>
    request<FundRankRefreshResult>("/api/funds/rankings/refresh", { method: "POST" }),
};
