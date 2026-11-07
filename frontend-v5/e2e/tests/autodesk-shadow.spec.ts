/**
 * Shadow scores on the desk screens (AD-SC-37..43). Test cases: docs/autodesk/testcases_scoring_v21.md (Part B).
 * API answered by route mocks (autodesk-mock.ts + autodesk-fixtures-shadow.ts — // MOCK — not real data).
 * The browser clock is fixed at 11:42:30 IST on 5 Nov 2026 like the scanner spec.
 */
import { expect, test } from "@playwright/test";
import { NOW, collectConsoleErrors, mockDesk } from "./autodesk-mock";
import { SIG, scannerRoutes } from "./autodesk-fixtures-scanner";
import { BY_INST, sigId } from "./autodesk-fixtures-studio-trace";
import { shadowScannerRoutes, shadowTraceRoutes } from "./autodesk-fixtures-shadow";

const LABEL = "Shadow scoring — not used for selection";

test.beforeEach(async ({ page }) => {
  await page.clock.setFixedTime(new Date(NOW));
});

test("AD-SC-37 scanner rows show one shadow chip per version beside the unchanged v1 score; rows without shadow scores show none", async ({ page }) => {
  const errors = collectConsoleErrors(page);
  const base = await mockDesk(page, { routes: scannerRoutes() });
  await page.goto("/autodesk/scanner");
  await expect(page.getByTestId("signal-row").first()).toBeVisible();
  const order = await page.getByTestId("signal-row").getByTestId("row-instrument").allTextContents();
  const scores = await page.getByTestId("signal-row").getByTestId("row-score").allTextContents();
  expect(await page.getByTestId("shadow-chip").count()).toBe(0);                 // no shadow data stored → nothing drawn
  expect(base.unmatched).toEqual([]);

  const page2 = await page.context().newPage();
  await page2.clock.setFixedTime(new Date(NOW));
  const desk = await mockDesk(page2, { routes: shadowScannerRoutes() });
  await page2.goto("/autodesk/scanner");
  await expect(page2.getByTestId("signal-row").first()).toBeVisible();
  expect(await page2.getByTestId("signal-row").getByTestId("row-instrument").allTextContents()).toEqual(order);   // ranking unchanged
  expect(await page2.getByTestId("signal-row").getByTestId("row-score").allTextContents()).toEqual(scores);       // v1 scores unchanged
  const pet = page2.getByTestId("signal-row-PETRONET");
  await expect(pet.getByTestId("shadow-chip")).toHaveText(["v2 67.5 · Developing", "v2.1 77.5 · Strong"]);
  await expect(pet.getByTestId("shadow-chip").nth(0)).toHaveAttribute("data-version", "v2-positional");
  await expect(page2.getByTestId("signal-row-GRASIM").getByTestId("shadow-chip")).toHaveText(["v2 71.0 · Developing", "v2.1 not scored"]);
  await expect(page2.getByTestId("signal-row-ADANIPORTS").getByTestId("shadow-chip")).toHaveCount(0);
  expect(desk.unmatched).toEqual([]);
  expect(errors).toEqual([]);
});

