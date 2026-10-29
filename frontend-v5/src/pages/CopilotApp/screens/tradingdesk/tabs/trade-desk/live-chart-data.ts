/**
 * Trade Desk › Chart Analysis › Live chart — the two reads of the owner's design (28 Oct), validated before use:
 *
 *   GET /api/desk/live-chart/{symbol}?plan_id=&interval=15m&sessions=2     useLiveChart
 *       the candles (Kite 15m, or daily with the reason), EMA 20 and RVOL on the same bars, the plan's or the scanner
 *       signal's levels, the signal conditions with status and value, the WATCH / READY / CONFIRMED / RVOL markers
 *       (backend routes/desk_live_chart.py; nothing is computed here)
 *   GET /api/fno/{symbol}/futures/oi-buildup?interval=15m&window=4&sessions=2   useOiBuildup
 *       the current / next / far month futures and consolidated, per 4-bar window: price change, OI change, volume, the
 *       build-up class (the desk board's rule), with the snapshot time; `mode` intraday (Kite) or end_of_day (bhavcopy);
 *       in intraday mode each series also carries `bars` [[t, close, volume, oi]] (+ one baseline bar) for the futures pane
 *   GET /api/fno/{symbol}/options/intraday?interval=15m&sessions=2&strikes=5   useOptionsIntraday
 *       the nearest expiry's ATM ±5 strikes, CE and PE, from Kite history: per-bar CE / PE OI, OI change, volume and PCR
 *   GET /api/desk/chart-events/{symbol}                                    useChartEvents
 *       results / board meetings, filings, corporate actions, macro, F&O expiry and FII/DII flow days, each with its
 *       price and volume reaction (day %, next day %, gap %, volume × 20-day average) from the daily bars
 *
 * A body that is not the documented shape throws a contract error, so the screen shows an error, never blanks.
 */
import { useQuery } from "@tanstack/react-query";
import { z } from "zod";
import { http } from "@/services/api/http";
import { ApiError } from "@/services/api/errors";

const N = z.number().nullable();
const NO = z.number().nullable().optional();
const S = z.string().nullable().optional();

const Bar = z.tuple([z.string(), z.number(), z.number(), z.number(), z.number(), z.number()]);

const ConditionC = z.object({
  key: z.string(), label: z.string(),
  status: z.enum(["met", "not_met", "waiting", "hit", "not_hit", "not_applicable", "unavailable"]),
  value: z.string(), rule: z.string(), at: S,
});
export type LiveCondition = z.infer<typeof ConditionC>;

const MarkerC = z.object({ kind: z.string(), at: z.string(), text: S, rvol: NO, signal_date: S, stage: S });
export type LiveMarker = z.infer<typeof MarkerC>;

const LevelsC = z.object({
  source: z.enum(["plan", "signal"]).nullable(),
  plan_id: S,
  entry: N, stop: N,
  targets: z.array(z.object({ name: z.string().nullable(), price: N, primary: z.boolean().optional() })).default([]),
  rule: S, valid_for_sessions: NO, reference_close: NO, direction: S, signal_date: S,
}).passthrough();
export type LiveLevels = z.infer<typeof LevelsC>;

/** Today's daily bar from Kite before the exchange's end-of-day file: the live quote in the session, the saved Kite close after
 *  it (services/kite_live_feed/day_quote.py). Provisional: raw Kite prices, replaced by the exchange's bar once it is in. */
const TodayC = z.object({
  source: z.enum(["kite_live", "kite_close"]), day: z.string(), provisional: z.boolean(), at: S, price: z.number(), text: S,
}).passthrough();
export type LiveToday = z.infer<typeof TodayC>;

const LiveChartC = z.object({
  symbol: z.string(),
  as_of: z.string(),
  timeframe: z.object({
    interval: z.string(), label: z.string(), source: z.string(), adjusted: z.boolean(), reason: S, reason_text: S, live_merged: z.boolean().optional(), note: S,
    today: TodayC.nullable().optional(), today_why: S, today_text: S,
  }),
  bars: z.array(Bar),
  ema20: z.array(N),
  rvol: z.array(N),
  last: z.object({ price: z.number(), at: z.string(), bar_complete: z.boolean(), source: S }),
  levels: LevelsC,
  signal: z.object({ signal_date: z.string(), stage: S, kind: S, revision: NO, engine_version: S, computed_at: S }).nullable(),
  signals_error: S,
  markers: z.array(MarkerC),
  markers_error: S,
  conditions: z.array(ConditionC),
  evaluated_at_bar: S,
  valid_until: S,
  sessions_left: NO,
  holidays_checked: z.boolean().optional(),
  paper_engine: z.string(),
});
export type LiveChart = z.infer<typeof LiveChartC>;

export const LIVE_CHART_KEY = (symbol: string, planId: string | null) => ["copilot", "desk", "live-chart", symbol, planId ?? ""] as const;

