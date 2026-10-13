/**
 * One-screen Copilot app (/v5/app) — the tool, workspace, trader, advisor and
 * internal screens.
 *
 * Test-case ids (TC-xx) match test_reports/copilot_one_screen_*.md.
 * Mocked APIs, production build — see pw.copilot-app.config.ts.
 */
import { test, expect, type Page } from "@playwright/test";
import fs from "fs";
import path from "path";
import { mockApi, mockAuthAs, mockSingleRoute } from "../helpers/api-mock";

const APP = "/v5/app";

/** view path below /v5/app → the screen's data-testid */
const VIEWS: Array<[string, string]> = [
  ["tool/analysis", "screen-tool-analysis"],
  ["tool/recommend", "screen-tool-recommend"],
  ["tool/research", "screen-tool-research"],
  ["tool/screener", "screen-tool-screener"],
  ["tool/markets", "screen-tool-markets"],
  ["tool/optlab", "screen-tool-optlab"],
  ["trader", "screen-trader"],
  ["trader/strategy", "screen-trader-strategy"],
  ["page/watchlist", "screen-page-watchlist"],
  ["page/saved", "screen-page-saved"],
  ["page/plan", "screen-page-plan"],
  ["page/ledger", "screen-page-ledger"],
  ["page/paper", "screen-page-paper"],
  ["page/brokers", "screen-page-brokers"],
  ["page/settings", "screen-page-settings"],
  ["advisor", "screen-advisor"],
  // screens of the original v5 app, mounted inside the shell
  ["tool/risk", "screen-tool-risk"],
  ["tool/goals", "screen-tool-goals"],
  ["tool/tax", "screen-tool-tax"],
  ["advisor/workspace", "screen-advisor-workspace"],
  ["advisor/client-360", "screen-advisor-client-360"],
  ["advisor/sip-board", "screen-advisor-sip-board"],
  ["onboarding", "screen-onboarding"],
  ["builder", "screen-builder"],
  ["ops/tools", "screen-ops-tools"],
  ["ops/feeds", "screen-ops-feeds"],
  ["ops/audit", "screen-ops-audit"],
  ["ops/kpis", "screen-ops-kpis"],
];

/**
 * Figures and names that exist only as sample data in the design
 * (frontend-v5/design/nivesh-copilot). None may reach the product.
 */
const DESIGN_SAMPLES = [
  "₹24.8 L", "₹64 Cr", "₹5.2 L", "₹2.10 L", "₹1.25 L", "₹3,045 Cr", "₹1,708 Cr", "22,363",
  "Amit Porwal", "RK Wealth", "ARN-128459", "D. Rao", "K. Verma", "M. Tandon", "B. Sen", "A. Iyer", "S. Khan",
  "TATAMOTORS", "CUMMINSIND", "INDUSINDBK", "CGPOWER",
  "NSDL_CAS_Sep2026", "Retire by 2045", "+0.18R", "47 holdings", "47 HOLDINGS", "ILLUSTRATIVE",
];

async function populated(page: Page) {
  await mockApi(page, "populated");
  await mockSingleRoute(page, "**/api/markets/home", "markets-home.json");
  await page.route("**/api/chat/sessions", (route) => route.fulfill({ status: 200, contentType: "application/json", body: "[]" }));
}

// Soft assertions: one broken screen is reported without hiding the rest.
async function visitAll(page: Page, check: (view: string) => Promise<void>) {
  let errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  for (const [view, testId] of VIEWS) {
    errors = [];
    await page.goto(`${APP}/${view}`);
    await expect.soft(page.getByTestId(testId), `${view} did not render`).toBeVisible();
    // Neither the route error page nor a per-screen crash fallback.
    await expect.soft(page.getByText("Page unavailable"), `${view}: route error page`).toHaveCount(0);
    await expect.soft(page.getByText(/^Copilot · /), `${view}: screen crashed`).toHaveCount(0);
    // The shell stays around every screen.
    await expect.soft(page.getByTestId("composer-input"), `${view}: ask box missing`).toBeVisible();
    await page.waitForLoadState("networkidle");
    await check(view);
    expect.soft(errors, `uncaught error on ${view}`).toEqual([]);
  }
}

test.describe("Copilot app screens — desktop", () => {
  test("TC-17 every rail destination renders", async ({ page }) => {
    test.setTimeout(120_000);
    await populated(page);
    await visitAll(page, async (view) => {
      await expect.soft(page.getByTestId("copilot-rail"), `${view}: rail missing`).toBeVisible();
    });
  });

  test("TC-18 with empty API responses no screen shows the design's sample data", async ({ page }) => {
    test.setTimeout(120_000);
    // Every /api/* call answers 200 {} except the signed-in user.
    await mockAuthAs(page, "user-profile-onboarded.json");
    const check = async (view: string) => {
      const text = await page.getByTestId("copilot-app").innerText();
      for (const sample of DESIGN_SAMPLES) {
        expect.soft(text.includes(sample), `${view || "home"} shows design sample "${sample}"`).toBe(false);
      }
    };
    await page.goto(APP);
    await expect(page.getByTestId("home-headline")).toBeVisible();
    await page.waitForLoadState("networkidle");
    await check("");
    await visitAll(page, check);
  });
});

test.describe("Copilot app screens — phone (390×844)", () => {
  test.use({ viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true });

  test("TC-17 every destination renders without sideways page scroll", async ({ page }) => {
    test.setTimeout(120_000);
    await populated(page);
    await visitAll(page, async (view) => {
      const over = await page.evaluate(() => {
        const sc = document.querySelector('[data-testid="copilot-scroll"]') as HTMLElement | null;
        return {
          doc: document.documentElement.scrollWidth - document.documentElement.clientWidth,
          scroll: sc ? sc.scrollWidth - sc.clientWidth : 0,
        };
      });
      expect.soft(over.doc, `${view}: page scrolls sideways`).toBeLessThanOrEqual(1);
      expect.soft(over.scroll, `${view}: content area scrolls sideways`).toBeLessThanOrEqual(1);
    });
  });
});

// ─────────────────────────────────────────────────────────────────────────
// TC-19 — each wired screen shows the data its endpoint returned.
//
// MOCK — not real data: every response below is a fixture or an inline test
// payload shaped like the real contract (source named beside each). Expected
// values are worked out from the payload, not copied from the screen.
// ─────────────────────────────────────────────────────────────────────────

const FX = path.join(process.cwd(), "e2e", "fixtures");
const load = (name: string) => JSON.parse(fs.readFileSync(path.join(FX, name), "utf-8"));

const json = (page: Page, pattern: string | RegExp, body: unknown, status = 200) =>
  page.route(pattern, (route) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) }));

