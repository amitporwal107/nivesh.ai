/**
 * Simulation studio · Agent trace (AD-UI-150..159). Test cases: docs/autodesk/ui_testcases/studio-trace.md.
 * API answered by route mocks (autodesk-mock.ts + autodesk-fixtures-studio-trace.ts — MOCK, shapes of the real API).
 * The view sends no POST. Most cases emulate prefers-reduced-motion so the replay starts paused and is stepped by hand.
 */
import { expect, test, type Page } from "@playwright/test";
import { collectConsoleErrors, mockDesk, reply, type RouteValue } from "./autodesk-mock";
import { BY_INST, EMPTY_SID, SID, sigId, traceRoutes, trdId, wfId } from "./autodesk-fixtures-studio-trace";

async function open(page: Page, routes: Record<string, RouteValue>, opts: { path?: string; motion?: boolean } = {}) {
  if (!opts.motion) await page.emulateMedia({ reducedMotion: "reduce" });
  const desk = await mockDesk(page, { routes });
  await page.goto(opts.path ?? "/autodesk/studio/trace");
  await expect(page.getByTestId("studio-trace")).toBeVisible();
  return desk;
}

const ADA = BY_INST.ADANIPORTS;
const meta = (page: Page, k: string) => page.getByTestId("trace-meta").filter({ has: page.locator(`span:text-is("${k}")`) });
const payload = (page: Page) => page.getByTestId("trace-payload");
const stepN = (page: Page) => page.getByTestId("trace-stepn");

test("AD-UI-150 header, task cards of the run's proposal chains, the revised chain picked first", async ({ page }) => {
  const errors = collectConsoleErrors(page);
  const desk = await open(page, traceRoutes());
  await expect(page.getByTestId("trace-eyebrow")).toHaveText(`Agent trace replay · ${SID}`);
  await expect(page.getByTestId("studio-trace")).toContainText("Structured messages only");
  await expect(page.getByTestId("studio-trace").locator("h1")).toHaveText("Replay one task, message by message, as the agents handed it on.");
  const cards = page.getByTestId("trace-card");
  await expect(cards).toHaveCount(6);
  const want: [string, string, string, string][] = [
    ["TRD-petronet…", "4 STEPS", "PETRONET · Bull call spread", "2 Nov · approved"],
    ["TRD-grasim02…", "4 STEPS", "GRASIM · Bull call spread", "2 Nov · waiting on a person"],
    ["TRD-adanipor…", "6 STEPS", "ADANIPORTS · Bull call spread", "2 Nov · waiting on a person"],
    ["WF-hindalco…", "2 STEPS", "HINDALCO", "2 Nov · no plan"],
    ["TRD-dlf030d1…", "3 STEPS", "DLF · Bear put spread", "3 Nov · failed"],
    ["TRD-tatastee…", "4 STEPS", "TATASTEEL · Bear put spread", "3 Nov · approved"],
  ];
  for (let i = 0; i < want.length; i++) for (const t of want[i]) await expect(cards.nth(i)).toContainText(t);
  await expect(cards.nth(2)).toHaveAttribute("aria-pressed", "true");
  await expect(cards.nth(2)).toHaveAttribute("data-wf", wfId(ADA));
  await expect(stepN(page)).toHaveText("STEP 1 OF 6");
  expect(desk.posts).toEqual([]);
  expect(desk.unmatched).toEqual([]);
  expect(errors).toEqual([]);
});

