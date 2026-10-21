/**
 * One-screen Copilot app (/v5/app) — Smart trading desk: the RESULTS EXPECTATION in the Events tab
 * (screens/tradingdesk/EventsTab.tsx ResultsExpectation + events-data.ts useResultsExpectation).
 *
 * MOCK — not real data: every route below is answered with an inline payload in the contract's shape
 * (GET /api/markets/events-calendar, .../history, .../expectation) with synthetic values. Expected figures
 * are worked out from the payload. Mocked APIs, production build — see pw.copilot-app.config.ts.
 * The clock is fixed at Wed 21 Oct 2026, 11:30 IST.
 */
import { test, expect, type Page, type Route } from "@playwright/test";
import { mockApi } from "../helpers/api-mock";

const DESK = "/v5/app/trader/desk";
const SLOW = { timeout: 15_000 };
const json = (route: Route, body: unknown, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });

// MOCK — not real data
const ev = (id: string, date: string, symbol: string, type: string, extra: Record<string, unknown> = {}) => ({
  id, date, symbol, name: `${symbol} Ltd (mock)`, sector: "IT", type, timing: "post", detail: type === "RESULTS" ? "Results for Q2 FY2027" : "Dividend of ₹5",
  universe: { n50: true, fno: true }, source: "NSE", announced_at: null, ...extra,
});
const CAL = {
  month: "2026-10", as_of: "2026-10-20",
  events: [ev("dec", "2026-10-14", "TCS", "RESULTS"), ev("up", "2026-10-23", "AAA", "RESULTS"), ev("div", "2026-10-22", "INFY", "DIVIDEND", { timing: "ex" })],
  holidays: [], index_closes: [], gaps: [],
};
const HIST = { symbol: "AAA", type: "RESULTS", coverage_from: "2025-10-01", n: 2, basis: "mock", occurrences: [
  { date: "2026-07-09", event_day_pct: -2.2, d1_pct: 0.6, w1_pct: -1.0 }, { date: "2026-04-10", event_day_pct: 0.5, d1_pct: 0.1, w1_pct: 0.3 }],
  stats: { event_day: { avg: -0.85, min: -2.2, max: 0.5 }, d1: { avg: 0.35, min: 0.1, max: 0.6 }, w1: { avg: -0.35, min: -1.0, max: 0.3 } } };

const METHOD = {
  name: "Seasonal year-on-year baseline",
  formula: "Last year's same-quarter figure grown by the median of the last four year-on-year changes; the band is the stock's own backtested error.",
  n_quarters: 12,
  backtest: { n_quarters: 8, median_abs_err_pct: 3.2, within_band_pct: 62.5 },
  universe_backtest: { n: 14200, median_abs_err_pct: 4.1, within_band_pct: 58.4 },
};
const EVIDENCE = [
  { date: "2026-10-02", title: "Bags order worth ₹1,200 crore (mock)", category: "orders", source: "NSE", url: "https://www.nseindia.com/mock-filing-1" },
  { date: "2026-09-18", title: "Credit rating reaffirmed (mock)", category: "rating", source: "BSE", url: "javascript:alert(1)" },
];
const UP = {
  symbol: "AAA", event_date: "2026-10-23", period_end: "2026-09-30", period_label: "Q2 FY2027", basis: "consolidated", status: "upcoming",
  metrics: [
    { key: "revenue", unit: "₹ cr", expected: { low: 9800, mid: 10200, high: 10600 }, same_quarter_last_year: 9400, previous_quarter: 9900, trend_yoy_pct: 8.5, filed: null, vs_mid_pct: null, reliable: true, note: null },
    { key: "pat", unit: "₹ cr", expected: { low: 1200, mid: 1300, high: 1400 }, same_quarter_last_year: 1150, previous_quarter: 1240, trend_yoy_pct: 11.2, filed: null, vs_mid_pct: null, reliable: true, note: null },
    { key: "eps", unit: "₹", expected: null, same_quarter_last_year: 12.4, previous_quarter: 13.1, trend_yoy_pct: null, filed: null, vs_mid_pct: null, reliable: false, note: "Share count changed in the last year (split), so per-share history is not comparable." },
  ],
  method: METHOD, evidence: EVIDENCE, gaps: ["No analyst consensus is available; this baseline uses only the company's own filed results"],
};
const DECL = {
  symbol: "TCS", event_date: "2026-10-14", period_end: "2026-09-30", period_label: "Q2 FY2027", basis: "consolidated", status: "declared",
  metrics: [
    { key: "revenue", unit: "₹ cr", expected: { low: 9800, mid: 10200, high: 10600 }, same_quarter_last_year: 9400, previous_quarter: 9900, trend_yoy_pct: 8.5,
      filed: { value: 10850, broadcast_at: "2026-10-14T17:42:00+05:30", audit_status: "Unaudited" }, vs_mid_pct: 6.37, reliable: true, note: null },
    { key: "pat", unit: "₹ cr", expected: { low: 1200, mid: 1300, high: 1400 }, same_quarter_last_year: 1150, previous_quarter: 1240, trend_yoy_pct: 11.2,
      filed: { value: 1310, broadcast_at: "2026-10-14T17:42:00+05:30", audit_status: null }, vs_mid_pct: 0.77, reliable: true, note: null },
    { key: "eps", unit: "₹", expected: null, same_quarter_last_year: 12.4, previous_quarter: 13.1, trend_yoy_pct: null,
      filed: { value: 14.2, broadcast_at: "2026-10-14T17:42:00+05:30", audit_status: null }, vs_mid_pct: null, reliable: false, note: "Not comparable after a split." },
  ],
  method: METHOD, evidence: [], gaps: [],
};

