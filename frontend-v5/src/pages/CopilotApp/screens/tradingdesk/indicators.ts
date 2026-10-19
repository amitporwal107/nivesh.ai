/**
 * Smart trading desk — the bar type the chart draws, and the few pure readings the desk still makes in the
 * browser. No I/O, no React.
 *
 * Every indicator value and every overlay line (EMA 20 / 50 / 200, the 20-day VWAP of daily prices) comes from
 * one server source: GET /api/research/chart/live/{symbol}/indicators (chart-data.ts useLiveIndicators), which runs
 * nidp/services/technical_indicator_engine/calculator.py — the engine that fills stock_features_daily and that the
 * strategy backtest reads — on the same adjusted daily bars the chart draws. Its lookbacks and formulas arrive in
 * the response (`definitions`) and are shown on screen. Nothing here recomputes them, so the tile, the line and
 * the backend cannot disagree (PRD §7.3, §7.8).
 *
 * What stays here is not an indicator:
 *   largestGap(bars)   the biggest opening gap, open ÷ previous close − 1, over the bars given (risk desk gap check)
 *   rsiZone(v)         the words on the RSI tile: ≥ 70 overbought, 55–70 healthy, otherwise neutral
 */

export interface DailyBar {
  /** YYYY-MM-DD. */
  day: string;
  open: number;
  high: number;
  low: number;
  close: number;
  /** Shares traded. */
  volume: number;
}

export type Series = Array<number | null>;

/**
 * The largest opening gap in the bars: open ÷ the previous session's close − 1, in percent, signed, with its
 * session. Null with fewer than two bars.
 */
export function largestGap(bars: DailyBar[]): { pct: number; day: string } | null {
  let best: { pct: number; day: string } | null = null;
  for (let i = 1; i < bars.length; i++) {
    const pc = bars[i - 1].close;
    if (!(pc > 0)) continue;
    const pct = (bars[i].open / pc - 1) * 100;
    if (best == null || Math.abs(pct) > Math.abs(best.pct)) best = { pct, day: bars[i].day };
  }
  return best;
}

/** RSI reading used on the tile: ≥ 70 overbought, 55–70 healthy, otherwise neutral. */
export function rsiZone(v: number | null): "Overbought" | "Healthy" | "Neutral" | null {
  if (v == null) return null;
  if (v >= 70) return "Overbought";
  if (v >= 55) return "Healthy";
  return "Neutral";
}
