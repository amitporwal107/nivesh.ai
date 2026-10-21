/**
 * One-screen Copilot app — the Screener's in-page results (POST /api/screeners/run).
 *
 * MOCK — not real data: every /api/* answer is a route mock. The run responses in
 * e2e/fixtures/screener-run-examples.json were produced by the real route code
 * (backend/routes/screeners.py) over two made-up stocks.
 *
 * Runs with the other Copilot specs — see pw.copilot-app.config.ts.
 */
import { test, expect, type Page } from "@playwright/test";
import fs from "fs";
import path from "path";
import { mockApi } from "../helpers/api-mock";

const APP = "/v5/app";
const EX = JSON.parse(fs.readFileSync(path.join(process.cwd(), "e2e", "fixtures", "screener-run-examples.json"), "utf-8"));
const SAVED = [{ screener_id: "scr_fixture01", name: "Fixture quality screen", query: "Screen stocks where ROE over 20, P/E under 15", conditions: [{ key: "roe", op: "over", value: "20" }, { key: "pe", op: "under", value: "15" }], bucket: "", updated_at: "2026-10-11T10:00:00+00:00" }];

const json = (page: Page, pattern: string | RegExp, body: unknown, status = 200) =>
  page.route(pattern, (route) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) }));

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

/** Answers POST /api/screeners/run with each given reply in turn (the last one repeats). */
async function mockRun(page: Page, ...replies: Array<{ status?: number; body: unknown }>) {
  const bodies: unknown[] = [];
  await page.route("**/api/screeners/run", (route) => {
    bodies.push(route.request().postDataJSON());
    const reply = replies[Math.min(bodies.length - 1, replies.length - 1)];
    return route.fulfill({ status: reply.status ?? 200, contentType: "application/json", body: JSON.stringify(reply.body) });
  });
  return bodies;
}

async function open(page: Page) {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await mockApi(page, "populated");
  const sent = await mockAsk(page);
  await json(page, "**/api/screeners", SAVED);
  return { sent, errors };
}

const results = (page: Page) => page.getByTestId("screener-results");

