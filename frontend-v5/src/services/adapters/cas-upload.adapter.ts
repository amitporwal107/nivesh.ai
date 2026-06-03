/**
 * CAS Connect adapter — matches the V4 frontend pattern in
 * `frontend/src/v4/api/portfolioIngestion.js`.
 *
 * Real endpoints (login-onboarding.yaml + V4 frontend code):
 *   POST /api/casparser/access-token   → mint widget token
 *   POST /api/cas/sdk-callback         → ingest widget output (the ACTUAL endpoint
 *                                         used by V4, supersedes /import-connect)
 *   POST /api/portfolio/upload         → CSV/Excel synchronous import only
 *   GET  /api/portfolio/upload-status/{task_id}
 *   GET  /api/portfolio/upload-latest-task
 *   GET  /api/portfolio/me             → active portfolio + snapshot
 *
 * Three onboarding modes — same surface area as V4:
 *   "cas"   – PDF via CAS Connect widget (file upload)
 *   "gmail" – Gmail inbox scan via CAS Connect widget (OAuth popup)
 *   "cdsl"  – CDSL OTP fetch via CAS Connect widget
 *
 * The widget is `@cas-parser/connect`, lazy-loaded and configured with the
 * minted token. The widget posts its parsed JSON to `/api/cas/sdk-callback`,
 * NOT to `/api/portfolio/import-connect` (which exists for raw-JSON re-imports).
 */
import { apiConfig } from "@/services/api/config";
import { http } from "@/services/api/http";
import { ApiError } from "@/services/api/errors";
import { correlationId, getObserver } from "@/lib/observability";

export type CasMode = "cas" | "gmail" | "cdsl";

export type UploadTaskStatus = "processing" | "completed" | "failed" | string;

export interface ActivePortfolioRes {
  snapshot?: {
    period?: string;
    statement_to?: string;
    is_active?: boolean;
    total_value?: number | string;
  } | null;
  portfolio?: {
    holdings_count?: number;
    total_value?: number | string;
    allocation?: unknown;
    top_holdings?: unknown[];
  } | null;
}

export interface CasUploadAdapter {
  /** Active portfolio + most recent snapshot. Drives the
   *  "already set up" vs "show import cards" routing. */
  getActivePortfolio(): Promise<ActivePortfolioRes>;

  /** CSV / Excel synchronous upload. PDF returns 410 Gone. */
  uploadFile(file: File, portfolioId?: string): Promise<{
    message: string;
    count: number;
    holdings: unknown[];
  }>;

  /** Mint short-lived token for the @cas-parser/connect widget. */
  getConnectToken(): Promise<{ access_token: string; expires_in: number }>;

  /** Submit the widget-parsed payload (canonical endpoint per V4 codebase). */
  sdkCallback(args: { mode: CasMode; payload: unknown; portfolio_id?: string; idempotencyKey?: string }): Promise<unknown>;

  /** Legacy raw-JSON ingestion path. Prefer sdkCallback for new code. */
  importConnect(args: { data: unknown; portfolio_id?: string; idempotencyKey?: string }): Promise<unknown>;

  status(taskId: string): Promise<{ task_id: string; status: UploadTaskStatus; count?: number; holdings?: unknown[]; message?: string; parser_source?: string }>;
  latestTask(): Promise<{ task_id?: string; status?: UploadTaskStatus } | null>;
  /** Convenience wrapper used by useCasUpload hook. Submits file + optional password, returns task_id. */
  upload(file: File, options?: { password?: string; portfolioId?: string }): Promise<{ task_id: string }>;
}

