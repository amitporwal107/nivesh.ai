/**
 * Smart trading desk — Portfolio & risk: the queries no shared hook reads, and
 * small readers over the payloads the tab shares with other screens.
 *
 *   GET /api/portfolio/risk-analytics            value-weighted beta, volatility and 1-day VaR over the
 *                                                holdings with a figure, and the risk drivers
 *                                                (backend/routes/portfolio_risk_analytics.py)
 *   GET /api/portfolio/correlation?sessions=120&limit=10
 *                                                the most correlated pairs of the user's equity holdings: Pearson
 *                                                correlation of daily log returns of adjusted closes (DaaS prices),
 *                                                with the method, sessions and the holdings it could not use
 *   GET /api/portfolio/market-cap-split          equity value by NSE index membership (Large = Nifty 100, Mid =
 *                                                Nifty Midcap 150, Small = Nifty Smallcap 250, Micro = rest of
 *                                                Nifty Total Market, Unclassified = none); `available: false` (top
 *                                                level and per bucket, with a `reason`) while the mid / small lists
 *                                                are not on record, and then `unsplit` = everything outside Nifty 100
 *                                                (large + unsplit = the equity total); `indices` names each list's
 *                                                date and member count
 *
 *   GET /api/portfolio/holding-risk?sessions=250 per stock held: average traded value and days to sell at 10% of the
 *                                                average volume, overnight gaps; today's stocks held together: drawdown
 *                                                and 1-month volatility; each level's rule; missing and stale prices
 *                                                (backend/routes/portfolio_desk.py, B15)
 *   GET /api/portfolio/composition/scope         the accounts and sources behind the totals, instrument types, asset
 *                                                allocation, freshness, and instruments held in two places
 *                                                (backend/routes/portfolio_composition.py)
 *   GET /api/portfolio/capital-gains-statement   realised gains this financial year, FIFO over the statement's
 *                                                transactions (backend/routes/portfolio_tax.py)
 *   POST /api/portfolio/upload/preview           import step 1: validated rows and flags, nothing saved
 *   POST /api/portfolio/upload/preview/{id}/commit   import step 2: save the rows the user confirmed
 *                                                (backend/routes/upload.py, B17)
 *
 * Read through shared hooks (see PortfolioTab.tsx):
 *   GET /api/portfolio/holdings-enriched         holdings, weights and totals   (useHoldingsEnriched)
 *   GET /api/portfolio/exposure/concentration    sector look-through            (usePortfolioConcentration)
 *   GET /api/paper-trades/evaluation             calibration buckets, modes     (usePaperEvaluation)
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
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "@/services/api/authed-fetch";
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
  /** The route's 0–10 risk score (annual volatility ÷ 4%, capped at 10); null when it sent none. */
  score: number | null;
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
  /** The stocks' own 1-year drawdowns, value-weighted, percent (≤ 0); not the portfolio's own drawdown. */
  holdingsDrawdownPct: number | null;
  /** Share of the portfolio's value with a drawdown on record, percent. */
  drawdownCoveragePct: number | null;
  worstDrawdown: { name: string; pct: number } | null;
  drawdownAsOf: string | null;
  drawdownMethod: string | null;
  drawdownSource: string | null;
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
    score: num(d.risk_score),
    beta: num(d.weighted_beta),
    volatilityPct: vol == null ? null : vol * 100,
    var1dRs: num(d.var_1d_rs),
    var1dPct: num(d.var_1d_pct),
    varConfidencePct: conf == null ? null : conf <= 1 ? conf * 100 : conf,
    coveragePct: num(d.coverage_pct),
    drivers,
    holdingsDrawdownPct: num(d.holdings_drawdown_1y_pct),
    drawdownCoveragePct: num(d.drawdown_coverage_pct),
    worstDrawdown: (() => {
      const w = rec(d.worst_drawdown_holding);
      const pct = num(w.max_drawdown_1y_pct);
      const name = str(w.ticker) ?? str(w.name);
      return name && pct != null ? { name: name.toUpperCase(), pct } : null;
    })(),
    drawdownAsOf: str(d.drawdown_as_of),
    drawdownMethod: str(d.drawdown_method),
    drawdownSource: str(d.drawdown_source),
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
  /** What was paid for the holdings with a cost on record (the route leaves out rows without one). */
  totalInvestedRs: number | null;
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
    totalInvestedRs: num(t?.invested_rs),
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

// ── correlated positions (GET /api/portfolio/correlation) ────────────────

