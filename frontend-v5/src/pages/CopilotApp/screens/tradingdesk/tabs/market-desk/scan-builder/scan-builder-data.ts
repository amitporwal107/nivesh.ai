/**
 * Scan Builder — the hooks (contract: docs/scan_builder/DESIGN.md §4; backend/routes/scan_builder.py).
 *
 *   useScanCatalog()       GET    /api/scan-builder/catalog          measures, fundamentals, operators, universes, timeframes, templates
 *   useSavedScans()        GET    /api/scan-builder/scans            the user's scans, newest first
 *   useSavedScan(id)       GET    /api/scan-builder/scans/{id}
 *   useSaveScan()          POST   /api/scan-builder/scans  |  PUT /api/scan-builder/scans/{id}
 *   useCopyScan()          POST   /api/scan-builder/scans/{id}/copy
 *   useDeleteScan()        DELETE /api/scan-builder/scans/{id}
 *   useScanRun(spec, n)    POST   /api/scan-builder/run              a read (POST only because the scan travels in the body), so a
 *                                                                    query keyed by the run number: each Run press / refresh asks again
 *
 * Every figure a run returns is the server's, computed on our own data (NSE end-of-day bars + Kite quotes + NIDP fundamentals).
 * Typed errors: 422 invalid_spec {code, message, path}, 429 run_too_soon {retry_after_s}, 503 data_unavailable,
 * 403 feature_disabled — read with scanProblem().
 */
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { z } from "zod";
import { http } from "@/services/api/http";
import { ApiError } from "@/services/api/errors";
import type { Catalog, ScanSpec } from "./scan-model";

export const SB_BASE = "/api/scan-builder";
export const SB_CATALOG = `${SB_BASE}/catalog`;
export const SB_RUN = `${SB_BASE}/run`;
export const SB_SCANS = `${SB_BASE}/scans`;
export const sbScanPath = (id: string) => `${SB_SCANS}/${encodeURIComponent(id)}`;

const KEY = ["copilot", "desk", "scan-builder"] as const;
const drift = (what: string, cause: unknown) => new ApiError("contract_drift", `The scan builder's ${what} was not in the expected form.`, { cause });

// ── schemas ──────────────────────────────────────────────────────────────────────────────────────────────────────────

const ParamValueC = z.union([z.number(), z.string()]);
const OperandC = z.discriminatedUnion("kind", [
  z.object({ kind: z.literal("number"), value: z.number() }),
  z.object({ kind: z.literal("measure"), tf: z.string(), offset: z.number().int(), measure: z.string(), params: z.record(ParamValueC).default({}) }),
  z.object({ kind: z.literal("fundamental"), field: z.string() }),
]);
const ExprC = z.object({ terms: z.array(z.object({ op: z.enum(["+", "-", "*", "/"]).nullable(), operand: OperandC })).min(1) });
const FilterC = z.object({
  id: z.string(), kind: z.literal("filter"), left: ExprC, op: z.string(), right: ExprC, enabled: z.boolean().default(true), comment: z.string().default(""),
});
type GroupIn = { id: string; kind: "group"; join: "all" | "any"; universe: string | null; enabled: boolean; comment: string; children: Array<GroupIn | z.infer<typeof FilterC>> };
const GroupC: z.ZodType<GroupIn, z.ZodTypeDef, unknown> = z.lazy(() => z.object({
  id: z.string(), kind: z.literal("group"), join: z.enum(["all", "any"]), universe: z.string().nullable().default(null),
  enabled: z.boolean().default(true), comment: z.string().default(""), children: z.array(z.union([GroupC, FilterC])),
})) as z.ZodType<GroupIn, z.ZodTypeDef, unknown>;
export const SpecC = z.object({
  version: z.literal(1).default(1),
  name: z.string(),
  description: z.string().default(""),
  filters: GroupC,
  columns: z.array(z.object({ id: z.string(), alias: z.string(), expr: ExprC, enabled: z.boolean().default(true), format: z.enum(["number", "pct", "price", "volume"]).default("number") })),
  sort: z.object({ column: z.string(), dir: z.enum(["asc", "desc"]) }),
  limit: z.number().int(),
}).passthrough();

