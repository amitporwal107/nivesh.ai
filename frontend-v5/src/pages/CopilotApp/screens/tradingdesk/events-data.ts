/**
 * Smart trading desk · Events calendar — the data.
 *
 *   GET /api/markets/events-calendar?month=YYYY-MM&universe=fno|n50|all
 *        { month, as_of, events[], holidays[], index_closes[], gaps[] }
 *        NSE board-meeting / corporate-action events (nidp.event_calendar, nidp.corporate_actions), NSE holidays
 *        (nidp.nse_holidays) and the Nifty 50's daily close % (nidp.index_eod). `gaps` is the route's own list of
 *        what it could not fill; it is shown as written.
 *   GET /api/markets/events-calendar/history?symbol=&type=
 *        { symbol, type, coverage_from, n, occurrences[], stats, basis }
 *        how the stock moved on past occurrences of the same event type: on the event day, the next day and a week
 *        later, from the warehouse's own price history (which starts at `coverage_from`).
 *
 *   GET /api/markets/macro-calendar?month=YYYY-MM&country=IN,US&impact=H,M,L
 *        { month, as_of, events[], holidays[], index_closes[], gaps[] }
 *        India and US macro releases: date, time (IST, may be null), impact, previous / estimate / actual and unit. The
 *        sources are free (FRED, RBI, MoSPI, BLS ...) and carry no consensus, so `estimate` is null and shown as "—".
 *   GET /api/markets/macro-calendar/history?code=&country=
 *        { code, country, source, coverage_from, coverage_to, n, occurrences[], stats, basis }
 *        how the Nifty 50 moved on past releases of the same indicator (release day, next day, a week later).
 *
 *   GET /api/markets/events-calendar/expectation?symbol=&date=YYYY-MM-DD
 *        { symbol, event_date, period_end, period_label, basis, status: upcoming|declared, metrics[], method, evidence[], gaps[] }
 *        A results event only. For an upcoming result: the range the company's own published quarters point to (a baseline
 *        from published data, not an analyst consensus), with the method's backtested track record. For a declared result:
 *        the filed figure beside that range. `evidence` is linked filings, `gaps` what could not be filled.
 *
 * Percent fields are percent points (1.2 = +1.2%). Nothing here is a forecast.
 */
import { useQuery } from "@tanstack/react-query";
import { z } from "zod";
import { http } from "@/services/api/http";
import { ApiError } from "@/services/api/errors";

export type EventType = "RESULTS" | "DIVIDEND" | "BOOK_CLOSURE" | "BONUS" | "SPLIT" | "BUYBACK" | "RIGHTS" | "OTHER";
export const EVENT_TYPES: readonly EventType[] = ["RESULTS", "DIVIDEND", "BOOK_CLOSURE", "BONUS", "SPLIT", "BUYBACK", "RIGHTS", "OTHER"];
export const TYPE_LABEL: Record<EventType, string> = {
  RESULTS: "RESULTS", DIVIDEND: "DIVIDEND", BOOK_CLOSURE: "BOOK CLOSURE", BONUS: "BONUS", SPLIT: "SPLIT", BUYBACK: "BUYBACK", RIGHTS: "RIGHTS", OTHER: "OTHER",
};
export const TYPE_SHORT: Record<EventType, string> = {
  RESULTS: "RES", DIVIDEND: "DIV", BOOK_CLOSURE: "BOOK", BONUS: "BONUS", SPLIT: "SPLIT", BUYBACK: "BUYBK", RIGHTS: "RIGHTS", OTHER: "OTHER",
};
export const TYPE_COLOR: Record<EventType, string> = {
  RESULTS: "var(--cp-indigo)", DIVIDEND: "var(--mint)", BOOK_CLOSURE: "var(--cp-ink-3)", BONUS: "var(--rose)", SPLIT: "var(--rose)", BUYBACK: "var(--rose)", RIGHTS: "var(--amber)", OTHER: "var(--cp-ink-4)",
};
/** Plural noun for "last N …" in the history basis line. */
export const TYPE_PLURAL: Record<EventType, string> = {
  RESULTS: "results", DIVIDEND: "dividends", BOOK_CLOSURE: "book closures", BONUS: "bonus issues", SPLIT: "splits", BUYBACK: "buybacks", RIGHTS: "rights issues", OTHER: "events",
};

