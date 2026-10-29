/**
 * Chart Analysis v2 — the OPTION CHAIN (design item 6) and the strategy cards (design item 9)
 * (test_reports/chart_analysis_v2_TESTCASES.md U3, U4, U5, U6, U11, U13).
 *
 * Two parts:
 *   1. "logic"  Node-context tests of analysis/reco-data.ts (no `page` fixture, no browser): the module imports types only,
 *               so nothing from the app's runtime is evaluated. These run now.
 *   2. "page"   the components on the Chart Analysis page (/v5/app/trader/desk?tab=trade&view=chart&sub=live&sym=TVSMOTOR),
 *               mocked APIs on a production build. test.fixme until the page's BasketPanel and StrategyPanel are merged
 *               (flip PAGE_LANDED then).
 *
 * MOCK — not real data. The plan payloads are e2e/fixtures/strategy-plan-*.json: the REAL output of the plan builder over the
 * fixture world of backend/tests/test_strategy_plan.py (RELIANCE-like: close 1200 on 2026-10-19, lot 250, chain 2026-11-24,
 * bull call spread 1200 / 1250 at 52 / 38), re-labelled TVSMOTOR here. The chain, live-chart, oi-buildup, expiries,
 * consolidated, chart-events and live-quote answers are inline MOCKs in the routes' shapes (trading/fno.ts, chain-data.ts,
 * live-chart-data.ts, routes/live_quotes.py).
 */
import { test, expect, type Page, type Route } from "@playwright/test";
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";
import { mockApi, mockSingleRoute } from "../helpers/api-mock";
import {
  callCells, candidateLegs, cardExpiry, cardFigures, cardTag, cardWhy, chainTemplate, engineOrder, kiteTradeDay, legsText, liveByContract,
  liveLegsFor, liveQuoteCounts, noTradeReasons, notQualifying, oiChangePct, pickBlock, putCells, topActionable,
} from "../../src/pages/CopilotApp/screens/tradingdesk/tabs/trade-desk/analysis/reco-data";
import type { AnalysisChain, StrikeRow } from "../../src/pages/CopilotApp/screens/tradingdesk/tabs/trade-desk/analysis/chain-data";
import type { StrategyPlan, Candidate } from "../../src/pages/CopilotApp/screens/tradingdesk/strategy/plan-contract";

/** Flip to true once analysis/BasketPanel.tsx and analysis/StrategyPanel.tsx are on the branch (the page imports both). */
const PAGE_LANDED = false;

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const load = (name: string) => JSON.parse(fs.readFileSync(path.join(__dirname, "..", "fixtures", name), "utf-8"));
const clone = <T,>(x: T): T => JSON.parse(JSON.stringify(x));
const json = (route: Route, body: unknown, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });

// MOCK — not real data: the plan builder's output over the backend test world (see the header).
const PLAN_ALL = load("strategy-plan-all.json") as StrategyPlan;
const PLAN_NOTRADE = load("strategy-plan-notrade.json") as StrategyPlan;
const relabel = (p: StrategyPlan): StrategyPlan => {
  const c = clone(p);
  c.underlying.symbol = "TVSMOTOR";
  c.inputs.underlying = "TVSMOTOR";
  return c;
};

