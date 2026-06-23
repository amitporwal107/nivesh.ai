/**
 * ApiError taxonomy.
 *
 * Backend (FastAPI) returns `{ detail: string | object }` on 4xx/5xx.
 * We normalise that — plus network failures, timeouts, validation drift —
 * into a single hierarchy the rest of the app can `instanceof` against.
 */
export type ApiErrorKind =
  | "network"          // fetch threw / no response
  | "timeout"          // aborted via AbortController
  | "auth"             // 401
  | "forbidden"        // 403
  | "not_found"        // 404
  | "validation"       // 422 / 400 with field-level detail
  | "conflict"         // 409 — duplicate / identity already exists
  | "rate_limit"       // 429
  | "server"           // 5xx
  | "contract_drift"   // Zod schema mismatch
  | "unknown";

export interface ApiErrorOptions {
  status?: number;
  detail?: string;
  fields?: Record<string, string>;
  correlationId?: string;
  cause?: unknown;
}

export class ApiError extends Error {
  readonly kind: ApiErrorKind;
  readonly status?: number;
  readonly detail?: string;
  readonly fields?: Record<string, string>;
  readonly correlationId?: string;

  constructor(kind: ApiErrorKind, message: string, opts: ApiErrorOptions = {}) {
    super(message);
    this.name = "ApiError";
    this.kind = kind;
    this.status = opts.status;
    this.detail = opts.detail;
    this.fields = opts.fields;
    this.correlationId = opts.correlationId;
    if (opts.cause) (this as { cause?: unknown }).cause = opts.cause;
  }

  static fromResponse(response: Response, body: unknown, correlationId?: string): ApiError {
    const { status } = response;
    // FastAPI envelope: { detail: string | Array<...> }
    const detail = extractDetail(body);
    const kind: ApiErrorKind =
      status === 401 ? "auth" :
      status === 403 ? "forbidden" :
      status === 404 ? "not_found" :
      status === 422 || status === 400 ? "validation" :
      status === 409 ? "conflict" :
      status === 429 ? "rate_limit" :
      status >= 500 ? "server" :
      "unknown";

    return new ApiError(kind, detail ?? `HTTP ${status}`, {
      status,
      detail,
      correlationId,
      fields: extractFields(body),
    });
  }

  static network(cause: unknown, correlationId?: string): ApiError {
    return new ApiError("network", "Network error", { cause, correlationId });
  }

  static timeout(correlationId?: string): ApiError {
    return new ApiError("timeout", "Request timed out", { correlationId });
  }

  static contractDrift(message: string, cause?: unknown): ApiError {
    return new ApiError("contract_drift", `Response did not match contract: ${message}`, { cause });
  }
}

function extractDetail(body: unknown): string | undefined {
  if (!body || typeof body !== "object") return undefined;
  const obj = body as Record<string, unknown>;
  if (typeof obj.detail === "string") return obj.detail;
  if (Array.isArray(obj.detail)) {
    // FastAPI validation errors are arrays of { msg, loc, type }
    const first = obj.detail[0] as { msg?: string } | undefined;
    return first?.msg;
  }
  // Structured detail object — e.g. the 409 identity-conflict envelope
  // { error, message, conflicts }. Surface its human-readable message.
  if (obj.detail && typeof obj.detail === "object") {
    const d = obj.detail as Record<string, unknown>;
    if (typeof d.message === "string") return d.message;
    if (typeof d.error === "string") return d.error;
  }
  if (typeof obj.message === "string") return obj.message;
  return undefined;
}

function extractFields(body: unknown): Record<string, string> | undefined {
  if (!body || typeof body !== "object") return undefined;
  const obj = body as Record<string, unknown>;
  if (!Array.isArray(obj.detail)) return undefined;
  const out: Record<string, string> = {};
  for (const item of obj.detail) {
    const e = item as { loc?: unknown[]; msg?: string };
    if (e?.loc && e.msg) {
      const key = e.loc.filter((x) => x !== "body").join(".");
      out[key] = e.msg;
    }
  }
  return Object.keys(out).length ? out : undefined;
}
