/**
 * One-screen Copilot app (/v5/app) — Smart trading desk redesign, step 3: tab 02 Trade Desk
 * (docs/desk_redesign_20261027/PLAN.md; test cases in test_reports/desk_trade_desk_TESTCASES.md, TD-1 … TD-36).
 *
 * The plans, GET /api/desk/trade-plans/{id} (with `account_size`, the risk service's own sizing), GET /api/risk/profile,
 * GET /api/desk/paper-account and the REAL allow / reduce / block answers of POST /api/desk/paper-trades come from
 * `contract-decision-card.json`, which backend/tests/test_decision_card_contract.py rebuilds from the real routes (cash:
 * MOCK — not real data, the RELIANCE-like world of backend/tests/test_strategy_plan.py). Everything else below is an inline
 * MOCK — not real data — in the real route's shape (the source is named beside each). Mocked APIs, production build.
 */
import { test, expect, type Page, type Route } from "@playwright/test";
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";
import { mockApi, mockSingleRoute } from "../helpers/api-mock";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const load = (name: string) => JSON.parse(fs.readFileSync(path.join(__dirname, "..", "fixtures", name), "utf-8"));
const CARD = load("contract-decision-card.json");
const clone = <T,>(x: T): T => JSON.parse(JSON.stringify(x));
const json = (route: Route, body: unknown, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });

const DESK = "/v5/app/trader/desk";
/** The owner's workbench places (PLAN.md "1-REVISED"): the TD cases' old view names, and where they are now. */
const PLACE: Record<string, string> = { open: "paper&sub=live", closed: "paper&sub=journal", new: "lab&sub=build", backtest: "lab&sub=backtest" };
const TD = (view: string, extra = "") => `${DESK}?tab=trade&view=${PLACE[view] ?? view}${extra}`;
const CASH_PLAN = CARD.cash.trade_plan_response.plan;
const SRC = "&src_kind=scanner&src_bucket=breakout_confirmed&src_date=2026-10-19";
const SLOW = { timeout: 15_000 };

// ── MOCK paper trades (backend/routes/desk_trading.py list_paper_trades: svc.public_trade / strat.public_strategy_trade
//    + _with_lifecycle). Every symbol, price and P/L is made up. ──────────────────────────────────────────────────────
const COST_V2 = { name: "desk cost card", version: "desk-cost-v2", slippage_pct_per_side: 0.05, brokerage_rs_per_side: 20 };
const ev = (seq: number, from: string | null, to: string, o: Record<string, unknown> = {}) => ({
  event_id: `x:${seq}`, seq, from, to, at: "2026-10-22T10:00:00+00:00", session: "2026-10-22", reason: null, source: "desk",
  actor: "u_fixture", rule_version: "desk-paper-v2", lifecycle_version: "trade-lifecycle-v1 (2026-10-27)", ...o,
});
const cash = (o: Record<string, unknown>) => ({
  kind: "cash", quantity: 10, entry_price: 100, stop_price: 95, target_price: 110, note: null, source: { kind: "scanner", bucket: "breakout_confirmed", signal_date: "2026-10-21" },
  opened_at: "2026-10-22T09:00:00+00:00", status: "open", closed_at: null, exit_price: null, exit_reason: null, exit_session: null, exit_note: null,
  last_close: 101, last_close_date: "2026-10-26", unrealized_pnl_rs: 10, realized_pnl_rs: null, checked_through: "2026-10-26", mark_error: null,
  entry_rule: "at_once", entry_window_sessions: null, max_hold_sessions: 10, rules_version: "desk-paper-v2", cost_model: COST_V2,
  entry_status: "assumed", entry_session: "2026-10-22", sim_entry_price: 100, observations: 3, held_sessions: 3, flags: [],
  exit_rules: [], exit_rules_version: "exit-rules-v1", stop_history: [], current_stop: 95, stop_version: 1, plan_ref: null, transitions: [], ...o,
});
const PENDING = cash({
  id: "pt-pend", symbol: "HDFCBANK", quantity: 60, entry_price: 1655, stop_price: 1610, target_price: 1745, current_stop: 1610,
  entry_rule: "break_above", entry_window_sessions: 3, entry_status: "waiting", entry_session: null, sim_entry_price: null,
  state: "TRADE_ELIGIBLE", last_close: 1641.2, unrealized_pnl_rs: null, gross_pnl_rs: null, costs_rs: null, net_pnl_rs: null,
  plan_ref: { plan_id: "tp_pending0001" },
  transitions: [ev(1, null, "TRADE_ELIGIBLE", { session: "2026-10-26", reason: "Recorded; waits for a break above ₹1,655.00 for 3 sessions." })],
});
const BREAKDOWN = { brokerage: 40, stt: 22.69, exchange: 6.75, sebi: 0.23, stamp: 3.4, gst: 8.48, slippage: 130.85, total: 212.4 };
const OPEN = cash({
  id: "pt-open", symbol: "INFY", quantity: 150, entry_price: 1512.4, sim_entry_price: 1512.4, stop_price: 1478, current_stop: 1490, stop_version: 2,
  target_price: 1598, last_close: 1538.1, unrealized_pnl_rs: 3855, gross_pnl_rs: 3855, costs_rs: 212.4, net_pnl_rs: 3642.6,
  costs_breakdown: BREAKDOWN, costs_basis: "entry and exit sides; the exit side estimated at the last close", state: "POSITION_OPEN",
  plan_ref: { plan_id: CASH_PLAN.plan_id },
  stop_history: [{ session: null, stop: 1478, reason: "initial", version: 1 }, { session: "2026-10-24", stop: 1490, reason: "trailing_atr", version: 2 }],
  transitions: [
    ev(1, null, "TRADE_ELIGIBLE", { reason: "Recorded at the plan's levels." }),
    ev(2, "TRADE_ELIGIBLE", "ENTRY_TRIGGERED", { reason: "At-once entry: triggered when recorded." }),
    ev(3, "ENTRY_TRIGGERED", "POSITION_OPEN", { reason: "Filled at the recorded price.", fill_price: 1512.4, slippage: 0 }),
  ],
});
const UNMARKED = cash({ id: "pt-nomark", symbol: "NOMARK", state: "POSITION_OPEN", last_close: null, last_close_date: null, unrealized_pnl_rs: null, gross_pnl_rs: null, costs_rs: null, net_pnl_rs: null, mark_error: "no_prices_for_symbol" });
const BOTH = "The stop and the target were both inside this session's range; counted as the stop (conservative).";
const GAP = "The session opened at ₹3,884.00, below the stop ₹3,890.00: the price never traded at the stop, so the fill is the open and the loss is larger than the stop distance.";
const AXIS = cash({
  id: "pt-axis", symbol: "AXISBANK", status: "closed", quantity: 80, entry_price: 1120, sim_entry_price: 1120, stop_price: 1080, current_stop: 1080, target_price: 1180,
  closed_at: "2026-10-24T15:30:00+00:00", exit_price: 1080, exit_reason: "stop", exit_session: "2026-10-24", exit_note: BOTH, state: "CLOSED",
  realized_pnl_rs: -3200, gross_pnl_rs: -3200, costs_rs: 160.1, net_pnl_rs: -3360.1, last_close: null, unrealized_pnl_rs: null, costs_breakdown: { ...BREAKDOWN, slippage: 78.55, total: 160.1 },
  flags: [{ code: "both_in_range", text: BOTH, session: "2026-10-24", price: 1080 }],
  transitions: [ev(1, null, "TRADE_ELIGIBLE"), ev(2, "TRADE_ELIGIBLE", "ENTRY_TRIGGERED"), ev(3, "ENTRY_TRIGGERED", "POSITION_OPEN", { fill_price: 1120 }),
    ev(4, "POSITION_OPEN", "EXIT_PENDING", { session: "2026-10-24", exit_reason: "stop" }), ev(5, "EXIT_PENDING", "CLOSED", { session: "2026-10-24", exit_reason: "stop", fill_price: 1080, reason: BOTH })],
});
const TCS = cash({
  id: "pt-tcs", symbol: "TCS", status: "closed", quantity: 20, entry_price: 3950, sim_entry_price: 3950, stop_price: 3890, current_stop: 3890, target_price: 4100,
  closed_at: "2026-10-23T15:30:00+00:00", exit_price: 3884, exit_reason: "stop", exit_session: "2026-10-23", state: "CLOSED",
  realized_pnl_rs: -1320, gross_pnl_rs: -1320, costs_rs: 120.1, net_pnl_rs: -1440.1, last_close: null, unrealized_pnl_rs: null,
  flags: [{ code: "gap_through_stop", text: GAP, session: "2026-10-23", price: 3884 }],
});
const LEGS = [
  { strike: 24300, option_type: "put", side: "buy", entry_price: 22.46, mark: 16.37, pnl_rs: -456.75 },
  { strike: 24400, option_type: "put", side: "sell", entry_price: 40.84, mark: 30.88, pnl_rs: 747 },
  { strike: 24800, option_type: "call", side: "sell", entry_price: 58.99, mark: 75.13, pnl_rs: -1210.5 },
  { strike: 24900, option_type: "call", side: "buy", entry_price: 34.62, mark: 45.59, pnl_rs: 822.75 },
];
const EXPIRY = "2026-11-25";
const CONDOR = {
  id: "pt-ic", kind: "strategy", symbol: "NIFTY", underlying: "NIFTY", direction: "neutral", family: "iron_condor", family_name: "Iron condor",
  summary_text: `Iron condor 24300/24400/24800/24900 · 25 Nov · 1 lot`, strategy_plan_id: "plan_ic", reference_price: 24600, stop_underlying: null, target_underlying: null,
  note: null, opened_at: "2026-10-21T10:00:00+00:00", status: "open", closed_at: null, exit_reason: null, exit_session: null, exit_note: null,
  entry_rule: "at_once", entry_status: "assumed", max_hold_sessions: null, rules_version: "desk-paper-v3", cost_model: COST_V2, risk: { defined_risk: true, futures_exposure: false, note: null },
  signal: { signal_at: "2026-10-21T10:00:00+00:00", rule_version: "fno-rules-v1", model_version: null, source_refs: [], evidence_summary: "MOCK: range-bound build-up" },
  entry_record_hash: "h", entry_record_intact: true,
  legs: LEGS.map((l, i) => ({ index: i, kind: "option", side: l.side, lots: 1, lot_size: 75, entry_price: l.entry_price, expiry: EXPIRY, strike: l.strike, option_type: l.option_type,
    price_source: "NSE F&O bhavcopy close, 2026-10-21", label: `${l.side} 1 lot ${l.option_type} ${l.strike}`, mark: l.mark, mark_date: "2026-10-26", mark_basis: "close", mark_basis_text: "the option's close", mark_source: "bhavcopy", pnl_rs: l.pnl_rs })),
  net_premium_rs: 3206.25, mark_premium_rs: 3303.75, gross_pnl_rs: -97.5, costs_rs: 120.4, costs_breakdown: { brokerage: 80, stt: 9.1, exchange: 8.2, sebi: 0.01, stamp: 0.3, gst: 15.9, slippage: 6.89, total: 120.4 },
  costs_basis: "entry and exit sides, every leg", net_pnl_rs: -217.9, unrealized_pnl_rs: -97.5, realized_pnl_rs: null, mfe_rs: 410, mae_rs: -380, observations: 4, held_sessions: 4,
  checked_through: "2026-10-26", last_mark_date: "2026-10-26", mark_error: null, flags: [], event_count: 1,
  events: [{ type: "created", at: "2026-10-21T10:00:00+00:00", session: "2026-10-21", text: "Strategy paper trade recorded at the legs' bhavcopy closes." }],
  premium_plan: null, structure_value_per_unit: 44.05, exit_basis: null, state: "POSITION_OPEN", transitions: [], plan_ref: null, rolled_from: null, rolled_to: null,
};
const ALL = [PENDING, OPEN, UNMARKED, CONDOR, AXIS, TCS];
const book = (trades: Array<Record<string, unknown>>, o: Record<string, unknown> = {}) => ({
  as_of: "2026-10-26", checked_through: "2026-10-26", source: "nidp", price_basis: "raw traded price", marks_error: null, exit_rule: "stop, target, time",
  entry_rules: {}, rules_version: "desk-paper-v2", cost_model: COST_V2, orders: "Paper trades never create a broker order.", status: "all", trades,
  summary: { open: trades.filter((t) => t.status === "open").length, closed: trades.filter((t) => t.status === "closed").length, wins: 0, losses: 2,
    realized_pnl_rs: -4520, net_realized_pnl_rs: -4800.2, costs_realized_rs: 280.2, unrealized_pnl_rs: 3757.5, unmarked_open: 1, partial: false, entry_pending: 1, not_entered: 0 },
  ...o,
});

