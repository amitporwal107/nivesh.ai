/**
 * Market Desk › Market Intelligence — the "Market Update" ticker's data. Owner, 5 Nov 2026: "a bloomberg style news ticker
 * where user can see latest quarterly results for today and waiting for tomorrow, fresh order books, M&A and all other
 * important aspects"; 6 Nov: "a summary of the everything, need not to display every thing — Market Update". Test cases:
 * test_reports/intel_news_ticker_TESTCASES.md.
 *
 * So the tape is a SUMMARY: one item per kind, each a count and a few names; the full lists stay in the event list below and
 * the Events calendar (a count opens its list, a name opens its event). No route of its own: it composes reads the view
 * already makes, with the same query keys, so the caches are shared:
 *   GET /api/markets/events-calendar/expectations?from=today&to=tomorrow&universe=all   results today and tomorrow, and the
 *        same route for the previous weekday alone (events-data.ts useResultsBoard), filtered here by the route's own list
 *        flags: F&O, Nifty 50 or all NSE
 *   GET /api/filings/feed?days=N&sort=latest&limit=1   the per-category counts (`facets`) of every filing since the window's
 *        start: the feed counts its whole window whatever the row limit, so the counts are complete (5 Nov: 61 M&A filings
 *        since 4 Nov, while a category read returns its newest 20)
 *   GET /api/filings/feed?category=…&provenance=1     the Intel chips Orders and M&A & actions (intel-data.ts useIntelEvents):
 *        the newest names, each linked to its event; re-read every minute while the ticker is mounted
 *   GET /api/markets/deals · /api/markets/fii-dii · /api/markets/sector-returns   the Bulk & block, FII / DII and Sector chips
 *   GET /api/markets/circulars                       SEBI circulars (the Regulatory chip's own list, so the ids match)
 *
 * The items, in this order:
 *   RESULTS          declared since the previous weekday (the warehouse loads a day's figures from about 20:30 IST: on 5 Nov
 *                    at 19:08 none of the 189 filed that day had figures, 88 of 4 Nov's did), newest first, each with revenue
 *                    and profit against the same quarter last year (a % only when last year's figure is positive; across a loss,
 *                    words; never beat / miss)
 *   FILED            filed today, figures not loaded yet
 *   DUE TODAY        today's meetings not filed yet
 *   TOMORROW         tomorrow's meetings
 *   ORDERS · M&A     the count since the window's start and the newest names. A board-meeting outcome or results filing from
 *                    a company with results in the window is not named under M&A (the classifier often files results there);
 *                    the count is the classifier's own
 *   CORPORATE ACTIONS  dividend, buyback, capex, fundraise and rating counts, each opening its chip
 *   DEALS            the latest deal day's count and its largest deals
 *   FII / DII        the latest session's net flows
 *   SEBI             circulars issued in the window
 *   SECTORS          NSE sector indices that moved 1 % or more in the last session (the Sector chip's rule)
 *
 * The window: from 00:00 IST of the weekday before today (Monday reaches back to Friday). The counts' route counts from 00:00
 * IST of its server's (UTC) date minus N days, so from 00:00 to 05:30 IST the counts start a day earlier; the count line then
 * names its own start.
 *
 * Wording: facts and counts; never buy / sell / target / stop loss / recommend / pick.
 */
import { useQuery } from "@tanstack/react-query";
import { http } from "@/services/api/http";
import { ApiError } from "@/services/api/errors";
import { FeedRespC } from "@/services/adapters/filings.adapter";
import { useResultsBoard, fmtExpVal, type Board, type BoardEvent, type ExpMetric, type Universe } from "../../events-data";
import {
  GROUP_COLOR, LIMIT_GROUPED, LIMIT_SINGLE, categoryKey, circularEvent, eventWhen, useCirculars, useIntelEvents,
  type IntelChip, type IntelEvent,
} from "../../intel-data";
import { istParts } from "../../overview-data";

