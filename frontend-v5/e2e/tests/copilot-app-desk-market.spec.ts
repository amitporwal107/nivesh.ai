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
 * IntelTab.tsx (+ intel-data.ts): index tiles and breadth (with the universe
 * the route names in breadth.universe_kind) from GET /api/markets/home, the
 * regime from GET /api/macro/today (and its "uninitialised" answer), sector
 * strength from GET /api/markets/sector-returns with its 1D / 1W / 1M toggle
 * and the 5-session leaders from GET /api/positional/market-dashboard, a failed
 * market overview, the filings event list with its category chips, the row's
 * exchange and the selected filing's read, bulk and block deals from GET
 * /api/markets/deals, SEBI circulars from GET /api/markets/circulars, the
 * linked stock against the scanner, FII / DII sessions, empty / failed / 403
 * states, and a 390px pass on both tabs.
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
  breadth: { advances: 2428, declines: 1142, unchanged: 72, universe: 3642, universe_kind: "bhavcopy", tone: "POSITIVE", pct_above_20ema: 41.0, pct_above_50ema: 47.2, new_52w_highs: 61, new_52w_lows: 22 },
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
// Only the leaders are read from it now. "IT" matches the Nifty IT row by sector; "Bank" matches Nifty Bank by its
// index name, and must not lend its leader to Nifty PSU Bank; "Chemicals" has no sector-index row.
const DASH_LIVE = DASH([
  sector("Metal", -0.85, -1.33, { tone: "COLD", source: "nse_live" }),
  sector("IT", 1.42, 0.94, { tone: "WARM", source: "nse_live", leader: { nse_symbol: "TESTIT", ret_5d_pct: 6.1, close: 1500 } }),
  sector("Bank", 0.3, -0.18, { source: "nse_live", leader: { nse_symbol: "TESTBANK", ret_5d_pct: 3.25, close: 800 } }),
  sector("Chemicals", -1.1, -1.6, { tone: "COLD", leader: { nse_symbol: "TESTCHEM", ret_5d_pct: 1.0, close: 90 } }),
]);

// backend/nidp/services/daas_api/routers/desk_market.py :: sector_returns, via backend/routes/markets_desk.py.
// Nifty Realty's own latest close is a session older than the response's as-of; Nifty Metal has no 1-month history.
const SECTOR_RETURNS = {
  as_of: "2026-10-13", source: "NSE index close (nidp.index_eod)", sessions: { "1d": 1, "1w": 5, "1m": 21 },
  sectors: [
    { index: "Nifty Bank", sector: "Banks", date: "2026-10-13", close: 56000.0, ret_1d_pct: 0.3, ret_1w_pct: 1.9, ret_1m_pct: -2.2 },
    { index: "Nifty IT", sector: "IT", date: "2026-10-13", close: 35210.5, ret_1d_pct: 1.42, ret_1w_pct: -0.8, ret_1m_pct: 3.1 },
    { index: "Nifty Metal", sector: "Metals", date: "2026-10-13", close: 9100.25, ret_1d_pct: -0.85, ret_1w_pct: 2.6, ret_1m_pct: null },
    { index: "Nifty PSU Bank", sector: "PSU Banks", date: "2026-10-13", close: 7010.0, ret_1d_pct: 0.95, ret_1w_pct: -1.4, ret_1m_pct: 0.5 },
    { index: "Nifty Realty", sector: "Realty", date: "2026-10-10", close: 980.4, ret_1d_pct: -1.6, ret_1w_pct: -3.05, ret_1m_pct: 4.4 },
  ],
};
type SectorRow = (typeof SECTOR_RETURNS.sectors)[number];
const PERIOD_KEY = { "1d": "ret_1d_pct", "1w": "ret_1w_pct", "1m": "ret_1m_pct" } as const;
/** The tiles' order for a period: highest return first, missing last. */
const sectorOrder = (period: keyof typeof PERIOD_KEY) =>
  [...SECTOR_RETURNS.sectors].sort((a, b) => ((b[PERIOD_KEY[period]] as number | null) ?? -Infinity) - ((a[PERIOD_KEY[period]] as number | null) ?? -Infinity));
const pctOrDash = (v: number | null) => (v == null ? "—" : pct(v));