export type Timing = "pre" | "mkt" | "post" | "ex" | "rec";
export const TIMING_LABEL: Record<Timing, string> = { pre: "Pre-market", mkt: "During market", post: "Post-market", ex: "Ex-date", rec: "Record date" };
export const TIMING_SHORT: Record<Timing, string> = { pre: "PRE", mkt: "MKT", post: "POST", ex: "EX-DATE", rec: "RECORD" };
export const TIMING_ORDER: Record<Timing, number> = { pre: 0, mkt: 1, post: 2, ex: 3, rec: 4 };

export type Universe = "fno" | "n50" | "all";

const Num = z.number().nullable().optional();
const Stat = z.object({ avg: Num, min: Num, max: Num }).partial();

const EventC = z.object({
  id: z.string(),
  date: z.string().regex(/^\d{4}-\d{2}-\d{2}/),
  symbol: z.string(),
  name: z.string().nullable().optional(),
  sector: z.string().nullable().optional(),
  type: z.string(),
  timing: z.string().nullable().optional(),
  detail: z.string().nullable().optional(),
  universe: z.object({ n50: z.boolean().nullable().optional(), fno: z.boolean().nullable().optional() }).partial().nullable().optional(),
  source: z.string().nullable().optional(),
  announced_at: z.string().nullable().optional(),
});
const CalendarC = z.object({
  month: z.string(),
  as_of: z.string().nullable().optional(),
  events: z.array(EventC),
  holidays: z.array(z.object({ date: z.string(), description: z.string().nullable().optional() })).default([]),
  index_closes: z.array(z.object({ date: z.string(), pct: z.number().nullable() })).default([]),
  gaps: z.array(z.string()).default([]),
});
const HistoryC = z.object({
  symbol: z.string(),
  type: z.string(),
  coverage_from: z.string().nullable().optional(),
  n: z.number(),
  occurrences: z.array(z.object({ date: z.string(), event_day_pct: Num, d1_pct: Num, w1_pct: Num })).default([]),
  stats: z.object({ event_day: Stat, d1: Stat, w1: Stat }).partial().nullable().optional(),
  basis: z.string().nullable().optional(),
});

export interface CalEvent {
  id: string;
  /** YYYY-MM-DD */
  date: string;
  symbol: string;
  name: string;
  sector: string | null;
  type: EventType;
  timing: Timing | null;
  detail: string;
  n50: boolean | null;
  fno: boolean | null;
  source: string | null;
  announcedAt: string | null;
}
export interface Calendar {
  month: string;
  asOf: string | null;
  events: CalEvent[];
  holidays: Map<string, string>;
  /** Nifty 50 close % by YYYY-MM-DD (days with a close only). */
  closes: Map<string, number>;
  gaps: string[];
}
export interface StatTriple { avg: number | null; min: number | null; max: number | null }
export interface History {
  symbol: string;
  type: EventType;
  coverageFrom: string | null;
  n: number;
  occurrences: Array<{ date: string; eventDay: number | null; d1: number | null; w1: number | null }>;
  stats: { eventDay: StatTriple; d1: StatTriple; w1: StatTriple };
  basis: string | null;
}

const asType = (v: string): EventType => ((EVENT_TYPES as readonly string[]).includes(v.toUpperCase()) ? (v.toUpperCase() as EventType) : "OTHER");
const asTiming = (v: string | null | undefined): Timing | null => (v === "pre" || v === "mkt" || v === "post" || v === "ex" || v === "rec" ? v : null);
const triple = (s: z.infer<typeof Stat> | undefined): StatTriple => ({ avg: s?.avg ?? null, min: s?.min ?? null, max: s?.max ?? null });
const noRetry4xx = (count: number, e: unknown) =>
  !(e instanceof ApiError && (e.kind === "contract_drift" || (e.status != null && e.status >= 400 && e.status < 500))) && count < 1;

