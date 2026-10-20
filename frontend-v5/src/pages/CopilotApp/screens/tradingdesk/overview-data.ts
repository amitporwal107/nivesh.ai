/**
 * Smart trading desk · Overview — the reads the Overview tab needs that had no
 * hook yet, and the small derivations it shows.
 *
 *   GET /api/macro/today                    the macro state (`market` BULL / NEUTRAL / BEAR = the Nifty 50 against
 *                                           its 50-day average, `risk`, the engine's `insight`) and `regime`: the
 *                                           desk's five-regime reading of the same session (macro_engine.
 *                                           classify_desk_regime — the rule, its thresholds, the inputs it read,
 *                                           the checks it could not make and what would change it)
 *   GET /api/markets/sector-returns         NSE sectoral indices' end-of-day close and their 1-day, 1-week and
 *                                           1-month returns (close vs the close N sessions earlier for that index;
 *                                           DaaS nidp.index_eod), with the route's own source and as-of date, and
 *                                           `in_sector_breadth` for the indices with a constituent list
 *   GET /api/markets/sector-constituents?index=   one sector index's constituents and each one's move on the index's
 *                                           latest close day (nidp.index_constituents, nidp.prices_eod)
 *   GET /api/positional/picks/mine?live=true      the scanner's picks with a delayed live price, readiness and the
 *                                           conviction check's penalties (the "against" side of a setup)
 *   GET /api/positional/market-dashboard    `sector_heatmap` leaders only: each sector's best 5-session stock from
 *                                           end-of-day bars (positional_engine/market_dashboard.py), shown on a
 *                                           sector-index tile when the two sector names match exactly
 *
 * GET /api/markets/home (index tape, breadth and the universe it counted, FII /
 * DII, USD / INR, Brent, the deploy verdict, `market_state`, `is_live` and
 * `session` — the NSE session by the IST clock and the NSE holiday list) is
 * read through useMarketOverview (screens/markets/hooks.ts).
 *
 * The market-status pill and the Overview's headline are worked out here from
 * those reads (marketStatus, deskHeadline): no figure is made up, and a part
 * with no data is left out of the sentence rather than guessed.
 *
 * Nothing here trusts the response shape: a missing or non-numeric field is
 * null, never 0, and a body without the field the route always sends throws a
 * contract error. /macro/today never answers 500 on an internal failure; it
 * sends an "uninitialised" payload with `_reason` instead, which is read as
 * "not available", never as a regime.
 */
import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { http } from "@/services/api/http";
import { ApiError } from "@/services/api/errors";
import type { GlobalQuote, MarketBreadth, MarketIndex, MarketsHome } from "@/services/contracts/markets.contract";
import type { EnrichedHoldingsRes } from "@/services/contracts/portfolio.contract";
import type { DeskPersona } from "./context";
import { scanDateLabel } from "./chart-data";
import { num, type DeskScanner, type DeskSetup, type ScanUniverse } from "./desk-data";
import type { IntelEvent } from "./intel-data";

type Raw = Record<string, unknown>;
const isRec = (v: unknown): v is Raw => !!v && typeof v === "object" && !Array.isArray(v);
const rec = (v: unknown): Raw => (isRec(v) ? v : {});
const str = (v: unknown): string | null => (typeof v === "string" && v.trim() ? v.trim() : null);

const drift = (what: string) => ApiError.contractDrift(what);
const noRetry4xx = (count: number, e: unknown) =>
  !(e instanceof ApiError && (e.kind === "contract_drift" || (e.status != null && e.status >= 400 && e.status < 500))) && count < 1;

// ── macro regime ─────────────────────────────────────────────────────────

export type Regime = "BULL" | "NEUTRAL" | "BEAR";

/** The desk's five regimes (PRD OV-003), as GET /api/macro/today sends them in `regime.key`. */
export const DESK_REGIME_KEYS = ["bearish", "sideways", "bullish", "mixed", "high_volatility"] as const;
export type DeskRegimeKey = (typeof DESK_REGIME_KEYS)[number];

export const DESK_REGIME_LABEL: Record<DeskRegimeKey, string> = {
  bearish: "Bearish",
  sideways: "Sideways",
  bullish: "Bullish",
  mixed: "Mixed",
  high_volatility: "High volatility",
};

/** The rule's thresholds, as the route sends them (macro_engine.DESK_REGIME_RULE). */
export interface RegimeRule {
  version: string | null;
  vixHigh: number | null;
  averageSessions: number | null;
  breadthUpPct: number | null;
  breadthDownPct: number | null;
}

/** One single change that would move the reading to another regime. */
export interface RegimeFlip {
  input: "nifty_close" | "india_vix" | "advancing_share_pct";
  condition: "below" | "above" | "at_or_above" | "at_or_below";
  level: number;
  then: DeskRegimeKey;
}

export interface DeskRegime {
  /** null = the rule could not classify the session (`reason` says why). */
  key: DeskRegimeKey | null;
  date: string | null;
  rule: RegimeRule;
  niftyClose: number | null;
  niftyAverage: number | null;
  /** Percent above (+) or below (−) the average. */
  gapPct: number | null;
  trend: "up" | "down" | "flat" | null;
  vix: number | null;
  vixHigh: boolean | null;
  advances: number | null;
  declines: number | null;
  unchanged: number | null;
  breadthUniverse: number | null;
  /** advances ÷ (advances + declines) × 100. */
  sharePct: number | null;
  breadth: "up" | "down" | "even" | null;
  breadthDate: string | null;
  breadthSource: string | null;
  /** Checks the rule could not make, each with the route's reason. */
  skipped: Array<{ check: string; reason: string }>;
  invalidation: RegimeFlip[];
  reason: string | null;
}

