/**
 * Research → one stock / one mutual fund: reads of existing backend routes that
 * had no hook yet. GET only; nothing here changes data.
 *
 *   Stock
 *     Research card      GET /api/move-odds/stocks/{symbol}/card      useStockCard
 *                        (the Copilot's own stock card; the same adapter the
 *                        original Research page uses)
 *     Price history      GET /api/research/chart-live/{symbol}/ohlcv  usePriceHistory
 *     Market backdrop    GET /api/stock/{symbol}/why                  useStockBackdrop
 *   Mutual fund
 *     Scheme + NAV       GET /api/mf/lookup                           useFundLookup
 *     Returns and risk   GET /api/portfolio/holding-detail/{isin}     useFundNumbers
 *     Factsheet          GET /api/mf/holdings                         useFundFactsheet
 *
 * The first two stock routes are switched on per account. A 403 is returned as
 * `{ kind: "locked" }` so the screen can say so instead of showing an error.
 *
 * A fetcher returns a complete typed value or throws: ApiError("contract_drift")
 * when a 200 body is not the shape it needs (that includes `{}`).
 *
 * Units: prices and NAV in rupees; AUM and holding values in ₹ crore; every
 * percentage in percent units (12.4 = 12.4%).
 */
import { useQuery } from "@tanstack/react-query";
import { z } from "zod";
import { http } from "@/services/api/http";
import { ApiError } from "@/services/api/errors";
import { fetchStockCard, type MoveStockCard } from "@/services/adapters/moveOdds.adapter";

const num = z.number().nullish();
const text = z.string().nullish();

function parse<T>(schema: z.ZodType<T, z.ZodTypeDef, unknown>, body: unknown): T {
  const r = schema.safeParse(body);
  if (!r.success) throw ApiError.contractDrift(r.error.issues[0]?.message ?? "unexpected shape", r.error);
  return r.data;
}

function isStatus(e: unknown, status: number): boolean {
  return e instanceof ApiError && e.status === status;
}

/** YYYY-MM-DD for today shifted by `days` (local calendar day). */
function dayFromToday(days: number): string {
  const d = new Date();
  d.setDate(d.getDate() + days);
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}

/** YYYY-MM-DD shifted by whole days, in UTC so a calendar day never slips. */
function shiftDay(day: string, days: number): string {
  const t = Date.parse(`${day}T00:00:00Z`);
  if (!Number.isFinite(t)) return day;
  return new Date(t + days * 86_400_000).toISOString().slice(0, 10);
}

// ── stock: the Copilot's research card ───────────────────────────────────

export type StockCard =
  | { kind: "ok"; widget: MoveStockCard }
  /** The data platform has no research for this symbol. */
  | { kind: "none" }
  /** This account is not on the list the card is switched on for. */
  | { kind: "locked" };

/** GET /api/move-odds/stocks/{symbol}/card — scores, valuation, technicals, risk and peers for one stock. */
export function useStockCard(symbol: string) {
  return useQuery({
    queryKey: ["research", "stock-card", symbol],
    enabled: !!symbol,
    staleTime: 5 * 60_000,
    queryFn: async (): Promise<StockCard> => {
      const r = await fetchStockCard(symbol.toUpperCase());
      if (r.kind === "ok") return r;
      if (r.kind === "not_found") return { kind: "none" };
      if (r.kind === "no_access") return { kind: "locked" };
      throw new Error(r.message);
    },
  });
}

// ── stock: daily prices ──────────────────────────────────────────────────

/** [date, open, high, low, close, volume] — split and bonus adjusted. */
const BarC = z.tuple([z.string(), z.number(), z.number(), z.number(), z.number(), z.number()]);

const PriceHistoryC = z.object({
  bars: z.array(BarC),
  data_quality_status: text,
});

export interface PricePoint {
  /** YYYY-MM-DD. */
  day: string;
  close: number;
  high: number;
  low: number;
  /** Shares traded. */
  volume: number;
  /** Mean close of the 200 sessions ending this day; null until 200 sessions exist. */
  avg200: number | null;
}

export interface PriceSeries {
  /** Oldest first: the sessions of the 12 months up to the last one. */
  points: PricePoint[];
  last: PricePoint;
  /** Change from the previous session's close. */
  dayChangePct: number | null;
  /** Highest high and lowest low across `points`. */
  high: number;
  low: number;
  /** First close in `points` to the last. */
  changePct: number | null;
  /** False when the stock has traded for less than the 12 months shown. */
  fullYear: boolean;
  /** True when the data platform dropped incomplete sessions from this series. */
  partial: boolean;
}

