/**
 * One-screen Copilot app (/v5/app) — Trade Desk › Paper Trading › 05 Real-time P&L (Paper Trading v2, the owner's design of
 * 5 Nov 2026, docs/scanner_paper_trading/UI_DESIGN_V2.md §2.05 and §5). Reworked from the P&L dashboard v2 spec: the
 * dashboard was replaced, so every behaviour it guarded that still exists is tested here on the new view (paper/Pnl.tsx);
 * the detail of a row (pnl-detail.tsx) is the same component, so its cases are unchanged.
 *
 * Kept (re-pointed): the sub-view and its URL (the old Live desk URL lands here), the read-only snapshot route (no
 * paper-trades read), Paper / Live reaching the route and the curve, the row detail (breakdown, fills, chart levels, journal at
 * entry, the trade curve), Modify risk, Simulate exit (desk close; the whole structure; the scanner route), Live read-only,
 * stream → polling with stale answers dropped and the stream path, a missing price never 0, a failing route and a contract
 * error, Live unavailable, the closed trades' period, the waiting entries, the route's notes, 390 px without a sideways scroll.
 * Dropped with the old layout (the design has none of them): the header's title / feed pill / account pills / IST clock and
 * Pause-Resume (V2-24), the account and segment selects and the search (V2-20 part), the hero's label and gross line, the
 * Paper and Live mode cards, the 11-column table's Status / Risk-used columns and the sort chips, the risk monitor, the
 * supervisor and the footer (V2-19 part), CSV export (TC-036), the by-segment strip and the analytics block (TC-034 part;
 * analytics is 06 Strategy analytics now), and "no buy / sell anywhere" (the design's F&O cards label their legs BUY / SELL).
 *
 * Every /api/* answer below is an inline MOCK — not real data — in the shape DESIGN.md gives for GET /api/desk/pnl (mode,
 * account, accounts, modes, LIVE rows), its stream, /timeseries (with mode and trade), /journal/{id}, the levels PATCH and the
 * paper close, plus GET /api/v1/paper/fno-structures (UI_DESIGN_V2 §7). Symbols, prices and P&L are made up. Mocked APIs,
 * production build.
 */
import { test, expect, type Page, type Route } from "@playwright/test";
import fs from "fs";
import path from "path";
import { mockApi, mockSingleRoute } from "../helpers/api-mock";

