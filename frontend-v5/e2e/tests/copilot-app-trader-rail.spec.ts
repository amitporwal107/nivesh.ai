/**
 * Copilot app (/v5/app) — Trader rail rows "Screener" and "Watchlists"
 * (docs/plans_20261031/SCREENER_WATCHLIST_PLAN.md slice W1; cases in test_reports/screener_watchlist_TESTCASES.md, RL-1 … RL-6).
 *
 * MOCK — not real data: every /api response comes from the shared mock API (helpers/api-mock "populated") or an inline payload.
 * Proves the rows, where they go, which row is lit, and that the other modes are unchanged. It does not prove the Screener or the
 * Watchlists page itself (copilot-app-screener.spec.ts, copilot-app-desk-market-desk.spec.ts, copilot-app-watchlist*.spec.ts).
 */
import { test, expect, type Page, type Route } from "@playwright/test";
import { mockApi, mockSingleRoute } from "../helpers/api-mock";

const APP = "/v5/app";
const DESK = `${APP}/trader/desk`;
const json = (route: Route, body: unknown, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });

async function api(page: Page) {
  await mockApi(page, "populated");
  await mockSingleRoute(page, "**/api/markets/home", "markets-home.json");
  await page.route("**/api/chat/sessions", (route) => json(route, []));
}

/** Trader mode, as the mode pill saves it (lib/store.ts: zustand persist "nivesh.copilot"). */
async function traderMode(page: Page) {
  await page.addInitScript(() => {
    try { window.localStorage.setItem("nivesh.copilot", JSON.stringify({ state: { mode: "trader" }, version: 0 })); } catch { /* blocked storage */ }
  });
}

const rail = (page: Page) => page.getByTestId("copilot-rail");
const row = (page: Page, name: string) => rail(page).getByRole("button", { name, exact: true });
const lit = (page: Page) => rail(page).locator('.cp-rail-row[aria-current="page"]');

test.describe("MOCK — not real data: Trader rail · Screener and Watchlists rows", () => {
  test("RL-1 Trader mode lists the Smart trading desk, Screener and Watchlists, in that order", async ({ page }) => {
    await api(page); await traderMode(page);
    await page.goto(DESK);
    const tools = rail(page).getByRole("button").filter({ hasText: /^(Smart trading desk|Screener|Watchlists)/ });
    await expect(tools).toHaveCount(3);
    await expect(tools.nth(0)).toContainText("Smart trading desk");
    await expect(tools.nth(1)).toHaveText("Screener");
    await expect(tools.nth(2)).toHaveText("Watchlists");
    // the 27 Oct decision still holds for these two
    for (const gone of ["Stock research", "Sector rotation"]) await expect(row(page, gone)).toHaveCount(0);
  });

  test("RL-2 Screener opens Market Desk › Screener and is the only lit row", async ({ page }) => {
    await api(page); await traderMode(page);
    await page.goto(DESK);
    await row(page, "Screener").click();
    await expect(page).toHaveURL(/\/v5\/app\/trader\/desk\?tab=market&view=screener/);
    await expect(page.getByTestId("desk-panel-screener")).toBeVisible();
    await expect(lit(page)).toHaveCount(1);
    await expect(row(page, "Screener")).toHaveAttribute("aria-current", "page");
    await expect(rail(page).getByRole("button", { name: /Smart trading desk/ })).not.toHaveAttribute("aria-current", "page");
  });

  test("RL-3 Watchlists opens Trade Desk › Watchlists and is the only lit row", async ({ page }) => {
    await api(page); await traderMode(page);
    await page.goto(DESK);
    await row(page, "Watchlists").click();
    await expect(page).toHaveURL(/\/v5\/app\/trader\/desk\?tab=trade&view=watchlists/);
    await expect(page.getByTestId("desk-panel-watchlists")).toBeVisible();
    await expect(lit(page)).toHaveCount(1);
    await expect(row(page, "Watchlists")).toHaveAttribute("aria-current", "page");
  });

  test("RL-4 on the desk's other places only the desk row is lit; going back to it lights it", async ({ page }) => {
    await api(page); await traderMode(page);
    await page.goto(`${DESK}?tab=risk&view=limits`);
    await expect(lit(page)).toHaveCount(1);
    await expect(rail(page).getByRole("button", { name: /Smart trading desk/ })).toHaveAttribute("aria-current", "page");
    await row(page, "Screener").click();
    await expect(row(page, "Screener")).toHaveAttribute("aria-current", "page");
    await rail(page).getByRole("button", { name: /Smart trading desk/ }).click();
    await expect(page).toHaveURL(/\/v5\/app\/trader\/desk$/);
    await expect(rail(page).getByRole("button", { name: /Smart trading desk/ })).toHaveAttribute("aria-current", "page");
    await expect(lit(page)).toHaveCount(1);
  });

  test("RL-5 the old routes still land on the same desk views, and Investor mode is unchanged", async ({ page }) => {
    await api(page); await traderMode(page);
    await page.goto(`${APP}/tool/screener`);
    await expect(page).toHaveURL(/\/v5\/app\/trader\/desk\?tab=market&view=screener/);
    await expect(row(page, "Screener")).toHaveAttribute("aria-current", "page");
    // Investor: its own Screener and "Watchlist & alerts" rows, no Watchlists row
    await page.addInitScript(() => {
      try { window.localStorage.setItem("nivesh.copilot", JSON.stringify({ state: { mode: "investor" }, version: 0 })); } catch { /* blocked storage */ }
    });
    await page.goto(APP);
    await expect(row(page, "Screener")).toBeVisible();
    await expect(row(page, "Watchlist & alerts")).toBeVisible();
    await expect(row(page, "Watchlists")).toHaveCount(0);
    await row(page, "Screener").click();
    await expect(page).toHaveURL(/\/v5\/app\/tool\/screener$/);
    await expect(row(page, "Screener")).toHaveAttribute("aria-current", "page");
  });

  test("RL-6 phone 390px: the drawer shows both rows and closes when one is pressed", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 800 });
    await api(page); await traderMode(page);
    await page.goto(DESK);
    await page.getByTestId("menu-button").click();
    await expect(row(page, "Screener")).toBeVisible();
    await expect(row(page, "Watchlists")).toBeVisible();
    await row(page, "Watchlists").click();
    await expect(page).toHaveURL(/\/v5\/app\/trader\/desk\?tab=trade&view=watchlists/);
    await expect(page.getByTestId("copilot-rail")).toHaveCount(0);
  });
});
