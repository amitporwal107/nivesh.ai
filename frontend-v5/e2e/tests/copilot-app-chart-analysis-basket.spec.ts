/**
 * Chart Analysis v2 — the PAPER TRADE basket and the strategy panel (test_reports/chart_analysis_v2_TESTCASES.md U6–U9, U11).
 *
 * MOCK — not real data. Two parts:
 *   1. the pure bodies (analysis/presets.ts): presets from a synthetic chain, the payoff / margin requests, the two paper-trade
 *      bodies, family and direction readings — run directly, no browser;
 *   2. the screen with every /api route mocked in the shape the real route returns (route named beside each), against
 *      /v5/app/trader/desk?tab=trade&view=chart&sub=live&sym=TVSMOTOR. Marked fixme until the page
 *      (analysis/ChartAnalysis.tsx, feat/chart-analysis-v2) is merged with these panels.
 * Expected figures are worked out from the payloads in this file, never copied from the screen.
 */
import { test, expect, type Page, type Route } from "@playwright/test";
import type { BasketLeg } from "../../src/pages/CopilotApp/screens/tradingdesk/tabs/trade-desk/analysis/basket";
import type { AnalysisChain } from "../../src/pages/CopilotApp/screens/tradingdesk/tabs/trade-desk/analysis/chain-data";
import {
  PRESETS, cashBodyOf, directionOf, familyOf, futureLeg, levelsFor, marginBodyOf, payoffRequestOf, presetLegs, scenarioPcts, strategyBodyOf, todayProblem, underlyingLegs,
} from "../../src/pages/CopilotApp/screens/tradingdesk/tabs/trade-desk/analysis/presets";

// ── MOCK chain: TVSMOTOR-like, strikes 4100…4500 step 50, ATM 4300, lot 350 (synthetic values) ──
const STRIKES = [4100, 4150, 4200, 4250, 4300, 4350, 4400, 4450, 4500];
const CALL_CLOSE = [215, 178, 142, 110, 84, 62, 45, 31, 21];
const PUT_CLOSE = [18, 26, 38, 54, 76, 102, 133, 170, 210];
const sideRow = (close: number, iv: number) => ({ oi: 100000, oiChange: 5000, volume: 2000, close, iv, delta: null, gamma: null, theta: null, vega: null });
const CHAIN: AnalysisChain = {
  slot: "current", expiry: "2026-11-24", expiries: ["2026-11-24"], asOf: "2026-10-28", spot: 4296.5, atm: 4300, lotSize: 350, daysToExpiry: 27,
  pcr: 0.9, maxPain: 4300, callWall: { strike: 4500, oi: 900000 }, putWall: { strike: 4100, oi: 800000 }, totalCallOi: 1, totalPutOi: 1,
  totalCallOiChange: 0, totalPutOiChange: 0, atmIv: 30.1, expectedMove: 160, expectedMovePct: 3.7,
  rows: STRIKES.map((strike, i) => ({ strike, call: sideRow(CALL_CLOSE[i], 30 + i * 0.2), put: sideRow(PUT_CLOSE[i], 31 + i * 0.2) })),
  tradable: true, source: "MOCK",
};
const LAST = { price: 4296.5, at: "2026-10-29T11:42:08+05:30", source: "Kite live price" };
let n = 0;
const leg = (l: Omit<BasketLeg, "id">): BasketLeg => ({ ...l, id: `t${(n += 1)}` });
const opt = (side: "B" | "S", kind: "CE" | "PE", strike: number, entry: number, qty = 1) =>
  leg({ kind, side, qty, strike, expiry: "2026-11-24", entry, priceSource: "NSE F&O bhavcopy close, 2026-10-28", lotSize: 350 });
const NOW = new Date("2026-10-29T06:30:00Z");