export const realCasUploadAdapter: CasUploadAdapter = {
  async getActivePortfolio() {
    try {
      const res = await http({ path: "/api/portfolio/me" });
      return res.data as ActivePortfolioRes;
    } catch (err) {
      if (err instanceof ApiError && (err.kind === "not_found" || err.kind === "auth")) {
        return {};
      }
      throw err;
    }
  },

  async uploadFile(file, portfolioId) {
    const id = correlationId();
    const form = new FormData();
    form.append("file", file);
    if (portfolioId) form.append("portfolio_id", portfolioId);

    const startedAt = performance.now();
    const obs = getObserver();
    obs.onRequestStart({ correlationId: id, method: "POST", url: "/api/portfolio/upload", startedAt });

    let res: Response;
    try {
      res = await fetch(new URL("/api/portfolio/upload", apiConfig.baseUrl).toString(), {
        method: "POST",
        body: form,
        credentials: "include",
        headers: { "X-Correlation-Id": id, "X-Client-Version": apiConfig.appVersion },
      });
    } catch (err) {
      obs.onRequestError({ correlationId: id, method: "POST", url: "/api/portfolio/upload", startedAt, durationMs: performance.now() - startedAt, error: err });
      throw ApiError.network(err, id);
    }
    obs.onRequestEnd({ correlationId: id, method: "POST", url: "/api/portfolio/upload", startedAt, durationMs: performance.now() - startedAt, status: res.status });

    if (!res.ok) {
      const body = await res.json().catch(() => undefined);
      throw ApiError.fromResponse(res, body, id);
    }
    const json = await res.json() as { message?: string; count?: number; holdings?: unknown[] };
    return { message: json.message ?? "", count: json.count ?? 0, holdings: json.holdings ?? [] };
  },

  async getConnectToken() {
    const res = await http({ method: "POST", path: "/api/casparser/access-token", noRetry: true });
    const obj = res.data as { access_token?: string; expires_in?: number };
    return { access_token: obj.access_token ?? "", expires_in: obj.expires_in ?? 0 };
  },

  async sdkCallback({ mode, payload, portfolio_id, idempotencyKey }) {
    const body = { mode, data: payload, ...(portfolio_id ? { portfolio_id } : {}) };
    const headers = idempotencyKey ? { "Idempotency-Key": idempotencyKey } : undefined;
    const res = await http({
      method: "POST",
      path: "/api/cas/sdk-callback",
      body,
      headers,
    });
    return res.data;
  },

  async importConnect({ data, portfolio_id, idempotencyKey }) {
    const body = portfolio_id ? { data, portfolio_id } : data;
    const headers = idempotencyKey ? { "Idempotency-Key": idempotencyKey } : undefined;
    const res = await http({
      method: "POST",
      path: "/api/portfolio/import-connect",
      body,
      headers,
    });
    return res.data;
  },

  async status(taskId) {
    const res = await http({ path: `/api/portfolio/upload-status/${encodeURIComponent(taskId)}` });
    return res.data as { task_id: string; status: UploadTaskStatus; count?: number; holdings?: unknown[]; message?: string; parser_source?: string };
  },

  async latestTask() {
    try {
      const res = await http({ path: "/api/portfolio/upload-latest-task" });
      return res.data as { task_id?: string; status?: UploadTaskStatus };
    } catch (err) {
      if (err instanceof ApiError && err.kind === "not_found") return null;
      throw err;
    }
  },

  async upload(file, options) {
    const id = correlationId();
    const form = new FormData();
    form.append("file", file);
    if (options?.portfolioId) form.append("portfolio_id", options.portfolioId);
    if (options?.password)   form.append("password",     options.password);

    const startedAt = performance.now();
    const obs = getObserver();
    obs.onRequestStart({ correlationId: id, method: "POST", url: "/api/portfolio/upload", startedAt });

    let res: Response;
    try {
      res = await fetch(new URL("/api/portfolio/upload", apiConfig.baseUrl).toString(), {
        method: "POST",
        body: form,
        credentials: "include",
        headers: { "X-Correlation-Id": id, "X-Client-Version": apiConfig.appVersion },
      });
    } catch (err) {
      obs.onRequestError({ correlationId: id, method: "POST", url: "/api/portfolio/upload", startedAt, durationMs: performance.now() - startedAt, error: err });
      throw ApiError.network(err, id);
    }
    obs.onRequestEnd({ correlationId: id, method: "POST", url: "/api/portfolio/upload", startedAt, durationMs: performance.now() - startedAt, status: res.status });

    if (!res.ok) {
      const body = await res.json().catch(() => undefined);
      throw ApiError.fromResponse(res, body, id);
    }
    const json = await res.json() as { task_id?: string };
    return { task_id: json.task_id ?? id };
  },
};
