/**
 * One-screen Copilot app — Smart trading desk: the AI scanner tab and the
 * Chart analysis tab with its risk desk (screens/tradingdesk/ScannerTab,
 * ChartTab, CandleChart, RiskDesk, indicators).
 *
 * MOCK — not real data: every /api response here is an inline payload in the
 * shape the real route returns (the route's file is named beside each), with
 * synthetic values. The ~200 daily bars are generated in this file. Expected
 * figures are worked out from the payload in the test — the indicators by an
 * independent implementation of the same formulas — not copied from the
 * screen. Mocked APIs, production build — see pw.copilot-app.config.ts.
 *
 * TC-13 … TC-23 and TC-7 of test_reports/copilot_trading_desk_20261014_1200.md, plus the
 * backend round: each row's 24-session line (spark_closes) and "Liquid only"
 * (avg_traded_value_cr_20d ≥ 10), next resistance / support in the setup
 * check, and the risk desk's two writes — POST /api/desk/paper-trades and POST
 * /api/desk/alerts — with their exact bodies, pending, success and error states.
 *
 * Design fidelity (design-spec §4, §5, §10, §11 M2 / M4): section titles and
 * numbering, column headers in the design's order, control labels, the
 * trader → investor wording switch, the phone compositions and their order,
 * and no sideways scroll at 390px.
 */
import { test, expect, type Page, type Route } from "@playwright/test";
import { mockApi, mockSingleRoute } from "../helpers/api-mock";

const DESK = "/v5/app/trader/desk";
/** A failed request is retried by the client and once by the query, so an error block takes a few seconds. */
const SLOW = { timeout: 15_000 };

const json = (page: Page, pattern: string | RegExp, body: unknown, status = 200) =>
  page.route(pattern, (route) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) }));

// ── payloads ─────────────────────────────────────────────────────────────

/** `n` daily closes from `from` to `to`, oldest first, with a small wobble (spark_closes, stock_ohlcv). */
const spark = (from: number, to: number, n = 24) =>
  Array.from({ length: n }, (_, i) => Math.round((from + ((to - from) * i) / (n - 1) + (i % 2 && i < n - 1 ? 0.6 : 0)) * 100) / 100);

// backend/routes/positional.py :: get_watchlist. spark_closes ≤ 24 oldest first; avg_traded_value_cr_20d null with fewer
// than 20 sessions. FIXTRD's line carries a null and a numeric string, as a defensive-parse check.
const WATCHLIST = {
  as_of_date: "2026-10-13", is_weekend_mode: false, is_weekend: false, days_stale: 1, total_count: 4,
  bucket_counts: { breakout_confirmed: 1, pre_breakout: 1, true_accumulation: 1, trend_continuation: 1 },
  buckets: {
    breakout_confirmed: [{
      nse_symbol: "FIXBRK", sector: "Capital Goods", stage: "BREAKOUT", confidence: "HIGH", final_score: 0.79, close_price: 510.0,
      trigger_price: 500.0, stop_price: 477.5, atr_pct: 2.94, rsi_14: 64.2, sma_50: 470.0, sma_200: 430.0, ema_20: 492.1,
      signals: { range_pct_15d: 9.1, volume_slope_10d_pct: 2.1, volume_spike_3v20: 1.8, higher_lows_count: 2, upper_wick_pct: 0.2, delivery_trend_pct: 4.0, dist_breakout_pct: 2.0, dist_ema20_pct: 3.64 },
      why: "Broke above ₹500.00 (+2.0%) on 1.8× avg volume",
      resistance_level: 530.0, support_level: 492.0,
      spark_closes: spark(480, 510) as unknown[], spark_end: "2026-10-13", avg_traded_value_cr_20d: 42.6 as number | null,
    }],
    pre_breakout: [{
      nse_symbol: "FIXPRE", sector: "Chemicals", stage: "EARLY_BREAKOUT", confidence: "MEDIUM", final_score: 0.74, close_price: 245.0,
      trigger_price: 250.0, stop_price: 238.0, atr_pct: 3.1, rsi_14: 58.0, sma_50: 236.0, sma_200: 220.0, ema_20: 241.0,
      signals: { range_pct_15d: 7.2, volume_slope_10d_pct: 1.0, volume_spike_3v20: 1.3, higher_lows_count: 1, upper_wick_pct: 0.3, delivery_trend_pct: null, dist_breakout_pct: -2.0, dist_ema20_pct: 1.66 },
      why: "2.0% below ₹250.00 resistance · volume 1.3× avg",
      resistance_level: 250.0, support_level: 238.5,
      spark_closes: spark(260, 245) as unknown[], spark_end: "2026-10-13", avg_traded_value_cr_20d: 3.2 as number | null,
    }],
    true_accumulation: [{
      nse_symbol: "FIXACC", sector: "Textiles", stage: "ACCUMULATION", confidence: "LOW", final_score: 0.62, close_price: 88.5,
      trigger_price: 92.0, stop_price: 84.0, atr_pct: 2.2, rsi_14: 51.0, sma_50: 87.0, sma_200: 90.0, ema_20: 88.0,
      signals: { range_pct_15d: 6.1, volume_slope_10d_pct: -1.4, volume_spike_3v20: 0.8, higher_lows_count: 2, upper_wick_pct: 0.1, delivery_trend_pct: 3.0, dist_breakout_pct: -3.8, dist_ema20_pct: 0.57 },
      why: "Tight 6.1% range, vol drying -1.4%/d, 2 higher lows",
      resistance_level: null, support_level: null,
      spark_closes: [] as unknown[], spark_end: null, avg_traded_value_cr_20d: 11.0 as number | null,
    }],
    trend_continuation: [{
      nse_symbol: "FIXTRD", sector: "IT", stage: "ACCUMULATION", confidence: "MEDIUM", final_score: 0.69, close_price: 1210.0,
      trigger_price: null, stop_price: 1150.0, atr_pct: 1.9, rsi_14: 61.0, sma_50: 1150.0, sma_200: 1100.0, ema_20: 1190.0,
      signals: { range_pct_15d: 8.4, volume_slope_10d_pct: 0.4, volume_spike_3v20: 1.0, higher_lows_count: 1, upper_wick_pct: 0.2, delivery_trend_pct: null, dist_breakout_pct: null, dist_ema20_pct: 1.68 },
      why: "Trend intact (close > 20EMA ₹1190.00 > 50EMA), 1.7% above 20EMA — pullback zone",
      resistance_level: 1250.0, support_level: 1150.0,
      spark_closes: [...spark(1150, 1205, 12), null, "1210"] as unknown[], spark_end: "2026-10-13", avg_traded_value_cr_20d: null as number | null,
    }],
  },
  _classifier_version: "smart_v2",
};

// backend/routes/positional.py :: get_picks. FIXBRK is in both routes: the pick's plan (entry, stop, target) and score win.
const PICKS = {
  signal_date: "2026-10-13", count: 2,
  picks: [
    { nse_symbol: "FIXBRK", signal_date: "2026-10-13", final_score: 0.86, confidence: "HIGH", stage: "BREAKOUT", timeframe_days_min: 5, timeframe_days_max: 15,
      entry_price: 505.0, stoploss: 480.0, target_price: 555.0, risk_reward: 2.0, source_scans: ["btst.breakout_confirmation"], reasons: ["Closed above a 60-day high on rising volume"],
      spark_closes: spark(480, 510), spark_end: "2026-10-13", avg_traded_value_cr_20d: 42.6 },
    // Exactly ₹10 Cr a day: "Liquid only" is ≥ 10, so it stays.
    { nse_symbol: "FIXPICK", signal_date: "2026-10-13", final_score: 0.81, confidence: "MEDIUM", stage: "EARLY_BREAKOUT", timeframe_days_min: 3, timeframe_days_max: 10,
      entry_price: 120.0, stoploss: 114.0, target_price: 138.0, risk_reward: 3.0, source_scans: ["swing.pullback"], reasons: ["Fixture pick reason"],
      spark_closes: spark(110, 120), spark_end: "2026-10-13", avg_traded_value_cr_20d: 10.0 },
  ],
};

// backend/nidp/services/daas_api/routers/move_odds.py :: latest, proxied by backend/routes/move_odds.py
const RUN = {
  model: "v4", refit: "monthly", status: "final", data_as_of: "2026-10-13", target_session: "2026-10-14", frozen_at: "2026-10-13T20:50:22+05:30",
  git_sha: "0fix000", universe_size: 1000, scored: 994, input_count: 84, train_rows: 366080, train_end: "2026-08-31", counts_toward_verdict: true, skipped_holidays: [],
};
const ODDS_ROWS = [
  { symbol: "FIXPRE", company_name: "Fixture Pre Ltd", sector: "Chemicals", p: 0.2412, p_opposite: 0.06, events_on_record: 0 },
  { symbol: "FIXBRK", company_name: "Fixture Breakout Ltd", sector: "Capital Goods", p: 0.1834, p_opposite: 0.05, events_on_record: 3 },
  { symbol: "FIXACC", company_name: "Fixture Accumulation Ltd", sector: "Textiles", p: 0.0412, p_opposite: 0.03, events_on_record: 1 },
];
// The +10% head ranks the stocks differently, so "Rank by P(+10% next session)" is a different order.
const ODDS10_ROWS = [
  { symbol: "FIXACC", company_name: "Fixture Accumulation Ltd", sector: "Textiles", p: 0.0912, p_opposite: 0.01, events_on_record: 1 },
  { symbol: "FIXBRK", company_name: "Fixture Breakout Ltd", sector: "Capital Goods", p: 0.0312, p_opposite: 0.01, events_on_record: 3 },
  { symbol: "FIXPRE", company_name: "Fixture Pre Ltd", sector: "Chemicals", p: 0.0205, p_opposite: 0.01, events_on_record: 0 },
];
const ROWS_BY_HEAD: Record<string, typeof ODDS_ROWS> = { p_up10_1d: ODDS10_ROWS };
const RECORD = { window_label: "Jan–Aug 2025", sessions: 165, base_rate: 0.0812, top10_hit_rate: 0.3103, bands: [] };
const BASE_RATE: Record<string, number> = { p_up5_1d: 0.0758, p_down5_1d: 0.0611, p_up10_1d: 0.0153, p_down10_1d: 0.0088 };
const latest = (head: string) => ({
  data: {
    status: "final", head, expected_session: "2026-10-14", base_rate: BASE_RATE[head], run: RUN, rows: ROWS_BY_HEAD[head] ?? ODDS_ROWS, record: RECORD,
    live_record: { sessions: 0, top10_hits: null, touched: null, graded_rows: null, last_target: null, last_top10_hits: null, last_touched: null, last_graded_rows: null },
    limits: { not_used: ["analyst estimates"] },
  },
});

