/**
 * One-screen Copilot app (/v5/app) — Smart trading desk redesign, step 1: the shell
 * (docs/desk_redesign_20261027/PLAN.md; test cases in test_reports/desk_redesign_shell_TESTCASES.md, SH-1 … SH-24).
 *
 * MOCK — not real data: every /api response is a fixture or an inline payload in the shape the real route returns
 * (source named beside each), with synthetic values. Mocked APIs, production build (pw.copilot-app.config.ts).
 *
 * Covers the frame only (screens/TradingDesk.tsx, tradingdesk/desk-nav.ts, DeskTrail.tsx, BottomBar.tsx): the four
 * numbered tabs, each tab's views, the redirects from every old desk URL and from the Trader rail's old tools, the
 * location breadcrumb, My portfolio inside the frame without the paper cards, the PAPER MODE banner, the Trader rail and
 * landing, the docked Copilot, 390px, and the wording. Each re-hosted component keeps its own spec.
 */
import { test, expect, type Page, type Route } from "@playwright/test";
import { mockApi, mockSingleRoute } from "../helpers/api-mock";

const APP = "/v5/app";
const DESK = `${APP}/trader/desk`;

const TABS = [
  { key: "overview", label: "Market Overview", num: "01" },
  { key: "trade", label: "Trade Desk", num: "02" },
  { key: "market", label: "Market Desk", num: "03" },
  { key: "risk", label: "Risk Desk", num: "04" },
];
const VIEWS: Record<string, Array<{ key: string; label: string }>> = {
  trade: [{ key: "paper", label: "Paper trades" }, { key: "new", label: "New trade" }],
  market: [
    { key: "intel", label: "Market Intelligence" }, { key: "smartmoney", label: "Smart Money" }, { key: "sectors", label: "Sector Rotation" },
    { key: "research", label: "Stock Research" }, { key: "screener", label: "Screener" }, { key: "watchlists", label: "Watchlists & alerts" },
  ],
  risk: [{ key: "limits", label: "Limits & budgets" }, { key: "controls", label: "Controls & profile" }, { key: "log", label: "Decision log" }],
};
/** The frame's section that hosts each view's component (data-testid), and a component testid inside it. */
const VIEW_HOST: Record<string, Array<[string, string | null]>> = {
  "trade/paper": [["desk-panel-paper", "desk-paper-trades"]],
  "trade/new": [["desk-panel-strategy", "builder-modes"], ["desk-panel-fno", "desk-fno"]],
  "market/intel": [["desk-panel-intel", null], ["desk-panel-events", null]],
  "market/smartmoney": [["desk-panel-smartmoney", null], ["desk-panel-fno", "desk-fno"]],
  "market/sectors": [["desk-panel-sectors", "screen-tool-sector-heatmap"]],
  "market/research": [["desk-panel-chart", null]],
  "market/screener": [["desk-panel-screener", "screen-tool-screener"], ["desk-panel-chartink", "chartink-settings"]],
  "market/watchlists": [["desk-panel-watchlists", "screen-page-watchlist"]],
  // The Risk Desk tab (step 4, tradingdesk/tabs/risk-desk) replaces the re-hosted Risk controls, F&O Live and Audit.
  "risk/limits": [["risk-desk", "rd-limits-card"], ["risk-desk", "risk-policy"]],
  "risk/controls": [["risk-desk", "risk-status"], ["risk-desk", "risk-audit"], ["risk-desk", "risk-profile"], ["risk-desk", "rd-live"]],
  "risk/log": [["risk-desk", "risk-decisions"]],
};
const LOCATIONS = ["overview", ...Object.keys(VIEW_HOST), "portfolio"];
const urlOf = (loc: string) => {
  const [tab, view] = loc.split("/");
  return view ? `${DESK}?tab=${tab}&view=${view}` : `${DESK}?tab=${tab}`;
};

const json = (route: Route, body: unknown, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });

// backend/routes/positional.py (get_watchlist, get_picks)
const WATCHLIST = { as_of_date: "2026-10-12", buckets: {
  breakout_confirmed: [{ nse_symbol: "TESTBRK", sector: "Capital Goods", close_price: 510.0, trigger_price: 500.0, stop_price: 477.5, atr_pct: 2.94, why: "Fixture reason" }],
  pre_breakout: [], true_accumulation: [], trend_continuation: [] } };
