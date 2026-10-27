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
 * IntelTab.tsx (+ intel-data.ts): index cards with their time and live /
 * delayed / end-of-day label, breadth with its ratio and the universe the route
 * names, from GET /api/markets/home; the five regimes of GET /api/macro/today's
 * `regime` (thresholds, evidence, invalidation, and the not-available states);
 * sector strength from GET /api/markets/sector-returns with its 1D / 1W / 1M
 * toggle, sort, filter, breadth within a sector and a sector's stocks (GET
 * /api/markets/sector-constituents), and the 5-session leaders from GET
 * /api/positional/market-dashboard; Top AI opportunities (with GET
 * /api/positional/picks/mine?live=true), Key market events, the portfolio
 * snapshot and risk summary, the trust line on every Overview card and the
 * investor wording; a failed market overview; the filings event list with its category chips, the row's
 * exchange and the selected filing's read, bulk and block deals from GET
 * /api/markets/deals, SEBI circulars from GET /api/markets/circulars, the
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
const REGIMES: Record<string, ReturnType<typeof regime>> = {
  bullish: regime("bullish", { nifty: 25100, avg: 25000, vix: 13.2, adv: 2400, dec: 1200, trend: "up", breadth: "up" }, [
    { input: "nifty_close", condition: "below", level: 25000, then: "mixed" },
    { input: "india_vix", condition: "at_or_above", level: 22.5, then: "high_volatility" },
    { input: "advancing_share_pct", condition: "at_or_below", level: 45, then: "mixed" }]),
  mixed: regime("mixed", { nifty: 25100, avg: 25000, vix: 13.2, adv: 1000, dec: 1500, trend: "up", breadth: "down" }, [
    { input: "nifty_close", condition: "below", level: 25000, then: "bearish" },
    { input: "india_vix", condition: "at_or_above", level: 22.5, then: "high_volatility" },
    { input: "advancing_share_pct", condition: "at_or_above", level: 55, then: "bullish" }]),
  high_volatility: regime("high_volatility", { nifty: 25100, avg: 25000, vix: 23.1, adv: 2400, dec: 1200, trend: "up", breadth: "up" }, [
    { input: "india_vix", condition: "below", level: 22.5, then: "bullish" }]),
  sideways: regime("sideways", { nifty: 25000, avg: 25000, vix: 13.2, adv: 1500, dec: 1500, trend: "flat", breadth: "even" }, [
    { input: "nifty_close", condition: "below", level: 25000, then: "bearish" },
    { input: "nifty_close", condition: "above", level: 25000, then: "bullish" },
    { input: "india_vix", condition: "at_or_above", level: 22.5, then: "high_volatility" }]),
  bearish: regime("bearish", { nifty: 24800, avg: 25000, vix: 14, adv: 1000, dec: 1500, trend: "down", breadth: "down" }, [
    { input: "nifty_close", condition: "above", level: 25000, then: "mixed" },
    { input: "india_vix", condition: "at_or_above", level: 22.5, then: "high_volatility" },
    { input: "advancing_share_pct", condition: "at_or_above", level: 55, then: "mixed" }]),
};
const LABEL: Record<string, string> = { bearish: "Bearish", sideways: "Sideways", bullish: "Bullish", mixed: "Mixed", high_volatility: "High volatility" };
const SEGMENTS = ["bearish", "sideways", "bullish", "mixed", "high_volatility"];
const withRegime = (r: unknown) => ({ ...MACRO_BULL, regime: r });
const thr = (n: number) => new Intl.NumberFormat("en-IN", { maximumFractionDigits: 2 }).format(n);
/** The card's trader sentence for each regime (OverviewTab.tsx regimeText), written out. */
function traderMeaning(key: string, r: ReturnType<typeof regime>): string {
  const v = thr(r.rule.vix_high);
  const i = r.inputs;
  if (key === "high_volatility") return `India VIX closed at ${(i.india_vix ?? 0).toFixed(2)}, at or above ${v}, so volatility overrides the trend reading.`;
  if (key === "mixed") return `The Nifty 50 trend is ${i.trend} (close vs its 50-day average) but breadth points ${i.breadth}: the index and the broad market disagree.`;
  if (key === "bullish") return `The Nifty 50 closed above its 50-day average; India VIX is under ${v} and breadth does not disagree.`;
  if (key === "bearish") return `The Nifty 50 closed below its 50-day average; India VIX is under ${v} and breadth does not disagree.`;
  return "The Nifty 50 closed level with its 50-day average.";
}
function flipLine(f: Flip): string {
  const head = f.input === "nifty_close" ? `A Nifty 50 close ${f.condition === "below" ? "below" : "above"} ${level(f.level)} (its 50-day average)`
    : f.input === "india_vix" ? `India VIX closing ${f.condition === "below" ? "below" : "at or above"} ${thr(f.level)}`
    : `Advancing stocks ${f.condition === "at_or_below" ? "at or below" : "at or above"} ${thr(f.level)}% of advances + declines`;
  return `${head} → ${LABEL[f.then]}`;
}

/** "13 Oct, 15:35 IST" for an instant, in India time (OverviewTab's stamp). */
const istStamp = (iso: string) => {
  const t = new Date(iso);
  const d = new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Kolkata", year: "numeric", month: "2-digit", day: "2-digit" }).format(t);
  const hm = new Intl.DateTimeFormat("en-GB", { timeZone: "Asia/Kolkata", hour: "2-digit", minute: "2-digit", hourCycle: "h23" }).format(t);
  return `${day(d)}, ${hm} IST`;
};

// backend/routes/positional.py :: get_watchlist with the fields the Overview reads (atr_pct, avg_traded_value_cr_20d,
// final_score). Risk class: ATR % of close, Low < 2, Medium 2–4, High > 4 (4.0 is Medium); liquid at ₹10 Cr a day or more.
const WATCH_OV = { as_of_date: "2026-10-13", buckets: {
  breakout_confirmed: [{ nse_symbol: "TESTBRK", sector: "Capital Goods", close_price: 510.0, trigger_price: 500.0, stop_price: 477.5, atr_pct: 2.94, why: "Fixture reason", avg_traded_value_cr_20d: 12.34, final_score: 0.76 }],
  pre_breakout: [{ nse_symbol: "TESTPRE", sector: "Chemicals", close_price: 98.0, trigger_price: 100.0, stop_price: 93.0, atr_pct: 4.6, why: "Fixture coil", avg_traded_value_cr_20d: 4.2 }],
  trend_continuation: [{ nse_symbol: "TESTEDGE", close_price: 300.0, trigger_price: 300.0, stop_price: 285.0, atr_pct: 4.0, why: "Fixture pullback", avg_traded_value_cr_20d: 10 }],
  true_accumulation: [{ nse_symbol: "TESTLOW", close_price: 220.0, trigger_price: 225.0, stop_price: 210.0, atr_pct: 1.5, why: "Fixture range", avg_traded_value_cr_20d: null }] } };
// backend/routes/positional.py :: get_picks_for_me?live=true — the live price, readiness and the conviction check's penalties.
const PICKS_MINE = { signal_date: "2026-10-13", count: 1, live: true, picks: [{ ...PICKS.picks[0], live_price: 561.3, live_pct_from_entry: 11.15, readiness: "LATE",
  conviction: { verdict: "SETUP_FORMING", penalties: [{ name: "overbought_rsi", points: -15, reason: "RSI 76 — overextended" }, { name: "recent_spike", points: -10, reason: "+9.2% in 5d — gap-up risk" }] },
  portfolio_warning: [] }] };

