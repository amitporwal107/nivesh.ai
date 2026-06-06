/**
 * API mocking helpers — intercept backend requests with fixture data.
 *
 * Usage:
 *   await mockApi(page, "populated");   // all endpoints return real fixture data
 *   await mockApi(page, "empty");       // empty portfolio state
 *   await mockSingleRoute(page, "/api/auth/me", "user-profile.json");
 */
import { Page } from "@playwright/test";
import path from "path";
import fs from "fs";
import { fileURLToPath } from "url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const FIXTURES_DIR = path.join(__dirname, "..", "fixtures");

function loadFixture(name: string): unknown {
  const filePath = path.join(FIXTURES_DIR, name);
  return JSON.parse(fs.readFileSync(filePath, "utf-8"));
}

/** Standard endpoint → fixture mapping for a populated portfolio */
const POPULATED_ROUTES: Record<string, string> = {
  "**/api/auth/me": "user-profile-onboarded.json",
  "**/api/auth/google-client-id": "google-client-id.json",
  "**/api/portfolio/holdings-enriched*": "holdings-enriched.json",
  "**/api/portfolio/holdings": "holdings.json",
  "**/api/portfolio/trend*": "portfolio-trend.json",
  "**/api/insights/analysis": "insights-analysis.json",
  "**/api/portfolio/exposure/concentration": "concentration.json",
  "**/api/intelligence/portfolio*": "intelligence-portfolio.json",
  "**/api/dashboards/performance*": "dashboards-performance.json",
  "**/api/dashboards/goals": "dashboards-goals.json",
  "**/api/goals": "goals.json",
  "**/api/dashboards/tax": "dashboards-tax.json",
  "**/api/plans/active": "plans-active.json",
  "**/api/copilot/suggested-prompts": "suggested-prompts.json",
  "**/api/portfolio/fund-performance*": "fund-performance.json",
  "**/api/portfolio/recommendations/v5*": "recommendations-v5.json",
  "**/api/dashboards/risk": "dashboards-risk.json",
  "**/api/onboarding/state": "onboarding-state.json",
  "**/api/user/risk-profile": "risk-profile.json",
  "**/api/portfolio/composition*": "composition.json",
};

/** Empty portfolio state — auth works but no holdings */
const EMPTY_ROUTES: Record<string, string> = {
  "**/api/auth/me": "user-profile-onboarded.json",
  "**/api/auth/google-client-id": "google-client-id.json",
  "**/api/portfolio/holdings-enriched*": "empty-portfolio.json",
  "**/api/portfolio/holdings": "empty-portfolio.json",
  "**/api/portfolio/trend*": "empty-portfolio.json",
  "**/api/insights/analysis": "empty-portfolio.json",
};

export type MockPreset = "populated" | "empty";

export async function mockApi(page: Page, preset: MockPreset = "populated") {
  const routes = preset === "empty" ? EMPTY_ROUTES : POPULATED_ROUTES;

  // Catch-all FIRST so it has lowest priority (Playwright runs handlers LIFO).
  // Any /api/* endpoint without an explicit fixture below resolves to 200 {}
  // instead of hitting Vite (no proxy in test config) and 404-hanging networkidle.
  await page.route(/\/\/[^/]+\/api\//, (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: "{}" }),
  );

  for (const [pattern, fixture] of Object.entries(routes)) {
    const data = loadFixture(fixture);
    await page.route(pattern, (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(data),
      }),
    );
  }
}

/** Mock a single API endpoint with a fixture file */
export async function mockSingleRoute(page: Page, urlPattern: string, fixture: string, status = 200) {
  const data = loadFixture(fixture);
  await page.route(urlPattern, (route) =>
    route.fulfill({
      status,
      contentType: "application/json",
      body: JSON.stringify(data),
    }),
  );
}

/** Mock API with a specific plans/active fixture — all routes in one page.route() batch. */
export async function mockApiWithPlan(page: Page, planFixture: string) {
  const planData = loadFixture(planFixture);
  const routes: Record<string, string> = {
    ...POPULATED_ROUTES,
    // Override plans/active with the provided fixture (do NOT add a second handler)
  };
  // Catch-all FIRST (lowest priority under LIFO) — see mockApi for rationale.
  await page.route(/\/\/[^/]+\/api\//, (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: "{}" }),
  );
  // Register all non-plan routes
  for (const [pattern, fixture] of Object.entries(routes)) {
    if (pattern === "**/api/plans/active") continue; // skip — we handle below
    const data = loadFixture(fixture);
    await page.route(pattern, (route) =>
      route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(data) }),
    );
  }
  // Register plan route once with the override fixture
  await page.route("**/api/plans/active", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(planData) }),
  );
}

/** Mock a single API endpoint returning 401 */
export async function mock401(page: Page, urlPattern: string) {
  await page.route(urlPattern, (route) =>
    route.fulfill({
      status: 401,
      contentType: "application/json",
      body: JSON.stringify({ detail: "Not authenticated" }),
    }),
  );
}

/** Mask volatile content in screenshots: ₹ values, scores, timers, charts */
export async function maskVolatile(page: Page) {
  await page.evaluate(() => {
    // Mask all SVG elements (charts, sparklines, treemap)
    document.querySelectorAll("svg").forEach((el) => {
      el.style.opacity = "0";
    });
    // Mask elements that show volatile numeric data
    document.querySelectorAll(".num, [class*='font-display']").forEach((el) => {
      if (el.textContent?.match(/[₹\d,.%]+/) && el.textContent.length < 20) {
        (el as HTMLElement).style.color = "transparent";
      }
    });
  });
}
