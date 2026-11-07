/**
 * Desk web app — 12 Policies & permissions (AD-UI-70..79). Test cases: docs/autodesk/ui_testcases/policies.md.
 * API answered by route mocks (autodesk-mock.ts + autodesk-fixtures-policies.ts — MOCK, shapes of the real API).
 * Every POST body is checked against e2e/fixtures/autodesk/requests/policies.json (posted to the real API by the
 * backend contract test). The page clock is fixed at NOW (11:42:30 IST, 5 Nov 2026).
 */
import { expect, test, type Page } from "@playwright/test";
import { ME, NOW, collectConsoleErrors, deskStatus, expectContract, mockDesk, reply, type DeskMock, type MockState, type Req, type RouteValue } from "./autodesk-mock";
import { PREMARKET_OUTCOME } from "./autodesk-fixtures-overview";
import { ACC, POL, POLICY_ROUTES, addVersion, policyState, twoVersions } from "./autodesk-fixtures-policies";

async function setup(page: Page, opts: { policy?: ReturnType<typeof policyState>; routes?: Record<string, RouteValue> } = {}) {
  await page.clock.setFixedTime(new Date(NOW));
  return mockDesk(page, {
    state: { policy: opts.policy ?? policyState() },
    routes: {
      "GET /desk/status": (_r: Req, s: MockState) => deskStatus(s, { last_premarket: { session_date: "2026-11-05", outcome: PREMARKET_OUTCOME } }),
      ...POLICY_ROUTES,
      ...(opts.routes ?? {}),
    },
  });
}

const screen = (page: Page) => page.getByTestId("screen-policies");
const posts = (d: DeskMock, prefix: string) => d.posts.filter((p) => p.path.startsWith(prefix));

test("AD-UI-70 header: eyebrow, one pill per policy, headline, computed sub line", async ({ page }) => {
  const errors = collectConsoleErrors(page);
  const desk = await setup(page);
  await page.goto("/autodesk/policies");
  await expect(screen(page).locator(".nv-eyebrow").first()).toHaveText("12 · Policies & permissions");
  await expect(page.getByTestId("policy-pill")).toHaveText(["Desk default · v1 active"]);
  await expect(page.getByTestId("headline")).toHaveText("The most restrictive rule always wins. Autonomous live stays locked until the owner decides.");
  await expect(page.getByTestId("headline").locator("em")).toHaveText("Autonomous live");
  await expect(page.getByTestId("subline")).toHaveText(
    "One policy (Desk default v1) governs 1 paper account. Every change creates a new version and an audit event; you may tighten any limit, and a limit looser than the default needs an admin.");
  await expect(page.getByTestId("version-row")).toHaveCount(1);
  expect(desk.unmatched).toEqual([]);
  expect(errors).toEqual([]);
});

test("AD-UI-71 operating mode by account: four options, current highlighted, live locked with no action", async ({ page }) => {
  const desk = await setup(page);
  await page.goto("/autodesk/policies");
  const card = page.getByTestId("mode-card");
  await expect(card).toHaveCount(1);
  await expect(card).toContainText("Paper · Desk A");
  await expect(card.getByTestId("mode-card-policy")).toHaveText("Desk default · v1");
  await expect(card.locator("button")).toHaveText(["Research", "Assisted", "Autonomous paper", "Autonomous live · locked"]);
  await expect(page.getByTestId("mode-opt-AUTONOMOUS_PAPER")).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByTestId("mode-opt-AUTONOMOUS_LIVE")).toBeDisabled();
  await page.getByTestId("mode-opt-AUTONOMOUS_LIVE").click({ force: true });
  await page.getByTestId("mode-opt-AUTONOMOUS_PAPER").click();
  await expect(page.getByTestId("mode-dialog")).toHaveCount(0);
  await expect(card.getByTestId("mode-note")).toHaveText(
    "Autonomous paper: the Middle Office approves plans inside the policy's autonomy rules and sends the rest to you. Paper only.");
  const gate = page.getByTestId("live-gate");
  await expect(gate).toContainText("AUTONOMOUS LIVE · LOCKED");
  for (const g of ["Broker permission", "Simulator certification", "Compliance approval", "Kill-switch drill"]) await expect(gate).toContainText(g);
  await expect(gate).toContainText("live trading awaits the owner's decision");
  await expect(gate).not.toContainText(/18 of 20|passed|✓/);
  expect(desk.posts).toEqual([]);
});