/** Sessions of daily returns the correlation is worked out over (the route takes 60–250). */
export const CORR_SESSIONS = 120;
const CORR_LIMIT = 10;

export interface CorrPair {
  a: string;
  b: string;
  corr: number;
  /** Each stock's share of the portfolio, percent. */
  weightA: number | null;
  weightB: number | null;
  /** Sessions both stocks have prices for. */
  commonSessions: number | null;
}

export interface Correlation {
  asOf: string | null;
  sessions: number | null;
  method: string | null;
  source: string | null;
  holdingsUsed: number | null;
  skipped: Array<{ symbol: string; reason: string | null }>;
  /** A pair at or above this correlation is flagged (0.7). */
  highThreshold: number | null;
  avgCorr: number | null;
  /** Fewest sessions a holding needs to be compared. */
  minSessions: number | null;
  /** Pairs at or above the threshold, and all pairs, over every compared holding (not only those listed). */
  highPairs: number | null;
  pairsTotal: number | null;
  /** Highest correlation first, as the route sorts them. */
  pairs: CorrPair[];
}

async function fetchCorrelation(signal?: AbortSignal): Promise<Correlation> {
  const res = await http({ path: "/api/portfolio/correlation", query: { sessions: CORR_SESSIONS, limit: CORR_LIMIT }, timeoutMs: 30_000, signal });
  const d = rec(res.data);
  if (!Array.isArray(d.pairs)) throw ApiError.contractDrift("portfolio.correlation: no pairs list");
  const pairs: CorrPair[] = d.pairs.flatMap((v): CorrPair[] => {
    const r = rec(v);
    const a = str(r.a)?.toUpperCase();
    const b = str(r.b)?.toUpperCase();
    const corr = num(r.corr);
    if (!a || !b || corr == null || corr < -1 || corr > 1) return [];
    return [{ a, b, corr, weightA: num(r.weight_a_pct), weightB: num(r.weight_b_pct), commonSessions: num(r.common_sessions) }];
  });
  pairs.sort((x, y) => y.corr - x.corr);
  const skipped = (Array.isArray(d.holdings_skipped) ? d.holdings_skipped : []).flatMap((v) => {
    const r = rec(v);
    const symbol = str(r.symbol);
    return symbol ? [{ symbol: symbol.toUpperCase(), reason: str(r.reason) }] : [];
  });
  return {
    asOf: str(d.as_of),
    sessions: num(d.sessions),
    method: str(d.method),
    source: str(d.source),
    holdingsUsed: num(d.holdings_used),
    skipped,
    highThreshold: num(d.high_threshold),
    avgCorr: num(d.avg_corr),
    minSessions: num(d.min_sessions),
    highPairs: num(d.high_pairs),
    pairsTotal: num(d.pairs_total),
    pairs,
  };
}

export function useCorrelation() {
  const profile = useImpersonationStore((s) => s.profileId);
  return useQuery<Correlation>({
    queryKey: ["copilot", "desk", "correlation", CORR_SESSIONS, profile ?? "self"],
    staleTime: 30 * 60_000,
    retry,
    queryFn: ({ signal }) => fetchCorrelation(signal),
  });
}

// ── market-cap split (GET /api/portfolio/market-cap-split) ───────────────

export const CAP_BUCKETS = ["large", "mid", "small", "micro", "unclassified"] as const;
export type CapBucket = (typeof CAP_BUCKETS)[number];

export interface CapSlice {
  bucket: CapBucket;
  valueRs: number | null;
  /** Share of the equity value, percent. */
  weightPct: number | null;
  count: number | null;
  symbols: string[];
  /** False when the route says this bucket cannot be told apart yet. */
  available: boolean;
  /** The route's words on why, for an unavailable bucket. */
  reason: string | null;
}

/** Everything the route could not split yet (outside Nifty 100 while the mid / small lists are missing). */
export interface CapUnsplit {
  valueRs: number | null;
  weightPct: number | null;
  count: number | null;
  symbols: string[];
  reason: string | null;
}

/** One membership list the split used: its name, the date of the list and how many members it has. */
export interface CapIndexList {
  name: string;
  date: string | null;
  members: number | null;
  /** False when the list is not in the warehouse. */
  available: boolean;
}

export interface CapSplit {
  asOf: string | null;
  method: string | null;
  /** False when the route could not split every bucket (the mid / small lists are not on record). */
  available: boolean;
  /** The route's own words on why, when it sends them. */
  reason: string | null;
  totalValueRs: number | null;
  /** Funds are not split; their value as the route states it, and its note. */
  fundsValueRs: number | null;
  fundsNote: string | null;
  slices: CapSlice[];
  unsplit: CapUnsplit | null;
  indices: CapIndexList[];
}