test.describe("MOCK — not real data: basket bodies (pure)", () => {
  test("U6 presets are legs at the chain's strikes and closes; a missing strike or close disables the preset with why", () => {
    const by = (k: string) => PRESETS.find((p) => p.key === k)!;
    const bcs = presetLegs(by("bull_call_spread"), CHAIN);
    expect(bcs.ok).toBe(true);
    if (!bcs.ok) return;
    expect(bcs.legs.map((l) => [l.side, l.kind, l.strike, l.entry, l.qty, l.lotSize, l.expiry])).toEqual([
      ["B", "CE", 4300, 84, 1, 350, "2026-11-24"], ["S", "CE", 4400, 45, 1, 350, "2026-11-24"]]);
    expect(bcs.legs[0].priceSource).toBe("NSE F&O bhavcopy close, 2026-10-28");
    const ic = presetLegs(by("iron_condor"), CHAIN);
    expect(ic.ok && ic.legs.map((l) => `${l.side}${l.strike}${l.kind}`)).toEqual(["S4400CE", "B4500CE", "S4200PE", "B4100PE"]);
    const straddle = presetLegs(by("long_straddle"), CHAIN);
    expect(straddle.ok && straddle.legs.map((l) => `${l.side}${l.strike}${l.kind}@${l.entry}`)).toEqual(["B4300CE@84", "B4300PE@76"]);
    // a chain with only 3 strikes each side has no 4-step wing
    const narrow = { ...CHAIN, rows: CHAIN.rows.slice(1, 8) };
    const bad = presetLegs(by("iron_condor"), narrow);
    expect(bad).toEqual({ ok: false, why: "The chain has no strike 4 steps above the ATM strike 4300." });
    const noClose = { ...CHAIN, rows: CHAIN.rows.map((r) => (r.strike === 4400 ? { ...r, call: { ...r.call!, close: null } } : r)) };
    expect(presetLegs(by("bull_call_spread"), noClose)).toEqual({ ok: false, why: "4400 CE has no close on 2026-10-28, so it cannot be priced." });
    expect(presetLegs(by("bull_call_spread"), { ...CHAIN, tradable: false, expiry: null }).ok).toBe(false);
    expect(presetLegs(by("bull_call_spread"), CHAIN, "No F&O data for XYZ").ok).toBe(false);
    expect(by("short_strangle").warning).toMatch(/Unlimited loss/);
  });

  test("＋ Future takes the chain's expiry, priced at the close (settle when there is no close)", () => {
    const rows = [{ expiry: "2026-11-24", close: 4312.4, settle: 4310 }, { expiry: "2026-12-29", close: null, settle: 4340 }];
    const f = futureLeg(rows, "2026-10-28", CHAIN);
    expect(f.ok && [f.legs[0].expiry, f.legs[0].entry, f.legs[0].lotSize, f.legs[0].priceSource]).toEqual(["2026-11-24", 4312.4, 350, "NSE F&O bhavcopy close, 2026-10-28"]);
    const far = futureLeg(rows, "2026-10-28", { ...CHAIN, expiry: "2026-12-29" });
    expect(far.ok && [far.legs[0].entry, far.legs[0].priceSource]).toEqual([4340, "NSE F&O bhavcopy settle price, 2026-10-28"]);
    expect(futureLeg(rows, "2026-10-28", null).ok).toBe(false);
  });

  test("U7 the payoff request: legs as the route takes them, ±r grid, 11 scenarios, today curve; stop / target only for cash and futures", () => {
    const legs = [opt("B", "CE", 4300, 84), opt("S", "CE", 4400, 45)];
    const req = payoffRequestOf({ symbol: "TVSMOTOR", legs, refPrice: 4296.5, asOf: "2026-10-28", today: "2026-10-29", rangePct: 15, levels: { stop: 4200, target: 4450 } })!;
    expect(req.grid).toEqual({ from_pct: -15, to_pct: 15, points: 61 });
    expect(req.pre_expiry).toEqual({ date: "2026-10-29" });
    expect(req.as_of).toBe("2026-10-28");
    expect(req.reference_price).toBe(4296.5);
    expect(req.scenarios!.map((s) => s.name)).toEqual(["-15%", "-12%", "-9%", "-6%", "-3%", "0%", "+3%", "+6%", "+9%", "+12%", "+15%"]);
    // rounded to paise: 4296.5 × 0.85 = 3652.025 → 3652.03; 4296.5 × 1.15 is 4940.97499… in binary floating point → 4940.97
    expect(req.scenarios![0].underlying_price).toBe(3652.03);
    expect(req.scenarios![10].underlying_price).toBe(4940.97);
    expect(req.legs[0]).toMatchObject({ kind: "option", side: "buy", quantity: 1, lot_size: 350, entry_price: 84, strike: 4300, option_type: "call", expiry: "2026-11-24", underlying: "TVSMOTOR" });
    expect(scenarioPcts(5)).toEqual([-5, -4, -3, -2, -1, 0, 1, 2, 3, 4, 5]);
    const fut = leg({ kind: "FUT", side: "B", qty: 1, strike: null, expiry: "2026-11-24", entry: 4312.4, priceSource: "NSE F&O bhavcopy close, 2026-10-28", lotSize: 350 });
    const futReq = payoffRequestOf({ symbol: "TVSMOTOR", legs: [fut], refPrice: 4296.5, asOf: "2026-10-28", today: "2026-10-29", rangePct: 10, levels: { stop: 4200, target: 4450 } })!;
    expect(futReq.scenarios!.slice(11)).toEqual([{ name: "stop", underlying_price: 4200 }, { name: "target", underlying_price: 4450 }]);
    expect(todayProblem(legs, "2026-10-28", "2026-11-25")).toBe("The 24 Nov expiry has passed, so there is no today curve.");
    expect(payoffRequestOf({ symbol: "TVSMOTOR", legs, refPrice: 4296.5, asOf: "2026-10-28", today: "2026-11-25", rangePct: 10, levels: { stop: null, target: null } })!.pre_expiry).toBeUndefined();
    expect(underlyingLegs([fut, ...legs])).toEqual([fut]);
  });

  test("U8 the margin body: option and future legs only", () => {
    const fut = leg({ kind: "FUT", side: "B", qty: 2, strike: null, expiry: "2026-11-24", entry: 4312.4, priceSource: "x", lotSize: 350 });
    const cash = leg({ kind: "CASH", side: "B", qty: 350, strike: null, expiry: null, entry: 4296.5, priceSource: "x", lotSize: 1 });
    expect(marginBodyOf("TVSMOTOR", [opt("S", "PE", 4200, 38), fut, cash])).toEqual({
      underlying: "TVSMOTOR",
      legs: [{ side: "sell", option_type: "put", expiry: "2026-11-24", strike: 4200, lots: 1 }, { side: "buy", option_type: "future", expiry: "2026-11-24", strike: null, lots: 2 }],
    });
    expect(marginBodyOf("TVSMOTOR", [cash])).toBeNull();
  });

  test("U9 the strategy body: family from the shape, direction from the route's delta, levels on the right side, the signal", () => {
    const legs = [opt("B", "CE", 4300, 84), opt("S", "CE", 4400, 45)];
    expect(familyOf(legs)).toBe("bull_call_spread");
    // delta +52.5 shares vs the largest leg 350 units: 52.5 ≥ 35 → bullish
    const r = strategyBodyOf({ symbol: "TVSMOTOR", legs, refPrice: 4296.5, last: LAST, fnoAsOf: "2026-10-28", delta: 52.5, levels: { stop: 4200, target: 4450 }, planId: "tp-123", now: NOW });
    expect(r.ok).toBe(true);
    if (!r.ok) return;
    const b = r.body;
    expect(b).toMatchObject({ kind: "strategy", underlying: "TVSMOTOR", direction: "bullish", family: "bull_call_spread", reference_price: 4296.5, stop_underlying: 4200, target_underlying: 4450, plan_ref: { plan_id: "tp-123" } });
    expect(b.legs).toEqual([
      { kind: "option", side: "buy", lots: 1, lot_size: 350, entry_price: 84, expiry: "2026-11-24", strike: 4300, option_type: "call", price_source: "NSE F&O bhavcopy close, 2026-10-28" },
      { kind: "option", side: "sell", lots: 1, lot_size: 350, entry_price: 45, expiry: "2026-11-24", strike: 4400, option_type: "call", price_source: "NSE F&O bhavcopy close, 2026-10-28" },
    ]);
    expect(b.signal.signal_at).toBe("2026-10-29T06:30:00.000Z");
    expect(b.signal.rule_version).toBe("chart-analysis-v2");
    expect(b.signal.source_refs?.map((s) => s.kind)).toEqual(["option_chain", "live_chart", "trade_plan"]);
    expect(b.signal.evidence_summary).toContain("BUY 1 lot of 350 4300 CE 24 Nov at ₹84.00");
    expect(b.signal.evidence_summary.length).toBeLessThanOrEqual(1000);
    // a stop above the reference is refused for a bullish position, before anything is posted
    const wrong = strategyBodyOf({ symbol: "TVSMOTOR", legs, refPrice: 4296.5, last: LAST, fnoAsOf: "2026-10-28", delta: 52.5, levels: { stop: 4350, target: null }, planId: null, now: NOW });
    expect(wrong).toEqual({ ok: false, problems: ["For a bullish position the stop (₹4,350.0) must be below the reference ₹4,296.5."] });
    // an iron condor with delta near zero is neutral and sends no levels
    const ic = [opt("S", "CE", 4400, 45), opt("B", "CE", 4500, 21), opt("S", "PE", 4200, 38), opt("B", "PE", 4100, 18)];
    expect(familyOf(ic)).toBe("iron_condor");
    const neutral = strategyBodyOf({ symbol: "TVSMOTOR", legs: ic, refPrice: 4296.5, last: LAST, fnoAsOf: "2026-10-28", delta: -3.1, levels: { stop: 4200, target: 4450 }, planId: null, now: NOW });
    expect(neutral.ok && [neutral.body.direction, "stop_underlying" in neutral.body, "plan_ref" in neutral.body]).toEqual(["neutral", false, false]);
    expect(directionOf(null, legs).direction).toBeNull();
    expect(directionOf(-40, legs).direction).toBe("bearish");
    expect(levelsFor("bearish", 4296.5, { stop: 4400, target: 4100 })).toMatchObject({ stop_underlying: 4400, target_underlying: 4100, problems: [] });
    expect(familyOf([opt("B", "PE", 4300, 76), opt("S", "PE", 4200, 38)])).toBe("bear_put_spread");
    expect(familyOf([opt("S", "CE", 4400, 45), opt("S", "PE", 4200, 38)])).toBe("custom");
  });

  test("U9 the share trade body for a cash-only basket: long only, a stop below the entry", () => {
    const cash = leg({ kind: "CASH", side: "B", qty: 350, strike: null, expiry: null, entry: 4296.5, priceSource: "Kite live price, 2026-10-29T11:42:08+05:30", lotSize: 1 });
    const r = cashBodyOf({ symbol: "TVSMOTOR", leg: cash, levels: { stop: 4200, target: 4450, cashEntry: null }, rule: "at_once", planId: null, now: NOW });
    expect(r.ok && r.body).toMatchObject({
      symbol: "TVSMOTOR", quantity: 350, entry_price: 4296.5, stop_price: 4200, target_price: 4450, entry_rule: "at_once",
      source: { kind: "chart_analysis", signal_date: "2026-10-29" }, signal_at: "2026-10-29T06:30:00.000Z", strategy_version: "chart-analysis-v2",
    });
    expect(r.ok && "plan_ref" in r.body).toBe(false);
    const chartEntry = cashBodyOf({ symbol: "TVSMOTOR", leg: cash, levels: { stop: 4200, target: null, cashEntry: 4250 }, rule: "pullback_to", planId: "tp-9", now: NOW });
    expect(chartEntry.ok && [chartEntry.body.entry_price, chartEntry.body.entry_rule, chartEntry.body.target_price, chartEntry.body.plan_ref]).toEqual([4250, "pullback_to", null, { plan_id: "tp-9" }]);
    expect(cashBodyOf({ symbol: "TVSMOTOR", leg: { ...cash, side: "S" }, levels: { stop: null, target: null, cashEntry: null }, rule: "at_once", planId: null, now: NOW }))
      .toEqual({ ok: false, problems: ["A share paper trade is long only: selling shares is not recorded. Flip the cash leg to BUY.", "Set a stop below the entry: a share paper trade needs one."] });
  });
});