test("AD-UI-72 switch mode: confirm with a reason sends the contract body; the card and sidebar update", async ({ page }) => {
  const desk = await setup(page);
  await page.goto("/autodesk/policies");
  await page.getByTestId("mode-opt-ASSISTED").click();
  await expect(page.getByTestId("mode-dialog")).toContainText("Assisted: every plan that passes the risk check comes to you for approval.");
  await expect(page.getByTestId("mode-reason")).toHaveValue("Changed from Policies & permissions");
  await page.getByTestId("mode-confirm").click();
  await expect(page.getByTestId("mode-dialog")).toHaveCount(0);
  expectContract(posts(desk, "/accounts/")[0], "policies", "set_mode_assisted", { account_id: ACC });
  await expect(page.getByTestId("mode-opt-ASSISTED")).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByTestId("mode-note")).toHaveText("Mode changed to assisted at 11:42 IST and recorded in the audit log.");
  await expect(page.getByTestId("account-row")).toContainText("Assisted");

  await page.getByTestId("mode-opt-RESEARCH").click();
  await page.getByTestId("mode-confirm").click();
  await expect(page.getByTestId("mode-opt-RESEARCH")).toHaveAttribute("aria-pressed", "true");
  expectContract(posts(desk, "/accounts/")[1], "policies", "set_mode_research", { account_id: ACC });

  await page.getByTestId("mode-opt-AUTONOMOUS_PAPER").click();
  await page.getByTestId("mode-confirm").click();
  await expect(page.getByTestId("mode-opt-AUTONOMOUS_PAPER")).toHaveAttribute("aria-pressed", "true");
  expectContract(posts(desk, "/accounts/")[2], "policies", "set_mode_autonomous_paper", { account_id: ACC });
});

test("AD-UI-72 a refused mode change shows the API message and keeps the old mode", async ({ page }) => {
  await setup(page, { routes: { "POST /accounts/:account_id/mode": reply(409, { error: "CONFLICT", message: "a simulation account's mode is fixed by its simulation config" }) } });
  await page.goto("/autodesk/policies");
  await page.getByTestId("mode-opt-ASSISTED").click();
  await page.getByTestId("mode-confirm").click();
  await expect(page.getByTestId("mode-error")).toHaveText("a simulation account's mode is fixed by its simulation config (409)");
  await expect(page.getByTestId("mode-dialog")).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByTestId("mode-opt-AUTONOMOUS_PAPER")).toHaveAttribute("aria-pressed", "true");
});

test("AD-UI-73 effective policy table: every limit, tenant level binding, pre-market narrowing note", async ({ page }) => {
  await setup(page);
  await page.goto("/autodesk/policies");
  await expect(page.getByTestId("effective-eyebrow")).toHaveText("Effective policy · Paper · Desk A · Desk default v1");
  await expect(page.getByTestId("eff-head-TENANT")).toHaveText("● Tenant · v1");
  for (const s of ["ACCOUNT", "STRATEGY", "SEGMENT"]) await expect(page.getByTestId(`eff-head-${s}`)).not.toContainText("●");
  await expect(page.locator('[data-testid^="eff-row-"]')).toHaveCount(21);
  const val = (k: string) => page.getByTestId(`eff-row-${k}`).getByTestId("eff-value");
  await expect(val("per_trade_risk_pct")).toHaveText("0.5%");
  await expect(val("open_risk_pct")).toHaveText("3%");
  await expect(val("position_pct")).toHaveText("10%");
  await expect(val("max_margin_utilization_pct")).toHaveText("25%");
  await expect(val("min_reward_risk")).toHaveText("1.5 : 1");
  await expect(val("credit_min_width_fraction")).toHaveText("0.3333 × width");
  await expect(val("max_proposals_per_session")).toHaveText("5");
  await expect(val("min_adv_rs")).toHaveText("₹1.00 Cr");
  await expect(val("require_traded_legs")).toHaveText("Yes");
  await expect(val("allowed_segments")).toHaveText("Cash, Futures, Options");
  await expect(page.getByTestId("eff-row-per_trade_risk_pct")).toContainText("Max risk per trade0.5%———0.5%");
  await expect(page.getByTestId("effective-note")).toContainText("Only the tenant level is set: Desk default v1 is the policy the risk engine applies to this account.");
  await expect(page.getByTestId("effective-note")).toContainText("narrows the allowed segments for its session to cash, futures, options");
});

