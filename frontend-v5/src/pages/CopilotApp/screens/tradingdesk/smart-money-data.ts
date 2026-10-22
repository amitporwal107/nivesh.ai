/**
 * Smart trading desk · Smart Money Movement — the screen's data.
 *
 *   GET /api/markets/smart-money/feeds            each feed's status, and the newest DATA period as
 *                                                 distinct from the last ingest run (they differ by weeks)
 *   GET /api/markets/smart-money/flows?window=    FII/DII cash net + cumulative; 1M/3M/6M daily, 1Y monthly
 *   GET /api/markets/smart-money/sectors          disclosed MF holdings change by industry, valued at VWAP
 *   GET /api/markets/smart-money/breadth          how many names carry disclosed vs proxy-only evidence
 *   GET /api/markets/smart-money/scanner          one row per Nifty 500 stock: the evidence behind it
 *
 * All five forward to the data platform (backend/routes/markets_smart_money.py ->
 * nidp/services/daas_api/routers/smart_money.py). Every figure, source and as-of date is the platform's;
 * this module parses and derives, and invents nothing.
 *
 * What this screen deliberately does NOT have, because the data does not support it:
 *   * No accumulation score, and no ranking by one. The validation study
 *     (NIDP-SM-VALIDATION-001/002) returned INCONCLUSIVE: its own frozen promotion rule needs a
 *     confidence-interval lower bound above zero and a point estimate >= +1.0 pp, and the measured
 *     values are 0.0000 and +0.2189 pp. `breadth.validatedStudy` is the live read of whether any
 *     promotion was ever approved; it is false.
 *   * No hit rate or "historical market reaction" number. None exists anywhere in the warehouse.
 *     The screen prints "no validated study available" instead, which is the honest alternative.
 *   * Nothing from nidp.v_smart_money_shadow_rank, whose rank is computed over a duplicated
 *     population and whose shadow_score falls back to the plain v3 score when a symbol has no
 *     smart-money row at all.
 *   * No A/B/C/D chip read from a stored evidence_class: that column is a hardcoded constant.
 *     `evidenceOf()` below derives the class from which sources actually answered for the row.
 *
 * House rule on partial failure: SOME sources failing is ready-with-a-banner, not an error. Only a
 * total failure is an error state, so one dead feed never blanks a screen that has four live ones.
 */
import { useQuery } from "@tanstack/react-query";
import { http } from "@/services/api/http";
import { ApiError } from "@/services/api/errors";
import { num } from "./desk-data";

type Raw = Record<string, unknown>;
const rec = (v: unknown): Raw => (v && typeof v === "object" && !Array.isArray(v) ? (v as Raw) : {});
const str = (v: unknown): string | null => (typeof v === "string" && v.trim() ? v.trim() : null);
const bool = (v: unknown): boolean | null => (typeof v === "boolean" ? v : null);

/** A contract drift or any 4xx is the server's settled answer: asking again changes nothing. */
const noRetry4xx = (count: number, e: unknown) =>
  !(e instanceof ApiError && (e.kind === "contract_drift" || (e.status != null && e.status >= 400 && e.status < 500))) && count < 1;

export type SourceState = "ok" | "failed" | "loading";
export type SmSourceKey = "feeds" | "flows" | "sectors" | "breadth" | "scanner";

// ── feeds (GET /api/markets/smart-money/feeds) ───────────────────────────

export interface FeedStrip {
  feed: string;
  sourceName: string | null;
  table: string | null;
  status: string | null;
  expectedFreq: string | null;
  stalenessDays: number | null;
  stalenessBudgetDays: number | null;
  lastSuccess: string | null;
  /** When the loader last ran. NOT the data's date — see `dataAsOf`. */
  ingestedFor: string | null;
  /** max() of the real date column in the underlying table: the honest "as of". */
  dataAsOf: string | null;
  statusRowPresent: boolean;
}

export interface FeedsFeed {
  source: string | null;
  disclosure: string | null;
  rows: FeedStrip[];
}

