/**
 * Portfolio analysis — performance.
 *
 * 1. Query hooks for the endpoints the Performance page
 *    (src/pages/Performance/index.tsx) reads through hooks of its own, which
 *    it does not export:
 *      GET /api/portfolio/fund-performance        useFundPerformance
 *      GET /api/portfolio/analytics               useHeatmapTiles   (its `heatmap_data`)
 *      GET /api/portfolio/value-history           useValueHistory
 *      GET /api/portfolio/recommendations/v5      useHoldingRecs
 *      GET /api/mf/category-top                   useCategoryTop
 *    The period figures come from the shared useDashboard("performance", { period }).
 * 2. The derivations of that page, copied; each function names the one it
 *    copies. A figure the backend did not send stays null (shown as "—").
 *
 * As everywhere in this folder, a fetcher returns a complete typed value or
 * throws ApiError("contract_drift"), so a `200 {}` ends in an ErrorBlock.
 *
 * Units: money is RUPEES; percentages are in percent units (12.4 = 12.4%).
 */
import { useQuery } from "@tanstack/react-query";
import { http } from "@/services/api/http";
import { ApiError } from "@/services/api/errors";
import type { DashboardEnvelopeC } from "@/services/contracts/dashboard.contract";
import type { Tone } from "../../components/ui";
import { humanise, list, num, rec, str } from "./data";

// ── period (GET /api/dashboards/performance?period=…) ────────────────────

export const PERIODS = [
  { id: "inception", label: "Since inception" },
  { id: "1Y", label: "1Y" },
  { id: "6M", label: "6M" },
  { id: "3M", label: "3M" },
  { id: "1M", label: "1M" },
] as const;

export type PeriodId = (typeof PERIODS)[number]["id"];

/** The period words the old page prints beside a block title (PeriodBadge). */
export const PERIOD_BADGE: Record<PeriodId, string> = {
  inception: "Since inception",
  "1Y": "1 year",
  "6M": "6 months",
  "3M": "3 months",
  "1M": "1 month",
};

export interface PerfTile {
  /** As the backend labels it: "XIRR", "Return (1Y)", "Alpha", "Sharpe", "Hit Rate". */
  label: string;
  /** Already formatted by the backend; "—" when it has no figure. */
  value: string;
  sub: string;
  tone: Tone;
  /** The old page's own caveat for the tile, when one applies. */
  note: string;
}

export interface MonthReturn {
  month: string;
  portfolio: number | null;
  benchmark: number | null;
}

export interface PerformanceRead {
  headline: string;
  /** "HEALTHY" | "FAIR" | "POOR" | "CALCULATING" | "EMPTY", or empty. */
  statusPill: string;
  tiles: PerfTile[];
  months: MonthReturn[];
  coverage: { matched: number; total: number } | null;
  computedAt: string;
}

/** Copy of toneColor(). */
function tileTone(tone: unknown): Tone {
  if (tone === "moss" || tone === "good") return "mint";
  if (tone === "rust" || tone === "neg") return "danger";
  return tone === "saffron" || tone === "warm" ? "amber" : "ink";
}

const NO_VALUE = "—";

/** Copy of what PerformancePage() takes from the dashboard envelope. */
export function readPerformance(env: DashboardEnvelopeC, period: PeriodId): PerformanceRead {
  const breakdown = rec(env.breakdown);
  const coverage = rec(breakdown?.coverage);
  const matched = num(coverage?.matched_funds);
  const total = num(coverage?.total_funds);
  const tiles = env.stat_tiles.map((t): PerfTile => {
    const value = t.value == null || t.value === "" ? NO_VALUE : String(t.value);
    const sub = str(t.sub);
    const notes: string[] = [];
    // With too little statement history the backend answers a bounded period with the since-inception XIRR.
    if (t.label === "XIRR" && period !== "inception") notes.push("Not enough CAS history — showing XIRR (since inception)");
    const sharpe = t.label === "Sharpe" ? parseFloat(value) : NaN;
    if (sharpe >= 1.0 && sub !== "above 1.0 ✓") notes.push("above 1.0 ✓");
    return { label: t.label, value, sub, tone: value === NO_VALUE ? "ink" : tileTone(t.tone), note: notes.join(" · ") };
  });
  return {
    headline: typeof env.insight === "string" ? env.insight.trim() : str(env.insight?.headline),
    statusPill: str(breakdown?.status_pill),
    tiles,
    months: list(breakdown?.monthly_returns).flatMap((m): MonthReturn[] => {
      const r = rec(m);
      const month = str(r?.month);
      return r && month ? [{ month, portfolio: num(r.portfolio), benchmark: num(r.benchmark) }] : [];
    }),
    coverage: matched != null && total != null ? { matched, total } : null,
    computedAt: str(breakdown?.computed_at),
  };
}

