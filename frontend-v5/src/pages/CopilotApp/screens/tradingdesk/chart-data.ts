/**
 * Smart trading desk — the Chart analysis tab's own reads. GET only; nothing here changes data.
 *
 *   GET /api/research/chart-live/{symbol}/ohlcv?start=   daily bars, split and bonus adjusted     useDailyBars
 *                                                         (nidp.prices_eod_adjusted; flag `charting`)
 *   GET /api/move-odds/stocks/{symbol}                   the move-odds model's four next-session  useStockOdds
 *                                                         estimates for one stock (flag `move_odds`)
 *   GET /api/research/chart/live/{symbol}/indicators     every indicator value, its lookback and  useLiveIndicators
 *                                                         the overlay lines, worked out on the server by the
 *                                                         stock_features_daily engine (calculator.py) from the
 *                                                         same adjusted bars; Nifty 50 relative strength; the
 *                                                         price band from security_reference_daily (flag `charting`)
 *   GET /api/research/chart/live/{symbol}/patterns       research.charting's pattern detector on    useLivePatterns
 *                                                         those bars: PRD states and per-criterion pass / fail
 *                                                         (flag `charting`; 503 when the engine is not deployed)
 *   GET /api/positional/backtest/calibration?symbol=     the accumulation detector's historical     useSetupRecord
 *                                                         record: outcomes, hit rates with 95% intervals, the
 *                                                         labelled period, and the bucket of the stock's score
 *   GET /api/positional/scenario?entry=&stop=&…          the trade scenario calculator (PRD §8.5,   useScenario
 *                                                         §8.6): sizing, costs, net outcomes, portfolio impact.
 *                                                         A read: it stores nothing and sends nothing to a broker.
 *
 * Routes switched on per account answer 403 → `{ kind: "locked" }` so the
 * screen can say so. A 404 is an answer too (no prices on record / not in the
 * model's published run). Anything else throws, and a 200 body that is not the
 * shape this tab needs throws a contract error. Missing figures stay null.
 *
 * The full chart (drawing tools, intervals, saved layouts) is the Research
 * chart workspace: fullChartHref() opens it with the symbol and the levels.
 */
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { z } from "zod";
import { http } from "@/services/api/http";
import { ApiError } from "@/services/api/errors";
import { moveOddsService, type MoveStock } from "@/services/adapters/moveOdds.adapter";
import type { Tone } from "../../components/ui";
import { fmtDay } from "../trading/parts";
import { BUCKET_LABEL, type DeskSetup, type SetupBucket, type SetupStatus } from "./desk-data";
import type { DailyBar } from "./indicators";

const isStatus = (e: unknown, status: number) => e instanceof ApiError && e.status === status;

/** YYYY-MM-DD for today shifted by `days` (local calendar day). */
function dayFromToday(days: number): string {
  const d = new Date();
  d.setDate(d.getDate() + days);
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}

// ── daily bars ───────────────────────────────────────────────────────────

/** [date, open, high, low, close, volume], oldest first (backend/routes/research_chart_live.py :: _bar). */
const BarC = z.tuple([z.string(), z.number(), z.number(), z.number(), z.number(), z.number()]);

const OhlcvC = z.object({
  bars: z.array(BarC),
  data_quality_status: z.string().nullish(),
  provenance: z.object({ provider: z.string().nullish(), last_bar_date: z.string().nullish() }).partial().nullish(),
});

/**
 * Calendar days of history to ask for: 6 months shown (126 sessions) plus the
 * 50 sessions the 50-day EMA needs to settle, with room for holidays.
 */
export const HISTORY_DAYS = 320;

export type DailyBars =
  | {
      kind: "ok";
      bars: DailyBar[];
      /** The data platform dropped incomplete sessions from this series. */
      partial: boolean;
      /** e.g. "nidp.prices_eod_adjusted", when the response names it. */
      provider: string | null;
    }
  /** No daily prices on record for this symbol (404, or an empty list). */
  | { kind: "none" }
  /** This account does not have the `charting` feature (403). */
  | { kind: "locked" };

