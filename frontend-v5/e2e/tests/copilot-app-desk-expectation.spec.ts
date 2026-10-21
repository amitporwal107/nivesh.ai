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

// MOCK — not real data. Shape = the real router's (backend/nidp/services/daas_api/routers/desk_expectation.py).
const BY_REV = { n: 19000, median_abs_err_pct: 10.3, naive_flat_median_abs_err_pct: 18.2, within_band_pct: 81.3, within_band_n: 9400,
  in_sample_within_band_pct: 80.0, held_out_stocks: { calibrated_on_n: 9600, tested_n: 9400, within_band_pct: 81.3 },
  latest_quarter: { calibrated_on: ["2026-03-31"], tested_on: "2026-06-30", tested_n: 410, within_band_pct: 77.1 } };
const BY_PAT = { n: 18500, median_abs_err_pct: 21.4, naive_flat_median_abs_err_pct: 34.9, within_band_pct: 79.2, within_band_n: 9100,
  in_sample_within_band_pct: 78.0, held_out_stocks: { calibrated_on_n: 9300, tested_n: 9100, within_band_pct: 79.2 }, latest_quarter: null };
const METHOD = {
  name: "Same quarter last year × recent growth",
  formula: "expected = value of the same quarter a year earlier × (1 + average of the last two year-on-year growth rates); band = 10th–90th percentile of this method's own past errors across all stocks, for stocks with similar growth stability",
  n_quarters: 7,
  backtest: { n_quarters: 2, median_abs_err_pct: 4.0, within_band_pct: 50.0, note: "a stock has only a few testable quarters, so these figures describe it but do not set its band" },
  universe_backtest: BY_PAT, // PAT-only in the real API
  by_metric: { revenue: BY_REV, pat: BY_PAT },
};
const LABEL = "A baseline from the company's own published quarters, not an analyst consensus and not a forecast.";
const SOURCES = { quarters: "Company quarterly results as stored (nidp.nse_financials_quarterly; rows from Trendlyne and Screener)", calendar: "NSE event calendar (nidp.event_calendar)", announcements: "NSE corporate announcements (nidp.corporate_announcements)" };
const EVIDENCE = [
  { date: "2026-10-02", title: "Bags order worth ₹1,200 crore (mock)", category: "order", source: "NSE announcement (nidp.corporate_announcements)", url: "https://www.nseindia.com/mock-filing-1" },
  { date: "2026-09-18", title: "Credit rating reaffirmed (mock)", category: "credit rating", source: "NSE announcement (nidp.corporate_announcements)", url: "javascript:alert(1)" },
];
const EPS_NOTE = "last year's EPS is not shown: the share count changed since (bonus or split), so it is not comparable";
const UP = {
  symbol: "AAA", event_date: "2026-10-23", period_end: "2026-09-30", period_label: "Q2 FY2027", basis: "consolidated", status: "upcoming", intimated_at: null,
  audit_status: "unaudited", audit_basis: "stated in the company's board-meeting notice (nidp.event_calendar.purpose)", label: LABEL, compared_with: null,
  expected_as_of: "2026-10-21T23:59:59.999999+00:00", sources: SOURCES,
  metrics: [
    { key: "revenue", unit: "₹ crore", expected: { low: 9800, mid: 10200, high: 10600 }, same_quarter_last_year: 9400, previous_quarter: 9900, trend_yoy_pct: 8.5, filed: null, vs_mid_pct: null, within_band: null, reliable: true, note: "growth of 9.0 % and 8.0 % in the last two quarters, averaged 8.5 %; band from 1,800 past forecasts of stocks with steady growth", last_year_note: null },
    { key: "pat", unit: "₹ crore", expected: { low: 1200, mid: 1300, high: 1400 }, same_quarter_last_year: 1150, previous_quarter: 1240, trend_yoy_pct: 11.2, filed: null, vs_mid_pct: null, within_band: null, reliable: true, note: null, last_year_note: null },
    { key: "eps", unit: "₹ a share", expected: null, same_quarter_last_year: null, previous_quarter: 13.1, trend_yoy_pct: null, filed: null, vs_mid_pct: null, within_band: null, reliable: false, note: "expected EPS follows expected profit, which is not available for this stock", last_year_note: EPS_NOTE },
  ],
  method: METHOD, evidence: EVIDENCE, gaps: ["no analyst consensus is available (nidp.earnings_estimates is empty): this is a baseline, not a consensus"],
};
const FILED_AT = "2026-10-14T17:42:00+05:30";
const DECL = {
  symbol: "TCS", event_date: "2026-10-14", period_end: "2026-09-30", period_label: "Q2 FY2027", basis: "consolidated", status: "declared", intimated_at: "2026-10-06T10:00:00+05:30",
  audit_status: "unaudited", audit_basis: "stated in the company's board-meeting notice (nidp.event_calendar.purpose)", label: LABEL,
  compared_with: "vs Nivesh baseline, not vs consensus", expected_as_of: "2026-10-14T12:12:00+00:00", sources: SOURCES,
  metrics: [
    { key: "revenue", unit: "₹ crore", expected: { low: 9800, mid: 10200, high: 10600 }, same_quarter_last_year: 9400, previous_quarter: 9900, trend_yoy_pct: 8.5,
      filed: { value: 10850, broadcast_at: FILED_AT, audit_status: "unaudited" }, vs_mid_pct: 6.4, within_band: false, reliable: true, note: null, last_year_note: null },
    { key: "pat", unit: "₹ crore", expected: { low: 1200, mid: 1300, high: 1400 }, same_quarter_last_year: 1150, previous_quarter: 1240, trend_yoy_pct: 11.2,
      filed: { value: 1310, broadcast_at: FILED_AT, audit_status: "unaudited" }, vs_mid_pct: 0.8, within_band: true, reliable: true, note: null, last_year_note: null },
    { key: "eps", unit: "₹ a share", expected: null, same_quarter_last_year: null, previous_quarter: 13.1, trend_yoy_pct: null,
      filed: { value: 14.2, broadcast_at: FILED_AT, audit_status: "unaudited" }, vs_mid_pct: null, within_band: null, reliable: false, note: "Not comparable after a split.", last_year_note: EPS_NOTE },
  ],
  method: METHOD, evidence: [], gaps: [],
};
const withAudit = (base: typeof DECL, status: string, basis: string | null) => ({
  ...base, audit_status: status, audit_basis: basis,
  metrics: base.metrics.map((m) => ({ ...m, filed: m.filed ? { ...m.filed, audit_status: status } : null })),
});

