/**
 * One-screen Copilot app - Smart trading desk: "Best picks from my Chartink scans" (screens/tradingdesk/chartink/ChartinkPicks.tsx).
 * The Chartink settings (?tab=more&view=chartink) list the picks; the Overview "Top AI opportunities" card shows the top 3 with "See all"; the Strategy
 * Builder's ideas board has a source filter "Chartink best picks".
 *
 * MOCK - not real data. Every /api answer below is written by hand to the contract (picks-contract.ts, GET /api/desk/chartink/picks). The scan names,
 * stocks and figures are INVENTED (public repo). The scores are HAND-COMPUTED from the factor weights (scan 25, trend 12, momentum 10, relative volume 8,
 * liquidity 8, OI build-up 10, fundamentals 10, event 8, range 5, ATR 4 = 100; a factor that does not apply leaves the weight; unavailable earns 0):
 *
 *   ZEDCO     long, F&O, 2 aligned scans (credit 2/3 -> 16.67) + trend 12 + momentum 10 + volume 8 + liquidity 8 + OI 10 + fundamentals 5 (neutral, half)
 *             + event 8 + range 5 + ATR 4 = 86.67 of 100 -> 86.7
 *   MOONCORP  short, F&O, 2 aligned bearish scans 16.67 + trend 12 + momentum 10 + volume 8 + liquidity 8 + OI 10 + fundamentals 0 (unavailable)
 *             + event 8 + range 5 + ATR 2 (neutral) = 79.67 of 100 -> 79.7
 *   TESTBRK   long, in the AI scanner too, 2 aligned scans, not F&O (OI does not apply, 90 of weight): 16.67 + 12 + 10 + 4 + 4 + 5 + 8 + 2.5 + 4 = 66.17
 *             of 90 -> 73.5
 *   QUBEX     long, not F&O, 2 aligned scans and 1 against (credit (2-1)/3 = 1/3 -> 8.33, a conflict) + 12 + 10 + 4 + 4 + 0 (fundamentals unavailable) + 8
 *             + 2.5 + 2 = 50.83 of 90 -> 56.5
 *   Order: ZEDCO 86.7, MOONCORP 79.7, TESTBRK 73.5, QUBEX 56.5. The Overview shows the first 3 ("1 more").
 *   Wait / No trade: PLANETX (thin evidence, 28.0), WIDGETCO (bullish and bearish scans tie: no direction).
 *   Payoff mock (POST /api/desk/strategy/payoff): cash buy 100 shares at 250 -> P&L at 275 = (275 - 250) x 100 = 2,500.
 *
 * Cases: PK-1 settings list (order, icon, score and its label, chips, reasons, trust) · PK-2 strategies expand, payoff, open in Strategy Builder
 * PK-3 breakdown with source and as-of · PK-4 Wait / No trade and the shortfall · PK-5 honest states · PK-7 ideas board filter ·
 * PK-8 390px, no sideways scroll · PK-9 reads only, no order controls. PK-6 (the old Overview's top 3) left with OverviewTab in the
 * desk redesign's step 6.
 */
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";
import { test, expect, type Page, type Route } from "@playwright/test";
import { mockApi, mockSingleRoute } from "../helpers/api-mock";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const DESK = "/v5/app/trader/desk";
const SETTINGS = `${DESK}?tab=more&view=chartink`;
const IDEAS = `${DESK}?tab=more&view=strategy`;
const json = (route: Route, body: unknown, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
const planFixture = (n: string) => JSON.parse(fs.readFileSync(path.join(__dirname, "..", "fixtures", `strategy-plan-${n}.json`), "utf-8"));
const SHOTS = process.env.SHOTS_DIR;
const shot = async (page: Page, name: string, w: number) => {
  if (!SHOTS) return;
  fs.mkdirSync(SHOTS, { recursive: true });
  await page.screenshot({ path: path.join(SHOTS, `ckpicks-${name}-${w}.png`), fullPage: false });
};

// ── MOCK payloads ────────────────────────────────────────────────────────

const FETCHED = "2026-10-20T05:00:00+00:00"; // 10:30 IST
const run = (hits: number) => ({ at: FETCHED, ok: true, hits, error: null, seconds: 2.4 });
const scan = (o: Record<string, unknown>) => ({ description: null, kind: "stock_scan", supported: true, unsupported_reason: null, uses_intraday_candles: false, enabled: true, direction: "bullish", last_run: null, ...o });
const SCANS = [scan({ id: "1001", name: "Volume Burst Sample", last_run: run(4) }), scan({ id: "1005", name: "Weak Close Sample", direction: "bearish", last_run: run(2) }), scan({ id: "1006", name: "Range Break Sample", last_run: run(3) })];
const SOURCE = { dashboard_id: "900001", url: "https://chartink.com/dashboard/900001", title: "Sample dashboard", fetched_at: FETCHED, scans: SCANS,
  summary: { scans: 3, stock_scans: 3, supported: 3, enabled: 3 }, refresh: { last_started_at: null, retry_after_s: null } };
const HITS = { as_of_date: "2026-10-19", fetched_at: FETCHED, mode: "end_of_day_snapshot", scans: SCANS.map((s) => ({ id: s.id, name: s.name, direction: s.direction, hits: 1, ok: true, error: null, uses_intraday_candles: false })),
  symbols: [], is_today: false, age_days: 1, dashboard_id: "900001", empty_reason: "MOCK: no symbols", unknown_symbols: [], source_failures: [] };
const WATCHLIST = { as_of_date: "2026-10-19", buckets: { breakout_confirmed: [], pre_breakout: [], true_accumulation: [], trend_continuation: [] } };

const W: Record<string, number> = { scan_confluence: 25, trend: 12, momentum: 10, relative_volume: 8, liquidity: 8, oi_buildup: 10, fundamentals: 10, event_risk: 8, range_position: 5, atr_risk: 4 };
const LABEL: Record<string, string> = { scan_confluence: "Scan confluence", trend: "Trend (EMA)", momentum: "Momentum (MACD, 20-day change, RSI)", relative_volume: "Relative volume", liquidity: "Liquidity",
  oi_buildup: "F&O open-interest build-up", fundamentals: "Fundamentals quality", event_risk: "Event risk (results)", range_position: "Distance from 52-week extremes", atr_risk: "ATR risk" };
const f = (key: string, state: string, points: number, text: string) => ({ key, label: LABEL[key], weight: W[key], points, state, tone: "x", text, value: null,
  source: state === "unavailable" || state === "not_applicable" ? null : `MOCK source of ${key}`, as_of: state === "unavailable" || state === "not_applicable" ? null : "2026-10-19" });
const S1001 = { id: "1001", name: "Volume Burst Sample", direction: "bullish" };
const S1006 = { id: "1006", name: "Range Break Sample", direction: "bullish" };
const S1005 = { id: "1005", name: "Weak Close Sample", direction: "bearish" };
const S1007 = { id: "1007", name: "Lower High Sample", direction: "bearish" };

const ZED_FACTORS = [f("scan_confluence", "supports", 16.67, "2 of your enabled bullish Chartink scans listed it: Volume Burst Sample, Range Break Sample. A scan is a rule match you chose, not validated and not a probability."),
  f("trend", "supports", 12, "Trend up: close 250.00 vs EMA50 230.00."), f("momentum", "supports", 10, "MACD histogram +1.50, 20-day change +4.00%."),
  f("relative_volume", "supports", 8, "Relative volume 1.80x the 20-session average confirms."), f("liquidity", "supports", 8, "20-session traded value Rs 120 crore a day."),
  f("oi_buildup", "supports", 10, "Futures OI build-up: long_buildup."), f("fundamentals", "neutral", 5, "1 of 2 readable quality tests passed."),
  f("event_risk", "supports", 8, "No results date inside the 10-day horizon."), f("range_position", "supports", 5, "4% below its 52-week high."), f("atr_risk", "supports", 4, "ATR(14) is 1.67% of the close.")];
const MOON_FACTORS = [f("scan_confluence", "supports", 16.67, "2 of your enabled bearish Chartink scans listed it."), f("trend", "supports", 12, "Trend down."), f("momentum", "supports", 10, "MACD histogram -1.00."),
  f("relative_volume", "supports", 8, "Relative volume 1.90x."), f("liquidity", "supports", 8, "20-session traded value Rs 90 crore a day."), f("oi_buildup", "supports", 10, "Futures OI build-up: short_buildup."),
  f("fundamentals", "unavailable", 0, "Only 1 of 3 quality figures are readable (at least 2 are needed; missing: debt-to-equity, cash conversion)."), f("event_risk", "supports", 8, "No results date inside the horizon."),
  f("range_position", "supports", 5, "6% above its 52-week low."), f("atr_risk", "neutral", 2, "ATR(14) is 3.00% of the close: medium gap and stop risk.")];
const TB_FACTORS = [f("scan_confluence", "supports", 16.67, "2 of your enabled bullish Chartink scans listed it."), f("trend", "supports", 12, "Trend up."), f("momentum", "supports", 10, "MACD histogram +0.90."),
  f("relative_volume", "neutral", 4, "Relative volume 1.20x is ordinary."), f("liquidity", "neutral", 4, "20-session traded value Rs 20 crore a day."), f("oi_buildup", "not_applicable", 0, "Not an F&O stock: this factor does not apply."),
  f("fundamentals", "neutral", 5, "1 of 2 readable quality tests passed."), f("event_risk", "supports", 8, "No results date inside the horizon."), f("range_position", "neutral", 2.5, "20% below its 52-week high."), f("atr_risk", "supports", 4, "ATR(14) is 1.90% of the close.")];
const QB_FACTORS = [f("scan_confluence", "conflicts", 8.33, "2 of your enabled bullish Chartink scans listed it. 1 opposing scan (Weak Close Sample) also listed it and takes 1 of 3 off the credit."), f("trend", "supports", 12, "Trend up."),
  f("momentum", "supports", 10, "MACD histogram +0.40."), f("relative_volume", "neutral", 4, "Relative volume 1.10x is ordinary."), f("liquidity", "neutral", 4, "20-session traded value Rs 15 crore a day."),
  f("oi_buildup", "not_applicable", 0, "Not an F&O stock: this factor does not apply."), f("fundamentals", "unavailable", 0, "Fundamental columns unavailable: no feature row."),
  f("event_risk", "supports", 8, "No results date inside the horizon."), f("range_position", "neutral", 2.5, "25% below its 52-week high."), f("atr_risk", "neutral", 2, "ATR(14) is 3.40% of the close.")];

const ST = (o: Record<string, unknown>) => ({ segment: "cash", family: "", status: "candidate", reasons: [], legs_text: null, max_loss: null, max_loss_basis: null, capital_at_risk: null, max_profit: null,
  profit_unbounded: false, breakeven: [], reward_risk_net: null, reward_risk_gross: null, actionable: true, liquidity_flags: [], why: null, flags: [], payoff_request: null,
  sizing: { status: "complete", quantity: null, lots: null, binding: null, unit: null, risk_budget_inr: null, risk_at_stop_inr: null, deployed_inr: null, missing: [] }, ...o });
const CASH_LEG = { kind: "cash", side: "buy", quantity: 100, lot_size: 1, entry_price: 250, expiry: null, strike: null, option_type: null, price_source: "MOCK close", iv_pct: null };
const ZED_STRATS = [
  ST({ id: "cash:breakout_continuation", segment: "cash", label: "Buy shares on the breakout", legs_text: "Buy 100 shares ZEDCO", max_loss: -2000, max_loss_basis: "to the stop at 230", capital_at_risk: 2040, max_profit: 5000,
    breakeven: [250.4], reward_risk_net: 2.4, reward_risk_gross: 2.5, why: "Breakout above the 20-session resistance.", sizing: { status: "complete", quantity: 100, lots: null, binding: "risk_budget", unit: "shares", risk_budget_inr: 2000, risk_at_stop_inr: 2000, deployed_inr: 25000, missing: [] },
    payoff_request: { underlying: "ZEDCO", reference_price: 250, as_of: "2026-10-19", legs: [CASH_LEG], grid: { min: 200, max: 300, points: 21 } } }),
  ST({ id: "options:bull_call_spread", segment: "options", label: "Bull call spread", legs_text: "Buy 1 lot ZEDCO 260 call + Sell 1 lot ZEDCO 280 call, 24 Nov", max_loss: -4000, max_profit: 6000, breakeven: [268],
    reward_risk_net: 1.5, reward_risk_gross: 1.6, sizing: { status: "complete", quantity: 500, lots: 1, binding: "risk_budget", unit: "lots", risk_budget_inr: 5000, risk_at_stop_inr: 4000, deployed_inr: 4000, missing: [] },
    payoff_request: { underlying: "ZEDCO", reference_price: 250, as_of: "2026-10-19", legs: [{ kind: "option", side: "buy", quantity: 1, lot_size: 500, entry_price: 8, expiry: "2026-11-24", strike: 260, option_type: "call", price_source: "MOCK", iv_pct: null }, { kind: "option", side: "sell", quantity: 1, lot_size: 500, entry_price: 0, expiry: "2026-11-24", strike: 280, option_type: "call", price_source: "MOCK", iv_pct: null }] } }),
  ST({ id: "futures:long_buildup_continuation", segment: "futures", label: "Long futures", status: "no_trade", actionable: false, reasons: [{ code: "reward_risk_below_minimum", message: "Reward : risk 1.1 is below the minimum 1.5." }] }),
];
const MOON_STRATS = [ST({ id: "options:bear_put_spread", segment: "options", label: "Bear put spread", legs_text: "Buy 1 lot MOONCORP 600 put + Sell 1 lot MOONCORP 570 put", max_loss: -3000, max_profit: 5000, breakeven: [594], reward_risk_net: 1.6, reward_risk_gross: 1.7 })];
const TB_STRATS = [ST({ id: "cash:breakout_continuation", label: "Buy shares on the breakout", legs_text: "Buy 10 shares TESTBRK", max_loss: -500, capital_at_risk: 520, max_profit: 1200, reward_risk_net: 2.3, reward_risk_gross: 2.4 }),
  ST({ id: "options:none", segment: "options", label: "No options strategy", status: "no_trade", actionable: false, reasons: [{ code: "not_fno_eligible", message: "The stock is not in the NSE F&O segment: only the cash idea applies." }] })];
const QB_STRATS = [ST({ id: "cash:chartink_screen_signal", family: "chartink_screen_signal", label: "Chartink scan signal (long)", legs_text: "Buy 5 shares QUBEX", max_loss: -400, capital_at_risk: 420, max_profit: 900, reward_risk_net: 2.1, reward_risk_gross: 2.2 })];

const pick = (o: Record<string, unknown>) => ({ rank: null, name: null, source: "chartink", in_ai_scanner: false, ai_score: null, direction: "long", action: "Long idea: the long side of the plan below (cash, futures, defined-risk options, combinations).",
  outcome: "pick", score: null, score_label: "evidence score — not a probability", scans: { aligned: [], opposed: [], count: 0 }, factors: [], available_weight_pct: 100, reasons_for: [], reasons_against: [], unavailable: [],
  wait_reasons: [], plan_id: "plan_mock", plan_status: "plan", preferred: null, strategies: [], data_as_of: { price: "2026-10-19", fno: "2026-10-19" }, fno_eligible: true, close: 250, plan_inputs: null, ...o });
const reasons = (...a: Array<[string, string, string]>) => a.map(([key, label, text]) => ({ key, label, text, points: null, weight: null, source: null, as_of: null }));
const PLAN_IN = (sym: string, direction = "bullish") => ({ underlying: sym, direction, instrument: "all", capital: 1000000 });
const PICKS = [
  pick({ rank: 1, symbol: "ZEDCO", name: "Zed Industries Ltd", score: 86.7, scans: { aligned: [S1001, S1006], opposed: [], count: 2 }, factors: ZED_FACTORS, preferred: "cash:breakout_continuation", strategies: ZED_STRATS, plan_inputs: PLAN_IN("ZEDCO"),
    reasons_for: reasons(["scan_confluence", "Scan confluence", "2 of your enabled bullish Chartink scans listed it."], ["trend", "Trend (EMA)", "Trend up: close 250.00 vs EMA50 230.00."], ["momentum", "Momentum (MACD, 20-day change, RSI)", "MACD histogram +1.50."]),
    reasons_against: [] }),
  pick({ rank: 2, symbol: "MOONCORP", name: "Moon Corp Ltd", score: 79.7, direction: "short", action: "Avoid new longs. Short side only through futures or defined-risk options (no naked short options); the plan below lists what the evidence supports.",
    scans: { aligned: [S1005, S1007], opposed: [], count: 2 }, factors: MOON_FACTORS, strategies: MOON_STRATS, plan_inputs: PLAN_IN("MOONCORP", "bearish"), available_weight_pct: 90,
    reasons_for: reasons(["trend", "Trend (EMA)", "Trend down."]), unavailable: reasons(["fundamentals", "Fundamentals quality", "Only 1 of 3 quality figures are readable."]) }),
  pick({ rank: 3, symbol: "TESTBRK", name: "Test Breakout Ltd", source: "both", in_ai_scanner: true, ai_score: 71, score: 73.5, scans: { aligned: [S1001, S1006], opposed: [], count: 2 }, factors: TB_FACTORS, strategies: TB_STRATS,
    plan_inputs: PLAN_IN("TESTBRK"), fno_eligible: false, reasons_for: reasons(["trend", "Trend (EMA)", "Trend up."]) }),
  pick({ rank: 4, symbol: "QUBEX", name: "Qubex Systems Ltd", score: 56.5, scans: { aligned: [S1001, S1006], opposed: [S1005], count: 3 }, factors: QB_FACTORS, strategies: QB_STRATS, plan_inputs: PLAN_IN("QUBEX"), fno_eligible: false, available_weight_pct: 88.9,
    reasons_for: reasons(["trend", "Trend (EMA)", "Trend up."]), reasons_against: reasons(["scan_confluence", "Scan confluence", "1 opposing scan (Weak Close Sample) also listed it."]),
    unavailable: reasons(["fundamentals", "Fundamentals quality", "Fundamental columns unavailable: no feature row."]) }),
];
const WAIT = [
  pick({ symbol: "PLANETX", name: "Planet X Ltd", outcome: "wait", score: 28, available_weight_pct: 25, factors: [], wait_reasons: ["Thin evidence: only 25% of the scoring weight could be read (at least 60% is needed). Unavailable: Trend (EMA), Momentum, Relative volume."] }),
  pick({ symbol: "WIDGETCO", name: "Widget Co Ltd", outcome: "wait", direction: null, action: null, score: null, available_weight_pct: null, wait_reasons: ["Both bullish and bearish scans listed it, as many each way: the scans conflict, so there is no direction to score."] }),
];
const BODY = (o: Record<string, unknown> = {}) => ({
  state: "ok", reason: null, label: "evidence score — not a probability", generated_at: "2026-10-20T05:01:00+00:00", limit: 5, direction_filter: "all", dashboard_id: "900001", rules_version: "strategy-rules.v1.5 (2026-10-20)",
  ranking_note: "Each Chartink stock that passes the eligibility gates is scored on real evidence; the score ranks the evidence and is not a probability.",
  data_as_of: { mode: "end_of_day", chartink: { scan_date: "2026-10-19", fetched_at: FETCHED, mode: "end_of_day_snapshot" }, price: "2026-10-19", fno: "2026-10-19", scan_eligibility: "2026-10-19" },
  considered: 6, evaluated: 5, not_evaluated: 0, qualified: 4, returned: 4, coverage_note: "Scored 5 of the 6 Chartink stocks with a bullish or bearish scan hit (the most scans first, then the highest traded value; at most 12 per request): 0 were not scored and 1 failed the eligibility gates.", picks: PICKS, wait: WAIT, excluded: [{ symbol: "CASHIETF", code: "etf", reason: "an ETF" }], empty_reason: null,
  shortfall_reason: "Only 4 of the 5 asked qualified. 2 evaluated stock(s) are Wait / No trade: PLANETX (Thin evidence); WIDGETCO (Both bullish and bearish scans listed it). 1 stock(s) failed the eligibility gates.",
  source_failures: [], caveats: ["Conditional research ideas, not advice and not an instruction to trade.", "Nothing is sent to a broker."], sent_to_broker: false, ...o });

/** MOCK payoff engine: the expiry P&L of cash and option legs on the request's grid, net of a flat 40 for costs. Not the real engine. */
function payoffFor(req: { legs: Array<Record<string, number | string | null>>; grid?: { min: number; max: number; points: number } }) {
  const g = req.grid ?? { min: 200, max: 300, points: 21 };
  const grid = Array.from({ length: g.points }, (_, i) => g.min + ((g.max - g.min) * i) / (g.points - 1));
  const gross = grid.map((p) => req.legs.reduce((sum, l) => {
    const q = Number(l.quantity) * Number(l.lot_size) * (l.side === "buy" ? 1 : -1);
    if (l.kind === "cash") return sum + (p - Number(l.entry_price)) * q;
    const intrinsic = l.option_type === "call" ? Math.max(0, p - Number(l.strike)) : Math.max(0, Number(l.strike) - p);
    return sum + (intrinsic - Number(l.entry_price)) * q;
  }, 0));
  const net = gross.map((v) => v - 40);
  return { valid: true, problems: [], warnings: [], calculation_version: "payoff-v1", expiry: { grid, gross, net, per_leg: [], breakevens: [], max_profit: Math.max(...gross), max_loss: Math.min(...gross), profit_unbounded: false, loss_unbounded: false, net_premium: null, scenarios: [] },
    pre_expiry: null, costs: null, margin: null, capital_at_risk: null, sent_to_broker: false };
}

// ── page plumbing ────────────────────────────────────────────────────────

interface Opts { picks?: Array<{ status: number; body: unknown }>; source?: unknown }
interface State { picksCalls: number; picksUrls: string[]; payoffs: Array<Record<string, unknown>>; plans: Array<Record<string, unknown>>; writes: string[]; ideas: number }

async function setup(page: Page, o: Opts = {}): Promise<State> {
  const st: State = { picksCalls: 0, picksUrls: [], payoffs: [], plans: [], writes: [], ideas: 0 };
  const queue = [...(o.picks ?? [])];
  await mockApi(page, "populated");
  await mockSingleRoute(page, "**/api/markets/home", "markets-home.json");
  page.on("request", (r) => {
    const p = new URL(r.url()).pathname;
    if (r.method() !== "GET" && /\/api\//.test(p) && !/\/api\/desk\/strategy\/(ideas|plan|payoff)$/.test(p)) st.writes.push(`${r.method()} ${p}`);
  });
  await page.route("**/api/positional/watchlist*", (r) => json(r, WATCHLIST));
  await page.route("**/api/positional/picks*", (r) => json(r, { signal_date: "2026-10-19", count: 0, picks: [] }));
  await page.route("**/api/move-odds/**", (r) => json(r, { detail: "feature_not_enabled" }, 403));
  await page.route("**/api/desk/paper-trades*", (r) => json(r, { as_of: null, trades: [], summary: null }));
  await page.route("**/api/desk/alerts*", (r) => json(r, { as_of: null, alerts: [] }));
  await page.route("**/api/desk/strategy/plans*", (r) => json(r, { plans: [], count: 0, limit: 100, max_saved: 200 }));
  await page.route("**/api/research/chart-live/**", (r) => json(r, { detail: "not mocked here" }, 404));
  await page.route("**/api/chat/**", (r) => json(r, []));
  await page.route("**/api/watchlists", (r) => json(r, { lists: [], limits: { max_lists: 20, max_symbols: 50 }, starter_pending: false }));
  await page.route("**/api/desk/strategy/ideas", (r) => {
    st.ideas += 1;
    return json(r, { generated_at: "2026-10-20T05:00:00+00:00", data_as_of: { mode: "end_of_day", price: "2026-10-19", fno: "2026-10-19" }, caveats: [], rules_version: "strategy-rules.v1.5", calculation_version: "payoff-v1", sent_to_broker: false,
      ranking_note: "MOCK ranking note", selection: { source: "positional_watchlist", scan_date: "2026-10-19", rule: "MOCK rule", considered: 0, selected: 0, excluded: [], limit: 8, empty_reason: "MOCK: the scanner has no setups.", gate: null, source_failures: [], chartink: null },
      inputs: { defaults_applied: [] }, ideas: [] });
  });
  await page.route("**/api/desk/strategy/plan", (r) => { st.plans.push(r.request().postDataJSON()); return json(r, planFixture("all")); });
  await page.route("**/api/desk/strategy/payoff", (r) => { const b = r.request().postDataJSON(); st.payoffs.push(b); return json(r, payoffFor(b)); });
  await page.route("**/api/desk/chartink/source", (r) => (r.request().method() === "GET" ? json(r, { source: o.source === undefined ? SOURCE : o.source }) : json(r, { detail: "not mocked" }, 405)));
  await page.route("**/api/desk/chartink/hits", (r) => json(r, HITS));
  await page.route("**/api/desk/chartink/picks*", (r) => {
    st.picksCalls += 1;
    st.picksUrls.push(r.request().url());
    const next = queue.length > 1 ? queue.shift() : queue[0];
    return next ? json(r, next.body, next.status) : json(r, BODY());
  });
  return st;
}
async function open(page: Page, url: string, o: Opts = {}, width = 1440) {
  await page.setViewportSize({ width, height: 900 });
  const st = await setup(page, o);
  await page.goto(url);
  return st;
}
async function sideways(page: Page) {
  return page.evaluate(() => {
    const sc = document.querySelector('[data-testid="copilot-scroll"]') as HTMLElement | null;
    return { doc: document.documentElement.scrollWidth - window.innerWidth, scroll: sc ? sc.scrollWidth - sc.clientWidth : 0 };
  });
}
const card = (page: Page, sym: string) => page.locator(`[data-testid="ck-pick"][data-symbol="${sym}"]`);

test.describe("MOCK - not real data: best picks from my Chartink scans", () => {
  // ── PK-1 ─────────────────────────────────────────────────────────────

  test("PK-1 settings: picks in score order, icon beside the name, the score with its 'not a probability' label, factor chips with tone and text, reasons, trust line", async ({ page }) => {
    const st = await open(page, SETTINGS);
    const sec = page.getByTestId("ck-picks");
    await expect(sec.getByTestId("ck-picks-title")).toHaveText("Best picks from my Chartink scans");
    await expect(sec).toHaveAttribute("data-state", "ok");
    expect(st.picksUrls[0]).toContain("/api/desk/chartink/picks?limit=5");
    const cards = sec.getByTestId("ck-pick");
    await expect(cards).toHaveCount(4);
    await expect(cards.locator('[data-testid="ck-pick-symbol"]')).toHaveText(["ZEDCO", "MOONCORP", "TESTBRK", "QUBEX"]);
    await expect(cards.locator('[data-testid="ck-pick-rank"]')).toHaveText(["01", "02", "03", "04"]);
    await expect(cards.locator('[data-testid="ck-pick-score"]')).toHaveText(["86.7/100", "79.7/100", "73.5/100", "56.5/100"]);
    await expect(cards.locator('[data-testid="ck-pick-score-label"]')).toHaveText(Array(4).fill("evidence score — not a probability"));

    const z = card(page, "ZEDCO");
    await expect(z.locator('[data-testid="entity-icon"]').first()).toBeVisible();      // the company icon beside the name
    await expect(z.getByTestId("ck-pick-name")).toHaveText("Zed Industries Ltd");
    await expect(z.getByTestId("ck-pick-direction")).toHaveText("Long");
    await expect(z.getByTestId("ck-pick-source")).toHaveText("Chartink");
    await expect(card(page, "TESTBRK").getByTestId("ck-pick-source")).toHaveText("AI scanner + Chartink");
    await expect(z.getByTestId("ck-pick-scans")).toContainText("Volume Burst Sample, Range Break Sample");
    // ten chips, each with a tone (state) and words, not colour alone
    const chips = z.getByTestId("ck-pick-factor");
    await expect(chips).toHaveCount(10);
    await expect(z.locator('[data-testid="ck-pick-factor"][data-key="fundamentals"]')).toHaveAttribute("data-state", "neutral");
    await expect(z.locator('[data-testid="ck-pick-factor"][data-key="trend"]')).toContainText("Trend 12/12");
    await expect(z.locator('[data-testid="ck-pick-factor"][data-key="trend"]')).toContainText("Supports");
    await expect(z.locator('[data-testid="ck-pick-factor"][data-key="fundamentals"]')).toContainText("Fundamentals quality 5/10");
    // the OI factor on a non-F&O stock is "not applicable", an unreadable figure is "unavailable": neither is neutral
    await expect(card(page, "TESTBRK").locator('[data-testid="ck-pick-factor"][data-key="oi_buildup"]')).toHaveAttribute("data-state", "not_applicable");
    await expect(card(page, "MOONCORP").locator('[data-testid="ck-pick-factor"][data-key="fundamentals"]')).toHaveAttribute("data-state", "unavailable");
    await expect(card(page, "MOONCORP").locator('[data-testid="ck-pick-factor"][data-key="fundamentals"]')).toContainText("unavailable");
    // reasons for and against, and what could not be read
    await expect(z.getByTestId("ck-pick-for")).toContainText("Why it ranks");
    await expect(z.getByTestId("ck-pick-for")).toContainText("Trend up: close 250.00 vs EMA50 230.00.");
    await expect(z.getByTestId("ck-pick-against")).toHaveCount(0);
    await expect(card(page, "QUBEX").getByTestId("ck-pick-against")).toContainText("1 opposing scan (Weak Close Sample)");
    await expect(card(page, "QUBEX").getByTestId("ck-pick-unavailable")).toContainText("Fundamental columns unavailable: no feature row.");
    // the short side says so, in words
    await expect(card(page, "MOONCORP").getByTestId("ck-pick-direction")).toHaveText("Short side");
    await expect(card(page, "MOONCORP").getByTestId("ck-pick-action")).toContainText("no naked short options");
    // trust line on every card and on the section
    for (const sym of ["ZEDCO", "MOONCORP", "TESTBRK", "QUBEX"]) {
      const t = card(page, sym).getByTestId("ck-pick-trust");
      await expect(t).toContainText("Chartink scans (your dashboard)");
      await expect(t).toContainText("scan 19 Oct 2026");
      await expect(t).toHaveAttribute("data-mode", "eod");
      await expect(t).toContainText("evidence score, not a probability");
    }
    await expect(sec.getByTestId("ck-picks-trust")).toContainText("rules strategy-rules.v1.5");
    await expect(sec.getByTestId("ck-picks-shortfall")).toContainText("Only 4 of the 5 asked qualified");
    await expect(sec.getByTestId("ck-picks-excluded")).toContainText("CASHIETF (an ETF)");
    await expect(sec.getByTestId("ck-picks-coverage")).toContainText("Scored 5 of the 6 Chartink stocks");
    await shot(page, "settings", 1440);
  });

  // ── PK-2 ─────────────────────────────────────────────────────────────

  test("PK-2 strategies are expandable rows with the plan's figures and the payoff; Open in Strategy Builder carries the pick's plan inputs", async ({ page }) => {
    const st = await open(page, SETTINGS);
    const z = card(page, "ZEDCO");
    const rows = z.getByTestId("ck-pick-strategy");
    await expect(rows).toHaveCount(3);
    await expect(z.getByTestId("ck-pick-strategies")).toContainText("2 viable of 3");
    await expect(rows.nth(0).getByTestId("ck-pick-strategy-toggle")).toHaveAttribute("aria-expanded", "false");
    await expect(rows.nth(0).getByTestId("ck-pick-preferred")).toHaveText("★ preferred");
    await expect(rows.nth(0).getByTestId("ck-pick-strategy-summary")).toContainText("Max loss ₹2,000.00");
    await expect(rows.nth(0).getByTestId("ck-pick-strategy-detail")).toBeHidden();
    // a strategy that is not viable shows its reason and no number
    await expect(rows.nth(2).getByTestId("ck-pick-strategy-status")).toContainText("No trade");
    await expect(rows.nth(2).getByTestId("ck-pick-strategy-summary")).toContainText("Reward : risk 1.1 is below the minimum 1.5.");

    await rows.nth(0).getByTestId("ck-pick-strategy-toggle").click();
    await expect(rows.nth(0).getByTestId("ck-pick-strategy-toggle")).toHaveAttribute("aria-expanded", "true");
    const d = rows.nth(0).getByTestId("ck-pick-strategy-detail");
    await expect(d.getByTestId("ck-pick-strategy-legs")).toHaveText("Buy 100 shares ZEDCO");
    await expect(d.getByTestId("ck-pick-st-maxloss")).toContainText("₹2,000.00 (to the stop at 230)");
    await expect(d.getByTestId("ck-pick-st-maxprofit")).toContainText("₹5,000.00");
    await expect(d.getByTestId("ck-pick-st-rr")).toContainText("2.40 : 1 net");
    await expect(d.getByTestId("ck-pick-st-breakeven")).toHaveText("250.40");
    await expect(d.getByTestId("ck-pick-st-sizing")).toContainText("100 shares");
    await expect(d.getByTestId("ck-pick-st-margin")).toContainText("no margin source exists");   // margin is never invented
    // the payoff is the payoff engine's: the request carries the plan's own leg
    await expect(d.getByTestId("ck-pick-payoff")).toBeVisible();
    expect(st.payoffs).toHaveLength(1);
    expect(st.payoffs[0]).toMatchObject({ underlying: "ZEDCO", reference_price: 250, legs: [{ kind: "cash", side: "buy", quantity: 100, entry_price: 250 }] });
    // the options row: its two legs
    await rows.nth(1).getByTestId("ck-pick-strategy-toggle").click();
    await expect(rows.nth(1).getByTestId("ck-pick-strategy-legs")).toContainText("Buy 1 lot ZEDCO 260 call + Sell 1 lot ZEDCO 280 call");
    await expect.poll(() => st.payoffs.length).toBe(2);

    // Open in Strategy Builder: One stock mode, with the pick's inputs and the chosen strategy in the URL
    await d.getByTestId("ck-pick-open-builder").click();
    await expect(page).toHaveURL(/tab=trade/); // was tab=more&view=strategy before the 2026-10-27 redesign
    await expect(page).toHaveURL(/view=lab&sub=build/);
    await expect(page).toHaveURL(/mode=stock/);
    await expect(page).toHaveURL(/sym=ZEDCO/);
    await expect(page).toHaveURL(/src_kind=chartink_picks/);
    await expect(page).toHaveURL(/src_date=2026-10-19/);               // the Strategy Builder reads cand once and then removes it from the URL
    await expect.poll(() => st.plans.length).toBeGreaterThan(0);
    expect(st.plans[0]).toMatchObject({ underlying: "ZEDCO", direction: "bullish" });
    await expect(page.getByText("Started from your Chartink best picks").first()).toBeVisible();
  });

  test("PK-2b a short-side pick opens the Strategy Builder with the bearish direction", async ({ page }) => {
    const st = await open(page, SETTINGS);
    const m = card(page, "MOONCORP");
    await m.getByTestId("ck-pick-strategy-toggle").first().click();
    await m.getByTestId("ck-pick-open-builder").click();
    await expect(page).toHaveURL(/sym=MOONCORP/);
    await expect(page).toHaveURL(/direction=bearish/);
    await expect.poll(() => st.plans.length).toBeGreaterThan(0);
    expect(st.plans[0]).toMatchObject({ underlying: "MOONCORP", direction: "bearish" });
  });

  // ── PK-3 ─────────────────────────────────────────────────────────────

  test("PK-3 the score breakdown lists every factor with its points, state, words, source and as-of date", async ({ page }) => {
    await open(page, SETTINGS);
    const q = card(page, "QUBEX");
    await expect(q.getByTestId("ck-pick-breakdown")).toBeHidden();
    await q.getByTestId("ck-pick-breakdown-toggle").click();
    const rows = q.getByTestId("ck-pick-breakdown-row");
    await expect(rows).toHaveCount(10);
    await expect(rows.nth(0)).toContainText("Scan confluence · Conflicts · 8.3 of 25");
    await expect(rows.nth(0)).toContainText("MOCK source of scan_confluence · as of 2026-10-19");
    await expect(rows.nth(5)).toContainText("F&O open-interest build-up · Not applicable · left out of the weight");
    await expect(rows.nth(6)).toContainText("Fundamentals quality · Unavailable · 0 of 10");
    await expect(rows.nth(6)).toContainText("no source");
  });

  // ── PK-4 ─────────────────────────────────────────────────────────────

  test("PK-4 Wait / No trade lists the evaluated stocks that are not picks, with the reason; picks can be fewer than asked, and it says why", async ({ page }) => {
    await open(page, SETTINGS);
    const sec = page.getByTestId("ck-picks");
    await expect(sec.getByTestId("ck-picks-wait-toggle")).toHaveText("▸ Wait / No trade (2): evaluated, but not picks");
    await expect(sec.getByTestId("ck-picks-wait")).toBeHidden();
    await sec.getByTestId("ck-picks-wait-toggle").click();
    const rows = sec.getByTestId("ck-wait-row");
    await expect(rows).toHaveCount(2);
    await expect(rows.nth(0)).toContainText("PLANETX");
    await expect(rows.nth(0)).toContainText("Wait");
    await expect(rows.nth(0)).toContainText("28/100 evidence score — not a probability");
    await expect(rows.nth(0)).toContainText("Thin evidence: only 25% of the scoring weight could be read");
    await expect(rows.nth(1)).toContainText("Both bullish and bearish scans listed it");
    await expect(rows.nth(1)).toContainText("Widget Co Ltd");
    await expect(rows.nth(0).locator('[data-testid="entity-icon"]').first()).toBeVisible();
    // a Wait stock is not drawn as a pick: no score card, no strategies
    await expect(sec.locator('[data-testid="ck-pick"][data-symbol="PLANETX"]')).toHaveCount(0);
  });

  // ── PK-5 ─────────────────────────────────────────────────────────────

  test("PK-5 honest states: error with Retry, then the picks; no picks says why; the Chartink states say what is wrong", async ({ page }) => {
    const st = await open(page, SETTINGS, { picks: [{ status: 500, body: { detail: "boom" } }, { status: 200, body: BODY() }] });
    const sec = page.getByTestId("ck-picks");
    await expect(sec.getByTestId("ck-picks-error")).toContainText("Your Chartink best picks didn’t load");
    await expect(sec.getByTestId("ck-pick")).toHaveCount(0);
    await sec.getByRole("button", { name: /Retry/ }).click();
    await expect(sec.getByTestId("ck-pick")).toHaveCount(4);
    expect(st.picksCalls).toBe(2);
  });

  test("PK-5b no qualifying picks says why; a contract drift is an error, not an empty list", async ({ page }) => {
    await open(page, SETTINGS, { picks: [{ status: 200, body: BODY({ picks: [], returned: 0, qualified: 0, empty_reason: "Only 0 of the 5 asked qualified. 2 evaluated stock(s) are Wait / No trade: PLANETX (Thin evidence); WIDGETCO (Both bullish and bearish scans listed it)." }) }] });
    const sec = page.getByTestId("ck-picks");
    await expect(sec.getByTestId("ck-picks-empty")).toContainText("No qualifying picks right now.");
    await expect(sec.getByTestId("ck-picks-empty")).toContainText("Only 0 of the 5 asked qualified.");
    await expect(sec.getByTestId("ck-pick")).toHaveCount(0);
    await sec.getByTestId("ck-picks-wait-toggle").click();
    await expect(sec.getByTestId("ck-wait-row")).toHaveCount(2);

    const page2 = await page.context().newPage();
    await open(page2, SETTINGS, { picks: [{ status: 200, body: { state: "ok" } }] });
    await expect(page2.getByTestId("ck-picks-error")).toBeVisible();
    await expect(page2.getByTestId("ck-pick")).toHaveCount(0);
  });

  for (const [state, word] of [["no_source", "No Chartink dashboard is connected."], ["not_refreshed", "have not been refreshed yet"], ["stale", "too old to pick from"], ["failed", "could not be read"]] as const) {
    test(`PK-5c state ${state}`, async ({ page }) => {
      await open(page, SETTINGS, { picks: [{ status: 200, body: BODY({ state, reason: `MOCK reason for ${state}`, picks: [], wait: [], data_as_of: { mode: "end_of_day", chartink: null, price: null, fno: null, scan_eligibility: null }, returned: 0, qualified: 0, evaluated: 0, considered: 0, excluded: [], shortfall_reason: null, empty_reason: `MOCK reason for ${state}` }) }] });
      const s = page.getByTestId("ck-picks-state");
      await expect(s).toHaveAttribute("data-state", state);
      await expect(s).toContainText(word);
      await expect(s).toContainText(`MOCK reason for ${state}`);
      await expect(page.getByTestId("ck-pick")).toHaveCount(0);
    });
  }

  test("PK-5d no dashboard connected: no picks section and no picks request", async ({ page }) => {
    const st = await open(page, SETTINGS, { source: null });
    await expect(page.getByTestId("chartink-not-connected")).toBeVisible();
    await expect(page.getByTestId("ck-picks")).toHaveCount(0);
    expect(st.picksCalls).toBe(0);
  });

  // ── PK-7 ─────────────────────────────────────────────────────────────

  test("PK-7 Strategy Builder ideas board: a source filter 'Chartink best picks' shows the picks in place of the ideas, and 'All ideas' brings them back", async ({ page }) => {
    const st = await open(page, IDEAS);
    const filter = page.getByTestId("ideas-source-filter");
    await expect(filter.getByTestId("ideas-source-all")).toHaveAttribute("aria-pressed", "true");
    await expect(page.getByTestId("ideas-view")).toBeVisible();
    await expect(page.getByTestId("ideas-ck-picks")).toHaveCount(0);
    await filter.getByTestId("ideas-source-ck_picks").click();
    await expect(filter.getByTestId("ideas-source-ck_picks")).toHaveAttribute("aria-pressed", "true");
    const sec = page.getByTestId("ideas-ck-picks");
    await expect(sec.getByTestId("ck-pick")).toHaveCount(4);
    await expect(page.getByTestId("ideas-view")).toHaveCount(0);
    // back to every idea: the ideas view returns and the picks go
    await filter.getByTestId("ideas-source-all").click();
    await expect(page.getByTestId("ideas-view")).toBeVisible();
    await expect(page.getByTestId("ideas-ck-picks")).toHaveCount(0);
    // from the picks, a strategy opens in One stock mode with the pick's plan inputs
    await filter.getByTestId("ideas-source-ck_picks").click();
    await sec.getByTestId("ck-pick-strategy-toggle").first().click();
    await sec.getByTestId("ck-pick-open-builder").first().click();
    await expect(page).toHaveURL(/mode=stock/);
    await expect(page).toHaveURL(/sym=ZEDCO/);
    await expect.poll(() => st.plans.length).toBeGreaterThan(0);
  });

  test("PK-7b the filter is absent without a connected dashboard", async ({ page }) => {
    await open(page, IDEAS, { source: null });
    await expect(page.getByTestId("ideas-view")).toBeVisible();
    await expect(page.getByTestId("ideas-source-filter")).toHaveCount(0);
  });

  // ── PK-8 ─────────────────────────────────────────────────────────────

  // The old Overview's top-3 picks (and its 390px case) left with OverviewTab in the desk redesign's step 6.
  for (const [name, url] of [["settings", SETTINGS], ["ideas", IDEAS]] as const) {
    test(`PK-8 390px ${name}: the picks do not scroll the page sideways`, async ({ page }) => {
      await open(page, url, {}, 390);
      if (name === "ideas") await page.getByTestId("ideas-source-ck_picks").click();
      const sel = name === "settings" ? "ck-picks" : "ideas-ck-picks";
      const sec = page.getByTestId(sel);
      await expect(sec.getByTestId("ck-pick").first()).toBeVisible();
      await sec.getByTestId("ck-pick-strategy-toggle").first().click();
      await expect(sec.getByTestId("ck-pick-strategy-detail").first()).toBeVisible();
      await sec.getByTestId("ck-pick-breakdown-toggle").first().click();
      const s = await sideways(page);
      expect(s.doc).toBeLessThanOrEqual(0);
      expect(s.scroll).toBeLessThanOrEqual(0);
      await shot(page, name, 390);
    });
  }

  // ── PK-9 ─────────────────────────────────────────────────────────────

  test("PK-9 reads only: the picks are a GET, nothing is written, and there is no order control", async ({ page }) => {
    const st = await open(page, SETTINGS);
    await expect(page.getByTestId("ck-picks").getByTestId("ck-pick")).toHaveCount(4);
    await card(page, "ZEDCO").getByTestId("ck-pick-strategy-toggle").first().click();
    expect(st.writes).toEqual([]);
    const text = (await page.getByTestId("ck-picks").innerText()).toLowerCase();
    for (const w of ["place order", "buy now", "sell now", "execute", "send to broker"]) expect(text).not.toContain(w);
    await expect(page.getByTestId("ck-picks").getByRole("button", { name: /order|execute/i })).toHaveCount(0);
  });
});