/** "beat" when the month is at or above its benchmark; null when either figure is missing. Copy of MonthlyReturnsGrid(). */
export function monthVerdict(m: MonthReturn): "beat" | "miss" | null {
  if (m.portfolio == null || m.benchmark == null) return null;
  return m.portfolio >= m.benchmark ? "beat" : "miss";
}

// ── value history (GET /api/portfolio/value-history) ─────────────────────

export interface ValueHistory {
  /** Oldest first; `month` is the statement's own label, e.g. "Aug 2025". */
  months: Array<{ month: string; valueRs: number }>;
  /** Today's value from the holdings; null when it is not positive. */
  currentValueRs: number | null;
  /** "cas_statement" today. */
  source: string;
}

export async function fetchValueHistory(signal?: AbortSignal): Promise<ValueHistory> {
  const data = rec((await http({ path: "/api/portfolio/value-history", signal })).data);
  if (!data || !Array.isArray(data.monthly_values)) throw ApiError.contractDrift("portfolio.valueHistory: missing `monthly_values`");
  const current = num(data.current_value_rs);
  return {
    months: data.monthly_values.flatMap((m: unknown) => {
      const r = rec(m);
      const month = str(r?.month);
      const valueRs = num(r?.value_rs);
      return month && valueRs != null ? [{ month, valueRs }] : [];
    }),
    currentValueRs: current != null && current > 0 ? current : null,
    source: str(data.source),
  };
}

export function useValueHistory() {
  return useQuery<ValueHistory>({
    queryKey: ["portfolio", "value-history"],
    staleTime: 10 * 60_000,
    queryFn: ({ signal }) => fetchValueHistory(signal),
  });
}

export interface ValuePointLabelled {
  label: string;
  valueRs: number;
}

export interface ValueSeries {
  /** The statement's months, then "Now" when there is a current value. */
  points: ValuePointLabelled[];
  lastRs: number;
  /** First point to last, percent; null when the first value is not positive. */
  changePct: number | null;
  /** Statement months behind the series. */
  monthCount: number;
}

/** Copy of the series PortfolioValueChart() draws. null = no statement history. */
export function valueSeries(h: ValueHistory): ValueSeries | null {
  if (h.months.length === 0) return null;
  const points: ValuePointLabelled[] = h.months.map((m) => ({ label: m.month, valueRs: m.valueRs }));
  if (h.currentValueRs != null) points.push({ label: "Now", valueRs: h.currentValueRs });
  const first = points[0].valueRs;
  const last = points[points.length - 1].valueRs;
  return { points, lastRs: last, changePct: first > 0 ? ((last - first) / first) * 100 : null, monthCount: h.months.length };
}

/** Short axis label without the rupee sign: "1.07 Cr", "92.8 L", "45k". Copy of fmt() in PortfolioValueChart(). */
export function axisRupees(v: number): string {
  if (v >= 1e7) return `${(v / 1e7).toFixed(2)} Cr`;
  if (v >= 1e5) return `${(v / 1e5).toFixed(1)} L`;
  return `${Math.round(v / 1000)}k`;
}

// ── fund ratings (GET /api/portfolio/fund-performance) ───────────────────

export interface FundRating {
  name: string;
  ticker: string;
  sector: string;
  invested: number | null;
  currentValue: number | null;
  /** Gain on invested money since purchase. */
  simpleReturnPct: number | null;
  return1m: number | null;
  return3m: number | null;
  return1y: number | null;
  return3y: number | null;
  xirrPct: number | null;
  alpha: number | null;
  /** "overperforming" | "meeting" | "underperforming" | "no_data" | "etf_equity". */
  rating: string;
  schemeCategory: string;
  schemeCode: string;
  /** "mutual_fund" | "etf" | "equity" | "gold" | "other"; empty when the row has none. */
  assetType: string;
  benchmarkReturn: number | null;
  benchmarkName: string;
  categoryRank: number | null;
  categoryTotal: number | null;
  /** Percentile within the category, 0–100 (100 = best). */
  categoryRankPct: number | null;
  qualityScore: number | null;
  sectorRank: number | null;
  sectorTotal: number | null;
}

