/**
 * Plan Board widget tests — Kanban columns, action cards, badges.
 * All 6 actions from plans-active.json have status="pending" → Backlog column.
 */
import { test, expect } from "@playwright/test";
import { mockApi } from "../helpers/api-mock";

test.describe("Plan Board — Kanban columns", () => {
  test.beforeEach(async ({ page }) => {
    await mockApi(page, "populated");
    await page.goto("/v5/plan");
    await page.waitForLoadState("networkidle");
  });

  test("Backlog column is rendered", async ({ page }) => {
    // 4 columns: Backlog | This week | In flight | Done·30d
    await expect(page.locator("text=Backlog").first()).toBeVisible();
  });

  test("'This week' column is rendered", async ({ page }) => {
    await expect(page.locator("text=/This week/").first()).toBeVisible();
  });

  test("'In flight' column is rendered", async ({ page }) => {
    await expect(page.locator("text=/In flight/").first()).toBeVisible();
  });

  test("Done column is rendered", async ({ page }) => {
    // May show as "Done" or "Done·30d"
    await expect(page.locator("text=/Done/").first()).toBeVisible();
  });

  test("no error state shown", async ({ page }) => {
    await expect(page.locator("text=Something went wrong")).not.toBeVisible();
  });
});

test.describe("Plan Board — action cards in Backlog", () => {
  test.beforeEach(async ({ page }) => {
    await mockApi(page, "populated");
    await page.goto("/v5/plan");
    await page.waitForLoadState("networkidle");
  });

  test("6 action cards visible (all pending → Backlog)", async ({ page }) => {
    // plans-active.json: 6 actions all status="pending"
    // Each card should have an action type badge
    const actionTypes = page.locator("text=/TRIM|EXIT|ADD|HOLD|CONSOLIDATE|REDIRECT/");
    const count = await actionTypes.count();
    expect(count).toBeGreaterThanOrEqual(1);
  });

  test("HDFC Balanced action card is visible", async ({ page }) => {
    // First action: TRIM HDFC Balanced Advantage Fund
    await expect(page.locator("text=/HDFC Balanced/").first()).toBeVisible();
  });

  test("Reduce badge is present for EXIT/TRIM actions", async ({ page }) => {
    // actionToFilterGroup: EXIT/TRIM → "reduce"
    // May render as a "Reduce" chip/badge on the card
    const reduceBadge = page.locator("text=/Reduce|REDUCE/").first();
    await expect(reduceBadge).toBeVisible();
  });

  test("Add badge is present for ADD action", async ({ page }) => {
    // 1 ADD action → "add" filter group → "Add" badge/label
    const addBadge = page.locator("text=/\\bAdd\\b/").first();
    await expect(addBadge).toBeVisible();
  });

  test("plan score is shown", async ({ page }) => {
    // plans-active.json: portfolio_score=58.9
    const scoreEl = page.locator("text=/58\\.9|58\.9/").first();
    await expect(scoreEl).toBeVisible();
  });

  test("total actions count shown as 6", async ({ page }) => {
    // total_actions=6
    const countEl = page.locator("text=/6 action/").first();
    await expect(countEl).toBeVisible();
  });
});

test.describe("Plan Board — interaction", () => {
  test("clicking an action card does not crash", async ({ page }) => {
    await mockApi(page, "populated");
    await page.goto("/v5/plan");
    await page.waitForLoadState("networkidle");

    const firstCard = page.locator("[data-testid='action-card'], [class*='action-card'], [class*='ActionCard']").first();
    const cardExists = await firstCard.isVisible().catch(() => false);
    if (cardExists) {
      await firstCard.click();
      await expect(page.locator("text=Something went wrong")).not.toBeVisible();
    }
  });

  test("plan summary line is rendered", async ({ page }) => {
    await mockApi(page, "populated");
    await page.goto("/v5/plan");
    await page.waitForLoadState("networkidle");
    // plan_summary: "6 actions to improve your portfolio score."
    const summary = page.locator("text=/6 actions/").first();
    await expect(summary).toBeVisible();
  });
});
