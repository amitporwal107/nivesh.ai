/**
 * One-screen Copilot app (/v5/app) — Smart trading desk: the Overview and
 * Market intelligence tabs.
 *
 * MOCK — not real data: every /api response here is an inline payload in the
 * shape the real route returns (the route is named beside each), with
 * synthetic values. Expected figures are worked out from the payload, not
 * copied from the screen. Mocked APIs, production build — see
 * pw.copilot-app.config.ts.
 *
 * Covers screens/tradingdesk/OverviewTab.tsx (+ overview-data.ts) and
 * IntelTab.tsx (+ intel-data.ts): index tiles and breadth from GET
 * /api/markets/home, the regime from GET /api/macro/today (and its
 * "uninitialised" answer), sector strength from GET
 * /api/positional/market-dashboard and its period label, a failed market
 * overview, the filings event list with its category chips and the selected
 * filing's read, the linked stock against the scanner, FII / DII sessions, an
 * empty and a failed feed, and a 390px pass on both tabs.
 */
import { test, expect, type Page, type Route } from "@playwright/test";
import { mockApi } from "../helpers/api-mock";

const APP = "/v5/app";
const DESK = `${APP}/trader/desk`;
const SLOW = { timeout: 15_000 };

const json = (route: Route, body: unknown, status = 200) =>
  route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });

// ── expected-value helpers (the screen's formats, written out) ──────────
const MINUS = "−";
const sgn = (n: number) => (n > 0 ? "+" : n < 0 ? MINUS : "");
const level = (n: number) => n.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const points = (n: number) => `${sgn(n)}${level(Math.abs(n))}`;
const pct = (n: number, d = 2) => `${sgn(n)}${Math.abs(n).toFixed(d)}%`;
const int = (n: number) => Math.round(n).toLocaleString("en-IN");
const crore = (n: number) => `${sgn(n)}₹${int(Math.abs(n))} Cr`;
const crPlain = (n: number) => `${sgn(n)}${int(Math.abs(n))}`;
const day = (iso: string, year = false) =>
  new Date(`${iso}T00:00:00Z`).toLocaleDateString("en-IN", { day: "numeric", month: "short", ...(year ? { year: "numeric" } : {}), timeZone: "UTC" });

// ── payloads ─────────────────────────────────────────────────────────────

// backend/routes/markets.py :: markets_home. "Nifty 500" and "Nifty Midcap 50" are in the tape but not on the desk.
const HOME = {
  ok: true, as_of: "2026-10-13", is_live: false, market_state: "closed", fetched_at: "2026-10-13T10:05:00+00:00",
  verdict: "CAUTIOUS", verdict_reason: "Fixture: weak breadth (41% above 20EMA) — wait for confirmation",
  indices: [
    { name: "Nifty 50", value: 25123.45, change: 120.5, change_pct: 0.48, is_vix: false, trend: null, spark: [24900, 24950.5, 25010, 25002.95, 25123.45] },
    { name: "Sensex", value: 82010.1, change: -150.25, change_pct: -0.18, is_vix: false, trend: null, spark: [82300, 82160.35, 82010.1] },
    { name: "Nifty Bank", value: 56000, change: 210, change_pct: 0.38, is_vix: false, trend: null, spark: [55600, 55790, 56000] },
    { name: "Nifty Midcap 50", value: 16000, change: 10, change_pct: 0.06, is_vix: false, trend: null, spark: [15990, 16000] },
    { name: "Nifty 500", value: 23000, change: 20, change_pct: 0.09, is_vix: false, trend: null, spark: [22980, 23000] },
    { name: "India VIX", value: 11.82, change: -0.31, change_pct: -2.56, is_vix: true, trend: "FALLING", spark: [12.4, 12.13, 11.82] },
  ],
  breadth: { advances: 2428, declines: 1142, unchanged: 72, universe: 3642, tone: "POSITIVE", pct_above_20ema: 41.0, pct_above_50ema: 47.2, new_52w_highs: 61, new_52w_lows: 22 },
  gainers: [], losers: [], movers_as_of: null, sectors: [],
  fii_dii: { as_of: "2026-10-13", fii_net_cr: -1523.4, dii_net_cr: 2210.75 },
  news: [],
  global_cues: [
    { name: "USD / INR", sub: "spot", value: 84.12, change_pct: 0.11, region: null, unit: null, featured: false },
    { name: "Brent Crude", sub: "$/bbl", value: 63.4, change_pct: -1.25, region: null, unit: null, featured: false },
  ],
  global_indices: { us: [], europe: [], asia: [] },
  commodities: [{ name: "Brent Crude", sub: null, value: 63.4, change_pct: -1.25, region: null, unit: "$/bbl", featured: false }],
};

