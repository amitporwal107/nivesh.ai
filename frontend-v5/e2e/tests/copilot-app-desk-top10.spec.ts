/**
 * Smart trading desk — the Scanner's Top 10 ideas, market pulse, the lab's focus panel and URL state, Market
 * Intelligence's URL state, and the breadcrumb trail. Cases F-1 … F-35 of test_reports/desk_scanner_top10_TESTCASES.md.
 *
 * MOCK — not real data, except where said: every /api response is an inline payload in the shape the real route returns
 * (the route is named beside each). The F&O board starts from `desk-strategy-top.json`, a REAL staging capture of
 * POST /api/desk/strategy/top (2026-10-21); for these cases its two stock underlyings are renamed to the candidates
 * fixture's SB1 and LB2 (so the lab's focus can be checked against a real candidates payload shape), the board is marked
 * `distinct`, and one alternative is added to BANKNIFTY. Expected values are worked out from the payloads here, not
 * copied from the screen. Mocked APIs, production build — see pw.copilot-app.config.ts.
 *
 * L-1 … L-4 (test_reports/fno_idea_paper_trade_TESTCASES.md F-7, F-8): the provisional levels on the rows and the F&O
 * paper-trade body, compared with the shared contract `contract-fno-idea-paper-trade.json` that
 * backend/tests/test_fno_idea_paper_trade_contract.py sends through the real route. The levels reply for the contract
 * idea is the real engine's answer (`desk-strategy-levels-banknifty.json`); every other idea gets a MOCK not-valid answer.
 */
import { test, expect, type Page, type Route } from "@playwright/test";
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";
import { isDeepStrictEqual } from "util";
import { mockApi, mockSingleRoute } from "../helpers/api-mock";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const load = (name: string) => JSON.parse(fs.readFileSync(path.join(__dirname, "..", "fixtures", name), "utf-8"));
const DESK = "/v5/app/trader/desk";
const SCANNER = `${DESK}?tab=scanner`;
/** Both board routes and the filings feed answer in a few seconds on staging; mocked they are instant. */
const SLOW = { timeout: 15_000 };

const json = (route: Route, body: unknown, status = 200) =>
  route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });

// ── F&O board: POST /api/desk/strategy/top, distinct (backend/services/strategy_plan/regime_fit.py) ──

const CAPTURED = load("desk-strategy-top.json");
const CONTRACT = load("contract-fno-idea-paper-trade.json");
const LEVELS = load(CONTRACT.levels_reply_fixture);
const NOT_VALID = { valid: false, version: "strategy-levels-v2", problems: [{ code: "mock", message: "MOCK: not worked out in this test" }], sent_to_broker: false };
function topBoard() {
  const b = JSON.parse(JSON.stringify(CAPTURED));
  b.limit = 10;
  b.distinct = true;
  const rename = (from: string, to: string) => {
    const i = b.classes.stock_fno.ideas.find((x: { underlying: string }) => x.underlying === from);
    i.underlying = to;
  };
  rename("MPHASIS", "SB1");    // fit 100.0, reward:risk 2.15
  rename("ICICIBANK", "LB2");  // fit 92.5,  reward:risk 2.32
  for (const c of ["index_options", "stock_fno"]) {
    b.classes[c].distinct = true;
    for (const i of b.classes[c].ideas) i.alternatives = [];
  }
  const bank = b.classes.index_options.ideas.find((x: { underlying: string }) => x.underlying === "BANKNIFTY");
  bank.alternatives = [{ ...bank, alternatives: undefined, rank: null, structure: "long_put", name: "Long put 55000", reward_risk: 1.01 }];
  b.classes.stock_fno.universe = { source: "the AI scanner's merged setup list, F&O-listed names only", symbols_tried: ["SB1", "LB2"],
    skipped: [{ underlying: "PREMEXPLN", reason: "not in the NSE F&O list (scan snapshot), so no chain was read" }] };
  delete b.classes.cash;
  return b;
}
const TOP = topBoard();
/** The route's order across both classes: fit, then reward : risk (regime_fit._rank_key). Worked out from TOP. */
const FNO_ORDER = ["SB1", "LB2", "BANKNIFTY", "NIFTY"];

// ── stock board: POST /api/desk/strategy/ideas (services/strategy_plan/ideas.build_ideas) ──

const counts = { supports: 0, conflicts: 0, neutral: 0, unavailable: 0 };
const strat = (o: Record<string, unknown>) => ({
  legs_text: "", max_loss: null, max_loss_basis: null, capital_at_risk: null, max_profit: null, profit_unbounded: false, breakeven: [],
  reward_risk_net: null, reward_risk_gross: null, actionable: false, liquidity_flags: [], why: null, flags: [], reasons: [],
  sizing: { status: null, quantity: null, lots: null, binding: null, unit: null, risk_budget_inr: null, risk_at_stop_inr: null, deployed_inr: null, missing: [] }, ...o,
});
const scanner = (o: Record<string, unknown>) => ({ bucket: "breakout_confirmed", status: "confirmed", score: 86, close: 1200, close_date: "2026-10-19", entry: 1200, stop: 1160, target: 1280, reason: "MOCK", horizon_days: 10, liquidity_cr: 812.4, atr_pct: 1.67, ...o });
const PLAN_INPUTS = { underlying: "ICICIBANK", direction: "bullish", instrument: "all", capital: 1000000, risk_budget_inr: 10000 };
const ICICI = {
  rank: 1, symbol: "ICICIBANK", name: "ICICI Bank Ltd", scanner: scanner({}), direction: "bullish", fno_eligible: true, plan_id: "p1", plan_status: "plan",
  status_reasons: [], would_change_if: [], plan_inputs: PLAN_INPUTS, evidence_summary: { technical: counts }, oi_view: null,
  preferred: "options:bull_call_spread",
  strategies: [
    strat({ id: "cash:breakout_continuation", segment: "cash", family: "breakout_continuation", label: "Buy shares on the breakout", status: "candidate", legs_text: "Buy 208 shares at 1,200.00", max_loss: -8320, reward_risk_net: 1.9,
      sizing: { status: "complete", quantity: 208, lots: null, binding: "max_allocation", unit: "shares", risk_budget_inr: 10000, risk_at_stop_inr: 8320, deployed_inr: 249600, missing: [] } }),
    strat({ id: "options:bull_call_spread", segment: "options", family: "bull_call_spread", label: "Bull call spread 1200/1250", status: "candidate", legs_text: "Buy 1,200 call at 52.00; sell 1,250 call at 38.00", max_loss: -7000, reward_risk_net: 2.4 }),
  ],
};
const TATA = {
  rank: 2, symbol: "TATASTEEL", name: "Tata Steel Ltd", scanner: scanner({ bucket: "pre_breakout", status: "awaiting", score: 74, close: 158, entry: 160, stop: 152, target: 176 }),
  direction: "bullish", fno_eligible: true, plan_id: "p2", plan_status: "wait",
  status_reasons: [{ code: "not_confirmed", message: "Price has not closed above the 160.00 trigger yet." }], would_change_if: [],
  plan_inputs: { ...PLAN_INPUTS, underlying: "TATASTEEL" }, evidence_summary: {}, oi_view: null, preferred: null, strategies: [],
};
const AARTI = {
  rank: 3, symbol: "AARTIDRUGS", name: null, scanner: scanner({ bucket: "trend_continuation", score: 66, close: 410, entry: 410, stop: 390, target: 450 }),
  direction: "bullish", fno_eligible: false, plan_id: "p3", plan_status: "plan", status_reasons: [], would_change_if: [],
  plan_inputs: { ...PLAN_INPUTS, underlying: "AARTIDRUGS" }, evidence_summary: {}, oi_view: null, preferred: "cash:trend_pullback",
  strategies: [strat({ id: "cash:trend_pullback", segment: "cash", family: "trend_pullback", label: "Buy the pullback", status: "candidate", legs_text: "Buy 300 shares at 410.00", max_loss: -6000, reward_risk_net: 1.9 })],
};
const IDEAS = {
  generated_at: "2026-10-20T05:00:00+00:00", data_as_of: { mode: "end_of_day", scanner_watchlist: "2026-10-19", scanner_picks: "2026-10-19", scan_eligibility: "2026-10-19", price: "2026-10-19", fno: "2026-10-19" },
  caveats: [], rules_version: "strategy-rules-v2", calculation_version: "payoff-v1", sent_to_broker: false,
  ranking_note: "Ranked by the scanner's rules-based score. It is not a probability of profit.",
  selection: { source: "positional_watchlist", scan_date: "2026-10-19", rule: "MOCK", considered: 3, selected: 3, excluded: [], limit: 10, empty_reason: null, gate: null, source_failures: [] },
  inputs: { defaults_applied: [] }, ideas: [ICICI, TATA, AARTI],
};