export type PriceHistory =
  | { kind: "ok"; series: PriceSeries }
  /** No daily prices on record for this symbol. */
  | { kind: "none" }
  | { kind: "locked" };

const SMA_SESSIONS = 200;

/** Turn raw bars (oldest first) into the 12-month view. Null when there are no bars. */
export function buildPriceSeries(bars: z.infer<typeof BarC>[], partial: boolean): PriceSeries | null {
  if (bars.length === 0) return null;
  const closes = bars.map((b) => b[4]);
  let running = 0;
  const avg200 = closes.map((c, i) => {
    running += c;
    if (i >= SMA_SESSIONS) running -= closes[i - SMA_SESSIONS];
    return i >= SMA_SESSIONS - 1 ? running / SMA_SESSIONS : null;
  });

  const lastDay = bars[bars.length - 1][0];
  const from = shiftDay(lastDay, -365);
  const start = Math.max(0, bars.findIndex((b) => b[0] >= from));
  const points: PricePoint[] = bars.slice(start).map((b, i) => ({
    day: b[0], high: b[2], low: b[3], close: b[4], volume: b[5], avg200: avg200[start + i],
  }));
  const last = points[points.length - 1];
  const prev = bars.length > 1 ? closes[closes.length - 2] : null;
  const first = points[0].close;

  return {
    points,
    last,
    dayChangePct: prev != null && prev > 0 ? ((last.close - prev) / prev) * 100 : null,
    high: Math.max(...points.map((p) => p.high)),
    low: Math.min(...points.map((p) => p.low)),
    changePct: points.length > 1 && first > 0 ? ((last.close - first) / first) * 100 : null,
    // A week of slack for holidays around the first session of the window.
    fullYear: start > 0 || points[0].day <= shiftDay(from, 7),
    partial,
  };
}

/**
 * GET /api/research/chart-live/{symbol}/ohlcv — daily bars for any NSE symbol.
 * Two years are read so the 200-session average exists across the 12 months shown.
 */
export function usePriceHistory(symbol: string) {
  return useQuery({
    queryKey: ["research", "price-history", symbol],
    enabled: !!symbol,
    staleTime: 10 * 60_000,
    queryFn: async ({ signal }): Promise<PriceHistory> => {
      try {
        const res = await http({
          path: `/api/research/chart-live/${encodeURIComponent(symbol.toUpperCase())}/ohlcv`,
          query: { start: dayFromToday(-730) },
          signal,
        });
        const body = parse(PriceHistoryC, res.data);
        const series = buildPriceSeries(body.bars, body.data_quality_status === "PARTIAL");
        return series ? { kind: "ok", series } : { kind: "none" };
      } catch (e) {
        if (isStatus(e, 403)) return { kind: "locked" };
        if (isStatus(e, 404)) return { kind: "none" };
        throw e;
      }
    },
  });
}

// ── stock: market backdrop ───────────────────────────────────────────────

const StockBackdropC = z.object({
  raw_sector: text,
  macro_state: z.object({ market: text, inflation: text, liquidity: text, risk: text }),
  /** FAVORABLE / NEUTRAL / UNFAVORABLE for the stock's sector. */
  sector_bias: text,
  sector_rationale: text,
});
export type StockBackdrop = z.infer<typeof StockBackdropC>;

/** GET /api/stock/{symbol}/why — today's market regime and how it leans for this stock's sector. */
export function useStockBackdrop(symbol: string) {
  return useQuery({
    queryKey: ["research", "stock-backdrop", symbol],
    enabled: !!symbol,
    staleTime: 10 * 60_000,
    queryFn: async ({ signal }) => {
      const res = await http({ path: `/api/stock/${encodeURIComponent(symbol.toUpperCase())}/why`, signal });
      return parse(StockBackdropC, res.data);
    },
  });
}

// ── fund: scheme and latest NAV ──────────────────────────────────────────

const FundLookupC = z.object({
  resolved: z.object({ scheme_name: text, isin: text, symbol: text }),
  latest_nav: z.object({ nav: num, nav_date: text }).nullish(),
});
export type FundLookup = z.infer<typeof FundLookupC>;

/** GET /api/mf/lookup — the scheme's ISIN and its latest NAV on the data platform. */
export function useFundLookup(name: string, schemeCode: string | null | undefined) {
  return useQuery({
    queryKey: ["research", "fund-lookup", schemeCode ?? name],
    enabled: !!(schemeCode || name),
    staleTime: 10 * 60_000,
    queryFn: async ({ signal }) => {
      const res = await http({
        path: "/api/mf/lookup",
        query: schemeCode ? { scheme_code: schemeCode } : { scheme_name: name },
        signal,
      });
      return parse(FundLookupC, res.data);
    },
  });
}