// backend/services/macro_engine.py :: latest_state (via routes/macro.py :: macro_today).
const MACRO_BULL = {
  date: "2026-10-13", market_open_today: false, is_holiday_view: true, days_stale: 1, as_of_message: "Markets closed today — showing data as of 2026-10-13",
  market: "BULL", inflation: "STABLE", liquidity: "EASY", risk: "LOW", multiplier: 1.1,
  insight: "Fixture insight: the trend is intact and risk gauges are quiet.",
  interpretation: "Fixture interpretation.", strategy: {}, confidence: {}, risk_warning: null, composite_risk_score: 0.4, preopen_summary: null,
  values: { crude: 63.2, usd_inr: 84.1, nifty: 25003 }, features: {}, sources: {}, source_confidence: {},
};
// backend/routes/macro.py :: _uninitialised_payload — the route's answer when it has no state (never a 500).
const MACRO_UNINIT = {
  _uninitialised: true, _reason: "macro_state empty — backfill needed",
  market: "NEUTRAL", inflation: "STABLE", liquidity: "EASY", risk: "MEDIUM", multiplier: 1.0,
  insight: "Macro intelligence layer is initialising — daily ingestion runs at 18:35 IST.",
  values: {}, features: {}, sources: {}, confidence: {},
};

// backend/services/positional_engine/market_dashboard.py :: build — live overlay rows carry source "nse_live".
const sector = (name: string, ret: number, rs: number, extra: Record<string, unknown> = {}) =>
  ({ sector: name, ret_5d_pct: ret, rs_5d_pp: rs, tone: "COOL", stocks: 12, leader: null, ...extra });
const DASH = (rows: unknown[]) => ({
  ok: true, as_of_date: "2026-10-13", is_live: true, fetched_at: "2026-10-14T05:40:00+00:00",
  deploy_verdict: "NORMAL", verdict_reason: "Fixture", nifty: {}, vix: {}, breadth: {}, macro: { risk: "LOW", multiplier: 1.1 },
  sector_heatmap: rows,
});
const DASH_LIVE = DASH([
  sector("Metal", -0.85, -1.33, { tone: "COLD", source: "nse_live" }),
  sector("IT", 1.42, 0.94, { tone: "WARM", source: "nse_live", leader: { nse_symbol: "TESTIT", ret_5d_pct: 6.1, close: 1500 } }),
  sector("Bank", 0.3, -0.18, { source: "nse_live" }),
]);
const DASH_EOD = { ...DASH([sector("Capital Goods", 2.4, 1.9, { tone: "WARM" }), sector("Chemicals", -1.1, -1.6, { tone: "COLD" })]), is_live: false };

// backend/routes/positional.py (get_watchlist, get_picks): three setups; only TESTPICK carries a score.
const WATCHLIST = { as_of_date: "2026-10-13", buckets: {
  breakout_confirmed: [{ nse_symbol: "TESTBRK", sector: "Capital Goods", close_price: 510.0, trigger_price: 500.0, stop_price: 477.5, atr_pct: 2.94, why: "Fixture reason" }],
  pre_breakout: [{ nse_symbol: "TESTPRE", sector: "Chemicals", close_price: 98.0, trigger_price: 100.0, stop_price: 93.0, atr_pct: 3.1, why: "Fixture coil" }],
  true_accumulation: [], trend_continuation: [] } };
const PICKS = { signal_date: "2026-10-13", count: 1, picks: [{ nse_symbol: "TESTPICK", signal_date: "2026-10-13", final_score: 0.812, confidence: "HIGH", stage: "BREAKOUT", timeframe_days_min: 5, timeframe_days_max: 15, entry_price: 505.0, stoploss: 480.0, target_price: 555.0, risk_reward: 2.0, source_scans: ["btst.breakout_confirmation"], reasons: ["Fixture scanner reason"] }] };

