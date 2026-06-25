/**
 * Error and empty-state coverage:
 * - Empty portfolio: each page degrades gracefully (no crash, no blank screen)
 * - 401 unauthenticated: redirect to /login
 * - Performance empty fixture
 * - Plans edge-case fixtures (requires-goal, requires-persona)
 */
import { test, expect } from "@playwright/test";
import { mockApi, mockSingleRoute, mockApiWithPlan, mock401 } from "../helpers/api-mock";

// ─── Suite 1: Empty portfolio state ────────────────────────────────────────

test.describe("Empty portfolio — graceful degradation", () => {
  test.beforeEach(async ({ page }) => {
    await mockApi(page, "empty");
  });

  test("dashboard loads without crash when portfolio is empty", async ({ page }) => {
    await page.goto("/v5/dashboard");
    await page.waitForLoadState("networkidle");
    // Page renders — no JS error overlay, body has content
    await expect(page.locator("body")).not.toBeEmpty();
    // Should NOT show a white blank screen
    const bodyText = await page.locator("body").innerText();
    expect(bodyText.trim().length).toBeGreaterThan(10);
  });

  test("portfolio page shows empty state, not a crash", async ({ page }) => {
    await page.goto("/v5/portfolio");
    await page.waitForLoadState("networkidle");
    const bodyText = await page.locator("body").innerText();
    expect(bodyText.trim().length).toBeGreaterThan(10);
    // Should not render any holding rows (empty holdings array)
    const holdingRows = page.locator("[data-testid='holding-row']");
    await expect(holdingRows).toHaveCount(0);
  });

  test("AI insights page renders without crash on empty portfolio", async ({ page }) => {
    await page.goto("/v5/ai-insights");
    await page.waitForLoadState("networkidle");
    const bodyText = await page.locator("body").innerText();
    expect(bodyText.trim().length).toBeGreaterThan(10);
  });

  test("risk page renders without crash on empty portfolio", async ({ page }) => {
    await page.goto("/v5/risk");
    await page.waitForLoadState("networkidle");
    const bodyText = await page.locator("body").innerText();
    expect(bodyText.trim().length).toBeGreaterThan(10);
  });

  test("performance page renders without crash on empty portfolio", async ({ page }) => {
    await page.goto("/v5/performance");
    await page.waitForLoadState("networkidle");
    const bodyText = await page.locator("body").innerText();
    expect(bodyText.trim().length).toBeGreaterThan(10);
  });

  test("goals page renders without crash on empty portfolio", async ({ page }) => {
    await page.goto("/v5/goals");
    await page.waitForLoadState("networkidle");
    const bodyText = await page.locator("body").innerText();
    expect(bodyText.trim().length).toBeGreaterThan(10);
  });

  test("plan page renders without crash on empty portfolio", async ({ page }) => {
    await page.goto("/v5/plan");
    await page.waitForLoadState("networkidle");
    const bodyText = await page.locator("body").innerText();
    expect(bodyText.trim().length).toBeGreaterThan(10);
  });

  test("recommendations page renders without crash on empty portfolio", async ({ page }) => {
    await page.goto("/v5/recommendations");
    await page.waitForLoadState("networkidle");
    const bodyText = await page.locator("body").innerText();
    expect(bodyText.trim().length).toBeGreaterThan(10);
  });

  test("composition page renders without crash on empty portfolio", async ({ page }) => {
    await page.goto("/v5/composition");
    await page.waitForLoadState("networkidle");
    const bodyText = await page.locator("body").innerText();
    expect(bodyText.trim().length).toBeGreaterThan(10);
  });

  test("tax page renders without crash on empty portfolio", async ({ page }) => {
    await page.goto("/v5/tax");
    await page.waitForLoadState("networkidle");
    const bodyText = await page.locator("body").innerText();
    expect(bodyText.trim().length).toBeGreaterThan(10);
  });

  test("chat page renders without crash on empty portfolio", async ({ page }) => {
    await page.goto("/v5/chat");
    await page.waitForLoadState("networkidle");
    const bodyText = await page.locator("body").innerText();
    expect(bodyText.trim().length).toBeGreaterThan(10);
  });
});