export interface NamedReturn {
  name: string;
  returnPct: number | null;
}

export interface Performers {
  top: NamedReturn[];
  bottom: NamedReturn[];
}

export type PerfKey = "inception" | "1Y" | "3M" | "1M";

export interface Distribution {
  overperforming: number;
  meeting: number;
  underperforming: number;
}

export interface FundPerformance {
  ratings: FundRating[];
  /** The backend's own count across mutual funds; null when it sent none. */
  distribution: Distribution | null;
  /** Best and worst per period, from the backend; null when it sent none. */
  byPeriod: Record<PerfKey, Performers> | null;
  /** The older 1-year lists. */
  top: NamedReturn[];
  bottom: NamedReturn[];
  meeting: NamedReturn[];
}

/** A code the backend may send as a string or as a number. */
function code(v: unknown): string {
  return typeof v === "number" && Number.isFinite(v) ? String(v) : str(v);
}

function toRating(raw: unknown): FundRating[] {
  const r = rec(raw);
  const name = str(r?.name);
  if (!r || !name) return [];
  return [{
    name,
    ticker: str(r.ticker),
    sector: str(r.sector),
    invested: num(r.invested),
    currentValue: num(r.current_value),
    simpleReturnPct: num(r.simple_return_pct),
    return1m: num(r.return_1m),
    return3m: num(r.return_3m),
    return1y: num(r.return_1y),
    return3y: num(r.return_3y),
    xirrPct: num(r.xirr_pct),
    alpha: num(r.alpha),
    rating: str(r.rating),
    schemeCategory: str(r.scheme_category),
    schemeCode: code(r.scheme_code),
    assetType: str(r.asset_type).toLowerCase(),
    benchmarkReturn: num(r.benchmark_return),
    benchmarkName: str(r.benchmark_name),
    categoryRank: num(r.category_rank),
    categoryTotal: num(r.category_total),
    categoryRankPct: num(r.category_rank_pct),
    qualityScore: num(r.quality_score),
    sectorRank: num(r.sector_rank),
    sectorTotal: num(r.sector_total),
  }];
}

function namedReturns(raw: unknown, field: string): NamedReturn[] {
  return list(raw).flatMap((x) => {
    const r = rec(x);
    const name = str(r?.name);
    return r && name ? [{ name, returnPct: num(r[field]) }] : [];
  });
}

function readDistribution(raw: unknown): Distribution | null {
  const d = rec(raw);
  const over = num(d?.overperforming);
  const meeting = num(d?.meeting);
  const under = num(d?.underperforming);
  if (over == null && meeting == null && under == null) return null;
  return { overperforming: over ?? 0, meeting: meeting ?? 0, underperforming: under ?? 0 };
}

function readByPeriod(raw: unknown): Record<PerfKey, Performers> | null {
  const d = rec(raw);
  if (!d) return null;
  const of = (key: PerfKey): Performers => {
    const p = rec(d[key]);
    return { top: namedReturns(p?.top, "return_pct"), bottom: namedReturns(p?.bottom, "return_pct") };
  };
  return { inception: of("inception"), "1Y": of("1Y"), "3M": of("3M"), "1M": of("1M") };
}

export async function fetchFundPerformance(signal?: AbortSignal): Promise<FundPerformance> {
  const data = rec((await http({ path: "/api/portfolio/fund-performance", signal })).data);
  if (!data || !Array.isArray(data.fund_ratings)) throw ApiError.contractDrift("portfolio.fundPerformance: missing `fund_ratings`");
  return {
    ratings: data.fund_ratings.flatMap(toRating),
    distribution: readDistribution(data.performance_distribution),
    byPeriod: readByPeriod(data.performers_by_period),
    top: namedReturns(data.top_performers, "return_1y"),
    bottom: namedReturns(data.bottom_performers, "return_1y"),
    meeting: namedReturns(data.meeting_performers, "return_1y"),
  };
}

export function useFundPerformance() {
  return useQuery<FundPerformance>({
    queryKey: ["portfolio", "fund-performance"],
    staleTime: 5 * 60_000,
    queryFn: ({ signal }) => fetchFundPerformance(signal),
  });
}

// ── heatmap tiles (GET /api/portfolio/analytics) ─────────────────────────

export interface HeatmapTile {
  /** The backend cuts this to 30 characters. */
  name: string;
  ticker: string;
  valueRs: number;
  /** null when the holding has no cost basis on record. */
  investedRs: number | null;
  returnPct: number | null;
  assetType: string;
  sector: string;
  qualityScore: number | null;
  sectorRank: number | null;
  sectorTotal: number | null;
}