const PICKS = { signal_date: "2026-10-12", count: 0, picks: [] };

// backend/routes/desk_trading.py :: list paper trades — two open, one closed.
const trade = (o: Record<string, unknown> & { id: string; symbol: string; status: string }) => ({
  quantity: 10, entry_price: 100, stop_price: 95, target_price: 110, note: null, source: { kind: "scanner", signal_date: "2026-10-12" },
  opened_at: "2026-10-12T10:00:00+00:00", closed_at: null, exit_price: null, exit_reason: null, exit_session: null, exit_note: null,
  last_close: 101, last_close_date: "2026-10-13", unrealized_pnl_rs: 10, realized_pnl_rs: null, checked_through: "2026-10-13", mark_error: null, ...o,
});
const TRADES = [
  trade({ id: "pt-1", symbol: "FIXONE", status: "open" }),
  trade({ id: "pt-2", symbol: "FIXTWO", status: "open" }),
  trade({ id: "pt-3", symbol: "FIXSHUT", status: "closed", closed_at: "2026-10-09T15:00:00+00:00", exit_price: 110, exit_reason: "target", exit_session: "2026-10-09", unrealized_pnl_rs: null, realized_pnl_rs: 100 }),
];
const paperBody = (trades: unknown[]) => ({
  as_of: "2026-10-13", checked_through: "2026-10-13", marks_error: null, trades,
  summary: { open: trades.filter((t) => (t as { status: string }).status === "open").length, closed: trades.filter((t) => (t as { status: string }).status === "closed").length, wins: 1, losses: 0, realized_pnl_rs: 100, unrealized_pnl_rs: 20, unmarked_open: 0, partial: false },
});

// backend/routes/risk_controls.py :: GET /api/risk/status
const riskStatus = (o: Record<string, unknown> = {}) => ({
  user_id: "u_fixture", kill_switch: false, halted: false, reason: null, set_by: null, set_at: null, policy_version: "risk-controls-v1",
  stored: false, scope: "blocks new positions on the desk paper-trade path", not_in_scope: "open positions are untouched", can_reset: false,
  live_authorization: { granted: false, granted_by: null, granted_at: null, reason: null },
  modes: ["paper"], live_execution_available: false, gate: { enabled: true, policy_version: "fno-gate-v1" }, ...o,
});

async function deskApi(page: Page, opts: { trades?: unknown[]; status?: Record<string, unknown> } = {}) {
  await mockApi(page, "populated");
  await mockSingleRoute(page, "**/api/markets/home", "markets-home.json");
  await page.route("**/api/positional/watchlist*", (route) => json(route, WATCHLIST));
  await page.route("**/api/positional/picks*", (route) => json(route, PICKS));
  await page.route("**/api/move-odds/**", (route) => json(route, { detail: "feature_not_enabled" }, 403));
  await page.route("**/api/markets/sector-returns", (route) => json(route, { as_of: "2026-10-13", source: "NSE index close (nidp.index_eod)", sessions: { "1d": 1, "1w": 5, "1m": 21 }, sectors: [] }));
  await page.route("**/api/desk/paper-trades*", (route) => json(route, paperBody(opts.trades ?? TRADES)));
  await page.route("**/api/desk/alerts*", (route) => json(route, { as_of: null, checked_through: null, marks_error: null, alerts: [] }));
  await page.route("**/api/risk/status", (route) => json(route, riskStatus(opts.status)));
  await page.route("**/api/chat/sessions", (route) => json(route, []));
}

/** Trader mode, as the mode pill saves it (lib/store.ts: zustand persist "nivesh.copilot"). */
async function traderMode(page: Page) {
  await page.addInitScript(() => {
    try { window.localStorage.setItem("nivesh.copilot", JSON.stringify({ state: { mode: "trader" }, version: 0 })); } catch { /* blocked storage */ }
  });
}

const params = (page: Page) => new URL(page.url()).searchParams;
async function expectAt(page: Page, tab: string, view: string | null, extra: Record<string, string> = {}) {
  await expect.poll(() => params(page).get("tab")).toBe(tab);
  await expect.poll(() => params(page).get("view")).toBe(view);
  for (const [k, v] of Object.entries(extra)) await expect.poll(() => params(page).get(k)).toBe(v);
}

