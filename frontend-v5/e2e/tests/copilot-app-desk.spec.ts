/**
 * One-screen Copilot app (/v5/app) — Smart trading desk: the shell.
 *
 * MOCK — not real data: every /api response here is a fixture or an inline
 * payload in the shape the real route returns (source named beside each), with
 * synthetic values. Expected figures are worked out from the payload, not
 * copied from the screen. Mocked APIs, production build — see
 * pw.copilot-app.config.ts.
 *
 * Covers screens/TradingDesk.tsx, screens/tradingdesk/CopilotDock.tsx and the
 * design-fidelity pass on the Overview (OverviewTab.tsx): the Trader rail
 * entry; the desk header (search, TRADER / INVESTOR switch, market status);
 * the tab row in the PRD's order (Overview · AI Scanner · Market Intelligence
 * · Chart Analysis · Portfolio & Risk · More) and its URL (?tab=&sym=&persona=);
 * More's destinations (the lab under More, so ?tab=fno still opens it); the
 * docked Copilot from 1400px (384px card, asked in the desk's persona, its own
 * thread); More · AI Copilot below that and on a phone (the shell's ask box
 * hidden there); the disclaimer footer; the Overview's headline, index row,
 * pulse and sector card against design §3; the phone's M1 Overview and M6
 * More · AI Copilot; a failed answer; and 390px passes. Each tab's own blocks
 * are covered by copilot-app-desk-*.spec.ts.
 */
import { test, expect, type Page, type Route } from "@playwright/test";
import { mockApi, mockSingleRoute } from "../helpers/api-mock";

const APP = "/v5/app";
const DESK = `${APP}/trader/desk`;
// The desk PRD §3.1 order (docs/smart_trader): it overrides the desktop design's order and puts the lab under More.
const TABS = ["overview", "scanner", "intel", "chart", "portfolio", "more"];
const LABELS = ["Overview", "AI Scanner", "Market Intelligence", "Chart Analysis", "Portfolio & Risk", "More"];
// The phone's chips (design §11): the same order, shorter names, no numbers.
const MOBILE_LABELS = ["Overview", "AI Scanner", "Market Intel", "Chart Analysis", "Portfolio & Risk", "More"];
const MORE_ITEMS = ["copilot", "fno", "watchlist", "saved", "paper", "settings"];
const MORE_LABELS = ["AI Copilot", "Options & futures lab", "Watchlists", "Saved analyses", "Paper trading", "Settings & integrations"];

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