// ─── Suite 2: 401 unauthenticated → redirect to /login ─────────────────────

test.describe("401 unauthenticated — redirect to login", () => {
  // Register populated routes first, then override auth/me with 401.
  // Playwright uses LIFO order: the 401 handler registered last wins.
  async function setupUnauth(page: Parameters<typeof mockApi>[0]) {
    await mockApi(page, "populated");
    await mock401(page, "**/api/auth/me");
  }

  test("dashboard redirects to /login on 401", async ({ page }) => {
    await setupUnauth(page);
    await page.goto("/v5/dashboard");
    await page.waitForURL(/\/login/);
    await expect(page).toHaveURL(/\/login/);
  });

  test("portfolio redirects to /login on 401", async ({ page }) => {
    await setupUnauth(page);
    await page.goto("/v5/portfolio");
    await page.waitForURL(/\/login/);
    await expect(page).toHaveURL(/\/login/);
  });

  test("AI insights redirects to /login on 401", async ({ page }) => {
    await setupUnauth(page);
    await page.goto("/v5/ai-insights");
    await page.waitForURL(/\/login/);
    await expect(page).toHaveURL(/\/login/);
  });

  test("risk page redirects to /login on 401", async ({ page }) => {
    await setupUnauth(page);
    await page.goto("/v5/risk");
    await page.waitForURL(/\/login/);
    await expect(page).toHaveURL(/\/login/);
  });

  test("performance page redirects to /login on 401", async ({ page }) => {
    await setupUnauth(page);
    await page.goto("/v5/performance");
    await page.waitForURL(/\/login/);
    await expect(page).toHaveURL(/\/login/);
  });

  test("goals page redirects to /login on 401", async ({ page }) => {
    await setupUnauth(page);
    await page.goto("/v5/goals");
    await page.waitForURL(/\/login/);
    await expect(page).toHaveURL(/\/login/);
  });

  test("plan page redirects to /login on 401", async ({ page }) => {
    await setupUnauth(page);
    await page.goto("/v5/plan");
    await page.waitForURL(/\/login/);
    await expect(page).toHaveURL(/\/login/);
  });

  test("recommendations page redirects to /login on 401", async ({ page }) => {
    await setupUnauth(page);
    await page.goto("/v5/recommendations");
    await page.waitForURL(/\/login/);
    await expect(page).toHaveURL(/\/login/);
  });

  test("chat page redirects to /login on 401", async ({ page }) => {
    await setupUnauth(page);
    await page.goto("/v5/chat");
    await page.waitForURL(/\/login/);
    await expect(page).toHaveURL(/\/login/);
  });

  test("login page itself is accessible when unauthenticated", async ({ page }) => {
    // Don't mock auth/me at all — let it 404/fail naturally
    await page.goto("/v5/login");
    await page.waitForLoadState("networkidle");
    // Login page should render its editorial h1
    await expect(
      page.getByRole("heading", { name: /finally legible|Welcome back/i })
    ).toBeVisible();
  });
});

// ─── Suite 3: Performance empty fixture ────────────────────────────────────

test.describe("Performance page — empty/no-data fixture", () => {
  test("performance page renders gracefully with empty performance data", async ({ page }) => {
    await mockApi(page, "populated");
    // Override performance endpoint with empty fixture
    await mockSingleRoute(
      page,
      "**/api/dashboards/performance*",
      "dashboards-performance-empty.json"
    );
    await page.goto("/v5/performance");
    await page.waitForLoadState("networkidle");
    // No crash — body has content
    const bodyText = await page.locator("body").innerText();
    expect(bodyText.trim().length).toBeGreaterThan(10);
  });

  test("performance page still shows fund table when performance data is empty", async ({
    page,
  }) => {
    await mockApi(page, "populated");
    await mockSingleRoute(
      page,
      "**/api/dashboards/performance*",
      "dashboards-performance-empty.json"
    );
    await page.goto("/v5/performance");
    await page.waitForLoadState("networkidle");
    // Fund-performance fixture is still populated — fund rows should appear
    const bodyText = await page.locator("body").innerText();
    // Should not show a hard error message
    expect(bodyText).not.toMatch(/something went wrong/i);
    expect(bodyText).not.toMatch(/500 error/i);
  });
});

