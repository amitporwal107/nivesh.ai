/**
 * Trader screens — typed queries for endpoints that had no frontend hook.
 *
 *   GET /api/positional/journal?live=true          the user's logged trades, with a last price when Yahoo answers
 *   GET /api/positional/journal/summary/portfolio  open / closed counts, realised P&L, win rate
 *   GET /api/positional/watchlist?limit=30         four buckets of setups with trigger and stop levels      } one shared read with the
 *   GET /api/positional/picks?limit=30             the scanner's scored signals for the latest signal date } trading desk (useScannerRoutes)
 *   GET /api/broker/accounts                       the user's broker connections (holdings sync only)
 *
 * Paper trades reuse the existing adapter (services/adapters/paperTrades.adapter.ts),
 * which already turns 403 / 404 / empty into explicit results.
 *
 * Nothing here trusts the response shape. Numbers come from Postgres NUMERIC
 * and Mongo floats, so every field is read through num(): a missing or
 * non-numeric value is null, never 0. A body without the field the route always
 * sends (a `{}`, say) is a contract error and throws, so the screen shows an
 * error instead of reporting an empty journal or an empty scanner.
 */
import { useQuery } from "@tanstack/react-query";
import { http } from "@/services/api/http";
import { ApiError } from "@/services/api/errors";
import { useImpersonationStore } from "@/stores/impersonation.store";
import {
  fetchPaperEvaluation, fetchPaperLive, fetchPaperPortfolio,
  type EvaluationResult, type LiveResult, type PaperPortfolio, type PaperSample, type PortfolioResult,
} from "@/services/adapters/paperTrades.adapter";

type Raw = Record<string, unknown>;

const rec = (v: unknown): Raw => (v && typeof v === "object" && !Array.isArray(v) ? (v as Raw) : {});
const arr = (v: unknown): unknown[] => (Array.isArray(v) ? v : []);
const str = (v: unknown): string | null => (typeof v === "string" && v.trim() ? v.trim() : null);

function num(v: unknown): number | null {
  if (typeof v === "number") return Number.isFinite(v) ? v : null;
  if (typeof v === "string" && v.trim() !== "") {
    const n = Number(v);
    return Number.isFinite(n) ? n : null;
  }
  return null;
}

/** A list of strings that may arrive as an array or as a JSON-encoded array (JSONB read without a codec). */
function strList(v: unknown): string[] {
  let raw: unknown = v;
  if (typeof v === "string") {
    try {
      raw = JSON.parse(v);
    } catch {
      return v.trim() ? [v.trim()] : [];
    }
  }
  return arr(raw).filter((x): x is string => typeof x === "string" && x.trim() !== "");
}

export function isForbidden(e: unknown): boolean {
  return e instanceof ApiError && (e.kind === "forbidden" || e.status === 403);
}

/** One retry for transient failures; none when the account has no access or the body is the wrong shape. */
const retry = (count: number, e: unknown) => !isForbidden(e) && !(e instanceof ApiError && e.kind === "contract_drift") && count < 1;

/** The body is not what the route documents. */
const drift = (what: string) => ApiError.contractDrift(what);

// ── trade journal ────────────────────────────────────────────────────────

export interface JournalTrade {
  symbol: string;
  /** "OPEN" | "CLOSED" | "STOPPED" */
  status: string;
  /** "POSITIONAL_PICK" | "MANUAL"; null when the row does not say. */
  planSource: string | null;
  openedAt: string | null;
  closedAt: string | null;
  /** Rupees. null when the user logged no stop / target (the API stores 0). */
  stop: number | null;
  target: number | null;
  /** Last price from the live overlay; null when it was not available. */
  livePrice: number | null;
  qtyIn: number;
  heldQty: number;
  avgBuy: number | null;
  investedRs: number | null;
  /** Rupees; only meaningful when livePrice is present. */
  unrealizedRs: number | null;
  realizedRs: number | null;
  /** Percent units, locked when the trade was closed. */
  realizedPct: number | null;
}