interface ChatMock { streams: Array<{ message: string; session_id?: string; persona?: string }>; created: number }

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
    const body = route.request().postDataJSON() as { message: string; session_id?: string; persona?: string };
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
// backend/routes/macro.py :: macro_today.
const MACRO = {
  date: "2026-10-13", market_open_today: false, is_holiday_view: true, days_stale: 1, market: "BULL", inflation: "STABLE", liquidity: "EASY",
  risk: "LOW", multiplier: 1.1, insight: "Fixture insight: the trend is intact and risk gauges are quiet.", values: {}, features: {}, sources: {},
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

// backend/routes/portfolio_risk_analytics.py :: risk_analytics — a 21.5% a year volatility is the route's HIGH band.
const RISK = {
  empty: false, risk_rating: "HIGH", risk_score: 5.4, weighted_volatility: 0.215, weighted_beta: 1.12, var_1d_rs: 41000, var_1d_pct: 0.4,
  var_confidence: 0.95, coverage_pct: 88.0, risk_drivers: [],
};

async function traderMode(page: Page) {
  await page.addInitScript(() => localStorage.setItem("nivesh.copilot", JSON.stringify({ state: { mode: "trader", evidenceOpen: null }, version: 0 })));
}

const desk = (page: Page) => page.getByTestId("screen-trading-desk");

// ── expected-value helpers (the screen's rules, written out) ────────────
const dayShort = (iso: string) => new Date(`${iso}T00:00:00Z`).toLocaleDateString("en-IN", { day: "numeric", month: "short", timeZone: "UTC" });
const todayIst = () => new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Kolkata", year: "numeric", month: "2-digit", day: "2-digit" }).format(new Date());
const BAND_WORD = ["strong", "positive", "even", "soft", "weak"];
const INVESTOR_PAST = ["Most stocks rose", "More stocks rose than fell", "About as many stocks rose as fell", "More stocks fell than rose", "Most stocks fell"];
const band = (share: number) => { const i = [60, 52, 48, 40].findIndex((b) => share >= b); return i === -1 ? 4 : i; };
/** The headline's first sentence for a breadth day that is not today (the fixtures are dated 13 Oct 2026). */
function breadthLead(persona: "trader" | "investor", share: number, dayIso: string, topSector: string | null): string {
  const on = ` on ${dayShort(dayIso)}`;
  if (persona === "investor") return `${INVESTOR_PAST[band(share)]}${on}${topSector ? `, led by ${topSector}` : ""}.`;
  return `Breadth was ${BAND_WORD[band(share)]}${on}${topSector ? ` and ${topSector} led` : ""}.`;
}
const shareOf = (b: { advances: number; declines: number; unchanged: number }) => (b.advances / (b.advances + b.declines + b.unchanged)) * 100;
const STATUS_TEXT = /^(NSE hours|Market closed) · \d{2}:\d{2} IST$/;

async function overflow(page: Page) {
  return page.evaluate(() => {
    const sc = document.querySelector('[data-testid="copilot-scroll"]') as HTMLElement | null;
    return { doc: document.documentElement.scrollWidth - window.innerWidth, scroll: sc ? sc.scrollWidth - sc.clientWidth : 0 };
  });
}
async function noSideScroll(page: Page) {
  const o = await overflow(page);
  expect(o.doc).toBeLessThanOrEqual(1);
  expect(o.scroll).toBeLessThanOrEqual(1);
}

test.describe("Smart trading desk — shell", () => {
  test.beforeEach(async ({ page }) => {
    await deskApi(page);
  });

  test("TC-1: the Trader rail lists the Smart trading desk first and opens it with the PRD's six tabs", async ({ page }) => {
    await traderMode(page);
    await mockChat(page);
    await page.goto(`${APP}/trader`);
    const tools = page.getByRole("navigation", { name: "Tools and workspace" }).locator(".cp-rail-row");
    await expect(tools.first()).toContainText("Smart trading desk");
    await expect(tools.first()).toContainText("AI");
    await expect(tools.nth(1)).toContainText("Trader desk");

    await tools.first().click();
    await expect(page).toHaveURL(/\/v5\/app\/trader\/desk$/);
    await expect(desk(page)).toBeVisible();
    await expect(desk(page)).toHaveAttribute("data-tab", "overview");
    await expect(tools.first()).toHaveAttribute("aria-current", "page");

    const tabs = page.getByRole("tablist", { name: "Desk modules" }).getByRole("tab");
    await expect(tabs).toHaveCount(6);
    for (let i = 0; i < TABS.length; i += 1) {
      await expect(tabs.nth(i)).toHaveAttribute("data-testid", `desk-tab-${TABS[i]}`);
      await expect(tabs.nth(i)).toHaveText(`${String(i + 1).padStart(2, "0")}${LABELS[i]}`);
    }
    await expect(page.getByTestId("desk-tab-overview")).toHaveAttribute("aria-selected", "true");
    // The lab is not a top-level tab any more.
    await expect(page.getByTestId("desk-tab-fno")).toHaveCount(0);

    // No page headline above the tabs: the headline is the Overview's (design §2, §3). Worked out from the payload:
    // markets-home.json breadth 1200 / 800 / 50 (58.5% advancing, "positive") on 13 Oct; no sector figures in this mock;
    // TESTBRK (breakout_confirmed) and TESTPICK (stage BREAKOUT) confirmed of three setups.
    await expect(page.getByTestId("desk-headline")).toHaveCount(1);
    const head = page.getByTestId("desk-panel-overview").getByTestId("desk-headline");
    const lead = todayIst() === "2026-10-13" ? "Breadth is positive." : breadthLead("trader", shareOf({ advances: 1200, declines: 800, unchanged: 50 }), "2026-10-13", null);
    await expect(head).toHaveText(`${lead} 2 of 3 setups have confirmed.`);
    await expect(head.locator("em")).toHaveText("2 of 3 setups");

    const foot = page.getByTestId("desk-disclaimer");
    await expect(foot).toContainText("DISCLAIMER");
    await expect(foot).toContainText("Nivesh does not place orders");
    await expect(foot).toContainText("next session");
    await expect(foot).toContainText("SEBI study");
    await expect(foot).not.toContainText("Illustrative");
  });

  test("TC-2: a tab click sets ?tab=; More holds the lab (?tab=fno still opens it); a deep link opens that tab with that stock; a bad symbol is dropped", async ({ page }) => {
    await mockChat(page);
    await page.goto(DESK);
    await expect(desk(page)).toHaveAttribute("data-tab", "overview");

    for (const t of ["scanner", "intel", "portfolio", "chart", "overview"]) {
      await page.getByTestId(`desk-tab-${t}`).click();
      await expect(page).toHaveURL(new RegExp(`[?&]tab=${t}(&|$)`));
      await expect(desk(page)).toHaveAttribute("data-tab", t);
      await expect(page.getByTestId(`desk-tab-${t}`)).toHaveAttribute("aria-selected", "true");
      await expect(page.getByTestId(`desk-panel-${t}`)).toHaveCount(1);
    }

    // More, then the lab inside it: "More" stays the selected tab.
    await page.getByTestId("desk-tab-more").click();
    await expect(page).toHaveURL(/[?&]tab=more(&|$)/);
    await expect(desk(page)).toHaveAttribute("data-tab", "more");
    await expect(page.getByTestId("desk-tab-more")).toHaveAttribute("aria-selected", "true");
    await page.getByTestId("desk-more-fno").click();
    await expect(page).toHaveURL(/[?&]tab=fno(&|$)/);
    await expect(desk(page)).toHaveAttribute("data-tab", "fno");
    await expect(page.getByTestId("desk-panel-fno")).toHaveCount(1);
    await expect(page.getByTestId("desk-tab-more")).toHaveAttribute("aria-selected", "true");
    await expect(page.getByTestId("desk-more-fno")).toHaveAttribute("aria-pressed", "true");
    // An old link to the lab still opens it, under More.
    await page.goto(`${DESK}?tab=fno`);
    await expect(desk(page)).toHaveAttribute("data-tab", "fno");
    await expect(page.getByTestId("desk-tab-more")).toHaveAttribute("aria-selected", "true");

    // Lower case in the link is read as the NSE symbol.
    await page.goto(`${DESK}?tab=chart&sym=reliance`);
    await expect(desk(page)).toHaveAttribute("data-tab", "chart");
    await expect(desk(page)).toHaveAttribute("data-symbol", "RELIANCE");
    await expect(page.getByTestId("desk-tab-chart")).toHaveAttribute("aria-selected", "true");
    // Changing tab keeps the stock (the link's own spelling stays in the URL).
    await page.getByTestId("desk-tab-scanner").click();
    await expect(page).toHaveURL(/tab=scanner/);
    await expect(page).toHaveURL(/sym=reliance/i);
    await expect(desk(page)).toHaveAttribute("data-symbol", "RELIANCE");

    // M&M and BAJAJ-AUTO are valid NSE symbols; markup is not.
    await page.goto(`${DESK}?tab=chart&sym=${encodeURIComponent("M&M")}`);
    await expect(desk(page)).toHaveAttribute("data-symbol", "M&M");
    await page.goto(`${DESK}?tab=chart&sym=${encodeURIComponent("<img src=x>")}`);
    await expect(desk(page)).toHaveAttribute("data-tab", "chart");
    await expect(desk(page)).toHaveAttribute("data-symbol", "");
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
    expect(chat.streams[0]).toMatchObject({ message: q, session_id: "desk1", persona: "trader" });

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
    expect(chat.streams[1]).toMatchObject({ message: "And for banks?", session_id: "desk1", persona: "investor" });
    await expect(dock.getByTestId("dock-turn")).toHaveCount(2);
    expect(chat.created).toBe(1);
    await page.getByTestId("desk-persona-trader").click();
    await expect(page).not.toHaveURL(/persona=/);

    // The thread survives moving between tabs.
    await page.getByTestId("desk-tab-scanner").click();
    await expect(dock.getByTestId("dock-turn")).toHaveCount(2);
    // Beside the dock the desk is too narrow for the scanner's columns, so its rows show as cards.
    await expect(page.getByTestId("desk-scan-cards")).toBeVisible();
    await expect(page.getByTestId("desk-scan-table")).toHaveCount(0);

    // With the dock showing, More lists its destinations; "AI Copilot" puts the cursor in the dock.
    await page.getByTestId("desk-tab-more").click();
    const list = page.getByTestId("desk-more-list");
    await expect(list).toBeVisible();
    for (let i = 0; i < MORE_ITEMS.length; i += 1) {
      await expect(list.getByTestId(`desk-more-item-${MORE_ITEMS[i]}`)).toContainText(MORE_LABELS[i]);
    }
    await expect(page.getByTestId("desk-dock")).toHaveCount(1);
    await list.getByTestId("desk-more-item-copilot").click();
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
    await page.getByTestId("desk-tab-scanner").click();
    await expect(page.getByTestId("desk-scan-table")).toBeVisible();
    await expect(page.getByTestId("desk-scan-cards")).toHaveCount(0);

    await page.getByTestId("desk-tab-more").click();
    await expect(page.getByTestId("desk-dock")).toHaveAttribute("data-variant", "page");
    await expect(page.getByTestId("composer-input")).toHaveCount(0);
    await expect(page.getByTestId("desk-more-copilot")).toHaveAttribute("aria-pressed", "true");
    // A question typed in the desk search goes to it, in the desk's persona.
    await page.getByTestId("desk-tab-overview").click();
    await expect(page.getByTestId("composer-input")).toBeVisible();
    await page.getByTestId("desk-search").fill("Is breadth improving?");
    await page.getByTestId("desk-search").press("Enter");
    await expect(page).toHaveURL(/[?&]tab=more/);
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

  test("TC-7: at 390px — the phone frame (design §11), chips in order, More's destinations, no sideways scroll", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    const chat = await mockChat(page);
    await page.goto(DESK);
    await expect(desk(page)).toBeVisible();
    await expect(page.getByTestId("desk-dock")).toHaveCount(0);
    await expect(page.getByTestId("composer-input")).toBeVisible();
    await noSideScroll(page);

    const head = page.getByTestId("desk-mobile-header");
    await expect(head).toContainText("Nivesh Copilot");
    await expect(head).toContainText("AI SMART TRADING DESK");
    await expect(page.getByTestId("desk-persona-pill")).toHaveText("Trader");
    await expect(page.getByTestId("desk-topbar")).toHaveCount(0);

    const strip = page.getByRole("tablist", { name: "Desk modules" });
    const chips = strip.getByRole("tab");
    await expect(chips).toHaveCount(6);
    for (let i = 0; i < MOBILE_LABELS.length; i += 1) {
      await expect(chips.nth(i)).toHaveText(MOBILE_LABELS[i]);
      await expect(chips.nth(i)).toHaveAttribute("data-testid", `desk-tab-${TABS[i]}`);
    }
    // Six chips do not fit in 390px: the strip scrolls, and the last one is reachable.
    const fits = await strip.evaluate((el) => el.scrollWidth <= el.clientWidth);
    expect(fits).toBe(false);

    // M6 More · AI Copilot: the desk's Copilot full height; the shell's ask box does not show twice.
    await page.getByTestId("desk-tab-more").scrollIntoViewIfNeeded();
    await page.getByTestId("desk-tab-more").click();
    await expect(desk(page)).toHaveAttribute("data-tab", "more");
    const sub = page.getByTestId("desk-more-chips").getByRole("button");
    await expect(sub).toHaveCount(MORE_LABELS.length);
    for (let i = 0; i < MORE_LABELS.length; i += 1) await expect(sub.nth(i)).toHaveText(MORE_LABELS[i]);
    await expect(page.getByTestId("desk-more-copilot")).toHaveAttribute("aria-pressed", "true");
    await expect(page.getByTestId("desk-dock")).toHaveAttribute("data-variant", "page");
    await expect(page.getByTestId("composer-input")).toHaveCount(0);
    await expect(page.getByTestId("dock-input")).toHaveAttribute("placeholder", "Ask Nivesh AI anything…");
    await expect(page.getByTestId("dock-note")).toHaveText("For education and research only. Not a buy or sell recommendation.");
    await expect(page.getByTestId("dock-chips")).toContainText("Suggested questions");
    await noSideScroll(page);
    await page.getByTestId("dock-input").fill("What moved banks?");
    await page.getByTestId("dock-send").click();
    await expect.poll(() => chat.streams.length).toBe(1);
    expect(chat.streams[0]).toMatchObject({ message: "What moved banks?", persona: "trader" });
    await expect(page.getByTestId("dock-answer")).toHaveText(ANSWER);
    await noSideScroll(page);

    // The lab, under More.
    await page.getByTestId("desk-more-fno").click();
    await expect(desk(page)).toHaveAttribute("data-tab", "fno");
    await expect(page.getByTestId("desk-tab-more")).toHaveAttribute("aria-selected", "true");
    await expect(page.getByTestId("composer-input")).toBeVisible();
    await noSideScroll(page);

    // Paper trading is the Portfolio & Risk tab's paper desk; the rest leave the desk for their own views.
    await page.getByTestId("desk-more-paper").click();
    await expect(desk(page)).toHaveAttribute("data-tab", "portfolio");
    await page.goto(`${DESK}?tab=more`);
    await page.getByTestId("desk-more-watchlist").click();
    await expect(page).toHaveURL(/\/v5\/app\/page\/watchlist$/);
    await page.goto(`${DESK}?tab=more`);
    await page.getByTestId("desk-more-saved").click();
    await expect(page).toHaveURL(/\/v5\/app\/page\/saved$/);
    await page.goto(`${DESK}?tab=more`);
    await page.getByTestId("desk-more-settings").click();
    await expect(page).toHaveURL(/\/v5\/app\/page\/brokers$/);
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
    await expect(desk(page)).toHaveAttribute("data-tab", "more");
    await expect.poll(() => chat.streams.length).toBe(1);
    expect(chat.streams[0]).toMatchObject({ message: "Is this a good week for banks?", persona: "investor" });
    await expect(page.getByTestId("composer-input")).toHaveCount(0);
  });
});

// ── design fidelity: desk header and Overview (design-spec §2, §3, §10) ──

test.describe("Smart trading desk — header and Overview · design fidelity", () => {
  test("header row: search, TRADER / INVESTOR, market status from /markets/home; search selects a stock or asks the dock", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await overviewApi(page);
    const chat = await mockChat(page);
    await page.goto(DESK);
    const bar = page.getByTestId("desk-topbar");
    await expect(bar).toContainText("AI Smart Trading Desk");
    await expect(page.getByTestId("desk-search")).toHaveAttribute("placeholder", "Search a stock or ask Nivesh…");
    await expect(bar).toContainText("ENTER");
    await expect(page.getByTestId("desk-persona-trader")).toHaveAttribute("aria-pressed", "true");
    await expect(page.getByTestId("desk-persona-investor")).toHaveAttribute("aria-pressed", "false");
    // HOME: market_state "closed" — never "live", never "Market open".
    const status = page.getByTestId("desk-market-status");
    await expect(status).toHaveText(STATUS_TEXT);
    await expect(status).toHaveText(/^Market closed/);
    await expect(status).toHaveAttribute("data-feed", "closed");
    await expect(page.getByTestId("desk-intro-feed")).toHaveText("NSE · BSE end of day");
    const sb = await page.getByTestId("desk-search").locator("xpath=..").boundingBox();
    expect(Math.round(sb?.height ?? 0)).toBe(38);
    expect(sb?.width ?? 0).toBeLessThanOrEqual(380);

    // A scanner symbol (prefix, any case) is selected and the tab stays; anything else is asked in the dock.
    await page.getByTestId("desk-search").fill("testp");
    await page.getByTestId("desk-search").press("Enter");
    await expect(desk(page)).toHaveAttribute("data-symbol", "TESTPICK");
    await expect(desk(page)).toHaveAttribute("data-tab", "overview");
    await expect(page.getByTestId("desk-search")).toHaveValue("");
    await page.getByTestId("desk-search-picked").getByRole("button", { name: /Chart/ }).click();
    await expect(desk(page)).toHaveAttribute("data-tab", "chart");
    await page.getByTestId("desk-search").fill("Why is IT strong today?");
    await page.getByTestId("desk-search").press("Enter");
    await expect.poll(() => chat.streams.length).toBe(1);
    expect(chat.streams[0]).toMatchObject({ message: "Why is IT strong today?", persona: "trader" });
    await expect(desk(page)).toHaveAttribute("data-tab", "chart");

    // In NSE hours: the live tape says so; delayed quotes say delayed.
    await page.route("**/api/markets/home", (route) => json(route, { ...HOME, market_state: "open", is_live: true }));
    await page.goto(DESK);
    await expect(status).toHaveText(/^NSE hours · \d{2}:\d{2} IST$/);
    await expect(status).toHaveAttribute("data-feed", "live");
    await expect(page.getByTestId("desk-intro-feed")).toHaveText("NSE · BSE live");
    await page.route("**/api/markets/home", (route) => json(route, { ...HOME, market_state: "open", is_live: false }));
    await page.goto(DESK);
    await expect(status).toHaveAttribute("data-feed", "delayed");
    await expect(page.getByTestId("desk-intro-feed")).toHaveText("NSE · BSE delayed");
  });

  test("header search: a symbol not in the scan opens the Chart tab with ?sym= (PRD §7.2); on the Chart tab it switches the stock; words go to the Copilot", async ({ page }) => {
    await overviewApi(page);
    const chat = await mockChat(page);
    await page.goto(DESK);
    await expect(desk(page)).toHaveAttribute("data-tab", "overview");
    // TATASTEEL is not one of the mocked scanner setups (TESTBRK, TESTPRE, TESTPICK); lower case is read as the symbol.
    await page.getByTestId("desk-search").fill("tatasteel");
    await page.getByTestId("desk-search").press("Enter");
    await expect(page).toHaveURL(/[?&]tab=chart(&|$)/);
    await expect(page).toHaveURL(/[?&]sym=TATASTEEL(&|$)/);
    await expect(desk(page)).toHaveAttribute("data-tab", "chart");
    await expect(desk(page)).toHaveAttribute("data-symbol", "TATASTEEL");
    await expect(page.getByTestId("desk-search-picked")).toHaveCount(0);
    // Already on the Chart tab: the stock changes, the tab stays.
    await page.getByTestId("desk-search").fill("M&M");
    await page.getByTestId("desk-search").press("Enter");
    await expect(desk(page)).toHaveAttribute("data-symbol", "M&M");
    await expect(desk(page)).toHaveAttribute("data-tab", "chart");
    expect(chat.streams).toHaveLength(0);
    // More than one word is a question for the Copilot (More · AI Copilot below 1400px).
    await page.getByTestId("desk-search").fill("what about steel stocks");
    await page.getByTestId("desk-search").press("Enter");
    await expect.poll(() => chat.streams.length).toBe(1);
    expect(chat.streams[0]).toMatchObject({ message: "what about steel stocks", persona: "trader" });
    await expect(desk(page)).toHaveAttribute("data-tab", "more");
  });

  test("Overview §3: intro, headline from breadth / leading sector / setups, index row, pulse and sector card; persona switches the words", async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 800 });
    await overviewApi(page);
    await mockChat(page);
    await page.goto(DESK);
    const ov = page.getByTestId("desk-overview");
    // 972px of desk beside the rail: the design's 1440 grid.
    await expect(ov).toHaveAttribute("data-layout", "full");

    await expect(page.getByTestId("desk-intro-stamp")).toHaveText(/^(Mon|Tue|Wed|Thu|Fri|Sat|Sun) \d{1,2} [A-Z][a-z]{2} · \d{2}:\d{2} IST$/);
    const intro = page.getByTestId("desk-intro");
    for (const p of ["Broker hub · read-only", "Paper trading on", "Live orders off"]) await expect(intro).toContainText(p);
    // HOME 2,428 / 1,142 / 72 = 66.7% advancing ("strong") on 13 Oct; IT is the best 1-day sector (+1.42%); 2 of 3 setups confirmed.
    const share = shareOf(HOME.breadth);
    const h1 = page.getByTestId("desk-headline");
    await expect(h1).toHaveText(`${breadthLead("trader", share, "2026-10-13", "IT")} 2 of 3 setups have confirmed.`);
    await expect(h1.locator("em")).toHaveText("2 of 3 setups");
    const fs = await h1.evaluate((el) => getComputedStyle(el).fontSize);
    expect(fs).toBe("40px");

    // Index row: four cards and breadth on one row.
    const tiles = page.getByTestId("desk-index-tile");
    await expect(tiles).toHaveCount(4);
    const y0 = (await tiles.first().boundingBox())?.y ?? -1;
    expect(Math.round((await page.getByTestId("desk-breadth").boundingBox())?.y ?? -2)).toBe(Math.round(y0));
    await expect(page.getByTestId("desk-breadth-pct")).toHaveText(`${share.toFixed(0)}%`);
    await expect(page.getByTestId("desk-breadth-adv")).toHaveText("2,428 advances");
    await expect(page.getByTestId("desk-breadth-dec")).toHaveText("declines 1,142");

    // Pulse card.
    await expect(page.getByTestId("desk-pulse-title")).toHaveText("01 · AI Market pulse");
    await expect(page.getByTestId("desk-pulse-meta")).toHaveText(`Macro engine · ${dayShort(MACRO.date)} · end of day`);
    await expect(page.getByTestId("desk-regime-label")).toHaveText("Bullish");
    await expect(page.getByTestId("desk-regime-since")).toHaveText(`As of ${dayShort(MACRO.date)} · end of day`);
    const statLabels = ["FII · cash", "DII · cash", "USD / INR", "Crude oil"];
    const ids = ["desk-mini-fii", "desk-mini-dii", "desk-mini-usdinr", "desk-mini-brent"];
    let statY: number | null = null;
    for (let i = 0; i < ids.length; i += 1) {
      await expect(page.getByTestId(ids[i]).locator(".cp-eyebrow")).toHaveText(statLabels[i]);
      const y = Math.round((await page.getByTestId(ids[i]).boundingBox())?.y ?? -1);
      statY ??= y;
      expect(y).toBe(statY);
    }
    await expect(page.getByTestId("desk-insight")).toContainText("Rules-based insight");
    await expect(page.getByTestId("desk-insight-macro")).toHaveText(MACRO.insight);

    // Sector card: the period switch sits in the header; tiles high → low for 1D.
    await expect(page.getByTestId("desk-sector-title")).toHaveText("Sector strength");
    await expect(page.getByTestId("desk-sectors").getByTestId("desk-sector-period-1d")).toHaveCount(0);
    await expect(page.getByTestId("desk-sector-card").getByTestId("desk-sector-period-1d")).toHaveAttribute("aria-pressed", "true");
    const order = [...SECTORS.sectors].sort((a, b) => b.ret_1d_pct - a.ret_1d_pct).map((r) => r.index);
    const st = page.getByTestId("desk-sector-tile");
    await expect(st).toHaveCount(order.length);
    for (let i = 0; i < order.length; i += 1) await expect(st.nth(i)).toHaveAttribute("data-index", order[i]);
    // No ask-chip row on the Overview (the dock has the chips).
    await expect(page.getByTestId("desk-overview-ask")).toHaveCount(0);

    // INVESTOR: plain words, same data.
    await page.getByTestId("desk-persona-investor").click();
    await expect(h1).toHaveText(`${breadthLead("investor", share, "2026-10-13", "IT")} 2 ideas have confirmed, each with its evidence shown.`);
    await expect(h1.locator("em")).toHaveText("2 ideas");
    await expect(page.getByTestId("desk-regime-meaning")).toHaveText("The Nifty 50 is above its average of the last 50 sessions, so the broad trend is up.");
    await expect(page.getByTestId("desk-breadth-adv")).toHaveText("2,428 advances");

    // Beside the dock (1440) the desk is 728px: breadth moves under the four index cards.
    await page.setViewportSize({ width: 1440, height: 900 });
    await expect(ov).toHaveAttribute("data-layout", "compact");
    const y1 = (await tiles.first().boundingBox())?.y ?? 0;
    expect((await page.getByTestId("desk-breadth").boundingBox())?.y ?? 0).toBeGreaterThan(y1 + 20);
    await noSideScroll(page);
  });

  test("sector card: with more than ten sector indices the five strongest and five weakest show until Show all", async ({ page }) => {
    await overviewApi(page);
    await mockChat(page);
    const many = Array.from({ length: 12 }, (_, i) => ({ index: `Nifty Fixture ${i + 1}`, sector: `Fixture ${i + 1}`, date: "2026-10-13", close: 1000 + i, ret_1d_pct: 3 - i * 0.5, ret_1w_pct: 1, ret_1m_pct: 1 }));
    await page.route("**/api/markets/sector-returns", (route) => json(route, { ...SECTORS, sectors: many }));
    await page.goto(DESK);
    const st = page.getByTestId("desk-sector-tile");
    await expect(st).toHaveCount(10);
    const sorted = [...many].sort((a, b) => b.ret_1d_pct - a.ret_1d_pct);
    const expected = [...sorted.slice(0, 5), ...sorted.slice(-5)].map((r) => r.index);
    for (let i = 0; i < expected.length; i += 1) await expect(st.nth(i)).toHaveAttribute("data-index", expected[i]);
    await expect(page.getByTestId("desk-sector-source")).toContainText("the five strongest and five weakest of 12");
    await page.getByTestId("desk-sector-more").click();
    await expect(st).toHaveCount(12);
    await expect(page.getByTestId("desk-sector-more")).toHaveText("Show fewer");
  });
});

