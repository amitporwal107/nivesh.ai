/**
 * One-screen Copilot app (/v5/app) — Smart trading desk, tabs 05 Portfolio & risk
 * and 06 Options & futures lab (screens/tradingdesk/PortfolioTab.tsx, FnoTab.tsx).
 *
 * MOCK — not real data: every /api response here is a fixture or an inline
 * payload in the shape the real route returns (route file named beside each),
 * with synthetic values. Expected figures are worked out from the payload in
 * this file (or the fixture it loads), not copied from the screen. Mocked APIs,
 * production build — see pw.copilot-app.config.ts.
 *
 * Covers: TC-28 holdings with weights (>25% amber), the sector concentration
 * check, beta and VaR from the payloads; correlated positions from GET
 * /api/portfolio/correlation; the market-cap split from GET
 * /api/portfolio/market-cap-split (split, and not yet split); your paper trades
 * (GET /api/desk/paper-trades, Close → POST …/{id}/close) and price alerts (GET
 * /api/desk/alerts, Delete → DELETE …/{id}) with their confirmations; TC-29 an
 * empty portfolio's connect button; the paper evaluation's 403 note and its
 * forward / replay calibration; TC-7 no sideways scroll at 390px on the
 * Portfolio & risk tab. The Options & futures lab (FnoTab.tsx: TC-30 … TC-33,
 * its paper strategies and its 390px pass) is covered by
 * copilot-app-desk-lab.spec.ts.
 */
import { test, expect, type Page, type Route } from "@playwright/test";
import fs from "fs";
import path from "path";
import { mockApi, mockSingleRoute } from "../helpers/api-mock";

const DESK = "/v5/app/trader/desk";
const FX = path.join(process.cwd(), "e2e", "fixtures");
const load = (name: string) => JSON.parse(fs.readFileSync(path.join(FX, name), "utf-8"));
const has = (name: string) => fs.existsSync(path.join(FX, name));

const json = (page: Page, pattern: string | RegExp, body: unknown, status = 200) =>
  page.route(pattern, (route) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) }));

// ── the desk's own reads (header) and the shell ─────────────────────────

// Shapes: backend/routes/positional.py (get_watchlist, get_picks), positional_journal.py (trade_summary).
const WATCHLIST = { as_of_date: "2026-10-12", buckets: { breakout_confirmed: [{ nse_symbol: "TESTBRK", sector: "Capital Goods", close_price: 510.0, trigger_price: 500.0, stop_price: 477.5, atr_pct: 2.94, why: "Fixture reason" }], pre_breakout: [], true_accumulation: [], trend_continuation: [] } };
const PICKS = { signal_date: "2026-10-12", count: 1, picks: [{ nse_symbol: "TESTPICK", signal_date: "2026-10-12", final_score: 0.812, confidence: "HIGH", stage: "BREAKOUT", timeframe_days_min: 5, timeframe_days_max: 15, entry_price: 505.0, stoploss: 480.0, target_price: 555.0, risk_reward: 2.0, source_scans: ["btst.breakout_confirmation"], reasons: ["Fixture scanner reason"] }] };
const JOURNAL_SUMMARY = { open_count: 1, closed_count: 2, gross_long_rs: 10000, invested_rs: 10000, realized_pnl_rs: 600, win_count: 1, loss_count: 1, win_rate_pct: 50.0, needs_hedge: false, suggested_hedge: null };
// ── the broker block's live reads (MOCK — not real data) ────────────────
// GET /api/broker/holdings (broker_connect.py :: get_all_holdings) and GET /api/broker/positions (get_all_positions)
// list every account of the user. The fixture account (copilot-trader-broker-accounts.json) is connected through
// OpenAlgo, so both list it as not read live.
const AS_OF = "2026-10-12T10:15:00+00:00"; // 12 Oct 3:45 pm IST
const FIXTURE_ACCOUNT = { account_id: "ba_fixture00001", broker: "zerodha", broker_display: "Zerodha", label: "Zerodha" };
const NOT_SUPPORTED = { code: "BROKER_READ_NOT_SUPPORTED", message: "fixture: not read live" };
const NOT_LIVE_HOLDINGS = { as_of: AS_OF, accounts: [{ ...FIXTURE_ACCOUNT, ok: false, error: NOT_SUPPORTED, as_of: AS_OF, holdings: [], counts: { total: null }, totals: { invested_rs: null, value_rs: null, pnl_rs: null, pnl_pct: null } }] };
const NOT_LIVE_POSITIONS = { as_of: AS_OF, kind: "net", segment: "all", accounts: [{ ...FIXTURE_ACCOUNT, ok: false, error: NOT_SUPPORTED, as_of: AS_OF, positions: [], counts: { total: 0, fno: 0, intraday: 0 } }] };

/** The same account connected on the broker's own page and read live: two holdings, a share position and a future. */
const LIVE_ACCOUNTS = { accounts: [{ ...load("copilot-trader-broker-accounts.json").accounts[0], openalgo_hosted: false, native: true }] };
const LIVE_HOLDINGS = { as_of: AS_OF, accounts: [{ ...FIXTURE_ACCOUNT, ok: true, error: null, as_of: AS_OF, counts: { total: 2 },
  holdings: [
    // 10 at 100, last 120: cost 1,000, value 1,200, +200, +20.0%
    { isin: null, symbol: "FIXHEAVY", name: "Fixture Heavy Ltd", exchange: "NSE", asset_type: "equity", sector: null, quantity: 10, avg_price: 100, current_price: 120, price_source: "broker", invested_rs: 1000, value_rs: 1200, pnl_rs: 200, pnl_pct: 20, source_id: "NSE:FIXHEAVY" },
    // 5 at 200, last 180: cost 1,000, value 900, −100, −10.0%
    { isin: null, symbol: "FIXLIGHT", name: "Fixture Light Ltd", exchange: "NSE", asset_type: "equity", sector: null, quantity: 5, avg_price: 200, current_price: 180, price_source: "broker", invested_rs: 1000, value_rs: 900, pnl_rs: -100, pnl_pct: -10, source_id: "NSE:FIXLIGHT" },
  ],
  // 1,000 + 1,000 = 2,000; 1,200 + 900 = 2,100; +100; 100 / 2,000 = +5.0%
  totals: { invested_rs: 2000, value_rs: 2100, pnl_rs: 100, pnl_pct: 5 } }] };
const LIVE_POSITIONS = { as_of: AS_OF, kind: "net", segment: "all", accounts: [{ ...FIXTURE_ACCOUNT, ok: true, error: null, as_of: AS_OF, counts: { total: 2, fno: 1, intraday: 0 },
  positions: [
    { symbol: "FIXHEAVY", name: "Fixture Heavy Ltd", exchange: "NSE", quantity: 5, avg_price: 118, last_price: 120, pnl: 10, product: "delivery", product_raw: "CNC", segment: "equity", is_intraday: false, instrument_type: null, expiry: null, strike: null, kind: "net" },
    { symbol: "FIXIDX26OCTFUT", name: "Fixture Index", exchange: "NFO", quantity: -75, avg_price: 25100, last_price: 25050, pnl: 3750, product: "carryforward", product_raw: "NRML", segment: "fno", is_intraday: false, instrument_type: "FUT", expiry: "2026-10-27", strike: null, kind: "net" },
  ] }] };

async function deskBase(page: Page) {
  await mockApi(page, "populated");
  await mockSingleRoute(page, "**/api/markets/home", "markets-home.json");
  await page.route("**/api/chat/sessions", (route) => route.fulfill({ status: 200, contentType: "application/json", body: "[]" }));
  await json(page, "**/api/positional/watchlist*", WATCHLIST);
  await json(page, "**/api/positional/picks*", PICKS);
  await json(page, "**/api/move-odds/latest*", { detail: "Feature not enabled for this account" }, 403);
  await json(page, "**/api/positional/journal/summary/portfolio", JOURNAL_SUMMARY);
  // The broker block (desk/BrokerPositions): accounts, live holdings and positions, the holdings a sync stored.
  await json(page, "**/api/broker/positions*", NOT_LIVE_POSITIONS);
  await json(page, "**/api/broker/holdings*", NOT_LIVE_HOLDINGS);
  await json(page, "**/api/broker/accounts", load("copilot-trader-broker-accounts.json"));
  await json(page, "**/api/portfolio/holdings", load("copilot-trader-holdings.json"));
}

