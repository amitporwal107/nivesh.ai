/**
 * Trade Desk › Paper Trading › P&L dashboard — the reads (docs/paper_pnl_dashboard/DESIGN.md, v1 and "v2": the owner's
 * Real-Time PnL design of 4 Nov 2026 afternoon — Paper and Live (read-only broker positions), standard trading words on this
 * screen, Modify risk for paper share trades).
 *
 *   GET /api/desk/pnl?segment=&period=&from=&to=&mode=&account=
 *                                                     one snapshot: accounts, both modes, summary for the selection, positions
 *                                                     (legs flat; PAPER and LIVE rows), strategies, pending entries, closed
 *                                                     trades for the period, risk + alerts, analytics (backend/routes/desk_pnl.py;
 *                                                     READ-ONLY — it applies no exit and places no order, so it may be read
 *                                                     every few seconds)
 *   GET /api/desk/pnl/stream?<same filters>           server-sent events: `snapshot` with the same body every few seconds in
 *                                                     session; a `: heartbeat` comment; the server closes it after 30 min
 *   GET /api/desk/pnl/timeseries?interval=&mode=      the selected book's P&L through today's session, from Kite candles
 *   GET /api/desk/pnl/timeseries?interval=15m&trade=  ONE trade's net P&L (a paper share trade since its entry; a structure or
 *                                                     a live position over today's session)
 *   GET /api/desk/pnl/journal/{trade_id}              the Scan dashboard's signal for the stock on the trade's entry day
 *   PATCH /api/desk/paper-trades/{trade_id}/levels    Modify risk (paper share trades; new stop loss / target in force from
 *                                                     the next session)
 *   GET /api/desk/pnl/exits · POST …/exits/seen       Exit watch (EXIT_WATCH.md): live positions' stop loss and exit alerts;
 *   PUT / DELETE /api/positions/{U}/levels            marking alerts seen; the user's own stop for an underlying
 *
 * Transport (usePaperPnl): the stream first; polling GET /api/desk/pnl (3 s in session, 30 s otherwise) when EventSource is
 * missing, the session rides a bearer token or an advisor's X-Active-Profile (EventSource cannot send headers), or the stream
 * fails twice — then the stream is tried again after five minutes. Paused while the tab is hidden. Every snapshot carries a
 * server `sequence`; one not newer than the last applied is dropped, so a duplicate or a late answer never rolls the screen
 * back. Each snapshot is the whole picture, so a gap needs no repair.
 *
 * Reads trust nothing: a missing or non-numeric figure is null (the screen shows "—"), never 0; a body without `summary` or
 * `positions` is a contract error. Nothing here reaches a broker order; the writes are the paper levels PATCH, the exit alerts'
 * seen mark and the user's own stop levels.
 */
import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { http } from "@/services/api/http";
import { apiConfig } from "@/services/api/config";
import { ApiError } from "@/services/api/errors";
import { getAuthToken } from "@/services/api/auth-token";
import { useImpersonationStore } from "@/stores/impersonation.store";
import { num } from "../../desk-data";
import { PAPER_KEY } from "../../desk-trading";

type Raw = Record<string, unknown>;
const rec = (v: unknown): Raw => (v && typeof v === "object" && !Array.isArray(v) ? (v as Raw) : {});
const arr = (v: unknown): unknown[] => (Array.isArray(v) ? v : []);
const str = (v: unknown): string | null => (typeof v === "string" && v.trim() ? v.trim() : null);
const bool = (v: unknown): boolean | null => (typeof v === "boolean" ? v : null);

// ── filters ──────────────────────────────────────────────────────────────

export type PnlSegment = "ALL" | "EQUITY" | "FUTURES" | "OPTIONS";
export type PnlPeriod = "TODAY" | "1W" | "1M" | "ALL" | "CUSTOM";
export const SEGMENTS: readonly PnlSegment[] = ["ALL", "EQUITY", "FUTURES", "OPTIONS"];
export const PERIODS: readonly PnlPeriod[] = ["TODAY", "1W", "1M", "ALL", "CUSTOM"];
export type PnlMode = "ALL" | "PAPER" | "LIVE";
export const MODES: readonly PnlMode[] = ["ALL", "PAPER", "LIVE"];

export interface PnlFilters {
  segment: PnlSegment;
  period: PnlPeriod;
  /** YYYY-MM-DD, only with period CUSTOM. */
  from?: string | null;
  to?: string | null;
  /** v2: ALL | PAPER | LIVE (default ALL). */
  mode?: PnlMode;
  /** v2: "ALL" | "paper" | a broker account id (default ALL). */
  account?: string;
}

/** The query the routes take (DESIGN.md "API", v2 adds mode and account). A CUSTOM period without both days is sent as ALL. */
export function pnlQuery(f: PnlFilters): Record<string, string> {
  const q: Record<string, string> = { segment: f.segment, period: f.period, mode: f.mode ?? "ALL", account: f.account ?? "ALL" };
  if (f.period === "CUSTOM") {
    if (f.from && f.to) {
      q.from = f.from;
      q.to = f.to;
    } else q.period = "ALL";
  }
  return q;
}

// ── the snapshot ─────────────────────────────────────────────────────────

export type PriceStatus = "LIVE" | "DELAYED" | "CLOSE" | "EOD" | "MISSING";
const PRICE_STATUSES: readonly string[] = ["LIVE", "DELAYED", "CLOSE", "EOD", "MISSING"];
export type AlertSeverity = "CRITICAL" | "WARNING" | "INFO";
const SEVERITIES: readonly string[] = ["CRITICAL", "WARNING", "INFO"];

export interface PnlMarket {
  session: string | null;
  feed: string | null;
  feedAgeSeconds: number | null;
  staleAfterSeconds: number | null;
  priceRule: string | null;
  day: string | null;
  /** The route's own sentences about today's prices (e.g. no Kite session: F&O at end of day). */
  notes: string[];
}

export interface PnlSummary {
  realized: number | null;
  unrealized: number | null;
  gross: number | null;
  chargesBooked: number | null;
  chargesEstimated: number | null;
  net: number | null;
  dayPnl: number | null;
  allocatedCapital: number | null;
  returnPct: number | null;
  /** Trades: a structure counts once. */
  openPositions: number | null;
  /** Rows: every share position and every leg. */
  openLegs: number | null;
  winningPositions: number | null;
  losingPositions: number | null;
  closedTrades: number | null;
  pendingEntries: number | null;
  unpricedPositions: number | null;
  stalePositions: number | null;
  /** False when an open position has no price, so the totals leave it out. */
  complete: boolean | null;
  /** v2: |net quantity × multiplier × LTP| summed over the selection's open rows. */
  exposureRs: number | null;
  /** v2: what the capital figure is (paper: the paper account's starting capital; live: …). */
  capitalBasis: string | null;
}

/** v2: one account (paper or a broker account), always listed whatever the filters. */
export type AccountState = "OK" | "STALE" | "SIGN_IN" | "ERROR" | "OFF";
const ACCOUNT_STATES: readonly string[] = ["OK", "STALE", "SIGN_IN", "ERROR", "OFF"];
export interface PnlAccount {
  accountId: string;
  name: string;
  mode: "PAPER" | "LIVE";
  broker: string | null;
  state: AccountState;
  stateNote: string | null;
  readAt: string | null;
  capital: number | null;
  capitalBasis: string | null;
  openPositions: number | null;
  net: number | null;
}