// ── design fidelity: phone M1 Overview (design-spec §11) ────────────────

test.describe("Smart trading desk — phone M1 Overview · design fidelity", () => {
  test("M1: index tiles 2×2, status line, pulse with three breadth stats, top 5 opportunities, portfolio and risk tiles", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await overviewApi(page);
    await page.route("**/api/portfolio/risk-analytics", (route) => json(route, RISK));
    await mockChat(page);
    await page.goto(DESK);
    const ov = page.getByTestId("desk-overview");
    await expect(ov).toHaveAttribute("data-layout", "mobile");
    // The desktop intro is not on the phone (the header block is the title).
    await expect(page.getByTestId("desk-headline")).toHaveCount(0);

    // Order of the blocks, top to bottom.
    const order = ["desk-index-row", "desk-mobile-status", "desk-pulse-card", "desk-top-opps", "desk-m-portfolio"];
    let last = -1;
    for (const id of order) {
      const y = (await page.getByTestId(id).boundingBox())?.y ?? -1;
      expect(y).toBeGreaterThan(last);
      last = y;
    }
    expect(Math.round((await page.getByTestId("desk-m-risk").boundingBox())?.y ?? 0)).toBe(Math.round((await page.getByTestId("desk-m-portfolio").boundingBox())?.y ?? 1));

    // 2×2 index tiles, values from HOME.
    const tiles = page.getByTestId("desk-index-tile");
    await expect(tiles).toHaveCount(4);
    const ty = await Promise.all([0, 1, 2].map(async (i) => Math.round((await tiles.nth(i).boundingBox())?.y ?? 0)));
    expect(ty[0]).toBe(ty[1]);
    expect(ty[2]).toBeGreaterThan(ty[0]);
    await expect(tiles.first().getByTestId("desk-index-value")).toHaveText("25,123.45");

    await expect(page.getByTestId("desk-mobile-status")).toHaveText(/^Market closed · (Mon|Tue|Wed|Thu|Fri|Sat|Sun) \d{1,2} [A-Z][a-z]{2}, \d{2}:\d{2} IST$/);

    // Pulse: title, details, regime chip, the three centred breadth stats from HOME.
    await expect(page.getByTestId("desk-pulse-title")).toHaveText("01 · AI Market pulse");
    await expect(page.getByTestId("desk-pulse-details")).toHaveText("View details ›");
    await expect(page.getByTestId("desk-regime-label")).toHaveText("Bullish");
    await expect(page.getByTestId("desk-pulse-advances-value")).toHaveText("↑ 2,428");
    await expect(page.getByTestId("desk-pulse-declines-value")).toHaveText("↓ 1,142");
    await expect(page.getByTestId("desk-pulse-unchanged-value")).toHaveText("72");
    await expect(page.getByTestId("desk-insight")).toContainText("Rules-based insight");
    await expect(page.getByTestId("desk-mini-fii")).toHaveCount(0);
    await page.getByTestId("desk-pulse-details").click();
    await expect(page.getByTestId("desk-mini-fii-value")).toHaveText("−₹1,523 Cr");

    // 02 · Top AI opportunities: the scanner's order (TESTPICK scores 81.2; the watchlist rows have no score).
    await expect(page.getByTestId("desk-top-opps")).toContainText("02 · Top AI opportunities");
    const rows = page.getByTestId("desk-top-opp");
    await expect(rows).toHaveCount(3);
    const want = [
      // TESTPICK: picks only — price is the entry 505; upside (555 − 505) ÷ 505 = +9.9%; stage BREAKOUT.
      { sym: "TESTPICK", price: "₹505.00", score: "81", up: `+${(((555 - 505) / 505) * 100).toFixed(1)}%`, pattern: "Breakout", plain: "Broke above a recent high" },
      { sym: "TESTBRK", price: "₹510.00", score: "—", up: "—", pattern: "Breakout confirmed", plain: "Broke above a recent high" },
      { sym: "TESTPRE", price: "₹98.00", score: "—", up: "—", pattern: "Near breakout", plain: "Close to a recent high" },
    ];
    for (let i = 0; i < want.length; i += 1) {
      const r = rows.nth(i);
      await expect(r).toHaveAttribute("data-symbol", want[i].sym);
      await expect(r.getByTestId("desk-top-opp-price")).toHaveText(want[i].price);
      await expect(r.getByTestId("desk-top-opp-score")).toHaveText(want[i].score);
      await expect(r.getByTestId("desk-top-opp-upside")).toHaveText(want[i].up);
      await expect(r.getByTestId("desk-top-opp-pattern")).toHaveText(want[i].pattern);
      await expect(r.locator('[data-testid="entity-icon"]')).toHaveAttribute("data-key", want[i].sym);
    }

    // Your portfolio: holdings-enriched.json totals ₹1,03,06,772 (₹1.03 Cr), P&L ₹18,99,276 (+22.6%).
    await expect(page.getByTestId("desk-m-portfolio")).toContainText("Your portfolio");
    await expect(page.getByTestId("desk-m-portfolio-value")).toHaveText(`₹${(10306772.4 / 1e7).toFixed(2)} Cr`);
    await expect(page.getByTestId("desk-m-portfolio-sub")).toHaveText(`+₹${(1899275.8 / 1e5).toFixed(2)} L (+${(22.59).toFixed(1)}%)`);
    // Risk status: the route's HIGH band; 21.5% a year fills ⌈21.5 ÷ 8⌉ = 3 of 5 parts.
    await expect(page.getByTestId("desk-m-risk-value")).toHaveText("High");
    await expect(page.getByTestId("desk-m-risk-bar")).toHaveAttribute("data-filled", String(Math.ceil(21.5 / 8)));
    await expect(page.getByTestId("desk-m-risk-sub")).toHaveText("Volatility 21.5% a year");
    await noSideScroll(page);

    // Investor wording for the patterns; same rows.
    await page.getByTestId("desk-persona-pill").click();
    for (let i = 0; i < want.length; i += 1) await expect(rows.nth(i).getByTestId("desk-top-opp-pattern")).toHaveText(want[i].plain);

    // A row opens its chart; See all opens the scanner.
    await rows.first().click();
    await expect(desk(page)).toHaveAttribute("data-tab", "chart");
    await expect(desk(page)).toHaveAttribute("data-symbol", "TESTPICK");
    await page.goto(`${DESK}?tab=overview`);
    await page.getByTestId("desk-top-opps-all").click();
    await expect(desk(page)).toHaveAttribute("data-tab", "scanner");
  });

  test("M1: no holdings and a failed risk read show “—” with the reason, never 0", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await overviewApi(page);
    await page.route("**/api/portfolio/holdings-enriched*", (route) => json(route, { holdings: [], totals: null, alerts: [] }));
    await page.route("**/api/portfolio/risk-analytics", (route) => json(route, { detail: "fixture failure" }, 500));
    await mockChat(page);
    await page.goto(DESK);
    await expect(page.getByTestId("desk-m-portfolio-value")).toHaveText("—");
    await expect(page.getByTestId("desk-m-portfolio-sub")).toHaveText(/No holdings on record|Didn’t load/);
    await expect(page.getByTestId("desk-m-risk-value")).toHaveText("—", { timeout: 15_000 });
    await expect(page.getByTestId("desk-m-risk-sub")).toHaveText("Didn’t load", { timeout: 15_000 });
    await expect(page.getByTestId("desk-m-risk-bar")).toHaveAttribute("data-filled", "0");
  });
});

