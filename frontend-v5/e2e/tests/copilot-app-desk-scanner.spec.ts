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
 * Scanner PRD round (PRD §5.1–§5.6, §5.8; SP-1 … SP-15): the nine categories over GET /api/positional/scan-universe,
 * the ten filters (seven working, three disabled with their reasons) kept in the URL, the §5.3 columns, the withheld
 * probability and the model rank, the actions (POST /api/watchlists/{id}/symbols, POST /api/desk/paper-trades), the
 * eligible universe with its exclusions, About the model and the trust lines.
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
  /** MOCK — not real data: the move-odds model has not published for the next session. */
  oddsPending?: boolean;
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
    if (over.oddsPending) return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ data: { status: "not_published", head, expected_session: "2026-10-21", last_published_for: "2026-10-19", rows: [] } }) });
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
//
// PRD §5.1–§5.6 and §5.8 (test cases SP-1 … SP-15, authored before the build): the nine categories, the ten filters,
// the §5.3 columns, the three actions, the eligible universe and its exclusions, the withheld probability, the model
// rank, the rules with their version, the trust line and the URL-kept criteria. MOCK — not real data: the payloads
// below are in the shape of GET /api/positional/scan-universe (backend/routes/positional.py :: scan_universe) and the
// `rules` block of backend/services/positional_engine/setup_rules.py :: public_rules(); expected rows are worked out
// from them here.

// setup_rules.public_rules(), as GET /api/positional/watchlist and /scan-universe send it.
const RULES = {
  version: "scan-rules.v1 (2026-10-14)",
  watchlist: {
    classifier: "smart_v2",
    candidates: { min_close: 5.0, excluded_stages: ["WEAK", "EXTENDED"], top_by_score: 80, min_bars: 30 },
    breakout_confirmed: { dist_breakout_pct_min: 0.0, dist_breakout_pct_max: 3.0, volume_spike_min: 1.5, stages: ["BREAKOUT", "EARLY_BREAKOUT"], max_gap_up_pct: 5.0 },
    pre_breakout: { dist_breakout_pct_min: -2.0, dist_breakout_pct_below: 0.0, volume_spike_min: 1.2, volume_slope_above: -3.0 },
    true_accumulation: { range_15d_below_pct: 8.0, volume_slope_below: 0.0, higher_lows_min: 1, upper_wick_below: 0.5, close_vs_sma50_min: 0.97 },
    trend_continuation: { dist_ema20_min_pct: 0.0, dist_ema20_max_pct: 4.0, upper_wick_below: 0.5 },
    volume_spike_sessions: [3, 20],
    stop_atr_multiple: 1.5,
  },
  liquidity: { min_traded_value_cr: 10.0, sessions: 20, definition: "Mean of close × volume over the last 20 sessions, ₹ crore a day; none with fewer than 20 sessions." },
  risk_bands: { basis: "ATR(14) as a percent of the close", low_below_pct: 2.0, high_above_pct: 4.0 },
  universe: {
    series: ["EQ", "BE"], exclude_etf: true, min_price_band_pct: 10.0, band_limit_tolerance_pct: 0.1,
    exclusion_order: ["missing_price", "no_traded_value", "no_reference", "series", "etf", "price_band", "at_band_limit", "illiquid"],
  },
  categories: {
    momentum: { return_20d_min_pct: 5.0, close_above_sma50: true, sma50_slope_above: 0.0, rank_by: "return_20d_pct" },
    unusual_volume: { vol_z20_min: 2.0, rank_by: "vol_z20" },
    results_day: { event_type: "quarterly_results", window_calendar_days: 7, return_5d_min_pct: 3.0, vol_z20_min: 1.0, rank_by: "return_5d_pct" },
    fno: { requires_fno_eligible: true, rank_by: "traded_value_cr_20d" },
  },
  max_rows_per_category: 50,
};
const WATCH_R = { ...WATCHLIST, rules: RULES, engine_versions: ["positional.v1.0"] };
const PICKS_R = { ...PICKS, rules_version: RULES.version, engine_versions: ["positional.v1.0"] };

type URow = {
  symbol: string; sector: string | null; industry: string | null; close: number; close_price: number; prev_close: number;
  return_5d_pct: number | null; return_20d_pct: number | null; vol_z20: number | null; rvol20: number | null; atr_pct: number | null;
  volatility_1y_pct: number | null; market_cap_bucket: string | null; traded_value_cr_20d: number | null; series: string;
  price_band_pct: number | null; band_raw: string; fno_eligible: boolean; is_etf: boolean; has_reference: boolean;
  last_results_date: string | null; next_results_date: string | null; eligible: boolean; exclusion: string | null;
  risk_class: string | null; liquidity_class: string | null; categories: string[]; model_rank_pct: { p_up5_1d: number | null; p_up10_1d: number | null };
};

const urow = (symbol: string, close: number, prev: number, o: Partial<URow>): URow => ({
  symbol, sector: null, industry: null, close, close_price: close, prev_close: prev, return_5d_pct: null, return_20d_pct: null,
  vol_z20: null, rvol20: null, atr_pct: null, volatility_1y_pct: null, market_cap_bucket: null, traded_value_cr_20d: null,
  series: "EQ", price_band_pct: 20, band_raw: "20", fno_eligible: false, is_etf: false, has_reference: true,
  last_results_date: null, next_results_date: null, eligible: true, exclusion: null, risk_class: null, liquidity_class: null,
  categories: [], model_rank_pct: { p_up5_1d: null, p_up10_1d: null }, ...o,
});

// One universe row per stock: the five scanner setups, four stocks only the universe categories find, and a watchlist stock.
const UROWS: Record<string, URow> = {
  FIXBRK: urow("FIXBRK", 510, 507, { sector: "Capital Goods", rvol20: 2.2, volatility_1y_pct: 28, atr_pct: 2.94, traded_value_cr_20d: 42.6, fno_eligible: true, price_band_pct: null, band_raw: "No Band", categories: ["fno"], model_rank_pct: { p_up5_1d: 60.0, p_up10_1d: 0.0 } }),
  FIXPRE: urow("FIXPRE", 245, 246, { sector: "Chemicals", rvol20: 1.1, volatility_1y_pct: 40, atr_pct: 3.1, traded_value_cr_20d: 3.2, eligible: false, exclusion: "illiquid" }),
  FIXACC: urow("FIXACC", 88.5, 88.0, { sector: "Textiles", rvol20: 0.8, volatility_1y_pct: 24, atr_pct: 2.2, traded_value_cr_20d: 11.0, model_rank_pct: { p_up5_1d: 20.0, p_up10_1d: 100.0 } }),
  FIXTRD: urow("FIXTRD", 1210, 1205, { sector: "IT", volatility_1y_pct: 18, atr_pct: 1.9, eligible: false, exclusion: "no_traded_value" }),
  FIXPICK: urow("FIXPICK", 120, 119.5, { rvol20: 1.3, volatility_1y_pct: 33, atr_pct: 4.5, traded_value_cr_20d: 10.0, model_rank_pct: { p_up5_1d: 100.0, p_up10_1d: 40.0 } }),
  UMOM1: urow("UMOM1", 820, 810, { industry: "Information Technology", return_20d_pct: 14.2, rvol20: 1.4, volatility_1y_pct: 31, atr_pct: 2.4, traded_value_cr_20d: 25.0, next_results_date: "2026-10-21", categories: ["momentum"], model_rank_pct: { p_up5_1d: 40.0, p_up10_1d: 60.0 } }),
  UMOM2: urow("UMOM2", 95.5, 96, { return_20d_pct: 8.1, volatility_1y_pct: 45, atr_pct: 4.6, traded_value_cr_20d: 60.0, fno_eligible: true, price_band_pct: null, band_raw: "No Band", categories: ["momentum", "fno"] }),
  UVOL1: urow("UVOL1", 1500, 1440, { sector: "Healthcare", vol_z20: 3.4, rvol20: 3.6, volatility_1y_pct: 22, atr_pct: 1.6, traded_value_cr_20d: 120.0, categories: ["unusual_volume"], model_rank_pct: { p_up5_1d: 80.0, p_up10_1d: 20.0 } }),
  URES1: urow("URES1", 410, 400, { sector: "Financial Services", return_5d_pct: 6.3, vol_z20: 1.8, rvol20: 1.9, volatility_1y_pct: 30, atr_pct: 3.1, traded_value_cr_20d: 14.0, price_band_pct: 10, band_raw: "10", last_results_date: "2026-10-09", categories: ["results_day"], model_rank_pct: { p_up5_1d: 0.0, p_up10_1d: 80.0 } }),
  UWATCH: urow("UWATCH", 55, 56, { sector: "Retail", atr_pct: 5.2, traded_value_cr_20d: 0.8, eligible: false, exclusion: "illiquid" }),
};
const UCATS = {
  momentum: { total: 2, shown: 2, symbols: ["UMOM1", "UMOM2"], rank_by: "return_20d_pct", missing: 4 },
  unusual_volume: { total: 1, shown: 1, symbols: ["UVOL1"], rank_by: "vol_z20", missing: 2 },
  results_day: { total: 1, shown: 1, symbols: ["URES1"], rank_by: "return_5d_pct", missing: 0 },
  fno: { total: 2, shown: 2, symbols: ["FIXBRK", "UMOM2"], rank_by: "traded_value_cr_20d", missing: null },
};
// 2,469 stocks, 969 eligible: the excluded counts add up to the 1,500 left out.
const UNIVERSE_COUNTS = {
  total: 2469, eligible: 969, fno_eligible: 205,
  excluded: { missing_price: 0, no_traded_value: 17, no_reference: 0, series: 210, etf: 300, price_band: 590, at_band_limit: 3, illiquid: 380 },
};
const MODEL_RUN = { model: "v4", refit: "monthly", data_as_of: "2026-10-12", target_session: "2026-10-13", universe_size: 1000, scored: 994, train_end: "2026-08-31" };

interface ScanOver extends Over { universeStatus?: number; modelNoAccess?: boolean }

function universeBody(setups: string, symbols: string, over: ScanOver) {
  const want = new Set<string>();
  for (const c of Object.values(UCATS)) for (const s of c.symbols) want.add(s);
  for (const s of [...setups.split(","), ...symbols.split(",")]) if (s) want.add(s);
  const rows = [...want].filter((s) => UROWS[s]).map((s) => (over.modelNoAccess ? { ...UROWS[s], model_rank_pct: { p_up5_1d: null, p_up10_1d: null } } : UROWS[s]));
  return {
    as_of: "2026-10-12", reference_as_of: "2026-10-12", sessions: 20, mode: "eod",
    source: "NIDP feature store (nidp.stock_features_daily) · NSE bhavcopy (nidp.prices_eod) · NSE security reference (nidp.security_reference_daily)",
    rules: RULES, results_window: { from: "2026-10-06", to: "2026-10-12" }, universe: UNIVERSE_COUNTS, categories: UCATS,
    model: over.modelNoAccess
      ? { status: "no_access", reason: "Move probabilities are not enabled for this account.", heads: {} }
      : { status: "final", reason: null, heads: { p_up5_1d: { status: "final", run: MODEL_RUN, ranked_eligible: 6 }, p_up10_1d: { status: "final", run: MODEL_RUN, ranked_eligible: 6 } } },
    rows, not_found: [...want].filter((s) => !UROWS[s]),
  };
}

// backend/routes/watchlists.py :: list_watchlists, get_watchlist
const LIST_SUM = (id: string, name: string, n: number) => ({ watchlist_id: id, name, symbol_count: n, is_starter: false, seeded_from: null, created_at: "2026-10-01T10:00:00+00:00", updated_at: "2026-10-10T10:00:00+00:00" });
const LISTS = { lists: [LIST_SUM("wl1", "Swing ideas", 2), LIST_SUM("wl2", "Long term", 1)], limits: { max_lists: 20, max_symbols: 50 }, starter_pending: false };
const LIST_DETAIL: Record<string, unknown> = {
  wl1: { ...LIST_SUM("wl1", "Swing ideas", 2), quotes: { live: 0, stored: 0, none: 2 }, stocks: [
    { symbol: "FIXACC", company_name: "Fixture Accumulation Ltd", added_at: "2026-10-02T10:00:00+00:00", quote: null },
    { symbol: "UWATCH", company_name: "Fixture Watch Ltd", added_at: "2026-10-03T10:00:00+00:00", quote: null },
  ] },
  wl2: { ...LIST_SUM("wl2", "Long term", 1), quotes: { live: 0, stored: 0, none: 1 }, stocks: [{ symbol: "UMOM1", company_name: "Fixture Momentum Ltd", added_at: "2026-10-04T10:00:00+00:00", quote: null }] },
};

/** deskMocks plus the scanner's PRD routes. Returns every scan-universe request (its setups and symbols) and every list write. */
async function scanMocks(page: Page, over: ScanOver = {}) {
  await deskMocks(page, over);
  await json(page, "**/api/positional/watchlist*", over.watchStatus ? { detail: "fixture failure" } : WATCH_R, over.watchStatus ?? 200);
  await json(page, "**/api/positional/picks*", over.picksStatus ? { detail: "fixture failure" } : PICKS_R, over.picksStatus ?? 200);
  const asked: Array<{ setups: string; symbols: string }> = [];
  await page.route("**/api/positional/scan-universe*", (route) => {
    const q = new URL(route.request().url()).searchParams;
    const setups = q.get("setups") ?? "";
    const symbols = q.get("symbols") ?? "";
    asked.push({ setups, symbols });
    if (over.universeStatus) return route.fulfill({ status: over.universeStatus, contentType: "application/json", body: JSON.stringify({ detail: "upstream_unavailable" }) });
    return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(universeBody(setups, symbols, over)) });
  });
  const listWrites: Posted[] = [];
  await page.route("**/api/watchlists", (route) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(LISTS) }));
  await page.route(/\/api\/watchlists\/(wl1|wl2)$/, (route) => {
    const id = new URL(route.request().url()).pathname.split("/").pop() as string;
    return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(LIST_DETAIL[id]) });
  });
  await page.route(/\/api\/watchlists\/(wl1|wl2)\/symbols$/, (route) => {
    const req = route.request();
    const body = req.postDataJSON() as { symbol: string };
    listWrites.push({ method: req.method(), path: new URL(req.url()).pathname, body });
    const id = new URL(req.url()).pathname.split("/")[3];
    const sum = LISTS.lists.find((l) => l.watchlist_id === id) as ReturnType<typeof LIST_SUM>;
    return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ added: true, reason: null, stock: { symbol: body.symbol, company_name: null }, watchlist: { ...sum, symbol_count: sum.symbol_count + 1 } }) });
  });
  return { asked, listWrites };
}

// ── expected rows, worked out from the payloads ──

const SETUP_SYMS = expectedRows().map((r) => r.symbol);
const scoreOf = (sym: string) => expectedRows().find((r) => r.symbol === sym)?.score ?? null;
const bucketOf = (sym: string) => expectedRows().find((r) => r.symbol === sym)?.bucket ?? null;
const UNIVERSE_ONLY = Object.values(UCATS).flatMap((c) => c.symbols).filter((s, i, a) => a.indexOf(s) === i && !SETUP_SYMS.includes(s));
const ALL_SYMS = [...SETUP_SYMS, ...UNIVERSE_ONLY];
const RANK_FIELD: Record<string, keyof URow> = { return_20d_pct: "return_20d_pct", vol_z20: "vol_z20", return_5d_pct: "return_5d_pct", traded_value_cr_20d: "traded_value_cr_20d" };

/** The scanner's order restated: score, then the category's own figure, then model rank (+5%), then traded value, then symbol. */
function ordered(syms: string[], cat: keyof typeof UCATS | null = null, by: "score" | "m5" | "m10" = "score"): string[] {
  const n = (v: unknown) => (typeof v === "number" ? v : null);
  const field = cat ? RANK_FIELD[UCATS[cat].rank_by] : null;
  const traded = (s: string) => tradedOf(s) ?? n(UROWS[s]?.traded_value_cr_20d);
  const base = (a: string, b: string) => desc(scoreOf(a), scoreOf(b)) || (field ? desc(n(UROWS[a]?.[field]), n(UROWS[b]?.[field])) : 0)
    || desc(n(UROWS[a]?.model_rank_pct.p_up5_1d), n(UROWS[b]?.model_rank_pct.p_up5_1d)) || desc(traded(a), traded(b)) || a.localeCompare(b);
  const head = by === "m10" ? "p_up10_1d" : "p_up5_1d";
  return [...syms].sort((a, b) => (by === "score" ? base(a, b) : desc(n(UROWS[a]?.model_rank_pct[head]), n(UROWS[b]?.model_rank_pct[head])) || base(a, b)));
}

/** Last price and change: the setup's own daily closes when it has two, else the universe row's close and previous close. */
function priceOf(sym: string): { price: number; change: number | null; pct: number | null } {
  const line = lineOf(sym);
  if (line.length > 1) {
    const [a, b] = line.slice(-2);
    return { price: b, change: b - a, pct: ((b - a) / a) * 100 };
  }
  const u = UROWS[sym];
  return { price: u.close_price, change: u.close_price - u.prev_close, pct: ((u.close_price - u.prev_close) / u.prev_close) * 100 };
}

const atrOf = (sym: string): number | null => {
  for (const b of BUCKETS) {
    const w = (WATCHLIST.buckets[b] as Array<{ nse_symbol: string; atr_pct: number }>).find((x) => x.nse_symbol === sym);
    if (w) return w.atr_pct;
  }
  return UROWS[sym]?.atr_pct ?? null;
};
const riskOf = (sym: string) => {
  const a = atrOf(sym);
  return a == null ? null : a < RULES.risk_bands.low_below_pct ? "low" : a > RULES.risk_bands.high_above_pct ? "high" : "medium";
};
const sectorOf = (sym: string) => {
  for (const b of BUCKETS) {
    const w = (WATCHLIST.buckets[b] as Array<{ nse_symbol: string; sector: string | null }>).find((x) => x.nse_symbol === sym);
    if (w?.sector) return w.sector;
  }
  return UROWS[sym]?.sector ?? UROWS[sym]?.industry ?? null;
};
const signed2 = (v: number) => `${v > 0 ? "+" : v < 0 ? "−" : ""}${enIN(Math.abs(v), 2)}`;
const ord = (p: number) => { const n = Math.round(p); const t = n % 100; return `${n}${t >= 11 && t <= 13 ? "th" : n % 10 === 1 ? "st" : n % 10 === 2 ? "nd" : n % 10 === 3 ? "rd" : "th"}`; };
const DESK_SCAN = `${DESK}?tab=scanner`;