/** v2: one mode's totals (segment applies; mode and account do not). */
export interface PnlModeSummary {
  realized: number | null;
  unrealized: number | null;
  gross: number | null;
  charges: number | null;
  net: number | null;
  capital: number | null;
  returnPct: number | null;
  openPositions: number | null;
  complete: boolean | null;
  /** False when no account of this mode could be read (e.g. every broker session expired). */
  available: boolean | null;
  note: string | null;
}

export interface PnlPendingLevels { stopLoss: number | null; target: number | null; fromSession: string | null; version: number | null }

export interface PnlSegmentRow {
  segment: string;
  openPositions: number | null;
  realized: number | null;
  unrealized: number | null;
  charges: number | null;
  net: number | null;
}

export interface PnlExecution {
  executionId: string | null;
  /** "BUY" | "SELL" as sent; the screen shows it as a signed quantity. */
  side: string | null;
  quantity: number | null;
  price: number | null;
  at: string | null;
  /** "fill" (opening) | "exit" / "close" (closing), as sent. */
  kind: string | null;
}

export interface PnlPosition {
  positionId: string;
  tradeId: string | null;
  legIndex: number | null;
  strategyId: string | null;
  strategyName: string | null;
  mode: string;
  account: string | null;
  instrument: string;
  symbol: string | null;
  underlying: string | null;
  segment: string | null;
  side: "LONG" | "SHORT" | null;
  netQuantity: number | null;
  lots: number | null;
  lotSize: number | null;
  avgPrice: number | null;
  ltp: number | null;
  prevClose: number | null;
  priceStatus: PriceStatus;
  priceSource: string | null;
  priceAt: string | null;
  priceAgeSeconds: number | null;
  /** The IST day of the price (a delayed F&O leg can carry the previous session's last trade). */
  priceDay: string | null;
  investedValue: number | null;
  unrealized: number | null;
  realized: number | null;
  gross: number | null;
  chargesEstimated: number | null;
  net: number | null;
  dayPnl: number | null;
  returnPct: number | null;
  stopLoss: number | null;
  target: number | null;
  distanceToStopPct: number | null;
  riskUsedPct: number | null;
  status: string | null;
  openedAt: string | null;
  expiry: string | null;
  executions: PnlExecution[];
  /** v2: "paper" or the broker account id. */
  accountId: string | null;
  /** v2, LIVE: the broker's own P&L on its last read (it includes the broker's realised part). */
  brokerPnl: number | null;
  brokerReadAt: string | null;
  /** v2, LIVE: intraday | delivery | carryforward | margin. */
  product: string | null;
  exposureRs: number | null;
  /** v2: an open PAPER share trade whose stop loss / target may be changed (Modify risk). */
  editableLevels: boolean;
  /** Where a paper row came from: "desk" (the desk's own paper trades) or "scanner" (a Scanner-to-Paper Trading position,
   *  watched live by the paper monitor; its levels are read-only here). "broker" for LIVE rows; null from an older server. */
  rowSource: "desk" | "scanner" | "broker" | null;
  /** Paper Trading v2 (UI_DESIGN_V2 §2.05): the opportunity's setup type for a scanner row (`setup_type`), when the route sends
   *  it; null otherwise (the screen then groups by where the row came from). */
  setupType: string | null;
  /** v2: a change saved but not in force yet (from the next session). */
  pendingLevels: PnlPendingLevels | null;
  /** v2: why the fills list is short or empty (live: only today's fills come from the broker). */
  executionsNote: string | null;
  /** v2, LIVE: why the broker's contract could not be mapped to an NSE contract (null when mapped). */
  contractProblem: string | null;
}

export interface PnlStrategy {
  strategyId: string;
  name: string;
  /** "Bull call spread 49500/55000 · 23 Nov · 1 lot", the route's one line. */
  summary: string | null;
  underlying: string | null;
  direction: string | null;
  status: string | null;
  legs: string[];
  underlyingLtp: number | null;
  stopUnderlying: number | null;
  targetUnderlying: number | null;
  entryNetPremium: number | null;
  currentValue: number | null;
  unrealized: number | null;
  chargesEstimated: number | null;
  net: number | null;
  capitalAtRisk: number | null;
  /** False when a leg has no price: then the strategy's unrealized and net are null. */
  complete: boolean | null;
  openedAt: string | null;
  riskNote: string | null;
}

export interface PnlPending {
  tradeId: string;
  symbol: string;
  entryRule: string | null;
  level: number | null;
  ltp: number | null;
}

export interface PnlClosed {
  tradeId: string;
  instrument: string;
  segment: string | null;
  closedAt: string | null;
  exitSession: string | null;
  exitReason: string | null;
  realized: number | null;
  charges: number | null;
  net: number | null;
}

export interface PnlAlert {
  severity: AlertSeverity;
  type: string;
  positionId: string | null;
  symbol: string | null;
  message: string;
  observed: number | null;
  threshold: number | null;
}

export interface PnlRisk {
  capital: { starting: number | null; cash: number | null; blocked: number | null; available: number | null; utilisationPct: number | null; basis: string | null };
  openRiskRs: number | null;
  openRiskLimitRs: number | null;
  strategiesCapitalAtRiskRs: number | null;
  /** The distance (%) under which a position is "near" its stop loss. */
  nearStopPct: number | null;
  dailyLossLimitRs: number | null;
  dailyLossUsedPct: number | null;
  alerts: PnlAlert[];
  /** v2: margin used (paper: capital blocked by open trades, not exchange margin; live: not read from brokers). */
  margin: { usedPct: number | null; basis: string | null };
  exposureRs: number | null;
}

export interface PnlAnalytics {
  trades: number | null;
  wins: number | null;
  losses: number | null;
  winRatePct: number | null;
  profitFactor: number | null;
  avgWin: number | null;
  avgLoss: number | null;
  maxDrawdownRs: number | null;
  maxDrawdownPct: number | null;
  daily: Array<{ date: string; net: number | null }>;
}

export interface PnlSnapshot {
  /** v2: the SELECTED mode (ALL | PAPER | LIVE); v1 always sent PAPER. */
  mode: string;
  currency: string;
  asOf: string | null;
  sequence: number | null;
  filters: { segment: string | null; period: string | null; from: string | null; to: string | null; mode: string | null; account: string | null };
  /** v2: every account (paper + each broker account), whatever the filters. */
  accounts: PnlAccount[];
  /** v2: both modes' totals, unfiltered by mode / account. */
  modes: { PAPER: PnlModeSummary | null; LIVE: PnlModeSummary | null };
  market: PnlMarket;
  summary: PnlSummary;
  bySegment: PnlSegmentRow[];
  positions: PnlPosition[];
  strategies: PnlStrategy[];
  pendingEntries: PnlPending[];
  closed: PnlClosed[];
  /** Closed trades in the period on record, and whether more were on record than listed. */
  closedTotal: number | null;
  closedPartial: boolean;
  /** Why end-of-day marks could not all be read on this pass, or null. */
  marksError: string | null;
  risk: PnlRisk;
  analytics: PnlAnalytics | null;
  reconciliation: { checked: number | null; mismatches: number; basis: string | null };
  notes: Record<string, string>;
}

function readExecution(v: unknown): PnlExecution {
  const e = rec(v);
  return { executionId: str(e.execution_id), side: str(e.side), quantity: num(e.quantity), price: num(e.price), at: str(e.at), kind: str(e.kind) };
}

