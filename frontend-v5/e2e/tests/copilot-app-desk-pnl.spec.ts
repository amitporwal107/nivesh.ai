/**
 * One-screen Copilot app (/v5/app) — Trade Desk › Paper Trading › P&L dashboard (owner, 4 Nov 2026; the real-time paper P&L,
 * docs/paper_pnl_dashboard/DESIGN.md; test cases TC-032 … TC-040 in test_reports/paper_pnl_dashboard_TESTCASES.md).
 *
 * Every /api/* answer below is an inline MOCK — not real data — in the shape DESIGN.md gives for GET /api/desk/pnl, its stream
 * and /timeseries (backend/routes/desk_pnl.py). Symbols, prices and P&L are made up. Mocked APIs, production build.
 */
import { test, expect, type Page, type Route } from "@playwright/test";
import fs from "fs";
import { mockApi, mockSingleRoute } from "../helpers/api-mock";

const json = (route: Route, body: unknown, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
const clone = <T,>(x: T): T => JSON.parse(JSON.stringify(x));
const DESK = "/v5/app/trader/desk";
const PNL = `${DESK}?tab=trade&view=paper&sub=pnl`;
const SLOW = { timeout: 15_000 };

// ── MOCK — not real data: GET /api/desk/pnl (DESIGN.md "API") ─────────────────────────────────────────────────────────────
const ex = (id: string, side: string, quantity: number, price: number, kind = "fill") => ({ execution_id: id, side, quantity, price, at: "2026-10-28T02:24:09+00:00", kind });
const pos = (o: Record<string, unknown>) => ({
  trade_id: null, leg_index: null, strategy_id: null, strategy_name: null, mode: "PAPER", account: "Paper account", lots: null, lot_size: null,
  realized_pnl: 0, opened_at: "2026-10-28T02:24:09+00:00", expiry: null, risk_used_pct: null, price_day: "2026-11-04", ...o,
});
const ICICI = pos({
  position_id: "pt-icici", trade_id: "pt-icici", instrument: "ICICIBANK", symbol: "ICICIBANK", underlying: "ICICIBANK", segment: "EQUITY", side: "LONG",
  net_quantity: 35, avg_price: 1413.21, ltp: 1431.5, prev_close: 1420.1, price_status: "LIVE", price_source: "Kite live", price_at: "2026-11-04T10:30:01+05:30",
  price_age_seconds: 0.8, invested_value: 49462.35, unrealized_pnl: 640.15, gross_pnl: 640.15, charges_estimated: 40.2, net_pnl: 599.95, day_pnl: 399,
  return_pct: 1.21, stop_loss: 1374.9, target: 1489.83, distance_to_stop_pct: 3.95, status: "ACTIVE", executions: [ex("pt-icici:open", "BUY", 35, 1413.21)],
});
const COFORGE = pos({
  position_id: "pt-cof", trade_id: "pt-cof", instrument: "COFORGE", symbol: "COFORGE", underlying: "COFORGE", segment: "EQUITY", side: "LONG",
  net_quantity: 18, avg_price: 2010.81, ltp: 1900, prev_close: 1921, price_status: "DELAYED", price_source: "Kite live (no tick since 10:21:40)",
  price_at: "2026-11-04T10:21:40+05:30", price_age_seconds: 501, invested_value: 36194.58, unrealized_pnl: -1994.58, gross_pnl: -1994.58,
  charges_estimated: 35.1, net_pnl: -2029.68, day_pnl: -378, return_pct: -5.61, stop_loss: 1904.91, target: 2222.61, distance_to_stop_pct: -0.26,
  status: "STOP_LOSS_HIT", executions: [ex("pt-cof:open", "BUY", 18, 2010.81)],
});
const LEG0 = pos({
  position_id: "st-1:0", trade_id: "st-1", leg_index: 0, strategy_id: "st-1", strategy_name: "Bull call spread", instrument: "NIFTY 25 Nov 25000 CE",
  symbol: "NIFTY25NOV25000CE", underlying: "NIFTY", segment: "OPTIONS", side: "LONG", net_quantity: 75, lots: 1, lot_size: 75, avg_price: 180, ltp: 222,
  prev_close: 205, price_status: "LIVE", price_source: "Kite REST quote", price_at: "2026-11-04T10:30:00+05:30", price_age_seconds: 1.4,
  invested_value: 13500, unrealized_pnl: 3150, gross_pnl: 3150, charges_estimated: 60, net_pnl: 3090, day_pnl: 1275, return_pct: 22.89,
  stop_loss: null, target: null, distance_to_stop_pct: null, status: "ACTIVE", expiry: "2026-11-25", executions: [ex("st-1:0:open", "BUY", 75, 180)],
});
const LEG1 = pos({
  position_id: "st-1:1", trade_id: "st-1", leg_index: 1, strategy_id: "st-1", strategy_name: "Bull call spread", instrument: "NIFTY 25 Nov 25200 CE",
  symbol: "NIFTY25NOV25200CE", underlying: "NIFTY", segment: "OPTIONS", side: "SHORT", net_quantity: -75, lots: 1, lot_size: 75, avg_price: 95, ltp: 120,
  prev_close: 110, price_status: "DELAYED", price_source: "Kite REST quote (last trade in the previous session)", price_at: "2026-11-03T15:29:58+05:30",
  price_age_seconds: 68402, price_day: "2026-11-03", invested_value: -7125, unrealized_pnl: -1875, gross_pnl: -1875, charges_estimated: 40, net_pnl: -1915, day_pnl: -750, return_pct: null,
  stop_loss: null, target: null, distance_to_stop_pct: null, status: "ACTIVE", expiry: "2026-11-25", executions: [ex("st-1:1:open", "SELL", 75, 95)],
});
const STRATEGY = {
  strategy_id: "st-1", name: "Bull call spread", summary: "Bull call spread 25000/25200 · 25 Nov · 1 lot", opened_at: "2026-11-02T04:00:00+00:00", risk_note: null, underlying: "NIFTY", direction: "bullish", status: "OPEN", legs: ["st-1:0", "st-1:1"],
  underlying_ltp: 25890, stop_underlying: 25400, target_underlying: 26300, entry_net_premium: -6375, current_value: 7650, unrealized_pnl: 1275,
  charges_estimated: 100, net_pnl: 1175, capital_at_risk: 6375, complete: true,
};
const CLOSED = { trade_id: "pt-axis", instrument: "AXISBANK", segment: "EQUITY", closed_at: "2026-11-03T15:30:00+00:00", exit_session: "2026-11-03",
  exit_reason: "stop", realized_pnl: -3200, charges: 160.1, net_pnl: -3360.1 };
const ALERTS = [
  { severity: "INFO", type: "EXPIRY", position_id: "st-1:0", symbol: "NIFTY", message: "Expires on 25 Nov (15 sessions).", observed: null, threshold: null },
  { severity: "CRITICAL", type: "STOP_LOSS_HIT", position_id: "pt-cof", symbol: "COFORGE", message: "Price is below the stop loss. The paper exit is decided at the evening check on today's bar.", observed: 1900, threshold: 1904.91 },
  { severity: "WARNING", type: "STALE_PRICE", position_id: "pt-cof", symbol: "COFORGE", message: "No tick since 10:21:40; P&L is at that price.", observed: null, threshold: null },
];
const SUMMARY_ALL = {
  realized_pnl: 0, unrealized_pnl: -79.43, gross_pnl: -79.43, charges_booked: 0, charges_estimated: 175.3, net_pnl: -254.73, day_pnl: 546,
  allocated_capital: 10000000, return_pct: -0.0025, open_positions: 3, open_legs: 4, winning_positions: 2, losing_positions: 2, closed_trades: 0,
  pending_entries: 1, unpriced_positions: 0, stale_positions: 2, complete: true,
};
function snapshot(q: URLSearchParams, seq = 1762232401000, patch?: (s: Record<string, unknown>) => void) {
  const segment = q.get("segment") ?? "ALL";
  const period = q.get("period") ?? "TODAY";
  const opts = segment === "OPTIONS";
  const weekly = period === "1W" || period === "1M" || period === "ALL";
  const positions = opts ? [LEG0, LEG1] : segment === "EQUITY" ? [ICICI, COFORGE] : [ICICI, COFORGE, LEG0, LEG1];
  const realized = weekly ? -3200 : 0;
  const s: Record<string, unknown> = {
    mode: "PAPER", currency: "INR", as_of: "2026-11-04T10:30:01+05:30", sequence: seq,
    filters: { segment, period, from: weekly ? "2026-10-29" : "2026-11-04", to: "2026-11-04" },
    market: { session: "open", feed: "live", feed_age_seconds: 1.2, stale_after_seconds: 75, day: "2026-11-04",
      price_rule: "MOCK: live Kite price in session; Kite close after 15:30 until the exchange's end-of-day file; else the ledger's end-of-day mark.", notes: [] },
    summary: opts
      ? { ...SUMMARY_ALL, unrealized_pnl: 1275, gross_pnl: 1275, charges_estimated: 100, net_pnl: 1175, open_positions: 2, winning_positions: 1, losing_positions: 1, pending_entries: 0, stale_positions: 0 }
      : { ...SUMMARY_ALL, realized_pnl: realized, gross_pnl: -79.43 + realized, charges_booked: weekly ? 160.1 : 0, net_pnl: weekly ? -3614.83 : -254.73, closed_trades: weekly ? 1 : 0 },
    by_segment: opts ? [{ segment: "OPTIONS", open_positions: 2, realized_pnl: 0, unrealized_pnl: 1275, charges: 100, net_pnl: 1175 }]
      : [{ segment: "EQUITY", open_positions: 2, realized_pnl: realized, unrealized_pnl: -1354.43, charges: 75.3, net_pnl: -1429.73 },
        { segment: "OPTIONS", open_positions: 2, realized_pnl: 0, unrealized_pnl: 1275, charges: 100, net_pnl: 1175 }],
    positions: clone(positions),
    strategies: segment === "EQUITY" ? [] : [clone(STRATEGY)],
    pending_entries: opts ? [] : [{ trade_id: "pt-pend", symbol: "HDFCBANK", entry_rule: "break_above", level: 1655, ltp: 1641.2 }],
    closed: weekly && !opts ? [CLOSED] : [],
    closed_total: weekly && !opts ? 1 : 0, closed_partial: false, marks_error: null,
    risk: { capital: { starting: 10000000, cash: 10000000, blocked: 123887.21, available: 9876112.79, utilisation_pct: 1.24, basis: "capital at risk, not exchange margin" },
      open_risk_rs: -2100, open_risk_limit_rs: 300000, strategies_capital_at_risk_rs: 6375, near_stop_pct: 1, daily_loss_limit_rs: 200000, daily_loss_used_pct: 0, alerts: ALERTS },
    analytics: { trades: weekly ? 1 : 0, wins: 0, losses: weekly ? 1 : 0, win_rate_pct: weekly ? 0 : null, profit_factor: null, avg_win: null,
      avg_loss: weekly ? -3360.1 : null, max_drawdown_rs: weekly ? -3360.1 : null, max_drawdown_pct: weekly ? 0.0336 : null,
      daily: weekly ? [{ date: "2026-11-03", net_pnl: -3360.1 }] : [] },
    reconciliation: { checked: weekly ? 1 : 0, mismatches: [] },
    notes: { display_only: "MOCK: live prices are for display; the ledger decides exits on end-of-day bars.", charges: "MOCK: charges are the desk cost card's.",
      unrealized: "MOCK: open P&L = (price now − average price) × quantity.", capital: "MOCK: return % = net P&L ÷ starting capital." },
  };
  patch?.(s);
  return s;
}
// ── MOCK — not real data: GET /api/desk/pnl/timeseries ───────────────────────────────────────────────────────────────────
const TIMESERIES = {
  date: "2026-11-04", interval: "5m", baseline_gross: -500, positions_used: 3,
  points: ["09:15", "09:20", "09:25", "09:30", "09:35", "10:30"].map((t, i) => {
    const g = [-500, -320, -150, 40, -90, -79.43][i];
    return { t: `2026-11-04T${t}:00+05:30`, unrealized_pnl: g, realized_pnl: 0, gross_pnl: g, net_pnl: g - 175.3, change_since_baseline: g + 500 };
  }),
  missing: [{ position_id: "st-1:1", reason: "MOCK: no candles for NIFTY 25 Nov 25200 CE yet" }],
  basis: "MOCK: Kite 5-minute candles, carried forward where a contract did not trade.", partial: true,
};

interface Seen { pnlQueries: URLSearchParams[]; streamHits: number; tsQueries: URLSearchParams[]; listGets: number }
interface Opts {
  phone?: boolean;
  /** The body (and status) GET /api/desk/pnl answers; default snapshot(query). */
  pnl?: (q: URLSearchParams, n: number) => { status?: number; body: unknown };
  /** What the stream answers: "fail" (503, the default) or one SSE event of this body. */
  stream?: "fail" | { body: unknown; extra?: string };
  timeseries?: { status?: number; body: unknown };
}

async function setup(page: Page, o: Opts = {}): Promise<Seen> {
  const seen: Seen = { pnlQueries: [], streamHits: 0, tsQueries: [], listGets: 0 };
  if (o.phone) await page.setViewportSize({ width: 390, height: 844 });
  await page.route("**/api/**", (r) => json(r, { detail: "MOCK: not mocked in this spec" }, 404));
  await mockApi(page, "populated");
  await mockSingleRoute(page, "**/api/markets/home", "markets-home.json");
  await page.route("**/api/chat/sessions", (r) => json(r, []));
  await page.route("**/api/move-odds/**", (r) => json(r, { detail: "feature_not_enabled" }, 403));
  await page.route("**/api/risk/status", (r) => json(r, { kill_switch: false, halted: false, policy_version: "MOCK" }));
  await page.route("**/api/live/**", (r) => json(r, { available: false, reason: "MOCK: feed off", quotes: {}, mode: "expired", session: "closed", stale: true }));
  await page.route("**/api/desk/alerts*", (r) => json(r, { as_of: "2026-11-03", alerts: [] }));
  await page.route("**/api/desk/paper-trades*", (r) => {
    seen.listGets += 1;
    return json(r, { as_of: "2026-11-03", checked_through: "2026-11-03", trades: [], summary: { open: 0, closed: 0 }, status: "all" });
  });
  await page.route(/\/api\/desk\/pnl(\?|$)/, (r) => {
    const q = new URL(r.request().url()).searchParams;
    seen.pnlQueries.push(q);
    const a = o.pnl ? o.pnl(q, seen.pnlQueries.length) : { body: snapshot(q) };
    return json(r, a.body, a.status ?? 200);
  });
  await page.route(/\/api\/desk\/pnl\/stream(\?|$)/, (r) => {
    seen.streamHits += 1;
    const s = o.stream ?? "fail";
    if (s === "fail") return json(r, { detail: "MOCK: stream unavailable" }, 503);
    // One event, then the response ends; `retry` keeps the browser from reconnecting during the test.
    return r.fulfill({ status: 200, contentType: "text/event-stream", body: `retry: 120000\nevent: snapshot\ndata: ${JSON.stringify(s.body)}\n\n${s.extra ?? ""}` });
  });
  await page.route(/\/api\/desk\/pnl\/timeseries(\?|$)/, (r) => {
    seen.tsQueries.push(new URL(r.request().url()).searchParams);
    const t = o.timeseries ?? { body: TIMESERIES };
    return json(r, t.body, t.status ?? 200);
  });
  return seen;
}

const params = (page: Page) => new URL(page.url()).searchParams;
const BANNED = /\bpick|recommend|suggest/i;

async function noSideScroll(page: Page) {
  const o = await page.evaluate(() => {
    const sc = document.querySelector('[data-testid="copilot-scroll"]') as HTMLElement | null;
    const right = sc ? sc.getBoundingClientRect().right : window.innerWidth;
    const wide = (Array.from(document.querySelectorAll("*")) as HTMLElement[]).filter((el) => {
      const r = el.getBoundingClientRect();
      return r.width > 0 && r.right > right + 1 && !(el.parentElement && el.parentElement.getBoundingClientRect().right > right + 1);
    }).slice(0, 6).map((el) => `${el.tagName.toLowerCase()}[${el.getAttribute("data-testid") ?? ""}] right=${Math.round(el.getBoundingClientRect().right)}`);
    return { doc: document.documentElement.scrollWidth - window.innerWidth, scroll: sc ? sc.scrollWidth - sc.clientWidth : 0, wide: wide.join(", ") };
  });
  expect(o.doc, o.wide).toBeLessThanOrEqual(1);
  expect(o.scroll, o.wide).toBeLessThanOrEqual(1);
}

test.describe("MOCK — not real data: Paper Trading › P&L dashboard", () => {
  test("TC-032 Paper Trading has a third sub-view, P&L dashboard; it opens with sub=pnl and the four-deep crumb, without the paper-trades read", async ({ page }) => {
    const seen = await setup(page);
    await page.goto(`${DESK}?tab=trade&view=paper&sub=live`);
    await expect(page.getByTestId("desk-subviews").getByRole("button")).toHaveText(["Live desk", "Trade journal", "P&L dashboard"], SLOW);
    await page.getByTestId("desk-sub-pnl").click();
    await expect.poll(() => params(page).get("sub")).toBe("pnl");
    await expect(page.getByTestId("desk-trail")).toHaveText(/^▸Trading desk›Trade Desk›Paper Trading›P&L dashboard$/);
    await expect(page.getByTestId("pnl-dashboard")).toBeVisible(SLOW);
    await expect(page.getByTestId("desk-sub-pnl")).toHaveAttribute("aria-pressed", "true");
    // The Live desk's header strip is not repeated here; the dashboard has its own header.
    await expect(page.getByTestId("td-header")).toHaveCount(0);
    // Opened directly, the dashboard does not read GET /api/desk/paper-trades (that route applies exits).
    const before = seen.listGets;
    await page.goto(PNL);
    await expect(page.getByTestId("pnl-kpis")).toBeVisible(SLOW);
    await page.waitForTimeout(1_000);
    expect(seen.listGets).toBe(before);
  });

  test("TC-033 header, KPI cards, segments, positions with the strategy and its legs, waiting entries, alerts, chart", async ({ page }) => {
    const seen = await setup(page);
    await page.goto(PNL);
    await expect(page.getByTestId("pnl-kpis")).toBeVisible(SLOW);
    await expect(page.getByTestId("pnl-mode")).toHaveText("PAPER");
    await expect(page.getByTestId("pnl-feed")).toHaveAttribute("data-feed", "live");
    await expect(page.getByTestId("pnl-live-note")).toContainText("Live broker P&L is not part of this dashboard yet");
    await expect(page.getByTestId("pnl-kpi-net-value")).toHaveText("−₹254.73");
    await expect(page.getByTestId("pnl-kpi-gross-value")).toHaveText("−₹79.43");
    await expect(page.getByTestId("pnl-kpi-charges-booked")).toHaveText("₹0.00");
    await expect(page.getByTestId("pnl-kpi-charges-est")).toHaveText("₹175.30");
    await expect(page.getByTestId("pnl-kpi-unrealized-value")).toHaveText("−₹79.43");
    await expect(page.getByTestId("pnl-kpi-day-value")).toHaveText("+₹546.00");
    await expect(page.getByTestId("pnl-kpi-capital-value")).toHaveText("₹1,00,00,000");
    await expect(page.getByTestId("pnl-kpi-positions-sub")).toContainText("2 in profit · 2 in loss · 1 waiting to open");
    await expect(page.getByTestId("pnl-segment")).toHaveCount(2);
    // Two share rows, one strategy row with its two legs; the legs are not repeated as rows of their own.
    await expect(page.getByTestId("pnl-row")).toHaveCount(2);
    await expect(page.getByTestId("pnl-strategy-row")).toHaveCount(1);
    await expect(page.getByTestId("pnl-leg-row")).toHaveCount(2);
    const icici = page.locator('[data-testid="pnl-row"][data-id="pt-icici"]');
    await expect(icici.getByTestId("pnl-ltp")).toHaveText("₹1,431.50");
    await expect(icici.getByTestId("pnl-price-badge")).toHaveText("LIVE 10:30:01");
    await expect(icici.getByTestId("pnl-row-net")).toHaveText("+₹599.95");
    await expect(icici).toContainText("Long");
    await expect(icici).toContainText("₹1,374.90");
    await expect(icici).toContainText("₹1,489.83");
    const cof = page.locator('[data-testid="pnl-row"][data-id="pt-cof"]');
    await expect(cof.getByTestId("pnl-price-badge")).toHaveAttribute("data-status", "DELAYED");
    await expect(cof.getByTestId("pnl-price-badge")).toHaveText("DELAYED 10:21:40");
    await expect(cof.getByTestId("pnl-status")).toHaveText("Stop loss hit");
    await expect(page.getByTestId("pnl-strategy-net")).toHaveText("+₹1,175.00");
    await expect(page.locator('[data-testid="pnl-leg-row"][data-id="st-1:1"]')).toContainText("Short");
    await expect(page.getByTestId("pnl-shown")).toContainText("Shown: 4 of 4 positions · net −₹254.73");
    await expect(page.getByTestId("pnl-pending")).toHaveText(/HDFCBANK · Break above ₹1,655.00/);
    await expect(page.getByTestId("pnl-alert")).toHaveCount(3);
    // Sorted by severity: critical first.
    await expect(page.getByTestId("pnl-alert").first()).toHaveAttribute("data-severity", "CRITICAL");
    await expect(page.getByTestId("pnl-alert").nth(1)).toHaveAttribute("data-severity", "WARNING");
    await expect(page.getByTestId("pnl-alert").nth(2)).toHaveAttribute("data-severity", "INFO");
    await expect(page.getByTestId("pnl-capital-blocked")).toHaveText("₹1,23,887");
    await expect(page.getByTestId("pnl-stale-positions")).toContainText("2 positions are priced from a delayed quote");
    await expect(page.getByTestId("pnl-display-only")).toHaveText("MOCK: live prices are for display; the ledger decides exits on end-of-day bars.");
    await expect(page.getByTestId("pnl-market-notes")).toHaveCount(0);
    await expect(page.getByTestId("pnl-notes")).not.toContainText("for display");     // shown once, in the header
    await expect(page.getByTestId("pnl-kpi-positions-sub")).toContainText("4 rows with legs");
    await expect(page.getByTestId("pnl-strategy-summary")).toHaveText("Bull call spread 25000/25200 · 25 Nov · 1 lot");
    // A leg priced from the previous session's last trade says which day.
    await expect(page.locator('[data-testid="pnl-leg-row"][data-id="st-1:1"]').getByTestId("pnl-price-badge")).toHaveText("DELAYED 3 Nov 15:29:58");
    await expect(page.getByTestId("pnl-strategies-car")).toHaveText("₹6,375");
    await expect(page.getByTestId("pnl-near-stop")).toContainText("within 1.0%");
    // The chart: a partial curve, the previous-close baseline, the basis line; the interval goes to the route.
    await expect(page.getByTestId("pnl-chart-plot").locator("svg")).toBeVisible();
    await expect(page.getByTestId("pnl-chart-baseline")).toHaveCount(1);
    // The curve's missing position is named by its instrument, not its id.
    await expect(page.getByTestId("pnl-chart-partial")).toContainText("NIFTY 25 Nov 25200 CE: MOCK: no candles");
    await expect(page.getByTestId("pnl-chart-basis")).toContainText("Kite 5-minute candles");
    await page.getByTestId("pnl-interval-15m").click();
    await expect.poll(() => seen.tsQueries.map((q) => q.get("interval"))).toContain("15m");
    await expect(page.getByTestId("pnl-closed-empty")).toBeVisible();
    // TC-040 wording on this screen.
    const text = (await page.getByTestId("pnl-dashboard").innerText());
    expect(text).not.toMatch(BANNED);
    expect(text).not.toMatch(/\b(buy|sell)\b/i);
  });

  test("TC-034 segment and period go to the route; search, profit/loss and status filter the rows", async ({ page }) => {
    const seen = await setup(page);
    await page.goto(PNL);
    await expect(page.getByTestId("pnl-row")).toHaveCount(2, SLOW);
    await page.getByTestId("pnl-segment-options").click();
    await expect.poll(() => seen.pnlQueries.some((q) => q.get("segment") === "OPTIONS")).toBe(true);
    await expect(page.getByTestId("pnl-kpi-net-value")).toHaveText("+₹1,175.00");
    await expect(page.getByTestId("pnl-row")).toHaveCount(0);
    await expect(page.getByTestId("pnl-leg-row")).toHaveCount(2);
    await page.getByTestId("pnl-segment-all").click();
    await expect(page.getByTestId("pnl-row")).toHaveCount(2);
    await page.getByTestId("pnl-period-1w").click();
    await expect.poll(() => seen.pnlQueries.some((q) => q.get("period") === "1W")).toBe(true);
    await expect(page.getByTestId("pnl-closed-row")).toHaveCount(1);
    await expect(page.getByTestId("pnl-closed-net")).toHaveText("−₹3,360.10");
    await expect(page.getByTestId("pnl-kpi-realized-value")).toHaveText("−₹3,200.00");
    await expect(page.getByTestId("pnl-an-avgloss")).toHaveText("−₹3,360.10");
    await expect(page.getByTestId("pnl-daily-bar")).toHaveCount(1);
    // Client-side: search, profit/loss, status.
    await page.getByTestId("pnl-search").fill("cofo");
    await expect(page.getByTestId("pnl-row")).toHaveCount(1);
    await expect(page.getByTestId("pnl-strategy-row")).toHaveCount(0);
    // A filter change shows "Updating for the new filters…": the search and its result survive it (no remount).
    await page.getByTestId("pnl-segment-equity").click();
    await expect.poll(() => seen.pnlQueries.some((q) => q.get("segment") === "EQUITY")).toBe(true);
    await expect(page.getByTestId("pnl-search")).toHaveValue("cofo");
    await expect(page.getByTestId("pnl-row")).toHaveCount(1);
    await page.getByTestId("pnl-segment-all").click();
    await expect(page.getByTestId("pnl-leg-row")).toHaveCount(0);   // still searching "cofo"
    await page.getByTestId("pnl-search").fill("");
    await expect(page.getByTestId("pnl-leg-row")).toHaveCount(2);
    await page.getByTestId("pnl-outcome-profit").click();
    await expect(page.locator('[data-testid="pnl-row"]')).toHaveCount(1);
    await expect(page.locator('[data-testid="pnl-row"][data-id="pt-icici"]')).toHaveCount(1);
    await expect(page.getByTestId("pnl-strategy-row")).toHaveCount(1);
    await page.getByTestId("pnl-outcome-loss").click();
    await expect(page.locator('[data-testid="pnl-row"][data-id="pt-cof"]')).toHaveCount(1);
    await expect(page.getByTestId("pnl-strategy-row")).toHaveCount(0);
    await page.getByTestId("pnl-outcome-all").click();
    await page.getByTestId("pnl-status-filter").selectOption("ATTENTION");
    await expect(page.getByTestId("pnl-row")).toHaveCount(1);
    await expect(page.locator('[data-testid="pnl-row"][data-id="pt-cof"]')).toHaveCount(1);
    await page.getByTestId("pnl-status-filter").selectOption("ALL");
    // Sort: net low to high puts COFORGE first.
    await page.getByTestId("pnl-sort").selectOption("net-asc");
    await expect(page.locator('[data-testid="pnl-row"], [data-testid="pnl-strategy-row"]').first()).toHaveAttribute("data-id", "pt-cof");
    await page.getByTestId("pnl-sort").selectOption("net-desc");
    await expect(page.locator('[data-testid="pnl-row"], [data-testid="pnl-strategy-row"]').first()).toHaveAttribute("data-id", "st-1");
  });

  test("TC-035 a row expands to its fills; a leg too", async ({ page }) => {
    await setup(page);
    await page.goto(PNL);
    const icici = page.locator('[data-testid="pnl-row"][data-id="pt-icici"]');
    await expect(icici).toBeVisible(SLOW);
    await icici.getByTestId("pnl-expand").click();
    const detail = page.locator('[data-testid="pnl-row-detail"][data-id="pt-icici"]');
    await expect(detail.getByTestId("pnl-execution")).toHaveText(/^Opened \+35 @ ₹1,413\.21/);
    await expect(icici.getByTestId("pnl-expand")).toHaveAttribute("aria-expanded", "true");
    const leg = page.locator('[data-testid="pnl-leg-row"][data-id="st-1:1"]');
    await leg.getByTestId("pnl-expand").click();
    await expect(page.locator('[data-testid="pnl-row-detail"][data-id="st-1:1"]').getByTestId("pnl-execution")).toHaveText(/^Opened −75 @ ₹95\.00/);
    await icici.getByTestId("pnl-expand").click();
    await expect(detail).toHaveCount(0);
  });

  test("TC-036 CSV export: one line per shown position or leg, never a strategy total; follows the filters", async ({ page }) => {
    await setup(page);
    await page.goto(PNL);
    await expect(page.getByTestId("pnl-row")).toHaveCount(2, SLOW);
    const read = async () => {
      const [dl] = await Promise.all([page.waitForEvent("download"), page.getByTestId("pnl-export").click()]);
      expect(dl.suggestedFilename()).toBe("paper-pnl-positions-2026-11-04.csv");
      return fs.readFileSync((await dl.path()) as string, "utf-8").trim().split("\n");
    };
    const all = await read();
    expect(all[0]).toMatch(/^mode,account,instrument,strategy,segment,side,net_quantity,avg_price,ltp,price_status/);
    expect(all).toHaveLength(5);
    const icici = all.find((l) => l.includes("ICICIBANK")) as string;
    expect(icici).toContain(",599.95,");
    expect(icici).toContain(",LIVE,");
    expect(all.filter((l) => l.includes("Bull call spread"))).toHaveLength(2);
    // A null stays empty in the CSV, never 0 (the legs have no stop loss).
    expect(all.find((l) => l.includes("st-1:1"))).toMatch(/,-1915,[^,]*,,,/);
    await page.getByTestId("pnl-search").fill("NIFTY");
    const legs = await read();
    expect(legs).toHaveLength(3);
  });

  test("TC-037 the stream fails → polling; a newer snapshot updates the rows, an older one is dropped; the stream path delivers too", async ({ page }) => {
    let ltp = 1431.5, seq = 1762232401000;
    const seen = await setup(page, {
      pnl: (q) => ({ body: snapshot(q, seq, (s) => { (s.positions as Array<Record<string, unknown>>)[0].ltp = ltp; }) }),
    });
    await page.goto(PNL);
    const icici = page.locator('[data-testid="pnl-row"][data-id="pt-icici"]');
    await expect(icici.getByTestId("pnl-ltp")).toHaveText("₹1,431.50", SLOW);
    await expect(page.getByTestId("pnl-connection")).toHaveAttribute("data-state", "polling");
    await expect(page.getByTestId("pnl-connection")).toHaveText("Polling every 3 s");
    expect(seen.streamHits).toBeGreaterThan(0);
    // A newer snapshot (higher sequence): the screen follows within a poll.
    ltp = 1440; seq += 3000;
    await expect(icici.getByTestId("pnl-ltp")).toHaveText("₹1,440.00", { timeout: 10_000 });
    // An older one (a late or replayed answer): dropped; the screen keeps the newer figure.
    ltp = 1300; seq -= 10_000;
    const polls = seen.pnlQueries.length;
    await expect.poll(() => seen.pnlQueries.length, { timeout: 10_000 }).toBeGreaterThan(polls + 1);
    await expect(icici.getByTestId("pnl-ltp")).toHaveText("₹1,440.00");
    await expect(page.getByTestId("pnl-updated")).toContainText("updated");

    // The stream answering: the snapshot arrives over SSE (data-transport sse), with no poll needed.
    const p2 = await page.context().newPage();
    const seen2 = await setup(p2, { stream: { body: snapshot(new URLSearchParams("segment=ALL&period=TODAY"), 1762232409000) } });
    await p2.goto(PNL);
    await expect(p2.getByTestId("pnl-kpi-net-value")).toHaveText("−₹254.73", SLOW);
    await expect(p2.getByTestId("pnl-connection")).toHaveAttribute("data-transport", "sse");
    expect(seen2.streamHits).toBeGreaterThan(0);
    expect(seen2.pnlQueries.length).toBe(0);
    await p2.close();
  });

  test("TC-038 390 px: summary first, position cards instead of the table, cards expand; no sideways scroll", async ({ page }) => {
    await setup(page, { phone: true });
    await page.goto(PNL);
    await expect(page.getByTestId("pnl-dashboard")).toHaveAttribute("data-narrow", "true", SLOW);
    await expect(page.getByTestId("pnl-table")).toHaveCount(0);
    await expect(page.getByTestId("pnl-card")).toHaveCount(2);
    await expect(page.getByTestId("pnl-strategy-card")).toHaveCount(1);
    await expect(page.getByTestId("pnl-leg-card")).toHaveCount(2);
    // Spec §3.2: the net P&L summary comes before the filters on a phone.
    const order = await page.evaluate(() => {
      const y = (id: string) => (document.querySelector(`[data-testid="${id}"]`) as HTMLElement).getBoundingClientRect().top;
      return { kpis: y("pnl-kpis"), filters: y("pnl-filters"), positions: y("pnl-positions"), risk: y("pnl-risk"), chart: y("pnl-chart") };
    });
    expect(order.kpis).toBeLessThan(order.filters);
    expect(order.positions).toBeLessThan(order.risk);
    expect(order.risk).toBeLessThan(order.chart);
    const card = page.locator('[data-testid="pnl-card"][data-id="pt-icici"]');
    await card.getByTestId("pnl-expand").click();
    await expect(card.getByTestId("pnl-execution")).toHaveText(/^Opened \+35/);
    await expect(card.getByTestId("pnl-ltp")).toHaveText("₹1,431.50");
    await noSideScroll(page);
  });

  test("TC-039 the route fails: a problem with Retry, no figures; a missing price is said, never 0", async ({ page }) => {
    let fail = true;
    await setup(page, {
      pnl: (q) => (fail ? { status: 500, body: { detail: "MOCK: down" } }
        : { body: snapshot(q, 1762232401000, (s) => {
          const p = (s.positions as Array<Record<string, unknown>>)[0];
          Object.assign(p, { ltp: null, price_status: "MISSING", price_at: null, unrealized_pnl: null, gross_pnl: null, net_pnl: null, charges_estimated: null });
          Object.assign(s.summary as Record<string, unknown>, { unpriced_positions: 1, complete: false });
        }) }),
    });
    await page.goto(PNL);
    await expect(page.getByTestId("pnl-error")).toBeVisible(SLOW);
    await expect(page.getByTestId("pnl-kpis")).toHaveCount(0);
    await expect(page.getByTestId("pnl-connection")).toHaveAttribute("data-state", "error");
    fail = false;
    await page.getByTestId("pnl-error").getByRole("button").first().click();
    await expect(page.getByTestId("pnl-kpis")).toBeVisible(SLOW);
    const icici = page.locator('[data-testid="pnl-row"][data-id="pt-icici"]');
    await expect(icici.getByTestId("pnl-price-badge")).toHaveText("NO PRICE");
    await expect(icici.getByTestId("pnl-ltp")).toHaveText("—");
    await expect(icici.getByTestId("pnl-row-net")).toHaveText("—");
    await expect(page.getByTestId("pnl-incomplete")).toContainText("1 open position has no price");
    await expect(page.getByTestId("pnl-shown")).toContainText("net —");
  });

  test("TC-033b a structure with a share leg stays one group; a leg without a price makes the structure's total unknown; route notes", async ({ page }) => {
    // MOCK — not real data: a protective put (shares + a put) whose put has no price, a market note, a marks error, a partial closed list.
    const SHARES = pos({ position_id: "pp-1:0", trade_id: "pp-1", leg_index: 0, strategy_id: "pp-1", strategy_name: "Protective put", instrument: "MOCKPHARMA",
      symbol: "MOCKPHARMA", underlying: "MOCKPHARMA", segment: "EQUITY", side: "LONG", net_quantity: 250, avg_price: 1200, ltp: 1210, price_status: "LIVE",
      price_source: "Kite live", price_at: "2026-11-04T10:30:00+05:30", invested_value: 300000, unrealized_pnl: 2500, gross_pnl: 2500, charges_estimated: 300,
      net_pnl: 2200, day_pnl: 500, return_pct: 0.73, stop_loss: null, target: null, distance_to_stop_pct: null, status: "ACTIVE", executions: [] });
    const PUT = pos({ position_id: "pp-1:1", trade_id: "pp-1", leg_index: 1, strategy_id: "pp-1", strategy_name: "Protective put", instrument: "MOCKPHARMA 25 Nov 1160 PE",
      symbol: "MOCKPHARMA25NOV1160PE", underlying: "MOCKPHARMA", segment: "OPTIONS", side: "LONG", net_quantity: 250, lots: 1, lot_size: 250, avg_price: 18,
      ltp: null, prev_close: null, price_status: "MISSING", price_source: null, price_at: null, price_day: null, invested_value: 4500, unrealized_pnl: null,
      gross_pnl: null, charges_estimated: null, net_pnl: null, day_pnl: null, return_pct: null, stop_loss: null, target: null, distance_to_stop_pct: null, status: "ACTIVE", executions: [] });
    await setup(page, {
      pnl: (q) => ({ body: snapshot(q, 1762232401000, (s) => {
        s.positions = [ICICI, SHARES, PUT].map(clone);
        s.strategies = [{ strategy_id: "pp-1", name: "Protective put", summary: "Protective put 1160 · 25 Nov · mixed lots", underlying: "MOCKPHARMA", direction: "bullish",
          status: "ACTIVE", legs: ["pp-1:0", "pp-1:1"], underlying_ltp: 1210, stop_underlying: null, target_underlying: null, entry_net_premium: -4500,
          current_value: null, unrealized_pnl: null, charges_estimated: null, net_pnl: null, capital_at_risk: 14500, complete: false, opened_at: "2026-11-02T04:00:00+00:00",
          risk_note: "MOCK: the shares carry the loss above the put's strike." }];
        Object.assign(s.summary as Record<string, unknown>, { open_positions: 2, open_legs: 3, unpriced_positions: 1, complete: false });
        (s.market as Record<string, unknown>).notes = ["MOCK: no Kite session for the platform today: futures and options are priced at end of day."];
        s.marks_error = "prices_partially_unavailable";
        s.closed = [CLOSED]; s.closed_total = 7; s.closed_partial = true;
      }) }),
    });
    await page.goto(PNL);
    await expect(page.getByTestId("pnl-strategy-row")).toHaveCount(1, SLOW);
    // The share leg is a leg of the structure, not a share row of its own.
    await expect(page.getByTestId("pnl-row")).toHaveCount(1);
    await expect(page.locator('[data-testid="pnl-leg-row"][data-id="pp-1:0"]')).toHaveCount(1);
    await expect(page.locator('[data-testid="pnl-leg-row"][data-id="pp-1:1"]').getByTestId("pnl-price-badge")).toHaveText("NO PRICE");
    await expect(page.getByTestId("pnl-strategy-net")).toHaveText("—");
    await expect(page.getByTestId("pnl-strategy-row").getByTestId("pnl-status")).toHaveText("A leg has no price");
    await expect(page.getByTestId("pnl-strategy-summary")).toHaveText("Protective put 1160 · 25 Nov · mixed lots");
    await expect(page.getByTestId("pnl-market-notes")).toHaveText("MOCK: no Kite session for the platform today: futures and options are priced at end of day.");
    await expect(page.getByTestId("pnl-marks-error")).toContainText("prices_partially_unavailable");
    await expect(page.getByTestId("pnl-incomplete")).toContainText("1 open position has no price");
    await expect(page.getByTestId("pnl-closed-partial")).toHaveText("Showing the newest 1 of 7 closed trades in this period.");
    // Profit / loss filters never count an unknown total as either.
    await page.getByTestId("pnl-outcome-profit").click();
    await expect(page.getByTestId("pnl-strategy-row")).toHaveCount(0);
    await page.getByTestId("pnl-outcome-loss").click();
    await expect(page.getByTestId("pnl-strategy-row")).toHaveCount(0);
  });

  test("TC-037b the stream's problem event: the last snapshot stays, with a quiet warning", async ({ page }) => {
    const body = snapshot(new URLSearchParams("segment=ALL&period=TODAY"), 1762232409000);
    await setup(page, { stream: { body, extra: `event: problem\ndata: ${JSON.stringify({ error: "MOCK: one pass failed", kind: "prices" })}\n\n` } });
    await page.goto(PNL);
    await expect(page.getByTestId("pnl-stream-problem")).toContainText("MOCK: one pass failed", SLOW);
    await expect(page.getByTestId("pnl-kpi-net-value")).toHaveText("−₹254.73");
    await expect(page.getByTestId("pnl-error")).toHaveCount(0);
  });

  test("TC-039b a contract error (no positions list) is a problem, not an empty dashboard", async ({ page }) => {
    await setup(page, { pnl: () => ({ body: { summary: {} } }) });
    await page.goto(PNL);
    await expect(page.getByTestId("pnl-error")).toBeVisible(SLOW);
    await expect(page.getByTestId("pnl-error")).toContainText("unexpected response shape");
  });
});
