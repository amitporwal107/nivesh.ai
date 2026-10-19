/**
 * Data access for the market / research screens. Reads only — nothing here
 * changes data.
 *
 * 1. Named hooks over the app's existing market hooks (@/hooks/use-markets), so
 *    a screen never names a provider or an endpoint. They share the original
 *    app's query keys, so both apps show the same numbers from one cache; when a
 *    feed moves to another provider, only this file changes.
 * 2. Query hooks for endpoints that had no react-query hook yet. Each wraps an
 *    existing adapter (filings, markets) or reads an existing backend route
 *    with `http`.
 * 3. The joins between the user's directly held stocks and the market
 *    calendars (results, corporate actions).
 */
import { useCallback, useMemo } from "react";
import { useQueries, useQuery, useQueryClient } from "@tanstack/react-query";
import { z } from "zod";
import { marketsService } from "@/services";
import { http } from "@/services/api/http";
import { ApiError } from "@/services/api/errors";
import { filingsService, type FeedParams } from "@/services/adapters/filings.adapter";
import type {
  ArticlesQuery, CapSegment, CorpActionsQuery, EarningsCompaniesQuery, EarningsQuery,
} from "@/services/adapters/markets.adapter";
import type { CorpAction, EarningsCompany } from "@/services/contracts/markets.contract";
import {
  useArticles, useBriefHistory, useCorporateActions, useDailyBrief, useEarnings, useEarningsCompanies,
  useInstitutionalPositioning, useMarketsExplore, useMarketsFiiDii, useMarketsHome, useMarketsMovers,
  useSectorAnalyses, useSectorAnalysis,
} from "@/hooks/use-markets";
import { useHoldingsEnriched } from "@/hooks/use-portfolio";
import { useThematicQueries } from "@/hooks/useThematicQueries";
import { isoDay } from "./format";

// ── market and sector data ───────────────────────────────────────────────

/** GET /api/markets/home — indices, breadth, sectors, movers, flows, global quotes, headlines. */
export function useMarketOverview() {
  return useMarketsHome();
}

/** GET /api/markets/movers?cap= — gainers and losers for one market-cap segment. */
export function useMarketMovers(cap: CapSegment) {
  return useMarketsMovers(cap);
}

/** GET /api/markets/explore — near 52-week high / low and most-active lists. Fetched when first opened. */
export function useMarketLists(enabled: boolean) {
  return useMarketsExplore(enabled);
}

/** GET /api/markets/sectors — one card per sector profile. */
export function useSectorList() {
  return useSectorAnalyses();
}

/** GET /api/markets/sectors/{slug} — one sector's figures, largest companies and commentary. */
export function useSectorDetail(slug: string) {
  return useSectorAnalysis(slug);
}

/** GET /api/markets/fii-dii — daily and monthly FII / DII cash flows. */
export function useInstitutionalFlows(days = 90) {
  return useMarketsFiiDii(days);
}

/** GET /api/markets/institutional-positioning — FII / DII holdings by sector. */
export function useSectorPositioning() {
  return useInstitutionalPositioning();
}

/** GET /api/markets/earnings — declared results by sector for an index and quarter. */
export function useEarningsSeason(params: EarningsQuery) {
  return useEarnings(params);
}

/** GET /api/markets/earnings/companies — the companies behind one sector row. */
export function useEarningsSectorCompanies(params: EarningsCompaniesQuery, enabled: boolean) {
  return useEarningsCompanies(params, enabled);
}

// ── corporate events and news ────────────────────────────────────────────

/** GET /api/markets/corporate-actions — the corporate-action calendar. */
export function useActionCalendar(params: CorpActionsQuery) {
  return useCorporateActions(params);
}

/** GET /api/markets/articles — classified exchange announcements. */
export function useAnnouncements(params: ArticlesQuery) {
  return useArticles(params);
}

/** GET /api/markets/daily-brief — the stored brief for today or a past day. */
export function useMarketBrief(date?: string) {
  return useDailyBrief(date);
}

/** GET /api/markets/daily-brief/history — the days a brief exists for. */
export function useMarketBriefDays(limit = 30) {
  return useBriefHistory(limit);
}

/** GET /api/filings/{id}/insights — the generated read of one filing; null when none exists yet. */
export function useFilingInsight(id: string, enabled: boolean) {
  return useQuery({
    queryKey: ["filings", "insight", id],
    queryFn: () => filingsService.getInsight(id),
    enabled: enabled && !!id,
    staleTime: 5 * 60_000,
  });
}

