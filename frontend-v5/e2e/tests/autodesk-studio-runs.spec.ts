/**
 * Simulation studio · Run history (AD-UI-140..148). Test cases: docs/autodesk/ui_testcases/studio-runs.md.
 * API answered by route mocks (autodesk-mock.ts + autodesk-fixtures-studio-runs.ts — MOCK, shapes of the real API).
 * The view sends no POST.
 */
import { expect, test, type Page } from "@playwright/test";
import { NOW, collectConsoleErrors, mockDesk, reply, type RouteValue } from "./autodesk-mock";
import { A, B, C, D, RESULTS, RUN_A, RUN_B, RUN_C, RUN_D, plans, runsRoutes, signals, workflows } from "./autodesk-fixtures-studio-runs";

const short = (id: string) => `${id.slice(0, 12)}…`;

async function open(page: Page, routes: Record<string, RouteValue>, path = "/autodesk/studio/runs") {
  await page.clock.setFixedTime(new Date(NOW));
  const desk = await mockDesk(page, { routes });
  await page.goto(path);
  await expect(page.getByTestId("studio-runs")).toBeVisible();
  return desk;
}

const measure = (page: Page, k: string) => page.getByTestId("runs-measure").filter({ has: page.locator(`span:text-is("${k}")`) });

test("AD-UI-140 runs table newest first, real columns, Phase notes, default A/B like for like", async ({ page }) => {
  const errors = collectConsoleErrors(page);
  const desk = await open(page, runsRoutes());
  await expect(page.getByTestId("runs-count")).toHaveText("3 runs · newest first");
  const table = page.getByTestId("runs-table");
  for (const h of ["A · B", "Run", "Type · session", "Policy · seed", "Status", "Trades", "Net P&L", "Max DD", "Assertions"]) await expect(table).toContainText(h);
  const rows = page.getByTestId("runs-row");
  await expect(rows).toHaveCount(3);
  await expect(rows.nth(0)).toHaveAttribute("data-sim", B);
  await expect(rows.nth(1)).toHaveAttribute("data-sim", A);
  await expect(rows.nth(2)).toHaveAttribute("data-sim", C);
  await expect(rows.nth(0)).toContainText(short(B));
  await expect(rows.nth(0)).toContainText("10:50");                       // created 05:20 UTC, today in IST
  await expect(rows.nth(0)).toContainText("Historical replay");
  await expect(rows.nth(0)).toContainText("2 Nov – 3 Nov");
  await expect(rows.nth(0)).toContainText("Desk default v2");
  await expect(rows.nth(0)).toContainText("SEED 42 · STEP");
  await expect(rows.nth(0).getByTestId("runs-status")).toHaveText("COMPLETE");
  await expect(rows.nth(1)).toContainText("Desk default v1");
  await expect(rows.nth(2)).toContainText("Accelerated replay");
  await expect(rows.nth(2)).toContainText("29 Oct – 30 Oct");
  await expect(rows.nth(2)).toContainText("SEED 7 · ACCELERATED");
  await expect(rows.nth(2)).toContainText("4 Nov 18:10");
  for (let i = 0; i < 3; i++) await expect(rows.nth(i).locator('span.nv-num:text-is("—")')).toHaveCount(4);
  const note = page.getByTestId("runs-table-note");
  await expect(note).toContainText("Trades, net P&L and max drawdown come from the run's simulated fills");
  await expect(note).toContainText("Runs made before paper execution show a dash");
  await expect(note).toContainText("Assertions come with scenarios (Phase 3)");
  await expect(note).not.toContainText(/Phase 2|need simulated fills/);
  await expect(page.getByTestId(`runs-b-${B}`)).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByTestId(`runs-a-${A}`)).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByTestId(`runs-a-${B}`)).toHaveAttribute("aria-pressed", "false");
  expect(desk.posts).toEqual([]);
  expect(desk.unmatched).toEqual([]);
  expect(errors).toEqual([]);
});

