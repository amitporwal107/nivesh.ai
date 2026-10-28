/**
 * One-screen Copilot app (/v5/app) — Smart trading desk: Market intelligence (and the old Overview's remaining case).
 *
 * MOCK — not real data: every /api response here is an inline payload in the
 * shape the real route returns (the route is named beside each), with
 * synthetic values. Expected figures are worked out from the payload, not
 * copied from the screen. Mocked APIs, production build — see
 * pw.copilot-app.config.ts.
 *
 * Covers IntelTab.tsx (+ intel-data.ts), and the one old Overview case that still runs on the current desk (a question
 * typed in the desk search goes to the Copilot). The old Overview cards (OverviewTab.tsx) were deleted in the desk
 * redesign's step 6 with their cases; Market Overview's own spec covers their successors. Market intelligence: the
 * filings event list with its category chips, the row's exchange and the selected filing's read, bulk and block deals
 * from GET /api/markets/deals, SEBI circulars from GET /api/markets/circulars, the
 * linked stock against the scanner, FII / DII sessions, empty / failed / 403
 * states, and a 390px pass on both tabs.
 *
 * Market intelligence against the PRD (§6.1–§6.8, §12.4): All plus the twelve
 * categories (Macro disabled with its reason, the missing F&O ban / ASM / GSM
 * lists said), each filing's fields with both times and its source named (never
 * "verified"), the AI read apart from the sourced facts, NSE / BSE copies
 * consolidated as "2 sources", the event-to-stock impact (peers, the server's
 * indicators, the reaction from the bars, no past-reaction study), deals with %
 * of shares and the close around them, alerts created from an event and from the
 * list with the exact POST bodies and fired alerts listed with their reasons, the
 * sources line for everyone and the failing Intel feeds for admins only.
 */
import fs from "fs";
import path from "path";
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
const pct = (n: number, d = 2) => `${sgn(n)}${Math.abs(n).toFixed(d)}%`;
const int = (n: number) => Math.round(n).toLocaleString("en-IN");
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
//
// PRD §4 (OV-001 … OV-008, §4.4) on the desktop Overview, and the phone's M1. Payloads below are MOCK — not real data,
// in the shape of the route named beside each; expected figures are worked out from them in the test.

// backend/routes/macro.py :: macro_today → `regime` (services/macro_engine.py :: classify_desk_regime). Thresholds that are
// NOT the production defaults (22.5 / 55 / 45), so the card is shown to read them from the payload.
const RULE_X = { version: "desk-regime-fixture", vix_high: 22.5, trend_average_sessions: 50, breadth_up_pct: 55, breadth_down_pct: 45 };
type Flip = { input: string; condition: string; level: number; then: string };
function regime(key: string | null, i: { nifty: number | null; avg: number | null; vix: number | null; adv: number | null; dec: number | null; trend: string | null; breadth: string | null }, invalidation: Flip[], extra: Record<string, unknown> = {}) {
  const share = i.adv != null && i.dec != null ? Math.round((i.adv / (i.adv + i.dec)) * 1000) / 10 : null;
  return {
    key, label: key, date: "2026-10-13", rule: RULE_X,
    inputs: {
      nifty_close: i.nifty, nifty_average: i.avg, nifty_vs_average_pct: i.nifty != null && i.avg ? Math.round((i.nifty / i.avg - 1) * 10000) / 100 : null,
      trend: i.trend, india_vix: i.vix, volatility_high: i.vix == null ? null : i.vix >= RULE_X.vix_high,
      advances: i.adv, declines: i.dec, unchanged: 40, breadth_universe: i.adv != null && i.dec != null ? i.adv + i.dec + 40 : null,
      advancing_share_pct: share, breadth: i.breadth, breadth_date: "2026-10-13", breadth_source: "stock_ohlcv end-of-day bars (NSE bhavcopy)",
    },
    skipped: [], invalidation, reason: null, ...extra,
  };
}

