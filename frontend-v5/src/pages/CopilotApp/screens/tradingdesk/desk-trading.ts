/**
 * Smart trading desk — the user's own paper trades and price alerts. These are
 * the desk's only writes, and both are simulated: nothing here places an order
 * or reaches a broker.
 *
 *   GET    /api/desk/paper-trades?status=all          open and closed paper trades with their end-of-day marks
 *                                                     and a summary (backend/routes/desk_trading.py)
 *   POST   /api/desk/paper-trades                     { symbol, quantity, entry_price, stop_price, target_price, source }
 *   POST   /api/desk/paper-trades/{id}/close          {} — closes at the last close (exit reason "manual")
 *   GET    /api/desk/alerts?status=all                price alerts, active and fired, and the session they were checked through
 *   POST   /api/desk/alerts                           { symbol, condition, level }
 *   DELETE /api/desk/alerts/{id}                      204
 *
 * Marks, exits and alert checks use end-of-day daily bars (high, low, close of
 * the raw traded price). When those cannot be read the lists still answer,
 * with marks null and `marks_error` set; a mark is never made up. A trade whose stop and target are both touched in one
 * session is closed at the stop. Writes go through the app's http client (the
 * session cookie rides along) with no retry, and a failure keeps the server's
 * own words (a 409 limit, a 422 validation message) for the screen to show.
 *
 * Reads trust nothing: a missing or non-numeric field is null, never 0, and a
 * body without the list the route always sends throws a contract error.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { http } from "@/services/api/http";
import { ApiError } from "@/services/api/errors";
import { useImpersonationStore } from "@/stores/impersonation.store";
import { num } from "./desk-data";

type Raw = Record<string, unknown>;
const rec = (v: unknown): Raw => (v && typeof v === "object" && !Array.isArray(v) ? (v as Raw) : {});
const str = (v: unknown): string | null => (typeof v === "string" && v.trim() ? v.trim() : null);
const price = (v: unknown): number | null => {
  const n = num(v);
  return n != null && n > 0 ? n : null;
};

const isForbidden = (e: unknown) => e instanceof ApiError && (e.kind === "forbidden" || e.status === 403);
const retry = (count: number, e: unknown) => !isForbidden(e) && !(e instanceof ApiError && e.kind === "contract_drift") && count < 1;

const PAPER_KEY = ["copilot", "desk", "paper-trades"] as const;
const ALERTS_KEY = ["copilot", "desk", "alerts"] as const;

/** The route's error codes (backend/routes/desk_trading.py) in plain words; the code itself is shown beside them. */
const CODE_TEXT: Record<string, string> = {
  open_trade_limit: "You have the most open paper trades allowed (100). Close one first.",
  active_alert_limit: "You have the most active alerts allowed (50). Delete one first.",
  invalid_symbol: "The symbol is not a valid NSE symbol.",
  invalid_quantity: "The quantity must be a whole number from 1 to 10,00,000.",
  stop_not_below_entry: "The stop must be below the entry.",
  target_not_above_entry: "The target must be above the entry.",
  invalid_source: "The setup details sent with the trade were not accepted.",
  invalid_note: "The note was not accepted.",
  invalid_condition: "An alert is either above or below a level.",
  invalid_body: "The request was not in the expected form.",
  unknown_field: "The request carried a field the server does not take.",
  trade_not_found: "That paper trade is no longer on record.",
  alert_not_found: "That alert is no longer on record.",
  trade_already_closed: "That paper trade is already closed.",
  no_close_available: "There is no end-of-day close for this stock yet, so it cannot be closed at the last close.",
  prices_unavailable: "Prices could not be read from the data platform right now.",
  upstream_unavailable: "The data platform could not be reached right now.",
};

/** The server's own words for a failed write: its code in plain words with the code beside it, else its text. */
export function writeProblem(e: unknown): string {
  if (e instanceof ApiError) {
    if (e.detail) return CODE_TEXT[e.detail] ? `${CODE_TEXT[e.detail]} (${e.detail})` : e.detail;
    if (e.kind === "network") return "The network request failed.";
    if (e.kind === "timeout") return "The request took too long.";
    return e.message || `HTTP ${e.status ?? "error"}`;
  }
  return e instanceof Error && e.message ? e.message : "The request failed.";
}

// ── paper trades ─────────────────────────────────────────────────────────

export type ExitReason = "stop" | "target" | "manual";