export function useDailyBars(symbol: string | null) {
  return useQuery<DailyBars>({
    queryKey: ["copilot", "desk", "bars", symbol],
    enabled: !!symbol,
    staleTime: 10 * 60_000,
    retry: (count, e) => !(e instanceof ApiError && e.kind === "contract_drift") && count < 1,
    queryFn: async ({ signal }) => {
      const sym = (symbol ?? "").toUpperCase();
      try {
        const res = await http({
          path: `/api/research/chart-live/${encodeURIComponent(sym)}/ohlcv`,
          query: { start: dayFromToday(-HISTORY_DAYS) },
          signal,
        });
        const r = OhlcvC.safeParse(res.data);
        if (!r.success) throw ApiError.contractDrift(`chart-live: ${r.error.issues[0]?.message ?? "unexpected shape"}`, r.error);
        const bars: DailyBar[] = r.data.bars.map(([day, open, high, low, close, volume]) => ({ day, open, high, low, close, volume }));
        if (!bars.length) return { kind: "none" };
        return { kind: "ok", bars, partial: r.data.data_quality_status === "PARTIAL", provider: r.data.provenance?.provider ?? null };
      } catch (e) {
        if (isStatus(e, 403)) return { kind: "locked" };
        if (isStatus(e, 404)) return { kind: "none" };
        throw e;
      }
    },
  });
}

// ── one stock's move-odds estimates ──────────────────────────────────────

export type StockOdds =
  | { kind: "ok"; data: MoveStock }
  /** 404: the model has not published for the next session, or the stock is not in its run. */
  | { kind: "none" }
  | { kind: "withheld"; reason: string }
  /** 403: the account is not on the move_odds allowlist. */
  | { kind: "locked" };

export function useStockOdds(symbol: string | null) {
  return useQuery<StockOdds>({
    queryKey: ["copilot", "desk", "stock-odds", symbol],
    enabled: !!symbol,
    staleTime: 10 * 60_000,
    retry: (count) => count < 1,
    queryFn: async () => {
      const r = await moveOddsService.stock((symbol ?? "").toUpperCase());
      if (r.kind === "ok") return r;
      if (r.kind === "no_access") return { kind: "locked" };
      if (r.kind === "withheld") return { kind: "withheld", reason: r.reason };
      // The adapter reports any other status as "HTTP <status>"; the route answers 404 when there is no estimate to give.
      if (r.message === "HTTP 404") return { kind: "none" };
      throw new Error(r.message);
    },
  });
}

// ── labels the scanner, the chart and the risk desk share ────────────────

export const STATUS_LABEL: Record<SetupStatus, { label: string; tone: Tone }> = {
  confirmed: { label: "Confirmed", tone: "mint" },
  awaiting: { label: "Awaiting", tone: "amber" },
  forming: { label: "Forming", tone: "ink" },
};

/** The same setups in plain words (the design's investor wording, design-spec §10). */
export const BUCKET_PLAIN: Record<SetupBucket, string> = {
  breakout_confirmed: "Broke above a recent high",
  pre_breakout: "Just under a recent high",
  trend_continuation: "Dipped in an uptrend",
  true_accumulation: "Tight sideways range",
};

const STAGE_PLAIN: Record<string, string> = {
  BREAKOUT: "broke out",
  EARLY_BREAKOUT: "about to break out",
  ACCUMULATION: "building a base",
};

/**
 * The bucket's name, or "Scanner pick · early breakout" for a stock only the picks route has.
 * `plain` gives the investor wording ("Broke above a recent high").
 */
export function setupLabel(s: DeskSetup, plain = false): string {
  if (s.bucket) return plain ? BUCKET_PLAIN[s.bucket] : BUCKET_LABEL[s.bucket];
  if (!s.stage) return "Scanner pick";
  const stage = s.stage.replace(/_/g, " ").toLowerCase();
  return `Scanner pick · ${plain ? STAGE_PLAIN[s.stage.toUpperCase()] ?? stage : stage}`;
}

