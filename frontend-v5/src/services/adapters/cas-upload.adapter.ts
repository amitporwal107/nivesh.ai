/**
 * CAS Connect adapter — matches the V4 frontend pattern in
 * `frontend/src/v4/api/portfolioIngestion.js`.
 *
 * Real endpoints:
 *   POST /api/onboarding/upload-cas    → CAS *PDF* import. In-house server-side
 *                                         parser (our own wrapper over the
 *                                         open-source `casparser` lib +
 *                                         reconciling NSDL/CDSL/CAMS-KFin
 *                                         extractors). Synchronous — returns the
 *                                         imported-holdings summary directly.
 *   POST /api/portfolio/upload         → CSV/Excel synchronous import only
 *   GET  /api/portfolio/me             → active portfolio + snapshot
 *
 * Note: this app does NOT use the hosted `@cas-parser/connect` SDK/widget.
 * CAS PDFs are parsed entirely server-side; there is no browser widget, no
 * minted access token, and no `/api/cas/sdk-callback` round-trip. The
 * getConnectToken/sdkCallback/importConnect methods below are legacy stubs
 * kept only for interface compatibility and are not used by the live app.
 */
import { apiConfig } from "@/services/api/config";
import { http } from "@/services/api/http";
import { apiFetch } from "@/services/api/authed-fetch";
import { ApiError } from "@/services/api/errors";
import { correlationId, getObserver } from "@/lib/observability";

export type CasMode = "cas" | "gmail" | "cdsl";

export type UploadTaskStatus = "processing" | "completed" | "failed" | string;

/** Synchronous result of the in-house CAS PDF import (/api/onboarding/upload-cas). */
export interface CasUploadResult {
  ok: boolean;
  imported_holdings: number;
  statement_period?: string | null;
  filename?: string;
}

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
  /** CAS PDF import used by the useCasUpload hook. Submits the PDF + optional
   *  unlock secret (PAN or statement password) to the in-house server-side
   *  parser and returns the imported-holdings summary synchronously. */
  upload(file: File, options?: { password?: string; portfolioId?: string }): Promise<CasUploadResult>;
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
      res = await apiFetch("/api/portfolio/upload", {
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
    // CAS PDF import via the in-house server-side parser. Synchronous: the
    // endpoint parses (reconciling NSDL/CDSL/CAMS-KFin extractors → offline
    // casparser) and returns the imported-holdings summary in the response.
    const path = "/api/onboarding/upload-cas";
    const id = correlationId();
    const form = new FormData();
    form.append("file", file);
    if (options?.password) form.append("password", options.password);

    const startedAt = performance.now();
    const obs = getObserver();
    obs.onRequestStart({ correlationId: id, method: "POST", url: path, startedAt });

    let res: Response;
    try {
      res = await apiFetch(path, {
        method: "POST",
        body: form,
        credentials: "include",
        headers: { "X-Correlation-Id": id, "X-Client-Version": apiConfig.appVersion },
      });
    } catch (err) {
      obs.onRequestError({ correlationId: id, method: "POST", url: path, startedAt, durationMs: performance.now() - startedAt, error: err });
      throw ApiError.network(err, id);
    }
    obs.onRequestEnd({ correlationId: id, method: "POST", url: path, startedAt, durationMs: performance.now() - startedAt, status: res.status });

    if (!res.ok) {
      const body = await res.json().catch(() => undefined);
      throw ApiError.fromResponse(res, body, id);
    }
    const json = await res.json() as Partial<CasUploadResult>;
    return {
      ok: json.ok ?? true,
      imported_holdings: json.imported_holdings ?? 0,
      statement_period: json.statement_period ?? null,
      filename: json.filename,
    };
  },
};