/** A row without a symbol or a status is not a trade this screen can place, so it is dropped rather than guessed at. */
function mapTrade(v: unknown): JournalTrade | null {
  const t = rec(v);
  const symbol = str(t.nse_symbol);
  const status = str(t.status);
  if (!symbol || !status) return null;
  const pnl = rec(t.pnl);
  const positive = (x: unknown) => {
    const n = num(x);
    return n != null && n > 0 ? n : null;
  };
  const livePrice = positive(t.live_price);
  return {
    symbol,
    status: status.toUpperCase(),
    planSource: str(t.plan_source)?.toUpperCase() ?? null,
    openedAt: str(t.opened_at),
    closedAt: str(t.closed_at),
    stop: positive(t.stop_loss),
    target: positive(t.target),
    livePrice,
    qtyIn: num(pnl.qty_in) ?? 0,
    heldQty: num(pnl.held_qty) ?? 0,
    avgBuy: positive(pnl.avg_buy),
    investedRs: num(pnl.invested_rs),
    unrealizedRs: livePrice != null ? num(pnl.unrealized_pnl_rs) : null,
    realizedRs: num(t.realized_pnl_rs) ?? num(pnl.realized_pnl_rs),
    realizedPct: num(t.realized_pnl_pct),
  };
}

export async function fetchTradeJournal(signal?: AbortSignal): Promise<JournalTrade[]> {
  const res = await http({ path: "/api/positional/journal", query: { live: true }, signal });
  const d = rec(res.data);
  if (!Array.isArray(d.trades)) throw drift("positional.journal: no trades list");
  return d.trades.map(mapTrade).filter((t): t is JournalTrade => t != null);
}

export function useTradeJournal() {
  const profile = useImpersonationStore((s) => s.profileId);
  return useQuery<JournalTrade[]>({
    queryKey: ["copilot", "trading", "journal", profile ?? "self"],
    staleTime: 60_000,
    retry,
    queryFn: ({ signal }) => fetchTradeJournal(signal),
  });
}

export interface JournalSummary {
  openCount: number;
  closedCount: number;
  investedRs: number | null;
  realizedRs: number | null;
  winCount: number;
  lossCount: number;
  /** Percent units; null until a trade has closed with a gain or a loss. */
  winRatePct: number | null;
}

export async function fetchJournalSummary(signal?: AbortSignal): Promise<JournalSummary> {
  const res = await http({ path: "/api/positional/journal/summary/portfolio", signal });
  const d = rec(res.data);
  const openCount = num(d.open_count);
  const closedCount = num(d.closed_count);
  if (openCount == null || closedCount == null) throw drift("positional.journal.summary: no trade counts");
  return {
    openCount,
    closedCount,
    investedRs: num(d.invested_rs),
    realizedRs: num(d.realized_pnl_rs),
    winCount: num(d.win_count) ?? 0,
    lossCount: num(d.loss_count) ?? 0,
    winRatePct: num(d.win_rate_pct),
  };
}

export function useJournalSummary() {
  const profile = useImpersonationStore((s) => s.profileId);
  return useQuery<JournalSummary>({
    queryKey: ["copilot", "trading", "journal-summary", profile ?? "self"],
    staleTime: 60_000,
    retry,
    queryFn: ({ signal }) => fetchJournalSummary(signal),
  });
}

/** Rupees between the last price and the logged stop on what is still held. null when either is missing. */
export function riskLeftRs(t: JournalTrade): number | null {
  if (t.livePrice == null || t.stop == null || !(t.heldQty > 0)) return null;
  return Math.max(0, (t.livePrice - t.stop) * t.heldQty);
}

/** Realised P&L as a multiple of the risk taken at entry: (average buy − stop) × quantity bought. */
export function rMultiple(t: JournalTrade): number | null {
  if (t.realizedRs == null || t.avgBuy == null || t.stop == null || !(t.qtyIn > 0)) return null;
  const risk = (t.avgBuy - t.stop) * t.qtyIn;
  return risk > 0 ? t.realizedRs / risk : null;
}

/** Whole days between open and close. */
export function heldDays(t: JournalTrade): number | null {
  if (!t.openedAt || !t.closedAt) return null;
  const ms = new Date(t.closedAt).getTime() - new Date(t.openedAt).getTime();
  return Number.isFinite(ms) && ms >= 0 ? Math.round(ms / 86_400_000) : null;
}

// ── the scanner's two routes, read once ──────────────────────────────────
//
// One fetch and one cache entry for GET /api/positional/watchlist and /picks, shared by the Trader screens
// (useWatchLevels, useScannerPicks) and the Smart trading desk (useDeskScanner, tradingdesk/desk-data.ts). Each screen
// reads its own view through `select`, so the parse stays beside the screen while the network and the cache are one.