// GET /api/risk/profile (contract fixture, owner defaults) with 12,000 of open risk on 10,00,000 of equity → 1.2% of 3%.
const PROFILE = (() => { const p = clone(CARD.risk_profile_default); p.live.open.risk_rs = 12000; return p; })();
const PROFILE_UNKNOWN = (() => { const p = clone(CARD.risk_profile_default); p.live.equity.equity_rs = null; p.live.equity.unknown_reasons = ["NOMARK has no end-of-day mark"]; return p; })();
// GET /api/desk/paper-account (contract fixture; cash and blocked MOCK)
const ACCOUNT = { ...CARD.paper_account, cash_rs: 975000, blocked_rs: 124617.8, available_rs: 850382.2, stored: true };
// GET /api/desk/exit-job-status (services/job_runs.trader_status)
const EXIT_OK = { job: "check_desk_alerts", status: "ok", state: "ok", message: "Exits were checked after the 2026-10-26 close.", schedule: "Mon–Fri 20:45 IST, retry 22:45 IST",
  last_checked: { session: "2026-10-26", started_at: "2026-10-26T15:15:00+00:00", finished_at: "2026-10-26T15:16:10+00:00" }, latest_run: null, expected_since: "2026-10-26T15:15:00+00:00", grace_minutes: 60, as_of: "2026-10-27T05:00:00+00:00" };
// the staging answer of 27 Oct (test_reports/desk_redesign_backend_20261027.md)
const EXIT_MISSED = { job: "check_desk_alerts", status: "missed", state: "never_run", message: "No evening exit check has been recorded.", last_checked: null, latest_run: null,
  expected_since: "2026-10-26T17:15:00+00:00", schedule: "Mon–Fri 20:45 IST, retry 22:45 IST", grace_minutes: 60 };
const EXIT_LATE = { ...EXIT_OK, status: "late", message: "The exit check due at Mon 27 Oct 20:45 IST has not been recorded yet." };
// GET /api/desk/strategy/templates (backend strategy_plan/templates.py CATALOG names; legs abridged)
const TEMPLATES = { calculation_version: "payoff-v2", read_only: true, templates: ["long_call", "long_put", "bull_call_spread", "bear_put_spread", "iron_condor", "long_future", "short_future", "cash_long"].map((name) => ({
  name, label: name.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase()), kind: name.includes("future") ? "future" : name === "cash_long" ? "cash" : "option", legs: [], params: [], calculation_version: "payoff-v2" })) };
// POST /api/desk/strategy/payoff — MOCK answer (payoff-v2 shape); the figures are made up, never computed by the screen.
const payoffAnswer = (req: { legs: Array<Record<string, unknown>>; pre_expiry?: { date: string } }) => ({
  valid: true, problems: [], warnings: [], calculation_version: "payoff-v2", underlying: "NIFTY", reference_price: 24600, caveats: [], sent_to_broker: false,
  expiry: { grid: [24000, 24600, 25200], gross: [-4293.75, 3206.25, -4293.75], net: [-4410.5, 3089.5, -4410.5], per_leg: [], breakevens: [24342.75, 24857.25],
    max_profit: 3206.25, max_loss: -4293.75, profit_unbounded: false, loss_unbounded: false, net_premium: 3206.25, scenarios: [] },
  pre_expiry: req.pre_expiry ? { date: req.pre_expiry.date, model: "Black-76", assumptions: {}, grid: [24000, 24600, 25200], gross: [-2000, 1500, -2000], net: [-2100, 1400, -2100],
    greeks: { delta: -1.2, gamma: -0.01, theta: 41.5, vega: -88.2, rho: -3.1 },
    per_leg_greeks: req.legs.map((_, i) => ({ leg: i, label: `leg ${i}`, greeks: { delta: 0.1, gamma: 0.001, theta: -5, vega: 10, rho: 0.2 } })), unavailable: [] } : null,
  costs: { model: "desk-cost-v2", entry: 60.2, exit_at_expiry: 60.2, round_trip: 120.4, excluded: ["income tax"] }, margin: { estimate: null, source: null }, margin_reason: "MOCK",
  capital_at_risk: 4410.5, capital_at_risk_basis: "worst net loss over all prices, every leg charged entry and exit costs",
});
// GET /api/strategy-builder/strategies and POST …/backtest (provenance-v1, backend strategy_engine/backtest.py run_provenance)
const STRATEGIES = { strategies: [{ id: "st-1", name: "Breakout screen", asset_class: "STOCK", created_at: "2026-10-01" }, { id: "st-nifty", name: "Nifty 50 momentum", asset_class: "STOCK" }] };
const backtest = (index: boolean) => ({
  run_id: index ? "run-n50" : "run-liq", trade_count: 42, equity_curve: [],
  metrics: { trade_count: 42, total_return_pct: 6.12, win_rate: 47.6, max_drawdown_pct: 8.25, profit_factor: 1.12,
    slippage_sweep: { basis: "the same trades and quantities re-priced at each slippage per side; sizing and cash are not re-simulated",
      by_bps: { 0: { net_pnl_rs: 71000, expectancy_rs: 1690.48, win_rate: 50, total_return_pct: 7.1 }, 5: { net_pnl_rs: 61200, expectancy_rs: 1457.14, win_rate: 47.6, total_return_pct: 6.12 },
        10: { net_pnl_rs: 51000, expectancy_rs: 1214.29, win_rate: 45.2, total_return_pct: 5.1 }, 20: { net_pnl_rs: 30800, expectancy_rs: 733.33, win_rate: 40.5, total_return_pct: 3.08 } } } },
  provenance: { schema: "provenance-v1", data: { snapshot_as_of: "2026-10-26", window_last_session: "2026-10-24" }, code_version: "abc1234",
    rule_version: { dsl_version: 1, spec_sha256: "f00d", exit_rules_version: "exit-rules-v1" },
    cost_model: { version: "desk-cost-v2", slippage_pct_per_side: 0.05, slippage_basis: "in the fill prices", brokerage_rs_per_side: 20 },
    universe: index
      ? { type: "index", ref: "NIFTY 50", basis: "latest_snapshot", warning: "NIFTY 50 applied with its latest constituents: stocks that left the index are missing (survivorship bias).", rule: null }
      : { type: "market", ref: "LIQUID_EQ", basis: "point_in_time", warning: null, rule: { version: "liquid-eq-v1" } },
    entry_timing: "next_open", price_basis: "adjusted close", not_recorded: [], complete: true },
});

