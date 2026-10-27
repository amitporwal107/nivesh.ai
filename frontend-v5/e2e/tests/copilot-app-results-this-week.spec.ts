/**
 * Results This Week (docs/EARNINGS_SURPRISE_TRACKER.md §9, P1.5): the Watchlist page's "Results This Week" block
 * (screens/workspace/ResultsThisWeek.tsx) and the per-stock results file (tradingdesk/resultsweek/ResultsFile.tsx), opened
 * from that block and from the desk's Events › Results week. Cases TC-W1 … TC-W13 of
 * test_reports/results_this_week_frontend_2026-10-28.md.
 *
 * MOCK — not real data: GET /api/desk/results-week, GET /api/desk/results-week/stock/{symbol} and the AI scanner routes
 * (GET /api/positional/watchlist, /picks) are answered by inline payloads in the §5 / §9 shapes, aligned with the backend
 * on feat/results-week-file (services/results_week/stock.py, track.py: Snap `span` / `since` / `note` / `oi_comparable` /
 * `carry_vs_usual_pp`, items' `subtype` / `amounts` / `open_questions`, coverage `filings`). Symbols are MOCK names; the
 * rollover and coverage sentences copy the FORMAT of the coordinator's staging examples of 27 Oct (MANKIND, BAJAJ-AUTO),
 * not their figures. Every expected value below is worked out from these payloads. Mocked APIs, production build — see
 * pw.copilot-app.config.ts. The clock is fixed at Tue 27 Oct 2026, 11:30 IST.
 *
 * Except TC-W14, which is REAL DATA: e2e/fixtures/results_week_staging_20261027.json, the GET /api/desk/results-week body
 * built read-only on staging for 2026-10-27 (committed with the contract spec), before `fno_track` existed — so it also
 * exercises the older-route path on real rows. Its expected order is read from the fixture's own ideas, not the screen.
 *
 * Screenshots (1440 and 390, the list and the file) only when RTW_SHOTS names a directory, in a run with network so
 * fonts load; the TC run itself is offline.
 */
import { test, expect, type Page, type Route } from "@playwright/test";
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";
import { mockApi } from "../helpers/api-mock";

const here = path.dirname(fileURLToPath(import.meta.url));

const PAGE = "/v5/app/page/watchlist";
const EVENTS = "/v5/app/trader/desk?tab=events";
const SLOW = { timeout: 15_000 };
const SHOTS = process.env.RTW_SHOTS || "";
const json = (route: Route, body: unknown, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });

// ── MOCK — not real data: GET /api/desk/results-week (§5 + §9a fno_track) ──
const EXPIRY_NOTE = "spans a monthly expiry: total OI is not comparable across it (the expiring month still counts on expiry day while the next month fills, then drops out); read the carry against the stock's own past expiries instead";
const one = (date: string, state: string, text: string, price: number, oi: number) => ({ date, state, text, price_pct: price, oi_pct: oi, span: "1 session" });
const rng = (low: number, mid: number, high: number) => ({ low, mid, high });
const metric = (key: string, expected: unknown, filed: number | null, extra: Record<string, unknown> = {}) => ({ key, unit: "cr", expected, filed, reliable: expected != null, ...extra });
const row = (symbol: string, event_date: string, status: string, fno: boolean, extra: Record<string, unknown> = {}) => ({
  symbol, name: `${symbol} Ltd (mock)`, sector: fno ? "Capital Goods" : "Consumer", event_date, status, fno, period_label: "Q2 FY2027", basis: "consolidated",
  verdict: { label: null, intensity: null, reason: null },
  score: { value: null, band: null, coverage: { present: [], missing: [] } },
  components: { surprise: null, trend: null, outlook: null, quality: null },
  reaction: null, fno_buildup: null, technical: null, chartink: null, evidence: [], gaps: [],
  fno_track: null,
  ...extra,
});
const ROW_A = row("MOCKA", "2026-10-26", "declared", true, {
  filed_at: "2026-10-26T20:59:00+05:30",
  verdict: { label: "above", intensity: "outstanding", reason: "PAT 2.5 band-widths above the baseline mid (mock)" },
  score: { value: 82, band: "above", coverage: { present: ["surprise", "trend", "outlook", "quality"], missing: [] } },
  components: {
    surprise: { value: 88, metrics: { pat: metric("pat", rng(1100, 1200, 1300), 1450, { vs_mid_pct: 20.8, z: 2.5, verdict: "above" }), revenue: metric("revenue", rng(9000, 9400, 9800), 9800, { vs_mid_pct: 4.3, z: 1.0, verdict: "in_line" }) } },
    trend: { value: 74, yoy_pct: { revenue: 12.1, ebitda: 18.0, pat: 28.5 }, qoq_pct: { revenue: 3.4, ebitda: 5.1, pat: 9.2 }, ebitda_margin_change_pp: 1.2 },
    outlook: { value: 73, analysed: true, net_impact_score: 46, net_band: "moderately_positive", confidence_score: 88 },
    quality: { value: 100, flags: [], checked: ["tax_rate"], not_checked: ["cash_flow: not stored"] },
  },
  reaction: { first_session: "2026-10-27", stock_return_pct: 5.1, nifty_return_pct: -0.5, excess_pct: 5.6, volume_x: 3.2 },
  technical: { stage: "breakout_watch", final_score: 0.61, score: 61 },
  fno_track: {
    before: one("2026-10-26", "long_buildup", "long build-up", 4.49, 9.6),
    after: { date: "2026-10-27", since: "2026-10-26", state: null, text: "rollover 92.6 % vs its usual 93.6 % (normal)", price_pct: 5.1, oi_pct: -38.2,
      span: "2026-10-26 close → 2026-10-27 close", note: EXPIRY_NOTE, oi_comparable: false, carry_vs_usual_pp: -1.0 },
  },
});
const ROW_B = row("MOCKB", "2026-10-26", "declared", false, {
  verdict: { label: "in_line", intensity: null, reason: null },
  score: { value: 55, band: "in_line", coverage: { present: ["surprise", "trend", "quality"], missing: ["outlook"] } },
  components: { surprise: { value: 52, metrics: {} }, trend: { value: 58, yoy_pct: { revenue: 6.0 } }, outlook: null, quality: { value: 75, flags: [], checked: ["tax_rate"], not_checked: [] } },
  reaction: { excess_pct: -0.8, stock_return_pct: -1.3, nifty_return_pct: -0.5, first_session: "2026-10-27" },
});
const ROW_D = row("MOCKD", "2026-10-26", "declared", true, {
  verdict: { label: "below", intensity: "well_below", reason: "PAT 2.4 band-widths below the baseline mid (mock)" },
  score: { value: 31, band: "below", coverage: { present: ["surprise", "trend", "outlook", "quality"], missing: [] } },
  components: { surprise: { value: 10 }, trend: { value: 30, yoy_pct: { pat: -22 } }, outlook: { value: 30, net_impact_score: -40, net_band: "moderately_negative" }, quality: { value: 100, flags: [], checked: ["tax_rate"] } },
  reaction: { excess_pct: -4.1, stock_return_pct: -4.6, nifty_return_pct: -0.5, first_session: "2026-10-27" },
  fno_track: {
    before: one("2026-10-23", "no_clear_signal", "no clear signal", 0.2, 1.1),
    after: { date: "2026-10-27", since: "2026-10-23", state: "short_buildup", text: "short build-up", price_pct: -4.6, oi_pct: 6.1, span: "2026-10-23 close → 2026-10-27 close", note: null, oi_comparable: true, carry_vs_usual_pp: null },
  },
});
const ROW_X = row("MOCKX", "2026-10-26", "declared", true, {
  verdict: { label: "in_line", intensity: null, reason: null },
  score: { value: 70, band: "above", coverage: { present: ["surprise", "trend"], missing: ["outlook", "quality"] } },
  fno_track: { before: one("2026-10-23", "short_covering", "short covering", 1.0, -2.5), after: null },
});
const ROW_P = row("MOCKP", "2026-10-27", "pending", true, { gaps: ["Figures not in the warehouse yet (mock gap)"], fno_track: { before: one("2026-10-26", "long_unwinding", "long unwinding", -0.9, -3.0), after: null } });
const ROW_U1 = row("MOCKU1", "2026-10-28", "upcoming", true, { fno_track: { before: one("2026-10-27", "short_covering", "short covering", 1.2, -3.4), after: null } });
const ROW_U2 = row("MOCKU2", "2026-10-29", "upcoming", false);
const ROW_E = row("MOCKE", "2026-10-29", "upcoming", true, { fno_track: { before: null, after: null } });
const RESULTS = [ROW_A, ROW_B, ROW_D, ROW_X, ROW_P, ROW_U1, ROW_U2, ROW_E];
const NOTE = "Ordered for review, not a prediction. Tested on past results seasons: this ordering showed no measurable skill so far.";
const RW = {
  schema: "results-week-v1", date: "2026-10-27", as_of: "2026-10-27T11:20:00+05:30", mode: "live", week: { from: "2026-10-26", to: "2026-10-31" },
  basis: "historical_trend", consensus_available: false, label: "vs historical trend (the company's own past quarters), not analyst consensus",
  counts: { declared: 4, declared_pending: 1, upcoming: 3, above: 1, in_line: 2, below: 1, not_rated: 0 },
  results: RESULTS,
  ideas: {
    // MOCKOUT is ordered but outside the week's rows (a look-back meeting): never a row of this list.
    fno: [
      { rank: 1, symbol: "MOCKA", phase: "declared", signal: 78.4, parts: { earnings: { value: 82, weight: 40 }, reaction: { value: 74, weight: 20 }, oi: { value: 70, weight: 20 }, technical: { value: 61, weight: 20 } }, why: "Above trend on PAT (mock)" },
      { rank: 2, symbol: "MOCKU1", phase: "upcoming", signal: 64, parts: { technical: 58, oi: 66 }, why: "Short covering into results (mock)" },
      { rank: 3, symbol: "MOCKOUT", phase: "declared", signal: 60, parts: {}, why: "mock" },
      { rank: 4, symbol: "MOCKD", phase: "declared", signal: 40.2, parts: { earnings: 31 }, why: "Below trend (mock)" },
    ],
    all: [
      { rank: 1, symbol: "MOCKA", phase: "declared", signal: 80.1, parts: { earnings: 82 }, why: "mock" },
      { rank: 2, symbol: "MOCKB", phase: "declared", signal: 52.0, parts: { earnings: 55 }, why: "mock" },
      { rank: 3, symbol: "MOCKU2", phase: "upcoming", signal: 41.5, parts: { technical: 40 }, why: "mock" },
    ],
    note: NOTE, tested: true,
  },
  sources: {}, gaps: [], read_only: true,
};
/** An older backend: no row carries the fno_track key. */
const RW_OLD = { ...RW, results: RESULTS.map(({ fno_track: _t, ...r }) => r) };
const EXPECT_FNO = ["MOCKA", "MOCKU1", "MOCKD", "MOCKX", "MOCKP", "MOCKE"];
const EXPECT_ALL = ["MOCKA", "MOCKB", "MOCKU2", "MOCKX", "MOCKD", "MOCKP", "MOCKU1", "MOCKE"];

