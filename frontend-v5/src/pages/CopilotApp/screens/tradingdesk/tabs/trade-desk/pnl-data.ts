/**
 * Trade Desk › Paper Trading › P&L dashboard — the reads (docs/paper_pnl_dashboard/DESIGN.md; owner decisions of 4 Nov 2026:
 * a third Paper Trading sub-view, standard trading words on this screen, PAPER ONLY in this release).
 *
 *   GET /api/desk/pnl?segment=&period=&from=&to=      one snapshot: summary, positions (legs flat), strategies, pending
 *                                                     entries, closed trades for the period, risk + alerts, analytics
 *                                                     (backend/routes/desk_pnl.py; READ-ONLY — unlike GET /api/desk/paper-trades
 *                                                     it applies no exit, so it may be read every few seconds)
 *   GET /api/desk/pnl/stream?<same filters>           server-sent events: `snapshot` with the same body every few seconds in
 *                                                     session; a `: heartbeat` comment; the server closes it after 30 min
 *   GET /api/desk/pnl/timeseries?interval=5m|15m      the open book's P&L through today's session, from Kite candles
 *
 * Transport (usePaperPnl): the stream first; polling GET /api/desk/pnl (3 s in session, 30 s otherwise) when EventSource is
 * missing, the session rides a bearer token or an advisor's X-Active-Profile (EventSource cannot send headers), or the stream
 * fails twice — then the stream is tried again after five minutes. Paused while the tab is hidden. Every snapshot carries a
 * server `sequence`; one not newer than the last applied is dropped, so a duplicate or a late answer never rolls the screen
 * back. Each snapshot is the whole picture, so a gap needs no repair.
 *
 * Reads trust nothing: a missing or non-numeric figure is null (the screen shows "—"), never 0; a body without `summary` or
 * `positions` is a contract error. Nothing here writes anything or reaches a broker.
 */
import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { http } from "@/services/api/http";
import { apiConfig } from "@/services/api/config";
import { ApiError } from "@/services/api/errors";
import { getAuthToken } from "@/services/api/auth-token";
import { useImpersonationStore } from "@/stores/impersonation.store";
import { num } from "../../desk-data";

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

export interface PnlFilters {
  segment: PnlSegment;
  period: PnlPeriod;
  /** YYYY-MM-DD, only with period CUSTOM. */
  from?: string | null;
  to?: string | null;
}

/** The query the routes take (DESIGN.md "API"). A CUSTOM period without both days is sent as ALL. */
export function pnlQuery(f: PnlFilters): Record<string, string> {
  const q: Record<string, string> = { segment: f.segment, period: f.period };
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
}

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
  mode: string;
  currency: string;
  asOf: string | null;
  sequence: number | null;
  filters: { segment: string | null; period: string | null; from: string | null; to: string | null };
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
  const notes: Record<string, string> = {};
  for (const [k, v] of Object.entries(rec(b.notes))) {
    const t = str(v);
    if (t) notes[k] = t;
  }
  return {
    mode: str(b.mode) ?? "PAPER",
    currency: str(b.currency) ?? "INR",
    asOf: str(b.as_of),
    sequence: num(b.sequence),
    filters: { segment: str(f.segment), period: str(f.period), from: str(f.from), to: str(f.to) },
    market: { session: str(m.session), feed: str(m.feed), feedAgeSeconds: num(m.feed_age_seconds), staleAfterSeconds: num(m.stale_after_seconds), priceRule: str(m.price_rule), day: str(m.day), notes: strings(m.notes) },
    summary: {
      realized: num(s.realized_pnl), unrealized: num(s.unrealized_pnl), gross: num(s.gross_pnl), chargesBooked: num(s.charges_booked),
      chargesEstimated: num(s.charges_estimated), net: num(s.net_pnl), dayPnl: num(s.day_pnl), allocatedCapital: num(s.allocated_capital),
      returnPct: num(s.return_pct), openPositions: num(s.open_positions), openLegs: num(s.open_legs), winningPositions: num(s.winning_positions), losingPositions: num(s.losing_positions),
      closedTrades: num(s.closed_trades), pendingEntries: num(s.pending_entries), unpricedPositions: num(s.unpriced_positions),
      stalePositions: num(s.stale_positions), complete: bool(s.complete),
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

/** The dashboard's snapshot, kept current by the stream or by polling (see the header). */
export function usePaperPnl(filters: PnlFilters): PnlFeedState & { retry: () => void } {
  const profile = useImpersonationStore((st) => st.profileId);
  const query = pnlQuery(filters);
  const key = `${new URLSearchParams(query).toString()}|${profile ?? ""}`;
  const [state, setState] = useState<PnlFeedState>({ data: null, error: null, connection: "connecting", transport: null, receivedAt: null, dropped: 0, problem: null });
  const feed = useRef<PnlFeed | null>(null);
  const last = useRef<PnlSnapshot | null>(null);
  last.current = state.data;

  useEffect(() => {
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
  }, [key]);

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

export function usePnlTimeseries(interval: PnlInterval, sessionOpen: boolean) {
  const profile = useImpersonationStore((st) => st.profileId);
  return useQuery<PnlTimeseries>({
    queryKey: ["copilot", "desk", "pnl-timeseries", interval, profile ?? "self"],
    staleTime: 30_000,
    retry,
    refetchInterval: sessionOpen ? 60_000 : false,
    refetchIntervalInBackground: false,
    queryFn: async ({ signal }) => readTimeseries((await http({ path: "/api/desk/pnl/timeseries", query: { interval }, signal, noRetry: true, timeoutMs: 30_000 })).data),
  });
}

// ── CSV export ───────────────────────────────────────────────────────────

const CSV_COLUMNS: Array<[string, (p: PnlPosition) => unknown]> = [
  ["mode", (p) => p.mode], ["account", (p) => p.account], ["instrument", (p) => p.instrument], ["strategy", (p) => p.strategyName],
  ["segment", (p) => p.segment], ["side", (p) => p.side], ["net_quantity", (p) => p.netQuantity], ["avg_price", (p) => p.avgPrice],
  ["ltp", (p) => p.ltp], ["price_status", (p) => p.priceStatus], ["price_at", (p) => p.priceAt], ["price_day", (p) => p.priceDay], ["invested_value", (p) => p.investedValue],
  ["unrealized_pnl", (p) => p.unrealized], ["realized_pnl", (p) => p.realized], ["charges_estimated", (p) => p.chargesEstimated],
  ["net_pnl", (p) => p.net], ["day_pnl", (p) => p.dayPnl], ["stop_loss", (p) => p.stopLoss], ["target", (p) => p.target],
  ["distance_to_stop_pct", (p) => p.distanceToStopPct], ["status", (p) => p.status], ["opened_at", (p) => p.openedAt], ["position_id", (p) => p.positionId],
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