export interface PaperTrade {
  id: string;
  symbol: string;
  quantity: number | null;
  entry: number | null;
  stop: number | null;
  target: number | null;
  note: string | null;
  /** Where the plan came from (`source.kind`, e.g. "scanner"), with its bucket and signal date when sent. */
  source: { kind: string | null; bucket: string | null; signalDate: string | null } | null;
  openedAt: string | null;
  status: "open" | "closed";
  closedAt: string | null;
  exitPrice: number | null;
  exitReason: ExitReason | null;
  /** The session the trade was closed on, and the route's note on it (e.g. both levels in one session). */
  exitSession: string | null;
  exitNote: string | null;
  /** Why an open trade has no mark ("no_prices_for_symbol", "prices_unavailable"). */
  markError: string | null;
  /** The last end-of-day close the trade was marked at, and its session. */
  lastClose: number | null;
  lastCloseDate: string | null;
  unrealizedRs: number | null;
  realizedRs: number | null;
}

export interface PaperSummary {
  open: number | null;
  closed: number | null;
  wins: number | null;
  losses: number | null;
  realizedRs: number | null;
  unrealizedRs: number | null;
  /** Open trades without a mark (then the unrealised total is not given). */
  unmarkedOpen: number | null;
  /** More closed trades are on record than were listed. */
  partial: boolean;
}

export interface PaperBook {
  asOf: string | null;
  checkedThrough: string | null;
  /** The price source and basis as the route names them. */
  source: string | null;
  priceBasis: string | null;
  /** "prices_unavailable" | "prices_partially_unavailable" when marks could not all be read. */
  marksError: string | null;
  exitRule: string | null;
  trades: PaperTrade[];
  summary: PaperSummary | null;
}

function readTrade(v: unknown): PaperTrade | null {
  const t = rec(v);
  const id = str(t.id);
  const symbol = str(t.symbol)?.toUpperCase();
  const status = str(t.status)?.toLowerCase();
  if (!id || !symbol || (status !== "open" && status !== "closed")) return null;
  const src = rec(t.source);
  const reason = str(t.exit_reason)?.toLowerCase();
  const q = num(t.quantity);
  return {
    id, symbol, status,
    quantity: q != null && q > 0 ? q : null,
    entry: price(t.entry_price),
    stop: price(t.stop_price),
    target: price(t.target_price),
    note: str(t.note),
    source: Object.keys(src).length ? { kind: str(src.kind), bucket: str(src.bucket), signalDate: str(src.signal_date) } : null,
    openedAt: str(t.opened_at),
    closedAt: str(t.closed_at),
    exitPrice: price(t.exit_price),
    exitReason: reason === "stop" || reason === "target" || reason === "manual" ? reason : null,
    exitSession: str(t.exit_session),
    exitNote: str(t.exit_note),
    markError: str(t.mark_error),
    lastClose: price(t.last_close),
    lastCloseDate: str(t.last_close_date),
    unrealizedRs: num(t.unrealized_pnl_rs),
    realizedRs: num(t.realized_pnl_rs),
  };
}

async function fetchPaperBook(signal?: AbortSignal): Promise<PaperBook> {
  const res = await http({ path: "/api/desk/paper-trades", query: { status: "all" }, signal });
  const d = rec(res.data);
  if (!Array.isArray(d.trades)) throw ApiError.contractDrift("desk.paper-trades: no trades list");
  const trades = d.trades.flatMap((v) => {
    const t = readTrade(v);
    return t ? [t] : [];
  });
  const s = rec(d.summary);
  const summary: PaperSummary | null = Object.keys(s).length
    ? {
        open: num(s.open), closed: num(s.closed), wins: num(s.wins), losses: num(s.losses),
        realizedRs: num(s.realized_pnl_rs), unrealizedRs: num(s.unrealized_pnl_rs), unmarkedOpen: num(s.unmarked_open), partial: s.partial === true,
      }
    : null;
  return {
    asOf: str(d.as_of), checkedThrough: str(d.checked_through), source: str(d.source), priceBasis: str(d.price_basis),
    marksError: str(d.marks_error), exitRule: str(d.exit_rule), trades, summary,
  };
}

export function usePaperTrades() {
  const profile = useImpersonationStore((st) => st.profileId);
  return useQuery<PaperBook>({
    queryKey: [...PAPER_KEY, profile ?? "self"],
    staleTime: 60_000,
    retry,
    queryFn: ({ signal }) => fetchPaperBook(signal),
  });
}

/** POST /api/desk/paper-trades — the body exactly as the route takes it. */
export interface NewPaperTrade {
  symbol: string;
  quantity: number;
  entry_price: number;
  stop_price: number;
  target_price: number | null;
  source: { kind: "scanner"; bucket?: string; signal_date?: string };
}

export function useAddPaperTrade() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (body: NewPaperTrade): Promise<PaperTrade | null> => {
      const res = await http({ method: "POST", path: "/api/desk/paper-trades", body, noRetry: true });
      // The trade is created once the route answers 2xx; its echo is only used for the id.
      return readTrade(rec(res.data).trade);
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: PAPER_KEY }),
  });
}

export function useClosePaperTrade() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (id: string): Promise<void> => {
      await http({ method: "POST", path: `/api/desk/paper-trades/${encodeURIComponent(id)}/close`, body: {}, noRetry: true });
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: PAPER_KEY }),
  });
}

