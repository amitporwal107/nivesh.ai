/**
 * Desk web app — 03 · Opportunity scanner (AD-UI-40..49). Test cases: docs/autodesk/ui_testcases/scanner.md.
 * API answered by route mocks (autodesk-mock.ts + autodesk-fixtures-scanner.ts — MOCK, shapes of the real API).
 * The browser clock is fixed at 11:42:30 IST on 5 Nov 2026 so ages and expiries are deterministic.
 */
import { expect, test, type Page } from "@playwright/test";
import { NOW, TENANT, collectConsoleErrors, expectContract, mockDesk, reply } from "./autodesk-mock";
import {
  ACC, APR, CYCLE, CYCLE_RUNNING, PLANS, SCAN_TASK, SCAN_WF, SIG, SIGNALS, detailOf, scannerRoutes,
} from "./autodesk-fixtures-scanner";

const rowsIn = (page: Page) => page.getByTestId("signal-row");
const expectOrder = (page: Page, syms: string[]) => expect(page.getByTestId("signal-row").getByTestId("row-instrument")).toHaveText(syms);
const row = (page: Page, sym: string) => page.getByTestId(`signal-row-${sym}`);

test.beforeEach(async ({ page }) => {
  await page.clock.setFixedTime(new Date(NOW));
});

test("AD-UI-40/41 header, headline and the six scanner statistics come from the cycle, signals, plans and policy", async ({ page }) => {
  const errors = collectConsoleErrors(page);
  const desk = await mockDesk(page, { routes: scannerRoutes() });
  await page.goto("/autodesk/scanner");
  const s = page.getByTestId("screen-scanner");
  await expect(s).toContainText("03 · Opportunity scanner");
  await expect(page.getByTestId("ai-trader-pill")).toHaveText("AI Trader · idle");
  await expect(page.getByTestId("rules-pill")).toHaveText("autodesk-ait-v1 · ait-rules-v1");
  await expect(page.getByTestId("scanner-headline")).toHaveText("Five signals cleared the line for 5 Nov. One is already a plan waiting on you.");
  await expect(s).toContainText("The score ranks evidence with versioned rules and is not a probability.");

  await expect(page.getByTestId("stat-universe-v")).toHaveText("224");
  await expect(page.getByTestId("stat-universe")).toContainText("F&O underlyings · data 4 Nov");
  await expect(page.getByTestId("stat-coverage-v")).toHaveText("98.7%");
  await expect(page.getByTestId("stat-coverage")).toContainText("3 symbols missing data");
  await expect(page.getByTestId("stat-published-v")).toHaveText("174");
  await expect(page.getByTestId("stat-published")).toContainText("Session 5 Nov, all scores");
  await expect(page.getByTestId("stat-above")).toContainText("Score 60+");
  await expect(page.getByTestId("stat-above-v")).toHaveText("5");
  await expect(page.getByTestId("stat-dupes-v")).toHaveText("2");
  await expect(page.getByTestId("stat-expired-v")).toHaveText("0");
  await expect(page.getByTestId("history-phase-note")).toContainText("Phase 2");
  await expect(page.getByTestId("history-phase-note")).not.toContainText(/T1 HIT|\+0\.\d+R/);

  const reqs = desk.requests.map((r) => r.path);
  expect(reqs).toContain(`/desk/workflows?account_id=${ACC}&kind=SESSION_CYCLE&limit=500`);
  expect(reqs).toContain(`/signals?account_id=${ACC}&session_date=2026-11-05&limit=2000`);
  expect(reqs.some((p) => p.startsWith("/policies/POL-01JBX3K2M4N5P6Q7R8S9T0V1W3?version=1"))).toBe(true);
  expect(desk.unmatched).toEqual([]);
  expect(desk.posts).toEqual([]);
  expect(errors).toEqual([]);
});

