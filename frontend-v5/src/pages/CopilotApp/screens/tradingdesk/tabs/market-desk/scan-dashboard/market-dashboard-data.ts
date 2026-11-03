/**
 * Scan dashboard — the hook (contract: docs/scan_builder/DESIGN.md §8; backend/routes/scan_builder.py).
 *
 *   useMarketDashboard()   GET /api/scan-builder/market-dashboard   the 17 widgets of Chartink dashboard 247498 computed on our
 *                                                                   own data (definitions only; no Chartink data), each with
 *                                                                   its criteria, its table and its status; optionally
 *                                                                   `ideas` (a strategy idea per stock, from the strategy
 *                                                                   builder) and `ideas_meta`; optionally `signals` (today's
 *                                                                   early signals with their trading plans, §9) and
 *                                                                   `signals_meta`
 *
 * Real time: while the answer says the market is open it is asked again every `market.refresh_seconds` (10 s); a hidden tab
 * does not ask (React Query's refetchIntervalInBackground: false); after the close it is asked once. The previous answer stays
 * on screen while the next one loads. Typed errors ({detail: {code, message}}: 503 data_unavailable, 403 feature_disabled) are
 * read with scanProblem() from the Scan Builder's hooks.
 */
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { z } from "zod";
import { http } from "@/services/api/http";
import { ApiError } from "@/services/api/errors";

export const MD_PATH = "/api/scan-builder/market-dashboard";

const KEY = ["copilot", "desk", "scan-dashboard"] as const;
const drift = (cause: unknown) => new ApiError("contract_drift", "The scan dashboard's answer was not in the expected form.", { cause });

// ── schema (lenient: unknown fields pass, missing optional fields get defaults) ───────────────────────────────────────

const Str = z.string().nullable().optional();
const CellC = z.union([z.number(), z.string(), z.null()]);

const CriterionC = z.object({
  text: z.string(),
  level: z.number().int().min(0).catch(0).default(0),
  applied: z.boolean().default(true),
  note: Str,
}).passthrough();

const ColumnC = z.object({
  key: z.string(),
  label: z.string(),
  format: z.string().default("text"),
}).passthrough();

const WidgetC = z.object({
  id: z.string(),
  chartink_id: z.union([z.string(), z.number()]).nullable().optional(),
  title: z.string(),
  universe: Str,
  status: z.string().default("ok"),
  note: Str,
  criteria: z.array(CriterionC).default([]),
  columns: z.array(ColumnC).default([]),
  rows: z.array(z.array(CellC)).default([]),
  row_kind: z.string().default("symbol"),
  count: z.number().nullable().optional(),
  as_of: Str,
}).passthrough();

// Strategy ideas (owner 3 Nov: "the best strategies for each of the stocks wherever the risk reward are favorable"): one per
// symbol from the strategy builder, attached by the route. In `ideas`, a key that is absent means the idea is still being
// built; null means no structure with a favorable reward : risk. Both fields are optional: an older backend has neither, and a
// malformed entry is read as null rather than failing the whole dashboard.
const NumN = z.number().nullable().optional().catch(null);

const IdeaC = z.object({
  structure: z.string().catch("Strategy idea"),
  family: Str.catch(null),
  horizon: Str.catch(null),
  reward_risk: NumN,
  max_loss_inr: NumN,
  capital_at_risk_inr: NumN,
  legs_text: Str.catch(null),
  data_as_of: Str.catch(null),
}).passthrough();

const IdeasMetaC = z.object({
  built: z.number().catch(0).default(0),
  pending: z.number().catch(0).default(0),
  note: z.string().catch("").default(""),
  source: z.string().catch("").default(""),
  as_of: Str.catch(null),
}).passthrough();