/** Paper-trade routes over the captured fixtures (as copilot-app-trader.spec.ts), or one override for the evaluation. */
async function mockPaper(page: Page, evaluation?: { status: number; body: unknown }) {
  await page.route("**/api/paper-trades/**", (route) => {
    const u = new URL(route.request().url());
    const q = (k: string) => u.searchParams.get(k);
    const reply = (body: unknown, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
    if (u.pathname.endsWith("/evaluation")) {
      if (evaluation) return reply(evaluation.body, evaluation.status);
      const f = `paper-evaluation-${q("sample")}-${q("portfolio")}.json`;
      return reply(has(f) ? load(f) : { data: { status: "none", sample: q("sample"), portfolio: q("portfolio") } });
    }
    return reply({ detail: "not_found" }, 404);
  });
}

/** Sideways overflow of the page and of the shell's scroller, as the brief asks: scrollWidth − innerWidth / clientWidth. */
async function sideways(page: Page) {
  return page.evaluate(() => {
    const sc = document.querySelector('[data-testid="copilot-scroll"]') as HTMLElement | null;
    return {
      doc: document.documentElement.scrollWidth - window.innerWidth,
      scroll: sc ? sc.scrollWidth - sc.clientWidth : 0,
    };
  });
}

// ── portfolio payloads ───────────────────────────────────────────────────

/**
 * GET /api/portfolio/holdings-enriched (backend/routes/portfolio.py → portfolio_enrichment), three holdings:
 * two direct stocks and a fund. weight_pct is the route's share of the whole portfolio (₹10,00,000).
 *   FIXHEAVY ₹3,00,000 = 30.0% → above the 25% single-stock limit (amber)
 *   FIXLIGHT ₹1,00,000 = 10.0%
 *   fund     ₹6,00,000 = 60.0% (not a direct stock, so not in the positions list)
 * Totals: value ₹10,00,000 = ₹10.00 L; P&L +₹1,40,000 = +₹1.40 L on ₹8,60,000 invested = +16.28% → +16.3%.
 * Direct stocks ₹4,00,000 = ₹4.00 L = 40.0% of the value.
 */
const HOLDINGS = {
  holdings: [
    { holding_id: "hold_fixheavy", name: "Fixture Heavy Ltd", asset_type: "equity", quantity: 100, current_price: 3000, value_rs: 300000, invested_rs: 250000, pnl_rs: 50000, pnl_pct: 20.0, weight_pct: 30.0, nse_symbol: "FIXHEAVY", sector: "Financial", category: null },
    { holding_id: "hold_fixlight", name: "Fixture Light Ltd", asset_type: "equity", quantity: 50, current_price: 2000, value_rs: 100000, invested_rs: 110000, pnl_rs: -10000, pnl_pct: -9.09, weight_pct: 10.0, nse_symbol: "FIXLIGHT", sector: "Technology", category: null },
    { holding_id: "hold_fixfund", name: "Fixture Flexi Cap Fund", asset_type: "mutual_fund", quantity: 1000, current_price: 600, value_rs: 600000, invested_rs: 500000, pnl_rs: 100000, pnl_pct: 20.0, weight_pct: 60.0, nse_symbol: null, sector: "Flexi Cap", category: "equity" },
  ],
  totals: { count: 3, value_rs: 1000000, invested_rs: 860000, pnl_rs: 140000, pnl_pct: 16.28, xirr_pct: null },
};

/**
 * GET /api/portfolio/exposure/concentration (routes/portfolio_exposure.py :: compute_concentration), sector axis only.
 * HHI = 0.48² + 0.22² + 0.15² + 0.10² + 0.05² = 0.3138 → 3,138; effective N = 1 / 0.3138 = 3.19 → 3.2.
 * Financial 48.0% is above the 35% caution level → Over-concentrated; the five listed add to 100%, so no "Other sectors" slice.
 */
const CONCENTRATION = {
  total_value: 1000000,
  holdings_count: 3,
  lookthrough_coverage: 60.0,
  sector: {
    items: [
      { name: "Financial", pct: 48.0, value_inr: 480000 },
      { name: "Technology", pct: 22.0, value_inr: 220000 },
      { name: "Energy", pct: 15.0, value_inr: 150000 },
      { name: "Healthcare", pct: 10.0, value_inr: 100000 },
      { name: "Unclassified", pct: 5.0, value_inr: 50000 },
    ],
    all_items_count: 5, hhi: 0.3138, hhi_x10000: 3138, effective_n: 3.2, largest_pct: 48.0, top5_pct: 100.0, caution_pct: 35,
    warning: "Financial accounts for 48.0% of your Sector exposure — above 35% raises concentration risk.",
  },
};

/**
 * GET /api/portfolio/risk-analytics (backend/routes/portfolio_risk_analytics.py:51).
 * Volatility 0.185 a year → 18.5%, band HIGH (0.18–0.28). 1-day VaR at 95%: σ₁ = 0.185 / √252 = 0.011654;
 * × 1.645 = 0.019171 → 1.92%; × ₹10,00,000 = ₹19,171.
 */
const RISK = {
  empty: false, total_value: 1000000, risk_score: 4.6, risk_rating: "HIGH",
  weighted_beta: 1.32, weighted_sharpe: 0.81, weighted_volatility: 0.185,
  max_drawdown_pct: null, var_1d_rs: 19171, var_1d_pct: 1.92, portfolio_value_rs: 1000000, var_confidence: 0.95,
  equity_pct: 100.0, debt_pct: 0, gold_pct: 0, other_pct: 0,
  risk_drivers: [
    { type: "SMALLCAP_WEIGHT", label: "Smallcap weight", pct: 30.0, impact: "MEDIUM" },
    { type: "HIGH_BETA_NAMES", label: "High-beta names", pct: 40.0, impact: "MEDIUM" },
    { type: "DEBT_GOLD_BUFFER", label: "Debt + gold buffer", pct: 0.0, impact: "HIGH" },
  ],
  top_contributors: [],
  fund_breakdown: [],
  stock_breakdown: [
    { name: "Fixture Heavy Ltd", ticker: "FIXHEAVY", value_rs: 300000, weight_pct: 30.0, beta_1y: 1.5, sharpe_1y: 0.9, volatility_1y: 0.24, sector: "Financial" },
    { name: "Fixture Light Ltd", ticker: "FIXLIGHT", value_rs: 100000, weight_pct: 10.0, beta_1y: 0.9, sharpe_1y: 0.6, volatility_1y: 0.16, sector: "Technology" },
  ],
  coverage_pct: 100.0, data_source: "DAAS", period: null,
};

/**
 * GET /api/portfolio/correlation?sessions=120&limit=10 (backend/routes/portfolio_desk.py). Three compared stocks → three
 * pairs; average (0.82 + 0.55 − 0.14) ÷ 3 = 0.41; one pair at 0.70 or above. FIXNEW is skipped with the route's reason.
 */
const CORRELATION = {
  as_of: "2026-10-13", sessions: 120, min_sessions: 60,
  method: "Pearson correlation of daily log returns, split and bonus adjusted closes", source: "nidp.prices_eod_adjusted via DaaS",
  holdings_used: 3, holdings_skipped: [{ symbol: "FIXNEW", reason: "fewer than 60 sessions of prices in the window" }],
  high_threshold: 0.7, high_pairs: 1, avg_corr: 0.41, pairs_total: 3, pairs_excluded: 0,
  pairs: [
    { a: "FIXHEAVY", b: "FIXLIGHT", corr: 0.82, common_sessions: 118, weight_a_pct: 30.0, weight_b_pct: 10.0 },
    { a: "FIXHEAVY", b: "FIXMID", corr: 0.55, common_sessions: 120, weight_a_pct: 30.0, weight_b_pct: 5.0 },
    { a: "FIXLIGHT", b: "FIXMID", corr: -0.14, common_sessions: 118, weight_a_pct: 10.0, weight_b_pct: 5.0 },
  ],
};

/**
 * GET /api/portfolio/market-cap-split as it answers today (the lead's note, 2026-10-14): the Nifty Midcap 150 and Smallcap
 * 250 lists are not in the warehouse, so only large cap is split and the rest is `unsplit`. Large ₹3,00,000 (75%) +
 * unsplit ₹1,00,000 (25%) = the ₹4,00,000 of direct stocks.
 */
const ABSENT = "Nifty Midcap 150, Nifty Smallcap 250 constituents are not in the warehouse yet";
const MCAP_PARTIAL = {
  as_of: "2026-10-13",
  method: "NSE index membership: Large = Nifty 100, Mid = Nifty Midcap 150, Small = Nifty Smallcap 250, Micro = rest of Nifty Total Market, Unclassified = in none of them",
  source: "Holdings and values as in /api/portfolio/holdings-enriched; index membership from nidp.index_constituents (NSE index lists) via DaaS",
  total_value_rs: 400000, available: false, reason: `${ABSENT}; mid, small, micro and unclassified are not split`,
  buckets: [
    { bucket: "large", available: true, value_rs: 300000, weight_pct: 75.0, count: 1, symbols: ["FIXHEAVY"] },
    { bucket: "mid", available: false, value_rs: null, weight_pct: null, count: null, symbols: null, reason: "Nifty Midcap 150 constituents are not in the warehouse yet" },
    { bucket: "small", available: false, value_rs: null, weight_pct: null, count: null, symbols: null, reason: ABSENT },
    { bucket: "micro", available: false, value_rs: null, weight_pct: null, count: null, symbols: null, reason: ABSENT },
    { bucket: "unclassified", available: false, value_rs: null, weight_pct: null, count: null, symbols: null, reason: ABSENT },
  ],
  unsplit: { value_rs: 100000, weight_pct: 25.0, count: 1, symbols: ["FIXLIGHT"], reason: `${ABSENT}, so these holdings cannot be placed in a bucket` },
  indices: [
    { bucket: "large", index: "Nifty 100", as_of: "2026-10-13", available: true, members: 100 },
    { bucket: "mid", index: "Nifty Midcap 150", as_of: null, available: false, members: null },
    { bucket: "small", index: "Nifty Smallcap 250", as_of: null, available: false, members: null },
    { bucket: "micro", index: "Nifty Total Market", as_of: "2026-10-13", available: true, members: 750 },
  ],
  excluded: { funds_value_rs: 600000, holdings: 1, note: "Mutual funds, ETFs and other non-stock holdings are not split by market cap" },
};
/** The same once every list is on record: five buckets, no `unsplit`. */
const MCAP_FULL = {
  ...MCAP_PARTIAL, available: true, reason: null, unsplit: null,
  buckets: [
    { bucket: "large", available: true, value_rs: 240000, weight_pct: 60.0, count: 1, symbols: ["FIXHEAVY"] },
    { bucket: "mid", available: true, value_rs: 100000, weight_pct: 25.0, count: 1, symbols: ["FIXLIGHT"] },
    { bucket: "small", available: true, value_rs: 40000, weight_pct: 10.0, count: 1, symbols: ["FIXSML"] },
    { bucket: "micro", available: true, value_rs: 20000, weight_pct: 5.0, count: 1, symbols: ["FIXMIC"] },
    { bucket: "unclassified", available: true, value_rs: 0, weight_pct: 0.0, count: 0, symbols: [] },
  ],
  indices: MCAP_PARTIAL.indices.map((ix) => ({ ...ix, as_of: "2026-10-13", available: true, members: ix.members ?? (ix.index === "Nifty Midcap 150" ? 150 : 250) })),
};

// ── your paper trades and alerts (backend/routes/desk_trading.py) ────────

type Trade = Record<string, unknown> & { id: string; symbol: string; quantity: number; entry_price: number; status: string; last_close: number | null; unrealized_pnl_rs: number | null; realized_pnl_rs: number | null };
const trade = (o: Partial<Trade> & { id: string; symbol: string; quantity: number; entry_price: number }): Trade => ({
  stop_price: null, target_price: null, note: null, source: { kind: "scanner", bucket: "breakout_confirmed", signal_date: "2026-10-12" },
  opened_at: "2026-10-12T10:00:00+00:00", status: "open", closed_at: null, exit_price: null, exit_reason: null, exit_session: null, exit_note: null,
  last_close: null, last_close_date: null, unrealized_pnl_rs: null, realized_pnl_rs: null, checked_through: null, mark_error: null, ...o,
});
const BOTH = "The stop and the target were both inside this session's range; counted as the stop (conservative).";
/** Fresh each test: two open trades marked at the 13 Oct close, two closed (one at the stop on a both-touched session). */
function paperTrades(): Trade[] {
  return [
    // (512.40 − 505) × 200 = +1,480
    trade({ id: "pt-001", symbol: "FIXBRK", quantity: 200, entry_price: 505, stop_price: 480, target_price: 555, last_close: 512.4, last_close_date: "2026-10-13", unrealized_pnl_rs: 1480, checked_through: "2026-10-13" }),
    // (118.20 − 120) × 833 = −1,499.40
    trade({ id: "pt-002", symbol: "FIXPICK", quantity: 833, entry_price: 120, stop_price: 114, target_price: 138, last_close: 118.2, last_close_date: "2026-10-13", unrealized_pnl_rs: -1499.4, checked_through: "2026-10-13", source: { kind: "scanner", signal_date: "2026-10-12" } }),
    // (84 − 90) × 100 = −600, at the stop
    trade({ id: "pt-000", symbol: "FIXACC", quantity: 100, entry_price: 90, stop_price: 84, target_price: 99, status: "closed", opened_at: "2026-10-06T10:00:00+00:00", closed_at: "2026-10-09T15:00:00+00:00", exit_price: 84, exit_reason: "stop", exit_session: "2026-10-09", exit_note: BOTH, realized_pnl_rs: -600 }),
    // (1,260 − 1,200) × 20 = +1,200, at the target
    trade({ id: "pt-00a", symbol: "FIXTRD", quantity: 20, entry_price: 1200, stop_price: 1150, target_price: 1260, status: "closed", opened_at: "2026-10-01T10:00:00+00:00", closed_at: "2026-10-08T15:00:00+00:00", exit_price: 1260, exit_reason: "target", exit_session: "2026-10-08", realized_pnl_rs: 1200 }),
  ];
}
/** The route's summary, worked out over the trades the same way (services/desk_trading.py :: summarize). */
function summarize(trades: Trade[]) {
  const open = trades.filter((t) => t.status === "open");
  const closed = trades.filter((t) => t.status === "closed");
  const realized = closed.map((t) => t.realized_pnl_rs as number);
  const unmarked = open.filter((t) => t.unrealized_pnl_rs == null).length;
  return {
    open: open.length, closed: closed.length, wins: realized.filter((r) => r > 0).length, losses: realized.filter((r) => r < 0).length,
    realized_pnl_rs: realized.length ? Math.round(realized.reduce((a, b) => a + b, 0) * 100) / 100 : null,
    unrealized_pnl_rs: open.length && !unmarked ? Math.round(open.reduce((a, t) => a + (t.unrealized_pnl_rs as number), 0) * 100) / 100 : null,
    unmarked_open: unmarked, partial: false,
  };
}

const alert = (o: Record<string, unknown> & { id: string; symbol: string; condition: string; level: number; status: string }) => ({
  note: null, created_at: "2026-10-12T09:00:00+00:00", fired_at: null, fired_session: null, fired_price: null,
  last_close: null, last_close_date: null, checked_through: null, mark_error: null, ...o,
});
function priceAlerts() {
  return [
    alert({ id: "al-001", symbol: "FIXBRK", condition: "above", level: 530, status: "active", last_close: 512.4, last_close_date: "2026-10-13", checked_through: "2026-10-13" }),
    alert({ id: "al-003", symbol: "FIXACC", condition: "below", level: 84, status: "active", last_close: 88.5, last_close_date: "2026-10-13", checked_through: "2026-10-13" }),
    alert({ id: "al-002", symbol: "FIXPRE", condition: "above", level: 250, status: "fired", fired_at: "2026-10-13T15:30:00+00:00", fired_session: "2026-10-13", fired_price: 250 }),
  ];
}

interface DeskCalls { closes: Array<{ path: string; body: unknown }>; deletes: string[]; paperReads: number; alertReads: number }

/**
 * The desk lists, stateful like the real routes: a close moves the trade to closed at its last close ("manual"), a
 * delete removes the alert. `closeReply` / `paperList` / `alertList` override an answer.
 */
async function mockDeskLists(page: Page, opts: { closeReply?: { status: number; body: unknown }; paperList?: { status: number; body: unknown }; alertList?: { status: number; body: unknown }; empty?: boolean } = {}): Promise<DeskCalls> {
  const calls: DeskCalls = { closes: [], deletes: [], paperReads: 0, alertReads: 0 };
  let trades = opts.empty ? [] : paperTrades();
  let alerts = opts.empty ? [] : priceAlerts();
  const reply = (route: Route, body: unknown, status = 200) =>
    route.fulfill({ status, contentType: "application/json", body: status === 204 ? "" : JSON.stringify(body) });
  await page.route("**/api/desk/paper-trades*", (route) => {
    calls.paperReads += 1;
    if (opts.paperList) return reply(route, opts.paperList.body, opts.paperList.status);
    return reply(route, {
      as_of: "2026-10-13", checked_through: "2026-10-13", source: "NSE end-of-day bhavcopy, raw traded prices (nidp.prices_eod via the data platform)", price_basis: "end of day",
      exit_rule: "fixture", marks_error: null, status: "all", trades, summary: summarize(trades), limits: { max_open: 100 }, evaluated_at: "2026-10-14T10:00:00+00:00",
    });
  });
  await page.route("**/api/desk/paper-trades/*/close", (route) => {
    const path = new URL(route.request().url()).pathname;
    calls.closes.push({ path, body: route.request().postDataJSON() });
    if (opts.closeReply) return reply(route, opts.closeReply.body, opts.closeReply.status);
    const id = path.split("/").slice(-2)[0];
    trades = trades.map((t) => (t.id === id
      ? { ...t, status: "closed", closed_at: "2026-10-14T10:05:00+00:00", exit_price: t.last_close, exit_reason: "manual", exit_session: "2026-10-13",
          realized_pnl_rs: Math.round(((t.last_close as number) - t.entry_price) * t.quantity * 100) / 100, last_close: null, last_close_date: null, unrealized_pnl_rs: null }
      : t));
    return reply(route, { trade: trades.find((t) => t.id === id) });
  });
  const alertsRoute = (route: Route) => {
    if (route.request().method() === "DELETE") {
      const id = new URL(route.request().url()).pathname.split("/").pop() ?? "";
      calls.deletes.push(id);
      alerts = alerts.filter((a) => a.id !== id);
      return reply(route, null, 204);
    }
    calls.alertReads += 1;
    if (opts.alertList) return reply(route, opts.alertList.body, opts.alertList.status);
    return reply(route, {
      as_of: "2026-10-13", checked_through: "2026-10-13", source: "NSE end-of-day bhavcopy, raw traded prices (nidp.prices_eod via the data platform)", price_basis: "end of day",
      firing_rule: "fixture", marks_error: null, status: "all", alerts,
      counts: { active: alerts.filter((a) => a.status === "active").length, fired: alerts.filter((a) => a.status === "fired").length }, limits: { max_active: 50 },
    });
  };
  await page.route("**/api/desk/alerts*", alertsRoute);
  await page.route("**/api/desk/alerts/*", alertsRoute);
  return calls;
}

// ── expected-value helpers (the screen's formats, written out) ──────────
const MINUS = "−";
const rupees = (n: number, signed = false) => `${n < 0 ? MINUS : signed && n > 0 ? "+" : ""}₹${Math.round(Math.abs(n)).toLocaleString("en-IN")}`;
const paise = (n: number) => `₹${n.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
const lakh = (n: number) => `₹${(n / 1e5).toFixed(2)} L`;
const dec2 = (n: number) => new Intl.NumberFormat("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(n);
const dayY = (iso: string) => new Date(`${iso.slice(0, 10)}T12:00:00+05:30`).toLocaleDateString("en-IN", { timeZone: "Asia/Kolkata", day: "numeric", month: "short", year: "numeric" });

async function portfolioData(page: Page, opts: { holdings?: unknown; concentration?: unknown; risk?: unknown; correlation?: { status: number; body: unknown }; mcap?: { status: number; body: unknown } } = {}) {
  if (opts.holdings) await json(page, "**/api/portfolio/holdings-enriched*", opts.holdings);
  if (opts.concentration) await json(page, "**/api/portfolio/exposure/concentration", opts.concentration);
  await json(page, "**/api/portfolio/risk-analytics*", opts.risk ?? RISK);
  await json(page, "**/api/portfolio/correlation*", opts.correlation?.body ?? CORRELATION, opts.correlation?.status ?? 200);
  await json(page, "**/api/portfolio/market-cap-split*", opts.mcap?.body ?? MCAP_PARTIAL, opts.mcap?.status ?? 200);
}

/** The colour var(--amber) resolves to in the page's current theme. */
const amberColour = (page: Page) => page.evaluate(() => {
  const s = document.createElement("span");
  s.style.color = "var(--amber)";
  document.body.appendChild(s);
  const c = getComputedStyle(s).color;
  s.remove();
  return c;
});

/** Shares of the portfolio the market-cap route valued: direct stocks (total_value_rs) + the funds it leaves out. */
const capShare = (m: { total_value_rs: number; excluded: { funds_value_rs: number } }, v: number) => (v / (m.total_value_rs + m.excluded.funds_value_rs)) * 100;
const pct1 = (n: number, signed = false) => `${n < 0 ? MINUS : signed && n > 0 ? "+" : ""}${Math.abs(n).toFixed(1)}%`;
/** The seven risk checks of design-spec §7, in order. */
const RISK_ROWS = [
  ["overall", "Overall risk"], ["position", "Position concentration"], ["sector", "Sector concentration"], ["correlation", "Correlated positions"],
  ["gap", "Gap risk"], ["volatility", "Volatility · 1Y"], ["liquidity", "Liquidity"],
] as const;
type Bucket = { n: number; lo: number; hi: number; predicted_mean?: number; model_label_rate?: number };
/** Predicted vs realised over the selected buckets, each weighted by its predictions (portfolio-data.ts :: recordTiles). */
function tilesOf(buckets: Bucket[]) {
  const used = buckets.filter((b) => b.n > 0 && b.predicted_mean != null && b.model_label_rate != null);
  const n = used.reduce((a, b) => a + b.n, 0);
  const hits = used.reduce((a, b) => a + b.n * (b.model_label_rate as number), 0);
  return { n, predicted: (used.reduce((a, b) => a + b.n * (b.predicted_mean as number), 0) / n) * 100, realised: (hits / n) * 100, misses: Math.round(n - hits) };
}

test.describe("Smart trading desk — Portfolio & risk", () => {
  test.beforeEach(async ({ page }) => {
    await deskBase(page);
  });

  test("TC-28 broker hub: sources, value and P&L, the market-cap donut, positions (>25% amber) and the seven risk checks", async ({ page }) => {
    await mockPaper(page, { status: 403, body: { detail: "Feature not enabled" } });
    await mockDeskLists(page);
    await portfolioData(page, { holdings: HOLDINGS, concentration: CONCENTRATION });
    await page.goto(`${DESK}?tab=portfolio`);

    const hub = page.getByTestId("desk-portfolio-hub");
    await expect(page.getByTestId("desk-portfolio-hub-title")).toHaveText("Portfolio · broker hub");
    await expect(hub.getByTestId("desk-portfolio-readonly")).toHaveText("Read-only");
    // copilot-trader-broker-accounts.json: Zerodha, last read 2026-10-12T10:12Z = 12 Oct 3:42 pm IST
    await expect(page.getByTestId("desk-portfolio-sources")).toHaveText(/^Zerodha · last read 12 Oct, 3:42\s?pm$/i);
    await expect(hub.locator('[data-testid="entity-icon"][data-kind="broker"]')).toHaveCount(1);
    await expect(page.getByTestId("desk-portfolio-value")).toHaveText("₹10.00 L");
    await expect(page.getByTestId("desk-portfolio-pnl")).toHaveText("+₹1.40 L · +16.3%");

    // Donut: 2 direct stocks in the centre; legend Large / Mid / Small / Not split yet / Funds & other / Cash, as shares of
    // the ₹10.00 L the route valued (₹4.00 L stocks + ₹6.00 L funds). Mid and small lists are not on record: "—".
    await expect(page.getByTestId("desk-portfolio-donut-count")).toHaveText("2");
    const legend = page.getByTestId("desk-mcap-row");
    expect(await legend.evaluateAll((els) => els.map((e) => e.getAttribute("data-bucket")))).toEqual(["large", "mid", "small", "unsplit", "funds", "cash"]);
    const weight = (b: string) => page.locator(`[data-testid="desk-mcap-row"][data-bucket="${b}"]`).getByTestId("desk-mcap-weight");
    await expect(weight("large")).toHaveText(pct1(capShare(MCAP_PARTIAL, 300000)));
    await expect(weight("mid")).toHaveText("—");
    await expect(weight("unsplit")).toHaveText(pct1(capShare(MCAP_PARTIAL, MCAP_PARTIAL.unsplit.value_rs)));
    await expect(weight("funds")).toHaveText(pct1(capShare(MCAP_PARTIAL, MCAP_PARTIAL.excluded.funds_value_rs)));
    await expect(weight("cash")).toHaveText("—");
    await expect(page.locator('[data-testid="desk-mcap-row"][data-bucket="cash"]')).toHaveAttribute("title", "Broker cash balances are not read");

    // Positions: the two direct stocks, largest first, icon + symbol; the fund is not listed.
    const positions = page.getByTestId("desk-portfolio-position");
    await expect(page.getByTestId("desk-portfolio-stock-count")).toHaveText("2");
    expect(await positions.evaluateAll((els) => els.map((e) => e.getAttribute("data-symbol")))).toEqual(["FIXHEAVY", "FIXLIGHT"]);
    await expect(page.getByTestId("desk-portfolio-positions")).not.toContainText("Fixture Flexi Cap Fund");
    const heavy = positions.nth(0);
    await expect(heavy.locator('[data-testid="entity-icon"]')).toHaveAttribute("data-key", "FIXHEAVY");
    await expect(heavy.getByRole("cell").nth(0)).toHaveAttribute("title", "Fixture Heavy Ltd");
    await expect(heavy).toContainText("₹3.00 L");
    await expect(heavy.getByTestId("desk-portfolio-pnl-pct")).toHaveText("+20.0%");
    await expect(heavy.getByTestId("desk-portfolio-weight")).toHaveText("30.0%");
    await expect(heavy.getByTestId("desk-portfolio-weight")).toHaveAttribute("data-over", "true");
    await expect(heavy.getByTestId("desk-portfolio-weight")).toHaveCSS("color", await amberColour(page));
    await expect(positions.nth(1).getByTestId("desk-portfolio-pnl-pct")).toHaveText("−9.1%");
    await expect(positions.nth(1).getByTestId("desk-portfolio-weight")).toHaveAttribute("data-over", "false");

    // Risk checks · linked holdings: seven rows in the design's order.
    const risk = page.getByTestId("desk-portfolio-risk");
    await expect(risk).toContainText("Risk checks · linked holdings");
    const checks = risk.locator("ul[data-testid=desk-risk-list] > li");
    expect(await checks.evaluateAll((els) => els.map((e) => e.getAttribute("data-testid")))).toEqual(RISK_ROWS.map(([id]) => `desk-risk-${id}`));
    for (const [id, label] of RISK_ROWS) await expect(page.getByTestId(`desk-risk-${id}`)).toContainText(label);
    // Overall: the route's rating (HIGH from 18.5% volatility), its 0–10 score, beta and 1-day VaR.
    await expect(page.getByTestId("desk-risk-overall")).toHaveAttribute("data-value", "High");
    await expect(page.getByTestId("desk-risk-overall")).toContainText(`score ${RISK.risk_score} of 10`);
    await expect(page.getByTestId("desk-risk-beta-value")).toHaveText(RISK.weighted_beta.toFixed(2));
    await expect(page.getByTestId("desk-risk-var-value")).toHaveText("₹19,171 (1.92%)");
    await expect(page.getByTestId("desk-risk-overall")).toContainText("95% confidence");
    // The drivers sit under Details.
    await page.getByTestId("desk-risk-overall-toggle").click();
    await expect(page.getByTestId("desk-risk-driver-smallcap-weight")).toContainText("Smallcap weight · 30.0% of the portfolio’s value");
    await expect(page.getByTestId("desk-risk-driver-smallcap-weight")).toHaveAttribute("data-level", "Medium");
    await expect(page.getByTestId("desk-risk-driver-debt-gold-buffer")).toHaveAttribute("data-level", "High");
    await expect(page.getByTestId("desk-risk-overall-more")).toContainText("cover 100.0% of the portfolio’s value");
    // Position: the largest stock against the 25% limit.
    await expect(page.getByTestId("desk-risk-position")).toHaveAttribute("data-value", "30.0%");
    await expect(page.getByTestId("desk-risk-position")).toHaveAttribute("data-level", "high");
    await expect(page.getByTestId("desk-risk-single-stock-value")).toHaveText("30.0%");
    await expect(page.getByTestId("desk-risk-position").locator('[data-testid="entity-icon"]')).toHaveAttribute("data-key", "FIXHEAVY");
    // Sector: Financial 48.0% above the 35% caution level → over-concentrated; HHI and effective N from the payload.
    await expect(page.getByTestId("desk-risk-sector")).toContainText("Financial is 48.0% of sector exposure, above the 35% cap · HHI 3,138 · 3.2 effective sectors");
    await expect(page.getByTestId("desk-risk-sector")).toHaveAttribute("data-level", "high");
    // Correlated: the route's count of pairs at 0.70 or above.
    await expect(page.getByTestId("desk-risk-correlation")).toHaveAttribute("data-value", `${CORRELATION.high_pairs} pair`);
    // No source: "—" with the reason.
    await expect(page.getByTestId("desk-risk-gap")).toHaveAttribute("data-value", "—");
    await expect(page.getByTestId("desk-risk-gap")).toContainText("No overnight-gap figure is on record");
    await expect(page.getByTestId("desk-risk-liquidity")).toHaveAttribute("data-value", "—");
    await expect(page.getByTestId("desk-risk-volatility-value")).toHaveText("18.5%");

    // Right card: the paper record's 403 says "not enabled"; your desk trades still show; the meta counts your closed trades.
    await expect(page.getByTestId("desk-portfolio-record-title")).toHaveText("Paper trades · predicted vs actual");
    await expect(page.getByTestId("desk-paper-card-closed")).toHaveText(`${summarize(paperTrades()).closed} closed`);
    await expect(page.getByTestId("desk-paper-no-access")).toContainText("not enabled for this account");
    await expect(page.getByTestId("desk-record-predicted")).toHaveCount(0);

    // The broker block (live holdings and positions per account) stays in the tab; this account is not read live, so its stored rows say so.
    await expect(page.getByTestId("trader-broker-positions")).toBeVisible();
    await expect(page.getByTestId("trader-broker-account")).toContainText("Zerodha");
    await expect(page.getByTestId("broker-live-status")).toHaveText("Not read live");
    await expect(page.getByTestId("broker-stored-asof")).toHaveText(/^3 holdings · as of last sync 12 Oct, 3:42\s?pm$/i);
  });

  test("TC-28 over the shared fixtures: positions from the route, within the limit; the model's record forward then replay, tiles and calibration from the payload", async ({ page }) => {
    await mockPaper(page);
    await mockDeskLists(page);
    await portfolioData(page);
    await page.goto(`${DESK}?tab=portfolio`);

    // holdings-enriched.json: the direct stocks are the equity / stock rows, largest value first
    const fx = load("holdings-enriched.json") as { holdings: Array<{ asset_type: string; value_rs: number | null; weight_pct: number | null; nse_symbol: string | null; name: string }>; totals: { value_rs: number } };
    const stocks = fx.holdings.filter((h) => ["equity", "stock"].includes(h.asset_type)).sort((a, b) => (b.value_rs ?? -1) - (a.value_rs ?? -1));
    await expect(page.getByTestId("desk-portfolio-stock-count")).toHaveText(String(stocks.length));
    expect((fx.totals.value_rs / 1e7).toFixed(2)).toBe("1.03");
    await expect(page.getByTestId("desk-portfolio-value")).toHaveText("₹1.03 Cr");
    const first = page.getByTestId("desk-portfolio-position").nth(0);
    await expect(first).toHaveAttribute("data-symbol", stocks[0].nse_symbol ?? stocks[0].name);
    await expect(first.getByTestId("desk-portfolio-weight")).toHaveText(`${(stocks[0].weight_pct ?? 0).toFixed(1)}%`);
    await expect(page.getByTestId("desk-portfolio-weight").and(page.locator('[data-over="true"]'))).toHaveCount(0);
    await expect(page.getByTestId("desk-risk-position")).toHaveAttribute("data-level", "low");

    // concentration.json: the largest classified sector ("Unclassified" and "Other" are not judged) under the cap → low.
    const conc = load("concentration.json") as { sector: { items: Array<{ name: string; pct: number }>; caution_pct: number } };
    const classified = conc.sector.items.find((i) => !/unclassified|other/i.test(i.name));
    await expect(page.getByTestId("desk-risk-sector")).toContainText(`${classified?.name} is ${classified?.pct.toFixed(1)}% of sector exposure, under the ${conc.sector.caution_pct}% cap`);
    await expect(page.getByTestId("desk-risk-sector")).toHaveAttribute("data-level", "low");

    // The model's record: forward first and named; the forward fixture has no outcomes yet, so every tile is "—".
    await expect(page.getByTestId("desk-paper-sample-forward")).toHaveAttribute("aria-pressed", "true");
    await expect(page.getByTestId("desk-paper-sample-note")).toContainText("Forward sample");
    await expect(page.getByTestId("desk-paper-statement")).toContainText("Not established: 0 counted sessions");
    for (const id of ["predicted", "realised", "net", "false"]) await expect(page.getByTestId(`desk-record-${id}`)).toHaveText("—");
    await expect(page.getByTestId("desk-calibration-none")).toBeVisible();

    // Replay: tiles and calibration over the selected five a session (paper-evaluation-replay-P5-NEXT.json).
    await page.getByTestId("desk-paper-sample-replay").click();
    await expect(page.getByTestId("desk-paper-sample-note")).toContainText("Replay sample");
    const ev = load("paper-evaluation-replay-P5-NEXT.json").data.evaluation as {
      headline_mode: string; costs: { base: number }; modes: Array<{ mode: string; net_mean: number | null; closed_trades: number }>; buckets: { selected: Bucket[] };
    };
    const t = tilesOf(ev.buckets.selected);
    await expect(page.getByTestId("desk-record-predicted")).toHaveText(pct1(t.predicted));
    await expect(page.getByTestId("desk-record-realised")).toHaveText(pct1(t.realised));
    await expect(page.getByTestId("desk-record-false")).toHaveText(t.misses.toLocaleString("en-IN"));
    const head = ev.modes.find((m) => m.mode === ev.headline_mode);
    const net = (head?.net_mean as number) * 100;
    await expect(page.getByTestId("desk-record-net")).toHaveText(`${net < 0 ? MINUS : "+"}${Math.abs(net).toFixed(2)}%`);
    await expect(page.getByTestId("desk-portfolio-record")).toContainText(`after ${ev.costs.base.toFixed(2)}% costs · ${head?.closed_trades.toLocaleString("en-IN")} trades`);
    const used = ev.buckets.selected.filter((b) => b.n > 0);
    const bars = page.getByTestId("desk-calibration-row");
    await expect(bars).toHaveCount(used.length);
    const b10 = used.find((b) => b.lo === 0.1) as Bucket;
    const row10 = page.locator('[data-testid="desk-calibration-row"][data-lo="10"]');
    await expect(row10.getByTestId("desk-calibration-predicted")).toHaveText(`${((b10.predicted_mean as number) * 100).toFixed(0)}%`);
    await expect(row10.getByTestId("desk-calibration-realised")).toHaveText(`${((b10.model_label_rate as number) * 100).toFixed(0)}%`);
    await expect(row10).toContainText(`n ${b10.n}`);
  });

  test("TC-29 an empty portfolio shows the empty state, and its button opens broker connections", async ({ page }) => {
    await mockPaper(page);
    await mockDeskLists(page, { empty: true });
    await mockSingleRoute(page, "**/api/portfolio/holdings-enriched*", "empty-portfolio.json");
    await portfolioData(page);
    await page.goto(`${DESK}?tab=portfolio`);
    // Paper trades and alerts do not depend on holdings: their empty states show.
    await expect(page.getByTestId("desk-paper-trades-empty")).toContainText("No paper trades yet");
    await expect(page.getByTestId("desk-alerts-empty")).toContainText("No price alerts");
    await expect(page.getByTestId("desk-paper-today-none")).toHaveText("No paper trade added today.");
    await expect(page.getByTestId("desk-paper-last5-none")).toHaveText("No closed paper trades yet.");

    const empty = page.getByTestId("desk-portfolio-empty");
    await expect(empty).toContainText("No holdings on record yet");
    await expect(page.getByTestId("desk-portfolio-positions")).toHaveCount(0);
    await expect(page.getByTestId("desk-portfolio-risk")).toHaveCount(0);
    await page.getByTestId("desk-portfolio-connect").click();
    await expect(page).toHaveURL(/\/v5\/app\/page\/brokers/);
  });

  test("the broker block reads holdings and positions live; the F&O switch narrows to the contract; Refresh reads both again", async ({ page }) => {
    await mockPaper(page);
    await portfolioData(page, { holdings: HOLDINGS, concentration: CONCENTRATION });
    const reads = { holdings: 0, positions: 0 };
    await json(page, "**/api/broker/accounts", LIVE_ACCOUNTS);
    await page.route("**/api/broker/holdings*", (route) => {
      reads.holdings += 1;
      return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(LIVE_HOLDINGS) });
    });
    await page.route("**/api/broker/positions*", (route) => {
      reads.positions += 1;
      return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(LIVE_POSITIONS) });
    });
    await page.goto(`${DESK}?tab=portfolio`);

    const block = page.getByTestId("trader-broker-positions");
    await expect(block.getByTestId("broker-live-status")).toHaveText(/^Live · read 12 Oct, 3:45\s?pm$/i);
    const rows = block.getByTestId("broker-live-row");
    await expect(rows).toHaveCount(2);
    await expect(block.locator('[data-testid="broker-live-row"] [data-testid="entity-icon"][data-kind="stock"]')).toHaveCount(2);
    await expect(block.getByRole("row").filter({ hasText: "FIXLIGHT" }).getByTestId("broker-live-pnl-pct")).toHaveText("−10.0%");
    // totals from the payload: value ₹2,100, invested ₹2,000, +₹100, +5.0%
    await expect(block.getByTestId("broker-live-total-value")).toHaveText("₹2,100");
    await expect(block.getByTestId("broker-live-total-invested")).toHaveText("₹2,000");
    await expect(block.getByTestId("broker-live-total-pnl")).toHaveText("+₹100 · +5.0%");
    // Every account was read live: no stored rows are shown.
    await expect(block.getByTestId("broker-stored-holdings")).toHaveCount(0);

    // positions: All · 2, F&O · 1; the F&O view keeps the contract's expiry
    await expect(block.getByTestId("trader-positions-filter-all")).toHaveText("All · 2");
    await expect(block.getByTestId("trader-positions-filter-fno")).toHaveText("F&O · 1");
    await block.getByTestId("trader-positions-filter-fno").click();
    await expect(block.getByTestId("broker-position-row")).toHaveCount(1);
    await expect(block.getByTestId("broker-position-row")).toContainText("27 Oct 2026 future");
    await expect(block.getByTestId("broker-position-qty")).toHaveText("Short 75");

    await page.waitForLoadState("networkidle");
    const before = { ...reads };
    await block.getByTestId("trader-broker-refresh").click();
    await expect.poll(() => reads).toEqual({ holdings: before.holdings + 1, positions: before.positions + 1 });
  });
});

test.describe("Smart trading desk — Portfolio & risk: correlation, market cap, paper trades and alerts", () => {
  test.beforeEach(async ({ page }) => {
    await deskBase(page);
    await mockPaper(page);
  });

  test("correlated positions: the route's count and top pair in the row; Details lists the pairs with both icons, the 0.70 flag, method and skips", async ({ page }) => {
    await mockDeskLists(page);
    await portfolioData(page, { holdings: HOLDINGS, concentration: CONCENTRATION });
    await page.goto(`${DESK}?tab=portfolio`);
    const row = page.getByTestId("desk-risk-correlation");
    // The route's own counts over every pair; the average worked out here matches its figure.
    const avg = CORRELATION.pairs.reduce((a, p) => a + p.corr, 0) / CORRELATION.pairs.length;
    expect(avg.toFixed(2)).toBe(CORRELATION.avg_corr.toFixed(2));
    expect(CORRELATION.pairs.filter((p) => p.corr >= CORRELATION.high_threshold).length).toBe(CORRELATION.high_pairs);
    const top = CORRELATION.pairs[0];
    await expect(row.getByTestId("desk-corr-summary")).toHaveText(`${top.a} ↔ ${top.b} ${dec2(top.corr)} · average ${avg.toFixed(2)} of ${CORRELATION.pairs_total} pairs · ${CORRELATION.sessions} sessions`);
    await expect(row.getByTestId("desk-corr-pair")).toHaveCount(0);
    await page.getByTestId("desk-risk-correlation-toggle").click();
    const pairs = row.getByTestId("desk-corr-pair");
    await expect(pairs).toHaveCount(CORRELATION.pairs.length);
    for (let i = 0; i < CORRELATION.pairs.length; i += 1) {
      const p = CORRELATION.pairs[i];
      const r = pairs.nth(i);
      const high = p.corr >= CORRELATION.high_threshold;
      await expect(r).toHaveAttribute("data-pair", `${p.a}-${p.b}`);
      await expect(r).toHaveAttribute("data-high", String(high));
      await expect(r.getByTestId("desk-corr-value")).toHaveText(dec2(p.corr));
      await expect(r.getByTestId("desk-corr-flag")).toHaveCount(high ? 1 : 0);
      const icons = r.locator('[data-testid="entity-icon"]');
      await expect(icons).toHaveCount(2);
      await expect(icons.nth(0)).toHaveAttribute("data-key", p.a);
      await expect(icons.nth(1)).toHaveAttribute("data-key", p.b);
      await expect(r).toContainText(`${p.weight_a_pct.toFixed(1)}% and ${p.weight_b_pct.toFixed(1)}% of the portfolio · ${p.common_sessions} common sessions`);
    }
    await expect(row.getByTestId("desk-corr-method")).toContainText(
      `${CORRELATION.method} over ${CORRELATION.sessions} sessions (a stock needs at least ${CORRELATION.min_sessions}) · ${CORRELATION.source} · end of day ${dayY(CORRELATION.as_of)}`,
    );
    await expect(row.getByTestId("desk-corr-skipped")).toHaveText(`Not compared: ${CORRELATION.holdings_skipped[0].symbol} (${CORRELATION.holdings_skipped[0].reason}).`);
  });

  test("correlated positions: fewer than two usable stocks, and a failed read with retry", async ({ page }) => {
    await mockDeskLists(page);
    await portfolioData(page, { holdings: HOLDINGS, concentration: CONCENTRATION, correlation: { status: 200, body: { ...CORRELATION, holdings_used: 1, high_pairs: 0, avg_corr: null, pairs_total: 0, pairs: [] } } });
    await page.goto(`${DESK}?tab=portfolio`);
    await expect(page.getByTestId("desk-corr-none")).toContainText(`Fewer than two of your stocks have enough daily prices to compare over ${CORRELATION.sessions} sessions.`);
    await expect(page.getByTestId("desk-risk-correlation")).toHaveAttribute("data-value", "—");
    await page.getByTestId("desk-risk-correlation-toggle").click();
    await expect(page.getByTestId("desk-corr-skipped")).toContainText("Not compared: FIXNEW");

    let reads = 0;
    await page.route("**/api/portfolio/correlation*", (route) => { reads += 1; return route.fulfill({ status: 502, contentType: "application/json", body: JSON.stringify({ detail: "upstream_unavailable" }) }); });
    await page.reload();
    const err = page.getByTestId("desk-corr-error");
    await expect(err).toContainText("Correlated positions didn’t load", { timeout: 15_000 });
    const before = reads;
    await err.getByRole("button", { name: /Retry/ }).click();
    await expect.poll(() => reads).toBeGreaterThan(before);
  });

  test("market-cap donut as the route answers today: large cap split, the rest named as not split yet with the route's reason, funds and cash", async ({ page }) => {
    await mockDeskLists(page);
    await portfolioData(page, { holdings: HOLDINGS, concentration: CONCENTRATION });
    await page.goto(`${DESK}?tab=portfolio`);
    const block = page.getByTestId("desk-portfolio-mcap");
    const row = (b: string) => block.locator(`[data-testid="desk-mcap-row"][data-bucket="${b}"]`);
    for (const b of MCAP_PARTIAL.buckets.filter((x) => x.bucket === "large" || x.bucket === "mid" || x.bucket === "small")) {
      await expect(row(b.bucket)).toHaveAttribute("data-available", String(b.available));
      await expect(row(b.bucket).getByTestId("desk-mcap-weight")).toHaveText(b.available ? pct1(capShare(MCAP_PARTIAL, b.value_rs as number)) : "—");
      if (!b.available) await expect(row(b.bucket)).toHaveAttribute("title", b.reason as string);
    }
    // Micro and unclassified are not on record and hold nothing drawn: not listed.
    await expect(row("micro")).toHaveCount(0);
    await expect(row("unclassified")).toHaveCount(0);
    // large + unsplit = the equity total; with the funds the shares add to 100%.
    const u = MCAP_PARTIAL.unsplit;
    expect((MCAP_PARTIAL.buckets[0].value_rs as number) + u.value_rs).toBe(MCAP_PARTIAL.total_value_rs);
    await expect(row("unsplit").getByTestId("desk-mcap-weight")).toHaveText(pct1(capShare(MCAP_PARTIAL, u.value_rs)));
    await expect(row("unsplit")).toHaveAttribute("title", u.reason);
    await expect(row("funds").getByTestId("desk-mcap-weight")).toHaveText(pct1(capShare(MCAP_PARTIAL, MCAP_PARTIAL.excluded.funds_value_rs)));
    await expect(block.getByTestId("desk-mcap-reason")).toHaveText(`${u.reason}.`);
    await expect(block.getByTestId("desk-mcap-total")).toHaveText(lakh(MCAP_PARTIAL.total_value_rs + MCAP_PARTIAL.excluded.funds_value_rs));
    // The donut: a track and one arc per drawn share (large, not split yet, funds).
    await expect(block.locator('[data-testid="desk-portfolio-donut"] circle')).toHaveCount(1 + 3);
    expect(await block.getByTestId("desk-portfolio-donut").getAttribute("width")).toBe("120");
  });

  test("market-cap donut once every list is on record: four buckets drawn, no not-split share; a failed read says so", async ({ page }) => {
    await mockDeskLists(page);
    await portfolioData(page, { holdings: HOLDINGS, concentration: CONCENTRATION, mcap: { status: 200, body: MCAP_FULL } });
    await page.goto(`${DESK}?tab=portfolio`);
    const block = page.getByTestId("desk-portfolio-mcap");
    const drawn = MCAP_FULL.buckets.filter((b) => (b.value_rs as number) > 0);
    await expect(block.getByTestId("desk-mcap-row")).toHaveCount(drawn.length + 2);
    expect(await block.getByTestId("desk-mcap-row").evaluateAll((els) => els.map((e) => e.getAttribute("data-bucket")))).toEqual([...drawn.map((b) => b.bucket), "funds", "cash"]);
    for (const b of drawn) {
      await expect(block.locator(`[data-testid="desk-mcap-row"][data-bucket="${b.bucket}"]`).getByTestId("desk-mcap-weight")).toHaveText(pct1(capShare(MCAP_FULL, b.value_rs as number)));
    }
    const shares = [...drawn.map((b) => b.value_rs as number), MCAP_FULL.excluded.funds_value_rs].map((v) => capShare(MCAP_FULL, v));
    expect(shares.reduce((a, b) => a + b, 0)).toBeCloseTo(100, 6);
    await expect(block.locator('[data-testid="desk-mcap-row"][data-bucket="unsplit"]')).toHaveCount(0);
    await expect(block.getByTestId("desk-mcap-reason")).toHaveCount(0);

    await page.route("**/api/portfolio/market-cap-split*", (route) => route.fulfill({ status: 502, contentType: "application/json", body: JSON.stringify({ detail: "upstream_unavailable" }) }));
    await page.reload();
    await expect(page.getByTestId("desk-mcap-error").getByRole("alert")).toContainText("The market-cap split didn’t load", { timeout: 15_000 });
  });

  test("your paper trades: open marks, closed exits and reasons, the summary; Close asks first, then posts {} to …/{id}/close", async ({ page }) => {
    const calls = await mockDeskLists(page);
    await portfolioData(page, { holdings: HOLDINGS, concentration: CONCENTRATION });
    await page.goto(`${DESK}?tab=portfolio`);
    const block = page.getByTestId("desk-paper-trades");
    const trades = paperTrades();
    const sum = summarize(trades);
    const open = trades.filter((t) => t.status === "open");
    const closed = trades.filter((t) => t.status === "closed");

    await expect(page.getByTestId("desk-portfolio-paper")).toContainText("Simulated · no orders");
    await expect(block.getByTestId("desk-paper-open")).toHaveText(String(sum.open));
    await expect(block.getByTestId("desk-paper-closed")).toHaveText(String(sum.closed));
    await expect(block).toContainText(`${sum.wins} won · ${sum.losses} lost`);
    await expect(block.getByTestId("desk-paper-realised")).toHaveText(rupees(sum.realized_pnl_rs as number, true));
    await expect(block.getByTestId("desk-paper-unrealised")).toHaveText(rupees(sum.unrealized_pnl_rs as number, true));

    const openRows = block.getByTestId("desk-paper-open-table").getByRole("row").filter({ has: page.getByTestId("desk-paper-symbol") });
    await expect(openRows).toHaveCount(open.length);
    for (let i = 0; i < open.length; i += 1) {
      const t = open[i];
      const r = openRows.nth(i);
      await expect(r.getByTestId("desk-paper-symbol")).toHaveText(t.symbol);
      await expect(r.locator('[data-testid="entity-icon"]')).toHaveAttribute("data-key", t.symbol);
      await expect(r.getByTestId("desk-paper-qty")).toHaveText(t.quantity.toLocaleString("en-IN"));
      await expect(r.getByTestId("desk-paper-last")).toHaveText(paise(t.last_close as number));
      // Unrealised = (last close − entry) × quantity, worked out here.
      const u = ((t.last_close as number) - t.entry_price) * t.quantity;
      expect(u).toBeCloseTo(t.unrealized_pnl_rs as number, 6);
      await expect(r.getByTestId("desk-paper-unrealised-row")).toHaveText(rupees(u, true));
    }
    const closedRows = block.getByTestId("desk-paper-closed-table").getByRole("row").filter({ has: page.getByTestId("desk-paper-symbol") });
    await expect(closedRows).toHaveCount(closed.length);
    for (let i = 0; i < closed.length; i += 1) {
      const t = closed[i];
      const r = closedRows.nth(i);
      await expect(r.getByTestId("desk-paper-exit")).toHaveText(paise(t.exit_price as number));
      await expect(r.getByTestId("desk-paper-reason")).toHaveAttribute("data-reason", t.exit_reason as string);
      await expect(r.getByTestId("desk-paper-reason")).toContainText(t.exit_reason === "stop" ? "Stop" : "Target");
      const realised = ((t.exit_price as number) - t.entry_price) * t.quantity;
      expect(realised).toBeCloseTo(t.realized_pnl_rs as number, 6);
      await expect(r.getByTestId("desk-paper-realised-row")).toHaveText(rupees(realised, true));
    }
    // The both-touched session closed at the stop, and the note says so.
    await expect(block.getByTestId("desk-paper-exit-notes")).toContainText(BOTH);
    await expect(block.getByTestId("desk-paper-rules")).toContainText("Simulated: no order is placed.");
    await expect(block.getByTestId("desk-paper-rules")).toContainText(`checked through ${dayY("2026-10-13")}`);
    await expect(block.getByTestId("desk-paper-rules")).toContainText("one that reaches both closes it at the stop");

    // Close asks first; Cancel sends nothing.
    const brk = openRows.filter({ hasText: "FIXBRK" });
    await brk.getByTestId("desk-paper-close").click();
    const confirm = block.getByTestId("desk-paper-confirm");
    const t0 = open[0];
    await expect(confirm).toContainText(`Close the FIXBRK paper trade (${t0.quantity} shares) at its last close, ${paise(t0.last_close as number)} (end of day ${dayY("2026-10-13")})? It is simulated: no order is placed.`);
    await confirm.getByTestId("desk-paper-confirm-no").click();
    await expect(confirm).toHaveCount(0);
    expect(calls.closes).toHaveLength(0);

    // Confirm: POST …/pt-001/close with {} (the server closes at the last close); the list re-reads.
    await brk.getByTestId("desk-paper-close").click();
    const reads = calls.paperReads;
    await block.getByTestId("desk-paper-confirm-yes").click();
    await expect.poll(() => calls.closes.length).toBe(1);
    expect(calls.closes[0]).toEqual({ path: "/api/desk/paper-trades/pt-001/close", body: {} });
    await expect.poll(() => calls.paperReads).toBeGreaterThan(reads);
    await expect(block.getByTestId("desk-paper-open-count")).toHaveText(String(open.length - 1));
    await expect(block.getByTestId("desk-paper-closed-count")).toHaveText(String(closed.length + 1));
    const closedNow = block.getByTestId("desk-paper-closed-table").getByRole("row").filter({ hasText: "FIXBRK" });
    await expect(closedNow.getByTestId("desk-paper-reason")).toHaveText("Closed by you");
    await expect(closedNow.getByTestId("desk-paper-realised-row")).toHaveText(rupees(((t0.last_close as number) - t0.entry_price) * t0.quantity, true));
    await expect(block.getByTestId("desk-paper-confirm")).toHaveCount(0);
  });

  test("your paper trades: a refused close shows the server's words; missing marks are said, not made up; errors and 403", async ({ page }) => {
    const calls = await mockDeskLists(page, { closeReply: { status: 409, body: { detail: "trade_already_closed" } } });
    await portfolioData(page, { holdings: HOLDINGS, concentration: CONCENTRATION });
    await page.goto(`${DESK}?tab=portfolio`);
    const block = page.getByTestId("desk-paper-trades");
    await block.getByTestId("desk-paper-close").first().click();
    await block.getByTestId("desk-paper-confirm-yes").click();
    await expect(block.getByTestId("desk-paper-confirm-error")).toHaveText("That paper trade is already closed. (trade_already_closed)");
    expect(calls.closes).toHaveLength(1);
    // The confirmation stays open, with its buttons usable again.
    await expect(block.getByTestId("desk-paper-confirm-yes")).toBeEnabled();

    // Prices unreadable: marks null and the route's marks_error — said in words, P&L "—".
    const unmarked = paperTrades().map((t) => (t.status === "open" ? { ...t, last_close: null, last_close_date: null, unrealized_pnl_rs: null, mark_error: "prices_unavailable" } : t));
    await page.route("**/api/desk/paper-trades*", (route) => route.fulfill({
      status: 200, contentType: "application/json",
      body: JSON.stringify({ as_of: null, checked_through: null, marks_error: "prices_unavailable", trades: unmarked, summary: summarize(unmarked) }),
    }));
    await page.reload();
    await expect(page.getByTestId("desk-paper-marks-error")).toContainText("End-of-day prices could not be read just now");
    await expect(page.getByTestId("desk-paper-unrealised")).toHaveText("—");
    await expect(page.getByTestId("desk-paper-last").first()).toHaveText("—");
    await expect(page.getByTestId("desk-paper-trades")).toContainText("2 open without a mark");

    await page.route("**/api/desk/paper-trades*", (route) => route.fulfill({ status: 502, contentType: "application/json", body: JSON.stringify({ detail: "upstream_unavailable" }) }));
    await page.reload();
    await expect(page.getByTestId("desk-paper-trades-error").getByRole("alert")).toContainText("Your paper trades didn’t load", { timeout: 15_000 });
    await page.route("**/api/desk/paper-trades*", (route) => route.fulfill({ status: 403, contentType: "application/json", body: JSON.stringify({ detail: "forbidden" }) }));
    await page.reload();
    await expect(page.getByTestId("desk-paper-trades-error")).toContainText("Your paper trades is not enabled for this account");
  });

  test("your price alerts: levels, status, fired session, last close; Delete asks first, then sends DELETE …/{id}", async ({ page }) => {
    const calls = await mockDeskLists(page);
    await portfolioData(page, { holdings: HOLDINGS, concentration: CONCENTRATION });
    await page.goto(`${DESK}?tab=portfolio`);
    const block = page.getByTestId("desk-alerts");
    const alerts = priceAlerts();
    const rows = block.getByTestId("desk-alert-row");
    await expect(rows).toHaveCount(alerts.length);
    for (const a of alerts) {
      const row = block.locator(`[data-testid="desk-alert-row"][data-id="${a.id}"]`);
      await expect(row).toHaveAttribute("data-status", a.status as string);
      await expect(row.getByTestId("desk-alert-symbol")).toHaveText(a.symbol);
      await expect(row.locator('[data-testid="entity-icon"]')).toHaveAttribute("data-key", a.symbol);
      await expect(row.getByTestId("desk-alert-level")).toHaveText(`${a.condition === "above" ? "Above" : "Below"} ${paise(a.level)}`);
      await expect(row.getByTestId("desk-alert-status")).toHaveText(a.status === "fired" ? "Fired" : "Active");
      if (a.status === "fired") {
        await expect(row.getByTestId("desk-alert-fired")).toHaveText(`Reached on ${dayY(a.fired_session as string)} at ${paise(a.fired_price as number)} (end of day).`);
      } else {
        await expect(row.getByTestId("desk-alert-last")).toHaveText(`Last close ${paise(a.last_close as number)} · end of day ${dayY(a.last_close_date as string)}`);
      }
    }
    await expect(block.getByTestId("desk-alerts-rules")).toContainText(`checked through ${dayY("2026-10-13")}`);
    await expect(block.getByTestId("desk-alerts-rules")).toContainText("no email or push");

    const acc = block.locator('[data-testid="desk-alert-row"][data-id="al-003"]');
    await acc.getByTestId("desk-alert-delete").click();
    await expect(acc.getByTestId("desk-alert-confirm")).toContainText(`Delete the FIXACC alert (below ${paise(84)})?`);
    await acc.getByTestId("desk-alert-confirm-no").click();
    await expect(acc.getByTestId("desk-alert-confirm")).toHaveCount(0);
    expect(calls.deletes).toHaveLength(0);
    await acc.getByTestId("desk-alert-delete").click();
    await acc.getByTestId("desk-alert-confirm-yes").click();
    await expect.poll(() => calls.deletes).toEqual(["al-003"]);
    await expect(rows).toHaveCount(alerts.length - 1);
    await expect(block.locator('[data-testid="desk-alert-row"][data-id="al-003"]')).toHaveCount(0);
  });

  test("your price alerts: a failed read with retry", async ({ page }) => {
    const calls = await mockDeskLists(page, { alertList: { status: 502, body: { detail: "upstream_unavailable" } } });
    await portfolioData(page, { holdings: HOLDINGS, concentration: CONCENTRATION });
    await page.goto(`${DESK}?tab=portfolio`);
    const err = page.getByTestId("desk-alerts-error");
    await expect(err.getByRole("alert")).toContainText("Your price alerts didn’t load", { timeout: 15_000 });
    const before = calls.alertReads;
    await err.getByRole("button", { name: /Retry/ }).click();
    await expect.poll(() => calls.alertReads).toBeGreaterThan(before);
  });
});

test.describe("Smart trading desk — Portfolio & risk at 390px", () => {
  test.use({ viewport: { width: 390, height: 844 } });

  test("TC-7 no sideways scroll on the Portfolio & risk tab", async ({ page }) => {
    await deskBase(page);
    // the broker block with live holdings and positions, so their tables are on the page too
    await json(page, "**/api/broker/accounts", LIVE_ACCOUNTS);
    await json(page, "**/api/broker/holdings*", LIVE_HOLDINGS);
    await json(page, "**/api/broker/positions*", LIVE_POSITIONS);
    await mockPaper(page);
    await mockDeskLists(page);
    await portfolioData(page, { holdings: HOLDINGS, concentration: CONCENTRATION });

    await page.goto(`${DESK}?tab=portfolio`);
    // The phone composition (design §11 M5) is checked in "Portfolio & risk · design fidelity" below.
    await expect(page.getByTestId("desk-portfolio")).toHaveAttribute("data-layout", "phone");
    await expect(page.getByTestId("desk-risk-overall")).toBeVisible();
    await expect(page.locator('[data-testid="desk-mcap-row"][data-bucket="unsplit"]')).toBeVisible();
    await expect(page.getByTestId("desk-paper-open-table")).toBeVisible();
    await expect(page.getByTestId("desk-alert-row")).toHaveCount(3);
    await expect(page.getByTestId("trader-broker-positions")).toBeVisible();
    await expect(page.getByTestId("broker-live-row")).toHaveCount(2);
    await expect(page.getByTestId("broker-position-row")).toHaveCount(2);
    // the weight column (where the 25% limit shows) fits on a phone without scrolling the table
    const weightBox = await page.getByTestId("desk-portfolio-weight").first().boundingBox();
    expect(weightBox).not.toBeNull();
    expect((weightBox?.x ?? 0) + (weightBox?.width ?? 0)).toBeLessThanOrEqual(390);
    const o = await sideways(page);
    expect(o.doc).toBeLessThanOrEqual(1);
    expect(o.scroll).toBeLessThanOrEqual(1);
  });
});


// ── Portfolio & risk · design fidelity (design-spec §7, §10, §11 M5) ────

/** Screenshots for the design comparison land in test-results/ (git-ignored); they assert nothing on their own. */
const SHOTS = "test-results/fidelity-shots";

test.describe("Smart trading desk — Portfolio & risk · design fidelity", () => {
  test("§7 at 1440 with the dock: two equal cards with header bars; tiles, calibration, open-today and last-5-closed in the right card", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await deskBase(page);
    await mockPaper(page);
    // One trade opened today (it is listed under "Open · added today"); the rest as the fixture.
    const now = new Date().toISOString();
    const trades = [trade({ id: "pt-new", symbol: "FIXNEWT", quantity: 40, entry_price: 250, stop_price: 240, target_price: 270, opened_at: now, last_close: 251, last_close_date: "2026-10-13", unrealized_pnl_rs: 40 }), ...paperTrades()];
    await mockDeskLists(page, { paperList: { status: 200, body: { as_of: "2026-10-13", checked_through: "2026-10-13", marks_error: null, trades, summary: summarize(trades) } } });
    await portfolioData(page, { holdings: HOLDINGS, concentration: CONCENTRATION });
    await page.goto(`${DESK}?tab=portfolio`);
    await expect(page.getByTestId("desk-portfolio")).toHaveAttribute("data-layout", "desktop");

    // Two equal columns, side by side.
    const hub = page.getByTestId("desk-portfolio-hub");
    const record = page.getByTestId("desk-portfolio-record");
    const [hb, rb] = [await hub.boundingBox(), await record.boundingBox()];
    expect(Math.abs((hb?.width ?? 0) - (rb?.width ?? 0))).toBeLessThanOrEqual(2);
    expect(Math.abs((hb?.y ?? 0) - (rb?.y ?? 0))).toBeLessThanOrEqual(2);
    expect((rb?.x ?? 0)).toBeGreaterThan((hb?.x ?? 0) + (hb?.width ?? 0));
    // Header bars: bg-0, 13px 18px, the title left and the meta right.
    const bar = page.getByTestId("desk-portfolio-hub-title").locator("xpath=..");
    expect(await bar.evaluate((e) => getComputedStyle(e).padding)).toBe("13px 18px");
    await expect(page.getByTestId("desk-portfolio-record-title")).toHaveText("Paper trades · predicted vs actual");
    await expect(page.getByTestId("desk-paper-card-closed")).toHaveText(`${summarize(trades).closed} closed`);
    await expect(hub.getByTestId("desk-portfolio-readonly")).toHaveAttribute("data-tone", "indigo");
    // Value serif 34px; donut 120px; positions grid 1fr 78px 64px 44px.
    expect(await page.getByTestId("desk-portfolio-value").evaluate((e) => getComputedStyle(e).fontSize)).toBe("34px");
    expect(await page.getByTestId("desk-portfolio-donut").getAttribute("width")).toBe("120");
    const cols = await page.getByTestId("desk-portfolio-position").first().evaluate((e) => getComputedStyle(e).gridTemplateColumns.split(" ").slice(1));
    expect(cols).toEqual(["78px", "64px", "44px"]);
    // Section order inside the hub card: sources, value, donut, positions, risk checks.
    const order = await hub.evaluate((root) => ["desk-portfolio-sources", "desk-portfolio-value", "desk-portfolio-donut", "desk-portfolio-positions", "desk-portfolio-risk"]
      .map((id) => root.querySelector(`[data-testid="${id}"]`)?.getBoundingClientRect().top ?? -1));
    expect(order.every((t, i) => t >= 0 && (i === 0 || t > order[i - 1]))).toBe(true);
    // Right card: the four tiles in the design's order, then Calibration, Open · added today, Last 5 closed.
    await page.getByTestId("desk-paper-sample-replay").click();
    await expect(record.getByTestId("desk-record-predicted")).not.toHaveText("—");
    const tileLabels = await record.locator('[data-testid^="desk-record-"]').evaluateAll((els) => els.map((e) => e.parentElement?.firstElementChild?.textContent));
    expect(tileLabels).toEqual(["Predicted", "Realised", "Net after costs", "False positives"]);
    await expect(record).toContainText("Calibration");
    // Open · added today: the trade opened today, with its levels and P shown as "—" (no probability is stored with a trade).
    const today = record.getByTestId("desk-paper-today-row");
    await expect(today).toHaveCount(1);
    await expect(today).toHaveAttribute("data-id", "pt-new");
    await expect(today.getByTestId("desk-paper-today-levels")).toHaveText(`Entry ${paise(250)} · Stop ${paise(240)} · Target ${paise(270)}`);
    await expect(today.getByTestId("desk-paper-today-p")).toHaveText("P —");
    // Last 5 closed: grid 1fr 40px 84px 48px; setup · days · exit, P "—", outcome = exit vs entry, R = (exit − entry) ÷ (entry − stop).
    const closed = trades.filter((t) => t.status === "closed").slice(0, 5);
    const last = record.getByTestId("desk-paper-last5-row");
    await expect(last).toHaveCount(closed.length);
    expect(await last.first().evaluate((e) => getComputedStyle(e).gridTemplateColumns.split(" ").slice(1))).toEqual(["40px", "84px", "48px"]);
    for (let i = 0; i < closed.length; i += 1) {
      const t = closed[i];
      const ret = (((t.exit_price as number) - t.entry_price) / t.entry_price) * 100;
      const r = ((t.exit_price as number) - t.entry_price) / (t.entry_price - (t.stop_price as number));
      const days = Math.round((Date.parse((t.closed_at as string).slice(0, 10)) - Date.parse((t.opened_at as string).slice(0, 10))) / 86_400_000);
      await expect(last.nth(i)).toHaveAttribute("data-id", t.id);
      await expect(last.nth(i).getByTestId("desk-paper-last5-setup")).toHaveText(`Breakout confirmed · ${days} days · ${t.exit_reason}`);
      await expect(last.nth(i).getByTestId("desk-paper-last5-pred")).toHaveText("—");
      await expect(last.nth(i).getByTestId("desk-paper-last5-outcome")).toHaveText(pct1(ret, true));
      await expect(last.nth(i).getByTestId("desk-paper-last5-r")).toHaveText(`${r < 0 ? MINUS : "+"}${Math.abs(r).toFixed(1)}R`);
    }
    // Close and delete stay reachable in the full lists below, and the broker block stays in the tab.
    await expect(page.getByTestId("desk-paper-close").first()).toBeVisible();
    await expect(page.getByTestId("desk-alert-delete").first()).toBeVisible();
    await expect(page.getByTestId("trader-broker-positions")).toBeVisible();
  });

  test("§11 M5 at 390: portfolio card with donut, Risk dashboard with 5-segment level bars, Positions table, the read-only note; no sideways scroll", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await deskBase(page);
    await mockPaper(page);
    await mockDeskLists(page);
    await portfolioData(page, { holdings: HOLDINGS, concentration: CONCENTRATION });
    await page.goto(`${DESK}?tab=portfolio`);
    const root = page.getByTestId("desk-portfolio");
    await expect(root).toHaveAttribute("data-layout", "phone");
    // Order: portfolio card, risk dashboard, positions, the read-only note (then the paper card, broker block and lists).
    const order = await root.evaluate((r) => ["desk-portfolio-hub", "desk-portfolio-risk", "desk-portfolio-positions", "desk-portfolio-readonly-note", "desk-portfolio-record", "trader-broker-positions", "desk-portfolio-paper"]
      .map((id) => r.querySelector(`[data-testid="${id}"]`)?.getBoundingClientRect().top ?? -1));
    expect(order.every((t, i) => t >= 0 && (i === 0 || t > order[i - 1]))).toBe(true);

    await expect(page.getByTestId("desk-portfolio-hub-title")).toHaveText("Your portfolio");
    await expect(page.getByTestId("desk-portfolio-hub").getByTestId("desk-portfolio-readonly")).toHaveText("Read-only");
    await expect(page.getByTestId("desk-portfolio-sources")).toHaveText("Zerodha");
    expect(await page.getByTestId("desk-portfolio-value").evaluate((e) => getComputedStyle(e).fontSize)).toBe("34px");
    expect(await page.getByTestId("desk-portfolio-donut").getAttribute("width")).toBe("112");

    // Risk dashboard: the overall pill and seven rows, each with five 9×5 segments filled by its level.
    await expect(page.getByTestId("desk-portfolio-risk-title")).toHaveText("Risk dashboard");
    await expect(page.getByTestId("desk-risk-overall-pill")).toHaveText("High risk");
    const expected: Record<string, { filled: number; text: string }> = {
      overall: { filled: 4, text: "High" },
      position: { filled: 4, text: "Above limit" },
      sector: { filled: 4, text: "Over-concentrated" },
      correlation: { filled: 4, text: `${CORRELATION.high_pairs} pair ≥ ${CORRELATION.high_threshold.toFixed(2)}` },
      gap: { filled: 0, text: "—" },
      volatility: { filled: 4, text: "High" },
      liquidity: { filled: 0, text: "—" },
    };
    for (const [id, label] of RISK_ROWS) {
      const row = page.getByTestId(`desk-risk-${id}`);
      await expect(row).toContainText(label);
      const barEl = row.getByTestId("desk-risk-bar");
      await expect(barEl).toHaveAttribute("data-filled", String(expected[id].filled));
      await expect(barEl.locator("span")).toHaveCount(5);
      expect(await barEl.locator("span").first().evaluate((e) => [getComputedStyle(e).width, getComputedStyle(e).height])).toEqual(["9px", "5px"]);
      await expect(row.getByTestId("desk-risk-level")).toHaveText(expected[id].text);
    }

    // Positions: header STOCK · VALUE ₹ · P&L · WEIGHT, grid 1fr 72px 64px 46px, weights to the whole percent.
    const positions = page.getByTestId("desk-portfolio-positions");
    await expect(positions.getByRole("columnheader")).toHaveText(["Stock", "Value ₹", "P&L", "Weight"]);
    expect(await positions.getByTestId("desk-portfolio-position").first().evaluate((e) => getComputedStyle(e).gridTemplateColumns.split(" ").slice(1))).toEqual(["72px", "64px", "46px"]);
    await expect(positions.getByTestId("desk-portfolio-weight")).toHaveText(["30%", "10%"]);
    await expect(page.getByTestId("desk-portfolio-synced")).toHaveText(/^Last read 12 Oct, 3:42\s?pm$/i);
    await expect(page.getByTestId("desk-portfolio-readonly-note")).toHaveText("● Read-only view from connected brokers. No trading or order execution in Nivesh.");

    let o = await sideways(page);
    expect(o.doc).toBeLessThanOrEqual(1);
    expect(o.scroll).toBeLessThanOrEqual(1);
    await page.getByTestId("desk-risk-correlation-toggle").click();
    await expect(page.getByTestId("desk-corr-pair")).toHaveCount(CORRELATION.pairs.length);
    await page.getByTestId("desk-paper-sample-replay").click();
    await expect(page.getByTestId("desk-calibration-row").first()).toBeVisible();
    o = await sideways(page);
    expect(o.doc).toBeLessThanOrEqual(1);
    expect(o.scroll).toBeLessThanOrEqual(1);
  });

  test("fidelity screenshots: desktop 1440 with the dock, and 390", async ({ page }) => {
    const phase = "after";
    await page.setViewportSize({ width: 1440, height: 900 });
    await deskBase(page);
    await mockPaper(page);
    await mockDeskLists(page);
    await portfolioData(page, { holdings: HOLDINGS, concentration: CONCENTRATION });
    await page.goto(`${DESK}?tab=portfolio`);
    await expect(page.getByTestId("desk-portfolio-hub")).toBeVisible();
    await page.getByTestId("desk-paper-sample-replay").click();
    await page.waitForTimeout(600);
    await page.screenshot({ path: `${SHOTS}/fidelity-portfolio-${phase}-1440.png` });
    await page.setViewportSize({ width: 1440, height: 2000 });
    await page.waitForTimeout(300);
    await page.screenshot({ path: `${SHOTS}/fidelity-portfolio-${phase}-1440-tall.png` });

    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto(`${DESK}?tab=portfolio`);
    await expect(page.getByTestId("desk-portfolio-hub")).toBeVisible();
    await page.waitForTimeout(600);
    await page.screenshot({ path: `${SHOTS}/fidelity-portfolio-${phase}-390.png` });
    await page.setViewportSize({ width: 390, height: 4200 });
    await page.waitForTimeout(300);
    await page.screenshot({ path: `${SHOTS}/fidelity-portfolio-${phase}-390-full.png` });
  });
});
