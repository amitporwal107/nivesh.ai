/**
 * Simulation studio · Trading day (AD-UI-110..119). Test cases: docs/autodesk/ui_testcases/studio-day.md.
 * API answered by route mocks (autodesk-mock.ts + autodesk-fixtures-studio-day.ts — MOCK, shapes of the real API).
 */
import { expect, test, type Page } from "@playwright/test";
import { collectConsoleErrors, expectContract, mockDesk, reply, type RouteValue } from "./autodesk-mock";
import { NEW_SID, OTHER_SID, SID, SIM_DONE, doneRoutes, liveRoutes, liveRun, type Live } from "./autodesk-fixtures-studio-day";

async function openDay(page: Page, routes: Record<string, RouteValue>, path = `/autodesk/studio?sim=${SID}`) {
  const desk = await mockDesk(page, { routes });
  await page.goto(path);
  await expect(page.getByTestId("studio-day")).toBeVisible();
  return desk;
}

const simPosts = (desk: { posts: { method: string; path: string; body: unknown }[] }) => desk.posts.filter((p) => p.path.startsWith("/simulations"));
const ctr = (page: Page, id: string) => page.getByTestId(`day-ctr-${id}`);
const IST_OF_STEP = ["08:30:00", "08:45:00", "09:00:00", "09:15:00", "15:30:00", "18:00:00"];

test("AD-UI-110 completed 2-session replay: header, headline, clock card and the shown day's counters", async ({ page }) => {
  const errors = collectConsoleErrors(page);
  const desk = await openDay(page, doneRoutes());
  await expect(page.getByTestId("day-eyebrow")).toHaveText(`Full trading day · ${SID}`);
  await expect(page.getByTestId("day-mode-pill")).toHaveText("Historical replay · Tue 3 Nov 2026 · session 2 of 2");
  await expect(page.getByTestId("day-name-pill")).toHaveText("Replay 2–3 Nov");
  await expect(page.getByTestId("day-policy-pill")).toHaveText("POL-1b7e93c4d05a4e2f9c61 v1 · seed 42");
  await expect(page.getByTestId("day-headline")).toHaveText("The bell has rung. Every session of this run is replayed.");
  await expect(page.getByTestId("day-status")).toHaveText("COMPLETE");
  await expect(page.getByTestId("day-clock-time")).toHaveText("18:00:00");
  await expect(page.getByTestId("day-phase")).toHaveText("End of day · Tue 3 Nov 2026 · step 12 of 12");
  await expect(page.getByTestId("day-phase-note")).toContainText("Unused signals and unanswered approvals of the session expire");

  await expect(ctr(page, "signals")).toContainText("5");
  await expect(ctr(page, "plans")).toContainText("3");
  await expect(ctr(page, "risk")).toContainText("3");
  await expect(ctr(page, "approvals")).toContainText("3");
  await expect(ctr(page, "recovered")).toContainText("1");
  for (const [id, ph] of [["fills", "2"], ["exits", "3"], ["shocks", "3"]]) {
    await expect(ctr(page, id)).toContainText("—");
    await expect(ctr(page, id)).toContainText(`PHASE ${ph}`);
  }
  expect(desk.unmatched).toEqual([]);
  expect(errors).toEqual([]);
});

