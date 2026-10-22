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

/**
 * The design's period toggle (spec 2.1). One control, every panel recomputes — except the MF
 * holdings leg, which cannot: only a one-month disclosure pair exists in the warehouse. The server
 * reports `mfWindow.actualMonths` against `requestedMonths` so the column states its own window
 * instead of implying it moved. See `mfWindowNote()`.
 */
export const SM_PERIODS = ["1M", "3M", "6M", "1Y"] as const;
export type SmPeriod = (typeof SM_PERIODS)[number];
/** Kept as an alias: the flows panel reads the same toggle. */
export type FlowWindow = SmPeriod;
export const FLOW_WINDOWS = SM_PERIODS;

/**
 * Universes that exist as real constituent lists. The design offered "Nifty 1000", which NSE does
 * not publish and this warehouse does not hold; Nifty Total Market (755 names) is the nearest real
 * list and is offered under its own name rather than a label implying 1,000.
 */
export const SM_UNIVERSES = [
  { id: "nifty50", label: "Nifty 50" },
  { id: "nifty100", label: "Nifty 100" },
  { id: "nifty200", label: "Nifty 200" },
  { id: "nifty500", label: "Nifty 500" },
  { id: "total", label: "Nifty Total Market" },
] as const;
export type SmUniverse = (typeof SM_UNIVERSES)[number]["id"];

export const SM_DIRECTIONS = ["all", "accumulation", "distribution"] as const;
export type SmDirection = (typeof SM_DIRECTIONS)[number];
export const SM_LANES = ["all", "disclosed", "proxy"] as const;
export type SmLane = (typeof SM_LANES)[number];
export const SM_FRESHNESS = ["any", "fresh", "ageing", "stale"] as const;
export type SmFreshness = (typeof SM_FRESHNESS)[number];

/** Which disclosure window the server actually served, in words, or null when it matched. */
export interface MfWindow {
  requestedMonths: number | null;
  actualMonths: number | null;
  exact: boolean;
}

export function mfWindowNote(w: MfWindow | null): string | null {
  if (!w || w.exact || w.actualMonths == null || w.requestedMonths == null) return null;
  const m = w.actualMonths === 1 ? "1 month" : `${w.actualMonths} months`;
  return `Holdings change is over ${m} — a ${w.requestedMonths}-month disclosure pair is not published.`;
}

const mfWin = (v: unknown): MfWindow | null => {
  if (v == null) return null;
  const r = rec(v);
  return { requestedMonths: num(r.requested_months), actualMonths: num(r.actual_months), exact: bool(r.exact) ?? false };
};

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

/** Net over the last `n` points of the series, or null when the window is shorter than n. */
export function rollingNet(rows: FlowPoint[], n: number, key: "fiiNetCr" | "diiNetCr"): number | null {
  if (rows.length < n) return null;
  let t = 0;
  for (const r of rows.slice(-n)) {
    const v = r[key];
    if (v == null) return null;
    t += v;
  }
  return t;
}

/**
 * A one-line reading of the window, derived from the two net figures by fixed rules — not a model
 * output and not a forecast. It restates the arithmetic in words; nothing else.
 *
 * Deliberately COMPARATIVE, never causal. An earlier version said domestic institutions "absorbed"
 * the foreign selling, which claims the two sides traded the same securities. These are two
 * market-wide cash totals: nothing in this feed matches a buyer to a seller, or one stock to
 * another. `FLOW_CAVEAT` ships beside the line to say so.
 */
export function flowRegime(fii: number | null, dii: number | null): string | null {
  if (fii == null || dii == null) return null;
  const bigger = Math.abs(fii) >= Math.abs(dii) ? "foreign" : "domestic";
  if (fii < 0 && dii > 0) {
    return `Foreign institutions were net sellers and domestic institutions net buyers; the ${bigger} figure was the larger of the two.`;
  }
  if (fii > 0 && dii < 0) {
    return `Foreign institutions were net buyers and domestic institutions net sellers; the ${bigger} figure was the larger of the two.`;
  }
  if (fii > 0 && dii > 0) return "Both foreign and domestic institutions were net buyers over this window.";
  if (fii < 0 && dii < 0) return "Both foreign and domestic institutions were net sellers over this window.";
  return "Net flows were flat over this window.";
}

/** Ships beside the regime line: the two totals are not matched trades. */
export const FLOW_CAVEAT =
  "These are two market-wide cash totals for the same window. Nothing here matches a buyer to a seller " +
  "or one stock to another, so a larger figure on one side is not evidence it absorbed the other.";

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
  window: string | null;
  indexName: string | null;
  /** Which disclosure window was actually served, vs the one the period chip asked for. */
  mfWindow: MfWindow | null;
  source: string | null;
  disclosure: string | null;
  rows: SectorRow[];
}