export async function fetchCalendar(month: string, universe: Universe, signal?: AbortSignal): Promise<Calendar> {
  const res = await http({ path: "/api/markets/events-calendar", query: { month, universe }, signal });
  const parsed = CalendarC.safeParse(res.data);
  if (!parsed.success) throw ApiError.contractDrift(`events-calendar: ${parsed.error.issues[0]?.message ?? "unexpected shape"}`, parsed.error);
  const d = parsed.data;
  return {
    month: d.month,
    asOf: d.as_of ?? null,
    events: d.events.map((e) => ({
      id: e.id, date: e.date.slice(0, 10), symbol: e.symbol, name: e.name || e.symbol, sector: e.sector || null, type: asType(e.type), timing: asTiming(e.timing),
      detail: e.detail || "", n50: e.universe?.n50 ?? null, fno: e.universe?.fno ?? null, source: e.source ?? null, announcedAt: e.announced_at ?? null,
    })),
    holidays: new Map(d.holidays.map((h) => [h.date.slice(0, 10), h.description || "NSE holiday"])),
    closes: new Map(d.index_closes.filter((c): c is { date: string; pct: number } => c.pct != null).map((c) => [c.date.slice(0, 10), c.pct])),
    gaps: d.gaps,
  };
}

export function useEventsCalendar(month: string, universe: Universe) {
  return useQuery<Calendar>({
    queryKey: ["copilot", "desk", "events-calendar", month, universe],
    staleTime: 5 * 60_000,
    retry: noRetry4xx,
    queryFn: ({ signal }) => fetchCalendar(month, universe, signal),
  });
}

export async function fetchHistory(symbol: string, type: EventType, signal?: AbortSignal): Promise<History> {
  const res = await http({ path: "/api/markets/events-calendar/history", query: { symbol, type }, signal });
  const parsed = HistoryC.safeParse(res.data);
  if (!parsed.success) throw ApiError.contractDrift(`events-calendar.history: ${parsed.error.issues[0]?.message ?? "unexpected shape"}`, parsed.error);
  const d = parsed.data;
  return {
    symbol: d.symbol, type: asType(d.type), coverageFrom: d.coverage_from ?? null, n: d.n, basis: d.basis ?? null,
    occurrences: d.occurrences.map((o) => ({ date: o.date.slice(0, 10), eventDay: o.event_day_pct ?? null, d1: o.d1_pct ?? null, w1: o.w1_pct ?? null })),
    stats: { eventDay: triple(d.stats?.event_day), d1: triple(d.stats?.d1), w1: triple(d.stats?.w1) },
  };
}

export function useEventHistory(symbol: string | null, type: EventType | null) {
  return useQuery<History>({
    queryKey: ["copilot", "desk", "events-history", symbol, type],
    enabled: !!symbol && !!type,
    staleTime: 30 * 60_000,
    retry: noRetry4xx,
    queryFn: ({ signal }) => fetchHistory(symbol as string, type as EventType, signal),
  });
}

// ── results expectation (a results event only) ───────────────────────────

const Rng = z.object({ low: Num, mid: Num, high: Num }).partial();
const MetricC = z.object({
  key: z.string(),
  unit: z.string().nullable().optional(),
  expected: Rng.nullable().optional(),
  same_quarter_last_year: Num,
  previous_quarter: Num,
  trend_yoy_pct: Num,
  filed: z.object({ value: Num, broadcast_at: z.string().nullable().optional(), audit_status: z.string().nullable().optional() }).partial().nullable().optional(),
  vs_mid_pct: Num,
  /** true / false once a figure is filed against a range; null when there is nothing to compare. */
  within_band: z.boolean().nullable().optional(),
  reliable: z.boolean().nullable().optional(),
  note: z.string().nullable().optional(),
  last_year_note: z.string().nullable().optional(),
});
/** One stock's own testable quarters (profit only: the backend's stock backtest runs on profit). */
const BacktestC = z.object({ n_quarters: Num, median_abs_err_pct: Num, within_band_pct: Num, note: z.string().nullable().optional() }).partial();
/** All stocks, one metric: accuracy against the "last year's quarter unchanged" benchmark, and the held-out band check. */
const ByMetricC = z.object({
  n: Num,
  median_abs_err_pct: Num,
  naive_flat_median_abs_err_pct: Num,
  within_band_pct: Num,
  within_band_n: Num,
  latest_quarter: z.object({ tested_on: z.string().nullable().optional(), tested_n: Num, within_band_pct: Num }).partial().nullable().optional(),
}).partial();
const ExpectationC = z.object({
  symbol: z.string(),
  event_date: z.string().nullable().optional(),
  period_end: z.string().nullable().optional(),
  period_label: z.string().nullable().optional(),
  basis: z.string().nullable().optional(),
  status: z.string(),
  filed_state: z.string().nullable().optional(),
  filing: z.object({ filed_at: z.string().nullable().optional(), subject: z.string().nullable().optional(), url: z.string().nullable().optional() }).partial().nullable().optional(),
  label: z.string().nullable().optional(),
  compared_with: z.string().nullable().optional(),
  audit_status: z.string().nullable().optional(),
  audit_basis: z.string().nullable().optional(),
  expected_as_of: z.string().nullable().optional(),
  sources: z.record(z.string(), z.string().nullable()).nullable().optional(),
  metrics: z.array(MetricC).default([]),
  method: z.object({
    name: z.string().nullable().optional(),
    formula: z.string().nullable().optional(),
    n_quarters: Num,
    backtest: BacktestC.nullable().optional(),
    universe_backtest: ByMetricC.nullable().optional(),
    by_metric: z.record(z.string(), ByMetricC).nullable().optional(),
  }).partial().nullable().optional(),
  evidence: z.array(z.object({
    date: z.string().nullable().optional(), title: z.string().nullable().optional(), category: z.string().nullable().optional(),
    source: z.string().nullable().optional(), url: z.string().nullable().optional(),
  })).default([]),
  gaps: z.array(z.string()).default([]),
});