test("AD-UI-151 step through the revised chain: messages, structured output, tools, inputs, validation, handoff", async ({ page }) => {
  await open(page, traceRoutes());
  const msgs = page.getByTestId("trace-msg");
  await expect(stepN(page)).toHaveText("STEP 1 OF 6");
  await expect(msgs).toHaveCount(1);
  await expect(msgs.nth(0).getByTestId("trace-msg-route")).toHaveText("AI TRADER → TRADING ASSISTANT");
  await expect(msgs.nth(0).getByTestId("trace-msg-type")).toHaveText("SIGNAL");
  await expect(msgs.nth(0)).toContainText("SIG-adanipor… · ADANIPORTS · Short covering · score 68");
  await expect(page.getByTestId("trace-detail-step")).toHaveText("Step 1 · SIGNAL");
  await expect(payload(page)).toContainText("ADANIPORTS · NSE FUTURES");
  await expect(payload(page)).toContainText("not calibrated");
  await expect(page.getByTestId("trace-tools")).toContainText("The scan's tool calls belong to the market-scan workflow");
  await expect(page.getByTestId("trace-waiting")).toHaveText("5 more steps · press › or Play");
  await expect(page.getByTestId("trace-play")).toHaveText("Play");

  await page.getByTestId("trace-next").click();
  await expect(stepN(page)).toHaveText("STEP 2 OF 6");
  await expect(msgs).toHaveCount(2);
  await expect(msgs.nth(1)).toHaveAttribute("data-selected", "true");
  await expect(msgs.nth(1).getByTestId("trace-msg-route")).toHaveText("TRADING ASSISTANT → RISK & OPERATIONS");
  await expect(msgs.nth(1).getByTestId("trace-msg-type")).toHaveText("PLAN");
  await expect(msgs.nth(1)).toContainText("bull call spread on ADANIPORTS, size 4, loss 54947.00");
  await expect(msgs.nth(1)).toContainText("09:00:00");
  await expect(page.getByTestId("trace-detail")).toContainText("TRADING ASSISTANT → RISK & OPERATIONS · 09:00:00 · 572 ms");
  await expect(page.getByTestId("trace-verdict")).toHaveText("PLAN");
  for (const t of ["decision", "PLAN", "ADANIPORTS · OPTIONS", "Bull call spread", "BUY 4×475 ADANIPORTS26NOV1400CE @ 32.10 · SELL 4×475 ADANIPORTS26NOV1440CE @ 17.20", "₹54,947.00", "1 considered"]) await expect(payload(page)).toContainText(t);
  const tools = page.getByTestId("trace-tool");
  await expect(tools).toHaveCount(5);
  await expect(tools.nth(0).locator("span")).toHaveText(["market.options", "ok · 214 rows", "412 ms"]);
  await expect(meta(page, "Inputs")).toContainText(`signal://${sigId(ADA)}`);
  await expect(meta(page, "Validation")).toContainText("Schema ✓ · domain ✓");
  await expect(meta(page, "State · retries")).toContainText("COMPLETED · 0");
  await expect(meta(page, "Handoff")).toContainText("Risk & Operations · TRD-adanipor…");

  await page.getByTestId("trace-next").click();
  await expect(stepN(page)).toHaveText("STEP 3 OF 6");
  await expect(msgs.nth(2).getByTestId("trace-msg-type")).toHaveText("RISK REDUCE");
  await expect(msgs.nth(2)).toContainText("REDUCE: failed checks per_trade_risk; passes at 3 lots");
  await expect(page.getByTestId("trace-verdict")).toHaveText("REDUCE");
  await expect(payload(page)).toContainText("14 · 13 pass · 0 warn · 1 fail");
  await expect(payload(page)).toContainText("per_trade_risk");
  await expect(meta(page, "Inputs")).toContainText(`plan://${trdId(ADA)}@1`);
  await expect(meta(page, "Handoff")).toContainText("Trading Assistant · TRD-adanipor…");
  await expect(page.getByTestId("trace-progress")).toHaveAttribute("style", /width: 50%/);

  await page.getByTestId("trace-prev").click();
  await expect(stepN(page)).toHaveText("STEP 2 OF 6");
  await expect(msgs).toHaveCount(3);
  await expect(msgs.nth(1)).toHaveAttribute("data-selected", "true");
  await msgs.nth(0).click();
  await expect(stepN(page)).toHaveText("STEP 1 OF 6");
  await expect(page.getByTestId("trace-detail-step")).toHaveText("Step 1 · SIGNAL");
});