test("AD-UI-111 agent lanes: bands, nine lanes, dots where agents acted, Phase 2/3 lanes, session switch", async ({ page }) => {
  await openDay(page, doneRoutes());
  await expect(page.getByTestId("day-lanes")).toContainText("08:00 → 18:30 · click the track to jump");
  const bands = page.getByTestId("day-band");
  await expect(bands).toHaveCount(5);
  await expect(bands).toHaveText(["PRE-MARKET08:00", "PRE-OPEN09:00", "INTRADAY09:15", "CLOSE AND POST-CLOSE15:30", "EVENING18:00"]);
  const lanes = page.getByTestId("day-lane");
  await expect(lanes).toHaveCount(9);
  const names = ["AI Trader", "Trading Assistant", "Risk & Operations", "Middle Office", "Tech Support", "Lifecycle manager", "Sim exchange", "Orchestrator", "Scenarios"];
  for (let i = 0; i < 9; i++) await expect(lanes.nth(i)).toContainText(names[i]);
  await expect(page.locator('[data-testid="day-lane"][data-lane="tlm"]')).toContainText("PHASE 3");
  await expect(page.locator('[data-testid="day-lane"][data-lane="exec"]')).toContainText("PHASE 2");
  await expect(page.locator('[data-testid="day-lane"][data-lane="scn"]')).toContainText("PHASE 3");
  for (const l of ["tlm", "exec", "scn"]) await expect(page.locator(`[data-testid="day-dot"][data-lane="${l}"]`)).toHaveCount(0);

  const dot = (lane: string) => page.locator(`[data-testid="day-dot"][data-lane="${lane}"]`);
  await expect(dot("trader")).toHaveCount(1);
  await expect(dot("trader")).toHaveAttribute("data-phase", "SCAN");
  await expect(dot("ops")).toHaveAttribute("data-phase", "PREMARKET");
  await expect(dot("strat")).toHaveAttribute("data-phase", "PROPOSALS");
  await expect(dot("risk")).toHaveAttribute("data-tone", "amber");                 // the retried risk task
  await expect(dot("mo")).toHaveAttribute("data-tone", "amber");                   // waiting on a person
  await expect(dot("orch")).toHaveCount(6);
  await expect(dot("risk")).toHaveAttribute("title", "09:00 · Proposals · 7 events");
  await expect(page.getByTestId("day-dot-scheduled")).toHaveCount(0);
  await expect(page.getByTestId("day-cursor")).toContainText("18:00");
  const legend = page.getByTestId("day-legend");
  for (const t of ["DECISION", "CLOCK · RUN STATE", "INJECTED SCENARIO · PHASE 3", "FAILED · BLOCKED", "FAINT = SCHEDULED, NOT YET REACHED"]) await expect(legend).toContainText(t);

  await page.getByTestId("day-session").selectOption("2026-11-02");
  await expect(page.getByTestId("day-mode-pill")).toHaveText("Historical replay · Mon 2 Nov 2026 · session 1 of 2");
  await expect(ctr(page, "signals")).toContainText("6");
  await expect(ctr(page, "plans")).toContainText("2");
  await expect(ctr(page, "approvals")).toContainText("2");
  await expect(ctr(page, "recovered")).toContainText("0");
  await expect(dot("risk")).toHaveAttribute("data-tone", "mint");
  await expect(page.getByTestId("day-cursor")).toHaveCount(0);                      // the clock is on 3 Nov
  // the clock card stays on the run's clock
  await expect(page.getByTestId("day-clock-time")).toHaveText("18:00:00");
});

