/**
 * One-screen Copilot app (/v5/app) — Trade Desk › Chart Analysis › Live chart, built to the owner's design of 28 Oct
 * (test cases: test_reports/desk_live_chart_TESTCASES.md, TC-15 … TC-24).
 *
 * The plan, GET /api/desk/trade-plans/{id} (with `account_size`), GET /api/risk/profile, the F&O ideas board and the REAL
 * allow / block answers of POST /api/desk/paper-trades come from `contract-decision-card.json`, which
 * backend/tests/test_decision_card_contract.py rebuilds from the real routes (MOCK — not real data). The live-chart and
 * oi-buildup answers below are inline MOCKs — not real data — in the shape of backend/routes/desk_live_chart.py and
 * services/fno_oi_windows.py (backend/tests/test_desk_live_chart.py pins those shapes). Mocked APIs, production build.
 */
import { test, expect, type Page, type Route } from "@playwright/test";
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";
import { mockApi, mockSingleRoute } from "../helpers/api-mock";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const load = (name: string) => JSON.parse(fs.readFileSync(path.join(__dirname, "..", "fixtures", name), "utf-8"));
const CARD = load("contract-decision-card.json");
const clone = <T,>(x: T): T => JSON.parse(JSON.stringify(x));
const json = (route: Route, body: unknown, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });

const DESK = "/v5/app/trader/desk";
const CASH_PLAN = CARD.cash.trade_plan_response.plan;
const LIVE = (sym: string, extra = "") => `${DESK}?tab=trade&view=chart&sub=live&sym=${sym}${extra}`;
const SLOW = { timeout: 15_000 };
const params = (page: Page) => new URL(page.url()).searchParams;

// ── MOCK candles: 27 Oct (25 bars) and 28 Oct (10 bars) of 15m, IST ───────────────────────────────────────────────────
const t = (day: number, m: number) => {
  const mins = 9 * 60 + 15 + m * 15;
  return `2026-10-${day}T${String(Math.floor(mins / 60)).padStart(2, "0")}:${String(mins % 60).padStart(2, "0")}:00+05:30`;
};
const BARS: Array<[string, number, number, number, number, number]> = [
  ...Array.from({ length: 25 }, (_, i) => [t(27, i), 1180 + i * 0.6, 1182 + i * 0.6, 1178 + i * 0.6, 1181 + i * 0.6, 40000] as [string, number, number, number, number, number]),
  ...[1206, 1210, 1207, 1204, 1203, 1205, 1208, 1211, 1213, 1215].map((c, i) => [t(28, i), c - 2, c + 3, c - 4, c, i === 0 ? 68000 : 30000] as [string, number, number, number, number, number]),
];
const EMA = BARS.map((_, i) => (i < 19 ? null : 1190 + i * 0.4));
const RVOL = BARS.map((b, i) => (i < 20 ? null : i === 25 ? 1.7 : 0.75));
const COND = (o: Record<string, Partial<{ status: string; value: string; label: string }>> = {}) => [
  { key: "ema20", label: "15m close above 20 EMA", status: "met", value: "1,213.0 > 1,203.6", rule: "the last completed 15m close vs the 20-bar EMA", at: t(28, 8) },
  { key: "volume", label: "Volume ≥ 1.3× 20-bar avg", status: "met", value: "1.7×", rule: "a bar in the last 20 with volume ≥ 1.3× the mean of the 20 bars before it", at: t(28, 0) },
  { key: "pullback", label: "Pullback on lower volume", status: "met", value: "0.7×", rule: "after the volume bar: lows under its close on volume below the 20-bar average", at: null },
  { key: "trigger", label: "Entry trigger", status: "not_applicable", value: "the plan enters at once (end of day)", rule: "the plan's entry rule", at: null },
  { key: "validity", label: "Inside validity window", status: "unavailable", value: "no signal day or validity on the plan", rule: "the plan's valid_for_sessions after the signal day", at: null },
  { key: "invalidation", label: "Invalidation: close below 1,160.0", status: "not_hit", value: "not hit", rule: "a completed 15m close below the stop since the signal day", at: null },
].map((c) => ({ ...c, ...(o[c.key] ?? {}) }));