// ── price alerts ─────────────────────────────────────────────────────────

export interface DeskAlert {
  id: string;
  symbol: string;
  condition: "above" | "below";
  level: number | null;
  note: string | null;
  createdAt: string | null;
  status: "active" | "fired";
  firedAt: string | null;
  /** The session whose high (above) or low (below) reached the level. */
  firedSession: string | null;
  firedPrice: number | null;
  /** An active alert's last end-of-day close, or why there is none. */
  lastClose: number | null;
  lastCloseDate: string | null;
  markError: string | null;
}

export interface AlertBook {
  asOf: string | null;
  /** The last session the alerts were checked against. */
  checkedThrough: string | null;
  source: string | null;
  marksError: string | null;
  firingRule: string | null;
  alerts: DeskAlert[];
}

function readAlert(v: unknown): DeskAlert | null {
  const a = rec(v);
  const id = str(a.id);
  const symbol = str(a.symbol)?.toUpperCase();
  const condition = str(a.condition)?.toLowerCase();
  const status = str(a.status)?.toLowerCase();
  if (!id || !symbol || (condition !== "above" && condition !== "below") || (status !== "active" && status !== "fired")) return null;
  return {
    id, symbol, condition, status,
    level: price(a.level),
    note: str(a.note),
    createdAt: str(a.created_at),
    firedAt: str(a.fired_at),
    firedSession: str(a.fired_session),
    firedPrice: price(a.fired_price),
    lastClose: price(a.last_close),
    lastCloseDate: str(a.last_close_date),
    markError: str(a.mark_error),
  };
}

async function fetchAlerts(signal?: AbortSignal): Promise<AlertBook> {
  const res = await http({ path: "/api/desk/alerts", query: { status: "all" }, signal });
  const d = rec(res.data);
  if (!Array.isArray(d.alerts)) throw ApiError.contractDrift("desk.alerts: no alerts list");
  const alerts = d.alerts.flatMap((v) => {
    const a = readAlert(v);
    return a ? [a] : [];
  });
  return {
    asOf: str(d.as_of), checkedThrough: str(d.checked_through), source: str(d.source), marksError: str(d.marks_error),
    firingRule: str(d.firing_rule), alerts,
  };
}

export function useDeskAlerts() {
  const profile = useImpersonationStore((st) => st.profileId);
  return useQuery<AlertBook>({
    queryKey: [...ALERTS_KEY, profile ?? "self"],
    staleTime: 60_000,
    retry,
    queryFn: ({ signal }) => fetchAlerts(signal),
  });
}

/** POST /api/desk/alerts — the body exactly as the route takes it. */
export interface NewAlert {
  symbol: string;
  condition: "above" | "below";
  level: number;
}

export function useAddAlert() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (body: NewAlert): Promise<DeskAlert | null> => {
      const res = await http({ method: "POST", path: "/api/desk/alerts", body, noRetry: true });
      return readAlert(rec(res.data).alert);
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ALERTS_KEY }),
  });
}

export function useDeleteAlert() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (id: string): Promise<void> => {
      await http({ method: "DELETE", path: `/api/desk/alerts/${encodeURIComponent(id)}`, noRetry: true });
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ALERTS_KEY }),
  });
}

// ── per-trade figures the Portfolio tab shows (worked out from the trade) ─

const IST = "Asia/Kolkata";
const istDay = (iso: string | null): string | null => {
  if (!iso) return null;
  const d = new Date(iso);
  return Number.isFinite(d.getTime()) ? d.toLocaleDateString("en-CA", { timeZone: IST }) : null;
};

/** True when the trade was opened today, India time. */
export function openedToday(t: PaperTrade, now: Date = new Date()): boolean {
  return istDay(t.openedAt) === now.toLocaleDateString("en-CA", { timeZone: IST });
}

/** Calendar days from opening to closing (India time); null without both stamps. */
export function heldDays(t: PaperTrade): number | null {
  const a = istDay(t.openedAt);
  const b = istDay(t.closedAt);
  if (!a || !b) return null;
  return Math.round((Date.parse(`${b}T00:00:00Z`) - Date.parse(`${a}T00:00:00Z`)) / 86_400_000);
}

/** A closed trade's return on its entry, percent: (exit − entry) ÷ entry. */
export function tradeReturnPct(t: PaperTrade): number | null {
  if (t.exitPrice == null || t.entry == null) return null;
  return ((t.exitPrice - t.entry) / t.entry) * 100;
}

/** A closed trade's result in R: (exit − entry) ÷ (entry − stop); null without a stop below the entry. */
export function tradeR(t: PaperTrade): number | null {
  if (t.exitPrice == null || t.entry == null || t.stop == null || !(t.entry > t.stop)) return null;
  return (t.exitPrice - t.entry) / (t.entry - t.stop);
}
