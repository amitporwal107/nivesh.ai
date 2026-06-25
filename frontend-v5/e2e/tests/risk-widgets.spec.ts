/**
 * Risk page widget tests — h1 VaR amount, ATTENTION badge, MetricCards,
 * stress scenarios table, risk drivers from dashboards-risk.json.
 *
 * Key derivations:
 *   stat_tiles[0].sub = "~₹18L" → vaR95Paise = 18 * 100000 * 100 = 180,000,000
 *   formatINR(180000000, {compact:true}) = "₹18L"
 *   h1: "One bad year could cost ₹18L."
 */
import { test, expect } from "@playwright/test";
import { mockApi } from "../helpers/api-mock";

test.describe("Risk page — hero h1", () => {
  test.beforeEach(async ({ page }) => {
    await mockApi(page, "populated");
    await page.goto("/v5/risk");
    await page.waitForLoadState("networkidle");
  });

  test("h1 renders VaR amount '₹18L'", async ({ page }) => {
    // Risk.tsx: "One bad year could cost {formatINR(data.vaR95Paise, {compact:true})}."
    const h1 = page.locator("h1");
    await expect(h1).toBeVisible();
    await expect(h1).toContainText("₹18L");
  });

  test("h1 contains 'One bad year could cost'", async ({ page }) => {
    await expect(
      page.locator("text=/One bad year could cost/").first()
    ).toBeVisible();
  });

  test("ATTENTION badge is always rendered", async ({ page }) => {
    // Risk.tsx: <Badge tone="warm">ATTENTION</Badge> — unconditional
    await expect(page.locator("text=ATTENTION").first()).toBeVisible();
  });

  test("no PRA warning shown when pra_available=true and pra_run_today=true", async ({ page }) => {
    // meta.pra_available=true, meta.pra_run_today=true → no PRA warning
    // PRA warning text varies; check it is NOT shown
    await expect(page.locator("text=/PRA.*not.*run|PRA.*unavailable/i")).not.toBeVisible();
  });

  test("no error state shown", async ({ page }) => {
    await expect(page.locator("text=Something went wrong")).not.toBeVisible();
  });
});

test.describe("Risk page — MetricCards", () => {
  test.beforeEach(async ({ page }) => {
    await mockApi(page, "populated");
    await page.goto("/v5/risk");
    await page.waitForLoadState("networkidle");
  });

  test("VaR · 95th · 1Y metric card label shown", async ({ page }) => {
    await expect(page.locator("text=VaR · 95th · 1Y").first()).toBeVisible();
  });

  test("VaR value 18.5% shown", async ({ page }) => {
    // stat_tiles[0].value="18.5%"
    await expect(page.locator("text=/18\.5%/").first()).toBeVisible();
  });

  test("Volatility metric card shown", async ({ page }) => {
    await expect(page.locator("text=Volatility").first()).toBeVisible();
  });

  test("Volatility value 14.2% shown", async ({ page }) => {
    await expect(page.locator("text=/14\.2%/").first()).toBeVisible();
  });

  test("Max drawdown metric card shown", async ({ page }) => {
    await expect(page.locator("text=/Max drawdown/i").first()).toBeVisible();
  });

  test("Max drawdown value 32.4% shown", async ({ page }) => {
    await expect(page.locator("text=/32\.4%/").first()).toBeVisible();
  });

  test("Beta metric card shown", async ({ page }) => {
    await expect(page.locator("text=Beta").first()).toBeVisible();
  });

  test("Beta value 0.91 shown", async ({ page }) => {
    await expect(page.locator("text=/0\.91/").first()).toBeVisible();
  });
});

test.describe("Risk page — stress scenarios", () => {
  test.beforeEach(async ({ page }) => {
    await mockApi(page, "populated");
    await page.goto("/v5/risk");
    await page.waitForLoadState("networkidle");
  });

  test("'5 scenarios' count text shown", async ({ page }) => {
    // Risk.tsx hardcodes "5 scenarios" text
    await expect(page.locator("text=/5 scenarios/").first()).toBeVisible();
  });

  test("Scenario column header shown", async ({ page }) => {
    await expect(page.locator("text=Scenario").first()).toBeVisible();
  });

  test("Portfolio column header shown", async ({ page }) => {
    await expect(page.locator("text=Portfolio").first()).toBeVisible();
  });

  test("Benchmark column header shown", async ({ page }) => {
    await expect(page.locator("text=Benchmark").first()).toBeVisible();
  });

  test("Recovery column header shown", async ({ page }) => {
    await expect(page.locator("text=Recovery").first()).toBeVisible();
  });

  test("2020 COVID Crash scenario name shown", async ({ page }) => {
    await expect(page.locator("text=2020 COVID Crash").first()).toBeVisible();
  });

  test("2008 Financial Crisis scenario shown", async ({ page }) => {
    await expect(page.locator("text=2008 Financial Crisis").first()).toBeVisible();
  });

  test("COVID portfolio loss ~-22.5% shown", async ({ page }) => {
    // portfolio_pct=-22.5 → adapter divides by 100 → -0.225 → "−22.5%"
    await expect(page.locator("text=/-22\.5%/").first()).toBeVisible();
  });

  test("2008 Crisis recovery shown as '~4 years'", async ({ page }) => {
    await expect(page.locator("text=~4 years").first()).toBeVisible();
  });

  test("COVID recovery shown as '~8 months'", async ({ page }) => {
    await expect(page.locator("text=~8 months").first()).toBeVisible();
  });
});

test.describe("Risk page — risk drivers", () => {
  test.beforeEach(async ({ page }) => {
    await mockApi(page, "populated");
    await page.goto("/v5/risk");
    await page.waitForLoadState("networkidle");
  });

  test("risk drivers heading visible", async ({ page }) => {
    // Risk.tsx: "What's making it risky · composite risk"
    await expect(
      page.locator("text=/What's making it risky/").first()
    ).toBeVisible();
  });

  test("HDFC Balanced shown as top risk driver", async ({ page }) => {
    // breakdown.items[0].name="HDFC Balanced Advantage Fund", value=28.5
    await expect(page.locator("text=/HDFC Balanced/").first()).toBeVisible();
  });

  test("Nippon India Small Cap shown in risk drivers", async ({ page }) => {
    await expect(page.locator("text=/Nippon India Small Cap/").first()).toBeVisible();
  });
});
