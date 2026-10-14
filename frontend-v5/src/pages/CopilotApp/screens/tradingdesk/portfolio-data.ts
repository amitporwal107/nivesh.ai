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

export type DonutKey = CapBucket | "unsplit" | "funds";

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
export function capDonut(d: CapSplit): { slices: DonutSlice[]; totalRs: number } | null {
  const split = d.slices.filter((sl) => sl.available && sl.valueRs != null && sl.valueRs > 0);
  const unsplit = d.unsplit?.valueRs != null && d.unsplit.valueRs > 0 ? d.unsplit.valueRs : 0;
  const stocks = d.totalValueRs ?? split.reduce((a, sl) => a + (sl.valueRs ?? 0), 0) + unsplit;
  const funds = d.fundsValueRs != null && d.fundsValueRs > 0 ? d.fundsValueRs : 0;
  const totalRs = stocks + funds;
  if (!(totalRs > 0)) return null;
  const slices: DonutSlice[] = split.map((sl) => ({ key: sl.bucket, valueRs: sl.valueRs as number, pct: ((sl.valueRs as number) / totalRs) * 100 }));
  if (unsplit > 0) slices.push({ key: "unsplit", valueRs: unsplit, pct: (unsplit / totalRs) * 100 });
  if (funds > 0) slices.push({ key: "funds", valueRs: funds, pct: (funds / totalRs) * 100 });
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