const FLIP_INPUTS = ["nifty_close", "india_vix", "advancing_share_pct"] as const;
const FLIP_CONDITIONS = ["below", "above", "at_or_above", "at_or_below"] as const;
const isOneOf = <T extends string>(list: readonly T[], v: unknown): v is T => typeof v === "string" && (list as readonly string[]).includes(v);

function readDeskRegime(v: unknown): DeskRegime | null {
  if (!isRec(v)) return null;
  const rule = rec(v.rule);
  const i = rec(v.inputs);
  const trend = str(i.trend);
  const breadth = str(i.breadth);
  return {
    key: isOneOf(DESK_REGIME_KEYS, v.key) ? v.key : null,
    date: str(v.date),
    rule: {
      version: str(rule.version),
      vixHigh: num(rule.vix_high),
      averageSessions: num(rule.trend_average_sessions),
      breadthUpPct: num(rule.breadth_up_pct),
      breadthDownPct: num(rule.breadth_down_pct),
    },
    niftyClose: num(i.nifty_close),
    niftyAverage: num(i.nifty_average),
    gapPct: num(i.nifty_vs_average_pct),
    trend: trend === "up" || trend === "down" || trend === "flat" ? trend : null,
    vix: num(i.india_vix),
    vixHigh: typeof i.volatility_high === "boolean" ? i.volatility_high : null,
    advances: num(i.advances),
    declines: num(i.declines),
    unchanged: num(i.unchanged),
    breadthUniverse: num(i.breadth_universe),
    sharePct: num(i.advancing_share_pct),
    breadth: breadth === "up" || breadth === "down" || breadth === "even" ? breadth : null,
    breadthDate: str(i.breadth_date),
    breadthSource: str(i.breadth_source),
    skipped: (Array.isArray(v.skipped) ? v.skipped : []).flatMap((x) => {
      const r = rec(x);
      const check = str(r.check);
      const reason = str(r.reason);
      return check && reason ? [{ check, reason }] : [];
    }),
    invalidation: (Array.isArray(v.invalidation) ? v.invalidation : []).flatMap((x): RegimeFlip[] => {
      const r = rec(x);
      const level = num(r.level);
      if (!isOneOf(FLIP_INPUTS, r.input) || !isOneOf(FLIP_CONDITIONS, r.condition) || level == null || !isOneOf(DESK_REGIME_KEYS, r.then)) return [];
      return [{ input: r.input, condition: r.condition, level, then: r.then }];
    }),
    reason: str(v.reason),
  };
}

