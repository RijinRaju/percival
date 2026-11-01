// Thin fetch wrapper. The session cookie rides along automatically, writes
// also need the csrf token we get from /auth/me or /auth/login.

let csrfToken: string | null = null;

export function setCsrf(token: string | null) {
  csrfToken = token;
}

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

type Detail = string | { loc?: (string | number)[]; msg: string }[] | undefined;

function readDetail(detail: Detail, fallback: string): string {
  if (!detail) return fallback;
  if (typeof detail === "string") return detail;
  // pydantic validation errors: "schedule.minute: value error, ..."
  return detail
    .map((d) => {
      const where = (d.loc ?? []).filter((p) => p !== "body").join(".");
      const msg = d.msg.replace(/^Value error, /, "");
      return where ? `${where}: ${msg}` : msg;
    })
    .join("; ");
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const headers: Record<string, string> = { Accept: "application/json" };
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (method !== "GET" && csrfToken) headers["X-CSRF-Token"] = csrfToken;

  const resp = await fetch(`/api/v1${path}`, {
    method,
    headers,
    credentials: "same-origin",
    body: body === undefined ? undefined : JSON.stringify(body),
  });

  if (resp.status === 204) return undefined as T;
  const data = await resp.json().catch(() => null);
  if (!resp.ok) {
    throw new ApiError(resp.status, readDetail(data?.detail, `${resp.status} ${resp.statusText}`));
  }
  return data as T;
}

export const api = {
  get: <T>(path: string) => request<T>("GET", path),
  post: <T>(path: string, body?: unknown) => request<T>("POST", path, body ?? {}),
  patch: <T>(path: string, body: unknown) => request<T>("PATCH", path, body),
  put: <T>(path: string, body: unknown) => request<T>("PUT", path, body),
  del: (path: string) => request<void>("DELETE", path),
};

export function qs(params: Record<string, string | number | undefined | null | string[]>) {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === "") continue;
    if (Array.isArray(value)) value.forEach((v) => search.append(key, v));
    else search.set(key, String(value));
  }
  const s = search.toString();
  return s ? `?${s}` : "";
}

export const enc = encodeURIComponent;
