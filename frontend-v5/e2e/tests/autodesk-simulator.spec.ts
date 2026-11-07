/**
 * Desk web app — Simulator (AD-UI-60..69). Test cases: docs/autodesk/ui_testcases/simulator.md.
 * API answered by route mocks (autodesk-mock.ts + autodesk-fixtures-simulator.ts — MOCK, shapes of the real API).
 */
import fs from "node:fs";
import { expect, test, type Page } from "@playwright/test";
import { NOW, collectConsoleErrors, expectContract, mockDesk, reply, type RouteValue } from "./autodesk-mock";
import { LATEST_TP, NEW_SID, SID, liveRoutes, liveSim, mixedRoutes, doneRoutes, type LiveSim } from "./autodesk-fixtures-simulator";

async function openSim(page: Page, routes: Record<string, RouteValue>, path = `/autodesk/simulator/${SID}`) {
  await page.clock.setFixedTime(new Date(NOW));
  const desk = await mockDesk(page, { routes });
  await page.goto(path);
  await expect(page.getByTestId("screen-sim")).toBeVisible();
  return desk;
}

const simPosts = (desk: { posts: { method: string; path: string; body: unknown }[] }) => desk.posts.filter((p) => p.path.startsWith("/simulations"));

test("AD-UI-60 completed 2-session replay: header, clock, counters from /results, agents, limitations", async ({ page }) => {
  const errors = collectConsoleErrors(page);
  const desk = await openSim(page, doneRoutes());
  const s = page.getByTestId("screen-sim");
  await expect(s.getByText("10 · Trading desk simulator")).toBeVisible();
  await expect(s.getByText("Simulated · isolated · no broker route")).toBeVisible();
  await expect(page.getByTestId("sim-id-pill")).toHaveText(`${SID} · seed 42`);
  await expect(page.getByTestId("sim-headline")).toHaveText("Replayed 2 Nov – 3 Nov phase by phase. No order can reach a broker from here.");
  await expect(page.getByTestId("sim-status")).toHaveText("COMPLETED");
  await expect(page.getByTestId("sim-clock-time")).toHaveText("18:00:00");
  await expect(page.getByTestId("sim-clock")).toContainText("Simulation clock · Tue 3 Nov 2026");
  await expect(page.getByTestId("sim-step")).toHaveText("EOD · STEP 12 OF 12");
  await expect(page.getByTestId("sim-progress")).toHaveAttribute("style", /width: 100%/);
  const asof = page.getByTestId("sim-data-asof");
  await expect(asof).toContainText("CASH DATA AS OF");
  await expect(asof).toContainText("2 Nov");
  await expect(asof).toContainText("READY");
  await expect(asof).toContainText("CASH · FUTURES · OPTIONS");

  await expect(page.getByTestId("ctr-signals")).toContainText("476");
  await expect(page.getByTestId("ctr-signals")).toContainText("consumed 6 · expired 470");
  await expect(page.getByTestId("ctr-plans")).toContainText("6");
  await expect(page.getByTestId("ctr-plans")).toContainText("Bull call spread 3 · Bear put spread 3");
  await expect(page.getByTestId("ctr-risk")).toContainText("Risk & Operations · 6 completed · 0 failed");
  await expect(page.getByTestId("ctr-approvals")).toContainText("approved 6 · 6 by Middle Office");
  await expect(page.getByTestId("ctr-exceptions")).toContainText("1 retried · 0 pre-market blocked");
  await expect(page.getByTestId("ctr-violations")).toContainText("0");
  const p2 = page.getByTestId("ctr-p2");
  await expect(p2).toHaveCount(4);
  for (let i = 0; i < 4; i++) { await expect(p2.nth(i)).toContainText("—"); await expect(p2.nth(i)).not.toContainText("Phase 2"); }
  for (const i of [0, 1, 3]) await expect(p2.nth(i)).toContainText("Not shown here yet");
  await expect(p2.nth(2)).toContainText("Comes with Phase 3");

  const agents = page.getByTestId("sim-agent");
  await expect(agents).toHaveCount(5);
  await expect(agents.nth(0)).toContainText("AI Trader");
  await expect(agents.nth(0)).toContainText("238 signals from 224 instruments (101 suppressed or skipped)");
  await expect(agents.nth(0)).toContainText("2 TASKS · 2 COMPLETED · 0 FAILED · autodesk-ait-v1");
  await expect(agents.nth(3)).toContainText("Middle Office");
  await expect(agents.nth(3)).toContainText("APPROVED: within the autonomy rules of the policy; risk 0.44% of equity");
  await expect(page.getByTestId("sim-limitations")).toContainText("Daily-loss, weekly-loss and drawdown limits are not enforced: they act on P&L from Phase 3");
  await expect(page.getByTestId("sim-limitations")).not.toContainText("approved plans are not filled");
  await expect(page.getByTestId("sim-limitations").locator("li")).toHaveCount(8);
  await expect(page.getByTestId("badge-sim")).toHaveText("SIM");
  expect(desk.unmatched).toEqual([]);
  expect(errors).toEqual([]);
});

