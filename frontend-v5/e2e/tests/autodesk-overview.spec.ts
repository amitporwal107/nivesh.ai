/**
 * Desk web app — 01 Desk overview (AD-UI-20..29). Test cases: docs/autodesk/ui_testcases/overview.md.
 * API answered by route mocks (autodesk-mock.ts + autodesk-fixtures-overview.ts — MOCK, shapes of the real API).
 * The page clock is fixed at NOW (11:42:30 IST, 5 Nov 2026) so times and expiries read the same on every run.
 */
import { expect, test, type Page } from "@playwright/test";
import { AGENTS_STATUS, LIVE_OPEN, NOW, TENANT, collectConsoleErrors, mockDesk, reply, type MockState, type Req, type RouteValue } from "./autodesk-mock";
import { ACTIVITY, AGENTS_MIXED, APPROVED_HDFC, ASSESSMENTS, PENDING, POL, TRD, planDetail, status } from "./autodesk-fixtures-overview";

async function setup(page: Page, opts: { pending?: unknown[]; agents?: unknown[]; statusOver?: Record<string, unknown>; routes?: Record<string, RouteValue>; state?: Record<string, unknown> } = {}) {
  await page.clock.setFixedTime(new Date(NOW));
  const pending = opts.pending ?? PENDING;
  return mockDesk(page, {
    state: opts.state as never,
    routes: {
      "GET /desk/status": (_r: Req, s: MockState) => status(s, { agents: opts.agents ?? AGENTS_STATUS, ...(opts.statusOver ?? {}) }),
      "GET /approvals": (r: Req) => (r.query.get("pending") === "true" ? pending : [...pending, APPROVED_HDFC]),
      "GET /trade-plans/:trade_id": (r: Req) => planDetail(r.params.trade_id, Number(r.query.get("version") ?? 1)),
      "GET /agents/:agent_key/activity": (r: Req) => ACTIVITY[r.params.agent_key] ?? [],
      "GET /risk/assessments/:id": (r: Req) => ASSESSMENTS[r.params.id] ?? reply(404, { error: "NOT_FOUND", message: `not found: ${r.params.id}` }),
      ...(opts.routes ?? {}),
    },
  });
}

const screen = (page: Page) => page.getByTestId("screen-overview");

test("AD-UI-20 header from real data: date, mode pill, computed headline and sub line", async ({ page }) => {
  const errors = collectConsoleErrors(page);
  const desk = await setup(page, { pending: [PENDING[0], PENDING[1], PENDING[4]] });
  await page.goto("/autodesk/");
  await expect(screen(page).locator(".nv-eyebrow").first()).toHaveText("01 · Desk overview · Thu 5 Nov 2026");
  await expect(page.getByTestId("mode-pill")).toHaveText(["Auto paper · Desk A"]);
  await expect(page.getByTestId("headline")).toHaveText("All 5 agents are healthy. Two approvals are waiting on you; the first expires at 12:10.");
  await expect(page.getByTestId("headline").locator("em")).toHaveText("Two approvals");
  await expect(page.getByTestId("subline")).toContainText("There is no P&L yet: orders and fills come with paper execution (Phase 2).");
  await expect(page.getByTestId("subline")).toContainText("The last pre-market check, for 5 Nov, was ready, with cash, futures, options allowed.");
  await expect(screen(page)).not.toContainText("Every position is inside its limits");
  await expect(page.getByTestId("activity-row").first()).toBeVisible();
  expect(desk.unmatched).toEqual([]);
  expect(errors).toEqual([]);
});

test("AD-UI-21 needs you: desk approvals ranked by the plan's max loss, top 3, each opens its approval", async ({ page }) => {
  const desk = await setup(page);
  await page.goto("/autodesk/");
  const rows = page.getByTestId("needs-row");
  await expect(rows).toHaveCount(3);
  await expect(rows.nth(0)).toContainText("PETRONET bull call spread on paper needs your sign-off");
  await expect(rows.nth(1)).toContainText("GRASIM bull call spread on paper needs your sign-off");
  await expect(rows.nth(2)).toContainText("ADANIPORTS long call on paper needs your sign-off");
  await expect(page.getByTestId("needs-value")).toHaveText(["₹48,426", "₹41,683", "₹36,244"]);
  await expect(rows.nth(0).getByTestId("needs-sub")).toHaveText("APR-a1b2c3d4e5f6a7b8c9d0 · signal score 64.50 is below 70 · expires 15:25");
  await expect(rows.nth(1).getByTestId("needs-sub")).toHaveText("APR-b2c3d4e5f6a7b8c9d0e1 · risk 0.52% of equity is above 0.5% · expires 12:10");
  await expect(page.getByTestId("needs-you")).not.toContainText("RELIANCE");          // 4th by max loss
  await expect(page.getByTestId("headline")).toHaveText("All 5 agents are healthy. 4 approvals are waiting on you; the first expires at 12:10.");
  const plans = desk.requests.filter((r) => r.path.startsWith("/trade-plans/")).map((r) => r.path);
  expect(plans).toContain(`/trade-plans/${TRD.grasim}?version=2`);
  expect(plans.some((p) => p.includes(TRD.hdfc))).toBe(false);                         // the simulation's request is not the desk's
  expect(desk.unmatched).toEqual([]);
  await rows.nth(1).click();
  await expect(page).toHaveURL(/\/autodesk\/approvals\/APR-b2c3d4e5f6a7b8c9d0e1$/);
});