// ── market pulse: the Intel feeds (backend/routes/filings.py, markets.py, markets_desk.py, circulars.py) ──

const row = (id: string, o: Record<string, unknown>) => ({
  id, ticker: null, code: null, name: null, date: "2026-10-12T10:00:00+05:30", category: "Other", impact: null, sentiment: null,
  docLabel: "Fixture filing", url: null, one: null, period: null, metric: null, hasInsights: false, exchange: "NSE", ...o,
});
const R_EARN = row("ann-001", { ticker: "TESTRES", code: "TESTRES", name: "Test Results Industries Ltd", date: "2026-10-13T09:12:00+05:30", category: "Earnings", impact: "high", sentiment: "positive", docLabel: "Financial results for the quarter ended September 2026" });
const R_ORDER = row("ann-002", { ticker: "TESTORD", code: "TESTORD", name: "Test Orders Ltd", date: "2026-10-12T15:40:00+05:30", category: "Orders", docLabel: "Bagging of an order" });
const FEED = { ok: true, total: 2, facets: {}, rows: [R_EARN, R_ORDER] };
const FLOWS = { ok: true, as_of: "2026-10-13", monthly: [], daily: [
  { date: "2026-10-13", fii_buy: 10000, fii_sell: 11000, fii_net: -1000, dii_buy: 9000, dii_sell: 8200, dii_net: 800 },
  { date: "2026-10-10", fii_buy: 10000, fii_sell: 9500, fii_net: 500, dii_buy: 9000, dii_sell: 9100, dii_net: -100 },
] };
const SECTORS = { as_of: "2026-10-13", source: "NSE index close (nidp.index_eod)", sessions: { "1d": 1, "1w": 5, "1m": 21 }, sectors: [
  { index: "Nifty IT", sector: "IT", date: "2026-10-13", close: 35210.5, ret_1d_pct: 1.42, ret_1w_pct: -0.8, ret_1m_pct: 3.1 },
  { index: "Nifty Bank", sector: "Banks", date: "2026-10-13", close: 56000.0, ret_1d_pct: 0.3, ret_1w_pct: 1.9, ret_1m_pct: -2.2 },
  { index: "Nifty Realty", sector: "Realty", date: "2026-10-13", close: 980.4, ret_1d_pct: -1.6, ret_1w_pct: -3.05, ret_1m_pct: 4.4 },
] };
const DEALS = { as_of: "2026-10-13", from: "2026-10-09", days: 5, kind: "all", symbol: null, source: "NSE bulk and block deals", count: 0, total: 0, rows: [] };
const CIRCULARS = { as_of: "2026-10-14", source: "SEBI RSS", count: 0, rows: [] };
// GET /api/markets/smart-money/summary (backend/routes/markets_smart_money.py)
const SUMMARY = {
  window: "1M", as_of: "2026-10-21", grain: "daily", source: "MOCK", disclosure: "MOCK",
  fii: { net_cr: -98383, previous_net_cr: null, change_cr: null, window_from: "2026-09-22", previous_from: null },
  dii: { net_cr: 198123, previous_net_cr: null, change_cr: null, window_from: "2026-09-22", previous_from: null },
  mf_rising: { as_of: "2026-10-21", pct: 46.0, count: 449, evaluated: 976, previous_as_of: null, previous_pct: null, change_pp: null, series: [] },
  fii_rising: null,
};

// ── the scanner list and the shell (backend/routes/positional.py) ──
const WATCHLIST = { as_of_date: "2026-10-19", buckets: {
  breakout_confirmed: [{ nse_symbol: "TESTBRK", sector: "Capital Goods", close_price: 510.0, trigger_price: 500.0, stop_price: 477.5, atr_pct: 2.94, why: "Fixture reason" }],
  pre_breakout: [], true_accumulation: [], trend_continuation: [] } };
const PICKS = { signal_date: "2026-10-19", count: 0, picks: [] };

/** A minimal payoff answer (POST /api/desk/strategy/payoff), enough for the chart. */
const PAYOFF = {
  valid: true, problems: [], warnings: [], calculation_version: "payoff-v1", underlying: "SB1", reference_price: 2550, as_of: "2026-10-21",
  expiry: { grid: [2400, 2500, 2550, 2600], gross: [900, 400, -100, -100], net: [880, 380, -120, -120], per_leg: [], breakevens: [2534.25],
    max_profit: 9418.75, max_loss: -4331.25, profit_unbounded: false, loss_unbounded: false, range_max_profit: 9418.75, range_max_loss: -4331.25,
    net_premium: -4331.25, scenarios: [], extremes_basis: "gross, all prices" },
  pre_expiry: null, costs: null, margin: null, margin_reason: "none", capital_at_risk: 4331, capital_at_risk_basis: "worst net loss",
  loss_can_exceed_margin: false, caveats: [], sent_to_broker: false,
};

interface Seen { ideas: unknown[]; top: unknown[]; payoff: number; paper: Array<Record<string, unknown>>; paperKeys: Array<string | undefined>; levels: Array<Record<string, any>> }

/** A UUID v4, the shape of the Idempotency-Key the desk sends (lib/observability correlationId). */
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;

