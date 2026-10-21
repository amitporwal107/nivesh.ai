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
 * Macro releases have no source ingested yet: the Macro switch says so and carries no figures.
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
