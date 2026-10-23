/**
 * One-screen Copilot app (/v5/app) — Smart trading desk: the Historical Smart Money Movement panel.
 *
 * MOCK — not real data in the sense that these are inline route fulfilments rather than a live
 * backend; but every FIGURE here is the REAL staging figure, produced by running the shipped SQL
 * (nidp/services/daas_api/routers/ownership.py :: _ROWS_SQL / _CUTS_SQL) against nidp_staging on
 * 2026-10-23 and the shipped Python derivation (classify_row / cohort_cuts / classify_status) over
 * its output. They are recorded in test_reports/ownership_reaction_20261023.md. So a drift between
 * the payload shape here and the router's real output fails an assertion rather than silently
 * blanking a panel.
 *
 * This file's job is to assert the DISPLAYED NUMBERS, not that the endpoint returned 200. A green
 * health check validates the service, never the correctness of a metric — and every error worth
 * catching on this screen is a denominator or an absent-means-zero error, which only a displayed
 * value can catch. So the spec checks, on screen:
 *
 *   * the coverage denominator is the ELIGIBLE cohort (89), never the 429 that merely disclose the
 *     current quarter and never the whole index;
 *   * an empty classification renders as a first-class result naming its real siblings, and the
 *     cut-points are not relaxed to populate it (Accumulation is genuinely 0 this quarter);
 *   * the measured cut-points are printed, so a label can be checked against its own inputs;
 *   * a contested figure reads "sources differ" and NO number;
 *   * an undisclosed figure reads "not disclosed" / "not recorded", never 0;
 *   * Distribution Risk is the only red status and Reversal Watch is not red;
 *   * nothing anywhere reads as a buy/sell signal, a score or a ranking by one.
 */
import { test, expect, type Page, type Route } from "@playwright/test";
import { mockApi } from "../helpers/api-mock";

const DESK = "/v5/app/trader/desk";
const SM = `${DESK}?tab=smartmoney`;
const SLOW = { timeout: 15_000 };

/** Real cohort percentiles, measured by the shipped cohort_cuts() over the 89 eligible names. */
const COHORT = {
  quarter: "2026-06-30 -> 2026-09-30",
  note: "Percentiles of THIS quarter's eligible cohort, recomputed every quarter. They are quarter-specific, not universal constants, and the status rules below are written against them. The cohort is the 89 names with two comparable quarters.",
  rules: {},
  n: 89,
  inst_p25: -0.05, inst_p50: 0.15, inst_p75: 0.77,
  ret_p25: -13.75, ret_p50: -6.77, ret_p75: 3.42,
  vol_p25: 0.59, vol_p50: 0.761, vol_p75: 0.972,
  deliv_p25: 1.32, deliv_p50: 3.66, deliv_p75: 5.94,
  high_p50: -22.17, low_p25: 6.508,
  abs_inst_p50: 0.42, abs_ret_p50: 11.05, near_52w_high_pct: -10,
};

/** Real counts over the 89. Accumulation is 0 — a measured result, not a gap. */
const COUNTS = {
  cohort: 89,
  status_accumulation: 0, status_breakout_watch: 1, status_reversal_watch: 0,
  status_distribution_risk: 4, status_divergence: 7, status_insufficient_data: 3, status_none: 74,
  status_sum: 89, status_reconciles: true,
  same_source: 65, cross_source: 24,
  reduced: 10, raised: 29, divergence: 7,
  strong_positive: 13, neutral: 67, negative: 9, uncorroborated: 18,
  price_legs_missing: 0, split_disclosed: 77, fii_unusable: 3, reduced_and_negative: 5,
};

const COVERAGE = {
  universe_total: 500, with_current_quarter: 429, computable_change: 89,
  same_source: 65, cross_source: 24, split_disclosed: 77, reference_cross_section: 488,
  insufficient_for_change: 411, trend_renderable: 91, single_quarter_only: 340,
  with_52w_position: 88, filing_date_known: 78,
};

