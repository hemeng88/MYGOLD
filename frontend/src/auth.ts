const TOKEN_KEY = "mygold-token";
// 令牌失效时 api.ts 会派发这个事件，App 收到就切回登录页，不用整页刷新
export const UNAUTHORIZED_EVENT = "mygold-unauthorized";

export function getToken(): string {
  if (typeof window === "undefined") return "";
  return window.localStorage.getItem(TOKEN_KEY) || "";
}

export function setToken(token: string) {
  window.localStorage.setItem(TOKEN_KEY, token);
}

export function clearToken() {
  window.localStorage.removeItem(TOKEN_KEY);
}