test("AD-UI-152 the last step shows the workflow's outcome and the Phase 2 note; Restart", async ({ page }) => {
  await open(page, traceRoutes());
  for (let i = 0; i < 5; i++) await page.getByTestId("trace-next").click();
  await expect(stepN(page)).toHaveText("STEP 6 OF 6");
  const last = page.getByTestId("trace-msg").nth(5);
  await expect(last.getByTestId("trace-msg-route")).toHaveText("MIDDLE OFFICE → DESK ORCHESTRATOR");
  await expect(last.getByTestId("trace-msg-type")).toHaveText("NEEDS HUMAN");
  await expect(last).toContainText("NEEDS_HUMAN_APPROVAL: signal score 68.00 is below 70");
  await expect(page.getByTestId("trace-verdict")).toHaveText("NEEDS_HUMAN_APPROVAL");
  await expect(payload(page)).toContainText("MIDDLE_OFFICE@autodesk-mo-v1");
  await expect(meta(page, "Handoff")).toContainText("None — the chain ends here");
  await expect(page.getByTestId("trace-tools")).toContainText("No tool calls; deterministic decision on its inputs.");
  await expect(page.getByTestId("trace-waiting")).toHaveCount(0);
  await expect(page.getByTestId("trace-outcome")).toContainText("Workflow WAITING_HUMAN · WAITING HUMAN");
  await expect(page.getByTestId("trace-phase2")).toContainText("Phase 2");
  await expect(page.getByTestId("trace-progress")).toHaveAttribute("style", /width: 100%/);
  await expect(page.getByTestId("trace-play")).toHaveText("Replay");
  await page.getByTestId("trace-restart").click();
  await expect(stepN(page)).toHaveText("STEP 1 OF 6");
  await expect(page.getByTestId("trace-msg")).toHaveCount(1);
});

test("AD-UI-153 autoplay plays to the end; Pause stops it", async ({ page }) => {
  await open(page, traceRoutes(), { motion: true });
  await expect(page.getByTestId("trace-play")).toHaveText("Pause");
  await expect(stepN(page)).toHaveText("STEP 6 OF 6", { timeout: 15000 });
  await expect(page.getByTestId("trace-play")).toHaveText("Replay");
  await expect(page.getByTestId("trace-msg")).toHaveCount(6);
  await page.getByTestId("trace-restart").click();
  await page.getByTestId("trace-play").click();
  await expect(page.getByTestId("trace-play")).toHaveText("Play");
  const at = await stepN(page).innerText();
  await page.waitForTimeout(3000);
  await expect(stepN(page)).toHaveText(at);
  expect(at).not.toBe("STEP 6 OF 6");
});

test("AD-UI-154 other chains: no plan at the strategy stage; a failed risk task with its error", async ({ page }) => {
  await open(page, traceRoutes());
  await page.getByTestId("trace-card").nth(3).click();
  await expect(stepN(page)).toHaveText("STEP 1 OF 2");
  await page.getByTestId("trace-next").click();
  const m = page.getByTestId("trace-msg").nth(1);
  await expect(m.getByTestId("trace-msg-type")).toHaveText("NO TRADE");
  await expect(m).toContainText("no plan for HINDALCO: BULL_CALL_SPREAD: the 760 CE did not trade on 2026-11-02");
  await expect(page.getByTestId("trace-verdict")).toHaveText("NO_TRADE");
  await expect(payload(page)).toContainText("BULL_CALL_SPREAD: the 760 CE did not trade on 2026-11-02");
  await expect(page.getByTestId("trace-outcome")).toContainText("Workflow COMPLETED · NO TRADE");
  await expect(page.getByTestId("trace-outcome")).toContainText("BULL_CALL_SPREAD: the 760 CE did not trade on 2026-11-02");
  await expect(page.getByTestId("trace-phase2")).toHaveCount(0);

  await page.getByTestId("trace-card").nth(4).click();
  await expect(stepN(page)).toHaveText("STEP 1 OF 3");
  await page.getByTestId("trace-next").click();
  await page.getByTestId("trace-next").click();
  const f = page.getByTestId("trace-msg").nth(2);
  await expect(f.getByTestId("trace-msg-route")).toHaveText("RISK & OPERATIONS → DESK ORCHESTRATOR");
  await expect(f.getByTestId("trace-msg-type")).toHaveText("ASSESS RISK");
  await expect(f).toContainText("TimeoutError: market.daily_bars read timed out (deadline 30 s)");
  await expect(page.getByTestId("trace-verdict")).toHaveText("FAILED");
  await expect(page.getByTestId("trace-detail-x")).toHaveText("TimeoutError: market.daily_bars read timed out (deadline 30 s)");
  await expect(meta(page, "Error")).toContainText("TimeoutError: market.daily_bars read timed out (deadline 30 s)");
  await expect(meta(page, "State · retries")).toContainText("FAILED · 1");
  await expect(meta(page, "Validation")).toContainText("—");
  await expect(page.getByTestId("trace-tool").nth(0).locator("span")).toHaveText(["market.daily_bars", "timed out", "30.0 s"]);
  await expect(page.getByTestId("trace-detail")).toContainText("No structured output stored for this step.");
  await expect(page.getByTestId("trace-outcome")).toContainText("Workflow FAILED · FAILED");
  await expect(page.getByTestId("trace-outcome")).toContainText("risk task: TimeoutError: market.daily_bars read timed out (deadline 30 s)");
});