export type MacroToday =
  | {
      kind: "ready";
      regime: Regime;
      /** The desk's five-regime reading; null when the route sent none (an older backend). */
      desk: DeskRegime | null;
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
    desk: readDeskRegime(d.regime),
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

/** GET /api/positional/market-dashboard — the sector heatmap (the desk reads its leaders). */
export function useSectorStrength() {
  return useQuery<SectorStrength>({
    queryKey: ["copilot", "desk", "market-dashboard"],
    staleTime: 60_000,
    refetchInterval: 5 * 60_000,
    retry: noRetry4xx,
    queryFn: ({ signal }) => fetchSectors(signal),
  });
}

// ── sector returns (GET /api/markets/sector-returns) ─────────────────────

export const SECTOR_PERIODS = ["1d", "1w", "1m"] as const;
export type SectorPeriodKey = (typeof SECTOR_PERIODS)[number];

export interface SectorReturn {
  /** The NSE index ("Nifty Bank"). */
  index: string;
  /** The sector it stands for ("Banks"); the index name when the row has none. */
  sector: string;
  close: number | null;
  /** That index's own latest close day (it can trail the response's as-of). */
  date: string | null;
  /** Percent; null when that index's history is too short for the period. */
  ret: Record<SectorPeriodKey, number | null>;
}

/** Advances / declines among one sector index's constituents on that index's latest close day. */
export interface SectorBreadth {
  listDate: string | null;
  date: string | null;
  members: number;
  advances: number;
  declines: number;
  unchanged: number;
  /** Constituents with no bar that day: never counted as unchanged. */
  noPrice: number;
}

export interface SectorReturns {
  asOf: string | null;
  source: string | null;
  /** Sessions each period spans, as the route states them (1, 5, 21). */
  sessions: Record<SectorPeriodKey, number | null>;
  sectors: SectorReturn[];
  /** Breadth within each index that has a constituent list, by index name; absent = no list on record. */
  inSector: { source: string | null; rule: string | null; byIndex: Map<string, SectorBreadth> } | null;
}

function readSectorBreadth(v: unknown): SectorBreadth | null {
  const r = rec(v);
  const members = num(r.members);
  const adv = num(r.advances);
  const dec = num(r.declines);
  if (members == null || adv == null || dec == null) return null;
  return { listDate: str(r.list_date), date: str(r.date), members, advances: adv, declines: dec, unchanged: num(r.unchanged) ?? 0, noPrice: num(r.no_price) ?? 0 };
}

async function fetchSectorReturns(signal?: AbortSignal): Promise<SectorReturns> {
  const res = await http({ path: "/api/markets/sector-returns", signal });
  const d = rec(res.data);
  if (!Array.isArray(d.sectors)) throw drift("markets.sector-returns: no sectors list");
  const sectors: SectorReturn[] = d.sectors.flatMap((v): SectorReturn[] => {
    const r = rec(v);
    const index = str(r.index);
    const sector = str(r.sector) ?? index;
    if (!index || !sector) return [];
    return [{ index, sector, close: num(r.close), date: str(r.date), ret: { "1d": num(r.ret_1d_pct), "1w": num(r.ret_1w_pct), "1m": num(r.ret_1m_pct) } }];
  });
  const s = rec(d.sessions);
  let inSector: SectorReturns["inSector"] = null;
  if (isRec(d.in_sector_breadth)) {
    const b = d.in_sector_breadth;
    const byIndex = new Map<string, SectorBreadth>();
    for (const [name, v] of Object.entries(rec(b.indices))) {
      const sb = readSectorBreadth(v);
      if (sb) byIndex.set(name, sb);
    }
    inSector = { source: str(b.source), rule: str(b.rule), byIndex };
  }
  return {
    asOf: str(d.as_of),
    source: str(d.source),
    sessions: { "1d": num(s["1d"]), "1w": num(s["1w"]), "1m": num(s["1m"]) },
    sectors,
    inSector,
  };
}

/** GET /api/markets/sector-returns — end of day, so it changes once a session. */
export function useSectorReturns() {
  return useQuery<SectorReturns>({
    queryKey: ["copilot", "desk", "sector-returns"],
    staleTime: 10 * 60_000,
    retry: noRetry4xx,
    queryFn: ({ signal }) => fetchSectorReturns(signal),
  });
}

// ── one sector's constituents (GET /api/markets/sector-constituents) ─────

export interface Constituent {
  symbol: string;
  name: string | null;
  close: number | null;
  changePct: number | null;
  move: "advance" | "decline" | "unchanged" | null;
}

export type SectorConstituents =
  | { kind: "ready"; index: string; listDate: string | null; date: string | null; source: string | null; rule: string | null; breadth: SectorBreadth | null; rows: Constituent[] }
  /** The route answered `available: false` (no list on record, or not a desk sector index), with its reason. */
  | { kind: "unavailable"; index: string; reason: string | null; source: string | null };

async function fetchConstituents(index: string, signal?: AbortSignal): Promise<SectorConstituents> {
  const res = await http({ path: "/api/markets/sector-constituents", query: { index }, signal });
  const d = rec(res.data);
  if (!Array.isArray(d.rows)) throw drift("markets.sector-constituents: no rows list");
  if (d.available !== true) return { kind: "unavailable", index: str(d.index) ?? index, reason: str(d.reason), source: str(d.source) };
  const rows = d.rows.flatMap((v): Constituent[] => {
    const r = rec(v);
    const symbol = str(r.symbol);
    if (!symbol) return [];
    const move = str(r.move);
    return [{
      symbol: symbol.toUpperCase(),
      name: str(r.company_name),
      close: num(r.close),
      changePct: num(r.change_pct),
      move: move === "advance" || move === "decline" || move === "unchanged" ? move : null,
    }];
  });
  const b = rec(d.breadth);
  return {
    kind: "ready",
    index: str(d.index) ?? index,
    listDate: str(d.list_date),
    date: str(d.date),
    source: str(d.source),
    rule: str(d.rule),
    breadth: readSectorBreadth({ ...b, list_date: d.list_date, date: d.date }),
    rows,
  };
}

/** GET /api/markets/sector-constituents?index= — fetched when a sector is opened. */
export function useSectorConstituents(index: string | null) {
  return useQuery<SectorConstituents>({
    queryKey: ["copilot", "desk", "sector-constituents", index],
    enabled: !!index,
    staleTime: 10 * 60_000,
    retry: noRetry4xx,
    queryFn: ({ signal }) => fetchConstituents(index ?? "", signal),
  });
}

/** "Oil & Gas" and "oil gas" → "oilgas": sector names compared without case, spaces or punctuation. */
export const sectorKey = (name: string) => name.toLowerCase().replace(/[^a-z0-9]/g, "");

/**
 * The market dashboard's 5-session leader for a sector-index row: only when the
 * dashboard's sector name equals the row's sector, or its index name without
 * "Nifty" (IT = Nifty IT). No partial match: "Bank" must not lend its leader to
 * "PSU Bank".
 */
export function leaderFor(row: SectorReturn, tiles: SectorTile[]): SectorTile["leader"] {
  const keys = new Set([sectorKey(row.sector), sectorKey(row.index.replace(/^nifty\s+/i, ""))]);
  return tiles.find((t) => t.leader && keys.has(sectorKey(t.sector)))?.leader ?? null;
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
 * Which stocks the breadth counts cover, as the route names them in
 * `breadth.universe_kind` beside the count in `breadth.universe`: "bhavcopy" =
 * every NSE stock in the end-of-day file, "nifty50_live" = the live fallback
 * over the Nifty 50 constituents. No kind, or one this screen does not know, is
 * "unnamed": the count is shown and nothing is guessed from its size.
 */
export type BreadthScope = "eod" | "nifty50" | "unnamed";

export interface BreadthRead {
  advances: number;
  declines: number;
  unchanged: number | null;
  /** advances + declines + unchanged. */
  total: number;
  /** advances ÷ total × 100. */
  advancingPct: number;
  /** Stocks counted, as the route states it; null when it sent none. */
  universe: number | null;
  scope: BreadthScope;
}


export function readBreadth(b: MarketBreadth): BreadthRead | null {
  if (b.advances == null || b.declines == null) return null;
  const unchanged = b.unchanged ?? null;
  const total = b.advances + b.declines + (unchanged ?? 0);
  if (total <= 0) return null;
  const count = num(b.universe);
  const k = str(b.universe_kind)?.toLowerCase() ?? null;
  const scope: BreadthScope = k === "bhavcopy" ? "eod" : k === "nifty50_live" ? "nifty50" : "unnamed";
  return {
    advances: b.advances,
    declines: b.declines,
    unchanged,
    total,
    advancingPct: (b.advances / total) * 100,
    universe: count,
    scope,
  };
}


// ── IST clock and market status ──────────────────────────────────────────

const IST = "Asia/Kolkata";

export interface IstParts {
  /** "Wed" */
  weekday: string;
  /** "14 Oct" */
  day: string;
  /** "11:32" (24-hour) */
  time: string;
  /** "2026-10-14" — the IST calendar day. */
  iso: string;
  /** Minutes since IST midnight. */
  minutes: number;
  /** 0 = Sunday … 6 = Saturday, in IST. */
  dow: number;
}

const WEEKDAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

/** The IST calendar day and time of a moment. */
export function istParts(at: Date): IstParts {
  const f = new Intl.DateTimeFormat("en-GB", {
    timeZone: IST, year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hourCycle: "h23", weekday: "short",
  });
  const p: Record<string, string> = {};
  for (const x of f.formatToParts(at)) p[x.type] = x.value;
  const iso = `${p.year}-${p.month}-${p.day}`;
  const hh = Number(p.hour) % 24;
  const mm = Number(p.minute);
  const day = new Date(`${iso}T00:00:00Z`).toLocaleDateString("en-IN", { day: "numeric", month: "short", timeZone: "UTC" });
  const dow = WEEKDAYS.indexOf(p.weekday ?? "");
  return { weekday: p.weekday ?? "", day, time: `${String(hh).padStart(2, "0")}:${String(mm).padStart(2, "0")}`, iso, minutes: hh * 60 + mm, dow };
}

/** The IST calendar day of a response date: a bare "2026-10-13" as it is, a date-time in IST. */
export function istDay(iso: string | null | undefined): string | null {
  if (!iso) return null;
  if (/^\d{4}-\d{2}-\d{2}$/.test(iso)) return iso;
  const t = new Date(iso);
  return Number.isFinite(t.getTime()) ? istParts(t).iso : null;
}

/** The current time, refreshed every 30 seconds (the status pill shows minutes). */
export function useNow(intervalMs = 30_000): Date {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const id = window.setInterval(() => setNow(new Date()), intervalMs);
    return () => window.clearInterval(id);
  }, [intervalMs]);
  return now;
}

