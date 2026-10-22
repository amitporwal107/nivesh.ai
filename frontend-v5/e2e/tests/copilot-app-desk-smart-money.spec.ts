/**
 * One-screen Copilot app (/v5/app) — Smart trading desk: the Smart Money Movement tab (06).
 *
 * MOCK — not real data: every /api/markets/smart-money/* response here is an inline payload in the
 * shape the real route returns (backend/routes/markets_smart_money.py -> DaaS
 * nidp/services/daas_api/routers/smart_money.py). The FIGURES are the real ones queried from the
 * staging warehouse on 2026-10-22 and recorded in test_reports/smart_money_desk_20261022.md, so a
 * drift between the payload shape here and the router's real output fails an assertion rather than
 * silently blanking a panel.
 *
 * Covers screens/tradingdesk/SmartMoneyTab.tsx (+ smart-money-data.ts) against the v2 design
 * (docs/design/SMART_MONEY_MOVEMENT_SCREEN.md §1–§2): the period toggle driving every panel, the
 * five feed strips, the regime line and cumulative chart with its hover and table view, diverging
 * sector bars with the three measures, the three breadth tiers, the scanner's lanes/filters/legend,
 * the stock-evidence rail with its evidence chain and falsification list, and the §2.9 footer.
 *
 * The bulk of this file guards what the screen must NOT say. The validation study returned
 * INCONCLUSIVE and no promotion was approved, so the screen may show evidence and never a verdict:
 * no score, no ranking by one, no hit rate; "not checked" stays distinct from "no deals"; a
 * proxy-only name is never called accumulation; and the MF column states its own window rather
 * than implying it moved with the period chip.
 */
import { test, expect, type Page, type Route } from "@playwright/test";
import { mockApi } from "../helpers/api-mock";

const DESK = "/v5/app/trader/desk";
const SM = `${DESK}?tab=smartmoney`;
const SLOW = { timeout: 15_000 };

/** Real staging figures, 2026-10-22, point-in-time series. */
const BREADTH = {
  as_of: "2026-10-21", disclosure_as_of: "2026-09-01", validated_study: false,
  source: "nidp.smart_money_scores_daily (point_in_time series)",
  disclosure: "Counts of disclosed-holdings evidence.",
  metrics: {
    evaluated: 976, disclosed_rising: 449, disclosed_falling: 424,
    rising_direct_and_proxy: 417, rising_direct_only: 32, proxy_only: 0,
    single_amc: 379, fresh: 963, ageing: 8, stale: 5,
  },
};

const flows = (w: string) => (w === "1Y"
  ? {
    as_of: "2026-10-01", start: "2025-11-01", window: "1Y", grain: "monthly",
    source: "nidp.fii_dii_flows (source=SENSIBULL_MONTHLY)", disclosure: "Market-wide cash flows.",
    fii_net_cr: -503813, dii_net_cr: 849222, points: 2, count: 2, total: 2,
    rows: [
      { date: "2026-09-01", fii_net_cr: -54000, dii_net_cr: 61000, fii_cum_cr: -454918, dii_cum_cr: 796238 },
      { date: "2026-10-01", fii_net_cr: -48895, dii_net_cr: 52984, fii_cum_cr: -503813, dii_cum_cr: 849222 },
    ],
  }
  : {
    as_of: "2026-10-21", start: "2026-07-23", window: w, grain: "daily",
    source: "nidp.fii_dii_flows (source=SENSIBULL)", disclosure: "Market-wide cash flows.",
    fii_net_cr: -101382, dii_net_cr: 201070, points: 3, count: 3, total: 3,
    rows: [
      { date: "2026-10-16", fii_net_cr: 1166, dii_net_cr: -3661, fii_cum_cr: -101256, dii_cum_cr: 196255 },
      { date: "2026-10-19", fii_net_cr: -1149, dii_net_cr: 3201, fii_cum_cr: -102404, dii_cum_cr: 199456 },
      { date: "2026-10-21", fii_net_cr: 1022, dii_net_cr: 1614, fii_cum_cr: -101382, dii_cum_cr: 201070 },
    ],
  });

/** Requested 3 months, served 1 — the only disclosed pair. Drives the mf-window note. */
const MF_WINDOW = { requested_months: 3, actual_months: 1, exact: false };