interface Seen {
  listGets: number; posts: Array<Record<string, unknown>>; keys: Array<string | undefined>; payoffs: Array<Record<string, unknown>>;
  backtests: Array<{ id: string; body: unknown }>; closes: Array<{ path: string; body: unknown }>;
}
interface Opts {
  trades?: Array<Record<string, unknown>>; bookExtra?: Record<string, unknown>; profile?: unknown; exit?: { status: number; body: unknown };
  plan?: unknown; post?: Array<{ status: number; body: unknown }>; phone?: boolean; roll?: unknown; close?: { status: number; body: unknown };
  list?: { status: number; body: unknown }; corrections?: unknown;
}

async function setup(page: Page, o: Opts = {}): Promise<Seen> {
  const seen: Seen = { listGets: 0, posts: [], keys: [], payoffs: [], backtests: [], closes: [] };
  if (o.phone) await page.setViewportSize({ width: 390, height: 844 });
  // Anything not answered below: a 404 in the API's shape, so no request leaves the page.
  await page.route("**/api/**", (r) => json(r, { detail: "MOCK: not mocked in this spec" }, 404));
  await mockApi(page, "populated");
  await mockSingleRoute(page, "**/api/markets/home", "markets-home.json");
  await page.route("**/api/chat/sessions", (r) => json(r, []));
  await page.route("**/api/positional/watchlist*", (r) => json(r, { as_of_date: "2026-10-26", buckets: { breakout_confirmed: [], pre_breakout: [], true_accumulation: [], trend_continuation: [] } }));
  await page.route("**/api/positional/picks*", (r) => json(r, { signal_date: "2026-10-26", count: 0, picks: [] }));
  await page.route("**/api/move-odds/**", (r) => json(r, { detail: "feature_not_enabled" }, 403));
  await page.route("**/api/desk/alerts*", (r) => json(r, { as_of: "2026-10-26", alerts: [] }));
  await page.route("**/api/risk/status", (r) => json(r, { kill_switch: false, halted: false, policy_version: "MOCK" }));
  await page.route("**/api/risk/profile", (r) => json(r, o.profile ?? PROFILE));
  await page.route("**/api/desk/paper-account", (r) => json(r, ACCOUNT));
  await page.route("**/api/desk/paper-account/corrections", (r) => json(r, o.corrections ?? { corrections: [], count: 0, truncated: false, counts: { in_force: 0, excluded: 0, voided: 0, reverted: 0, by_reason_code: {} }, append_only: true }));
  await page.route("**/api/desk/exit-job-status", (r) => json(r, o.exit?.body ?? EXIT_OK, o.exit?.status ?? 200));
  await page.route("**/api/desk/strategy/templates", (r) => json(r, TEMPLATES));
  await page.route("**/api/desk/strategy/ideas", (r) => json(r, CARD.cash.ideas_response));
  await page.route("**/api/desk/strategy/plans*", (r) => json(r, { plans: [] }));
  await page.route("**/api/desk/strategy/levels", (r) => json(r, { valid: false, version: "strategy-levels-v2", problems: [{ code: "mock", message: "MOCK" }] }));
  await page.route("**/api/desk/strategy/payoff", (r) => {
    const body = r.request().postDataJSON() as { legs: Array<Record<string, unknown>>; pre_expiry?: { date: string } };
    seen.payoffs.push(body as unknown as Record<string, unknown>);
    return json(r, payoffAnswer(body));
  });
  await page.route("**/api/desk/trade-plans/*", (r) => {
    const id = decodeURIComponent(new URL(r.request().url()).pathname.split("/").pop() as string);
    return id === CASH_PLAN.plan_id ? json(r, o.plan ?? CARD.cash.trade_plan_response) : json(r, { detail: "plan_not_found" }, 404);
  });
  await page.route("**/api/desk/paper-trades/*/close", (r) => {
    seen.closes.push({ path: new URL(r.request().url()).pathname, body: r.request().postDataJSON() });
    const a = o.close ?? { status: 200, body: { trade: { id: "closed" } } };
    return json(r, a.body, a.status);
  });
  await page.route("**/api/desk/paper-trades/*/roll", (r) => json(r, o.roll ?? { eligible: false, refusal: { code: "roll_chain_not_ready", message: "The 27 Oct F&O bhavcopy is published after 22:15 IST; a roll is priced on it." } }));
  const posts = [...(o.post ?? [])];
  await page.route("**/api/desk/paper-trades*", (r) => {
    if (r.request().method() === "POST") {
      seen.posts.push(r.request().postDataJSON());
      seen.keys.push(r.request().headers()["idempotency-key"]);
      const a = posts.shift() ?? { status: 201, body: { trade: { id: `t${seen.posts.length}` }, risk: null } };
      return json(r, a.body, a.status);
    }
    seen.listGets += 1;
    return o.list ? json(r, o.list.body, o.list.status) : json(r, book(o.trades ?? ALL, o.bookExtra));
  });
  await page.route("**/api/strategy-builder/strategies", (r) => json(r, STRATEGIES));
  await page.route("**/api/strategy-builder/strategies/*/backtest", (r) => {
    const id = new URL(r.request().url()).pathname.split("/").slice(-2)[0];
    seen.backtests.push({ id, body: r.request().postDataJSON() });
    return json(r, backtest(id === "st-nifty"));
  });
  // The F&O builder's NIFTY data (synthetic fixtures in the routes' shape) and its side reads.
  await mockSingleRoute(page, "**/api/fno/NIFTY/expiries", "copilot-options-expiries.json");
  await mockSingleRoute(page, "**/api/fno/NIFTY/futures", "copilot-options-futures.json");
  await page.route("**/api/fno/NIFTY/chain*", (r) => json(r, load("copilot-options-chain.json")));
  await page.route("**/api/fno/scan/buildup*", (r) => json(r, { as_of: "2026-10-12", indices: [], counts: {}, sources: {}, master: {}, risk_flag_text: {}, rows: [] }));
  await page.route("**/api/fno/margin", (r) => json(r, { detail: "MOCK: margin calculator off" }, 503));
  await page.route("**/api/live/**", (r) => json(r, { available: false, reason: "MOCK: feed off", quotes: {}, mode: "expired", session: "closed", stale: true }));
  return seen;
}

