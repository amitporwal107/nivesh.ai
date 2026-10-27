/**
 * One-screen Copilot app (/v5/app) — Smart trading desk redesign, step 6: the duplicate trading screens are removed and
 * every old URL opens its new home (docs/desk_redesign_20261027/PLAN.md §4, scope A; test cases RM-1 … RM-9 in
 * test_reports/desk_remove_duplicates_TESTCASES.md).
 *
 * MOCK — not real data: every /api response is a fixture or an inline payload in the shape the real route returns
 * (source named beside each), with synthetic values. Mocked APIs, production build (pw.copilot-app.config.ts).
 *
 * Covers lib/retired-views.ts (the shell's redirects for /app/trader, tool/optlab and tool/fnolab?screen=…), the
 * /pro-trader and /strategy-builder redirects in routes.tsx, the /research?screen=paper|lab redirect and rail in
 * pages/Research/index.tsx, and the repointed "Backtest in the strategy builder" link. The Kite return path
 * (/v5/app/trader?kite=…) is run end to end in copilot-app-kite-login-notice.spec.ts.
 */
import { test, expect, type Page, type Route } from "@playwright/test";
import { mockApi, mockSingleRoute } from "../helpers/api-mock";

const APP = "/v5/app";
const DESK_PATH = /\/v5\/app\/trader\/desk$/;

const json = (route: Route, body: unknown, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });

// backend/routes/risk_controls.py :: GET /api/risk/status
const RISK_STATUS = {
  user_id: "u_fixture", kill_switch: false, halted: false, reason: null, set_by: null, set_at: null, policy_version: "risk-controls-v1",
  stored: false, scope: "blocks new positions on the desk paper-trade path", not_in_scope: "open positions are untouched", can_reset: false,
  live_authorization: { granted: false, granted_by: null, granted_at: null, reason: null },
  modes: ["paper"], live_execution_available: false, gate: { enabled: true, policy_version: "fno-gate-v1" },
};

/** The desk's reads, as copilot-app-desk-shell.spec.ts mocks them. */
async function deskApi(page: Page) {
  await mockApi(page, "populated");
  await mockSingleRoute(page, "**/api/markets/home", "markets-home.json");
  // backend/routes/positional.py (get_watchlist, get_picks)
  await page.route("**/api/positional/watchlist*", (route) => json(route, { as_of_date: "2026-10-12", buckets: { breakout_confirmed: [], pre_breakout: [], true_accumulation: [], trend_continuation: [] } }));
  await page.route("**/api/positional/picks*", (route) => json(route, { signal_date: "2026-10-12", count: 0, picks: [] }));
  await page.route("**/api/move-odds/**", (route) => json(route, { detail: "feature_not_enabled" }, 403));
  await page.route("**/api/markets/sector-returns", (route) => json(route, { as_of: "2026-10-13", source: "NSE index close (nidp.index_eod)", sessions: { "1d": 1, "1w": 5, "1m": 21 }, sectors: [] }));
  // backend/routes/desk_trading.py :: list paper trades / alerts — none
  await page.route("**/api/desk/paper-trades*", (route) => json(route, { as_of: "2026-10-13", checked_through: "2026-10-13", marks_error: null, trades: [],
    summary: { open: 0, closed: 0, wins: 0, losses: 0, realized_pnl_rs: 0, unrealized_pnl_rs: 0, unmarked_open: 0, partial: false } }));
  await page.route("**/api/desk/alerts*", (route) => json(route, { as_of: null, checked_through: null, marks_error: null, alerts: [] }));
  await page.route("**/api/risk/status", (route) => json(route, RISK_STATUS));
  await page.route("**/api/chat/sessions", (route) => json(route, []));
}

/** Trader mode, as the mode pill saves it (lib/store.ts: zustand persist "nivesh.copilot"). */
async function traderMode(page: Page) {
  await page.addInitScript(() => {
    try { window.localStorage.setItem("nivesh.copilot", JSON.stringify({ state: { mode: "trader" }, version: 0 })); } catch { /* blocked storage */ }
  });
}

const params = (page: Page) => new URL(page.url()).searchParams;
const pathOf = (page: Page) => new URL(page.url()).pathname;

async function expectDesk(page: Page, tab: string | null, view?: string | null, extra: Record<string, string | null> = {}) {
  await expect.poll(() => pathOf(page)).toMatch(DESK_PATH);
  await expect.poll(() => params(page).get("tab")).toBe(tab);
  if (view !== undefined) await expect.poll(() => params(page).get("view")).toBe(view);
  for (const [k, v] of Object.entries(extra)) await expect.poll(() => params(page).get(k)).toBe(v);
}

test.describe("MOCK — not real data: removed trading screens · the old Trader landing", () => {
  test("RM-1 /app/trader opens the desk's Market Overview in Trader mode, replacing the history entry", async ({ page }) => {
    await deskApi(page);
    await traderMode(page);
    await page.goto(`${APP}/page/settings`);
    await expect(page.getByTestId("screen-page-settings")).toBeVisible();
    await page.goto(`${APP}/trader`);
    await expectDesk(page, null);
    await expect(page.getByTestId("desk-overview")).toBeVisible();
    await expect(page.getByTestId("screen-trader")).toHaveCount(0);
    // The redirect replaced /app/trader: Back returns to the page before it.
    await page.goBack();
    await expect.poll(() => pathOf(page)).toBe(`${APP}/page/settings`);
  });

  test("RM-1 /app/trader opens the desk in Investor mode too, never the app home", async ({ page }) => {
    await deskApi(page);
    await page.goto(`${APP}/trader`);
    await expectDesk(page, null);
    await expect(page.getByTestId("desk-overview")).toBeVisible();
  });

  test("RM-1b the old URL's query string is kept (the backend's Kite login returns to /v5/app/trader?kite=…)", async ({ page }) => {
    await deskApi(page);
    await traderMode(page);
    await page.goto(`${APP}/trader?probe=kept`);
    await expectDesk(page, null, undefined, { probe: "kept" });
  });
});