test("AD-UI-61 agent communication newest first, exceptions with recovery, dependency graph of the latest proposal", async ({ page }) => {
  await openSim(page, doneRoutes());
  const rows = page.getByTestId("comm-row");
  await expect(rows).toHaveCount(10);
  await expect(rows.nth(0)).toContainText("SIM CLOCK · STATE");
  await expect(rows.nth(0)).toContainText("RUNNING → COMPLETED");
  await expect(rows.nth(0)).toContainText("18:00");
  await expect(rows.nth(1)).toContainText("SIM CLOCK · CLOCK");
  await expect(rows.nth(1)).toContainText("Step 12 · 3 Nov · EOD");
  await expect(rows.nth(5)).toContainText("MIDDLE OFFICE → ORCHESTRATOR · REVIEW FOR APPROVAL · COMPLETED");
  await expect(rows.nth(5)).toContainText("APPROVED: within the autonomy rules of the policy; risk 0.44% of equity");
  await expect(rows.nth(5)).toContainText("09:00");
  await expect(rows.nth(6)).toContainText("MIDDLE OFFICE · APPROVED");
  await expect(rows.nth(6)).toContainText("APR-dlf1 · TRD-dlf1 v1 · within the autonomy rules of the policy; risk 0.44% of equity");
  await expect(rows.nth(6)).toContainText("09:00");                          // no sim_time: the phase it ran in
  await expect(rows.nth(7)).toContainText("RISK & OPERATIONS → MIDDLE OFFICE · HANDOFF");
  await page.getByTestId("comm-more").click();
  await expect(rows).toHaveCount(30);

  const ex = page.getByTestId("exception-row");
  await expect(ex).toHaveCount(1);
  await expect(ex.nth(0)).toContainText("Risk & Operations · Assess risk");
  await expect(ex.nth(0)).toContainText("RECOVERED");
  await expect(ex.nth(0)).toContainText("TimeoutError: the option chain read took 31 s (deadline 30 s)");
  await expect(page.getByTestId("sim-recon")).toHaveText("Not shown here yet · each finished run's results record a capital reconciliation");

  await expect(page.getByTestId("graph-wf-id")).toHaveText(`${LATEST_TP} · TRD-dlf1 v1 · APPROVED_NO_EXECUTION`);
  const nodes = page.getByTestId("graph-node");
  await expect(nodes).toHaveCount(13);
  await expect(nodes.nth(0)).toContainText("01 · DONE");
  await expect(nodes.nth(1)).toContainText("02 · DONE");
  await expect(nodes.nth(2)).toContainText("03 · DONE");
  await expect(nodes.nth(3)).toContainText("04 · NOT NEEDED");
  await expect(nodes.nth(4)).toContainText("05 · APPROVED");
  for (let i = 5; i < 13; i++) await expect(nodes.nth(i)).toContainText("NOT SHOWN YET");
  await expect(page.getByTestId("graph-wf").locator("option")).toHaveCount(6);
});

