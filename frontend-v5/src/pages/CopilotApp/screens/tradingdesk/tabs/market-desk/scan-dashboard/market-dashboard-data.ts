/**
 * Scan dashboard — the hook (contract: docs/scan_builder/DESIGN.md §8; backend/routes/scan_builder.py).
 *
 *   useMarketDashboard(key)   GET /api/scan-builder/market-dashboard?dashboard=<key>   one Chartink dashboard computed on our
 *                                own data (definitions only; no Chartink data): `atlas` = 247498 "Atlas fresh" (17 widgets,
 *                                the server's default), `daytrade` = 503347 "Day trade" (20 widgets). Each widget with its
 *                                criteria, its table and its status; optionally `ideas` (a strategy idea per stock, from the
 *                                strategy builder) and `ideas_meta`; `dashboard` (the one served) and `dashboards` (the tabs); optionally `signals` (today's early signals with their trading plans, §10) and
 *                                `signals_meta`; optionally (§11, 4 Nov) `scores` (each signalled stock's strength 0–100 with its parts,
 *                                reasons and penalties), `strong` (the stocks whose score reached 70 today, each with its positional plan)
 *                                and `scores_meta`
 *
 * Real time: while the answer says the market is open it is asked again every `market.refresh_seconds` (10 s); a hidden tab
 * does not ask (React Query's refetchIntervalInBackground: false); after the close it is asked once. One query per dashboard,
 * so only the dashboard on screen is asked again, and a dashboard's previous answer stays on screen while its next one loads
 * (never another dashboard's). Typed errors ({detail: {code, message}}: 503 data_unavailable, 403 feature_disabled, 422
 * unknown_dashboard) are read with scanProblem() from the Scan Builder's hooks.
 *
 * Deploy-order trap: a backend from before the second dashboard ignores `?dashboard=` and answers 247498 without `dashboard`.
 * servedKey() reads such an answer as atlas, and the screen shows no widgets under a tab whose key the answer does not carry.
 */
import { useQuery } from "@tanstack/react-query";
import { z } from "zod";
import { http } from "@/services/api/http";
import { ApiError } from "@/services/api/errors";

export const MD_PATH = "/api/scan-builder/market-dashboard";

const KEY = ["copilot", "desk", "scan-dashboard"] as const;

/** The dashboard asked for when the URL names none (and the one an older backend always answers). */
export const DEFAULT_DASHBOARD = "atlas";

export interface DashboardRef { key: string; title: string; chartink_id?: string | null }

/** The tabs before the first answer (and when an older answer carries no `dashboards`). */
export const STATIC_DASHBOARDS: readonly DashboardRef[] = [
  { key: "atlas", title: "Atlas fresh", chartink_id: "247498" },
  { key: "daytrade", title: "Day trade", chartink_id: "503347" },
];
const drift = (cause: unknown) => new ApiError("contract_drift", "The scan dashboard's answer was not in the expected form.", { cause });

// ── schema (lenient: unknown fields pass, missing optional fields get defaults) ───────────────────────────────────────

export const Str = z.string().nullable().optional();
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
export const NumN = z.number().nullable().optional().catch(null);

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

// Early signals (DESIGN.md §10, owner 3 Nov evening): a stock entering a widget's list during the session, with the
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
  score: NumN,                                   // §11: the stock's strength now (null = not scored); absent from an older backend
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

// Signal strength (DESIGN.md §11, owner 4 Nov: "process only those signals where signal strength is above 70%"). Every
// signalled stock's score 0–100 = quality (30) + trend (25) + reason (20) + size (15) + participation (10) − penalties; the
// stocks that reached 70 are the STRONG signals, each with the positional plan frozen when it got there. All three fields are
// optional (an older backend has none); a malformed entry is dropped rather than failing the whole dashboard.
const PartN = z.number().catch(0).default(0);
export const PartsC = z.object({
  quality: PartN, trend: PartN, reason: PartN, size: PartN, participation: PartN, penalty: PartN,
}).passthrough();

export const PenaltyC = z.object({ text: z.string(), points: z.number().catch(0).default(0) }).passthrough();

/** A list a stock is in today: {id, title}, or a bare id from a terser answer. */
const ListRefC = z.union([
  z.object({ id: z.string(), title: z.string().catch("").default("") }).passthrough(),
  z.string().transform((id) => ({ id, title: "" })),
]);

export const keepGood = <T extends z.ZodTypeAny>(c: T) => z.array(z.unknown()).catch([]).default([]).transform((items) => {
  const out: z.infer<T>[] = [];
  for (const it of items) {
    const r = c.safeParse(it);
    if (r.success) out.push(r.data);
  }
  return out;
});

export const ScoreC = z.object({
  score: z.number().nullable().catch(null).default(null),
  parts: PartsC.nullable().optional().catch(null),
  reasons: z.array(z.string()).catch([]).default([]),
  penalties: keepGood(PenaltyC),
  lists: keepGood(ListRefC),
  note: Str.catch(null),
}).passthrough();

const ScoresC = z.record(z.unknown()).transform((m) => {
  const out: Record<string, z.infer<typeof ScoreC>> = {};
  for (const [sym, v] of Object.entries(m)) {
    const r = ScoreC.safeParse(v);
    if (r.success) out[sym] = r.data;
  }
  return out;
});