test.describe("Smart trading desk · AI scanner", () => {
  test("TC-13 setups are ranked by score with the pick's plan; the universe's stocks follow; status follows the bucket", async ({ page }) => {
    await scanMocks(page);
    await page.goto(DESK_SCAN);
    await expect(page.getByTestId("desk-scan-row-UVOL1")).toBeVisible();
    const want = ordered(ALL_SYMS);
    expect(want.slice(0, SETUP_SYMS.length).sort()).toEqual([...SETUP_SYMS].sort()); // setups (with a score) come first
    expect(await rowOrder(page)).toEqual(want);
    await expect(page.getByTestId("desk-scan-eyebrow")).toHaveText(`NSE · end of day 13 Oct 2026 · ${want.length} of ${want.length} shown`);

    for (const r of expectedRows()) {
      const row = page.getByTestId(`desk-scan-row-${r.symbol}`);
      await expect(row.getByTestId("desk-scan-rank")).toHaveText(String(want.indexOf(r.symbol) + 1).padStart(2, "0"));
      await expect(row.getByTestId("desk-scan-status")).toHaveAttribute("data-status", r.status);
      await expect(row.getByTestId("desk-scan-score")).toHaveText(String(Math.round(r.score)));
      const base = r.close ?? r.entry;
      await expect(row.getByTestId("desk-scan-target")).toHaveText(r.target != null && base != null ? `+${(((r.target - base) / base) * 100).toFixed(1)}%` : "—");
    }
    const brk = page.getByTestId("desk-scan-row-FIXBRK");
    await expect(brk.getByTestId("desk-scan-score")).toHaveText(String(Math.round(PICKS.picks[0].final_score * 100)));
    await expect(brk.getByTestId("desk-scan-setup")).toHaveText("Breakout confirmed");
    await expect(brk.getByTestId("desk-scan-why")).toHaveText(WATCHLIST.buckets.breakout_confirmed[0].why);
    await expect(page.getByTestId("desk-scan-row-FIXPICK").getByTestId("desk-scan-setup")).toHaveText("Scanner pick · early breakout");
    // A universe-only stock has no score ("—", never 0) and says which rule found it.
    const vol = page.getByTestId("desk-scan-row-UVOL1");
    await expect(vol.getByTestId("desk-scan-score")).toHaveText("—");
    await expect(vol.getByTestId("desk-scan-setup")).toHaveText("Unusual volume");
    await expect(vol.getByTestId("desk-scan-status")).toHaveAttribute("data-status", "rule");
    await expect(page.getByTestId("desk-scan-footnote")).toContainText("it is not a probability");
  });

  test("SP-1 the nine PRD categories, in order, each listing the rows its rule gives; Reversal says why it is empty", async ({ page }) => {
    const { asked } = await scanMocks(page);
    await page.goto(DESK_SCAN);
    await expect(page.getByTestId("desk-scan-row-UVOL1")).toBeVisible();
    expect(await texts(page, '[data-testid^="desk-scan-cat-"][aria-pressed]')).toEqual([
      "All", "Breakouts", "Near breakout", "Momentum", "Pullback continuation", "Accumulation", "Reversal candidates",
      "Unusual volume", "Results-day momentum", "F&O candidates", "User watchlist",
    ]);
    // The universe is asked once with the scanner's own setups.
    expect(asked[0].setups.split(",").sort()).toEqual([...SETUP_SYMS].sort());

    const cases: Array<[string, string[]]> = [
      ["breakouts", SETUP_SYMS.filter((s) => bucketOf(s) === "breakout_confirmed")],
      ["near_breakout", SETUP_SYMS.filter((s) => bucketOf(s) === "pre_breakout")],
      ["pullbacks", SETUP_SYMS.filter((s) => bucketOf(s) === "trend_continuation")],
      ["accumulation", SETUP_SYMS.filter((s) => bucketOf(s) === "true_accumulation")],
      ["momentum", ordered(UCATS.momentum.symbols, "momentum")],
      ["unusual_volume", ordered(UCATS.unusual_volume.symbols, "unusual_volume")],
      ["results_day", ordered(UCATS.results_day.symbols, "results_day")],
      ["fno", ordered(UCATS.fno.symbols, "fno")],
    ];
    for (const [cat, want] of cases) {
      await page.getByTestId(`desk-scan-cat-${cat}`).click();
      await expect(page.getByTestId(`desk-scan-cat-${cat}`)).toHaveAttribute("aria-pressed", "true");
      await expect.poll(() => rowOrder(page)).toEqual(want);
    }
    expect(ordered(UCATS.momentum.symbols, "momentum")).toEqual(["UMOM1", "UMOM2"]); // by 20-day return, 14.2 over 8.1

    await page.getByTestId("desk-scan-cat-reversal").click();
    await expect(page.getByTestId("desk-scan-cat-reversal")).toHaveAttribute("data-unavailable", "true");
    await expect(page.getByTestId("desk-scan-reversal-why")).toContainText("No reversal rule is defined");
    await expect(page.getByTestId("desk-scan-cat-empty")).toHaveText("No reversal list: no rule is defined.");
    expect(await rowOrder(page)).toEqual([]);

    // User watchlist: the first list's stocks, the scanner's figures where it has them, the others looked up in the universe.
    await page.getByTestId("desk-scan-cat-watchlist").click();
    await expect.poll(() => rowOrder(page)).toEqual(ordered(["FIXACC", "UWATCH"]));
    await expect.poll(() => asked.some((a) => a.symbols === "UWATCH")).toBe(true); // FIXACC is already a setup
    await expect(page.getByTestId("desk-scan-row-UWATCH").getByTestId("desk-scan-setup")).toHaveText("Watchlist stock");
    await expect(page.getByTestId("desk-scan-row-UWATCH").getByTestId("desk-scan-excluded")).toHaveText("⚠ Excluded: below the liquidity gate");
    await page.getByTestId("desk-scan-list-pick").selectOption("wl2");
    await expect.poll(() => rowOrder(page)).toEqual(["UMOM1"]);
    await expect(page).toHaveURL(/[?&]sc_list=wl2(&|$)/);
  });

  test("SP-2 each category states its rule with the thresholds and the version the route sent; SP-3 F&O links to the lab", async ({ page }) => {
    await scanMocks(page);
    await page.goto(`${DESK_SCAN}&sc_cat=momentum`);
    const rule = page.getByTestId("desk-scan-cat-rule");
    await expect(rule).toContainText("20-day return of at least 5%, close above the 50-day average, and the 50-day average rising (slope above 0% a day). Ranked by 20-day return. Eligible universe only.");
    await expect(page.getByTestId("desk-scan-cat-count")).toHaveText(`${UCATS.momentum.total} match; ${UCATS.momentum.missing} could not be judged for missing figures.`);
    await expect(page.getByTestId("desk-scan-rules-version")).toHaveText(` · ${RULES.version}`);
    await page.getByTestId("desk-scan-cat-unusual_volume").click();
    await expect(rule).toContainText("The day's volume at least 2 standard deviations above its 20-day average");
    await page.getByTestId("desk-scan-cat-results_day").click();
    await expect(rule).toContainText("dated in the 7 calendar days up to the scan date, a 5-day return of at least 3%, and volume at least 1 standard deviation above normal");
    await page.getByTestId("desk-scan-cat-breakouts").click();
    await expect(rule).toContainText("Closed 0–3% above the breakout level on at least 1.5× the 20-day average volume (last 3 sessions), and not on a gap of more than 5% above the previous close.");
    await page.getByTestId("desk-scan-cat-near_breakout").click();
    await expect(rule).toContainText("Within 2% below resistance with volume at least 1.2× the 20-day average.");

    await page.getByTestId("desk-scan-cat-fno").click();
    await expect(rule).toContainText("F&O-eligible (NSE lot-size file) and in another category or a scanner setup.");
    await page.getByTestId("desk-scan-open-lab").click();
    await expect(page).toHaveURL(/[?&]tab=fno(&|$)/);
  });

  test("SP-4 filters: each one keeps the rows its figure allows and counts the rows without the figure; unavailable ones say why", async ({ page }) => {
    await scanMocks(page);
    await page.goto(DESK_SCAN);
    await expect(page.getByTestId("desk-scan-row-UVOL1")).toBeVisible();
    await page.getByTestId("desk-scan-filters-toggle").click();
    const all = ALL_SYMS;
    const check = async (want: string[], hidden: string | null) => {
      await expect.poll(async () => (await rowOrder(page)).sort()).toEqual([...want].sort());
      if (hidden) await expect(page.getByTestId("desk-scan-hidden")).toHaveText(hidden);
      else await expect(page.getByTestId("desk-scan-hidden")).toHaveCount(0);
    };
    const reset = async () => {
      await page.getByTestId("desk-scan-reset").click();
      await expect.poll(async () => (await rowOrder(page)).length).toBe(all.length);
    };

    // Sector / industry: the industry of an index stock counts; a stock with neither is hidden and counted.
    const noSector = all.filter((s) => sectorOf(s) == null);
    await page.getByTestId("desk-scan-f-sector").selectOption("Healthcare");
    await check(all.filter((s) => sectorOf(s) === "Healthcare"), `Hidden because a filter needs a figure they do not have: ${noSector.length} with no sector.`);
    await reset();

    // Price range ₹400–1,000.
    await page.getByTestId("desk-scan-f-pmin").fill("400");
    await page.getByTestId("desk-scan-f-pmin").press("Enter");
    await page.getByTestId("desk-scan-f-pmax").fill("1000");
    await page.getByTestId("desk-scan-f-pmax").press("Enter");
    await check(all.filter((s) => priceOf(s).price >= 400 && priceOf(s).price <= 1000), null);
    expect(all.filter((s) => priceOf(s).price >= 400 && priceOf(s).price <= 1000).sort()).toEqual(["FIXBRK", "UMOM1", "URES1"]);
    await reset();

    // Relative volume ≥ 2×.
    const noRvol = all.filter((s) => UROWS[s].rvol20 == null);
    await page.getByTestId("desk-scan-f-rvol").selectOption("2");
    await check(all.filter((s) => (UROWS[s].rvol20 ?? -1) >= 2), `Hidden because a filter needs a figure they do not have: ${noRvol.length} with no relative volume.`);
    await reset();

    // Volatility (1 year) ≤ 25%.
    await page.getByTestId("desk-scan-f-vol").selectOption("25");
    await check(all.filter((s) => (UROWS[s].volatility_1y_pct ?? 999) <= 25), null);
    await reset();

    // Risk category from ATR% with the route's bands (2 / 4): the setup's own ATR first, else the universe row's.
    await expect(page.getByTestId("desk-scan-f-risk-bands")).toHaveText("ATR(14) % of price: low under 2%, high over 4%.");
    await page.getByTestId("desk-scan-f-risk").selectOption("high");
    await check(all.filter((s) => riskOf(s) === "high"), null);
    expect(all.filter((s) => riskOf(s) === "high").sort()).toEqual(["FIXPICK", "UMOM2"]);
    await reset();

    // Instrument eligibility.
    await page.getByTestId("desk-scan-f-inst").selectOption("fno");
    await check(all.filter((s) => UROWS[s].fno_eligible), null);
    await page.getByTestId("desk-scan-f-inst").selectOption("eligible");
    await check(all.filter((s) => UROWS[s].eligible), null);
    await reset();

    // Liquidity (the Liquid-only switch): ₹10 Cr from the route; FIXPICK sits exactly at 10 and stays.
    await page.getByTestId("desk-scan-liquid").click();
    const tv = (s: string) => tradedOf(s) ?? UROWS[s].traded_value_cr_20d;
    await check(all.filter((s) => (tv(s) ?? -1) >= 10), `Hidden because a filter needs a figure they do not have: ${all.filter((s) => tv(s) == null).length} with no 20-session traded value.`);
    await expect(page.getByTestId("desk-scan-liquid-note")).toHaveText(`Liquid only: average daily traded value (close × volume) over the last 20 sessions of at least ₹10 Cr (${RULES.version}).`);
    await page.getByTestId("desk-scan-liquid").click();

    // Not available, each with its reason: market cap (no bucket on any row), horizon, model probability.
    await expect(page.getByTestId("desk-scan-f-cap")).toBeDisabled();
    await expect(page.getByTestId("desk-scan-f-cap-why")).toContainText("no stock here carries a market-cap bucket");
    await expect(page.getByTestId("desk-scan-f-horizon")).toBeDisabled();
    await expect(page.getByTestId("desk-scan-f-horizon-why")).toHaveText("The model has next-session estimates only; longer horizons need model work.");
    await expect(page.getByTestId("desk-scan-f-prob")).toBeDisabled();
    await expect(page.getByTestId("desk-scan-f-prob-why")).toContainText("does not mark these estimates as calibrated");
  });

  test("SP-5 / SP-6 filters show as chips that clear one at a time, Reset clears all, and every choice lives in the URL", async ({ page }) => {
    await scanMocks(page);
    await page.goto(DESK_SCAN);
    await expect(page.getByTestId("desk-scan-row-UVOL1")).toBeVisible();
    await page.getByTestId("desk-scan-cat-momentum").click();
    await page.getByTestId("desk-scan-liquid").click();
    await page.getByTestId("desk-scan-filters-toggle").click();
    await page.getByTestId("desk-scan-f-risk").selectOption("medium");
    await page.getByTestId("desk-scan-rank-m10").click();
    await expect(page).toHaveURL(/sc_cat=momentum/);
    await expect(page).toHaveURL(/sc_liq=1/);
    await expect(page).toHaveURL(/sc_risk=medium/);
    await expect(page).toHaveURL(/sc_rank=m10/);
    const want = UCATS.momentum.symbols.filter((s) => riskOf(s) === "medium" && (UROWS[s].traded_value_cr_20d ?? -1) >= 10);
    await expect.poll(() => rowOrder(page)).toEqual(want);
    await expect(page.getByTestId("desk-scan-filters-toggle")).toContainText("Filters · 2");

    // A reload and a trip to the Chart tab and back keep all of it.
    await page.reload();
    await expect(page.getByTestId("desk-scan-cat-momentum")).toHaveAttribute("aria-pressed", "true");
    await expect(page.getByTestId("desk-scan-rank-m10")).toHaveAttribute("aria-pressed", "true");
    await expect.poll(() => rowOrder(page)).toEqual(want);
    await page.getByTestId(`desk-scan-row-${want[0]}`).getByTestId("desk-scan-setup").click();
    await expect(page).toHaveURL(/[?&]tab=chart(&|$)/);
    await expect(page).toHaveURL(/sc_risk=medium/);
    await page.getByTestId("desk-tab-scanner").click();
    await expect(page).toHaveURL(/[?&]tab=scanner(&|$)/);
    await expect(page.getByTestId("desk-scan-cat-momentum")).toHaveAttribute("aria-pressed", "true");
    await expect.poll(() => rowOrder(page)).toEqual(want);

    // One chip clears its own filter; Reset clears the rest (the category and the ranking stay).
    await page.getByTestId("desk-scan-fchip-risk").click();
    await expect(page).not.toHaveURL(/sc_risk=/);
    await expect(page.getByTestId("desk-scan-fchip-liquid")).toHaveText("Liquid ≥ ₹10 Cr ×");
    await page.getByTestId("desk-scan-reset").click();
    await expect(page).not.toHaveURL(/sc_liq=/);
    await expect(page).toHaveURL(/sc_cat=momentum/);
    await expect(page.getByTestId("desk-scan-reset")).toBeDisabled();
    await expect.poll(() => rowOrder(page)).toEqual(ordered(UCATS.momentum.symbols, "momentum", "m10"));
  });

  test("SP-7 / SP-8 the PRD columns from the payload; the probability is withheld with its reason and the model rank is a percentile", async ({ page }) => {
    await page.setViewportSize({ width: 1360, height: 900 });
    await scanMocks(page);
    await page.goto(DESK_SCAN);
    await expect(page.getByTestId("desk-scan-table")).toHaveAttribute("data-layout", "table");
    expect(await texts(page, '[data-testid^="desk-scan-col-"]')).toEqual([
      "#", "Stock", "Score", "P(+5% next session)", "Model rank", "Pattern / catalyst", "Confirmation", "Liquidity · risk", "To target", "24 sessions", "Action",
    ]);
    for (const sym of ALL_SYMS) {
      const row = page.getByTestId(`desk-scan-row-${sym}`);
      const p = priceOf(sym);
      await expect(row.getByTestId("desk-scan-symbol")).toContainText(sym);
      await expect(row).toContainText(inr2(p.price));
      await expect(row.getByTestId("desk-scan-change-abs")).toHaveText(signed2(p.change as number));
      await expect(row.getByTestId("desk-scan-change")).toHaveText(signedPct(p.pct as number));
      // Probability: withheld, with the reason on the cell.
      await expect(row.getByTestId("desk-scan-odds")).toHaveAttribute("data-state", "withheld");
      await expect(row.getByTestId("desk-scan-odds")).toContainText("Withheld");
      await expect(row.getByTestId("desk-scan-odds")).toHaveAttribute("title", /does not mark these estimates as calibrated/);
      // Model rank: the route's percentile, or "—" with the reason.
      const rk = UROWS[sym].model_rank_pct.p_up5_1d;
      await expect(row.getByTestId("desk-scan-mrank")).toHaveAttribute("data-value", rk == null ? "" : String(rk));
      if (rk == null) await expect(row.getByTestId("desk-scan-mrank")).toContainText("—");
      else await expect(row.getByTestId("desk-scan-mrank")).toHaveText(`${ord(rk)} pct`);
      // Liquidity and risk.
      const tv = tradedOf(sym) ?? UROWS[sym].traded_value_cr_20d;
      await expect(row.getByTestId("desk-scan-traded")).toHaveText(tv == null ? "No traded value" : `₹${tv >= 100 ? new Intl.NumberFormat("en-IN").format(Math.round(tv)) : tv.toFixed(1)} Cr a day`);
      const rc = riskOf(sym);
      await expect(row.getByTestId("desk-scan-risk")).toHaveAttribute("data-class", rc ?? "");
    }
    // FIXBRK: confirmed, volume 1.8×, three events on record, liquid and F&O, medium risk at 2.9% ATR.
    const brk = page.getByTestId("desk-scan-row-FIXBRK");
    await expect(brk.getByTestId("desk-scan-evidence")).toHaveText("Vol 1.8×");
    await expect(brk.getByTestId("desk-scan-catalyst")).toHaveText("+ 3 events · ");
    await expect(brk.getByTestId("desk-scan-liq-class")).toHaveText("Liquid · F&O");
    await expect(brk.getByTestId("desk-scan-risk")).toContainText("ATR 2.9%");
    // A results-day stock: its results date is the catalyst; its 10% band is its tradability.
    await expect(page.getByTestId("desk-scan-row-URES1").getByTestId("desk-scan-catalyst")).toHaveText("Results 9 Oct");
    await expect(page.getByTestId("desk-scan-row-URES1").getByTestId("desk-scan-liq-class")).toHaveText("Liquid · Band 10%");
    await expect(page.getByTestId("desk-scan-row-UMOM1").getByTestId("desk-scan-catalyst")).toHaveText("Results due 21 Oct");
    await expect(page.getByTestId("desk-scan-row-UVOL1").getByTestId("desk-scan-evidence")).toHaveText("Vol z 3.4 · RVOL 3.6×");
    // An ineligible setup says so and has no rank; missing is never shown as 0.
    await expect(page.getByTestId("desk-scan-row-FIXPRE").getByTestId("desk-scan-excluded")).toHaveText("⚠ Excluded: below the liquidity gate");
    await expect(page.getByTestId("desk-scan-row-FIXPRE").getByTestId("desk-scan-mrank")).toHaveAttribute("title", "Not in the eligible universe: below the liquidity gate.");
    await expect(page.getByTestId("desk-scan-row-FIXTRD").getByTestId("desk-scan-traded")).toHaveText("No traded value");

    // Ranking by the model's rank: highest percentile first, unranked last.
    await page.getByTestId("desk-scan-rank-m5").click();
    await expect.poll(() => rowOrder(page)).toEqual(ordered(ALL_SYMS, null, "m5"));
    await page.getByTestId("desk-scan-rank-m10").click();
    await expect.poll(() => rowOrder(page)).toEqual(ordered(ALL_SYMS, null, "m10"));
    await expect(page.getByTestId("desk-scan-col-odds")).toHaveText("P(+10% next session)");
    await expect(page.getByTestId("desk-scan-row-FIXACC").getByTestId("desk-scan-mrank")).toHaveText("100th pct");
  });

  test("SP-9 actions: open the analysis, add to a list (POST body), paper trade at the setup's levels (POST body); nothing else is written", async ({ page }) => {
    await page.setViewportSize({ width: 1360, height: 900 });
    const { listWrites } = await scanMocks(page);
    const paperPosts = await mockDeskWrites(page);
    const writes = recordWrites(page);
    await page.goto(DESK_SCAN);
    const brk = page.getByTestId("desk-scan-row-FIXBRK");
    await brk.getByTestId("desk-scan-act").click();
    const panel = page.getByTestId("desk-scan-actions-FIXBRK");
    await expect(panel).toBeVisible();

    // Add to a list: the second list, through the watchlists API.
    await panel.getByTestId("watchlist-add-to-list").click();
    await panel.getByTestId("watchlist-add-to-list-pick").selectOption("wl2");
    await panel.getByTestId("watchlist-add-to-list-save").click();
    await expect(panel.getByTestId("watchlist-add-to-list-done")).toHaveText("Added to Long term.");
    expect(listWrites).toEqual([{ method: "POST", path: "/api/watchlists/wl2/symbols", body: { symbol: "FIXBRK" } }]);

    // Paper trade: disabled until a whole quantity is typed; the body carries the pick's levels and the scan date.
    await expect(panel.getByTestId("desk-scan-paper-add")).toBeDisabled();
    await panel.getByTestId("desk-scan-paper-qty").fill("2.5");
    await expect(panel.getByTestId("desk-scan-paper-add")).toBeDisabled();
    await panel.getByTestId("desk-scan-paper-qty").fill("12");
    const p = PICKS.picks[0];
    await expect(panel.getByTestId("desk-scan-paper-note")).toContainText(`entry ${inr2(p.entry_price)}, stop ${inr2(p.stoploss)}, target ${inr2(p.target_price)}. No order is placed and nothing is sent to a broker`);
    await panel.getByTestId("desk-scan-paper-add").click();
    await expect(panel.getByTestId("desk-scan-paper-done")).toHaveText(`Paper trade added: 12 FIXBRK at ${inr2(p.entry_price)}. No order is placed.`);
    expect(paperPosts.map((x) => x.body)).toEqual([{
      symbol: "FIXBRK", quantity: 12, entry_price: p.entry_price, stop_price: p.stoploss, target_price: p.target_price,
      source: { kind: "scanner", bucket: "breakout_confirmed", signal_date: PICKS.signal_date },
    }]);

    // A universe-only stock has no plan: no paper trade, and it says why.
    await page.getByTestId("desk-scan-row-UVOL1").getByTestId("desk-scan-act").click();
    const uvol = page.getByTestId("desk-scan-actions-UVOL1");
    await expect(uvol.getByTestId("desk-scan-paper-none")).toContainText("needs a scanner setup with an entry and a stop below it");
    expect(writes.map((w) => w.split(" ")[0])).toEqual(["POST", "POST"]);

    // Open analysis: the Chart tab with that stock.
    await uvol.getByTestId("desk-scan-act-open").click();
    await expect(page).toHaveURL(/[?&]tab=chart(&|$)/);
    await expect(page).toHaveURL(/[?&]sym=UVOL1(&|$)/);
  });

  test("SP-10 / SP-11 / SP-12 the eligible universe and every exclusion, About the model with its limitation, and the trust lines", async ({ page }) => {
    await scanMocks(page);
    await page.goto(DESK_SCAN);
    await expect(page.getByTestId("desk-scan-row-UVOL1")).toBeVisible();
    await expect(page.getByTestId("desk-scan-trust")).toHaveText(
      `NSE end-of-day scanner · NIDP feature store · End of day · 13 Oct 2026 · Rules-based · ${RULES.version} · smart_v2 · positional.v1.0`);
    await expect(page.getByTestId("desk-scan-trust")).toHaveAttribute("data-mode", "eod");
    await expect(page.getByTestId("desk-scan-trust-model")).toHaveText(
      `Move-odds model · End of day · 13 Oct 2026 · Model output · Move-odds ${RUN.model} · out-of-sample ${RECORD.window_label} · probability withheld, not marked calibrated`);
    await expect(page.getByTestId("desk-scan-trust-model")).toHaveAttribute("data-maker", "model");

    await page.getByTestId("desk-scan-universe-toggle").click();
    const u = UNIVERSE_COUNTS;
    await expect(page.getByTestId("desk-scan-universe-count")).toHaveText(`${u.eligible} of 2,469`);
    expect(u.total - u.eligible).toBe(Object.values(u.excluded).reduce((a, b) => a + b, 0));
    for (const [k, n] of Object.entries(u.excluded)) await expect(page.getByTestId(`desk-scan-excl-${k}`)).toContainText(`: ${n.toLocaleString("en-IN")}`);
    await expect(page.getByTestId("desk-scan-excl-illiquid")).toHaveText("average traded value under ₹10 Cr a day over 20 sessions: 380");
    await expect(page.getByTestId("desk-scan-excl-price_band")).toHaveText("a price band under 10% (NSE's tight circuit limits): 590");
    await expect(page.getByTestId("desk-scan-universe-fno")).toHaveText(`F&O eligible in the eligible universe: ${u.fno_eligible} (NSE lot-size file, reference of 12 Oct 2026).`);
    await expect(page.getByTestId("desk-scan-setup-universe")).toHaveText("Setups come from the positional scanner: the top 80 stocks by score above ₹5 whose stage is not WEAK or EXTENDED, with at least 30 sessions of bars.");

    await page.getByTestId("desk-scan-about-toggle").click();
    const about = page.getByTestId("desk-scan-about-model");
    await expect(about).toContainText("backend/nidp/migrations/149_tpd_move_odds_publish.sql");
    await expect(about).toContainText("setup_rules.py");
    await expect(page.getByTestId("desk-scan-about-odds")).toContainText(`Published run: model ${RUN.model}, monthly refit, trained to 31 Aug 2026, ${RUN.scored} of ${RUN.universe_size.toLocaleString("en-IN")} stocks scored on data of 13 Oct 2026.`);
    await expect(page.getByTestId("desk-scan-model-limit")).toHaveText(
      "Limitation (PRD §5.4): “Prior evaluation identified substantial dependence on volatility features and gaps in stock-universe coverage. Therefore, the initial scanner must not assume that the model's ranking is a reliable estimate of profitability.”");
  });

  test("TC-15 odds 403: the probability says the account is not enabled, the model rank is “—” and ranking by it is off", async ({ page }) => {
    await scanMocks(page, { oddsStatus: 403, modelNoAccess: true });
    await page.goto(DESK_SCAN);
    await expect(page.getByTestId("desk-scan-record")).toHaveAttribute("data-state", "no_access");
    await expect(page.getByTestId("desk-scan-record")).toHaveText("Move-odds · not enabled for this account");
    for (const sym of ALL_SYMS) {
      const row = page.getByTestId(`desk-scan-row-${sym}`);
      await expect(row.getByTestId("desk-scan-odds")).toHaveAttribute("title", "Move probabilities are not enabled for this account.");
      await expect(row.getByTestId("desk-scan-mrank")).toHaveAttribute("data-value", "");
      await expect(row.getByTestId("desk-scan-mrank")).toContainText("—");
      await expect(row.getByTestId("desk-scan-catalyst").filter({ hasText: "event" })).toHaveCount(0);
    }
    await expect(page.getByTestId("desk-scan-rank-m5")).toBeDisabled();
    await expect(page.getByTestId("desk-scan-rank-m10")).toBeDisabled();
  });

  test("each setup row draws its last daily closes from spark_closes", async ({ page }) => {
    await page.setViewportSize({ width: 1360, height: 900 });
    await scanMocks(page);
    await page.goto(DESK_SCAN);
    await expect(page.getByTestId("desk-scan-table")).toHaveAttribute("data-layout", "table");
    for (const r of expectedRows()) {
      const row = page.getByTestId(`desk-scan-row-${r.symbol}`);
      const pts = lineOf(r.symbol);
      if (pts.length > 1) {
        await expect(row.getByTestId("desk-scan-spark")).toHaveAttribute("data-points", String(pts.length));
        const tone = pts[pts.length - 1] > pts[0] ? "mint" : pts[pts.length - 1] < pts[0] ? "danger" : "ink";
        await expect(row.getByTestId("desk-scan-spark")).toHaveAttribute("data-tone", tone);
      } else {
        await expect(row.getByTestId("desk-scan-spark-none")).toHaveText("No line");
      }
    }
  });

  test("TC-16 a row opens the Chart tab with that stock, and the selected stock's row is marked", async ({ page }) => {
    await scanMocks(page);
    await page.goto(`${DESK_SCAN}&sym=FIXACC`);
    await expect(page.getByTestId("desk-scan-row-FIXACC")).toHaveAttribute("data-selected", "true");
    await expect(page.getByTestId("desk-scan-row-FIXBRK")).toHaveAttribute("data-selected", "false");
    await page.getByTestId("desk-scan-row-FIXPRE").getByTestId("desk-scan-setup").click();
    await expect(page).toHaveURL(/[?&]tab=chart(&|$)/);
    await expect(page).toHaveURL(/[?&]sym=FIXPRE(&|$)/);
    await expect(page.getByTestId("desk-chart-symbol")).toHaveText("FIXPRE");
  });

  test("TC-17 both scanner routes and the universe fail → error with retry", async ({ page }) => {
    await scanMocks(page, { watchStatus: 500, picksStatus: 500, universeStatus: 502 });
    await page.goto(DESK_SCAN);
    const err = page.getByTestId("desk-scan-error");
    await expect(err).toBeVisible(SLOW);
    await expect(err.getByRole("alert")).toContainText("The scanner didn’t load");
    await expect(err.getByRole("button", { name: "Retry ›" })).toBeVisible();
  });

  test("TC-17 one scanner route fails → the other's rows and a note naming the route", async ({ page }) => {
    await scanMocks(page, { picksStatus: 500 });
    await page.goto(DESK_SCAN);
    await expect(page.getByTestId("desk-scan-partial")).toContainText("GET /api/positional/picks", SLOW);
    const watchOnly = BUCKETS.flatMap((b) => (WATCHLIST.buckets[b] as Watch[]).map((w) => w.nse_symbol));
    await expect(page.getByTestId("desk-scan-row-FIXPICK")).toHaveCount(0);
    for (const s of watchOnly) await expect(page.getByTestId(`desk-scan-row-${s}`).getByTestId("desk-scan-target")).toHaveText("—");
    await expect(page.getByTestId("desk-scan-trust")).toHaveAttribute("data-status", "failed");
  });

  test("SP-15 the universe fails → setups still listed with a note; its categories show an error with retry", async ({ page }) => {
    await scanMocks(page, { universeStatus: 502 });
    await page.goto(DESK_SCAN);
    await expect.poll(async () => (await rowOrder(page)).sort(), SLOW).toEqual([...SETUP_SYMS].sort());
    await page.getByTestId("desk-scan-universe-toggle").click();
    await expect(page.getByTestId("desk-scan-universe")).toContainText("GET /api/positional/scan-universe did not answer");
    await expect(page.getByTestId("desk-scan-universe-retry")).toBeVisible();
    await page.getByTestId("desk-scan-cat-momentum").click();
    await expect(page.getByTestId("desk-scan-cat-error")).toContainText("This category needs the universe scan, which didn’t load");
    await expect(page.getByTestId("desk-scan-cat-error").getByRole("button", { name: "Retry ›" })).toBeVisible();
  });

  // PRD-round screenshots (e2e/screenshots, git-ignored) for a visual check; they assert only that the tab rendered.
  for (const vp of [{ width: 1440, height: 900, name: "1440" }, { width: 1360, height: 900, name: "1360" }, { width: 390, height: 844, name: "390" }]) {
    test(`SHOT scanner PRD at ${vp.name}`, async ({ page }) => {
      await page.setViewportSize({ width: vp.width, height: vp.height });
      await scanMocks(page);
      await page.goto(`${DESK_SCAN}&sym=FIXBRK`);
      await expect(page.getByTestId("desk-scan-row-UVOL1")).toBeVisible();
      await page.waitForTimeout(300);
      await page.screenshot({ path: `e2e/screenshots/prd-scanner-after-${vp.name}.png` });
      await page.getByTestId("desk-scan-filters-toggle").click();
      await page.getByTestId("desk-scan-row-FIXBRK").getByTestId("desk-scan-act").click();
      await page.setViewportSize({ width: vp.width, height: vp.width > 700 ? 2400 : 4200 });
      await page.waitForTimeout(300);
      await page.screenshot({ path: `e2e/screenshots/prd-scanner-after-${vp.name}-tall.png` });
    });
  }

  test("an empty scan and an empty universe category say so and name the scan date", async ({ page }) => {
    await scanMocks(page);
    await json(page, "**/api/positional/watchlist*", { ...WATCH_R, buckets: { breakout_confirmed: [], pre_breakout: [], true_accumulation: [], trend_continuation: [] } });
    await json(page, "**/api/positional/picks*", { ...PICKS_R, count: 0, picks: [] });
    await page.goto(`${DESK_SCAN}&sc_cat=breakouts`);
    await expect(page.getByTestId("desk-scan-cat-empty")).toHaveText("No setup in this group on the 13 Oct 2026 scan.");
    // The universe's own categories still list their stocks on a day without setups (staging today).
    await page.getByTestId("desk-scan-cat-momentum").click();
    await expect.poll(() => rowOrder(page)).toEqual(ordered(UCATS.momentum.symbols, "momentum"));
  });
});

