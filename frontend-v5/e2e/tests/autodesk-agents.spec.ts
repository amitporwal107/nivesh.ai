/**
 * Desk web app — 02 · Agent command centre (AD-UI-30..39). Test cases: docs/autodesk/ui_testcases/agents.md.
 * API answered by route mocks (autodesk-mock.ts + autodesk-fixtures-agents.ts — MOCK, shapes of the real API).
 * The browser clock is fixed at 11:42:30 IST on 5 Nov 2026 so ages are deterministic.
 */
import { expect, test, type Page } from "@playwright/test";
import { NOW, collectConsoleErrors, mockDesk, reply } from "./autodesk-mock";
import { ACTIVITY, T, agentRoutes, registry } from "./autodesk-fixtures-agents";
import { SCAN_WF, SIG, TRD, WFP } from "./autodesk-fixtures-scanner";

const card = (page: Page, k: string) => page.getByTestId(`agent-card-${k}`);
const trace = (page: Page, k: string) => page.getByTestId("decision-trace").getByTestId(`trace-${k}`);

test.beforeEach(async ({ page }) => {
  await page.clock.setFixedTime(new Date(NOW));
});

test("AD-UI-30 header, headline and the seven-status legend from the registry (current versions only)", async ({ page }) => {
  const errors = collectConsoleErrors(page);
  const desk = await mockDesk(page, { routes: agentRoutes() });
  await page.goto("/autodesk/agents");
  const s = page.getByTestId("screen-agents");
  await expect(s).toContainText("02 · Agent command centre");
  await expect(s).toContainText("Desk Orchestrator · deterministic");
  await expect(page.getByTestId("agents-count")).toHaveText("5 agents · 6 registered versions");
  await expect(page.getByTestId("agents-headline")).toHaveText("All five agents are healthy. None is busy right now.");
  const legend = page.getByTestId("agent-legend");
  for (const [st, n] of [["IDLE", 5], ["BUSY", 0], ["SCALING", 0], ["DEGRADED", 0], ["MAINTENANCE", 0], ["QUARANTINED", 0], ["OFFLINE", 0]] as const) {
    await expect(legend.getByTestId(`legend-${st}`)).toHaveText(`${st} ${n}`);      // the older OFFLINE RISK_OPS version is not current
  }
  expect(desk.unmatched).toEqual([]);
  expect(errors).toEqual([]);
});

test("AD-UI-30 headline names a degraded or busy agent", async ({ page }) => {
  await mockDesk(page, { routes: agentRoutes({ "GET /agents": registry({ TECH_SUPPORT: "DEGRADED" }) }) });
  await page.goto("/autodesk/agents");
  await expect(page.getByTestId("agents-headline")).toHaveText("Four agents are healthy. Tech Support is degraded.");
  await expect(page.getByTestId("agents-headline").locator("em")).toHaveText("Tech Support");
  await expect(page.getByTestId("legend-DEGRADED")).toHaveText("DEGRADED 1");
  await expect(card(page, "TECH_SUPPORT").getByTestId("agent-status")).toHaveText("DEGRADED");

  await page.unrouteAll({ behavior: "ignoreErrors" });
  await mockDesk(page, { routes: agentRoutes({ "GET /agents": registry({ AI_TRADER: "BUSY" }) }) });
  await page.reload();
  await expect(page.getByTestId("agents-headline")).toHaveText("All five agents are healthy. AI Trader is busy right now.");
  await expect(page.getByTestId("legend-BUSY")).toHaveText("BUSY 1");
});