test("AD-UI-112 event feed newest first; Jump to and the track filter it by phase", async ({ page }) => {
  await openDay(page, doneRoutes());
  const rows = page.getByTestId("day-feed-row");
  await expect(rows).toHaveCount(10);
  await expect(rows.nth(0)).toContainText("SIM CLOCK · STATE");
  await expect(rows.nth(0)).toContainText("RUNNING → COMPLETED");
  await expect(rows.nth(0)).toContainText("18:00");
  await expect(rows.nth(1)).toContainText("Step 12 · 3 Nov · EOD");
  await expect(rows.nth(2)).toContainText("SESSION CLOSE · APPROVAL EXPIRED");
  await expect(rows.nth(2)).toContainText("APR-dlf1x · TRD-dlf1 v1 · the approval window closed at the session close");
  await expect(rows.nth(3)).toContainText("SESSION CLOSE · SIGNAL EXPIRED ×2");
  await expect(rows.nth(3)).toContainText("2 signals · session closed");
  await expect(rows.nth(4)).toContainText("Step 11 · 3 Nov · CLOSE");
  await expect(rows.nth(4)).toContainText("15:30");
  await expect(page.getByTestId("day-feed-count")).toContainText("85 EVENTS READ · 45 ROWS ON THIS DAY");
  await page.getByTestId("day-feed-more").click();
  await expect(rows).toHaveCount(30);

  await page.getByTestId("day-jump-PROPOSALS").click();
  await expect(page.getByTestId("day-jump-PROPOSALS")).toHaveAttribute("aria-pressed", "true");
  await expect(rows).toHaveCount(10);
  await expect(page.getByTestId("day-feed-count")).toContainText("29 ROWS IN THIS PHASE");
  await expect(rows.nth(0)).toContainText("Step 9 · 3 Nov · PROPOSALS");
  await expect(rows.nth(1)).toContainText("MIDDLE OFFICE → ORCHESTRATOR · REVIEW FOR APPROVAL · COMPLETED");
  await expect(rows.nth(1)).toContainText("NEEDS_HUMAN_APPROVAL: notional above the autonomous threshold of the policy");   // agent text as written
  await expect(rows.nth(2)).toContainText("MIDDLE OFFICE · NEEDS HUMAN APPROVAL");
  for (let i = 0; i < 10; i++) await expect(rows.nth(i)).toContainText("09:00");
  await expect(page.getByTestId("day-track-selected")).toHaveCount(1);
  await page.getByTestId("day-jump-PROPOSALS").click();                              // toggles back to the whole day
  await expect(page.getByTestId("day-feed-count")).toContainText("45 ROWS ON THIS DAY");

  await page.getByTestId("day-jump-SCAN").click();
  await expect(rows).toHaveCount(7);
  await expect(rows.nth(1)).toContainText("AI TRADER → ORCHESTRATOR · SCAN MARKET · COMPLETED");
  await expect(rows.nth(1)).toContainText("5 signals from 212 instruments (31 suppressed or skipped)");
  await expect(rows.nth(2)).toContainText("AI TRADER · SIGNAL");
  await page.getByTestId("day-jump-all").click();

  // clicking the track at 09:15 jumps to the Open phase
  const track = page.getByTestId("day-track");
  const box = (await track.boundingBox())!;
  const f = (9.25 * 3600 - 8 * 3600) / (10.5 * 3600);
  await track.click({ position: { x: 142 + (box.width - 142) * f, y: 20 } });
  await expect(page.getByTestId("day-jump-OPEN")).toHaveAttribute("aria-pressed", "true");
  await expect(rows).toHaveCount(1);
  await expect(rows.nth(0)).toContainText("Step 10 · 3 Nov · OPEN");
});