const symbolsOf = (v: unknown): string[] =>
  (Array.isArray(v) ? v : []).flatMap((x) => (typeof x === "string" && x.trim() ? [x.trim().toUpperCase()] : []));

/** `indices` as a list of { index | name, date | as_of, count | members } or a map keyed by the index name. */
function readIndexLists(v: unknown): CapIndexList[] {
  const one = (name: string | null, r: Raw): CapIndexList[] =>
    name ? [{ name, date: str(r.date) ?? str(r.as_of), members: num(r.count) ?? num(r.members) ?? num(r.member_count), available: r.available !== false }] : [];
  if (Array.isArray(v)) return v.flatMap((x) => { const r = rec(x); return one(str(r.index) ?? str(r.name), r); });
  const m = rec(v);
  return Object.keys(m).flatMap((k) => one(k, rec(m[k])));
}

async function fetchCapSplit(signal?: AbortSignal): Promise<CapSplit> {
  const res = await http({ path: "/api/portfolio/market-cap-split", timeoutMs: 30_000, signal });
  const d = rec(res.data);
  if (!Array.isArray(d.buckets)) throw ApiError.contractDrift("portfolio.market-cap-split: no buckets list");
  const byBucket = new Map<CapBucket, CapSlice>();
  for (const v of d.buckets) {
    const r = rec(v);
    const bucket = str(r.bucket)?.toLowerCase();
    if (!bucket || !(CAP_BUCKETS as readonly string[]).includes(bucket) || byBucket.has(bucket as CapBucket)) continue;
    byBucket.set(bucket as CapBucket, {
      bucket: bucket as CapBucket,
      valueRs: num(r.value_rs),
      weightPct: num(r.weight_pct),
      count: num(r.count),
      symbols: symbolsOf(r.symbols),
      available: r.available !== false,
      reason: str(r.reason),
    });
  }
  const excluded = rec(d.excluded);
  const u = rec(d.unsplit);
  const unsplit: CapUnsplit | null = Object.keys(u).length
    ? { valueRs: num(u.value_rs), weightPct: num(u.weight_pct), count: num(u.count), symbols: symbolsOf(u.symbols), reason: str(u.reason) }
    : null;
  return {
    asOf: str(d.as_of),
    method: str(d.method),
    available: d.available !== false,
    reason: str(d.reason) ?? str(d.unavailable_reason) ?? str(d.note),
    totalValueRs: num(d.total_value_rs),
    fundsValueRs: num(excluded.funds_value_rs),
    fundsNote: str(excluded.note),
    slices: CAP_BUCKETS.flatMap((b) => {
      const sl = byBucket.get(b);
      return sl ? [sl] : [];
    }),
    unsplit,
    indices: readIndexLists(d.indices),
  };
}

export function useMarketCapSplit() {
  const profile = useImpersonationStore((s) => s.profileId);
  return useQuery<CapSplit>({
    queryKey: ["copilot", "desk", "market-cap-split", profile ?? "self"],
    staleTime: 10 * 60_000,
    retry,
    queryFn: ({ signal }) => fetchCapSplit(signal),
  });
}

// ── the portfolio donut (design-spec §7: split by market cap, with cash) ─

export type DonutKey = CapBucket | "unsplit" | "funds" | "cash";

export interface DonutSlice {
  key: DonutKey;
  valueRs: number;
  /** Share of the whole portfolio the route valued (direct stocks + funds and other holdings), percent. */
  pct: number;
}

/**
 * The donut's slices from GET /api/portfolio/market-cap-split: each market-cap
 * bucket the route could split, then what it could not split yet, then the funds
 * and other holdings it leaves out. Shares are of direct stocks + funds as the
 * route states them, so the slices add to 100%. null when nothing has a value.
 */
