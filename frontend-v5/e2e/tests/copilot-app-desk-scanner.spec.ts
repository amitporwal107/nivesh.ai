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
 * TC-13 … TC-23 and TC-7 of test_reports/copilot_trading_desk_20261014_1200.md.
 */
import { test, expect, type Page } from "@playwright/test";
import { mockApi, mockSingleRoute } from "../helpers/api-mock";

const DESK = "/v5/app/trader/desk";
/** A failed request is retried by the client and once by the query, so an error block takes a few seconds. */
const SLOW = { timeout: 15_000 };

const json = (page: Page, pattern: string | RegExp, body: unknown, status = 200) =>
  page.route(pattern, (route) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) }));

// ── payloads ─────────────────────────────────────────────────────────────

// backend/routes/positional.py :: get_watchlist
const WATCHLIST = {
  as_of_date: "2026-10-13", is_weekend_mode: false, is_weekend: false, days_stale: 1, total_count: 4,
  bucket_counts: { breakout_confirmed: 1, pre_breakout: 1, true_accumulation: 1, trend_continuation: 1 },
  buckets: {
    breakout_confirmed: [{
      nse_symbol: "FIXBRK", sector: "Capital Goods", stage: "BREAKOUT", confidence: "HIGH", final_score: 0.79, close_price: 510.0,
      trigger_price: 500.0, stop_price: 477.5, atr_pct: 2.94, rsi_14: 64.2, sma_50: 470.0, sma_200: 430.0, ema_20: 492.1,
      signals: { range_pct_15d: 9.1, volume_slope_10d_pct: 2.1, volume_spike_3v20: 1.8, higher_lows_count: 2, upper_wick_pct: 0.2, delivery_trend_pct: 4.0, dist_breakout_pct: 2.0, dist_ema20_pct: 3.64 },
      why: "Broke above ₹500.00 (+2.0%) on 1.8× avg volume",
    }],
    pre_breakout: [{
      nse_symbol: "FIXPRE", sector: "Chemicals", stage: "EARLY_BREAKOUT", confidence: "MEDIUM", final_score: 0.74, close_price: 245.0,
      trigger_price: 250.0, stop_price: 238.0, atr_pct: 3.1, rsi_14: 58.0, sma_50: 236.0, sma_200: 220.0, ema_20: 241.0,
      signals: { range_pct_15d: 7.2, volume_slope_10d_pct: 1.0, volume_spike_3v20: 1.3, higher_lows_count: 1, upper_wick_pct: 0.3, delivery_trend_pct: null, dist_breakout_pct: -2.0, dist_ema20_pct: 1.66 },
      why: "2.0% below ₹250.00 resistance · volume 1.3× avg",
    }],
    true_accumulation: [{
      nse_symbol: "FIXACC", sector: "Textiles", stage: "ACCUMULATION", confidence: "LOW", final_score: 0.62, close_price: 88.5,
      trigger_price: 92.0, stop_price: 84.0, atr_pct: 2.2, rsi_14: 51.0, sma_50: 87.0, sma_200: 90.0, ema_20: 88.0,
      signals: { range_pct_15d: 6.1, volume_slope_10d_pct: -1.4, volume_spike_3v20: 0.8, higher_lows_count: 2, upper_wick_pct: 0.1, delivery_trend_pct: 3.0, dist_breakout_pct: -3.8, dist_ema20_pct: 0.57 },
      why: "Tight 6.1% range, vol drying -1.4%/d, 2 higher lows",
    }],
    trend_continuation: [{
      nse_symbol: "FIXTRD", sector: "IT", stage: "ACCUMULATION", confidence: "MEDIUM", final_score: 0.69, close_price: 1210.0,
      trigger_price: null, stop_price: 1150.0, atr_pct: 1.9, rsi_14: 61.0, sma_50: 1150.0, sma_200: 1100.0, ema_20: 1190.0,
      signals: { range_pct_15d: 8.4, volume_slope_10d_pct: 0.4, volume_spike_3v20: 1.0, higher_lows_count: 1, upper_wick_pct: 0.2, delivery_trend_pct: null, dist_breakout_pct: null, dist_ema20_pct: 1.68 },
      why: "Trend intact (close > 20EMA ₹1190.00 > 50EMA), 1.7% above 20EMA — pullback zone",
    }],
  },
  _classifier_version: "smart_v2",
};

