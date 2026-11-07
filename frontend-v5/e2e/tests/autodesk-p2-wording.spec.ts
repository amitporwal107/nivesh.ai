/**
 * AD-P2-120: with paper execution wired, no screen of the desk may say that the desk has no execution, that approved plans are
 * not filled, or that orders, fills and P&L "arrive with Phase 2". Test cases: docs/autodesk/TESTCASES.md, "Screen wording before merge".
 *
 * Each screen is opened with the same route mocks as its own spec (autodesk-mock.ts + autodesk-fixtures-*.ts — MOCK, shapes of the
 * real API). The visible text AND every tooltip (`title`) of the page are checked against what is no longer true. Text about stored
 * history is not checked: the outcome APPROVED_NO_EXECUTION of an older run is still read (AD-P2-118).
 */
import { expect, test, type Page } from "@playwright/test";
import { ACCOUNT_A, NOW, collectConsoleErrors, deskStatus, mockDesk, type MockState, type Req, type RouteValue } from "./autodesk-mock";
import { ACCOUNT_B, APR_ADANI, approvalsRoutes, world } from "./autodesk-fixtures-approvals";
import { setupRoutes } from "./autodesk-fixtures-studio-setup";
import { traceRoutes } from "./autodesk-fixtures-studio-trace";
import { runsRoutes } from "./autodesk-fixtures-studio-runs";
import { agentRoutes } from "./autodesk-fixtures-agents";
import { SID as SIM_SID, doneRoutes as simDoneRoutes } from "./autodesk-fixtures-simulator";
import { SID as DAY_SID, doneRoutes as dayDoneRoutes } from "./autodesk-fixtures-studio-day";
import { PREMARKET_OUTCOME } from "./autodesk-fixtures-overview";
import { POLICY_ROUTES, policyState } from "./autodesk-fixtures-policies";
import { scannerRoutes } from "./autodesk-fixtures-scanner";

/** Claims that were true of Phase 1 and are false once approved plans become simulated orders and fills. */
const STALE = new RegExp([
  "Phase 1 has no", "Phase 1 sends no orders", "Phase 1 run", "Phase 1 chain", "Phase 1 ends", "Phase 1 checks", "Phase 1 has one working control",
  "no orders in Phase 1", "no orders in this phase", "places no orders", "no orders, fills or", "no orders or positions", "there are no orders",
  "Nothing is executed", "nothing is executed", "Nothing was filled", "are not filled", "is not filled", "NO FILLS IN PHASE 1", "no fills in Phase 1",
  "none sent", "NO ORDERS IN PHASE 1", "no execution", "NO EXECUTION", "None in Phase 1", "no P&L yet", "no positions in Phase 1",
  "Phase 2", "PHASE 2", "needs? (simulated |paper )?(fills|execution|positions)", "reconciliation needs fills",
  "(arrive|arrives|come|comes) (with|in) (paper execution|Phase 2)", "Capital reservations arrive", "begin with paper fills",
].join("|"));

async function textOf(page: Page): Promise<string> {
  const body = await page.locator("body").innerText();
  const titles = await page.locator("[title]").evaluateAll((els) => els.map((e) => e.getAttribute("title") ?? ""));
  const labels = await page.locator("[aria-label]").evaluateAll((els) => els.map((e) => e.getAttribute("aria-label") ?? ""));
  return [body, ...titles, ...labels].join("\n");
}

async function expectClean(page: Page, what: string) {
  const text = await textOf(page);
  const hits = text.split("\n").filter((l) => STALE.test(l));
  expect(hits, `${what}: lines that are no longer true`).toEqual([]);
}

const status = (page: Page) => page.clock.setFixedTime(new Date(NOW));

test("AD-P2-120 approval detail: pending and decided", async ({ page }) => {
  const errors = collectConsoleErrors(page);
  await status(page);
  const w = world();
  await mockDesk(page, { routes: approvalsRoutes(w), state: { accounts: [{ ...ACCOUNT_A }, { ...ACCOUNT_B }], controls: [] } });
  await page.goto("/autodesk/approvals");
  await expect(page.getByTestId("screen-approvals")).toBeVisible();
  await expect(page.getByTestId("reservation-phase")).toHaveText("Capital is reserved when the plan goes to paper execution.");
  await expectClean(page, "approval detail (pending)");
  await page.goto(`/autodesk/approvals/${APR_ADANI.approval_id}`);
  await expect(page.getByTestId("decided-banner")).toContainText("Orders from here are paper only: nothing is sent to a broker.");
  await expectClean(page, "approval detail (decided)");
  expect(errors).toEqual([]);
});

test("AD-P2-120 Studio Setup: review row and Execution model note", async ({ page }) => {
  await mockDesk(page, { routes: setupRoutes() });
  await page.goto("/autodesk/studio/new");
  await expect(page.getByTestId("studio-new")).toBeVisible();
  await expect(page.getByTestId("setup-summary-row").filter({ hasText: "Execution" })).toContainText("Simulated fills · no broker");
  await expect(page.getByTestId("setup-execution-note")).toContainText("none is sent to a broker");
  await expectClean(page, "Studio Setup");
});