const SECTORS = {
  as_of: "2026-09-01", previous_month: "2026-08-01", window: "3M", index_name: "Nifty 500",
  mf_window: MF_WINDOW,
  source: "nidp.mf_holdings_deltas x nidp.index_constituents x nidp.prices_eod VWAP",
  disclosure: "Disclosed monthly portfolios of 11 reporting AMCs.", count: 3, total: 3,
  rows: [
    { industry: "Financial Services", stocks: 98, stocks_priced: 98, net_value_cr: 45225, schemes_up: 7000, schemes_dn: 5849 },
    { industry: "Healthcare", stocks: 44, stocks_priced: 44, net_value_cr: 24993, schemes_up: 2878, schemes_dn: 2346 },
    { industry: "Consumer Durables", stocks: 16, stocks_priced: 16, net_value_cr: -1375, schemes_up: 959, schemes_dn: 1068 },
  ],
};

const FEEDS = {
  source: "nidp.v_feed_status, paired with max() of each underlying table",
  disclosure: "`ingested_for` is the loader run; `data_as_of` is the newest data period.",
  count: 3, total: 3,
  rows: [
    { feed: "Shareholding patterns", source_name: "NSE_SHAREHOLDING", table: "nidp.shareholding_pattern",
      status: "OK", expected_freq: "quarterly", staleness_days: 0, staleness_budget_days: 120,
      last_success: "2026-10-22", ingested_for: "2026-10-22", data_as_of: "2026-09-30", status_row_present: true },
    { feed: "AMFI scheme portfolios", source_name: "mf_holdings", table: "nidp.mf_holdings_monthly",
      status: "STALE", expected_freq: "monthly", staleness_days: 9, staleness_budget_days: 4,
      last_success: "2026-10-13", ingested_for: "2026-09-01", data_as_of: "2026-09-01", status_row_present: true },
    { feed: "Financials feed", source_name: "NSE_FINANCIALS", table: "nidp.nse_financials_quarterly",
      status: null, expected_freq: null, staleness_days: null, staleness_budget_days: null,
      last_success: null, ingested_for: null, data_as_of: "2026-09-30", status_row_present: false },
  ],
};

/** Four rows, one per derived evidence class, each also exercising a deal state. */
const ROWS = [
  { symbol: "BSE", industry: "Financial Services", mf_shares_pct_chg: 12.58, net_shares_delta: 13841340,
    schemes_up: 180, schemes_dn: 94, amcs_up: 10, fii_delta_pp: null, dii_delta_pp: null,
    deal_net_qty: -1590764, deal_gross_inr: 38640397021, deal_legs: 4, matched_legs: 0, deal_days: 1,
    transfer_days: 0, deals_checked: true, deliv_10d: 36.6, deliv_60d: 41.3, deliv_vs_base_pp: -4.6,
    close_price: 3248.3, prev_close: 3336.0, change_pct: -2.63, freshness_status: "fresh",
    single_amc_signal: false, latest_reporting_date: "2026-09-01", evidence: "D" },
  { symbol: "TATATECH", industry: "Information Technology", mf_shares_pct_chg: 20.65, net_shares_delta: 4000000,
    schemes_up: 34, schemes_dn: 32, amcs_up: 6, fii_delta_pp: 0.29, dii_delta_pp: 1.06,
    deal_net_qty: null, deal_gross_inr: null, deal_legs: null, matched_legs: null, deal_days: null,
    transfer_days: null, deals_checked: false, deliv_10d: 30.5, deliv_60d: 36.8, deliv_vs_base_pp: -6.3,
    close_price: 690.0, prev_close: 685.0, change_pct: 0.73, freshness_status: "ageing",
    single_amc_signal: true, latest_reporting_date: "2026-09-01", evidence: "A" },
  { symbol: "ULTRACEMCO", industry: "Construction Materials", mf_shares_pct_chg: 0.17, net_shares_delta: 108375,
    schemes_up: 135, schemes_dn: 158, amcs_up: 9, fii_delta_pp: 0.33, dii_delta_pp: 1.17,
    deal_net_qty: 0, deal_gross_inr: null, deal_legs: 31, matched_legs: 30, deal_days: 1,
    transfer_days: 1, deals_checked: true, deliv_10d: 51.7, deliv_60d: 58.1, deliv_vs_base_pp: -6.4,
    close_price: 10849.0, prev_close: 10650.0, change_pct: 1.87, freshness_status: "fresh",
    single_amc_signal: false, latest_reporting_date: "2026-09-01", evidence: "A" },
  { symbol: "ARVINDFASN", industry: "Consumer Durables", mf_shares_pct_chg: null, net_shares_delta: null,
    schemes_up: null, schemes_dn: null, amcs_up: null, fii_delta_pp: null, dii_delta_pp: null,
    deal_net_qty: null, deal_gross_inr: null, deal_legs: null, matched_legs: null, deal_days: null,
    transfer_days: null, deals_checked: true, deliv_10d: 61.2, deliv_60d: 44.0, deliv_vs_base_pp: 17.2,
    close_price: 410.5, prev_close: 404.0, change_pct: 1.61, freshness_status: "stale",
    single_amc_signal: false, latest_reporting_date: "2026-09-01", evidence: "C" },
];