// ── filings ──────────────────────────────────────────────────────────────

/** GET /api/filings/signals — the top material filings (today, or the latest). */
export function useFilingSignals(todayOnly: boolean) {
  return useQuery({
    queryKey: ["filings", "signals", todayOnly],
    queryFn: () => filingsService.getSignals(1, todayOnly),
    staleTime: 60_000,
  });
}

/** GET /api/filings/feed — classified filings with facet counts and a total. */
export function useFilingsFeed(params: FeedParams, enabled = true) {
  return useQuery({
    queryKey: ["filings", "feed", params],
    queryFn: () => filingsService.getFeed(params),
    enabled,
    staleTime: 60_000,
    placeholderData: (prev) => prev,
  });
}

/** GET /api/filings/alerts — the signed-in user's filing-alert preferences. */
export function useFilingAlerts() {
  return useQuery({
    queryKey: ["filings", "alerts"],
    queryFn: () => filingsService.getAlerts(),
    staleTime: 60_000,
  });
}

export interface HeldKeys {
  names: Set<string>;
  symbols: Set<string>;
}

/** Same normalisation the backend applies to holding names (routes/filings.py). */
function normName(x: string | null | undefined): string {
  return (x ?? "")
    .toLowerCase()
    .replace(/\b(limited|ltd|corporation|corp|company|co|pvt|private)\b/g, "")
    .replace(/[^a-z0-9]/g, "");
}

/** True when a company (by NSE symbol or name) is in the user's holdings. */
export function isHeld(held: HeldKeys | undefined, symbol?: string | null, name?: string | null): boolean {
  if (!held) return false;
  if (symbol && held.symbols.has(symbol.toUpperCase())) return true;
  const n = normName(name);
  return !!n && held.names.has(n);
}

/**
 * GET /api/filings/portfolio-held — match keys for the "You hold" badge. The
 * adapter answers with empty sets when there are no holdings or the call fails,
 * so a missing badge never blocks a table.
 */
export function useHeldKeys() {
  return useQuery({
    queryKey: ["filings", "portfolio-held"],
    queryFn: async (): Promise<HeldKeys> => {
      const h = await filingsService.getPortfolioHeld();
      return { names: new Set(h.names), symbols: new Set(h.symbols.map((s) => s.toUpperCase())) };
    },
    staleTime: 5 * 60_000,
  });
}

// ── thematic research questions (history + favourites) ───────────────────

const ThematicPrefsC = z.object({
  history: z.array(z.string()).default([]),
  favorites: z.array(z.string()).default([]),
});
export type ThematicPrefs = z.infer<typeof ThematicPrefsC>;

const THEMATIC_KEY = ["thematic", "prefs"] as const;
/** Same cap the backend and useThematicQueries apply to history. */
const HISTORY_CAP = 40;

/** GET /api/thematic/prefs — the user's research-question history and favourites. */
export function useThematicPrefs() {
  return useQuery({
    queryKey: THEMATIC_KEY,
    queryFn: async ({ signal }) => {
      const res = await http({ path: "/api/thematic/prefs", signal });
      return ThematicPrefsC.parse(res.data);
    },
    staleTime: 60_000,
  });
}

/**
 * The read query above plus the app's existing writers (useThematicQueries).
 * That hook keeps its own copy of the lists and exposes no loading or error
 * state, so the screen reads from the query and mirrors each write into the
 * query cache the same way the hook updates its own state.
 */
export function useThematicLibrary() {
  const prefs = useThematicPrefs();
  const { addHistory: writeHistory, removeHistory: dropHistory, toggleFavorite: writeFavorite } = useThematicQueries();
  const qc = useQueryClient();

  const patch = useCallback(
    (fn: (p: ThematicPrefs) => ThematicPrefs) => {
      qc.setQueryData<ThematicPrefs>(THEMATIC_KEY, (p) => (p ? fn(p) : p));
    },
    [qc],
  );

  const addHistory = useCallback(
    (question: string) => {
      const q = question.trim();
      if (!q) return;
      writeHistory(q);
      patch((p) => ({ ...p, history: [q, ...p.history.filter((x) => x !== q)].slice(0, HISTORY_CAP) }));
    },
    [writeHistory, patch],
  );

  const removeHistory = useCallback(
    (question: string) => {
      dropHistory(question);
      patch((p) => ({ ...p, history: p.history.filter((x) => x !== question) }));
    },
    [dropHistory, patch],
  );

  const toggleFavorite = useCallback(
    (question: string) => {
      const q = question.trim();
      if (!q) return;
      writeFavorite(q);
      patch((p) => ({
        ...p,
        favorites: p.favorites.includes(q) ? p.favorites.filter((x) => x !== q) : [q, ...p.favorites],
      }));
    },
    [writeFavorite, patch],
  );

  return { prefs, addHistory, removeHistory, toggleFavorite };
}

