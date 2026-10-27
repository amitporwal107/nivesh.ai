/**
 * One-screen Copilot app (/v5/app) — Smart trading desk: the shell.
 *
 * MOCK — not real data: every /api response here is a fixture or an inline
 * payload in the shape the real route returns (source named beside each), with
 * synthetic values. Expected figures are worked out from the payload, not
 * copied from the screen. Mocked APIs, production build — see
 * pw.copilot-app.config.ts.
 *
 * Covers screens/TradingDesk.tsx, screens/tradingdesk/CopilotDock.tsx and
 * screens/tradingdesk/BottomBar.tsx: an unknown ?tab=; the docked Copilot from
 * 1400px (asked in the desk's persona with surface "trading_desk", its own
 * thread) and the page Copilot below that; a failed answer; the phone's bottom
 * bar and search; and the header search. The old Overview cases (OverviewTab.tsx:
 * its headline, index row, pulse, sector card, "Data as of" line, the phone's M1
 * Overview and their screenshots) were removed with that tab in the desk
 * redesign's step 6; the header's market-status pill states moved to
 * copilot-app-desk-market-overview.spec.ts MO-32. The tabs, views and redirects
 * are in copilot-app-desk-shell.spec.ts; each tab's blocks in copilot-app-desk-*.spec.ts.
 */
import { test, expect, type Page, type Route } from "@playwright/test";
import { mockApi, mockSingleRoute } from "../helpers/api-mock";

const APP = "/v5/app";
const DESK = `${APP}/trader/desk`;

const json = (route: Route, body: unknown, status = 200) =>
  route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });

// Shapes: backend/routes/positional.py (get_watchlist, get_picks). Two setups have confirmed (a breakout_confirmed
// bucket, and a pick at stage BREAKOUT); one is awaiting (pre_breakout).
const WATCHLIST = { as_of_date: "2026-10-12", buckets: {
  breakout_confirmed: [{ nse_symbol: "TESTBRK", sector: "Capital Goods", close_price: 510.0, trigger_price: 500.0, stop_price: 477.5, atr_pct: 2.94, why: "Fixture reason" }],
  pre_breakout: [{ nse_symbol: "TESTPRE", sector: "Chemicals", close_price: 98.0, trigger_price: 100.0, stop_price: 93.0, atr_pct: 3.1, why: "Fixture coil" }],
  true_accumulation: [], trend_continuation: [] } };
const PICKS = { signal_date: "2026-10-12", count: 1, picks: [{ nse_symbol: "TESTPICK", signal_date: "2026-10-12", final_score: 0.812, confidence: "HIGH", stage: "BREAKOUT", timeframe_days_min: 5, timeframe_days_max: 15, entry_price: 505.0, stoploss: 480.0, target_price: 555.0, risk_reward: 2.0, source_scans: ["btst.breakout_confirmation"], reasons: ["Fixture scanner reason"] }] };

type Frame = Record<string, unknown> & { type: string };
const sse = (frames: Frame[]) => frames.map((f) => `data: ${JSON.stringify(f)}\n\n`).join("");
const ANSWER = "Breadth is narrow and FII selling continued.";
const FRAMES: Frame[] = [
  { type: "route", agent: "market_analyst", confidence: 0.9 },
  { type: "token", content: "Breadth is narrow " },
  { type: "token", content: "and FII selling continued." },
  { type: "done", content: ANSWER, follow_ups: [] },
];

interface ChatMock { streams: Array<{ message: string; session_id?: string; persona?: string; surface?: string }>; created: number }

/**
 * Chat routes, stateful like the real backend: a stream saves the question and the answer to that
 * thread, so the reload after the stream returns them (backend/routes/chat.py).
 */
