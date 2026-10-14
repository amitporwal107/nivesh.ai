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
    // Design §3: "67% advancing" at the top right, "<n> advances … declines <n>" under the bar.
    await expect(page.getByTestId("desk-breadth-pct")).toHaveText(`${share.toFixed(0)}%`);
    await expect(page.getByTestId("desk-breadth-adv")).toHaveText(`${int(b.advances)} advances`);
    await expect(page.getByTestId("desk-breadth-dec")).toHaveText(`declines ${int(b.declines)}`);
    // breadth.universe_kind "bhavcopy": the route counted every NSE stock in the end-of-day file.
    await expect(page.getByTestId("desk-breadth-scope")).toHaveAttribute("data-scope", "eod");
    await expect(page.getByTestId("desk-breadth-scope")).toHaveText(`Across ${int(b.universe)} NSE stocks in the end-of-day bhavcopy · ${day(HOME.as_of, true)}`);
    await expect(page.getByTestId("desk-breadth-bar")).toHaveAttribute("aria-label", `${int(b.advances)} advances, ${int(b.unchanged)} unchanged, ${int(b.declines)} declines`);

    // The route's fallback, named "nifty50_live": a live count over the Nifty 50 constituents.
    const live = { advances: 31, declines: 17, unchanged: 2, universe: 50, universe_kind: "nifty50_live", tone: "POSITIVE" };
    await page.route("**/api/markets/home", (route) => json(route, { ...HOME, breadth: live }));
    await page.reload();
    await expect(page.getByTestId("desk-breadth-pct")).toHaveText(`${((31 / 50) * 100).toFixed(0)}%`);
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
    // FII net is negative in the payload: a net sell. DII is positive: a net buy.
    await expect(page.getByTestId("desk-mini-fii-sub")).toHaveText(`Net sell · ${day(HOME.fii_dii.as_of)}`);
    await expect(page.getByTestId("desk-mini-dii-sub")).toHaveText(`Net buy · ${day(HOME.fii_dii.as_of)}`);
    await expect(page.getByTestId("desk-mini-usdinr-value")).toHaveText(level(84.12));
    await expect(page.getByTestId("desk-mini-usdinr-sub")).toHaveText(`Spot · ${pct(0.11)}`);
    await expect(page.getByTestId("desk-mini-brent-value")).toHaveText(`$${level(63.4)}`);
    await expect(page.getByTestId("desk-mini-brent-sub")).toHaveText(`Brent · ${pct(-1.25)}`);

    const read = page.getByTestId("desk-insight");
    await expect(read).toContainText("Rules-based insight");
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
    // Design §3 tile: name and return only; the index and its close are in the tile's title.
    await expect(it).toHaveAttribute("title", `Nifty IT · ${level(35210.5)} · close of ${day("2026-10-13")}`);
    await expect(it.getByTestId("desk-sector-stale")).toHaveCount(0);
    // Tint by sign.
    expect(await tiles.nth(0).getAttribute("style")).toContain("var(--mint)");
    expect(await tiles.nth(SECTOR_RETURNS.sectors.length - 1).getAttribute("style")).toContain("var(--cp-danger)");
    // Source and as-of from the response.
    await expect(page.getByTestId("desk-sector-source")).toContainText(`Source: ${SECTOR_RETURNS.source}`);
    await expect(page.getByTestId("desk-sector-source")).toContainText(`end of day ${day(SECTOR_RETURNS.as_of, true)}`);
    // Nifty Realty's own close is older than the as-of, and says so.
    const realty = page.locator('[data-testid="desk-sector-tile"][data-index="Nifty Realty"]');
    await expect(realty.getByTestId("desk-sector-stale")).toHaveText(`Close of ${day("2026-10-10")}`);
    await expect(realty).toHaveAttribute("title", `Nifty Realty · ${level(980.4)} · close of ${day("2026-10-10")}`);

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

  test("a question typed in the desk search goes to the Copilot (the Overview has no ask-chip row in the design)", async ({ page }) => {
    await deskApi(page);
    const sent = await mockAsk(page);
    await page.goto(`${DESK}?tab=overview`);
    await expect(page.getByTestId("desk-overview-ask")).toHaveCount(0);
    await page.getByTestId("desk-search").fill("Which sectors are leading today and why?");
    await page.getByTestId("desk-search").press("Enter");
    await expect.poll(() => sent).toContain("Which sectors are leading today and why?");
  });
});