/** The analytics payload's `heatmap_data`: the largest holdings by value (the backend sends at most 40). */
export async function fetchHeatmapTiles(signal?: AbortSignal): Promise<HeatmapTile[]> {
  const data = rec((await http({ path: "/api/portfolio/analytics", signal })).data);
  // An account with no holdings gets the totals without `heatmap_data`.
  if (!data || (!Array.isArray(data.heatmap_data) && num(data.holdings_count) == null)) {
    throw ApiError.contractDrift("portfolio.analytics: missing `heatmap_data`");
  }
  return list(data.heatmap_data).flatMap((t): HeatmapTile[] => {
    const r = rec(t);
    const name = str(r?.name);
    const valueRs = num(r?.value);
    if (!r || !name || valueRs == null) return [];
    return [{
      name,
      ticker: str(r.ticker),
      valueRs,
      investedRs: num(r.invested),
      returnPct: num(r.return_pct),
      assetType: str(r.asset_type).toLowerCase(),
      sector: str(r.sector),
      qualityScore: num(r.quality_score),
      sectorRank: num(r.sector_rank),
      sectorTotal: num(r.sector_total),
    }];
  });
}

export function useHeatmapTiles() {
  return useQuery<HeatmapTile[]>({
    queryKey: ["portfolio", "analytics-heatmap"],
    staleTime: 5 * 60_000,
    queryFn: ({ signal }) => fetchHeatmapTiles(signal),
  });
}

// ── asset-class tabs ─────────────────────────────────────────────────────

export type AssetTab = "all" | "mf" | "stocks" | "etf" | "sgb";

export const ASSET_TABS: Array<{ id: AssetTab; label: string }> = [
  { id: "all", label: "All" },
  { id: "mf", label: "MF" },
  { id: "stocks", label: "Stocks" },
  { id: "etf", label: "ETF" },
  { id: "sgb", label: "SGB / Bonds" },
];

export function assetTabLabel(tab: AssetTab): string {
  return ASSET_TABS.find((t) => t.id === tab)?.label ?? "";
}

/** What "vs category benchmark" compares on each tab. The old page's wording, verbatim. */
export const BENCHMARK_EXPLANATION: Record<AssetTab, string> = {
  all: "Portfolio XIRR vs Nifty 500 CAGR — broad India equity market benchmark",
  mf: "Each fund vs its sub-category peer average (e.g. Large Cap fund vs all Large Cap funds)",
  stocks: "Each stock vs Nifty 500 total-return index for the selected period",
  etf: "ETF vs underlying index — Nifty ETF → Nifty 50, Gold ETF → MCX Gold price CAGR",
  sgb: "SGB return (gold price CAGR + 2.5% annual interest) vs MCX Gold spot price",
};

/** Copy of ratingToTab(). */
export function ratingToTab(r: FundRating): AssetTab {
  if (r.rating === "etf_equity") return "etf";
  if (r.assetType === "etf") return "etf";
  if (r.assetType === "equity") return "stocks";
  if (r.assetType === "gold" || r.assetType === "sgb") return "sgb";
  return "mf"; // mutual_fund, and rows with no asset type
}

/** Copy of filterByTab(). */
export function filterByTab(ratings: FundRating[], tab: AssetTab): FundRating[] {
  return tab === "all" ? ratings : ratings.filter((r) => ratingToTab(r) === tab);
}

type ReturnField = "return1y" | "return3m" | "return1m" | "return3y" | "xirrPct";

/** Average of one return weighted by invested money, over the folios that have it. */
function weightedAvg(group: FundRating[], field: ReturnField): number | null {
  const valid = group.filter((r) => r[field] != null);
  if (valid.length === 0) return null;
  const totalW = valid.reduce((s, r) => s + (r.invested ?? 1), 0) || 1;
  const sum = valid.reduce((s, r) => s + (r[field] ?? 0) * (r.invested ?? 1), 0);
  return parseFloat((sum / totalW).toFixed(2));
}

/**
 * One row per fund when the same fund sits in several folios: money summed,
 * returns averaged by invested money. Copy of consolidateByName().
 */