function readPosition(v: unknown, i: number): PnlPosition | null {
  const p = rec(v);
  const id = str(p.position_id);
  if (!id) return null;
  const side = str(p.side);
  const ps = str(p.price_status);
  return {
    positionId: id, tradeId: str(p.trade_id), legIndex: num(p.leg_index), strategyId: str(p.strategy_id), strategyName: str(p.strategy_name),
    mode: str(p.mode) ?? "PAPER", account: str(p.account), instrument: str(p.instrument) ?? str(p.symbol) ?? `position ${i + 1}`,
    symbol: str(p.symbol), underlying: str(p.underlying), segment: str(p.segment),
    side: side === "LONG" || side === "SHORT" ? side : null,
    netQuantity: num(p.net_quantity), lots: num(p.lots), lotSize: num(p.lot_size), avgPrice: num(p.avg_price), ltp: num(p.ltp), prevClose: num(p.prev_close),
    // An unknown status is treated as the least trusted one: no price claim is made for it.
    priceStatus: ps && PRICE_STATUSES.includes(ps) ? (ps as PriceStatus) : "MISSING",
    priceSource: str(p.price_source), priceAt: str(p.price_at), priceAgeSeconds: num(p.price_age_seconds), priceDay: str(p.price_day),
    investedValue: num(p.invested_value), unrealized: num(p.unrealized_pnl), realized: num(p.realized_pnl), gross: num(p.gross_pnl),
    chargesEstimated: num(p.charges_estimated), net: num(p.net_pnl), dayPnl: num(p.day_pnl), returnPct: num(p.return_pct),
    stopLoss: num(p.stop_loss), target: num(p.target), distanceToStopPct: num(p.distance_to_stop_pct), riskUsedPct: num(p.risk_used_pct),
    status: str(p.status), openedAt: str(p.opened_at), expiry: str(p.expiry),
    executions: arr(p.executions).map(readExecution),
    accountId: str(p.account_id), brokerPnl: num(p.broker_pnl), brokerReadAt: str(p.broker_read_at), product: str(p.product),
    exposureRs: num(p.exposure_rs), editableLevels: p.editable_levels === true, pendingLevels: readPendingLevels(p.pending_levels),
    rowSource: p.source === "desk" || p.source === "scanner" || p.source === "broker" ? p.source : null,
    setupType: str(p.setup_type) ?? str(p.setup),
    executionsNote: str(p.executions_note), contractProblem: str(p.contract_problem),
  };
}

function readPendingLevels(v: unknown): PnlPendingLevels | null {
  if (!v || typeof v !== "object") return null;
  const l = rec(v);
  const out = { stopLoss: num(l.stop_loss), target: num(l.target), fromSession: str(l.from_session), version: num(l.version) };
  return out.stopLoss == null && out.target == null ? null : out;
}

function readAccount(v: unknown): PnlAccount | null {
  const a = rec(v);
  const id = str(a.account_id);
  const mode = str(a.mode);
  if (!id || (mode !== "PAPER" && mode !== "LIVE")) return null;
  const state = str(a.state);
  return {
    accountId: id, name: str(a.name) ?? (mode === "PAPER" ? "Paper account" : str(a.broker) ?? id), mode, broker: str(a.broker),
    // An unknown state is shown as an error: no claim that the account is fine.
    state: state && ACCOUNT_STATES.includes(state) ? (state as AccountState) : "ERROR",
    stateNote: str(a.state_note), readAt: str(a.read_at), capital: num(a.capital), capitalBasis: str(a.capital_basis),
    openPositions: num(a.open_positions), net: num(a.net_pnl),
  };
}

function readModeSummary(v: unknown): PnlModeSummary | null {
  if (!v || typeof v !== "object") return null;
  const m = rec(v);
  return {
    realized: num(m.realized_pnl), unrealized: num(m.unrealized_pnl), gross: num(m.gross_pnl), charges: num(m.charges), net: num(m.net_pnl),
    capital: num(m.capital), returnPct: num(m.return_pct), openPositions: num(m.open_positions), complete: bool(m.complete),
    available: bool(m.available), note: str(m.note),
  };
}

function readStrategy(v: unknown): PnlStrategy | null {
  const s = rec(v);
  const id = str(s.strategy_id);
  if (!id) return null;
  return {
    strategyId: id, name: str(s.name) ?? "Strategy", summary: str(s.summary), underlying: str(s.underlying), direction: str(s.direction), status: str(s.status),
    legs: arr(s.legs).map(str).filter((x): x is string => !!x),
    underlyingLtp: num(s.underlying_ltp), stopUnderlying: num(s.stop_underlying), targetUnderlying: num(s.target_underlying),
    entryNetPremium: num(s.entry_net_premium), currentValue: num(s.current_value), unrealized: num(s.unrealized_pnl),
    chargesEstimated: num(s.charges_estimated), net: num(s.net_pnl), capitalAtRisk: num(s.capital_at_risk), complete: bool(s.complete),
    openedAt: str(s.opened_at), riskNote: str(s.risk_note),
  };
}

function readAlert(v: unknown): PnlAlert | null {
  const a = rec(v);
  const message = str(a.message);
  if (!message) return null;
  const sev = str(a.severity);
  return {
    severity: sev && SEVERITIES.includes(sev) ? (sev as AlertSeverity) : "WARNING",
    type: str(a.type) ?? "ALERT", positionId: str(a.position_id), symbol: str(a.symbol), message,
    observed: num(a.observed), threshold: num(a.threshold),
  };
}

const strings = (v: unknown): string[] => arr(v).map(str).filter((x): x is string => !!x);

const SEVERITY_ORDER: Record<AlertSeverity, number> = { CRITICAL: 0, WARNING: 1, INFO: 2 };