async function desk(page: Page, over: { top?: { status: number; body: unknown }; ideas?: { status: number; body: unknown } } = {}): Promise<Seen> {
  const seen: Seen = { ideas: [], top: [], payoff: 0, paper: [], paperKeys: [], levels: [] };
  await mockApi(page, "populated");
  await mockSingleRoute(page, "**/api/markets/home", "markets-home.json");
  await page.route("**/api/chat/sessions", (r) => json(r, []));
  await page.route("**/api/positional/watchlist*", (r) => json(r, WATCHLIST));
  await page.route("**/api/positional/picks*", (r) => json(r, PICKS));
  await page.route("**/api/move-odds/**", (r) => json(r, { detail: "feature_not_enabled" }, 403));
  await page.route("**/api/desk/alerts*", (r) => json(r, { as_of: "2026-10-19", alerts: [] }));
  await page.route("**/api/desk/paper-trades*", (r) => {
    if (r.request().method() === "POST") {
      seen.paper.push(r.request().postDataJSON());
      seen.paperKeys.push(r.request().headers()["idempotency-key"]);
      return json(r, { trade: { id: `t${seen.paper.length}` } }, 201);
    }
    return json(r, { as_of: "2026-10-19", trades: [], summary: null });
  });
  await page.route("**/api/desk/strategy/ideas", (r) => {
    seen.ideas.push(r.request().postDataJSON());
    return over.ideas ? json(r, over.ideas.body, over.ideas.status) : json(r, IDEAS);
  });
  await page.route("**/api/desk/strategy/top", (r) => {
    seen.top.push(r.request().postDataJSON());
    return over.top ? json(r, over.top.body, over.top.status) : json(r, TOP);
  });
  await page.route("**/api/desk/strategy/payoff", (r) => { seen.payoff += 1; return json(r, PAYOFF); });
  await page.route("**/api/desk/strategy/levels", (r) => {
    const body = r.request().postDataJSON();
    seen.levels.push(body);
    return json(r, isDeepStrictEqual(body, CONTRACT.levels_request) ? LEVELS : NOT_VALID);
  });
  await page.route("**/api/filings/feed*", (r) => json(r, new URL(r.request().url()).searchParams.get("category") ? { ok: true, total: 0, facets: {}, rows: [] } : FEED));
  await page.route("**/api/markets/fii-dii*", (r) => json(r, FLOWS));
  await page.route("**/api/markets/sector-returns", (r) => json(r, SECTORS));
  await page.route("**/api/markets/deals*", (r) => json(r, DEALS));
  await page.route("**/api/markets/circulars*", (r) => json(r, CIRCULARS));
  await page.route("**/api/markets/smart-money/summary*", (r) => json(r, SUMMARY));
  await page.route("**/api/fno/scan/candidates*", (r) => json(r, load("fno-candidates.json")));
  await page.route("**/api/fno/NIFTY/expiries", (r) => json(r, load("copilot-options-expiries.json")));
  await page.route("**/api/fno/NIFTY/futures", (r) => json(r, load("copilot-options-futures.json")));
  await page.route("**/api/fno/NIFTY/chain*", (r) => json(r, load("copilot-options-chain.json")));
  return seen;
}

const params = (page: Page) => new URL(page.url()).searchParams;
// Market Overview (desk redesign step 2): one board at a time (Cash | F&O), and a row's levels, links and paper trade are in
// its drawer ("Full card ›" / "Paper trade"), which is rendered inside the row.
const showFno = (page: Page) => page.getByTestId("desk-top10-switch-fno").click(SLOW);
const openCard = (row: ReturnType<Page["getByTestId"]>, kind: "stock" | "fno" = "stock") => row.getByTestId(`desk-top10-${kind}-open`).click(SLOW);
const closeDrawer = (page: Page) => page.keyboard.press("Escape");
const trailText = async (page: Page) => (await page.getByTestId("desk-trail").innerText()).replace(/\s+/g, " ").trim();

// ── layout and the two boards ─────────────────────────────────────────────