export function consolidateByName(ratings: FundRating[]): FundRating[] {
  const groups = new Map<string, FundRating[]>();
  for (const r of ratings) groups.set(r.name, [...(groups.get(r.name) ?? []), r]);
  return [...groups.values()].map((group) => {
    if (group.length === 1) return group[0];
    const invested = group.reduce((s, r) => s + (r.invested ?? 0), 0);
    const currentValue = group.reduce((s, r) => s + (r.currentValue ?? 0), 0);
    return {
      ...group[0],
      invested,
      currentValue,
      simpleReturnPct: invested > 0 ? parseFloat((((currentValue - invested) / invested) * 100).toFixed(2)) : null,
      return1y: weightedAvg(group, "return1y"),
      return3m: weightedAvg(group, "return3m"),
      return1m: weightedAvg(group, "return1m"),
      return3y: weightedAvg(group, "return3y"),
      xirrPct: weightedAvg(group, "xirrPct"),
    };
  });
}

/** Copy of distributionFromRatings(): an ETF is rated by its return against its benchmark, ±2 points. */
export function distributionFromRatings(ratings: FundRating[]): Distribution {
  const out: Distribution = { overperforming: 0, meeting: 0, underperforming: 0 };
  for (const r of consolidateByName(ratings)) {
    let rating = r.rating;
    if (rating === "etf_equity") {
      const ret = r.return1y ?? r.simpleReturnPct;
      if (ret != null && r.benchmarkReturn != null) {
        const diff = ret - r.benchmarkReturn;
        rating = diff >= 2 ? "overperforming" : diff >= -2 ? "meeting" : "underperforming";
      }
    }
    if (rating === "overperforming") out.overperforming++;
    else if (rating === "meeting") out.meeting++;
    else if (rating === "underperforming") out.underperforming++;
  }
  return out;
}

const PERF_FIELD: Record<PerfKey, "simpleReturnPct" | "return1y" | "return3m" | "return1m"> = {
  inception: "simpleReturnPct",
  "1Y": "return1y",
  "3M": "return3m",
  "1M": "return1m",
};

/** Copy of performersFromRatings(): ten best and ten worst for one period. */
function performersFromRatings(ratings: FundRating[], key: PerfKey): Performers {
  const field = PERF_FIELD[key];
  const sorted = consolidateByName(ratings)
    .flatMap((r) => { const v = r[field]; return v != null ? [{ name: r.name, returnPct: v }] : []; })
    .sort((a, b) => b.returnPct - a.returnPct);
  return { top: sorted.slice(0, 10), bottom: sorted.slice(-10).reverse() };
}

/** The page period → the performers bucket. The API has no 6-month bucket; the old page falls back to 1 year. */
export const PERF_KEY_FOR: Record<PeriodId, PerfKey> = { inception: "inception", "1Y": "1Y", "6M": "1Y", "3M": "3M", "1M": "1M" };

export const PERF_KEY_LABEL: Record<PerfKey, string> = { inception: "Since purchase", "1Y": "1 Year", "3M": "3 Months", "1M": "1 Month" };

export interface PerformersView {
  key: PerfKey;
  top: NamedReturn[];
  bottom: NamedReturn[];
  /** Funds within ±2 points of their benchmark (1-year return). Only on the All and MF tabs. */
  meeting: NamedReturn[];
}

/**
 * Copy of what PerformancePage() hands BestWorstPerformers(): the backend's
 * lists on the All and MF tabs, lists derived from the tab's own rows elsewhere.
 */
export function performersFor(fp: FundPerformance, tab: AssetTab, period: PeriodId): PerformersView {
  const key = PERF_KEY_FOR[period];
  const wide = tab === "all" || tab === "mf";
  const tabRatings = filterByTab(fp.ratings, tab);
  const byPeriod = (wide ? fp.byPeriod : null) ?? (tabRatings.length > 0
    ? { inception: performersFromRatings(tabRatings, "inception"), "1Y": performersFromRatings(tabRatings, "1Y"), "3M": performersFromRatings(tabRatings, "3M"), "1M": performersFromRatings(tabRatings, "1M") }
    : null);
  return {
    key,
    top: byPeriod ? byPeriod[key].top : wide ? fp.top : [],
    bottom: byPeriod ? byPeriod[key].bottom : wide ? fp.bottom : [],
    meeting: wide ? fp.meeting : [],
  };
}

/** Copy of the choice in PerformancePage(): the backend's count on All and MF, a count of the tab's rows elsewhere. */
export function distributionFor(fp: FundPerformance, tab: AssetTab): Distribution {
  return (tab === "all" || tab === "mf") && fp.distribution ? fp.distribution : distributionFromRatings(filterByTab(fp.ratings, tab));
}