// ── Market intelligence ─────────────────────────────────────────────────
//
// Design-spec §6: one event list (newest first) and a detail panel; chips All · Results · Corporate · Regulatory ·
// FII / DII · Bulk & block. Ids: a filing keeps its own id; the other sources are "fiidii-<date>",
// "deal-<date>-<kind>-<symbol>-<i>" and "sebi-<date>-<i>" (i = position in the list the chip takes).

const IST_EOD = (d: string) => Date.parse(`${d}T23:59:59+05:30`);
const newestFirst = (a: { t: number }, b: { t: number }) => (a.t === b.t ? 0 : b.t - a.t);
/** "All": the default filing mix, the 5 latest FII / DII sessions, the 5 largest deals, the 5 latest circulars, newest first (dated-only rows count as the end of their day). */
function expectedAll(): string[] {
  const out: Array<{ id: string; t: number }> = [];
  for (const r of [R_EARN, R_ORDER, R_LIT]) out.push({ id: r.id, t: Date.parse(r.date as string) });
  [...FLOWS.daily].sort((a, b) => b.date.localeCompare(a.date)).slice(0, 5).forEach((f) => out.push({ id: `fiidii-${f.date}`, t: IST_EOD(f.date) }));
  [...DEALS.rows].sort((a, b) => b.value_cr - a.value_cr).slice(0, 5).forEach((d, i) => out.push({ id: `deal-${d.date}-${d.kind}-${d.symbol}-${i}`, t: IST_EOD(d.date) }));
  [...CIRCULARS.rows]
    .map((c) => ({ c, t: c.issued_on ? IST_EOD(c.issued_on) : -Infinity }))
    .sort(newestFirst)
    .slice(0, 5)
    .forEach(({ c, t }, i) => out.push({ id: `sebi-${c.issued_on ?? "nodate"}-${i}`, t }));
  return out.sort(newestFirst).map((e) => e.id);
}
const flowCr = (n: number) => `₹${int(Math.abs(n))} Cr`;
const flowWords = (who: string, n: number) => (n > 0 ? `${who} net bought ${flowCr(n)}` : n < 0 ? `${who} net sold ${flowCr(n)}` : `${who} flat`);
const lakhQty = (n: number) => (n >= 1e5 ? `${(n / 1e5).toFixed(2)} L` : int(n));
/** TESTPICK with daily closes, so its 1-day change can be shown (routes/positional.py :: get_picks spark fields). */
const PICKS_SPARK = { ...PICKS, picks: PICKS.picks.map((p) => ({ ...p, spark_closes: [498.0, 505.0, 512.4], spark_end: "2026-10-13" })) };