test("AD-P2-120 Studio Trace note and Run history notes", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await mockDesk(page, { routes: traceRoutes() });
  await page.goto("/autodesk/studio/trace");
  await expect(page.getByTestId("studio-trace")).toBeVisible();
  for (let i = 0; i < 5; i++) await page.getByTestId("trace-next").click();
  await expect(page.getByTestId("trace-phase2")).toBeVisible();
  await expectClean(page, "Studio Trace");
  await page.unrouteAll({ behavior: "ignoreErrors" });
  await mockDesk(page, { routes: runsRoutes() });
  await page.goto("/autodesk/studio/runs");
  await expect(page.getByTestId("studio-runs")).toBeVisible();
  await expect(page.getByTestId("runs-chart-note")).toBeVisible();
  await expectClean(page, "Run history");
});

test("AD-P2-120 Overview and Agents flows note", async ({ page }) => {
  await status(page);
  await mockDesk(page, { routes: { "GET /desk/status": (_r: Req, s: MockState) => deskStatus(s, { last_premarket: { session_date: "2026-11-05", outcome: PREMARKET_OUTCOME } }) } });
  await page.goto("/autodesk/");
  await expect(page.getByTestId("subline")).toContainText("this screen does not read them yet");
  await expectClean(page, "Overview");
  await page.unrouteAll({ behavior: "ignoreErrors" });
  await mockDesk(page, { routes: agentRoutes() });
  await page.goto("/autodesk/agents");
  await expect(page.getByTestId("flows-phase-note")).toBeVisible();
  await expectClean(page, "Agents");
});

for (const id of ["workbench", "trades", "pnl", "risk", "middle", "fleet"]) {
  test(`AD-P2-120 placeholder screen ${id}`, async ({ page }) => {
    await mockDesk(page);
    await page.goto(`/autodesk/${id}`);
    const s = page.getByTestId(`screen-${id}`);
    await expect(s).toBeVisible();
    await expect(s.getByTestId("phase2-note")).toContainText(/Not (shown|built) yet/);
    await expectClean(page, `placeholder ${id}`);
    // what Phase 2 did not build is never claimed as recorded: closing positions and realized P&L come with Phase 3
    await expect(s).not.toContainText(/realized P&L (is|are) recorded|stops (are|is) recorded/i);
  });
}

test("AD-P2-120 trades and P&L placeholders say Phase 3 for what Phase 2 did not build", async ({ page }) => {
  await mockDesk(page);
  await page.goto("/autodesk/trades");
  await expect(page.getByTestId("screen-trades")).toContainText("The desk records paper orders, fills and positions for approved plans, but this screen does not read them yet.");
  await expect(page.getByTestId("screen-trades")).toContainText("closes each position by its plan's rules");
  await page.goto("/autodesk/pnl");
  await expect(page.getByTestId("screen-pnl")).toContainText("realized P&L of closed positions");
  await page.goto("/autodesk/risk");
  await expect(page.getByTestId("screen-risk")).toContainText("Daily-loss, weekly-loss and drawdown limits act on paper P&L");
  await page.goto("/autodesk/middle");
  await expect(page.getByTestId("screen-middle")).toContainText("Orders of unknown state are reconciled by the desk.");
});

test("AD-P2-120 Simulator limitations, P&L note, counters and graph", async ({ page }) => {
  await status(page);
  await mockDesk(page, { routes: simDoneRoutes() });
  await page.goto(`/autodesk/simulator/${SIM_SID}`);
  await expect(page.getByTestId("screen-sim")).toBeVisible();
  await expect(page.getByTestId("sim-limitations")).toBeVisible();
  await expect(page.getByTestId("graph-node")).toHaveCount(13);
  await expectClean(page, "Simulator");
});

test("AD-P2-120 Studio Trading day", async ({ page }) => {
  await mockDesk(page, { routes: dayDoneRoutes() });
  await page.goto(`/autodesk/studio?sim=${DAY_SID}`);
  await expect(page.getByTestId("studio-day")).toBeVisible();
  await expect(page.getByTestId("day-pnl-note")).toBeVisible();
  await expectClean(page, "Studio Trading day");
});

test("AD-P2-120 Stop new entries dialog does not say there are no orders", async ({ page }) => {
  await mockDesk(page);
  await page.goto("/autodesk/");
  await page.getByTestId("stop-entries").click();
  const d = page.getByTestId("stop-dialog");
  await expect(d).toContainText("Paper orders that are still waiting do not fill while this is on, and they are not cancelled.");
  await expect(d).not.toContainText(/no orders|nothing is cancelled/i);
});

test("AD-P2-120 Policies: position-actions matrix and emergency controls", async ({ page }) => {
  await status(page);
  await mockDesk(page, {
    state: { policy: policyState() },
    routes: { "GET /desk/status": (_r: Req, s: MockState) => deskStatus(s, { last_premarket: { session_date: "2026-11-05", outcome: PREMARKET_OUTCOME } }), ...POLICY_ROUTES },
  });
  await page.goto("/autodesk/policies");
  await expect(page.getByTestId("screen-policies")).toBeVisible();
  await expect(page.getByTestId("matrix-phase-note")).toBeVisible();
  await expect(page.getByTestId("emergency")).toBeVisible();
  await expectClean(page, "Policies");
});

test("AD-P2-120 Scanner signal history note", async ({ page }) => {
  await status(page);
  await mockDesk(page, { routes: scannerRoutes() });
  await page.goto("/autodesk/scanner");
  await expect(page.getByTestId("history-phase-note")).toBeVisible();
  await expectClean(page, "Scanner");
});