/** GET /api/desk/pnl (and each stream event): the body as the screen uses it. */
export function readPnl(body: unknown): PnlSnapshot {
  const b = rec(body);
  if (!Array.isArray(b.positions)) throw ApiError.contractDrift("desk.pnl: no positions list");
  if (!b.summary || typeof b.summary !== "object") throw ApiError.contractDrift("desk.pnl: no summary");
  const s = rec(b.summary);
  const m = rec(b.market);
  const f = rec(b.filters);
  const r = rec(b.risk);
  const cap = rec(r.capital);
  const an = b.analytics && typeof b.analytics === "object" ? rec(b.analytics) : null;
  const recon = rec(b.reconciliation);
  const modes = rec(b.modes);
  const margin = rec(r.margin);
  const notes: Record<string, string> = {};
  for (const [k, v] of Object.entries(rec(b.notes))) {
    const t = str(v);
    if (t) notes[k] = t;
  }
  return {
    mode: str(b.mode) ?? "ALL",
    currency: str(b.currency) ?? "INR",
    asOf: str(b.as_of),
    sequence: num(b.sequence),
    filters: { segment: str(f.segment), period: str(f.period), from: str(f.from), to: str(f.to), mode: str(f.mode), account: str(f.account) },
    accounts: arr(b.accounts).map(readAccount).filter((x): x is PnlAccount => !!x),
    modes: { PAPER: readModeSummary(modes.PAPER), LIVE: readModeSummary(modes.LIVE) },
    market: { session: str(m.session), feed: str(m.feed), feedAgeSeconds: num(m.feed_age_seconds), staleAfterSeconds: num(m.stale_after_seconds), priceRule: str(m.price_rule), day: str(m.day), notes: strings(m.notes) },
    summary: {
      realized: num(s.realized_pnl), unrealized: num(s.unrealized_pnl), gross: num(s.gross_pnl), chargesBooked: num(s.charges_booked),
      chargesEstimated: num(s.charges_estimated), net: num(s.net_pnl), dayPnl: num(s.day_pnl), allocatedCapital: num(s.allocated_capital),
      returnPct: num(s.return_pct), openPositions: num(s.open_positions), openLegs: num(s.open_legs), winningPositions: num(s.winning_positions), losingPositions: num(s.losing_positions),
      closedTrades: num(s.closed_trades), pendingEntries: num(s.pending_entries), unpricedPositions: num(s.unpriced_positions),
      stalePositions: num(s.stale_positions), complete: bool(s.complete), exposureRs: num(s.exposure_rs), capitalBasis: str(s.capital_basis),
    },
    bySegment: arr(b.by_segment).flatMap((x) => {
      const g = rec(x);
      const seg = str(g.segment);
      return seg ? [{ segment: seg, openPositions: num(g.open_positions), realized: num(g.realized_pnl), unrealized: num(g.unrealized_pnl), charges: num(g.charges), net: num(g.net_pnl) }] : [];
    }),
    positions: (b.positions as unknown[]).map(readPosition).filter((x): x is PnlPosition => !!x),
    strategies: arr(b.strategies).map(readStrategy).filter((x): x is PnlStrategy => !!x),
    pendingEntries: arr(b.pending_entries).flatMap((x) => {
      const p = rec(x);
      const id = str(p.trade_id);
      return id ? [{ tradeId: id, symbol: str(p.symbol) ?? "—", entryRule: str(p.entry_rule), level: num(p.level), ltp: num(p.ltp) }] : [];
    }),
    closed: arr(b.closed).flatMap((x) => {
      const c = rec(x);
      const id = str(c.trade_id);
      return id ? [{ tradeId: id, instrument: str(c.instrument) ?? "—", segment: str(c.segment), closedAt: str(c.closed_at), exitSession: str(c.exit_session),
        exitReason: str(c.exit_reason), realized: num(c.realized_pnl), charges: num(c.charges), net: num(c.net_pnl) }] : [];
    }),
    closedTotal: num(b.closed_total),
    closedPartial: b.closed_partial === true,
    marksError: str(b.marks_error),
    risk: {
      capital: { starting: num(cap.starting), cash: num(cap.cash), blocked: num(cap.blocked), available: num(cap.available), utilisationPct: num(cap.utilisation_pct), basis: str(cap.basis) },
      openRiskRs: num(r.open_risk_rs), openRiskLimitRs: num(r.open_risk_limit_rs),
      strategiesCapitalAtRiskRs: num(r.strategies_capital_at_risk_rs), nearStopPct: num(r.near_stop_pct), dailyLossLimitRs: num(r.daily_loss_limit_rs), dailyLossUsedPct: num(r.daily_loss_used_pct),
      alerts: arr(r.alerts).map(readAlert).filter((x): x is PnlAlert => !!x).sort((a, z) => SEVERITY_ORDER[a.severity] - SEVERITY_ORDER[z.severity]),
      margin: { usedPct: num(margin.used_pct), basis: str(margin.basis) },
      exposureRs: num(r.exposure_rs),
    },
    analytics: an ? {
      trades: num(an.trades), wins: num(an.wins), losses: num(an.losses), winRatePct: num(an.win_rate_pct), profitFactor: num(an.profit_factor),
      avgWin: num(an.avg_win), avgLoss: num(an.avg_loss), maxDrawdownRs: num(an.max_drawdown_rs), maxDrawdownPct: num(an.max_drawdown_pct),
      daily: arr(an.daily).flatMap((x) => { const d = rec(x); const day = str(d.date); return day ? [{ date: day, net: num(d.net_pnl) }] : []; }),
    } : null,
    reconciliation: { checked: num(recon.checked), mismatches: arr(recon.mismatches).length, basis: str(recon.basis) },
    notes,
  };
}

// ── the live connection ──────────────────────────────────────────────────

export type PnlConnection = "connecting" | "live" | "reconnecting" | "polling" | "paused" | "error";

export interface PnlFeedState {
  data: PnlSnapshot | null;
  /** The last failure (a poll that failed, a contract error); the last good snapshot stays on screen. */
  error: unknown;
  connection: PnlConnection;
  transport: "sse" | "poll" | null;
  /** Date.now() of the last applied snapshot, for "updated Ns ago". */
  receivedAt: number | null;
  /** Snapshots dropped because their sequence was not newer than the last applied (duplicates, late answers). */
  dropped: number;
  /** The stream's `problem` event: one server pass failed; the last snapshot stays. Cleared by the next snapshot. */
  problem: string | null;
}

const STREAM_FAILS_BEFORE_POLL = 2;
const RETRY_STREAM_AFTER_MS = 5 * 60_000;
const POLL_OPEN_MS = 3_000;
const POLL_IDLE_MS = 30_000;
const POLL_ERROR_MS = 10_000;

/** One dashboard's connection: the stream, or polling, for one set of filters. Disposed when the filters change. */
class PnlFeed {
  private es: EventSource | null = null;
  private timer: ReturnType<typeof setTimeout> | null = null;
  private inflight: AbortController | null = null;
  private fails = 0;
  private pollUntil = 0;
  private disposed = false;
  private lastSeq: number | null = null;
  private state: PnlFeedState;

  constructor(private readonly query: Record<string, string>, private readonly canStream: () => boolean,
              initial: PnlSnapshot | null, private readonly onState: (s: PnlFeedState) => void) {
    this.state = { data: initial, error: null, connection: "connecting", transport: null, receivedAt: null, dropped: 0, problem: null };
  }

  private set(patch: Partial<PnlFeedState>) {
    if (this.disposed) return;
    this.state = { ...this.state, ...patch };
    this.onState(this.state);
  }

  start() {
    if (this.disposed) return;
    if (typeof document !== "undefined" && document.hidden) { this.pause(); return; }
    this.clearTimer();
    if (typeof EventSource !== "undefined" && this.canStream() && Date.now() >= this.pollUntil) this.openStream();
    else void this.poll();
  }

  pause() {
    this.closeStream();
    this.clearTimer();
    this.set({ connection: "paused" });
  }

  dispose() {
    this.closeStream();
    this.clearTimer();
    this.disposed = true;
  }

  private clearTimer() { if (this.timer) { clearTimeout(this.timer); this.timer = null; } }
  private closeStream() {
    if (this.es) { this.es.close(); this.es = null; }
    this.inflight?.abort();
    this.inflight = null;
  }

  private openStream() {
    this.closeStream();
    this.set({ connection: this.state.data ? "reconnecting" : "connecting" });
    try {
      const es = new EventSource(`${apiConfig.baseUrl}/api/desk/pnl/stream?${new URLSearchParams(this.query).toString()}`, { withCredentials: true });
      this.es = es;
      es.addEventListener("snapshot", (ev) => {
        this.fails = 0;
        let body: unknown;
        try { body = JSON.parse((ev as MessageEvent).data); } catch { return; /* a malformed event is skipped; the next one replaces it */ }
        this.apply(body, "sse");
      });
      // One pass on the server failed (data {error, kind}): keep the last snapshot, say so quietly.
      es.addEventListener("problem", (ev) => {
        let p: Raw = {};
        try { p = rec(JSON.parse((ev as MessageEvent).data)); } catch { /* a malformed problem still counts as one */ }
        this.set({ problem: str(p.error) ?? str(p.kind) ?? "one update failed on the server" });
      });
      es.onerror = () => {
        if (this.disposed) return;
        this.fails++;
        // CLOSED = the browser gave up for good (a non-200 answer or the wrong content type): poll at once.
        if (es.readyState === 2 || this.fails >= STREAM_FAILS_BEFORE_POLL) {
          this.closeStream();
          this.pollUntil = Date.now() + RETRY_STREAM_AFTER_MS;
          void this.poll();
        } else this.set({ connection: "reconnecting" });
      };
    } catch {
      this.pollUntil = Date.now() + RETRY_STREAM_AFTER_MS;
      void this.poll();
    }
  }

