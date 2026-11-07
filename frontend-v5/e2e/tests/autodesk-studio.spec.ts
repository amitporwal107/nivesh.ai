/**
 * Simulation studio — frame (AD-UI-100..107). Test cases: docs/autodesk/TESTCASES.md "Simulation studio — frame".
 * API answered by route mocks (autodesk-mock.ts — MOCK, shapes of the real API).
 */
import { expect, test } from "@playwright/test";
import { collectConsoleErrors, mockDesk, reply } from "./autodesk-mock";

// MOCK — not real data: two simulation rows in the shape of GET /simulations (store.list_simulations).
const SIM = (id: string, created: string, status = "COMPLETED") => ({
  simulation_id: id, tenant_id: "user_7f3a9c", name: `Replay ${id}`, mode: "HISTORICAL_REPLAY", status,
  config: { name: `Replay ${id}`, mode: "HISTORICAL_REPLAY", start_date: "2026-11-02", end_date: "2026-11-03", universe: "FNO", operating_mode: "AUTONOMOUS_PAPER", starting_capital_rs: 10000000, max_proposals_per_session: 5, seed: 42, speed: "STEP" },
  account_id: `ACC-${id}`, clock_sim_time: "2026-11-03T13:00:00Z", clock_session: "2026-11-03", clock_phase: "EOD", step_seq: 12,
  versions: null, results: null, error: null, created_by: "user_7f3a9c", created_at: created, started_at: created, ended_at: created, updated_at: created,
});
const SIMS = [SIM("SIM-1", "2026-11-05T04:00:00Z"), SIM("SIM-2", "2026-11-05T05:00:00Z")];

test("AD-UI-100 studio frame: header, isolation pill, five tabs, theme switch, link back to the desk", async ({ page }) => {
  const errors = collectConsoleErrors(page);
  await mockDesk(page, { routes: { "GET /simulations": SIMS } });
  await page.goto("/autodesk/studio");
  await expect(page.getByTestId("studio")).toBeVisible();
  await expect(page.locator("header")).toContainText("Simulation studio");
  await expect(page.locator("header")).toContainText("Nivesh · trading desk simulator");
  await expect(page.getByTestId("studio-isolation-pill")).toHaveText("Simulated · isolated · no broker route");
  const tabs = page.locator("header nav a");
  await expect(tabs).toHaveText(["Trading day", "New simulation", "Scenario library", "Run history", "Agent trace"]);
  await expect(page.getByTestId("studio-tab-day")).toHaveAttribute("aria-current", "page");
  await expect(page.getByTestId("studio-desk-link")).toHaveAttribute("href", "/autodesk/");
  await expect(page.locator("aside")).toHaveCount(0);
  expect(errors).toEqual([]);
});

test("AD-UI-101/102 tabs change the URL and view and keep ?sim=", async ({ page }) => {
  await mockDesk(page, { routes: { "GET /simulations": SIMS } });
  await page.goto("/autodesk/studio?sim=SIM-1");
  for (const [id, path] of [["new", "/studio/new"], ["scenarios", "/studio/scenarios"], ["runs", "/studio/runs"], ["trace", "/studio/trace"], ["day", "/studio"]] as const) {
    await page.getByTestId(`studio-tab-${id}`).click();
    await expect(page).toHaveURL(new RegExp(`/autodesk${path}\\?sim=SIM-1$`));
    await expect(page.getByTestId(`studio-tab-${id}`)).toHaveAttribute("aria-current", "page");
    await expect(page.getByTestId(`studio-${id}`)).toBeVisible();
  }
});

test("AD-UI-103 signed out shows the sign-in screen", async ({ page }) => {
  await mockDesk(page, { routes: { "GET /simulations": reply(401, { detail: "Not authenticated" }) } });
  await page.goto("/autodesk/studio");
  await expect(page.getByTestId("sign-in")).toBeVisible();
  await expect(page.getByTestId("studio")).toHaveCount(0);
});

test("AD-UI-104 theme switch is shared with the desk and kept", async ({ page }) => {
  await mockDesk(page, { routes: { "GET /simulations": SIMS } });
  await page.goto("/autodesk/studio");
  await expect(page.getByTestId("studio")).toHaveAttribute("data-theme", "dark");
  await page.getByTestId("studio-theme-light").click();
  await expect(page.getByTestId("studio")).toHaveAttribute("data-theme", "light");
  await page.reload();
  await expect(page.getByTestId("studio")).toHaveAttribute("data-theme", "light");
  await page.goto("/autodesk/");
  await expect(page.getByTestId("desk-desktop")).toHaveAttribute("data-theme", "light");
});

test("AD-UI-105 deep link + reload; unknown studio path goes to Trading day", async ({ page }) => {
  await mockDesk(page, { routes: { "GET /simulations": SIMS } });
  await page.goto("/autodesk/studio/trace");
  await expect(page.getByTestId("studio-trace")).toBeVisible();
  await page.reload();
  await expect(page.getByTestId("studio-trace")).toBeVisible();
  await page.goto("/autodesk/studio/nope");
  await expect(page).toHaveURL(/\/autodesk\/studio$/);
  await expect(page.getByTestId("studio-day")).toBeVisible();
});

test("AD-UI-106 phone: header wraps, tabs reachable, no horizontal overflow", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await mockDesk(page, { routes: { "GET /simulations": SIMS } });
  await page.goto("/autodesk/studio");
  await page.getByTestId("studio-tab-runs").click();
  await expect(page.getByTestId("studio-runs")).toBeVisible();
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow).toBeLessThanOrEqual(0);
});

test("AD-UI-107 desk routes still render inside the desk shell", async ({ page }) => {
  await mockDesk(page, { routes: { "GET /simulations": SIMS } });
  await page.goto("/autodesk/");
  await expect(page.getByTestId("desk-desktop")).toBeVisible();
  await expect(page.getByTestId("screen-overview")).toBeVisible();
  await page.goto("/autodesk/simulator");
  await expect(page.getByTestId("screen-sim")).toBeVisible();
  await expect(page.locator("aside")).toHaveCount(1);
});