test.describe("MOCK — not real data: removed trading screens · Options lab and F&O lab", () => {
  test.beforeEach(async ({ page }) => {
    await deskApi(page);
    await traderMode(page);
  });

  test("RM-2 tool/optlab opens Market Desk › Smart Money at its F&O section", async ({ page }) => {
    await page.goto(`${APP}/tool/optlab`);
    await expectDesk(page, "market", "smartmoney", { section: "fno" });
    await expect(page.getByTestId("screen-tool-optlab")).toHaveCount(0);
  });

  const LAB: Array<{ screen: string | null; tab: string; view?: string; host?: string }> = [
    { screen: null, tab: "market", view: "smartmoney" },
    { screen: "mi", tab: "market", view: "smartmoney" },
    { screen: "prog", tab: "trade" },
    { screen: "replay", tab: "trade" },
    { screen: "shadow", tab: "trade" },
    { screen: "live", tab: "risk", view: "controls", host: "rd-live" },
    { screen: "cert", tab: "risk", view: "controls", host: "rd-live" },
    { screen: "audit", tab: "risk", view: "log", host: "risk-decisions" },
    { screen: "zzz", tab: "market", view: "smartmoney" },
  ];
  for (const c of LAB) {
    test(`RM-3 tool/fnolab${c.screen ? `?screen=${c.screen}` : ""} → tab=${c.tab}${c.view ? `&view=${c.view}` : ""}`, async ({ page }) => {
      await page.goto(`${APP}/tool/fnolab${c.screen ? `?screen=${c.screen}` : ""}`);
      await expectDesk(page, c.tab, c.view, { screen: null });
      await expect(page.getByTestId("screen-tool-fnolab")).toHaveCount(0);
      if (c.host) await expect(page.getByTestId(c.host)).toBeVisible();
    });
  }
});

test.describe("MOCK — not real data: removed trading screens · standalone URLs", () => {
  test.beforeEach(async ({ page }) => {
    await deskApi(page);
    await traderMode(page);
  });

  for (const from of ["/v5/pro-trader", "/v5/strategy-builder"]) {
    test(`RM-4 / RM-5 ${from} opens the desk's Trade Desk`, async ({ page }) => {
      await page.goto(from);
      await expectDesk(page, "trade");
      await expect(page.getByTestId("strategy-builder-page")).toHaveCount(0);
    });
  }

  test("RM-9 Saved's 'Backtest in the strategy builder' opens the builder inside the shell, not /strategy-builder", async ({ page }) => {
    // backend/routes/strategy_builder.py :: list strategies — one saved stock screen
    await page.route("**/api/strategy-builder/strategies", (route) => json(route, { strategies: [
      { id: "st_fixture1", name: "Fixture momentum", description: "MOCK saved strategy", asset_class: "STOCK", created_at: "2026-10-20T05:00:00+00:00", updated_at: null },
    ] }));
    await page.goto(`${APP}/page/saved`);
    const link = page.getByTestId("saved-strategy").getByRole("link", { name: /Backtest in the strategy builder/ });
    await expect(link).toHaveAttribute("href", `${APP}/trader/strategy`);
    await link.click();
    await expect.poll(() => pathOf(page)).toBe(`${APP}/trader/strategy`);
    await expect(page.getByTestId("screen-trader-strategy")).toBeVisible();
  });
});

test.describe("MOCK — not real data: removed trading screens · Research Paper and Lab", () => {
  /** An account with every Research feature: move odds (Odds, and Paper before), the simulation lab and charts. */
  const ME = { user_id: "u_fixture", email: "fixture@example.test", name: "Fixture User", is_admin: false, onboarding_completed: true,
    features: { research: true, research_only: false, move_odds: true, sim_lab: true, charting: true } };

  test.beforeEach(async ({ page }) => {
    await deskApi(page);
    await page.route("**/api/auth/me", (route) => json(route, ME));
  });

  for (const screen of ["paper", "lab"]) {
    test(`RM-6 /research?screen=${screen} opens /app/page/paper`, async ({ page }) => {
      await page.goto(`/v5/research?screen=${screen}`);
      await expect.poll(() => pathOf(page)).toBe(`${APP}/page/paper`);
      await expect(page.getByTestId("screen-page-paper")).toBeVisible();
    });
  }

  test("RM-7 the Research rail keeps Feed, Alerts, Odds and Charts, and has no Paper or Lab", async ({ page }) => {
    await page.goto("/v5/research");
    for (const id of ["rail-feed", "rail-alerts", "rail-odds", "rail-charts"]) await expect(page.getByTestId(id)).toBeVisible();
    await expect(page.getByTestId("rail-paper")).toHaveCount(0);
    await expect(page.getByTestId("rail-lab")).toHaveCount(0);
  });
});