test.describe("Screener results — desktop", () => {
  test("a run shows the matches on the page; Open in Copilot still hands the sentence over", async ({ page }) => {
    const { sent, errors } = await open(page);
    const bodies = await mockRun(page, { body: EX.matches });
    await page.goto(`${APP}/tool/screener`);
    await expect(page.getByTestId("screen-tool-screener")).toBeVisible();
    await expect(page.getByTestId("screener-saved-name")).toHaveText("Fixture quality screen");
    await expect(results(page)).toHaveAttribute("data-state", "idle");
    await expect(page.getByTestId("screener-results-idle")).toBeVisible();
    await expect(page.getByTestId("screener-results-nc")).toHaveCount(0);
    await expect(page.getByTestId("screener-run")).toBeDisabled();
    await expect(page.getByTestId("screener-open-copilot")).toBeDisabled();

    await page.getByTestId("screener-rule-value").nth(1).fill("15");      // second rule is P/E, "under" by default
    await expect(page.getByTestId("screener-query")).toHaveText("Screen stocks where P/E under 15");
    await page.getByTestId("screener-run").click();

    await expect(results(page)).toHaveAttribute("data-state", "ready");
    expect(bodies).toEqual([{ conditions: [{ key: "pe", op: "under", value: "15" }], bucket: "" }]);
    await expect(page.getByTestId("screener-results-count")).toHaveText("2 stocks match");
    await expect(page.getByTestId("screener-results-query")).toHaveText("Screen stocks where P/E under 15");
    const widget = page.getByTestId("screener-results-widget");
    await expect(widget.locator("tbody tr")).toHaveCount(2);
    await expect(widget.locator("tbody tr").first()).toContainText("FIXALPHA");
    await expect(widget.locator("tbody tr").first()).toContainText("12.5");
    await expect(widget).toContainText("P/E < 15");                       // the widget's own compiled query
    await expect(page.getByTestId("screener-results-coverage")).toHaveText("Data as of 12 Oct 2026 · P/E ratio filled for 2 of 2 stocks");
    await expect(page.getByTestId("screener-results-nodata")).toHaveCount(0);
    await expect(page.getByTestId("screener-results-nomatch")).toHaveCount(0);
    // Nothing went to the Copilot and the screen is still open.
    expect(sent).toEqual([]);
    await expect(page).toHaveURL(/\/v5\/app\/tool\/screener$/);

    await page.getByTestId("screener-open-copilot").click();
    await expect.poll(() => sent).toEqual(["Screen stocks where P/E under 15"]);
    await expect(page).toHaveURL(/\/v5\/app\/t\/asked1$/);
    expect(errors).toEqual([]);
  });

  test("a rule on a metric with no data says so, and names the metric", async ({ page }) => {
    const { sent, errors } = await open(page);
    const bodies = await mockRun(page, { body: EX.no_data });
    await page.goto(`${APP}/tool/screener`);
    await page.getByTestId("screener-rule-value").first().fill("20");
    await expect(page.getByTestId("screener-query")).toHaveText("Screen stocks where ROE over 20");
    await page.getByTestId("screener-run").click();
    await expect(results(page)).toHaveAttribute("data-state", "empty");
    expect(bodies).toEqual([{ conditions: [{ key: "roe", op: "over", value: "20" }], bucket: "" }]);
    await expect(page.getByTestId("screener-results-count")).toHaveText("0 stocks match");
    await expect(page.getByTestId("screener-results-nodata")).toContainText("The latest screening data has no values for ROE");
    await expect(page.getByTestId("screener-results-nodata")).toContainText("remove that rule");
    await expect(page.getByTestId("screener-results-nomatch")).toHaveCount(0);
    await expect(page.getByTestId("screener-results-widget")).toHaveCount(0);
    await expect(page.getByTestId("screener-results-coverage")).toHaveText("Data as of 12 Oct 2026 · ROE filled for 0 of 2 stocks");
    expect(sent).toEqual([]);
    expect(errors).toEqual([]);
  });

  test("rules that are only too strict say that instead", async ({ page }) => {
    const { errors } = await open(page);
    await mockRun(page, { body: EX.no_match });
    await page.goto(`${APP}/tool/screener`);
    await page.getByTestId("screener-rule-value").nth(1).fill("5");
    await page.getByTestId("screener-run").click();
    await expect(results(page)).toHaveAttribute("data-state", "empty");
    await expect(page.getByTestId("screener-results-nomatch")).toContainText("No stock passes every rule");
    await expect(page.getByTestId("screener-results-nomatch")).toContainText("Loosen a threshold");
    await expect(page.getByTestId("screener-results-nodata")).toHaveCount(0);
    await expect(page.getByTestId("screener-results-coverage")).toHaveText("Data as of 12 Oct 2026 · P/E ratio filled for 2 of 2 stocks");
    expect(errors).toEqual([]);
  });

  test("a size universe the data has no labels for is named too", async ({ page }) => {
    const { errors } = await open(page);
    const bodies = await mockRun(page, { body: EX.no_size_labels });
    await page.goto(`${APP}/tool/screener`);
    await page.getByTestId("screener-bucket-large").click();
    await page.getByTestId("screener-rule-value").nth(1).fill("15");
    await expect(page.getByTestId("screener-query")).toHaveText("Screen large cap stocks where P/E under 15");
    await page.getByTestId("screener-run").click();
    expect(bodies).toEqual([{ conditions: [{ key: "pe", op: "under", value: "15" }], bucket: "large" }]);
    await expect(page.getByTestId("screener-results-nodata")).toContainText("The latest screening data has no values for market-cap size");
    await expect(page.getByTestId("screener-results-nodata")).toContainText("set the universe to Any size");
    await expect(page.getByTestId("screener-results-coverage")).toHaveText("Data as of 12 Oct 2026 · P/E ratio filled for 2 of 2 stocks · Market-cap size filled for 0 of 2 stocks");
    expect(errors).toEqual([]);
  });

  test("200 {} is an error state with a retry that works", async ({ page }) => {
    const { errors } = await open(page);
    const bodies = await mockRun(page, { body: {} }, { body: EX.matches });
    await page.goto(`${APP}/tool/screener`);
    await page.getByTestId("screener-rule-value").nth(1).fill("15");
    await page.getByTestId("screener-run").click();
    await expect(results(page)).toHaveAttribute("data-state", "error");
    await expect(page.getByTestId("screener-results-error")).toContainText("The screen didn’t run");
    await expect(page.getByTestId("screener-results-error")).toContainText("not in the expected format");
    await expect(page.getByTestId("screener-results-count")).toHaveCount(0);
    await page.waitForTimeout(600);
    await expect(page.getByText("Something went wrong")).toHaveCount(0);     // a failed read is not a toast
    await page.getByTestId("screener-results-error").getByRole("button", { name: "Retry ›" }).click();
    await expect(results(page)).toHaveAttribute("data-state", "ready");
    await expect(page.getByTestId("screener-results-count")).toHaveText("2 stocks match");
    expect(bodies.length).toBe(2);
    expect(errors).toEqual([]);
  });

  for (const [label, reply, text] of [
    ["the source did not answer (ok:false)", { body: EX.unreachable }, "the stock data source did not answer"],
    ["HTTP 500", { status: 500, body: { detail: "boom" } }, "the server reported an error"],
    ["a half-shaped answer", { body: { ok: true, as_of_date: "2026-10-12", widget: {}, coverage: {}, matched: 2, universe_complete: true } }, "not in the expected format"],
    ["rows that disagree with the count", { body: { ...EX.matches, matched: 1 } }, "not in the expected format"],
    ["a count with no rows", { body: { ...EX.no_data, matched: 3 } }, "not in the expected format"],
  ] as Array<[string, { status?: number; body: unknown }, string]>) {
    test(`error state: ${label}`, async ({ page }) => {
      const { errors } = await open(page);
      await mockRun(page, reply);
      await page.goto(`${APP}/tool/screener`);
      await page.getByTestId("screener-rule-value").first().fill("20");
      await page.getByTestId("screener-run").click();
      await expect(results(page)).toHaveAttribute("data-state", "error");
      await expect(page.getByTestId("screener-results-error")).toContainText(text);
      await expect(page.getByTestId("screener-results-error").getByRole("button", { name: "Retry ›" })).toBeVisible();
      await expect(page.getByTestId("screener-results-widget")).toHaveCount(0);
      expect(errors).toEqual([]);
    });
  }

  test("Run on a saved row uses the same path and leaves the Copilot alone", async ({ page }) => {
    const { sent, errors } = await open(page);
    const bodies = await mockRun(page, { body: EX.no_data });
    await page.goto(`${APP}/tool/screener`);
    await page.getByTestId("screener-saved-run").click();
    await expect(results(page)).toHaveAttribute("data-state", "empty");
    expect(bodies).toEqual([{ conditions: [{ key: "roe", op: "over", value: "20" }, { key: "pe", op: "under", value: "15" }], bucket: "" }]);
    await expect(page.getByTestId("screener-results-query")).toHaveText("Fixture quality screen · Screen stocks where ROE over 20, P/E under 15");
    await expect(page.getByTestId("screener-results-nodata")).toContainText("no values for ROE");
    await expect(page.getByTestId("screener-results-coverage")).toHaveText("Data as of 12 Oct 2026 · ROE filled for 0 of 2 stocks · P/E ratio filled for 2 of 2 stocks");
    await expect(results(page)).toBeInViewport();
    expect(sent).toEqual([]);
    await expect(page).toHaveURL(/\/v5\/app\/tool\/screener$/);
    expect(errors).toEqual([]);
  });

  test("a template fills the rules; running it posts those rules", async ({ page }) => {
    const { errors } = await open(page);
    const bodies = await mockRun(page, { body: EX.no_data });
    await page.goto(`${APP}/tool/screener`);
    await page.getByTestId("screener-preset").first().click();
    await expect(page.getByTestId("screener-query")).toHaveText("Screen stocks where ROCE over 20, ROE over 18, sales growth over 12, profit growth over 12, debt to equity under 0.5");
    await page.waitForTimeout(300);
    expect(bodies).toEqual([]);                                            // picking a template does not run it
    await page.getByTestId("screener-run").click();
    await expect(results(page)).toHaveAttribute("data-state", "empty");
    expect(bodies).toEqual([{ bucket: "", conditions: [
      { key: "roce", op: "over", value: "20" }, { key: "roe", op: "over", value: "18" }, { key: "salesG", op: "over", value: "12" },
      { key: "profitG", op: "over", value: "12" }, { key: "de", op: "under", value: "0.5" },
    ] }]);
    // ROE, ROCE, sales/profit growth and D/E are all empty in the fixture day
    await expect(page.getByTestId("screener-results-nodata")).toContainText("The latest screening data has no values for ROCE, ROE, Sales growth 3Y, Profit growth 3Y and Debt to Equity");
    await expect(page.getByTestId("screener-results-nodata")).toContainText("remove those rules");
    expect(errors).toEqual([]);
  });

  test("while the run is in flight the section says so; every press of Run asks again", async ({ page }) => {
    const { errors } = await open(page);
    const bodies: unknown[] = [];
    let release: () => void = () => {};
    const gate = new Promise<void>((r) => { release = r; });
    await page.route("**/api/screeners/run", async (route) => {
      bodies.push(route.request().postDataJSON());
      if (bodies.length === 1) await gate;
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(EX.matches) });
    });
    await page.goto(`${APP}/tool/screener`);
    await page.getByTestId("screener-rule-value").nth(1).fill("15");
    await page.getByTestId("screener-run").click();
    await expect(results(page)).toHaveAttribute("data-state", "loading");
    await expect(page.getByTestId("screener-results-loading")).toBeVisible();
    await expect(page.getByTestId("screener-results-query")).toHaveText("Screen stocks where P/E under 15");
    release();
    await expect(results(page)).toHaveAttribute("data-state", "ready");
    await page.getByTestId("screener-run").click();
    await expect.poll(() => bodies.length).toBe(2);
    await expect(results(page)).toHaveAttribute("data-state", "ready");
    await expect(page.getByTestId("screener-results-count")).toHaveText("2 stocks match");
    expect(errors).toEqual([]);
  });

  test("more matches than rows sent is said plainly", async ({ page }) => {
    const { errors } = await open(page);
    await mockRun(page, { body: { ...EX.matches, matched: 1214, universe_complete: false } });
    await page.goto(`${APP}/tool/screener`);
    await page.getByTestId("screener-rule-value").nth(1).fill("15");
    await page.getByTestId("screener-run").click();
    await expect(page.getByTestId("screener-results-count")).toHaveText("Showing 2 of 1,214 matching stocks, in ticker order");
    await expect(page.getByTestId("screener-results-coverage")).toContainText("Only the first 2 stocks of the day were screened");
    expect(errors).toEqual([]);
  });

  test("the table's own Ask button reaches the Copilot", async ({ page }) => {
    const { sent, errors } = await open(page);
    await mockRun(page, { body: EX.matches });
    await page.goto(`${APP}/tool/screener`);
    await page.getByTestId("screener-rule-value").nth(1).fill("15");
    await page.getByTestId("screener-run").click();
    const row = page.getByTestId("screener-results-widget").locator("tbody tr").first();
    await row.hover();
    await row.getByRole("button", { name: /Ask/ }).click();
    await expect.poll(() => sent).toEqual(["Tell me about FIXALPHA — is it worth a deeper look?"]);
    expect(errors).toEqual([]);
  });
});