/** NSE cash-market hours by the clock: Monday to Friday, 09:15–15:30 IST (used only until the route answers). */
export function inNseHours(p: IstParts): boolean {
  return p.dow >= 1 && p.dow <= 5 && p.minutes >= 9 * 60 + 15 && p.minutes <= 15 * 60 + 30;
}

export interface MarketStatus {
  /** "Market open" (holiday list checked), "NSE hours" (clock only), "NSE holiday", "Market closed". */
  label: string;
  /** "live" = the route's live tape; "delayed" = in hours, delayed quotes; "closed"; "clock" = no response, read from the clock. */
  feed: "live" | "delayed" | "closed" | "clock";
  open: boolean;
  /** The holiday's name on an NSE holiday. */
  holiday: string | null;
  /** True when the NSE holiday list was read for today. */
  calendarChecked: boolean;
  /** Tooltip: where the status comes from. */
  why: string;
}

/**
 * The session state. GET /api/markets/home sends `market_state`, `is_live` and
 * `session`: NSE hours by the IST clock AND the NSE holiday list (routes/markets.py
 * session_state). "Market open" is said only when the holiday list was read;
 * with the list unread, or from an older backend without `session`, the pill
 * says "NSE hours" (the clock's word), never "market open", and never "live"
 * for delayed or end-of-day figures. Before the route answers, or when it
 * fails, the clock rule is read from this device.
 */
export function marketStatus(home: MarketsHome | undefined, now: IstParts): MarketStatus {
  if (home) {
    const open = home.market_state === "open";
    const s = home.session ?? null;
    const checked = s?.calendar === "ok";
    const unread = s ? "The NSE holiday list could not be read, so the status follows the clock." : "Exchange holidays are not checked by this server.";
    if (!open) {
      if (s?.reason === "holiday") {
        return { label: "NSE holiday", feed: "closed", open, holiday: s.holiday ?? null, calendarChecked: true, why: `NSE holiday${s.holiday ? `: ${s.holiday}` : ""} (NSE holiday list, GET /api/markets/home)` };
      }
      const when = s?.reason === "weekend" ? "Weekend" : "Outside NSE hours (Mon–Fri 09:15–15:30 IST)";
      return { label: "Market closed", feed: "closed", open, holiday: null, calendarChecked: checked, why: `${when}, per GET /api/markets/home${checked ? "" : `. ${unread}`}` };
    }
    const label = checked ? "Market open" : "NSE hours";
    const tail = checked ? "Today is not an NSE holiday (NSE holiday list)." : unread;
    return home.is_live
      ? { label, feed: "live", open, holiday: null, calendarChecked: checked, why: `Inside NSE hours; the index tape is the live feed (GET /api/markets/home). ${tail}` }
      : { label, feed: "delayed", open, holiday: null, calendarChecked: checked, why: `Inside NSE hours; quotes are delayed (GET /api/markets/home). ${tail}` };
  }
  const open = inNseHours(now);
  return {
    label: open ? "NSE hours" : "Market closed",
    feed: "clock",
    open,
    holiday: null,
    calendarChecked: false,
    why: "Read from this device’s clock: NSE hours are Mon–Fri 09:15–15:30 IST. Exchange holidays are not checked.",
  };
}