const scanner = (lane: string) => {
  const rows = lane === "proxy" ? ROWS.filter((r) => r.evidence === "C")
    : lane === "disclosed" ? ROWS.filter((r) => r.evidence !== "C") : ROWS;
  return {
    as_of: "2026-09-01", previous_month: "2026-08-01", window: "3M", index_name: "Nifty 500",
    mf_window: MF_WINDOW,
    quarters: { current: "2026-09-30", previous: "2026-06-30", requested_back: 1, actual_back: 1, exact: true },
    deal_window: { from: "2026-07-23", to: "2026-10-21", days: 90 },
    source: "nidp.mf_holdings_deltas, nidp.v_trendlyne_deals_net, nidp.prices_eod",
    disclosure: "Evidence, not a verdict.",
    count: rows.length, total: rows.length, matched: ROWS.length,
    lanes: { all: 4, disclosed: 3, proxy: 1 },
    classes: { A: 2, B: 0, C: 1, D: 1 },
    rows,
  };
};

const json = (body: unknown) => ({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
const bad = { status: 502, contentType: "application/json", body: JSON.stringify({ error: { status: 502, message: "upstream_unavailable" } }) };

async function mockSmartMoney(page: Page, over: { fail?: string[] } = {}) {
  const fail = new Set(over.fail ?? []);
  const serve = (r: Route, key: string, body: unknown) => (fail.has(key) ? r.fulfill(bad) : r.fulfill(json(body)));
  await page.route("**/api/markets/smart-money/feeds*", (r) => serve(r, "feeds", FEEDS));
  await page.route("**/api/markets/smart-money/flows*", (r) =>
    serve(r, "flows", flows(new URL(r.request().url()).searchParams.get("window") ?? "3M")));
  await page.route("**/api/markets/smart-money/sectors*", (r) => serve(r, "sectors", SECTORS));
  await page.route("**/api/markets/smart-money/breadth*", (r) => serve(r, "breadth", BREADTH));
  await page.route("**/api/markets/smart-money/scanner*", (r) =>
    serve(r, "scanner", scanner(new URL(r.request().url()).searchParams.get("lane") ?? "all")));
}

const screen = (page: Page) => page.getByTestId("screen-desk-smart-money");
const row = (page: Page, sym: string) => page.getByRole("row").filter({ hasText: sym });

test.describe("Smart trading desk · 06 Smart Money Movement", () => {
  test.beforeEach(async ({ page }) => {
    await mockApi(page, "populated");
    await mockSmartMoney(page);
  });

  test("TC-F1: it is the sixth primary tab and pushes More to 07", async ({ page }) => {
    await page.goto(DESK);
    const tabs = page.getByRole("tablist", { name: "Desk modules" }).getByRole("tab");
    await expect(tabs).toHaveCount(7);
    await expect(tabs.nth(5)).toHaveAttribute("data-testid", "desk-tab-smartmoney");
    await expect(tabs.nth(5)).toHaveText("06Smart Money");
    await expect(tabs.nth(6)).toHaveText("07More");
  });

  test("TC-F2: the five design panels are all present, and nothing is scored", async ({ page }) => {
    await page.goto(SM);
    await expect(screen(page)).toBeVisible(SLOW);
    await expect(page.getByTestId("screen-trading-desk")).toHaveAttribute("data-tab", "smartmoney");
    for (const id of ["desk-smart-money-feed-strips", "desk-smart-money-chart", "desk-smart-money-sector-bars",
                      "desk-smart-money-legend", "desk-smart-money-rail", "desk-smart-money-disclaimer"]) {
      await expect(page.getByTestId(id)).toBeVisible();
    }
    await expect(screen(page)).toContainText("Evidence only · not scored");
    await expect(screen(page)).toContainText("11 disclosing AMCs");
  });

  test("TC-F3: the disclosure date is shown, not the compute date", async ({ page }) => {
    await page.goto(SM);
    await expect(screen(page)).toBeVisible(SLOW);
    // 2026-09-01 is the disclosure; 2026-10-21 is when the score was computed.
    await expect(screen(page)).toContainText(/Disclosed\s+0?1 Sept? 2026\s+·\s+51d ago/);
  });

  test("TC-F4: the period chip moves flows to monthly, and says the MF leg could not follow", async ({ page }) => {
    await page.goto(SM);
    await expect(screen(page)).toBeVisible(SLOW);
    // The warehouse holds only a one-month pair, so the note must be explicit rather than silent.
    await expect(page.getByTestId("desk-smart-money-mf-window"))
      .toContainText("Holdings change is over 1 month — a 3-month disclosure pair is not published.");
    await expect(screen(page)).toContainText("Daily grain, cash segment only.");

    await page.getByTestId("desk-smart-money-period-1Y").click();
    await expect(screen(page)).toContainText("Monthly grain");
    await expect(screen(page)).toContainText("The two grains are never added together.");
  });

  test("TC-F5: the flows panel is market-wide, with a rules-based regime line and rolling sums", async ({ page }) => {
    await page.goto(SM);
    await expect(screen(page)).toBeVisible(SLOW);
    await expect(screen(page)).toContainText("Market-wide · not stock-specific");
    // FII -101382 and DII +201070 -> domestic absorbed the foreign selling.
    await expect(page.getByTestId("desk-smart-money-regime"))
      .toContainText("Domestic institutions absorbed the foreign selling over this window.");
    await expect(screen(page)).toContainText("regime line is rules-based, not a model");
    // Only 3 points are mocked, so 5D/20D/60D cannot be computed and must read "—", never 0.
    await expect(screen(page)).toContainText("5D — · 20D — · 60D —");
  });

  test("TC-F6: the chart has a legend, a hover readout and a table view", async ({ page }) => {
    await page.goto(SM);
    await expect(screen(page)).toBeVisible(SLOW);
    // Two series => a legend is always present, so identity never rests on colour alone.
    await expect(screen(page)).toContainText("FII cumulative");
    await expect(screen(page)).toContainText("DII cumulative");
    const chart = page.getByTestId("desk-smart-money-chart");
    await expect(chart).toHaveAttribute("aria-label", /Cumulative FII and DII/);
    await chart.hover({ position: { x: 600, y: 90 } });
    await expect(page.getByTestId("desk-smart-money-chart-hover")).toContainText("2026-10-");
    await page.getByText("Show as a table").click();
    await expect(screen(page)).toContainText("FII cum.");
  });

  test("TC-F7: the sector bars switch measure and diverge around zero", async ({ page }) => {
    await page.goto(SM);
    await expect(screen(page)).toBeVisible(SLOW);
    const bars = page.getByTestId("desk-smart-money-sector-bars");
    await expect(bars).toContainText("Financial Services");
    await expect(bars).toContainText("45,225");             // ₹ Cr, Indian grouping
    await expect(bars).toContainText("1,375");              // a negative sector, drawn left of zero
    await page.getByTestId("desk-smart-money-measure-pct").click();
    await expect(bars).toContainText("63.2");               // 45225 / 71593 gross
    await page.getByTestId("desk-smart-money-measure-stocks").click();
    await expect(bars).toContainText("98");
    await expect(screen(page)).toContainText("158 of 158 covered");
  });

  test("TC-F8: the breadth tiers are the three the spec names", async ({ page }) => {
    await page.goto(SM);
    await expect(screen(page)).toBeVisible(SLOW);
    await expect(screen(page)).toContainText("Direct + proxy agree");
    await expect(screen(page)).toContainText("Direct evidence only");
    await expect(screen(page)).toContainText("Proxy only, not confirmed");
    await expect(screen(page)).toContainText("449");
    await expect(screen(page)).toContainText("of 976 evaluated names");
    await expect(screen(page)).toContainText("fresh 963");
  });

  test("TC-F9: each deal state reads differently — checked, never asked, pure transfer", async ({ page }) => {
    await page.goto(SM);
    await expect(screen(page)).toBeVisible(SLOW);
    await expect(row(page, "TATATECH")).toContainText("Not checked");
    await expect(row(page, "ULTRACEMCO")).toContainText("Net 0 · transfer");
    await expect(row(page, "ARVINDFASN")).toContainText("No deals");
    // A surviving leg shows its size and how many legs were removed as transfers.
    const bse = ((await row(page, "BSE").textContent()) ?? "").replace(/,/g, "");
    expect(bse).toContain("1590764");
    await expect(row(page, "BSE")).toContainText("4 legs · 0 matched");
  });

  test("TC-F10: the lanes carry real counts and an empty lane explains itself", async ({ page }) => {
    await page.goto(SM);
    await expect(screen(page)).toBeVisible(SLOW);
    await expect(page.getByTestId("desk-smart-money-lane-all")).toContainText("All (4)");
    await expect(page.getByTestId("desk-smart-money-lane-disclosed")).toContainText("Disclosed evidence · A/B (3)");
    await expect(page.getByTestId("desk-smart-money-lane-proxy")).toContainText("Proxy only · C (1)");
    await page.getByTestId("desk-smart-money-lane-proxy").click();
    await expect(row(page, "ARVINDFASN")).toBeVisible();
    await expect(page.getByTestId("desk-smart-money-coverage")).toContainText("4 match the other filters");
  });

  test("TC-F11: filters apply and Clear filters appears only once something is set", async ({ page }) => {
    await page.goto(SM);
    await expect(screen(page)).toBeVisible(SLOW);
    await expect(page.getByTestId("desk-smart-money-clear")).toHaveCount(0);
    await page.getByTestId("desk-smart-money-direction-accumulation").click();
    await expect(page.getByTestId("desk-smart-money-clear")).toBeVisible();
    await page.getByTestId("desk-smart-money-sector").selectOption("Healthcare");
    await page.getByTestId("desk-smart-money-clear").click();
    await expect(page.getByTestId("desk-smart-money-clear")).toHaveCount(0);
    await expect(page.getByTestId("desk-smart-money-direction-all")).toHaveAttribute("aria-selected", "true");
  });

  test("TC-F12: the A/B/C/D legend ships verbatim", async ({ page }) => {
    await page.goto(SM);
    await expect(screen(page)).toBeVisible(SLOW);
    const legend = page.getByTestId("desk-smart-money-legend");
    await expect(legend).toContainText("disclosed holdings change");
    await expect(legend).toContainText("disclosed deal, net of transfers");
    await expect(legend).toContainText("market proxy, buyer unknown");
    await expect(legend).toContainText("direct and proxy align");
  });

  test("TC-F13: the rail starts empty, then shows the chosen stock's evidence chain", async ({ page }) => {
    await page.goto(SM);
    await expect(screen(page)).toBeVisible(SLOW);
    await expect(page.getByTestId("desk-smart-money-evidence-empty")).toContainText("Select a stock in the scanner");
    await row(page, "BSE").click();
    const panel = page.getByTestId("desk-smart-money-evidence");
    await expect(panel).toContainText("BSE");
    await expect(panel).toContainText("Why it surfaced · evidence chain");
    await expect(panel).toContainText("10 AMCs raised the holding across 180 schemes (+12.58%)");
    await expect(panel).toContainText("Disclosed monthly portfolios, as of 2026-09-01");
    await expect(panel).toContainText("What would weaken this reading");
    await expect(panel).toContainText("no counterparty classification");
    await expect(panel).toContainText("Accumulation");
  });

  test("TC-F14: a proxy-only stock is banner-warned and never called accumulation", async ({ page }) => {
    await page.goto(SM);
    await expect(screen(page)).toBeVisible(SLOW);
    await row(page, "ARVINDFASN").click();
    const panel = page.getByTestId("desk-smart-money-evidence");
    await expect(page.getByTestId("desk-smart-money-proxy-banner"))
      .toContainText("Market-proxy evidence only. This is not labelled institutional accumulation.");
    await expect(panel).toContainText("Proxy signal");
    await expect(panel).toContainText("delivery and volume do not identify a buyer");
    await expect(panel).not.toContainText("Accumulation");
  });

  test("TC-F15: a single-AMC row says so, in the table and in the falsification list", async ({ page }) => {
    await page.goto(SM);
    await expect(screen(page)).toBeVisible(SLOW);
    await expect(row(page, "TATATECH")).toContainText("1 AMC");
    await row(page, "TATATECH").click();
    const panel = page.getByTestId("desk-smart-money-evidence");
    await expect(panel).toContainText("One AMC only");
    await expect(panel).toContainText("rests on a single fund house");
    await expect(panel).toContainText("never queried for bulk or block deals");
    await expect(panel).toContainText("disclosure is ageing");
  });

  test("TC-F16: the feed strips separate the data date from the loader run", async ({ page }) => {
    await page.goto(SM);
    await expect(screen(page)).toBeVisible(SLOW);
    const strips = page.getByTestId("desk-smart-money-feed-strips");
    await expect(strips).toContainText(/Shareholding patterns/);
    await expect(strips).toContainText(/30 Sept? 2026/);        // data as of
    await expect(strips).toContainText(/loader ran\s+22 Oct 2026/);
    // A feed with no status row still gets a strip, flagged, rather than disappearing.
    await expect(strips).toContainText("Financials feed");
    await expect(strips).toContainText("no status row");
  });

  test("TC-F17: the footer refuses a hit rate and carries the §2.9 wording", async ({ page }) => {
    await page.goto(SM);
    await expect(screen(page)).toBeVisible(SLOW);
    await expect(screen(page)).toContainText("Historical market reaction: no validated study available.");
    const foot = page.getByTestId("desk-smart-money-disclaimer");
    await expect(foot).toContainText("Smart money is evidence, not a buy signal.");
    await expect(foot).toContainText("deal disclosures may not identify beneficial intent");
    await expect(foot).toContainText("Educational market intelligence, not investment advice");
  });

  test("TC-F18: one dead source leaves the rest standing; all of them is an error", async ({ page }) => {
    await mockSmartMoney(page, { fail: ["sectors"] });
    await page.goto(SM);
    await expect(screen(page)).toBeVisible(SLOW);
    await expect(page.getByTestId("desk-smart-money-partial")).toContainText("sectors");
    await expect(screen(page)).toContainText("976");
    await expect(page.getByTestId("desk-smart-money-chart")).toBeVisible();

    await mockSmartMoney(page, { fail: ["feeds", "flows", "sectors", "breadth", "scanner"] });
    await page.goto(SM);
    await expect(screen(page)).toContainText("Smart Money didn’t load", SLOW);
  });

  test("TC-F19: the rail stacks inside the desk, because the desk never gives it 1240px", async ({ page }) => {
    // The design wants 860px main + 380px rail. The desk shell caps this tab's column at 888px at
    // a 1600px viewport and 1076px at 2200px, both with the Copilot docked — so the split never
    // engages here and the panel sits under the scanner instead of squeezing it sideways.
    for (const w of [1600, 2200]) {
      await page.setViewportSize({ width: w, height: 1100 });
      await page.goto(SM);
      await expect(screen(page)).toBeVisible(SLOW);
      const col = await screen(page).evaluate((el) => Math.round(el.getBoundingClientRect().width));
      expect(col, `tab column at ${w}px`).toBeLessThan(1240);
      const rail = (await page.getByTestId("desk-smart-money-rail").boundingBox())!;
      const strips = (await page.getByTestId("desk-smart-money-feed-strips").boundingBox())!;
      // Stacked: the rail starts below the main column, not to the right of it.
      expect(rail.y, `rail below strips at ${w}px`).toBeGreaterThan(strips.y);
      expect(Math.abs(rail.x - strips.x), `rail aligned with main at ${w}px`).toBeLessThan(24);
      // It is still fully usable, not merely present.
      await row(page, "BSE").first().click();
      await expect(page.getByTestId("desk-smart-money-evidence")).toContainText("Why it surfaced");
    }
  });

  test("TC-F20: on a phone it is in the bottom bar as Flows, and the rail stacks", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto(SM);
    await expect(screen(page)).toBeVisible(SLOW);
    const bar = page.getByRole("navigation", { name: "Desk sections" });
    await expect(bar.getByRole("button")).toHaveCount(7);
    const btn = page.getByTestId("desk-bottom-smartmoney");
    await expect(btn).toHaveText("Flows");
    await expect(btn).toHaveAttribute("aria-label", /Smart Money Movement/);
    await expect(btn).toHaveAttribute("aria-current", "page");
    // The rail is still reachable, just below the scanner.
    await expect(page.getByTestId("desk-smart-money-rail")).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true);
  });

  test("TC-F21: no score, rank or hit rate reaches the DOM", async ({ page }) => {
    await page.goto(SM);
    await expect(screen(page)).toBeVisible(SLOW);
    const text = ((await screen(page).textContent()) ?? "").toLowerCase();
    for (const banned of ["accumulation score", "shadow score", "hit rate", "win rate", "success rate", "probability", "nifty 1000"]) {
      expect(text, `"${banned}" must not appear`).not.toContain(banned);
    }
  });

});