// backend/routes/filings.py :: _row (feed rows) and filings_feed (total, facets).
const row = (id: string, o: Record<string, unknown>) => ({
  id, ticker: null, code: null, name: null, date: "2026-10-12T10:00:00+05:30", category: "Other", impact: null, sentiment: null,
  docLabel: "Fixture filing", url: null, one: null, period: null, metric: null, hasInsights: false, ...o,
});
const R_EARN = row("ann-001", {
  ticker: "TESTPICK", code: "TESTPICK", name: "Test Pick Industries Ltd", date: "2026-10-13T09:12:00+05:30", category: "Earnings", impact: "high",
  sentiment: "positive", docLabel: "Financial results for the quarter ended September 2026", url: "https://nsearchives.nseindia.com/corporate/fixture-001.pdf",
  one: "Fixture read: revenue grew on new orders.", period: "Q2 FY27", metric: "Revenue: 1,234 Cr", hasInsights: true,
});
const R_ORDER = row("ann-002", {
  ticker: "TESTORD", code: "TESTORD", name: "Test Orders Ltd", date: "2026-10-12T15:40:00+05:30", category: "Orders", impact: "medium",
  sentiment: "neutral", docLabel: "Bagging of an order", url: "https://www.bseindia.com/xml-data/fixture-002.pdf",
});
const R_LIT = row("ann-003", {
  ticker: "TESTLIT", code: "TESTLIT", name: "Test Litigation Ltd", date: "2026-10-11T11:00:00+05:30", category: "Litigation", impact: "high",
  sentiment: "negative", docLabel: "Disclosure of a tax demand", url: "https://nsearchives.nseindia.com/corporate/fixture-003.pdf",
  one: "Fixture read: a tax demand was raised.", hasInsights: true,
});
const R_MNA = row("ann-010", {
  ticker: "TESTMNA", code: "TESTMNA", name: "Test Mergers Ltd", date: "2026-10-10T12:00:00+05:30", category: "Mna", impact: "high",
  sentiment: "positive", docLabel: "Acquisition of a subsidiary",
});
const FACETS = { earnings: 21, orders: 9, mna: 2, capex: 4, management: 6, dividend: 3, buyback: 1, qip: 0, rating: 2, litigation: 1 };
const feed = (rows: unknown[], total = rows.length) => ({ ok: true, total, facets: FACETS, rows });
const FEEDS: Record<string, unknown> = {
  "": feed([R_EARN, R_ORDER, R_LIT], 57),
  earnings: feed([R_EARN], 21),
  orders: feed([R_ORDER], 9),
  mna: feed([R_MNA], 2),
};

// backend/routes/filings.py :: filing_insight_detail.
const insight = (id: string, one: string) => ({
  ok: true, id, one, period: null, metric: null, metricRaw: null, sentiment: "positive", confidence: 0.82, docType: "financial_results",
  docLabel: "Financial Results", model: "fixture", generatedAt: "2026-10-13T10:00:00+00:00",
  tabs: [{ key: "quick_summary", label: "Quick Summary" }],
  sections: [{ tab: "Quick Summary", h: "What changed", items: [`Fixture item for ${id}.`], cite: "pp. 2-3", cite_url: null }],
  sourceUrl: null, grounded: true, disclaimer: "AI-generated summary · refer to the source document for complete detail.",
});

// backend/routes/markets.py :: markets_fii_dii (DaaS series, newest first). Twelve sessions; the desk lists ten.
const FLOW_DAYS = ["2026-10-13", "2026-10-10", "2026-10-09", "2026-10-08", "2026-10-07", "2026-10-06", "2026-10-03", "2026-10-01", "2026-09-30", "2026-09-29", "2026-09-26", "2026-09-25"];
const FLOWS = {
  ok: true, as_of: "2026-10-13", monthly: [],
  daily: FLOW_DAYS.map((date, i) => {
    const fii = (i % 2 ? 1 : -1) * (1000 + i * 111.4);
    const dii = (i % 3 ? 1 : -1) * (800 + i * 57.6);
    return { date, fii_buy: 10000, fii_sell: 10000 - fii, fii_net: fii, dii_buy: 9000, dii_sell: 9000 - dii, dii_net: dii };
  }),
};

interface Calls { feed: URL[]; insights: string[]; home: number }

