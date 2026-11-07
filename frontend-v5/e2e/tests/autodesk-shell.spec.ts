/**
 * Desk web app — shell (AD-UI-01..16, AD-UI-90). Test cases: docs/autodesk/TESTCASES.md "Desk web app (UI)".
 * API answered by route mocks (autodesk-mock.ts — MOCK, shapes of the real API).
 */
import { expect, test } from "@playwright/test";
import { ACCOUNT_A, AGENTS_STATUS, LIVE_OPEN, collectConsoleErrors, deskStatus, expectContract, mockDesk, reply } from "./autodesk-mock";

test("AD-UI-01 desktop frame: sidebar, 12 numbered items in 3 groups, header, overview active", async ({ page }) => {
  const errors = collectConsoleErrors(page);
  const desk = await mockDesk(page);
  await page.goto("/autodesk/");
  await expect(page.getByTestId("desk-desktop")).toBeVisible();
  const aside = page.locator("aside");
  const box = await aside.boundingBox();
  expect(Math.round(box!.width)).toBe(236);
  for (const g of ["Desk", "Positions", "Control"]) await expect(aside.getByText(g, { exact: true })).toBeVisible();
  const items = aside.locator("nav a");
  await expect(items).toHaveCount(12);
  await expect(items.nth(0)).toContainText("01");
  await expect(items.nth(0)).toContainText("Desk overview");
  await expect(items.nth(11)).toContainText("12");
  await expect(items.nth(11)).toContainText("Policies & permissions");
  await expect(page.getByTestId("nav-overview")).toHaveAttribute("aria-current", "page");
  await expect(page.getByTestId("me-name")).toHaveText("Amit P");
  expect(desk.unmatched).toEqual([]);
  expect(errors).toEqual([]);
});

test("AD-UI-02 signed out: sign-in screen, no shell data", async ({ page }) => {
  await mockDesk(page, { routes: { "GET /desk/status": reply(401, { detail: "Not authenticated" }), "GET /accounts": reply(401, { detail: "Not authenticated" }) } });
  await page.goto("/autodesk/");
  await expect(page.getByTestId("sign-in")).toBeVisible();
  await expect(page.getByTestId("sign-in-link")).toHaveAttribute("href", "/v5/login");
  await expect(page.locator("aside")).toHaveCount(0);
});

test("AD-UI-03 accounts card lists desk accounts with mode pills, no broker rows", async ({ page }) => {
  await mockDesk(page, {
    state: {
      accounts: [
        { ...ACCOUNT_A },
        { ...ACCOUNT_A, account_id: "ACC-2", name: "Desk B", operating_mode: "ASSISTED" },
        { ...ACCOUNT_A, account_id: "ACC-3", name: "Research", operating_mode: "RESEARCH" },
      ],
    },
  });
  await page.goto("/autodesk/");
  const rows = page.getByTestId("account-row");
  await expect(rows).toHaveCount(3);
  await expect(rows.nth(0)).toContainText("Paper · Desk A");
  await expect(rows.nth(0)).toContainText("Auto");
  await expect(rows.nth(1)).toContainText("Assisted");
  await expect(rows.nth(2)).toContainText("Research");
  await expect(page.getByTestId("accounts-card")).not.toContainText(/Zerodha|ICICI/);
});

test("AD-UI-04 no account: create a paper account sends the contract body and lists it", async ({ page }) => {
  const desk = await mockDesk(page, { state: { accounts: [] } });
  await page.goto("/autodesk/");
  await expect(page.getByTestId("accounts-card")).toContainText("No desk account yet");
  await page.getByTestId("new-account").click();
  await page.getByTestId("account-create").click();
  await expect(page.getByTestId("account-dialog")).toHaveCount(0);
  expectContract(desk.posts.find((p) => p.path === "/accounts"), "shell", "create_account");
  await expect(page.getByTestId("account-row")).toHaveCount(1);
  await expect(page.getByTestId("account-row").first()).toContainText("Research");
});

