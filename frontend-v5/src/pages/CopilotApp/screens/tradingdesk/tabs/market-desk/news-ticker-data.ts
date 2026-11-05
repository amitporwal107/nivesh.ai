/**
 * Market Desk › Market Intelligence — the news ticker's data (owner, 5 Nov 2026: "a bloomberg style news ticker where user
 * can see latest quarterly results for today and waiting for tomorrow, fresh order books, M&A and all other important
 * aspects"). Test cases: test_reports/intel_news_ticker_TESTCASES.md.
 *
 * No route of its own. It composes reads the view already makes, with the same query keys, so the caches are shared with
 * the event list (IntelTab) and the Events calendar:
 *   GET /api/markets/events-calendar/expectations?from=today&to=tomorrow&universe=all   results today and tomorrow
 *        (events-data.ts useResultsBoard), filtered here by the route's own list flags: F&O, Nifty 50 or all NSE
 *   GET /api/filings/feed?category=…&provenance=1    the Intel chips Orders, M&A & actions and Announcements
 *        (intel-data.ts useIntelEvents), re-read every minute while the ticker is mounted
 *   GET /api/markets/deals · /api/markets/fii-dii · /api/markets/sector-returns   the Bulk & block, FII / DII and Sector chips
 *   GET /api/markets/circulars                       SEBI circulars (the Regulatory chip's own list, so the ids match)
 *
 * What goes on the tape, in this order:
 *   RESULTS          today's and the previous weekday's meetings whose figures are loaded (a second read of the same route
 *                    for that day: the warehouse loads a day's figures from about 20:30 IST, so on 5 Nov at 19:08 none of
 *                    today's 189 filed results had figures yet, while 88 of 4 Nov's did): revenue and profit, each against
 *                    the same quarter last year (both figures from the route). The % is shown only when last year's figure
 *                    is positive; a filed loss against a profit reads "turned to a loss", a profit against a loss "from a
 *                    loss". Never beat / miss.
 *   RESULTS FILED    filed today, figures not loaded yet
 *   DUE TODAY        today's meetings not filed yet (one item; each company opens its own results panel)
 *   TOMORROW         tomorrow's meetings (one item, the first TOMORROW_SHOWN companies and "+n more")
 *   ORDER · M&A · BUYBACK · DIVIDEND · CAPEX · FUNDRAISE · RATING
 *                    filings by the classifier's category, published since 00:00 IST of the previous weekday. Management
 *                    changes are left out (appointments are noise on a tape). A board-meeting outcome or results filing from
 *                    a company with results today is left out too: the classifier often files those under M&A or capex,
 *                    and the RESULTS item already covers the company.
 *   BLOCK / BULK DEAL  the latest deal date only, the DEALS_SHOWN largest by value
 *   FII / DII        the latest session
 *   SEBI             circulars issued in the filings window, at most SEBI_SHOWN
 *   SECTOR           NSE sector indices that moved 1 % or more in the last session (the Sector chip's rule), at most SECTOR_SHOWN
 *
 * Wording: facts and the exchange's own subject lines; never buy / sell / target / stop loss / recommend / pick.
 */
import { useResultsBoard, fmtExpVal, type Board, type BoardEvent, type ExpMetric, type Universe } from "../../events-data";
import {
  GROUP_COLOR, LIMIT_GROUPED, LIMIT_SINGLE, categoryKey, circularEvent, eventWhen, useCirculars, useIntelEvents, type IntelChip, type IntelEvent,
} from "../../intel-data";
import { istParts } from "../../overview-data";

/** Filings are re-read this often while the ticker is on screen. */
export const FILINGS_REFETCH_MS = 60_000;
export const TOMORROW_SHOWN = 15;
export const DEALS_SHOWN = 6;
export const SEBI_SHOWN = 3;
export const SECTOR_SHOWN = 4;

export type TickerTag =
  | "results" | "filed" | "due" | "tomorrow"
  | "order" | "mna" | "buyback" | "dividend" | "capex" | "fundraise" | "rating"
  | "deal" | "flows" | "sebi" | "sector";

export const TAG_LABEL: Record<TickerTag, string> = {
  results: "Results", filed: "Results filed", due: "Due today", tomorrow: "Results tomorrow",
  order: "Order", mna: "M&A", buyback: "Buyback", dividend: "Dividend", capex: "Capex", fundraise: "Fundraise", rating: "Rating",
  deal: "Deal", flows: "FII / DII", sebi: "SEBI", sector: "Sector",
};