/** The two up-move heads of the move-odds model the scanner ranks by. */
export type UpHead = "p_up5_1d" | "p_up10_1d";

/**
 * The model's probability in the design's slot, worded truthfully: it is a next-session
 * estimate (the session's high reaches the previous close plus the move), never a 20-session one.
 */
export function oddsLabel(head: UpHead, plain: boolean): string {
  const move = head === "p_up10_1d" ? 10 : 5;
  return plain ? `Chance +${move}% next day` : `P(+${move}% next session)`;
}

/** Last close and the change from the one before, from a stock's daily closes (oldest first); null without two. */
export function lastMove(closes: number[]): { close: number; change: number; changePct: number } | null {
  const n = closes.length;
  if (n < 2 || !(closes[n - 2] > 0)) return null;
  const change = closes[n - 1] - closes[n - 2];
  return { close: closes[n - 1], change, changePct: (change / closes[n - 2]) * 100 };
}

/** "13 Oct 2026", or both dates when the two scanner routes are on different sessions. */
export function scanDateLabel(watchAsOf: string | null, signalDate: string | null): string | null {
  if (watchAsOf && signalDate && watchAsOf !== signalDate) return `Watchlist ${fmtDay(watchAsOf)} · picks ${fmtDay(signalDate)}`;
  const d = watchAsOf ?? signalDate;
  return d ? fmtDay(d) : null;
}

// ── live indicators (GET /api/research/chart/live/{symbol}/indicators) ───

const nn = z.number().nullable();

const IndicatorValuesC = z.object({
  close: z.number(),
  ema20: nn, ema50: nn, ema200: nn,
  rsi14: nn, atr14: nn, atr_pct: nn,
  macd: nn, macd_signal: nn, macd_hist: nn,
  roc20: nn, avg_volume20: nn, rvol20: nn, vwap20: nn,
  resistance20: nn, support20: nn, avg_traded_value_cr20: nn,
  rs63: z.object({
    stock_return_pct: z.number(), benchmark_return_pct: z.number(), excess_pct: z.number(),
    from: z.string().nullish(), to: z.string().nullish(),
  }).nullable(),
});

const LiveIndicatorsC = z.object({
  symbol: z.string(),
  as_of: z.string(),
  sessions: z.number(),
  source: z.string(),
  mode: z.string(),
  method: z.string().nullish(),
  adjustment_break: z.object({ date: z.string(), prev_close: z.number(), close: z.number(), ratio: z.number() }).nullish(),
  series_notes: z.record(z.string()).nullish(),
  hypothetical_levels: z.object({
    rule: z.string(), version: z.string(), label: z.string(),
    constants: z.record(z.number()),
    entry: nn, stop: nn, target: nn, risk_reward: nn,
    stop_basis: z.string().nullable(), reason: z.string().nullable(), source: z.string().nullish(),
  }).nullish(),
  values: IndicatorValuesC,
  series: z.object({
    days: z.array(z.string()),
    ema20: z.array(nn), ema50: z.array(nn), ema200: z.array(nn), vwap20: z.array(nn),
  }),
  definitions: z.array(z.object({ key: z.string(), label: z.string(), lookback: z.string(), formula: z.string() })),
  benchmark: z.object({ name: z.string(), source: z.string().nullish(), as_of: z.string().nullish(), reason: z.string().nullish() }),
  tradability: z.object({
    as_of_date: z.string().nullish(),
    price_band_pct: nn.optional(),
    band_raw: z.string().nullish(),
    fno_eligible: z.boolean().nullish(),
    is_etf: z.boolean().nullish(),
    series: z.string().nullish(),
    source: z.string().nullish(),
  }).nullable(),
  tradability_reason: z.string().nullish(),
  liquidity_rule: z.object({ min_traded_value_cr: z.number().nullish(), source: z.string().nullish() }).nullish(),
});
export type LiveIndicators = z.infer<typeof LiveIndicatorsC>;
export type IndicatorValues = LiveIndicators["values"];

