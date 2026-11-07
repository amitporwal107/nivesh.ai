/**
 * Desk web app — Approval queue (AD-UI-50..59). Test cases: docs/autodesk/ui_testcases/approvals.md.
 * API answered by route mocks (autodesk-mock.ts + autodesk-fixtures-approvals.ts — MOCK, shapes of the real API).
 * The page clock is fixed at 11:42:30 IST (NOW) so countdowns are exact.
 */
import { expect, test, type Page } from "@playwright/test";
import { ACCOUNT_A, NOW, TENANT, collectConsoleErrors, expectContract, mockDesk, reply, type Req, type RouteValue } from "./autodesk-mock";
import { ACCOUNT_B, APR_ADANI, APR_G, APR_P, HASH_G, HASH_P, PLAN_P_BODY, RISK_P, approvalsRoutes, world, type ApprovalsWorld } from "./autodesk-fixtures-approvals";

const HALT = { tenant_id: TENANT, control: "STOP_NEW_ENTRIES", active: true, reason: "Stopped from the desk header", changed_by: TENANT, changed_at: NOW };

async function openQueue(page: Page, o: { path?: string; over?: Record<string, RouteValue>; edit?: (w: ApprovalsWorld) => void; halted?: boolean } = {}) {
  await page.clock.setFixedTime(new Date(NOW));
  const w = world();
  o.edit?.(w);
  const desk = await mockDesk(page, { routes: approvalsRoutes(w, o.over), state: { accounts: [{ ...ACCOUNT_A }, { ...ACCOUNT_B }], controls: o.halted ? [HALT] : [] } });
  await page.goto(o.path ?? "/autodesk/approvals");
  await expect(page.getByTestId("screen-approvals")).toBeVisible();
  return { desk, w };
}

const decisionPost = (desk: { posts: { method: string; path: string; body: unknown }[] }) => desk.posts.filter((p) => p.path.endsWith("/decision"));

test("AD-UI-50 queue: header, desk requests sorted by expiry, decided rows, first request opened", async ({ page }) => {
  const errors = collectConsoleErrors(page);
  const { desk } = await openQueue(page);
  const s = page.getByTestId("screen-approvals");
  await expect(s.getByText("05 · Approval queue")).toBeVisible();
  await expect(page.getByTestId("pending-pill")).toHaveText("2 pending");
  await expect(s.getByText("Approvals bind to one plan version")).toBeVisible();
  await expect(page.getByTestId("approvals-headline")).toHaveText("Two decisions need you. The first lapses at 15:30.");
  const items = page.getByTestId("approval-item");
  await expect(items).toHaveCount(2);
  await expect(items.nth(0)).toContainText(APR_P.approval_id as string);
  await expect(items.nth(0).getByTestId("item-short")).toHaveText("PETRONET 310/335 CE · Bull call spread · 4 lots");
  await expect(items.nth(0).getByTestId("item-risk")).toHaveText("₹48,426");
  await expect(items.nth(0)).toContainText("Assisted paper");
  await expect(items.nth(0)).toContainText("Paper · Desk B");
  await expect(items.nth(0).getByTestId("item-countdown")).toHaveText("3h 47m");
  await expect(items.nth(1).getByTestId("item-short")).toHaveText("GRASIM 2700/2800 CE · Bull call spread · 1 lot");
  await expect(items.nth(1).getByTestId("item-risk")).toHaveText("₹41,683");
  await expect(s).not.toContainText("APR-9c8b7a6f5e4d3c2b1a09");          // the simulation's request is not the desk's
  await expect(page.getByTestId("history-label")).toHaveText("Decided earlier today");
  const hist = page.getByTestId("history-row");
  await expect(hist).toHaveCount(2);
  await expect(hist.nth(0)).toContainText("TATAPOWER · Long futures v1");
  await expect(hist.nth(0)).toContainText("REJECTED");
  await expect(hist.nth(0)).toContainText("Middle Office · risk checks failed: per_trade_risk");
  await expect(hist.nth(1)).toContainText("ADANIPORTS · Bull call spread v1");
  await expect(hist.nth(1)).toContainText("APPROVED");
  await expect(hist.nth(1)).toContainText("Middle Office · within the autonomy rules of the policy; risk 0.36% of equity");
  await expect(page.getByTestId("detail-id")).toContainText(`${APR_P.approval_id} · ${RISK_P.trade_id} v1`);
  await expect(page.getByTestId("badge-approvals")).toHaveText("2");
  expect(desk.unmatched).toEqual([]);
  expect(errors).toEqual([]);
});