/** Everything the desk header, the docked Copilot and these two tabs read. */
async function deskApi(page: Page, over: { home?: { status: number; body: unknown }; macro?: unknown; dash?: unknown; feed?: { status: number; body: unknown } } = {}): Promise<Calls> {
  const calls: Calls = { feed: [], insights: [], home: 0 };
  await mockApi(page, "populated");
  await page.route("**/api/chat/sessions", (route) => json(route, []));
  await page.route("**/api/positional/watchlist*", (route) => json(route, WATCHLIST));
  await page.route("**/api/positional/picks*", (route) => json(route, PICKS));
  // backend/routes/move_odds.py: an account not on the move_odds allowlist.
  await page.route("**/api/move-odds/**", (route) => json(route, { detail: "feature_not_enabled" }, 403));
  await page.route("**/api/markets/home", (route) => {
    calls.home += 1;
    return over.home ? json(route, over.home.body, over.home.status) : json(route, HOME);
  });
  await page.route("**/api/macro/today", (route) => json(route, over.macro ?? MACRO_BULL));
  await page.route("**/api/positional/market-dashboard", (route) => json(route, over.dash ?? DASH_LIVE));
  await page.route("**/api/filings/feed*", (route) => {
    const u = new URL(route.request().url());
    calls.feed.push(u);
    if (over.feed) return json(route, over.feed.body, over.feed.status);
    return json(route, FEEDS[u.searchParams.get("category") ?? ""] ?? feed([], 0));
  });
  await page.route("**/api/filings/*/insights", (route) => {
    const id = decodeURIComponent(new URL(route.request().url()).pathname.split("/").slice(-2)[0]);
    calls.insights.push(id);
    const r = [R_EARN, R_LIT].find((x) => x.id === id);
    return r ? json(route, insight(id, String(r.one))) : json(route, { ok: false, reason: "no_insight_yet" }, 404);
  });
  await page.route("**/api/markets/fii-dii*", (route) => json(route, FLOWS));
  return calls;
}

/** Captures what an "Ask" chip hands to the Copilot (a normal thread below the dock width). */
async function mockAsk(page: Page): Promise<string[]> {
  const sent: string[] = [];
  await page.route("**/api/chat/sessions", (route) =>
    route.request().method() === "POST" ? json(route, { session_id: "asked1" }) : json(route, []));
  await page.route("**/api/chat/messages*", (route) => json(route, []));
  await page.route("**/api/chat/stream", (route) => {
    sent.push((route.request().postDataJSON() as { message: string }).message);
    return route.fulfill({ status: 200, contentType: "text/event-stream", body: `data: ${JSON.stringify({ type: "done", content: "ok" })}\n\n` });
  });
  return sent;
}

async function overflow(page: Page) {
  return page.evaluate(() => {
    const sc = document.querySelector('[data-testid="copilot-scroll"]') as HTMLElement | null;
    return { doc: document.documentElement.scrollWidth - window.innerWidth, scroll: sc ? sc.scrollWidth - sc.clientWidth : 0 };
  });
}

// ── Overview ─────────────────────────────────────────────────────────────