// ── MOCK chain: 15 strikes 850 … 1550 (step 50), ATM 1200, expiry 2026-11-24, end of day 2026-10-28, lot 250 ───────────
const EXPIRY = "2026-11-24";
const AS_OF = "2026-10-28";
const STRIKES = Array.from({ length: 15 }, (_, i) => 850 + i * 50);
type Side = { close: number | null; settle: number | null; oi: number | null; change_in_oi: number | null; volume: number | null; iv: number | null; iv_price: "close" | null; delta: number | null; gamma: number | null; theta: number | null; vega: number | null };
const side = (k: number, call: boolean): Side => {
  const d = (k - 1200) / 50;                                                    // strikes from the money
  const close = call ? Math.max(4, 52 - d * 14) : Math.max(4, 40 + d * 14);
  return {
    close: Math.round(close * 100) / 100, settle: Math.round(close * 100) / 100,
    oi: 100_000 + (call ? Math.max(0, d) : Math.max(0, -d)) * 40_000, change_in_oi: 10_000, volume: 5_000,
    iv: 22.5, iv_price: "close", delta: call ? 0.5 - d * 0.08 : -0.5 - d * 0.08, gamma: 0.00321, theta: -1.25, vega: 1.4,
  };
};
const CHAIN_ROWS = STRIKES.map((k) => ({ strike: k, call: side(k, true), put: side(k, false) }));
const row = (k: number) => CHAIN_ROWS.find((r) => r.strike === k)!;
row(1250).call.oi = 300_000; row(1250).call.change_in_oi = 60_000;            // OI Δ% = 60,000 / 240,000 = +25.0%
row(1150).put.oi = 200_000; row(1150).put.change_in_oi = -50_000;             // OI Δ% = −50,000 / 250,000 = −20.0%
row(1200).call.close = 52; row(1250).call.close = 38;                          // the plan's legs (fixture)
row(1450).call.volume = 0;                                                     // did not trade on the day: no price to pick
row(1500).put.close = null;                                                    // no close at all
const CHAIN_BODY = {
  symbol: "TVSMOTOR",
  summary: {
    as_of: AS_OF, expiry: EXPIRY, spot: 1203, atm_strike: 1200, total_call_oi: 3_000_000, total_put_oi: 2_700_000, total_call_oi_change: 150_000, total_put_oi_change: 90_000,
    pcr: 0.9, max_pain: 1200, max_call_oi: { strike: 1250, oi: 300_000 }, max_put_oi: { strike: 1150, oi: 200_000 }, put_wall: { strike: 1150, oi: 200_000 }, call_wall: { strike: 1250, oi: 300_000 },
    days_to_expiry: 27, forward: 1205, forward_basis: "future", rate_pct: 5.75, atm_iv: 22.5, expected_move: 92, expected_move_pct: 7.65,
  },
  strikes: CHAIN_ROWS, strike_count: 15, strikes_returned: 15, lot_size: 250,
};
const EXPIRIES = { symbol: "TVSMOTOR", as_of: AS_OF, expiries: [{ expiry: EXPIRY, days_to_expiry: 27 }, { expiry: "2026-12-29", days_to_expiry: 62 }, { expiry: "2027-01-26", days_to_expiry: 90 }], count: 3 };
const CONSOLIDATED = {
  symbol: "TVSMOTOR", as_of: AS_OF, expiries: EXPIRIES.expiries.map((e) => e.expiry), spot: 1203,
  strikes: STRIKES.map((k) => ({ strike: k, call: { oi: 500_000, change_in_oi: 20_000, volume: 9_000 }, put: { oi: 400_000, change_in_oi: -10_000, volume: 8_000 } })),
  summary: { atm_strike: 1200, pcr: 0.8, max_pain: 1200, put_wall: { strike: 1150, oi: 400_000 }, call_wall: { strike: 1250, oi: 500_000 }, total_call_oi: 7_500_000, total_put_oi: 6_000_000, total_call_oi_change: 300_000, total_put_oi_change: -150_000 },
  basis: "summed over the listed expiries", read_only: true,
};

// ── logic (Node; no browser) ──────────────────────────────────────────────────────────────────────────────────────────
const toSide = (s: Side) => ({ oi: s.oi, oiChange: s.change_in_oi, volume: s.volume, close: s.close, iv: s.iv, delta: s.delta, gamma: s.gamma, theta: s.theta, vega: s.vega });
const ANALYSIS: AnalysisChain = {
  slot: "current", expiry: EXPIRY, expiries: [EXPIRY], asOf: AS_OF, spot: 1203, atm: 1200, lotSize: 250, daysToExpiry: 27, pcr: 0.9, maxPain: 1200,
  callWall: { strike: 1250, oi: 300_000 }, putWall: { strike: 1150, oi: 200_000 }, totalCallOi: null, totalPutOi: null, totalCallOiChange: null, totalPutOiChange: null,
  atmIv: 22.5, expectedMove: 92, expectedMovePct: 7.65,
  rows: CHAIN_ROWS.map((r): StrikeRow => ({ strike: r.strike, call: toSide(r.call), put: toSide(r.put) })),
  tradable: true, source: `NSE F&O bhavcopy, end of day ${AS_OF}`,
};
const cand = (p: StrategyPlan, id: string) => p.candidates.find((c) => c.id === id) as Candidate;

