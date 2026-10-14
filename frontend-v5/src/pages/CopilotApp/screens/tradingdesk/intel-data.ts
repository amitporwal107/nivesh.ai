/**
 * Smart trading desk · Market intelligence — the event list's data.
 *
 *   GET /api/filings/feed?days=&category=&sort=latest&limit=   classified NSE / BSE filings (backend/routes/filings.py, filings_feed);
 *                                                         each row's `exchange` names where it was filed
 *   GET /api/markets/deals?days=5&kind=all&limit=200     NSE bulk and block deals over the last 5 calendar days to the latest
 *                                                         deal date (nidp.bulk_deals, nidp.block_deals via DaaS)
 *   GET /api/markets/circulars?days=30&limit=50          SEBI circulars and master circulars (SEBI RSS, nidp.sebi_circulars)
 *   GET /api/markets/fii-dii                              daily FII / DII net cash flows, ₹ crore (NSE provisional)
 *
 * Design-spec §6: one event list, newest first, with the chips All · Results ·
 * Corporate · Regulatory · FII / DII · Bulk & block. Every source becomes an
 * IntelEvent (time, type, title, sub, sentiment where the classifier gave one,
 * stock, sources) so the list and the detail panel render them the same way.
 *
 * Chips → sources:
 *   Results      filings, category earnings
 *   Corporate    filings, categories orders, mna, capex, management, dividend, buyback, qip, rating, litigation
 *   Regulatory   filings, category regulatory (the route's default mix leaves it out), plus SEBI's own circulars
 *   FII / DII    the daily institutional cash flows
 *   Bulk & block the exchange's bulk and block deals
 *   All          the route's default filing mix (results + corporate), plus the 5 largest deals by value, the 5
 *                latest SEBI circulars and the 5 latest FII / DII sessions (stated under the list)
 *
 * The filings route takes ONE `category` (an exact match on the classifier's
 * event_category), so a chip that groups several makes one request per category.
 * The query keys are the same as useFilingsFeed (screens/markets/hooks.ts), so
 * both share one cache. Rows that carry only a date (deals, flows, circulars)
 * sort after that day's timed filings: they are published after the close.
 */
import { useQueries, useQuery } from "@tanstack/react-query";
import { http } from "@/services/api/http";
import { ApiError } from "@/services/api/errors";
import { filingsService, type FeedParams, type FeedResp, type FilingRow } from "@/services/adapters/filings.adapter";
import type { FiiDiiFlowRow } from "@/services/contracts/markets.contract";
import { fmtNum } from "../../components/ui";
import { useInstitutionalFlows } from "../markets/hooks";
import { num } from "./desk-data";

type Raw = Record<string, unknown>;
const rec = (v: unknown): Raw => (v && typeof v === "object" && !Array.isArray(v) ? (v as Raw) : {});
const str = (v: unknown): string | null => (typeof v === "string" && v.trim() ? v.trim() : null);
const noRetry4xx = (count: number, e: unknown) =>
  !(e instanceof ApiError && (e.kind === "contract_drift" || (e.status != null && e.status >= 400 && e.status < 500))) && count < 1;

/** The classifier's window is 30 days; a trading desk reads the last week. */
export const FEED_DAYS = 7;
/** Rows per request: one category on its own, or each category of a group. */
const LIMIT_SINGLE = 40;
const LIMIT_GROUPED = 20;
/** What "All" takes from the sources that are not filings. */
export const ALL_TAKE = 5;

/** The event types of the design, each with its colour (Results indigo, Corporate mint, Regulatory amber, FII / DII ink-2, deals rose). */
export type EventGroup = "results" | "corporate" | "regulatory" | "flows" | "deals";

export const GROUP_LABEL: Record<EventGroup, string> = {
  results: "Results",
  corporate: "Corporate",
  regulatory: "Regulatory",
  flows: "FII / DII",
  deals: "Bulk & block",
};

export const GROUP_COLOR: Record<EventGroup, string> = {
  results: "var(--cp-indigo)",
  corporate: "var(--mint)",
  regulatory: "var(--amber)",
  flows: "var(--cp-ink-2)",
  deals: "var(--rose)",
};

export type IntelChip = "all" | EventGroup;