// ── "Data as of": one place that dates every feed on the Overview ────────

export interface FeedAsOf {
  key: "tape" | "breadth" | "flows" | "regime";
  label: string;
  /** What the feed's own field says, e.g. "End of day · 14 Oct, 15:45 IST" or "session 2026-10-14"; null when it says nothing. */
  value: string | null;
  /** The ISO day of the feed's data when it is a session figure, else null. */
  day: string | null;
  /** Why value is "—". */
  why: string | null;
}

export interface DataAsOf {
  /** "Wed 14 Oct, 11:32 IST": this device's clock, which is not a data date. */
  clock: string;
  /** "Market closed", "NSE holiday: Diwali" ... from GET /api/markets/home `session`. */
  state: string;
  /** The last session that has completed, from the breadth's end-of-day bhavcopy; null when the response does not give one. */
  lastSession: string | null;
  lastSessionWhy: string | null;
  /** True when the last completed session is before today's IST day (a holiday, weekend or before the day's file). */
  notToday: boolean;
  feeds: FeedAsOf[];
}

/**
 * The Overview's dating, from the routes' own fields and nothing else (PRD 4.1 issue 1, 6.1, 7). The last completed
 * session is the end-of-day breadth's day (`as_of` when the breadth counts the NSE bhavcopy, which exists only for a
 * finished session). With the live Nifty 50 fallback, or no breadth, no completed-session date is in the response, so
 * none is shown and the reason says why. Nothing here counts back over a holiday list.
 */
export function dataAsOf(home: MarketsHome | undefined, macro: MacroToday | undefined, now: IstParts, status: MarketStatus): DataAsOf {
  const clock = `${now.weekday} ${now.day}, ${now.time} IST`;
  const state = status.holiday ? `NSE holiday: ${status.holiday}` : status.label;
  const b = home ? readBreadth(home.breadth) : null;
  const homeDay = istDay(home?.as_of);
  const feeds: FeedAsOf[] = [];
  const tapeStamp = home ? stampIst(home.fetched_at ?? home.as_of) : null;
  feeds.push(home
    ? { key: "tape", label: "Index tape", value: `${indexMode(home) === "live" ? "Live" : indexMode(home) === "delayed" ? "Delayed" : "End of day"}${tapeStamp ? ` · ${tapeStamp}` : ""}`, day: null, why: tapeStamp ? null : "The response carries no timestamp for the tape." }
    : { key: "tape", label: "Index tape", value: null, day: null, why: "The market overview has not loaded." });
  let lastSession: string | null = null;
  let lastSessionWhy: string | null = null;
  if (!home) {
    feeds.push({ key: "breadth", label: "Breadth", value: null, day: null, why: "The market overview has not loaded." });
    lastSessionWhy = "The market overview has not loaded.";
  } else if (!b) {
    feeds.push({ key: "breadth", label: "Breadth", value: null, day: null, why: "The response carries no advances and declines." });
    lastSessionWhy = "The response carries no breadth, which is the source of the session date.";
  } else if (b.scope === "eod") {
    lastSession = homeDay;
    lastSessionWhy = homeDay ? null : "The breadth is end of day, but the response gives no date for it.";
    feeds.push({ key: "breadth", label: "Breadth", value: homeDay ? `End of day · session ${homeDay}` : null, day: homeDay, why: homeDay ? null : "The response gives no date for the breadth." });
  } else {
    const stamp = stampIst(home.fetched_at);
    feeds.push({ key: "breadth", label: "Breadth", value: `Delayed Nifty 50 quotes${stamp ? ` · ${stamp}` : ""}`, day: null, why: stamp ? null : "The response carries no timestamp for it." });
    lastSessionWhy = b.scope === "nifty50"
      ? "Breadth is the live Nifty 50 fallback, which names no completed session."
      : "The response does not say which stocks the breadth counted, so it names no session.";
  }
  const f = home?.fii_dii ?? null;
  feeds.push(f?.as_of
    ? { key: "flows", label: "FII / DII", value: `End of day · session ${istDay(f.as_of) ?? f.as_of}`, day: istDay(f.as_of), why: null }
    : { key: "flows", label: "FII / DII", value: null, day: null, why: home ? "The response carries no FII / DII row." : "The market overview has not loaded." });
  if (macro?.kind === "ready") {
    const day = istDay(macro.desk?.date ?? macro.date);
    feeds.push({
      key: "regime", label: "Regime",
      value: day ? `End of day · session ${day}${macro.daysStale != null && macro.daysStale > 0 ? ` (${macro.daysStale} ${macro.daysStale === 1 ? "day" : "days"} old)` : ""}` : null,
      day, why: day ? null : "The regime response carries no date.",
    });
  } else {
    feeds.push({ key: "regime", label: "Regime", value: null, day: null, why: macro?.kind === "unavailable" ? macro.reason ?? "The macro engine has not produced a regime yet." : "The regime has not loaded." });
  }
  return { clock, state, lastSession, lastSessionWhy, notToday: lastSession != null && lastSession < now.iso, feeds };
}

