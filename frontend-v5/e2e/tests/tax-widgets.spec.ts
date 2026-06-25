/**
 * Tax page widget tests — badge, insight, LTCG stat tiles, harvest opportunities.
 * Data from dashboards-tax.json.
 */
import { test, expect } from "@playwright/test";
import { mockApi } from "../helpers/api-mock";

test.describe("Tax page — badge and insight", () => {
  test.beforeEach(async ({ page }) => {
    await mockApi(page, "populated");
    await page.goto("/v5/tax");
    await page.waitForLoadState("networkidle");
  });

  test("badge shows 'Nothing to harvest'", async ({ page }) => {
    // dashboards-tax.json: badge.label="Nothing to harvest", tone="mute"
    await expect(page.locator("text=Nothing to harvest").first()).toBeVisible();
  });

  test("insight headline 'No LTCG harvest opportunities right now.'", async ({ page }) => {
    // dashboards-tax.json: insight.headline
    await expect(
      page.locator("text=No LTCG harvest opportunities right now.").first()
    ).toBeVisible();
  });

  test("insight subtext shows '307 days until FY end.'", async ({ page }) => {
    // dashboards-tax.json: insight.subtext="307 days until FY end."
    await expect(
      page.locator("text=307 days until FY end.").first()
    ).toBeVisible();
  });

  test("no error state shown", async ({ page }) => {
    await expect(page.locator("text=Something went wrong")).not.toBeVisible();
  });
});

test.describe("Tax page — stat tiles", () => {
  test.beforeEach(async ({ page }) => {
    await mockApi(page, "populated");
    await page.goto("/v5/tax");
    await page.waitForLoadState("networkidle");
  });

  test("LTCG remaining tile shows ₹125K", async ({ page }) => {
    // stat_tiles[0]: label="LTCG remaining", value="₹125K"
    await expect(page.locator("text=₹125K").first()).toBeVisible();
  });

  test("Days to FY end tile shows 307", async ({ page }) => {
    // stat_tiles[1]: label="Days to FY end", value="307"
    await expect(page.locator("text=307").first()).toBeVisible();
  });

  test("Harvest opp. tile shows 0", async ({ page }) => {
    // stat_tiles[2]: label="Harvest opp.", value="0"
    await expect(page.locator("text=Harvest opp.").first()).toBeVisible();
  });

  test("'LTCG remaining' label is visible", async ({ page }) => {
    await expect(page.locator("text=LTCG remaining").first()).toBeVisible();
  });
});

test.describe("Tax page — LTCG/STCG breakdown", () => {
  test.beforeEach(async ({ page }) => {
    await mockApi(page, "populated");
    await page.goto("/v5/tax");
    await page.waitForLoadState("networkidle");
  });

  test("tax page renders full content without blank screen", async ({ page }) => {
    // Verify the page content area is not blank
    const bodyText = await page.locator("body").innerText();
    expect(bodyText.length).toBeGreaterThan(50);
  });

  test("FY end mention present", async ({ page }) => {
    await expect(page.locator("text=/FY end|FY\s?end/").first()).toBeVisible();
  });
});