export interface ChipDef {
  key: IntelChip;
  label: string;
  /** Filing categories the chip reads; [undefined] = no category (the route's default mix). */
  categories: Array<string | undefined>;
  deals: boolean;
  circulars: boolean;
  flows: boolean;
}

const CORPORATE_CATEGORIES = ["orders", "mna", "capex", "management", "dividend", "buyback", "qip", "rating", "litigation"];

/** The design's chips, in the design's order (backend categories: nidp.corporate_announcements.event_category). */
export const INTEL_CHIPS: ChipDef[] = [
  { key: "all", label: "All", categories: [undefined], deals: true, circulars: true, flows: true },
  { key: "results", label: "Results", categories: ["earnings"], deals: false, circulars: false, flows: false },
  { key: "corporate", label: "Corporate", categories: CORPORATE_CATEGORIES, deals: false, circulars: false, flows: false },
  { key: "regulatory", label: "Regulatory", categories: ["regulatory"], deals: false, circulars: true, flows: false },
  { key: "flows", label: "FII / DII", categories: [], deals: false, circulars: false, flows: true },
  { key: "deals", label: "Bulk & block", categories: [], deals: true, circulars: false, flows: false },
];

const CATEGORY_LABEL: Record<string, string> = {
  earnings: "Results",
  orders: "Order",
  mna: "M&A",
  capex: "Capex",
  management: "Management",
  dividend: "Dividend",
  buyback: "Buyback",
  qip: "QIP",
  rating: "Rating",
  litigation: "Litigation",
  regulatory: "Regulatory",
  other: "Other",
  // The articles query sends "Markets" for a filing the classifier has not labelled yet.
  markets: "Unclassified",
};

/** The feed row's category ("Earnings", "Mna") as the classifier's key ("earnings", "mna"). */
export function categoryKey(category: string | null | undefined): string {
  return (category ?? "").trim().toLowerCase().replace(/\s+/g, "_");
}

export function categoryLabel(category: string | null | undefined): string {
  const k = categoryKey(category);
  if (!k) return "Unclassified";
  return CATEGORY_LABEL[k] ?? k.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase());
}

/** The design type a filing belongs to: earnings → Results, regulatory → Regulatory, every other category → Corporate. */
export function groupOfCategory(category: string | null | undefined): EventGroup {
  const k = categoryKey(category);
  if (k === "earnings") return "results";
  if (k === "regulatory") return "regulatory";
  return "corporate";
}

const IST = "Asia/Kolkata";
const istDay = (d: Date) => d.toLocaleDateString("en-CA", { timeZone: IST });

/** "09:12" for a filing made today (India time), "13 Oct" before that, and the full stamp. */
export function eventWhen(iso: string | null | undefined): { short: string; full: string } {
  if (!iso) return { short: "—", full: "—" };
  const dateOnly = /^\d{4}-\d{2}-\d{2}$/.test(iso);
  const d = new Date(dateOnly ? `${iso}T12:00:00+05:30` : iso);
  if (!Number.isFinite(d.getTime())) return { short: "—", full: "—" };
  const day = d.toLocaleDateString("en-IN", { timeZone: IST, day: "numeric", month: "short" });
  if (dateOnly) return { short: day, full: d.toLocaleDateString("en-IN", { timeZone: IST, day: "numeric", month: "short", year: "numeric" }) };
  const time = d.toLocaleTimeString("en-IN", { timeZone: IST, hour: "2-digit", minute: "2-digit", hour12: false });
  return {
    short: istDay(d) === istDay(new Date()) ? time : day,
    full: `${d.toLocaleDateString("en-IN", { timeZone: IST, day: "numeric", month: "short", year: "numeric" })}, ${time} IST`,
  };
}

/** The exchange a filing was made on, read from its document link (for a row that does not name it). */
export function exchangeOf(url: string | null | undefined): string | null {
  if (!url) return null;
  try {
    const host = new URL(url).hostname.toLowerCase();
    if (host.includes("nseindia")) return "NSE";
    if (host.includes("bseindia")) return "BSE";
    return host.replace(/^www\./, "");
  } catch {
    return null;
  }
}

/** Where a filing was made: the row's own `exchange` (from the stored source), else read from the document link. */
export function filingExchange(r: FilingRow): string | null {
  const named = str(r.exchange);
  return named ? named.toUpperCase() : exchangeOf(r.url);
}