// ── one company's reported numbers ───────────────────────────────────────

const num = z.number().nullish();

const QuarterRowC = z.object({
  quarter: z.string().nullish(),
  period_end: z.string().nullish(),
  /** ₹ crore. */
  revenue_cr: num,
  ebitda_cr: num,
  pat_cr: num,
  /** ₹ per share. */
  eps_basic: num,
  /** Percent units. */
  ebitda_margin_pct: num,
  revenue_yoy_pct: num,
  pat_yoy_pct: num,
});
export type QuarterRow = z.infer<typeof QuarterRowC>;

const HoldingRowC = z.object({
  period: z.string().nullish(),
  period_end: z.string().nullish(),
  /** Percent of equity. */
  promoter_pct: num,
  promoter_pledged_pct: num,
  fii_pct: num,
  dii_pct: num,
  mf_pct: num,
  public_pct: num,
});
export type HoldingRow = z.infer<typeof HoldingRowC>;

const FeaturesC = z.object({
  pe_ttm: num,
  pb: num,
  /** Percent units. */
  roe_pct: num,
  debt_to_equity: num,
  /** ₹ crore. */
  market_cap_cr: num,
  market_cap_bucket: z.string().nullish(),
  /** The feature row's date, and where its ROE, P/B and market cap came from (nidp migration 162). */
  as_of_date: z.string().nullish(),
  fundamentals_source: z.string().nullish(),
  fundamentals_as_of: z.string().nullish(),
});
export type CompanyFeatures = z.infer<typeof FeaturesC>;

const CompanyFinancialsC = z.object({
  data: z
    .object({
      error: z.string().nullish(),
      /** Latest daily features; absent when the data platform has none for the symbol. */
      v3_score: FeaturesC.nullish(),
      /** Quarter rows, newest first, followed by shareholding rows tagged `_type`. */
      rows: z.array(z.record(z.unknown())).default([]),
    })
    .nullish(),
});

export interface CompanyNumbers {
  quarters: QuarterRow[];
  holdings: HoldingRow[];
  features: CompanyFeatures | null;
}

/**
 * POST /api/copilot/widgets/company_financials — reported quarterly results,
 * the shareholding pattern and the latest valuation features for one NSE symbol.
 * A read: the route only fetches from the data platform. The envelope's outlook
 * label and score are a heuristic and are deliberately not read here.
 */
export function useCompanyNumbers(symbol: string) {
  return useQuery({
    queryKey: ["copilot-widgets", "company-financials", symbol],
    enabled: !!symbol,
    staleTime: 5 * 60_000,
    queryFn: async ({ signal }): Promise<CompanyNumbers> => {
      const res = await http({
        method: "POST",
        path: "/api/copilot/widgets/company_financials",
        body: { symbol, quarters: 8 },
        signal,
      });
      const data = CompanyFinancialsC.parse(res.data).data;
      if (data?.error) throw new Error(data.error);
      const quarters: QuarterRow[] = [];
      const holdings: HoldingRow[] = [];
      for (const row of data?.rows ?? []) {
        if (row._type === "shareholding") {
          const h = HoldingRowC.safeParse(row);
          if (h.success) holdings.push(h.data);
        } else {
          const q = QuarterRowC.safeParse(row);
          if (q.success) quarters.push(q.data);
        }
      }
      return { quarters, holdings, features: data?.v3_score ?? null };
    },
  });
}

// ── the user's directly held stocks ──────────────────────────────────────

export interface DirectStock {
  /** NSE symbol in upper case; null when the holding carries none. */
  symbol: string | null;
  name: string;
  /** Shares held, as on the latest statement or broker sync. */
  quantity: number | null;
  /** Rupees. */
  valueRs: number | null;
}

export interface DirectStocks {
  stocks: DirectStock[];
  /** Mutual funds and ETFs in the portfolio. The stocks inside them are not looked through. */
  fundCount: number;
}

/**
 * GET /api/portfolio/holdings-enriched (the app's useHoldingsEnriched, same
 * cache) reduced to the stocks the user owns directly. Funds are only counted:
 * the look-through endpoint returns the top companies by name without an
 * exchange symbol, which is not enough to match a calendar row.
 */
