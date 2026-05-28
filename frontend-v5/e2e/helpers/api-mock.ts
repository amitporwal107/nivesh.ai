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
  "**/api/auth/me": "user-profile.json",
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
};

/** Empty portfolio state — auth works but no holdings */
const EMPTY_ROUTES: Record<string, string> = {
  "**/api/auth/me": "user-profile.json",
  "**/api/auth/google-client-id": "google-client-id.json",
  "**/api/portfolio/holdings-enriched*": "empty-portfolio.json",
  "**/api/portfolio/holdings": "empty-portfolio.json",
  "**/api/portfolio/trend*": "empty-portfolio.json",
  "**/api/insights/analysis": "empty-portfolio.json",
};

export type MockPreset = "populated" | "empty";

export async function mockApi(page: Page, preset: MockPreset = "populated") {
  const routes = preset === "empty" ? EMPTY_ROUTES : POPULATED_ROUTES;

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
