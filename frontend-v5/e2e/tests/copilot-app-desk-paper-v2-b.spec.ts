/**
 * One-screen Copilot app (/v5/app) — Paper Trading v2, builder B: 03 Capital allocation, 04 Portfolio risk, 05 Real-time P&L
 * (docs/scanner_paper_trading/UI_DESIGN_V2.md §2.03–§2.05, §3, §5; test cases PV2-B-UI-01 … 29 in
 * test_reports/paper_v2_ui_b_TESTCASES.md).
 *
 * MOCK — not real data. Every /api answer below is written by hand in the §7 contract's shape (policy, correlation,
 * fno-structures, the named stress scenarios) or in the shape the existing routes return (risk/account, exposures, allocation
 * recommendations, /api/desk/pnl and its stream, exits, risk controls). Account ids, symbols, sectors, reasons and numbers are
 * INVENTED; expected text is worked out here from the payloads. Production build, every /api mocked.
 */
import { test, expect, type Page, type Route } from "@playwright/test";
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";
import { mockApi, mockSingleRoute } from "../helpers/api-mock";

const json = (route: Route, body: unknown, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
const clone = <T,>(x: T): T => JSON.parse(JSON.stringify(x));
type Row = Record<string, unknown>;
const DESK = "/v5/app/trader/desk";
const at = (sub: string) => `${DESK}?tab=trade&view=paper&sub=${sub}`;
const SLOW = { timeout: 15_000 };
const SHOTS = process.env.PV2_SHOTS || "";
const BANNED = /\b(recommend\w*|picks?|suggest\w*)\b/i;
const ME = JSON.parse(fs.readFileSync(fileURLToPath(new URL("../fixtures/user-profile-onboarded.json", import.meta.url)), "utf-8")) as Row;

// ── MOCK — not real data: the paper account (routes/spt_accounts.py) and the shell's overview (§7) ─────────────────────────
const ACC = "u_pv2b_fixture";
const EQUITY = 1_012_500;
const ACCOUNTS = { accounts: [{ account_id: ACC, account: { starting_capital_rs: 1_000_000, cash_rs: 700_000 }, modes: ["off", "tracking", "approval", "auto"],
  config: { user_id: ACC, account_id: ACC, mode: "approval", version: 3, stored: true, extras: {} }, note: "MOCK" }], count: 1 };
const OVERVIEW = {
  account_id: ACC, as_of: "2026-11-05T05:40:00+00:00",
  status: { feed_state: "live", last_tick_age_s: 1.2, session: "open", kill_switch: { state: "ACTIVE", entries_blocked: false, text: "MOCK" }, policy_version: 7, mode: "approval" },
  kpis: null, pipeline: [], warnings: [], headline: null,
};

// ── MOCK — not real data: GET /api/v1/risk/account/{id} (routes/spt_risk.py) ──────────────────────────────────────────────
const riskAccount = (o: Row = {}): Row => ({
  account_id: ACC, as_of: "2026-11-05T04:00:00+00:00", error: null, equity_rs: EQUITY, equity_basis: "MOCK basis", equity_unknown_reasons: [],
  cash_rs: 700_000, available_rs: 640_000, blocked_rs: 360_000, deployed_rs: 300_000, reserved_rs: 60_000,
  pending_entries: [{ order_id: "ord-p1", symbol: "AXISBANK", reserved_rs: 60_000, order_state: "PENDING" }], reserve_bucket_rs: 101_250,
  open_risk: { rs: 18_400, basis: "MOCK open-risk basis", cap_rs: 30_375, limit_pct: 3, used_pct_of_equity: 1.8173 },
  spt_risk: { planned_rs: 12_340.5, stressed_rs: 15_890.25, entries: 3, unpriced: [], stressed_gap_pct: 1, basis: "MOCK" },
  daily_loss: { pnl_rs: -4_200, start_equity_rs: 1_016_700, loss_pct: 0.4131, limit_pct: 2, breached: false },
  weekly_loss: { pnl_rs: 6_100, start_equity_rs: 1_006_400, loss_pct: 0, limit_pct: 4, breached: false },
  drawdown: { pct: 2.5, peak_rs: 1_038_461.54, profile_halt_pct: 6, ladder: { band: "reduce", drawdown_pct: 2.5, factor: 0.5, blocks_new_entries: false, thresholds: {}, text: "MOCK" } },
  kill_switch: { state: "ACTIVE", entries_blocked: false, kill_switch: false, halted: false, reason: null, reasons: [], text: "MOCK" },
  limits: { profile: {}, limits_version: "MOCK", spt: { allocation_buckets_pct: {} }, spt_config_version: 3 },
  utilisation: { positions: { open: 4, max: 10 }, new_today: { count: 1, max: 5 },
    buckets: { equity_positional: { used_rs: 240_000, cap_rs: 455_625 }, equity_intraday: { used_rs: 0, cap_rs: 253_125 }, fno: { used_rs: 0, cap_rs: 202_500 } },
    exposure_rs: 300_000, exposure_pct_of_equity: 29.63 },
  mode: "approval", ...o,
});
// MOCK — not real data: GET /api/v1/risk/exposures/{id}
const EXPOSURES = {
  as_of: "2026-11-05T04:00:00+00:00", equity_rs: EQUITY,
  by_sector: [{ sector: "Banks", exposure_rs: 210_000, pct_of_equity: 20.74, limit_pct: 25 }, { sector: "IT", exposure_rs: 90_000, pct_of_equity: 8.89, limit_pct: 25 }],
  unclassified_exposure_rs: 0,
  by_instrument: [{ symbol: "ICICIBANK", exposure_rs: 83_000, pct_of_equity: 8.2, limit_pct: 10 }, { symbol: "TCS", exposure_rs: 90_000, pct_of_equity: 8.89, limit_pct: 10 }],
  by_category: [], total_exposure_rs: 300_000, basis: "MOCK",
};
// MOCK — not real data: GET /api/v1/risk/stress-test/{id}: the three existing scenarios, then the five named ones (§7)
const STRESS = {
  account_id: ACC, as_of: "2026-11-05T04:00:00+00:00", equity_rs: EQUITY, version: "MOCK", basis: "MOCK", unpriced: [],
  positions: [], totals: { planned_rs: 12_340.5, stressed_rs: 15_890.25, value_rs: 300_000 },
  scenarios: [
    { name: "gap_through_stop", gap_pct: 1, planned_rs: 12_340.5, stressed_rs: 15_890.25, text: "MOCK: every stop gaps 1%." },
    { name: "sector_shock", shock_pct: -5, by_sector_rs: { Banks: 9_000 }, worst_sector: "Banks", worst_loss_rs: 9_000, text: "MOCK: one sector falls 5%." },
    { name: "market_shock", results: [{ shock_pct: -3, beta: 1, beta_assumed: true, loss_rs: 8_600 }, { shock_pct: -5, beta: 1, beta_assumed: true, loss_rs: 14_300 }], text: "MOCK: the market falls." },
    { name: "index_down", label: "Nifty -2%", pnl_rs: -5_700, loss_rs: 5_700, assumption: "MOCK: beta 1 on every stock." },
    { name: "sector_gap", label: "Banks gap -3%", pnl_rs: -6_300, loss_rs: 6_300, assumption: "MOCK: the largest sector gaps 3%." },
    { name: "correlated_stops", label: "Correlated stops hit", pnl_rs: -11_200, loss_rs: 11_200, assumption: "MOCK: pairs at ρ ≥ 0.70 stop together." },
    { name: "gap_beyond_stops", label: "Gap beyond stops +25%", pnl_rs: -19_863, loss_rs: 19_863, assumption: "MOCK: every stop fills 25% worse." },
    { name: "iv_up", label: "IV +10 pts (F&O)", pnl_rs: -4_100, loss_rs: 4_100, assumption: "MOCK: every option's IV +10 points." },
  ],
};
// MOCK — not real data: GET /api/v1/allocation/recommendations/{id}
const RANKED = {
  as_of: "2026-11-05T04:00:00+00:00", mode: "approval", rank_basis: "MOCK", price_source: "MOCK",
  items: [
    { rank: 1, opportunity_id: "opp-tcs", symbol: "TCS", opportunity_score: 80, rr: { t2: 2.1 }, entry: { price: 4000 }, stop_loss: 3880, outcome: "ok",
      sizing: { quantity: 40, capital_required: 160_000, planned_risk: 4_800, blocked: [] },
      allocation: { decision: "ALLOCATION_REDUCED", requested_qty: 40, quantity: 25, capital_rs: 100_000, stressed_risk_rs: 3_100,
        reasons: [{ code: "bucket_reduced", message: "MOCK: equity positional bucket has ₹1,00,000 left." }] } },
    { rank: 2, opportunity_id: "opp-hdfc", symbol: "HDFCBANK", opportunity_score: 70, rr: { t2: 2 }, entry: { price: 1640 }, stop_loss: 1600, outcome: "ok",
      sizing: { quantity: 50, capital_required: 82_000, planned_risk: 2_000, blocked: [] },
      allocation: { decision: "ALLOCATION_REJECTED", requested_qty: 50, quantity: 0, capital_rs: 0, stressed_risk_rs: 0, reasons: [{ code: "positions_full", message: "MOCK: ten positions are open." }] } },
    { rank: 3, opportunity_id: "opp-infy", symbol: "INFY", opportunity_score: 65, rr: { t2: 2 }, entry: { price: 1600 }, stop_loss: 1560, outcome: "ok",
      sizing: { quantity: 30, capital_required: 48_000, planned_risk: 1_200, blocked: [] },
      allocation: { decision: "ALLOCATION_APPROVED", requested_qty: 30, quantity: 30, capital_rs: 48_000, stressed_risk_rs: 1_500, reasons: [] } },
    { rank: 4, opportunity_id: "opp-sbin", symbol: "SBIN", opportunity_score: 40, rr: {}, entry: {}, stop_loss: null, outcome: "rejected", explanations: ["MOCK"], sizing: null, allocation: null },
  ],
};
// MOCK — not real data: GET /api/v1/risk/correlation/{id} (§7)
const CORR = {
  account_id: ACC, symbols: ["ICICIBANK", "HDFCBANK", "TCS", "INFY"], days: 60, threshold: 0.7, basis: "MOCK: 60 daily returns, adjusted closes.",
  matrix: [[1, 0.82, 0.31, null], [0.82, 1, 0.28, 0.35], [0.31, 0.28, 1, 0.74], [null, 0.35, 0.74, 1]],
  notes: ["MOCK: INFY has 41 of 60 sessions, so its pair with ICICIBANK is not computed."],
};
// MOCK — not real data: GET /api/v1/paper/fno-structures (§7)
const leg = (side: string, contract: string, entry: number, ltp: number | null, qty: number, filled: number, pnl: number | null, pending = false) =>
  ({ side, contract, entry, ltp, filled_qty: filled, qty, pnl_rs: pnl, pending });
const sc = (a: number, b: number, c: number, d: number) => [{ name: "und_up_1", label: "Underlying +1%", pnl_rs: a }, { name: "und_down_1", label: "Underlying −1%", pnl_rs: b },
  { name: "iv_up_5", label: "IV +5 pts", pnl_rs: c }, { name: "theta_1d", label: "1-day theta", pnl_rs: d }];
const FNO = () => ({
  account_id: ACC,
  structures: [
    { id: "st-1", name: "Bull call spread", underlying: "NIFTY", underlying_ltp: 25_890, expiry: "2026-11-25", days_to_expiry: 20, lots: 1, lot_size: 75, status: "filled", hedged: true,
      max_loss_rs: 6_375, max_profit_rs: 8_625, profit_unbounded: false, breakevens: [25_085], net: { delta: 21.4, gamma: 0.0012, theta_rs_day: -310.5, vega_rs_pt: 420 },
      margin_rs: 6_375, pnl_rs: 1_275, legs: [leg("BUY", "NIFTY 25 Nov 25000 CE", 180, 222, 75, 75, 3_150), leg("SELL", "NIFTY 25 Nov 25200 CE", 95, 120, 75, 75, -1_875)],
      scenarios: sc(1_500, -1_400, 210, -310), notes: [] },
    { id: "st-2", name: "Iron condor", underlying: "BANKNIFTY", underlying_ltp: 52_010, expiry: "2026-11-25", days_to_expiry: 20, lots: 1, lot_size: 30, status: "partial", hedged: false,
      max_loss_rs: 18_500, max_profit_rs: 6_500, profit_unbounded: false, breakevens: [50_800, 53_200], net: { delta: -4.2, gamma: -0.0004, theta_rs_day: 890, vega_rs_pt: -1_250 },
      margin_rs: 95_000, pnl_rs: 2_100,
      legs: [leg("SELL", "BANKNIFTY 25 Nov 52500 CE", 210, 160, 30, 30, 1_500), leg("BUY", "BANKNIFTY 25 Nov 53500 CE", 70, null, 30, 0, null, true),
        leg("SELL", "BANKNIFTY 25 Nov 51500 PE", 190, 170, 30, 30, 600), leg("BUY", "BANKNIFTY 25 Nov 50500 PE", 60, 60, 30, 30, 0)],
      scenarios: sc(-2_200, 1_800, -1_100, 890), notes: ["MOCK: the 53500 CE is not filled yet."] },
  ],
  totals: { margin_rs: 101_375, max_loss_rs: 24_875, net: { delta: 17.2, gamma: 0.0008, theta_rs_day: 579.5, vega_rs_pt: -830 } },
  limits: { fno_max_loss_pct: 2, margin_util_pct: 50 }, basis: "MOCK: payoff at expiry and Black-Scholes Greeks.", notes: [],
});
// MOCK — not real data: the existing risk controls (routes/risk_controls.py /status, /policy)
const riskStatus = (gate: boolean | null) => ({ kill_switch: false, halted: false, policy_version: "fno-risk-v1", can_reset: false, modes: ["paper"], gate: gate == null ? {} : { enabled: gate, policy_version: "fno-risk-v1" } });
const RISK_POLICY = { policy_version: "fno-risk-v1", limits: { max_legs: 4, max_lots_per_leg: 10, max_open_structures: 10, max_capital_at_risk_rs: 200_000, require_defined_risk: true },
  usage: { open_structures: 2, capital_at_risk_rs: 24_875 } };

// ── MOCK — not real data: the combined policy (§7), stateful ───────────────────────────────────────────────────────────────
const F = (value: number, def: number, min: number, max: number, step: number, unit: string, store: string, overridden = false) =>
  ({ value, default: def, min, max, step, unit, store, overridden, loosen_needs_admin: true, label: "MOCK label" });
function policyFields(): Record<string, Row> {
  return {
    per_trade_risk_pct: F(0.5, 0.5, 0.1, 2, 0.05, "%", "risk_profile"), max_open_risk_pct: F(3, 3, 0.5, 10, 0.5, "%", "risk_profile"),
    daily_loss_pct: F(2, 2, 0.25, 5, 0.05, "%", "risk_profile"), weekly_loss_pct: F(4, 4, 0.5, 10, 0.5, "%", "risk_profile"),
    restrict_at_pct: F(4, 4, 1, 15, 0.5, "%", "spt"), halt_at_pct: F(6, 10, 2, 20, 0.5, "%", "risk_profile", true),
    max_position_pct: F(10, 10, 1, 25, 1, "%", "risk_profile"), max_sector_pct: F(25, 25, 5, 50, 1, "%", "risk_profile"),
    margin_util_pct: F(50, 50, 10, 90, 5, "%", "spt"), fno_max_loss_pct: F(2, 2, 0.5, 5, 0.25, "%", "spt"),
    bucket_positional_pct: F(45, 50, 0, 100, 1, "%", "spt", true), bucket_intraday_pct: F(25, 20, 0, 100, 1, "%", "spt", true),
    bucket_fno_pct: F(20, 20, 0, 100, 1, "%", "spt"), max_positions: F(10, 10, 1, 30, 1, "", "spt"),
  };
}
class PolicyState {
  version: number;
  fields: Record<string, Row>;
  constructor(version = 7) { this.version = version; this.fields = policyFields(); }
  body(id = ACC): Row {
    return { account_id: id, version: this.version, saved_at: "2026-11-05T04:00:00+00:00", saved_by: "MOCK user", fields: clone(this.fields),
      derived: { reserve_pct: 10, risk_budget_left_pct: 1.18, risk_budget_left_rs: 11_975, per_trade_risk_rs: 5_062.5 } };
  }
  apply(values: Record<string, number | null>) {
    for (const [k, v] of Object.entries(values)) {
      const f = this.fields[k];
      if (v == null) { f.value = f.default; f.overridden = false; } else { f.value = v; f.overridden = true; }
    }
    this.version += 1;
  }
}

// ── MOCK — not real data: GET /api/desk/pnl (routes/desk_pnl.py), its stream, /timeseries, /exits, /paper-trades ────────────
const ex = (id: string, side: string, quantity: number, price: number) => ({ execution_id: id, side, quantity, price, at: "2026-11-04T04:00:00+00:00", kind: "fill" });
const prow = (o: Row): Row => ({
  trade_id: null, leg_index: null, strategy_id: null, strategy_name: null, mode: "PAPER", account: "Paper account", account_id: "paper", lots: null, lot_size: null,
  realized_pnl: 0, opened_at: "2026-11-03T04:00:00+00:00", expiry: null, risk_used_pct: 0, price_day: "2026-11-05", broker_pnl: null, broker_read_at: null,
  product: null, editable_levels: false, pending_levels: null, executions_note: null, contract_problem: null, prev_close: null, day_pnl: null, return_pct: null,
  price_status: "LIVE", price_source: "Kite live", price_at: "2026-11-05T10:30:01+05:30", price_age_seconds: 1, status: "ACTIVE", source: "desk", executions: [], ...o,
});
const ICICI = prow({ position_id: "pt-icici", trade_id: "pt-icici", instrument: "ICICIBANK", symbol: "ICICIBANK", underlying: "ICICIBANK", segment: "EQUITY", side: "LONG",
  net_quantity: 35, avg_price: 1413.21, ltp: 1431.5, invested_value: 49_462.35, unrealized_pnl: 640.15, gross_pnl: 640.15, charges_estimated: 40.2, net_pnl: 599.95,
  stop_loss: 1374.9, target: 1489.83, distance_to_stop_pct: 3.95, exposure_rs: 50_102.5, editable_levels: true, executions: [ex("e1", "BUY", 35, 1413.21)] });
const SCAN = prow({ position_id: "spt-pos-1", trade_id: "spt-pos-1", instrument: "TATAPOWER", symbol: "TATAPOWER", underlying: "TATAPOWER", segment: "EQUITY", side: "LONG",
  net_quantity: 40, avg_price: 401.5, ltp: 405.2, invested_value: 16_060, unrealized_pnl: 148, gross_pnl: 148, charges_estimated: 22.4, net_pnl: 125.6,
  stop_loss: 389, target: 425, exposure_rs: 16_208, source: "scanner", setup_type: "breakout", opportunity_id: "opp-1", executions: [ex("f1", "BUY", 40, 401.5)] });
const sleg = (sid: string, i: number, name: string, inst: string, side: string, q: number, net: number) => prow({ position_id: `${sid}:${i}`, trade_id: sid, leg_index: i,
  strategy_id: sid, strategy_name: name, instrument: inst, symbol: inst.replace(/ /g, ""), underlying: inst.split(" ")[0], segment: "OPTIONS", side, net_quantity: q, lots: 1,
  lot_size: Math.abs(q), avg_price: 100, ltp: 110, unrealized_pnl: net, gross_pnl: net, charges_estimated: 10, net_pnl: net - 10, stop_loss: null, target: null, expiry: "2026-11-25" });
const LEGS = [sleg("st-1", 0, "Bull call spread", "NIFTY 25 Nov 25000 CE", "LONG", 75, 3150), sleg("st-1", 1, "Bull call spread", "NIFTY 25 Nov 25200 CE", "SHORT", -75, -1875),
  sleg("st-2", 0, "Iron condor", "BANKNIFTY 25 Nov 52500 CE", "SHORT", -30, 1500), sleg("st-2", 2, "Iron condor", "BANKNIFTY 25 Nov 51500 PE", "SHORT", -30, 600)];
const live = (o: Row): Row => prow({ mode: "LIVE", account: "Zerodha", account_id: "zr-1", source: "broker", realized_pnl: null, stop_loss: null, target: null, risk_used_pct: null, ...o });
const INFY = live({ position_id: "zr-1:INFY", instrument: "INFY", symbol: "INFY", underlying: "INFY", segment: "EQUITY", side: "LONG", net_quantity: 300, avg_price: 1590, ltp: 1618,
  invested_value: 477_000, unrealized_pnl: 8_400, gross_pnl: 8_400, charges_estimated: 180, net_pnl: 8_220, exposure_rs: 485_400, broker_pnl: 9_900, product: "delivery" });
const strat = (id: string, name: string, net: number) => ({ strategy_id: id, name, summary: `${name} · MOCK`, underlying: id === "st-1" ? "NIFTY" : "BANKNIFTY", direction: null, status: "OPEN",
  legs: [], underlying_ltp: null, stop_underlying: null, target_underlying: null, entry_net_premium: null, current_value: null, unrealized_pnl: net, charges_estimated: 20, net_pnl: net,
  capital_at_risk: id === "st-1" ? 6_375 : 18_500, complete: true, opened_at: null, risk_note: null });
const CLOSED = [
  { trade_id: "pt-axis", instrument: "AXISBANK", segment: "EQUITY", closed_at: "2026-11-03T10:00:00+00:00", exit_session: "2026-11-03", exit_reason: "stop", realized_pnl: -1_200, charges: 60.1, net_pnl: -1_260.1 },
  { trade_id: "spt-old", instrument: "BEL", segment: "EQUITY", closed_at: "2026-11-04T10:00:00+00:00", exit_session: "2026-11-04", exit_reason: "target", realized_pnl: 900, charges: 30, net_pnl: 870 },
];
function snapshot(q: URLSearchParams, seq = 1762319520000, patch?: (s: Row) => void): Row {
  const mode = q.get("mode") ?? "ALL";
  const period = q.get("period") ?? "TODAY";
  const paper = mode !== "LIVE";
  const rows = paper ? [ICICI, SCAN, ...LEGS] : [INFY];
  const weekly = period !== "TODAY";
  const s: Row = {
    mode, currency: "INR", as_of: "2026-11-05T10:30:01+05:30", sequence: seq,
    filters: { segment: "ALL", period, from: null, to: null, mode, account: "ALL" },
    market: { session: "open", feed: "live", feed_age_seconds: 1, stale_after_seconds: 75, day: "2026-11-05", price_rule: "MOCK price rule.", notes: [] },
    accounts: [{ account_id: "paper", name: "Paper account", mode: "PAPER", broker: null, state: "OK", capital: 10_000_000 },
      { account_id: "zr-1", name: "Zerodha", mode: "LIVE", broker: "zerodha", state: "OK", capital: null }],
    modes: { PAPER: { net_pnl: 3_900.55, available: true }, LIVE: { net_pnl: 8_220, available: true } },
    summary: {
      realized_pnl: paper ? (weekly ? -300 : 0) : null, unrealized_pnl: paper ? 4_163.15 : 8_400, gross_pnl: paper ? 4_163.15 : 8_400, charges_booked: paper ? (weekly ? 90.1 : 0) : 0,
      charges_estimated: paper ? 262.6 : 180, net_pnl: paper ? 3_900.55 : 8_220, day_pnl: null, allocated_capital: paper ? 10_000_000 : null, return_pct: paper ? 0.039 : null,
      open_positions: paper ? 4 : 1, open_legs: rows.length, winning_positions: 3, losing_positions: 1, closed_trades: paper ? (weekly ? 2 : 0) : 0, pending_entries: paper ? 1 : 0,
      unpriced_positions: 0, stale_positions: 0, complete: true, exposure_rs: null, capital_basis: paper ? "MOCK: paper starting capital" : "MOCK: broker capital is not read",
    },
    by_segment: [], positions: clone(rows),
    strategies: paper ? [strat("st-1", "Bull call spread", 1_175), strat("st-2", "Iron condor", 2_000)] : [],
    pending_entries: paper ? [{ trade_id: "pt-pend", symbol: "HDFCBANK", entry_rule: "break_above", level: 1655, ltp: 1641.2 }] : [],
    closed: paper && weekly ? clone(CLOSED) : [], closed_total: paper && weekly ? 2 : 0, closed_partial: false, marks_error: null,
    risk: { capital: { starting: 10_000_000, cash: 10_000_000, blocked: 0, available: 10_000_000, utilisation_pct: 1, basis: "MOCK" }, open_risk_rs: 21_000, open_risk_limit_rs: 300_000,
      strategies_capital_at_risk_rs: 24_875, near_stop_pct: 1, daily_loss_limit_rs: 200_000, daily_loss_used_pct: 12, alerts: [], margin: { used_pct: 1, basis: "MOCK" }, exposure_rs: null },
    analytics: null, reconciliation: { checked: weekly ? 2 : 0, mismatches: [] }, notes: { charges: "MOCK: charges are the desk cost card's." },
  };
  patch?.(s);
  return s;
}
const TIMESERIES = {
  date: "2026-11-05", interval: "5m", baseline_gross: 0, positions_used: 4, missing: [], basis: "MOCK: Kite 5-minute candles.", partial: false,
  points: ["09:15", "09:30", "09:45", "10:00", "10:30"].map((t, i) => ({ t: `2026-11-05T${t}:00+05:30`, unrealized_pnl: null, realized_pnl: 0, gross_pnl: null, net_pnl: [-400, 600, 1800, 2900, 3900.55][i], change_since_baseline: null })),
};
const EXITS = () => ({
  as_of: "2026-11-05T10:30:00+05:30", session: "open", rule: { id: "MOCK", text: "MOCK rule." }, watcher: { enabled: true, live_round_at: "2026-11-05T10:30:00+05:30", eod_day: "2026-11-04", feed_why: null },
  positions: [{ key: "zr-1|INFY|long", account_id: "zr-1", account: "Zerodha", underlying: "INFY", label: "INFY shares", kind: "shares", side: "long", legs: [], price: 1618, price_source: "kite_live",
    stop: 1625, method: "atr_trail", stop_day: "2026-11-04", stored: true, distance_pct: -0.43, status: "HIT", loss_at_stop: -10_500, history: [] }],
  not_watched: [], alerts: [{ id: "a1", at: "2026-11-05T10:29:00+05:30", day: "2026-11-05", kind: "STOP_HIT", severity: "CRITICAL", key: "zr-1|INFY|long", underlying: "INFY", account: "Zerodha",
    text: "MOCK: INFY is under its stop. Nothing has been sold: the broker is read-only here.", price: 1618, level: 1625, source: "kite_live", seen: false }],
  unseen: 1, accounts: [{ account_id: "zr-1", name: "Zerodha", state: "OK" }],
});
const PAPER_BOOK = { as_of: "2026-11-05", checked_through: "2026-11-04", status: "all", summary: { open: 0, closed: 1 },
  trades: [{ id: "pt-axis", symbol: "AXISBANK", status: "closed", quantity: 30, entry_price: 1100, stop_price: 1060, target_price: 1180, exit_price: 1060, exit_reason: "stop",
    opened_at: "2026-10-28T04:00:00+00:00", closed_at: "2026-11-03T10:00:00+00:00", transitions: [], flags: [] }] };

// ── setup ──────────────────────────────────────────────────────────────────────────────────────────────────────────────────
interface Seen {
  puts: Array<{ path: string; body: Row }>; policyGets: string[]; pnlQueries: URLSearchParams[]; closes: string[]; sptExits: string[]; patches: Array<{ id: string; body: Row }>;
  paperTradeGets: number;
}
interface Opts {
  phone?: boolean; admin?: boolean; gate?: boolean | null; policy?: PolicyState; adminPolicy?: PolicyState;
  put?: (n: number, body: Row) => { status: number; body: unknown } | null;
  account?: { status: number; body: unknown }; exposures?: Row; ranked?: Row; corr?: { status: number; body: unknown }; fno?: { status: number; body: unknown };
  stress?: Row; pnl?: (q: URLSearchParams) => { status?: number; body: unknown }; stream?: boolean; exits?: { status: number; body: unknown };
}

async function setup(page: Page, o: Opts = {}): Promise<Seen> {
  const seen: Seen = { puts: [], policyGets: [], pnlQueries: [], closes: [], sptExits: [], patches: [], paperTradeGets: 0 };
  const pol = o.policy ?? new PolicyState();
  const adminPol = o.adminPolicy ?? new PolicyState(3);
  if (o.phone) await page.setViewportSize({ width: 390, height: 844 });
  await page.route("**/api/**", (r) => json(r, { detail: "MOCK: not mocked in this spec" }, 404));
  await mockApi(page, "populated");
  await mockSingleRoute(page, "**/api/markets/home", "markets-home.json");
  await page.route("**/api/auth/me", (r) => json(r, { ...ME, is_admin: o.admin === true }));
  await page.route("**/api/chat/sessions", (r) => json(r, []));
  await page.route("**/api/move-odds/**", (r) => json(r, { detail: "feature_not_enabled" }, 403));
  await page.route("**/api/live/**", (r) => json(r, { available: false, reason: "MOCK: feed off", quotes: {}, mode: "expired", session: "closed", stale: true }));
  await page.route("**/api/desk/alerts*", (r) => json(r, { as_of: "2026-11-05", alerts: [] }));
  await page.route("**/api/risk/status", (r) => json(r, riskStatus(o.gate === undefined ? true : o.gate)));
  await page.route("**/api/risk/policy", (r) => json(r, RISK_POLICY));
  await page.route(/\/api\/v1\/paper\/accounts(\?|$)/, (r) => json(r, ACCOUNTS));
  await page.route(/\/api\/v1\/paper\/overview(\?|$)/, (r) => json(r, OVERVIEW));
  await page.route(/\/api\/v1\/proposals(\?|$)/, (r) => json(r, { items: [], count: 0 }));
  await page.route(/\/api\/v1\/risk\/account\/[^/?]+(\?|$)/, (r) => (o.account ? json(r, o.account.body, o.account.status) : json(r, riskAccount())));
  await page.route(/\/api\/v1\/risk\/exposures\/[^/?]+(\?|$)/, (r) => json(r, o.exposures ?? EXPOSURES));
  await page.route(/\/api\/v1\/risk\/stress-test\/[^/?]+(\?|$)/, (r) => json(r, o.stress ?? STRESS));
  await page.route(/\/api\/v1\/allocation\/recommendations\/[^/?]+(\?|$)/, (r) => json(r, o.ranked ?? RANKED));
  await page.route(/\/api\/v1\/risk\/correlation\/[^/?]+(\?|$)/, (r) => (o.corr ? json(r, o.corr.body, o.corr.status) : json(r, CORR)));
  await page.route(/\/api\/v1\/paper\/fno-structures(\?|$)/, (r) => (o.fno ? json(r, o.fno.body, o.fno.status) : json(r, FNO())));
  const policyRoute = (state: PolicyState, id: string) => async (r: Route) => {
    const req = r.request();
    const p = new URL(req.url()).pathname;
    if (req.method() === "GET") { seen.policyGets.push(p); return json(r, state.body(id)); }
    const body = req.postDataJSON() as Row;
    seen.puts.push({ path: p, body });
    const forced = o.put?.(seen.puts.length, body) ?? null;
    if (forced) return json(r, forced.body, forced.status);
    if (body.expected_version !== state.version) return json(r, { detail: { code: "version_conflict", field: null, message: "MOCK: stale version" } }, 409);
    state.apply(body.values as Record<string, number | null>);
    return json(r, { policy: state.body(id) });
  };
  await page.route(/\/api\/v1\/paper\/accounts\/[^/]+\/policy(\?|$)/, policyRoute(pol, ACC));
  await page.route(/\/api\/admin\/spt\/[^/]+\/policy(\?|$)/, policyRoute(adminPol, "u_other"));
  // the P&L reads
  await page.route(/\/api\/desk\/pnl(\?|$)/, (r) => {
    const q = new URL(r.request().url()).searchParams;
    seen.pnlQueries.push(q);
    const a = o.pnl ? o.pnl(q) : { body: snapshot(q) };
    return json(r, a.body, a.status ?? 200);
  });
  await page.route(/\/api\/desk\/pnl\/stream(\?|$)/, (r) => json(r, { detail: "MOCK: stream unavailable" }, 503));
  await page.route(/\/api\/desk\/pnl\/timeseries(\?|$)/, (r) => {
    const q = new URL(r.request().url()).searchParams;
    if (q.get("trade")) return json(r, { trade: q.get("trade"), points: [], missing: [], basis: "MOCK", notes: [] });
    return json(r, TIMESERIES);
  });
  await page.route(/\/api\/desk\/pnl\/journal\/[^/?]+/, (r) => json(r, { detail: "journal_not_available" }, 404));
  await page.route(/\/api\/desk\/pnl\/exits(\?|$)/, (r) => (o.exits ? json(r, o.exits.body, o.exits.status) : json(r, EXITS())));
  await page.route("**/api/desk/live-chart/*", (r) => json(r, { detail: "MOCK: no chart in this spec" }, 404));
  await page.route("**/api/desk/paper-trades*", (r) => { seen.paperTradeGets += 1; return json(r, PAPER_BOOK); });
  await page.route(/\/api\/desk\/paper-trades\/[^/]+\/(levels|close)$/, (r) => {
    const [, id, what] = new URL(r.request().url()).pathname.match(/paper-trades\/([^/]+)\/(levels|close)$/) as RegExpMatchArray;
    if (what === "close") { seen.closes.push(decodeURIComponent(id)); return json(r, { trade: { id, status: "closed" }, replayed: false }); }
    seen.patches.push({ id: decodeURIComponent(id), body: r.request().postDataJSON() as Row });
    return json(r, { trade: { id, pending_levels: { stop_loss: 1380, target: 1489.83, from_session: "2026-11-06", version: 1 }, level_rule: "MOCK" }, replayed: false });
  });
  await page.route(/\/api\/v1\/paper\/positions\/[^/]+\/exit$/, (r) => {
    seen.sptExits.push(decodeURIComponent(new URL(r.request().url()).pathname.split("/").slice(-2)[0]));
    return json(r, { order: { _id: "ord-x", order_id: "ord-x", state: "PENDING", purpose: "EXIT" }, duplicate: false });
  });
  if (o.stream) {
    // MOCK — not real data: a stand-in EventSource that keeps the stream open and sends a snapshot every 300 ms, so the
    // "Streaming · N ticks" state can be seen (a fulfilled route closes the stream at once).
    await page.addInitScript((bodies: Record<string, Row>) => {
      class FakeES {
        readyState = 1; private l: Record<string, Array<(e: { data: string }) => void>> = {}; private t: ReturnType<typeof setInterval>; onerror: (() => void) | null = null;
        constructor(url: string) {
          const mode = new URL(url, location.href).searchParams.get("mode") ?? "PAPER";
          let seq = 1762319520000;
          this.t = setInterval(() => { seq += 1000; const b = { ...bodies[mode], sequence: seq }; (this.l.snapshot ?? []).forEach((f) => f({ data: JSON.stringify(b) })); }, 300);
        }
        addEventListener(n: string, f: (e: { data: string }) => void) { (this.l[n] ??= []).push(f); }
        close() { clearInterval(this.t); this.readyState = 2; }
      }
      (window as unknown as { EventSource: unknown }).EventSource = FakeES;
    }, { PAPER: snapshot(new URLSearchParams("mode=PAPER")), LIVE: snapshot(new URLSearchParams("mode=LIVE")) });
  }
  return seen;
}

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

/** Only when PV2_SHOTS names a folder: grow the viewport to the content and shoot the view. */
async function shot(page: Page, testId: string, name: string) {
  if (!SHOTS) return;
  fs.mkdirSync(SHOTS, { recursive: true });
  const vp = page.viewportSize() as { width: number; height: number };
  const h = await page.evaluate(() => { const sc = document.querySelector('[data-testid="copilot-scroll"]') as HTMLElement | null; return sc ? sc.scrollHeight + (window.innerHeight - sc.clientHeight) : document.documentElement.scrollHeight; });
  await page.setViewportSize({ width: vp.width, height: Math.min(h + 200, 12_000) });
  await page.waitForTimeout(400);
  await page.getByTestId(testId).screenshot({ path: path.join(SHOTS, name) });
  await page.setViewportSize(vp);
}

const field = (page: Page, k: string) => page.getByTestId(`pv2-policy-input-${k}`);
async function setField(page: Page, k: string, v: string) {
  const i = field(page, k);
  await i.fill(v);
  await i.blur();
}
const limitRow = (page: Page, k: string) => page.locator(`[data-testid="pv2-limit-row"][data-key="${k}"]`);

test.describe("MOCK — not real data: Paper Trading v2 › Capital allocation, Portfolio risk, Real-time P&L", () => {
  // ── 03 Capital allocation ────────────────────────────────────────────────
  test("PV2-B-UI-01 Capital allocation: synthesis, KPIs, policy card, bucket bars, sectors, F&O margin vs max loss, ranked changes", async ({ page }) => {
    await setup(page);
    await page.goto(at("allocation"));
    await expect(page.getByTestId("pv2-allocation")).toBeVisible(SLOW);
    await expect(page.getByTestId("pv2-al-head-eyebrow")).toHaveText("Capital allocation");
    // No per-bucket risk from the account route: the template stops after the first sentence and says why the bars are empty.
    await expect(page.getByTestId("pv2-al-head-synthesis")).toHaveText("₹3,00,000 is deployed.", SLOW);
    await expect(page.getByTestId("pv2-al-head-prose")).toHaveText("Capital and risk are allocated separately. F&O capital is measured by margin and F&O risk by strategy max loss, so a small margin can still carry large risk.");
    await expect(page.getByTestId("pv2-al-kpi-equity-value")).toHaveText("₹10,12,500");
    await expect(page.getByTestId("pv2-al-kpi-equity-sub")).toHaveText("cash ₹7,00,000");
    await expect(page.getByTestId("pv2-al-kpi-deployed-sub")).toHaveText("29.6% of equity");
    await expect(page.getByTestId("pv2-al-kpi-reserved-sub")).toHaveText("1 order");
    await expect(page.getByTestId("pv2-al-kpi-risk-left-value")).toHaveText("₹11,975");
    await expect(page.getByTestId("pv2-al-kpi-risk-left-sub")).toHaveText("of 3.0% · ₹30,375");
    // The policy card: saved pill, the sub-line from the figures, dimmed Discard / Save, the derived reserve; no admin picker.
    const card = page.locator('[data-testid="pv2-policy-card"][data-panel="allocation"]');
    await expect(card.getByTestId("pv2-policy-version")).toHaveText("Policy v7 · saved");
    await expect(card.getByTestId("pv2-policy-version")).toHaveAttribute("data-state", "saved");
    await expect(card.getByTestId("pv2-policy-sub")).toHaveText("Per-trade risk of ₹5,063 per trade on ₹10.13 L equity. Bucket targets always total 100%.");
    await expect(card.getByTestId("pv2-policy-discard")).toBeDisabled();
    await expect(card.getByTestId("pv2-policy-save")).toBeDisabled();
    await expect(card.getByTestId("pv2-policy-reserve-value")).toHaveText("10%");
    await expect(page.getByTestId("pv2-policy-admin")).toHaveCount(0);
    for (const k of ["bucket_positional_pct", "bucket_intraday_pct", "bucket_fno_pct", "per_trade_risk_pct", "max_positions"]) await expect(field(page, k)).toBeVisible();
    // Buckets: capital against the draft target; F&O capital = margin, risk = max loss.
    await expect(page.getByTestId("pv2-al-bucket-equity_positional-target")).toHaveText("TARGET 45.0%");
    await expect(page.getByTestId("pv2-al-bucket-equity_positional-cap")).toHaveAttribute("data-pct", "52.7");
    await expect(page.getByTestId("pv2-al-bucket-fno-cap")).toHaveAttribute("data-pct", "50.1");
    await expect(page.getByTestId("pv2-al-bucket-fno-risk")).toHaveAttribute("data-level", "danger");
    await expect(page.getByTestId("pv2-al-bucket-equity_positional-risk")).toHaveAttribute("data-level", "unknown");
    await expect(page.getByTestId("pv2-al-risk-missing")).toContainText("Equity positional, Equity intraday");
    // Sectors against the max-sector limit (Banks 20.74 of 25 → over 80 %: amber).
    await expect(page.locator('[data-testid="pv2-al-sector"][data-sector="Banks"]').getByTestId("pv2-al-sector-bar")).toHaveAttribute("data-level", "amber");
    await expect(page.getByTestId("pv2-al-fno-total")).toHaveText("Margin ₹1,01,375");
    await expect(page.locator('[data-testid="pv2-al-fno-row"][data-id="st-2"]').getByTestId("pv2-al-fno-maxloss")).toHaveText("₹18,500");
    await expect(page.locator('[data-testid="pv2-al-fno-row"][data-id="st-2"]').getByTestId("pv2-al-fno-bar")).toHaveAttribute("data-level", "amber");
    // Allocation changes: ranked by |₹|, numbered, mint / danger / plain; never "Recommended".
    await expect(page.getByTestId("pv2-al-changes")).toContainText("Allocation changes · ranked by ₹ impact");
    await expect(page.getByTestId("pv2-al-change")).toHaveCount(3);
    await expect(page.getByTestId("pv2-al-change-text")).toHaveText([
      "HDFCBANK is blocked: MOCK: ten positions are open.",
      "TCS is reduced from 40 shares to 25 shares to fit the risk budget: MOCK: equity positional bucket has ₹1,00,000 left.",
      "INFY fits in full at 30 shares.",
    ]);
    await expect(page.getByTestId("pv2-al-change-impact")).toHaveText(["₹82,000", "₹60,000", "₹48,000"]);
    await expect(page.getByTestId("pv2-al-change").first()).toHaveAttribute("data-tone", "danger");
    await expect(page.getByTestId("pv2-al-change").nth(1)).toHaveAttribute("data-tone", "mint");
    await expect(page.getByTestId("pv2-allocation")).not.toContainText(/Recommended/i);
    await shot(page, "pv2-allocation", "pv2-allocation-desktop.png");
  });

  test("PV2-B-UI-01b with bucket risk sent, the synthesis names the bucket whose risk share outruns its capital share", async ({ page }) => {
    // MOCK — not real data: `risk_rs` per bucket is NOT sent by today's route; this case proves the template once it is.
    const a = riskAccount();
    (a.utilisation as Row).buckets = { equity_positional: { used_rs: 240_000, cap_rs: 455_625, risk_rs: 9_000 }, equity_intraday: { used_rs: 0, cap_rs: 253_125, risk_rs: 0 }, fno: { used_rs: 0, cap_rs: 202_500 } };
    await setup(page, { account: { status: 200, body: a } });
    await page.goto(at("allocation"));
    await expect(page.getByTestId("pv2-al-head-synthesis")).toHaveText("₹3,00,000 is deployed. F&O strategies uses 30% of it but carries 73% of open risk.", SLOW);
    await expect(page.getByTestId("pv2-al-head-synthesis-hi")).toHaveText("F&O strategies uses 30% of it but carries 73% of open risk.");
    await expect(page.getByTestId("pv2-al-risk-missing")).toHaveCount(0);
  });

  // ── the shared policy draft (§3) ─────────────────────────────────────────
  test("PV2-B-UI-02/03/05 one draft across Allocation and Portfolio risk; Save policy writes one version of both panels' changes", async ({ page }) => {
    const seen = await setup(page);
    await page.goto(at("allocation"));
    await expect(field(page, "bucket_fno_pct")).toHaveValue("20", SLOW);
    await setField(page, "bucket_fno_pct", "15");
    const pill = page.getByTestId("pv2-policy-version");
    await expect(pill).toHaveText("Policy v8 · draft");
    await expect(pill).toHaveAttribute("data-state", "draft");
    await expect(page.getByTestId("pv2-policy-reserve-value")).toHaveText("15%");
    // Live preview: the F&O bucket's target bar moved before any save.
    await expect(page.getByTestId("pv2-al-bucket-fno-target")).toHaveText("TARGET 15.0%");
    // Open 04 by its chip (client-side, the draft lives on).
    await page.getByTestId("desk-sub-risk").click();
    await expect(page.getByTestId("pv2-risk")).toBeVisible(SLOW);
    await expect(page.getByTestId("pv2-policy-version")).toHaveText("Policy v8 · draft");
    await expect(page.getByTestId("pv2-policy-changes")).toContainText("F&O strategies % 20% → 15%");
    await expect(page.getByTestId("pv2-policy-changes")).toContainText("1 of them is on Capital allocation");
    await setField(page, "daily_loss_pct", "1.5");
    await page.getByTestId("desk-sub-allocation").click();
    await expect(page.getByTestId("pv2-allocation")).toBeVisible(SLOW);
    await expect(field(page, "bucket_fno_pct")).toHaveValue("15");
    await expect(page.getByTestId("pv2-policy-changes")).toContainText("2 unsaved changes");
    expect(seen.puts).toHaveLength(0);
    await page.getByTestId("pv2-policy-save").click();
    await expect(page.getByTestId("pv2-policy-saved")).toHaveText("Saved as policy v8. The risk engine applies it to new orders.");
    expect(seen.puts).toHaveLength(1);
    expect(seen.puts[0].path).toBe(`/api/v1/paper/accounts/${ACC}/policy`);
    expect(seen.puts[0].body).toEqual({ expected_version: 7, values: { bucket_fno_pct: 15, daily_loss_pct: 1.5 } });
    await expect(pill).toHaveText("Policy v8 · saved");
    await expect(pill).toHaveAttribute("data-state", "saved");
    await expect(page.getByTestId("pv2-policy-save")).toBeDisabled();
    await expect(page.getByTestId("pv2-policy-discard")).toBeDisabled();
  });

  test("PV2-B-UI-04 Discard returns to the saved version; Defaults sets this panel's fields to null (the default)", async ({ page }) => {
    const seen = await setup(page);
    await page.goto(at("allocation"));
    await expect(field(page, "bucket_positional_pct")).toHaveValue("45", SLOW);
    await setField(page, "bucket_positional_pct", "40");
    await setField(page, "max_positions", "8");
    await expect(page.getByTestId("pv2-policy-discard")).toBeEnabled();
    await page.getByTestId("pv2-policy-discard").click();
    await expect(field(page, "bucket_positional_pct")).toHaveValue("45");
    await expect(field(page, "max_positions")).toHaveValue("10");
    await expect(page.getByTestId("pv2-policy-version")).toHaveText("Policy v7 · saved");
    // Defaults: the overridden buckets go back to their defaults (50 / 20); Save sends null for them.
    await page.getByTestId("pv2-policy-defaults").click();
    await expect(field(page, "bucket_positional_pct")).toHaveValue("50");
    await expect(field(page, "bucket_intraday_pct")).toHaveValue("20");
    await expect(page.getByTestId("pv2-policy-reserve-value")).toHaveText("10%");
    await expect(page.getByTestId("pv2-policy-version")).toHaveText("Policy v8 · draft");
    await page.getByTestId("pv2-policy-save").click();
    await expect.poll(() => seen.puts.length).toBe(1);
    expect(seen.puts[0].body).toEqual({ expected_version: 7, values: { bucket_positional_pct: null, bucket_intraday_pct: null } });
  });

  test("PV2-B-UI-06 a bucket is capped so the three never exceed 100; the reserve is derived and amber under 5%", async ({ page }) => {
    await setup(page);
    await page.goto(at("allocation"));
    await expect(field(page, "bucket_positional_pct")).toHaveValue("45", SLOW);
    await field(page, "bucket_positional_pct").fill("70");
    await expect(page.getByTestId("pv2-policy-capped")).toHaveText("Capped at 55% so the three buckets never exceed 100%.");
    await field(page, "bucket_positional_pct").blur();
    await expect(field(page, "bucket_positional_pct")).toHaveValue("55");
    await expect(page.getByTestId("pv2-policy-reserve-value")).toHaveText("0%");
    await expect(page.getByTestId("pv2-policy-reserve")).toHaveAttribute("data-low", "true");
    await expect(page.getByTestId("pv2-policy-slider-bucket_intraday_pct")).toHaveAttribute("max", "25");
    await setField(page, "bucket_positional_pct", "52");
    await expect(page.getByTestId("pv2-policy-reserve-value")).toHaveText("3%");
    await expect(page.getByTestId("pv2-policy-reserve")).toHaveAttribute("data-low", "true");
    await setField(page, "bucket_positional_pct", "40");
    await expect(page.getByTestId("pv2-policy-reserve")).toHaveAttribute("data-low", "false");
    // A non-number is refused on screen.
    await field(page, "max_positions").fill("ten");
    await expect(page.getByTestId("pv2-policy-invalid-max_positions")).toHaveText("Max open positions: enter a number.");
    await expect(page.getByTestId("pv2-policy-save")).toBeDisabled();
  });

  test("PV2-B-UI-07 halt at or below restricted: the warning shows and Save is refused", async ({ page }) => {
    const seen = await setup(page);
    await page.goto(at("risk"));
    await expect(field(page, "halt_at_pct")).toHaveValue("6", SLOW);
    await setField(page, "halt_at_pct", "4");
    await expect(page.getByTestId("pv2-policy-halt-warning")).toHaveText("Halt threshold must sit above the restricted threshold.");
    await expect(page.getByTestId("pv2-policy-save")).toBeDisabled();
    await page.getByTestId("pv2-policy-save").click({ force: true });
    await page.waitForTimeout(300);
    expect(seen.puts).toHaveLength(0);
    await setField(page, "halt_at_pct", "8");
    await expect(page.getByTestId("pv2-policy-halt-warning")).toHaveCount(0);
    await expect(page.getByTestId("pv2-policy-save")).toBeEnabled();
  });

  test("PV2-B-UI-08/09/10 refusals: 403 names the loosened fields, 409 offers Reload, 422 names the field", async ({ page }) => {
    const pol = new PolicyState();
    const seen = await setup(page, {
      policy: pol,
      put: (n) => n === 1 ? { status: 403, body: { detail: { code: "admin_required", field: null, message: "MOCK", loosened: ["daily_loss_pct", "max_sector_pct"] } } }
        : n === 2 ? { status: 409, body: { detail: { code: "version_conflict", field: null, message: "MOCK: at version 9" } } }
          : n === 3 ? { status: 422, body: { detail: { code: "out_of_range", field: "weekly_loss_pct", message: "MOCK: must be between 0.5 and 10." } } } : null,
    });
    await page.goto(at("risk"));
    await expect(field(page, "daily_loss_pct")).toHaveValue("2", SLOW);
    await setField(page, "daily_loss_pct", "3");
    await setField(page, "max_sector_pct", "30");
    await page.getByTestId("pv2-policy-save").click();
    const box = page.getByTestId("pv2-policy-problem");
    await expect(box).toHaveAttribute("data-code", "admin_required");
    await expect(box).toContainText("Loosening needs an admin: Daily loss limit %, Max sector exposure %. Nothing was saved.");
    await expect(page.getByTestId("pv2-policy-version")).toHaveText("Policy v8 · draft");
    // 409: Reload re-reads the policy and the draft becomes it.
    await page.getByTestId("pv2-policy-save").click();
    await expect(box).toHaveAttribute("data-code", "version_conflict");
    pol.version = 9;
    pol.fields.daily_loss_pct.value = 1.75;
    pol.fields.daily_loss_pct.overridden = true;
    const gets = seen.policyGets.length;
    await page.getByTestId("pv2-policy-reload").click();
    await expect.poll(() => seen.policyGets.length).toBeGreaterThan(gets);
    await expect(page.getByTestId("pv2-policy-version")).toHaveText("Policy v9 · saved");
    await expect(field(page, "daily_loss_pct")).toHaveValue("1.75");
    await expect(field(page, "max_sector_pct")).toHaveValue("25");
    await expect(box).toHaveCount(0);
    // 422 names the field.
    await setField(page, "weekly_loss_pct", "3");
    await page.getByTestId("pv2-policy-save").click();
    await expect(box).toHaveAttribute("data-field", "weekly_loss_pct");
    await expect(box).toHaveText("Weekly loss limit %: MOCK: must be between 0.5 and 10.");
    expect(seen.puts.map((p) => p.body.expected_version)).toEqual([7, 7, 9]);
  });

  test("PV2-B-UI-11 an admin picks a user; their policy loads from the admin route; Save needs a reason and PUTs there", async ({ page }) => {
    const seen = await setup(page, { admin: true });
    await page.goto(at("allocation"));
    await expect(page.getByTestId("pv2-policy-admin")).toBeVisible(SLOW);
    await page.getByTestId("pv2-policy-admin-uid").fill("u_other");
    await page.getByTestId("pv2-policy-admin-load").click();
    await expect(page.getByTestId("pv2-policy-version")).toHaveText("Policy v3 · saved", SLOW);
    expect(seen.policyGets).toContain("/api/admin/spt/u_other/policy");
    await expect(page.getByTestId("pv2-policy-admin")).toContainText("Editing u_other's policy. A reason is required to save.");
    await setField(page, "max_positions", "12");
    await expect(page.getByTestId("pv2-policy-save")).toBeDisabled();
    await page.getByTestId("pv2-policy-reason").fill("MOCK reason");
    await page.getByTestId("pv2-policy-save").click();
    await expect.poll(() => seen.puts.length).toBe(1);
    expect(seen.puts[0]).toEqual({ path: "/api/admin/spt/u_other/policy", body: { expected_version: 3, values: { max_positions: 12 }, reason: "MOCK reason" } });
    await expect(page.getByTestId("pv2-policy-version")).toHaveText("Policy v4 · saved");
    // Back to the admin's own policy: its own draft and version.
    await page.getByTestId("pv2-policy-admin-self").click();
    await expect(page.getByTestId("pv2-policy-version")).toHaveText("Policy v7 · saved");
  });

  // ── 04 Portfolio risk ────────────────────────────────────────────────────
  test("PV2-B-UI-12 limit utilization moves with the draft: NEAR LIMIT, then BREACH, and the synthesis follows", async ({ page }) => {
    await setup(page);
    await page.goto(at("risk"));
    await expect(page.getByTestId("pv2-limit-row")).toHaveCount(9, SLOW);
    await expect(page.getByTestId("pv2-rk-head-eyebrow")).toHaveText("Portfolio risk");
    await expect(page.getByTestId("pv2-rk-head-synthesis")).toHaveText("Within every limit, with Iron condor's max loss the nearest to a breach.");
    await expect(page.getByTestId("pv2-policy-sub")).toHaveText("Risk budget left 1.18% (₹11,975). The risk engine enforces these as hard limits.");
    await expect(limitRow(page, "open_risk").getByTestId("pv2-limit-value")).toHaveText("₹18,400 / ₹30,375");
    await expect(limitRow(page, "single_stock")).toHaveAttribute("data-level", "amber");
    await expect(limitRow(page, "single_stock").getByTestId("pv2-limit-flag")).toHaveText("NEAR LIMIT");
    await expect(limitRow(page, "daily_loss")).toHaveAttribute("data-level", "mint");
    await expect(limitRow(page, "positions").getByTestId("pv2-limit-value")).toHaveText("4 / 10");
    await setField(page, "daily_loss_pct", "0.5");
    await expect(limitRow(page, "daily_loss")).toHaveAttribute("data-level", "amber");
    await expect(limitRow(page, "daily_loss").getByTestId("pv2-limit-flag")).toHaveText("NEAR LIMIT");
    await setField(page, "daily_loss_pct", "0.4");
    await expect(limitRow(page, "daily_loss")).toHaveAttribute("data-level", "danger");
    await expect(limitRow(page, "daily_loss").getByTestId("pv2-limit-flag")).toHaveText("BREACH");
    await expect(page.getByTestId("pv2-rk-head-synthesis")).toHaveText("1 limit breached: Daily loss.");
    // The open-risk limit too: 18,400 against 1.5 % of equity (15,187.50) is a breach.
    await setField(page, "max_open_risk_pct", "1.5");
    await expect(limitRow(page, "open_risk")).toHaveAttribute("data-level", "danger");
    await expect(page.getByTestId("pv2-rk-head-synthesis")).toHaveText("3 limits breached: Open planned risk, Stressed portfolio loss, Daily loss.");
  });

  test("PV2-B-UI-13/14 correlation colours (≥ 0.70 danger, diagonal, null '—') and every stress scenario with its assumption", async ({ page }) => {
    await setup(page);
    await page.goto(at("risk"));
    await expect(page.getByTestId("pv2-corr-cell")).toHaveCount(16, SLOW);
    await expect(page.getByTestId("pv2-rk-corr")).toContainText("Correlation · 60d returns");
    await expect(page.getByTestId("pv2-rk-corr")).toContainText("≥0.70 = concentrated");
    await expect(page.locator('[data-testid="pv2-corr-cell"][data-hot="true"]')).toHaveCount(4);
    await expect(page.locator('[data-testid="pv2-corr-cell"][data-pair="ICICIBANK|HDFCBANK"]')).toHaveText("0.82");
    await expect(page.locator('[data-testid="pv2-corr-cell"][data-pair="ICICIBANK|TCS"]')).toHaveAttribute("data-hot", "false");
    await expect(page.locator('[data-testid="pv2-corr-cell"][data-pair="ICICIBANK|INFY"]')).toHaveText("—");
    await expect(page.locator('[data-testid="pv2-corr-cell"][data-diag="true"]')).toHaveCount(4);
    await expect(page.getByTestId("pv2-corr-row")).toHaveText(["ICICIBANK", "HDFCBANK", "TCS", "INFY"]);
    await expect(page.getByTestId("pv2-rk-corr-notes")).toContainText("MOCK: INFY has 41 of 60 sessions");
    const rows = page.getByTestId("pv2-rk-stress-row");
    await expect(rows).toHaveCount(9);
    await expect(rows.locator("span").first()).toHaveText("Gap through every stop");
    for (const label of ["Sector shock −5%", "Market −3%", "Market −5%", "Nifty -2%", "Banks gap -3%", "Correlated stops hit", "Gap beyond stops +25%", "IV +10 pts (F&O)"]) {
      await expect(page.getByTestId("pv2-rk-stress")).toContainText(label);
    }
    await expect(page.locator('[data-testid="pv2-rk-stress-row"][data-key="gap_beyond_stops"]').getByTestId("pv2-rk-stress-loss")).toHaveText("₹19,863");
    await expect(page.locator('[data-testid="pv2-rk-stress-row"][data-key="correlated_stops"]')).toContainText("MOCK: pairs at ρ ≥ 0.70 stop together.");
    await expect(page.locator('[data-testid="pv2-rk-stress-row"][data-key="market_shock-0"]')).toContainText("Beta 1 assumed.");
  });

  test("PV2-B-UI-15 F&O net Greeks: the sum of max loss, the tiles, max loss by strategy vs the draft limit, scenario P&L", async ({ page }) => {
    await setup(page);
    await page.goto(at("risk"));
    const c = page.getByTestId("pv2-rk-fno");
    await expect(c).toContainText("F&O · 2 strategies · net Greeks", SLOW);
    await expect(page.getByTestId("pv2-rk-fno-sum")).toHaveText("Sum of max loss · ₹24,875");
    await expect(page.getByTestId("pv2-rk-greek-delta")).toContainText("17.20");
    await expect(page.getByTestId("pv2-rk-greek-delta")).toContainText("NIFTY 21.40 · BANKNIFTY -4.20");
    await expect(page.getByTestId("pv2-rk-greek-theta")).toContainText("+₹580 / day");
    await expect(page.getByTestId("pv2-rk-greek-vega")).toContainText("−₹830 / IV pt");
    await expect(page.getByTestId("pv2-rk-greek-margin")).toContainText("₹1,01,375");
    const st2 = page.locator('[data-testid="pv2-rk-fno-row"][data-id="st-2"]');
    await expect(st2.getByTestId("pv2-rk-fno-flag")).toHaveText("NEAR LIMIT");
    await expect(st2.getByTestId("pv2-rk-fno-unhedged")).toHaveText("Unhedged · hedge leg pending");
    await expect(page.locator('[data-testid="pv2-rk-fno-row"][data-id="st-1"]').getByTestId("pv2-rk-fno-flag")).toHaveCount(0);
    await expect(page.getByTestId("pv2-rk-fno-scenario-pnl")).toHaveText(["−₹700", "+₹400", "−₹890", "+₹580"]);
    await expect(c).toContainText("Scenarios are assumptions, not forecasts.");
    // The per-strategy limit is the draft's: 0.5 % of equity (5,062.50) puts both structures in breach.
    await setField(page, "fno_max_loss_pct", "0.5");
    await expect(st2.getByTestId("pv2-rk-fno-flag")).toHaveText("BREACH");
    await expect(page.locator('[data-testid="pv2-rk-fno-row"][data-id="st-1"]').getByTestId("pv2-rk-fno-flag")).toHaveText("BREACH");
  });

  test("PV2-B-UI-16 F&O structure caps: gate on (Remaining), gate off (amber, the note, Remaining '—'), collapsible, the footer", async ({ page }) => {
    await setup(page, { gate: true });
    await page.goto(at("risk"));
    const caps = page.getByTestId("pv2-rk-caps");
    await expect(page.getByTestId("pv2-rk-gate")).toHaveText("Gate on for your account", SLOW);
    await expect(page.getByTestId("pv2-rk-gate")).toHaveAttribute("data-tone", "mint");
    await expect(page.getByTestId("pv2-rk-gate-note")).toHaveText("The policy gate checks your paper writes against these limits before an order is created. The kill switch and the halt also apply.");
    await expect(page.getByTestId("pv2-rk-cap-capital-allowed")).toHaveValue("2,00,000");
    await expect(page.getByTestId("pv2-rk-cap-capital")).toContainText("₹");
    await expect(page.getByTestId("pv2-rk-cap-capital-used")).toHaveText("₹24,875");
    await expect(page.getByTestId("pv2-rk-cap-capital-left")).toHaveText("₹1,75,125");
    await expect(page.getByTestId("pv2-rk-cap-structures-left")).toHaveText("8");
    await expect(page.getByTestId("pv2-rk-cap-legs-left")).toHaveText("—");
    await expect(page.locator('[data-testid="pv2-rk-cap-defined-allowed"] [data-on="true"]')).toHaveText("Yes");
    await expect(page.getByTestId("pv2-rk-caps-footer")).toHaveText("Risk controls · Rules-based · FNO-RISK-V1");
    await expect(page.getByTestId("pv2-rk-caps-readonly")).toContainText("no route changes them in this release");
    await page.getByTestId("pv2-rk-caps-toggle").click();
    await expect(caps).toHaveAttribute("data-open", "false");
    await expect(page.getByTestId("pv2-rk-caps-table")).toHaveCount(0);
    await page.getByTestId("pv2-rk-caps-toggle").click();
    await expect(page.getByTestId("pv2-rk-caps-table")).toBeVisible();
    const p2 = await page.context().newPage();
    await setup(p2, { gate: false });
    await p2.goto(at("risk"));
    await expect(p2.getByTestId("pv2-rk-gate")).toHaveText("Gate off for your account", SLOW);
    await expect(p2.getByTestId("pv2-rk-gate")).toHaveAttribute("data-tone", "amber");
    await expect(p2.getByTestId("pv2-rk-gate-note")).toHaveText("The policy gate does not check your paper writes, so these limits are not applied to them. The kill switch and the halt still apply.");
    for (const k of ["legs", "lots", "structures", "capital", "defined"]) await expect(p2.getByTestId(`pv2-rk-cap-${k}-left`)).toHaveText("—");
    await shot(p2, "pv2-risk", "pv2-risk-desktop.png");
    await p2.close();
  });

  // ── 05 Real-time P&L ─────────────────────────────────────────────────────
  test("PV2-B-UI-17/18/19/20 Real-time P&L: header, KPIs, the curve, P&L by strategy, the open positions table and its marker", async ({ page }) => {
    const seen = await setup(page);
    await page.goto(at("pnl"));
    await expect(page.getByTestId("pv2-pnl")).toBeVisible(SLOW);
    await expect(page.getByTestId("pv2-pnl-eyebrow")).toHaveText("Real-time paper P&L");
    await expect(page.getByTestId("pv2-pnl-total")).toHaveText("+₹3,900.55", SLOW);
    await expect(page.getByTestId("pv2-pnl-return")).toHaveText("+0.04% of equity");
    await expect(page.getByTestId("pv2-pnl-stream")).toHaveText("Polling · every 3 s");
    await expect(page.getByTestId("pv2-pnl-stream")).toHaveAttribute("data-state", "polling");
    expect(seen.pnlQueries[0].get("mode")).toBe("PAPER");
    await expect(page.getByTestId("pv2-pnl-kpi-unrealized-value")).toHaveText("+₹4,163.15");
    await expect(page.getByTestId("pv2-pnl-kpi-unrealized-sub")).toHaveText("2 equity · 2 F&O strategies");
    await expect(page.getByTestId("pv2-pnl-kpi-realized-sub")).toHaveText("0 closed today · net of costs");
    await expect(page.getByTestId("pv2-pnl-kpi-risk-value")).toHaveText("₹2,79,000");
    await expect(page.getByTestId("pv2-pnl-kpi-risk-sub")).toHaveText("2.79% of equity");
    await expect(page.getByTestId("pv2-pnl-kpi-dayloss-value")).toHaveText("12%");
    await expect(page.getByTestId("pv2-pnl-kpi-dayloss-sub")).toHaveText("of 2.0% limit · ₹2,00,000");
    // The curve: SVG with the dashed zero line and the 09:15 · NOW · 15:30 axis.
    await expect(page.getByTestId("pv2-pnl-curve")).toContainText("Intraday equity · net of costs");
    await expect(page.getByTestId("pv2-pnl-curve-plot")).toHaveAttribute("data-points", "5");
    await expect(page.getByTestId("pv2-pnl-curve-zero")).toHaveAttribute("stroke-dasharray", "4 5");
    await expect(page.getByTestId("pv2-pnl-curve-axis")).toContainText("09:15");
    await expect(page.getByTestId("pv2-pnl-curve-axis")).toContainText("10:30 NOW");
    await expect(page.getByTestId("pv2-pnl-curve-axis")).toContainText("15:30");
    // P&L by strategy: setup type, the desk's own, F&O spreads as one row.
    const groups = page.getByTestId("pv2-pnl-strategy-row");
    await expect(groups).toHaveCount(3);
    await expect(page.locator('[data-testid="pv2-pnl-strategy-row"][data-key="fno"]')).toContainText("F&O spreads2 positions+₹3,175.00");
    await expect(page.locator('[data-testid="pv2-pnl-strategy-row"][data-key="Breakout"]')).toContainText("+₹125.60");
    await expect(page.locator('[data-testid="pv2-pnl-strategy-row"][data-key="Desk share trades"]')).toContainText("+₹599.95");
    // The table: the design's columns; F&O legs are not rows; the marker and R.
    await expect(page.getByTestId("pv2-pnl-positions-title")).toHaveText("Open positions · 2");
    await expect(page.getByTestId("pnl-table").getByRole("columnheader")).toHaveText(["Instrument", "Avg entry", "LTP", "Qty", "Stop → Target", "Position in plan", "R", "Unrealized"]);
    await expect(page.getByTestId("pnl-row")).toHaveCount(2);
    const icici = page.locator('[data-testid="pnl-row"][data-id="pt-icici"]');
    await expect(icici.getByTestId("pv2-pnl-row-setup")).toHaveText("Desk · LONG");
    await expect(icici.getByTestId("pnl-row-levels")).toHaveText("1,374.90 → 1,489.83");
    await expect(icici.getByTestId("pv2-pnl-plan")).toHaveAttribute("data-pos", "0.492");
    await expect(icici.getByTestId("pv2-pnl-row-r")).toHaveText("+0.48R");
    await expect(icici.getByTestId("pv2-pnl-row-unrealized")).toHaveText("+₹640.15");
    const scan = page.locator('[data-testid="pnl-row"][data-id="spt-pos-1"]');
    await expect(scan.getByTestId("pv2-pnl-row-setup")).toHaveText("Breakout · LONG");
    await expect(scan.getByTestId("pv2-pnl-plan")).toHaveAttribute("data-pos", "0.450");
    await expect(page.getByTestId("pv2-pnl-positions-foot")).toHaveText("P&L uses the prices shown (each badge names its source) with modeled costs. A stop trigger is not a guaranteed fill at the stop.");
    await expect(page.getByTestId("pnl-pending")).toHaveText(/HDFCBANK/);
    await shot(page, "pv2-pnl", "pv2-pnl-desktop.png");
  });

  test("PV2-B-UI-17b on the stream the pill reads '● Streaming · N ticks' and counts up", async ({ page }) => {
    await setup(page, { stream: true });
    await page.goto(at("pnl"));
    const pill = page.getByTestId("pv2-pnl-stream");
    await expect(pill).toHaveAttribute("data-state", "live", SLOW);
    await expect(pill).toHaveAttribute("data-transport", "sse");
    await expect(pill).toHaveText(/^Streaming · \d+ ticks?$/);
    const n = async () => Number(((await pill.textContent()) ?? "").match(/(\d+) tick/)?.[1] ?? 0);
    const first = await n();
    await expect.poll(n, { timeout: 5_000 }).toBeGreaterThan(first);
    await expect(page.getByTestId("pv2-pnl-total")).toHaveText("+₹3,900.55");
  });

  test("PV2-B-UI-21 F&O cards: filled · hedged vs partially filled · unhedged, a PENDING leg; Details closes the whole structure", async ({ page }) => {
    const seen = await setup(page);
    await page.goto(at("pnl"));
    await expect(page.getByTestId("pv2-fno-card")).toHaveCount(2, SLOW);
    await expect(page.getByTestId("pv2-pnl-fno-title")).toHaveText("F&O strategy positions · 2");
    await expect(page.getByTestId("pv2-pnl-fno")).toContainText("Risk is measured by strategy max loss, not margin.");
    const c1 = page.locator('[data-testid="pv2-fno-card"][data-id="st-1"]');
    const c2 = page.locator('[data-testid="pv2-fno-card"][data-id="st-2"]');
    await expect(c1.getByTestId("pv2-fno-status")).toHaveText("Filled · hedged");
    await expect(c1.getByTestId("pv2-fno-status")).toHaveAttribute("data-tone", "mint");
    await expect(c1.getByTestId("pv2-fno-meta")).toHaveText("NIFTY · EXP 2026-11-25 · 1 lot");
    await expect(c1.getByTestId("pv2-fno-pnl")).toHaveText("+₹1,275");
    await expect(c1.getByTestId("pv2-fno-maxloss")).toContainText("₹6,375");
    await expect(c1.getByTestId("pv2-fno-leg-side")).toHaveText(["BUY", "SELL"]);
    await expect(c1.getByTestId("pv2-fno-partial")).toHaveCount(0);
    await expect(c2.getByTestId("pv2-fno-status")).toHaveText("Partially filled · unhedged");
    await expect(c2.getByTestId("pv2-fno-status")).toHaveAttribute("data-tone", "amber");
    await expect(c2.locator('[data-testid="pv2-fno-leg"][data-pending="true"]').getByTestId("pv2-fno-leg-pnl")).toHaveText("PENDING");
    await expect(c2.locator('[data-testid="pv2-fno-leg"][data-pending="true"]').getByTestId("pv2-fno-leg-filled")).toHaveText("0/30");
    await expect(c2.getByTestId("pv2-fno-partial")).toContainText("3 of 4 legs are filled.");
    await expect(c2.getByTestId("pv2-fno-partial")).toContainText("MOCK: the 53500 CE is not filled yet.");
    // Details: the existing detail of the structure; Simulate exit closes all its legs through the desk close.
    await c1.getByTestId("pv2-fno-details").click();
    await c1.getByTestId("pnl-exit").click();
    await expect(c1.getByTestId("pnl-exit-confirm")).toContainText("This closes the whole structure, all its legs.");
    await c1.getByTestId("pnl-exit-yes").click();
    await expect(c1.getByTestId("pnl-exit-done")).toBeVisible();
    expect(seen.closes).toEqual(["st-1"]);
  });

  test("PV2-B-UI-23 row actions survive: Modify risk and Simulate exit on a desk row; a scanner row exits through its own route", async ({ page }) => {
    const seen = await setup(page);
    await page.goto(at("pnl"));
    await page.locator('[data-testid="pnl-row"][data-id="pt-icici"]').click(SLOW);
    const d = page.locator('[data-testid="pnl-row-detail"][data-id="pt-icici"]');
    await expect(d.getByTestId("pnl-modify")).toBeEnabled();
    await d.getByTestId("pnl-modify").click();
    await d.getByTestId("pnl-levels-stop").fill("1380");
    await d.getByTestId("pnl-levels-save").click();
    await expect(d.getByTestId("pnl-levels-done")).toContainText("Saved.");
    expect(seen.patches).toEqual([{ id: "pt-icici", body: { stop_price: 1380 } }]);
    await d.getByTestId("pnl-exit").click();
    await expect(d.getByTestId("pnl-exit-confirm")).toContainText("at the last end-of-day close");
    await d.getByTestId("pnl-exit-yes").click();
    await expect(d.getByTestId("pnl-exit-done")).toBeVisible();
    expect(seen.closes).toEqual(["pt-icici"]);
    await page.locator('[data-testid="pnl-row"][data-id="spt-pos-1"]').click();
    const s = page.locator('[data-testid="pnl-row-detail"][data-id="spt-pos-1"]');
    await expect(s.getByTestId("pnl-modify")).toBeDisabled();
    await s.getByTestId("pnl-exit").click();
    await expect(s.getByTestId("pnl-exit-confirm")).toHaveAttribute("data-source", "scanner");
    await s.getByTestId("pnl-exit-yes").click();
    await expect(s.getByTestId("pnl-exit-done")).toContainText("Exit order placed in the paper book.");
    expect(seen.sptExits).toEqual(["spt-pos-1"]);
    expect(seen.closes).toEqual(["pt-icici"]);
  });

  test("PV2-B-UI-22/24 the Paper / Live switch: exit alert banner, Live read-only rows with the exit-watch chip and section", async ({ page }) => {
    const seen = await setup(page);
    await page.goto(at("pnl"));
    await expect(page.getByTestId("pnl-exit-banner")).toBeVisible(SLOW);
    await expect(page.getByTestId("pnl-exit-banner-count")).toHaveText("1 new exit alert");
    await expect(page.getByTestId("pnl-exits")).toHaveCount(0);
    await page.getByTestId("pv2-pnl-exit-golive").click();
    await expect(page.getByTestId("pv2-pnl-mode-live")).toHaveAttribute("aria-pressed", "true");
    await expect.poll(() => seen.pnlQueries.some((q) => q.get("mode") === "LIVE")).toBe(true);
    await expect(page.getByTestId("pv2-pnl")).toHaveAttribute("data-mode", "LIVE", SLOW);
    await expect(page.getByTestId("pv2-pnl-eyebrow")).toHaveText("Real-time live P&L · broker positions, read-only");
    await expect(page.getByTestId("pv2-pnl-return")).toHaveText("return not computed: MOCK: broker capital is not read");
    await expect(page.getByTestId("pv2-pnl-kpi-realized-sub")).toContainText("Brokers do not split their realised P&L");
    await expect(page.getByTestId("pnl-row")).toHaveCount(1);
    const infy = page.locator('[data-testid="pnl-row"][data-id="zr-1:INFY"]');
    await expect(infy.getByTestId("pv2-pnl-row-exit")).toHaveText("Exit watch · Stop hit · 1,625.00");
    await expect(infy.getByTestId("pv2-pnl-row-exit")).toHaveAttribute("data-status", "HIT");
    await expect(infy.getByTestId("pv2-pnl-plan")).toHaveAttribute("data-pos", "");
    await expect(page.getByTestId("pnl-exits")).toBeVisible();
    await expect(page.getByTestId("pv2-pnl-fno")).toHaveCount(0);
    await infy.click();
    const d = page.locator('[data-testid="pnl-row-detail"][data-id="zr-1:INFY"]');
    await expect(d.getByTestId("pnl-modify")).toBeDisabled();
    await expect(d.getByTestId("pnl-exit")).toHaveText("Initiate exit");
    await d.getByTestId("pnl-exit").click();
    await expect(d.getByTestId("pnl-exit-note")).toHaveText("Nivesh is read-only with brokers: exit this position in your broker's app. No order has been placed.");
    await page.waitForTimeout(400);
    expect(seen.closes).toEqual([]);
    expect(seen.sptExits).toEqual([]);
    expect(seen.patches).toEqual([]);
    await expect(page.getByTestId("pv2-pnl-foot")).toContainText("Nivesh places, modifies and cancels no broker order.");
    await page.getByTestId("pv2-pnl-mode-paper").click();
    await expect(page.getByTestId("pv2-pnl")).toHaveAttribute("data-mode", "PAPER", SLOW);
    await expect(page.getByTestId("pnl-exits")).toHaveCount(0);
  });

  test("PV2-B-UI-25 closed trades: the period goes to the route; a desk trade's journal opens; a scanner trade says where its record is", async ({ page }) => {
    const seen = await setup(page);
    await page.goto(at("pnl"));
    await expect(page.getByTestId("pnl-closed-empty")).toHaveText("No paper trade closed today.", SLOW);
    // The section sits at the bottom of the view.
    const tops = await page.evaluate(() => ["pnl-positions", "pv2-pnl-fno", "pnl-closed"].map((id) => (document.querySelector(`[data-testid="${id}"]`) as HTMLElement).getBoundingClientRect().top));
    expect(tops[0]).toBeLessThan(tops[1]);
    expect(tops[1]).toBeLessThan(tops[2]);
    await page.getByTestId("pnl-period-1w").click();
    await expect.poll(() => seen.pnlQueries.some((q) => q.get("period") === "1W")).toBe(true);
    await expect(page.getByTestId("pnl-closed-row")).toHaveCount(2);
    await expect(page.locator('[data-testid="pnl-closed-row"][data-id="pt-axis"]').getByTestId("pnl-closed-net")).toHaveText("−₹1,260.10");
    await expect(page.getByTestId("pv2-pnl-kpi-realized-sub")).toHaveText("2 closed this week · net of costs");
    await expect(page.getByTestId("pv2-pnl-kpi-realized-value")).toHaveText("−₹390.10");
    await expect(page.getByTestId("pv2-pnl-recon")).toContainText("2 checked against the ledger · 0 mismatches");
    await page.locator('[data-testid="pnl-closed-row"][data-id="pt-axis"]').getByTestId("pv2-pnl-closed-journal").click();
    await expect(page.getByTestId("pv2-pnl-journal").getByTestId("td-journal-timeline")).toBeVisible(SLOW);
    await page.locator('[data-testid="pnl-closed-row"][data-id="spt-old"]').getByTestId("pv2-pnl-closed-journal").click();
    await expect(page.getByTestId("pv2-pnl-journal-none")).toHaveText("This trade is not in the desk's paper book: a scanner trade keeps its record in Scanner opportunities.");
    await expect(page.getByTestId("pnl-notes")).toContainText("MOCK: charges are the desk cost card's.");
  });

  // ── empty and failed reads ───────────────────────────────────────────────
  test("PV2-B-UI-26 empty states say what is missing on all three views", async ({ page }) => {
    await setup(page, {
      exposures: { ...EXPOSURES, by_sector: [], by_instrument: [] }, ranked: { ...RANKED, items: [] },
      fno: { status: 200, body: { account_id: ACC, structures: [], totals: { margin_rs: 0, max_loss_rs: 0, net: {} }, limits: {}, basis: "MOCK", notes: [] } },
      corr: { status: 200, body: { symbols: ["ICICIBANK"], matrix: [[1]], days: 60, threshold: 0.7, basis: "MOCK", notes: [] } },
      pnl: (q) => ({ body: snapshot(q, undefined, (s) => { s.positions = []; s.strategies = []; s.pending_entries = []; }) }),
    });
    await page.goto(at("allocation"));
    await expect(page.getByTestId("pv2-al-sectors-empty")).toHaveText("No open sector exposure: no paper position or pending entry has a sector on record.", SLOW);
    await expect(page.getByTestId("pv2-al-fno-empty")).toHaveText("No open paper F&O structure on the desk, so no margin or max loss is allocated to F&O.");
    await expect(page.getByTestId("pv2-al-changes-empty")).toHaveText("No allocated opportunity right now, so there is no allocation change to rank.");
    await page.getByTestId("desk-sub-risk").click();
    await expect(page.getByTestId("pv2-rk-corr-empty")).toHaveText("Fewer than two open positions, so there is nothing to correlate.", SLOW);
    await expect(page.getByTestId("pv2-rk-fno-empty")).toHaveText("No open paper F&O structure on the desk, so there are no Greeks to net.");
    await expect(limitRow(page, "single_stock").getByTestId("pv2-limit-note")).toHaveText("No open position.");
    await page.getByTestId("desk-sub-pnl").click();
    await expect(page.getByTestId("pnl-positions-empty")).toHaveText("No open paper share position. F&O structures are listed below.", SLOW);
    await expect(page.getByTestId("pv2-pnl-fno-empty")).toHaveText("No open paper F&O structure on the desk.");
    await expect(page.getByTestId("pv2-pnl-strategies-empty")).toBeVisible();
  });

  test("PV2-B-UI-27 failures: the account and the policy say they did not load (Retry); without the F&O route the P&L view falls back and says so", async ({ page }) => {
    await setup(page, { account: { status: 500, body: { detail: "MOCK: down" } }, fno: { status: 404, body: { detail: "Not Found" } } });
    await page.route(/\/api\/v1\/paper\/accounts\/[^/]+\/policy(\?|$)/, (r) => json(r, { detail: "MOCK: down" }, 500));
    await page.goto(at("allocation"));
    await expect(page.getByTestId("pv2-al-error")).toBeVisible(SLOW);
    await expect(page.getByTestId("pv2-al-error").getByRole("button").first()).toBeVisible();
    await expect(page.getByTestId("pv2-policy-error")).toBeVisible();
    await expect(page.getByTestId("pv2-al-buckets")).toContainText("The account could not be read, so bucket use is unknown.");
    await page.getByTestId("desk-sub-pnl").click();
    await expect(page.getByTestId("pv2-pnl-fno-error")).toBeVisible(SLOW);
    await expect(page.getByTestId("pv2-pnl-fno-fallback")).toHaveCount(2);
    await expect(page.getByTestId("pv2-pnl-fno")).toContainText("Without the details route, each structure shows the P&L snapshot's own line");
  });

  // ── wording and the phone ────────────────────────────────────────────────
  test("PV2-B-UI-28 compliance lint: no recommend / pick / suggest in the three views' text, labels or titles", async ({ page }) => {
    await setup(page, { admin: true });
    for (const [sub, id] of [["allocation", "pv2-allocation"], ["risk", "pv2-risk"], ["pnl", "pv2-pnl"]] as const) {
      await page.goto(at(sub));
      await expect(page.getByTestId(id)).toBeVisible(SLOW);
      await page.waitForLoadState("networkidle");
      await page.waitForTimeout(400);
      const text = await page.getByTestId(id).evaluate((el) => {
        const out = [(el as HTMLElement).innerText];
        for (const n of Array.from(el.querySelectorAll("[aria-label],[title],[placeholder]"))) for (const a of ["aria-label", "title", "placeholder"]) { const v = n.getAttribute(a); if (v) out.push(v); }
        return out.join("\n");
      });
      expect(text, sub).not.toMatch(BANNED);
    }
  });

  test("PV2-B-UI-29 390 px: no sideways page scroll on the three views; tables scroll inside their cards", async ({ page }) => {
    await setup(page, { phone: true });
    for (const [sub, id] of [["allocation", "pv2-allocation"], ["risk", "pv2-risk"], ["pnl", "pv2-pnl"]] as const) {
      await page.goto(at(sub));
      await expect(page.getByTestId(id)).toBeVisible(SLOW);
      await page.waitForLoadState("networkidle");
      await page.waitForTimeout(500);
      await noSideScroll(page);
      await shot(page, id, `${id}-390.png`);
    }
    // The positions table is wider than the phone and scrolls inside its own card.
    const t = page.getByTestId("pnl-table");
    expect(await t.evaluate((el) => el.scrollWidth - el.clientWidth)).toBeGreaterThan(0);
    await page.locator('[data-testid="pnl-row"][data-id="pt-icici"]').click();
    await expect(page.getByTestId("pv2-pnl-detail-below")).toBeVisible();
    await noSideScroll(page);
  });
});
