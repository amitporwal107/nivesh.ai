/**
 * Move odds adapter — the Research page's Ten-Percent Days screen (backend/routes/move_odds.py → DaaS).
 *
 *   GET /api/move-odds/latest?head=…     → published estimates for the session they apply to
 *   GET /api/move-odds/stocks/{symbol}   → one stock: four estimates, inputs on record, events on record
 *   GET /api/move-odds/diagnostics       → backtest results of the rejected entry setups (research, never signals)
 *   GET /api/move-odds/history           → past sessions: what was estimated and how it turned out
 *
 * Every state is explicit so the screen can never show numbers it should not:
 *   final         → rows (sorted by estimate, no rank)
 *   not_published → no rows; the session they will be for
 *   withheld      → no rows; the run was refused on incomplete data
 *   no_access     → 403: the account is not on the move_odds allowlist
 *   error         → anything else (retry offered; no cached numbers)
 */
import { http } from "@/services/api/http";
import { ApiError } from "@/services/api/errors";
import { z } from "zod";

export const MOVE_HEADS = ["p_up5_1d", "p_down5_1d", "p_up10_1d", "p_down10_1d"] as const;
export type MoveHead = (typeof MOVE_HEADS)[number];

const RunC = z.object({
  model: z.string(),
  refit: z.string().nullable().optional(),
  status: z.string(),
  data_as_of: z.string(),
  target_session: z.string(),
  frozen_at: z.string(),
  git_sha: z.string(),
  universe_size: z.number(),
  scored: z.number(),
  input_count: z.number().nullable().optional(),
  train_rows: z.number().nullable().optional(),
  train_end: z.string().nullable().optional(),
  counts_toward_verdict: z.boolean(),
  skipped_holidays: z.array(z.string()).default([]),
});
export type MoveRun = z.infer<typeof RunC>;

const RowC = z.object({
  symbol: z.string(),
  company_name: z.string().nullable(),
  sector: z.string().nullable(),
  p: z.number(),
  p_opposite: z.number().nullable(),
  events_on_record: z.number(),
});
export type MoveRow = z.infer<typeof RowC>;

const BandC = z.object({ band_lo: z.number(), band_hi: z.number(), rows: z.number(), realised: z.number().nullable() });
export type MoveBand = z.infer<typeof BandC>;

const FinalC = z.object({
  status: z.literal("final"),
  head: z.enum(MOVE_HEADS),
  expected_session: z.string(),
  base_rate: z.number(),
  run: RunC,
  rows: z.array(RowC),
  record: z.object({
    window_label: z.string(), sessions: z.number(), base_rate: z.number(), top10_hit_rate: z.number(), bands: z.array(BandC),
  }).nullable(),
  live_record: z.object({
    sessions: z.number(),
    top10_hits: z.number().nullable(),
    touched: z.number().nullable(),
    graded_rows: z.number().nullable(),
    last_target: z.string().nullable(),
    last_top10_hits: z.number().nullable(),
    last_touched: z.number().nullable(),
    last_graded_rows: z.number().nullable(),
  }),
  limits: z.object({ not_used: z.array(z.string()) }),
});
export type MoveFinal = z.infer<typeof FinalC>;

const PendingC = z.object({
  status: z.literal("not_published"),
  head: z.enum(MOVE_HEADS),
  expected_session: z.string(),
  last_published_for: z.string().nullable(),
  rows: z.array(z.unknown()).length(0),
});
export type MovePending = z.infer<typeof PendingC>;

const InputC = z.object({ v: z.number().nullable(), date: z.string().nullable() });
const EventC = z.object({
  ord: z.number(),
  event_time: z.string(),
  source_label: z.string(),
  is_media: z.boolean(),
  event_type: z.string(),
  event_subtype: z.string(),
  direction: z.string(),
  title: z.string().nullable(),
  url: z.string().nullable(),
  method: z.string(),
});
const StockC = z.object({
  symbol: z.string(),
  company_name: z.string().nullable(),
  sector: z.string().nullable(),
  results_filed: z.boolean(),
  run: RunC,
  estimates: z.record(z.number()),
  inputs: z.record(InputC),
  events: z.array(EventC),
});
export type MoveStock = z.infer<typeof StockC>;
export type MoveEvent = z.infer<typeof EventC>;

export type MoveLatestResult =
  | { kind: "final"; data: MoveFinal }
  | { kind: "not_published"; data: MovePending }
  | { kind: "withheld"; reason: string }
  | { kind: "no_access" }
  | { kind: "error"; message: string };

export type MoveStockResult =
  | { kind: "ok"; data: MoveStock }
  | { kind: "no_access" }
  | { kind: "withheld"; reason: string }
  | { kind: "error"; message: string };