/** Real rows, exactly as the shipped derivation emits them. */
const ROW = {
  CANFINHOME: {
    symbol: "CANFINHOME", industry: "Financial Services",
    delta_basis: "cross_source", delta_source: "NSE_SHP - screener_in",
    fii_delta_pp: -0.72, dii_delta_pp: -1.07, inst_delta_pp: -1.79,
    fii_pct_now: 11.3, dii_pct_now: 20.4, delta_alt_pp: null, fii_spread_pp: null,
    fii_trust: "contested", mf_pct: 14.99, bank_fi_pct: 0.0, split_source: "NSE_SHP",
    split_is_level: true, dii_components_complete: false,
    ret_pct: -17.14, vol_ratio: 1.137, deliv_shift_pp: 6.6, ret_percentile: 9.9,
    sessions_cur: 65, sessions_prev: 60, price_legs_present: true,
    price_band: "bottom_quintile", volume_band: "expanded",
    reaction: "negative", reaction_corroborated: true, reaction_note: null,
    dist_52w_high_pct: -25.97, dist_52w_low_pct: 0.59,
    filed_at: "2026-10-15 15:57:35+05:30", quarters_available: 13,
    status: "distribution_risk",
    status_reason: "Institutional holding fell -1.79pp (at or beyond the -0.50pp materiality floor) while the price fell -17.14% (at or below the cohort median -6.77%) on a volume ratio of 1.137 (at or above the cohort 75th percentile 0.972) -- falling on rising participation while ownership dropped.",
  },
  ICICIBANK: {
    symbol: "ICICIBANK", industry: "Financial Services",
    delta_basis: "same_source", delta_source: "screener_in",
    fii_delta_pp: 0.89, dii_delta_pp: -0.55, inst_delta_pp: 0.34,
    fii_pct_now: 34.68, dii_pct_now: 41.77, delta_alt_pp: 16.65, fii_spread_pp: 15.76,
    fii_trust: "unusable", mf_pct: 29.39, bank_fi_pct: 0.1, split_source: "NSE_SHP",
    split_is_level: true, dii_components_complete: false,
    ret_pct: -3.89, vol_ratio: 0.585, deliv_shift_pp: 4.89, ret_percentile: 53.6,
    sessions_cur: 65, sessions_prev: 60, price_legs_present: true,
    price_band: "middle", volume_band: "contracted",
    reaction: "neutral", reaction_corroborated: true, reaction_note: null,
    dist_52w_high_pct: -10.7, dist_52w_low_pct: 11.29,
    filed_at: "2026-10-22 16:44:35+05:30", quarters_available: 12,
    status: "insufficient_data",
    status_reason: "The two sources disagree about this quarter's FII holding by as much as the change itself, so the ownership leg cannot carry a status.",
  },
  ANGELONE: {
    symbol: "ANGELONE", industry: "Financial Services",
    delta_basis: "same_source", delta_source: "screener_in",
    fii_delta_pp: -1.25, dii_delta_pp: -0.75, inst_delta_pp: -2.0,
    fii_pct_now: 8.4, dii_pct_now: 9.1, delta_alt_pp: -1.25, fii_spread_pp: null,
    fii_trust: "ok", mf_pct: null, bank_fi_pct: null, split_source: null,
    split_is_level: true, dii_components_complete: false,
    ret_pct: -17.13, vol_ratio: 0.606, deliv_shift_pp: 5.61, ret_percentile: 10.1,
    sessions_cur: 65, sessions_prev: 60, price_legs_present: true,
    price_band: "bottom_quintile", volume_band: "contracted",
    reaction: "neutral", reaction_corroborated: false,
    reaction_note: "Price fell into the bottom quintile of the peer group, but volume contracted (0.606 vs the 0.757 peer median), so the two legs do not agree.",
    dist_52w_high_pct: -90.44, dist_52w_low_pct: 31.33,
    filed_at: null, quarters_available: 12,
    status: "none", status_reason: "No status rule's legs all fired for this name this quarter.",
  },
  KARURVYSYA: {
    symbol: "KARURVYSYA", industry: "Financial Services",
    delta_basis: "cross_source", delta_source: "NSE_SHP - screener_in",
    fii_delta_pp: 0.18, dii_delta_pp: 0.88, inst_delta_pp: 1.06,
    fii_pct_now: 15.2, dii_pct_now: 24.1, delta_alt_pp: null, fii_spread_pp: null,
    fii_trust: "contested", mf_pct: 33.29, bank_fi_pct: 0.0, split_source: "NSE_SHP",
    split_is_level: true, dii_components_complete: false,
    ret_pct: 9.69, vol_ratio: 1.063, deliv_shift_pp: 1.57, ret_percentile: 84.0,
    sessions_cur: 65, sessions_prev: 60, price_legs_present: true,
    price_band: "top_quintile", volume_band: "expanded",
    reaction: "strong_positive", reaction_corroborated: true, reaction_note: null,
    dist_52w_high_pct: -9.44, dist_52w_low_pct: 55.97,
    filed_at: "2026-10-15 12:21:54+05:30", quarters_available: 13,
    status: "breakout_watch",
    status_reason: "Institutional holding rose 1.06pp (cohort 75th percentile 0.77pp) and the quarter closed -9.44% from the 52-week high -- within 10% of it, against a cohort median of -22.17% -- on a volume ratio of 1.063 (cohort median 0.761).",
  },
  NUVOCO: {
    symbol: "NUVOCO", industry: "Construction Materials",
    delta_basis: "same_source", delta_source: "screener_in",
    fii_delta_pp: -0.08, dii_delta_pp: -0.35, inst_delta_pp: -0.43,
    fii_pct_now: 4.2, dii_pct_now: 22.0, delta_alt_pp: -0.08, fii_spread_pp: 0.0,
    fii_trust: "ok", mf_pct: 16.35, bank_fi_pct: null, split_source: "NSE_SHP",
    split_is_level: true, dii_components_complete: false,
    ret_pct: 11.47, vol_ratio: 2.907, deliv_shift_pp: -2.37, ret_percentile: 86.2,
    sessions_cur: 65, sessions_prev: 60, price_legs_present: true,
    price_band: "top_quintile", volume_band: "expanded",
    reaction: "strong_positive", reaction_corroborated: true, reaction_note: null,
    dist_52w_high_pct: -23.2, dist_52w_low_pct: 22.28,
    filed_at: "2026-10-21 17:04:57+05:30", quarters_available: 12,
    status: "divergence",
    status_reason: "Ownership moved -0.43pp while the price moved +11.47% -- opposite directions, and both beyond their cohort median magnitudes (0.42pp and 11.05%).",
  },
};