async function mockChat(page: Page, opts: { streamStatus?: number } = {}): Promise<ChatMock> {
  const state: ChatMock = { streams: [], created: 0 };
  const messages: Record<string, Array<Record<string, unknown>>> = {};
  const sessions: Array<{ session_id: string; title: string; updated_at: string }> = [];
  await page.route("**/api/chat/sessions", (route) => {
    if (route.request().method() === "POST") {
      state.created += 1;
      const id = `desk${state.created}`;
      sessions.unshift({ session_id: id, title: "New conversation", updated_at: new Date().toISOString() });
      messages[id] = [];
      return json(route, { session_id: id, id });
    }
    return json(route, sessions);
  });
  await page.route("**/api/chat/messages*", (route) => json(route, messages[new URL(route.request().url()).searchParams.get("session_id") ?? ""] ?? []));
  await page.route("**/api/chat/suggest-queries*", (route) => json(route, { suggestions: [] }));
  await page.route("**/api/chat/stream", (route) => {
    const body = route.request().postDataJSON() as { message: string; session_id?: string; persona?: string; surface?: string };
    state.streams.push(body);
    if (opts.streamStatus) return json(route, { detail: "fixture failure" }, opts.streamStatus);
    const sid = body.session_id ?? "desk1";
    const now = new Date().toISOString();
    const n = state.streams.length;
    (messages[sid] ??= []).push(
      { message_id: `u${n}`, session_id: sid, role: "user", content: body.message, created_at: now },
      { message_id: `a${n}`, session_id: sid, role: "assistant", content: ANSWER, created_at: now },
    );
    return route.fulfill({ status: 200, contentType: "text/event-stream", body: sse(FRAMES) });
  });
  return state;
}

/** Everything the desk and its tabs read on open. Routes a tab reads and this does not list fail offline, which the shell does not depend on. */
async function deskApi(page: Page) {
  await mockApi(page, "populated");
  await mockSingleRoute(page, "**/api/markets/home", "markets-home.json");
  await page.route("**/api/positional/watchlist*", (route) => json(route, WATCHLIST));
  await page.route("**/api/positional/picks*", (route) => json(route, PICKS));
  // backend/routes/move_odds.py: an account not on the move_odds allowlist.
  await page.route("**/api/move-odds/**", (route) => json(route, { detail: "feature_not_enabled" }, 403));
  // The desk's own reads (backend/routes/markets_desk.py, desk_trading.py, portfolio_desk.py, fno.py), empty or minimal:
  // the shell does not depend on them; each tab's spec checks their figures.
  await page.route("**/api/markets/sector-returns", (route) => json(route, { as_of: "2026-10-13", source: "NSE index close (nidp.index_eod)", sessions: { "1d": 1, "1w": 5, "1m": 21 }, sectors: [] }));
  await page.route("**/api/desk/paper-trades*", (route) => json(route, { as_of: null, checked_through: null, marks_error: null, trades: [], summary: { open: 0, closed: 0, wins: 0, losses: 0, realized_pnl_rs: null, unrealized_pnl_rs: null, unmarked_open: 0, partial: false } }));
  await page.route("**/api/desk/alerts*", (route) => json(route, { as_of: null, checked_through: null, marks_error: null, alerts: [] }));
}

// ── richer Overview payloads (MOCK — not real data) ─────────────────────

