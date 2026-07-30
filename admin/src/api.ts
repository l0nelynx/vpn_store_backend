let accessToken: string | null = null;
let refreshPromise: Promise<boolean> | null = null;

export function getToken() { return accessToken; }
export function setToken(token: string) { accessToken = token; }
export function clearToken() { accessToken = null; }

async function refresh(): Promise<boolean> {
  if (!refreshPromise) {
    refreshPromise = fetch("/store/api/admin/refresh", {
      method: "POST", credentials: "include",
    }).then(async (res) => {
      if (!res.ok) return false;
      const data = await res.json() as { token: string };
      setToken(data.token);
      return true;
    }).finally(() => { refreshPromise = null; });
  }
  return refreshPromise;
}

export async function restoreSession() { return getToken() ? true : refresh(); }

export async function api<T = unknown>(path: string, options: RequestInit = {}, retry = true): Promise<T> {
  const headers = new Headers(options.headers || {});
  if (options.body && !(options.body instanceof FormData)) headers.set("Content-Type", "application/json");
  if (accessToken) headers.set("Authorization", `Bearer ${accessToken}`);
  const res = await fetch(path, { ...options, headers, credentials: "include" });
  if (res.status === 401 && retry && !path.includes("/session") && await refresh()) {
    return api<T>(path, options, false);
  }
  if (!res.ok) {
    const body = await res.json().catch(() => null) as { detail?: string } | null;
    throw new Error(body?.detail || res.statusText || "Request failed");
  }
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}
