/**
 * Research → Paper: the arithmetic behind the page's what-ifs. Pure functions, no I/O.
 *
 * The engine's stored record (equal ₹20,000 legs, pre-registered ATR levels, 0.25% round trip) is shown as stored. These
 * functions only answer "what if I sized it differently / used another stop", from the same stored daily path:
 *   · levels() is the engine's formula (nidp.services.tpd_model.paper.sim.levels): stop = entry − k·ATR14, or the
 *     10-session support when lower, never more than 8% below entry; target = entry × (1 + target%).
 *   · modeResult() follows the engine's exit rules on returns measured from entry: EOD-n = close of session n; FIXED =
 *     close of session 6; TARGET_STOP = first barrier from the entry session on, a session touching both counts the stop,
 *     and from the second session an open beyond a level exits at that open.
 *   · sizeBasket() is the design's sizing: equal, inverse-ATR ("risk weighted") or capped weights, then every leg held
 *     to the notional that loses exactly its share of the loss limit at its own stop.
 */
import type { PaperMode } from "@/services/adapters/paperTrades.adapter";

export const MODE_SESSION: Record<PaperMode, number> = { "EOD-1": 1, "EOD-3": 3, "EOD-5": 5, FIXED: 6, TARGET_STOP: 6 };
export const STOP_CAP = 0.08;

export interface Levels { stop: number; target: number; method: "ATR" | "SUPPORT" | "CAP_8PCT"; riskPct: number }

export function levels(entry: number | null, atr: number | null, support: number | null, k: number, targetPct: number, cap = STOP_CAP): Levels | null {
  if (entry == null || atr == null || !(entry > 0)) return null;
  const stopAtr = entry - k * atr;
  const useSup = support != null && support < entry && support < stopAtr;
  let stop = useSup ? (support as number) : stopAtr;
  let method: Levels["method"] = useSup ? "SUPPORT" : "ATR";
  const floor = entry * (1 - cap);
  if (stop < floor) { stop = floor; method = "CAP_8PCT"; }
  return { stop, target: entry * (1 + targetPct / 100), method, riskPct: (entry - stop) / entry };
}

export interface Path { open: (number | null)[]; high: (number | null)[]; low: (number | null)[]; close: (number | null)[]; observed: number }

export interface ModeResult { state: "CLOSED" | "OPEN" | "NO_BAR"; gross: number | null; net: number | null; mark: number | null; exitIndex: number | null; reason: string | null }

/** Returns are from entry (0.05 = +5%). `stopRet` is negative (−0.08), `targetRet` positive. */
export function modeResult(p: Path, mode: PaperMode, stopRet: number, targetRet: number, costPct: number): ModeResult {
  const cost = costPct / 100;
  const last = p.observed > 0 ? p.close[p.observed - 1] ?? null : null;
  const mark = last == null ? null : last - cost;
  if (mode !== "TARGET_STOP") {
    const s = MODE_SESSION[mode];
    if (p.observed < s) return { state: "OPEN", gross: null, net: null, mark, exitIndex: null, reason: null };
    const g = p.close[s - 1];
    return g == null ? { state: "NO_BAR", gross: null, net: null, mark, exitIndex: s, reason: "no bar at exit" }
                     : { state: "CLOSED", gross: g, net: g - cost, mark, exitIndex: s, reason: `close of session ${s}` };
  }
  for (let t = 0; t < Math.min(p.observed, 6); t++) {
    const o = p.open[t], h = p.high[t], l = p.low[t];
    if (h == null || l == null) continue;
    if (t >= 1 && o != null) {
      if (o <= stopRet) return { state: "CLOSED", gross: o, net: o - cost, mark, exitIndex: t + 1, reason: "stop (gap)" };
      if (o >= targetRet) return { state: "CLOSED", gross: o, net: o - cost, mark, exitIndex: t + 1, reason: "target (gap)" };
    }
    if (l <= stopRet) return { state: "CLOSED", gross: stopRet, net: stopRet - cost, mark, exitIndex: t + 1, reason: "stop" };
    if (h >= targetRet) return { state: "CLOSED", gross: targetRet, net: targetRet - cost, mark, exitIndex: t + 1, reason: "target" };
  }
  if (p.observed >= 6) {
    const g = p.close[5];
    return g == null ? { state: "NO_BAR", gross: null, net: null, mark, exitIndex: 6, reason: "no bar at exit" }
                     : { state: "CLOSED", gross: g, net: g - cost, mark, exitIndex: 6, reason: "horizon close" };
  }
  return { state: "OPEN", gross: null, net: null, mark, exitIndex: null, reason: null };
}