// ── Chart analysis and risk desk ─────────────────────────────────────────

// ── Chart analysis, risk desk and the opportunity detail: their own payloads ──
// MOCK — not real data. Each payload below is in the shape its route returns (the route's file is named beside it);
// the figures are worked out here from BARS, by an independent restatement of the documented formulas, so the
// assertions compare the screen with what the server would have answered for these bars.

/** Nifty 50 closes on the BARS sessions (nidp.index_eod, via the indicator route). */
const NIFTY = BARS.map((b, i) => [b[0], 20_000 + 5 * i] as const);
const mean = (xs: number[]) => xs.reduce((a, b) => a + b, 0) / xs.length;

/** calculator.py _ema_series: seeded with the FIRST value, k = 2 / (n + 1); shown once n values exist. */
function emaFull(xs: number[], n: number): number[] {
  const k = 2 / (n + 1);
  const out: number[] = [];
  let e = xs[0];
  xs.forEach((x, i) => {
    if (i > 0) e = x * k + e * (1 - k);
    out.push(e);
  });
  return out;
}
const emaMasked = (xs: number[], n: number) => emaFull(xs, n).map((v, i) => (i >= n - 1 ? v : null));

/** GET /api/research/chart/live/{symbol}/indicators (backend/routes/research_chart.py :: live_indicators) for these bars. */
function liveIndicators(symbol: string, bars: Bar[] = BARS) {
  const c = bars.map((b) => b[4]);
  const h = bars.map((b) => b[2]);
  const l = bars.map((b) => b[3]);
  const v = bars.map((b) => b[5]);
  const n = c.length;
  const line = emaFull(c, 12).map((x, i) => x - emaFull(c, 26)[i]);
  const sig = emaFull(line.slice(25), 9);
  const macd = line[n - 1];
  const signal = sig[sig.length - 1];
  const avg20 = mean(v.slice(n - 21, n - 1));
  const vwapAt = (i: number) => {
    const w = bars.slice(i - 19, i + 1);
    return w.reduce((s, b) => s + ((b[2] + b[3] + b[4]) / 3) * b[5], 0) / w.reduce((s, b) => s + b[5], 0);
  };
  const atr = atrLast(bars, 14);
  const stockRet = (c[n - 1] / c[n - 64] - 1) * 100;
  const benchRet = (NIFTY[n - 1][1] / NIFTY[n - 64][1] - 1) * 100;
  const k = Math.min(126, n);
  const days = bars.slice(n - k).map((b) => b[0]);
  return {
    symbol, as_of: bars[n - 1][0], sessions: n, source: "nidp.prices_eod_adjusted", mode: "eod", adjustment_status: "SPLIT_BONUS_ADJUSTED",
    pit_status: "PIT_UNVERIFIED",
    method: "backend/nidp/services/technical_indicator_engine/calculator.py (the engine behind stock_features_daily), run on the adjusted daily bars above",
    values: {
      close: c[n - 1], ema20: emaFull(c, 20)[n - 1], ema50: emaFull(c, 50)[n - 1], ema200: n >= 200 ? emaFull(c, 200)[n - 1] : null,
      rsi14: rsiLast(c, 14), atr14: atr, atr_pct: (atr / c[n - 1]) * 100,
      macd, macd_signal: signal, macd_hist: macd - signal,
      roc20: (c[n - 1] / c[n - 21] - 1) * 100,
      avg_volume20: avg20, rvol20: v[n - 1] / avg20, vwap20: vwapAt(n - 1),
      resistance20: Math.max(...h.slice(n - 20)), support20: Math.min(...l.slice(n - 20)),
      avg_traded_value_cr20: mean(c.slice(n - 20).map((x, i) => x * v[n - 20 + i])) / 1e7,
      rs63: { stock_return_pct: stockRet, benchmark_return_pct: benchRet, excess_pct: stockRet - benchRet, from: bars[n - 64][0], to: bars[n - 1][0] },
    },
    series: {
      days,
      ema20: emaMasked(c, 20).slice(n - k), ema50: emaMasked(c, 50).slice(n - k), ema200: emaMasked(c, 200).slice(n - k),
      vwap20: bars.map((_, i) => (i >= 19 ? vwapAt(i) : null)).slice(n - k),
    },
    definitions: [
      ["ema20", "EMA 20", "20 sessions", "Exponential moving average of the close, k = 2 ÷ (20 + 1), seeded with the first close of the window (calculator.py _ema_series); none until 20 sessions exist."],
      ["ema50", "EMA 50", "50 sessions", "As EMA 20 with k = 2 ÷ (50 + 1), seeded with the first close of the window."],
      ["ema200", "EMA 200", "200 sessions", "As EMA 20 with k = 2 ÷ (200 + 1), seeded with the first close of the window (up to 750 sessions)."],
      ["rsi14", "RSI 14", "14 sessions", "Wilder's RSI."],
      ["atr14", "ATR 14", "14 sessions", "Wilder's average true range."],
      ["atr_pct", "ATR %", "14 sessions", "ATR 14 ÷ the last close × 100."],
      ["macd", "MACD 12 / 26 / 9", "35 sessions", "EMA 12 − EMA 26 of the close; signal = EMA 9 of the MACD line from the 26th session on."],
      ["roc20", "Rate of change 20", "20 sessions", "(Close ÷ the close 20 sessions earlier − 1) × 100."],
      ["avg_volume20", "Volume MA 20", "20 sessions", "Mean volume of the 20 sessions before the last one."],
      ["rvol20", "Relative volume", "20 sessions", "The last session's volume ÷ volume MA 20."],
      ["vwap20", "VWAP 20D", "20 sessions", "A 20-day volume-weighted average of daily prices, not the intraday VWAP."],
      ["rs63", "Relative strength vs Nifty 50", "63 sessions", "The stock's 63-session return minus Nifty 50's over the same two dates."],
      ["resistance20", "Resistance · 20-session high", "20 sessions", "Highest high of the last 20 sessions."],
      ["support20", "Support · 20-session low", "20 sessions", "Lowest low of the last 20 sessions."],
      ["avg_traded_value_cr20", "Traded value · 20 sessions", "20 sessions", "Mean of close × volume over the last 20 sessions, ₹ crore a day."],
    ].map(([key, label, lookback, formula]) => ({ key, label, lookback, formula })),
    benchmark: { name: "Nifty 50", source: "nidp.index_eod", as_of: NIFTY[n - 1][0], reason: null },
    // staging today: an F&O stock carries "No Band" and a null percentage
    tradability: { as_of_date: "2026-10-14", price_band_pct: null, band_raw: "No Band", fno_eligible: true, is_etf: false, series: "EQ", source: "nidp.security_reference_daily" },
    tradability_reason: null,
    liquidity_rule: { min_traded_value_cr: 10, source: "services/positional_engine/setup_rules.py LIQUIDITY" },
  };
}
const LIVE = liveIndicators("FIXBRK");
// MOCK — not real data: the server's rule-based hypothetical levels (ATR 2x stop, 2R target).
const HYPO = {
  rule: "ATR_2X_STOP", version: "1", label: "Rule-based hypothetical levels, not a scanner pick and not a recommendation",
  constants: { atr_multiple: 2, min_stop_atr: 0.5, reward_multiple: 2, atr_period: 14 },
  entry: 500, stop: 480, target: 540, risk_reward: 2, stop_basis: "atr", reason: null, source: "fixture",
};

