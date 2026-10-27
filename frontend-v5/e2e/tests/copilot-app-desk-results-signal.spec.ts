/**
 * Smart trading desk — the AI scanner's results chip (owner requirement 2026-10-27: "show extra strength signal for
 * strong-results candidate stocks in the AI scanner"): `results_signal` + `base_final_score` on the scanner routes' rows,
 * rendered by ResultsSignalTag on the scanner list, the Top 10 stock ideas, the Overview's Top AI opportunities and the
 * Results week ideas.
 *
 * MOCK — not real data: every route is answered with an inline payload in the shape the real route returns
 * (GET /api/positional/watchlist, /picks; POST /api/desk/strategy/ideas; GET /api/desk/results-week). `results_signal`
 * follows the coordinator's contract note of 2026-10-27 ({strength, points, basis, reasons, filed_at, sessions_since});
 * symbols are MOCK names and every expected value is worked out from these payloads. Mocked APIs, production build —
 * see pw.copilot-app.config.ts.
 */
import { test, expect, type Page, type Route } from "@playwright/test";
import { mockApi } from "../helpers/api-mock";

const DESK = "/v5/app/trader/desk";
const SLOW = { timeout: 15_000 };
const json = (route: Route, body: unknown, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });

// ── MOCK — not real data ──────────────────────────────────────────────────
const STRONG = { strength: "strong", points: 10, basis: "figures", reasons: ["PAT 2.5 band-widths above its own trend (mock)", "Filing analysis moderately positive (mock)"], filed_at: "2026-10-26T18:40:00+05:30", sessions_since: 1 };
const WEAK = { strength: "weak", points: -10, basis: "filing_analysis", reasons: ["Filing analysis moderately negative; figures not filed yet (mock)"], filed_at: "2026-10-27T14:05:00+05:30", sessions_since: 0 };
const w = (sym: string, final: number, extra: Record<string, unknown> = {}) => ({
  nse_symbol: sym, sector: "Capital Goods", stage: "BREAKOUT", confidence: "HIGH", final_score: final, close_price: 500, trigger_price: 495, stop_price: 470, atr_pct: 2.1, why: `Fixture reason ${sym}`, ...extra,
});
/** final_score already includes the points (86 = 76 + 10; 62 = 72 − 10). Order by final_score: STRONGA, PLAINC, PLAIND, WEAKB. */
const watchlist = (withSignals: boolean) => ({
  as_of_date: "2026-10-27",
  buckets: {
    breakout_confirmed: [
      w("WEAKB", 0.62, withSignals ? { base_final_score: 0.72, results_signal: WEAK } : {}),
      w("PLAINC", 0.80, withSignals ? { base_final_score: 0.80, results_signal: null } : {}),
      w("STRONGA", 0.86, withSignals ? { base_final_score: 0.76, results_signal: STRONG } : {}),
      w("PLAIND", 0.70), // no key at all: an older route
    ],
    pre_breakout: [], true_accumulation: [], trend_continuation: [],
  },
});
const PICKS = { signal_date: "2026-10-27", count: 0, picks: [] };
const scanner = (score: number, extra: Record<string, unknown> = {}) => ({ bucket: "breakout_confirmed", status: "confirmed", score, close: 500, close_date: "2026-10-27", entry: 495, stop: 470, target: 540, reason: "MOCK", horizon_days: 10, liquidity_cr: 120, atr_pct: 2.1, ...extra });
const idea = (rank: number, symbol: string, sc: Record<string, unknown>) => ({
  rank, symbol, name: `${symbol} Ltd (mock)`, scanner: sc, direction: "bullish", fno_eligible: false, plan_id: `p${rank}`, plan_status: "wait",
  status_reasons: [{ code: "mock", message: "MOCK plan reason" }], would_change_if: [], plan_inputs: { underlying: symbol }, evidence_summary: {}, oi_view: null, preferred: null, strategies: [],
});
const RANKING_NOTE = "Ranked by the scanner's final score, which now includes a provisional results adjustment that has not been tested yet (mock note).";
/** The route's order = final_score order (STRONGA 86, PLAINC 80, WEAKB 62). STRONGA's scanner block has no results_signal (the
 *  screen joins the scanner read); WEAKB's carries it (passthrough). */