export function useDirectStocks() {
  const q = useHoldingsEnriched();
  const data = useMemo((): DirectStocks | undefined => {
    if (!q.data) return undefined;
    const stocks: DirectStock[] = [];
    let fundCount = 0;
    for (const h of q.data.holdings) {
      const type = h.asset_type.toLowerCase();
      if (type === "mutual_fund" || type === "etf") fundCount += 1;
      if (type !== "equity" && type !== "stock") continue;
      const symbol = h.nse_symbol?.trim().toUpperCase() || null;
      stocks.push({ symbol, name: h.name, quantity: Number.isFinite(h.quantity) ? h.quantity : null, valueRs: h.value_rs ?? null });
    }
    return { stocks, fundCount };
  }, [q.data]);
  return { data, isPending: q.isPending, isError: q.isError, error: q.error, refetch: q.refetch };
}

export interface StockIndex {
  bySymbol: Map<string, DirectStock>;
  byName: Map<string, DirectStock>;
}

export function indexStocks(stocks: DirectStock[]): StockIndex {
  const bySymbol = new Map<string, DirectStock>();
  const byName = new Map<string, DirectStock>();
  for (const s of stocks) {
    if (s.symbol) bySymbol.set(s.symbol, s);
    const n = normName(s.name);
    if (n) byName.set(n, s);
  }
  return { bySymbol, byName };
}

/** The directly held stock a calendar row refers to: by NSE symbol, else by company name. */
export function findStock(index: StockIndex, symbol?: string | null, name?: string | null): DirectStock | undefined {
  const bySymbol = symbol ? index.bySymbol.get(symbol.trim().toUpperCase()) : undefined;
  if (bySymbol) return bySymbol;
  const n = normName(name);
  return n ? index.byName.get(n) : undefined;
}

// ── results calendar (upcoming result dates) ─────────────────────────────

const CalendarEventC = z.object({
  symbol: z.string(),
  company_name: z.string().nullish(),
  /** quarterly_results, board_meeting, agm, dividend, … */
  event_type: z.string().nullish(),
  /** YYYY-MM-DD. */
  event_date: z.string().nullish(),
  /** "Q2 FY27" when the notice named a period. */
  period: z.string().nullish(),
  purpose: z.string().nullish(),
  /** Where the calendar row came from, as the route reports it. */
  calendar_source: z.string().nullish(),
});
export type CalendarEvent = z.infer<typeof CalendarEventC>;

const CalendarDayC = z.object({
  events: z.array(z.unknown()).default([]),
  /** Set by the route (with HTTP 200) when it could not read its calendar. */
  _error: z.string().nullish(),
  _reason: z.string().nullish(),
});

interface CalendarDay {
  events: CalendarEvent[];
  /** The route answered but said it could not read the calendar. */
  unavailable: boolean;
}

async function fetchCalendarDay(date: string, signal?: AbortSignal): Promise<CalendarDay> {
  const res = await http({ path: "/api/market/events", query: { date_str: date }, signal });
  const parsed = CalendarDayC.safeParse(res.data);
  if (!parsed.success) throw ApiError.contractDrift(`market.events: ${parsed.error.message}`);
  const events = parsed.data.events.flatMap((e) => {
    const row = CalendarEventC.safeParse(e);
    return row.success ? [row.data] : [];
  });
  return { events, unavailable: !!(parsed.data._error || parsed.data._reason) };
}

/** Days ahead the results calendar is read for (today included). */
export const RESULTS_WINDOW_DAYS = 14;

export interface ResultsCalendar {
  /** "unavailable": the route answered, but could not read its calendar. */
  status: "loading" | "error" | "unavailable" | "ready";
  /** Scheduled quarterly-results events in the window, soonest first. */
  events: CalendarEvent[];
  from: string;
  to: string;
  error: unknown;
  refetch: () => void;
}

/**
 * GET /api/market/events?date_str= — the event calendar, which the route serves
 * one day per call. Today is read first; the remaining days are requested only
 * when that call could read the calendar, so an unavailable calendar costs one
 * request, not fourteen.
 */