test("AD-UI-51 detail: header, trade, capital, risk report, impact, chain, checks, audit — all from the API", async ({ page }) => {
  const errors = collectConsoleErrors(page);
  await openQueue(page);
  const d = page.getByTestId("approval-detail");
  await expect(page.getByTestId("detail-title")).toHaveText("PETRONET bull call spread · 310 / 335 CE · 24 Nov expiry");
  await expect(page.getByTestId("detail-mode")).toHaveText("Assisted paper");
  await expect(page.getByTestId("detail-account")).toHaveText("Paper · Desk B");
  await expect(page.getByTestId("detail-why")).toHaveText("assisted mode: a person approves every plan");
  await expect(page.getByTestId("detail-countdown")).toHaveText("3h 47m");
  await expect(d).toContainText("LEFT · EXPIRES 15:30:00 IST");
  await expect(page.getByTestId("detail-thesis")).toHaveText(PLAN_P_BODY.thesis);
  await expect(page.getByTestId("detail-rationale")).toContainText("the spread caps the loss at the premium paid");

  const tr = page.getByTestId("trade-row");
  await expect(tr.nth(0)).toContainText("Long");
  await expect(tr.nth(0)).toContainText("4 lots · 1900 · PETRONET 24 NOV 310 CE");
  await expect(tr.nth(0)).toContainText("REF 9.80 · fno_bhavcopy.close 2026-11-04");
  await expect(tr.nth(1)).toContainText("Short");
  await expect(tr.nth(1)).toContainText("4 lots · 1900 · PETRONET 24 NOV 335 CE");
  await expect(tr.nth(2)).toContainText("Capital ₹48,260.00 · max loss ₹48,425.90");
  await expect(tr.nth(3)).toContainText("Until 15:30 IST · 5 Nov");
  await expect(tr.nth(4)).toContainText("close the position when the underlying closes beyond the invalidation level");
  await expect(tr.nth(4)).toContainText("INVALIDATION 298.40");

  const cap = page.getByTestId("sec-capital");
  await expect(page.getByTestId("reservation-phase")).toContainText("Phase 2");
  await expect(cap).toContainText("₹48,260.00 · premium paid");
  await expect(cap).toContainText("fixed risk per trade (policy per_trade_risk_pct of equity) · 4 lots per leg proposed, 4 allowed · budget ₹50,000.00");

  await expect(page.getByTestId("risk-id")).toHaveText(`${RISK_P.assessment_id} · PASS · RISK & OPERATIONS · 09:01:10`);
  const tiles = page.getByTestId("risk-tile");
  await expect(tiles.nth(0)).toContainText("Max loss");
  await expect(tiles.nth(0)).toContainText("₹48,426");
  await expect(tiles.nth(0)).toContainText("0.48% of ₹1.00 Cr");
  await expect(tiles.nth(1)).toContainText("₹1,41,574");
  await expect(tiles.nth(1)).toContainText("R:R 1 : 2.92");
  await expect(tiles.nth(2)).toContainText("316.37");
  await expect(tiles.nth(3)).toContainText("₹48,260");
  await expect(page.getByTestId("stress-phase-note")).toContainText("Phase 2");

  const imp = page.getByTestId("impact-row");
  await expect(imp).toHaveCount(4);
  await expect(imp.nth(0)).toContainText("Open risk (Desk B)");
  await expect(imp.nth(0)).toContainText("₹36,244");
  await expect(imp.nth(0)).toContainText("₹84,670");
  await expect(imp.nth(0)).toContainText("₹3.00 L");
  await expect(imp.nth(1)).toContainText("F&O capital");
  await expect(imp.nth(1)).toContainText("₹84,398");
  await expect(imp.nth(1)).toContainText("₹60.00 L");
  await expect(imp.nth(2)).toContainText("Sector · Oil Gas & Consumable Fuels");
  await expect(imp.nth(2)).toContainText("₹25.00 L");
  await expect(imp.nth(3)).toContainText("Capital in this plan");
  await expect(imp.nth(3)).toContainText("₹10.00 L");
  await expect(page.getByTestId("book-now")).toHaveText("Book now: 1 approved plan · committed max loss ₹36,244.39.");
  await expect(page.getByTestId("impact-note")).toContainText("Phase 1: commitments are approved, unexpired plans; there are no fills or positions yet");

  const chain = page.getByTestId("chain-row");
  await expect(chain).toHaveCount(4);
  await expect(chain.nth(0)).toContainText("Risk & Operations");
  await expect(chain.nth(0)).toContainText("PASS · 1 WARNING");
  await expect(chain.nth(1)).toContainText("NEEDS HUMAN APPROVAL");
  await expect(chain.nth(1)).toContainText("09:01:11");
  await expect(chain.nth(2)).toContainText("Account owner · you");
  await expect(chain.nth(2)).toContainText("WAITING");
  await expect(chain.nth(3)).toContainText("PHASE 2 · NO EXECUTION");

  await expect(page.getByTestId("check-row")).toHaveCount(18);
  await expect(page.getByTestId("check-summary")).toHaveText("13 PASS · 1 WARNING · 0 FAIL · 4 SKIPPED");
  const ptr = page.getByTestId("check-row").filter({ hasText: "Per trade risk" });
  await expect(ptr).toContainText("✓");
  await expect(ptr).toContainText("loss 48425.90 (0.484% of equity) vs limit 0.5%");
  await expect(page.getByTestId("check-row").filter({ hasText: "Sector" })).toContainText("!");
  await expect(page.getByTestId("check-row").filter({ hasText: "Drawdown" })).toContainText("–");

  const audit = page.getByTestId("audit-row");
  await expect(audit).toHaveCount(4);
  await expect(audit.nth(0)).toContainText("08:45:42");
  await expect(audit.nth(0)).toContainText("AI Trader");
  await expect(audit.nth(0)).toContainText("SIG-a41f0c9e7b2d3e5f6a7b · PETRONET bullish · Long buildup · score 72.5");
  await expect(audit.nth(1)).toContainText("Trading Assistant");
  await expect(audit.nth(1)).toContainText(`${RISK_P.trade_id} v1 · Bull call spread · max loss ₹48,425.90`);
  await expect(audit.nth(2)).toContainText("Risk & Operations");
  await expect(audit.nth(2)).toContainText(`${RISK_P.assessment_id} PASS · 1 warning`);
  await expect(audit.nth(3)).toContainText("Middle Office");
  await expect(audit.nth(3)).toContainText("NEEDS HUMAN APPROVAL · assisted mode: a person approves every plan");

  // nothing from the prototype's sample data
  await expect(page.getByTestId("screen-approvals")).not.toContainText(/Zerodha|ZX4821|24000|10,927|RSV-|APR-3107|Strategist|Risk Guardian|amit\.p/);
  expect(errors).toEqual([]);
});