// ── holdings composition and its drill-down ──────────────────────────────

export interface CompositionSlice {
  tab: Exclude<AssetTab, "all">;
  label: string;
  valueRs: number;
  /** Whole percent of the four classes together. */
  pct: number;
}

/**
 * Current value by asset class. Copy of the sums in HoldingsCompositionPie():
 * MF and ETF from the fund ratings, Stocks and SGB / Bonds from the heatmap
 * tiles. The tiles are only the largest holdings, so the four can add up to
 * less than the portfolio.
 */
export function compositionSlices(ratings: FundRating[], tiles: HeatmapTile[]): CompositionSlice[] {
  const value = { mf: 0, stocks: 0, etf: 0, sgb: 0 };
  for (const r of ratings) {
    const tab = ratingToTab(r);
    if (tab === "mf" || tab === "etf") value[tab] += r.currentValue ?? 0;
  }
  for (const t of tiles) {
    if (t.assetType === "equity") value.stocks += t.valueRs;
    if (t.assetType === "gold" || t.assetType === "sgb") value.sgb += t.valueRs;
  }
  const total = value.mf + value.stocks + value.etf + value.sgb;
  return ASSET_TABS.flatMap((t): CompositionSlice[] => {
    if (t.id === "all" || value[t.id] <= 0) return [];
    return [{ tab: t.id, label: t.label, valueRs: value[t.id], pct: Math.round((value[t.id] / total) * 100) }];
  });
}

function tileToRating(t: HeatmapTile, withStockDetail: boolean): FundRating {
  return {
    name: t.name,
    ticker: withStockDetail ? t.ticker : "",
    sector: withStockDetail ? t.sector : "",
    invested: t.investedRs,
    currentValue: t.valueRs,
    simpleReturnPct: t.returnPct,
    return1m: null, return3m: null, return1y: null, return3y: null, xirrPct: null, alpha: null,
    rating: "no_data",
    schemeCategory: "",
    schemeCode: "",
    assetType: t.assetType,
    benchmarkReturn: null,
    benchmarkName: "",
    categoryRank: null, categoryTotal: null, categoryRankPct: null,
    qualityScore: withStockDetail ? t.qualityScore : null,
    sectorRank: withStockDetail ? t.sectorRank : null,
    sectorTotal: withStockDetail ? t.sectorTotal : null,
  };
}

const isGoldTile = (t: HeatmapTile): boolean => t.assetType === "gold" || t.assetType === "sgb";

export interface DrillRows {
  rows: FundRating[];
  /** Folio rows merged into those; 0 on the Stocks and SGB tabs. */
  mergedFolios: number;
  /** Folio rows before merging. */
  folios: number;
}

/** The holdings behind one tab. Copy of `drillData` in HoldingsCompositionPie(). */
export function drillRows(ratings: FundRating[], tiles: HeatmapTile[], tab: AssetTab): DrillRows {
  if (tab === "stocks") return { rows: tiles.filter((t) => t.assetType === "equity").map((t) => tileToRating(t, true)), mergedFolios: 0, folios: 0 };
  if (tab === "sgb") return { rows: tiles.filter(isGoldTile).map((t) => tileToRating(t, false)), mergedFolios: 0, folios: 0 };
  const tabRatings = filterByTab(ratings, tab);
  const rows = consolidateByName(tabRatings);
  return { rows, mergedFolios: tabRatings.length - rows.length, folios: tabRatings.length };
}

export type DrillSort = "return" | "invested" | "name";

export const DRILL_SORTS: Array<{ id: DrillSort; label: string }> = [
  { id: "return", label: "By Return" },
  { id: "invested", label: "By Invested" },
  { id: "name", label: "By Name" },
];

/** Copy of the sort in HoldingsCompositionPie(); a row with no return sorts last. */
export function sortRows(rows: FundRating[], key: DrillSort): FundRating[] {
  return [...rows].sort((a, b) => {
    if (key === "return") return (b.simpleReturnPct ?? -Infinity) - (a.simpleReturnPct ?? -Infinity);
    if (key === "invested") return (b.invested ?? 0) - (a.invested ?? 0);
    return a.name.localeCompare(b.name);
  });
}

/** The holding behind a name the user picked: the merged fund row first, then a heatmap tile. */
export function findHolding(name: string, ratings: FundRating[], tiles: HeatmapTile[]): FundRating | null {
  const fund = consolidateByName(ratings).find((r) => r.name === name);
  if (fund) return fund;
  const tile = tiles.find((t) => t.name === name);
  return tile ? tileToRating(tile, true) : null;
}