// The two hand-written minimal mocks given in the hand-over report, exactly as written there.
const MINI_WIDGET = {
  title: "Stock screen",
  columns: [
    { key: "name", label: "Stock", kind: "text", align: "left" },
    { key: "pe", label: "P/E", kind: "num", align: "right" },
    { key: "roe", label: "ROE", unit: "%", kind: "num", align: "right" },
  ],
  filter_labels: { pe: "P/E", roe: "ROE" },
  name_key: "name", ticker_key: "ticker", sector_key: "sector",
};
const MINI_MATCHES = {
  ok: true, as_of_date: "2026-10-12", matched: 2, universe_complete: true,
  coverage: { pe: { filled: 2, total: 2 }, roe: { filled: 0, total: 2 }, mcap: { filled: 0, total: 2 } },
  widget: { ...MINI_WIDGET, filters: { pe_max: 15 }, universe: [
    { name: "FIXALPHA", ticker: "FIXALPHA", sector: "IT", pe: 12.5, roe: null },
    { name: "FIXBRAVO", ticker: "FIXBRAVO", sector: null, pe: 9.1, roe: null },
  ] },
};
const MINI_NO_DATA = {
  ok: true, as_of_date: "2026-10-12", matched: 0, universe_complete: true,
  coverage: { pe: { filled: 2, total: 2 }, roe: { filled: 0, total: 2 }, mcap: { filled: 0, total: 2 } },
  widget: { ...MINI_WIDGET, filters: { roe_min: 20 }, universe: [] },
};