test("AD-UI-41 after the session close, signals without a plan count as expired unused", async ({ page }) => {
  await page.clock.setFixedTime(new Date("2026-11-05T11:00:00.000Z"));     // 16:30 IST
  await mockDesk(page, { routes: scannerRoutes() });
  await page.goto("/autodesk/scanner");
  await expect(page.getByTestId("stat-expired-v")).toHaveText("6");
  await expect(row(page, "NIFTY").getByTestId("row-status")).toHaveText("Expired unused");
  await expect(row(page, "PETRONET").getByTestId("row-status")).toHaveText("Approved · APR-0e2c4a6b…");
});

test("AD-UI-42 ranked rows: score order, direction, calibrated P, levels, confirmation, age · expiry, plan status", async ({ page }) => {
  await mockDesk(page, { routes: scannerRoutes() });
  await page.goto("/autodesk/scanner");
  await expect(rowsIn(page)).toHaveCount(9);
  await expectOrder(page, ["PETRONET", "GRASIM", "ADANIPORTS", "HINDALCO", "NIFTY", "TATASTEEL", "RELIANCE", "INFY", "SBIN"]);

  const p = row(page, "PETRONET");
  await expect(p.getByTestId("row-direction")).toHaveText("BULLISH");
  await expect(p.getByTestId("row-score")).toHaveText("80");
  await expect(p.getByTestId("row-prob")).toHaveText("—");
  await expect(p).toContainText("Not calibrated");
  await expect(p.getByTestId("row-entry")).toHaveText("316.40–320.50 → 306.15");
  await expect(p.getByTestId("row-targets")).toHaveText("343.05 / 355.35");
  await expect(p.getByTestId("row-confirmation")).toHaveText("futures long buildup: price 2.34% OI 6.18%");
  await expect(p.getByTestId("row-age")).toHaveText("41m · 15:30");
  await expect(p.getByTestId("row-status")).toHaveText("Approved · APR-0e2c4a6b…");
  await expect(p.getByTestId("row-status")).toHaveAttribute("title", APR.PETRONET);
  await expect(p).toContainText("FUTURES · POSITIONAL");

  await expect(row(page, "GRASIM").getByTestId("row-status")).toHaveText("In approval · APR-3c5e7a9b…");
  await expect(row(page, "ADANIPORTS").getByTestId("row-status")).toHaveText("Rejected · APR-9b1d3f5a…");     // the person's decision, not the older request
  await expect(row(page, "HINDALCO").getByTestId("row-status")).toHaveText("No plan · NO_TRADE");
  await expect(row(page, "NIFTY").getByTestId("row-status")).toHaveText("Watch only");
  await expect(row(page, "NIFTY")).toContainText("INDEX · POSITIONAL");
  await expect(row(page, "TATASTEEL").getByTestId("row-direction")).toHaveText("BEARISH");
  await expect(row(page, "RELIANCE").getByTestId("row-entry")).toHaveText("1,306.10–1,315.90 → 1,281.60");
  await expect(row(page, "RELIANCE").getByTestId("row-confirmation")).toHaveText("futures long unwinding: price 0.62% OI −2.10%");
  await expect(row(page, "RELIANCE")).toContainText("CASH · POSITIONAL");
});

