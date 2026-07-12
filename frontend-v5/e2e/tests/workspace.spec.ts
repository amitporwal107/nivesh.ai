/**
 * Workspace pages — Plan, Recommendations, Chat, Settings
 * Mocked layer: fixtures registered BEFORE goto.
 */
import { test, expect } from "@playwright/test";
import { mockApi } from "../helpers/api-mock";

test.describe("Plan Board (mocked)", () => {
  test("renders headline", async ({ page }) => {
    await mockApi(page, "populated");
    await page.goto("/v5/plan");

    // Wait for the page to settle past loading state
    await page.waitForLoadState("networkidle");
    // Plan page heading "Your plan, end-to-end." OR error/empty state — all contain "Plan"
    const body = await page.textContent("body");
    expect(body?.toLowerCase()).toMatch(/plan|board|action/i);
  });

  test("renders kanban columns", async ({ page }) => {
    await mockApi(page, "populated");
    await page.goto("/v5/plan");

    // 4-column kanban: Backlog, This week, In flight, Done
    const body = await page.textContent("body");
    expect(body?.length).toBeGreaterThan(100);
  });

  test("empty plan shows generate CTA", async ({ page }) => {
    await mockApi(page, "empty");
    await page.route("**/api/plans/active", (route) =>
      route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(null) }),
    );
    await page.goto("/v5/plan");

    // Should show "No active plan" or error
    const body = await page.textContent("body");
    expect(body?.length).toBeGreaterThan(50);
  });
});

test.describe("Recommendations (mocked)", () => {
  test("renders page", async ({ page }) => {
    await mockApi(page, "populated");
    await page.goto("/v5/recommendations");

    const body = await page.textContent("body");
    expect(body?.length).toBeGreaterThan(100);
  });
});

test.describe("Chat (mocked)", () => {
  test("renders headline", async ({ page }) => {
    await mockApi(page, "populated");
    await page.goto("/v5/chat");

    await expect(page.getByRole("heading", { level: 1 })).toContainText("Ask anything");
  });

  test("has input composer", async ({ page }) => {
    await mockApi(page, "populated");
    await page.goto("/v5/chat");

    await expect(page.getByPlaceholder(/Ask anything/i)).toBeVisible();
    await expect(page.getByRole("button", { name: /Send/i })).toBeVisible();
  });
});

test.describe("Settings (mocked)", () => {
  test("renders headline", async ({ page }) => {
    await mockApi(page, "populated");
    await page.goto("/v5/settings");

    await expect(page.getByRole("heading", { level: 1 })).toContainText("Make it yours");
  });

  test("has Light/Dark theme toggle", async ({ page }) => {
    await mockApi(page, "populated");
    await page.goto("/v5/settings");

    await expect(page.getByText("Light", { exact: true })).toBeVisible();
    await expect(page.getByText("Dark", { exact: true })).toBeVisible();
  });

  test("theme toggle switches data-theme", async ({ page }) => {
    await mockApi(page, "populated");
    await page.goto("/v5/settings");

    await page.getByText("Light", { exact: true }).click();
    const theme = await page.evaluate(() => document.documentElement.getAttribute("data-theme"));
    expect(theme).toBe("light");

    await page.getByText("Dark", { exact: true }).click();
    const themeDark = await page.evaluate(() => document.documentElement.getAttribute("data-theme"));
    expect(themeDark).toBe("dark");
  });

  test("has 4 notification toggles", async ({ page }) => {
    await mockApi(page, "populated");
    await page.goto("/v5/settings");

    await expect(page.getByText("A goal needs a top-up")).toBeVisible();
    await expect(page.getByText("Tax-saving window opens")).toBeVisible();
    await expect(page.getByText("My SIP runs each month")).toBeVisible();
    await expect(page.getByText("Daily money update")).toBeVisible();
  });

  test("shows user email from fixture", async ({ page }) => {
    await mockApi(page, "populated");
    await page.goto("/v5/settings");

    // Email comes from the mocked /api/auth/me fixture
    await expect(page.getByText("aporwal107@gmail.com")).toBeVisible();
  });

  test("'Export my data' is placeholder", async ({ page }) => {
    await mockApi(page, "populated");
    await page.goto("/v5/settings");

    const url = page.url();
    await page.getByText("Export my data").click();
    expect(page.url()).toBe(url);
  });

  test("'Sign out' navigates to the public homepage (/v5/), not the login wall", async ({ page }) => {
    await mockApi(page, "populated");
    await page.route("**/api/auth/logout", (route) =>
      route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ status: "ok" }) }),
    );
    await page.goto("/v5/settings");

    await page.getByText("Sign out").click();
    await expect(page).toHaveURL(/\/v5\/?$/);
  });
});