async function setup(page: Page, opts: { exp?: (symbol: string, date: string) => { status?: number; body?: unknown; delayMs?: number }; calls?: string[] } = {}) {
  await mockApi(page, "populated");
  await page.clock.setFixedTime(new Date("2026-10-21T06:00:00Z"));
  await page.route("**/api/markets/events-calendar/history*", (r) => json(r, HIST));
  await page.route("**/api/markets/events-calendar/expectation?*", async (r) => {
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

  test("TC-E1/E2/E3 upcoming: request, labels, range, as-of and sources", async ({ page }) => {
    const calls: string[] = [];
    await setup(page, { calls });
    await page.goto(`${DESK}?tab=events`);
    await page.getByTestId("events-chip-up").click();
    const exp = page.getByTestId("events-exp");
    await expect(exp).toBeVisible(SLOW);
    expect(calls).toEqual(["AAA|2026-10-23"]);
    await expect(page.getByTestId("events-exp-label")).toHaveText("NIVESH BASELINE FROM PUBLISHED RESULTS · NOT A CONSENSUS · NOT A FORECAST");
    await expect(page.getByTestId("events-exp-api-label")).toHaveText(LABEL);
    await expect(page.getByTestId("events-exp-heading")).toHaveText("EXPECTED RANGE · Q2 FY2027 · CONSOLIDATED");
    await expect(page.getByTestId("events-exp-range-revenue")).toHaveText("₹9,800 cr – ₹10,600 cr"); // unit "₹ crore" from the API
    await expect(page.getByTestId("events-exp-metric-revenue")).toContainText("MIDPOINT ₹10,200 cr");
    await expect(page.getByTestId("events-exp-metric-revenue")).toContainText("₹9,400 cr");   // last year, same quarter
    await expect(page.getByTestId("events-exp-metric-revenue")).toContainText("₹9,900 cr");   // previous quarter
    await expect(page.getByTestId("events-exp-metric-revenue")).toContainText("+8.5%");
    await expect(page.getByTestId("events-exp-note-revenue")).toContainText("band from 1,800 past forecasts");
    await expect(page.getByTestId("events-exp-range-pat")).toHaveText("₹1,200 cr – ₹1,400 cr");
    await expect(page.getByTestId("events-exp-method")).toContainText("Same quarter last year × recent growth");
    await expect(page.getByTestId("events-exp-method")).toContainText("Built from 7 published quarters, using only what was published before 2026-10-21.");
    await expect(page.getByTestId("events-exp-method")).toContainText("A stock has only a few testable quarters");
    await expect(page.getByTestId("events-exp-sources")).toContainText("NSE event calendar (nidp.event_calendar)");
    await expect(page.getByTestId("events-exp-filed-mark")).toHaveCount(0); // nothing filed yet
    await page.setViewportSize({ width: 1440, height: 2300 });
    await page.screenshot({ path: "e2e/screenshots/desk-expectation/desktop-upcoming.png" });
  });

  test("TC-E4 track record is per metric: a profit record never sits under revenue", async ({ page }) => {
    await setup(page);
    await page.goto(`${DESK}?tab=events`);
    await page.getByTestId("events-chip-up").click();
    const rev = page.getByTestId("events-exp-metric-revenue");
    const pat = page.getByTestId("events-exp-metric-pat");
    // all stocks, revenue: by_metric.revenue, held-out sample within_band_n (9,400), median error beside the naive benchmark
    await expect(page.getByTestId("events-exp-track-all-revenue")).toHaveText(
      "ACROSS ALL STOCKS (held out): within its band in 81% of 9,400 tests · median error 10.3% vs 18.2% if last year's quarter were repeated", SLOW);
    await expect(page.getByTestId("events-exp-track-latest-revenue")).toHaveText("Latest quarter (2026-06-30): within its band in 77% of 410, a small sample.");
    // all stocks, profit: by_metric.pat (9,100 tests, 21.4% vs 34.9%)
    await expect(page.getByTestId("events-exp-track-all-pat")).toHaveText(
      "ACROSS ALL STOCKS (held out): within its band in 79% of 9,100 tests · median error 21.4% vs 34.9% if last year's quarter were repeated");
    // the stock's own record is profit-only: round(50 × 2 / 100) = 1 of 2 tested quarters
    await expect(page.getByTestId("events-exp-track-stock-pat")).toHaveText("FOR AAA: the method was within its band in 1 of 2 tested quarters · median error 4.0%");
    await expect(page.getByTestId("events-exp-track-stock-revenue")).toHaveText("FOR AAA: not tested separately for revenue from operations");
    // nothing leaks across: no profit figure under revenue, no revenue figure under profit
    await expect(rev).not.toContainText("21.4%");
    await expect(rev).not.toContainText("9,100");
    await expect(pat).not.toContainText("10.3%");
    await expect(pat).not.toContainText("9,400 tests");
  });

  test("TC-E5 no track record is said, not omitted", async ({ page }) => {
    await setup(page, { exp: () => ({ body: { ...UP, method: { ...METHOD, backtest: null, universe_backtest: { n: 0 }, by_metric: { revenue: { n: 0 }, pat: { n: 0 } } } } }) });
    await page.goto(`${DESK}?tab=events`);
    await page.getByTestId("events-chip-up").click();
    await expect(page.getByTestId("events-exp-track-stock-pat")).toHaveText("FOR AAA: no track record, too few published quarters to test the method", SLOW);
    await expect(page.getByTestId("events-exp-track-all-pat")).toHaveText("ACROSS ALL STOCKS: track record not available");
    await expect(page.getByTestId("events-exp-track-all-revenue")).toHaveText("ACROSS ALL STOCKS: track record not available");
  });

  test("TC-E5b band not yet checked on held-out stocks: said, with the test count", async ({ page }) => {
    const pat = { ...BY_PAT, within_band_pct: null, within_band_n: 0, held_out_stocks: null };
    await setup(page, { exp: () => ({ body: { ...UP, method: { ...METHOD, by_metric: { revenue: BY_REV, pat } } } }) });
    await page.goto(`${DESK}?tab=events`);
    await page.getByTestId("events-chip-up").click();
    await expect(page.getByTestId("events-exp-track-all-pat")).toHaveText(
      "ACROSS ALL STOCKS: band not yet checked on held-out stocks (18,500 tests) · median error 21.4% vs 34.9% if last year's quarter were repeated", SLOW);
  });

  test("TC-E6 unreliable metric: words and the note, no number range; last-year note shown", async ({ page }) => {
    await setup(page);
    await page.goto(`${DESK}?tab=events`);
    await page.getByTestId("events-chip-up").click();
    const u = page.getByTestId("events-exp-unreliable-eps");
    await expect(u).toContainText("No reliable expectation.", SLOW);
    await expect(u).toContainText("expected EPS follows expected profit, which is not available for this stock");
    await expect(page.getByTestId("events-exp-range-eps")).toHaveCount(0);
    await expect(page.getByTestId("events-exp-lynote-eps")).toHaveText(EPS_NOTE);
    await expect(page.getByTestId("events-exp-metric-eps")).toContainText("₹13.10"); // "₹ a share" unit: rupees per share
  });

  test("TC-E7/E8/E9 declared: filed beside the range, position not verdict, audit status and its basis", async ({ page }) => {
    await setup(page);
    await page.goto(`${DESK}?tab=events`);
    await page.getByTestId("events-chip-dec").click();
    await expect(page.getByTestId("events-exp-heading")).toHaveText("FILED RESULT VS BASELINE · Q2 FY2027 · CONSOLIDATED", SLOW);
    // revenue within_band false and 10,850 > high 10,600 -> above; pct from the API
    await expect(page.getByTestId("events-exp-vs-revenue")).toHaveText("Above the baseline range · +6.4% vs midpoint");
    await expect(page.getByTestId("events-exp-filed-revenue")).toContainText("₹10,850 cr");
    // pat within_band true -> inside
    await expect(page.getByTestId("events-exp-vs-pat")).toHaveText("Inside the baseline range · +0.8% vs midpoint");
    // eps has no reliable range: filed is shown, nothing compared
    await expect(page.getByTestId("events-exp-filed-eps")).toContainText("No reliable baseline to compare it with.");
    await expect(page.getByTestId("events-exp-filed-eps")).toContainText("₹14.20");
    await expect(page.getByTestId("events-exp-vs-eps")).toHaveCount(0);
    await expect(page.getByTestId("events-exp-filed-mark")).toHaveCount(2);
    // what the filed figure is compared with
    await expect(page.getByTestId("events-exp-compared-revenue")).toHaveText("VS NIVESH BASELINE, NOT VS CONSENSUS");
    await expect(page.getByTestId("events-exp-compared-pat")).toHaveText("VS NIVESH BASELINE, NOT VS CONSENSUS");
    // audit status as the API sent it, with where it was read from
    await expect(page.getByTestId("events-exp-audit-revenue")).toContainText("UNAUDITED · FILED 2026-10-14 17:42");
    await expect(page.getByTestId("events-exp-audit-basis-revenue")).toHaveText("stated in the company's board-meeting notice (nidp.event_calendar.purpose)");
    // never a verdict
    const text = await page.getByTestId("events-exp").innerText();
    expect(text).not.toMatch(/\b(beat|miss|missed|bullish|bearish|surprise)\b/i);
    await page.setViewportSize({ width: 1440, height: 2300 });
    await page.screenshot({ path: "e2e/screenshots/desk-expectation/desktop-declared.png" });
  });

  test("TC-E9b audit status 'not recorded' is said so and 'unaudited' is never added", async ({ page }) => {
    await setup(page, { exp: (sym) => ({ body: sym === "TCS" ? withAudit(DECL, "not recorded", null) : UP }) });
    await page.goto(`${DESK}?tab=events`);
    await page.getByTestId("events-chip-dec").click();
    await expect(page.getByTestId("events-exp-audit-pat")).toContainText("AUDIT STATUS NOT RECORDED", SLOW);
    await expect(page.getByTestId("events-exp-audit-revenue")).toContainText("AUDIT STATUS NOT RECORDED");
    await expect(page.getByTestId("events-exp")).not.toContainText(/unaudited/i);
    await expect(page.getByTestId("events-exp-audit-basis-pat")).toHaveCount(0);
  });

  test("TC-E9c audit status 'mixed' and 'audited' are shown exactly as sent", async ({ page }) => {
    await setup(page, { exp: (sym) => ({ body: sym === "TCS" ? withAudit(DECL, "mixed", "the board-meeting notice names both audited and unaudited results") : UP }) });
    await page.goto(`${DESK}?tab=events`);
    await page.getByTestId("events-chip-dec").click();
    await expect(page.getByTestId("events-exp-audit-pat")).toContainText("MIXED · FILED", SLOW);
    await expect(page.getByTestId("events-exp-audit-basis-pat")).toHaveText("the board-meeting notice names both audited and unaudited results");
  });

  test("TC-E20 the backend's within_band wins over inferring from low/high", async ({ page }) => {
    // MOCK: profit 1,405 is above the stated high of 1,400, yet the backend says within_band true -> the UI says Inside
    const body = { ...DECL, metrics: DECL.metrics.map((m) => (m.key === "pat" ? { ...m, filed: { ...m.filed!, value: 1405 }, within_band: true } : m)) };
    await setup(page, { exp: (sym) => ({ body: sym === "TCS" ? body : UP }) });
    await page.goto(`${DESK}?tab=events`);
    await page.getByTestId("events-chip-dec").click();
    await expect(page.getByTestId("events-exp-vs-pat")).toContainText("Inside the baseline range", SLOW);
  });

  test("TC-E20b without within_band the position is read off low/high", async ({ page }) => {
    const body = { ...DECL, metrics: DECL.metrics.map((m) => (m.key === "pat" ? { ...m, filed: { ...m.filed!, value: 1100 }, within_band: null, vs_mid_pct: null } : m)) };
    await setup(page, { exp: (sym) => ({ body: sym === "TCS" ? body : UP }) });
    await page.goto(`${DESK}?tab=events`);
    await page.getByTestId("events-chip-dec").click();
    // 1,100 < low 1,200 -> below; vs_mid null -> computed from the two numbers: 1,100 / 1,300 - 1 = -15.4%
    await expect(page.getByTestId("events-exp-vs-pat")).toHaveText("Below the baseline range · −15.4% vs midpoint", SLOW);
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
    await expect(rows.first()).toContainText("2026-10-02 · ORDER · SOURCE NSE announcement (nidp.corporate_announcements)");
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
    await expect(page.getByTestId("events-exp-gaps")).toContainText("no analyst consensus is available (nidp.earnings_estimates is empty): this is a baseline, not a consensus", SLOW);
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

  test("TC-E21 404: no results meeting on file is said plainly", async ({ page }) => {
    await setup(page, { exp: () => ({ status: 404, body: { detail: "no results meeting for this symbol on that date" } }) });
    await page.goto(`${DESK}?tab=events`);
    await page.getByTestId("events-chip-up").click();
    await expect(page.getByTestId("events-exp-error")).toContainText("No results meeting is on file for this stock on that date", SLOW);
    await expect(page.getByTestId("events-history-n")).toBeVisible();
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
    await expect(page.getByTestId("events-sheet").getByTestId("events-exp-track-all-revenue")).toBeVisible();
    await page.screenshot({ path: "e2e/screenshots/desk-expectation/phone-sheet.png" });
    const over = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    expect(over).toBeLessThanOrEqual(0);
  });
});