export interface ExpMetric {
  key: string;
  unit: string | null;
  expected: { low: number; mid: number | null; high: number } | null;
  lastYearQuarter: number | null;
  previousQuarter: number | null;
  trendYoy: number | null;
  filed: { value: number | null; broadcastAt: string | null; auditStatus: string | null } | null;
  vsMid: number | null;
  /** The backend's own inside / outside answer for a filed figure; null when nothing was compared. */
  withinBand: boolean | null;
  reliable: boolean;
  note: string | null;
  lastYearNote: string | null;
}
/** One stock's testable quarters. */
export interface StockTrack { nQuarters: number | null; medianAbsErr: number | null; withinBand: number | null; note: string | null }
/** All stocks, one metric. `withinBandN` is the held-out sample the within-band share was measured on. */
export interface UniTrack {
  n: number | null; medianAbsErr: number | null; naiveMedianAbsErr: number | null; withinBand: number | null; withinBandN: number | null;
  latest: { testedOn: string | null; testedN: number | null; withinBand: number | null } | null;
}
export interface Expectation {
  symbol: string;
  eventDate: string | null;
  periodEnd: string | null;
  periodLabel: string | null;
  basis: string | null;
  status: "upcoming" | "declared";
  /** Today's meetings: "figures" (filed and loaded), "pending" (filed, our results feed has not loaded it yet) or null. */
  filedState: "figures" | "pending" | null;
  /** The board-meeting outcome filing, when one exists. */
  filing: { filedAt: string | null; subject: string | null; url: string | null } | null;
  /** The backend's own one-line statement of what this is. */
  label: string | null;
  /** What a filed figure is compared with ("vs Nivesh baseline, not vs consensus"); null when nothing is filed. */
  comparedWith: string | null;
  auditStatus: string | null;
  /** Where the audit status was read from. */
  auditBasis: string | null;
  /** The cut-off: only quarters published before this were used. */
  expectedAsOf: string | null;
  sources: Array<[string, string]>;
  metrics: ExpMetric[];
  method: { name: string | null; formula: string | null; nQuarters: number | null; stock: StockTrack | null; byMetric: Record<string, UniTrack>; universe: UniTrack | null };
  evidence: Array<{ date: string | null; title: string; category: string | null; source: string | null; url: string | null }>;
  gaps: string[];
}

const uniTrack = (b: z.infer<typeof ByMetricC> | null | undefined): UniTrack | null =>
  b && (b.n ?? 0) > 0
    ? {
        n: b.n ?? null, medianAbsErr: b.median_abs_err_pct ?? null, naiveMedianAbsErr: b.naive_flat_median_abs_err_pct ?? null,
        withinBand: b.within_band_pct ?? null, withinBandN: b.within_band_n ?? null,
        latest: b.latest_quarter ? { testedOn: b.latest_quarter.tested_on ?? null, testedN: b.latest_quarter.tested_n ?? null, withinBand: b.latest_quarter.within_band_pct ?? null } : null,
      }
    : null;