export type LiveRead<T> =
  | { kind: "ok"; data: T }
  /** No daily bars on record for the symbol (404). */
  | { kind: "none" }
  /** This account does not have the `charting` feature (403). */
  | { kind: "locked" }
  /** The server cannot answer this here (503), with its reason. */
  | { kind: "unavailable"; reason: string };

async function liveGet<T>(path: string, schema: z.ZodType<T, z.ZodTypeDef, unknown>, what: string, signal?: AbortSignal): Promise<LiveRead<T>> {
  try {
    const res = await http({ path, signal, noRetry: true });
    const r = schema.safeParse(res.data);
    if (!r.success) throw ApiError.contractDrift(`${what}: ${r.error.issues[0]?.message ?? "unexpected shape"}`, r.error);
    return { kind: "ok", data: r.data };
  } catch (e) {
    if (isStatus(e, 403)) return { kind: "locked" };
    if (isStatus(e, 404)) return { kind: "none" };
    if (isStatus(e, 503)) return { kind: "unavailable", reason: e instanceof ApiError && e.detail ? e.detail : "service unavailable" };
    throw e;
  }
}

export function useLiveIndicators(symbol: string | null) {
  return useQuery<LiveRead<LiveIndicators>>({
    queryKey: ["copilot", "desk", "live-indicators", symbol],
    enabled: !!symbol,
    staleTime: 10 * 60_000,
    retry: (count, e) => !(e instanceof ApiError && e.kind === "contract_drift") && count < 1,
    queryFn: ({ signal }) =>
      liveGet(`/api/research/chart/live/${encodeURIComponent((symbol ?? "").toUpperCase())}/indicators`, LiveIndicatorsC, "live indicators", signal),
  });
}

/** The levels the desk shows and sizes: the scanner's when it has any, else the server's rule-based hypothetical ones. */
export interface DeskLevels {
  entry: number | null; stop: number | null; target: number | null; riskReward: number | null;
  source: "scanner" | "rule" | null;
  /** Rule source: its name, version, the plain label, the constants and the basis of the stop. */
  rule: { name: string; version: string; label: string; constants: Record<string, number>; stopBasis: string | null } | null;
  /** Why there are no levels (rule could not derive them, or no indicator read). */
  reason: string | null;
}

export function deskLevels(setup: DeskSetup | null, live: LiveIndicators | null): DeskLevels {
  if (setup && (setup.entry != null || setup.stop != null || setup.target != null)) {
    return { entry: setup.entry, stop: setup.stop, target: setup.target, riskReward: setup.riskReward, source: "scanner", rule: null, reason: null };
  }
  const h = live?.hypothetical_levels ?? null;
  if (!h) return { entry: null, stop: null, target: null, riskReward: null, source: null, rule: null, reason: live ? "The indicator route did not publish rule-based levels." : "No indicator read, so no rule-based levels." };
  const rule = { name: h.rule, version: h.version, label: h.label, constants: h.constants, stopBasis: h.stop_basis };
  if (h.entry == null || h.stop == null) return { entry: null, stop: null, target: null, riskReward: null, source: null, rule, reason: h.reason ?? "The rule could not derive levels." };
  return { entry: h.entry, stop: h.stop, target: h.target, riskReward: h.risk_reward, source: "rule", rule, reason: null };
}

export function useDeskLevels(symbol: string, setup: DeskSetup | null): DeskLevels {
  const q = useLiveIndicators(symbol);
  return deskLevels(setup, q.data?.kind === "ok" ? q.data.data : null);
}