test("AD-UI-22 nothing pending: empty state, headline and tile say so", async ({ page }) => {
  await setup(page, { pending: [] });
  await page.goto("/autodesk/");
  await expect(page.getByTestId("needs-none")).toHaveText("Nothing is waiting on you.");
  await expect(page.getByTestId("needs-row")).toHaveCount(0);
  await expect(page.getByTestId("headline")).toHaveText("All 5 agents are healthy. No approvals are waiting on you.");
  await expect(page.getByTestId("tile-pending")).toContainText("0");
  await expect(page.getByTestId("tile-pending")).toContainText("Queue is clear");
});

test("AD-UI-23 tiles: real values from the API, Phase 2 tiles say so, no sample figures", async ({ page }) => {
  await setup(page, { agents: AGENTS_MIXED });
  await page.goto("/autodesk/");
  await expect(page.locator('[data-testid^="tile-"]')).toHaveCount(12);
  await expect(page.getByTestId("tile-mode")).toContainText("Auto paper");
  await expect(page.getByTestId("tile-mode")).toContainText("Desk A");
  await expect(page.getByTestId("tile-session")).toContainText("Open");
  await expect(page.getByTestId("tile-session")).toContainText("NSE · 09:15–15:30 IST · closes in 3h 47m");
  await expect(page.getByTestId("tile-agents")).toContainText("4 · 1 · 0");
  await expect(page.getByTestId("tile-pending")).toContainText("4");
  await expect(page.getByTestId("tile-pending")).toContainText("First expires 12:10 IST");
  await expect(page.getByTestId("tile-premarket")).toContainText("Ready");
  await expect(page.getByTestId("tile-premarket")).toContainText("Session 5 Nov · cash, futures, options");
  await expect(page.getByTestId("tile-workflows")).toContainText("2");
  for (const id of ["trades", "orders", "capital", "risk", "pnl", "exceptions"]) {
    await expect(page.getByTestId(`tile-${id}`)).toContainText("—");
    await expect(page.getByTestId(`tile-${id}`)).toContainText("Phase 2");
  }
  await expect(page.getByTestId("tile-capital")).toContainText("starting capital ₹1.00 Cr");
  for (const sample of ["₹15.1 L", "₹77.4 L", "0.47%", "+₹9,888", "−₹1,470", "5 paper · 2 live"]) await expect(screen(page)).not.toContainText(sample);
  await page.getByTestId("tile-agents").click();
  await expect(page).toHaveURL(/\/autodesk\/agents$/);
});

test("AD-UI-24 P&L card is a Phase 2 note; feeds card rows come from the feed and desk status", async ({ page }) => {
  await setup(page);
  await page.goto("/autodesk/");
  await expect(page.getByTestId("pnl-phase-note")).toContainText("Phase 2");
  await expect(page.getByTestId("pnl-card")).not.toContainText(/₹\s?\d/);
  await expect(page.getByTestId("pnl-card").locator("svg")).toHaveCount(0);
  await expect(page.getByTestId("feed-kite-status")).toHaveText("LIVE · 2s");
  await expect(page.getByTestId("feed-cash-status")).toHaveText("SESSION 4 NOV");
  await expect(page.getByTestId("feed-fno-status")).toHaveText("SESSION 4 NOV");
  await expect(page.getByTestId("feed-premarket-status")).toHaveText("READY · 5 NOV");
  await expect(page.getByTestId("feed-paper-status")).toHaveText("PHASE 2");
  await expect(page.getByTestId("feeds-broker-note")).toContainText("Broker connections are not part of Phase 1");
  await expect(page.getByTestId("feeds-card")).not.toContainText(/Zerodha|ICICI|ZX4821|IX2207/);
});

