/**
 * The magnet drawing modifier (§38.6): "snaps anchors to the nearest O/H/L/C". Pure — no chart/DOM dependency, so
 * it can be unit-tested directly. The chart-coordinate → bar lookup (which bar is "under" the cursor) is a
 * lightweight-charts concern and stays in ChartCanvas.tsx (W1b); this module only decides, given a bar, which of
 * its four prices an anchor should snap to.
 */
import type { Bar } from "../contract";

export type OhlcField = "open" | "high" | "low" | "close";

export interface MagnetResult {
  price: number;
  field: OhlcField;
  /** |snapped price - requested price|, so a caller can decide not to snap past some pixel/price threshold. */
  distance: number;
}

/**
 * The bar whose date is closest to `date` in an ascending, date-sorted series (contract.ts `Bar[]`, as returned by
 * `chartApi.ohlcv`). Ties resolve to the earlier bar. Returns null for an empty series.
 */
export function nearestBar(bars: Bar[], date: string): Bar | null {
  if (bars.length === 0) return null;
  let lo = 0;
  let hi = bars.length - 1;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (bars[mid][0] < date) lo = mid + 1;
    else hi = mid;
  }
  // `lo` is the first bar with date >= target (or the last bar, if target is past the end).
  if (lo === 0) return bars[0];
  const after = bars[lo];
  const before = bars[lo - 1];
  if (after[0] === date) return after;
  const dAfter = Math.abs(daysBetween(date, after[0]));
  const dBefore = Math.abs(daysBetween(date, before[0]));
  return dBefore <= dAfter ? before : after;
}

function daysBetween(a: string, b: string): number {
  return (Date.parse(a) - Date.parse(b)) / 86_400_000;
}

/**
 * Snaps `rawPrice` to the nearest of the O/H/L/C values of the bar nearest `date`. Returns null when there is no
 * bar to snap to (empty series) — the caller keeps the raw, un-snapped anchor in that case.
 */
export function magnetSnap(bars: Bar[], date: string, rawPrice: number): MagnetResult | null {
  const bar = nearestBar(bars, date);
  if (!bar) return null;
  return magnetSnapToBar(bar, rawPrice);
}

/** Same as `magnetSnap`, for a caller that has already resolved the bar (e.g. from a chart hit-test). */
export function magnetSnapToBar(bar: Bar, rawPrice: number): MagnetResult {
  const candidates: Array<[OhlcField, number]> = [
    ["open", bar[1]], ["high", bar[2]], ["low", bar[3]], ["close", bar[4]],
  ];
  let best: MagnetResult = { field: candidates[0][0], price: candidates[0][1], distance: Math.abs(candidates[0][1] - rawPrice) };
  for (const [field, value] of candidates.slice(1)) {
    const distance = Math.abs(value - rawPrice);
    if (distance < best.distance) best = { field, price: value, distance };
  }
  return best;
}
