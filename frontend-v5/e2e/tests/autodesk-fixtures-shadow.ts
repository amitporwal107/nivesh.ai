/**
 * Fixtures for the shadow-score spec (autodesk-shadow.spec.ts).
 *
 * // MOCK — not real data. Shapes copy contracts.ShadowScore as the AI Trader stores it in a signal body
 * // (`shadow_scores`: v2-positional and v21-positional); the numbers are made up for the tests.
 */
import type { Handler, Req, RouteValue } from "./autodesk-mock";
import { SIG, SIGNALS, scannerRoutes } from "./autodesk-fixtures-scanner";
import { traceRoutes } from "./autodesk-fixtures-studio-trace";

const comp = (dimension: string, weight: number, points: number, detail: string) => ({ dimension, weight: String(weight), points: String(points), available: true, detail });

export const V2 = {
  version: "v2-positional", horizon: "POSITIONAL", status: "SHADOW", score: "67.50", band: "Developing", tier: "TIER_2",
  primary_signal: "SETUP_A_ACCUMULATION", signals: ["SETUP_A_ACCUMULATION", "VOLUME_BREAKOUT"], context_signals: [], warnings: ["MACD_BEAR_CROSS"],
  components: [
    comp("signal_quality", 45, 24, "setup a accumulation (tier 2, 24)"), comp("trend_confirmation", 30, 26, "above a rising EMA50 (12); price > EMA20 > EMA50 (8)"),
    comp("relative_strength", 15, 11, "20-session return +6.1 % vs the Nifty"), comp("supporting_evidence", 10, 6.5, "RSI14 66.0 (3); delivery 58 % (3)"),
    comp("bearish_warning", 10, -10, "bearish warning present: macd bear cross"),
  ], reasons: [], bars_used: 500,
};
export const V21 = {
  ...V2, version: "v21-positional", score: "77.50", band: "Strong", tier: "TIER_2", primary_signal: "VOLUME_BREAKOUT",
  signals: ["VOLUME_BREAKOUT"], context_signals: ["SETUP_A_ACCUMULATION"],
  components: V2.components.filter((c) => c.dimension !== "bearish_warning"),
};
export const NOT_SCORED = { ...V2, version: "v21-positional", score: null, band: null, tier: null, primary_signal: null, signals: [], warnings: [], components: [], reasons: ["20-session average traded value below ₹5 crore"] };

/** PETRONET carries both shadow scores, GRASIM carries a version that could not score, the rest carry none (older rows, index). */
export const SHADOW_BY_ID: Record<string, unknown[]> = { [SIG.PETRONET]: [V2, V21], [SIG.GRASIM]: [{ ...V2, score: "71.00", band: "Developing" }, NOT_SCORED] };

type Row = { signal_id: string; body: Record<string, unknown> } & Record<string, unknown>;
export const withShadow = (r: Row, by: Record<string, unknown[]> = SHADOW_BY_ID): Row => (by[r.signal_id] ? { ...r, body: { ...r.body, shadow_scores: by[r.signal_id] } } : r);

export function shadowScannerRoutes(by: Record<string, unknown[]> = SHADOW_BY_ID): Record<string, RouteValue> {
  const base = scannerRoutes()["GET /signals"] as Handler;
  return scannerRoutes({ "GET /signals": ((r: Req, st) => ((base(r, st) as Row[]) ?? []).map((x) => withShadow(x, by))) as Handler });
}

/** Trace: the ADANIPORTS chain's signal carries a v2 shadow score (every other signal none). */
export function shadowTraceRoutes(sigIdOfAda: string): Record<string, RouteValue> {
  const base = traceRoutes()["GET /signals/:id"] as Handler;
  return traceRoutes({ "GET /signals/:id": ((r: Req, st) => { const x = base(r, st) as Row; return x && x.signal_id === sigIdOfAda ? withShadow(x, { [sigIdOfAda]: [V2, V21] }) : x; }) as Handler });
}
export { SIGNALS };