export type Sizing = "equal" | "risk" | "capped";
export interface SizeLeg { symbol: string; atrPct: number | null; stopDist: number | null }
export interface Sized { w: Record<string, number>; legBudget: number; legCap: Record<string, number>; binding: boolean; totalRisk: number }

/** Weights as a share of capital. `capPct` limits any one leg under "capped"; `dayLimitPct` is the most the person accepts
 *  losing across the basket if every stop fills. A leg without a stop distance keeps its allocation-rule weight. */
export function sizeBasket(legs: SizeLeg[], sizing: Sizing, capPct: number, dayLimitPct: number): Sized {
  const n = legs.length;
  const w: Record<string, number> = {};
  const legCap: Record<string, number> = {};
  if (!n) return { w, legBudget: 0, legCap, binding: false, totalRisk: 0 };
  if (sizing === "risk") {
    const inv = legs.map((l) => (l.atrPct && l.atrPct > 0 ? 1 / l.atrPct : null));
    const known = inv.filter((x): x is number => x != null);
    const fill = known.length ? known.reduce((a, b) => a + b, 0) / known.length : 1;
    const vals = inv.map((x) => x ?? fill);
    const tot = vals.reduce((a, b) => a + b, 0);
    legs.forEach((l, i) => { w[l.symbol] = vals[i] / tot; });
  } else {
    legs.forEach((l) => { w[l.symbol] = 1 / n; });
  }
  if (sizing === "capped") legs.forEach((l) => { w[l.symbol] = Math.min(w[l.symbol], capPct / 100); });
  const legBudget = dayLimitPct / 100 / n;
  let binding = false;
  legs.forEach((l) => {
    if (l.stopDist == null || !(l.stopDist > 0)) return;
    legCap[l.symbol] = legBudget / l.stopDist;
    if (legCap[l.symbol] < w[l.symbol] - 1e-9) { w[l.symbol] = legCap[l.symbol]; binding = true; }
  });
  const totalRisk = legs.reduce((a, l) => a + (l.stopDist && l.stopDist > 0 ? w[l.symbol] * l.stopDist : 0), 0);
  return { w, legBudget, legCap, binding, totalRisk };
}

// ── formatting ──────────────────────────────────────────────────────────────────────────────────────────────────
export function pct(x: number | null | undefined, d = 2, signed = true): string {
  if (x == null || !isFinite(x)) return "—";
  const v = x * 100;
  const t = Math.abs(v).toFixed(d);
  if (!signed) return `${t}%`;
  return v > 0 && Number(t) !== 0 ? `+${t}%` : v < 0 && Number(t) !== 0 ? `−${t}%` : `${Number(0).toFixed(d)}%`;
}
export function prob(x: number | null | undefined): string {
  if (x == null || !isFinite(x)) return "—";
  const v = x * 100;
  return v < 0.1 ? "<0.1%" : `${v.toFixed(1)}%`;
}
export function inr(x: number | null | undefined, signed = false): string {
  if (x == null || !isFinite(x)) return "—";
  const r = Math.round(x);
  const body = "₹" + Math.abs(r).toLocaleString("en-IN");
  if (!signed) return r < 0 ? `−${body}` : body;
  return r > 0 ? `+${body}` : r < 0 ? `−${body}` : body;
}
export function price(x: number | null | undefined): string {
  return x == null || !isFinite(x) ? "—" : `₹${x.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}
const IST: Intl.DateTimeFormatOptions = { timeZone: "Asia/Kolkata" };
export function day(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso.length === 10 ? `${iso}T12:00:00+05:30` : iso);
  return d.toLocaleDateString("en-GB", { ...IST, weekday: "short", day: "numeric", month: "short" });
}
export function dayYear(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso.length === 10 ? `${iso}T12:00:00+05:30` : iso);
  return d.toLocaleDateString("en-GB", { ...IST, day: "numeric", month: "short", year: "numeric" });
}
export function clock(iso: string | null | undefined): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleTimeString("en-GB", { ...IST, hour: "2-digit", minute: "2-digit", hour12: false }) + " IST";
}
