/**
 * Homepage — /v5/
 * Tests the public landing page (no auth required).
 */
import { test, expect } from "@playwright/test";

test.describe("Homepage", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/v5/");
  });

  test("renders hero headline from prototype", async ({ page }) => {
    const h1 = page.getByRole("heading", { level: 1 });
    await expect(h1).toContainText("Your portfolio");
    await expect(h1).toContainText("finally");
    await expect(h1).toContainText("legible");
  });

  test("renders nav bar with brand and CTA", async ({ page }) => {
    await expect(page.locator(".nvx-mark").first()).toBeVisible();
    await expect(page.getByText("Nivesh", { exact: true }).first()).toBeVisible();
    await expect(page.getByRole("button", { name: /Check my portfolio/i }).first()).toBeVisible();
  });

  test("renders feature trio (01, 02, 03)", async ({ page }) => {
    await expect(page.getByText("Read every holding")).toBeVisible();
    await expect(page.getByText("Score it across 20 checks")).toBeVisible();
    await expect(page.getByText("Show you what to do")).toBeVisible();
  });

  test("renders trust badges", async ({ page }) => {
    const trust = page.locator(".trust");
    await expect(trust.getByText("SEBI-aligned")).toBeVisible();
    await expect(trust.getByText("Read-only access")).toBeVisible();
    await expect(trust.getByText("No card needed")).toBeVisible();
  });

  test("health card shows the sample portfolio (PREVIEW) when logged out", async ({ page }) => {
    await expect(page.getByText("Portfolio health", { exact: false })).toBeVisible();
    // Logged out → no live data → the card advertises the sample portfolio.
    await expect(page.getByText("PREVIEW")).toBeVisible();
    await expect(page.getByText("sample portfolio")).toBeVisible();
    // The six scored-domain tiles are labelled (scoped to the card — some of
    // these words also appear in the "what we score" grid lower down).
    const tiles = page.locator(".hc-tiles");
    const tileLabels = ["Risk", "Concen", "Diverse", "Cost", "Tax", "Goals"];
    for (const label of tileLabels) {
      await expect(tiles.getByText(label, { exact: true })).toBeVisible();
    }
  });

  test("'Check my portfolio free' CTA navigates to /login", async ({ page }) => {
    await page.getByRole("button", { name: "Check my portfolio free" }).click();
    await expect(page).toHaveURL(/\/v5\/login/);
  });

  test("'Check my portfolio' nav CTA navigates to /login", async ({ page }) => {
    await page.getByRole("button", { name: "Check my portfolio", exact: true }).click();
    await expect(page).toHaveURL(/\/v5\/login/);
  });

  test("'Sign in' text navigates to /login", async ({ page }) => {
    // Both the nav and the footer carry a "Sign in" link — use the nav one.
    await page.getByText("Sign in", { exact: true }).first().click();
    await expect(page).toHaveURL(/\/v5\/login/);
  });

  test("'Watch the 90-second tour' does NOT navigate", async ({ page }) => {
    const url = page.url();
    await page.getByRole("button", { name: /Watch the 90-second tour/i }).click();
    // Scrolls to the on-page tour — should stay on the same page (no nav).
    expect(page.url()).toBe(url);
  });

  test("page uses dark theme by default", async ({ page }) => {
    const theme = await page.evaluate(() => document.documentElement.getAttribute("data-theme"));
    expect(theme).toBe("dark");
  });

  test("page has .nvx-home wrapper", async ({ page }) => {
    await expect(page.locator(".nvx-home")).toBeVisible();
  });
});
