/**
 * Smart trading desk — Portfolio & risk: the one query no shared hook reads,
 * and small readers over the payloads the tab shares with other screens.
 *
 *   GET /api/portfolio/risk-analytics   value-weighted beta, volatility and 1-day VaR over the
 *                                       holdings with a figure, and the risk drivers
 *                                       (backend/routes/portfolio_risk_analytics.py)
 *
 * Read through shared hooks (see PortfolioTab.tsx):
 *   GET /api/portfolio/holdings-enriched         holdings, weights and totals   (useHoldingsEnriched)
 *   GET /api/portfolio/exposure/concentration    sector look-through            (usePortfolioConcentration)
 *   GET /api/paper-trades/evaluation             calibration buckets            (usePaperEvaluation)
 *
 * Nothing here trusts the response shape: a missing or non-numeric field is
 * null, never 0, and a body without the list the route always sends
 * (`risk_drivers`) throws a contract error, so the tab shows an error state
 * instead of an empty set of checks.
 *
 * Units: money is RUPEES; every percentage returned from here is in percent
 * units (12.4 = 12.4%). The risk route sends volatility as a fraction a year
 * (0.185); it is converted once, here.
 */
import { useQuery } from "@tanstack/react-query";
import { http } from "@/services/api/http";
import { ApiError } from "@/services/api/errors";
import { useImpersonationStore } from "@/stores/impersonation.store";
import type { ConcentrationBreakdownC, EnrichedHoldingsRes } from "@/services/contracts/portfolio.contract";
import type { PaperBucket } from "@/services/adapters/paperTrades.adapter";
import { num } from "./desk-data";

type Raw = Record<string, unknown>;
const rec = (v: unknown): Raw => (v && typeof v === "object" && !Array.isArray(v) ? (v as Raw) : {});
const str = (v: unknown): string | null => (typeof v === "string" && v.trim() ? v.trim() : null);

const isForbidden = (e: unknown) => e instanceof ApiError && (e.kind === "forbidden" || e.status === 403);
const retry = (count: number, e: unknown) => !isForbidden(e) && !(e instanceof ApiError && e.kind === "contract_drift") && count < 1;

// ── risk figures (GET /api/portfolio/risk-analytics) ─────────────────────

export interface RiskDriver {
  /** SMALLCAP_WEIGHT, HIGH_BETA_NAMES, CYCLICAL_SECTORS, DEBT_GOLD_BUFFER, … */
  type: string;
  label: string;
  /** Share of the portfolio's value, percent. */
  pct: number | null;
  /** HIGH | MEDIUM | LOW, as the route judged it; null when it sent none. */
  impact: string | null;
}

export interface RiskAnalytics {
  /** The route found no holdings. */
  empty: boolean;
  /** LOW | MEDIUM | HIGH | VERY_HIGH from the route's volatility bands; null for UNKNOWN or none. */
  rating: string | null;
  /** Value-weighted 1-year beta of the holdings that have one. */
  beta: number | null;
  /** Value-weighted 1-year volatility, percent a year. */
  volatilityPct: number | null;
  /** Parametric 1-day value at risk, rupees and percent of the portfolio. */
  var1dRs: number | null;
  var1dPct: number | null;
  /** Confidence level of the VaR, percent (95). */
  varConfidencePct: number | null;
  /** Share of the portfolio's value with a beta, Sharpe or volatility on record, percent. */
  coveragePct: number | null;
  drivers: RiskDriver[];
}

export async function fetchRiskAnalytics(signal?: AbortSignal): Promise<RiskAnalytics> {
  const res = await http({ path: "/api/portfolio/risk-analytics", signal });
  const d = rec(res.data);
  if (!Array.isArray(d.risk_drivers)) throw ApiError.contractDrift("portfolio.risk-analytics: no risk_drivers list");
  const drivers: RiskDriver[] = d.risk_drivers.flatMap((v): RiskDriver[] => {
    const r = rec(v);
    const type = str(r.type);
    if (!type) return [];
    return [{ type, label: str(r.label) ?? type, pct: num(r.pct), impact: str(r.impact)?.toUpperCase() ?? null }];
  });
  const vol = num(d.weighted_volatility);
  const conf = num(d.var_confidence);
  const rating = str(d.risk_rating)?.toUpperCase() ?? null;
  return {
    empty: d.empty === true,
    rating: rating === "UNKNOWN" ? null : rating,
    beta: num(d.weighted_beta),
    volatilityPct: vol == null ? null : vol * 100,
    var1dRs: num(d.var_1d_rs),
    var1dPct: num(d.var_1d_pct),
    varConfidencePct: conf == null ? null : conf <= 1 ? conf * 100 : conf,
    coveragePct: num(d.coverage_pct),
    drivers,
  };
}

export function useRiskAnalytics(enabled = true) {
  const profile = useImpersonationStore((s) => s.profileId);
  return useQuery<RiskAnalytics>({
    queryKey: ["copilot", "desk", "risk-analytics", profile ?? "self"],
    enabled,
    staleTime: 5 * 60_000,
    retry,
    queryFn: ({ signal }) => fetchRiskAnalytics(signal),
  });
}