test("AD-UI-31 five agent cards: status, heartbeat, task, queue (Phase 3), last success, decisions as written, errors · retries", async ({ page }) => {
  await mockDesk(page, { routes: agentRoutes() });
  await page.goto("/autodesk/agents");
  await expect(page.locator('[data-testid^="agent-card-"]')).toHaveCount(5);
  const ids = await page.locator('[data-testid^="agent-card-"]').evaluateAll((els) => els.map((e) => e.getAttribute("data-testid")));
  expect(ids).toEqual(["agent-card-AI_TRADER", "agent-card-TRADING_ASSISTANT", "agent-card-RISK_OPS", "agent-card-MIDDLE_OFFICE", "agent-card-TECH_SUPPORT"]);

  const ai = card(page, "AI_TRADER");
  await expect(ai).toContainText("AI Trader");
  await expect(ai).toContainText("Opportunity hunter");
  await expect(ai.getByTestId("agent-status")).toHaveText("IDLE");
  await expect(ai.getByTestId("agent-heartbeat")).toHaveText("♥ 41 min ago");
  await expect(ai.getByTestId("agent-task")).toHaveText("Idle · last: Market scan, 41 min ago");
  await expect(ai.getByTestId("agent-queue")).toHaveText("—");
  await expect(ai).toContainText("PHASE 3 · NO WORKER POOL");
  await expect(ai.getByTestId("agent-last-success")).toHaveText("11:01:11 · TASK-9e4b2a71…");
  await expect(ai.locator('[data-testid^="decision-"]')).toHaveCount(1);                                // the simulation scan is not desk work
  await expect(ai).toContainText("174 signals from 224 instruments (128 suppressed or skipped)");
  await expect(ai).not.toContainText("238 signals");
  await expect(ai.getByTestId("agent-errors")).toHaveText("0 errors · 0 retries in the last 1 desk task");

  const ta = card(page, "TRADING_ASSISTANT");
  await expect(ta).toContainText("Strategist and trader interface");
  await expect(ta.locator('[data-testid^="decision-"]')).toHaveText([
    "11:01 bull call spread on ADANIPORTS, size 3, loss 41210.25",
    "11:01 bull call spread on ADANIPORTS, size 4, loss 54947.00",
    "11:01 no plan for HINDALCO: BULL_CALL_SPREAD: the 760 CE did not trade on 2026-11-04",
  ]);
  await expect(ta.getByTestId("agent-errors")).toHaveText("0 errors · 1 retry in the last 5 desk tasks");
  await expect(card(page, "RISK_OPS")).toContainText("Risk & Operations");
  await expect(card(page, "RISK_OPS")).toContainText("Risk guardian");
  await expect(card(page, "RISK_OPS").getByTestId("agent-last-success")).toHaveText("11:01:17 · TRD-d4f2b0a8…");
  await expect(card(page, "TECH_SUPPORT").getByTestId("agent-task")).toHaveText("Idle · last: Pre-market health check, 41 min ago");
});