// ── MOCK — not real data: the AI scanner's rows (results booster join) ─────
const STRONG = { strength: "strong", points: 5, basis: "figures", reasons: ["Q2 FY27 PAT +28.5 % YoY, revenue +12.1 % (mock)"], filed_at: "2026-10-26T20:59:00+05:30", sessions_since: 0 };
const w = (sym: string, final: number, extra: Record<string, unknown> = {}) => ({ nse_symbol: sym, sector: "Capital Goods", stage: "BREAKOUT", confidence: "HIGH", final_score: final, close_price: 500, trigger_price: 495, stop_price: 470, atr_pct: 2.1, why: `Fixture reason ${sym}`, ...extra });
const SCANNER = { as_of_date: "2026-10-27", buckets: { breakout_confirmed: [w("MOCKA", 0.66, { base_final_score: 0.61, results_signal: STRONG }), w("MOCKD", 0.5, { base_final_score: 0.5, results_signal: null })], pre_breakout: [], true_accumulation: [], trend_continuation: [] } };

// ── MOCK — not real data: GET /api/desk/results-week/stock/{symbol} (§9b) ──
const ANALYST_NOTE = "No analyst-views source is connected: the Trendlyne connection returns corporate events only and no consensus or brokerage feed is held. Nothing on this page is an analyst view.";
const item = (at: string, kind: string, title: string, extra: Record<string, unknown> = {}) => ({
  at, kind, title, subtype: null, band: "neutral", impact: 0, confidence: 70, summary: `${title}: summary from the stored analysis (mock).`,
  positives: [], negatives: [], amounts: [], open_questions: [], announcement_id: `a-${kind}-${at.slice(0, 10)}`, url: null, ...extra,
});
const sess = (rel: number, date: string, close: number, chg: number, ex: number, vol: number, fut: Record<string, unknown> | null, pcr: number | null = null) =>
  ({ date, rel, close, chg_pct: chg, excess_pct: ex, volume_x: vol, fut, pcr_next: pcr });
const fut = (oi: number, oiPct: number, pricePct: number, state: string, extra: Record<string, unknown> = {}) =>
  ({ total_oi: oi, oi_pct: oiPct, near_price: 500, price_pct: pricePct, state, text: state.replace(/_/g, " "), next_premium_pct: null, expiry_day: false, carry_vs_usual_pp: null, ...extra });