test("AD-UI-62 blocks the API cannot serve: notes, disabled controls, no sample figures", async ({ page }) => {
  await openSim(page, doneRoutes());
  await expect(page.getByTestId("pnl-phase-note")).toContainText("is not drawn here yet");
  await expect(page.getByTestId("pnl-phase-note")).not.toContainText("are not filled");
  await expect(page.getByTestId("policy-phase-note")).toContainText("Phase 4");
  await expect(page.getByTestId("policy-phase-note")).toContainText("This run used policy POL-1b7e93c4d05a4e2f9c61 v1");
  await expect(page.getByTestId("sim-policy")).toContainText("Policy v1 against a candidate");
  await expect(page.getByTestId("gate-phase-note")).toContainText("Live trading is not in scope for this desk");
  await expect(page.getByTestId("controls-note")).toContainText("Phase 3");
  await expect(page.getByTestId("sim-speeds").locator("button")).toHaveCount(4);
  for (const b of await page.getByTestId("sim-speeds").locator("button").all()) await expect(b).toBeDisabled();
  await expect(page.getByTestId("scenario-select")).toBeDisabled();
  await expect(page.getByTestId("sim-inject")).toBeDisabled();
  const s = page.getByTestId("screen-sim");
  for (const id of ["sim-pnl", "sim-policy", "sim-gate"]) await expect(page.getByTestId(id)).not.toContainText(/₹\s?\d/);
  await expect(s).not.toContainText(/SIM-0417|8841|18 of 20|P-PAPER|v8 CANDIDATE|AXISBANK|16,950/);
});

test("AD-UI-63 new simulation: defaults from the latest cash session, contract body, opens the new run", async ({ page }) => {
  const s = liveSim();
  const desk = await openSim(page, mixedRoutes(s), "/autodesk/simulator");
  await expect(page.getByTestId("sim-id-pill")).toContainText(SID);
  await page.getByTestId("new-sim").click();
  const dlg = page.getByTestId("new-sim-dialog");
  await expect(dlg).toBeVisible();
  await expect(page.getByTestId("new-start")).toHaveValue("2026-11-03");
  await expect(page.getByTestId("new-end")).toHaveValue("2026-11-04");
  await expect(page.getByTestId("new-capital")).toHaveValue("10000000");
  await page.getByTestId("new-create").click();
  await expect(dlg).toHaveCount(0);
  expectContract(simPosts(desk)[0], "simulator", "create", { start_date: "2026-11-03", end_date: "2026-11-04" });
  await expect(page).toHaveURL(new RegExp(`/autodesk/simulator/${NEW_SID}$`));
  await expect(page.getByTestId("sim-status")).toHaveText("NOT STARTED");
  await expect(page.getByTestId("sim-toggle")).toHaveText("Start");
  await expect(page.getByTestId("sim-toggle")).toBeEnabled();
  await expect(page.getByTestId("sim-step-phase")).toBeDisabled();

  await page.getByTestId("new-sim").click();
  await page.getByTestId("new-symbols").fill("petronet, GRASIM");
  await page.getByTestId("new-create").click();
  await expect(page.getByTestId("new-sim-dialog")).toHaveCount(0);
  expectContract(simPosts(desk)[1], "simulator", "create_symbols", { start_date: "2026-11-03", end_date: "2026-11-04" });
});

test("AD-UI-64 start, step phase, step session: contract bodies and the clock from the API", async ({ page }) => {
  const s = liveSim();
  const desk = await openSim(page, liveRoutes(s), `/autodesk/simulator/${NEW_SID}`);
  await expect(page.getByTestId("sim-step")).toHaveText("NO STEP YET · STEP 0 OF 12");
  await expect(page.getByTestId("sim-clock-time")).toHaveText("--:--:--");
  await page.getByTestId("sim-toggle").click();
  await expect(page.getByTestId("sim-status")).toHaveText("RUNNING");
  await expect(page.getByTestId("sim-toggle")).toHaveText("Pause");
  expectContract(simPosts(desk)[0], "simulator", "start", { simulation_id: NEW_SID });
  await page.getByTestId("sim-step-phase").click();
  await expect(page.getByTestId("sim-step")).toHaveText("PREMARKET · STEP 1 OF 12");
  await expect(page.getByTestId("sim-clock-time")).toHaveText("08:30:00");
  expectContract(simPosts(desk)[1], "simulator", "step_phase", { simulation_id: NEW_SID });
  await page.getByTestId("sim-step-session").click();
  await expect(page.getByTestId("sim-step")).toHaveText("EOD · STEP 6 OF 12");
  await expect(page.getByTestId("sim-clock-time")).toHaveText("18:00:00");
  await expect(page.getByTestId("sim-clock")).toContainText("Tue 3 Nov 2026");
  expectContract(simPosts(desk)[2], "simulator", "step_session", { simulation_id: NEW_SID });
});