export function useLiveChart(symbol: string | null, planId: string | null, sessionOpen: boolean) {
  return useQuery<LiveChart>({
    queryKey: LIVE_CHART_KEY(symbol ?? "", planId),
    enabled: !!symbol,
    staleTime: 30_000,
    refetchInterval: sessionOpen ? 60_000 : false,
    retry: (count, e) => !(e instanceof ApiError && (e.kind === "contract_drift" || (e.status != null && e.status < 500))) && count < 1,
    queryFn: async ({ signal }) => {
      const res = await http({
        path: `/api/desk/live-chart/${encodeURIComponent((symbol ?? "").toUpperCase())}`,
        query: { interval: "15m", sessions: 2, ...(planId ? { plan_id: planId } : {}) },
        signal,
        timeoutMs: 30_000,
      });
      const r = LiveChartC.safeParse(res.data);
      if (!r.success) throw ApiError.contractDrift(`live-chart: ${r.error.issues[0]?.path.join(".")} ${r.error.issues[0]?.message ?? "unexpected shape"}`, r.error);
      return r.data;
    },
  });
}

// ── futures OI build-up by window ────────────────────────────────────────

const WindowC = z.object({
  day: z.string(), index: z.number(), start: z.string(), end: z.string(), bars: z.number(),
  close: N, price_change: N, price_change_pct: NO, oi: N, oi_change: N, oi_change_pct: NO, volume: N,
  label: z.enum(["long_buildup", "short_buildup", "short_covering", "long_unwinding", "neutral"]).nullable(),
  complete: z.boolean().optional(),
});
export type OiWindow = z.infer<typeof WindowC>;

/** [t, close, volume, oi]: one futures candle (Kite 15m) for the per-bar futures pane; nulls where Kite gave none. */
const FutBarC = z.tuple([z.string(), N, N, N]);
export type FutBar = z.infer<typeof FutBarC>;

const SeriesC = z.object({
  slot: z.string(), expiry: S, tradingsymbol: S, lot_size: NO, windows: z.array(WindowC),
  expiries: z.array(z.string().nullable()).optional(), basis: S,
  bars: z.array(FutBarC).optional().default([]),
});
export type OiSeries = z.infer<typeof SeriesC>;

const OiBuildupC = z.object({
  symbol: z.string(),
  mode: z.enum(["intraday", "end_of_day"]),
  interval: z.string(), window: z.number(), sessions: z.number(),
  source: S, snapshot_at: S, last_bar_at: S,
  contracts: z.array(SeriesC),
  consolidated: SeriesC,
  missing_slots: z.array(z.string()).optional().default([]),
  missing_note: S,
  kite_reason: S,
  note: z.string(),
});
export type OiBuildup = z.infer<typeof OiBuildupC>;

export type OiResult = { kind: "ok"; data: OiBuildup } | { kind: "none"; message: string };

export function useOiBuildup(symbol: string | null, sessionOpen: boolean) {
  return useQuery<OiResult>({
    queryKey: ["copilot", "desk", "oi-buildup", symbol ?? ""],
    enabled: !!symbol,
    staleTime: 30_000,
    refetchInterval: sessionOpen ? 60_000 : false,
    retry: (count, e) => !(e instanceof ApiError && (e.kind === "contract_drift" || (e.status != null && e.status < 500))) && count < 1,
    queryFn: async ({ signal }) => {
      try {
        const res = await http({
          path: `/api/fno/${encodeURIComponent((symbol ?? "").toUpperCase())}/futures/oi-buildup`,
          query: { interval: "15m", window: 4, sessions: 2 },
          signal,
          timeoutMs: 30_000,
        });
        const r = OiBuildupC.safeParse(res.data);
        if (!r.success) throw ApiError.contractDrift(`oi-buildup: ${r.error.issues[0]?.path.join(".")} ${r.error.issues[0]?.message ?? "unexpected shape"}`, r.error);
        return { kind: "ok", data: r.data };
      } catch (e) {
        if (e instanceof ApiError && e.status === 404) return { kind: "none", message: `${symbol} has no futures in the F&O segment.` };
        throw e;
      }
    },
  });
}

export const SLOT_LABEL: Record<string, string> = { current: "Current month", next: "Next month", far: "Far month", consolidated: "Consolidated" };

// ── IV percentile (GET /api/fno/{symbol}/iv-history) ─────────────────────

const IvHistoryC = z.object({
  iv_percentile: NO, iv_rank: NO, sessions: z.number().optional(), min_sessions: NO, last_session: S, reason: S,
}).passthrough();
export type IvHistory = z.infer<typeof IvHistoryC>;

/** The recorded ATM IV history's percentile (null with the route's reason until 252 sessions are recorded). */
export function useIvHistory(symbol: string | null) {
  return useQuery<IvHistory | null>({
    queryKey: ["copilot", "desk", "iv-history", symbol ?? ""],
    enabled: !!symbol,
    staleTime: 10 * 60_000,
    retry: false,
    queryFn: async ({ signal }) => {
      const res = await http({ path: `/api/fno/${encodeURIComponent((symbol ?? "").toUpperCase())}/iv-history`, query: { days: 5 }, signal });
      const r = IvHistoryC.safeParse(res.data);
      if (!r.success) throw ApiError.contractDrift("iv-history: unexpected shape", r.error);
      return r.data;
    },
  });
}