// Early signals (DESIGN.md §9, owner 3 Nov ~17:15 IST): a stock entering a widget's list during the session, with the
// trading plan frozen at that moment (Entry · Stop loss · Target 1 · Target 2 — the owner's chosen words for this screen).
// Today's, newest first. Both fields are optional (an older backend has neither); a malformed signal is dropped, never
// allowed to fail the whole dashboard.
export const SignalC = z.object({
  id: z.string(),
  widget_id: z.string(),
  widget_title: z.string().catch("").default(""),
  symbol: z.string(),
  first_seen: z.string(),
  at_open: z.boolean().catch(false).default(false),
  direction: z.enum(["long", "short"]).catch("long").default("long"),
  entry: NumN,
  stop_loss: NumN,
  target_1: NumN,
  target_2: NumN,
  risk_per_share: NumN,
  rr_1: NumN,
  rr_2: NumN,
  stop_basis: Str.catch(null),
  target_1_basis: Str.catch(null),
  plan_ok: z.boolean().catch(false).default(false),
  plan_note: Str.catch(null),
  price_now: NumN,
  move_since_pct: NumN,
}).passthrough();

const SignalsC = z.array(z.unknown()).transform((items) => {
  const out: z.infer<typeof SignalC>[] = [];
  for (const it of items) {
    const r = SignalC.safeParse(it);
    if (r.success) out.push(r.data);
  }
  return out;
});

const SignalsMetaC = z.object({
  day: z.string().catch("").default(""),
  count: z.number().catch(0).default(0),
  recording: z.boolean().catch(false).default(false),
  rules: z.string().catch("").default(""),
  caveat: z.string().catch("").default(""),
}).passthrough();

export const MarketDashboardC = z.object({
  ok: z.boolean().default(true),
  run_at: Str,
  elapsed_ms: z.number().nullable().optional(),
  cached: z.boolean().nullable().optional(),
  basis: z.object({
    mode: z.string().default("eod"),
    day: Str,
    eod_date: Str,
    quote_as_of: Str,
    text: z.string().default(""),
  }).passthrough(),
  market: z.object({
    open: z.boolean().default(false),
    refresh_seconds: z.number().positive().catch(10).default(10),
  }).passthrough(),
  counts: z.record(z.unknown()).default({}),
  sources: z.record(z.unknown()).default({}),
  warnings: z.array(z.string()).default([]),
  widgets: z.array(WidgetC).default([]),
  ideas: z.record(z.union([IdeaC, z.null()]).catch(null)).nullable().optional().catch(null),
  ideas_meta: IdeasMetaC.nullable().optional().catch(null),
  signals: SignalsC.nullable().optional().catch(null),
  signals_meta: SignalsMetaC.nullable().optional().catch(null),
}).passthrough();

export type MarketDashboard = z.infer<typeof MarketDashboardC>;
export type DashboardSignal = z.infer<typeof SignalC>;
export type SignalsMeta = z.infer<typeof SignalsMetaC>;
export type DashboardIdea = z.infer<typeof IdeaC>;
export type DashboardIdeas = Record<string, DashboardIdea | null>;
export type IdeasMeta = z.infer<typeof IdeasMetaC>;
export type DashboardWidget = z.infer<typeof WidgetC>;
export type DashboardCriterion = z.infer<typeof CriterionC>;
export type DashboardColumn = z.infer<typeof ColumnC>;
export type DashboardCell = z.infer<typeof CellC>;

/** The refresh period while the market is open, never under 5 s whatever the server says. */
export const refreshMs = (d: MarketDashboard | undefined): number | false =>
  d?.market.open ? Math.max(5, d.market.refresh_seconds) * 1000 : false;

// ── hook ─────────────────────────────────────────────────────────────────────────────────────────────────────────────

export function useMarketDashboard(enabled = true) {
  return useQuery<MarketDashboard>({
    queryKey: [...KEY],
    enabled,
    queryFn: async ({ signal }) => {
      // The first answer of the day loads the market's history on the server (up to a minute).
      const res = await http({ path: MD_PATH, signal, timeoutMs: 90_000, noRetry: true });
      const r = MarketDashboardC.safeParse(res.data);
      if (!r.success) throw drift(r.error);
      return r.data;
    },
    refetchInterval: (query) => refreshMs(query.state.data),
    refetchIntervalInBackground: false,
    placeholderData: keepPreviousData,
    retry: false,
    staleTime: 5_000,
    refetchOnWindowFocus: false,
  });
}
