/**
 * One-screen Copilot app (/v5/app) — Smart trading desk, Market Desk › Screener › Scan dashboard
 * (screens/tradingdesk/tabs/market-desk/scan-dashboard/; contract docs/scan_builder/DESIGN.md §8). Cases TC-DE1 … TC-DE7 of
 * test_reports/scan_builder_20261103_0431.md, for the simple realtime dashboard; TC-DE10 the strategy idea column (3 Nov).
 *
 * MOCK — not real data. Every /api/scan-builder/market-dashboard answer below is hand-written to the contract: invented
 * symbols (ALPHA, BETA, GAMMA, DELTA), invented prices, invented index levels. Nothing here is market data; the expected text is
 * worked out from these fixtures, not copied from the screen. Production build, every /api mocked — see pw.copilot-app.config.ts.
 */
import { test, expect, type Page, type Route } from "@playwright/test";
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";
import { mockApi, mockSingleRoute } from "../helpers/api-mock";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const load = (name: string) => JSON.parse(fs.readFileSync(path.join(__dirname, "..", "fixtures", name), "utf-8"));

const DESK = "/v5/app/trader/desk";
const SCREENER = `${DESK}?tab=market&view=screener`;
const DASH = `${SCREENER}&sub=dashboard`;
const SLOW = { timeout: 15_000 };
const reply = (route: Route, body: unknown, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
const params = (page: Page) => new URL(page.url()).searchParams;

// ── MOCK — not real data: one dashboard answer ───────────────────────────────────────────────────────────────────────

const C = (text: string, o: { level?: number; applied?: boolean; note?: string } = {}) => ({ text, level: o.level ?? 0, applied: o.applied ?? true, note: o.note ?? null });
const STD_COLS = [
  { key: "symbol", label: "Symbol", format: "text" },
  { key: "chg", label: "% Change", format: "pct" },
  { key: "price", label: "Price", format: "price" },
  { key: "volume", label: "Volume", format: "volume" },
];

// MOCK — not real data: strategy ideas for the invented symbols. ALPHA and DELTA have one, BETA has none with a favorable
// reward : risk (null), GAMMA is still being built (no key).
const IDEAS = {
  ALPHA: { structure: "Bull call spread", family: "debit_spread", horizon: "1–3 weeks", reward_risk: 2.1, max_loss_inr: 12500,
           capital_at_risk_inr: 12500, legs_text: "NOV 820 CE / 860 CE", data_as_of: "2026-11-02" },
  BETA: null,
  DELTA: { structure: "Cash", family: "cash", horizon: "2–6 weeks", reward_risk: 1.6, max_loss_inr: 4100,
           capital_at_risk_inr: 41025, legs_text: "Cash, 100 shares", data_as_of: "2026-11-02" },
};
const IDEAS_META = { built: 3, pending: 1, note: "MOCK note: net reward : risk under the desk's rules.", source: "MOCK strategy builder", as_of: "2026-11-03T04:45:00Z" };

function dashboard(o: { open?: boolean; bump?: number; warnings?: string[]; ideas?: boolean } = {}) {
  const bump = o.bump ?? 0;
  return {
    ...(o.ideas === false ? {} : { ideas: IDEAS, ideas_meta: IDEAS_META }),
    ok: true,
    run_at: "2026-11-03T04:45:30Z",                      // 10:15:30 IST
    elapsed_ms: 640,
    cached: false,
    basis: { mode: o.open === false ? "kite_close" : "live", day: "2026-11-03", eod_date: "2026-11-02", quote_as_of: "2026-11-03T04:45:29Z", text: "MOCK basis — Kite live 10:15:29 IST over NSE end-of-day bars to 02 Nov 2026" },
    market: { open: o.open !== false, refresh_seconds: 10 },
    counts: { cash: 2714, fno: 218, nifty50: 50, no_today_bar: 12 },
    sources: { prices: "MOCK prices source", today: "MOCK today source", fundamentals: "MOCK fundamentals source" },
    warnings: o.warnings ?? ["12 stocks had no live quote and are left out."],
    widgets: [
      {
        id: "mcap_ad", chartink_id: "3072994", title: "Marketcap Advances % / Declines", universe: "All NSE stocks", status: "ok", note: null,
        criteria: [
          C("Universe: All NSE stocks"),
          C("Grouped by market cap: rank 1–100 Largecap, 101–250 Midcap, 251+ Smallcap"),
          C("Advances = % of stocks with Close > 1 day ago Close"),
          C("Declines = % of stocks with Close < 1 day ago Close"),
        ],
        columns: [{ key: "group", label: "Marketcap", format: "text" }, { key: "adv", label: "Advances", format: "pct" }, { key: "dec", label: "Declines", format: "pct" }],
        rows: [["Midcap", 61.5, 37.25], ["Largecap", 55, 43], ["Smallcap", 48.25, 50.1]],
        row_kind: "group", count: 3, as_of: null,
      },
      {
        id: "index_stats", chartink_id: "3073022", title: "Index stats", universe: "Indices", status: "ok", note: null,
        criteria: [C("NIFTY 50 and NIFTY BANK: last price and % change against the previous close (Kite)")],
        columns: [{ key: "symbol", label: "Symbol", format: "text" }, { key: "ltp", label: "Ltp", format: "price" }, { key: "chg", label: "% chg", format: "pct" }],
        rows: [["BANKNIFTY", 50100.5, -0.42], ["NIFTY", 21000.25, 0.35]],
        row_kind: "index", count: 2, as_of: "2026-11-03T04:45:29Z",
      },
      {
        id: "n50_gainers", chartink_id: "2556934", title: "Nifty 50 Top Gainers", universe: "Nifty 50", status: "partial",
        note: "MOCK note: the two 15-minute conditions are not applied yet.",
        criteria: [
          C("Universe: Nifty 50"),
          C("Open > 1 day ago Close"),
          C("Close > 15 minute High of the first candle", { applied: false, note: "needs 15-minute candles" }),
          C("Volume > 200,000"),
          C("Close > 15 minute EMA(close, 21)", { applied: false, note: "needs 15-minute candles" }),
          C("RSI(14) > 55"),
        ],
        columns: STD_COLS,
        rows: [["ALPHA", 4.2, 812.5 + bump, 3250000], ["BETA", 1.1, 1999.95, 120000], ["GAMMA", -0.5, 55.1, null]],
        row_kind: "symbol", count: 3, as_of: null,
      },
      {
        id: "oi_any", chartink_id: "3044849", title: "Open interest", universe: "F&O stocks", status: "ok", note: null,
        criteria: [
          C("Universe: F&O stocks"),
          C("Volume > EMA(close, 10) × 5"),
          C("Any of:"),
          C("Close > 1 day ago Close × 1.05", { level: 1 }),
          C("Close < 1 day ago Close × 0.95", { level: 1 }),
        ],
        columns: STD_COLS,
        rows: [["DELTA", 6.1, 410.25, 2500000]],
        row_kind: "symbol", count: 1, as_of: null,
      },
      {
        id: "oi_7", chartink_id: "2854924", title: "Open interest 7", universe: "F&O stocks", status: "ok", note: null,
        criteria: [C("Universe: F&O stocks"), C("Volume > EMA(close, 8) × 5")],
        columns: STD_COLS, rows: [], row_kind: "symbol", count: 0, as_of: null,
      },
      {
        id: "good_results", chartink_id: "2737396", title: "Good quarter result stocks", universe: "All NSE stocks", status: "pending",
        note: "MOCK note: company results are loading (the first load of the day takes about a minute).",
        criteria: [C("Universe: All NSE stocks"), C("Net profit, latest quarter > Net profit, 1 quarter ago")],
        columns: STD_COLS, rows: [], row_kind: "symbol", count: null, as_of: null,
      },
      {
        id: "vol_10x_5min", chartink_id: "2653943", title: "10x volume first 5 min", universe: "All NSE stocks", status: "not_computed",
        note: "MOCK note: needs the count of trades initiated at the ask and at the bid, which no feed of ours carries.",
        criteria: [
          C("Universe: All NSE stocks"),
          C("5 minute Volume of the first candle > previous 5 minute SMA(volume, 1000) × 10", { applied: false, note: "needs 5-minute candles" }),
        ],
        columns: STD_COLS, rows: [], row_kind: "symbol", count: null, as_of: null,
      },
      {
        id: "triple_bottom", chartink_id: "2894893", title: "Triple bottom", universe: "F&O stocks", status: "error",
        note: "MOCK note: this widget could not be computed just now; it retries on the next refresh.",
        criteria: [C("Universe: F&O stocks"), C("RSI(14) > 50")],
        columns: STD_COLS, rows: [], row_kind: "symbol", count: 0, as_of: null,
      },
    ],
  };
}

// ── the mocked desk ──────────────────────────────────────────────────────────────────────────────────────────────────

interface Backend { calls: string[]; answer: (n: number) => { status: number; body: unknown } }

async function desk(page: Page, o: { flag?: boolean; answer?: Backend["answer"] } = {}): Promise<Backend> {
  const be: Backend = { calls: [], answer: o.answer ?? (() => ({ status: 200, body: dashboard() })) };
  await mockApi(page, "populated");
  await mockSingleRoute(page, "**/api/markets/home", "markets-home.json");
  await page.route("**/api/chat/sessions", (r) => reply(r, []));
  await page.route("**/api/move-odds/**", (r) => reply(r, { detail: "feature_not_enabled" }, 403));
  const base = load("user-profile-onboarded.json");
  await page.route("**/api/auth/me", (r) => reply(r, { ...base, features: { ...(base.features ?? {}), scan_builder: o.flag !== false } }));
  await page.route(/\/api\/scan-builder\//, async (r) => {
    const req = r.request();
    const p = new URL(req.url()).pathname.replace(/^.*\/api\/scan-builder/, "");
    be.calls.push(`${req.method()} ${p}`);
    if (p === "/market-dashboard" && req.method() === "GET") {
      const a = be.answer(be.calls.filter((c) => c === "GET /market-dashboard").length);
      return reply(r, a.body, a.status);
    }
    return reply(r, { detail: { code: "unexpected", message: `unmocked ${req.method()} ${p}` } }, 500);
  });
  return be;
}