/** Captures what a screen hands to the Copilot. Returns the sent messages. */
async function mockAsk(page: Page): Promise<string[]> {
  const sent: string[] = [];
  await page.route("**/api/chat/sessions", (route) =>
    route.request().method() === "POST"
      ? route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ session_id: "asked1" }) })
      : route.fulfill({ status: 200, contentType: "application/json", body: "[]" }));
  await page.route("**/api/chat/messages*", (route) => route.fulfill({ status: 200, contentType: "application/json", body: "[]" }));
  await page.route("**/api/chat/stream", (route) => {
    sent.push((route.request().postDataJSON() as { message: string }).message);
    return route.fulfill({ status: 200, contentType: "text/event-stream", body: `data: ${JSON.stringify({ type: "done", content: "ok" })}\n\n` });
  });
  return sent;
}

const ADVISOR_ME = { user_id: "u_adv", email: "advisor@example.test", name: "Fixture Advisor", is_admin: false, onboarding_completed: true, workspace_type: "ADVISORY" };

test.describe("TC-19 screens show their endpoint's data — desktop", () => {
  test.beforeEach(async ({ page }) => { await populated(page); });

  test("Portfolio analysis ← holdings, concentration, overlap, remediation, performance (the old AI Insights and Performance data)", async ({ page }) => {
    await mockSingleRoute(page, "**/api/portfolio/exposure/fund-overlap/matrix*", "fund-overlap-matrix.json");
    await mockSingleRoute(page, "**/api/portfolio/exposure/remediation*", "exposure-remediation.json");
    await mockSingleRoute(page, "**/api/dashboards/performance*", "dashboards-performance-rich.json");
    await mockSingleRoute(page, "**/api/portfolio/value-history*", "portfolio-value-history.json");
    await mockSingleRoute(page, "**/api/portfolio/analytics*", "portfolio-analytics.json");
    await page.goto(`${APP}/tool/analysis`);
    // holdings-enriched.json totals: value 1,03,06,772.4 · invested 84,07,496.59 · pnl 18,99,275.8 (22.59%) · xirr 14.29
    await expect(page.getByTestId("analysis-total-value")).toHaveText("₹1.03 Cr");
    await expect(page.getByTestId("analysis-invested")).toHaveText("₹84.07 L");
    await expect(page.getByTestId("analysis-gain")).toHaveText("+₹18.99 L");
    await expect(page.getByTestId("analysis-gain-pct")).toHaveText("+22.6%");
    await expect(page.getByTestId("analysis-xirr")).toHaveText("14.3%");
    // concentration.json: 10 sector rows returned, first is "Unclassified"; sector Effective N 12.1, HHI 0.0824
    await expect(page.getByTestId("analysis-sector-name")).toHaveCount(10);
    await expect(page.getByTestId("analysis-sector-name").first()).toHaveText("Unclassified");
    await expect(page.getByTestId("analysis-sector-effective-n")).toContainText("12.1");
    await expect(page.getByTestId("analysis-sector-hhi")).toContainText("824");
    // AMC axis: HDFC first at 40.58%, Effective N 4.9
    await page.getByTestId("analysis-tab-amc").click();
    await expect(page.getByTestId("analysis-amc-name").first()).toHaveText("HDFC");
    await expect(page.getByTestId("analysis-amc-effective-n")).toContainText("4.9");
    await expect(page.getByTestId("analysis-amc-largest")).toContainText("40.6%");

    // Concentration ladder (Effective N per axis) and fund overlap
    await page.getByTestId("analysis-section-tab-concentration").click();
    await expect(page.getByTestId("analysis-ladder-row")).toHaveCount(4);
    await expect(page.getByTestId("analysis-ladder-company-n")).toContainText("74.4");
    await expect(page.getByTestId("analysis-ladder-sector-n")).toContainText("12.1");
    await expect(page.getByTestId("analysis-ladder-group-n")).toContainText("5.6");
    await expect(page.getByTestId("analysis-ladder-amc-n")).toContainText("4.9");
    await expect(page.getByTestId("analysis-overlap-pair")).toHaveCount(3); // fund-overlap-matrix.json has three pairs
    await expect(page.getByTestId("analysis-overlap-pct").first()).toContainText("96.5%");

    // Remediation plan
    await page.getByTestId("analysis-section-tab-fix").click();
    await expect(page.getByTestId("analysis-remediation-card")).toHaveCount(2); // exposure-remediation.json
    await expect(page.getByTestId("analysis-remediation-leverage").first()).toContainText("90");
    await expect(page.getByTestId("analysis-remediation-saving").first()).toContainText("₹1,950");

    // Performance — the figures the old Performance page shows, labelled the same way
    await page.getByTestId("analysis-section-tab-performance").click();
    await expect(page.getByTestId("analysis-perf-headline")).toHaveText("You beat the benchmark by 3.2 points");
    await expect(page.getByTestId("analysis-perf-tile-xirr")).toContainText("14.8%");
    await expect(page.getByTestId("analysis-perf-tile-sharpe")).toContainText("1.24");
    await expect(page.getByTestId("analysis-perf-tile-alpha")).toContainText("+3.2pp");
    // portfolio-value-history.json: three months, current value ₹10,25,000 (+2.5% on the first month's ₹10,00,000)
    await expect(page.getByTestId("analysis-value-now")).toContainText("₹10.25 L");
    await expect(page.getByTestId("analysis-value-change")).toContainText("2.5%");
    await expect(page.getByTestId("analysis-value-source")).toContainText("CAS statement · 3 months of history");
    await expect(page.getByTestId("analysis-benchmark-basis")).toContainText("Portfolio XIRR vs Nifty 500 CAGR");
  });

  test("Portfolio ledger ← holdings-enriched", async ({ page }) => {
    await page.goto(`${APP}/page/ledger`);
    await expect(page.getByTestId("ledger-count")).toHaveText("111");
    await expect(page.getByTestId("ledger-market-value")).toHaveText("₹1.03 Cr");
    await expect(page.getByTestId("ledger-invested")).toHaveText("₹84.07 L");
    // holdings-enriched.json health: score 68.56, grade B
    await expect(page.getByTestId("ledger-health-score")).toHaveText("69");
    await expect(page.getByTestId("ledger-health-grade")).toHaveText("B");
    await expect(page.getByTestId("ledger-holding")).toHaveCount(10); // first page of 111
    await expect(page.getByTestId("ledger-corrections-not-connected")).toBeVisible();
  });

  test("Recommendations and Action plan ← plans/active", async ({ page }) => {
    // plans-active.json: 6 PENDING actions; first TRIM ₹7,28,670, second ADD ₹36,05,990; freed capital ₹15,48,029.92
    await page.goto(`${APP}/tool/recommend`);
    await expect(page.getByTestId("recommend-count")).toHaveText("Six");
    await expect(page.getByTestId("recommend-card")).toHaveCount(6);
    await expect(page.getByTestId("recommend-card-title").first()).toHaveText("Trim HDFC Balanced, Advantage Fund -, Regular Plan -, Growth");
    await expect(page.getByTestId("recommend-card-amount").first()).toHaveText("₹7.29 L");
    await expect(page.getByTestId("recommend-card-amount").nth(1)).toHaveText("₹36.06 L");
    await expect(page.getByTestId("recommend-freed")).toHaveText("₹15.48 L");

    await page.goto(`${APP}/page/plan`);
    await expect(page.getByTestId("plan-count-considering")).toHaveText("6");
    await expect(page.getByTestId("plan-count-decided")).toHaveText("0");
    await expect(page.getByTestId("plan-count-done")).toHaveText("0");
    await expect(page.getByTestId("plan-card")).toHaveCount(6);
    await expect(page.getByTestId("plan-card-impact").first()).toHaveText("₹7.29 L");
  });

  test("Markets ← markets/home, and a mover row asks the Copilot", async ({ page }) => {
    const sent = await mockAsk(page);
    await page.goto(`${APP}/tool/markets`);
    // markets-home.json: Nifty 50 24568 (−0.49%), 1200 advances / 800 declines, gainer +4.2%
    await expect(page.locator('[data-testid="markets-index-value"][data-index="Nifty 50"]')).toHaveText("24,568.00");
    await expect(page.getByTestId("markets-breadth")).toHaveText("1,200 advances · 800 declines");
    const movers = page.getByTestId("markets-movers");
    await expect(movers).toContainText("Fixture Gainer Ltd");
    await expect(movers).toContainText("+4.20%");
    await expect(movers).toContainText("−3.10%");
    await movers.getByText("Fixture Gainer Ltd").click();
    await expect(page).toHaveURL(/\/v5\/app\/t\/asked1$/);
    await expect.poll(() => sent).toEqual(["Tell me about Fixture Gainer Ltd"]);
  });

  test("Research ← instrument search + company financials", async ({ page }) => {
    // Shapes: backend/routes/chat.py chat_instrument_search; services/copilot_tools/company_financials.py
    await json(page, "**/api/chat/instrument-search*", { stocks: [{ symbol: "FIXTUREUP", name: "Fixture Gainer Ltd", sector: "Fixture Sector A" }], funds: [] });
    await json(page, "**/api/copilot/widgets/company_financials", {
      kind: "company_financials", title: "FIXTUREUP — Financials & Prospects",
      data: { symbol: "FIXTUREUP", v3_score: { pe_ttm: 24.6, pb: 3.1, roe_pct: 18.2, debt_to_equity: 0.35, market_cap_cr: 15200, market_cap_bucket: "MID_CAP" },
        rows: [{ quarter: "Q1 FY27", period_end: "2026-06-30", revenue_cr: 1200, ebitda_cr: 180, pat_cr: 96, eps_basic: 4.8, ebitda_margin_pct: 15.0, revenue_yoy_pct: 12.0, pat_yoy_pct: -8.5 }] },
    });
    await page.goto(`${APP}/tool/research`);
    await page.getByTestId("research-kind-stock").click();
    await page.getByTestId("research-search").fill("fixture");
    await page.getByTestId("research-search-result").first().click();
    await expect(page.getByTestId("research-entity-name")).toHaveText("Fixture Gainer Ltd");
    await expect(page.getByTestId("research-stock-pe")).toHaveText("24.6×");
    await expect(page.getByTestId("research-stock-mcap")).toHaveText("₹15.2K Cr");
    await expect(page.getByTestId("research-stock-quarters")).toContainText("Q1 FY27");
    // Everything the design shows beyond these figures is declared missing.
    await expect(page.getByTestId("research-stock-nc")).toBeVisible();
  });

  test("Screener ← saved screeners; Open in Copilot asks the compiled rule (in-page runs: copilot-app-screener.spec.ts)", async ({ page }) => {
    const sent = await mockAsk(page);
    // Shape: backend/routes/screeners.py (contract in src/hooks/use-screeners.ts)
    await json(page, "**/api/screeners", [{ screener_id: "scr_fixture01", name: "Fixture quality screen", query: "Screen stocks where ROE over 20, P/E under 15", conditions: [{ key: "roe", op: "over", value: "20" }, { key: "pe", op: "under", value: "15" }], bucket: "", updated_at: "2026-10-11T10:00:00+00:00" }]);
    await page.goto(`${APP}/tool/screener`);
    await expect(page.getByTestId("screener-saved-name")).toHaveText("Fixture quality screen");
    await expect(page.getByTestId("screener-run")).toBeDisabled();
    await page.getByTestId("screener-rule-value").first().fill("20");
    await expect(page.getByTestId("screener-query")).toHaveText("Screen stocks where ROE over 20");
    await page.getByTestId("screener-open-copilot").click();
    await expect.poll(() => sent).toEqual(["Screen stocks where ROE over 20"]);
    await expect(page).toHaveURL(/\/v5\/app\/t\/asked1$/);
  });

  test("Watchlist ← the research watchlist, watchlists from saved screens, and filing alerts", async ({ page }) => {
    const sent = await mockAsk(page);
    // Shape: backend/routes/research_watchlist.py (types in research-watchlist.adapter.ts)
    await json(page, "**/api/public/research-watchlist*", {
      meta: { count: 1, carried_over: 0, list_date: "2026-10-12", available_dates: [{ list_date: "2026-10-12", count: 1 }, { list_date: "2026-10-05", count: 3 }], disclaimer: "Fixture disclaimer text.", live_quotes_source: "yahoo_finance" },
      items: [{ list_date: "2026-10-12", symbol: "FIXTUREUP", company_name: "Fixture Gainer Ltd", tier: "high", rank: 1, thesis: "Fixture thesis line.", published_price: 95, published_date: "2026-10-12", current_price: 101.5, current_price_date: "2026-10-13", change_since_published_pct: 6.84, day_change: 1.5, day_change_pct: 1.5, is_live: true, earlier_list_dates: [] }],
    });
    await json(page, "**/api/screeners", [{ screener_id: "scr_fixture01", name: "Fixture value screen", query: "Screen stocks where P/E under 15", conditions: [{ key: "pe", op: "under", value: "15" }], bucket: "", updated_at: "2026-10-11T10:00:00+00:00" }]);
    const runs: unknown[] = [];
    await page.route("**/api/screeners/run", (route) => {
      runs.push(route.request().postDataJSON());
      return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(load("screener-run-examples.json").matches) });
    });
    // Shape: AlertsC in src/services/adapters/filings.adapter.ts
    await json(page, "**/api/filings/alerts", {
      ok: true,
      types: { concall_transcript: true, annual_report: false, investor_presentation: true, financial_results: true },
      channels: { email: true, whatsapp: false },
      catalog: [{ key: "concall_transcript", label: "Earnings transcripts" }, { key: "annual_report", label: "Annual reports" }, { key: "investor_presentation", label: "Investor presentations" }, { key: "financial_results", label: "Quarterly results" }],
      delivery: { active: false, note: "Fixture delivery note." },
      updatedAt: "2026-10-12T10:00:00+00:00",
    });
    await page.goto(`${APP}/page/watchlist`);

    // The research watchlist the product already publishes, with its live quote and disclaimer.
    await expect(page.getByTestId("watchlist-count")).toHaveText("Research watchlist · 1 stock");
    await expect(page.getByTestId("watchlist-name")).toHaveText("Fixture Gainer Ltd");
    await expect(page.getByTestId("watchlist-price")).toHaveText("₹101.50");
    await expect(page.getByTestId("watchlist-change")).toHaveText("+1.50%");
    await expect(page.getByTestId("watchlist-since")).toContainText("+6.8%");
    await expect(page.getByTestId("watchlist-disclaimer")).toHaveText("Fixture disclaimer text.");
    await expect(page.getByTestId("watchlist-list-picker")).toBeVisible(); // two dated lists

    // A saved screen is a watchlist: its stocks are whatever passes it today.
    await expect(page.getByTestId("watchlist-screen-name")).toHaveText("Fixture value screen");
    expect(runs).toEqual([]); // nothing runs until asked
    await page.getByTestId("watchlist-screen-toggle").click();
    await expect(page.getByTestId("watchlist-screen-stock")).toHaveText(["FIXALPHA", "FIXBRAVO"]);
    await expect(page.getByTestId("watchlist-screen-count")).toContainText("2 stocks today");
    expect(runs).toEqual([{ conditions: [{ key: "pe", op: "under", value: "15" }], bucket: "" }]);

    await expect(page.getByTestId("watchlist-alerts-on")).toHaveText("3"); // three of four types are true
    await expect(page.getByTestId("watchlist-alert")).toHaveCount(4);
    await expect(page.getByTestId("watchlist-alerts-nc")).toBeVisible();

    await page.getByTestId("watchlist-row").click();
    await expect.poll(() => sent).toEqual(["Tell me about Fixture Gainer Ltd"]);
  });

  test("Saved ← screeners + chat sessions; a thread opens", async ({ page }) => {
    await json(page, "**/api/screeners", [{ screener_id: "scr_fixture01", name: "Fixture quality screen", query: "Screen stocks where ROE over 20, P/E under 15", conditions: [{ key: "roe", op: "over", value: "20" }, { key: "pe", op: "under", value: "15" }], bucket: "", updated_at: "2026-10-11T10:00:00+00:00" }]);
    await json(page, "**/api/chat/sessions", [{ session_id: "sess_fixture01", title: "Fixture thread title", updated_at: "2026-10-12T10:00:00+00:00" }]);
    await json(page, "**/api/chat/messages*", []);
    await page.goto(`${APP}/page/saved`);
    await expect(page.getByTestId("saved-screen-title")).toHaveText("Fixture quality screen");
    await expect(page.getByTestId("saved-thread-title")).toHaveText("Fixture thread title");
    await expect(page.getByTestId("saved-reports-nc")).toBeVisible();
    await page.getByTestId("saved-thread-open").click();
    await expect(page).toHaveURL(/\/v5\/app\/t\/sess_fixture01$/);
  });

  test("Trader desk ← journal, scanner, watch levels, broker accounts, markets/home", async ({ page }) => {
    // Shapes: backend/routes/positional_journal.py, positional.py, broker routes (read from the route code)
    await json(page, "**/api/positional/journal/summary/portfolio", { open_count: 1, closed_count: 2, gross_long_rs: 10000, invested_rs: 10000, realized_pnl_rs: 600, win_count: 1, loss_count: 1, win_rate_pct: 50.0, needs_hedge: false, suggested_hedge: null });
    await json(page, /\/api\/positional\/journal(\?.*)?$/, { count: 3, live: true, trades: [
      { nse_symbol: "TESTOPEN", status: "OPEN", plan_source: "MANUAL", stop_loss: 95, target: 120, opened_at: "2026-10-01T04:00:00+00:00", closed_at: null, live_price: 110, pnl: { qty_in: 100, qty_out: 0, held_qty: 100, avg_buy: 100, invested_rs: 10000, realized_pnl_rs: 0, unrealized_pnl_rs: 1000 } },
      { nse_symbol: "TESTWIN", status: "CLOSED", plan_source: "POSITIONAL_PICK", stop_loss: 190, target: 230, opened_at: "2026-09-01T04:00:00+00:00", closed_at: "2026-09-07T04:00:00+00:00", live_price: null, realized_pnl_rs: 1000, realized_pnl_pct: 10, pnl: { qty_in: 50, qty_out: 50, held_qty: 0, avg_buy: 200, invested_rs: 10000, realized_pnl_rs: 1000, unrealized_pnl_rs: 0 } },
      { nse_symbol: "TESTLOSS", status: "STOPPED", plan_source: "MANUAL", stop_loss: 96, target: 0, opened_at: "2026-09-10T04:00:00+00:00", closed_at: "2026-09-12T04:00:00+00:00", live_price: null, realized_pnl_rs: -400, realized_pnl_pct: -4, pnl: { qty_in: 100, qty_out: 100, held_qty: 0, avg_buy: 100, invested_rs: 10000, realized_pnl_rs: -400, unrealized_pnl_rs: 0 } },
    ] });
    await json(page, "**/api/positional/watchlist*", { as_of_date: "2026-10-12", buckets: { breakout_confirmed: [{ nse_symbol: "TESTBRK", sector: "Capital Goods", close_price: 510.0, trigger_price: 500.0, stop_price: 477.5, atr_pct: 2.94, why: "Fixture reason" }], pre_breakout: [], true_accumulation: [], trend_continuation: [] } });
    await json(page, "**/api/positional/picks*", { signal_date: "2026-10-12", count: 1, picks: [{ nse_symbol: "TESTBRK", signal_date: "2026-10-12", final_score: 0.812, confidence: "HIGH", stage: "BREAKOUT", timeframe_days_min: 5, timeframe_days_max: 15, entry_price: 505.0, stoploss: 480.0, target_price: 555.0, risk_reward: 2.0, source_scans: ["btst.breakout_confirmation"], reasons: ["Fixture scanner reason"] }] });
    await json(page, "**/api/broker/accounts", { accounts: [] });
    await page.goto(`${APP}/trader`);
    await expect(page.getByTestId("trader-headline")).toHaveText("1 open trade in your journal.");
    await expect(page.getByTestId("trader-open-count")).toHaveText("1");
    // Open risk = (last 110 − stop 95) × 100 held = ₹1,500
    await expect(page.getByTestId("trader-open-risk")).toHaveText("₹1,500");
    await expect(page.getByTestId("trader-realised")).toHaveText("+₹600");
    await expect(page.getByTestId("trader-win-rate")).toHaveText("50.0%");
    // R per closed trade: +1000 / ((200−190)×50) = +2.0R and −400 / ((100−96)×100) = −1.0R → mean +0.50R
    await expect(page.getByTestId("trader-expectancy")).toHaveText("+0.50R");
    await expect(page.getByTestId("journal-open-row")).toHaveText(["TESTOPEN"]);
    await expect(page.getByTestId("watch-row")).toHaveText(["TESTBRK"]);
    await expect(page.getByTestId("scanner-pick")).toContainText("Fixture scanner reason");
    // markets-home.json: Nifty 50 24568, change −120.5 (−0.49%)
    await expect(page.getByTestId("fno-spot")).toHaveText("24,568.00");
    await expect(page.getByTestId("fno-change")).toHaveText("−120.50 · −0.49%");
    // The broker position book is not exposed by any route.
    await expect(page.getByTestId("trader-positions-not-connected")).toBeVisible();
    await expect(page.getByTestId("trader-risk-rules-not-connected")).toBeVisible();
  });

  test("Options lab: payoff is computed from typed legs; with no F&O answer the chain and open interest show an error, not numbers", async ({ page }) => {
    await page.goto(`${APP}/tool/optlab`);
    // No chain (the mock answers /api/fno/* with {}), so the spot falls back to the markets feed.
    await expect(page.getByTestId("optlab-spot")).toContainText("24,568.00");
    await expect(page.getByTestId("optlab-asof")).toHaveCount(0);
    await page.getByTestId("optlab-tab-builder").click();
    await page.getByTestId("optlab-structure").filter({ hasText: "Bull call spread" }).click();
    await expect(page.getByTestId("optlab-payoff-empty")).toBeVisible(); // nothing computed until prices are typed
    await page.getByTestId("optlab-lot-size").fill("75");
    await page.getByTestId("optlab-leg-0-strike").fill("22000");
    await page.getByTestId("optlab-leg-0-premium").fill("200");
    await page.getByTestId("optlab-leg-1-strike").fill("22500");
    await page.getByTestId("optlab-leg-1-premium").fill("50");
    // Buy 22000 CE @200, sell 22500 CE @50, lot 75:
    //   net debit (200−50)×75 = 11,250 = max loss · max profit (500−150)×75 = 26,250 · breakeven 22000+150
    await expect(page.getByTestId("optlab-max-profit")).toHaveText("₹26,250");
    await expect(page.getByTestId("optlab-max-loss")).toHaveText("₹11,250");
    await expect(page.getByTestId("optlab-breakevens")).toHaveText("22,150");
    await expect(page.getByTestId("optlab-net-premium")).toHaveText("₹11,250");
    await expect(page.getByTestId("optlab-payoff-chart")).toBeVisible();
    await expect(page.getByTestId("optlab-analytics-not-connected")).toBeVisible();
    await page.getByTestId("optlab-tab-chain").click();
    await expect(page.getByTestId("optlab-chain-error")).toBeVisible();
    await expect(page.getByTestId("optlab-chain-row")).toHaveCount(0);
    await page.getByTestId("optlab-tab-oi").click();
    await expect(page.getByTestId("optlab-oi-error")).toBeVisible();
    await expect(page.getByTestId("optlab-oi-bar")).toHaveCount(0);
  });

  test("Options lab ← /api/fno: end-of-day chain, open interest, lot size and prefilled legs", async ({ page }) => {
    const fno = load("fno-nifty.json");
    await json(page, "**/api/fno/NIFTY/expiries", fno.expiries);
    await json(page, "**/api/fno/NIFTY/chain*", fno.chain);
    await page.goto(`${APP}/tool/optlab`);
    // Spot and date come from the chain, and are labelled end of day.
    await expect(page.getByTestId("optlab-spot")).toHaveText("25,040.50");
    await expect(page.getByTestId("optlab-asof")).toHaveText("End-of-day data · as of 12 Oct 2026");
    await expect(page.getByTestId("optlab-expiry")).toHaveValue("2026-10-13");

    await page.getByTestId("optlab-tab-chain").click();
    const rows = page.getByTestId("optlab-chain-row");
    await expect(rows).toHaveCount(3);
    const atm = page.locator('[data-testid="optlab-chain-row"][data-atm="true"]');
    await expect(atm).toHaveAttribute("data-strike", "25000");
    await expect(atm.locator('[data-col="call-oi"]')).toHaveText("31.00 L");
    await expect(atm.locator('[data-col="call-price"]')).toHaveText("240.25");
    await expect(atm.locator('[data-col="put-price"]')).toHaveText("128.60");
    await expect(atm.locator('[data-col="put-oi"]')).toHaveText("36.00 L");
    await expect(page.getByTestId("optlab-chain-note")).toContainText("3 of this expiry’s 3 strikes");

    await page.getByTestId("optlab-tab-oi").click();
    // Totals 1,68,00,000 calls and 87,00,000 puts → PCR 0.5179
    await expect(page.getByTestId("optlab-oi-total-call")).toHaveText("1.68 Cr");
    await expect(page.getByTestId("optlab-oi-total-put")).toHaveText("87.00 L");
    await expect(page.getByTestId("optlab-oi-pcr")).toHaveText("0.52");
    await expect(page.getByTestId("optlab-oi-max-pain")).toHaveText("25,000");
    await expect(page.getByTestId("optlab-oi-top-call")).toHaveText("25,100 · 1.24 Cr");
    await expect(page.getByTestId("optlab-oi-top-put")).toHaveText("24,900 · 42.00 L");
    await expect(page.getByTestId("optlab-oi-bar")).toHaveCount(6);

    await page.getByTestId("optlab-tab-builder").click();
    // "Buy call" is filled from the ATM strike's close, and the lot from the contract file.
    await expect(page.getByTestId("optlab-leg-0-strike")).toHaveValue("25000");
    await expect(page.getByTestId("optlab-leg-0-premium")).toHaveValue("240.25");
    await expect(page.getByTestId("optlab-lot-size")).toHaveValue("65");
    await expect(page.getByTestId("optlab-lot-source")).toBeVisible();
    await expect(page.getByTestId("optlab-prefill-note")).toContainText("end-of-day closing prices as of 12 Oct 2026");
    // Buy 1 lot of 65 at 240.25: the most that can be lost is the premium, 240.25 × 65 = 15,616.25
    await expect(page.getByTestId("optlab-max-profit")).toHaveText("Unlimited");
    await expect(page.getByTestId("optlab-max-loss")).toHaveText("₹15,616");
    // A typed lot size is kept when another expiry's chain arrives.
    await page.getByTestId("optlab-lot-size").fill("130");
    await page.getByTestId("optlab-expiry").selectOption("2026-10-27");
    await expect(page.getByTestId("optlab-lot-size")).toHaveValue("130");
    await expect(page.getByTestId("optlab-lot-source")).toHaveCount(0);
    // Nothing here offers an order.
    await expect(page.getByTestId("screen-tool-optlab").getByRole("button", { name: /place|send order|buy now|sell now/i })).toHaveCount(0);
  });

  test("Trader desk F&O card ← /api/fno: futures basis, put-call ratio, max pain and open-interest levels", async ({ page }) => {
    const fno = load("fno-nifty.json");
    await json(page, "**/api/fno/NIFTY/expiries", fno.expiries);
    await json(page, "**/api/fno/NIFTY/chain*", fno.chain);
    await json(page, "**/api/fno/NIFTY/futures", fno.futures);
    await page.goto(`${APP}/trader`);
    await expect(page.getByTestId("fno-futures-price")).toHaveText("25,079.00");
    // 25,079.00 settle − 25,040.50 spot
    await expect(page.getByTestId("fno-basis")).toHaveText("+38.50");
    await expect(page.getByTestId("fno-futures-asof")).toHaveText("End-of-day data · as of 12 Oct 2026");
    await expect(page.getByTestId("fno-pcr")).toHaveText("0.52");
    await expect(page.getByTestId("fno-max-pain")).toHaveText("25,000");
    await expect(page.getByTestId("fno-top-put-oi")).toHaveText("24,900");
    await expect(page.getByTestId("fno-top-call-oi")).toHaveText("25,100");
    await expect(page.getByTestId("fno-oi-by-strike-row")).toHaveCount(3);
  });

  test("Paper trades ← paper-trades portfolio, evaluation, live", async ({ page }) => {
    // Same fixtures and routing as research-paper-trades.spec.ts
    await page.route("**/api/paper-trades/**", (route) => {
      const u = new URL(route.request().url());
      const q = (k: string) => u.searchParams.get(k);
      const reply = (body: unknown, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
      const pick = (name: string, fallback: unknown) => (fs.existsSync(path.join(FX, name)) ? load(name) : fallback);
      if (u.pathname.endsWith("/portfolio")) {
        const base = `paper-portfolio-${q("sample") ?? "forward"}-${q("portfolio") ?? "P5-NEXT"}`;
        const d = q("prediction_date");
        return reply(pick(d ? `${base}-${d}.json` : `${base}.json`, load(`${base}.json`)));
      }
      if (u.pathname.endsWith("/evaluation")) return reply(pick(`paper-evaluation-${q("sample")}-${q("portfolio")}.json`, { data: { status: "none", sample: q("sample"), portfolio: q("portfolio") } }));
      if (u.pathname.endsWith("/live")) return reply(pick(`paper-live-${q("portfolio")}.json`, { data: { status: "empty", portfolio: q("portfolio"), positions: [] } }));
      return reply({ detail: "not_found" }, 404);
    });
    await page.goto(`${APP}/page/paper`);
    // paper-portfolio-forward-P5-NEXT.json: five positions, none closed
    await expect(page.getByTestId("paper-open-count")).toHaveText("5");
    await expect(page.getByTestId("paper-closed-count")).toHaveText("0");
    const rows = page.getByTestId("paper-open-row");
    await expect(rows).toHaveCount(5);
    for (const sym of ["SHAREINDIA", "RATNAVEER", "PNCINFRA", "TRIVENI", "TEGA"]) {
      await expect(rows.filter({ hasText: sym })).toHaveCount(1);
    }
    await expect(page.getByTestId("paper-disclaimer")).toBeVisible();
  });

  test("Advisor ← client book + SIP board; opening a client lands in the Copilot", async ({ page }) => {
    await json(page, "**/api/auth/me", ADVISOR_ME);
    // Shapes: backend/routes/mfd.py list_profiles; backend/routes/advisor_v4.py sip_board_summary
    await json(page, "**/api/mfd/profiles*", {
      workspace: { workspace_id: "ws-test-1", type: "ADVISORY", firm_name: "Test Advisory LLP", arn_or_ria: "ARN-TEST-0001" },
      profiles: [
        { profile_id: "p-1", name: "Test Client One", type: "CLIENT", aum_rs: null, portfolio_value_rs: 6200000, portfolio_score: 41, risk_score: 72, recommendation_count: 2, last_reviewed_at: null,
          priority: { score: 0.82, bucket: "high", factors: { portfolio_weakness: 0.59, risk: 0.72, aum: 0.4, recency: 1.0, recommendation_severity: 0.4 }, reasons: ["High exposure risk (72/100)"], dominant_action: "rebalance" } },
        { profile_id: "p-2", name: "Test Client Two", type: "CLIENT", aum_rs: 2500000, portfolio_value_rs: null, portfolio_score: 78, risk_score: 30, recommendation_count: 0, last_reviewed_at: new Date(Date.now() - 3 * 86_400_000).toISOString(),
          priority: { score: 0.2, bucket: "low", factors: { portfolio_weakness: 0.22, risk: 0.3, aum: 0.3, recency: 0.1, recommendation_severity: 0 }, reasons: ["Stable portfolio, no urgent action"], dominant_action: null } },
        { profile_id: "p-self", name: "Fixture Advisor", type: "SELF", portfolio_value_rs: 900000, priority: { score: 0.3, bucket: "low", factors: {}, reasons: [] } },
      ],
      count: 3,
    });
    await json(page, "**/api/advisor/sip-board/summary*", { cycle: "2026-10", monthly_inflow_rs: 45000, active_sips_count: 7, failed_count: 1, mandate_at_risk_count: 2 });
    await page.goto(`${APP}/advisor`);
    await expect(page.getByTestId("advisor-firm")).toHaveText("Advisor · Test Advisory LLP · ARN-TEST-0001");
    await expect(page.getByTestId("advisor-tile-clients")).toHaveText("2"); // the SELF profile is not a client
    await expect(page.getByTestId("advisor-tile-aum")).toHaveText("₹87.00 L"); // 62,00,000 + 25,00,000
    await expect(page.getByTestId("advisor-tile-at-risk")).toHaveText("1");
    await expect(page.getByTestId("advisor-tile-sips")).toHaveText("7");
    await expect(page.getByTestId("advisor-queue-name")).toHaveText(["Test Client One"]);
    // Health = round(0.6 × score + 0.4 × (100 − risk)): 0.6×41+0.4×28 = 35.8 → 36 ; 0.6×78+0.4×70 = 74.8 → 75
    await expect(page.getByTestId("advisor-client-health")).toHaveText(["36", "75"]);
    await expect(page.getByTestId("advisor-models-not-connected")).toBeVisible();
    await expect(page.getByTestId("advisor-reports-not-connected")).toBeVisible();
    await page.getByTestId("advisor-open-client").first().click();
    await expect(page).toHaveURL(/\/v5\/app$/);
    await expect(page.getByTestId("home-headline")).toBeVisible();
  });

  test("Advisor screen explains itself to a non-advisor account", async ({ page }) => {
    await page.goto(`${APP}/advisor`);
    await expect(page.getByTestId("advisor-not-advisor")).toBeVisible();
  });

  test("Internal pages ← feeds, audit trail, admin stats, routing agents", async ({ page }) => {
    await mockSingleRoute(page, "**/api/admin/nidp/feeds/live", "nidp-feeds-live.json");
    // nidp-feeds-live.json summary: total 4 · healthy 1 · failing 1 · stale 1 · never_run 1
    await page.goto(`${APP}/ops/feeds`);
    await expect(page.getByTestId("feeds-total")).toHaveText("4");
    await expect(page.getByTestId("feeds-healthy")).toHaveText("1");
    await expect(page.getByTestId("feeds-failing")).toHaveText("1");
    await expect(page.getByTestId("feeds-stale")).toHaveText("1");
    await expect(page.getByTestId("feeds-row")).toHaveText(["bhavcopy", "amfi_nav", "yfinance_backfill", "fii_dii"]);

    // Shape: backend/services/audit.py record
    await json(page, "**/api/compliance/audit*", { rows: [
      { audit_id: "aud_0123456789ab", user_id: "u-adm", action: "cas_upload", resource: "cas_2026_10.pdf", outcome: "success", details: null, ts: "2026-10-13T08:15:30+00:00" },
      { audit_id: "aud_ba9876543210", user_id: "u-adm", action: "login_failed", resource: null, outcome: "denied", details: null, ts: "2026-10-12T19:02:11+00:00" },
    ], count: 2 });
    await page.goto(`${APP}/ops/audit`);
    await expect(page.getByTestId("audit-count")).toHaveText("2");
    await expect(page.getByTestId("audit-row")).toHaveCount(2);
    await expect(page.getByTestId("audit-outcome")).toHaveText(["success", "denied"]);
    await expect(page.getByTestId("audit-platform-not-connected")).toBeVisible();

    // Shape: backend/routes/admin.py get_admin_stats
    await json(page, "**/api/admin/stats", { whitelist: { total: 40, active: 25, pending: 12, blocked: 3, conversion_rate: 62.5 }, usage: { total_users: 31, total_portfolios: 22, total_holdings: 418 } });
    await page.goto(`${APP}/ops/kpis`);
    await expect(page.getByTestId("kpi-users")).toHaveText("31");
    await expect(page.getByTestId("kpi-portfolios")).toHaveText("22");
    await expect(page.getByTestId("kpi-holdings")).toHaveText("418");
    await expect(page.getByTestId("kpi-conversion")).toHaveText("62.5%");
    await expect(page.getByTestId("kpi-feeds-healthy")).toHaveText("1 of 4");
    await expect(page.getByTestId("kpi-ux-not-connected")).toBeVisible();

    // Shape: backend/services/copilot_agents.py
    await json(page, "**/api/copilot/agents", { agents: [
      { id: "auto", label: "Auto-route", icon: "compass", one_liner: "Picks the right specialist automatically.", triggers: [], default_suggestions: ["How is my portfolio doing?"] },
      { id: "tax_agent", label: "Tax Agent", icon: "receipt", one_liner: "Capital gains, harvesting, FY planning.", triggers: ["\\btax\\b", "\\bcapital gains?\\b"], default_suggestions: ["How much LTCG do I have this FY?"] },
    ] });
    await page.goto(`${APP}/ops/tools`);
    await expect(page.getByTestId("tools-agent-count")).toHaveText("2");
    await expect(page.getByTestId("tools-agent-label")).toHaveText(["Auto-route", "Tax Agent"]);
    await expect(page.getByTestId("tools-registry-not-connected")).toBeVisible();
  });

  test("Tool builder: the contract is derived from what is typed; saving is declared missing", async ({ page }) => {
    await page.goto(`${APP}/builder`);
    await expect(page.getByTestId("builder-contract-empty")).toBeVisible();
    await expect(page.getByTestId("builder-checklist-done")).toHaveText("0");
    await page.getByTestId("builder-name").fill("Harness check tool");
    await page.getByTestId("builder-persona-trader").click();
    await page.getByTestId("builder-objective").fill("Typed by the test to check the contract.");
    const contract = page.getByTestId("builder-contract");
    await expect(contract).toContainText("tool: harness_check_tool");
    await expect(contract).toContainText("personas: [trader]");
    await expect(contract).toContainText("objective: Typed by the test to check the contract.");
    await expect(page.getByTestId("builder-save")).toBeDisabled();
    await expect(page.getByTestId("builder-send-review")).toBeDisabled();
    await expect(page.getByTestId("builder-not-connected")).toBeVisible();
  });

  test("the engineering 'needs' list on a not-connected block is shown to admins only", async ({ page }) => {
    await page.goto(`${APP}/page/watchlist`); // fixture user is an admin
    await expect(page.getByTestId("watchlist-alerts-nc").getByTestId("not-connected-needs")).toBeVisible();
    await json(page, "**/api/auth/me", { user_id: "u_plain", email: "user@example.test", name: "Fixture User", is_admin: false, onboarding_completed: true });
    await page.reload();
    await expect(page.getByTestId("watchlist-alerts-nc")).toBeVisible();
    await expect(page.getByTestId("not-connected-needs")).toHaveCount(0);
  });
});