test.describe("Smart trading desk — Market intelligence", () => {
  test("§6 frame: 04 · AI Event intelligence, its meta, the six chips in order, no sort control, a two-pane list and detail", async ({ page }) => {
    const calls = await deskApi(page);
    await page.route("**/api/positional/picks*", (route) => json(route, PICKS_SPARK));
    await page.goto(`${DESK}?tab=intel`);
    await expect(page.getByTestId("desk-intel-title")).toHaveText("04 · AI Event intelligence");
    await expect(page.getByTestId("desk-intel-meta")).toHaveText("NSE · BSE · SEBI · linked to the scanner");
    const chips = page.getByRole("group", { name: "Event type" }).getByRole("button");
    await expect(chips).toHaveText(["All", "Results", "Corporate", "Regulatory", "FII / DII", "Bulk & block"]);
    await expect(page.getByTestId("desk-intel-chip-all")).toHaveAttribute("aria-pressed", "true");
    await expect(page.locator('[data-testid^="desk-intel-sort-"]')).toHaveCount(0);

    // All: every source, newest first; 12 listed, then "Show more".
    const order = expectedAll();
    const rows = page.getByTestId("desk-event-row");
    await expect(rows).toHaveCount(12);
    expect(await rows.evaluateAll((els) => els.map((e) => e.getAttribute("data-id")))).toEqual(order.slice(0, 12));
    await expect(page.getByTestId("desk-intel-count")).toHaveText(
      `12 of ${order.length} events · newest first · 3 filings of 57 in the last 7 days, the ${DEALS.rows.length} largest deals of the last 5 days, the ${CIRCULARS.rows.length} latest SEBI circulars, the 5 latest FII / DII sessions`,
    );
    await page.getByTestId("desk-intel-more").click();
    await expect(rows).toHaveCount(order.length);
    // The filings request: the route's default mix (no category), the last 7 days, newest first. Deals and circulars are read for All.
    expect(calls.feed[0].searchParams.get("category")).toBeNull();
    expect([calls.feed[0].searchParams.get("days"), calls.feed[0].searchParams.get("sort")]).toEqual(["7", "latest"]);
    expect([calls.deals[0].searchParams.get("days"), calls.deals[0].searchParams.get("kind"), calls.deals[0].searchParams.get("limit")]).toEqual(["5", "all", "200"]);
    expect([calls.circulars[0].searchParams.get("days"), calls.circulars[0].searchParams.get("limit")]).toEqual(["30", "50"]);

    // Row grid 62px | text | right column; the first row is selected (bg-2) and the detail panel sits beside the list.
    const first = rows.nth(0);
    expect(await first.evaluate((e) => getComputedStyle(e).gridTemplateColumns.split(" ")[0])).toBe("62px");
    await expect(first).toHaveAttribute("aria-pressed", "true");
    const detail = page.getByTestId("desk-event-detail");
    await expect(detail).toHaveAttribute("data-id", order[0]);
    const [listBox, detailBox] = [await page.getByTestId("desk-event-list").boundingBox(), await detail.boundingBox()];
    expect((detailBox?.x ?? 0)).toBeGreaterThan((listBox?.x ?? 0) + (listBox?.width ?? 0) - 2);

    // A filing row: coloured type, title, the generated read as its sub, the classifier's sentiment, the stock with its icon,
    // and its 1-day change from the scanner's closes: (512.40 − 505) ÷ 505.
    const earn = page.locator(`[data-testid="desk-event-row"][data-id="${R_EARN.id}"]`);
    await expect(earn.getByTestId("desk-event-type")).toHaveText("Results");
    expect(await earn.getByTestId("desk-event-type").getAttribute("style")).toContain("var(--cp-indigo)");
    await expect(earn.getByTestId("desk-event-title")).toHaveText(R_EARN.docLabel as string);
    await expect(earn.getByTestId("desk-event-sub")).toHaveText(R_EARN.one as string);
    await expect(earn.getByTestId("desk-event-sentiment")).toHaveText("Positive");
    await expect(earn.getByTestId("desk-event-stock")).toHaveText("TESTPICK");
    await expect(earn.locator('[data-testid="entity-icon"]')).toHaveAttribute("data-key", "TESTPICK");
    await expect(earn.getByTestId("desk-event-change")).toHaveText(pct(((512.4 - 505) / 505) * 100));
    // A stock that is not in today's scan has no close on the desk: "—".
    await expect(page.locator(`[data-testid="desk-event-row"][data-id="${R_ORDER.id}"]`).getByTestId("desk-event-change")).toHaveText("—");
    await expect(page.locator(`[data-testid="desk-event-row"][data-id="${R_ORDER.id}"]`).getByTestId("desk-event-type")).toHaveText("Corporate · Order");
    await expect(page.locator(`[data-testid="desk-event-row"][data-id="${R_LIT.id}"]`).getByTestId("desk-event-sentiment")).toHaveText("Negative");

    // FII / DII: no sentiment (no classification exists); the change slot carries the FII net flow.
    const f0 = FLOWS.daily[0];
    const flow = page.locator(`[data-testid="desk-event-row"][data-id="fiidii-${f0.date}"]`);
    await expect(flow.getByTestId("desk-event-type")).toHaveText("FII / DII");
    await expect(flow.getByTestId("desk-event-title")).toHaveText(`${flowWords("FIIs", f0.fii_net)} · ${flowWords("DIIs", f0.dii_net)}`);
    await expect(flow.getByTestId("desk-event-sentiment")).toHaveCount(0);
    await expect(flow.getByTestId("desk-event-change")).toHaveText(`FII ${sgn(f0.fii_net)}${flowCr(f0.fii_net)}`);

    // A deal: who, side and quantity; kind, value and average price (rose).
    const d0 = DEALS.rows[0];
    const deal = page.locator(`[data-testid="desk-event-row"][data-id="deal-${d0.date}-${d0.kind}-${d0.symbol}-0"]`);
    await expect(deal.getByTestId("desk-event-type")).toHaveText("Block deal");
    expect(await deal.getByTestId("desk-event-type").getAttribute("style")).toContain("var(--rose)");
    await expect(deal.getByTestId("desk-event-title")).toHaveText(`${d0.client_name} sold ${lakhQty(d0.quantity)} shares`);
    await expect(deal.getByTestId("desk-event-sub")).toHaveText(`Block deal · ₹${d0.value_cr.toFixed(2)} Cr · at ₹${level(d0.avg_price)} average`);

    // A SEBI circular sits under Regulatory (amber).
    const c0 = page.locator(`[data-testid="desk-event-row"][data-id="sebi-${CIRCULARS.rows[0].issued_on}-0"]`);
    await expect(c0.getByTestId("desk-event-type")).toHaveText("Regulatory · SEBI circular");
    expect(await c0.getByTestId("desk-event-type").getAttribute("style")).toContain("var(--amber)");
  });

  test("§6 detail: TYPE · TIME, sentiment, serif title, why it may matter, linked stock with its scan rank, numbered sources", async ({ page }) => {
    const calls = await deskApi(page);
    await page.goto(`${DESK}?tab=intel`);
    const detail = page.getByTestId("desk-event-detail");
    const row = (id: string) => page.locator(`[data-testid="desk-event-row"][data-id="${id}"]`);

    // A filing with a generated read.
    await row(R_EARN.id).click();
    await expect(row(R_EARN.id)).toHaveAttribute("aria-pressed", "true");
    await expect(detail).toHaveAttribute("data-id", R_EARN.id);
    await expect(detail.getByTestId("desk-event-detail-meta")).toHaveText("Results · 13 Oct 2026, 09:12 IST");
    await expect(detail.getByTestId("desk-event-sentiment")).toHaveText("Positive");
    await expect(detail.getByTestId("desk-event-detail-title")).toHaveText(R_EARN.docLabel as string);
    expect(await detail.getByTestId("desk-event-detail-title").evaluate((e) => [getComputedStyle(e).fontSize, getComputedStyle(e).fontFamily])).toEqual(["26px", expect.stringContaining("Instrument Serif")]);
    await expect(detail.getByTestId("desk-event-why")).toHaveText(R_EARN.one as string);
    // Linked stock: in today's scan (TESTPICK ranks first of the 3 merged setups), indigo, opens the chart.
    await expect(detail.getByTestId("desk-event-linked")).toContainText("TESTPICK");
    await expect(detail.getByTestId("desk-event-linked")).toHaveAttribute("data-tone", "indigo");
    await expect(detail.getByTestId("desk-event-linked").locator('[data-testid="entity-icon"]')).toHaveAttribute("data-key", "TESTPICK");
    await expect(detail.getByTestId("desk-event-scanner")).toContainText("TESTPICK is #1 of 3 in today’s scan. Select it to load the setup.");
    // Sources: [1] the filing on its exchange, linked.
    await expect(detail.getByTestId("desk-event-sources")).toHaveText(`[1]Filed with NSE · ${R_EARN.docLabel} ↗`);
    await expect(detail.getByTestId("desk-event-doc")).toHaveAttribute("href", R_EARN.url as string);
    // The full generated read is read only when asked for.
    expect(calls.insights).toHaveLength(0);
    await detail.getByTestId("desk-event-read-toggle").click();
    await expect(detail.getByTestId("filing-insight-one")).toHaveText(R_EARN.one as string);
    expect(calls.insights).toEqual([R_EARN.id]);

    // A filing with no read: the plain sentence, said as such; not in the scan; the exchange read from the link.
    await row(R_ORDER.id).click();
    await expect(detail).toHaveAttribute("data-id", R_ORDER.id);
    await expect(detail.getByTestId("desk-event-noread")).toHaveText("A company disclosure classified as Order. No generated read of this filing yet; the filing itself has the detail.");
    await expect(detail.getByTestId("desk-event-read-toggle")).toHaveCount(0);
    await expect(detail.getByTestId("desk-event-not-scanner")).toHaveText("TESTORD is not in today’s scan. Select it to open its chart.");
    await expect(detail.getByTestId("desk-event-sources")).toContainText("Filed with BSE");

    // FII / DII: market-wide, no sentiment, the provisional NSE figures as the source.
    const f0 = FLOWS.daily[0];
    await row(`fiidii-${f0.date}`).click();
    await expect(detail.getByTestId("desk-event-detail-meta")).toHaveText(`FII / DII · ${day(f0.date, true)}`);
    await expect(detail.getByTestId("desk-event-sentiment")).toHaveCount(0);
    await expect(detail.getByTestId("desk-event-market-wide")).toBeVisible();
    await expect(detail.getByTestId("desk-event-noread")).toContainText("Net buying (+) or selling (−) in the cash market");
    await expect(detail.getByTestId("desk-event-sources")).toHaveText(`[1]NSE · provisional FII / DII cash-market figures, ${day(f0.date, true)}`);

    // A deal: the route's source, end of day; a circular: SEBI's own link; an unsafe link is not a link.
    const d0 = DEALS.rows[0];
    await row(`deal-${d0.date}-${d0.kind}-${d0.symbol}-0`).click();
    await expect(detail.getByTestId("desk-event-sources")).toHaveText(`[1]${DEALS.source} · end of day ${day(d0.date, true)}`);
    await expect(detail.getByTestId("desk-event-linked")).toContainText(d0.symbol);
    await row(`sebi-${CIRCULARS.rows[0].issued_on}-0`).click();
    await expect(detail.getByTestId("desk-event-doc")).toHaveAttribute("href", CIRCULARS.rows[0].url);
    await expect(detail.getByTestId("desk-event-doc")).toHaveAttribute("target", "_blank");
    await page.getByTestId("desk-intel-more").click();
    await row("sebi-nodate-2").click();
    await expect(detail.getByTestId("desk-event-sources").locator("a")).toHaveCount(0);
    await expect(detail.getByTestId("desk-event-sources")).toHaveText("[1]SEBI · Circular");

    // The linked stock opens the Chart tab with that stock.
    await row(R_EARN.id).click();
    await detail.getByTestId("desk-event-linked").click();
    await expect(page.getByTestId("screen-trading-desk")).toHaveAttribute("data-tab", "chart");
    await expect(page).toHaveURL(/[?&]sym=TESTPICK/);
  });

  test("chips read the real sources: Results = earnings, Corporate = the nine corporate categories, Regulatory = filings + SEBI, FII / DII, Bulk & block", async ({ page }) => {
    const calls = await deskApi(page);
    await page.goto(`${DESK}?tab=intel`);
    const rows = page.getByTestId("desk-event-row");
    await expect(rows).toHaveCount(12);
    const ids = () => rows.evaluateAll((els) => els.map((e) => e.getAttribute("data-id")));

    await page.getByTestId("desk-intel-chip-results").click();
    await expect(page.getByTestId("desk-intel-chip-results")).toHaveAttribute("aria-pressed", "true");
    await expect.poll(() => calls.feed.map((u) => u.searchParams.get("category"))).toContain("earnings");
    await expect(rows).toHaveCount(1);
    expect(await ids()).toEqual([R_EARN.id]);

    await page.getByTestId("desk-intel-chip-corporate").click();
    const corporate = ["orders", "mna", "capex", "management", "dividend", "buyback", "qip", "rating", "litigation"];
    await expect.poll(() => calls.feed.map((u) => u.searchParams.get("category"))).toEqual(expect.arrayContaining(corporate));
    await expect(rows).toHaveCount(2);
    expect(await ids()).toEqual([R_ORDER.id, R_MNA.id]);
    await expect(rows.nth(1).getByTestId("desk-event-type")).toHaveText("Corporate · M&A");

    await page.getByTestId("desk-intel-chip-regulatory").click();
    await expect.poll(() => calls.feed.map((u) => u.searchParams.get("category"))).toContain("regulatory");
    await expect(rows).toHaveCount(CIRCULARS.rows.length);
    expect(await ids()).toEqual(CIRCULARS.rows.map((c, i) => `sebi-${c.issued_on ?? "nodate"}-${i}`));
    await expect(rows.nth(1).getByTestId("desk-event-type")).toHaveText("Regulatory · SEBI master circular");

    await page.getByTestId("desk-intel-chip-flows").click();
    const ten = [...FLOWS.daily].sort((a, b) => b.date.localeCompare(a.date)).slice(0, 10);
    await expect(rows).toHaveCount(10);
    expect(await ids()).toEqual(ten.map((f) => `fiidii-${f.date}`));
    await expect(rows.nth(9).getByTestId("desk-event-title")).toHaveText(`${flowWords("FIIs", ten[9].fii_net)} · ${flowWords("DIIs", ten[9].dii_net)}`);
    expect(await rows.nth(0).getByTestId("desk-event-change").getAttribute("style")).toContain(ten[0].fii_net < 0 ? "var(--cp-danger)" : "var(--mint)");

    await page.getByTestId("desk-intel-chip-deals").click();
    await expect(rows).toHaveCount(DEALS.rows.length);
    expect(await ids()).toEqual(DEALS.rows.map((d, i) => `deal-${d.date}-${d.kind}-${d.symbol}-${i}`));
    await expect(page.getByTestId("desk-intel-count")).toHaveText(`3 of 3 events · newest first · ${DEALS.rows.length} deals over 5 calendar days`);
    await expect(rows.nth(2).getByTestId("desk-event-title")).toHaveText(`${DEALS.rows[2].client_name} bought ${lakhQty(DEALS.rows[2].quantity)} shares`);
  });

  test("states: an empty chip, a failed chip with retry, a 403, and a partial All when one source fails", async ({ page }) => {
    const calls = await deskApi(page, { feed: { status: 200, body: { ok: true, total: 0, facets: {}, rows: [] } } });
    await page.goto(`${DESK}?tab=intel`);
    await page.getByTestId("desk-intel-chip-results").click();
    await expect(page.getByTestId("desk-intel-empty")).toContainText("No events here yet");
    await expect(page.getByTestId("desk-event-row")).toHaveCount(0);

    // Filings fail: All still lists the deals, circulars and flows and says what is missing, with a retry.
    await page.route("**/api/filings/feed*", (route) => { calls.feed.push(new URL(route.request().url())); return json(route, { detail: "fixture failure" }, 500); });
    await page.reload();
    const partial = page.getByTestId("desk-intel-partial");
    await expect(partial.getByRole("alert")).toContainText("Filings didn’t load; the rest are listed", SLOW);
    await expect(page.getByTestId("desk-event-row")).toHaveCount(5 + DEALS.rows.length + CIRCULARS.rows.length);
    const before = calls.feed.length;
    await partial.getByRole("button", { name: /Retry/ }).click();
    await expect.poll(() => calls.feed.length).toBeGreaterThan(before);
    // On its own chip the failure is the whole answer.
    await page.getByTestId("desk-intel-chip-results").click();
    await expect(page.getByTestId("desk-intel-error").getByRole("alert")).toContainText("Market events didn’t load", SLOW);

    await page.route("**/api/markets/deals*", (route) => json(route, { detail: "feature_not_enabled" }, 403));
    await page.reload();
    await page.getByTestId("desk-intel-chip-deals").click();
    await expect(page.getByTestId("desk-intel-error")).toContainText("this account does not have access", SLOW);
  });

  test("§10 persona: the investor wording explains the event in plain language; the trader wording is the classifier's read", async ({ page }) => {
    await deskApi(page);
    await page.goto(`${DESK}?tab=intel`);
    const detail = page.getByTestId("desk-event-detail");
    const row = (id: string) => page.locator(`[data-testid="desk-event-row"][data-id="${id}"]`);
    await row(R_EARN.id).click();
    await expect(detail.getByTestId("desk-event-why")).toHaveText(R_EARN.one as string);
    await page.getByTestId("desk-persona-investor").click();
    await expect(detail.getByTestId("desk-event-why")).toHaveText(
      `The company has published its quarterly numbers. Share prices often react when results are better or worse than people expected. What the filing says: ${R_EARN.one}`,
    );
    await row(R_ORDER.id).click();
    await expect(detail.getByTestId("desk-event-noread")).toHaveText(
      "The company told the exchange about a new order or contract. News like this can affect the share price. No generated read of this filing yet; the filing itself has the detail.",
    );
    await page.getByTestId("desk-persona-trader").click();
    await expect(detail.getByTestId("desk-event-noread")).toHaveText("A company disclosure classified as Order. No generated read of this filing yet; the filing itself has the detail.");
  });
});

