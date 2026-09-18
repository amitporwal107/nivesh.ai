/**
 * Paper trades adapter — Research → Paper (backend/routes/paper_trades.py → DaaS /v1/paper-trades).
 *
 *   GET /api/paper-trades/portfolio?sample=&portfolio=&prediction_date=   one frozen session: positions, paths, exits, universe
 *   GET /api/paper-trades/trades/{id}                                     one trade with its lifecycle log
 *   GET /api/paper-trades/evaluation?sample=&portfolio=                   the latest stored evaluation (forward and replay separate)
 *   GET /api/paper-trades/live?portfolio=                                 target/stop status of the latest forward selection (Yahoo)
 *
 * Every state is explicit so the screen never shows numbers it should not:
 *   ok · empty (nothing recorded yet) · no_access (403, not on the move_odds allowlist) · not_found · error (retry, no cache)
 */
import { http } from "@/services/api/http";
import { ApiError } from "@/services/api/errors";
import { z } from "zod";

export const PORTFOLIOS = ["P5-NEXT", "P10-NEXT"] as const;
export type PaperPortfolio = (typeof PORTFOLIOS)[number];
export type PaperSample = "forward" | "replay";
export const MODES = ["EOD-1", "EOD-3", "EOD-5", "FIXED", "TARGET_STOP"] as const;
export type PaperMode = (typeof MODES)[number];

const n = z.number().nullable();
const s = z.string().nullable();

const ObsC = z.object({
  session_date: z.string(), days_held: z.number(), open_price: n, high_price: n, low_price: n, close_price: n, adjustment_factor: n,
  return_from_entry: n, open_return: n, high_return: n, low_return: n, high_watermark: n, drawdown_from_entry: n, mfe_to_date: n, mae_to_date: n,
  target_hit: z.boolean().nullable(), stop_hit: z.boolean().nullable(), exit_status: s, data_quality_status: s,
});
export type PaperObservation = z.infer<typeof ObsC>;

const ExitC = z.object({
  state: z.string(), exit_date: s, exit_price: n, exit_reason: s, sessions_held: n, gross_return: n, cost_pct: n, net_return: n,
  net_return_050: n, net_return_100: n, mfe: n, mae: n, target_hit: z.boolean().nullable(), stop_hit: z.boolean().nullable(),
});
export type PaperExit = z.infer<typeof ExitC>;

const PositionC = z.object({
  trade_id: z.number(), symbol: z.string(), portfolio_type: z.string(), prediction_date: z.string(), intended_entry_date: z.string(), entry_date: s, entry_price: n,
  entry_source: s, prev_close: n, gap_from_previous_close: n, quantity: n, allocated_capital: n, target_pct: n, stop_pct: n, atr_14: n,
  support_level: n, stop_loss_price: n, stop_method: s, target_1_price: n, target_2_price: n, risk_percent: n, reward_percent: n,
  risk_reward_ratio: n, status: z.string(), status_reason: s, flags: z.array(z.string()), sessions_observed: n,
  counts_toward_evaluation: z.boolean().nullable(), rank: n, model_rank: n, movement_probability: z.number(), p_opposite: n,
  p_other_threshold: n, prediction_close: n, company_name: s, sector: s, size_group: s,
  observations: z.array(ObsC), exits: z.record(ExitC.nullable()),
});
export type PaperPosition = z.infer<typeof PositionC>;

const UniverseC = z.object({
  rank: z.number(), symbol: z.string(), movement_probability: z.number(), p_opposite: n, p_other_threshold: n, selection_status: z.string(),
  prediction_close: n, company_name: s, sector: s, size_group: s, entry_status: s, entry_reason: s, flags: z.array(z.string()).nullable(),
  entry_price: n, gap: n, atr_14: n, stop_loss_price: n, stop_method: s, target_price: n, sessions_observed: n,
  session_dates: z.array(z.string()).nullable(), r_open: z.array(n).nullable(), r_high: z.array(n).nullable(), r_low: z.array(n).nullable(),
  r_close: z.array(n).nullable(), model_label_hit: z.boolean().nullable(),
});
export type PaperUniverseRow = z.infer<typeof UniverseC>;

const BenchRowC = z.object({ benchmark: z.string(), mode: z.string(), state: z.string(), n: n, gross_mean: n, net_mean: n, target_hit_rate: n, positive_rate: n });

