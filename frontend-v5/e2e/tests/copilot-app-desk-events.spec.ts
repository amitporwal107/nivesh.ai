/**
 * One-screen Copilot app (/v5/app) — Smart trading desk: the Events calendar tab
 * (screens/tradingdesk/EventsTab.tsx + events-data.ts).
 *
 * MOCK — not real data: the two routes below are answered with inline payloads in the
 * contract's shape (GET /api/markets/events-calendar, .../history) with synthetic values.
 * Expected figures are worked out from the payload. Mocked APIs, production build — see
 * pw.copilot-app.config.ts. The clock is fixed at Wed 21 Oct 2026, 11:30 IST.
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
  events: [
    ev("e1", "2026-10-14", "TCS", "RESULTS"),
    ...["AAA", "BBB", "CCC", "DDD", "EEE"].map((s, i) => ev(`f${i}`, "2026-10-23", s, "RESULTS", { sector: i < 2 ? "Banks" : "IT" })),
    ev("d1", "2026-10-22", "INFY", "DIVIDEND", { timing: "ex" }),
    ev("n1", "2026-10-27", "XYZ", "BONUS", { timing: null, universe: { n50: false, fno: null } }),
  ],
  holidays: [{ date: "2026-10-20", description: "Dussehra" }],
  index_closes: [{ date: "2026-10-14", pct: 0.74 }, { date: "2026-10-12", pct: -1.12 }, { date: "2026-10-19", pct: 0.02 }],
  gaps: ["BSE-only announcements are not merged into this calendar"],
};
const HIST = {
  symbol: "TCS", type: "RESULTS", coverage_from: "2025-10-01", n: 3, basis: "TCS · last 3 results",
  occurrences: [
    { date: "2026-10-14", event_day_pct: 1.2, d1_pct: -0.4, w1_pct: 2.0 },
    { date: "2026-07-09", event_day_pct: -2.2, d1_pct: 0.6, w1_pct: -1.0 },
    { date: "2026-04-10", event_day_pct: 0.5, d1_pct: 0.1, w1_pct: 0.3 },
  ],
  stats: { event_day: { avg: -0.17, min: -2.2, max: 1.2 }, d1: { avg: 0.1, min: -0.4, max: 0.6 }, w1: { avg: 0.43, min: -1.0, max: 2.0 } },
};

async function setup(page: Page, opts: { calStatus?: number; hist?: unknown; urls?: string[] } = {}) {
  await mockApi(page, "populated");
  await page.clock.setFixedTime(new Date("2026-10-21T06:00:00Z"));
  await page.route("**/api/markets/events-calendar/history*", (r) => json(r, opts.hist ?? HIST));
  await page.route("**/api/markets/events-calendar?*", (r) => {
    opts.urls?.push(r.request().url());
    return opts.calStatus && opts.calStatus >= 400 ? json(r, { detail: "upstream_unavailable" }, opts.calStatus) : json(r, CAL);
  });
}