/** Filings and their counts are re-read this often while the ticker is on screen. */
export const FILINGS_REFETCH_MS = 60_000;
/** Names shown in one item before "+n more". */
export const RESULTS_SHOWN = 8;
export const MEETINGS_SHOWN = 12;
export const FILINGS_SHOWN = 6;
export const DEALS_SHOWN = 3;
export const SEBI_SHOWN = 2;
export const SECTOR_SHOWN = 4;

export type TickerTag = "results" | "filed" | "due" | "tomorrow" | "orders" | "mna" | "actions" | "deals" | "flows" | "sebi" | "sector";

export const TAG_LABEL: Record<TickerTag, string> = {
  results: "Results", filed: "Results filed", due: "Due today", tomorrow: "Results tomorrow", orders: "Orders", mna: "M&A",
  actions: "Corporate actions", deals: "Deals", flows: "FII / DII", sebi: "SEBI", sector: "Sectors",
};

const TAG_COLOR: Record<TickerTag, string> = {
  results: GROUP_COLOR.results, filed: GROUP_COLOR.results, due: GROUP_COLOR.results, tomorrow: GROUP_COLOR.results,
  orders: "var(--mint)", mna: "var(--mint)", actions: "var(--mint)",
  deals: GROUP_COLOR.deals, flows: GROUP_COLOR.flows, sebi: GROUP_COLOR.regulatory, sector: GROUP_COLOR.sector,
};

/** Where a click goes: one event or a chip's whole list in the Intel list, a company's results panel, or the results board. */
export type TickerLink =
  | { kind: "intel"; chip: IntelChip; event: string | null }
  | { kind: "results"; event: string; universe: Universe }
  | { kind: "board" };

export type Tone = "up" | "down" | "flat" | "note";

export interface TickerFigure {
  key: string;
  label: string;
  text: string;
  tone: Tone;
}

/** One name (or one count) inside an item. */
export interface TickerEntry {
  key: string;
  text: string;
  figures: TickerFigure[];
  link: TickerLink | null;
}

export interface TickerItem {
  key: string;
  tag: TickerTag;
  label: string;
  color: string;
  /** The summary line: "21 since Thu 5 Nov". */
  count: string;
  entries: TickerEntry[];
  /** Names not shown, and the list that holds them all. */
  more: number;
  moreLink: TickerLink | null;
}

// ── time ───────────────────────────────────────────────────────────────────