test.describe("Screener results — the minimal mocks from the report", () => {
  test("two rows, rule on P/E", async ({ page }) => {
    const { sent, errors } = await open(page);
    const bodies = await mockRun(page, { body: MINI_MATCHES });
    await page.goto(`${APP}/tool/screener`);
    await page.getByTestId("screener-rule-value").nth(1).fill("15");
    await page.getByTestId("screener-run").click();
    expect(bodies).toEqual([{ conditions: [{ key: "pe", op: "under", value: "15" }], bucket: "" }]);
    await expect(results(page)).toHaveAttribute("data-state", "ready");
    await expect(page.getByTestId("screener-results-query")).toHaveText("Screen stocks where P/E under 15");
    await expect(page.getByTestId("screener-results-count")).toHaveText("2 stocks match");
    await expect(page.getByTestId("screener-results-widget").locator("tbody tr")).toHaveCount(2);
    await expect(page.getByTestId("screener-results-widget").locator("tbody tr").nth(1)).toContainText("FIXBRAVO");
    await expect(page.getByTestId("screener-results-coverage")).toHaveText("Data as of 12 Oct 2026 · P/E ratio filled for 2 of 2 stocks");
    await expect(page.getByTestId("screener-results-nodata")).toHaveCount(0);
    expect(sent).toEqual([]);
    await page.getByTestId("screener-open-copilot").click();
    await expect.poll(() => sent).toEqual(["Screen stocks where P/E under 15"]);
    expect(errors).toEqual([]);
  });

  test("rule on ROE, which has no data", async ({ page }) => {
    const { errors } = await open(page);
    await mockRun(page, { body: MINI_NO_DATA });
    await page.goto(`${APP}/tool/screener`);
    await page.getByTestId("screener-rule-value").first().fill("20");
    await page.getByTestId("screener-run").click();
    await expect(results(page)).toHaveAttribute("data-state", "empty");
    await expect(page.getByTestId("screener-results-count")).toHaveText("0 stocks match");
    await expect(page.getByTestId("screener-results-nodata")).toHaveText("The latest screening data has no values for ROENo stock can pass a rule on something the data does not carry, so this screen matches nothing. That is a gap in the data, not a verdict on any stock. To screen on the rest, remove that rule.");
    await expect(page.getByTestId("screener-results-coverage")).toHaveText("Data as of 12 Oct 2026 · ROE filled for 0 of 2 stocks");
    await expect(page.getByTestId("screener-results-widget")).toHaveCount(0);
    expect(errors).toEqual([]);
  });
});