const LIVE_ICICI = {
  symbol: "ICICIBANK", as_of: "2026-10-28T11:42:08+05:30",
  timeframe: { interval: "15m", label: "15M", source: "Kite intraday", adjusted: false, reason: null, live_merged: true, note: "Kite candles, raw prices (not split or bonus adjusted)." },
  bars: BARS, ema20: EMA, rvol: RVOL,
  last: { price: 1215, at: t(28, 9), bar_complete: false },
  levels: { source: "plan", plan_id: CASH_PLAN.plan_id, entry: 1200, stop: 1160, targets: [{ name: "conservative", price: 1220, primary: false }, { name: "base", price: 1280, primary: true }],
    rule: "at_once", valid_for_sessions: null, reference_close: 1200, direction: "bullish", signal_date: "2026-10-27", invalidation: null },
  signal: { signal_date: "2026-10-27", stage: "EARLY_BREAKOUT", kind: "READY", revision: 2, engine_version: "positional.v1.0", computed_at: "2026-10-27T14:15:00+00:00" },
  signals_error: null,
  markers: [
    { kind: "READY", at: t(27, 24), signal_date: "2026-10-27", stage: "EARLY_BREAKOUT", text: "READY: the scanner's stage EARLY_BREAKOUT on 2026-10-27 (end of day)" },
    { kind: "RVOL", at: t(28, 0), rvol: 1.7, text: "Volume 1.7× the 20-bar average" },
  ],
  markers_error: null,
  conditions: COND(),
  evaluated_at_bar: t(28, 8), valid_until: null, sessions_left: null, holidays_checked: true,
  paper_engine: "A condition met on the chart is not a fill: the paper engine fills on end-of-day bars (break above / pull back to / at once), and a stop does not cap a loss in a gap.",
  read_only: true, sent_to_broker: false,
};

// ── MOCK futures OI by 4-bar window (services/fno_oi_windows.intraday_answer shape) ───────────────────────────────────
const WINDOW_LABELS = ["long_buildup", "long_buildup", "short_covering", "short_covering", "long_unwinding", "long_buildup", "long_buildup", "long_buildup", "short_covering", "long_buildup"];
const windows = (labels: string[], scale = 1) => {
  const out: Array<Record<string, unknown>> = [];
  let k = 0;
  for (const [day, n] of [[27, 7], [28, 3]] as Array<[number, number]>) {
    for (let i = 0; i < n; i++) {
      const lab = labels[k++ % labels.length];
      const up = lab === "long_buildup" || lab === "short_covering";
      const oiUp = lab === "long_buildup" || lab === "short_buildup";
      const startM = i * 4, endM = Math.min(i * 4 + 4, 25);
      out.push({ day: `2026-10-${day}`, index: i, start: t(day, startM), end: t(day, endM), bars: 4, close: 1200 + k, price_change: up ? 1.5 : -1.5, price_change_pct: up ? 0.12 : -0.12,
        oi: 9_000_000 * scale + k * 10_000, oi_change: (oiUp ? 1 : -1) * 40_000 * scale, oi_change_pct: 0.4, volume: 1200 * scale, label: lab, complete: !(day === 28 && i === n - 1) });
    }
  }
  return out;
};
const OI_ICICI = {
  symbol: "ICICIBANK", mode: "intraday", interval: "15m", window: 4, sessions: 2, source: "Kite intraday, futures with open interest", snapshot_at: "2026-10-28T06:12:08+00:00", last_bar_at: t(28, 9),
  contracts: [
    { slot: "current", expiry: "2026-11-24", tradingsymbol: "ICICIBANK26NOVFUT", lot_size: 700, windows: windows(WINDOW_LABELS) },
    { slot: "next", expiry: "2026-12-29", tradingsymbol: "ICICIBANK26DECFUT", lot_size: 700, windows: windows(["short_buildup"], 0.4) },
    { slot: "far", expiry: "2027-01-26", tradingsymbol: "ICICIBANK27JANFUT", lot_size: 700, windows: windows(["long_unwinding"], 0.05) },
  ],
  consolidated: { slot: "consolidated", expiries: ["2026-11-24", "2026-12-29", "2027-01-26"], windows: windows(["long_buildup"], 1.4), basis: "the near month's price change; OI and volume summed over the expiries listed" },
  missing_slots: [], missing_note: null, kite_reason: null,
  note: "OI shows positioning, not who initiated it. Build-up is a reading of price change and OI change together.", read_only: true,
};