const FILE_A = {
  schema: "results-stock-v1", symbol: "MOCKA", name: "MOCKA Ltd (mock)", sector: "Capital Goods", event_date: "2026-10-26", status: "declared",
  filed_at: "2026-10-26T20:59:00+05:30", first_reaction_session: "2026-10-27", period_label: "Q2 FY2027", row: ROW_A,
  preview: {
    as_of: "2026-10-26",
    lines: [
      "Revenue baseline for Q2 FY2027: ₹9,000–9,800 crore (mid ₹9,400 crore), from the company's own past quarters (not analyst consensus).",
      "Latest stored quarter (2026-09-30): revenue +12.1 % YoY, PAT +28.5 % YoY, EBITDA margin 21.0 %.",
      "F&O going in (2026-10-26): long build-up (spot +4.49 %, total OI +9.60 %).",
    ],
    expected: { revenue: { low: 9000, mid: 9400, high: 9800, reliable: true, note: null }, pat: { low: 1100, mid: 1200, high: 1300, reliable: true, note: null } },
    last_quarters: [
      { period_end: "2025-12-31", revenue: 8300, ebitda: 1600, pat: 1080, ebitda_margin_pct: 19.3, revenue_yoy_pct: 9.0, pat_yoy_pct: 11.0 },
      { period_end: "2026-09-30", revenue: 9800, ebitda: 2058, pat: 1450, ebitda_margin_pct: 21.0, revenue_yoy_pct: 12.1, pat_yoy_pct: 28.5 },
      { period_end: "2026-06-30", revenue: 9480, ebitda: 1960, pat: 1330, ebitda_margin_pct: 20.7, revenue_yoy_pct: 10.2, pat_yoy_pct: null },
      { period_end: "2026-03-31", revenue: 9100, ebitda: 1800, pat: 1200, ebitda_margin_pct: 19.8, revenue_yoy_pct: 8.4, pat_yoy_pct: 14.0 },
    ],
    past_reactions: { n: 8, event_day_avg_pct: 1.2, d1_avg_pct: 0.4, w1_avg_pct: 2.4, up_share_pct: 75.0 },
    positioning: one("2026-10-26", "long_buildup", "long build-up", 4.49, 9.6),
  },
  commentary: {
    pre: [item("2026-10-12T10:15:00+05:30", "business_update", "Business update (mock)", { band: "mildly_positive", impact: 18 })],
    results: [
      item("2026-10-26T20:59:00+05:30", "results", "Outcome of Board Meeting (mock)", {
        subtype: "Q2 FY27 results", band: "moderately_positive", impact: 46, confidence: 88,
        summary: "Revenue and margins grew on volume; the board approved the quarter's unaudited results (mock analysis text).",
        positives: ["Volume growth in the core segment (mock)", "EBITDA margin up 120 bps (mock)"],
        negatives: ["Higher raw-material costs (mock)"], amounts: ["Revenue: 9800 ₹ crore", "PAT: 1450 ₹ crore"],
        open_questions: ["Whether the margin gain holds next quarter (mock)"], url: "https://www.nseindia.com/mock-results-a",
      }),
      item("2026-10-26T21:20:00+05:30", "presentation", "Investor Presentation (mock)", { band: "mildly_positive", impact: 20, confidence: 75 }),
    ],
    post: [],
    sentiment: { band: "moderately_positive", impact: 46, confidence: 88, basis: "the filing analysis of “Outcome of Board Meeting (mock)” (2026-10-26 15:29 UTC)", n: 2 },
    coverage: { analysed: 3, filings: 7, note: "3 of 7 exchange filings since 2026-10-05 have a stored analysis; the others are not summarised here." },
  },
  analyst_views: { available: false, note: ANALYST_NOTE },
  track: {
    sessions: [
      sess(0, "2026-10-27", 525.5, 5.1, 5.6, 3.2, fut(1_400_000, -38.2, 5.0, "short_covering", { next_premium_pct: 0.55, expiry_day: true, carry_vs_usual_pp: -1.0 }), 0.43),
      sess(-5, "2026-10-20", 488.0, 0.4, 0.1, 0.9, fut(2_000_000, 0.8, 0.4, "no_clear_signal")),
      sess(-4, "2026-10-21", 487.0, -0.2, -0.4, 0.8, fut(2_020_000, 1.0, -0.2, "no_clear_signal")),
      sess(-3, "2026-10-22", 489.9, 0.6, 0.3, 1.1, fut(2_080_000, 3.0, 0.6, "long_buildup")),
      sess(-2, "2026-10-23", 477.9, -2.45, -1.9, 1.4, null),
      sess(-1, "2026-10-26", 499.4, 4.49, 3.9, 2.1, fut(2_270_000, 9.6, 4.5, "long_buildup", { next_premium_pct: 0.62 }), 0.71),
    ],
    before: one("2026-10-26", "long_buildup", "long build-up", 4.49, 9.6),
    after: ROW_A.fno_track.after,
    notes: ["Next-month premium and PCR are read for the session before the result and the latest session only.", `This window ${EXPIRY_NOTE}.`],
  },
  sources: { commentary: "stored filing analyses (mock)", track: "stock_ohlcv, NSE F&O bhavcopy (mock)" }, gaps: [], read_only: true,
};
const FILE_B = {
  schema: "results-stock-v1", symbol: "MOCKB", name: "MOCKB Ltd (mock)", sector: "Consumer", event_date: "2026-10-26", status: "declared",
  filed_at: "2026-10-26T14:10:00+05:30", first_reaction_session: "2026-10-26", period_label: "Q2 FY2027", row: ROW_B,
  preview: { as_of: "2026-10-26", lines: [], expected: { revenue: { low: 1500, mid: 1600, high: 1700, reliable: true, note: null }, pat: null }, last_quarters: [], past_reactions: null, positioning: null },
  commentary: {
    pre: [], results: [], post: [], sentiment: null,
    coverage: { analysed: 0, filings: 4, note: "0 of 4 exchange filings since 2026-10-05 have a stored analysis; the others are not summarised here. The results filing itself has no full analysis yet (or its document could not be read)." },
  },
  analyst_views: { available: false, note: ANALYST_NOTE },
  track: { sessions: [sess(-1, "2026-10-23", 1010, 0.3, 0.1, 0.9, null), sess(0, "2026-10-26", 997, -1.3, -0.8, 1.6, null), sess(1, "2026-10-27", 1001, 0.4, 0.9, 1.1, null)], before: null, after: null, notes: ["Not in F&O: the track shows the cash market only."] },
  sources: {}, gaps: ["exchange filings list could not be read (mock gap)"], read_only: true,
};
/** A partial answer (an older backend): no preview, commentary or track blocks at all. */
const FILE_D_PARTIAL = { schema: "results-stock-v1", symbol: "MOCKD", name: "MOCKD Ltd (mock)", status: "declared", event_date: "2026-10-26", row: ROW_D };
const FILE_U1 = {
  schema: "results-stock-v1", symbol: "MOCKU1", name: "MOCKU1 Ltd (mock)", sector: "Capital Goods", event_date: "2026-10-28", status: "upcoming", filed_at: null,
  first_reaction_session: null, period_label: "Q2 FY2027", row: ROW_U1,
  preview: { as_of: "2026-10-27", lines: ["Past 6 results: the stock moved +1.10 % on average on the day; up on 67 % of them."], expected: { revenue: { low: 4000, mid: 4200, high: 4400, reliable: true }, pat: { low: 500, mid: 540, high: 580, reliable: false, note: "Profit near zero in a base quarter (mock)." } }, last_quarters: [], past_reactions: { n: 6, event_day_avg_pct: 1.1, d1_avg_pct: null, w1_avg_pct: 0.8, up_share_pct: 66.7 }, positioning: one("2026-10-27", "short_covering", "short covering", 1.2, -3.4) },
  commentary: { pre: [item("2026-10-20T09:00:00+05:30", "board_outcome", "Board meeting intimation (mock)")], results: [], post: [], sentiment: null, coverage: { analysed: 1, filings: 2, note: "1 of 2 exchange filings since 2026-10-07 have a stored analysis; the others are not summarised here." } },
  analyst_views: { available: false, note: ANALYST_NOTE },
  track: { sessions: [sess(-2, "2026-10-26", 300, 0.5, 0.2, 1.0, fut(900_000, 1.0, 0.5, "no_clear_signal")), sess(-1, "2026-10-27", 303.6, 1.2, 1.7, 1.3, fut(870_000, -3.4, 1.2, "short_covering"))], before: one("2026-10-27", "short_covering", "short covering", 1.2, -3.4), after: null, notes: [] },
  sources: {}, gaps: [], read_only: true,
};