test("AD-UI-43 expanded row: eight dimensions, evidence, missing inputs, provenance; Open approval navigates", async ({ page }) => {
  await mockDesk(page, { routes: scannerRoutes() });
  await page.goto("/autodesk/scanner");

  await row(page, "NIFTY").getByTestId("signal-row").click();
  const n = row(page, "NIFTY").getByTestId("row-expanded");
  await expect(n).toBeVisible();
  await expect(n.locator('[data-testid^="dim-"]')).toHaveCount(8);
  await expect(n.getByTestId("dim-volume_delivery")).toContainText("Volume and delivery · missing input");
  await expect(n.getByTestId("dim-volume_delivery")).toContainText("—/15");
  await expect(n.getByTestId("dim-relative_strength")).toContainText("—/10");
  await expect(n.getByTestId("missing-inputs")).toContainText("volume_delivery, relative_strength");
  await expect(n.getByTestId("row-action")).toHaveCount(0);          // watch only: no action, as in the design
  await row(page, "NIFTY").getByTestId("signal-row").click();
  await expect(page.getByTestId("row-expanded")).toHaveCount(0);

  await row(page, "PETRONET").getByTestId("signal-row").click();
  const x = row(page, "PETRONET").getByTestId("row-expanded");
  await expect(x).toContainText("Score breakdown · 80 of 100");
  const dims = await x.locator('[data-testid^="dim-"] > span:first-child').allTextContents();
  expect(dims).toEqual(["Trend confirmation", "Momentum", "Volume and delivery", "Relative strength", "Market structure", "Derivatives confirmation", "Market regime", "Liquidity"]);
  await expect(x.getByTestId("dim-trend")).toContainText("15/15");
  await expect(x.getByTestId("dim-volume_delivery")).toContainText("10/15");
  await expect(x.getByTestId("dim-liquidity")).toContainText("6/10");
  await expect(x.getByTestId("dim-trend")).toHaveAttribute("title", "close 318.45, SMA20 305.12, SMA50 298.70 (10 sessions ago 296.10)");
  await expect(x.getByTestId("evidence-chip")).toHaveText(["LONG BUILDUP", "OIL GAS & CONSUMABLE FUELS", "F&O ELIGIBLE"]);
  await expect(x.getByTestId("evidence-text")).toHaveText(["futures long buildup on 2026-11-04"]);
  await expect(x.getByTestId("row-close")).toHaveText("Close 318.45 · liquidity 20-session average traded value ₹38.2 cr");
  await expect(x).toContainText("Similar-setup history needs recorded outcomes");
  const prov = x.getByTestId("provenance");
  for (const t of [SIG.PETRONET, "DATA AS OF 4 Nov 19:30 IST", "MODEL autodesk-ait-v1/ait-rules-v1", "RULES ait-rules-v1", "SESSION 5 Nov", "EXPIRES 5 Nov 15:30", `WORKFLOW ${SCAN_WF}`, `TASK ${SCAN_TASK}`]) {
    await expect(prov).toContainText(t);
  }
  await expect(x.getByTestId("row-action")).toHaveText("Open approval ›");
  await x.getByTestId("row-action").click();
  await expect(page).toHaveURL(new RegExp(`/autodesk/approvals/${APR.PETRONET}$`));
  await expect(page.getByTestId("screen-approvals")).toBeVisible();
});

test("AD-UI-44 direction, segment and min-score filters narrow the rows on screen", async ({ page }) => {
  const desk = await mockDesk(page, { routes: scannerRoutes() });
  await page.goto("/autodesk/scanner");
  await expect(rowsIn(page)).toHaveCount(9);
  const before = desk.requests.length;

  await page.getByTestId("filter-direction-bearish").click();
  await expect(page.getByTestId("filter-direction-bearish")).toHaveAttribute("aria-pressed", "true");
  await expectOrder(page, ["TATASTEEL", "INFY", "SBIN"]);
  await page.getByTestId("filter-direction-all").click();

  await page.getByTestId("filter-segment-index").click();
  await expectOrder(page, ["NIFTY"]);
  await page.getByTestId("filter-segment-cash").click();
  await expectOrder(page, ["RELIANCE"]);
  await page.getByTestId("filter-segment-all").click();

  await page.getByTestId("filter-min-70").click();
  await expectOrder(page, ["PETRONET"]);
  await page.getByTestId("filter-min-60").click();
  await expect(rowsIn(page)).toHaveCount(5);

  await page.getByTestId("filter-direction-bearish").click();
  await expect(page.getByTestId("scanner-no-match")).toHaveText("No signal matches these filters.");
  expect(desk.requests.slice(before).filter((r) => r.path.startsWith("/signals"))).toEqual([]);   // filtering is on screen
});