test.describe("Smart trading desk — Overview", () => {
  test("TC-8: the four index tiles equal the /home payload, VIX included, each with its daily-close line", async ({ page }) => {
    await deskApi(page);
    await page.goto(`${DESK}?tab=overview`);
    const tiles = page.getByTestId("desk-index-tile");
    await expect(tiles).toHaveCount(4);
    // The desk's four, by the names the route sends; Nifty 500 / Midcap 50 are not shown.
    for (const name of ["Nifty 50", "Nifty Bank", "Sensex", "India VIX"]) {
      const ix = HOME.indices.find((i) => i.name === name)!;
      const tile = page.locator(`[data-testid="desk-index-tile"][data-index="${name}"]`);
      await expect(tile.getByTestId("desk-index-value")).toHaveText(level(ix.value));
      await expect(tile.getByTestId("desk-index-change")).toHaveText(`${points(ix.change)} (${pct(ix.change_pct)})`);
      await expect(tile.getByTestId("desk-index-spark")).toHaveCount(1);
    }
    await expect(page.locator('[data-testid="desk-index-tile"][data-index="Nifty 500"]')).toHaveCount(0);
    // Longest spark is five sessions; the source line says they are daily closes.
    await expect(page.getByTestId("desk-index-source")).toContainText("each line is the last 5 daily closes");
    await expect(page.getByTestId("desk-index-source")).toContainText("delayed");
  });

  test("TC-9: breadth counts and the advancing share are worked out from the payload, with the universe named", async ({ page }) => {
    await deskApi(page);
    await page.goto(`${DESK}?tab=overview`);
    const b = HOME.breadth;
    const share = (b.advances / (b.advances + b.declines + b.unchanged)) * 100; // 2428 / 3642 = 66.67
    await expect(page.getByTestId("desk-breadth-pct")).toHaveText(`${share.toFixed(1)}%`);
    await expect(page.getByTestId("desk-breadth-counts")).toHaveText(`${int(b.advances)} advances · ${int(b.declines)} declines · ${int(b.unchanged)} unchanged`);
    await expect(page.getByTestId("desk-breadth-scope")).toHaveText(`Across ${int(b.universe)} NSE stocks · end of day ${day(HOME.as_of, true)}`);
    await expect(page.getByTestId("desk-breadth-bar")).toHaveAttribute("aria-label", `${int(b.advances)} advances, ${int(b.unchanged)} unchanged, ${int(b.declines)} declines`);

    // The route's fallback: a live count over the Nifty 50 constituents.
    const live = { advances: 31, declines: 17, unchanged: 2, universe: 50, tone: "POSITIVE" };
    await page.route("**/api/markets/home", (route) => json(route, { ...HOME, breadth: live }));
    await page.reload();
    await expect(page.getByTestId("desk-breadth-pct")).toHaveText(`${((31 / 50) * 100).toFixed(1)}%`);
    await expect(page.getByTestId("desk-breadth-scope")).toHaveText("Across the 50 Nifty 50 stocks · delayed quotes");
  });

  test("TC-10: regime BULL reads Bullish with its definition; flows, rupee, crude and the rules-based read come from the backend", async ({ page }) => {
    await deskApi(page);
    await page.goto(`${DESK}?tab=overview`);
    const regime = page.getByTestId("desk-regime");
    await expect(regime).toHaveAttribute("data-regime", "BULL");
    await expect(page.getByTestId("desk-regime-label")).toHaveText("Bullish");
    await expect(page.getByTestId("desk-regime-meaning")).toContainText("closed above its 50-day average");
    await expect(page.locator('[data-testid="desk-regime-segment"][data-on="true"]')).toHaveCount(1);
    await expect(page.getByTestId("desk-regime-segment").nth(2)).toHaveAttribute("data-on", "true");

    await expect(page.getByTestId("desk-mini-fii-value")).toHaveText(crore(HOME.fii_dii.fii_net_cr));
    await expect(page.getByTestId("desk-mini-dii-value")).toHaveText(crore(HOME.fii_dii.dii_net_cr));
    await expect(page.getByTestId("desk-mini-fii-sub")).toHaveText(`Net · ${day(HOME.fii_dii.as_of)}`);
    await expect(page.getByTestId("desk-mini-usdinr-value")).toHaveText(level(84.12));
    await expect(page.getByTestId("desk-mini-usdinr-sub")).toHaveText(`Spot · ${pct(0.11)}`);
    await expect(page.getByTestId("desk-mini-brent-value")).toHaveText(`$${level(63.4)}`);
    await expect(page.getByTestId("desk-mini-brent-sub")).toHaveText(`$/bbl · ${pct(-1.25)}`);

    const read = page.getByTestId("desk-insight");
    await expect(read).toContainText("Rules-based read");
    await expect(read).not.toContainText("AI");
    await expect(page.getByTestId("desk-insight-macro")).toHaveText(MACRO_BULL.insight);
    await expect(page.getByTestId("desk-verdict-label")).toHaveText("cautious");
    await expect(page.getByTestId("desk-verdict-reason")).toHaveText(HOME.verdict_reason);
  });

  test("TC-10: the macro route's uninitialised answer shows an honest not-available state, not a Neutral regime", async ({ page }) => {
    await deskApi(page, { macro: MACRO_UNINIT });
    await page.goto(`${DESK}?tab=overview`);
    await expect(page.getByTestId("desk-regime")).toHaveAttribute("data-regime", "unavailable");
    await expect(page.getByTestId("desk-regime-label")).toHaveText("Not available");
    await expect(page.getByTestId("desk-regime-unavailable")).toContainText("has not produced a regime yet");
    // The fixture user is an admin: the route's reason is shown to admins.
    await expect(page.getByTestId("desk-regime-unavailable")).toContainText(MACRO_UNINIT._reason);
    await expect(page.locator('[data-testid="desk-regime-segment"][data-on="true"]')).toHaveCount(0);
    // The placeholder insight is not presented as a read; the /home verdict still is.
    await expect(page.getByTestId("desk-insight")).not.toContainText("initialising");
    await expect(page.getByTestId("desk-verdict-reason")).toHaveText(HOME.verdict_reason);
  });

  test("TC-11: sector strength says Today for live sector-index rows and 5 days for end-of-day rows", async ({ page }) => {
    await deskApi(page);
    await page.goto(`${DESK}?tab=overview`);
    await expect(page.getByTestId("desk-sector-period")).toHaveText("Today · sector indices");
    const tiles = page.getByTestId("desk-sector-tile");
    // Strongest first: IT +1.42, Bank +0.30, Metal −0.85.
    await expect(tiles).toHaveCount(3);
    await expect(tiles.nth(0)).toHaveAttribute("data-sector", "IT");
    await expect(tiles.nth(0).getByTestId("desk-sector-pct")).toHaveText(pct(1.42));
    await expect(tiles.nth(2)).toHaveAttribute("data-sector", "Metal");
    await expect(tiles.nth(2).getByTestId("desk-sector-pct")).toHaveText(pct(-0.85));
    // Tint by sign.
    expect(await tiles.nth(0).getAttribute("style")).toContain("var(--mint)");
    expect(await tiles.nth(2).getAttribute("style")).toContain("var(--cp-danger)");
    // No toggle is faked: the missing periods say they are not connected.
    await expect(page.getByTestId("desk-sector-periods-gap")).toContainText("Not connected yet");

    // The leader opens its chart.
    await tiles.nth(0).getByTestId("desk-sector-leader").click();
    await expect(page).toHaveURL(/[?&]tab=chart/);
    await expect(page).toHaveURL(/[?&]sym=TESTIT/);

    await page.route("**/api/positional/market-dashboard", (route) => json(route, DASH_EOD));
    await page.goto(`${DESK}?tab=overview`);
    await expect(page.getByTestId("desk-sector-period")).toHaveText("5 days · end of day");
    await expect(page.getByTestId("desk-sector-tile")).toHaveCount(2);
    await expect(page.getByTestId("desk-sector-source")).toContainText("Mean 5-session return");
  });

  test("TC-12: a failed market overview shows an error with retry while the regime and sectors still render", async ({ page }) => {
    const calls = await deskApi(page, { home: { status: 500, body: { detail: "fixture failure" } } });
    await page.goto(`${DESK}?tab=overview`);
    const problem = page.getByTestId("desk-index-error");
    await expect(problem.getByRole("alert")).toBeVisible(SLOW);
    await expect(page.getByTestId("desk-index-tile")).toHaveCount(0);
    await expect(page.getByTestId("desk-regime-label")).toHaveText("Bullish");
    await expect(page.getByTestId("desk-sector-tile")).toHaveCount(3);
    await expect(page.getByTestId("desk-flows-unavailable")).toBeVisible();
    const before = calls.home;
    await problem.getByRole("button", { name: /Retry/ }).click();
    await expect.poll(() => calls.home).toBeGreaterThan(before);
  });

  test("an Ask chip hands its question to the Copilot", async ({ page }) => {
    await deskApi(page);
    const sent = await mockAsk(page);
    await page.goto(`${DESK}?tab=overview`);
    await page.getByTestId("desk-overview-ask").filter({ hasText: "Which sectors are leading today and why?" }).click();
    await expect.poll(() => sent).toContain("Which sectors are leading today and why?");
  });
});

