/**
 * Smart trading desk · Market intelligence — the event list's data.
 *
 *   GET /api/filings/feed?days=&category=&sort=latest&limit=&provenance=1
 *                                                         classified NSE / BSE filings (backend/routes/filings.py). With
 *                                                         provenance=1 each row also carries its source records, the
 *                                                         exchange's publication time AND Nivesh's ingestion time, the
 *                                                         resolved NSE symbol, market timing, sector (with its source)
 *                                                         and same-industry peers (DaaS /v1/desk/event-sources)
 *   GET /api/filings/feed?family=calls|ownership|exchange&provenance=1
 *                                                         filings by the exchange's OWN subject line, for the PRD
 *                                                         categories the classifier has no label for
 *   GET /api/markets/deals?days=5&kind=all&limit=200     NSE bulk and block deals with % of shares, the close around the
 *                                                         deal and the ingestion time (nidp.bulk_deals / block_deals)
 *   GET /api/markets/circulars?days=30&limit=50          SEBI circulars and master circulars (SEBI RSS, nidp.sebi_circulars)
 *   GET /api/markets/fii-dii                              daily FII / DII net cash flows, ₹ crore (NSE provisional)
 *   GET /api/markets/sector-returns                       NSE sector indices' 1-day return, end of day (Sector chip)
 *
 * PRD §6.2's twelve categories → the chips, each on a real source:
 *   Announcements      filings, classifier categories management, capex, qip, rating
 *   Results            filings, earnings
 *   Calls & guidance   filings whose exchange subject is an analyst / investor meet, a call, a transcript or an
 *                      investor presentation (family "calls")
 *   Orders             filings, orders
 *   M&A & actions      filings, mna, dividend, buyback
 *   Ownership          filings under SEBI's takeover (SAST) and insider-trading rules, pledges, shareholding
 *                      (family "ownership"); nidp.insider_sast is empty on staging and has no app route
 *   Bulk & block       NSE bulk and block deals
 *   FII / DII          NSE provisional institutional cash flows
 *   Regulatory         filings, regulatory and litigation, plus SEBI's own circulars
 *   Sector             NSE sector index closes that moved SECTOR_MOVE_MIN % or more in the last session
 *                      (no sector-news feed is ingested; these are index moves, said so)
 *   Macro              disabled: no macro-economic calendar is ingested
 *   Exchange notices   the company's answers to the exchange's surveillance queries (family "exchange"); F&O ban
 *                      and ASM / GSM lists are not ingested, said so
 *   All                the route's default filing mix, plus the 5 largest deals, the 5 latest SEBI circulars and
 *                      the 5 latest FII / DII sessions (stated under the list)
 *
 * Duplicates (PRD §6.4, §6.8): the NSE and BSE copies of one filing are separate rows with no shared id. Two filings
 * are consolidated into one event when they resolve to the same NSE symbol, come from different exchanges and were
 * filed within DUPLICATE_WINDOW_MIN minutes of each other, or come from the same exchange with the same subject the
 * same IST day. No record is dropped: the event lists every source ("2 sources"). The NSE copy leads.
 *
 * Every IntelEvent says where it came from (`sourceLabel`, e.g. "Exchange filing (NSE)") — never "verified".
 * The classifier's sentiment, importance and the generated read are AI outputs and are kept apart (`ai`) from the
 * sourced facts (`facts`).
 */
import { useQueries, useQuery } from "@tanstack/react-query";
import { http } from "@/services/api/http";
import { ApiError } from "@/services/api/errors";
import { FeedRespC, type FeedParams, type FilingRow } from "@/services/adapters/filings.adapter";
import type { FiiDiiFlowRow } from "@/services/contracts/markets.contract";
import { fmtNum } from "../../components/ui";
import { useInstitutionalFlows } from "../markets/hooks";
import { num } from "./desk-data";
import { useSectorReturns } from "./overview-data";

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
/** A sector index move this large (either way, percent, last session) is listed under Sector. */
export const SECTOR_MOVE_MIN = 1;
/** NSE and BSE copies of one filing filed this many minutes apart or less are one event. */
export const DUPLICATE_WINDOW_MIN = 10;

/** The event types of the design, each with its colour (Results indigo, Corporate mint, Regulatory amber, FII / DII ink-2, deals rose). */
export type EventGroup = "results" | "corporate" | "regulatory" | "flows" | "deals" | "sector" | "exchange";

export const GROUP_LABEL: Record<EventGroup, string> = {
  results: "Results",
  corporate: "Corporate",
  regulatory: "Regulatory",
  flows: "FII / DII",
  deals: "Bulk & block",
  sector: "Sector",
  exchange: "Exchange notice",
};

export const GROUP_COLOR: Record<EventGroup, string> = {
  results: "var(--cp-indigo)",
  corporate: "var(--mint)",
  regulatory: "var(--amber)",
  flows: "var(--cp-ink-2)",
  deals: "var(--rose)",
  sector: "var(--cp-indigo)",
  exchange: "var(--amber)",
};