test("AD-UI-52 deep link to a decided request (and reload); unknown id shows the API's 404", async ({ page }) => {
  await openQueue(page, { path: `/autodesk/approvals/${APR_ADANI.approval_id}` });
  await expect(page.getByTestId("detail-id")).toContainText(APR_ADANI.approval_id as string);
  await expect(page.getByTestId("decided-banner")).toContainText("APPROVED");
  await expect(page.getByTestId("decided-banner")).toContainText("Approved by Middle Office at 09:01:30. Phase 1 has no execution");
  await expect(page.getByTestId("decision-actions")).toHaveCount(0);
  await expect(page.getByTestId("nav-approvals")).toHaveAttribute("aria-current", "page");
  await page.reload();
  await expect(page.getByTestId("decided-banner")).toContainText("APPROVED");
  await page.goto("/autodesk/approvals/APR-00000000000000000000");
  await expect(page.getByTestId("approval-detail").getByTestId("error-box")).toContainText("not found: APR-00000000000000000000 (404)");
  await expect(page.getByTestId("approval-card")).toHaveCount(0);
});

test("AD-UI-53 empty queue: clear headline, empty state, no detail, no figures", async ({ page }) => {
  await openQueue(page, { over: { "GET /approvals": [] } });
  await expect(page.getByTestId("pending-pill")).toHaveText("0 pending");
  await expect(page.getByTestId("approvals-headline")).toHaveText("The queue is clear. Agents continue inside policy.");
  await expect(page.getByTestId("queue-empty")).toBeVisible();
  await expect(page.getByTestId("approval-detail")).toHaveCount(0);
  await expect(page.getByTestId("history")).toContainText("No decisions recorded yet.");
  await expect(page.getByTestId("screen-approvals")).not.toContainText(/₹\s?\d/);
});