/** The three measures the design offers for the diverging bars (spec 2.4). */
export const SECTOR_MEASURES = [
  { id: "cr", label: "\u20b9 Cr" },
  { id: "pct", label: "% of total" },
  { id: "stocks", label: "# stocks" },
] as const;
export type SectorMeasure = (typeof SECTOR_MEASURES)[number]["id"];

/**
 * The value a bar should draw for the chosen measure. "% of total" is share of the summed
 * ABSOLUTE net across sectors, so a sector that bought and one that sold both read as a share of
 * the period's gross disclosed movement rather than cancelling out to a meaningless denominator.
 */
export function sectorValue(r: SectorRow, m: SectorMeasure, grossCr: number): number | null {
  if (m === "stocks") return r.stocks;
  if (m === "cr") return r.netValueCr;
  if (r.netValueCr == null || grossCr <= 0) return null;
  return (r.netValueCr / grossCr) * 100;
}

export function sectorGrossCr(rows: SectorRow[]): number {
  return rows.reduce((t, r) => t + Math.abs(r.netValueCr ?? 0), 0);
}

/**
 * The reconciliation a reader needs to check the ranking by hand: what was added, what was reduced
 * and what the two come to. Without it a bar chart of signed values cannot be verified at all.
 */
export function sectorTotals(rows: SectorRow[]): { added: number; reduced: number; net: number; sectors: number } {
  let added = 0, reduced = 0;
  for (const r of rows) {
    const v = r.netValueCr;
    if (v == null) continue;
    if (v > 0) added += v; else reduced += -v;
  }
  return { added, reduced, net: added - reduced, sectors: rows.length };
}

async function fetchSectors(p: { window: SmPeriod; universe: SmUniverse }, signal?: AbortSignal): Promise<SectorsFeed> {
  const res = await http({ path: "/api/markets/smart-money/sectors", query: { window: p.window, universe: p.universe }, signal });
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
    asOf: str(d.as_of), previousMonth: str(d.previous_month), window: str(d.window),
    indexName: str(d.index_name), mfWindow: mfWin(d.mf_window),
    source: str(d.source), disclosure: str(d.disclosure), rows,
  };
}

