/**
 * Smart trading desk · Overview — the reads the Overview tab needs that had no
 * hook yet, and the small derivations it shows.
 *
 *   GET /api/macro/today                    the macro regime: `market` BULL / NEUTRAL / BEAR is the Nifty 50
 *                                           against its 50-day average (services/macro_engine.py), plus `risk`
 *                                           and the engine's own `insight` line
 *   GET /api/positional/market-dashboard    `sector_heatmap`: today's sector-index change when a row says
 *                                           `source: "nse_live"`, otherwise the mean 5-session return of the
 *                                           sector's stocks from end-of-day bars (positional_engine/market_dashboard.py)
 *
 * GET /api/markets/home (index tape, breadth, FII / DII, USD / INR, Brent, the
 * deploy verdict) is read through useMarketOverview (screens/markets/hooks.ts).
 *
 * Nothing here trusts the response shape: a missing or non-numeric field is
 * null, never 0, and a body without the field the route always sends throws a
 * contract error. /macro/today never answers 500 on an internal failure; it
 * sends an "uninitialised" payload with `_reason` instead, which is read as
 * "not available", never as a regime.
 */
import { useQuery } from "@tanstack/react-query";
import { http } from "@/services/api/http";
import { ApiError } from "@/services/api/errors";
import type { GlobalQuote, MarketBreadth, MarketIndex, MarketsHome } from "@/services/contracts/markets.contract";
import { num } from "./desk-data";

type Raw = Record<string, unknown>;
const isRec = (v: unknown): v is Raw => !!v && typeof v === "object" && !Array.isArray(v);
const rec = (v: unknown): Raw => (isRec(v) ? v : {});
const str = (v: unknown): string | null => (typeof v === "string" && v.trim() ? v.trim() : null);

const drift = (what: string) => ApiError.contractDrift(what);
const noRetry4xx = (count: number, e: unknown) =>
  !(e instanceof ApiError && (e.kind === "contract_drift" || (e.status != null && e.status >= 400 && e.status < 500))) && count < 1;

// ── macro regime ─────────────────────────────────────────────────────────

export type Regime = "BULL" | "NEUTRAL" | "BEAR";

export type MacroToday =
  | {
      kind: "ready";
      regime: Regime;
      /** LOW | MEDIUM | HIGH, as the engine stores it. */
      risk: string | null;
      /** The engine's own one-line read (rules-based). */
      insight: string | null;
      /** The session the state was computed for. */
      date: string | null;
      /** Days between that session and today (0 = today). */
      daysStale: number | null;
    }
  /** The route answered with its "uninitialised" payload: there is no regime to show. */
  | { kind: "unavailable"; reason: string | null };

async function fetchMacro(signal?: AbortSignal): Promise<MacroToday> {
  const res = await http({ path: "/api/macro/today", signal });
  if (!isRec(res.data)) throw drift("macro.today: not an object");
  const d = res.data;
  if (d._uninitialised === true) return { kind: "unavailable", reason: str(d._reason) };
  const market = (str(d.market) ?? "").toUpperCase();
  if (market !== "BULL" && market !== "NEUTRAL" && market !== "BEAR") throw drift("macro.today: no market regime");
  return {
    kind: "ready",
    regime: market,
    risk: str(d.risk)?.toUpperCase() ?? null,
    insight: str(d.insight),
    date: str(d.date),
    daysStale: num(d.days_stale),
  };
}

/** GET /api/macro/today — the daily macro state (computed after the close, 18:35 IST). */
export function useMacroToday() {
  return useQuery<MacroToday>({
    queryKey: ["copilot", "desk", "macro-today"],
    staleTime: 10 * 60_000,
    retry: noRetry4xx,
    queryFn: ({ signal }) => fetchMacro(signal),
  });
}

export const REGIME_LABEL: Record<Regime, string> = { BULL: "Bullish", NEUTRAL: "Neutral", BEAR: "Bearish" };

/** What each regime means, from the engine's rule (macro_engine.compute_features). */
export const REGIME_MEANING: Record<Regime, string> = {
  BULL: "The Nifty 50 closed above its 50-day average.",
  NEUTRAL: "The Nifty 50 is level with its 50-day average, or the average could not be worked out.",
  BEAR: "The Nifty 50 closed below its 50-day average.",
};

// ── sector strength ──────────────────────────────────────────────────────

export interface SectorTile {
  sector: string;
  /** Percent. Today's sector-index change (live rows) or the 5-session mean return (end of day). */
  pct: number | null;
  /** Percentage points against the Nifty over the same period. */
  rsPp: number | null;
  /** HOT | WARM | COOL | COLD, as the route sends it. */
  tone: string | null;
  /** Stocks the end-of-day figures were averaged over. */
  stocks: number | null;
  /** The sector's best 5-session performer in the end-of-day bars. */
  leader: { symbol: string; ret5dPct: number | null } | null;
  /** True when the row is the live sector index (source "nse_live"). */
  live: boolean;
}