test("AD-UI-54 approve: binding shown, contract body with the version's plan hash, decided state, queue refreshed", async ({ page }) => {
  const { desk } = await openQueue(page);
  await page.getByTestId("approve-btn").click();
  const bind = page.getByTestId("bind-panel");
  await expect(bind).toContainText("Your approval binds exactly this");
  await expect(bind).toContainText(`${TENANT} · Paper · Desk B`);
  await expect(page.getByTestId("bind-hash")).toHaveText(`${RISK_P.trade_id} · v1 · hash 9f3c…a21e`);
  await expect(page.getByTestId("bind-hash")).toHaveAttribute("title", HASH_P);
  await expect(bind).toContainText("PETRONET 310/335 · bull call spread");
  await expect(bind).toContainText("4 lots · 7600 per leg");
  await expect(bind).toContainText("₹1,00,700.00 · ₹48,425.90");
  await expect(bind).toContainText("Assisted paper · no orders in Phase 1");
  await expect(bind).toContainText("15:30:00 IST · 5 Nov · approver Amit P");
  await page.getByTestId("confirm-approve").click();
  await expect(page.getByTestId("decided-banner")).toContainText("APPROVED");
  await expect(page.getByTestId("decided-banner")).toContainText("Approved by You at 11:42:30. Phase 1 has no execution");
  expect(decisionPost(desk)).toHaveLength(1);
  expectContract(decisionPost(desk)[0], "approvals", "approve", { approval_id: APR_P.approval_id as string, plan_hash: HASH_P });
  await expect(page).toHaveURL(new RegExp(`/autodesk/approvals/${APR_P.approval_id}$`));
  await expect(page.getByTestId("chain-row").nth(2)).toContainText("APPROVED");
  await expect(page.getByTestId("decision-actions")).toHaveCount(0);
  await expect(page.getByTestId("pending-pill")).toHaveText("1 pending");
  await expect(page.getByTestId("badge-approvals")).toHaveText("1");
  await expect(page.getByTestId("audit-row").last()).toContainText("You");
});

test("AD-UI-55 reject and request revision: reason chips, contract bodies, decided banners", async ({ page }) => {
  const { desk } = await openQueue(page);
  await page.getByTestId("reject-btn").click();
  await expect(page.getByTestId("reason-panel")).toContainText("Why are you rejecting it?");
  await expect(page.getByTestId("confirm-reason")).toBeDisabled();
  await page.getByTestId("reason-chip").filter({ hasText: "Risk too high for today" }).click();
  await expect(page.getByTestId("confirm-reason")).toHaveText("Reject plan");
  await page.getByTestId("confirm-reason").click();
  await expect(page.getByTestId("decided-banner")).toContainText("REJECTED");
  await expect(page.getByTestId("decided-banner")).toContainText("Rejected by You at 11:42:30. This plan version is closed. Reason: Risk too high for today");
  expectContract(decisionPost(desk)[0], "approvals", "reject", { approval_id: APR_P.approval_id as string, plan_hash: HASH_P });

  await page.getByTestId("approval-item").filter({ hasText: "GRASIM" }).click();
  await expect(page.getByTestId("detail-id")).toContainText(APR_G.approval_id as string);
  await page.getByTestId("revise-btn").click();
  await expect(page.getByTestId("reason-panel")).toContainText("What should the Trading Assistant change?");
  await page.getByTestId("reason-chip").filter({ hasText: "Smaller size" }).click();
  await expect(page.getByTestId("confirm-reason")).toHaveText("Send for revision");
  await page.getByTestId("confirm-reason").click();
  await expect(page.getByTestId("decided-banner")).toContainText("NEEDS REVISION");
  await expect(page.getByTestId("decided-banner")).toContainText("A new version needs a new approval.");
  expectContract(decisionPost(desk)[1], "approvals", "request_revision", { approval_id: APR_G.approval_id as string, plan_hash: HASH_G });
  await expect(page.getByTestId("pending-pill")).toHaveText("0 pending");
});