// backend/routes/positional.py (get_watchlist, get_picks): three setups; only TESTPICK carries a score.
const WATCHLIST = { as_of_date: "2026-10-13", buckets: {
  breakout_confirmed: [{ nse_symbol: "TESTBRK", sector: "Capital Goods", close_price: 510.0, trigger_price: 500.0, stop_price: 477.5, atr_pct: 2.94, why: "Fixture reason" }],
  pre_breakout: [{ nse_symbol: "TESTPRE", sector: "Chemicals", close_price: 98.0, trigger_price: 100.0, stop_price: 93.0, atr_pct: 3.1, why: "Fixture coil" }],
  true_accumulation: [], trend_continuation: [] } };
const PICKS = { signal_date: "2026-10-13", count: 1, picks: [{ nse_symbol: "TESTPICK", signal_date: "2026-10-13", final_score: 0.812, confidence: "HIGH", stage: "BREAKOUT", timeframe_days_min: 5, timeframe_days_max: 15, entry_price: 505.0, stoploss: 480.0, target_price: 555.0, risk_reward: 2.0, source_scans: ["btst.breakout_confirmation"], reasons: ["Fixture scanner reason"] }] };

// backend/routes/filings.py :: _row (feed rows, with `exchange` from the stored source) and filings_feed (total, facets).
const row = (id: string, o: Record<string, unknown>) => ({
  id, ticker: null, code: null, name: null, date: "2026-10-12T10:00:00+05:30", category: "Other", impact: null, sentiment: null,
  docLabel: "Fixture filing", url: null, one: null, period: null, metric: null, hasInsights: false, exchange: null, ...o,
});
const R_EARN = row("ann-001", {
  ticker: "TESTPICK", code: "TESTPICK", name: "Test Pick Industries Ltd", date: "2026-10-13T09:12:00+05:30", category: "Earnings", impact: "high",
  sentiment: "positive", docLabel: "Financial results for the quarter ended September 2026", url: "https://nsearchives.nseindia.com/corporate/fixture-001.pdf",
  one: "Fixture read: revenue grew on new orders.", period: "Q2 FY27", metric: "Revenue: 1,234 Cr", hasInsights: true, exchange: "NSE",
});
// No `exchange` on this row: the detail falls back to the document link's host (bseindia.com).
const R_ORDER = row("ann-002", {
  ticker: "TESTORD", code: "TESTORD", name: "Test Orders Ltd", date: "2026-10-12T15:40:00+05:30", category: "Orders", impact: "medium",
  sentiment: "neutral", docLabel: "Bagging of an order", url: "https://www.bseindia.com/xml-data/fixture-002.pdf", exchange: null,
});
const R_LIT = row("ann-003", {
  ticker: "TESTLIT", code: "TESTLIT", name: "Test Litigation Ltd", date: "2026-10-11T11:00:00+05:30", category: "Litigation", impact: "high",
  sentiment: "negative", docLabel: "Disclosure of a tax demand", url: "https://nsearchives.nseindia.com/corporate/fixture-003.pdf",
  one: "Fixture read: a tax demand was raised.", hasInsights: true,
});
// No document link at all: the exchange comes from the row alone.
const R_MNA = row("ann-010", {
  ticker: "TESTMNA", code: "TESTMNA", name: "Test Mergers Ltd", date: "2026-10-10T12:00:00+05:30", category: "Mna", impact: "high",
  sentiment: "positive", docLabel: "Acquisition of a subsidiary", exchange: "BSE",
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

// backend/nidp/services/daas_api/routers/desk_market.py :: deals, via backend/routes/markets_desk.py. value_cr = quantity ×
// avg_price ÷ 1e7, to 2 decimals; newest day first, largest value first within a day.
const DEALS = {
  as_of: "2026-10-13", from: "2026-10-09", days: 5, kind: "all", symbol: null,
  source: "NSE bulk and block deals (nidp.bulk_deals, nidp.block_deals)", count: 3, total: 3,
  rows: [
    { date: "2026-10-13", kind: "block", symbol: "TESTPICK", client_name: "FIXTURE CAPITAL LLP", side: "SELL", quantity: 250000, avg_price: 1210.25, value_cr: 30.26 },
    { date: "2026-10-13", kind: "bulk", symbol: "TESTORD", client_name: "FIXTURE FUND A", side: "BUY", quantity: 120000, avg_price: 410.5, value_cr: 4.93 },
    { date: "2026-10-10", kind: "bulk", symbol: "TESTLIT", client_name: "FIXTURE TRADER", side: "BUY", quantity: 85000, avg_price: 98.4, value_cr: 0.84 },
  ],
};

// backend/nidp/services/daas_api/routers/circulars.py :: sebi, via backend/routes/circulars.py. The third row carries a
// link that is not http(s): it must not become a link.
const CIRCULARS = {
  as_of: "2026-10-14", source: "SEBI RSS (sebi.gov.in) — circulars and master circulars", count: 3,
  rows: [
    { title: "Fixture circular on cyber resilience of intermediaries", url: "https://www.sebi.gov.in/legal/circulars/oct-2026/fixture-1.html", kind: "circular", issued_on: "2026-10-13" },
    { title: "Fixture master circular for stock brokers", url: "https://www.sebi.gov.in/legal/master-circulars/oct-2026/fixture-2.html", kind: "master_circular", issued_on: "2026-10-10" },
    { title: "Fixture circular with an unsafe link", url: "javascript:alert(1)", kind: "circular", issued_on: null },
  ],
};

type Reply = { status: number; body: unknown };
interface Calls { feed: URL[]; insights: string[]; home: number; sectors: number; deals: URL[]; circulars: URL[] }

/** Everything the desk header, the docked Copilot and these two tabs read. */
async function deskApi(page: Page, over: {
  home?: Reply; macro?: unknown; dash?: unknown; feed?: Reply; sectors?: Reply; deals?: Reply; circulars?: Reply;
} = {}): Promise<Calls> {
  const calls: Calls = { feed: [], insights: [], home: 0, sectors: 0, deals: [], circulars: [] };
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
  await page.route("**/api/markets/sector-returns", (route) => {
    calls.sectors += 1;
    return over.sectors ? json(route, over.sectors.body, over.sectors.status) : json(route, SECTOR_RETURNS);
  });
  await page.route("**/api/markets/deals*", (route) => {
    calls.deals.push(new URL(route.request().url()));
    return over.deals ? json(route, over.deals.body, over.deals.status) : json(route, DEALS);
  });
  await page.route("**/api/markets/circulars*", (route) => {
    calls.circulars.push(new URL(route.request().url()));
    return over.circulars ? json(route, over.circulars.body, over.circulars.status) : json(route, CIRCULARS);
  });
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
    // breadth.universe_kind "bhavcopy": the route counted every NSE stock in the end-of-day file.
    await expect(page.getByTestId("desk-breadth-scope")).toHaveAttribute("data-scope", "eod");
    await expect(page.getByTestId("desk-breadth-scope")).toHaveText(`Across ${int(b.universe)} NSE stocks in the end-of-day bhavcopy · ${day(HOME.as_of, true)}`);
    await expect(page.getByTestId("desk-breadth-bar")).toHaveAttribute("aria-label", `${int(b.advances)} advances, ${int(b.unchanged)} unchanged, ${int(b.declines)} declines`);

    // The route's fallback, named "nifty50_live": a live count over the Nifty 50 constituents.
    const live = { advances: 31, declines: 17, unchanged: 2, universe: 50, universe_kind: "nifty50_live", tone: "POSITIVE" };
    await page.route("**/api/markets/home", (route) => json(route, { ...HOME, breadth: live }));
    await page.reload();
    await expect(page.getByTestId("desk-breadth-pct")).toHaveText(`${((31 / 50) * 100).toFixed(1)}%`);
    await expect(page.getByTestId("desk-breadth-scope")).toHaveAttribute("data-scope", "nifty50");
    await expect(page.getByTestId("desk-breadth-scope")).toHaveText("Across the 50 Nifty 50 stocks · delayed quotes");

    // No kind (an older backend) or one this screen does not know: the count is shown and nothing is guessed from its
    // size — 50 stocks is not called the Nifty 50.
    for (const kind of [undefined, null, "zzz_unknown"]) {
      const unnamed = { advances: 31, declines: 17, unchanged: 2, universe: 50, tone: "POSITIVE", ...(kind === undefined ? {} : { universe_kind: kind }) };
      await page.route("**/api/markets/home", (route) => json(route, { ...HOME, breadth: unnamed }));
      await page.reload();
      await expect(page.getByTestId("desk-breadth-scope")).toHaveAttribute("data-scope", "unnamed");
      await expect(page.getByTestId("desk-breadth-scope")).toHaveText("Across 50 stocks · the response does not say which");
    }
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

  test("TC-11: sector strength: 1D / 1W / 1M from /markets/sector-returns, source and as-of named, leaders by exact sector match", async ({ page }) => {
    const calls = await deskApi(page);
    await page.goto(`${DESK}?tab=overview`);
    const tiles = page.getByTestId("desk-sector-tile");
    await expect(tiles).toHaveCount(SECTOR_RETURNS.sectors.length);
    // The old "periods not connected" gap is gone.
    await expect(page.getByTestId("desk-sector-periods-gap")).toHaveCount(0);

    const checkPeriod = async (period: "1d" | "1w" | "1m", words: string, sessions: number) => {
      await expect(page.getByTestId(`desk-sector-period-${period}`)).toHaveAttribute("aria-pressed", "true");
      for (const other of (["1d", "1w", "1m"] as const).filter((p) => p !== period)) {
        await expect(page.getByTestId(`desk-sector-period-${other}`)).toHaveAttribute("aria-pressed", "false");
      }
      await expect(page.getByTestId("desk-sector-period")).toHaveText(`${words} · ${sessions} ${sessions === 1 ? "session" : "sessions"} · end of day`);
      const order = sectorOrder(period);
      for (let i = 0; i < order.length; i += 1) {
        const r: SectorRow = order[i];
        await expect(tiles.nth(i)).toHaveAttribute("data-index", r.index);
        await expect(tiles.nth(i).getByTestId("desk-sector-pct")).toHaveText(pctOrDash(r[PERIOD_KEY[period]] as number | null));
      }
      await expect(page.getByTestId("desk-sector-source")).toContainText(`${words} = the index close vs its close ${sessions} ${sessions === 1 ? "session" : "sessions"} earlier`);
    };

    // 1D by default: IT +1.42, PSU Bank +0.95, Bank +0.30, Metal −0.85, Realty −1.60.
    await checkPeriod("1d", "1 day", SECTOR_RETURNS.sessions["1d"]);
    const it = page.locator('[data-testid="desk-sector-tile"][data-index="Nifty IT"]');
    await expect(it.getByTestId("desk-sector-index")).toHaveText(`Nifty IT · ${level(35210.5)}`);
    // Tint by sign.
    expect(await tiles.nth(0).getAttribute("style")).toContain("var(--mint)");
    expect(await tiles.nth(SECTOR_RETURNS.sectors.length - 1).getAttribute("style")).toContain("var(--cp-danger)");
    // Source and as-of from the response.
    await expect(page.getByTestId("desk-sector-source")).toContainText(`Source: ${SECTOR_RETURNS.source}`);
    await expect(page.getByTestId("desk-sector-source")).toContainText(`end of day ${day(SECTOR_RETURNS.as_of, true)}`);
    // Nifty Realty's own close is older than the as-of, and says so.
    await expect(page.locator('[data-testid="desk-sector-tile"][data-index="Nifty Realty"]').getByTestId("desk-sector-index")).toHaveText(`Nifty Realty · ${level(980.4)} · close of ${day("2026-10-10")}`);

    // 1W re-ranks: Metal +2.6 first, Realty −3.05 last.
    await page.getByTestId("desk-sector-period-1w").click();
    await checkPeriod("1w", "1 week", SECTOR_RETURNS.sessions["1w"]);
    // 1M: Metal has no 1-month history — "—", listed last, and the source line counts it.
    await page.getByTestId("desk-sector-period-1m").click();
    await checkPeriod("1m", "1 month", SECTOR_RETURNS.sessions["1m"]);
    await expect(page.locator('[data-testid="desk-sector-tile"][data-index="Nifty Metal"]').getByTestId("desk-sector-pct")).toHaveText("—");
    await expect(page.getByTestId("desk-sector-source")).toContainText("1 with too little history for this period show “—”");
    // One read: the toggle re-sorts the same response.
    expect(calls.sectors).toBe(1);

    // Leaders: IT matches by sector, Bank by index name; PSU Bank does not borrow Bank's leader; Metals ≠ Metal (no leader sent).
    await expect(it.getByTestId("desk-sector-leader-label")).toHaveText(`TESTIT ${pct(6.1, 1)} · 5 sessions`);
    await expect(it.getByTestId("desk-sector-leader").locator('[data-testid="entity-icon"]')).toHaveAttribute("data-key", "TESTIT");
    await expect(page.locator('[data-testid="desk-sector-tile"][data-index="Nifty Bank"]').getByTestId("desk-sector-leader")).toContainText("TESTBANK");
    await expect(page.locator('[data-testid="desk-sector-tile"][data-index="Nifty PSU Bank"]').getByTestId("desk-sector-leader")).toHaveCount(0);
    await expect(page.locator('[data-testid="desk-sector-tile"][data-index="Nifty Metal"]').getByTestId("desk-sector-leader")).toHaveCount(0);
    await expect(page.getByTestId("desk-sector-leader")).toHaveCount(2);
    await expect(page.getByTestId("desk-sector-source")).toContainText("leader = the sector’s best stock over 5 sessions");

    // The leader opens its chart.
    await it.getByTestId("desk-sector-leader").click();
    await expect(page).toHaveURL(/[?&]tab=chart/);
    await expect(page).toHaveURL(/[?&]sym=TESTIT/);
  });

  test("TC-11: sector returns — a failed read shows an error with retry, 403 says not enabled, an empty list says so; a failed leader read only drops the leaders", async ({ page }) => {
    const calls = await deskApi(page, { sectors: { status: 502, body: { detail: "upstream_unavailable" } } });
    await page.route("**/api/positional/market-dashboard", (route) => json(route, { detail: "fixture failure" }, 500));
    await page.goto(`${DESK}?tab=overview`);
    const err = page.getByTestId("desk-sectors-error");
    await expect(err.getByRole("alert")).toContainText("Sector strength didn’t load", SLOW);
    const before = calls.sectors;
    await err.getByRole("button", { name: /Retry/ }).click();
    await expect.poll(() => calls.sectors).toBeGreaterThan(before);

    await page.route("**/api/markets/sector-returns", (route) => json(route, { detail: "feature_not_enabled" }, 403));
    await page.reload();
    await expect(page.getByTestId("desk-sectors-error")).toContainText("Sector strength is not enabled for this account");

    await page.route("**/api/markets/sector-returns", (route) => json(route, { ...SECTOR_RETURNS, sectors: [] }));
    await page.reload();
    await expect(page.getByTestId("desk-sectors-empty")).toContainText("No sector figures yet");

    // Tiles without leaders when the dashboard fails (it answers 500 throughout this test).
    await page.route("**/api/markets/sector-returns", (route) => json(route, SECTOR_RETURNS));
    await page.reload();
    await expect(page.getByTestId("desk-sector-tile")).toHaveCount(SECTOR_RETURNS.sectors.length);
    await expect(page.getByTestId("desk-sector-leaders-error")).toBeVisible(SLOW);
    await expect(page.getByTestId("desk-sector-leader")).toHaveCount(0);
  });

  test("TC-12: a failed market overview shows an error with retry while the regime and sectors still render", async ({ page }) => {
    const calls = await deskApi(page, { home: { status: 500, body: { detail: "fixture failure" } } });
    await page.goto(`${DESK}?tab=overview`);
    const problem = page.getByTestId("desk-index-error");
    await expect(problem.getByRole("alert")).toBeVisible(SLOW);
    await expect(page.getByTestId("desk-index-tile")).toHaveCount(0);
    await expect(page.getByTestId("desk-regime-label")).toHaveText("Bullish");
    await expect(page.getByTestId("desk-sector-tile")).toHaveCount(SECTOR_RETURNS.sectors.length);
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
    // The M&A filing has no document link; its exchange comes from the row's own `exchange`.
    await rows.nth(0).click();
    await expect(detail.getByTestId("desk-event-sources")).toContainText("Filed with BSE");
    await expect(detail.getByTestId("desk-event-doc")).toHaveCount(0);
    // The deals list sits under the filings; the old "not connected" gaps are gone.
    await expect(page.getByTestId("desk-deals")).toBeVisible();
    await expect(page.getByTestId("desk-intel-deals-gap")).toHaveCount(0);

    // Regulatory is asked for by name (the default feed leaves it out), with SEBI's own circulars under it.
    await page.getByTestId("desk-intel-chip-regulatory").click();
    await expect.poll(() => calls.feed.map((u) => u.searchParams.get("category"))).toContain("regulatory");
    await expect(page.getByTestId("desk-circulars")).toBeVisible();
    await expect(page.getByTestId("desk-intel-sebi-gap")).toHaveCount(0);

    // Latest-first ordering is a query parameter too.
    await page.getByTestId("desk-intel-chip-all").click();
    await page.getByTestId("desk-intel-sort-latest").click();
    await expect.poll(() => calls.feed.some((u) => u.searchParams.get("sort") === "latest" && !u.searchParams.get("category"))).toBe(true);
  });

  test("Orders & deals lists bulk and block deals from /markets/deals; figures, window and source from the payload; a row opens its chart", async ({ page }) => {
    const calls = await deskApi(page);
    await page.goto(`${DESK}?tab=intel`);
    // Not read until the chip is open.
    await expect(page.getByTestId("desk-event-row")).toHaveCount(3);
    expect(calls.deals).toHaveLength(0);
    await page.getByTestId("desk-intel-chip-orders").click();

    const table = page.getByTestId("desk-deals-table");
    const deals = table.getByRole("row").filter({ has: page.getByTestId("desk-deal-symbol") });
    await expect(deals).toHaveCount(DEALS.rows.length);
    const q = calls.deals[0].searchParams;
    expect([q.get("days"), q.get("kind"), q.get("limit")]).toEqual(["5", "all", "200"]);

    const qty = (n: number) => (n >= 1e5 ? `${(n / 1e5).toFixed(2)} L` : int(n));
    for (let i = 0; i < DEALS.rows.length; i += 1) {
      const d = DEALS.rows[i];
      const r = deals.nth(i);
      await expect(r.getByTestId("desk-deal-date")).toHaveText(day(d.date));
      await expect(r.getByTestId("desk-deal-kind")).toHaveText(d.kind === "bulk" ? "Bulk" : "Block");
      await expect(r.getByTestId("desk-deal-symbol")).toHaveText(d.symbol);
      await expect(r.locator('[data-testid="entity-icon"]')).toHaveAttribute("data-key", d.symbol);
      await expect(r.getByTestId("desk-deal-client")).toHaveText(d.client_name);
      await expect(r.getByTestId("desk-deal-side")).toHaveText(d.side);
      expect(await r.getByTestId("desk-deal-side").getAttribute("style")).toContain(d.side === "BUY" ? "var(--mint)" : "var(--cp-danger)");
      await expect(r.getByTestId("desk-deal-qty")).toHaveText(qty(d.quantity));
      await expect(r.getByTestId("desk-deal-price")).toHaveText(`₹${level(d.avg_price)}`);
      // ₹ crore = quantity × price ÷ 1e7, worked out here and checked against the route's figure.
      const cr = (d.quantity * d.avg_price) / 1e7;
      expect(Number(cr.toFixed(2))).toBe(d.value_cr);
      await expect(r.getByTestId("desk-deal-value")).toHaveText(cr.toFixed(2));
    }
    const src = page.getByTestId("desk-deals-source");
    await expect(src).toContainText(`Source: ${DEALS.source}`);
    await expect(src).toContainText(`end of day ${day(DEALS.as_of, true)}`);
    await expect(src).toContainText(`${day(DEALS.from)} to ${day(DEALS.as_of)}, the sessions on record`);
    await expect(page.getByTestId("desk-deals-count")).toContainText(`${DEALS.rows.length} of ${DEALS.rows.length} loaded`);

    await deals.nth(1).click();
    await expect(page).toHaveURL(/[?&]tab=chart/);
    await expect(page).toHaveURL(new RegExp(`[?&]sym=${DEALS.rows[1].symbol}(&|$)`));
  });

  test("Deals: empty, failed (with retry) and 403 states", async ({ page }) => {
    const calls = await deskApi(page, { deals: { status: 200, body: { ...DEALS, count: 0, total: 0, rows: [] } } });
    await page.goto(`${DESK}?tab=intel`);
    await page.getByTestId("desk-intel-chip-orders").click();
    await expect(page.getByTestId("desk-deals-empty")).toContainText(`No bulk or block deals are on record in the 5 calendar days to ${day(DEALS.as_of, true)}`);

    await page.route("**/api/markets/deals*", (route) => { calls.deals.push(new URL(route.request().url())); return json(route, { detail: "upstream_unavailable" }, 502); });
    await page.reload();
    await page.getByTestId("desk-intel-chip-orders").click();
    const err = page.getByTestId("desk-deals-error");
    await expect(err.getByRole("alert")).toContainText("Bulk and block deals didn’t load", SLOW);
    const before = calls.deals.length;
    await err.getByRole("button", { name: /Retry/ }).click();
    await expect.poll(() => calls.deals.length).toBeGreaterThan(before);

    await page.route("**/api/markets/deals*", (route) => json(route, { detail: "feature_not_enabled" }, 403));
    await page.reload();
    await page.getByTestId("desk-intel-chip-orders").click();
    await expect(page.getByTestId("desk-deals-error")).toContainText("Bulk and block deals is not enabled for this account");
  });

  test("Regulatory lists SEBI circulars from /markets/circulars: title link, kind, issue date, source; a non-web link is not a link", async ({ page }) => {
    const calls = await deskApi(page);
    await page.goto(`${DESK}?tab=intel`);
    await page.getByTestId("desk-intel-chip-regulatory").click();
    const items = page.getByTestId("desk-circular");
    await expect(items).toHaveCount(CIRCULARS.rows.length);
    expect([calls.circulars[0].searchParams.get("days"), calls.circulars[0].searchParams.get("limit")]).toEqual(["30", "50"]);
    for (let i = 0; i < CIRCULARS.rows.length; i += 1) {
      const c = CIRCULARS.rows[i];
      const it = items.nth(i);
      await expect(it.getByTestId("desk-circular-kind")).toHaveText(c.kind === "master_circular" ? "Master circular" : "Circular");
      await expect(it.getByTestId("desk-circular-date")).toHaveText(c.issued_on ? `Issued ${day(c.issued_on, true)}` : "Issue date not stated");
      if (c.url.startsWith("https://")) {
        await expect(it.getByTestId("desk-circular-title")).toHaveText(`${c.title} ↗`);
        await expect(it.getByTestId("desk-circular-title")).toHaveAttribute("href", c.url);
        await expect(it.getByTestId("desk-circular-title")).toHaveAttribute("target", "_blank");
      } else {
        await expect(it.getByTestId("desk-circular-title")).toHaveText(c.title);
        await expect(it.locator("a")).toHaveCount(0);
      }
    }
    await expect(page.getByTestId("desk-circulars-source")).toContainText(`Source: ${CIRCULARS.source}`);
    await expect(page.getByTestId("desk-circulars-source")).toContainText(`as of ${day(CIRCULARS.as_of, true)}`);
  });

  test("Circulars: empty and failed states", async ({ page }) => {
    const calls = await deskApi(page, { circulars: { status: 200, body: { ...CIRCULARS, count: 0, rows: [] } } });
    await page.goto(`${DESK}?tab=intel`);
    await page.getByTestId("desk-intel-chip-regulatory").click();
    await expect(page.getByTestId("desk-circulars-empty")).toContainText("No SEBI circulars on record");

    await page.route("**/api/markets/circulars*", (route) => { calls.circulars.push(new URL(route.request().url())); return json(route, { detail: "upstream_unavailable" }, 502); });
    await page.reload();
    await page.getByTestId("desk-intel-chip-regulatory").click();
    const err = page.getByTestId("desk-circulars-error");
    await expect(err.getByRole("alert")).toContainText("SEBI circulars didn’t load", SLOW);
    const before = calls.circulars.length;
    await err.getByRole("button", { name: /Retry/ }).click();
    await expect.poll(() => calls.circulars.length).toBeGreaterThan(before);
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
    await expect(page.getByTestId("desk-sector-tile")).toHaveCount(SECTOR_RETURNS.sectors.length);
    await expect(page.getByTestId("desk-regime-label")).toHaveText("Bullish");
    let o = await overflow(page);
    expect(o.doc).toBeLessThanOrEqual(1);
    expect(o.scroll).toBeLessThanOrEqual(1);
    await page.getByTestId("desk-sector-period-1m").click();
    await expect(page.getByTestId("desk-sector-period-1m")).toHaveAttribute("aria-pressed", "true");
    o = await overflow(page);
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

    // The deals table scrolls inside its own box; the circulars wrap.
    await page.getByTestId("desk-intel-chip-orders").click();
    await expect(page.getByTestId("desk-deal-symbol")).toHaveCount(DEALS.rows.length);
    o = await overflow(page);
    expect(o.doc).toBeLessThanOrEqual(1);
    expect(o.scroll).toBeLessThanOrEqual(1);
    await page.getByTestId("desk-intel-chip-regulatory").click();
    await expect(page.getByTestId("desk-circular")).toHaveCount(CIRCULARS.rows.length);
    o = await overflow(page);
    expect(o.doc).toBeLessThanOrEqual(1);
    expect(o.scroll).toBeLessThanOrEqual(1);
  });
});
