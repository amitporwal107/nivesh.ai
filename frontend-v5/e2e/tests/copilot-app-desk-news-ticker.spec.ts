/**
 * One-screen Copilot app (/v5/app) — Market Desk › Market Intelligence: the news ticker (owner, 5 Nov 2026).
 * Covers tradingdesk/tabs/market-desk/NewsTicker.tsx + news-ticker-data.ts, the Events calendar's ?ev_open=&ev_uni= link
 * (EventsTab.tsx) and the ticker's ?in_chip=&in_ev= links into IntelTab. Test cases: test_reports/intel_news_ticker_TESTCASES.md.
 *
 * MOCK — not real data: every /api response is an inline payload in the shape the real route returns (named beside each)
 * with synthetic symbols and values; expected figures are worked out from the payload. The clock is fixed at Thu 5 Nov
 * 2026, 19:30 IST, so the filings window starts Wed 4 Nov 00:00 IST.
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
  // ten orders in the window (the newest is ORDA), so "Everything" shows 8 of them; one 9 days old
  orders: [frow("ord-1", "ORDA", "Orders", "Bagging/Receiving of orders/contracts", "2026-11-05T17:01:00+05:30"),
    ...Array.from({ length: 9 }, (_, i) => frow(`ord-x${i + 1}`, `ORDX${i + 1}`, "Orders", "Bagging/Receiving of orders/contracts", `2026-11-05T09:0${i}:00+05:30`)),
    frow("ord-old", "ORDOLD", "Orders", "Bagging/Receiving of orders/contracts", "2026-10-27T11:00:00+05:30")],
  mna: [frow("mna-1", "MNAA", "Mna", "Acquisition", "2026-11-05T17:05:00+05:30"),
    frow("mna-outcome", "OUTCO", "Mna", "Outcome of Board Meeting", "2026-11-05T16:59:00+05:30")],
  dividend: [frow("div-1", "DIVA", "Dividend", "Dividend", "2026-11-04T14:00:00+05:30")],
  buyback: [frow("bb-1", "BBKA", "Buyback", "Buyback", "2026-11-05T12:00:00+05:30")],
  capex: [frow("cap-1", "CAPX", "Capex", "Capacity addition", "2026-11-05T13:29:00+05:30")],
  qip: [frow("qip-1", "QIPA", "Qip", "Fund raising", "2026-11-05T11:00:00+05:30")],
  rating: [frow("rat-1", "RATA", "Rating", "Credit Rating", "2026-11-05T17:18:00+05:30")],
  management: [frow("mgmt-1", "MGMT", "Management", "Change in Key Managerial Personnel", "2026-11-05T15:00:00+05:30")],
};
const feedBody = (rows: unknown[]) => ({ ok: true, total: rows.length, facets: {}, rows, provenance: { error: null } });

// ── deals: backend/routes/markets_desk.py deals ── MOCK — not real data. Eight on the latest day, one the day before.
const deal = (symbol: string, value_cr: number, side: string, date = T, kind = "block") => ({
  date, kind, symbol, client_name: `FIXTURE ${symbol} FUND`, side, quantity: 100000, avg_price: 100, value_cr, pct_of_shares: 0.5,
  shares_period_end: "2026-09-30", close_on_day: 101, prev_close: 99, next_date: null, next_close: null, price_vs_close_pct: -1, ingested_at: "2026-11-05T19:00:00+05:30",
});
const DEALS = {
  as_of: T, from: "2026-11-01", days: 5, kind: "all", source: "NSE bulk and block deals (mock)", disclosure: "Exchange disclosure", count: 9, total: 9,
  rows: [deal("DLA", 50, "BUY"), deal("DLB", 80, "SELL"), deal("DLC", 10, "BUY", T, "bulk"), deal("DLD", 70, "BUY"), deal("DLE", 5, "SELL", T, "bulk"),
    deal("DLF", 60, "SELL"), deal("DLG", 40, "BUY"), deal("DLH", 30, "BUY"), deal("DLOLD", 999, "BUY", PREV)],
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

interface Calls { board: URL[]; feed: URL[] }
type Fail = Partial<Record<"board" | "prev" | "feed" | "deals" | "flows" | "circulars" | "sectors", number>>;

async function setup(page: Page, opts: { fail?: Fail; empty?: boolean; fixedClock?: boolean; feeds?: Record<string, unknown[]> } = {}): Promise<Calls> {
  const calls: Calls = { board: [], feed: [] };
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
    calls.feed.push(u);
    if (fail.feed) return json(r, { detail: "upstream_unavailable" }, fail.feed);
    const cat = u.searchParams.get("category");
    if (opts.empty) return json(r, feedBody([]));
    const feeds = { ...FEEDS, ...(opts.feeds ?? {}) };
    return json(r, feedBody(cat ? feeds[cat] ?? [] : Object.values(feeds).flat()));
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
const params = (page: Page) => new URL(page.url()).searchParams;
const BANNED = /\b(buy|sell|sold|bought|target|stop[- ]?loss|recommend\w*|pick\w*|suggest\w*|beat|miss(ed)?)\b/i;

test.describe("MOCK — not real data: Market Intelligence news ticker (desktop)", () => {
  test.use({ viewport: { width: 1440, height: 1000 } });

  test("NT-1 the ticker sits above the event list on Market Intelligence only", async ({ page }) => {
    await setup(page);
    await page.goto(INTEL);
    const ticker = page.getByTestId("md-ticker");
    await expect(ticker).toBeVisible(SLOW);
    await expect(ticker).toHaveAttribute("aria-label", "Market news ticker");
    const tBox = await page.getByTestId("desk-panel-ticker").boundingBox();
    const iBox = await page.getByTestId("desk-panel-intel").boundingBox();
    expect(tBox && iBox && tBox.y < iBox.y).toBe(true);
    await expect(page.getByTestId("md-ticker-label")).toContainText("MARKET WIRE");
    for (const view of ["smartmoney", "sectors", "research", "screener"]) {
      await page.goto(`${DESK}?tab=market&view=${view}`);
      await expect(page.getByTestId("md-head")).toHaveAttribute("data-view", view, SLOW);
      await expect(page.getByTestId("md-ticker"), view).toHaveCount(0);
    }
  });

  test("NT-2/3/4 results: figures vs the same quarter last year, losses in words, filed-pending, previous day", async ({ page }) => {
    await setup(page);
    await page.goto(INTEL);
    await expect(tape(page)).toBeVisible(SLOW);
    const decla = item(page, `res-${evId(T, "DECLA")}`);
    await expect(decla).toContainText("DECLA");
    await expect(decla).toContainText("Q2 FY27 results");
    await expect(decla.getByTestId("md-ticker-fig-revenue")).toHaveText(/Rev\s*₹1,100 cr\s*▲10\.0% YoY/);
    await expect(decla.getByTestId("md-ticker-fig-pat")).toHaveText(/PAT\s*₹90 cr\s*▼10\.0% YoY/);
    await expect(decla).toContainText("16:10");
    const loss = item(page, `res-${evId(T, "LOSSA")}`);
    await expect(loss.getByTestId("md-ticker-fig-pat")).toContainText("turned to a loss");
    await expect(loss.getByTestId("md-ticker-fig-pat")).not.toContainText("%");
    const gain = item(page, `res-${evId(T, "GAINB")}`);
    await expect(gain.getByTestId("md-ticker-fig-pat")).toContainText("from a loss");
    await expect(gain.getByTestId("md-ticker-fig-revenue")).toHaveText(/Rev\s*₹300 cr$/);
    // previous weekday's declared results, dated
    const prev = item(page, `res-${evId(PREV, "PREVA")}`);
    await expect(prev.getByTestId("md-ticker-fig-revenue")).toContainText("▲25.0% YoY");
    await expect(prev.getByTestId("md-ticker-fig-pat")).toContainText("▲20.0% YoY");
    await expect(prev).toContainText("4 Nov");
    // newest filing first: LOSSA 17:00, DECLA 16:10, GAINB 15:00, PREVA 4 Nov
    const keys = await tape(page).locator('[data-tag="results"]').evaluateAll((els) => els.map((e) => e.getAttribute("data-testid")));
    expect(keys).toEqual([`md-ticker-item-res-${evId(T, "LOSSA")}`, `md-ticker-item-res-${evId(T, "DECLA")}`, `md-ticker-item-res-${evId(T, "GAINB")}`, `md-ticker-item-res-${evId(PREV, "PREVA")}`]);
    // filed, figures pending
    const pend = item(page, `filed-${evId(T, "PENDA")}`);
    await expect(pend).toContainText("figures not loaded yet");
    await expect(pend).toContainText("16:05");
    // F&O by default: the non-F&O company is not on the tape
    await expect(item(page, `res-${evId(T, "WIDEC")}`)).toHaveCount(0);
  });

  test("NT-5 due today and tomorrow are grouped; tomorrow shows 15 and '+3 more'", async ({ page }) => {
    await setup(page);
    await page.goto(INTEL);
    const due = item(page, `due-${T}`);
    await expect(due).toContainText("Thu 5 Nov · 2 companies", SLOW);
    await expect(due.getByTestId("md-ticker-sym-due-DUEA")).toBeVisible();
    await expect(due.getByTestId("md-ticker-sym-due-DUEB")).toBeVisible();
    const tom = item(page, `tomorrow-${TOM}`);
    await expect(tom).toContainText("Results tomorrow");
    await expect(tom).toContainText("Fri 6 Nov · 18 companies");
    await expect(tom.locator('[data-testid^="md-ticker-sym-tomorrow-"]')).toHaveCount(15);
    await expect(tom.getByTestId("md-ticker-more-tomorrow")).toHaveText("+3 more ›");
    await expect(tom.getByTestId("md-ticker-sym-tomorrow-TOMWIDE")).toHaveCount(0);
  });

  test("NT-6/7 filings since the previous weekday, one tag each; the old one, management and the results outcome are left out", async ({ page }) => {
    await setup(page);
    await page.goto(INTEL);
    await expect(tape(page)).toBeVisible(SLOW);
    const expectTag = async (id: string, tag: string, symbol: string, text: string, when: string) => {
      const it = item(page, `filing-${id}`);
      await expect(it, id).toHaveAttribute("data-tag", tag);
      await expect(it, id).toContainText(symbol);
      await expect(it, id).toContainText(text);
      await expect(it, id).toContainText(when);
    };
    await expectTag("ord-1", "order", "ORDA", "Bagging/Receiving of orders/contracts", "17:01");
    await expectTag("mna-1", "mna", "MNAA", "Acquisition", "17:05");
    await expectTag("div-1", "dividend", "DIVA", "Dividend", "4 Nov");
    await expectTag("bb-1", "buyback", "BBKA", "Buyback", "12:00");
    await expectTag("cap-1", "capex", "CAPX", "Capacity addition", "13:29");
    await expectTag("qip-1", "fundraise", "QIPA", "Fund raising", "11:00");
    await expectTag("rat-1", "rating", "RATA", "Credit Rating", "17:18");
    await expect(item(page, "filing-ord-old")).toHaveCount(0);
    await expect(item(page, "filing-mgmt-1")).toHaveCount(0);
    await expect(item(page, "filing-mna-outcome")).toHaveCount(0);
    // tag order on the tape: results → order → M&A → buyback → dividend → capex → fundraise → rating → deals → flows → SEBI → sector
    const tags = await tape(page).locator("[data-tag]").evaluateAll((els) => els.map((e) => e.getAttribute("data-tag")));
    const firsts = tags.filter((t, i) => tags.indexOf(t) === i);
    expect(firsts).toEqual(["results", "filed", "due", "tomorrow", "order", "mna", "buyback", "dividend", "capex", "fundraise", "rating", "deal", "flows", "sebi", "sector"]);
  });

  test("NT-8/9/10 deals of the latest day (6 largest), FII / DII, SEBI in the window, sector moves of 1% or more", async ({ page }) => {
    await setup(page);
    await page.goto(INTEL);
    await expect(tape(page)).toBeVisible(SLOW);
    const deals = await tape(page).locator('[data-tag="deal"]').evaluateAll((els) => els.map((e) => (e.textContent ?? "").match(/DL[A-Z]+?(?=FIXTURE)/)?.[0]));
    expect(deals).toEqual(["DLB", "DLD", "DLF", "DLA", "DLG", "DLH"]);
    const dlb = tape(page).locator('[data-tag="deal"]').first();
    await expect(dlb).toContainText("FIXTURE DLB FUND disposed of 1.00 L shares");
    await expect(dlb).toContainText("₹80 cr");
    await expect(dlb).toContainText("0.50%");
    await expect(tape(page).locator('[data-tag="deal"]').nth(1)).toContainText("acquired");
    const flows = tape(page).locator('[data-tag="flows"]');
    await expect(flows).toHaveCount(1);
    await expect(flows.getByTestId("md-ticker-fig-fii")).toContainText("−₹1,235 cr");
    await expect(flows.getByTestId("md-ticker-fig-dii")).toContainText("+₹2,000 cr");
    const sebi = tape(page).locator('[data-tag="sebi"]');
    await expect(sebi).toHaveCount(1);
    await expect(sebi).toContainText("Fixture circular on investor charters");
    const sec = tape(page).locator('[data-tag="sector"]');
    await expect(sec).toHaveCount(2);
    await expect(sec.nth(0)).toContainText("Nifty IT rose 2.10%");
    await expect(sec.nth(1)).toContainText("Nifty Metal fell 1.40%");
  });

  test("NT-11 one board read for all NSE; the switch filters it (F&O default, Nifty 50, All NSE)", async ({ page }) => {
    const calls = await setup(page);
    await page.goto(INTEL);
    await expect(tape(page)).toBeVisible(SLOW);
    await expect(page.getByTestId("md-ticker-uni-fno")).toHaveAttribute("aria-pressed", "true");
    // the ticker's reads are universe=all (the Events calendar below makes its own F&O read of today and tomorrow)
    const tickerReads = () => calls.board.filter((u) => u.searchParams.get("universe") === "all");
    await expect.poll(() => tickerReads().length).toBe(2);
    const boards = tickerReads().map((u) => `${u.searchParams.get("from")}..${u.searchParams.get("to")}`);
    expect(boards.sort()).toEqual([`${PREV}..${PREV}`, `${T}..${TOM}`].sort());
    await page.getByTestId("md-ticker-uni-n50").click();
    await expect(item(page, `res-${evId(T, "DECLA")}`)).toBeVisible();
    await expect(item(page, `res-${evId(T, "LOSSA")}`)).toHaveCount(0);
    await expect(item(page, `tomorrow-${TOM}`)).toHaveCount(0);
    await page.getByTestId("md-ticker-uni-all").click();
    await expect(item(page, `res-${evId(T, "WIDEC")}`)).toContainText("▲100.0% YoY");
    await expect(item(page, `tomorrow-${TOM}`)).toContainText("19 companies");
    // switching filters the one read; nothing is fetched again and no n50 read is made
    expect(tickerReads().length).toBe(2);
    expect(calls.board.filter((u) => u.searchParams.get("universe") === "n50")).toHaveLength(0);
  });

  test("NT-23 Show: Everything keeps the newest 8 orders; a kind shows all of it, with its count", async ({ page }) => {
    await setup(page);
    await page.goto(INTEL);
    await expect(tape(page)).toBeVisible(SLOW);
    await expect(page.getByTestId("md-ticker-focus-all")).toHaveAttribute("aria-pressed", "true");
    const orderKeys = () => tape(page).locator('[data-tag="order"]').evaluateAll((els) => els.map((e) => e.getAttribute("data-testid")));
    const all = await orderKeys();
    expect(all).toHaveLength(8);
    expect(all[0]).toBe("md-ticker-item-filing-ord-1");
    await expect(page.getByTestId("md-ticker-focus-orders")).toHaveText("Orders10");
    await expect(page.getByTestId("md-ticker-focus-mna")).toHaveText("M&A1");
    // F&O results: 4 declared + 1 filed + 2 due today + 18 tomorrow
    await expect(page.getByTestId("md-ticker-focus-results")).toHaveText("Results25");
    await page.getByTestId("md-ticker-focus-orders").click();
    await expect(page.getByTestId("md-ticker-focus-orders")).toHaveAttribute("aria-pressed", "true");
    await expect.poll(async () => (await orderKeys()).length).toBe(10);
    const tags = await tape(page).locator("[data-tag]").evaluateAll((els) => [...new Set(els.map((e) => e.getAttribute("data-tag")))]);
    expect(tags).toEqual(["order"]);
    await page.getByTestId("md-ticker-focus-market").click();
    const market = await tape(page).locator("[data-tag]").evaluateAll((els) => [...new Set(els.map((e) => e.getAttribute("data-tag")))]);
    expect(market).toEqual(["deal", "flows", "sebi", "sector"]);
  });

  test("NT-24 a kind whose read hits the row limit before the window's start says from when it is covered", async ({ page }) => {
    // the M&A read returns its limit of 20 rows, all from today 09:00–09:19, so the tape covers M&A only from 09:00
    const full = Array.from({ length: 20 }, (_, i) => frow(`mna-f${i}`, `MNAF${i}`, "Mna", "Acquisition", `2026-11-05T09:${String(i).padStart(2, "0")}:00+05:30`));
    await setup(page, { feeds: { mna: full } });
    await page.goto(INTEL);
    await expect(tape(page)).toBeVisible(SLOW);
    await expect(page.getByTestId("md-ticker-reach")).toHaveText(
      "Each kind reads the newest 20 filings (40 for orders), so these start after Wed 4 Nov: M&A from 5 Nov, 09:00 IST.",
    );
    // the default fixture stays under every limit: no such line
    const p2 = await page.context().newPage();
    await setup(p2);
    await p2.goto(INTEL);
    await expect(p2.getByTestId("md-ticker-tape")).toBeVisible(SLOW);
    await expect(p2.getByTestId("md-ticker-reach")).toHaveCount(0);
  });

  test("NT-12/13 a filing, a deal and the FII / DII item open their event in the list below", async ({ page }) => {
    await setup(page);
    await page.goto(INTEL);
    await expect(tape(page)).toBeVisible(SLOW);
    await page.getByTestId("md-ticker-pause").click();
    await item(page, "filing-ord-1").getByRole("button").click();
    await expect.poll(() => params(page).get("in_chip")).toBe("orders");
    expect(params(page).get("in_ev")).toBe("ord-1");
    await expect(page.getByTestId("desk-panel-intel").getByTestId("desk-event-title").first()).toContainText("Bagging/Receiving of orders/contracts", SLOW);
    await tape(page).locator('[data-tag="deal"]').first().getByRole("button").click();
    await expect.poll(() => params(page).get("in_chip")).toBe("deals");
    expect(params(page).get("in_ev")).toMatch(/^deal-2026-11-05-block-DLB-/);
    await tape(page).locator('[data-tag="flows"]').getByRole("button").click();
    await expect.poll(() => params(page).get("in_chip")).toBe("flows");
    expect(params(page).get("in_ev")).toBe(`fiidii-${T}`);
  });

  test("NT-14 a results item opens that company in the Events calendar; the link is used once", async ({ page }) => {
    await setup(page);
    await page.goto(INTEL);
    await expect(tape(page)).toBeVisible(SLOW);
    await page.getByTestId("md-ticker-pause").click();
    await item(page, `res-${evId(T, "DECLA")}`).getByRole("button").click();
    const panel = page.getByTestId("desk-panel-events").getByTestId("events-panel");
    await expect(panel).toContainText("DECLA Ltd (mock)", SLOW);
    await expect.poll(() => params(page).get("ev_open")).toBeNull();
    expect(params(page).get("ev_uni")).toBeNull();
    // a grouped company (tomorrow) opens its own panel too
    await page.getByTestId("events-panel-close").first().click();
    await tape(page).getByTestId("md-ticker-sym-tomorrow-TOM02").click();
    await expect(panel).toContainText("TOM02 Ltd (mock)", SLOW);
  });

  test("NT-15/16 pause, hover and focus stop the tape; the copy is hidden from assistive technology", async ({ page }) => {
    await setup(page);
    await page.goto(INTEL);
    await expect(tape(page)).toBeVisible(SLOW);
    const track = page.getByTestId("md-ticker-track");
    const state = () => track.evaluate((el) => getComputedStyle(el).animationPlayState);
    const name = () => track.evaluate((el) => getComputedStyle(el).animationName);
    expect(await name()).toBe("mkt-marquee");
    expect(await state()).toBe("running");
    const pause = page.getByTestId("md-ticker-pause");
    await pause.click();
    await expect(pause).toHaveAttribute("aria-pressed", "true");
    await expect(pause).toHaveAccessibleName("Play the ticker");
    expect(await state()).toBe("paused");
    await pause.click();
    await expect(pause).toHaveAttribute("aria-pressed", "false");
    await page.mouse.move(0, 0);
    expect(await state()).toBe("running");
    await page.getByTestId("md-ticker-view").hover();
    expect(await state()).toBe("paused");
    await page.mouse.move(0, 0);
    // keyboard focus inside the tape pauses it
    await item(page, "filing-ord-1").getByRole("button").focus();
    await expect(track).toHaveAttribute("data-paused", "true");
    // the second copy: aria-hidden, no tab stops; the first copy's buttons are named
    const copy = page.getByTestId("md-ticker-tape-copy");
    await expect(copy).toHaveAttribute("aria-hidden", "true");
    const tabbable = await copy.locator("button").evaluateAll((els) => els.filter((e) => e.getAttribute("tabindex") !== "-1").length);
    expect(tabbable).toBe(0);
    await expect(item(page, "filing-ord-1").getByRole("button")).toHaveAccessibleName(/Order, ORDA, Bagging\/Receiving of orders\/contracts, 17:01/);
  });

  test("NT-17 states: loading, partial, all failed with retry, nothing in the window", async ({ page }) => {
    // partial: deals and the board fail; filings still show, and the note names what did not load
    await setup(page, { fail: { deals: 500, board: 500 } });
    await page.goto(INTEL);
    await expect(item(page, "filing-ord-1")).toBeVisible(SLOW);
    await expect(page.getByTestId("md-ticker-partial")).toContainText("Not loaded: results, deals.");
    await expect(page.getByTestId("md-ticker-partial-retry")).toBeVisible();

    const p2 = await page.context().newPage();
    await setup(p2, { fail: { board: 500, prev: 500, feed: 500, deals: 500, flows: 500, circulars: 500, sectors: 500 } });
    await p2.goto(INTEL);
    await expect(p2.getByTestId("md-ticker-error")).toContainText("The ticker’s sources didn’t load.", SLOW);
    await expect(p2.getByTestId("md-ticker-retry")).toBeVisible();

    const p3 = await page.context().newPage();
    await setup(p3, { empty: true });
    await p3.goto(INTEL);
    await expect(p3.getByTestId("md-ticker-empty")).toContainText("Nothing on the wire since Wed 4 Nov", SLOW);

    const p4 = await page.context().newPage();
    await setup(p4);
    await p4.route("**/api/markets/events-calendar/expectations*", () => undefined); // never answers
    await p4.route("**/api/filings/feed*", () => undefined);
    await p4.route("**/api/markets/deals*", () => undefined);
    await p4.route("**/api/markets/fii-dii*", () => undefined);
    await p4.route("**/api/markets/circulars*", () => undefined);
    await p4.route("**/api/markets/sector-returns", () => undefined);
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