export const StrongC = z.object({
  symbol: z.string(),
  name: Str.catch(null),
  first_strong: z.string(),
  score_at: z.number().nullable().catch(null).default(null),
  parts_at: PartsC.nullable().optional().catch(null),
  reasons_at: z.array(z.string()).catch([]).default([]),
  score_now: NumN,
  rules: Str.catch(null),
  entry: NumN,
  stop_loss: NumN,
  target_1: NumN,
  target_2: NumN,
  risk_per_share: NumN,
  rr_1: NumN,
  rr_2: NumN,
  atr: NumN,
  sma20: NumN,
  trend_exit: Str.catch(null),
  plan_ok: z.boolean().catch(false).default(false),
  plan_note: Str.catch(null),
  lists_at: keepGood(ListRefC),
  price_now: NumN,
  move_since_pct: NumN,
}).passthrough();

const StrongsC = keepGood(StrongC);

const ScoresMetaC = z.object({
  threshold: z.number().catch(70).default(70),
  weights: z.record(z.number()).catch({}).default({}),
  as_of: z.record(z.union([z.string(), z.null()])).catch({}).default({}),
  rules: z.string().catch("").default(""),
  plan_rules: z.string().catch("").default(""),
  caveat: z.string().catch("").default(""),
  counts: z.record(z.number()).catch({}).default({}),
  warnings: z.array(z.string()).catch([]).default([]),
}).passthrough();

const DashboardRefC = z.object({
  key: z.string().min(1),
  title: z.string().catch(""),
  chartink_id: z.union([z.string(), z.number()]).nullable().optional().catch(null).transform((v) => (v == null ? null : String(v))),
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
  scores: ScoresC.nullable().optional().catch(null),
  strong: StrongsC.nullable().optional().catch(null),
  scores_meta: ScoresMetaC.nullable().optional().catch(null),
  // The second dashboard (3 Nov): the one served and the list for the tabs. Both absent from an older backend; a malformed
  // value is read as absent rather than failing the whole dashboard.
  dashboard: DashboardRefC.nullable().optional().catch(null),
  dashboards: z.array(DashboardRefC).nullable().optional().catch(null),
}).passthrough();

export type MarketDashboard = z.infer<typeof MarketDashboardC>;
export type DashboardSignal = z.infer<typeof SignalC>;
export type SignalsMeta = z.infer<typeof SignalsMetaC>;
export type StockScore = z.infer<typeof ScoreC>;
export type StockScores = Record<string, StockScore>;
export type StrongSignal = z.infer<typeof StrongC>;
export type ScoresMeta = z.infer<typeof ScoresMetaC>;
export type ScoreParts = z.infer<typeof PartsC>;
export type ListRef = { id: string; title: string };
export type DashboardIdea = z.infer<typeof IdeaC>;
export type DashboardIdeas = Record<string, DashboardIdea | null>;
export type IdeasMeta = z.infer<typeof IdeasMetaC>;
export type DashboardWidget = z.infer<typeof WidgetC>;
export type DashboardCriterion = z.infer<typeof CriterionC>;
export type DashboardColumn = z.infer<typeof ColumnC>;
export type DashboardCell = z.infer<typeof CellC>;

/** The dashboard an answer is for: its `dashboard.key`, or atlas for an older backend's answer, which carries none. */
export const servedKey = (d: MarketDashboard): string => d.dashboard?.key ?? DEFAULT_DASHBOARD;

/** The tabs: the answer's `dashboards` when it carries any (blank titles named by their key), else the static pair. */
export function dashboardTabs(d: MarketDashboard | undefined): readonly DashboardRef[] {
  const list = d?.dashboards ?? [];
  return list.length ? list.map((x) => ({ key: x.key, title: x.title.trim() || x.key, chartink_id: x.chartink_id ?? null })) : STATIC_DASHBOARDS;
}

/** The refresh period while the market is open, never under 5 s whatever the server says. */
export const refreshMs = (d: MarketDashboard | undefined): number | false =>
  d?.market.open ? Math.max(5, d.market.refresh_seconds) * 1000 : false;

// ── hook ─────────────────────────────────────────────────────────────────────────────────────────────────────────────

export function useMarketDashboard(dashboard: string = DEFAULT_DASHBOARD, enabled = true) {
  return useQuery<MarketDashboard>({
    // One cache entry per dashboard: a tab never shows another dashboard's answer while its own loads (no placeholder data).
    queryKey: [...KEY, dashboard],
    enabled,
    queryFn: async ({ signal }) => {
      // The first answer of the day loads the market's history on the server (up to a minute).
      const res = await http({ path: MD_PATH, query: { dashboard }, signal, timeoutMs: 90_000, noRetry: true });
      const r = MarketDashboardC.safeParse(res.data);
      if (!r.success) throw drift(r.error);
      return r.data;
    },
    refetchInterval: (query) => refreshMs(query.state.data),
    refetchIntervalInBackground: false,
    retry: false,
    staleTime: 5_000,
    refetchOnWindowFocus: false,
  });
}