test.describe("Desk — Events calendar (desktop)", () => {
  test.use({ viewport: { width: 1440, height: 1000 } });

  test("TC-1 entry points: URL, More list, Intel button", async ({ page }) => {
    await setup(page);
    await page.goto(`${DESK}?tab=events`);
    await expect(page.getByTestId("desk-events")).toBeVisible(SLOW);
    // Desk redesign (2026-10-27): no More list; the Events calendar is a section of Market Desk › Market Intelligence, the Market Desk's first view.
    await page.goto(DESK);
    await page.getByTestId("desk-tab-market").click();
    await expect(page.getByTestId("desk-events")).toBeVisible(SLOW);
    await page.goto(`${DESK}?tab=intel`);
    await page.getByTestId("desk-intel-open-events").click();
    await expect(page.getByTestId("desk-events")).toBeVisible(SLOW);
  });

  test("TC-2/3/10 grid, fold, tints, holiday, gaps, headline", async ({ page }) => {
    await setup(page);
    await page.goto(`${DESK}?tab=events`);
    await expect(page.getByTestId("events-month")).toHaveText("October 2026", SLOW);
    // 5 events on 23 Oct -> 2 chips + VIEW ALL 5
    await expect(page.getByTestId("events-cell-2026-10-23").locator('[data-testid^="events-chip-"]')).toHaveCount(2);
    await expect(page.getByTestId("events-viewall-2026-10-23")).toHaveText("VIEW ALL 5 →");
    await expect(page.getByTestId("events-meta-2026-10-14")).toHaveText("+0.74%");
    await expect(page.getByTestId("events-meta-2026-10-12")).toHaveText("−1.12%");
    await expect(page.getByTestId("events-hol-2026-10-20")).toHaveText("Dussehra");
    await expect(page.getByTestId("events-cell-2026-10-21")).toHaveAttribute("data-today", "1");
    await expect(page.getByTestId("events-gaps")).toContainText("BSE-only announcements");
    // results still to come before month-end: 5 (23 Oct); the 14th is past
    await expect(page.getByTestId("events-headline")).toContainText("5 companies report results before month-end.");
    await page.screenshot({ path: "e2e/screenshots/desk-events/desktop-calendar.png", fullPage: true });
  });

  test("TC-4 day panel: search, open event, next/prev", async ({ page }) => {
    await setup(page);
    await page.goto(`${DESK}?tab=events`);
    await page.getByTestId("events-viewall-2026-10-23").click();
    await expect(page.getByTestId("events-panel")).toContainText("5 stock events");
    await page.getByTestId("events-panel-search").fill("ccc");
    await expect(page.locator('[data-testid^="events-day-row-"]')).toHaveCount(1);
    await page.getByTestId("events-panel-search").fill("");
    await page.getByTestId("events-day-row-f1").click();
    await expect(page.getByTestId("events-pos")).toHaveText("2 / 5");
    await page.getByTestId("events-next").click();
    await expect(page.getByTestId("events-pos")).toHaveText("3 / 5");
    await page.getByTestId("events-panel-back").click();
    await expect(page.getByTestId("events-panel")).toContainText("5 stock events");
  });

  test("TC-5 filters: type chip, universe param, sector", async ({ page }) => {
    const urls: string[] = [];
    await setup(page, { urls });
    await page.goto(`${DESK}?tab=events`);
    await expect(page.getByTestId("events-cell-2026-10-22").locator('[data-testid^="events-chip-"]')).toHaveCount(1, SLOW);
    await page.getByTestId("events-type-DIVIDEND").click();
    await expect(page.getByTestId("events-cell-2026-10-22").locator('[data-testid^="events-chip-"]')).toHaveCount(0);
    await page.getByTestId("events-universe-n50").click();
    await expect.poll(() => urls.some((u) => u.includes("universe=n50"))).toBe(true);
    await page.getByTestId("events-sector").click();
    await page.getByTestId("events-sector-Banks").click();
    await expect(page.getByTestId("events-viewall-2026-10-23")).toHaveCount(0); // only 2 Banks events remain
    await expect(page.getByTestId("events-cell-2026-10-23").locator('[data-testid^="events-chip-"]')).toHaveCount(2);
  });

  test("TC-6 history panel: figures, own-move ring, coverage line", async ({ page }) => {
    await setup(page);
    await page.goto(`${DESK}?tab=events`);
    await page.getByTestId("events-chip-e1").click();
    await expect(page.getByTestId("events-detail-title")).toHaveText("TCS Ltd (mock)");
    await expect(page.getByTestId("events-history-n")).toContainText("BASED ON 3 OCCURRENCES SINCE 2025-10-01", SLOW);
    const h = page.getByTestId("events-history");
    await expect(h).toContainText("−0.2%"); // avg −0.17 -> 1dp
    await expect(h).toContainText("−2.2%");
    await expect(h).toContainText("+2.0%");
    await expect(page.getByTestId("events-own-move")).toHaveCount(1); // event date 14 Oct is in the occurrences
    await expect(page.getByTestId("events-panel")).toContainText("PAST BEHAVIOUR · NOT A FORECAST OR A SIGNAL");
    await page.screenshot({ path: "e2e/screenshots/desk-events/desktop-panel.png", fullPage: true });
  });

  test("TC-7 empty history says so", async ({ page }) => {
    await setup(page, { hist: { ...HIST, n: 0, occurrences: [], stats: {} } });
    await page.goto(`${DESK}?tab=events`);
    await page.getByTestId("events-chip-e1").click();
    await expect(page.getByTestId("events-history-empty")).toContainText("nothing to plot", SLOW);
    await expect(page.getByTestId("events-own-move")).toHaveCount(0);
  });

  test("TC-8 calendar failure: error, no chips", async ({ page }) => {
    await setup(page, { calStatus: 502 });
    await page.goto(`${DESK}?tab=events`);
    await expect(page.getByTestId("events-error")).toBeVisible({ timeout: 25_000 });
    await expect(page.locator('[data-testid^="events-chip-"]')).toHaveCount(0);
    await expect(page.getByTestId("events-retry")).toBeVisible();
  });

  // TC-9 (macro switch, source pending) is superseded by the macro specs in copilot-app-desk-macro.spec.ts.

  test("TC-11 timeline expands a row in place", async ({ page }) => {
    await setup(page);
    await page.goto(`${DESK}?tab=events`);
    await page.getByTestId("events-view-tl").click();
    await expect(page.getByTestId("events-timeline")).toBeVisible(SLOW);
    // 14 Oct is before today: hidden until "show earlier"
    await expect(page.getByTestId("events-tl-row-e1")).toHaveCount(0);
    await page.getByTestId("events-earlier").click();
    await page.getByTestId("events-tl-toggle-e1").click();
    await expect(page.getByTestId("events-tl-row-e1").getByTestId("events-history-n")).toBeVisible(SLOW);
    await page.screenshot({ path: "e2e/screenshots/desk-events/desktop-timeline.png", fullPage: true });
  });
});

test.describe("Desk — Events calendar (phone)", () => {
  test.use({ viewport: { width: 390, height: 844 } });

  test("TC-12 week strip, agenda, sheet, no sideways scroll", async ({ page }) => {
    await setup(page);
    await page.goto(`${DESK}?tab=events`);
    await expect(page.getByTestId("events-m-day-2026-10-21")).toBeVisible(SLOW);
    await page.getByTestId("events-m-day-2026-10-23").click();
    await expect(page.getByTestId("events-m-count")).toHaveText("5 EVENTS");
    await page.getByTestId("events-m-row-f0").click();
    await expect(page.getByTestId("events-sheet")).toBeVisible();
    await expect(page.getByTestId("events-sheet")).toContainText("PAST BEHAVIOUR · NOT A FORECAST OR A SIGNAL");
    await page.screenshot({ path: "e2e/screenshots/desk-events/phone-sheet.png" });
    await page.getByTestId("events-sheet-close").click();
    await page.screenshot({ path: "e2e/screenshots/desk-events/phone-agenda.png" });
    const over = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    expect(over).toBeLessThanOrEqual(0);
  });
});
