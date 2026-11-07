/**
 * Simulation studio · Scenario library (AD-UI-130..137). Test cases: docs/autodesk/ui_testcases/studio-scenarios.md.
 * The page reads nothing but the studio frame's GET /simulations (route mock: autodesk-fixtures-studio-scenarios.ts —
 * MOCK, shape of the real API). Scenario runs are Phase 3: the API refuses mode SCENARIO with 422, so nothing is sent.
 */
import { expect, test, type Page } from "@playwright/test";
import { collectConsoleErrors, mockDesk, reply, type RouteValue } from "./autodesk-mock";
import { SCEN_SID, SCEN_SIMS } from "./autodesk-fixtures-studio-scenarios";

async function openLib(page: Page, routes: Record<string, RouteValue> = { "GET /simulations": SCEN_SIMS }, path = `/autodesk/studio/scenarios?sim=${SCEN_SID}`) {
  const desk = await mockDesk(page, { routes });
  await page.goto(path);
  await expect(page.getByTestId("studio-scenarios")).toBeVisible();
  return desk;
}

test("AD-UI-130 header: planned kinds, nothing scheduled, the design's headline, Phase 3 sub line", async ({ page }) => {
  const errors = collectConsoleErrors(page);
  const desk = await openLib(page);
  const v = page.getByTestId("studio-scenarios");
  await expect(v.locator(".nv-eyebrow").first()).toHaveText("Scenario library");
  await expect(page.getByTestId("scen-count-pill")).toHaveText("16 planned kinds · 3 categories");
  await expect(page.getByTestId("scen-sched-pill")).toHaveText("Nothing scheduled · Phase 3");
  await expect(v.locator("h1")).toHaveText("Each scenario names the shock and the behaviour it must produce.");
  await expect(page.getByTestId("scen-sub")).toContainText("Scenario runs come in Phase 3");
  await expect(page.getByTestId("scen-sub")).toContainText("the desk API refuses a scenario run");
  await expect(page.getByTestId("scen-sub")).toContainText("nothing on this page is sent");
  expect(desk.unmatched).toEqual([]);
  expect(errors).toEqual([]);
});

test("AD-UI-131 schedule for the next run: 09:15 → 15:30 axis, nothing scheduled, Phase 3 note", async ({ page }) => {
  await openLib(page);
  const s = page.getByTestId("scen-schedule");
  await expect(s).toContainText("Schedule for the next run");
  await expect(s).toContainText("09:15 → 15:30");
  await expect(page.getByTestId("scen-tick")).toHaveText(["09:15", "10:15", "11:15", "12:15", "13:15", "14:15", "15:15"]);
  await expect(page.getByTestId("scen-schedule-empty")).toContainText("Nothing is scheduled.");
  await expect(page.getByTestId("scen-schedule-note")).toContainText("Phase 3");
  await expect(s).not.toContainText("Remove");
  await expect(s.locator('span[style*="rotate(45deg)"]')).toHaveCount(0);
});

test("AD-UI-132 library: Market, Execution, Operational; planned kinds from the PRD, no ids, severities or results", async ({ page }) => {
  await openLib(page);
  const cats = page.getByTestId("scen-cat");
  await expect(cats).toHaveCount(3);
  await expect(cats.locator(".nv-eyebrow")).toHaveText(["Market", "Execution", "Operational"]);
  const cards = page.getByTestId("scen-card");
  await expect(cards).toHaveCount(16);
  await expect(cats.nth(0).getByTestId("scen-card")).toHaveCount(5);
  await expect(cats.nth(1).getByTestId("scen-card")).toHaveCount(5);
  await expect(cats.nth(2).getByTestId("scen-card")).toHaveCount(6);
  await expect(cards.nth(0)).toContainText("PRD §31");
  await expect(cards.nth(0)).toContainText("PHASE 3");
  await expect(cards.nth(0)).toContainText("Sudden gap down");
  await expect(cards.nth(0)).toContainText("Risk is recalculated and only approved protective actions run.");
  await expect(cards.nth(0)).toContainText("PLANNED");
  await expect(cats.nth(2)).toContainText("LLM provider unavailable");
  await expect(cats.nth(2)).toContainText("PRD §20.1");
  for (let i = 0; i < 16; i++) await expect(cards.nth(i)).toContainText("PLANNED");
  const lib = await page.getByTestId("scen-library").innerText();
  expect(lib).not.toMatch(/SCN-\d|SIM-\d|\bHIGH\b|\bMEDIUM\b|PASS ·|FAIL ·|WARN ·/);
});

