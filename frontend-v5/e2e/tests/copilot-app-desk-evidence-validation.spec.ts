/**
 * One-screen Copilot app (/v5/app) — Smart trading desk: the Evidence & Validation panel.
 *
 * MOCK — not real data in the sense that these are inline route fulfilments rather than a live
 * backend; but every FIGURE here is the REAL, already-run study result, copied verbatim from
 * test_reports/SHP_POST_DISCLOSURE_FORWARD_STUDY_20261023.md (branch
 * study/post-disclosure-forward-returns @ 62443b98, NIDP-SHP-FWD-001). So a drift between the
 * payload shape here and the router's real output (nidp/services/daas_api/routers/
 * evidence_validation.py) fails an assertion rather than silently blanking or misstating the panel.
 *
 * This file's job is to assert the DISPLAYED NUMBERS, not that the endpoint returned 200:
 *
 *   * INCONCLUSIVE renders as the loud, primary state of the panel, not a footnote.
 *   * The mean spread at the primary horizon is shown WITH its 95% CI, block count and
 *     positive-quarter count — never the point estimate alone.
 *   * The cost-adjusted figure (net of ~0.9874pp of estimated costs) is shown explicitly.
 *   * "2026-09-30: not yet eligible for forward-return evaluation" renders as its own field, never
 *     as a zero and never folded into the horizon rows.
 *   * No Nifty 500 TRI row and no benchmark figure appears anywhere on the panel.
 *   * Nothing on the panel reads as a score, a rank or a buy/sell signal.
 */
import { test, expect, type Page, type Route } from "@playwright/test";
import { mockApi } from "../helpers/api-mock";

const DESK = "/v5/app/trader/desk";
const SM = `${DESK}?tab=smartmoney`;
const SLOW = { timeout: 15_000 };