test.describe("logic: analysis/reco-data.ts (pure)", () => {
  test("OI Δ% = change / (OI − change) × 100; null when it cannot be computed", () => {
    expect(oiChangePct(300_000, 60_000)).toBeCloseTo(25, 10);
    expect(oiChangePct(200_000, -50_000)).toBeCloseTo(-20, 10);
    expect(oiChangePct(null, 10)).toBeNull();
    expect(oiChangePct(100, null)).toBeNull();
    expect(oiChangePct(50_000, 50_000)).toBeNull();               // new contract: no previous OI
    expect(oiChangePct(10, 20)).toBeNull();                       // inconsistent: previous OI below zero
  });

  test("columns per mode and width: OI | GREEKS, phone keeps OI Δ% or THETA + DELTA; the put side mirrors", () => {
    expect(callCells("oi", false)).toEqual(["oi", "oiPct"]);
    expect(callCells("oi", true)).toEqual(["oiPct"]);
    expect(callCells("greeks", false)).toEqual(["iv", "vega", "gamma", "theta", "delta"]);
    expect(callCells("greeks", true)).toEqual(["theta", "delta"]);
    expect(putCells("greeks", false)).toEqual(["delta", "theta", "gamma", "vega", "iv"]);
    expect(chainTemplate(2, false)).toBe("1fr 1fr 1fr 26px 26px 66px 26px 26px 1fr 1fr 1fr");
    expect(chainTemplate(1, true)).toBe("1fr 1fr 26px 26px 52px 26px 26px 1fr 1fr");
  });

  test("a live quote counts only when its contract last traded today (IST)", () => {
    expect(kiteTradeDay("2026-10-29 10:15:02")).toBe("2026-10-29");               // Kite: IST without a zone
    expect(kiteTradeDay("2026-10-28T22:00:00+00:00")).toBe("2026-10-29");          // 03:30 IST on the 29th
    expect(kiteTradeDay("nonsense")).toBeNull();
    expect(liveQuoteCounts({ last_price: 51.2, last_trade_time: "2026-10-29 10:15:02" }, "2026-10-29")).toBe(true);
    expect(liveQuoteCounts({ last_price: 51.2, last_trade_time: "2026-10-27 15:29:00" }, "2026-10-29")).toBe(false);
    expect(liveQuoteCounts({ last_price: 51.2, last_trade_time: "1970-01-01 05:30:00" }, "2026-10-29")).toBe(false);
    expect(liveQuoteCounts({ last_price: 51.2 }, "2026-10-29")).toBe(false);            // no trade time: not live
    const rows = ANALYSIS.rows.filter((r) => r.strike === 1200 || r.strike === 1250);
    const req = liveLegsFor("TVSMOTOR", EXPIRY, rows);
    expect(req.legs).toHaveLength(4);
    expect(req.legs[0]).toEqual({ underlying: "TVSMOTOR", kind: "option", expiry: EXPIRY, strike: 1200, option_type: "call" });
    const answer = { available: true, unresolved: [], quotes: {
      0: { key: "NFO:A", last_price: 55.5, last_trade_time: "2026-10-29 10:01:00" },
      1: { key: "NFO:B", last_price: 37, last_trade_time: "2026-10-28 15:29:00" },
    } } as never;
    const by = liveByContract(req.at, answer, "2026-10-29");
    expect([...by.keys()]).toEqual(["CE|1200"]);
    expect(liveByContract(req.at, { available: false, quotes: {}, unresolved: [] }, "2026-10-29").size).toBe(0);
    expect(liveLegsFor("TVSMOTOR", null, rows).legs).toEqual([]);                   // Consolidated: no expiry, no quotes
  });

  test("B / S are off with the reason: Consolidated, no contract, no lot size, no close, not traded", () => {
    const r = (k: number) => ANALYSIS.rows.find((x) => x.strike === k)!;
    expect(pickBlock({ chain: ANALYSIS, side: r(1200).call, kind: "CE", strike: 1200, price: 52, live: false })).toBeNull();
    expect(pickBlock({ chain: { ...ANALYSIS, tradable: false, expiry: null }, side: r(1200).call, kind: "CE", strike: 1200, price: null, live: false }))
      .toBe("Pick an expiry to trade: legs need one expiry.");
    expect(pickBlock({ chain: ANALYSIS, side: null, kind: "PE", strike: 1200, price: null, live: false })).toBe("No 1200 PE contract is listed in this expiry.");
    expect(pickBlock({ chain: { ...ANALYSIS, lotSize: null }, side: r(1200).call, kind: "CE", strike: 1200, price: 52, live: false })).toMatch(/no lot size/);
    expect(pickBlock({ chain: ANALYSIS, side: r(1500).put, kind: "PE", strike: 1500, price: null, live: false })).toBe("There is no close for the 1500 PE on 2026-10-28, so there is no price to pick it at.");
    expect(pickBlock({ chain: ANALYSIS, side: r(1450).call, kind: "CE", strike: 1450, price: 4, live: false })).toBe("The 1450 CE did not trade on 2026-10-28: its close is not a market price.");
    expect(pickBlock({ chain: ANALYSIS, side: r(1450).call, kind: "CE", strike: 1450, price: 4.5, live: true })).toBeNull();   // traded today (live)
  });

  test("the engine's order: viable by net reward : risk, preferred first; the cards are the first 3 actionable", () => {
    const p = clone(PLAN_ALL);
    expect(p.preferred).toBe("options:bull_call_spread");
    p.candidates.reverse();                                                          // the order the route sends does not matter
    expect(engineOrder(p).map((c) => c.id)).toEqual(["options:bull_call_spread", "cash:breakout_continuation", "futures:long_buildup_continuation"]);
    expect(topActionable(p).map((c) => c.id)).toEqual(["options:bull_call_spread", "cash:breakout_continuation", "futures:long_buildup_continuation"]);
    // a viable candidate priced off a delayed chain is not actionable: never a card
    const stale = clone(PLAN_ALL);
    cand(stale, "options:bull_call_spread").actionable = false;
    expect(topActionable(stale).map((c) => c.id)).toEqual(["cash:breakout_continuation", "futures:long_buildup_continuation"]);
    expect(notQualifying(stale, topActionable(stale))).toBe(`Not qualifying: ${cand(PLAN_ALL, "options:long_call").label}: Reward : risk -0.04 at the base level is below the minimum 0.5; ${cand(PLAN_ALL, "options:bull_call_spread").label}: the option chain is delayed, so its strikes are not current.`);
    expect(topActionable(PLAN_NOTRADE)).toEqual([]);
    expect(noTradeReasons(PLAN_NOTRADE).length).toBeGreaterThan(0);
  });

  test("tags, legs line and the reason in plain words", () => {
    const [a, b, c] = topActionable(PLAN_ALL);
    expect([cardTag(0, a), cardTag(1, b), cardTag(2, c)]).toEqual(["PRIMARY", "ALTERNATE", "DIRECTIONAL"]);
    expect(cardTag(2, { segment: "options" })).toBe("ALTERNATE");
    expect(legsText(a.legs)).toBe("BUY 1200 CE · SELL 1250 CE");
    expect(legsText(b.legs)).toBe("BUY SHARES");
    expect(legsText(c.legs)).toBe("BUY FUT");
    expect(cardWhy(a)).toBe("Long the ATM 1200, short 1250: the call wall, inside the expected move, so the short leg sits where the market has the most open interest.");
    expect(cardWhy(c)).toBe("Futures OI build-up is long buildup, confirmed by the cash market (a heuristic, not proof of intent). Contract 2026-10-27, lot size 250, basis 3.0.");
    expect(cardExpiry(a)).toBe(EXPIRY);
    expect(cardExpiry(b)).toBeNull();
  });

  test("figures are the route's: payoff block and comparison row; Unlimited only where the payoff says so", () => {
    const spread = cand(PLAN_ALL, "options:bull_call_spread");
    const f = cardFigures(PLAN_ALL, spread);
    expect(f.maxProfit).toEqual({ kind: "value", value: spread.payoff!.expiry!.max_profit });           // 45,000 (5 lots)
    expect(f.maxLoss).toEqual({ kind: "value", value: spread.payoff!.expiry!.max_loss });               // −17,500
    expect(f.lossLabel).toBe("MAX LOSS");
    expect(f.rr).toEqual({ value: spread.risk_reward!.net, basis: "after costs" });
    expect(f.breakevens).toEqual(spread.payoff!.expiry!.breakevens);
    expect(f.premium).toEqual({ kind: "debit", value: Math.abs(spread.payoff!.expiry!.net_premium!), optionsOnly: false });
    expect(f.size).toBe("5 LOTS");
    const cash = cand(PLAN_ALL, "cash:breakout_continuation");
    const g = cardFigures(PLAN_ALL, cash);
    const alt = PLAN_ALL.alternatives.find((x) => x.id === cash.id)!;
    expect(g.maxProfit).toEqual({ kind: "unlimited" });                                                 // profit_unbounded: true
    expect(g.lossLabel).toBe("LOSS AT STOP");
    expect(g.maxLoss).toEqual({ kind: "value", value: alt.max_loss });
    expect(g.lossBasis).toBe(alt.max_loss_basis);
    expect(g.premium).toEqual({ kind: "entry", value: cash.legs[0].entry_price });
    expect(g.size).toBe(`${cash.legs[0].quantity} SHARES`);
  });

  test("ADD TO BASKET legs: the candidate's own legs and prices; the chain close only for a leg with no price", () => {
    const spread = cand(PLAN_ALL, "options:bull_call_spread");
    const out = candidateLegs(spread, ANALYSIS);
    expect(out.problem).toBeNull();
    expect(out.chainPriced).toBe(false);
    expect(out.legs).toEqual([
      { kind: "CE", side: "B", qty: 5, strike: 1200, expiry: EXPIRY, entry: 52, priceSource: "NSE F&O bhavcopy close, 2026-10-19", lotSize: 250 },
      { kind: "CE", side: "S", qty: 5, strike: 1250, expiry: EXPIRY, entry: 38, priceSource: "NSE F&O bhavcopy close, 2026-10-19", lotSize: 250 },
    ]);
    const unpriced = clone(spread);
    unpriced.legs[1].entry_price = 0;
    const fb = candidateLegs(unpriced, ANALYSIS);
    expect(fb.chainPriced).toBe(true);
    expect(fb.legs[1]).toMatchObject({ entry: 38, priceSource: "NSE F&O bhavcopy close, 2026-10-28 (priced at the chain close)" });
    expect(candidateLegs(unpriced, { ...ANALYSIS, expiry: "2026-12-29" }).problem).toBe("The 1250 CE leg has no price, so the strategy cannot be added.");
    expect(candidateLegs(unpriced, null).problem).toBe("The 1250 CE leg has no price, so the strategy cannot be added.");
    const cashLegs = candidateLegs(cand(PLAN_ALL, "cash:breakout_continuation"), null);
    expect(cashLegs.legs).toEqual([{ kind: "CASH", side: "B", qty: 500, strike: null, expiry: null, entry: 1200, priceSource: "nidp.prices_eod_adjusted close, 2026-10-19", lotSize: 1 }]);
  });
});

