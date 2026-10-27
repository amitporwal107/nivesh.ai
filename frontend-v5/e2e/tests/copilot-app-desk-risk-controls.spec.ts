/**
 * One-screen Copilot app (/v5/app) — Smart trading desk, More · Risk controls (?tab=more&view=risk;
 * screens/tradingdesk/RiskControls.tsx, risk-controls.ts) and the header's "Kill switch on" pill (TradingDesk.tsx).
 *
 * MOCK — not real data. Every /api/risk/* answer below is written by hand to the contract the backend PR
 * (feat/fno-risk-foundation) builds: backend/routes/risk_controls.py (status, kill-switch, halt, audit, decisions) plus
 * its policy route and the gate. User ids, reasons, symbols and correlation ids are INVENTED. The routes are stateful
 * like the real ones: a PUT changes the status and appends an audit event. Expected text is worked out here from the
 * payloads, not copied from the screen. Production build, every /api mocked — see pw.copilot-app.config.ts.
 *
 * Cases (test_reports/risk_control_center_TESTCASES.md): RC-1 navigation (TC-1) · RC-2 status off, modes, live
 * authorization, scope, trust (TC-2, TC-10, TC-11) · RC-3 status on and the header pill (TC-3, TC-12) · RC-4 trip with
 * reason and confirm (TC-4, TC-21) · RC-5 reset and the admin-only paths (TC-5, TC-20) · RC-6 halt (TC-6) · RC-7 policy
 * limits and the gate (TC-7, TC-15) · RC-8 decisions and audit (TC-8, TC-9, TC-17) · RC-9 empty lists (TC-14) · RC-10
 * unknown status shape (TC-15, TC-12) · RC-11 status 503 / 500 (TC-18, TC-19) · RC-12 part failures (TC-22) · RC-13 a
 * server 422 (TC-21) · RC-14 keyboard and labels (TC-23, TC-24) · RC-15 phone, long text (TC-16, TC-25, TC-12).
 * TC-13 (a paper write's 409 risk_blocked in words) is in copilot-app-desk-scanner.spec.ts beside the other 409 test.
 */
import { test, expect, type Page, type Route } from "@playwright/test";
import { mockApi, mockSingleRoute } from "../helpers/api-mock";

const DESK = "/v5/app/trader/desk";
const RISK = `${DESK}?tab=more&view=risk`;
// Desk redesign (2026-10-27): Risk controls is the Risk Desk, split into three views; the old URL above redirects to Limits.
const RISK_LIMITS = `${DESK}?tab=risk&view=limits`;
const RISK_CONTROLS = `${DESK}?tab=risk&view=controls`;
const RISK_LOG = `${DESK}?tab=risk&view=log`;