/** The bodies as the routes sent them, after the one shape check each route always meets. */
export interface ScannerRoutes {
  /** GET /api/positional/watchlist?limit=30 — has `buckets`; null when the route failed or broke its shape. */
  watch: Record<string, unknown> | null;
  watchError: unknown;
  /** GET /api/positional/picks?limit=30 — has a `picks` list; null when the route failed or broke its shape. */
  picks: Record<string, unknown> | null;
  picksError: unknown;
}

/** Rows asked of each route. The desk shows up to this many; the Trader screens show the first few (see below). */
export const SCANNER_ROUTE_LIMIT = 30;
const SCANNER_ROUTES_KEY = ["copilot", "scanner", "routes"] as const;

async function fetchScannerRoutes(signal?: AbortSignal): Promise<ScannerRoutes> {
  const [w, p] = await Promise.allSettled([
    // The watchlist re-reads 60 bars for ~80 candidates, so it can be slow on a cold cache.
    http({ path: "/api/positional/watchlist", query: { limit: SCANNER_ROUTE_LIMIT }, timeoutMs: 30_000, signal }),
    http({ path: "/api/positional/picks", query: { limit: SCANNER_ROUTE_LIMIT }, signal }),
  ]);
  const out: ScannerRoutes = { watch: null, watchError: null, picks: null, picksError: null };
  if (w.status === "fulfilled") {
    const d = rec(w.value.data);
    if (d.buckets && typeof d.buckets === "object" && !Array.isArray(d.buckets)) out.watch = d;
    else out.watchError = drift("positional.watchlist: no buckets");
  } else out.watchError = w.reason;
  if (p.status === "fulfilled") {
    const d = rec(p.value.data);
    if (Array.isArray(d.picks)) out.picks = d;
    else out.picksError = drift("positional.picks: no picks list");
  } else out.picksError = p.reason;
  // Both routes failing is the query's error; one failing is the reading screen's to judge.
  if (!out.watch && !out.picks) throw out.watchError ?? out.picksError;
  return out;
}

/** The shared read. `select` turns the two bodies into a screen's own view and may throw that screen's error. */
export function useScannerRoutes<T>(select: (r: ScannerRoutes) => T) {
  return useQuery<ScannerRoutes, Error, T>({
    queryKey: SCANNER_ROUTES_KEY,
    staleTime: 5 * 60_000,
    retry,
    queryFn: ({ signal }) => fetchScannerRoutes(signal),
    select,
  });
}

// ── watch levels ─────────────────────────────────────────────────────────

export const WATCH_BUCKETS = ["breakout_confirmed", "pre_breakout", "true_accumulation", "trend_continuation"] as const;
export type WatchBucket = (typeof WATCH_BUCKETS)[number];

export interface WatchRow {
  symbol: string;
  bucket: WatchBucket;
  sector: string | null;
  /** End-of-day close on `asOf`. */
  close: number | null;
  /** The breakout level the scanner watches. */
  trigger: number | null;
  /** Suggested stop: 1.5 × ATR(14) below the trigger, the close or the 20-day EMA, by bucket. */
  stop: number | null;
  /** ATR(14) as a percent of the close. */
  atrPct: number | null;
  why: string | null;
}

export interface Watchlist {
  /** The session the levels were computed for; null when the scanner has no features yet. */
  asOf: string | null;
  rows: WatchRow[];
}

/**
 * The levels the Trader screens list: the first WATCH_PER_BUCKET rows of each bucket. The route caps each bucket at
 * max(4, limit ÷ 3 or ÷ 4) from one score-ordered candidate list, so these are exactly the rows it sends for
 * limit=12 — the limit these screens used to ask for.
 */
const WATCH_PER_BUCKET = 4;

export function parseWatchLevels(body: Record<string, unknown>): Watchlist {
  const buckets = rec(body.buckets);
  const rows: WatchRow[] = [];
  for (const bucket of WATCH_BUCKETS) {
    for (const item of arr(buckets[bucket]).slice(0, WATCH_PER_BUCKET)) {
      const r = rec(item);
      const symbol = str(r.nse_symbol);
      if (!symbol) continue;
      rows.push({
        symbol,
        bucket,
        sector: str(r.sector),
        close: num(r.close_price),
        trigger: num(r.trigger_price),
        stop: num(r.stop_price),
        atrPct: num(r.atr_pct),
        why: str(r.why),
      });
    }
  }
  return { asOf: str(body.as_of_date), rows };
}

function toWatchLevels(r: ScannerRoutes): Watchlist {
  if (!r.watch) throw r.watchError;
  return parseWatchLevels(r.watch);
}