  private async poll() {
    if (this.disposed) return;
    this.clearTimer();
    this.inflight?.abort();
    const ctl = (this.inflight = new AbortController());
    let wait = POLL_ERROR_MS;
    try {
      const res = await http({ path: "/api/desk/pnl", query: this.query, signal: ctl.signal, noRetry: true, timeoutMs: 15_000 });
      if (ctl.signal.aborted || this.disposed) return;
      this.apply(res.data, "poll");
      wait = this.state.data?.market.session === "open" ? POLL_OPEN_MS : POLL_IDLE_MS;
    } catch (e) {
      if (ctl.signal.aborted || this.disposed) return;
      this.set({ error: e, connection: "error", transport: "poll" });
    }
    if (this.disposed || ctl.signal.aborted) return;
    // Back to the stream once its holiday is over; otherwise the next poll.
    this.timer = setTimeout(() => this.start(), wait);
  }

  private apply(body: unknown, transport: "sse" | "poll") {
    let snap: PnlSnapshot;
    try {
      snap = readPnl(body);
    } catch (e) {
      this.set({ error: e, connection: "error", transport });
      return;
    }
    if (this.lastSeq != null && snap.sequence != null && snap.sequence <= this.lastSeq) {
      this.set({ dropped: this.state.dropped + 1 });
      return;
    }
    if (snap.sequence != null) this.lastSeq = snap.sequence;
    this.set({ data: snap, error: null, problem: null, transport, receivedAt: Date.now(), connection: transport === "sse" ? "live" : "polling" });
  }
}

/** The dashboard's snapshot, kept current by the stream or by polling (see the header). `paused` (the screen's Pause button)
 *  closes the stream / stops the polls and keeps the last snapshot on screen; Resume opens a fresh connection. */