const TAG_COLOR: Record<TickerTag, string> = {
  results: GROUP_COLOR.results, filed: GROUP_COLOR.results, due: GROUP_COLOR.results, tomorrow: GROUP_COLOR.results,
  order: "var(--mint)", mna: "var(--mint)", buyback: "var(--mint)", dividend: "var(--mint)", capex: "var(--mint)",
  fundraise: "var(--mint)", rating: "var(--mint)",
  deal: GROUP_COLOR.deals, flows: GROUP_COLOR.flows, sebi: GROUP_COLOR.regulatory, sector: GROUP_COLOR.sector,
};

/** The classifier categories the tape lists, with their tag and the Intel chip that holds them. */
const FILING_TAGS: Array<{ category: string; tag: TickerTag; chip: IntelChip }> = [
  { category: "orders", tag: "order", chip: "orders" },
  { category: "mna", tag: "mna", chip: "mna" },
  { category: "buyback", tag: "buyback", chip: "mna" },
  { category: "dividend", tag: "dividend", chip: "mna" },
  { category: "capex", tag: "capex", chip: "announcements" },
  { category: "qip", tag: "fundraise", chip: "announcements" },
  { category: "rating", tag: "rating", chip: "announcements" },
];

/** Where a click on an item goes: one event in the Intel list, or one company's results panel in the Events calendar. */
export type TickerLink =
  | { kind: "intel"; chip: IntelChip; event: string }
  | { kind: "results"; event: string; universe: Universe };

export interface TickerFigure {
  key: string;
  label: string;
  value: string;
  /** Percent against the same quarter last year (results) or the sign of a flow; null when not comparable. */
  change: number | null;
  /** Said instead of a % when the comparison is across a loss. */
  note: string | null;
  /** "yoy" = change is a % vs last year; "sign" = only the tone of `value` is coloured (flows). */
  kind: "yoy" | "sign" | "plain";
}

export interface TickerSymbol { symbol: string; link: TickerLink }

export interface TickerItem {
  key: string;
  tag: TickerTag;
  label: string;
  color: string;
  symbol: string | null;
  /** The company's name or the item's own sentence. */
  text: string;
  figures: TickerFigure[];
  /** "17:05" today, "4 Nov" before. */
  when: string | null;
  link: TickerLink | null;
  /** Grouped items (due today, tomorrow): each company opens its own results panel. */
  group: { symbols: TickerSymbol[]; more: number; moreLink: TickerLink | null } | null;
}

// ── time ───────────────────────────────────────────────────────────────────

