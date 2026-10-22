/**
 * One-screen Copilot app (/v5/app) — Smart trading desk: the Events calendar's MACRO view
 * (screens/tradingdesk/EventsTab.tsx + events-data.ts).
 *
 * MOCK — not real data: the routes below are answered with inline payloads in the contract's shape
 * (GET /api/markets/macro-calendar, .../history; the stock routes for the Stock switch) with synthetic
 * values. Expected figures are worked out from the payloads. Mocked APIs, production build — see
 * pw.copilot-app.config.ts. The clock is fixed at Wed 21 Oct 2026, 11:30 IST.
 */
import { test, expect, type Page, type Route } from "@playwright/test";
import { mockApi } from "../helpers/api-mock";

const DESK = "/v5/app/trader/desk";
const SLOW = { timeout: 15_000 };
const json = (route: Route, body: unknown, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });

// MOCK — not real data
const mev = (id: string, date: string, time: string | null, country: string, impact: string, name: string, short: string, extra: Record<string, unknown> = {}) => ({
  id, date, date_ist: date, time, time_basis: time ? "usual time" : null, country, impact, name, short, code: `${country}_${short}`, period: "Sep", previous: null, estimate: null, actual: null, unit: "%", source: "FRED (mock)", source_url: null, ...extra,
});
const EVENTS = [
  mev("m-in-cpi", "2026-10-12", "16:00", "IN", "H", "CPI inflation YoY", "CPI", { previous: "2.07", actual: "2.62" }),
  mev("m-us-cpi", "2026-10-14", "19:00", "US", "H", "CPI inflation YoY", "CPI", { previous: "2.9", actual: "3.1" }),
  mev("m-us-claims", "2026-10-22", "18:00", "US", "L", "Initial jobless claims", "Jobless claims", { period: "Week", previous: "224", unit: "K" }),
  mev("m-in-pmi", "2026-10-23", "10:30", "IN", "M", "HSBC Flash Manufacturing PMI", "Flash PMI", { period: "Oct", unit: "", previous: "58.6", estimate: "58.4", actual: "58.6" }),
  mev("m-us-fed", "2026-10-28", "23:30", "US", "H", "Fed interest rate decision", "Fed decision", { period: "Oct meeting", previous: "3.50" }),
  mev("m-us-gdp", "2026-10-28", "18:00", "US", "H", "GDP growth rate QoQ, advance", "GDP", { period: "Q3", previous: "3.3" }),
  mev("m-in-iip", "2026-10-28", "16:00", "IN", "M", "Industrial production YoY", "IIP", { previous: "4.1" }),
  mev("m-us-pce", "2026-10-28", "18:00", "US", "M", "Core PCE price index YoY", "Core PCE", { previous: "2.9" }),
];
const CAL = {
  month: "2026-10", as_of: "2026-10-20", events: EVENTS,
  holidays: [{ date: "2026-10-20", description: "Dussehra" }],
  index_closes: [{ date: "2026-10-12", pct: -1.12 }, { date: "2026-10-14", pct: 0.74 }, { date: "2026-10-15", pct: 0.31 }],
  gaps: ["release times are each agency's usual time (Nivesh's editorial), not read from the calendars", "consensus estimates are not shown: no free source publishes them, so every estimate is null"],
};
const HIST = {
  code: "US_CPI", country: "US", source: "FRED + NSE index (mock)", coverage_from: "2025-10-01", coverage_to: "2026-10-19", n: 4, basis: "Nifty 50 around past US CPI releases (mock basis line).",
  occurrences: [
    { date: "2026-09-11", period: "Aug", previous: "2.7", actual: "2.9", event_day_pct: 0.4, d1_pct: -0.2, w1_pct: 1.1 },
    { date: "2026-08-12", period: "Jul", previous: "2.6", actual: "2.7", event_day_pct: -0.3, d1_pct: 0.5, w1_pct: -0.4 },
    { date: "2026-07-14", period: "Jun", previous: "2.5", actual: "2.6", event_day_pct: 0.2, d1_pct: 0.1, w1_pct: 0.3 },
    { date: "2026-06-10", period: "May", previous: "2.4", actual: "2.5", event_day_pct: -0.1, d1_pct: 0.3, w1_pct: 0.9 },
  ],
  stats: { event_day: { avg: 0.1, min: -0.3, max: 0.4 }, d1: { avg: 0.2, min: -0.2, max: 0.5 }, w1: { avg: 0.5, min: -0.4, max: 1.1 } },
};
const STOCK_CAL = { month: "2026-10", as_of: "2026-10-20", events: [{ id: "s1", date: "2026-10-23", symbol: "TCS", name: "TCS Ltd (mock)", sector: "IT", type: "RESULTS", timing: "post", detail: "Results", universe: { n50: true, fno: true }, source: "NSE", announced_at: null }], holidays: [], index_closes: [], gaps: [] };

