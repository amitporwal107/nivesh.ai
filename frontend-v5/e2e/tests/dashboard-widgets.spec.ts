/**
 * Dashboard widget tests — verifies every visible element on /v5/dashboard
 * for a fully-populated portfolio (health_score=68.56, 6 pending actions).
 */
import { test, expect } from "@playwright/test";
import { mockApi } from "../helpers/api-mock";

test.describe("Dashboard widgets — populated portfolio", () => {
  test.beforeEach(async ({ page }) => {
    await mockApi(page, "populated");
    await page.goto("/v5/dashboard");
    await page.waitForLoadState("networkidle");
  });

  test("hero h1 renders health label phrase", async ({ page }) => {
    // healthLabel(68.56) → score≥55 → phrase="needs some work"
    const h1 = page.locator("h1");
    await expect(h1).toBeVisible();
    await expect(h1).toContainText("needs some work");
  });

  test("verdict paragraph renders correct text", async ({ page }) => {
    // score=68.56 ≥55 → "Fair — a few changes needed."
    await expect(page.locator("text=Fair — a few changes needed.")).toBeVisible();
  });

  test("actions identified count in summary", async ({ page }) => {
    // 6 pending actions from plans-active.json
    await expect(page.locator("text=6 actions identified")).toBeVisible();
  });

  test("ActionMatrix shows pending badge count", async ({ page }) => {
    // ActionMatrix renders "· 6 pending" for total=6
    await expect(page.locator("text=6 pending")).toBeVisible();
  });

  test("diversification sub-score renders ~37", async ({ page }) => {
    // insights-analysis.json: diversification.score=36.9 → rounds to 37
    const scoreEl = page.locator("text=37").first();
    await expect(scoreEl).toBeVisible();
  });

  test("risk sub-score renders ~77", async ({ page }) => {
    // insights-analysis.json: risk.score=76.96 → rounds to 77
    await expect(page.locator("text=77").first()).toBeVisible();
  });

  test("cost sub-score renders ~79", async ({ page }) => {
    // insights-analysis.json: cost.score=78.76 → rounds to 79
    await expect(page.locator("text=79").first()).toBeVisible();
  });

  test("performance sub-score renders 90", async ({ page }) => {
    // insights-analysis.json: performance.score=90.0
    await expect(page.locator("text=90").first()).toBeVisible();
  });

  test("nav links are present", async ({ page }) => {
    await expect(page.locator("a[href='/v5/portfolio']").first()).toBeVisible();
    await expect(page.locator("a[href='/v5/risk']").first()).toBeVisible();
    await expect(page.locator("a[href='/v5/performance']").first()).toBeVisible();
  });

  test("page does not show error state", async ({ page }) => {
    await expect(page.locator("text=Something went wrong")).not.toBeVisible();
    await expect(page.locator("text=Error loading")).not.toBeVisible();
  });
});

test.describe("Dashboard widgets — action matrix items", () => {
  test.beforeEach(async ({ page }) => {
    await mockApi(page, "populated");
    await page.goto("/v5/dashboard");
    await page.waitForLoadState("networkidle");
  });

  test("Review bucket visible for TRIM/null-type actions", async ({ page }) => {
    // plans-active.json: TRIM + 4 null-type actions → classifyAction → "review" bucket → label "Review"
    // ActionMatrix renders bucket pills; "TRIM" and "EXIT" are raw types, not labels
    await expect(page.locator("text=Review").first()).toBeVisible();
  });

  test("Increase SIP bucket visible for ADD action", async ({ page }) => {
    // plans-active.json: 1 ADD action → classifyAction → "increase" bucket → label "Increase SIP"
    await expect(page.locator("text=Increase SIP").first()).toBeVisible();
  });

  test("HDFC Balanced shown after expanding Review bucket", async ({ page }) => {
    // plans-active.json: first action is TRIM HDFC Balanced Advantage Fund (in Review bucket)
    // Bucket pills are collapsed by default; click Review to expand fund-level rows
    await page.locator("button:has-text('Review')").first().click();
    await expect(page.locator("text=HDFC Balanced").first()).toBeVisible();
  });
});

test.describe("Dashboard widgets — plan summary line", () => {
  test("plan_summary text is displayed", async ({ page }) => {
    await mockApi(page, "populated");
    await page.goto("/v5/dashboard");
    await page.waitForLoadState("networkidle");
    // plans-active.json plan_summary contains "6 actions"
    const summary = page.locator("text=/6 actions/").first();
    await expect(summary).toBeVisible();
  });
});
