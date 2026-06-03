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
    await expect(page.locator(".nv-mark").first()).toBeVisible();
    await expect(page.getByText("Nivesh", { exact: true }).first()).toBeVisible();
    await expect(page.getByRole("button", { name: /Check my portfolio/i }).first()).toBeVisible();
  });

  test("renders feature trio (01, 02, 03)", async ({ page }) => {
    await expect(page.getByText("Read every holding")).toBeVisible();
    await expect(page.getByText("Score it across 20 checks")).toBeVisible();
    await expect(page.getByText("Show you what to do")).toBeVisible();
  });

  test("renders trust badges", async ({ page }) => {
    await expect(page.getByText("SEBI-aligned")).toBeVisible();
    await expect(page.getByText("Read-only access")).toBeVisible();
    await expect(page.getByText("No card needed")).toBeVisible();
  });

  test("health preview card shows placeholder when logged out", async ({ page }) => {
    await expect(page.getByText("Portfolio health", { exact: false })).toBeVisible();
    await expect(page.getByText("Sign in to see your insights")).toBeVisible();
    // Bars should be present but empty (no scores)
    const barLabels = ["risk", "concen", "diverse", "cost", "tax", "goals"];
    for (const label of barLabels) {
      await expect(page.getByText(label, { exact: true })).toBeVisible();
    }
  });

  test("'Check my portfolio free' CTA navigates to /login", async ({ page }) => {
    await page.getByRole("button", { name: "Check my portfolio free" }).click();
    await expect(page).toHaveURL(/\/v5\/login/);
  });

  test("'Check my portfolio →' nav CTA navigates to /login", async ({ page }) => {
    await page.getByRole("button", { name: "Check my portfolio →" }).click();
    await expect(page).toHaveURL(/\/v5\/login/);
  });

  test("'Sign in' text navigates to /login", async ({ page }) => {
    await page.getByText("Sign in", { exact: true }).click();
    await expect(page).toHaveURL(/\/v5\/login/);
  });

  test("'Watch 90-second tour' does NOT navigate", async ({ page }) => {
    const url = page.url();
    await page.getByRole("button", { name: /Watch 90-second tour/i }).click();
    // Should stay on same page
    expect(page.url()).toBe(url);
  });

  test("page uses dark theme by default", async ({ page }) => {
    const theme = await page.evaluate(() => document.documentElement.getAttribute("data-theme"));
    expect(theme).toBe("dark");
  });

  test("page has .nv-frame wrapper with radial gradient", async ({ page }) => {
    await expect(page.locator(".nv-frame")).toBeVisible();
  });
});