type Ans = { status?: number; body?: unknown; gate?: Promise<void> };
interface Opts { rw?: () => Ans; file?: (sym: string) => Ans | undefined; phone?: boolean }
async function setup(page: Page, o: Opts = {}) {
  const seen = { rw: [] as string[], file: [] as string[] };
  if (o.phone) await page.setViewportSize({ width: 390, height: 844 });
  await mockApi(page, "populated");
  await page.clock.setFixedTime(new Date("2026-10-27T06:00:00Z"));
  await page.route("**/api/chat/sessions", (r) => json(r, []));
  await page.route("**/api/positional/watchlist*", (r) => json(r, SCANNER));
  await page.route("**/api/positional/picks*", (r) => json(r, { signal_date: "2026-10-27", count: 0, picks: [] }));
  await page.route(/\/api\/desk\/results-week(\?|$)/, async (r) => {
    seen.rw.push(r.request().url());
    const a: Ans = o.rw ? o.rw() : { body: RW };
    if (a.gate) await a.gate;
    return json(r, a.body ?? { detail: "mock failure" }, a.status ?? 200);
  });
  await page.route(/\/api\/desk\/results-week\/stock\//, (r) => {
    const url = r.request().url();
    seen.file.push(url);
    const sym = decodeURIComponent(new URL(url).pathname.split("/").pop() ?? "");
    const a = o.file?.(sym);
    if (a) return json(r, a.body ?? { detail: "mock failure" }, a.status ?? 200);
    if (sym === "MOCKA") return json(r, FILE_A);
    if (sym === "MOCKB") return json(r, FILE_B);
    if (sym === "MOCKD") return json(r, FILE_D_PARTIAL);
    if (sym === "MOCKU1") return json(r, FILE_U1);
    if (sym === "MOCKE") return json(r, { detail: "mock failure" }, 500);
    return json(r, { detail: { code: "no_results_meeting", message: `${sym} has no results meeting in the week of 2026-10-27 (mock).` } }, 404);
  });
  return seen;
}

async function openPage(page: Page) {
  await page.goto(PAGE);
  await expect(page.getByTestId("rtw-list")).toBeVisible(SLOW);
}
const order = (page: Page) => page.getByTestId("rtw-list").locator(":scope > li").evaluateAll((els) => els.map((e) => e.getAttribute("data-testid")?.replace("rtw-row-", "")));
const over = (page: Page) => page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
const BANNED = [/\bpicks?\b/i, /recommend/i, /\bbuy\b/i, /\bsell\b/i, /beat the street/i, /beat expectations/i];