// ── the screen (route-mocked) ─────────────────────────────────────────────

const DESK = "/v5/app/trader/desk";
const URL_ = `${DESK}?tab=trade&view=chart&sub=live&sym=TVSMOTOR`;
const SLOW = { timeout: 15_000 };
const json = (r: Route, body: unknown, status = 200) => r.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });

/** GET /api/fno/{sym}/chain in the route's shape (backend/routes/fno.py :: chain), from the synthetic rows above. */
const CHAIN_ROUTE = {
  symbol: "TVSMOTOR",
  summary: { as_of: "2026-10-28", expiry: "2026-11-24", spot: 4296.5, atm_strike: 4300, total_call_oi: 900000, total_put_oi: 810000, total_call_oi_change: 45000, total_put_oi_change: 45000,
    pcr: 0.9, max_pain: 4300, max_call_oi: { strike: 4500, oi: 100000 }, max_put_oi: { strike: 4100, oi: 100000 }, put_wall: { strike: 4100, oi: 100000 }, call_wall: { strike: 4500, oi: 100000 },
    days_to_expiry: 27, forward: 4310, forward_basis: "future", rate_pct: 6.5, atm_iv: 30.1, expected_move: 160, expected_move_pct: 3.7 },
  strikes: STRIKES.map((strike, i) => ({
    strike,
    call: { close: CALL_CLOSE[i], settle: CALL_CLOSE[i], oi: 100000, change_in_oi: 5000, volume: 2000, iv: 30 + i * 0.2, delta: null, gamma: null, theta: null, vega: null },
    put: { close: PUT_CLOSE[i], settle: PUT_CLOSE[i], oi: 90000, change_in_oi: 5000, volume: 2000, iv: 31 + i * 0.2, delta: null, gamma: null, theta: null, vega: null },
  })),
  strike_count: 9, lot_size: 350,
};
const EXPIRIES = { symbol: "TVSMOTOR", as_of: "2026-10-28", expiries: [{ expiry: "2026-11-24", days_to_expiry: 27 }, { expiry: "2026-12-29", days_to_expiry: 62 }] };
const FUTURES = { symbol: "TVSMOTOR", as_of: "2026-10-28", spot: 4296.5, futures: [{ expiry: "2026-11-24", close: 4312.4, settle: 4310, oi: 1, change_in_oi: 1, volume: 1, basis: 13.5 }] };
const DAYS = Array.from({ length: 40 }, (_, i) => new Date(Date.UTC(2026, 8, 1 + i)).toISOString().slice(0, 10));
const LIVE_CHART = {
  symbol: "TVSMOTOR", as_of: "2026-10-29T11:42:08+05:30",
  timeframe: { interval: "1d", label: "DAILY", source: "end of day", adjusted: false, reason: "token_expired", live_merged: false, note: "MOCK" },
  bars: DAYS.map((d, i) => [d, 4200 + i, 4210 + i, 4190 + i, 4205 + i, 100000]), ema20: DAYS.map((_, i) => (i < 19 ? null : 4220)), rvol: DAYS.map(() => 1),
  last: { price: 4296.5, at: "2026-10-28", bar_complete: true },
  levels: { source: "plan", plan_id: null, entry: 4300, stop: 4200, targets: [{ name: "base", price: 4450, primary: true }], rule: "at_once", valid_for_sessions: null, reference_close: 4296.5, direction: "bullish", signal_date: "2026-10-28", invalidation: null },
  signal: null, signals_error: null, markers: [], conditions: [], evaluated_at_bar: "2026-10-28",
};