export function usePaperPnl(filters: PnlFilters, paused = false): PnlFeedState & { retry: () => void } {
  const profile = useImpersonationStore((st) => st.profileId);
  const query = pnlQuery(filters);
  const key = `${new URLSearchParams(query).toString()}|${profile ?? ""}`;
  const [state, setState] = useState<PnlFeedState>({ data: null, error: null, connection: "connecting", transport: null, receivedAt: null, dropped: 0, problem: null });
  const feed = useRef<PnlFeed | null>(null);
  const last = useRef<PnlSnapshot | null>(null);
  last.current = state.data;

  useEffect(() => {
    if (paused) {
      setState((st) => ({ ...st, connection: "paused" }));
      return;
    }
    // EventSource sends cookies only: a bearer-token session or an advisor viewing a client (X-Active-Profile) must poll.
    const canStream = () => !getAuthToken() && !profile;
    const f = new PnlFeed(JSON.parse(JSON.stringify(query)) as Record<string, string>, canStream, last.current, setState);
    feed.current = f;
    f.start();
    const onVis = () => { if (document.hidden) f.pause(); else f.start(); };
    document.addEventListener("visibilitychange", onVis);
    return () => {
      document.removeEventListener("visibilitychange", onVis);
      f.dispose();
      if (feed.current === f) feed.current = null;
    };
    // `key` is the whole of the query and the profile.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, paused]);

  return { ...state, retry: () => feed.current?.start() };
}

// ── the intraday curve ───────────────────────────────────────────────────

export type PnlInterval = "5m" | "15m";

export interface PnlPoint {
  t: string;
  unrealized: number | null;
  realized: number | null;
  gross: number | null;
  net: number | null;
  changeSinceBaseline: number | null;
}

export interface PnlTimeseries {
  date: string | null;
  interval: string | null;
  baselineGross: number | null;
  points: PnlPoint[];
  positionsUsed: number | null;
  missing: Array<{ positionId: string | null; reason: string }>;
  basis: string | null;
  partial: boolean;
  notes: string[];
}

export function readTimeseries(body: unknown): PnlTimeseries {
  const b = rec(body);
  if (!Array.isArray(b.points)) throw ApiError.contractDrift("desk.pnl.timeseries: no points list");
  const missing = arr(b.missing).flatMap((x) => {
    const m = rec(x);
    const reason = str(m.reason);
    return reason ? [{ positionId: str(m.position_id), reason }] : [];
  });
  return {
    date: str(b.date), interval: str(b.interval), baselineGross: num(b.baseline_gross),
    points: (b.points as unknown[]).flatMap((x) => {
      const p = rec(x);
      const t = str(p.t);
      return t ? [{ t, unrealized: num(p.unrealized_pnl), realized: num(p.realized_pnl), gross: num(p.gross_pnl), net: num(p.net_pnl), changeSinceBaseline: num(p.change_since_baseline) }] : [];
    }),
    positionsUsed: num(b.positions_used), missing, basis: str(b.basis),
    partial: bool(b.partial) ?? missing.length > 0,
    notes: strings(b.notes),
  };
}

const isForbidden = (e: unknown) => e instanceof ApiError && (e.kind === "forbidden" || e.status === 403);
const retry = (count: number, e: unknown) => !isForbidden(e) && !(e instanceof ApiError && e.kind === "contract_drift") && count < 1;

export function usePnlTimeseries(interval: PnlInterval, sessionOpen: boolean, mode: PnlMode = "ALL") {
  const profile = useImpersonationStore((st) => st.profileId);
  return useQuery<PnlTimeseries>({
    queryKey: ["copilot", "desk", "pnl-timeseries", interval, mode, profile ?? "self"],
    staleTime: 30_000,
    retry,
    refetchInterval: sessionOpen ? 60_000 : false,
    refetchIntervalInBackground: false,
    queryFn: async ({ signal }) => readTimeseries((await http({ path: "/api/desk/pnl/timeseries", query: { interval, mode }, signal, noRetry: true, timeoutMs: 30_000 })).data),
  });
}

// ── one trade's curve (v2) ───────────────────────────────────────────────

export interface TradeCurve {
  trade: string | null;
  mode: string | null;
  /** ISO of the first point. */
  from: string | null;
  /** True: from the trade's entry; false: today's session only (a structure, a live position). Null: not said. */
  sinceEntry: boolean | null;
  points: Array<{ t: string; gross: number | null; net: number | null }>;
  basis: string | null;
  missing: Array<{ positionId: string | null; reason: string }>;
  /** The trade's estimated charges taken off every point (constant), and the route's own sentences. */
  chargesEstimated: number | null;
  notes: string[];
}

export function readTradeCurve(body: unknown): TradeCurve {
  const b = rec(body);
  if (!Array.isArray(b.points)) throw ApiError.contractDrift("desk.pnl.timeseries(trade): no points list");
  return {
    trade: str(b.trade), mode: str(b.mode), from: str(b.from), sinceEntry: bool(b.since_entry),
    points: (b.points as unknown[]).flatMap((x) => {
      const p = rec(x);
      const t = str(p.t);
      return t ? [{ t, gross: num(p.gross_pnl), net: num(p.net_pnl) }] : [];
    }),
    basis: str(b.basis),
    missing: arr(b.missing).flatMap((x) => { const m = rec(x); const reason = str(m.reason); return reason ? [{ positionId: str(m.position_id), reason }] : []; }),
    chargesEstimated: num(b.charges_estimated), notes: strings(b.notes),
  };
}

/** GET /api/desk/pnl/timeseries?interval=15m&trade=<id> — only while the row is open. */
export function useTradeCurve(tradeId: string | null, sessionOpen: boolean) {
  const profile = useImpersonationStore((st) => st.profileId);
  return useQuery<TradeCurve>({
    queryKey: ["copilot", "desk", "pnl-trade-curve", tradeId ?? "", profile ?? "self"],
    enabled: !!tradeId,
    staleTime: 30_000,
    retry,
    refetchInterval: sessionOpen ? 60_000 : false,
    refetchIntervalInBackground: false,
    queryFn: async ({ signal }) => readTradeCurve((await http({ path: "/api/desk/pnl/timeseries", query: { interval: "15m", trade: tradeId as string }, signal, noRetry: true, timeoutMs: 30_000 })).data),
  });
}

// ── signals at entry (v2) ────────────────────────────────────────────────

export interface JournalParts { quality: number | null; trend: number | null; reason: number | null; size: number | null; participation: number | null; penalty: number | null }

export interface JournalSignal {
  /** "strong" (score ≥ 70, its plan frozen then) | "scored" (only the day's stored score). */
  kind: string | null;
  firstStrong: string | null;
  score: number | null;
  parts: JournalParts | null;
  reasons: string[];
  /** The score's penalties in words (e.g. a pump-and-dump pattern), when any. */
  penalties: string[];
  lists: Array<{ id: string; title: string }>;
  entry: number | null;
  stopLoss: number | null;
  target1: number | null;
  target2: number | null;
  rr1: number | null;
  rr2: number | null;
  trendExit: string | null;
  planOk: boolean | null;
  planNote: string | null;
  rules: string | null;
}

export interface PnlJournal {
  tradeId: string | null;
  symbol: string | null;
  /** The day of the signal looked up (the trade's entry session's day). */
  entryDay: string | null;
  found: boolean;
  why: string | null;
  signal: JournalSignal | null;
  trade: { source: { kind: string | null; bucket: string | null; signalDate: string | null } | null; rationale: string | null; note: string | null; openedAt: string | null; entryRule: string | null; entrySession: string | null };
}

export type JournalResult = { kind: "ok"; data: PnlJournal } | { kind: "none"; why: string };

function readJournalSignal(v: unknown): JournalSignal | null {
  if (!v || typeof v !== "object") return null;
  const g = rec(v);
  const pa = g.parts && typeof g.parts === "object" ? rec(g.parts) : null;
  return {
    kind: str(g.kind), firstStrong: str(g.first_strong), score: num(g.score),
    parts: pa ? { quality: num(pa.quality), trend: num(pa.trend), reason: num(pa.reason), size: num(pa.size), participation: num(pa.participation), penalty: num(pa.penalty) } : null,
    reasons: strings(g.reasons),
    penalties: arr(g.penalties).flatMap((x) => {
      if (typeof x === "string" && x.trim()) return [x.trim()];
      const o = rec(x);
      const t = str(o.text) ?? str(o.reason) ?? str(o.label) ?? str(o.code);
      const pts = num(o.points);
      return t ? [pts != null ? `${t} (${pts})` : t] : [];
    }),
    lists: arr(g.lists).flatMap((x) => {
      if (typeof x === "string" && x.trim()) return [{ id: x.trim(), title: x.trim() }];
      const l = rec(x);
      const id = str(l.id);
      const title = str(l.title) ?? id;
      return id || title ? [{ id: id ?? (title as string), title: title as string }] : [];
    }),
    entry: num(g.entry), stopLoss: num(g.stop_loss), target1: num(g.target_1), target2: num(g.target_2), rr1: num(g.rr_1), rr2: num(g.rr_2),
    trendExit: str(g.trend_exit), planOk: bool(g.plan_ok), planNote: str(g.plan_note), rules: str(g.rules),
  };
}

export function readJournal(body: unknown): PnlJournal {
  const b = rec(body);
  if (typeof b.found !== "boolean") throw ApiError.contractDrift("desk.pnl.journal: no found flag");
  const t = rec(b.trade);
  const src = t.source && typeof t.source === "object" ? rec(t.source) : null;
  const signal = readJournalSignal(b.signal);
  return {
    tradeId: str(b.trade_id), symbol: str(b.symbol), entryDay: str(b.entry_day),
    // "found" with no signal body is not a signal: the screen says so instead of an empty card.
    found: b.found === true && !!signal, why: str(b.why), signal,
    trade: { source: src ? { kind: str(src.kind), bucket: str(src.bucket), signalDate: str(src.signal_date) } : null,
      rationale: str(t.rationale), note: str(t.note), openedAt: str(t.opened_at), entryRule: str(t.entry_rule), entrySession: str(t.entry_session) },
  };
}

/** GET /api/desk/pnl/journal/{trade_id}; 404 journal_not_available / trade_not_found → {kind: "none"}. */
export function useTradeJournal(tradeId: string | null) {
  const profile = useImpersonationStore((st) => st.profileId);
  return useQuery<JournalResult>({
    queryKey: ["copilot", "desk", "pnl-journal", tradeId ?? "", profile ?? "self"],
    enabled: !!tradeId,
    staleTime: 60_000,
    retry,
    queryFn: async ({ signal }) => {
      try {
        const res = await http({ path: `/api/desk/pnl/journal/${encodeURIComponent(tradeId as string)}`, signal, noRetry: true, timeoutMs: 20_000 });
        return { kind: "ok", data: readJournal(res.data) };
      } catch (e) {
        if (e instanceof ApiError && e.status === 404) return { kind: "none", why: e.detail === "trade_not_found" ? "This trade is not in your paper book any more." : "No entry signal recorded for this position." };
        throw e;
      }
    },
  });
}

// ── Modify risk (v2): PATCH /api/desk/paper-trades/{id}/levels ───────────

/** Only the levels the user changed (an omitted level stays; this screen never sends `target_price: null`, which removes it). */
export interface LevelsBody { stop_price?: number; target_price?: number; note?: string }

/** 200 {trade, replayed, source, price_basis}: the waiting change and the rule sentence from the public trade. */
export interface LevelsSaved { pendingLevels: PnlPendingLevels | null; levelRule: string | null; replayed: boolean }

export function useEditPaperLevels() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({ tradeId, body, key }: { tradeId: string; body: LevelsBody; key: string }): Promise<LevelsSaved> => {
      const res = await http({ method: "PATCH", path: `/api/desk/paper-trades/${encodeURIComponent(tradeId)}/levels`, body, headers: { "Idempotency-Key": key }, noRetry: true, timeoutMs: 20_000 });
      const b = rec(res.data);
      const t = rec(b.trade);
      return { pendingLevels: readPendingLevels(t.pending_levels ?? b.pending_levels), levelRule: str(t.level_rule), replayed: b.replayed === true };
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: PAPER_KEY }),
  });
}

