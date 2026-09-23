/**
 * Bottom-bar range presets (§38.7, §38.13 AC 8): "1M, 3M, 6M, YTD, 1Y, 5Y and All. 1D and 5D are added once
 * intraday exists; until then they are disabled, with a tooltip giving the reason." Pure date-window logic over
 * an ascending daily bar series — no chart/DOM dependency.
 */
import type { Bar } from "../contract";

export type RangePreset = "1D" | "5D" | "1M" | "3M" | "6M" | "YTD" | "1Y" | "5Y" | "ALL";

export interface RangeDef {
  id: RangePreset;
  label: string;
  enabled: boolean;
  /** Present exactly when `enabled` is false — shown as the disabled control's tooltip/reason text. */
  disabledReason?: string;
}

const INTRADAY_REASON = "needs intraday data";

/** In display order, left to right (§38.7: "1D 5D 1M 3M 6M YTD 1Y 5Y All" minus the 1D/5D the reference adds
 *  once intraday exists — kept here, disabled, so the row layout does not shift when D-2 lands). */
export const RANGE_PRESETS: RangeDef[] = [
  { id: "1D", label: "1D", enabled: false, disabledReason: INTRADAY_REASON },
  { id: "5D", label: "5D", enabled: false, disabledReason: INTRADAY_REASON },
  { id: "1M", label: "1M", enabled: true },
  { id: "3M", label: "3M", enabled: true },
  { id: "6M", label: "6M", enabled: true },
  { id: "YTD", label: "YTD", enabled: true },
  { id: "1Y", label: "1Y", enabled: true },
  { id: "5Y", label: "5Y", enabled: true },
  { id: "ALL", label: "All", enabled: true },
];

const MONTHS_BACK: Partial<Record<RangePreset, number>> = { "1M": 1, "3M": 3, "6M": 6, "1Y": 12, "5Y": 60 };

export interface VisibleRange { from: string; to: string }

/**
 * Resolves a preset to a `[from, to]` date window over `bars` (ascending, contract.ts `Bar[]`). `to` is always the
 * series' last bar — the snapshot has no live "now" clock (§38.14 D-4 tracks live refresh separately). `from` is
 * clamped to the series' first bar, so a preset wider than the history never asks for dates the series doesn't
 * have. Returns null for a disabled preset or an empty series — the caller keeps whatever range was showing.
 */
export function resolveRange(preset: RangePreset, bars: Bar[]): VisibleRange | null {
  if (bars.length === 0) return null;
  const def = RANGE_PRESETS.find((r) => r.id === preset);
  if (!def || !def.enabled) return null;

  const to = bars[bars.length - 1][0];
  if (preset === "ALL") return { from: bars[0][0], to };

  const toDate = new Date(`${to}T00:00:00Z`);
  const fromDate = preset === "YTD"
    ? new Date(Date.UTC(toDate.getUTCFullYear(), 0, 1))
    : monthsBefore(toDate, MONTHS_BACK[preset]!);

  const fromIso = fromDate.toISOString().slice(0, 10);
  // Land on a real bar at/after the computed date (never a non-trading-day gap), clamped to the first bar.
  const clamped = bars.find((b) => b[0] >= fromIso)?.[0] ?? bars[0][0];
  return { from: clamped, to };
}

function monthsBefore(d: Date, months: number): Date {
  const out = new Date(d.getTime());
  out.setUTCMonth(out.getUTCMonth() - months);
  return out;
}