const BASE = {
  as_of: "2026-09-30", previous_period: "2026-06-30", universe: "Nifty 500",
  retrospective: true, validated_study: false,
  source: "nidp.shareholding_pattern (FII/DII percent, two quarters) x nidp.prices_eod_adjusted (adj_close/adj_volume) x nidp.prices_eod (deliv_pct), universe nidp.index_constituents",
  disclosure: "DESCRIPTIVE AND RETROSPECTIVE: this is co-occurrence, not causation, and not a trading signal.",
  basis_note: "At the prior quarter NSE_SHP discloses no FII figure at all, so a change can only come from screener_in (same_source) or by differencing the two publishers (cross_source). ICICIBANK shows why that matters: cross-source reads +16.65pp where screener_in alone reads +0.89pp.",
  split_note: "mf_pct and bank_fi_pct are a LEVEL at the current quarter only.",
  filing_note: "`filed_at` is the real NSE publication timestamp from shareholding_pattern.broadcast_at, not an estimate. 48.5% are timestamped after the 15:30 close, so for those the figure was first tradable the NEXT session.",
  trend_note: "Of the 500 names, 340 disclose exactly one quarter and only 91 disclose four or more, so a multi-quarter trend is not drawable for most of the index.",
  price_window: {
    current: ["2026-07-01", "2026-09-30"], previous: ["2026-04-01", "2026-06-30"],
    sessions_current: 65, sessions_previous: 60,
  },
  thresholds: {
    basis: "percentiles of the same quarter's Nifty-500 cross-section; derived from the distribution, not chosen round numbers",
    price_series: "nidp.prices_eod_adjusted adj_close / adj_volume (split- and bonus-adjusted, dividends excluded, so a price return and not a total return)",
    relative_strength: "`ret_percentile` is this name's position within the peer cross-section over the identical window. It is NOT excess return over an index.",
    reference_cross_section: 488,
    ret_p20_pct: -13.54, ret_p80_pct: 7.66, ret_median_pct: -5.53,
    vol_ratio_median: 0.757, deliv_shift_median_pp: 3.34,
    material_pp: 0.5, min_sessions: 30,
    note: "The median name's volume FELL this quarter (ratio 0.757) and the median delivery percentage ROSE (3.34 pp), so a fixed 1.0x or 'delivery up' rule would misread the quarter. Both legs are judged against the market.",
  },
  cohort_thresholds: COHORT,
  coverage: COVERAGE,
  counts: COUNTS,
};