test.describe("MOCK — not real data: news ticker refresh, reduced motion and phone", () => {
  test("NT-20 filings are re-read every minute while the ticker is on screen", async ({ page }) => {
    await page.clock.install({ time: NOW });
    const calls = await setup(page, { fixedClock: false });
    await page.goto(INTEL);
    await expect(tape(page)).toBeVisible(SLOW);
    const orders = () => calls.feed.filter((u) => u.searchParams.get("category") === "orders").length;
    const before = orders();
    await page.clock.runFor(61_000);
    await expect.poll(orders).toBeGreaterThan(before);
  });

  test("NT-15b reduced motion: no animation, one copy, scrolls sideways, no Pause button", async ({ page }) => {
    await page.emulateMedia({ reducedMotion: "reduce" });
    await setup(page);
    await page.goto(INTEL);
    await expect(tape(page)).toBeVisible(SLOW);
    await expect(page.getByTestId("md-ticker-tape-copy")).toHaveCount(0);
    await expect(page.getByTestId("md-ticker-pause")).toHaveCount(0);
    const anim = await page.getByTestId("md-ticker-track").evaluate((el) => getComputedStyle(el).animationName);
    expect(anim).toBe("none");
    const view = page.getByTestId("md-ticker-view");
    expect(await view.evaluate((el) => getComputedStyle(el).overflowX)).toBe("auto");
    expect(await view.evaluate((el) => el.scrollWidth > el.clientWidth)).toBe(true);
  });

  test("NT-18 phone 390 px: no sideways page scroll; the controls sit under the band; a results tap opens the sheet", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await setup(page);
    await page.goto(INTEL);
    await expect(tape(page)).toBeVisible(SLOW);
    await expect(page.getByTestId("md-ticker-label")).toContainText("WIRE");
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
    await item(page, `res-${evId(T, "WIDEC")}`).getByRole("button").click();
    await expect(page.getByTestId("events-sheet")).toContainText("WIDEC Ltd (mock)", SLOW);
    await expect(page.getByTestId("events-m-uni")).toContainText("Showing all NSE companies");
    await page.getByTestId("events-sheet-close").click();
    await page.getByTestId("events-m-uni-back").click();
    await expect(page.getByTestId("events-m-uni")).toHaveCount(0);
    await page.screenshot({ path: "e2e/screenshots/desk-news-ticker/phone-intel.png" });
  });
});