// backend/routes/markets_desk.py :: sector_constituents → DaaS /v1/desk/sector-constituents. change_pct is the route's own
// (close ÷ prev_close − 1, 2 decimals), worked out the same way here.
const member = (symbol: string, name: string, close: number | null, prev: number | null) => ({
  symbol, company_name: name, industry: "Financial Services", weight_pct: null, close, prev_close: prev,
  change_pct: close != null && prev != null ? Math.round((close / prev - 1) * 10000) / 100 : null,
  move: close == null || prev == null ? null : close > prev ? "advance" : close < prev ? "decline" : "unchanged",
});
const BANK_ROWS = [member("PNB", "Punjab National Bank", 118.5, 116.55), member("SBIN", "State Bank of India", 954.9, 957.0), member("HDFCBANK", "HDFC Bank Ltd", 710.7, 714.0)];
const CONSTITUENTS_BANK = {
  index: "Nifty Bank", sector: "Banks", available: true, reason: null, list_date: "2026-10-13", date: "2026-10-13",
  source: "NSE index lists (nidp.index_constituents) with NSE bhavcopy closes (nidp.prices_eod)", rule: "advance = …",
  breadth: { members: 3, advances: 1, declines: 2, unchanged: 0, no_price: 0 }, count: 3, rows: BANK_ROWS,
};
const CONSTITUENTS_NONE = { index: "Nifty Metal", sector: "Metals", available: false, reason: "no constituent list for Nifty Metal in nidp.index_constituents",
  list_date: null, date: "2026-10-13", source: "NSE index lists (nidp.index_constituents) with NSE bhavcopy closes (nidp.prices_eod)", rule: "advance = …", breadth: null, count: 0, rows: [] };
const SECTORS_ISB = { ...SECTOR_RETURNS, in_sector_breadth: { source: CONSTITUENTS_BANK.source, rule: "advance = …",
  indices: { "Nifty Bank": { list_date: "2026-10-13", date: "2026-10-13", members: 14, advances: 6, declines: 8, unchanged: 0, no_price: 0 } } } };

// backend/routes/portfolio_risk_analytics.py :: risk_analytics — 21.5% a year volatility is the route's HIGH band.
const RISK = { empty: false, risk_rating: "HIGH", risk_score: 5.4, weighted_volatility: 0.215, weighted_beta: 1.12, var_1d_rs: 41000, var_1d_pct: 0.4, var_confidence: 0.95, coverage_pct: 88.0, risk_drivers: [] };
const FX = path.join(process.cwd(), "e2e", "fixtures");
const HOLDINGS = JSON.parse(fs.readFileSync(path.join(FX, "holdings-enriched.json"), "utf-8")) as { holdings: Array<{ holding_id: string; name: string; asset_type: string; nse_symbol: string | null; value_rs: number | null; weight_pct: number | null }>; totals: { value_rs: number; pnl_rs: number; pnl_pct: number } };

/** The Overview's extra reads on top of deskApi: live picks, risk, brokers, constituents. */
async function overviewExtras(page: Page, o: { watch?: unknown; macro?: unknown } = {}) {
  await page.route("**/api/positional/watchlist*", (route) => json(route, o.watch ?? WATCH_OV));
  await page.route("**/api/positional/picks/mine*", (route) => json(route, PICKS_MINE));
  await page.route("**/api/portfolio/risk-analytics", (route) => json(route, RISK));
  // backend/routes/broker.py :: accounts — one account read two hours ago (not stale).
  const read = new Date(Date.now() - 2 * 3600_000).toISOString();
  await page.route("**/api/broker/accounts", (route) => json(route, { accounts: [{ account_id: "acc1", broker: "zerodha", broker_display: "Zerodha", status: "active", last_sync_at: read, last_sync_count: 12 }] }));
  await page.route("**/api/markets/sector-constituents*", (route) => {
    const idx = new URL(route.request().url()).searchParams.get("index");
    return json(route, idx === "Nifty Bank" ? CONSTITUENTS_BANK : { ...CONSTITUENTS_NONE, index: idx });
  });
  if (o.macro) await page.route("**/api/macro/today", (route) => json(route, o.macro));
}