// move_odds.py :: stock
const EVENT = (ord: number) => ({
  ord, event_time: `2026-10-1${ord}T12:35:20+05:30`, source_label: "NSE filing", is_media: false, event_type: "CORPORATE", event_subtype: "update",
  direction: "neutral", title: `Fixture filing ${ord}`, url: null, method: "rules",
});
const STOCK_FIXBRK = {
  data: {
    symbol: "FIXBRK", company_name: "Fixture Breakout Ltd", sector: "Capital Goods", results_filed: false, run: RUN,
    estimates: { p_up5_1d: 0.1834, p_down5_1d: 0.0421, p_up10_1d: 0.0312, p_down10_1d: 0.0065 },
    inputs: { close_change_pct: { v: 2.1, date: "2026-10-13" } },
    events: [EVENT(1), EVENT(2), EVENT(3)],
  },
};

type Bar = [string, number, number, number, number, number];
const r2 = (v: number) => Math.round(v * 100) / 100;

/** ~200 weekday sessions ending 13 Oct 2026, a wave on a gentle uptrend, with a volume spike on the last session. */
function makeBars(n = 200, end = "2026-10-13"): Bar[] {
  const days: string[] = [];
  for (let t = Date.parse(`${end}T00:00:00Z`); days.length < n; t -= 86_400_000) {
    const wd = new Date(t).getUTCDay();
    if (wd !== 0 && wd !== 6) days.unshift(new Date(t).toISOString().slice(0, 10));
  }
  const out: Bar[] = [];
  let prev = 480;
  for (let i = 0; i < n; i++) {
    const close = r2(480 + 25 * Math.sin(i / 7) + 0.15 * i + 6 * Math.cos(i / 3));
    const open = r2(prev + 2 * Math.sin(i * 1.3));
    const high = r2(Math.max(open, close) + 3 + 2 * Math.abs(Math.sin(i * 0.7)));
    const low = r2(Math.min(open, close) - 3 - 2 * Math.abs(Math.cos(i * 0.9)));
    const volume = 100_000 + ((i * 7919) % 60_000) + (i === n - 1 ? 150_000 : 0);
    out.push([days[i], open, high, low, close, volume]);
    prev = close;
  }
  return out;
}
const BARS = makeBars();
// backend/routes/research_chart_live.py :: ohlcv
const ohlcv = (symbol: string) => ({
  symbol, timeframe: "1D", bars: BARS, data_quality_status: "VALID", pit_status: "PIT_UNVERIFIED", findings: [],
  provenance: { provider: "nidp.prices_eod_adjusted", series: "EQ", adjustment_status: "SPLIT_BONUS_ADJUSTED", last_bar_date: BARS[BARS.length - 1][0], source_mode: "live", last_event_type: null },
});

// ── mocks ────────────────────────────────────────────────────────────────

interface Over {
  watchStatus?: number;
  picksStatus?: number;
  oddsStatus?: number;
  barsStatus?: number;
}

type Reply = { status: number; body: unknown };
interface Posted { method: string; path: string; body: unknown }

/**
 * POST /api/desk/paper-trades and POST /api/desk/alerts (backend/routes/desk_trading.py): records each call with its
 * JSON body and answers 201 { trade } / { alert } echoing it, or the given reply. `gate` holds every answer until it
 * resolves, so a test can see the pending state.
 */
async function mockDeskWrites(page: Page, opts: { paper?: Reply; alert?: Reply; gate?: Promise<void> } = {}): Promise<Posted[]> {
  const posted: Posted[] = [];
  const handle = (kind: "paper" | "alert") => async (route: Route) => {
    const req = route.request();
    const body = req.postDataJSON() as Record<string, unknown>;
    posted.push({ method: req.method(), path: new URL(req.url()).pathname, body });
    if (opts.gate) await opts.gate;
    const reply = kind === "paper" ? opts.paper : opts.alert;
    if (reply) return route.fulfill({ status: reply.status, contentType: "application/json", body: JSON.stringify(reply.body) });
    const now = "2026-10-14T10:00:00+00:00";
    const echo = kind === "paper"
      ? { trade: { id: `pt-${posted.length}`, ...body, note: null, opened_at: now, status: "open", closed_at: null, exit_price: null, exit_reason: null, last_close: null, last_close_date: null, unrealized_pnl_rs: null, realized_pnl_rs: null } }
      : { alert: { id: `al-${posted.length}`, ...body, note: null, created_at: now, status: "active", fired_at: null, fired_session: null, fired_price: null } };
    return route.fulfill({ status: 201, contentType: "application/json", body: JSON.stringify(echo) });
  };
  await page.route("**/api/desk/paper-trades", handle("paper"));
  await page.route("**/api/desk/alerts", handle("alert"));
  return posted;
}

async function deskMocks(page: Page, over: Over = {}) {
  await mockApi(page, "populated");
  await mockSingleRoute(page, "**/api/markets/home", "markets-home.json");
  await page.route("**/api/chat/sessions", (route) => route.fulfill({ status: 200, contentType: "application/json", body: "[]" }));
  await json(page, "**/api/positional/watchlist*", over.watchStatus ? { detail: "fixture failure" } : WATCHLIST, over.watchStatus ?? 200);
  await json(page, "**/api/positional/picks*", over.picksStatus ? { detail: "fixture failure" } : PICKS, over.picksStatus ?? 200);
  await page.route("**/api/move-odds/latest*", (route) => {
    const head = new URL(route.request().url()).searchParams.get("head") ?? "p_up5_1d";
    if (over.oddsStatus) return route.fulfill({ status: over.oddsStatus, contentType: "application/json", body: JSON.stringify({ detail: "Feature not enabled" }) });
    return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(latest(head)) });
  });
  await page.route("**/api/move-odds/stocks/*", (route) => {
    const sym = new URL(route.request().url()).pathname.split("/").pop();
    if (over.oddsStatus) return route.fulfill({ status: over.oddsStatus, contentType: "application/json", body: JSON.stringify({ detail: "Feature not enabled" }) });
    if (sym === "FIXBRK") return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(STOCK_FIXBRK) });
    return route.fulfill({ status: 404, contentType: "application/json", body: JSON.stringify({ detail: `${sym} is not in the published run` }) });
  });
  await page.route("**/api/research/chart-live/*/ohlcv*", (route) => {
    const sym = new URL(route.request().url()).pathname.split("/").slice(-2)[0];
    if (over.barsStatus) {
      const detail = over.barsStatus === 404 ? "no_bars_for_symbol" : "Feature not enabled";
      return route.fulfill({ status: over.barsStatus, contentType: "application/json", body: JSON.stringify({ detail }) });
    }
    return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(ohlcv(sym)) });
  });
}