export function capDonut(d: CapSplit, cashRs: number | null = null): { slices: DonutSlice[]; totalRs: number } | null {
  const split = d.slices.filter((sl) => sl.available && sl.valueRs != null && sl.valueRs > 0);
  const unsplit = d.unsplit?.valueRs != null && d.unsplit.valueRs > 0 ? d.unsplit.valueRs : 0;
  const stocks = d.totalValueRs ?? split.reduce((a, sl) => a + (sl.valueRs ?? 0), 0) + unsplit;
  const funds = d.fundsValueRs != null && d.fundsValueRs > 0 ? d.fundsValueRs : 0;
  // Cash only when the brokers reported it (read live); unknown cash is left out, never counted as 0.
  const cash = cashRs != null && cashRs > 0 ? cashRs : 0;
  const totalRs = stocks + funds + cash;
  if (!(totalRs > 0)) return null;
  const slices: DonutSlice[] = split.map((sl) => ({ key: sl.bucket, valueRs: sl.valueRs as number, pct: ((sl.valueRs as number) / totalRs) * 100 }));
  if (unsplit > 0) slices.push({ key: "unsplit", valueRs: unsplit, pct: (unsplit / totalRs) * 100 });
  if (funds > 0) slices.push({ key: "funds", valueRs: funds, pct: (funds / totalRs) * 100 });
  if (cash > 0) slices.push({ key: "cash", valueRs: cash, pct: (cash / totalRs) * 100 });
  return { slices, totalRs };
}

// ── the model's paper record (GET /api/paper-trades/evaluation) ──────────

export interface RecordTiles {
  /** Predictions with an outcome in the bucket set. */
  n: number;
  /** n-weighted mean of the model's probability, percent. */
  predictedPct: number | null;
  /** n-weighted share where the move happened, percent. */
  realisedPct: number | null;
  /** Predictions where the move did not happen. */
  misses: number | null;
}

/** Predicted vs realised over a bucket set, weighting each bucket by its predictions. */
export function recordTiles(buckets: PaperBucket[]): RecordTiles {
  let n = 0;
  let p = 0;
  let r = 0;
  for (const b of buckets) {
    if (!(b.n > 0) || b.predicted_mean == null || b.model_label_rate == null) continue;
    n += b.n;
    p += b.n * b.predicted_mean;
    r += b.n * b.model_label_rate;
  }
  if (n === 0) return { n: 0, predictedPct: null, realisedPct: null, misses: null };
  return { n, predictedPct: (p / n) * 100, realisedPct: (r / n) * 100, misses: Math.round(n - r) };
}

// ── holding risk (GET /api/portfolio/holding-risk) ───────────────────────

export type RiskLevel = "low" | "medium" | "high" | "very_high";
const RISK_LEVELS: readonly string[] = ["low", "medium", "high", "very_high"];
const levelOf = (v: unknown): RiskLevel | null => {
  const s = str(v)?.toLowerCase();
  return s && RISK_LEVELS.includes(s) ? (s as RiskLevel) : null;
};

export const HOLDING_RISK_SESSIONS = 250;

export interface HoldingRiskRow {
  symbol: string;
  name: string | null;
  valueRs: number | null;
  weightPct: number | null;
  lastSession: string | null;
  stale: boolean;
  /** Average traded value over the last 20 sessions, ₹ crore. */
  advCr: number | null;
  daysToExit: number | null;
  belowThreshold: boolean | null;
  liquidityLevel: RiskLevel | null;
  gapSessions: number | null;
  gapRatePct: number | null;
  largestGapDownPct: number | null;
  largestGapDownDate: string | null;
  volatility1mPct: number | null;
  drawdownPct: number | null;
}

export interface RiskRule {
  text: string;
  /** The rule's numbers as the route sends them (min_adv_cr, gap_pct, bands_pct, …). */
  values: Record<string, unknown>;
}

export interface HoldingRisk {
  asOf: string | null;
  sessions: number | null;
  method: string | null;
  source: string | null;
  rules: { liquidity: RiskRule | null; gap: RiskRule | null; volatility: RiskRule | null; drawdown: RiskRule | null };
  holdings: HoldingRiskRow[];
  liquidity: { level: RiskLevel | null; belowThresholdValuePct: number | null; slowest: { symbol: string; days: number } | null };
  gap: { level: RiskLevel | null; ratePct: number | null; largest: { symbol: string; pct: number; date: string | null } | null };
  volatility1m: { pct: number | null; level: RiskLevel | null };
  drawdown: { pct: number | null; level: RiskLevel | null; peakDate: string | null; troughDate: string | null; currentPct: number | null; sessions: number | null };
  series: { symbols: string[]; excluded: Array<{ symbol: string; reason: string | null }>; start: string | null; end: string | null; coveragePct: number | null };
  missing: { noSymbol: string[]; noPrices: string[]; stale: Array<{ symbol: string; lastSession: string | null }>; latestSession: string | null };
}

const strList = (v: unknown): string[] => (Array.isArray(v) ? v.flatMap((x) => (typeof x === "string" && x.trim() ? [x.trim()] : [])) : []);