async function setup(page: Page, opts: { exp?: (symbol: string, date: string) => { status?: number; body?: unknown; delayMs?: number }; calls?: string[] } = {}) {
  await mockApi(page, "populated");
  await page.clock.setFixedTime(new Date("2026-10-21T06:00:00Z"));
  await page.route("**/api/markets/events-calendar/history*", (r) => json(r, HIST));
  await page.route("**/api/markets/events-calendar/expectation*", async (r) => {
    const u = new URL(r.request().url());
    const symbol = u.searchParams.get("symbol") ?? "", date = u.searchParams.get("date") ?? "";
    opts.calls?.push(`${symbol}|${date}`);
    const o = opts.exp?.(symbol, date) ?? {};
    if (o.delayMs) await new Promise((res) => setTimeout(res, o.delayMs));
    return json(r, o.body ?? (symbol === "TCS" ? DECL : UP), o.status ?? 200);
  });
  await page.route("**/api/markets/events-calendar?*", (r) => json(r, CAL));
}

test.describe("Desk — Results expectation (desktop)", () => {
  test.use({ viewport: { width: 1440, height: 1000 } });

  test("TC-E1/E2/E3/E4 upcoming: request, labels, range, track record", async ({ page }) => {
    const calls: string[] = [];
    await setup(page, { calls });
    await page.goto(`${DESK}?tab=events`);
    await page.getByTestId("events-chip-up").click();
    const exp = page.getByTestId("events-exp");
    await expect(exp).toBeVisible(SLOW);
    expect(calls).toEqual(["AAA|2026-10-23"]);
    await expect(page.getByTestId("events-exp-label")).toHaveText("NIVESH BASELINE FROM PUBLISHED RESULTS · NOT A CONSENSUS · NOT A FORECAST");
    await expect(page.getByTestId("events-exp-heading")).toHaveText("EXPECTED RANGE · Q2 FY2027 · CONSOLIDATED");
    await expect(page.getByTestId("events-exp-range-revenue")).toHaveText("₹9,800 cr – ₹10,600 cr");
    await expect(page.getByTestId("events-exp-metric-revenue")).toContainText("MIDPOINT ₹10,200 cr");
    await expect(page.getByTestId("events-exp-metric-revenue")).toContainText("₹9,400 cr");   // last year, same quarter
    await expect(page.getByTestId("events-exp-metric-revenue")).toContainText("₹9,900 cr");   // previous quarter
    await expect(page.getByTestId("events-exp-metric-revenue")).toContainText("+8.5%");
    await expect(page.getByTestId("events-exp-range-pat")).toHaveText("₹1,200 cr – ₹1,400 cr");
    // 62.5% of 8 quarters = 5 of 8; across all stocks 58% of 14,200
    await expect(page.getByTestId("events-exp-track-stock")).toHaveText("FOR AAA: the method was within its band in 5 of 8 quarters (63%) · median error 3.2%");
    await expect(page.getByTestId("events-exp-track-all")).toHaveText("ACROSS ALL STOCKS: within its band in 58% of 14,200 tests · median error 4.1%");
    await expect(page.getByTestId("events-exp-method")).toContainText("Seasonal year-on-year baseline");
    await expect(page.getByTestId("events-exp-filed-mark")).toHaveCount(0); // nothing filed yet
    await page.setViewportSize({ width: 1440, height: 2300 });
    await page.screenshot({ path: "e2e/screenshots/desk-expectation/desktop-upcoming.png" });
  });

  test("TC-E5 no track record is said, not omitted", async ({ page }) => {
    await setup(page, { exp: () => ({ body: { ...UP, method: { ...METHOD, backtest: null, universe_backtest: null } } }) });
    await page.goto(`${DESK}?tab=events`);
    await page.getByTestId("events-chip-up").click();
    await expect(page.getByTestId("events-exp-track-stock")).toHaveText("FOR AAA: no track record, too few published quarters to test the method", SLOW);
    await expect(page.getByTestId("events-exp-track-all")).toHaveText("ACROSS ALL STOCKS: track record not available");
  });

  test("TC-E6 unreliable metric: words and the note, no number range", async ({ page }) => {
    await setup(page);
    await page.goto(`${DESK}?tab=events`);
    await page.getByTestId("events-chip-up").click();
    const u = page.getByTestId("events-exp-unreliable-eps");
    await expect(u).toContainText("No reliable expectation.", SLOW);
    await expect(u).toContainText("Share count changed in the last year (split)");
    await expect(page.getByTestId("events-exp-range-eps")).toHaveCount(0);
  });

  test("TC-E7/E8/E9 declared: filed beside the range, position not verdict, audit status as sent", async ({ page }) => {
    await setup(page);
    await page.goto(`${DESK}?tab=events`);
    await page.getByTestId("events-chip-dec").click();
    await expect(page.getByTestId("events-exp-heading")).toHaveText("FILED RESULT VS BASELINE · Q2 FY2027 · CONSOLIDATED", SLOW);
    // revenue 10,850 > high 10,600 -> above; pct from the API (6.37 -> +6.4%)
    await expect(page.getByTestId("events-exp-vs-revenue")).toHaveText("Above the baseline range · +6.4% vs midpoint");
    await expect(page.getByTestId("events-exp-filed-revenue")).toContainText("₹10,850 cr");
    // pat 1,310 within 1,200–1,400 -> inside; 0.77 -> +0.8%
    await expect(page.getByTestId("events-exp-vs-pat")).toHaveText("Inside the baseline range · +0.8% vs midpoint");
    // eps has no reliable range: filed is shown, nothing compared
    await expect(page.getByTestId("events-exp-filed-eps")).toContainText("No reliable baseline to compare it with.");
    await expect(page.getByTestId("events-exp-vs-eps")).toHaveCount(0);
    await expect(page.getByTestId("events-exp-filed-mark")).toHaveCount(2);
    // audit status: exactly what the API sent, else "not recorded"; never invented
    await expect(page.getByTestId("events-exp-audit-revenue")).toContainText("UNAUDITED · FILED 2026-10-14 17:42");
    await expect(page.getByTestId("events-exp-audit-pat")).toContainText("AUDIT STATUS NOT RECORDED");
    await expect(page.getByTestId("events-exp-audit-pat")).not.toContainText(/unaudited/i);
    // never a verdict
    const text = await page.getByTestId("events-exp").innerText();
    expect(text).not.toMatch(/\b(beat|miss|missed|bullish|bearish|surprise)\b/i);
    await page.setViewportSize({ width: 1440, height: 2300 });
    await page.screenshot({ path: "e2e/screenshots/desk-expectation/desktop-declared.png" });
  });

  test("TC-E10/E11 evidence: linked sources, safe urls only; empty says so", async ({ page }) => {
    await setup(page);
    await page.goto(`${DESK}?tab=events`);
    await page.getByTestId("events-chip-up").click();
    const rows = page.getByTestId("events-exp-evidence-row");
    await expect(rows).toHaveCount(2, SLOW);
    const link = page.getByTestId("events-exp-evidence-link");
    await expect(link).toHaveCount(1); // the javascript: url is not a link
    await expect(link).toHaveAttribute("href", "https://www.nseindia.com/mock-filing-1");
    await expect(link).toHaveAttribute("target", "_blank");
    await expect(link).toHaveAttribute("rel", /noopener/);
    await expect(rows.first()).toContainText("2026-10-02 · ORDERS · SOURCE NSE");
    await expect(rows.nth(1)).toContainText("Credit rating reaffirmed (mock)");
    // declared fixture has none
    await page.getByTestId("events-panel-close").click();
    await page.getByTestId("events-chip-dec").click();
    await expect(page.getByTestId("events-exp-evidence-empty")).toHaveText("No filings or news on file for this quarter.", SLOW);
  });

  test("TC-E12 gaps are shown as written", async ({ page }) => {
    await setup(page);
    await page.goto(`${DESK}?tab=events`);
    await page.getByTestId("events-chip-up").click();
    await expect(page.getByTestId("events-exp-gaps")).toContainText("No analyst consensus is available; this baseline uses only the company's own filed results", SLOW);
  });

  test("TC-E13 failure: error with Retry; the price history still renders", async ({ page }) => {
    await setup(page, { exp: () => ({ status: 502, body: { detail: "upstream_unavailable" } }) });
    await page.goto(`${DESK}?tab=events`);
    await page.getByTestId("events-chip-up").click();
    await expect(page.getByTestId("events-exp-error")).toBeVisible({ timeout: 25_000 });
    await expect(page.getByTestId("events-exp-retry")).toBeVisible();
    await expect(page.getByTestId("events-history-n")).toBeVisible();
    await expect(page.getByTestId("events-exp")).toHaveCount(0);
  });

  test("TC-E14 loading block while the call is pending", async ({ page }) => {
    await setup(page, { exp: () => ({ delayMs: 2500 }) });
    await page.goto(`${DESK}?tab=events`);
    await page.getByTestId("events-chip-up").click();
    await expect(page.getByTestId("events-exp-loading")).toBeVisible(SLOW);
    await expect(page.getByTestId("events-exp")).toBeVisible(SLOW);
  });

  test("TC-E15 a dividend makes no expectation call and shows no section", async ({ page }) => {
    const calls: string[] = [];
    await setup(page, { calls });
    await page.goto(`${DESK}?tab=events`);
    await page.getByTestId("events-chip-div").click();
    await expect(page.getByTestId("events-detail-title")).toHaveText("INFY Ltd (mock)", SLOW);
    await expect(page.getByTestId("events-history-n")).toBeVisible();
    await expect(page.getByTestId("events-exp")).toHaveCount(0);
    expect(calls).toEqual([]);
  });

  test("TC-E16 timeline row expands with the section in place", async ({ page }) => {
    await setup(page);
    await page.goto(`${DESK}?tab=events`);
    await page.getByTestId("events-view-tl").click();
    await page.getByTestId("events-tl-toggle-up").click();
    await expect(page.getByTestId("events-tl-row-up").getByTestId("events-exp")).toBeVisible(SLOW);
    await expect(page.getByTestId("events-tl-row-up").getByTestId("events-exp-range-revenue")).toHaveText("₹9,800 cr – ₹10,600 cr");
    await page.screenshot({ path: "e2e/screenshots/desk-expectation/desktop-timeline.png", fullPage: true });
  });

  test("TC-E18 a malformed payload shows the error state, not numbers", async ({ page }) => {
    await setup(page, { exp: () => ({ body: { symbol: "AAA", metrics: "nope" } }) });
    await page.goto(`${DESK}?tab=events`);
    await page.getByTestId("events-chip-up").click();
    await expect(page.getByTestId("events-exp-error")).toBeVisible({ timeout: 25_000 });
    await expect(page.getByTestId("events-exp-range-revenue")).toHaveCount(0);
  });
});

test.describe("Desk — Results expectation (phone)", () => {
  test.use({ viewport: { width: 390, height: 844 } });

  test("TC-E17 phone sheet shows the section, no sideways scroll", async ({ page }) => {
    await setup(page);
    await page.goto(`${DESK}?tab=events`);
    await page.getByTestId("events-m-day-2026-10-23").click();
    await page.getByTestId("events-m-row-up").click();
    await expect(page.getByTestId("events-sheet").getByTestId("events-exp-range-revenue")).toHaveText("₹9,800 cr – ₹10,600 cr", SLOW);
    await expect(page.getByTestId("events-sheet").getByTestId("events-exp-track-stock")).toBeVisible();
    await page.screenshot({ path: "e2e/screenshots/desk-expectation/phone-sheet.png" });
    const over = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    expect(over).toBeLessThanOrEqual(0);
  });
});