const PortfolioC = z.object({
  status: z.literal("ok"), sample: z.enum(["forward", "replay"]), portfolio: z.enum(PORTFOLIOS), prediction_date: z.string(),
  dates: z.array(z.object({ prediction_date: z.string(), entry_session: z.string(), counts: z.boolean() })),
  provenance: z.object({
    model_version: z.string(), feature_version: z.string(), snapshot_sha256: z.string(), prediction_timestamp: z.string(),
    data_cutoff_timestamp: z.string(), next_trading_session: z.string(), rules_id: z.string(), counts_toward_evaluation: z.boolean(),
    scored: z.number(), eligible: z.number(), excluded: z.record(z.number()),
    rules: z.object({ rules_id: z.string(), rules_sha256: z.string(), git_sha: z.string(), registered_at: z.string() }).nullable(),
  }),
  config: z.object({
    target_pct: z.number(), atr_multiplier: z.number(), head: z.string(), other_threshold: z.string(), capital_inr: z.number(),
    positions: z.number(), cost_pct: z.number(), cost_sensitivity_pct: z.array(z.number()), stop_cap_pct: z.number(), headline_mode: z.string(),
  }),
  positions: z.array(PositionC),
  universe: z.array(UniverseC),
  exceptions: z.array(z.object({ symbol: z.string(), status: z.string(), reason: s, flags: z.array(z.string()) })),
  benchmarks: z.array(BenchRowC),
});
export type PaperPortfolioData = z.infer<typeof PortfolioC>;

const EventC = z.object({ to_status: z.string(), from_status: s, effective_at: z.string(), recorded_at: z.string(), note: s });
export type PaperEvent = z.infer<typeof EventC>;
const TradeC = PositionC.extend({
  events: z.array(EventC),
  snapshot: z.object({ prediction_timestamp: z.string(), data_cutoff_timestamp: z.string(), model_version: z.string(), feature_version: z.string(),
                       snapshot_sha256: z.string(), rules_id: z.string() }).nullable(),
});
export type PaperTrade = z.infer<typeof TradeC>;

const Ci = z.object({ mean: n, lo: n, hi: n, n: z.number() }).nullable();
const EvalModeC = z.object({
  mode: z.string(), label: z.string(), headline: z.boolean().optional(), closed_trades: z.number(), sessions: z.number(), gross_mean: n, net_mean: n,
  net_median: n, net_mean_050: n, net_mean_100: n, win_rate: n, profit_factor: n, mean_mfe: n, mean_mae: n, target_hit_rate: n,
  total_net_inr: n, ci95: Ci, edge_vs_a_all: Ci, established: z.boolean(),
  portfolio: z.object({ sessions: z.number(), mean_daily_return: n, volatility_daily: n, sharpe_like: n, total_pnl_inr: n, max_drawdown_inr: n,
                        capital_base_inr: n }).partial().nullable().optional(),
}).passthrough();
const BucketC = z.object({ lo: z.number(), hi: z.number(), n: z.number(), predicted_mean: n.optional(), model_label_rate: n.optional(),
                           trade_target_rate: n.optional(), positive_rate: n.optional(), net_mean: n.optional(), mae_mean: n.optional(),
                           calibration_error: n.optional() });
export type PaperBucket = z.infer<typeof BucketC>;
const EvaluationC = z.object({
  sample: z.string(), portfolio: z.string(), headline_mode: z.string(), as_of_session: s,
  sessions: z.object({ recorded: z.number(), counted: z.number(), with_closed_headline: z.number(), first_counted: s, last_counted: s, not_counted: z.array(z.string()) }),
  // with nothing counted yet the engine stores only { selected: 0 }
  exceptions: z.object({ selected: z.number().default(0), entered: z.number().default(0), by_status: z.record(z.number()).default({}),
                         by_reason: z.record(z.number()).default({}), flags: z.record(z.number()).default({}) }),
  modes: z.array(EvalModeC),
  benchmarks: z.array(z.object({ benchmark: z.string(), label: z.string(), mode: z.string(), sessions: z.number(), trades: z.number(),
                                 net_mean: n, hit_rate: n, positive_rate: n })),
  buckets: z.object({ universe: z.array(BucketC), selected: z.array(BucketC) }),
  statement: z.object({ established: z.boolean(), text: z.string(), min_sessions: z.number() }),
  costs: z.object({ base: z.number(), sensitivity: z.array(z.number()) }),
});
export type PaperEvaluation = z.infer<typeof EvaluationC>;
export type PaperEvalMode = z.infer<typeof EvalModeC>;

