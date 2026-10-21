/**
 * One-screen Copilot app (/v5/app) — the shared live-quote feed: the shell chip and the sector heatmap's 1D layer.
 *
 * MOCK — not real data: /api/live/stream, /api/live/quotes and /api/markets/sector-heatmap are answered by fixtures built
 * below (invented prices and weights). What this proves is the front end's handling of the feed: one connection, the chip's
 * four states, the polling fallback, and that live figures replace end-of-day ones ONLY while the feed is LIVE. It does not
 * prove the Kite feed itself; that is UNVERIFIED here (see test_reports/OVERRIDE_kite_live_feed.md).
 * Production build, every /api call route-mocked (pw.copilot-app.config.ts).
 */
import { test, expect, type Page } from "@playwright/test";
import { mockApi } from "../helpers/api-mock";

const HEATMAP = "/v5/app/tool/sector-heatmap";

// symbol, sector, weight %, close, 1D % (end of day)
const ROWS: Array<[string, string, number, number, number]> = [
  ["HDFCBANK", "Financial Services", 10, 1650, 1.0],
  ["ICICIBANK", "Financial Services", 6, 1210, 0.5],
  ["TCS", "Information Technology", 4, 3980, -2.0],
  ["INFY", "Information Technology", 5, 1620, -1.0],
];
const eodWeighted = ROWS.reduce((a, r) => a + r[2] * r[4], 0) / ROWS.reduce((a, r) => a + r[2], 0);

function heatmap() {
  const stocks = ROWS.map(([symbol, sector, weight, close, d]) => ({
    symbol, name: symbol, sector, close, weight_pct: weight, traded_value_cr: 100, returns: { d, w: 1, m: 2 },
    index_impact_pct: { d: (weight * d) / 100 }, rel_volume: 1,
  }));
  const sectors = [...new Set(ROWS.map((r) => r[1]))].map((name) => {
    const ss = stocks.filter((s) => s.sector === name);
    const w = ss.reduce((a, s) => a + s.weight_pct, 0);
    const ret = (k: "d" | "w" | "m") => ss.reduce((a, s) => a + s.weight_pct * s.returns[k], 0) / w;
    return { name, stocks: ss.length, weight_pct: w, returns: { d: ret("d"), w: ret("w"), m: ret("m") }, contribution_pct: { d: (w * ret("d")) / 100, w: 0, m: 0 }, breadth: { advances: 0, declines: 0, unchanged: 0, no_price: 0 } };
  });
  return {
    as_of: new Date().toISOString().slice(0, 10), index: "NIFTY50", source: "nidp.warehouse", sessions: { d: 1, w: 5, m: 21 }, mode: "end_of_day",
    weight_basis: "market_cap", weight_note: "", sectors, stocks, breadth: { advances: 2, declines: 2, unchanged: 0 },
    weighted_change: { d: eodWeighted, w: 1, m: 2 }, unavailable: [],
  };
}

// Live prices: TCS and INFY turn green, HDFCBANK red.
const LIVE: Record<string, number> = { HDFCBANK: -0.5, ICICIBANK: 0.5, TCS: 3.0, INFY: 1.0 };
const liveWeighted = ROWS.reduce((a, r) => a + r[2] * LIVE[r[0]], 0) / ROWS.reduce((a, r) => a + r[2], 0);

function payload(mode: string, quotes = true) {
  const q = Object.fromEntries(ROWS.map(([symbol, , , close]) => [symbol, {
    ltp: close * (1 + LIVE[symbol] / 100), change: 1, change_pct: LIVE[symbol], open: close, high: close, low: close, close, volume: 1000, oi: null, ts: "2026-10-21T11:13:09+05:30",
  }]));
  return {
    as_of: "2026-10-21T05:43:10+00:00", data_at: "2026-10-21T05:43:09+00:00", age_seconds: 1.2, stale: mode !== "live", stale_after_seconds: 15, mode,
    session: mode === "closed" ? "closed" : "open", source: "ws", final: mode === "closed", count: quotes ? 4 : 0, missing: [], quotes: quotes ? q : {}, read_only: true,
  };
}

type Feed = "sse" | "poll" | "down";
async function open(page: Page, feed: Feed, mode = "live", opts: { admin?: boolean; plain?: boolean } = {}) {
  const live: string[] = [];
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.addInitScript(() => localStorage.setItem("nivesh.copilot", JSON.stringify({ state: { mode: "trader", evidenceOpen: null }, version: 0 })));
  await mockApi(page, "populated");
  if (opts.plain) await page.route("**/api/auth/me", (route) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ user_id: "u_plain", email: "user@example.test", name: "Fixture User", is_admin: false, onboarding_completed: true }) }));
  if (opts.admin) {
    await page.route("**/api/auth/me", (route) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ user_id: "u_admin", email: "admin@example.test", name: "Admin Fixture", is_admin: true, onboarding_completed: true }) }));
  }
  await page.route("**/api/markets/sector-heatmap*", (route) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(heatmap()) }));
  await page.route("**/api/live/**", (route) => {
    const req = route.request();
    live.push(`${req.method()} ${new URL(req.url()).pathname}`);
    const path = new URL(req.url()).pathname;
    if (feed === "down") return route.fulfill({ status: 503, contentType: "application/json", body: JSON.stringify({ detail: "down" }) });
    if (path.endsWith("/stream")) {
      if (feed === "poll") return route.fulfill({ status: 500, contentType: "application/json", body: "{}" });
      return route.fulfill({ status: 200, contentType: "text/event-stream", body: `retry: 100\n\nevent: snapshot\ndata: ${JSON.stringify(payload(mode))}\n\n` });
    }
    return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(payload(mode)) });
  });
  if (opts.admin) await page.route("**/api/live/kite/login-url", (route) => {
    live.push(`${route.request().method()} /api/live/kite/login-url`);
    return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ login_url: "/v5/kite-login-stub?opened=1", expires_at: "2026-10-21T06:30:00+00:00" }) });
  });
  await page.goto(HEATMAP);
  return live;
}