test.describe("Scanner — Top 10 ideas", () => {
  test("F-1 the Top AI ideas, then the scanner list (the market pulse is now the Market Overview's strip and events)", async ({ page }) => {
    await desk(page);
    await page.goto(SCANNER);
    const top = page.getByTestId("desk-top10");
    const list = page.getByTestId("desk-scanner");
    await expect(top).toBeVisible();
    await expect(list).toBeVisible(SLOW);
    await expect(page.getByTestId("desk-pulse")).toHaveCount(0);
    const y = async (l: typeof top) => (await l.boundingBox())!.y;
    expect(await y(top)).toBeLessThan(await y(list));
  });

  test("F-2 the stock board asks for ten and lists each idea with the strategy that fits", async ({ page }) => {
    const seen = await desk(page);
    await page.goto(SCANNER);
    const rows = page.getByTestId("desk-top10-stocks-list").locator(":scope > li");
    await expect(rows).toHaveCount(3, SLOW);
    expect(seen.ideas[0]).toEqual({ limit: 10 });
    const icici = page.getByTestId("desk-top10-stock-ICICIBANK");
    await expect(icici).toContainText("01");
    await expect(icici).toContainText("Score 86/100");
    await expect(icici.getByTestId("desk-top10-stock-strategy")).toContainText("Bull call spread 1200/1250");
    await expect(icici.getByTestId("desk-top10-stock-strategy")).toContainText("2.40 : 1");
    // No strategy preferred: the route's own reason, not a made-up one.
    await expect(page.getByTestId("desk-top10-stock-TATASTEEL").getByTestId("desk-top10-stock-strategy")).toContainText("Price has not closed above the 160.00 trigger yet.");
  });

  test("F-3 Strategy › opens the plan in the Strategy Builder with its inputs and the strategy that fits", async ({ page }) => {
    await desk(page);
    await page.goto(SCANNER);
    await openCard(page.getByTestId("desk-top10-stock-ICICIBANK"));
    await page.getByTestId("desk-top10-stock-ICICIBANK").getByTestId("desk-top10-stock-plan").click();
    await expect(page.getByTestId("desk-panel-strategy")).toBeVisible(SLOW);
    const p = params(page);
    expect([p.get("tab"), p.get("view"), p.get("sym"), p.get("mode"), p.get("build")]).toEqual(["trade", "new", "ICICIBANK", "stock", "1"]); // was more/strategy before the 2026-10-27 redesign
    expect([p.get("cand"), p.get("src_kind"), p.get("src_date"), p.get("direction")]).toEqual(["options:bull_call_spread", "ideas", "2026-10-19", "bullish"]);
  });

  test("F-4 Option chain › only on F&O stocks, and it opens that stock's chain in the lab", async ({ page }) => {
    await desk(page);
    await page.goto(SCANNER);
    await expect(page.getByTestId("desk-top10-stock-AARTIDRUGS")).toBeVisible(SLOW);
    await openCard(page.getByTestId("desk-top10-stock-AARTIDRUGS"));
    await expect(page.getByTestId("desk-top10-stock-AARTIDRUGS").getByTestId("desk-top10-stock-chart")).toBeVisible();
    await expect(page.getByTestId("desk-top10-stock-AARTIDRUGS").getByTestId("desk-top10-stock-chain")).toHaveCount(0);
    await closeDrawer(page);
    await openCard(page.getByTestId("desk-top10-stock-ICICIBANK"));
    await page.getByTestId("desk-top10-stock-ICICIBANK").getByTestId("desk-top10-stock-chain").click();
    await expect(page.getByTestId("desk-fno")).toBeVisible(SLOW);
    expect([params(page).get("tab"), params(page).get("lab"), params(page).get("lab_sym")]).toEqual(["market", "chain", "ICICIBANK"]); // the lab's chain is in Market Desk › Smart Money since the 2026-10-27 redesign
    await expect(page.getByTestId("desk-fno-view-chain")).toHaveAttribute("aria-selected", "true");
    await expect(page.getByTestId("desk-fno-view-chain")).toContainText("ICICIBANK");
  });

  test("F-5 a stock paper trade starts at the plan's sized quantity and posts the scanner's levels", async ({ page }) => {
    const seen = await desk(page);
    await page.goto(SCANNER);
    const icici = page.getByTestId("desk-top10-stock-ICICIBANK");
    await icici.getByTestId("desk-top10-stock-paper").click();
    await expect(icici.getByTestId("desk-top10-paper-qty")).toHaveValue("208");
    await icici.getByTestId("desk-top10-paper-add").click();
    await expect(icici.getByTestId("desk-top10-paper-done")).toContainText("208 ICICIBANK");
    // paper_fills_pnl TESTCASES ER-2: the entry 1200 is the scan's close 1200 (a BREAKOUT entry), so it fills at once.
    // p2_exits_backtest TC-70: the scanner's holding window (horizon_days 10) is sent as the time exit.
    expect(seen.paper).toEqual([{ symbol: "ICICIBANK", quantity: 208, entry_price: 1200, stop_price: 1160, target_price: 1280,
      source: { kind: "scanner", bucket: "breakout_confirmed", signal_date: "2026-10-19" }, entry_rule: "at_once", max_hold_sessions: 10 }]);
    await expect(icici).toContainText("exits after 10 sessions held");
    // desk_paper_safety TESTCASES UI-1: one Idempotency-Key with the submission (a header; the body is unchanged).
    expect(seen.paperKeys).toHaveLength(1);
    expect(seen.paperKeys[0]).toMatch(UUID);
  });

  test("F-5c a pullback level below the close is sent as pullback_to, a trigger above it as break_above, and the note says how it fills", async ({ page }) => {
    // paper_fills_pnl TESTCASES ER-1, ER-2. FEDERALBNK's levels are the 26 Oct 2026 Top 10 row the study quotes (entry
    // 316.89 under a close of 344.40: an ACCUMULATION pullback level); the trigger row is MOCK — not real data.
    const federal = { ...ICICI, rank: 1, symbol: "FEDERALBNK", name: "Federal Bank Ltd",
      scanner: scanner({ bucket: "true_accumulation", stage: "ACCUMULATION", close: 344.4, close_date: "2026-10-26", entry: 316.89, stop: 312.18, target: 355.5 }) };
    const trigger = { ...ICICI, rank: 2, symbol: "TRIGGERCO", name: "Trigger Co",
      scanner: scanner({ bucket: "pre_breakout", stage: "EARLY_BREAKOUT", close: 1000, entry: 1012, stop: 980, target: 1080 }) };
    const seen = await desk(page, { ideas: { status: 200, body: { ...IDEAS, ideas: [federal, trigger] } } });
    await page.goto(SCANNER);
    const fed = page.getByTestId("desk-top10-stock-FEDERALBNK");
    await fed.getByTestId("desk-top10-stock-paper").click();
    await expect(fed.getByTestId("desk-top10-paper-rule")).toHaveText("filled when a later session pulls back to it");
    await fed.getByTestId("desk-top10-paper-add").click();
    await expect(fed.getByTestId("desk-top10-paper-done")).toBeVisible();
    await closeDrawer(page);
    const trg = page.getByTestId("desk-top10-stock-TRIGGERCO");
    await trg.getByTestId("desk-top10-stock-paper").click();
    await expect(trg.getByTestId("desk-top10-paper-rule")).toHaveAttribute("data-rule", "break_above");
    await trg.getByTestId("desk-top10-paper-add").click();
    await expect(trg.getByTestId("desk-top10-paper-done")).toBeVisible();
    expect(seen.paper.map((b) => [b.symbol, b.entry_price, b.entry_rule])).toEqual([["FEDERALBNK", 316.89, "pullback_to"], ["TRIGGERCO", 1012, "break_above"]]);
  });

  test("F-5b a retried submission reuses its key, a changed one gets a new key, and a 409 duplicate shows the route's reason", async ({ page }) => {
    // desk_paper_safety TESTCASES UI-2, UI-3. MOCK — not real data: the 503 and the 409 below are the route's shapes
    // (backend/routes/desk_trading.py _duplicate_detail), not captured answers.
    await desk(page);
    const posts: Array<{ key: string | undefined; body: Record<string, unknown> }> = [];
    const answers = [
      { status: 503, body: { detail: "upstream_unavailable" } },
      { status: 409, body: { detail: { code: "duplicate_open_trade", existing_trade_id: "t-open-1", symbol: "ICICIBANK",
        message: "You already have an open paper trade in ICICIBANK (paper trade t-open-1, opened 2026-10-20T03:03:00+00:00). Adding to a position is not supported yet; close it first." } } },
      { status: 201, body: { trade: { id: "t-new" } } },
    ];
    await page.route("**/api/desk/paper-trades*", (r) => {
      if (r.request().method() !== "POST") return json(r, { as_of: "2026-10-19", trades: [], summary: null });
      posts.push({ key: r.request().headers()["idempotency-key"], body: r.request().postDataJSON() });
      const a = answers[posts.length - 1];
      return json(r, a.body, a.status);
    });
    await page.goto(SCANNER);
    const icici = page.getByTestId("desk-top10-stock-ICICIBANK");
    await icici.getByTestId("desk-top10-stock-paper").click();
    await icici.getByTestId("desk-top10-paper-add").click();
    await expect(icici.getByTestId("desk-top10-paper-error")).toContainText("(upstream_unavailable)");
    await icici.getByTestId("desk-top10-paper-add").click();                       // the same submission, retried
    await expect(icici.getByTestId("desk-top10-paper-error")).toHaveText(
      "Not added — You already have an open paper trade in ICICIBANK (paper trade t-open-1, opened 2026-10-20T03:03:00+00:00). Adding to a position is not supported yet; close it first. (duplicate_open_trade)");
    await icici.getByTestId("desk-top10-paper-qty").fill("100");                 // a different submission
    await icici.getByTestId("desk-top10-paper-add").click();
    await expect(icici.getByTestId("desk-top10-paper-done")).toContainText("100 ICICIBANK");
    expect(posts).toHaveLength(3);
    expect(posts[0].key).toMatch(UUID);
    expect(posts[1].key).toBe(posts[0].key);
    expect(posts[2].key).toMatch(UUID);
    expect(posts[2].key).not.toBe(posts[0].key);
    expect([posts[0].body.quantity, posts[1].body.quantity, posts[2].body.quantity]).toEqual([208, 208, 100]);
  });

  test("F-6 View trades › opens the paper trades", async ({ page }) => {
    await desk(page);
    await page.goto(SCANNER);
    await openCard(page.getByTestId("desk-top10-stock-ICICIBANK"));
    await page.getByTestId("desk-top10-stock-ICICIBANK").getByTestId("desk-top10-stock-trades").click();
    // Desk redesign (2026-10-27): the paper trades are on Trade Desk › Paper trades (they were on Portfolio & Risk).
    await expect(page.getByTestId("screen-trading-desk")).toHaveAttribute("data-tab", "trade");
    await expect(page.getByTestId("screen-trading-desk")).toHaveAttribute("data-view", "paper");
  });

  test("F-7 the F&O board asks for one row per underlying and merges both classes in the route's order", async ({ page }) => {
    const seen = await desk(page);
    await page.goto(SCANNER);
    await showFno(page);
    const rows = page.getByTestId("desk-top10-fno-list").locator(":scope > li");
    await expect(rows).toHaveCount(4, SLOW);
    expect(seen.top[0]).toEqual({ limit: 10, classes: ["index_options", "stock_fno"], distinct: true });
    const order = await rows.evaluateAll((els) => els.map((e) => e.getAttribute("data-testid")!.replace("desk-top10-fno-", "")));
    expect(order).toEqual(FNO_ORDER);
    await expect(rows.nth(0)).toContainText("01");
    await expect(rows.nth(3)).toContainText("04");
    await expect(page.getByTestId("desk-top10-fno-BANKNIFTY")).toHaveAttribute("data-kind", "index");
    await expect(page.getByTestId("desk-top10-fno-SB1").getByTestId("desk-top10-fno-strategy")).toContainText("Bear put spread 2500/2550");
  });

  test("F-8 All / Indices / Stocks counts and filtering", async ({ page }) => {
    await desk(page);
    await page.goto(SCANNER);
    await showFno(page);
    await expect(page.getByTestId("desk-top10-fno-filter-all")).toContainText("All 4", SLOW);
    await expect(page.getByTestId("desk-top10-fno-filter-index")).toContainText("Indices 2");
    await expect(page.getByTestId("desk-top10-fno-filter-stock")).toContainText("Stocks 2");
    await page.getByTestId("desk-top10-fno-filter-index").click();
    const shown = await page.getByTestId("desk-top10-fno-list").locator(":scope > li").evaluateAll((els) => els.map((e) => e.getAttribute("data-kind")));
    expect(shown).toEqual(["index", "index"]);
  });

  test("F-9 the other structures on an underlying sit behind its row", async ({ page }) => {
    await desk(page);
    await page.goto(SCANNER);
    await showFno(page);
    const bank = page.getByTestId("desk-top10-fno-BANKNIFTY");
    await openCard(bank, "fno");
    await expect(bank.getByTestId("desk-top10-fno-more")).toContainText("1 other structure on BANKNIFTY", SLOW);
    await bank.getByTestId("desk-top10-fno-more").locator("summary").click();
    await expect(bank.getByTestId("desk-top10-fno-alt-BANKNIFTY-long_put")).toContainText("Long put 55000");
    await closeDrawer(page);
    await openCard(page.getByTestId("desk-top10-fno-SB1"), "fno");
    await expect(page.getByTestId("desk-top10-fno-SB1").getByTestId("desk-top10-fno-more")).not.toContainText("other structure");
  });

  test("F-10 payoff is asked for only when opened; the paper trade posts the idea as a strategy", async ({ page }) => {
    const seen = await desk(page);
    await page.goto(SCANNER);
    await showFno(page);
    const sb1 = page.getByTestId("desk-top10-fno-SB1");
    await expect(sb1).toBeVisible(SLOW);
    await sb1.getByTestId("desk-top10-fno-paper").click();
    expect(seen.payoff).toBe(0);
    await sb1.getByTestId("idea-payoff-toggle").first().click();
    await expect.poll(() => seen.payoff).toBe(1);
    await sb1.getByTestId("idea-paper-trade").first().click();
    await expect(sb1.getByTestId("idea-paper-trade").first()).toHaveText("Added to paper trades");
    expect(seen.paper).toHaveLength(1);
    expect(seen.paper[0]).toMatchObject({ kind: "strategy", underlying: "SB1", direction: "bearish", family: "bear_put_spread" });
    expect((seen.paper[0].legs as unknown[]).length).toBe(TOP.classes.stock_fno.ideas.find((i: { underlying: string }) => i.underlying === "SB1").legs.length);
  });

  test("F-15 one board failing leaves the other board and the scanner list in place", async ({ page }) => {
    await desk(page, { top: { status: 502, body: { detail: "upstream_unavailable" } } });
    await page.goto(SCANNER);
    await showFno(page);
    await expect(page.getByTestId("desk-top10-fno").getByRole("button", { name: /retry/i })).toBeVisible(SLOW);
    await page.getByTestId("desk-top10-switch-stocks").click();
    await expect(page.getByTestId("desk-top10-stocks-list").locator(":scope > li")).toHaveCount(3);
    await expect(page.getByTestId("desk-scanner")).toBeVisible();
  });

  test("F-16 / F-17 the boards say ideas, never picks, and show the routes' own caveats and dates", async ({ page }) => {
    await desk(page);
    await page.goto(SCANNER);
    await expect(page.getByTestId("desk-top10-stocks-list")).toBeVisible(SLOW);
    await expect(page.getByTestId("desk-top10-stocks-note")).toContainText("It is not a probability of profit.");
    const cash = await page.getByTestId("desk-top10").innerText();
    await showFno(page);
    await expect(page.getByTestId("desk-top10-fno-list")).toBeVisible(SLOW);
    const text = cash + (await page.getByTestId("desk-top10").innerText());
    expect(text).not.toMatch(/\bpicks?\b/i);
    expect(text).not.toMatch(/\bsuggested\b/i);
    expect(text.replace(/not (a )?recommendations?/gi, "")).not.toMatch(/recommend/i);
    await expect(page.getByTestId("desk-top10-fno-note")).toContainText("not a forecast");
    await expect(page.getByTestId("desk-top10-fno-regime")).toContainText("measured 19 Oct");
    await expect(page.getByTestId("desk-top10-fno-regime")).toContainText("regime was last classified");
    await expect(page.getByTestId("desk-top10-fno-skipped")).toContainText("PREMEXPLN");
  });
});