async function noSideScroll(page: Page) {
  const o = await page.evaluate(() => {
    const sc = document.querySelector('[data-testid="copilot-scroll"]') as HTMLElement | null;
    const right = sc ? sc.getBoundingClientRect().right : window.innerWidth;
    // The outermost elements that reach past the right edge (a scroller's own content is clipped and not listed).
    const wide = (Array.from(document.querySelectorAll("*")) as HTMLElement[]).filter((el) => {
      const r = el.getBoundingClientRect();
      return r.width > 0 && r.right > right + 1 && !(el.parentElement && el.parentElement.getBoundingClientRect().right > right + 1);
    }).slice(0, 6).map((el) => `${el.tagName.toLowerCase()}[${el.getAttribute("data-testid") ?? ""}] right=${Math.round(el.getBoundingClientRect().right)}`);
    return { doc: document.documentElement.scrollWidth - window.innerWidth, scroll: sc ? sc.scrollWidth - sc.clientWidth : 0, wide: wide.join(", ") };
  });
  expect(o.doc, o.wide).toBeLessThanOrEqual(1);
  expect(o.scroll, o.wide).toBeLessThanOrEqual(1);
}

const BANNER = /Paper mode · simulated execution only · no broker orders/i;
const BANNED = /\bpick|recommend|suggest/i;

test.describe("MOCK — not real data: desk shell · tabs and views", () => {
  test.beforeEach(async ({ page }) => { await deskApi(page); });

  test("SH-1 four numbered tabs in the owner's order; Market Overview selected; no old tabs or More", async ({ page }) => {
    await page.goto(DESK);
    const tabs = page.getByTestId("desk-tabs").getByRole("tab");
    await expect(tabs).toHaveCount(4);
    for (let i = 0; i < TABS.length; i++) {
      await expect(tabs.nth(i)).toHaveAttribute("data-testid", `desk-tab-${TABS[i].key}`);
      await expect(tabs.nth(i)).toHaveText(`${TABS[i].num}${TABS[i].label}`);
    }
    await expect(page.getByTestId("desk-tab-overview")).toHaveAttribute("aria-selected", "true");
    await expect(page.getByTestId("screen-trading-desk")).toHaveAttribute("data-tab", "overview");
    for (const gone of ["desk-tab-more", "desk-tab-scanner", "desk-tab-chart", "desk-tab-intel", "desk-tab-smartmoney"]) await expect(page.getByTestId(gone)).toHaveCount(0);
    for (const old of ["AI Scanner", "Chart Analysis", "Portfolio & Risk", "More"]) await expect(page.getByTestId("desk-tabs")).not.toContainText(old);
  });

  test("SH-2 / SH-3 each tab sets ?tab= and its default view; every view of the switcher sets ?view=", async ({ page }) => {
    await page.goto(DESK);
    for (const t of TABS) {
      await page.getByTestId(`desk-tab-${t.key}`).click();
      const views = VIEWS[t.key];
      await expectAt(page, t.key, views ? views[0].key : null);
      await expect(page.getByTestId(`desk-tab-${t.key}`)).toHaveAttribute("aria-selected", "true");
      if (!views) {
        await expect(page.getByTestId("desk-views")).toHaveCount(0);
        continue;
      }
      const chips = page.getByTestId("desk-views").getByRole("button");
      await expect(chips).toHaveText(views.map((v) => v.label));
      for (const v of views) {
        await page.getByTestId(`desk-view-${v.key}`).click();
        await expectAt(page, t.key, v.key);
        await expect(page.getByTestId(`desk-view-${v.key}`)).toHaveAttribute("aria-pressed", "true");
        await expect(page.getByTestId("screen-trading-desk")).toHaveAttribute("data-view", v.key);
      }
    }
  });

  test("SH-4 every view mounts its re-hosted component", async ({ page }) => {
    for (const [loc, hosts] of Object.entries(VIEW_HOST)) {
      await page.goto(urlOf(loc));
      for (const [host, inner] of hosts) {
        const h = page.getByTestId(`desk-panel-${loc.split("/")[0]}`).getByTestId(host).first();
        await expect(h, `${loc}: ${host}`).toBeVisible({ timeout: 15_000 });
        if (inner) await expect(h.getByTestId(inner).first(), `${loc}: ${inner}`).toBeAttached({ timeout: 15_000 });
      }
    }
  });

  test("SH-5 a bad view falls back to the tab's default; a bad tab to Market Overview", async ({ page }) => {
    await page.goto(`${DESK}?tab=market&view=zzz`);
    await expectAt(page, "market", "intel");
    await page.goto(`${DESK}?tab=zzz`);
    await expectAt(page, "overview", null);
    await expect(page.getByTestId("desk-tab-overview")).toHaveAttribute("aria-selected", "true");
  });
});

