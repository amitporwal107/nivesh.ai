/**
 * One-screen Copilot app (/v5/app) — Stock & fund research (tool/research).
 *
 * The stock and fund pages read existing backend routes. Every /api call is
 * answered here; fixtures have the real response shapes with synthetic values
 * (e2e/fixtures/copilot-research-*.json). Mocked APIs, production build — see
 * pw.copilot-app.config.ts.
 *
 *   Stock  price            GET  /api/research/chart-live/{symbol}/ohlcv
 *          key figures      POST /api/copilot/widgets/company_financials
 *          research card    GET  /api/move-odds/stocks/{symbol}/card
 *          market backdrop  GET  /api/stock/{symbol}/why
 *   Fund   NAV              GET  /api/mf/lookup
 *          returns, risk    GET  /api/portfolio/holding-detail/{isin}
 *          factsheet        GET  /api/mf/holdings
 */
import { test, expect, type Page } from "@playwright/test";
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";
import { mockApi } from "../helpers/api-mock";

const APP = "/v5/app";
const FX = path.join(path.dirname(fileURLToPath(import.meta.url)), "..", "fixtures");
const load = (name: string) => JSON.parse(fs.readFileSync(path.join(FX, name), "utf-8"));

const json = (page: Page, pattern: string | RegExp, body: unknown, status = 200) =>
  page.route(pattern, (route) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) }));

const PRICE = "**/api/research/chart-live/FIXTUREUP/ohlcv*";
const CARD = "**/api/move-odds/stocks/FIXTUREUP/card";
const BACKDROP = "**/api/stock/FIXTUREUP/why";
const LOOKUP = "**/api/mf/lookup*";
const NUMBERS = "**/api/portfolio/holding-detail/INF000FIX002";
const FACTSHEET = "**/api/mf/holdings*";

type Bar = [string, number, number, number, number, number];

/**
 * `count` weekday sessions ending Fri 9 Oct 2026, in the shape of
 * backend/routes/research_chart_live.py: [date, open, high, low, close, volume].
 * Session i closes at 100 + 0.1·i, with the high 1 above and the low 1 below.
 */
function bars(count: number): Bar[] {
  const out: Bar[] = [];
  const d = new Date(Date.UTC(2026, 9, 9));
  while (out.length < count) {
    const dow = d.getUTCDay();
    if (dow !== 0 && dow !== 6) out.unshift([d.toISOString().slice(0, 10), 0, 0, 0, 0, 0]);
    d.setUTCDate(d.getUTCDate() - 1);
  }
  return out.map(([day], i) => {
    const close = Math.round((100 + i * 0.1) * 100) / 100;
    return [day, close, close + 1, close - 1, close, 100000 + i * 1000];
  });
}

const history = (count: number) => ({
  symbol: "FIXTUREUP", timeframe: "1D", bars: bars(count), data_quality_status: "VALID", pit_status: "PIT_UNVERIFIED", findings: [],
  provenance: { provider: "nidp.prices_eod_adjusted", series: "EQ", adjustment_status: "SPLIT_BONUS_ADJUSTED", last_bar_date: "2026-10-09", source_mode: "live", last_event_type: null },
});

/** As on staging: P/E is filled; market cap, P/B, ROE and debt to equity are empty. */
const FINANCIALS = {
  kind: "company_financials", title: "FIXTUREUP — Financials & Prospects",
  data: {
    symbol: "FIXTUREUP",
    v3_score: { pe_ttm: 24.6, pb: null, roe_pct: null, debt_to_equity: null, market_cap_cr: null, market_cap_bucket: null },
    rows: [{ quarter: "Q1 FY27", period_end: "2026-06-30", revenue_cr: 1200, ebitda_cr: 180, pat_cr: 96, eps_basic: 4.8, ebitda_margin_pct: null, revenue_yoy_pct: 12.0, pat_yoy_pct: null }],
  },
};

async function base(page: Page) {
  await mockApi(page, "populated");
  await page.route("**/api/chat/sessions", (route) => route.fulfill({ status: 200, contentType: "application/json", body: "[]" }));
  // Shape: backend/routes/chat.py chat_instrument_search
  await json(page, "**/api/chat/instrument-search*", {
    stocks: [{ symbol: "FIXTUREUP", name: "Fixture Gainer Ltd", sector: "Fixture Sector A" }],
    funds: [{ name: "Fixture Flexi Cap Fund", scheme_code: "900002", amc: "Fixture Mutual Fund", category: "Equity Scheme - Flexi Cap Fund" }],
  });
}

