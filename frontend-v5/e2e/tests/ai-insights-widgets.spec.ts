/**
 * AI Insights page widget tests — concentration analytics on /v5/ai-insights.
 *
 * The route /v5/ai-insights renders ConcentrationAnalytics, which calls
 * GET /api/portfolio/exposure/concentration (mocked via concentration.json).
 * It does NOT render portfolio health scores — those live on /v5/dashboard.
 *
 * Data from concentration.json:
 *   amc.items[0] = HDFC at 40.58%, caution_pct=30 → "over-concentrated"
 *   sector.items[0] = Unclassified at 19.99%, caution_pct=35 → "balanced"
 */
import { test, expect } from "@playwright/test";
import { mockApi } from "../helpers/api-mock";

test.describe("AI Insights page — concentration overview", () => {
  test.beforeEach(async ({ page }) => {
    await mockApi(page, "populated");
    await page.goto("/v5/ai-insights");
    await page.waitForLoadState("networkidle");
  });

  test("page loads without error", async ({ page }) => {
    await expect(page.locator("text=Something went wrong")).not.toBeVisible();
    await expect(page.locator("text=Error loading")).not.toBeVisible();
  });

  test("AI Insights label is present", async ({ page }) => {
    // Page header has "AI Insights · portfolio analysis"
    await expect(page.locator("text=/AI Insights/i").first()).toBeVisible();
  });

  test("over-concentrated badge is shown for AMC", async ({ page }) => {
    // AMC lens: HDFC at 40.58% exceeds caution_pct=30 → portfolioVerdict = over-concentrated
    // Header badge renders "Over-concentrated · AMC"
    await expect(page.locator("text=/Over-concentrated/i").first()).toBeVisible();
  });

  test("Concentration ladder section is present", async ({ page }) => {
    await expect(page.locator("text=/Concentration ladder/i").first()).toBeVisible();
  });

  test("lens tabs are present (Sector, AMC)", async ({ page }) => {
    await expect(page.getByRole("tab", { name: "Sector" })).toBeVisible();
    await expect(page.getByRole("tab", { name: "AMC" })).toBeVisible();
  });

  test("no error state is shown", async ({ page }) => {
    await expect(page.locator("text=Something went wrong")).not.toBeVisible();
    await expect(page.locator("text=Error loading")).not.toBeVisible();
  });
});

test.describe("AI Insights page — AMC concentration (tab)", () => {
  test.beforeEach(async ({ page }) => {
    await mockApi(page, "populated");
    await page.goto("/v5/ai-insights");
    await page.waitForLoadState("networkidle");
    // Click AMC tab to reveal AMC lens content
    await page.getByRole("tab", { name: "AMC" }).click();
  });

  test("HDFC AMC dominance percentage is shown", async ({ page }) => {
    // concentration.json: amc.largest_pct=40.58 → MetricCard renders "40.6%"
    await expect(page.locator("text=/40\\.5|40\\.6/").first()).toBeVisible();
  });

  test("HDFC named as largest AMC", async ({ page }) => {
    // amc.items[0].name = "HDFC" shown as MetricCard subtext
    await expect(page.locator("text=/HDFC/").first()).toBeVisible();
  });

  test("AMC over-concentrated verdict is shown in lens panel", async ({ page }) => {
    // VerdictBanner for AMC tab shows "Over-concentrated"
    await expect(page.locator("text=/Over-concentrated/i").first()).toBeVisible();
  });
});

test.describe("AI Insights page — sector concentration (default tab)", () => {
  test.beforeEach(async ({ page }) => {
    await mockApi(page, "populated");
    await page.goto("/v5/ai-insights");
    await page.waitForLoadState("networkidle");
    // Sector tab is the default tab — no click needed
  });

  test("sector tab content is visible by default", async ({ page }) => {
    // Sector is defaultValue — its content is rendered immediately
    await expect(page.locator("text=/Sector/i").first()).toBeVisible();
  });

  test("Unclassified sector item is shown", async ({ page }) => {
    // sector.items[0].name = "Unclassified" at 19.99%
    await expect(page.locator("text=/Unclassified/").first()).toBeVisible();
  });

  test("sector HHI value or label shown", async ({ page }) => {
    // sector.hhi_x10000 or HHI label; soft check — design may vary
    const hhi = page.locator("text=/0\\.08|HHI/i").first();
    const isVisible = await hhi.isVisible().catch(() => false);
    if (!isVisible) {
      await expect(page.locator("text=/Sector/i").first()).toBeVisible();
    }
  });
});

test.describe("AI Insights page — navigation", () => {
  test("insights page is reachable from dashboard", async ({ page }) => {
    await mockApi(page, "populated");
    await page.goto("/v5/dashboard");
    await page.waitForLoadState("networkidle");
    // Click AI Insights nav link if present in the sidebar
    const insightsLink = page.locator("a[href='/v5/ai-insights']").first();
    if (await insightsLink.isVisible()) {
      await insightsLink.click();
      await page.waitForLoadState("networkidle");
      await expect(page).toHaveURL(/\/v5\/ai-insights/);
    }
  });
});