const CatalogC = z.object({
  measures: z.array(z.object({
    key: z.string(), label: z.string(), group: z.string().nullish(),
    params: z.array(z.object({
      name: z.string(), label: z.string().nullish(), type: z.string().nullish(), default: ParamValueC.nullish(), min: z.number().nullish(), max: z.number().nullish(),
    }).passthrough()).nullish(),
  }).passthrough()),
  fundamentals: z.array(z.object({ key: z.string(), label: z.string(), unit: z.string().nullish() }).passthrough()).default([]),
  operators: z.array(z.object({ key: z.string(), label: z.string() }).passthrough()).default([]),
  universes: z.array(z.object({ key: z.string(), label: z.string(), size: z.number().nullish() }).passthrough()),
  timeframes: z.array(z.object({ key: z.string(), label: z.string(), available: z.boolean(), reason: z.string().nullish() }).passthrough()),
  templates: z.array(z.object({ key: z.string(), name: z.string(), description: z.string().nullish(), spec: SpecC }).passthrough()).default([]),
  refresh_seconds: z.number().positive().default(10),
  default_spec: SpecC.nullish(),
}).passthrough();

const SavedMetaC = z.object({ id: z.string(), name: z.string(), description: z.string().nullish(), created_at: z.string().nullish(), updated_at: z.string().nullish() }).passthrough();
const ScansC = z.object({ scans: z.array(SavedMetaC) });
const SavedScanC = z.object({ scan: z.object({ id: z.string(), spec: SpecC, created_at: z.string().nullish(), updated_at: z.string().nullish() }).passthrough() });
export type SavedScanMeta = z.infer<typeof SavedMetaC>;
export interface SavedScan { id: string; spec: ScanSpec; created_at?: string | null; updated_at?: string | null }

const NumOrNull = z.number().nullable();
export const RunResultC = z.object({
  ok: z.boolean(),
  run_at: z.string(),
  elapsed_ms: z.number().nullish(),
  basis: z.object({ mode: z.string(), day: z.string().nullish(), eod_date: z.string().nullish(), quote_as_of: z.string().nullish(), text: z.string() }).passthrough(),
  sources: z.object({ prices: z.string().nullish(), today: z.string().nullish(), fundamentals: z.string().nullish() }).passthrough().nullish(),
  market: z.object({ open: z.boolean(), refresh_seconds: z.number().positive().default(10) }).passthrough(),
  universe: z.object({ key: z.string(), label: z.string(), size: z.number().nullish() }).passthrough(),
  counts: z.object({
    universe: z.number(), evaluated: z.number(), matched: z.number(), shown: z.number(),
    no_today_bar: z.number().default(0), no_history: z.number().default(0),
  }).passthrough(),
  columns: z.array(z.object({ id: z.string(), alias: z.string(), format: z.string().default("number") }).passthrough()),
  rows: z.array(z.object({ symbol: z.string(), name: z.string().nullish(), values: z.array(NumOrNull), today: z.string().nullish() }).passthrough()),
  nodes: z.record(z.object({ passed: z.number(), unknown: z.number().default(0) }).passthrough()).default({}),
  warnings: z.array(z.string()).default([]),
}).passthrough().refine((r) => r.rows.every((row) => row.values.length === r.columns.length), { path: ["rows"], message: "a row's values do not match the columns" });
export type RunResult = z.infer<typeof RunResultC>;

// ── typed problems ───────────────────────────────────────────────────────────────────────────────────────────────────

export interface ScanProblem {
  code: string;
  message: string;
  /** JSON path of the first problem in the scan (422 invalid_spec). */
  path?: string | null;
  /** Seconds to wait before running again (429 run_too_soon). */
  retryAfter?: number | null;
  kind: ApiError["kind"] | "unknown";
}

/** The route's typed error ({detail: {code, message, path?, retry_after_s?}} or the same at the top level), as one object. */
export function scanProblem(error: unknown): ScanProblem | null {
  if (!error) return null;
  if (!(error instanceof ApiError)) return { code: "unexpected", message: error instanceof Error ? error.message : String(error), kind: "unknown" };
  const body = (error.body ?? {}) as Record<string, unknown>;
  const d = (body.detail && typeof body.detail === "object" ? body.detail : body) as Record<string, unknown>;
  const code = typeof d.code === "string" ? d.code
    : error.kind === "rate_limit" ? "run_too_soon" : error.kind === "forbidden" ? "feature_disabled" : error.kind === "contract_drift" ? "contract_drift" : error.kind;
  const message = typeof d.message === "string" ? d.message : error.detail || error.message;
  const retry = typeof d.retry_after_s === "number" ? d.retry_after_s : typeof body.retry_after_s === "number" ? (body.retry_after_s as number) : null;
  return { code, message, path: typeof d.path === "string" ? d.path : null, retryAfter: retry, kind: error.kind };
}