const pct = (v: number) => `${v < 0 ? "−" : v > 0 ? "+" : ""}${Math.abs(v).toFixed(2)}%`;

test.describe("Live quotes in the Copilot app", () => {
  test("SSE: the chip says LIVE and the heatmap's 1D layer is recomputed from the live prices", async ({ page }) => {
    const calls = await open(page, "sse");
    await expect(page.getByTestId("live-chip")).toHaveAttribute("data-mode", "live");
    await expect(page.getByTestId("live-chip")).toContainText("Live · Kite");
    await expect(page.getByTestId("live-chip")).toHaveAttribute("data-transport", "sse");
    await expect(page.getByTestId("hm-weighted")).toHaveText(pct(liveWeighted));
    await expect(page.getByTestId("hm-trust-weighted")).toContainText("Live");
    await expect(page.getByTestId("hm-breadth-counts")).toContainText("3 advancing");     // HDFCBANK flipped to a decline
    expect(calls.every((c) => c.startsWith("GET "))).toBe(true);                            // read only
    expect(calls.filter((c) => c.endsWith("/stream")).length).toBeGreaterThan(0);
  });

  test("polling fallback: a stream that cannot be opened is replaced by GET /api/live/quotes", async ({ page }) => {
    const calls = await open(page, "poll");
    await expect(page.getByTestId("live-chip")).toHaveAttribute("data-mode", "live");
    await expect(page.getByTestId("live-chip")).toHaveAttribute("data-transport", "poll");
    await expect(page.getByTestId("hm-weighted")).toHaveText(pct(liveWeighted));
    expect(calls.some((c) => c.endsWith("/quotes"))).toBe(true);
  });

  test("market closed: the chip says so and the end-of-day figures are left alone", async ({ page }) => {
    await open(page, "sse", "closed");
    await expect(page.getByTestId("live-chip")).toHaveAttribute("data-mode", "closed");
    await expect(page.getByTestId("live-chip")).toContainText("Market closed");
    await expect(page.getByTestId("hm-weighted")).toHaveText(pct(eodWeighted));
    await expect(page.getByTestId("hm-trust-weighted")).not.toContainText(/\blive\b/i);
  });

  test("delayed feed: the chip says DELAYED and stale prices never replace end-of-day ones", async ({ page }) => {
    await open(page, "sse", "delayed");
    await expect(page.getByTestId("live-chip")).toHaveAttribute("data-mode", "delayed");
    await expect(page.getByTestId("live-chip")).toContainText("Delayed");
    await expect(page.getByTestId("hm-weighted")).toHaveText(pct(eodWeighted));
  });

  test("not connected: a failing feed shows NOT CONNECTED and the screens keep their end-of-day figures", async ({ page }) => {
    const errors: string[] = [];
    page.on("pageerror", (e) => errors.push(e.message));
    await open(page, "down");
    await expect(page.getByTestId("live-chip")).toHaveAttribute("data-mode", "not_connected", { timeout: 15000 });
    await expect(page.getByTestId("live-chip")).toContainText("Not connected");
    await expect(page.getByTestId("hm-weighted")).toHaveText(pct(eodWeighted));
    expect(errors).toEqual([]);
  });

  test("token expired: the feed's own state is named, not guessed", async ({ page }) => {
    await open(page, "sse", "expired");
    await expect(page.getByTestId("live-chip")).toHaveAttribute("data-mode", "expired");
    await expect(page.getByTestId("live-chip")).toContainText("Kite token expired");
  });

  test("expired token: an admin gets a Log in to Kite link that fetches a fresh login URL; a non-admin does not", async ({ page, browser }) => {
    const calls = await open(page, "sse", "expired", { admin: true });
    await expect(page.getByTestId("live-chip")).toHaveAttribute("data-mode", "expired");
    await expect(page.getByTestId("live-chip-login")).toHaveText("Log in to Kite");
    await page.route("**/kite-login-stub*", (route) => route.fulfill({ status: 200, contentType: "text/html", body: "<title>stub</title>" }));
    const nav = page.waitForRequest((r) => r.url().includes("/kite-login-stub?opened=1"));
    await page.getByTestId("live-chip-login").click();
    await nav;
    expect(calls).toContain("POST /api/live/kite/login-url");

    const plain = await browser.newPage();
    await open(plain, "sse", "expired", { plain: true });
    await expect(plain.getByTestId("live-chip")).toHaveAttribute("data-mode", "expired");
    await expect(plain.getByTestId("live-chip-login")).toHaveCount(0);
    await plain.close();
  });
});
