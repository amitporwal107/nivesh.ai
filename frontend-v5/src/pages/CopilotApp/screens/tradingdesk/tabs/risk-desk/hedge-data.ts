/**
 * Risk Desk › Portfolio hedge: the data layer (Quick Hedge). One call, POST /api/portfolio/quick-hedge (backend/routes/
 * portfolio_hedge.py, services/quick_hedge), made when the person asks. The request carries only what they chose; the holdings,
 * beta, fit to Nifty and Nifty's price, lot and puts are read on the server. Every figure shown comes from that answer: nothing
 * is computed here except the way it is laid out. Reads only; nothing is stored and no order is placed.
 *
 * Fail-closed behind the `portfolio_hedge` feature flag: a 403 is read as "not enabled for this account", never as an outage.
 */
import { useMutation } from "@tanstack/react-query";
import { http } from "@/services/api/http";
import { ApiError } from "@/services/api/errors";
import { num } from "../../desk-data";

type Raw = Record<string, unknown>;
const rec = (v: unknown): Raw => (v && typeof v === "object" && !Array.isArray(v) ? (v as Raw) : {});
const str = (v: unknown): string | null => (typeof v === "string" && v.trim() ? v.trim() : null);
const list = (v: unknown): Raw[] => (Array.isArray(v) ? v.map(rec) : []);

export type HedgeTenor = "1w" | "2w" | "1m" | "3m";
export const HEDGE_TENORS: readonly { key: HedgeTenor; label: string }[] = [
  { key: "1w", label: "1 week" }, { key: "2w", label: "2 weeks" }, { key: "1m", label: "1 month" }, { key: "3m", label: "3 months" },
];
export const HEDGE_FALLS: readonly number[] = [5, 10, 15, 20];
export const HEDGE_MODES = ["balanced", "maximum", "lowest_cost"] as const;
export type HedgeModeKey = (typeof HEDGE_MODES)[number];
export const HEDGE_MODE_LABEL: Record<HedgeModeKey, string> = { balanced: "Balanced", maximum: "Maximum protection", lowest_cost: "Lowest cost" };
export const HEDGE_MODE_BLURB: Record<HedgeModeKey, string> = {
  balanced: "Protection starts where your tolerable loss ends.",
  maximum: "Protection starts earlier, at half your tolerable loss. Costs more.",
  lowest_cost: "A put spread: cheaper, but protection stops at the fall you fear.",
};

export interface HedgeRequest {
  expectedFallPct: number;
  tenor: HedgeTenor;
  /** The loss accepted before protection starts: a percent of the equity-linked holdings, or rupees. */
  tolerance: { kind: "pct" | "rs"; value: number };
}

export interface HedgeReason { code: string; message: string }
export interface HedgeRow { movePct: number; niftyLevel: number | null; withoutRs: number | null; hedgePnlRs: number | null; withRs: number | null; isExpectedFall: boolean }
export interface HedgeLeg { side: "buy" | "sell"; strike: number | null; premium: number | null; qty: number | null }
export interface HedgeMode {
  mode: HedgeModeKey; available: boolean; placeAllowed: boolean; reason: HedgeReason | null; structure: "long_put" | "put_spread" | null;
  legs: HedgeLeg[]; deductibleRs: number | null; deductiblePct: number | null; protectionAtFearRs: number | null; maxProtectionRs: number | null;
  breakEven: number | null; premiumRs: number | null; chargesRs: number | null; totalCostRs: number | null; costPct: number | null;
  rows: HedgeRow[]; notes: HedgeReason[];
}
export interface HedgeResult {
  status: "ok" | "not_hedgeable" | "no_hedge_needed" | "incomplete";
  reasons: HedgeReason[];
  exposure: { exposureRs: number | null; lotNotionalRs: number | null; requiredLots: number | null; executedLots: number | null; protectedPct: number | null; residualPct: number | null; spot: number | null; lot: number | null } | null;
  confidence: { level: "high" | "medium" | "poor" | "unknown"; r2: number | null; message: string | null };
  modes: HedgeMode[];
  disclosures: string[];
  expiry: string | null;
  portfolio: { valueRs: number | null; hedgeableRs: number | null; beta: number | null; betaCoverage: number | null; excludedRs: number; asOf: string | null };
  market: { asOf: string | null; expiry: string | null; putsTraded: number | null };
  fit: { r2: number | null; windowEnd: string | null; observations: number | null; seriesUsed: number | null };
}

const reasons = (v: unknown): HedgeReason[] => list(v).flatMap((r) => (str(r.message) ? [{ code: str(r.code) ?? "", message: str(r.message) as string }] : []));