// RETIRED by the desk redesign step 2 (Market Overview, 2026-10-27): the old Overview cards (tradingdesk/OverviewTab.tsx) are
// no longer mounted on the desk. Market Overview's strip and events replace them (copilot-app-desk-market-overview.spec.ts,
// which also carries TC-3 … TC-5's Kite-close rule as MO-2b … MO-2d). OverviewTab is deleted or re-hosted in step 6.
// The cases marked test.skip below test those cards; the rest still run.
test.describe("Smart trading desk — Overview", () => {
  test.skip("TC-8 (OV-001): the four index cards equal the /home payload, each with its time and end-of-day / delayed / live label; the lines are daily closes", async ({ page }) => {
    await deskApi(page);
    await page.goto(`${DESK}?tab=overview`);
    const tiles = page.getByTestId("desk-index-tile");
    await expect(tiles).toHaveCount(4);
    const stamp = istStamp(HOME.fetched_at);
    for (const name of ["Nifty 50", "Nifty Bank", "Sensex", "India VIX"]) {
      const ix = HOME.indices.find((i) => i.name === name)!;
      const tile = page.locator(`[data-testid="desk-index-tile"][data-index="${name}"]`);
      await expect(tile.getByTestId("desk-index-value")).toHaveText(level(ix.value));
      await expect(tile.getByTestId("desk-index-change")).toHaveText(`${points(ix.change)} (${pct(ix.change_pct)})`);
      await expect(tile.getByTestId("desk-index-spark")).toHaveCount(1);
      await expect(tile.getByTestId("desk-index-spark-label")).toHaveText("DAILY CLOSES");
      // market_state "closed": end of day, never live; the stamp is the route's fetched_at in IST.
      await expect(tile.getByTestId("desk-index-stamp")).toHaveText(`End of day · ${stamp}`);
      await expect(tile.getByTestId("desk-index-stamp")).toHaveAttribute("data-mode", "eod");
    }
    await expect(page.locator('[data-testid="desk-index-tile"][data-index="Nifty 500"]')).toHaveCount(0);
    // Trust line: source, mode, time, who made it, and that the lines are the last 5 daily closes (the longest spark), not intraday.
    await expect(page.getByTestId("desk-index-trust")).toHaveText(`Yahoo Finance index quotes · End of day · updated ${stamp} · As reported · each line is the last 5 daily closes, not intraday`);

    // In hours with delayed quotes, and with the live tape.
    await page.route("**/api/markets/home", (route) => json(route, { ...HOME, market_state: "open", is_live: false }));
    await page.reload();
    await expect(page.getByTestId("desk-index-stamp").first()).toHaveText(`Delayed · ${stamp}`);
    await page.route("**/api/markets/home", (route) => json(route, { ...HOME, market_state: "open", is_live: true }));
    await page.reload();
    await expect(page.getByTestId("desk-index-stamp").first()).toHaveText(`Live · ${stamp}`);
    await expect(page.getByTestId("desk-index-trust")).toHaveAttribute("data-mode", "live");
  });

  test.skip("TC-9 (OV-002): breadth counts, unchanged, A/D ratio and the advancing share from the payload, the universe named, no invented trend", async ({ page }) => {
    await deskApi(page);
    await page.goto(`${DESK}?tab=overview`);
    const b = HOME.breadth;
    const share = (b.advances / (b.advances + b.declines + b.unchanged)) * 100; // 2428 / 3642 = 66.67
    await expect(page.getByTestId("desk-breadth-pct")).toHaveText(`${share.toFixed(0)}%`);
    await expect(page.getByTestId("desk-breadth-adv")).toHaveText(`${int(b.advances)} advances`);
    await expect(page.getByTestId("desk-breadth-dec")).toHaveText(`declines ${int(b.declines)}`);
    await expect(page.getByTestId("desk-breadth-unch")).toHaveText(`${int(b.unchanged)} unchanged`);
    // A/D ratio = 2428 ÷ 1142 = 2.13
    await expect(page.getByTestId("desk-breadth-ratio")).toHaveText(`A/D ratio ${(b.advances / b.declines).toFixed(2)}`);
    // No route keeps daily counts: the trend slot says so instead of drawing one.
    await expect(page.getByTestId("desk-breadth-trend")).toHaveText("A/D trend — no daily history on record");
    await expect(page.getByTestId("desk-breadth-scope")).toHaveAttribute("data-scope", "eod");
    await expect(page.getByTestId("desk-breadth-scope")).toHaveText(`Across ${int(b.universe)} NSE stocks in the end-of-day bhavcopy · ${day(HOME.as_of, true)}`);
    await expect(page.getByTestId("desk-breadth-bar")).toHaveAttribute("aria-label", `${int(b.advances)} advances, ${int(b.unchanged)} unchanged, ${int(b.declines)} declines`);
    await expect(page.getByTestId("desk-breadth-trust")).toHaveText(`NSE bhavcopy, end-of-day bars (stock_ohlcv) · End of day · ${day(HOME.as_of, true)} · Rules-based · close above / below the previous close`);

    // The route's fallback, named "nifty50_live": a delayed count over the Nifty 50 constituents.
    const live = { advances: 31, declines: 17, unchanged: 2, universe: 50, universe_kind: "nifty50_live", tone: "POSITIVE" };
    await page.route("**/api/markets/home", (route) => json(route, { ...HOME, breadth: live }));
    await page.reload();
    await expect(page.getByTestId("desk-breadth-pct")).toHaveText(`${((31 / 50) * 100).toFixed(0)}%`);
    await expect(page.getByTestId("desk-breadth-scope")).toHaveText("Across the 50 Nifty 50 stocks · delayed quotes");
    await expect(page.getByTestId("desk-breadth-trust")).toHaveAttribute("data-mode", "delayed");
    // No kind, or one this screen does not know: the count is shown and nothing is guessed from its size.
    for (const kind of [undefined, null, "zzz_unknown"]) {
      const unnamed = { advances: 31, declines: 17, unchanged: 2, universe: 50, tone: "POSITIVE", ...(kind === undefined ? {} : { universe_kind: kind }) };
      await page.route("**/api/markets/home", (route) => json(route, { ...HOME, breadth: unnamed }));
      await page.reload();
      await expect(page.getByTestId("desk-breadth-scope")).toHaveAttribute("data-scope", "unnamed");
      await expect(page.getByTestId("desk-breadth-scope")).toHaveText("Across 50 stocks · the response does not say which");
    }
    // Missing is not zero: no declines → the ratio is "—".
    await page.route("**/api/markets/home", (route) => json(route, { ...HOME, breadth: { ...HOME.breadth, declines: 0 } }));
    await page.reload();
    await expect(page.getByTestId("desk-breadth-ratio")).toHaveText("A/D ratio —");
  });

  test.skip("TC-10 (OV-003): each of the five regimes comes from the route's rule — label, segment, meaning, evidence, thresholds on the card, invalidation", async ({ page }) => {
    await deskApi(page);
    for (const key of SEGMENTS) {
      const r = REGIMES[key];
      await page.route("**/api/macro/today", (route) => json(route, withRegime(r)));
      await page.goto(`${DESK}?tab=overview`);
      await expect(page.getByTestId("desk-regime")).toHaveAttribute("data-regime", key);
      await expect(page.getByTestId("desk-regime-label")).toHaveText(LABEL[key]);
      await expect(page.locator('[data-testid="desk-regime-segment"][data-on="true"]')).toHaveCount(1);
      await expect(page.locator('[data-testid="desk-regime-segment"][data-on="true"]')).toHaveAttribute("data-key", key);
      await expect(page.getByTestId("desk-regime-segment")).toHaveCount(5);
      await expect(page.getByTestId("desk-regime-meaning")).toHaveText(traderMeaning(key, r));
      // Supporting evidence: the three inputs the rule read, as sent.
      const i = r.inputs;
      await expect(page.getByTestId("desk-regime-input-trend")).toContainText(`${level(i.nifty_close!)} vs ${level(i.nifty_average!)} (${pct(i.nifty_vs_average_pct!)})`);
      await expect(page.getByTestId("desk-regime-input-trend")).toHaveAttribute("data-reads", i.trend!);
      await expect(page.getByTestId("desk-regime-input-volatility")).toContainText(`${i.india_vix!.toFixed(2)} · ${i.volatility_high ? "at or above" : "under"} ${thr(RULE_X.vix_high)}`);
      await expect(page.getByTestId("desk-regime-input-breadth")).toContainText(`${int(i.advances!)} up · ${int(i.declines!)} down · ${i.advancing_share_pct!.toFixed(1)}% of movers up · ${int(i.breadth_universe!)} stocks`);
      await expect(page.getByTestId("desk-regime-input-breadth")).toHaveAttribute("data-reads", i.breadth!);
      // The thresholds, from the payload (22.5 / 55 / 45 here), shown on the card.
      await expect(page.getByTestId("desk-regime-rule")).toContainText(`Rule ${RULE_X.version}: High volatility when India VIX ≥ ${thr(RULE_X.vix_high)}`);
      await expect(page.getByTestId("desk-regime-rule")).toContainText(`breadth up at ≥ ${thr(RULE_X.breadth_up_pct)}%, down at ≤ ${thr(RULE_X.breadth_down_pct)}%`);
      // Invalidation: one line per flip the route sent, in its order.
      const flips = page.getByTestId("desk-regime-flip");
      await expect(flips).toHaveCount(r.invalidation.length);
      for (let k = 0; k < r.invalidation.length; k += 1) {
        await expect(flips.nth(k)).toHaveText(flipLine(r.invalidation[k]));
        await expect(flips.nth(k)).toHaveAttribute("data-then", r.invalidation[k].then);
      }
      await expect(page.getByTestId("desk-pulse-trust")).toHaveText(`Macro engine (macro_daily, macro_features) and end-of-day bars (stock_ohlcv) · End of day · ${day("2026-10-13", true)} · Rules-based · regime rule ${RULE_X.version}`);
    }

    // Flows, rupee, crude and the rules-based read still come from /home and the engine.
    await expect(page.getByTestId("desk-mini-fii-value")).toHaveText(crore(HOME.fii_dii.fii_net_cr));
    await expect(page.getByTestId("desk-mini-dii-sub")).toHaveText(`Net buy · ${day(HOME.fii_dii.as_of)}`);
    await expect(page.getByTestId("desk-mini-usdinr-value")).toHaveText(level(84.12));
    await expect(page.getByTestId("desk-mini-brent-value")).toHaveText(`$${level(63.4)}`);
    await expect(page.getByTestId("desk-insight-macro")).toHaveText(MACRO_BULL.insight);
    await expect(page.getByTestId("desk-insight")).not.toContainText("AI");
    await expect(page.getByTestId("desk-verdict-reason")).toHaveText(HOME.verdict_reason);
  });

  test.skip("TC-10 (OV-003): sector leadership, important events and risks beside the regime; a skipped check is said, not guessed", async ({ page }) => {
    await deskApi(page);
    const skipped = regime("bullish", { nifty: 25100, avg: 25000, vix: null, adv: null, dec: null, trend: "up", breadth: null }, [
      { input: "nifty_close", condition: "below", level: 25000, then: "bearish" }],
    { skipped: [{ check: "high_volatility", reason: "no India VIX close on record for the session" }, { check: "mixed", reason: "no advances and declines on record for the session" }] });
    await page.route("**/api/macro/today", (route) => json(route, withRegime(skipped)));
    await page.goto(`${DESK}?tab=overview`);
    await expect(page.getByTestId("desk-regime-label")).toHaveText("Bullish");
    await expect(page.getByTestId("desk-regime-input-volatility")).toContainText("— no India VIX close on record for the session (check skipped)");
    await expect(page.getByTestId("desk-regime-input-breadth")).toContainText("— no advances and declines on record for the session (check skipped)");
    await expect(page.getByTestId("desk-pulse-risks")).toContainText("Volatility not checked: no India VIX close on record for the session.");
    await expect(page.getByTestId("desk-pulse-risks")).toContainText("Breadth not checked: no advances and declines on record for the session.");
    await expect(page.getByTestId("desk-pulse-risks")).toContainText(`Macro engine risk: ${MACRO_BULL.risk.toLowerCase()}`);
    // Leadership over 1 day from /markets/sector-returns: IT +1.42% leads, Realty −1.60% lags.
    const sorted = [...SECTOR_RETURNS.sectors].sort((a, b) => b.ret_1d_pct - a.ret_1d_pct);
    await expect(page.getByTestId("desk-pulse-lead")).toHaveText(`${sorted[0].sector} ${pct(sorted[0].ret_1d_pct)}`);
    await expect(page.getByTestId("desk-pulse-lag")).toHaveText(`${sorted[sorted.length - 1].sector} ${pct(sorted[sorted.length - 1].ret_1d_pct)}`);
    // Important events: the three newest key events (see the Key market events test for the rule).
    await expect(page.getByTestId("desk-pulse-event")).toHaveCount(3);
  });

  test.skip("TC-10: no regime block, a rule that could not classify, and the macro route's uninitialised answer are honest not-available states", async ({ page }) => {
    await deskApi(page);
    await page.goto(`${DESK}?tab=overview`);
    // MACRO_BULL carries no `regime` (an older backend): the engine's BULL is NOT turned into a regime here.
    await expect(page.getByTestId("desk-regime")).toHaveAttribute("data-regime", "unavailable");
    await expect(page.getByTestId("desk-regime-label")).toHaveText("Not available");
    await expect(page.getByTestId("desk-regime-unavailable")).toContainText("This server sent no regime classification");
    await expect(page.locator('[data-testid="desk-regime-segment"][data-on="true"]')).toHaveCount(0);

    await page.route("**/api/macro/today", (route) => json(route, withRegime({ ...regime(null, { nifty: null, avg: 25000, vix: 13, adv: null, dec: null, trend: null, breadth: null }, []), reason: "no Nifty 50 close or 50-session average on record for the session" })));
    await page.reload();
    await expect(page.getByTestId("desk-regime-label")).toHaveText("Not available");
    await expect(page.getByTestId("desk-regime-unavailable")).toContainText("could not classify the session: no Nifty 50 close or 50-session average");
    await expect(page.getByTestId("desk-regime-invalidation")).toContainText("— no regime to invalidate.");

    await page.route("**/api/macro/today", (route) => json(route, MACRO_UNINIT));
    await page.reload();
    await expect(page.getByTestId("desk-regime")).toHaveAttribute("data-regime", "unavailable");
    await expect(page.getByTestId("desk-regime-unavailable")).toContainText("has not produced a regime yet");
    // The fixture user is an admin: the route's reason is shown to admins.
    await expect(page.getByTestId("desk-regime-unavailable")).toContainText(MACRO_UNINIT._reason);
    await expect(page.getByTestId("desk-insight")).not.toContainText("initialising");
  });

  test.skip("TC-11 (OV-004): sector strength — 1D / 1W / 1M, source and as-of, leaders by exact sector match", async ({ page }) => {
    const calls = await deskApi(page);
    await page.goto(`${DESK}?tab=overview`);
    const tiles = page.getByTestId("desk-sector-tile");
    await expect(tiles).toHaveCount(SECTOR_RETURNS.sectors.length);
    const checkPeriod = async (period: "1d" | "1w" | "1m", words: string, sessions: number) => {
      await expect(page.getByTestId(`desk-sector-period-${period}`)).toHaveAttribute("aria-pressed", "true");
      await expect(page.getByTestId("desk-sector-period")).toHaveText(`${words} · ${sessions} ${sessions === 1 ? "session" : "sessions"} · end of day`);
      const order = sectorOrder(period);
      for (let k = 0; k < order.length; k += 1) {
        const r: SectorRow = order[k];
        await expect(tiles.nth(k)).toHaveAttribute("data-index", r.index);
        await expect(tiles.nth(k).getByTestId("desk-sector-pct")).toHaveText(pctOrDash(r[PERIOD_KEY[period]] as number | null));
      }
      await expect(page.getByTestId("desk-sector-source")).toContainText(`${words} = the index close vs its close ${sessions} ${sessions === 1 ? "session" : "sessions"} earlier`);
      await expect(page.getByTestId("desk-sector-trust")).toContainText(`${words} = close vs the close ${sessions} ${sessions === 1 ? "session" : "sessions"} earlier`);
    };
    await checkPeriod("1d", "1 day", SECTOR_RETURNS.sessions["1d"]);
    const it = page.locator('[data-testid="desk-sector-tile"][data-index="Nifty IT"]');
    await expect(it).toHaveAttribute("title", `Nifty IT · ${level(35210.5)} · close of ${day("2026-10-13")}`);
    await expect(page.getByTestId("desk-sector-source")).toContainText(`Source: ${SECTOR_RETURNS.source}`);
    await expect(page.getByTestId("desk-sector-trust")).toHaveText(new RegExp(`^${SECTOR_RETURNS.source.replace(/[().]/g, "\\$&")} · End of day · ${day(SECTOR_RETURNS.as_of, true)} · As reported`));
    const realty = page.locator('[data-testid="desk-sector-tile"][data-index="Nifty Realty"]');
    await expect(realty.getByTestId("desk-sector-stale")).toHaveText(`Close of ${day("2026-10-10")}`);
    await page.getByTestId("desk-sector-period-1w").click();
    await checkPeriod("1w", "1 week", SECTOR_RETURNS.sessions["1w"]);
    await page.getByTestId("desk-sector-period-1m").click();
    await checkPeriod("1m", "1 month", SECTOR_RETURNS.sessions["1m"]);
    await expect(page.getByTestId("desk-sector-source")).toContainText("1 with too little history for this period show “—”");
    expect(calls.sectors).toBe(1);
    // Leaders: IT by sector, Bank by index name; PSU Bank does not borrow Bank's leader.
    await page.getByTestId("desk-sector-period-1d").click();
    await expect(it.getByTestId("desk-sector-leader-label")).toHaveText(`TESTIT ${pct(6.1, 1)} · 5 sessions`);
    await expect(page.locator('[data-testid="desk-sector-tile"][data-index="Nifty PSU Bank"]').getByTestId("desk-sector-leader")).toHaveCount(0);
    await expect(page.getByTestId("desk-sector-leader")).toHaveCount(2);
    await it.getByTestId("desk-sector-leader").click();
    await expect(page).toHaveURL(/[?&]tab=market&view=research(&|$)/); // the Chart tab is Market Desk › Stock Research since the 2026-10-27 redesign
    await expect(page).toHaveURL(/[?&]sym=TESTIT/);
  });

  test.skip("TC-11 (OV-004): sort, filter with clear, breadth within a sector where a list exists (else “—” with the reason), and a sector's stocks", async ({ page }) => {
    await deskApi(page, { sectors: { status: 200, body: SECTORS_ISB } });
    await overviewExtras(page);
    await page.goto(`${DESK}?tab=overview`);
    const tiles = page.getByTestId("desk-sector-tile");
    // Sort: worst first, then A–Z, then back to best first.
    await page.getByTestId("desk-sector-sort-worst").click();
    const worst = [...SECTOR_RETURNS.sectors].sort((a, b) => a.ret_1d_pct - b.ret_1d_pct).map((r) => r.index);
    for (let k = 0; k < worst.length; k += 1) await expect(tiles.nth(k)).toHaveAttribute("data-index", worst[k]);
    await page.getByTestId("desk-sector-sort-name").click();
    const az = [...SECTOR_RETURNS.sectors].sort((a, b) => a.sector.localeCompare(b.sector)).map((r) => r.index);
    for (let k = 0; k < az.length; k += 1) await expect(tiles.nth(k)).toHaveAttribute("data-index", az[k]);
    await page.getByTestId("desk-sector-sort-best").click();
    await expect(page.getByTestId("desk-sector-sort-best")).toHaveAttribute("aria-pressed", "true");
    // Filter to one sector, then clear it.
    await page.getByTestId("desk-sector-filter").selectOption("Nifty IT");
    await expect(tiles).toHaveCount(1);
    await expect(tiles.first()).toHaveAttribute("data-index", "Nifty IT");
    await page.getByTestId("desk-sector-filter-clear").click();
    await expect(tiles).toHaveCount(SECTOR_RETURNS.sectors.length);
    await expect(page.getByTestId("desk-sector-filter")).toHaveValue("");
    // Breadth within a sector: Nifty Bank has a list (6 up, 8 down); the others say "Breadth —" and the note says why.
    const bank = page.locator('[data-testid="desk-sector-tile"][data-index="Nifty Bank"]');
    const b = SECTORS_ISB.in_sector_breadth.indices["Nifty Bank"];
    await expect(bank.getByTestId("desk-sector-breadth")).toHaveText(`${b.advances}↑ ${b.declines}↓`);
    await expect(bank.getByTestId("desk-sector-breadth")).toHaveAttribute("data-has", "true");
    const metal = page.locator('[data-testid="desk-sector-tile"][data-index="Nifty Metal"]');
    await expect(metal.getByTestId("desk-sector-breadth")).toHaveText("Breadth —");
    await expect(page.getByTestId("desk-sector-breadth-note")).toContainText("Only Nifty Bank has a constituent list on record; the others show “Breadth —”.");
    // Open Nifty Bank's stocks: each row's change is the route's, worked out from its closes; a row opens the chart.
    await bank.getByTestId("desk-sector-open").click();
    const panel = page.getByTestId("desk-sector-constituents");
    await expect(panel).toHaveAttribute("data-index", "Nifty Bank");
    const rows = panel.getByTestId("desk-sector-constituent");
    await expect(rows).toHaveCount(BANK_ROWS.length);
    for (let k = 0; k < BANK_ROWS.length; k += 1) {
      await expect(rows.nth(k)).toHaveAttribute("data-symbol", BANK_ROWS[k].symbol);
      await expect(rows.nth(k).getByTestId("desk-sector-constituent-chg")).toHaveText(pct(((BANK_ROWS[k].close! / BANK_ROWS[k].prev_close!) - 1) * 100));
      await expect(rows.nth(k).locator('[data-testid="entity-icon"]')).toHaveAttribute("data-key", BANK_ROWS[k].symbol);
    }
    await expect(panel.getByTestId("desk-sector-constituents-breadth")).toHaveText("1 advance · 2 declines · 0 unchanged · of 3 stocks");
    await expect(panel.getByTestId("desk-sector-constituents-trust")).toContainText(`close of ${day("2026-10-13", true)}`);
    // An index with no list says so with the route's reason.
    await metal.getByTestId("desk-sector-open").click();
    await expect(page.getByTestId("desk-sector-constituents-none")).toContainText(CONSTITUENTS_NONE.reason);
    await bank.getByTestId("desk-sector-open").click();
    await page.getByTestId("desk-sector-constituent").first().click();
    await expect(page).toHaveURL(/[?&]tab=market&view=research(&|$)/); // the Chart tab is Market Desk › Stock Research since the 2026-10-27 redesign
    await expect(page).toHaveURL(new RegExp(`[?&]sym=${BANK_ROWS[0].symbol}`));
  });

  test.skip("TC-11: sector returns — a failed read shows an error with retry, 403 says not enabled, an empty list says so; a failed leader read only drops the leaders", async ({ page }) => {
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
    await page.route("**/api/markets/sector-returns", (route) => json(route, SECTOR_RETURNS));
    await page.reload();
    await expect(page.getByTestId("desk-sector-tile")).toHaveCount(SECTOR_RETURNS.sectors.length);
    await expect(page.getByTestId("desk-sector-leaders-error")).toBeVisible(SLOW);
    await expect(page.getByTestId("desk-sector-leader")).toHaveCount(0);
    // No in_sector_breadth in this payload: every tile says "Breadth —", never 0.
    await expect(page.locator('[data-testid="desk-sector-breadth"][data-has="true"]')).toHaveCount(0);
  });

  test.skip("OV-005b: with a published, uncalibrated move-odds run the Overview withholds the probability and shows the model as evidence", async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 900 });
    await deskApi(page);
    await overviewExtras(page);
    // MOCK - not real data: the shape of GET /api/move-odds/latest (backend/routes/move_odds.py) with a made-up run; no calibration flag.
    const run = { model: "v4", refit: "monthly", status: "final", data_as_of: "2026-10-13", target_session: "2026-10-14", frozen_at: "2026-10-13T20:50:22+05:30",
      git_sha: "0fix000", universe_size: 1000, scored: 994, input_count: 84, train_rows: 1, train_end: "2026-08-31", counts_toward_verdict: true, skipped_holidays: [] };
    await page.route("**/api/move-odds/latest*", (route) => json(route, { data: {
      status: "final", head: "p_up5_1d", expected_session: "2026-10-14", base_rate: 0.0758, run,
      rows: [{ symbol: "TESTPICK", company_name: "Test Pick Ltd", sector: "IT", p: 0.1834, p_opposite: 0.05, events_on_record: 2 }],
      record: { window_label: "Jan–Aug 2025", sessions: 165, base_rate: 0.0812, top10_hit_rate: 0.3103, bands: [] },
      live_record: { sessions: 0, top10_hits: null, touched: null, graded_rows: null, last_target: null, last_top10_hits: null, last_touched: null, last_graded_rows: null },
      limits: { not_used: [] } } }));
    await page.goto(`${DESK}?tab=overview`);
    const first = page.getByTestId("desk-opp").first();
    await expect(first.getByTestId("desk-opp-prob")).toHaveText("P(+5% next session) Withheld");
    await expect(first).not.toContainText("18.3%");
    await expect(first.getByTestId("desk-opp-prob")).toHaveAttribute("title", /does not mark these estimates as calibrated/);
    await expect(page.getByTestId("desk-opps-prob-why")).toContainText("does not mark these estimates as calibrated");
    const ev = page.getByTestId("desk-opps-prob-evidence");
    await expect(ev).toContainText("Move-odds v4");
    await expect(ev).toContainText("data as of 13 Oct 2026");
    await expect(ev).toContainText("out of sample Jan–Aug 2025: top-10 hit rate 31.0% vs a base rate of 8.1% over 165 sessions");
  });

  test.skip("OV-005: Top AI opportunities — symbol, price and its date, score vs probability labelled, horizon, setup, evidence, against, liquidity, risk class; a row opens the chart", async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 900 });
    await deskApi(page);
    await overviewExtras(page);
    await page.goto(`${DESK}?tab=overview`);
    const card = page.getByTestId("desk-opps-card");
    await expect(page.getByTestId("desk-opps-title")).toHaveText("02 · Top AI opportunities");
    const rows = card.getByTestId("desk-opp");
    // Score order: TESTPICK 81.2, TESTBRK 76.0, then the unscored watchlist rows in the route's bucket order.
    const order = ["TESTPICK", "TESTBRK", "TESTPRE", "TESTEDGE", "TESTLOW"];
    await expect(rows).toHaveCount(order.length);
    for (let k = 0; k < order.length; k += 1) await expect(rows.nth(k)).toHaveAttribute("data-symbol", order[k]);
    const risk = (atr: number | null) => (atr == null ? "—" : `${atr < 2 ? "Low" : atr > 4 ? "High" : "Medium"} · ATR ${atr.toFixed(1)}%`);
    const liq = (cr: number | null) => (cr == null ? "Liquidity —" : `${cr >= 10 ? "Liquid" : "Thin"} · ₹${cr.toFixed(1)} Cr/day`);
    const w = WATCH_OV.buckets;
    const want = [
      // Picks only: no close in the rows (the entry 505 is not a price); 5–15 sessions; against = the conviction penalties
      // (and readiness LATE); LTP from the live check; upside (555 − 505) ÷ 505.
      { sym: "TESTPICK", status: "Confirmed", setup: "Setup: Breakout", horizon: "Horizon: 5–15 sessions", liq: "Liquidity —", risk: "Risk: —",
        evidence: "+ Evidence: Fixture scanner reason", against: "− Against: RSI 76 — overextended; +9.2% in 5d — gap-up risk", againstCount: "3",
        price: "—", stamp: "no close in the scan", score: "Score 81/100", up: `to target +${(((555 - 505) / 505) * 100).toFixed(1)}%`, ltp: "LTP ₹561.30 · delayed" },
      { sym: "TESTBRK", status: "Confirmed", setup: "Setup: Breakout confirmed", horizon: "Horizon: —", liq: liq(w.breakout_confirmed[0].avg_traded_value_cr_20d), risk: `Risk: ${risk(w.breakout_confirmed[0].atr_pct)}`,
        evidence: "+ Evidence: Fixture reason", against: "− Against: — not one of the picks the live check reads", againstCount: "0",
        price: "₹510.00", stamp: `close ${day("2026-10-13")}`, score: "Score 76/100", up: null, ltp: null },
      { sym: "TESTPRE", status: "Awaiting", setup: "Setup: Near breakout", horizon: "Horizon: —", liq: liq(w.pre_breakout[0].avg_traded_value_cr_20d), risk: `Risk: ${risk(w.pre_breakout[0].atr_pct)}`,
        evidence: "+ Evidence: Fixture coil", against: "− Against: — not one of the picks the live check reads", againstCount: "0",
        price: "₹98.00", stamp: `close ${day("2026-10-13")}`, score: "Score —", up: null, ltp: null },
      { sym: "TESTEDGE", status: "Awaiting", setup: "Setup: Trend pullback", horizon: "Horizon: —", liq: liq(w.trend_continuation[0].avg_traded_value_cr_20d), risk: `Risk: ${risk(w.trend_continuation[0].atr_pct)}`,
        evidence: "+ Evidence: Fixture pullback", against: "− Against: — not one of the picks the live check reads", againstCount: "0",
        price: "₹300.00", stamp: `close ${day("2026-10-13")}`, score: "Score —", up: null, ltp: null },
      { sym: "TESTLOW", status: "Forming", setup: "Setup: Accumulation", horizon: "Horizon: —", liq: liq(w.true_accumulation[0].avg_traded_value_cr_20d), risk: `Risk: ${risk(w.true_accumulation[0].atr_pct)}`,
        evidence: "+ Evidence: Fixture range", against: "− Against: — not one of the picks the live check reads", againstCount: "0",
        price: "₹220.00", stamp: `close ${day("2026-10-13")}`, score: "Score —", up: null, ltp: null },
    ];
    // Boundaries: 4.0% is Medium, ₹10 Cr a day is liquid.
    expect(want[3].risk).toBe("Risk: Medium · ATR 4.0%");
    expect(want[3].liq).toBe("Liquid · ₹10.0 Cr/day");
    for (let k = 0; k < want.length; k += 1) {
      const r = rows.nth(k);
      const x = want[k];
      await expect(r.getByTestId("desk-opp-symbol")).toHaveText(x.sym);
      await expect(r.locator('[data-testid="entity-icon"]').first()).toHaveAttribute("data-key", x.sym);
      // No name source while move-odds is not enabled (403): the slot stays, "—".
      await expect(r.getByTestId("desk-opp-name")).toHaveText("—");
      await expect(r.getByTestId("desk-opp-status")).toHaveText(x.status);
      await expect(r.getByTestId("desk-opp-setup")).toHaveText(x.setup);
      await expect(r.getByTestId("desk-opp-horizon")).toHaveText(x.horizon);
      await expect(r.getByTestId("desk-opp-liquidity")).toHaveText(x.liq);
      await expect(r.getByTestId("desk-opp-risk")).toHaveText(x.risk);
      await expect(r.getByTestId("desk-opp-evidence")).toHaveText(x.evidence);
      await expect(r.getByTestId("desk-opp-against")).toHaveText(x.against);
      await expect(r.getByTestId("desk-opp-against")).toHaveAttribute("data-count", x.againstCount);
      await expect(r.getByTestId("desk-opp-price")).toHaveText(x.price);
      await expect(r.getByTestId("desk-opp-price-stamp")).toHaveText(x.stamp);
      await expect(r.getByTestId("desk-opp-score")).toHaveText(x.score);
      // The probability is a different thing from the score; the shared gate withholds it (here: not enabled for the account).
      await expect(r.getByTestId("desk-opp-prob")).toHaveText("P(+5% next session) Withheld");
      await expect(r.getByTestId("desk-opp-prob")).toHaveAttribute("title", /Move probabilities are not enabled for this account/);
      if (x.up) await expect(r.getByTestId("desk-opp-upside")).toHaveText(x.up);
      if (x.ltp) await expect(r.getByTestId("desk-opp-ltp")).toHaveText(x.ltp);
      else await expect(r.getByTestId("desk-opp-ltp")).toHaveCount(0);
    }
    await expect(page.getByTestId("desk-opps-legend")).toContainText("a rank, not a probability");
    await expect(page.getByTestId("desk-opps-prob-why")).toHaveText("Move probabilities are not enabled for this account.");
    await expect(page.getByTestId("desk-opps-legend")).toContainText("Risk: ATR(14) % of the close: Low < 2%, Medium 2–4%, High > 4%");
    await expect(page.getByTestId("desk-opps-trust")).toContainText(`Positional scanner (watchlist and picks) · End of day · ${day("2026-10-13", true)} · Rules-based`);
    // A row opens its chart analysis (PRD §4.4: every opportunity opens a detailed view).
    await rows.nth(1).click();
    await expect(page).toHaveURL(/[?&]tab=market&view=research(&|$)/); // the Chart tab is Market Desk › Stock Research since the 2026-10-27 redesign
    await expect(page).toHaveURL(/[?&]sym=TESTBRK/);
  });

  test.skip("OV-005: no setups in the scan is an honest empty state; a failed live check says so on each pick", async ({ page }) => {
    await deskApi(page);
    await page.route("**/api/positional/watchlist*", (route) => json(route, { as_of_date: "2026-10-13", buckets: { breakout_confirmed: [], pre_breakout: [], trend_continuation: [], true_accumulation: [] } }));
    await page.route("**/api/positional/picks*", (route) => json(route, { signal_date: "2026-10-13", count: 0, picks: [] }));
    await page.goto(`${DESK}?tab=overview`);
    await expect(page.getByTestId("desk-opps-empty")).toContainText("No setups in the latest end-of-day scan");
    await page.route("**/api/positional/picks*", (route) => json(route, PICKS));
    await page.route("**/api/positional/picks/mine*", (route) => json(route, { detail: "fixture failure" }, 500));
    await page.reload();
    await expect(page.locator('[data-testid="desk-opp"][data-symbol="TESTPICK"]').getByTestId("desk-opp-against")).toHaveText("− Against: — the live check didn’t load", SLOW);
  });

  test.skip("OV-006: Key market events — the key filings, a deal, a SEBI circular and the FII / DII session, newest first, each with time, stock and source; never “verified”", async ({ page }) => {
    await deskApi(page);
    await overviewExtras(page);
    await page.goto(`${DESK}?tab=overview`);
    // The rule (overview-data.ts keyEvents), written out from the payloads: filings by impact then time, the newest of
    // the five largest deals, the newest circular, the newest FII / DII session; then all newest first (a dated-only row
    // counts as the end of its day, and ties keep that order).
    const rank: Record<string, number> = { high: 0, medium: 1, low: 2 };
    const filings = [R_EARN, R_ORDER, R_LIT].map((r) => ({ id: r.id, t: Date.parse(r.date as string), rank: rank[String(r.impact)] ?? 3 }))
      .sort((a, b) => a.rank - b.rank || b.t - a.t).slice(0, 3);
    const top5 = [...DEALS.rows].sort((a, b) => b.value_cr - a.value_cr).slice(0, 5).map((d, i) => ({ id: `deal-${d.date}-${d.kind}-${d.symbol}-${i}`, t: IST_EOD(d.date) }));
    const deal = [...top5].sort(newestFirst)[0];
    const circ = [...CIRCULARS.rows].map((c) => ({ c, t: c.issued_on ? IST_EOD(c.issued_on) : -Infinity })).sort(newestFirst);
    const circular = { id: `sebi-${circ[0].c.issued_on}-0`, t: circ[0].t };
    const flowDay = [...FLOWS.daily].sort((a, b) => b.date.localeCompare(a.date))[0].date;
    const expected = [...filings, deal, circular, { id: `fiidii-${flowDay}`, t: IST_EOD(flowDay) }].sort(newestFirst).map((e) => e.id);
    const rows = page.getByTestId("desk-events-card").getByTestId("desk-event");
    await expect(rows).toHaveCount(expected.length, SLOW);
    for (let k = 0; k < expected.length; k += 1) await expect(rows.nth(k)).toHaveAttribute("data-id", expected[k]);
    // A filing: its time, the affected stock with its icon (opens the chart), the exchange it was filed with and a link.
    const earn = page.locator(`[data-testid="desk-event"][data-id="${R_EARN.id}"]`);
    await expect(earn.getByTestId("desk-event-title")).toHaveText(String(R_EARN.docLabel));
    await expect(earn.getByTestId("desk-event-time")).toHaveText(day("2026-10-13"));
    await expect(earn.getByTestId("desk-event-symbol")).toHaveText("TESTPICK");
    await expect(earn.getByTestId("desk-event-stock").locator('[data-testid="entity-icon"]')).toHaveAttribute("data-key", "TESTPICK");
    await expect(earn.getByTestId("desk-event-source")).toContainText("NSE");
    await expect(earn.getByTestId("desk-event-source")).toContainText(String(R_EARN.docLabel));
    await expect(earn.getByTestId("desk-event-source").getByRole("link")).toHaveAttribute("href", String(R_EARN.url));
    // A market-wide event names no stock.
    await expect(page.locator(`[data-testid="desk-event"][data-id="fiidii-${flowDay}"]`).getByTestId("desk-event-stock-none")).toHaveText("Market-wide");
    // Source labels, never a "verified" claim (PRD §6.3 / the user's decision).
    await expect(page.getByTestId("desk-events-card")).not.toContainText(/verified/i);
    await expect(page.getByTestId("desk-events-trust")).toContainText("As reported");
    await earn.getByTestId("desk-event-stock").click();
    await expect(page).toHaveURL(/[?&]sym=TESTPICK/);
    await page.goto(`${DESK}?tab=overview`);
    await page.getByTestId("desk-events-all").click();
    await expect(page).toHaveURL(/[?&]tab=market&view=intel/); // Market Intelligence is a Market Desk view since 2026-10-27
  });

  // Superseded by the desk redesign (2026-10-27): Market Overview is the market part only; the portfolio snapshot and the
  // risk summary are not on it (the real portfolio is My portfolio). Covered by copilot-app-desk-shell.spec.ts SH-8 / SH-12.
  test.skip("OV-007 / OV-008: portfolio snapshot and risk summary from the holdings on record; nothing connected shows the empty state, never made-up holdings", async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 900 });
    await deskApi(page);
    await overviewExtras(page);
    await page.goto(`${DESK}?tab=overview`);
    const t = HOLDINGS.totals;
    const cr = (n: number) => `₹${(n / 1e7).toFixed(2)} Cr`;
    await expect(page.getByTestId("desk-snapshot-value")).toHaveText(cr(t.value_rs));
    await expect(page.getByTestId("desk-snapshot-pnl")).toHaveText(`+₹${(t.pnl_rs / 1e5).toFixed(2)} L · +${t.pnl_pct.toFixed(1)}% unrealised`);
    await expect(page.getByTestId("desk-snapshot-realised")).toContainText("Realised P&L —");
    await expect(page.getByTestId("desk-snapshot-sync")).toContainText("Zerodha · last read");
    // Allocation by asset type over the summed values of the fixture's holdings, largest first.
    const lab: Record<string, string> = { equity: "Stocks", mutual_fund: "Mutual funds", etf: "ETFs" };
    const by = new Map<string, number>();
    for (const h of HOLDINGS.holdings) if (h.value_rs != null) by.set(h.asset_type, (by.get(h.asset_type) ?? 0) + h.value_rs);
    const total = [...by.values()].reduce((a, b) => a + b, 0);
    const alloc = [...by.entries()].sort((a, b) => b[1] - a[1]);
    const items = page.getByTestId("desk-snapshot-alloc");
    await expect(items).toHaveCount(alloc.length);
    for (let k = 0; k < alloc.length; k += 1) await expect(items.nth(k)).toHaveText(`${lab[alloc[k][0]]} ${((alloc[k][1] / total) * 100).toFixed(1)}%`);
    // Top five holdings by value, with icons.
    const top = [...HOLDINGS.holdings].filter((h) => h.value_rs != null).sort((a, b) => (b.value_rs ?? 0) - (a.value_rs ?? 0)).slice(0, 5);
    const hold = page.getByTestId("desk-snapshot-holding");
    await expect(hold).toHaveCount(5);
    for (let k = 0; k < 5; k += 1) await expect(hold.nth(k)).toContainText(top[k].nse_symbol ?? top[k].name);
    // Risk summary: the largest direct stock against the 25% limit, the route's volatility band, liquidity "—" with its reason.
    const stocks = HOLDINGS.holdings.filter((h) => h.asset_type === "equity" && h.weight_pct != null).sort((a, b) => (b.weight_pct ?? 0) - (a.weight_pct ?? 0));
    await expect(page.getByTestId("desk-risk-position-value")).toHaveText(`${stocks[0].weight_pct!.toFixed(1)}% · Within limit`);
    await expect(page.getByTestId("desk-risk-volatility-value")).toHaveText(`${(RISK.weighted_volatility * 100).toFixed(1)}% a year · High`);
    await expect(page.getByTestId("desk-risk-liquidity-value")).toHaveText("—");
    await expect(page.getByTestId("desk-risk-liquidity")).toContainText("No traded-value figure is read for holdings yet");
    await expect(page.getByTestId("desk-risk-data")).toContainText(`risk figures cover ${RISK.coverage_pct.toFixed(1)}% of the value`);
    await expect(page.getByTestId("desk-snapshot-trust")).toContainText("Your holdings on record (broker reads and imports)");
    await expect(page.getByTestId("desk-risk-trust")).toContainText("Rules-based");

    // Nothing connected: the empty state on both cards, with the way to connect; no figures.
    await page.route("**/api/portfolio/holdings-enriched*", (route) => json(route, { holdings: [], alerts: [] }));
    await page.reload();
    await expect(page.getByTestId("desk-snapshot-empty")).toContainText("No portfolio connected");
    await expect(page.getByTestId("desk-risk-empty")).toContainText("No portfolio connected");
    await expect(page.getByTestId("desk-snapshot-value")).toHaveCount(0);
    await page.getByTestId("desk-snapshot-empty").getByRole("button", { name: /Connect a broker/ }).click();
    await expect(page).toHaveURL(/\/v5\/app\/page\/brokers$/);
  });

  test.skip("§3.2 / §16.3: every Overview card carries a trust line; the investor wording is plain, the data the same", async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 900 });
    await deskApi(page, { macro: withRegime(REGIMES.mixed) });
    await overviewExtras(page);
    await page.goto(`${DESK}?tab=overview`);
    // Desk redesign (2026-10-27): the portfolio snapshot and the risk summary left Market Overview (SH-8), so their trust lines are not here.
    for (const id of ["desk-index-trust", "desk-breadth-trust", "desk-pulse-trust", "desk-sector-trust", "desk-opps-trust", "desk-events-trust"]) {
      await expect(page.getByTestId(id), id).toHaveCount(1);
      await expect(page.getByTestId(id), id).not.toBeEmpty();
    }
    // Never "live" for end-of-day figures.
    for (const id of ["desk-pulse-trust", "desk-sector-trust", "desk-opps-trust"]) await expect(page.getByTestId(id)).toHaveAttribute("data-mode", "eod");
    await expect(page.getByTestId("desk-regime-evidence")).toContainText("Supporting evidence");
    await expect(page.getByTestId("desk-regime-invalidation")).toContainText("Invalidation");

    await page.goto(`${DESK}?tab=overview&persona=investor`);
    await expect(page.getByTestId("desk-regime-label")).toHaveText("Mixed");
    await expect(page.getByTestId("desk-regime-meaning")).toHaveText("The Nifty 50 and the wider market are pointing different ways (the index is above its 50-day average while most stocks fell), so the picture is unclear.");
    await expect(page.getByTestId("desk-regime-evidence")).toContainText("What the rule looked at");
    await expect(page.getByTestId("desk-regime-input-volatility")).toContainText("Expected swings (India VIX)");
    await expect(page.getByTestId("desk-regime-invalidation")).toContainText("What would change this");
    const pick = page.locator('[data-testid="desk-opp"][data-symbol="TESTPICK"]');
    await expect(pick.getByTestId("desk-opp-setup")).toHaveText("Shape: Broke above a recent high");
    await expect(pick.getByTestId("desk-opp-horizon")).toHaveText("Time frame: 5–15 sessions");
    await expect(pick.getByTestId("desk-opp-evidence")).toHaveText("+ Why it shows up: Fixture scanner reason");
    await expect(pick.getByTestId("desk-opp-against")).toContainText("− What could go wrong: RSI 76 — overextended");
    // Same figures.
    await expect(pick.getByTestId("desk-opp-score")).toHaveText("Score 81/100");
    await expect(page.getByTestId("desk-regime-input-breadth")).toContainText(`${int(REGIMES.mixed.inputs.advances!)} up`);
  });

  test.skip("TC-12: a failed market overview shows an error with retry while the regime and sectors still render", async ({ page }) => {
    const calls = await deskApi(page, { home: { status: 500, body: { detail: "fixture failure" } }, macro: withRegime(REGIMES.bullish) });
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
    await expect(page.getByTestId("desk-intel-title")).toHaveText("04 · AI Event intelligence");
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
    await expect(page.getByTestId("screen-trading-desk")).toHaveAttribute("data-view", "research"); // the Chart tab is Market Desk › Stock Research since 2026-10-27
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

// RETIRED by the desk redesign step 2 (Market Overview, 2026-10-27): the old Overview cards (tradingdesk/OverviewTab.tsx) are
// no longer mounted on the desk. Market Overview's strip and events replace them (copilot-app-desk-market-overview.spec.ts,
// which also carries TC-3 … TC-5's Kite-close rule as MO-2b … MO-2d). OverviewTab is deleted or re-hosted in step 6.
test.describe.skip("Smart trading desk — Overview and Market intelligence at 390px", () => {
  test("TC-7: no sideways scroll on either tab", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await deskApi(page, { macro: withRegime(REGIMES.bullish) });
    await overviewExtras(page);
    await page.goto(`${DESK}?tab=overview`);
    // The phone's bottom bar and the key events card are part of the Overview at 390.
    await expect(page.getByTestId("desk-bottom-bar")).toBeVisible();
    await expect(page.getByTestId("desk-events-card").getByTestId("desk-event")).toHaveCount(3, SLOW);
    // The phone's Overview is design §11 M1: index tiles, pulse, top opportunities, portfolio and risk tiles (no sector card).
    await expect(page.getByTestId("desk-overview")).toHaveAttribute("data-layout", "mobile");
    await expect(page.getByTestId("desk-index-tile")).toHaveCount(4);
    await expect(page.getByTestId("desk-regime-label")).toHaveText("Bullish");
    // WATCH_OV's four rows and TESTPICK: the phone shows the five best.
    await expect(page.getByTestId("desk-top-opp")).toHaveCount(5);
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
    await expect(page.getByTestId("desk-intel-title")).toHaveText("04 · Top market events");
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

// ── Kite's closing quote vs the tile's OWN daily-bar day (fix: index tape end-of-day day) ────────────────────────────
// MOCK — not real data: the home payload's `as_of` is the breadth/dashboard day (19 Oct, stale); each tile carries `as_of`, its own latest daily bar.
// RETIRED by the desk redesign step 2 (Market Overview, 2026-10-27): the old Overview cards (tradingdesk/OverviewTab.tsx) are
// no longer mounted on the desk. Market Overview's strip and events replace them (copilot-app-desk-market-overview.spec.ts,
// which also carries TC-3 … TC-5's Kite-close rule as MO-2b … MO-2d). OverviewTab is deleted or re-hosted in step 6.
test.describe.skip("Smart trading desk — Overview · index tiles and Kite's closing quote", () => {
  const finalSnapshot = {
    as_of: "2026-10-23T11:02:24+00:00", data_at: "2026-10-23T11:02:27+00:00", age_seconds: 1, stale: false, stale_after_seconds: 75, cadence_seconds: 30,
    mode: "closed", session: "closed", source: "rest", final: true, count: 1, missing: [], read_only: true,
    quotes: { "NIFTY 50": { ltp: 22600, change: -87.65, change_pct: -0.39, open: 22690, high: 22710, low: 22580, close: 22687.65, volume: 0, oi: null, ts: "2026-10-23T15:29:00+05:30" } },
  };
  async function open(page: Page, tileDay: string | null) {
    const home = { ...HOME, as_of: "2026-10-19", indices: HOME.indices.map((i) => ({ ...i, as_of: tileDay })) };
    if (tileDay === null) for (const i of home.indices) delete (i as { as_of?: unknown }).as_of;
    await deskApi(page, { home: { body: home, status: 200 } });
    await page.route("**/api/live/**", (route) => route.fulfill(
      new URL(route.request().url()).pathname.endsWith("/stream")
        ? { status: 200, contentType: "text/event-stream", body: `retry: 100\n\nevent: snapshot\ndata: ${JSON.stringify(finalSnapshot)}\n\n` }
        : { status: 200, contentType: "application/json", body: JSON.stringify(finalSnapshot) }));
    await page.goto(`${DESK}?tab=overview`);
    await expect(page.getByTestId("desk-index-tile").first()).toBeVisible();
  }
  const nifty = (page: Page) => page.locator('[data-testid="desk-index-tile"][data-index="Nifty 50"]');

  test("TC-3 the tile already has its own 23 Oct bar: Kite's 23 Oct close is NOT shown, even though the page's day is 19 Oct", async ({ page }) => {
    await open(page, "2026-10-23");
    const stamp = nifty(page).getByTestId("desk-index-stamp");
    await expect(stamp).toHaveAttribute("data-mode", "eod");
    await expect(stamp).not.toHaveAttribute("data-live", /.+/);
    await expect(stamp).not.toContainText("Kite");
    await expect(nifty(page).getByTestId("desk-index-value")).toHaveText(level(HOME.indices[0].value as number));
  });

  test("TC-4 the tile's own bar is older than Kite's final snapshot: Kite's close is shown, labelled Close", async ({ page }) => {
    await open(page, "2026-10-22");
    const stamp = nifty(page).getByTestId("desk-index-stamp");
    await expect(stamp).toHaveAttribute("data-live", "close");
    await expect(stamp).toContainText("Close · 23 Oct · Kite");
    await expect(nifty(page).getByTestId("desk-index-value")).toHaveText("22,600.00");
  });

  test("TC-5 an older backend without a tile date falls back to the page's day, as before", async ({ page }) => {
    await open(page, null);
    await expect(nifty(page).getByTestId("desk-index-stamp")).toHaveAttribute("data-live", "close");
  });
});