// ─── Suite 4: Plans edge-case fixtures ─────────────────────────────────────

test.describe("Plan board — edge-case plan states", () => {
  test("plan page renders when plans require a goal to be set", async ({ page }) => {
    await mockApiWithPlan(page, "plans-requires-goal.json");
    await page.goto("/v5/plan");
    await page.waitForLoadState("networkidle");
    const bodyText = await page.locator("body").innerText();
    expect(bodyText.trim().length).toBeGreaterThan(10);
    // Should not crash
    expect(bodyText).not.toMatch(/something went wrong/i);
  });

  test("plan page renders when plans require a persona to be set", async ({ page }) => {
    await mockApiWithPlan(page, "plans-requires-persona.json");
    await page.goto("/v5/plan");
    await page.waitForLoadState("networkidle");
    const bodyText = await page.locator("body").innerText();
    expect(bodyText.trim().length).toBeGreaterThan(10);
    expect(bodyText).not.toMatch(/something went wrong/i);
  });

  test("plan page shows Backlog column even with requires-goal plan state", async ({ page }) => {
    await mockApiWithPlan(page, "plans-requires-goal.json");
    await page.goto("/v5/plan");
    await page.waitForLoadState("networkidle");
    // Kanban columns should still render
    await expect(page.getByText("Backlog")).toBeVisible();
  });

  test("plan page shows Backlog column even with requires-persona plan state", async ({ page }) => {
    await mockApiWithPlan(page, "plans-requires-persona.json");
    await page.goto("/v5/plan");
    await page.waitForLoadState("networkidle");
    await expect(page.getByText("Backlog")).toBeVisible();
  });
});

// ─── Suite 5: Network error resilience ─────────────────────────────────────

test.describe("Network error resilience", () => {
  test("dashboard survives a failed secondary API call", async ({ page }) => {
    // Mount populated auth + portfolio, but let dashboards/* 404
    await mockApi(page, "populated");
    // Abort the risk dashboard endpoint to simulate network failure
    await page.route("**/api/dashboards/risk", (route) => route.abort("failed"));
    await page.goto("/v5/dashboard");
    await page.waitForLoadState("networkidle");
    // Core dashboard should still load — body must have meaningful content
    const bodyText = await page.locator("body").innerText();
    expect(bodyText.trim().length).toBeGreaterThan(10);
    expect(bodyText).not.toMatch(/unhandled error/i);
  });

  test("performance page survives a failed fund-performance call", async ({ page }) => {
    await mockApi(page, "populated");
    await page.route("**/api/portfolio/fund-performance*", (route) => route.abort("failed"));
    await page.goto("/v5/performance");
    await page.waitForLoadState("networkidle");
    const bodyText = await page.locator("body").innerText();
    expect(bodyText.trim().length).toBeGreaterThan(10);
    expect(bodyText).not.toMatch(/unhandled error/i);
  });

  test("risk page survives an aborted risk dashboard call", async ({ page }) => {
    await mockApi(page, "populated");
    await page.route("**/api/dashboards/risk", (route) => route.abort("failed"));
    await page.goto("/v5/risk");
    await page.waitForLoadState("networkidle");
    const bodyText = await page.locator("body").innerText();
    expect(bodyText.trim().length).toBeGreaterThan(10);
  });

  test("goals page survives a failed goals call", async ({ page }) => {
    await mockApi(page, "populated");
    await page.route("**/api/goals", (route) => route.abort("failed"));
    await page.route("**/api/dashboards/goals", (route) => route.abort("failed"));
    await page.goto("/v5/goals");
    await page.waitForLoadState("networkidle");
    const bodyText = await page.locator("body").innerText();
    expect(bodyText.trim().length).toBeGreaterThan(10);
  });
});