export function useSmSectors(enabled: boolean, window: SmPeriod, universe: SmUniverse) {
  return useQuery<SectorsFeed>({
    queryKey: ["copilot", "desk", "smart-money", "sectors", window, universe],
    enabled, staleTime: 30 * 60_000, retry: noRetry4xx,
    queryFn: ({ signal }) => fetchSectors({ window, universe }, signal),
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
  /** Disclosed legs in the window, and how many of them paired off as transfers. */
  dealLegs: number | null;
  matchedLegs: number | null;
  dealDays: number | null;
  transferDays: number | null;
  /** False = never queried for deals. Not the same as "no deals". */
  dealsChecked: boolean;
  deliv10d: number | null;
  deliv60d: number | null;
  delivVsBasePp: number | null;
  closePrice: number | null;
  prevClose: number | null;
  changePct: number | null;
  /** "fresh" | "ageing" | "stale" — how old the disclosure behind this row is. */
  freshnessStatus: string | null;
  /** True when the whole signal rests on one fund house: weaker evidence, shown as a badge. */
  singleAmcSignal: boolean | null;
  latestReportingDate: string | null;
  /** Derived server-side from which sources answered — never read from the stored constant. */
  evidence: EvidenceClass;
}

export interface ScannerFeed {
  asOf: string | null;
  previousMonth: string | null;
  window: string | null;
  indexName: string | null;
  mfWindow: MfWindow | null;
  quarters: { current: string | null; previous: string | null; requestedBack: number | null; actualBack: number | null; exact: boolean } | null;
  dealWindow: { from: string | null; to: string | null; days: number | null } | null;
  source: string | null;
  disclosure: string | null;
  /** Rows after every filter including the lane. */
  total: number | null;
  /** Rows matching every filter EXCEPT the lane, so an empty lane is explainable. */
  matched: number | null;
  lanes: { all: number; disclosed: number; proxy: number };
  classes: Record<"A" | "B" | "C" | "D", number>;
  rows: ScannerRow[];
}

/**
 * Evidence class. Derived — never read from the stored `evidence_class` column, which is a
 * hardcoded literal 'A' on all 25,313 rows.
 *
 *   A  a disclosed holdings change (an AMC's own filing)
 *   B  a disclosed deal leg that survived transfer-netting
 *   C  a market proxy only: delivery moved, the buyer is unknown — never called accumulation
 *   D  a disclosed holdings change and a deal leg point the same way
 */
export type EvidenceClass = "A" | "B" | "C" | "D" | "none";

export const EVIDENCE_LABEL: Record<EvidenceClass, string> = {
  A: "Disclosed holdings",
  B: "Disclosed deal",
  C: "Market proxy only",
  D: "Disclosed + deal",
  none: "Nothing on record",
};

/** The class legend, shipped verbatim from spec 2.6. */
export const EVIDENCE_LEGEND: Array<{ cls: Exclude<EvidenceClass, "none">; text: string }> = [
  { cls: "A", text: "disclosed holdings change" },
  { cls: "B", text: "disclosed deal, net of transfers" },
  { cls: "C", text: "market proxy, buyer unknown" },
  { cls: "D", text: "direct and proxy align" },
];

export const EVIDENCE_NOTE: Record<EvidenceClass, string> = {
  A: "An AMC's own monthly filing shows the holding changed.",
  B: "A bulk or block deal leg that was not a matched same-day transfer.",
  C: "Delivery moved against its own baseline. The buyer is not disclosed, so this is not accumulation.",
  D: "A disclosed holdings change and a disclosed deal leg point the same way.",
  none: "No disclosed change, no deal leg and no proxy move for this name.",
};

const CLASSES: EvidenceClass[] = ["A", "B", "C", "D", "none"];
const asClass = (v: unknown): EvidenceClass => {
  const t = str(v);
  return (CLASSES as string[]).includes(t ?? "") ? (t as EvidenceClass) : "none";
};

/** The direction a row's disclosed holdings moved. Proxy-only rows have no direction. */
export function rowDirection(r: ScannerRow): "accumulation" | "distribution" | "proxy" | null {
  if (r.evidence === "C") return "proxy";
  if (r.netSharesDelta == null || r.netSharesDelta === 0) return null;
  return r.netSharesDelta > 0 ? "accumulation" : "distribution";
}

/**
 * Why this row surfaced: one line per source that actually answered, each naming its own source.
 * This is spec 2.7's "evidence chain" — assembled from the row, never narrated beyond it.
 */
export function evidenceChain(r: ScannerRow): Array<{ cls: Exclude<EvidenceClass, "none">; headline: string; source: string }> {
  const out: Array<{ cls: Exclude<EvidenceClass, "none">; headline: string; source: string }> = [];
  if (r.netSharesDelta != null && r.netSharesDelta !== 0) {
    const dir = r.netSharesDelta > 0 ? "raised" : "cut";
    const pct = r.mfSharesPctChg == null ? "" : ` (${r.mfSharesPctChg > 0 ? "+" : ""}${r.mfSharesPctChg}%)`;
    out.push({
      cls: "A",
      headline: `${r.amcsUp ?? 0} AMC${(r.amcsUp ?? 0) === 1 ? "" : "s"} ${dir} the holding across ${r.schemesUp ?? 0} scheme${(r.schemesUp ?? 0) === 1 ? "" : "s"}${pct}`,
      source: `Disclosed monthly portfolios${r.latestReportingDate ? `, as of ${r.latestReportingDate}` : ""}`,
    });
  }
  if (r.dealNetQty != null && r.dealNetQty !== 0) {
    const side = r.dealNetQty > 0 ? "net bought" : "net sold";
    const matched = r.matchedLegs && r.matchedLegs > 0 ? ` · ${r.matchedLegs} of ${r.dealLegs} legs were matched transfers and removed` : "";
    out.push({
      cls: "B",
      headline: `Disclosed deals ${side} ${Math.abs(r.dealNetQty).toLocaleString("en-IN")} shares${matched}`,
      source: "Exchange bulk and block deal disclosures, net of same-day matched transfers",
    });
  }
  if (r.delivVsBasePp != null) {
    const d = r.delivVsBasePp;
    out.push({
      cls: "C",
      headline: `Delivery ${d > 0 ? "above" : "below"} its own 60-session baseline by ${Math.abs(d)} pp`,
      source: "Exchange delivery percentage — a market proxy. The buyer is not disclosed.",
    });
  }
  return out;
}

/**
 * What would weaken this reading (spec 2.7). Each item is a concrete fact about THIS row, not
 * boilerplate — the panel is only defensible if it names its own soft spots.
 */
export function whatWouldWeaken(r: ScannerRow, mf: MfWindow | null): string[] {
  const out: string[] = [];
  if (r.singleAmcSignal) out.push("The whole disclosed signal rests on a single fund house, so one manager's decision explains it.");
  if (r.freshnessStatus && r.freshnessStatus !== "fresh") out.push(`The underlying disclosure is ${r.freshnessStatus}, so the position may already have changed.`);
  if (!r.dealsChecked) out.push("This stock was never queried for bulk or block deals, so the deal column is unknown rather than empty.");
  else if (r.transferDays && r.transferDays > 0) out.push(`${r.transferDays} deal day(s) in the window were pure transfers, which move ownership without net demand.`);
  if (r.dealNetQty != null && r.dealNetQty !== 0) out.push("Deal legs carry no counterparty classification, so a leg may be a market maker rather than a long-term holder.");
  if (r.fiiDeltaPp == null) out.push("No FII/DII shareholding change is disclosed for both quarters, so the foreign and domestic legs are unknown.");
  if (r.evidence === "C") out.push("There is no disclosed holdings change at all: delivery and volume do not identify a buyer.");
  const note = mfWindowNote(mf);
  if (note) out.push(note);
  if (r.mfSharesPctChg != null && Math.abs(r.mfSharesPctChg) < 1) out.push("The holdings change is under 1% of the prior position, which is small enough to be routine rebalancing.");
  return out;
}

async function fetchScanner(p: {
  window: SmPeriod; universe: SmUniverse; sector: string | null;
  direction: SmDirection; lane: SmLane; freshness: SmFreshness; limit: number;
}, signal?: AbortSignal): Promise<ScannerFeed> {
  const query: Record<string, string | number> = {
    window: p.window, universe: p.universe, direction: p.direction,
    lane: p.lane, freshness: p.freshness, limit: p.limit,
  };
  if (p.sector) query.sector = p.sector;
  const res = await http({ path: "/api/markets/smart-money/scanner", query, signal });
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
      dealLegs: num(r.deal_legs), matchedLegs: num(r.matched_legs),
      dealDays: num(r.deal_days), transferDays: num(r.transfer_days),
      dealsChecked: bool(r.deals_checked) ?? false,
      deliv10d: num(r.deliv_10d), deliv60d: num(r.deliv_60d), delivVsBasePp: num(r.deliv_vs_base_pp),
      closePrice: num(r.close_price), prevClose: num(r.prev_close), changePct: num(r.change_pct),
      freshnessStatus: str(r.freshness_status),
      singleAmcSignal: bool(r.single_amc_signal),
      latestReportingDate: str(r.latest_reporting_date),
      evidence: asClass(r.evidence),
    }];
  });
  const q = rec(d.quarters);
  const w = rec(d.deal_window);
  const ln = rec(d.lanes);
  const cl = rec(d.classes);
  const n = (v: unknown) => num(v) ?? 0;
  return {
    asOf: str(d.as_of), previousMonth: str(d.previous_month), window: str(d.window),
    indexName: str(d.index_name), mfWindow: mfWin(d.mf_window),
    quarters: d.quarters == null ? null : {
      current: str(q.current), previous: str(q.previous),
      requestedBack: num(q.requested_back), actualBack: num(q.actual_back), exact: bool(q.exact) ?? false,
    },
    dealWindow: d.deal_window == null ? null : { from: str(w.from), to: str(w.to), days: num(w.days) },
    source: str(d.source), disclosure: str(d.disclosure),
    total: num(d.total), matched: num(d.matched),
    lanes: { all: n(ln.all), disclosed: n(ln.disclosed), proxy: n(ln.proxy) },
    classes: { A: n(cl.A), B: n(cl.B), C: n(cl.C), D: n(cl.D) },
    rows,
  };
}

export const SCANNER_LIMIT = 100;

export interface ScannerFilters {
  window: SmPeriod;
  universe: SmUniverse;
  sector: string | null;
  direction: SmDirection;
  lane: SmLane;
  freshness: SmFreshness;
}

export function useSmScanner(enabled: boolean, f: ScannerFilters) {
  return useQuery<ScannerFeed>({
    queryKey: ["copilot", "desk", "smart-money", "scanner", f.window, f.universe, f.sector, f.direction, f.lane, f.freshness],
    enabled, staleTime: 15 * 60_000, retry: noRetry4xx,
    queryFn: ({ signal }) => fetchScanner({ ...f, limit: SCANNER_LIMIT }, signal),
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
export function useSmartMoney(f: ScannerFilters): SmartMoneyFeed {
  const feeds = useSmFeeds(true);
  const flows = useSmFlows(true, f.window);
  const sectors = useSmSectors(true, f.window, f.universe);
  const breadth = useSmBreadth(true);
  const scanner = useSmScanner(true, f);

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