// backend/routes/markets.py :: markets_home — the desk's four index tiles, breadth over the bhavcopy, flows, rupee, Brent.
const HOME = {
  ok: true, as_of: "2026-10-13", is_live: false, market_state: "closed", fetched_at: "2026-10-13T10:05:00+00:00",
  verdict: "CAUTIOUS", verdict_reason: "Fixture: weak breadth (41% above 20EMA) — wait for confirmation",
  indices: [
    { name: "Nifty 50", value: 25123.45, change: 120.5, change_pct: 0.48, is_vix: false, trend: null, spark: [24900, 24950.5, 25010, 25002.95, 25123.45] },
    { name: "Nifty Bank", value: 56000, change: 210, change_pct: 0.38, is_vix: false, trend: null, spark: [55600, 55790, 56000] },
    { name: "Sensex", value: 82010.1, change: -150.25, change_pct: -0.18, is_vix: false, trend: null, spark: [82300, 82160.35, 82010.1] },
    { name: "India VIX", value: 11.82, change: -0.31, change_pct: -2.56, is_vix: true, trend: "FALLING", spark: [12.4, 12.13, 11.82] },
  ],
  breadth: { advances: 2428, declines: 1142, unchanged: 72, universe: 3642, universe_kind: "bhavcopy", tone: "POSITIVE" },
  gainers: [], losers: [], movers_as_of: null, sectors: [],
  fii_dii: { as_of: "2026-10-13", fii_net_cr: -1523.4, dii_net_cr: 2210.75 },
  news: [],
  global_cues: [
    { name: "USD / INR", sub: "spot", value: 84.12, change_pct: 0.11, region: null, unit: null, featured: false },
    { name: "Brent Crude", sub: "$/bbl", value: 63.4, change_pct: -1.25, region: null, unit: null, featured: false },
  ],
  global_indices: { us: [], europe: [], asia: [] },
  commodities: [],
};
// backend/routes/macro.py :: macro_today, with `regime` from services/macro_engine.py :: classify_desk_regime.
// Nifty 25,100 vs its 50-day average 25,000 (up), India VIX 12.4 (< 20), breadth 2,428 up / 1,142 down = 68.0% (≥ 52%: up) → bullish.
const RULE = { version: "desk-regime-v1", vix_high: 20.0, trend_average_sessions: 50, breadth_up_pct: 52.0, breadth_down_pct: 48.0 };
const MACRO = {
  date: "2026-10-13", market_open_today: false, is_holiday_view: true, days_stale: 1, market: "BULL", inflation: "STABLE", liquidity: "EASY",
  risk: "LOW", multiplier: 1.1, insight: "Fixture insight: the trend is intact and risk gauges are quiet.", values: {}, features: {}, sources: {},
  regime: {
    key: "bullish", label: "Bullish", date: "2026-10-13", rule: RULE,
    inputs: { nifty_close: 25100.0, nifty_average: 25000.0, nifty_vs_average_pct: 0.4, trend: "up", india_vix: 12.4, volatility_high: false,
      advances: 2428, declines: 1142, unchanged: 72, breadth_universe: 3642, advancing_share_pct: 68.0, breadth: "up", breadth_date: "2026-10-13",
      breadth_source: "stock_ohlcv end-of-day bars (NSE bhavcopy)" },
    skipped: [],
    invalidation: [
      { input: "nifty_close", condition: "below", level: 25000.0, then: "mixed" },
      { input: "india_vix", condition: "at_or_above", level: 20.0, then: "high_volatility" },
      { input: "advancing_share_pct", condition: "at_or_below", level: 48.0, then: "mixed" },
    ],
    reason: null,
  },
};
// backend/routes/markets_desk.py :: sector_returns.
const SECTORS = {
  as_of: "2026-10-13", source: "NSE index close (nidp.index_eod)", sessions: { "1d": 1, "1w": 5, "1m": 21 },
  sectors: [
    { index: "Nifty Bank", sector: "Banks", date: "2026-10-13", close: 56000.0, ret_1d_pct: 0.3, ret_1w_pct: 1.9, ret_1m_pct: -2.2 },
    { index: "Nifty IT", sector: "IT", date: "2026-10-13", close: 35210.5, ret_1d_pct: 1.42, ret_1w_pct: -0.8, ret_1m_pct: 3.1 },
    { index: "Nifty Metal", sector: "Metals", date: "2026-10-13", close: 9100.25, ret_1d_pct: -0.85, ret_1w_pct: 2.6, ret_1m_pct: null },
    { index: "Nifty PSU Bank", sector: "PSU Banks", date: "2026-10-13", close: 7010.0, ret_1d_pct: 0.95, ret_1w_pct: -1.4, ret_1m_pct: 0.5 },
    { index: "Nifty Realty", sector: "Realty", date: "2026-10-13", close: 980.4, ret_1d_pct: -1.6, ret_1w_pct: -3.05, ret_1m_pct: 4.4 },
    { index: "Nifty Pharma", sector: "Pharma", date: "2026-10-13", close: 22010.0, ret_1d_pct: 0.12, ret_1w_pct: 0.4, ret_1m_pct: 1.2 },
  ],
};

/** The shell's mocks plus the Overview's own reads with figures in them. */
async function overviewApi(page: Page) {
  await deskApi(page);
  await page.route("**/api/markets/home", (route) => json(route, HOME));
  await page.route("**/api/macro/today", (route) => json(route, MACRO));
  await page.route("**/api/markets/sector-returns", (route) => json(route, SECTORS));
  await page.route("**/api/positional/market-dashboard", (route) => json(route, { ok: false, error: "fixture: no leaders" }));
}

const desk = (page: Page) => page.getByTestId("screen-trading-desk");

