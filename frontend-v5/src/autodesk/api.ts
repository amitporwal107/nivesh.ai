/**
 * HTTP for the desk app.
 *
 * Two same-origin APIs, one sign-in (the main app's session cookie, plus the Bearer token the main app keeps in
 * localStorage when it has one):
 *   - the desk API at /autodesk/api/v1/…  (backend/autodesk, its own service)
 *   - three read-only calls to the main app: /api/auth/me (who is signed in) and /api/live/quotes (index quotes and
 *     the NSE session from the platform Kite feed).
 *
 * Errors are thrown as DeskApiError carrying the API's own code and message ({"error": "...", "message": "..."} from
 * the desk API, {"detail": ...} from FastAPI validation), so a screen can show what actually went wrong.
 */
import { getAuthToken } from "@/services/api/auth-token";

export const DESK_API = "/autodesk/api/v1";

export class DeskApiError extends Error {
  status: number;
  code: string;
  constructor(status: number, code: string, message: string) {
    super(message);
    this.name = "DeskApiError";
    this.status = status;
    this.code = code;
  }
}

function headers(init?: HeadersInit, json = false): Headers {
  const h = new Headers(init);
  const token = getAuthToken();
  if (token && !h.has("Authorization")) h.set("Authorization", `Bearer ${token}`);
  if (json && !h.has("Content-Type")) h.set("Content-Type", "application/json");
  h.set("Accept", "application/json");
  return h;
}

function messageOf(status: number, body: unknown, fallback: string): { code: string; message: string } {
  if (body && typeof body === "object") {
    const b = body as Record<string, unknown>;
    if (typeof b.error === "string") {
      return { code: b.error, message: typeof b.message === "string" ? b.message : b.error };
    }
    const d = b.detail;
    if (typeof d === "string") return { code: String(status), message: d };
    if (Array.isArray(d) && d.length) {
      const first = d[0] as Record<string, unknown>;
      const loc = Array.isArray(first.loc) ? first.loc.slice(1).join(".") : "";
      return { code: "INVALID", message: `${loc ? loc + ": " : ""}${String(first.msg ?? "invalid request")}` };
    }
    if (d && typeof d === "object") {
      const dd = d as Record<string, unknown>;
      if (typeof dd.message === "string") return { code: String(dd.error ?? status), message: dd.message };
    }
  }
  return { code: String(status), message: fallback };
}

async function request<T>(url: string, init: RequestInit = {}): Promise<T> {
  const hasBody = init.body !== undefined && init.body !== null;
  let res: Response;
  try {
    res = await fetch(url, { credentials: "include", ...init, headers: headers(init.headers, hasBody) });
  } catch (e) {
    throw new DeskApiError(0, "NETWORK", `Could not reach ${url.split("?")[0]}: ${(e as Error).message}`);
  }
  const text = await res.text();
  let body: unknown = null;
  if (text) {
    try {
      body = JSON.parse(text);
    } catch {
      body = null;
    }
  }
  if (!res.ok) {
    const { code, message } = messageOf(res.status, body, `${res.status} ${res.statusText || "error"} from ${url.split("?")[0]}`);
    throw new DeskApiError(res.status, code, message);
  }
  if (text && body === null) {
    throw new DeskApiError(res.status, "BAD_RESPONSE", `Unexpected response from ${url.split("?")[0]} (not JSON)`);
  }
  return body as T;
}

type Query = Record<string, string | number | boolean | null | undefined>;

export function qs(q?: Query): string {
  if (!q) return "";
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(q)) {
    if (v === undefined || v === null || v === "") continue;
    p.set(k, String(v));
  }
  const s = p.toString();
  return s ? `?${s}` : "";
}

/** GET on the desk API: deskGet("/signals", { min_score: 60 }). */
export function deskGet<T>(path: string, query?: Query): Promise<T> {
  return request<T>(`${DESK_API}${path}${qs(query)}`);
}

/** POST on the desk API with a JSON body. The body is sent exactly as given (the API forbids unknown fields). */
export function deskPost<T>(path: string, body?: unknown): Promise<T> {
  return request<T>(`${DESK_API}${path}`, { method: "POST", body: body === undefined ? undefined : JSON.stringify(body) });
}

/** GET on the main app's API (/api/…): only /auth/me and /live/quotes are used. */
export function mainGet<T>(path: string, query?: Query): Promise<T> {
  return request<T>(`/api${path}${qs(query)}`);
}

export const isUnauthorized = (e: unknown): boolean => e instanceof DeskApiError && e.status === 401;

export function errorText(e: unknown): string {
  if (e instanceof DeskApiError) return e.status ? `${e.message} (${e.status})` : e.message;
  if (e instanceof Error) return e.message;
  return String(e);
}
