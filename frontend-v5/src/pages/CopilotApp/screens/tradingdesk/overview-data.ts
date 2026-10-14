/**
 * Smart trading desk · Overview — the reads the Overview tab needs that had no
 * hook yet, and the small derivations it shows.
 *
 *   GET /api/macro/today                    the macro regime: `market` BULL / NEUTRAL / BEAR is the Nifty 50
 *                                           against its 50-day average (services/macro_engine.py), plus `risk`
 *                                           and the engine's own `insight` line
 *   GET /api/markets/sector-returns         NSE sectoral indices' end-of-day close and their 1-day, 1-week and
 *                                           1-month returns (close vs the close N sessions earlier for that index;
 *                                           DaaS nidp.index_eod), with the route's own source and as-of date
 *   GET /api/positional/market-dashboard    `sector_heatmap` leaders only: each sector's best 5-session stock from
 *                                           end-of-day bars (positional_engine/market_dashboard.py), shown on a
 *                                           sector-index tile when the two sector names match exactly
 *
 * GET /api/markets/home (index tape, breadth and the universe it counted, FII /
 * DII, USD / INR, Brent, the deploy verdict, `market_state` and `is_live`) is
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
import type { DeskPersona } from "./context";
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

export interface SectorReturns {
  asOf: string | null;
  source: string | null;
  /** Sessions each period spans, as the route states them (1, 5, 21). */
  sessions: Record<SectorPeriodKey, number | null>;
  sectors: SectorReturn[];
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
  return {
    asOf: str(d.as_of),
    source: str(d.source),
    sessions: { "1d": num(s["1d"]), "1w": num(s["1w"]), "1m": num(s["1m"]) },
    sectors,
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

/** NSE cash-market hours by the clock: Monday to Friday, 09:15–15:30 IST (exchange holidays are not known here). */
export function inNseHours(p: IstParts): boolean {
  return p.dow >= 1 && p.dow <= 5 && p.minutes >= 9 * 60 + 15 && p.minutes <= 15 * 60 + 30;
}

export interface MarketStatus {
  /** "NSE hours" inside the session window, else "Market closed". */
  label: string;
  /** "live" = the route's live tape; "delayed" = in hours, delayed quotes; "closed"; "clock" = no response, read from the clock. */
  feed: "live" | "delayed" | "closed" | "clock";
  open: boolean;
  /** Tooltip: where the status comes from. */
  why: string;
}

/**
 * The session state. GET /api/markets/home sends `market_state` (open / closed)
 * and `is_live`; both follow NSE hours by the IST clock on the server
 * (nse_live._is_market_open_ist) and do not know exchange holidays, so the pill
 * says "NSE hours", never "market open", and never "live" for delayed or
 * end-of-day figures. Before the route answers, or when it fails, the same rule
 * is read from this device's clock.
 */
export function marketStatus(home: MarketsHome | undefined, now: IstParts): MarketStatus {
  if (home) {
    const open = home.market_state === "open";
    if (!open) return { label: "Market closed", feed: "closed", open, why: "Outside NSE hours (Mon–Fri 09:15–15:30 IST), per GET /api/markets/home" };
    return home.is_live
      ? { label: "NSE hours", feed: "live", open, why: "Inside NSE hours; the index tape is the live feed (GET /api/markets/home). Exchange holidays are not checked." }
      : { label: "NSE hours", feed: "delayed", open, why: "Inside NSE hours; quotes are delayed (GET /api/markets/home). Exchange holidays are not checked." };
  }
  const open = inNseHours(now);
  return {
    label: open ? "NSE hours" : "Market closed",
    feed: "clock",
    open,
    why: "Read from this device’s clock: NSE hours are Mon–Fri 09:15–15:30 IST. Exchange holidays are not checked.",
  };
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
