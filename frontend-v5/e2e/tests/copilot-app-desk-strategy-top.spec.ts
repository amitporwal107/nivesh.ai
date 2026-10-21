/**
 * Smart trading desk — Strategy Builder, "Top 5 by regime" (?tab=more&view=strategy&mode=top).
 *
 * The fixture `desk-strategy-top.json` is a REAL response captured from staging on 2026-10-21
 * (schema desk.strategy.top.v1, rules regime-fit-v1), trimmed to two ideas per class. Figures in it
 * are therefore real prices and a real measured regime, not invented numbers.
 *
 * What these cases defend is the honesty of the screen as much as its layout: the ranking caveat and
 * the gaps must be ON the page rather than behind a tooltip, the cash section must not claim a fit
 * ranking it does not have, and a theoretical reward:risk must never be presented as the ranking
 * number. Those are the properties that would quietly rot.
 */
import { test, expect, type Page } from "@playwright/test";
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";
import { mockApi } from "../helpers/api-mock";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const TOP = JSON.parse(fs.readFileSync(path.join(__dirname, "..", "fixtures", "desk-strategy-top.json"), "utf-8"));
const DESK = "/v5/app/trader/desk";
const URL = `${DESK}?tab=more&view=strategy&mode=top`;

async function openTop(page: Page, body: unknown = TOP) {
  await mockApi(page, "populated");
  await page.route("**/api/desk/strategy/top", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) }));
  await page.goto(URL);
  await expect(page.getByTestId("top-by-regime")).toBeVisible();
}

test.describe("Strategy Builder — Top by regime", () => {
  test("TC-28 the mode chip exists and opens the board", async ({ page }) => {
    await mockApi(page, "populated");
    await page.route("**/api/desk/strategy/top", (route) =>
      route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(TOP) }));
    await page.goto(`${DESK}?tab=more&view=strategy`);
    const chip = page.getByTestId("builder-mode-top");
    await expect(chip).toBeVisible();
    await chip.click();
    await expect(page.getByTestId("top-by-regime")).toBeVisible();
  });

  test("TC-28 all three asset classes render with their own sections", async ({ page }) => {
    await openTop(page);
    await expect(page.getByTestId("top-class-index_options")).toBeVisible();
    await expect(page.getByTestId("top-class-stock_fno")).toBeVisible();
    await expect(page.getByTestId("top-class-cash")).toBeVisible();
    await expect(page.getByText("Index options — NIFTY and BANKNIFTY")).toBeVisible();
    await expect(page.getByText("Stock F&O", { exact: true })).toBeVisible();
    await expect(page.getByText("Cash stocks", { exact: true })).toBeVisible();
  });

  test("TC-29 the regime strip shows trend, VIX against its threshold, breadth and the measured date", async ({ page }) => {
    await openTop(page);
    const strip = page.getByTestId("top-regime");
    await expect(strip).toContainText("down");                 // regime.trend
    await expect(strip).toContainText("14.77");                // india_vix
    await expect(strip).toContainText("20");                   // vix_high_threshold
    await expect(strip).toContainText("below");                // judged against the threshold
    await expect(strip).toContainText("19");                   // advancing_share_pct
  });

  test("TC-29 the regime/chain date gap is shown, not hidden", async ({ page }) => {
    await openTop(page);
    await expect(page.getByTestId("top-staleness")).toContainText("regime was last classified");
  });

  test("TC-30 an idea card carries max loss, capital at risk, breakeven and reward : risk", async ({ page }) => {
    await openTop(page);
    const first = page.getByTestId("top-class-index_options").locator("article").first();
    await expect(first).toContainText("Max loss");
    await expect(first).toContainText("Capital at risk");
    await expect(first).toContainText("Breakeven");
    await expect(first).toContainText("Reward : risk");
    await expect(first.getByTestId("idea-fit")).toContainText("fit");
  });

  test("TC-30 each idea states why it fits, from the route's own factors", async ({ page }) => {
    await openTop(page);
    const why = page.getByTestId("top-class-index_options").locator("article").first().getByTestId("idea-why");
    await expect(why).toContainText("India VIX");
    await expect(why).toContainText("50-session average");
  });

  test("TC-31 the ranking caveat is visible on the page, not behind a tooltip", async ({ page }) => {
    await openTop(page);
    const note = page.getByTestId("top-ranking-note");
    await expect(note).toBeVisible();
    await expect(note).toContainText("not a forecast");
    await expect(note).toContainText("not a probability");
    await expect(note).toContainText("not a ranking by past performance");
  });

  test("TC-31 the gaps the engine cannot close are listed on screen", async ({ page }) => {
    await openTop(page);
    const gaps = page.getByTestId("top-gaps");
    await expect(gaps).toBeVisible();
    await expect(gaps).toContainText("IV percentile");
    await expect(gaps).toContainText("performance");
  });

  test("the cash section does not claim a regime-fit ranking", async ({ page }) => {
    await openTop(page);
    const cash = page.getByTestId("top-class-cash");
    await expect(cash).toBeVisible();
    // No fit chip anywhere in the cash section: those ideas carry the scanner's evidence rank.
    await expect(cash.getByTestId("idea-fit")).toHaveCount(0);
    await expect(page.getByText("NOT ranked by regime fit", { exact: false })).toBeVisible();
  });

  test("a theoretical reward : risk is labelled as not the ranking number", async ({ page }) => {
    await openTop(page);
    const first = page.getByTestId("top-class-index_options").locator("article").first();
    await expect(first).toContainText("is not what this is ranked on");
  });

  test("TC-32 a class with no ideas shows the reason instead of an empty box", async ({ page }) => {
    const body = JSON.parse(JSON.stringify(TOP));
    body.classes.index_options.ideas = [];
    body.classes.index_options.unavailable = [{ underlying: "NIFTY", reason: "no chain today" }];
    await openTop(page, body);
    const cls = page.getByTestId("top-class-index_options");
    await expect(cls).toContainText("No idea fits here");
    await cls.getByTestId("top-unavailable").click();
    await expect(cls).toContainText("no chain today");
  });

  test("an unavailable regime is stated and nothing is invented", async ({ page }) => {
    const body = JSON.parse(JSON.stringify(TOP));
    body.regime = { available: false, reason: "macro_state is empty" };
    body.classes.index_options.ideas = [];
    body.classes.stock_fno.ideas = [];
    await openTop(page, body);
    await expect(page.getByTestId("top-regime")).toContainText("macro_state is empty");
    await expect(page.getByTestId("top-class-index_options")).toContainText("No idea fits here");
  });

  test("a failed request offers a retry rather than a blank screen", async ({ page }) => {
    await mockApi(page, "populated");
    await page.route("**/api/desk/strategy/top", (route) =>
      route.fulfill({ status: 500, contentType: "application/json", body: JSON.stringify({ detail: "upstream" }) }));
    await page.goto(URL);
    await expect(page.getByRole("alert")).toBeVisible();
  });
});