test("AD-UI-45 Run session cycle: contract body, running state, polling until COMPLETED, then the signals load", async ({ page }) => {
  const errors = collectConsoleErrors(page);
  const st = { posted: false, polls: 0 };
  const desk = await mockDesk(page, {
    routes: scannerRoutes({
      "GET /desk/workflows": () => (!st.posted ? [] : [st.polls >= 2 ? CYCLE : CYCLE_RUNNING]),
      "POST /desk/workflows": () => { st.posted = true; return reply(202, CYCLE_RUNNING); },
      "GET /desk/workflows/:id": () => { st.polls += 1; return detailOf(st.polls >= 2 ? CYCLE : CYCLE_RUNNING); },
      "GET /signals": () => (st.polls >= 2 ? SIGNALS : []),
    }),
  });
  await page.goto("/autodesk/scanner");
  await expect(page.getByTestId("scanner-no-cycle")).toContainText("a person starts the cycle");
  await expect(page.getByTestId("run-cycle")).toBeEnabled();
  await page.getByTestId("run-cycle").click();

  const status = page.getByTestId("cycle-status");
  await expect(status).toHaveAttribute("data-state", "RUNNING");
  expectContract(desk.posts.find((p) => p.path === "/desk/workflows"), "scanner", "run_session_cycle", { account_id: ACC });
  await expect(status).toContainText("Running since 11:01:01 IST: pre-market check → market scan → trade proposals");
  await expect(page.getByTestId("ai-trader-pill")).toHaveText("AI Trader · scanning");
  await expect(page.getByTestId("run-cycle")).toBeDisabled();
  await expect(page.getByTestId("run-cycle")).toHaveText("Cycle running…");

  await expect(status).toHaveAttribute("data-state", "COMPLETED", { timeout: 10000 });
  await expect(status).toContainText("COMPLETED · CYCLE_COMPLETED · 174 signals published · 4 proposed of 61 candidates");
  await expect(rowsIn(page)).toHaveCount(9);
  await expect(page.getByTestId("ai-trader-pill")).toHaveText("AI Trader · idle");
  await expect(page.getByTestId("run-cycle")).toBeEnabled();
  expect(desk.requests.filter((r) => r.path.startsWith(`/desk/workflows/${CYCLE.workflow_id}`)).length).toBeGreaterThanOrEqual(2);
  expect(desk.posts).toHaveLength(1);
  expect(errors).toEqual([]);
});

test("AD-UI-46 Run session cycle failures show the API's message; a finished cycle says it already ran", async ({ page }) => {
  const answers = [
    reply(409, { detail: "already running" }),
    reply(409, { error: "CONFLICT", message: "account is SUSPENDED" }),
    reply(422, { detail: [{ loc: ["body", "account_id"], msg: "Field required", type: "missing" }] }),
    reply(202, CYCLE),
  ];
  const desk = await mockDesk(page, { routes: scannerRoutes({ "POST /desk/workflows": () => answers.shift() }) });
  await page.goto("/autodesk/scanner");
  await expect(rowsIn(page)).toHaveCount(9);
  const run = page.getByTestId("run-cycle");

  await run.click();
  await expect(page.getByTestId("cycle-error")).toContainText("Could not start the session cycle");
  await expect(page.getByTestId("cycle-error")).toContainText("already running (409)");
  await run.click();
  await expect(page.getByTestId("cycle-error")).toContainText("account is SUSPENDED (409)");
  await run.click();
  await expect(page.getByTestId("cycle-error")).toContainText("account_id: Field required (422)");
  await expect(rowsIn(page)).toHaveCount(9);
  await expect(page.getByTestId("cycle-status")).toHaveCount(0);

  await run.click();
  await expect(page.getByTestId("cycle-error")).toHaveCount(0);
  await expect(page.getByTestId("cycle-already")).toContainText("The cycle for Thu 5 Nov 2026 already ran on this account (COMPLETED · CYCLE_COMPLETED");
  await expect(page.getByTestId("cycle-already")).toContainText("one cycle per account and session");
  expect(desk.posts).toHaveLength(4);
  for (const p of desk.posts) expectContract(p, "scanner", "run_session_cycle", { account_id: ACC });
});