test("AD-UI-74 edit limits: tighten one limit → contract body, new version active, change listed", async ({ page }) => {
  const desk = await setup(page);
  await page.goto("/autodesk/policies");
  await page.getByTestId("edit-limits").click();
  await expect(page.getByTestId("limits-dialog")).toContainText("Saving creates version 2 of this policy for the 1 account that uses it.");
  await expect(page.getByTestId("limits-save")).toBeDisabled();
  await page.getByTestId("limit-input-per_trade_risk_pct").fill("0.4");
  await expect(page.getByTestId("limits-count")).toHaveText("1 change");
  await page.getByTestId("limits-save").click();
  await expect(page.getByTestId("limits-dialog")).toHaveCount(0);
  expectContract(posts(desk, "/policies/")[0], "policies", "tighten_limit", { policy_id: POL });
  await expect(page.getByTestId("policy-pill")).toHaveText(["Desk default · v2 active"]);
  await expect(page.getByTestId("eff-row-per_trade_risk_pct").getByTestId("eff-value")).toHaveText("0.4%");
  const rows = page.getByTestId("version-row");
  await expect(rows).toHaveCount(2);
  await expect(rows.nth(0)).toContainText("Desk default · v2");
  await expect(rows.nth(0).getByTestId("version-state")).toHaveText("ACTIVE");
  await expect(rows.nth(0).getByTestId("version-text")).toHaveText("Max risk per trade 0.5% → 0.4% · “Edited from Policies & permissions” · by user:user_7f3a9c");
  await expect(rows.nth(1).getByTestId("version-state")).toHaveText("RETIRED");
  await expect(rows.nth(1)).toContainText("5 Nov, 10:50 – 5 Nov, 11:42");
});

test("AD-UI-74b edit limits: the refreshed list arrives before the save has finished; the dialog closes and stays closed", async ({ page }) => {
  // The version-keyed policy query is empty for a moment once the list says v2. Holding /desk/status back keeps the save's
  // refresh unfinished through that moment, which is the order that used to unmount the dialog and lose its close callback.
  const desk = await setup(page);
  await page.route("**/autodesk/api/v1/desk/status", async (route) => {
    await new Promise((r) => setTimeout(r, 700));
    await route.fallback();
  });
  await page.goto("/autodesk/policies");
  await page.getByTestId("edit-limits").click();
  await page.getByTestId("limit-input-per_trade_risk_pct").fill("0.4");
  await page.getByTestId("limits-save").click();
  await expect(page.getByTestId("policy-pill")).toHaveText(["Desk default · v2 active"]);
  await expect(page.getByTestId("limits-dialog")).toHaveCount(0);
  await page.waitForTimeout(1200);
  await expect(page.getByTestId("limits-dialog")).toHaveCount(0);
  expect(posts(desk, "/policies/")).toHaveLength(1);
});

test("AD-UI-75 loosening as a non-admin and an invalid value: the API's messages are shown, nothing changes", async ({ page }) => {
  const desk = await setup(page, {
    routes: {
      "POST /policies/:policy_id/versions": (r: Req, s: MockState) => {
        const v = (r.body as { changes: Record<string, string> }).changes.per_trade_risk_pct;
        if (v === "1") return reply(403, { detail: "looser than the default needs an admin: per_trade_risk_pct" });
        if (v === "150") return reply(422, { detail: "invalid policy: 1 validation error for PolicyBody\n  Value error, per_trade_risk_pct must be in (0, 100]" });
        return addVersion(r, s);
      },
    },
  });
  await page.goto("/autodesk/policies");
  await page.getByTestId("edit-limits").click();
  await page.getByTestId("limit-input-per_trade_risk_pct").fill("abc");
  await expect(page.getByTestId("limits-dialog")).toContainText("not a number");
  await expect(page.getByTestId("limits-save")).toBeDisabled();
  await page.getByTestId("limit-input-per_trade_risk_pct").fill("1");
  await page.getByTestId("limits-save").click();
  await expect(page.getByTestId("limits-error")).toHaveText("looser than the default needs an admin: per_trade_risk_pct (403)");
  expectContract(posts(desk, "/policies/")[0], "policies", "loosen_limit_needs_admin", { policy_id: POL });
  await page.getByTestId("limit-input-per_trade_risk_pct").fill("150");
  await page.getByTestId("limits-save").click();
  await expect(page.getByTestId("limits-error")).toContainText("per_trade_risk_pct must be in (0, 100] (422)");
  expectContract(posts(desk, "/policies/")[1], "policies", "invalid_limit", { policy_id: POL });
  await expect(page.getByTestId("limits-dialog")).toBeVisible();
  await page.getByTestId("limit-input-per_trade_risk_pct").fill("0.5");
  await expect(page.getByTestId("limits-save")).toBeDisabled();
  await page.keyboard.press("Escape");
  await expect(page.getByTestId("policy-pill")).toHaveText(["Desk default · v1 active"]);
  await expect(page.getByTestId("version-row")).toHaveCount(1);
});

