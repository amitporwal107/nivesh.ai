/**
 * Bar signals on the Chart Analysis chart (the "Signals Chart" design of 3 Nov): one triangle per bar and signal, worked out
 * from the figures the page already has (the live-chart route's bars and RVOL, the futures series of the selected slot).
 * Pure: no I/O. Each rule is said on screen (`BAR_SIGNALS[k].rule`); a bar without the figures a rule needs gets nothing.
 *
 *   long_buildup / short_buildup / short_covering
 *       the desk board's build-up rule on that bar (services/fno_oi_windows.buildup_label): the futures' price change and OI
 *       change together, both within ONE contract (a roll is never read as a change), AND the bar's OI change at least
 *       OI_SIZE_X × the mean size of the OI changes of the OI_LOOKBACK bars before it (at least OI_MIN_HISTORY of them), so
 *       only the bars where positioning moved more than usual are marked
 *   volume_spike   the route's RVOL (volume ÷ the mean of the 20 bars before it) ≥ RVOL_SPIKE
 *   breakout       close above the highest high of the BREAK_LOOKBACK bars before it
 *   breakdown      close below the lowest low of the BREAK_LOOKBACK bars before it
 *
 * Readings of the chart, not instructions: OI shows positioning, not who initiated it.
 */
import type { DailyBar } from "../../../indicators";

export type BarSignalKey = "long_buildup" | "short_covering" | "volume_spike" | "breakout" | "breakdown" | "short_buildup";
export type SignalTone = "mint" | "indigo" | "amber" | "danger";

export const OI_SIZE_X = 2;
export const OI_LOOKBACK = 20;
export const OI_MIN_HISTORY = 10;
export const RVOL_SPIKE = 2;
export const BREAK_LOOKBACK = 20;

export interface BarSignalMeta { key: BarSignalKey; label: string; tone: SignalTone; up: boolean; rule: string }

/** In the design's order: the four marked under the bar (up), then the two marked over it (down). */
export const BAR_SIGNALS: BarSignalMeta[] = [
  { key: "long_buildup", label: "Long build-up", tone: "mint", up: true, rule: `futures price up and OI up on the bar, the OI change at least ${OI_SIZE_X}× its ${OI_LOOKBACK}-bar average size` },
  { key: "short_covering", label: "Short covering", tone: "indigo", up: true, rule: `futures price up and OI down on the bar, the OI change at least ${OI_SIZE_X}× its ${OI_LOOKBACK}-bar average size` },
  { key: "volume_spike", label: "Volume spike", tone: "amber", up: true, rule: `volume at least ${RVOL_SPIKE}× the average of the 20 bars before it` },
  { key: "breakout", label: "Breakout", tone: "mint", up: true, rule: `close above the highest high of the ${BREAK_LOOKBACK} bars before it` },
  { key: "breakdown", label: "Breakdown", tone: "danger", up: false, rule: `close below the lowest low of the ${BREAK_LOOKBACK} bars before it` },
  { key: "short_buildup", label: "Short build-up", tone: "danger", up: false, rule: `futures price down and OI up on the bar, the OI change at least ${OI_SIZE_X}× its ${OI_LOOKBACK}-bar average size` },
];

export const DEFAULT_SIGNALS: Record<BarSignalKey, boolean> = {
  long_buildup: true, short_covering: false, volume_spike: true, breakout: false, breakdown: false, short_buildup: false,
};

export interface BarSignal { i: number; key: BarSignalKey }

const fin = (v: number | null | undefined): v is number => v != null && Number.isFinite(v);

/** The futures on the chart's bars: price change and OI change of ONE contract per bar (null where there is none). */
export interface FutChanges { price: Array<number | null>; oi: Array<number | null> }

export function barSignals(bars: DailyBar[], rvol: Array<number | null>, fut: FutChanges | null): BarSignal[] {
  const out: BarSignal[] = [];
  for (let i = 0; i < bars.length; i += 1) {
    const b = bars[i];
    // build-up, only where the OI moved more than usual
    if (fut) {
      const p = fut.price[i], d = fut.oi[i];
      if (fin(p) && fin(d) && p !== 0 && d !== 0) {
        const hist: number[] = [];
        for (let k = Math.max(0, i - OI_LOOKBACK); k < i; k += 1) { const v = fut.oi[k]; if (fin(v)) hist.push(Math.abs(v)); }
        const mean = hist.length >= OI_MIN_HISTORY ? hist.reduce((a, v) => a + v, 0) / hist.length : null;
        if (mean != null && mean > 0 && Math.abs(d) >= OI_SIZE_X * mean) {
          if (p > 0 && d > 0) out.push({ i, key: "long_buildup" });
          else if (p > 0 && d < 0) out.push({ i, key: "short_covering" });
          else if (p < 0 && d > 0) out.push({ i, key: "short_buildup" });
        }
      }
    }
    const rv = rvol[i];
    if (fin(rv) && rv >= RVOL_SPIKE) out.push({ i, key: "volume_spike" });
    if (i >= BREAK_LOOKBACK) {
      let hh = -Infinity, ll = Infinity;
      for (let k = i - BREAK_LOOKBACK; k < i; k += 1) { hh = Math.max(hh, bars[k].high); ll = Math.min(ll, bars[k].low); }
      if (b.close > hh) out.push({ i, key: "breakout" });
      if (b.close < ll) out.push({ i, key: "breakdown" });
    }
  }
  return out;
}