/** Writes (anything but GET) to /api/* made by the page. */
function recordWrites(page: Page): string[] {
  const writes: string[] = [];
  page.on("request", (req) => {
    if (req.method() !== "GET" && /\/api\//.test(new URL(req.url()).pathname)) writes.push(`${req.method()} ${req.url()}`);
  });
  return writes;
}

async function rowOrder(page: Page): Promise<string[]> {
  const ids = await page.locator('[data-testid^="desk-scan-row-"]').evaluateAll((els) => els.map((e) => e.getAttribute("data-testid") ?? ""));
  return ids.map((id) => id.replace("desk-scan-row-", ""));
}

async function sidewaysOverflow(page: Page) {
  return page.evaluate(() => {
    const sc = document.querySelector('[data-testid="copilot-scroll"]') as HTMLElement | null;
    return {
      doc: document.documentElement.scrollWidth - window.innerWidth,
      scroll: sc ? sc.scrollWidth - sc.clientWidth : 0,
    };
  });
}

// ── expected values, worked out from the payload ─────────────────────────

type Watch = (typeof WATCHLIST.buckets.breakout_confirmed)[number] | (typeof WATCHLIST.buckets.trend_continuation)[number];
const BUCKETS = ["breakout_confirmed", "pre_breakout", "trend_continuation", "true_accumulation"] as const;

/** The merge rule restated: one row per symbol; the pick's score and plan win; status from the bucket, else the stage. */
function expectedRows() {
  const rows = new Map<string, { score: number; bucket: string | null; stage: string; close: number | null; entry: number | null; target: number | null; rr: number | null }>();
  for (const b of BUCKETS) {
    for (const w of WATCHLIST.buckets[b] as Watch[]) {
      rows.set(w.nse_symbol, { score: w.final_score * 100, bucket: b, stage: w.stage, close: w.close_price, entry: w.trigger_price, target: null, rr: null });
    }
  }
  for (const p of PICKS.picks) {
    const have = rows.get(p.nse_symbol);
    rows.set(p.nse_symbol, { score: p.final_score * 100, bucket: have?.bucket ?? null, stage: have?.stage ?? p.stage, close: have?.close ?? null, entry: p.entry_price, target: p.target_price, rr: p.risk_reward });
  }
  const status = (r: { bucket: string | null; stage: string }) =>
    r.bucket === "breakout_confirmed" ? "confirmed"
      : r.bucket === "pre_breakout" || r.bucket === "trend_continuation" ? "awaiting"
        : r.bucket === "true_accumulation" ? "forming"
          : r.stage === "BREAKOUT" ? "confirmed" : r.stage === "EARLY_BREAKOUT" ? "awaiting" : "forming";
  return [...rows.entries()].map(([symbol, r]) => ({ symbol, ...r, status: status(r) }));
}

const desc = (a: number | null, b: number | null) => (a == null && b == null ? 0 : a == null ? 1 : b == null ? -1 : b - a);
const pct1 = (p: number) => `${(p * 100).toFixed(1)}%`;
const inr2 = (v: number) => `₹${new Intl.NumberFormat("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(v)}`;
const inr0 = (v: number) => `₹${new Intl.NumberFormat("en-IN").format(Math.round(v))}`;

// Independent restatement of indicators.ts (different code, same definitions).
function emaLast(xs: number[], n: number): number {
  let e = xs.slice(0, n).reduce((a, b) => a + b, 0) / n;
  for (const x of xs.slice(n)) e += (2 / (n + 1)) * (x - e);
  return e;
}
function rsiLast(xs: number[], n = 14): number {
  const d = xs.slice(1).map((x, i) => x - xs[i]);
  let g = d.slice(0, n).reduce((a, x) => a + Math.max(x, 0), 0) / n;
  let l = d.slice(0, n).reduce((a, x) => a + Math.max(-x, 0), 0) / n;
  for (const x of d.slice(n)) {
    g = (g * (n - 1) + Math.max(x, 0)) / n;
    l = (l * (n - 1) + Math.max(-x, 0)) / n;
  }
  return (100 * g) / (g + l);
}
function atrLast(bars: Bar[], n = 14): number {
  const tr = bars.slice(1).map((b, i) => Math.max(b[2] - b[3], Math.abs(b[2] - bars[i][4]), Math.abs(b[3] - bars[i][4])));
  let a = tr.slice(0, n).reduce((s, x) => s + x, 0) / n;
  for (const x of tr.slice(n)) a = (a * (n - 1) + x) / n;
  return a;
}
function vwapLast(bars: Bar[], n = 20): number {
  const w = bars.slice(-n);
  return w.reduce((s, b) => s + ((b[2] + b[3] + b[4]) / 3) * b[5], 0) / w.reduce((s, b) => s + b[5], 0);
}
function rvolLast(bars: Bar[], n = 20): number {
  const prev = bars.slice(-(n + 1), -1);
  return bars[bars.length - 1][5] / (prev.reduce((s, b) => s + b[5], 0) / n);
}

const signedPct = (v: number, d = 1) => `${v > 0 ? "+" : v < 0 ? "−" : ""}${Math.abs(v).toFixed(d)}%`;
const enIN = (v: number, d = 2) => new Intl.NumberFormat("en-IN", { minimumFractionDigits: d, maximumFractionDigits: d }).format(v);

/** The daily closes a row draws: the watchlist's line when it has one, else the pick's; only positive numbers. */
function lineOf(sym: string): number[] {
  const clean = (xs: unknown[]) => xs.map((v) => (v == null ? NaN : Number(v))).filter((n) => Number.isFinite(n) && n > 0);
  for (const b of BUCKETS) {
    const w = (WATCHLIST.buckets[b] as Array<{ nse_symbol: string; spark_closes: unknown[] }>).find((x) => x.nse_symbol === sym);
    if (w && clean(w.spark_closes).length > 1) return clean(w.spark_closes);
  }
  return clean(PICKS.picks.find((x) => x.nse_symbol === sym)?.spark_closes ?? []);
}

/** Traded value per stock: the watchlist's when it has one, else the pick's. */
function tradedOf(sym: string): number | null {
  for (const b of BUCKETS) {
    const w = (WATCHLIST.buckets[b] as Array<{ nse_symbol: string; avg_traded_value_cr_20d: number | null }>).find((x) => x.nse_symbol === sym);
    if (w && w.avg_traded_value_cr_20d != null) return w.avg_traded_value_cr_20d;
  }
  return PICKS.picks.find((x) => x.nse_symbol === sym)?.avg_traded_value_cr_20d ?? null;
}

/** Top of an element, to check the order blocks are stacked in. */
async function topOf(page: Page, testId: string): Promise<number> {
  const box = await page.getByTestId(testId).first().boundingBox();
  if (!box) throw new Error(`${testId} has no box`);
  return box.y;
}

const texts = (page: Page, selector: string) => page.locator(selector).allTextContents();

// ── AI scanner ───────────────────────────────────────────────────────────

test.describe("Smart trading desk · AI scanner", () => {
  test("TC-13 merged rows are ranked by score, status follows the bucket, and the pick's plan wins", async ({ page }) => {
    await deskMocks(page);
    await page.goto(`${DESK}?tab=scanner`);
    await expect(page.getByTestId("desk-scanner")).toBeVisible();

    const exp = expectedRows();
    const byScore = [...exp].sort((a, b) => b.score - a.score).map((r) => r.symbol);
    expect(await rowOrder(page)).toEqual(byScore);
    await expect(page.getByTestId("desk-scan-eyebrow")).toHaveText(`NSE · end of day 13 Oct 2026 · next-session odds · ${exp.length} of ${exp.length} shown`);

    for (const [i, r] of [...exp].sort((a, b) => b.score - a.score).entries()) {
      const row = page.getByTestId(`desk-scan-row-${r.symbol}`);
      await expect(row.getByTestId("desk-scan-rank")).toHaveText(String(i + 1).padStart(2, "0"));
      await expect(row.getByTestId("desk-scan-status")).toHaveAttribute("data-status", r.status);
      await expect(row.getByTestId("desk-scan-score")).toHaveText(String(Math.round(r.score)));
      // To target: from the close (else the entry) to the pick's target; "—" without a target.
      const base = r.close ?? r.entry;
      const to = r.target != null && base != null ? `+${(((r.target - base) / base) * 100).toFixed(1)}%` : "—";
      await expect(row.getByTestId("desk-scan-target")).toHaveText(to);
      // No per-setup back-tested record is published: the hit-rate cell is "—".
      await expect(row.getByTestId("desk-scan-hit")).toHaveText("—");
      // The stock's last close and its change, from its own daily closes.
      const line = lineOf(r.symbol);
      if (line.length > 1) {
        const [a, b] = line.slice(-2);
        await expect(row).toContainText(inr2(b));
        await expect(row.getByTestId("desk-scan-change")).toHaveText(signedPct(((b - a) / a) * 100));
      }
    }
    // FIXBRK is in both routes: one row, the pick's score (86, not the watchlist's 79) and its target (555 from the 510 close).
    await expect(page.locator('[data-testid="desk-scan-row-FIXBRK"]')).toHaveCount(1);
    const brk = page.getByTestId("desk-scan-row-FIXBRK");
    await expect(brk.getByTestId("desk-scan-score")).toHaveText(String(Math.round(PICKS.picks[0].final_score * 100)));
    await expect(brk.getByTestId("desk-scan-setup")).toHaveText("Breakout confirmed");
    await expect(brk.getByTestId("desk-scan-why")).toHaveText(WATCHLIST.buckets.breakout_confirmed[0].why);
    await expect(brk.getByTestId("desk-scan-symbol")).toHaveText("FIXBRK");
    // A pick the watchlist does not have: its status comes from the stage.
    await expect(page.getByTestId("desk-scan-row-FIXPICK").getByTestId("desk-scan-setup")).toHaveText("Scanner pick · early breakout");
    await expect(page.getByTestId("desk-scan-footnote")).toContainText("it is not a probability");
  });

  test("TC-14 group chips filter the list and P(+10% next session) re-ranks it and switches the column", async ({ page }) => {
    await deskMocks(page);
    await page.goto(`${DESK}?tab=scanner`);
    const exp = expectedRows();

    await page.getByTestId("desk-scan-group-breakout_confirmed").click();
    await expect(page.getByTestId("desk-scan-group-breakout_confirmed")).toHaveAttribute("aria-pressed", "true");
    expect(await rowOrder(page)).toEqual(exp.filter((r) => r.bucket === "breakout_confirmed").map((r) => r.symbol));
    await expect(page.getByTestId("desk-scan-eyebrow")).toHaveText(`NSE · end of day 13 Oct 2026 · next-session odds · 1 of ${exp.length} shown`);

    await page.getByTestId("desk-scan-group-trend_continuation").click();
    expect(await rowOrder(page)).toEqual(exp.filter((r) => r.bucket === "trend_continuation").map((r) => r.symbol));
    await page.getByTestId("desk-scan-group-true_accumulation").click();
    expect(await rowOrder(page)).toEqual(exp.filter((r) => r.bucket === "true_accumulation").map((r) => r.symbol));

    await page.getByTestId("desk-scan-group-all").click();
    await page.getByTestId("desk-scan-rank-p10").click();
    await expect(page.getByTestId("desk-scan-rank-p10")).toHaveAttribute("aria-pressed", "true");
    const p10 = new Map(ODDS10_ROWS.map((r) => [r.symbol, r.p]));
    const byP10 = [...exp].sort((a, b) => desc(p10.get(a.symbol) ?? null, p10.get(b.symbol) ?? null) || b.score - a.score).map((r) => r.symbol);
    expect(await rowOrder(page)).toEqual(byP10);
    expect(byP10[0]).toBe("FIXACC"); // the +10% head puts FIXACC first, above the higher-scored FIXBRK
    for (const r of exp) {
      const p = p10.get(r.symbol);
      await expect(page.getByTestId(`desk-scan-row-${r.symbol}`).getByTestId("desk-scan-odds")).toHaveText(p != null ? pct1(p) : "—");
      await expect(page.getByTestId(`desk-scan-row-${r.symbol}`).getByTestId("desk-scan-odds")).toHaveAttribute("data-head", "p_up10_1d");
    }
    await expect(page.getByTestId("desk-scan-footnote")).toContainText("previous close plus 10%, one session only");
  });

  test("TC-15 published odds: P(+5% next session) and events per row, the model's record, and ranking by it", async ({ page }) => {
    await deskMocks(page);
    await page.goto(`${DESK}?tab=scanner`);
    await expect(page.getByTestId("desk-scan-record")).toHaveAttribute("data-state", "final");
    await expect(page.getByTestId("desk-scan-record")).toHaveText(`Move-odds ${RUN.model} · out-of-sample ${RECORD.window_label}`);
    const bySym = new Map(ODDS_ROWS.map((r) => [r.symbol, r]));
    for (const r of expectedRows()) {
      const row = page.getByTestId(`desk-scan-row-${r.symbol}`);
      const o = bySym.get(r.symbol);
      await expect(row.getByTestId("desk-scan-odds")).toHaveText(o ? pct1(o.p) : "—");
      // Events on record ride on the pattern line as the catalyst; none → no catalyst text.
      if (o && o.events_on_record > 0) await expect(row.getByTestId("desk-scan-catalyst")).toHaveText(`+ ${o.events_on_record} ${o.events_on_record === 1 ? "event" : "events"} · `);
      else await expect(row.getByTestId("desk-scan-catalyst")).toHaveCount(0);
    }
    await expect(page.getByTestId("desk-scan-model-note")).toHaveText(
      `Out-of-sample ${RECORD.window_label}: top-10 hit rate ${pct1(RECORD.top10_hit_rate)} over ${RECORD.sessions} sessions vs base rate ${pct1(RECORD.base_rate)}. Run on data of 13 Oct 2026, for the session of 14 Oct 2026.`,
    );

    await page.getByTestId("desk-scan-rank-p5").click();
    const exp = expectedRows();
    const byP = [...exp].sort((a, b) => desc(bySym.get(a.symbol)?.p ?? null, bySym.get(b.symbol)?.p ?? null) || b.score - a.score).map((r) => r.symbol);
    expect(await rowOrder(page)).toEqual(byP);
  });

  test("TC-15 odds 403: every probability is “—” and the account is told it is not enabled", async ({ page }) => {
    await deskMocks(page, { oddsStatus: 403 });
    await page.goto(`${DESK}?tab=scanner`);
    await expect(page.getByTestId("desk-scan-record")).toHaveAttribute("data-state", "no_access");
    await expect(page.getByTestId("desk-scan-record")).toHaveText("Move-odds · not enabled for this account");
    await expect(page.getByTestId("desk-scan-model-note")).toContainText("Move probabilities are not enabled for this account");
    for (const r of expectedRows()) {
      const row = page.getByTestId(`desk-scan-row-${r.symbol}`);
      await expect(row.getByTestId("desk-scan-odds")).toHaveText("—");
      await expect(row.getByTestId("desk-scan-catalyst")).toHaveCount(0);
    }
    await expect(page.getByTestId("desk-scan-rank-p5")).toBeDisabled();
    await expect(page.getByTestId("desk-scan-rank-p10")).toBeDisabled();
  });

  test("each row draws its last daily closes from spark_closes and names its 20-session traded value", async ({ page }) => {
    await deskMocks(page);
    await page.goto(`${DESK}?tab=scanner`);
    await expect(page.getByTestId("desk-scanner")).toBeVisible();
    for (const r of expectedRows()) {
      const row = page.getByTestId(`desk-scan-row-${r.symbol}`);
      // Only positive numbers are drawn: a null in the series is dropped, a numeric string is read.
      const pts = lineOf(r.symbol);
      if (pts.length > 1) {
        await expect(row.getByTestId("desk-scan-spark")).toHaveAttribute("data-points", String(pts.length));
        const tone = pts[pts.length - 1] > pts[0] ? "mint" : pts[pts.length - 1] < pts[0] ? "danger" : "ink";
        await expect(row.getByTestId("desk-scan-spark")).toHaveAttribute("data-tone", tone);
        await expect(row.getByTestId("desk-scan-spark").locator("polyline")).toHaveCount(1);
      } else {
        await expect(row.getByTestId("desk-scan-spark")).toHaveCount(0);
        await expect(row.getByTestId("desk-scan-spark-none")).toHaveText("No line");
      }
      const cr = tradedOf(r.symbol);
      await expect(row.getByTestId("desk-scan-traded")).toHaveText(cr == null ? "No traded value" : `₹${cr.toFixed(1)} Cr a day`);
    }
    await expect(page.getByTestId("desk-scan-footnote")).toContainText("each stock’s last daily closes to 13 Oct 2026, end of day");
  });

  test("Liquid only keeps stocks trading ₹10 Cr a day or more, says the rule, and counts the ones without a figure", async ({ page }) => {
    await deskMocks(page);
    await page.goto(`${DESK}?tab=scanner`);
    const exp = expectedRows();
    const toggle = page.getByTestId("desk-scan-liquid");
    await expect(toggle).toHaveAttribute("aria-pressed", "false");
    await expect(toggle).toHaveText("Liquid only · ADV ≥ ₹10 Cr");
    await expect(page.getByTestId("desk-scan-liquid-note")).toHaveCount(0);

    const liquid = exp.filter((r) => (tradedOf(r.symbol) ?? -1) >= 10);
    const lacking = exp.filter((r) => tradedOf(r.symbol) == null);
    expect(liquid.map((r) => r.symbol).sort()).toEqual(["FIXACC", "FIXBRK", "FIXPICK"]); // FIXPICK sits exactly at 10
    expect(lacking.map((r) => r.symbol)).toEqual(["FIXTRD"]);

    await toggle.click();
    await expect(toggle).toHaveAttribute("aria-pressed", "true");
    expect(await rowOrder(page)).toEqual([...liquid].sort((a, b) => b.score - a.score).map((r) => r.symbol));
    await expect(page.getByTestId("desk-scan-eyebrow")).toHaveText(`NSE · end of day 13 Oct 2026 · next-session odds · ${liquid.length} of ${exp.length} shown`);
    const note = page.getByTestId("desk-scan-liquid-note");
    await expect(note).toContainText("average daily traded value (close × volume) over the last 20 sessions of at least ₹10 Cr");
    await expect(note).toContainText(`${lacking.length} stock has no traded-value figure and is not shown while this is on.`);

    // With a group chosen, the count is the group's: the trend pullback (FIXTRD) has no figure, so nothing is left.
    await page.getByTestId("desk-scan-group-trend_continuation").click();
    await expect(page.getByTestId("desk-scan-group-empty")).toHaveText("No setup in this group trades ₹10 Cr or more a day on average.");
    await expect(note).toContainText("1 stock has no traded-value figure");
    await page.getByTestId("desk-scan-group-breakout_confirmed").click();
    await expect(note).toContainText("Every stock here has a traded-value figure.");

    // Off again: everything is back.
    await page.getByTestId("desk-scan-group-all").click();
    await toggle.click();
    await expect(toggle).toHaveAttribute("aria-pressed", "false");
    expect((await rowOrder(page)).length).toBe(exp.length);
  });

  test("TC-16 a row opens the Chart tab with that stock, and the selected stock's row is marked", async ({ page }) => {
    await deskMocks(page);
    await page.goto(`${DESK}?tab=scanner&sym=FIXACC`);
    await expect(page.getByTestId("desk-scan-row-FIXACC")).toHaveAttribute("data-selected", "true");
    await expect(page.getByTestId("desk-scan-row-FIXBRK")).toHaveAttribute("data-selected", "false");
    await page.getByTestId("desk-scan-row-FIXPRE").click();
    await expect(page).toHaveURL(/[?&]tab=chart(&|$)/);
    await expect(page).toHaveURL(/[?&]sym=FIXPRE(&|$)/);
    await expect(page.getByTestId("desk-chart-symbol")).toHaveText("FIXPRE");
  });

  test("TC-17 both scanner routes fail → error with retry", async ({ page }) => {
    await deskMocks(page, { watchStatus: 500, picksStatus: 500 });
    await page.goto(`${DESK}?tab=scanner`);
    const err = page.getByTestId("desk-scan-error");
    await expect(err).toBeVisible(SLOW);
    await expect(err.getByRole("alert")).toContainText("The scanner didn’t load");
    await expect(err.getByRole("button", { name: "Retry ›" })).toBeVisible();
  });

  test("TC-17 one scanner route fails → the other's rows and a note naming the route", async ({ page }) => {
    await deskMocks(page, { picksStatus: 500 });
    await page.goto(`${DESK}?tab=scanner`);
    await expect(page.getByTestId("desk-scan-partial")).toContainText("GET /api/positional/picks", SLOW);
    const watchOnly = BUCKETS.flatMap((b) => (WATCHLIST.buckets[b] as Watch[]).map((w) => w.nse_symbol));
    expect((await rowOrder(page)).sort()).toEqual([...watchOnly].sort());
    // Without the picks there is no target anywhere.
    for (const s of watchOnly) await expect(page.getByTestId(`desk-scan-row-${s}`).getByTestId("desk-scan-target")).toHaveText("—");
  });

  test("an empty scan says so and names the scan date", async ({ page }) => {
    await deskMocks(page);
    await json(page, "**/api/positional/watchlist*", { ...WATCHLIST, buckets: { breakout_confirmed: [], pre_breakout: [], true_accumulation: [], trend_continuation: [] } });
    await json(page, "**/api/positional/picks*", { signal_date: "2026-10-13", count: 0, picks: [] });
    await page.goto(`${DESK}?tab=scanner`);
    await expect(page.getByTestId("desk-scan-empty")).toContainText("No setups on the 13 Oct 2026 scan");
  });
});

// ── Chart analysis and risk desk ─────────────────────────────────────────

test.describe("Smart trading desk · Chart analysis and risk desk", () => {
  test("TC-18 1M / 3M / 6M draw 22 / 63 / 126 daily candles; the readout moves with the arrow keys", async ({ page }) => {
    await deskMocks(page);
    await page.goto(`${DESK}?tab=chart&sym=FIXBRK`);
    const candles = page.getByTestId("desk-candle");
    await expect(page.getByTestId("desk-chart-tf-3M")).toHaveAttribute("aria-pressed", "true");
    await expect(candles).toHaveCount(63);
    await expect(page.getByTestId("desk-chart-span")).toHaveText("Daily · 3 months");
    await page.getByTestId("desk-chart-tf-1M").click();
    await expect(candles).toHaveCount(22);
    await expect(page.getByTestId("desk-chart-span")).toHaveText("Daily · 1 month");
    await page.getByTestId("desk-chart-tf-6M").click();
    await expect(candles).toHaveCount(126);
    await expect(candles.last()).toHaveAttribute("data-day", BARS[BARS.length - 1][0]);
    await expect(candles.first()).toHaveAttribute("data-day", BARS[BARS.length - 126][0]);

    // Readout: the last session by default, the one before after ←.
    const last = BARS[BARS.length - 1];
    const prev = BARS[BARS.length - 2];
    const readout = page.getByTestId("desk-chart-readout");
    await expect(readout).toContainText(`C ${inr2(last[4])}`);
    await page.getByTestId("desk-chart-svg").focus();
    await page.keyboard.press("ArrowLeft");
    await expect(readout).toContainText(`O ${inr2(prev[1])} · H ${inr2(prev[2])} · L ${inr2(prev[3])} · C ${inr2(prev[4])}`);
    await expect(page.getByTestId("desk-chart-svg")).toHaveAttribute("aria-label", /126 daily candles/);
    // The last-price tag carries the last close.
    await expect(page.getByTestId("desk-last-tag")).toHaveAttribute("data-value", String(last[4]));

    // Overlays toggle (aria-pressed) and leave the chart and the legend.
    await expect(page.getByTestId("desk-line-ema20")).toHaveCount(1);
    await page.getByTestId("desk-chart-ov-ema").click();
    await expect(page.getByTestId("desk-chart-ov-ema")).toHaveAttribute("aria-pressed", "false");
    await expect(page.getByTestId("desk-line-ema20")).toHaveCount(0);
    await expect(page.getByTestId("desk-chart-legend")).not.toContainText("EMA 20");
    await expect(page.getByTestId("desk-line-vwap")).toHaveCount(1);
  });

  test("TC-19 indicator tiles equal the formulas worked out here from the bars", async ({ page }) => {
    await deskMocks(page);
    await page.goto(`${DESK}?tab=chart&sym=FIXBRK`);
    const closes = BARS.map((b) => b[4]);
    const close = closes[closes.length - 1];
    const e20 = emaLast(closes, 20);
    const e50 = emaLast(closes, 50);
    const rsi = rsiLast(closes, 14);
    const atr = atrLast(BARS, 14);
    const vwap = vwapLast(BARS, 20);
    const rv = rvolLast(BARS, 20);
    const side = (v: number) => (close > v ? "Price above" : close < v ? "Price below" : "Price at");

    await expect(page.getByTestId("desk-ind-ema20")).toHaveText(inr2(e20));
    await expect(page.getByTestId("desk-ind-ema20-sub")).toHaveText(side(e20));
    await expect(page.getByTestId("desk-ind-rsi")).toHaveText(rsi.toFixed(1));
    await expect(page.getByTestId("desk-ind-rsi-sub")).toHaveText(rsi >= 70 ? "Overbought" : rsi >= 55 ? "Healthy" : "Neutral");
    await expect(page.getByTestId("desk-ind-atr")).toHaveText(inr2(atr));
    await expect(page.getByTestId("desk-ind-atr-sub")).toHaveText(`${((atr / close) * 100).toFixed(2)}% of price`);
    await expect(page.getByTestId("desk-ind-vwap")).toHaveText(inr2(vwap));
    await expect(page.getByTestId("desk-ind-vwap-sub")).toHaveText(side(vwap));
    await expect(page.getByTestId("desk-ind-rvol")).toHaveText(`${rv.toFixed(2)}×`);
    expect(rv).toBeGreaterThanOrEqual(1.5); // the fixture's last session is a volume spike
    await expect(page.getByTestId("desk-ind-rvol-sub")).toHaveText("Volume expansion");
    await expect(page.getByTestId("desk-chart-source")).toContainText("not the intraday VWAP");
    // The trend row names both averages.
    await expect(page.getByTestId("desk-why-trend")).toContainText(`the 20-day EMA ${inr2(e20)}`);
    await expect(page.getByTestId("desk-why-trend")).toContainText(`EMA 50 ${inr2(e50)}`);

    // Head row: last close and the day's change in rupees and percent, from the bars.
    const prev = closes[closes.length - 2];
    const ch = close - prev;
    await expect(page.getByTestId("desk-chart-close")).toHaveText(inr2(close));
    await expect(page.getByTestId("desk-chart-change")).toHaveText(`${ch > 0 ? "+" : ch < 0 ? "−" : ""}${enIN(Math.abs(ch))} (${signedPct((ch / prev) * 100, 2)})`);
  });

  test("TC-20 levels and reward / risk come from the pick, not the watchlist; the gate counts only real passes", async ({ page }) => {
    await deskMocks(page);
    // No ?sym: the Chart tab opens on the scanner's first setup.
    await page.goto(`${DESK}?tab=chart`);
    const top = [...expectedRows()].sort((a, b) => b.score - a.score)[0];
    expect(top.symbol).toBe("FIXBRK");
    await expect(page.getByTestId("desk-chart-symbol")).toHaveText(top.symbol);

    const p = PICKS.picks[0];
    await expect(page.getByTestId("desk-level-target")).toContainText(`Target ${inr2(p.target_price)}`);
    await expect(page.getByTestId("desk-level-entry")).toContainText(`Entry ${inr2(p.entry_price)}`);
    await expect(page.getByTestId("desk-level-stop")).toContainText(`Stop ${inr2(p.stoploss)}`);
    await expect(page.getByTestId("desk-level-target")).toHaveAttribute("data-value", String(p.target_price));
    await expect(page.getByTestId("desk-risk-entry")).toHaveText(`Entry ${inr2(p.entry_price)}`);
    await expect(page.getByTestId("desk-risk-stop")).toHaveText(`Stop ${inr2(p.stoploss)}`);
    await expect(page.getByTestId("desk-risk-target")).toHaveText(`Target ${inr2(p.target_price)}`);
    const rr = (p.target_price - p.entry_price) / (p.entry_price - p.stoploss);
    expect(rr).toBeCloseTo(p.risk_reward, 9);
    await expect(page.getByTestId("desk-risk-rr")).toHaveText(`${p.risk_reward.toFixed(1)} : 1`);
    await expect(page.getByTestId("desk-hist-rr")).toHaveText(`${p.risk_reward.toFixed(1)} : 1`);
    await expect(page.getByTestId("desk-hist-conf")).toHaveText("High");
    await expect(page.getByTestId("desk-hist-hit")).toHaveText("—");
    await expect(page.getByTestId("desk-hist-move")).toHaveText("—");
    await expect(page.getByTestId("desk-risk-winrate")).toHaveText("—");
    await expect(page.getByTestId("desk-risk-scenario")).toHaveText("Breakout confirmed");
    await expect(page.getByTestId("desk-risk-status")).toHaveAttribute("data-status", "confirmed");
    await expect(page.getByTestId("desk-chart-pills")).toContainText(`Volume ${WATCHLIST.buckets.breakout_confirmed[0].signals.volume_spike_3v20.toFixed(1)}×`);
    // The last close sits between the entry's left edge and the target: marked on the range bar.
    await expect(page.getByTestId("desk-risk-ltp")).toContainText(`Close ${inr2(BARS[BARS.length - 1][4])}`);

    // Levels toggle off removes the lines; the gutter then shows the price axis.
    await expect(page.getByTestId("desk-axis-label")).toHaveCount(0);
    await page.getByTestId("desk-chart-ov-levels").click();
    await expect(page.getByTestId("desk-level-target")).toHaveCount(0);
    expect(await page.getByTestId("desk-axis-label").count()).toBeGreaterThan(1);

    // Probability and gate: FIXBRK is in the run with 3 events, the record beats its base rate, and it trades ₹42.6 Cr a day → 5 of 5.
    const o = ODDS_ROWS.find((r) => r.symbol === "FIXBRK")!;
    await expect(page.getByTestId("desk-risk-p5")).toHaveText(pct1(o.p));
    await expect(page.getByTestId("desk-risk-gate-count")).toHaveText("5 of 5 passed");
    await expect(page.getByTestId("desk-risk-check-events-value")).toHaveText(String(o.events_on_record));
    await expect(page.getByTestId("desk-risk-check-edge-value")).toHaveText(`${pct1(RECORD.top10_hit_rate)} vs ${pct1(RECORD.base_rate)}`);
    await expect(page.getByTestId("desk-risk-check-liquidity-value")).toHaveText(`₹${tradedOf("FIXBRK")!.toFixed(1)} Cr a day`);
    await expect(page.getByTestId("desk-risk-check-published-value")).toHaveText("14 Oct 2026");
    await expect(page.getByTestId("desk-risk-record")).toContainText(`top-10 hit rate ${pct1(RECORD.top10_hit_rate)} over ${RECORD.sessions} sessions`);

    // Setup check (seven rows at most) and why: from the scanner payload. Next resistance / support from the watchlist row,
    // with the distance from the scan-day close.
    const w = WATCHLIST.buckets.breakout_confirmed[0];
    const from = (lvl: number) => signedPct(((lvl - w.close_price) / w.close_price) * 100);
    await expect(page.getByTestId("desk-check-resistance")).toHaveText(`Next resistance${inr2(w.resistance_level)} · ${from(w.resistance_level)}`);
    await expect(page.getByTestId("desk-check-support")).toHaveText(`Next support${inr2(w.support_level)} · ${from(w.support_level)}`);
    await expect(page.getByTestId("desk-check-volume")).toContainText("1.8×");
    await expect(page.getByTestId("desk-setup-check").locator('[data-testid^="desk-check-"]')).toHaveCount(7);
    await expect(page.getByTestId("desk-why")).toContainText(PICKS.picks[0].reasons[0]);
    await expect(page.getByTestId("desk-why")).toContainText(WATCHLIST.buckets.breakout_confirmed[0].why);
    // Catalyst: the events on record, and the latest one from the stock route.
    await expect(page.getByTestId("desk-why-catalyst")).toContainText(`${o.events_on_record} events on record; latest: Fixture filing 3 (NSE filing, 13 Oct 2026)`);
    // Risk: the stop's distance below the entry.
    await expect(page.getByTestId("desk-why-risk")).toContainText(`Stop ${inr2(p.stoploss)} is ${(((p.entry_price - p.stoploss) / p.entry_price) * 100).toFixed(1)}% below the entry`);
  });

  test("a stock with no events and a thin traded value fails two gate checks; its estimate is not shown as high-confidence", async ({ page }) => {
    await deskMocks(page);
    await page.goto(`${DESK}?tab=chart&sym=FIXPRE`);
    const o = ODDS_ROWS.find((r) => r.symbol === "FIXPRE")!;
    // published ✓, record ✓, top-10 above base ✓, events 0 ✕, ₹3.2 Cr a day ✕
    const passed = [true, true, RECORD.top10_hit_rate > RECORD.base_rate, o.events_on_record > 0, (tradedOf("FIXPRE") ?? 0) >= 10].filter(Boolean).length;
    expect(passed).toBe(3);
    await expect(page.getByTestId("desk-risk-gate-count")).toHaveText(`${passed} of 5 passed`);
    await expect(page.getByTestId("desk-risk-check-events")).toHaveAttribute("data-ok", "false");
    await expect(page.getByTestId("desk-risk-check-liquidity")).toHaveAttribute("data-ok", "false");
    await expect(page.getByTestId("desk-risk-p5")).toHaveText(pct1(o.p));
    await expect(page.getByTestId("desk-risk-p5-note")).toHaveText(`P(+5% next session). Not shown as high-confidence: ${passed} of 5 gate checks passed.`);
    await expect(page.getByTestId("desk-why-catalyst")).toContainText("No filing or news event on record in the model’s run.");
  });

  test("odds 403: the gate's model checks show “—” and are not counted; only the liquidity check can pass", async ({ page }) => {
    await deskMocks(page, { oddsStatus: 403 });
    await page.goto(`${DESK}?tab=chart&sym=FIXBRK`);
    for (const k of ["published", "record", "edge", "events"]) {
      await expect(page.getByTestId(`desk-risk-check-${k}`)).toHaveAttribute("data-ok", "na");
      await expect(page.getByTestId(`desk-risk-check-${k}-value`)).toHaveText("—");
    }
    await expect(page.getByTestId("desk-risk-check-liquidity")).toHaveAttribute("data-ok", "true");
    await expect(page.getByTestId("desk-risk-gate-count")).toHaveText("1 of 5 passed");
    await expect(page.getByTestId("desk-risk-p5")).toHaveText("—");
    await expect(page.getByTestId("desk-risk-p5-note")).toHaveText("Move probabilities are not enabled for this account.");
  });

  test("a symbol that is not on the scanner shows the chart and indicators, and no levels", async ({ page }) => {
    await deskMocks(page);
    await page.goto(`${DESK}?tab=chart&sym=OTHERSYM`);
    await expect(page.getByTestId("desk-chart-symbol")).toHaveText("OTHERSYM");
    await expect(page.getByTestId("desk-candle")).toHaveCount(63);
    await expect(page.getByTestId("desk-not-on-scanner")).toContainText("Not on today’s scanner — no levels");
    await expect(page.getByTestId("desk-chart-pills")).toHaveText("Not on today’s scanner");
    await expect(page.getByTestId("desk-risk-nolevels")).toBeVisible();
    await expect(page.getByTestId("desk-risk-nosize")).toBeVisible();
    await expect(page.getByTestId("desk-chart-ov-levels")).toBeDisabled();
    await expect(page.getByTestId("desk-risk-rr")).toHaveText("—");
    // Without levels the gutter shows the price axis.
    expect(await page.getByTestId("desk-axis-label").count()).toBeGreaterThan(1);
  });

  test("TC-21 chart-live 403 → charting locked for the account", async ({ page }) => {
    await deskMocks(page, { barsStatus: 403 });
    await page.goto(`${DESK}?tab=chart&sym=FIXBRK`);
    await expect(page.getByTestId("desk-chart-locked")).toContainText("Charting is not enabled for this account");
    await expect(page.getByTestId("desk-candle")).toHaveCount(0);
    await expect(page.getByTestId("desk-indicators")).toHaveCount(0);
    // The scanner's levels still drive the risk desk; gap risk needs the bars and says so.
    await expect(page.getByTestId("desk-risk-rr")).toHaveText(`${PICKS.picks[0].risk_reward.toFixed(1)} : 1`);
    await expect(page.getByTestId("desk-risk-chk-gap")).toHaveText(/Needs the stock’s daily bars/);
  });

  test("TC-21 chart-live 404 → no prices on record", async ({ page }) => {
    await deskMocks(page, { barsStatus: 404 });
    await page.goto(`${DESK}?tab=chart&sym=FIXBRK`);
    await expect(page.getByTestId("desk-chart-noprices")).toContainText("No daily prices on record for FIXBRK");
    await expect(page.getByTestId("desk-candle")).toHaveCount(0);
  });

  test("TC-22 position size: the worked example from the pick, toggles recompute, and the concentration check", async ({ page }) => {
    await deskMocks(page);
    await page.goto(`${DESK}?tab=chart&sym=FIXBRK`);
    const { entry_price: entry, stoploss: stop, target_price: target } = PICKS.picks[0];
    const size = (capital: number, riskPct: number) => {
      const qty = Math.floor((capital * riskPct) / 100 / (entry - stop));
      const used = qty * entry;
      return { qty, used, usedPct: (used / capital) * 100, maxLoss: qty * (entry - stop), atTarget: qty * (target - entry), limit: Math.floor((capital * 0.25) / entry) };
    };
    const conc = page.getByTestId("desk-risk-chk-concentration");
    const check = async (capital: number, riskPct: number) => {
      const s = size(capital, riskPct);
      await expect(page.getByTestId("desk-risk-qty")).toHaveText(new Intl.NumberFormat("en-IN").format(s.qty));
      await expect(page.getByTestId("desk-risk-used")).toHaveText(inr0(s.used));
      await expect(page.getByTestId("desk-risk-used-pct")).toHaveText(`${s.usedPct.toFixed(1)}%`);
      await expect(page.getByTestId("desk-risk-maxloss")).toHaveText(inr0(s.maxLoss));
      await expect(page.getByTestId("desk-risk-attarget")).toHaveText(`+${inr0(s.atTarget)}`);
      if (s.used > capital * 0.25) {
        await expect(conc).toHaveAttribute("data-tone", "amber");
        await expect(conc).toContainText(`${s.usedPct.toFixed(1)}% of capital in one stock, above the 25% single-stock limit; ${s.limit} shares keeps it inside.`);
      } else {
        await expect(conc).toHaveAttribute("data-tone", "mint");
        await expect(conc).toContainText(`${s.usedPct.toFixed(1)}% of capital, within the 25% single-stock limit.`);
      }
      return s;
    };
    // Defaults: ₹5L at 1% → 5,000 ÷ 25 = 200 shares.
    await expect(page.getByTestId("desk-risk-capital-5l")).toHaveAttribute("aria-pressed", "true");
    await expect(page.getByTestId("desk-risk-pct-1")).toHaveAttribute("aria-pressed", "true");
    expect((await check(500_000, 1)).qty).toBe(200);
    await expect(page.getByTestId("desk-risk-size")).toContainText("before brokerage and taxes");
    await expect(page.getByTestId("desk-risk-chk-size")).toContainText(`${inr0(5_000)} at risk (1% of ${inr0(500_000)}); max loss ${inr0(5_000)} at the stop.`);

    await page.getByTestId("desk-risk-capital-2l").click();
    await page.getByTestId("desk-risk-pct-2").click();
    const over = await check(200_000, 2); // 4,000 ÷ 25 = 160 shares = ₹80,800, 40.4% of ₹2L
    expect(over.used).toBeGreaterThan(200_000 * 0.25);

    await page.getByTestId("desk-risk-capital-10l").click();
    await page.getByTestId("desk-risk-pct-0-5").click();
    await check(1_000_000, 0.5);

    // Gap risk: the largest opening gap over the last 63 sessions of the bars, against the stop's distance.
    const recent = BARS.slice(-64);
    let best = { pct: 0, day: "" };
    for (let i = 1; i < recent.length; i++) {
      const g = (recent[i][1] / recent[i - 1][4] - 1) * 100;
      if (Math.abs(g) > Math.abs(best.pct)) best = { pct: g, day: recent[i][0] };
    }
    await expect(page.getByTestId("desk-risk-chk-gap")).toContainText(`Largest opening gap in the last 63 sessions: ${signedPct(best.pct)}`);
    await expect(page.getByTestId("desk-risk-chk-correlation")).toHaveAttribute("data-tone", "na");
  });

  test("TC-23 Add to paper trades posts the calculator's quantity at the pick's levels; it is pending, then confirmed, and says no order is placed", async ({ page }) => {
    const writes = recordWrites(page);
    await deskMocks(page);
    let release: () => void = () => {};
    const gate = new Promise<void>((r) => { release = r; });
    const posted = await mockDeskWrites(page, { gate });
    await page.goto(`${DESK}?tab=chart&sym=FIXBRK`);

    const p = PICKS.picks[0];
    const qty = (capital: number, riskPct: number) => Math.floor((capital * riskPct) / 100 / (p.entry_price - p.stoploss));
    const paper = page.getByTestId("desk-risk-paper");
    await expect(paper).toBeEnabled();
    await expect(page.getByTestId("desk-risk-paper-note")).toHaveText(
      `Simulated: ${qty(500_000, 1)} shares at ${inr2(p.entry_price)}, stop ${inr2(p.stoploss)}, target ${inr2(p.target_price)}. No order is placed; it is marked against end-of-day closes.`,
    );
    await paper.click();
    // Pending: disabled until the server answers.
    await expect(paper).toBeDisabled();
    await expect(paper).toHaveText("Adding…");
    release();
    const done = page.getByTestId("desk-risk-paper-done");
    await expect(done).toContainText(`Paper trade added: ${qty(500_000, 1)} FIXBRK at ${inr2(p.entry_price)}. No order is placed.`);
    await expect(paper).toBeEnabled();

    // The body, exactly: FIXBRK is in both routes, so the plan is the pick's; the bucket is the watchlist's; the signal
    // date is the picks' session.
    expect(posted).toHaveLength(1);
    expect(posted[0]).toEqual({
      method: "POST", path: "/api/desk/paper-trades",
      body: {
        symbol: "FIXBRK", quantity: qty(500_000, 1), entry_price: p.entry_price, stop_price: p.stoploss, target_price: p.target_price,
        source: { kind: "scanner", bucket: "breakout_confirmed", signal_date: PICKS.signal_date },
      },
    });

    // The quantity follows the calculator: ₹2L at 2% → 4,000 ÷ 25 = 160 shares.
    await page.getByTestId("desk-risk-capital-2l").click();
    await page.getByTestId("desk-risk-pct-2").click();
    await paper.click();
    await expect.poll(() => posted.length).toBe(2);
    expect((posted[1].body as { quantity: number }).quantity).toBe(qty(200_000, 2));
    await expect(done).toContainText(`Paper trade added: ${qty(200_000, 2)} FIXBRK`);

    // Nothing else was written.
    const origin = new URL(page.url()).origin;
    expect(writes).toEqual([`POST ${origin}/api/desk/paper-trades`, `POST ${origin}/api/desk/paper-trades`]);
    // The link goes to the list on Portfolio & risk.
    await done.getByTestId("desk-risk-paper-done-open").click();
    await expect(page).toHaveURL(/[?&]tab=portfolio/);
  });

  test("TC-23 Alert on trigger posts the watchlist trigger as an 'above' level and turns into “Alert set ✓”; a pick without a trigger uses its entry and sends no bucket", async ({ page }) => {
    await deskMocks(page);
    const posted = await mockDeskWrites(page);
    await page.goto(`${DESK}?tab=chart&sym=FIXBRK`);
    const w = WATCHLIST.buckets.breakout_confirmed[0];
    const alertBtn = page.getByTestId("desk-risk-alert");
    await expect(alertBtn).toHaveText("Alert on trigger");
    await expect(page.getByTestId("desk-risk-alert-note")).toContainText(`reaches ${inr2(w.trigger_price)} (the trigger)`);
    await alertBtn.click();
    await expect(page.getByTestId("desk-risk-alert-done")).toContainText(`Alert set: FIXBRK above ${inr2(w.trigger_price)}`);
    await expect(alertBtn).toHaveText("Alert set ✓");
    await expect(alertBtn).toBeDisabled();
    expect(posted).toEqual([{ method: "POST", path: "/api/desk/alerts", body: { symbol: "FIXBRK", condition: "above", level: w.trigger_price } }]);

    // FIXPICK is only in the picks: no trigger (the alert uses the entry), no bucket in the trade's source.
    await page.goto(`${DESK}?tab=chart&sym=FIXPICK`);
    await expect(page.getByTestId("desk-chart-symbol")).toHaveText("FIXPICK");
    const fp = PICKS.picks[1];
    await page.getByTestId("desk-risk-alert").click();
    await expect.poll(() => posted.length).toBe(2);
    expect(posted[1].body).toEqual({ symbol: "FIXPICK", condition: "above", level: fp.entry_price });
    await page.getByTestId("desk-risk-paper").click();
    await expect.poll(() => posted.length).toBe(3);
    expect(posted[2].body).toEqual({
      symbol: "FIXPICK", quantity: Math.floor(5_000 / (fp.entry_price - fp.stoploss)), entry_price: fp.entry_price, stop_price: fp.stoploss,
      target_price: fp.target_price, source: { kind: "scanner", signal_date: PICKS.signal_date },
    });
  });

  test("TC-23 a 409 limit and a 422 validation error show the server's words; a stock with no levels can do neither and sends nothing", async ({ page }) => {
    const writes = recordWrites(page);
    await deskMocks(page);
    const posted = await mockDeskWrites(page, {
      paper: { status: 409, body: { detail: "open_trade_limit" } },
      alert: { status: 422, body: { detail: "invalid_symbol" } },
    });
    await page.goto(`${DESK}?tab=chart&sym=FIXBRK`);
    await page.getByTestId("desk-risk-paper").click();
    const perr = page.getByTestId("desk-risk-paper-error");
    await expect(perr).toHaveAttribute("role", "alert");
    await expect(perr).toHaveText("Not added — You have the most open paper trades allowed (100). Close one first. (open_trade_limit)");
    await expect(page.getByTestId("desk-risk-paper-done")).toHaveCount(0);
    await page.getByTestId("desk-risk-alert").click();
    await expect(page.getByTestId("desk-risk-alert-error")).toHaveText("Not set — The symbol is not a valid NSE symbol. (invalid_symbol)");
    // A code the screen does not know is shown as the server sent it.
    await page.route("**/api/desk/alerts", (route) => route.fulfill({ status: 422, contentType: "application/json", body: JSON.stringify({ detail: [{ loc: ["body", "level"], msg: "Input should be greater than 0", type: "greater_than" }] }) }));
    await page.getByTestId("desk-risk-alert").click();
    await expect(page.getByTestId("desk-risk-alert-error")).toHaveText("Not set — Input should be greater than 0");
    expect(posted).toHaveLength(2);

    // A symbol off the scanner: both buttons are disabled with the reason, and a forced click sends nothing.
    await page.goto(`${DESK}?tab=chart&sym=OTHERSYM`);
    await expect(page.getByTestId("desk-chart-symbol")).toHaveText("OTHERSYM");
    await expect(page.getByTestId("desk-risk-paper")).toBeDisabled();
    await expect(page.getByTestId("desk-risk-alert")).toBeDisabled();
    await expect(page.getByTestId("desk-risk-paper-note")).toHaveText("Needs a scanner setup: this stock has no entry or stop.");
    await expect(page.getByTestId("desk-risk-alert-note")).toHaveText("Needs a trigger or an entry level; this stock has neither on today’s scanner.");
    await page.getByTestId("desk-risk-paper").click({ force: true });
    await page.getByTestId("desk-risk-alert").click({ force: true });
    await expect(page.getByTestId("desk-risk-note")).toHaveText("Paper trade only. Nivesh reads broker positions and cannot place orders.");
    await page.waitForTimeout(500);
    expect(writes).toHaveLength(3);
    expect(writes.every((w) => /^POST .*\/api\/desk\/(paper-trades|alerts)$/.test(w))).toBe(true);
  });

  test("TC-23 a setup with no entry disables both actions and says why", async ({ page }) => {
    await deskMocks(page);
    // FIXTRD has a stop (₹1,150) but no trigger or pick, so it has no entry: no sizing, nothing to add; no alert level.
    await page.goto(`${DESK}?tab=chart&sym=FIXTRD`);
    await expect(page.getByTestId("desk-risk-paper")).toBeDisabled();
    await expect(page.getByTestId("desk-risk-paper-note")).toHaveText("Needs an entry with a stop below it; this setup does not have both.");
    await expect(page.getByTestId("desk-risk-alert")).toBeDisabled();
  });

  test("Ask Copilot hands the setup question to the Copilot", async ({ page }) => {
    await deskMocks(page);
    const sent: string[] = [];
    await page.route("**/api/chat/sessions", (route) =>
      route.request().method() === "POST"
        ? route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ session_id: "asked1" }) })
        : route.fulfill({ status: 200, contentType: "application/json", body: "[]" }));
    await page.route("**/api/chat/messages*", (route) => route.fulfill({ status: 200, contentType: "application/json", body: "[]" }));
    await page.route("**/api/chat/stream", (route) => {
      sent.push((route.request().postDataJSON() as { message: string }).message);
      return route.fulfill({ status: 200, contentType: "text/event-stream", body: `data: ${JSON.stringify({ type: "done", content: "ok" })}\n\n` });
    });
    await page.goto(`${DESK}?tab=chart&sym=FIXBRK`);
    await page.getByTestId("desk-why-ask").click();
    await expect.poll(() => sent).toEqual(["Explain the FIXBRK setup and what would invalidate it"]);
  });
});