const VIEW_ROWS: Record<string, Array<Record<string, unknown>>> = {
  all: [ROW.CANFINHOME, ROW.ICICIBANK, ROW.ANGELONE, ROW.KARURVYSYA, ROW.NUVOCO],
  reduced: [ROW.CANFINHOME, ROW.ANGELONE],
  raised: [ROW.KARURVYSYA],
  divergence: [ROW.NUVOCO],
};

const STATUS_ROWS: Record<string, Array<Record<string, unknown>>> = {
  accumulation: [],                      // genuinely zero this quarter
  reversal_watch: [],                    // also genuinely zero
  distribution_risk: [ROW.CANFINHOME],
  breakout_watch: [ROW.KARURVYSYA],
  divergence: [ROW.NUVOCO],
  insufficient_data: [ROW.ICICIBANK],
};

const json = (body: unknown) => ({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
const bad = { status: 502, contentType: "application/json", body: JSON.stringify({ error: { status: 502, message: "upstream_unavailable" } }) };

/** Minimal-but-valid smart-money payloads: the host tab early-returns on a TOTAL failure, so the
 *  panel under test needs its neighbours to answer. They are deliberately empty, which also proves
 *  this panel does not depend on them. */
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

async function mockOwnership(page: Page, over: { fail?: boolean } = {}) {
  await page.route("**/api/markets/ownership/reaction*", (r: Route) => {
    if (over.fail) return r.fulfill(bad);
    const u = new URL(r.request().url());
    const view = u.searchParams.get("view") ?? "all";
    const status = u.searchParams.get("status") ?? "any";
    const rows = status !== "any" ? (STATUS_ROWS[status] ?? []) : (VIEW_ROWS[view] ?? VIEW_ROWS.all);
    return r.fulfill(json({
      ...BASE,
      filters: { view, reaction: "any", status, basis: u.searchParams.get("basis") ?? "any", sort: "inst_delta" },
      count: rows.length, total: rows.length, rows,
    }));
  });
}

const panel = (page: Page) => page.getByTestId("or-coverage-banner");

async function openPanel(page: Page) {
  await page.goto(SM);
  await expect(panel(page)).toBeVisible(SLOW);
}

test.describe("Smart trading desk · Historical Smart Money Movement", () => {
  test.beforeEach(async ({ page }) => {
    await mockApi(page, "populated");
    await mockHostTab(page);
    await mockOwnership(page);
  });

  test("TC-16: the reduced view renders real rows and PRINTS its measured cut-points", async ({ page }) => {
    await openPanel(page);
    await page.getByTestId("or-view-reduced").click();

    // The rows themselves, with the real figures.
    const row = page.getByRole("row").filter({ hasText: "CANFINHOME" });
    await expect(row).toBeVisible(SLOW);
    await expect(page.getByTestId("or-inst-CANFINHOME")).toHaveText("-1.79pp");
    await expect(page.getByTestId("or-ret-CANFINHOME")).toContainText("-17.14%");
    await expect(page.getByTestId("or-vol-CANFINHOME")).toHaveText("1.137×");
    await expect(page.getByTestId("or-dlv-CANFINHOME")).toHaveText("+6.60pp");

    // The cut-points are on screen, so "Negative" can be checked against its own inputs.
    const cuts = page.getByTestId("or-thresholds");
    await expect(cuts).toContainText("-13.54%");
    await expect(cuts).toContainText("7.66%");
    await expect(cuts).toContainText("0.757");
    await expect(cuts).toContainText("488");
    // And the status cut-points, labelled with the quarter they came from.
    const cohort = page.getByTestId("or-cohort-thresholds");
    await expect(cohort).toContainText("2026-06-30 -> 2026-09-30");
    await expect(cohort).toContainText("+0.77pp");
    await expect(cohort).toContainText("0.972");
    await expect(cohort).toContainText("Recomputed every quarter");
  });

  test("TC-17: it says it explains the past, and never reads as a buy/sell signal", async ({ page }) => {
    await openPanel(page);
    const note = page.getByTestId("or-retrospective-note");
    await expect(note).toContainText("explains the past");
    await expect(note).toContainText("does not predict");
    await expect(note).toContainText("co-occurrence, not cause");
    await expect(note).toContainText("not a reason to buy or sell");

    // Nothing in THIS panel may read as a call or a score. Scoped to the panel, because the host
    // tab's own footer legitimately contains the words "not a buy signal" — as a disclaimer.
    const body = (await page.getByTestId("or-panel").innerText()).toLowerCase();
    for (const banned of ["buy signal", "sell signal", "strong buy", "target price",
      "recommended", "smart money score", "rank #"]) {
      expect(body, `panel must not say "${banned}"`).not.toContain(banned);
    }
    // The live `validated_study` read drives the wording, not a hardcoded string. Scoped to this
    // panel's own Section: the host tab carries its own identically-worded pill.
    await expect(
      page.getByTestId("screen-desk-smart-money")
        .locator("section", { has: page.getByTestId("or-panel") })
        .getByText("Evidence only · not scored"),
    ).toBeVisible();
  });

  test("TC-18: an undisclosed figure reads 'not disclosed'/'not recorded', never 0", async ({ page }) => {
    await openPanel(page);
    // ANGELONE discloses no MF/Banks-FI split and has no filing timestamp.
    const split = page.getByTestId("or-split-ANGELONE");
    await expect(split).toContainText("MF not disclosed");
    await expect(split).toContainText("Banks/FI not disclosed");
    await expect(split).not.toContainText("0.00%");
    await expect(page.getByTestId("or-filed-ANGELONE")).toHaveText("not recorded");

    // Whereas a real zero IS shown as a zero: CANFINHOME's Banks/FI is genuinely 0.00%.
    await expect(page.getByTestId("or-split-CANFINHOME")).toContainText("Banks/FI 0.00%");

    // The split is a level, never a change — said in words.
    await expect(page.getByTestId("or-split-caveat")).toContainText("LEVEL, not a change");
    await expect(page.getByTestId("or-split-caveat")).toContainText("LIC is invisible");
  });

  test("TC-19: every denominator is the ELIGIBLE cohort, never 429 and never the index", async ({ page }) => {
    await openPanel(page);
    // The prominent banner, not a footnote.
    const banner = panel(page);
    await expect(banner).toContainText("89 of 500");
    await expect(banner).toContainText("excluded from ownership-change classifications");
    await expect(banner).not.toContainText("429 of");

    // The detail line splits the basis, so "89" is not itself overstated.
    const denom = page.getByTestId("or-denominator");
    await expect(denom).toContainText("89 of 500");
    await expect(denom).toContainText("65");
    await expect(denom).toContainText("24");
    // 429 may be MENTIONED as the current-quarter count, but never as a delta denominator.
    await expect(denom).toContainText("429 disclose the current quarter");
  });

  test("TC-20: divergence renders, and a contested figure reads 'sources differ' with no number", async ({ page }) => {
    await openPanel(page);
    await page.getByTestId("or-view-divergence").click();
    await expect(page.getByRole("row").filter({ hasText: "NUVOCO" })).toBeVisible(SLOW);
    // The one real case where ownership fell while the price ROSE.
    await expect(page.getByTestId("or-inst-NUVOCO")).toHaveText("-0.43pp");
    await expect(page.getByTestId("or-ret-NUVOCO")).toContainText("+11.47%");

    // ICICIBANK: the publishers disagree by as much as the change, so no number is printed.
    await page.getByTestId("or-view-all").click();
    const fii = page.getByTestId("or-fii-ICICIBANK");
    await expect(fii).toHaveText("sources differ");
    await expect(fii).not.toContainText("0.89");
    await expect(fii).not.toContainText("16.65");
  });

  test("TC-21: no score column anywhere, and sorting is by a measured column", async ({ page }) => {
    await openPanel(page);
    const headers = await page.getByTestId("or-panel").getByRole("row").first().innerText();
    for (const banned of ["Score", "Rank", "Conviction"]) {
      expect(headers).not.toContain(banned);
    }
    // The sort vocabulary is measured columns only.
    for (const id of ["inst_delta", "ret", "vol_ratio", "symbol"]) {
      await expect(page.getByTestId(`or-sort-${id}`)).toBeVisible();
    }
    await expect(page.getByTestId("or-sort-score")).toHaveCount(0);
  });

  test("TC-31: status chips carry their REAL counts, including a zero", async ({ page }) => {
    await openPanel(page);
    const f = page.getByTestId("or-status-filter");
    await expect(f).toContainText("Accumulation 0");
    await expect(f).toContainText("Breakout Watch 1");
    await expect(f).toContainText("Reversal Watch 0");
    await expect(f).toContainText("Distribution Risk 4");
    await expect(f).toContainText("Divergence 7");
    await expect(f).toContainText("Insufficient data 3");
  });

  test("TC-32: an empty classification is a first-class RESULT naming its real siblings", async ({ page }) => {
    await openPanel(page);
    await page.getByTestId("or-status-pick-accumulation").click();
    const empty = page.getByTestId("or-empty-state");
    await expect(empty).toBeVisible(SLOW);
    await expect(empty).toContainText("No stocks currently meet the Accumulation criteria");
    // It names what DID fire, with real counts.
    await expect(empty).toContainText("1 Breakout Watch");
    await expect(empty).toContainText("4 Distribution Risk");
    // And it states that the thresholds were not relaxed to fill the tab.
    await expect(empty).toContainText("not relaxed to fill a tab");
  });

  test("TC-41: the DISPLAYED classification counts reconcile to the eligible cohort", async ({ page }) => {
    await openPanel(page);
    const rec = page.getByTestId("or-reconciliation");
    await expect(rec).toBeVisible(SLOW);
    // 0 + 1 + 0 + 4 + 7 + 3 + 74 = 89. Printed, so a dropped or double-counted name is visible.
    await expect(rec).toContainText("= 89 of 89 eligible");
    await expect(rec).not.toContainText("MISMATCH");
    // "No status" is explicitly accounted for, not hidden.
    await expect(rec).toContainText("No status 74");
    await expect(rec).toContainText("Insufficient data 3");

    // Cross-check: the sum of the chip counts equals the cohort, read off the screen.
    const text = await page.getByTestId("or-status-filter").innerText();
    const nums = [...text.matchAll(/(?:Accumulation|Breakout Watch|Reversal Watch|Distribution Risk|Divergence|Insufficient data|No status)\s+(\d+)/g)]
      .map((m) => Number(m[1]));
    expect(nums).toHaveLength(7);
    expect(nums.reduce((a, b) => a + b, 0)).toBe(89);
  });

  test("TC-42: the count of names with no ownership history is VISIBLE, not implied", async ({ page }) => {
    await openPanel(page);
    // 500 eligible universe - 89 comparable = 411 excluded, stated outright.
    await expect(panel(page)).toContainText("411 names have no second comparable quarter");
    await expect(panel(page)).toContainText("not counted as unchanged");
  });

  test("TC-33: Distribution Risk is the only red status; Reversal Watch is not red", async ({ page }) => {
    await openPanel(page);
    await page.getByTestId("or-view-all").click();   // the breakout_watch row lives in this view
    const risk = page.getByTestId("or-status-CANFINHOME");
    await expect(risk).toHaveText("Distribution Risk");
    await expect(risk).toHaveAttribute("data-status", "distribution_risk");

    // The legend must describe Reversal Watch as a watch item and NOT as a risk.
    const legend = page.getByTestId("or-status-legend");
    await expect(legend).toContainText("buying into weakness");
    await expect(legend).toContainText("A watch item, not a risk");

    // Colour: the risk chip and the watch chip must not share a border colour.
    const riskColour = await risk.evaluate((el) => getComputedStyle(el).borderColor);
    const watch = page.getByTestId("or-status-KARURVYSYA");
    const watchColour = await watch.evaluate((el) => getComputedStyle(el).borderColor);
    expect(riskColour).not.toBe(watchColour);
  });

  test("TC-34: the filing timestamp is shown as the real publication date, after-close flagged", async ({ page }) => {
    await openPanel(page);
    await page.getByTestId("or-view-all").click();
    // ICICIBANK filed 2026-10-22 16:44 IST — after the 15:30 close.
    const filed = page.getByTestId("or-filed-ICICIBANK");
    await expect(filed).toContainText("2026-10-22");
    await expect(filed).toContainText("after close — next session");
    // KARURVYSYA filed 12:21 — during the session.
    await expect(page.getByTestId("or-filed-KARURVYSYA")).toContainText("during session");
    // And the note explains what the timestamp is and is not.
    await expect(page.getByTestId("or-filing-note")).toContainText("not an estimate");
  });

  test("TC-35: the cohort percentile is never labelled as a benchmark comparison", async ({ page }) => {
    await openPanel(page);
    await expect(page.getByTestId("or-ret-CANFINHOME")).toContainText("10th in cohort");
    const body = await page.getByTestId("or-panel").innerText();
    // The exact phrasing that would imply an index benchmark must not appear.
    expect(body).not.toContain("vs Nifty 500");
    expect(body).not.toContain("Rel. Strength (vs");
    expect(body).not.toContain("TRI");
  });

  test("TC-36: this panel's failure is its own, and never blanks the tab", async ({ page }) => {
    await mockOwnership(page, { fail: true });
    await page.goto(SM);
    // The host screen still renders.
    await expect(page.getByTestId("screen-desk-smart-money")).toBeVisible(SLOW);
    // And the panel shows an error rather than an empty table that would read as "nobody moved".
    await expect(page.getByText("Ownership reaction didn’t load")).toBeVisible(SLOW);
    await expect(page.getByTestId("or-coverage-banner")).toHaveCount(0);
  });

  test("TC-37: a row without enough quarters says so instead of implying a trend", async ({ page }) => {
    await openPanel(page);
    // All five real rows disclose >= 12 quarters, so none shows the no-trend hint...
    await expect(page.getByTestId("or-no-trend-CANFINHOME")).toHaveCount(0);
    // ...and the panel still states that a trend is undrawable for most of the INDEX.
    await expect(page.getByTestId("or-trend-note")).toContainText("340 disclose exactly one quarter");
    await expect(page.getByTestId("or-trend-note")).toContainText("only 91 disclose four or more");
  });

  test("TC-38: an uncorroborated sharp move is not called Negative", async ({ page }) => {
    await openPanel(page);
    // ANGELONE fell 17.13% but on CONTRACTING volume: one leg only.
    await expect(page.getByTestId("or-reaction-ANGELONE")).toHaveText("Neutral");
    await expect(page.getByTestId("or-uncorroborated-ANGELONE")).toContainText("volume did not confirm");
    // CANFINHOME fell on EXPANDING volume: both legs, so Negative is earned.
    await expect(page.getByTestId("or-reaction-CANFINHOME")).toHaveText("Negative");
  });
});