/** A server series as a line aligned to the bars the chart draws (null where the server has no value for that day). */
export function alignSeries(days: string[], values: Array<number | null>, bars: DailyBar[]): Array<number | null> {
  const at = new Map<string, number | null>();
  days.forEach((d, i) => at.set(d, values[i] ?? null));
  return bars.map((b) => at.get(b.day) ?? null);
}

// ── live patterns (GET /api/research/chart/live/{symbol}/patterns) ───────

export const PATTERN_STATES = ["candidate", "awaiting_confirmation", "confirmed", "invalidated", "expired"] as const;
export type PatternState = (typeof PATTERN_STATES)[number];

const CriterionC = z.object({
  key: z.string(),
  label: z.string(),
  status: z.enum(["pass", "fail", "pending", "na"]),
  judged_by: z.string().nullish(),
  observed: z.string().nullish(),
  threshold: z.number().nullish(),
  reason: z.string().nullish(),
});
export type PatternCriterion = z.infer<typeof CriterionC>;

const PatternC = z.object({
  pattern_id: z.string(),
  pattern_type: z.string(),
  label: z.string(),
  direction: z.string().nullish(),
  lifecycle_status: z.string().nullish(),
  state: z.enum(PATTERN_STATES).nullable(),
  state_reason: z.string().nullish(),
  detected_on: z.string().nullish(),
  formation_start: z.string().nullish(),
  formation_end: z.string().nullish(),
  rules: z.array(z.object({ rule_id: z.string(), result: z.string(), observed: z.unknown(), threshold: z.unknown() })).default([]),
  criteria: z.array(CriterionC),
});
export type LivePattern = z.infer<typeof PatternC>;

const LivePatternsC = z.object({
  symbol: z.string(),
  as_of: z.string(),
  source: z.string(),
  mode: z.string(),
  engine: z.object({ engine_version: z.string(), config_hash: z.string(), profile: z.string().nullish(), registry_version: z.string().nullish() }),
  state_rule: z.record(z.string()),
  criteria_rule: z.record(z.string()),
  patterns: z.array(PatternC),
  total: z.number(),
  families: z.array(z.object({
    pattern_type: z.string(), label: z.string(), enabled: z.boolean(), disabled_reason: z.string().nullish(), spec: z.string().nullish(),
  })),
});
export type LivePatterns = z.infer<typeof LivePatternsC>;

export function useLivePatterns(symbol: string | null) {
  return useQuery<LiveRead<LivePatterns>>({
    queryKey: ["copilot", "desk", "live-patterns", symbol],
    enabled: !!symbol,
    staleTime: 10 * 60_000,
    retry: (count, e) => !(e instanceof ApiError && e.kind === "contract_drift") && count < 1,
    queryFn: ({ signal }) =>
      liveGet(`/api/research/chart/live/${encodeURIComponent((symbol ?? "").toUpperCase())}/patterns`, LivePatternsC, "live patterns", signal),
  });
}

/** The PRD's five states, in words. */
export const STATE_LABEL: Record<PatternState, { trader: string; plain: string; tone: Tone }> = {
  candidate: { trader: "Candidate", plain: "Shape forming", tone: "ink" },
  awaiting_confirmation: { trader: "Awaiting confirmation", plain: "Waiting for proof", tone: "amber" },
  confirmed: { trader: "Confirmed", plain: "Confirmed", tone: "mint" },
  invalidated: { trader: "Invalidated", plain: "Did not hold", tone: "danger" },
  expired: { trader: "Expired", plain: "Ran out of time", tone: "ink" },
};

// ── historical record (GET /api/positional/backtest/calibration) ─────────

/** The record the desk shows: this horizon, every outcome metric on its own row. */
export const RECORD_HORIZON = 10;

const RecordRowC = z.object({
  metric: z.string(),
  bucket_lo: nn, bucket_hi: nn,
  horizon_days: z.number().nullable(),
  sample_count: z.number(),
  moves_count: z.number(),
  probability: nn,
  avg_fwd_return: nn,
  avg_fwd_drawdown: nn,
  ci95_lo: nn.optional(),
  ci95_hi: nn.optional(),
  matched: z.boolean().optional(),
});
export type RecordRow = z.infer<typeof RecordRowC>;