test("AD-UI-24 feeds card shows the market-data error text and a disconnected Kite feed", async ({ page }) => {
  await setup(page, {
    statusOver: { market_data: { error: "DataUnavailable: data API answered 503 for /eod/latest" } },
    routes: { "GET /api/live/quotes": { ...LIVE_OPEN, mode: "not_connected", stale: true } },
  });
  await page.goto("/autodesk/");
  await expect(page.getByTestId("feed-kite-status")).toHaveText("NOT CONNECTED");
  await expect(page.getByTestId("feed-cash-status")).toHaveText("ERROR");
  await expect(page.getByTestId("feed-fno-status")).toHaveText("ERROR");
  await expect(page.getByTestId("feed-cash-note")).toHaveText("DataUnavailable: data API answered 503 for /eod/latest");
});

test("AD-UI-25 agents: registry status and the latest desk task (simulation tasks skipped)", async ({ page }) => {
  await setup(page, {
    agents: AGENTS_MIXED,
    routes: {
      "GET /agents/:agent_key/activity": (r: Req) =>
        r.params.agent_key === "RISK_OPS" ? [] : r.params.agent_key === "MIDDLE_OFFICE" ? [ACTIVITY.AI_TRADER[0]] : ACTIVITY[r.params.agent_key],
    },
  });
  await page.goto("/autodesk/");
  const cards = page.locator('[data-testid^="agent-card-"]');
  await expect(cards).toHaveCount(5);
  expect(await cards.evaluateAll((els) => els.map((e) => e.getAttribute("data-testid")))).toEqual(
    ["agent-card-AI_TRADER", "agent-card-TRADING_ASSISTANT", "agent-card-RISK_OPS", "agent-card-MIDDLE_OFFICE", "agent-card-TECH_SUPPORT"]);
  const ta = page.getByTestId("agent-card-TRADING_ASSISTANT");
  await expect(ta.getByTestId("agent-status")).toHaveText("BUSY");
  await expect(ta.getByTestId("agent-task")).toHaveText("Working on: Plan drafting · SIG-1b2c3d4e5f6a7b8c9d0e · running since 11:42");
  await expect(page.getByTestId("agent-card-AI_TRADER").getByTestId("agent-task"))
    .toHaveText("Last: Market scan · completed 09:20 · 174 signals from 224 instruments (125 suppressed or skipped)");
  await expect(page.getByTestId("agent-card-TECH_SUPPORT").getByTestId("agent-status")).toHaveText("DEGRADED");
  await expect(page.getByTestId("agent-card-RISK_OPS").getByTestId("agent-task")).toHaveText("No desk task yet.");
  await expect(page.getByTestId("agent-card-MIDDLE_OFFICE").getByTestId("agent-task")).toHaveText("No desk task among its last 50 tasks (the rest are simulation runs).");
  await expect(page.getByTestId("headline")).toContainText("1 of 5 agents need attention.");
  await expect(page.getByTestId("subline")).toContainText("Tech Support is degraded.");
});

test("AD-UI-26 recent activity: desk tasks newest first, why as written, policy and quantity from the API", async ({ page }) => {
  const desk = await setup(page);
  await page.goto("/autodesk/");
  const rows = page.getByTestId("activity-row");
  await expect(rows).toHaveCount(8);
  await expect(rows.nth(0)).toContainText("11:42");
  await expect(rows.nth(0)).toContainText("Trading Assistant");
  await expect(rows.nth(0)).toContainText("Plan drafting · SIG-1b2c3d4e5f6a7b8c9d0e (running)");
  await expect(rows.nth(1)).toContainText("09:25");
  await expect(rows.nth(1)).toContainText("Middle Office");
  await expect(rows.nth(1)).toContainText(`Approval review · ${TRD.hdfc}`);
  await expect(rows.nth(1)).toContainText("APPROVED: within the autonomy rules of the policy; risk 0.31% of equity");
  await expect(rows.nth(1)).toContainText(`${POL} v1`);
  await expect(rows.nth(1)).toContainText("max 4 lots");
  await expect(rows.nth(2)).toContainText("Risk & Operations");
  await expect(rows.nth(2)).toContainText("PASS: failed checks none");
  await expect(rows.nth(2)).toContainText(`${POL} v1`);
  await expect(rows.nth(2)).toContainText("allowed 4 of 4 lots per leg");
  await expect(rows.nth(3)).toContainText("NEEDS_HUMAN_APPROVAL: signal score 64.50 is below 70");
  await expect(rows.nth(6)).toContainText("Market scan");
  await expect(rows.nth(7)).toContainText("09:01");
  await expect(rows.nth(7)).toContainText("Pre-market check");
  const table = page.getByTestId("activity");
  for (const h of ["Time", "Agent", "What happened", "Why", "Policy", "Quantity"]) await expect(table.getByText(h, { exact: true })).toBeVisible();
  await expect(table).not.toContainText("238 signals");                                  // simulation task
  await expect(table).not.toContainText("4 Nov");                                        // 9th, older row cut
  expect(desk.requests.map((r) => r.path)).toEqual(expect.arrayContaining(["/risk/assessments/RSK-hdfc00000000000000", "/risk/assessments/RSK-petro0000000000000"]));
  expect(desk.unmatched).toEqual([]);
});