async function setup(page: Page, opts: { cal?: unknown; calStatus?: number; hist?: unknown; histStatus?: number; urls?: string[] } = {}) {
  await mockApi(page, "populated");
  await page.clock.setFixedTime(new Date("2026-10-21T06:00:00Z"));
  await page.route("**/api/markets/events-calendar/history*", (r) => json(r, { symbol: "TCS", type: "RESULTS", n: 0, occurrences: [], stats: {} }));
  await page.route("**/api/markets/events-calendar?*", (r) => json(r, STOCK_CAL));
  await page.route("**/api/markets/macro-calendar/history*", (r) => (opts.histStatus && opts.histStatus >= 400 ? json(r, { detail: "x" }, opts.histStatus) : json(r, opts.hist ?? HIST)));
  await page.route("**/api/markets/macro-calendar?*", (r) => {
    opts.urls?.push(r.request().url());
    if (opts.calStatus && opts.calStatus >= 400) return json(r, { detail: "upstream_unavailable" }, opts.calStatus);
    // like the real route, answer only the requested month
    const month = new URL(r.request().url()).searchParams.get("month") ?? "2026-10";
    const base = (opts.cal ?? CAL) as typeof CAL;
    return json(r, { ...base, month, events: base.events.filter((e) => e.date.startsWith(month)) });
  });
}
const openMacro = async (page: Page) => {
  await page.goto(`${DESK}?tab=events`);
  await expect(page.getByTestId("events-tab-macro")).toBeVisible(SLOW);
  await page.getByTestId("events-tab-macro").click();
};

