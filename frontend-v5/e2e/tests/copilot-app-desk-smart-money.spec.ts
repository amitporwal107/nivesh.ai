/**
 * One-screen Copilot app (/v5/app) — Smart trading desk: the Smart Money Movement tab (06).
 *
 * MOCK — not real data: every /api/markets/smart-money/* response here is an inline payload in the
 * shape the real route returns (backend/routes/markets_smart_money.py -> DaaS
 * nidp/services/daas_api/routers/smart_money.py). The FIGURES, however, are the real ones queried
 * from the staging warehouse on 2026-10-22 and recorded in
 * test_reports/smart_money_desk_20261022.md — so a drift between the payload shape here and the
 * router's real output shows up as a failing assertion rather than a silently blank panel.
 *
 * Covers screens/tradingdesk/SmartMoneyTab.tsx (+ smart-money-data.ts): the tab's place in the row
 * as 06 with More pushed to 07, the flows window switching grain, the derived evidence classes, the
 * three distinct deal states, the disclosure date shown apart from the compute date, the feed strip
 * separating the data date from the loader run, partial and total failure, and the phone bar.
 *
 * The bulk of this file guards what the screen must NOT say. The smart-money validation study
 * returned INCONCLUSIVE and no promotion was ever approved, so the screen may show evidence and
 * never a verdict: no score, no ranking by one, no hit rate, and "not checked" must stay visibly
 * different from "no deals". Those are asserted directly, because each would read as plausible.
 */
import { test, expect, type Page } from "@playwright/test";
import { mockApi } from "../helpers/api-mock";

const DESK = "/v5/app/trader/desk";
const SM = `${DESK}?tab=smartmoney`;

/** Real staging figures, 2026-10-22 (point-in-time series). */
const BREADTH = {
  as_of: "2026-10-21",
  disclosure_as_of: "2026-09-01",
  validated_study: false,
  source: "nidp.smart_money_scores_daily (point_in_time series)",
  disclosure: "Counts of disclosed-holdings evidence.",
  metrics: {
    evaluated: 976, disclosed_rising: 449, disclosed_falling: 424,
    rising_direct_and_proxy: 417, rising_direct_only: 32, proxy_only: 0,
    single_amc: 379, fresh: 963, ageing: 8, stale: 5,
  },
};

const FLOWS_3M = {
  as_of: "2026-10-21", start: "2026-07-23", window: "3M", grain: "daily",
  source: "nidp.fii_dii_flows (source=SENSIBULL)", disclosure: "Market-wide cash-segment flows.",
  fii_net_cr: -101382, dii_net_cr: 201070, points: 62, count: 62, total: 62,
  rows: [{ date: "2026-10-21", fii_net_cr: 1022, dii_net_cr: 1614, fii_cum_cr: -101382, dii_cum_cr: 201070 }],
};

const FLOWS_1Y = {
  as_of: "2026-10-01", start: "2025-11-01", window: "1Y", grain: "monthly",
  source: "nidp.fii_dii_flows (source=SENSIBULL_MONTHLY)", disclosure: "Market-wide cash-segment flows.",
  fii_net_cr: -503813, dii_net_cr: 849222, points: 12, count: 12, total: 12,
  rows: [{ date: "2026-10-01", fii_net_cr: -48895, dii_net_cr: 52984, fii_cum_cr: -503813, dii_cum_cr: 849222 }],
};

const SECTORS = {
  as_of: "2026-09-01", previous_month: "2026-08-01",
  source: "nidp.mf_holdings_deltas x nidp.index_constituents (Nifty 500) x nidp.prices_eod VWAP",
  disclosure: "Disclosed monthly portfolios of 11 reporting AMCs.", count: 2, total: 2,
  rows: [
    { industry: "Financial Services", stocks: 98, stocks_priced: 98, net_value_cr: 45225, schemes_up: 7000, schemes_dn: 5849 },
    { industry: "Healthcare", stocks: 44, stocks_priced: 44, net_value_cr: 24993, schemes_up: 2878, schemes_dn: 2346 },
  ],
};