// ── provisional levels on the rows, and the F&O paper-trade contract ───────

const f2 = (n: number) => n.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

test.describe("Scanner — Top 10 ideas: provisional levels", () => {
  test("L-1 the BANKNIFTY F&O row shows the engine's levels, labelled and dated, with the full plan and no new entry control", async ({ page }) => {
    const seen = await desk(page);
    await page.goto(SCANNER);
    await showFno(page);
    const row = page.getByTestId("desk-top10-fno-BANKNIFTY");
    await openCard(row, "fno");
    const lv = row.getByTestId("idea-levels");
    await expect(lv).toHaveAttribute("data-state", "ok", SLOW);
    expect(seen.levels.filter((b) => b.payoff?.underlying === "BANKNIFTY")).toEqual([CONTRACT.levels_request]);
    await expect(lv.getByTestId("idea-levels-label")).toHaveText("Provisional · research levels");
    await expect(lv.getByTestId("idea-levels-asof")).toHaveText("end-of-day chain of 21 Oct 2026");
    await expect(lv.getByTestId("idea-levels-stop")).toContainText(`(BANKNIFTY ${f2(LEVELS.underlying.stop)})`);
    await expect(lv.getByTestId("idea-levels-t1")).toContainText(`(BANKNIFTY ${f2(LEVELS.underlying.target)})`);
    await expect(lv.getByTestId("idea-levels-maxloss")).toContainText(`₹${Math.abs(LEVELS.max_loss_total).toLocaleString("en-IN")}`);
    await expect(lv.locator("button")).toHaveCount(1);
    await lv.getByTestId("idea-levels-plan").click();
    await expect(lv.getByTestId("desk-levels")).toBeVisible();
    // the alternative structure behind the row asks for no levels and shows none
    expect(seen.levels.filter((b) => b.payoff?.underlying === "BANKNIFTY")).toHaveLength(1);
    await expect(row.getByTestId("desk-top10-fno-alt-BANKNIFTY-long_put").getByTestId("idea-levels")).toHaveCount(0);
    // an idea the engine did not accept says so instead of showing numbers
    await closeDrawer(page);
    await openCard(page.getByTestId("desk-top10-fno-SB1"), "fno");
    await expect(page.getByTestId("desk-top10-fno-SB1").getByTestId("idea-levels")).toHaveAttribute("data-state", "invalid");
  });

  test("L-2 the BANKNIFTY row's paper trade posts exactly the shared contract body", async ({ page }) => {
    const seen = await desk(page);
    await page.goto(SCANNER);
    await showFno(page);
    const row = page.getByTestId("desk-top10-fno-BANKNIFTY");
    await row.getByTestId("desk-top10-fno-paper").click(SLOW);
    await expect(row.getByTestId("idea-levels")).toHaveAttribute("data-state", "ok", SLOW);
    await row.getByTestId("idea-paper-trade").first().click();
    await expect(row.getByTestId("idea-paper-trade").first()).toHaveText("Added to paper trades");
    expect(seen.paper).toEqual([CONTRACT.body_with_levels]);
  });

  test("L-3 a stock row shows the scanner's entry, stop and target in the row, labelled with the scan date", async ({ page }) => {
    await desk(page);
    await page.goto(SCANNER);
    const icici = page.getByTestId("desk-top10-stock-ICICIBANK");
    await openCard(icici);
    const lv = icici.getByTestId("desk-top10-stock-levels");
    await expect(lv).toHaveAttribute("data-state", "ok", SLOW);
    await expect(icici.getByTestId("desk-top10-stock-paper")).toHaveAttribute("aria-expanded", "false");
    await expect(lv.getByTestId("desk-top10-stock-levels-label")).toHaveText("Provisional · research levels");
    await expect(lv.getByTestId("desk-top10-stock-levels-asof")).toHaveText("scan of 19 Oct 2026");
    await expect(lv.getByTestId("desk-top10-stock-levels-entry")).toHaveText("Entry ₹1,200.00");
    await expect(lv.getByTestId("desk-top10-stock-levels-stop")).toHaveText("Stop ₹1,160.00");
    await expect(lv.getByTestId("desk-top10-stock-levels-target")).toHaveText("Target ₹1,280.00");
    await expect(lv.locator("button, input")).toHaveCount(0);
  });

  test("L-4 the lab's focus card shows the same levels and posts the same contract body", async ({ page }) => {
    const seen = await desk(page);
    await page.goto(SCANNER);
    await showFno(page);
    await openCard(page.getByTestId("desk-top10-fno-BANKNIFTY"), "fno");
    await page.getByTestId("desk-top10-fno-BANKNIFTY").getByTestId("desk-top10-fno-lab").click(SLOW);
    const focus = page.getByTestId("desk-lab-focus");
    await expect(focus.getByTestId("idea-levels")).toHaveAttribute("data-state", "ok", SLOW);
    await expect(focus.getByTestId("idea-levels-label")).toHaveText("Provisional · research levels");
    await focus.getByTestId("idea-paper-trade").click();
    await expect(focus.getByTestId("idea-paper-trade")).toHaveText("Added to paper trades");
    expect(seen.paper).toEqual([CONTRACT.body_with_levels]);
  });
});

