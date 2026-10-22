/**
 * One-screen Copilot app (/v5/app) — Smart trading desk: the "Results today & tomorrow" board in the Events tab
 * (screens/tradingdesk/EventsTab.tsx ResultsBoard + events-data.ts useResultsBoard).
 *
 * MOCK — not real data: every route below is answered with an inline payload in the contract's shape
 * (GET /api/markets/events-calendar, .../history, .../expectation, .../expectations) with synthetic values.
 * Expected figures are worked out from the payload. Mocked APIs, production build — see pw.copilot-app.config.ts.
 * The clock is fixed at Wed 21 Oct 2026, 11:30 IST.
 */
import { test, expect, type Page, type Route } from "@playwright/test";
import { mockApi } from "../helpers/api-mock";

const DESK = "/v5/app/trader/desk";
const SLOW = { timeout: 15_000 };
const json = (route: Route, body: unknown, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
const id = (d: string, s: string) => `${d}|${s}|RESULTS|mtg`;

// MOCK — not real data
const cev = (date: string, symbol: string, sector: string) => ({
  id: id(date, symbol), date, symbol, name: `${symbol} Ltd (mock)`, sector, type: "RESULTS", timing: "post", detail: "Results for Q2 FY2027",
  universe: { n50: true, fno: true }, source: "NSE", announced_at: null,
});
const CAL = {
  month: "2026-10", as_of: "2026-10-20",
  events: [cev("2026-10-21", "DECL", "IT"), cev("2026-10-21", "PEND", "IT"), cev("2026-10-21", "AWT1", "Banks"), cev("2026-10-22", "AWT2", "Banks")],
  holidays: [], index_closes: [], gaps: [],
};
const HIST = { symbol: "DECL", type: "RESULTS", coverage_from: "2025-10-01", n: 0, basis: "mock", occurrences: [], stats: { event_day: {}, d1: {}, w1: {} } };

// MOCK — not real data. Shape = the batch route's (desk_expectation.py compact_event / results_expectations).
const rng = (low: number, mid: number, high: number) => ({ low, mid, high });
const met = (key: string, unit: string, expected: unknown, filed: unknown = null, extra: Record<string, unknown> = {}) => ({
  key, unit, expected, same_quarter_last_year: null, previous_quarter: null, trend_yoy_pct: null, filed, vs_mid_pct: null, within_band: null,
  reliable: expected != null, note: null, last_year_note: null, ...extra,
});
const base = (date: string, symbol: string, sector: string, filed_state: string | null, metrics: unknown[], extra: Record<string, unknown> = {}) => ({
  id: id(date, symbol), symbol, name: `${symbol} Ltd (mock)`, sector, event_date: date, status: filed_state ? "declared" : "upcoming", filed_state,
  filing: null, period_label: "Q2 FY2027", basis: "standalone", audit_status: null, audit_basis: null, compared_with: null, expected_as_of: "2026-10-20",
  universe: { n50: true, fno: true }, metrics, gaps: [], ...extra,
});
const BY_REV = { n: 19000, median_abs_err_pct: 10.3, naive_flat_median_abs_err_pct: 18.2, within_band_pct: 81.3, within_band_n: 9400, latest_quarter: null };
const BOARD = {
  from: "2026-10-21", to: "2026-10-22", universe: "fno", as_of: "2026-10-21", count: 4,
  counts: { declared_figures: 1, declared_pending: 1, upcoming: 2 },
  label: "A baseline from the company's own published quarters, not an analyst consensus and not a forecast.",
  events: [
    base("2026-10-21", "DECL", "IT", "figures", [
      met("revenue", "cr", rng(1000, 1100, 1200), { value: 1250, broadcast_at: "2026-10-21T15:40:00+05:30", audit_status: null }, { vs_mid_pct: 13.6, within_band: false }),
      met("pat", "cr", rng(100, 120, 140), { value: 125, broadcast_at: "2026-10-21T15:40:00+05:30", audit_status: null }, { vs_mid_pct: 4.2, within_band: true }),
    ], { compared_with: "vs Nivesh baseline, not vs consensus", audit_status: "Unaudited", audit_basis: "Read from the board-meeting notice (mock)" }),
    base("2026-10-21", "PEND", "IT", "pending", [met("revenue", "cr", rng(500, 540, 580))],
      { filing: { filed_at: "2026-10-21T16:05:00+05:30", subject: "Outcome of Board Meeting", url: "https://www.nseindia.com/mock-outcome" } }),
    base("2026-10-21", "AWT1", "Banks", null, [met("revenue", "cr", rng(2000, 2200, 2400)), met("pat", "cr", null, null, { note: "Profit is near zero in the base quarter (mock)." })]),
    base("2026-10-22", "AWT2", "Banks", null, [met("revenue", "cr", rng(300, 330, 360))]),
  ],
  method: { by_metric: { revenue: BY_REV } }, sources: {}, gaps: ["Stored quarterly figures reach us about a day after the filing (mock gap)"],
};
const PEND_SINGLE = {
  symbol: "PEND", event_date: "2026-10-21", period_end: "2026-09-30", period_label: "Q2 FY2027", basis: "standalone", status: "declared", filed_state: "pending",
  filing: BOARD.events[1].filing, label: BOARD.label, compared_with: null, audit_status: null, audit_basis: null, expected_as_of: "2026-10-20", sources: {},
  metrics: [met("revenue", "cr", rng(500, 540, 580))], method: { name: "Same quarter last year × recent growth", formula: "mock", n_quarters: 6, by_metric: { revenue: BY_REV } }, evidence: [], gaps: [],
};

async function setup(page: Page, opts: { board?: unknown; boardStatus?: number; urls?: string[] } = {}) {
  await mockApi(page, "populated");
  await page.clock.setFixedTime(new Date("2026-10-21T06:00:00Z"));
  await page.route("**/api/markets/events-calendar/history*", (r) => json(r, HIST));
  await page.route("**/api/markets/events-calendar/expectation?*", (r) => json(r, PEND_SINGLE));
  await page.route("**/api/markets/events-calendar/expectations*", (r) => {
    opts.urls?.push(r.request().url());
    return opts.boardStatus && opts.boardStatus >= 400 ? json(r, { detail: "upstream_unavailable" }, opts.boardStatus) : json(r, opts.board ?? BOARD);
  });
  await page.route("**/api/markets/events-calendar?*", (r) => json(r, CAL));
  await page.route("**/api/markets/macro-calendar*", (r) => json(r, { month: "2026-10", as_of: "2026-10-20", events: [], holidays: [], index_closes: [], gaps: [], countries: [] }));
}

test.describe("Desk — Results today & tomorrow (desktop)", () => {
  test.use({ viewport: { width: 1440, height: 1000 } });

  test("TC-17/18/19/23 rows, filed vs range, pending without a number, order, wording", async ({ page }) => {
    const urls: string[] = [];
    await setup(page, { urls });
    await page.goto(`${DESK}?tab=events`);
    const board = page.getByTestId("events-board");
    await expect(board).toBeVisible(SLOW);
    // TC-24: one request, today to tomorrow, universe follows the filter
    expect(urls).toHaveLength(1);
    expect(urls[0]).toContain("from=2026-10-21");
    expect(urls[0]).toContain("to=2026-10-22");
    expect(urls[0]).toContain("universe=fno");
    await expect(page.getByTestId("events-board-label")).toContainText("NOT A CONSENSUS · NOT A FORECAST");
    await expect(page.getByTestId("events-board-counts")).toContainText("1 DECLARED · 1 FILED, FIGURES PENDING · 2 AWAITED");
    // declared row: expected range and the filed value, with the position worked out from the payload
    await expect(page.getByTestId("events-board-state-DECL")).toHaveText("DECLARED");
    await expect(page.getByTestId("events-board-expected-DECL-revenue")).toContainText("1,000");
    await expect(page.getByTestId("events-board-filed-DECL-revenue")).toContainText("1,250");
    await expect(page.getByTestId("events-board-place-DECL-revenue")).toContainText("above the range");
    await expect(page.getByTestId("events-board-place-DECL-revenue")).toContainText("+13.6% vs midpoint");
    await expect(page.getByTestId("events-board-place-DECL-pat")).toContainText("inside the range");
    await expect(page.getByTestId("events-board-row-DECL")).toContainText("VS NIVESH BASELINE, NOT VS CONSENSUS");
    await expect(page.getByTestId("events-board-row-DECL")).toContainText("UNAUDITED");
    // pending row: says so, shows the range, and no filed figure
    await expect(page.getByTestId("events-board-state-PEND")).toContainText("FILED · FIGURES PENDING");
    await expect(page.getByTestId("events-board-pending-PEND")).toContainText("not loaded yet");
    await expect(page.getByTestId("events-board-pending-PEND")).toContainText("2026-10-21 16:05 IST");
    await expect(page.getByTestId("events-board-expected-PEND-revenue")).toContainText("500");
    await expect(page.getByTestId("events-board-filed-PEND-revenue")).toHaveCount(0);
    // awaited rows; an unreliable metric shows no range
    await expect(page.getByTestId("events-board-state-AWT1")).toHaveText("AWAITED");
    await expect(page.getByTestId("events-board-expected-AWT1-pat")).toContainText("no reliable range");
    await expect(page.getByTestId("events-board-filed-AWT1-revenue")).toHaveCount(0);
    // days and order
    await expect(page.getByTestId("events-board-day-today")).toContainText("TODAY · WED 21 OCT · 3 RESULTS");
    await expect(page.getByTestId("events-board-day-tomorrow")).toContainText("TOMORROW · THU 22 OCT · 1 RESULT");
    const order = await page.getByTestId("events-board-day-today").locator("[data-state]").evaluateAll((els) => els.map((e) => e.getAttribute("data-state")));
    expect(order).toEqual(["figures", "pending", "awaited"]);
    // track record and gaps
    await expect(page.getByTestId("events-board-track")).toContainText("revenue from operations median miss 10.3%, inside the range 81% of the time");
    await expect(page.getByTestId("events-board-gaps")).toContainText("about a day after the filing");
    // TC-23: no verdict wording anywhere in the board
    const text = (await board.innerText()).toLowerCase();
    for (const w of ["beat", "bullish", "bearish", "outperform", "underperform"]) expect(text).not.toContain(w);
    expect(text).not.toMatch(/\bmissed\b/);
    await page.screenshot({ path: "e2e/screenshots/desk-results-today/desktop-board.png", fullPage: true });
  });

  test("TC-20 the board follows the sector filter and the search", async ({ page }) => {
    await setup(page);
    await page.goto(`${DESK}?tab=events`);
    await expect(page.getByTestId("events-board")).toBeVisible(SLOW);
    await page.getByTestId("events-search").fill("awt2");
    await expect(page.getByTestId("events-board-row-AWT2")).toBeVisible();
    await expect(page.getByTestId("events-board-row-DECL")).toHaveCount(0);
    await page.getByTestId("events-search").fill("");
    await page.getByTestId("events-sector").click();
    await page.getByTestId("events-sector-Banks").click();
    await expect(page.getByTestId("events-board-row-AWT1")).toBeVisible();
    await expect(page.getByTestId("events-board-row-DECL")).toHaveCount(0);
  });

  test("TC-20b universe switch re-requests the board with the new universe", async ({ page }) => {
    const urls: string[] = [];
    await setup(page, { urls });
    await page.goto(`${DESK}?tab=events`);
    await expect(page.getByTestId("events-board")).toBeVisible(SLOW);
    await page.getByRole("button", { name: "ALL NSE" }).click();
    await expect.poll(() => urls.some((u) => u.includes("universe=all"))).toBe(true);
  });

  test("TC-21 a row opens the event panel; a pending result says figures are not loaded", async ({ page }) => {
    await setup(page);
    await page.goto(`${DESK}?tab=events`);
    await expect(page.getByTestId("events-board")).toBeVisible(SLOW);
    await page.getByTestId("events-board-open-PEND").click();
    const panel = page.getByTestId("events-panel");
    await expect(panel).toContainText("PEND Ltd (mock)", SLOW);
    await expect(page.getByTestId("events-exp-heading")).toContainText("FILED · FIGURES NOT LOADED YET");
    await expect(page.getByTestId("events-exp-pending")).toContainText("not loaded yet");
  });

  test("TC-22 hidden in macro mode and when nothing reports today or tomorrow", async ({ page }) => {
    await setup(page);
    await page.goto(`${DESK}?tab=events`);
    await expect(page.getByTestId("events-board")).toBeVisible(SLOW);
    await page.getByRole("button", { name: /^MACRO/ }).click();
    await expect(page.getByTestId("events-board")).toHaveCount(0);
    await page.getByRole("button", { name: /^STOCK EVENTS/ }).click();
    await expect(page.getByTestId("events-board")).toBeVisible();

    const p2 = await page.context().newPage();
    await setup(p2, { board: { ...BOARD, count: 0, counts: { declared_figures: 0, declared_pending: 0, upcoming: 0 }, events: [] } });
    await p2.goto(`${DESK}?tab=events`);
    await expect(p2.getByTestId("desk-events")).toBeVisible(SLOW);
    await expect(p2.getByTestId("events-board")).toHaveCount(0);
  });

  test("TC-24 a failed request shows an error with retry; a malformed payload shows no numbers", async ({ page }) => {
    await setup(page, { boardStatus: 502 });
    await page.goto(`${DESK}?tab=events`);
    await expect(page.getByText("Results for today and tomorrow could not be loaded")).toBeVisible(SLOW);
    await expect(page.getByTestId("events-board")).toHaveCount(0);

    const p2 = await page.context().newPage();
    await setup(p2, { board: { from: "2026-10-21", events: "not-a-list" } });
    await p2.goto(`${DESK}?tab=events`);
    await expect(p2.getByText("Results for today and tomorrow could not be loaded")).toBeVisible(SLOW);
    await expect(p2.getByTestId("events-board-filed-DECL-revenue")).toHaveCount(0);
  });
});

test.describe("Desk — Results today & tomorrow (phone)", () => {
  test.use({ viewport: { width: 390, height: 844 } });

  test("TC-25 cards fit the phone with no sideways scroll; a row opens the sheet", async ({ page }) => {
    await setup(page);
    await page.goto(`${DESK}?tab=events`);
    await expect(page.getByTestId("events-board")).toBeVisible(SLOW);
    await expect(page.getByTestId("events-board-filed-DECL-revenue")).toContainText("1,250");
    const over = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    expect(over).toBeLessThanOrEqual(0);
    await page.screenshot({ path: "e2e/screenshots/desk-results-today/phone-board.png", fullPage: true });
    await page.getByTestId("events-board-open-PEND").click();
    await expect(page.getByTestId("events-sheet")).toContainText("PEND Ltd (mock)", SLOW);
    await expect(page.getByTestId("events-exp-heading")).toContainText("FILED · FIGURES NOT LOADED YET");
    await page.screenshot({ path: "e2e/screenshots/desk-results-today/phone-sheet-pending.png" });
  });
});