// ── 390px ───────────────────────────────────────────────────────────────

test.describe("Smart trading desk — Overview and Market intelligence at 390px", () => {
  test("TC-7: no sideways scroll on either tab", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await deskApi(page);
    await page.goto(`${DESK}?tab=overview`);
    // The phone's Overview is design §11 M1: index tiles, pulse, top opportunities, portfolio and risk tiles (no sector card).
    await expect(page.getByTestId("desk-overview")).toHaveAttribute("data-layout", "mobile");
    await expect(page.getByTestId("desk-index-tile")).toHaveCount(4);
    await expect(page.getByTestId("desk-regime-label")).toHaveText("Bullish");
    await expect(page.getByTestId("desk-top-opp")).toHaveCount(3);
    let o = await overflow(page);
    expect(o.doc).toBeLessThanOrEqual(1);
    expect(o.scroll).toBeLessThanOrEqual(1);
    await page.getByTestId("desk-pulse-details").click();
    await expect(page.getByTestId("desk-mini-fii-value")).toHaveText(crore(HOME.fii_dii.fii_net_cr));
    o = await overflow(page);
    expect(o.doc).toBeLessThanOrEqual(1);
    expect(o.scroll).toBeLessThanOrEqual(1);

    // The Market intelligence phone layout (design §11 M3) and its 390px checks are in "Market intelligence · design fidelity" below.
  });
});