/** Calendar arithmetic on an ISO day (in UTC, so no zone shifts). */
export const addIstDays = (iso: string, n: number) => {
  const d = new Date(`${iso}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + n);
  return d.toISOString().slice(0, 10);
};

const DOW = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
/** "Thu 5 Nov" for an ISO day. */
export const dayLabel = (iso: string) => {
  const d = new Date(`${iso}T00:00:00Z`);
  return `${DOW[d.getUTCDay()]} ${d.getUTCDate()} ${MON[d.getUTCMonth()]}`;
};

/** The filings window: from 00:00 IST of the weekday before today (Monday reaches back to Friday). */
export function filingsWindow(now: Date): { from: string; ms: number; label: string } {
  const p = istParts(now);
  let d = addIstDays(p.iso, -1);
  while ([0, 6].includes(new Date(`${d}T00:00:00Z`).getUTCDay())) d = addIstDays(d, -1);
  return { from: d, ms: new Date(`${d}T00:00:00+05:30`).getTime(), label: dayLabel(d) };
}

const timeOf = (iso: string | null) => {
  if (!iso) return NaN;
  return new Date(/^\d{4}-\d{2}-\d{2}$/.test(iso) ? `${iso}T23:59:59+05:30` : iso).getTime();
};

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

function resultFigures(metrics: ExpMetric[]): TickerFigure[] {
  return ["revenue", "pat"].flatMap((k): TickerFigure[] => {
    const m = metrics.find((x) => x.key === k);
    const v = m?.filed?.value;
    if (!m || v == null || !Number.isFinite(v)) return [];
    const y = yoy(v, m.lastYearQuarter);
    return [{ key: k, label: METRIC_LABEL[k], value: fmtExpVal(v, m.unit), change: y.change, note: y.note, kind: "yoy" }];
  });
}

const filedAt = (e: BoardEvent) => e.metrics.map((m) => m.filed?.broadcastAt ?? null).find(Boolean) ?? e.filing?.filedAt ?? null;
const resultsLink = (e: BoardEvent, u: Universe): TickerLink => ({ kind: "results", event: e.id, universe: u });

/** "Q2 FY27 (Jul–Sep 2026)" → "Q2 FY27". */
const shortPeriod = (p: string | null) => (p ? p.replace(/\s*\(.*\)\s*$/, "") : null);

/**
 * The results items: today's and the previous weekday's meetings with filed figures (newest filing first; the warehouse
 * loads a day's figures from about 20:30 IST, so the morning tape leads with the evening before), today's filings whose
 * figures are not loaded yet, today's meetings still to come, and tomorrow's.
 */
export function resultItems(board: Board, prev: Board | null, today: string, tomorrow: string, u: Universe): TickerItem[] {
  const evs = board.events.filter((e) => inUniverse(e, u));
  const prevEvs = (prev?.events ?? []).filter((e) => inUniverse(e, u) && e.eventDate < today);
  const byNewest = (a: BoardEvent, b: BoardEvent) => (timeOf(filedAt(b)) || 0) - (timeOf(filedAt(a)) || 0);
  const out: TickerItem[] = [];
  const todays = evs.filter((e) => e.eventDate === today);
  const declared = [...todays, ...prevEvs].filter((x) => x.filedState === "figures").sort(byNewest);
  for (const e of declared) {
    const at = filedAt(e);
    const p = shortPeriod(e.periodLabel);
    out.push({
      key: `res-${e.id}`, tag: "results", label: TAG_LABEL.results, color: TAG_COLOR.results, symbol: e.symbol,
      text: p ? `${p} results` : "Results", figures: resultFigures(e.metrics),
      when: at ? eventWhen(at).short : dayLabel(e.eventDate), link: resultsLink(e, u), group: null,
    });
  }
  for (const e of todays.filter((x) => x.filedState === "pending").sort(byNewest)) {
    const at = filedAt(e);
    out.push({
      key: `filed-${e.id}`, tag: "filed", label: TAG_LABEL.filed, color: TAG_COLOR.filed, symbol: e.symbol,
      text: "figures not loaded yet", figures: [], when: at ? eventWhen(at).short : null, link: resultsLink(e, u), group: null,
    });
  }
  const group = (tag: TickerTag, day: string, list: BoardEvent[], cap: number): TickerItem | null => {
    if (!list.length) return null;
    const sorted = [...list].sort((a, b) => a.symbol.localeCompare(b.symbol));
    const shown = sorted.slice(0, cap);
    return {
      key: `${tag}-${day}`, tag, label: TAG_LABEL[tag], color: TAG_COLOR[tag], symbol: null,
      text: `${dayLabel(day)} · ${list.length} ${list.length === 1 ? "company" : "companies"}`, figures: [], when: null, link: null,
      group: { symbols: shown.map((e) => ({ symbol: e.symbol, link: resultsLink(e, u) })), more: sorted.length - shown.length, moreLink: null },
    };
  };
  const due = group("due", today, todays.filter((x) => x.status === "upcoming"), TOMORROW_SHOWN);
  if (due) out.push(due);
  const tom = group("tomorrow", tomorrow, evs.filter((e) => e.eventDate === tomorrow), TOMORROW_SHOWN);
  if (tom) out.push(tom);
  return out;
}

// ── filings ────────────────────────────────────────────────────────────────

const RESULTS_SUBJECT = /board meeting|financial result/i;

/** The filings of one Intel chip that belong on the tape (rules in the header), newest first. */
export function filingItems(events: IntelEvent[], startMs: number, resultsToday: ReadonlySet<string>): TickerItem[] {
  return events.flatMap((e): TickerItem[] => {
    const cat = categoryKey(e.filing?.category);
    const t = FILING_TAGS.find((x) => x.category === cat);
    if (!t) return [];
    const at = e.publishedAt ?? e.at;
    const ms = timeOf(at);
    if (!(ms >= startMs)) return [];
    if (e.symbol && resultsToday.has(e.symbol) && RESULTS_SUBJECT.test(e.title)) return [];
    return [{
      key: `filing-${e.id}`, tag: t.tag, label: TAG_LABEL[t.tag], color: TAG_COLOR[t.tag], symbol: e.symbol,
      text: e.title, figures: [], when: at ? eventWhen(at).short : null, link: { kind: "intel", chip: t.chip, event: e.id }, group: null,
    }];
  });
}

/** Tag order on the tape for the filings. */
const FILING_ORDER: TickerTag[] = ["order", "mna", "buyback", "dividend", "capex", "fundraise", "rating"];

/** A filing kind whose read hit the feed's row limit before reaching the window's start: the tape covers it only from `since`. */
export interface KindReach { tag: TickerTag; label: string; limit: number; since: string }

/**
 * The ticker shares the Intel chips' reads (so a click always finds its event in the list), and those return the newest
 * LIMIT_GROUPED filings per category (LIMIT_SINGLE for Orders). On a heavy day a category's newest rows do not reach back to
 * the window's start (5 Nov 19:08 IST, real data: 61 M&A filings since 4 Nov 00:00, the read's 20 reached back to 4 Nov
 * 20:25). Said under the band instead of implying the tape is complete.
 */
export function kindReach(events: IntelEvent[], startMs: number, limit: number): KindReach[] {
  return FILING_TAGS.flatMap((t): KindReach[] => {
    const evs = events.filter((e) => categoryKey(e.filing?.category) === t.category);
    const records = evs.reduce((n, e) => n + Math.max(1, e.records.length), 0);
    if (records < limit) return [];
    let oldest: string | null = null;
    for (const e of evs) {
      const at = e.publishedAt ?? e.at;
      if (at && (oldest == null || timeOf(at) < timeOf(oldest))) oldest = at;
    }
    return oldest && timeOf(oldest) > startMs ? [{ tag: t.tag, label: TAG_LABEL[t.tag], limit, since: oldest }] : [];
  });
}

// ── deals, flows, SEBI, sectors ────────────────────────────────────────────

export function dealItems(events: IntelEvent[]): TickerItem[] {
  const dated = events.filter((e) => e.deal && e.at);
  const latest = dated.reduce<string | null>((m, e) => (!m || (e.at as string) > m ? (e.at as string) : m), null);
  if (!latest) return [];
  return dated
    .filter((e) => e.at === latest)
    .sort((a, b) => (b.deal?.valueCr ?? -Infinity) - (a.deal?.valueCr ?? -Infinity))
    .slice(0, DEALS_SHOWN)
    .map((e): TickerItem => {
      const d = e.deal!;
      const figures: TickerFigure[] = [];
      if (d.valueCr != null) figures.push({ key: "value", label: "Value", value: `₹${d.valueCr.toLocaleString("en-IN", { maximumFractionDigits: 2 })} cr`, change: null, note: null, kind: "plain" });
      if (d.pctOfShares != null) figures.push({ key: "pct", label: "Of shares", value: `${d.pctOfShares.toFixed(2)}%`, change: null, note: null, kind: "plain" });
      return {
        key: `deal-${e.id}`, tag: "deal", label: e.type, color: TAG_COLOR.deal, symbol: e.symbol,
        text: e.title, figures, when: eventWhen(e.at).short, link: { kind: "intel", chip: "deals", event: e.id }, group: null,
      };
    });
}

const crore = (n: number) => `${n < 0 ? "−" : "+"}₹${Math.abs(n).toLocaleString("en-IN", { maximumFractionDigits: 0 })} cr`;

export function flowItem(events: IntelEvent[]): TickerItem | null {
  const e = events.find((x) => x.flow && x.at);
  if (!e || !e.flow) return null;
  const figures: TickerFigure[] = [];
  if (e.flow.fii != null) figures.push({ key: "fii", label: "FII net", value: crore(e.flow.fii), change: e.flow.fii, note: null, kind: "sign" });
  if (e.flow.dii != null) figures.push({ key: "dii", label: "DII net", value: crore(e.flow.dii), change: e.flow.dii, note: null, kind: "sign" });
  if (!figures.length) return null;
  return {
    key: `flows-${e.id}`, tag: "flows", label: TAG_LABEL.flows, color: TAG_COLOR.flows, symbol: null,
    text: "Cash market, provisional", figures, when: eventWhen(e.at).short, link: { kind: "intel", chip: "flows", event: e.id }, group: null,
  };
}

export function sebiItems(events: IntelEvent[], from: string): TickerItem[] {
  return events
    .filter((e) => e.at && e.at.slice(0, 10) >= from)
    .sort((a, b) => (b.at ?? "").localeCompare(a.at ?? ""))
    .slice(0, SEBI_SHOWN)
    .map((e) => ({
      key: `sebi-${e.id}`, tag: "sebi" as const, label: TAG_LABEL.sebi, color: TAG_COLOR.sebi, symbol: null, text: e.title, figures: [],
      when: eventWhen(e.at).short, link: { kind: "intel" as const, chip: "regulatory" as const, event: e.id }, group: null,
    }));
}

export function sectorItems(events: IntelEvent[]): TickerItem[] {
  return events.filter((e) => e.group === "sector").slice(0, SECTOR_SHOWN).map((e) => ({
    key: `sector-${e.id}`, tag: "sector" as const, label: TAG_LABEL.sector, color: TAG_COLOR.sector, symbol: null, text: e.title, figures: [],
    when: eventWhen(e.at).short, link: { kind: "intel" as const, chip: "sector" as const, event: e.id }, group: null,
  }));
}

// ── what the tape shows ────────────────────────────────────────────────────

export type TickerFocus = "all" | "results" | "orders" | "mna" | "actions" | "market";

/** The "Show" switch: everything, or one kind of item. */
export const FOCUS: Array<{ key: TickerFocus; label: string; tags: TickerTag[] }> = [
  { key: "all", label: "Everything", tags: [] },
  { key: "results", label: "Results", tags: ["results", "filed", "due", "tomorrow"] },
  { key: "orders", label: "Orders", tags: ["order"] },
  { key: "mna", label: "M&A", tags: ["mna"] },
  { key: "actions", label: "Corporate actions", tags: ["buyback", "dividend", "capex", "fundraise", "rating"] },
  { key: "market", label: "Deals & flows", tags: ["deal", "flows", "sebi", "sector"] },
];

/**
 * On "Everything" each kind shows only its newest few, so one pass of the tape stays a few minutes long (5 Nov 19:08 IST,
 * real data: 149 items on the F&O tape, about 16 minutes at the tape's speed); choosing a kind shows all of it.
 */
export const EVERYTHING_CAP: Partial<Record<TickerTag, number>> = {
  results: 15, filed: 8, order: 8, mna: 8, buyback: 5, dividend: 5, capex: 5, fundraise: 5, rating: 5,
};

export function focusItems(items: TickerItem[], focus: TickerFocus): TickerItem[] {
  if (focus !== "all") {
    const tags = FOCUS.find((f) => f.key === focus)?.tags ?? [];
    return items.filter((i) => tags.includes(i.tag));
  }
  const seen: Partial<Record<TickerTag, number>> = {};
  return items.filter((i) => {
    const cap = EVERYTHING_CAP[i.tag];
    if (cap == null) return true;
    seen[i.tag] = (seen[i.tag] ?? 0) + 1;
    return (seen[i.tag] as number) <= cap;
  });
}

/** Items of one kind on the full tape (the count on its switch); grouped items count their companies. */
export function focusCount(items: TickerItem[], focus: TickerFocus): number {
  const tags = FOCUS.find((f) => f.key === focus)?.tags ?? [];
  return items.filter((i) => tags.includes(i.tag)).reduce((n, i) => n + (i.group ? i.group.symbols.length + i.group.more : 1), 0);
}

// ── the hook ───────────────────────────────────────────────────────────────

export type SourceName = "results" | "previous day's results" | "orders" | "M&A and corporate actions" | "announcements" | "deals" | "FII / DII" | "SEBI circulars" | "sector moves";

export interface TickerFeed {
  status: "loading" | "ready" | "error";
  items: TickerItem[];
  /** Sources that failed while others answered. */
  failed: SourceName[];
  /** Sources still loading (the tape shows what has arrived). */
  pending: SourceName[];
  /** The newest filing time on the tape (the band's "as of"). */
  latestAt: string | null;
  /** Filing kinds the tape covers only from a later time than the window's start (the read's row limit). */
  reach: KindReach[];
  window: { from: string; label: string };
  today: string;
  tomorrow: string;
  refetch: () => void;
}

export function useNewsTicker(universe: Universe, now: Date): TickerFeed {
  const today = istParts(now).iso;
  const tomorrow = addIstDays(today, 1);
  const win = filingsWindow(now);
  const board = useResultsBoard(today, tomorrow, "all", true);
  // the previous weekday's declared results (the route's window is at most 3 days, so it is a read of its own)
  const prevBoard = useResultsBoard(win.from, win.from, "all", true);
  const orders = useIntelEvents("orders", { refetchMs: FILINGS_REFETCH_MS });
  const mna = useIntelEvents("mna", { refetchMs: FILINGS_REFETCH_MS });
  const ann = useIntelEvents("announcements", { refetchMs: FILINGS_REFETCH_MS });
  const deals = useIntelEvents("deals");
  const flows = useIntelEvents("flows");
  const sectors = useIntelEvents("sector");
  const circulars = useCirculars(true);

  const parts: Array<{ name: SourceName; pending: boolean; failed: boolean; refetch: () => void }> = [
    { name: "results", pending: board.isPending, failed: board.isError, refetch: () => void board.refetch() },
    { name: "previous day's results", pending: prevBoard.isPending, failed: prevBoard.isError, refetch: () => void prevBoard.refetch() },
    { name: "orders", pending: orders.status === "loading", failed: orders.status === "error" || orders.failed.length > 0, refetch: orders.refetch },
    { name: "M&A and corporate actions", pending: mna.status === "loading", failed: mna.status === "error" || mna.failed.length > 0, refetch: mna.refetch },
    { name: "announcements", pending: ann.status === "loading", failed: ann.status === "error" || ann.failed.length > 0, refetch: ann.refetch },
    { name: "deals", pending: deals.status === "loading", failed: deals.status === "error", refetch: deals.refetch },
    { name: "FII / DII", pending: flows.status === "loading", failed: flows.status === "error", refetch: flows.refetch },
    { name: "SEBI circulars", pending: circulars.isPending, failed: circulars.isError, refetch: () => void circulars.refetch() },
    { name: "sector moves", pending: sectors.status === "loading", failed: sectors.status === "error", refetch: sectors.refetch },
  ];

  // companies with a results meeting in the filings window (today or the previous weekday), for the board-outcome rule
  const resultsDays = new Set([
    ...(board.data?.events ?? []).filter((e) => e.eventDate === today).map((e) => e.symbol),
    ...(prevBoard.data?.events ?? []).map((e) => e.symbol),
  ]);
  const items: TickerItem[] = [];
  if (board.data) items.push(...resultItems(board.data, prevBoard.data ?? null, today, tomorrow, universe));
  const filings = [orders, mna, ann].flatMap((f) => (f.status === "ready" ? filingItems(f.events, win.ms, resultsDays) : []));
  for (const tag of FILING_ORDER) items.push(...filings.filter((x) => x.tag === tag));
  if (deals.status === "ready") items.push(...dealItems(deals.events));
  if (flows.status === "ready") { const f = flowItem(flows.events); if (f) items.push(f); }
  if (circulars.data) items.push(...sebiItems(circulars.data.rows.map((c, i) => circularEvent(c, i)), win.from));
  if (sectors.status === "ready") items.push(...sectorItems(sectors.events));

  let latestAt: string | null = null;
  for (const f of [orders, mna, ann]) {
    for (const e of f.events) {
      const at = e.publishedAt ?? e.at;
      if (at && /T/.test(at) && (!latestAt || timeOf(at) > timeOf(latestAt))) latestAt = at;
    }
  }

  const reach = [
    ...(orders.status === "ready" ? kindReach(orders.events, win.ms, LIMIT_SINGLE) : []),
    ...(mna.status === "ready" ? kindReach(mna.events, win.ms, LIMIT_GROUPED) : []),
    ...(ann.status === "ready" ? kindReach(ann.events, win.ms, LIMIT_GROUPED) : []),
  ].sort((a, b) => FILING_ORDER.indexOf(a.tag) - FILING_ORDER.indexOf(b.tag));

  const failed = parts.filter((p) => p.failed).map((p) => p.name);
  const pending = parts.filter((p) => p.pending && !p.failed).map((p) => p.name);
  const status: TickerFeed["status"] = failed.length === parts.length ? "error" : items.length === 0 && pending.length > 0 ? "loading" : "ready";
  return {
    status, items, failed, pending, latestAt, reach, window: { from: win.from, label: win.label }, today, tomorrow,
    refetch: () => { for (const p of parts) if (p.failed) p.refetch(); },
  };
}
