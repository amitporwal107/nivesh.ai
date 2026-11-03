/**
 * Smart trading desk — shared market reads and helpers: the sector returns, the index tiles and breadth, the IST clock
 * and the market-status pill. It began as the old Overview tab's data module; that tab (OverviewTab.tsx) and the parts
 * only it used (the macro regime card, sector strength and constituents, live picks, the headline, allocation and top
 * holdings) were removed in the desk redesign's step 6 (2026-10-27). Market Overview, Market Intelligence, the results
 * week, the Risk Desk and the desk header still use what is here.
 *
 *   GET /api/markets/sector-returns         NSE sectoral indices' end-of-day close and their 1-day, 1-week and
 *                                           1-month returns (close vs the close N sessions earlier for that index;
 *                                           DaaS nidp.index_eod), with the route's own source and as-of date, and
 *                                           `in_sector_breadth` for the indices with a constituent list
 *
 * GET /api/markets/home (index tape, breadth and the universe it counted, `market_state`, `is_live` and `session` —
 * the NSE session by the IST clock and the NSE holiday list) is read through useMarketOverview
 * (screens/markets/hooks.ts); the helpers here read its payload. The market-status pill is worked out here
 * (marketStatus): no figure is made up.
 *
 * Nothing here trusts the response shape: a missing or non-numeric field is
 * null, never 0, and a body without the field the route always sends throws a
 * contract error.
 */
import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { http } from "@/services/api/http";
import { ApiError } from "@/services/api/errors";
import type { MarketBreadth, MarketIndex, MarketsHome } from "@/services/contracts/markets.contract";
import { num } from "./desk-data";

type Raw = Record<string, unknown>;
const isRec = (v: unknown): v is Raw => !!v && typeof v === "object" && !Array.isArray(v);
const rec = (v: unknown): Raw => (isRec(v) ? v : {});
const str = (v: unknown): string | null => (typeof v === "string" && v.trim() ? v.trim() : null);

const drift = (what: string) => ApiError.contractDrift(what);
const noRetry4xx = (count: number, e: unknown) =>
  !(e instanceof ApiError && (e.kind === "contract_drift" || (e.status != null && e.status >= 400 && e.status < 500))) && count < 1;

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

// ── index tiles and breadth (GET /api/markets/home) ──────────────────────

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
        return { label: "NSE holiday", feed: "closed", open, holiday: s.holiday ?? null, calendarChecked: true, why: `NSE holiday${s.holiday ? `: ${s.holiday}` : ""} (NSE holiday list)` };
      }
      const when = s?.reason === "weekend" ? "Weekend" : "Outside NSE hours (Mon–Fri 09:15–15:30 IST)";
      return { label: "Market closed", feed: "closed", open, holiday: null, calendarChecked: checked, why: `${when}, per the market status${checked ? "" : `. ${unread}`}` };
    }
    const label = checked ? "Market open" : "NSE hours";
    const tail = checked ? "Today is not an NSE holiday (NSE holiday list)." : unread;
    return home.is_live
      ? { label, feed: "live", open, holiday: null, calendarChecked: checked, why: `Inside NSE hours; the index tape is the live feed. ${tail}` }
      : { label, feed: "delayed", open, holiday: null, calendarChecked: checked, why: `Inside NSE hours; quotes are delayed. ${tail}` };
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

// ── index mode and time stamps ───────────────────────────────────────────

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