test.describe("Results This Week — Watchlist page (desktop 1440)", () => {
  test.use({ viewport: { width: 1440, height: 1000 } });

  test("TC-W1 the block sits right after the AI scanner watchlist; title, week, counts, basis", async ({ page }) => {
    const seen = await setup(page);
    await openPage(page);
    await expect(page.getByTestId("rtw-title")).toHaveText("Results This Week · Mon 26 Oct – Sat 31 Oct");
    await expect(page.getByTestId("rtw-counts")).toHaveText("This week: 4 declared · 1 figures pending · 3 upcoming.");
    await expect(page.getByTestId("rtw-basis")).toHaveText("vs historical trend · not analyst consensus");
    expect(seen.rw[0]).toContain("/api/desk/results-week?date=2026-10-27");
    const y = async (id: string) => (await page.getByTestId(id).boundingBox())!.y;
    expect(await y("ai-scanner-watchlist")).toBeLessThan(await y("results-this-week"));
    await expect(page.getByTestId("watchlist-count")).toBeVisible(SLOW);
    expect(await y("results-this-week")).toBeLessThan(await y("watchlist-count"));
    await expect(page.getByTestId("rtw-ideas-note")).toContainText(NOTE);
  });

  test("TC-W2 F&O | All toggle and the order: ideas order of that list, then earnings score, then date", async ({ page }) => {
    await setup(page);
    await openPage(page);
    await expect(page.getByTestId("rtw-seg-fno")).toHaveAttribute("aria-pressed", "true");
    await expect(page.getByTestId("rtw-seg-fno")).toHaveText("F&O · 6");
    await expect(page.getByTestId("rtw-seg-all")).toHaveText("All · 8");
    expect(await order(page)).toEqual(EXPECT_FNO);
    await expect(page.getByTestId("rtw-row-MOCKB")).toHaveCount(0);
    await expect(page.getByTestId("rtw-row-MOCKOUT")).toHaveCount(0);
    await page.getByTestId("rtw-seg-all").click();
    await expect(page.getByTestId("rtw-list")).toHaveAttribute("data-universe", "all");
    expect(await order(page)).toEqual(EXPECT_ALL);
    await expect(page.getByTestId("rtw-signal-MOCKB")).toHaveText("52");
    await expect(page.getByTestId("rtw-rule")).toContainText("All: every results name this week.");
  });

  test("TC-W3 cells: date · status, verdict, earnings score, signal, reaction, sentiment; missing says so", async ({ page }) => {
    await setup(page);
    await openPage(page);
    const a = page.getByTestId("rtw-row-MOCKA");
    await expect(a.getByTestId("rtw-when-MOCKA")).toHaveText(/Mon 26 Oct\s*Declared/);
    await expect(page.getByTestId("rtw-verdict-MOCKA")).toHaveText("Above · Outstanding");
    await expect(page.getByTestId("rtw-score-MOCKA")).toHaveText("82");
    await expect(page.getByTestId("rtw-signal-MOCKA")).toHaveText("78");
    await expect(page.getByTestId("rtw-reaction-MOCKA")).toHaveText("+5.6% vs Nifty");
    await expect(page.getByTestId("rtw-sentiment-MOCKA")).toHaveText("moderately positive");
    await expect(page.getByTestId("rtw-verdict-MOCKD")).toHaveText("Well below");
    await expect(page.getByTestId("rtw-sentiment-MOCKD")).toHaveText("moderately negative");
    await expect(page.getByTestId("rtw-verdict-MOCKP")).toHaveText("figures pending");
    await expect(page.getByTestId("rtw-signal-MOCKP")).toHaveText("not ordered");
    await expect(page.getByTestId("rtw-score-MOCKP")).toHaveText("—");
    await expect(page.getByTestId("rtw-verdict-MOCKU1")).toHaveText("not declared yet");
    await expect(page.getByTestId("rtw-when-MOCKU1")).toHaveText(/Wed 28 Oct\s*Upcoming/);
    await expect(page.getByTestId("rtw-signal-MOCKX")).toHaveText("—");
    await expect(page.getByTestId("rtw-score-MOCKX")).toHaveText("70");
    await expect(page.getByTestId("rtw-sentiment-MOCKX")).toHaveText("not analysed");
    await page.getByTestId("rtw-seg-all").click();
    await expect(page.getByTestId("rtw-sentiment-MOCKB")).toHaveText("not analysed");
    await expect(page.getByTestId("rtw-fno-MOCKB")).toHaveText("not F&O");
    // no zero anywhere for a missing figure
    for (const id of ["rtw-score-MOCKU2", "rtw-signal-MOCKE", "rtw-reaction-MOCKE"]) await expect(page.getByTestId(id)).not.toHaveText(/^0/);
  });

  test("TC-W4 results booster: the scanner row's results_signal joined by symbol; none → nothing", async ({ page }) => {
    await setup(page);
    await openPage(page);
    await expect(page.getByTestId("rtw-booster-MOCKA-chip")).toHaveText(/Strong results \+5/, SLOW);
    await expect(page.getByTestId("rtw-booster-MOCKA")).toHaveAttribute("data-strength", "strong");
    await expect(page.getByTestId("rtw-booster-MOCKD")).toHaveCount(0);
    await expect(page.getByTestId("rtw-booster-MOCKU1")).toHaveCount(0);
    // opening the chip does not open the row's file
    await page.getByTestId("rtw-booster-MOCKA-chip").click();
    await expect(page.getByTestId("rtw-booster-MOCKA-detail")).toContainText("PAT +28.5 % YoY");
    await expect(page.getByTestId("results-file")).toHaveCount(0);
  });

  test("TC-W5 F&O before → after: fno_track text and spot / OI %; across an expiry the rollover reading, uncoloured", async ({ page }) => {
    await setup(page);
    await openPage(page);
    const before = page.getByTestId("rtw-fno-MOCKA-before");
    await expect(before).toContainText("Long build-up");
    await expect(before).toContainText("spot +4.49% · OI +9.60%");
    const after = page.getByTestId("rtw-fno-MOCKA-after");
    await expect(after).toHaveAttribute("data-comparable", "false");
    await expect(after).toContainText("Rollover 92.6 % vs its usual 93.6 % (normal)");
    await expect(after).toContainText("spot +5.10% · carry vs usual −1.0 pp");
    await expect(after).not.toContainText(/build-up|unwinding|covering/i);
    await expect(after).toHaveAttribute("title", EXPIRY_NOTE);
    await expect(page.getByTestId("rtw-fno-MOCKD-after")).toContainText("Short build-up");
    await expect(page.getByTestId("rtw-fno-MOCKD-after")).toContainText("spot −4.60% · OI +6.10%");
    await expect(page.getByTestId("rtw-fno-MOCKU1")).toContainText("So far");
    await expect(page.getByTestId("rtw-fno-MOCKU1-before")).toContainText("Short covering");
    await expect(page.getByTestId("rtw-fno-MOCKU1-after")).toHaveText("results not declared yet");
    await expect(page.getByTestId("rtw-fno-MOCKX-after")).toHaveText("not available yet");
    await expect(page.getByTestId("rtw-fno-MOCKE")).toHaveText("not available");
  });

  test("TC-W6 a row opens the results file: every section in order, with the route's commentary", async ({ page }) => {
    const seen = await setup(page);
    await openPage(page);
    await page.getByTestId("rtw-open-MOCKA").click();
    const file = page.getByTestId("results-file");
    await expect(file).toBeVisible();
    await expect(file).toHaveAttribute("role", "dialog");
    await expect(page.getByTestId("results-file-close")).toBeFocused();
    await expect(page.getByTestId("results-file-preview")).toBeVisible(SLOW);
    expect(seen.file[0]).toContain("/api/desk/results-week/stock/MOCKA?date=2026-10-27");
    await expect(page.getByTestId("results-file-meta")).toHaveText("Capital Goods · Q2 FY2027 · results Mon 26 Oct · filed Mon 26 Oct, 20:59 IST");
    const ids = await file.locator("section[data-testid^='results-file-']").evaluateAll((els) => els.map((e) => e.getAttribute("data-testid")));
    expect(ids).toEqual(["results-file-preview", "results-file-pre", "results-file-result", "results-file-post", "results-file-analyst", "results-file-track", "results-file-scores"]);
    await expect(page.getByTestId("results-file-coverage")).toContainText("3 of 7 exchange filings since 2026-10-05 have a stored analysis");
    // preview
    await expect(page.getByTestId("results-file-preview-lines").locator("li")).toHaveCount(3);
    await expect(page.getByTestId("results-file-preview-lines")).toContainText("F&O going in (2026-10-26): long build-up (spot +4.49 %, total OI +9.60 %).");
    await expect(page.getByTestId("results-file-expected-revenue")).toContainText("₹9,000 cr – ₹9,800 cr · mid ₹9,400 cr");
    await expect(page.getByTestId("results-file-expected-pat")).toContainText("₹1,100 cr – ₹1,300 cr");
    const q = page.getByTestId("results-file-quarters").locator("tbody tr");
    await expect(q).toHaveCount(4);
    await expect(q.first()).toContainText("Sep 2026");
    await expect(q.first()).toContainText("₹9,800 cr");
    await expect(q.first()).toContainText("+28.5%");
    await expect(page.getByTestId("results-file-quarter-2026-06-30")).toContainText("n/a");
    await expect(page.getByTestId("results-file-past")).toContainText("+1.2%");
    await expect(page.getByTestId("results-file-past")).toContainText("75% of results");
    await expect(page.getByTestId("results-file-past")).toContainText("Based on 8 past results");
    await expect(page.getByTestId("results-file-positioning")).toContainText("Long build-up");
    // pre-result filings
    const pre = page.getByTestId("results-file-pre-items").getByTestId("results-file-item");
    await expect(pre).toHaveCount(1);
    await expect(pre.first()).toHaveAttribute("data-kind", "business_update");
    await expect(pre.first()).toContainText("Business update · Mon 12 Oct, 10:15 IST");
    // the result: early commentary on the unaudited result + sentiment
    const res = page.getByTestId("results-file-result-items").getByTestId("results-file-item");
    await expect(res).toHaveCount(2);
    const r0 = res.first();
    await expect(r0).toContainText("Results filing · Q2 FY27 results · Mon 26 Oct, 20:59 IST");
    await expect(r0.getByTestId("results-file-item-title")).toHaveText("Outcome of Board Meeting (mock)");
    await expect(r0.getByTestId("results-file-item-summary")).toHaveText("Revenue and margins grew on volume; the board approved the quarter's unaudited results (mock analysis text).");
    await expect(r0.getByTestId("results-file-item-band")).toHaveText(/moderately positive\s*impact \+46\s*· confidence 88%/);
    await expect(r0.getByTestId("results-file-item-positives").locator("li")).toHaveCount(2);
    await expect(r0.getByTestId("results-file-item-negatives")).toContainText("Higher raw-material costs (mock)");
    await expect(r0.getByTestId("results-file-item-amounts")).toContainText("Revenue: 9800 ₹ crore");
    await expect(r0.getByTestId("results-file-item-questions")).toContainText("Whether the margin gain holds next quarter (mock)");
    await expect(r0.getByTestId("results-file-item-link")).toHaveAttribute("href", "https://www.nseindia.com/mock-results-a");
    await expect(res.nth(1)).toHaveAttribute("data-kind", "presentation");
    await expect(page.getByTestId("results-file-sentiment-band")).toHaveText(/moderately positive\s*impact \+46\s*· confidence 88%/);
    await expect(page.getByTestId("results-file-sentiment")).toContainText("2 analyses");
    // post-result
    await expect(page.getByTestId("results-file-post-empty")).toHaveText("no analysed filing after the results yet");
    // analyst views: not connected
    await expect(page.getByTestId("results-file-analyst-nc")).toContainText("Not connected");
    await expect(page.getByTestId("results-file-analyst-nc")).toContainText(ANALYST_NOTE);
    // cash & F&O tracker: rel −5 … 0 in order, rel 0 highlighted, the expiry day's carry, before vs after, notes
    const rows = page.getByTestId("results-file-track-table").locator("tbody tr");
    await expect(rows).toHaveCount(6);
    expect(await rows.evaluateAll((els) => els.map((e) => e.getAttribute("data-rel")))).toEqual(["-5", "-4", "-3", "-2", "-1", "0"]);
    const zero = page.getByTestId("results-file-track-row-0");
    await expect(zero).toHaveAttribute("aria-current", "true");
    await expect(zero).toContainText("0 · reaction");
    await expect(zero).toContainText("Tue 27 Oct");
    await expect(zero).toContainText("₹525.50");
    await expect(zero.getByTestId("results-file-track-expiry")).toContainText("expiry day");
    await expect(zero.getByTestId("results-file-track-carry")).toHaveText("carry vs usual −1.0 pp");
    await expect(zero).toContainText("0.43");
    const pre1 = page.getByTestId("results-file-track-row--1");
    await expect(pre1).toContainText("+0.62%");
    await expect(pre1).toContainText("0.71");
    await expect(pre1.getByTestId("results-file-track-carry")).toHaveCount(0);
    await expect(page.getByTestId("results-file-track-row--2")).toContainText("n/a");
    await expect(page.getByTestId("results-file-track-before")).toContainText("BEFORE · MON 26 OCT · 1 SESSION");
    await expect(page.getByTestId("results-file-track-before")).toContainText("Long build-up");
    await expect(page.getByTestId("results-file-track-after")).toContainText("AFTER · MON 26 OCT → TUE 27 OCT");
    await expect(page.getByTestId("results-file-track-after-snap")).toHaveAttribute("data-comparable", "false");
    await expect(page.getByTestId("results-file-track-after-snap")).toContainText("Rollover 92.6 % vs its usual 93.6 % (normal)");
    await expect(page.getByTestId("results-file-track-after-snap-note")).toContainText("Spans a monthly expiry: total OI is not comparable");
    // the window's expiry note is shown once, in the after box; the other track note stays
    await expect(page.getByTestId("results-file-track-notes").locator("li")).toHaveCount(1);
    await expect(page.getByTestId("results-file-track-notes")).toContainText("Next-month premium and PCR are read for the session before the result and the latest session only.");
    // scores
    await expect(page.getByTestId("results-file-verdict")).toHaveText("Above · Outstanding");
    await expect(page.getByTestId("results-file-score")).toContainText("82 · above");
    await expect(page.getByTestId("results-file-score-surprise")).toContainText("88/100");
    await expect(page.getByTestId("results-file-score-trend")).toContainText("74/100");
    await expect(page.getByTestId("results-file-score-outlook")).toContainText("73/100");
    await expect(page.getByTestId("results-file-score-quality")).toContainText("100/100");
    await expect(page.getByTestId("results-file-score-technical")).toContainText("61");
    await expect(page.getByTestId("results-file-signal")).toContainText("Signal 78 · #1 in the order");
    await expect(page.getByTestId("results-file-booster-tag-chip")).toHaveText(/Strong results \+5/);
    // wording, then Escape closes and focus goes back to the row
    const text = await file.innerText();
    for (const b of BANNED) expect(text, `banned wording ${b}`).not.toMatch(b);
    await page.keyboard.press("Escape");
    await expect(file).toHaveCount(0);
    await expect(page.getByTestId("rtw-open-MOCKA")).toBeFocused();
  });

  test("TC-W7 missing parts say not available / not analysed, never 0 (non-F&O file; a partial answer)", async ({ page }) => {
    await setup(page);
    await openPage(page);
    await page.getByTestId("rtw-seg-all").click();
    await page.getByTestId("rtw-open-MOCKB").click();
    await expect(page.getByTestId("results-file-preview")).toBeVisible(SLOW);
    await expect(page.getByTestId("results-file-preview-lines-na")).toHaveText("no preview lines");
    await expect(page.getByTestId("results-file-expected-revenue")).toContainText("₹1,500 cr – ₹1,700 cr");
    await expect(page.getByTestId("results-file-expected-pat")).toContainText("no reliable baseline");
    await expect(page.getByTestId("results-file-quarters")).toContainText("no stored quarters");
    await expect(page.getByTestId("results-file-past")).toContainText("no past results with price history");
    await expect(page.getByTestId("results-file-positioning")).toContainText("not an F&O stock");
    await expect(page.getByTestId("results-file-coverage")).toContainText("0 of 4 exchange filings");
    await expect(page.getByTestId("results-file-pre-empty")).toHaveText("no analysed filing before the results");
    await expect(page.getByTestId("results-file-result-empty")).toHaveText("the results filing is not analysed yet");
    await expect(page.getByTestId("results-file-sentiment-na")).toHaveText("not analysed");
    await expect(page.getByTestId("results-file-analyst-nc")).toContainText("Not connected");
    await expect(page.getByTestId("results-file-track-table").locator("thead")).not.toContainText("Futures");
    await expect(page.getByTestId("results-file-track")).toContainText("Not an F&O stock: the cash market only.");
    await expect(page.getByTestId("results-file-track-summary")).toHaveCount(0);
    await expect(page.getByTestId("results-file-track-notes")).toContainText("Not in F&O");
    await expect(page.getByTestId("results-file-track-row-0")).toContainText("0 · reaction");
    await expect(page.getByTestId("results-file-score-outlook")).toContainText("missing");
    await expect(page.getByTestId("results-file-gaps")).toContainText("exchange filings list could not be read (mock gap)");
    await page.getByTestId("results-file-close").click();
    // a partial answer: blocks the route did not send are "not available"; Scores read the row
    await page.getByTestId("rtw-open-MOCKD").click();
    await expect(page.getByTestId("results-file-preview-na")).toHaveText("not available", SLOW);
    await expect(page.getByTestId("results-file-pre-na")).toHaveText("not available");
    await expect(page.getByTestId("results-file-result-na")).toHaveText("not available");
    await expect(page.getByTestId("results-file-post-na")).toHaveText("not available");
    await expect(page.getByTestId("results-file-track-na")).toHaveText("not available");
    await expect(page.getByTestId("results-file-coverage")).toHaveText("Commentary coverage: not available.");
    await expect(page.getByTestId("results-file-analyst-nc")).toContainText("No analyst-views or consensus source is connected");
    await expect(page.getByTestId("results-file-verdict")).toHaveText("Well below");
    await expect(page.getByTestId("results-file-booster-none")).toHaveText("no results adjustment on the AI scanner's rows");
    await page.getByTestId("results-file-close").click();
    // an upcoming file: rel counts to the meeting; no rel 0 yet; "so far" positioning
    await page.getByTestId("rtw-open-MOCKU1").click();
    await expect(page.getByTestId("results-file-track")).toContainText("Results not declared yet: sessions count to the meeting date (Wed 28 Oct).", SLOW);
    await expect(page.getByTestId("results-file-track-row-0")).toHaveCount(0);
    await expect(page.getByTestId("results-file-track-before")).toContainText("SO FAR · TUE 27 OCT");
    await expect(page.getByTestId("results-file-track-after-snap")).toHaveText("results not declared yet");
    await expect(page.getByTestId("results-file-result-empty")).toHaveText("results not declared yet");
    await expect(page.getByTestId("results-file-sentiment-na")).toHaveText("results not declared yet");
    await expect(page.getByTestId("results-file-expected-pat")).toContainText("no reliable baseline");
    await expect(page.getByTestId("results-file-expected-pat")).toContainText("Profit near zero in a base quarter (mock).");
    await expect(page.getByTestId("results-file-verdict-na")).toHaveText("results not declared yet");
  });

  test("TC-W8 the file's 404 (no results meeting) and error states; Retry recovers; Scores still from the row", async ({ page }) => {
    let failE = true;
    await setup(page, { file: (s) => (s === "MOCKE" && !failE ? { body: { ...FILE_U1, symbol: "MOCKE", name: "MOCKE Ltd (mock)", row: ROW_E } } : undefined) });
    await openPage(page);
    await page.getByTestId("rtw-open-MOCKX").click();
    await expect(page.getByTestId("results-file-not-found")).toHaveText("No results meeting for MOCKX in the week of Tue 27 Oct: there is no results file to show.", SLOW);
    await expect(page.getByTestId("results-file-scores")).toContainText("70");
    await expect(page.getByTestId("results-file-preview")).toHaveCount(0);
    await page.getByTestId("results-file-close").click();
    await page.getByTestId("rtw-open-MOCKE").click();
    const err = page.getByTestId("results-file-error");
    await expect(err).toBeVisible(SLOW);
    await expect(err).toContainText("The results file didn’t load");
    await expect(page.getByTestId("results-file-verdict-na")).toHaveText("results not declared yet");
    failE = false;
    await err.getByRole("button", { name: /Retry/ }).click();
    await expect(page.getByTestId("results-file-preview")).toBeVisible(SLOW);
    await expect(page.getByTestId("results-file-error")).toHaveCount(0);
  });

  test("TC-W9 list loading and error states; Retry recovers", async ({ page }) => {
    let release!: () => void;
    const gate = new Promise<void>((res) => { release = res; });
    let mode: "gate" | "error" | "ok" = "gate";
    await setup(page, { rw: () => (mode === "gate" ? { body: RW, gate } : mode === "error" ? { status: 502, body: { detail: { code: "upstream_unavailable", message: "results calendar unreadable (mock)" } } } : { body: RW }) });
    await page.goto(PAGE);
    await expect(page.getByTestId("rtw-loading")).toBeVisible(SLOW);
    await expect(page.getByTestId("rtw-list")).toHaveCount(0);
    release();
    await expect(page.getByTestId("rtw-list")).toBeVisible(SLOW);
    // a fresh page, the route fails (502 upstream_unavailable)
    mode = "error";
    await page.goto(PAGE);
    await expect(page.getByTestId("rtw-error")).toBeVisible(SLOW);
    await expect(page.getByTestId("rtw-error")).toContainText("This week’s results didn’t load");
    mode = "ok";
    await page.getByTestId("rtw-error").getByRole("button", { name: /Retry/ }).click();
    await expect(page.getByTestId("rtw-list")).toBeVisible(SLOW);
  });

  test("TC-W10 an older list route without fno_track hides the F&O before → after part", async ({ page }) => {
    await setup(page, { rw: () => ({ body: RW_OLD }) });
    await openPage(page);
    expect(await order(page)).toEqual(EXPECT_FNO);
    await expect(page.locator("[data-testid^='rtw-fno-']")).toHaveCount(0);
    await expect(page.getByTestId("results-this-week")).not.toContainText("F&O before → after");
    await expect(page.getByTestId("rtw-verdict-MOCKA")).toHaveText("Above · Outstanding");
  });

  test("TC-W11 wording on the block: ideas for review, no advice words", async ({ page }) => {
    await setup(page);
    await openPage(page);
    for (const u of ["fno", "all"]) {
      await page.getByTestId(`rtw-seg-${u}`).click();
      const text = await page.getByTestId("results-this-week").innerText();
      for (const b of BANNED) expect(text, `banned wording ${b}`).not.toMatch(b);
    }
    await expect(page.getByTestId("rtw-disclaimer")).toHaveText("For review only; nothing here places an order or is sent to a broker.");
  });
});