// Real shape of GET /api/onboarding/state (backend/routes/onboarding_gmail.py).
// e2e/fixtures/onboarding-state.json predates it and lacks these fields.
const ONBOARDING_STATE = { onboarding_completed: true, pan_on_file: true, gmail_connected: true, cas_statement_period: "Mar/2025", cas_portfolio_value_rs: 1234567.5, cas_statement_date: "31-Mar-2025" };

test.describe("TC-19 account screens — desktop", () => {
  test.beforeEach(async ({ page }) => {
    await populated(page);
    await json(page, "**/api/onboarding/state", ONBOARDING_STATE);
  });

  /** auth/me that reports onboarding as unfinished until the completion call succeeds. */
  async function onboardingUser(page: Page, completeStatus: number) {
    const state = { completed: false, posts: 0 };
    const user = load("user-profile.json"); // onboarding_completed: false
    await page.route("**/api/auth/me", (route) =>
      route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ ...user, onboarding_completed: state.completed }) }));
    await page.route("**/api/user/complete-onboarding", (route) => {
      state.posts += 1;
      if (completeStatus < 400) state.completed = true;
      return route.fulfill({ status: completeStatus, contentType: "application/json", body: JSON.stringify(completeStatus < 400 ? { ok: true } : { detail: "boom" }) });
    });
    return state;
  }

  test("Onboarding: skipping records completion and lands on home for good", async ({ page }) => {
    const state = await onboardingUser(page, 200);
    await page.goto(APP);
    await expect(page).toHaveURL(/\/v5\/app\/onboarding$/);
    await expect(page.getByTestId("onboarding-step-you")).toBeVisible();
    await page.getByTestId("onboarding-skip").click();
    await expect(page).toHaveURL(/\/v5\/app$/);
    await expect(page.getByTestId("home-headline")).toBeVisible();
    expect(state.posts).toBe(1);
    // The profile is re-read after the write; the user must not be sent back.
    await page.waitForLoadState("networkidle");
    await expect(page).toHaveURL(/\/v5\/app$/);
    await expect(page.getByTestId("screen-onboarding")).toHaveCount(0);
  });

  test("Onboarding: if recording completion fails the user still gets out, and is told", async ({ page }) => {
    const state = await onboardingUser(page, 500);
    await page.goto(`${APP}/onboarding`);
    await page.getByTestId("onboarding-skip").click();
    await expect(page).toHaveURL(/\/v5\/app$/);
    await expect(page.getByTestId("home-headline")).toBeVisible();
    await expect(page.getByText("Setup wasn’t saved")).toBeVisible();
    expect(state.posts).toBe(1);
  });

  test("Onboarding: the four steps in order, showing what is on file, then finish", async ({ page }) => {
    const state = await onboardingUser(page, 200);
    await page.goto(`${APP}/onboarding`);
    await page.getByTestId("onboarding-mode-investor").click();
    await page.getByTestId("onboarding-next").click();
    await expect(page.getByTestId("onboarding-step-goals")).toBeVisible();
    await expect(page.getByTestId("onboarding-risk-category")).toHaveText("Moderately Aggressive"); // risk-profile.json
    await expect(page.getByTestId("onboarding-rules-missing")).toBeVisible();
    await page.getByTestId("onboarding-next").click();
    await expect(page.getByTestId("onboarding-step-portfolio")).toBeVisible();
    await expect(page.getByTestId("cas-choose")).toBeVisible();
    await page.getByTestId("onboarding-back").click();
    await expect(page.getByTestId("onboarding-step-goals")).toBeVisible();
    await page.getByTestId("onboarding-next").click();
    await page.getByTestId("onboarding-next").click();
    await expect(page.getByTestId("onboarding-step-done")).toBeVisible();
    await expect(page.getByTestId("onboarding-statement-period")).toHaveText("Mar/2025");
    await expect(page.getByTestId("onboarding-statement-value")).toHaveText("₹12,34,568"); // 12,34,567.5 rounded
    await page.getByTestId("onboarding-finish").click();
    await expect(page).toHaveURL(/\/v5\/app$/);
    expect(state.posts).toBe(1);
  });

  test("Broker connections ← broker accounts, statement on file, Gmail, import log", async ({ page }) => {
    // Shapes: routes/broker_connect.py, routes/broker_native.py, routes/gmail.py, services/audit.py
    await json(page, "**/api/broker/accounts", { accounts: [{ account_id: "ba_0123456789ab", broker: "zerodha", broker_display: "Zerodha", label: "Zerodha", status: "active", last_sync_at: "2026-10-13T08:30:00+00:00", last_sync_count: 12, last_error: null, created_at: "2026-10-01T10:00:00+00:00" }] });
    await json(page, "**/api/broker/native/supported", { brokers: [{ slug: "zerodha", name: "Zerodha", auth_style: "oauth", implemented: true }, { slug: "groww", name: "Groww", auth_style: "form", implemented: false }] });
    await json(page, "**/api/gmail/status", { connected: true, connected_at: "2026-10-01T10:00:00+00:00", last_import: { filename: "NSDL_CAS.pdf", imported_at: "2026-10-12T06:30:00+00:00", count: 12 }, auto_import_enabled: true, auto_import_ready: true });
    await json(page, "**/api/gmail/history", { imports: [{ message_id: "m1", filename: "NSDL_CAS.pdf", count: 12, status: "completed", source: "onboarding_gmail", imported_at: "2026-10-12T06:30:00+00:00" }] });
    await json(page, "**/api/compliance/audit*", { rows: [{ audit_id: "aud_1", action: "broker_sync", outcome: "success", details: { broker: "zerodha", count: 12 }, ts: "2026-10-13T08:30:00+00:00" }] });
    await page.goto(`${APP}/page/brokers`);
    await expect(page.getByTestId("brokers-connected-count")).toHaveText("3"); // broker account + statement + Gmail
    await expect(page.getByTestId("broker-account-name")).toHaveText("Zerodha");
    await expect(page.getByTestId("broker-account-status")).toHaveText("Connected");
    await expect(page.getByTestId("broker-account-meta")).toContainText("12 holdings");
    await expect(page.getByTestId("statement-period")).toHaveText("Mar/2025");
    await expect(page.getByTestId("statement-date")).toHaveText("31-Mar-2025");
    await expect(page.getByTestId("statement-value")).toHaveText("₹12,34,568");
    await expect(page.getByTestId("gmail-status")).toHaveText("Connected");
    await expect(page.getByTestId("gmail-last-file")).toContainText("NSDL_CAS.pdf");
    await expect(page.getByTestId("broker-adapters-built")).toHaveText("1");
    await expect(page.getByTestId("broker-adapters-pending")).toHaveText("1");
    await expect(page.getByTestId("import-log-event")).toHaveText(["Broker sync", "Gmail import"]); // newest first
    // Signing in to a broker from this app is not possible yet, and the screen says so.
    await expect(page.getByTestId("broker-signin-missing")).toBeVisible();
  });

  test("Settings ← profile, risk, goals; mode and theme take effect", async ({ page }) => {
    await json(page, "**/api/goals", { goals: [{ goal_id: "g1", goal_type: "retirement", goal_name: "Retirement", target_amount_rs: 10000000, horizon_years: 20, monthly_sip_rs: 25000, on_track_pct: 72, status: "active" }], total: 1, on_track: 1, at_risk: 0 });
    await json(page, "**/api/broker/accounts", { accounts: [] });
    await json(page, "**/api/gmail/status", { connected: false });
    await page.goto(`${APP}/page/settings`);
    // user-profile-onboarded.json
    await expect(page.getByTestId("settings-name")).toHaveText("Test Onboarded User");
    await expect(page.getByTestId("settings-email")).toHaveText("aporwal107@gmail.com");
    await expect(page.getByTestId("settings-risk-category")).toHaveText("Moderately Aggressive");
    await expect(page.getByTestId("settings-goal-name")).toHaveText("Retirement");
    await expect(page.getByTestId("settings-statement-status")).toHaveText("On file");
    await expect(page.getByTestId("settings-gmail-status")).toHaveText("Not connected");
    for (const id of ["settings-answer-depth-missing", "settings-constraints-missing", "settings-memory-missing", "settings-privacy-missing"]) {
      await expect(page.getByTestId(id)).toBeVisible();
    }
    await page.getByTestId("settings-theme-light").click();
    await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
    await page.getByTestId("settings-theme-dark").click();
    await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
    await expect(page.getByTestId("settings-mode-advisor")).toBeDisabled(); // not an advisor workspace
    await page.getByTestId("settings-mode-trader").click();
    await expect(page.getByTestId("mode-pill")).toContainText("Trader");
    await expect(page.getByTestId("copilot-rail").getByRole("button", { name: /Options lab/ })).toBeVisible();
  });
});