test.describe("Smart trading desk — shell", () => {
  test.beforeEach(async ({ page }) => {
    await deskApi(page);
  });

  test("TC-3: an unknown ?tab= opens the Overview", async ({ page }) => {
    await mockChat(page);
    await page.goto(`${DESK}?tab=zzz`);
    await expect(desk(page)).toHaveAttribute("data-tab", "overview");
    await expect(page.getByTestId("desk-tab-overview")).toHaveAttribute("aria-selected", "true");
    await expect(page.getByTestId("desk-panel-overview")).toHaveCount(1);
  });

  test("TC-4: from 1400px the Copilot is docked (design §9), the shell ask box is hidden, and questions go in the desk's persona", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    const chat = await mockChat(page);
    await page.goto(DESK);

    const dock = page.getByTestId("desk-dock");
    await expect(dock).toBeVisible();
    await expect(dock).toHaveAttribute("data-variant", "dock");
    await expect(page.getByTestId("desk-docked-note")).toHaveText("Copilot docked right");
    await expect(page.getByTestId("composer-input")).toHaveCount(0);
    // Design §9: the card header, the composer, a 384px column, no taller than 820px.
    const header = page.getByTestId("dock-header");
    await expect(header).toContainText("Nivesh Copilot");
    await expect(header).toContainText("06 · Conversational intelligence");
    await expect(header).toContainText("NIDP");
    await expect(page.getByTestId("dock-input")).toHaveAttribute("placeholder", "Ask about a stock, sector or your portfolio");
    const box = await dock.boundingBox();
    expect(Math.abs((box?.width ?? 0) - 384)).toBeLessThanOrEqual(1);
    expect(box?.height ?? 0).toBeLessThanOrEqual(820);
    const send = await page.getByTestId("dock-send").boundingBox();
    expect(Math.round(send?.width ?? 0)).toBe(34);
    // Nothing is asked until the user asks.
    expect(chat.streams).toHaveLength(0);

    const q = "What are the key market risks this week?";
    await page.getByTestId("dock-chips").getByRole("button", { name: q }).click();
    await expect.poll(() => chat.streams.length).toBe(1);
    // The desk's own surface: the server adds the PRD §9.4 answer structure for it (backend persona_framing.py).
    expect(chat.streams[0]).toMatchObject({ message: q, session_id: "desk1", persona: "trader", surface: "trading_desk" });

    await expect(dock.getByTestId("dock-question")).toHaveText(q);
    await expect(dock.getByTestId("dock-answer")).toHaveText(ANSWER);
    // The desk is still on screen while the answer shows.
    await expect(desk(page)).toBeVisible();

    // The INVESTOR switch changes the persona the dock asks in (and the URL), not the app's rail mode.
    await page.getByTestId("desk-persona-investor").click();
    await expect(page).toHaveURL(/[?&]persona=investor/);
    await expect(page.getByTestId("desk-persona-investor")).toHaveAttribute("aria-pressed", "true");
    await page.getByTestId("dock-input").fill("And for banks?");
    await page.getByTestId("dock-send").click();
    await expect.poll(() => chat.streams.length).toBe(2);
    expect(chat.streams[1]).toMatchObject({ message: "And for banks?", session_id: "desk1", persona: "investor", surface: "trading_desk" });
    await expect(dock.getByTestId("dock-turn")).toHaveCount(2);
    expect(chat.created).toBe(1);
    await page.getByTestId("desk-persona-trader").click();
    await expect(page).not.toHaveURL(/persona=/);

    // The thread survives moving between tabs.
    // Desk redesign step 3: the scanner list is Trade Desk › AI Scanner › Ranked candidates (the tab's default).
    await page.getByTestId("desk-tab-overview").click();
    await page.getByTestId("desk-tab-trade").click();
    await expect(dock.getByTestId("dock-turn")).toHaveCount(2);
    // Beside the dock the desk is too narrow for the scanner's columns, so its rows show as cards.
    await expect(page.getByTestId("desk-scan-cards")).toBeVisible();
    await expect(page.getByTestId("desk-scan-table")).toHaveCount(0);

    // Desk redesign (2026-10-27): there is no More list; the header's "Copilot docked right" puts the cursor in the dock.
    await expect(page.getByTestId("desk-dock")).toHaveCount(1);
    await page.getByTestId("desk-docked-note").click();
    await expect(page.getByTestId("dock-input")).toBeFocused();

    // "Open the full thread" opens it in the app's thread view, where the shell's ask box is back.
    await page.getByTestId("dock-open-thread").click();
    await expect(page).toHaveURL(/\/v5\/app\/t\/desk1$/);
    await expect(page.getByTestId("composer-input")).toBeVisible();
    await expect(page.getByTestId("desk-dock")).toHaveCount(0);

    // "＋" starts a fresh conversation.
    await page.goto(DESK);
    await expect(page.getByTestId("dock-turn")).toHaveCount(2);
    await page.getByTestId("dock-new").click();
    await expect(page.getByTestId("dock-turn")).toHaveCount(0);
    await expect(page.getByTestId("desk-dock")).toContainText("Ask about anything on the desk.");
  });

  test("TC-5: below 1400px there is no dock; the shell ask box is there, and More · AI Copilot is the desk's Copilot (ask box hidden)", async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 800 });
    const chat = await mockChat(page);
    await page.goto(DESK);
    await expect(desk(page)).toBeVisible();
    await expect(page.getByTestId("desk-dock")).toHaveCount(0);
    await expect(page.getByTestId("desk-docked-note")).toHaveCount(0);
    await expect(page.getByTestId("composer-input")).toBeVisible();
    // Without the dock there is room for the scanner's full table.
    // Desk redesign step 3: the scanner list is Trade Desk › AI Scanner › Ranked candidates (the tab's default).
    await page.getByTestId("desk-tab-trade").click();
    await expect(page.getByTestId("desk-scan-table")).toBeVisible();
    await expect(page.getByTestId("desk-scan-cards")).toHaveCount(0);

    // Desk redesign (2026-10-27): the page Copilot is the header's Copilot button (?tab=copilot), not More · AI Copilot.
    await page.getByTestId("desk-copilot-button").click();
    await expect(page.getByTestId("desk-dock")).toHaveAttribute("data-variant", "page");
    await expect(page.getByTestId("composer-input")).toHaveCount(0);
    await expect(page.getByTestId("desk-copilot-button")).toHaveAttribute("aria-pressed", "true");
    // A question typed in the desk search goes to it, in the desk's persona.
    await page.getByTestId("desk-tab-overview").click();
    await expect(page.getByTestId("composer-input")).toBeVisible();
    await page.getByTestId("desk-search").fill("Is breadth improving?");
    await page.getByTestId("desk-search").press("Enter");
    await expect(page).toHaveURL(/[?&]tab=copilot/); // was tab=more before the 2026-10-27 redesign
    await expect.poll(() => chat.streams.length).toBe(1);
    expect(chat.streams[0]).toMatchObject({ message: "Is breadth improving?", persona: "trader" });
    await expect(page.getByTestId("dock-question")).toHaveText("Is breadth improving?");
  });

  test("TC-6: a failed answer shows an error line in the dock with a retry, and the desk stays up", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    const chat = await mockChat(page, { streamStatus: 500 });
    await page.goto(DESK);
    await page.getByTestId("dock-input").fill("Is breadth improving?");
    await page.getByTestId("dock-send").click();

    const problem = page.getByTestId("dock-problem");
    await expect(problem).toBeVisible({ timeout: 15_000 });
    await expect(problem.getByRole("button", { name: /Retry/ })).toBeVisible();
    await expect(desk(page)).toBeVisible();
    await expect(page.getByTestId("desk-tab-overview")).toBeVisible();

    const before = chat.streams.length;
    await problem.getByRole("button", { name: /Retry/ }).click();
    await expect.poll(() => chat.streams.length).toBeGreaterThan(before);
    expect(chat.streams[chat.streams.length - 1]).toMatchObject({ message: "Is breadth improving?", persona: "trader" });
  });

  test("TC-9: the bottom bar is keyboard reachable — Tab reaches its items and Enter opens one", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await mockChat(page);
    await page.goto(DESK);
    await expect(page.getByTestId("desk-bottom-bar")).toBeVisible();
    // Desk redesign (2026-10-27): the bar is 01 Overview · 02 Trade · 03 Market · 04 Risk · Copilot; the same keyboard steps on its items.
    // Focus the item before Market, then Tab once: the next stop is Market; Enter opens it.
    await page.getByTestId("desk-bottom-trade").focus();
    await page.keyboard.press("Tab");
    await expect(page.getByTestId("desk-bottom-market")).toBeFocused();
    await page.keyboard.press("Enter");
    await expect(desk(page)).toHaveAttribute("data-tab", "market");
    await page.getByTestId("desk-bottom-copilot").focus();
    await page.keyboard.press("Space");
    await expect(desk(page)).toHaveAttribute("data-tab", "copilot");
    // Wider than a phone the bar is not drawn and the numbered tab row is back.
    await page.setViewportSize({ width: 1280, height: 800 });
    await expect(page.getByTestId("desk-bottom-bar")).toHaveCount(0);
    await expect(page.getByRole("tablist", { name: "Desk tabs" }).getByRole("tab")).toHaveCount(4); // four numbered tabs since 2026-10-27
  });

  test("TC-8: on a phone the search selects a scanner stock, or asks More · AI Copilot; the persona pill switches the wording", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    const chat = await mockChat(page);
    await page.goto(DESK);
    await page.getByTestId("desk-search-toggle").click();
    await page.getByTestId("desk-search").fill("testp");
    await page.getByTestId("desk-search").press("Enter");
    await expect(desk(page)).toHaveAttribute("data-symbol", "TESTPICK");
    await expect(desk(page)).toHaveAttribute("data-tab", "overview");
    await expect(page.getByTestId("desk-search-picked")).toContainText("TESTPICK selected");

    await page.getByTestId("desk-persona-pill").click();
    await expect(page).toHaveURL(/[?&]persona=investor/);
    await expect(page.getByTestId("desk-persona-pill")).toHaveText("Investor");
    await page.getByTestId("desk-search").fill("Is this a good week for banks?");
    await page.getByTestId("desk-search").press("Enter");
    await expect(desk(page)).toHaveAttribute("data-tab", "copilot"); // was "more" before the 2026-10-27 redesign
    await expect.poll(() => chat.streams.length).toBe(1);
    expect(chat.streams[0]).toMatchObject({ message: "Is this a good week for banks?", persona: "investor", surface: "trading_desk" });
    await expect(page.getByTestId("composer-input")).toHaveCount(0);
    await expect(page.getByTestId("desk-bottom-copilot")).toHaveAttribute("aria-current", "page"); // was the bar's More
  });
});