type MetricIn = z.infer<typeof MetricC>;
const mapMetric = (m: MetricIn): ExpMetric => ({
  key: m.key, unit: m.unit ?? null,
  expected: m.expected && m.expected.low != null && m.expected.high != null ? { low: m.expected.low, mid: m.expected.mid ?? null, high: m.expected.high } : null,
  lastYearQuarter: m.same_quarter_last_year ?? null, previousQuarter: m.previous_quarter ?? null, trendYoy: m.trend_yoy_pct ?? null,
  filed: m.filed ? { value: m.filed.value ?? null, broadcastAt: m.filed.broadcast_at ?? null, auditStatus: m.filed.audit_status ?? null } : null,
  vsMid: m.vs_mid_pct ?? null, withinBand: m.within_band ?? null, reliable: m.reliable !== false, note: m.note ?? null, lastYearNote: m.last_year_note ?? null,
});
const mapFiling = (f: z.infer<typeof ExpectationC>["filing"]): Expectation["filing"] =>
  f ? { filedAt: f.filed_at ?? null, subject: f.subject ?? null, url: f.url ?? null } : null;
const asFiledState = (v: string | null | undefined): Expectation["filedState"] => (v === "figures" || v === "pending" ? v : null);

export async function fetchExpectation(symbol: string, date: string, signal?: AbortSignal): Promise<Expectation> {
  const res = await http({ path: "/api/markets/events-calendar/expectation", query: { symbol, date }, signal });
  const parsed = ExpectationC.safeParse(res.data);
  if (!parsed.success) throw ApiError.contractDrift(`events-calendar.expectation: ${parsed.error.issues[0]?.message ?? "unexpected shape"}`, parsed.error);
  const d = parsed.data;
  const byMetric: Record<string, UniTrack> = {};
  for (const [k, v] of Object.entries(d.method?.by_metric ?? {})) { const t = uniTrack(v); if (t) byMetric[k] = t; }
  const bt = d.method?.backtest;
  return {
    symbol: d.symbol, eventDate: d.event_date ?? null, periodEnd: d.period_end ?? null, periodLabel: d.period_label ?? null, basis: d.basis ?? null,
    status: d.status === "declared" ? "declared" : "upcoming", filedState: asFiledState(d.filed_state), filing: mapFiling(d.filing),
    label: d.label ?? null, comparedWith: d.compared_with ?? null, auditStatus: d.audit_status ?? null, auditBasis: d.audit_basis ?? null, expectedAsOf: d.expected_as_of ?? null,
    sources: Object.entries(d.sources ?? {}).filter((e): e is [string, string] => !!e[1]),
    metrics: d.metrics.map(mapMetric),
    method: {
      name: d.method?.name ?? null, formula: d.method?.formula ?? null, nQuarters: d.method?.n_quarters ?? null,
      stock: bt ? { nQuarters: bt.n_quarters ?? null, medianAbsErr: bt.median_abs_err_pct ?? null, withinBand: bt.within_band_pct ?? null, note: bt.note ?? null } : null,
      byMetric, universe: uniTrack(d.method?.universe_backtest),
    },
    evidence: d.evidence.map((e) => ({ date: e.date ? e.date.slice(0, 10) : null, title: e.title || "Filing", category: e.category ?? null, source: e.source ?? null, url: e.url ?? null })),
    gaps: d.gaps,
  };
}

export function useResultsExpectation(symbol: string | null, date: string | null, enabled: boolean) {
  return useQuery<Expectation>({
    queryKey: ["copilot", "desk", "events-expectation", symbol, date],
    enabled: enabled && !!symbol && !!date,
    staleTime: 30 * 60_000,
    retry: noRetry4xx,
    queryFn: ({ signal }) => fetchExpectation(symbol as string, date as string, signal),
  });
}

// ── results today & tomorrow (one request for every meeting in a two-day window) ──