test("AD-UI-65 run to end polls until COMPLETED; pause, resume, stop; accelerated start also runs", async ({ page }) => {
  let s: LiveSim = liveSim("HISTORICAL_REPLAY", "RUNNING");
  let desk = await openSim(page, liveRoutes(s), `/autodesk/simulator/${NEW_SID}`);
  await page.getByTestId("sim-run").click();
  expectContract(simPosts(desk)[0], "simulator", "run", { simulation_id: NEW_SID });
  await expect(page.getByTestId("sim-status")).toHaveText("COMPLETED", { timeout: 15000 });
  await expect(page.getByTestId("sim-step")).toHaveText("EOD · STEP 12 OF 12");
  expect(s.polls).toBeGreaterThanOrEqual(2);
  await expect(page.getByTestId("sim-toggle")).toHaveText("Finished");
  await expect(page.getByTestId("sim-toggle")).toBeDisabled();

  await page.unrouteAll({ behavior: "ignoreErrors" });
  s = liveSim();
  desk = await mockDesk(page, { routes: liveRoutes(s) });
  await page.goto(`/autodesk/simulator/${NEW_SID}`);
  await page.getByTestId("sim-toggle").click();                 // start
  await expect(page.getByTestId("sim-toggle")).toHaveText("Pause");
  await page.getByTestId("sim-toggle").click();                 // pause
  await expect(page.getByTestId("sim-status")).toHaveText("PAUSED");
  await expect(page.getByTestId("sim-toggle")).toHaveText("Resume");
  await page.getByTestId("sim-toggle").click();                 // resume
  await expect(page.getByTestId("sim-status")).toHaveText("RUNNING");
  await page.getByTestId("sim-stop").click();
  await expect(page.getByTestId("sim-status")).toHaveText("STOPPED");
  await expect(page.getByTestId("stopped-banner")).toContainText("The clock stays where it is and no further step runs; nothing outside the simulation was touched.");
  const posts = simPosts(desk);
  expectContract(posts[0], "simulator", "start", { simulation_id: NEW_SID });
  expectContract(posts[1], "simulator", "pause", { simulation_id: NEW_SID });
  expectContract(posts[2], "simulator", "resume", { simulation_id: NEW_SID });
  expectContract(posts[3], "simulator", "stop", { simulation_id: NEW_SID });
  for (const id of ["sim-toggle", "sim-stop", "sim-step-phase", "sim-step-session", "sim-run"]) await expect(page.getByTestId(id)).toBeDisabled();

  await page.unrouteAll({ behavior: "ignoreErrors" });
  s = liveSim("ACCELERATED_REPLAY");
  desk = await mockDesk(page, { routes: liveRoutes(s) });
  await page.goto(`/autodesk/simulator/${NEW_SID}`);
  await expect(page.getByTestId("sim-headline")).toContainText("accelerated");
  await page.getByTestId("sim-toggle").click();
  await expect(page.getByTestId("sim-status")).toHaveText("COMPLETED", { timeout: 15000 });
  expect(simPosts(desk).map((p) => p.path)).toEqual([`/simulations/${NEW_SID}/start`, `/simulations/${NEW_SID}/run`]);
});

test("AD-UI-66 action errors show the API's message and change nothing", async ({ page }) => {
  const s = liveSim("HISTORICAL_REPLAY", "RUNNING");
  await openSim(page, liveRoutes(s, {
    "POST /simulations/:sid/step": reply(409, { error: "CONFLICT", message: "simulation is PAUSED; it does not step" }),
    "POST /simulations/:sid/run": reply(409, { detail: "simulation is PAUSED; start or resume it first" }),
    "POST /simulations": reply(422, { error: "INVALID", message: "no trading sessions in the chosen date range" }),
  }), `/autodesk/simulator/${NEW_SID}`);
  await page.getByTestId("sim-step-phase").click();
  await expect(page.getByTestId("sim-action-error")).toHaveText("simulation is PAUSED; it does not step (409)");
  await expect(page.getByTestId("sim-step")).toHaveText("NO STEP YET · STEP 0 OF 12");
  await page.getByTestId("sim-run").click();
  await expect(page.getByTestId("sim-action-error")).toHaveText("simulation is PAUSED; start or resume it first (409)");
  await page.getByTestId("new-sim").click();
  await page.getByTestId("new-start").fill("2026-11-07");
  await page.getByTestId("new-end").fill("2026-11-08");
  await page.getByTestId("new-create").click();
  await expect(page.getByTestId("new-error")).toHaveText("no trading sessions in the chosen date range (422)");
  await expect(page.getByTestId("new-sim-dialog")).toBeVisible();
  await page.getByTestId("new-end").fill("2026-11-01");
  await expect(page.getByTestId("new-problems")).toContainText("an end date on or after the start date");
  await expect(page.getByTestId("new-create")).toBeDisabled();
});