// backend/routes/positional.py :: get_picks. FIXBRK is in both routes: the pick's plan (entry, stop, target) and score win.
const PICKS = {
  signal_date: "2026-10-13", count: 2,
  picks: [
    { nse_symbol: "FIXBRK", signal_date: "2026-10-13", final_score: 0.86, confidence: "HIGH", stage: "BREAKOUT", timeframe_days_min: 5, timeframe_days_max: 15,
      entry_price: 505.0, stoploss: 480.0, target_price: 555.0, risk_reward: 2.0, source_scans: ["btst.breakout_confirmation"], reasons: ["Closed above a 60-day high on rising volume"] },
    { nse_symbol: "FIXPICK", signal_date: "2026-10-13", final_score: 0.81, confidence: "MEDIUM", stage: "EARLY_BREAKOUT", timeframe_days_min: 3, timeframe_days_max: 10,
      entry_price: 120.0, stoploss: 114.0, target_price: 138.0, risk_reward: 3.0, source_scans: ["swing.pullback"], reasons: ["Fixture pick reason"] },
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
const RECORD = { window_label: "Jan–Aug 2025", sessions: 165, base_rate: 0.0812, top10_hit_rate: 0.3103, bands: [] };
const BASE_RATE: Record<string, number> = { p_up5_1d: 0.0758, p_down5_1d: 0.0611, p_up10_1d: 0.0153, p_down10_1d: 0.0088 };
const latest = (head: string) => ({
  data: {
    status: "final", head, expected_session: "2026-10-14", base_rate: BASE_RATE[head], run: RUN, rows: ODDS_ROWS, record: RECORD,
    live_record: { sessions: 0, top10_hits: null, touched: null, graded_rows: null, last_target: null, last_top10_hits: null, last_touched: null, last_graded_rows: null },
    limits: { not_used: ["analyst estimates"] },
  },
});

// move_odds.py :: stock
const EVENT = (ord: number) => ({
  ord, event_time: "2026-10-13T12:35:20+05:30", source_label: "NSE filing", is_media: false, event_type: "CORPORATE", event_subtype: "update",
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

// ── AI scanner ───────────────────────────────────────────────────────────

test.describe("Smart trading desk · AI scanner", () => {
  test("TC-13 merged rows are ranked by score, status follows the bucket, and the pick's plan wins", async ({ page }) => {
    await deskMocks(page);
    await page.goto(`${DESK}?tab=scanner`);
    await expect(page.getByTestId("desk-scanner")).toBeVisible();

    const exp = expectedRows();
    const byScore = [...exp].sort((a, b) => b.score - a.score).map((r) => r.symbol);
    expect(await rowOrder(page)).toEqual(byScore);
    await expect(page.getByTestId("desk-scan-eyebrow")).toHaveText(`NSE · end of day · ${exp.length} of ${exp.length} shown`);
    await expect(page.getByTestId("desk-scan-date")).toHaveText("Scan · 13 Oct 2026");

    for (const r of exp) {
      const row = page.getByTestId(`desk-scan-row-${r.symbol}`);
      await expect(row.getByTestId("desk-scan-status")).toHaveAttribute("data-status", r.status);
      await expect(row.getByTestId("desk-scan-score")).toHaveText(String(Math.round(r.score)));
      // To target: from the close (else the entry) to the pick's target; "—" without a target.
      const base = r.close ?? r.entry;
      const to = r.target != null && base != null ? `+${(((r.target - base) / base) * 100).toFixed(1)}%` : "—";
      await expect(row.getByTestId("desk-scan-target")).toHaveText(to);
    }
    // FIXBRK is in both routes: one row, the pick's score (86, not the watchlist's 79) and its target (555 from the 510 close).
    await expect(page.locator('[data-testid="desk-scan-row-FIXBRK"]')).toHaveCount(1);
    const brk = page.getByTestId("desk-scan-row-FIXBRK");
    await expect(brk.getByTestId("desk-scan-score")).toHaveText(String(Math.round(PICKS.picks[0].final_score * 100)));
    await expect(brk.getByTestId("desk-scan-setup")).toHaveText("Breakout confirmed");
    await expect(brk.getByTestId("desk-scan-why")).toHaveText(WATCHLIST.buckets.breakout_confirmed[0].why);
    await expect(brk.getByTestId("desk-scan-symbol")).toHaveText("FIXBRK");
    // A pick the watchlist does not have: no close, so its row names the entry, and its status comes from the stage.
    const pick = page.getByTestId("desk-scan-row-FIXPICK");
    await expect(pick).toContainText(`Entry ${inr2(PICKS.picks[1].entry_price)}`);
    await expect(pick.getByTestId("desk-scan-setup")).toHaveText("Scanner pick · early breakout");
    await expect(page.getByTestId("desk-scan-footnote")).toContainText("it is not a probability");
  });

  test("TC-14 group chips filter the list and Reward:risk re-ranks it", async ({ page }) => {
    await deskMocks(page);
    await page.goto(`${DESK}?tab=scanner`);
    const exp = expectedRows();

    await page.getByTestId("desk-scan-group-breakout_confirmed").click();
    await expect(page.getByTestId("desk-scan-group-breakout_confirmed")).toHaveAttribute("aria-pressed", "true");
    expect(await rowOrder(page)).toEqual(exp.filter((r) => r.bucket === "breakout_confirmed").map((r) => r.symbol));
    await expect(page.getByTestId("desk-scan-eyebrow")).toHaveText(`NSE · end of day · 1 of ${exp.length} shown`);

    await page.getByTestId("desk-scan-group-picks").click();
    const picks = PICKS.picks.map((p) => p.nse_symbol);
    expect((await rowOrder(page)).sort()).toEqual([...picks].sort());

    await page.getByTestId("desk-scan-group-true_accumulation").click();
    expect(await rowOrder(page)).toEqual(exp.filter((r) => r.bucket === "true_accumulation").map((r) => r.symbol));

    await page.getByTestId("desk-scan-group-all").click();
    await page.getByTestId("desk-scan-rank-rr").click();
    await expect(page.getByTestId("desk-scan-rank-rr")).toHaveAttribute("aria-pressed", "true");
    const byRr = [...exp].sort((a, b) => desc(a.rr, b.rr) || b.score - a.score).map((r) => r.symbol);
    expect(await rowOrder(page)).toEqual(byRr);
    expect(byRr[0]).toBe("FIXPICK"); // the 3.0 reward-to-risk pick moves above the higher-scored FIXBRK (2.0)
  });

  test("TC-15 published odds: P(+5% next session) and events per row, the model's record, and ranking by it", async ({ page }) => {
    await deskMocks(page);
    await page.goto(`${DESK}?tab=scanner`);
    await expect(page.getByTestId("desk-scan-record")).toHaveAttribute("data-state", "final");
    const bySym = new Map(ODDS_ROWS.map((r) => [r.symbol, r]));
    for (const r of expectedRows()) {
      const row = page.getByTestId(`desk-scan-row-${r.symbol}`);
      const o = bySym.get(r.symbol);
      await expect(row.getByTestId("desk-scan-odds")).toHaveText(o ? pct1(o.p) : "—");
      await expect(row.getByTestId("desk-scan-events")).toHaveText(o ? String(o.events_on_record) : "—");
    }
    await expect(page.getByTestId("desk-scan-record")).toContainText(
      `Out-of-sample ${RECORD.window_label}: top-10 hit rate ${pct1(RECORD.top10_hit_rate)} over ${RECORD.sessions} sessions vs base rate ${pct1(RECORD.base_rate)}.`,
    );
    await expect(page.getByTestId("desk-scan-record")).toContainText("Run on data of 13 Oct 2026, for the session of 14 Oct 2026.");

    await page.getByTestId("desk-scan-rank-odds").click();
    const exp = expectedRows();
    const byP = [...exp].sort((a, b) => desc(bySym.get(a.symbol)?.p ?? null, bySym.get(b.symbol)?.p ?? null) || b.score - a.score).map((r) => r.symbol);
    expect(await rowOrder(page)).toEqual(byP);
  });

  test("TC-15 odds 403: every probability is “—” and the account is told it is not enabled", async ({ page }) => {
    await deskMocks(page, { oddsStatus: 403 });
    await page.goto(`${DESK}?tab=scanner`);
    await expect(page.getByTestId("desk-scan-record")).toHaveAttribute("data-state", "no_access");
    await expect(page.getByTestId("desk-scan-record")).toContainText("Move probabilities are not enabled for this account");
    for (const r of expectedRows()) {
      const row = page.getByTestId(`desk-scan-row-${r.symbol}`);
      await expect(row.getByTestId("desk-scan-odds")).toHaveText("—");
      await expect(row.getByTestId("desk-scan-events")).toHaveText("—");
    }
    await expect(page.getByTestId("desk-scan-rank-odds")).toBeDisabled();
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
    await page.getByTestId("desk-chart-tf-1M").click();
    await expect(candles).toHaveCount(22);
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

    // Overlays toggle (aria-pressed) and leave the chart.
    await expect(page.getByTestId("desk-line-ema20")).toHaveCount(1);
    await page.getByTestId("desk-chart-ov-ema").click();
    await expect(page.getByTestId("desk-chart-ov-ema")).toHaveAttribute("aria-pressed", "false");
    await expect(page.getByTestId("desk-line-ema20")).toHaveCount(0);
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
    await expect(page.getByTestId("desk-ind-ema50")).toHaveText(inr2(e50));
    await expect(page.getByTestId("desk-ind-ema20-sub")).toContainText(side(e20));
    await expect(page.getByTestId("desk-ind-rsi")).toHaveText(rsi.toFixed(1));
    await expect(page.getByTestId("desk-ind-rsi-sub")).toHaveText(rsi >= 70 ? "Overbought" : rsi >= 55 ? "Healthy" : "Neutral");
    await expect(page.getByTestId("desk-ind-atr")).toHaveText(inr2(atr));
    await expect(page.getByTestId("desk-ind-atr-sub")).toHaveText(`${((atr / close) * 100).toFixed(2)}% of price`);
    await expect(page.getByTestId("desk-ind-vwap")).toHaveText(inr2(vwap));
    await expect(page.getByTestId("desk-ind-vwap-sub")).toHaveText(side(vwap));
    await expect(page.getByTestId("desk-ind-rvol")).toHaveText(`${rv.toFixed(2)}×`);
    expect(rv).toBeGreaterThanOrEqual(1.5); // the fixture's last session is a volume spike
    await expect(page.getByTestId("desk-ind-rvol-sub")).toHaveText("Volume expansion");
    await expect(page.getByTestId("desk-indicators")).toContainText("not the intraday VWAP");

    // Header: last close and the day's change from the bars.
    const prev = closes[closes.length - 2];
    const ch = ((close - prev) / prev) * 100;
    await expect(page.getByTestId("desk-chart-close")).toHaveText(inr2(close));
    await expect(page.getByTestId("desk-chart-change")).toHaveText(`${ch > 0 ? "+" : ch < 0 ? "−" : ""}${Math.abs(ch).toFixed(2)}%`);
  });

  test("TC-20 levels and reward : risk come from the pick, not the watchlist", async ({ page }) => {
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
    await expect(page.getByTestId("desk-risk-entry")).toHaveText(`Entry ${inr2(p.entry_price)}`);
    await expect(page.getByTestId("desk-risk-stop")).toHaveText(`Stop ${inr2(p.stoploss)}`);
    await expect(page.getByTestId("desk-risk-target")).toHaveText(`Target ${inr2(p.target_price)}`);
    const rr = (p.target_price - p.entry_price) / (p.entry_price - p.stoploss);
    expect(rr).toBeCloseTo(p.risk_reward, 9);
    await expect(page.getByTestId("desk-risk-rr")).toHaveText(`${p.risk_reward.toFixed(2)} : 1`);
    await expect(page.getByTestId("desk-risk-scenario")).toHaveText("Breakout confirmed");
    await expect(page.getByTestId("desk-risk-status")).toHaveAttribute("data-status", "confirmed");
    await expect(page.getByTestId("desk-chart-pills")).toContainText(`Volume ${WATCHLIST.buckets.breakout_confirmed[0].signals.volume_spike_3v20.toFixed(1)}×`);

    // Levels toggle off removes the lines.
    await page.getByTestId("desk-chart-ov-levels").click();
    await expect(page.getByTestId("desk-level-target")).toHaveCount(0);

    // Risk desk probability and gate: FIXBRK has 3 events on record, a record, and a run that counts → 5 of 5.
    const o = ODDS_ROWS.find((r) => r.symbol === "FIXBRK")!;
    await expect(page.getByTestId("desk-risk-p5")).toHaveText(pct1(o.p));
    await expect(page.getByTestId("desk-risk-gate-count")).toHaveText("5 of 5 passed");
    await expect(page.getByTestId("desk-risk-check-events")).toContainText(`Events on record for FIXBRK: ${o.events_on_record}`);
    await expect(page.getByTestId("desk-risk-record")).toHaveText(pct1(RECORD.top10_hit_rate));

    // Model block: the stock route's four estimates beside each head's base rate.
    for (const [head, v] of Object.entries(STOCK_FIXBRK.data.estimates)) {
      await expect(page.getByTestId(`desk-model-${head}-p`)).toHaveText(pct1(v));
      await expect(page.getByTestId(`desk-model-${head}-base`)).toHaveText(`Base rate ${pct1(BASE_RATE[head])}`);
    }

    // Setup check and why: from the scanner payload.
    await expect(page.getByTestId("desk-check-volume")).toContainText("1.8×");
    await expect(page.getByTestId("desk-why")).toContainText(PICKS.picks[0].reasons[0]);
    await expect(page.getByTestId("desk-why")).toContainText(WATCHLIST.buckets.breakout_confirmed[0].why);
  });

  test("a stock with no events on record fails one gate check and its estimate is withheld from high-confidence display", async ({ page }) => {
    await deskMocks(page);
    await page.goto(`${DESK}?tab=chart&sym=FIXPRE`);
    const o = ODDS_ROWS.find((r) => r.symbol === "FIXPRE")!;
    await expect(page.getByTestId("desk-risk-gate-count")).toHaveText("4 of 5 passed");
    await expect(page.getByTestId("desk-risk-check-events")).toHaveAttribute("data-ok", "false");
    await expect(page.getByTestId("desk-risk-p5")).toHaveText(pct1(o.p));
    await expect(page.getByTestId("desk-risk-p5-note")).toHaveText("Withheld from high-confidence display: 4 of 5 checks passed.");
    // The stock route has no estimate for it (404): said in words.
    await expect(page.getByTestId("desk-model-none")).toContainText("not in the model’s published run");
  });

  test("a symbol that is not on the scanner shows the chart and indicators, and no levels", async ({ page }) => {
    await deskMocks(page);
    await page.goto(`${DESK}?tab=chart&sym=FIXBRK`);
    await page.getByTestId("desk-chart-symbol-input").fill("bad sym!");
    await page.getByTestId("desk-chart-symbol-load").click();
    await expect(page.getByTestId("desk-chart-symbol-error")).toBeVisible();
    await page.getByTestId("desk-chart-symbol-input").fill("othersym");
    await page.getByTestId("desk-chart-symbol-load").click();
    await expect(page).toHaveURL(/[?&]sym=OTHERSYM(&|$)/);
    await expect(page.getByTestId("desk-chart-symbol")).toHaveText("OTHERSYM");
    await expect(page.getByTestId("desk-candle")).toHaveCount(63);
    await expect(page.getByTestId("desk-not-on-scanner")).toContainText("Not on today’s scanner — no levels");
    await expect(page.getByTestId("desk-risk-nolevels")).toBeVisible();
    await expect(page.getByTestId("desk-risk-nosize")).toBeVisible();
    await expect(page.getByTestId("desk-chart-ov-levels")).toBeDisabled();
    await expect(page.getByTestId("desk-risk-rr")).toHaveText("—");
  });

  test("TC-21 chart-live 403 → charting locked for the account", async ({ page }) => {
    await deskMocks(page, { barsStatus: 403 });
    await page.goto(`${DESK}?tab=chart&sym=FIXBRK`);
    await expect(page.getByTestId("desk-chart-locked")).toContainText("Charting is not enabled for this account");
    await expect(page.getByTestId("desk-candle")).toHaveCount(0);
    await expect(page.getByTestId("desk-indicators")).toHaveCount(0);
    // The scanner's levels still drive the risk desk.
    await expect(page.getByTestId("desk-risk-rr")).toHaveText(`${PICKS.picks[0].risk_reward.toFixed(2)} : 1`);
  });

  test("TC-21 chart-live 404 → no prices on record", async ({ page }) => {
    await deskMocks(page, { barsStatus: 404 });
    await page.goto(`${DESK}?tab=chart&sym=FIXBRK`);
    await expect(page.getByTestId("desk-chart-noprices")).toContainText("No daily prices on record for FIXBRK");
    await expect(page.getByTestId("desk-candle")).toHaveCount(0);
  });

  test("TC-22 position size: the worked example from the pick, toggles recompute, and the 25% warning", async ({ page }) => {
    await deskMocks(page);
    await page.goto(`${DESK}?tab=chart&sym=FIXBRK`);
    const { entry_price: entry, stoploss: stop, target_price: target } = PICKS.picks[0];
    const size = (capital: number, riskPct: number) => {
      const qty = Math.floor((capital * riskPct) / 100 / (entry - stop));
      const used = qty * entry;
      return { qty, used, usedPct: (used / capital) * 100, maxLoss: qty * (entry - stop), atTarget: qty * (target - entry), limit: Math.floor((capital * 0.25) / entry) };
    };
    const check = async (capital: number, riskPct: number) => {
      const s = size(capital, riskPct);
      await expect(page.getByTestId("desk-risk-qty")).toHaveText(new Intl.NumberFormat("en-IN").format(s.qty));
      await expect(page.getByTestId("desk-risk-used")).toHaveText(inr0(s.used));
      await expect(page.getByTestId("desk-risk-used-pct")).toHaveText(`${s.usedPct.toFixed(1)}%`);
      await expect(page.getByTestId("desk-risk-maxloss")).toHaveText(inr0(s.maxLoss));
      await expect(page.getByTestId("desk-risk-attarget")).toHaveText(`+${inr0(s.atTarget)}`);
      if (s.used > capital * 0.25) {
        await expect(page.getByTestId("desk-risk-warn")).toHaveText(`Capital used is above a 25% single-stock limit; ${s.limit} shares keeps you inside it.`);
      } else {
        await expect(page.getByTestId("desk-risk-warn")).toHaveCount(0);
      }
      return s;
    };
    // Defaults: ₹5L at 1% → 5,000 ÷ 25 = 200 shares.
    await expect(page.getByTestId("desk-risk-capital-5l")).toHaveAttribute("aria-pressed", "true");
    await expect(page.getByTestId("desk-risk-pct-1")).toHaveAttribute("aria-pressed", "true");
    expect((await check(500_000, 1)).qty).toBe(200);
    await expect(page.getByTestId("desk-risk-size")).toContainText("before brokerage and taxes");

    await page.getByTestId("desk-risk-capital-2l").click();
    await page.getByTestId("desk-risk-pct-2").click();
    const over = await check(200_000, 2); // 4,000 ÷ 25 = 160 shares = ₹80,800, 40.4% of ₹2L
    expect(over.used).toBeGreaterThan(200_000 * 0.25);

    await page.getByTestId("desk-risk-capital-10l").click();
    await page.getByTestId("desk-risk-pct-0-5").click();
    await check(1_000_000, 0.5);
  });

  test("TC-23 the paper-trade and alert actions are disabled, explained, and send nothing", async ({ page }) => {
    const writes = recordWrites(page);
    await deskMocks(page);
    await page.goto(`${DESK}?tab=chart&sym=FIXBRK`);
    const paper = page.getByTestId("desk-risk-paper");
    const alert = page.getByTestId("desk-risk-alert");
    await expect(paper).toBeDisabled();
    await expect(alert).toBeDisabled();
    await expect(page.getByTestId("desk-risk-paper-note")).toContainText("Not connected yet");
    await expect(page.getByTestId("desk-risk-alert-note")).toContainText("Not connected yet");
    await paper.click({ force: true });
    await alert.click({ force: true });
    await page.getByTestId("desk-risk-capital-2l").click();
    await page.getByTestId("desk-chart-tf-6M").click();
    await expect(page.getByTestId("desk-risk")).toContainText("Nivesh reads broker positions and cannot place orders.");
    await page.waitForTimeout(500);
    expect(writes).toEqual([]);
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

// ── phone width ──────────────────────────────────────────────────────────

test.describe("Smart trading desk · scanner and chart at 390px", () => {
  test.use({ viewport: { width: 390, height: 844 } });

  for (const tab of ["scanner", "chart"] as const) {
    test(`TC-7 ${tab} tab: no sideways page scroll`, async ({ page }) => {
      await deskMocks(page);
      await page.goto(`${DESK}?tab=${tab}&sym=FIXBRK`);
      if (tab === "scanner") {
        await expect(page.getByTestId("desk-scan-cards")).toBeVisible();
        await expect(page.getByTestId("desk-scan-row-FIXBRK")).toBeVisible();
      } else {
        await expect(page.getByTestId("desk-candle")).toHaveCount(63);
        await expect(page.getByTestId("desk-risk")).toBeVisible();
        await expect(page.getByTestId("desk-model-p_up5_1d-p")).toBeVisible();
      }
      const o = await sidewaysOverflow(page);
      expect(o.doc).toBeLessThanOrEqual(1);
      expect(o.scroll).toBeLessThanOrEqual(1);
    });
  }
});
