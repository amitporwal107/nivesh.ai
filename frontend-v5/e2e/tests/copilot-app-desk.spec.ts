/**
 * One-screen Copilot app (/v5/app) — Smart trading desk: the shell.
 *
 * MOCK — not real data: every /api response here is a fixture or an inline
 * payload in the shape the real route returns (source named beside each), with
 * synthetic values. Expected figures are worked out from the payload, not
 * copied from the screen. Mocked APIs, production build — see
 * pw.copilot-app.config.ts.
 *
 * Covers screens/TradingDesk.tsx and screens/tradingdesk/CopilotDock.tsx: the
 * Trader rail entry, the six tabs and their URL (?tab=&sym=), the docked
 * Copilot from 1400px (asked in the trader persona, its own thread, "Full
 * thread"), the shell's ask box below 1400px, a failed answer, and a 390px
 * pass. Each tab's own blocks are covered by copilot-app-desk-*.spec.ts.
 */
import { test, expect, type Page, type Route } from "@playwright/test";
import { mockApi, mockSingleRoute } from "../helpers/api-mock";

const APP = "/v5/app";
const DESK = `${APP}/trader/desk`;
const TABS = ["overview", "scanner", "chart", "intel", "portfolio", "fno"];
const LABELS = ["Overview", "AI scanner", "Chart analysis", "Market intelligence", "Portfolio & risk", "Options & futures lab"];

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
}

async function traderMode(page: Page) {
  await page.addInitScript(() => localStorage.setItem("nivesh.copilot", JSON.stringify({ state: { mode: "trader", evidenceOpen: null }, version: 0 })));
}

const desk = (page: Page) => page.getByTestId("screen-trading-desk");

test.describe("Smart trading desk — shell", () => {
  test.beforeEach(async ({ page }) => {
    await deskApi(page);
  });

  test("TC-1: the Trader rail lists the Smart trading desk first and opens it with six tabs", async ({ page }) => {
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
      await expect(page.getByTestId(`desk-tab-${TABS[i]}`)).toContainText(LABELS[i]);
    }
    await expect(page.getByTestId("desk-tab-overview")).toHaveAttribute("aria-selected", "true");

    // Header: worked out from the payload — TESTBRK (breakout_confirmed) and TESTPICK (stage BREAKOUT) of three setups.
    await expect(page.getByTestId("desk-headline")).toHaveText("2 of 3 scanner setups have confirmed.");
    await expect(desk(page)).toContainText("Broker data read-only");
    await expect(desk(page)).toContainText("No orders placed");
    await expect(page.getByTestId("desk-disclaimer")).toContainText("Nivesh does not place orders");
    await expect(page.getByTestId("desk-disclaimer")).toContainText("SEBI study");
  });

  test("TC-2: a tab click sets ?tab=; a deep link opens that tab with that stock; a bad symbol is dropped", async ({ page }) => {
    await mockChat(page);
    await page.goto(DESK);
    await expect(desk(page)).toHaveAttribute("data-tab", "overview");

    for (const t of ["scanner", "intel", "portfolio", "fno", "chart", "overview"]) {
      await page.getByTestId(`desk-tab-${t}`).click();
      await expect(page).toHaveURL(new RegExp(`[?&]tab=${t}(&|$)`));
      await expect(desk(page)).toHaveAttribute("data-tab", t);
      await expect(page.getByTestId(`desk-tab-${t}`)).toHaveAttribute("aria-selected", "true");
      await expect(page.getByTestId(`desk-panel-${t}`)).toHaveCount(1);
    }

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

  test("TC-4: from 1400px the Copilot is docked, the shell ask box is hidden, and a chip is asked as a trader", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    const chat = await mockChat(page);
    await page.goto(DESK);

    const dock = page.getByTestId("desk-dock");
    await expect(dock).toBeVisible();
    await expect(dock).toContainText("Asked as a trader");
    await expect(page.getByTestId("composer-input")).toHaveCount(0);
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

    // A typed question goes to the same thread.
    await page.getByTestId("dock-input").fill("And for banks?");
    await page.getByTestId("dock-send").click();
    await expect.poll(() => chat.streams.length).toBe(2);
    expect(chat.streams[1]).toMatchObject({ message: "And for banks?", session_id: "desk1", persona: "trader" });
    await expect(dock.getByTestId("dock-turn")).toHaveCount(2);
    expect(chat.created).toBe(1);

    // The thread survives moving between tabs.
    await page.getByTestId("desk-tab-scanner").click();
    await expect(dock.getByTestId("dock-turn")).toHaveCount(2);
    // Beside the dock the desk is too narrow for the scanner's columns, so its rows show as cards.
    await expect(page.getByTestId("desk-scan-cards")).toBeVisible();
    await expect(page.getByTestId("desk-scan-table")).toHaveCount(0);

    // "Full thread" opens it in the app's thread view, where the shell's ask box is back.
    await page.getByTestId("dock-open-thread").click();
    await expect(page).toHaveURL(/\/v5\/app\/t\/desk1$/);
    await expect(page.getByTestId("composer-input")).toBeVisible();
    await expect(page.getByTestId("desk-dock")).toHaveCount(0);

    // "New" starts a fresh conversation.
    await page.goto(DESK);
    await expect(page.getByTestId("dock-turn")).toHaveCount(2);
    await page.getByTestId("dock-new").click();
    await expect(page.getByTestId("dock-turn")).toHaveCount(0);
    await expect(page.getByTestId("desk-dock")).toContainText("Ask about anything on the desk.");
  });

  test("TC-5: below 1400px there is no dock and the shell ask box is there", async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 800 });
    await mockChat(page);
    await page.goto(DESK);
    await expect(desk(page)).toBeVisible();
    await expect(page.getByTestId("desk-dock")).toHaveCount(0);
    await expect(page.getByTestId("composer-input")).toBeVisible();
    // Without the dock there is room for the scanner's full table.
    await page.getByTestId("desk-tab-scanner").click();
    await expect(page.getByTestId("desk-scan-table")).toBeVisible();
    await expect(page.getByTestId("desk-scan-cards")).toHaveCount(0);
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

  test("TC-7: at 390px there is no sideways page scroll and the tab strip scrolls inside itself", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await mockChat(page);
    await page.goto(DESK);
    await expect(desk(page)).toBeVisible();
    await expect(page.getByTestId("desk-dock")).toHaveCount(0);
    await expect(page.getByTestId("composer-input")).toBeVisible();

    const overflow = () => page.evaluate(() => {
      const sc = document.querySelector('[data-testid="copilot-scroll"]') as HTMLElement | null;
      return {
        doc: document.documentElement.scrollWidth - window.innerWidth,
        scroll: sc ? sc.scrollWidth - sc.clientWidth : 0,
      };
    });
    const o = await overflow();
    expect(o.doc).toBeLessThanOrEqual(1);
    expect(o.scroll).toBeLessThanOrEqual(1);

    // Six tabs do not fit in 390px: the strip scrolls, and the last tab is reachable.
    const strip = page.getByRole("tablist", { name: "Desk modules" });
    const fits = await strip.evaluate((el) => el.scrollWidth <= el.clientWidth);
    expect(fits).toBe(false);
    await page.getByTestId("desk-tab-fno").scrollIntoViewIfNeeded();
    await page.getByTestId("desk-tab-fno").click();
    await expect(desk(page)).toHaveAttribute("data-tab", "fno");
    const after = await overflow();
    expect(after.doc).toBeLessThanOrEqual(1);
    expect(after.scroll).toBeLessThanOrEqual(1);
  });
});