test("AD-UI-32 decision trace: the latest desk task by default, ten fields from the task row and handoffs; pick another decision", async ({ page }) => {
  await mockDesk(page, { routes: agentRoutes() });
  await page.goto("/autodesk/agents");
  const tr = page.getByTestId("decision-trace");
  await expect(tr.getByTestId("trace-eyebrow")).toHaveText("Decision trace · Middle Office");
  await expect(card(page, "MIDDLE_OFFICE")).toHaveAttribute("aria-pressed", "true");
  await expect(tr.getByTestId("trace-ref")).toHaveText("TRD-d4f2b0a8…");
  await expect(tr.getByTestId("trace-title")).toHaveText("NEEDS_HUMAN_APPROVAL: signal score 68.00 is below 70");
  await expect(trace(page, "requesting")).toContainText("Risk & Operations · handoff of TRD-d4f2b0a8…");
  await expect(trace(page, "receiving")).toContainText("Desk Orchestrator");
  await expect(trace(page, "input-references")).toContainText(`plan://${TRD.ADANIPORTS}@2 · assessment://RSK-4d6f8b0c2e3a45d7f9b1`);
  await expect(trace(page, "structured-output")).toContainText("APPROVAL DECISION · NEEDS_HUMAN_APPROVAL");
  await expect(trace(page, "evidence")).toContainText(`plan://${TRD.ADANIPORTS}@2`);
  await expect(trace(page, "tool-calls")).toContainText("None");
  await expect(trace(page, "validation")).toContainText("Schema ✓ · domain ✓");
  await expect(trace(page, "time-retries")).toContainText("38 ms · 0");
  await expect(trace(page, "handoff")).toContainText("None recorded in this workflow");
  await expect(trace(page, "decision")).toContainText("COMPLETED · NEEDS_HUMAN_APPROVAL: signal score 68.00 is below 70");
  await expect(tr).toContainText("Hidden model reasoning is neither stored nor shown.");

  await page.getByTestId(`decision-${T.TA_ADA}`).click();
  await expect(tr.getByTestId("trace-eyebrow")).toHaveText("Decision trace · Trading Assistant");
  await expect(card(page, "TRADING_ASSISTANT")).toHaveAttribute("aria-pressed", "true");
  await expect(tr.getByTestId("trace-title")).toHaveText("bull call spread on ADANIPORTS, size 4, loss 54947.00");
  await expect(trace(page, "requesting")).toContainText("AI Trader · handoff of SIG-c7e3a9b2…");
  await expect(trace(page, "receiving")).toContainText("Risk & Operations");
  await expect(trace(page, "structured-output")).toContainText("PLAN · Bull call spread · ADANIPORTS · max loss ₹54,947.00");
  await expect(trace(page, "tool-calls")).toContainText("5 calls · market.options ×1 · market.expiries ×1 · market.lot_size ×1 · +2 more");
  await expect(trace(page, "time-retries")).toContainText("572 ms · 0");
  await expect(trace(page, "handoff")).toContainText("Risk & Operations · TRD-d4f2b0a8…");

  await card(page, "AI_TRADER").click();
  await expect(tr.getByTestId("trace-eyebrow")).toHaveText("Decision trace · AI Trader");
  await expect(tr.getByTestId("trace-title")).toHaveText("174 signals from 224 instruments (128 suppressed or skipped)");
  await expect(trace(page, "requesting")).toContainText(`Desk Orchestrator · Market scan ${SCAN_WF.slice(0, 11)}…`);
  await expect(trace(page, "structured-output")).toContainText("SCAN REPORT · 174 signals · 224 instruments · 128 suppressed or skipped");
  await expect(trace(page, "tool-calls")).toContainText("444 calls · market.daily_bars ×221 · market.sector ×221 · market.index_bars ×1 · +1 more");
  await expect(trace(page, "time-retries")).toContainText("8.9 s · 0");
  await expect(trace(page, "input-references")).toContainText("—");
});

test("AD-UI-33 permissions from the descriptor, model and config, human escalation", async ({ page }) => {
  await mockDesk(page, { routes: agentRoutes() });
  await page.goto("/autodesk/agents");
  const perm = page.getByTestId("agent-permissions");
  await expect(perm.getByTestId("perm-allow")).toHaveText(["✓ Approval review"]);
  await expect(perm.getByTestId("perm-deny")).toHaveText(["× alter fills", "× bypass the gateway", "× change risk limits"]);
  await expect(page.getByTestId("agent-model")).toHaveText("autodesk-mo-v1 · deterministic · model — · prompt —");
  await expect(page.getByTestId("agent-escalation")).toContainText("On an assisted account a person approves every plan.");
  await expect(page.getByTestId("agent-escalation")).toContainText("0 escalated tasks in the last 3 desk tasks.");

  await card(page, "AI_TRADER").click();
  await expect(perm.getByTestId("perm-allow")).toHaveCount(8);
  await expect(perm.getByTestId("perm-allow").first()).toHaveText("✓ Market scan");
  await expect(perm).toContainText("✓ market.fno_buildup");
  await expect(perm.getByTestId("perm-deny")).toHaveText(["× size positions", "× approve", "× execute"]);
  await expect(page.getByTestId("agent-model")).toHaveText("autodesk-ait-v1 · deterministic · model — · prompt —");
});