/** Only an http(s) link is rendered as a link; the text comes from an outside feed. */
function webUrl(v: unknown): string | null {
  const s = str(v);
  if (!s) return null;
  try {
    const u = new URL(s);
    return u.protocol === "https:" || u.protocol === "http:" ? u.href : null;
  } catch {
    return null;
  }
}

// ── one event, whatever its source ───────────────────────────────────────

export interface EventSource {
  text: string;
  /** An http(s) link, or null when the source has none. */
  url: string | null;
}

export interface IntelEvent {
  /** The filing's own id; "deal-…", "sebi-…" or "fiidii-…" for the other sources. */
  id: string;
  group: EventGroup;
  /** The type line: "Results", "Corporate · Order", "Regulatory · SEBI circular", "FII / DII", "Block deal". */
  type: string;
  /** An ISO date-time (filings) or a calendar day (deals, flows, circulars); null when the source sent none. */
  at: string | null;
  /** Newest first; a calendar day counts as its end (India time). */
  sortAt: number;
  title: string;
  sub: string | null;
  /** The classifier's sentiment, for filings only; null elsewhere (no classification exists). */
  sentiment: string | null;
  impact: string | null;
  /** The listed stock the event is about; null for market-wide events. */
  symbol: string | null;
  name: string | null;
  /** FII / DII net cash flows, ₹ crore (flows only). */
  flow: { fii: number | null; dii: number | null } | null;
  /** The classifier's generated one-line read of a filing; null when none exists yet. */
  read: string | null;
  sources: EventSource[];
  filing: FilingRow | null;
}

const DAY_RE = /^\d{4}-\d{2}-\d{2}$/;

function sortTime(at: string | null): number {
  if (!at) return -Infinity;
  const t = new Date(DAY_RE.test(at) ? `${at}T23:59:59+05:30` : at).getTime();
  return Number.isFinite(t) ? t : -Infinity;
}

/** Newest first for two sort times, with equal (or both missing) times kept in place. */
const byTime = (a: number, b: number) => (a === b ? 0 : b - a);

export function filingEvent(r: FilingRow): IntelEvent {
  const group = groupOfCategory(r.category);
  const cat = categoryLabel(r.category);
  const ticker = (r.code ?? r.ticker ?? "").trim().toUpperCase() || null;
  const exchange = filingExchange(r);
  const doc = r.docLabel ?? "Exchange filing";
  const url = webUrl(r.url);
  return {
    id: r.id,
    group,
    type: group === "corporate" ? `${GROUP_LABEL.corporate} · ${cat}` : GROUP_LABEL[group],
    at: r.date ?? null,
    sortAt: sortTime(r.date ?? null),
    title: doc,
    sub: r.one ?? r.metric ?? r.name ?? null,
    sentiment: str(r.sentiment),
    impact: str(r.impact),
    symbol: ticker,
    name: r.name ?? null,
    flow: null,
    read: str(r.one),
    sources: [{ text: `${exchange ? `Filed with ${exchange}` : "Exchange filing"} · ${doc}`, url }],
    filing: r,
  };
}

const crore = (n: number) => `₹${fmtNum(Math.abs(n))} Cr`;

export function dealEvent(d: DealRow, i: number, source: string | null): IntelEvent {
  const kind = d.kind === "block" ? "Block deal" : d.kind === "bulk" ? "Bulk deal" : "Deal";
  const verb = d.side === "BUY" ? "bought" : d.side === "SELL" ? "sold" : "traded";
  const qty = d.quantity != null ? (d.quantity >= 1e5 ? `${(d.quantity / 1e5).toFixed(2)} L` : fmtNum(d.quantity)) : null;
  const value = d.valueCr != null ? `₹${fmtNum(d.valueCr, 2)} Cr` : null;
  const price = d.price != null ? `₹${fmtNum(d.price, 2)} average` : null;
  return {
    id: `deal-${d.date ?? "nodate"}-${d.kind ?? "deal"}-${d.symbol}-${i}`,
    group: "deals",
    type: kind,
    at: d.date,
    sortAt: sortTime(d.date),
    title: `${d.client ?? "A client"} ${verb} ${qty ? `${qty} shares` : "shares"}`,
    sub: [kind, value, price ? `at ${price}` : null].filter(Boolean).join(" · "),
    sentiment: null,
    impact: null,
    symbol: d.symbol,
    name: null,
    flow: null,
    read: null,
    sources: [{ text: `${source ?? "NSE bulk and block deals"}${d.date ? ` · end of day ${eventWhen(d.date).full}` : ""}`, url: null }],
    filing: null,
  };
}