/** True when the loader ran later than the data it carries — i.e. the strip must not print one date. */
export function ingestAheadOfData(s: FeedStrip): boolean {
  return !!s.ingestedFor && !!s.dataAsOf && s.ingestedFor > s.dataAsOf;
}

/** Whole days between the newest data period and `today`, or null when either is unknown. */
export function dataAgeDays(dataAsOf: string | null, today: Date): number | null {
  if (!dataAsOf) return null;
  const t = Date.parse(`${dataAsOf}T00:00:00Z`);
  if (Number.isNaN(t)) return null;
  const now = Date.UTC(today.getUTCFullYear(), today.getUTCMonth(), today.getUTCDate());
  return Math.max(0, Math.round((now - t) / 86_400_000));
}

async function fetchFeeds(signal?: AbortSignal): Promise<FeedsFeed> {
  const res = await http({ path: "/api/markets/smart-money/feeds", signal });
  const d = rec(res.data);
  if (!Array.isArray(d.rows)) throw ApiError.contractDrift("smart-money.feeds: no rows list");
  const rows: FeedStrip[] = d.rows.flatMap((v): FeedStrip[] => {
    const r = rec(v);
    const feed = str(r.feed);
    if (!feed) return [];
    return [{
      feed,
      sourceName: str(r.source_name),
      table: str(r.table),
      status: str(r.status),
      expectedFreq: str(r.expected_freq),
      stalenessDays: num(r.staleness_days),
      stalenessBudgetDays: num(r.staleness_budget_days),
      lastSuccess: str(r.last_success),
      ingestedFor: str(r.ingested_for),
      dataAsOf: str(r.data_as_of),
      statusRowPresent: bool(r.status_row_present) ?? false,
    }];
  });
  return { source: str(d.source), disclosure: str(d.disclosure), rows };
}

export function useSmFeeds(enabled: boolean) {
  return useQuery<FeedsFeed>({
    queryKey: ["copilot", "desk", "smart-money", "feeds"],
    enabled, staleTime: 15 * 60_000, retry: noRetry4xx,
    queryFn: ({ signal }) => fetchFeeds(signal),
  });
}

// ── flows (GET /api/markets/smart-money/flows) ───────────────────────────

export const FLOW_WINDOWS = ["1M", "3M", "6M", "1Y"] as const;
export type FlowWindow = (typeof FLOW_WINDOWS)[number];

export interface FlowPoint {
  date: string;
  fiiNetCr: number | null;
  diiNetCr: number | null;
  fiiCumCr: number | null;
  diiCumCr: number | null;
}

export interface FlowsFeed {
  asOf: string | null;
  start: string | null;
  window: string | null;
  /** "daily" or "monthly". 1Y is monthly because the daily series only begins 2026-04-01. */
  grain: string | null;
  source: string | null;
  disclosure: string | null;
  /** The window's net, i.e. the last cumulative point. Null on an empty window. */
  fiiNetCr: number | null;
  diiNetCr: number | null;
  rows: FlowPoint[];
}

async function fetchFlows(window: FlowWindow, signal?: AbortSignal): Promise<FlowsFeed> {
  const res = await http({ path: "/api/markets/smart-money/flows", query: { window }, signal });
  const d = rec(res.data);
  if (!Array.isArray(d.rows)) throw ApiError.contractDrift("smart-money.flows: no rows list");
  const rows: FlowPoint[] = d.rows.flatMap((v): FlowPoint[] => {
    const r = rec(v);
    const date = str(r.date);
    if (!date) return [];
    return [{
      date,
      fiiNetCr: num(r.fii_net_cr), diiNetCr: num(r.dii_net_cr),
      fiiCumCr: num(r.fii_cum_cr), diiCumCr: num(r.dii_cum_cr),
    }];
  });
  return {
    asOf: str(d.as_of), start: str(d.start), window: str(d.window), grain: str(d.grain),
    source: str(d.source), disclosure: str(d.disclosure),
    fiiNetCr: num(d.fii_net_cr), diiNetCr: num(d.dii_net_cr), rows,
  };
}

