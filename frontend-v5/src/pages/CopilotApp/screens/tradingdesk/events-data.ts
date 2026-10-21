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