test("AD-UI-27 desk status and agent activity failing: messages shown, other sections still render", async ({ page }) => {
  await setup(page, {
    routes: {
      "GET /desk/status": reply(500, { error: "INTERNAL", message: "desk database did not answer" }),
      "GET /agents/:agent_key/activity": reply(500, { error: "INTERNAL", message: "task store unavailable" }),
    },
  });
  await page.goto("/autodesk/");
  await expect(screen(page).getByTestId("error-box").first()).toContainText("desk database did not answer (500)", { timeout: 15000 });
  await expect(page.getByTestId("needs-row")).toHaveCount(3);
  await expect(page.getByTestId("agent-card-AI_TRADER").getByTestId("agent-task")).toHaveText("Could not load tasks: task store unavailable (500)", { timeout: 15000 });
  await expect(page.getByTestId("activity").getByTestId("error-box")).toContainText("task store unavailable (500)");
});

test("AD-UI-27 pending approvals failing, and a plan that answers 404", async ({ page }) => {
  await setup(page, { routes: { "GET /approvals": reply(503, { error: "UNAVAILABLE", message: "approvals are not readable" }) } });
  await page.goto("/autodesk/");
  await expect(page.getByTestId("needs-you").getByTestId("error-box")).toContainText("approvals are not readable (503)", { timeout: 15000 });
  await expect(page.getByTestId("headline")).toContainText("Pending approvals could not be loaded.");

  await page.unrouteAll({ behavior: "ignoreErrors" });
  await setup(page, {
    pending: [PENDING[0], PENDING[1]],
    routes: {
      "GET /trade-plans/:trade_id": (r: Req) => (r.params.trade_id === TRD.grasim
        ? reply(404, { error: "NOT_FOUND", message: `not found: ${TRD.grasim}` })
        : planDetail(r.params.trade_id)),
    },
  });
  await page.reload();
  const rows = page.getByTestId("needs-row");
  await expect(rows).toHaveCount(2);
  await expect(rows.nth(1).getByTestId("needs-value")).toHaveText("—");
  await expect(rows.nth(1).getByTestId("needs-sub")).toContainText(`plan could not be loaded: not found: ${TRD.grasim} (404)`);
});

test("AD-UI-28 entries stopped: the headline says new plans are on hold", async ({ page }) => {
  await setup(page, {
    pending: [],
    state: { controls: [{ tenant_id: TENANT, control: "STOP_NEW_ENTRIES", active: true, reason: "results day", changed_by: `user:${TENANT}`, changed_at: NOW }] },
  });
  await page.goto("/autodesk/");
  await expect(page.getByTestId("headline")).toHaveText("New plans are on hold. No approvals are waiting on you.");
});

test("AD-UI-29 phone 390×844: one column, two tiles a row, activity as cards, no horizontal overflow", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const errors = collectConsoleErrors(page);
  await setup(page);
  await page.goto("/autodesk/");
  await expect(page.getByTestId("desk-mobile")).toBeVisible();
  const h1 = screen(page).locator("h1");
  expect(await h1.evaluate((e) => getComputedStyle(e).fontSize)).toBe("30px");
  const t = page.locator('[data-testid^="tile-"]');
  await expect(t).toHaveCount(12);
  const [a, b, c] = await Promise.all([t.nth(0).boundingBox(), t.nth(1).boundingBox(), t.nth(2).boundingBox()]);
  expect(b!.x).toBeGreaterThan(a!.x);
  expect(Math.round(c!.x)).toBe(Math.round(a!.x));
  await expect(page.getByTestId("activity-card")).toHaveCount(8);
  await expect(page.getByTestId("activity-row")).toHaveCount(0);
  await expect(page.getByTestId("activity").getByText("What happened", { exact: true })).toHaveCount(0);
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow).toBeLessThanOrEqual(0);
  expect(errors).toEqual([]);
});