// ── design-fidelity screenshots (design-spec §2, §3, §9, §11) ───────────

/** Screenshots for the design comparison land in test-results/ (git-ignored); they assert nothing on their own. */
const SHOTS = "test-results/fidelity-shots";

test.describe("Smart trading desk — frame · fidelity screenshots", () => {
  test("fidelity screenshots: overview at 1440 with the dock, and at 390", async ({ page }) => {
    const phase = "after";
    await overviewApi(page);
    await page.route("**/api/portfolio/risk-analytics", (route) => json(route, RISK));
    await mockChat(page);
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto(DESK);
    await expect(page.getByTestId("desk-index-tile").first()).toBeVisible();
    await page.waitForTimeout(800);
    await page.screenshot({ path: `${SHOTS}/fidelity-area1-${phase}-1440.png` });
    await page.setViewportSize({ width: 1440, height: 1900 });
    await page.waitForTimeout(400);
    await page.screenshot({ path: `${SHOTS}/fidelity-area1-${phase}-1440-full.png` });
    await page.getByTestId("desk-dock").getByTestId("dock-chips").getByRole("button").first().click();
    await expect(page.getByTestId("dock-answer")).toBeVisible();
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.getByTestId("desk-tab-more").click();
    await page.waitForTimeout(400);
    await page.screenshot({ path: `${SHOTS}/fidelity-area1-${phase}-1440-more.png` });

    await page.setViewportSize({ width: 1280, height: 1500 });
    await page.goto(DESK);
    await expect(page.getByTestId("desk-index-tile").first()).toBeVisible();
    await page.waitForTimeout(800);
    await page.screenshot({ path: `${SHOTS}/fidelity-area1-${phase}-1280-full.png` });

    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto(DESK);
    await expect(page.getByTestId("desk-index-tile").first()).toBeVisible();
    await page.waitForTimeout(800);
    await page.screenshot({ path: `${SHOTS}/fidelity-area1-${phase}-390.png` });
    await page.setViewportSize({ width: 390, height: 2000 });
    await page.waitForTimeout(400);
    await page.screenshot({ path: `${SHOTS}/fidelity-area1-${phase}-390-full.png` });
    await page.setViewportSize({ width: 390, height: 844 });
    await page.getByTestId("desk-tab-more").click();
    // The thread from the 1440 step is restored first; the new question adds a second turn.
    await expect(page.getByTestId("dock-turn")).toHaveCount(1);
    await page.getByTestId("dock-input").fill("What moved banks?");
    await page.getByTestId("dock-send").click();
    await expect(page.getByTestId("dock-turn")).toHaveCount(2);
    await expect(page.getByTestId("dock-answer").last()).toBeVisible();
    await page.waitForTimeout(400);
    await page.screenshot({ path: `${SHOTS}/fidelity-area1-${phase}-390-more.png` });
  });
});