const SetupRecordC = z.object({
  buckets: z.array(RecordRowC),
  metrics: z.record(z.object({ label: z.string(), outcome_type: z.string(), rule: z.string() })).optional(),
  measures: z.record(z.string()).optional(),
  not_measured: z.record(z.string()).optional(),
  sample: z.object({
    first_scan_date: z.string().nullish(), last_scan_date: z.string().nullish(), labelled_rows: z.number(), engine_versions: z.array(z.string()).default([]),
  }).nullish(),
  sample_reason: z.string().nullish(),
  symbol_score: z.object({ symbol: z.string(), as_of_date: z.string(), accumulation_score: z.number() }).nullish(),
  symbol_reason: z.string().nullish(),
  empty_reason: z.string().nullish(),
  _reason: z.string().nullish(),
  source: z.string().nullish(),
  method: z.string().nullish(),
});
export type SetupRecord = z.infer<typeof SetupRecordC>;

export function useSetupRecord(symbol: string | null) {
  return useQuery<SetupRecord>({
    queryKey: ["copilot", "desk", "setup-record", symbol],
    enabled: !!symbol,
    staleTime: 30 * 60_000,
    retry: (count, e) => !(e instanceof ApiError && e.kind === "contract_drift") && count < 1,
    queryFn: async ({ signal }) => {
      const res = await http({
        path: "/api/positional/backtest/calibration",
        query: { symbol: (symbol ?? "").toUpperCase(), horizon_days: RECORD_HORIZON },
        signal,
      });
      const r = SetupRecordC.safeParse(res.data);
      if (!r.success) throw ApiError.contractDrift(`calibration: ${r.error.issues[0]?.message ?? "unexpected shape"}`, r.error);
      return r.data;
    },
  });
}

// ── trade scenario (GET /api/positional/scenario) ────────────────────────

export interface ScenarioInputs {
  entry: number;
  stop: number;
  target: number | null;
  capital: number | null;
  /** Percent of capital. */
  riskPct: number | null;
  /** Percent of capital. */
  maxAllocPct: number;
  /** Percent per side. */
  slippagePct: number;
  /** Rupees per side. */
  brokeragePerSide: number;
  maxQty: number | null;
  lotSize: number;
  portfolioValue: number | null;
  existingValue: number | null;
  sectorValue: number | null;
}

const ProblemC = z.object({ field: z.string(), code: z.string(), message: z.string() });
export type ScenarioProblem = z.infer<typeof ProblemC>;

const ScenarioC = z.object({
  valid: z.boolean(),
  problems: z.array(ProblemC),
  warnings: z.array(ProblemC).default([]),
  side: z.string(),
  per_share: z.object({ risk: z.number(), reward: nn, reward_to_risk: nn }).nullable(),
  sizing: z.object({
    risk_budget: z.number(), qty_by_risk: z.number(), qty_by_allocation: nn, qty_by_max: nn, lot_size: z.number(),
    quantity: z.number(), binding: z.string(), gross_exposure: z.number(), allocation_pct: nn, max_alloc_pct: z.number(),
  }).nullable(),
  costs: z.object({ entry: z.number(), exit_at_stop: z.number(), exit_at_target: nn, round_trip_at_stop: z.number(), round_trip_at_target: nn }).nullable(),
  outcomes: z.object({ loss_at_stop: z.number(), loss_at_stop_net: z.number(), profit_at_target: nn, profit_at_target_net: nn }).nullable(),
  portfolio: z.object({
    portfolio_value: z.number(),
    stock_weight_before_pct: z.number(), stock_weight_after_pct: z.number(), stock_weight_change_pct: z.number(),
    sector_weight_before_pct: nn, sector_weight_after_pct: nn,
    impact_at_stop_pct: nn, impact_at_target_pct: nn,
    assumption: z.string().nullish(),
  }).nullable(),
  cost_model: z.object({ slippage_pct_per_side: z.number(), brokerage_inr_per_side: z.number(), source: z.string().nullish() }),
  caveats: z.array(z.string()).default([]),
  method: z.string().nullish(),
  sent_to_broker: z.literal(false),
});
export type Scenario = z.infer<typeof ScenarioC>;