test.describe("Results This Week — REAL staging list capture (desktop 1440)", () => {
  test.use({ viewport: { width: 1440, height: 1000 } });

  test("TC-W14 the block renders the real 27 Oct body: F&O order = the fixture's ideas.fno among its F&O rows; no page error", async ({ page }) => {
    const REAL = JSON.parse(fs.readFileSync(path.join(here, "..", "fixtures", "results_week_staging_20261027.json"), "utf8"));
    type R = { symbol: string; fno?: boolean; status?: string; score?: { value?: number | null } };
    type I = { symbol: string; rank?: number };
    const fnoSyms = new Set((REAL.results as R[]).filter((r) => r.fno === true).map((r) => r.symbol));
    const allSyms = new Set((REAL.results as R[]).map((r) => r.symbol));
    const ranked = [...(REAL.ideas.fno as I[])].sort((a, b) => (a.rank ?? 0) - (b.rank ?? 0)).map((i) => i.symbol).filter((s, i, xs) => fnoSyms.has(s) && xs.indexOf(s) === i);
    const rankedAll = [...(REAL.ideas.all as I[])].sort((a, b) => (a.rank ?? 0) - (b.rank ?? 0)).map((i) => i.symbol).filter((s, i, xs) => allSyms.has(s) && xs.indexOf(s) === i);
    expect(ranked.length).toBeGreaterThan(0);
    const errors: string[] = [];
    page.on("pageerror", (e) => errors.push(String(e)));
    await setup(page, { rw: () => ({ body: REAL }) });
    await openPage(page);
    await expect(page.getByTestId("rtw-seg-fno")).toHaveText(`F&O · ${fnoSyms.size}`);
    await expect(page.getByTestId("rtw-seg-all")).toHaveText(`All · ${allSyms.size}`);
    const n = Math.min(ranked.length, 20);
    expect((await order(page)).slice(0, n)).toEqual(ranked.slice(0, n));
    await page.getByTestId("rtw-seg-all").click();
    const m = Math.min(rankedAll.length, 20);
    expect((await order(page)).slice(0, m)).toEqual(rankedAll.slice(0, m));
    // this capture predates fno_track: the part is hidden, not shown empty
    await expect(page.locator("[data-testid^='rtw-fno-']")).toHaveCount(0);
    expect(await over(page)).toBeLessThanOrEqual(0);
    const text = await page.getByTestId("results-this-week").innerText();
    for (const b of BANNED) expect(text, `banned wording ${b}`).not.toMatch(b);
    expect(errors).toEqual([]);
  });
});