const dashCalls = (be: Backend) => be.calls.filter((c) => c === "GET /market-dashboard").length;
const widget = (page: Page, id: string) => page.getByTestId(`sd-widget-${id}`);

async function openDashboard(page: Page) {
  await page.goto(DASH);
  await expect(page.getByTestId("scan-dashboard")).toBeVisible(SLOW);
}

test.describe("MOCK — not real data: Market Desk › Screener › Scan dashboard", () => {
  test("TC-DE1a with the flag off only the Screener is offered (no switcher), and the dashboard URL asks nothing", async ({ page }) => {
    const be = await desk(page, { flag: false });
    await page.goto(SCREENER);
    await expect(page.getByTestId("desk-panel-screener")).toBeAttached(SLOW);
    await expect(page.getByTestId("desk-subviews")).toHaveCount(0);
    await expect(page.getByTestId("desk-sub-dashboard")).toHaveCount(0);
    await page.goto(DASH);
    await expect(page.getByTestId("sd-off")).toContainText("not enabled for your account", SLOW);
    await expect(page.getByTestId("scan-dashboard")).toHaveCount(0);
    expect(be.calls).toEqual([]);
  });

  test("TC-DE1b with the flag on the Screener has three sub-views; Scan dashboard opens from the switcher", async ({ page }) => {
    const be = await desk(page);
    await page.goto(SCREENER);
    await expect(page.getByTestId("desk-subviews")).toBeVisible(SLOW);
    await expect.poll(() => params(page).get("sub")).toBe("screens");
    const keys = await page.getByTestId("desk-subviews").locator("button").evaluateAll((els) => els.map((e) => e.getAttribute("data-testid")));
    expect(keys).toEqual(["desk-sub-screens", "desk-sub-dashboard", "desk-sub-builder"]);
    await expect(page.getByTestId("desk-subviews").getByRole("button")).toHaveText(["Screener", "Scan dashboard", "Scan builder"]);
    await expect(page.getByTestId("desk-panel-screener")).toBeAttached(SLOW);
    // the Market Desk views themselves: the Screener is still the last one, no separate Scan Builder view
    await expect(page.getByTestId("desk-views").getByRole("button")).toHaveText(["Market Intelligence", "Smart Money", "Sector Rotation", "Stock Research", "Screener"]);
    expect(dashCalls(be)).toBe(0);
    await page.getByTestId("desk-sub-dashboard").click();
    await expect.poll(() => params(page).get("sub")).toBe("dashboard");
    await expect(page.getByTestId("md-eyebrow")).toHaveText("Market Desk · Screener · Scan dashboard");
    await expect(page.getByTestId("scan-dashboard")).toBeVisible(SLOW);
    await expect(page.getByTestId("desk-sub-dashboard")).toHaveAttribute("aria-pressed", "true");
    expect(dashCalls(be)).toBe(1);
  });

  test("TC-DE1c the old Scan Builder URL lands on Screener › Scan builder and keeps the open scan", async ({ page }) => {
    await desk(page);
    await page.goto(`${DESK}?tab=market&view=scanbuilder&scan=s9`);
    await expect.poll(() => params(page).get("view"), SLOW).toBe("screener");
    expect(params(page).get("sub")).toBe("builder");
    expect(params(page).get("scan")).toBe("s9");
    await expect(page.getByTestId("desk-panel-scanbuilder")).toBeAttached(SLOW);
    await expect(page.getByTestId("md-eyebrow")).toHaveText("Market Desk · Screener · Scan builder");
  });

  test("TC-DE2 the cards: titles, criteria, statuses, rows and formats; the header's basis, counts and warnings", async ({ page }) => {
    await desk(page, { answer: () => ({ status: 200, body: dashboard({ warnings: ["W1 MOCK", "W2 MOCK", "W3 MOCK", "W4 MOCK"] }) }) });
    await openDashboard(page);
    // header
    await expect(page.getByTestId("sd-basis")).toHaveText("MOCK basis — Kite live 10:15:29 IST over NSE end-of-day bars to 02 Nov 2026");
    await expect(page.getByTestId("sd-updated")).toContainText("Updated 10:15:30 IST");
    await expect(page.getByTestId("sd-counts")).toHaveText("All NSE stocks 2,714 · F&O 218 · Nifty 50 50 · 12 without today’s candle (left out)");
    await expect(page.getByTestId("sd-warning")).toHaveCount(3);
    await page.getByTestId("sd-warnings-toggle").click();
    await expect(page.getByTestId("sd-warning")).toHaveCount(4);
    // every card, in the server's order
    const titles = page.getByTestId("sd-widget-title");
    await expect(titles).toHaveText(["Marketcap Advances % / Declines", "Index stats", "Nifty 50 Top Gainers", "Open interest", "Open interest 7", "Good quarter result stocks", "10x volume first 5 min", "Triple bottom"]);
    // a group widget: plain rows, no links, no stock count
    const ad = widget(page, "mcap_ad");
    await expect(ad.getByTestId("sd-row")).toHaveCount(3);
    await expect(ad.getByTestId("sd-sym")).toHaveCount(0);
    await expect(ad.getByTestId("sd-widget-count")).toHaveCount(0);
    await expect(ad.getByTestId("sd-row").nth(0)).toContainText("Midcap");
    await expect(ad.getByTestId("sd-row").nth(0)).toContainText("61.50%");
    await expect(ad.getByTestId("sd-criterion")).toHaveCount(4);
    // an index widget: plain rows, its own as-of
    const ix = widget(page, "index_stats");
    await expect(ix.getByTestId("sd-sym")).toHaveCount(0);
    await expect(ix.getByTestId("sd-row").nth(0)).toContainText("BANKNIFTY");
    await expect(ix.getByTestId("sd-row").nth(0)).toContainText("50,100.50");
    await expect(ix.getByTestId("sd-row").nth(0)).toContainText("-0.42%");
    await expect(ix.getByTestId("sd-widget-meta")).toContainText("as of 10:15:29 IST");
    // a partial widget: the badge, its note, and the criteria it could not apply dimmed with the reason
    const n50 = widget(page, "n50_gainers");
    await expect(n50).toHaveAttribute("data-status", "partial");
    await expect(n50.getByTestId("sd-widget-status")).toHaveText("Partial");
    await expect(n50.getByTestId("sd-widget-note")).toHaveText("MOCK note: the two 15-minute conditions are not applied yet.");
    await expect(n50.getByTestId("sd-widget-count")).toHaveText("3 stocks");
    await expect(n50.getByTestId("sd-criterion")).toHaveCount(6);
    await expect(n50.locator('[data-testid="sd-criterion"][data-applied="false"]')).toHaveCount(2);
    await expect(n50.locator('[data-testid="sd-criterion"][data-applied="false"]').nth(0)).toContainText("Close > 15 minute High of the first candle");
    await expect(n50.getByTestId("sd-criterion-note").nth(0)).toContainText("not applied — needs 15-minute candles");
    // rows: the server's order, formats, symbol links, missing values
    const rows = n50.getByTestId("sd-row");
    await expect(rows).toHaveCount(3);
    await expect(rows.nth(0)).toHaveAttribute("data-key", "ALPHA");
    await expect(rows.nth(0)).toContainText("4.20%");
    await expect(rows.nth(0)).toContainText("812.50");
    await expect(rows.nth(0)).toContainText("32,50,000");
    await expect(rows.nth(1)).toContainText("1,999.95");
    await expect(rows.nth(2)).toContainText("-0.50%");
    await expect(rows.nth(2).locator("td").nth(3)).toHaveText("–");
    await expect(n50.getByTestId("sd-sym").nth(0)).toHaveText("ALPHA ↗");
    // the first % column is coloured by sign: mint up, danger down
    const upColor = await rows.nth(0).locator("td").nth(1).evaluate((el) => getComputedStyle(el).color);
    const downColor = await rows.nth(2).locator("td").nth(1).evaluate((el) => getComputedStyle(el).color);
    expect(upColor).not.toBe(downColor);
    // nested criteria are indented
    const oi = widget(page, "oi_any");
    const pad = await oi.getByTestId("sd-criterion").nth(3).evaluate((el) => getComputedStyle(el).paddingLeft);
    expect(pad).toBe("14px");
    await expect(oi.getByTestId("sd-widget-count")).toHaveText("1 stock");
    // an empty widget, a pending one and a not computed one
    await expect(widget(page, "oi_7").getByTestId("sd-widget-empty")).toHaveText("No stock passes right now.");
    await expect(widget(page, "oi_7").getByTestId("sd-widget-count")).toHaveText("0 stocks");
    const pend = widget(page, "good_results");
    await expect(pend.getByTestId("sd-widget-status")).toHaveText("Pending");
    await expect(pend.getByTestId("sd-widget-note")).toHaveText("MOCK note: company results are loading (the first load of the day takes about a minute).");
    await expect(pend.getByTestId("sd-table")).toHaveCount(0);
    const nc = widget(page, "vol_10x_5min");
    await expect(nc.getByTestId("sd-widget-status")).toHaveText("Not computed");
    await expect(nc.getByTestId("sd-widget-note")).toHaveText("MOCK note: needs the count of trades initiated at the ask and at the bid, which no feed of ours carries.");
    await expect(nc.getByTestId("sd-table")).toHaveCount(0);
    await expect(nc.locator('[data-testid="sd-criterion"][data-applied="false"]')).toHaveCount(1);
  });

  test("TC-DE3 a header click sorts the card's rows, a second click reverses, missing values stay last", async ({ page }) => {
    await desk(page);
    await openDashboard(page);
    const n50 = widget(page, "n50_gainers");
    const rows = n50.getByTestId("sd-row");
    await n50.getByTestId("sd-sort-price").click();
    await expect(n50.locator("th", { has: page.getByTestId("sd-sort-price") })).toHaveAttribute("aria-sort", "descending");
    await expect(rows.nth(0)).toHaveAttribute("data-key", "BETA");
    await expect(rows.nth(2)).toHaveAttribute("data-key", "GAMMA");
    await n50.getByTestId("sd-sort-price").click();
    await expect(n50.locator("th", { has: page.getByTestId("sd-sort-price") })).toHaveAttribute("aria-sort", "ascending");
    await expect(rows.nth(0)).toHaveAttribute("data-key", "GAMMA");
    await expect(rows.nth(2)).toHaveAttribute("data-key", "BETA");
    // GAMMA has no volume: last whichever way
    await n50.getByTestId("sd-sort-volume").click();
    await expect(rows.nth(0)).toHaveAttribute("data-key", "ALPHA");
    await expect(rows.nth(2)).toHaveAttribute("data-key", "GAMMA");
    await n50.getByTestId("sd-sort-volume").click();
    await expect(rows.nth(0)).toHaveAttribute("data-key", "BETA");
    await expect(rows.nth(2)).toHaveAttribute("data-key", "GAMMA");
    // text columns sort A→Z first
    await n50.getByTestId("sd-sort-symbol").click();
    await expect(rows.nth(0)).toHaveAttribute("data-key", "ALPHA");
    await expect(rows.nth(2)).toHaveAttribute("data-key", "GAMMA");
  });

  test("TC-DE4 a symbol opens Trade Desk › Chart Analysis for it; the link also carries the chart URL for a new tab", async ({ page }) => {
    await desk(page);
    await openDashboard(page);
    const link = widget(page, "n50_gainers").getByTestId("sd-sym").nth(0);
    await expect(link).toHaveAttribute("href", "/v5/app/trader/desk?tab=trade&view=chart&sub=live&sym=ALPHA");
    await link.click();
    await expect.poll(() => params(page).get("tab"), SLOW).toBe("trade");
    expect(params(page).get("view")).toBe("chart");
    expect(params(page).get("sub")).toBe("live");
    expect(params(page).get("sym")).toBe("ALPHA");
  });

  test("TC-DE9 a widget that could not be computed says so and shows no empty table", async ({ page }) => {
    await desk(page);
    await openDashboard(page);
    const w = widget(page, "triple_bottom");
    await expect(w).toHaveAttribute("data-status", "error");
    await expect(w.getByTestId("sd-widget-status")).toHaveText("Unavailable");
    await expect(w.getByTestId("sd-widget-note")).toContainText("could not be computed just now");
    await expect(w.getByTestId("sd-widget-empty")).toHaveCount(0);
    await expect(w.getByTestId("sd-criteria")).toBeVisible();
  });

  test("TC-DE5 while the market is open the dashboard is asked again every 10 s and the new numbers are shown", async ({ page }) => {
    await page.clock.install({ time: new Date("2026-11-03T04:45:00Z") });
    const be = await desk(page, { answer: (n) => ({ status: 200, body: dashboard({ bump: n }) }) });
    await openDashboard(page);
    expect(dashCalls(be)).toBe(1);
    await expect(page.getByTestId("sd-live-chip")).toHaveAttribute("data-state", "live");
    await expect(page.getByTestId("sd-live-chip")).toHaveText("Live · every 10 s");
    const first = widget(page, "n50_gainers").getByTestId("sd-row").nth(0);
    await expect(first).toContainText("813.50");                                // 812.5 + bump 1
    await page.clock.runFor(10_500);
    await expect.poll(() => dashCalls(be), SLOW).toBe(2);
    await expect(first).toContainText("814.50", SLOW);                          // the refreshed answer is on screen
    await page.clock.runFor(10_500);
    await expect.poll(() => dashCalls(be), SLOW).toBe(3);
    await expect(first).toContainText("815.50", SLOW);
  });

  test("TC-DE5b with the market closed the dashboard is asked once and not again", async ({ page }) => {
    await page.clock.install({ time: new Date("2026-11-03T12:00:00Z") });
    const be = await desk(page, { answer: () => ({ status: 200, body: dashboard({ open: false }) }) });
    await openDashboard(page);
    await expect(page.getByTestId("sd-live-chip")).toHaveAttribute("data-state", "closed");
    await expect(page.getByTestId("sd-live-chip")).toHaveText("Market closed");
    await page.clock.runFor(60_000);
    expect(dashCalls(be)).toBe(1);
  });

  test("TC-DE6 data unavailable (503) offers Retry; a failed refresh keeps the last answer and says so", async ({ page }) => {
    await page.clock.install({ time: new Date("2026-11-03T04:45:00Z") });
    const answers = [
      { status: 503, body: { detail: { code: "data_unavailable", message: "MOCK: the price history could not be loaded from the data platform." } } },
      { status: 200, body: dashboard() },
      { status: 503, body: { detail: { code: "data_unavailable", message: "MOCK: refresh failed." } } },
      { status: 200, body: dashboard({ bump: 7 }) },
    ];
    const be = await desk(page, { answer: (n) => answers[Math.min(n, answers.length) - 1] });
    await page.goto(DASH);
    const err = page.getByTestId("sd-error");
    await expect(err).toHaveAttribute("data-code", "data_unavailable", SLOW);
    await expect(err).toContainText("The market data could not be loaded");
    await expect(err).toContainText("MOCK: the price history could not be loaded from the data platform.");
    await err.getByRole("button", { name: /Retry/ }).click();
    await expect(page.getByTestId("scan-dashboard")).toBeVisible(SLOW);
    expect(dashCalls(be)).toBe(2);
    // the next refresh fails: the cards stay, the header says the last refresh failed
    await page.clock.runFor(10_500);
    await expect.poll(() => dashCalls(be), SLOW).toBe(3);
    await expect(page.getByTestId("sd-refresh-problem")).toContainText("The last refresh failed (MOCK: refresh failed.)", SLOW);
    await expect(widget(page, "n50_gainers").getByTestId("sd-row")).toHaveCount(3);
    // and the one after recovers by itself
    await page.clock.runFor(10_500);
    await expect.poll(() => dashCalls(be), SLOW).toBe(4);
    await expect(widget(page, "n50_gainers").getByTestId("sd-row").nth(0)).toContainText("819.50", SLOW);
    await expect(page.getByTestId("sd-refresh-problem")).toHaveCount(0);
  });

  test("TC-DE7 the dashboard never says buy, sell, target, stop loss, picks, recommended, entry or exit (ideas included)", async ({ page }) => {
    await desk(page);
    await openDashboard(page);
    await page.getByTestId("sd-sources").locator("summary").click();
    await expect(page.getByTestId("sd-idea").first()).toBeVisible();
    const banned = /\b(buy\w*|sell\w*|target\w*|stop[ -]?loss|picks?|recommend\w*|entry|exit)\b/i;
    const panel = page.getByTestId("desk-panel-scandashboard");
    const titles = await panel.locator("[title]").evaluateAll((els) => els.map((e) => e.getAttribute("title") ?? ""));
    const texts = [await page.getByTestId("md-head").innerText(), await panel.innerText(), ...titles];
    expect(titles.some((t) => t.includes("max loss"))).toBe(true);           // the idea tooltips are among the checked strings
    for (const t of texts) expect(t).not.toMatch(banned);
  });

  test("TC-DE10 stock tables end with a Strategy idea column: an idea, none favorable, or still being built; group and index tables do not", async ({ page }) => {
    await desk(page);
    await openDashboard(page);
    // the header line from ideas_meta, with the fixed caveat
    await expect(page.getByTestId("sd-ideas-count")).toHaveText("Strategy ideas: 3 of 4 stocks checked");
    await expect(page.getByTestId("sd-ideas-note")).toHaveText("· MOCK note: net reward : risk under the desk's rules.");
    await expect(page.getByTestId("sd-ideas-caveat")).toHaveText("Rules-based fits from the strategy builder, not investment advice.");
    // a stock table: Chartink's columns unchanged, the idea column appended last
    const n50 = widget(page, "n50_gainers");
    await expect(n50.locator("thead th")).toHaveText(["Symbol", "% Change", "Price", "Volume", "Strategy idea"]);
    const idea = (sym: string) => n50.locator(`[data-testid="sd-row"][data-key="${sym}"] [data-testid="sd-idea"]`);
    await expect(idea("ALPHA")).toHaveAttribute("data-state", "idea");
    await expect(idea("ALPHA")).toHaveText("Bull call spread · R:R 2.10");
    await expect(idea("ALPHA")).toHaveAttribute("title", "NOV 820 CE / 860 CE · max loss ₹12,500 · capital at risk ₹12,500 · 1–3 weeks · data 2026-11-02");
    await expect(idea("BETA")).toHaveAttribute("data-state", "none");
    await expect(idea("BETA")).toHaveText("–");
    await expect(idea("BETA")).toHaveAttribute("title", "No structure with a favorable reward : risk");
    await expect(idea("GAMMA")).toHaveAttribute("data-state", "building");
    await expect(idea("GAMMA")).toHaveText("…");
    await expect(idea("GAMMA")).toHaveAttribute("title", "Being built");
    const oi = widget(page, "oi_any");
    await expect(oi.locator('[data-testid="sd-row"][data-key="DELTA"] [data-testid="sd-idea"]')).toHaveText("Cash · R:R 1.60");
    // group and index tables: no idea column
    for (const id of ["mcap_ad", "index_stats"]) {
      await expect(widget(page, id).getByTestId("sd-idea")).toHaveCount(0);
      await expect(widget(page, id).getByTestId("sd-sort-idea")).toHaveCount(0);
    }
    // sorting by the idea's reward : risk: stocks without a number stay last either way
    const rows = n50.getByTestId("sd-row");
    await n50.getByTestId("sd-sort-idea").click();
    await expect(n50.locator("th", { has: page.getByTestId("sd-sort-idea") })).toHaveAttribute("aria-sort", "descending");
    await expect(rows.nth(0)).toHaveAttribute("data-key", "ALPHA");
    await n50.getByTestId("sd-sort-idea").click();
    await expect(n50.locator("th", { has: page.getByTestId("sd-sort-idea") })).toHaveAttribute("aria-sort", "ascending");
    await expect(rows.nth(0)).toHaveAttribute("data-key", "ALPHA");
    await expect(n50.getByTestId("sd-sort-idea")).toHaveText("Strategy idea ↑");
  });

  test("TC-DE10b an answer without ideas (an older backend) shows no idea column and no ideas line", async ({ page }) => {
    await desk(page, { answer: () => ({ status: 200, body: dashboard({ ideas: false }) }) });
    await openDashboard(page);
    await expect(widget(page, "n50_gainers").locator("thead th")).toHaveText(["Symbol", "% Change", "Price", "Volume"]);
    await expect(page.getByTestId("sd-idea")).toHaveCount(0);
    await expect(page.getByTestId("sd-ideas-line")).toHaveCount(0);
  });
});

test.describe("MOCK — not real data: Market Desk › Screener › Scan dashboard · phone 390px", () => {
  test.use({ viewport: { width: 390, height: 844 } });

  test("TC-DE8 one card per row, no sideways page scroll; a wide table scrolls inside its card", async ({ page }) => {
    await desk(page);
    await openDashboard(page);
    const o = await page.evaluate(() => {
      const sc = document.querySelector('[data-testid="copilot-scroll"]') as HTMLElement | null;
      const cards = Array.from(document.querySelectorAll('[data-testid^="sd-widget-"][data-status]')) as HTMLElement[];
      const lefts = new Set(cards.map((c) => Math.round(c.getBoundingClientRect().left)));
      return {
        doc: document.documentElement.scrollWidth - window.innerWidth,
        scroll: sc ? sc.scrollWidth - sc.clientWidth : 0,
        columns: lefts.size,
        cards: cards.length,
      };
    });
    expect(o.cards).toBe(8);
    expect(o.columns).toBe(1);
    expect(o.doc).toBeLessThanOrEqual(1);
    expect(o.scroll).toBeLessThanOrEqual(1);
  });
});