const BoardEventC = z.object({
  id: z.string(),
  symbol: z.string(),
  name: z.string().nullable().optional(),
  sector: z.string().nullable().optional(),
  event_date: z.string(),
  status: z.string(),
  filed_state: z.string().nullable().optional(),
  filing: ExpectationC.shape.filing,
  period_label: z.string().nullable().optional(),
  audit_status: z.string().nullable().optional(),
  compared_with: z.string().nullable().optional(),
  metrics: z.array(MetricC).default([]),
  gaps: z.array(z.string()).default([]),
});
const BoardC = z.object({
  from: z.string(),
  to: z.string(),
  as_of: z.string().nullable().optional(),
  count: Num,
  counts: z.object({ declared_figures: Num, declared_pending: Num, upcoming: Num }).partial().nullable().optional(),
  label: z.string().nullable().optional(),
  events: z.array(BoardEventC).default([]),
  method: z.object({ by_metric: z.record(z.string(), ByMetricC).nullable().optional() }).partial().nullable().optional(),
  gaps: z.array(z.string()).default([]),
});

export interface BoardEvent {
  id: string; symbol: string; name: string; sector: string | null; eventDate: string;
  status: "upcoming" | "declared"; filedState: "figures" | "pending" | null; filing: Expectation["filing"];
  periodLabel: string | null; auditStatus: string | null; comparedWith: string | null; metrics: ExpMetric[]; gaps: string[];
}
export interface Board {
  from: string; to: string; label: string | null; events: BoardEvent[];
  counts: { figures: number; pending: number; upcoming: number };
  byMetric: Record<string, UniTrack>; gaps: string[];
}

export async function fetchBoard(from: string, to: string, universe: Universe, signal?: AbortSignal): Promise<Board> {
  const res = await http({ path: "/api/markets/events-calendar/expectations", query: { from, to, universe }, signal });
  const parsed = BoardC.safeParse(res.data);
  if (!parsed.success) throw ApiError.contractDrift(`events-calendar.expectations: ${parsed.error.issues[0]?.message ?? "unexpected shape"}`, parsed.error);
  const d = parsed.data;
  const byMetric: Record<string, UniTrack> = {};
  for (const [k, v] of Object.entries(d.method?.by_metric ?? {})) { const t = uniTrack(v); if (t) byMetric[k] = t; }
  return {
    from: d.from, to: d.to, label: d.label ?? null,
    events: d.events.map((e) => ({
      id: e.id, symbol: e.symbol, name: e.name || e.symbol, sector: e.sector ?? null, eventDate: e.event_date,
      status: e.status === "declared" ? "declared" : "upcoming", filedState: asFiledState(e.filed_state), filing: mapFiling(e.filing),
      periodLabel: e.period_label ?? null, auditStatus: e.audit_status ?? null, comparedWith: e.compared_with ?? null,
      metrics: e.metrics.map(mapMetric), gaps: e.gaps,
    })),
    counts: { figures: d.counts?.declared_figures ?? 0, pending: d.counts?.declared_pending ?? 0, upcoming: d.counts?.upcoming ?? 0 },
    byMetric, gaps: d.gaps,
  };
}

export function useResultsBoard(from: string, to: string, universe: Universe, enabled: boolean) {
  return useQuery<Board>({
    queryKey: ["copilot", "desk", "events-board", from, to, universe],
    enabled,
    staleTime: 5 * 60_000,
    refetchInterval: 10 * 60_000,
    retry: noRetry4xx,
    queryFn: ({ signal }) => fetchBoard(from, to, universe, signal),
  });
}