test.describe("Screener results — phone (390×844)", () => {
  test.use({ viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true });

  const sideways = (page: Page) => page.evaluate(() => {
    const sc = document.querySelector('[data-testid="copilot-scroll"]') as HTMLElement | null;
    return {
      doc: document.documentElement.scrollWidth - document.documentElement.clientWidth,
      scroll: sc ? sc.scrollWidth - sc.clientWidth : 0,
    };
  });

  test("matches fit the phone without sideways page scroll", async ({ page }) => {
    const { errors } = await open(page);
    await mockRun(page, { body: EX.matches });
    await page.goto(`${APP}/tool/screener`);
    await page.getByTestId("screener-rule-value").nth(1).fill("15");
    await page.getByTestId("screener-run").click();
    await expect(page.getByTestId("screener-results-count")).toHaveText("2 stocks match");
    await expect(page.getByTestId("screener-results-widget").locator("tbody tr")).toHaveCount(2);
    await expect(results(page)).toBeInViewport();
    expect(await sideways(page)).toEqual({ doc: 0, scroll: 0 });
    expect(errors).toEqual([]);
  });

  test("the no-data explanation fits the phone", async ({ page }) => {
    const { errors } = await open(page);
    await mockRun(page, { body: EX.no_data });
    await page.goto(`${APP}/tool/screener`);
    await page.getByTestId("screener-rule-value").first().fill("20");
    await page.getByTestId("screener-run").click();
    await expect(page.getByTestId("screener-results-nodata")).toBeVisible();
    expect(await sideways(page)).toEqual({ doc: 0, scroll: 0 });
    expect(errors).toEqual([]);
  });
});

