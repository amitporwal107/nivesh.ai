/**
 * One-screen Copilot app (/v5/app) — the in-app notice for the daily Kite login (admin only; no email or Telegram).
 *
 * MOCK — not real data: GET /api/live/status, the quote stream and POST /api/live/kite/login-url are answered by fixtures below.
 * Covers components/KiteLoginNotice.tsx: the banner for an admin while alert_state is TOKEN_ALERT (or the feed is expired /
 * not connected in a session), nothing for a non-admin (and no status request), dismiss until reload, the Log in to Kite button
 * (fresh login URL, navigates), auto-hide when the feed turns LIVE, the "Kite connected" toast and a readable ?kite=error reason.
 * Whether Zerodha really redirects back with these parameters is UNVERIFIED (see test_reports/OVERRIDE_kite_live_feed.md).
 */
import { test, expect, type Page } from "@playwright/test";
import { mockApi } from "../helpers/api-mock";

const TRADER = "/v5/app/trader";
const ADMIN = { user_id: "u_admin", email: "aporwal107@gmail.com", name: "Admin Fixture", is_admin: true, onboarding_completed: true };
const PLAIN = { user_id: "u_plain", email: "user@example.test", name: "Fixture User", is_admin: false, onboarding_completed: true };

function status(over: Record<string, unknown> = {}) {
  return { enabled: true, mode: "expired", state: "expired", session: "open", reason: "regular_session", alert_state: "TOKEN_ALERT", token_alert: { state: "TOKEN_ALERT" },
    cadence_seconds: 30, instrument_count: 0, read_only: true, ...over };
}
function quotes(mode: string) {
  return { as_of: "2026-10-21T05:43:10+00:00", data_at: "2026-10-21T05:43:09+00:00", age_seconds: 1, stale: mode !== "live", cadence_seconds: 30, mode, session: "open", source: "ws", final: false, count: 0, missing: [], quotes: {} };
}

async function open(page: Page, o: { admin?: boolean; st?: Record<string, unknown>; feedMode?: string; url?: string; mode?: "trader" | "investor" } = {}) {
  const seen: string[] = [];
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.addInitScript((mode) => localStorage.setItem("nivesh.copilot", JSON.stringify({ state: { mode, evidenceOpen: null }, version: 0 })), o.mode ?? "trader");
  await mockApi(page, "populated");
  await page.route("**/api/auth/me", (route) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(o.admin === false ? PLAIN : ADMIN) }));
  await page.route("**/api/live/**", (route) => {
    const req = route.request();
    const path = new URL(req.url()).pathname;
    seen.push(`${req.method()} ${path}`);
    if (path.endsWith("/status")) return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(status(o.st)) });
    if (path.endsWith("/kite/login-url")) return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ login_url: "/v5/kite-login-stub?go=1", expires_at: "2026-10-21T06:30:00+00:00" }) });
    if (path.endsWith("/stream")) return route.fulfill({ status: 200, contentType: "text/event-stream", body: `retry: 100\n\nevent: snapshot\ndata: ${JSON.stringify(quotes(o.feedMode ?? "expired"))}\n\n` });
    return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(quotes(o.feedMode ?? "expired")) });
  });
  await page.route("**/kite-login-stub*", (route) => route.fulfill({ status: 200, contentType: "text/html", body: "<title>stub</title>" }));
  await page.goto(o.url ?? TRADER);
  return seen;
}