/** Filing families read by the exchange's own subject line (DaaS /v1/desk/filings). */
export type FilingFamily = "calls" | "ownership" | "exchange";

export type IntelChip =
  | "all" | "announcements" | "results" | "calls" | "orders" | "mna" | "ownership" | "deals" | "flows" | "regulatory"
  | "sector" | "macro" | "exchange"
  /** Not a chip on screen: every corporate category at once (kept for callers outside the tab). */
  | "corporate";

export interface ChipDef {
  key: IntelChip;
  label: string;
  /** Filing categories the chip reads; [undefined] = no category (the route's default mix). */
  categories: Array<string | undefined>;
  families: FilingFamily[];
  deals: boolean;
  circulars: boolean;
  flows: boolean;
  sectors: boolean;
  /** Why the chip has nothing to show (a source that is not ingested); the chip is disabled. */
  disabled?: string;
  /** What the chip cannot show although the PRD asks for it, said under its list. */
  missing?: string;
  /** The single classifier category the chip stands for, so "alert me on the next one" can be offered. */
  alertCategory?: string;
  /** Hidden chips are not drawn. */
  hidden?: boolean;
}

const CORPORATE_CATEGORIES = ["orders", "mna", "capex", "management", "dividend", "buyback", "qip", "rating", "litigation"];
const none = { families: [] as FilingFamily[], deals: false, circulars: false, flows: false, sectors: false };

/** PRD §6.2's twelve categories in the PRD's order, after All (backend categories: nidp.corporate_announcements.event_category). */
export const INTEL_CHIPS: ChipDef[] = [
  { key: "all", label: "All", categories: [undefined], ...none, deals: true, circulars: true, flows: true },
  { key: "announcements", label: "Announcements", categories: ["management", "capex", "qip", "rating"], ...none },
  { key: "results", label: "Results", categories: ["earnings"], ...none, alertCategory: "earnings" },
  { key: "calls", label: "Calls & guidance", categories: [], ...none, families: ["calls"] },
  { key: "orders", label: "Orders", categories: ["orders"], ...none, alertCategory: "orders" },
  { key: "mna", label: "M&A & actions", categories: ["mna", "dividend", "buyback"], ...none },
  { key: "ownership", label: "Ownership", categories: [], ...none, families: ["ownership"],
    missing: "Promoter and insider trades from NSE's SAST / PIT disclosure files are not loaded yet (nidp.insider_sast is empty); these are the companies' own filings." },
  { key: "deals", label: "Bulk & block", categories: [], ...none, deals: true },
  { key: "flows", label: "FII / DII", categories: [], ...none, flows: true },
  { key: "regulatory", label: "Regulatory", categories: ["regulatory", "litigation"], ...none, circulars: true },
  { key: "sector", label: "Sector", categories: [], ...none, sectors: true,
    missing: `No sector news feed is ingested. These are NSE sector indices that closed ${SECTOR_MOVE_MIN}% or more up or down in their last session.` },
  { key: "macro", label: "Macro", categories: [], ...none,
    disabled: "No macro-economic calendar (RBI policy, inflation, GDP dates) is ingested, so there are no macro events to list." },
  { key: "exchange", label: "Exchange notices", categories: [], ...none, families: ["exchange"],
    missing: "F&O ban lists and ASM / GSM surveillance lists are not ingested, so trading restrictions are not listed; these are the companies' answers to the exchange's queries." },
  { key: "corporate", label: "Corporate", categories: CORPORATE_CATEGORIES, ...none, hidden: true },
];

export const VISIBLE_CHIPS = INTEL_CHIPS.filter((c) => !c.hidden);

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

/** Classifier categories an alert may name (services/desk_alerts.py FILING_CATEGORIES). */
const ALERTABLE = new Set(["earnings", "orders", "mna", "capex", "management", "dividend", "buyback", "qip", "rating", "litigation", "regulatory"]);