type CritStatus = "pass" | "fail" | "pending" | "na";
const crit = (key: string, label: string, status: CritStatus, extra: Record<string, unknown> = {}) => ({ key, label, status, judged_by: null, observed: null, reason: null, ...extra });

// GET /api/research/chart/live/{symbol}/patterns (backend/routes/research_chart.py :: live_patterns)
const LIVE_PAT = {
  symbol: "FIXBRK", as_of: "2026-10-13", sessions: 200, source: "nidp.prices_eod_adjusted", mode: "eod", adjustment_status: "SPLIT_BONUS_ADJUSTED",
  pit_status: "PIT_UNVERIFIED",
  engine: { name: "research.charting.patterns.detect_as_of", engine_version: "0.1.0", profile: "PATTERN_CONFIRMATION_V1_RESEARCH", config_hash: "05167d3ae57f18602b8761ee21de311f", registry_version: "1.0.0" },
  state_rule: { confirmed: "PRICE_CONFIRMED or later, with the engine's volume component PASS." },
  criteria_rule: { liquidity: "Desk rule: mean traded value over 20 sessions of at least ₹10 Cr a day." },
  patterns: [
    {
      pattern_id: "FIXBRK:RECTANGLE:2026-08-20:500.00", pattern_type: "RECTANGLE", label: "Rectangle", direction: "BULLISH", lifecycle_status: "PRICE_CONFIRMED",
      state: "confirmed", state_reason: "Closed beyond the level by the breakout buffer, on follow-through volume in the band.", detected_on: "2026-10-09",
      formation_start: "2026-08-20", formation_end: "2026-10-13", levels: { resistance: 500, support: 470 }, events: [{ date: "2026-10-09", event_type: "PRICE_CONFIRMED" }],
      rules: [{ rule_id: "CLOSE_ABOVE_BREAKOUT", result: "PASS", observed: 506.2, threshold: 502.5 }, { rule_id: "FOLLOWTHROUGH_VOLUME_BAND", result: "PASS", observed: 1.6, threshold: null }],
      components: { geometry: "PASS", price: "PASS", volume: "PASS", volatility: "PENDING", market: "UNAVAILABLE", sector: "UNAVAILABLE", data_quality: "VALID" },
      criteria: [
        crit("price_structure", "Price structure", "pass", { judged_by: "engine", observed: "geometry PASS · price PASS" }),
        crit("volume", "Volume", "pass", { judged_by: "engine", observed: "PASS" }),
        crit("trend", "Trend", "pass", { judged_by: "desk rule", observed: "close 500.39 · EMA 50 495.10 · EMA 200 480.20" }),
        crit("relative_strength", "Relative strength", "fail", { judged_by: "desk rule", observed: "−2.1 points vs Nifty 50 over 63 sessions" }),
        crit("volatility", "Volatility", "pending", { judged_by: "engine", observed: "PENDING" }),
        crit("liquidity", "Liquidity", "fail", { judged_by: "desk rule", observed: "₹6.5 Cr a day", threshold: 10 }),
        crit("regime", "Market regime", "na", { observed: "UNAVAILABLE", reason: "The pattern engine has no market context yet (it never sets CONTEXT_VALIDATED)." }),
        crit("events", "Events", "na", { reason: "The live engine does not join corporate events; the stock's filings are listed separately." }),
      ],
    },
    {
      pattern_id: "FIXBRK:SUPPORT_RESISTANCE:2026-07-01:470.00", pattern_type: "SUPPORT_RESISTANCE", label: "Support / resistance", direction: "BEARISH",
      lifecycle_status: "FAILED", state: "invalidated", state_reason: "The breakout failed: price came back through the level.", detected_on: "2026-09-02",
      formation_start: "2026-07-01", formation_end: "2026-10-13", levels: { level: 470 }, events: [], rules: [],
      components: { geometry: "PASS", price: "PASS", volume: "FAIL", volatility: "PASS", market: "UNAVAILABLE", sector: "UNAVAILABLE", data_quality: "VALID" },
      criteria: [
        crit("price_structure", "Price structure", "pass"), crit("volume", "Volume", "fail"), crit("trend", "Trend", "fail"), crit("relative_strength", "Relative strength", "pass"),
        crit("volatility", "Volatility", "pass"), crit("liquidity", "Liquidity", "fail", { threshold: 10 }), crit("regime", "Market regime", "na", { reason: "No market context." }),
        crit("events", "Events", "na", { reason: "No event join." }),
      ],
    },
  ],
  total: 2,
  families: [
    { pattern_type: "SUPPORT_RESISTANCE", label: "Support / resistance", enabled: true, disabled_reason: null, spec: "docs/charting.md §13.2" },
    { pattern_type: "RECTANGLE", label: "Rectangle", enabled: true, disabled_reason: null, spec: "docs/charting.md §11" },
    { pattern_type: "HH_HL", label: "Higher highs / higher lows", enabled: true, disabled_reason: null, spec: "docs/charting.md §11" },
    { pattern_type: "ASCENDING_TRIANGLE", label: "Ascending triangle", enabled: false, disabled_reason: "no detector implemented; specification only", spec: "NI-3 §2" },
    { pattern_type: "DOUBLE_TOP", label: "Double top", enabled: false, disabled_reason: "no detector implemented; specification only", spec: "NI-3 §5" },
    { pattern_type: "CUP_AND_HANDLE", label: "Cup & handle", enabled: false, disabled_reason: "no detector implemented; specification only", spec: "NI-3 §7" },
  ],
};

/** 95% Wilson interval, restated. */
function wilson(k: number, n: number) {
  const z = 1.96;
  const p = k / n;
  const d = 1 + (z * z) / n;
  const c = (p + (z * z) / (2 * n)) / d;
  const half = (z * Math.sqrt((p * (1 - p)) / n + (z * z) / (4 * n * n))) / d;
  return [Math.round(Math.max(0, c - half) * 1e4) / 1e4, Math.round(Math.min(1, c + half) * 1e4) / 1e4];
}
const calRow = (metric: string, lo: number, hi: number, n: number, k: number, ret: number, dd: number, matched: boolean) => {
  const [a, b] = wilson(k, n);
  return { metric, bucket_lo: lo, bucket_hi: hi, horizon_days: 10, sample_count: n, moves_count: k, probability: Math.round((k / n) * 1e4) / 1e4, avg_fwd_return: ret, avg_fwd_drawdown: dd, ci95_lo: a, ci95_hi: b, refreshed_at: "2026-10-01T20:00:00+05:30", matched };
};
// GET /api/positional/backtest/calibration?symbol=&horizon_days=10 (backend/routes/positional.py :: get_calibration)
const CAL = {
  metrics: {
    broke_high: { label: "Broke its 20-session high", outcome_type: "touch", rule: "Within the horizon, any session's intraday high went above the 20-session high the stock had on the scan day." },
    moved_scaled: { label: "Rose by its scaled threshold", outcome_type: "touch", rule: "Within the horizon, the highest intraday high was at least max(5%, 3 × ATR%) above the scan-day close." },
    moved_5pct: { label: "Rose 5%", outcome_type: "touch", rule: "Within the horizon, the highest intraday high was at least 5% above the scan-day close." },
  },
  measures: { probability: "Hit rate." },
  not_measured: {
    median_return: "Not stored: the labeller keeps each scan's maximum excursion, not a realised exit return.",
    costs: "None applied: the labels are price-only, with no brokerage, slippage or taxes.",
    benchmark: "None: the labels are not compared with an index over the same sessions.",
    out_of_sample: "None: the buckets are fitted on every labelled scan; no later period is held out. Treat the hit rates as in-sample.",
  },
  source: "accumulation_calibration", method: "services/positional_engine/backtest.py",
  sample: { first_scan_date: "2024-01-02", last_scan_date: "2026-09-30", labelled_rows: 41_250, engine_versions: ["v2.2"] },
  symbol_score: { symbol: "FIXBRK", as_of_date: "2026-10-13", accumulation_score: 0.62 },
  buckets: [
    calRow("broke_high", 0.55, 0.65, 100, 40, 6.1, -3.4, true),
    calRow("broke_high", 0.65, 0.75, 50, 30, 7.2, -2.9, false),
    calRow("moved_5pct", 0.55, 0.65, 100, 31, 6.1, -3.4, true),
    calRow("moved_scaled", 0.55, 0.65, 100, 22, 6.1, -3.4, true),
  ],
  count: 4,
};
const CAL_EMPTY = {
  ...CAL, buckets: [], count: 0, sample: null, sample_reason: "No labelled scans on record (positional_backtest_labels is empty).", symbol_score: null,
  symbol_reason: "No accumulation score on record for FIXBRK (stock_technical_features).",
  empty_reason: "No calibration rows on record: the accumulation backtest (POST /api/positional/backtest/label, then /backtest/calibrate) has not been run here.",
};

// POST /api/copilot/widgets/company_financials (backend/routes/copilot_widgets.py) — a read sent as POST.
const COMPANY = {
  kind: "company_financials",
  data: {
    v3_score: { pe_ttm: 24.1, pb: 3.2, roe_pct: 18.4, debt_to_equity: 0.42, market_cap_cr: 12_450, market_cap_bucket: "mid" },
    rows: [
      { quarter: "Q1 FY27", period_end: "2026-06-30", revenue_cr: 1520.4, ebitda_cr: 240.1, pat_cr: 132.5, eps_basic: 8.2, ebitda_margin_pct: 15.8, revenue_yoy_pct: 12.4, pat_yoy_pct: -4.2 },
      { quarter: "Q4 FY26", period_end: "2026-03-31", revenue_cr: 1490.0, ebitda_cr: 230.0, pat_cr: 140.1, eps_basic: 8.6, ebitda_margin_pct: 15.4, revenue_yoy_pct: 10.1, pat_yoy_pct: 6.0 },
      { _type: "shareholding", period: "Jun 2026", period_end: "2026-06-30", promoter_pct: 52.6, promoter_pledged_pct: 6.0, fii_pct: 17.9, dii_pct: 13.8, mf_pct: 9.0, public_pct: 15.7 },
      { _type: "shareholding", period: "Sep 2026", period_end: "2026-09-30", promoter_pct: 52.1, promoter_pledged_pct: 6.5, fii_pct: 18.2, dii_pct: 14.0, mf_pct: 9.1, public_pct: 15.7 },
    ],
  },
};

// GET /api/filings/feed?symbol=FIXBRK&days=30&sort=latest&limit=20 (backend/routes/filings.py :: filings_feed)
const FILINGS = {
  ok: true, total: 2, facets: { results: 1, corporate_action: 1 },
  rows: [
    { id: "f1", ticker: "FIXBRK", code: "FIXBRK", name: "Fixture Breakout Ltd", date: "2026-10-08T17:20:00+05:30", exchange: "NSE", category: "results", impact: "high",
      sentiment: "positive", docLabel: "Financial Results", url: "https://www.nseindia.com/fixture/f1.pdf", one: "Revenue up 12% year on year (fixture text)", period: null, metric: null, hasInsights: true },
    { id: "f2", ticker: "FIXBRK", code: "FIXBRK", name: "Fixture Breakout Ltd", date: "2026-09-25T10:05:00+05:30", exchange: "NSE", category: "corporate_action", impact: "low",
      sentiment: null, docLabel: "Board Meeting Intimation", url: "https://www.nseindia.com/fixture/f2.pdf", one: null, period: null, metric: null, hasInsights: false },
  ],
};

// GET /api/watchlists (backend/routes/watchlists.py)
const CHART_LISTS = {
  lists: [{ watchlist_id: "w1", name: "Breakouts", symbol_count: 3, is_starter: false, seeded_from: null, created_at: null, updated_at: null }],
  limits: { max_lists: 10, max_symbols: 50 },
  starter_pending: false,
};

// GET /api/portfolio/holdings-enriched (backend/routes/portfolio.py) — a portfolio that holds FIXBRK and another Capital Goods stock.
const holding = (id: string, name: string, sym: string | null, sector: string, value: number, type = "equity") => ({
  holding_id: id, name, asset_type: type, quantity: 10, current_price: value / 10, value_rs: value, weight_pct: (value / 1_000_000) * 100, nse_symbol: sym, sector,
});
const HOLDINGS_IDEA = {
  holdings: [
    holding("h1", "Fixture Breakout Ltd", "FIXBRK", "Capital Goods", 50_000),
    holding("h2", "Fixture Capital Ltd", "FIXCAP", "Capital Goods", 100_000),
    holding("h3", "Other Bank Ltd", "OTHBNK", "Banking", 250_000),
    holding("h4", "Some Flexi Cap Fund", null, "Flexi Cap", 600_000, "mutual_fund"),
  ],
  totals: { count: 4, value_rs: 1_000_000 },
};
const HOLDINGS_EMPTY = { holdings: [], totals: { count: 0, value_rs: 0 } };

const r2m = (v: number) => Math.round(v * 100) / 100;
const STOP_CAVEAT = "A stop price does not guarantee the exit price: a gap or thin trading can fill the exit beyond the stop, so the loss can be larger than shown.";

/**
 * GET /api/positional/scenario (backend/routes/positional.py :: _trade_scenario), restated: what the route answers for
 * the query the screen sent. backend/tests/test_positional_scenario.py pins the route itself to the same worked example.
 */