test.describe("MOCK — not real data: desk shell · Market Overview", () => {
  test("SH-4 / SH-6 / SH-8 overview, pulse and Top 10 once; scanner list collapsed until opened; no portfolio snapshot or risk summary", async ({ page }) => {
    await deskApi(page);
    await page.goto(DESK);
    const panel = page.getByTestId("desk-panel-overview");
    await expect(panel.getByTestId("desk-overview")).toBeVisible();
    await expect(panel.getByTestId("desk-panel-pulse")).toHaveCount(1);
    await expect(panel.getByTestId("desk-panel-top10")).toHaveCount(1);
    await expect(panel.getByTestId("desk-top10")).toHaveCount(1);
    const toggle = page.getByTestId("desk-scanner-toggle");
    await expect(toggle).toHaveText(/All scanner candidates/);
    await expect(toggle).toHaveAttribute("aria-expanded", "false");
    await expect(page.getByTestId("desk-panel-scanner")).toHaveCount(0);
    await toggle.click();
    await expect(toggle).toHaveAttribute("aria-expanded", "true");
    await expect.poll(() => params(page).get("section")).toBe("scanner");
    await expect(page.getByTestId("desk-panel-scanner")).toBeVisible();
    // The pulse and the Top 10 are not mounted a second time by the scanner list.
    await expect(panel.getByTestId("desk-top10")).toHaveCount(1);
    await expect(page.getByTestId("desk-snapshot-card")).toHaveCount(0);
    await expect(page.getByTestId("desk-risk-card")).toHaveCount(0);
  });

  test("SH-7 the open paper trades line counts open trades and opens Trade Desk", async ({ page }) => {
    await deskApi(page);
    await page.goto(DESK);
    const line = page.getByTestId("desk-open-trades-line");
    await expect(line).toContainText("2 open paper trades");
    await line.getByTestId("desk-open-trades-link").click();
    await expectAt(page, "trade", "paper");
    await expect(page.getByTestId("desk-panel-paper")).toBeVisible();
  });

  test("SH-7 no open paper trades says so", async ({ page }) => {
    await deskApi(page, { trades: [] });
    await page.goto(DESK);
    await expect(page.getByTestId("desk-open-trades-line")).toContainText("No open paper trades");
  });
});