test.describe("Desk — Events calendar, macro (desktop)", () => {
  test.use({ viewport: { width: 1440, height: 1000 } });

  test("M-1/M-2 switch count, headline, chips with short name + country, fold, tint, holiday, gaps", async ({ page }) => {
    await setup(page);
    await openMacro(page);
    await expect(page.getByTestId("events-tab-macro")).toContainText(String(EVENTS.length), SLOW);
    await expect(page.getByTestId("events-headline")).toContainText("2 high-impact releases before month-end");
    await expect(page.getByTestId("events-headline")).toContainText("US Fed decision 28 Oct");
    const chip = page.getByTestId("events-chip-m-us-cpi");
    await expect(chip).toContainText("CPI");
    await expect(chip).toContainText("US");
    await expect(page.getByTestId("events-cell-2026-10-28").locator('[data-testid^="events-chip-"]')).toHaveCount(2);
    await expect(page.getByTestId("events-viewall-2026-10-28")).toHaveText("VIEW ALL 4 →");
    await expect(page.getByTestId("events-meta-2026-10-14")).toHaveText("+0.74%");
    await expect(page.getByTestId("events-hol-2026-10-20")).toHaveText("Dussehra");
    await expect(page.getByTestId("events-gaps")).toContainText("usual time");
    await page.screenshot({ path: "e2e/screenshots/desk-events/macro-desktop-calendar.png", fullPage: true });
  });

  test("M-3 country and impact chips filter on the client; one request per month", async ({ page }) => {
    const urls: string[] = [];
    await setup(page, { urls });
    await openMacro(page);
    await expect(page.getByTestId("events-chip-m-us-cpi")).toBeVisible(SLOW);
    await expect(page.getByTestId("events-country-IN")).toContainText("3");
    await expect(page.getByTestId("events-country-US")).toContainText("5");
    await page.getByTestId("events-country-US").click();
    await expect(page.getByTestId("events-chip-m-us-cpi")).toHaveCount(0);
    await expect(page.getByTestId("events-chip-m-in-cpi")).toBeVisible();
    await expect(page.getByTestId("events-tab-macro")).toContainText("3");
    await page.getByTestId("events-country-US").click();
    await page.getByTestId("events-impact-H").click();
    await expect(page.getByTestId("events-chip-m-us-cpi")).toHaveCount(0);
    await expect(page.getByTestId("events-chip-m-us-claims")).toBeVisible();
    await page.getByTestId("events-search").fill("jobless");
    await expect(page.locator('[data-testid^="events-chip-"]')).toHaveCount(1);
    expect(urls.length).toBe(1);
    expect(urls[0]).toContain("country=IN%2CUS");
    expect(urls[0]).toContain("impact=H%2CM%2CL");
  });

  test("M-4/M-7 panel: previous/estimate/actual, no free-consensus note, no surprise, Nifty history", async ({ page }) => {
    await setup(page);
    await openMacro(page);
    await page.getByTestId("events-chip-m-us-cpi").click();
    const panel = page.getByTestId("events-panel");
    await expect(panel.getByTestId("events-detail-title")).toHaveText("CPI inflation YoY");
    await expect(panel.getByTestId("events-macro-previous")).toContainText("2.9%");
    await expect(panel.getByTestId("events-macro-estimate")).toContainText("—");
    await expect(panel.getByTestId("events-macro-estimate")).toContainText("NO FREE CONSENSUS SOURCE");
    await expect(panel.getByTestId("events-macro-actual")).toContainText("3.1%");
    await expect(panel.getByTestId("events-macro-surprise")).toHaveCount(0);
    await expect(panel.getByTestId("events-history-n")).toContainText("NIFTY 50 · CPI · BASED ON 4 OCCURRENCES SINCE 2025-10-01", SLOW);
    await expect(panel.getByTestId("events-history")).toContainText("+0.1%");
    await expect(panel.getByTestId("events-history")).toContainText("−0.3%");
    await expect(panel.getByTestId("events-history")).toContainText("+0.4%");
    await expect(panel.getByTestId("events-history")).toContainText("09-11 · Aug"); // past-release table label
    await expect(panel.getByTestId("events-history")).toContainText("2.9%");          // its ACTUAL column
    await expect(panel.getByTestId("events-history")).toContainText("1ST SESSION");
    await expect(panel.getByTestId("events-own-move")).toBeVisible();                 // 14 Oct 19:00 IST is after the close: the 15 Oct close (+0.31%) is its own move
    await expect(panel).toContainText("19:00 IST (usual time, not confirmed)");
    await expect(panel).toContainText("PAST BEHAVIOUR · NOT A FORECAST OR A SIGNAL");
    await page.screenshot({ path: "e2e/screenshots/desk-events/macro-desktop-panel.png" });
  });

  test("M-5 surprise tag only when estimate and actual both exist", async ({ page }) => {
    await setup(page);
    await openMacro(page);
    await page.getByTestId("events-chip-m-in-pmi").click();
    await expect(page.getByTestId("events-macro-estimate")).toContainText("58.4");
    await expect(page.getByTestId("events-macro-surprise")).toContainText("ABOVE ESTIMATE");
    await expect(page.getByTestId("events-macro-surprise")).toContainText("+0.2 vs estimate");
  });

  test("M-6 upcoming release: actual shows when it is due", async ({ page }) => {
    await setup(page);
    await openMacro(page);
    await page.getByTestId("events-chip-m-us-claims").click();
    await expect(page.getByTestId("events-macro-actual")).toContainText("—");
    await expect(page.getByTestId("events-macro-actual")).toContainText("DUE 22 OCT · 18:00");
    await expect(page.getByTestId("events-macro-previous")).toContainText("224K");
    await expect(page.getByTestId("events-own-move")).toHaveCount(0);
  });

  test("M-8 empty history says so; failed history offers retry", async ({ page }) => {
    await setup(page, { hist: { ...HIST, n: 0, occurrences: [], stats: {} } });
    await openMacro(page);
    await page.getByTestId("events-chip-m-us-cpi").click();
    await expect(page.getByTestId("events-history-empty")).toContainText("nothing to plot", SLOW);
    const p2 = await page.context().newPage();
    await setup(p2, { histStatus: 500 });
    await openMacro(p2);
    await p2.getByTestId("events-chip-m-us-cpi").click();
    await expect(p2.getByTestId("events-history-error")).toContainText("could not be loaded", { timeout: 25_000 });
  });

  test("M-9 India with no releases says why, in the API's words", async ({ page }) => {
    const noIn = { ...CAL, events: EVENTS.filter((e) => e.country === "US"), gaps: ["India: MoSPI and RBI release dates could not be read from their sites, so no India release is listed"] };
    await setup(page, { cal: noIn });
    await openMacro(page);
    await expect(page.getByTestId("events-chip-m-us-cpi")).toBeVisible(SLOW);
    await expect(page.getByTestId("events-country-gap")).toContainText("India: no releases listed");
    await expect(page.getByTestId("events-country-gap")).toContainText("MoSPI and RBI release dates could not be read");
    await expect(page.getByTestId("events-gaps")).toContainText("Data gap: India:");
  });

  test("M-10 macro failure: error with retry, no chips", async ({ page }) => {
    await setup(page, { calStatus: 502 });
    await openMacro(page);
    await expect(page.getByTestId("events-error")).toBeVisible({ timeout: 25_000 });
    await expect(page.locator('[data-testid^="events-chip-"]')).toHaveCount(0);
    await expect(page.getByTestId("events-retry")).toBeVisible();
    await expect(page.getByTestId("events-tab-macro")).toContainText("!");
  });

  test("M-11 timeline rows read time · name · country · period · figure and expand in place", async ({ page }) => {
    await setup(page);
    await openMacro(page);
    await page.getByTestId("events-view-tl").click();
    await expect(page.getByTestId("events-timeline")).toBeVisible(SLOW);
    const row = page.getByTestId("events-tl-row-m-us-claims");
    await expect(row).toContainText("18:00 IST");
    await expect(row).toContainText("Initial jobless claims");
    await expect(row).toContainText("United States · Week · previous 224K");
    await expect(row).toContainText("LOW IMPACT");
    await page.getByTestId("events-tl-toggle-m-us-claims").click();
    await expect(row.getByTestId("events-macro-previous")).toContainText("224K");
    await page.screenshot({ path: "e2e/screenshots/desk-events/macro-desktop-timeline.png", fullPage: true });
  });

  test("M-14 the IST date places the chip; no ring when the reaction session's close is not on file", async ({ page }) => {
    // MOCK — not real data: agency date 30 Oct, IST date 31 Oct. And a release on Mon 19 Oct 19:00 IST (after the close): its first
    // session is 20 Oct (a holiday), then 21 Oct (today, no close yet), so no close is on file and no ring is drawn.
    const late = { ...CAL, events: [
      mev("m-late", "2026-10-30", "23:30", "US", "H", "Fed interest rate decision", "Fed decision", { date_ist: "2026-10-31", period: "Oct meeting" }),
      mev("m-past19", "2026-10-19", "19:00", "US", "M", "Core PCE price index YoY", "Core PCE", { previous: "2.9", actual: "2.9" }),
    ], index_closes: [{ date: "2026-10-19", pct: 0.02 }] };
    await setup(page, { cal: late });
    await openMacro(page);
    await expect(page.getByTestId("events-cell-2026-10-31").getByTestId("events-chip-m-late")).toBeVisible(SLOW);
    await expect(page.getByTestId("events-cell-2026-10-30").locator('[data-testid^="events-chip-"]')).toHaveCount(0);
    await page.getByTestId("events-chip-m-late").click();
    await expect(page.getByTestId("events-panel")).toContainText("Sat 31 Oct 2026 · 23:30 IST");
    await page.getByTestId("events-panel-close").click();
    await page.getByTestId("events-chip-m-past19").click();
    await expect(page.getByTestId("events-history-n")).toBeVisible(SLOW);
    await expect(page.getByTestId("events-own-move")).toHaveCount(0);
  });

  test("M-13 stock switch still works after visiting macro", async ({ page }) => {
    await setup(page);
    await openMacro(page);
    await page.getByTestId("events-tab-stock").click();
    await expect(page.getByTestId("events-chip-s1")).toBeVisible(SLOW);
    await expect(page.getByTestId("events-type-RESULTS")).toBeVisible();
  });
});