/** A figure in the unit the API names: crore of rupees, rupees per share, or a plain number with its unit. */
export function fmtExpVal(v: number | null | undefined, unit: string | null): string {
  if (v == null || !Number.isFinite(v)) return "—";
  const u = (unit ?? "").toLowerCase().replace(/[\s_₹]/g, "");
  const neg = v < 0 ? "−" : "";
  const a = Math.abs(v);
  if (u.includes("cr")) return `${neg}₹${a.toLocaleString("en-IN", { maximumFractionDigits: a >= 100 ? 0 : 1 })} cr`;
  if (u === "" || u === "inr" || u === "rs" || u === "rupees" || u.endsWith("share")) return `${neg}₹${a.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
  if (u === "%" || u === "pct") return `${neg}${a.toFixed(1)}%`;
  return `${neg}${a.toLocaleString("en-IN", { maximumFractionDigits: 2 })} ${unit}`;
}

// ── macro releases ────────────────────────────────────────────────────────

export type Impact = "H" | "M" | "L";
export const IMPACTS: readonly Impact[] = ["H", "M", "L"];
export const IMPACT_LABEL: Record<Impact, string> = { H: "HIGH", M: "MEDIUM", L: "LOW" };
export const IMPACT_COLOR: Record<Impact, string> = { H: "var(--cp-indigo)", M: "var(--amber)", L: "var(--cp-ink-4)" };
export type Country = "IN" | "US";
export const COUNTRIES: readonly Country[] = ["IN", "US"];
export const COUNTRY_NAME: Record<Country, string> = { IN: "India", US: "United States" };
export const COUNTRY_CHIP: Record<Country, string> = { IN: "INDIA", US: "UNITED STATES" };

/** A release figure: the API may send a number or a string; null / "" is "not available". */
const Val = z.union([z.number(), z.string()]).nullable().optional();
const MacroEventC = z.object({
  id: z.string(),
  date: z.string().regex(/^\d{4}-\d{2}-\d{2}/),
  /** The release's IST date: late-evening releases can land a day after the agency's own date. */
  date_ist: z.string().nullable().optional(),
  time: z.string().nullable().optional(),
  /** "usual time" when the time is the agency's usual time of day, not read from a calendar. */
  time_basis: z.string().nullable().optional(),
  country: z.string(),
  impact: z.string().nullable().optional(),
  name: z.string(),
  short: z.string().nullable().optional(),
  code: z.string().nullable().optional(),
  period: z.string().nullable().optional(),
  previous: Val,
  estimate: Val,
  actual: Val,
  unit: z.string().nullable().optional(),
  source: z.string().nullable().optional(),
  source_url: z.string().nullable().optional(),
});
const MacroCalendarC = z.object({
  month: z.string(),
  as_of: z.string().nullable().optional(),
  events: z.array(MacroEventC),
  holidays: z.array(z.object({ date: z.string(), description: z.string().nullable().optional() })).default([]),
  index_closes: z.array(z.object({ date: z.string(), pct: z.number().nullable() })).default([]),
  gaps: z.array(z.string()).default([]),
});
const MacroHistoryC = z.object({
  code: z.string(),
  country: z.string(),
  source: z.string().nullable().optional(),
  coverage_from: z.string().nullable().optional(),
  coverage_to: z.string().nullable().optional(),
  n: z.number(),
  occurrences: z.array(z.object({ date: z.string(), period: z.string().nullable().optional(), previous: Val, actual: Val, event_day_pct: Num, d1_pct: Num, w1_pct: Num })).default([]),
  stats: z.object({ event_day: Stat, d1: Stat, w1: Stat }).partial().nullable().optional(),
  basis: z.string().nullable().optional(),
});

export interface MacroEvent {
  id: string;
  /** YYYY-MM-DD, the IST date when the API sends one. */
  date: string;
  /** "HH:MM" IST, null when the source gives only a date. */
  time: string | null;
  /** Says what the time is, e.g. "usual time"; null when there is no time. */
  timeBasis: string | null;
  country: Country;
  impact: Impact;
  name: string;
  short: string;
  /** What the history endpoint is keyed on: the API's `code`, else its short name. */
  code: string;
  period: string;
  previous: string | null;
  estimate: string | null;
  actual: string | null;
  unit: string;
  source: string | null;
  sourceUrl: string | null;
}
export interface MacroCalendar {
  month: string;
  asOf: string | null;
  events: MacroEvent[];
  holidays: Map<string, string>;
  closes: Map<string, number>;
  gaps: string[];
}
export interface MacroHistory {
  code: string;
  country: Country;
  source: string | null;
  coverageFrom: string | null;
  coverageTo: string | null;
  n: number;
  occurrences: Array<{ date: string; period: string | null; previous: string | null; actual: string | null; eventDay: number | null; d1: number | null; w1: number | null }>;
  stats: { eventDay: StatTriple; d1: StatTriple; w1: StatTriple };
  basis: string | null;
}

const asImpact = (v: string | null | undefined): Impact => (v === "H" || v === "M" || v === "L" ? v : v && /^high/i.test(v) ? "H" : v && /^med/i.test(v) ? "M" : "L");
const asCountry = (v: string): Country => (v.toUpperCase() === "US" || v.toUpperCase() === "USA" ? "US" : "IN");
const valStr = (v: string | number | null | undefined): string | null => (v == null || (typeof v === "string" && v.trim() === "") ? null : String(v).trim());

/** "3.1" + "%" -> "3.1%"; "64" + "K" -> "64K"; "-26.5" + "$B" -> "−$26.5B"; no unit -> the figure as sent. */
export function fmtMacroVal(v: string | null | undefined, unit: string): string {
  if (v == null) return "—";
  const neg = v.startsWith("-");
  const a = neg ? v.slice(1) : v;
  const body = unit === "$B" ? `$${a}B` : unit === "%" ? `${a}%` : unit === "K" ? `${a}K` : unit ? `${a} ${unit}` : a;
  return `${neg ? MINUS_SIGN : ""}${body}`;
}
const MINUS_SIGN = "−";

export async function fetchMacroCalendar(month: string, signal?: AbortSignal): Promise<MacroCalendar> {
  const res = await http({ path: "/api/markets/macro-calendar", query: { month, country: "IN,US", impact: "H,M,L" }, signal });
  const parsed = MacroCalendarC.safeParse(res.data);
  if (!parsed.success) throw ApiError.contractDrift(`macro-calendar: ${parsed.error.issues[0]?.message ?? "unexpected shape"}`, parsed.error);
  const d = parsed.data;
  return {
    month: d.month,
    asOf: d.as_of ?? null,
    events: d.events.map((e) => ({
      id: e.id, date: (e.date_ist || e.date).slice(0, 10), time: e.time && /^\d{1,2}:\d{2}/.test(e.time) ? e.time.slice(0, 5) : null, timeBasis: e.time_basis ?? null, country: asCountry(e.country), impact: asImpact(e.impact),
      name: e.name, short: (e.short || e.name).trim(), code: (e.code || e.short || e.name).trim(), period: e.period ?? "",
      previous: valStr(e.previous), estimate: valStr(e.estimate), actual: valStr(e.actual), unit: e.unit ?? "", source: e.source ?? null, sourceUrl: e.source_url ?? null,
    })),
    holidays: new Map(d.holidays.map((h) => [h.date.slice(0, 10), h.description || "NSE holiday"])),
    closes: new Map(d.index_closes.filter((c): c is { date: string; pct: number } => c.pct != null).map((c) => [c.date.slice(0, 10), c.pct])),
    gaps: d.gaps,
  };
}

export function useMacroCalendar(month: string) {
  return useQuery<MacroCalendar>({
    queryKey: ["copilot", "desk", "macro-calendar", month],
    staleTime: 5 * 60_000,
    retry: noRetry4xx,
    queryFn: ({ signal }) => fetchMacroCalendar(month, signal),
  });
}

export async function fetchMacroHistory(code: string, country: Country, signal?: AbortSignal): Promise<MacroHistory> {
  const res = await http({ path: "/api/markets/macro-calendar/history", query: { code, country }, signal });
  const parsed = MacroHistoryC.safeParse(res.data);
  if (!parsed.success) throw ApiError.contractDrift(`macro-calendar.history: ${parsed.error.issues[0]?.message ?? "unexpected shape"}`, parsed.error);
  const d = parsed.data;
  return {
    code: d.code, country: asCountry(d.country), source: d.source ?? null, coverageFrom: d.coverage_from ?? null, coverageTo: d.coverage_to ?? null, n: d.n, basis: d.basis ?? null,
    occurrences: d.occurrences.map((o) => ({ date: o.date.slice(0, 10), period: o.period ?? null, previous: valStr(o.previous), actual: valStr(o.actual), eventDay: o.event_day_pct ?? null, d1: o.d1_pct ?? null, w1: o.w1_pct ?? null })),
    stats: { eventDay: triple(d.stats?.event_day), d1: triple(d.stats?.d1), w1: triple(d.stats?.w1) },
  };
}

export function useMacroHistory(code: string | null, country: Country | null) {
  return useQuery<MacroHistory>({
    queryKey: ["copilot", "desk", "macro-history", code, country],
    enabled: !!code && !!country,
    staleTime: 30 * 60_000,
    retry: noRetry4xx,
    queryFn: ({ signal }) => fetchMacroHistory(code as string, country as Country, signal),
  });
}
