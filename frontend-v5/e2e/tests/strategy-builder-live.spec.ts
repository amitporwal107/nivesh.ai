/**
 * @live — Strategy Builder wizard (V5) end-to-end on real staging.
 *
 * Drives the actual deployed screen at /v5/strategy-builder with a real session
 * cookie (SESSION_TOKEN → storageState). Walks Universe → Strategy → Screen →
 * Backtest and asserts real candidates + backtest metrics render. No mocking.
 */
import { test, expect } from "@playwright/test";

test.describe("@live Strategy Builder wizard", () => {
  test("walks universe → strategy → screen → backtest with real data", async ({ page }) => {
    // 1) Load the deployed wizard (V5 is served under /v5/)
    await page.goto("/v5/strategy-builder", { waitUntil: "domcontentloaded" });
    await expect(page.getByTestId("strategy-builder-page")).toBeVisible({ timeout: 20_000 });
    await expect(page.getByRole("heading", { name: "Strategy Builder" })).toBeVisible();

    // 2) Universe — Nifty 500 (default) is selectable; advance
    await page.getByTestId("universe-NIFTY500").click();
    await page.getByRole("button", { name: /Strategy →/ }).click();

    // 3) Strategy — pick a template that reliably returns candidates in the
    // current market (the strict templates can legitimately match 0 stocks).
    const template = page.locator('button', { hasText: "Simple Momentum" });
    await expect(template).toBeVisible({ timeout: 15_000 });
    await template.click();
    await page.getByRole("button", { name: /Screen →/ }).click();

    // 4) Screen — run against live data; expect a non-empty ranked candidate list
    await page.getByTestId("run-screen").click();
    const screenResults = page.getByTestId("screen-results");
    await expect(screenResults).toBeVisible({ timeout: 30_000 });
    const candidateRows = screenResults.locator("tbody tr");
    await expect.poll(() => candidateRows.count(), { timeout: 30_000 }).toBeGreaterThan(0);

    // 5) Backtest — run a short window; expect metrics + trades to render
    await page.getByRole("button", { name: /Backtest →/ }).click();
    await page.getByTestId("run-backtest").click();
    const backtest = page.getByTestId("backtest-results");
    await expect(backtest).toBeVisible({ timeout: 60_000 });
    // "Trades" metric card renders a number ≥ 0; total-return card present
    await expect(backtest.getByText("Total return")).toBeVisible();
    await expect(backtest.getByText("Trades")).toBeVisible();

    await page.screenshot({ path: "e2e/.artifacts/strategy-builder-backtest.png", fullPage: true });
  });
});
