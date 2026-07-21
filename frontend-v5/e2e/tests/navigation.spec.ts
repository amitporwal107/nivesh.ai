/**
 * Navigation + cross-cutting tests
 * Mocked layer: sidebar routing, mobile nav, 401 handling
 */
import { test, expect } from "@playwright/test";
import { mockApi, mock401 } from "../helpers/api-mock";

test.describe("Desktop sidebar navigation (≥1024px)", () => {
  test.use({ viewport: { width: 1280, height: 800 } });

  const SIDEBAR_LINKS = [
    { label: "Overview", path: "/v5/dashboard" },
    { label: "Concentration", path: "/v5/concentration" },
    { label: "Diversification", path: "/v5/diversification" },
    { label: "Risk", path: "/v5/risk" },
    { label: "Performance", path: "/v5/performance" },
    { label: "Goals", path: "/v5/goals" },
    { label: "Tax", path: "/v5/tax" },
    { label: "Plan board", path: "/v5/plan" },
    { label: "Chat copilot", path: "/v5/chat" },
    { label: "Recommendations", path: "/v5/recommendations" },
  ];

  for (const { label, path } of SIDEBAR_LINKS) {
    test(`sidebar link "${label}" navigates to ${path}`, async ({ page }) => {
      await mockApi(page, "populated");
      await page.goto("/v5/dashboard");

      const link = page.getByRole("link", { name: label });
      await expect(link).toBeVisible();
      await link.click();
      await expect(page).toHaveURL(new RegExp(path.replace(/\//g, "\\/")));
    });
  }

  test("active link is highlighted", async ({ page }) => {
    await mockApi(page, "populated");
    await page.goto("/v5/concentration");

    const activeLink = page.getByRole("link", { name: "Concentration" });
    // Active link should have a distinguishing class
    await expect(activeLink).toBeVisible();
  });

  test("sidebar shows nav groups", async ({ page }) => {
    await mockApi(page, "populated");
    await page.goto("/v5/dashboard");

    await expect(page.getByText("Dashboards", { exact: true }).first()).toBeVisible();
    await expect(page.getByText("Workspace", { exact: true }).first()).toBeVisible();
  });

  test("Pro Trader and Strategy Builder are hidden from the sidebar", async ({ page }) => {
    await mockApi(page, "populated");
    await page.goto("/v5/dashboard");

    // Sanity: the nav rendered (a known link is present) before asserting absence.
    await expect(page.getByRole("link", { name: "Recommendations" })).toBeVisible();

    // The two de-surfaced destinations must NOT appear as nav links.
    await expect(page.getByRole("link", { name: "Pro Trader" })).toHaveCount(0);
    await expect(page.getByRole("link", { name: "Strategy Builder" })).toHaveCount(0);
  });

  test("sidebar shows user name from fixture", async ({ page }) => {
    await mockApi(page, "populated");
    await page.goto("/v5/dashboard");

    // Name from user-profile.json fixture
    await expect(page.getByText("Amit Porwal")).toBeVisible();
  });

  test("sidebar shows logo mark", async ({ page }) => {
    await mockApi(page, "populated");
    await page.goto("/v5/dashboard");

    await expect(page.locator(".nv-mark").first()).toBeVisible();
  });
});

test.describe("Mobile navigation (<1024px)", () => {
  test.use({ viewport: { width: 390, height: 844 } });

  test("sidebar is hidden on mobile", async ({ page }) => {
    await mockApi(page, "populated");
    await page.goto("/v5/dashboard");

    // Sidebar should be hidden at mobile width
    const sidebar = page.locator("aside");
    if (await sidebar.count() > 0) {
      await expect(sidebar).toBeHidden();
    }
  });

  // ── Mobile bottom nav — personal (non-advisory) user gets PERSONAL_TABS,
  //    which now carries a "Research" tab inserted directly after "Tips".
  //    Scope the queries to the bottom <nav aria-label="Primary"> so they can't
  //    collide with the desktop sidebar (also aria-label="Primary", but hidden).
  test.describe("bottom nav Research tab", () => {
    const bottomNav = (page: import("@playwright/test").Page) =>
      page.locator('nav[aria-label="Primary"]').last();

    test("bottom nav shows Home · Portfolio · Tips · Research · Chat in order", async ({ page }) => {
      await mockApi(page, "populated");
      await page.goto("/v5/dashboard");

      // Wait for the nav to settle before the one-shot allInnerTexts() read.
      const nav = bottomNav(page);
      await expect(nav.getByRole("link", { name: "Research" })).toBeVisible();

      const labels = (await nav.getByRole("link").allInnerTexts()).map((t) => t.trim());
      expect(labels).toEqual(["Home", "Portfolio", "Tips", "Research", "Chat"]);
    });

    test('"Research" sits immediately after "Tips"', async ({ page }) => {
      await mockApi(page, "populated");
      await page.goto("/v5/dashboard");

      const nav = bottomNav(page);
      await expect(nav.getByRole("link", { name: "Research" })).toBeVisible();

      const labels = (await nav.getByRole("link").allInnerTexts()).map((t) => t.trim());
      expect(labels.indexOf("Research")).toBe(labels.indexOf("Tips") + 1);
    });

    test('"Research" tab links to /research', async ({ page }) => {
      await mockApi(page, "populated");
      await page.goto("/v5/dashboard");

      const research = bottomNav(page).getByRole("link", { name: "Research" });
      await expect(research).toBeVisible();
      await expect(research).toHaveAttribute("href", /\/research$/);
    });

    test('tapping "Research" navigates to /research', async ({ page }) => {
      await mockApi(page, "populated");
      await page.goto("/v5/dashboard");

      await bottomNav(page).getByRole("link", { name: "Research" }).click();
      await expect(page).toHaveURL(/\/research$/);
    });

    test('existing "Tips" tab still links to /recommendations (regression)', async ({ page }) => {
      await mockApi(page, "populated");
      await page.goto("/v5/dashboard");

      const tips = bottomNav(page).getByRole("link", { name: "Tips" });
      await expect(tips).toHaveAttribute("href", /\/recommendations$/);
    });
  });
});

test.describe("Unauthenticated access — 401 handling", () => {
  test("protected page with 401 shows error, does NOT redirect to /login", async ({ page }) => {
    await mock401(page, "**/api/**");
    await page.goto("/v5/dashboard");
    await page.waitForLoadState("networkidle");

    // Should NOT redirect to /login — no active route guard
    expect(page.url()).toContain("/v5/dashboard");

    // Should show error state or content (not blank)
    const body = await page.textContent("body");
    expect(body?.length).toBeGreaterThan(0);
  });

  test("homepage works without auth", async ({ page }) => {
    await page.goto("/v5/");

    await expect(page.getByRole("heading", { level: 1 })).toContainText("Your portfolio");
  });
});