async function stockRoutes(page: Page) {
  await json(page, PRICE, history(460));
  await json(page, "**/api/copilot/widgets/company_financials", FINANCIALS);
  await json(page, CARD, load("copilot-research-stock-card.json"));
  await json(page, BACKDROP, load("copilot-research-stock-backdrop.json"));
}

async function fundRoutes(page: Page) {
  await json(page, LOOKUP, load("copilot-research-fund-lookup.json"));
  await json(page, NUMBERS, load("copilot-research-fund-numbers.json"));
  await json(page, FACTSHEET, load("copilot-research-fund-factsheet.json"));
}

async function openStock(page: Page) {
  await page.goto(`${APP}/tool/research`);
  await page.getByTestId("research-kind-stock").click();
  await page.getByTestId("research-search").fill("fixture");
  await page.getByTestId("research-search-result").first().click();
  await expect(page.getByTestId("research-entity-name")).toHaveText("Fixture Gainer Ltd");
}

async function openFund(page: Page) {
  await page.goto(`${APP}/tool/research`);
  await page.getByTestId("research-kind-fund").click();
  await page.getByTestId("research-search").fill("fixture");
  await page.getByTestId("research-search-result").first().click();
  await expect(page.getByTestId("research-entity-name")).toHaveText("Fixture Flexi Cap Fund");
}

/** An error surfaces after the app's one automatic retry. */
const SLOW = { timeout: 15_000 };

