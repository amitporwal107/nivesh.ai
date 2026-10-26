/**
 * One-screen Copilot app (/v5/app) — F&O lab, the Kite sessions panel (screens/fnolab/KiteSessions.tsx) on 09 Live Desk and
 * 01 Market Intelligence: the platform's daily Kite data login (admin) and the user's own read-only Zerodha connection.
 *
 * MOCK — not real data: GET /api/live/status, the quote stream, POST /api/live/kite/login-url, GET /api/broker/accounts,
 * GET /api/broker/native/supported and GET /api/broker/native/start/zerodha are answered by the fixtures below (INVENTED ids,
 * masked client id and times). Whether Zerodha really redirects back is checked on staging, not here.
 *
 * Cases (test_reports/fno_lab_screens_TESTCASES.md): K-1..K-8.
 */
import { test, expect, type Page } from "@playwright/test";
import { mockApi } from "../helpers/api-mock";

const LIVE = "/v5/app/tool/fnolab?screen=live";
const MI = "/v5/app/tool/fnolab?screen=mi";
const ADMIN = { user_id: "u_admin", email: "admin@example.test", name: "Admin Fixture", is_admin: true, onboarding_completed: true };
const PLAIN = { user_id: "u_plain", email: "user@example.test", name: "Fixture User", is_admin: false, onboarding_completed: true };

const liveStatus = (o: Record<string, unknown> = {}) => ({
  enabled: true, mode: "expired", state: "expired", session: "open", reason: "regular_session", alert_state: "TOKEN_ALERT", token_alert: { state: "TOKEN_ALERT" },
  cadence_seconds: 30, instrument_count: 0, read_only: true, platform_token: { stored: true, valid_until: "2026-10-26T00:30:00+00:00", expired: true }, ...o,
});
const quotes = (mode: string) => ({
  as_of: "2026-10-26T05:43:10+00:00", data_at: "2026-10-26T05:43:09+00:00", age_seconds: 1, stale: mode !== "live", cadence_seconds: 30, mode,
  session: mode === "closed" ? "closed" : "open", source: "ws", final: false, count: 0, missing: [], quotes: {},
});
const riskStatus = {
  user_id: "u_fixture", kill_switch: false, halted: false, reason: null, set_by: null, set_at: null, policy_version: "risk-controls-v1", can_reset: false,
  live_authorization: { granted: false, granted_by: null, granted_at: null, reason: null }, modes: ["paper", "shadow", "assisted", "live"],
  live_execution_available: false, gate: { enabled: false, policy_version: "fno-risk-v1" },
};
const ZERODHA = { slug: "zerodha", name: "Zerodha", implemented: true, auth_style: "oauth", configured: true, connectable: true };
const account = (o: Record<string, unknown> = {}) => ({
  account_id: "acc-fixture-z1", broker: "zerodha", broker_display: "Zerodha", label: null, status: "active", last_sync_at: "2026-10-26T03:00:00+00:00",
  last_sync_count: 0, last_error: null, created_at: "2026-10-14T03:00:00+00:00", native: true, broker_user_masked: "••••34",
  session_expires_at: "2026-10-27T00:30:00+00:00", session_ended_reason: null, needs_reconnect: false, ...o,
});

interface Opts { admin?: boolean; st?: Record<string, unknown>; feedMode?: string; accounts?: unknown[]; url?: string }

async function open(page: Page, o: Opts = {}) {
  const seen: string[] = [];
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.addInitScript(() => localStorage.setItem("nivesh.copilot", JSON.stringify({ state: { mode: "trader", evidenceOpen: null }, version: 0 })));
  await mockApi(page, "populated");
  const json = (pattern: string, body: unknown) => page.route(pattern, (route) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) }));
  await page.route("**/api/chat/sessions", (route) => route.fulfill({ status: 200, contentType: "application/json", body: "[]" }));
  await json("**/api/auth/me", o.admin === false ? PLAIN : ADMIN);
  await json("**/api/risk/status", riskStatus);
  await json("**/api/broker/accounts", { accounts: o.accounts ?? [] });
  await json("**/api/broker/native/supported", { brokers: [ZERODHA] });
  await page.route("**/api/broker/native/start/**", (route) => {
    seen.push(`START ${route.request().url()}`);
    return route.fulfill({ status: 302, headers: { location: "/v5/kite-login-stub?broker=zerodha" }, body: "" });
  });
  await page.route("**/api/live/**", (route) => {
    const req = route.request();
    const p = new URL(req.url()).pathname;
    seen.push(`${req.method()} ${p}`);
    if (p.endsWith("/status")) return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(liveStatus(o.st)) });
    if (p.endsWith("/kite/login-url")) return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ login_url: "/v5/kite-login-stub?go=1", expires_at: "2026-10-26T06:30:00+00:00" }) });
    if (p.endsWith("/stream")) return route.fulfill({ status: 200, contentType: "text/event-stream", body: `retry: 100\n\nevent: snapshot\ndata: ${JSON.stringify(quotes(o.feedMode ?? "expired"))}\n\n` });
    if (p.endsWith("/option-chain")) return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ underlying: "NIFTY", expiry: null, cache: "empty", rows: [], count: 0, strikes: 0, stale_count: 0, session: "open", cadence_seconds: 30, stale_after_seconds: 60, read_only: true }) });
    return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(quotes(o.feedMode ?? "expired")) });
  });
  await page.route("**/kite-login-stub*", (route) => route.fulfill({ status: 200, contentType: "text/html", body: "<title>stub</title>" }));
  await page.goto(o.url ?? LIVE);
  await expect(page.getByTestId("fnolab-kite")).toBeVisible();
  return seen;
}