test.describe("Results This Week — the desk's Events › Results week opens the same file", () => {
  test.use({ viewport: { width: 1440, height: 1000 } });

  test("TC-W12 from the row drawer's Results file action and from a row's File button; nothing removed", async ({ page }) => {
    const seen = await setup(page);
    await page.goto(EVENTS);
    await page.getByTestId("events-view-rw").click(SLOW);
    await expect(page.getByTestId("results-week-declared")).toBeVisible(SLOW);
    // the existing drawer still opens from the row, and now hands over to the file
    await page.getByTestId("results-week-open-MOCKA").click();
    await expect(page.getByTestId("results-week-drawer")).toBeVisible();
    await expect(page.getByTestId("results-week-drawer-verdict-pill")).toHaveText("Above · Outstanding");
    await page.getByTestId("results-week-drawer-file").click();
    await expect(page.getByTestId("results-week-drawer")).toHaveCount(0);
    await expect(page.getByTestId("results-file")).toHaveAttribute("data-symbol", "MOCKA");
    await expect(page.getByTestId("results-file-result-items")).toBeVisible(SLOW);
    await expect(page.getByTestId("results-file-signal")).toContainText("Signal 78");
    expect(seen.file.some((u) => u.includes("/stock/MOCKA?date=2026-10-27"))).toBe(true);
    await page.getByTestId("results-file-close").click();
    await expect(page.getByTestId("results-file")).toHaveCount(0);
    // a row's own File button, without opening the drawer
    await page.getByTestId("results-week-file-MOCKU1").click();
    await expect(page.getByTestId("results-file")).toHaveAttribute("data-symbol", "MOCKU1");
    await expect(page.getByTestId("results-week-drawer")).toHaveCount(0);
    await expect(page.getByTestId("results-file-pre-items")).toBeVisible(SLOW);
    await page.keyboard.press("Escape");
    await expect(page.getByTestId("results-file")).toHaveCount(0);
  });
});