test.describe("Research — stock", () => {
  test.beforeEach(async ({ page }) => { await base(page); });

  test("header: the company icon sits beside the name; search rows carry icons too", async ({ page }) => {
    await stockRoutes(page);
    await page.goto(`${APP}/tool/research`);
    await page.getByTestId("research-search").fill("fixture");
    const rows = page.getByTestId("research-search-result");
    await expect(rows).toHaveCount(2);
    await expect(rows.nth(0).locator('[data-testid="entity-icon"][data-kind="stock"][data-key="FIXTUREUP"]')).toBeVisible();
    await expect(rows.nth(1).locator('[data-testid="entity-icon"][data-kind="fund-house"]')).toBeVisible();
    await rows.nth(0).click();
    await expect(page.getByTestId("research-entity-name")).toHaveText("Fixture Gainer Ltd");
    await expect(page.getByTestId("research-entity-icon").locator('[data-testid="entity-icon"][data-kind="stock"][data-key="FIXTUREUP"]')).toBeVisible();
    await expect(page.getByTestId("research-entity-meta")).toHaveText("FIXTUREUP");
  });

  test("price block ← daily bars: last close, day change, 52-week range, 200-day average and the chart", async ({ page }) => {
    await stockRoutes(page);
    await openStock(page);
    // 460 sessions; the last closes at 100 + 0.1·459 = 145.90, the one before at 145.80.
    await expect(page.getByTestId("research-stock-close")).toHaveText("₹145.90");
    await expect(page.getByTestId("research-stock-day-change")).toHaveText("+0.07% on the day");
    // The 12 months to 9 Oct 2026 hold 262 weekday sessions, so the window starts at session 198 (close 119.80).
    await expect(page.getByTestId("research-stock-year-change")).toHaveText("+21.8%");
    await expect(page.getByTestId("research-stock-high")).toHaveText("₹146.90");
    await expect(page.getByTestId("research-stock-low")).toHaveText("₹118.80");
    // Mean of the last 200 closes: 145.90 − 0.1·99.5 = 135.95.
    await expect(page.getByTestId("research-stock-avg200")).toHaveText("₹135.95");
    const block = page.getByTestId("research-stock-price");
    await expect(block).toContainText("52-week high");
    await expect(block).toContainText("Last close is above it");
    // Session 198 opens the window; the first with 200 sessions behind it is session 199, Fri 10 Oct 2025.
    await expect(page.getByTestId("research-stock-avg200-note")).toContainText("The 200-day average line starts on 10 Oct 2025");
    const chart = page.getByTestId("research-price-chart");
    await expect(chart.locator("svg[role='img']")).toBeVisible();
    await expect(chart).toContainText("200-day average");
    await expect(page.getByTestId("research-price-readout")).toContainText("9 Oct 2026 · Close ₹145.90 · 200-day average ₹135.95");
    // The keyboard reads the previous session.
    await chart.locator("svg[role='img']").focus();
    await page.keyboard.press("ArrowLeft");
    await expect(page.getByTestId("research-price-readout")).toContainText("8 Oct 2026 · Close ₹145.80");
  });

  test("price block: under a year of sessions is not called a 52-week range, and the 200-day average is not available", async ({ page }) => {
    await stockRoutes(page);
    await json(page, PRICE, history(30));
    await openStock(page);
    const block = page.getByTestId("research-stock-price");
    // 30 weekday sessions ending 9 Oct 2026 start on 31 Aug 2026.
    await expect(block).toContainText("High since 31 Aug 2026");
    await expect(block).not.toContainText("52-week");
    await expect(page.getByTestId("research-stock-avg200")).toHaveText("Not available");
    await expect(block).toContainText("Needs 200 trading sessions");
    await expect(page.getByTestId("research-price-chart")).not.toContainText("200-day average");
    await expect(page.getByTestId("research-stock-avg200-note")).toHaveCount(0);
  });

  test("price block: empty, switched-off and error states", async ({ page }) => {
    await stockRoutes(page);
    await json(page, PRICE, { detail: "no_bars_for_symbol" }, 404);
    await openStock(page);
    await expect(page.getByTestId("research-stock-price-empty")).toContainText("No daily prices for FIXTUREUP yet");
    await expect(page.getByTestId("research-stock-price")).toHaveCount(0);

    await json(page, PRICE, { detail: "feature_not_enabled" }, 403);
    await openStock(page);
    await expect(page.getByTestId("research-stock-price-locked")).toContainText("Price history is not switched on for this account");

    await json(page, PRICE, {});
    await openStock(page);
    await expect(page.getByTestId("research-stock-price-error")).toContainText("The price history didn’t load", SLOW);
    // The rest of the overview still renders beside a failed block.
    await expect(page.getByTestId("research-stock-pe")).toHaveText("24.6×");
  });

  test("key figures: a figure the data does not carry reads “Not available”, never a dash or 0", async ({ page }) => {
    await stockRoutes(page);
    await openStock(page);
    await expect(page.getByTestId("research-stock-pe")).toHaveText("24.6×");
    for (const id of ["research-stock-mcap", "research-stock-pb", "research-stock-roe", "research-stock-de"]) {
      await expect(page.getByTestId(id)).toHaveText("Not available");
    }
    await expect(page.getByTestId("research-stock-metrics-missing")).toHaveText("Not in the latest data for FIXTUREUP: market cap, P/B, ROE and debt to equity.");
    const quarters = page.getByTestId("research-stock-quarters");
    await expect(quarters).toContainText("Q1 FY27");
    // EBITDA margin and profit YoY are null in the row.
    await expect(quarters.locator('[data-na="true"]')).toHaveCount(2);
    // What is still missing is declared.
    await expect(page.getByTestId("research-stock-nc")).toContainText("Some parts of the stock page are not connected yet");
  });

  test("scores and technicals ← the Copilot's research card, and the market backdrop", async ({ page }) => {
    await stockRoutes(page);
    await openStock(page);
    await page.getByTestId("research-stock-tab-scores").click();
    const card = page.getByTestId("research-stock-card");
    await expect(card).toContainText("Synthetic summary: a fixture business at a fixture valuation.");
    await expect(card).toContainText("₹145.90");
    await expect(card).toContainText("Fundamentals");
    await card.getByRole("tab", { name: /How's it performed\?/ }).click();
    await expect(card).toContainText("RSI (14)");
    await expect(card).toContainText("Sideways trend");

    const backdrop = page.getByTestId("research-stock-backdrop");
    await expect(backdrop).toContainText("Neutral");
    await expect(backdrop).toContainText("Stable");
    await expect(backdrop).toContainText("Easy");
    await expect(backdrop).toContainText("Medium");
    await expect(page.getByTestId("research-stock-backdrop-sector")).toHaveText(
      "Sector on record for FIXTUREUP: Fixture Sector A. How today’s regime leans for it: Favourable (synthetic rationale for the fixture sector).",
    );
  });

  test("scores and technicals: empty, switched-off and error states", async ({ page }) => {
    await stockRoutes(page);
    await json(page, CARD, { detail: "not_found" }, 404);
    await json(page, BACKDROP, { symbol: "FIXTUREUP", raw_sector: null, macro_state: { market: null, inflation: null, liquidity: null, risk: null }, sector_bias: "NEUTRAL", sector_rationale: null });
    await openStock(page);
    await page.getByTestId("research-stock-tab-scores").click();
    await expect(page.getByTestId("research-stock-card-empty")).toContainText("No scores for FIXTUREUP yet");
    await expect(page.getByTestId("research-stock-backdrop-empty")).toContainText("No market backdrop yet");

    await json(page, CARD, { detail: "feature_not_enabled" }, 403);
    await openStock(page);
    await page.getByTestId("research-stock-tab-scores").click();
    await expect(page.getByTestId("research-stock-card-locked")).toContainText("Scores and technicals are not switched on for this account");

    await json(page, CARD, {});
    await json(page, BACKDROP, {});
    await openStock(page);
    await page.getByTestId("research-stock-tab-scores").click();
    await expect(page.getByTestId("research-stock-card-error")).toContainText("Scores and technicals didn’t load", SLOW);
    await expect(page.getByTestId("research-stock-backdrop-error")).toContainText("The market backdrop didn’t load", SLOW);
  });
});

test.describe("Research — filings", () => {
  test("a material filing names its company with the company icon", async ({ page }) => {
    await base(page);
    // Shape: backend/routes/filings.py signals (contract SignalC in services/adapters/filings.adapter.ts)
    await json(page, "**/api/filings/signals*", {
      ok: true,
      signals: [{ rank: 1, id: "fixture-signal-1", company: "Fixture Gainer Ltd", ticker: "FIXTUREUP", type: "order_win", one: "Synthetic one-line read of a fixture filing.", metric: null, docLabel: null, date: "2026-10-09T10:00:00+00:00", sentiment: "positive" }],
    });
    await page.goto(`${APP}/tool/research`);
    const card = page.getByTestId("research-signal");
    await expect(card).toHaveCount(1);
    await expect(card).toContainText("Synthetic one-line read of a fixture filing.");
    await expect(card.locator('[data-testid="entity-icon"][data-kind="stock"][data-key="FIXTUREUP"]')).toBeVisible();
    await expect(page.getByTestId("research-signal-company")).toHaveText("Fixture Gainer Ltd");
  });
});

test.describe("Research — mutual fund", () => {
  test.beforeEach(async ({ page }) => { await base(page); });

  test("overview ← lookup, factsheet and data-platform figures; the fund house icon sits beside the name", async ({ page }) => {
    await fundRoutes(page);
    await openFund(page);
    await expect(page.getByTestId("research-entity-icon").locator('[data-testid="entity-icon"][data-kind="fund-house"]')).toBeVisible();
    await expect(page.getByTestId("research-entity-meta")).toHaveText("AMFI 900002 · Fixture Mutual Fund");

    // NAV from the lookup; its date is null in the fixture, as on staging.
    await expect(page.getByTestId("research-fund-nav")).toHaveText("₹41.2345");
    await expect(page.getByTestId("research-fund-facts")).toContainText("Date not reported");
    await expect(page.getByTestId("research-fund-aum")).toHaveText("₹2.0K Cr");
    // The factsheet leads with the Direct plan (0.60%); the page shows the plan that was searched for (Regular, 1.45%).
    await expect(page.getByTestId("research-fund-expense")).toHaveText("1.45%");
    await expect(page.getByTestId("research-fund-facts")).toContainText("Regular plan");
    await expect(page.getByTestId("research-fund-plan-note")).toHaveCount(0);
    await expect(page.getByTestId("research-fund-risk-label")).toHaveText("Very High");
    await expect(page.getByTestId("research-fund-benchmark")).toHaveText("Fixture 500 Total Return Index");
    await expect(page.getByTestId("research-fund-facts-missing")).toHaveText("Not in the data for this scheme: the NAV’s date.");

    const returns = page.getByTestId("research-fund-returns");
    const row = (period: string) => returns.getByRole("row").filter({ hasText: period });
    await expect(row("1 year")).toContainText("+12.40%");
    await expect(row("1 year")).toContainText("+10.00%");
    await expect(row("1 year")).toContainText("+2.40%");
    await expect(row("3 months")).toContainText("−2.50%");
    await expect(row("3 months")).toContainText("Not computed");
    // The 3-year category average is null: said so, not hidden.
    await expect(row("3 years")).toContainText("+15.00%");
    await expect(row("3 years").locator('[data-na="true"]')).toHaveCount(2);

    await expect(page.getByTestId("research-fund-sharpe")).toHaveText("0.85");
    await expect(page.getByTestId("research-fund-drawdown")).toHaveText("−9.5%");
    await expect(page.getByTestId("research-fund-rank")).toHaveText("Not available");

    const peers = page.getByTestId("research-fund-peers");
    await expect(peers).toContainText("Fixture Peer Fund One");
    await expect(peers).toContainText("+14.20%");
    await expect(peers.locator('[data-testid="entity-icon"][data-kind="fund-house"]')).toHaveCount(2);
    await expect(peers.locator('[data-na="true"]')).toHaveCount(1);

    await expect(page.getByTestId("research-fund-nc")).toContainText("Some parts of the fund page are not connected yet");
  });

  test("holdings and managers ← the factsheet", async ({ page }) => {
    await fundRoutes(page);
    await openFund(page);
    await page.getByTestId("research-fund-tab-holdings").click();
    const split = page.getByTestId("research-fund-split");
    await expect(split).toContainText("73.50%");
    await expect(split).toContainText("51.20%");
    await expect(split.locator('[data-na="true"]')).toHaveCount(1); // cash is null
    const holdings = page.getByTestId("research-fund-holdings");
    await expect(holdings.getByRole("row")).toHaveCount(4); // header + 3
    await expect(holdings).toContainText("Fixture Bank Ltd");
    await expect(holdings).toContainText("7.50%");
    // A company row carries a company icon; a treasury bill does not.
    await expect(holdings.locator('[data-testid="entity-icon"][data-kind="stock"]')).toHaveCount(2);
    await expect(page.getByTestId("research-fund-sectors")).toContainText("Fixture Financials");

    await page.getByTestId("research-fund-tab-managers").click();
    const managers = page.getByTestId("research-fund-managers");
    await expect(managers).toContainText("Fixture Manager One");
    await expect(managers).toContainText("11.5 years");
    await expect(managers.locator('[data-na="true"]')).toHaveCount(2); // the second manager has no start date or tenure
  });

  test("a factsheet for another plan only is named as such", async ({ page }) => {
    await fundRoutes(page);
    const sheet = load("copilot-research-fund-factsheet.json");
    delete sheet.sibling;
    await json(page, FACTSHEET, sheet);
    await openFund(page);
    await expect(page.getByTestId("research-fund-expense")).toHaveText("0.60%");
    await expect(page.getByTestId("research-fund-plan-note")).toContainText("The factsheet on file is for Fixture Flexi Cap Fund Direct Growth (Direct plan)");
  });

  test("empty states: no factsheet collected, and no figures on the data platform", async ({ page }) => {
    await fundRoutes(page);
    await json(page, FACTSHEET, { instrument_key: "ISIN:INF000FIX002", scheme_name: "Fixture Flexi Cap Fund Growth", available: false, reason: "scrape scheduled for off-hours", queued: true });
    await json(page, NUMBERS, {
      isin: "INF000FIX002", name: null, category: null,
      returns: { "1m": null, "3m": null, "1y": null, "3y": null }, category_avg: { "1y": null, "3y": null },
      risk: { sharpe: null, sortino: null, volatility_1y: null, max_drawdown: null },
      ranking: { composite_rank: null, category_size: null, top_position_pct: null }, top_peers: [], daas_available: false,
    });
    await openFund(page);
    await expect(page.getByTestId("research-fund-facts-empty")).toContainText("No factsheet on file for this scheme yet");
    // The NAV still shows; the factsheet figures read “Not available”.
    await expect(page.getByTestId("research-fund-nav")).toHaveText("₹41.2345");
    await expect(page.getByTestId("research-fund-aum")).toHaveText("Not available");
    await expect(page.getByTestId("research-fund-expense")).toHaveText("Not available");
    await expect(page.getByTestId("research-fund-returns-empty")).toContainText("No returns or risk figures for this scheme yet");
    await expect(page.getByTestId("research-fund-returns")).toHaveCount(0);
    await page.getByTestId("research-fund-tab-holdings").click();
    await expect(page.getByTestId("research-fund-holdings-empty")).toContainText("No holdings on file for this scheme yet");
    await page.getByTestId("research-fund-tab-managers").click();
    await expect(page.getByTestId("research-fund-managers-empty")).toContainText("No manager details on file for this scheme yet");
  });

  test("empty state: a scheme the data platform cannot match has no returns block", async ({ page }) => {
    await fundRoutes(page);
    await json(page, LOOKUP, { resolved: { instrument_key: "SCHEME:900002", scheme_name: "" }, latest_nav: null });
    await openFund(page);
    await expect(page.getByTestId("research-fund-nav")).toHaveText("Not available");
    await expect(page.getByTestId("research-fund-returns-empty")).toContainText("could not be matched to a fund on the data platform");
  });

  test("error states: each block reports its own failed read", async ({ page }) => {
    await fundRoutes(page);
    await json(page, FACTSHEET, {});
    await json(page, NUMBERS, {});
    await openFund(page);
    await expect(page.getByTestId("research-fund-facts-error")).toContainText("The fund’s factsheet didn’t load", SLOW);
    await expect(page.getByTestId("research-fund-returns-error")).toContainText("Returns and risk didn’t load", SLOW);
    await page.getByTestId("research-fund-tab-holdings").click();
    await expect(page.getByTestId("research-fund-holdings-error")).toContainText("The fund’s holdings didn’t load", SLOW);
    await page.getByTestId("research-fund-tab-managers").click();
    await expect(page.getByTestId("research-fund-managers-error")).toContainText("The fund’s managers didn’t load", SLOW);

    await json(page, LOOKUP, {});
    await openFund(page);
    await expect(page.getByTestId("research-fund-lookup-error")).toContainText("The latest NAV didn’t load", SLOW);
  });
});

test.describe("Research — phone (390×844)", () => {
  test.use({ viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true });

  const sideways = (page: Page) => page.evaluate(() => {
    const sc = document.querySelector('[data-testid="copilot-scroll"]') as HTMLElement | null;
    return {
      doc: document.documentElement.scrollWidth - document.documentElement.clientWidth,
      scroll: sc ? sc.scrollWidth - sc.clientWidth : 0,
    };
  });

  test("the stock and fund pages fit the phone without sideways page scroll", async ({ page }) => {
    await base(page);
    await stockRoutes(page);
    await fundRoutes(page);

    await openStock(page);
    await expect(page.getByTestId("research-stock-close")).toHaveText("₹145.90");
    await expect(page.getByTestId("research-stock-quarters")).toContainText("Q1 FY27");
    expect(await sideways(page)).toEqual({ doc: 0, scroll: 0 });
    await page.getByTestId("research-stock-tab-scores").click();
    await expect(page.getByTestId("research-stock-card")).toContainText("Synthetic summary");
    await expect(page.getByTestId("research-stock-backdrop")).toBeVisible();
    expect(await sideways(page)).toEqual({ doc: 0, scroll: 0 });

    await openFund(page);
    await expect(page.getByTestId("research-fund-returns")).toContainText("1 year");
    expect(await sideways(page)).toEqual({ doc: 0, scroll: 0 });
    await page.getByTestId("research-fund-tab-holdings").click();
    await expect(page.getByTestId("research-fund-holdings")).toContainText("Fixture Bank Ltd");
    expect(await sideways(page)).toEqual({ doc: 0, scroll: 0 });
  });
});

// Screenshots for checking the layout by eye. Not assertions: skipped unless SHOT_DIR is set.
// The screen scrolls inside the shell, so the viewport is made tall enough to hold a whole page.
for (const size of [{ tag: "desktop", width: 1280, height: 2600 }, { tag: "phone", width: 390, height: 4200 }]) {
  test.describe(`Research shots — ${size.tag}`, () => {
    test.skip(!process.env.SHOT_DIR, "set SHOT_DIR to capture screenshots");
    test.use({ viewport: { width: size.width, height: size.height }, ...(size.tag === "phone" ? { hasTouch: true, isMobile: true } : {}) });

    test(`stock and fund pages ${size.tag}`, async ({ page }) => {
      const shot = (name: string) => page.getByTestId("screen-tool-research").screenshot({ path: path.join(process.env.SHOT_DIR ?? ".", `research-${name}-${size.tag}.png`) });
      await base(page);
      await stockRoutes(page);
      await fundRoutes(page);
      await openStock(page);
      await expect(page.getByTestId("research-stock-close")).toBeVisible();
      await expect(page.getByTestId("research-stock-quarters")).toBeVisible();
      await shot("stock-overview");
      await page.getByTestId("research-stock-tab-scores").click();
      await expect(page.getByTestId("research-stock-card")).toBeVisible();
      await expect(page.getByTestId("research-stock-backdrop")).toBeVisible();
      await shot("stock-scores");
      await openFund(page);
      await expect(page.getByTestId("research-fund-returns")).toBeVisible();
      await shot("fund-overview");
      await page.getByTestId("research-fund-tab-holdings").click();
      await expect(page.getByTestId("research-fund-holdings")).toBeVisible();
      await shot("fund-holdings");
    });
  });
}