// ── page (mocked APIs, production build) ──────────────────────────────────────────────────────────────────────────────
const DESK = "/v5/app/trader/desk";
const URL_TVS = `${DESK}?tab=trade&view=chart&sub=live&sym=TVSMOTOR`;
const SLOW = { timeout: 15_000 };
const AFTER_HOURS = new Date("2026-10-29T20:00:00+05:30");
const IN_HOURS = new Date("2026-10-29T10:30:00+05:30");

// MOCK — not real data: 60 daily bars around 1,200 (no Kite session), READY signal of 28 Oct, long levels.
const DAYS = Array.from({ length: 60 }, (_, i) => new Date(Date.UTC(2026, 7, 3 + Math.floor(i * 7 / 5))).toISOString().slice(0, 10));
const DAILY = DAYS.map((d, i) => [d, 1180 + i * 0.3, 1186 + i * 0.3, 1176 + i * 0.3, 1182 + i * 0.3, 900_000] as [string, number, number, number, number, number]);
const LIVE = {
  symbol: "TVSMOTOR", as_of: "2026-10-29T20:00:00+05:30",
  timeframe: { interval: "1d", label: "DAILY", source: "nidp.prices_eod_adjusted (end of day)", adjusted: true, reason: "token_expired",
    reason_text: "Kite login needed for 15m candles: the platform Kite session expired.", live_merged: false, note: "Daily bars, split and bonus adjusted." },
  bars: DAILY, ema20: DAILY.map((_, i) => (i < 19 ? null : 1190)), rvol: DAILY.map((_, i) => (i < 20 ? null : 1.0)),
  last: { price: 1203, at: DAYS[59], bar_complete: true },
  levels: { source: "signal", plan_id: null, entry: 1210, stop: 1170, targets: [{ name: "T1", price: 1270, primary: true }], rule: "break_above", valid_for_sessions: null,
    reference_close: 1203, direction: "long", signal_date: "2026-10-28", invalidation: null },
  signal: { signal_date: "2026-10-28", stage: "EARLY_BREAKOUT", kind: "READY", revision: 1, engine_version: "positional.v1.0", computed_at: null },
  signals_error: null, markers: [], markers_error: null, conditions: [], evaluated_at_bar: DAYS[59], valid_until: null, sessions_left: null, holidays_checked: true,
  paper_engine: "MOCK", read_only: true, sent_to_broker: false,
};
const OI = {
  symbol: "TVSMOTOR", mode: "end_of_day", interval: "1d", window: 1, sessions: 1, source: "NSE F&O bhavcopy (nidp.fno_bhavcopy), end of day", snapshot_at: AS_OF, last_bar_at: AS_OF,
  contracts: [{ slot: "current", expiry: EXPIRY, tradingsymbol: null, lot_size: 250, windows: [], daily_bars: [], daily_windows: [] }],
  consolidated: { slot: "consolidated", expiries: [EXPIRY], windows: [], basis: "summed", daily_bars: [], daily_windows: [] },
  missing_slots: [], missing_note: null, kite_reason: "token_expired", note: "MOCK", read_only: true,
};