test("AD-UI-67 Scenario and Live shadow chips explain the phase and send nothing; replay chips open the form", async ({ page }) => {
  const desk = await openSim(page, doneRoutes());
  await page.getByTestId("mode-SCENARIO").click();
  await expect(page.getByTestId("mode-note")).toContainText("Phase 3");
  await expect(page.getByTestId("mode-note")).toContainText("the API refuses SCENARIO runs today");
  await page.getByTestId("mode-LIVE_SHADOW").click();
  await expect(page.getByTestId("mode-note")).toContainText("Phase 4");
  await expect(page.getByTestId("mode-note")).toContainText("the API refuses LIVE_SHADOW runs today");
  expect(desk.posts).toEqual([]);
  await page.getByTestId("mode-ACCELERATED_REPLAY").click();
  await expect(page.getByTestId("new-sim-dialog")).toContainText("Start runs it to the end in the background");
  await expect(page.getByTestId("mode-note")).toHaveCount(0);
});

test("AD-UI-68 no simulations, list error, unknown simulation", async ({ page }) => {
  await openSim(page, doneRoutes({ "GET /simulations": [] }), "/autodesk/simulator");
  await expect(page.getByTestId("sim-empty")).toBeVisible();
  await expect(page.getByTestId("sim-clock")).toHaveCount(0);
  await expect(page.getByTestId("screen-sim")).not.toContainText(/₹\s?\d/);

  await page.unrouteAll({ behavior: "ignoreErrors" });
  await mockDesk(page, { routes: doneRoutes({ "GET /simulations": reply(500, { error: "INTERNAL", message: "database unavailable" }) }) });
  await page.goto("/autodesk/simulator");
  await expect(page.getByTestId("error-box").first()).toContainText("database unavailable (500)", { timeout: 15000 });

  await page.unrouteAll({ behavior: "ignoreErrors" });
  await mockDesk(page, { routes: doneRoutes() });
  await page.goto("/autodesk/simulator/SIM-00000000000000000000");
  await expect(page.getByTestId("error-box")).toContainText("not found: SIM-00000000000000000000 (404)");
  await expect(page.getByTestId("sim-clock")).toHaveCount(0);
});

test("AD-UI-69 phone 390×844: single column, no overflow; Export downloads the results JSON", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const other: string[] = [];
  page.on("request", (r) => {
    const u = new URL(r.url());
    if (/fonts\.(googleapis|gstatic)\.com/.test(u.host)) return;
    if (u.pathname.startsWith("/autodesk/") || u.pathname === "/api/auth/me" || u.pathname === "/api/live/quotes") return;
    other.push(u.pathname);
  });
  const errors = collectConsoleErrors(page);
  await openSim(page, doneRoutes());
  await expect(page.getByTestId("ctr-signals")).toContainText("476");
  await expect(page.getByTestId("graph-node")).toHaveCount(13);
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow).toBeLessThanOrEqual(0);
  const [download] = await Promise.all([page.waitForEvent("download"), page.getByTestId("sim-export").click()]);
  expect(download.suggestedFilename()).toBe(`${SID}-results.json`);
  const data = JSON.parse(fs.readFileSync((await download.path())!, "utf8"));
  expect(data.simulation.simulation_id).toBe(SID);
  expect(data.results.signals.total).toBe(476);
  expect(data.results.limitations).toHaveLength(8);
  expect(other).toEqual([]);
  expect(errors).toEqual([]);
});