test("AD-UI-56 decision refused by the API: 409 entries stopped, 409 stale hash, 409 already answered, 500", async ({ page }) => {
  const answers = [
    reply(409, { error: "CONFLICT", message: "new entries are stopped (STOP_NEW_ENTRIES: Stopped from the desk header); lift it to approve, or reject" }),
    reply(409, { error: "CONFLICT", message: "the plan you reviewed is not the current version (plan hash differs)" }),
    reply(409, { error: "CONFLICT", message: "this approval request has already been answered" }),
    reply(500, { detail: "Internal Server Error" }),
  ];
  let n = 0;
  await openQueue(page, { over: { "POST /approvals/:id/decision": () => answers[Math.min(n++, answers.length - 1)] } });
  await page.getByTestId("approve-btn").click();
  await page.getByTestId("confirm-approve").click();
  await expect(page.getByTestId("decision-error")).toHaveText("new entries are stopped (STOP_NEW_ENTRIES: Stopped from the desk header); lift it to approve, or reject (409)");
  await page.getByTestId("confirm-approve").click();
  await expect(page.getByTestId("decision-error")).toHaveText("the plan you reviewed is not the current version (plan hash differs) (409)");
  await page.getByTestId("reject-btn").click();
  await expect(page.getByTestId("decision-error")).toHaveCount(0);
  await page.getByTestId("reason-input").fill("Thesis not convincing");
  await page.getByTestId("confirm-reason").click();
  await expect(page.getByTestId("decision-error")).toHaveText("this approval request has already been answered (409)");
  await page.getByTestId("confirm-reason").click();
  await expect(page.getByTestId("decision-error")).toHaveText("Internal Server Error (500)");
  await expect(page.getByTestId("decided-banner")).toHaveCount(0);
  await expect(page.getByTestId("pending-pill")).toHaveText("2 pending");
  await expect(page.getByTestId("approval-item")).toHaveCount(2);
});

test("AD-UI-57 entries stopped: Approve disabled with the reason, Reject still recorded", async ({ page }) => {
  const { desk } = await openQueue(page, { halted: true });
  await expect(page.getByTestId("halt-banner")).toBeVisible();
  await expect(page.getByTestId("halted-note")).toContainText("New entries are stopped (Stopped from the desk header). The API refuses approvals until entries resume; Reject and Request revision still work.");
  await expect(page.getByTestId("approve-btn")).toBeDisabled();
  await page.getByTestId("reject-btn").click();
  await page.getByTestId("reason-chip").filter({ hasText: "Risk too high for today" }).click();
  await page.getByTestId("confirm-reason").click();
  await expect(page.getByTestId("decided-banner")).toContainText("REJECTED");
  expectContract(decisionPost(desk)[0], "approvals", "reject", { approval_id: APR_P.approval_id as string, plan_hash: HASH_P });
});

test("AD-UI-58 expired request, request approved by the Middle Office, plan changed after the request", async ({ page }) => {
  await openQueue(page, { edit: (w) => { w.approvals[APR_P.approval_id as string] = { ...w.approvals[APR_P.approval_id as string], expires_at: "2026-11-05T06:00:00+00:00" }; } });
  await expect(page.getByTestId("approval-item").nth(0).getByTestId("item-countdown")).toHaveText("EXPIRED");
  await expect(page.getByTestId("approvals-headline")).toContainText("The first lapsed at 11:30.");
  await expect(page.getByTestId("detail-countdown")).toHaveText("EXPIRED");
  await expect(page.getByTestId("expired-banner")).toContainText("The approval window closed at 11:30:00 IST. The API refuses a decision after expiry.");
  await expect(page.getByTestId("decision-actions")).toHaveCount(0);
  await expect(page.getByTestId("chain-row").nth(2)).toContainText("EXPIRED");

  await page.getByTestId("history-row").filter({ hasText: "ADANIPORTS" }).click();
  await expect(page).toHaveURL(new RegExp(`/autodesk/approvals/${APR_ADANI.approval_id}$`));
  await expect(page.getByTestId("decided-banner")).toContainText("Approved by Middle Office");
  await expect(page.getByTestId("chain-row").nth(1)).toContainText("APPROVED");
  await expect(page.getByTestId("chain-row").nth(2)).toContainText("NOT NEEDED");
  await expect(page.getByTestId("decision-actions")).toHaveCount(0);
  await expect(page.getByTestId("risk-id")).toContainText("RSK-7a2c9e5db3f4618ac2d3 · PASS");
  await expect(page.getByTestId("detail-mode")).toHaveText("Auto paper");
});