test("AD-UI-05 header strip from the live feed: NSE open, ticking IST clock, index values", async ({ page }) => {
  await mockDesk(page);
  await page.goto("/autodesk/");
  await expect(page.getByTestId("session-pill")).toHaveText("NSE open");
  await expect(page.getByTestId("ticker-NIFTY")).toContainText("24,012.35");
  await expect(page.getByTestId("ticker-NIFTY")).toContainText("+0.22%");
  await expect(page.getByTestId("ticker-BANKNIFTY")).toContainText("55,742.60");
  await expect(page.getByTestId("ticker-VIX")).toContainText("12.84");
  await expect(page.getByTestId("ticker-VIX")).toContainText("−2.13%");
  await expect(page.getByTestId("feed-pill")).toHaveText("Kite feed live");
  const c1 = await page.getByTestId("clock").textContent();
  expect(c1).toMatch(/^\d{2}:\d{2}:\d{2} IST$/);
  await expect.poll(async () => page.getByTestId("clock").textContent(), { timeout: 4000 }).not.toBe(c1);
});

test("AD-UI-06 feed closed shows the close; not connected or failing shows no numbers", async ({ page }) => {
  const desk = await mockDesk(page, { routes: { "GET /api/live/quotes": { ...LIVE_OPEN, mode: "closed", session: "closed", final: true, stale: false } } });
  await page.goto("/autodesk/");
  await expect(page.getByTestId("session-pill")).toHaveText("NSE closed");
  await expect(page.getByTestId("ticker-NIFTY")).toContainText("close");

  await page.unrouteAll({ behavior: "ignoreErrors" });
  await mockDesk(page, { routes: { "GET /api/live/quotes": { ...LIVE_OPEN, mode: "not_connected", stale: true } } });
  await page.reload();
  await expect(page.getByTestId("tickers-unavailable")).toHaveText("Index quotes unavailable");
  await expect(page.getByTestId("feed-pill")).toHaveText("Kite feed not connected");
  await expect(page.locator("header")).not.toContainText("24,012.35");

  await page.unrouteAll({ behavior: "ignoreErrors" });
  await mockDesk(page, { routes: { "GET /api/live/quotes": reply(500, { detail: "boom" }) } });
  await page.reload();
  await expect(page.getByTestId("tickers-unavailable")).toBeVisible();
  await expect(page.getByTestId("feed-pill")).toHaveText("Kite feed unavailable");
  await expect(page.getByTestId("session-pill")).toHaveText("NSE session unknown");
  expect(desk.unmatched).toEqual([]);
});

test("AD-UI-07 agents pill counts healthy agents and opens the fleet screen", async ({ page }) => {
  const agents = AGENTS_STATUS.map((a) => (a.agent_key === "TECH_SUPPORT" ? { ...a, status: "DEGRADED" } : a));
  await mockDesk(page, { routes: { "GET /desk/status": (_r, s) => deskStatus(s, { agents }) } });
  await page.goto("/autodesk/");
  await expect(page.getByTestId("agents-pill")).toHaveText("4/5 agents healthy");
  await expect(page.getByTestId("badge-fleet")).toHaveText("1");
  await page.getByTestId("agents-pill").click();
  await expect(page).toHaveURL(/\/autodesk\/fleet$/);
  await expect(page.getByTestId("screen-fleet")).toBeVisible();
});

test("AD-UI-07b the agents pill counts each agent once (newest version), not every registered version", async ({ page }) => {
  // The registry keeps a row per version, newest first per agent (store.list_agents).
  const agents = [
    ...AGENTS_STATUS.slice(0, 2),
    { agent_key: "AI_TRADER", version: "autodesk-ait-v0", kind: "DETERMINISTIC", status: "OFFLINE", last_heartbeat: "2026-11-04T05:31:09.870Z" },
    ...AGENTS_STATUS.slice(2),
  ];
  await mockDesk(page, { routes: { "GET /desk/status": (_r, s) => deskStatus(s, { agents }) } });
  await page.goto("/autodesk/");
  await expect(page.getByTestId("agents-pill")).toHaveText("5/5 agents healthy");
  await expect(page.getByTestId("badge-fleet")).toHaveCount(0);
});