// ── the lab: focus panel, URL state, candidates ───────────────────────────

test.describe("F&O lab — opened from the Top 10 F&O ideas", () => {
  test("F-11 a stock idea opens Candidates with the idea in focus and its card outlined", async ({ page }) => {
    await desk(page);
    await page.goto(SCANNER);
    await showFno(page);
    await openCard(page.getByTestId("desk-top10-fno-SB1"), "fno");
    await page.getByTestId("desk-top10-fno-SB1").getByTestId("desk-top10-fno-lab").click();
    await expect(page.getByTestId("desk-lab-focus")).toBeVisible(SLOW);
    expect([params(page).get("tab"), params(page).get("lab"), params(page).get("lab_focus"), params(page).get("lab_sym")]).toEqual(["market", "candidates", "SB1", "SB1"]); // the lab is in Market Desk › Smart Money since the 2026-10-27 redesign
    await expect(page.getByTestId("desk-lab-focus")).toContainText("Bear put spread 2500/2550");
    await expect(page.getByTestId("desk-lab-focus-rank")).toContainText("#1 · SB1");
    // SB1 is a short build-up candidate: that category opens, not the first one.
    await expect(page.getByTestId("desk-cand-category-short_buildup")).toHaveAttribute("aria-pressed", "true");
    await expect(page.getByTestId("desk-cand-card-SB1")).toHaveAttribute("data-focused", "true");
    await expect(page.getByTestId("desk-cand-card-SB2")).not.toHaveAttribute("data-focused", "true");
  });

  test("F-12 an index idea opens the index workspace with the idea in focus", async ({ page }) => {
    await desk(page);
    await page.goto(SCANNER);
    await showFno(page);
    await openCard(page.getByTestId("desk-top10-fno-BANKNIFTY"), "fno");
    await page.getByTestId("desk-top10-fno-BANKNIFTY").getByTestId("desk-top10-fno-lab").click();
    await expect(page.getByTestId("desk-lab-focus")).toHaveAttribute("data-symbol", "BANKNIFTY", SLOW);
    expect([params(page).get("lab"), params(page).get("lab_sym"), params(page).get("lab_focus")]).toEqual(["indices", "BANKNIFTY", "BANKNIFTY"]);
    await expect(page.getByTestId("desk-fno-indices")).toHaveAttribute("data-index", "BANKNIFTY");
    await expect(page.getByTestId("desk-lab-focus-index")).toBeVisible();
  });

  test("F-13 the focus panel switches the lab to the chain and the futures OI build-up, and closes", async ({ page }) => {
    await desk(page);
    await page.goto(`${DESK}?tab=fno&lab=candidates&lab_sym=SB1&lab_focus=SB1`);
    await expect(page.getByTestId("desk-lab-focus")).toBeVisible(SLOW);
    await page.getByTestId("desk-lab-focus-chain").click();
    expect([params(page).get("lab"), params(page).get("lab_sym")]).toEqual(["chain", "SB1"]);
    await expect(page.getByTestId("desk-fno-view-chain")).toHaveAttribute("aria-selected", "true");
    await page.getByTestId("desk-lab-focus-buildup").click();
    expect(params(page).get("lab")).toBeNull();                       // the default view is left out of the URL
    await expect(page.getByTestId("desk-fno-view-buildup")).toHaveAttribute("aria-selected", "true");
    await expect(page.getByTestId("desk-lab-focus-buildup")).toHaveAttribute("aria-pressed", "true");
    await page.getByTestId("desk-lab-focus-close").click();
    await expect(page.getByTestId("desk-lab-focus")).toHaveCount(0);
    expect(params(page).get("lab_focus")).toBeNull();
  });

  test("F-13 an underlying not on the board says so instead of showing another idea", async ({ page }) => {
    await desk(page);
    await page.goto(`${DESK}?tab=fno&lab=candidates&lab_focus=LB1`);
    await expect(page.getByTestId("desk-lab-focus-missing")).toContainText("LB1 is not on the current Top 10", SLOW);
  });

  test("F-14 a candidate card opens its futures OI build-up and the Strategy Builder", async ({ page }) => {
    await desk(page);
    await page.goto(`${DESK}?tab=fno&lab=candidates`);
    await page.getByTestId("desk-cand-buildup-LB1").click(SLOW);
    expect([params(page).get("lab"), params(page).get("lab_sym")]).toEqual([null, "LB1"]);
    await expect(page.getByTestId("desk-fno-view-buildup")).toHaveAttribute("aria-selected", "true");
    await page.getByTestId("desk-fno-view-candidates").click();
    await page.getByTestId("desk-cand-strategy-open-LB1").click();
    expect([params(page).get("tab"), params(page).get("view"), params(page).get("sym"), params(page).get("src_kind")]).toEqual(["trade", "new", "LB1", "lab"]); // was more/strategy before the 2026-10-27 redesign
    expect(params(page).get("lab")).toBeNull();                       // a tab change drops the lab's own params
  });
});