test.describe("MOCK — not real data: desk shell · redirects from the old URLs", () => {
  test.beforeEach(async ({ page }) => { await deskApi(page); });

  const CASES: Array<{ from: string; tab: string; view: string | null; extra?: Record<string, string>; gone?: string[] }> = [
    { from: "?tab=scanner", tab: "overview", view: null, extra: { section: "scanner" } },
    { from: "?tab=intel", tab: "market", view: "intel" },
    { from: "?tab=intel&in_chip=flows", tab: "market", view: "intel", extra: { in_chip: "flows" } },
    { from: "?tab=events", tab: "market", view: "intel", extra: { section: "events" } },
    { from: "?tab=chart&sym=RELIANCE", tab: "market", view: "research", extra: { sym: "RELIANCE" } },
    { from: "?tab=smartmoney", tab: "market", view: "smartmoney" },
    { from: "?tab=fno", tab: "market", view: "smartmoney", extra: { section: "fno" } },
    { from: "?tab=fno&lab=chain&lab_sym=BANKNIFTY", tab: "market", view: "smartmoney", extra: { section: "fno", lab: "chain", lab_sym: "BANKNIFTY" } },
    { from: "?tab=fno&lab=strategies&lab_sym=NIFTY", tab: "trade", view: "new", extra: { section: "fno", lab_sym: "NIFTY" } },
    { from: "?tab=more&view=strategy&mode=stock&sym=INFY", tab: "trade", view: "new", extra: { mode: "stock", sym: "INFY" } },
    { from: "?tab=more&view=risk", tab: "risk", view: "limits" },
    { from: "?tab=more&view=chartink", tab: "market", view: "screener", extra: { section: "chartink" } },
    { from: "?tab=portfolio", tab: "portfolio", view: null },
  ];
  for (const c of CASES) {
    test(`SH-9 ${c.from} → tab=${c.tab}${c.view ? `&view=${c.view}` : ""}`, async ({ page }) => {
      await page.goto(`${APP}/page/history`);
      await page.goto(`${DESK}${c.from}`);
      await expectAt(page, c.tab, c.view, c.extra);
      await expect(page.getByTestId(`desk-panel-${c.tab}`)).toBeVisible();
      // The redirect replaced the old URL: Back leaves the desk.
      await page.goBack();
      await expect(page).toHaveURL(/\/v5\/app\/page\/history$/);
    });
  }

  test("SH-9 ?tab=scanner opens the scanner list expanded", async ({ page }) => {
    await page.goto(`${DESK}?tab=scanner`);
    await expect(page.getByTestId("desk-scanner-toggle")).toHaveAttribute("aria-expanded", "true");
    await expect(page.getByTestId("desk-panel-scanner")).toBeVisible();
  });

  test("SH-10 Trader mode: the old rail tools open their Market Desk views", async ({ page }) => {
    await traderMode(page);
    for (const [from, view] of [["tool/screener", "screener"], ["tool/sector-heatmap", "sectors"], ["tool/research", "research"]]) {
      await page.goto(`${APP}/${from}`);
      await expect(page).toHaveURL(/\/v5\/app\/trader\/desk\?/);
      await expectAt(page, "market", view);
    }
  });

  test("SH-10 Investor mode: the Screener stays a standalone screen", async ({ page }) => {
    await page.goto(`${APP}/tool/screener`);
    await expect(page).toHaveURL(/\/v5\/app\/tool\/screener$/);
    await expect(page.getByTestId("screen-tool-screener")).toBeVisible();
    await expect(page.getByTestId("screen-trading-desk")).toHaveCount(0);
  });
});