/** The query the route reads; only the figures that are set are sent. */
export function scenarioQuery(i: ScenarioInputs): Record<string, number | string> {
  const q: Record<string, number | string> = { entry: i.entry, stop: i.stop, max_alloc_pct: i.maxAllocPct, slippage_pct: i.slippagePct, brokerage_per_side: i.brokeragePerSide, lot_size: i.lotSize };
  if (i.target != null) q.target = i.target;
  if (i.capital != null) q.capital = i.capital;
  if (i.riskPct != null) q.risk_pct = i.riskPct;
  if (i.maxQty != null) q.max_qty = i.maxQty;
  if (i.portfolioValue != null && i.portfolioValue > 0) q.portfolio_value = i.portfolioValue;
  if (i.existingValue != null) q.existing_value = i.existingValue;
  if (i.sectorValue != null) q.sector_value = i.sectorValue;
  return q;
}

/** null inputs: nothing to ask (no entry and stop yet). The previous answer stays on screen while a new one loads. */
export function useScenario(inputs: ScenarioInputs | null) {
  const query = inputs ? scenarioQuery(inputs) : null;
  return useQuery<Scenario>({
    queryKey: ["copilot", "desk", "scenario", query],
    enabled: !!query,
    staleTime: 5 * 60_000,
    placeholderData: keepPreviousData,
    retry: (count, e) => !(e instanceof ApiError && (e.kind === "contract_drift" || e.status === 422)) && count < 1,
    queryFn: async ({ signal }) => {
      const res = await http({ path: "/api/positional/scenario", query: query ?? {}, signal });
      const r = ScenarioC.safeParse(res.data);
      if (!r.success) throw ApiError.contractDrift(`scenario: ${r.error.issues[0]?.message ?? "unexpected shape"}`, r.error);
      return r.data;
    },
  });
}

// ── the full chart (Research → Charts) ───────────────────────────────────

/**
 * The Research chart workspace (frontend-v5/src/pages/Research/charts/ChartsScreen.tsx) for a symbol, with the
 * levels it draws. It reads ?screen=charts&symbol=&entry=&stop=&t1= once, when it mounts, so this is a real link (a
 * fresh navigation), not a state change. Only levels that exist are sent: an absent target never arrives as 0.
 */
export function fullChartHref(symbol: string, levels: { entry: number | null; stop: number | null; target: number | null }): string {
  const q = new URLSearchParams({ screen: "charts", symbol: symbol.toUpperCase() });
  const put = (k: string, v: number | null) => {
    if (v != null && Number.isFinite(v) && v > 0) q.set(k, String(v));
  };
  put("entry", levels.entry);
  put("stop", levels.stop);
  put("t1", levels.target);
  return `${import.meta.env.BASE_URL}research?${q.toString()}`;
}

/** Chart intervals (PRD §7.2). Only daily bars exist for the desk: intraday needs bars nobody collects here yet. */
export const INTERVALS = [
  { value: "1D", label: "Daily", id: "1d", disabled: false },
  { value: "60m", label: "60m", id: "60m", disabled: true },
  { value: "30m", label: "30m", id: "30m", disabled: true },
  { value: "15m", label: "15m", id: "15m", disabled: true },
  { value: "5m", label: "5m", id: "5m", disabled: true },
] as const;
export const INTRADAY_REASON =
  "No intraday bars on record: nidp.intraday_bars is not collected on this environment and has no read route yet. Daily bars only.";