// ── design fidelity: titles, order, labels, persona (desktop) ────────────

test.describe("Smart trading desk · design fidelity (desktop)", () => {
  test.use({ viewport: { width: 1360, height: 900 } });

  test("scanner: the 02 card header, the controls row in order, and the nine columns in the design's order", async ({ page }) => {
    await deskMocks(page);
    await page.goto(`${DESK}?tab=scanner`);
    await expect(page.getByTestId("desk-scan-table")).toBeVisible();
    await expect(page.getByTestId("desk-scan-title")).toHaveText("02 · AI Opportunity scanner");
    expect(await texts(page, '[data-testid^="desk-scan-col-"]')).toEqual([
      "#", "Stock", "Score", "P(+5% next session)", "Hit rate · n", "Pattern / catalyst", "To target", "24 sessions", "Status",
    ]);
    expect(await texts(page, '[data-testid^="desk-scan-rank-"]:not([data-testid="desk-scan-rank"])')).toEqual(["Score", "P(+5% next session)", "P(+10% next session)"]);
    expect(await texts(page, '[data-testid^="desk-scan-group-"]')).toEqual(["All", "Breakouts", "Near breakout", "Pullbacks", "Accumulation"]);
    // Controls row order: Rank by → chips → the Liquid-only switch at the right.
    const rankBox = (await page.getByTestId("desk-scan-rank-score").boundingBox())!;
    const chipBox = (await page.getByTestId("desk-scan-group-all").boundingBox())!;
    const liquidBox = (await page.getByTestId("desk-scan-liquid").boundingBox())!;
    expect(rankBox.x).toBeLessThan(chipBox.x);
    expect(chipBox.x).toBeLessThan(liquidBox.x);
    // Rank is zero-padded; the selected row's rank is mint.
    await expect(page.getByTestId("desk-scan-row-FIXBRK").getByTestId("desk-scan-rank")).toHaveText("01");
  });

  test("scanner: the investor wording switches labels, the probability wording and the pattern text", async ({ page }) => {
    await deskMocks(page);
    await page.goto(`${DESK}?tab=scanner`);
    await expect(page.getByTestId("desk-scan-col-odds")).toHaveText("P(+5% next session)");
    await page.getByTestId("desk-persona-investor").click();
    await expect(page).toHaveURL(/[?&]persona=investor/);
    expect(await texts(page, '[data-testid^="desk-scan-col-"]')).toEqual([
      "#", "Stock", "Score", "Chance +5% next day", "Past record", "Why it shows up", "To target", "24 sessions", "Status",
    ]);
    expect(await texts(page, '[data-testid^="desk-scan-rank-"]:not([data-testid="desk-scan-rank"])')).toEqual(["Score", "Chance +5% next day", "Chance +10% next day"]);
    await expect(page.getByTestId("desk-scan-row-FIXBRK").getByTestId("desk-scan-setup")).toHaveText("Broke above a recent high");
    await expect(page.getByTestId("desk-scan-row-FIXTRD").getByTestId("desk-scan-setup")).toHaveText("Dipped in an uptrend");
    await expect(page.getByTestId("desk-scan-footnote")).toContainText("one day only");
    // Same data, other words: the figures do not change.
    await expect(page.getByTestId("desk-scan-row-FIXBRK").getByTestId("desk-scan-odds")).toHaveText(pct1(ODDS_ROWS[1].p));
  });

  test("chart: 03 card with the overlay chips then the timeframe, the head row, indicators, setup check, why rows and history tiles; 05 risk desk beside it", async ({ page }) => {
    await deskMocks(page);
    await page.goto(`${DESK}?tab=chart&sym=FIXBRK`);
    await expect(page.getByTestId("desk-candle")).toHaveCount(63);
    await expect(page.getByTestId("desk-chart-title")).toHaveText("03 · AI Chart intelligence");
    await expect(page.getByTestId("desk-risk-title")).toHaveText("05 · AI Risk desk");
    await expect(page.getByTestId("desk-chart-tab")).toHaveAttribute("data-layout", "desk");
    // 7 : 5 side by side, tops aligned.
    const card = (await page.getByTestId("desk-chart-card").boundingBox())!;
    const risk = (await page.getByTestId("desk-risk").boundingBox())!;
    expect(Math.abs(card.y - risk.y)).toBeLessThanOrEqual(1);
    expect(risk.x).toBeGreaterThan(card.x + card.width);
    expect(card.width / risk.width).toBeGreaterThan(1.25);
    // Header: EMA · VWAP · Levels, then 1M · 3M · 6M.
    const order = await page.locator('[data-testid="desk-chart-card"] [data-testid^="desk-chart-ov-"], [data-testid="desk-chart-card"] [data-testid^="desk-chart-tf-"]').allTextContents();
    expect(order).toEqual(["EMA", "VWAP", "Levels", "1M", "3M", "6M"]);
    // Legend keys and span, design order.
    await expect(page.getByTestId("desk-chart-legend")).toHaveText("EMA 20EMA 50VWAP 20DTargetEntryStopDaily · 3 months");
    // Indicator tiles in order, five across.
    await expect(page.getByTestId("desk-indicators")).toHaveAttribute("data-cols", "5");
    expect(await page.getByTestId("desk-indicators").locator(".cp-eyebrow").allTextContents()).toEqual(["EMA 20", "RSI 14", "ATR 14", "VWAP 20D", "RVOL"]);
    await expect(page.getByTestId("desk-setup-check")).toContainText("Setup check");
    expect(await page.locator('[data-testid^="desk-why-"] > .cp-eyebrow').allTextContents()).toEqual(["Trend", "Momentum", "Catalyst", "Risk"]);
    await expect(page.getByTestId("desk-why-ask")).toHaveText("Ask Copilot ›");
    expect(await page.getByTestId("desk-history").locator(".cp-eyebrow").allTextContents()).toEqual(["Hit rate", "Average move", "Reward : risk", "Scanner confidence"]);
    // The head row: label · company, price, change, then the pattern pills (first mint).
    await expect(page.getByTestId("desk-chart-header")).toContainText(`FIXBRK · ${STOCK_FIXBRK.data.company_name}`);
    await expect(page.getByTestId("desk-chart-pills").locator(".cp-pill").first()).toHaveAttribute("data-tone", "mint");
  });

  test("risk desk: scenario and reward / risk, range bar, two probability tiles, the gate, position size, four checks, two buttons and the note — in that order", async ({ page }) => {
    await deskMocks(page);
    await page.goto(`${DESK}?tab=chart&sym=FIXBRK`);
    await expect(page.getByTestId("desk-risk-gate-count")).toHaveText("5 of 5 passed");
    const ids = ["desk-risk-scenario", "desk-risk-bar", "desk-risk-p5", "desk-risk-explain", "desk-risk-gate", "desk-risk-size", "desk-risk-checks", "desk-risk-actions", "desk-risk-note"];
    const tops: number[] = [];
    for (const id of ids) tops.push(await topOf(page, id));
    expect([...tops].sort((a, b) => a - b)).toEqual(tops);
    const risk = page.getByTestId("desk-risk");
    await expect(risk).toContainText("Reward / risk");
    await expect(risk).toContainText("Move probability");
    await expect(risk).toContainText("Trade win rate");
    await expect(risk).toContainText("Validation gate");
    expect(await risk.locator('[data-testid^="desk-risk-chk-"] .cp-eyebrow').allTextContents()).toEqual(["Position size", "Concentration", "Correlation", "Gap risk"]);
    expect(await texts(page, '[data-testid^="desk-risk-capital-"]')).toEqual(["₹2L", "₹5L", "₹10L"]);
    expect(await texts(page, '[data-testid^="desk-risk-pct-"]')).toEqual(["0.5%", "1%", "2%"]);
    expect(await page.getByTestId("desk-risk-size").locator(".cp-eyebrow").allTextContents()).toEqual(["Position size", "Quantity", "Capital used", "Max loss", "At target"]);
    await expect(page.getByTestId("desk-risk-paper")).toHaveText("Add to paper trades");
    await expect(page.getByTestId("desk-risk-alert")).toHaveText("Alert on trigger");
    await expect(page.getByTestId("desk-risk-gate").locator("li")).toHaveCount(5);
  });

  test("chart and risk desk: the investor wording swaps every design label and keeps the figures", async ({ page }) => {
    await deskMocks(page);
    await page.goto(`${DESK}?tab=chart&sym=FIXBRK&persona=investor`);
    await expect(page.getByTestId("desk-candle")).toHaveCount(63);
    await expect(page.getByTestId("desk-chart-legend")).toHaveText("20-day avg50-day avgMonth’s avgTargetBuy aboveExitDaily · 3 months");
    expect(await page.getByTestId("desk-indicators").locator(".cp-eyebrow").allTextContents()).toEqual(["Trend", "Momentum", "Daily swing", "Month’s avg", "Activity"]);
    await expect(page.getByTestId("desk-setup-check")).toContainText("What the chart shows");
    expect(await page.locator('[data-testid^="desk-why-"] > .cp-eyebrow').allTextContents()).toEqual(["Trend", "Strength", "News", "Watch"]);
    expect(await page.getByTestId("desk-history").locator(".cp-eyebrow").allTextContents()).toEqual(["Worked before", "Typical rise", "Reward for risk", "Scanner’s confidence"]);
    const risk = page.getByTestId("desk-risk");
    await expect(risk).toContainText("Reward for risk");
    await expect(risk).toContainText("Chance of +5%");
    await expect(risk).toContainText("Past trades that worked");
    expect(await page.getByTestId("desk-risk-size").locator(".cp-eyebrow").allTextContents()).toEqual(["How much to buy", "Shares", "Money used", "If wrong", "If right"]);
    expect(await risk.locator('[data-testid^="desk-risk-chk-"] .cp-eyebrow').allTextContents()).toEqual(["Size", "One-stock share", "Moves with", "Sudden jumps"]);
    const p = PICKS.picks[0];
    await expect(page.getByTestId("desk-risk-stop")).toHaveText(`Exit if wrong ${inr2(p.stoploss)}`);
    await expect(page.getByTestId("desk-risk-entry")).toHaveText(`Buy above ${inr2(p.entry_price)}`);
    await expect(page.getByTestId("desk-risk-scenario")).toHaveText("Broke above a recent high");
    // The figures are the same as the trader's.
    await expect(page.getByTestId("desk-risk-p5")).toHaveText(pct1(ODDS_ROWS[1].p));
    await expect(page.getByTestId("desk-risk-qty")).toHaveText("200");
  });

  test("at 1440 with the Copilot docked the chart and the risk desk still sit side by side", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await deskMocks(page);
    await page.goto(`${DESK}?tab=chart&sym=FIXBRK`);
    await expect(page.getByTestId("desk-candle")).toHaveCount(63);
    await expect(page.getByTestId("desk-chart-tab")).toHaveAttribute("data-layout", "desk");
    const card = (await page.getByTestId("desk-chart-card").boundingBox())!;
    const risk = (await page.getByTestId("desk-risk").boundingBox())!;
    expect(risk.x).toBeGreaterThan(card.x + card.width);
    const o = await sidewaysOverflow(page);
    expect(o.doc).toBeLessThanOrEqual(1);
  });
});