// ── MOCK: no Kite session (HDFCBANK): daily bars and the bhavcopy day (figures shaped like the staging read of 28 Oct) ─
const DAYS = Array.from({ length: 60 }, (_, i) => { const d = new Date(Date.UTC(2026, 7, 3 + Math.floor(i * 7 / 5))); return d.toISOString().slice(0, 10); });
const DAILY = DAYS.map((d, i) => [d, 700 + i * 0.2, 704 + i * 0.2, 696 + i * 0.2, 701 + i * 0.2, 4_000_000] as [string, number, number, number, number, number]);
const LIVE_HDFC = {
  ...clone(LIVE_ICICI), symbol: "HDFCBANK",
  timeframe: { interval: "1d", label: "DAILY", source: "nidp.prices_eod_adjusted (end of day)", adjusted: true, reason: "token_expired",
    reason_text: "Kite login needed for 15m candles: the platform Kite session expired.", live_merged: false, note: "Daily bars, split and bonus adjusted." },
  bars: DAILY, ema20: DAILY.map((_, i) => (i < 19 ? null : 706)), rvol: DAILY.map((_, i) => (i < 20 ? null : 1.0)),
  last: { price: 680.2, at: DAYS[59], bar_complete: true },
  levels: { source: "signal", plan_id: null, entry: 750.05, stop: 729.06, targets: [{ name: "T1", price: 792.04, primary: true }], rule: "break_above", valid_for_sessions: null,
    reference_close: 680.2, direction: "long", signal_date: "2026-09-25", invalidation: null },
  signal: { signal_date: "2026-09-25", stage: "EARLY_BREAKOUT", kind: "READY", revision: 1, engine_version: "positional.v1.0", computed_at: null },
  markers: [],
  conditions: COND({
    ema20: { label: "daily close above 20 EMA", status: "not_met", value: "680.20 ≤ 706.03" },
    trigger: { label: "daily close above 750.05", status: "waiting", value: "waiting" },
    validity: { status: "not_met", value: "expired" },
    invalidation: { label: "Invalidation: close below 729.06", status: "hit", value: "hit at 2026-09-28" },
  }),
  evaluated_at_bar: DAYS[59],
};
const eodWin = (price: number, chg: number, oi: number, label: string) => [{ day: "2026-10-27", index: 0, start: "2026-10-27", end: "2026-10-27", bars: 1, close: 681.4, price_change: price,
  price_change_pct: -1.12, oi, oi_change: chg, oi_change_pct: null, volume: 75194, label, complete: true }];
const OI_HDFC = {
  symbol: "HDFCBANK", mode: "end_of_day", interval: "1d", window: 1, sessions: 1, source: "NSE F&O bhavcopy (nidp.fno_bhavcopy), end of day", snapshot_at: "2026-10-27", last_bar_at: "2026-10-27",
  contracts: [
    { slot: "current", expiry: "2026-10-27", tradingsymbol: null, lot_size: null, windows: eodWin(-7.75, -38621050, 1, "long_unwinding") },
    { slot: "next", expiry: "2026-11-23", tradingsymbol: null, lot_size: null, windows: eodWin(-7.8, 38107550, 2, "short_buildup") },
    { slot: "far", expiry: "2026-12-29", tradingsymbol: null, lot_size: null, windows: eodWin(-7.5, 2860000, 3, "short_buildup") },
  ],
  consolidated: { slot: "consolidated", expiries: ["2026-10-27", "2026-11-23", "2026-12-29"], windows: eodWin(-7.75, 2346500, 406337750, "short_buildup"), basis: "summed" },
  missing_slots: [], missing_note: null, kite_reason: "token_expired",
  note: "OI shows positioning, not who initiated it. Build-up is a reading of price change and OI change together.", read_only: true,
};

// GET /api/fno/{symbol}/expiries + /chain: the synthetic chain fixture (backend/routes/fno.py over a made-up payload), with the walls.
const EXPIRIES = { symbol: "X", as_of: "2026-10-27", expiries: [{ expiry: "2026-10-27", days_to_expiry: 0 }, { expiry: "2026-11-24", days_to_expiry: 28 }], count: 2 };
const CHAIN = (() => {
  const c = load("copilot-options-chain.json");
  c.summary = { ...c.summary, as_of: "2026-10-27", expiry: "2026-11-24", days_to_expiry: 28, put_wall: { strike: 24700, oi: 3000000 }, call_wall: { strike: 25300, oi: 3000000 } };
  return c;
})();
const IV_NONE = { symbol: "X", bucket: "near_month", sessions: 0, min_sessions: 252, last_session: null, iv_percentile: null, iv_rank: null, reason: "No IV history is recorded for X.", series: [] };