const FEEDS = {
  source: "nidp.v_feed_status, paired with max() of each underlying table",
  disclosure: "`ingested_for` is when the loader last ran; `data_as_of` is the newest data period.",
  count: 2, total: 2,
  rows: [
    { feed: "Shareholding patterns", source_name: "NSE_SHAREHOLDING", table: "nidp.shareholding_pattern",
      status: "OK", expected_freq: "quarterly", staleness_days: 0, staleness_budget_days: 120,
      last_success: "2026-10-22", ingested_for: "2026-10-22", data_as_of: "2026-09-30", status_row_present: true },
    { feed: "AMFI scheme portfolios", source_name: "mf_holdings", table: "nidp.mf_holdings_monthly",
      status: "STALE", expected_freq: "daily", staleness_days: 9, staleness_budget_days: 4,
      last_success: "2026-10-13", ingested_for: "2026-09-01", data_as_of: "2026-09-01", status_row_present: true },
  ],
};

/** Four rows chosen to exercise each derived evidence class and each deal state. */
const SCANNER = {
  as_of: "2026-09-01", previous_month: "2026-08-01",
  quarters: { current: "2026-09-30", previous: "2026-06-30" },
  deal_window: { from: "2026-07-23", to: "2026-10-21" },
  source: "nidp.mf_holdings_deltas, nidp.v_trendlyne_deals_net, nidp.prices_eod",
  disclosure: "Evidence, not a verdict.", count: 4, total: 4,
  rows: [
    // disclosed + a surviving deal leg -> class D
    { symbol: "GROWW", industry: "Financial Services", mf_shares_pct_chg: 8.6, net_shares_delta: 9e6,
      schemes_up: 82, schemes_dn: 16, amcs_up: 7, fii_delta_pp: 4.01, dii_delta_pp: 2.65,
      deal_net_qty: -279513109, deal_gross_inr: null, deal_days: 2, transfer_days: 0, deals_checked: true,
      deliv_10d: 48.9, deliv_60d: 52.3, deliv_vs_base_pp: -3.4 },
    // disclosed only, never queried for deals -> class A + "Not checked"
    { symbol: "TATATECH", industry: "Information Technology", mf_shares_pct_chg: 20.65, net_shares_delta: 4e6,
      schemes_up: 34, schemes_dn: 32, amcs_up: 6, fii_delta_pp: null, dii_delta_pp: null,
      deal_net_qty: null, deal_gross_inr: null, deal_days: null, transfer_days: null, deals_checked: false,
      deliv_10d: 30.5, deliv_60d: 36.8, deliv_vs_base_pp: -6.3 },
    // every leg paired off -> "Net 0 · transfer"
    { symbol: "DMART", industry: "Consumer Services", mf_shares_pct_chg: 2.89, net_shares_delta: 1e6,
      schemes_up: 135, schemes_dn: 86, amcs_up: 9, fii_delta_pp: -0.73, dii_delta_pp: 0.76,
      deal_net_qty: 0, deal_gross_inr: null, deal_days: 3, transfer_days: 3, deals_checked: true,
      deliv_10d: 47.8, deliv_60d: 53.7, deliv_vs_base_pp: -5.9 },
    // proxy only, buyer unknown -> class C, and it must not be called accumulation
    { symbol: "PROXYONLY", industry: "Power", mf_shares_pct_chg: null, net_shares_delta: null,
      schemes_up: null, schemes_dn: null, amcs_up: null, fii_delta_pp: null, dii_delta_pp: null,
      deal_net_qty: null, deal_gross_inr: null, deal_days: null, transfer_days: null, deals_checked: true,
      deliv_10d: 61.2, deliv_60d: 44.0, deliv_vs_base_pp: 17.2 },
  ],
};

const json = (body: unknown) => ({ status: 200, contentType: "application/json", body: JSON.stringify(body) });