function scenarioAnswer(q: URLSearchParams) {
  const n = (k: string) => (q.has(k) ? Number(q.get(k)) : null);
  const entry = n("entry")!;
  const stop = n("stop")!;
  const target = n("target");
  const capital = n("capital");
  const riskPct = n("risk_pct");
  const maxAlloc = n("max_alloc_pct") ?? 25;
  const slip = n("slippage_pct") ?? 0.05;
  const brk = n("brokerage_per_side") ?? 20;
  const maxQty = n("max_qty");
  const lot = n("lot_size") ?? 1;
  const pv = n("portfolio_value");
  const ex = n("existing_value");
  const sv = n("sector_value");
  const base = {
    side: "long", cost_model: { slippage_pct_per_side: slip, brokerage_inr_per_side: brk, default: false, source: "services/strategy_engine/backtest.py" },
    caveats: [STOP_CAVEAT, "Costs are estimates.", "Illustrative only: nothing is sent to a broker and no order is placed."], method: "PRD §8.5", sent_to_broker: false,
  };
  const money = (v: number) => `₹${new Intl.NumberFormat("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(v)}`;
  const problems: Array<{ field: string; code: string; message: string }> = [];
  if (!(stop < entry)) problems.push({ field: "stop", code: "stop_not_below_entry", message: `For a long position the stop (${money(stop)}) must be below the entry (${money(entry)}).` });
  if (target != null && !(target > entry)) problems.push({ field: "target", code: "target_not_above_entry", message: `For a long position the target (${money(target)}) must be above the entry (${money(entry)}).` });
  if (problems.length) return { ...base, valid: false, problems, warnings: [], per_share: null, sizing: null, costs: null, outcomes: null, portfolio: null };
  const risk = entry - stop;
  const reward = target != null ? target - entry : null;
  const budget = (capital! * riskPct!) / 100;
  const qRisk = Math.floor(budget / risk + 1e-9);
  const qAlloc = Math.floor((capital! * maxAlloc) / 100 / entry + 1e-9);
  const lims: Array<[string, number | null]> = [["risk_budget", qRisk], ["max_allocation", qAlloc], ["max_qty", maxQty]];
  let [binding, qty] = lims.filter((x): x is [string, number] => x[1] != null).reduce((a, b) => (b[1] < a[1] ? b : a));
  if (lot > 1) {
    const lots = Math.floor(qty / lot) * lot;
    if (lots !== qty) [binding, qty] = ["lot_size", lots];
  }
  const gross = qty * entry;
  const s = slip / 100;
  const entryCost = qty * entry * s + brk;
  const exitStop = qty * stop * s + brk;
  const exitTarget = target != null ? qty * target * s + brk : null;
  const loss = qty * risk;
  const profit = reward != null ? qty * reward : null;
  const outcomes = qty > 0 ? {
    loss_at_stop: r2m(loss), loss_at_stop_net: r2m(loss + entryCost + exitStop),
    profit_at_target: profit != null ? r2m(profit) : null, profit_at_target_net: profit != null && exitTarget != null ? r2m(profit - entryCost - exitTarget) : null,
  } : null;
  const after = pv ? pv + gross : null;
  return {
    ...base, valid: true, problems: [], warnings: qty === 0 ? [{ field: "risk", code: "no_whole_share", message: "The risk budget is smaller than one share's risk, so no whole share fits." }] : [],
    per_share: { risk: r2m(risk), reward: reward != null ? r2m(reward) : null, reward_to_risk: reward != null ? reward / risk : null },
    sizing: { risk_budget: r2m(budget), qty_by_risk: qRisk, qty_by_allocation: qAlloc, qty_by_max: maxQty, lot_size: lot, quantity: qty, binding, gross_exposure: r2m(gross), allocation_pct: (gross / capital!) * 100, max_alloc_pct: maxAlloc },
    costs: qty > 0 ? { entry: r2m(entryCost), exit_at_stop: r2m(exitStop), exit_at_target: exitTarget != null ? r2m(exitTarget) : null, round_trip_at_stop: r2m(entryCost + exitStop), round_trip_at_target: exitTarget != null ? r2m(entryCost + exitTarget) : null } : null,
    outcomes,
    portfolio: pv && after ? {
      portfolio_value: pv,
      stock_weight_before_pct: ((ex ?? 0) / pv) * 100, stock_weight_after_pct: (((ex ?? 0) + gross) / after) * 100,
      stock_weight_change_pct: (((ex ?? 0) + gross) / after) * 100 - ((ex ?? 0) / pv) * 100,
      sector_weight_before_pct: sv != null ? (sv / pv) * 100 : null, sector_weight_after_pct: sv != null ? ((sv + gross) / after) * 100 : null,
      impact_at_stop_pct: outcomes ? (-outcomes.loss_at_stop_net / pv) * 100 : null,
      impact_at_target_pct: outcomes?.profit_at_target_net != null ? (outcomes.profit_at_target_net / pv) * 100 : null,
      assumption: "The buy is new money added to the portfolio; weights are of the portfolio after the buy.",
    } : null,
  };
}
type ScenarioAnswer = ReturnType<typeof scenarioAnswer>;

interface ChartOver extends Over {
  indStatus?: number;
  patStatus?: number;
  patDetail?: string;
  cal?: unknown;
  holdings?: unknown;
  filings?: unknown;
  company?: unknown;
}

/** deskMocks plus every read the Chart tab, the opportunity detail and the risk desk make. Returns the scenario queries sent. */
async function chartMocks(page: Page, over: ChartOver = {}): Promise<{ scenario: URLSearchParams[] }> {
  await deskMocks(page, over);
  const scenario: URLSearchParams[] = [];
  const indStatus = over.indStatus ?? over.barsStatus;
  const patStatus = over.patStatus ?? over.barsStatus;
  await page.route("**/api/research/chart/live/*/indicators", (route) => {
    const sym = new URL(route.request().url()).pathname.split("/").slice(-2)[0];
    if (indStatus) return route.fulfill({ status: indStatus, contentType: "application/json", body: JSON.stringify({ detail: "fixture failure" }) });
    // MOCK — not real data: the server's rule-based levels for one symbol only; every other symbol has none.
    const body: Record<string, unknown> = { ...liveIndicators(sym) };
    if (sym === "HYPOSYM") body.hypothetical_levels = HYPO;
    return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
  });
  await page.route("**/api/research/chart/live/*/patterns", (route) => {
    if (patStatus) return route.fulfill({ status: patStatus, contentType: "application/json", body: JSON.stringify({ detail: over.patDetail ?? "fixture failure" }) });
    return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(LIVE_PAT) });
  });
  await json(page, "**/api/positional/backtest/calibration*", over.cal ?? CAL);
  await json(page, "**/api/copilot/widgets/company_financials", over.company ?? COMPANY);
  await json(page, "**/api/filings/feed*", over.filings ?? FILINGS);
  await page.route("**/api/watchlists", (route) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(CHART_LISTS) }));
  if (over.holdings) await json(page, "**/api/portfolio/holdings-enriched*", over.holdings);
  await page.route("**/api/positional/scenario*", (route) => {
    const q = new URL(route.request().url()).searchParams;
    scenario.push(q);
    return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(scenarioAnswer(q)) });
  });
  return { scenario };
}

/** The query of the last scenario request, as a plain object. */
const lastQuery = (calls: URLSearchParams[]) => (calls.length ? Object.fromEntries(calls[calls.length - 1].entries()) : {});