/** POST /api/desk/strategy/payoff (MOCK — not real data): the request's own scenario names, synthetic numbers. */
function payoffAnswer(req: { scenarios: Array<{ name: string; underlying_price: number }>; reference_price: number; legs: unknown[] }, greeks = true) {
  const grid = Array.from({ length: 61 }, (_, i) => req.reference_price * (0.9 + i * 0.2 / 60));
  const pnl = (p: number) => Math.max(-13650, Math.min(21350, (p - 4339) * 350));
  return {
    valid: true, problems: [], warnings: [], calculation_version: "payoff-v2", underlying: "TVSMOTOR", reference_price: req.reference_price, as_of: "2026-10-28",
    expiry: { grid, gross: grid.map(pnl), net: grid.map((p) => pnl(p) - 60), per_leg: [], breakevens: [4339], max_profit: 21350, max_loss: -13650, profit_unbounded: false, loss_unbounded: false,
      net_premium: -13650, scenarios: req.scenarios.map((s) => ({ name: s.name, underlying_price: s.underlying_price, gross: pnl(s.underlying_price), net: pnl(s.underlying_price) - 60 })) },
    pre_expiry: { date: "2026-10-29", model: "Black-76", assumptions: {}, grid, gross: grid.map((p) => pnl(p) * 0.6), net: grid.map((p) => pnl(p) * 0.6 - 60),
      greeks: { delta: 52.5, gamma: 0.0841, theta: -310.2, vega: 120.5, rho: 1 },
      per_leg_greeks: [{ leg: 0, label: "Buy", greeks: { delta: 180.1, gamma: 0.3, theta: -900.4, vega: 600.2, rho: 1 } }, { leg: 1, label: "Sell", greeks: { delta: -127.6, gamma: -0.2159, theta: 590.2, vega: -479.7, rho: 0 } }],
      unavailable: [],
      ...(greeks ? { scenarios: req.scenarios.map((s) => ({ name: s.name, underlying_price: s.underlying_price, gross: pnl(s.underlying_price) * 0.6, net: 0, greeks: { delta: 50, gamma: 0.08, theta: -300, vega: 110, rho: 1 } })) } : {}) },
    costs: null, margin: null, capital_at_risk: -13800, caveats: [], sent_to_broker: false,
  };
}

