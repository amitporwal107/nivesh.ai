/**
 * Smart trading desk — Earnings Surprise & Guidance Tracker, Phase 1 frontend (docs/EARNINGS_SURPRISE_TRACKER.md §6, §8
 * TC-F1 … TC-F6): Events › View › RESULTS WEEK and Scanner › Results week ideas.
 *
 * MOCK — not real data: every route below is answered with an inline payload in the shape of the §5 contract
 * (GET /api/desk/results-week) or of the desk's existing routes (GET /api/markets/home, /api/markets/sector-returns,
 * /api/markets/macro-calendar, /api/markets/events-calendar…). Symbols are MOCK*, figures are synthetic, and every
 * expected value below is worked out from these payloads, not copied from the screen. Mocked APIs, production build —
 * see pw.copilot-app.config.ts. The clock is fixed at Tue 27 Oct 2026, 11:30 IST.
 *
 * Screenshots (1440 px and 390 px, both views) are taken only when RW_SHOTS names a directory, in a run that lets
 * fonts load; the TC run itself is offline.
 */
import { test, expect, type Page, type Route } from "@playwright/test";
import { mockApi } from "../helpers/api-mock";

const DESK = "/v5/app/trader/desk";
const EVENTS = `${DESK}?tab=events`;
const SLOW = { timeout: 15_000 };
const SHOTS = process.env.RW_SHOTS || "";
const json = (route: Route, body: unknown, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
const NOTE = "Ordered for review, not a prediction. This ordering has not been tested yet.";

// ── MOCK — not real data: GET /api/desk/results-week (spec §5) ────────────
const rng = (low: number, mid: number, high: number) => ({ low, mid, high });
const metric = (key: string, expected: unknown, filed: number | null, extra: Record<string, unknown> = {}) => ({
  key, unit: "cr", expected, filed, vs_mid_pct: null, z: null, verdict: null, reliable: expected != null, ...extra,
});
const row = (symbol: string, event_date: string, status: string, fno: boolean, extra: Record<string, unknown> = {}) => ({
  symbol, name: `${symbol} Ltd (mock)`, sector: fno ? "Capital Goods" : "Consumer", event_date, status, fno, period_label: "Q2 FY2027",
  basis: "historical_trend",
  verdict: { label: null, intensity: null, reason: null },
  score: { value: null, band: null, coverage: { present: [], missing: [] } },
  components: { surprise: null, trend: null, outlook: null, quality: null },
  reaction: null, fno_buildup: null, technical: null, chartink: null, evidence: [], gaps: [],
  ...extra,
});
const RESULTS = [
  row("MOCKA", "2026-10-26", "declared", true, {
    verdict: { label: "above", intensity: "outstanding", reason: "PAT 2.5 band-widths above the baseline mid (mock)" },
    score: { value: 82, band: "above", coverage: { present: ["surprise", "trend", "outlook", "quality"], missing: [] } },
    // the committed backend's shapes (services/results_week/scoring.py: surprise / trend / quality / outlook / reaction)
    components: {
      surprise: { value: 88, used: ["pat", "revenue"], weights: { pat: 0.6, revenue: 0.4 }, z: 1.9, metrics: {
        pat: metric("pat", rng(1100, 1200, 1300), 1450, { vs_mid_pct: 20.8, z: 2.5, verdict: "above", intensity: "outstanding", score: 100 }),
        revenue: metric("revenue", rng(9000, 9400, 9800), 9800, { vs_mid_pct: 4.3, z: 1.0, verdict: "in_line", score: 75 }),
      } },
      trend: { value: 74, quarter: "2026-09-30", yoy_pct: { revenue: 12.1, ebitda: 18.0, pat: 28.5 }, qoq_pct: { revenue: 3.4, ebitda: 5.1, pat: 9.2 }, ebitda_margin_pct: 21.0, ebitda_margin_change_pp: 1.2, missing: [] },
      outlook: { value: 73, label: "filing analysis, not a guidance tracker", analysed: true, net_impact_score: 46, net_band: "moderately_positive", confidence_score: 70, summary: "Order book and margins guided higher (mock).", reason: null },
      quality: { value: 100, flags: [], checked: ["exceptional_items", "other_income", "tax_rate", "profit_vs_revenue"], not_checked: ["cash_flow: not stored"] },
    },
    reaction: { filed_at: "2026-10-26T18:40:00+05:30", filed_after_close: true, first_session: "2026-10-27", previous_session: "2026-10-26", stock_return_pct: 5.1, nifty_return_pct: -0.5, excess_pct: 5.6, volume_x: 3.2, score: 100 },
    // The coming-months F&O block (coordinator, 27 Oct): `total` is the headline; by expiry, rollover, next-expiry options.
    fno_buildup: {
      as_of: "2026-10-26", state: "long_buildup", text: "long build-up", price_chg_pct: 2.1, oi_chg_pct: 8.4,
      total: { state: "long_buildup", positions: "fresh", price_pct: { "1": 2.1, "3": 4.8 }, oi_pct: { "1": 9.6, "3": 14.2 } },
      by_expiry: [
        { leg: "near", expiry: "2026-10-28", price_pct: 2.1, oi_pct: -12.0, basis_pct: 0.18, state: "long_unwinding" },
        { leg: "next", expiry: "2026-11-25", price_pct: 2.3, oi_pct: 41.0, basis_pct: 0.62, state: "long_buildup" },
        { leg: "far", expiry: "2026-12-30", price_pct: null, oi_pct: null, basis_pct: null, state: null },
      ],
      rollover: { pct: 72.4, own_range: [55.0, 80.0], next_premium_pct: 0.62, premium_range: [0.3, 0.9] },
      options_next_expiry: { expiry: "2026-11-25", pcr: 0.43, pcr_prev: 0.71, put_oi_added: 120000, call_oi_added: 340000, max_put_strike: 2200, max_call_strike: 2500, most_put_added_strike: 2280, most_call_added_strike: 2500, note: null },
    },
    technical: { stage: "breakout_watch", score: 61 },
    chartink: { scans: ["Volume shocker", "52w high"], scan_date: "2026-10-26" },
    evidence: [{ label: "Outcome of board meeting (mock)", url: "https://www.nseindia.com/mock-a" }],
  }),
  row("MOCKB", "2026-10-26", "declared", false, {
    verdict: { label: "in_line", intensity: null, reason: null },
    score: { value: 55, band: "in_line", coverage: { present: ["surprise", "trend", "quality"], missing: ["outlook"] } },
    components: {
      surprise: { metrics: [metric("pat", rng(200, 220, 240), 226, { vs_mid_pct: 2.7, z: 0.3, verdict: "in_line" }), metric("revenue", rng(1500, 1600, 1700), 1580, { vs_mid_pct: -1.3, z: -0.2, verdict: "in_line" })] },
      trend: { revenue_yoy_pct: 6.0, revenue_qoq_pct: 1.0, pat_yoy_pct: 4.0, pat_qoq_pct: -2.0 },
      outlook: null,
      quality: { value: 85, flags: [{ code: "other_income", text: "other income is 34 % of PBT (over 30 %)", value_pct: 34 }], checked: ["other_income", "tax_rate"], not_checked: ["cash_flow: not stored"] },
    },
    reaction: { excess_vs_nifty_pct: -0.8, stock_pct: -1.3, nifty_pct: -0.5, session: "2026-10-27" },
    chartink: { scans: [], scan_date: "2026-10-26" },
  }),
  row("MOCKC", "2026-10-26", "declared", true, {
    verdict: { label: null, intensity: null, reason: "not rated: no reliable baseline" },
    score: { value: null, band: null, coverage: { present: ["quality"], missing: ["surprise", "trend", "outlook"] } },
    components: { surprise: { metrics: [metric("pat", null, 210, { reliable: false, note: "Profit near zero in the base quarter (mock)." })] }, trend: null, outlook: null, quality: { value: 100, flags: [], checked: ["tax_rate"], not_checked: ["cash_flow: not stored"] } },
    gaps: ["Quarterly history short: 3 quarters on file (mock gap)"],
  }),
  row("MOCKD", "2026-10-27", "declared", true, {
    verdict: { label: "below", intensity: "well_below", reason: "PAT 2.4 band-widths below the baseline mid (mock)" },
    score: { value: 31, band: "below", coverage: { present: ["surprise", "trend", "outlook", "quality"], missing: [] } },
    components: {
      surprise: { metrics: [metric("pat", rng(300, 340, 380), 244, { vs_mid_pct: -28.2, z: -2.4, verdict: "below" }), metric("revenue", rng(2000, 2100, 2200), 1990, { vs_mid_pct: -5.2, z: -1.1, verdict: "below" })] },
      trend: { revenue_yoy_pct: -3.0, revenue_qoq_pct: -1.0, pat_yoy_pct: -22.0, pat_qoq_pct: -15.0 },
      outlook: { net_impact_score: -40, net_band: "moderately_negative" },
      quality: { value: 100, flags: [], checked: ["tax_rate"], not_checked: [] },
    },
    reaction: { excess_vs_nifty_pct: -4.1, stock_pct: -4.6, nifty_pct: -0.5, session: "2026-10-27" },
    fno_buildup: { state: "short_buildup", date: "2026-10-26" },
  }),
  row("MOCKP", "2026-10-27", "pending", true, { gaps: ["Figures not in the warehouse yet (mock gap)"] }),
  row("MOCKU1", "2026-10-28", "upcoming", true, {
    components: {
      surprise: { value: null, metrics: { pat: metric("pat", rng(500, 540, 580), null), revenue: metric("revenue", rng(4000, 4200, 4400), null) } },
      trend: null, outlook: null, quality: { value: null, flags: [], checked: [], not_checked: [], reason: "results not declared yet" },
      past_reactions: { n: 8, mean_two_session_pct: 1.6, score: 66, stats: { event_day: { avg: 1.2, min: -2.0, max: 4.0 }, d1: { avg: 0.4 }, w1: { avg: 2.4 } } },
    },
    fno_buildup: { state: "short_covering", date: "2026-10-26" },
    technical: { stage: "setup_forming", score: 58 },
  }),
  row("MOCKU2", "2026-10-29", "upcoming", false, {
    components: { surprise: { metrics: [metric("pat", null, null, { reliable: false }), metric("revenue", rng(800, 850, 900), null)] }, trend: null, outlook: null, quality: null },
  }),
  row("MOCKU3", "2026-10-29", "upcoming", true),
];
const RW = {
  date: "2026-10-27", as_of: "2026-10-27T11:20:00+05:30", week: { from: "2026-10-26", to: "2026-10-31" },
  basis: "historical_trend", consensus_available: false,
  label: "vs historical trend (the company's own past quarters), not analyst consensus",
  counts: { declared: 4, declared_pending: 1, upcoming: 3, above: 1, in_line: 1, below: 1, not_rated: 1 },
  results: RESULTS,
  ideas: {
    fno: [
      { rank: 1, symbol: "MOCKA", phase: "declared", signal: 78.4, parts: { earnings: { value: 82, weight: 40 }, reaction: { value: 74, weight: 20 }, oi: { value: 70, weight: 20 }, technical: { value: 61, weight: 20 } }, missing: [], why: "Above trend on PAT (+20.8% vs mid); long build-up (mock)" },
      { rank: 2, symbol: "MOCKU1", phase: "upcoming", signal: 64, parts: { technical: 58, oi: 66, past_reactions: 70, trend: null }, why: ["Short covering into results", "Past results averaged +2.4% in a week (mock)"] },
    ],
    all: [
      { rank: 1, symbol: "MOCKA", phase: "declared", signal: 80.1, parts: { earnings: 82, reaction: 74, technical: 61 }, why: "Above trend (mock)" },
      { rank: 2, symbol: "MOCKB", phase: "declared", signal: 52.0, parts: { earnings: 55, reaction: 46, technical: 50 }, why: "In line (mock)" },
      { rank: 3, symbol: "MOCKU2", phase: "upcoming", signal: 41.5, parts: { technical: 40, past_reactions: null, trend: 45 }, why: "No reliable PAT baseline (mock)" },
    ],
    note: NOTE,
  },
  sources: { results: "DaaS events-calendar expectations (mock)", quarterly: "DaaS financials (mock)" },
  gaps: ["Cash flow statements are empty on staging: quality checks skip them (mock gap)"],
};
const EMPTY_RW = { ...RW, counts: { declared: 0, declared_pending: 0, upcoming: 0, above: 0, in_line: 0, below: 0, not_rated: 0 }, results: [], ideas: { fno: [], all: [], note: NOTE }, gaps: [] };

// ── MOCK — not real data: the desk's existing routes the view composes ────
const HOME = {
  ok: true, as_of: "2026-10-27T10:00:00+05:30", is_live: false, market_state: "closed", fetched_at: "2026-10-27T10:00:00+05:30",
  indices: [
    { name: "Nifty 50", value: 25480.5, change: 120.3, change_pct: 0.47, is_vix: false, spark: [], as_of: "2026-10-26" },
    { name: "Nifty Bank", value: 57210, change: -85.2, change_pct: -0.15, is_vix: false, spark: [], as_of: "2026-10-26" },
    { name: "India VIX", value: 12.84, change: 0.3, change_pct: 2.4, is_vix: true, spark: [], as_of: "2026-10-26" },
  ],
  breadth: { advances: 1800, declines: 1100, unchanged: 90, universe: 2990, universe_kind: "bhavcopy", tone: "positive" },
  gainers: [], losers: [], sectors: [], news: [], global_cues: [], commodities: [],
  fii_dii: { as_of: "2026-10-26", fii_net_cr: -1520.4, dii_net_cr: 2210.9 },
};
const SECTORS = { as_of: "2026-10-26", source: "NSE index close (mock)", sessions: { "1d": 1, "1w": 5, "1m": 21 }, sectors: [
  { index: "Nifty IT", sector: "IT", date: "2026-10-26", close: 35210.5, ret_1d_pct: 1.42, ret_1w_pct: -0.8, ret_1m_pct: 3.1 },
  { index: "Nifty Auto", sector: "Auto", date: "2026-10-26", close: 24000.0, ret_1d_pct: 0.3, ret_1w_pct: 1.9, ret_1m_pct: -2.2 },
  { index: "Nifty Realty", sector: "Realty", date: "2026-10-26", close: 980.4, ret_1d_pct: -1.6, ret_1w_pct: -3.05, ret_1m_pct: 4.4 },
] };
const mac = (id: string, date: string, time: string | null, country: string, impact: string, name: string, extra: Record<string, unknown> = {}) => ({
  id, date, time, country, impact, name, short: name.split(" ")[0], code: id, period: "Sep 2026", previous: null, estimate: null, actual: null, unit: "%", source: "MOCK", source_url: null, ...extra,
});
const MACRO = { month: "2026-10", as_of: "2026-10-27", holidays: [], index_closes: [], gaps: [], countries: [], events: [
  mac("m-iip", "2026-10-28", "16:00", "IN", "M", "Industrial production (IIP)", { previous: "4.0" }),
  mac("m-fomc", "2026-10-29", "23:30", "US", "H", "FOMC rate decision", { previous: "4.25" }),
  mac("m-old", "2026-10-21", "18:00", "US", "H", "Retail sales outside the week"),
] };
const CAL = { month: "2026-10", as_of: "2026-10-26", events: [], holidays: [], index_closes: [], gaps: [] };
const BOARD = { from: "2026-10-27", to: "2026-10-28", as_of: "2026-10-27", count: 0, counts: {}, events: [], gaps: [] };
const HIST = { symbol: "MOCKA", type: "RESULTS", coverage_from: "2025-01-01", n: 2, basis: "mock",
  occurrences: [{ date: "2026-07-25", event_day_pct: 3.1, d1_pct: 0.4, w1_pct: 4.2 }, { date: "2026-04-25", event_day_pct: -1.1, d1_pct: 0.2, w1_pct: 0.6 }],
  stats: { event_day: { avg: 1.0, min: -1.1, max: 3.1 }, d1: { avg: 0.3, min: 0.2, max: 0.4 }, w1: { avg: 2.4, min: 0.6, max: 4.2 } } };

type RwAnswer = { status?: number; body?: unknown; gate?: Promise<void> };
async function setup(page: Page, rw: () => RwAnswer = () => ({ body: RW }), urls: string[] = []) {
  await mockApi(page, "populated");
  await page.clock.setFixedTime(new Date("2026-10-27T06:00:00Z"));
  await page.route("**/api/chat/sessions", (r) => json(r, []));
  await page.route("**/api/markets/home", (r) => json(r, HOME));
  await page.route("**/api/markets/sector-returns", (r) => json(r, SECTORS));
  await page.route("**/api/markets/macro-calendar?*", (r) => json(r, MACRO));
  await page.route("**/api/markets/events-calendar?*", (r) => json(r, CAL));
  await page.route("**/api/markets/events-calendar/expectations*", (r) => json(r, BOARD));
  await page.route("**/api/markets/events-calendar/history*", (r) => json(r, HIST));
  await page.route("**/api/desk/results-week*", async (r) => {
    urls.push(r.request().url());
    const a = rw();
    if (a.gate) await a.gate;
    return json(r, a.body ?? { detail: "mock failure" }, a.status ?? 200);
  });
}

async function openResultsWeek(page: Page) {
  await page.goto(EVENTS);
  await page.getByTestId("events-view-rw").click(SLOW);
  await expect(page.getByTestId("results-week")).toBeVisible(SLOW);
}

const BANNED = ["beat", "recommend", "pick", "suggest", "outperform", "buy now"];

test.describe("Results week — Events view (desktop 1440)", () => {
  test.use({ viewport: { width: 1440, height: 1000 } });

  test("TC-F1 basis label and counts; macro this week and the market strip from the desk's own reads", async ({ page }) => {
    const urls: string[] = [];
    await setup(page, () => ({ body: RW }), urls);
    await openResultsWeek(page);
    await expect(page.getByTestId("results-week-basis")).toContainText("vs historical trend — the company’s own past quarters, not analyst consensus", { ignoreCase: true });
    await expect(page.getByTestId("results-week-counts")).toBeVisible(SLOW);
    const count = (k: string) => page.getByTestId(`results-week-count-${k}`);
    await expect(count("declared")).toContainText("4");
    await expect(count("pending")).toContainText("1");
    await expect(count("upcoming")).toContainText("3");
    await expect(count("above")).toContainText("1");
    await expect(count("in-line")).toContainText("1");
    await expect(count("below")).toContainText("1");
    await expect(count("not-rated")).toContainText("1");
    expect(urls[0]).toContain("/api/desk/results-week?date=2026-10-27");
    // macro: the two releases inside 26–31 Oct, not the one on 21 Oct
    const macro = page.getByTestId("results-week-macro");
    await expect(macro).toContainText("Industrial production (IIP)");
    await expect(macro).toContainText("FOMC rate decision");
    await expect(macro).not.toContainText("Retail sales outside the week");
    // market strip
    await expect(page.getByTestId("results-week-market-nifty-50")).toContainText("25,480.50");
    await expect(page.getByTestId("results-week-market-flows")).toContainText("FII");
    await expect(page.getByTestId("results-week-market-sectors")).toContainText("IT");
    await expect(page.getByTestId("results-week-market-sectors")).toContainText("Realty");
    await expect(page.getByTestId("results-week-gaps")).toContainText("Cash flow statements are empty");
    const text = (await page.getByTestId("results-week").innerText()).toLowerCase();
    for (const w of BANNED) expect(text, `banned word "${w}"`).not.toContain(w);
  });

  test("TC-F2 declared rows: verdict pill, PAT surprise, reaction; pending says figures not filed yet; the drawer", async ({ page }) => {
    await setup(page);
    await openResultsWeek(page);
    const declared = page.getByTestId("results-week-declared");
    await expect(declared).toBeVisible(SLOW);
    await expect(page.getByTestId("results-week-verdict-MOCKA")).toHaveText("Above · Outstanding");
    await expect(page.getByTestId("results-week-vsmid-MOCKA-pat")).toHaveText("+20.8%");
    await expect(page.getByTestId("results-week-vsmid-MOCKA-revenue")).toHaveText("+4.3%");
    await expect(page.getByTestId("results-week-reaction-MOCKA")).toContainText("+5.6%");
    await expect(page.getByTestId("results-week-reaction-MOCKA")).toContainText("vs Nifty");
    await expect(page.getByTestId("results-week-reaction-MOCKA")).toContainText("3.2× vol");
    await expect(page.getByTestId("results-week-growth-MOCKA")).toContainText("+28.5%");
    await expect(page.getByTestId("results-week-outlook-MOCKA")).toContainText("moderately positive");
    await expect(page.getByTestId("results-week-chartink-MOCKA")).toContainText("Volume shocker");
    await expect(page.getByTestId("results-week-oi-MOCKA")).toHaveText("Fresh long build-up · OI +9.6%");
    await expect(page.getByTestId("results-week-oi-MOCKD")).toHaveText("Short build-up");
    await expect(page.getByTestId("results-week-oi-MOCKB")).toHaveText("not F&O");
    await expect(page.getByTestId("results-week-verdict-MOCKB")).toHaveText("In line");
    await expect(page.getByTestId("results-week-outlook-MOCKB")).toHaveText("not analysed");
    await expect(page.getByTestId("results-week-quality-MOCKB")).toContainText("1 flag");
    await expect(page.getByTestId("results-week-quality-MOCKB")).toHaveAttribute("title", "other income is 34 % of PBT (over 30 %)");
    await expect(page.getByTestId("results-week-verdict-MOCKC")).toHaveText("Not rated");
    await expect(page.getByTestId("results-week-vsmid-MOCKC-pat")).toHaveText("no baseline");
    await expect(page.getByTestId("results-week-reaction-MOCKC")).toHaveText("not available");
    await expect(page.getByTestId("results-week-verdict-MOCKD")).toHaveText("Well below");
    await expect(page.getByTestId("results-week-vsmid-MOCKD-pat")).toHaveText("−28.2%");
    // pending
    await expect(page.getByTestId("results-week-pending-note-MOCKP")).toHaveText("Figures not filed yet");
    await expect(page.getByTestId("results-week-row-MOCKP")).toHaveAttribute("data-status", "pending");
    // verdict filter
    await page.getByTestId("results-week-verdict-filter-below").click();
    await expect(page.getByTestId("results-week-row-MOCKD")).toBeVisible();
    await expect(page.getByTestId("results-week-row-MOCKA")).toHaveCount(0);
    await page.getByTestId("results-week-verdict-filter-all").click();
    // the drawer, by keyboard
    await page.getByTestId("results-week-open-MOCKA").focus();
    await page.keyboard.press("Enter");
    const drawer = page.getByTestId("results-week-drawer");
    await expect(drawer).toBeVisible();
    await expect(drawer).toHaveAttribute("role", "dialog");
    await expect(page.getByTestId("results-week-drawer-close")).toBeFocused();
    await expect(page.getByTestId("results-week-drawer-verdict-pill")).toHaveText("Above · Outstanding");
    await expect(page.getByTestId("results-week-drawer-score")).toContainText("82");
    await expect(page.getByTestId("results-week-drawer-coverage")).toContainText("Surprise vs historical trend");
    await expect(page.getByTestId("results-week-drawer-metric-pat")).toContainText("₹1,450 cr");
    await expect(page.getByTestId("results-week-drawer-outlook")).toContainText("FILING ANALYSIS, NOT A GUIDANCE TRACKER", { ignoreCase: true });
    await expect(page.getByTestId("results-week-drawer-quality")).toContainText("Not checked: cash flow: not stored.");
    await expect(page.getByTestId("results-week-drawer-fno-headline")).toHaveText("Fresh long build-up · OI +9.6%");
    await expect(page.getByTestId("results-week-drawer-past")).toContainText("Based on 2 past results");
    await expect(page.getByTestId("results-week-drawer-evidence").getByRole("link", { name: "Outcome of board meeting (mock)" })).toHaveAttribute("href", "https://www.nseindia.com/mock-a");
    // Tab stays inside the dialog
    await page.keyboard.press("Shift+Tab");
    expect(await page.evaluate(() => !!document.activeElement?.closest("[data-testid='results-week-drawer']"))).toBe(true);
    await page.keyboard.press("Escape");
    await expect(drawer).toHaveCount(0);
    await expect(page.getByTestId("results-week-open-MOCKA")).toBeFocused();
    // a not-rated row: missing parts say so, never a number
    await page.getByTestId("results-week-open-MOCKC").click();
    await expect(page.getByTestId("results-week-drawer-coverage")).toContainText("Operating trend · missing");
    await expect(page.getByTestId("results-week-drawer-metric-pat")).toContainText("no reliable baseline");
    await expect(page.getByTestId("results-week-drawer-outlook-na")).toHaveText("not analysed");
    await expect(page.getByTestId("results-week-drawer-gaps")).toContainText("Quarterly history short");
    await page.getByTestId("results-week-drawer-close").click();
    await expect(drawer).toHaveCount(0);
  });

  test("TC-F7 drawer › F&O: coming months — expiries, rollover and premium vs their ranges, the option-chain line; null parts say so", async ({ page }) => {
    await setup(page);
    await openResultsWeek(page);
    await page.getByTestId("results-week-open-MOCKA").click(SLOW);
    const fno = page.getByTestId("results-week-drawer-fno");
    await expect(fno).toBeVisible();
    await expect(fno).toContainText("Open interest · 1 / 3 sessions");
    await expect(fno).toContainText("+14.2%");
    const near = page.getByTestId("results-week-drawer-fno-leg-near");
    await expect(near).toContainText("Wed 28 Oct");
    await expect(near).toContainText("−12.0%");
    await expect(near).toContainText("+0.18%");
    await expect(near).toContainText("Long unwinding");
    await expect(page.getByTestId("results-week-drawer-fno-leg-next")).toContainText("+41.0%");
    await expect(page.getByTestId("results-week-drawer-fno-leg-next")).toContainText("Long build-up");
    await expect(page.getByTestId("results-week-drawer-fno-leg-far")).toContainText("n/a");
    await expect(page.getByTestId("results-week-drawer-fno-rollover")).toHaveText("72.4% (range 55.0%–80.0%)");
    await expect(page.getByTestId("results-week-drawer-fno-premium")).toHaveText("0.62% (range 0.30%–0.90%)");
    await expect(page.getByTestId("results-week-drawer-fno-options")).toHaveText("Nov: PCR 0.71→0.43 · puts added most at 2,280 · calls at 2,500 · open interest cannot tell buyers from writers");
    await page.getByTestId("results-week-drawer-close").click();
    // only the headline state on file: every other part says not available
    await page.getByTestId("results-week-open-MOCKD").click();
    await expect(page.getByTestId("results-week-drawer-fno-headline")).toHaveText("Short build-up");
    await expect(page.getByTestId("results-week-drawer-fno-expiries")).toContainText("expiry-wise futures not available");
    await expect(page.getByTestId("results-week-drawer-fno-rollover")).toHaveText("not available");
    await expect(page.getByTestId("results-week-drawer-fno-premium")).toHaveText("not available");
    await expect(page.getByTestId("results-week-drawer-fno-options")).toHaveText("Next expiry options: not available");
    await page.getByTestId("results-week-drawer-close").click();
    // a non-F&O stock
    await page.getByTestId("results-week-open-MOCKB").click();
    await expect(page.getByTestId("results-week-drawer-fno")).toContainText("not an F&O stock");
  });

  test("TC-F3 upcoming rows: expected range, or no reliable baseline; past reactions, OI and stage", async ({ page }) => {
    await setup(page);
    await openResultsWeek(page);
    await expect(page.getByTestId("results-week-upcoming")).toBeVisible(SLOW);
    await expect(page.getByTestId("results-week-expected-MOCKU1-pat")).toHaveText("₹500 cr – ₹580 cr");
    await expect(page.getByTestId("results-week-expected-MOCKU1-revenue")).toHaveText("₹4,000 cr – ₹4,400 cr");
    await expect(page.getByTestId("results-week-past-MOCKU1")).toContainText("+1.2%");
    await expect(page.getByTestId("results-week-past-MOCKU1")).toContainText("+2.4%");
    await expect(page.getByTestId("results-week-oi-MOCKU1")).toHaveText("Short covering");
    await expect(page.getByTestId("results-week-stage-MOCKU1")).toHaveText("setup forming");
    await expect(page.getByTestId("results-week-expected-MOCKU2-pat")).toHaveText("no reliable baseline");
    await expect(page.getByTestId("results-week-expected-MOCKU2-revenue")).toHaveText("₹800 cr – ₹900 cr");
    await expect(page.getByTestId("results-week-past-MOCKU2")).toHaveText("not available");
    await expect(page.getByTestId("results-week-oi-MOCKU2")).toHaveText("not F&O");
    await expect(page.getByTestId("results-week-expected-MOCKU3-pat")).toHaveText("no reliable baseline");
    await expect(page.getByTestId("results-week-expected-MOCKU3-revenue")).toHaveText("no reliable baseline");
    await expect(page.getByTestId("results-week-oi-MOCKU3")).toHaveText("not available");
    await expect(page.getByTestId("results-week-upcoming-day-2026-10-28")).toContainText("Wed 28 Oct · 1 result");
    await expect(page.getByTestId("results-week-upcoming-day-2026-10-29")).toContainText("Thu 29 Oct · 2 results");
    // F&O universe keeps F&O names only
    await page.getByTestId("results-week-universe-fno").click();
    await expect(page.getByTestId("results-week-row-MOCKU2")).toHaveCount(0);
    await expect(page.getByTestId("results-week-row-MOCKU3")).toBeVisible();
    // the view switch goes back to the calendar
    await page.getByTestId("events-view-cal").click();
    await expect(page.getByTestId("results-week")).toHaveCount(0);
    await expect(page.getByTestId("events-month")).toBeVisible();
  });

  test("TC-F5 loading, empty and error states (the basis label stays on screen)", async ({ page }) => {
    let release!: () => void;
    const gate = new Promise<void>((r) => { release = r; });
    let mode: "gate" | "error" | "ok" | "empty" = "gate";
    await setup(page, () => (mode === "gate" ? { body: RW, gate } : mode === "error" ? { status: 500 } : mode === "empty" ? { body: EMPTY_RW } : { body: RW }));
    await openResultsWeek(page);
    await expect(page.getByTestId("results-week-loading")).toBeVisible();
    await expect(page.getByTestId("results-week-basis")).toBeVisible();
    release();
    await expect(page.getByTestId("results-week-counts")).toBeVisible(SLOW);
    // error: a fresh page, the route fails
    mode = "error";
    await openResultsWeek(page);
    await expect(page.getByTestId("results-week-error")).toBeVisible(SLOW);
    await expect(page.getByTestId("results-week-basis")).toBeVisible();
    await expect(page.getByTestId("results-week-counts")).toHaveCount(0);
    // retry recovers
    mode = "ok";
    await page.getByTestId("results-week-error").getByRole("button", { name: /Retry/ }).click();
    await expect(page.getByTestId("results-week-counts")).toBeVisible(SLOW);
    // empty week
    mode = "empty";
    await openResultsWeek(page);
    await expect(page.getByTestId("results-week-empty")).toHaveText("No results meetings on file for this week.", SLOW);
    await expect(page.getByTestId("results-week-count-declared")).toContainText("0");
    // the Scanner block in the same three states
    mode = "error";
    await openResultsWeek(page);
    await expect(page.getByTestId("results-week-ideas-error")).toBeVisible(SLOW);
    mode = "empty";
    await page.getByTestId("results-week-ideas-error").getByRole("button", { name: /Retry/ }).click();
    await expect(page.getByTestId("results-week-ideas-empty")).toBeVisible(SLOW);
    await expect(page.getByTestId("results-week-ideas-note")).toContainText(NOTE);
  });
});

test.describe("Results week — Scanner ideas (desktop 1440)", () => {
  test.use({ viewport: { width: 1440, height: 1000 } });

  test("TC-F4 Results week ideas below the Results week view: F&O | All toggle, rows, the not-yet-tested note", async ({ page }) => {
    await setup(page);
    await openResultsWeek(page);
    const box = page.getByTestId("results-week-ideas");
    await expect(box).toBeVisible(SLOW);
    // in the Results week view, below its results (the owner's Market Overview / AI Scanner structure stays as drawn)
    const view = page.getByTestId("results-week");
    expect((await view.boundingBox())!.y).toBeLessThan((await box.boundingBox())!.y);
    await expect(page.getByTestId("results-week-ideas-untested")).toHaveText("NOT YET TESTED");
    await expect(page.getByTestId("results-week-ideas-toggle-fno")).toHaveAttribute("aria-pressed", "true");
    const rows = page.getByTestId("results-week-ideas-list").locator(":scope > li");
    await expect(rows).toHaveCount(2, SLOW);
    const a = page.getByTestId("results-week-idea-MOCKA");
    await expect(a.getByTestId("results-week-idea-rank")).toHaveText("01");
    await expect(a.getByTestId("results-week-idea-phase")).toHaveText("Declared");
    await expect(a.getByTestId("results-week-idea-signal")).toHaveText("Signal 78");
    await expect(a.getByTestId("results-week-idea-parts")).toContainText("OI build-up 70");
    await expect(a.getByTestId("results-week-idea-why")).toContainText("long build-up");
    const u1 = page.getByTestId("results-week-idea-MOCKU1");
    await expect(u1.getByTestId("results-week-idea-phase")).toHaveText("Upcoming");
    await expect(u1.getByTestId("results-week-idea-parts")).toContainText("Operating trend n/a");
    await expect(u1.getByTestId("results-week-idea-why")).toContainText("Short covering into results · Past results");
    // All: three names, no OI part
    await page.getByTestId("results-week-ideas-toggle-all").click();
    await expect(rows).toHaveCount(3);
    await expect(page.getByTestId("results-week-ideas-list")).not.toContainText("OI build-up");
    await expect(page.getByTestId("results-week-idea-MOCKU2").getByTestId("results-week-idea-rank")).toHaveText("03");
    await expect(page.getByTestId("results-week-ideas-note")).toContainText(NOTE);
    const text = (await box.innerText()).toLowerCase();
    for (const w of BANNED) expect(text, `banned word "${w}"`).not.toContain(w);
  });
});

test.describe("Results week — phone 390", () => {
  test.use({ viewport: { width: 390, height: 844 } });

  test("TC-F6 no horizontal page scroll: Events › Results week, its drawer, and the Scanner ideas", async ({ page }) => {
    await setup(page);
    await page.goto(EVENTS);
    await page.getByTestId("events-view-rw").click(SLOW);
    await expect(page.getByTestId("results-week")).toBeVisible(SLOW);
    await expect(page.getByTestId("results-week-declared-cards")).toBeVisible(SLOW);
    await expect(page.getByTestId("results-week-verdict-MOCKA")).toHaveText("Above · Outstanding");
    const over = () => page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    expect(await over()).toBeLessThanOrEqual(0);
    await page.getByTestId("results-week-open-MOCKD").click();
    await expect(page.getByTestId("results-week-drawer")).toBeVisible();
    expect(await over()).toBeLessThanOrEqual(0);
    await page.getByTestId("results-week-drawer-close").click();
    await openResultsWeek(page);
    await expect(page.getByTestId("results-week-ideas-list")).toBeVisible(SLOW);
    expect(await over()).toBeLessThanOrEqual(0);
  });
});

// ── screenshots (only with RW_SHOTS; run with network so fonts load) ──────
test.describe("Results week — screenshots", () => {
  test.skip(!SHOTS, "RW_SHOTS not set");
  // The desk scrolls inside its own frame, so a full-page shot stops at the viewport: a tall viewport shows the whole view.
  for (const [w, h, tall, tag] of [[1440, 1000, 3000, "1440"], [390, 844, 5600, "390"]] as const) {
    test(`shots ${tag}`, async ({ page }) => {
      await page.setViewportSize({ width: w, height: tall });
      await setup(page);
      await openResultsWeek(page);
      await expect(page.getByTestId("results-week-counts")).toBeVisible(SLOW);
      await expect(page.getByTestId("results-week-macro")).toContainText("FOMC", SLOW);
      await page.evaluate(() => document.fonts.ready);
      await page.screenshot({ path: `${SHOTS}/events-results-week-${tag}.png`, fullPage: true });
      await page.setViewportSize({ width: w, height: h });
      await page.getByTestId("results-week-open-MOCKA").click();
      await expect(page.getByTestId("results-week-drawer-past")).toContainText("Based on", SLOW);
      await page.screenshot({ path: `${SHOTS}/events-results-week-drawer-${tag}.png` });
      await page.getByTestId("results-week-drawer-fno").scrollIntoViewIfNeeded();
      await page.screenshot({ path: `${SHOTS}/events-results-week-drawer-fno-${tag}.png` });
      await page.keyboard.press("Escape");
      await openResultsWeek(page);
      const box = page.getByTestId("results-week-ideas");
      await expect(page.getByTestId("results-week-ideas-list")).toBeVisible(SLOW);
      await box.scrollIntoViewIfNeeded();
      await box.screenshot({ path: `${SHOTS}/scanner-results-week-ideas-${tag}.png` });
    });
  }
});

test.describe("Results week — Scanner ideas after the study (desktop 1440)", () => {
  test.use({ viewport: { width: 1440, height: 1000 } });

  test("TC-F4b once the backend says tested, the badge says no measurable skill so far and the note carries the study's result", async ({ page }) => {
    // MOCK — not real data: the same payload with the backend's post-study flag and note (PR #374)
    const STUDY_NOTE = "Ordered for review, not a prediction. Tested on past results seasons: this ordering showed no measurable skill so far.";
    const body = { ...RW, ideas: { ...(RW as any).ideas, tested: true, note: STUDY_NOTE } };
    await setup(page, () => ({ body }));
    await openResultsWeek(page);
    await expect(page.getByTestId("results-week-ideas")).toBeVisible(SLOW);
    await expect(page.getByTestId("results-week-ideas-untested")).toHaveText("NO MEASURABLE SKILL SO FAR");
    await expect(page.getByTestId("results-week-ideas-note")).toContainText(STUDY_NOTE);
  });
});