test("AD-UI-76 automatic approval off: the whole autonomy object is sent; the matrix and approvers follow", async ({ page }) => {
  const desk = await setup(page);
  await page.goto("/autodesk/policies");
  const inRules = page.getByTestId("matrix-row").filter({ hasText: "Approve a plan inside the autonomy rules" });
  await expect(inRules).toContainText("APPROVALAUTOLOCKED");
  await page.getByTestId("edit-limits").click();
  await page.getByTestId("autonomy-auto-approve").uncheck();
  await page.getByTestId("limits-save").click();
  await expect(page.getByTestId("limits-dialog")).toHaveCount(0);
  expectContract(posts(desk, "/policies/")[0], "policies", "autonomy_auto_approve_off", { policy_id: POL });
  await expect(inRules).toContainText("APPROVALAPPROVALLOCKED");
  await expect(page.getByTestId("who-approves")).toContainText("Every plan on an Autonomous paper account");
  await expect(page.getByTestId("version-row").first()).toContainText("Automatic approval on → off");
});

test("AD-UI-77 matrix, approvers and roles from the policy, the Middle Office rules and the signed-in role", async ({ page }) => {
  await setup(page);
  await page.goto("/autodesk/policies");
  const rows = page.getByTestId("matrix-row");
  await expect(rows).toHaveCount(8);
  for (let i = 0; i < 8; i++) await expect(rows.nth(i)).toContainText(/LOCKED$/);
  await expect(rows.filter({ hasText: "Approve a plan whose risk check failed" })).toContainText("NEVERNEVERLOCKED");
  await expect(page.getByTestId("matrix-phase-note")).toContainText("Opening a position is a paper order placed after approval");
  await expect(page.getByTestId("matrix-phase-note")).toContainText("The desk trails and closes positions by each plan's rules");
  const who = page.getByTestId("who-approves");
  await expect(who).toContainText("Plan risk above 0.5% of equity");
  await expect(who).toContainText("Signal score below 70");
  await expect(who).toContainText("approved automatically only: Long equity, Bull call spread, Bear put spread, Bull put spread, Bear call spread, Iron condor");
  await expect(who).toContainText("Not available · owner decision pending");
  await expect(page.getByTestId("role-owner")).toHaveAttribute("data-you", "true");
  await expect(page.getByTestId("role-owner")).toContainText("Account owner · you");
  await expect(page.getByTestId("role-owner")).toContainText("Tighten");
  await expect(page.getByTestId("role-admin")).not.toHaveAttribute("data-you", "true");
  await expect(screen(page)).not.toContainText(/Risk officer|Read-only auditor|Platform administrator · you/);

  await page.unrouteAll({ behavior: "ignoreErrors" });
  await setup(page, { routes: { "GET /api/auth/me": { ...ME, role: "admin" } } });
  await page.reload();
  await expect(page.getByTestId("role-admin")).toHaveAttribute("data-you", "true");
  await expect(page.getByTestId("role-admin")).toContainText("Administrator · you");
});

