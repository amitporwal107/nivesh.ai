/**
 * HTTP client.
 *
 * - `credentials: include` — cookie session (name `session`) auto-attached
 * - AbortController timeout
 * - Correlation ID + observability events on every call
 * - FastAPI `{ detail }` envelope normalisation via ApiError.fromResponse
 * - Optional ETag pass-through for cache-aware endpoints (insights/v3-portfolio)
 * - Bounded retry on transient (network / 5xx / 429) — does NOT retry 4xx
 */
import { apiConfig } from "./config";
import { ApiError } from "./errors";
import { getAuthToken } from "./auth-token";
import { correlationId, getObserver } from "@/lib/observability";
import { useImpersonationStore } from "@/stores/impersonation.store";
import { useLoggingStore } from "@/stores/logging.store";

export interface HttpRequest {
  method?: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
  path: string;                 // e.g. "/api/portfolio/holdings"
  query?: Record<string, string | number | boolean | undefined>;
  body?: unknown;
  headers?: Record<string, string>;
  /** Pass an ETag to send `If-None-Match`. Returns 304 → cached payload (caller decides). */
  ifNoneMatch?: string;
  /** Override default timeout (ms). */
  timeoutMs?: number;
  /** Skip retry (e.g. POST /auth/google). */
  noRetry?: boolean;
  /** Signal from caller (React Query passes one). */
  signal?: AbortSignal;
}

export interface HttpResponse<T> {
  status: number;
  data: T;
  etag?: string;
  notModified?: boolean;
  correlationId: string;
}

export async function http<T = unknown>(req: HttpRequest): Promise<HttpResponse<T>> {
  const id = correlationId();
  const url = buildUrl(req.path, req.query);
  const method = req.method ?? "GET";
  const authToken = getAuthToken();
  // Per-request impersonation: when an advisor is viewing a client, carry the
  // active client profile on every request. The backend validates ownership
  // and resolves the effective user. Single source of truth = the store; no
  // session-token coupling.
  const activeProfileId = useImpersonationStore.getState().profileId;
  // Session logging (Settings → Logs & Diagnostics): when the user has it on,
  // echo the debug-session id so the backend buffers this session's server logs.
  const logging = useLoggingStore.getState();
  const debugSid = logging.enabled ? logging.sid : null;
  const headers: Record<string, string> = {
    Accept: "application/json",
    "X-Correlation-Id": id,
    "X-Client-Version": apiConfig.appVersion,
    // Bearer fallback for native (WebView drops the cross-site session cookie).
    ...(authToken ? { Authorization: `Bearer ${authToken}` } : {}),
    ...(activeProfileId ? { "X-Active-Profile": activeProfileId } : {}),
    ...(debugSid ? { "X-Nivesh-Debug-Session": debugSid } : {}),
    ...(req.body != null ? { "Content-Type": "application/json" } : {}),
    ...(req.ifNoneMatch ? { "If-None-Match": req.ifNoneMatch } : {}),
    ...(req.headers ?? {}),
  };

  const obs = getObserver();
  const attempts = req.noRetry ? 1 : Math.max(1, apiConfig.retry.attempts + 1);

  let lastErr: unknown;
  for (let attempt = 0; attempt < attempts; attempt++) {
    const startedAt = performance.now();
    obs.onRequestStart({ correlationId: id, method, url, startedAt });

    const timeoutCtrl = new AbortController();
    const timeoutMs = req.timeoutMs ?? apiConfig.requestTimeoutMs;
    const timeoutHandle = setTimeout(() => timeoutCtrl.abort(), timeoutMs);
    const signal = req.signal
      ? anyAbortSignal([req.signal, timeoutCtrl.signal])
      : timeoutCtrl.signal;

    try {
      const res = await fetch(url, {
        method,
        headers,
        credentials: "include",
        body: req.body != null ? JSON.stringify(req.body) : undefined,
        signal,
      });
      clearTimeout(timeoutHandle);
      const durationMs = performance.now() - startedAt;
      obs.onRequestEnd({ correlationId: id, method, url, startedAt, durationMs, status: res.status });

      if (res.status === 304) {
        return { status: 304, data: undefined as unknown as T, notModified: true, etag: req.ifNoneMatch, correlationId: id };
      }

      if (!res.ok) {
        const body = await safeJson(res);
        const err = ApiError.fromResponse(res, body, id);
        // retry on 5xx / 429 only if attempts remain
        if (shouldRetry(err) && attempt < attempts - 1) {
          lastErr = err;
          await delay(backoff(attempt));
          continue;
        }
        throw err;
      }

      const etag = res.headers.get("etag") ?? undefined;
      const data = (await safeJson(res)) as T;
      return { status: res.status, data, etag, correlationId: id };
    } catch (err) {
      clearTimeout(timeoutHandle);
      const durationMs = performance.now() - startedAt;
      obs.onRequestError({ correlationId: id, method, url, startedAt, durationMs, error: err });

      if (err instanceof ApiError) {
        if (shouldRetry(err) && attempt < attempts - 1) {
          lastErr = err;
          await delay(backoff(attempt));
          continue;
        }
        throw err;
      }
      if (isAbort(err)) {
        if (req.signal?.aborted) throw err;       // caller cancellation — re-throw
        throw ApiError.timeout(id);
      }
      const wrapped = ApiError.network(err, id);
      if (attempt < attempts - 1) {
        lastErr = wrapped;
        await delay(backoff(attempt));
        continue;
      }
      throw wrapped;
    }
  }
  throw lastErr ?? new ApiError("unknown", "Exhausted retries");
}

function buildUrl(path: string, query?: HttpRequest["query"]): string {
  const u = new URL(path, apiConfig.baseUrl);
  if (query) {
    for (const [k, v] of Object.entries(query)) {
      if (v === undefined || v === null || v === "") continue;
      u.searchParams.append(k, String(v));
    }
  }
  return u.toString();
}

async function safeJson(res: Response): Promise<unknown> {
  const text = await res.text();
  if (!text) return undefined;
  try { return JSON.parse(text); } catch { return text; }
}

function shouldRetry(err: ApiError): boolean {
  // 429 is intentional — retrying without Retry-After just burns the same budget again
  return err.kind === "network" || err.kind === "server" || err.kind === "timeout";
}

function backoff(attempt: number): number {
  const base = apiConfig.retry.baseDelayMs;
  return base * 2 ** attempt + Math.random() * base;
}

function delay(ms: number): Promise<void> {
  return new Promise((r) => setTimeout(r, ms));
}

function isAbort(err: unknown): boolean {
  return err instanceof DOMException && err.name === "AbortError";
}

function anyAbortSignal(signals: AbortSignal[]): AbortSignal {
  // AbortSignal.any() is Baseline 2024; fall back for older browsers.
  const Any = (AbortSignal as unknown as { any?: (s: AbortSignal[]) => AbortSignal }).any;
  if (Any) return Any(signals);
  const ctrl = new AbortController();
  for (const s of signals) {
    if (s.aborted) { ctrl.abort(s.reason); return ctrl.signal; }
    s.addEventListener("abort", () => ctrl.abort(s.reason), { once: true });
  }
  return ctrl.signal;
}