test("AD-UI-58b plan changed after the request: no actions, the API would refuse", async ({ page }) => {
  await openQueue(page, {
    edit: (w) => {
      const p = w.plans[RISK_P.trade_id];
      p.head = { ...p.head, current_version: 2 };
      p.versions[2] = { ...p.versions[1], created_at: "2026-11-05T05:00:00+00:00", change_reason: "smaller size" };
    },
  });
  await expect(page.getByTestId("version-banner")).toContainText("The plan is now at v2; this request binds v1. The API refuses a decision on an older version.");
  await expect(page.getByTestId("decision-actions")).toHaveCount(0);
  await expect(page.getByTestId("audit-row").filter({ hasText: "v2" })).toContainText("smaller size");
});

test("AD-UI-59 load errors: queue and plan show the API message", async ({ page }) => {
  await openQueue(page, {
    over: {
      "GET /approvals": (r: Req) => (r.query.get("pending") === "true" ? reply(500, { error: "INTERNAL", message: "database unavailable" }) : []),
    },
  });
  await expect(page.getByTestId("approval-list").getByTestId("error-box")).toContainText("database unavailable (500)", { timeout: 15000 });
  await expect(page.getByTestId("pending-pill")).toHaveText("? pending");

  await page.unrouteAll({ behavior: "ignoreErrors" });
  const w = world();
  await mockDesk(page, { routes: approvalsRoutes(w, { "GET /trade-plans/:id": reply(500, { detail: "upstream timeout" }) }), state: { accounts: [{ ...ACCOUNT_A }, { ...ACCOUNT_B }] } });
  await page.goto(`/autodesk/approvals/${APR_P.approval_id}`);
  await expect(page.getByTestId("approval-card").getByTestId("error-box")).toContainText("upstream timeout (500)", { timeout: 15000 });
  await expect(page.getByTestId("decision-actions").getByTestId("approve-btn")).toBeDisabled();
});

test("AD-UI-59b phone 390×844: list first, detail with back link, no overflow, only desk URLs", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const other: string[] = [];
  page.on("request", (r) => {
    const u = new URL(r.url());
    if (/fonts\.(googleapis|gstatic)\.com/.test(u.host)) return;
    if (u.pathname.startsWith("/autodesk/") || u.pathname === "/api/auth/me" || u.pathname === "/api/live/quotes") return;
    other.push(u.pathname);
  });
  const errors = collectConsoleErrors(page);
  await openQueue(page);
  await expect(page.getByTestId("approval-list")).toBeVisible();
  await expect(page.getByTestId("approval-detail")).toHaveCount(0);
  const ov1 = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(ov1).toBeLessThanOrEqual(0);
  await page.getByTestId("approval-item").first().click();
  await expect(page.getByTestId("approval-detail")).toBeVisible();
  await expect(page.getByTestId("approval-list")).toHaveCount(0);
  await expect(page.getByTestId("check-row")).toHaveCount(18);
  await page.getByTestId("approve-btn").click();
  await expect(page.getByTestId("bind-panel")).toBeVisible();
  const ov2 = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(ov2).toBeLessThanOrEqual(0);
  await page.getByTestId("back-to-list").click();
  await expect(page.getByTestId("approval-list")).toBeVisible();
  expect(other).toEqual([]);
  expect(errors).toEqual([]);
});