// ── hooks ────────────────────────────────────────────────────────────────────────────────────────────────────────────

export function useScanCatalog(enabled = true) {
  return useQuery<Catalog>({
    queryKey: [...KEY, "catalog"],
    enabled,
    staleTime: 10 * 60_000,
    retry: false,
    refetchOnWindowFocus: false,
    queryFn: async ({ signal }) => {
      const res = await http({ path: SB_CATALOG, signal, noRetry: true });
      const r = CatalogC.safeParse(res.data);
      if (!r.success) throw drift("catalog", r.error);
      return r.data as unknown as Catalog;
    },
  });
}

export function useSavedScans(enabled = true) {
  return useQuery<SavedScanMeta[]>({
    queryKey: [...KEY, "scans"],
    enabled,
    staleTime: 60_000,
    retry: false,
    refetchOnWindowFocus: false,
    queryFn: async ({ signal }) => {
      const res = await http({ path: SB_SCANS, signal, noRetry: true });
      const r = ScansC.safeParse(res.data);
      if (!r.success) throw drift("saved scans list", r.error);
      return r.data.scans;
    },
  });
}

function parseScan(data: unknown, what: string): SavedScan {
  const r = SavedScanC.safeParse(data);
  if (!r.success) throw drift(what, r.error);
  return r.data.scan as unknown as SavedScan;
}

export function useSavedScan(id: string | null, enabled = true) {
  return useQuery<SavedScan>({
    queryKey: [...KEY, "scan", id],
    enabled: enabled && !!id,
    staleTime: 60_000,
    retry: false,
    refetchOnWindowFocus: false,
    queryFn: async ({ signal }) => parseScan((await http({ path: sbScanPath(id as string), signal, noRetry: true })).data, "saved scan"),
  });
}

export function useSaveScan() {
  const qc = useQueryClient();
  return useMutation<SavedScan, unknown, { id: string | null; spec: ScanSpec }>({
    mutationFn: async ({ id, spec }) => {
      const res = await http({ method: id ? "PUT" : "POST", path: id ? sbScanPath(id) : SB_SCANS, body: { spec }, noRetry: true });
      return parseScan(res.data, "saved scan");
    },
    onSuccess: (scan) => {
      qc.setQueryData([...KEY, "scan", scan.id], scan);
      void qc.invalidateQueries({ queryKey: [...KEY, "scans"] });
    },
  });
}

export function useCopyScan() {
  const qc = useQueryClient();
  return useMutation<SavedScan, unknown, string>({
    mutationFn: async (id) => parseScan((await http({ method: "POST", path: `${sbScanPath(id)}/copy`, noRetry: true })).data, "copied scan"),
    onSuccess: (scan) => {
      qc.setQueryData([...KEY, "scan", scan.id], scan);
      void qc.invalidateQueries({ queryKey: [...KEY, "scans"] });
    },
  });
}

export function useDeleteScan() {
  const qc = useQueryClient();
  return useMutation<unknown, unknown, string>({
    mutationFn: async (id) => (await http({ method: "DELETE", path: sbScanPath(id), noRetry: true })).data,
    onSuccess: (_d, id) => {
      qc.removeQueries({ queryKey: [...KEY, "scan", id] });
      void qc.invalidateQueries({ queryKey: [...KEY, "scans"] });
    },
  });
}

/**
 * One run of a scan. `runNo` changes on every Run press and every 10-second refresh, so each asks again; nothing is asked while
 * `spec` is null. The previous answer stays on screen while the next one loads (no flicker on refresh).
 */
export function useScanRun(spec: ScanSpec | null, runNo: number) {
  return useQuery<RunResult>({
    queryKey: [...KEY, "run", runNo],
    enabled: spec !== null && runNo > 0,
    // The first run of the day loads the market's history on the server (up to a minute).
    queryFn: async ({ signal }) => {
      const res = await http({ method: "POST", path: SB_RUN, body: { spec }, timeoutMs: 90_000, noRetry: true, signal });
      const r = RunResultC.safeParse(res.data);
      if (!r.success) throw drift("run result", r.error);
      return r.data;
    },
    placeholderData: keepPreviousData,
    retry: false,
    staleTime: Infinity,
    gcTime: 60_000,
    refetchOnWindowFocus: false,
  });
}
