/**
 * One-screen Copilot app (/v5/app) — Market Desk › Market Intelligence: the "Market Update" ticker (owner, 5–6 Nov 2026: a
 * Bloomberg-style ticker that is a summary of everything, not every filing). Covers tradingdesk/tabs/market-desk/NewsTicker.tsx
 * + news-ticker-data.ts, the Events calendar's ?ev_open=&ev_uni= link (EventsTab.tsx) and the ticker's ?in_chip=&in_ev= links
 * into IntelTab. Test cases: test_reports/intel_news_ticker_TESTCASES.md.
 *
 * MOCK — not real data: every /api response is an inline payload in the shape the real route returns (named beside each)
 * with synthetic symbols and values; expected figures are worked out from the payload. The clock is fixed at Thu 5 Nov
 * 2026, 19:30 IST (14:00 UTC), so the window starts Wed 4 Nov 00:00 IST and the counts read asks days=1.
 */
import { test, expect, type Page, type Route } from "@playwright/test";
import { mockApi, mockSingleRoute } from "../helpers/api-mock";

const DESK = "/v5/app/trader/desk";
const INTEL = `${DESK}?tab=market&view=intel`;
const SLOW = { timeout: 15_000 };
const NOW = new Date("2026-11-05T14:00:00Z");
const json = (route: Route, body: unknown, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
const evId = (d: string, s: string) => `${d}|${s}|RESULTS|mtg`;

// ── results board: backend/routes/events_calendar.py → DaaS desk_expectation.py results_expectations (compact_event) ──
// MOCK — not real data
const met = (key: string, filed: number | null, lastYear: number | null, at: string | null) => ({
  key, unit: "₹ crore", expected: null, same_quarter_last_year: lastYear, previous_quarter: null, trend_yoy_pct: null,
  filed: filed == null ? null : { value: filed, broadcast_at: at, audit_status: null }, vs_mid_pct: null, within_band: null, reliable: true, note: null, last_year_note: null,
});
const bev = (date: string, symbol: string, state: "figures" | "pending" | null, uni: { fno: boolean; n50: boolean }, metrics: unknown[] = [], filing: unknown = null) => ({
  id: evId(date, symbol), symbol, name: `${symbol} Ltd (mock)`, sector: "Fixture", event_date: date, status: state ? "declared" : "upcoming", filed_state: state,
  filing, period_label: "Q2 FY27 (Jul–Sep 2026)", basis: "consolidated", audit_status: null, audit_basis: null, compared_with: null, expected_as_of: "2026-11-04",
  universe: uni, metrics, gaps: [],
});
const FNO = { fno: true, n50: false };
const N50 = { fno: true, n50: true };
const NONE = { fno: false, n50: false };
const T = "2026-11-05";
const TOM = "2026-11-06";
const PREV = "2026-11-04";
const TOMORROW_SYMS = Array.from({ length: 18 }, (_, i) => `TOM${String(i + 1).padStart(2, "0")}`);
const BOARD = {
  from: T, to: TOM, universe: "all", as_of: T, count: 0, counts: { declared_figures: 4, declared_pending: 2, upcoming: 2 + 19 },
  label: "Baseline (mock)",
  events: [
    bev(T, "DECLA", "figures", N50, [met("revenue", 1100, 1000, "2026-11-05T16:10:00+05:30"), met("pat", 90, 100, "2026-11-05T16:10:00+05:30")]),
    bev(T, "LOSSA", "figures", FNO, [met("revenue", 500, 450, "2026-11-05T17:00:00+05:30"), met("pat", -5, 20, "2026-11-05T17:00:00+05:30")]),
    bev(T, "GAINB", "figures", FNO, [met("revenue", 300, null, "2026-11-05T15:00:00+05:30"), met("pat", 8, -3, "2026-11-05T15:00:00+05:30")]),
    bev(T, "WIDEC", "figures", NONE, [met("revenue", 200, 100, "2026-11-05T18:00:00+05:30"), met("pat", 20, 10, "2026-11-05T18:00:00+05:30")]),
    bev(T, "PENDA", "pending", FNO, [], { filed_at: "2026-11-05T16:05:00+05:30", subject: "Outcome of Board Meeting", url: "https://nsearchives.nseindia.com/mock.pdf" }),
    bev(T, "OUTCO", "pending", NONE, [], { filed_at: "2026-11-05T16:59:00+05:30", subject: "Outcome of Board Meeting", url: null }),
    bev(T, "DUEA", null, FNO), bev(T, "DUEB", null, N50),
    ...TOMORROW_SYMS.map((s) => bev(TOM, s, null, FNO)),
    bev(TOM, "TOMWIDE", null, NONE),
  ],
  method: { by_metric: {} }, sources: {}, gaps: [],
};
const PREV_BOARD = {
  from: PREV, to: PREV, universe: "all", as_of: T, count: 1, counts: { declared_figures: 1, declared_pending: 0, upcoming: 0 }, label: "Baseline (mock)",
  events: [bev(PREV, "PREVA", "figures", FNO, [met("revenue", 2000, 1600, "2026-11-04T19:00:00+05:30"), met("pat", 300, 250, "2026-11-04T19:00:00+05:30")])],
  method: { by_metric: {} }, sources: {}, gaps: [],
};

// ── filings: backend/routes/filings.py filings_feed?provenance=1 (_row + provenance) ── MOCK — not real data
const frow = (id: string, symbol: string, category: string, docLabel: string, date: string) => ({
  id, ticker: symbol, code: symbol, name: `${symbol} Ltd (mock)`, date, category, impact: "medium", sentiment: "neutral", docLabel,
  url: "https://nsearchives.nseindia.com/corporate/mock.pdf", one: null, period: null, metric: null, hasInsights: false, exchange: "NSE",
  published_at: date, ingested_at: date,
});
const FEEDS: Record<string, unknown[]> = {
  // ten orders in the window (the newest is ORDA), one 9 days old
  orders: [frow("ord-1", "ORDA", "Orders", "Bagging/Receiving of orders/contracts", "2026-11-05T17:01:00+05:30"),
    ...Array.from({ length: 9 }, (_, i) => frow(`ord-x${i + 1}`, `ORDX${i + 1}`, "Orders", "Bagging/Receiving of orders/contracts", `2026-11-05T09:0${i}:00+05:30`)),
    frow("ord-old", "ORDOLD", "Orders", "Bagging/Receiving of orders/contracts", "2026-10-27T11:00:00+05:30")],
  // MNAA filed twice (named once); OUTCO's board outcome on its results day is not named
  mna: [frow("mna-1", "MNAA", "Mna", "Acquisition", "2026-11-05T17:05:00+05:30"),
    frow("mna-outcome", "OUTCO", "Mna", "Outcome of Board Meeting", "2026-11-05T16:59:00+05:30"),
    frow("mna-2", "MNAA", "Mna", "Acquisition", "2026-11-05T10:00:00+05:30")],
  dividend: [frow("div-1", "DIVA", "Dividend", "Dividend", "2026-11-04T14:00:00+05:30")],
  buyback: [frow("bb-1", "BBKA", "Buyback", "Buyback", "2026-11-05T12:00:00+05:30")],
};
const feedBody = (rows: unknown[]) => ({ ok: true, total: rows.length, facets: {}, rows, provenance: { error: null } });
// backend/routes/filings.py filings_feed?days=1&sort=latest&limit=1 — the per-category counts of the whole window (facets)
const COUNTS = { ok: true, total: 961, facets: { earnings: 285, management: 78, orders: 27, mna: 61, dividend: 22, buyback: 1, capex: 15, qip: 17, rating: 10 }, rows: [] };

// ── deals: backend/routes/markets_desk.py deals ── MOCK — not real data. Nine on the latest day (both sides of DLB's block),
// one the day before.
const deal = (symbol: string, value_cr: number, side: string, date = T, kind = "block") => ({
  date, kind, symbol, client_name: `FIXTURE ${symbol} FUND`, side, quantity: 100000, avg_price: 100, value_cr, pct_of_shares: 0.5,
  shares_period_end: "2026-09-30", close_on_day: 101, prev_close: 99, next_date: null, next_close: null, price_vs_close_pct: -1, ingested_at: "2026-11-05T19:00:00+05:30",
});
const DEALS = {
  as_of: T, from: "2026-11-01", days: 5, kind: "all", source: "NSE bulk and block deals (mock)", disclosure: "Exchange disclosure", count: 9, total: 9,
  rows: [deal("DLA", 50, "BUY"), deal("DLB", 80, "SELL"), deal("DLC", 10, "BUY", T, "bulk"), deal("DLD", 70, "BUY"), deal("DLE", 5, "SELL", T, "bulk"),
    deal("DLF", 60, "SELL"), deal("DLG", 40, "BUY"), deal("DLH", 30, "BUY"), deal("DLOLD", 999, "BUY", PREV), deal("DLB", 79.5, "BUY")],
};
// ── FII / DII: backend/routes/markets.py markets_fii_dii ── MOCK — not real data
const FLOWS = { ok: true, as_of: T, monthly: [], daily: [
  { date: T, fii_buy: 1, fii_sell: 1, fii_net: -1234.5, dii_buy: 1, dii_sell: 1, dii_net: 2000 },
  { date: PREV, fii_buy: 1, fii_sell: 1, fii_net: 500, dii_buy: 1, dii_sell: 1, dii_net: -100 },
] };
// ── SEBI circulars: backend/routes/circulars.py ── MOCK — not real data
const CIRCULARS = { as_of: T, source: "SEBI RSS (mock)", count: 2, rows: [
  { title: "Fixture circular on investor charters", url: "https://www.sebi.gov.in/legal/circulars/nov-2026/mock.html", kind: "circular", issued_on: T },
  { title: "Fixture old circular", url: "https://www.sebi.gov.in/legal/circulars/oct-2026/mock.html", kind: "circular", issued_on: "2026-10-16" },
] };
// ── sector returns: backend/routes/markets_desk.py sector_returns ── MOCK — not real data
const SECTORS = { as_of: T, source: "NSE index close (mock)", sessions: { "1d": 1, "1w": 5, "1m": 21 }, sectors: [
  { index: "Nifty IT", sector: "IT", date: T, close: 35000, ret_1d_pct: 2.1, ret_1w_pct: 1, ret_1m_pct: 2 },
  { index: "Nifty Metal", sector: "Metals", date: T, close: 9000, ret_1d_pct: -1.4, ret_1w_pct: 1, ret_1m_pct: 2 },
  { index: "Nifty Bank", sector: "Banks", date: T, close: 56000, ret_1d_pct: 0.3, ret_1w_pct: 1, ret_1m_pct: 2 },
] };
// ── Events calendar (EventsTab): backend/routes/events_calendar.py ── MOCK — not real data
const CAL = { month: "2026-11", as_of: T, events: BOARD.events.concat(PREV_BOARD.events).map((e) => ({
  id: e.id, date: e.event_date, symbol: e.symbol, name: e.name, sector: "Fixture", type: "RESULTS", timing: null, detail: "Results (mock)",
  universe: e.universe, source: "NSE", announced_at: null,
})), holidays: [], index_closes: [], gaps: [] };
const HIST = { symbol: "DECLA", type: "RESULTS", coverage_from: "2025-10-01", n: 0, basis: "mock", occurrences: [], stats: { event_day: {}, d1: {}, w1: {} } };

interface Calls { board: URL[]; feed: URL[]; counts: URL[] }
type Fail = Partial<Record<"board" | "prev" | "feed" | "counts" | "deals" | "flows" | "circulars" | "sectors", number>>;

async function setup(page: Page, opts: { fail?: Fail; empty?: boolean; fixedClock?: boolean } = {}): Promise<Calls> {
  const calls: Calls = { board: [], feed: [], counts: [] };
  const fail = opts.fail ?? {};
  await mockApi(page, "populated");
  if (opts.fixedClock !== false) await page.clock.setFixedTime(NOW);
  await mockSingleRoute(page, "**/api/markets/home", "markets-home.json");
  await page.route("**/api/chat/sessions", (r) => json(r, []));
  await page.route("**/api/positional/watchlist*", (r) => json(r, { as_of_date: T, buckets: { breakout_confirmed: [], pre_breakout: [], true_accumulation: [], trend_continuation: [] } }));
  await page.route("**/api/positional/picks*", (r) => json(r, { signal_date: T, count: 0, picks: [] }));
  await page.route("**/api/move-odds/**", (r) => json(r, { detail: "feature_not_enabled" }, 403));
  await page.route("**/api/desk/alerts*", (r) => json(r, { as_of: null, checked_through: null, marks_error: null, alerts: [] }));
  await page.route("**/api/markets/sector-heatmap*", (r) => json(r, { as_of: T, index: "NIFTY50", sectors: [], stocks: [], weighted_change: { d: 0, w: 0, m: 0 }, unavailable: [] }));
  await page.route("**/api/markets/events-calendar/expectations*", (r) => {
    const u = new URL(r.request().url());
    calls.board.push(u);
    const prev = u.searchParams.get("from") === PREV;
    const code = prev ? fail.prev : fail.board;
    if (code) return json(r, { detail: "upstream_unavailable" }, code);
    if (opts.empty) return json(r, { ...(prev ? PREV_BOARD : BOARD), events: [] });
    return json(r, prev ? PREV_BOARD : BOARD);
  });
  await page.route("**/api/markets/events-calendar/history*", (r) => json(r, HIST));
  await page.route("**/api/markets/events-calendar/expectation?*", (r) => json(r, { detail: "not found" }, 404));
  await page.route("**/api/markets/events-calendar?*", (r) => json(r, CAL));
  await page.route("**/api/markets/macro-calendar*", (r) => json(r, { month: "2026-11", as_of: T, events: [], holidays: [], index_closes: [], gaps: [], countries: [] }));
  await page.route("**/api/filings/feed*", (r) => {
    const u = new URL(r.request().url());
    const cat = u.searchParams.get("category");
    if (!cat && !u.searchParams.get("family") && u.searchParams.get("limit") === "1") {
      calls.counts.push(u);
      if (fail.counts) return json(r, { detail: "upstream_unavailable" }, fail.counts);
      return json(r, opts.empty ? { ...COUNTS, total: 0, facets: {} } : COUNTS);
    }
    calls.feed.push(u);
    if (fail.feed) return json(r, { detail: "upstream_unavailable" }, fail.feed);
    if (opts.empty) return json(r, feedBody([]));
    return json(r, feedBody(cat ? FEEDS[cat] ?? [] : Object.values(FEEDS).flat()));
  });
  await page.route("**/api/filings/*/insights", (r) => json(r, { ok: false, reason: "no_insight_yet" }, 404));
  await page.route("**/api/markets/deals*", (r) => (fail.deals ? json(r, { detail: "x" }, fail.deals) : json(r, opts.empty ? { ...DEALS, rows: [], count: 0, total: 0 } : DEALS)));
  await page.route("**/api/markets/fii-dii*", (r) => (fail.flows ? json(r, { detail: "x" }, fail.flows) : json(r, opts.empty ? { ...FLOWS, daily: [] } : FLOWS)));
  await page.route("**/api/markets/circulars*", (r) => (fail.circulars ? json(r, { detail: "x" }, fail.circulars) : json(r, opts.empty ? { ...CIRCULARS, rows: [] } : CIRCULARS)));
  await page.route("**/api/markets/sector-returns", (r) => (fail.sectors ? json(r, { detail: "x" }, fail.sectors) : json(r, opts.empty ? { ...SECTORS, sectors: [] } : SECTORS)));
  return calls;
}

const tape = (page: Page) => page.getByTestId("md-ticker-tape");
const item = (page: Page, key: string) => tape(page).getByTestId(`md-ticker-item-${key}`);
const entry = (page: Page, key: string, id: string) => tape(page).getByTestId(`md-ticker-entry-${key}-${id}`);
const entryIds = (page: Page, key: string) =>
  item(page, key).locator(`[data-testid^="md-ticker-entry-${key}-"]`).evaluateAll((els, k) => els.map((e) => (e.getAttribute("data-testid") ?? "").replace(`md-ticker-entry-${k}-`, "")), key);
const params = (page: Page) => new URL(page.url()).searchParams;
const BANNED = /\b(buy|sell|sold|bought|target|stop[- ]?loss|recommend\w*|pick\w*|suggest\w*|beat|miss(ed)?)\b/i;

test.describe("MOCK — not real data: Market Update (desktop)", () => {
  test.use({ viewport: { width: 1440, height: 1000 } });

  test("NT-1 the band sits above the event list on Market Intelligence only", async ({ page }) => {
    await setup(page);
    await page.goto(INTEL);
    const ticker = page.getByTestId("md-ticker");
    await expect(ticker).toBeVisible(SLOW);
    await expect(ticker).toHaveAttribute("aria-label", "Market update");
    const tBox = await page.getByTestId("desk-panel-ticker").boundingBox();
    const iBox = await page.getByTestId("desk-panel-intel").boundingBox();
    expect(tBox && iBox && tBox.y < iBox.y).toBe(true);
    await expect(page.getByTestId("md-ticker-label")).toContainText("MARKET UPDATE");
    for (const view of ["smartmoney", "sectors", "research", "screener"]) {
      await page.goto(`${DESK}?tab=market&view=${view}`);
      await expect(page.getByTestId("md-head")).toHaveAttribute("data-view", view, SLOW);
      await expect(page.getByTestId("md-ticker"), view).toHaveCount(0);
    }
  });

  test("NT-2 one item per kind, in order; the counts come from the counts read", async ({ page }) => {
    const calls = await setup(page);
    await page.goto(INTEL);
    await expect(tape(page)).toBeVisible(SLOW);
    const tags = await tape(page).locator("[data-tag]").evaluateAll((els) => els.map((e) => e.getAttribute("data-tag")));
    expect(tags).toEqual(["results", "filed", "due", "tomorrow", "orders", "mna", "actions", "deals", "flows", "sebi", "sector"]);
    expect(calls.counts).toHaveLength(1);
    expect([calls.counts[0].searchParams.get("days"), calls.counts[0].searchParams.get("sort"), calls.counts[0].searchParams.get("limit")]).toEqual(["1", "latest", "1"]);
  });

  test("NT-3 results: declared since the previous weekday with their change on the year; losses in words", async ({ page }) => {
    await setup(page);
    await page.goto(INTEL);
    await expect(tape(page)).toBeVisible(SLOW);
    await expect(tape(page).getByTestId("md-ticker-count-results")).toHaveText("4 declared since Wed 4 Nov");
    // newest filing first: LOSSA 17:00, DECLA 16:10, GAINB 15:00, PREVA 4 Nov; the non-F&O WIDEC is not on the F&O tape
    expect(await entryIds(page, "results")).toEqual([evId(T, "LOSSA"), evId(T, "DECLA"), evId(T, "GAINB"), evId(PREV, "PREVA")]);
    const decla = entry(page, "results", evId(T, "DECLA"));
    await expect(decla.getByTestId("md-ticker-fig-revenue")).toHaveText(/Rev\s*▲10\.0% YoY/);
    await expect(decla.getByTestId("md-ticker-fig-pat")).toHaveText(/PAT\s*▼10\.0% YoY/);
    await expect(entry(page, "results", evId(T, "LOSSA")).getByTestId("md-ticker-fig-pat")).toHaveText(/PAT\s*turned to a loss/);
    const gain = entry(page, "results", evId(T, "GAINB"));
    await expect(gain.getByTestId("md-ticker-fig-revenue")).toHaveText(/Rev\s*₹300 cr/);
    await expect(gain.getByTestId("md-ticker-fig-pat")).toHaveText(/PAT\s*from a loss/);
    await expect(entry(page, "results", evId(PREV, "PREVA")).getByTestId("md-ticker-fig-pat")).toHaveText(/PAT\s*▲20\.0% YoY/);
    await expect(tape(page).getByTestId("md-ticker-more-results")).toHaveCount(0);
  });

  test("NT-4/5 filed, due today and tomorrow: counts and names; tomorrow shows 12 and '+6 more'", async ({ page }) => {
    await setup(page);
    await page.goto(INTEL);
    await expect(tape(page)).toBeVisible(SLOW);
    await expect(tape(page).getByTestId("md-ticker-count-filed")).toHaveText("1 filed today, figures not loaded yet");
    expect(await entryIds(page, "filed")).toEqual([evId(T, "PENDA")]);
    await expect(tape(page).getByTestId("md-ticker-count-due")).toHaveText("2 meetings today");
    expect(await entryIds(page, "due")).toEqual([evId(T, "DUEA"), evId(T, "DUEB")]);
    await expect(tape(page).getByTestId("md-ticker-count-tomorrow")).toHaveText("Fri 6 Nov · 18 meetings");
    expect(await entryIds(page, "tomorrow")).toHaveLength(12);
    await expect(tape(page).getByTestId("md-ticker-more-tomorrow")).toHaveText("+6 more ›");
  });

  test("NT-6/7/8 orders and M&A: the full count with the newest names; corporate actions as counts", async ({ page }) => {
    await setup(page);
    await page.goto(INTEL);
    await expect(tape(page)).toBeVisible(SLOW);
    await expect(tape(page).getByTestId("md-ticker-count-orders")).toHaveText("27 since Wed 4 Nov");
    expect(await entryIds(page, "orders")).toEqual(["ord-1", "ord-x9", "ord-x8", "ord-x7", "ord-x6", "ord-x5"]);
    await expect(entry(page, "orders", "ord-1")).toHaveText("ORDA");
    await expect(tape(page).getByTestId("md-ticker-more-orders")).toHaveText("+21 more ›");
    // the board-meeting outcome of a company with results today is not named under M&A; the count is the classifier's
    await expect(tape(page).getByTestId("md-ticker-count-mna")).toHaveText("61 since Wed 4 Nov");
    // MNAA filed twice (one event of two records in the list): named once, "+ more" counts the other filings (61 − MNAA's 2)
    expect(await entryIds(page, "mna")).toEqual(["mna-1"]);
    await expect(tape(page).getByTestId("md-ticker-more-mna")).toHaveText("+59 more ›");
    await expect(tape(page).getByTestId("md-ticker-count-actions")).toHaveText("65 since Wed 4 Nov");
    const actions = await item(page, "actions").locator('[data-testid^="md-ticker-entry-actions-"]').allInnerTexts();
    expect(actions).toEqual(["Dividend 22", "Buyback 1", "Capex 15", "Fundraise 17", "Rating 10"]);
  });

  test("NT-9 when the counts read fails, the names read is counted and the note says what did not load", async ({ page }) => {
    await setup(page, { fail: { counts: 500 } });
    await page.goto(INTEL);
    await expect(tape(page)).toBeVisible(SLOW);
    await expect(tape(page).getByTestId("md-ticker-count-orders")).toHaveText("10 since Wed 4 Nov", SLOW);
    await expect(tape(page).getByTestId("md-ticker-more-orders")).toHaveText("+4 more ›");
    await expect(item(page, "actions")).toHaveCount(0);
    await expect(page.getByTestId("md-ticker-partial")).toContainText("Not loaded: filing counts.");
  });

  test("NT-10/11/12/13 deals, FII / DII, SEBI and sectors", async ({ page }) => {
    await setup(page);
    await page.goto(INTEL);
    await expect(tape(page)).toBeVisible(SLOW);
    await expect(tape(page).getByTestId("md-ticker-count-deals")).toHaveText("9 bulk / block deals on 5 Nov, the largest");
    // both sides of DLB's block are one name (the larger), and "+ more" counts the other deals (9 − DLB's 2 − DLD − DLF)
    const deals = await item(page, "deals").locator('[data-testid^="md-ticker-entry-deals-"]').allInnerTexts();
    expect(deals.map((s) => s.replace(/\s+/g, " "))).toEqual(["DLB ₹80 cr", "DLD ₹70 cr", "DLF ₹60 cr"]);
    await expect(tape(page).getByTestId("md-ticker-more-deals")).toHaveText("+5 more ›");
    await expect(tape(page).getByTestId("md-ticker-count-flows")).toHaveText("5 Nov, cash market, provisional");
    await expect(item(page, "flows").getByTestId("md-ticker-fig-fii")).toHaveText(/FII net\s*−₹1,235 cr/);
    await expect(item(page, "flows").getByTestId("md-ticker-fig-dii")).toHaveText(/DII net\s*\+₹2,000 cr/);
    await expect(tape(page).getByTestId("md-ticker-count-sebi")).toHaveText("1 circular since Wed 4 Nov");
    await expect(item(page, "sebi")).toContainText("Fixture circular on investor charters");
    await expect(item(page, "sebi")).not.toContainText("Fixture old circular");
    await expect(tape(page).getByTestId("md-ticker-count-sector")).toHaveText("moved 1% or more on 5 Nov");
    const sec = await item(page, "sector").locator('[data-testid^="md-ticker-entry-sector-"]').allInnerTexts();
    expect(sec.map((s) => s.replace(/\s+/g, " "))).toEqual(["Nifty IT ▲2.10%", "Nifty Metal ▼1.40%"]);
  });

  test("NT-14 one board read for all NSE; the switch filters it (F&O default, Nifty 50, All NSE)", async ({ page }) => {
    const calls = await setup(page);
    await page.goto(INTEL);
    await expect(tape(page)).toBeVisible(SLOW);
    await expect(page.getByTestId("md-ticker-uni-fno")).toHaveAttribute("aria-pressed", "true");
    // the ticker's reads are universe=all (the Events calendar below makes its own F&O read of today and tomorrow)
    const tickerReads = () => calls.board.filter((u) => u.searchParams.get("universe") === "all");
    await expect.poll(() => tickerReads().length).toBe(2);
    expect(tickerReads().map((u) => `${u.searchParams.get("from")}..${u.searchParams.get("to")}`).sort()).toEqual([`${PREV}..${PREV}`, `${T}..${TOM}`].sort());
    await page.getByTestId("md-ticker-uni-n50").click();
    expect(await entryIds(page, "results")).toEqual([evId(T, "DECLA")]);
    await expect(item(page, "tomorrow")).toHaveCount(0);
    await page.getByTestId("md-ticker-uni-all").click();
    await expect(tape(page).getByTestId("md-ticker-count-results")).toHaveText("5 declared since Wed 4 Nov");
    await expect(entry(page, "results", evId(T, "WIDEC")).getByTestId("md-ticker-fig-revenue")).toHaveText(/▲100\.0% YoY/);
    await expect(tape(page).getByTestId("md-ticker-count-tomorrow")).toHaveText("Fri 6 Nov · 19 meetings");
    expect(tickerReads().length).toBe(2);
    expect(calls.board.filter((u) => u.searchParams.get("universe") === "n50")).toHaveLength(0);
  });

  test("NT-15 names open their event below; '+ more' opens the whole list", async ({ page }) => {
    await setup(page);
    await page.goto(INTEL);
    await expect(tape(page)).toBeVisible(SLOW);
    await page.getByTestId("md-ticker-pause").click();
    await entry(page, "orders", "ord-1").click();
    await expect.poll(() => params(page).get("in_chip")).toBe("orders");
    expect(params(page).get("in_ev")).toBe("ord-1");
    await expect(page.getByTestId("desk-panel-intel").getByTestId("desk-event-title").first()).toContainText("Bagging/Receiving of orders/contracts", SLOW);
    await tape(page).getByTestId("md-ticker-more-mna").click();
    await expect.poll(() => params(page).get("in_chip")).toBe("mna");
    expect(params(page).get("in_ev")).toBeNull();
    await item(page, "actions").getByRole("button", { name: /Capex 15/ }).click();
    await expect.poll(() => params(page).get("in_chip")).toBe("announcements");
    await item(page, "deals").locator('[data-testid^="md-ticker-entry-deals-"]').first().click();
    await expect.poll(() => params(page).get("in_chip")).toBe("deals");
    expect(params(page).get("in_ev")).toMatch(/^deal-2026-11-05-block-DLB-/);
    await item(page, "flows").getByRole("button").click();
    await expect.poll(() => params(page).get("in_chip")).toBe("flows");
    expect(params(page).get("in_ev")).toBe(`fiidii-${T}`);
  });

  test("NT-16 a results name opens that company in the Events calendar; the link is used once", async ({ page }) => {
    await setup(page);
    await page.goto(INTEL);
    await expect(tape(page)).toBeVisible(SLOW);
    await page.getByTestId("md-ticker-pause").click();
    await entry(page, "results", evId(T, "DECLA")).click();
    const panel = page.getByTestId("desk-panel-events").getByTestId("events-panel");
    await expect(panel).toContainText("DECLA Ltd (mock)", SLOW);
    await expect.poll(() => params(page).get("ev_open")).toBeNull();
    expect(params(page).get("ev_uni")).toBeNull();
    await page.getByTestId("events-panel-close").first().click();
    await entry(page, "tomorrow", evId(TOM, "TOM02")).click();
    await expect(panel).toContainText("TOM02 Ltd (mock)", SLOW);
  });

  test("NT-17 pause, hover and focus stop the tape; the copy is hidden from assistive technology", async ({ page }) => {
    await setup(page);
    await page.goto(INTEL);
    await expect(tape(page)).toBeVisible(SLOW);
    const track = page.getByTestId("md-ticker-track");
    const state = () => track.evaluate((el) => getComputedStyle(el).animationPlayState);
    expect(await track.evaluate((el) => getComputedStyle(el).animationName)).toBe("mkt-marquee");
    expect(await state()).toBe("running");
    const pause = page.getByTestId("md-ticker-pause");
    await pause.click();
    await expect(pause).toHaveAttribute("aria-pressed", "true");
    await expect(pause).toHaveAccessibleName("Play the market update");
    expect(await state()).toBe("paused");
    await pause.click();
    await page.mouse.move(0, 0);
    expect(await state()).toBe("running");
    await page.getByTestId("md-ticker-view").hover();
    expect(await state()).toBe("paused");
    await page.mouse.move(0, 0);
    await entry(page, "orders", "ord-1").focus();
    await expect(track).toHaveAttribute("data-paused", "true");
    const copy = page.getByTestId("md-ticker-tape-copy");
    await expect(copy).toHaveAttribute("aria-hidden", "true");
    expect(await copy.locator("button").evaluateAll((els) => els.filter((e) => e.getAttribute("tabindex") !== "-1").length)).toBe(0);
    await expect(entry(page, "results", evId(T, "DECLA"))).toHaveAccessibleName("Results, DECLA, Rev up 10.0% YoY, PAT down 10.0% YoY");
    await expect(tape(page).getByTestId("md-ticker-more-orders")).toHaveAccessibleName("Orders: the other 21, in the full list below");
  });

  test("NT-18 states: partial, all failed with retry, nothing new, loading", async ({ page }) => {
    await setup(page, { fail: { deals: 500, board: 500 } });
    await page.goto(INTEL);
    await expect(item(page, "orders")).toBeVisible(SLOW);
    await expect(page.getByTestId("md-ticker-partial")).toContainText("Not loaded: results, deals.");
    await expect(page.getByTestId("md-ticker-partial-retry")).toBeVisible();

    const p2 = await page.context().newPage();
    await setup(p2, { fail: { board: 500, prev: 500, feed: 500, counts: 500, deals: 500, flows: 500, circulars: 500, sectors: 500 } });
    await p2.goto(INTEL);
    await expect(p2.getByTestId("md-ticker-error")).toContainText("The market update’s sources didn’t load.", SLOW);
    await expect(p2.getByTestId("md-ticker-retry")).toBeVisible();

    const p3 = await page.context().newPage();
    await setup(p3, { empty: true });
    await p3.goto(INTEL);
    await expect(p3.getByTestId("md-ticker-empty")).toContainText("Nothing new since Wed 4 Nov", SLOW);

    const p4 = await page.context().newPage();
    await setup(p4);
    for (const pat of ["**/api/markets/events-calendar/expectations*", "**/api/filings/feed*", "**/api/markets/deals*", "**/api/markets/fii-dii*", "**/api/markets/circulars*", "**/api/markets/sector-returns"]) {
      await p4.route(pat, () => undefined); // never answers
    }
    await p4.goto(INTEL);
    await expect(p4.getByTestId("md-ticker-loading")).toBeVisible(SLOW);
  });

  test("NT-19 wording: no advice words on the tape or its note", async ({ page }) => {
    await setup(page);
    await page.goto(INTEL);
    await expect(tape(page)).toBeVisible(SLOW);
    await page.getByTestId("md-ticker-uni-all").click();
    const text = `${await tape(page).innerText()} ${await page.getByTestId("md-ticker-note").innerText()}`;
    expect(text).not.toMatch(BANNED);
    await page.getByTestId("md-ticker-pause").click();
    await page.getByTestId("md-ticker").screenshot({ path: "e2e/screenshots/desk-news-ticker/desktop-ticker.png" });
  });
});

test.describe("MOCK — not real data: Market Update refresh, reduced motion and phone", () => {
  test("NT-20 counts and names are re-read every minute while the band is on screen", async ({ page }) => {
    await page.clock.install({ time: NOW });
    const calls = await setup(page, { fixedClock: false });
    await page.goto(INTEL);
    await expect(tape(page)).toBeVisible(SLOW);
    const orders = () => calls.feed.filter((u) => u.searchParams.get("category") === "orders").length;
    const [o, c] = [orders(), calls.counts.length];
    await page.clock.runFor(61_000);
    await expect.poll(orders).toBeGreaterThan(o);
    await expect.poll(() => calls.counts.length).toBeGreaterThan(c);
  });

  test("NT-21 reduced motion: no animation, one copy, scrolls sideways, no Pause button", async ({ page }) => {
    await page.emulateMedia({ reducedMotion: "reduce" });
    await setup(page);
    await page.goto(INTEL);
    await expect(tape(page)).toBeVisible(SLOW);
    await expect(page.getByTestId("md-ticker-tape-copy")).toHaveCount(0);
    await expect(page.getByTestId("md-ticker-pause")).toHaveCount(0);
    expect(await page.getByTestId("md-ticker-track").evaluate((el) => getComputedStyle(el).animationName)).toBe("none");
    const view = page.getByTestId("md-ticker-view");
    expect(await view.evaluate((el) => getComputedStyle(el).overflowX)).toBe("auto");
    expect(await view.evaluate((el) => el.scrollWidth > el.clientWidth)).toBe(true);
  });

  test("NT-22 phone 390 px: no sideways page scroll; a results tap opens the sheet in the right list", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await setup(page);
    await page.goto(INTEL);
    await expect(tape(page)).toBeVisible(SLOW);
    await expect(page.getByTestId("md-ticker-label")).toContainText("UPDATE");
    await expect(page.getByTestId("md-ticker-uni-fno")).toBeVisible();
    const o = await page.evaluate(() => {
      const sc = document.querySelector('[data-testid="copilot-scroll"]') as HTMLElement | null;
      return { doc: document.documentElement.scrollWidth - window.innerWidth, scroll: sc ? sc.scrollWidth - sc.clientWidth : 0 };
    });
    expect(o.doc).toBeLessThanOrEqual(1);
    expect(o.scroll).toBeLessThanOrEqual(1);
    await page.getByTestId("md-ticker-pause").click();
    await page.getByTestId("md-ticker").screenshot({ path: "e2e/screenshots/desk-news-ticker/phone-ticker.png" });
    await page.getByTestId("md-ticker-uni-all").click();
    await entry(page, "results", evId(T, "WIDEC")).click();
    await expect(page.getByTestId("events-sheet")).toContainText("WIDEC Ltd (mock)", SLOW);
    await expect(page.getByTestId("events-m-uni")).toContainText("Showing all NSE companies");
    await page.getByTestId("events-sheet-close").click();
    await page.getByTestId("events-m-uni-back").click();
    await expect(page.getByTestId("events-m-uni")).toHaveCount(0);
  });
});
