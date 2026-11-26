/**
 * Minimal API client. Authentication uses the httpOnly `atlas_session` cookie set by the API;
 * every state-changing request carries the X-Atlas-CSRF header required by the backend.
 */
export class ApiError extends Error {
  constructor(
    public status: number,
    public detail: unknown,
  ) {
    super(typeof detail === "string" ? detail : `Request failed (${status})`);
  }

  /** Flatten FastAPI validation / authorisation errors into readable messages. */
  get messages(): string[] {
    const d = this.detail as unknown;
    if (typeof d === "string") return [d];
    if (Array.isArray(d)) {
      return d.map((e: { loc?: unknown[]; msg?: string }) => `${(e.loc ?? []).slice(1).join(".")}: ${e.msg ?? ""}`);
    }
    if (d && typeof d === "object" && "authorization" in d) {
      return (d as { authorization: string[] }).authorization;
    }
    return [this.message];
  }
}

export async function api<T>(path: string, init: RequestInit & { json?: unknown } = {}): Promise<T> {
  const headers = new Headers(init.headers);
  headers.set("Accept", "application/json");
  const method = (init.method ?? "GET").toUpperCase();
  if (method !== "GET" && method !== "HEAD") headers.set("X-Atlas-CSRF", "1");
  let body = init.body;
  if (init.json !== undefined) {
    headers.set("Content-Type", "application/json");
    body = JSON.stringify(init.json);
  }
  const res = await fetch(path, { ...init, method, headers, body, credentials: "same-origin", cache: "no-store" });
  if (res.status === 401 && typeof window !== "undefined" && !path.endsWith("/auth/login")) {
    const next = encodeURIComponent(window.location.pathname + window.location.search);
    window.location.assign(`/login?next=${next}`);
  }
  if (!res.ok) {
    let detail: unknown = res.statusText;
    try {
      detail = (await res.json()).detail;
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(res.status, detail);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export function reportUrl(id: string, format: "json" | "csv" | "html" | "pdf"): string {
  return `/api/v1/investigations/${encodeURIComponent(id)}/report?format=${format}`;
}