// The breadcrumb-trail cases left in the desk redesign's step 6: the breadcrumb is the location (copilot-app-desk-shell.spec.ts SH-11).

// ── market pulse, and Market Intelligence's URL state ─────────────────────

// RETIRED by the desk redesign step 2 (Market Overview, 2026-10-27): the market pulse (tradingdesk/ScannerPulse.tsx) is no
// longer mounted; its FII / DII, sector moves and events are Market Overview's strip and events today
// (copilot-app-desk-market-overview.spec.ts). F-30 … F-34 are skipped; F-35 (Market Intelligence) still runs. ScannerPulse is
// deleted or re-hosted in step 6.
test.describe("Scanner — market pulse", () => {
  test.skip("F-30 / F-31 the latest events and the three indicators, from their routes, with dates", async ({ page }) => {
    await desk(page);
    await page.goto(SCANNER);
    await expect(page.getByTestId("desk-pulse-event-ann-001")).toContainText("Financial results for the quarter ended September 2026", SLOW);
    // Desk redesign (2026-10-27): the strip is read in its section (Market Overview has a second pulse card).
    const ids = await page.getByTestId("desk-panel-pulse").getByTestId("desk-pulse-events").locator("button").evaluateAll((els) => els.map((e) => e.getAttribute("data-testid")));
    expect(ids).toEqual(["desk-pulse-event-ann-001", "desk-pulse-event-ann-002"]);   // newest first
    await expect(page.getByTestId("desk-pulse-fii")).toHaveText("−₹1,000 cr");      // 2026-10-13, the newest session
    await expect(page.getByTestId("desk-pulse-dii")).toHaveText("+₹800 cr");
    await expect(page.getByTestId("desk-pulse-flows")).toContainText("13 Oct 2026");
    await expect(page.getByTestId("desk-pulse-sm-fii")).toHaveText("−₹98,383 cr");
    await expect(page.getByTestId("desk-pulse-sm-dii")).toHaveText("+₹1,98,123 cr");
    await expect(page.getByTestId("desk-pulse-sm-mf")).toContainText("46.0% of Nifty 500 names");
    // Sector moves of 1% or more only: IT and Realty, not Bank (+0.3%).
    await expect(page.getByTestId("desk-pulse-sector")).toHaveCount(2);
    await expect(page.getByTestId("desk-pulse-sectors")).not.toContainText("Nifty Bank");
  });

  test.skip("F-32 an event opens Market Intelligence with that event selected", async ({ page }) => {
    await desk(page);
    await page.goto(SCANNER);
    await page.getByTestId("desk-pulse-event-ann-002").click(SLOW);
    // Desk redesign (2026-10-27): Market Intelligence is a Market Desk view; the breadcrumb is the location (SH-11), so no "from" crumb.
    await expect(page.getByTestId("screen-trading-desk")).toHaveAttribute("data-view", "intel");
    expect(params(page).get("in_ev")).toBe("ann-002");
    await expect(page.getByTestId("desk-event-detail")).toHaveAttribute("data-id", "ann-002", SLOW);
  });

  test.skip("F-33 the pulse opens Market Intelligence, its FII / DII chip, and Smart Money", async ({ page }) => {
    await desk(page);
    await page.goto(SCANNER);
    await page.getByTestId("desk-pulse-flows").click(SLOW);
    expect(params(page).get("in_chip")).toBe("flows");
    await expect(page.getByTestId("desk-intel-chip-flows")).toHaveAttribute("aria-pressed", "true", SLOW);
    // Desk redesign (2026-10-27): back to Market Overview by URL (the breadcrumb no longer records the path); the targets are Market Desk views.
    await page.goto(SCANNER);
    await page.getByTestId("desk-pulse-open-smartmoney").click(SLOW);
    await expect(page.getByTestId("screen-trading-desk")).toHaveAttribute("data-view", "smartmoney");
    await page.goto(SCANNER);
    await page.getByTestId("desk-pulse-open-intel").click(SLOW);
    await expect(page.getByTestId("screen-trading-desk")).toHaveAttribute("data-view", "intel");
    expect(params(page).get("in_chip")).toBeNull();
  });

  test.skip("F-34 a failed source shows in its own tile; the rest still show", async ({ page }) => {
    await desk(page);
    await page.route("**/api/markets/smart-money/summary*", (r) => json(r, { error: { message: "upstream_unavailable" } }, 502));
    await page.goto(SCANNER);
    await expect(page.getByTestId("desk-pulse-smartmoney")).toContainText("didn’t load", SLOW);
    await expect(page.getByTestId("desk-pulse-fii")).toHaveText("−₹1,000 cr");
  });

  test("F-35 Market Intelligence keeps its chip in the URL across a reload", async ({ page }) => {
    await desk(page);
    await page.goto(`${DESK}?tab=intel`);
    await page.getByTestId("desk-intel-chip-results").click(SLOW);
    expect(params(page).get("in_chip")).toBe("results");
    await page.reload();
    await expect(page.getByTestId("desk-intel-chip-results")).toHaveAttribute("aria-pressed", "true", SLOW);
  });
});

