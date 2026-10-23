/**
 * One-screen Copilot app — the Screener's lenses, sorting, mutual-fund metrics and click-to-chart.
 *
 * MOCK — not real data: every /api/* answer is a route mock. The two stocks (FIXALPHA, FIXBRAVO) and
 * their figures are made up; the price bars are the same synthetic series the Research spec uses.
 * The panel under test is Research's own StockResearch, so the same chart routes are mocked.
 *
 * Runs with the other Copilot specs — see pw.copilot-app.config.ts.
 */
import { test, expect, type Page } from "@playwright/test";
import fs from "fs";
import path from "path";
import { mockApi } from "../helpers/api-mock";

const APP = "/v5/app";
const EX = JSON.parse(fs.readFileSync(path.join(process.cwd(), "e2e", "fixtures", "screener-run-examples.json"), "utf-8"));

const json = (page: Page, pattern: string | RegExp, body: unknown, status = 200) =>
  page.route(pattern, (route) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) }));

/** The two-stock run, with fund metrics: ALPHA is in the scanner's universe, BRAVO is not. */
const RUN = (() => {
  const run = JSON.parse(JSON.stringify(EX.matches));
  const [a, b] = run.widget.universe;
  Object.assign(a, { mcap: 250000, roe: 21.5, promoter: 52.1, fii: 18.2, fiiChange: 0.6, mfChange: 12.5, amcsUp: 5, amcsDn: 1, amcsHolding: 9 });
  Object.assign(b, { mcap: 9000, roe: 14.0, promoter: 40.0, fii: 9.5, fiiChange: -0.4, mfChange: null, amcsUp: null, amcsDn: null, amcsHolding: null });
  run.coverage = { ...run.coverage, mfChange: { filled: 1, total: 2 }, amcsUp: { filled: 1, total: 2 }, amcsDn: { filled: 1, total: 2 }, amcsHolding: { filled: 1, total: 2 } };
  return run;
})();

function bars(count: number) {
  const out: [string, number, number, number, number, number][] = [];
  const d = new Date(Date.UTC(2026, 9, 9));
  while (out.length < count) {
    const dow = d.getUTCDay();
    if (dow !== 0 && dow !== 6) out.unshift([d.toISOString().slice(0, 10), 0, 0, 0, 0, 0]);
    d.setUTCDate(d.getUTCDate() - 1);
  }
  return out.map(([day], i) => {
    const close = Math.round((100 + i * 0.1) * 100) / 100;
    return [day, close, close + 1, close - 1, close, 100000 + i * 1000] as [string, number, number, number, number, number];
  });
}

async function open(page: Page, run: unknown = RUN) {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await mockApi(page, "populated");
  await json(page, "**/api/screeners", []);
  const bodies: unknown[] = [];
  await page.route("**/api/screeners/run", (route) => {
    bodies.push(route.request().postDataJSON());
    return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(run) });
  });
  const chartCalls: string[] = [];
  await page.route("**/api/research/chart-live/*/ohlcv*", (route) => {
    chartCalls.push(new URL(route.request().url()).pathname.split("/").slice(-2)[0]);
    return route.fulfill({
      status: 200, contentType: "application/json",
      body: JSON.stringify({
        symbol: "X", timeframe: "1D", bars: bars(460), data_quality_status: "VALID", pit_status: "PIT_UNVERIFIED", findings: [],
        provenance: { provider: "nidp.prices_eod_adjusted", series: "EQ", adjustment_status: "SPLIT_BONUS_ADJUSTED", last_bar_date: "2026-10-09", source_mode: "live", last_event_type: null },
      }),
    });
  });
  await json(page, "**/api/copilot/widgets/company_financials", { kind: "company_financials", title: "x", data: { symbol: "FIXALPHA", v3_score: {}, rows: [] } });
  await page.route("**/api/move-odds/stocks/*/card", (r) => r.fulfill({ status: 404, contentType: "application/json", body: "{}" }));
  await page.route("**/api/stock/*/why", (r) => r.fulfill({ status: 404, contentType: "application/json", body: "{}" }));
  return { errors, bodies, chartCalls };
}

