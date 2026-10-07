/**
 * Research Watchlist — public page at /watchlist on REAL staging (no auth).
 * TC-5/TC-6 in test_reports/research_watchlist_functionality.md. No mocks, no
 * login: a cold browser context hitting the live backend, same as a visitor
 * arriving from a direct link.
 */
import { test, expect } from "@playwright/test";

const UI = "https://staging.niveshcopilot.com/v5/watchlist";

test.describe("Research Watchlist public page", () => {
  // TC-5 — reachable with no session, no redirect to /login, all 41 cards render.
  test("TC-5 renders unauthenticated with all picks", async ({ page }) => {
    await page.goto(UI);
    await expect(page).not.toHaveURL(/\/login/);
    await expect(page.getByText(/Loading watchlist/i)).toHaveCount(0, { timeout: 15_000 });
    await expect(page.getByText(/41 of 41 picks shown/i)).toBeVisible();
    await expect(page.getByText("CUMMINSIND")).toBeVisible();
  });

  // TC-6 — tier filter chips change the visible card count.
  test("TC-6 tier filter narrows the visible cards", async ({ page }) => {
    await page.goto(UI);
    await expect(page.getByText(/41 of 41 picks shown/i)).toBeVisible({ timeout: 15_000 });
    await page.getByRole("button", { name: /^Speculative$/ }).click();
    const summary = page.getByText(/of 41 picks shown/i);
    await expect(summary).toBeVisible();
    const text = (await summary.textContent()) ?? "";
    const shown = Number(text.match(/(\d+) of 41/)?.[1] ?? "41");
    expect(shown).toBeLessThan(41);
  });
});