test("AD-SC-38 expanded row: per version score, tier, signals, warnings and attributed components; v2.1 has no bearish penalty; not-scored shows its reason", async ({ page }) => {
  const errors = collectConsoleErrors(page);
  await mockDesk(page, { routes: shadowScannerRoutes() });
  await page.goto("/autodesk/scanner");
  await page.getByTestId("signal-row-PETRONET").getByTestId("signal-row").click();
  const sec = page.getByTestId("signal-row-PETRONET").getByTestId("shadow-section");
  await expect(sec).toContainText(LABEL);
  const v2 = sec.locator('[data-version="v2-positional"][data-testid="shadow-version"]');
  const v21 = sec.locator('[data-version="v21-positional"][data-testid="shadow-version"]');
  await expect(v2.getByTestId("shadow-score")).toHaveText("67.5 · Developing");
  await expect(v2).toContainText("TIER_2");
  await expect(v2).toContainText("Primary signal: setup a accumulation");
  await expect(v2.getByTestId("shadow-warnings")).toContainText("macd bear cross");
  await expect(v2.getByTestId("shadow-dim-bearish_warning")).toContainText("-10 / 10");
  await expect(v2.getByTestId("shadow-dim-signal_quality")).toContainText("24 / 45");
  await expect(v21.getByTestId("shadow-score")).toHaveText("77.5 · Strong");
  await expect(v21).toContainText("Primary signal: volume breakout");
  await expect(v21).toContainText("Context only: setup a accumulation");
  await expect(v21.getByTestId("shadow-warnings")).toContainText("macd bear cross");      // still listed
  await expect(v21.getByTestId("shadow-dim-bearish_warning")).toHaveCount(0);             // but costs nothing
  await expect(v21.getByTestId("shadow-dim-signal_quality")).toContainText("24 / 45");
  // the v1 breakdown is still there, unchanged
  await expect(page.getByTestId("signal-row-PETRONET").getByTestId("score-breakdown")).toContainText("Score breakdown");

  await page.getByTestId("signal-row-GRASIM").getByTestId("signal-row").click();
  const g = page.getByTestId("signal-row-GRASIM").locator('[data-version="v21-positional"][data-testid="shadow-version"]');
  await expect(g.getByTestId("shadow-score")).toHaveText("not scored");
  await expect(g.getByTestId("shadow-reason")).toHaveText("20-session average traded value below ₹5 crore");
  expect(errors).toEqual([]);
});

test("AD-SC-39 rows from before package 5 open as today and say no shadow score is stored", async ({ page }) => {
  const errors = collectConsoleErrors(page);
  await mockDesk(page, { routes: scannerRoutes() });
  await page.goto("/autodesk/scanner");
  await page.getByTestId("signal-row-ADANIPORTS").getByTestId("signal-row").click();
  await expect(page.getByTestId("signal-row-ADANIPORTS").getByTestId("shadow-none")).toHaveText("No shadow score stored with this signal.");
  await expect(page.getByTestId("signal-row-ADANIPORTS").getByTestId("score-breakdown")).toBeVisible();
  expect(errors).toEqual([]);
});

test("AD-SC-40 phone 390×844: chips and the section render in the card with no horizontal overflow", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await mockDesk(page, { routes: shadowScannerRoutes() });
  await page.goto("/autodesk/scanner");
  const card = page.getByTestId("signal-row-PETRONET");
  await expect(card.getByTestId("shadow-chip")).toHaveCount(2);
  await card.click();
  await expect(card.getByTestId("shadow-section")).toContainText(LABEL);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
});

test("AD-SC-41 Studio Agent trace: the signal step's payload lists each shadow score; other signals are unchanged", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  const ada = BY_INST.ADANIPORTS;
  await mockDesk(page, { routes: shadowTraceRoutes(sigId(ada)) });
  await page.goto("/autodesk/studio/trace");
  await expect(page.getByTestId("studio-trace")).toBeVisible();
  const payload = page.getByTestId("trace-payload");
  await expect(payload).toContainText("ADANIPORTS · NSE FUTURES");
  await expect(payload).toContainText("shadow v2-positional · shadow — not used for selection");
  await expect(payload).toContainText("v2 67.5 · Developing · TIER_2 · primary SETUP_A_ACCUMULATION");
  await expect(payload).toContainText("v2.1 77.5 · Strong · TIER_2 · primary VOLUME_BREAKOUT");
  // the same view without shadow data shows no shadow row
  const p2 = await page.context().newPage();
  await p2.emulateMedia({ reducedMotion: "reduce" });
  await mockDesk(p2, { routes: shadowTraceRoutes("SIG-none") });
  await p2.goto("/autodesk/studio/trace");
  await expect(p2.getByTestId("trace-payload")).toContainText("ADANIPORTS · NSE FUTURES");
  await expect(p2.getByTestId("trace-payload")).not.toContainText("shadow");
});