test("AD-UI-113 Phase 2 blocks, End of day from the run's events, Compare and Trace links", async ({ page }) => {
  await openDay(page, doneRoutes());
  await expect(page.getByTestId("day-pnl")).toContainText("Net P&L, simulated");
  await expect(page.getByTestId("day-pnl")).toContainText("NO FILLS IN PHASE 1");
  await expect(page.getByTestId("day-pnl-note")).toContainText("Phase 2");
  await expect(page.getByTestId("day-positions-note")).toContainText("Phase 2");
  await expect(page.getByTestId("day-pnl")).not.toContainText("₹");
  await expect(page.getByTestId("day-positions")).not.toContainText("₹");
  await expect(page.locator('[data-testid="day-pnl"] svg')).toHaveCount(0);

  await expect(page.getByTestId("day-eod-status")).toHaveText("RUN COMPLETE");
  for (const [id, ph] of [["orders", 2], ["gross", 2], ["net", 2], ["drawdown", 2], ["assertions", 3]] as const) {
    await expect(page.getByTestId(`day-eod-${id}`)).toContainText("—");
    await expect(page.getByTestId(`day-eod-${id}`)).toContainText(`PHASE ${ph}`);
  }
  await expect(page.getByTestId("day-eod-violations")).toHaveText("Policy violations · whole run0");
  await expect(page.getByTestId("day-eod-signals-expired")).toHaveText("Signals expired at the close2");
  await expect(page.getByTestId("day-eod-approvals-expired")).toHaveText("Approvals expired at the close1");
  await page.getByTestId("day-session").selectOption("2026-11-02");
  await expect(page.getByTestId("day-eod-status")).toHaveText("SESSION CLOSED");
  await expect(page.getByTestId("day-eod-signals-expired")).toHaveText("Signals expired at the close4");
  await expect(page.getByTestId("day-eod-approvals-expired")).toHaveText("Approvals expired at the close0");

  await expect(page.getByTestId("day-compare")).toHaveText("Compare with other runs");
  await page.getByTestId("day-compare").click();
  await expect(page).toHaveURL(new RegExp(`/autodesk/studio/runs\\?sim=${SID}$`));
  await expect(page.getByTestId("studio-runs")).toBeVisible();
  await page.goBack();
  await page.getByTestId("day-trace").click();
  await expect(page).toHaveURL(new RegExp(`/autodesk/studio/trace\\?sim=${SID}$`));
  await expect(page.getByTestId("studio-trace")).toBeVisible();
});

test("AD-UI-113b only one run: Compare is disabled and says there is no other run", async ({ page }) => {
  await openDay(page, doneRoutes({}, [SIM_DONE]));
  await expect(page.getByTestId("day-compare")).toBeDisabled();
  await expect(page.getByTestId("day-compare")).toHaveText("No other run to compare");
  await expect(page.locator("body")).not.toContainText(OTHER_SID);
});

test("AD-UI-114 Play / Pause send the lifecycle contracts (start + run, pause, resume + run)", async ({ page }) => {
  const live: Live = liveRun("CREATED");
  const desk = await openDay(page, liveRoutes(live), `/autodesk/studio?sim=${NEW_SID}`);
  await expect(page.getByTestId("day-status")).toHaveText("NOT STARTED");
  await expect(page.getByTestId("day-headline")).toHaveText("Desk replay is ready to replay 2 Nov – 3 Nov. No order can leave the simulator.");
  await expect(page.getByTestId("day-phase")).toHaveText("Not started · step 0 of 12");
  await expect(page.getByTestId("day-clock-time")).toHaveText("--:--:--");
  await expect(page.getByTestId("day-dot-scheduled")).toHaveCount(6);
  await expect(page.getByTestId("day-jump-PREMARKET")).toBeDisabled();
  await expect(page.getByTestId("day-toggle")).toHaveText("Play");

  await page.getByTestId("day-toggle").click();
  await expect(page.getByTestId("day-toggle")).toHaveText("Pause");
  await expect(page.getByTestId("day-status")).toHaveText("RUNNING");
  let posts = simPosts(desk);
  expectContract(posts[0], "studio-day", "start", { simulation_id: NEW_SID });
  expectContract(posts[1], "studio-day", "run", { simulation_id: NEW_SID });

  await page.getByTestId("day-toggle").click();
  await expect(page.getByTestId("day-status")).toHaveText("PAUSED");
  await expect(page.getByTestId("day-toggle")).toHaveText("Play");
  posts = simPosts(desk);
  expectContract(posts[2], "studio-day", "pause", { simulation_id: NEW_SID });

  await page.getByTestId("day-toggle").click();
  await expect(page.getByTestId("day-toggle")).toHaveText("Pause");
  posts = simPosts(desk);
  expectContract(posts[3], "studio-day", "resume", { simulation_id: NEW_SID });
  expectContract(posts[4], "studio-day", "run", { simulation_id: NEW_SID });
  expect(posts).toHaveLength(5);
  expect(desk.unmatched).toEqual([]);
});