const LivePosC = z.object({
  trade_id: z.number(), symbol: z.string(), entry_session: z.string(), entry: n, entry_source: s, provisional: z.boolean(), stop: n, target: n,
  stop_method: s, last: n, return_from_entry: n, day_high: n, day_low: n, at: s, quote_time: s, state: z.string(), label: z.string(), note: z.string(),
});
export type PaperLivePosition = z.infer<typeof LivePosC>;
const LiveC = z.object({
  status: z.literal("ok"), source: z.string(), delay_note: z.string(), fetched_at: z.string(), prediction_date: z.string(), portfolio: z.string(),
  experiment: z.string(), official_note: z.string(), counts: z.object({ holding: z.number(), target: z.number(), stop: z.number(), awaiting: z.number() }),
  positions: z.array(LivePosC),
});
export type PaperLive = z.infer<typeof LiveC>;

export type Fail = { kind: "no_access" } | { kind: "not_found" } | { kind: "error"; message: string };
export type PortfolioResult = { kind: "ok"; data: PaperPortfolioData } | { kind: "empty" } | Fail;
export type TradeResult = { kind: "ok"; data: PaperTrade } | Fail;
export type EvaluationResult = { kind: "ok"; data: PaperEvaluation; asOf: string | null } | { kind: "empty" } | Fail;
export type LiveResult = { kind: "ok"; data: PaperLive } | { kind: "empty" } | Fail;

function fail(e: unknown): Fail {
  if (e instanceof ApiError) {
    if (e.status === 403) return { kind: "no_access" };
    if (e.status === 404) return { kind: "not_found" };
    return { kind: "error", message: e.status ? `HTTP ${e.status}` : e.message };
  }
  return { kind: "error", message: e instanceof Error ? e.message : "unexpected response" };
}

export async function fetchPaperPortfolio(sample: PaperSample, portfolio: PaperPortfolio, predictionDate?: string | null): Promise<PortfolioResult> {
  try {
    const query: Record<string, string> = { sample, portfolio };
    if (predictionDate) query.prediction_date = predictionDate;
    const res = await http<unknown>({ path: "/api/paper-trades/portfolio", query, noRetry: true });
    const d = (res.data as { data?: { status?: string } } | null)?.data;
    if (d?.status === "empty") return { kind: "empty" };
    const env = z.object({ data: PortfolioC }).safeParse(res.data);
    return env.success ? { kind: "ok", data: env.data.data } : { kind: "error", message: "unexpected response shape" };
  } catch (e) {
    return fail(e);
  }
}

export async function fetchPaperTrade(tradeId: number): Promise<TradeResult> {
  try {
    const res = await http<unknown>({ path: `/api/paper-trades/trades/${tradeId}`, noRetry: true });
    const env = z.object({ data: TradeC }).safeParse(res.data);
    return env.success ? { kind: "ok", data: env.data.data } : { kind: "error", message: "unexpected response shape" };
  } catch (e) {
    return fail(e);
  }
}

export async function fetchPaperEvaluation(sample: PaperSample, portfolio: PaperPortfolio): Promise<EvaluationResult> {
  try {
    const res = await http<unknown>({ path: "/api/paper-trades/evaluation", query: { sample, portfolio }, noRetry: true });
    const d = (res.data as { data?: { status?: string } } | null)?.data;
    if (d?.status === "none") return { kind: "empty" };
    const env = z.object({ data: z.object({ status: z.literal("ok"), as_of_session: s, evaluation: EvaluationC }) }).safeParse(res.data);
    return env.success ? { kind: "ok", data: env.data.data.evaluation, asOf: env.data.data.as_of_session } : { kind: "error", message: "unexpected response shape" };
  } catch (e) {
    return fail(e);
  }
}

export async function fetchPaperLive(portfolio: PaperPortfolio): Promise<LiveResult> {
  try {
    const res = await http<unknown>({ path: "/api/paper-trades/live", query: { portfolio }, noRetry: true, timeoutMs: 30_000 });
    const d = (res.data as { data?: { status?: string } } | null)?.data;
    if (d?.status === "empty") return { kind: "empty" };
    const env = z.object({ data: LiveC }).safeParse(res.data);
    return env.success ? { kind: "ok", data: env.data.data } : { kind: "error", message: "unexpected response shape" };
  } catch (e) {
    return fail(e);
  }
}