test("AD-UI-141 comparison of the like-for-like pair: measures from /results, rows not shown yet, chart note", async ({ page }) => {
  await open(page, runsRoutes());
  await expect(page.getByTestId("runs-cmp-title")).toHaveText(`${short(A)} (Desk default v1) against ${short(B)} (Desk default v2)`);
  await expect(page.getByTestId("runs-fair")).toHaveText("SAME SESSIONS · SAME SEED");
  await expect(page.getByTestId("runs-headline")).toHaveText(`${short(A)} against ${short(B)}: 6 differences in what the agents decided.`);
  const real: [string, string, string, string][] = [
    ["Signals", "7", "6", "−1"], ["Trade plans", "4", "4", "0"], ["Proposals rejected", "0", "0", "0"], ["Approved", "4", "3", "−1"],
    ["Human approvals", "0", "1", "+1"], ["Agent task failures", "0", "0", "0"], ["Policy violations", "0", "0", "0"],
  ];
  for (const [k, a, b, d] of real) await expect(measure(page, k).locator("span")).toHaveText([k, a, b, d]);
  for (const k of ["Trades", "Net P&L after costs", "Max drawdown", "Slippage paid"]) await expect(measure(page, k).locator("span")).toHaveText([k, "—", "—", "Not shown yet"]);
  await expect(measure(page, "Win rate").locator("span")).toHaveText(["Win rate", "—", "—", "Phase 3"]);
  await expect(measure(page, "Assertions").locator("span")).toHaveText(["Assertions", "—", "—", "Phase 3"]);
  await expect(page.getByTestId("runs-measure")).toHaveCount(13);
  await expect(page.getByTestId("runs-chart-note")).toHaveText("Not shown yetNet P&L through the session is not drawn here yet.");
  await expect(page.getByTestId("runs-compare")).not.toContainText("₹");
});

test("AD-UI-142 where the two runs decided differently — computed from both runs' records", async ({ page }) => {
  await open(page, runsRoutes());
  const diffs = page.getByTestId("runs-diff");
  await expect(diffs).toHaveCount(6);
  const want: [string, string, string][] = [
    ["2 Nov", "ADANIPORTS: A planned a bull call spread, B a bull put spread", "STRATEGY"],
    ["2 Nov", "GRASIM: A approved it, B sent it to a person", "OUTCOME"],
    ["2 Nov", "HINDALCO: only in B — B made no plan", "B ONLY"],
    ["3 Nov", "Signals: A found 3, B found 2", "−1"],
    ["3 Nov", "Signals only A found: DLF", "A ONLY"],
    ["3 Nov", "TATASTEEL: A's plan ended at v1, B's at v2", "REVISIONS"],
  ];
  for (let i = 0; i < want.length; i++) await expect(diffs.nth(i).locator("span")).toHaveText(want[i]);
});

test("AD-UI-143 picking a run on other sessions and seed: DIFFERENT INPUTS, no decision match", async ({ page }) => {
  await open(page, runsRoutes());
  await page.getByTestId(`runs-a-${C}`).click();
  await expect(page.getByTestId(`runs-a-${C}`)).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByTestId(`runs-a-${A}`)).toHaveAttribute("aria-pressed", "false");
  await expect(page.getByTestId("runs-fair")).toHaveText("DIFFERENT INPUTS");
  await expect(page.getByTestId("runs-headline")).toHaveText("These two runs are not like for like. Read the differences with care.");
  await expect(page.getByTestId("runs-diff")).toHaveCount(1);
  await expect(page.getByTestId("runs-diff")).toContainText("Different sessions: there is no decision-by-decision match to show.");
  await expect(measure(page, "Signals").locator("span")).toHaveText(["Signals", "12", "6", "−6"]);
  await expect(measure(page, "Proposals rejected").locator("span")).toHaveText(["Proposals rejected", "1", "0", "−1"]);
  await expect(measure(page, "Agent task failures").locator("span")).toHaveText(["Agent task failures", "1", "0", "−1"]);
  await page.getByTestId(`runs-b-${A}`).click();
  await expect(page.getByTestId("runs-cmp-title")).toContainText(`${short(C)} (Desk default v1) against ${short(A)} (Desk default v1)`);
});