test.describe("Desk — Events calendar, macro (phone)", () => {
  test.use({ viewport: { width: 390, height: 844 } });

  test("M-12 week strip dots, agenda rows, sheet with tiles, no sideways scroll", async ({ page }) => {
    await setup(page);
    await page.goto(`${DESK}?tab=events`);
    await expect(page.getByTestId("events-tab-macro")).toBeVisible(SLOW);
    await page.getByTestId("events-tab-macro").click();
    await page.getByTestId("events-m-next").click();           // week of 26 Oct
    await page.getByTestId("events-m-day-2026-10-28").click();
    await expect(page.getByTestId("events-m-count")).toHaveText("4 RELEASES");
    await expect(page.getByTestId("events-m-row-m-us-fed")).toContainText("Fed interest rate decision");
    await expect(page.getByTestId("events-m-row-m-us-fed")).toContainText("United States · Oct meeting");
    await page.getByTestId("events-m-row-m-us-gdp").click();
    const sheet = page.getByTestId("events-sheet");
    await expect(sheet).toBeVisible();
    await expect(sheet.getByTestId("events-macro-previous")).toContainText("3.3%");
    await expect(sheet.getByTestId("events-macro-estimate")).toContainText("NO FREE CONSENSUS SOURCE");
    await expect(sheet.getByTestId("events-macro-actual")).toContainText("DUE 28 OCT · 18:00");
    await expect(sheet).toContainText("PAST BEHAVIOUR · NOT A FORECAST OR A SIGNAL");
    await page.screenshot({ path: "e2e/screenshots/desk-events/macro-phone-sheet.png" });
    await page.getByTestId("events-sheet-close").click();
    await page.screenshot({ path: "e2e/screenshots/desk-events/macro-phone-agenda.png" });
    const over = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    expect(over).toBeLessThanOrEqual(0);
  });
});