const reply = (route: Route, body: unknown, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
const inr = (n: number) => `₹${new Intl.NumberFormat("en-IN").format(Math.round(n))}`;

// ── the MOCK payloads ────────────────────────────────────────────────────

const SET_AT = "2026-10-24T04:30:00+00:00";      // 24 Oct, 10:00 IST
const SET_AT_IST = "24 Oct, 10:00 IST";
const CHANGED_AT = "2026-10-24T06:15:00+00:00";  // a PUT's own time: 24 Oct, 11:45 IST
const SCOPE = "blocks new positions on the AI-trader ticket, desk paper-trade and journal paths";
const NOT_IN_SCOPE = "no order is placed anywhere in this system, and open positions are untouched";

type Status = Record<string, unknown> & { kill_switch?: unknown; halted?: unknown };
/** GET /api/risk/status, off: nothing blocked, gate on, live not authorized. */
const status = (o: Record<string, unknown> = {}): Status => ({
  user_id: "u_fixture", kill_switch: false, halted: false, reason: null, set_by: null, set_at: null, policy_version: "risk-controls-v1",
  stored: false, scope: SCOPE, not_in_scope: NOT_IN_SCOPE, can_reset: false,
  live_authorization: { granted: false, granted_by: null, granted_at: null, reason: null },
  modes: ["paper", "shadow", "assisted", "live"], live_execution_available: false, gate: { enabled: true, policy_version: "fno-gate-v1" }, ...o,
});
const KILL_ON = { kill_switch: true, reason: "Too many losing trades today", set_by: "admin_fixture", set_at: SET_AT, stored: true };

/** GET /api/risk/policy: 2 of 5 structures open; ₹45,000 of ₹2,00,000 at risk. */
const POLICY = {
  policy_version: "fno-gate-v1",
  limits: { max_legs: 4, max_lots_per_leg: 10, max_open_structures: 5, max_capital_at_risk_rs: 200000, require_defined_risk: true },
  usage: { open_structures: 2, capital_at_risk_rs: 45000 },
};

/** GET /api/risk/decisions, sent OLDEST first so the screen's newest-first order is checked. d-001 is an old row whose outcome predates allow / block. */
const DECISIONS = {
  count: 3, append_only: true, policy_version: "risk-controls-v1",
  decisions: [
    { _id: "d-001", at: "2026-10-23T05:00:00+00:00", action: "desk_paper_trade", outcome: "reduced", path: "/api/desk/paper-trades", mode: "paper", symbol: "FIXOLD", reasons: [], correlation_id: "corr-old-0001" },
    { _id: "d-003", at: "2026-10-24T04:50:00+00:00", action: "journal_trade", outcome: "allow", path: "journal_trade", mode: "paper", symbol: "FIXOK", reasons: ["within every limit"], correlation_id: "corr-ok-0003" },
    {
      _id: "d-002", at: "2026-10-24T05:10:00+00:00", action: "desk_paper_trade", outcome: "block", path: "/api/desk/paper-trades", mode: "paper", symbol: "FIXBLK",
      reasons: [{ code: "max_legs", message: "The structure has 5 legs; the limit is 4." }, { code: "undefined_risk", message: "Only defined-risk structures are allowed." }],
      correlation_id: "corr-3f9a1c2e-7b4d-4e0a-9c55-0a1b2c3d4e5f",
    },
  ],
};
/** Newest first, worked out from the `at` values above: 24 Oct 05:10, 24 Oct 04:50, 23 Oct 05:00. */
const DECISION_ORDER = ["FIXBLK", "FIXOK", "FIXOLD"];

/** GET /api/risk/audit, oldest first. */
const AUDIT_EVENTS = [
  { _id: "a-1", at: "2026-10-22T06:00:00+00:00", actor: "u_fixture", action: "set_halted", field: "halted", before: false, after: true, reason: "Results week", policy_version: "risk-controls-v1" },
  { _id: "a-2", at: SET_AT, actor: "admin_fixture", action: "set_kill_switch", field: "kill_switch", before: false, after: true, reason: "Too many losing trades today", policy_version: "risk-controls-v1" },
];

interface Put { path: string; body: { enabled: boolean; reason: string } }
interface Calls { puts: Put[]; statusReads: number; auditReads: number }
type Reply = { status: number; body: unknown };

/**
 * The risk routes, stateful: a PUT sets the field, stamps who and when, and appends an audit event, as
 * services/risk_controls.py :: set_control does. Each option overrides one answer.
 */
async function riskMocks(page: Page, opts: {
  status?: Status; statusReply?: Reply; policy?: unknown; policyReply?: Reply; decisions?: unknown; decisionsReply?: Reply;
  audit?: unknown[]; auditReply?: Reply; putReply?: Reply;
} = {}): Promise<Calls> {
  const calls: Calls = { puts: [], statusReads: 0, auditReads: 0 };
  let state: Status = opts.status ?? status();
  let events = [...(opts.audit ?? AUDIT_EVENTS)];
  await page.route("**/api/risk/status", (route) => {
    calls.statusReads += 1;
    if (opts.statusReply) return reply(route, opts.statusReply.body, opts.statusReply.status);
    return reply(route, state);
  });
  const put = (field: "kill_switch" | "halted") => (route: Route) => {
    const req = route.request();
    const body = req.postDataJSON() as Put["body"];
    calls.puts.push({ path: new URL(req.url()).pathname, body });
    if (opts.putReply) return reply(route, opts.putReply.body, opts.putReply.status);
    events = [...events, { _id: `a-${events.length + 1}`, at: CHANGED_AT, actor: "u_fixture", action: `set_${field}`, field, before: Boolean(state[field]), after: body.enabled, reason: body.reason, policy_version: "risk-controls-v1" }];
    state = { ...state, [field]: body.enabled, reason: body.reason, set_by: "u_fixture", set_at: CHANGED_AT, stored: true };
    return reply(route, state);
  };
  await page.route("**/api/risk/kill-switch", put("kill_switch"));
  await page.route("**/api/risk/halt", put("halted"));
  await page.route("**/api/risk/policy", (route) => (opts.policyReply ? reply(route, opts.policyReply.body, opts.policyReply.status) : reply(route, opts.policy ?? POLICY)));
  await page.route("**/api/risk/decisions*", (route) => (opts.decisionsReply ? reply(route, opts.decisionsReply.body, opts.decisionsReply.status) : reply(route, opts.decisions ?? DECISIONS)));
  await page.route("**/api/risk/audit*", (route) => {
    calls.auditReads += 1;
    if (opts.auditReply) return reply(route, opts.auditReply.body, opts.auditReply.status);
    return reply(route, { events, count: events.length, append_only: true, policy_version: "risk-controls-v1" });
  });
  return calls;
}

/** The shell and the desk header's own reads. Everything else falls to mockApi's catch-all 200 {}. */
async function deskBase(page: Page) {
  await mockApi(page, "populated");
  await mockSingleRoute(page, "**/api/markets/home", "markets-home.json");
  await page.route("**/api/chat/sessions", (route) => route.fulfill({ status: 200, contentType: "application/json", body: "[]" }));
  await page.route("**/api/move-odds/**", (route) => reply(route, { detail: "feature_not_enabled" }, 403));
}

/** Writes (anything but GET) to /api/* made by the page. */
function recordWrites(page: Page): string[] {
  const writes: string[] = [];
  page.on("request", (req) => {
    const path = new URL(req.url()).pathname;
    if (req.method() !== "GET" && /\/api\//.test(path) && !path.startsWith("/api/copilot/widgets/")) writes.push(`${req.method()} ${path}`);
  });
  return writes;
}

async function noSideScroll(page: Page) {
  const o = await page.evaluate(() => {
    const sc = document.querySelector('[data-testid="copilot-scroll"]') as HTMLElement | null;
    return { doc: document.documentElement.scrollWidth - window.innerWidth, scroll: sc ? sc.scrollWidth - sc.clientWidth : 0 };
  });
  expect(o.doc).toBeLessThanOrEqual(1);
  expect(o.scroll).toBeLessThanOrEqual(1);
}

test.describe("MOCK — not real data: Smart trading desk · Risk controls", () => {
  test.beforeEach(async ({ page }) => {
    await deskBase(page);
  });

  // Superseded by the desk redesign (2026-10-27): there is no More list or More chip row. The old URL's redirect to Risk Desk
  // and the tabs are covered by copilot-app-desk-shell.spec.ts SH-9 / SH-3; rewritten in step 6.
  test.skip("RC-1 More lists Risk controls and opens ?tab=more&view=risk; its chip is pressed and the Copilot chip is not", async ({ page }) => {
    await riskMocks(page);
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto(`${DESK}?tab=more`);
    const item = page.getByTestId("desk-more-list").getByTestId("desk-more-item-risk");
    await expect(item).toContainText("Risk controls");
    await expect(item).toContainText("Kill switch, trading halt, policy limits and every risk decision on your paper trades");
    await item.click();
    await expect(page).toHaveURL(/[?&]tab=more(&|$)/);
    await expect(page).toHaveURL(/[?&]view=risk(&|$)/);
    const panel = page.getByRole("tabpanel", { name: "Risk controls" });
    await expect(panel).toHaveAttribute("data-testid", "desk-panel-risk");
    await expect(panel.getByTestId("risk-controls")).toBeVisible();
    await expect(page.getByTestId("risk-title")).toHaveText("Risk controls");
    await expect(page.getByTestId("desk-more-risk")).toHaveAttribute("aria-pressed", "true");
    await expect(page.getByTestId("desk-more-copilot")).toHaveAttribute("aria-pressed", "false");
    await expect(page.getByTestId("desk-tab-more")).toHaveAttribute("aria-selected", "true");

    // Under 1400px (no dock) the chip row reaches it too, and another tab leaves it.
    await page.setViewportSize({ width: 1280, height: 800 });
    await page.goto(`${DESK}?tab=more`);
    await page.getByTestId("desk-more-risk").click();
    await expect(page.getByTestId("desk-panel-risk")).toBeVisible();
    await page.getByTestId("desk-tab-overview").click();
    await expect(page).not.toHaveURL(/view=risk/);
    await expect(page.getByTestId("desk-panel-risk")).toHaveCount(0);
  });

  test("RC-2 status off: both controls in words and pills, the data modes, live authorization, the scope note and the trust line", async ({ page }) => {
    const writes = recordWrites(page);
    await riskMocks(page);
    await page.goto(RISK_CONTROLS);
    const kill = page.getByTestId("risk-kill");
    await expect(kill).toHaveAttribute("data-state", "off");
    await expect(kill.getByTestId("risk-kill-pill")).toHaveText("Off");
    await expect(kill.getByTestId("risk-kill-words")).toHaveText("Kill switch: off. The kill switch blocks nothing.");
    await expect(kill.getByTestId("risk-kill-on")).toHaveText("Turn kill switch on");
    const halt = page.getByTestId("risk-halt");
    await expect(halt.getByTestId("risk-halt-pill")).toHaveText("Not halted");
    await expect(halt.getByTestId("risk-halt-words")).toHaveText("Trading halt: not halted. The halt blocks nothing.");
    await expect(halt.getByTestId("risk-halt-on")).toHaveText("Halt trading");
    await expect(page.getByTestId("risk-last-none")).toHaveText("No change on record yet.");

    await expect(page.getByTestId("risk-mode-paper")).toHaveText("Paper");
    await expect(page.getByTestId("risk-modes")).toContainText("Active");
    // The route's modes other than paper, in its order.
    await expect(page.getByTestId("risk-mode-unavailable")).toHaveText("Shadow / Assisted / Live: not available");
    await expect(page.getByTestId("risk-live-auth")).toHaveAttribute("data-granted", "false");
    await expect(page.getByTestId("risk-live-auth-words")).toHaveText("Not authorized");

    await expect(page.getByTestId("risk-scope")).toHaveText(`Covers: ${SCOPE}.`);
    await expect(page.getByTestId("risk-scope-note")).toHaveText(`Not covered: ${NOT_IN_SCOPE}.`);
    await expect(page.getByTestId("risk-trust-status")).toHaveText("Risk controls · risk-controls-v1");
    await expect(page.getByTestId("risk-gate-on")).toHaveText("Gate on");
    // Off: no header pill, and reading the screen writes nothing.
    await expect(page.getByTestId("desk-risk-pill")).toHaveCount(0);
    await page.waitForTimeout(300);
    expect(writes).toEqual([]);
  });

  test("RC-3 status on: the reason, who set it and when; authorized by; the header pill opens the view", async ({ page }) => {
    await riskMocks(page, { status: status({ ...KILL_ON, live_authorization: { granted: true, granted_by: "admin_fixture", granted_at: SET_AT, reason: "Fixture authorization" } }) });
    await page.goto(`${DESK}?tab=overview`);
    const pill = page.getByTestId("desk-topbar").getByTestId("desk-risk-pill");
    await expect(pill).toHaveText("Kill switch on");
    await expect(pill).toHaveAttribute("data-control", "kill_switch");
    await pill.click();
    await expect(page).toHaveURL(/[?&]tab=risk&view=controls(&|$)/); // was ?tab=more&view=risk before the 2026-10-27 redesign

    const kill = page.getByTestId("risk-kill");
    await expect(kill).toHaveAttribute("data-state", "on");
    await expect(kill.getByTestId("risk-kill-pill")).toHaveText("On");
    await expect(kill.getByTestId("risk-kill-words")).toHaveText("Kill switch: on. New paper positions are blocked.");
    await expect(page.getByTestId("risk-last-reason")).toHaveText(`“${KILL_ON.reason}”`);
    await expect(page.getByTestId("risk-last-by")).toHaveText(KILL_ON.set_by);
    await expect(page.getByTestId("risk-last-at")).toHaveText(SET_AT_IST);
    await expect(page.getByTestId("risk-live-auth")).toHaveAttribute("data-granted", "true");
    await expect(page.getByTestId("risk-live-auth-words")).toHaveText(`Authorized by admin_fixture · ${SET_AT_IST}`);
    await expect(page.getByTestId("risk-live-auth")).toContainText("Authorization alone places nothing: live execution is not available.");

    // Halted with the kill switch off: the pill names the halt.
    await page.unroute("**/api/risk/status");
    await page.route("**/api/risk/status", (route) => reply(route, status({ halted: true, reason: "Results week", set_by: "u_fixture", set_at: SET_AT })));
    await page.goto(`${DESK}?tab=overview`);
    await expect(page.getByTestId("desk-risk-pill")).toHaveText("Trading halted");
    await expect(page.getByTestId("desk-risk-pill")).toHaveAttribute("data-control", "halted");
  });

  test("RC-4 trip: a reason is required, a confirmation follows, then exactly one PUT; Cancel sends nothing; the status re-reads", async ({ page }) => {
    const writes = recordWrites(page);
    const calls = await riskMocks(page, { audit: [] });
    await page.goto(RISK_CONTROLS);
    const kill = page.getByTestId("risk-kill");

    // Cancel at the reason step.
    await kill.getByTestId("risk-kill-on").click();
    await expect(kill.getByTestId("risk-kill-reason")).toBeFocused();
    await kill.getByTestId("risk-kill-cancel").click();
    await expect(kill.getByTestId("risk-kill-form")).toHaveCount(0);

    // An empty (or blank) reason is refused in the form; nothing is sent.
    await kill.getByTestId("risk-kill-on").click();
    await kill.getByTestId("risk-kill-reason").fill("   ");
    await kill.getByTestId("risk-kill-continue").click();
    await expect(kill.getByTestId("risk-kill-reason-error")).toHaveText("Give a reason: it is recorded with the change.");
    await expect(kill.getByTestId("risk-kill-reason")).toHaveAttribute("aria-invalid", "true");
    await expect(kill.getByTestId("risk-kill-confirm")).toHaveCount(0);

    // A reason, then the confirmation; Cancel there sends nothing either.
    await kill.getByTestId("risk-kill-reason").fill("  Stop for today  ");
    await expect(kill.getByTestId("risk-kill-reason-error")).toHaveCount(0);
    await kill.getByTestId("risk-kill-continue").click();
    const confirm = kill.getByTestId("risk-kill-confirm");
    await expect(confirm).toContainText("Turn the kill switch on? New paper positions stay blocked until an admin turns it off. Open positions are untouched.");
    await expect(confirm.getByTestId("risk-kill-confirm-reason")).toHaveText("Reason: “Stop for today”");
    await expect(confirm.getByTestId("risk-kill-confirm-no")).toBeFocused();
    await confirm.getByTestId("risk-kill-confirm-no").click();
    await expect(confirm).toHaveCount(0);
    expect(calls.puts).toHaveLength(0);

    // Through to the end: one PUT with the trimmed reason.
    await kill.getByTestId("risk-kill-on").click();
    await kill.getByTestId("risk-kill-reason").fill("Stop for today");
    await kill.getByTestId("risk-kill-continue").click();
    const reads = calls.statusReads;
    await kill.getByTestId("risk-kill-confirm-yes").click();
    await expect.poll(() => calls.puts.length).toBe(1);
    expect(calls.puts[0]).toEqual({ path: "/api/risk/kill-switch", body: { enabled: true, reason: "Stop for today" } });
    await expect(kill.getByTestId("risk-kill-done")).toHaveText("Kill switch turned on. The change is recorded below.");
    await expect.poll(() => calls.statusReads).toBeGreaterThan(reads);
    await expect(kill.getByTestId("risk-kill-pill")).toHaveText("On");
    // can_reset is false: no way to turn it back off here.
    await expect(kill.getByTestId("risk-kill-off")).toHaveCount(0);
    await expect(kill.getByTestId("risk-kill-admin-only")).toHaveText("Only an admin can turn the kill switch off.");
    // The audit re-reads and shows the change; the header pill appears.
    await expect(page.getByTestId("risk-audit-event")).toHaveCount(1);
    await expect(page.getByTestId("risk-audit-change")).toHaveText("Kill switch: off → on");
    await expect(page.getByTestId("risk-audit-reason")).toHaveText("“Stop for today”");
    await expect(page.getByTestId("desk-risk-pill")).toHaveText("Kill switch on");
    expect(writes).toEqual(["PUT /api/risk/kill-switch"]);
  });

  test("RC-5 reset: absent without can_reset; with it, one PUT {enabled:false}; a 403 admin_required says only an admin can", async ({ page }) => {
    const calls = await riskMocks(page, { status: status({ ...KILL_ON, can_reset: true }) });
    await page.goto(RISK_CONTROLS);
    const kill = page.getByTestId("risk-kill");
    await expect(kill.getByTestId("risk-kill-admin-only")).toHaveCount(0);
    await kill.getByTestId("risk-kill-off").click();
    await kill.getByTestId("risk-kill-reason").fill("Reviewed; resume");
    await kill.getByTestId("risk-kill-continue").click();
    await expect(kill.getByTestId("risk-kill-confirm")).toContainText("Turn the kill switch off? New paper positions are allowed again unless trading is halted.");
    await expect(kill.getByTestId("risk-kill-confirm-yes")).toHaveText("Turn kill switch off");
    await kill.getByTestId("risk-kill-confirm-yes").click();
    await expect.poll(() => calls.puts.length).toBe(1);
    expect(calls.puts[0]).toEqual({ path: "/api/risk/kill-switch", body: { enabled: false, reason: "Reviewed; resume" } });
    await expect(kill.getByTestId("risk-kill-pill")).toHaveText("Off");
    await expect(kill.getByTestId("risk-kill-done")).toHaveText("Kill switch turned off. The change is recorded below.");
    await expect(page.getByTestId("desk-risk-pill")).toHaveCount(0);
  });

  test("RC-5b a 403 admin_required on reset keeps the confirmation open with the admin message", async ({ page }) => {
    // The status says can_reset (stale), the server refuses: the server's answer wins.
    const calls = await riskMocks(page, { status: status({ ...KILL_ON, can_reset: true }), putReply: { status: 403, body: { detail: { code: "admin_required" } } } });
    await page.goto(RISK_CONTROLS);
    const kill = page.getByTestId("risk-kill");
    await kill.getByTestId("risk-kill-off").click();
    await kill.getByTestId("risk-kill-reason").fill("Try to clear");
    await kill.getByTestId("risk-kill-continue").click();
    await kill.getByTestId("risk-kill-confirm-yes").click();
    await expect(kill.getByTestId("risk-kill-confirm-error")).toHaveText("Only an admin can turn this off. (admin_required)");
    await expect(kill.getByTestId("risk-kill-confirm-error")).toHaveAttribute("role", "alert");
    await expect(kill.getByTestId("risk-kill-confirm-yes")).toBeEnabled();
    await expect(kill.getByTestId("risk-kill-pill")).toHaveText("On");
    expect(calls.puts).toHaveLength(1);
  });

  test("RC-6 halt: the same pattern on PUT /api/risk/halt; halted without can_reset says only an admin can lift it", async ({ page }) => {
    const calls = await riskMocks(page);
    await page.goto(RISK_CONTROLS);
    const halt = page.getByTestId("risk-halt");
    await halt.getByTestId("risk-halt-on").click();
    await halt.getByTestId("risk-halt-reason").fill("Results week");
    await halt.getByTestId("risk-halt-continue").click();
    await expect(halt.getByTestId("risk-halt-confirm")).toContainText("Halt trading? New paper positions stay blocked until an admin lifts the halt. Open positions are untouched.");
    await halt.getByTestId("risk-halt-confirm-yes").click();
    await expect.poll(() => calls.puts.length).toBe(1);
    expect(calls.puts[0]).toEqual({ path: "/api/risk/halt", body: { enabled: true, reason: "Results week" } });
    await expect(halt.getByTestId("risk-halt-pill")).toHaveText("Halted");
    await expect(halt.getByTestId("risk-halt-done")).toHaveText("Trading halted. The change is recorded below.");
    await expect(halt.getByTestId("risk-halt-admin-only")).toHaveText("Only an admin can lift the halt.");
    await expect(halt.getByTestId("risk-halt-off")).toHaveCount(0);
    // The kill switch is a separate control and is still off.
    await expect(page.getByTestId("risk-kill-pill")).toHaveText("Off");
    await expect(page.getByTestId("desk-risk-pill")).toHaveText("Trading halted");
  });

  test("RC-7 policy limits: allowed, used and remaining where usage exists; the gate off for the account is said", async ({ page }) => {
    await riskMocks(page, { status: status({ gate: { enabled: false, policy_version: "fno-gate-v1" } }) });
    await page.goto(RISK);
    const t = page.getByTestId("risk-policy-table");
    await expect(t.getByRole("columnheader")).toHaveText(["Limit", "Allowed", "Used", "Remaining"]);
    const l = POLICY.limits;
    const u = POLICY.usage;
    await expect(t.getByTestId("risk-limit-legs-limit")).toHaveText(String(l.max_legs));
    await expect(t.getByTestId("risk-limit-legs-used")).toHaveText("—");
    await expect(t.getByTestId("risk-limit-legs-left")).toHaveText("—");
    await expect(t.getByTestId("risk-limit-lots-limit")).toHaveText(String(l.max_lots_per_leg));
    await expect(t.getByTestId("risk-limit-structures-limit")).toHaveText(String(l.max_open_structures));
    await expect(t.getByTestId("risk-limit-structures-used")).toHaveText(String(u.open_structures));
    await expect(t.getByTestId("risk-limit-structures-left")).toHaveText(String(l.max_open_structures - u.open_structures)); // 5 − 2 = 3
    await expect(t.getByTestId("risk-limit-capital-limit")).toHaveText(inr(l.max_capital_at_risk_rs));                     // ₹2,00,000
    await expect(t.getByTestId("risk-limit-capital-used")).toHaveText(inr(u.capital_at_risk_rs));                          // ₹45,000
    await expect(t.getByTestId("risk-limit-capital-left")).toHaveText(inr(l.max_capital_at_risk_rs - u.capital_at_risk_rs)); // ₹1,55,000
    await expect(t.getByTestId("risk-limit-defined-limit")).toHaveText("Yes");
    await expect(page.getByTestId("risk-gate-off")).toHaveText("Gate off for your account");
    await expect(page.getByTestId("risk-gate-off-note")).toContainText("The policy gate does not check your paper writes, so these limits are not applied to them.");
    await expect(page.getByTestId("risk-trust-policy")).toHaveText("Risk controls · Rules-based · fno-gate-v1");

    // Over a limit, and no usage block at all.
    await page.unroute("**/api/risk/policy");
    await page.route("**/api/risk/policy", (route) => reply(route, { ...POLICY, usage: { open_structures: 7, capital_at_risk_rs: null } }));
    await page.reload();
    await expect(page.getByTestId("risk-limit-structures-left")).toHaveText("Over by 2"); // 7 − 5
    await expect(page.getByTestId("risk-limit-capital-used")).toHaveText("—");
    await page.unroute("**/api/risk/policy");
    await page.route("**/api/risk/policy", (route) => reply(route, { policy_version: "fno-gate-v1", limits: { ...POLICY.limits, require_defined_risk: false } }));
    await page.reload();
    await expect(page.getByTestId("risk-limit-structures-used")).toHaveText("—");
    await expect(page.getByTestId("risk-limit-structures-left")).toHaveText("—");
    await expect(page.getByTestId("risk-limit-defined-limit")).toHaveText("No");
    await expect(page.getByTestId("risk-policy-no-usage")).toHaveText("The route sent no usage figures, so used and remaining are not shown.");
  });

  test("RC-8 decisions newest first with reasons and a monospace correlation id; the audit timeline newest first, append only", async ({ page }) => {
    await riskMocks(page);
    await page.goto(RISK_LOG);
    const rows = page.getByTestId("risk-decision");
    await expect(rows).toHaveCount(DECISIONS.decisions.length);
    await expect(rows.getByTestId("risk-decision-symbol")).toHaveText(DECISION_ORDER);
    const blk = rows.nth(0);
    await expect(blk).toHaveAttribute("data-outcome", "block");
    await expect(blk.getByTestId("risk-decision-outcome")).toHaveText("Blocked");
    await expect(blk.getByTestId("risk-decision-path")).toHaveText("/api/desk/paper-trades");
    await expect(blk.getByTestId("risk-decision-reasons").getByRole("listitem")).toHaveText([
      "The structure has 5 legs; the limit is 4. (max_legs)",
      "Only defined-risk structures are allowed. (undefined_risk)",
    ]);
    const cid = blk.getByTestId("risk-decision-cid");
    await expect(cid).toHaveText("corr-3f9a1c2e-7b4d-4e0a-9c55-0a1b2c3d4e5f");
    expect(await cid.evaluate((el) => el.tagName)).toBe("CODE");
    expect(await cid.evaluate((el) => getComputedStyle(el).fontFamily)).toMatch(/mono/i);
    await expect(blk).toContainText("24 Oct, 10:40 IST"); // 05:10 UTC
    // A plain-string reason; an allow.
    await expect(rows.nth(1).getByTestId("risk-decision-outcome")).toHaveText("Allowed");
    await expect(rows.nth(1).getByTestId("risk-decision-reasons")).toHaveText("within every limit");
    await expect(rows.nth(1).getByTestId("risk-decision-path")).toHaveText("journal_trade");
    // An old row's outcome is shown as given, not turned into Allowed or Blocked; no reasons, no list.
    await expect(rows.nth(2).getByTestId("risk-decision-outcome")).toHaveText("reduced");
    await expect(rows.nth(2).getByTestId("risk-decision-reasons")).toHaveCount(0);
    await expect(page.getByTestId("risk-trust-decisions")).toHaveText("Risk controls · Rules-based · risk-controls-v1");

    const ev = page.getByTestId("risk-audit-event");
    await expect(ev).toHaveCount(2);
    await expect(ev.getByTestId("risk-audit-change")).toHaveText(["Kill switch: off → on", "Trading halt: not halted → halted"]);
    await expect(ev.getByTestId("risk-audit-actor")).toHaveText(["admin_fixture", "u_fixture"]);
    await expect(ev.getByTestId("risk-audit-reason")).toHaveText(["“Too many losing trades today”", "“Results week”"]);
    await expect(ev.nth(0)).toContainText(SET_AT_IST);
    await expect(ev.nth(0)).toContainText("risk-controls-v1");
    await expect(page.getByTestId("risk-audit-append-only")).toHaveText("Append only: no change is edited or deleted.");
  });

  test("RC-9 no decisions and no control changes are said, nothing invented", async ({ page }) => {
    await riskMocks(page, { decisions: { decisions: [], count: 0 }, audit: [] });
    await page.goto(RISK_LOG);
    await expect(page.getByTestId("risk-decisions-empty")).toContainText("No risk decisions yet");
    await expect(page.getByTestId("risk-decisions-empty")).toContainText("Each paper write the gate checks is recorded here, allowed or blocked.");
    await expect(page.getByTestId("risk-audit-empty")).toContainText("No control changes yet");
    await expect(page.getByTestId("risk-decision")).toHaveCount(0);
    await expect(page.getByTestId("risk-audit-event")).toHaveCount(0);
  });

  test("RC-10 a status without a boolean kill_switch is unknown: never Off, no controls, no header pill", async ({ page }) => {
    await riskMocks(page, { status: { kill_switch: "yes", halted: true } as Status });
    await page.goto(RISK_CONTROLS);
    await expect(page.getByTestId("risk-status-unknown").getByRole("alert")).toContainText("The risk status was not in the expected form — the kill switch and halt state is unknown, not off");
    await expect(page.getByTestId("risk-kill")).toHaveCount(0);
    await expect(page.getByTestId("risk-halt")).toHaveCount(0);
    await expect(page.getByTestId("risk-status")).not.toContainText("Off");
    await expect(page.getByTestId("desk-risk-pill")).toHaveCount(0);
    // The rest of the page still reads.
    await expect(page.getByTestId("risk-policy-table")).toBeVisible();

    // mockApi's catch-all {} (what every other desk spec answers): also unknown, also no pill.
    await page.unroute("**/api/risk/status");
    await page.goto(`${DESK}?tab=overview`);
    await expect(page.getByTestId("desk-market-status")).toBeVisible();
    await expect(page.getByTestId("desk-risk-pill")).toHaveCount(0);
  });

  for (const code of [503, 500]) {
    test(`RC-11 status ${code}: an error with Retry, no controls and no claim that anything is off; the other cards still load`, async ({ page }) => {
      const calls = await riskMocks(page, { statusReply: { status: code, body: { detail: "upstream_unavailable" } } });
      await page.goto(RISK_CONTROLS);
      const err = page.getByTestId("risk-status-error");
      await expect(err.getByRole("alert")).toContainText("Your risk controls didn’t load — the server reported an error", { timeout: 15_000 });
      await expect(err).toContainText("Their state is unknown here. This screen does not assume the kill switch or the halt is off.");
      await expect(page.getByTestId("risk-kill")).toHaveCount(0);
      await expect(page.getByTestId("desk-risk-pill")).toHaveCount(0);
      await expect(page.getByTestId("risk-scope-note")).toHaveCount(0);
      await page.goto(RISK_LIMITS); // the other cards are in the Risk Desk's other views
      await expect(page.getByTestId("risk-policy-table")).toBeVisible();
      await page.goto(RISK_LOG);
      await expect(page.getByTestId("risk-decision")).toHaveCount(DECISIONS.decisions.length);
      await page.goto(RISK_CONTROLS);
      await expect(err.getByRole("alert")).toContainText("Your risk controls didn’t load — the server reported an error", { timeout: 15_000 });
      const before = calls.statusReads;
      await err.getByRole("button", { name: /Retry/ }).click();
      await expect.poll(() => calls.statusReads).toBeGreaterThan(before);
    });
  }

  test("RC-12 policy, decisions and audit failures each show their own error; the status card still works", async ({ page }) => {
    const fail = { status: 500, body: { detail: "fixture failure" } };
    await riskMocks(page, { policyReply: fail, decisionsReply: fail, auditReply: fail });
    await page.goto(RISK_LIMITS); // each card is in its Risk Desk view
    await expect(page.getByTestId("risk-policy-error").getByRole("alert")).toContainText("The policy limits didn’t load", { timeout: 15_000 });
    await expect(page.getByTestId("risk-policy-table")).toHaveCount(0);
    await page.goto(RISK_LOG);
    await expect(page.getByTestId("risk-decisions-error").getByRole("alert")).toContainText("Risk decisions didn’t load", { timeout: 15_000 });
    await expect(page.getByTestId("risk-audit-error").getByRole("alert")).toContainText("Control changes didn’t load", { timeout: 15_000 });
    await page.goto(RISK_CONTROLS);
    await expect(page.getByTestId("risk-kill-pill")).toHaveText("Off");
    await expect(page.getByTestId("risk-kill-on")).toBeEnabled();
  });

  test("RC-13 a server 422 invalid_input shows the server's words with the code", async ({ page }) => {
    await riskMocks(page, { putReply: { status: 422, body: { detail: { code: "invalid_input", message: "a reason is required" } } } });
    await page.goto(RISK_CONTROLS);
    const kill = page.getByTestId("risk-kill");
    await kill.getByTestId("risk-kill-on").click();
    await kill.getByTestId("risk-kill-reason").fill("x");
    await kill.getByTestId("risk-kill-continue").click();
    await kill.getByTestId("risk-kill-confirm-yes").click();
    await expect(kill.getByTestId("risk-kill-confirm-error")).toHaveText("a reason is required (invalid_input)");
    await expect(kill.getByTestId("risk-kill-pill")).toHaveText("Off");
  });

  test("RC-14 keyboard: the whole trip flow works from the keyboard; the reason field and buttons are labelled", async ({ page }) => {
    const calls = await riskMocks(page);
    await page.goto(RISK_CONTROLS);
    const on = page.getByRole("button", { name: "Turn kill switch on" });
    await on.focus();
    await expect(on).toBeFocused();
    await page.keyboard.press("Enter");
    const reason = page.getByLabel("Reason (required; recorded with the change)");
    await expect(reason).toBeFocused();
    await expect(reason).toHaveAttribute("maxlength", "500");
    await page.keyboard.type("Keyboard trip");
    await expect(page.getByTestId("risk-kill-form")).toContainText("13 / 500");
    await page.keyboard.press("Tab");
    await expect(page.getByRole("button", { name: "Continue" })).toBeFocused();
    await page.keyboard.press("Enter");
    const group = page.getByRole("group", { name: "Confirm: Turn kill switch on" });
    await expect(group).toBeVisible();
    await expect(group.getByRole("button", { name: "Cancel" })).toBeFocused();
    await page.keyboard.press("Shift+Tab");
    await expect(group.getByRole("button", { name: "Turn kill switch on" })).toBeFocused();
    await page.keyboard.press("Enter");
    await expect.poll(() => calls.puts.length).toBe(1);
    expect(calls.puts[0].body).toEqual({ enabled: true, reason: "Keyboard trip" });
    await expect(page.getByRole("status").filter({ hasText: "Kill switch turned on." })).toBeVisible();
    // State is in words as well as colour.
    await expect(page.getByTestId("risk-kill-words")).toHaveText("Kill switch: on. New paper positions are blocked.");
  });

  test("RC-15 phone 390px: the header pill, the cards, a 500-character reason and a long correlation id wrap with no sideways scroll", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    const long = "Long reason ".repeat(42).slice(0, 500);
    expect(long.length).toBe(500);
    const longCid = `corr-${"9f".repeat(60)}`;
    await riskMocks(page, {
      status: status({ ...KILL_ON, reason: long }),
      decisions: { decisions: [{ ...DECISIONS.decisions[2], correlation_id: longCid }], count: 1 },
      audit: [{ ...AUDIT_EVENTS[1], reason: long }],
    });
    await page.goto(`${DESK}?tab=overview`);
    const pill = page.getByTestId("desk-mobile-header").getByTestId("desk-risk-pill");
    await expect(pill).toHaveText("Kill switch on");
    await noSideScroll(page);
    await pill.click();
    // Desk redesign (2026-10-27): the pill opens Risk Desk › Controls & profile (was More · Risk controls); the bottom bar's
    // 04 Risk and the view switcher mark it. The cards are split over the three Risk Desk views.
    await expect(page).toHaveURL(/[?&]tab=risk&view=controls(&|$)/);
    await expect(page.getByTestId("desk-bottom-risk")).toHaveAttribute("aria-current", "page");
    await expect(page.getByTestId("desk-view-controls")).toHaveAttribute("aria-pressed", "true");
    await expect(page.getByTestId("risk-status")).toBeVisible();
    await expect(page.getByTestId("risk-last-reason")).toHaveText(`“${long}”`);
    await noSideScroll(page);
    await page.goto(RISK_LOG);
    for (const id of ["risk-decisions", "risk-audit"]) await expect(page.getByTestId(id)).toBeVisible();
    await expect(page.getByTestId("risk-decision-cid")).toHaveText(longCid);
    await expect(page.getByTestId("risk-audit-reason")).toHaveText(`“${long}”`);
    await noSideScroll(page);
    await page.goto(RISK_LIMITS);
    await expect(page.getByTestId("risk-policy")).toBeVisible();
    // The policy table fits the phone: all four columns, no scroll inside its box either.
    const table = page.getByTestId("risk-policy-table");
    await table.scrollIntoViewIfNeeded();
    const box = await table.evaluate((el) => { const p = el.parentElement as HTMLElement; return { scroll: p.scrollWidth, client: p.clientWidth }; });
    expect(box.scroll - box.client).toBeLessThanOrEqual(1);
    await expect(page.getByTestId("risk-limit-capital-left")).toBeInViewport();
    await noSideScroll(page);
  });
});