test.describe("MOCK — not real data: F&O lab Kite sessions", () => {
  test("K-1 admin, feed expired in a session: Log in to Kite fetches a fresh link and goes there", async ({ page }) => {
    const seen = await open(page);
    const row = page.getByTestId("fnolab-kite-platform");
    await expect(row).toHaveAttribute("data-state", "login_needed");
    await expect(row).toContainText("Kite login needed");
    await expect(row).toContainText("platform's own Zerodha account");
    const nav = page.waitForRequest((r) => r.url().includes("/kite-login-stub?go=1"));
    await page.getByTestId("fnolab-kite-login").click();
    await nav;
    expect(seen).toContain("POST /api/live/kite/login-url");
  });

  test("K-2 non-admin: no login button; an admin logs in once a day", async ({ page }) => {
    await open(page, { admin: false });
    const row = page.getByTestId("fnolab-kite-platform");
    await expect(row).toHaveAttribute("data-state", "login_needed");
    await expect(row).toContainText("An admin logs in to Kite once a day");
    await expect(page.getByTestId("fnolab-kite-login")).toHaveCount(0);
  });

  test("K-3 feed LIVE: the session is active and no login is offered", async ({ page }) => {
    await open(page, { st: { mode: "live", state: "live", alert_state: null, token_alert: { state: null } }, feedMode: "live" });
    const row = page.getByTestId("fnolab-kite-platform");
    await expect(row).toHaveAttribute("data-state", "live");
    await expect(row).toContainText("Today's Kite session is active; quotes refresh every 30 seconds.");
    await expect(page.getByTestId("fnolab-kite-login")).toHaveCount(0);
  });

  test("K-4 market closed with a valid stored token: closed, and how long today's session is valid", async ({ page }) => {
    await open(page, {
      st: { mode: "closed", state: "closed", session: "closed", reason: "after_close", alert_state: null, token_alert: { state: null },
        platform_token: { stored: true, valid_until: "2026-10-27T00:30:00+00:00", expired: false } },
      feedMode: "closed",
    });
    const row = page.getByTestId("fnolab-kite-platform");
    await expect(row).toHaveAttribute("data-state", "closed");
    await expect(row).toContainText("The NSE session is closed. Today's Kite session is valid until");
    await expect(row).toContainText("06:00 IST");                   // 00:30 UTC = 06:00 IST
    await expect(page.getByTestId("fnolab-kite-login")).toHaveCount(0);
  });

  test("K-5 no Zerodha account: Connect Zerodha starts the broker sign-in and comes back to this screen", async ({ page }) => {
    const seen = await open(page);
    const own = page.getByTestId("fnolab-kite-own");
    await expect(own).toHaveAttribute("data-state", "none");
    await expect(own).toContainText("No Zerodha account is connected.");
    await expect(page.getByTestId("fnolab-kite-own-readonly")).toContainText("Read-only today");
    const nav = page.waitForRequest((r) => r.url().includes("/kite-login-stub?broker=zerodha"));
    await page.getByTestId("fnolab-kite-connect").click();
    await nav;
    const start = seen.find((s) => s.startsWith("START "));
    expect(start).toBeTruthy();
    const u = new URL(start!.slice(6));
    expect(u.pathname).toBe("/api/broker/native/start/zerodha");
    expect(u.searchParams.get("return_to")).toBe("/v5/app/tool/fnolab?screen=live");
  });

  test("K-6 Zerodha account active: connected with the masked client id; no connect button", async ({ page }) => {
    await open(page, { accounts: [account()] });
    const own = page.getByTestId("fnolab-kite-own");
    await expect(own).toHaveAttribute("data-state", "connected");
    await expect(own).toContainText("Zerodha ••••34 is connected");
    await expect(own).toContainText("27 Oct");
    await expect(page.getByTestId("fnolab-kite-connect")).toHaveCount(0);
    await expect(page.getByTestId("fnolab-kite-own-readonly")).toContainText("order adapter and certification (P3.2)");
  });

  test("K-7 Zerodha session ended: Reconnect Zerodha", async ({ page }) => {
    await open(page, { accounts: [account({ needs_reconnect: true, session_expires_at: null, session_ended_reason: "expired", status: "expired" })] });
    await expect(page.getByTestId("fnolab-kite-own")).toHaveAttribute("data-state", "reconnect");
    await expect(page.getByTestId("fnolab-kite-connect")).toHaveText("Reconnect Zerodha");
  });

  test("K-8 Market Intelligence shows the platform row only", async ({ page }) => {
    await open(page, { url: MI });
    await expect(page.getByTestId("fnolab-kite-platform")).toHaveAttribute("data-state", "login_needed");
    await expect(page.getByTestId("fnolab-kite-own")).toHaveCount(0);
  });
});