const LEVEL_CODES: Record<string, string> = {
  trade_not_found: "This trade is not in your paper book any more.",
  trade_already_closed: "This trade is already closed.",
  levels_not_editable: "Option and futures structures keep their levels in this release.",
  invalid_stop_price: "The stop loss must be a positive price.",
  invalid_target_price: "The target must be a positive price.",
  stop_not_below_price: "The stop loss must be below the last end-of-day close.",
  target_not_above_price: "The target must be above the last end-of-day close.",
  stop_not_below_entry: "This trade is still waiting for its entry: the stop loss must be below its reference entry price.",
  target_not_above_entry: "This trade is still waiting for its entry: the target must be above its reference entry price.",
  no_close_available: "There is no end-of-day close for this stock yet, so the levels cannot be checked.",
  levels_changed: "The levels were changed elsewhere just now. Reopen the form and try again.",
  too_many_level_changes: "This trade has had the most level changes allowed.",
  prices_unavailable: "End-of-day prices could not be read just now, so the levels cannot be checked. Try again shortly.",
  idempotency_conflict: "This save was already sent with other values. Reopen the form and try again.",
  invalid_idempotency_key: "The request's key was not accepted. Reopen the form and try again.",
  stop_not_below_target: "The stop loss must be below the target.",
  no_change: "Those are the levels already in force.",
  unknown_field: "The request carried a field the server does not take.",
  invalid_body: "The request could not be read by the server.",
};

/** A Modify risk refusal in words: the code (a plain detail or {code, message}) mapped, else the server's own sentence. */
export function levelsProblem(e: unknown): string {
  if (e instanceof ApiError) {
    const d = rec(e.body).detail;
    const code = typeof d === "string" ? d : str(rec(d).code);
    if (code && LEVEL_CODES[code]) return LEVEL_CODES[code];
    const message = str(rec(d).message);
    if (message) return message;
    if (e.kind === "network") return "The network request failed.";
    if (e.kind === "timeout") return "The request took too long.";
    return e.detail ?? e.message ?? `HTTP ${e.status ?? "error"}`;
  }
  return e instanceof Error && e.message ? e.message : "The request failed.";
}