// ── Market intelligence ─────────────────────────────────────────────────

test.describe("Smart trading desk — Market intelligence", () => {
  test("TC-24: feed rows with sentiment; a chip sets the category query; selecting a row reads its insight", async ({ page }) => {
    const calls = await deskApi(page);
    await page.goto(`${DESK}?tab=intel`);
    const rows = page.getByTestId("desk-event-row");
    await expect(rows).toHaveCount(3);
    // The default request: no category (the route's own mix), the last 7 days, material first.
    const first = calls.feed[0];
    expect(first.searchParams.get("category")).toBeNull();
    expect(first.searchParams.get("days")).toBe("7");
    expect(first.searchParams.get("sort")).toBe("material");

    await expect(rows.nth(0).getByTestId("desk-event-type")).toHaveText("Results");
    await expect(rows.nth(0).getByTestId("desk-event-title")).toHaveText(R_EARN.docLabel as string);
    await expect(rows.nth(0).getByTestId("desk-event-sentiment")).toHaveText("Positive");
    await expect(rows.nth(1).getByTestId("desk-event-sentiment")).toHaveText("Neutral");
    await expect(rows.nth(2).getByTestId("desk-event-sentiment")).toHaveText("Negative");
    await expect(rows.nth(0).locator('[data-testid="entity-icon"]')).toHaveAttribute("data-key", "TESTPICK");

    // Chip counts from the facets: Results = earnings 21; Orders & deals = orders 9 + mna 2; Corporate = 4+6+3+1+0+2+1.
    await expect(page.getByTestId("desk-intel-chip-results")).toContainText("21");
    await expect(page.getByTestId("desk-intel-chip-orders")).toContainText("11");
    await expect(page.getByTestId("desk-intel-chip-corporate")).toContainText("17");

    // The first row is selected and has a generated read: its insight is requested and shown.
    const detail = page.getByTestId("desk-event-detail");
    await expect(detail).toHaveAttribute("data-id", "ann-001");
    await expect(detail.getByTestId("filing-insight-one")).toHaveText(R_EARN.one as string);
    expect(calls.insights).toContain("ann-001");
    await expect(detail.getByTestId("desk-event-doc")).toHaveAttribute("href", R_EARN.url as string);
    await expect(detail.getByTestId("desk-event-sources")).toContainText("Filed with NSE");

    // Selecting another row with a read requests that filing's insight.
    await rows.nth(2).click();
    await expect(rows.nth(2)).toHaveAttribute("aria-pressed", "true");
    await expect(detail).toHaveAttribute("data-id", "ann-003");
    await expect(detail.getByTestId("filing-insight-one")).toHaveText(R_LIT.one as string);
    expect(calls.insights).toContain("ann-003");

    // A row without a read says so and asks for nothing.
    await rows.nth(1).click();
    await expect(detail).toHaveAttribute("data-id", "ann-002");
    await expect(detail.getByTestId("desk-event-noread")).toBeVisible();
    await expect(detail.getByTestId("desk-event-sources")).toContainText("Filed with BSE");
    expect(calls.insights).not.toContain("ann-002");

    // Results → category=earnings.
    await page.getByTestId("desk-intel-chip-results").click();
    await expect(page.getByTestId("desk-intel-chip-results")).toHaveAttribute("aria-pressed", "true");
    await expect.poll(() => calls.feed.map((u) => u.searchParams.get("category"))).toContain("earnings");
    await expect(rows).toHaveCount(1);
    await expect(rows.nth(0)).toHaveAttribute("data-id", "ann-001");

    // Orders & deals → one request per category (orders, mna), merged high impact first.
    await page.getByTestId("desk-intel-chip-orders").click();
    await expect.poll(() => calls.feed.map((u) => u.searchParams.get("category"))).toEqual(expect.arrayContaining(["orders", "mna"]));
    await expect(rows).toHaveCount(2);
    await expect(rows.nth(0)).toHaveAttribute("data-id", "ann-010");
    await expect(rows.nth(0).getByTestId("desk-event-type")).toHaveText("M&A");
    await expect(rows.nth(1)).toHaveAttribute("data-id", "ann-002");
    await expect(page.getByTestId("desk-intel-deals-gap")).toContainText("Not connected yet");

    // Regulatory is asked for by name (the default feed leaves it out); SEBI circulars are not connected.
    await page.getByTestId("desk-intel-chip-regulatory").click();
    await expect.poll(() => calls.feed.map((u) => u.searchParams.get("category"))).toContain("regulatory");
    await expect(page.getByTestId("desk-intel-sebi-gap")).toContainText("SEBI circulars");

    // Latest-first ordering is a query parameter too.
    await page.getByTestId("desk-intel-chip-all").click();
    await page.getByTestId("desk-intel-sort-latest").click();
    await expect.poll(() => calls.feed.some((u) => u.searchParams.get("sort") === "latest" && !u.searchParams.get("category"))).toBe(true);
  });

  test("TC-25: a linked stock in today's scanner shows its rank and opens its chart", async ({ page }) => {
    await deskApi(page);
    await page.goto(`${DESK}?tab=intel`);
    const detail = page.getByTestId("desk-event-detail");
    // Merged setups: TESTBRK, TESTPRE (watchlist) and TESTPICK (picks) = 3; only TESTPICK has a score, so it ranks first.
    await expect(detail.getByTestId("desk-event-scanner")).toContainText("In today’s scanner · #1 of 3");
    await expect(detail.getByTestId("desk-event-linked").locator('[data-testid="entity-icon"]')).toHaveAttribute("data-key", "TESTPICK");

    await page.getByTestId("desk-event-row").nth(1).click();
    await expect(detail.getByTestId("desk-event-not-scanner")).toBeVisible();

    await page.getByTestId("desk-event-row").nth(0).click();
    await detail.getByTestId("desk-event-linked").click();
    await expect(page.getByTestId("screen-trading-desk")).toHaveAttribute("data-tab", "chart");
    await expect(page).toHaveURL(/[?&]tab=chart/);
    await expect(page).toHaveURL(/[?&]sym=TESTPICK/);
  });

  test("TC-26: the FII / DII chip lists the latest ten sessions from /markets/fii-dii", async ({ page }) => {
    await deskApi(page);
    await page.goto(`${DESK}?tab=intel`);
    await page.getByTestId("desk-intel-chip-flows").click();
    const block = page.getByTestId("desk-flows");
    await expect(block.getByTestId("desk-flow-date")).toHaveCount(10);
    const [d0, d9] = [FLOWS.daily[0], FLOWS.daily[9]];
    await expect(block.getByTestId("desk-flow-date").nth(0)).toHaveText(day(d0.date, true));
    await expect(block.getByTestId("desk-flow-fii").nth(0)).toHaveText(crPlain(d0.fii_net));
    await expect(block.getByTestId("desk-flow-dii").nth(0)).toHaveText(crPlain(d0.dii_net));
    await expect(block.getByTestId("desk-flow-date").nth(9)).toHaveText(day(d9.date, true));
    await expect(block.getByTestId("desk-flow-fii").nth(9)).toHaveText(crPlain(d9.fii_net));
    // Coloured by sign: the first session's FII figure is a net sale.
    expect(await block.getByTestId("desk-flow-fii").nth(0).getAttribute("style")).toContain("var(--cp-danger)");
    await expect(page.getByTestId("desk-flows-source")).toContainText("Source: NSE");
    await expect(page.getByTestId("desk-event-row")).toHaveCount(0);
  });

  test("TC-27: an empty feed shows an empty state", async ({ page }) => {
    await deskApi(page, { feed: { status: 200, body: { ok: true, total: 0, facets: {}, rows: [] } } });
    await page.goto(`${DESK}?tab=intel`);
    await expect(page.getByTestId("desk-intel-empty")).toContainText("No filings here yet");
    await expect(page.getByTestId("desk-event-row")).toHaveCount(0);
  });

  test("TC-27: a failed feed shows an error with retry", async ({ page }) => {
    const calls = await deskApi(page, { feed: { status: 500, body: { detail: "fixture failure" } } });
    await page.goto(`${DESK}?tab=intel`);
    const problem = page.getByTestId("desk-intel-error");
    await expect(problem.getByRole("alert")).toContainText("Filings didn’t load", SLOW);
    const before = calls.feed.length;
    await problem.getByRole("button", { name: /Retry/ }).click();
    await expect.poll(() => calls.feed.length).toBeGreaterThan(before);
  });
});