const PROFILE = (() => { const p = clone(CARD.risk_profile_default); p.live.open.risk_rs = 12000; return p; })();
const book = (trades: Array<Record<string, unknown>>) => ({
  as_of: "2026-10-27", checked_through: "2026-10-27", source: "nidp", price_basis: "raw traded price", marks_error: null, exit_rule: "stop, target, time", entry_rules: {},
  rules_version: "desk-paper-v2", cost_model: null, orders: "Paper trades never create a broker order.", status: "all", trades,
  summary: { open: trades.length, closed: 0, wins: 0, losses: 0, realized_pnl_rs: 0, net_realized_pnl_rs: 0, costs_realized_rs: 0, unrealized_pnl_rs: 0, unmarked_open: 0, partial: false, entry_pending: trades.length, not_entered: 0 },
});
const PENDING_HDFC = {
  id: "pt-hdfc", kind: "cash", symbol: "HDFCBANK", quantity: 60, entry_price: 750.05, stop_price: 729.06, target_price: 792.04, note: null, source: { kind: "scanner" },
  opened_at: "2026-10-27T09:00:00+00:00", status: "open", closed_at: null, exit_price: null, exit_reason: null, exit_session: null, exit_note: null, last_close: 680.2, last_close_date: "2026-10-27",
  unrealized_pnl_rs: null, realized_pnl_rs: null, checked_through: "2026-10-27", mark_error: null, entry_rule: "break_above", entry_window_sessions: 5, max_hold_sessions: 10, rules_version: "desk-paper-v2",
  entry_status: "waiting", entry_session: null, sim_entry_price: null, flags: [], exit_rules: [], stop_history: [], current_stop: 729.06, stop_version: 1, plan_ref: null, transitions: [], state: "TRADE_ELIGIBLE",
};

interface Seen { posts: Array<Record<string, unknown>>; chainExpiry: Array<string | null> }
interface Opts { phone?: boolean; trades?: Array<Record<string, unknown>>; post?: Array<{ status: number; body: unknown }>; oi?: Record<string, unknown> }