interface Seen { plans: Array<Record<string, unknown>>; quoteBodies: Array<{ legs: Array<Record<string, unknown>> }> }
async function setup(page: Page, o: { phone?: boolean; plan?: (n: number) => { status: number; body: unknown }; at?: Date; quotes?: (legs: Array<Record<string, unknown>>) => unknown } = {}): Promise<Seen> {
  const seen: Seen = { plans: [], quoteBodies: [] };
  await page.clock.setFixedTime(o.at ?? AFTER_HOURS);
  if (o.phone) await page.setViewportSize({ width: 390, height: 844 });
  await page.route("**/api/**", (r) => json(r, { detail: "MOCK: not mocked in this spec" }, 404));
  await mockApi(page, "populated");
  await mockSingleRoute(page, "**/api/markets/home", "markets-home.json");
  await page.route("**/api/chat/sessions", (r) => json(r, []));
  await page.route("**/api/desk/paper-trades*", (r) => json(r, { as_of: AS_OF, status: "all", trades: [], summary: { open: 0, closed: 0 } }));
  await page.route("**/api/live/**", (r) => json(r, { available: false, reason: "MOCK: feed off", quotes: {}, unresolved: [], mode: "expired", session: "closed", stale: true }));
  await page.route("**/api/live/fno-quotes", (r) => {
    const body = r.request().postDataJSON() as { legs: Array<Record<string, unknown>> };
    seen.quoteBodies.push(body);
    return json(r, o.quotes ? o.quotes(body.legs) : { available: false, reason: "MOCK: feed off", quotes: {}, unresolved: [] });
  });
  await page.route("**/api/desk/live-chart/*", (r) => json(r, LIVE));
  await page.route("**/api/fno/*/futures/oi-buildup*", (r) => json(r, OI));
  await page.route("**/api/fno/*/expiries", (r) => json(r, EXPIRIES));
  await page.route((u) => /\/api\/fno\/[^/]+\/chain$/.test(u.pathname), (r) => json(r, CHAIN_BODY));
  await page.route("**/api/fno/*/chain/consolidated*", (r) => json(r, CONSOLIDATED));
  await page.route("**/api/fno/*/iv-history*", (r) => json(r, { symbol: "TVSMOTOR", bucket: "near_month", sessions: 0, min_sessions: 252, last_session: null, iv_percentile: null, iv_rank: null, reason: "MOCK: no IV history is recorded.", series: [] }));
  await page.route("**/api/desk/chart-events/*", (r) => json(r, { symbol: "TVSMOTOR", from: "2026-08-01", to: AS_OF, events: [], sources: {}, fii_dii_rule: null }));
  let n = 0;
  await page.route("**/api/desk/strategy/plan", (r) => {
    seen.plans.push(r.request().postDataJSON());
    n += 1;
    const a = o.plan ? o.plan(n) : { status: 200, body: relabel(PLAN_ALL) };
    return json(r, a.body, a.status);
  });
  return seen;
}