export function circularEvent(c: Circular, i: number): IntelEvent {
  const kind = c.kind ? CIRCULAR_KIND_LABEL[c.kind] ?? c.kind : "Circular";
  return {
    id: `sebi-${c.issuedOn ?? "nodate"}-${i}`,
    group: "regulatory",
    type: `${GROUP_LABEL.regulatory} · SEBI ${kind.toLowerCase()}`,
    at: c.issuedOn,
    sortAt: sortTime(c.issuedOn),
    title: c.title,
    sub: c.issuedOn ? "Issued by SEBI" : "Issued by SEBI · issue date not stated",
    sentiment: null,
    impact: null,
    symbol: null,
    name: null,
    flow: null,
    read: null,
    sources: [{ text: `SEBI · ${kind}`, url: c.url }],
    filing: null,
  };
}

const flowWords = (who: string, n: number | null) =>
  n == null ? `${who}: no figure` : n > 0 ? `${who} net bought ${crore(n)}` : n < 0 ? `${who} net sold ${crore(n)}` : `${who} flat`;

export function flowEvent(r: FiiDiiFlowRow): IntelEvent {
  const fii = r.fii_net ?? null;
  const dii = r.dii_net ?? null;
  const date = r.date ?? null;
  return {
    id: `fiidii-${date ?? "nodate"}`,
    group: "flows",
    type: GROUP_LABEL.flows,
    at: date,
    sortAt: sortTime(date),
    title: `${flowWords("FIIs", fii)} · ${flowWords("DIIs", dii)}`,
    sub: "Cash market · provisional figures",
    sentiment: null,
    impact: null,
    symbol: null,
    name: null,
    flow: { fii, dii },
    read: null,
    sources: [{ text: `NSE · provisional FII / DII cash-market figures${date ? `, ${eventWhen(date).full}` : ""}`, url: null }],
    filing: null,
  };
}

export type SourceKey = "filings" | "deals" | "circulars" | "flows";

export interface EventFeed {
  status: "loading" | "error" | "ready";
  /** Newest first. */
  events: IntelEvent[];
  /** What each source added, and (filings) how many matched in the window before the route's limit. */
  counts: { filings: number; filingsTotal: number | null; deals: number; dealsTotal: number | null; circulars: number; flows: number };
  /** Sources that failed while others answered: the list is partial. */
  failed: SourceKey[];
  error: unknown;
  /** As-of stamps the sources sent, for the source line. */
  asOf: { deals: string | null; circulars: string | null; flows: string | null };
  dealsSource: string | null;
  circularsSource: string | null;
  refetch: () => void;
}

