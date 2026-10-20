/**
 * Chartink scans as opportunity sources - the hooks.
 *
 *   useChartinkSource()      GET /api/desk/chartink/source   the saved dashboard (null = not connected)
 *   useChartinkHits()        GET /api/desk/chartink/hits     stale after 5 minutes, never polled; runs only for a connected source
 *   useChartinkRefresh()     POST .../refresh                runs the enabled scans now (the route has a 10-minute cooldown)
 *   useConnectChartink()     PUT  .../source                 validates the dashboard URL (422 problems) and saves it
 *   useUpdateChartinkScan()  PATCH .../scans/{id}            enabled / direction
 *   useDisconnectChartink()  DELETE .../source
 *
 * Chartink has no official API: the backend reads the user's public dashboard and runs the scans through Chartink's
 * own page. Nothing here runs a scan or judges a hit; the hits are the route's, joined to the AI scanner by the route.
 * A missing source or a failed hits call must never break the Overview, Scanner or Ideas: callers degrade to the AI scanner.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { http } from "@/services/api/http";
import { ApiError } from "@/services/api/errors";
import {
  HitsSchema, RefreshSchema, SourceSchema,
  type ChartinkHitSymbol, type ChartinkHits, type ChartinkRefresh, type ChartinkSource, type ChartinkSourceDoc, type ScanDirection,
} from "./chartink-contract";

export const CHARTINK_SOURCE_PATH = "/api/desk/chartink/source";
export const CHARTINK_HITS_PATH = "/api/desk/chartink/hits";
export const CHARTINK_REFRESH_PATH = "/api/desk/chartink/refresh";
export const chartinkScanPath = (id: string) => `/api/desk/chartink/scans/${encodeURIComponent(id)}`;

const KEY = ["copilot", "desk", "chartink"] as const;
const drift = (what: string, cause: unknown) => new ApiError("contract_drift", `The Chartink ${what} were not in the expected form.`, { cause });

export function useChartinkSource() {
  return useQuery<ChartinkSource>({
    queryKey: [...KEY, "source"],
    staleTime: 5 * 60_000,
    retry: false,
    refetchOnWindowFocus: false,
    queryFn: async ({ signal }) => {
      const res = await http({ path: CHARTINK_SOURCE_PATH, signal, noRetry: true });
      const r = SourceSchema.safeParse(res.data);
      if (!r.success) throw drift("source", r.error);
      return r.data;
    },
  });
}

export function useChartinkHits(enabled = true) {
  const source = useChartinkSource();
  return useQuery<ChartinkHits>({
    queryKey: [...KEY, "hits"],
    // A hits call is made only once a dashboard is known to be connected: without one the route has nothing to answer.
    enabled: enabled && source.data != null,
    staleTime: 5 * 60_000,
    retry: false,
    refetchOnWindowFocus: false,
    queryFn: async ({ signal }) => {
      const res = await http({ path: CHARTINK_HITS_PATH, signal, noRetry: true });
      const r = HitsSchema.safeParse(res.data);
      if (!r.success) throw drift("hits", r.error);
      return r.data;
    },
  });
}

/** What the Overview, Scanner and Ideas know about Chartink, in one place. */
export type ChartinkState =
  | { kind: "loading" }
  | { kind: "not_connected" }
  | { kind: "source_error"; error: unknown; retry: () => void }
  | { kind: "hits_error"; error: unknown; retry: () => void; source: ChartinkSourceDoc }
  | { kind: "hits_loading"; source: ChartinkSourceDoc }
  | { kind: "ready"; source: ChartinkSourceDoc; hits: ChartinkHits };

export function useChartink(): ChartinkState {
  const src = useChartinkSource();
  const hits = useChartinkHits();
  if (src.isPending) return { kind: "loading" };
  if (src.isError) return { kind: "source_error", error: src.error, retry: () => { void src.refetch(); } };
  if (src.data == null) return { kind: "not_connected" };
  if (hits.isError) return { kind: "hits_error", error: hits.error, retry: () => { void hits.refetch(); }, source: src.data };
  if (hits.data == null) return { kind: "hits_loading", source: src.data };
  return { kind: "ready", source: src.data, hits: hits.data };
}

/** Hits by upper-cased symbol. */
export function hitsBySymbol(h: ChartinkHits | null | undefined): Map<string, ChartinkHitSymbol> {
  return new Map((h?.symbols ?? []).map((s) => [s.symbol.toUpperCase(), s]));
}

/** "Also on Chartink: Scan A (+2)" for a stock the AI scanner lists too; null when the stock is not in the hits. */
export function alsoOnChartinkText(h: ChartinkHitSymbol | null | undefined): string | null {
  if (!h || h.scans.length === 0) return null;
  const extra = h.scans.length - 1;
  return `Also on Chartink: ${h.scans[0].name}${extra > 0 ? ` (+${extra})` : ""}`;
}