function fromError(e: unknown): { kind: "no_access" } | { kind: "withheld"; reason: string } | { kind: "error"; message: string } {
  if (e instanceof ApiError) {
    if (e.status === 403) return { kind: "no_access" };
    if (e.status === 503 && (e.detail ?? "").startsWith("withheld")) {
      return { kind: "withheld", reason: (e.detail ?? "").replace(/^withheld:\s*/, "") || "not stated" };
    }
    return { kind: "error", message: e.status ? `HTTP ${e.status}` : e.message };
  }
  return { kind: "error", message: e instanceof Error ? e.message : "unexpected response" };
}

export const moveOddsService = {
  async latest(head: MoveHead): Promise<MoveLatestResult> {
    try {
      const res = await http<unknown>({ path: "/api/move-odds/latest", query: { head }, noRetry: true });
      const env = z.object({ data: z.union([FinalC, PendingC]) }).safeParse(res.data);
      if (!env.success) return { kind: "error", message: "unexpected response shape" };
      return env.data.data.status === "final"
        ? { kind: "final", data: env.data.data as MoveFinal }
        : { kind: "not_published", data: env.data.data as MovePending };
    } catch (e) {
      return fromError(e);
    }
  },

  async stock(symbol: string): Promise<MoveStockResult> {
    try {
      const res = await http<unknown>({ path: `/api/move-odds/stocks/${encodeURIComponent(symbol)}`, noRetry: true });
      const env = z.object({ data: StockC }).safeParse(res.data);
      return env.success ? { kind: "ok", data: env.data.data } : { kind: "error", message: "unexpected response shape" };
    } catch (e) {
      return fromError(e);
    }
  },
};

// ── Live prices and breakout checks (GET /api/move-odds/live?symbols=…) ─────────────────────────────────────────────
const ChecksC = z.object({
  above_prev_close: z.boolean(), above_opening_range: z.boolean(), above_vwap: z.boolean(), room_to_level: z.boolean(), volume_pace: z.boolean(),
  bar: z.string(), close: z.number(), vwap: z.number().nullable(), opening_range_high: z.number(), cum_volume: z.number(), volume_needed: z.number(), met: z.number(),
});
export type LiveChecks = z.infer<typeof ChecksC>;
const ConditionsC = z.object({
  evaluated_bars: z.number(),
  latest: ChecksC.nullable(),
  first_met_at: z.string().nullable(),
  close_at_first_met: z.number().nullable(),
  at_first_met: ChecksC.nullable(),
  entry_signal: z.boolean().default(false),
  entry_signal_since: z.string().nullable().default(null),
  close_at_signal_start: z.number().nullable().default(null),
});
export type LiveConditions = z.infer<typeof ConditionsC>;
const PaperExitC = z.object({
  pct: z.number(), level: z.number(), reached: z.boolean(), at: z.string().nullable(), price: z.number(),
  state: z.string(), gross: z.number(), charges: z.number(), net: z.number(),
});
const PaperC = z.object({ qty: z.number(), entry_price: z.number(), entry_time: z.string(), exits: z.array(PaperExitC), marked_at: z.string() });
export type PaperTrade = z.infer<typeof PaperC>;
const QuoteC = z.object({
  symbol: z.string(),
  error: z.string().nullable().optional(),
  last: z.number().optional(),
  prev_close: z.number().optional(),
  change_pct: z.number().optional(),
  day_high: z.number().nullable().optional(),
  day_low: z.number().nullable().optional(),
  high_pct: z.number().nullable().optional(),
  low_pct: z.number().nullable().optional(),
  volume: z.number().nullable().optional(),
  quote_time: z.string().nullable().optional(),
  session_date: z.string().nullable().optional(),
  levels: z.record(z.number()).optional(),
  touched: z.record(z.boolean()).optional(),
  conditions: ConditionsC.nullable().optional(),
  paper: PaperC.nullable().optional(),
});
export type LiveQuote = z.infer<typeof QuoteC>;

const LiveC = z.object({
  source: z.string(),
  delay_note: z.string().optional(),
  fetched_at: z.string(),
  entry_signal_validated: z.boolean(),
  signal_record: z.object({
    window: z.string(), candidates: z.string(), trades: z.number(), touch_rate_after_checks: z.number(), touch_rate_unconditional: z.number(),
    mean_net_return: z.number(), ci95_mean_net_return: z.tuple([z.number(), z.number()]), verdict: z.string(),
  }).nullable(),
  quotes: z.array(QuoteC),
});
export type LivePayload = z.infer<typeof LiveC>;
export type LiveResult = { kind: "ok"; data: LivePayload } | { kind: "no_access" } | { kind: "error"; message: string };

export async function fetchLive(symbols: string[]): Promise<LiveResult> {
  if (!symbols.length) return { kind: "error", message: "no symbols" };
  try {
    const res = await http<unknown>({ path: "/api/move-odds/live", query: { symbols: symbols.slice(0, 60).join(",") }, noRetry: true, timeoutMs: 30_000 });
    const env = LiveC.safeParse(res.data);
    return env.success ? { kind: "ok", data: env.data } : { kind: "error", message: "unexpected response shape" };
  } catch (e) {
    const f = fromError(e);
    return f.kind === "no_access" ? f : { kind: "error", message: f.kind === "withheld" ? f.reason : f.message };
  }
}