export function useWatchLevels() {
  return useScannerRoutes(toWatchLevels);
}

// ── scanner signals ──────────────────────────────────────────────────────

export interface ScannerPick {
  symbol: string;
  /** ACCUMULATION | EARLY_BREAKOUT | BREAKOUT */
  stage: string | null;
  /** HIGH | MEDIUM | LOW */
  confidence: string | null;
  /** 0–1 */
  score: number | null;
  entry: number | null;
  stop: number | null;
  target: number | null;
  riskReward: number | null;
  daysMin: number | null;
  daysMax: number | null;
  reasons: string[];
  scans: string[];
}

export interface ScannerPicks {
  signalDate: string | null;
  picks: ScannerPick[];
}

/** The signals the Trader screens list: the route's first rows (it orders by score, then reward to risk). */
const PICKS_SHOWN = 6;

export function parseScannerPicks(body: Record<string, unknown>): ScannerPicks {
  const picks: ScannerPick[] = [];
  for (const item of arr(body.picks).slice(0, PICKS_SHOWN)) {
    const p = rec(item);
    const symbol = str(p.nse_symbol);
    if (!symbol) continue;
    picks.push({
      symbol,
      stage: str(p.stage),
      confidence: str(p.confidence),
      score: num(p.final_score),
      entry: num(p.entry_price),
      stop: num(p.stoploss),
      target: num(p.target_price),
      riskReward: num(p.risk_reward),
      daysMin: num(p.timeframe_days_min),
      daysMax: num(p.timeframe_days_max),
      reasons: strList(p.reasons),
      scans: strList(p.source_scans),
    });
  }
  return { signalDate: str(body.signal_date), picks };
}

function toScannerPicks(r: ScannerRoutes): ScannerPicks {
  if (!r.picks) throw r.picksError;
  return parseScannerPicks(r.picks);
}

export function useScannerPicks() {
  return useScannerRoutes(toScannerPicks);
}

// ── broker connections ───────────────────────────────────────────────────

export interface BrokerAccount {
  id: string;
  name: string;
  status: string | null;
  lastSyncAt: string | null;
  lastSyncCount: number | null;
}

export async function fetchBrokerAccounts(signal?: AbortSignal): Promise<BrokerAccount[]> {
  const res = await http({ path: "/api/broker/accounts", signal });
  const accounts = rec(res.data).accounts;
  if (!Array.isArray(accounts)) throw drift("broker.accounts: no accounts list");
  const out: BrokerAccount[] = [];
  for (const item of accounts) {
    const a = rec(item);
    const id = str(a.account_id);
    if (!id) continue;
    out.push({
      id,
      name: str(a.broker_display) ?? str(a.label) ?? str(a.broker) ?? "Broker",
      status: str(a.status),
      lastSyncAt: str(a.last_sync_at),
      lastSyncCount: num(a.last_sync_count),
    });
  }
  return out;
}

export function useBrokerAccounts() {
  const profile = useImpersonationStore((s) => s.profileId);
  return useQuery<BrokerAccount[]>({
    queryKey: ["copilot", "trading", "broker-accounts", profile ?? "self"],
    staleTime: 60_000,
    retry,
    queryFn: ({ signal }) => fetchBrokerAccounts(signal),
  });
}

// ── paper trades (existing adapter; results carry their own failure kinds) ──

export function usePaperPortfolio(sample: PaperSample, portfolio: PaperPortfolio, predictionDate: string | null) {
  return useQuery<PortfolioResult>({
    queryKey: ["copilot", "trading", "paper-portfolio", sample, portfolio, predictionDate ?? "latest"],
    staleTime: 60_000,
    queryFn: () => fetchPaperPortfolio(sample, portfolio, predictionDate),
  });
}

export function usePaperEvaluation(sample: PaperSample, portfolio: PaperPortfolio) {
  return useQuery<EvaluationResult>({
    queryKey: ["copilot", "trading", "paper-evaluation", sample, portfolio],
    staleTime: 60_000,
    queryFn: () => fetchPaperEvaluation(sample, portfolio),
  });
}

/** Delayed intraday status of the latest forward selection. Refreshes every minute while the tab is visible. */
export function usePaperLive(portfolio: PaperPortfolio, enabled: boolean) {
  return useQuery<LiveResult>({
    queryKey: ["copilot", "trading", "paper-live", portfolio],
    enabled,
    staleTime: 30_000,
    refetchInterval: 60_000,
    queryFn: () => fetchPaperLive(portfolio),
  });
}