test("AD-UI-115 controls without an API are disabled; a 409 shows the API's message; stopped and failed banners", async ({ page }) => {
  await openDay(page, doneRoutes());
  await expect(page.getByTestId("day-toggle")).toHaveText("Day done");
  await expect(page.getByTestId("day-toggle")).toBeDisabled();
  await expect(page.getByTestId("day-restart")).toBeDisabled();
  const speeds = page.getByTestId("day-speeds").locator("button");
  await expect(speeds).toHaveText(["60×", "120×", "300×", "600×"]);
  for (let i = 0; i < 4; i++) await expect(speeds.nth(i)).toBeDisabled();
  await expect(page.getByTestId("day-controls-note")).toContainText("Phase 3");
  await expect(page.getByTestId("day-controls-note")).toContainText("moves one phase at a time");

  // RUNNING but not playing in the background: Play sends run; the API answers 409
  const live = liveRun("RUNNING", 3);
  const desk = await mockDesk(page, { routes: liveRoutes(live, { "POST /simulations/:sid/run": reply(409, { detail: "simulation is PAUSED; start or resume it first" }) }) });
  await page.goto(`/autodesk/studio?sim=${NEW_SID}`);
  await expect(page.getByTestId("day-clock-time")).toHaveText("09:00:00");
  await expect(page.getByTestId("day-headline")).toContainText("Before the bell: the desk loads its world.");
  await expect(page.getByTestId("day-headline")).toContainText("6 signals and 2 plans so far; no order can leave the simulator.");
  await expect(page.getByTestId("day-dot-scheduled")).toHaveCount(3);
  await page.getByTestId("day-toggle").click();
  await expect(page.getByTestId("day-action-error")).toHaveText("simulation is PAUSED; start or resume it first (409)");
  await expect(page.getByTestId("day-status")).toHaveText("RUNNING");
  expect(simPosts(desk).map((p) => p.path)).toEqual([`/simulations/${NEW_SID}/run`]);

  const stopped = liveRun("STOPPED", 4);
  await mockDesk(page, { routes: liveRoutes(stopped) });
  await page.goto(`/autodesk/studio?sim=${NEW_SID}`);
  await expect(page.getByTestId("day-stopped")).toContainText("Stopped at 09:15:00 on Mon 2 Nov 2026 (OPEN, step 4 of 12)");
  await expect(page.getByTestId("day-toggle")).toHaveText("Stopped");
  await expect(page.getByTestId("day-toggle")).toBeDisabled();
  await expect(page.getByTestId("day-headline")).toContainText("The run was stopped here; no further step runs.");

  const failed = liveRun("FAILED", 2);
  failed.row.error = "2026-11-02 SCAN: RuntimeError: cash EOD for 2026-10-30 missing";
  await mockDesk(page, { routes: liveRoutes(failed) });
  await page.goto(`/autodesk/studio?sim=${NEW_SID}`);
  await expect(page.getByTestId("day-failed")).toContainText("2026-11-02 SCAN: RuntimeError: cash EOD for 2026-10-30 missing");
  await expect(page.getByTestId("day-toggle")).toHaveText("Failed");
});