test("AD-UI-47 no desk account: the run button is disabled with the reason", async ({ page }) => {
  const desk = await mockDesk(page, { routes: scannerRoutes(), state: { accounts: [] } });
  await page.goto("/autodesk/scanner");
  await expect(page.getByTestId("scanner-headline")).toHaveText("No desk account yet.");
  await expect(page.getByTestId("scanner-no-account")).toBeVisible();
  await expect(page.getByTestId("run-cycle")).toBeDisabled();
  await expect(page.getByTestId("run-why")).toHaveText("Create a paper account first (sidebar › New paper account).");
  await page.getByTestId("run-cycle").click({ force: true });
  expect(desk.posts).toEqual([]);
  expect(desk.requests.some((r) => r.path.startsWith("/signals"))).toBe(false);
});

test("AD-UI-47 account without a cycle: empty state saying a person starts it", async ({ page }) => {
  await mockDesk(page, { routes: scannerRoutes({ "GET /desk/workflows": [] }) });
  await page.goto("/autodesk/scanner");
  await expect(page.getByTestId("scanner-headline")).toHaveText("No session cycle has run on this desk yet.");
  await expect(page.getByTestId("scanner-no-cycle")).toContainText("There is no scheduler in Phase 1");
  await expect(page.getByTestId("stat-universe-v")).toHaveText("—");
  await expect(page.getByTestId("stat-published-v")).toHaveText("—");
  await expect(page.getByTestId("run-cycle")).toBeEnabled();
});

const NIFTY_REVISION = { ...PLANS[0], trade_id: "TRD-f0e1d2c3b4a54968a7b6", signal_id: SIG.NIFTY, instrument: "NIFTY", status: "NEEDS_REVISION", current_version: 1 };

test("AD-UI-47 Stop new entries: the design's banner, the cycle note, workbench actions read Entries stopped", async ({ page }) => {
  const stop = { tenant_id: TENANT, control: "STOP_NEW_ENTRIES", active: true, reason: "results week", changed_by: TENANT, changed_at: NOW };
  await mockDesk(page, { routes: scannerRoutes({ "GET /trade-plans": [NIFTY_REVISION, ...PLANS] }), state: { controls: [stop] } });
  await page.goto("/autodesk/scanner");
  await expect(page.getByTestId("scanner-halted")).toHaveText("New entries are stopped. Signals keep publishing for the record; strategy generation is paused until entries resume.");
  await expect(page.getByTestId("cycle-halted-note")).toContainText("a session cycle still runs the pre-market check and the scan and publishes signals; its trade proposals are held back");
  await expect(page.getByTestId("run-cycle")).toBeEnabled();
  await expect(row(page, "NIFTY").getByTestId("row-status")).toHaveText("Revision · TRD-f0e1d2c3…");
  await row(page, "NIFTY").getByTestId("signal-row").click();
  const act = row(page, "NIFTY").getByTestId("row-action");
  await expect(act).toHaveText("Entries stopped");
  await expect(act).toBeDisabled();
  await row(page, "PETRONET").getByTestId("signal-row").click();
  await expect(row(page, "PETRONET").getByTestId("row-action")).toHaveText("Open approval ›");      // opening an approval is not blocked
  await expect(row(page, "PETRONET").getByTestId("row-action")).toBeEnabled();
});

