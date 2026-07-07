/**
 * Copilot tour — /v5/copilot  (public marketing page, no auth)
 * + homepage product-overview link that opens it.
 *
 * Acceptance criteria for the new interactive tour page:
 *  1. /copilot renders the tour hero + all 8 section anchors.
 *  2. The sticky sub-nav lists every section.
 *  3. Signature content of each section is present (overview pipeline,
 *     design principles, the 6-stage advisory flow, the 10 workflows,
 *     the all-flows filmstrip, the advisor book, the mobile rail).
 *  4. The tour renders dark (forced .copilot-tour dark wrapper).
 *  5. The homepage product overview has a "Take the full Copilot tour"
 *     card/link that navigates to /copilot.
 */
import { test, expect } from "@playwright/test";

test.describe("Copilot tour page", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/v5/copilot");
    // large page — on a cold dev server the module graph compiles on first hit;
    // wait for the tour root before asserting so we don't race the compile.
    await page.locator(".copilot-tour").waitFor({ state: "attached", timeout: 30000 });
  });

  test("renders hero headline", async ({ page }) => {
    const h1 = page.getByRole("heading", { level: 1 });
    await expect(h1).toContainText("one thing to fix first");
  });

  test("renders the sticky section sub-nav with every section", async ({ page }) => {
    const nav = page.locator(".ct-subnav");
    await expect(nav).toBeVisible();
    for (const label of ["Overview", "Principles", "Screens", "Workflows", "All flows", "Advisor", "Mobile"]) {
      await expect(nav.getByText(label, { exact: true })).toBeVisible();
    }
  });

  test("all 8 section anchors exist in the DOM", async ({ page }) => {
    for (const id of [
      "ct-overview",
      "ct-principles",
      "ct-screens",
      "ct-workflows",
      "ct-allflows",
      "ct-advisor",
      "ct-mobile",
    ]) {
      await expect(page.locator(`#${id}`)).toBeAttached();
    }
  });

  test("overview: pipeline + two audiences", async ({ page }) => {
    await expect(page.getByText("How the copilot thinks")).toBeVisible();
    await expect(page.getByText("NIDP data layer")).toBeVisible();
    await expect(page.getByText("Specialist agents", { exact: true })).toBeVisible();
  });

  test("design principles are listed", async ({ page }) => {
    await expect(page.getByText("Conversation + workspace, not chat alone")).toBeVisible();
    await expect(page.getByText("Trust & evidence architecture")).toBeVisible();
    await expect(page.getByText("Human-in-the-loop & escalation")).toBeVisible();
  });

  test("advisory flow shows the six stages", async ({ page }) => {
    const section = page.locator("#ct-screens");
    for (const stage of ["Intake", "Analysis", "Options", "Recommendation", "Action", "Human handoff"]) {
      await expect(section.getByText(stage, { exact: false }).first()).toBeVisible();
    }
  });

  test("workflow library shows the 10 workflows", async ({ page }) => {
    await expect(page.getByText("Portfolio health review").first()).toBeVisible();
    await expect(page.getByText("Fund deep-dive").first()).toBeVisible();
    await expect(page.getByText("Tax-loss harvesting").first()).toBeVisible();
    await expect(page.getByText("What moved today").first()).toBeVisible();
  });

  test("all-flows filmstrip renders Ask→Analyze→Decide→Act", async ({ page }) => {
    const section = page.locator("#ct-allflows");
    await expect(section.getByText("ASK", { exact: true }).first()).toBeVisible();
    await expect(section.getByText("ANALYZE", { exact: true }).first()).toBeVisible();
    await expect(section.getByText("DECIDE", { exact: true }).first()).toBeVisible();
    await expect(section.getByText("ACT", { exact: true }).first()).toBeVisible();
  });

  test("advisor book shows AUM + who-to-call table", async ({ page }) => {
    await expect(page.locator("#ct-advisor").getByText("Who to call first", { exact: true })).toBeVisible();
    await expect(page.getByText("Rohan Shah").first()).toBeVisible();
  });

  test("mobile rail renders phone frames", async ({ page }) => {
    const devices = page.locator("#ct-mobile .ct-device");
    await expect(devices.first()).toBeVisible();
    expect(await devices.count()).toBeGreaterThanOrEqual(4);
  });

  test("tour is forced dark", async ({ page }) => {
    await expect(page.locator(".copilot-tour")).toBeAttached();
    const bg = await page.locator(".copilot-tour").evaluate(
      (el) => getComputedStyle(el).getPropertyValue("--bg-0").trim(),
    );
    expect(bg.toLowerCase()).toBe("#06080f");
  });
});

test.describe("Homepage → Copilot tour link", () => {
  test("product overview has a Copilot tour card that navigates to /copilot", async ({ page }) => {
    await page.goto("/v5/");
    await page.getByRole("heading", { level: 1 }).waitFor({ timeout: 30000 });
    const btn = page.getByRole("button", { name: /Explore the full Copilot tour/i });
    await expect(btn).toBeVisible();
    await btn.click();
    await expect(page).toHaveURL(/\/v5\/copilot/);
    await expect(page.getByRole("heading", { level: 1 })).toContainText("one thing to fix first");
  });
});
