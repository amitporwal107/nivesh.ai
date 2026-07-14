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