test("AD-UI-155 more than six proposals: the select picks any, and its card is added", async ({ page }) => {
  await open(page, traceRoutes());
  const sel = page.getByTestId("trace-select");
  await expect(sel.locator("option")).toHaveCount(7);
  await expect(sel.locator("option").nth(6)).toHaveText("3 Nov · ONGC · Bear call spread · approved");
  await sel.selectOption(wfId(BY_INST.ONGC));
  await expect(page.getByTestId("trace-card")).toHaveCount(7);
  await expect(page.getByTestId("trace-card").nth(6)).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByTestId("trace-card").nth(6)).toContainText("ONGC · Bear call spread");
  await expect(stepN(page)).toHaveText("STEP 1 OF 4");
  await expect(page.getByTestId("trace-msg").nth(0)).toContainText("ONGC · Long unwinding · score 70.75");
});

test("AD-UI-156/159 empty states, and ?sim= decides the run", async ({ page }) => {
  const desk = await open(page, traceRoutes(), { path: `/autodesk/studio/trace?sim=${EMPTY_SID}` });
  await expect(page.getByTestId("trace-eyebrow")).toHaveText(`Agent trace replay · ${EMPTY_SID}`);
  await expect(page.getByTestId("trace-empty")).toContainText("No trade proposals in this run yet.");
  await expect(page.getByTestId("trace-empty").locator("a")).toHaveAttribute("href", `/autodesk/studio?sim=${EMPTY_SID}`);
  await expect(page.getByTestId("trace-card")).toHaveCount(0);
  expect(desk.requests.some((r) => r.path === `/simulations/${EMPTY_SID}/workflows`)).toBe(true);
  expect(desk.requests.some((r) => r.path === `/simulations/${SID}/workflows`)).toBe(false);

  await page.unrouteAll({ behavior: "ignoreErrors" });
  await mockDesk(page, { routes: traceRoutes({ "GET /simulations": [] }) });
  await page.goto("/autodesk/studio/trace");
  await expect(page.getByTestId("trace-empty")).toContainText("No runs yet, so there is nothing to replay.");
  await expect(page.getByTestId("trace-empty").locator("a")).toHaveAttribute("href", "/autodesk/studio/new");
});

test("AD-UI-157 load errors: the run's workflows, and one workflow's detail", async ({ page }) => {
  await open(page, traceRoutes({ "GET /simulations/:sid/workflows": reply(500, { error: "INTERNAL", message: "workflow store unavailable" }) }));
  await expect(page.getByTestId("error-box")).toContainText("workflow store unavailable (500)", { timeout: 15000 });
  await expect(page.getByTestId("error-box")).toContainText(`Could not load the workflows of ${SID}`);

  await page.unrouteAll({ behavior: "ignoreErrors" });
  await mockDesk(page, { routes: traceRoutes({ "GET /desk/workflows/:id": ((r: { params: Record<string, string> }) => reply(404, { error: "NOT_FOUND", message: `not found: ${r.params.id}` })) as never }) });
  await page.goto("/autodesk/studio/trace");
  await expect(page.getByTestId("error-box")).toContainText(`not found: ${wfId(ADA)} (404)`);
  await expect(page.getByTestId("error-box")).toContainText("Could not load this workflow");
  await expect(page.getByTestId("trace-card").nth(0)).toContainText("— STEPS");
});

test("AD-UI-158 phone 390×844: single column, no overflow, no sample ids", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const errors = collectConsoleErrors(page);
  await open(page, traceRoutes());
  for (let i = 0; i < 5; i++) await page.getByTestId("trace-next").click();
  await expect(stepN(page)).toHaveText("STEP 6 OF 6");
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow).toBeLessThanOrEqual(0);
  const msgs = await page.getByTestId("trace-msgs").boundingBox();
  const aside = await page.getByTestId("trace-detail").boundingBox();
  expect(msgs && aside && aside.y > msgs.y).toBeTruthy();
  const text = await page.getByTestId("studio-trace").innerText();
  for (const sample of ["SIM-0418", "PLN-S-", "SCN-0", "AXISBANK", "RSV-S-"]) expect(text).not.toContain(sample);
  expect(errors).toEqual([]);
});