export function useSmFlows(enabled: boolean, window: FlowWindow) {
  return useQuery<FlowsFeed>({
    queryKey: ["copilot", "desk", "smart-money", "flows", window],
    enabled, staleTime: 10 * 60_000, retry: noRetry4xx,
    queryFn: ({ signal }) => fetchFlows(window, signal),
  });
}

// ── sectors (GET /api/markets/smart-money/sectors) ───────────────────────

export interface SectorRow {
  industry: string;
  stocks: number | null;
  stocksPriced: number | null;
  netValueCr: number | null;
  schemesUp: number | null;
  schemesDn: number | null;
}

export interface SectorsFeed {
  asOf: string | null;
  previousMonth: string | null;
  source: string | null;
  disclosure: string | null;
  rows: SectorRow[];
}

async function fetchSectors(signal?: AbortSignal): Promise<SectorsFeed> {
  const res = await http({ path: "/api/markets/smart-money/sectors", signal });
  const d = rec(res.data);
  if (!Array.isArray(d.rows)) throw ApiError.contractDrift("smart-money.sectors: no rows list");
  const rows: SectorRow[] = d.rows.flatMap((v): SectorRow[] => {
    const r = rec(v);
    const industry = str(r.industry);
    if (!industry) return [];
    return [{
      industry,
      stocks: num(r.stocks), stocksPriced: num(r.stocks_priced), netValueCr: num(r.net_value_cr),
      schemesUp: num(r.schemes_up), schemesDn: num(r.schemes_dn),
    }];
  });
  return {
    asOf: str(d.as_of), previousMonth: str(d.previous_month),
    source: str(d.source), disclosure: str(d.disclosure), rows,
  };
}

export function useSmSectors(enabled: boolean) {
  return useQuery<SectorsFeed>({
    queryKey: ["copilot", "desk", "smart-money", "sectors"],
    enabled, staleTime: 30 * 60_000, retry: noRetry4xx,
    queryFn: ({ signal }) => fetchSectors(signal),
  });
}

// ── breadth (GET /api/markets/smart-money/breadth) ───────────────────────

export interface BreadthMetrics {
  evaluated: number | null;
  disclosedRising: number | null;
  disclosedFalling: number | null;
  risingDirectAndProxy: number | null;
  risingDirectOnly: number | null;
  proxyOnly: number | null;
  singleAmc: number | null;
  fresh: number | null;
  ageing: number | null;
  stale: number | null;
}

export interface BreadthFeed {
  asOf: string | null;
  /** The newest underlying disclosure. Weeks behind `asOf` by construction — show this one. */
  disclosureAsOf: string | null;
  /** Live read of whether any promotion was ever approved. False today; gates every score claim. */
  validatedStudy: boolean;
  source: string | null;
  disclosure: string | null;
  metrics: BreadthMetrics | null;
}

async function fetchBreadth(signal?: AbortSignal): Promise<BreadthFeed> {
  const res = await http({ path: "/api/markets/smart-money/breadth", signal });
  const d = rec(res.data);
  if (!("validated_study" in d)) throw ApiError.contractDrift("smart-money.breadth: no validated_study flag");
  const m = d.metrics == null ? null : rec(d.metrics);
  return {
    asOf: str(d.as_of), disclosureAsOf: str(d.disclosure_as_of),
    validatedStudy: bool(d.validated_study) ?? false,
    source: str(d.source), disclosure: str(d.disclosure),
    metrics: m && {
      evaluated: num(m.evaluated),
      disclosedRising: num(m.disclosed_rising),
      disclosedFalling: num(m.disclosed_falling),
      risingDirectAndProxy: num(m.rising_direct_and_proxy),
      risingDirectOnly: num(m.rising_direct_only),
      proxyOnly: num(m.proxy_only),
      singleAmc: num(m.single_amc),
      fresh: num(m.fresh), ageing: num(m.ageing), stale: num(m.stale),
    },
  };
}

export function useSmBreadth(enabled: boolean) {
  return useQuery<BreadthFeed>({
    queryKey: ["copilot", "desk", "smart-money", "breadth"],
    enabled, staleTime: 15 * 60_000, retry: noRetry4xx,
    queryFn: ({ signal }) => fetchBreadth(signal),
  });
}