test("AD-UI-116 empty and failing loads", async ({ page }) => {
  await openDay(page, { "GET /simulations": [] }, "/autodesk/studio");
  await expect(page.getByTestId("day-empty")).toContainText("No simulation yet.");
  await expect(page.getByTestId("day-empty-new")).toHaveAttribute("href", "/autodesk/studio/new");
  await expect(page.getByTestId("day-clock")).toHaveCount(0);
  await expect(page.getByTestId("day-lanes")).toHaveCount(0);
  await page.getByTestId("day-empty-new").click();
  await expect(page.getByTestId("studio-new")).toBeVisible();

  await openDay(page, { "GET /simulations": reply(500, { error: "INTERNAL", message: "database unavailable" }) }, "/autodesk/studio");
  await expect(page.getByTestId("error-box")).toContainText("database unavailable", { timeout: 10_000 });

  await openDay(page, doneRoutes(), "/autodesk/studio?sim=SIM-nope");
  await expect(page.getByTestId("error-box")).toContainText("not found: SIM-nope (404)");
  await expect(page.getByTestId("day-clock")).toHaveCount(0);

  await openDay(page, doneRoutes({ "GET /simulations/:sid/timeline": reply(500, { error: "INTERNAL", message: "timeline read failed" }) }));
  await expect(page.getByTestId("day-feed").getByTestId("error-box")).toContainText("timeline read failed", { timeout: 10_000 });
  await expect(page.getByTestId("day-clock-time")).toHaveText("18:00:00");
});

test("AD-UI-117 a run playing in the background: polled, clock moves, timeline read incrementally", async ({ page }) => {
  const live = liveRun("RUNNING", 1);
  live.row.background_run = true;
  await openDay(page, liveRoutes(live), `/autodesk/studio?sim=${NEW_SID}`);
  await expect(page.getByTestId("day-toggle")).toHaveText("Pause");
  await expect.poll(() => live.polls, { timeout: 15_000 }).toBeGreaterThanOrEqual(3);
  live.row.background_run = false;                                               // the run stops moving (e.g. paused elsewhere)
  await expect(page.getByTestId("day-toggle")).toHaveText("Play", { timeout: 10_000 });
  const n = live.row.step_seq as number;
  expect(n).toBeGreaterThanOrEqual(3);
  await expect(page.getByTestId("day-clock-time")).toHaveText(IST_OF_STEP[(n - 1) % 6]);
  await expect(page.getByTestId("day-phase")).toContainText(`step ${n} of 12`);
  await expect(page.getByTestId("day-feed-row").nth(0)).toContainText(`Step ${n} · `);
  expect(live.afterSeqs[0]).toBe(0);
  expect(live.afterSeqs.some((a) => a > 0)).toBe(true);                         // later reads ask only for newer events
});

test("AD-UI-118 phone 390×844: one column, two-column counters, lanes scroll inside their box, no page overflow", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await openDay(page, doneRoutes());
  await expect(page.getByTestId("day-clock-time")).toHaveText("18:00:00");
  const cols = await page.getByTestId("day-counters").evaluate((el) => getComputedStyle(el).gridTemplateColumns.split(" ").length);
  expect(cols).toBe(2);
  const inner = await page.getByTestId("day-track-scroll").evaluate((el) => el.scrollWidth - el.clientWidth);
  expect(inner).toBeGreaterThan(0);
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow).toBeLessThanOrEqual(0);
  await page.getByTestId("day-jump-PROPOSALS").click();
  const overflow2 = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow2).toBeLessThanOrEqual(0);
});

test("AD-UI-119 no sample ids or figures, no forbidden words in the view's own text, no console errors", async ({ page }) => {
  const errors = collectConsoleErrors(page);
  const desk = await openDay(page, doneRoutes());
  await expect(page.getByTestId("day-feed-row").first()).toBeVisible();
  const text = await page.getByTestId("studio-day").innerText();
  for (const s of ["SIM-0418", "SIM-0417", "SCN-0", "P-PAPER", "8841", "16,734", "18,874", "RELIANCE", "TATASTEEL filled", "CP-1700"]) expect(text).not.toContain(s);
  expect(text).not.toMatch(/\b(buy|sell|stop[ -]?loss|targets?|entry|entries|accumulate|book profit|upside|price target|recommend\w*|pick\w*)\b/i);
  expect(text).not.toMatch(/\bSL\b/);
  expect(desk.unmatched).toEqual([]);
  expect(desk.requests.every((r) => r.path.startsWith("/simulations") || r.path.startsWith("/api/"))).toBe(true);
  expect(errors).toEqual([]);
});