/** "today" = every row is a sector index's change today; "5d" = every row is the end-of-day 5-session mean. */
export type SectorPeriod = "today" | "5d" | "mixed";

export type SectorStrength =
  | { kind: "ready"; tiles: SectorTile[]; period: SectorPeriod; asOf: string | null; fetchedAt: string | null; isLive: boolean }
  /** The route answered `{ ok: false, error }` (no price table, no database). */
  | { kind: "unavailable"; reason: string | null };

async function fetchSectors(signal?: AbortSignal): Promise<SectorStrength> {
  // The builder reads 80 days of bars for every stock on a cold cache.
  const res = await http({ path: "/api/positional/market-dashboard", timeoutMs: 30_000, signal });
  if (!isRec(res.data)) throw drift("positional.market-dashboard: not an object");
  const d = res.data;
  if (d.ok === false) return { kind: "unavailable", reason: str(d.error) };
  if (!Array.isArray(d.sector_heatmap)) throw drift("positional.market-dashboard: no sector_heatmap");
  const tiles: SectorTile[] = [];
  for (const v of d.sector_heatmap) {
    const r = rec(v);
    const sector = str(r.sector);
    if (!sector) continue;
    const l = rec(r.leader);
    const leaderSym = str(l.nse_symbol);
    tiles.push({
      sector,
      pct: num(r.ret_5d_pct),
      rsPp: num(r.rs_5d_pp),
      tone: str(r.tone),
      stocks: num(r.stocks),
      leader: leaderSym ? { symbol: leaderSym.toUpperCase(), ret5dPct: num(l.ret_5d_pct) } : null,
      live: str(r.source) === "nse_live",
    });
  }
  tiles.sort((a, b) => (b.pct ?? -Infinity) - (a.pct ?? -Infinity));
  const live = tiles.filter((t) => t.live).length;
  const period: SectorPeriod = live === 0 ? "5d" : live === tiles.length ? "today" : "mixed";
  return { kind: "ready", tiles, period, asOf: str(d.as_of_date), fetchedAt: str(d.fetched_at), isLive: d.is_live === true };
}

/** GET /api/positional/market-dashboard — the sector heatmap. */
export function useSectorStrength() {
  return useQuery<SectorStrength>({
    queryKey: ["copilot", "desk", "market-dashboard"],
    staleTime: 60_000,
    refetchInterval: 5 * 60_000,
    retry: noRetry4xx,
    queryFn: ({ signal }) => fetchSectors(signal),
  });
}

// ── /markets/home derivations ────────────────────────────────────────────

/** The four index tiles of the design, by the names GET /api/markets/home sends (nse_live.TAPE_INDICES). */
export const DESK_INDICES: Array<{ name: string; vix: boolean }> = [
  { name: "Nifty 50", vix: false },
  { name: "Nifty Bank", vix: false },
  { name: "Sensex", vix: false },
  { name: "India VIX", vix: true },
];

/** One index by its exact name ("Nifty 50" must not match "Nifty 500"); the VIX also by its flag. */
export function findIndex(home: MarketsHome, name: string, vix: boolean): MarketIndex | null {
  const n = name.toLowerCase();
  return home.indices.find((i) => i.name.trim().toLowerCase() === n) ?? (vix ? home.indices.find((i) => i.is_vix) ?? null : null);
}

/** A global quote by name, from the pre-open cues first, then commodities ("USD / INR", "Brent Crude"). */
export function findQuote(home: MarketsHome, name: string): GlobalQuote | null {
  const n = name.toLowerCase();
  return [...home.global_cues, ...home.commodities].find((q) => q.name.trim().toLowerCase() === n) ?? null;
}

/**
 * Which stocks the breadth counts cover. The route prefers the full end-of-day
 * count (every NSE stock with 21+ sessions of daily bars) and falls back to a
 * live count over the Nifty 50 constituents. The response does not name the
 * universe, so it is read from its size: 60 stocks or fewer can only be the
 * Nifty 50 fallback.
 */
export type BreadthScope = "eod" | "nifty50" | "unknown";

export interface BreadthRead {
  advances: number;
  declines: number;
  unchanged: number | null;
  /** advances + declines + unchanged. */
  total: number;
  /** advances ÷ total × 100. */
  advancingPct: number;
  universe: number | null;
  scope: BreadthScope;
}

export function readBreadth(b: MarketBreadth): BreadthRead | null {
  if (b.advances == null || b.declines == null) return null;
  const unchanged = b.unchanged ?? null;
  const total = b.advances + b.declines + (unchanged ?? 0);
  if (total <= 0) return null;
  const universe = b.universe ?? null;
  return {
    advances: b.advances,
    declines: b.declines,
    unchanged,
    total,
    advancingPct: (b.advances / total) * 100,
    universe,
    scope: universe == null ? "unknown" : universe <= 60 ? "nifty50" : "eod",
  };
}