export function newIdempotencyKey(): string {
  const c = (globalThis as { crypto?: { randomUUID?: () => string } }).crypto;
  return c?.randomUUID ? c.randomUUID() : `lv-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
}

// ── CSV export ───────────────────────────────────────────────────────────

const CSV_COLUMNS: Array<[string, (p: PnlPosition) => unknown]> = [
  ["mode", (p) => p.mode], ["account", (p) => p.account], ["instrument", (p) => p.instrument], ["strategy", (p) => p.strategyName],
  ["segment", (p) => p.segment], ["side", (p) => p.side], ["net_quantity", (p) => p.netQuantity], ["avg_price", (p) => p.avgPrice],
  ["ltp", (p) => p.ltp], ["price_status", (p) => p.priceStatus], ["price_at", (p) => p.priceAt], ["price_day", (p) => p.priceDay], ["invested_value", (p) => p.investedValue],
  ["unrealized_pnl", (p) => p.unrealized], ["realized_pnl", (p) => p.realized], ["charges_estimated", (p) => p.chargesEstimated],
  ["net_pnl", (p) => p.net], ["day_pnl", (p) => p.dayPnl], ["stop_loss", (p) => p.stopLoss], ["target", (p) => p.target],
  ["distance_to_stop_pct", (p) => p.distanceToStopPct], ["status", (p) => p.status], ["opened_at", (p) => p.openedAt], ["position_id", (p) => p.positionId],
  ["risk_used_pct", (p) => p.riskUsedPct], ["exposure_rs", (p) => p.exposureRs], ["broker_pnl", (p) => p.brokerPnl], ["account_id", (p) => p.accountId],
];

const csvCell = (v: unknown): string => {
  if (v == null) return "";            // unknown stays empty, never 0
  const s = String(v);
  return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
};

/** The rows on screen (after the filters) as CSV: one line per position or leg, never a strategy total (no double count). */
export function positionsCsv(rows: PnlPosition[]): string {
  return [CSV_COLUMNS.map(([h]) => h).join(","), ...rows.map((p) => CSV_COLUMNS.map(([, f]) => csvCell(f(p))).join(","))].join("\n") + "\n";
}

export function downloadText(name: string, text: string, type = "text/csv;charset=utf-8") {
  const url = URL.createObjectURL(new Blob([text], { type }));
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1_000);
}

// ── Exit watch (docs/paper_pnl_dashboard/EXIT_WATCH.md): live broker positions' stop loss and exit alerts ──────────────
//
//   GET  /api/desk/pnl/exits?account=        the watched live positions (stop, method, distance, status, loss at stop,
//                                            history), what is not watched and why, the last 7 days of alerts. READ-ONLY.
//   POST /api/desk/pnl/exits/seen {ids?}     marks the caller's alerts seen ({} = every unseen one)
//   PUT / DELETE /api/positions/{U}/levels   the user's own stop for an underlying (replaces the rule) / back to the rule
//
// Alerts are in-app only (owner, 4 Nov 2026) and nothing here reaches a broker order.

export type ExitKind = "shares" | "future" | "hedged";
export type ExitMethod = "atr_trail" | "yours" | "put_floor" | "call_cap" | "none";
export type ExitStatus = "OK" | "NEAR" | "HIT" | "FLOOR" | "NO_STOP";

export interface ExitLeg { instrument: string | null; type: string | null; quantity: number | null; avg: number | null; expiry: string | null; strike: number | null }
export interface ExitHistory { day: string | null; stop: number | null; candidate: number | null; close: number | null; atr: number | null; moved: boolean | null; reason: string | null }

export interface ExitPosition {
  key: string;
  accountId: string | null;
  account: string | null;
  underlying: string;
  label: string;
  kind: ExitKind | null;
  side: "long" | "short" | null;
  legs: ExitLeg[];
  price: number | null;
  /** "kite_live" | "kite_close" | "eod" (anything else is shown as given). */
  priceSource: string | null;
  priceAsOf: string | null;
  stop: number | null;
  method: ExitMethod;
  stopDay: string | null;
  /** False: worked out for this answer, not yet stored by the watcher. */
  stored: boolean | null;
  ruleStop: number | null;
  atr: number | null;
  atrPct: number | null;
  distancePct: number | null;
  distanceAtr: number | null;
  status: ExitStatus;
  why: string | null;
  /** ₹, gross, from the average cost; negative = a gain locked in. */
  lossAtStop: number | null;
  lossBasis: string | null;
  support: number | null;
  note: string | null;
  history: ExitHistory[];
  /** The user's own levels for the underlying as stored (positions workspace), null when none. Sent back whole when the stop
   *  changes: PUT /api/positions/{U}/levels replaces the document, so leaving them out would wipe a target or a trail. */
  own: OwnLevels | null;
}

export interface OwnLevels {
  stop: number | null;
  target: number | null;
  trailPct: number | null;
}

export interface ExitAlert {
  id: string;
  at: string | null;
  day: string | null;
  kind: string;
  severity: AlertSeverity;
  key: string | null;
  underlying: string | null;
  account: string | null;
  text: string;
  price: number | null;
  level: number | null;
  source: string | null;
  seen: boolean;
}

export interface ExitWatch {
  asOf: string | null;
  session: string | null;
  rule: { id: string | null; text: string | null };
  watcher: { enabled: boolean | null; liveRoundAt: string | null; eodDay: string | null; feedWhy: string | null };
  positions: ExitPosition[];
  notWatched: Array<{ label: string; why: string | null }>;
  /** Newest first. */
  alerts: ExitAlert[];
  unseen: number;
  accounts: Array<{ accountId: string; name: string | null; state: string | null }>;
}

const EXIT_KINDS: readonly string[] = ["shares", "future", "hedged"];
const EXIT_METHODS: readonly string[] = ["atr_trail", "yours", "put_floor", "call_cap", "none"];
const EXIT_STATUSES: readonly string[] = ["OK", "NEAR", "HIT", "FLOOR", "NO_STOP"];

function readExitPosition(v: unknown): ExitPosition | null {
  const p = rec(v);
  const key = str(p.key);
  const underlying = str(p.underlying);
  if (!key || !underlying) return null;
  const kind = str(p.kind);
  const side = str(p.side);
  const method = str(p.method);
  const status = str(p.status);
  return {
    key, accountId: str(p.account_id), account: str(p.account), underlying, label: str(p.label) ?? underlying,
    kind: kind && EXIT_KINDS.includes(kind) ? (kind as ExitKind) : null,
    side: side === "long" || side === "short" ? side : null,
    legs: arr(p.legs).map((x) => {
      const l = rec(x);
      return { instrument: str(l.instrument), type: str(l.type), quantity: num(l.quantity), avg: num(l.avg), expiry: str(l.expiry), strike: num(l.strike) };
    }),
    price: num(p.price), priceSource: str(p.price_source), priceAsOf: str(p.price_as_of),
    stop: num(p.stop), method: method && EXIT_METHODS.includes(method) ? (method as ExitMethod) : "none", stopDay: str(p.stop_day), stored: bool(p.stored),
    ruleStop: num(p.rule_stop), atr: num(p.atr), atrPct: num(p.atr_pct), distancePct: num(p.distance_pct), distanceAtr: num(p.distance_atr),
    // An unknown status is never shown as OK.
    status: status && EXIT_STATUSES.includes(status) ? (status as ExitStatus) : "NO_STOP",
    why: str(p.why), lossAtStop: num(p.loss_at_stop), lossBasis: str(p.loss_basis), support: num(p.support), note: str(p.note),
    history: arr(p.history).map((x) => {
      const h = rec(x);
      return { day: str(h.day), stop: num(h.stop), candidate: num(h.candidate), close: num(h.close), atr: num(h.atr), moved: bool(h.moved), reason: str(h.reason) };
    }),
    own: p.own && typeof p.own === "object" ? { stop: num(rec(p.own).stop), target: num(rec(p.own).target), trailPct: num(rec(p.own).trail_pct) } : null,
  };
}

function readExitAlert(v: unknown): ExitAlert | null {
  const a = rec(v);
  const id = str(a.id);
  const text = str(a.text);
  if (!id || !text) return null;
  const sev = str(a.severity);
  return {
    id, at: str(a.at), day: str(a.day), kind: str(a.kind) ?? "ALERT",
    severity: sev && SEVERITIES.includes(sev) ? (sev as AlertSeverity) : "WARNING",
    key: str(a.key), underlying: str(a.underlying), account: str(a.account), text, price: num(a.price), level: num(a.level), source: str(a.source),
    // Only an explicit true is seen: an alert never goes quiet on a missing flag.
    seen: a.seen === true,
  };
}

/** GET /api/desk/pnl/exits: the body as the screen uses it. A body without a positions list is a contract error. */
export function readExits(body: unknown): ExitWatch {
  const b = rec(body);
  if (!Array.isArray(b.positions)) throw ApiError.contractDrift("desk.pnl.exits: no positions list");
  const rule = rec(b.rule);
  const w = rec(b.watcher);
  const alerts = arr(b.alerts).map(readExitAlert).filter((x): x is ExitAlert => !!x)
    .sort((x, y) => (y.at ?? "").localeCompare(x.at ?? ""));
  const unseen = num(b.unseen);
  return {
    asOf: str(b.as_of), session: str(b.session),
    rule: { id: str(rule.id), text: str(rule.text) },
    watcher: { enabled: bool(w.enabled), liveRoundAt: str(w.live_round_at), eodDay: str(w.eod_day), feedWhy: str(w.feed_why) },
    positions: (b.positions as unknown[]).map(readExitPosition).filter((x): x is ExitPosition => !!x),
    notWatched: arr(b.not_watched).flatMap((x) => { const n = rec(x); const label = str(n.label); return label ? [{ label, why: str(n.why) }] : []; }),
    alerts,
    unseen: unseen ?? alerts.filter((a) => !a.seen).length,
    accounts: arr(b.accounts).flatMap((x) => { const a = rec(x); const id = str(a.account_id); return id ? [{ accountId: id, name: str(a.name), state: str(a.state) }] : []; }),
  };
}

export const EXITS_KEY = ["copilot", "desk", "pnl-exits"] as const;

/** GET /api/desk/pnl/exits, every 30 s while the page is open (paused in a hidden tab). */
export function useExitWatch(account: string, enabled: boolean) {
  const profile = useImpersonationStore((st) => st.profileId);
  return useQuery<ExitWatch>({
    queryKey: [...EXITS_KEY, account, profile ?? "self"],
    enabled,
    staleTime: 15_000,
    retry: (count: number, e: unknown) => !(e instanceof ApiError && e.status === 404) && retry(count, e),
    refetchInterval: 30_000,
    refetchIntervalInBackground: false,
    queryFn: async ({ signal }) => readExits((await http({ path: "/api/desk/pnl/exits", query: { account }, signal, noRetry: true, timeoutMs: 30_000 })).data),
  });
}

/** POST /api/desk/pnl/exits/seen — the given alerts, or (no ids) every unseen one of the caller's. */
export function useMarkExitsSeen() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (ids?: string[]): Promise<number | null> => {
      const res = await http({ method: "POST", path: "/api/desk/pnl/exits/seen", body: ids && ids.length ? { ids } : {}, noRetry: true, timeoutMs: 20_000 });
      return num(rec(res.data).marked);
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: EXITS_KEY }),
  });
}

/** PUT /api/positions/{U}/levels {stop}: the user's own stop loss for that underlying (every account), in place of the rule. */
export function useSetOwnStop() {
  const qc = useQueryClient();
  return useMutation({
    // The PUT replaces the whole document, so the target and trail the user already has are sent back unchanged.
    mutationFn: async ({ underlying, stop, own }: { underlying: string; stop: number; own: OwnLevels | null }) => {
      const body = { stop, target: own?.target ?? null, trail_pct: own?.trailPct ?? null };
      const res = await http({ method: "PUT", path: `/api/positions/${encodeURIComponent(underlying)}/levels`, body, noRetry: true, timeoutMs: 20_000 });
      return { stop: num(rec(res.data).stop) };
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: EXITS_KEY }),
  });
}

/** DELETE /api/positions/{U}/levels — back to the rule; 404 levels_not_found means there was nothing to clear. */
export function useClearOwnStop() {
  const qc = useQueryClient();
  return useMutation({
    // Back to the rule = no own stop and no own trail (both set the stop). A target the user keeps stays: then the document is
    // rewritten with only the target, else it is deleted.
    mutationFn: async ({ underlying, own }: { underlying: string; own: OwnLevels | null }) => {
      try {
        if (own?.target != null) {
          await http({ method: "PUT", path: `/api/positions/${encodeURIComponent(underlying)}/levels`,
            body: { stop: null, target: own.target, trail_pct: null }, noRetry: true, timeoutMs: 20_000 });
        } else {
          await http({ method: "DELETE", path: `/api/positions/${encodeURIComponent(underlying)}/levels`, noRetry: true, timeoutMs: 20_000 });
        }
      } catch (e) {
        if (!(e instanceof ApiError && e.status === 404)) throw e;
      }
      return true;
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: EXITS_KEY }),
  });
}