async function setup(page: Page, o: Opts = {}): Promise<Seen> {
  const seen: Seen = { posts: [], chainExpiry: [] };
  if (o.phone) await page.setViewportSize({ width: 390, height: 844 });
  await page.route("**/api/**", (r) => json(r, { detail: "MOCK: not mocked in this spec" }, 404));
  await mockApi(page, "populated");
  await mockSingleRoute(page, "**/api/markets/home", "markets-home.json");
  await page.route("**/api/chat/sessions", (r) => json(r, []));
  await page.route("**/api/positional/watchlist*", (r) => json(r, { as_of_date: "2026-10-27", buckets: { breakout_confirmed: [], pre_breakout: [], true_accumulation: [], trend_continuation: [] } }));
  await page.route("**/api/positional/picks*", (r) => json(r, { signal_date: "2026-10-27", count: 0, picks: [] }));
  await page.route("**/api/move-odds/**", (r) => json(r, { detail: "feature_not_enabled" }, 403));
  await page.route("**/api/desk/alerts*", (r) => json(r, { as_of: "2026-10-27", alerts: [] }));
  await page.route("**/api/risk/status", (r) => json(r, { kill_switch: false, halted: false, policy_version: "MOCK" }));
  await page.route("**/api/risk/profile", (r) => json(r, PROFILE));
  await page.route("**/api/desk/paper-account", (r) => json(r, { ...CARD.paper_account, stored: true }));
  await page.route("**/api/desk/exit-job-status", (r) => json(r, { job: "check_desk_alerts", status: "ok", message: "ok", last_checked: { session: "2026-10-27" } }));
  await page.route("**/api/desk/strategy/ideas", (r) => json(r, CARD.cash.ideas_response));
  await page.route("**/api/desk/strategy/top", (r) => json(r, CARD.fno.top_response));
  await page.route("**/api/desk/trade-plans/*", (r) => {
    const id = decodeURIComponent(new URL(r.request().url()).pathname.split("/").pop() as string);
    return id === CASH_PLAN.plan_id ? json(r, CARD.cash.trade_plan_response) : json(r, { detail: "plan_not_found" }, 404);
  });
  const posts = [...(o.post ?? [])];
  await page.route("**/api/desk/paper-trades*", (r) => {
    if (r.request().method() === "POST") {
      seen.posts.push(r.request().postDataJSON());
      const a = posts.shift() ?? { status: 201, body: { trade: { id: "t1" }, risk: null } };
      return json(r, a.body, a.status);
    }
    return json(r, book(o.trades ?? []));
  });
  await page.route("**/api/live/**", (r) => json(r, { available: false, reason: "MOCK: feed off", quotes: {}, mode: "expired", session: "closed", stale: true }));
  await page.route("**/api/desk/live-chart/*", (r) => {
    const sym = new URL(r.request().url()).pathname.split("/").pop();
    return sym === "ICICIBANK" ? json(r, LIVE_ICICI) : sym === "HDFCBANK" ? json(r, LIVE_HDFC) : json(r, { detail: "no_bars_for_symbol" }, 404);
  });
  await page.route("**/api/fno/*/futures/oi-buildup*", (r) => {
    const sym = new URL(r.request().url()).pathname.split("/")[3];
    return sym === "ICICIBANK" ? json(r, o.oi ?? OI_ICICI) : json(r, OI_HDFC);
  });
  await page.route("**/api/fno/*/expiries", (r) => json(r, EXPIRIES));
  await page.route("**/api/fno/*/chain*", (r) => {
    seen.chainExpiry.push(new URL(r.request().url()).searchParams.get("expiry"));
    return json(r, CHAIN);
  });
  await page.route("**/api/fno/*/iv-history*", (r) => json(r, IV_NONE));
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

test.describe("MOCK — not real data: Trade Desk › Chart Analysis › Live chart", () => {
  test("TC-15 / TC-16 / TC-19 the chart card: header, headline, the marks on the chart, the legend", async ({ page }) => {
    await setup(page);
    await page.goto(LIVE("ICICIBANK", `&tp=${CASH_PLAN.plan_id}`));
    const card = page.getByTestId("lc-chart");
    await expect(card).toHaveAttribute("data-interval", "15m", SLOW);
    await expect(page.getByTestId("lc-symbol")).toHaveText("ICICIBANK");
    await expect(page.getByTestId("lc-state")).toHaveText("READY");
    await expect(page.getByTestId("lc-meta")).toHaveText(/NSE · CASH · 15M · Signal 27 OCT r2 · Detector positional\.v1\.0/i);
    await expect(page.getByTestId("lc-last")).toHaveText(/Last 1,215(\.0)? · \d\d:\d\d:\d\d IST/i);
    await expect(page.getByTestId("lc-headline")).toHaveText("ICICIBANK is above its entry 1,200.0. No fill yet: the plan enters at once, inside the last session's range. The paper engine fills on end-of-day bars.");
    await expect(card.getByTestId("desk-candle")).toHaveCount(BARS.length);
    await expect(card.getByTestId("desk-level-entry")).toHaveAttribute("data-value", "1200");
    await expect(card.getByTestId("desk-level-stop")).toHaveAttribute("data-value", "1160");
    await expect(card.getByTestId("desk-level-t1")).toHaveAttribute("data-value", "1220");
    await expect(card.getByTestId("desk-level-t2")).toHaveAttribute("data-value", "1280");
    await expect(card.getByTestId("desk-level-name-stop")).toHaveText("STOP");
    await expect(card.getByTestId("desk-line-ema20")).toHaveCount(1);
    await expect(card.getByTestId("desk-last-dot")).toHaveCount(1);
    await expect(card.getByTestId("desk-signal-marker")).toHaveCount(2);
    await expect(card.locator('[data-testid="desk-signal-marker"][data-label="READY"]')).toHaveAttribute("data-at", t(27, 24));
    await expect(card.locator('[data-testid="desk-signal-marker"][data-label="RVOL 1.7×"]')).toHaveCount(1);
    // F&O markers where the current month's build-up class changes (long build-up → short covering → long unwinding → …)
    await expect(card.getByTestId("desk-fno-marker").first()).toHaveAttribute("data-label", "LONG BUILD-UP");
    await expect(card.locator('[data-testid="desk-fno-marker"][data-label="SHORT COVERING"]')).not.toHaveCount(0);
    await expect(card.locator('[data-testid="desk-fno-marker"][data-label="LONG UNWINDING"]')).toHaveCount(1);
    await expect(page.getByTestId("lc-legend")).toContainText(/EMA 20/i);
    await expect(page.getByTestId("lc-fill-state")).toHaveText(/No fill yet/i);
    await expect(page.getByTestId("lc-kite-fallback")).toHaveCount(0);
  });

  test("TC-15 the SIGNALS ON CHART toggles hide and show their own markers", async ({ page }) => {
    await setup(page);
    await page.goto(LIVE("ICICIBANK", `&tp=${CASH_PLAN.plan_id}`));
    const card = page.getByTestId("lc-chart");
    await expect(card.getByTestId("desk-signal-marker")).toHaveCount(2, SLOW);
    for (const g of ["pattern", "confirmation", "volume", "fno"]) await expect(page.getByTestId(`lc-toggle-${g}`)).toHaveAttribute("aria-pressed", "true");
    await page.getByTestId("lc-toggle-pattern").click();
    await expect(card.locator('[data-testid="desk-signal-marker"][data-group="pattern"]')).toHaveCount(0);
    await expect(card.locator('[data-testid="desk-signal-marker"][data-group="volume"]')).toHaveCount(1);
    await page.getByTestId("lc-toggle-volume").click();
    await expect(card.getByTestId("desk-signal-marker")).toHaveCount(0);
    await page.getByTestId("lc-toggle-fno").click();
    await expect(card.getByTestId("desk-fno-marker")).toHaveCount(0);
    await page.getByTestId("lc-toggle-confirmation").click();
    await expect(page.getByTestId("lc-toggle-confirmation")).toHaveAttribute("aria-pressed", "false");
    await page.getByTestId("lc-toggle-pattern").click();
    await page.getByTestId("lc-toggle-fno").click();
    await expect(card.locator('[data-testid="desk-signal-marker"][data-group="pattern"]')).toHaveCount(1);
    await expect(card.getByTestId("desk-fno-marker")).not.toHaveCount(0);
  });

  test("TC-17 the futures OI strip: build-up by 4-bar window, snapshot, and the current / next / far / consolidated selector", async ({ page }) => {
    await setup(page);
    await page.goto(LIVE("ICICIBANK", `&tp=${CASH_PLAN.plan_id}`));
    const strip = page.getByTestId("lc-oi");
    await expect(strip).toHaveAttribute("data-mode", "intraday", SLOW);
    await expect(strip).toContainText(/Futures OI · build-up by 4-bar window/i);
    await expect(page.getByTestId("lc-oi-snapshot")).toHaveText(/Snapshot 11:42:08 IST/i);
    await expect(strip.getByTestId("lc-oi-bar")).toHaveCount(10);
    await expect(strip.getByTestId("lc-oi-line")).toHaveCount(1);
    await expect(strip.locator('[data-testid="lc-oi-bar"][data-complete="false"]')).toHaveCount(1);
    await expect(page.getByTestId("lc-oi-slot-current")).toHaveAttribute("aria-pressed", "true");
    await expect(page.getByTestId("lc-oi-slot-current")).toHaveText(/Current month · 24 Nov/);
    await page.getByTestId("lc-oi-slot-next").click();
    await expect(strip).toHaveAttribute("data-slot", "next");
    await expect(strip.locator('[data-testid="lc-oi-bar"][data-label="short_buildup"]')).toHaveCount(10);
    await page.getByTestId("lc-oi-slot-far").click();
    await expect(strip.locator('[data-testid="lc-oi-bar"][data-label="long_unwinding"]')).toHaveCount(10);
    await page.getByTestId("lc-oi-slot-consolidated").click();
    await expect(strip).toHaveAttribute("data-slot", "consolidated");
    await expect(strip.locator('[data-testid="lc-oi-bar"][data-label="long_buildup"]')).toHaveCount(10);
    await expect(page.getByTestId("lc-oi-note")).toContainText("Consolidated: the near month's price with OI summed over 3 expiries");
    // the F&O markers follow the selected series: consolidated is long build-up throughout → one marker
    await expect(page.getByTestId("lc-chart").getByTestId("desk-fno-marker")).toHaveCount(1);
  });

  test("TC-17 a month Kite has not listed yet is disabled and said", async ({ page }) => {
    const oi = clone(OI_ICICI) as typeof OI_ICICI & { missing_slots: string[]; missing_note: string | null };
    oi.contracts = oi.contracts.slice(0, 2);
    oi.missing_slots = ["far"];
    oi.missing_note = "Kite lists 2 futures for ICICIBANK right now: after an expiry the new far month is listed later in the morning, so the consolidated figure sums the 2 listed.";
    await setup(page, { oi });
    await page.goto(LIVE("ICICIBANK", `&tp=${CASH_PLAN.plan_id}`));
    await expect(page.getByTestId("lc-oi-slot-far")).toBeDisabled(SLOW);
    await expect(page.getByTestId("lc-oi-note")).toContainText("the new far month is listed later in the morning");
  });

  test("TC-20 / TC-21 the paper order ticket: no slider, quantity = account_size, the profile's risk read-only, Place → allow / block", async ({ page }) => {
    const seen = await setup(page, { post: [{ status: 409, body: { detail: CARD.cash.blocked.paper_detail } }, { status: 201, body: { trade: { id: "t-666" }, risk: null } }] });
    await page.goto(LIVE("ICICIBANK", `&tp=${CASH_PLAN.plan_id}`));
    const ticket = page.getByTestId("lc-ticket");
    await expect(ticket.getByTestId("lc-ticket-qty")).toHaveText("666 sh", SLOW);
    await expect(ticket.getByTestId("lc-ticket-paper-only")).toHaveText(/Paper only/i);
    await expect(ticket.getByTestId("lc-ticket-symbol")).toHaveText("ICICIBANK");
    await expect(ticket.getByTestId("lc-ticket-direction")).toHaveText("LONG");
    await expect(ticket.getByTestId("lc-ticket-from")).toContainText(`signal 27 OCT r2 · plan ${CASH_PLAN.plan_id}`);
    await expect(ticket.locator('[data-testid="lc-ticket-policy"]')).toHaveText(["Retest of range", "Range touch", "Next open", "At once"]);
    await expect(ticket.locator('[data-testid="lc-ticket-policy"][data-on="true"]')).toHaveText("At once");
    await expect(ticket.locator('input, [role="slider"], input[type="range"]')).toHaveCount(0);
    await expect(page.locator('input[type="range"]')).toHaveCount(0);
    await expect(ticket.getByTestId("lc-ticket-risk")).toHaveText("0.50%");
    await expect(ticket.getByTestId("lc-ticket-entry")).toHaveText("₹1,200.00");
    await expect(ticket.getByTestId("lc-ticket-stop")).toHaveText("₹1,160.00");
    await expect(ticket.getByTestId("lc-ticket-targets")).toHaveText("₹1,220.00 / ₹1,280.00");
    await expect(ticket.getByTestId("lc-ticket-value")).toHaveText("₹7,99,200");
    await expect(ticket.getByTestId("lc-ticket-risk-at-stop")).toHaveText("₹26,640");
    await expect(ticket.getByTestId("lc-ticket-rr")).toHaveText("0.50 : 1");
    await expect(ticket.getByTestId("lc-ticket-costs")).toHaveText(/₹2,58[34]/);
    await expect(ticket.getByTestId("lc-ticket-not-a-fill")).toHaveText("Entry is not a fill. The order fills only when the entry policy and trigger are met. A stop does not cap loss in a gap.");
    await expect(ticket.getByTestId("lc-ticket-footer")).toHaveText(/^Feed[^.]*\. Daily loss 0\.0% of 2\.0%\. Open risk 1\.2% of 3\.0%\. No broker order is sent\.$/);
    // the block answer, then the allow answer; the body is the Strategy Lab ticket's planCashBody (the contract's own body)
    await ticket.getByTestId("lc-ticket-place").click();
    await expect(ticket.getByTestId("lc-ticket-answer")).toHaveAttribute("data-outcome", "block");
    await expect(ticket.getByTestId("lc-ticket-answer-text")).toHaveText("Blocked by the risk service. Nothing was recorded.");
    const { source: _s, ...sentNoSource } = CARD.cash.allowed.sent;
    const { source, ...bodyNoSource } = seen.posts[0] as Record<string, unknown> & { source: Record<string, unknown> };
    expect(bodyNoSource).toEqual(sentNoSource);
    expect(source).toEqual({ kind: "scanner", bucket: "breakout_confirmed" });
    await ticket.getByTestId("lc-ticket-place").click();
    await expect(ticket.getByTestId("lc-ticket-answer")).toHaveAttribute("data-outcome", "allow");
    await expect(ticket.getByTestId("lc-ticket-answer-text")).toContainText("Allowed: 666 ICICIBANK shares placed as a paper order (t-666)");
    // the risk link goes to Risk Desk › Policy & runtime
    await ticket.getByTestId("lc-ticket-risk-link").click();
    await expect.poll(() => params(page).get("tab")).toBe("risk");
    await expect.poll(() => params(page).get("view")).toBe("controls");
  });

  test("TC-20 without ?tp= the ticket uses today's idea for the symbol", async ({ page }) => {
    await setup(page);
    await page.goto(LIVE("ICICIBANK"));
    await expect(page.getByTestId("lc-ticket-qty")).toHaveText("666 sh", SLOW);
  });

  test("TC-22 the F&O setup: build-up and wall lines, OI by strike, PCR · ATM IV · IV pctile · exp. move, the CANDIDATE STRUCTURE", async ({ page }) => {
    const seen = await setup(page);
    await page.goto(LIVE("ICICIBANK", `&tp=${CASH_PLAN.plan_id}`));
    const fno = page.getByTestId("lc-fno");
    await expect(fno.getByTestId("lc-fno-age")).toHaveText(/Chain end of day · 27 Oct/i, SLOW);
    expect(seen.chainExpiry).toContain("2026-11-24");                   // the expiry with days left, not the one expiring today
    expect(seen.chainExpiry).not.toContain("2026-10-27");
    await expect(fno.getByTestId("lc-fno-line-current")).toContainText(/Long build-up/i);
    await expect(fno.getByTestId("lc-fno-line-consolidated")).toContainText(/Long build-up/i);
    await expect(fno.getByTestId("lc-fno-line-callwall")).toContainText(/Call wall 25,300/i);
    await expect(fno.getByTestId("lc-fno-line-putwall")).toContainText(/Put wall 24,700/i);
    await expect(fno.getByTestId("lc-fno-strike")).toHaveCount(7);
    await expect(fno.locator('[data-testid="lc-fno-strike"][data-strike="24700"]')).toHaveAttribute("data-put-oi", "3000000");
    await expect(fno.getByTestId("lc-fno-pcr")).toHaveText("0.96");
    await expect(fno.getByTestId("lc-fno-atmiv")).toHaveText(/12\.0%/);
    await expect(fno.getByTestId("lc-fno-ivp")).toHaveText("not recorded");
    await expect(fno.getByTestId("lc-fno-em")).toHaveText("±487.05");
    await expect(fno.getByTestId("lc-structure-title")).toHaveText(/Candidate structure/i);
    await expect(fno.getByTestId("lc-structure-name")).toContainText("Bear put spread 1360/1380");
    await expect(fno.getByTestId("lc-structure-leg")).toHaveCount(2);
    await expect(fno.getByTestId("lc-structure-note")).toContainText("Both legs bounded. Margin is an estimate");
    await expect(fno.getByTestId("lc-structure-note")).toContainText("OI shows positioning, not who initiated it.");
    await expect(page.getByTestId("lc-view")).not.toContainText(/suggest/i);
    await expect(page.getByTestId("lc-view")).not.toContainText(/F&O Lab ↗/);
    await fno.getByTestId("lc-structure-lab").click();
    await expect.poll(() => params(page).get("view")).toBe("lab");
    await expect.poll(() => params(page).get("sub")).toBe("build");
  });

  test("TC-23 the signal conditions: ✓ / ○ / — with values and the note", async ({ page }) => {
    await setup(page);
    await page.goto(LIVE("ICICIBANK", `&tp=${CASH_PLAN.plan_id}`));
    const c = page.getByTestId("lc-conditions");
    await expect(c.getByTestId("lc-cond-ema20")).toHaveText("✓15m close above 20 EMA (1,213.0 > 1,203.6)", SLOW);
    await expect(c.getByTestId("lc-cond-volume")).toHaveText("✓Volume ≥ 1.3× 20-bar avg (1.7×)");
    await expect(c.getByTestId("lc-cond-pullback")).toHaveAttribute("data-status", "met");
    await expect(c.getByTestId("lc-cond-trigger")).toHaveText(/^—Entry trigger/);
    await expect(c.getByTestId("lc-cond-invalidation")).toHaveText("—Invalidation: close below 1,160.0 (not hit)");
    await expect(c.getByTestId("lc-conditions-note")).toContainText("Touching the range does not create a fill.");
  });

  test("TC-18 no Kite session: daily candles labelled, the bhavcopy day for the OI, the signal's levels; a pending order", async ({ page }) => {
    await setup(page, { trades: [PENDING_HDFC] });
    await page.goto(LIVE("HDFCBANK"));
    await expect(page.getByTestId("lc-kite-fallback")).toHaveText("Kite login needed for 15m candles: the platform Kite session expired. Showing daily candles (end of day).", SLOW);
    await expect(page.getByTestId("lc-chart")).toHaveAttribute("data-interval", "1d");
    await expect(page.getByTestId("lc-meta")).toContainText(/NSE · CASH · DAILY/i);
    await expect(page.getByTestId("lc-state")).toHaveText("ENTRY_PENDING");
    await expect(page.getByTestId("lc-fill-state")).toHaveText(/Order pending · no fill yet/i);
    await expect(page.getByTestId("lc-headline")).toHaveText("HDFCBANK is below its entry 750.05, but the signal's invalidation was hit (hit at 2026-09-28). No fill.");
    await expect(page.getByTestId("lc-oi")).toHaveAttribute("data-mode", "end_of_day");
    await expect(page.getByTestId("lc-oi-snapshot")).toHaveText(/End of day · 27 Oct/i);
    await expect(page.getByTestId("lc-oi-note")).toContainText("Kite login needed for 15m OI");
    await expect(page.getByTestId("lc-cond-invalidation")).toHaveAttribute("data-status", "hit");
    await expect(page.getByTestId("lc-cond-trigger")).toHaveText("○daily close above 750.05 (waiting)");
    await expect(page.getByTestId("lc-conditions-note")).toContainText("Evaluated on daily bars: the 15m candles need the day's Kite login.");
    await expect(page.getByTestId("lc-ticket-none")).toContainText("No plan for HDFCBANK today", SLOW);
    await page.getByTestId("lc-ticket-ideas").click();
    await expect.poll(() => params(page).get("view")).toBe("scanner");
    await expect.poll(() => params(page).get("sub")).toBe("ranked");
  });

  test("TC-24 390 px: the columns stack, no sideways scroll", async ({ page }) => {
    await setup(page, { phone: true });
    await page.goto(LIVE("ICICIBANK", `&tp=${CASH_PLAN.plan_id}`));
    await expect(page.getByTestId("lc-ticket-qty")).toHaveText("666 sh", SLOW);
    await expect(page.getByTestId("lc-conditions")).toBeVisible();
    const chart = await page.getByTestId("lc-chart").boundingBox();
    const ticket = await page.getByTestId("lc-ticket").boundingBox();
    expect(chart && ticket && ticket.y >= chart.y + chart.height - 1).toBeTruthy();
    await noSideScroll(page);
  });
});