// ── 390px ───────────────────────────────────────────────────────────────

test.describe("Smart trading desk — Overview and Market intelligence at 390px", () => {
  test("TC-7: no sideways scroll on either tab", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await deskApi(page);
    await page.goto(`${DESK}?tab=overview`);
    await expect(page.getByTestId("desk-index-tile")).toHaveCount(4);
    await expect(page.getByTestId("desk-sector-tile")).toHaveCount(3);
    await expect(page.getByTestId("desk-regime-label")).toHaveText("Bullish");
    let o = await overflow(page);
    expect(o.doc).toBeLessThanOrEqual(1);
    expect(o.scroll).toBeLessThanOrEqual(1);

    await page.goto(`${DESK}?tab=intel`);
    await expect(page.getByTestId("desk-event-row")).toHaveCount(3);
    await page.getByTestId("desk-event-row").nth(2).click();
    await expect(page.getByTestId("desk-event-detail")).toHaveAttribute("data-id", "ann-003");
    o = await overflow(page);
    expect(o.doc).toBeLessThanOrEqual(1);
    expect(o.scroll).toBeLessThanOrEqual(1);

    await page.getByTestId("desk-intel-chip-flows").click();
    await expect(page.getByTestId("desk-flow-date")).toHaveCount(10);
    o = await overflow(page);
    expect(o.doc).toBeLessThanOrEqual(1);
    expect(o.scroll).toBeLessThanOrEqual(1);
  });
});
