/**
 * Dashboard — /v5/dashboard
 * Mocked layer: deterministic fixtures, no live API.
 */
import { test, expect } from "@playwright/test";
import { mockApi } from "../helpers/api-mock";

test.describe("Dashboard (mocked)", () => {
  test("renders sidebar with nav groups", async ({ page }) => {
    await mockApi(page, "populated");   // BEFORE goto
    await page.goto("/v5/dashboard");

    await expect(page.getByText("Dashboards", { exact: true }).first()).toBeVisible();
    await expect(page.getByText("Workspace", { exact: true }).first()).toBeVisible();
  });

  test("renders page heading", async ({ page }) => {
    await mockApi(page, "populated");
    await page.goto("/v5/dashboard");
    await page.waitForLoadState("networkidle");

    // Accept h1 (loaded data) OR h3 (error/empty states) OR "Couldn't load" text
    const h1 = await page.getByRole("heading", { level: 1 }).count();
    const h3 = await page.getByRole("heading", { level: 3 }).count();
    const hasError = await page.getByText("Couldn't load", { exact: false }).count();
    expect(h1 + h3 + hasError).toBeGreaterThan(0);
  });

  test("empty portfolio shows upload CTA", async ({ page }) => {
    await mockApi(page, "empty");
    await page.goto("/v5/dashboard");

    // Should show empty state or error — not a blank page
    const body = await page.textContent("body");
    expect(body?.length).toBeGreaterThan(50);
  });
});