const ideasBody = (withSignals: boolean) => ({
  generated_at: "2026-10-27T05:00:00+00:00", data_as_of: { mode: "end_of_day", scanner_watchlist: "2026-10-27", scanner_picks: "2026-10-27", scan_eligibility: null, price: "2026-10-27", fno: null },
  caveats: [], rules_version: "strategy-rules-v2", calculation_version: "payoff-v1", sent_to_broker: false, ranking_note: RANKING_NOTE,
  selection: { source: "positional_watchlist", scan_date: "2026-10-27", rule: "MOCK", considered: 3, selected: 3, excluded: [], limit: 10, empty_reason: null, gate: null, source_failures: [] },
  inputs: { defaults_applied: [] },
  ideas: [idea(1, "STRONGA", scanner(86)), idea(2, "PLAINC", scanner(80)), idea(3, "WEAKB", scanner(62, withSignals ? { results_signal: WEAK, base_score: 72 } : {}))],
});
const RW = {
  date: "2026-10-27", as_of: "2026-10-27T11:20:00+05:30", week: { from: "2026-10-26", to: "2026-10-31" }, basis: "historical_trend", consensus_available: false, label: "mock",
  counts: {}, results: [],
  ideas: { fno: [{ rank: 1, symbol: "STRONGA", phase: "declared", signal: 70, parts: { earnings: 80 }, why: "mock" }, { rank: 2, symbol: "PLAINC", phase: "upcoming", signal: 50, parts: {}, why: "mock" }], all: [], note: "Ordered for review, not a prediction. This ordering has not been tested yet." },
  sources: {}, gaps: [],
};

async function setup(page: Page, withSignals = true) {
  await mockApi(page, "populated");
  await page.clock.setFixedTime(new Date("2026-10-27T06:00:00Z"));
  await page.route("**/api/chat/sessions", (r) => json(r, []));
  await page.route("**/api/positional/watchlist*", (r) => json(r, watchlist(withSignals)));
  await page.route("**/api/positional/picks*", (r) => json(r, PICKS));
  await page.route("**/api/move-odds/**", (r) => json(r, { detail: "feature_not_enabled" }, 403));
  await page.route("**/api/desk/strategy/ideas", (r) => json(r, ideasBody(withSignals)));
  await page.route("**/api/desk/strategy/top", (r) => json(r, { detail: "mock: not under test" }, 503));
  await page.route("**/api/desk/results-week*", (r) => json(r, RW));
}

const BANNED = ["buy", "pick", "recommend"];