async function run(page: Page) {
  await page.goto(`${APP}/tool/screener`);
  await page.getByTestId("screener-rule-value").nth(1).fill("15");
  await page.getByTestId("screener-run").click();
  await expect(page.getByTestId("screener-results")).toHaveAttribute("data-state", "ready");
}

const rows = (page: Page) => page.getByTestId("screener-row");
const symbols = async (page: Page) => rows(page).evaluateAll((els) => els.map((e) => e.getAttribute("data-symbol")));

test.describe("Screener — chart on click", () => {
  test("TC-8/9: a row opens the Research stock view with its price chart; Esc closes it and focus returns", async ({ page }) => {
    const { errors, chartCalls } = await open(page);
    await run(page);
    await rows(page).first().focus();
    await rows(page).first().press("Enter");
    const panel = page.getByTestId("screener-stock-panel");
    await expect(panel).toBeVisible();
    await expect(panel.getByTestId("research-entity-name")).toHaveText("FIXALPHA");
    await expect(panel.getByTestId("research-stock-price")).toBeVisible();   // Research's own price block
    expect(chartCalls).toContain("FIXALPHA");
    await page.keyboard.press("Escape");
    await expect(panel).toHaveCount(0);
    await expect(rows(page).first()).toBeFocused();
    // A click works the same, and the backdrop closes it.
    await rows(page).nth(1).click();
    await expect(page.getByTestId("screener-stock-panel").getByTestId("research-entity-name")).toHaveText("FIXBRAVO");
    await page.getByTestId("screener-stock-backdrop").click({ position: { x: 5, y: 5 } });
    await expect(page.getByTestId("screener-stock-panel")).toHaveCount(0);
    expect(errors).toEqual([]);
  });

  test("TC-14: a ready-made (strategy builder) row opens the same panel", async ({ page }) => {
    const { errors } = await open(page);
    await json(page, "**/api/strategy-builder/templates", [{ key: "t1", name: "Fixture Uptrend", description: "d", definition: { entry: [] } }]);
    await json(page, "**/api/strategy-builder/screen", { as_of: "2026-10-12", ranked_by: "rsi14", candidates: [{ symbol: "FIXALPHA", close: 101.5, rsi14: 61 }] });
    await page.goto(`${APP}/tool/screener`);
    await page.getByTestId("screener-strategy-template").first().click();
    await expect(page.getByTestId("screener-strategy-results")).toHaveAttribute("data-state", "ready");
    await page.getByTestId("screener-strategy-row").first().click();
    await expect(page.getByTestId("screener-stock-panel").getByTestId("research-entity-name")).toHaveText("FIXALPHA");
    expect(errors).toEqual([]);
  });
});