// ── fund: returns, risk and rank ─────────────────────────────────────────

const FundNumbersC = z.object({
  name: text,
  category: text,
  returns: z.object({ "1m": num, "3m": num, "1y": num, "3y": num }),
  category_avg: z.object({ "1y": num, "3y": num }),
  risk: z.object({ sharpe: num, sortino: num, volatility_1y: num, max_drawdown: num }),
  ranking: z.object({ composite_rank: num, category_size: num }),
  top_peers: z.array(z.object({ name: text, return_1y: num, composite_rank: num })).default([]),
  /** False when the data platform has no figures for this ISIN. */
  daas_available: z.boolean(),
});
export type FundNumbers = z.infer<typeof FundNumbersC>;

/** GET /api/portfolio/holding-detail/{isin} — the figures the original app's holding drawer shows. */
export function useFundNumbers(isin: string | null | undefined) {
  return useQuery({
    queryKey: ["research", "fund-numbers", isin],
    enabled: !!isin,
    staleTime: 10 * 60_000,
    queryFn: async ({ signal }) => {
      const res = await http({ path: `/api/portfolio/holding-detail/${encodeURIComponent(isin ?? "")}`, signal });
      return parse(FundNumbersC, res.data);
    },
  });
}

// ── fund: factsheet ──────────────────────────────────────────────────────

const FactHoldingC = z.object({ name: z.string(), sector: text, instrument_type: text, pct: num });
export type FactHolding = z.infer<typeof FactHoldingC>;

const FactManagerC = z.object({ name: z.string(), since: text, tenure_years: num });
export type FactManager = z.infer<typeof FactManagerC>;

/** One plan of a scheme. The response carries two: the plan it found and its Direct / Regular sibling. */
const FactPlanC = z.object({
  holdings: z.array(FactHoldingC).default([]),
  sectors: z.array(z.object({ name: z.string(), pct: num })).default([]),
  split: z.object({ equity: num, debt: num, cash: num }).nullish(),
  metadata: z
    .object({
      scheme_code: text,
      scheme_name: text,
      plan_type: text,
      benchmark: text,
      risk_label: text,
      launch_date: text,
      aum_cr: num,
      expense_ratio: num,
      min_sip: num,
      portfolio_turnover: num,
    })
    .nullish(),
  v3_primitives: z
    .object({ fund_managers: z.array(FactManagerC).default([]), top10_concentration_pct: num })
    .nullish(),
});
type FactPlan = z.infer<typeof FactPlanC>;

const FactsheetC = FactPlanC.extend({
  /** False when no factsheet has been collected for the scheme. */
  available: z.boolean(),
  fetched_at: text,
  sibling: FactPlanC.nullish(),
});

export interface FundFactsheet {
  plan: FactPlan;
  /** True when `plan` is the plan of the scheme code that was asked for. */
  exactPlan: boolean;
  /** When the factsheet was collected (ISO). */
  fetchedAt: string | null;
}

/**
 * GET /api/mf/holdings — the scheme's factsheet: size, cost, managers and what it
 * holds. Null when none has been collected.
 *
 * The response leads with whichever plan the collector found first, which is
 * not always the plan that was asked for (a Regular scheme code can come back
 * with the Direct plan on top and the Regular one under `sibling`). The plan
 * whose scheme code matches is used; if neither matches, the leading plan is
 * returned with `exactPlan: false` so the screen can name the plan it shows.
 */
export function useFundFactsheet(name: string, schemeCode: string | null | undefined) {
  return useQuery({
    queryKey: ["research", "fund-factsheet", schemeCode ?? name],
    enabled: !!name,
    staleTime: 30 * 60_000,
    queryFn: async ({ signal }): Promise<FundFactsheet | null> => {
      const res = await http({
        path: "/api/mf/holdings",
        query: { scheme_name: name, scheme_code: schemeCode ?? undefined },
        timeoutMs: 45_000,
        signal,
      });
      const body = parse(FactsheetC, res.data);
      if (!body.available) return null;
      const plans: FactPlan[] = [body, ...(body.sibling ? [body.sibling] : [])];
      const exact = schemeCode ? plans.find((p) => p.metadata?.scheme_code === schemeCode) : undefined;
      return { plan: exact ?? body, exactPlan: !!exact, fetchedAt: body.fetched_at ?? null };
    },
  });
}