// ── the strategy builder's ready-made screens, run on the Screener screen ──
// MOCK — not real data. Shapes: backend/routes/strategy_builder.py
// (GET /templates, POST /screen → { candidates, count, as_of_date, ranked_by, score_basis }).
test.describe("Screener — ready-made strategy screens", () => {
  const TEMPLATES = [
    { key: "uptrend", name: "Fixture Uptrend", description: "Fixture description of an uptrend screen.", asset_class: "STOCK", definition: { universe: { type: "index", ref: "FIXTURE" }, entry: { all: [] }, ranking: { by: "return_20d_pct" } } },
    { key: "squeeze", name: "Fixture Squeeze", description: "Fixture description of a squeeze screen.", asset_class: "STOCK", definition: { universe: { type: "index", ref: "FIXTURE" }, entry: { all: [] }, ranking: { by: "vol_z20" } } },
  ];
  const UPTREND = { candidates: [
    { symbol: "FIXALPHA", close: 512.4, rsi14: 61.2, return_20d_pct: 14.5, vol_z20: 1.8, accumulation_score: 72 },
    { symbol: "FIXBRAVO", close: 88.15, rsi14: 58.0, return_20d_pct: 9.25, vol_z20: 0.4, accumulation_score: 55 },
  ], count: 2, as_of_date: "2026-10-12", ranked_by: "return_20d_pct", score_basis: "return_20d_pct" };

  test("a ready-made screen runs in place and lists its candidates; a row asks the Copilot", async ({ page }) => {
    const { sent, errors } = await open(page);
    await json(page, "**/api/strategy-builder/templates", { templates: TEMPLATES });
    const definitions: unknown[] = [];
    await page.route("**/api/strategy-builder/screen", (route) => {
      const body = route.request().postDataJSON() as { definition: { ranking: { by: string } } };
      definitions.push(body.definition);
      const reply = body.definition.ranking.by === "vol_z20" ? { candidates: [], count: 0, as_of_date: "2026-10-12", ranked_by: "vol_z20", score_basis: "vol_z20" } : UPTREND;
      return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(reply) });
    });
    await page.goto(`${APP}/tool/screener`);
    const cards = page.getByTestId("screener-strategy-template");
    await expect(cards).toHaveText([/Fixture Uptrend/, /Fixture Squeeze/]);
    await expect(page.getByTestId("screener-strategy-results")).toHaveCount(0); // nothing runs until one is picked

    await cards.nth(0).click();
    await expect(page.getByTestId("screener-strategy-results")).toHaveAttribute("data-state", "ready");
    expect(definitions).toEqual([TEMPLATES[0].definition]); // the template's own rules are what is run
    await expect(page.getByTestId("screener-strategy-count")).toHaveText("2 stocks");
    await expect(page.getByTestId("screener-strategy-row")).toHaveText(["FIXALPHA", "FIXBRAVO"]);
    const section = page.getByTestId("screener-strategy-screens");
    await expect(section).toContainText("ranked by 20-day return %");
    await expect(section).toContainText("₹512.40");
    await expect(section).toContainText("14.50");

    // A screen with no candidate says so instead of showing an empty table.
    await cards.nth(1).click();
    await expect(page.getByTestId("screener-strategy-results")).toHaveAttribute("data-state", "empty");
    await expect(section).toContainText("No stock passes this screen today");

    await cards.nth(0).click();
    await page.getByTestId("screener-strategy-row").first().click();
    await expect.poll(() => sent).toEqual(["Tell me about FIXALPHA"]);
    expect(errors).toEqual([]);
  });

  test("templates or a run that answer 200 {} show an error with retry, not a crash", async ({ page }) => {
    const { errors } = await open(page);
    await json(page, "**/api/strategy-builder/templates", {});
    await page.goto(`${APP}/tool/screener`);
    await expect(page.getByTestId("screener-strategy-screens")).toContainText("No ready-made screens are set up");
    await json(page, "**/api/strategy-builder/templates", { templates: TEMPLATES });
    await json(page, "**/api/strategy-builder/screen", {});
    await page.reload();
    await page.getByTestId("screener-strategy-template").first().click();
    await expect(page.getByTestId("screener-strategy-results")).toHaveAttribute("data-state", "error");
    await expect(page.getByTestId("screener-strategy-results")).toContainText("the response was not in the expected shape");
    expect(errors).toEqual([]);
  });
});