/** Writes (anything but GET) to /api/* — except the company-financials widget, a read the route takes as POST. */
function recordDeskWrites(page: Page): string[] {
  const writes: string[] = [];
  page.on("request", (req) => {
    const path = new URL(req.url()).pathname;
    if (req.method() !== "GET" && /\/api\//.test(path) && !path.startsWith("/api/copilot/widgets/")) writes.push(`${req.method()} ${req.url()}`);
  });
  return writes;
}

const FIXTURE_TOTAL = 10_306_772.4; // e2e/fixtures/holdings-enriched.json totals.value_rs (mockApi "populated")
const fmtInt = (v: number) => new Intl.NumberFormat("en-IN").format(v);
const pctD = (v: number, d = 1) => `${v < 0 ? "−" : ""}${Math.abs(v).toFixed(d)}%`;

test.describe("Smart trading desk · Chart analysis and risk desk", () => {
  test("TC-18 1M / 3M / 6M draw 22 / 63 / 126 daily candles; the readout moves with the arrow keys; overlays toggle", async ({ page }) => {
    await chartMocks(page);
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

    const last = BARS[BARS.length - 1];
    const prev = BARS[BARS.length - 2];
    const readout = page.getByTestId("desk-chart-readout");
    await expect(readout).toContainText(`C ${inr2(last[4])}`);
    await page.getByTestId("desk-chart-svg").focus();
    await page.keyboard.press("ArrowLeft");
    await expect(readout).toContainText(`O ${inr2(prev[1])} · H ${inr2(prev[2])} · L ${inr2(prev[3])} · C ${inr2(prev[4])}`);
    await expect(page.getByTestId("desk-chart-svg")).toHaveAttribute("aria-label", /126 daily candles/);
    await expect(page.getByTestId("desk-last-tag")).toHaveAttribute("data-value", String(last[4]));

    // The lines are the server's series (EMA 20 / 50 / 200, VWAP 20D); the EMA chip hides all three.
    await expect(page.getByTestId("desk-line-ema20")).toHaveCount(1);
    await expect(page.getByTestId("desk-line-ema200")).toHaveCount(1);
    await page.getByTestId("desk-chart-ov-ema").click();
    await expect(page.getByTestId("desk-chart-ov-ema")).toHaveAttribute("aria-pressed", "false");
    await expect(page.getByTestId("desk-line-ema20")).toHaveCount(0);
    await expect(page.getByTestId("desk-line-ema200")).toHaveCount(0);
    await expect(page.getByTestId("desk-chart-legend")).not.toContainText("EMA 20");
    await expect(page.getByTestId("desk-line-vwap")).toHaveCount(1);
  });

  test("TC-19 indicator tiles show the server's values (the stock_features_daily engine's convention), five by default", async ({ page }) => {
    await chartMocks(page);
    await page.goto(`${DESK}?tab=chart&sym=FIXBRK`);
    const v = LIVE.values;
    const side = (x: number) => (v.close > x ? "Price above" : v.close < x ? "Price below" : "Price at");
    await expect(page.getByTestId("desk-ind-ema20")).toHaveText(inr2(v.ema20));
    await expect(page.getByTestId("desk-ind-ema20-sub")).toHaveText(side(v.ema20));
    await expect(page.getByTestId("desk-ind-rsi")).toHaveText(v.rsi14.toFixed(1));
    await expect(page.getByTestId("desk-ind-rsi-sub")).toHaveText(v.rsi14 >= 70 ? "Overbought" : v.rsi14 >= 55 ? "Healthy" : "Neutral");
    await expect(page.getByTestId("desk-ind-atr")).toHaveText(inr2(v.atr14));
    await expect(page.getByTestId("desk-ind-atr-sub")).toHaveText(`${v.atr_pct.toFixed(2)}% of price`);
    await expect(page.getByTestId("desk-ind-vwap")).toHaveText(inr2(v.vwap20));
    await expect(page.getByTestId("desk-ind-vwap-sub")).toHaveText(side(v.vwap20));
    await expect(page.getByTestId("desk-ind-rvol")).toHaveText(`${v.rvol20.toFixed(2)}×`);
    expect(v.rvol20).toBeGreaterThanOrEqual(1.5); // the fixture's last session is a volume spike
    await expect(page.getByTestId("desk-ind-rvol-sub")).toHaveText("Volume expansion");
    await expect(page.getByTestId("desk-indicators").locator('[data-testid^="desk-ind-tile-"]')).toHaveCount(5);
    await expect(page.getByTestId("desk-chart-source")).toContainText("not the intraday VWAP");
    await expect(page.getByTestId("desk-chart-source")).toContainText("lines and indicators from the server");
    // The why rows read the same server figures.
    await expect(page.getByTestId("desk-why-trend")).toContainText(`the 20-day EMA ${inr2(v.ema20)}`);
    await expect(page.getByTestId("desk-why-trend")).toContainText(`EMA 50 ${inr2(v.ema50)}`);
    // Head row: last close and the day's change in rupees and percent, from the bars.
    const closes = BARS.map((b) => b[4]);
    const close = closes[closes.length - 1];
    const prev = closes[closes.length - 2];
    const ch = close - prev;
    await expect(page.getByTestId("desk-chart-close")).toHaveText(inr2(close));
    await expect(page.getByTestId("desk-chart-change")).toHaveText(`${ch > 0 ? "+" : ch < 0 ? "−" : ""}${enIN(Math.abs(ch))} (${signedPct((ch / prev) * 100, 2)})`);
  });

  test("PRD §7.3 the indicator drawer lists every lookback and adds tiles on demand; nothing extra by default", async ({ page }) => {
    await chartMocks(page);
    await page.goto(`${DESK}?tab=chart&sym=FIXBRK`);
    const toggle = page.getByTestId("desk-ind-drawer-toggle");
    await expect(toggle).toHaveAttribute("aria-expanded", "false");
    await expect(page.getByTestId("desk-ind-defs")).toHaveCount(0);
    await toggle.click();
    await expect(toggle).toHaveAttribute("aria-expanded", "true");
    for (const d of LIVE.definitions) {
      await expect(page.getByTestId(`desk-ind-def-${d.key}`)).toContainText(`${d.label} · lookback ${d.lookback}`);
    }
    await expect(page.getByTestId("desk-ind-def-ema20")).toContainText("seeded with the first close");
    const v = LIVE.values;
    await page.getByTestId("desk-ind-toggle-ema200").click();
    await expect(page.getByTestId("desk-ind-toggle-ema200")).toHaveAttribute("aria-pressed", "true");
    await expect(page.getByTestId("desk-ind-ema200")).toHaveText(inr2(v.ema200!));
    await page.getByTestId("desk-ind-toggle-macd").click();
    await expect(page.getByTestId("desk-ind-macd")).toHaveText(enIN(v.macd_hist));
    await page.getByTestId("desk-ind-toggle-rs63").click();
    const ex = v.rs63.excess_pct;
    await expect(page.getByTestId("desk-ind-rs63")).toHaveText(`${ex > 0 ? "+" : ex < 0 ? "−" : ""}${enIN(Math.abs(ex), 1)} pts`);
    await page.getByTestId("desk-ind-toggle-roc20").click();
    await expect(page.getByTestId("desk-ind-roc20")).toHaveText(signedPct(v.roc20, 1));
    await page.getByTestId("desk-ind-toggle-avg_volume20").click();
    await expect(page.getByTestId("desk-ind-avg_volume20")).toHaveText(fmtInt(Math.round(v.avg_volume20)));
    await page.getByTestId("desk-ind-toggle-sr20").click();
    await expect(page.getByTestId("desk-ind-sr20")).toHaveText(`${inr2(v.support20)} – ${inr2(v.resistance20)}`);
    await expect(page.getByTestId("desk-indicators").locator('[data-testid^="desk-ind-tile-"]')).toHaveCount(11);
    await page.getByTestId("desk-ind-toggle-macd").click();
    await expect(page.getByTestId("desk-ind-macd")).toHaveCount(0);
  });

  test("PRD §7.2 the toolbar: daily interval only (intraday disabled with the reason), the full chart with the levels, and the watchlist", async ({ page }) => {
    await chartMocks(page);
    const posted: unknown[] = [];
    await page.route("**/api/watchlists/w1/symbols", (route) => {
      posted.push(route.request().postDataJSON());
      return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ added: true, reason: null, stock: { symbol: "FIXBRK", company_name: "Fixture Breakout Ltd" }, watchlist: { ...CHART_LISTS.lists[0], symbol_count: 4 } }) });
    });
    await page.goto(`${DESK}?tab=chart&sym=FIXBRK`);
    await expect(page.getByTestId("desk-chart-iv-1d")).toHaveAttribute("aria-pressed", "true");
    for (const id of ["60m", "30m", "15m", "5m"]) {
      await expect(page.getByTestId(`desk-chart-iv-${id}`)).toBeDisabled();
      await expect(page.getByTestId(`desk-chart-iv-${id}`)).toHaveAttribute("title", /No intraday bars on record/);
    }
    // The full chart: Research → Charts with the pick's levels (ChartsScreen reads entry, stop and t1).
    const p = PICKS.picks[0];
    const href = await page.getByTestId("desk-chart-full").getAttribute("href");
    const u = new URL(href!, "http://x");
    expect(u.pathname).toBe("/v5/research");
    expect(Object.fromEntries(u.searchParams.entries())).toEqual({ screen: "charts", symbol: "FIXBRK", entry: String(p.entry_price), stop: String(p.stoploss), t1: String(p.target_price) });
    // Watchlist: the existing lists API (the user's own list; not an order).
    await page.getByTestId("watchlist-add-to-list").click();
    await expect(page.getByTestId("watchlist-add-to-list-pick")).toHaveValue("w1");
    await page.getByTestId("watchlist-add-to-list-save").click();
    await expect(page.getByTestId("watchlist-add-to-list-done")).toContainText("Added to Breakouts");
    expect(posted).toEqual([{ symbol: "FIXBRK" }]);
    // A stock without levels opens with the symbol alone.
    await page.goto(`${DESK}?tab=chart&sym=OTHERSYM`);
    await expect(page.getByTestId("desk-chart-symbol")).toHaveText("OTHERSYM");
    const href2 = await page.getByTestId("desk-chart-full").getAttribute("href");
    expect(Object.fromEntries(new URL(href2!, "http://x").searchParams.entries())).toEqual({ screen: "charts", symbol: "OTHERSYM" });
  });

  test("PRD §7.2 event markers: one diamond per session with an exchange filing, in the shown range; the readout names it", async ({ page }) => {
    await chartMocks(page);
    await page.goto(`${DESK}?tab=chart&sym=FIXBRK`);
    const markers = page.getByTestId("desk-event-marker");
    const days = FILINGS.rows.map((r) => r.date.slice(0, 10)).sort();
    await expect(markers).toHaveCount(days.length);
    expect((await markers.evaluateAll((els) => els.map((e) => e.getAttribute("data-day")))).sort()).toEqual(days);
    await expect(page.getByTestId("desk-chart-legend-events")).toHaveText("Filing");
    await expect(page.getByTestId("desk-chart-source")).toContainText(`◆ ${days.length} sessions with an exchange filing in the last 30 days`);
    // Step the readout back to the last filing's session.
    const idx = BARS.findIndex((b) => b[0] === days[days.length - 1]);
    await page.getByTestId("desk-chart-svg").focus();
    for (let i = BARS.length - 1; i > idx; i--) await page.keyboard.press("ArrowLeft");
    await expect(page.getByTestId("desk-chart-readout")).toContainText("· 1 filing");
    // 1M range: only the filings inside the 22 sessions shown keep a marker.
    await page.getByTestId("desk-chart-tf-1M").click();
    const firstShown = BARS[BARS.length - 22][0];
    await expect(markers).toHaveCount(days.filter((d) => d >= firstShown).length);
  });

  test("TC-20 levels and reward / risk come from the pick; the gate counts only real passes; history tiles quote the record", async ({ page }) => {
    await chartMocks(page);
    await page.goto(`${DESK}?tab=chart`);
    const top = [...expectedRows()].sort((a, b) => b.score - a.score)[0];
    expect(top.symbol).toBe("FIXBRK");
    await expect(page.getByTestId("desk-chart-symbol")).toHaveText(top.symbol);

    const p = PICKS.picks[0];
    await expect(page.getByTestId("desk-level-target")).toContainText(`Target ${inr2(p.target_price)}`);
    await expect(page.getByTestId("desk-level-entry")).toContainText(`Entry ${inr2(p.entry_price)}`);
    await expect(page.getByTestId("desk-level-stop")).toContainText(`Stop ${inr2(p.stoploss)}`);
    await expect(page.getByTestId("desk-risk-entry")).toHaveText(`Entry ${inr2(p.entry_price)}`);
    await expect(page.getByTestId("desk-risk-stop")).toHaveText(`Stop ${inr2(p.stoploss)}`);
    await expect(page.getByTestId("desk-risk-target")).toHaveText(`Target ${inr2(p.target_price)}`);
    await expect(page.getByTestId("desk-risk-rr")).toHaveText(`${p.risk_reward.toFixed(1)} : 1`);
    await expect(page.getByTestId("desk-hist-rr")).toHaveText(`${p.risk_reward.toFixed(1)} : 1`);
    await expect(page.getByTestId("desk-hist-conf")).toHaveText("High");
    // History tiles: the record's breakout row in FIXBRK's score bucket, at 10 sessions — a touch outcome.
    const row = CAL.buckets.find((r) => r.matched && r.metric === "broke_high")!;
    await expect(page.getByTestId("desk-hist-hit")).toHaveText(`${Math.round(row.probability * 100)}% · n ${row.sample_count}`);
    await expect(page.getByTestId("desk-hist-hit-note")).toContainText("intraday touch");
    await expect(page.getByTestId("desk-hist-move")).toHaveText(signedPct(row.avg_fwd_return, 1));
    await expect(page.getByTestId("desk-hist-move-note")).toContainText("not an average return");
    await expect(page.getByTestId("desk-risk-winrate")).toHaveText("—");
    await expect(page.getByTestId("desk-risk-scenario")).toHaveText("Breakout confirmed");
    await expect(page.getByTestId("desk-risk-status")).toHaveAttribute("data-status", "confirmed");
    await expect(page.getByTestId("desk-risk-ltp")).toContainText(`Close ${inr2(BARS[BARS.length - 1][4])}`);

    await expect(page.getByTestId("desk-axis-label")).toHaveCount(0);
    await page.getByTestId("desk-chart-ov-levels").click();
    await expect(page.getByTestId("desk-level-target")).toHaveCount(0);
    expect(await page.getByTestId("desk-axis-label").count()).toBeGreaterThan(1);

    const o = ODDS_ROWS.find((r) => r.symbol === "FIXBRK")!;
    await expect(page.getByTestId("desk-risk-p5")).toHaveText(pct1(o.p));
    await expect(page.getByTestId("desk-risk-gate-count")).toHaveText("5 of 5 passed");
    await expect(page.getByTestId("desk-risk-check-liquidity-value")).toHaveText(`₹${tradedOf("FIXBRK")!.toFixed(1)} Cr a day`);
    await expect(page.getByTestId("desk-risk-record")).toContainText(`top-10 hit rate ${pct1(RECORD.top10_hit_rate)} over ${RECORD.sessions} sessions`);

    const w = WATCHLIST.buckets.breakout_confirmed[0];
    const from = (lvl: number) => signedPct(((lvl - w.close_price) / w.close_price) * 100);
    await expect(page.getByTestId("desk-check-resistance")).toHaveText(`Next resistance${inr2(w.resistance_level)} · ${from(w.resistance_level)}`);
    await expect(page.getByTestId("desk-setup-check").locator('[data-testid^="desk-check-"]')).toHaveCount(7);
    await expect(page.getByTestId("desk-why-catalyst")).toContainText(`${o.events_on_record} events on record; latest: Fixture filing 3 (NSE filing, 13 Oct 2026)`);
    await expect(page.getByTestId("desk-why-risk")).toContainText(`Stop ${inr2(p.stoploss)} is ${(((p.entry_price - p.stoploss) / p.entry_price) * 100).toFixed(1)}% below the entry`);
  });

  test("a stock with no events and a thin traded value fails two gate checks; its estimate is not shown as high-confidence", async ({ page }) => {
    await chartMocks(page);
    await page.goto(`${DESK}?tab=chart&sym=FIXPRE`);
    const o = ODDS_ROWS.find((r) => r.symbol === "FIXPRE")!;
    const passed = [true, true, RECORD.top10_hit_rate > RECORD.base_rate, o.events_on_record > 0, (tradedOf("FIXPRE") ?? 0) >= 10].filter(Boolean).length;
    expect(passed).toBe(3);
    await expect(page.getByTestId("desk-risk-gate-count")).toHaveText(`${passed} of 5 passed`);
    await expect(page.getByTestId("desk-risk-check-events")).toHaveAttribute("data-ok", "false");
    await expect(page.getByTestId("desk-risk-check-liquidity")).toHaveAttribute("data-ok", "false");
    await expect(page.getByTestId("desk-risk-p5-note")).toHaveText(`P(+5% next session). Not shown as high-confidence: ${passed} of 5 gate checks passed.`);
  });

  test("odds 403: the gate's model checks show “—” and are not counted; only the liquidity check can pass", async ({ page }) => {
    await chartMocks(page, { oddsStatus: 403 });
    await page.goto(`${DESK}?tab=chart&sym=FIXBRK`);
    for (const k of ["published", "record", "edge", "events"]) {
      await expect(page.getByTestId(`desk-risk-check-${k}`)).toHaveAttribute("data-ok", "na");
      await expect(page.getByTestId(`desk-risk-check-${k}-value`)).toHaveText("—");
    }
    await expect(page.getByTestId("desk-risk-gate-count")).toHaveText("1 of 5 passed");
    await expect(page.getByTestId("desk-risk-p5-note")).toHaveText("Move probabilities are not enabled for this account.");
  });

  test("a symbol that is not on the scanner shows the chart and indicators, no levels, and asks for levels to size", async ({ page }) => {
    await chartMocks(page);
    await page.goto(`${DESK}?tab=chart&sym=OTHERSYM`);
    await expect(page.getByTestId("desk-chart-symbol")).toHaveText("OTHERSYM");
    await expect(page.getByTestId("desk-candle")).toHaveCount(63);
    await expect(page.getByTestId("desk-ind-ema20")).toHaveText(inr2(LIVE.values.ema20));
    await expect(page.getByTestId("desk-not-on-scanner")).toContainText("Not on today’s scanner — no levels");
    await expect(page.getByTestId("desk-risk-nolevels")).toBeVisible();
    await expect(page.getByTestId("desk-risk-nosize")).toBeVisible();
    await expect(page.getByTestId("desk-chart-ov-levels")).toBeDisabled();
    await expect(page.getByTestId("desk-risk-rr")).toHaveText("—");
    // No scanner levels: the calculator is open for the user's own levels, and the card says why none are suggested.
    await expect(page.getByTestId("desk-risk-nolevels")).toContainText("nothing is made up");
    await expect(page.getByTestId("desk-scn-editor")).toHaveCount(1);
    await expect(page.getByTestId("desk-scn-problems")).toContainText("Enter an entry price.");
    expect(await page.getByTestId("desk-axis-label").count()).toBeGreaterThan(1);
  });

  test("not on the scanner and the model has not published: no gate check applies, the count is “—”, not “0 of 5 passed”", async ({ page }) => {
    await chartMocks(page, { oddsPending: true });
    await page.goto(`${DESK}?tab=chart&sym=OTHERSYM`);
    await expect(page.getByTestId("desk-risk-p5-note")).toHaveText("The model has not published for 21 Oct 2026 yet.");
    for (const k of ["published", "record", "edge", "events", "liquidity"]) await expect(page.getByTestId(`desk-risk-check-${k}`)).toHaveAttribute("data-ok", "na");
    await expect(page.getByTestId("desk-risk-check-published-value")).toHaveText("Not published yet");
    await expect(page.getByTestId("desk-risk-gate-count")).toHaveText("—");
    await expect(page.getByTestId("desk-risk-gate-none")).toContainText("not judged, not failed");
    // the calculator is open and works on the user's own levels
    await expect(page.getByTestId("desk-scn-editor")).toHaveCount(1);
  });

  test("not on the scanner: the rule's levels fill the section, the calculator and the full-chart link, labelled; the scanner's win when present", async ({ page }) => {
    await chartMocks(page);
    await page.goto(`${DESK}?tab=chart&sym=HYPOSYM`);
    await expect(page.getByTestId("desk-risk-rule")).toContainText("Rule-based hypothetical levels, not a scanner pick and not a recommendation");
    await expect(page.getByTestId("desk-risk-rule")).toContainText("ATR_2X_STOP v1");
    await expect(page.getByTestId("desk-risk-rr")).toHaveText("2.0 : 1");
    await expect(page.getByTestId("desk-scn-entry")).toHaveValue("500");
    await expect(page.getByTestId("desk-scn-stop")).toHaveValue("480");
    await expect(page.getByTestId("desk-scn-target")).toHaveValue("540");
    await page.getByTestId("desk-detail-levels-toggle").click();
    await expect(page.getByTestId("desk-lvl-source")).toContainText("ATR_2X_STOP v1");
    await expect(page.getByTestId("desk-lvl-entry")).toContainText(inr2(500));
    await expect(page.getByTestId("desk-lvl-stop")).toContainText(inr2(480));
    await expect(page.getByTestId("desk-lvl-target")).toContainText(inr2(540));
    await expect(page.getByTestId("desk-lvl-full")).toHaveAttribute("href", /entry=500.*stop=480.*t1=540/);
    // a stock the scanner has: its own levels, and the source says so
    await page.goto(`${DESK}?tab=chart&sym=FIXBRK`);
    await page.getByTestId("desk-detail-levels-toggle").click();
    await expect(page.getByTestId("desk-lvl-source")).toContainText("AI scanner pick");
  });

  test("TC-21 chart-live 403 → charting locked for the account; indicators and patterns are locked too", async ({ page }) => {
    await chartMocks(page, { barsStatus: 403 });
    await page.goto(`${DESK}?tab=chart&sym=FIXBRK`);
    await expect(page.getByTestId("desk-chart-locked")).toContainText("Charting is not enabled for this account");
    await expect(page.getByTestId("desk-candle")).toHaveCount(0);
    await expect(page.getByTestId("desk-indicators")).toHaveCount(0);
    await expect(page.getByTestId("desk-risk-rr")).toHaveText(`${PICKS.picks[0].risk_reward.toFixed(1)} : 1`);
    await expect(page.getByTestId("desk-risk-chk-gap")).toHaveText(/Needs the stock’s daily bars/);
    await page.getByTestId("desk-detail-technical-toggle").click();
    await expect(page.getByTestId("desk-patterns-none")).toContainText("needs the charting feature");
  });

  test("TC-21 chart-live 404 → no prices on record", async ({ page }) => {
    await chartMocks(page, { barsStatus: 404 });
    await page.goto(`${DESK}?tab=chart&sym=FIXBRK`);
    await expect(page.getByTestId("desk-chart-noprices")).toContainText("No daily prices on record for FIXBRK");
    await expect(page.getByTestId("desk-candle")).toHaveCount(0);
  });

  test("TC-22 PRD §8.5 calculator round trip: the screen sends its inputs to the server rule and shows the answer", async ({ page }) => {
    const { scenario } = await chartMocks(page);
    await page.goto(`${DESK}?tab=chart&sym=FIXBRK`);
    const p = PICKS.picks[0];
    // The first answer once the portfolio is known: ₹5L at 1%, 25% cap, strategy_engine costs, the pick's levels.
    await expect.poll(() => lastQuery(scenario)).toEqual({
      entry: String(p.entry_price), stop: String(p.stoploss), target: String(p.target_price), capital: "500000", risk_pct: "1", max_alloc_pct: "25",
      slippage_pct: "0.05", brokerage_per_side: "20", lot_size: "1", portfolio_value: String(FIXTURE_TOTAL), existing_value: "0", sector_value: "0",
    });
    const tiles = async (a: ScenarioAnswer) => {
      await expect(page.getByTestId("desk-risk-qty")).toHaveText(fmtInt(a.sizing!.quantity));
      await expect(page.getByTestId("desk-risk-used")).toHaveText(inr0(a.sizing!.gross_exposure));
      await expect(page.getByTestId("desk-risk-used-pct")).toHaveText(`${a.sizing!.allocation_pct.toFixed(1)}%`);
      await expect(page.getByTestId("desk-risk-maxloss")).toHaveText(inr0(a.outcomes!.loss_at_stop_net));
      await expect(page.getByTestId("desk-risk-attarget")).toHaveText(`+${inr0(a.outcomes!.profit_at_target_net!)}`);
    };
    const a0 = scenarioAnswer(scenario[scenario.length - 1]);
    // The worked example of backend/tests/test_positional_scenario.py: 200 shares, ₹5,138.50 lost at the stop after costs.
    expect(a0.sizing!.quantity).toBe(200);
    expect(a0.outcomes!.loss_at_stop_net).toBe(5_138.5);
    expect(a0.outcomes!.profit_at_target_net).toBe(9_854);
    await tiles(a0);
    await expect(page.getByTestId("desk-risk-maxloss-tile-note")).toHaveText(`at the stop, after costs (${inr0(a0.outcomes!.loss_at_stop)} before)`);
    await expect(page.getByTestId("desk-risk-chk-size")).toContainText(`${inr0(5_000)} at risk (1% of ${inr0(500_000)}); max loss ${inr0(a0.outcomes!.loss_at_stop_net)} at the stop after costs.`);
    await expect(page.getByTestId("desk-risk-stopnote")).toHaveText(STOP_CAVEAT);

    // Presets: ₹2L at 2% → the 25% cap binds (99 shares), and the concentration check names the portfolio weight.
    await page.getByTestId("desk-risk-capital-2l").click();
    await page.getByTestId("desk-risk-pct-2").click();
    await expect.poll(() => lastQuery(scenario).capital + "/" + lastQuery(scenario).risk_pct).toBe("200000/2");
    const a1 = scenarioAnswer(scenario[scenario.length - 1]);
    expect(a1.sizing!.binding).toBe("max_allocation");
    await tiles(a1);
    await expect(page.getByTestId("desk-risk-qty-tile-note")).toHaveText("shares · limited by the maximum allocation");
    await expect(page.getByTestId("desk-risk-chk-concentration")).toContainText(`${a1.portfolio!.stock_weight_after_pct.toFixed(1)}% of your portfolio after the buy (0.0% now), within the 25% limit.`);

    // Every input is editable: levels, capital, risk, cap, costs, max shares and lot size.
    if ((await page.getByTestId("desk-risk-editor-toggle").getAttribute("aria-expanded")) !== "true") await page.getByTestId("desk-risk-editor-toggle").click();
    await page.getByTestId("desk-scn-entry").fill("510");
    await page.getByTestId("desk-scn-stop").fill("490");
    await page.getByTestId("desk-scn-target").fill("560");
    await page.getByTestId("desk-scn-capital").fill("1000000");
    await page.getByTestId("desk-scn-riskPct").fill("0.5");
    await page.getByTestId("desk-scn-maxAllocPct").fill("10");
    await page.getByTestId("desk-scn-slippagePct").fill("0");
    await page.getByTestId("desk-scn-brokerage").fill("0");
    await expect.poll(() => lastQuery(scenario)).toMatchObject({ entry: "510", stop: "490", target: "560", capital: "1000000", risk_pct: "0.5", max_alloc_pct: "10", slippage_pct: "0", brokerage_per_side: "0" });
    const a2 = scenarioAnswer(scenario[scenario.length - 1]);
    await expect(page.getByTestId("desk-scn-out-down-v")).toHaveText(inr2(20));
    await expect(page.getByTestId("desk-scn-out-up-v")).toHaveText(inr2(50));
    await expect(page.getByTestId("desk-scn-out-rr-v")).toHaveText("2.5 : 1");
    await expect(page.getByTestId("desk-scn-out-qty-v")).toHaveText(`${fmtInt(a2.sizing!.quantity)} shares`);
    // No costs: net equals gross.
    expect(a2.outcomes!.loss_at_stop_net).toBe(a2.outcomes!.loss_at_stop);
    await expect(page.getByTestId("desk-scn-out-loss-v")).toHaveText(`−${inr0(a2.outcomes!.loss_at_stop_net)} after costs`);
    await expect(page.getByTestId("desk-scn-out-costs-v")).toHaveText(`${inr0(0)} at the stop · ${inr0(0)} at the target`);
    await page.getByTestId("desk-scn-maxQty").fill("50");
    await page.getByTestId("desk-scn-lotSize").fill("30");
    await expect.poll(() => lastQuery(scenario)).toMatchObject({ max_qty: "50", lot_size: "30" });
    await expect(page.getByTestId("desk-scn-out-qty-v")).toHaveText("30 shares");
    await expect(page.getByTestId("desk-scn-out-qty")).toContainText("Limited by the lot size");

    // Wrong direction: the server's problem beside the inputs, no sizing, nothing to add.
    await page.getByTestId("desk-scn-stop").fill("520");
    await expect(page.getByTestId("desk-scn-problems")).toContainText("For a long position the stop (₹520.00) must be below the entry (₹510.00).");
    await expect(page.getByTestId("desk-scn-stop")).toHaveAttribute("aria-invalid", "true");
    await expect(page.getByTestId("desk-risk-nosize")).toBeVisible();
    await expect(page.getByTestId("desk-risk-paper")).toBeDisabled();
    await expect(page.getByTestId("desk-risk-paper-note")).toHaveText("Fix the scenario’s inputs first.");
    // Zero risk per share is the same problem, never a division by zero.
    await page.getByTestId("desk-scn-stop").fill("510");
    await expect(page.getByTestId("desk-scn-problems")).toContainText("must be below the entry");
    // A mistyped number is caught before anything is sent.
    const sent = scenario.length;
    await page.getByTestId("desk-scn-capital").fill("ten lakh");
    await expect(page.getByTestId("desk-scn-problems")).toContainText("The capital must be a number above zero.");
    await page.waitForTimeout(500);
    expect(scenario.length).toBe(sent);
    // Back to the scanner's levels.
    await page.getByTestId("desk-scn-capital").fill("500000");
    await page.getByTestId("desk-scn-reset").click();
    await expect(page.getByTestId("desk-scn-entry")).toHaveValue(String(p.entry_price));
    await expect.poll(() => lastQuery(scenario).stop).toBe(String(p.stoploss));
  });

  test("PRD §8.6 your portfolio and this idea: exposure, sector, related holdings, the weight after the buy and the impact", async ({ page }) => {
    const { scenario } = await chartMocks(page, { holdings: HOLDINGS_IDEA });
    await page.goto(`${DESK}?tab=chart&sym=FIXBRK`);
    await expect.poll(() => lastQuery(scenario)).toMatchObject({ portfolio_value: "1000000", existing_value: "50000", sector_value: "150000" });
    const a = scenarioAnswer(scenario[scenario.length - 1]);
    await expect(page.getByTestId("desk-pf-existing-v")).toHaveText(inr0(50_000));
    await expect(page.getByTestId("desk-pf-existing")).toContainText("5.00% of the portfolio, all accounts");
    await expect(page.getByTestId("desk-pf-sector-v")).toHaveText("15.00%");
    await expect(page.getByTestId("desk-pf-sector")).toContainText(`${a.portfolio!.sector_weight_after_pct!.toFixed(2)}% after the buy`);
    await expect(page.getByTestId("desk-pf-related-FIXCAP")).toContainText("Fixture Capital Ltd");
    await expect(page.getByTestId("desk-pf-related")).not.toContainText("Other Bank");
    await expect(page.getByTestId("desk-pf-incremental-v")).toHaveText(`5.00% → ${a.portfolio!.stock_weight_after_pct.toFixed(2)}%`);
    await expect(page.getByTestId("desk-pf-impact-v")).toHaveText(`${pctD(a.portfolio!.impact_at_stop_pct!, 2)} at the stop · +${a.portfolio!.impact_at_target_pct!.toFixed(2)}% at the target`);
    await expect(page.getByTestId("desk-pf-limits")).toContainText("nothing is rebalanced or traded");
    await expect(page.getByTestId("desk-risk-chk-concentration")).toContainText(`${a.portfolio!.stock_weight_after_pct.toFixed(1)}% of your portfolio after the buy (5.0% now)`);
  });

  test("PRD §8.6 with no portfolio on record the block says so and sends no portfolio figures", async ({ page }) => {
    const { scenario } = await chartMocks(page, { holdings: HOLDINGS_EMPTY });
    await page.goto(`${DESK}?tab=chart&sym=FIXBRK`);
    await expect(page.getByTestId("desk-pf-empty")).toContainText("No portfolio on record");
    await expect(page.getByTestId("desk-risk-qty")).toHaveText("200");
    expect(scenario.every((q) => !q.has("portfolio_value"))).toBe(true);
  });

  test("TC-23 Add to paper trades posts the scenario's quantity at its levels; pending, then confirmed; nothing else is written", async ({ page }) => {
    const writes = recordDeskWrites(page);
    const { scenario } = await chartMocks(page);
    let release: () => void = () => {};
    const gate = new Promise<void>((r) => { release = r; });
    const posted = await mockDeskWrites(page, { gate });
    await page.goto(`${DESK}?tab=chart&sym=FIXBRK`);

    const p = PICKS.picks[0];
    const paper = page.getByTestId("desk-risk-paper");
    await expect(page.getByTestId("desk-risk-qty")).toHaveText("200");
    await expect(paper).toBeEnabled();
    await expect(page.getByTestId("desk-risk-paper-note")).toHaveText(
      `Simulated: 200 shares at ${inr2(p.entry_price)}, stop ${inr2(p.stoploss)}, target ${inr2(p.target_price)}. No order is placed; it is marked against end-of-day closes.`,
    );
    await paper.click();
    await expect(paper).toBeDisabled();
    await expect(paper).toHaveText("Adding…");
    release();
    const done = page.getByTestId("desk-risk-paper-done");
    await expect(done).toContainText(`Paper trade added: 200 FIXBRK at ${inr2(p.entry_price)}. No order is placed.`);
    expect(posted[0]).toEqual({
      method: "POST", path: "/api/desk/paper-trades",
      body: { symbol: "FIXBRK", quantity: 200, entry_price: p.entry_price, stop_price: p.stoploss, target_price: p.target_price, source: { kind: "scanner", bucket: "breakout_confirmed", signal_date: PICKS.signal_date } },
    });

    // ₹2L at 2%: the server caps it at 99 shares, and that is what is added.
    await page.getByTestId("desk-risk-capital-2l").click();
    await page.getByTestId("desk-risk-pct-2").click();
    await expect(page.getByTestId("desk-risk-qty")).toHaveText("99");
    await paper.click();
    await expect.poll(() => posted.length).toBe(2);
    expect((posted[1].body as { quantity: number }).quantity).toBe(scenarioAnswer(scenario[scenario.length - 1]).sizing!.quantity);
    const origin = new URL(page.url()).origin;
    expect(writes).toEqual([`POST ${origin}/api/desk/paper-trades`, `POST ${origin}/api/desk/paper-trades`]);
    await done.getByTestId("desk-risk-paper-done-open").click();
    await expect(page).toHaveURL(/[?&]tab=portfolio/);
  });

  test("TC-23 Alert on trigger posts the watchlist trigger; a pick without a trigger uses its entry and sends no bucket", async ({ page }) => {
    await chartMocks(page);
    const posted = await mockDeskWrites(page);
    await page.goto(`${DESK}?tab=chart&sym=FIXBRK`);
    const w = WATCHLIST.buckets.breakout_confirmed[0];
    const alertBtn = page.getByTestId("desk-risk-alert");
    await expect(page.getByTestId("desk-risk-alert-note")).toContainText(`reaches ${inr2(w.trigger_price)} (the trigger)`);
    await alertBtn.click();
    await expect(alertBtn).toHaveText("Alert set ✓");
    expect(posted).toEqual([{ method: "POST", path: "/api/desk/alerts", body: { symbol: "FIXBRK", condition: "above", level: w.trigger_price } }]);

    await page.goto(`${DESK}?tab=chart&sym=FIXPICK`);
    await expect(page.getByTestId("desk-chart-symbol")).toHaveText("FIXPICK");
    const fp = PICKS.picks[1];
    await page.getByTestId("desk-risk-alert").click();
    await expect.poll(() => posted.length).toBe(2);
    expect(posted[1].body).toEqual({ symbol: "FIXPICK", condition: "above", level: fp.entry_price });
    const qty = Math.floor(5_000 / (fp.entry_price - fp.stoploss));
    await expect(page.getByTestId("desk-risk-qty")).toHaveText(fmtInt(qty));
    await page.getByTestId("desk-risk-paper").click();
    await expect.poll(() => posted.length).toBe(3);
    expect(posted[2].body).toEqual({
      symbol: "FIXPICK", quantity: qty, entry_price: fp.entry_price, stop_price: fp.stoploss, target_price: fp.target_price, source: { kind: "scanner", signal_date: PICKS.signal_date },
    });
  });

  test("TC-23 a 409 limit and a 422 validation error show the server's words; a stock with no levels can do neither", async ({ page }) => {
    const writes = recordDeskWrites(page);
    await chartMocks(page);
    await mockDeskWrites(page, { paper: { status: 409, body: { detail: "open_trade_limit" } }, alert: { status: 422, body: { detail: "invalid_symbol" } } });
    await page.goto(`${DESK}?tab=chart&sym=FIXBRK`);
    await expect(page.getByTestId("desk-risk-qty")).toHaveText("200");
    await page.getByTestId("desk-risk-paper").click();
    await expect(page.getByTestId("desk-risk-paper-error")).toHaveText("Not added — You have the most open paper trades allowed (100). Close one first. (open_trade_limit)");
    await page.getByTestId("desk-risk-alert").click();
    await expect(page.getByTestId("desk-risk-alert-error")).toHaveText("Not set — The symbol is not a valid NSE symbol. (invalid_symbol)");
    await page.goto(`${DESK}?tab=chart&sym=OTHERSYM`);
    await expect(page.getByTestId("desk-risk-paper")).toBeDisabled();
    await expect(page.getByTestId("desk-risk-alert")).toBeDisabled();
    await expect(page.getByTestId("desk-risk-paper-note")).toHaveText("Needs a scanner setup: this stock has no entry or stop.");
    await page.getByTestId("desk-risk-paper").click({ force: true });
    await page.getByTestId("desk-risk-alert").click({ force: true });
    await expect(page.getByTestId("desk-risk-note")).toHaveText("Paper trade only. Nivesh reads broker positions and cannot place orders.");
    await page.waitForTimeout(500);
    expect(writes).toHaveLength(2);
    expect(writes.every((w) => /^POST .*\/api\/desk\/(paper-trades|alerts)$/.test(w))).toBe(true);
  });

  test("TC-23 a setup with no entry disables both actions and says why", async ({ page }) => {
    await chartMocks(page);
    await page.goto(`${DESK}?tab=chart&sym=FIXTRD`);
    await expect(page.getByTestId("desk-risk-paper")).toBeDisabled();
    await expect(page.getByTestId("desk-risk-paper-note")).toHaveText("Needs an entry with a stop below it; this setup does not have both.");
    await expect(page.getByTestId("desk-risk-alert")).toBeDisabled();
  });

  test("Ask Copilot hands the setup question to the Copilot", async ({ page }) => {
    await chartMocks(page);
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

// ── the opportunity detail (PRD §5.7) ─────────────────────────────────────

const SECTIONS = ["definition", "model", "technical", "fundamentals", "events", "liquidity", "levels", "validation", "contra", "freshness"];

test.describe("Smart trading desk · opportunity detail (PRD §5.7)", () => {
  test.use({ viewport: { width: 1360, height: 900 } });

  test("ten sections in the PRD's order, collapsed with a summary each; a section and Open all expand them", async ({ page }) => {
    await chartMocks(page);
    await page.goto(`${DESK}?tab=chart&sym=FIXBRK`);
    await expect(page.getByTestId("desk-detail-title")).toHaveText("03 · Opportunity detail");
    const ids = await page.locator('[data-testid^="desk-detail-"][data-testid$="-toggle"]').evaluateAll((els) => els.map((e) => e.getAttribute("data-testid")));
    expect(ids).toEqual(SECTIONS.map((k) => `desk-detail-${k}-toggle`));
    expect(await page.locator('[data-testid^="desk-detail-"][data-testid$="-toggle"] > span > span:first-child').allTextContents()).toEqual([
      "Prediction definition and horizon", "Model score and calibration", "Technical evidence", "Fundamental and ownership context", "Corporate events and news",
      "Liquidity and tradability", "Hypothetical entry, stop and target", "Historical validation", "Contradictory evidence", "Data freshness and missing inputs",
    ]);
    for (const k of SECTIONS) {
      await expect(page.getByTestId(`desk-detail-${k}-toggle`)).toHaveAttribute("aria-expanded", "false");
      await expect(page.getByTestId(`desk-detail-${k}-body`)).toHaveCount(0);
    }
    // Summaries from the payloads.
    const o = ODDS_ROWS.find((r) => r.symbol === "FIXBRK")!;
    await expect(page.getByTestId("desk-detail-model-summary")).toHaveText(`Score 86 (rules) · P(+5% next session) ${pct1(o.p)} · ${RECORD.window_label}`);
    await expect(page.getByTestId("desk-detail-technical-summary")).toContainText("1 confirmed, 0 awaiting");
    await expect(page.getByTestId("desk-detail-fundamentals-summary")).toHaveText("P/E 24.1 · ROE 18% · promoter 52%");
    await expect(page.getByTestId("desk-detail-events-summary")).toHaveText("2 filings in 30 days · latest 8 Oct 2026");
    await expect(page.getByTestId("desk-detail-validation-summary")).toHaveText("Hit rate 40.0% · n 100 (touch, 10 sessions)");
    await page.getByTestId("desk-detail-model-toggle").click();
    await expect(page.getByTestId("desk-detail-model-toggle")).toHaveAttribute("aria-expanded", "true");
    await expect(page.getByTestId("desk-detail-model-body")).toBeVisible();
    await page.getByTestId("desk-detail-all").click();
    for (const k of SECTIONS) await expect(page.getByTestId(`desk-detail-${k}-body`)).toBeVisible();
    await expect(page.getByTestId("desk-detail-all")).toHaveText("Close all");
    await page.getByTestId("desk-detail-all").click();
    await expect(page.getByTestId("desk-detail-model-body")).toHaveCount(0);
  });

  test("each section's values come from its route, and every figure without a source is “—” with the reason", async ({ page }) => {
    await chartMocks(page);
    await page.goto(`${DESK}?tab=chart&sym=FIXBRK`);
    await page.getByTestId("desk-detail-all").click();
    const p = PICKS.picks[0];
    // 1 · definition and horizon
    await expect(page.getByTestId("desk-def-setup")).toContainText("Breakout confirmed");
    await expect(page.getByTestId("desk-def-window")).toContainText(`${p.timeframe_days_min}–${p.timeframe_days_max} days`);
    await expect(page.getByTestId("desk-def-odds")).toContainText("for 14 Oct 2026");
    await expect(page.getByTestId("desk-def-odds")).toContainText("One session only");
    await expect(page.getByTestId("desk-def-record")).toContainText("An intraday touch, not a close and not a trade");
    // 2 · model score and calibration
    await expect(page.getByTestId("desk-model-score")).toContainText("86 / 100");
    await expect(page.getByTestId("desk-model-pdown")).toContainText(pct1(STOCK_FIXBRK.data.estimates.p_down5_1d));
    await expect(page.getByTestId("desk-model-version")).toContainText(`Move-odds ${RUN.model}`);
    await expect(page.getByTestId("desk-model-version")).toContainText(`build ${RUN.git_sha}`);
    await expect(page.getByTestId("desk-model-eval")).toContainText(RECORD.window_label);
    await expect(page.getByTestId("desk-model-bands")).toContainText("The run publishes no calibration bands.");
    // 3 · technical evidence and patterns
    await expect(page.getByTestId("desk-tech-rs")).toContainText("pts");
    const rect = page.getByTestId(`desk-pattern-${LIVE_PAT.patterns[0].pattern_id}`);
    await expect(rect).toHaveAttribute("data-state", "confirmed");
    await expect(rect.getByTestId("desk-pattern-state")).toHaveText("Confirmed");
    await expect(rect).toContainText("Detected 9 Oct 2026");
    expect(await rect.locator('[data-testid^="desk-crit-"]').evaluateAll((els) => els.map((e) => `${e.getAttribute("data-testid")}:${e.getAttribute("data-status")}`))).toEqual(
      LIVE_PAT.patterns[0].criteria.map((c) => `desk-crit-${c.key}:${c.status}`),
    );
    await expect(rect.getByTestId("desk-crit-regime")).toContainText("no market context");
    await expect(rect.getByTestId("desk-crit-liquidity")).toContainText("₹6.5 Cr a day");
    const sr = page.getByTestId(`desk-pattern-${LIVE_PAT.patterns[1].pattern_id}`);
    await expect(sr).toHaveAttribute("data-state", "invalidated");
    await expect(sr.getByTestId("desk-pattern-state")).toHaveText("Invalidated");
    await expect(page.getByTestId("desk-patterns-off")).toContainText("Ascending triangle, Double top, Cup & handle");
    await expect(page.getByTestId("desk-patterns-trust")).toContainText("engine 0.1.0");
    // 4 · fundamentals and ownership (newest shareholding first, whatever the row order)
    await expect(page.getByTestId("desk-fund-valuation")).toContainText("24.1 · 3.2");
    await expect(page.getByTestId("desk-fund-quarter")).toContainText("Latest quarter · Q1 FY27");
    await expect(page.getByTestId("desk-fund-quarter")).toContainText("profit −4.2%");
    await expect(page.getByTestId("desk-fund-promoter")).toContainText("Promoter · Sep 2026");
    await expect(page.getByTestId("desk-fund-promoter")).toContainText("52.1% (−0.5% vs Jun 2026)");
    await expect(page.getByTestId("desk-fund-trust")).toContainText("As reported");
    // 5 · events: the exchange filing link, and the AI one-liner labelled as unverified
    const ev = page.getByTestId("desk-event");
    await expect(ev).toHaveCount(2);
    await expect(ev.first()).toContainText("Financial Results");
    await expect(ev.first().getByRole("link")).toHaveText("Exchange filing (NSE) ↗");
    await expect(ev.first()).toContainText("AI read · not verified");
    await expect(ev.nth(1)).not.toContainText("AI read");
    // 6 · liquidity and tradability
    await expect(page.getByTestId("desk-liq-traded")).toContainText(`₹${tradedOf("FIXBRK")!.toFixed(1)} Cr`);
    await expect(page.getByTestId("desk-liq-traded")).toContainText("Passes");
    await expect(page.getByTestId("desk-liq-band")).toContainText("No price band");
    await expect(page.getByTestId("desk-liq-band")).toContainText("F&O stocks trade without a daily price band");
    await expect(page.getByTestId("desk-liq-fno")).toContainText("Yes");
    await expect(page.getByTestId("desk-liq-ban")).toContainText("Not ingested");
    // 7 · hypothetical levels, with the full chart
    await expect(page.getByTestId("desk-lvl-entry")).toContainText(inr2(p.entry_price));
    await expect(page.getByTestId("desk-lvl-full")).toHaveAttribute("href", `/v5/research?screen=charts&symbol=FIXBRK&entry=${p.entry_price}&stop=${p.stoploss}&t1=${p.target_price}`);
    // 8 · historical validation: one row per outcome, each a touch, with n, hit rate, 95% interval, MFE, MAE
    for (const r of CAL.buckets.filter((x) => x.matched)) {
      await expect(page.getByTestId(`desk-val-${r.metric}-n`)).toHaveText(String(r.sample_count));
      await expect(page.getByTestId(`desk-val-${r.metric}-hit`)).toHaveText(pct1(r.probability));
      await expect(page.getByTestId(`desk-val-${r.metric}-ci`)).toHaveText(`${pct1(r.ci95_lo)}–${pct1(r.ci95_hi)}`);
      await expect(page.getByTestId(`desk-val-${r.metric}-mfe`)).toHaveText(signedPct(r.avg_fwd_return, 1));
      await expect(page.getByTestId(`desk-val-${r.metric}`)).toContainText("intraday touch");
    }
    await expect(page.getByTestId("desk-val-broke_high-ci")).toHaveText("30.9%–49.8%"); // Wilson, 40 of 100
    for (const k of ["average", "median", "costs", "benchmark", "oos"]) await expect(page.getByTestId(`desk-val-slot-${k}`)).toContainText("—");
    await expect(page.getByTestId("desk-val-slot-costs")).toContainText(CAL.not_measured.costs);
    await expect(page.getByTestId("desk-val-slot-oos")).toContainText("in-sample");
    await expect(page.getByTestId("desk-val-slot-sample")).toContainText("2 Jan 2024 – 30 Sept 2026");
    // 9 · contradictory evidence, each naming its source
    await expect(page.getByTestId(`desk-contra-pat-${LIVE_PAT.patterns[1].pattern_id}`)).toContainText("Support / resistance did not hold");
    await expect(page.getByTestId(`desk-contra-crit-${LIVE_PAT.patterns[0].pattern_id}`)).toContainText("relative strength, liquidity fail its check");
    await expect(page.getByTestId("desk-contra-profit-fall")).toContainText("profit fell 4.2%");
    await expect(page.getByTestId("desk-contra-pledge")).toContainText("6.5% of shares pledged");
    const v = LIVE.values;
    await expect(page.getByTestId("desk-contra-weak-rs")).toHaveCount(v.rs63.excess_pct < 0 ? 1 : 0);
    await expect(page.getByTestId("desk-contra-below-ema200")).toHaveCount(v.ema200 != null && v.close < v.ema200 ? 1 : 0);
    // 10 · freshness and missing inputs
    await expect(page.getByTestId("desk-fresh-bars")).toContainText("13 Oct 2026");
    await expect(page.getByTestId("desk-fresh-reference")).toContainText("14 Oct 2026");
    await expect(page.getByTestId("desk-fresh-missing")).toContainText("Intraday bars, F&O ban list, ASM / GSM lists");
    await expect(page.getByTestId("desk-detail-trust")).toContainText("End of day");
  });

  test("fundamentals and ownership: a blank figure says why, and a pledge-only quarter does not hide the last full one", async ({ page }) => {
    // MOCK — not real data: the shape of the staging reply on 2026-10-19 (feature row present but unfilled,
    // newest shareholding quarter carrying only a pledge figure).
    await chartMocks(page, {
      company: {
        kind: "company_financials",
        data: {
          v3_score: { pe_ttm: null, pb: null, roe_pct: null, debt_to_equity: null, market_cap_cr: null, as_of_date: "2026-10-19", fundamentals_source: null, fundamentals_as_of: null },
          rows: [
            { quarter: "Q1 FY27", period_end: "2026-06-30", revenue_cr: 48211, pat_cr: 7775, revenue_yoy_pct: 14.0, pat_yoy_pct: 12.3 },
            { _type: "shareholding", period: "Mar 2026", period_end: "2026-03-31", promoter_pct: 50.3, promoter_pledged_pct: null, fii_pct: 19.0, dii_pct: 17.0, mf_pct: null },
            { _type: "shareholding", period: "Jun 2026", period_end: "2026-06-30", promoter_pct: null, promoter_pledged_pct: 6.0, fii_pct: null, dii_pct: null, mf_pct: null },
          ],
        },
      },
    });
    await page.goto(`${DESK}?tab=chart&sym=FIXBRK`);
    await page.getByTestId("desk-detail-all").click();
    await expect(page.getByTestId("desk-fund-valuation")).toContainText("not filled on the 19 Oct 2026 feature row");
    await expect(page.getByTestId("desk-fund-quality")).toContainText("No source figure was loaded for that date");
    await expect(page.getByTestId("desk-fund-mcap")).toContainText("Market cap: not filled");
    await expect(page.getByTestId("desk-fund-promoter")).toContainText("Promoter · Mar 2026");
    await expect(page.getByTestId("desk-fund-promoter")).toContainText("50.3%");
    await expect(page.getByTestId("desk-fund-promoter")).toContainText("Pledged 6.0% (Jun 2026)");
    await expect(page.getByTestId("desk-fund-institutions")).toContainText("19.0%");
    await expect(page.getByTestId("desk-fund-institutions")).toContainText("mutual-fund line is not loaded");
  });

  test("honest states: the pattern engine not deployed (503) and an empty historical record show “—” with the reason", async ({ page }) => {
    await chartMocks(page, { patStatus: 503, patDetail: "pattern_engine_unavailable", cal: CAL_EMPTY });
    await page.goto(`${DESK}?tab=chart&sym=FIXBRK`);
    await page.getByTestId("desk-detail-all").click();
    await expect(page.getByTestId("desk-patterns-unavailable")).toContainText("pattern_engine_unavailable");
    await expect(page.getByTestId("desk-patterns-unavailable")).toContainText("no state is shown rather than a guess");
    await expect(page.getByTestId("desk-hist-hit")).toHaveText("—");
    await expect(page.getByTestId("desk-hist-hit-note")).toHaveText("No historical record is on file yet");
    await expect(page.getByTestId("desk-val-none")).toContainText(CAL_EMPTY.empty_reason);
    await expect(page.getByTestId("desk-val-score")).toContainText(CAL_EMPTY.symbol_reason);
    await expect(page.getByTestId("desk-val-slot-sample")).toContainText(CAL_EMPTY.sample_reason);
    await expect(page.getByTestId("desk-fresh-patterns")).toHaveAttribute("data-missing", "true");
    await expect(page.getByTestId("desk-fresh-patterns")).toContainText("not deployed");
    await expect(page.getByTestId("desk-contra-unchecked")).toContainText("Pattern failures");
  });

  test("the investor wording renames every section and keeps the figures", async ({ page }) => {
    await chartMocks(page);
    await page.goto(`${DESK}?tab=chart&sym=FIXBRK&persona=investor`);
    await expect(page.getByTestId("desk-detail-title")).toHaveText("03 · Everything about this idea");
    expect(await page.locator('[data-testid^="desk-detail-"][data-testid$="-toggle"] > span > span:first-child').allTextContents()).toEqual([
      "What is being estimated, and for how long", "The score, and how reliable it has been", "What the chart shows", "The business and who owns it", "Company news and filings",
      "Is it easy to buy and sell?", "Possible buy, exit and target prices", "How similar setups did before", "What argues against it", "How fresh the data is, and what is missing",
    ]);
    await expect(page.getByTestId("desk-detail-validation-summary")).toHaveText("Hit rate 40.0% · n 100 (touch, 10 sessions)");
    await page.getByTestId("desk-detail-technical-toggle").click();
    await expect(page.getByTestId(`desk-pattern-${LIVE_PAT.patterns[1].pattern_id}`).getByTestId("desk-pattern-state")).toHaveText("Did not hold");
    await expect(page.getByTestId("desk-ind-drawer-toggle")).toBeVisible();
    await expect(page.getByTestId("desk-risk-editor-toggle")).toContainText("Change the numbers");
  });

  test("a trust line on the chart card, the risk card and the detail: source, end of day, rules", async ({ page }) => {
    await chartMocks(page);
    await page.goto(`${DESK}?tab=chart&sym=FIXBRK`);
    await expect(page.getByTestId("desk-chart-trust")).toHaveText("NSE daily bars (nidp.prices_eod_adjusted) · End of day · 13 Oct 2026 · Rules-based · Indicators: stock_features_daily engine (calculator.py) · scanner setups: rules");
    await expect(page.getByTestId("desk-chart-trust")).toHaveAttribute("data-mode", "eod");
    await expect(page.getByTestId("desk-risk-trust")).toContainText("Positional scanner levels · scenario route (server) · End of day · 13 Oct 2026 · Rules-based");
    await expect(page.getByTestId("desk-risk-trust")).toContainText("costs 0.05% + ₹20 a side (strategy_engine)");
    await expect(page.getByTestId("desk-detail-trust")).toHaveAttribute("data-maker", "rules");
    // Nothing on the tab claims to be live.
    await expect(page.getByTestId("desk-chart-tab")).not.toContainText(/\bLive\b/);
  });
});

// ── design fidelity: titles, order, labels, persona (desktop) ────────────

test.describe("Smart trading desk · design fidelity (desktop)", () => {
  test.use({ viewport: { width: 1360, height: 900 } });

  test("scanner: the 02 card header with its trust lines, the controls row in order, and the PRD columns in order", async ({ page }) => {
    await scanMocks(page);
    await page.goto(`${DESK}?tab=scanner`);
    await expect(page.getByTestId("desk-scan-table")).toHaveAttribute("data-layout", "table");
    await expect(page.getByTestId("desk-scan-title")).toHaveText("02 · AI Opportunity scanner");
    await expect(page.getByTestId("desk-scan-trust")).toBeVisible();
    await expect(page.getByTestId("desk-scan-trust-model")).toBeVisible();
    expect(await texts(page, '[data-testid^="desk-scan-col-"]')).toEqual([
      "#", "Stock", "Score", "P(+5% next session)", "Model rank", "Pattern / catalyst", "Confirmation", "Liquidity · risk", "To target", "24 sessions", "Action",
    ]);
    expect(await texts(page, '[data-testid^="desk-scan-rank-"]:not([data-testid="desk-scan-rank"])')).toEqual(["Score", "Model rank +5%", "Model rank +10%"]);
    expect(await texts(page, '[data-testid^="desk-scan-cat-"][aria-pressed]')).toEqual([
      "All", "Breakouts", "Near breakout", "Momentum", "Pullback continuation", "Accumulation", "Reversal candidates",
      "Unusual volume", "Results-day momentum", "F&O candidates", "User watchlist",
    ]);
    // Controls row order: Rank by → chips → the Liquid-only switch at the right.
    const rankBox = (await page.getByTestId("desk-scan-rank-score").boundingBox())!;
    const chipBox = (await page.getByTestId("desk-scan-cat-all").boundingBox())!;
    const liquidBox = (await page.getByTestId("desk-scan-liquid").boundingBox())!;
    expect(rankBox.x).toBeLessThan(chipBox.x);
    expect(chipBox.x).toBeLessThan(liquidBox.x);
    await expect(page.getByTestId("desk-scan-row-FIXBRK").getByTestId("desk-scan-rank")).toHaveText("01");
    const o = await sidewaysOverflow(page);
    expect(o.doc).toBeLessThanOrEqual(1);
  });

  test("scanner: the investor wording switches the labels, the chips and the pattern text; the figures stay", async ({ page }) => {
    await scanMocks(page);
    await page.goto(`${DESK}?tab=scanner`);
    await expect(page.getByTestId("desk-scan-col-odds")).toHaveText("P(+5% next session)");
    await page.getByTestId("desk-persona-investor").click();
    await expect(page).toHaveURL(/[?&]persona=investor/);
    expect(await texts(page, '[data-testid^="desk-scan-col-"]')).toEqual([
      "#", "Stock", "Score", "Chance +5% next day", "Model rank", "Why it shows up", "What backs it", "Easy to trade · risk", "To target", "24 sessions", "Action",
    ]);
    expect(await texts(page, '[data-testid^="desk-scan-rank-"]:not([data-testid="desk-scan-rank"])')).toEqual(["Score", "Model rank +5% day", "Model rank +10% day"]);
    expect(await texts(page, '[data-testid^="desk-scan-cat-"][aria-pressed]')).toEqual([
      "All", "Broke out", "About to break out", "Rising steadily", "Dip in an uptrend", "Quiet sideways range", "Turning around",
      "Heavy trading", "Moving after results", "Has futures & options", "Your list",
    ]);
    await expect(page.getByTestId("desk-scan-row-FIXBRK").getByTestId("desk-scan-setup")).toHaveText("Broke above a recent high");
    await expect(page.getByTestId("desk-scan-row-FIXTRD").getByTestId("desk-scan-setup")).toHaveText("Dipped in an uptrend");
    await expect(page.getByTestId("desk-scan-row-UVOL1").getByTestId("desk-scan-setup")).toHaveText("Heavy trading");
    await expect(page.getByTestId("desk-scan-row-FIXBRK").getByTestId("desk-scan-liq-class")).toHaveText("Easy to trade · F&O");
    await expect(page.getByTestId("desk-scan-footnote")).toContainText("one day only");
    await expect(page.getByTestId("desk-scan-footnote")).toContainText("held back because it is not marked as checked against real outcomes");
    await expect(page.getByTestId("desk-scan-row-FIXBRK").getByTestId("desk-scan-odds")).toHaveAttribute("title", /not marked as checked against real outcomes/);
    // Same data, other words: the figures do not change.
    await expect(page.getByTestId("desk-scan-row-FIXBRK").getByTestId("desk-scan-mrank")).toHaveText(`${ord(UROWS.FIXBRK.model_rank_pct.p_up5_1d as number)} pct`);
    await expect(page.getByTestId("desk-scan-row-FIXBRK").getByTestId("desk-scan-score")).toHaveText("86");
  });

  test("chart: 03 card with the overlay chips then the timeframe, the head row, indicators, setup check, why rows and history tiles; 05 risk desk beside it", async ({ page }) => {
    await chartMocks(page);
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
    // The lines are the server's (EMA 200 has a value on the last session of these 200 bars); ◆ marks the filings in view.
    await expect(page.getByTestId("desk-chart-legend")).toHaveText("EMA 20EMA 50EMA 200VWAP 20DTargetEntryStopFilingDaily · 3 months");
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
    await chartMocks(page);
    await page.goto(`${DESK}?tab=chart&sym=FIXBRK`);
    await expect(page.getByTestId("desk-risk-gate-count")).toHaveText("5 of 5 passed");
    await expect(page.getByTestId("desk-risk-qty")).toHaveText("200");
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
    await chartMocks(page);
    await page.goto(`${DESK}?tab=chart&sym=FIXBRK&persona=investor`);
    await expect(page.getByTestId("desk-candle")).toHaveCount(63);
    await expect(page.getByTestId("desk-chart-legend")).toHaveText("20-day avg50-day avg200-day avgMonth’s avgTargetBuy aboveExitFilingDaily · 3 months");
    expect(await page.getByTestId("desk-indicators").locator(".cp-eyebrow").allTextContents()).toEqual(["Trend", "Momentum", "Daily swing", "Month’s avg", "Activity"]);
    await expect(page.getByTestId("desk-setup-check")).toContainText("What the chart shows");
    expect(await page.locator('[data-testid^="desk-why-"] > .cp-eyebrow').allTextContents()).toEqual(["Trend", "Strength", "News", "Watch"]);
    expect(await page.getByTestId("desk-history").locator(".cp-eyebrow").allTextContents()).toEqual(["Worked before", "Typical rise", "Reward for risk", "Scanner’s confidence"]);
    const risk = page.getByTestId("desk-risk");
    await expect(risk).toContainText("Reward for risk");
    await expect(risk).toContainText("Chance of +5%");
    await expect(risk).toContainText("Past trades that worked");
    await expect(page.getByTestId("desk-risk-qty")).toHaveText("200");
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
    await chartMocks(page);
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

  test("M2: scrolling category chips → Rank by and Liquid → filters → compact cards → Scanner insights; actions and filters fit", async ({ page }) => {
    await scanMocks(page);
    await page.goto(`${DESK}?tab=scanner`);
    await expect(page.getByTestId("desk-scanner")).toHaveAttribute("data-layout", "phone");
    await expect(page.getByTestId("desk-scan-table")).toHaveAttribute("data-layout", "phone");
    await expect(page.getByTestId("desk-scan-row-UVOL1")).toBeVisible();
    // The eleven chips scroll inside their own row.
    const cats = page.getByTestId("desk-scan-cats");
    expect(await cats.evaluate((el) => getComputedStyle(el).overflowX)).toBe("auto");
    expect(await cats.evaluate((el) => el.scrollWidth > el.clientWidth)).toBe(true);
    const tops = [await topOf(page, "desk-scan-cat-all"), await topOf(page, "desk-scan-rank-score"), await topOf(page, "desk-scan-filters-toggle"), await topOf(page, "desk-scan-table"), await topOf(page, "desk-scan-insights")];
    expect([...tops].sort((a, b) => a - b)).toEqual(tops);
    // Each compact card carries the PRD fields.
    const brk = page.getByTestId("desk-scan-row-FIXBRK");
    await expect(brk.getByTestId("desk-scan-score")).toHaveText("86");
    await expect(brk.getByTestId("desk-scan-odds")).toContainText("Withheld");
    await expect(brk.getByTestId("desk-scan-mrank")).toHaveText(`${ord(UROWS.FIXBRK.model_rank_pct.p_up5_1d as number)} pct`);
    await expect(brk.getByTestId("desk-scan-target")).toHaveText(`+${(((555 - 510) / 510) * 100).toFixed(1)}%`);
    await expect(brk.getByTestId("desk-scan-status")).toHaveAttribute("data-status", "confirmed");
    await expect(brk.getByTestId("desk-scan-risk")).toHaveAttribute("data-class", "medium");
    const confirmed = expectedRows().filter((r) => r.status === "confirmed").length;
    await expect(page.getByTestId("desk-scan-insights")).toContainText(
      `${ALL_SYMS.length} stocks in All on the 13 Oct 2026 scan; ${confirmed} confirmed setup. ${UNIVERSE_COUNTS.eligible} of 2,469 stocks pass the eligibility gates.`);
    await page.getByTestId("desk-scan-footnote-toggle").click();
    await expect(page.getByTestId("desk-scan-footnote")).toContainText("it is not a probability");
    // Actions and the filter panel open without a sideways scroll.
    await brk.getByTestId("desk-scan-act").click();
    await expect(page.getByTestId("desk-scan-actions-FIXBRK").getByTestId("desk-scan-act-open")).toBeVisible();
    await page.getByTestId("desk-scan-filters-toggle").click();
    await expect(page.getByTestId("desk-scan-filter-panel")).toBeVisible();
    let o = await sidewaysOverflow(page);
    expect(o.doc).toBeLessThanOrEqual(1);
    expect(o.scroll).toBeLessThanOrEqual(1);
    // Liquid only works on the phone too.
    await page.getByTestId("desk-scan-liquid").click();
    const tv = (s: string) => tradedOf(s) ?? UROWS[s].traded_value_cr_20d;
    await expect.poll(async () => (await rowOrder(page)).sort()).toEqual(ALL_SYMS.filter((s) => (tv(s) ?? -1) >= 10).sort());
    o = await sidewaysOverflow(page);
    expect(o.doc).toBeLessThanOrEqual(1);
  });

  test("M4: stock head → controls → chart → 03 analysis → historical performance → 05 trade scenario with a full-width button", async ({ page }) => {
    await chartMocks(page);
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
    await chartMocks(page);
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

// ── chart, opportunity detail and risk desk at 390px; PRD screenshots ─────

test.describe("Smart trading desk · chart, detail and risk desk at 390px", () => {
  test.use({ viewport: { width: 390, height: 844 } });

  test("PRD §5.7 / §8.5 / §8.6 at 390: every detail section and the scenario editor open, no sideways scroll", async ({ page }) => {
    await chartMocks(page, { holdings: HOLDINGS_IDEA });
    await page.goto(`${DESK}?tab=chart&sym=FIXBRK`);
    await expect(page.getByTestId("desk-candle")).toHaveCount(63);
    await expect(page.getByTestId("desk-detail-title")).toHaveText("Opportunity detail");
    await page.getByTestId("desk-detail-all").click();
    for (const k of SECTIONS) await expect(page.getByTestId(`desk-detail-${k}-body`)).toBeVisible();
    await page.getByTestId("desk-risk-editor-toggle").click();
    await expect(page.getByTestId("desk-scn-out-qty-v")).toHaveText("200 shares");
    await expect(page.getByTestId("desk-pf-existing-v")).toHaveText(inr0(50_000));
    await expect(page.getByTestId("desk-chart-full")).toBeVisible();
    await expect(page.getByTestId("desk-chart-iv-60m")).toBeDisabled();
    await expect(page.getByTestId("desk-chart-trust")).toBeVisible();
    await expect(page.getByTestId("desk-risk-trust")).toBeVisible();
    const o = await sidewaysOverflow(page);
    expect(o.doc).toBeLessThanOrEqual(1);
    expect(o.scroll).toBeLessThanOrEqual(1);
  });
});

test.describe("Smart trading desk · PRD chart screenshots", () => {
  // Written to e2e/screenshots/prd-chart-after-*.png for a visual check; the detail and the scenario editor are open.
  for (const vp of [{ width: 1440, height: 900, name: "1440", tall: 5200 }, { width: 390, height: 844, name: "390", tall: 7000 }]) {
    test(`PRDSHOT chart at ${vp.name}`, async ({ page }) => {
      await page.setViewportSize({ width: vp.width, height: vp.height });
      await chartMocks(page, { holdings: HOLDINGS_IDEA });
      await page.goto(`${DESK}?tab=chart&sym=FIXBRK`);
      await expect(page.getByTestId("desk-candle")).toHaveCount(63);
      await expect(page.getByTestId("desk-risk-paper")).toBeEnabled();
      await page.waitForTimeout(300);
      await page.screenshot({ path: `e2e/screenshots/prd-chart-after-${vp.name}.png` });
      await page.getByTestId("desk-detail-all").click();
      await page.getByTestId("desk-risk-editor-toggle").click();
      if (vp.width > 700) await page.getByTestId("desk-ind-drawer-toggle").click();
      await page.setViewportSize({ width: vp.width, height: vp.tall });
      await expect(page.getByTestId("desk-detail-freshness-body")).toBeVisible();
      await page.waitForTimeout(400);
      await page.screenshot({ path: `e2e/screenshots/prd-chart-after-${vp.name}-tall.png` });
    });
  }
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
