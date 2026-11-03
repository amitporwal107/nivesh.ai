/**
 * Chart Analysis timeframes (the "Signals Chart" design of 3 Nov: 1m 3m 5m 15m 1h 1D 1W). Each pill asks GET
 * /api/desk/live-chart for its candles and GET /api/fno/{sym}/futures/oi-buildup for the futures on the same bars.
 *
 *   intraday   Kite candles: `interval` over `sessions` sessions (the route adds its own warm-up sessions for EMA / SMA /
 *              RVOL); the futures OI comes per bar from Kite at the same interval, build-up windows of 4 bars.
 *              When Kite cannot answer, the route draws daily bars and says why (the page shows that note).
 *   1D / 1W    end-of-day bars (1W = one bar per week, built by the route from the daily bars); the futures come from the
 *              NSE F&O bhavcopy (`daily` sessions), build-up windows of 4 sessions (1D) or 5 sessions, about a week (1W).
 */
export type TfKey = "1m" | "3m" | "5m" | "15m" | "1h" | "1D" | "1W";

export interface Timeframe {
  key: TfKey;
  label: string;
  /** the route's interval */
  interval: string;
  /** Kite sessions asked for (intraday only) */
  sessions: number;
  eod: boolean;
  /** bars (intraday) or sessions (end of day) per build-up window */
  window: number;
}

export const TIMEFRAMES: Timeframe[] = [
  { key: "1m", label: "1m", interval: "1m", sessions: 1, eod: false, window: 4 },
  { key: "3m", label: "3m", interval: "3m", sessions: 2, eod: false, window: 4 },
  { key: "5m", label: "5m", interval: "5m", sessions: 3, eod: false, window: 4 },
  { key: "15m", label: "15m", interval: "15m", sessions: 2, eod: false, window: 4 },
  { key: "1h", label: "1h", interval: "60m", sessions: 10, eod: false, window: 4 },
  { key: "1D", label: "1D", interval: "1d", sessions: 2, eod: true, window: 4 },
  { key: "1W", label: "1W", interval: "1w", sessions: 2, eod: true, window: 5 },
];

export const DEFAULT_TF: TfKey = "15m";

/** The pill named by `?tf=`, else the default (an unknown value is ignored, never guessed). */
export function tfOf(raw: string | null | undefined): Timeframe {
  return TIMEFRAMES.find((t) => t.key.toLowerCase() === (raw ?? "").toLowerCase()) ?? TIMEFRAMES.find((t) => t.key === DEFAULT_TF)!;
}

/** Bhavcopy sessions of futures asked for with end-of-day bars: every bar drawn (at least 60), the route's cap 250. */
export const FUT_DAILY_MAX = 250;
export function futDailySessions(tf: Timeframe, eodBars: number): number {
  if (tf.key === "1W") return FUT_DAILY_MAX;
  return Math.min(FUT_DAILY_MAX, Math.max(60, eodBars));
}