test("AD-UI-08/09 stop and resume new entries: contract bodies, banner, button state", async ({ page }) => {
  const desk = await mockDesk(page);
  await page.goto("/autodesk/");
  await expect(page.getByTestId("halt-banner")).toHaveCount(0);
  await page.getByTestId("stop-entries").click();
  await expect(page.getByTestId("stop-dialog")).toContainText("No new trade plans are proposed");
  await page.getByTestId("stop-confirm").click();
  await expect(page.getByTestId("halt-banner")).toContainText("ENTRIES STOPPED");
  await expect(page.getByTestId("halt-banner")).toContainText("11:42:30 IST by user_7f3a9c");
  await expect(page.getByTestId("halt-banner")).toContainText("simulations of past sessions are not affected");
  expectContract(desk.posts[0], "shell", "stop_entries");

  await page.getByTestId("resume-entries").click();
  await page.getByTestId("stop-confirm").click();
  await expect(page.getByTestId("halt-banner")).toHaveCount(0);
  await expect(page.getByTestId("stop-entries")).toBeVisible();
  expectContract(desk.posts[1], "shell", "resume_entries");
});

test("AD-UI-10 a failed control POST shows the API message and changes nothing", async ({ page }) => {
  await mockDesk(page, { routes: { "POST /desk/controls/:control": reply(403, { error: "FORBIDDEN", message: "only the account owner may stop entries" }) } });
  await page.goto("/autodesk/");
  await page.getByTestId("stop-entries").click();
  await page.getByTestId("stop-confirm").click();
  await expect(page.getByTestId("stop-error")).toContainText("only the account owner may stop entries (403)");
  await expect(page.getByTestId("halt-banner")).toHaveCount(0);
});

test("AD-UI-11 nav badges: pending approvals (desk only) and SIM", async ({ page }) => {
  const appr = (id: string, sim: string | null) => ({
    approval_id: id, trade_id: "TRD-1", plan_version: 1, account_id: ACCOUNT_A.account_id, simulation_id: sim, status: "NEEDS_HUMAN_APPROVAL",
    decided_by: "MIDDLE_OFFICE@autodesk-mo-v1", body: {}, risk_assessment_id: "RSK-1", supersedes_id: null, expires_at: "2026-11-05T10:00:00Z", created_at: "2026-11-05T05:31:11Z",
  });
  await mockDesk(page, { routes: { "GET /approvals": [appr("APR-1", null), appr("APR-2", null), appr("APR-3", "SIM-1")] } });
  await page.goto("/autodesk/");
  await expect(page.getByTestId("badge-approvals")).toHaveText("2");
  await expect(page.getByTestId("badge-sim")).toHaveText("SIM");
});

for (const id of ["workbench", "trades", "pnl", "risk", "middle", "fleet"]) {
  test(`AD-UI-12 ${id} is a labelled placeholder screen with no sample figures and no claim that nothing is executed`, async ({ page }) => {
    await mockDesk(page);
    await page.goto("/autodesk/");
    await page.getByTestId(`nav-${id}`).click();
    const s = page.getByTestId(`screen-${id}`);
    await expect(s).toBeVisible();
    await expect(s.getByTestId("phase2-note")).toContainText(/Not (shown|built) yet/);
    await expect(s.getByTestId("phase2-note")).not.toContainText("comes in Phase 2");
    await expect(s).not.toContainText(/₹\s?\d/);
    await expect(s).not.toContainText(/Phase 1 has no|Nothing is executed|no orders, fills or positions/);
  });
}