// ── scanner (GET /api/markets/smart-money/scanner) ───────────────────────

export interface ScannerRow {
  symbol: string;
  industry: string | null;
  mfSharesPctChg: number | null;
  netSharesDelta: number | null;
  schemesUp: number | null;
  schemesDn: number | null;
  amcsUp: number | null;
  fiiDeltaPp: number | null;
  diiDeltaPp: number | null;
  dealNetQty: number | null;
  dealGrossInr: number | null;
  dealDays: number | null;
  /** Days in the window where every leg paired off: an ownership transfer, no net demand. */
  transferDays: number | null;
  /** False = this symbol was never queried for deals. Not the same as "no deals". */
  dealsChecked: boolean;
  deliv10d: number | null;
  deliv60d: number | null;
  delivVsBasePp: number | null;
}

export interface ScannerFeed {
  asOf: string | null;
  previousMonth: string | null;
  quarters: { current: string | null; previous: string | null } | null;
  dealWindow: { from: string | null; to: string | null } | null;
  source: string | null;
  disclosure: string | null;
  rows: ScannerRow[];
}

/**
 * Evidence class, derived from which sources answered for this row — never read from a stored
 * column, because the stored `evidence_class` is a hardcoded constant.
 *
 *   A  a disclosed holdings change (an AMC's own filing)
 *   B  a disclosed deal leg that survived transfer-netting
 *   D  A and B together
 *   C  a market proxy only: delivery moved, the buyer is unknown — never called accumulation
 *   —  nothing answered for this row
 */
export type EvidenceClass = "A" | "B" | "C" | "D" | "none";

export function evidenceOf(r: ScannerRow): EvidenceClass {
  const disclosed = r.netSharesDelta != null && r.netSharesDelta !== 0;
  // A transfer-only day is not demand, so it is not class-B evidence.
  const dealt = r.dealNetQty != null && r.dealNetQty !== 0;
  const proxy = r.delivVsBasePp != null;
  if (disclosed && dealt) return "D";
  if (disclosed) return "A";
  if (dealt) return "B";
  if (proxy) return "C";
  return "none";
}

export const EVIDENCE_LABEL: Record<EvidenceClass, string> = {
  A: "Disclosed holdings",
  B: "Disclosed deal",
  C: "Market proxy only",
  D: "Disclosed + deal",
  none: "Nothing on record",
};

export const EVIDENCE_NOTE: Record<EvidenceClass, string> = {
  A: "An AMC's own monthly filing shows the holding changed.",
  B: "A bulk or block deal leg that was not a matched same-day transfer.",
  C: "Delivery moved against its own baseline. The buyer is not disclosed, so this is not accumulation.",
  D: "A disclosed holdings change and a disclosed deal leg point the same way.",
  none: "No disclosed change, no deal leg and no proxy move for this name.",
};

async function fetchScanner(p: { rising: boolean; dealDays: number; limit: number }, signal?: AbortSignal): Promise<ScannerFeed> {
  const res = await http({
    path: "/api/markets/smart-money/scanner",
    query: { rising_only: p.rising, deal_days: p.dealDays, limit: p.limit },
    signal,
  });
  const d = rec(res.data);
  if (!Array.isArray(d.rows)) throw ApiError.contractDrift("smart-money.scanner: no rows list");
  const rows: ScannerRow[] = d.rows.flatMap((v): ScannerRow[] => {
    const r = rec(v);
    const symbol = str(r.symbol)?.toUpperCase();
    if (!symbol) return [];
    return [{
      symbol,
      industry: str(r.industry),
      mfSharesPctChg: num(r.mf_shares_pct_chg),
      netSharesDelta: num(r.net_shares_delta),
      schemesUp: num(r.schemes_up), schemesDn: num(r.schemes_dn), amcsUp: num(r.amcs_up),
      fiiDeltaPp: num(r.fii_delta_pp), diiDeltaPp: num(r.dii_delta_pp),
      dealNetQty: num(r.deal_net_qty), dealGrossInr: num(r.deal_gross_inr),
      dealDays: num(r.deal_days), transferDays: num(r.transfer_days),
      dealsChecked: bool(r.deals_checked) ?? false,
      deliv10d: num(r.deliv_10d), deliv60d: num(r.deliv_60d), delivVsBasePp: num(r.deliv_vs_base_pp),
    }];
  });
  const q = rec(d.quarters);
  const w = rec(d.deal_window);
  return {
    asOf: str(d.as_of), previousMonth: str(d.previous_month),
    quarters: d.quarters == null ? null : { current: str(q.current), previous: str(q.previous) },
    dealWindow: d.deal_window == null ? null : { from: str(w.from), to: str(w.to) },
    source: str(d.source), disclosure: str(d.disclosure), rows,
  };
}