function readRule(v: unknown): RiskRule | null {
  const r = rec(v);
  const text = str(r.text);
  return text ? { text, values: r } : null;
}

export function readHoldingRisk(body: unknown): HoldingRisk {
  const d = rec(body);
  if (!Array.isArray(d.holdings)) throw ApiError.contractDrift("portfolio.holding-risk: no holdings list");
  const p = rec(d.portfolio);
  const liq = rec(p.liquidity);
  const gap = rec(p.gap);
  const vol = rec(p.volatility_1m);
  const dd = rec(p.drawdown);
  const series = rec(p.series);
  const missing = rec(d.missing);
  const rules = rec(d.rules);
  const slowest = rec(liq.slowest);
  const largest = rec(gap.largest);
  const slowSym = str(slowest.symbol);
  const slowDays = num(slowest.days_to_exit);
  const bigSym = str(largest.symbol);
  const bigPct = num(largest.pct);
  return {
    asOf: str(d.as_of),
    sessions: num(d.sessions),
    method: str(d.method),
    source: str(d.source),
    rules: { liquidity: readRule(rules.liquidity), gap: readRule(rules.gap), volatility: readRule(rules.volatility), drawdown: readRule(rules.drawdown) },
    holdings: d.holdings.flatMap((v): HoldingRiskRow[] => {
      const r = rec(v);
      const symbol = str(r.symbol)?.toUpperCase();
      if (!symbol) return [];
      return [{
        symbol, name: str(r.name), valueRs: num(r.value_rs), weightPct: num(r.weight_pct), lastSession: str(r.last_session),
        stale: r.stale === true, advCr: num(r.adv_cr), daysToExit: num(r.days_to_exit),
        belowThreshold: typeof r.below_threshold === "boolean" ? r.below_threshold : null, liquidityLevel: levelOf(r.liquidity_level),
        gapSessions: num(r.gap_sessions), gapRatePct: num(r.gap_rate_pct), largestGapDownPct: num(r.largest_gap_down_pct),
        largestGapDownDate: str(r.largest_gap_down_date), volatility1mPct: num(r.volatility_1m_pct), drawdownPct: num(r.drawdown_pct),
      }];
    }),
    liquidity: { level: levelOf(liq.level), belowThresholdValuePct: num(liq.below_threshold_value_pct), slowest: slowSym && slowDays != null ? { symbol: slowSym, days: slowDays } : null },
    gap: { level: levelOf(gap.level), ratePct: num(gap.rate_pct), largest: bigSym && bigPct != null ? { symbol: bigSym, pct: bigPct, date: str(largest.date) } : null },
    volatility1m: { pct: num(vol.pct), level: levelOf(vol.level) },
    drawdown: { pct: num(dd.max_pct), level: levelOf(dd.level), peakDate: str(dd.peak_date), troughDate: str(dd.trough_date), currentPct: num(dd.current_pct), sessions: num(dd.sessions) },
    series: {
      symbols: strList(series.symbols),
      excluded: (Array.isArray(series.excluded) ? series.excluded : []).flatMap((x) => {
        const r = rec(x);
        const symbol = str(r.symbol);
        return symbol ? [{ symbol, reason: str(r.reason) }] : [];
      }),
      start: str(series.start), end: str(series.end), coveragePct: num(series.coverage_pct),
    },
    missing: {
      noSymbol: strList(missing.no_symbol),
      noPrices: strList(missing.no_prices),
      stale: (Array.isArray(missing.stale) ? missing.stale : []).flatMap((x) => {
        const r = rec(x);
        const symbol = str(r.symbol);
        return symbol ? [{ symbol, lastSession: str(r.last_session) }] : [];
      }),
      latestSession: str(missing.latest_session),
    },
  };
}

export function useHoldingRisk() {
  const profile = useImpersonationStore((s) => s.profileId);
  return useQuery<HoldingRisk>({
    queryKey: ["copilot", "desk", "holding-risk", HOLDING_RISK_SESSIONS, profile ?? "self"],
    staleTime: 30 * 60_000,
    retry,
    queryFn: async ({ signal }) => {
      const res = await http({ path: "/api/portfolio/holding-risk", query: { sessions: HOLDING_RISK_SESSIONS }, timeoutMs: 30_000, signal });
      return readHoldingRisk(res.data);
    },
  });
}

// ── what the totals are made of (GET /api/portfolio/composition/scope) ───

export type ScopeKind = "broker_account" | "broker_file" | "statement" | "manual";
const SCOPE_KINDS: readonly string[] = ["broker_account", "broker_file", "statement", "manual"];