test("AD-UI-133 builder follows the selected kind; every control is disabled and nothing is sent", async ({ page }) => {
  const desk = await openLib(page);
  const b = page.getByTestId("scen-builder");
  await expect(b).toContainText("Builder · Phase 3");
  await expect(page.getByTestId("scen-builder-name")).toHaveText("Sudden gap down");
  await expect(page.getByTestId("scen-card").nth(0)).toHaveAttribute("aria-pressed", "true");
  await page.getByText("Broker disconnect", { exact: true }).click();
  await expect(page.getByTestId("scen-builder-name")).toHaveText("Broker disconnect");
  await expect(page.getByTestId("scen-builder-exp")).toHaveText("Unsafe new orders stop; the desk recovers and reconciles before going on.");
  await expect(page.getByTestId("scen-builder-check")).toHaveText("· Unsafe new orders stop; the desk recovers and reconciles before going on.");
  await page.getByTestId("scen-card").nth(5).focus();
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("scen-builder-name")).toHaveText("Partial fill when a position opens");
  const times = page.getByTestId("scen-times").locator("button");
  await expect(times).toHaveCount(7);
  for (let i = 0; i < 7; i++) await expect(times.nth(i)).toBeDisabled();
  const add = page.getByTestId("scen-add");
  await expect(add).toBeDisabled();
  await expect(add).toHaveText("Scenario runs come in Phase 3");
  await add.click({ force: true });
  await times.nth(0).click({ force: true });
  await page.waitForTimeout(300);
  expect(desk.posts).toEqual([]);
  expect(desk.requests.map((r) => `${r.method} ${r.path.split("?")[0]}`).filter((x) => x !== "GET /simulations")).toEqual([]);
});

test("AD-UI-134 'Replay a past session instead' opens New simulation and keeps ?sim=", async ({ page }) => {
  await openLib(page);
  await expect(page.getByTestId("scen-replay-link")).toHaveAttribute("href", `/autodesk/studio/new?sim=${SCEN_SID}`);
  await page.getByTestId("scen-replay-link").click();
  await expect(page).toHaveURL(new RegExp(`/autodesk/studio/new\\?sim=${SCEN_SID}$`));
  await expect(page.getByTestId("studio-new")).toBeVisible();
});

test("AD-UI-135 phone 390×844: one column, builder not sticky, no horizontal overflow", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await openLib(page);
  const lib = (await page.getByTestId("scen-library").boundingBox())!;
  const builder = (await page.getByTestId("scen-builder").boundingBox())!;
  expect(builder.y).toBeGreaterThan(lib.y + lib.height - 1);                    // builder below the library
  expect(Math.abs(builder.x - lib.x)).toBeLessThan(2);
  await expect(page.getByTestId("scen-builder")).toHaveCSS("position", "static");
  const c0 = (await page.getByTestId("scen-card").nth(0).boundingBox())!;
  const c1 = (await page.getByTestId("scen-card").nth(1).boundingBox())!;
  expect(c1.y).toBeGreaterThan(c0.y + c0.height - 1);                            // one card per row
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow).toBeLessThanOrEqual(0);
});

test("AD-UI-136 no sample ids or results, no forbidden words, no console errors", async ({ page }) => {
  const errors = collectConsoleErrors(page);
  const desk = await openLib(page);
  const text = await page.getByTestId("studio-scenarios").innerText();
  for (const s of ["SCN-0", "SCN-1", "SIM-0412", "SIM-0418", "SIM-0417", "PASS · ", "FAIL · RETRY BUDGET", "WARN · 2.4 s", "SCHEDULED 6 NOV", "−2%", "VIX +2.5"]) expect(text).not.toContain(s);
  expect(text).not.toMatch(/\b(buy|sell|stop[ -]?loss|targets?|entry|entries|accumulate|book profit|upside|price target|recommend\w*|pick\w*)\b/i);
  expect(text).not.toMatch(/\bSL\b/);
  expect(desk.unmatched).toEqual([]);
  expect(errors).toEqual([]);
});

test("AD-UI-137 the library needs no run data: it renders when GET /simulations fails", async ({ page }) => {
  await openLib(page, { "GET /simulations": reply(500, { error: "INTERNAL", message: "database unavailable" }) });
  await expect(page.getByTestId("scen-card")).toHaveCount(16);
  await expect(page.getByTestId("scen-schedule")).toBeVisible();
  await expect(page.getByTestId("scen-builder")).toBeVisible();
});