test("AD-UI-34 workflows in flight against the 13-step workflow (desk only; Phase 1 ends at step 5)", async ({ page }) => {
  await mockDesk(page, { routes: agentRoutes() });
  await page.goto("/autodesk/agents");
  const box = page.getByTestId("workflows-in-flight");
  const flows = box.locator('[data-testid^="flow-WF-"]');
  await expect(flows).toHaveCount(4);                                  // the simulation's proposal is not listed
  const order = await flows.evaluateAll((els) => els.map((e) => e.getAttribute("data-testid")));
  expect(order).toEqual([`flow-${WFP.GRASIM}`, `flow-${WFP.ADANIPORTS}`, `flow-${WFP.HINDALCO}`, `flow-${WFP.PETRONET}`]);

  const fills = async (id: string) => box.getByTestId(`flow-${id}`).locator("[data-step]").evaluateAll((els) => els.map((e) => e.getAttribute("data-fill")));
  const g = box.getByTestId(`flow-${WFP.GRASIM}`);
  await expect(g.getByTestId("flow-name")).toHaveText("GRASIM · Bull call spread");
  await expect(g.getByTestId("flow-at")).toHaveText("Step 5 · waiting on you");
  expect(await fills(WFP.GRASIM)).toEqual(["done", "done", "done", "done", "current", ...Array(8).fill("none")]);
  await expect(g.locator('[data-step="4"]')).toHaveAttribute("title", "Revision · not needed");

  const a = box.getByTestId(`flow-${WFP.ADANIPORTS}`);
  await expect(a.getByTestId("flow-at")).toHaveText("Step 5 · rejected by person");
  await expect(a.locator('[data-step="4"]')).toHaveAttribute("title", "Revision");

  const h = box.getByTestId(`flow-${WFP.HINDALCO}`);
  await expect(h.getByTestId("flow-name")).toHaveText("HINDALCO · Long buildup signal");     // no plan: named from its signal
  await expect(h.getByTestId("flow-at")).toHaveText("Step 2 · no plan (NO_TRADE)");
  expect(await fills(WFP.HINDALCO)).toEqual(["done", "current", ...Array(11).fill("none")]);

  const p = box.getByTestId(`flow-${WFP.PETRONET}`);
  await expect(p.getByTestId("flow-at")).toHaveText("Approved · Phase 1 ends at step 5");
  expect(await fills(WFP.PETRONET)).toEqual([...Array(5).fill("done"), ...Array(8).fill("none")]);
  await expect(p.locator('[data-step="6"]')).toHaveAttribute("title", "Capital reservation · Phase 2");
  await expect(page.getByTestId("flows-phase-note")).toContainText("Phase 1 ends at step 5");
  await expect(page.getByTestId("flows-phase-note")).toContainText("Phase 2");
});

test("AD-UI-35 empty states: an agent without desk tasks, no proposal workflows", async ({ page }) => {
  await mockDesk(page, {
    routes: agentRoutes({
      "GET /agents/:agent_key/activity": (r) => (r.params.agent_key === "TECH_SUPPORT" ? [] : ACTIVITY[r.params.agent_key] ?? []),
      "GET /desk/workflows": [],
    }),
  });
  await page.goto("/autodesk/agents");
  const ts = card(page, "TECH_SUPPORT");
  await expect(ts.getByTestId("agent-task")).toHaveText("No desk tasks yet");
  await expect(ts).toContainText("None yet");
  await expect(ts.getByTestId("agent-last-success")).toHaveText("—");
  await expect(page.getByTestId("flows-empty")).toContainText("No trade proposal workflows on the desk yet");
  await ts.click();
  await expect(page.getByTestId("trace-empty")).toContainText("No desk task for Tech Support yet.");
});

test("AD-UI-35 empty registry", async ({ page }) => {
  await mockDesk(page, { routes: agentRoutes({ "GET /agents": [] }) });
  await page.goto("/autodesk/agents");
  await expect(page.getByTestId("agents-headline")).toHaveText("No agents are registered yet.");
  await expect(page.getByTestId("agents-empty")).toBeVisible();
  await expect(page.getByTestId("legend-IDLE")).toHaveText("IDLE 0");
});