// ── options intraday (GET /api/fno/{symbol}/options/intraday) ────────────

const OptRowC = z.object({ t: z.string(), ce_oi: N, pe_oi: N, ce_oi_change: N, pe_oi_change: N, ce_volume: N, pe_volume: N, pcr: N });
export type OptRow = z.infer<typeof OptRowC>;
const OptionsIntradayC = z.object({
  symbol: z.string(),
  availability: z.string(),
  interval: z.string().optional(), sessions: NO,
  expiry: S, atm: NO, strikes: z.array(z.number()).optional().default([]),
  ref: z.object({ price: NO, source: S, at: S }).nullable().optional(),
  series: z.array(OptRowC).optional().default([]),
  missing: z.array(z.string()).optional().default([]),
  source: S, as_of: S, note: S,
}).passthrough();
export type OptionsIntraday = z.infer<typeof OptionsIntradayC>;

export type OptionsResult = { kind: "ok"; data: OptionsIntraday } | { kind: "none"; message: string };

/** Why the options pane is empty, in the screen's words (availability codes of the route). */
export const OPTIONS_WHY: Record<string, string> = {
  token_missing: "Kite login needed for the option candles: the platform Kite session is not logged in today.",
  token_expired: "Kite login needed for the option candles: the platform Kite session expired.",
  no_options: "No option contracts are listed for this stock.",
  no_bars: "Kite returned no option candles for these strikes.",
  upstream_unavailable: "Kite did not answer for the option candles.",
};

/** Only with intraday candles on the chart (the series is per Kite 15m bar). */
export function useOptionsIntraday(symbol: string | null, sessionOpen: boolean, enabled: boolean) {
  return useQuery<OptionsResult>({
    queryKey: ["copilot", "desk", "options-intraday", symbol ?? ""],
    enabled: !!symbol && enabled,
    staleTime: 30_000,
    refetchInterval: sessionOpen ? 60_000 : false,
    retry: (count, e) => !(e instanceof ApiError && (e.kind === "contract_drift" || (e.status != null && e.status < 500))) && count < 1,
    queryFn: async ({ signal }) => {
      try {
        const res = await http({
          path: `/api/fno/${encodeURIComponent((symbol ?? "").toUpperCase())}/options/intraday`,
          query: { interval: "15m", sessions: 2, strikes: 5 },
          signal,
          timeoutMs: 45_000,
        });
        const r = OptionsIntradayC.safeParse(res.data);
        if (!r.success) throw ApiError.contractDrift(`options-intraday: ${r.error.issues[0]?.path.join(".")} ${r.error.issues[0]?.message ?? "unexpected shape"}`, r.error);
        return { kind: "ok", data: r.data };
      } catch (e) {
        if (e instanceof ApiError && e.status === 404) return { kind: "none", message: `${symbol} has no options in the F&O segment.` };
        throw e;
      }
    },
  });
}

// ── chart events (GET /api/desk/chart-events/{symbol}) ───────────────────

export const EVENT_KINDS = ["results", "board", "filing", "dividend", "split", "bonus", "buyback", "rights", "agm", "demerger", "macro", "fno_expiry", "fii_dii"] as const;
const ReactionC = z.object({
  basis: S, day_change_pct: NO, next_day_change_pct: NO, gap_pct: NO, volume_x_avg20: NO, provisional: z.boolean().optional(),
}).passthrough();
const ChartEventC = z.object({
  id: z.string(), date: z.string(), time: S, kind: z.string(), scope: z.string(), title: z.string(), detail: S, source: S, url: S,
  reaction: ReactionC.nullable().optional(),
}).passthrough();
export type DeskChartEvent = z.infer<typeof ChartEventC>;
const ChartEventsC = z.object({
  symbol: z.string(), from: z.string(), to: z.string(),
  events: z.array(ChartEventC),
  sources: z.record(z.string(), z.string()).optional().default({}),
  fii_dii_rule: S,
}).passthrough();
export type ChartEvents = z.infer<typeof ChartEventsC>;

export function useChartEvents(symbol: string | null) {
  return useQuery<ChartEvents>({
    queryKey: ["copilot", "desk", "chart-events", symbol ?? ""],
    enabled: !!symbol,
    staleTime: 5 * 60_000,
    retry: (count, e) => !(e instanceof ApiError && (e.kind === "contract_drift" || (e.status != null && e.status < 500))) && count < 1,
    queryFn: async ({ signal }) => {
      const res = await http({ path: `/api/desk/chart-events/${encodeURIComponent((symbol ?? "").toUpperCase())}`, signal, timeoutMs: 30_000 });
      const r = ChartEventsC.safeParse(res.data);
      if (!r.success) throw ApiError.contractDrift(`chart-events: ${r.error.issues[0]?.path.join(".")} ${r.error.issues[0]?.message ?? "unexpected shape"}`, r.error);
      return r.data;
    },
  });
}