// ── design fidelity: desk header and Overview (design-spec §2, §3, §10) ──

test.describe("Smart trading desk — header search", () => {
  test("header search: a symbol not in the scan opens the Chart tab with ?sym= (PRD §7.2); on the Chart tab it switches the stock; words go to the Copilot", async ({ page }) => {
    await overviewApi(page);
    const chat = await mockChat(page);
    await page.goto(DESK);
    await expect(desk(page)).toHaveAttribute("data-tab", "overview");
    // TATASTEEL is not one of the mocked scanner setups (TESTBRK, TESTPRE, TESTPICK); lower case is read as the symbol.
    await page.getByTestId("desk-search").fill("tatasteel");
    await page.getByTestId("desk-search").press("Enter");
    // The owner's design: a symbol's chart is Trade Desk › Chart Analysis › Live chart.
    await expect(page).toHaveURL(/[?&]tab=trade&view=chart&sub=live(&|$)/);
    await expect(page).toHaveURL(/[?&]sym=TATASTEEL(&|$)/);
    await expect(desk(page)).toHaveAttribute("data-view", "chart");
    await expect(desk(page)).toHaveAttribute("data-symbol", "TATASTEEL");
    await expect(page.getByTestId("desk-search-picked")).toHaveCount(0);
    // Already on the Chart tab: the stock changes, the tab stays.
    await page.getByTestId("desk-search").fill("M&M");
    await page.getByTestId("desk-search").press("Enter");
    await expect(desk(page)).toHaveAttribute("data-symbol", "M&M");
    await expect(desk(page)).toHaveAttribute("data-view", "chart");
    expect(chat.streams).toHaveLength(0);
    // More than one word is a question for the Copilot (More · AI Copilot below 1400px).
    await page.getByTestId("desk-search").fill("what about steel stocks");
    await page.getByTestId("desk-search").press("Enter");
    await expect.poll(() => chat.streams.length).toBe(1);
    expect(chat.streams[0]).toMatchObject({ message: "what about steel stocks", persona: "trader" });
    await expect(desk(page)).toHaveAttribute("data-tab", "copilot"); // was "more" before the 2026-10-27 redesign
  });

});

// ── design fidelity: phone M1 Overview (design-spec §11) ────────────────

// ── design-fidelity screenshots (design-spec §2, §3, §9, §11) ───────────