const chainRow = (page: Page, k: number) => page.locator(`[data-testid="ca-chain-row"][data-strike="${k}"]`);
async function toReco(page: Page) {
  await page.getByTestId("ca-reco").scrollIntoViewIfNeeded();
}

test.describe("page: Chart Analysis › option chain and strategy cards (MOCK — not real data)", () => {
  test.fixme(!PAGE_LANDED, "the page imports BasketPanel and StrategyPanel, which are not on this branch yet");

  test("U3 / U5 chain: 13 rows around the ATM, OI and OI Δ%, GREEKS toggle, strike click selects", async ({ page }) => {
    await setup(page);
    await page.goto(URL_TVS);
    await expect(page.getByTestId("ca-chain")).toBeVisible(SLOW);
    await expect(page.getByTestId("ca-chain-title")).toHaveText(/Option chain · Current month · 24 Nov 2026/i);
    await expect(page.getByTestId("ca-chain-row")).toHaveCount(13);
    await expect(page.locator('[data-testid="ca-chain-row"]').first()).toHaveAttribute("data-strike", "900");
    await expect(chainRow(page, 1200)).toHaveAttribute("data-atm", "true");
    await expect(chainRow(page, 1250).locator('[data-col="call-oiPct"]')).toHaveText("+25.0%");
    await expect(chainRow(page, 1150).locator('[data-col="put-oiPct"]')).toHaveText("−20.0%");
    await expect(chainRow(page, 1250).locator('[data-col="call-oi"]')).toHaveText("3.00 L");
    await expect(chainRow(page, 1200).getByTestId("ca-chain-ltp-ce")).toHaveText("52.00");
    await expect(chainRow(page, 1200).getByTestId("ca-chain-ltp-ce")).toHaveAttribute("data-src", "close");
    await expect(page.getByTestId("ca-chain-source")).toContainText("Prices: NSE F&O bhavcopy close, 28 Oct 2026");
    await page.getByTestId("ca-chain-mode-greeks").click();
    await expect(page.getByTestId("ca-chain")).toHaveAttribute("data-mode", "greeks");
    await expect(chainRow(page, 1200).locator('[data-col="call-gamma"]')).toHaveText("0.0032");
    await expect(chainRow(page, 1200).locator('[data-col="call-iv"]')).toHaveText("22.5%");
    await expect(page.getByTestId("ca-chain-header").getByRole("columnheader")).toHaveText(["IV", "VEGA", "GAMMA", "THETA", "DELTA", "LTP", "B · S", "STRIKE", "B · S", "LTP", "DELTA", "THETA", "GAMMA", "VEGA", "IV"]);
    await chainRow(page, 1300).getByTestId("ca-chain-strike").click();
    await expect(chainRow(page, 1300)).toHaveAttribute("data-selected", "true");
  });

  test("U5 B adds a buy leg, B again removes it, S switches the side; no price or no trade keeps B / S off; a fifth leg is refused", async ({ page }) => {
    await setup(page);
    await page.goto(URL_TVS);
    const b = chainRow(page, 1200).getByTestId("ca-chain-b-ce");
    const s = chainRow(page, 1200).getByTestId("ca-chain-s-ce");
    await expect(b).toBeEnabled(SLOW);
    await b.click();
    await expect(b).toHaveAttribute("aria-pressed", "true");
    await b.click();
    await expect(b).toHaveAttribute("aria-pressed", "false");
    await b.click();
    await s.click();
    await expect(s).toHaveAttribute("aria-pressed", "true");
    await expect(b).toHaveAttribute("aria-pressed", "false");
    await expect(chainRow(page, 1450).getByTestId("ca-chain-b-ce")).toBeDisabled();
    await expect(chainRow(page, 1450).getByTestId("ca-chain-b-ce")).toHaveAttribute("title", "The 1450 CE did not trade on 2026-10-28: its close is not a market price.");
    await expect(chainRow(page, 1500).getByTestId("ca-chain-s-pe")).toBeDisabled();
    for (const k of [1250, 1300, 1350]) await chainRow(page, k).getByTestId("ca-chain-b-pe").click();
    await chainRow(page, 1100).getByTestId("ca-chain-b-pe").click();                  // the fifth leg
    await expect(page.getByTestId("ca-chain-refused")).toHaveText("The paper engine takes at most 4 legs.");
    await expect(chainRow(page, 1100).getByTestId("ca-chain-b-pe")).toHaveAttribute("aria-pressed", "false");
  });

  test("live quotes in NSE hours: only contracts that traded today replace the close, labelled", async ({ page }) => {
    const seen = await setup(page, {
      at: IN_HOURS,
      quotes: (legs) => {
        const quotes: Record<string, unknown> = {};
        legs.forEach((l, i) => {
          if (l.strike === 1200 && l.option_type === "call") quotes[i] = { key: "NFO:TVSMOTOR26NOV1200CE", last_price: 55.5, last_trade_time: "2026-10-29 10:29:41" };
          if (l.strike === 1200 && l.option_type === "put") quotes[i] = { key: "NFO:TVSMOTOR26NOV1200PE", last_price: 41, last_trade_time: "2026-10-27 15:10:00" };
        });
        return { available: true, reason: null, quotes, unresolved: [], as_of: "2026-10-29T05:00:00+00:00", source: "kite REST quote", read_only: true };
      },
    });
    await page.goto(URL_TVS);
    const ce = chainRow(page, 1200).getByTestId("ca-chain-ltp-ce");
    await expect(ce).toHaveAttribute("data-src", "live", SLOW);
    await expect(ce).toContainText("55.50");
    await expect(chainRow(page, 1200).getByTestId("ca-chain-ltp-pe")).toHaveAttribute("data-src", "close");   // last traded 27 Oct
    await expect(page.getByTestId("ca-chain-source")).toContainText("Kite quote read at 10:30 IST where the contract traded today (1 of 26)");
    expect(seen.quoteBodies[0].legs).toHaveLength(26);
    expect(seen.quoteBodies[0].legs[0]).toEqual({ underlying: "TVSMOTOR", kind: "option", expiry: EXPIRY, strike: 900, option_type: "call" });
  });

  test("U4 Consolidated: summed OI, OI mode only, B / S off with the reason", async ({ page }) => {
    await setup(page);
    await page.goto(URL_TVS);
    await expect(page.getByTestId("ca-chain")).toBeVisible(SLOW);
    await page.getByTestId("ca-expiry-consolidated").click();
    await expect(page.getByTestId("ca-chain")).toHaveAttribute("data-slot", "consolidated");
    await expect(page.getByTestId("ca-chain-title")).toHaveText(/Consolidated · 3 expiries/i);
    await expect(chainRow(page, 1200).locator('[data-col="call-oi"]')).toHaveText("5.00 L");
    await expect(page.getByTestId("ca-chain-mode-greeks")).toBeDisabled();
    await expect(chainRow(page, 1200).getByTestId("ca-chain-b-ce")).toBeDisabled();
    await expect(page.getByTestId("ca-chain-untradable")).toHaveText("Pick an expiry to trade: legs need one expiry.");
    await expect(chainRow(page, 1200).getByTestId("ca-chain-ltp-ce")).toHaveText("—");
  });

  test("U6 cards: the engine's first three in its order, the route's figures, ADD TO BASKET writes the candidate's legs", async ({ page }) => {
    const seen = await setup(page);
    await page.goto(URL_TVS);
    await toReco(page);
    await expect(page.getByTestId("ca-reco-card")).toHaveCount(3, SLOW);
    expect(seen.plans).toEqual([{ underlying: "TVSMOTOR", direction: "bullish" }]);
    await expect(page.getByTestId("ca-reco-title")).toHaveText(/Strategies that fit · TVSMOTOR · 24 Nov 2026/i);
    await expect(page.getByTestId("ca-reco-direction")).toHaveText(/^Bullish view from the READY signal of 28 Oct$/i);      // directionWhy is the page's text, shown as given
    await expect(page.getByTestId("ca-reco-name")).toHaveText([cand(PLAN_ALL, "options:bull_call_spread").label, cand(PLAN_ALL, "cash:breakout_continuation").label, cand(PLAN_ALL, "futures:long_buildup_continuation").label]);
    await expect(page.getByTestId("ca-reco-tag")).toHaveText(["PRIMARY", "ALTERNATE", "DIRECTIONAL"]);
    const first = page.getByTestId("ca-reco-card").first();
    await expect(first.getByTestId("ca-reco-legs")).toHaveText("BUY 1200 CE · SELL 1250 CE");
    await expect(first.getByTestId("ca-reco-max-profit")).toContainText("₹45,000.00");
    await expect(first.getByTestId("ca-reco-max-loss")).toContainText("₹17,500.00");
    await expect(first.getByTestId("ca-reco-rr")).toContainText("2.54 : 1");
    await expect(first.getByTestId("ca-reco-breakeven")).toContainText("1,214.00");
    await expect(first.getByTestId("ca-reco-premium")).toHaveText("NET DEBIT ₹17,500.00 · 5 LOTS");
    await expect(page.getByTestId("ca-reco-card").nth(1).getByTestId("ca-reco-max-profit")).toContainText("Unlimited");
    await expect(page.getByTestId("ca-reco-foot")).toContainText("ordered by net reward : risk");
    await first.getByTestId("ca-reco-add").click();
    await expect(chainRow(page, 1200).getByTestId("ca-chain-b-ce")).toHaveAttribute("aria-pressed", "true");
    await expect(chainRow(page, 1250).getByTestId("ca-chain-s-ce")).toHaveAttribute("aria-pressed", "true");
  });

  test("U6 fewer than three: what qualifies plus one line why; none: no card, the engine's reasons; error: words and Retry", async ({ page }) => {
    const fewer = relabel(PLAN_ALL);
    for (const id of ["cash:breakout_continuation", "futures:long_buildup_continuation"]) {
      const c = cand(fewer, id);
      c.status = "no_trade"; c.actionable = false; c.reasons = [{ code: "liquidity", message: "Average traded value 6 Cr a day is below the 10 Cr liquidity gate." }];
    }
    const plans = [{ status: 502, body: { detail: "upstream_unavailable" } }, { status: 200, body: fewer }];
    await setup(page, { plan: (n) => plans[Math.min(n, plans.length) - 1] });
    await page.goto(URL_TVS);
    await toReco(page);
    await expect(page.getByTestId("ca-reco-error")).toContainText("The strategy engine did not answer", SLOW);
    await page.getByTestId("ca-reco-retry").click();
    await expect(page.getByTestId("ca-reco-card")).toHaveCount(1, SLOW);
    await expect(page.getByTestId("ca-reco-fewer")).toContainText("Only 1 strategy fits. Not qualifying:");
    await expect(page.getByTestId("ca-reco-fewer")).toContainText("below the 10 Cr liquidity gate");
  });

  test("U6 nothing qualifies: no card, no tag, no ADD; the engine's reasons", async ({ page }) => {
    await setup(page, { plan: () => ({ status: 200, body: relabel(PLAN_NOTRADE) }) });
    await page.goto(URL_TVS);
    await toReco(page);
    await expect(page.getByTestId("ca-reco-none")).toContainText("No strategy fits a bullish view on TVSMOTOR today.", SLOW);
    await expect(page.getByTestId("ca-reco-none-reason").first()).toBeVisible();
    await expect(page.getByTestId("ca-reco-card")).toHaveCount(0);
    await expect(page.getByTestId("ca-reco-tag")).toHaveCount(0);
  });

  test("U6 a strategy with more than 4 legs is refused by the basket, said on its card", async ({ page }) => {
    const five = relabel(PLAN_ALL);
    const spread = cand(five, "options:bull_call_spread");
    spread.legs = [1100, 1150, 1200, 1250, 1300].map((k, i) => ({ ...spread.legs[0], strike: k, side: i % 2 ? "sell" : "buy" }));
    await setup(page, { plan: () => ({ status: 200, body: five }) });
    await page.goto(URL_TVS);
    await toReco(page);
    await page.getByTestId("ca-reco-card").first().getByTestId("ca-reco-add").click(SLOW);
    await expect(page.getByTestId("ca-reco-card").first().getByTestId("ca-reco-refused")).toHaveText("The paper engine takes at most 4 legs.");
  });

  test("U11 390 px: no sideways page scroll; the chain scrolls inside its box; phone columns", async ({ page }) => {
    await setup(page, { phone: true });
    await page.goto(URL_TVS);
    await expect(page.getByTestId("ca-chain")).toBeVisible(SLOW);
    await expect(page.getByTestId("ca-chain-header").getByRole("columnheader")).toHaveText(["OI Δ%", "LTP", "B · S", "STRIKE", "B · S", "LTP", "OI Δ%"]);
    await page.getByTestId("ca-chain-mode-greeks").click();
    await expect(page.getByTestId("ca-chain-header").getByRole("columnheader")).toHaveText(["THETA", "DELTA", "LTP", "B · S", "STRIKE", "B · S", "LTP", "DELTA", "THETA"]);
    await toReco(page);
    await expect(page.getByTestId("ca-reco-card")).toHaveCount(3, SLOW);
    const o = await page.evaluate(() => {
      const sc = document.querySelector('[data-testid="copilot-scroll"]') as HTMLElement | null;
      const box = document.querySelector('[data-testid="ca-chain-scroll"]') as HTMLElement;
      return { doc: document.documentElement.scrollWidth - window.innerWidth, scroll: sc ? sc.scrollWidth - sc.clientWidth : 0, inner: box.scrollWidth - box.clientWidth };
    });
    expect(o.doc).toBeLessThanOrEqual(1);
    expect(o.scroll).toBeLessThanOrEqual(1);
    expect(o.inner).toBeGreaterThan(0);
  });
});