test("AD-UI-78 emergency controls: activate and lift Stop new entries inline; the rest are not available", async ({ page }) => {
  const desk = await setup(page);
  await page.goto("/autodesk/policies");
  const c = page.getByTestId("control-entries");
  await expect(c.getByTestId("control-entries-state")).toHaveText("OFF");
  await c.getByTestId("control-ask").click();
  await expect(c.getByTestId("control-reason")).toHaveValue("Stopped from Policies & permissions");
  await expect(c.getByTestId("control-confirm")).toHaveText("Confirm activate");
  await c.getByTestId("control-confirm").click();
  await expect(c.getByTestId("control-entries-state")).toHaveText("ACTIVE");
  expectContract(posts(desk, "/desk/controls/")[0], "policies", "stop_entries");
  await expect(c.getByTestId("control-entries-since")).toContainText("by user_7f3a9c · Stopped from Policies & permissions");
  await expect(page.getByTestId("halt-banner")).toBeVisible();
  await expect(c.getByTestId("control-ask")).toHaveText("Lift this control");
  await c.getByTestId("control-ask").click();
  await expect(c.getByTestId("control-confirm")).toHaveText("Confirm lift");
  await c.getByTestId("control-confirm").click();
  await expect(c.getByTestId("control-entries-state")).toHaveText("OFF");
  expectContract(posts(desk, "/desk/controls/")[1], "policies", "lift_entries");
  await expect(page.getByTestId("halt-banner")).toHaveCount(0);
  for (const id of ["gen", "mods", "cancel", "strat", "acct", "exits", "broker"]) {
    await expect(page.getByTestId(`control-${id}`)).toContainText("NOT AVAILABLE");
    await expect(page.getByTestId(`control-${id}`).locator("button")).toHaveCount(0);
  }
  await expect(page.getByTestId("emergency")).not.toContainText(/DLF|Zerodha|21 Oct/);
});

test("AD-UI-78 a refused control POST shows the API message inline", async ({ page }) => {
  await setup(page, { routes: { "POST /desk/controls/:control": reply(403, { error: "FORBIDDEN", message: "only the account owner may stop entries" }) } });
  await page.goto("/autodesk/policies");
  const c = page.getByTestId("control-entries");
  await c.getByTestId("control-ask").click();
  await c.getByTestId("control-confirm").click();
  await expect(c.getByTestId("control-error")).toHaveText("only the account owner may stop entries (403)");
  await expect(c.getByTestId("control-entries-state")).toHaveText("OFF");
});

test("AD-UI-79 version history from the API, newest first, with the stored reason and computed changes", async ({ page }) => {
  const desk = await setup(page, { policy: twoVersions() });
  await page.goto("/autodesk/policies");
  const rows = page.getByTestId("version-row");
  await expect(rows).toHaveCount(2);
  await expect(rows.nth(0)).toContainText("Desk default · v2");
  await expect(rows.nth(0)).toContainText("Since 5 Nov, 11:10");
  await expect(rows.nth(0).getByTestId("version-text")).toHaveText(
    "Max risk per trade 0.5% → 0.4%; Max lots per leg 10 → 8 · “results week: smaller size” · by user:user_7f3a9c");
  await expect(rows.nth(1)).toContainText("Desk default · v1");
  await expect(rows.nth(1).getByTestId("version-state")).toHaveText("RETIRED");
  await expect(rows.nth(1).getByTestId("version-text")).toHaveText("“default from the risk-profile defaults” · by user:user_7f3a9c");
  expect(desk.requests.map((r) => r.path)).toContain(`/policies/${POL}?version=1`);
  expect(desk.unmatched).toEqual([]);
});

test("AD-UI-79 policies failing to load: ErrorBox with the API's message", async ({ page }) => {
  await setup(page, { routes: { "GET /policies": reply(500, { error: "INTERNAL", message: "policy store unavailable" }) } });
  await page.goto("/autodesk/policies");
  await expect(screen(page).getByTestId("error-box").first()).toContainText("policy store unavailable (500)", { timeout: 15000 });
  await expect(screen(page).getByTestId("error-box").first()).toContainText("Could not load the policies");
});

test("AD-UI-79 phone 390×844: one column, wide tables scroll inside their box, no page overflow", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const errors = collectConsoleErrors(page);
  await setup(page);
  await page.goto("/autodesk/policies");
  await expect(page.getByTestId("desk-mobile")).toBeVisible();
  await expect(page.getByTestId("effective-table")).toBeVisible();
  expect(await screen(page).locator("h1").evaluate((e) => getComputedStyle(e).fontSize)).toBe("30px");
  const scroll = await page.getByTestId("effective-scroll").evaluate((e) => e.scrollWidth - e.clientWidth);
  expect(scroll).toBeGreaterThan(0);
  const [m, w] = await Promise.all([page.getByTestId("agents-matrix").boundingBox(), page.getByTestId("who-approves").boundingBox()]);
  expect(Math.round(w!.x)).toBe(Math.round(m!.x));                                       // stacked, one column
  await page.getByTestId("version-row").first().scrollIntoViewIfNeeded();
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow).toBeLessThanOrEqual(0);
  expect(errors).toEqual([]);
});