export interface ScopeLine {
  isin: string | null;
  symbol: string | null;
  quantity: number;
}

export interface ScopeAccount {
  key: string;
  kind: ScopeKind;
  name: string;
  broker: string | null;
  accountId: string | null;
  holdings: number;
  valueRs: number | null;
  investedRs: number | null;
  weightPct: number | null;
  /** asset type → rows ("equity": 3). */
  instrumentTypes: Record<string, number>;
  unpriced: number;
  noCost: number;
  lastUpdated: string | null;
  lastSyncAt: string | null;
  /** A broker account's stored lines, for the reconciliation with its live read. */
  lines: ScopeLine[] | null;
}

export interface PortfolioScope {
  asOf: string | null;
  source: string | null;
  accounts: ScopeAccount[];
  instrumentTypes: Record<string, number>;
  allocation: Array<{ assetClass: string; valueRs: number | null; weightPct: number | null }>;
  totals: { holdings: number; valueRs: number | null; investedRs: number | null; unpricedRows: number; noCostRows: number };
  lastUpdated: string | null;
  oldestUpdated: string | null;
  rule: string | null;
  duplicates: Array<{ isin: string; name: string | null; sources: string[]; rows: number }>;
}

const countMap = (v: unknown): Record<string, number> => {
  const out: Record<string, number> = {};
  for (const [k, x] of Object.entries(rec(v))) {
    const n = num(x);
    if (n != null && n > 0) out[k] = n;
  }
  return out;
};

export function readScope(body: unknown): PortfolioScope {
  const d = rec(body);
  if (!Array.isArray(d.accounts)) throw ApiError.contractDrift("portfolio.composition.scope: no accounts list");
  const t = rec(d.totals);
  const recon = rec(d.reconciliation);
  return {
    asOf: str(d.as_of),
    source: str(d.source),
    accounts: d.accounts.flatMap((v): ScopeAccount[] => {
      const a = rec(v);
      const key = str(a.key);
      const kind = str(a.kind);
      const name = str(a.name);
      if (!key || !name || !kind || !SCOPE_KINDS.includes(kind)) return [];
      return [{
        key, kind: kind as ScopeKind, name, broker: str(a.broker), accountId: str(a.account_id),
        holdings: num(a.holdings) ?? 0, valueRs: num(a.value_rs), investedRs: num(a.invested_rs), weightPct: num(a.weight_pct),
        instrumentTypes: countMap(a.instrument_types), unpriced: num(a.unpriced) ?? 0, noCost: num(a.no_cost) ?? 0,
        lastUpdated: str(a.last_updated), lastSyncAt: str(a.last_sync_at),
        lines: Array.isArray(a.lines)
          ? a.lines.flatMap((x) => {
              const l = rec(x);
              const q = num(l.quantity);
              return q != null ? [{ isin: str(l.isin)?.toUpperCase() ?? null, symbol: str(l.symbol)?.toUpperCase() ?? null, quantity: q }] : [];
            })
          : null,
      }];
    }),
    instrumentTypes: countMap(d.instrument_types),
    allocation: (Array.isArray(d.asset_allocation) ? d.asset_allocation : []).flatMap((x) => {
      const r = rec(x);
      const assetClass = str(r.asset_class);
      return assetClass ? [{ assetClass, valueRs: num(r.value_rs), weightPct: num(r.weight_pct) }] : [];
    }),
    totals: { holdings: num(t.holdings) ?? 0, valueRs: num(t.value_rs), investedRs: num(t.invested_rs), unpricedRows: num(t.unpriced_rows) ?? 0, noCostRows: num(t.no_cost_rows) ?? 0 },
    lastUpdated: str(d.last_updated),
    oldestUpdated: str(d.oldest_updated),
    rule: str(recon.rule),
    duplicates: (Array.isArray(recon.duplicates) ? recon.duplicates : []).flatMap((x) => {
      const r = rec(x);
      const isin = str(r.isin);
      return isin ? [{ isin, name: str(r.name), sources: strList(r.sources), rows: num(r.rows) ?? 0 }] : [];
    }),
  };
}

export function usePortfolioScope() {
  const profile = useImpersonationStore((s) => s.profileId);
  return useQuery<PortfolioScope>({
    queryKey: ["copilot", "desk", "portfolio-scope", profile ?? "self"],
    staleTime: 5 * 60_000,
    retry,
    queryFn: async ({ signal }) => readScope((await http({ path: "/api/portfolio/composition/scope", signal })).data),
  });
}