// The old Overview cards (tradingdesk/OverviewTab.tsx) left the desk in step 2 (Market Overview) and were deleted in step 6,
// with their cases (TC-3 … TC-12, OV-005 … OV-008, §3.2). Market Overview's strip and events replace them
// (copilot-app-desk-market-overview.spec.ts: MO-2 … MO-9, MO-2b … MO-2d for the Kite close, MO-24, MO-30, and MO-33 / MO-34
// for a failed market or sector read). The case below runs on the current desk.
test.describe("Smart trading desk — Overview", () => {
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
// Design-spec §6 and PRD §6: one event list (newest first) and a detail panel; chips All plus the PRD's twelve
// categories. Ids: a filing keeps its own id (a consolidated NSE / BSE pair keeps the NSE one); the other sources are
// "fiidii-<date>", "deal-<date>-<kind>-<symbol>-<i>", "sebi-<date>-<i>" (i = position in the list the chip takes)
// and "sector-<index>-<date>".

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

// ── Market intelligence payloads (PRD §6) ────────────────────────────────

/** An India date-time as the screen writes it: "13 Oct 2026, 09:12 IST". */
const istFull = (iso: string) => {
  const d = new Date(iso);
  const day = d.toLocaleDateString("en-IN", { timeZone: "Asia/Kolkata", day: "numeric", month: "short", year: "numeric" });
  const time = d.toLocaleTimeString("en-IN", { timeZone: "Asia/Kolkata", hour: "2-digit", minute: "2-digit", hour12: false });
  return `${day}, ${time} IST`;
};

// backend/routes/filings.py :: filings_feed?provenance=1 — each row merged with DaaS /v1/desk/event-sources
// (nidp/services/daas_api/routers/desk_market.py :: event_sources).
const PEERS = [
  { symbol: "PEERONE", name: "Peer One Ltd.", largest_index: "Nifty 50" },
  { symbol: "PEERTWO", name: "Peer Two Ltd.", largest_index: "Nifty 100" },
];
const record = (id: string, source: string, subject: string, url: string | null, published: string, ingested: string) => ({
  announcement_id: id, source, company: "Test Pick Industries Ltd", subject, url, published_at: published, broadcast_at: null,
  ingested_at: ingested, classified_at: null, classifier_version: source === "NSE_ANN" ? "fixture-v3" : null,
});
const PROV_EARN = {
  published_at: "2026-10-13T03:42:00+00:00", ingested_at: "2026-10-13T04:00:05+00:00", broadcast_at: "2026-10-13T03:41:59+00:00",
  nse_symbol: "TESTPICK", resolution: "exchange_symbol", timing_type: "pre_market", known_at_open_session: "2026-10-13",
  known_by_close_session: "2026-10-13", primary_row: true, sector: "Capital Goods",
  sector_source: "NSE index list (Nifty Total Market, 2026-10-13)", peers: PEERS, classifier_version: "fixture-v3", classified_at: null,
  records: [record("ann-001", "NSE_ANN", R_EARN.docLabel as string, R_EARN.url as string, "2026-10-13T03:42:00+00:00", "2026-10-13T04:00:05+00:00")],
};
const P_EARN = { ...R_EARN, ...PROV_EARN };
/** The BSE copy of the same results filing, 3 minutes later, unclassified, resolved to TESTPICK through the scrip bridge. */
const P_EARN_BSE = row("bse-001", {
  ticker: null, code: null, name: "Test Pick Industries Ltd", date: "2026-10-13T09:15:00+05:30", category: "Markets",
  docLabel: "Results for the quarter ended September 2026", url: "https://www.bseindia.com/xml-data/fixture-b01.pdf", exchange: "BSE",
  ...PROV_EARN, published_at: "2026-10-13T03:45:00+00:00", ingested_at: "2026-10-13T04:20:00+00:00", resolution: "bse_scrip_isin_bridge",
  primary_row: false,
  records: [record("bse-001", "BSE_ANN", "Results for the quarter ended September 2026", "https://www.bseindia.com/xml-data/fixture-b01.pdf", "2026-10-13T03:45:00+00:00", "2026-10-13T04:20:00+00:00")],
});
const P_ORDER = { ...R_ORDER, ingested_at: null, records: null, peers: [], sector: null };
const P_LIT = { ...R_LIT, ingested_at: "2026-10-11T06:00:00+00:00", sector: null, peers: [] };
// The exchange-subject families (DaaS /v1/desk/filings, the articles shape).
const C_CALL = row("ann-020", {
  ticker: "TESTCALL", code: "TESTCALL", name: "Test Calls Ltd", date: "2026-10-13T16:05:00+05:30", category: "Regulatory",
  docLabel: "Analysts/Institutional Investor Meet/Con. Call Updates", url: "https://nsearchives.nseindia.com/corporate/fixture-020.pdf", exchange: "NSE",
});
const X_SPURT = row("ann-030", {
  ticker: "TESTSPRT", code: "TESTSPRT", name: "Test Spurt Ltd", date: "2026-10-12T11:30:00+05:30", category: "Regulatory",
  docLabel: "Spurt in Volume", url: null, exchange: "NSE",
});
const INTEL_FEEDS: Record<string, unknown> = {
  "": feed([P_EARN_BSE, P_EARN, P_ORDER, P_LIT], 57),
  earnings: feed([P_EARN], 21),
  orders: feed([P_ORDER], 9),
  litigation: feed([P_LIT], 1),
  mna: feed([R_MNA], 2),
  "family:calls": { ...feed([C_CALL], 1), family: { key: "calls", patterns: ["%Con. Call%"], source: "fixture" } },
  "family:ownership": feed([], 0),
  "family:exchange": { ...feed([X_SPURT], 1), family: { key: "exchange", patterns: ["%Spurt in Volume%"], source: "fixture" } },
};

// The deals route with the B9 enrichment (desk_market.py :: deal_row): % of shares = quantity ÷ total shares × 100,
// the stock's close that day, the previous and the next close, the deal price against the close, the ingestion time.
const DEALS_RICH = {
  ...DEALS,
  disclosure: "Every row is NSE's own bulk or block deal disclosure, published after the close. No institutional activity is inferred here.",
  rows: [
    { ...DEALS.rows[0], total_shares: 50_000_000, shares_period_end: "2026-06-30", pct_of_shares: (250000 / 50_000_000) * 100, close_on_day: 1215.0,
      prev_close: 1190.0, next_date: null, next_close: null, price_vs_close_pct: -0.39, ingested_at: "2026-10-13T14:00:00+00:00", disclosure: "exchange" },
    { ...DEALS.rows[1], total_shares: null, shares_period_end: null, pct_of_shares: null, close_on_day: 412.0, prev_close: 405.0,
      next_date: "2026-10-14", next_close: 418.5, price_vs_close_pct: -0.36, ingested_at: "2026-10-13T14:00:00+00:00", disclosure: "exchange" },
    { ...DEALS.rows[2], ingested_at: null, disclosure: "exchange" },
  ],
};

// backend/routes/research_chart_live.py: the server's indicators (useLiveIndicators) and the adjusted daily bars.
const INDICATORS = {
  symbol: "TESTPICK", as_of: "2026-10-13", sessions: 250, source: "nidp.prices_eod_adjusted", mode: "eod",
  method: "technical_indicator_engine.calculator",
  values: { close: 512.4, ema20: 498.2, ema50: 470.15, ema200: null, rsi14: 61.3, atr14: null, atr_pct: null, macd: null, macd_signal: null, macd_hist: null,
    roc20: null, avg_volume20: null, rvol20: 1.85, vwap20: null, resistance20: null, support20: null, avg_traded_value_cr20: null, rs63: null },
  series: { days: [], ema20: [], ema50: [], ema200: [], vwap20: [] },
  definitions: [], benchmark: { name: "Nifty 50" }, tradability: null,
};
const OHLCV = {
  bars: [["2026-10-09", 495, 500, 490, 498.0, 100000], ["2026-10-12", 498, 507, 497, 505.0, 120000], ["2026-10-13", 506, 515, 504, 512.4, 210000]],
  data_quality_status: "OK", provenance: { provider: "nidp.prices_eod_adjusted", last_bar_date: "2026-10-13" },
};

// backend/routes/desk_trading.py :: list_alerts (services/desk_alerts.py): a fired filing alert with its reason.
const FIRED = {
  id: "al-1", symbol: "TESTORD", condition: "filing", level: null, params: { impact: "any" }, label: "TESTORD: a new exchange filing",
  rule: "The stock's first exchange filing (NSE or BSE) filed after the alert was made.", note: null, created_at: "2026-10-12T04:00:00+00:00",
  status: "fired", fired_at: "2026-10-13T12:00:00+00:00", fired_session: "2026-10-12", fired_price: null,
  reason: "TESTORD filed “Bagging of an order” with BSE at 15:40 IST on 12 Oct 2026.",
  evidence: { announcement_id: "ann-002", url: "https://www.bseindia.com/xml-data/fixture-002.pdf" }, check_error: null, checked_through: null,
  last_close: null, last_close_date: null, mark_error: null,
};
const CHECK_NOTE = "Checked when you open the alerts and once each weekday evening; shown in this list only (in-app). Counted from the first session after the day the alert was made; a filing counts from the moment it was made.";

// backend/routes/admin_nidp.py :: feeds_live (admins only).
const FEEDS_LIVE = {
  generated_at: "2026-10-14T10:00:00+00:00", last_trading_day: "2026-10-14",
  summary: { total: 4, healthy: 2, failing: 2, stale: 0, never_run: 0, running: 0 },
  feeds: [
    { ingester: "corporate_announcements_bse", freshness_state: "failing", last_success_at: "2026-10-13T03:43:30+00:00", last_run_status: "FAILED" },
    { ingester: "amfi_nav", freshness_state: "failing", last_success_at: null, last_run_status: "FAILED" },
    { ingester: "corporate_announcements_nse", freshness_state: "healthy", last_success_at: "2026-10-14T09:00:00+00:00", last_run_status: "OK" },
    { ingester: "bulk_deals", freshness_state: "healthy", last_success_at: "2026-10-13T14:00:00+00:00", last_run_status: "OK" },
  ],
  db_error: null,
};

interface IntelCalls { feed: URL[]; posts: Array<Record<string, unknown>>; deletes: string[]; feedsLive: number; indicators: string[] }

/** deskApi plus the Market intelligence reads: filings with provenance and families, the enriched deals, the chart
 * reads behind the technical check, the alerts (a small in-memory store) and the admin feed status. */
async function intelApi(page: Page, over: {
  feed?: Reply; deals?: Reply; alerts?: unknown[]; postReply?: (body: Record<string, unknown>) => Reply | null; feedsLive?: Reply; notAdmin?: boolean;
} = {}): Promise<IntelCalls> {
  await deskApi(page);
  const calls: IntelCalls = { feed: [], posts: [], deletes: [], feedsLive: 0, indicators: [] };
  const store: Array<Record<string, unknown>> = [...((over.alerts ?? [FIRED]) as Array<Record<string, unknown>>)];
  await page.route("**/api/filings/feed*", (route) => {
    const u = new URL(route.request().url());
    calls.feed.push(u);
    if (over.feed) return json(route, over.feed.body, over.feed.status);
    const fam = u.searchParams.get("family");
    return json(route, INTEL_FEEDS[fam ? `family:${fam}` : u.searchParams.get("category") ?? ""] ?? feed([], 0));
  });
  await page.route("**/api/markets/deals*", (route) => (over.deals ? json(route, over.deals.body, over.deals.status) : json(route, DEALS_RICH)));
  await page.route("**/api/research/chart/live/*/indicators", (route) => {
    const sym = new URL(route.request().url()).pathname.split("/").slice(-2)[0];
    calls.indicators.push(sym);
    return sym === "TESTPICK" ? json(route, INDICATORS) : json(route, { detail: "no bars" }, 404);
  });
  await page.route("**/api/research/chart-live/*/ohlcv*", (route) =>
    (new URL(route.request().url()).pathname.includes("/TESTPICK/") ? json(route, OHLCV) : json(route, { detail: "no bars" }, 404)));
  await page.route("**/api/desk/alerts**", (route) => {
    const req = route.request();
    if (req.method() === "GET") {
      return json(route, { as_of: "2026-10-13", checked_through: "2026-10-13", alerts: store, check_errors: [], check_note: CHECK_NOTE, delivery: "in_app",
        conditions: [{ condition: "filing", rule: "The stock's first exchange filing (NSE or BSE) filed after the alert was made." }] });
    }
    if (req.method() === "POST") {
      const body = req.postDataJSON() as Record<string, unknown>;
      calls.posts.push(body);
      const forced = over.postReply?.(body);
      if (forced) return json(route, forced.body, forced.status);
      const { condition, symbol, level, ...params } = body;
      const alert = { id: `al-new-${calls.posts.length}`, symbol: symbol ?? null, condition, level: level ?? null, params, label: `${symbol ?? "Any company"}: ${String(condition)}`,
        rule: "fixture rule", note: null, created_at: "2026-10-13T10:00:00+00:00", status: "active", fired_at: null, fired_session: null, fired_price: null,
        reason: null, evidence: null, check_error: null, checked_through: null, last_close: null, last_close_date: null, mark_error: null };
      store.unshift(alert);
      return json(route, { alert }, 201);
    }
    if (req.method() === "DELETE") {
      const id = decodeURIComponent(new URL(req.url()).pathname.split("/").pop() ?? "");
      calls.deletes.push(id);
      const i = store.findIndex((a) => a.id === id);
      if (i >= 0) store.splice(i, 1);
      return route.fulfill({ status: 204, body: "" });
    }
    return route.fallback();
  });
  await page.route("**/api/admin/nidp/feeds/live", (route) => {
    calls.feedsLive += 1;
    return over.feedsLive ? json(route, over.feedsLive.body, over.feedsLive.status) : json(route, FEEDS_LIVE);
  });
  if (over.notAdmin) {
    await page.route("**/api/auth/me", (route) => json(route, { user_id: "u_plain", email: "user@example.test", name: "Fixture User", is_admin: false, onboarding_completed: true }));
  }
  return calls;
}

const CHIP_LABELS = ["All", "Announcements", "Results", "Calls & guidance", "Orders", "M&A & actions", "Ownership", "Bulk & block", "FII / DII", "Regulatory", "Sector", "Macro", "Exchange notices"];
const evRow = (page: Page, id: string) => page.locator(`[data-testid="desk-event-row"][data-id="${id}"]`);

test.describe("Smart trading desk — Market intelligence", () => {
  test("§6 frame: 04 · AI Event intelligence, its meta, All plus the PRD's twelve categories, a two-pane list and detail", async ({ page }) => {
    const calls = await intelApi(page);
    await page.route("**/api/positional/picks*", (route) => json(route, PICKS_SPARK));
    await page.goto(`${DESK}?tab=intel`);
    await expect(page.getByTestId("desk-intel-title")).toHaveText("AI Event intelligence");   // no leftover "04 ·" (desk audit wave 1)
    await expect(page.getByTestId("desk-intel-meta")).toHaveText("NSE · BSE · SEBI · linked to the scanner");
    await expect(page.getByRole("group", { name: "Event type" }).getByRole("button")).toHaveText(CHIP_LABELS);
    await expect(page.getByTestId("desk-intel-chip-all")).toHaveAttribute("aria-pressed", "true");

    // All: every source, newest first; the NSE and BSE copies of one filing are one event; 12 listed, then "Show more".
    const order = expectedAll();
    const rows = page.getByTestId("desk-event-row");
    await expect(rows).toHaveCount(12);
    expect(await rows.evaluateAll((els) => els.map((e) => e.getAttribute("data-id")))).toEqual(order.slice(0, 12));
    await expect(page.getByTestId("desk-intel-count")).toHaveText(
      `12 of ${order.length} events · newest first · 3 filings (4 records; repeats consolidated) of 57 in the last 7 days, the ${DEALS.rows.length} largest deals of the last 5 days, the ${CIRCULARS.rows.length} latest SEBI circulars, the 5 latest FII / DII sessions`,
    );
    await page.getByTestId("desk-intel-more").click();
    await expect(rows).toHaveCount(order.length);
    // The filings request asks for provenance; deals and circulars are read for All.
    expect(calls.feed[0].searchParams.get("category")).toBeNull();
    expect([calls.feed[0].searchParams.get("days"), calls.feed[0].searchParams.get("sort"), calls.feed[0].searchParams.get("provenance")]).toEqual(["7", "latest", "1"]);

    // Row grid 62px | text | right column; the detail panel sits beside the list.
    const first = rows.nth(0);
    expect(await first.evaluate((e) => getComputedStyle(e).gridTemplateColumns.split(" ")[0])).toBe("62px");
    await expect(first).toHaveAttribute("aria-pressed", "true");
    const detail = page.getByTestId("desk-event-detail");
    await expect(detail).toHaveAttribute("data-id", order[0]);
    const [listBox, detailBox] = [await page.getByTestId("desk-event-list").boundingBox(), await detail.boundingBox()];
    expect((detailBox?.x ?? 0)).toBeGreaterThan((listBox?.x ?? 0) + (listBox?.width ?? 0) - 2);

    // A filing row: type, title, the generated read as its sub, the AI pill (never a bullish / bearish word), the stock
    // with its icon, its 1-day change from the scanner's closes ((512.40 − 505) ÷ 505) and "2 sources".
    const earn = evRow(page, R_EARN.id);
    await expect(earn.getByTestId("desk-event-type")).toHaveText("Results");
    expect(await earn.getByTestId("desk-event-type").getAttribute("style")).toContain("var(--cp-indigo)");
    await expect(earn.getByTestId("desk-event-title")).toHaveText(R_EARN.docLabel as string);
    await expect(earn.getByTestId("desk-event-sub")).toHaveText(R_EARN.one as string);
    await expect(earn.getByTestId("desk-event-sentiment")).toHaveText("AI read · not verified");
    await expect(earn.getByTestId("desk-event-sentiment")).toHaveAttribute("data-sentiment", "positive");
    await expect(earn.getByTestId("desk-event-sentiment")).not.toHaveAttribute("data-tone", /.+/);
    await expect(earn.getByTestId("desk-event-sources-count")).toHaveText("2 sources");
    await expect(earn.getByTestId("desk-event-stock")).toHaveText("TESTPICK");
    await expect(earn.locator('[data-testid="entity-icon"]')).toHaveAttribute("data-key", "TESTPICK");
    await expect(earn.getByTestId("desk-event-change")).toHaveText(pct(((512.4 - 505) / 505) * 100));
    await expect(evRow(page, "bse-001")).toHaveCount(0);
    await expect(evRow(page, R_ORDER.id).getByTestId("desk-event-change")).toHaveText("—");
    await expect(evRow(page, R_ORDER.id).getByTestId("desk-event-type")).toHaveText("Corporate · Order");
    // Litigation is "Regulatory and judicial" (PRD §6.2), amber.
    await expect(evRow(page, R_LIT.id).getByTestId("desk-event-type")).toHaveText("Regulatory · Litigation");
    expect(await evRow(page, R_LIT.id).getByTestId("desk-event-type").getAttribute("style")).toContain("var(--amber)");

    // FII / DII: no AI pill (no classification exists); the change slot carries the FII net flow.
    const f0 = FLOWS.daily[0];
    const flow = evRow(page, `fiidii-${f0.date}`);
    await expect(flow.getByTestId("desk-event-title")).toHaveText(`${flowWords("FIIs", f0.fii_net)} · ${flowWords("DIIs", f0.dii_net)}`);
    await expect(flow.getByTestId("desk-event-sentiment")).toHaveCount(0);
    await expect(flow.getByTestId("desk-event-change")).toHaveText(`FII ${sgn(f0.fii_net)}${flowCr(f0.fii_net)}`);

    // A deal: who, side and quantity; kind, value and average price (rose).
    const d0 = DEALS.rows[0];
    const deal = evRow(page, `deal-${d0.date}-${d0.kind}-${d0.symbol}-0`);
    await expect(deal.getByTestId("desk-event-type")).toHaveText("Block deal");
    expect(await deal.getByTestId("desk-event-type").getAttribute("style")).toContain("var(--rose)");
    await expect(deal.getByTestId("desk-event-title")).toHaveText(`${d0.client_name} sold ${lakhQty(d0.quantity)} shares`);
    await expect(deal.getByTestId("desk-event-sub")).toHaveText(`Block deal · ₹${d0.value_cr.toFixed(2)} Cr · at ₹${level(d0.avg_price)} average`);

    // The card's trust line: the sources, delayed (filings are fetched on a schedule), as reported, the last ingestion.
    const trust = page.getByTestId("desk-intel-trust");
    await expect(trust).toHaveText(`Exchange filings (NSE, BSE) · NSE deals · SEBI · NSE FII / DII · Delayed · last ingested ${istFull("2026-10-13T04:20:00+00:00")} · As reported · AI reads are labelled where shown`);
    await expect(trust).toHaveAttribute("data-maker", "reported");
  });

  test("§6.3 / §6.8 a filing's fields: ID, both times, source named not verified, sector with its source, AI read apart from the facts", async ({ page }) => {
    await intelApi(page);
    await page.goto(`${DESK}?tab=intel`);
    const detail = page.getByTestId("desk-event-detail");
    await evRow(page, R_EARN.id).click();
    await expect(detail).toHaveAttribute("data-id", R_EARN.id);
    await expect(detail.getByTestId("desk-event-detail-meta")).toHaveText("Results · 13 Oct 2026, 09:12 IST");
    await expect(detail.getByTestId("desk-event-detail-title")).toHaveText(R_EARN.docLabel as string);
    expect(await detail.getByTestId("desk-event-detail-title").evaluate((e) => [getComputedStyle(e).fontSize, getComputedStyle(e).fontFamily])).toEqual(["26px", expect.stringContaining("Instrument Serif")]);
    // The source, never "verified".
    await expect(detail.getByTestId("desk-event-source-label")).toHaveText("Exchange filing (NSE)");
    // Nothing claims "verified": the only use of the word is the AI read's own "not verified".
    expect(((await detail.textContent()) ?? "").replace(/not verified/gi, "")).not.toMatch(/verified/i);

    // Sourced facts, from the payload.
    await expect(detail.getByTestId("desk-event-fact-id")).toHaveText(R_EARN.id);
    await expect(detail.getByTestId("desk-event-fact-source")).toHaveText("Exchange filing (NSE) · 2 sources");
    await expect(detail.getByTestId("desk-event-fact-company")).toHaveText(`${R_EARN.name} · TESTPICK`);
    await expect(detail.getByTestId("desk-event-fact-published")).toHaveText(istFull(PROV_EARN.published_at));
    await expect(detail.getByTestId("desk-event-fact-ingested")).toHaveText(istFull(PROV_EARN.ingested_at));
    await expect(detail.getByTestId("desk-event-facts")).toContainText("when Nivesh last fetched it; a first-seen time is not stored");
    await expect(detail.getByTestId("desk-event-fact-category")).toHaveText("Results");
    await expect(detail.getByTestId("desk-event-fact-sector")).toHaveText(PROV_EARN.sector);
    await expect(detail.getByTestId("desk-event-facts")).toContainText(PROV_EARN.sector_source);
    await expect(detail.getByTestId("desk-event-fact-timing")).toHaveText("Filed before the market opened; the first session whose open can reflect it is 13 Oct 2026.");

    // The AI read, in its own box: summary, the figures the generator extracted, the classifier's labels said to be AI.
    const ai = detail.getByTestId("desk-event-ai");
    await expect(ai).toContainText("AI read · not verified");
    await expect(ai.getByTestId("desk-event-why")).toHaveText(R_EARN.one as string);
    await expect(ai.getByTestId("desk-event-ai-extracted")).toHaveText(`Extracted by AI: Period ${R_EARN.period} · Headline figure ${R_EARN.metric}`);
    await expect(ai.getByTestId("desk-event-ai-labels")).toHaveText("Tone: Positive · Importance: High · labels from the announcement classifier, not checked against the price and not a buy or sell direction.");
    await expect(ai.getByTestId("desk-event-ai-trust")).toHaveAttribute("data-maker", "ai");
    // The facts carry none of the AI's words; the plain "why" is rules text.
    await expect(detail.getByTestId("desk-event-facts")).not.toContainText(R_EARN.one as string);
    await expect(detail.getByTestId("desk-event-plain")).toHaveText("Quarterly results move a stock when revenue, margins or guidance differ from what was expected.");

    // §6.4: both source records are kept and listed.
    const src = detail.getByTestId("desk-event-sources").locator("li");
    await expect(src).toHaveCount(2);
    await expect(src.nth(0)).toHaveText(`[1]Filed with NSE · ${R_EARN.docLabel} ↗`);
    await expect(src.nth(1)).toHaveText(`[2]Filed with BSE · ${P_EARN_BSE.docLabel} ↗`);
    await expect(detail.getByTestId("desk-event-doc")).toHaveAttribute("href", R_EARN.url as string);
    await expect(detail.getByTestId("desk-event-doc-more")).toHaveAttribute("href", P_EARN_BSE.url as string);

    // A filing without an AI read says so; its exchange comes from its link.
    await evRow(page, R_ORDER.id).click();
    await expect(detail.getByTestId("desk-event-source-label")).toHaveText("Exchange filing (BSE)");
    await expect(detail.getByTestId("desk-event-ai")).toContainText("AI read · not verified");
    await expect(detail.getByTestId("desk-event-why")).toHaveCount(0);
    await expect(detail.getByTestId("desk-event-fact-ingested")).toHaveText("—");
    await expect(detail.getByTestId("desk-event-fact-sector")).toHaveText("—");
  });

  test("§6.5 impact: the stock with its scan rank, related companies, the technical check from the indicator route, the reaction from the bars, no past-reaction study", async ({ page }) => {
    const calls = await intelApi(page);
    await page.goto(`${DESK}?tab=intel`);
    const detail = page.getByTestId("desk-event-detail");
    await evRow(page, R_EARN.id).click();
    const impact = detail.getByTestId("desk-event-impact");
    await expect(impact.getByTestId("desk-event-linked")).toContainText("TESTPICK");
    await expect(impact.getByTestId("desk-event-linked")).toHaveAttribute("data-tone", "indigo");
    await expect(impact.getByTestId("desk-event-scanner")).toContainText("TESTPICK is #1 of 3 in today’s scan.");
    await expect(impact.getByTestId("desk-event-sector")).toHaveText(PROV_EARN.sector);
    const peers = impact.getByTestId("desk-event-peer");
    expect(await peers.evaluateAll((els) => els.map((e) => e.getAttribute("data-symbol")))).toEqual(PEERS.map((p) => p.symbol));
    await expect(peers.nth(0).locator('[data-testid="entity-icon"]')).toHaveAttribute("data-key", PEERS[0].symbol);
    // Technical check: the server's values, worded from the payload.
    const v = INDICATORS.values;
    await expect(impact.getByTestId("desk-event-tech")).toHaveText(
      `Close ₹${level(v.close)} on 13 Oct 2026: above its 20-day EMA (₹${level(v.ema20)}), above its 50-day EMA (₹${level(v.ema50)}); RSI 14 ${v.rsi14.toFixed(1)}; volume ${v.rvol20.toFixed(2)}× its 20-session average.`,
    );
    expect(calls.indicators).toContain("TESTPICK");
    // The first session whose open could reflect a pre-market filing on 13 Oct: 512.40 vs 505.00.
    await expect(impact.getByTestId("desk-event-reaction")).toHaveText(`Move on 13 Oct 2026 (the first session whose open could reflect the filing): ${pct(((512.4 / 505) - 1) * 100)}, close to close.`);
    await expect(impact.getByTestId("desk-event-tech-trust")).toHaveAttribute("data-maker", "rules");
    await expect(impact.getByTestId("desk-event-history")).toContainText("— No study of how prices reacted to this kind of event is published yet");
    // A peer opens its chart.
    await peers.nth(1).click();
    await expect(page.getByTestId("screen-trading-desk")).toHaveAttribute("data-view", "chart"); // the chart is Trade Desk › Chart Analysis › Live chart (the owner's design)
    await expect(page).toHaveURL(/[?&]sym=PEERTWO/);
  });

  test("§6.6 deals: share of the company, the close around the deal, a confirmed exchange disclosure, ingestion time", async ({ page }) => {
    await intelApi(page);
    await page.goto(`${DESK}?tab=intel`);
    await page.getByTestId("desk-intel-chip-deals").click();
    const d = DEALS_RICH.rows[0];
    await evRow(page, `deal-${d.date}-${d.kind}-${d.symbol}-0`).click();
    const box = page.getByTestId("desk-event-detail").getByTestId("desk-event-deal");
    await expect(box.getByTestId("desk-deal-confirmed")).toHaveText("Confirmed · exchange disclosure");
    await expect(box).toContainText("Seller");
    await expect(box.getByTestId("desk-deal-client")).toHaveText(d.client_name);
    await expect(box.getByTestId("desk-deal-qty")).toHaveText(`${int(d.quantity)} shares`);
    await expect(box.getByTestId("desk-deal-price")).toHaveText(`₹${level(d.avg_price)}`);
    await expect(box.getByTestId("desk-deal-value")).toHaveText(`₹${d.value_cr.toFixed(2)} Cr`);
    await expect(box.getByTestId("desk-deal-pct")).toHaveText(`${((d.quantity / (d.total_shares as number)) * 100).toFixed(2)}%`);
    await expect(box).toContainText("of total shares, shareholding pattern 30 Jun 2026");
    await expect(box.getByTestId("desk-deal-close")).toHaveText(`₹${level(d.close_on_day as number)}`);
    await expect(box).toContainText(`previous close ₹${level(d.prev_close as number)}`);
    await expect(box.getByTestId("desk-deal-vs-close")).toHaveText(pct(d.price_vs_close_pct as number));
    await expect(box.getByTestId("desk-deal-next")).toHaveText("—");
    await expect(box.getByTestId("desk-deal-inferred")).toContainText("no institutional activity is inferred");
    const detail = page.getByTestId("desk-event-detail");
    await expect(detail.getByTestId("desk-event-source-label")).toHaveText("Exchange disclosure (NSE)");
    await expect(detail.getByTestId("desk-event-fact-ingested")).toHaveText(istFull(d.ingested_at as string));
    // A deal with no shareholding pattern on record: "—" with the reason; the next session's close when it exists.
    const d1 = DEALS_RICH.rows[1];
    await evRow(page, `deal-${d1.date}-${d1.kind}-${d1.symbol}-1`).click();
    await expect(box.getByTestId("desk-deal-pct")).toHaveText("—");
    await expect(box).toContainText("no shareholding pattern on record for the share count");
    await expect(box.getByTestId("desk-deal-next")).toHaveText(`₹${level(d1.next_close as number)} (14 Oct 2026)`);
  });

  test("§6.2 chips read their real sources; Macro is disabled with its reason; F&O ban and ASM / GSM are said to be missing", async ({ page }) => {
    const calls = await intelApi(page);
    await page.goto(`${DESK}?tab=intel`);
    const rows = page.getByTestId("desk-event-row");
    await expect(rows).toHaveCount(12);
    const ids = () => rows.evaluateAll((els) => els.map((e) => e.getAttribute("data-id")));
    const cats = () => calls.feed.map((u) => u.searchParams.get("category"));
    const fams = () => calls.feed.map((u) => u.searchParams.get("family"));

    await page.getByTestId("desk-intel-chip-results").click();
    await expect.poll(cats).toContain("earnings");
    await expect(rows).toHaveCount(1);
    expect(await ids()).toEqual([R_EARN.id]);

    await page.getByTestId("desk-intel-chip-announcements").click();
    await expect.poll(cats).toEqual(expect.arrayContaining(["management", "capex", "qip", "rating"]));
    await expect(page.getByTestId("desk-intel-empty")).toBeVisible();

    await page.getByTestId("desk-intel-chip-mna").click();
    await expect.poll(cats).toEqual(expect.arrayContaining(["mna", "dividend", "buyback"]));
    await expect(rows).toHaveCount(1);
    await expect(rows.nth(0).getByTestId("desk-event-type")).toHaveText("Corporate · M&A");

    await page.getByTestId("desk-intel-chip-calls").click();
    await expect.poll(fams).toContain("calls");
    await expect(rows).toHaveCount(1);
    await expect(rows.nth(0).getByTestId("desk-event-type")).toHaveText("Call / guidance");
    await expect(rows.nth(0).getByTestId("desk-event-title")).toHaveText(C_CALL.docLabel as string);

    await page.getByTestId("desk-intel-chip-ownership").click();
    await expect.poll(fams).toContain("ownership");
    await expect(page.getByTestId("desk-intel-missing")).toContainText("nidp.insider_sast is empty");

    await page.getByTestId("desk-intel-chip-exchange").click();
    await expect.poll(fams).toContain("exchange");
    await expect(rows).toHaveCount(1);
    await expect(rows.nth(0).getByTestId("desk-event-type")).toHaveText("Exchange query");
    await expect(page.getByTestId("desk-intel-missing")).toContainText("F&O ban lists and ASM / GSM surveillance lists are not ingested");

    await page.getByTestId("desk-intel-chip-regulatory").click();
    await expect.poll(cats).toEqual(expect.arrayContaining(["regulatory", "litigation"]));
    await expect(rows).toHaveCount(1 + CIRCULARS.rows.length);

    // Sector: the indices that closed 1% or more either way in their last session (|1.42| and |−1.60| here), newest first.
    await page.getByTestId("desk-intel-chip-sector").click();
    const moved = SECTOR_RETURNS.sectors.filter((s) => Math.abs(s.ret_1d_pct) >= 1).sort((a, b) => b.date.localeCompare(a.date));
    await expect(rows).toHaveCount(moved.length);
    expect(await ids()).toEqual(moved.map((s) => `sector-${s.index}-${s.date}`));
    await expect(rows.nth(0).getByTestId("desk-event-title")).toHaveText(`${moved[0].index} rose ${moved[0].ret_1d_pct.toFixed(2)}%`);
    await expect(page.getByTestId("desk-intel-missing")).toContainText("No sector news feed is ingested");

    // Macro: disabled, with the reason, and nothing is read for it.
    const before = calls.feed.length;
    await page.getByTestId("desk-intel-chip-macro").click();
    await expect(page.getByTestId("desk-intel-chip-macro")).toHaveAttribute("data-disabled", "true");
    await expect(page.getByTestId("desk-intel-disabled")).toContainText("No macro-economic calendar (RBI policy, inflation, GDP dates) is ingested");
    expect(calls.feed.length).toBe(before);

    await page.getByTestId("desk-intel-chip-flows").click();
    const ten = [...FLOWS.daily].sort((a, b) => b.date.localeCompare(a.date)).slice(0, 10);
    await expect(rows).toHaveCount(10);
    expect(await ids()).toEqual(ten.map((f) => `fiidii-${f.date}`));

    await page.getByTestId("desk-intel-chip-deals").click();
    await expect(rows).toHaveCount(DEALS.rows.length);
    await expect(page.getByTestId("desk-intel-count")).toHaveText(`3 of 3 events · newest first · ${DEALS.rows.length} deals over 5 calendar days`);
  });

  test("§6.7 alerts: create from the event and from the list, the exact POST bodies, fired alerts listed with their reasons, a duplicate refused, delete", async ({ page }) => {
    const calls = await intelApi(page, {
      postReply: (b) => (b.condition === "volume" ? { status: 409, body: { detail: "duplicate_alert" } } : null),
    });
    await page.goto(`${DESK}?tab=intel`);
    // The in-app list: the fired alert first, with the route's reason and the filing it fired on.
    const card = page.getByTestId("desk-intel-alerts");
    const fired = card.locator(`[data-testid="desk-intel-alert"][data-id="${FIRED.id}"]`);
    await expect(fired.getByTestId("desk-intel-alert-label")).toHaveText(FIRED.label);
    await expect(fired.getByTestId("desk-intel-alert-status")).toHaveText("Fired 12 Oct 2026");
    await expect(fired.getByTestId("desk-intel-alert-reason")).toHaveText(`${FIRED.reason} Filing ↗`);
    await expect(fired.getByRole("link", { name: "Filing ↗" })).toHaveAttribute("href", FIRED.evidence.url);
    await expect(card.getByTestId("desk-intel-alerts-note")).toHaveText(`${CHECK_NOTE} Nothing is emailed or sent to your phone.`);

    // From the event: a new filing by the stock, then a volume alert the route refuses as a duplicate.
    await evRow(page, R_EARN.id).click();
    const alerts = page.getByTestId("desk-event-detail").getByTestId("desk-event-alerts");
    await expect(alerts.getByRole("button")).toHaveText(["New filing by TESTPICK", "Next results by TESTPICK", "Next bulk / block deal in TESTPICK", "Volume ≥ 2× average", "Enters the scanner", "ATR ≥ 4% of price"]);
    await alerts.getByTestId("desk-event-alert-filing").click();
    await expect(alerts.getByTestId("desk-event-alert-filing")).toHaveText("New filing by TESTPICK ✓");
    expect(calls.posts[0]).toEqual({ condition: "filing", symbol: "TESTPICK" });
    await expect(card.locator('[data-testid="desk-intel-alert"][data-status="active"]')).toHaveCount(1);
    await alerts.getByTestId("desk-event-alert-volume").click();
    await expect(alerts.getByTestId("desk-alert-create-error")).toHaveText("You already have this alert, and it is still active. (duplicate_alert)");
    expect(calls.posts[1]).toEqual({ condition: "volume", symbol: "TESTPICK", multiple: 2 });
    await alerts.getByTestId("desk-event-alert-risk").click();
    expect(calls.posts[2]).toEqual({ condition: "risk", symbol: "TESTPICK", level: 4 });
    await alerts.getByTestId("desk-event-alert-category").click();
    await expect.poll(() => calls.posts[3]).toEqual({ condition: "category", category: "earnings", symbol: "TESTPICK" });

    // From the list: the Results chip offers the next results filing from any company.
    await page.getByTestId("desk-intel-chip-results").click();
    await page.getByTestId("desk-intel-alert-chip").click();
    await expect(page.getByTestId("desk-intel-alert-chip")).toHaveText("Alert me on the next results filing ✓");
    expect(calls.posts[4]).toEqual({ condition: "category", category: "earnings" });

    // A sector move offers a sector alert.
    await page.getByTestId("desk-intel-chip-sector").click();
    await page.getByTestId("desk-event-row").first().click();
    await page.getByTestId("desk-event-detail").getByTestId("desk-event-alert-sector").click();
    expect(calls.posts[5]).toEqual({ condition: "sector", index: "Nifty IT", threshold_pct: 2, direction: "either" });

    // Delete the fired alert.
    await fired.getByTestId("desk-intel-alert-delete").click();
    await expect.poll(() => calls.deletes).toEqual([FIRED.id]);
    await expect(card.locator(`[data-testid="desk-intel-alert"][data-id="${FIRED.id}"]`)).toHaveCount(0);
  });

  test("§12.4 sources line: every user sees what each source answered; an admin also sees the failing Intel feeds; a non-admin never reads the admin route", async ({ page }) => {
    const calls = await intelApi(page);
    await page.goto(`${DESK}?tab=intel`);
    const status = page.getByTestId("desk-intel-sources-status");
    await expect(status.getByTestId("desk-intel-source-state")).toHaveText([
      `Filings: answered · latest ${istFull("2026-10-13T04:20:00+00:00")}`,
      "· Bulk and block deals: answered · latest 13 Oct 2026",
      "· SEBI circulars: answered · latest 14 Oct 2026",
      "· FII / DII flows: answered · latest 13 Oct 2026",
    ]);
    // Admin (the fixture user is an admin): only the Intel feeds that are not healthy, never the others.
    await expect(status.getByTestId("desk-intel-admin-feeds")).toHaveText(
      `Admin · BSE announcements (corporate_announcements_bse) failing, last success ${istFull(FEEDS_LIVE.feeds[0].last_success_at as string)}`,
    );
    expect(calls.feedsLive).toBeGreaterThan(0);

    // A failed source is said in words on the line too.
    await page.route("**/api/markets/deals*", (route) => json(route, { detail: "fixture failure" }, 500));
    await page.reload();
    await expect(page.locator('[data-testid="desk-intel-source-state"][data-source="deals"]')).toHaveText("· Bulk and block deals: failed", SLOW);
    await expect(page.getByTestId("desk-intel-trust")).toHaveAttribute("data-status", "failed");
  });

  test("§12.4 a non-admin sees the sources line but no admin feed status", async ({ page }) => {
    const calls = await intelApi(page, { notAdmin: true });
    await page.goto(`${DESK}?tab=intel`);
    await expect(page.getByTestId("desk-intel-sources-status")).toContainText("Filings: answered");
    await expect(page.getByTestId("desk-intel-admin-feeds")).toHaveCount(0);
    expect(calls.feedsLive).toBe(0);
  });

  test("states: an empty chip, a failed chip with retry, a 403, a partial All, and a failed provenance read said in words", async ({ page }) => {
    const calls = await intelApi(page, { feed: { status: 200, body: { ok: true, total: 0, facets: {}, rows: [] } } });
    await page.goto(`${DESK}?tab=intel`);
    await page.getByTestId("desk-intel-chip-results").click();
    await expect(page.getByTestId("desk-intel-empty")).toContainText("No events here yet");
    await expect(page.getByTestId("desk-event-row")).toHaveCount(0);

    // Filings fail: All still lists the deals, circulars and flows and says what is missing, with a retry.
    // The chip is kept in the URL (?in_chip=), so a reload would stay on Results: open the All list by its URL instead.
    await page.route("**/api/filings/feed*", (route) => { calls.feed.push(new URL(route.request().url())); return json(route, { detail: "fixture failure" }, 500); });
    await page.goto(`${DESK}?tab=intel`);
    const partial = page.getByTestId("desk-intel-partial");
    await expect(partial.getByRole("alert")).toContainText("Filings didn’t load; the rest are listed", SLOW);
    await expect(page.getByTestId("desk-event-row")).toHaveCount(5 + DEALS.rows.length + CIRCULARS.rows.length);
    const before = calls.feed.length;
    await partial.getByRole("button", { name: /Retry/ }).click();
    await expect.poll(() => calls.feed.length).toBeGreaterThan(before);
    await page.getByTestId("desk-intel-chip-results").click();
    await expect(page.getByTestId("desk-intel-error").getByRole("alert")).toContainText("Market events didn’t load", SLOW);

    await page.route("**/api/markets/deals*", (route) => json(route, { detail: "feature_not_enabled" }, 403));
    await page.goto(`${DESK}?tab=intel`);
    await page.getByTestId("desk-intel-chip-deals").click();
    await expect(page.getByTestId("desk-intel-error")).toContainText("this account does not have access", SLOW);

    // The rows answered but their provenance could not be read: rows stay, the gap is said.
    await page.route("**/api/filings/feed*", (route) => json(route, { ...feed([R_EARN], 1), provenance: { source: null, error: "upstream_unavailable" } }));
    await page.goto(`${DESK}?tab=intel`);
    await expect(page.getByTestId("desk-intel-provenance-error")).toHaveText("The filings’ source records could not be read, so ingestion times, sectors and related companies are not shown.", SLOW);
  });

  test("§10 persona: the investor wording explains the event and the alerts in plain language; the AI read stays labelled", async ({ page }) => {
    await intelApi(page);
    await page.goto(`${DESK}?tab=intel`);
    const detail = page.getByTestId("desk-event-detail");
    await evRow(page, R_EARN.id).click();
    await page.getByTestId("desk-persona-investor").click();
    await expect(detail.getByTestId("desk-event-plain")).toHaveText("The company has published its quarterly numbers. Share prices often react when results are better or worse than people expected.");
    await expect(detail.getByTestId("desk-event-ai")).toContainText("AI read · not verified");
    await expect(detail.getByTestId("desk-event-alert-filing")).toHaveText("Tell me about its next filing");
    await expect(detail.getByTestId("desk-event-alert-volume")).toHaveText("Tell me if trading jumps");
    await evRow(page, R_ORDER.id).click();
    await expect(detail.getByTestId("desk-event-plain")).toHaveText("The company told the exchange about a new order or contract. News like this can affect the share price.");
    await page.getByTestId("desk-persona-trader").click();
    await expect(detail.getByTestId("desk-event-plain")).toHaveText("A company disclosure classified as Order.");
  });
});

// ── 390px ───────────────────────────────────────────────────────────────

// ── Market intelligence · design fidelity (design-spec §6, §10, §11 M3) ──

/** Screenshots for the design comparison land in test-results/ (git-ignored); they assert nothing on their own. */
const SHOTS = "test-results/fidelity-shots";

test.describe("Smart trading desk — Market intelligence · design fidelity", () => {
  test("§11 M3 at 390: type chips in one scrolling row, 04 · Top market events with tap-for-why rows, the event body, Sector impact · 1D, alerts, no sideways scroll", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await intelApi(page);
    await page.goto(`${DESK}?tab=intel`);
    const intel = page.getByTestId("desk-intel");
    // The chips: All and the PRD's twelve, on one row that scrolls inside itself.
    const chips = intel.getByRole("group", { name: "Event type" });
    await expect(chips.getByRole("button")).toHaveText(CHIP_LABELS);
    expect(await chips.evaluate((e) => getComputedStyle(e).flexWrap)).toBe("nowrap");
    const tops = await chips.getByRole("button").evaluateAll((els) => els.map((e) => Math.round(e.getBoundingClientRect().top)));
    expect(new Set(tops).size).toBe(1);

    // The events card: title and the "tap for why" note; no side detail panel on a phone.
    await expect(page.getByTestId("desk-intel-title")).toHaveText("Top market events");
    await expect(page.getByTestId("desk-intel-events")).toContainText("Tap for why");
    await expect(page.getByTestId("desk-event-detail")).toHaveCount(0);
    const order = expectedAll();
    const rows = page.getByTestId("desk-event-row");
    await expect(rows).toHaveCount(12);
    expect(await rows.evaluateAll((els) => els.map((e) => e.getAttribute("data-id")))).toEqual(order.slice(0, 12));
    const toggle = rows.nth(0).getByTestId("desk-event-toggle");
    expect(await toggle.evaluate((e) => getComputedStyle(e).gridTemplateColumns.split(" ")[0])).toBe("44px");

    // Tap a filing: it expands in place with the source, why, the AI read, the facts, the impact, alerts and both sources.
    const earn = evRow(page, R_EARN.id);
    await expect(earn.getByTestId("desk-event-sentiment")).toHaveText("AI read · not verified");
    await expect(earn.getByTestId("desk-event-sources-count")).toHaveText("2 sources");
    await expect(earn.getByTestId("desk-event-type")).toHaveText("Results");
    await expect(earn.getByTestId("desk-event-linked")).toContainText("TESTPICK");
    await earn.getByTestId("desk-event-toggle").click();
    await expect(earn.getByTestId("desk-event-toggle")).toHaveAttribute("aria-expanded", "true");
    const box = earn.getByTestId("desk-event-why-box");
    await expect(box).toContainText("Why it may matter");
    await expect(box.getByTestId("desk-event-source-label")).toHaveText("Exchange filing (NSE)");
    await expect(box.getByTestId("desk-event-why")).toHaveText(R_EARN.one as string);
    await expect(box.getByTestId("desk-event-fact-ingested")).toHaveText(istFull(PROV_EARN.ingested_at));
    await expect(box.getByTestId("desk-event-sources").locator("li")).toHaveCount(2);
    await expect(box.getByTestId("desk-event-scanner").first()).toHaveText("TESTPICK is #1 of 3 in today’s scan.");
    await expect(box.getByTestId("desk-event-tech")).toBeVisible();
    await expect(box.getByTestId("desk-event-alerts")).toBeVisible();
    let o = await overflow(page);
    expect(o.doc).toBeLessThanOrEqual(1);
    expect(o.scroll).toBeLessThanOrEqual(1);
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
    // The alerts card on the phone, with the fired alert's reason.
    await expect(page.getByTestId("desk-intel-alerts").getByTestId("desk-intel-alert-reason")).toContainText(FIRED.reason);

    o = await overflow(page);
    expect(o.doc).toBeLessThanOrEqual(1);
    expect(o.scroll).toBeLessThanOrEqual(1);
    // Every chip keeps the phone composition and fits.
    for (const key of ["announcements", "results", "calls", "orders", "mna", "ownership", "deals", "flows", "regulatory", "sector", "macro", "exchange"]) {
      await page.getByTestId(`desk-intel-chip-${key}`).click();
      await expect(page.getByTestId(`desk-intel-chip-${key}`)).toHaveAttribute("aria-pressed", "true");
      o = await overflow(page);
      expect(o.doc).toBeLessThanOrEqual(1);
      expect(o.scroll).toBeLessThanOrEqual(1);
    }
    // A deal expanded on a phone: the plain explanation, the deal block and the exchange's source.
    await page.getByTestId("desk-intel-chip-deals").click();
    await rows.first().getByTestId("desk-event-toggle").click();
    await expect(rows.first().getByTestId("desk-event-plain")).toContainText("A bulk deal is one in which a client traded more than 0.5%");
    await expect(rows.first().getByTestId("desk-event-deal")).toBeVisible();
    await expect(rows.first().getByTestId("desk-event-sources")).toContainText(DEALS.source);
    o = await overflow(page);
    expect(o.doc).toBeLessThanOrEqual(1);
    expect(o.scroll).toBeLessThanOrEqual(1);
  });

  test("fidelity screenshots: desktop 1440 with the dock, and 390", async ({ page }) => {
    const phase = "after";
    await page.setViewportSize({ width: 1440, height: 900 });
    await intelApi(page);
    await page.goto(`${DESK}?tab=intel`);
    await expect(page.getByTestId("desk-event-row").first()).toBeVisible();
    await page.waitForTimeout(400);
    await page.screenshot({ path: `${SHOTS}/fidelity-intel-${phase}-1440.png` });
    await evRow(page, R_EARN.id).click();
    await expect(page.getByTestId("desk-event-tech")).toBeVisible();
    await page.waitForTimeout(300);
    await page.screenshot({ path: `${SHOTS}/fidelity-intel-${phase}-1440-filing.png` });
    await page.setViewportSize({ width: 1440, height: 2600 });
    await page.waitForTimeout(300);
    await page.screenshot({ path: `${SHOTS}/fidelity-intel-${phase}-1440-full.png` });

    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto(`${DESK}?tab=intel`);
    await expect(page.getByTestId("desk-event-row").first()).toBeVisible();
    await evRow(page, R_EARN.id).getByTestId("desk-event-toggle").click();
    await page.waitForTimeout(400);
    await page.screenshot({ path: `${SHOTS}/fidelity-intel-${phase}-390.png` });
    await page.setViewportSize({ width: 390, height: 3200 });
    await page.waitForTimeout(300);
    await page.screenshot({ path: `${SHOTS}/fidelity-intel-${phase}-390-full.png` });
  });
});