// ── phone width (design-spec §11 M2 / M4) ────────────────────────────────

test.describe("Smart trading desk · scanner and chart at 390px", () => {
  test.use({ viewport: { width: 390, height: 844 } });

  for (const tab of ["scanner", "chart"] as const) {
    test(`TC-7 ${tab} tab: no sideways page scroll`, async ({ page }) => {
      await deskMocks(page);
      await page.goto(`${DESK}?tab=${tab}&sym=FIXBRK`);
      if (tab === "scanner") {
        await expect(page.getByTestId("desk-scan-table")).toHaveAttribute("data-layout", "phone");
        await expect(page.getByTestId("desk-scan-row-FIXBRK")).toBeVisible();
      } else {
        await expect(page.getByTestId("desk-candle")).toHaveCount(63);
        await expect(page.getByTestId("desk-risk")).toHaveAttribute("data-layout", "phone");
        await expect(page.getByTestId("desk-risk-p5")).toBeVisible();
      }
      const o = await sidewaysOverflow(page);
      expect(o.doc).toBeLessThanOrEqual(1);
      expect(o.scroll).toBeLessThanOrEqual(1);
    });
  }

  test("M2: chips with Liquid only → Rank by → the five-column table → Scanner insights, in that order", async ({ page }) => {
    await deskMocks(page);
    await page.goto(`${DESK}?tab=scanner`);
    await expect(page.getByTestId("desk-scanner")).toHaveAttribute("data-layout", "phone");
    expect(await texts(page, '[data-testid^="desk-scan-group-"], [data-testid="desk-scan-liquid"]')).toEqual(["All", "Breakouts", "Near breakout", "Pullbacks", "Accumulation", "Liquid only"]);
    expect(await texts(page, '[data-testid^="desk-scan-col-"]')).toEqual(["#", "Stock", "Score", "Upside", "Pattern"]);
    const tops = [await topOf(page, "desk-scan-group-all"), await topOf(page, "desk-scan-rank-score"), await topOf(page, "desk-scan-table"), await topOf(page, "desk-scan-insights")];
    expect([...tops].sort((a, b) => a - b)).toEqual(tops);
    // Each row: score chip with P under it, upside, pattern with its status.
    const brk = page.getByTestId("desk-scan-row-FIXBRK");
    await expect(brk.getByTestId("desk-scan-score")).toHaveText("86");
    await expect(brk.getByTestId("desk-scan-odds")).toHaveText(`${Math.round(ODDS_ROWS[1].p * 100)}%`);
    await expect(brk.getByTestId("desk-scan-target")).toHaveText(`+${(((555 - 510) / 510) * 100).toFixed(1)}%`);
    await expect(brk.getByTestId("desk-scan-status")).toHaveText("Confirmed");
    // Insights from the payload: 5 setups, 1 confirmed, the highest next-session estimate.
    const exp = expectedRows();
    const confirmed = exp.filter((r) => r.status === "confirmed").length;
    const awaiting = exp.filter((r) => r.status === "awaiting").length;
    const best = [...ODDS_ROWS].sort((a, b) => b.p - a.p)[0];
    const insights = page.getByTestId("desk-scan-insights");
    await expect(insights).toContainText(`${exp.length} setups on the 13 Oct 2026 scan: ${confirmed} confirmed, ${awaiting} awaiting a trigger, ${exp.length - confirmed - awaiting} forming.`);
    await expect(insights).toContainText(`Highest P(+5% next session): ${best.symbol} at ${pct1(best.p)}.`);
    // The definitions sit behind a disclosure, and say the score is not a probability.
    await page.getByTestId("desk-scan-footnote-toggle").click();
    await expect(page.getByTestId("desk-scan-footnote")).toContainText("it is not a probability");
    // Liquid only works on the phone too.
    await page.getByTestId("desk-scan-liquid").click();
    expect((await rowOrder(page)).sort()).toEqual(["FIXACC", "FIXBRK", "FIXPICK"]);
    const o = await sidewaysOverflow(page);
    expect(o.doc).toBeLessThanOrEqual(1);
  });

  test("M4: stock head → controls → chart → 03 analysis → historical performance → 05 trade scenario with a full-width button", async ({ page }) => {
    await deskMocks(page);
    await page.goto(`${DESK}?tab=chart&sym=FIXBRK`);
    await expect(page.getByTestId("desk-chart-tab")).toHaveAttribute("data-layout", "phone");
    await expect(page.getByTestId("desk-candle")).toHaveCount(63);
    await expect(page.getByTestId("desk-chart-svg")).toHaveAttribute("viewBox", "0 0 330 194");
    const ids = ["desk-chart-header", "desk-chart-tf-3M", "desk-chart-card", "desk-analysis", "desk-history", "desk-risk"];
    const tops: number[] = [];
    for (const id of ids) tops.push(await topOf(page, id));
    expect([...tops].sort((a, b) => a - b)).toEqual(tops);
    await expect(page.getByTestId("desk-analysis")).toContainText("03 · AI chart analysis");
    await expect(page.getByTestId("desk-analysis").locator('[data-testid^="desk-check-"]')).toHaveCount(7);
    await expect(page.getByTestId("desk-chart-pills")).toContainText("Scanner confidence · High");
    expect(await page.getByTestId("desk-history").locator(".cp-eyebrow").allTextContents()).toEqual(["Hit rate", "Average move", "Reward : risk"]);
    await expect(page.getByTestId("desk-risk-title")).toHaveText("05 · Trade scenario");
    await expect(page.getByTestId("desk-risk-rr")).toHaveText("2.0 : 1");
    await expect(page.getByTestId("desk-chart-status")).toHaveAttribute("data-status", "confirmed");
    // Only the paper-trade button, full width of the card's body.
    await expect(page.getByTestId("desk-risk-alert")).toHaveCount(0);
    const btn = (await page.getByTestId("desk-risk-paper").boundingBox())!;
    const card = (await page.getByTestId("desk-risk").boundingBox())!;
    expect(btn.width).toBeGreaterThanOrEqual(card.width - 2 * 14 - 2);
  });

  test("M4: Add to paper trades posts the default sizing (₹5L at 1%) and says so", async ({ page }) => {
    await deskMocks(page);
    const posted = await mockDeskWrites(page);
    await page.goto(`${DESK}?tab=chart&sym=FIXBRK`);
    const p = PICKS.picks[0];
    const qty = Math.floor(5_000 / (p.entry_price - p.stoploss));
    await expect(page.getByTestId("desk-risk-paper-note")).toContainText(`Simulated: ${qty} shares at ${inr2(p.entry_price)}`);
    await expect(page.getByTestId("desk-risk-paper-note")).toContainText(`(sized at ${inr0(500_000)} with 1% risk)`);
    await page.getByTestId("desk-risk-paper").click();
    await expect(page.getByTestId("desk-risk-paper-done")).toContainText(`Paper trade added: ${qty} FIXBRK`);
    expect(posted).toHaveLength(1);
    expect(posted[0].body).toEqual({
      symbol: "FIXBRK", quantity: qty, entry_price: p.entry_price, stop_price: p.stoploss, target_price: p.target_price,
      source: { kind: "scanner", bucket: "breakout_confirmed", signal_date: PICKS.signal_date },
    });
  });
});