export const SCANNER_LIMIT = 100;
export const SCANNER_DEAL_DAYS = 90;

export function useSmScanner(enabled: boolean, rising: boolean) {
  return useQuery<ScannerFeed>({
    queryKey: ["copilot", "desk", "smart-money", "scanner", rising],
    enabled, staleTime: 15 * 60_000, retry: noRetry4xx,
    queryFn: ({ signal }) => fetchScanner({ rising, dealDays: SCANNER_DEAL_DAYS, limit: SCANNER_LIMIT }, signal),
  });
}

// ── the one feed the screen reads ────────────────────────────────────────

export interface SmartMoneyFeed {
  status: "loading" | "error" | "ready";
  feeds: FeedsFeed | null;
  flows: FlowsFeed | null;
  sectors: SectorsFeed | null;
  breadth: BreadthFeed | null;
  scanner: ScannerFeed | null;
  /** Sources that failed while others answered: the screen is partial and says so. */
  failed: SmSourceKey[];
  sourceStates: Partial<Record<SmSourceKey, SourceState>>;
  error: unknown;
  refetch: () => void;
}

/**
 * Fans out the five reads and collapses them into one object. Partial failure stays "ready" with
 * `failed` populated — a dead feed costs its own panel, not the screen.
 */
export function useSmartMoney(window: FlowWindow, rising: boolean): SmartMoneyFeed {
  const feeds = useSmFeeds(true);
  const flows = useSmFlows(true, window);
  const sectors = useSmSectors(true);
  const breadth = useSmBreadth(true);
  const scanner = useSmScanner(true, rising);

  const parts: Array<{ key: SmSourceKey; pending: boolean; failed: boolean; error: unknown; refetch: () => void }> = [
    { key: "feeds", pending: feeds.isPending, failed: feeds.isError, error: feeds.error, refetch: () => void feeds.refetch() },
    { key: "flows", pending: flows.isPending, failed: flows.isError, error: flows.error, refetch: () => void flows.refetch() },
    { key: "sectors", pending: sectors.isPending, failed: sectors.isError, error: sectors.error, refetch: () => void sectors.refetch() },
    { key: "breadth", pending: breadth.isPending, failed: breadth.isError, error: breadth.error, refetch: () => void breadth.refetch() },
    { key: "scanner", pending: scanner.isPending, failed: scanner.isError, error: scanner.error, refetch: () => void scanner.refetch() },
  ];

  const sourceStates: Partial<Record<SmSourceKey, SourceState>> = {};
  for (const p of parts) sourceStates[p.key] = p.failed ? "failed" : p.pending ? "loading" : "ok";
  const failedParts = parts.filter((p) => p.failed);
  const refetch = () => { for (const p of parts) if (p.failed) p.refetch(); };

  const base = {
    feeds: feeds.data ?? null, flows: flows.data ?? null, sectors: sectors.data ?? null,
    breadth: breadth.data ?? null, scanner: scanner.data ?? null,
    failed: [...new Set(failedParts.map((p) => p.key))], sourceStates, refetch,
  };
  if (failedParts.length === parts.length) return { status: "error", ...base, error: failedParts[0].error };
  if (parts.some((p) => p.pending)) return { status: "loading", ...base, failed: [], error: null };
  return { status: "ready", ...base, error: failedParts[0]?.error ?? null };
}