interface Seen { payoff: Array<Record<string, unknown>>; margin: Array<Record<string, unknown>>; posts: Array<Record<string, unknown>> }

async function setup(page: Page, o: { margin?: { status: number; body: unknown }; post?: { status: number; body: unknown }; phone?: boolean } = {}): Promise<Seen> {
  const seen: Seen = { payoff: [], margin: [], posts: [] };
  if (o.phone) await page.setViewportSize({ width: 390, height: 844 });
  await page.route("**/api/**", (r) => json(r, { detail: "MOCK: not mocked in this spec" }, 404));
  await page.route("**/api/auth/me", (r) => json(r, { user_id: "u1", email: "mock@example.com", name: "Mock", role: "admin", features: [] }));
  await page.route("**/api/live/**", (r) => json(r, { available: false, reason: "MOCK: feed off", quotes: {}, mode: "expired", session: "closed", stale: true }));
  await page.route("**/api/desk/live-chart/*", (r) => json(r, LIVE_CHART));
  await page.route("**/api/fno/*/expiries", (r) => json(r, EXPIRIES));
  await page.route("**/api/fno/*/chain?*", (r) => json(r, CHAIN_ROUTE));
  await page.route("**/api/fno/*/futures", (r) => json(r, FUTURES));
  await page.route("**/api/fno/*/iv-history*", (r) => json(r, { symbol: "TVSMOTOR", sessions: 0, min_sessions: 252, iv_percentile: null, reason: "MOCK: not recorded", series: [] }));
  await page.route("**/api/desk/strategy/payoff", (r) => { const b = r.request().postDataJSON(); seen.payoff.push(b); return json(r, payoffAnswer(b)); });
  await page.route("**/api/fno/margin", (r) => {
    seen.margin.push(r.request().postDataJSON());
    return json(r, o.margin?.body ?? { required_margin: 41250.5, initial_margin: 98700, charges: { per_order: [], total: {} }, as_of: "2026-10-29", source: "MOCK Zerodha", note: "MOCK", sent_to_broker: false }, o.margin?.status ?? 200);
  });
  await page.route("**/api/desk/paper-trades*", (r) => {
    if (r.request().method() !== "POST") return json(r, { as_of: "2026-10-28", trades: [], summary: null });
    seen.posts.push(r.request().postDataJSON());
    return json(r, o.post?.body ?? { trade: { id: "pt-1", kind: "strategy", legs: [] }, risk: null }, o.post?.status ?? 201);
  });
  return seen;
}

