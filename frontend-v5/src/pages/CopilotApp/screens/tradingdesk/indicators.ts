/**
 * Smart trading desk — technical indicators worked out in the browser from
 * end-of-day daily bars (GET /api/research/chart-live/{symbol}/ohlcv, read in
 * chart-data.ts). Pure functions: no I/O, no React.
 *
 * Every series is aligned to its input: index i holds the value as of session
 * i, and null where there is not yet enough history. Inputs are oldest first.
 *
 *   ema(values, n)        EMA with k = 2 / (n + 1), seeded with the simple mean of the first n values
 *   rsiWilder(closes, 14) Wilder's RSI: the first average gain / loss is the simple mean of the first 14
 *                         changes, then avg = (prev × 13 + today) / 14; RSI = 100 − 100 / (1 + gain / loss)
 *   atrWilder(bars, 14)   true range TR = max(H − L, |H − prev C|, |L − prev C|) from the second bar on;
 *                         the first ATR is the mean of the first 14 TRs, then (prev × 13 + TR) / 14
 *   vwapRolling(bars, 20) Σ(typical × volume) / Σ volume over the last 20 sessions, typical = (H + L + C) / 3.
 *                         A 20-day volume-weighted average of daily prices — not the intraday VWAP.
 *   rvol(bars, 20)        the latest session's volume ÷ the mean volume of the 20 sessions before it
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

/** Exponential moving average seeded with the simple mean of the first `n` values. */
export function ema(values: number[], n: number): Series {
  const out: Series = values.map(() => null);
  if (n < 1 || values.length < n) return out;
  const k = 2 / (n + 1);
  let prev = 0;
  for (let i = 0; i < n; i++) prev += values[i];
  prev /= n;
  out[n - 1] = prev;
  for (let i = n; i < values.length; i++) {
    prev = values[i] * k + prev * (1 - k);
    out[i] = prev;
  }
  return out;
}

/** Wilder's relative strength index. Null until `n` changes exist (index n). */
export function rsiWilder(closes: number[], n = 14): Series {
  const out: Series = closes.map(() => null);
  if (n < 1 || closes.length <= n) return out;
  let gain = 0;
  let loss = 0;
  for (let i = 1; i <= n; i++) {
    const ch = closes[i] - closes[i - 1];
    if (ch > 0) gain += ch;
    else loss -= ch;
  }
  gain /= n;
  loss /= n;
  const rsi = (g: number, l: number) => (l === 0 ? (g === 0 ? 50 : 100) : 100 - 100 / (1 + g / l));
  out[n] = rsi(gain, loss);
  for (let i = n + 1; i < closes.length; i++) {
    const ch = closes[i] - closes[i - 1];
    gain = (gain * (n - 1) + Math.max(ch, 0)) / n;
    loss = (loss * (n - 1) + Math.max(-ch, 0)) / n;
    out[i] = rsi(gain, loss);
  }
  return out;
}

/** True range of bar i (needs the previous close, so it starts at the second bar). */
function trueRange(bars: DailyBar[], i: number): number {
  const b = bars[i];
  const pc = bars[i - 1].close;
  return Math.max(b.high - b.low, Math.abs(b.high - pc), Math.abs(b.low - pc));
}

/** Wilder's average true range, in rupees. Null until `n` true ranges exist (index n). */
export function atrWilder(bars: DailyBar[], n = 14): Series {
  const out: Series = bars.map(() => null);
  if (n < 1 || bars.length <= n) return out;
  let atr = 0;
  for (let i = 1; i <= n; i++) atr += trueRange(bars, i);
  atr /= n;
  out[n] = atr;
  for (let i = n + 1; i < bars.length; i++) {
    atr = (atr * (n - 1) + trueRange(bars, i)) / n;
    out[i] = atr;
  }
  return out;
}

/** Rolling volume-weighted average of the daily typical price over `n` sessions. Null when the window traded nothing. */
export function vwapRolling(bars: DailyBar[], n = 20): Series {
  const out: Series = bars.map(() => null);
  if (n < 1) return out;
  for (let i = n - 1; i < bars.length; i++) {
    let pv = 0;
    let vol = 0;
    for (let j = i - n + 1; j <= i; j++) {
      const b = bars[j];
      pv += ((b.high + b.low + b.close) / 3) * b.volume;
      vol += b.volume;
    }
    out[i] = vol > 0 ? pv / vol : null;
  }
  return out;
}

/** Relative volume: the last session's volume ÷ the mean of the `n` sessions before it. Null without n + 1 sessions or with no volume. */
export function rvol(bars: DailyBar[], n = 20): number | null {
  if (n < 1 || bars.length < n + 1) return null;
  const last = bars[bars.length - 1].volume;
  let sum = 0;
  for (let i = bars.length - 1 - n; i < bars.length - 1; i++) sum += bars[i].volume;
  const mean = sum / n;
  return mean > 0 ? last / mean : null;
}

/** The value as of the last session (null when that session has none — never an older value). */
export function latest(series: Series): number | null {
  const v = series.length ? series[series.length - 1] : null;
  return v != null && Number.isFinite(v) ? v : null;
}

/** RSI reading used on the tile: ≥ 70 overbought, 55–70 healthy, otherwise neutral. */
export function rsiZone(v: number | null): "Overbought" | "Healthy" | "Neutral" | null {
  if (v == null) return null;
  if (v >= 70) return "Overbought";
  if (v >= 55) return "Healthy";
  return "Neutral";
}

/** Everything the indicator tiles show, from the whole bar series (oldest first). */
export interface IndicatorSnapshot {
  close: number | null;
  ema20: number | null;
  ema50: number | null;
  rsi14: number | null;
  atr14: number | null;
  /** ATR as a percent of the last close. */
  atrPct: number | null;
  vwap20: number | null;
  rvol20: number | null;
}

export function snapshot(bars: DailyBar[]): IndicatorSnapshot {
  const closes = bars.map((b) => b.close);
  const close = closes.length ? closes[closes.length - 1] : null;
  const atr14 = latest(atrWilder(bars, 14));
  return {
    close,
    ema20: latest(ema(closes, 20)),
    ema50: latest(ema(closes, 50)),
    rsi14: latest(rsiWilder(closes, 14)),
    atr14,
    atrPct: atr14 != null && close != null && close > 0 ? (atr14 / close) * 100 : null,
    vwap20: latest(vwapRolling(bars, 20)),
    rvol20: rvol(bars, 20),
  };
}