export const FAMILY_LABEL: Record<FilingFamily, string> = {
  calls: "Call / guidance",
  ownership: "Ownership disclosure",
  exchange: "Exchange query",
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

/** The design type a filing belongs to: earnings → Results, regulatory / litigation → Regulatory, every other category → Corporate. */
export function groupOfCategory(category: string | null | undefined): EventGroup {
  const k = categoryKey(category);
  if (k === "earnings") return "results";
  if (k === "regulatory" || k === "litigation") return "regulatory";
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

/** "NSE_ANN" → "NSE". */
function exchangeOfSource(s: string | null): string | null {
  if (!s) return null;
  const u = s.toUpperCase();
  return u.startsWith("NSE") ? "NSE" : u.startsWith("BSE") ? "BSE" : s;
}

// ── one event, whatever its source ───────────────────────────────────────

export interface EventSource {
  text: string;
  /** An http(s) link, or null when the source has none. */
  url: string | null;
}

/** One stored record behind an event (a filing on one exchange). */
export interface EventRecord {
  id: string;
  exchange: string | null;
  subject: string | null;
  url: string | null;
  /** The exchange's dissemination time. */
  publishedAt: string | null;
  /** When Nivesh last fetched the record (the store keeps the latest fetch only). */
  ingestedAt: string | null;
}

export interface Peer {
  symbol: string;
  name: string | null;
  /** The narrowest broad index the company is in ("Nifty 50"), its size order. */
  index: string | null;
}

/** A sourced fact: a field the source itself published (or one worked out from such fields, said in `note`). */
export interface Fact {
  k: string;
  v: string;
  note?: string;
  testId: string;
}

/** What an AI model produced about the event: kept apart from the facts and labelled as such. */
export interface AiRead {
  /** The generated one-line read of the filing. */
  summary: string | null;
  /** Period and headline metric the generator extracted from the document. */
  extracted: Fact[];
  /** The classifier's tone label (positive / neutral / negative): never a price direction. */
  tone: string | null;
  /** The classifier's importance (impact_score). */
  importance: string | null;
  classifier: string | null;
}

/** The deal's own figures for the §6.6 block (null where the warehouse has none). */
export interface DealFacts {
  kind: string | null;
  client: string | null;
  side: string | null;
  quantity: number | null;
  price: number | null;
  valueCr: number | null;
  pctOfShares: number | null;
  sharesPeriodEnd: string | null;
  closeOnDay: number | null;
  prevClose: number | null;
  nextDate: string | null;
  nextClose: number | null;
  priceVsClosePct: number | null;
  ingestedAt: string | null;
}

export interface IntelEvent {
  /** The filing's own id; "deal-…", "sebi-…", "fiidii-…" or "sector-…" for the other sources. */
  id: string;
  group: EventGroup;
  /** The type line: "Results", "Corporate · Order", "Regulatory · SEBI circular", "FII / DII", "Block deal". */
  type: string;
  /** An ISO date-time (filings) or a calendar day (deals, flows, circulars, sectors); null when the source sent none. */
  at: string | null;
  /** Newest first; a calendar day counts as its end (India time). */
  sortAt: number;
  title: string;
  sub: string | null;
  /** The classifier's sentiment, for filings only (an AI label; the screen says so). */
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
  /** Who published it: "NSE", "BSE", "SEBI", "NSE (bulk deal file)". */
  org: string | null;
  /** The source, said instead of a verification claim: "Exchange filing (NSE)", "SEBI circular", "Exchange disclosure (NSE)". */
  sourceLabel: string;
  /** The source's own publication time, and when Nivesh ingested it (null when not known). */
  publishedAt: string | null;
  ingestedAt: string | null;
  sector: { name: string; source: string } | null;
  peers: Peer[];
  /** v_event_asof: when the filing was made relative to the session, and the first session whose open can reflect it. */
  timing: { type: string | null; knownAtOpen: string | null; knownByClose: string | null } | null;
  facts: Fact[];
  ai: AiRead | null;
  deal: DealFacts | null;
  /** Every record behind the event (two or more when duplicates were consolidated). */
  records: EventRecord[];
  /** For "alert me on the next one like this": the classifier category ("deal" for a deal), when the event has one. */
  alertCategory: string | null;
  /** A sector move's index name (for a sector alert). */
  sectorIndex: string | null;
}

const DAY_RE = /^\d{4}-\d{2}-\d{2}$/;

function sortTime(at: string | null): number {
  if (!at) return -Infinity;
  const t = new Date(DAY_RE.test(at) ? `${at}T23:59:59+05:30` : at).getTime();
  return Number.isFinite(t) ? t : -Infinity;
}

/** Newest first for two sort times, with equal (or both missing) times kept in place. */
const byTime = (a: number, b: number) => (a === b ? 0 : b - a);

const TIMING_TEXT: Record<string, string> = {
  pre_market: "before the market opened",
  intraday: "during market hours",
  after_close: "after the close",
  non_session: "on a day the market was shut",
};

/** The market-timing sentence for a filing (v_event_asof), or null. */
export function timingText(t: IntelEvent["timing"]): string | null {
  if (!t?.type) return null;
  const when = TIMING_TEXT[t.type] ?? t.type.replace(/_/g, " ");
  return t.knownAtOpen ? `Filed ${when}; the first session whose open can reflect it is ${eventWhen(t.knownAtOpen).full}.` : `Filed ${when}.`;
}

function readRecords(r: Raw, fallback: { id: string; exchange: string | null; subject: string | null; url: string | null; at: string | null }): EventRecord[] {
  const list = Array.isArray(r.records) ? r.records : null;
  const one = (): EventRecord[] => [{ id: fallback.id, exchange: fallback.exchange, subject: fallback.subject, url: fallback.url, publishedAt: fallback.at, ingestedAt: str(r.ingested_at) }];
  if (!list) return one();
  const out = list.flatMap((v): EventRecord[] => {
    const x = rec(v);
    const id = str(x.announcement_id);
    if (!id) return [];
    return [{ id, exchange: exchangeOfSource(str(x.source)), subject: str(x.subject), url: webUrl(x.url), publishedAt: str(x.published_at), ingestedAt: str(x.ingested_at) }];
  });
  return out.length ? out : one();
}

/** The numbered sources and the sourced facts, from the event's records (so a consolidated event lists them all). */
function withSources(ev: IntelEvent): IntelEvent {
  const recs = ev.records;
  const sources = recs.map((x) => ({
    text: `${x.exchange ? `Filed with ${x.exchange}` : "Exchange filing"} · ${x.subject ?? ev.title}`,
    url: x.url,
  }));
  const facts: Fact[] = [
    { k: "Event ID", v: ev.id, testId: "desk-event-fact-id" },
    { k: "Source", v: recs.length > 1 ? `${ev.sourceLabel} · ${recs.length} sources` : ev.sourceLabel, testId: "desk-event-fact-source" },
    { k: "Company", v: [ev.name, ev.symbol].filter(Boolean).join(" · ") || "—", testId: "desk-event-fact-company" },
    { k: "Published", v: ev.publishedAt ? eventWhen(ev.publishedAt).full : "—", note: "the exchange's own time stamp", testId: "desk-event-fact-published" },
    {
      k: "Ingested",
      v: ev.ingestedAt ? eventWhen(ev.ingestedAt).full : "—",
      note: ev.ingestedAt ? "when Nivesh last fetched it; a first-seen time is not stored" : "not sent for this filing",
      testId: "desk-event-fact-ingested",
    },
    { k: "Category", v: ev.type, testId: "desk-event-fact-category" },
    { k: "Sector", v: ev.sector ? ev.sector.name : "—", note: ev.sector?.source ?? "no industry on record for this company", testId: "desk-event-fact-sector" },
  ];
  const t = timingText(ev.timing);
  if (t) facts.push({ k: "Market timing", v: t, note: "rules-based, from the filing time and the NSE calendar", testId: "desk-event-fact-timing" });
  return { ...ev, sources, facts };
}

export function filingEvent(r: FilingRow, family: FilingFamily | null = null): IntelEvent {
  const raw = r as unknown as Raw;
  const ck = categoryKey(r.category);
  const group: EventGroup = family === "exchange" ? "exchange" : family ? "corporate" : groupOfCategory(r.category);
  const cat = categoryLabel(r.category);
  const nse = str(raw.nse_symbol)?.toUpperCase() ?? null;
  const ticker = (r.code ?? r.ticker ?? "").trim().toUpperCase() || nse;
  const exchange = filingExchange(r);
  const doc = r.docLabel ?? "Exchange filing";
  const url = webUrl(r.url);
  const sectorName = str(raw.sector);
  const peers = (Array.isArray(raw.peers) ? raw.peers : []).flatMap((v): Peer[] => {
    const p = rec(v);
    const s = str(p.symbol)?.toUpperCase();
    return s ? [{ symbol: s, name: str(p.name), index: str(p.largest_index) }] : [];
  });
  const timing = str(raw.timing_type) || str(raw.known_at_open_session)
    ? { type: str(raw.timing_type), knownAtOpen: str(raw.known_at_open_session), knownByClose: str(raw.known_by_close_session) }
    : null;
  const extracted: Fact[] = [];
  if (r.period) extracted.push({ k: "Period", v: r.period, testId: "desk-event-ai-period" });
  if (r.metric) extracted.push({ k: "Headline figure", v: r.metric, testId: "desk-event-ai-metric" });
  const ai: AiRead | null = r.one || extracted.length || r.sentiment || r.impact
    ? { summary: str(r.one), extracted, tone: str(r.sentiment), importance: str(r.impact), classifier: str(raw.classifier_version) }
    : null;
  let type: string;
  if (family) type = FAMILY_LABEL[family];
  else if (group === "corporate") type = `${GROUP_LABEL.corporate} · ${cat}`;
  else if (ck === "litigation") type = `${GROUP_LABEL.regulatory} · Litigation`;
  else type = GROUP_LABEL[group];
  return withSources({
    id: r.id,
    group,
    type,
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
    sources: [],
    filing: r,
    org: exchange,
    sourceLabel: `Exchange filing${exchange ? ` (${exchange})` : ""}`,
    publishedAt: str(raw.published_at) ?? r.date ?? null,
    ingestedAt: str(raw.ingested_at),
    sector: sectorName ? { name: sectorName, source: str(raw.sector_source) ?? "source not named" } : null,
    peers,
    timing,
    facts: [],
    ai,
    deal: null,
    records: readRecords(raw, { id: r.id, exchange, subject: doc, url, at: r.date ?? null }),
    alertCategory: ALERTABLE.has(ck) ? ck : null,
    sectorIndex: null,
  });
}

const minutes = (a: string | null, b: string | null) => {
  if (!a || !b) return Infinity;
  const d = Math.abs(new Date(a).getTime() - new Date(b).getTime());
  return Number.isFinite(d) ? d / 60_000 : Infinity;
};
const norm = (s: string | null) => (s ?? "").toLowerCase().replace(/[^a-z0-9]+/g, " ").trim();
const dayOf = (iso: string | null) => {
  if (!iso) return null;
  const d = new Date(iso);
  return Number.isFinite(d.getTime()) ? istDay(d) : null;
};

/**
 * Consolidates repeated filings without dropping a record (rule in the file header). Filings only; other events
 * pass through untouched. The input is newest first; the merged event keeps the first member's place.
 */
export function consolidate(events: IntelEvent[]): IntelEvent[] {
  const out: IntelEvent[] = [];
  const groups: Array<{ at: number; members: IntelEvent[] }> = [];
  for (const ev of events) {
    if (!ev.filing || !ev.symbol) {
      out.push(ev);
      continue;
    }
    const g = groups.find(({ members }) => members[0].symbol === ev.symbol && members.some((m) =>
      (m.org != null && ev.org != null && m.org !== ev.org && minutes(m.at, ev.at) <= DUPLICATE_WINDOW_MIN)
      || (m.org === ev.org && norm(m.title) === norm(ev.title) && dayOf(m.at) != null && dayOf(m.at) === dayOf(ev.at))));
    if (g) {
      g.members.push(ev);
      continue;
    }
    groups.push({ at: out.length, members: [ev] });
    out.push(ev);
  }
  for (const { at, members } of groups) {
    if (members.length === 1) continue;
    // The NSE copy leads; else the earliest filed.
    const lead = members.find((m) => m.org === "NSE") ?? [...members].sort((a, b) => a.sortAt - b.sortAt)[0];
    out[at] = withSources({
      ...lead,
      // The lead's own record first, then the copies, in the order they were filed.
      records: [...lead.records, ...members.filter((m) => m !== lead).sort((a, b) => a.sortAt - b.sortAt).flatMap((m) => m.records)],
      ai: lead.ai ?? members.find((m) => m.ai)?.ai ?? null,
      sector: lead.sector ?? members.find((m) => m.sector)?.sector ?? null,
      peers: lead.peers.length ? lead.peers : members.find((m) => m.peers.length)?.peers ?? [],
      timing: lead.timing ?? members.find((m) => m.timing)?.timing ?? null,
    });
  }
  return out;
}

const crore = (n: number) => `₹${fmtNum(Math.abs(n))} Cr`;
const signedPct = (n: number, digits = 2) => `${n > 0 ? "+" : n < 0 ? "−" : ""}${fmtNum(Math.abs(n), digits)}%`;

export function dealEvent(d: DealRow, i: number, source: string | null): IntelEvent {
  const kind = d.kind === "block" ? "Block deal" : d.kind === "bulk" ? "Bulk deal" : "Deal";
  const verb = d.side === "BUY" ? "bought" : d.side === "SELL" ? "sold" : "traded";
  const qty = d.quantity != null ? (d.quantity >= 1e5 ? `${(d.quantity / 1e5).toFixed(2)} L` : fmtNum(d.quantity)) : null;
  const value = d.valueCr != null ? `₹${fmtNum(d.valueCr, 2)} Cr` : null;
  const price = d.price != null ? `₹${fmtNum(d.price, 2)} average` : null;
  const id = `deal-${d.date ?? "nodate"}-${d.kind ?? "deal"}-${d.symbol}-${i}`;
  return {
    id,
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
    org: `NSE (${d.kind === "block" ? "block" : "bulk"} deal file)`,
    sourceLabel: "Exchange disclosure (NSE)",
    publishedAt: d.date,
    ingestedAt: d.ingestedAt,
    sector: null,
    peers: [],
    timing: null,
    facts: [
      { k: "Event ID", v: id, testId: "desk-event-fact-id" },
      { k: "Source", v: "Exchange disclosure (NSE) · confirmed, not inferred", testId: "desk-event-fact-source" },
      { k: "Trade date", v: d.date ? eventWhen(d.date).full : "—", note: "NSE publishes the day's deals after the close", testId: "desk-event-fact-published" },
      { k: "Ingested", v: d.ingestedAt ? eventWhen(d.ingestedAt).full : "—", note: d.ingestedAt ? "when Nivesh loaded NSE's deal file" : "not sent", testId: "desk-event-fact-ingested" },
    ],
    ai: null,
    deal: {
      kind: d.kind, client: d.client, side: d.side, quantity: d.quantity, price: d.price, valueCr: d.valueCr, pctOfShares: d.pctOfShares,
      sharesPeriodEnd: d.sharesPeriodEnd, closeOnDay: d.closeOnDay, prevClose: d.prevClose, nextDate: d.nextDate, nextClose: d.nextClose,
      priceVsClosePct: d.priceVsClosePct, ingestedAt: d.ingestedAt,
    },
    records: [],
    alertCategory: "deal",
    sectorIndex: null,
  };
}

export function circularEvent(c: Circular, i: number): IntelEvent {
  const kind = c.kind ? CIRCULAR_KIND_LABEL[c.kind] ?? c.kind : "Circular";
  const id = `sebi-${c.issuedOn ?? "nodate"}-${i}`;
  return {
    id,
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
    org: "SEBI",
    sourceLabel: `SEBI ${kind.toLowerCase()}`,
    publishedAt: c.issuedOn,
    ingestedAt: null,
    sector: null,
    peers: [],
    timing: null,
    facts: [
      { k: "Event ID", v: id, testId: "desk-event-fact-id" },
      { k: "Source", v: `SEBI ${kind.toLowerCase()} (sebi.gov.in)`, testId: "desk-event-fact-source" },
      { k: "Issued", v: c.issuedOn ? eventWhen(c.issuedOn).full : "—", testId: "desk-event-fact-published" },
    ],
    ai: null,
    deal: null,
    records: [],
    alertCategory: null,
    sectorIndex: null,
  };
}

const flowWords = (who: string, n: number | null) =>
  n == null ? `${who}: no figure` : n > 0 ? `${who} net bought ${crore(n)}` : n < 0 ? `${who} net sold ${crore(n)}` : `${who} flat`;

export function flowEvent(r: FiiDiiFlowRow): IntelEvent {
  const fii = r.fii_net ?? null;
  const dii = r.dii_net ?? null;
  const date = r.date ?? null;
  const id = `fiidii-${date ?? "nodate"}`;
  return {
    id,
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
    org: "NSE",
    sourceLabel: "Exchange data (NSE, provisional)",
    publishedAt: date,
    ingestedAt: null,
    sector: null,
    peers: [],
    timing: null,
    facts: [
      { k: "Event ID", v: id, testId: "desk-event-fact-id" },
      { k: "Source", v: "NSE provisional FII / DII figures", testId: "desk-event-fact-source" },
      { k: "Session", v: date ? eventWhen(date).full : "—", testId: "desk-event-fact-published" },
    ],
    ai: null,
    deal: null,
    records: [],
    alertCategory: null,
    sectorIndex: null,
  };
}

export interface SectorMove {
  index: string;
  sector: string;
  close: number | null;
  date: string | null;
  ret1d: number;
}

/** A sector index that moved SECTOR_MOVE_MIN % or more in its last session. */
export function sectorEvent(s: SectorMove, source: string | null): IntelEvent {
  const id = `sector-${s.index}-${s.date ?? "nodate"}`;
  return {
    id,
    group: "sector",
    type: "Sector move",
    at: s.date,
    sortAt: sortTime(s.date),
    title: `${s.index} ${s.ret1d > 0 ? "rose" : "fell"} ${fmtNum(Math.abs(s.ret1d), 2)}%`,
    sub: `${s.sector} · close ${s.close != null ? fmtNum(s.close, 2) : "—"} · ${signedPct(s.ret1d)} on the session`,
    sentiment: null,
    impact: null,
    symbol: null,
    name: null,
    flow: null,
    read: null,
    sources: [{ text: `${source ?? "NSE index close"}${s.date ? ` · end of day ${eventWhen(s.date).full}` : ""}`, url: null }],
    filing: null,
    org: "NSE",
    sourceLabel: "Exchange index close (NSE)",
    publishedAt: s.date,
    ingestedAt: null,
    sector: { name: s.sector, source: s.index },
    peers: [],
    timing: null,
    facts: [
      { k: "Event ID", v: id, testId: "desk-event-fact-id" },
      { k: "Source", v: source ?? "NSE index close", testId: "desk-event-fact-source" },
      { k: "Session", v: s.date ? eventWhen(s.date).full : "—", testId: "desk-event-fact-published" },
      { k: "1-day return", v: signedPct(s.ret1d), note: "close against the index's previous close", testId: "desk-event-fact-return" },
    ],
    ai: null,
    deal: null,
    records: [],
    alertCategory: null,
    sectorIndex: s.index,
  };
}

export type SourceKey = "filings" | "deals" | "circulars" | "flows" | "sectors";
export type SourceState = "ok" | "failed" | "loading";

export interface EventFeed {
  status: "loading" | "error" | "ready" | "disabled";
  /** Newest first. */
  events: IntelEvent[];
  /** What each source added, and (filings) how many matched in the window before the route's limit. */
  counts: {
    filings: number; filingsTotal: number | null; deals: number; dealsTotal: number | null; circulars: number; flows: number;
    sectors: number;
    /** Filing records read, before duplicates were consolidated into `filings` events. */
    records: number;
  };
  /** Sources that failed while others answered: the list is partial. */
  failed: SourceKey[];
  error: unknown;
  /** As-of stamps the sources sent, for the source line (filings: the latest ingestion time the rows carry). */
  asOf: { deals: string | null; circulars: string | null; flows: string | null; sectors: string | null; filings: string | null };
  dealsSource: string | null;
  circularsSource: string | null;
  /** The provenance lookup failed: rows have no ingestion time, sector or peers (said on screen). */
  provenanceError: string | null;
  /** Each source the chip reads, and how it answered. */
  sourceStates: Partial<Record<SourceKey, SourceState>>;
  refetch: () => void;
}

interface DeskFeed {
  rows: FilingRow[];
  total: number;
  provenanceError: string | null;
  family: FilingFamily | null;
}

type DeskFeedParams = FeedParams & { family?: FilingFamily; provenance: 1 };

/** GET /api/filings/feed with provenance (and a family): the feed's own contract, plus the provenance block. */
async function fetchFeed(params: DeskFeedParams, signal?: AbortSignal): Promise<DeskFeed> {
  const res = await http({ path: "/api/filings/feed", query: { ...params }, signal });
  const parsed = FeedRespC.passthrough().safeParse(res.data);
  if (!parsed.success) throw ApiError.contractDrift(`filings.feed: ${parsed.error.issues[0]?.message ?? "unexpected shape"}`, parsed.error);
  const prov = rec((parsed.data as Raw).provenance);
  return { rows: parsed.data.rows, total: parsed.data.total ?? parsed.data.rows.length, provenanceError: str(prov.error), family: params.family ?? null };
}

/** Every event behind one chip, merged newest first. */
export function useIntelEvents(chip: IntelChip): EventFeed {
  const def = INTEL_CHIPS.find((c) => c.key === chip) ?? INTEL_CHIPS[0];
  const asks: DeskFeedParams[] = [];
  const limit = def.categories.length + def.families.length > 1 ? LIMIT_GROUPED : LIMIT_SINGLE;
  if (!def.disabled) {
    for (const category of def.categories) asks.push({ days: FEED_DAYS, category, sort: "latest", limit, provenance: 1 });
    for (const family of def.families) asks.push({ days: FEED_DAYS, family, sort: "latest", limit, provenance: 1 });
  }
  const filings = useQueries({
    queries: asks.map((params) => ({
      queryKey: ["copilot", "desk", "filings", params],
      queryFn: ({ signal }: { signal?: AbortSignal }) => fetchFeed(params, signal),
      staleTime: 60_000,
      retry: noRetry4xx,
    })),
  });
  const deals = useDeals(def.deals);
  const circulars = useCirculars(def.circulars);
  const flows = useInstitutionalFlows(90);
  const sectorQ = useSectorReturns();
  const all = chip === "all";

  type Part = { key: SourceKey; pending: boolean; error: unknown; failed: boolean; refetch: () => void };
  const parts: Part[] = [];
  for (const q of filings) parts.push({ key: "filings", pending: q.isPending, failed: q.isError, error: q.error, refetch: () => void q.refetch() });
  if (def.deals) parts.push({ key: "deals", pending: deals.isPending, failed: deals.isError, error: deals.error, refetch: () => void deals.refetch() });
  if (def.circulars) parts.push({ key: "circulars", pending: circulars.isPending, failed: circulars.isError, error: circulars.error, refetch: () => void circulars.refetch() });
  if (def.flows) parts.push({ key: "flows", pending: flows.isPending, failed: flows.isError, error: flows.error, refetch: () => void flows.refetch() });
  if (def.sectors) parts.push({ key: "sectors", pending: sectorQ.isPending, failed: sectorQ.isError, error: sectorQ.error, refetch: () => void sectorQ.refetch() });

  const refetch = () => {
    for (const p of parts) if (p.failed) p.refetch();
  };
  const failedParts = parts.filter((p) => p.failed);
  const sourceStates: EventFeed["sourceStates"] = {};
  for (const p of parts) {
    const prev = sourceStates[p.key];
    const s: SourceState = p.failed ? "failed" : p.pending ? "loading" : "ok";
    sourceStates[p.key] = prev === "failed" || s === "failed" ? "failed" : prev === "loading" || s === "loading" ? "loading" : "ok";
  }
  const empty = { filings: 0, filingsTotal: null, deals: 0, dealsTotal: null, circulars: 0, flows: 0, sectors: 0, records: 0 };
  let latestFiling: string | null = null;
  for (const q of filings) {
    for (const r of q.data?.rows ?? []) {
      const t = str((r as unknown as Raw).ingested_at);
      if (t && (!latestFiling || new Date(t).getTime() > new Date(latestFiling).getTime())) latestFiling = t;
    }
  }
  const asOf = {
    deals: deals.data?.asOf ?? null, circulars: circulars.data?.asOf ?? null, flows: flows.data?.as_of ?? null,
    sectors: sectorQ.data?.asOf ?? null, filings: latestFiling,
  };
  const provenanceError = filings.map((q) => q.data?.provenanceError ?? null).find((e) => e != null) ?? null;
  const base = { asOf, dealsSource: deals.data?.source ?? null, circularsSource: circulars.data?.source ?? null, provenanceError, sourceStates, refetch };
  if (def.disabled) return { status: "disabled", events: [], counts: empty, failed: [], error: null, ...base };
  if (parts.length && failedParts.length === parts.length) {
    return { status: "error", events: [], counts: empty, failed: [...new Set(failedParts.map((p) => p.key))], error: failedParts[0].error, ...base };
  }
  if (parts.some((p) => p.pending)) return { status: "loading", events: [], counts: empty, failed: [], error: null, ...base };

  let filingEvents: IntelEvent[] = [];
  const seen = new Set<string>();
  let filingsTotal: number | null = 0;
  for (const q of filings) {
    if (!q.isSuccess) continue;
    const d = q.data;
    filingsTotal = filingsTotal == null ? null : filingsTotal + d.total;
    for (const r of d.rows) {
      if (seen.has(r.id)) continue;
      seen.add(r.id);
      filingEvents.push(filingEvent(r, d.family));
    }
  }
  const nRecords = filingEvents.length;
  filingEvents.sort((a, b) => byTime(a.sortAt, b.sortAt));
  filingEvents = consolidate(filingEvents);
  const events: IntelEvent[] = [...filingEvents];

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
  let nSectors = 0;
  if (def.sectors && sectorQ.data) {
    const moved: SectorMove[] = sectorQ.data.sectors
      .flatMap((s): SectorMove[] => {
        const r = s.ret["1d"];
        return r != null && Math.abs(r) >= SECTOR_MOVE_MIN ? [{ index: s.index, sector: s.sector, close: s.close, date: s.date, ret1d: r }] : [];
      })
      .sort((a, b) => Math.abs(b.ret1d) - Math.abs(a.ret1d));
    for (const s of moved) events.push(sectorEvent(s, sectorQ.data.source));
    nSectors = moved.length;
  }
  // Newest first; Array.prototype.sort is stable, so same-time rows keep their source order (undated rows last).
  events.sort((a, b) => byTime(a.sortAt, b.sortAt));
  return {
    status: "ready",
    events,
    counts: {
      filings: filingEvents.length, filingsTotal: asks.length ? filingsTotal : null, deals: nDeals, dealsTotal: deals.data?.total ?? null,
      circulars: nCirculars, flows: nFlows, sectors: nSectors, records: nRecords,
    },
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
  /** quantity ÷ the company's total shares × 100, and the shareholding period the share count is from. */
  pctOfShares: number | null;
  sharesPeriodEnd: string | null;
  /** The stock's close on the deal date, the previous close, and the next session's close. */
  closeOnDay: number | null;
  prevClose: number | null;
  nextDate: string | null;
  nextClose: number | null;
  /** The deal price against the day's close, percent. */
  priceVsClosePct: number | null;
  ingestedAt: string | null;
}

export interface DealsFeed {
  /** The latest deal date on record, and the first calendar day of the window ending there. */
  asOf: string | null;
  from: string | null;
  /** Calendar days in the window. */
  days: number | null;
  source: string | null;
  /** The route's statement that every row is an exchange disclosure. */
  disclosure: string | null;
  /** Rows sent, and deals matching in the window before the route's limit. */
  count: number | null;
  total: number | null;
  rows: DealRow[];
}

const positive = (v: unknown) => {
  const n = num(v);
  return n != null && n > 0 ? n : null;
};

async function fetchDeals(days: number, signal?: AbortSignal): Promise<DealsFeed> {
  const res = await http({ path: "/api/markets/deals", query: { days, kind: "all", limit: DEAL_LIMIT }, signal });
  const d = rec(res.data);
  if (!Array.isArray(d.rows)) throw ApiError.contractDrift("markets.deals: no rows list");
  const rows: DealRow[] = d.rows.flatMap((v): DealRow[] => {
    const r = rec(v);
    const symbol = str(r.symbol)?.toUpperCase();
    if (!symbol) return [];
    const q = num(r.quantity);
    return [{
      date: str(r.date),
      kind: str(r.kind)?.toLowerCase() ?? null,
      symbol,
      client: str(r.client_name),
      side: str(r.side)?.toUpperCase() ?? null,
      quantity: q != null && q > 0 ? q : null,
      price: positive(r.avg_price),
      valueCr: num(r.value_cr),
      pctOfShares: num(r.pct_of_shares),
      sharesPeriodEnd: str(r.shares_period_end),
      closeOnDay: positive(r.close_on_day),
      prevClose: positive(r.prev_close),
      nextDate: str(r.next_date),
      nextClose: positive(r.next_close),
      priceVsClosePct: num(r.price_vs_close_pct),
      ingestedAt: str(r.ingested_at),
    }];
  });
  return {
    asOf: str(d.as_of), from: str(d.from), days: num(d.days), source: str(d.source), disclosure: str(d.disclosure),
    count: num(d.count), total: num(d.total), rows,
  };
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
