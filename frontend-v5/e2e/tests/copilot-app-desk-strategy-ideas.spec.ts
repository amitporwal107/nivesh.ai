/**
 * One-screen Copilot app - Smart trading desk: the Strategy Builder's "From AI opportunities" mode
 * (screens/tradingdesk/strategy/IdeasBoard; reached at ?tab=more&view=strategy&mode=ideas, and the default when
 * the URL names no stock).
 *
 * MOCK - not real data. POST /api/desk/strategy/ideas is answered by `ideasBody()` below, hand-written to the
 * contract (ideas-contract.ts) while the backend route is built in parallel. Every figure printed is the
 * payload's; the ones written into it are HAND-COMPUTED so the screen is checked against known numbers:
 *   ICICIBANK close 1,200, stop 1,160 (40 a share), risk budget 10,000, capital 10,00,000 at 25% allocation:
 *     cash      208 shares = min(floor(10,000 / 40) = 250, floor(10,00,000 x 25% / 1,200) = 208);
 *               max loss 208 x 40 = 8,320; at risk 208 x 1,200 = 2,49,600 is the position, 8,320 the loss; target 1,280: profit 80 x 208 = 16,640
 *     futures   lot 250, stop 1,150, 53 a unit x 250 = 13,250 a lot; floor(20,000 / 13,250) = 1 lot; profit unbounded; breakeven 1,203
 *     spread    buy 1,200 call at 52, sell 1,250 call at 38: debit 14, width 50; 2 lots of 250:
 *               max loss 14 x 250 x 2 = 7,000, max profit (50 - 14) x 250 x 2 = 18,000, breakeven 1,200 + 14 = 1,214
 *     protective put  250 shares at 1,200 + one 1,160 put at 20: loss (1,200 - 1,160 + 20) x 250 = 15,000, breakeven 1,220
 *
 * SI-10 uses a REAL captured response of the built route (e2e/fixtures/strategy-ideas-real.json, 2026-10-20, staging data read-only: 8 ideas,
 * scan 16 Oct, prices 19 Oct), so the screen is checked against the exact shape. HAL covered call, by hand from its legs: 900 shares bought at
 * 4,989 and 6 lots (150 each) of the 5,400 call sold; max profit (5,400 - 4,989) x 900 + 67.25 premium x 900 = 369,900 + 60,525 = 4,30,425,
 * breakeven 4,989 - 67.25 = 4,921.75 (both as the payload has them).
 *
 * Cases: SI-1 mode switch and default · SI-2 board header, request, excluded · SI-3 the viable idea in full ·
 * SI-4 wait / no trade / not-F&O / insufficient · SI-5 inputs and 422 · SI-6 open full plan / open this strategy ·
 * SI-7 Overview links · SI-8 empty, errors, 401, 403, contract error · SI-9 persona, 390px, no order controls.
 */
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";
import { test, expect, type Page, type Route } from "@playwright/test";
import { mockApi, mockSingleRoute } from "../helpers/api-mock";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const DESK = "/v5/app/trader/desk";
const IDEAS = `${DESK}?tab=more&view=strategy`;
const json = (route: Route, body: unknown, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
const planFixture = (n: string) => JSON.parse(fs.readFileSync(path.join(__dirname, "..", "fixtures", `strategy-plan-${n}.json`), "utf-8"));
const SHOTS = process.env.SHOTS_DIR;
/** Screenshots only when SHOTS_DIR is set: the viewport (with the dock) and the whole board element (the page scrolls inside the app). */
const shot = async (page: Page, name: string, w: number) => {
  if (!SHOTS) return;
  fs.mkdirSync(SHOTS, { recursive: true });
  await page.screenshot({ path: path.join(SHOTS, `si-${name}-${w}.png`) });
  const el = page.getByTestId("strategy-ideas");
  if (await el.count()) {
    const vp = page.viewportSize() ?? { width: w, height: 900 };
    await page.setViewportSize({ width: vp.width, height: 5200 });
    await el.screenshot({ path: path.join(SHOTS, `si-${name}-${w}-full.png`) });
    await page.setViewportSize(vp);
  }
};

// ── the MOCK payload, shaped as the contract ─────────────────────────────

const OTHER_COUNTS = { supports: 0, conflicts: 0, neutral: 0, unavailable: 0 };
const evidence = (t: number[], f: number[], d: number[] | null) => ({
  technical: { supports: t[0], conflicts: t[1], neutral: t[2], unavailable: t[3] },
  fundamental: { supports: f[0], conflicts: f[1], neutral: f[2], unavailable: f[3] },
  ...(d ? { derivatives: { supports: d[0], conflicts: d[1], neutral: d[2], unavailable: d[3] } } : {}),
  market_context: OTHER_COUNTS, catalysts: OTHER_COUNTS, validation: OTHER_COUNTS, portfolio: OTHER_COUNTS,
});
// The real route's strategy shape: reasons are {code, message}; max_loss is a negative P&L (null when not viable); legs_text is "" without legs.
const strat = (o: Record<string, unknown>) => ({
  legs_text: "", max_loss: null, max_loss_basis: "defined max loss at expiry (gross)", capital_at_risk: null, max_profit: null, profit_unbounded: false, breakeven: [],
  reward_risk_net: null, reward_risk_gross: null, actionable: false, liquidity_flags: [], why: null, flags: [], ...o,
  reasons: ((o.reasons as string[] | undefined) ?? []).map((m, i) => ({ code: `mock_${i}`, message: m })),
  sizing: { status: null, quantity: null, lots: null, binding: null, unit: null, risk_budget_inr: null, risk_at_stop_inr: null, deployed_inr: null, missing: [], ...((o.sizing as object | undefined) ?? {}) },
});
const CASH_BASIS = "loss at the stop (net); gaps can exceed it";
// The exact body that rebuilds the plan (the route: the symbol, bullish, "all" and the inputs the request passed).
const PLAN_INPUTS = { underlying: "ICICIBANK", direction: "bullish", instrument: "all", capital: 1000000, risk_budget_inr: 10000, max_allocation_pct: 25, min_reward_risk: 1.5, avoid_events: true, allow_multi_leg: true, include_combinations: true };
const scanner = (o: Record<string, unknown>) => ({ bucket: "breakout_confirmed", status: "confirmed", score: 86, close: 1200, close_date: "2026-10-19", entry: 1200, stop: 1160, target: 1280, reason: "MOCK reason", horizon_days: 10, liquidity_cr: 812.4, atr_pct: 1.67, ...o });

const ICICI = {
  rank: 1, symbol: "ICICIBANK", name: "ICICI Bank Ltd", scanner: scanner({}), direction: "bullish", fno_eligible: true, plan_id: "plan_icici_1", plan_status: "plan",
  status_reasons: [{ code: "setup_confirmed", message: "The breakout closed above its 20-session high on volume." }], would_change_if: ["A close below 1,160"],
  plan_inputs: PLAN_INPUTS, headline: { model_estimate: { status: "withheld" } }, evidence_summary: evidence([5, 1, 1, 0], [3, 2, 0, 2], [2, 0, 1, 0]),
  oi_view: { buildup: "long_buildup", cash_confirmation: "confirmed", pcr: 1.12, max_pain: 1200, call_wall: 1250, put_wall: 1150, source_as_of: "2026-10-19" },
  preferred: "options:bull_call_spread",
  strategies: [
    strat({ id: "cash:breakout_continuation", segment: "cash", family: "breakout_continuation", label: "Buy shares on the breakout", status: "candidate", legs_text: "Buy 208 shares at 1,200.00", max_loss: -8320, max_loss_basis: CASH_BASIS, capital_at_risk: 249600, max_profit: 16640, breakeven: [1200], reward_risk_net: 1.9, reward_risk_gross: 2, sizing: { status: "complete", unit: "shares", quantity: 208, lots: null, binding: "max_allocation" } }),
    strat({ id: "futures:long_buildup_continuation", segment: "futures", family: "long_buildup_continuation", label: "Long futures on build-up", status: "candidate", legs_text: "Buy 1 lot (250) of the Oct futures at 1,203.00", max_loss: -13250, max_loss_basis: CASH_BASIS, capital_at_risk: 13250, profit_unbounded: true, breakeven: [1203], reward_risk_net: 1.6, sizing: { status: "complete", unit: "lots", quantity: 250, lots: 1, binding: "risk_budget" }, flags: ["Futures loss can exceed margin"] }),
    strat({ id: "options:long_call", segment: "options", family: "long_call", label: "Buy a call", status: "no_trade", reasons: ["One lot's premium is above the risk budget"], max_loss: 99999, capital_at_risk: 99999, max_profit: 88888, breakeven: [7777], reward_risk_net: 9.9 }),
    strat({ id: "options:bull_call_spread", segment: "options", family: "bull_call_spread", label: "Bull call spread 1200/1250", status: "candidate", legs_text: "Buy 1,200 call at 52.00; sell 1,250 call at 38.00", max_loss: -7000, max_loss_basis: "defined max loss at expiry (net)", capital_at_risk: 7000, max_profit: 18000, breakeven: [1214], reward_risk_net: 2.4, sizing: { status: "complete", unit: "lots", quantity: 500, lots: 2, binding: "risk_budget" }, liquidity_flags: ["Thin open interest at the 1,250 strike"] }),
    strat({ id: "combination:protective_put", segment: "combination", family: "protective_put", label: "Shares with a protective put", status: "candidate", legs_text: "Buy 250 shares at 1,200.00; buy 1 lot 1,160 put at 20.00", max_loss: -15000, max_loss_basis: "defined max loss at expiry (net)", capital_at_risk: 15000, profit_unbounded: true, breakeven: [1220], reward_risk_net: null, sizing: { status: "complete", unit: "lots", quantity: 250, lots: 1, binding: "lot_size" } }),
    strat({ id: "combination:collar", segment: "combination", family: "collar", label: "Collar 1160/1250", status: "wait", reasons: ["The 1,250 call wall leaves little room above the entry"], max_loss: 12345, capital_at_risk: 12345 }),
  ],
};
const TATA = {
  rank: 2, symbol: "TATASTEEL", name: "Tata Steel Ltd", scanner: scanner({ bucket: "pre_breakout", status: "awaiting", score: 74, close: 158, entry: 160, stop: 152, target: 176, atr_pct: 2.9, liquidity_cr: 410 }), direction: "bullish", fno_eligible: true, plan_id: "plan_tata_1", plan_status: "wait",
  status_reasons: [{ code: "not_confirmed", message: "Price has not closed above the 160.00 trigger yet." }], would_change_if: ["A close above 160.00 on above-average volume"],
  plan_inputs: { ...PLAN_INPUTS, underlying: "TATASTEEL" }, headline: {}, evidence_summary: evidence([3, 2, 2, 0], [1, 1, 1, 4], [0, 1, 1, 0]),
  oi_view: { buildup: "short_covering", cash_confirmation: null, pcr: null, max_pain: 160, call_wall: null, put_wall: 150, source_as_of: "2026-10-19" }, preferred: null,
  strategies: [
    strat({ id: "cash:breakout_watch", segment: "cash", family: "breakout_watch", label: "Wait for the breakout close", status: "wait", reasons: ["Enter only after a close above 160.00"], max_loss: 5555, capital_at_risk: 5555, reward_risk_net: 3.3 }),
    strat({ id: "futures:long_buildup_continuation", segment: "futures", family: "long_buildup_continuation", label: "Long futures on build-up", status: "wait", reasons: ["Build-up is short covering, not fresh longs"] }),
  ],
};
const RELI = {
  rank: 3, symbol: "RELIANCE", name: "Reliance Industries Ltd", scanner: scanner({ close: 1180, score: 71, atr_pct: 1.9 }), direction: "bullish", fno_eligible: true, plan_id: "plan_reli_1", plan_status: "no_trade",
  status_reasons: [{ code: "event_in_horizon", message: "Results on 23 Oct 2026 fall inside the 10-session horizon." }], would_change_if: ["The results are out of the horizon"],
  plan_inputs: { ...PLAN_INPUTS, underlying: "RELIANCE" }, headline: {}, evidence_summary: evidence([4, 0, 2, 0], [2, 1, 1, 1], [1, 0, 2, 0]),
  oi_view: { buildup: "long_buildup", cash_confirmation: "confirmed", pcr: 0.94, max_pain: 1180, call_wall: 1220, put_wall: 1140, source_as_of: "2026-10-19" }, preferred: null,
  strategies: [
    strat({ id: "cash:breakout_continuation", segment: "cash", family: "breakout_continuation", label: "Buy shares on the breakout", status: "no_trade", reasons: ["Results on 23 Oct 2026 are inside the horizon and events are to be avoided"], max_loss: 4444 }),
    strat({ id: "futures:long_buildup_continuation", segment: "futures", family: "long_buildup_continuation", label: "Long futures on build-up", status: "avoid", reasons: ["A gap on the results can pass the stop"] }),
  ],
};
const NOT_FNO = "The stock is not in the NSE F&O segment (fno_eligible is false): it has no futures or options, so only the cash idea applies.";
const noFnoRow = (segment: string) => ({ ...strat({ id: `${segment}:none`, segment, family: "none", label: `No ${segment} strategy`, status: "no_trade" }), reasons: [{ code: "not_fno_eligible", message: NOT_FNO }] });
const AARTI = {
  rank: 4, symbol: "AARTIDRUGS", name: null, scanner: scanner({ bucket: "trend_continuation", score: 66, close: 410, entry: 410, stop: 390, target: 450, atr_pct: 4.6, liquidity_cr: 14.2 }), direction: "bullish", fno_eligible: false, plan_id: "plan_aarti_1", plan_status: "plan",
  status_reasons: [{ code: "not_fno_eligible", message: NOT_FNO }], would_change_if: [],
  plan_inputs: { ...PLAN_INPUTS, underlying: "AARTIDRUGS" }, headline: {}, evidence_summary: evidence([3, 1, 1, 0], [2, 0, 1, 2], null),
  oi_view: { buildup: null, cash_confirmation: null, pcr: null, max_pain: null, call_wall: null, put_wall: null, expected_move: null, chain_expiry: null, atm_iv: null, source_as_of: null, unavailable: ["build-up: AARTIDRUGS has no futures row on 2026-10-19"] }, preferred: "cash:trend_pullback",
  strategies: [strat({ id: "cash:trend_pullback", segment: "cash", family: "trend_pullback", label: "Buy the pullback", status: "candidate", legs_text: "Buy 300 shares at 410.00", max_loss: -6000, max_loss_basis: CASH_BASIS, capital_at_risk: 123000, max_profit: 12000, breakeven: [410], reward_risk_net: 1.9, sizing: { status: "complete", unit: "shares", quantity: 300, lots: null, binding: "risk_budget" } }), noFnoRow("futures"), noFnoRow("options"), noFnoRow("combination")],
};
const HIND = {
  rank: 5, symbol: "HINDALCO", name: "Hindalco Industries Ltd", scanner: scanner({ bucket: "true_accumulation", status: "forming", score: 52, close: 700, atr_pct: null, liquidity_cr: null }), direction: "bullish", fno_eligible: true, plan_id: null, plan_status: "insufficient_data",
  status_reasons: [{ code: "no_price_history", message: "Fewer than 60 sessions of adjusted prices, so no plan is built." }], would_change_if: ["60 sessions of prices exist"],
  plan_inputs: { ...PLAN_INPUTS, underlying: "HINDALCO" }, headline: {}, evidence_summary: evidence([0, 0, 0, 9], [0, 0, 0, 6], [0, 0, 0, 3]), oi_view: null, preferred: null, strategies: [],
};

const ideasBody = (over: Record<string, unknown> = {}) => ({
  generated_at: "2026-10-20T05:00:00+00:00", data_as_of: { mode: "end_of_day", scanner_watchlist: "2026-10-19", scanner_picks: "2026-10-19", scan_eligibility: "2026-10-19", price: "2026-10-19", fno: "2026-10-19" },
  caveats: ["Conditional research ideas, not advice and not an instruction to trade.", "Margin is not estimated (no source exists in this system) and is not the maximum loss."],
  rules_version: "strategy-rules-v2", calculation_version: "payoff-v1", sent_to_broker: false,
  ranking_note: "Ranked by the scanner's rules-based score. It is not a probability of profit.",
  selection: { source: "positional_watchlist", scan_date: "2026-10-19", rule: "Confirmed and awaiting setups, highest scanner score first, liquidity of at least 10 Cr a day", considered: 14, selected: 5,
    excluded: [{ symbol: "SMALLCO", reason: "Liquidity 3.2 Cr a day is below the 10 Cr floor", code: "illiquid" }, { symbol: "WEAKCO", reason: "Score 41 is below the minimum of 50", code: "score" }], excluded_note: "Only setups ranked above the last selected one are listed.", limit: 8, empty_reason: null, gate: "scan snapshot eligibility gates", source_failures: [] },
  inputs: { direction: "bullish", instrument: "all", max_allocation_pct: 25, min_reward_risk: 1.5, avoid_events: true, include_combinations: true, limit: 8, defaults_applied: ["avoid_events", "max_allocation_pct", "min_reward_risk"] },
  ideas: [ICICI, TATA, RELI, AARTI, HIND], ...over,
});

// ── page plumbing ────────────────────────────────────────────────────────

const WATCHLIST = { as_of_date: "2026-10-19", buckets: {
  breakout_confirmed: [{ nse_symbol: "TESTBRK", sector: "Capital Goods", close_price: 510.0, trigger_price: 500.0, stop_price: 477.5, atr_pct: 2.94, why: "Fixture reason" }],
  pre_breakout: [], true_accumulation: [], trend_continuation: [] } };
const PICKS = { signal_date: "2026-10-19", count: 0, picks: [] };

interface Opts { reply?: { status: number; body: unknown }; plan?: string }
interface State { ideas: Array<Record<string, unknown>>; builds: Array<Record<string, unknown>>; writes: string[] }

async function setup(page: Page, o: Opts = {}): Promise<State> {
  const st: State = { ideas: [], builds: [], writes: [] };
  await mockApi(page, "populated");
  await mockSingleRoute(page, "**/api/markets/home", "markets-home.json");
  page.on("request", (r) => {
    const p = new URL(r.url()).pathname;
    if (r.method() !== "GET" && /\/api\//.test(p) && !/\/api\/desk\/strategy\/(ideas|plan|payoff)$/.test(p)) st.writes.push(`${r.method()} ${p}`);
  });
  await page.route("**/api/positional/watchlist*", (r) => json(r, WATCHLIST));
  await page.route("**/api/positional/picks*", (r) => json(r, PICKS));
  await page.route("**/api/move-odds/**", (r) => json(r, { detail: "feature_not_enabled" }, 403));
  await page.route("**/api/desk/paper-trades*", (r) => json(r, { as_of: null, trades: [], summary: null }));
  await page.route("**/api/desk/alerts*", (r) => json(r, { as_of: null, alerts: [] }));
  await page.route("**/api/desk/strategy/plans*", (r) => json(r, { plans: [], count: 0, limit: 100, max_saved: 200 }));
  await page.route("**/api/desk/strategy/payoff", (r) => json(r, { detail: "not mocked here" }, 404));
  await page.route("**/api/research/chart-live/**", (r) => json(r, { detail: "not mocked here" }, 404));
  await page.route("**/api/chat/**", (r) => json(r, []));
  const L = { watchlist_id: "wl1", name: "Swing ideas", symbol_count: 1, is_starter: false, seeded_from: null, created_at: "2026-10-01T10:00:00+00:00", updated_at: "2026-10-10T10:00:00+00:00" };
  await page.route("**/api/watchlists", (r) => json(r, { lists: [L], limits: { max_lists: 20, max_symbols: 50 }, starter_pending: false }));
  await page.route("**/api/desk/strategy/plan", (r) => { st.builds.push(r.request().postDataJSON() as Record<string, unknown>); return json(r, planFixture(o.plan ?? "all")); });
  await page.route("**/api/desk/strategy/ideas", (r) => {
    st.ideas.push(r.request().postDataJSON() as Record<string, unknown>);
    return o.reply ? json(r, o.reply.body, o.reply.status) : json(r, ideasBody());
  });
  return st;
}

async function openBoard(page: Page, o: Opts = {}, query = "", width = 1440) {
  await page.setViewportSize({ width, height: 900 });
  const st = await setup(page, o);
  await page.goto(`${IDEAS}${query}`);
  return st;
}
const card = (page: Page, sym: string) => page.getByTestId(`idea-${sym}`);
async function sideways(page: Page) {
  return page.evaluate(() => {
    const sc = document.querySelector('[data-testid="copilot-scroll"]') as HTMLElement | null;
    return { doc: document.documentElement.scrollWidth - window.innerWidth, scroll: sc ? sc.scrollWidth - sc.clientWidth : 0 };
  });
}

test.describe("MOCK - not real data: Strategy Builder, from AI opportunities", () => {
  // ── SI-1 ─────────────────────────────────────────────────────────────

  test("SI-1 the default mode without a stock is the ideas board; One stock is one click away; a stock in the URL opens One stock; the URL carries the mode", async ({ page }) => {
    await openBoard(page);
    await expect(page.getByTestId("strategy-ideas")).toBeVisible();
    await expect(page.getByTestId("builder-mode-ideas")).toHaveAttribute("aria-pressed", "true");
    await expect(page.getByTestId("builder-mode-stock")).toHaveAttribute("aria-pressed", "false");
    await expect(page.getByTestId("builder-mode-ideas")).toHaveText("From AI opportunities");

    await page.getByTestId("builder-mode-stock").click();
    await expect(page).toHaveURL(/mode=stock/);
    await expect(page.getByTestId("strategy-builder")).toBeVisible();
    await expect(page.getByTestId("builder-empty")).toContainText("No plan yet");
    await expect(page.getByTestId("strategy-ideas")).toHaveCount(0);

    await page.getByTestId("builder-mode-ideas").click();
    await expect(page).toHaveURL(/mode=ideas/);
    await expect(page.getByTestId("strategy-ideas")).toBeVisible();

    // A stock in the URL keeps today's screen; the switch still leads back.
    await page.goto(`${IDEAS}&sym=RELIANCE&direction=bullish&instrument=cash`);
    await expect(page.getByTestId("strategy-builder")).toBeVisible();
    await expect(page.getByTestId("builder-mode-stock")).toHaveAttribute("aria-pressed", "true");
    await expect(page.getByTestId("in-symbol")).toHaveValue("RELIANCE");
  });

  // ── SI-2 ─────────────────────────────────────────────────────────────

  test("SI-2 the board runs once on open with the defaults, states its source, rule and data dates, lists what was left out (collapsed), and carries a trust line", async ({ page }) => {
    const st = await openBoard(page);
    await expect(page.getByTestId("ideas-view")).toBeVisible();
    expect(st.ideas).toEqual([{ limit: 8, include_combinations: true }]);

    await expect(page.getByTestId("ideas-source")).toHaveText("Top setups from the AI scanner, end-of-day scan 19 Oct 2026; ranked by the scanner's rules-based score, not a probability.");
    await expect(page.getByTestId("ideas-asof")).toContainText("Scan 19 Oct 2026 · prices 19 Oct 2026 · F&O 19 Oct 2026 · end of day, not live");
    await expect(page.getByTestId("ideas-scan-older")).toHaveCount(0);
    await expect(page.getByTestId("ideas-rule")).toContainText("highest scanner score first");
    await expect(page.getByTestId("ideas-ranking")).toContainText("It is not a probability of profit");
    await expect(page.getByTestId("ideas-defaults")).toContainText("avoid events true, max allocation pct 25, min reward risk 1.5");
    await expect(page.getByTestId("ideas-defaults")).toContainText("strategy-rules-v2");

    const t = page.getByTestId("ideas-considered-toggle");
    await expect(t).toHaveText(/Considered 14, selected 5, left out 2/);
    await expect(t).toHaveAttribute("aria-expanded", "false");
    await expect(page.getByTestId("ideas-considered")).toBeHidden();
    await t.click();
    await expect(t).toHaveAttribute("aria-expanded", "true");
    const ex = page.getByTestId("ideas-excluded");
    await expect(ex).toHaveCount(2);
    await expect(ex.nth(0)).toContainText("SMALLCO: Liquidity 3.2 Cr a day is below the 10 Cr floor");
    await expect(ex.nth(1)).toContainText("WEAKCO: Score 41 is below the minimum of 50");
    await expect(page.getByTestId("ideas-excluded-note")).toContainText("Only setups ranked above the last selected one are listed");
    await expect(page.getByTestId("ideas-gate")).toContainText("scan snapshot eligibility gates");
    const cv = page.getByTestId("ideas-caveats-toggle");
    await expect(cv).toHaveAttribute("aria-expanded", "false");
    await expect(page.getByTestId("ideas-caveats")).toBeHidden();
    await cv.click();
    await expect(page.getByTestId("ideas-caveats")).toContainText("Margin is not estimated");

    await expect(page.getByTestId("ideas-trust")).toHaveAttribute("data-mode", "eod");
    await expect(page.getByTestId("ideas-trust")).toContainText("rules strategy-rules-v2 · calculation payoff-v1");
    await expect(page.getByTestId("ideas-trust")).not.toContainText("Live");
    await expect(page.getByTestId("ideas-paper-note")).toContainText("Paper trade and save are in the full plan");
    await shot(page, "board", 1440);
  });

  // ── SI-3 ─────────────────────────────────────────────────────────────

  test("SI-3 the viable idea: header facts, three evidence lines, the OI view, strategies grouped by segment with the route's figures, the preferred row marked in text, non-viable rows without numbers", async ({ page }) => {
    await openBoard(page);
    await expect(page.getByTestId("ideas-view")).toBeVisible();
    const order = await page.locator('[data-testid^="idea-"][data-rank]').evaluateAll((els) => els.map((e) => e.getAttribute("data-symbol")));
    expect(order).toEqual(["ICICIBANK", "TATASTEEL", "RELIANCE", "AARTIDRUGS", "HINDALCO"]);

    const c = card(page, "ICICIBANK");
    await expect(c.getByTestId("idea-symbol")).toHaveText("ICICIBANK");
    await expect(c.getByTestId("idea-name")).toHaveText("ICICI Bank Ltd");
    await expect(c.getByTestId("idea-scan-status")).toContainText("Confirmed");
    await expect(c.getByTestId("idea-score")).toHaveText("Score 86/100");
    await expect(c.getByTestId("idea-plan-status")).toContainText("Plan");
    await expect(c.getByTestId("idea-plan-status")).toHaveAttribute("data-status", "plan");
    await expect(c.getByTestId("idea-setup")).toHaveText("Setup: Breakout confirmed");
    await expect(c.getByTestId("idea-close")).toContainText("Scan close: ₹1,200.00 on 19 Oct 2026");
    await expect(c.getByTestId("idea-liquidity")).toContainText("₹812 Cr/day");
    await expect(c.getByTestId("idea-risk")).toContainText("ATR 1.7% of price");
    await expect(c.getByTestId("idea-reasons")).toContainText("The breakout closed above its 20-session high on volume.");
    await expect(c.getByTestId("idea-would-change")).toContainText("A close below 1,160");
    await expect(c.getByTestId("idea-trust")).toContainText("End of day");

    // Evidence at a glance, from evidence_summary counts and oi_view.
    await expect(c.getByTestId("idea-ev-technical")).toContainText("5 support · 1 conflict · 1 neutral · 0 unavailable");
    await expect(c.getByTestId("idea-ev-fundamental")).toContainText("3 support · 2 conflict · 0 neutral · 2 unavailable");
    const oi = c.getByTestId("idea-ev-oi");
    for (const t of ["build-up long_buildup", "cash confirmation confirmed", "PCR 1.12", "call wall 1,250.00", "put wall 1,150.00", "max pain 1,200.00", "as of 19 Oct 2026"]) await expect(oi).toContainText(t);

    // Segments in the order cash, futures, options, combination.
    const segs = await c.locator('[data-testid^="idea-seg-"]').evaluateAll((els) => els.map((e) => e.getAttribute("data-testid")));
    expect(segs).toEqual(["idea-seg-cash", "idea-seg-futures", "idea-seg-options", "idea-seg-combination"]);
    const row = (id: string) => c.getByTestId(`idea-strat-${id}`);

    const cash = row("cash:breakout_continuation");
    await expect(cash.getByTestId("idea-strat-status")).toContainText("Viable");
    await expect(cash.getByTestId("idea-strat-legs")).toHaveText("Buy 208 shares at 1,200.00");
    await expect(cash.getByTestId("idea-strat-maxloss")).toContainText("₹8,320.00");
    await expect(cash.getByTestId("idea-strat-maxloss")).toContainText("loss at the stop (net); gaps can exceed it");
    await expect(cash.getByTestId("idea-strat-capital")).toHaveText("₹2,49,600.00");
    await expect(cash.getByTestId("idea-strat-maxprofit")).toHaveText("₹16,640.00");
    await expect(cash.getByTestId("idea-strat-breakeven")).toHaveText("1,200.00");
    await expect(cash.getByTestId("idea-strat-rr")).toContainText("1.90 : 1 net");
    await expect(cash.getByTestId("idea-strat-rr")).toContainText("2.00 : 1 gross");
    await expect(cash.getByTestId("idea-strat-sizing")).toContainText("208 shares");
    await expect(cash.getByTestId("idea-strat-sizing")).toContainText("limited by max allocation");
    await expect(cash.getByTestId("idea-strat-flags")).toHaveText("None flagged");
    await expect(cash.getByTestId("idea-preferred")).toHaveCount(0);

    const fut = row("futures:long_buildup_continuation");
    await expect(fut.getByTestId("idea-strat-maxloss")).toContainText("₹13,250.00");
    await expect(fut.getByTestId("idea-strat-maxprofit")).toHaveText("Unlimited");
    await expect(fut.getByTestId("idea-strat-sizing")).toContainText("1 lot (250 units)");
    await expect(fut.getByTestId("idea-strat-flags")).toContainText("Futures loss can exceed margin");

    const spread = row("options:bull_call_spread");
    await expect(spread).toHaveAttribute("data-preferred", "true");
    await expect(spread.getByTestId("idea-preferred")).toHaveText("★ Preferred strategy");
    await expect(spread.getByTestId("idea-strat-legs")).toContainText("Buy 1,200 call at 52.00; sell 1,250 call at 38.00");
    await expect(spread.getByTestId("idea-strat-maxloss")).toContainText("₹7,000.00");
    await expect(spread.getByTestId("idea-strat-maxloss")).toContainText("defined max loss at expiry (net)");
    await expect(spread.getByTestId("idea-strat-maxprofit")).toHaveText("₹18,000.00");
    await expect(spread.getByTestId("idea-strat-breakeven")).toHaveText("1,214.00");
    await expect(spread.getByTestId("idea-strat-sizing")).toContainText("2 lots (500 units)");
    await expect(spread.getByTestId("idea-strat-flags")).toContainText("Thin open interest at the 1,250 strike");

    const pp = row("combination:protective_put");
    await expect(pp.getByTestId("idea-strat-maxloss")).toContainText("₹15,000.00");
    await expect(pp.getByTestId("idea-strat-maxprofit")).toHaveText("Unlimited");
    await expect(pp.getByTestId("idea-strat-breakeven")).toHaveText("1,220.00");
    await expect(pp.getByTestId("idea-strat-rr")).toContainText("— net");

    // A strategy that is not viable shows its reasons and "—", never a number (the payload carries decoys).
    for (const [id, reason] of [["options:long_call", "One lot's premium is above the risk budget"], ["combination:collar", "call wall leaves little room above the entry"]] as const) {
      const r = row(id);
      await expect(r.getByTestId("idea-strat-reasons")).toContainText(reason);
      for (const k of ["maxloss", "capital", "maxprofit", "breakeven", "rr", "sizing", "flags"]) await expect(r.getByTestId(`idea-strat-${k}`)).toHaveText("—");
    }
    await expect(row("options:long_call")).not.toContainText(/99,?999|88,?888|7,?777/);
    await expect(row("options:long_call").getByTestId("idea-strat-status")).toContainText("No trade");
    await expect(row("combination:collar").getByTestId("idea-strat-status")).toContainText("Wait");
    await expect(row("options:long_call").getByTestId("idea-open-strategy")).toHaveCount(0);
    await expect(row("combination:collar").getByTestId("idea-open-strategy")).toHaveCount(1);
    await expect(c.getByTestId("idea-strategy-table").locator("th[scope=rowgroup]")).toHaveText(["Cash", "Futures", "Options", "Combination"]);
    await shot(page, "viable", 1440);
  });

  // ── SI-4 ─────────────────────────────────────────────────────────────

  test("SI-4 wait, no trade (event inside the horizon), cash-only (not in F&O) and insufficient-data ideas each say so, with word and shape", async ({ page }) => {
    await openBoard(page);
    const wait = card(page, "TATASTEEL");
    await expect(wait.getByTestId("idea-plan-status")).toContainText("Wait for confirmation");
    await expect(wait.getByTestId("idea-plan-status")).toContainText("◔");
    await expect(wait.getByTestId("idea-scan-status")).toContainText("Awaiting");
    await expect(wait.getByTestId("idea-reasons")).toContainText("Price has not closed above the 160.00 trigger yet.");
    await expect(wait.getByTestId("idea-would-change")).toContainText("A close above 160.00 on above-average volume");
    await expect(wait.getByTestId("idea-strat-cash:breakout_watch").getByTestId("idea-strat-maxloss")).toHaveText("—");
    await expect(wait.getByTestId("idea-strat-cash:breakout_watch").getByTestId("idea-strat-reasons")).toContainText("Enter only after a close above 160.00");
    // Missing OI fields are "—", not a number.
    const oi = wait.getByTestId("idea-ev-oi");
    await expect(oi).toContainText("build-up short_covering");
    await expect(oi).toContainText("cash confirmation —");
    await expect(oi).toContainText("PCR —");
    await expect(oi).toContainText("call wall —");
    await expect(oi).toContainText("put wall 150.00");
    await expect(wait.getByTestId("idea-preferred")).toHaveCount(0);

    const no = card(page, "RELIANCE");
    await expect(no.getByTestId("idea-plan-status")).toContainText("No trade");
    await expect(no.getByTestId("idea-plan-status")).toContainText("✕");
    await expect(no.getByTestId("idea-reasons")).toContainText("Results on 23 Oct 2026 fall inside the 10-session horizon.");
    await expect(no.getByTestId("idea-strat-cash:breakout_continuation").getByTestId("idea-strat-maxloss")).toHaveText("—");
    await expect(no).not.toContainText("4,444");
    await expect(no.getByTestId("idea-strat-futures:long_buildup_continuation").getByTestId("idea-strat-status")).toContainText("Avoid");

    const cashOnly = card(page, "AARTIDRUGS");
    await expect(cashOnly.getByTestId("idea-not-fno")).toContainText("No futures and options for this stock");
    await expect(cashOnly.getByTestId("idea-not-fno")).toContainText("not in the NSE F&O segment");
    await expect(cashOnly.getByTestId("idea-strat-futures:none")).toHaveCount(0);
    await expect(cashOnly.getByTestId("idea-strat-options:none")).toHaveCount(0);
    await expect(cashOnly.locator('[data-testid^="idea-seg-"]')).toHaveCount(1);
    await expect(cashOnly.getByTestId("idea-seg-cash")).toBeVisible();
    await expect(cashOnly.getByTestId("idea-ev-oi")).toContainText("no futures and options for this stock, so no open-interest view");
    await expect(cashOnly.getByTestId("idea-name")).toHaveText("—");
    await expect(cashOnly.getByTestId("idea-preferred")).toHaveCount(1);
    await expect(cashOnly.getByTestId("idea-risk")).toContainText("ATR 4.6% of price");

    const none = card(page, "HINDALCO");
    await expect(none.getByTestId("idea-plan-status")).toContainText("Insufficient data");
    await expect(none.getByTestId("idea-reasons")).toContainText("Fewer than 60 sessions");
    await expect(none.getByTestId("idea-no-strategies")).toContainText("No strategy was built");
    await expect(none.getByTestId("idea-strategy-table")).toHaveCount(0);
    await expect(none.getByTestId("idea-risk")).toContainText("Risk: —");
    await expect(none.getByTestId("idea-liquidity")).toContainText("Liquidity: —");
    await expect(none.getByTestId("idea-ev-oi")).toContainText("the F&O data gave no open-interest view");
    await expect(page.getByTestId("ideas-partial")).toHaveText("1 of 5 ideas have insufficient data, so no strategy is built for them. The others are unaffected.");
    await shot(page, "states", 1440);
  });

  // ── SI-5 ─────────────────────────────────────────────────────────────

  test("SI-5 the inputs: the request carries what was typed and nothing else, the browser checks the limits, the route's 422 problems land on their fields, and the previous board stays while it rebuilds", async ({ page }) => {
    const st = await openBoard(page);
    await expect(page.getByTestId("ideas-view")).toBeVisible();
    await page.getByTestId("ideas-in-capital").fill("10,00,000");
    await page.getByTestId("ideas-in-risk").fill("10000");
    await page.getByTestId("ideas-in-alloc").fill("25");
    await page.getByTestId("ideas-in-minrr").fill("1.5");
    await page.getByTestId("ideas-in-avoid-events").uncheck();
    await page.getByTestId("ideas-in-combos").uncheck();
    await page.getByTestId("build-ideas").click();
    await expect.poll(() => st.ideas.length).toBe(2);
    expect(st.ideas[1]).toEqual({ limit: 8, capital: 1000000, risk_budget_inr: 10000, max_allocation_pct: 25, min_reward_risk: 1.5, avoid_events: false, include_combinations: false });

    await page.getByTestId("ideas-risk-mode-pct").click();
    await page.getByTestId("ideas-in-risk").fill("1");
    await page.getByTestId("build-ideas").click();
    await expect.poll(() => st.ideas.length).toBe(3);
    expect(st.ideas[2]).toMatchObject({ risk_pct: 1 });
    expect(st.ideas[2]).not.toHaveProperty("risk_budget_inr");

    await page.getByTestId("ideas-in-risk").fill("150");
    await page.getByTestId("ideas-in-alloc").fill("0");
    await page.getByTestId("build-ideas").click();
    await expect(page.getByTestId("field-risk").getByTestId("problem-risk")).toContainText("at most 100");
    await expect(page.getByTestId("field-max_allocation_pct").getByTestId("problem-max_allocation_pct")).toBeVisible();
    expect(st.ideas).toHaveLength(3);

    // The route's own refusal, per field.
    const body = { detail: { code: "invalid_input", problems: [{ field: "min_reward_risk", code: "bad_min_reward_risk", message: "min_reward_risk must be a number above 0 and at most 100." }, { field: "limit", code: "bad_limit", message: "limit must be between 1 and 15." }] } };
    await page.unroute("**/api/desk/strategy/ideas");
    await page.route("**/api/desk/strategy/ideas", (r) => json(r, body, 422));
    await page.getByTestId("ideas-in-risk").fill("");
    await page.getByTestId("ideas-in-alloc").fill("");
    await page.getByTestId("build-ideas").click();
    await expect(page.getByTestId("problem-min_reward_risk")).toContainText("above 0 and at most 100");
    await expect(page.getByTestId("ideas-problems-other")).toContainText("limit must be between 1 and 15");
    await expect(page.getByTestId("ideas-error")).toHaveCount(0);

    // While a rebuild is in flight the earlier board stays on screen.
    await page.unroute("**/api/desk/strategy/ideas");
    let release: () => void = () => {};
    const gate = new Promise<void>((res) => { release = res; });
    await page.route("**/api/desk/strategy/ideas", async (r) => { await gate; await json(r, ideasBody()); });
    await page.getByTestId("ideas-in-minrr").fill("");
    await page.getByTestId("build-ideas").click();
    await expect(page.getByTestId("build-ideas")).toBeDisabled();
    release();
    await expect(page.getByTestId("ideas-view")).toBeVisible();
    await expect(card(page, "ICICIBANK")).toBeVisible();
  });

  test("SI-5b the previous board stays on screen while a new one loads", async ({ page }) => {
    await openBoard(page);
    await expect(card(page, "ICICIBANK")).toBeVisible();
    await page.unroute("**/api/desk/strategy/ideas");
    let release: () => void = () => {};
    const gate = new Promise<void>((res) => { release = res; });
    await page.route("**/api/desk/strategy/ideas", async (r) => { await gate; await json(r, ideasBody({ ideas: [{ ...ICICI, rank: 1, symbol: "NEWONE" }] })); });
    await page.getByTestId("build-ideas").click();
    await expect(page.getByTestId("ideas-updating")).toBeVisible();
    await expect(card(page, "ICICIBANK")).toBeVisible();
    await expect(page.getByTestId("ideas-view")).toHaveAttribute("aria-busy", "true");
    release();
    await expect(card(page, "NEWONE")).toBeVisible();
    await expect(card(page, "ICICIBANK")).toHaveCount(0);
  });

  // ── SI-6 ─────────────────────────────────────────────────────────────

  test("SI-6 Open full plan goes to One stock with the idea's inputs, build=1 and the source in the URL, builds once, and says where it started; Open this strategy also selects that candidate", async ({ page }) => {
    const st = await openBoard(page);
    await card(page, "ICICIBANK").getByTestId("idea-open-plan").click();
    await expect(page.getByTestId("plan-view")).toBeVisible();
    let q = new URL(page.url()).searchParams;
    expect(Object.fromEntries(q)).toMatchObject({
      tab: "trade", view: "new", mode: "stock", sym: "ICICIBANK", // was more/strategy before the 2026-10-27 redesign direction: "bullish", instrument: "all", build: "1",
      src_kind: "ideas", src_bucket: "breakout_confirmed", src_date: "2026-10-19", capital: "1000000", risk_inr: "10000", max_alloc: "25", min_rr: "1.5",
      avoid_events: "true", multi_leg: "true", combos: "true",
    });
    expect(q.has("cand")).toBe(false);
    expect(st.builds).toHaveLength(1);
    expect(st.builds[0]).toEqual({
      underlying: "ICICIBANK", direction: "bullish", instrument: "all", capital: 1000000, risk_budget_inr: 10000,
      max_allocation_pct: 25, min_reward_risk: 1.5, avoid_events: true, allow_multi_leg: true, include_combinations: true,
    });
    await expect(page.getByTestId("builder-source")).toHaveText("Started from the AI opportunities: breakout confirmed, scan 19 Oct 2026");
    await expect(page.getByTestId("builder-mode-stock")).toHaveAttribute("aria-pressed", "true");
    await expect(page.getByTestId("in-capital")).toHaveValue("1000000");
    // The plan opens on its own preferred candidate when none was asked for.
    await expect(page.getByTestId("cmp-row-options:bull_call_spread")).toHaveAttribute("data-selected", "true");
    await shot(page, "full-plan", 1440);

    // Back to the board, then one strategy: the candidate is selected and the cand param is spent.
    await page.getByTestId("builder-mode-ideas").click();
    await expect(page.getByTestId("ideas-view")).toBeVisible();
    await card(page, "ICICIBANK").getByTestId("idea-strat-futures:long_buildup_continuation").getByTestId("idea-open-strategy").click();
    await expect(page.getByTestId("plan-view")).toBeVisible();
    q = new URL(page.url()).searchParams;
    expect(q.get("mode")).toBe("stock");
    expect(q.get("sym")).toBe("ICICIBANK");
    expect(q.get("build")).toBe("1");
    expect(q.get("src_kind")).toBe("ideas");
    await expect(page.getByTestId("cmp-row-futures:long_buildup_continuation")).toHaveAttribute("data-selected", "true");
    await expect(page.getByTestId("cmp-row-options:bull_call_spread")).toHaveAttribute("data-selected", "false");
    expect(st.builds).toHaveLength(2);

    // A link with cand= opens straight to that candidate.
    await page.goto(`${IDEAS}&mode=stock&sym=ICICIBANK&direction=bullish&instrument=all&build=1&cand=cash:breakout_continuation&src_kind=ideas&src_bucket=breakout_confirmed&src_date=2026-10-19`);
    await expect(page.getByTestId("cmp-row-cash:breakout_continuation")).toHaveAttribute("data-selected", "true");
    // Opening a not-F&O idea carries the same inputs (the plan itself drops the F&O segments).
    await page.getByTestId("builder-mode-ideas").click();
    await card(page, "AARTIDRUGS").getByTestId("idea-open-plan").click();
    await expect(page.getByTestId("plan-view")).toBeVisible();
    expect(new URL(page.url()).searchParams.get("instrument")).toBe("all");
    expect(new URL(page.url()).searchParams.get("src_bucket")).toBe("trend_continuation");
    expect(st.writes).toEqual([]);
  });

  test("SI-6b Add to watchlist is the existing control and writes nothing until used (the Scanner's own Build a strategy is covered by SP-10)", async ({ page }) => {
    const st = await openBoard(page);
    await expect(card(page, "ICICIBANK").getByTestId("watchlist-add-to-list")).toBeVisible();
    await card(page, "ICICIBANK").getByTestId("watchlist-add-to-list").click();
    await expect(card(page, "ICICIBANK").getByTestId("watchlist-add-to-list-form")).toContainText("Add ICICIBANK to");
    expect(st.writes).toEqual([]);
  });

  // ── SI-7 ─────────────────────────────────────────────────────────────

  test("SI-7 the Overview's Top AI opportunities card links to the board (card and row), the row link scrolls to that idea", async ({ page }) => {
    const st = await setup(page);
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto(DESK);
    await expect(page.getByTestId("desk-opps-card")).toBeVisible();
    await expect(page.getByTestId("desk-opps-strategies")).toHaveText("Strategies for these ›");
    await page.getByTestId("desk-opps-strategies").click();
    await expect(page.getByTestId("strategy-ideas")).toBeVisible();
    let q = new URL(page.url()).searchParams;
    expect(q.get("tab")).toBe("trade"); // was more/strategy before the 2026-10-27 redesign
    expect(q.get("view")).toBe("new");
    expect(q.get("mode")).toBe("ideas");
    expect(q.has("focus")).toBe(false);
    await expect(page.getByTestId("ideas-view")).toBeVisible();
    expect(st.ideas).toHaveLength(1);

    await page.goto(DESK);
    const rowLink = page.locator('li:has([data-testid="desk-opp"][data-symbol="TESTBRK"])').getByTestId("desk-opp-strategies");
    await expect(rowLink).toHaveText("Strategies ›");
    await rowLink.click();
    await expect(page.getByTestId("strategy-ideas")).toBeVisible();
    q = new URL(page.url()).searchParams;
    expect(q.get("mode")).toBe("ideas");
    expect(q.get("focus")).toBe("TESTBRK");

    // The focus scrolls to that idea once the board is there.
    await page.goto(`${IDEAS}&mode=ideas&focus=HINDALCO`);
    await expect(card(page, "HINDALCO")).toBeInViewport();
  });

  test("SI-7b the phone Overview card has the same link", async ({ page }) => {
    await setup(page);
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto(DESK);
    await page.getByTestId("desk-top-opps-strategies").click();
    await expect(page.getByTestId("strategy-ideas")).toBeVisible();
    expect(new URL(page.url()).searchParams.get("mode")).toBe("ideas");
  });

  // ── SI-8 ─────────────────────────────────────────────────────────────

  test("SI-8a the scanner has no setups: the empty state says so with the selection reason, and no board of cards", async ({ page }) => {
    await openBoard(page, { reply: { status: 200, body: ideasBody({ ideas: [], selection: { source: "positional_watchlist", scan_date: "2026-10-19", rule: "No confirmed or awaiting setup passed the liquidity floor", considered: 6, selected: 0, excluded: [{ symbol: "SMALLCO", reason: "Liquidity below the floor" }], limit: 8 } }) } });
    const e = page.getByTestId("ideas-empty");
    await expect(e).toContainText("The scanner has no setups on its latest scan, so there is nothing to build strategies from");
    await expect(e).toContainText("No confirmed or awaiting setup passed the liquidity floor");
    await expect(page.locator('[data-testid^="idea-"][data-rank]')).toHaveCount(0);
    await page.getByTestId("ideas-considered-toggle").click();
    await expect(page.getByTestId("ideas-excluded")).toContainText("SMALLCO: Liquidity below the floor");
    await shot(page, "empty", 1440);
  });

  test("SI-8b a server error says so and Retry asks again; 401 asks to sign in; 403 says the account is not enabled", async ({ page }) => {
    const st = await openBoard(page, { reply: { status: 502, body: { detail: "scanner_unavailable" } } });
    const err = page.getByTestId("ideas-error");
    await expect(err).toContainText("The ideas were not built: the server could not finish (502");
    await expect(page.getByTestId("ideas-view")).toHaveCount(0);
    await shot(page, "error", 1440);
    await page.unroute("**/api/desk/strategy/ideas");
    await page.route("**/api/desk/strategy/ideas", (r) => { st.ideas.push({}); return json(r, ideasBody()); });
    await err.getByRole("button", { name: /retry|try again/i }).click();
    await expect(page.getByTestId("ideas-view")).toBeVisible();
    await expect(page.getByTestId("ideas-error")).toHaveCount(0);

    await page.unroute("**/api/desk/strategy/ideas");
    await page.route("**/api/desk/strategy/ideas", (r) => json(r, { detail: "not_authenticated" }, 401));
    await page.getByTestId("build-ideas").click();
    await expect(page.getByTestId("ideas-error")).toContainText("Sign in to see strategies for the AI opportunities");

    await page.unroute("**/api/desk/strategy/ideas");
    await page.route("**/api/desk/strategy/ideas", (r) => json(r, { detail: "feature_not_enabled" }, 403));
    await page.getByTestId("build-ideas").click();
    await expect(page.getByTestId("ideas-error")).toContainText("The Strategy Builder is not enabled for this account");
    await expect(page.getByTestId("ideas-error").getByRole("button", { name: /retry/i })).toHaveCount(0);
    await shot(page, "forbidden", 1440);
  });

  test("SI-8c an answer without the ideas list is a contract error, never an empty board", async ({ page }) => {
    const { ideas: _drop, ...noIdeas } = ideasBody();
    void _drop;
    await openBoard(page, { reply: { status: 200, body: noIdeas } });
    await expect(page.getByTestId("ideas-error")).toContainText("not in the expected form");
    await expect(page.getByTestId("ideas-empty")).toHaveCount(0);
    await expect(page.getByTestId("ideas-view")).toHaveCount(0);
  });

  test("SI-8d loading shows a loading block, not an empty board", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await setup(page);
    await page.unroute("**/api/desk/strategy/ideas");
    let release: () => void = () => {};
    const gate = new Promise<void>((res) => { release = res; });
    await page.route("**/api/desk/strategy/ideas", async (r) => { await gate; await json(r, ideasBody()); });
    await page.goto(IDEAS);
    await expect(page.getByRole("status", { name: /Picking the scanner's top setups/ })).toBeVisible();
    await expect(page.getByTestId("ideas-empty")).toHaveCount(0);
    await shot(page, "loading", 1440);
    release();
    await expect(page.getByTestId("ideas-view")).toBeVisible();
  });

  // ── SI-9 ─────────────────────────────────────────────────────────────

  test("SI-9a investor wording; the board has headings, disclosures and a keyboard-reachable table region", async ({ page }) => {
    await openBoard(page, {}, "&persona=investor");
    await expect(page.getByTestId("strategy-ideas")).toHaveAttribute("data-persona", "investor");
    await expect(page.getByTestId("ideas-title")).toContainText("top ideas");
    await expect(page.getByTestId("builder-mode-ideas")).toHaveText("From the AI's ideas");
    const c = card(page, "ICICIBANK");
    await expect(c.getByTestId("idea-plan-status")).toContainText("A plan is ready");
    await expect(c.getByTestId("idea-ev-technical")).toContainText("Price chart:");
    await expect(c.getByTestId("idea-ev-oi")).toContainText("Open interest:");
    await expect(c.getByRole("columnheader", { name: "Most you could lose" })).toBeVisible();
    await expect(c.getByTestId("idea-would-change")).toContainText("This could change if");
    await expect(page.getByRole("heading", { level: 1 })).toHaveCount(1);
    await expect(c.getByRole("heading", { level: 2 })).toHaveText("ICICIBANK");
    const region = c.getByRole("region", { name: /ICICIBANK strategies/ });
    await expect(region).toHaveAttribute("tabindex", "0");
    await expect(page.getByTestId("ideas-considered-toggle")).toHaveAttribute("aria-expanded", "false");
    await expect(page.getByTestId("ideas-considered-toggle")).toHaveAttribute("aria-controls", /.+/);
    await expect(page.getByTestId("ideas-defaults")).toBeVisible();
  });

  test("SI-9b no order, broker or trade control anywhere on the board", async ({ page }) => {
    const st = await openBoard(page);
    await expect(page.getByTestId("ideas-view")).toBeVisible();
    await expect(page.getByTestId("strategy-ideas").getByRole("button", { name: /place order|buy now|sell now|execute|send to broker|paper trade/i })).toHaveCount(0);
    await expect(page.getByTestId("strategy-ideas")).toContainText("Nivesh does not place orders");
    expect(st.writes).toEqual([]);
  });

  test("SI-9c 390px: the cards stack, each strategies table scrolls inside itself, the page does not scroll sideways", async ({ page }) => {
    await openBoard(page, {}, "", 390);
    await expect(page.getByTestId("ideas-view")).toBeVisible();
    const s = await sideways(page);
    expect(s.doc).toBeLessThanOrEqual(0);
    expect(s.scroll).toBeLessThanOrEqual(0);
    const region = card(page, "ICICIBANK").getByRole("region", { name: /ICICIBANK strategies/ });
    const dims = await region.evaluate((e) => ({ client: e.clientWidth, scroll: e.scrollWidth }));
    expect(dims.scroll).toBeGreaterThan(dims.client);
    const boxes = await page.locator('[data-testid^="idea-"][data-rank]').evaluateAll((els) => els.map((e) => e.getBoundingClientRect().width));
    for (const w of boxes) expect(w).toBeLessThanOrEqual(390);
    await page.getByTestId("ideas-considered-toggle").click();
    await shot(page, "board", 390);
    await card(page, "HINDALCO").scrollIntoViewIfNeeded();
    await shot(page, "states", 390);
    expect((await sideways(page)).doc).toBeLessThanOrEqual(0);
  });

  test("SI-9d 390px: the empty and error states fit too", async ({ page }) => {
    await openBoard(page, { reply: { status: 502, body: { detail: "x" } } }, "", 390);
    await expect(page.getByTestId("ideas-error")).toBeVisible();
    expect((await sideways(page)).doc).toBeLessThanOrEqual(0);
    await shot(page, "error", 390);
  });

  // ── SI-10 ────────────────────────────────────────────────────────────

  test("SI-10 the real captured response: scan older than prices, hedged and income rows with max loss beside reward : risk, pick-only setups, a non-F&O stock", async ({ page }) => {
    const real = JSON.parse(fs.readFileSync(path.join(__dirname, "..", "fixtures", "strategy-ideas-real.json"), "utf-8"));
    await openBoard(page, { reply: { status: 200, body: real } });
    await expect(page.getByTestId("ideas-view")).toBeVisible();
    const order = await page.locator('[data-testid^="idea-"][data-rank]').evaluateAll((els) => els.map((e) => e.getAttribute("data-symbol")));
    expect(order).toEqual(real.ideas.map((i: { symbol: string }) => i.symbol));
    expect(order).toHaveLength(8);

    await expect(page.getByTestId("ideas-asof")).toContainText("Scan 16 Oct 2026 · prices 19 Oct 2026 · F&O 19 Oct 2026");
    await expect(page.getByTestId("ideas-scan-older")).toContainText("The scan is older than the price data");
    await expect(page.getByTestId("ideas-ranking")).toContainText("not comparable with an unhedged one");
    await expect(page.getByTestId("ideas-considered-toggle")).toHaveText(/Considered 34, selected 8, left out 3/);
    await page.getByTestId("ideas-considered-toggle").click();
    await expect(page.getByTestId("ideas-excluded").first()).toContainText("RAJRILTD: 20-session traded value below Rs 10 crore a day");
    await expect(page.getByTestId("ideas-gate")).toContainText("scan snapshot eligibility gates");

    // HAL: a pick-only setup (no bucket, no ATR) and the covered call as the preferred strategy.
    const hal = card(page, "HAL");
    await expect(hal.getByTestId("idea-setup")).toContainText("(scanner pick)");
    await expect(hal.getByTestId("idea-scan-status")).toContainText("Confirmed");
    await expect(hal.getByTestId("idea-score")).toHaveText("Score 76/100");
    await expect(hal.getByTestId("idea-risk")).toContainText("— no ATR in the scanner's row");
    await expect(hal.getByTestId("idea-name")).toHaveText("Hindustan Aeronautics Limited");
    await expect(hal.getByTestId("idea-ev-oi")).toContainText("build-up short_buildup");
    await expect(hal.getByTestId("idea-ev-oi")).toContainText("call wall 5,400.00");
    await expect(hal.getByTestId("idea-ev-oi")).toContainText("ATM IV 29.66%");
    const cc = hal.getByTestId("idea-strat-combination:covered_call");
    await expect(cc).toHaveAttribute("data-preferred", "true");
    await expect(cc.getByTestId("idea-preferred")).toHaveText("★ Preferred strategy");
    await expect(cc.getByTestId("idea-strat-legs")).toHaveText("Buy 900 shares HAL + Sell 6 lots HAL 5400 call, 23 Nov");
    await expect(cc.getByTestId("idea-strat-maxloss")).toContainText("₹44,29,575.00");
    await expect(cc.getByTestId("idea-strat-maxloss")).toContainText("falls to the long put's strike, or to zero without a put");
    await expect(cc.getByTestId("idea-strat-capital")).toHaveText("₹44,31,903.31");
    await expect(cc.getByTestId("idea-strat-rr")).toContainText("2.92 : 1 net");
    await expect(cc.getByTestId("idea-strat-rr")).toContainText("3.12 : 1 gross");
    await expect(cc.getByTestId("idea-strat-maxprofit")).toHaveText("₹4,30,425.00");
    await expect(cc.getByTestId("idea-strat-breakeven")).toHaveText("4,921.75");
    await expect(cc.getByTestId("idea-strat-sizing")).toContainText("6 lots (900 units)");
    // The ratio sits in the same row, between capital at risk and max profit, so it is never read alone.
    const cells = await cc.locator("td").evaluateAll((els) => els.map((e) => e.getAttribute("data-testid")));
    expect(cells.indexOf("idea-strat-maxloss")).toBeLessThan(cells.indexOf("idea-strat-rr"));
    expect(cells.indexOf("idea-strat-capital")).toBeLessThan(cells.indexOf("idea-strat-rr"));
    const cash = hal.getByTestId("idea-strat-cash:breakout_continuation");
    await expect(cash.getByTestId("idea-strat-maxloss")).toContainText("₹1,42,813.75");
    await expect(cash.getByTestId("idea-strat-capital")).toHaveText("₹50,01,211.34");
    await expect(cash.getByTestId("idea-strat-sizing")).toContainText("1,008 shares");
    await expect(cash.getByTestId("idea-strat-rr")).toContainText("1.89 : 1 net");
    await expect(hal.getByTestId("idea-strat-futures:long_buildup_continuation").getByTestId("idea-strat-reasons")).toContainText("the opposite of the bullish view");
    await expect(hal.getByTestId("idea-strat-combination:protective_put").getByTestId("idea-strat-maxloss")).toHaveText("—");
    // A strategy that is not viable carries figures in the payload (a no-trade long call has a max loss): none is shown.
    const lc = card(page, "ICICIBANK").getByTestId("idea-strat-options:long_call");
    await expect(lc.getByTestId("idea-strat-status")).toContainText("No trade");
    await expect(lc.getByTestId("idea-strat-maxloss")).toHaveText("—");
    await expect(lc).not.toContainText("1,83,750");

    // PREMEXPLN: not in F&O, so one sentence and the cash row only.
    const pre = card(page, "PREMEXPLN");
    await expect(pre.getByTestId("idea-not-fno")).toContainText("No futures and options for this stock: The stock is not in the NSE F&O segment");
    await expect(pre.locator('[data-testid^="idea-seg-"]')).toHaveCount(1);
    await expect(pre.getByTestId("idea-strat-futures:none")).toHaveCount(0);
    await expect(pre.getByTestId("idea-strat-cash:pullback_in_uptrend").getByTestId("idea-strat-sizing")).toContainText("6,637 shares");
    await expect(pre.getByTestId("idea-ev-oi")).toContainText("no futures and options for this stock, so no open-interest view");
    await expect(pre.getByTestId("idea-ev-oi")).toContainText("PREMEXPLN has no futures row on 2026-10-19");
    await expect(pre.getByTestId("idea-risk")).toContainText("ATR 1.2% of price");

    // An event inside the horizon: no trade, with the route's words.
    const ind = card(page, "INDHOTEL");
    await expect(ind.getByTestId("idea-plan-status")).toContainText("No trade");
    await expect(ind.getByTestId("idea-reasons")).toContainText("Results are scheduled on 2026-10-21, inside the 10-day horizon");
    await expect(ind.locator('[data-testid="idea-open-strategy"]')).toHaveCount(0);
    await expect(page.getByRole("button", { name: /place order|execute|send to broker/i })).toHaveCount(0);
    await shot(page, "real", 1440);
  });
});