/** The pill's data-feed words for the index tape: live only when the route says so. */
export function feedWords(s: MarketStatus): string {
  if (s.feed === "live") return "live";
  if (s.feed === "delayed") return "delayed";
  return s.open ? "delayed" : "end of day";
}

// ── the Overview headline (design: H1 with one phrase in mint) ───────────

export interface Headline {
  lead: string;
  emph: string | null;
  tail: string;
}

/** Breadth bands by the share of advancing stocks, strongest first. */
const BANDS = [60, 52, 48, 40] as const;
function band(advancingPct: number): number {
  const i = BANDS.findIndex((b) => advancingPct >= b);
  return i === -1 ? BANDS.length : i;
}

const TRADER_BREADTH = ["strong", "positive", "even", "soft", "weak"];
const INVESTOR_NOW = [
  "Most stocks are rising today",
  "More stocks are rising than falling today",
  "About as many stocks are rising as falling today",
  "More stocks are falling than rising today",
  "Most stocks are falling today",
];
const INVESTOR_PAST = [
  "Most stocks rose",
  "More stocks rose than fell",
  "About as many stocks rose as fell",
  "More stocks fell than rose",
  "Most stocks fell",
];

/**
 * The Overview's headline, from real reads only:
 *   breadth   advancing share (GET /api/markets/home), on its session day — "today" only when that day is today in IST
 *   sector    the strongest sector index over 1 day (GET /api/markets/sector-returns); "no sector index rose" when none did
 *   setups    confirmed of all scanner setups (GET /api/positional/watchlist + picks)
 * A part with no data is left out. With nothing at all it is a plain title.
 */
export function deskHeadline(input: {
  persona: DeskPersona;
  advancingPct: number | null;
  /** The session the breadth counts are for (YYYY-MM-DD, IST). */
  breadthDay: string | null;
  todayIso: string;
  /** The strongest sector over 1 day and its return (percent); null when the read has none. */
  topSector: { name: string; pct: number } | null;
  setups: { confirmed: number; total: number } | null;
}): Headline {
  const { persona, advancingPct, breadthDay, todayIso, topSector, setups } = input;
  const investor = persona === "investor";
  let lead = "";
  if (advancingPct != null) {
    const b = band(advancingPct);
    const today = breadthDay === todayIso;
    const on = !today && breadthDay ? ` on ${new Date(`${breadthDay}T00:00:00Z`).toLocaleDateString("en-IN", { day: "numeric", month: "short", timeZone: "UTC" })}` : "";
    let sector = "";
    if (topSector) {
      if (topSector.pct > 0) sector = investor ? `, led by ${topSector.name}` : ` and ${topSector.name} ${today ? "leads" : "led"}`;
      else sector = investor ? `, and no sector ${today ? "is up" : "rose"}` : `, and no sector index ${today ? "is up" : "rose"}`;
    }
    const first = investor
      ? (today ? INVESTOR_NOW[b] : `${INVESTOR_PAST[b]}${on}`)
      : `Breadth ${today ? "is" : "was"} ${TRADER_BREADTH[b]}${today ? "" : on}`;
    lead = `${first}${sector}.`;
  }
  if (setups && setups.total > 0) {
    const c = setups.confirmed;
    const space = lead ? " " : "";
    if (investor) {
      if (c === 0) return { lead: `${lead}${space}`, emph: "No ideas", tail: " have confirmed yet." };
      return { lead: `${lead}${space}`, emph: `${c} ${c === 1 ? "idea" : "ideas"}`, tail: ` ${c === 1 ? "has" : "have"} confirmed, each with its evidence shown.` };
    }
    return { lead: `${lead}${space}`, emph: `${c} of ${setups.total} setups`, tail: ` ${c === 1 ? "has" : "have"} confirmed.` };
  }
  if (lead) return { lead, emph: null, tail: "" };
  return { lead: "Your smart ", emph: "trading desk", tail: "." };
}

// ── the setup lifecycle behind "N of M setups have confirmed" (PRD 4.1 issue 2) ──

export interface SetupLifecycle {
  /** "End-of-day scan · 13 Oct 2026": the timeframe the counts are for. */
  scope: string;
  /** The rules version the scanner routes name ("smart_v2" classifier, rules version), or null when none is sent. */
  rules: string | null;
  /** Stocks in the eligible universe on the scan-universe route's day; null with the reason in `universeWhy`. */
  eligible: number | null;
  universeDay: string | null;
  universeWhy: string | null;
  confirmed: number;
  awaiting: number;
  forming: number;
  total: number;
  /** The scanner sends no invalidated or expired state, so it is said and not counted as zero. */
  untracked: string;
}

/**
 * The counts behind the headline, from the scanner's own statuses and the scan-universe route. Setups are the
 * deduplicated stocks of the watchlist and picks routes; each is confirmed (breakout happened), awaiting (near
 * breakout or pullback) or forming (accumulation). Invalidated and expired setups are not sent by the scanner, so
 * they are not counted.
 */
