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
 * forward / replay calibration; TC-30 the NIFTY and BANKNIFTY cards; TC-31 the
 * ATM / R / S / MP tags; TC-32 a stock loaded by ticker and a ticker with no F&O
 * rows; TC-33 OI build-up from GET /api/fno/scan/buildup (counts, sort, filter,
 * a row opens its chain); TC-7 no sideways scroll at 390px on both tabs.
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
/** GET /api/broker/positions with no account signed in (broker_connect.py :: get_all_positions). */
const NO_LIVE_ACCOUNT = { as_of: "2026-10-12T10:15:00+00:00", kind: "net", segment: "all", accounts: [] };

async function deskBase(page: Page) {
  await mockApi(page, "populated");
  await mockSingleRoute(page, "**/api/markets/home", "markets-home.json");
  await page.route("**/api/chat/sessions", (route) => route.fulfill({ status: 200, contentType: "application/json", body: "[]" }));
  await json(page, "**/api/positional/watchlist*", WATCHLIST);
  await json(page, "**/api/positional/picks*", PICKS);
  await json(page, "**/api/move-odds/latest*", { detail: "Feature not enabled for this account" }, 403);
  await json(page, "**/api/positional/journal/summary/portfolio", JOURNAL_SUMMARY);
  // The broker block (desk/BrokerPositions): accounts, the holdings a broker read stored, live positions.
  await json(page, "**/api/broker/positions*", NO_LIVE_ACCOUNT);
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

test.describe("Smart trading desk — Portfolio & risk", () => {
  test.beforeEach(async ({ page }) => {
    await deskBase(page);
  });

  test("TC-28 positions with weights, a stock above 25% in amber, sector concentration, beta and VaR", async ({ page }) => {
    await mockPaper(page, { status: 403, body: { detail: "Feature not enabled" } });
    await mockDeskLists(page);
    await portfolioData(page, { holdings: HOLDINGS, concentration: CONCENTRATION });
    await page.goto(`${DESK}?tab=portfolio`);

    const hub = page.getByTestId("desk-portfolio-hub");
    await expect(hub).toContainText("Portfolio · broker hub");
    await expect(hub).toContainText("Read-only");
    // copilot-trader-broker-accounts.json: Zerodha, last read 2026-10-12T10:12Z = 12 Oct 3:42 pm IST
    await expect(page.getByTestId("desk-portfolio-sources")).toHaveText(/^Zerodha · last read 12 Oct, 3:42\s?pm$/i);
    await expect(hub.locator('[data-testid="entity-icon"][data-kind="broker"]')).toHaveCount(1);
    await expect(page.getByTestId("desk-portfolio-value")).toHaveText("₹10.00 L");
    await expect(page.getByTestId("desk-portfolio-pnl")).toHaveText("+₹1.40 L · +16.3%");
    await expect(hub).toContainText("3 holdings on record · direct stocks ₹4.00 L (40.0% of the value)");

    // positions: the two direct stocks, largest first, each with its company icon; the fund is not listed
    const positions = page.getByTestId("desk-portfolio-positions");
    await expect(page.getByTestId("desk-portfolio-stock-count")).toHaveText("2");
    await expect(positions).not.toContainText("Fixture Flexi Cap Fund");
    await expect(positions.locator('[data-testid="entity-icon"][data-kind="stock"]')).toHaveCount(2);
    const heavy = positions.getByRole("row").filter({ hasText: "FIXHEAVY" });
    await expect(heavy).toContainText("Fixture Heavy Ltd");
    await expect(heavy).toContainText("₹3.00 L");
    await expect(heavy).toContainText("+20.0%");
    const heavyWeight = heavy.getByTestId("desk-portfolio-weight");
    await expect(heavyWeight).toHaveText("30.0%");
    await expect(heavyWeight).toHaveAttribute("data-over", "true");
    await expect(heavyWeight).toHaveCSS("color", await amberColour(page));
    const light = positions.getByRole("row").filter({ hasText: "FIXLIGHT" });
    await expect(light).toContainText("−9.1%");
    await expect(light.getByTestId("desk-portfolio-weight")).toHaveText("10.0%");
    await expect(light.getByTestId("desk-portfolio-weight")).toHaveAttribute("data-over", "false");
    await expect(positions).toContainText("single-stock limit");

    // the sector ring: five listed sectors that add to 100%, so no "Other sectors" slice
    const sectors = page.getByTestId("desk-portfolio-sector-row");
    await expect(sectors).toHaveCount(5);
    await expect(sectors.nth(0)).toContainText("Financial");
    await expect(sectors.nth(0)).toContainText("48.0%");
    await expect(page.getByTestId("desk-portfolio-mcap-note")).toHaveCount(0);
    await expect(page.getByTestId("desk-portfolio-mcap")).toBeVisible();

    // risk checks, in order: beta, largest stock, sector, volatility, VaR, then the route's drivers
    const risk = page.getByTestId("desk-portfolio-risk");
    await expect(risk.locator('li[data-testid^="desk-risk-"]')).toHaveCount(8);
    await expect(page.getByTestId("desk-risk-beta-value")).toHaveText("1.32");
    await expect(page.getByTestId("desk-risk-beta")).toHaveAttribute("data-level", "High");
    await expect(page.getByTestId("desk-risk-single-stock-value")).toHaveText("30.0%");
    await expect(page.getByTestId("desk-risk-single-stock")).toHaveAttribute("data-level", "Above limit");
    await expect(page.getByTestId("desk-risk-single-stock").locator('[data-testid="entity-icon"]')).toHaveAttribute("data-key", "FIXHEAVY");
    await expect(page.getByTestId("desk-risk-sector")).toContainText("Financial is 48.0% of sector exposure, above the 35% cap · HHI 3,138 · 3.2 effective sectors");
    await expect(page.getByTestId("desk-risk-sector")).toHaveAttribute("data-level", "Over-concentrated");
    await expect(page.getByTestId("desk-risk-volatility-value")).toHaveText("18.5%");
    await expect(page.getByTestId("desk-risk-volatility")).toHaveAttribute("data-level", "High");
    await expect(page.getByTestId("desk-risk-var-value")).toHaveText("₹19,171 (1.92%)");
    await expect(page.getByTestId("desk-risk-var")).toContainText("95% confidence");
    await expect(page.getByTestId("desk-risk-driver-smallcap-weight")).toContainText("Smallcap weight");
    await expect(page.getByTestId("desk-risk-driver-smallcap-weight")).toContainText("30.0% of the portfolio’s value");
    await expect(page.getByTestId("desk-risk-driver-smallcap-weight")).toHaveAttribute("data-level", "Medium");
    await expect(page.getByTestId("desk-risk-driver-debt-gold-buffer")).toHaveAttribute("data-level", "High");
    await expect(page.getByTestId("desk-portfolio-risk-note")).toContainText("cover 100.0% of the portfolio’s value");

    // correlated positions: from GET /api/portfolio/correlation (its own test below); nothing says "not connected"
    const corr = page.getByTestId("desk-portfolio-correlation");
    await expect(corr).toBeVisible();
    await expect(corr).toContainText("Correlated positions");
    await expect(corr).not.toContainText("Not connected yet");
    await expect(corr.getByTestId("desk-corr-pair")).toHaveCount(CORRELATION.pairs.length);

    // right card: the journal summary, and the paper record's 403 as "not enabled"
    await expect(page.getByTestId("desk-journal-open")).toHaveText("1");
    await expect(page.getByTestId("desk-journal-closed")).toHaveText("2");
    await expect(page.getByTestId("desk-journal-win-rate")).toHaveText("50.0%");
    await expect(page.getByTestId("desk-journal-realised")).toHaveText("+₹600");
    await expect(page.getByTestId("desk-paper-no-access")).toContainText("not enabled for this account");
    await expect(page.getByTestId("desk-calibration")).toHaveCount(0);

    // the broker block from the Trader desk is mounted below
    await expect(page.getByTestId("trader-broker-positions")).toBeVisible();
    await expect(page.getByTestId("trader-broker-account")).toContainText("Zerodha");
  });

  test("TC-28 over the shared fixtures: equity rows only, weights from the route, sector split with the rest folded", async ({ page }) => {
    await mockPaper(page);
    await mockDeskLists(page);
    await portfolioData(page);
    await page.goto(`${DESK}?tab=portfolio`);

    // holdings-enriched.json: the direct stocks are the equity / stock rows, largest value first
    const fx = load("holdings-enriched.json") as { holdings: Array<{ asset_type: string; value_rs: number | null; weight_pct: number | null; nse_symbol: string | null; name: string }>; totals: { value_rs: number } };
    const stocks = fx.holdings.filter((h) => ["equity", "stock"].includes(h.asset_type)).sort((a, b) => (b.value_rs ?? -1) - (a.value_rs ?? -1));
    await expect(page.getByTestId("desk-portfolio-stock-count")).toHaveText(String(stocks.length));
    // totals.value_rs 1,03,06,772.40 → ₹1.03 Cr
    expect((fx.totals.value_rs / 1e7).toFixed(2)).toBe("1.03");
    await expect(page.getByTestId("desk-portfolio-value")).toHaveText("₹1.03 Cr");
    const first = page.getByTestId("desk-portfolio-positions").getByRole("row").nth(1);
    await expect(first).toContainText(stocks[0].nse_symbol ?? stocks[0].name);
    await expect(first.getByTestId("desk-portfolio-weight")).toHaveText(`${(stocks[0].weight_pct ?? 0).toFixed(1)}%`);
    await expect(page.getByTestId("desk-portfolio-weight").and(page.locator('[data-over="true"]'))).toHaveCount(0);
    await expect(page.getByTestId("desk-risk-single-stock")).toHaveAttribute("data-level", "Within limit");

    // concentration.json: the five largest sectors by name, then 100 − their sum as "Other sectors"
    const conc = load("concentration.json") as { sector: { items: Array<{ name: string; pct: number }>; caution_pct: number } };
    const top5 = [...conc.sector.items].sort((a, b) => b.pct - a.pct).slice(0, 5);
    const rest = 100 - top5.reduce((s, x) => s + x.pct, 0);
    const rows = page.getByTestId("desk-portfolio-sector-row");
    await expect(rows).toHaveCount(6);
    await expect(rows.nth(0)).toContainText(top5[0].name);
    await expect(rows.nth(5)).toContainText("Other sectors");
    await expect(rows.nth(5)).toContainText(`${rest.toFixed(1)}%`);
    // largest classified sector ("Unclassified" and "Other" are not judged) under the caution level → Balanced
    const classified = conc.sector.items.find((i) => !/unclassified|other/i.test(i.name));
    await expect(page.getByTestId("desk-risk-sector")).toContainText(`${classified?.name} is ${classified?.pct.toFixed(1)}% of sector exposure, under the ${conc.sector.caution_pct}% cap`);
    await expect(page.getByTestId("desk-risk-sector")).toHaveAttribute("data-level", "Balanced");

    // the paper record: forward first and named; the forward fixture has no outcomes yet
    await expect(page.getByTestId("desk-paper-sample-forward")).toHaveAttribute("aria-pressed", "true");
    await expect(page.getByTestId("desk-paper-sample-note")).toContainText("Forward sample");
    await expect(page.getByTestId("desk-paper-statement")).toContainText("Not established: 0 counted sessions");
    await expect(page.getByTestId("desk-calibration-none")).toBeVisible();

    // replay, every eligible stock (paper-evaluation-replay-P5-NEXT.json buckets.universe): five buckets
    await page.getByTestId("desk-paper-sample-replay").click();
    await expect(page.getByTestId("desk-paper-sample-note")).toContainText("Replay sample");
    const ev = load("paper-evaluation-replay-P5-NEXT.json").data.evaluation as { buckets: { universe: Array<{ lo: number; predicted_mean: number; model_label_rate: number }>; selected: Array<{ n: number }> } };
    const bars = page.getByTestId("desk-calibration-row");
    await expect(bars).toHaveCount(ev.buckets.universe.length);
    const b10 = ev.buckets.universe.find((b) => b.lo === 0.1)!;
    const row10 = page.locator('[data-testid="desk-calibration-row"][data-lo="10"]');
    await expect(row10.getByTestId("desk-calibration-realised")).toHaveText(`${(b10.model_label_rate * 100).toFixed(1)}%`);
    await expect(row10.getByTestId("desk-calibration-predicted")).toHaveText(`${(b10.predicted_mean * 100).toFixed(1)}%`);
    // selected five: the 0–10% bucket has no trades (n 0), so it has no bar
    await page.getByTestId("desk-paper-set-selected").click();
    await expect(bars).toHaveCount(ev.buckets.selected.filter((b) => b.n > 0).length);
    await expect(page.locator('[data-testid="desk-calibration-row"][data-lo="0"]')).toHaveCount(0);
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

    const empty = page.getByTestId("desk-portfolio-empty");
    await expect(empty).toContainText("No holdings on record yet");
    await expect(page.getByTestId("desk-portfolio-positions")).toHaveCount(0);
    await expect(page.getByTestId("desk-portfolio-risk")).toHaveCount(0);
    await page.getByTestId("desk-portfolio-connect").click();
    await expect(page).toHaveURL(/\/v5\/app\/page\/brokers/);
  });
});

test.describe("Smart trading desk — Portfolio & risk: correlation, market cap, paper trades and alerts", () => {
  test.beforeEach(async ({ page }) => {
    await deskBase(page);
    await mockPaper(page);
  });

  test("correlated positions: the route's pairs with both icons, values, the 0.70 flag, method, sessions and skips", async ({ page }) => {
    await mockDeskLists(page);
    await portfolioData(page, { holdings: HOLDINGS, concentration: CONCENTRATION });
    await page.goto(`${DESK}?tab=portfolio`);
    const block = page.getByTestId("desk-portfolio-correlation");
    const pairs = block.getByTestId("desk-corr-pair");
    await expect(pairs).toHaveCount(CORRELATION.pairs.length);
    for (let i = 0; i < CORRELATION.pairs.length; i += 1) {
      const p = CORRELATION.pairs[i];
      const row = pairs.nth(i);
      const high = p.corr >= CORRELATION.high_threshold;
      await expect(row).toHaveAttribute("data-pair", `${p.a}-${p.b}`);
      await expect(row).toHaveAttribute("data-high", String(high));
      await expect(row.getByTestId("desk-corr-value")).toHaveText(dec2(p.corr));
      await expect(row.getByTestId("desk-corr-flag")).toHaveCount(high ? 1 : 0);
      const icons = row.locator('[data-testid="entity-icon"]');
      await expect(icons).toHaveCount(2);
      await expect(icons.nth(0)).toHaveAttribute("data-key", p.a);
      await expect(icons.nth(1)).toHaveAttribute("data-key", p.b);
      await expect(row).toContainText(`${p.weight_a_pct.toFixed(1)}% and ${p.weight_b_pct.toFixed(1)}% of the portfolio · ${p.common_sessions} common sessions`);
    }
    // The route's own counts over every pair; the average worked out here matches its figure.
    const avg = CORRELATION.pairs.reduce((a, p) => a + p.corr, 0) / CORRELATION.pairs.length;
    expect(avg.toFixed(2)).toBe(CORRELATION.avg_corr.toFixed(2));
    expect(CORRELATION.pairs.filter((p) => p.corr >= CORRELATION.high_threshold).length).toBe(CORRELATION.high_pairs);
    await expect(block.getByTestId("desk-corr-summary")).toHaveText(
      `${CORRELATION.high_pairs} pair at ${CORRELATION.high_threshold.toFixed(2)} or above of ${CORRELATION.pairs_total} pairs · average ${avg.toFixed(2)} · ${CORRELATION.holdings_used} stocks compared`,
    );
    await expect(block.getByTestId("desk-corr-method")).toContainText(
      `${CORRELATION.method} over ${CORRELATION.sessions} sessions (a stock needs at least ${CORRELATION.min_sessions}) · ${CORRELATION.source} · end of day ${dayY(CORRELATION.as_of)}`,
    );
    await expect(block.getByTestId("desk-corr-skipped")).toHaveText(`Not compared: ${CORRELATION.holdings_skipped[0].symbol} (${CORRELATION.holdings_skipped[0].reason}).`);
  });

  test("correlated positions: fewer than two usable stocks, and a failed read with retry", async ({ page }) => {
    await mockDeskLists(page);
    await portfolioData(page, { holdings: HOLDINGS, concentration: CONCENTRATION, correlation: { status: 200, body: { ...CORRELATION, holdings_used: 1, high_pairs: 0, avg_corr: null, pairs_total: 0, pairs: [] } } });
    await page.goto(`${DESK}?tab=portfolio`);
    await expect(page.getByTestId("desk-corr-none")).toContainText(`Fewer than two of your stocks have enough daily prices to compare over ${CORRELATION.sessions} sessions.`);
    await expect(page.getByTestId("desk-corr-none")).toContainText("Not compared: FIXNEW");

    let reads = 0;
    await page.route("**/api/portfolio/correlation*", (route) => { reads += 1; return route.fulfill({ status: 502, contentType: "application/json", body: JSON.stringify({ detail: "upstream_unavailable" }) }); });
    await page.reload();
    const err = page.getByTestId("desk-corr-error");
    await expect(err.getByRole("alert")).toContainText("Correlated positions didn’t load", { timeout: 15_000 });
    const before = reads;
    await err.getByRole("button", { name: /Retry/ }).click();
    await expect.poll(() => reads).toBeGreaterThan(before);
  });

  test("market-cap split as the route answers today: large cap split, the rest named as not split yet with the route's reason", async ({ page }) => {
    await mockDeskLists(page);
    await portfolioData(page, { holdings: HOLDINGS, concentration: CONCENTRATION });
    await page.goto(`${DESK}?tab=portfolio`);
    const block = page.getByTestId("desk-portfolio-mcap");
    const rows = block.getByTestId("desk-mcap-row");
    await expect(rows).toHaveCount(MCAP_PARTIAL.buckets.length);
    for (const b of MCAP_PARTIAL.buckets) {
      const row = block.locator(`[data-testid="desk-mcap-row"][data-bucket="${b.bucket}"]`);
      await expect(row).toHaveAttribute("data-available", String(b.available));
      if (b.available) {
        // Each weight is its value over the direct stocks' total.
        expect(((b.value_rs as number) / MCAP_PARTIAL.total_value_rs) * 100).toBeCloseTo(b.weight_pct as number, 6);
        await expect(row.getByTestId("desk-mcap-weight")).toHaveText(`${(b.weight_pct as number).toFixed(1)}%`);
        await expect(row.getByTestId("desk-mcap-value")).toHaveText(lakh(b.value_rs as number));
        await expect(row.getByTestId("desk-mcap-count")).toHaveText(`${b.count} stock`);
      } else {
        await expect(row.getByTestId("desk-mcap-weight")).toHaveText("Not available");
      }
    }
    // large + unsplit = the equity total
    const u = MCAP_PARTIAL.unsplit;
    expect((MCAP_PARTIAL.buckets[0].value_rs as number) + u.value_rs).toBe(MCAP_PARTIAL.total_value_rs);
    await expect(block.getByTestId("desk-mcap-unsplit")).toContainText(`Outside Nifty 100 — not split yet: ${lakh(u.value_rs)} (${u.weight_pct.toFixed(1)}%) · ${u.count} stock`);
    await expect(block.getByTestId("desk-mcap-reason")).toHaveText(`${u.reason}.`);
    // The bar: the large-cap share and the not-split share.
    await expect(block.getByTestId("desk-mcap-bar").locator("span")).toHaveCount(2);
    await expect(block.getByTestId("desk-mcap-bar-unsplit")).toHaveCount(1);
    // Method, each list's date and size (or "not on record"), the total and the funds left out.
    const note = block.getByTestId("desk-mcap-note");
    await expect(note).toContainText(MCAP_PARTIAL.method);
    await expect(note).toContainText(`Lists: ${MCAP_PARTIAL.indices.map((ix) => (ix.available ? `${ix.index} (${ix.members} members, ${dayY(ix.as_of as string)})` : `${ix.index} (not on record)`)).join(" · ")}.`);
    await expect(note).toContainText(`(${lakh(MCAP_PARTIAL.total_value_rs)})`);
    await expect(note).toContainText(`Funds and other holdings (${lakh(MCAP_PARTIAL.excluded.funds_value_rs)}) are not split.`);
  });

  test("market-cap split once every list is on record: five buckets, no not-split line; a failed read says so", async ({ page }) => {
    await mockDeskLists(page);
    await portfolioData(page, { holdings: HOLDINGS, concentration: CONCENTRATION, mcap: { status: 200, body: MCAP_FULL } });
    await page.goto(`${DESK}?tab=portfolio`);
    const block = page.getByTestId("desk-portfolio-mcap");
    for (const b of MCAP_FULL.buckets) {
      const row = block.locator(`[data-testid="desk-mcap-row"][data-bucket="${b.bucket}"]`);
      await expect(row).toHaveAttribute("data-available", "true");
      await expect(row.getByTestId("desk-mcap-weight")).toHaveText(`${(b.weight_pct as number).toFixed(1)}%`);
    }
    expect(MCAP_FULL.buckets.reduce((a, b) => a + (b.weight_pct as number), 0)).toBeCloseTo(100, 6);
    // A zero bucket is listed but not drawn.
    await expect(block.getByTestId("desk-mcap-bar").locator("span")).toHaveCount(MCAP_FULL.buckets.filter((b) => (b.weight_pct as number) > 0).length);
    await expect(block.getByTestId("desk-mcap-unsplit")).toHaveCount(0);
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

// ── F&O payloads ─────────────────────────────────────────────────────────

/** The synthetic NIFTY chains (copilot-app-options.spec.ts): 27 Oct (future), 24 Nov (put-call parity), 30 Mar 2027. */
const NIFTY_CHAINS: Record<string, string> = {
  "2026-10-27": "copilot-options-chain.json",
  "2026-11-24": "copilot-options-chain-parity.json",
  "2027-03-30": "copilot-options-chain-carried.json",
};

const side = (close: number, oi: number, change_in_oi: number, iv: number | null = null) => ({
  close, settle: close, oi, change_in_oi, volume: Math.round(oi / 4), iv, iv_price: iv == null ? null : "settle",
  delta: null, gamma: null, theta: null, vega: null, change: null, change_pct: null, oi_buildup: null,
});

/**
 * BANKNIFTY in the shape of GET /api/fno/{symbol}/chain (backend/routes/fno.py :: chain), 11 strikes, all of the expiry.
 * Spot 52,040 → ATM 52,000. Call OI peaks at 52,500 (9.00 L) = R; put OI peaks at 51,500 (11.00 L) = S.
 * Totals: call 68,50,000, put 54,90,000 → PCR 0.8015 → 0.80.
 * Max pain = the strike K minimising Σ call OI × max(0, K − strike) + Σ put OI × max(0, strike − K):
 *   51,700 → 836.0 Cr, 51,800 → 716.0 Cr, 51,900 → 724.0 Cr → 51,800.
 * ATM straddle 690.20 + 520.20 = 1,210.40 = 2.33% of 52,040. ATM IV (14.10 + 14.40) / 2 = 14.25.
 */
const BN_STRIKES = [51500, 51600, 51700, 51800, 51900, 52000, 52100, 52200, 52300, 52400, 52500];
const BN_CALL = { oi: [400000, 450000, 500000, 520000, 560000, 600000, 640000, 700000, 760000, 820000, 900000], close: [1050.0, 975.5, 903.0, 823.4, 755.0, 690.2, 628.6, 570.5, 516.0, 465.3, 418.0], chg: [-5000, 0, 5000, 10000, 20000, 30000, 40000, 50000, 60000, 70000, 90000] };
const BN_PUT = { oi: [1100000, 980000, 860000, 760000, 600000, 450000, 300000, 200000, 120000, 80000, 40000], close: [335.0, 362.4, 392.0, 424.1, 459.4, 520.2, 560.0, 603.3, 650.1, 700.0, 752.5], chg: [80000, 60000, 50000, 40000, 20000, 10000, 0, -10000, -20000, -20000, -10000] };
const sum = (xs: number[]) => xs.reduce((a, b) => a + b, 0);
const BN_CHAIN = {
  symbol: "BANKNIFTY",
  summary: {
    as_of: "2026-10-12", expiry: "2026-10-28", spot: 52040.0, atm_strike: 52000,
    total_call_oi: sum(BN_CALL.oi), total_put_oi: sum(BN_PUT.oi), total_call_oi_change: sum(BN_CALL.chg), total_put_oi_change: sum(BN_PUT.chg),
    pcr: 0.8015, max_pain: 51800, max_call_oi: { strike: 52500, oi: 900000 }, max_put_oi: { strike: 51500, oi: 1100000 },
    days_to_expiry: 16, forward: 52160.0, forward_basis: "future", rate_pct: 5.75, atm_iv: 14.25, expected_move: 1210.4, expected_move_pct: 2.33,
  },
  strikes: BN_STRIKES.map((strike, i) => ({
    strike,
    call: side(BN_CALL.close[i], BN_CALL.oi[i], BN_CALL.chg[i], strike === 52000 ? 14.1 : null),
    put: side(BN_PUT.close[i], BN_PUT.oi[i], BN_PUT.chg[i], strike === 52000 ? 14.4 : null),
  })),
  strike_count: 11, strikes_returned: 11, lot_size: 30,
};
const BN_EXPIRIES = { symbol: "BANKNIFTY", as_of: "2026-10-12", expiries: [{ expiry: "2026-10-28", days_to_expiry: 16 }], count: 1 };
/** GET /api/fno/{symbol}/futures: settle 52,160 − spot 52,040 = +120.00 premium; OI change +84,000. */
const BN_FUTURES = { symbol: "BANKNIFTY", as_of: "2026-10-12", spot: 52040.0, lot_size: 30, futures: [{ expiry: "2026-10-28", close: 52161.0, settle: 52160.0, oi: 2100000, change_in_oi: 84000, volume: 900000, basis: 120.0 }], count: 1 };

/**
 * FIXFNO, a made-up F&O stock: five strikes, spot 1,502.50 → ATM 1,500. Totals call 16,00,000, put 15,00,000 → PCR 0.9375 → 0.94.
 * Max pain: 1,480 → 1.98 Cr, 1,500 → 1.32 Cr, 1,520 → 1.96 Cr → 1,500. Straddle 31.50 + 27.60 = 59.10 = 3.93% of 1,502.50.
 */
const FIX_STRIKES = [1460, 1480, 1500, 1520, 1540];
const FIX_CALL = { oi: [100000, 150000, 300000, 450000, 600000], close: [52.0, 41.2, 31.5, 23.1, 16.4], chg: [0, 10000, 20000, 30000, 40000] };
const FIX_PUT = { oi: [500000, 420000, 350000, 150000, 80000], close: [12.1, 18.9, 27.6, 39.0, 52.3], chg: [30000, 20000, 10000, 0, -5000] };
const FIX_CHAIN = {
  symbol: "FIXFNO",
  summary: {
    as_of: "2026-10-12", expiry: "2026-10-27", spot: 1502.5, atm_strike: 1500,
    total_call_oi: sum(FIX_CALL.oi), total_put_oi: sum(FIX_PUT.oi), total_call_oi_change: sum(FIX_CALL.chg), total_put_oi_change: sum(FIX_PUT.chg),
    pcr: 0.9375, max_pain: 1500, max_call_oi: { strike: 1540, oi: 600000 }, max_put_oi: { strike: 1460, oi: 500000 },
    days_to_expiry: 15, forward: 1509.6, forward_basis: "future", rate_pct: 5.75, atm_iv: 26.4, expected_move: 59.1, expected_move_pct: 3.93,
  },
  strikes: FIX_STRIKES.map((strike, i) => ({ strike, call: side(FIX_CALL.close[i], FIX_CALL.oi[i], FIX_CALL.chg[i]), put: side(FIX_PUT.close[i], FIX_PUT.oi[i], FIX_PUT.chg[i]) })),
  strike_count: 5, strikes_returned: 5, lot_size: 500,
};
const FIX_EXPIRIES = { symbol: "FIXFNO", as_of: "2026-10-12", expiries: [{ expiry: "2026-10-27", days_to_expiry: 15 }], count: 1 };
const FIX_FUTURES = { symbol: "FIXFNO", as_of: "2026-10-12", spot: 1502.5, lot_size: 500, futures: [{ expiry: "2026-10-27", close: 1510.0, settle: 1509.6, oi: 5400000, change_in_oi: -120000, volume: 2100000, basis: 7.1 }], count: 1 };

/**
 * GET /api/fno/scan/buildup (backend/nidp/services/daas_api/routers/desk_market.py :: fno_buildup, via routes/fno.py).
 * Rows come largest |OI chg %| first; the label is null when a change is missing (counted as no_data). FIXFNO is the
 * stock the lab can load (fnoData), so its row opens a real chain.
 */
const bu = (symbol: string, price: number | null, oiPct: number | null, label: string | null, extra: Record<string, unknown> = {}) => ({
  symbol, near_expiry: "2026-10-27", close: price == null ? null : 1000 * (1 + price / 100), prev_close: price == null ? null : 1000,
  price_chg_pct: price, oi: 1_000_000, oi_chg: oiPct == null ? null : Math.round((1_000_000 * oiPct) / (100 + oiPct)), oi_chg_pct: oiPct, expiries: 3, label, ...extra,
});
const BUILDUP_ROWS = [
  bu("FIXFNO", 2.03, 12.5, "long_buildup", { close: 1510.0, prev_close: 1480.0, oi: 5_400_000, oi_chg: 600_000 }),
  bu("FIXSHORT", -1.8, 9.2, "short_buildup"),
  bu("FIXCOVER", 0.9, -7.4, "short_covering"),
  bu("FIXUNWIND", -2.4, -5.1, "long_unwinding"),
  bu("FIXLONG2", 0.4, 3.3, "long_buildup", { expiries: 2 }),
  bu("FIXFLAT", 0.0, 1.0, "neutral"),
  bu("FIXNODATA", null, null, null, { expiries: 1 }),
];
const countBy = (label: string | null) => BUILDUP_ROWS.filter((r) => r.label === label).length;
const BUILDUP = {
  as_of: "2026-10-13", source: "NSE F&O bhavcopy (nidp.fno_bhavcopy), stock futures", universe: BUILDUP_ROWS.length,
  counts: { long_buildup: countBy("long_buildup"), short_buildup: countBy("short_buildup"), short_covering: countBy("short_covering"), long_unwinding: countBy("long_unwinding"), neutral: countBy("neutral"), no_data: countBy(null) },
  rows: BUILDUP_ROWS,
};

/** Every /api/fno/* route. Returns the paths (with query) the page asked for. */
async function fnoData(page: Page): Promise<string[]> {
  const asked: string[] = [];
  page.on("request", (r) => {
    const u = new URL(r.url());
    if (u.pathname.startsWith("/api/fno/")) asked.push(u.pathname + u.search);
  });
  await json(page, "**/api/fno/NIFTY/expiries", load("copilot-options-expiries.json"));
  await json(page, "**/api/fno/NIFTY/futures", load("copilot-options-futures.json"));
  await page.route("**/api/fno/NIFTY/chain*", (route) => {
    const expiry = new URL(route.request().url()).searchParams.get("expiry") ?? "2026-10-27";
    return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(load(NIFTY_CHAINS[expiry] ?? NIFTY_CHAINS["2026-10-27"])) });
  });
  await json(page, "**/api/fno/BANKNIFTY/expiries", BN_EXPIRIES);
  await json(page, "**/api/fno/BANKNIFTY/futures", BN_FUTURES);
  await json(page, "**/api/fno/BANKNIFTY/chain*", BN_CHAIN);
  await json(page, "**/api/fno/FIXFNO/expiries", FIX_EXPIRIES);
  await json(page, "**/api/fno/FIXFNO/futures", FIX_FUTURES);
  await json(page, "**/api/fno/FIXFNO/chain*", FIX_CHAIN);
  // backend/routes/fno.py answers 404 with no_data(sym) when the bhavcopy has no rows for the underlying
  await json(page, "**/api/fno/NOFNO/**", { detail: "No F&O data for NOFNO" }, 404);
  await json(page, "**/api/fno/scan/buildup*", BUILDUP);
  return asked;
}

const chainRow = (page: Page, strike: number) => page.locator(`[data-testid="desk-fno-chain-row"][data-strike="${strike}"]`);
const tagsOf = async (page: Page, strike: number) => (await chainRow(page, strike).locator('[data-testid^="desk-fno-tag-"]').allTextContents()).join(" ");

test.describe("Smart trading desk — Options & futures lab", () => {
  test.beforeEach(async ({ page }) => {
    await deskBase(page);
  });

  test("header, expiry choice and the eight stats come from the NIFTY chain and futures", async ({ page }) => {
    const asked = await fnoData(page);
    await page.goto(`${DESK}?tab=fno`);

    const tab = page.getByTestId("desk-fno");
    await expect(tab).toContainText("Options & futures lab · NSE F&O");
    await expect(tab).toContainText("Analysis only");
    await expect(tab).toContainText("End of day");
    // copilot-options-chain.json: spot 25,010, data day 12 Oct 2026
    await expect(page.getByTestId("desk-fno-spot")).toHaveText("25,010.00");
    await expect(page.getByTestId("desk-fno-asof")).toHaveText("bhavcopy · 12 Oct 2026 · end of day");
    await expect(page.getByTestId("desk-fno-symbol-nifty")).toHaveAttribute("aria-pressed", "true");

    // expiries nearest first; 27 Oct is monthly because a future expires that day (copilot-options-futures.json)
    await expect(page.getByTestId("desk-fno-expiry").locator("option")).toHaveText([
      "27 Oct 2026 · 15 days · monthly",
      "24 Nov 2026 · 43 days",
      "30 Mar 2027 · 169 days",
    ]);
    await expect(page.getByTestId("desk-fno-expiry")).toHaveValue("2026-10-27");

    await expect(page.getByTestId("desk-fno-atm-iv")).toHaveText("12.00%");
    // 273.45 + 213.60 = 487.05, 1.95% of 25,010
    await expect(page.getByTestId("desk-fno-expected-move")).toHaveText("±487.05");
    await expect(page.getByTestId("desk-fno-stats")).toContainText("1.95% of spot");
    // nearest future 27 Oct: settle 25,060, basis +50.00, change in OI −2,50,000
    await expect(page.getByTestId("desk-fno-futures")).toHaveText("25,060.00");
    await expect(page.getByTestId("desk-fno-stats")).toContainText("27 Oct 2026 · +50.00 premium to spot");
    await expect(page.getByTestId("desk-fno-days")).toHaveText("15");
    // 1,23,00,000 ÷ 1,27,51,300 = 0.9646
    await expect(page.getByTestId("desk-fno-pcr")).toHaveText("0.96");
    await expect(page.getByTestId("desk-fno-max-pain")).toHaveText("25,000");
    await expect(page.getByTestId("desk-fno-oi-range")).toHaveText("24,700 – 25,300");
    await expect(page.getByTestId("desk-fno-fut-oi-change")).toHaveText("−2.50 L");
    await expect(page.getByTestId("desk-fno-model-note")).toContainText("Model estimate from end-of-day prices (Black-76), at an interest rate of 5.75% a year. They are estimates, not quotes");
    await expect(page.getByTestId("desk-fno-sebi")).toContainText("9 out of 10 individual traders in equity F&O incurred net losses");

    // another expiry: 24 Nov (copilot-options-chain-parity.json): 43 days, straddle 550.85 + 322.40
    await page.getByTestId("desk-fno-expiry").selectOption("2026-11-24");
    await expect(page.getByTestId("desk-fno-days")).toHaveText("43");
    await expect(page.getByTestId("desk-fno-expected-move")).toHaveText("±873.25");
    expect(asked).toContain("/api/fno/NIFTY/chain?expiry=2026-11-24");
  });

  test("TC-31 the chain table tags ATM, R, S and MP on the right strikes, with a read from the figures", async ({ page }) => {
    await fnoData(page);
    await page.goto(`${DESK}?tab=fno`);

    // NIFTY: ATM 25,000 is also max pain; R (most call OI) 25,300; S (most put OI) 24,700
    await expect(page.getByTestId("desk-fno-view-chain")).toHaveAttribute("aria-selected", "true");
    await expect(page.getByTestId("desk-fno-chain-row")).toHaveCount(7);
    await expect(chainRow(page, 25000)).toHaveAttribute("data-atm", "true");
    expect(await tagsOf(page, 25000)).toBe("ATM MP");
    expect(await tagsOf(page, 25300)).toBe("R");
    expect(await tagsOf(page, 24700)).toBe("S");
    await expect(page.getByTestId("desk-fno-tag-r")).toHaveCount(1);
    await expect(page.getByTestId("desk-fno-tag-s")).toHaveCount(1);
    // the 25,300 call: OI 30,00,000 = 30.00 L, change +2,40,000 = +2.40 L, close 131.30
    await expect(chainRow(page, 25300).locator('[data-col="call-oi"]')).toHaveText("30.00 L");
    await expect(chainRow(page, 25300).locator('[data-col="call-oi-change"]')).toHaveText("+2.40 L");
    await expect(chainRow(page, 25300).locator('[data-col="call-close"]')).toHaveText("131.30");
    const read = page.getByTestId("desk-fno-chain-read");
    await expect(read).toContainText("the most call open interest is at 25,300 (30.00 L), the most put open interest at 24,700 (30.00 L), the put-call ratio on open interest is 0.96, max pain is 25,000.");
    await expect(read).toContainText("The end-of-day spot of 25,010.00 is between the two.");
    await expect(read).toContainText("not price targets");

    // BANKNIFTY: four different strikes — ATM 52,000, MP 51,800, R 52,500, S 51,500
    await page.getByTestId("desk-fno-symbol-banknifty").click();
    await expect(page.getByTestId("desk-fno-chain-row")).toHaveCount(11);
    await expect(chainRow(page, 52000)).toHaveAttribute("data-atm", "true");
    expect(await tagsOf(page, 52000)).toBe("ATM");
    expect(await tagsOf(page, 51800)).toBe("MP");
    expect(await tagsOf(page, 52500)).toBe("R");
    expect(await tagsOf(page, 51500)).toBe("S");
    await expect(page.getByTestId("desk-fno-pcr")).toHaveText("0.80");
  });

  test("TC-30 NIFTY and BANKNIFTY cards show each chain's PCR, max pain, walls and expected move", async ({ page }) => {
    await fnoData(page);
    await page.goto(`${DESK}?tab=fno`);
    await page.getByTestId("desk-fno-view-indices").click();

    const n = "desk-fno-card-NIFTY";
    await expect(page.getByTestId(`${n}-spot`)).toHaveText("25,010.00");
    await expect(page.getByTestId(`${n}-pcr`)).toHaveText("0.96");
    await expect(page.getByTestId(`${n}-max-pain`)).toHaveText("25,000");
    await expect(page.getByTestId(`${n}-put-wall`)).toHaveText("24,700");
    await expect(page.getByTestId(`${n}-call-wall`)).toHaveText("25,300");
    await expect(page.getByTestId(`${n}-move`)).toHaveText("12.00% · ±487.05 (1.95%)");
    await expect(page.getByTestId(`${n}-futures`)).toHaveText("25,060.00 · +50.00 premium");
    await expect(page.getByTestId(`${n}-fut-oi-change`)).toHaveText("−2.50 L");
    // expected-move band: 25,010 ± 487.05
    await expect(page.getByTestId(n)).toContainText("24,522.95–25,497.05");

    const b = "desk-fno-card-BANKNIFTY";
    await expect(page.getByTestId(`${b}-spot`)).toHaveText("52,040.00");
    await expect(page.getByTestId(`${b}-pcr`)).toHaveText("0.80");
    await expect(page.getByTestId(`${b}-max-pain`)).toHaveText("51,800");
    await expect(page.getByTestId(`${b}-put-wall`)).toHaveText("51,500");
    await expect(page.getByTestId(`${b}-call-wall`)).toHaveText("52,500");
    await expect(page.getByTestId(`${b}-move`)).toHaveText("14.25% · ±1,210.40 (2.33%)");
    await expect(page.getByTestId(`${b}-futures`)).toHaveText("52,160.00 · +120.00 premium");
    await expect(page.getByTestId(`${b}-fut-oi-change`)).toHaveText("+84,000");
    // 52,040 ± 1,210.40
    await expect(page.getByTestId(b)).toContainText("50,829.60–53,250.40");

    // the link opens that chain
    await page.getByTestId(`${b}-open`).click();
    await expect(page.getByTestId("desk-fno-view-chain")).toHaveAttribute("aria-selected", "true");
    await expect(page.getByTestId("desk-fno-symbol-banknifty")).toHaveAttribute("aria-pressed", "true");
    await expect(page.getByTestId("desk-fno-chain-row")).toHaveCount(11);
  });

  test("TC-32 a ticker loads that stock's chain; a ticker with no F&O rows says so", async ({ page }) => {
    const asked = await fnoData(page);
    await page.goto(`${DESK}?tab=fno`);
    await expect(page.getByTestId("desk-fno-pcr")).toHaveText("0.96");

    await page.getByTestId("desk-fno-symbol-input").fill("fixfno ");
    await page.getByTestId("desk-fno-symbol-load").click();
    await expect(page.getByTestId("desk-fno-spot")).toHaveText("1,502.50");
    await expect.poll(() => asked.some((p) => p.startsWith("/api/fno/FIXFNO/chain"))).toBe(true);
    expect(asked).toContain("/api/fno/FIXFNO/expiries");
    expect(asked).toContain("/api/fno/FIXFNO/futures");
    // the loaded stock sits beside the indices with its company icon
    const chip = page.getByTestId("desk-fno-symbol-fixfno");
    await expect(chip).toHaveAttribute("aria-pressed", "true");
    await expect(chip.locator('[data-testid="entity-icon"][data-kind="stock"]')).toHaveAttribute("data-key", "FIXFNO");
    await expect(page.getByTestId("desk-fno-pcr")).toHaveText("0.94");
    await expect(page.getByTestId("desk-fno-expected-move")).toHaveText("±59.10");
    await expect(page.getByTestId("desk-fno-futures")).toHaveText("1,509.60");
    await expect(page.getByTestId("desk-fno-chain-row")).toHaveCount(5);
    expect(await tagsOf(page, 1500)).toBe("ATM MP");
    expect(await tagsOf(page, 1540)).toBe("R");
    expect(await tagsOf(page, 1460)).toBe("S");

    await page.getByTestId("desk-fno-symbol-input").fill("NOFNO");
    await page.getByTestId("desk-fno-symbol-load").click();
    const none = page.getByTestId("desk-fno-stats-none");
    await expect(none).toContainText("No F&O rows for NOFNO on the latest day");
    await expect(none).toContainText("No F&O data for NOFNO");
    await expect(page.getByTestId("desk-fno-chain-row")).toHaveCount(0);
    expect(asked).toContain("/api/fno/NOFNO/expiries");

    // a malformed ticker is refused before any request
    await page.getByTestId("desk-fno-symbol-input").fill("BAD TICKER!");
    await page.getByTestId("desk-fno-symbol-load").click();
    await expect(page.getByTestId("desk-fno-symbol-error")).toBeVisible();
  });

  test("TC-33 OI build-up: the route's quadrant counts, a sortable table, a quadrant filter, and a row opens that stock's chain", async ({ page }) => {
    const asked = await fnoData(page);
    await page.goto(`${DESK}?tab=fno`);
    await expect(page.getByTestId("desk-fno-pcr")).toHaveText("0.96");
    // Not read until the view is open.
    expect(asked.some((a) => a.startsWith("/api/fno/scan/buildup"))).toBe(false);
    await page.getByTestId("desk-fno-view-buildup").click();
    await expect(page.getByTestId("desk-fno-buildup-not-connected")).toHaveCount(0);

    // The four counts are the route's, and agree with its rows.
    for (const k of ["long_buildup", "short_buildup", "short_covering", "long_unwinding"] as const) {
      expect(BUILDUP.counts[k]).toBe(countBy(k));
      await expect(page.getByTestId(`desk-buildup-count-${k}`)).toHaveText(String(BUILDUP.counts[k]));
    }
    await expect(page.getByTestId("desk-buildup-neutral")).toHaveText(
      `${BUILDUP.counts.neutral} neutral (price or OI unchanged) · ${BUILDUP.counts.no_data} without a label (a change is missing) · ${BUILDUP.universe} F&O stocks scanned`,
    );

    // Default: the route's order (largest |OI chg %| first, missing last).
    const order = () => page.getByTestId("desk-buildup-row").evaluateAll((els) => els.map((e) => e.getAttribute("data-symbol")));
    expect(await order()).toEqual(BUILDUP_ROWS.map((r) => r.symbol));
    const sign = (n: number) => (n > 0 ? "+" : n < 0 ? "−" : "");
    const pctTxt = (v: number | null) => (v == null ? "—" : `${sign(v)}${Math.abs(v).toFixed(2)}%`);
    const META: Record<string, string> = { long_buildup: "Long build-up", short_buildup: "Short build-up", short_covering: "Short covering", long_unwinding: "Long unwinding", neutral: "Neutral" };
    for (const r of BUILDUP_ROWS) {
      const row = page.locator(`[data-testid="desk-buildup-row"][data-symbol="${r.symbol}"]`);
      await expect(row.getByTestId("desk-buildup-symbol")).toHaveText(r.symbol);
      await expect(row.locator('[data-testid="entity-icon"]')).toHaveAttribute("data-key", r.symbol);
      await expect(row.getByTestId("desk-buildup-price")).toHaveText(pctTxt(r.price_chg_pct));
      await expect(row.getByTestId("desk-buildup-oi")).toHaveText(pctTxt(r.oi_chg_pct));
      await expect(row.getByTestId("desk-buildup-label")).toHaveText(r.label ? META[r.label] : "—");
      await expect(row).toContainText(`${r.expiries} ${r.expiries === 1 ? "expiry" : "expiries"}`);
    }
    // FIXFNO's figures agree with its close / previous close and OI.
    const f = BUILDUP_ROWS[0];
    expect(((f.close as number) / (f.prev_close as number) - 1) * 100).toBeCloseTo(f.price_chg_pct as number, 2);
    expect(((f.oi_chg as number) / (f.oi - (f.oi_chg as number))) * 100).toBeCloseTo(f.oi_chg_pct as number, 6);

    // Sort by price change: high to low, then low to high; missing last both ways.
    const byPrice = (dir: 1 | -1) => [...BUILDUP_ROWS].sort((a, b) => {
      if (a.price_chg_pct == null) return 1;
      if (b.price_chg_pct == null) return -1;
      return dir * (a.price_chg_pct - b.price_chg_pct) || a.symbol.localeCompare(b.symbol);
    }).map((r) => r.symbol);
    await page.getByTestId("desk-buildup-sort-price").click();
    expect(await order()).toEqual(byPrice(-1));
    await expect(page.getByRole("columnheader").filter({ has: page.getByTestId("desk-buildup-sort-price") })).toHaveAttribute("aria-sort", "descending");
    await page.getByTestId("desk-buildup-sort-price").click();
    expect(await order()).toEqual(byPrice(1));
    await expect(page.getByRole("columnheader").filter({ has: page.getByTestId("desk-buildup-sort-price") })).toHaveAttribute("aria-sort", "ascending");
    await page.getByTestId("desk-buildup-sort-symbol").click();
    expect(await order()).toEqual(BUILDUP_ROWS.map((r) => r.symbol).sort((a, b) => a.localeCompare(b)));

    // A quadrant filters the table (aria-pressed), and again shows every row.
    await page.getByTestId("desk-buildup-q-long_buildup").click();
    await expect(page.getByTestId("desk-buildup-q-long_buildup")).toHaveAttribute("aria-pressed", "true");
    expect((await order()).sort()).toEqual(BUILDUP_ROWS.filter((r) => r.label === "long_buildup").map((r) => r.symbol).sort());
    await page.getByTestId("desk-buildup-q-long_buildup").click();
    await expect(page.getByTestId("desk-buildup-row")).toHaveCount(BUILDUP_ROWS.length);

    const src = page.getByTestId("desk-buildup-source");
    await expect(src).toContainText(`Source: ${BUILDUP.source}`);
    await expect(src).toContainText("end of day 13 Oct 2026");

    // A row opens that stock's option chain in the lab.
    await page.locator('[data-testid="desk-buildup-row"][data-symbol="FIXFNO"]').click();
    await expect(page.getByTestId("desk-fno-view-chain")).toHaveAttribute("aria-selected", "true");
    await expect(page.getByTestId("desk-fno-symbol-fixfno")).toHaveAttribute("aria-pressed", "true");
    await expect(page.getByTestId("desk-fno-chain-row")).toHaveCount(5);
    await expect(page.getByTestId("desk-fno-spot")).toHaveText("1,502.50");
  });

  test("TC-33 OI build-up: a failed scan shows an error with retry; the keyboard opens a row", async ({ page }) => {
    await fnoData(page);
    // 502 (the route's upstream_unavailable) until Retry is pressed; the client's own retries also see 502.
    let failing = true;
    await page.route("**/api/fno/scan/buildup*", (route) => (failing
      ? route.fulfill({ status: 502, contentType: "application/json", body: JSON.stringify({ detail: "upstream_unavailable" }) })
      : route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(BUILDUP) })));
    await page.goto(`${DESK}?tab=fno`);
    await page.getByTestId("desk-fno-view-buildup").click();
    const err = page.getByTestId("desk-buildup-error");
    await expect(err.getByRole("alert")).toContainText("OI build-up across F&O stocks didn’t load", { timeout: 15_000 });
    failing = false;
    await err.getByRole("button", { name: /Retry/ }).click();
    await expect(page.getByTestId("desk-buildup-row")).toHaveCount(BUILDUP_ROWS.length);
    await page.locator('[data-testid="desk-buildup-row"][data-symbol="FIXFNO"]').focus();
    await page.keyboard.press("Enter");
    await expect(page.getByTestId("desk-fno-symbol-fixfno")).toHaveAttribute("aria-pressed", "true");
  });

  test("TC-33 strategies link to the Options lab and say one-click paper strategies are not connected", async ({ page }) => {
    await fnoData(page);
    await page.goto(`${DESK}?tab=fno`);
    await page.getByTestId("desk-fno-view-strategies").click();
    await expect(page.getByTestId("desk-fno-strategies-not-connected")).toContainText("One-click paper strategies");
    await page.getByTestId("desk-fno-open-optlab").click();
    await expect(page).toHaveURL(/\/v5\/app\/tool\/optlab/);
  });
});

test.describe("Smart trading desk — Portfolio & risk and F&O at 390px", () => {
  test.use({ viewport: { width: 390, height: 844 } });

  test("TC-7 no sideways scroll on the Portfolio & risk tab or the Options & futures lab", async ({ page }) => {
    await deskBase(page);
    await mockPaper(page);
    await mockDeskLists(page);
    await portfolioData(page, { holdings: HOLDINGS, concentration: CONCENTRATION });
    await fnoData(page);

    await page.goto(`${DESK}?tab=portfolio`);
    await expect(page.getByTestId("desk-risk-beta")).toBeVisible();
    await expect(page.getByTestId("desk-portfolio-correlation")).toBeVisible();
    await expect(page.getByTestId("desk-corr-pair")).toHaveCount(CORRELATION.pairs.length);
    await expect(page.getByTestId("desk-mcap-unsplit")).toBeVisible();
    await expect(page.getByTestId("desk-paper-open-table")).toBeVisible();
    await expect(page.getByTestId("desk-alert-row")).toHaveCount(3);
    await expect(page.getByTestId("trader-broker-positions")).toBeVisible();
    // the weight column (where the 25% limit shows) fits on a phone without scrolling the table
    const weightBox = await page.getByTestId("desk-portfolio-weight").first().boundingBox();
    expect(weightBox).not.toBeNull();
    expect((weightBox?.x ?? 0) + (weightBox?.width ?? 0)).toBeLessThanOrEqual(390);
    let o = await sideways(page);
    expect(o.doc).toBeLessThanOrEqual(1);
    expect(o.scroll).toBeLessThanOrEqual(1);

    await page.goto(`${DESK}?tab=fno`);
    await expect(page.getByTestId("desk-fno-chain-row")).toHaveCount(7);
    // the chain scrolls inside its own box, opened on the strike column
    const strikeBox = await chainRow(page, 25000).locator('[data-col="strike"]').boundingBox();
    expect(strikeBox).not.toBeNull();
    expect(strikeBox?.x ?? -1).toBeGreaterThanOrEqual(0);
    expect((strikeBox?.x ?? 0) + (strikeBox?.width ?? 0)).toBeLessThanOrEqual(390);
    o = await sideways(page);
    expect(o.doc).toBeLessThanOrEqual(1);
    expect(o.scroll).toBeLessThanOrEqual(1);

    await page.getByTestId("desk-fno-view-indices").click();
    await expect(page.getByTestId("desk-fno-card-BANKNIFTY-pcr")).toHaveText("0.80");
    o = await sideways(page);
    expect(o.doc).toBeLessThanOrEqual(1);
    expect(o.scroll).toBeLessThanOrEqual(1);

    // OI build-up: the table scrolls inside its own box.
    await page.getByTestId("desk-fno-view-buildup").click();
    await expect(page.getByTestId("desk-buildup-row")).toHaveCount(BUILDUP_ROWS.length);
    o = await sideways(page);
    expect(o.doc).toBeLessThanOrEqual(1);
    expect(o.scroll).toBeLessThanOrEqual(1);
  });
});