// ── direct stocks: sector and company split (Stocks tab) ─────────────────

export interface ValueShare {
  name: string;
  valueRs: number;
  /** Whole percent of the direct-equity tiles. */
  pct: number;
  returnPct: number | null;
}

/** Copy of SectorAllocationPie(): direct-equity value by sector, largest first. */
export function sectorAllocation(tiles: HeatmapTile[]): ValueShare[] {
  const bySector = new Map<string, number>();
  for (const t of tiles) {
    if (t.assetType !== "equity") continue;
    const sector = t.sector || "Other";
    bySector.set(sector, (bySector.get(sector) ?? 0) + t.valueRs);
  }
  const total = [...bySector.values()].reduce((s, v) => s + v, 0);
  return [...bySector.entries()]
    .sort((a, b) => b[1] - a[1])
    .map(([name, valueRs]) => ({ name, valueRs, pct: total > 0 ? Math.round((valueRs / total) * 100) : 0, returnPct: null }));
}

export interface CompanyAllocation {
  /** Direct stocks among the tiles. */
  count: number;
  /** The eight largest. */
  top: ValueShare[];
  restCount: number;
  restValueRs: number;
}

/** Copy of CompanyAllocationPie(): the eight largest direct stocks, then the rest as one figure. */
export function companyAllocation(tiles: HeatmapTile[]): CompanyAllocation {
  const equity = tiles.filter((t) => t.assetType === "equity").sort((a, b) => b.valueRs - a.valueRs);
  const total = equity.reduce((s, t) => s + t.valueRs, 0);
  const rest = equity.slice(8);
  return {
    count: equity.length,
    top: equity.slice(0, 8).map((t) => ({ name: t.name, valueRs: t.valueRs, pct: total > 0 ? Math.round((t.valueRs / total) * 100) : 0, returnPct: t.returnPct })),
    restCount: rest.length,
    restValueRs: rest.reduce((s, t) => s + t.valueRs, 0),
  };
}

// ── gain / loss distribution ─────────────────────────────────────────────

export interface ScatterPoint {
  name: string;
  investedRs: number;
  returnPct: number;
  valueRs: number;
}

// The tile's asset_type for each tab. The old page compares it with the tab id
// itself, which never matches "mutual_fund", so its MF tab is always empty.
const TILE_TYPES: Record<Exclude<AssetTab, "all">, string[]> = { mf: ["mutual_fund"], stocks: ["equity"], etf: ["etf"], sgb: ["gold"] };

/** Copy of the points GainLossDistribution() plots: holdings with a cost basis and a return. */
export function scatterPoints(tiles: HeatmapTile[], tab: AssetTab): ScatterPoint[] {
  return tiles.flatMap((t): ScatterPoint[] => {
    if (tab !== "all" && !TILE_TYPES[tab].includes(t.assetType)) return [];
    if (t.investedRs == null || t.investedRs <= 0 || t.returnPct == null) return [];
    return [{ name: t.name, investedRs: t.investedRs, returnPct: t.returnPct, valueRs: Math.max(t.valueRs, 1) }];
  });
}

// ── per-holding recommendations (GET /api/portfolio/recommendations/v5) ──

export interface HoldingRec {
  name: string;
  /** Engine verdict, upper case: BUY_MORE, HOLD, EXIT, SWITCH, REVIEW. */
  action: string;
  reason: string;
  qualityScore: number | null;
  healthScore: number | null;
  category: string;
  categoryRank: number | null;
  categoryTotal: number | null;
  categoryRankPct: number | null;
}

export interface HoldingRecs {
  /** Every holding the engine has a view on. */
  holdings: HoldingRec[];
  /** Up to five per asset class: mutual_fund, equity, etf, gold. */
  top5: Record<string, HoldingRec[]>;
}

function toRec(raw: unknown): HoldingRec[] {
  const r = rec(raw);
  const name = str(r?.name);
  if (!r || !name) return [];
  return [{
    name,
    action: str(r.action).toUpperCase(),
    reason: str(r.reason),
    qualityScore: num(r.quality_score),
    healthScore: num(r.health_score),
    category: str(r.category),
    categoryRank: num(r.category_rank),
    categoryTotal: num(r.category_total),
    categoryRankPct: num(r.category_rank_pct),
  }];
}