/** Every event behind one chip, merged newest first. */
export function useIntelEvents(chip: IntelChip): EventFeed {
  const def = INTEL_CHIPS.find((c) => c.key === chip) ?? INTEL_CHIPS[0];
  const cats = def.categories;
  const limit = cats.length > 1 ? LIMIT_GROUPED : LIMIT_SINGLE;
  const filings = useQueries({
    queries: cats.map((category) => {
      const params: FeedParams = { days: FEED_DAYS, category, sort: "latest", limit };
      return {
        queryKey: ["filings", "feed", params],
        queryFn: () => filingsService.getFeed(params),
        staleTime: 60_000,
      };
    }),
  });
  const deals = useDeals(def.deals);
  const circulars = useCirculars(def.circulars);
  const flows = useInstitutionalFlows(90);
  const all = chip === "all";

  type Part = { key: SourceKey; pending: boolean; error: unknown; failed: boolean; refetch: () => void };
  const parts: Part[] = [];
  for (const q of filings) parts.push({ key: "filings", pending: q.isPending, failed: q.isError, error: q.error, refetch: () => void q.refetch() });
  if (def.deals) parts.push({ key: "deals", pending: deals.isPending, failed: deals.isError, error: deals.error, refetch: () => void deals.refetch() });
  if (def.circulars) parts.push({ key: "circulars", pending: circulars.isPending, failed: circulars.isError, error: circulars.error, refetch: () => void circulars.refetch() });
  if (def.flows) parts.push({ key: "flows", pending: flows.isPending, failed: flows.isError, error: flows.error, refetch: () => void flows.refetch() });

  const refetch = () => {
    for (const p of parts) if (p.failed) p.refetch();
  };
  const failedParts = parts.filter((p) => p.failed);
  const empty = { filings: 0, filingsTotal: null, deals: 0, dealsTotal: null, circulars: 0, flows: 0 };
  const asOf = { deals: deals.data?.asOf ?? null, circulars: circulars.data?.asOf ?? null, flows: flows.data?.as_of ?? null };
  const base = { asOf, dealsSource: deals.data?.source ?? null, circularsSource: circulars.data?.source ?? null, refetch };
  if (parts.length && failedParts.length === parts.length) {
    return { status: "error", events: [], counts: empty, failed: [...new Set(failedParts.map((p) => p.key))], error: failedParts[0].error, ...base };
  }
  if (parts.some((p) => p.pending)) return { status: "loading", events: [], counts: empty, failed: [], error: null, ...base };

  const events: IntelEvent[] = [];
  const seen = new Set<string>();
  let filingsTotal: number | null = 0;
  for (const q of filings) {
    if (!q.isSuccess) continue;
    const d = q.data as FeedResp;
    filingsTotal = filingsTotal == null ? null : filingsTotal + (d.total ?? d.rows.length);
    for (const r of d.rows) {
      if (seen.has(r.id)) continue;
      seen.add(r.id);
      events.push(filingEvent(r));
    }
  }
  const nFilings = events.length;

  let nFlows = 0;
  if (def.flows && flows.data) {
    const rows = flows.data.daily.filter((r) => !!r.date).sort((a, b) => (b.date ?? "").localeCompare(a.date ?? ""));
    const take = all ? rows.slice(0, ALL_TAKE) : rows.slice(0, FLOW_SESSIONS);
    for (const r of take) events.push(flowEvent(r));
    nFlows = take.length;
  }
  let nDeals = 0;
  if (def.deals && deals.data) {
    const rows = all ? [...deals.data.rows].sort((a, b) => (b.valueCr ?? -Infinity) - (a.valueCr ?? -Infinity)).slice(0, ALL_TAKE) : deals.data.rows;
    rows.forEach((d, i) => events.push(dealEvent(d, i, deals.data.source)));
    nDeals = rows.length;
  }
  let nCirculars = 0;
  if (def.circulars && circulars.data) {
    const rows = all ? [...circulars.data.rows].sort((a, b) => byTime(sortTime(a.issuedOn), sortTime(b.issuedOn))).slice(0, ALL_TAKE) : circulars.data.rows;
    rows.forEach((c, i) => events.push(circularEvent(c, i)));
    nCirculars = rows.length;
  }
  // Newest first; Array.prototype.sort is stable, so same-time rows keep their source order (undated rows last).
  events.sort((a, b) => byTime(a.sortAt, b.sortAt));
  return {
    status: "ready",
    events,
    counts: { filings: nFilings, filingsTotal: cats.length ? filingsTotal : null, deals: nDeals, dealsTotal: deals.data?.total ?? null, circulars: nCirculars, flows: nFlows },
    failed: [...new Set(failedParts.map((p) => p.key))],
    error: failedParts[0]?.error ?? null,
    ...base,
  };
}

/** FII / DII sessions the FII / DII chip lists. */
export const FLOW_SESSIONS = 10;

// ── the stock's last move (from the scanner's daily closes) ──────────────

/** 1-day change from a series of daily closes (oldest first), percent; null with fewer than two closes. */
export function dayChangePct(closes: number[]): number | null {
  if (closes.length < 2) return null;
  const last = closes[closes.length - 1];
  const prev = closes[closes.length - 2];
  return prev > 0 ? ((last - prev) / prev) * 100 : null;
}

// ── bulk and block deals (GET /api/markets/deals) ────────────────────────

/** Calendar days of deals the Bulk & block chip lists, ending at the latest deal date on record. */
export const DEAL_DAYS = 5;
/** Deals asked for; the route says how many matched (`total`). */
const DEAL_LIMIT = 200;

