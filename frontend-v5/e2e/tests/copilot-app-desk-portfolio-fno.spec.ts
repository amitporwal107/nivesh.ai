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
 * check, beta and VaR from the payloads; the correlation check as not
 * connected; TC-29 an empty portfolio's connect button; the paper evaluation's
 * 403 note and its forward / replay calibration; TC-30 the NIFTY and BANKNIFTY
 * cards; TC-31 the ATM / R / S / MP tags; TC-32 a stock loaded by ticker and a
 * ticker with no F&O rows; TC-33 OI build-up as not connected; TC-7 no
 * sideways scroll at 390px on both tabs.
 */
import { test, expect, type Page } from "@playwright/test";
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

async function portfolioData(page: Page, opts: { holdings?: unknown; concentration?: unknown; risk?: unknown } = {}) {
  if (opts.holdings) await json(page, "**/api/portfolio/holdings-enriched*", opts.holdings);
  if (opts.concentration) await json(page, "**/api/portfolio/exposure/concentration", opts.concentration);
  await json(page, "**/api/portfolio/risk-analytics*", opts.risk ?? RISK);
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
    await expect(page.getByTestId("desk-portfolio-mcap-note")).toContainText("large-, mid- and small-cap split is not shown");

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

    // correlated positions: no route, so it says so (the needs list shows: the fixture user is an admin)
    const corr = page.getByTestId("desk-portfolio-correlation");
    await expect(corr).toBeVisible();
    await expect(corr).toContainText("Not connected yet");
    await expect(corr).toContainText("Correlated positions");
    await expect(corr.getByTestId("not-connected-needs")).toContainText("pairwise return correlation");

    // right card: the journal summary, and the paper record's 403 as "not enabled"
    await expect(page.getByTestId("desk-journal-open")).toHaveText("1");
    await expect(page.getByTestId("desk-journal-closed")).toHaveText("2");
    await expect(page.getByTestId("desk-journal-win-rate")).toHaveText("50.0%");
    await expect(page.getByTestId("desk-journal-realised")).toHaveText("+₹600");
    await expect(page.getByTestId("desk-paper-no-access")).toContainText("not enabled for this account");
    await expect(page.getByTestId("desk-calibration")).toHaveCount(0);

    // the broker block from the Trader desk is mounted below; this account is not read live, so its stored rows say so
    await expect(page.getByTestId("trader-broker-positions")).toBeVisible();
    await expect(page.getByTestId("trader-broker-account")).toContainText("Zerodha");
    await expect(page.getByTestId("broker-live-status")).toHaveText("Not read live");
    await expect(page.getByTestId("broker-stored-asof")).toHaveText(/^3 holdings · as of last sync 12 Oct, 3:42\s?pm$/i);
  });

  test("TC-28 over the shared fixtures: equity rows only, weights from the route, sector split with the rest folded", async ({ page }) => {
    await mockPaper(page);
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
    await mockSingleRoute(page, "**/api/portfolio/holdings-enriched*", "empty-portfolio.json");
    await portfolioData(page);
    await page.goto(`${DESK}?tab=portfolio`);

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

  test("TC-33 OI build-up is not connected; strategies link to the Options lab and say paper strategies are not connected", async ({ page }) => {
    await fnoData(page);
    await page.goto(`${DESK}?tab=fno`);

    await page.getByTestId("desk-fno-view-buildup").click();
    const buildup = page.getByTestId("desk-fno-buildup-not-connected");
    await expect(buildup).toContainText("Not connected yet");
    await expect(buildup).toContainText("OI build-up across F&O stocks");
    await expect(buildup.getByTestId("not-connected-needs")).toContainText("no previous close");
    await expect(buildup.getByTestId("not-connected-needs")).toContainText("one underlying at a time");

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
    // the broker block with live holdings and positions, so their tables are on the page too
    await json(page, "**/api/broker/accounts", LIVE_ACCOUNTS);
    await json(page, "**/api/broker/holdings*", LIVE_HOLDINGS);
    await json(page, "**/api/broker/positions*", LIVE_POSITIONS);
    await mockPaper(page);
    await portfolioData(page, { holdings: HOLDINGS, concentration: CONCENTRATION });
    await fnoData(page);

    await page.goto(`${DESK}?tab=portfolio`);
    await expect(page.getByTestId("desk-risk-beta")).toBeVisible();
    await expect(page.getByTestId("desk-portfolio-correlation")).toBeVisible();
    await expect(page.getByTestId("trader-broker-positions")).toBeVisible();
    await expect(page.getByTestId("broker-live-row")).toHaveCount(2);
    await expect(page.getByTestId("broker-position-row")).toHaveCount(2);
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
  });
});