test.describe("Kite login notice", () => {
  test("an admin sees the banner while the alert is on; Log in to Kite fetches a fresh link and goes there", async ({ page }) => {
    const seen = await open(page);
    const banner = page.getByTestId("kite-login-banner");
    await expect(banner).toBeVisible();
    await expect(banner).toContainText("Kite login needed — 2FA required to start live data");
    await expect(banner).toHaveAttribute("data-alert", "TOKEN_ALERT");
    const nav = page.waitForRequest((r) => r.url().includes("/kite-login-stub?go=1"));
    await page.getByTestId("kite-login-banner-login").click();
    await nav;
    expect(seen).toContain("POST /api/live/kite/login-url");
  });

  test("a non-admin sees nothing and the status is never requested for them", async ({ page }) => {
    const seen = await open(page, { admin: false });
    await expect(page.getByTestId("copilot-app")).toBeVisible();
    await page.waitForTimeout(800);
    await expect(page.getByTestId("kite-login-banner")).toHaveCount(0);
    await expect(page.getByTestId("kite-toast")).toHaveCount(0);
    expect(seen.some((c) => c.endsWith("/api/live/status"))).toBe(false);
  });

  test("dismiss hides the banner for now; a reload brings it back while the problem is unresolved", async ({ page }) => {
    await open(page);
    await page.getByTestId("kite-login-banner-dismiss").click();
    await expect(page.getByTestId("kite-login-banner")).toHaveCount(0);
    await page.reload();
    await expect(page.getByTestId("kite-login-banner")).toBeVisible();
  });

  test("the banner is not shown when the alert is off and the feed is fine, or the market is closed", async ({ page }) => {
    await open(page, { st: { mode: "live", state: "live", alert_state: null, token_alert: { state: null } }, feedMode: "live" });
    await expect(page.getByTestId("live-chip")).toHaveAttribute("data-mode", "live");
    await expect(page.getByTestId("kite-login-banner")).toHaveCount(0);
  });

  test("it hides by itself once the feed turns LIVE", async ({ page }) => {
    await open(page, { feedMode: "live" });                                  // the status still says alert, the stream says LIVE
    await expect(page.getByTestId("live-chip")).toHaveAttribute("data-mode", "live");
    await expect(page.getByTestId("kite-login-banner")).toHaveCount(0);
  });

  test("an expired token in a session shows the banner even before the alert fires", async ({ page }) => {
    await open(page, { st: { alert_state: null, token_alert: { state: null }, mode: "not_connected", state: "not_connected" } });
    await expect(page.getByTestId("kite-login-banner")).toBeVisible();
  });

  // 2026-10-26: after 15:30 the alert stops, but a login still lets the feed save the day's close (login_needed, close_not_saved).
  const AFTER_CLOSE = { session: "closed", reason: "after_hours", alert_state: null, token_alert: { state: null }, mode: "expired", state: "expired" };

  test("after the close, until the day's close is saved, the banner asks for the login to save today's closing prices", async ({ page }) => {
    const seen = await open(page, { st: { ...AFTER_CLOSE, login_needed: true, login_why: "close_not_saved", close_saved_today: false } });
    const banner = page.getByTestId("kite-login-banner");
    await expect(banner).toBeVisible();
    await expect(banner).toHaveAttribute("data-why", "close_not_saved");
    await expect(page.getByTestId("kite-login-banner-title")).toHaveText("Kite login needed — 2FA required to save today’s closing prices");
    await expect(banner).toContainText("today’s Kite close shows until the bhavcopy end of day lands");
    const nav = page.waitForRequest((r) => r.url().includes("/kite-login-stub?go=1"));
    await page.getByTestId("kite-login-banner-login").click();
    await nav;
    expect(seen).toContain("POST /api/live/kite/login-url");
  });

  test("after the close, once the day's close is saved, there is no banner", async ({ page }) => {
    await open(page, { st: { ...AFTER_CLOSE, login_needed: false, login_why: null, close_saved_today: true } });
    await expect(page.getByTestId("copilot-app")).toBeVisible();
    await page.waitForTimeout(800);
    await expect(page.getByTestId("kite-login-banner")).toHaveCount(0);
  });

  test("an admin in Investor mode gets the banner too", async ({ page }) => {
    await open(page, { mode: "investor", url: "/v5/app", st: { ...AFTER_CLOSE, login_needed: true, login_why: "close_not_saved" } });
    await expect(page.getByTestId("kite-login-banner")).toBeVisible();
  });

  test("back from Zerodha: ?kite=connected shows a Kite connected toast and the parameter leaves the address bar", async ({ page }) => {
    await open(page, { url: `${TRADER}?kite=connected`, feedMode: "live", st: { mode: "live", state: "live", alert_state: null, token_alert: { state: null } } });
    const toast = page.getByTestId("kite-toast");
    await expect(toast).toContainText("Kite connected");
    await expect(toast).toHaveAttribute("data-kind", "connected");
    expect(page.url()).not.toContain("kite=");
  });

  test("back from Zerodha with an error: the reason is readable", async ({ page }) => {
    await open(page, { url: `${TRADER}?kite=error&reason=wrong_account` });
    const toast = page.getByTestId("kite-toast");
    await expect(toast).toHaveAttribute("data-kind", "error");
    await expect(toast).toContainText("not the platform account");
    await page.getByTestId("kite-toast-close").click();
    await expect(toast).toHaveCount(0);
  });

  test("an unknown error code still gets a sentence, never a raw code", async ({ page }) => {
    await open(page, { url: `${TRADER}?kite=error&reason=zzz_unknown` });
    await expect(page.getByTestId("kite-toast")).toContainText("did not complete");
    await expect(page.getByTestId("kite-toast")).not.toContainText("zzz_unknown");
  });
});