test.describe("Screener — lenses, sorting and fund metrics", () => {
  test("TC-10: the lenses change the columns over the same rows", async ({ page }) => {
    await open(page);
    await run(page);
    const head = page.getByTestId("screener-table").locator("thead");
    await expect(head).toContainText("P/E");
    await expect(head).not.toContainText("Promoter %");
    await page.getByTestId("screener-lens-ownership").click();
    await expect(head).toContainText("Promoter %");
    await expect(head).toContainText("Houses ↑");
    await expect(rows(page).first()).toContainText("52.1");
    await page.getByTestId("screener-lens-fundamentals").click();
    await expect(head).toContainText("ROCE %");
    await page.getByTestId("screener-lens-technicals").click();
    await expect(head).toContainText("Momentum");
    await expect(rows(page)).toHaveCount(2);
  });

  test("TC-11: sorting reverses on a second click and a missing value always sorts last", async ({ page }) => {
    await open(page);
    await run(page);
    await page.getByTestId("screener-lens-ownership").click();
    const sortBy = (col: string) => page.locator(`[data-testid="screener-sort"][data-col="${col}"]`);
    await sortBy("promoter").click();                 // descending first
    expect(await symbols(page)).toEqual(["FIXALPHA", "FIXBRAVO"]);
    await sortBy("promoter").click();                 // then ascending
    expect(await symbols(page)).toEqual(["FIXBRAVO", "FIXALPHA"]);
    // BRAVO has no MF value: last in both directions.
    await sortBy("amcsUp").click();
    expect(await symbols(page)).toEqual(["FIXALPHA", "FIXBRAVO"]);
    await sortBy("amcsUp").click();
    expect(await symbols(page)).toEqual(["FIXALPHA", "FIXBRAVO"]);
  });

  test("TC-16: a stock the fund data does not cover shows — (never 0), and a fund rule says Nifty 500 only", async ({ page }) => {
    const { bodies } = await open(page);
    await page.goto(`${APP}/tool/screener`);
    await page.getByTestId("screener-rule-metric").first().selectOption("amcsUp");
    await page.getByTestId("screener-rule-value").first().fill("3");
    await page.getByTestId("screener-rule-value").nth(1).fill("15");
    await expect(page.getByTestId("screener-query")).toHaveText("Screen stocks where P/E under 15, fund houses raising over 3");
    await expect(page.getByTestId("screener-open-copilot")).toBeDisabled();           // the Copilot cannot read a fund rule
    await page.getByTestId("screener-run").click();
    await expect(page.getByTestId("screener-results")).toHaveAttribute("data-state", "ready");
    expect(bodies).toEqual([{ conditions: [{ key: "amcsUp", op: "over", value: "3" }, { key: "pe", op: "under", value: "15" }], bucket: "", include_funds: true }]);
    await expect(page.getByTestId("screener-results-coverage")).toContainText("Fund houses raising filled for 1 of 2 stocks (Nifty 500 only)");
    await page.getByTestId("screener-lens-ownership").click();
    const bravo = page.locator('[data-testid="screener-row"][data-symbol="FIXBRAVO"]');
    for (const col of ["mfChange", "amcsUp", "amcsDn", "amcsHolding"]) await expect(bravo.locator(`[data-col="${col}"]`)).toHaveText("—");   // no value: a dash, never 0
    await expect(page.locator('[data-testid="screener-row"][data-symbol="FIXALPHA"] [data-col="amcsUp"]')).toHaveText("5");
  });
});

test.describe("Screener — live columns and mobile", () => {
  test("TC-12: no live quote → no LTP/Day columns, never a column of dashes or zeros", async ({ page }) => {
    await open(page);
    await run(page);
    await expect(page.getByTestId("screener-table").locator("thead")).not.toContainText("LTP");
    await page.getByTestId("screener-lens-technicals").click();
    await expect(page.getByTestId("screener-table").locator("thead")).not.toContainText("Day %");
  });

  test("TC-12: while the feed is LIVE the table gets Kite's LTP and Day %; a stock the feed lacks shows —", async ({ page }) => {
    await open(page);
    // MOCK — not real data: an invented live snapshot with a quote for FIXALPHA only.
    const snapshot = {
      as_of: "2026-10-21T05:43:10+00:00", data_at: "2026-10-21T05:43:09+00:00", age_seconds: 1.2, stale: false, stale_after_seconds: 75, cadence_seconds: 30,
      mode: "live", session: "open", source: "ws", final: false, count: 1, missing: ["FIXBRAVO"], read_only: true,
      quotes: { FIXALPHA: { ltp: 120, change: 3, change_pct: 2.5, open: 117, high: 121, low: 116, close: 117, volume: 1000, oi: null, ts: "2026-10-21T11:13:09+05:30" } },
    };
    await page.route("**/api/live/**", (route) => route.fulfill(
      new URL(route.request().url()).pathname.endsWith("/stream")
        ? { status: 200, contentType: "text/event-stream", body: `retry: 100\n\nevent: snapshot\ndata: ${JSON.stringify(snapshot)}\n\n` }
        : { status: 200, contentType: "application/json", body: JSON.stringify(snapshot) }));
    await run(page);
    const head = page.getByTestId("screener-table").locator("thead");
    await expect(head).toContainText("LTP");
    await expect(head).toContainText("Day %");
    const alpha = page.locator('[data-testid="screener-row"][data-symbol="FIXALPHA"]');
    await expect(alpha).toContainText("120.00");
    await expect(alpha).toContainText("+2.50");
    await expect(page.locator('[data-testid="screener-row"][data-symbol="FIXBRAVO"]')).toContainText("—");
  });

  test("TC-15: at phone width the panel is a full-width sheet and the page does not scroll sideways", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await open(page);
    await run(page);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    await rows(page).first().click();
    const box = await page.getByTestId("screener-stock-panel").boundingBox();
    expect(Math.round(box?.width ?? 0)).toBe(390);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  });
});