// ── Market intelligence · design fidelity (design-spec §6, §10, §11 M3) ──

/** Screenshots for the design comparison land in test-results/ (git-ignored); they assert nothing on their own. */
const SHOTS = "test-results/fidelity-shots";

test.describe("Smart trading desk — Market intelligence · design fidelity", () => {
  test("§11 M3 at 390: type chips in one scrolling row, 04 · Top market events with tap-for-why rows, Sector impact · 1D 3×2, no sideways scroll", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await deskApi(page);
    await page.goto(`${DESK}?tab=intel`);
    const intel = page.getByTestId("desk-intel");
    // The chips: the design's six, on one row that scrolls inside itself.
    const chips = intel.getByRole("group", { name: "Event type" });
    await expect(chips.getByRole("button")).toHaveText(["All", "Results", "Corporate", "Regulatory", "FII / DII", "Bulk & block"]);
    expect(await chips.evaluate((e) => getComputedStyle(e).flexWrap)).toBe("nowrap");
    const tops = await chips.getByRole("button").evaluateAll((els) => els.map((e) => Math.round(e.getBoundingClientRect().top)));
    expect(new Set(tops).size).toBe(1);

    // The events card: title and the "tap for why" note; no side detail panel on a phone.
    await expect(page.getByTestId("desk-intel-title")).toHaveText("04 · Top market events");
    await expect(page.getByTestId("desk-intel-events")).toContainText("Tap for why");
    await expect(page.getByTestId("desk-event-detail")).toHaveCount(0);
    const order = expectedAll();
    const rows = page.getByTestId("desk-event-row");
    await expect(rows).toHaveCount(12);
    expect(await rows.evaluateAll((els) => els.map((e) => e.getAttribute("data-id")))).toEqual(order.slice(0, 12));
    const toggle = rows.nth(0).getByTestId("desk-event-toggle");
    expect(await toggle.evaluate((e) => getComputedStyle(e).gridTemplateColumns.split(" ")[0])).toBe("44px");

    // Tap a filing: it expands in place with "Why it may matter" and its numbered source.
    const earn = page.locator(`[data-testid="desk-event-row"][data-id="${R_EARN.id}"]`);
    await expect(earn.getByTestId("desk-event-sentiment")).toHaveText("Positive");
    await expect(earn.getByTestId("desk-event-type")).toHaveText("Results");
    await expect(earn.getByTestId("desk-event-linked")).toContainText("TESTPICK");
    await earn.getByTestId("desk-event-toggle").click();
    await expect(earn.getByTestId("desk-event-toggle")).toHaveAttribute("aria-expanded", "true");
    const box = earn.getByTestId("desk-event-why-box");
    await expect(box).toContainText("Why it may matter");
    await expect(box.getByTestId("desk-event-why")).toHaveText(R_EARN.one as string);
    await expect(box.getByTestId("desk-event-sources")).toHaveText(`[1]Filed with NSE · ${R_EARN.docLabel} ↗`);
    await expect(box.getByTestId("desk-event-scanner")).toHaveText("TESTPICK is #1 of 3 in today’s scan.");
    // Tapping again closes it; only one is open at a time.
    await earn.getByTestId("desk-event-toggle").click();
    await expect(page.getByTestId("desk-event-why-box")).toHaveCount(0);

    // Sector impact · 1D: the six sector indices that moved most (here all five), highest first, heat by size.
    const sectors = page.getByTestId("desk-intel-sectors");
    await expect(sectors).toContainText("Sector impact · 1D");
    const moved = SECTOR_RETURNS.sectors.filter((s) => s.ret_1d_pct != null)
      .sort((a, b) => Math.abs(b.ret_1d_pct) - Math.abs(a.ret_1d_pct)).slice(0, 6).sort((a, b) => b.ret_1d_pct - a.ret_1d_pct);
    const tiles = sectors.getByTestId("desk-intel-sector-tile");
    await expect(tiles).toHaveCount(moved.length);
    const max = Math.max(...moved.map((s) => Math.abs(s.ret_1d_pct)));
    for (let i = 0; i < moved.length; i += 1) {
      const s = moved[i];
      await expect(tiles.nth(i)).toHaveAttribute("data-sector", s.sector);
      await expect(tiles.nth(i).getByTestId("desk-intel-sector-value")).toHaveText(pct(s.ret_1d_pct, 1));
      const p = Math.round(6 + (Math.abs(s.ret_1d_pct) / max) * 18);
      expect(await tiles.nth(i).getAttribute("style")).toContain(`${s.ret_1d_pct > 0 ? "var(--mint)" : "var(--cp-danger)"} ${p}%`);
    }
    expect(await sectors.locator(".grid").first().evaluate((e) => getComputedStyle(e).gridTemplateColumns.split(" ").length)).toBe(3);
    await expect(page.getByTestId("desk-intel-sectors-source")).toContainText(`Source: ${SECTOR_RETURNS.source}`);

    let o = await overflow(page);
    expect(o.doc).toBeLessThanOrEqual(1);
    expect(o.scroll).toBeLessThanOrEqual(1);
    // Every chip keeps the phone composition and fits.
    for (const key of ["results", "corporate", "regulatory", "flows", "deals"]) {
      await page.getByTestId(`desk-intel-chip-${key}`).click();
      await expect(page.getByTestId(`desk-intel-chip-${key}`)).toHaveAttribute("aria-pressed", "true");
      await expect(rows.first()).toBeVisible();
      o = await overflow(page);
      expect(o.doc).toBeLessThanOrEqual(1);
      expect(o.scroll).toBeLessThanOrEqual(1);
    }
    // A deal expanded on a phone: the plain explanation and the exchange's source.
    await rows.first().getByTestId("desk-event-toggle").click();
    await expect(rows.first().getByTestId("desk-event-noread")).toContainText("A bulk deal is one in which a client traded more than 0.5%");
    await expect(rows.first().getByTestId("desk-event-sources")).toContainText(DEALS.source);
    o = await overflow(page);
    expect(o.doc).toBeLessThanOrEqual(1);
    expect(o.scroll).toBeLessThanOrEqual(1);
  });

  test("fidelity screenshots: desktop 1440 with the dock, and 390", async ({ page }) => {
    const phase = "after";
    await page.setViewportSize({ width: 1440, height: 900 });
    await deskApi(page);
    await page.goto(`${DESK}?tab=intel`);
    await expect(page.getByTestId("desk-event-row").first()).toBeVisible();
    await page.waitForTimeout(400);
    await page.screenshot({ path: `${SHOTS}/fidelity-intel-${phase}-1440.png` });
    await page.locator(`[data-testid="desk-event-row"][data-id="${R_EARN.id}"]`).click();
    await page.waitForTimeout(200);
    await page.screenshot({ path: `${SHOTS}/fidelity-intel-${phase}-1440-filing.png` });

    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto(`${DESK}?tab=intel`);
    await expect(page.getByTestId("desk-event-row").first()).toBeVisible();
    await page.locator(`[data-testid="desk-event-row"][data-id="${R_EARN.id}"]`).getByTestId("desk-event-toggle").click();
    await page.waitForTimeout(400);
    await page.screenshot({ path: `${SHOTS}/fidelity-intel-${phase}-390.png` });
    await page.setViewportSize({ width: 390, height: 2400 });
    await page.waitForTimeout(300);
    await page.screenshot({ path: `${SHOTS}/fidelity-intel-${phase}-390-full.png` });
  });
});