/** "equity 3 · mutual fund 1", largest first. */
export function typesText(types: Record<string, number>): string {
  return Object.entries(types)
    .sort((a, b) => b[1] - a[1])
    .map(([k, n]) => `${k.replace(/_/g, " ")} ${n}`)
    .join(" · ");
}

/**
 * One broker account's live read against the lines its last sync stored, by ISIN (else symbol) and quantity.
 * `matches` is true only when every line is on both sides with the same quantity.
 */
export function reconcileAccount(
  live: Array<{ isin: string | null; symbol: string; qty: number }>,
  stored: ScopeLine[],
): { matches: boolean; differing: number; onlyLive: number; onlyStored: number } {
  const keyOf = (isin: string | null, symbol: string | null) => (isin ? `I:${isin.toUpperCase()}` : symbol ? `S:${symbol.toUpperCase()}` : null);
  const sum = (m: Map<string, number>, k: string | null, q: number) => { if (k) m.set(k, (m.get(k) ?? 0) + q); };
  const a = new Map<string, number>();
  const b = new Map<string, number>();
  for (const l of live) sum(a, keyOf(l.isin, l.symbol), l.qty);
  for (const l of stored) sum(b, keyOf(l.isin, l.symbol), l.quantity);
  let differing = 0;
  let onlyLive = 0;
  let onlyStored = 0;
  for (const [k, q] of a) {
    if (!b.has(k)) onlyLive += 1;
    else if (Math.abs((b.get(k) as number) - q) > 1e-6) differing += 1;
  }
  for (const k of b.keys()) if (!a.has(k)) onlyStored += 1;
  return { matches: differing + onlyLive + onlyStored === 0, differing, onlyLive, onlyStored };
}

// ── realised gains (GET /api/portfolio/capital-gains-statement) ──────────

export interface RealisedGains {
  fy: string | null;
  /** Rows (sales) on record in the year; 0 means no sale is on record, not a zero gain. */
  sales: number;
  /** Short + long term equity gains, FIFO; null when no sale is on record. */
  totalRs: number | null;
  shortTermRs: number | null;
  longTermRs: number | null;
  gaps: string[];
}

export function readRealisedGains(body: unknown): RealisedGains {
  const d = rec(body);
  const sections = rec(d.sections);
  if (!Object.keys(sections).length || !Array.isArray(d.summary)) throw ApiError.contractDrift("portfolio.capital-gains-statement: no sections");
  const a = rec(sections.A_stcg_equity);
  const b = rec(sections.B_ltcg_equity);
  const sales = (Array.isArray(a.rows) ? a.rows.length : 0) + (Array.isArray(b.rows) ? b.rows.length : 0);
  const st = num(rec(a.total).gain_rs);
  const lt = num(rec(b.total).gain_rs);
  return {
    fy: str(rec(d.header).fy),
    sales,
    totalRs: sales > 0 && st != null && lt != null ? Math.round((st + lt) * 100) / 100 : null,
    shortTermRs: sales > 0 ? st : null,
    longTermRs: sales > 0 ? lt : null,
    gaps: strList(d.data_gaps),
  };
}

export function useRealisedGains() {
  const profile = useImpersonationStore((s) => s.profileId);
  return useQuery<RealisedGains>({
    queryKey: ["copilot", "desk", "realised-gains", profile ?? "self"],
    staleTime: 30 * 60_000,
    retry,
    queryFn: async ({ signal }) => readRealisedGains((await http({ path: "/api/portfolio/capital-gains-statement", signal })).data),
  });
}

// ── import with a preview (POST /api/portfolio/upload/preview, …/commit) ──

export type ImportRowStatus = "ready" | "review" | "rejected";

export interface ImportFlag {
  code: string;
  level: "info" | "review" | "reject";
  text: string;
}

export interface ImportRow {
  rowNo: number;
  name: string;
  symbol: string | null;
  isin: string | null;
  /** "file" when the file stated the ISIN, "nse_list" when it was looked up from the symbol. */
  isinSource: string | null;
  exchange: string | null;
  quantity: number | null;
  avgCost: number | null;
  price: number | null;
  instrumentType: string | null;
  accountRef: string | null;
  currency: string | null;
  status: ImportRowStatus;
  include: boolean;
  flags: ImportFlag[];
}

export interface ImportPreview {
  id: string;
  createdAt: string | null;
  expiresAt: string | null;
  file: { name: string | null; kind: string | null; sizeBytes: number | null; format: string | null; brokerName: string | null; skippedRows: number | null };
  accountNote: string | null;
  currency: string | null;
  currencyBasis: string | null;
  rows: ImportRow[];
  counts: { rows: number; ready: number; review: number; rejected: number };
  effectsNote: string | null;
  checks: string[];
  nothingSaved: boolean;
}