export interface DealRow {
  date: string | null;
  /** "bulk" | "block", as sent. */
  kind: string | null;
  symbol: string;
  client: string | null;
  /** "BUY" | "SELL", as sent (upper case). */
  side: string | null;
  quantity: number | null;
  /** Average traded price of the deal, rupees. */
  price: number | null;
  /** Deal value, ₹ crore. */
  valueCr: number | null;
}

export interface DealsFeed {
  /** The latest deal date on record, and the first calendar day of the window ending there. */
  asOf: string | null;
  from: string | null;
  /** Calendar days in the window. */
  days: number | null;
  source: string | null;
  /** Rows sent, and deals matching in the window before the route's limit. */
  count: number | null;
  total: number | null;
  rows: DealRow[];
}

async function fetchDeals(days: number, signal?: AbortSignal): Promise<DealsFeed> {
  const res = await http({ path: "/api/markets/deals", query: { days, kind: "all", limit: DEAL_LIMIT }, signal });
  const d = rec(res.data);
  if (!Array.isArray(d.rows)) throw ApiError.contractDrift("markets.deals: no rows list");
  const rows: DealRow[] = d.rows.flatMap((v): DealRow[] => {
    const r = rec(v);
    const symbol = str(r.symbol)?.toUpperCase();
    if (!symbol) return [];
    const q = num(r.quantity);
    const p = num(r.avg_price);
    return [{
      date: str(r.date),
      kind: str(r.kind)?.toLowerCase() ?? null,
      symbol,
      client: str(r.client_name),
      side: str(r.side)?.toUpperCase() ?? null,
      quantity: q != null && q > 0 ? q : null,
      price: p != null && p > 0 ? p : null,
      valueCr: num(r.value_cr),
    }];
  });
  return { asOf: str(d.as_of), from: str(d.from), days: num(d.days), source: str(d.source), count: num(d.count), total: num(d.total), rows };
}

/** GET /api/markets/deals — read when the All or Bulk & block chip is open. */
export function useDeals(enabled: boolean, days = DEAL_DAYS) {
  return useQuery<DealsFeed>({
    queryKey: ["copilot", "desk", "deals", days],
    enabled,
    staleTime: 10 * 60_000,
    retry: noRetry4xx,
    queryFn: ({ signal }) => fetchDeals(days, signal),
  });
}

// ── SEBI circulars (GET /api/markets/circulars) ──────────────────────────

export const CIRCULAR_DAYS = 30;
const CIRCULAR_LIMIT = 50;

export interface Circular {
  title: string;
  /** The circular on sebi.gov.in; null when the row has no http(s) link. */
  url: string | null;
  /** "circular" | "master_circular", as sent. */
  kind: string | null;
  issuedOn: string | null;
}

export interface CircularsFeed {
  asOf: string | null;
  source: string | null;
  count: number | null;
  rows: Circular[];
}

async function fetchCirculars(signal?: AbortSignal): Promise<CircularsFeed> {
  const res = await http({ path: "/api/markets/circulars", query: { days: CIRCULAR_DAYS, limit: CIRCULAR_LIMIT }, signal });
  const d = rec(res.data);
  if (!Array.isArray(d.rows)) throw ApiError.contractDrift("markets.circulars: no rows list");
  const rows: Circular[] = d.rows.flatMap((v): Circular[] => {
    const r = rec(v);
    const title = str(r.title);
    if (!title) return [];
    return [{ title, url: webUrl(r.url), kind: str(r.kind)?.toLowerCase() ?? null, issuedOn: str(r.issued_on) }];
  });
  return { asOf: str(d.as_of), source: str(d.source), count: num(d.count), rows };
}

/** GET /api/markets/circulars — read when the All or Regulatory chip is open. */
export function useCirculars(enabled: boolean) {
  return useQuery<CircularsFeed>({
    queryKey: ["copilot", "desk", "circulars"],
    enabled,
    staleTime: 30 * 60_000,
    retry: noRetry4xx,
    queryFn: ({ signal }) => fetchCirculars(signal),
  });
}

export const CIRCULAR_KIND_LABEL: Record<string, string> = { circular: "Circular", master_circular: "Master circular" };