// ── Entry-setup diagnostics (GET /api/move-odds/diagnostics) ────────────────────────────────────────────────────────────
// Owner decision 2026-09-17: setups A–D were rejected as entries (0 of 8 validated). Only their research results are shown.
const DiagTradeC = z.object({
  trade: z.enum(["5%", "10%"]), trades: z.number(), mean_net: z.number().nullable(), ci95: z.tuple([z.number(), z.number()]).nullable(),
  baseline_mean_net: z.number(), half1_mean_net: z.number().nullable(), half2_mean_net: z.number().nullable(),
  validation: z.literal("failed"),                       // a passed setup would need a new owner decision, so it cannot render here
});
const DiagSetupC = z.object({
  id: z.enum(["A", "B", "C", "D"]), name: z.string(), status: z.enum(["not_validated", "research_only_insufficient_sample"]),
  status_label: z.string(), headline: z.string(), research_status: z.string(), explanation: z.string(), trades: z.array(DiagTradeC).length(2),
});
const DiagC = z.object({
  source_sha256: z.string(),
  study: z.object({
    first_signal_day: z.string(), last_signal_day: z.string(), universe: z.string(), cost_round_trip: z.number(),
    exits: z.string(), rule: z.string(), baseline: z.string(), tested: z.number(), validated: z.number(),
  }),
  setups: z.array(DiagSetupC).length(4),
});
export type MoveDiagnostics = z.infer<typeof DiagC>;
export type MoveDiagnosticSetup = z.infer<typeof DiagSetupC>;
export type DiagnosticsResult = { kind: "ok"; data: MoveDiagnostics } | { kind: "no_access" } | { kind: "error"; message: string };

export async function fetchDiagnostics(): Promise<DiagnosticsResult> {
  try {
    const res = await http<unknown>({ path: "/api/move-odds/diagnostics", noRetry: true });
    const env = z.object({ data: DiagC }).safeParse(res.data);
    return env.success ? { kind: "ok", data: env.data.data } : { kind: "error", message: "unexpected response shape" };
  } catch (e) {
    const f = fromError(e);
    return f.kind === "no_access" ? f : { kind: "error", message: f.kind === "withheld" ? f.reason : f.message };
  }
}

// ── History (GET /api/move-odds/history) ───────────────────────────────────────────────────────────────────────────────
// Each past published session with its top estimates and what actually happened. A session whose prices are not in yet
// comes back pending; outcome fields stay null rather than reading as a miss.
const OutcomeC = z.object({
  state: z.enum(["graded", "pending"]),
  touched: z.boolean().nullable(),
  move_pct: z.number().nullable(),
  reference_close: z.number().nullable(),
  within3: z.boolean().nullable(),
  within5: z.boolean().nullable(),
  sessions_available: z.number(),
});
const HistoryRowC = z.object({
  rank: z.number(), symbol: z.string(), company_name: z.string().nullable(), sector: z.string().nullable(),
  p: z.number(), is_new: z.boolean().nullable(), outcome: OutcomeC,
});
const HistorySessionC = z.object({
  target_session: z.string(), data_as_of: z.string().nullable(), frozen_at: z.string().nullable(),
  scored: z.number().nullable(), base_rate: z.number().nullable(), state: z.enum(["graded", "pending"]),
  summary: z.object({
    graded_rows: z.number().nullable(), touched: z.number().nullable(), touch_rate: z.number().nullable(),
    top10_touched: z.number().nullable(), top_n_touched: z.number().nullable(),
  }),
  rows: z.array(HistoryRowC),
});
const HistoryC = z.object({ head: z.enum(MOVE_HEADS), model: z.string(), top_n: z.number(), sessions: z.array(HistorySessionC) });
export type MoveHistory = z.infer<typeof HistoryC>;
export type MoveHistorySession = z.infer<typeof HistorySessionC>;
export type MoveHistoryRow = z.infer<typeof HistoryRowC>;
export type HistoryResult = { kind: "ok"; data: MoveHistory } | { kind: "no_access" } | { kind: "error"; message: string };

export async function fetchHistory(head: MoveHead): Promise<HistoryResult> {
  try {
    const res = await http<unknown>({ path: "/api/move-odds/history", query: { head }, noRetry: true });
    const env = z.object({ data: HistoryC }).safeParse(res.data);
    return env.success ? { kind: "ok", data: env.data.data } : { kind: "error", message: "unexpected response shape" };
  } catch (e) {
    const f = fromError(e);
    return f.kind === "no_access" ? f : { kind: "error", message: f.kind === "withheld" ? f.reason : f.message };
  }
}