// ── phone ─────────────────────────────────────────────────────────────────

test.describe("Phone (390px)", () => {
  test.use({ viewport: { width: 390, height: 844 } });

  test("F-26 breadcrumb and both boards (one at a time) render with no sideways scroll", async ({ page }) => {
    await desk(page);
    await page.goto(SCANNER);
    await expect(page.getByTestId("desk-trail")).toBeVisible();
    await expect(page.getByTestId("desk-top10-stocks-list").locator(":scope > li")).toHaveCount(3, SLOW);
    await page.getByTestId("desk-top10-switch-fno").click();
    await expect(page.getByTestId("desk-top10-fno-list").locator(":scope > li")).toHaveCount(4, SLOW);
    const over = await page.evaluate(() => {
      const sc = document.querySelector('[data-testid="copilot-scroll"]') as HTMLElement | null;
      return Math.max(document.documentElement.scrollWidth - window.innerWidth, sc ? sc.scrollWidth - sc.clientWidth : 0);
    });
    expect(over).toBeLessThanOrEqual(0);
  });
});

// ── Phase 2.1: every row records the TradePlan's levels (test_reports/p2_trade_plan_lifecycle_TESTCASES.md UI-1, UI-3) ──
// The ideas and the F&O board come from the shared contract fixture contract-trade-plan-paper.json, whose bodies
// backend/tests/test_trade_plan_contract.py sends through the real route. Cash: MOCK — the RELIANCE-like world of
// backend/tests/test_strategy_plan.py; F&O: the REAL 2026-10-21 capture with the plans the backend builds for it.
const PLANS = load("contract-trade-plan-paper.json");
const planBoard = () => {
  const b = JSON.parse(JSON.stringify(PLANS.fno.top_response));
  delete b.classes.cash;
  return b;
};

test.describe("Top 10 — trade plans (Phase 2.1)", () => {
  test("UI-1 a stock row shows its plan (entry, stop method, targets in R) and records exactly the plan's levels with plan_ref", async ({ page }) => {
    const seen = await desk(page, { ideas: { status: 200, body: PLANS.cash.ideas_response } });
    await page.goto(SCANNER);
    const sym = PLANS.cash.body.symbol;
    const row = page.getByTestId(`desk-top10-stock-${sym}`);
    await row.getByTestId("desk-top10-stock-paper").click(SLOW);
    const line = row.getByTestId("desk-top10-paper-plan");
    await expect(line).toHaveAttribute("data-plan-id", PLANS.cash.trade_plan.plan_id);
    await expect(line).toContainText("Stop ₹1,160 (1.5×ATR below 1195)");
    await expect(line).toContainText("₹1,280 (2R)");
    await expect(line).not.toContainText("2 x ATR");
    await expect(row.getByTestId("desk-top10-paper-rule")).toHaveAttribute("data-rule", "at_once");
    await row.getByTestId("desk-top10-paper-qty").fill(String(PLANS.cash.body.quantity));
    await row.getByTestId("desk-top10-paper-add").click();
    await expect(row.getByTestId("desk-top10-paper-done")).toBeVisible();
    expect(seen.paper).toEqual([PLANS.cash.body]);
    expect(seen.paperKeys[0]).toMatch(UUID);
  });

  test("UI-1b a plan its own rules reject cannot be added and the row says why", async ({ page }) => {
    const ideas = JSON.parse(JSON.stringify(PLANS.cash.ideas_response));
    ideas.ideas[0].trade_plan.eligibility = { eligible: false, paper_eligible: false, state: "REJECTED", status: "no_trade",
      reasons: [{ code: "reward_risk_below_minimum", message: "Reward : risk 0.9 at the base level is below the minimum 1.5." }] };
    const seen = await desk(page, { ideas: { status: 200, body: ideas } });
    await page.goto(SCANNER);
    const row = page.getByTestId(`desk-top10-stock-${PLANS.cash.body.symbol}`);
    await row.getByTestId("desk-top10-stock-paper").click(SLOW);
    await expect(row.getByTestId("desk-top10-paper-blocked")).toContainText("This plan is rejected: Reward : risk 0.9");
    await expect(row.getByTestId("desk-top10-paper-add")).toHaveCount(0);
    expect(seen.paper).toEqual([]);
  });

  test("UI-3 an F&O row cites its plan; a bearish stock idea on a bullish cash setup says so and cannot be recorded", async ({ page }) => {
    const seen = await desk(page, { top: { status: 200, body: planBoard() } });
    await page.goto(SCANNER);
    await showFno(page);
    const bank = page.getByTestId(`desk-top10-fno-${PLANS.fno.idea_underlying}`);
    await bank.getByTestId("desk-top10-fno-paper").click(SLOW);
    await expect(bank.getByTestId("idea-plan-id").first()).toHaveAttribute("data-plan-id", PLANS.fno.trade_plan.plan_id, SLOW);
    await expect(bank.getByTestId("idea-levels")).toHaveAttribute("data-state", "ok", SLOW);
    await bank.getByTestId("idea-paper-trade").first().click();
    await expect(bank.getByTestId("idea-paper-trade").first()).toHaveText("Added to paper trades");
    expect(seen.paper).toEqual([PLANS.fno.body]);
    const conflicted = planBoard().classes.stock_fno.ideas.find((i: { conflicts_with_cash_setup?: unknown }) => i.conflicts_with_cash_setup);
    expect(conflicted, "the real capture's bearish stock ideas are flagged").toBeTruthy();
    await closeDrawer(page);
    const row = page.getByTestId(`desk-top10-fno-${conflicted.underlying}`);
    await openCard(row, "fno");
    await expect(row.getByTestId("idea-cash-conflict").first()).toContainText("One direction per instrument per day");
    await expect(row.getByTestId("idea-paper-trade").first()).toBeDisabled();
  });
});