test("AD-UI-36 API errors: registry, one agent's activity, the trace's workflow", async ({ page }) => {
  await mockDesk(page, { routes: agentRoutes({ "GET /agents": reply(500, { detail: "agent registry unavailable" }) }) });
  await page.goto("/autodesk/agents");
  await expect(page.getByTestId("error-box").first()).toContainText("agent registry unavailable (500)", { timeout: 15000 });
  await expect(page.locator('[data-testid^="agent-card-"]')).toHaveCount(0);

  await page.unrouteAll({ behavior: "ignoreErrors" });
  await mockDesk(page, {
    routes: agentRoutes({
      "GET /agents/:agent_key/activity": (r) => (r.params.agent_key === "RISK_OPS" ? reply(500, { detail: "task store timeout" }) : ACTIVITY[r.params.agent_key] ?? []),
      "GET /desk/workflows/:id": reply(404, { error: "NOT_FOUND", message: `not found: ${WFP.ADANIPORTS}` }),
    }),
  });
  await page.reload();
  await expect(card(page, "RISK_OPS").getByTestId("agent-activity-error")).toContainText("task store timeout (500)", { timeout: 15000 });
  await expect(card(page, "AI_TRADER").getByTestId("agent-task")).toBeVisible();
  const tr = page.getByTestId("decision-trace");
  await expect(tr.getByTestId("error-box")).toContainText(`not found: ${WFP.ADANIPORTS} (404)`);
  await expect(tr.getByTestId("trace-title")).toHaveText("NEEDS_HUMAN_APPROVAL: signal score 68.00 is below 70");
});

test("AD-UI-37 no sample figures or ids from the prototype; later-phase blocks are labelled", async ({ page }) => {
  await mockDesk(page, { routes: agentRoutes() });
  await page.goto("/autodesk/agents");
  await expect(page.locator('[data-testid^="agent-card-"]')).toHaveCount(5);
  await expect(page.getByTestId("workflows-in-flight").locator('[data-testid^="flow-WF-"]')).toHaveCount(4);
  const text = await page.getByTestId("screen-agents").innerText();
  for (const s of ["SIG-10267", "PLN-2045", "RSK-5530", "APR-3107", "INC-0311", "9 instances", "BSE feed", "187 of 212", "WF-88430", "signal-v1.4", "ZX4821"]) {
    expect(text, s).not.toContain(s);
  }
  await expect(page.getByTestId("agent-queue")).toHaveText(["—", "—", "—", "—", "—"]);
  expect(text).toContain("PHASE 3 · NO WORKER POOL");
});

test("AD-UI-38 phone 390×844: single column, no horizontal overflow", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await mockDesk(page, { routes: agentRoutes() });
  await page.goto("/autodesk/agents");
  await expect(page.getByTestId("desk-mobile")).toBeVisible();
  await expect(page.locator('[data-testid^="agent-card-"]')).toHaveCount(5);
  const a = await card(page, "AI_TRADER").boundingBox();
  const b = await card(page, "TRADING_ASSISTANT").boundingBox();
  expect(b!.y).toBeGreaterThan(a!.y + a!.height - 1);                  // stacked, one per row
  const tr = await page.getByTestId("decision-trace").boundingBox();
  const perm = await page.getByTestId("agent-permissions").boundingBox();
  expect(perm!.y).toBeGreaterThan(tr!.y + tr!.height - 1);
  await expect(page.getByTestId(`flow-${WFP.GRASIM}`)).toBeVisible();
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow).toBeLessThanOrEqual(0);
});

test("AD-UI-39 read-only: no request body is sent, only desk API calls, no console errors", async ({ page }) => {
  const other: string[] = [];
  page.on("request", (r) => {
    const u = new URL(r.url());
    if (/fonts\.(googleapis|gstatic)\.com/.test(u.host)) return;
    if (u.pathname.startsWith("/autodesk/")) return;
    if (u.pathname === "/api/auth/me" || u.pathname === "/api/live/quotes") return;
    other.push(u.pathname);
  });
  const errors = collectConsoleErrors(page);
  const desk = await mockDesk(page, { routes: agentRoutes() });
  await page.goto("/autodesk/agents");
  await expect(page.getByTestId("decision-trace").getByTestId("trace-decision")).toBeVisible();
  await page.getByTestId(`decision-${T.MO_PET}`).click();
  await expect(page.getByTestId("decision-trace").getByTestId("trace-title")).toContainText("APPROVED: within the autonomy rules");
  expect(desk.posts).toEqual([]);
  expect(desk.unmatched.filter((u) => !u.startsWith("GET /desk/workflows/"))).toEqual([]);
  expect(desk.requests.some((r) => r.path.startsWith(`/signals/${SIG.HINDALCO}`))).toBe(true);
  expect(other).toEqual([]);
  expect(errors).toEqual([]);
});