/** Calendar arithmetic on an ISO day (in UTC, so no zone shifts). */
export const addIstDays = (iso: string, n: number) => {
  const d = new Date(`${iso}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + n);
  return d.toISOString().slice(0, 10);
};
const dayDiff = (a: string, b: string) => Math.round((new Date(`${a}T00:00:00Z`).getTime() - new Date(`${b}T00:00:00Z`).getTime()) / 864e5);

const DOW = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
/** "Thu 5 Nov" for an ISO day. */
export const dayLabel = (iso: string) => {
  const d = new Date(`${iso}T00:00:00Z`);
  return `${DOW[d.getUTCDay()]} ${d.getUTCDate()} ${MON[d.getUTCMonth()]}`;
};

/** The window: from 00:00 IST of the weekday before today (Monday reaches back to Friday). */
export function filingsWindow(now: Date): { from: string; ms: number; label: string } {
  const p = istParts(now);
  let d = addIstDays(p.iso, -1);
  while ([0, 6].includes(new Date(`${d}T00:00:00Z`).getUTCDay())) d = addIstDays(d, -1);
  return { from: d, ms: new Date(`${d}T00:00:00+05:30`).getTime(), label: dayLabel(d) };
}

/** The counts route's `days` for a window start, and the IST day its count really starts on (header: UTC server date). */
export function countsDays(now: Date, from: string): { days: number; from: string } {
  const serverDay = now.toISOString().slice(0, 10);
  const days = Math.max(1, dayDiff(serverDay, from));
  return { days, from: addIstDays(serverDay, -days) };
}

const timeOf = (iso: string | null) => {
  if (!iso) return NaN;
  return new Date(/^\d{4}-\d{2}-\d{2}$/.test(iso) ? `${iso}T23:59:59+05:30` : iso).getTime();
};

/**
 * The first `cap` distinct companies of a newest- (or largest-) first list, and how many of the list they stand for: a company
 * that filed twice, or both sides of one block deal, is named once (5 Nov real data: ASHOKLEY twice under M&A, PIIND twice
 * under deals).
 */
function distinctNames(list: IntelEvent[], cap: number): { shown: IntelEvent[]; covered: number } {
  const shown: IntelEvent[] = [];
  const keys = new Set<string>();
  for (const e of list) {
    const k = e.symbol ?? e.id;
    if (keys.has(k)) continue;
    if (shown.length >= cap) break;
    keys.add(k);
    shown.push(e);
  }
  // filings the names stand for: an event that consolidated repeats (IntelTab consolidate) counts each of its records
  return { shown, covered: list.filter((e) => keys.has(e.symbol ?? e.id)).reduce((n, e) => n + Math.max(1, e.records.length), 0) };
}

const fmtPct = (n: number, digits = 1) => `${n > 0 ? "▲" : n < 0 ? "▼" : ""}${Math.abs(n).toFixed(digits)}%`;
const toneOf = (n: number): Tone => (n > 0 ? "up" : n < 0 ? "down" : "flat");
const plural = (n: number, one: string, many: string) => `${n.toLocaleString("en-IN")} ${n === 1 ? one : many}`;

// ── results ────────────────────────────────────────────────────────────────

export function inUniverse(e: BoardEvent, u: Universe): boolean {
  return u === "all" || (u === "fno" ? e.inFno === true : e.inN50 === true);
}

/** Filed against the same quarter last year: a % only when last year's figure is positive; across a loss, words. */
export function yoy(filed: number, lastYear: number | null): { change: number | null; note: string | null } {
  if (lastYear == null || !Number.isFinite(lastYear)) return { change: null, note: null };
  if (lastYear > 0) return filed < 0 ? { change: null, note: "turned to a loss" } : { change: (filed / lastYear - 1) * 100, note: null };
  if (lastYear < 0 && filed > 0) return { change: null, note: "from a loss" };
  return { change: null, note: null };
}

const METRIC_LABEL: Record<string, string> = { revenue: "Rev", pat: "PAT" };

/** Revenue and profit, each as its change on the year; the filed figure itself when there is nothing to compare with. */
export function resultFigures(metrics: ExpMetric[]): TickerFigure[] {
  return ["revenue", "pat"].flatMap((k): TickerFigure[] => {
    const m = metrics.find((x) => x.key === k);
    const v = m?.filed?.value;
    if (!m || v == null || !Number.isFinite(v)) return [];
    const y = yoy(v, m.lastYearQuarter);
    if (y.change != null) return [{ key: k, label: METRIC_LABEL[k], text: `${fmtPct(y.change)} YoY`, tone: toneOf(y.change) }];
    if (y.note) return [{ key: k, label: METRIC_LABEL[k], text: y.note, tone: "note" }];
    return [{ key: k, label: METRIC_LABEL[k], text: fmtExpVal(v, m.unit), tone: "flat" }];
  });
}

const filedAt = (e: BoardEvent) => e.metrics.map((m) => m.filed?.broadcastAt ?? null).find(Boolean) ?? e.filing?.filedAt ?? null;
const resultsLink = (e: BoardEvent, u: Universe): TickerLink => ({ kind: "results", event: e.id, universe: u });
const byNewest = (a: BoardEvent, b: BoardEvent) => (timeOf(filedAt(b)) || 0) - (timeOf(filedAt(a)) || 0);

function names(tag: TickerTag, count: string, list: BoardEvent[], cap: number, u: Universe, withFigures = false): TickerItem | null {
  if (!list.length) return null;
  const shown = list.slice(0, cap);
  return {
    key: tag, tag, label: TAG_LABEL[tag], color: TAG_COLOR[tag], count,
    entries: shown.map((e) => ({ key: e.id, text: e.symbol, figures: withFigures ? resultFigures(e.metrics) : [], link: resultsLink(e, u) })),
    more: list.length - shown.length, moreLink: { kind: "board" },
  };
}

/** RESULTS · FILED · DUE TODAY · TOMORROW (rules in the header). */
export function resultItems(board: Board, prev: Board | null, today: string, tomorrow: string, u: Universe, windowLabel: string): TickerItem[] {
  const evs = board.events.filter((e) => inUniverse(e, u));
  const prevEvs = (prev?.events ?? []).filter((e) => inUniverse(e, u) && e.eventDate < today);
  const todays = evs.filter((e) => e.eventDate === today);
  const declared = [...todays, ...prevEvs].filter((x) => x.filedState === "figures").sort(byNewest);
  const pending = todays.filter((x) => x.filedState === "pending").sort(byNewest);
  const due = todays.filter((x) => x.status === "upcoming").sort((a, b) => a.symbol.localeCompare(b.symbol));
  const tom = evs.filter((e) => e.eventDate === tomorrow).sort((a, b) => a.symbol.localeCompare(b.symbol));
  return [
    names("results", `${plural(declared.length, "declared", "declared")} since ${windowLabel}`, declared, RESULTS_SHOWN, u, true),
    names("filed", `${plural(pending.length, "filed", "filed")} today, figures not loaded yet`, pending, MEETINGS_SHOWN, u),
    names("due", `${plural(due.length, "meeting", "meetings")} today`, due, MEETINGS_SHOWN, u),
    names("tomorrow", `${dayLabel(tomorrow)} · ${plural(tom.length, "meeting", "meetings")}`, tom, MEETINGS_SHOWN, u),
  ].filter((x): x is TickerItem => x != null);
}

// ── filings ────────────────────────────────────────────────────────────────

const RESULTS_SUBJECT = /board meeting|financial result/i;

/** The corporate actions the summary counts, each with the Intel chip that lists it. */
const ACTIONS: Array<{ category: string; label: string; chip: IntelChip }> = [
  { category: "dividend", label: "Dividend", chip: "mna" },
  { category: "buyback", label: "Buyback", chip: "mna" },
  { category: "capex", label: "Capex", chip: "announcements" },
  { category: "qip", label: "Fundraise", chip: "announcements" },
  { category: "rating", label: "Rating", chip: "announcements" },
];

/** The newest filings of one category in the window (rule in the header), newest first. */
export function windowFilings(events: IntelEvent[], category: string, startMs: number, resultsDays: ReadonlySet<string>): IntelEvent[] {
  return events.filter((e) => {
    if (categoryKey(e.filing?.category) !== category) return false;
    if (!(timeOf(e.publishedAt ?? e.at) >= startMs)) return false;
    return !(e.symbol && resultsDays.has(e.symbol) && RESULTS_SUBJECT.test(e.title));
  });
}

/**
 * ORDERS or M&A: the count since the window's start and the newest names. `count` is the counts route's (complete); without
 * it the names read are counted, with "+" when the read hit its row limit.
 */
export function filingItem(tag: "orders" | "mna", chip: IntelChip, list: IntelEvent[], count: number | null, atLimit: boolean, countLabel: string): TickerItem | null {
  const n = count ?? list.length;
  if (n === 0 && !list.length) return null;
  const { shown, covered } = distinctNames(list, FILINGS_SHOWN);
  return {
    key: tag, tag, label: TAG_LABEL[tag], color: TAG_COLOR[tag],
    count: `${n.toLocaleString("en-IN")}${count == null && atLimit ? "+" : ""} since ${countLabel}`,
    entries: shown.map((e) => ({ key: e.id, text: e.symbol ?? e.name ?? e.title, figures: [], link: { kind: "intel", chip, event: e.id } })),
    more: Math.max(0, n - covered), moreLink: { kind: "intel", chip, event: null },
  };
}

export function actionsItem(counts: Record<string, number> | null, countLabel: string): TickerItem | null {
  if (!counts) return null;
  const entries: TickerEntry[] = ACTIONS.flatMap((a) => {
    const n = counts[a.category] ?? 0;
    return n > 0 ? [{ key: a.category, text: `${a.label} ${n.toLocaleString("en-IN")}`, figures: [], link: { kind: "intel" as const, chip: a.chip, event: null } }] : [];
  });
  if (!entries.length) return null;
  const total = ACTIONS.reduce((s, a) => s + (counts[a.category] ?? 0), 0);
  return { key: "actions", tag: "actions", label: TAG_LABEL.actions, color: TAG_COLOR.actions, count: `${total.toLocaleString("en-IN")} since ${countLabel}`, entries, more: 0, moreLink: null };
}

// ── deals, flows, SEBI, sectors ────────────────────────────────────────────

const crore = (n: number, signed = false) => `${signed ? (n < 0 ? "−" : "+") : n < 0 ? "−" : ""}₹${Math.abs(n).toLocaleString("en-IN", { maximumFractionDigits: n !== 0 && Math.abs(n) < 10 ? 2 : 0 })} cr`;

export function dealsItem(events: IntelEvent[]): TickerItem | null {
  const dated = events.filter((e) => e.deal && e.at);
  const latest = dated.reduce<string | null>((m, e) => (!m || (e.at as string) > m ? (e.at as string) : m), null);
  if (!latest) return null;
  const day = dated.filter((e) => e.at === latest).sort((a, b) => (b.deal?.valueCr ?? -Infinity) - (a.deal?.valueCr ?? -Infinity));
  const { shown, covered } = distinctNames(day, DEALS_SHOWN);
  return {
    key: "deals", tag: "deals", label: TAG_LABEL.deals, color: TAG_COLOR.deals,
    count: `${plural(day.length, "bulk / block deal", "bulk / block deals")} on ${eventWhen(latest).short}, the largest`,
    entries: shown.map((e) => ({
      key: e.id, text: e.symbol ?? "—",
      figures: e.deal?.valueCr != null ? [{ key: "value", label: "", text: crore(e.deal.valueCr), tone: "flat" as Tone }] : [],
      link: { kind: "intel" as const, chip: "deals" as const, event: e.id },
    })),
    more: day.length - covered, moreLink: { kind: "intel", chip: "deals", event: null },
  };
}

export function flowsItem(events: IntelEvent[]): TickerItem | null {
  const e = events.find((x) => x.flow && x.at);
  if (!e || !e.flow) return null;
  const figures: TickerFigure[] = [];
  if (e.flow.fii != null) figures.push({ key: "fii", label: "FII net", text: crore(e.flow.fii, true), tone: toneOf(e.flow.fii) });
  if (e.flow.dii != null) figures.push({ key: "dii", label: "DII net", text: crore(e.flow.dii, true), tone: toneOf(e.flow.dii) });
  if (!figures.length) return null;
  return {
    key: "flows", tag: "flows", label: TAG_LABEL.flows, color: TAG_COLOR.flows, count: `${eventWhen(e.at).short}, cash market, provisional`,
    entries: [{ key: e.id, text: "", figures, link: { kind: "intel", chip: "flows", event: e.id } }], more: 0, moreLink: null,
  };
}

const clip = (s: string, n = 64) => (s.length > n ? `${s.slice(0, n - 1).trimEnd()}…` : s);

export function sebiItem(events: IntelEvent[], from: string, windowLabel: string): TickerItem | null {
  const list = events.filter((e) => e.at && e.at.slice(0, 10) >= from).sort((a, b) => (b.at ?? "").localeCompare(a.at ?? ""));
  if (!list.length) return null;
  const shown = list.slice(0, SEBI_SHOWN);
  return {
    key: "sebi", tag: "sebi", label: TAG_LABEL.sebi, color: TAG_COLOR.sebi, count: `${plural(list.length, "circular", "circulars")} since ${windowLabel}`,
    entries: shown.map((e) => ({ key: e.id, text: clip(e.title), figures: [], link: { kind: "intel" as const, chip: "regulatory" as const, event: e.id } })),
    more: list.length - shown.length, moreLink: { kind: "intel", chip: "regulatory", event: null },
  };
}

export function sectorItem(events: IntelEvent[]): TickerItem | null {
  const moves = events.filter((e) => e.group === "sector");
  if (!moves.length) return null;
  const shown = moves.slice(0, SECTOR_SHOWN);
  return {
    key: "sector", tag: "sector", label: TAG_LABEL.sector, color: TAG_COLOR.sector,
    count: `moved 1% or more on ${eventWhen(moves[0].at).short}`,
    entries: shown.map((e) => {
      const m = e.title.match(/^(.*) (rose|fell) ([\d.,]+)%$/);
      const pct = m ? (m[2] === "fell" ? -1 : 1) * Number(m[3].replace(/,/g, "")) : null;
      return {
        key: e.id, text: m ? m[1] : e.title,
        figures: pct != null ? [{ key: "pct", label: "", text: fmtPct(pct, 2), tone: toneOf(pct) }] : [],
        link: { kind: "intel" as const, chip: "sector" as const, event: e.id },
      };
    }),
    more: moves.length - shown.length, moreLink: { kind: "intel", chip: "sector", event: null },
  };
}

// ── the counts ─────────────────────────────────────────────────────────────

/** GET /api/filings/feed?days=&sort=latest&limit=1 — only its per-category counts (`facets`) are used. */
export function useFilingCounts(days: number) {
  return useQuery<Record<string, number>>({
    queryKey: ["copilot", "desk", "ticker-counts", days],
    staleTime: 60_000,
    refetchInterval: FILINGS_REFETCH_MS,
    retry: (n, e) => !(e instanceof ApiError && e.status != null && e.status >= 400 && e.status < 500) && n < 1,
    queryFn: async ({ signal }) => {
      const res = await http({ path: "/api/filings/feed", query: { days, sort: "latest", limit: 1 }, signal });
      const parsed = FeedRespC.safeParse(res.data);
      if (!parsed.success || !parsed.data.facets) throw ApiError.contractDrift("filings.feed: no facets");
      return parsed.data.facets;
    },
  });
}

// ── the hook ───────────────────────────────────────────────────────────────

export type SourceName = "results" | "previous day's results" | "filing counts" | "orders" | "M&A" | "deals" | "FII / DII" | "SEBI circulars" | "sector moves";

export interface TickerFeed {
  status: "loading" | "ready" | "error";
  items: TickerItem[];
  /** Sources that failed while others answered. */
  failed: SourceName[];
  /** Sources still loading (the tape shows what has arrived). */
  pending: SourceName[];
  /** The newest filing time read (the band's "as of"). */
  latestAt: string | null;
  window: { from: string; label: string };
  today: string;
  tomorrow: string;
  refetch: () => void;
}

export function useNewsTicker(universe: Universe, now: Date): TickerFeed {
  const today = istParts(now).iso;
  const tomorrow = addIstDays(today, 1);
  const win = filingsWindow(now);
  const cd = countsDays(now, win.from);
  const board = useResultsBoard(today, tomorrow, "all", true);
  // the previous weekday's declared results (the route's window is at most 3 days, so it is a read of its own)
  const prevBoard = useResultsBoard(win.from, win.from, "all", true);
  const counts = useFilingCounts(cd.days);
  const orders = useIntelEvents("orders", { refetchMs: FILINGS_REFETCH_MS });
  const mna = useIntelEvents("mna", { refetchMs: FILINGS_REFETCH_MS });
  const deals = useIntelEvents("deals");
  const flows = useIntelEvents("flows");
  const sectors = useIntelEvents("sector");
  const circulars = useCirculars(true);

  const parts: Array<{ name: SourceName; pending: boolean; failed: boolean; refetch: () => void }> = [
    { name: "results", pending: board.isPending, failed: board.isError, refetch: () => void board.refetch() },
    { name: "previous day's results", pending: prevBoard.isPending, failed: prevBoard.isError, refetch: () => void prevBoard.refetch() },
    { name: "filing counts", pending: counts.isPending, failed: counts.isError, refetch: () => void counts.refetch() },
    { name: "orders", pending: orders.status === "loading", failed: orders.status === "error" || orders.failed.length > 0, refetch: orders.refetch },
    { name: "M&A", pending: mna.status === "loading", failed: mna.status === "error" || mna.failed.length > 0, refetch: mna.refetch },
    { name: "deals", pending: deals.status === "loading", failed: deals.status === "error", refetch: deals.refetch },
    { name: "FII / DII", pending: flows.status === "loading", failed: flows.status === "error", refetch: flows.refetch },
    { name: "SEBI circulars", pending: circulars.isPending, failed: circulars.isError, refetch: () => void circulars.refetch() },
    { name: "sector moves", pending: sectors.status === "loading", failed: sectors.status === "error", refetch: sectors.refetch },
  ];

  // companies with a results meeting in the window (today or the previous weekday), for the board-outcome rule
  const resultsDays = new Set([
    ...(board.data?.events ?? []).filter((e) => e.eventDate === today).map((e) => e.symbol),
    ...(prevBoard.data?.events ?? []).map((e) => e.symbol),
  ]);
  const facets = counts.data ?? null;
  const countLabel = dayLabel(facets ? cd.from : win.from);
  const atLimit = (f: typeof orders, limit: number) => f.events.reduce((n, e) => n + Math.max(1, e.records.length), 0) >= limit;

  const items: TickerItem[] = [];
  if (board.data) items.push(...resultItems(board.data, prevBoard.data ?? null, today, tomorrow, universe, win.label));
  const push = (x: TickerItem | null) => { if (x) items.push(x); };
  if (orders.status === "ready" || facets) {
    push(filingItem("orders", "orders", orders.status === "ready" ? windowFilings(orders.events, "orders", win.ms, resultsDays) : [],
      facets ? facets.orders ?? 0 : null, orders.status === "ready" && atLimit(orders, LIMIT_SINGLE), countLabel));
  }
  if (mna.status === "ready" || facets) {
    push(filingItem("mna", "mna", mna.status === "ready" ? windowFilings(mna.events, "mna", win.ms, resultsDays) : [],
      facets ? facets.mna ?? 0 : null, mna.status === "ready" && atLimit(mna, LIMIT_GROUPED), countLabel));
  }
  push(actionsItem(facets, countLabel));
  if (deals.status === "ready") push(dealsItem(deals.events));
  if (flows.status === "ready") push(flowsItem(flows.events));
  if (circulars.data) push(sebiItem(circulars.data.rows.map((c, i) => circularEvent(c, i)), win.from, win.label));
  if (sectors.status === "ready") push(sectorItem(sectors.events));

  let latestAt: string | null = null;
  for (const f of [orders, mna]) {
    for (const e of f.events) {
      const at = e.publishedAt ?? e.at;
      if (at && /T/.test(at) && (!latestAt || timeOf(at) > timeOf(latestAt))) latestAt = at;
    }
  }

  const failed = parts.filter((p) => p.failed).map((p) => p.name);
  const pending = parts.filter((p) => p.pending && !p.failed).map((p) => p.name);
  const status: TickerFeed["status"] = failed.length === parts.length ? "error" : items.length === 0 && pending.length > 0 ? "loading" : "ready";
  return {
    status, items, failed, pending, latestAt, window: { from: win.from, label: win.label }, today, tomorrow,
    refetch: () => { for (const p of parts) if (p.failed) p.refetch(); },
  };
}