test("AD-UI-47 without the stop, a revision plan's action opens the workbench", async ({ page }) => {
  await mockDesk(page, { routes: scannerRoutes({ "GET /trade-plans": [NIFTY_REVISION, ...PLANS] }) });
  await page.goto("/autodesk/scanner");
  await expect(page.getByTestId("scanner-halted")).toHaveCount(0);
  await row(page, "NIFTY").getByTestId("signal-row").click();
  await expect(row(page, "NIFTY").getByTestId("row-action")).toHaveText("Revise in workbench ›");
  await row(page, "NIFTY").getByTestId("row-action").click();
  await expect(page).toHaveURL(/\/autodesk\/workbench$/);
});

test("AD-UI-48 API errors are shown in place; plan status failure is not hidden", async ({ page }) => {
  await mockDesk(page, { routes: scannerRoutes({ "GET /signals": reply(500, { detail: "signals store unavailable" }) }) });
  await page.goto("/autodesk/scanner");
  const box = page.getByTestId("error-box");
  await expect(box).toContainText("Could not load the signals", { timeout: 15000 });
  await expect(box).toContainText("signals store unavailable (500)");
  await expect(rowsIn(page)).toHaveCount(0);

  await page.unrouteAll({ behavior: "ignoreErrors" });
  await mockDesk(page, { routes: scannerRoutes({ "GET /desk/workflows": reply(503, { error: "UNAVAILABLE", message: "desk database did not answer" }) }) });
  await page.reload();
  await expect(page.getByTestId("error-box")).toContainText("Could not load the session cycles", { timeout: 15000 });
  await expect(page.getByTestId("error-box")).toContainText("desk database did not answer (503)");

  await page.unrouteAll({ behavior: "ignoreErrors" });
  await mockDesk(page, { routes: scannerRoutes({ "GET /trade-plans": reply(500, { detail: "plans unavailable" }) }) });
  await page.reload();
  await expect(page.getByTestId("error-box")).toContainText("Could not load plan status for these signals", { timeout: 15000 });
  await expect(page.getByTestId("error-box")).toContainText("plans unavailable (500)");
  await expect(rowsIn(page)).toHaveCount(9);
  await expect(page.getByTestId("row-status")).toHaveText(Array(9).fill("Status unavailable"));
});

test("AD-UI-48 no sample figures or ids from the prototype", async ({ page }) => {
  await mockDesk(page, { routes: scannerRoutes() });
  await page.goto("/autodesk/scanner");
  await expect(rowsIn(page)).toHaveCount(9);
  const text = await page.getByTestId("screen-scanner").innerText();
  for (const s of ["SIG-10251", "SIG-10262", "APR-3106", "APR-3107", "TRD-1189", "PLN-2045", "n = 412", "signal-v1.4", "rules-v3.2", "Nifty 500 + F&O + indices", "T1 HIT"]) {
    expect(text, s).not.toContain(s);
  }
  expect(text).not.toMatch(/\b712\b|\b0\.57\b|99\.1%/);
});

test("AD-UI-49 phone 390×844: cards instead of the table, tap to expand, no horizontal overflow", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await mockDesk(page, { routes: scannerRoutes() });
  await page.goto("/autodesk/scanner");
  await expect(page.getByTestId("signal-cards")).toBeVisible();
  await expect(page.getByTestId("signal-table")).toHaveCount(0);
  await expect(page.locator('[data-testid^="signal-row-"]')).toHaveCount(9);
  await expect(row(page, "PETRONET").getByTestId("row-score")).toHaveText("80");
  await expect(row(page, "PETRONET").getByTestId("row-entry")).toHaveText("316.40–320.50 → 306.15");
  await row(page, "PETRONET").click();
  const x = row(page, "PETRONET").getByTestId("row-expanded");
  await expect(x.locator('[data-testid^="dim-"]')).toHaveCount(8);
  await expect(x.getByTestId("row-action")).toHaveText("Open approval ›");
  await expect(page.getByTestId("run-cycle")).toBeVisible();
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow).toBeLessThanOrEqual(0);
});