const json = (body: unknown) => ({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
const bad = { status: 502, contentType: "application/json", body: JSON.stringify({ error: { status: 502, message: "upstream_unavailable" } }) };

/** Minimal-but-valid smart-money payloads: the host tab needs its neighbours to answer so it
 *  renders at all. Deliberately empty/minimal, which also proves this panel does not depend on
 *  them. */
async function mockHostTab(page: Page) {
  const empty = { as_of: "2026-09-30", source: "x", disclosure: "x", count: 0, total: 0, rows: [] };
  for (const p of ["feeds", "flows", "sectors", "scanner", "amc"]) {
    await page.route(`**/api/markets/smart-money/${p}*`, (r) => r.fulfill(json(empty)));
  }
  await page.route("**/api/markets/smart-money/breadth*", (r) => r.fulfill(json({
    as_of: "2026-10-21", disclosure_as_of: "2026-09-01", validated_study: false,
    source: "x", disclosure: "x", metrics: { evaluated: 0 },
  })));
  await page.route("**/api/markets/smart-money/summary*", (r) => r.fulfill(json({
    as_of: "2026-09-30", source: "x", disclosure: "x",
  })));
}

/** The real, already-run study output. Every figure below is copied verbatim from
 *  test_reports/SHP_POST_DISCLOSURE_FORWARD_STUDY_20261023.md §4.1 / the verdict block. */
const STUDY = {
  as_of: "2026-10-23", study_id: "NIDP-SHP-FWD-001",
  title: "Post-disclosure forward returns by institutional ownership change",
  stage: "exploratory",
  preregistration_sha256: "5452b0551ab57ff68ba365963eae4d0490ee250c0d4322c9f5218d0734ec7071",
  source: "study/post-disclosure-forward-returns@62443b98",
  disclosure: "RESEARCH ARTIFACT. NOT A PRODUCT FEATURE. No predictive score, no ranking, no buy/sell framing. No Nifty 500 TRI is used or implied.",
  verdict: "INCONCLUSIVE",
  verdict_reason: "At the primary horizon (20 sessions) the 95% CI [-0.8673, +2.9054] pp straddles zero and does not clear the +1.00 pp hurdle. The sample is also below the pre-registered review floor (10 of 12 blocks).",
  study_period: { start: "2024-03-31", end: "2026-06-30" }, quarters: 10,
  review_floor_blocks: 12, primary_horizon_sessions: 20, secondary_horizons_sessions: [5, 60],
  hurdle_pp: 1.0, cost_pct_round_trip_per_leg: 0.4937, cost_total_pp: 0.9874,
  cost_note: "Two legs, so the spread carries two round-trip costs (0.9874pp total). The net figure is always shown alongside the gross one.",
  eligible_population: 1255,
  eligible_population_note: "1,255 pairs survive all six pre-registered screens.",
  eligible_primary_estimand_n: 1248,
  not_yet_eligible: {
    quarter: "2026-09-30",
    reason: "Not yet eligible for forward-return evaluation. This is the only quarter with a genuine NSE filing-broadcast timestamp, but no trading session exists yet after its 25-day availability date, so the forward window has not elapsed.",
  },
  excluded_quarters: [{ quarter: "2023-12-31", reason: "Only 61 names have a comparable prior quarter." }],
  benchmark_note: "No Nifty 500 total-return index exists in this warehouse. nidp.index_eod's 'Nifty 500' row is a PRICE index with severe gaps -- 25.4% of 2025 sessions missing, largest gap 375 days -- and is never used or implied as a benchmark here.",
  robustness_note: "The same 20-session spread is +1.07pp on delta(FII+DII), -0.47pp on delta(FII) alone and +1.28pp on threshold-free terciles -- two signs from three defensible readings.",
  robustness_20_sessions: [],
  count: 3, total: 3,
  rows: [
    { sessions: 5, is_primary: false, mean_spread_pp: -0.0007, ci_low_pp: -1.1932, ci_high_pp: 1.1074,
      blocks: 10, positive_quarters: 5, net_of_cost_pp: -0.9881 },
    { sessions: 20, is_primary: true, mean_spread_pp: 1.0749, ci_low_pp: -0.8673, ci_high_pp: 2.9054,
      blocks: 10, positive_quarters: 6, net_of_cost_pp: 0.0875,
      verdict: "INCONCLUSIVE",
      verdict_reason: "10 formation quarters against a review floor of 12; the 95% CI [-0.8673, +2.9054] pp does not clear the +1.00 pp hurdle and the interval straddles zero." },
    { sessions: 60, is_primary: false, mean_spread_pp: -0.7468, ci_low_pp: -5.6316, ci_high_pp: 3.6992,
      blocks: 10, positive_quarters: 5, net_of_cost_pp: -1.7342 },
  ],
};

async function mockEvidenceStudy(page: Page, over: { fail?: boolean } = {}) {
  await page.route("**/api/markets/evidence/post-disclosure-study*", (r: Route) => {
    if (over.fail) return r.fulfill(bad);
    return r.fulfill(json(STUDY));
  });
}

const panel = (page: Page) => page.getByTestId("evidence-validation-panel");

async function openPanel(page: Page) {
  await page.goto(SM);
  await expect(panel(page)).toBeVisible(SLOW);
}

test.describe("Smart trading desk · Evidence & Validation", () => {
  test.beforeEach(async ({ page }) => {
    await mockApi(page, "populated");
    await mockHostTab(page);
    await mockEvidenceStudy(page);
  });

  test("EV-1: INCONCLUSIVE is the loud, primary state of the panel", async ({ page }) => {
    await openPanel(page);
    const verdict = page.getByTestId("evidence-verdict");
    await expect(verdict).toHaveText("INCONCLUSIVE");
    await expect(page.getByTestId("evidence-verdict-headline")).toContainText("INCONCLUSIVE");
    // Not a small badge: it is inside the dedicated headline block, not buried in a footnote.
    await expect(page.getByTestId("evidence-verdict-headline")).toContainText("Result");
  });

  test("EV-2: the primary horizon shows the mean spread WITH its 95% CI, blocks and positive quarters", async ({ page }) => {
    await openPanel(page);
    const spread = page.getByTestId("evidence-spread-20");
    await expect(spread).toHaveText("+1.07pp");
    const ci = page.getByTestId("evidence-ci-20");
    await expect(ci).toContainText("-0.87");
    await expect(ci).toContainText("+2.91");
    await expect(page.getByTestId("evidence-horizon-20")).toContainText("10 date-blocks");
    await expect(page.getByTestId("evidence-horizon-20")).toContainText("6/10 quarters positive");
    await expect(page.getByTestId("evidence-horizon-20")).toContainText("Primary horizon");
  });

  test("EV-3: the secondary horizons (5, 60) are shown, each with its own CI", async ({ page }) => {
    await openPanel(page);
    await expect(page.getByTestId("evidence-spread-5")).toHaveText("-0.00pp");
    await expect(page.getByTestId("evidence-ci-5")).toContainText("-1.19");
    await expect(page.getByTestId("evidence-spread-60")).toHaveText("-0.75pp");
    await expect(page.getByTestId("evidence-ci-60")).toContainText("-5.63");
    await expect(page.getByTestId("evidence-ci-60")).toContainText("+3.70");
  });

  test("EV-4: the cost-adjusted figure is shown explicitly, not hidden", async ({ page }) => {
    await openPanel(page);
    await expect(page.getByTestId("evidence-net-cost-20")).toContainText("+0.09pp");
    await expect(page.getByTestId("evidence-net-cost-5")).toContainText("-0.99pp");
  });

  test("EV-5: 2026-09-30 renders as its own explicit field, never a zero and never folded in", async ({ page }) => {
    await openPanel(page);
    const nye = page.getByTestId("evidence-not-yet-eligible");
    await expect(nye).toContainText("2026-09-30");
    await expect(nye).toContainText("Not yet eligible for forward-return evaluation");
    await expect(nye).toContainText("forward window has not elapsed");
    // It must never appear as one of the three horizon cards.
    await expect(page.getByTestId("evidence-horizons").getByText("2026-09-30")).toHaveCount(0);
    await expect(page.locator('[data-testid^="evidence-spread-"]')).toHaveCount(3);
  });

  test("EV-6: no Nifty 500 TRI row or benchmark figure appears anywhere on the panel", async ({ page }) => {
    // The disclosure text is allowed to SAY no TRI exists (that is the required honest framing) —
    // what must never appear is a TRI used AS a benchmark: no "vs Nifty 500" / excess-return value,
    // and no horizon card carries a benchmark figure.
    await openPanel(page);
    const body = (await panel(page).innerText()).toLowerCase();
    expect(body).not.toContain("vs nifty 500");
    expect(body).not.toContain("excess return");
    for (const n of [5, 20, 60]) {
      await expect(page.getByTestId(`evidence-horizon-${n}`)).not.toContainText("benchmark");
    }
    // The absence is explained, which is required honesty, not a violation.
    await expect(panel(page)).toContainText("No Nifty 500 total-return index exists");
  });

  test("EV-7: nothing on the panel reads as a score, a rank or a buy/sell signal", async ({ page }) => {
    await openPanel(page);
    const body = (await panel(page).innerText()).toLowerCase();
    for (const banned of ["buy signal", "sell signal", "strong buy", "target price",
      "recommended", "smart money score", "rank #", "rank:"]) {
      expect(body, `panel must not say "${banned}"`).not.toContain(banned);
    }
    await expect(panel(page)).toContainText("Research artifact");
    await expect(panel(page)).toContainText("not a product feature");
  });

  test("EV-8: the study contract fields (period, quarters, horizon, eligible pairs) are on screen", async ({ page }) => {
    await openPanel(page);
    const contract = page.getByTestId("evidence-study-contract");
    await expect(contract).toContainText("2024-03-31");
    await expect(contract).toContainText("2026-06-30");
    await expect(contract).toContainText("10");
    await expect(contract).toContainText("20 sessions");
    await expect(contract).toContainText("5, 60");
    await expect(contract).toContainText("1255");
  });

  test("EV-9: a failing data platform is an error state, never a fabricated study", async ({ page }) => {
    await mockEvidenceStudy(page, { fail: true });
    await page.goto(SM);
    await expect(page.getByTestId("evidence-validation-panel")).toBeVisible(SLOW);
    await expect(page.getByText("Evidence & Validation didn’t load")).toBeVisible(SLOW);
    // No stale/fabricated verdict is shown while the real one failed to load.
    await expect(page.getByTestId("evidence-verdict")).toHaveCount(0);
  });

  test("EV-10: the pre-registration hash is shown for provenance", async ({ page }) => {
    await openPanel(page);
    await expect(page.getByTestId("evidence-prereg-hash")).toContainText(
      "5452b0551ab57ff68ba365963eae4d0490ee250c0d4322c9f5218d0734ec7071",
    );
  });
});