export async function fetchHoldingRecs(signal?: AbortSignal): Promise<HoldingRecs> {
  const data = rec((await http({ path: "/api/portfolio/recommendations/v5", signal })).data);
  const top5 = rec(data?.top5_by_asset_class);
  if (!data || !top5) throw ApiError.contractDrift("portfolio.recommendationsV5: missing `top5_by_asset_class`");
  return {
    holdings: list(data.holdings).flatMap(toRec),
    top5: Object.fromEntries(Object.entries(top5).map(([k, v]) => [k, list(v).flatMap(toRec)])),
  };
}

export function useHoldingRecs() {
  return useQuery<HoldingRecs>({
    queryKey: ["portfolio", "recommendations-v5"],
    staleTime: 10 * 60_000,
    queryFn: ({ signal }) => fetchHoldingRecs(signal),
  });
}

const ACTION_META: Record<string, { label: string; tone: Tone }> = {
  BUY_MORE: { label: "Add", tone: "mint" },
  HOLD: { label: "Hold", tone: "ink" },
  EXIT: { label: "Exit", tone: "danger" },
  SWITCH: { label: "Switch", tone: "amber" },
  REVIEW: { label: "Review", tone: "amber" },
};

/** Copy of ACTION_STYLES; an action it does not name keeps its own name instead of reading "Hold". */
export function actionMeta(action: string): { label: string; tone: Tone } {
  return ACTION_META[action] ?? { label: humanise(action) || "—", tone: "ink" };
}

const TAB_CLASS: Record<Exclude<AssetTab, "all">, string> = { mf: "mutual_fund", stocks: "equity", etf: "etf", sgb: "gold" };
const ACTION_RANK: Record<string, number> = { BUY_MORE: 0, EXIT: 1, SWITCH: 2, REVIEW: 3, HOLD: 4 };

/** Copy of `allRecs` in RecommendationsPanel(): the class's five, or the five most actionable across classes. */
export function recsForTab(recs: HoldingRecs, tab: AssetTab): HoldingRec[] {
  if (tab !== "all") return recs.top5[TAB_CLASS[tab]] ?? [];
  return Object.values(recs.top5).flat().sort((a, b) => (ACTION_RANK[a.action] ?? 9) - (ACTION_RANK[b.action] ?? 9)).slice(0, 5);
}

/** The old page's own note on how the quality score is built, verbatim. */
export const QUALITY_SCORE_EXPLANATION =
  "NIDP quality score (0–100) combines: expense ratio vs peers, rolling alpha (3Y), fund manager tenure, AUM stability, and category peer percentile rank. Score ≥70 = strong · 45–70 = neutral · <45 = weak.";

/** Copy of qsColor(): 70 and above strong, 45 and above neutral, below that weak. */
export function scoreTone(score: number | null): Tone {
  if (score == null) return "ink";
  if (score >= 70) return "mint";
  return score >= 45 ? "amber" : "danger";
}

// ── category leaders (GET /api/mf/category-top) ──────────────────────────

export interface CategoryPeer {
  schemeCode: string;
  schemeName: string;
  rank: number | null;
  ret1y: number | null;
  ret3y: number | null;
  /** NIDP composite score, 0–100. */
  composite: number | null;
}

export interface CategoryTop {
  rankDate: string;
  funds: CategoryPeer[];
}

export async function fetchCategoryTop(category: string, signal?: AbortSignal): Promise<CategoryTop> {
  const data = rec((await http({ path: "/api/mf/category-top", query: { category, n: 5 }, signal })).data);
  if (!data || !Array.isArray(data.funds)) throw ApiError.contractDrift("mf.categoryTop: missing `funds`");
  return {
    rankDate: str(data.rank_date),
    funds: data.funds.flatMap((f: unknown): CategoryPeer[] => {
      const r = rec(f);
      const schemeName = str(r?.scheme_name);
      if (!r || !schemeName) return [];
      return [{ schemeCode: code(r.scheme_code), schemeName, rank: num(r.category_rank), ret1y: num(r.ret_1y), ret3y: num(r.ret_3y), composite: num(r.composite) }];
    }),
  };
}

/** The five best-ranked funds of a SEBI category. Off until `enabled`, as on the old page (a ranked fund is open). */
export function useCategoryTop(category: string, enabled: boolean) {
  return useQuery<CategoryTop>({
    queryKey: ["mf", "category-top", category],
    enabled: enabled && category !== "",
    staleTime: 5 * 60_000,
    queryFn: ({ signal }) => fetchCategoryTop(category, signal),
  });
}
