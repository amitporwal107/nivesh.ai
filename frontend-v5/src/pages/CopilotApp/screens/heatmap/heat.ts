/**
 * Sector heatmap — colour scale, ranking and the verdict sentence. Pure functions over the parsed route
 * (heatmap-data.ts); nothing here fetches or renders.
 */
import type { HeatSector, HeatStock, PeriodKey } from "./heatmap-data";

export const PERIODS = ["d", "w", "m"] as const;
export const PERIOD_LABEL: Record<PeriodKey, string> = { d: "1D", w: "1W", m: "1M" };
/** A return this size (percent) fills the tile with the full colour. */
export const CLAMP: Record<PeriodKey, number> = { d: 3, w: 6, m: 10 };
/** Under this size (percent, either way) a move is shown as flat. */
export const FLAT_BELOW = 0.05;
const PERIOD_PHRASE: Record<PeriodKey, string> = { d: "on the day", w: "over the week", m: "over the month" };
export const periodPhrase = (p: PeriodKey) => PERIOD_PHRASE[p];

export type Tone = "up" | "down" | "flat" | "none";

export function toneOf(v: number | null | undefined): Tone {
  if (v == null || !Number.isFinite(v)) return "none";
  if (Math.abs(v) < FLAT_BELOW) return "flat";
  return v > 0 ? "up" : "down";
}

export interface Tint { tone: Tone; bg: string; fg: string; shadow: string; strength: number }

/** Tile fill: mint or danger mixed over the card background, stronger with the move; neutral when flat or unknown. */
export function tintOf(v: number | null | undefined, period: PeriodKey): Tint {
  const tone = toneOf(v);
  if (tone === "none") return { tone, bg: "var(--bg-2)", fg: "var(--cp-ink-3)", shadow: "none", strength: 0 };
  if (tone === "flat") return { tone, bg: "var(--bg-3)", fg: "var(--cp-ink)", shadow: "none", strength: 0 };
  const t = Math.min(1, Math.abs(v as number) / CLAMP[period]);
  const pct = Math.round(18 + 44 * t);
  const base = tone === "up" ? "var(--mint)" : "var(--cp-danger)";
  return { tone, bg: `color-mix(in srgb, ${base} ${pct}%, var(--bg-1))`, fg: "#fff", shadow: "0 1px 2px rgba(0,0,0,0.55)", strength: pct };
}

/** The seven legend steps, from the full down colour to the full up colour. */
export function legendSteps(period: PeriodKey): number[] {
  const c = CLAMP[period];
  return [-1, -2 / 3, -1 / 3, 0, 1 / 3, 2 / 3, 1].map((f) => f * c);
}

export function signed(v: number | null | undefined, digits = 2): string {
  if (v == null || !Number.isFinite(v)) return "—";
  const s = Math.abs(v).toFixed(digits);
  return v < 0 ? `−${s}%` : v > 0 ? `+${s}%` : `${s}%`;
}

export interface Counts { advances: number; flat: number; declines: number; priced: number }

/** Advancers / flat / decliners among the stocks that have a return for the period. */
export function countsFor(stocks: HeatStock[], period: PeriodKey): Counts {
  let advances = 0; let flat = 0; let declines = 0;
  for (const s of stocks) {
    const t = toneOf(s.returns[period]);
    if (t === "up") advances += 1; else if (t === "down") declines += 1; else if (t === "flat") flat += 1;
  }
  return { advances, flat, declines, priced: advances + flat + declines };
}

/** A sector's pull on the index over a period, in index percentage points. The route's figure, else weight × return. */
export function contributionOf(s: HeatSector, period: PeriodKey): number | null {
  const c = s.contribution[period];
  if (c != null) return c;
  const r = s.returns[period];
  return r != null && s.weightPct != null ? (s.weightPct * r) / 100 : null;
}

export interface VerdictPart { text: string; tone?: "up" | "down" }

function joinNames(names: string[], tone: "up" | "down"): VerdictPart[] {
  const out: VerdictPart[] = [];
  names.forEach((n, i) => {
    if (i > 0) out.push({ text: i === names.length - 1 ? " and " : ", " });
    out.push({ text: n, tone });
  });
  return out;
}

/** The headline, in parts so sector names can be coloured. Null when no sector has a figure for the period. */
export function verdictFor(sectors: HeatSector[], stocks: HeatStock[], period: PeriodKey): VerdictPart[] | null {
  const rows = sectors.flatMap((s) => { const c = contributionOf(s, period); return c == null ? [] : [{ name: s.name, c }]; });
  if (!rows.length) return null;
  const pos = rows.filter((r) => r.c > 0).sort((a, b) => b.c - a.c);
  const neg = rows.filter((r) => r.c < 0).sort((a, b) => a.c - b.c);
  const parts: VerdictPart[] = [];
  if (pos.length && neg.length) {
    parts.push(...joinNames(pos.slice(0, 2).map((r) => r.name), "up"), { text: " led while " }, ...joinNames([neg[0].name], "down"), { text: " dragged the index." });
  } else if (pos.length) {
    parts.push(...joinNames(pos.slice(0, 2).map((r) => r.name), "up"), { text: " led a broad advance; no sector pulled the index down." });
  } else if (neg.length) {
    parts.push(...joinNames([neg[0].name], "down"), { text: neg.length > 1 ? ` dragged most as every sector fell; ` : " dragged the index as every sector fell." });
    if (neg.length > 1) parts.push(...joinNames([neg[neg.length - 1].name], "up"), { text: " held up best." });
  } else {
    parts.push({ text: "No sector moved the index." });
  }
  const c = countsFor(stocks, period);
  if (c.priced > 0) {
    const rose = c.advances > c.declines;
    parts.push({ text: ` ${rose ? c.advances : c.declines} of ${c.priced} stocks ${rose ? "rose" : "fell"} ${periodPhrase(period)}.` });
  }
  return parts;
}

/** Sectors ranked best first by a period; those without a return go last. */
export function rankSectors(sectors: HeatSector[], period: PeriodKey): HeatSector[] {
  return [...sectors].sort((a, b) => {
    const x = a.returns[period]; const y = b.returns[period];
    if (x == null || y == null) return x == null && y == null ? a.name.localeCompare(b.name) : x == null ? 1 : -1;
    return y - x;
  });
}

export type SizeBy = "weight" | "volume" | "equal";

export function sizeOf(s: HeatStock, by: SizeBy): number {
  if (by === "equal") return 1;
  if (by === "volume") return s.tradedValueCr != null && s.tradedValueCr > 0 ? s.tradedValueCr : 0;
  return s.weightPct != null && s.weightPct > 0 ? s.weightPct : 0;
}

/** The stock with the largest move (either way) for the period, among those given. */
export function biggestMover(stocks: HeatStock[], period: PeriodKey): HeatStock | null {
  let best: HeatStock | null = null;
  for (const s of stocks) {
    const v = s.returns[period];
    if (v == null) continue;
    if (!best || Math.abs(v) > Math.abs(best.returns[period] as number)) best = s;
  }
  return best;
}

/** Whole days between an ISO date and now; null when the date does not parse. */
export function daysOld(asOf: string | null, now = Date.now()): number | null {
  if (!asOf) return null;
  const t = Date.parse(/^\d{4}-\d{2}-\d{2}$/.test(asOf) ? `${asOf}T00:00:00Z` : asOf);
  return Number.isFinite(t) ? Math.floor((now - t) / 86_400_000) : null;
}
export const STALE_AFTER_DAYS = 4;