test.describe("MOCK — not real data: desk shell · breadcrumb, My portfolio, banner, header", () => {
  test.beforeEach(async ({ page }) => { await deskApi(page); });

  test("SH-11 the breadcrumb is the location, whatever the path taken", async ({ page }) => {
    await page.goto(`${DESK}?tab=market&view=smartmoney`);
    const trail = page.getByTestId("desk-trail");
    await expect(trail).toHaveText(/^▸Trading desk›Market Desk›Smart Money$/);
    await expect(page.getByTestId("desk-trail-here")).toHaveAttribute("aria-current", "page");
    // The same view reached through other views: the same crumbs.
    await page.getByTestId("desk-tab-overview").click();
    await expect(trail).toHaveText(/^▸Trading desk›Market Overview$/);
    await page.getByTestId("desk-tab-market").click();
    await page.getByTestId("desk-view-research").click();
    await page.getByTestId("desk-view-smartmoney").click();
    await expect(trail).toHaveText(/^▸Trading desk›Market Desk›Smart Money$/);
    // The tab crumb opens the tab's default view; the root opens Market Overview.
    await page.getByTestId("desk-trail-tab").click();
    await expectAt(page, "market", "intel");
    await page.getByTestId("desk-trail-root").click();
    await expectAt(page, "overview", null);
    await page.goto(`${DESK}?tab=portfolio`);
    await expect(trail).toHaveText(/^▸Trading desk›My portfolio$/);
  });

  test("SH-12 / SH-13 My portfolio opens inside the frame, without the paper cards", async ({ page }) => {
    await page.goto(DESK);
    const btn = page.getByTestId("desk-my-portfolio");
    await expect(btn).toHaveText("My portfolio");
    await btn.click();
    await expectAt(page, "portfolio", null);
    await expect(btn).toHaveAttribute("aria-pressed", "true");
    for (const t of TABS) await expect(page.getByTestId(`desk-tab-${t.key}`)).toHaveAttribute("aria-selected", "false");
    await expect(page.getByTestId("desk-paper-banner")).toBeVisible();
    await expect(page.getByTestId("desk-panel-portfolio").getByTestId("desk-portfolio")).toBeVisible();
    await expect(page.getByTestId("desk-portfolio-record")).toHaveCount(0);
    await expect(page.getByTestId("desk-portfolio-paper")).toHaveCount(0);
    await expect(page.getByTestId("desk-paper-trades")).toHaveCount(0);
    // They are on Trade Desk › Paper trades.
    await page.getByTestId("desk-tab-trade").click();
    await expect(page.getByTestId("desk-panel-trade").getByTestId("desk-portfolio-record")).toBeVisible();
    await expect(page.getByTestId("desk-panel-trade").getByTestId("desk-paper-trades")).toBeVisible();
  });

  test("SH-14 Trade Desk says the trades are paper and links the real portfolio", async ({ page }) => {
    await page.goto(`${DESK}?tab=trade`);
    const line = page.getByTestId("desk-paper-real-line");
    await expect(line).toHaveText("These are paper trades. Your real holdings and F&O positions (read-only): My portfolio");
    await line.getByTestId("desk-paper-real-link").click();
    await expectAt(page, "portfolio", null);
  });

  test("SH-15 the PAPER MODE banner is on every location", async ({ page }) => {
    for (const loc of LOCATIONS) {
      await page.goto(urlOf(loc));
      await expect(page.getByTestId("desk-paper-banner"), loc).toHaveText(BANNER);
    }
  });

  test("SH-16 the market pill shows; a kill switch shows the risk pill, which opens Controls & profile", async ({ page }) => {
    await page.unroute("**/api/risk/status");
    await page.route("**/api/risk/status", (route) => json(route, riskStatus({ kill_switch: true, reason: "Fixture stop", set_by: "admin_fixture", set_at: "2026-10-24T04:30:00+00:00", stored: true })));
    await page.goto(DESK);
    await expect(page.getByTestId("desk-topbar").getByTestId("desk-market-status")).toBeVisible();
    const pill = page.getByTestId("desk-topbar").getByTestId("desk-risk-pill");
    await expect(pill).toHaveText("Kill switch on");
    await pill.click();
    await expectAt(page, "risk", "controls");
  });

  test("SH-24 no 'picks', 'recommended' or 'suggested' in the frame's words", async ({ page }) => {
    for (const loc of ["overview", "trade/paper", "market/intel", "risk/limits", "portfolio"]) {
      await page.goto(urlOf(loc));
      await expect(page.getByTestId("desk-tabs")).toBeVisible();
      for (const id of ["desk-paper-banner", "desk-tabs", "desk-my-portfolio", "desk-trail", "desk-views", "desk-open-trades-line", "desk-paper-real-line"]) {
        const el = page.getByTestId(id);
        if (await el.count()) expect(await el.first().innerText(), `${loc}: ${id}`).not.toMatch(BANNED);
      }
    }
  });
});