export function useResultsCalendar(enabled = true): ResultsCalendar {
  const days = useMemo(() => Array.from({ length: RESULTS_WINDOW_DAYS }, (_, i) => isoDay(i)), []);
  const first = useQuery({
    queryKey: ["market-events", "day", days[0]],
    queryFn: ({ signal }) => fetchCalendarDay(days[0], signal),
    enabled,
    staleTime: 5 * 60_000,
  });
  const usable = first.isSuccess && !first.data.unavailable;
  const rest = useQueries({
    queries: days.slice(1).map((day) => ({
      queryKey: ["market-events", "day", day],
      queryFn: ({ signal }: { signal: AbortSignal }) => fetchCalendarDay(day, signal),
      enabled: enabled && usable,
      staleTime: 5 * 60_000,
    })),
  });

  const base = { from: days[0], to: days[days.length - 1] };
  const refetch = () => {
    void first.refetch();
    for (const r of rest) if (r.isError) void r.refetch();
  };
  if (first.isError) return { ...base, status: "error", events: [], error: first.error, refetch };
  const failed = rest.find((r) => r.isError);
  if (failed) return { ...base, status: "error", events: [], error: failed.error, refetch };
  if (first.isPending) return { ...base, status: "loading", events: [], error: null, refetch };
  if (first.data.unavailable || rest.some((r) => r.data?.unavailable)) {
    return { ...base, status: "unavailable", events: [], error: null, refetch };
  }
  if (rest.some((r) => r.isPending)) return { ...base, status: "loading", events: [], error: null, refetch };

  const events = [first.data, ...rest.flatMap((r) => (r.data ? [r.data] : []))]
    .flatMap((d) => d.events)
    .filter((e) => e.event_type === "quarterly_results" && !!e.event_date)
    .sort((a, b) => (a.event_date ?? "").localeCompare(b.event_date ?? "") || a.symbol.localeCompare(b.symbol));
  return { ...base, status: "ready", events, error: null, refetch };
}

// ── this quarter's results for the user's stocks ─────────────────────────

export interface HeldResult {
  stock: DirectStock;
  company: EarningsCompany;
  sector: string;
}

export interface HeldResults {
  status: "loading" | "error" | "ready";
  /** Directly held stocks that are in the index, reported ones first. */
  rows: HeldResult[];
  /** Directly held stocks the index does not contain. */
  outside: DirectStock[];
  error: unknown;
  refetch: () => void;
}

/**
 * GET /api/markets/earnings/companies for every sector of the index, joined
 * with the user's directly held stocks. Same query keys as the sector
 * drill-down, so opening a sector afterwards costs no request.
 */
export function useHeldResults({ index, quarter, sectors, stocks, enabled }: {
  index: string;
  quarter?: string;
  sectors: string[];
  stocks: DirectStock[];
  enabled: boolean;
}): HeldResults {
  const on = enabled && stocks.length > 0;
  const lists = useQueries({
    queries: sectors.map((sector) => {
      const params: EarningsCompaniesQuery = { index, sector, quarter };
      return {
        queryKey: ["markets", "earnings-companies", params],
        queryFn: () => marketsService.getEarningsCompanies(params),
        enabled: on,
        staleTime: 5 * 60_000,
      };
    }),
  });

  const refetch = () => {
    for (const r of lists) if (r.isError) void r.refetch();
  };
  const failed = lists.find((r) => r.isError);
  if (failed) return { status: "error", rows: [], outside: [], error: failed.error, refetch };
  if (on && lists.some((r) => r.isPending)) return { status: "loading", rows: [], outside: [], error: null, refetch };

  const held = indexStocks(stocks);
  const seen = new Set<DirectStock>();
  const rows: HeldResult[] = [];
  lists.forEach((r, i) => {
    for (const company of r.data?.companies ?? []) {
      const stock = findStock(held, company.symbol, company.name);
      if (!stock || seen.has(stock)) continue;
      seen.add(stock);
      rows.push({ stock, company, sector: sectors[i] });
    }
  });
  rows.sort((a, b) => Number(b.company.declared) - Number(a.company.declared) || a.stock.name.localeCompare(b.stock.name));
  return { status: "ready", rows, outside: stocks.filter((s) => !seen.has(s)), error: null, refetch };
}

// ── corporate actions on the user's stocks ───────────────────────────────

export interface HeldAction {
  stock: DirectStock;
  action: CorpAction;
}

/** The calendar rows that name a stock the user holds directly, soonest ex-date first. */
export function heldActions(actions: CorpAction[], stocks: DirectStock[]): HeldAction[] {
  const index = indexStocks(stocks);
  return actions
    .flatMap((action) => {
      const stock = findStock(index, action.symbol, action.name);
      return stock ? [{ stock, action }] : [];
    })
    .sort((a, b) => (a.action.ex_date ?? "9999").localeCompare(b.action.ex_date ?? "9999"));
}
