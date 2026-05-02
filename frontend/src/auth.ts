/**
 * Tiny auth client. JWT lives in localStorage; every API call sends it as
 * `Authorization: Bearer <token>` via the `authedFetch` wrapper.
 */
const TOKEN_KEY = "hitl-auth-token";
const USER_KEY = "hitl-auth-user";

export interface AuthUser {
  id: number;
  username: string;
  role: string;
  display_name: string | null;
}

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string) {
  localStorage.setItem(TOKEN_KEY, token);
}

export function clearAuth() {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(USER_KEY);
}

export function getUser(): AuthUser | null {
  const raw = localStorage.getItem(USER_KEY);
  if (!raw) return null;
  try { return JSON.parse(raw); } catch { return null; }
}

export function setUser(user: AuthUser) {
  localStorage.setItem(USER_KEY, JSON.stringify(user));
}

/**
 * fetch wrapper that adds the bearer token to every request.
 *
 * On a 401 response (token expired or revoked), clears the cached auth
 * state and dispatches an `auth-expired` window event. The App listens
 * for that event and bounces the user back to the login screen — no
 * extra plumbing needed at every callsite.
 */
export async function authedFetch(input: RequestInfo, init?: RequestInit): Promise<Response> {
  const token = getToken();
  const headers = new Headers(init?.headers || {});
  if (token) headers.set("Authorization", `Bearer ${token}`);
  const resp = await fetch(input, { ...init, headers });
  if (resp.status === 401 && getToken()) {
    // Best-effort cleanup. Don't block the original caller.
    clearAuth();
    window.dispatchEvent(new CustomEvent("auth-expired"));
  }
  return resp;
}

export async function login(username: string, password: string): Promise<{ token: string; user: AuthUser }> {
  const body = new URLSearchParams({ username, password, grant_type: "password" });
  const resp = await fetch("/api/auth/login", {
    method: "POST",
    headers: { "content-type": "application/x-www-form-urlencoded" },
    body: body.toString(),
  });
  if (!resp.ok) {
    const text = await resp.text();
    throw new Error(`${resp.status}: ${text}`);
  }
  const data = await resp.json();
  setToken(data.access_token);
  setUser(data.user);
  return { token: data.access_token, user: data.user };
}

export async function register(username: string, password: string, displayName?: string): Promise<{ token: string; user: AuthUser }> {
  const resp = await fetch("/api/auth/register", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ username, password, display_name: displayName }),
  });
  if (!resp.ok) {
    const text = await resp.text();
    throw new Error(`${resp.status}: ${text}`);
  }
  const data = await resp.json();
  setToken(data.access_token);
  setUser(data.user);
  return { token: data.access_token, user: data.user };
}

export async function fetchMe(): Promise<AuthUser | null> {
  if (!getToken()) return null;
  try {
    const resp = await authedFetch("/api/auth/me");
    if (!resp.ok) return null;
    const u = await resp.json();
    setUser(u);
    return u;
  } catch {
    return null;
  }
}

/**
 * Server-side logout: blocklists the current token's jti so it can't be
 * reused even if a copy was stolen. Best-effort — clears local state
 * regardless of whether the server call succeeds.
 */
export async function logout(): Promise<void> {
  try {
    await authedFetch("/api/auth/logout", { method: "POST" });
  } catch {
    // Network failure shouldn't block the user from logging out locally.
  }
  clearAuth();
}