export function invalidateChartink(qc: ReturnType<typeof useQueryClient>) {
  return qc.invalidateQueries({ queryKey: KEY });
}

export function useConnectChartink() {
  const qc = useQueryClient();
  return useMutation<ChartinkSourceDoc, unknown, string>({
    mutationFn: async (dashboard_url) => {
      const res = await http({ method: "PUT", path: CHARTINK_SOURCE_PATH, body: { dashboard_url }, noRetry: true });
      const r = SourceSchema.safeParse(res.data);
      if (!r.success || r.data == null) throw drift("source", r.success ? null : r.error);
      return r.data;
    },
    onSuccess: (doc) => {
      qc.setQueryData([...KEY, "source"], doc);
      qc.removeQueries({ queryKey: [...KEY, "hits"] });
      void qc.invalidateQueries({ queryKey: [...KEY, "hits"] });
    },
  });
}

export function useUpdateChartinkScan() {
  const qc = useQueryClient();
  return useMutation<unknown, unknown, { id: string; enabled?: boolean; direction?: ScanDirection }>({
    mutationFn: async ({ id, ...patch }) => (await http({ method: "PATCH", path: chartinkScanPath(id), body: patch, noRetry: true })).data,
    onSuccess: () => invalidateChartink(qc),
  });
}

export function useChartinkRefresh() {
  const qc = useQueryClient();
  return useMutation<ChartinkRefresh, unknown, void>({
    mutationFn: async () => {
      const res = await http({ method: "POST", path: CHARTINK_REFRESH_PATH, noRetry: true });
      const r = RefreshSchema.safeParse(res.data);
      if (!r.success) throw drift("refresh result", r.error);
      return r.data;
    },
    onSuccess: () => invalidateChartink(qc),
  });
}

export function useDisconnectChartink() {
  const qc = useQueryClient();
  return useMutation<unknown, unknown, void>({
    mutationFn: async () => (await http({ method: "DELETE", path: CHARTINK_SOURCE_PATH, noRetry: true })).data,
    onSuccess: () => {
      qc.setQueryData([...KEY, "source"], null);
      qc.removeQueries({ queryKey: [...KEY, "hits"] });
    },
  });
}

// ── the dashboard URL ────────────────────────────────────────────────────

/** Client-side check before the request: https, host chartink.com (or www.), path /dashboard/<digits>. The server checks again. */
export function checkDashboardUrl(raw: string): string | null {
  const t = raw.trim();
  if (!t) return "Paste the address of your Chartink dashboard.";
  let u: URL;
  try { u = new URL(t); } catch { return "That is not a web address. It looks like https://chartink.com/dashboard/123456."; }
  if (u.protocol !== "https:") return "The address must start with https://.";
  if (u.hostname !== "chartink.com" && u.hostname !== "www.chartink.com") return "The address must be on chartink.com.";
  if (!/^\/dashboard\/\d+\/?$/.test(u.pathname)) return "The path must be /dashboard/ followed by the dashboard number, for example https://chartink.com/dashboard/123456.";
  return null;
}

/** The 422's message: `{detail: {code, message}, message}`, or a `detail.problems` list, or a plain `detail` string. */
export function connectProblems(e: unknown): string[] {
  if (!(e instanceof ApiError) || e.status !== 422) return [];
  const b = e.body as { message?: unknown; detail?: unknown } | undefined;
  const d = b?.detail;
  if (typeof d === "string") return [d];
  if (d && typeof d === "object") {
    const o = d as { message?: unknown; problems?: unknown };
    if (Array.isArray(o.problems)) {
      const m = o.problems.flatMap((p) => { const x = (p as { message?: unknown })?.message; return typeof x === "string" ? [x] : []; });
      if (m.length) return m;
    }
    if (typeof o.message === "string") return [o.message];
  }
  if (typeof b?.message === "string") return [b.message];
  return e.detail ? [e.detail] : [];
}

/** Seconds left of the refresh cooldown from a 429, or null when the error is not one. */
export function cooldownSeconds(e: unknown): number | null {
  if (!(e instanceof ApiError) || e.status !== 429) return null;
  const b = e.body as { retry_after_s?: unknown; detail?: unknown } | undefined;
  const d = b?.detail && typeof b.detail === "object" ? (b.detail as { retry_after_s?: unknown }) : undefined;
  const v = typeof b?.retry_after_s === "number" ? b.retry_after_s : typeof d?.retry_after_s === "number" ? d.retry_after_s : null;
  return v != null && Number.isFinite(v) && v >= 0 ? v : 0;
}