// ── fidelity screenshots (design-spec §4, §5, §11 M2 / M4) ────────────────
// Written to e2e/screenshots/ (git-ignored) for a visual check against the design; they assert only that the tab rendered.
// "-tall" sets a viewport tall enough to show the whole tab (the shell scrolls inside its own box).

const SHOT = "after";

test.describe("Smart trading desk · fidelity screenshots", () => {
  // 1440 has the Copilot docked (the scanner box is too narrow for the nine columns: cards); 1360 is not docked (the table).
  for (const vp of [{ width: 1440, height: 900, name: "1440" }, { width: 1360, height: 900, name: "1360" }, { width: 390, height: 844, name: "390" }]) {
    for (const tab of ["scanner", "chart"] as const) {
      test(`SHOT ${tab} at ${vp.name}`, async ({ page }) => {
        await page.setViewportSize({ width: vp.width, height: vp.height });
        await deskMocks(page);
        await page.goto(`${DESK}?tab=${tab}&sym=FIXBRK`);
        const ready = async () => {
          if (tab === "scanner") await expect(page.getByTestId("desk-scan-row-FIXBRK")).toBeVisible();
          else {
            await expect(page.getByTestId("desk-candle")).toHaveCount(63);
            await expect(page.getByTestId("desk-risk-p5")).not.toHaveText("…");
          }
        };
        await ready();
        await page.waitForTimeout(400);
        await page.screenshot({ path: `e2e/screenshots/fidelity-${tab}-${SHOT}-${vp.name}.png` });
        await page.setViewportSize({ width: vp.width, height: vp.width > 700 ? 2400 : 3600 });
        await ready();
        await page.waitForTimeout(400);
        await page.screenshot({ path: `e2e/screenshots/fidelity-${tab}-${SHOT}-${vp.name}-tall.png` });
      });
    }
  }
});