test("AD-UI-144 same sessions and identical decisions: no differences", async ({ page }) => {
  await open(page, runsRoutes(undefined, {
    "GET /simulations/:sid/workflows": ((r: { params: Record<string, string> }) => workflows(r.params.sid === B ? A : r.params.sid)) as never,
    "GET /trade-plans": ((r: { query: URLSearchParams }) => plans(r.query.get("simulation_id") === B ? A : r.query.get("simulation_id") ?? "")) as never,
    "GET /signals": ((r: { query: URLSearchParams }) => signals(r.query.get("simulation_id") === B ? A : r.query.get("simulation_id") ?? "")) as never,
  }));
  await expect(page.getByTestId("runs-diff")).toHaveCount(1);
  await expect(page.getByTestId("runs-diff")).toContainText("No differences: on every session both runs found the same signals and made the same proposals with the same outcome.");
  await expect(page.getByTestId("runs-headline")).toHaveText(`${short(A)} against ${short(B)}: the same decisions on every shared session.`);
});

test("AD-UI-145 one run → a second run is needed; no runs → empty table and link", async ({ page }) => {
  await open(page, runsRoutes([RUN_A]));
  await expect(page.getByTestId("runs-row")).toHaveCount(1);
  await expect(page.getByTestId("runs-count")).toHaveText("1 run · newest first");
  await expect(page.getByTestId("runs-headline")).toHaveText("One run so far. A second run is needed to compare.");
  await expect(page.getByTestId("runs-cmp-empty")).toContainText("A second run is needed to compare.");
  await expect(page.getByTestId("runs-compare")).toHaveCount(0);
  await page.goto(`/autodesk/studio/runs?sim=${A}`);
  await expect(page.getByTestId("runs-new-link")).toHaveAttribute("href", `/autodesk/studio/new?sim=${A}`);

  await page.unrouteAll({ behavior: "ignoreErrors" });
  await mockDesk(page, { routes: runsRoutes([]) });
  await page.goto("/autodesk/studio/runs");
  await expect(page.getByTestId("runs-empty")).toContainText("No runs yet.");
  await expect(page.getByTestId("runs-headline")).toHaveText("No runs yet. Create one under New simulation.");
  await expect(page.getByTestId("runs-new-link")).toHaveAttribute("href", "/autodesk/studio/new");
});

test("AD-UI-146 load errors: the runs list, and one run's results", async ({ page }) => {
  await open(page, runsRoutes(undefined, { "GET /simulations": reply(500, { error: "INTERNAL", message: "simulation store unavailable" }) }));
  await expect(page.getByTestId("studio-runs").getByTestId("error-box")).toContainText("simulation store unavailable (500)", { timeout: 15000 });
  await expect(page.getByTestId("studio-runs").getByTestId("error-box")).toContainText("Could not load the runs");

  await page.unrouteAll({ behavior: "ignoreErrors" });
  await mockDesk(page, { routes: runsRoutes(undefined, {
    "GET /simulations/:sid/results": ((r: { params: Record<string, string> }) => (r.params.sid === B ? reply(500, { error: "INTERNAL", message: "results unavailable" }) : (runsRoutes()["GET /simulations/:sid/results"] as (x: unknown) => unknown)(r))) as never,
  }) });
  await page.goto("/autodesk/studio/runs");
  await expect(page.getByTestId("runs-row")).toHaveCount(3);
  await expect(page.getByTestId("runs-compare").getByTestId("error-box")).toContainText("results unavailable (500)", { timeout: 15000 });
  await expect(page.getByTestId("runs-compare").getByTestId("error-box")).toContainText(`Could not load the results of ${short(B)}`);
});

test("AD-UI-147 ?sim= picks B; a RUNNING run's counters come from /results", async ({ page }) => {
  const desk = await open(page, runsRoutes([RUN_D, RUN_B, RUN_A, RUN_C]), `/autodesk/studio/runs?sim=${A}`);
  await expect(page.getByTestId(`runs-b-${A}`)).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByTestId(`runs-a-${B}`)).toHaveAttribute("aria-pressed", "true");
  const running = page.getByTestId("runs-row").filter({ has: page.locator(`[data-testid="runs-b-${D}"]`) });
  await expect(running.getByTestId("runs-status")).toHaveText("RUNNING");
  await page.getByTestId(`runs-b-${D}`).click();
  await expect(page.getByTestId(`runs-a-${B}`)).toHaveAttribute("aria-pressed", "true");     // no like-for-like partner: the newest other run
  await expect(measure(page, "Signals").locator("span")).toHaveText(["Signals", "6", "3", "−3"]);
  await expect(page.getByTestId("runs-fair")).toHaveText("DIFFERENT INPUTS");
  expect(desk.requests.some((r) => r.path === `/simulations/${D}/results`)).toBe(true);
});