export function setupLifecycle(scan: DeskScanner | undefined, universe: ScanUniverse | undefined, universeWhy: string | null): SetupLifecycle | null {
  if (!scan || scan.setups.length === 0) return null;
  const n = (st: DeskSetup["status"]) => scan.setups.filter((x) => x.status === st).length;
  const date = scanDateLabel(scan.watchAsOf, scan.signalDate);
  const versions = [scan.classifierVersion, scan.rulesVersion ?? scan.rules?.version].filter((v): v is string => !!v);
  return {
    scope: `End-of-day scan${date ? ` · ${date}` : " · date not in the response"}`,
    rules: versions.length ? [...new Set(versions)].join(" · ") : null,
    eligible: universe ? universe.universe.eligible : null,
    universeDay: universe?.asOf ?? null,
    universeWhy: universe ? null : universeWhy ?? "The eligible universe did not load.",
    confirmed: n("confirmed"), awaiting: n("awaiting"), forming: n("forming"), total: scan.setups.length,
    untracked: "Invalidated and expired setups are not tracked yet: the scanner does not send them.",
  };
}

// ── the scanner's picks with the live overlay (GET /api/positional/picks/mine?live=true) ──

/** One pick's live read: a delayed price, where it stands against the plan, and what the conviction check holds against it. */
export interface LivePick {
  symbol: string;
  /** Delayed last price (Yahoo Finance via the route); null when the route could not fetch one. */
  livePrice: number | null;
  /** Percent from the plan's entry. */
  fromEntryPct: number | null;
  /** LATE | TRIGGERED | NEAR | WAIT | FAR | STOPPED | UNKNOWN (routes/positional.py _readiness). */
  readiness: string | null;
  /** HIGH_CONVICTION | SETUP_FORMING | AVOID_LATE (positional_engine/conviction.py). */
  verdict: string | null;
  /** The conviction check's penalties: RSI overbought, already past entry, a 5-session spike, … */
  against: string[];
  /** Overlap with the caller's own holdings (portfolio_filter). */
  portfolioWarnings: string[];
}

export interface PicksLive {
  signalDate: string | null;
  /** When this browser received the answer (the route sends no time for its live prices). */
  receivedAt: number;
  bySymbol: Map<string, LivePick>;
}

/** Drop the route's leading "⚠ " and trailing "(−15)" points: the words only. */
const cleanReason = (t: string) => t.replace(/^⚠\s*/, "").replace(/\s*\([+−-]?\d+\)\s*$/, "").trim();

async function fetchPicksLive(signal?: AbortSignal): Promise<PicksLive> {
  // yfinance can take several seconds on a cold cache (the route caps it at 8s).
  const res = await http({ path: "/api/positional/picks/mine", query: { live: "true", limit: 30 }, timeoutMs: 30_000, signal });
  const d = rec(res.data);
  if (!Array.isArray(d.picks)) throw drift("positional.picks/mine: no picks list");
  const bySymbol = new Map<string, LivePick>();
  for (const v of d.picks) {
    const p = rec(v);
    const symbol = str(p.nse_symbol)?.toUpperCase();
    if (!symbol) continue;
    const c = rec(p.conviction);
    const penalties = Array.isArray(c.penalties) ? c.penalties : [];
    const live = num(p.live_price);
    bySymbol.set(symbol, {
      symbol,
      livePrice: live != null && live > 0 ? live : null,
      fromEntryPct: num(p.live_pct_from_entry),
      readiness: str(p.readiness)?.toUpperCase() ?? null,
      verdict: str(c.verdict)?.toUpperCase() ?? null,
      against: penalties.flatMap((x) => {
        const reason = str(rec(x).reason);
        return reason ? [cleanReason(reason)] : [];
      }),
      portfolioWarnings: (Array.isArray(p.portfolio_warning) ? p.portfolio_warning : []).flatMap((x) => (typeof x === "string" && x.trim() ? [x.trim()] : [])),
    });
  }
  return { signalDate: str(d.signal_date), receivedAt: Date.now(), bySymbol };
}

/** GET /api/positional/picks/mine?live=true — refreshed every two minutes (its prices are delayed quotes). */
export function usePicksLive() {
  return useQuery<PicksLive>({
    queryKey: ["copilot", "desk", "picks-mine-live"],
    staleTime: 60_000,
    refetchInterval: 2 * 60_000,
    retry: noRetry4xx,
    queryFn: ({ signal }) => fetchPicksLive(signal),
  });
}

/** Readiness words: what the live price says about the plan (routes/positional.py _readiness). */
export const READINESS_WORDS: Record<string, { text: string; against: boolean }> = {
  LATE: { text: "already more than 8% past the entry", against: true },
  STOPPED: { text: "at or below the stop", against: true },
  TRIGGERED: { text: "crossed the entry", against: false },
  NEAR: { text: "within 2% of the entry", against: false },
  WAIT: { text: "2–5% below the entry", against: false },
  FAR: { text: "more than 5% below the entry", against: true },
};

// ── risk class (the user's default of 2026-10-14) ───────────────────────

/** Risk class from ATR(14) as a percent of the close: Low under 2%, Medium 2–4%, High over 4%. One config; cards show it. */
export const RISK_ATR_BANDS = { lowBelowPct: 2, highAbovePct: 4 } as const;
export type RiskClass = "low" | "medium" | "high";
export const RISK_CLASS_LABEL: Record<RiskClass, string> = { low: "Low", medium: "Medium", high: "High" };

export function riskClass(atrPct: number | null): RiskClass | null {
  if (atrPct == null || !Number.isFinite(atrPct) || atrPct < 0) return null;
  if (atrPct < RISK_ATR_BANDS.lowBelowPct) return "low";
  if (atrPct > RISK_ATR_BANDS.highAbovePct) return "high";
  return "medium";
}