async function openBasket(page: Page) {
  await page.goto(URL_);
  await page.getByTestId("ca-paper-btn").click(SLOW);
  await expect(page.getByTestId("ca-basket")).toBeVisible();
}

test.describe("MOCK — not real data: Chart Analysis basket and strategy panel (screen)", () => {

  test("U6 a preset fills the basket with the chain's strikes around ATM", async ({ page }) => {
    await setup(page);
    await openBasket(page);
    await expect(page.getByTestId("ca-basket-empty")).toBeVisible();
    await page.getByTestId("ca-preset-bull_call_spread").click();
    const legs = page.getByTestId("ca-basket-leg");
    await expect(legs).toHaveCount(2);
    await expect(legs.nth(0)).toHaveAttribute("data-strike", "4300");
    await expect(legs.nth(1)).toHaveAttribute("data-strike", "4400");
    await expect(legs.nth(1)).toHaveAttribute("data-side", "S");
    await expect(page.getByTestId("ca-preset-short_strangle-warning")).toHaveText("∞ loss");
  });

  test("U7 strategy panel: legs table, payoff, scenario table from the mocked answer; range buttons re-request", async ({ page }) => {
    const seen = await setup(page);
    await openBasket(page);
    await page.getByTestId("ca-preset-bull_call_spread").click();
    const panel = page.locator("#ca-strategy-panel");
    await expect(panel.getByTestId("ca-strategy-leg")).toHaveCount(2);
    await expect(panel.getByTestId("ca-strategy-delta").first()).toHaveText("180.10");
    await expect(panel.getByTestId("ca-total-gamma")).toHaveText("0.0841");
    await expect(panel.getByTestId("ca-strategy-iv").first()).toHaveText("30.8%");  // 4300 call: 30 + 4 × 0.2
    await expect(panel.getByTestId("ca-payoff-maxloss")).toHaveText("MAX LOSS −₹13,650");
    await expect(panel.getByTestId("ca-payoff-be")).toHaveAttribute("data-value", "4339");
    await expect(panel.getByTestId("ca-scenario-head-cell")).toHaveCount(11);
    await panel.getByTestId("ca-range-15").click();
    await expect.poll(() => seen.payoff.at(-1)?.grid).toEqual({ from_pct: -15, to_pct: 15, points: 61 });
  });

  test("U8 margin: Zerodha's answer → required, no benefit figure; 503 → needs today's Kite login", async ({ page }) => {
    await setup(page);
    await openBasket(page);
    await page.getByTestId("ca-preset-bull_call_spread").click();
    await expect(page.getByTestId("ca-margin-required")).toHaveText("₹41,251");
    await expect(page.getByTestId("ca-margin-benefit")).toHaveText("—");
  });

  test("U8 margin 503 says the Kite login is needed", async ({ page }) => {
    await setup(page, { margin: { status: 503, body: { detail: "kite_session_unavailable" } } });
    await openBasket(page);
    await page.getByTestId("ca-preset-bull_call_spread").click();
    await expect(page.getByTestId("ca-margin-note")).toHaveText("Margin needs today's Kite login.");
  });

  test("U9 place: an options basket posts kind strategy with the legs; the route's refusal is shown", async ({ page }) => {
    const seen = await setup(page, { post: { status: 422, body: { detail: "unbounded_loss" } } });
    await openBasket(page);
    await page.getByTestId("ca-preset-bull_call_spread").click();
    await page.getByTestId("ca-basket-place").click();
    await expect.poll(() => seen.posts.length).toBe(1);
    expect(seen.posts[0]).toMatchObject({ kind: "strategy", underlying: "TVSMOTOR", family: "bull_call_spread", direction: "bullish" });
    await expect(page.getByTestId("ca-basket-answer")).toContainText("unbounded_loss");
  });

  test("U9 place: a cash-only basket posts the share trade", async ({ page }) => {
    const seen = await setup(page, { post: { status: 201, body: { trade: { id: "pt-cash" }, risk: null } } });
    await openBasket(page);
    await page.getByTestId("ca-basket-add-cash").click();
    await page.getByTestId("ca-level-stop").fill("4200");
    await page.getByTestId("ca-basket-place").click();
    await expect.poll(() => seen.posts.length).toBe(1);
    expect(seen.posts[0]).toMatchObject({ symbol: "TVSMOTOR", quantity: 350, stop_price: 4200, source: { kind: "chart_analysis" } });
    expect(seen.posts[0].kind).toBeUndefined();
    await expect(page.getByTestId("ca-basket-answer")).toHaveAttribute("data-ok", "true");
  });

  test("U11 390 px: no sideways page scroll; the strategy tables scroll inside their boxes", async ({ page }) => {
    await setup(page, { phone: true });
    await openBasket(page);
    await page.getByTestId("ca-preset-iron_condor").click();
    const o = await page.evaluate(() => {
      const sc = document.querySelector('[data-testid="copilot-scroll"]') as HTMLElement | null;
      const box = document.querySelector('[data-testid="ca-strategy-legs-box"]') as HTMLElement | null;
      return { doc: document.documentElement.scrollWidth - window.innerWidth, scroll: sc ? sc.scrollWidth - sc.clientWidth : 0, box: box ? box.scrollWidth - box.clientWidth : -1 };
    });
    expect(o.doc).toBeLessThanOrEqual(1);
    expect(o.scroll).toBeLessThanOrEqual(1);
    expect(o.box).toBeGreaterThan(0);
  });
});
