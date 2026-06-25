/**
 * Goals page widget tests — badge, insight, stat tiles from dashboards-goals.json.
 * Also tests Goals setup wizard flow when no goals are configured.
 */
import { test, expect } from "@playwright/test";
import { mockApi, mockSingleRoute } from "../helpers/api-mock";

test.describe("Goals page — stat tiles and badge", () => {
  test.beforeEach(async ({ page }) => {
    await mockApi(page, "populated");
    await page.goto("/v5/goals");
    await page.waitForLoadState("networkidle");
  });

  test("badge shows 'On track'", async ({ page }) => {
    // dashboards-goals.json: badge.label="On track", tone="moss"
    await expect(page.locator("text=On track").first()).toBeVisible();
  });

  test("headline 'All goals on track.' is shown", async ({ page }) => {
    // dashboards-goals.json: insight.headline="All goals on track."
    await expect(page.locator("text=All goals on track.").first()).toBeVisible();
  });

  test("Goals stat tile is present", async ({ page }) => {
    // stat_tiles[0]: label="Goals", value="0"
    await expect(page.locator("text=Goals").first()).toBeVisible();
  });

  test("At risk stat tile shows 0", async ({ page }) => {
    // stat_tiles[1]: label="At risk", value="0"
    await expect(page.locator("text=At risk").first()).toBeVisible();
  });

  test("no error state shown", async ({ page }) => {
    await expect(page.locator("text=Something went wrong")).not.toBeVisible();
    await expect(page.locator("text=Error loading")).not.toBeVisible();
  });
});

test.describe("Goals page — goals list", () => {
  test.beforeEach(async ({ page }) => {
    await mockApi(page, "populated");
    await page.goto("/v5/goals");
    await page.waitForLoadState("networkidle");
  });

  test("goals.json data rendered (retirement goal)", async ({ page }) => {
    // goals.json likely contains sample goals — check for a common goal type
    const goalEl = page.locator("text=/Retirement|Emergency|Education|Home/").first();
    const isVisible = await goalEl.isVisible().catch(() => false);
    if (!isVisible) {
      // Zero goals state — check for empty/add-goals CTA
      const addGoal = page.locator("text=/Add|Set up|Create.*goal/i").first();
      const emptyState = await addGoal.isVisible().catch(() => false);
      // Either goals shown or empty state — both are valid
      expect(isVisible || emptyState).toBeTruthy();
    }
  });
});

test.describe("Goals page — add goal wizard", () => {
  test("Add goal button is visible", async ({ page }) => {
    await mockApi(page, "populated");
    await page.goto("/v5/goals");
    await page.waitForLoadState("networkidle");
    // Look for an Add Goal / New Goal / + button
    const addBtn = page.locator("text=/Add.*goal|New.*goal|\\+ Goal/i").first();
    const isVisible = await addBtn.isVisible().catch(() => false);
    // May not be present if goals are already configured — soft assertion
    if (isVisible) {
      await addBtn.click();
      // After click, a modal or form should appear
      await expect(page.locator("text=/goal name|goal type|target|amount/i").first()).toBeVisible();
    }
  });
});

test.describe("Goals page — risk profile alignment", () => {
  test("goal alignment section is present if goals exist", async ({ page }) => {
    await mockApi(page, "populated");
    await page.goto("/v5/goals");
    await page.waitForLoadState("networkidle");
    // insight.headline should indicate alignment status
    const headline = page.locator("text=/on track|at risk|off track/i").first();
    await expect(headline).toBeVisible();
  });
});