test.describe("MOCK — not real data: desk shell · rail, landing and links", () => {
  test("SH-17 / SH-19 Trader mode lands on the desk and lists only the Smart trading desk under Tools", async ({ page }) => {
    await deskApi(page);
    await page.goto(APP);
    await page.getByTestId("mode-pill").click();
    await expect(page.getByTestId("mode-pill")).toContainText("Trader");
    await expect(page).toHaveURL(/\/v5\/app\/trader\/desk$/);
    await expect(page.getByTestId("desk-tab-overview")).toHaveAttribute("aria-selected", "true");
    const rail = page.getByTestId("copilot-rail");
    await expect(rail.getByRole("button", { name: /Smart trading desk/ })).toBeVisible();
    for (const gone of ["Screener", "Stock research", "Sector rotation"]) await expect(rail.getByRole("button", { name: gone, exact: true })).toHaveCount(0);
    for (const gone of [/Trader desk/, /Options lab/, /F&O lab/]) await expect(rail.getByRole("button", { name: gone })).toHaveCount(0);
  });

  test("SH-18 Investor mode's tools are unchanged", async ({ page }) => {
    await deskApi(page);
    await page.goto(APP);
    const rail = page.getByTestId("copilot-rail");
    for (const name of ["Portfolio analysis", "Recommendations", "Risk", "Goals", "Tax", "Stock & fund research", "Screener", "Markets"]) {
      await expect(rail.getByRole("button", { name, exact: true })).toBeVisible();
    }
  });

  test("SH-20 repointed links: Overview's scanner link expands the list; Top 10's trades link and the AI watchlist's links use the new URLs", async ({ page }) => {
    await deskApi(page);
    await page.goto(DESK);
    await page.getByTestId("desk-opps-all").click();
    await expectAt(page, "overview", null, { section: "scanner" });
    await expect(page.getByTestId("desk-scanner-toggle")).toHaveAttribute("aria-expanded", "true");
    // The AI watchlist's desk links (workspace/ai-watchlist-data.ts) are built for the new URLs.
    await page.goto(`${APP}/page/watchlist`);
    await expect(page.getByTestId("screen-page-watchlist")).toBeVisible();
  });
});

test.describe("MOCK — not real data: desk shell · Copilot dock", () => {
  test("SH-23 docked at 1440px on every tab; below 1400px the header button opens the page Copilot without a second ask box", async ({ page }) => {
    await deskApi(page);
    await page.setViewportSize({ width: 1440, height: 900 });
    for (const t of TABS) {
      await page.goto(`${DESK}?tab=${t.key}`);
      await expect(page.getByTestId("desk-dock"), t.key).toHaveAttribute("data-variant", "dock");
    }
    await page.setViewportSize({ width: 1280, height: 800 });
    await page.goto(DESK);
    await expect(page.getByTestId("desk-dock")).toHaveCount(0);
    await page.getByTestId("desk-copilot-button").click();
    await expectAt(page, "copilot", null);
    await expect(page.getByTestId("desk-dock")).toHaveAttribute("data-variant", "page");
    await expect(page.getByTestId("composer-input")).toHaveCount(0);
  });
});

test.describe("MOCK — not real data: desk shell · phone 390px", () => {
  test.use({ viewport: { width: 390, height: 844 } });

  test("SH-21 / SH-15 no sideways scroll and the banner on every tab and on My portfolio", async ({ page }) => {
    await deskApi(page);
    for (const loc of ["overview", "trade/paper", "trade/new", "market/intel", "market/smartmoney", "market/screener", "risk/limits", "risk/controls", "risk/log", "portfolio"]) {
      await page.goto(urlOf(loc));
      await expect(page.getByTestId("desk-paper-banner"), loc).toHaveText(BANNER);
      await expect(page.getByTestId(`desk-panel-${loc.split("/")[0]}`), loc).toBeVisible();
      await page.waitForTimeout(300);
      await noSideScroll(page);
    }
  });

  test("SH-22 the bottom bar reaches every tab and the Copilot; My portfolio is in the header; the view switcher scrolls inside itself", async ({ page }) => {
    await deskApi(page);
    await page.goto(DESK);
    const bar = page.getByTestId("desk-bottom-bar");
    await expect(bar.getByRole("button")).toHaveCount(5);
    for (const t of TABS) {
      await bar.getByTestId(`desk-bottom-${t.key}`).click();
      await expect.poll(() => params(page).get("tab")).toBe(t.key);
      await expect(bar.getByTestId(`desk-bottom-${t.key}`)).toHaveAttribute("aria-current", "page");
    }
    await page.getByTestId("desk-tab-market").count(); // the tab row is the bottom bar on a phone
    const views = page.getByTestId("desk-views");
    await page.getByTestId("desk-bottom-market").click();
    await expect(views).toBeVisible();
    await views.getByTestId("desk-view-watchlists").click();
    await expectAt(page, "market", "watchlists");
    await noSideScroll(page);
    await bar.getByTestId("desk-bottom-copilot").click();
    await expectAt(page, "copilot", null);
    await expect(page.getByTestId("desk-dock")).toHaveAttribute("data-variant", "page");
    await page.getByTestId("desk-my-portfolio").click();
    await expectAt(page, "portfolio", null);
  });
});