const params = (page: Page) => new URL(page.url()).searchParams;
const n2 = (n: number) => new Intl.NumberFormat("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(n);
const rs0 = (n: number) => `₹${new Intl.NumberFormat("en-IN").format(Math.round(n))}`;
const BANNED = /\bpick|recommend|suggest/i;
/** The SEBI caveat on a decision card ("not a recommendation") is required wording, not a breach. */
const wordingOf = (t: string) => t.replace(/not (a )?recommendations?/gi, "");

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

// ── header strip ─────────────────────────────────────────────────────────

test.describe("MOCK — not real data: Trade Desk · header strip", () => {
  test("TD-1 / TD-2 / TD-3 / TD-5 the Live desk's account, open-risk chip and exit line; the paper/real line on Paper Trading and Strategy Lab", async ({ page }) => {
    await setup(page);
    for (const view of ["closed", "new"]) {
      await page.goto(TD(view));
      await expect(page.getByTestId("desk-paper-real-line"), view).toHaveText("These are paper trades. Your real holdings and F&O positions (read-only): My portfolio", SLOW);
    }
    for (const view of ["open"]) {
      await page.goto(TD(view));
      const h = page.getByTestId("td-header");
      await expect(h, view).toBeVisible(SLOW);
      await expect(page.getByTestId("td-acct-cash")).toHaveText(rs0(ACCOUNT.cash_rs));
      await expect(page.getByTestId("td-acct-blocked")).toHaveText(rs0(ACCOUNT.blocked_rs));
      await expect(page.getByTestId("td-acct-equity")).toHaveText(rs0(PROFILE.live.equity.equity_rs));
      await expect(page.getByTestId("td-acct-start")).toContainText(`Starting capital ${rs0(ACCOUNT.starting_capital_rs)}, a simulation default`);
      await expect(page.getByTestId("td-open-risk")).toHaveText("Open risk 1.2% of 3%");
      await expect(page.getByTestId("td-open-risk")).toHaveAttribute("data-pct", (12000 / PROFILE.live.equity.equity_rs * 100).toFixed(2));
      await expect(page.getByTestId("td-exit-job")).toHaveAttribute("data-status", "ok");
      await expect(page.getByTestId("td-exit-job")).toContainText("Exits checked after the 26 Oct close");
      await expect(page.getByTestId("desk-paper-real-line")).toHaveText("These are paper trades. Your real holdings and F&O positions (read-only): My portfolio");
    }
  });

  test("TD-4 the exit check missed, late, or its status unreadable", async ({ page }) => {
    await setup(page, { exit: { status: 200, body: EXIT_MISSED } });
    await page.goto(TD("open"));
    await expect(page.getByTestId("td-exit-job")).toHaveAttribute("data-status", "missed", SLOW);
    await expect(page.getByTestId("td-exit-job")).toContainText("Exit check missed: No evening exit check has been recorded.");
    await page.unroute("**/api/desk/exit-job-status");
    await page.route("**/api/desk/exit-job-status", (r) => json(r, EXIT_LATE));
    await page.reload();
    await expect(page.getByTestId("td-exit-job")).toHaveAttribute("data-status", "late", SLOW);
    await expect(page.getByTestId("td-exit-job")).toContainText("Exit check late: The exit check due at Mon 27 Oct 20:45 IST has not been recorded yet.");
    await page.unroute("**/api/desk/exit-job-status");
    await page.route("**/api/desk/exit-job-status", (r) => json(r, { detail: "MOCK: down" }, 500));
    await page.reload();
    await expect(page.getByTestId("td-exit-job")).toHaveAttribute("data-status", "error", SLOW);
    await expect(page.getByTestId("td-exit-job")).toContainText("unavailable");
  });

  test("TD-42 the paper account's corrections: the count in force, and the list on request (none: nothing shown)", async ({ page }) => {
    // GET /api/desk/paper-account/corrections, in the shape of the staging answer of 27 Oct (ids shortened; MOCK symbols)
    const corrections = { count: 2, truncated: false, append_only: true, note: "Corrections are added to the ledger, never edited or deleted.",
      counts: { in_force: 2, excluded: 1, voided: 1, reverted: 0, by_reason_code: {} },
      corrections: [
        { id: "reconcile:closed_pnl_missing:1", at: "2026-10-27T01:22:00+00:00", reason_code: "closed_pnl_missing", reason: "A closed trade had no P&L on record", decision: "void", kind: "owner_decision", symbol: "FIXA", cash_delta_rs: 0, blocked_delta_rs: 0, in_force: true },
        { id: "reconcile:closed_pnl_not_in_cash:2", at: "2026-10-27T01:22:00+00:00", reason_code: "closed_pnl_not_in_cash", reason: "A closed trade's P&L is not in cash", decision: "exclude", kind: "owner_decision", symbol: "FIXB", cash_delta_rs: 0, blocked_delta_rs: 0, in_force: true },
      ] };
    await setup(page, { corrections });
    await page.goto(TD("open"));
    await expect(page.getByTestId("td-corrections-count")).toHaveText("Paper-account corrections: 2 in force (1 excluded, 1 voided)", SLOW);
    await page.getByTestId("td-corrections-toggle").click();
    await expect(page.getByTestId("td-correction")).toHaveText(["FIXA: A closed trade had no P&L on record · void", "FIXB: A closed trade's P&L is not in cash · exclude"]);
    await page.unroute("**/api/desk/paper-account/corrections");
    await page.route("**/api/desk/paper-account/corrections", (r) => json(r, { corrections: [], count: 0, counts: { in_force: 0 } }));
    await page.reload();
    await expect(page.getByTestId("td-header")).toBeVisible(SLOW);
    await expect(page.getByTestId("td-acct-cash")).toHaveText(rs0(ACCOUNT.cash_rs));
    await expect(page.getByTestId("td-corrections")).toHaveCount(0);
  });

  test("TD-6 equity unknown: said with the reason, never ₹0", async ({ page }) => {
    await setup(page, { profile: PROFILE_UNKNOWN });
    await page.goto(TD("open"));
    await expect(page.getByTestId("td-acct-equity")).toHaveText("Unknown", SLOW);
    await expect(page.getByTestId("td-header")).toContainText("NOMARK has no end-of-day mark");
    await expect(page.getByTestId("td-open-risk")).toHaveText("Open risk unknown of 3% (NOMARK has no end-of-day mark)");
    await expect(page.getByTestId("td-acct-equity")).not.toHaveText(/₹0\b/);
  });
});

// ── navigation and Open & pending ────────────────────────────────────────

test.describe("MOCK — not real data: Trade Desk · Open & pending", () => {
  test("NV-1 / NV-2 / TD-7 five sections in the design's order; ?tab=trade opens AI Scanner › Ranked candidates; sub-views and the four-deep crumb", async ({ page }) => {
    await setup(page);
    await page.goto(`${DESK}?tab=trade`);
    await expect.poll(() => params(page).get("view")).toBe("scanner");
    await expect.poll(() => params(page).get("sub")).toBe("ranked");
    await expect(page.getByTestId("desk-views").getByRole("button")).toHaveText(["AI Scanner", "Chart Analysis", "Strategy Lab", "Paper Trading", "Watchlists"]);
    const trail = page.getByTestId("desk-trail");
    await expect(trail).toHaveText(/^▸Trading desk›Trade Desk›AI Scanner›Ranked candidates$/);
    const SUBS: Record<string, string[]> = {
      scanner: ["Ranked candidates", "Signal library & sources", "Scorecard"], chart: ["Live chart", "Signal record"],
      lab: ["Build a trade", "Backtest & validation"], paper: ["Live desk", "Trade journal"], watchlists: [],
    };
    for (const [view, labels] of Object.entries(SUBS)) {
      await page.getByTestId(`desk-view-${view}`).click();
      await expect.poll(() => params(page).get("view")).toBe(view);
      if (!labels.length) {
        await expect(page.getByTestId("desk-subviews")).toHaveCount(0);
        continue;
      }
      await expect(page.getByTestId("desk-subviews").getByRole("button")).toHaveText(labels);
      await expect(page.getByTestId("desk-subviews").getByRole("button").first()).toHaveAttribute("aria-pressed", "true");
    }
    await page.getByTestId("desk-view-paper").click();
    await page.getByTestId("desk-sub-journal").click();
    await expect(trail).toHaveText(/^▸Trading desk›Trade Desk›Paper Trading›Trade journal$/);
    await expect(page.getByTestId("td-view-journal")).toBeVisible(SLOW);
    await trail.getByTestId("desk-trail-view").click();
    await expect.poll(() => params(page).get("sub")).toBe("live");
  });

  test("NV-3 / NV-4 old URLs land in their sections; Watchlists moved from Market Desk", async ({ page }) => {
    await setup(page);
    const cases: Array<[string, string, string | null, Record<string, string>?]> = [
      ["?tab=trade&view=paper", "paper", "live"], ["?tab=trade&view=open", "paper", "live"], ["?tab=trade&view=closed", "paper", "journal"],
      ["?tab=trade&view=new", "lab", "build"], ["?tab=fno&lab=strategies&lab_sym=NIFTY", "lab", "build", { section: "fno", lab_sym: "NIFTY" }],
      ["?tab=more&view=strategy&mode=stock&sym=INFY", "lab", "build", { mode: "stock", sym: "INFY" }], ["?tab=market&view=watchlists", "watchlists", null],
    ];
    for (const [from, view, sub, extra] of cases) {
      await page.goto(`${DESK}${from}`);
      await expect.poll(() => params(page).get("tab"), from).toBe("trade");
      await expect.poll(() => params(page).get("view"), from).toBe(view);
      await expect.poll(() => params(page).get("sub"), from).toBe(sub);
      for (const [k, v] of Object.entries(extra ?? {})) expect(params(page).get(k), `${from} ${k}`).toBe(v);
    }
    await expect(page.getByTestId("desk-panel-watchlists")).toBeVisible(SLOW);
    await page.getByTestId("desk-tab-market").click();
    await expect(page.getByTestId("desk-views").getByRole("button")).toHaveText(["Market Intelligence", "Smart Money", "Sector Rotation", "Stock Research", "Screener"]);
  });

  test("TD-8 / TD-9 pending entries with rule and validity; open positions with state, net P/L and plan id", async ({ page }) => {
    await setup(page);
    await page.goto(TD("open"));
    await expect(page.getByTestId("td-open-lead")).toHaveText("2 cash positions and 1 F&O structure open, 1 entry pending.", SLOW);
    const pend = page.getByTestId("td-pending");
    await expect(pend.getByTestId("td-pending-rule")).toHaveText(`Break above ₹${n2(1655)} · valid 3 sessions`);
    await expect(pend.getByTestId("td-pending-state")).toHaveText(/waiting for entry/i);
    await expect(pend.getByTestId("td-row-plan")).toHaveText("tp_pending0001");
    const pos = page.getByTestId("td-positions");
    const infy = pos.getByRole("row").filter({ hasText: "INFY" });
    await expect(infy.getByTestId("td-open-state")).toHaveText(/position open/i);
    await expect(infy.getByTestId("td-open-qty")).toHaveText("150");
    await expect(infy.getByTestId("td-open-stop")).toHaveText(`₹${n2(1490)}`);
    await expect(infy.getByTestId("td-open-net")).toHaveText(`+${rs0(3642.6)}`);
    await expect(infy.getByTestId("td-row-plan")).toHaveText(CASH_PLAN.plan_id);
    await expect(pos).toContainText("net of trading costs, before income tax");
  });

  test("TD-10 the F&O structure: every leg, payoff-v2 figures from the stored legs, Greeks unavailable, days to expiry", async ({ page }) => {
    const seen = await setup(page);
    await page.goto(TD("open"));
    const card = page.getByTestId("td-structure");
    await expect(card).toHaveCount(1, SLOW);
    await expect(card.getByTestId("td-legs-row")).toHaveCount(4);
    for (let i = 0; i < LEGS.length; i++) {
      const row = card.getByTestId("td-legs-row").nth(i);
      await expect(row.getByTestId("td-legs-contract")).toHaveText(`${new Intl.NumberFormat("en-IN").format(LEGS[i].strike)} ${LEGS[i].option_type === "call" ? "CE" : "PE"}`);
      await expect(row.getByTestId("td-legs-entry")).toHaveText(`₹${n2(LEGS[i].entry_price)}`);
      await expect(row.getByTestId("td-legs-mark")).toContainText(`₹${n2(LEGS[i].mark)}`);
      await expect(row.getByTestId("td-legs-pnl")).toHaveText(`${LEGS[i].pnl_rs > 0 ? "+" : "−"}${rs0(Math.abs(LEGS[i].pnl_rs))}`);
    }
    await expect(card.getByTestId("td-structure-net")).toHaveText(`−${rs0(217.9)}`);
    await expect(card.getByTestId("td-structure-figures")).toHaveAttribute("data-state", "ok");
    await expect(card.getByTestId("td-fig-max-profit")).toHaveText(`+${rs0(3206.25)}`);
    await expect(card.getByTestId("td-fig-max-loss")).toHaveText(`−${rs0(4293.75)}`);
    await expect(card.getByTestId("td-fig-worst")).toHaveText(`−${rs0(4410.5)}`);
    await expect(card.getByTestId("td-fig-breakevens")).toHaveText(`${n2(24342.75)} · ${n2(24857.25)}`);
    await expect(card.getByTestId("td-fig-greeks")).toHaveText("unavailable");
    const today = new Date().toLocaleDateString("en-CA", { timeZone: "Asia/Kolkata" });
    const dte = Math.round((Date.parse(`${EXPIRY}T00:00:00Z`) - Date.parse(`${today}T00:00:00Z`)) / 86_400_000);
    await expect(card.getByTestId("td-fig-dte")).toHaveText(`${dte}d`);
    // The payoff route got the trade's STORED legs and entry premiums, nothing worked out in the browser.
    const req = seen.payoffs.find((p) => (p.legs as unknown[]).length === 4) as { underlying: string; reference_price: number; as_of: string; legs: Array<Record<string, unknown>> };
    expect(req).toBeTruthy();
    expect(req.underlying).toBe("NIFTY");
    expect(req.reference_price).toBe(24600);
    expect(req.as_of).toBe("2026-10-21");
    expect(req.legs.map((l) => [l.kind, l.side, l.quantity, l.lot_size, l.entry_price, l.strike, l.option_type, l.expiry]))
      .toEqual(LEGS.map((l) => ["option", l.side, 1, 75, l.entry_price, l.strike, l.option_type, EXPIRY]));
  });

  test("TD-11 roll on the F&O row: the preview, and a refused roll in the route's words", async ({ page }) => {
    await setup(page);
    await page.goto(TD("open"));
    await page.getByTestId("td-structure").getByTestId("td-roll-open").click(SLOW);
    await expect(page.getByTestId("td-roll-refused")).toHaveAttribute("data-code", "roll_chain_not_ready");
    await expect(page.getByTestId("td-roll-refused")).toContainText("Cannot roll: The 27 Oct F&O bhavcopy is published after 22:15 IST");
  });

  test("TD-12 a trade without a mark says so; the list says prices could not all be read", async ({ page }) => {
    await setup(page, { bookExtra: { marks_error: "prices_partially_unavailable" } });
    await page.goto(TD("open"));
    await expect(page.getByTestId("td-marks-error")).toContainText("Some end-of-day prices could not be read", SLOW);
    const row = page.getByTestId("td-positions").getByRole("row").filter({ hasText: "NOMARK" });
    await expect(row.getByTestId("td-open-last")).toHaveText("no mark");
    await expect(row.getByTestId("td-open-net")).toHaveText("—");
  });

  test("TD-13 no trades: the empty state links to Market Overview and New trade", async ({ page }) => {
    await setup(page, { trades: [] });
    await page.goto(TD("open"));
    await expect(page.getByTestId("td-open-empty")).toBeVisible(SLOW);
    await page.getByTestId("td-empty-new").click();
    await expect.poll(() => params(page).get("view")).toBe("lab");
    await page.goto(TD("open"));
    await page.getByTestId("td-empty-overview").click(SLOW);
    await expect.poll(() => params(page).get("tab")).toBe("overview");
  });
});

// ── the journal drawer ───────────────────────────────────────────────────

test.describe("MOCK — not real data: Trade Desk · the journal drawer", () => {
  test("TD-14 / TD-15 / TD-16 / TD-17 / TD-18 / NV-5 a row opens Trade journal: timeline, fills, the desk-cost-v2 bridge, stop history", async ({ page }) => {
    await setup(page);
    await page.goto(TD("open"));
    await page.getByTestId("td-positions").getByRole("row").filter({ hasText: "INFY" }).click(SLOW);
    const d = page.getByRole("region", { name: "Trade journal · INFY" });
    await expect(d).toBeVisible();
    await expect(d.getByTestId("td-journal-state")).toHaveText(/position open/i);
    const tr = d.getByTestId("td-journal-transition");
    await expect(tr).toHaveCount(3);
    await expect(tr.nth(2)).toHaveAttribute("data-to", "POSITION_OPEN");
    await expect(tr.nth(2)).toContainText("ENTRY_TRIGGERED → POSITION_OPEN");
    await expect(tr.nth(2).getByTestId("td-journal-transition-meta")).toHaveText("source desk · rules desk-paper-v2");
    await expect(d.getByTestId("td-journal-fill-entry-price")).toHaveText(`₹${n2(1512.4)}`);
    const bridge = d.getByTestId("td-journal-bridge");
    await expect(bridge.getByTestId("td-bridge-gross")).toContainText(`+${rs0(3855)}`);
    for (const [k, label] of [["brokerage", "Brokerage"], ["stt", "STT"], ["exchange", "Exchange charges"], ["sebi", "SEBI fee"], ["stamp", "Stamp duty"], ["gst", "GST"], ["slippage", "Slippage"]] as const) {
      await expect(bridge.getByTestId(`td-bridge-${k}`)).toHaveText(`${label}−₹${n2(BREAKDOWN[k])}`);
    }
    await expect(bridge.getByTestId("td-bridge-total")).toHaveText(`Total costs−₹${n2(212.4)}`);
    await expect(bridge.getByTestId("td-bridge-net-value")).toHaveText(`+${rs0(3642.6)}`);
    await expect(bridge.getByTestId("td-bridge-note")).toContainText("Net, before income tax. Cost card desk-cost-v2");
    await expect(bridge.getByTestId("td-bridge-note")).toContainText("slippage 0.05% a side, charged as a cost line");
    const stops = d.getByTestId("td-journal-stop");
    await expect(stops).toHaveCount(2);
    await expect(stops.nth(1)).toContainText(`₹${n2(1490)} · set at the 24 Oct close, in force from the next session · raised by the ATR trail`);
    await expect(page).toHaveURL(/[?&]sub=journal&trade=pt-open/);
    await page.getByTestId("desk-sub-live").click();
    await page.getByTestId("td-pending").getByRole("row").filter({ hasText: "HDFCBANK" }).click();
    await expect(page.getByRole("region", { name: "Trade journal · HDFCBANK" })).toBeVisible();
    await expect(page.getByTestId("td-journal-fill-entry-price")).toHaveText("not filled");
    // NV-5: the picker switches trades.
    await page.getByTestId("td-journal-pick").selectOption("pt-open");
    await expect(page.getByRole("region", { name: "Trade journal · INFY" })).toBeVisible();
  });

  test("TD-19 exit flags: both touched → stop assumed; gap through the stop → filled at the open; no AMBIGUOUS", async ({ page }) => {
    await setup(page);
    await page.goto(TD("closed"));
    await page.getByTestId("td-closed").getByRole("row").filter({ hasText: "AXISBANK" }).click(SLOW);
    const d = page.getByTestId("td-journal");
    await expect(d.getByTestId("td-journal-flag")).toHaveAttribute("data-code", "both_in_range");
    await expect(d.getByTestId("td-journal-flag")).toContainText(`Stop and target both touched on 24 Oct: stop assumed. ${BOTH}`);
    await expect(d).not.toContainText(/ambiguous/i);
    await page.getByTestId("td-closed").getByRole("row").filter({ hasText: "TCS" }).click();
    await expect(page.getByTestId("td-journal").getByTestId("td-journal-flag")).toContainText(`Gapped through the stop: filled at the open. ${GAP}`);
  });

  test("TD-20 the journal links to Chart Analysis › Live chart and to the plan's decision card", async ({ page }) => {
    await setup(page);
    await page.goto(TD("open"));
    await page.getByTestId("td-positions").getByRole("row").filter({ hasText: "INFY" }).click(SLOW);
    await page.getByTestId("td-journal-plan").click();
    await expect(page.getByTestId("td-journal-plan-card")).toContainText(CASH_PLAN.plan_id);
    await expect(page.getByTestId("td-journal-dc")).toHaveAttribute("data-store", "read", SLOW);
    await page.getByTestId("td-journal-chart").click();
    await expect.poll(() => params(page).get("tab")).toBe("trade");
    await expect.poll(() => params(page).get("view")).toBe("chart");
    expect(params(page).get("sub")).toBe("live");
    expect(params(page).get("sym")).toBe("INFY");
  });

  test("TD-21 the F&O journal: legs, payoff figures, events and roll", async ({ page }) => {
    await setup(page);
    await page.goto(TD("open"));
    await page.getByTestId("td-structure-journal").click(SLOW);
    const d = page.getByRole("region", { name: "Trade journal · NIFTY" });
    await expect(d.getByTestId("td-journal-legs-row")).toHaveCount(4);
    await expect(d.getByTestId("td-fig-max-loss")).toHaveText(`−${rs0(4293.75)}`);
    await expect(d.getByTestId("td-journal-event")).toHaveCount(1);
    await expect(d.getByTestId("td-journal-roll-open")).toBeVisible();
    await expect(d.getByTestId("td-bridge-net-value")).toHaveText(`−${rs0(217.9)}`);
  });
});

// ── Closed & journal ─────────────────────────────────────────────────────

test.describe("MOCK — not real data: Trade Desk · Closed & journal", () => {
  test("TD-22 / TD-23 closed trades with exit reason, net before tax; the summary; a row opens the drawer", async ({ page }) => {
    await setup(page);
    await page.goto(TD("closed"));
    await expect(page.getByTestId("td-closed-rows")).toHaveText("2", SLOW);
    const axis = page.getByTestId("td-closed").getByRole("row").filter({ hasText: "AXISBANK" });
    await expect(axis.getByTestId("td-closed-reason")).toHaveAttribute("data-reason", "stop");
    await expect(axis.getByTestId("td-closed-reason")).toHaveAttribute("data-flagged", "true");
    await expect(axis.getByTestId("td-closed-net")).toHaveText(`−${rs0(3360.1)}`);
    await expect(page.getByTestId("td-closed-net-total")).toHaveText(`−${rs0(4800.2)}`);
    await expect(page.getByTestId("td-view-closed")).toContainText("Net before income tax");
    await axis.click();
    await expect(page.getByRole("region", { name: "Trade journal · AXISBANK" })).toBeVisible();
  });
});

// ── New trade ────────────────────────────────────────────────────────────

test.describe("MOCK — not real data: Trade Desk · New trade", () => {
  test("TD-24 no idea open: the ticket points to Market Overview › Top AI ideas", async ({ page }) => {
    await setup(page);
    await page.goto(TD("new"));
    await expect(page.getByTestId("td-ticket-none")).toBeVisible(SLOW);
    await page.getByTestId("td-ticket-overview").click();
    await expect.poll(() => params(page).get("tab")).toBe("overview");
  });

  test("TD-25 / TD-26 the ticket's size is account_size, with no slider or size field; allowed → the contract body with an Idempotency-Key", async ({ page }) => {
    const risk = CARD.cash.allowed.trade_plan_response.risk_decision;
    const sent = CARD.cash.allowed.sent;
    const trade = cash({ id: "t-allowed", symbol: sent.symbol, quantity: sent.quantity, entry_price: sent.entry_price, stop_price: sent.stop_price, target_price: sent.target_price, plan_ref: sent.plan_ref, state: "POSITION_OPEN" });
    const seen = await setup(page, { post: [{ status: 201, body: { trade, risk } }] });
    await page.goto(TD("new", `&tp=${CASH_PLAN.plan_id}${SRC}`));
    const ticket = page.getByTestId("td-ticket");
    const size = ticket.getByTestId("td-ticket-size");
    await expect(size).toHaveAttribute("data-qty", String(CARD.cash.trade_plan_response.account_size.quantity), SLOW);
    await expect(size).toContainText("666 shares");
    await expect(size).toContainText("The risk service’s own size (account_size)");
    await expect(ticket.locator('input, [role="slider"], input[type="range"]')).toHaveCount(0);
    await ticket.getByTestId("td-ticket-submit").click();
    await expect(ticket.getByTestId("td-ticket-answer")).toHaveAttribute("data-outcome", "allow");
    await expect(ticket.getByTestId("td-ticket-answer-text")).toHaveText("Allowed: 666 ICICIBANK shares recorded as a paper trade (t-allowed).");
    expect(seen.posts).toEqual([CARD.cash.allowed.sent]);
    expect(seen.keys[0]).toMatch(/^.{8,64}$/);
  });

  test("TD-27 reduced: 113 → 83 with the reasons and \"Accept 83?\"; accepting sends the same body at 83", async ({ page }) => {
    // MOCK edit: the plan answer sized at the contract's submitted 113, so the ticket sends the contract's reduced body.
    const plan = clone(CARD.cash.trade_plan_response);
    plan.account_size.quantity = CARD.cash.reduced.sent.quantity;
    const seen = await setup(page, { plan, post: [{ status: 409, body: { detail: CARD.cash.reduced.paper_detail } }, { status: 201, body: { trade: { id: "t-83" }, risk: null } }] });
    await page.goto(TD("new", `&tp=${CASH_PLAN.plan_id}${SRC}`));
    await page.getByTestId("td-ticket-submit").click(SLOW);
    const ans = page.getByTestId("td-ticket-answer");
    await expect(ans).toHaveAttribute("data-outcome", "reduce");
    await expect(ans.getByTestId("td-ticket-answer-text")).toHaveText("Reduced 113 → 83. Nothing was recorded.");
    await expect(ans.getByTestId("td-ticket-reason").first()).toHaveText(CARD.cash.reduced.paper_detail.reasons[0].message);
    await expect(ans.getByTestId("td-ticket-reduce-accept")).toHaveText("Accept 83?");
    await ans.getByTestId("td-ticket-reduce-accept").click();
    await expect(page.getByTestId("td-ticket-answer")).toHaveAttribute("data-outcome", "allow");
    expect(seen.posts).toEqual([CARD.cash.reduced.sent, { ...CARD.cash.reduced.sent, quantity: 83 }]);
    expect(seen.keys[0]).not.toBe(seen.keys[1]);
  });

  test("TD-28 blocked: the reason, and no accept", async ({ page }) => {
    await setup(page, { post: [{ status: 409, body: { detail: CARD.cash.blocked.paper_detail } }] });
    await page.goto(TD("new", `&tp=${CASH_PLAN.plan_id}${SRC}`));
    await page.getByTestId("td-ticket-submit").click(SLOW);
    const ans = page.getByTestId("td-ticket-answer");
    await expect(ans).toHaveAttribute("data-outcome", "block");
    await expect(ans.getByTestId("td-ticket-answer-text")).toHaveText("Blocked by the risk service. Nothing was recorded.");
    await expect(ans.getByTestId("td-ticket-reason")).toHaveText([CARD.cash.blocked.paper_detail.reasons[0].message]);
    await expect(ans).toContainText("only an admin clears it");
    await expect(page.getByTestId("td-ticket-reduce-accept")).toHaveCount(0);
  });

  test("TD-29 / TD-30 a duplicate and an impossible fill, in plain words", async ({ page }) => {
    const dup = { code: "duplicate_open_trade", existing_trade_id: "pt-icici", symbol: "ICICIBANK",
      message: "You already have an open paper trade in ICICIBANK (paper trade pt-icici, opened 2026-10-20T05:00:00+00:00). Adding to a position is not supported yet; close it first." };
    const unfillable = { code: "entry_not_tradable",
      message: "The entry ₹1,200.00 is above the last completed session's range (2026-10-19: ₹1,150.00–₹1,190.00), so it could not be filled at once. Record it with the entry rule \"break above\" to wait for that level." };
    await setup(page, { post: [{ status: 409, body: { detail: dup } }, { status: 422, body: { detail: unfillable } }] });
    await page.goto(TD("new", `&tp=${CASH_PLAN.plan_id}${SRC}`));
    await page.getByTestId("td-ticket-submit").click(SLOW);
    await expect(page.getByTestId("td-ticket-answer")).toHaveAttribute("data-outcome", "duplicate");
    await expect(page.getByTestId("td-ticket-answer-text")).toHaveText("ICICIBANK is already open (paper trade pt-icici): not added twice.");
    await page.getByTestId("td-ticket-submit").click();
    await expect(page.getByTestId("td-ticket-answer")).toHaveAttribute("data-outcome", "unfillable");
    await expect(page.getByTestId("td-ticket-answer-text")).toHaveText(`Not recorded: ${unfillable.message}`);
  });

  test("TD-31 / TD-32 the F&O builder offers only the backend catalog; the first wave is marked; payoff with Greeks", async ({ page }) => {
    const seen = await setup(page);
    await page.goto(TD("new"));
    await expect(page.getByTestId("td-template")).toHaveCount(TEMPLATES.templates.length, SLOW);
    const wave = page.getByTestId("td-first-wave-item");
    await expect(wave).toHaveText([
      "Covered call: not in the backend catalog yet", "Bull put credit spread: not in the backend catalog yet", "Bear call credit spread: not in the backend catalog yet",
      "Iron condor: available", "Protective put / collar: not in the backend catalog yet",
    ]);
    const fno = page.getByTestId("desk-panel-fno");
    await expect(fno.getByTestId("desk-builder-tile-buy_call")).toBeVisible(SLOW);
    await expect(fno.getByTestId("desk-builder-tile-bull_call_spread")).toBeVisible();
    await expect(fno.getByTestId("desk-builder-tile-sell_put")).toHaveCount(0);
    await expect(fno.getByTestId("desk-builder-tile-bull_put_spread")).toHaveCount(0);
    await fno.getByTestId("desk-builder-view-neutral").click();
    await expect(fno.getByTestId("desk-builder-tile-iron_butterfly")).toHaveCount(0);
    await fno.getByTestId("desk-builder-tile-iron_condor").click();
    await expect(fno.getByTestId("payoff-summary")).toBeVisible(SLOW);
    await expect(fno.getByTestId("payoff-leg-greeks")).toBeVisible();
    expect(seen.payoffs.some((p) => (p.legs as unknown[]).length === 4 && !!p.pre_expiry)).toBe(true);
  });

  test("TD-33 backtest provenance: liquid-eq-v1 point-in-time, code, data to, cost model, slippage sweep; an index shows survivorship", async ({ page }) => {
    const seen = await setup(page);
    await page.goto(TD("backtest"));
    const bt = page.getByTestId("td-backtest");
    await expect(bt.getByTestId("td-bt-strategy")).toBeVisible(SLOW);
    await bt.getByTestId("td-bt-from").fill("2025-10-27");
    await bt.getByTestId("td-bt-to").fill("2026-10-24");
    await bt.getByTestId("td-bt-run").click();
    await expect(bt.getByTestId("td-bt-universe")).toHaveText("liquid-eq-v1 (point-in-time, no survivorship)");
    await expect(bt.getByTestId("td-bt-code")).toHaveText("abc1234");
    await expect(bt.getByTestId("td-bt-data")).toHaveText("26 Oct 2026");
    await expect(bt.getByTestId("td-bt-cost")).toHaveText("desk-cost-v2");
    await expect(bt.getByTestId("td-bt-provenance")).toContainText("slippage 0.05% a side");
    await expect(bt.getByTestId("td-bt-sweep-row")).toHaveCount(4);
    await expect(bt.getByTestId("td-bt-survivorship")).toHaveCount(0);
    expect(seen.backtests[0]).toEqual({ id: "st-1", body: { from_date: "2025-10-27", to_date: "2026-10-24" } });
    await bt.getByTestId("td-bt-strategy").selectOption("st-nifty");
    await bt.getByTestId("td-bt-run").click();
    await expect(bt.getByTestId("td-bt-survivorship")).toContainText("Survivorship bias: NIFTY 50 applied with its latest constituents");
  });
});

// ── PaperDesk's behaviours, on the Trade Desk (its old mount is replaced by this tab) ──────────────────

test.describe("MOCK — not real data: Trade Desk · close, errors, records", () => {
  test("TD-37 Close asks first; Cancel sends nothing; Yes posts {} to …/{id}/close and the list is read again", async ({ page }) => {
    const seen = await setup(page);
    await page.goto(TD("open"));
    await page.getByTestId("td-positions").getByRole("row").filter({ hasText: "INFY" }).click(SLOW);
    await page.getByTestId("td-journal-close").click();
    await expect(page.getByTestId("td-journal-close-confirm")).toContainText(`Close the INFY paper trade at its last end-of-day close (₹${n2(1538.1)})? It is simulated: no order is placed.`);
    await page.getByTestId("td-journal-close-no").click();
    expect(seen.closes).toHaveLength(0);
    await page.getByTestId("td-journal-close").click();
    const before = seen.listGets;
    await page.getByTestId("td-journal-close-yes").click();
    await expect.poll(() => seen.closes.length).toBe(1);
    expect(seen.closes[0]).toEqual({ path: "/api/desk/paper-trades/pt-open/close", body: {} });
    await expect.poll(() => seen.listGets).toBeGreaterThan(before);
    // A waiting entry is cancelled, not closed.
    await page.getByTestId("desk-sub-live").click();
    await page.getByTestId("td-pending").getByRole("row").filter({ hasText: "HDFCBANK" }).click();
    await expect(page.getByTestId("td-journal-close")).toHaveText("Cancel paper trade");
  });

  test("TD-38 a refused close keeps the server's words, and the confirmation stays usable", async ({ page }) => {
    const seen = await setup(page, { close: { status: 409, body: { detail: "trade_already_closed" } } });
    await page.goto(TD("open"));
    await page.getByTestId("td-positions").getByRole("row").filter({ hasText: "INFY" }).click(SLOW);
    await page.getByTestId("td-journal-close").click();
    await page.getByTestId("td-journal-close-yes").click();
    await expect(page.getByTestId("td-journal-close-confirm").getByRole("alert")).toHaveText("That paper trade is already closed. (trade_already_closed)");
    expect(seen.closes).toHaveLength(1);
    await expect(page.getByTestId("td-journal-close-yes")).toBeEnabled();
  });

  test("TD-39 the list fails (502) or is not enabled (403): said, never an empty book", async ({ page }) => {
    await setup(page, { list: { status: 502, body: { detail: "upstream_unavailable" } } });
    await page.goto(TD("open"));
    await expect(page.getByTestId("td-trades-error").getByRole("alert")).toContainText("Your paper trades didn’t load", { timeout: 20_000 });
    await expect(page.getByTestId("td-open-empty")).toHaveCount(0);
    await page.unroute("**/api/desk/paper-trades*");
    await page.route("**/api/desk/paper-trades*", (r) => json(r, { detail: "forbidden" }, 403));
    await page.reload();
    await expect(page.getByTestId("td-trades-error")).toContainText("Your paper trades is not enabled for this account", SLOW);
  });

  test("TD-40 a strategy row without its legs or signal is a loud contract error, not a dropped trade", async ({ page }) => {
    const broken = { ...CONDOR, legs: [] };
    await setup(page, { trades: [OPEN, broken] });
    await page.goto(TD("open"));
    await expect(page.getByTestId("td-trades-error")).toContainText("unexpected response shape", { timeout: 20_000 });
    await expect(page.getByTestId("td-positions")).toHaveCount(0);
  });

  test("TD-41 a flat-cost trade's bridge shows brokerage and slippage only; research exit rules and an unknown exit reason are shown as sent", async ({ page }) => {
    const flat = cash({ id: "pt-flat", symbol: "FLATCO", status: "closed", state: "CLOSED", exit_price: 104, exit_reason: "weird_exit", exit_session: "2026-10-24", closed_at: "2026-10-24T15:30:00+00:00",
      realized_pnl_rs: 40, gross_pnl_rs: 40, costs_rs: 41.04, net_pnl_rs: -1.04, last_close: null, unrealized_pnl_rs: null,
      cost_model: { name: "flat", version: "desk-flat-v1", slippage_pct_per_side: 0.05, brokerage_rs_per_side: 20 },
      costs_breakdown: { brokerage: 40, stt: 0, exchange: 0, sebi: 0, stamp: 0, gst: 0, slippage: 1.04, total: 41.04 },
      exit_rules: [{ code: "trailing_atr", version: "exit-rules-v1", label: "ATR trailing stop (2×ATR14)", params: {} }] });
    await setup(page, { trades: [flat] });
    await page.goto(TD("closed"));
    const row = page.getByTestId("td-closed").getByRole("row").filter({ hasText: "FLATCO" });
    await expect(row.getByTestId("td-closed-reason")).toHaveText("weird_exit", SLOW);
    await row.click();
    const bridge = page.getByTestId("td-journal-bridge");
    await expect(bridge.getByTestId("td-bridge-brokerage")).toHaveText(`Brokerage−₹${n2(40)}`);
    await expect(bridge.getByTestId("td-bridge-slippage")).toHaveText(`Slippage−₹${n2(1.04)}`);
    for (const k of ["stt", "exchange", "sebi", "stamp", "gst"]) await expect(bridge.getByTestId(`td-bridge-${k}`)).toHaveCount(0);
    await expect(bridge.getByTestId("td-bridge-note")).toContainText("Cost card desk-flat-v1");
    await expect(page.getByTestId("td-journal-rec-exit-rules")).toHaveText("ATR trailing stop (2×ATR14) (exit-rules-v1) · opt-in research rule");
    await expect(page.getByTestId("td-journal-rec-exit")).toContainText("weird_exit");
  });
});

// ── PR B: AI Scanner and Chart Analysis ──────────────────────────────────

const SCORECARD = load("desk-idea-scorecard.json"); // staging's real GET /api/desk/idea-scorecard body of 27 Oct (#375)

test.describe("MOCK — not real data: Trade Desk · AI Scanner and Chart Analysis", () => {
  test("AS-1 Ranked candidates: the Top 10 cards and every scanner candidate; the old scanner URLs land here", async ({ page }) => {
    await setup(page);
    for (const from of ["?tab=scanner", "?tab=overview&section=scanner", "?tab=trade"]) {
      await page.goto(`${DESK}${from}`);
      await expect.poll(() => params(page).get("view"), from).toBe("scanner");
      await expect.poll(() => params(page).get("sub"), from).toBe("ranked");
    }
    await expect(page.getByTestId("desk-panel-top10")).toBeVisible(SLOW);
    await expect(page.getByTestId("desk-section-scanner-title")).toHaveText("All scanner candidates");
    await expect(page.getByTestId("desk-panel-scanner")).toBeAttached(SLOW);
    await page.getByTestId("desk-tab-overview").click();
    await expect(page.getByTestId("market-overview")).toBeVisible(SLOW);
    await expect(page.getByTestId("desk-scanner-toggle")).toHaveCount(0);
  });

  test("AS-2 Signal library & sources: the scanner's categories with their rules, and Chartink sources", async ({ page }) => {
    await setup(page);
    await page.goto(`${DESK}?tab=trade&view=scanner&sub=library`);
    const cats = page.getByTestId("desk-signal-category");
    await expect(cats.first()).toBeVisible(SLOW);
    await expect(page.getByTestId("desk-signal-categories")).toContainText("Breakouts");
    await expect(page.getByTestId("desk-signal-categories")).toContainText("not a prediction");
    await expect(page.getByTestId("desk-section-chartink-title")).toHaveText("Chartink sources");
    // The only place: Market Desk › Screener has no copy, and its old ?section=chartink URL lands here.
    await page.goto(`${DESK}?tab=market&view=screener&section=chartink`);
    await expect.poll(() => params(page).get("sub")).toBe("library");
    await page.goto(`${DESK}?tab=market&view=screener`);
    await expect(page.getByTestId("desk-panel-screener")).toBeAttached(SLOW);
    await expect(page.getByTestId("desk-section-chartink-title")).toHaveCount(0);
  });

  test("AS-3 Scorecard: the real study (no measurable skill, RS63 awaiting confirmation), then the F&O forward test", async ({ page }) => {
    await setup(page);
    await page.route("**/api/desk/idea-scorecard", (r) => json(r, SCORECARD));
    await page.goto(`${DESK}?tab=trade&view=scanner&sub=scorecard`);
    await expect(page.getByTestId("sc-verdict")).toHaveText("keep B0; the current ranking shows no measurable skill", SLOW);
    await expect(page.getByTestId("sc-body")).not.toContainText(/beats the (random )?baseline|precision@/i);
    await expect(page.getByTestId("desk-trail")).toHaveText(/^▸Trading desk›Trade Desk›AI Scanner›Scorecard$/);
    await expect(page.getByTestId("desk-section-forward-test-title")).toHaveText("F&O signal · forward test");
  });

  test("AS-4 Market Overview's \"See all ›\" opens Ranked candidates and \"Scorecard →\" opens Scorecard", async ({ page }) => {
    await setup(page);
    await page.goto(`${DESK}?tab=overview`);
    await page.getByTestId("desk-top10-see-all").click(SLOW);
    await expect.poll(() => params(page).get("view")).toBe("scanner");
    await expect.poll(() => params(page).get("sub")).toBe("ranked");
    await page.goto(`${DESK}?tab=overview`);
    await page.getByTestId("desk-top10-scorecard").click(SLOW);
    await expect.poll(() => params(page).get("sub")).toBe("scorecard");
  });

  test("CH-1 Live chart: the ticket beside the chart is the account_size one (from ?tp= or today's idea); no calculator, no slider", async ({ page }) => {
    await setup(page);
    await page.goto(`${DESK}?tab=trade&view=chart&sub=live&sym=ICICIBANK&tp=${CASH_PLAN.plan_id}`);
    const ticket = page.getByTestId("td-chart-ticket");
    await expect(ticket).toHaveAttribute("data-source", "url", SLOW);
    await expect(ticket.getByTestId("td-ticket-size")).toHaveAttribute("data-qty", "666", SLOW);
    await expect(ticket.locator('input, [role="slider"], input[type="range"]')).toHaveCount(0);
    await expect(page.getByTestId("desk-scn-out-gross")).toHaveCount(0);           // the old capital × risk-% calculator
    await page.goto(`${DESK}?tab=trade&view=chart&sub=live&sym=ICICIBANK`);
    await expect(page.getByTestId("td-chart-ticket")).toHaveAttribute("data-source", "top10", SLOW);
    await expect(page.getByTestId("td-ticket-size")).toHaveAttribute("data-qty", "666", SLOW);
  });

  test("CH-2 / CH-3 a stock with no idea has no ticket, said with the way to the ideas; Signal record is not available yet", async ({ page }) => {
    await setup(page);
    await page.goto(`${DESK}?tab=trade&view=chart&sub=live&sym=NOIDEA`);
    await expect(page.getByTestId("td-chart-ticket")).toHaveAttribute("data-source", "none", SLOW);
    await expect(page.getByTestId("td-chart-ticket")).toContainText("No idea with a plan for NOIDEA today, so there is no ticket");
    await page.getByTestId("td-chart-ticket-ideas").click();
    await expect.poll(() => params(page).get("sub")).toBe("ranked");
    await page.goto(`${DESK}?tab=trade&view=chart&sub=record`);
    await expect(page.getByTestId("desk-trade-record-pending")).toContainText("not available yet", SLOW);
  });
});

// ── data, layout, wording ────────────────────────────────────────────────

test.describe("MOCK — not real data: Trade Desk · one read, phone, wording", () => {
  test("TD-34 one GET /api/desk/paper-trades per load, across sections and sub-views", async ({ page }) => {
    const seen = await setup(page);
    await page.goto(TD("open"));
    await expect(page.getByTestId("td-structure")).toHaveCount(1, SLOW);
    await page.getByTestId("td-positions").getByRole("row").filter({ hasText: "INFY" }).click();
    await expect(page.getByTestId("td-journal")).toBeVisible();
    await page.getByTestId("desk-sub-live").click();
    await page.getByTestId("desk-view-lab").click();
    await expect(page.getByTestId("td-view-build")).toBeVisible();
    await page.getByTestId("desk-sub-backtest").click();
    await expect(page.getByTestId("td-view-backtest")).toBeVisible();
    await page.getByTestId("desk-view-paper").click();
    await expect(page.getByTestId("td-view-open")).toBeVisible();
    await page.getByTestId("desk-sub-journal").click();
    await expect(page.getByTestId("td-view-journal")).toBeVisible();
    await page.waitForTimeout(1500);
    expect(seen.listGets).toBe(1);
  });

  test("TD-35 390 px: no sideways page scroll on any sub-view or the journal; the leg table scrolls in its own box", async ({ page }) => {
    await setup(page, { phone: true });
    for (const [view, root] of [["open", "td-view-open"], ["closed", "td-view-journal"], ["new", "td-view-build"], ["backtest", "td-view-backtest"]]) {
      await page.goto(TD(view));
      await expect(page.getByTestId(root)).toBeVisible(SLOW);
      if (view === "new") await expect(page.getByTestId("td-template").first()).toBeVisible(SLOW);
      await noSideScroll(page);
    }
    await page.goto(TD("open"));
    const legs = page.getByTestId("td-structure").getByTestId("td-legs");
    await expect(legs).toBeVisible(SLOW);
    const box = await legs.evaluate((el) => ({ sw: el.scrollWidth, cw: el.clientWidth, right: el.getBoundingClientRect().right }));
    expect(box.sw).toBeGreaterThan(box.cw);
    expect(box.right).toBeLessThanOrEqual(390);
    await page.getByTestId("td-structure-journal").click();
    await expect(page.getByTestId("td-journal")).toBeVisible();
    await noSideScroll(page);
  });

  test("TD-36 wording: ideas, paper; no pick, recommend or suggest in the tab's own words", async ({ page }) => {
    await setup(page);
    await page.goto(TD("open"));
    await expect(page.getByTestId("td-structure")).toHaveCount(1, SLOW);
    expect(wordingOf(await page.getByTestId("td-tab").innerText())).not.toMatch(BANNED);
    await expect(page.getByTestId("td-rules-note")).toContainText("nothing is sent to a broker");
    await page.getByTestId("td-positions").getByRole("row").filter({ hasText: "INFY" }).click();
    expect(wordingOf(await page.getByTestId("td-journal").innerText())).not.toMatch(BANNED);
    await page.goto(TD("closed"));
    await expect(page.getByTestId("td-view-closed")).toBeVisible(SLOW);
    expect(wordingOf(await page.getByTestId("td-tab").innerText())).not.toMatch(BANNED);
    await page.goto(`${DESK}?tab=trade&view=watchlists`);
    await expect(page.getByTestId("desk-views")).toBeVisible(SLOW);
    expect(wordingOf(await page.getByTestId("desk-views").innerText())).not.toMatch(BANNED);
    await page.goto(TD("new", `&tp=${CASH_PLAN.plan_id}${SRC}`));
    await expect(page.getByTestId("td-ticket-size")).toHaveAttribute("data-qty", "666", SLOW);
    for (const id of ["td-ticket", "td-templates"]) {
      expect(wordingOf(await page.getByTestId(id).innerText()), id).not.toMatch(BANNED);
    }
    await expect(page.getByTestId("td-ticket")).toContainText("nothing is sent to a broker");
    await page.goto(TD("backtest"));
    await expect(page.getByTestId("td-backtest")).toBeVisible(SLOW);
    expect(wordingOf(await page.getByTestId("td-backtest").innerText())).not.toMatch(BANNED);
  });
});