// ── positions (GET /api/portfolio/holdings-enriched) ─────────────────────

/** A single stock above this share of the whole portfolio is flagged. */
export const SINGLE_STOCK_LIMIT_PCT = 25;

export interface StockPosition {
  id: string;
  name: string;
  /** Exchange symbol; null when the holding has none on record (its icon is keyed by the name). */
  symbol: string | null;
  valueRs: number | null;
  pnlPct: number | null;
  /** Share of the whole portfolio's value, percent, as the route worked it out. */
  weightPct: number | null;
}

export interface PortfolioView {
  /** Every holding on record, of any type. */
  holdingsCount: number;
  totalValueRs: number | null;
  totalPnlRs: number | null;
  totalPnlPct: number | null;
  /** Direct stocks only (asset type equity / stock), largest first. */
  stocks: StockPosition[];
  /** Sum of the direct stocks' value; null when none has a value. */
  stocksValueRs: number | null;
}

export function readPortfolio(d: EnrichedHoldingsRes): PortfolioView {
  const stocks = d.holdings
    .filter((h) => {
      const t = h.asset_type.trim().toLowerCase();
      return t === "equity" || t === "stock";
    })
    .map((h): StockPosition => ({
      id: h.holding_id,
      name: h.name,
      symbol: str(h.nse_symbol),
      valueRs: num(h.value_rs),
      pnlPct: num(h.pnl_pct),
      weightPct: num(h.weight_pct),
    }))
    .sort((a, b) => (b.valueRs ?? -1) - (a.valueRs ?? -1));
  const valued = stocks.flatMap((s) => (s.valueRs != null ? [s.valueRs] : []));
  const t = d.totals;
  return {
    holdingsCount: d.holdings.length,
    totalValueRs: num(t?.value_rs),
    totalPnlRs: num(t?.pnl_rs),
    totalPnlPct: num(t?.pnl_pct),
    stocks,
    stocksValueRs: valued.length ? valued.reduce((a, b) => a + b, 0) : null,
  };
}

/** The direct stock with the largest weight; null when none has a weight. */
export function largestStock(stocks: StockPosition[]): (StockPosition & { weightPct: number }) | null {
  let best: (StockPosition & { weightPct: number }) | null = null;
  for (const s of stocks) {
    if (s.weightPct != null && (best == null || s.weightPct > best.weightPct)) best = { ...s, weightPct: s.weightPct };
  }
  return best;
}

// ── sector split (GET /api/portfolio/exposure/concentration) ─────────────

export interface SectorSlice {
  name: string;
  /** Share of the portfolio's sector exposure, percent. */
  pct: number;
  /** The slice for the sectors not listed by name. */
  rest?: boolean;
}

/** Sectors the ring names; the remainder is one "Other sectors" slice. */
const RING_SLICES = 5;

/**
 * The ring's slices: the largest sectors by name, then everything else as one
 * slice. The route lists its top sectors only, so "everything else" is
 * 100% − the listed ones, when that is above zero. null when the payload has
 * no sector items.
 */
export function sectorSlices(d: ConcentrationBreakdownC): { slices: SectorSlice[]; sectorCount: number | null } | null {
  const items = (d.sector?.items ?? []).flatMap((it) => {
    const pct = num(it.pct);
    return pct != null && pct > 0 ? [{ name: it.name, pct }] : [];
  });
  if (!items.length) return null;
  items.sort((a, b) => b.pct - a.pct);
  const named = items.slice(0, RING_SLICES);
  const listedTotal = items.reduce((s, it) => s + it.pct, 0);
  const shownTotal = named.reduce((s, it) => s + it.pct, 0);
  // What the route did not list, plus what it listed beyond the named slices.
  const rest = Math.max(0, 100 - listedTotal) + (listedTotal - shownTotal);
  const slices: SectorSlice[] = [...named];
  if (rest >= 0.05) slices.push({ name: "Other sectors", pct: rest, rest: true });
  return { slices, sectorCount: num(d.sector?.all_items_count) };
}

// ── paper-trade calibration (GET /api/paper-trades/evaluation) ───────────

export interface CalibrationRow {
  /** Bucket bounds, percent (10, 20). */
  loPct: number;
  hiPct: number;
  n: number;
  /** The model's average next-session probability in the bucket, percent. */
  predictedPct: number;
  /** How often the move the model was scoring happened, percent. */
  realisedPct: number;
  /** Realised − predicted, percentage points. */
  errorPts: number;
}

/** Buckets with predictions in them and both rates stored; the engine stores fractions. */
export function calibrationRows(buckets: PaperBucket[]): CalibrationRow[] {
  return buckets.flatMap((b): CalibrationRow[] => {
    const predicted = b.predicted_mean;
    const realised = b.model_label_rate;
    if (!(b.n > 0) || predicted == null || realised == null) return [];
    const error = b.calibration_error ?? realised - predicted;
    return [{ loPct: b.lo * 100, hiPct: b.hi * 100, n: b.n, predictedPct: predicted * 100, realisedPct: realised * 100, errorPts: error * 100 }];
  });
}
