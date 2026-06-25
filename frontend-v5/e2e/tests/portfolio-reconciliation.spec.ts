/**
 * Portfolio reconciliation tests — verifies holdings count, total value,
 * and tab structure against fixtures (holdings-enriched.json, 111 holdings).
 */
import { test, expect } from "@playwright/test";
import { mockApi } from "../helpers/api-mock";

const HOLDINGS_COUNT = 111;
const TOTAL_VALUE_COMPACT = "₹1.03Cr"; // formatINR(10306772.4 * 100, {compact:true})
const INVESTED_COMPACT = "₹84.07L";   // formatINR(8407496.59 * 100, {compact:true})

test.describe("Portfolio page — Holdings tab", () => {
  test.beforeEach(async ({ page }) => {
    await mockApi(page, "populated");
    await page.goto("/v5/portfolio");
    await page.waitForLoadState("networkidle");
  });

  test("Holdings tab label shows correct count", async ({ page }) => {
    // Portfolio.tsx: "Holdings · {holdings.length}"
    await expect(
      page.locator(`text=Holdings · ${HOLDINGS_COUNT}`)
    ).toBeVisible();
  });

  test("portfolio total value renders compacted", async ({ page }) => {
    // enrichedValue = 10306772.4 * 100 paise → "₹1.03Cr"
    await expect(page.locator(`text=${TOTAL_VALUE_COMPACT}`).first()).toBeVisible();
  });

  test("Allocation tab is present", async ({ page }) => {
    await expect(page.locator("text=Allocation")).toBeVisible();
  });

  test("SIPs tab is present", async ({ page }) => {
    await expect(page.locator("text=SIPs")).toBeVisible();
  });

  test("no equity/MF/ETF filter tabs rendered", async ({ page }) => {
    // Portfolio.tsx has no category filter — these should NOT appear
    await expect(page.locator("text=Equity")).not.toBeVisible();
    await expect(page.locator("text=ETF")).not.toBeVisible();
  });

  test("at least one holding row is rendered", async ({ page }) => {
    // Holdings list should render items from the enriched fixture
    const rows = page.locator("[data-testid='holding-row'], tr, [class*='holding']");
    // Just assert some list content appears — ISIN from first enriched holding
    const firstFundName = page.locator("text=HDFC").first();
    await expect(firstFundName).toBeVisible();
  });

  test("page does not crash or show error", async ({ page }) => {
    await expect(page.locator("text=Something went wrong")).not.toBeVisible();
  });
});

test.describe("Portfolio page — Allocation tab", () => {
  test.beforeEach(async ({ page }) => {
    await mockApi(page, "populated");
    await page.goto("/v5/portfolio");
    await page.waitForLoadState("networkidle");
  });

  test("switching to Allocation tab works", async ({ page }) => {
    await page.click("text=Allocation");
    // After tab switch, allocation chart/content should appear
    await expect(page.locator("text=Allocation")).toBeVisible();
    await expect(page.locator("text=Something went wrong")).not.toBeVisible();
  });
});

test.describe("Portfolio page — SIPs tab", () => {
  test.beforeEach(async ({ page }) => {
    await mockApi(page, "populated");
    await page.goto("/v5/portfolio");
    await page.waitForLoadState("networkidle");
  });

  test("switching to SIPs tab works", async ({ page }) => {
    await page.click("text=SIPs");
    await expect(page.locator("text=Something went wrong")).not.toBeVisible();
  });
});

test.describe("Portfolio reconciliation — totals", () => {
  test("total invested value renders", async ({ page }) => {
    await mockApi(page, "populated");
    await page.goto("/v5/portfolio");
    await page.waitForLoadState("networkidle");
    // invested_rs=8407496.59 * 100 paise → "₹84.07L"
    const invested = page.locator(`text=${INVESTED_COMPACT}`).first();
    await expect(invested).toBeVisible();
  });

  test("P&L renders as positive gain", async ({ page }) => {
    await mockApi(page, "populated");
    await page.goto("/v5/portfolio");
    await page.waitForLoadState("networkidle");
    // pnl_pct=22.59%, xirr_pct=14.29% — one of these positive % should appear
    const pnlPct = page.locator("text=/\\+?22\\.5|\\+?22\\.6/").first();
    const xirrPct = page.locator("text=/\\+?14\\.2|\\+?14\\.3/").first();
    // At least one gain indicator visible
    const either = (await pnlPct.isVisible()) || (await xirrPct.isVisible());
    expect(either).toBeTruthy();
  });
});