test("AD-UI-148 phone 390×844: no page overflow, comparison single column, no sample ids", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const errors = collectConsoleErrors(page);
  await open(page, runsRoutes());
  await expect(page.getByTestId("runs-diff")).toHaveCount(6);
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow).toBeLessThanOrEqual(0);
  const m = await page.getByTestId("runs-measures").boundingBox();
  const d = await page.getByTestId("runs-diffs").boundingBox();
  expect(m && d && d.y > m.y).toBeTruthy();
  const text = await page.getByTestId("studio-runs").innerText();
  for (const sample of ["SIM-0416", "SIM-0417", "SIM-0418", "P-PAPER", "SCN-0", "₹"]) expect(text).not.toContain(sample);
  expect(errors).toEqual([]);
});

// AD-P2-121: Trades, Net P&L and Max DD come from results.execution_summary of the run row (GET /simulations returns `results`).
// MOCK — not real data. The summary has the shape of backend/autodesk/execution/reports.py execution_summary (money as strings;
// max drawdown arrives as a negative amount).
test("AD-P2-121 Trades, Net P&L and Max DD come from results.execution_summary; a run without one shows the dash", async ({ page }) => {
  const errors = collectConsoleErrors(page);
  const withFills = (run: typeof RUN_B, id: string, summary: Record<string, unknown>) => ({ ...run, results: { ...(RESULTS[id] as object), execution_summary: summary } });
  const rowB = withFills(RUN_B, B, { trades: 3, net_pnl_rs: "-1470.00", max_drawdown_rs: "-2210.00", max_drawdown_pct: "-0.0221", seed: 42 });
  const rowA = withFills(RUN_A, A, { trades: 12, net_pnl_rs: "9888.40", max_drawdown_rs: "0", max_drawdown_pct: "0", seed: 42 });
  const rowC = { ...RUN_C, results: RESULTS[C] };                          // finished, results stored, made before paper execution: no summary
  const rowE = { ...RUN_A, simulation_id: "SIM-7a7a7a7a7a7a7a7a7a7a", results: { execution_summary: { trades: 2 } } };   // incomplete summary
  const desk = await open(page, runsRoutes([rowB, rowA, rowC, RUN_D, rowE]));
  const rows = page.getByTestId("runs-row");
  await expect(rows).toHaveCount(5);
  const cells = (sim: string) => { const r = page.locator(`[data-testid="runs-row"][data-sim="${sim}"]`); return { trades: r.getByTestId("runs-trades"), net: r.getByTestId("runs-net"), dd: r.getByTestId("runs-dd") }; };
  await expect(cells(B).trades).toHaveText("3");
  await expect(cells(B).net).toHaveText("−₹1,470");
  await expect(cells(B).dd).toHaveText("−₹2,210");
  await expect(cells(A).trades).toHaveText("12");
  await expect(cells(A).net).toHaveText("+₹9,888");
  await expect(cells(A).dd).toHaveText("₹0");
  // no summary (made before paper execution, still running, or incomplete): the dash, with the reason as its tooltip
  for (const sim of [C, D, rowE.simulation_id]) for (const c of Object.values(cells(sim))) {
    await expect(c).toHaveText("—");
    await expect(c).toHaveAttribute("title", /made before paper execution/);
  }
  // the Assertions cell is untouched: always the dash for Phase 3
  for (let i = 0; i < 5; i++) await expect(rows.nth(i).locator("span.nv-num").last()).toHaveText("—");
  expect(desk.posts).toEqual([]);
  expect(desk.unmatched).toEqual([]);
  expect(errors).toEqual([]);
});