const json = (route: Route, body: unknown, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
const clone = <T,>(x: T): T => JSON.parse(JSON.stringify(x));
const DESK = "/v5/app/trader/desk";
const PNL = `${DESK}?tab=trade&view=paper&sub=pnl`;
const SLOW = { timeout: 15_000 };
const SHOTS = process.env.PNL_SHOTS || "";

// ── MOCK — not real data: positions (DESIGN.md v2 "positions") ───────────────────────────────────────────────────────────
type Row = Record<string, unknown>;
const ex = (id: string, side: string, quantity: number, price: number, kind = "fill") => ({ execution_id: id, side, quantity, price, at: "2026-10-28T02:24:09+00:00", kind });
const paper = (o: Row): Row => ({
  trade_id: null, leg_index: null, strategy_id: null, strategy_name: null, mode: "PAPER", account: "Paper account", account_id: "paper", lots: null, lot_size: null,
  realized_pnl: 0, opened_at: "2026-10-28T02:24:09+00:00", expiry: null, risk_used_pct: null, price_day: "2026-11-04", broker_pnl: null, broker_read_at: null,
  product: null, editable_levels: false, pending_levels: null, executions_note: null, contract_problem: null, ...o,
});
const live = (o: Row): Row => ({
  ...paper(o), mode: "LIVE", account: "Zerodha", account_id: "zr-1", realized_pnl: null, stop_loss: null, target: null, distance_to_stop_pct: null,
  broker_read_at: "2026-11-04T10:29:30+05:30", executions_note: "MOCK: Today's fills from the broker's trade book; earlier fills are not sent by brokers.", ...o,
});
const ICICI = paper({
  position_id: "pt-icici", trade_id: "pt-icici", instrument: "ICICIBANK", symbol: "ICICIBANK", underlying: "ICICIBANK", segment: "EQUITY", side: "LONG",
  net_quantity: 35, avg_price: 1413.21, ltp: 1431.5, prev_close: 1420.1, price_status: "LIVE", price_source: "Kite live", price_at: "2026-11-04T10:30:01+05:30",
  price_age_seconds: 0.8, invested_value: 49462.35, unrealized_pnl: 640.15, gross_pnl: 640.15, charges_estimated: 40.2, net_pnl: 599.95, day_pnl: 399,
  return_pct: 1.21, stop_loss: 1374.9, target: 1489.83, distance_to_stop_pct: 3.95, risk_used_pct: 0, status: "ACTIVE", exposure_rs: 50102.5,
  editable_levels: true, executions: [ex("pt-icici:open", "BUY", 35, 1413.21)],
});
const COFORGE = paper({
  position_id: "pt-cof", trade_id: "pt-cof", instrument: "COFORGE", symbol: "COFORGE", underlying: "COFORGE", segment: "EQUITY", side: "LONG",
  net_quantity: 18, avg_price: 2010.81, ltp: 1900, prev_close: 1921, price_status: "DELAYED", price_source: "Kite live (no tick since 10:21:40)",
  price_at: "2026-11-04T10:21:40+05:30", price_age_seconds: 501, invested_value: 36194.58, unrealized_pnl: -1994.58, gross_pnl: -1994.58,
  charges_estimated: 35.1, net_pnl: -2029.68, day_pnl: -378, return_pct: -5.61, stop_loss: 1904.91, target: 2222.61, distance_to_stop_pct: -0.26,
  risk_used_pct: 100, status: "STOP_LOSS_HIT", exposure_rs: 34200, editable_levels: true,
  pending_levels: { stop_loss: 1850, target: 2222.61, from_session: "2026-11-05", version: 2 }, executions: [ex("pt-cof:open", "BUY", 18, 2010.81)],
});
const LEG0 = paper({
  position_id: "st-1:0", trade_id: "st-1", leg_index: 0, strategy_id: "st-1", strategy_name: "Bull call spread", instrument: "NIFTY 25 Nov 25000 CE",
  symbol: "NIFTY25NOV25000CE", underlying: "NIFTY", segment: "OPTIONS", side: "LONG", net_quantity: 75, lots: 1, lot_size: 75, avg_price: 180, ltp: 222,
  prev_close: 205, price_status: "LIVE", price_source: "Kite REST quote", price_at: "2026-11-04T10:30:00+05:30", price_age_seconds: 1.4,
  invested_value: 13500, unrealized_pnl: 3150, gross_pnl: 3150, charges_estimated: 60, net_pnl: 3090, day_pnl: 1275, return_pct: 22.89,
  stop_loss: null, target: null, distance_to_stop_pct: null, status: "ACTIVE", expiry: "2026-11-25", exposure_rs: 16650, executions: [ex("st-1:0:open", "BUY", 75, 180)],
});
const LEG1 = paper({
  position_id: "st-1:1", trade_id: "st-1", leg_index: 1, strategy_id: "st-1", strategy_name: "Bull call spread", instrument: "NIFTY 25 Nov 25200 CE",
  symbol: "NIFTY25NOV25200CE", underlying: "NIFTY", segment: "OPTIONS", side: "SHORT", net_quantity: -75, lots: 1, lot_size: 75, avg_price: 95, ltp: 120,
  prev_close: 110, price_status: "DELAYED", price_source: "Kite REST quote (last trade in the previous session)", price_at: "2026-11-03T15:29:58+05:30",
  price_age_seconds: 68402, price_day: "2026-11-03", invested_value: -7125, unrealized_pnl: -1875, gross_pnl: -1875, charges_estimated: 40, net_pnl: -1915, day_pnl: -750, return_pct: null,
  stop_loss: null, target: null, distance_to_stop_pct: null, status: "ACTIVE", expiry: "2026-11-25", exposure_rs: 9000, executions: [ex("st-1:1:open", "SELL", 75, 95)],
});
const INFY = live({
  position_id: "zr-1:INFY", trade_id: null, instrument: "INFY", symbol: "INFY", underlying: "INFY", segment: "EQUITY", side: "LONG", net_quantity: 300,
  avg_price: 1590, ltp: 1618, prev_close: 1600, price_status: "LIVE", price_source: "Kite live", price_at: "2026-11-04T10:30:01+05:30", price_age_seconds: 0.6,
  invested_value: 477000, unrealized_pnl: 8400, gross_pnl: 8400, charges_estimated: 180, net_pnl: 8220, day_pnl: 5400, return_pct: 1.72,
  status: "ACTIVE", exposure_rs: 485400, broker_pnl: 9900, product: "delivery", executions: [ex("zr-1:INFY:t1", "BUY", 300, 1590)],
});
const NFUT = live({
  position_id: "zr-1:NIFTY25NOVFUT", trade_id: null, instrument: "NIFTY 25 Nov 2026 FUT", symbol: "NIFTY25NOVFUT", underlying: "NIFTY", segment: "FUTURES",
  side: "SHORT", net_quantity: -75, lots: 1, lot_size: 75, avg_price: 25880, ltp: 25925, prev_close: 25900, price_status: "LIVE", price_source: "Kite live",
  price_at: "2026-11-04T10:30:00+05:30", price_age_seconds: 1.1, invested_value: -1941000, unrealized_pnl: -3375, gross_pnl: -3375, charges_estimated: 140,
  net_pnl: -3515, day_pnl: -1875, return_pct: -0.18, status: "ACTIVE", expiry: "2026-11-25", exposure_rs: 1944375, broker_pnl: -3375, product: "carryforward", executions: [],
});
const ROWS = [ICICI, COFORGE, LEG0, LEG1, INFY, NFUT];
const STRATEGY = {
  strategy_id: "st-1", name: "Bull call spread", summary: "Bull call spread 25000/25200 · 25 Nov · 1 lot", opened_at: "2026-11-02T04:00:00+00:00", risk_note: null, underlying: "NIFTY", direction: "bullish", status: "OPEN", legs: ["st-1:0", "st-1:1"],
  underlying_ltp: 25890, stop_underlying: 25400, target_underlying: 26300, entry_net_premium: -6375, current_value: 7650, unrealized_pnl: 1275,
  charges_estimated: 100, net_pnl: 1175, capital_at_risk: 6375, complete: true,
};
// MOCK — not real data: GET /api/v1/paper/fno-structures (UI_DESIGN_V2 §7), the one structure above
const FNO = {
  structures: [{ id: "st-1", name: "Bull call spread", underlying: "NIFTY", underlying_ltp: 25890, expiry: "2026-11-25", days_to_expiry: 21, lots: 1, lot_size: 75, status: "filled", hedged: true,
    max_loss_rs: 6375, max_profit_rs: 8625, profit_unbounded: false, breakevens: [25085], net: { delta: 21.4, gamma: 0.0012, theta_rs_day: -310.5, vega_rs_pt: 420 }, margin_rs: 6375, pnl_rs: 1275,
    legs: [{ side: "BUY", contract: "NIFTY 25 Nov 25000 CE", entry: 180, ltp: 222, filled_qty: 75, qty: 75, pnl_rs: 3150, pending: false },
      { side: "SELL", contract: "NIFTY 25 Nov 25200 CE", entry: 95, ltp: 120, filled_qty: 75, qty: 75, pnl_rs: -1875, pending: false }], scenarios: [], notes: [] }],
  totals: { margin_rs: 6375, max_loss_rs: 6375, net: { delta: 21.4, gamma: 0.0012, theta_rs_day: -310.5, vega_rs_pt: 420 } }, limits: {}, basis: "MOCK", notes: [],
};
const CLOSED = { trade_id: "pt-axis", instrument: "AXISBANK", segment: "EQUITY", closed_at: "2026-11-03T15:30:00+00:00", exit_session: "2026-11-03",
  exit_reason: "stop", realized_pnl: -3200, charges: 160.1, net_pnl: -3360.1 };
const ALERTS = [
  { severity: "INFO", type: "EXPIRY", position_id: "st-1:0", symbol: "NIFTY", message: "MOCK: Expires on 25 Nov (15 sessions).", observed: null, threshold: null },
  { severity: "CRITICAL", type: "STOP_LOSS_HIT", position_id: "pt-cof", symbol: "COFORGE", message: "MOCK: Price is below the stop loss. The paper exit is decided at the evening check on today's bar.", observed: 1900, threshold: 1904.91 },
  { severity: "WARNING", type: "STALE_PRICE", position_id: "pt-cof", symbol: "COFORGE", message: "MOCK: No tick since 10:21:40; P&L is at that price.", observed: null, threshold: null },
];
const ACCOUNTS = [
  { account_id: "paper", name: "Paper account", mode: "PAPER", broker: null, state: "OK", state_note: null, read_at: "2026-11-04T10:30:01+05:30", capital: 10000000, capital_basis: "MOCK: paper starting capital", open_positions: 3, net_pnl: -254.73 },
  { account_id: "zr-1", name: "Zerodha", mode: "LIVE", broker: "zerodha", state: "OK", state_note: null, read_at: "2026-11-04T10:29:30+05:30", capital: null, capital_basis: "MOCK: not read from brokers", open_positions: 2, net_pnl: 4705 },
  { account_id: "ic-1", name: "ICICI Direct", mode: "LIVE", broker: "icici", state: "SIGN_IN", state_note: "MOCK: Session expired: sign in to ICICI Direct again.", read_at: null, capital: null, capital_basis: null, open_positions: 0, net_pnl: null },
];
const MODES = {
  PAPER: { realized_pnl: 0, unrealized_pnl: -79.43, gross_pnl: -79.43, charges: 175.3, net_pnl: -254.73, capital: 10000000, return_pct: -0.0025, open_positions: 3, complete: true, available: true, note: null },
  LIVE: { realized_pnl: null, unrealized_pnl: 5025, gross_pnl: 5025, charges: 320, net_pnl: 4705, capital: null, return_pct: null, open_positions: 2, complete: true, available: true, note: null },
};

const known = (rows: Row[], k: string): number | null => {
  const v = rows.map((r) => r[k]).filter((x): x is number => typeof x === "number");
  return v.length ? Math.round(v.reduce((a, b) => a + b, 0) * 100) / 100 : null;
};

function snapshot(q: URLSearchParams, seq = 1762232401000, patch?: (s: Record<string, unknown>) => void) {
  const segment = q.get("segment") ?? "ALL";
  const period = q.get("period") ?? "TODAY";
  const mode = q.get("mode") ?? "ALL";
  const account = q.get("account") ?? "ALL";
  const weekly = period === "1W" || period === "1M" || period === "ALL";
  const rows = ROWS.filter((r) => (mode === "ALL" || r.mode === mode) && (account === "ALL" || r.account_id === account) && (segment === "ALL" || r.segment === segment));
  const paperRows = rows.filter((r) => r.mode === "PAPER");
  const realized = weekly && paperRows.length ? -3200 : paperRows.length ? 0 : null;
  const net = known(rows, "net_pnl");
  const s: Record<string, unknown> = {
    mode, currency: "INR", as_of: "2026-11-04T10:30:01+05:30", sequence: seq,
    filters: { segment, period, from: weekly ? "2026-10-29" : "2026-11-04", to: "2026-11-04", mode, account },
    market: { session: "open", feed: "live", feed_age_seconds: 1.2, stale_after_seconds: 75, day: "2026-11-04",
      price_rule: "MOCK: live Kite price in session; Kite close after 15:30 until the exchange's end-of-day file; else the ledger's end-of-day mark.", notes: [] },
    accounts: clone(ACCOUNTS), modes: clone(MODES),
    summary: {
      realized_pnl: realized, unrealized_pnl: known(rows, "unrealized_pnl"), gross_pnl: known(rows, "gross_pnl"), charges_booked: weekly && paperRows.length ? 160.1 : 0,
      charges_estimated: known(rows, "charges_estimated"), net_pnl: net == null ? null : Math.round((net + (weekly && paperRows.length ? -3360.1 : 0)) * 100) / 100,
      day_pnl: known(rows, "day_pnl"), allocated_capital: mode === "PAPER" ? 10000000 : null, return_pct: mode === "PAPER" && net != null ? (net / 10000000) * 100 : null,
      open_positions: new Set(rows.map((r) => (r.strategy_id as string | null) ?? r.position_id)).size, open_legs: rows.length,
      winning_positions: rows.filter((r) => (r.net_pnl as number) > 0).length, losing_positions: rows.filter((r) => (r.net_pnl as number) < 0).length,
      closed_trades: weekly && paperRows.length ? 1 : 0, pending_entries: paperRows.length ? 1 : 0, unpriced_positions: 0,
      stale_positions: rows.filter((r) => r.price_status === "DELAYED").length, complete: true, exposure_rs: known(rows, "exposure_rs"),
      capital_basis: mode === "PAPER" ? "MOCK: paper starting capital" : "MOCK: broker capital is not read, so no return is computed",
    },
    by_segment: [{ segment: "EQUITY", open_positions: 3, realized_pnl: realized, unrealized_pnl: 7045.57, charges: 255.3, net_pnl: 6790.27 }],
    positions: clone(rows),
    strategies: rows.some((r) => r.strategy_id === "st-1") ? [clone(STRATEGY)] : [],
    pending_entries: paperRows.length ? [{ trade_id: "pt-pend", symbol: "HDFCBANK", entry_rule: "break_above", level: 1655, ltp: 1641.2 }] : [],
    closed: weekly && paperRows.length ? [CLOSED] : [],
    closed_total: weekly && paperRows.length ? 1 : 0, closed_partial: false, marks_error: null,
    risk: { capital: { starting: 10000000, cash: 10000000, blocked: 123887.21, available: 9876112.79, utilisation_pct: 1.24, basis: "capital at risk, not exchange margin" },
      open_risk_rs: -2100, open_risk_limit_rs: 300000, strategies_capital_at_risk_rs: 6375, near_stop_pct: 1, daily_loss_limit_rs: 200000, daily_loss_used_pct: 12,
      alerts: ALERTS.filter((a) => rows.some((r) => r.position_id === a.position_id)), margin: { used_pct: 1.24, basis: "MOCK: paper: capital blocked by open trades, not exchange margin" },
      exposure_rs: known(rows, "exposure_rs") },
    analytics: { trades: weekly ? 1 : 0, wins: 0, losses: weekly ? 1 : 0, win_rate_pct: weekly ? 0 : null, profit_factor: null, avg_win: null,
      avg_loss: weekly ? -3360.1 : null, max_drawdown_rs: weekly ? -3360.1 : null, max_drawdown_pct: weekly ? 0.0336 : null,
      daily: weekly ? [{ date: "2026-11-03", net_pnl: -3360.1 }] : [] },
    reconciliation: { checked: weekly ? 1 : 0, mismatches: [] },
    notes: { display_only: "MOCK: live prices are for display; the ledger decides exits on end-of-day bars.", charges: "MOCK: charges are the desk cost card's.",
      capital: "MOCK: return % = net P&L ÷ starting capital." },
  };
  patch?.(s);
  return s;
}

// ── MOCK — not real data: /timeseries, /journal, /live-chart ─────────────────────────────────────────────────────────────
const TIMESERIES = {
  date: "2026-11-04", interval: "5m", baseline_gross: -500, positions_used: 5,
  points: ["09:15", "09:20", "09:25", "09:30", "09:35", "10:30"].map((t, i) => {
    const g = [-500, 820, 2150, 3940, 4810, 5000][i];
    return { t: `2026-11-04T${t}:00+05:30`, unrealized_pnl: g, realized_pnl: 0, gross_pnl: g, net_pnl: g - 495.3, change_since_baseline: g + 500 };
  }),
  missing: [{ position_id: "st-1:1", reason: "MOCK: no candles for NIFTY 25 Nov 25200 CE yet" }],
  basis: "MOCK: Kite 5-minute candles, carried forward where a contract did not trade.", partial: true,
};
const tradeCurve = (id: string) => ({
  trade: id, mode: id.startsWith("zr-1") ? "LIVE" : "PAPER", from: id === "pt-icici" ? "2026-10-28T09:15:00+05:30" : "2026-11-04T09:15:00+05:30", since_entry: id === "pt-icici",
  date: "2026-11-04", interval: "15m", charges_estimated: 40.2, notes: id === "pt-icici" ? [] : ["MOCK: today's session only."],
  points: [0, 1, 2, 3, 4].map((i) => ({ t: `2026-11-04T${String(9 + i).padStart(2, "0")}:15:00+05:30`, gross_pnl: [-300, 120, 400, 520, 640.15][i], net_pnl: [-340.2, 79.8, 359.8, 479.8, 599.95][i] })),
  basis: "MOCK: Kite 15-minute candles of the trade's instrument.", missing: [],
});
const JOURNAL_FOUND = {
  trade_id: "pt-icici", symbol: "ICICIBANK", entry_day: "2026-10-28", found: true, why: null,
  signal: { kind: "strong", first_strong: "2026-10-28T09:42:00+05:30", score: 82, parts: { quality: 24, trend: 16, reason: 14, size: 10, participation: 6, penalty: -5 },
    reasons: ["MOCK RSI(14) 58", "MOCK Above 6 of 8 daily averages", "MOCK Long build-up · price vs OI"], penalties: ["MOCK steep one-day jump"],
    lists: [{ id: "w1", title: "MOCK Breakout" }], entry: 1410, stop_loss: 1374.9, target_1: 1489.83, target_2: 1559.6, rr_1: 2, rr_2: 4,
    trend_exit: "MOCK Trend exit: a daily close below the 20-day average ends the trade.", plan_ok: true, plan_note: null, rules: "scan-plan-v3" },
  trade: { source: { kind: "scan", bucket: "breakout", signal_date: "2026-10-28" }, rationale: "MOCK rationale", note: null, opened_at: "2026-10-28T09:45:00+05:30", entry_rule: "at_once", entry_session: "2026-10-28" },
};
const JOURNAL_NONE = { trade_id: "pt-cof", symbol: "COFORGE", entry_day: "2026-10-28", found: false, why: "MOCK: No scan signal for COFORGE on 28 Oct.", signal: null,
  trade: { source: null, rationale: null, note: null, opened_at: "2026-10-28T09:45:00+05:30", entry_rule: "at_once", entry_session: "2026-10-28" } };
// 15-minute bars around each symbol's own price (ICICIBANK 1,396 … 1,434: its target 1,489.83 lies outside that range).
const BASE: Record<string, number> = { ICICIBANK: 1400, COFORGE: 1890, INFY: 1590, NIFTY: 25800 };
const bars = (base: number) => Array.from({ length: 30 }, (_, i) => {
  const t = new Date(Date.UTC(2026, 10, 3, 3, 45 + 15 * i)).toISOString().replace(".000Z", "+00:00");
  const o = base + i, c = base + 1 + i;
  return [t, o, c + 4, o - 4, c, 120000];
});
const LIVE_CHART = (sym: string, BARS = bars(BASE[sym] ?? 1000)) => ({
  symbol: sym, as_of: "2026-11-04T10:30:01+05:30",
  timeframe: { interval: "15m", label: "15 MIN", source: "kite", adjusted: false, reason: null, live_merged: true, note: "MOCK" },
  bars: BARS, ema20: BARS.map((_, i) => (i < 19 ? null : 1420)), rvol: BARS.map(() => 1),
  last: { price: 1431.5, at: "2026-11-04T10:30:01+05:30", bar_complete: false },
  levels: { source: null, plan_id: null, entry: null, stop: null, targets: [], rule: null, valid_for_sessions: null, reference_close: null, direction: null, signal_date: null, invalidation: null },
  signal: null, signals_error: null, markers: [], conditions: [], evaluated_at_bar: null,
  markers_error: null, valid_until: null, sessions_left: null, paper_engine: "MOCK: a condition met on the chart is not a fill.",
});

interface Seen {
  pnlQueries: URLSearchParams[]; streamHits: number; tsQueries: URLSearchParams[]; listGets: number;
  patches: Array<{ id: string; body: unknown; key: string | undefined; method: string }>; closes: string[]; journals: string[];
}
interface Opts {
  phone?: boolean;
  pnl?: (q: URLSearchParams, n: number) => { status?: number; body: unknown };
  stream?: "fail" | { body: unknown; extra?: string };
  timeseries?: { status?: number; body: unknown };
  levels?: (n: number) => { status: number; body: unknown };
}

async function setup(page: Page, o: Opts = {}): Promise<Seen> {
  const seen: Seen = { pnlQueries: [], streamHits: 0, tsQueries: [], listGets: 0, patches: [], closes: [], journals: [] };
  if (o.phone) await page.setViewportSize({ width: 390, height: 844 });
  await page.route("**/api/**", (r) => json(r, { detail: "MOCK: not mocked in this spec" }, 404));
  await mockApi(page, "populated");
  await mockSingleRoute(page, "**/api/markets/home", "markets-home.json");
  await page.route("**/api/chat/sessions", (r) => json(r, []));
  await page.route("**/api/move-odds/**", (r) => json(r, { detail: "feature_not_enabled" }, 403));
  await page.route("**/api/risk/status", (r) => json(r, { kill_switch: false, halted: false, policy_version: "MOCK" }));
  await page.route("**/api/live/**", (r) => json(r, { available: false, reason: "MOCK: feed off", quotes: {}, mode: "expired", session: "closed", stale: true }));
  await page.route("**/api/desk/alerts*", (r) => json(r, { as_of: "2026-11-03", alerts: [] }));
  await page.route("**/api/desk/paper-trades*", (r) => {
    seen.listGets += 1;
    return json(r, { as_of: "2026-11-03", checked_through: "2026-11-03", trades: [], summary: { open: 0, closed: 0 }, status: "all" });
  });
  await page.route(/\/api\/desk\/paper-trades\/[^/]+\/(levels|close)$/, (r) => {
    const url = new URL(r.request().url());
    const [, id, what] = url.pathname.match(/paper-trades\/([^/]+)\/(levels|close)$/) as RegExpMatchArray;
    if (what === "close") {
      seen.closes.push(decodeURIComponent(id));
      return json(r, { trade: { id, status: "closed" }, replayed: false });
    }
    seen.patches.push({ id: decodeURIComponent(id), body: r.request().postDataJSON(), key: r.request().headers()["idempotency-key"], method: r.request().method() });
    const a = o.levels ? o.levels(seen.patches.length) : {
      status: 200,
      body: { trade: { id, pending_levels: { stop_loss: 1380, target: 1489.83, from_session: "2026-11-05", version: 1 }, level_rule: "MOCK: in force from the next session." }, replayed: false, source: "user", price_basis: "MOCK" },
    };
    return json(r, a.body, a.status);
  });
  await page.route(/\/api\/desk\/pnl(\?|$)/, (r) => {
    const q = new URL(r.request().url()).searchParams;
    seen.pnlQueries.push(q);
    const a = o.pnl ? o.pnl(q, seen.pnlQueries.length) : { body: snapshot(q) };
    return json(r, a.body, a.status ?? 200);
  });
  await page.route(/\/api\/desk\/pnl\/stream(\?|$)/, (r) => {
    seen.streamHits += 1;
    const s = o.stream ?? "fail";
    if (s === "fail") return json(r, { detail: "MOCK: stream unavailable" }, 503);
    return r.fulfill({ status: 200, contentType: "text/event-stream", body: `retry: 120000\nevent: snapshot\ndata: ${JSON.stringify(s.body)}\n\n${s.extra ?? ""}` });
  });
  await page.route(/\/api\/desk\/pnl\/timeseries(\?|$)/, (r) => {
    const q = new URL(r.request().url()).searchParams;
    seen.tsQueries.push(q);
    const trade = q.get("trade");
    if (trade) return json(r, tradeCurve(trade));
    const t = o.timeseries ?? { body: TIMESERIES };
    return json(r, t.body, t.status ?? 200);
  });
  await page.route(/\/api\/desk\/pnl\/journal\/[^/?]+/, (r) => {
    const id = decodeURIComponent(new URL(r.request().url()).pathname.split("/").pop() as string);
    seen.journals.push(id);
    if (id === "pt-icici") return json(r, JOURNAL_FOUND);
    if (id === "pt-cof") return json(r, JOURNAL_NONE);
    return json(r, { detail: "journal_not_available" }, 404);
  });
  await page.route("**/api/desk/live-chart/*", (r) => json(r, LIVE_CHART(decodeURIComponent(new URL(r.request().url()).pathname.split("/").pop() as string))));
  await page.route(/\/api\/v1\/paper\/fno-structures(\?|$)/, (r) => json(r, FNO));
  return seen;
}

const params = (page: Page) => new URL(page.url()).searchParams;
const BANNED = /\bpick|recommend|suggest/i;
const row = (page: Page, id: string) => page.locator(`[data-testid="pnl-row"][data-id="${id}"]`);
const detail = (page: Page, id: string) => page.locator(`[data-testid="pnl-row-detail"][data-id="${id}"]`);

async function noSideScroll(page: Page) {
  const o = await page.evaluate(() => {
    const sc = document.querySelector('[data-testid="copilot-scroll"]') as HTMLElement | null;
    const right = sc ? sc.getBoundingClientRect().right : window.innerWidth;
    const wide = (Array.from(document.querySelectorAll("*")) as HTMLElement[]).filter((el) => {
      const r = el.getBoundingClientRect();
      return r.width > 0 && r.right > right + 1 && !(el.parentElement && el.parentElement.getBoundingClientRect().right > right + 1);
    }).slice(0, 6).map((el) => `${el.tagName.toLowerCase()}[${el.getAttribute("data-testid") ?? ""}] right=${Math.round(el.getBoundingClientRect().right)}`);
    return { doc: document.documentElement.scrollWidth - window.innerWidth, scroll: sc ? sc.scrollWidth - sc.clientWidth : 0, wide: wide.join(", ") };
  });
  expect(o.doc, o.wide).toBeLessThanOrEqual(1);
  expect(o.scroll, o.wide).toBeLessThanOrEqual(1);
}

/** The app scrolls inside its own container, so a full-page shot shows one screen: grow the viewport to the content, shoot the
 *  dashboard, then put the viewport back. Only when PNL_SHOTS names a folder. */
async function shot(page: Page, name: string) {
  if (!SHOTS) return;
  fs.mkdirSync(SHOTS, { recursive: true });
  const vp = page.viewportSize() as { width: number; height: number };
  const h = await page.evaluate(() => {
    const sc = document.querySelector('[data-testid="copilot-scroll"]') as HTMLElement | null;
    return sc ? sc.scrollHeight + (window.innerHeight - sc.clientHeight) : document.documentElement.scrollHeight;
  });
  await page.setViewportSize({ width: vp.width, height: Math.min(h + 200, 14_000) });
  await page.waitForTimeout(400);
  await page.getByTestId("pv2-pnl").screenshot({ path: path.join(SHOTS, name) });
  await page.setViewportSize(vp);
}

const toLive = async (page: Page) => {
  await page.getByTestId("pv2-pnl-mode-live").click();
  await expect(page.getByTestId("pv2-pnl")).toHaveAttribute("data-mode", "LIVE", SLOW);
};
/** A structure's detail opens from its F&O card ("Details · Simulate exit"): legs are not table rows in the new view. */
const openStructure = async (page: Page, id: string) => {
  await page.locator(`[data-testid="pv2-fno-card"][data-id="${id}"]`).getByTestId("pv2-fno-details").click(SLOW);
};

test.describe("MOCK — not real data: Paper Trading › 05 Real-time P&L (reworked from the P&L dashboard v2 spec)", () => {
  test("TC-032 the 05 chip opens Real-time P&L with sub=pnl; the old Live desk URL lands there; no paper-trades read", async ({ page }) => {
    const seen = await setup(page);
    await page.goto(`${DESK}?tab=trade&view=paper&sub=live`);
    await expect.poll(() => params(page).get("sub"), SLOW).toBe("pnl");
    await expect(page.getByTestId("pv2-pnl")).toBeVisible(SLOW);
    await page.getByTestId("desk-sub-overview").click();
    await expect.poll(() => params(page).get("sub")).toBe("overview");
    await page.getByTestId("desk-sub-pnl").click();
    await expect.poll(() => params(page).get("sub")).toBe("pnl");
    await expect(page.getByTestId("desk-trail")).toContainText("Real-time P&L");
    await expect(page.getByTestId("pv2-pnl")).toBeVisible(SLOW);
    const before = seen.listGets;
    await page.goto(PNL);
    await expect(page.getByTestId("pv2-pnl-total")).toHaveText("−₹254.73", SLOW);
    await page.waitForTimeout(1_000);
    expect(seen.listGets).toBe(before);
  });

  test("V2-19 the view in the design's order with the snapshot's figures; the table's columns line up; no sideways scroll", async ({ page }) => {
    const seen = await setup(page);
    await page.goto(PNL);
    await expect(page.getByTestId("pv2-pnl-total")).toHaveText("−₹254.73", SLOW);
    await expect(page.getByTestId("pv2-pnl-return")).toContainText("of equity");
    expect(seen.pnlQueries[0].get("mode")).toBe("PAPER");
    const ids = ["pv2-pnl-head", "pv2-pnl-kpis", "pv2-pnl-curve", "pnl-positions", "pv2-pnl-fno", "pnl-closed"];
    await expect(page.getByTestId("pv2-fno-card")).toHaveCount(1, SLOW);
    const tops = await page.evaluate((list) => list.map((id) => (document.querySelector(`[data-testid="${id}"]`) as HTMLElement).getBoundingClientRect().top), ids);
    for (let i = 1; i < tops.length; i++) expect(tops[i], `${ids[i]} after ${ids[i - 1]}`).toBeGreaterThan(tops[i - 1]);
    // The curve and P&L by strategy side by side on a desktop.
    const [cTop, sTop] = await page.evaluate(() => ["pv2-pnl-curve", "pv2-pnl-strategies"].map((id) => (document.querySelector(`[data-testid="${id}"]`) as HTMLElement).getBoundingClientRect().top));
    expect(Math.abs(cTop - sTop)).toBeLessThan(2);
    // The stale-price note stays: two rows are priced from a quote that is not current.
    await expect(page.getByTestId("pnl-stale-positions")).toContainText("2 positions are priced from a quote that is not current");
    // Curve: the paper book's mode goes to the route; HIGH / LOW; the partial note names the missing leg.
    await expect(page.getByTestId("pv2-pnl-curve-plot")).toHaveAttribute("data-points", "6");
    await expect(page.getByTestId("pv2-pnl-curve")).toContainText("HIGH +₹4,504.70 · LOW −₹995.30");
    await expect(page.getByTestId("pv2-pnl-curve-partial")).toContainText("MOCK: no candles for NIFTY 25 Nov 25200 CE yet");
    expect(seen.tsQueries.some((q) => q.get("mode") === "PAPER" && !q.get("trade"))).toBe(true);
    // P&L by strategy: the desk's share trades together, the spread as one row.
    await expect(page.locator('[data-testid="pv2-pnl-strategy-row"][data-key="Desk share trades"]')).toContainText("−₹1,429.73");
    await expect(page.locator('[data-testid="pv2-pnl-strategy-row"][data-key="fno"]')).toContainText("+₹1,175.00");
    // Table: share positions only (the spread's legs are its card), the design's columns, levels and the pending change.
    await expect(page.getByTestId("pnl-row")).toHaveCount(2);
    await expect(page.getByTestId("pnl-table").getByRole("columnheader")).toHaveText(["Instrument", "Avg entry", "LTP", "Qty", "Stop → Target", "Position in plan", "R", "Unrealized"]);
    await expect(row(page, "pt-icici").getByTestId("pnl-row-levels")).toHaveText("1,374.90 → 1,489.83");
    await expect(row(page, "pt-icici").getByTestId("pv2-pnl-row-qty")).toHaveText("35");
    await expect(row(page, "pt-cof").getByTestId("pnl-row-pending")).toHaveText("new 1,850.00 → 2,222.61");
    await expect(row(page, "pt-cof").getByTestId("pv2-pnl-plan")).toHaveAttribute("data-pos", "0.000");
    await expect(row(page, "pt-cof").getByTestId("pv2-pnl-row-r")).toHaveText("−1.05R");
    await expect(row(page, "pt-cof").getByTestId("pnl-price-badge")).toHaveAttribute("data-status", "DELAYED");
    await expect(page.getByTestId("pnl-pending")).toHaveText(/HDFCBANK · Break above ₹1,655.00/);
    await shot(page, "pnl-v2-desktop.png");
    // Every row's columns line up with the header (each row is its own grid).
    const widths = () => page.getByTestId("pnl-table").evaluate((el) => Array.from(el.querySelectorAll('[role="row"]'))
      .map((r) => Array.from((r as HTMLElement).children).map((c) => Math.round((c as HTMLElement).getBoundingClientRect().width)).join(",")));
    expect(new Set(await widths()).size).toBe(1);
    const overflow = () => page.getByTestId("pnl-table").evaluate((el) => el.scrollWidth - el.clientWidth);
    await noSideScroll(page);
    await page.setViewportSize({ width: 1440, height: 900 });
    await noSideScroll(page);
    await page.setViewportSize({ width: 1920, height: 1080 });
    await expect.poll(overflow).toBeLessThanOrEqual(1);
    expect(new Set(await widths()).size).toBe(1);
    expect(await page.getByTestId("pv2-pnl").innerText()).not.toMatch(BANNED);
  });

  test("V2-20 the Paper / Live switch goes to the route and to the curve; Live is the broker book with no return", async ({ page }) => {
    const seen = await setup(page);
    await page.goto(PNL);
    await expect(page.getByTestId("pnl-row")).toHaveCount(2, SLOW);
    expect(seen.pnlQueries[0].get("mode")).toBe("PAPER");
    expect(seen.pnlQueries[0].get("account")).toBe("ALL");
    await expect(page.getByTestId("pv2-pnl-mode-paper")).toHaveAttribute("aria-pressed", "true");
    await toLive(page);
    await expect.poll(() => seen.pnlQueries.some((q) => q.get("mode") === "LIVE")).toBe(true);
    await expect(page.getByTestId("pv2-pnl-mode-live")).toHaveAttribute("aria-pressed", "true");
    await expect(page.getByTestId("pnl-row")).toHaveCount(2);
    await expect(page.getByTestId("pv2-pnl-total")).toHaveText("+₹4,705.00");
    await expect(page.getByTestId("pv2-pnl-return")).toHaveText("return not computed: MOCK: broker capital is not read, so no return is computed");
    await expect(page.getByTestId("pv2-pnl-kpi-realized-sub")).toContainText("Brokers do not split their realised P&L");
    await expect(page.getByTestId("pnl-account-note")).toContainText("ICICI Direct: MOCK: Session expired: sign in to ICICI Direct again.");
    await expect.poll(() => seen.tsQueries.some((q) => q.get("mode") === "LIVE")).toBe(true);
    await page.getByTestId("pv2-pnl-mode-paper").click();
    await expect(page.getByTestId("pv2-pnl")).toHaveAttribute("data-mode", "PAPER", SLOW);
    await expect(page.getByTestId("pnl-row")).toHaveCount(2);
    await expect(page.getByTestId("pv2-pnl-total")).toHaveText("−₹254.73");
  });

  test("V2-21 a paper share row opens to breakdown, fills, actions, the candle chart with its levels, the journal and the trade P&L", async ({ page }) => {
    const seen = await setup(page);
    await page.goto(PNL);
    await row(page, "pt-icici").click(SLOW);
    const d = detail(page, "pt-icici");
    await expect(d.getByTestId("pnl-breakdown-net")).toHaveText("+₹599.95");
    await expect(d.getByTestId("pnl-breakdown")).toContainText("Est. charges · ₹40.20 (estimate, not settled)");
    await expect(d.getByTestId("pnl-execution")).toHaveText(/^Opened \+35 @ ₹1,413\.21/);
    await expect(d.getByTestId("pnl-feed-note")).toContainText("checked on end-of-day bars at the evening check");
    await expect(d.getByTestId("pnl-modify")).toBeEnabled();
    await expect(d.getByTestId("pnl-exit")).toHaveText("Simulate exit");
    await expect(d.getByTestId("ca-chart")).toBeVisible(SLOW);
    await expect(d.locator('[data-testid="ca-level"]')).toHaveCount(3);
    await expect(d.getByTestId("ca-level-tag")).toHaveText(["ENTRY 1,413", "STOP 1,375", "LTP 1,432"]);
    await expect(d.locator('[data-testid="pnl-chart-level"][data-key="target"]')).toHaveAttribute("data-off", "true");
    await expect(d.getByTestId("pnl-trade-chart-levels")).toHaveText("TARGET 1 1,489.83 (outside these sessions' range, not drawn) · ENTRY 1,413.21 · STOP 1,374.90 · LTP 1,431.50");
    await expect(d.getByTestId("pnl-chart-pill")).toHaveText("LIVE");
    await expect(d.getByTestId("pnl-chart-ohlc")).toContainText("C 1,430.00");
    await expect(d.getByTestId("pnl-journal-score")).toHaveText("82/100");
    await expect(d.getByTestId("pnl-journal-parts")).toHaveText("Quality 24/30 · Trend 16/25 · Reason 14/20 · Size 10/15 · Participation 6/10 · Penalties −5");
    await expect(d.getByTestId("pnl-journal-chip")).toHaveCount(3);
    await expect(d.getByTestId("pnl-journal-levels")).toContainText("Entry 1,410.00 · Stop loss 1,374.90 · Target 1 1,489.83 · Target 2 1,559.60");
    await expect(d.getByTestId("pnl-journal-levels")).toContainText("R:R 2 / 4");
    await expect(d.getByTestId("pnl-journal-penalties")).toContainText("MOCK steep one-day jump");
    await expect(d.getByTestId("pnl-journal-lists")).toHaveText("In the day's lists: MOCK Breakout");
    await expect(d.getByTestId("pnl-journal-trade")).toContainText("Entered 28 Oct");
    expect(seen.journals).toContain("pt-icici");
    await expect(d.getByTestId("pnl-trade-curve")).toHaveAttribute("data-since-entry", "true");
    await expect(d.getByTestId("pnl-trade-curve-span")).toContainText("Net of est. charges · since entry");
    await expect(d.getByTestId("pnl-trade-curve-now")).toHaveText("+₹599.95");
    expect(seen.tsQueries.some((q) => q.get("trade") === "pt-icici" && q.get("interval") === "15m")).toBe(true);
    await shot(page, "pnl-v2-desktop-expanded.png");
    await expect(d).not.toContainText(BANNED);
    await row(page, "pt-cof").click();
    await expect(detail(page, "pt-icici")).toHaveCount(0);
    const c = detail(page, "pt-cof");
    await expect(c.getByTestId("pnl-journal-why")).toHaveText("MOCK: No scan signal for COFORGE on 28 Oct.");
    await expect(c.getByTestId("pnl-pending-levels")).toContainText("New levels saved: stop loss 1,850.00 · target 2,222.61, in force from 5 Nov (version 2)");
    await expect(c.getByTestId("pnl-feed-note")).toContainText("Last known price from 10:21:40: this P&L is not current.");
  });

  test("V2-21b a live row is read-only: no levels, no journal, the broker's own figure, today's fills note; a structure charts the underlying", async ({ page }) => {
    const seen = await setup(page);
    await page.goto(PNL);
    await expect(page.getByTestId("pnl-row")).toHaveCount(2, SLOW);
    await toLive(page);
    await row(page, "zr-1:INFY").click(SLOW);
    const d = detail(page, "zr-1:INFY");
    await expect(d.getByTestId("pnl-broker-pnl")).toContainText("Broker's own P&L · +₹9,900.00 at 10:29 (includes its realised part)");
    await expect(d.getByTestId("pnl-fills")).toContainText("MOCK: Today's fills from the broker's trade book");
    await expect(d.getByTestId("pnl-modify")).toBeDisabled();
    await expect(d.getByTestId("pnl-modify-why")).toHaveText("Broker positions are read-only here.");
    await expect(d.getByTestId("pnl-journal-none")).toContainText("No entry signal recorded for this position.");
    await expect(d.getByTestId("ca-level-tag")).toHaveText(["ENTRY 1,590", "LTP 1,618"]);
    await expect(d.getByTestId("pnl-trade-chart-note")).toHaveText("Broker positions have no stop loss or target here.");
    await expect(d.getByTestId("pnl-trade-curve")).toHaveAttribute("data-since-entry", "false");
    await expect(d.getByTestId("pnl-trade-curve-notes")).toHaveText("MOCK: today's session only.");
    expect(seen.tsQueries.some((q) => q.get("trade") === "zr-1:INFY")).toBe(true);
    expect(seen.journals).not.toContain("zr-1:INFY");
    // A structure (paper): its card's Details opens the same detail, with the structure's levels on the underlying.
    await page.getByTestId("pv2-pnl-mode-paper").click();
    await expect(page.getByTestId("pv2-pnl")).toHaveAttribute("data-mode", "PAPER", SLOW);
    await openStructure(page, "st-1");
    const l = detail(page, "st-1:0");
    await expect(l.getByTestId("pnl-structure-net")).toContainText("Bull call spread 25000/25200 · 25 Nov · 1 lot · net +₹1,175.00 (all legs)");
    await expect(l.getByTestId("pnl-modify-why")).toHaveText("Option and futures structures keep their levels in this release.");
    await expect(l.getByTestId("pnl-trade-chart-note")).toContainText("the leg's own price is a premium");
    expect(seen.tsQueries.some((q) => q.get("trade") === "st-1")).toBe(true);
  });

  test("V2-21c a live row on the broker's last read is stale and keeps its contract problem in the detail", async ({ page }) => {
    await setup(page, {
      pnl: (q) => ({ body: snapshot(q, 1762232401000, (s) => {
        const rows = s.positions as Row[];
        const infy = rows.find((r) => r.position_id === "zr-1:INFY");
        if (infy) Object.assign(infy, { price_status: "DELAYED", price_source: "Broker's last price on its read", price_at: "2026-11-04T10:29:30+05:30", price_age_seconds: 31,
          contract_problem: "MOCK: Lot size not found in the contract master." });
      }) }),
    });
    await page.goto(PNL);
    await toLive(page);
    await expect(row(page, "zr-1:INFY").getByTestId("pnl-price-badge")).toHaveAttribute("data-status", "DELAYED", SLOW);
    await row(page, "zr-1:INFY").click();
    await expect(detail(page, "zr-1:INFY").getByTestId("pnl-feed-note")).toContainText(
      "MOCK: Lot size not found in the contract master. Last known price from 10:29:30 (Broker's last price on its read): this P&L is not current. Read from Zerodha at 10:29. Nivesh places no order.");
  });

  test("V2-22 Modify risk sends only the changed level with an idempotency key; a refusal is shown in words", async ({ page }) => {
    const seen = await setup(page, {
      levels: (n) => n === 1
        ? { status: 200, body: { trade: { id: "pt-icici", pending_levels: { stop_loss: 1380, target: 1489.83, from_session: "2026-11-05", version: 1 }, level_rule: "MOCK: in force from the next session." }, replayed: false, source: "user", price_basis: "MOCK" } }
        : n === 2 ? { status: 422, body: { detail: { code: "stop_not_below_price", message: "MOCK: the server's own sentence" } } }
          : { status: 409, body: { detail: "trade_already_closed" } },
    });
    await page.goto(PNL);
    await row(page, "pt-icici").click(SLOW);
    const d = detail(page, "pt-icici");
    await d.getByTestId("pnl-modify").click();
    const f = d.getByTestId("pnl-levels-form");
    await expect(f.getByTestId("pnl-levels-stop")).toHaveValue("1374.9");
    await expect(f.getByTestId("pnl-levels-rule")).toContainText("In force from the next session; today's bar is still checked against the current levels at the evening check.");
    await f.getByTestId("pnl-levels-save").click();
    await expect(f.getByTestId("pnl-levels-error")).toHaveText("Those are the levels already in force.");
    expect(seen.patches).toHaveLength(0);
    await f.getByTestId("pnl-levels-stop").fill("1380");
    await f.getByTestId("pnl-levels-note").fill("MOCK note");
    await f.getByTestId("pnl-levels-save").click();
    await expect(f.getByTestId("pnl-levels-done")).toContainText("Saved. The new levels are in force from 5 Nov.");
    expect(seen.patches).toHaveLength(1);
    expect(seen.patches[0]).toMatchObject({ id: "pt-icici", method: "PATCH", body: { stop_price: 1380, note: "MOCK note" } });
    expect(seen.patches[0].body).not.toHaveProperty("target_price");
    const key1 = seen.patches[0].key;
    expect(key1).toBeTruthy();
    await f.getByTestId("pnl-levels-stop").fill("1420");
    await f.getByTestId("pnl-levels-save").click();
    await expect(f.getByTestId("pnl-levels-error")).toHaveText("The stop loss must be below the last end-of-day close.");
    expect(seen.patches[1].key).toBeTruthy();
    expect(seen.patches[1].key).not.toBe(key1);
    await f.getByTestId("pnl-levels-save").click();
    await expect(f.getByTestId("pnl-levels-error")).toHaveText("This trade is already closed.");
    expect(seen.patches[2].key).toBe(seen.patches[1].key);
    await f.getByTestId("pnl-levels-target").fill("1600");
    await f.getByTestId("pnl-levels-save").click();
    await expect.poll(() => seen.patches.length).toBe(4);
    expect(seen.patches[3].key).not.toBe(seen.patches[2].key);
    expect(seen.patches[3].body).toEqual({ stop_price: 1420, target_price: 1600, note: "MOCK note" });
    await f.getByTestId("pnl-levels-stop").fill("1700");
    await f.getByTestId("pnl-levels-save").click();
    await expect(f.getByTestId("pnl-levels-error")).toHaveText("The stop loss must be below the target.");
    expect(seen.patches).toHaveLength(4);
  });

  test("V2-23 Simulate exit asks first, then closes through the paper close (a structure: all its legs); Initiate exit on a live row places nothing", async ({ page }) => {
    const seen = await setup(page);
    await page.goto(PNL);
    await row(page, "pt-icici").click(SLOW);
    const d = detail(page, "pt-icici");
    await d.getByTestId("pnl-exit").click();
    await expect(d.getByTestId("pnl-exit-confirm")).toContainText("at the last end-of-day close");
    expect(seen.closes).toHaveLength(0);
    await d.getByTestId("pnl-exit-yes").click();
    await expect(d.getByTestId("pnl-exit-done")).toBeVisible();
    expect(seen.closes).toEqual(["pt-icici"]);
    await openStructure(page, "st-1");
    await detail(page, "st-1:0").getByTestId("pnl-exit").click();
    await expect(detail(page, "st-1:0").getByTestId("pnl-exit-confirm")).toContainText("This closes the whole structure, all its legs.");
    await toLive(page);
    await row(page, "zr-1:NIFTY25NOVFUT").click(SLOW);
    const l = detail(page, "zr-1:NIFTY25NOVFUT");
    await expect(l.getByTestId("pnl-exit")).toHaveText("Initiate exit");
    await l.getByTestId("pnl-exit").click();
    await expect(l.getByTestId("pnl-exit-note")).toHaveText("Nivesh is read-only with brokers: exit this position in your broker's app. No order has been placed.");
    await page.waitForTimeout(500);
    expect(seen.closes).toEqual(["pt-icici"]);
    expect(seen.patches).toHaveLength(0);
  });

  test("SPT-PNL-1 a scanner paper row: tagged, levels read-only with the reason, and its exit goes to the scanner's own route", async ({ page }) => {
    // MOCK — not real data: one Scanner-to-Paper Trading position as GET /api/desk/pnl sends it (source "scanner", 5 Nov 2026).
    const SCAN = paper({
      position_id: "spt-pos-1", trade_id: "spt-pos-1", instrument: "TATAPOWER", symbol: "TATAPOWER", underlying: "TATAPOWER", segment: "EQUITY", side: "LONG",
      net_quantity: 40, avg_price: 401.5, ltp: 405.2, prev_close: 400, price_status: "LIVE", price_source: "Kite live", price_at: "2026-11-04T10:30:01+05:30",
      price_age_seconds: 1, invested_value: 16060, unrealized_pnl: 148, gross_pnl: 148, charges_estimated: 22.4, net_pnl: 125.6, day_pnl: 208, return_pct: 0.78,
      stop_loss: 389, target: 425, distance_to_stop_pct: 4, risk_used_pct: 0, status: "ACTIVE", exposure_rs: 16208, editable_levels: false,
      source: "scanner", opportunity_id: "opp-1", proposal_id: "prop-1", order_id: "ord-1", spt_state: "MONITORING",
      executions_note: "MOCK: fills recorded by the paper monitor.", executions: [ex("fill-1", "BUY", 40, 401.5)],
    });
    const seen = await setup(page, {
      pnl: (q) => ({ body: snapshot(q, undefined, (s) => { if ((q.get("mode") ?? "ALL") !== "LIVE") s.positions = [...(s.positions as Row[]), clone(SCAN)]; }) }),
    });
    const exits: string[] = [];
    await page.route(/\/api\/v1\/paper\/positions\/[^/]+\/exit$/, (r) => {
      exits.push(decodeURIComponent(new URL(r.request().url()).pathname.split("/").slice(-2)[0]));
      return json(r, { order: { _id: "ord-exit-1", order_id: "ord-exit-1", state: "PENDING", purpose: "EXIT" }, duplicate: false });
    });
    await page.goto(PNL);
    await expect(row(page, "spt-pos-1").getByTestId("pv2-pnl-row-setup")).toHaveText("Scanner · LONG", SLOW);
    await expect(row(page, "pt-icici").getByTestId("pv2-pnl-row-setup")).toHaveText("Desk · LONG");
    await row(page, "spt-pos-1").click();
    const d = detail(page, "spt-pos-1");
    await expect(d.getByTestId("pnl-modify")).toBeDisabled();
    await expect(d.getByTestId("pnl-modify-why")).toHaveText("A scanner paper trade keeps its plan's stop and targets; the paper monitor watches them live.");
    await d.getByTestId("pnl-exit").click();
    await expect(d.getByTestId("pnl-exit-confirm")).toHaveAttribute("data-source", "scanner");
    await expect(d.getByTestId("pnl-exit-confirm")).toContainText("The paper monitor sells at the live bid");
    expect(exits).toHaveLength(0);
    await d.getByTestId("pnl-exit-yes").click();
    await expect(d.getByTestId("pnl-exit-done")).toContainText("Exit order placed in the paper book.");
    expect(exits).toEqual(["spt-pos-1"]);
    expect(seen.closes).toHaveLength(0);   // never the desk's close for a scanner position
    expect(seen.patches).toHaveLength(0);
  });

  test("TC-037 the stream fails → polling; a newer snapshot updates, an older one is dropped; the stream path delivers too", async ({ page }) => {
    let ltp = 1431.5, seq = 1762232401000;
    const seen = await setup(page, { pnl: (q) => ({ body: snapshot(q, seq, (s) => { (s.positions as Row[]).find((r) => r.position_id === "pt-icici")!.ltp = ltp; }) }) });
    await page.goto(PNL);
    const icici = row(page, "pt-icici");
    await expect(icici.getByTestId("pnl-ltp")).toHaveText("1,431.50", SLOW);
    await expect(page.getByTestId("pv2-pnl-stream")).toHaveText("Polling · every 3 s");
    await expect(page.getByTestId("pv2-pnl-stream")).toHaveAttribute("data-state", "polling");
    expect(seen.streamHits).toBeGreaterThan(0);
    ltp = 1440; seq += 3000;
    await expect(icici.getByTestId("pnl-ltp")).toHaveText("1,440.00", { timeout: 10_000 });
    ltp = 1300; seq -= 10_000;
    const polls = seen.pnlQueries.length;
    await expect.poll(() => seen.pnlQueries.length, { timeout: 10_000 }).toBeGreaterThan(polls + 1);
    await expect(icici.getByTestId("pnl-ltp")).toHaveText("1,440.00");
    const p2 = await page.context().newPage();
    const seen2 = await setup(p2, { stream: { body: snapshot(new URLSearchParams("segment=ALL&period=TODAY&mode=PAPER&account=ALL"), 1762232409000) } });
    await p2.goto(PNL);
    await expect(p2.getByTestId("pv2-pnl-total")).toHaveText("−₹254.73", SLOW);
    await expect(p2.getByTestId("pv2-pnl-stream")).toHaveAttribute("data-transport", "sse");
    expect(seen2.streamHits).toBeGreaterThan(0);
    expect(seen2.pnlQueries.length).toBe(0);
    await p2.close();
  });

  test("V2-25 390 px: the table scrolls inside its card, a row opens its detail below it, no sideways page scroll", async ({ page }) => {
    await setup(page, { phone: true });
    await page.goto(PNL);
    await expect(page.getByTestId("pv2-pnl")).toHaveAttribute("data-narrow", "true", SLOW);
    const t = page.getByTestId("pnl-table");
    await expect(t).toBeVisible();
    expect(await t.evaluate((el) => el.scrollWidth - el.clientWidth)).toBeGreaterThan(0);
    await row(page, "pt-icici").click();
    const below = page.getByTestId("pv2-pnl-detail-below");
    await expect(below.getByTestId("pnl-row-detail")).toBeVisible();
    await expect(below.getByTestId("pnl-journal-score")).toHaveText("82/100", SLOW);
    await expect(below.getByTestId("ca-chart")).toBeVisible();
    await noSideScroll(page);
    await shot(page, "pnl-v2-390.png");
  });

  test("TC-039 the route fails: a problem with Retry, no figures; a missing price is said, never 0", async ({ page }) => {
    let fail = true;
    await setup(page, {
      pnl: (q) => (fail ? { status: 500, body: { detail: "MOCK: down" } }
        : { body: snapshot(q, 1762232401000, (s) => {
          const p = (s.positions as Row[]).find((r) => r.position_id === "pt-icici")!;
          Object.assign(p, { ltp: null, price_status: "MISSING", price_at: null, unrealized_pnl: null, gross_pnl: null, net_pnl: null, charges_estimated: null });
          Object.assign(s.summary as Row, { unpriced_positions: 1, complete: false });
        }) }),
    });
    await page.goto(PNL);
    await expect(page.getByTestId("pnl-error")).toBeVisible(SLOW);
    await expect(page.getByTestId("pv2-pnl-kpis")).toHaveCount(0);
    await expect(page.getByTestId("pv2-pnl-total")).toHaveText("—");
    await expect(page.getByTestId("pv2-pnl-stream")).toHaveAttribute("data-state", "error");
    fail = false;
    await page.getByTestId("pnl-error").getByRole("button").first().click();
    await expect(page.getByTestId("pv2-pnl-kpis")).toBeVisible(SLOW);
    const icici = row(page, "pt-icici");
    await expect(icici.getByTestId("pnl-price-badge")).toHaveText("NO PRICE");
    await expect(icici.getByTestId("pnl-ltp")).toHaveText("—");
    await expect(icici.getByTestId("pv2-pnl-row-unrealized")).toHaveText("—");
    await expect(page.getByTestId("pnl-incomplete")).toContainText("1 open position has no price");
  });

  test("V2-26 Live unavailable (every session expired): the view says why; a contract error is a problem", async ({ page }) => {
    await setup(page, {
      pnl: (q) => ({ body: snapshot(q, 1762232401000, (s) => {
        s.positions = (s.positions as Row[]).filter((r) => r.mode === "PAPER");
        (s.accounts as Row[])[1] = { ...(s.accounts as Row[])[1], state: "SIGN_IN", state_note: "MOCK: Session expired: sign in to Zerodha again.", open_positions: 0, net_pnl: null };
        (s.modes as Record<string, Row>).LIVE = { realized_pnl: null, unrealized_pnl: null, gross_pnl: null, charges: null, net_pnl: null, capital: null, return_pct: null, open_positions: 0, complete: true, available: false,
          note: "MOCK: No broker account could be read: Zerodha session expired; ICICI Direct session expired." };
      }) }),
    });
    await page.goto(PNL);
    await toLive(page);
    await expect(page.getByTestId("pnl-positions-empty")).toBeVisible();
    await expect(page.getByTestId("pv2-pnl-live-note")).toHaveText("MOCK: No broker account could be read: Zerodha session expired; ICICI Direct session expired.");
    await expect(page.getByTestId("pnl-account-note")).toContainText("Zerodha: MOCK: Session expired: sign in to Zerodha again.");
    await expect(page.getByTestId("pnl-account-note")).toContainText("Its positions are not in this total.");
    const p2 = await page.context().newPage();
    await setup(p2, { pnl: () => ({ body: { summary: {} } }) });
    await p2.goto(PNL);
    await expect(p2.getByTestId("pnl-error")).toBeVisible(SLOW);
    await expect(p2.getByTestId("pnl-error")).toContainText("unexpected response shape");
    await p2.close();
  });

  test("TC-034 Closed trades: the period goes to the route; the closed rows, the realized KPI net of costs, waiting entries, the route's notes", async ({ page }) => {
    const seen = await setup(page);
    await page.goto(PNL);
    await expect(page.getByTestId("pnl-closed")).toBeVisible(SLOW);
    await expect(page.getByTestId("pnl-closed-empty")).toHaveText("No paper trade closed today.");
    await expect(page.getByTestId("pnl-pending")).toHaveText(/HDFCBANK · Break above ₹1,655.00/);
    await page.getByTestId("pnl-period-1w").click();
    await expect.poll(() => seen.pnlQueries.some((q) => q.get("period") === "1W")).toBe(true);
    await expect(page.getByTestId("pnl-closed-row")).toHaveCount(1);
    await expect(page.getByTestId("pnl-closed-net")).toHaveText("−₹3,360.10");
    await expect(page.getByTestId("pv2-pnl-kpi-realized-value")).toHaveText("−₹3,360.10");
    await expect(page.getByTestId("pv2-pnl-kpi-realized-sub")).toHaveText("1 closed this week · net of costs");
    await expect(page.getByTestId("pnl-notes")).toContainText("MOCK: charges are the desk cost card's.");
  });
});
