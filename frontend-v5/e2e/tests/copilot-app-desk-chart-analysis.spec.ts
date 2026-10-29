/**
 * One-screen Copilot app (/v5/app) — Trade Desk › Chart Analysis › Live chart, the owner's new chart interface of 29 Oct
 * ("Nivesh Chart"), and Strategy Lab removed (test cases: test_reports/chart_analysis_v2_TESTCASES.md, U1–U4, U11–U13 and
 * the page parts of U10; the option chain, strategy cards, basket and strategy panel have their own specs).
 *
 * Every answer below is an inline MOCK — not real data — in the shape of the real routes: backend/routes/desk_live_chart.py
 * (live chart), services/fno_oi_windows.py (oi-buildup with `bars`, `daily_bars`, `daily_windows`), backend/routes/fno.py
 * (expiries, chain, chain/consolidated, iv-history) and the chart-events route. Mocked APIs, production build.
 */
import { test, expect, type Page, type Route } from "@playwright/test";
import { mockApi, mockSingleRoute } from "../helpers/api-mock";

const json = (route: Route, body: unknown, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
const DESK = "/v5/app/trader/desk";
const CHART = (sym: string, extra = "") => `${DESK}?tab=trade&view=chart&sub=live&sym=${sym}${extra}`;
const SLOW = { timeout: 15_000 };
const params = (page: Page) => new URL(page.url()).searchParams;

// ── MOCK candles: 27 Oct (25 bars) and 28 Oct (10 bars) of 15m, IST ─────────────────────────────────────────────────
const t = (day: number, m: number) => {
  const mins = 9 * 60 + 15 + m * 15;
  return `2026-10-${day}T${String(Math.floor(mins / 60)).padStart(2, "0")}:${String(mins % 60).padStart(2, "0")}:00+05:30`;
};
type Bar = [string, number, number, number, number, number];
const BARS: Bar[] = [
  ...Array.from({ length: 25 }, (_, i) => [t(27, i), 1180 + i * 0.6, 1182 + i * 0.6, 1178 + i * 0.6, 1181 + i * 0.6, 40000] as Bar),
  ...[1206, 1210, 1207, 1204, 1203, 1205, 1208, 1211, 1213, 1215].map((c, i) => [t(28, i), c - 2, c + 3, c - 4, c, i === 0 ? 68000 : 30000] as Bar),
];
const LIVE_FIX = {
  symbol: "FIXFNO", as_of: "2026-10-28T11:42:08+05:30",
  timeframe: { interval: "15m", label: "15M", source: "Kite intraday", adjusted: false, reason: null, live_merged: true, note: "Kite candles, raw prices." },
  bars: BARS, ema20: BARS.map((_, i) => (i < 19 ? null : 1190 + i * 0.4)), rvol: BARS.map((_, i) => (i < 20 ? null : i === 25 ? 1.7 : 0.75)),
  last: { price: 1215, at: t(28, 9), bar_complete: false },
  levels: { source: "signal", plan_id: null, entry: 1200, stop: 1170, targets: [{ name: "T1", price: 1230, primary: true }],
    rule: "break_above", valid_for_sessions: 5, reference_close: 1200, direction: "long", signal_date: "2026-10-27" },
  signal: { signal_date: "2026-10-27", stage: "EARLY_BREAKOUT", kind: "READY", revision: 2, engine_version: "positional.v1.0", computed_at: null },
  signals_error: null,
  markers: [
    { kind: "READY", at: t(27, 24), signal_date: "2026-10-27", stage: "EARLY_BREAKOUT", text: "READY: EARLY_BREAKOUT on 2026-10-27" },
    { kind: "RVOL", at: t(28, 0), rvol: 1.7, text: "Volume 1.7× the 20-bar average" },
    { kind: "CONFIRMED", at: t(28, 2), text: "Confirmed: close above the trigger" },
  ],
  markers_error: null, conditions: [], evaluated_at_bar: t(28, 8), valid_until: null, sessions_left: null, holidays_checked: true,
  paper_engine: "A condition met on the chart is not a fill.", read_only: true, sent_to_broker: false,
};

// ── MOCK futures: Kite 15m bars [t, close, volume, oi] (one baseline bar first) and 4-bar windows ────────────────────────
const FUT_OI = (i: number) => 9_000_000 + i * 5_000 - (i === 30 ? 60_000 : 0);
const FUT_BARS = [[t(27, -1), 1180, 900, FUT_OI(-1)], ...BARS.map((b, i) => [b[0], b[4] + 4, 1200, FUT_OI(i)])];
const win = (day: number, i: number, label: string, oiChange: number) => ({
  day: `2026-10-${day}`, index: i, start: t(day, i * 4), end: t(day, Math.min(i * 4 + 4, 25)), bars: 4, close: 1210, price_change: label === "long_buildup" ? 3.5 : -2,
  price_change_pct: 0.29, oi: 9_150_000, oi_change: oiChange, oi_change_pct: 0.44, volume: 4800, label, complete: true,
});
const WINDOWS = [win(27, 0, "long_buildup", 20_000), win(27, 1, "short_covering", -15_000), win(27, 5, "long_buildup", 40_000), win(28, 0, "short_buildup", 30_000), win(28, 1, "long_buildup", 40_000)];
const series = (slot: string, expiry: string | null, scale: number) => ({
  slot, expiry, tradingsymbol: expiry ? `FIXFNO${slot.toUpperCase()}FUT` : null, lot_size: 500, basis: null,
  windows: WINDOWS.map((w) => ({ ...w, oi_change: (w.oi_change as number) * scale })),
  bars: FUT_BARS.map((b) => [b[0], b[1], b[2], Math.round((b[3] as number) * scale)]),
});
const OI_FIX = {
  symbol: "FIXFNO", mode: "intraday", interval: "15m", window: 4, sessions: 2, source: "Kite intraday", snapshot_at: "2026-10-28T06:12:08+00:00", last_bar_at: t(28, 9),
  contracts: [series("current", "2026-11-24", 1), series("next", "2026-12-29", 0.4), series("far", "2027-01-26", 0.05)],
  consolidated: { ...series("consolidated", null, 1.45), expiries: ["2026-11-24", "2026-12-29", "2027-01-26"] },
  missing_slots: [], missing_note: null, kite_reason: null, note: "OI shows positioning, not who initiated it.",
};

// ── MOCK option chain around the price: strikes 1100–1320, call wall 1240, put wall 1160, max pain 1200 ────────────────
const STRIKES = Array.from({ length: 12 }, (_, i) => 1100 + i * 20);
const side = (k: number, kind: "call" | "put", scale = 1) => {
  const peak = kind === "call" ? 1240 : 1160;
  const oi = Math.round((400_000 - Math.abs(k - peak) * 4_000) * scale);
  const intrinsic = kind === "call" ? Math.max(0, 1215 - k) : Math.max(0, k - 1215);
  return { close: +(intrinsic + 18).toFixed(2), settle: +(intrinsic + 18).toFixed(2), oi, change_in_oi: Math.round((k % 40 === 0 ? 12_000 : -6_000) * scale), volume: Math.round(oi / 4),
    change: 1.2, change_pct: 3.1, oi_buildup: null, iv: 22.4, iv_price: "settle", delta: kind === "call" ? 0.5 : -0.5, gamma: 0.004, theta: -0.9, vega: 1.3 };
};
const CHAIN = (expiry: string) => ({
  symbol: "FIXFNO", lot_size: 500, strike_count: STRIKES.length, strikes_returned: STRIKES.length,
  summary: { as_of: "2026-10-27", expiry, spot: 1215, atm_strike: 1220, total_call_oi: 3_400_000, total_put_oi: 2_890_000, total_call_oi_change: 72_000, total_put_oi_change: 36_000,
    pcr: 0.85, max_pain: 1200, max_call_oi: { strike: 1240, oi: 400_000 }, max_put_oi: { strike: 1160, oi: 400_000 }, call_wall: { strike: 1240, oi: 400_000 }, put_wall: { strike: 1160, oi: 400_000 },
    days_to_expiry: 28, forward: 1220, forward_basis: "future", rate_pct: 5.75, atm_iv: 22.4, expected_move: 61.3, expected_move_pct: 5.05 },
  strikes: STRIKES.map((k) => ({ strike: k, call: side(k, "call"), put: side(k, "put") })),
});
const CONSOLIDATED = {
  symbol: "FIXFNO", as_of: "2026-10-27", expiries: ["2026-11-24", "2026-12-29", "2027-01-26"], spot: 1215,
  strikes: STRIKES.map((k) => ({ strike: k, call: { oi: side(k, "call", 1.6).oi, change_in_oi: side(k, "call", 1.6).change_in_oi, volume: side(k, "call", 1.6).volume },
    put: { oi: side(k, "put", 1.6).oi, change_in_oi: side(k, "put", 1.6).change_in_oi, volume: side(k, "put", 1.6).volume } })),
  summary: { atm_strike: 1220, pcr: 0.91, max_pain: 1200, put_wall: { strike: 1160, oi: 640_000 }, call_wall: { strike: 1240, oi: 640_000 },
    total_call_oi: 5_440_000, total_put_oi: 4_950_000, total_call_oi_change: 115_200, total_put_oi_change: 57_600 },
  basis: "summed over the listed expiries", read_only: true,
};
const EXPIRIES = { symbol: "FIXFNO", as_of: "2026-10-27", count: 4, expiries: [
  { expiry: "2026-10-27", days_to_expiry: 0 }, { expiry: "2026-11-24", days_to_expiry: 28 }, { expiry: "2026-12-29", days_to_expiry: 63 }, { expiry: "2027-01-26", days_to_expiry: 91 }] };
const IV_NONE = { symbol: "FIXFNO", bucket: "near_month", sessions: 0, min_sessions: 252, last_session: null, iv_percentile: null, iv_rank: null, reason: "No IV history is recorded for FIXFNO.", series: [] };
const EVENTS = { symbol: "FIXFNO", from: "2026-08-01", to: "2026-10-28", sources: {}, fii_dii_rule: null, events: [
  { id: "e1", date: "2026-10-27", time: null, kind: "results", scope: "stock", title: "Q2 results", detail: null, source: "BSE", url: null,
    reaction: { basis: "daily", day_change_pct: 1.4, next_day_change_pct: 0.6, gap_pct: 0.2, volume_x_avg20: 1.8 } }] };

// ── MOCK daily: no Kite session (FIXDAY) with 60 sessions of daily_bars / daily_windows; after the close (FIXKC) ─────────
const DAYS = Array.from({ length: 60 }, (_, i) => new Date(Date.UTC(2026, 7, 3 + Math.floor(i * 7 / 5))).toISOString().slice(0, 10));
const DAILY: Bar[] = DAYS.map((d, i) => [d, 1180 + i * 0.5, 1186 + i * 0.5, 1176 + i * 0.5, 1182 + i * 0.5, 4_000_000]);
const LIVE_DAY = {
  ...LIVE_FIX, symbol: "FIXDAY", markers: [],
  timeframe: { interval: "1d", label: "DAILY", source: "nidp.prices_eod_adjusted (end of day)", adjusted: true, reason: "token_expired",
    reason_text: "Kite login needed for 15m candles: the platform Kite session expired.", live_merged: false, note: "Daily bars." },
  bars: DAILY, ema20: DAILY.map((_, i) => (i < 19 ? null : 1195)), rvol: DAILY.map(() => null),
  last: { price: DAILY[59][4], at: DAYS[59], bar_complete: true, source: "eod" },
};
const DAILY_OI = DAYS.map((d, i) => [d, DAILY[i][4] + 3, 9000, 8_000_000 + i * 10_000, i === 0 ? null : 10_000, "2026-11-24"]);
const DAILY_WINDOWS = Array.from({ length: 15 }, (_, k) => ({
  day: DAYS[k * 4 + 3], index: k, start: DAYS[k * 4], end: DAYS[k * 4 + 3], bars: 4, close: DAILY[k * 4 + 3][4], price_change: 2, price_change_pct: 0.17,
  oi: 8_000_000 + (k * 4 + 3) * 10_000, oi_change: 40_000, oi_change_pct: 0.5, volume: 36000, label: k % 3 === 2 ? "short_covering" : "long_buildup", complete: true, expiry: "2026-11-24",
}));
const OI_DAY = {
  ...OI_FIX, symbol: "FIXDAY", mode: "end_of_day", interval: "1d", window: 1, sessions: 1, kite_reason: "token_expired",
  contracts: OI_FIX.contracts.map((c) => ({ ...c, bars: [], windows: [], daily_bars: c.slot === "current" ? DAILY_OI : [], daily_windows: c.slot === "current" ? DAILY_WINDOWS : [] })),
  consolidated: { ...OI_FIX.consolidated, bars: [], windows: [], daily_bars: [], daily_windows: [] },
};
const LIVE_KC = {
  ...LIVE_DAY, symbol: "FIXKC",
  timeframe: { ...LIVE_DAY.timeframe, today: { source: "kite_close", day: "2026-10-29", provisional: true, at: "2026-10-29T15:30:57+05:30", price: 1215.5, text: null } },
  bars: [...DAILY.slice(1), ["2026-10-29", 1200, 1218, 1198, 1215.5, 5_000_000] as Bar],
  last: { price: 1215.5, at: "2026-10-29", bar_complete: true, source: "kite_close" },
};
// a stock outside F&O: chart and a cash basket only
const LIVE_CASH = { ...LIVE_DAY, symbol: "FIXCASH" };

const book = { as_of: "2026-10-27", checked_through: "2026-10-27", source: "nidp", price_basis: "raw", marks_error: null, exit_rule: "", entry_rules: {}, rules_version: "desk-paper-v2",
  cost_model: null, orders: "Paper trades never create a broker order.", status: "all", trades: [],
  summary: { open: 0, closed: 0, wins: 0, losses: 0, realized_pnl_rs: 0, net_realized_pnl_rs: 0, costs_realized_rs: 0, unrealized_pnl_rs: 0, unmarked_open: 0, partial: false, entry_pending: 0, not_entered: 0 } };

interface Seen { chain: string[]; oi: string[] }

async function setup(page: Page, o: { phone?: boolean } = {}): Promise<Seen> {
  const seen: Seen = { chain: [], oi: [] };
  if (o.phone) await page.setViewportSize({ width: 390, height: 844 });
  await page.route("**/api/**", (r) => json(r, { detail: "MOCK: not mocked in this spec" }, 404));
  await mockApi(page, "populated");
  await mockSingleRoute(page, "**/api/markets/home", "markets-home.json");
  await page.route("**/api/chat/sessions", (r) => json(r, []));
  await page.route("**/api/positional/watchlist*", (r) => json(r, { as_of_date: "2026-10-27", buckets: { breakout_confirmed: [], pre_breakout: [], true_accumulation: [], trend_continuation: [] } }));
  await page.route("**/api/positional/picks*", (r) => json(r, { signal_date: "2026-10-27", count: 0, picks: [] }));
  await page.route("**/api/move-odds/**", (r) => json(r, { detail: "feature_not_enabled" }, 403));
  await page.route("**/api/desk/alerts*", (r) => json(r, { as_of: "2026-10-27", alerts: [] }));
  await page.route("**/api/desk/ai-watchlist*", (r) => json(r, { detail: "no stored day" }, 404));
  await page.route("**/api/desk/paper-trades*", (r) => json(r, book));
  await page.route("**/api/live/**", (r) => json(r, { available: false, reason: "MOCK: feed off", quotes: {}, mode: "expired", session: "closed", stale: true }));
  await page.route("**/api/desk/live-chart/*", (r) => {
    const sym = new URL(r.request().url()).pathname.split("/").pop();
    const body = ({ FIXFNO: LIVE_FIX, FIXDAY: LIVE_DAY, FIXKC: LIVE_KC, FIXCASH: LIVE_CASH } as Record<string, unknown>)[sym ?? ""];
    return body ? json(r, body) : json(r, { detail: "no_bars_for_symbol" }, 404);
  });
  await page.route("**/api/fno/*/futures/oi-buildup*", (r) => {
    seen.oi.push(r.request().url());
    const sym = new URL(r.request().url()).pathname.split("/")[3];
    return sym === "FIXCASH" ? json(r, { detail: "No F&O data for FIXCASH" }, 404) : json(r, sym === "FIXFNO" ? OI_FIX : { ...OI_DAY, symbol: sym });
  });
  await page.route("**/api/fno/*/expiries", (r) => {
    const sym = new URL(r.request().url()).pathname.split("/")[3];
    return sym === "FIXCASH" ? json(r, { detail: "No F&O data for FIXCASH" }, 404) : json(r, { ...EXPIRIES, symbol: sym });
  });
  await page.route("**/api/fno/*/chain/consolidated*", (r) => { seen.chain.push("consolidated"); return json(r, CONSOLIDATED); });
  await page.route("**/api/fno/*/chain?*", (r) => {
    const u = new URL(r.request().url());
    const expiry = u.searchParams.get("expiry") ?? "2026-11-24";
    seen.chain.push(expiry);
    return json(r, CHAIN(expiry));
  });
  await page.route("**/api/fno/*/iv-history*", (r) => json(r, IV_NONE));
  await page.route("**/api/desk/chart-events/*", (r) => json(r, EVENTS));
  return seen;
}

async function noSideScroll(page: Page) {
  const o = await page.evaluate(() => {
    const sc = document.querySelector('[data-testid="copilot-scroll"]') as HTMLElement | null;
    return { doc: document.documentElement.scrollWidth - window.innerWidth, scroll: sc ? sc.scrollWidth - sc.clientWidth : 0 };
  });
  expect(o.doc).toBeLessThanOrEqual(1);
  expect(o.scroll).toBeLessThanOrEqual(1);
}

test.describe("MOCK — not real data: Trade Desk › Chart Analysis (the owner's chart interface of 29 Oct)", () => {
  test("U1 header and stats row: every figure is the mocked route's; IV percentile says it is not recorded and why", async ({ page }) => {
    await setup(page);
    await page.goto(CHART("FIXFNO"));
    await expect(page.getByTestId("ca-symbol")).toHaveText("FIXFNO", SLOW);
    await expect(page.getByTestId("ca-state")).toHaveAttribute("data-state", "READY");
    await expect(page.getByTestId("ca-meta")).toHaveText("NSE · CASH · 15M · SIGNAL 27 OCT R2");
    await expect(page.getByTestId("ca-last")).toHaveText("LAST 1,215.0 · 11:30:00 IST · KITE");
    await expect(page.getByTestId("ca-stat-pcr")).toContainText("0.85", SLOW);
    await expect(page.getByTestId("ca-stat-max-pain")).toContainText("1,200");
    await expect(page.getByTestId("ca-stat-max-pain")).toContainText("−15 vs last");
    await expect(page.getByTestId("ca-stat-atm-iv")).toContainText("22.4%");
    await expect(page.getByTestId("ca-stat-atm-iv")).toContainText("model, end of day 27 OCT");
    await expect(page.getByTestId("ca-stat-iv-pctile")).toContainText("not recorded");
    await expect(page.getByTestId("ca-stat-iv-pctile")).toContainText("No IV history is recorded for FIXFNO.");
    await expect(page.getByTestId("ca-stat-exp-move")).toContainText("±61.30");
    await expect(page.getByTestId("ca-stat-exp-move")).toContainText("5.05% to expiry");
    // FUT OI Δ: the last labelled 4-bar window of the current month (+40,000 = +0.40 L, its route's 0.44%)
    await expect(page.getByTestId("ca-stat-fut-oi")).toContainText("+0.40 L");
    await expect(page.getByTestId("ca-stat-fut-oi")).toContainText("+0.44%");
    // the readout follows the last bar, and ← moves it one bar back
    await expect(page.getByTestId("ca-readout")).toContainText("C ₹1,215.0");
    await expect(page.getByTestId("ca-readout")).toContainText(`FUT OI ${(FUT_OI(34) / 1e5).toFixed(1)} L`);
    await page.getByTestId("ca-chart-svg").focus();
    await page.keyboard.press("ArrowLeft");
    await expect(page.getByTestId("ca-readout")).toContainText("C ₹1,213.0");
    await expect(page.getByTestId("ca-candle")).toHaveCount(BARS.length);
    await expect(page.getByTestId("ca-footer")).toContainText("CHAIN END OF DAY 27 OCT 2026");
  });

  test("U2 SIGNALS ON CHART: each chip hides and shows its own marks", async ({ page }) => {
    await setup(page);
    await page.goto(CHART("FIXFNO"));
    const count = (id: string) => page.getByTestId(id);
    await expect(count("ca-level")).toHaveCount(3, SLOW);                  // call wall, put wall, max pain
    await expect(count("ca-mark")).toHaveCount(2);                         // READY, RVOL
    await expect(count("ca-confirm")).toHaveCount(1);
    await expect(count("ca-buildup")).toHaveCount(WINDOWS.length);
    await expect(count("ca-event")).toHaveCount(1);
    await expect(page.locator('[data-testid="ca-event"][data-kind="results"]')).toHaveCount(1);
    await page.getByTestId("ca-toggle-walls").click();
    await expect(page.getByTestId("ca-toggle-walls")).toHaveAttribute("aria-pressed", "false");
    await expect(count("ca-level")).toHaveCount(1);
    await expect(page.locator('[data-testid="ca-level"][data-key="max-pain"]')).toHaveCount(1);
    await page.getByTestId("ca-toggle-pain").click();
    await expect(count("ca-level")).toHaveCount(0);
    await page.getByTestId("ca-toggle-pattern").click();
    await expect(count("ca-mark")).toHaveCount(1);
    await page.getByTestId("ca-toggle-rvol").click();
    await expect(count("ca-mark")).toHaveCount(0);
    await page.getByTestId("ca-toggle-conf").click();
    await expect(count("ca-confirm")).toHaveCount(0);
    await page.getByTestId("ca-toggle-build").click();
    await expect(count("ca-buildup")).toHaveCount(0);
    await page.getByTestId("ca-toggle-events").click();
    await expect(count("ca-event")).toHaveCount(0);
    await page.getByTestId("ca-toggle-walls").click();
    await expect(count("ca-level")).toHaveCount(2);
  });

  test("U3 strike ladder: OI / OI Δ / VOLUME read the chain's own columns; a click selects the strike for the summary", async ({ page }) => {
    await setup(page);
    await page.goto(CHART("FIXFNO"));
    const ladder = page.getByTestId("ca-ladder");
    await expect(ladder).toHaveAttribute("data-mode", "oi", SLOW);
    const row = (k: number) => page.locator(`[data-testid="ca-ladder-row"][data-strike="${k}"]`);
    await expect(row(1240)).toHaveAttribute("data-call", String(side(1240, "call").oi));
    await expect(row(1160)).toHaveAttribute("data-put", String(side(1160, "put").oi));
    await expect(row(1220)).toHaveAttribute("data-selected", "true");          // ATM until a strike is picked
    await page.getByTestId("ca-ladder-oichg").click();
    await expect(ladder).toHaveAttribute("data-mode", "oichg");
    await expect(row(1240)).toHaveAttribute("data-call", String(side(1240, "call").change_in_oi));
    await page.getByTestId("ca-ladder-vol").click();
    await expect(row(1240)).toHaveAttribute("data-call", String(side(1240, "call").volume));
    await row(1160).click();
    await expect(row(1160)).toHaveAttribute("data-selected", "true");
    await expect(row(1220)).toHaveAttribute("data-selected", "false");
    await expect(page.getByTestId("ca-sum-strike")).toContainText("STRIKE 1,160");
    await expect(page.getByTestId("ca-sum-strike")).toContainText(`Put OI ${(side(1160, "put").oi / 1e5).toFixed(2)} L`);
    await expect(page.getByTestId("ca-sum-call-wall")).toContainText("CALL WALL 1,240");
    await expect(page.getByTestId("ca-sum-put-wall")).toContainText("PUT WALL 1,160");
  });

  test("U4 expiry pills switch the chain's expiry and the futures slot; Consolidated reads the summed chain", async ({ page }) => {
    const seen = await setup(page);
    await page.goto(CHART("FIXFNO"));
    await expect(page.getByTestId("ca-expiry-current")).toHaveAttribute("aria-pressed", "true", SLOW);
    await expect(page.getByTestId("ca-expiry-current")).toContainText("24 Nov 2026");
    await expect(page.getByTestId("ca-expiry-far")).toContainText("26 Jan 2027");
    await expect.poll(() => seen.chain).toContain("2026-11-24");
    await expect(page.getByTestId("ca-sum-buildup")).toContainText("Current month (24 Nov 2026)");
    await page.getByTestId("ca-expiry-next").click();
    await expect.poll(() => seen.chain).toContain("2026-12-29");
    await expect(page.getByTestId("ca-sum-buildup")).toContainText("Next month (29 Dec 2026)");
    await expect(page.getByTestId("ca-sum-buildup")).toContainText("OI +0.16 L");             // the next month's own window (40,000 × 0.4)
    await page.getByTestId("ca-expiry-consolidated").click();
    await expect.poll(() => seen.chain).toContain("consolidated");
    await expect(page.getByTestId("ca-stat-pcr")).toContainText("0.91");
    await expect(page.getByTestId("ca-stat-atm-iv")).toContainText("pick an expiry");
    await expect(page.getByTestId("ca-stat-exp-move")).toContainText("pick an expiry");
    await expect(page.locator('[data-testid="ca-ladder-row"][data-strike="1240"]')).toHaveAttribute("data-call", String(CONSOLIDATED.strikes.find((s) => s.strike === 1240)!.call.oi));
    await expect(page.getByTestId("ca-sum-buildup")).toContainText("Consolidated");
  });

  test("daily (no Kite session): the request asks for 60 daily sessions; futures OI, OI Δ and build-up come from daily_bars / daily_windows", async ({ page }) => {
    const seen = await setup(page);
    await page.goto(CHART("FIXDAY"));
    await expect(page.getByTestId("ca-card")).toHaveAttribute("data-interval", "1d", SLOW);
    await expect(page.getByTestId("ca-kite-fallback")).toContainText("Kite login needed for 15m candles");
    await expect(page.getByTestId("ca-meta")).toContainText("NSE · CASH · DAILY");
    await expect.poll(() => seen.oi.some((u) => new URL(u).searchParams.get("daily") === "60")).toBe(true);
    await expect(page.getByTestId("ca-fut-oi")).toHaveCount(1);
    await expect(page.getByTestId("ca-fut-chg")).toHaveCount(DAILY_OI.length - 1);            // the first session has no change
    await expect(page.getByTestId("ca-buildup")).toHaveCount(DAILY_WINDOWS.length);
    await expect(page.locator('[data-testid="ca-buildup"][data-tag="SC"]')).toHaveCount(5);
    await expect(page.getByTestId("ca-stat-fut-oi")).toContainText("+0.10 L");
    await expect(page.getByTestId("ca-stat-fut-oi")).toContainText(`session ${new Date(`${DAYS[59]}T12:00:00+05:30`).toLocaleDateString("en-IN", { timeZone: "Asia/Kolkata", day: "numeric", month: "short", year: "numeric" })}`);
    await expect(page.getByTestId("ca-last")).toContainText("EXCHANGE EOD");
  });

  test("KC after the close, before the exchange's end of day: LAST is the Kite close, labelled provisional", async ({ page }) => {
    await setup(page);
    await page.goto(CHART("FIXKC"));
    await expect(page.getByTestId("ca-last")).toHaveAttribute("data-source", "kite_close", SLOW);
    await expect(page.getByTestId("ca-last")).toContainText("LAST 1,215.5");
    await expect(page.getByTestId("ca-last")).toContainText("KITE CLOSE · PROVISIONAL");
    await expect(page.getByTestId("ca-kite-fallback")).toContainText("the Kite close (provisional until the exchange's end-of-day file)");
  });

  test("U10 (page part) with an empty basket the signal's own levels are drawn and cannot be dragged", async ({ page }) => {
    await setup(page);
    await page.goto(CHART("FIXFNO"));
    await expect(page.locator('[data-testid="ca-tradeline"][data-key="sig-entry"]')).toHaveAttribute("data-value", "1200", SLOW);
    await expect(page.locator('[data-testid="ca-tradeline"][data-key="sig-stop"]')).toHaveAttribute("data-value", "1170");
    await expect(page.locator('[data-testid="ca-tradeline"][data-key="sig-t1"]')).toHaveAttribute("data-value", "1230");
    await expect(page.getByTestId("ca-tradeline-handle")).toHaveCount(0);
  });

  test("U11 390 px: no sideways page scroll; the stats sit two to a row; no ladder on a phone (the chain has the strikes)", async ({ page }) => {
    await setup(page, { phone: true });
    await page.goto(CHART("FIXFNO"));
    await expect(page.getByTestId("ca-candle").first()).toBeVisible(SLOW);
    await expect(page.getByTestId("ca-stat-pcr")).toContainText("0.85", SLOW);
    const a = await page.getByTestId("ca-stat-pcr").boundingBox();
    const b = await page.getByTestId("ca-stat-fut-oi").boundingBox();
    const c = await page.getByTestId("ca-stat-max-pain").boundingBox();
    expect(Math.abs((a?.y ?? 0) - (b?.y ?? 1))).toBeLessThan(2);                 // PCR and FUT OI Δ share a row
    expect((c?.y ?? 0)).toBeGreaterThan((a?.y ?? 0) + 10);                         // MAX PAIN starts the next
    await expect(page.getByTestId("ca-ladder")).toHaveCount(0);
    await noSideScroll(page);
  });

  test("U13 a stock outside F&O: the chart draws; the F&O parts say why they are empty; no expiry pills", async ({ page }) => {
    await setup(page);
    await page.goto(CHART("FIXCASH"));
    await expect(page.getByTestId("ca-candle")).toHaveCount(DAILY.length, SLOW);
    await expect(page.getByTestId("ca-chain-none")).toContainText("FIXCASH is not in the F&O segment, so there is no option chain. The paper basket takes a cash trade.");
    await expect(page.getByTestId("ca-stat-pcr")).toContainText("not in F&O");
    await expect(page.getByTestId("ca-stat-fut-oi")).toContainText("FIXCASH has no futures in the F&O segment.");
    await expect(page.getByTestId("ca-ladder-empty")).toHaveText("FIXCASH is not in F&O");
    await expect(page.getByTestId("ca-expiry-current")).toHaveCount(0);
  });

  test("TC-10 a symbol with no prices says so instead of an error", async ({ page }) => {
    await setup(page);
    await page.goto(CHART("NOPRICE"));
    await expect(page.getByTestId("ca-noprices")).toContainText("No prices on record for NOPRICE", SLOW);
    await expect(page.getByTestId("ca-error")).toHaveCount(0);
  });

  test("U12 Strategy Lab is gone: four Trade Desk sections; every old lab URL opens the chart with its stock and plan", async ({ page }) => {
    await setup(page);
    await page.goto(CHART("FIXFNO"));
    await expect(page.getByTestId("desk-views").getByRole("button")).toHaveText(["AI Scanner", "Chart Analysis", "Paper Trading", "Watchlists"], SLOW);
    await expect(page.getByTestId("desk-view-lab")).toHaveCount(0);
    for (const [from, sym, tp] of [
      ["?tab=trade&view=lab&sub=build&sym=FIXFNO&tp=PLAN-1", "FIXFNO", "PLAN-1"],
      ["?tab=trade&view=lab&sub=backtest", null, null],
      ["?tab=fno&lab=strategies&lab_sym=fixfno", "FIXFNO", null],
      ["?tab=more&view=strategy&mode=stock&sym=FIXFNO&direction=bullish", "FIXFNO", null],
    ] as Array<[string, string | null, string | null]>) {
      await page.goto(`${DESK}${from}`);
      await expect.poll(() => params(page).get("view"), from).toBe("chart");
      await expect.poll(() => params(page).get("sub"), from).toBe("live");
      expect(params(page).get("sym"), from).toBe(sym);
      expect(params(page).get("tp"), from).toBe(tp);
      for (const gone of ["lab", "lab_sym", "mode", "direction", "section"]) expect(params(page).get(gone), `${from} ${gone}`).toBeNull();
    }
    for (const from of ["/v5/pro-trader", "/v5/strategy-builder"]) {
      await page.goto(from);
      await expect.poll(() => params(page).get("view"), from).toBe("chart");
    }
  });

  test("wording: ideas and paper; the page never calls anything a pick or a recommendation of its own", async ({ page }) => {
    await setup(page);
    await page.goto(CHART("FIXFNO"));
    await expect(page.getByTestId("ca-stat-pcr")).toContainText("0.85", SLOW);
    const text = await page.getByTestId("ca-card").innerText();
    expect(text).toContain("EDUCATIONAL · PAPER ONLY");
    expect(text).not.toMatch(/\b(pick|picks|buy now|sell now|guaranteed)\b/i);
  });
});
