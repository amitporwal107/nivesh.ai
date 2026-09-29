/**
 * Research -> Paper -> one trade: the swing chart (TC-PC1..TC-PC9).
 *
 * MOCK -- not real data: every /api/paper-trades response is a fixture (e2e/fixtures/paper-*.json).
 * Trade 532 is MPSLTD, entry 2627.25, stop 2417.07, T1 2758.6125, T2 2889.975, six daily observations.
 *
 * The chart draws to a <canvas> (lightweight-charts), so nothing about the pixels is assertable here.
 * Every assertion below targets the chart's TEXT ALTERNATIVE instead -- the level list the component
 * renders for screen readers. That is not a testing workaround: a canvas with no text alternative is
 * unreadable to assistive tech, so the thing that makes the chart accessible is the same thing that
 * makes it verifiable.
 */
import { test, expect, type Page } from "@playwright/test";
import fs from "fs";
import path from "path";
import { mockAuthAs } from "../helpers/api-mock";

const FX = path.join(process.cwd(), "e2e", "fixtures");
const load = (name: string) => JSON.parse(fs.readFileSync(path.join(FX, name), "utf-8"));
const has = (name: string) => fs.existsSync(path.join(FX, name));
const BANNED = /\b(buy|sell|recommend(ed|ation)?|multibagger|top pick|sure[- ]shot|guaranteed)\b/i;

const TRADE = load("paper-trade-532.json").data as {
  symbol: string; entry_price: number; stop_loss_price: number;
  target_1_price: number; target_2_price: number;
  observations: Array<{ session_date: string; open_price: number; high_price: number;
                        low_price: number; close_price: number;
                        stop_hit: boolean | null; target_hit: boolean | null }>;
};

async function mockPaper(page: Page, tradeOver?: (id: string) => unknown | null) {
  await page.route("**/api/paper-trades/**", (route) => {
    const u = new URL(route.request().url());
    const reply = (status: number, body: unknown) =>
      route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
    const q = (k: string) => u.searchParams.get(k);
    if (u.pathname.endsWith("/portfolio")) {
      const base = `paper-portfolio-${q("sample") ?? "forward"}-${q("portfolio") ?? "P5-NEXT"}`;
      const d = q("prediction_date");
      if (d && has(`${base}-${d}.json`)) return reply(200, load(`${base}-${d}.json`));
      return has(`${base}.json`) ? reply(200, load(`${base}.json`)) : reply(404, { detail: "not_found" });
    }
    if (u.pathname.endsWith("/evaluation")) {
      const f = `paper-evaluation-${q("sample")}-${q("portfolio")}.json`;
      return reply(200, has(f) ? load(f) : { data: { status: "none" } });
    }
    if (u.pathname.endsWith("/live")) {
      const f = `paper-live-${q("portfolio")}.json`;
      return reply(200, has(f) ? load(f) : { data: { status: "empty", positions: [] } });
    }
    const m = u.pathname.match(/\/trades\/(\d+)$/);
    if (m) {
      const o = tradeOver?.(m[1]);
      if (o) return reply(200, o);
      return has(`paper-trade-${m[1]}.json`) ? reply(200, load(`paper-trade-${m[1]}.json`))
                                             : reply(404, { detail: "not_found" });
    }
    return reply(404, { detail: "not_found" });
  });
}

async function openTrade532(page: Page) {
  await page.goto("/v5/research");
  await page.getByTestId("rail-paper").click();
  await expect(page.getByTestId("paper-screen")).toBeVisible();
  await page.getByTestId("pt-sample-replay").click();
  await page.getByTestId("pt-date").selectOption("2025-03-10");
  await page.getByTestId("pt-open-MPSLTD").click();
  await expect(page.getByTestId("pt-trade-symbol")).toHaveText("MPSLTD");
}

test.describe("Paper — swing chart", () => {
  test.use({ viewport: { width: 1280, height: 900 } });

  test.beforeEach(async ({ page }) => {
    await mockAuthAs(page, "user-profile-move-odds.json");
    await mockPaper(page);
  });

  test("TC-PC1 one candle per recorded session", async ({ page }) => {
    await openTrade532(page);
    const chart = page.getByTestId("pt-swing-chart");
    await expect(chart).toBeVisible();
    await expect(chart).toHaveAttribute("data-bars", String(TRADE.observations.length));
  });

  test("TC-PC2 all three legs are drawn, each with its price", async ({ page }) => {
    await openTrade532(page);
    // the page formats every price through paperMath.price() -- assert what a reader sees
    const money = (x: number) =>
      `₹${x.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
    for (const [leg, value] of [
      ["entry", TRADE.entry_price], ["stop", TRADE.stop_loss_price],
      ["t1", TRADE.target_1_price], ["t2", TRADE.target_2_price],
    ] as const) {
      const row = page.getByTestId(`pt-swing-level-${leg}`);
      await expect(row).toBeVisible();
      await expect(row).toContainText(money(value));
    }
  });

  test("TC-PC3 the stop is below entry and both targets above, in order", async ({ page }) => {
    await openTrade532(page);
    expect(TRADE.stop_loss_price).toBeLessThan(TRADE.entry_price);
    expect(TRADE.entry_price).toBeLessThan(TRADE.target_1_price);
    expect(TRADE.target_1_price).toBeLessThan(TRADE.target_2_price);
    await expect(page.getByTestId("pt-swing-risk")).toContainText("8.0%");
  });

  test("TC-PC4 the canvas has a text alternative naming the symbol and the legs", async ({ page }) => {
    await openTrade532(page);
    const label = await page.getByTestId("pt-swing-chart").getAttribute("aria-label");
    expect(label).toBeTruthy();
    for (const word of ["MPSLTD", "entry", "stop", "target"]) {
      expect(label!.toLowerCase()).toContain(word.toLowerCase());
    }
  });

  test("TC-PC5 a session that touched a level is marked", async ({ page }) => {
    await openTrade532(page);
    const touched = TRADE.observations.filter((o) => o.stop_hit || o.target_hit).length;
    await expect(page.getByTestId("pt-swing-chart")).toHaveAttribute("data-marks", String(touched));
  });

  test("TC-PC6 a trade with no sessions yet says so instead of drawing an empty chart", async ({ page }) => {
    await mockPaper(page, (id) =>
      id === "532" ? { data: { ...TRADE, observations: [] } } : null);
    await openTrade532(page);
    await expect(page.getByTestId("pt-swing-empty")).toBeVisible();
    await expect(page.getByTestId("pt-swing-chart")).toHaveCount(0);
  });

  test("TC-PC7 the existing path table is untouched", async ({ page }) => {
    await openTrade532(page);
    await expect(page.getByTestId("pt-path")).toBeVisible();
    await expect(page.getByTestId("pt-path-0")).toBeVisible();
  });

  test("TC-PC8 no value leaks and no advice language", async ({ page }) => {
    await openTrade532(page);
    const t = await page.getByTestId("paper-screen").innerText();
    expect(t).not.toMatch(/NaN|undefined|\[object Object\]|Infinity/);
    const disc = await page.getByTestId("pt-disclaimer").innerText();
    expect(t.replace(disc, "")).not.toMatch(BANNED);
  });

  test("TC-PC9 a missing level degrades instead of drawing a wrong line", async ({ page }) => {
    await mockPaper(page, (id) =>
      id === "532" ? { data: { ...TRADE, target_2_price: null } } : null);
    await openTrade532(page);
    await expect(page.getByTestId("pt-swing-level-t2")).toHaveCount(0);
    await expect(page.getByTestId("pt-swing-level-entry")).toBeVisible();
  });
});