async function mockSmartMoney(page: Page, over: { fail?: string[] } = {}) {
  const fail = new Set(over.fail ?? []);
  const serve = async (route: import("@playwright/test").Route, key: string, body: unknown) => {
    if (fail.has(key)) return route.fulfill({ status: 502, contentType: "application/json", body: JSON.stringify({ error: { status: 502, message: "upstream_unavailable" } }) });
    return route.fulfill(json(body));
  };
  await page.route("**/api/markets/smart-money/feeds*", (r) => serve(r, "feeds", FEEDS));
  await page.route("**/api/markets/smart-money/flows*", (r) => {
    const w = new URL(r.request().url()).searchParams.get("window");
    return serve(r, "flows", w === "1Y" ? FLOWS_1Y : FLOWS_3M);
  });
  await page.route("**/api/markets/smart-money/sectors*", (r) => serve(r, "sectors", SECTORS));
  await page.route("**/api/markets/smart-money/breadth*", (r) => serve(r, "breadth", BREADTH));
  await page.route("**/api/markets/smart-money/scanner*", (r) => serve(r, "scanner", SCANNER));
}

const screen = (page: Page) => page.getByTestId("screen-desk-smart-money");

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
    // More is an overflow chip and must stay last, renumbered rather than left at 06.
    await expect(tabs.nth(6)).toHaveText("07More");
  });

  test("TC-F2: the tab opens and says plainly that nothing here is scored", async ({ page }) => {
    await page.goto(SM);
    await expect(screen(page)).toBeVisible({ timeout: 15_000 });
    await expect(page.getByTestId("screen-trading-desk")).toHaveAttribute("data-tab", "smartmoney");
    await expect(screen(page)).toContainText("Evidence only · not scored");
    await expect(screen(page)).toContainText("11 disclosing AMCs");
  });

  test("TC-F3: the disclosure date is shown, not the compute date", async ({ page }) => {
    await page.goto(SM);
    await expect(screen(page)).toBeVisible({ timeout: 15_000 });
    // 2026-09-01 is the disclosure; 2026-10-21 is when the score was computed. The pill must carry
    // the first, with its age, so the screen cannot read as 51 days fresher than it is.
    await expect(screen(page)).toContainText(/Disclosed\s+0?1 Sept? 2026\s+·\s+51d ago/);
  });

  test("TC-F4: the flows panel is market-wide and 1Y switches to monthly grain", async ({ page }) => {
    await page.goto(SM);
    await expect(screen(page)).toBeVisible({ timeout: 15_000 });
    await expect(screen(page)).toContainText("Market-wide · not stock-specific");
    await expect(screen(page)).toContainText("Daily grain, cash segment only.");
    await expect(screen(page)).toContainText("Sessions");

    await page.getByTestId("desk-smart-money-window-1Y").click();
    await expect(screen(page)).toContainText("Monthly grain");
    await expect(screen(page)).toContainText("The two grains are never added together.");
    await expect(screen(page)).toContainText("Months");
  });

  test("TC-F5: the breadth tiles come from the point-in-time counts", async ({ page }) => {
    await page.goto(SM);
    await expect(screen(page)).toBeVisible({ timeout: 15_000 });
    for (const t of ["976", "449", "424", "417", "379"]) {
      await expect(screen(page)).toContainText(t);
    }
    await expect(screen(page)).toContainText("One AMC only");
  });

  test("TC-F6: each deal state reads differently — checked, never asked, and a pure transfer", async ({ page }) => {
    await page.goto(SM);
    await expect(screen(page)).toBeVisible({ timeout: 15_000 });
    const row = (sym: string) => page.getByRole("row").filter({ hasText: sym });
    // Never queried: must not read as an absence of activity.
    await expect(row("TATATECH")).toContainText("Not checked");
    // Every leg paired off: an ownership transfer, not demand.
    await expect(row("DMART")).toContainText("Net 0 · transfer");
    // A real surviving leg shows a number. Digits are grouped in the Indian system
    // (27,95,13,109), so compare with the separators stripped rather than pinning a locale.
    const groww = ((await row("GROWW").textContent()) ?? "").replace(/,/g, "");
    expect(groww).toContain("279513109");
  });

  test("TC-F7: the evidence class is derived per row, and a proxy is never called accumulation", async ({ page }) => {
    await page.goto(SM);
    await expect(screen(page)).toBeVisible({ timeout: 15_000 });
    const row = (sym: string) => page.getByRole("row").filter({ hasText: sym });
    await expect(row("GROWW")).toContainText("Disclosed + deal");
    await expect(row("TATATECH")).toContainText("Disclosed holdings");
    await expect(row("PROXYONLY")).toContainText("Market proxy only");
    await expect(row("PROXYONLY")).not.toContainText("Accumulation");
  });

  test("TC-F8: the feed strip keeps the data date apart from the loader run", async ({ page }) => {
    await page.goto(SM);
    await expect(screen(page)).toBeVisible({ timeout: 15_000 });
    const shp = page.getByRole("row").filter({ hasText: "Shareholding patterns" });
    await expect(shp).toContainText(/30 Sept? 2026/);  // data as of
    await expect(shp).toContainText("22 Oct 2026");   // loader ran
    await expect(screen(page)).toContainText("“Data as of” is the newest period in the table");
    await expect(page.getByRole("row").filter({ hasText: "AMFI scheme portfolios" })).toContainText("STALE");
  });

  test("TC-F9: the footer refuses a hit rate and carries the advice disclaimer", async ({ page }) => {
    await page.goto(SM);
    await expect(screen(page)).toBeVisible({ timeout: 15_000 });
    const foot = page.getByTestId("desk-smart-money-disclaimer");
    await expect(foot).toContainText("Historical market reaction: no validated study available.");
    await expect(foot).toContainText("Smart money is evidence, not a buy signal");
    await expect(foot).toContainText("Educational market intelligence, not investment advice");
  });

  test("TC-F10: one dead source leaves the rest of the screen standing", async ({ page }) => {
    await page.unroute("**/api/markets/smart-money/sectors*");
    await mockSmartMoney(page, { fail: ["sectors"] });
    await page.goto(SM);
    await expect(screen(page)).toBeVisible({ timeout: 15_000 });
    await expect(page.getByTestId("desk-smart-money-partial")).toContainText("sectors");
    // The live panels are still there: partial is not an error.
    await expect(screen(page)).toContainText("976");
    await expect(screen(page)).toContainText("Market-wide · not stock-specific");
  });

  test("TC-F11: every source failing is an error, not a silently empty screen", async ({ page }) => {
    await mockSmartMoney(page, { fail: ["feeds", "flows", "sectors", "breadth", "scanner"] });
    await page.goto(SM);
    await expect(screen(page)).toContainText("Smart Money didn’t load", { timeout: 15_000 });
  });

  test("TC-F12: on a phone it is in the bottom bar as Flows", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto(SM);
    await expect(screen(page)).toBeVisible({ timeout: 15_000 });
    const bar = page.getByRole("navigation", { name: "Desk sections" });
    await expect(bar.getByRole("button")).toHaveCount(7);
    const btn = page.getByTestId("desk-bottom-smartmoney");
    await expect(btn).toHaveText("Flows");
    await expect(btn).toHaveAttribute("aria-label", /Smart Money Movement/);
    await expect(btn).toHaveAttribute("aria-current", "page");
  });

  test("TC-F13: no score, rank or hit rate reaches the DOM", async ({ page }) => {
    await page.goto(SM);
    await expect(screen(page)).toBeVisible({ timeout: 15_000 });
    const text = ((await screen(page).textContent()) ?? "").toLowerCase();
    for (const banned of ["accumulation score", "shadow score", "hit rate", "win rate", "success rate", "probability"]) {
      expect(text, `"${banned}" must not appear`).not.toContain(banned);
    }
  });
});