export const RISK_BANDS_TEXT = `ATR(14) % of the close: Low < ${RISK_ATR_BANDS.lowBelowPct}%, Medium ${RISK_ATR_BANDS.lowBelowPct}–${RISK_ATR_BANDS.highAbovePct}%, High > ${RISK_ATR_BANDS.highAbovePct}%`;

// ── key market events (from the Market Intelligence feed) ───────────────

const IMPACT_RANK: Record<string, number> = { high: 0, medium: 1, low: 2 };
const impactRank = (e: IntelEvent) => IMPACT_RANK[(e.impact ?? "").toLowerCase()] ?? 3;
const timeOf = (e: IntelEvent) => (Number.isFinite(e.sortAt) ? e.sortAt : -8.64e15);

/** How many filings the Overview takes, ranked by the classifier's impact, then newest. */
export const KEY_FILINGS = 3;

/**
 * The Overview's key events from Market Intelligence · All (same reads, same cache):
 * the three highest-impact filings (newest first within an impact level), the
 * newest of the five largest bulk or block deals (All takes the five largest),
 * the latest SEBI circular and the latest FII / DII session — then newest first.
 * A source with nothing to give is skipped.
 */
export function keyEvents(events: IntelEvent[]): IntelEvent[] {
  const filings = events.filter((e) => e.filing).sort((a, b) => impactRank(a) - impactRank(b) || timeOf(b) - timeOf(a)).slice(0, KEY_FILINGS);
  const deal = events.find((e) => e.group === "deals" && !e.filing) ?? null;
  const circular = events.filter((e) => e.group === "regulatory" && !e.filing).sort((a, b) => timeOf(b) - timeOf(a))[0] ?? null;
  const flow = events.filter((e) => e.group === "flows").sort((a, b) => timeOf(b) - timeOf(a))[0] ?? null;
  return [...filings, ...[deal, circular, flow].filter((e): e is IntelEvent => e != null)].sort((a, b) => timeOf(b) - timeOf(a));
}

// ── portfolio snapshot (GET /api/portfolio/holdings-enriched) ───────────

export const ASSET_LABEL: Record<string, string> = {
  equity: "Stocks", stock: "Stocks", mutual_fund: "Mutual funds", etf: "ETFs", bond: "Bonds", gold: "Gold", fd: "Fixed deposits", other: "Other",
};

export interface AllocationSlice {
  key: string;
  label: string;
  valueRs: number;
  /** Share of the holdings' summed value, percent. */
  pct: number;
}

/** Value by asset type, largest first; shares of the summed value of the holdings that have one. null with no values. */
export function allocationOf(d: EnrichedHoldingsRes): { slices: AllocationSlice[]; totalRs: number; unvalued: number } | null {
  const by = new Map<string, number>();
  let unvalued = 0;
  for (const h of d.holdings) {
    const v = num(h.value_rs);
    if (v == null || v < 0) {
      unvalued += 1;
      continue;
    }
    const t = h.asset_type.trim().toLowerCase();
    const key = t === "stock" ? "equity" : ASSET_LABEL[t] ? t : "other";
    by.set(key, (by.get(key) ?? 0) + v);
  }
  const totalRs = [...by.values()].reduce((a, b) => a + b, 0);
  if (totalRs <= 0) return null;
  const slices = [...by.entries()]
    .map(([key, valueRs]) => ({ key, label: ASSET_LABEL[key] ?? "Other", valueRs, pct: (valueRs / totalRs) * 100 }))
    .sort((a, b) => b.valueRs - a.valueRs);
  return { slices, totalRs, unvalued };
}

export interface TopHolding {
  id: string;
  name: string;
  symbol: string | null;
  assetType: string;
  valueRs: number;
  /** The route's share of the whole portfolio, percent. */
  weightPct: number | null;
  pnlPct: number | null;
}

/** The largest holdings of any type by value. */
export function topHoldings(d: EnrichedHoldingsRes, n = 5): TopHolding[] {
  return d.holdings
    .flatMap((h): TopHolding[] => {
      const v = num(h.value_rs);
      return v == null ? [] : [{ id: h.holding_id, name: h.name, symbol: str(h.nse_symbol), assetType: h.asset_type.trim().toLowerCase(), valueRs: v, weightPct: num(h.weight_pct), pnlPct: num(h.pnl_pct) }];
    })
    .sort((a, b) => b.valueRs - a.valueRs)
    .slice(0, n);
}

// ── index card stamps (OV-001: every card says when and how fresh) ──────

export type IndexMode = "live" | "delayed" | "eod";

/** Live only when the route says the tape is live; in hours otherwise delayed; after the close end of day. */
export function indexMode(home: MarketsHome): IndexMode {
  if (home.is_live && home.market_state === "open") return "live";
  return home.market_state === "open" ? "delayed" : "eod";
}

/** "14 Oct, 11:32 IST" for a time stamp in IST; the bare day for a date. */
export function stampIst(iso: string | null | undefined): string | null {
  if (!iso) return null;
  if (/^\d{4}-\d{2}-\d{2}$/.test(iso)) {
    return new Date(`${iso}T00:00:00Z`).toLocaleDateString("en-IN", { day: "numeric", month: "short", timeZone: "UTC" });
  }
  const t = new Date(iso);
  if (!Number.isFinite(t.getTime())) return null;
  const p = istParts(t);
  return `${p.day}, ${p.time} IST`;
}