function readMode(r: Raw): HedgeMode | null {
  const mode = str(r.mode) as HedgeModeKey | null;
  if (!mode || !HEDGE_MODES.includes(mode)) return null;
  const cost = rec(r.cost);
  const structure = str(r.structure);
  return {
    mode, available: r.available === true, placeAllowed: r.place_allowed === true,
    reason: reasons([r.reason])[0] ?? null,
    structure: structure === "long_put" || structure === "put_spread" ? structure : null,
    legs: list(r.legs).map((l) => ({ side: l.side === "sell" ? "sell" : "buy", strike: num(l.strike), premium: num(l.premium), qty: num(l.qty) })),
    deductibleRs: num(r.deductible_rs), deductiblePct: num(r.deductible_pct), protectionAtFearRs: num(r.protection_at_expected_fall_rs),
    maxProtectionRs: num(r.max_protection_rs), breakEven: num(r.break_even_level),
    premiumRs: num(cost.premium_rs), chargesRs: num(cost.charges_rs), totalCostRs: num(cost.total_rs), costPct: num(cost.pct_of_portfolio),
    rows: list(r.scenario_rows).map((x) => ({
      movePct: num(x.move_pct) ?? 0, niftyLevel: num(x.nifty_level), withoutRs: num(x.without_hedge_rs), hedgePnlRs: num(x.hedge_pnl_rs),
      withRs: num(x.with_hedge_rs), isExpectedFall: x.is_expected_fall === true,
    })),
    notes: reasons(r.notes),
  };
}

export function readQuickHedge(body: unknown): HedgeResult {
  const d = rec(body);
  const data = rec(d.data);
  const pf = rec(data.portfolio);
  const mk = rec(data.market);
  const fit = rec(data.fit);
  const ex = rec(d.exposure);
  const cf = rec(d.confidence);
  const status = str(d.status);
  const level = str(cf.level);
  return {
    status: status === "ok" || status === "not_hedgeable" || status === "no_hedge_needed" ? status : "incomplete",
    reasons: reasons(d.reasons),
    exposure: d.exposure ? {
      exposureRs: num(ex.beta_adjusted_exposure_rs), lotNotionalRs: num(ex.lot_notional_rs), requiredLots: num(ex.required_lots), executedLots: num(ex.executed_lots),
      protectedPct: num(ex.protected_pct), residualPct: num(ex.residual_pct), spot: num(ex.spot), lot: num(ex.lot),
    } : null,
    confidence: { level: level === "high" || level === "medium" || level === "poor" ? level : "unknown", r2: num(cf.r2), message: str(cf.message) },
    modes: list(d.modes).flatMap((m) => { const x = readMode(m); return x ? [x] : []; }),
    disclosures: (Array.isArray(d.disclosures) ? d.disclosures : []).flatMap((x) => (str(x) ? [str(x) as string] : [])),
    expiry: str(d.expiry),
    portfolio: {
      valueRs: num(pf.portfolio_value_rs), hedgeableRs: num(pf.hedgeable_value_rs), beta: num(pf.beta), betaCoverage: num(pf.beta_coverage),
      excludedRs: Object.values(rec(pf.excluded_rs)).reduce<number>((a, v) => a + (num(v) ?? 0), 0), asOf: str(pf.as_of),
    },
    market: { asOf: str(mk.as_of), expiry: str(mk.expiry), putsTraded: num(mk.puts_traded) },
    fit: { r2: num(fit.r2), windowEnd: str(fit.window_end), observations: num(fit.observations), seriesUsed: num(fit.series_used) },
  };
}

export function toBody(r: HedgeRequest): Record<string, unknown> {
  return {
    expected_fall_pct: r.expectedFallPct, tenor: r.tenor,
    ...(r.tolerance.kind === "pct" ? { tolerance_pct: r.tolerance.value } : { tolerance_rs: r.tolerance.value }),
  };
}

/** The sentence a failed call is shown as. A 403 is the flag being off for this account; a 422 is an input the route refused. */
export function hedgeProblem(e: unknown): string {
  if (e instanceof ApiError && (e.kind === "forbidden" || e.status === 403)) return "Portfolio hedge is not enabled for your account.";
  if (e instanceof ApiError && e.status === 422) return "That input was not accepted: check the loss you can accept and the fall you are worried about.";
  return "The hedge choices could not be calculated just now. Nothing was assumed in their place.";
}

export function useQuickHedge() {
  return useMutation({
    mutationFn: async (req: HedgeRequest): Promise<HedgeResult> =>
      readQuickHedge((await http({ method: "POST", path: "/api/portfolio/quick-hedge", body: toBody(req), noRetry: true })).data),
  });
}