test.describe("Results This Week — phone 390", () => {
  test.use({ viewport: { width: 390, height: 844 } });

  test("TC-W13 cards, no horizontal page scroll on the list or the file; the track scrolls inside its own box", async ({ page }) => {
    await setup(page, { phone: true });
    await openPage(page);
    await expect(page.getByTestId("rtw-row-MOCKA")).toBeVisible();
    await expect(page.getByTestId("rtw-file-MOCKA")).toBeVisible();
    await expect(page.getByTestId("rtw-fno-MOCKA-after")).toContainText("Rollover 92.6 %");
    expect(await over(page)).toBeLessThanOrEqual(0);
    await page.getByTestId("rtw-seg-all").click();
    expect(await over(page)).toBeLessThanOrEqual(0);
    await page.getByTestId("rtw-seg-fno").click();
    await page.getByTestId("rtw-file-MOCKA").click();
    await expect(page.getByTestId("results-file-track-table")).toBeVisible(SLOW);
    // before and after stack on a phone
    const b = (await page.getByTestId("results-file-track-before").boundingBox())!;
    const a = (await page.getByTestId("results-file-track-after").boundingBox())!;
    expect(a.y).toBeGreaterThan(b.y + b.height - 1);
    expect(await over(page)).toBeLessThanOrEqual(0);
    const box = await page.getByTestId("results-file").boundingBox();
    expect(box!.x).toBeGreaterThanOrEqual(0);
    expect(box!.x + box!.width).toBeLessThanOrEqual(390);
  });
});

// ── screenshots (only with RTW_SHOTS; run with network so fonts load) ─────
test.describe("Results This Week — screenshots", () => {
  test.skip(!SHOTS, "RTW_SHOTS not set");
  // The app scrolls inside its own frame: a tall viewport shows the whole block for the list shot.
  for (const [w, h, tall, tag] of [[1440, 1000, 1800, "1440"], [390, 844, 4200, "390"]] as const) {
    test(`shots ${tag}`, async ({ page }) => {
      await page.setViewportSize({ width: w, height: tall });
      await setup(page);
      await openPage(page);
      await page.evaluate(() => document.fonts.ready);
      const block = page.getByTestId("results-this-week");
      await block.scrollIntoViewIfNeeded();
      await expect(page.getByTestId("rtw-booster-MOCKA-chip")).toBeVisible(SLOW);
      await page.locator("section", { has: block }).screenshot({ path: `${SHOTS}/results-this-week-list-${tag}.png` });
      await page.setViewportSize({ width: w, height: h });
      await page.getByTestId("rtw-open-MOCKA").click();
      await expect(page.getByTestId("results-file-result-items")).toBeVisible(SLOW);
      await page.screenshot({ path: `${SHOTS}/results-file-top-${tag}.png` });
      await page.getByTestId("results-file-result").scrollIntoViewIfNeeded();
      await page.screenshot({ path: `${SHOTS}/results-file-result-${tag}.png` });
      await page.getByTestId("results-file-track").scrollIntoViewIfNeeded();
      await page.screenshot({ path: `${SHOTS}/results-file-track-${tag}.png` });
      await page.getByTestId("results-file-scores").scrollIntoViewIfNeeded();
      await page.screenshot({ path: `${SHOTS}/results-file-scores-${tag}.png` });
    });
  }
});
