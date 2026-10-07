/**
 * Research → Charts with a trade's levels on it (TC-TL1..TC-TL7).
 *
 * MOCK — not real data: every /api/research/chart* response is a fixture. The point of these tests is
 * the LEVEL layer and the deep link, not the price data.
 *
 * The chart is a <canvas>, so the levels cannot be read from the DOM. ChartCanvas already publishes
 * `data-rendered-levels` and `data-level-tags` for exactly this reason; this adds `data-trade-levels`.
 * Those attributes are the assertion surface.
 */
import { test, expect, type Page } from "@playwright/test";
import fs from "fs";
import path from "path";
import { mockAuthAs } from "../helpers/api-mock";

const FX = path.join(process.cwd(), "e2e", "fixtures");
const load = (n: string) => JSON.parse(fs.readFileSync(path.join(FX, n), "utf-8"));
const has = (n: string) => fs.existsSync(path.join(FX, n));

const LIVE_CALLS: string[] = [];

async function mockCharts(page: Page, opts?: { snapshotHas?: (sym: string) => boolean }) {
  const snapshotHas = opts?.snapshotHas ?? ((s: string) => has(`research-chart-ohlcv-${s}.json`));
  const ok = (route: import("@playwright/test").Route, body: unknown) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
  const nf = (route: import("@playwright/test").Route) =>
    route.fulfill({ status: 404, contentType: "application/json", body: JSON.stringify({ detail: "unknown_symbol" }) });

  await page.route("**/api/research/chart/run", (r) => ok(r, load("research-chart-run.json")));
  await page.route("**/api/research/chart/symbols", (r) => ok(r, load("research-chart-symbols.json")));
  await page.route("**/api/research/chart/catalogue", (r) => ok(r, load("research-chart-catalogue.json")));
  await page.route("**/api/research/chart/*/ohlcv*", (r) => {
    const sym = decodeURIComponent(new URL(r.request().url()).pathname.split("/").slice(-2, -1)[0]);
    return snapshotHas(sym) ? ok(r, load(`research-chart-ohlcv-${sym}.json`)) : nf(r);
  });
  await page.route("**/api/research/chart-live/*/ohlcv*", (r) => {
    const u = new URL(r.request().url());
    const sym = decodeURIComponent(u.pathname.split("/").slice(-2, -1)[0]);
    LIVE_CALLS.push(sym);
    // the live route always answers 1D; reuse a fixture's bars so the shape is identical
    const base = load("research-chart-ohlcv-TCS.json");
    return ok(r, { ...base, symbol: sym, pit_status: "PIT_UNVERIFIED",
                   provenance: { ...(base.provenance ?? {}), source_mode: "live" } });
  });
  await page.route("**/api/research/chart/*/indicators*", (r) => {
    const sym = decodeURIComponent(new URL(r.request().url()).pathname.split("/").slice(-2, -1)[0]);
    return has(`research-chart-indicators-${sym}.json`)
      ? ok(r, load(`research-chart-indicators-${sym}.json`))
      : ok(r, { symbol: sym, timeframe: "1D", indicators: {} });
  });
  await page.route("**/api/research/chart/*/patterns", (r) => {
    const sym = decodeURIComponent(new URL(r.request().url()).pathname.split("/").slice(-2, -1)[0]);
    return has(`research-chart-patterns-${sym}.json`)
      ? ok(r, load(`research-chart-patterns-${sym}.json`))
      : ok(r, { symbol: sym, patterns: [] });
  });
  await page.route("**/api/research/drawings**", (r) => ok(r, load("research-chart-drawings-empty.json")));
  await page.route("**/api/research/chart-layouts**", (r) => ok(r, { data: [] }));
}

// Levels placed around the TCS fixture's own last close, so the test exercises a trade whose
// levels sit inside a plausible range rather than off the axis.
const L = { entry: 4109.4, stop: 3780.65, t1: 4314.87, t2: 4520.34 };
const url = (sym: string, lv: Partial<typeof L> = L) => {
  const q = new URLSearchParams({ screen: "charts", symbol: sym, trade: "532" });
  for (const [k, v] of Object.entries(lv)) if (v != null) q.set(k, String(v));
  return `/v5/research?${q.toString()}`;
};

async function canvas(page: Page) {
  const c = page.locator("[data-rendered-levels]").first();
  await expect(c).toBeVisible({ timeout: 15000 });
  return c;
}

test.describe("Charts — trade levels", () => {
  test.use({ viewport: { width: 1440, height: 900 } });

  test.beforeEach(async ({ page }) => {
    LIVE_CALLS.length = 0;
    await mockAuthAs(page, "user-profile-charting.json");
    await mockCharts(page);
  });

  test("TC-TL1 a ?screen=charts deep link lands on the workspace with that symbol", async ({ page }) => {
    await page.goto(url("TCS"));
    await expect(page.getByTestId("charts-screen")).toBeVisible();
    await expect(page.locator("body")).toContainText("TCS");
  });

  test("TC-TL2 all four trade levels are drawn on the chart", async ({ page }) => {
    await page.goto(url("TCS"));
    const c = await canvas(page);
    const drawn = await c.getAttribute("data-trade-levels");
    expect(drawn).toBeTruthy();
    for (const k of ["ENTRY", "STOP", "TARGET_1", "TARGET_2"]) expect(drawn!).toContain(k);
    for (const v of Object.values(L)) expect(drawn!).toContain(String(v));
  });

  test("TC-TL3 the price-axis tag lane carries the trade tags alongside S/R", async ({ page }) => {
    await page.goto(url("TCS"));
    const c = await canvas(page);
    const tags = await c.getAttribute("data-level-tags");
    for (const side of ["E", "SL", "T1", "T2"]) {
      expect(tags!.split("|").some((t) => t.startsWith(side))).toBeTruthy();
    }
  });

  test("TC-TL4 a level that was never set is not drawn at all", async ({ page }) => {
    await page.goto(url("TCS", { entry: L.entry, stop: L.stop }));   // no targets
    const c = await canvas(page);
    const drawn = await c.getAttribute("data-trade-levels");
    expect(drawn).toContain("ENTRY");
    expect(drawn).toContain("STOP");
    expect(drawn).not.toContain("TARGET_1");
    expect(drawn).not.toContain("TARGET_2");
  });

  test("TC-TL5 a zero or junk level is refused rather than drawn at the axis floor", async ({ page }) => {
    await page.goto(`/v5/research?screen=charts&symbol=TCS&entry=0&stop=abc&t1=${L.t1}`);
    const c = await canvas(page);
    const drawn = await c.getAttribute("data-trade-levels");
    expect(drawn).not.toContain("ENTRY");
    expect(drawn).not.toContain("STOP");
    expect(drawn).toContain("TARGET_1");
  });

  test("TC-TL6 a symbol outside the frozen snapshot falls back to the live source", async ({ page }) => {
    await mockCharts(page, { snapshotHas: () => false });
    await page.goto(url("PNCINFRA"));
    await canvas(page);
    expect(LIVE_CALLS).toContain("PNCINFRA");
  });

  test("TC-TL7 no value leaks into the rendered page", async ({ page }) => {
    await page.goto(url("TCS"));
    await canvas(page);
    const body = await page.locator("body").innerText();
    expect(body).not.toMatch(/NaN|undefined|\[object Object\]|Infinity/);
  });
});