test.describe("AI scanner — results chip", () => {
  test.use({ viewport: { width: 1440, height: 1000 } });

  test("RS-1/2/3 scanner list: strong chip with points and reasons, weak chip, no chip without a signal; order by final score", async ({ page }) => {
    await setup(page);
    await page.goto(`${DESK}?tab=scanner`);
    await expect(page.getByTestId("desk-scan-row-STRONGA")).toBeVisible(SLOW);
    // order follows final_score (the routes already include the points)
    const order = await page.locator("[data-testid^='desk-scan-row-']").evaluateAll((els) => els.map((e) => e.getAttribute("data-testid")!.replace("desk-scan-row-", "")));
    expect(order.filter((s) => ["STRONGA", "PLAINC", "PLAIND", "WEAKB"].includes(s))).toEqual(["STRONGA", "PLAINC", "PLAIND", "WEAKB"]);
    // RS-1 strong
    const strong = page.getByTestId("desk-scan-results-STRONGA");
    await expect(strong).toHaveAttribute("data-strength", "strong");
    await expect(page.getByTestId("desk-scan-results-STRONGA-chip")).toHaveText(/Strong results \+10$/);
    await expect(page.getByTestId("desk-scan-results-STRONGA-chip")).toHaveAttribute("title", /PAT 2\.5 band-widths above its own trend/);
    await expect(page.getByTestId("desk-scan-results-STRONGA-detail")).toBeHidden();
    await page.getByTestId("desk-scan-results-STRONGA-chip").click();
    await expect(page.getByTestId("desk-scan-results-STRONGA-detail")).toBeVisible();
    await expect(page.getByTestId("desk-scan-results-STRONGA-detail")).toContainText("Filing analysis moderately positive (mock)");
    await expect(page.getByTestId("desk-scan-results-STRONGA-sum")).toHaveText("score 86 = technical 76 + results +10");
    // opening the chip did not open the row's chart
    expect(new URL(page.url()).searchParams.get("tab")).toBe("scanner");
    // RS-2 weak, from the filing analysis
    await expect(page.getByTestId("desk-scan-results-WEAKB")).toHaveAttribute("data-strength", "weak");
    await expect(page.getByTestId("desk-scan-results-WEAKB-chip")).toHaveText(/Weak results −10 · figures pending$/);
    await page.getByTestId("desk-scan-results-WEAKB-chip").click();
    await expect(page.getByTestId("desk-scan-results-WEAKB-sum")).toHaveText("score 62 = technical 72 + results −10");
    // RS-3 null signal and an absent key: no chip
    await expect(page.getByTestId("desk-scan-results-PLAINC")).toHaveCount(0);
    await expect(page.getByTestId("desk-scan-results-PLAIND")).toHaveCount(0);
    const chipText = (await page.locator("[data-testid$='-chip'][data-testid^='desk-scan-results-']").allInnerTexts()).join(" ").toLowerCase();
    for (const b of BANNED) expect(chipText).not.toContain(b);
  });

  test("RS-4 Top 10 stock ideas: the route's final-score order, chips by passthrough or join, the API's ranking note", async ({ page }) => {
    await setup(page);
    await page.goto(`${DESK}?tab=scanner`);
    const rows = page.getByTestId("desk-top10-stocks-list").locator(":scope > li");
    await expect(rows).toHaveCount(3, SLOW);
    const order = await rows.evaluateAll((els) => els.map((e) => e.getAttribute("data-testid")!.replace("desk-top10-stock-", "")));
    expect(order).toEqual(["STRONGA", "PLAINC", "WEAKB"]);
    // STRONGA: the ideas route's scanner block has no signal; the scanner read's row gives it (and its technical part)
    await expect(page.getByTestId("desk-top10-results-STRONGA-chip")).toHaveText(/Strong results \+10$/, SLOW);
    await page.getByTestId("desk-top10-results-STRONGA-chip").click();
    await expect(page.getByTestId("desk-top10-results-STRONGA-sum")).toHaveText("score 86 = technical 76 + results +10");
    // WEAKB: carried by the ideas route itself
    await expect(page.getByTestId("desk-top10-results-WEAKB-chip")).toHaveText(/Weak results −10 · figures pending$/);
    await expect(page.getByTestId("desk-top10-results-PLAINC")).toHaveCount(0);
    await expect(page.getByTestId("desk-top10-stocks-note")).toContainText(RANKING_NOTE);
    // the Results week ideas join the same scanner read
    await expect(page.getByTestId("results-week-idea-results-STRONGA-chip")).toHaveText(/Strong results \+10$/, SLOW);
    await expect(page.getByTestId("results-week-idea-results-PLAINC")).toHaveCount(0);
  });

  test("RS-5 Overview › Top AI opportunities: final-score order and the chip", async ({ page }) => {
    await setup(page);
    await page.goto(`${DESK}?tab=overview`);
    const opps = page.getByTestId("desk-opp");
    await expect(opps.first()).toBeVisible(SLOW);
    const order = await opps.evaluateAll((els) => els.map((e) => e.getAttribute("data-symbol")));
    expect(order.slice(0, 4)).toEqual(["STRONGA", "PLAINC", "PLAIND", "WEAKB"]);
    await expect(page.getByTestId("desk-opp-results-STRONGA-chip")).toHaveText(/Strong results \+10$/);
    await expect(page.getByTestId("desk-opp-results-WEAKB-chip")).toHaveText(/Weak results −10 · figures pending$/);
    await expect(page.getByTestId("desk-opp-results-PLAINC")).toHaveCount(0);
    await page.getByTestId("desk-opp-results-STRONGA-chip").click();
    await expect(page.getByTestId("desk-opp-results-STRONGA-detail")).toContainText("PAT 2.5 band-widths above its own trend (mock)");
    expect(new URL(page.url()).searchParams.get("tab")).toBe("overview");
  });

  test("RS-6 an older backend without results_signal: no chip anywhere, the lists still render", async ({ page }) => {
    const errors: string[] = [];
    page.on("pageerror", (e) => errors.push(e.message));
    await setup(page, false);
    await page.goto(`${DESK}?tab=scanner`);
    await expect(page.getByTestId("desk-scan-row-STRONGA")).toBeVisible(SLOW);
    await expect(page.getByTestId("desk-top10-stocks-list").locator(":scope > li")).toHaveCount(3, SLOW);
    await expect(page.locator("[data-strength]")).toHaveCount(0);
    expect(errors).toEqual([]);
  });
});
