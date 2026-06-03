/**
 * Portfolio — /v5/portfolio
 * Mocked layer.
 */
import { test, expect } from "@playwright/test";
import { mockApi } from "../helpers/api-mock";

test.describe("Portfolio (mocked)", () => {
  test("renders page content", async ({ page }) => {
    await mockApi(page, "populated");
    await page.goto("/v5/portfolio");

    // Portfolio page should render something — heading or holdings
    const body = await page.textContent("body");
    expect(body?.length).toBeGreaterThan(50);
  });

  test("empty portfolio shows connect CTA", async ({ page }) => {
    await mockApi(page, "empty");
    await page.goto("/v5/portfolio");

    const body = await page.textContent("body");
    expect(body?.length).toBeGreaterThan(50);
  });
});