const IMPORT_STATUSES: readonly string[] = ["ready", "review", "rejected"];
const FLAG_LEVELS: readonly string[] = ["info", "review", "reject"];

export function readImportPreview(body: unknown): ImportPreview {
  const d = rec(body);
  const id = str(d.preview_id);
  if (!id || !Array.isArray(d.rows)) throw ApiError.contractDrift("portfolio.upload.preview: no preview id or rows");
  const f = rec(d.file);
  const c = rec(d.counts);
  return {
    id,
    createdAt: str(d.created_at),
    expiresAt: str(d.expires_at),
    file: { name: str(f.name), kind: str(f.kind), sizeBytes: num(f.size_bytes), format: str(f.format), brokerName: str(f.broker_name), skippedRows: num(f.skipped_rows) },
    accountNote: str(rec(d.account_ref).note),
    currency: str(d.currency),
    currencyBasis: str(d.currency_basis),
    rows: d.rows.flatMap((v): ImportRow[] => {
      const r = rec(v);
      const rowNo = num(r.row_no);
      const status = str(r.status);
      if (rowNo == null || !status || !IMPORT_STATUSES.includes(status)) return [];
      return [{
        rowNo, name: str(r.name) ?? "—", symbol: str(r.symbol), isin: str(r.isin), isinSource: str(r.isin_source), exchange: str(r.exchange),
        quantity: num(r.quantity), avgCost: num(r.avg_cost), price: num(r.current_price), instrumentType: str(r.instrument_type),
        accountRef: str(r.account_ref), currency: str(r.currency), status: status as ImportRowStatus, include: r.include === true,
        flags: (Array.isArray(r.flags) ? r.flags : []).flatMap((x) => {
          const fl = rec(x);
          const code = str(fl.code);
          const level = str(fl.level);
          const text = str(fl.text);
          return code && level && text && FLAG_LEVELS.includes(level) ? [{ code, level: level as ImportFlag["level"], text }] : [];
        }),
      }];
    }),
    counts: { rows: num(c.rows) ?? 0, ready: num(c.ready) ?? 0, review: num(c.review) ?? 0, rejected: num(c.rejected) ?? 0 },
    effectsNote: str(rec(d.effects).note),
    checks: strList(d.checks),
    nothingSaved: d.nothing_saved === true,
  };
}

export interface ImportDone {
  count: number;
  committedRows: number[];
  leftOutRows: number[];
}

/** Step 1: send the file; the server reads, validates and flags it and saves nothing. One request per press (no retry). */
export function usePreviewImport() {
  return useMutation<ImportPreview, unknown, File>({
    mutationFn: async (file) => {
      const form = new FormData();
      form.append("file", file);
      let res: Response;
      try {
        res = await apiFetch("/api/portfolio/upload/preview", { method: "POST", body: form });
      } catch (cause) {
        throw ApiError.network(cause);
      }
      const body: unknown = await res.json().catch(() => undefined);
      if (!res.ok) throw ApiError.fromResponse(res, body);
      return readImportPreview(body);
    },
  });
}

/** Step 2: save the chosen rows of a preview. Holdings-based reads are refreshed afterwards. */
export function useCommitImport() {
  const qc = useQueryClient();
  return useMutation<ImportDone, unknown, { id: string; rows: number[] }>({
    mutationFn: async ({ id, rows }) => {
      const res = await http({ method: "POST", path: `/api/portfolio/upload/preview/${encodeURIComponent(id)}/commit`, body: { rows }, noRetry: true });
      const d = rec(res.data);
      const count = num(d.count);
      if (count == null) throw ApiError.contractDrift("portfolio.upload.commit: no count");
      const ints = (v: unknown) => (Array.isArray(v) ? v.flatMap((x) => (typeof x === "number" && Number.isInteger(x) ? [x] : [])) : []);
      return { count, committedRows: ints(d.committed_rows), leftOutRows: ints(d.left_out_rows) };
    },
    onSuccess: () => {
      for (const key of ["holdings-enriched", "portfolio-scope", "risk-analytics", "correlation", "market-cap-split", "holding-risk"]) {
        void qc.invalidateQueries({ predicate: (q) => q.queryKey.includes(key) });
      }
      void qc.invalidateQueries({ queryKey: ["portfolio"] });
    },
  });
}