test("AD-UI-13 phone: top bar, five tabs, approvals badge, More sheet with all screens", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const appr = { approval_id: "APR-1", trade_id: "TRD-1", plan_version: 1, account_id: ACCOUNT_A.account_id, simulation_id: null, status: "NEEDS_HUMAN_APPROVAL", decided_by: null, body: {}, risk_assessment_id: null, supersedes_id: null, expires_at: null, created_at: "2026-11-05T05:31:11Z" };
  await mockDesk(page, { routes: { "GET /approvals": [appr] } });
  await page.goto("/autodesk/");
  await expect(page.getByTestId("desk-mobile")).toBeVisible();
  await expect(page.getByTestId("mobile-title")).toHaveText("Desk overview");
  await expect(page.getByTestId("stop-entries")).toContainText("STOP");
  const tabs = page.getByTestId("tabbar").locator("button");
  await expect(tabs).toHaveCount(5);
  for (const [i, t] of ["Desk", "Trades", "Approve", "P&L", "More"].entries()) await expect(tabs.nth(i)).toContainText(t);
  await expect(page.getByTestId("tab-approvals-badge")).toHaveText("1");
  await page.getByTestId("tab-more").click();
  await expect(page.getByTestId("more-sheet").locator("nav a")).toHaveCount(12);
  await page.getByTestId("more-sheet").getByTestId("nav-policies").click();
  await expect(page.getByTestId("mobile-title")).toHaveText("Policies & permissions");
  await expect(page.getByTestId("more-sheet")).toHaveCount(0);
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow).toBeLessThanOrEqual(0);
});

test("AD-UI-14 deep link and reload keep the screen (SPA fallback)", async ({ page }) => {
  await mockDesk(page);
  await page.goto("/autodesk/approvals");
  await expect(page.getByTestId("screen-approvals")).toBeVisible();
  await page.reload();
  await expect(page.getByTestId("screen-approvals")).toBeVisible();
  await expect(page.getByTestId("nav-approvals")).toHaveAttribute("aria-current", "page");
});

test("AD-UI-15 light theme sticks after reload", async ({ page }) => {
  await mockDesk(page);
  await page.goto("/autodesk/");
  await expect(page.getByTestId("desk-desktop")).toHaveAttribute("data-theme", "dark");
  await page.getByTestId("theme-toggle").click();
  await expect(page.getByTestId("desk-desktop")).toHaveAttribute("data-theme", "light");
  await page.reload();
  await expect(page.getByTestId("desk-desktop")).toHaveAttribute("data-theme", "light");
});

test("AD-UI-16/90 only the desk API, /api/auth/me and /api/live/quotes are called; assets under /autodesk/", async ({ page }) => {
  const other: string[] = [];
  page.on("request", (r) => {
    const u = new URL(r.url());
    if (/fonts\.(googleapis|gstatic)\.com/.test(u.host)) return;
    if (u.pathname.startsWith("/autodesk/api/v1/") || u.pathname === "/api/auth/me" || u.pathname === "/api/live/quotes") return;
    if (u.pathname.startsWith("/autodesk/")) return;    // the app's own document and assets
    other.push(u.pathname);
  });
  const errors = collectConsoleErrors(page);
  await mockDesk(page);
  await page.goto("/autodesk/");
  await expect(page.getByTestId("desk-desktop")).toBeVisible();
  for (const id of ["agents", "scanner", "approvals", "sim", "policies"]) await page.getByTestId(`nav-${id}`).click();
  const assets = await page.evaluate(() => Array.from(document.querySelectorAll("script[src],link[rel=stylesheet][href]")).map((e) => e.getAttribute("src") ?? e.getAttribute("href") ?? ""));
  expect(assets.filter((a) => !a.startsWith("https://fonts.")).every((a) => a.startsWith("/autodesk/assets/"))).toBe(true);
  expect(other).toEqual([]);
  expect(errors).toEqual([]);
});
