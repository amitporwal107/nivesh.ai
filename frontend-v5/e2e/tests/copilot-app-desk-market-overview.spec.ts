/**
 * Market Overview (desk tab 01, the redesign's step 2) — MO-1 … MO-31 of test_reports/desk_market_overview_TESTCASES.md.
 *
 * The ideas, their plans, GET /api/desk/trade-plans/{id} (with the universal risk service's REAL allow / reduce / block
 * answers), the risk profile and the stored AI watchlist day come from `contract-decision-card.json`, which
 * backend/tests/test_decision_card_contract.py rebuilds from the REAL routes (cash: MOCK — not real data, the
 * RELIANCE-like world of backend/tests/test_strategy_plan.py; F&O: the REAL 2026-10-21 staging capture). The market tape is
 * `markets-home.json` (a TEST FIXTURE). Everything else is an inline MOCK — not real data — in the route's real shape.
 * Expected figures are worked out from the payloads here, never copied from the screen. Mocked APIs, production build.
 */
import { test, expect, type Page, type Route } from "@playwright/test";
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";
import { mockApi } from "../helpers/api-mock";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const load = (name: string) => JSON.parse(fs.readFileSync(path.join(__dirname, "..", "fixtures", name), "utf-8"));
const CARD = load("contract-decision-card.json");
const HOME = load("markets-home.json");
const clone = <T,>(x: T): T => JSON.parse(JSON.stringify(x));
const DESK = "/v5/app/trader/desk";
const SLOW = { timeout: 15_000 };
const json = (route: Route, body: unknown, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });

// ── the plans, as the routes send them ───────────────────────────────────
const IDEA = CARD.cash.ideas_response.ideas[0];
const CASH = IDEA.trade_plan;
const SYM: string = IDEA.symbol;
const FNO_GET = CARD.fno.trade_plan_response;
const FNO = FNO_GET.plan;
const A = CARD.cash.trade_plan_response.account_size;
/** "Today" for every case: Tue 20 Oct 2026, 15:00 IST — the session of the fixture's risk decisions (at 10:30 IST). */
const NOW = new Date("2026-10-20T15:00:00+05:30");

const n2 = (n: number) => new Intl.NumberFormat("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(n);
const rs = (n: number) => `₹${n2(n)}`;
const int = (n: number) => new Intl.NumberFormat("en-IN").format(n);
const pct2 = (n: number) => `${n > 0 ? "+" : n < 0 ? "−" : ""}${n2(Math.abs(n))}%`;
const targets = (tp: { targets: Array<{ price: number; r_multiple: number }> }) => tp.targets.map((t) => `${rs(t.price)} (${n2(t.r_multiple)}R)`).join(" · ");

// ── MOCK — not real data: the routes this tab adds to the decision-card world ──
/** GET /api/risk/freshness (backend routes/risk_controls.py `freshness`, no symbol), the market state as judged. */
const freshness = (m: Partial<Record<string, unknown>> = {}, reference = "2026-10-19") => ({
  symbol: null,
  inputs: {
    market_state: {
      source: "desk regime (MOCK)", as_of: "2026-10-19", age_sessions: 0, budget: 2, ok: true, reason: null, version: "freshness-v1",
      status: "ok", regime: "BEAR", vix: 14.2, key: "bearish", ...m,
    },
    last_close: { status: "not_checked", ok: null, reason: "give ?symbol= to check a share's inputs" },
    sector: { status: "not_checked", ok: null, reason: "give ?symbol= to check a share's inputs" },
  },
  all_ok: true, reference_session: reference, as_of: "2026-10-20T09:30:00+00:00",
  budgets: { last_close: 2, market_state: 2, sector: null }, freshness_version: "freshness-v1", risk_policy_version: "universal-risk-v1",
});
/** GET /api/markets/sector-returns: seven NSE sector indices (MOCK). */
const SECTORS = {
  as_of: "2026-10-19", source: "NSE index close (MOCK)", sessions: { "1d": 1, "1w": 5, "1m": 21 },
  sectors: [
    { index: "Nifty IT", sector: "IT", close: 1, date: "2026-10-19", ret_1d_pct: 1.42, ret_1w_pct: 2, ret_1m_pct: 3 },
    { index: "Nifty Pharma", sector: "Pharma", close: 1, date: "2026-10-19", ret_1d_pct: 0.8, ret_1w_pct: 1, ret_1m_pct: 1 },
    { index: "Nifty FMCG", sector: "FMCG", close: 1, date: "2026-10-19", ret_1d_pct: 0.3, ret_1w_pct: 1, ret_1m_pct: 1 },
    { index: "Nifty Auto", sector: "Auto", close: 1, date: "2026-10-19", ret_1d_pct: 0.1, ret_1w_pct: 1, ret_1m_pct: 1 },
    { index: "Nifty Bank", sector: "Banks", close: 1, date: "2026-10-19", ret_1d_pct: -0.4, ret_1w_pct: 1, ret_1m_pct: 1 },
    { index: "Nifty Realty", sector: "Realty", close: 1, date: "2026-10-19", ret_1d_pct: -1.6, ret_1w_pct: 1, ret_1m_pct: 1 },
    { index: "Nifty Metal", sector: "Metal", close: 1, date: "2026-10-19", ret_1d_pct: -0.9, ret_1w_pct: 1, ret_1m_pct: 1 },
  ],
};
/** GET /api/filings/feed rows (backend routes/filings.py), MOCK. */
const filing = (id: string, code: string, date: string, category: string, docLabel: string) => ({
  id, ticker: code, code, name: `${code} Ltd (MOCK)`, date, category, impact: "high", sentiment: null, docLabel,
  url: null, one: null, period: null, metric: null, hasInsights: false, exchange: "NSE",
});
const F_TODAY = filing("mo-ev-1", SYM, "2026-10-20T11:05:00+05:30", "Earnings", "Financial results for the quarter (MOCK)");
const F_OTHER = filing("mo-ev-2", "ZZZOTHER", "2026-10-20T12:00:00+05:30", "Earnings", "Results of a name not on the ideas (MOCK)");
const F_YESTERDAY = filing("mo-ev-3", SYM, "2026-10-19T16:00:00+05:30", "Orders", "Order win yesterday (MOCK)");
const feed = (rows: unknown[]) => ({ ok: true, total: rows.length, facets: {}, rows });

/** The stored list, with ICICIBANK carried for 3 sessions since 15 Oct (MOCK on top of the fixture's real day). */
function carriedDay() {
  const day = clone(CARD.ai_watchlist_day);
  const e = day.cash.find((x: { symbol: string }) => x.symbol === SYM);
  e.days_on_list = 3;
  e.earlier_list_dates = ["2026-10-16", "2026-10-15"];
  e.carried = {
    sessions: 3, from: "2026-10-15",
    first: { list_date: "2026-10-15", entry: 1190, entry_kind: "price", stop: 1150, target: 1270, plan_id: "tp_mock_first", basis: "trade_plan" },
    today: { list_date: day.list_date, entry: CASH.entry.price, entry_kind: "price", stop: CASH.stop.price, target: 1280, plan_id: CASH.plan_id, basis: "trade_plan" },
  };
  return day;
}

interface Opts {
  fresh?: { status: number; body: unknown }; profile?: { status: number; body: unknown }; ideas?: unknown; day?: unknown;
  plans?: Record<string, { status: number; body: unknown }>; paperStatus?: Array<{ status: number; body: unknown }>; killSwitch?: boolean;
  phone?: boolean; filings?: unknown[];
}
interface Seen { paperGets: string[]; paperPosts: Array<Record<string, unknown>>; alertGets: string[] }

async function setup(page: Page, o: Opts = {}): Promise<Seen> {
  const seen: Seen = { paperGets: [], paperPosts: [], alertGets: [] };
  await page.clock.setFixedTime(NOW);
  if (o.phone) await page.setViewportSize({ width: 390, height: 844 });
  await mockApi(page, "populated");
  await page.route("**/api/markets/home", (r) => json(r, HOME));
  await page.route("**/api/chat/sessions", (r) => json(r, []));
  await page.route("**/api/positional/watchlist*", (r) => json(r, { as_of_date: "2026-10-19", buckets: { breakout_confirmed: [], pre_breakout: [], true_accumulation: [], trend_continuation: [] } }));
  await page.route("**/api/positional/picks*", (r) => json(r, { signal_date: "2026-10-19", count: 0, picks: [] }));
  await page.route("**/api/move-odds/**", (r) => json(r, { detail: "feature_not_enabled" }, 403));
  await page.route("**/api/live/**", (r) => json(r, { available: false, reason: "MOCK: feed off", quotes: {}, mode: "expired", session: "closed", stale: true }));
  await page.route("**/api/risk/freshness*", (r) => (o.fresh ? json(r, o.fresh.body, o.fresh.status) : json(r, freshness())));
  await page.route("**/api/markets/sector-returns", (r) => json(r, SECTORS));
  await page.route("**/api/markets/fii-dii*", (r) => json(r, { ok: true, as_of: "2026-10-19", daily: [], monthly: [] }));
  await page.route("**/api/markets/deals*", (r) => json(r, { ok: true, rows: [], total: 0 }));
  await page.route("**/api/markets/circulars*", (r) => json(r, { ok: true, rows: [], total: 0 }));
  await page.route("**/api/filings/feed*", (r) => json(r, feed(o.filings ?? [F_TODAY, F_OTHER, F_YESTERDAY])));
  await page.route("**/api/desk/strategy/ideas", (r) => json(r, o.ideas ?? CARD.cash.ideas_response));
  await page.route("**/api/desk/strategy/top", (r) => json(r, CARD.fno.top_response));
  // MOCK: the levels engine and the payoff are not asked for here (the plans carry the levels).
  await page.route("**/api/desk/strategy/levels", (r) => json(r, { valid: false, version: "strategy-levels-v2", problems: [{ code: "mock", message: "MOCK" }] }));
  await page.route("**/api/desk/strategy/payoff", (r) => json(r, { valid: false, problems: [{ code: "mock", message: "MOCK" }], warnings: [] }));
  const plans: Record<string, { status: number; body: unknown }> = {
    [CASH.plan_id]: { status: 200, body: CARD.cash.trade_plan_response }, [FNO.plan_id]: { status: 200, body: FNO_GET }, ...(o.plans ?? {}),
  };
  await page.route("**/api/desk/trade-plans/*", (r) => {
    const id = decodeURIComponent(new URL(r.request().url()).pathname.split("/").pop() as string);
    const a = plans[id];
    return a ? json(r, a.body, a.status) : json(r, { detail: "plan_not_found" }, 404);
  });
  await page.route("**/api/risk/profile", (r) => (o.profile ? json(r, o.profile.body, o.profile.status) : json(r, CARD.risk_profile)));
  // MOCK: the controls as GET /api/risk/status reports them.
  await page.route("**/api/risk/status", (r) => json(r, { kill_switch: !!o.killSwitch, halted: false, policy_version: "MOCK" }));
  await page.route("**/api/desk/ai-watchlist*", (r) => json(r, o.day ?? CARD.ai_watchlist_day));
  await page.route("**/api/fno/scan/buildup*", (r) => json(r, { as_of: "2026-10-19", indices: [], counts: {}, sources: {}, master: {}, risk_flag_text: {}, rows: [] }));
  await page.route("**/api/desk/alerts*", (r) => { seen.alertGets.push(r.request().url()); return json(r, { as_of: "2026-10-19", alerts: [] }); });
  await page.route("**/api/desk/paper-account", (r) => json(r, CARD.paper_account));
  const answers = [...(o.paperStatus ?? [])];
  await page.route("**/api/desk/paper-trades*", (r) => {
    if (r.request().method() === "POST") {
      seen.paperPosts.push(r.request().postDataJSON());
      const a = answers.shift() ?? { status: 201, body: { trade: { id: `t${seen.paperPosts.length}` } } };
      return json(r, a.body, a.status);
    }
    seen.paperGets.push(r.request().url());
    return json(r, { as_of: "2026-10-19", trades: [], summary: null });
  });
  return seen;
}

const panel = (page: Page) => page.getByTestId("desk-panel-overview");
const stockRow = (page: Page) => page.getByTestId(`desk-top10-stock-${SYM}`);
const ready = (card: ReturnType<Page["getByTestId"]>) => expect(card).toHaveAttribute("data-store", "read", SLOW);
const params = (page: Page) => new URL(page.url()).searchParams;

// ── the page ──────────────────────────────────────────────────────────────

test.describe("MOCK — not real data: Market Overview · the page", () => {
  test("MO-1 the design's panels in order: KPIs, market regime, Top AI candidates, paper trades, alerts and events; no old Overview cards or pulse", async ({ page }) => {
    await setup(page);
    await page.goto(DESK);
    const p = panel(page);
    await expect(p.getByTestId("market-overview")).toBeVisible(SLOW);
    const ids = ["mo-kpis", "mo-strip", "desk-top10", "mo-paper", "mo-events"];
    for (const id of ids) await expect(p.getByTestId(id)).toBeVisible(SLOW);
    const tops = await Promise.all(ids.map(async (id) => (await p.getByTestId(id).boundingBox())?.y ?? -1));
    expect(tops).toEqual([...tops].sort((a, b) => a - b));
    for (const gone of ["desk-overview", "desk-pulse", "desk-panel-pulse", "desk-open-trades-line", "desk-paper-trades", "desk-snapshot-card", "desk-risk-card"]) {
      await expect(p.getByTestId(gone)).toHaveCount(0);
    }
    await expect(page.getByTestId("mo-strip")).toContainText("Market regime");
    await expect(page.getByTestId("desk-top10")).toContainText("Top AI candidates");
    await expect(page.getByTestId("mo-events")).toContainText("Alerts and events");
    // Step 3 PR B: "All scanner candidates" is Trade Desk › AI Scanner › Ranked candidates.
    await expect(page.getByTestId("desk-scanner-toggle")).toHaveCount(0);
    await expect(page.getByTestId("desk-panel-scanner")).toHaveCount(0);
  });

  test("MO-31 All scanner candidates is Trade Desk › AI Scanner › Ranked candidates: ?tab=scanner and ?section=scanner open it", async ({ page }) => {
    await setup(page);
    for (const from of ["?tab=scanner", "?tab=overview&section=scanner"]) {
      await page.goto(`${DESK}${from}`);
      await expect.poll(() => params(page).get("tab"), from).toBe("trade");
      await expect.poll(() => params(page).get("view"), from).toBe("scanner");
      await expect.poll(() => params(page).get("sub"), from).toBe("ranked");
    }
    await expect(page.getByTestId("desk-panel-scanner")).toBeVisible(SLOW);
  });
});

// ── the market strip ──────────────────────────────────────────────────────

test.describe("MOCK — not real data: Market Overview · the market strip", () => {
  test("MO-2 / MO-3 / MO-8 / MO-9 indices, breadth, FII / DII and sector moves from their routes", async ({ page }) => {
    await setup(page);
    await page.goto(DESK);
    const strip = page.getByTestId("mo-strip");
    await expect(strip).toBeVisible(SLOW);
    const ix = (name: string) => HOME.indices.find((i: { name: string }) => i.name === name);
    for (const [key, name] of [["nifty", "Nifty 50"], ["banknifty", "Nifty Bank"], ["vix", "India VIX"]] as const) {
      const cell = strip.locator(`[data-testid="mo-index"][data-index="${key}"]`);
      await expect(cell.getByTestId("mo-index-value")).toHaveText(n2(ix(name).value));
      await expect(cell.getByTestId("mo-index-change")).toContainText(`(${pct2(ix(name).change_pct)})`);
      await expect(cell.getByTestId("mo-index-stamp")).toContainText("End of day");
    }
    const b = HOME.breadth;
    const advPct = (b.advances / (b.advances + b.declines + b.unchanged)) * 100;
    await expect(strip.getByTestId("mo-breadth-value")).toHaveText(`${new Intl.NumberFormat("en-IN", { minimumFractionDigits: 1, maximumFractionDigits: 1 }).format(advPct)}%`);
    await expect(strip.getByTestId("mo-breadth-counts")).toHaveText(`${int(b.advances)} advancing · ${int(b.declines)} declining`);
    const f = HOME.fii_dii;
    await expect(strip.getByTestId("mo-flows-fii")).toHaveText(`FII ${f.fii_net_cr < 0 ? "−" : "+"}₹${int(Math.abs(f.fii_net_cr))} Cr`);
    await expect(strip.getByTestId("mo-flows-dii")).toHaveText(`DII ${f.dii_net_cr < 0 ? "−" : "+"}₹${int(Math.abs(f.dii_net_cr))} Cr`);
    await expect(strip.getByTestId("mo-flows")).toContainText("12 Oct");
    // Sectors: the top three by 1-day return, then the bottom three, most negative first.
    const sorted = [...SECTORS.sectors].sort((x, y) => y.ret_1d_pct - x.ret_1d_pct);
    await expect(strip.getByTestId("mo-sector-up")).toHaveText(sorted.slice(0, 3).map((s) => `${s.sector} ${pct2(s.ret_1d_pct)}`));
    await expect(strip.getByTestId("mo-sector-down")).toHaveText(sorted.slice(-3).reverse().map((s) => `${s.sector} ${pct2(s.ret_1d_pct)}`));
    await strip.getByTestId("mo-strip-sectors").click();
    await expect.poll(() => `${params(page).get("tab")}/${params(page).get("view")}`).toBe("market/sectors");
  });

  test("MO-4 BEAR: the regime the risk service uses, its as-of date, and the halved size limits", async ({ page }) => {
    await setup(page);
    await page.goto(DESK);
    const row = page.getByTestId("mo-regime");
    await expect(row).toHaveAttribute("data-regime", "BEAR", SLOW);
    await expect(row.getByTestId("mo-regime-label")).toHaveText("BEAR");
    await expect(row.getByTestId("mo-regime-asof")).toHaveText("as of 19 Oct");
    await expect(row.getByTestId("mo-regime-bear")).toHaveText("New-trade size limits are halved in BEAR.");
    await expect(row.getByTestId("mo-regime-cut")).toHaveCount(0);
    await expect(row.getByTestId("mo-regime-stale")).toHaveCount(0);
  });

  test("MO-5 BULL: no halving note; the line says no regime cut applies", async ({ page }) => {
    await setup(page, { fresh: { status: 200, body: freshness({ regime: "BULL", key: "bullish", as_of: "2026-10-16" }) } });
    await page.goto(DESK);
    const row = page.getByTestId("mo-regime");
    await expect(row).toHaveAttribute("data-regime", "BULL", SLOW);
    await expect(row.getByTestId("mo-regime-asof")).toHaveText("as of 16 Oct");
    await expect(row.getByTestId("mo-regime-bear")).toHaveCount(0);
    await expect(row.getByTestId("mo-regime-cut")).toHaveText("No regime cut on new-trade size limits (only BEAR halves them).");
  });

  test("MO-6 a stale regime input says so, with the route's reason, and that new paper entries are blocked", async ({ page }) => {
    const reason = "as of 2026-10-14, 3 sessions before 2026-10-19; the budget is 2";
    await setup(page, { fresh: { status: 200, body: freshness({ as_of: "2026-10-14", age_sessions: 3, ok: false, status: "stale", reason }) } });
    await page.goto(DESK);
    const row = page.getByTestId("mo-regime");
    await expect(row).toHaveAttribute("data-state", "stale", SLOW);
    await expect(row.getByTestId("mo-regime-stale-pill")).toHaveText("Stale");
    await expect(row.getByTestId("mo-regime-stale")).toHaveText(`Stale: ${reason}. The risk service blocks new paper entries while this input is stale.`);
  });

  test("MO-7 the freshness route failing leaves the rest of the strip in place", async ({ page }) => {
    await setup(page, { fresh: { status: 500, body: { detail: "MOCK: upstream" } } });
    await page.goto(DESK);
    await expect(page.getByTestId("mo-regime-unavailable")).toContainText("Regime unavailable", SLOW);
    await expect(page.getByTestId("mo-index")).toHaveCount(3);
    await expect(page.getByTestId("mo-flows-fii")).toBeVisible();
  });
});

// Kite's closing quote on an index cell: the same rule as the old Overview's tiles (useLiveOverlay with the cell's own bar
// day), ported from copilot-app-desk-market.spec.ts TC-3 … TC-5. MOCK — not real data: the final snapshot below.
test.describe("MOCK — not real data: Market Overview · index cells and Kite's closing quote", () => {
  const finalSnapshot = {
    as_of: "2026-10-23T11:02:24+00:00", data_at: "2026-10-23T11:02:27+00:00", age_seconds: 1, stale: false, stale_after_seconds: 75, cadence_seconds: 30,
    mode: "closed", session: "closed", source: "rest", final: true, count: 1, missing: [], read_only: true,
    quotes: { "NIFTY 50": { ltp: 22600, change: -87.65, change_pct: -0.39, open: 22690, high: 22710, low: 22580, close: 22687.65, volume: 0, oi: null, ts: "2026-10-23T15:29:00+05:30" } },
  };
  async function open(page: Page, tileDay: string | null) {
    await setup(page);
    const home = { ...HOME, as_of: "2026-10-19", indices: HOME.indices.map((i: Record<string, unknown>) => ({ ...i, as_of: tileDay })) };
    if (tileDay === null) for (const i of home.indices) delete (i as { as_of?: unknown }).as_of;
    await page.route("**/api/markets/home", (r) => json(r, home));
    await page.route("**/api/live/**", (route) => route.fulfill(
      new URL(route.request().url()).pathname.endsWith("/stream")
        ? { status: 200, contentType: "text/event-stream", body: `retry: 100\n\nevent: snapshot\ndata: ${JSON.stringify(finalSnapshot)}\n\n` }
        : { status: 200, contentType: "application/json", body: JSON.stringify(finalSnapshot) }));
    await page.goto(DESK);
    await expect(page.getByTestId("mo-index").first()).toBeVisible(SLOW);
  }
  const nifty = (page: Page) => page.locator('[data-testid="mo-index"][data-index="nifty"]');

  test("MO-2b the cell already has its own 23 Oct bar: Kite's 23 Oct close is NOT shown", async ({ page }) => {
    await open(page, "2026-10-23");
    const stamp = nifty(page).getByTestId("mo-index-stamp");
    await expect(stamp).toHaveAttribute("data-mode", "eod");
    await expect(stamp).not.toHaveAttribute("data-live", /.+/);
    await expect(stamp).not.toContainText("Kite");
    await expect(nifty(page).getByTestId("mo-index-value")).toHaveText(n2(HOME.indices[0].value));
  });

  test("MO-2c the cell's own bar is older than Kite's final snapshot: Kite's close is shown, labelled Close", async ({ page }) => {
    await open(page, "2026-10-22");
    const stamp = nifty(page).getByTestId("mo-index-stamp");
    await expect(stamp).toHaveAttribute("data-live", "close", SLOW);
    await expect(stamp).toContainText("Close · 23 Oct · Kite");
    await expect(nifty(page).getByTestId("mo-index-value")).toHaveText("22,600.00");
  });

  test("MO-2d an older backend without a cell date falls back to the page's day", async ({ page }) => {
    await open(page, null);
    await expect(nifty(page).getByTestId("mo-index-stamp")).toHaveAttribute("data-live", "close", SLOW);
  });
});

// ── Top AI ideas ──────────────────────────────────────────────────────────

test.describe("MOCK — not real data: Market Overview · Top AI ideas", () => {
  test("MO-10 / MO-11 / MO-13 a cash row is the decision-card row: the plan's levels, the risk service's size, provisional, budgets left", async ({ page }) => {
    await setup(page);
    await page.goto(DESK);
    const card = stockRow(page).getByTestId("desk-top10-card");
    await ready(card);
    await expect(card).toHaveAttribute("data-plan-id", CASH.plan_id);
    await expect(card.getByTestId("dc-entry")).toHaveText(`Entry ${rs(CASH.entry.price)} (at the close)`);
    await expect(card.getByTestId("dc-stop")).toHaveText(`Stop ${rs(CASH.stop.price)} (${CASH.stop.atr_multiple}×ATR below ${CASH.stop.measured_from})`);
    await expect(card.getByTestId("dc-targets")).toHaveText(`Targets ${targets(CASH)}`);
    await expect(card.getByTestId("dc-size")).toHaveText(`Size ${int(A.quantity)} shares`);
    await expect(card.getByTestId("dc-risk")).toHaveText(`Risk ${rs(A.estimated_risk_rs.total)} (${n2(A.risk_pct_of_equity)}% of equity)`);
    await expect(card.getByTestId("dc-costs")).toHaveText(`Est. costs ${rs(A.estimated_risk_rs.costs)}`);
    await expect(card.getByTestId("dc-plan-id")).toContainText(CASH.plan_id);
    // MO-11: no risk decision yet.
    await expect(card.getByTestId("dc-approval")).toHaveAttribute("data-approval", "provisional");
    await expect(card.getByTestId("dc-approval")).toHaveText("Provisional · no risk decision yet");
    expect(await card.getByTestId("dc-approval").evaluate((el) => getComputedStyle(el).borderStyle)).toBe("dashed");
    // MO-13: may be reduced, with the budgets left on the real book.
    const left = A.portfolio.remaining;
    const budgets = card.getByTestId("dc-row-budgets");
    await expect(budgets).toContainText("May be reduced by portfolio limits at submission");
    await expect(budgets).toContainText(`open risk ${rs(left.open_risk_rs)}`);
    await expect(budgets).toContainText(`${left.positions} more positions`);
    await expect(card.getByTestId("dc-caveat")).toContainText("not a prediction");
  });

  test("MO-10b a slow ideas answer (20 s, past the app's 15 s default) still fills the Top AI candidates, never 'took too long'", async ({ page }) => {
    test.setTimeout(90_000);
    // Staging, 27 Oct 23:05 IST: POST /api/desk/strategy/ideas took 15.6–16.0 s and the panel said "the request took too long".
    await setup(page);
    await page.route("**/api/desk/strategy/ideas", async (r) => {
      await new Promise((res) => setTimeout(res, 20_000));
      await r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(CARD.cash.ideas_response) });
    });
    await page.goto(DESK);
    const card = stockRow(page).getByTestId("desk-top10-card");
    await expect(card).toHaveAttribute("data-plan-id", CASH.plan_id, { timeout: 40_000 });
    await expect(page.getByText(/took too long/)).toHaveCount(0);
  });

  test("MO-12 a real allow decision reads Risk-approved, solid mint", async ({ page }) => {
    await setup(page, { plans: { [CASH.plan_id]: { status: 200, body: CARD.cash.allowed.trade_plan_response } } });
    await page.goto(DESK);
    const card = stockRow(page).getByTestId("desk-top10-card");
    await ready(card);
    await expect(card.getByTestId("dc-approval")).toHaveAttribute("data-approval", "approved");
    await expect(card.getByTestId("dc-approval")).toHaveText("✓ Risk-approved");
    expect(await card.getByTestId("dc-approval").evaluate((el) => getComputedStyle(el).borderStyle)).toBe("solid");
  });

  test("MO-14 / MO-15 the carry-forward tag, the scan basis and the stored list", async ({ page }) => {
    await setup(page, { day: carriedDay() });
    await page.goto(DESK);
    const tag = stockRow(page).getByTestId("desk-top10-carried");
    await expect(tag).toBeVisible(SLOW);
    await expect(tag).toHaveAttribute("data-sessions", "3");
    await expect(tag).toContainText("On the list 3 sessions · carried from 15 Oct 2026");
    const basis = page.getByTestId("desk-top10-basis");
    await expect(basis.getByTestId("desk-top10-scan")).toHaveText("From the 19 Oct close · AI scanner, end of day");
    await expect(basis.getByTestId("desk-top10-list")).toContainText(`Stored list of 19 Oct (${CARD.ai_watchlist_day.cash.length} cash · ${CARD.ai_watchlist_day.fno.length} F&O, the 22:45 IST job)`);
    await expect(basis).toHaveAttribute("data-stale", "false");
    await expect(basis.getByTestId("desk-top10-stale")).toHaveCount(0);
  });

  test("MO-16 a scan older than the last session is marked STALE DATA, naming both days", async ({ page }) => {
    await setup(page, { fresh: { status: 200, body: freshness({}, "2026-10-23") } });
    await page.goto(DESK);
    const basis = page.getByTestId("desk-top10-basis");
    await expect(basis).toHaveAttribute("data-stale", "true", SLOW);
    await expect(basis.getByTestId("desk-top10-stale")).toHaveText("Stale data");
    await expect(basis.getByTestId("desk-top10-stale-text")).toHaveText("Stale data: the scan of 19 Oct is older than the last session (23 Oct). Levels and sizes are from that day.");
  });

  test("MO-17 no stored list yet: the route's 22:45 IST words", async ({ page }) => {
    const empty = { list_date: null, available_dates: [], cash: [], fno: [], notes: {}, rules: {}, read_only: true,
      empty_reason: "No list is stored yet. The job runs each weekday at 22:45 IST, after the AI scanner's run and the day's NSE F&O bhavcopy, and keeps every day's list." };
    await setup(page, { day: empty });
    await page.goto(DESK);
    await expect(page.getByTestId("desk-top10-nolist")).toHaveText(empty.empty_reason, SLOW);
    await expect(stockRow(page).getByTestId("desk-top10-carried")).toHaveCount(0);
  });

  test("MO-18 an empty board shows the route's own reason and no rows", async ({ page }) => {
    const ideas = clone(CARD.cash.ideas_response);
    ideas.ideas = [];
    ideas.selection.empty_reason = "No setup passed the scan snapshot's gates on 19 Oct (MOCK).";
    await setup(page, { ideas });
    await page.goto(DESK);
    await expect(page.getByTestId("desk-top10-stocks-empty")).toHaveText(ideas.selection.empty_reason, SLOW);
    await expect(page.locator('[data-testid^="desk-top10-stock-"][data-testid$="ICICIBANK"]')).toHaveCount(0);
  });

  test("MO-19 Cash | F&O: one board at a time, Cash first", async ({ page }) => {
    await setup(page);
    await page.goto(DESK);
    const sw = page.getByTestId("desk-top10-switch");
    await expect(sw.getByTestId("desk-top10-switch-stocks")).toHaveText("Cash");
    await expect(sw.getByTestId("desk-top10-switch-stocks")).toHaveAttribute("aria-pressed", "true");
    await expect(stockRow(page)).toBeVisible(SLOW);
    await expect(page.getByTestId("desk-top10-fno")).toHaveCount(0);
    await sw.getByTestId("desk-top10-switch-fno").click();
    const bank = page.getByTestId("desk-top10-fno-BANKNIFTY");
    await expect(bank).toBeVisible(SLOW);
    await expect(page.getByTestId("desk-top10-stocks")).toHaveCount(0);
    const card = bank.getByTestId("desk-top10-fno-card");
    await ready(card);
    await expect(card).toHaveAttribute("data-plan-id", FNO.plan_id);
    await expect(card.getByTestId("dc-targets")).toHaveText(`Targets ${targets(FNO)}`);
    await expect(card.getByTestId("dc-row-budgets")).toContainText("May be reduced by portfolio limits at submission");
    await expect(page.getByTestId("desk-top10-scan")).toHaveText("Option chains of 21 Oct · regime fit, end of day");
  });

  test("MO-20 Full card opens the drawer: every section, the levels and the links; Escape and ✕ close it", async ({ page }) => {
    await setup(page);
    await page.goto(DESK);
    const row = stockRow(page);
    await row.getByTestId("desk-top10-stock-open").click(SLOW);
    const drawer = row.getByTestId("desk-top10-drawer");
    await expect(drawer).toBeVisible();
    await expect(drawer).toHaveAttribute("role", "dialog");
    const full = drawer.getByTestId("desk-top10-drawer-card");
    await ready(full);
    await expect(full).toHaveAttribute("data-variant", "full");
    for (const s of ["setup", "entry", "stop", "targets", "size", "costs", "evidence", "warnings", "exit", "audit"]) await expect(full.getByTestId(`dc-sec-${s}`)).toBeVisible();
    await expect(drawer.getByTestId("desk-top10-drawer-paper")).toBeVisible();
    await expect(drawer.getByTestId("desk-top10-stock-levels")).toBeVisible();
    await expect(drawer.getByTestId("desk-top10-stock-chart")).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(drawer).toHaveCount(0);
    await row.getByTestId("desk-top10-stock-open").click();
    await row.getByTestId("desk-top10-drawer-close").click();
    await expect(row.getByTestId("desk-top10-drawer")).toHaveCount(0);
  });

  test("MO-21 Paper trade in the drawer: a 409 risk_reduce offers the allowed size and re-posts it with the plan", async ({ page }) => {
    const reduced = CARD.cash.reduced;
    const seen = await setup(page, { paperStatus: [{ status: 409, body: { detail: reduced.paper_detail } }] });
    await page.goto(DESK);
    const row = stockRow(page);
    await row.getByTestId("desk-top10-stock-paper").click(SLOW);
    await expect(row.getByTestId("desk-top10-stock-paper")).toHaveAttribute("aria-expanded", "true");
    const drawer = row.getByTestId("desk-top10-drawer");
    await expect(drawer.getByTestId("desk-top10-paper-qty")).toHaveValue(String(A.quantity), SLOW);
    await drawer.getByTestId("desk-top10-paper-qty").fill(String(reduced.sent.quantity));
    await drawer.getByTestId("desk-top10-paper-add").click();
    await expect(drawer.getByTestId("desk-top10-paper-error")).toBeVisible(SLOW);
    const accept = drawer.getByTestId("desk-top10-paper-reduce-accept");
    await expect(accept).toHaveText(`Paper trade ${reduced.paper_detail.approved_qty} shares instead`);
    await accept.click();
    await expect(drawer.getByTestId("desk-top10-paper-done")).toContainText(`Paper trade added: ${reduced.paper_detail.approved_qty} ${SYM}`, SLOW);
    expect(seen.paperPosts.map((b) => b.quantity)).toEqual([reduced.sent.quantity, reduced.paper_detail.approved_qty]);
    expect(seen.paperPosts[1]).toEqual({ ...reduced.sent, quantity: reduced.paper_detail.approved_qty });
  });

  test("MO-22 a block that still applies turns Paper trade off with the gate's reason; nothing is posted", async ({ page }) => {
    const blocked = CARD.cash.blocked.trade_plan_response;
    const seen = await setup(page, { killSwitch: true, plans: { [CASH.plan_id]: { status: 200, body: blocked } } });
    await page.goto(DESK);
    const row = stockRow(page);
    await expect(row.getByTestId("desk-top10-card").getByTestId("dc-approval")).toHaveAttribute("data-approval", "block", SLOW);
    await row.getByTestId("desk-top10-stock-paper").click();
    const drawer = row.getByTestId("desk-top10-drawer");
    await expect(drawer.getByTestId("desk-top10-paper-blocked")).toContainText("The kill switch is on");
    await expect(drawer.getByTestId("desk-top10-paper-add")).toHaveCount(0);
    expect(seen.paperPosts).toHaveLength(0);
  });

  test("MO-23 the footer: ideas, not recommendations; no measurable ranking skill; Scorecard → opens Trade Desk › AI Scanner › Scorecard", async ({ page }) => {
    await setup(page);
    await page.goto(DESK);
    const foot = page.getByTestId("desk-top10-footer");
    await expect(foot).toHaveText("Ideas, not recommendations. The rank orders ideas; our test found no measurable ranking skill. Scorecard →", SLOW);
    await foot.getByTestId("desk-top10-scorecard").click();
    await expect.poll(() => params(page).get("tab")).toBe("trade");
    await expect.poll(() => params(page).get("view")).toBe("scanner");
    await expect.poll(() => params(page).get("sub")).toBe("scorecard");
  });

  test("MO-23b See all › opens Trade Desk › AI Scanner › Ranked candidates", async ({ page }) => {
    await setup(page);
    await page.goto(DESK);
    await page.getByTestId("desk-top10-see-all").click(SLOW);
    await expect.poll(() => params(page).get("tab")).toBe("trade");
    await expect.poll(() => params(page).get("view")).toBe("scanner");
    await expect.poll(() => params(page).get("sub")).toBe("ranked");
  });
});

// ── events, the Trade Desk line, read-only, wording, phone ────────────────

test.describe("MOCK — not real data: Market Overview · events and the Trade Desk line", () => {
  test("MO-24 events today: only today's filing for a name on the ideas; its symbol opens the chart", async ({ page }) => {
    await setup(page);
    await page.goto(DESK);
    const ev = page.getByTestId("mo-events");
    await expect(ev.getByTestId("mo-event")).toHaveCount(1, SLOW);
    await expect(ev.getByTestId("mo-event")).toHaveAttribute("data-id", F_TODAY.id);
    await expect(ev.getByTestId("mo-event-title")).toHaveText(F_TODAY.docLabel);
    await ev.getByTestId("mo-event-stock").click();
    await expect.poll(() => `${params(page).get("tab")}/${params(page).get("view")}/${params(page).get("sym")}`).toBe(`trade/chart/${SYM}`); // a symbol's chart is Trade Desk › Chart Analysis › Live chart (owner's design)
  });

  test("MO-24b a day with no filing for the listed names says so", async ({ page }) => {
    await setup(page, { filings: [F_OTHER, F_YESTERDAY] });
    await page.goto(DESK);
    await expect(page.getByTestId("mo-events-empty")).toContainText("No results or filings today for the", SLOW);
  });

  test("MO-25 KPIs and the paper trades panel: equity, day net P/L, open risk vs 3%, candidates and feed; held rows open Trade Desk", async ({ page }) => {
    const p = clone(CARD.risk_profile_default);
    p.live.open.positions = 3;
    p.live.open.risk_rs = 12000;
    p.live.open.exposure_rs = 250000;
    p.live.open.held_symbols = ["ICICIBANK", "INFY"];
    p.live.equity.equity_rs = 1038420;
    p.live.day.pnl_rs = 8137;
    await setup(page, { profile: { status: 200, body: p } });
    await page.goto(DESK);
    const start = CARD.paper_account.starting_capital_rs;
    await expect(page.getByTestId("mo-kpi-equity-value")).toHaveText("₹10,38,420", SLOW);
    await expect(page.getByTestId("mo-kpi-equity-sub")).toHaveText(`start ₹${int(start)} · +${(((1038420 - start) / start) * 100).toFixed(1)}%`);
    await expect(page.getByTestId("mo-kpi-day-value")).toHaveText("+₹8,137");
    await expect(page.getByTestId("mo-kpi-day-sub")).toHaveText("net of costs, before income tax");
    await expect(page.getByTestId("mo-kpi-risk-value")).toHaveText(`${((12000 / 1038420) * 100).toFixed(1)}%`);
    await expect(page.getByTestId("mo-kpi-risk-sub")).toHaveText("limit 3%");
    const fnoRows = ["index_options", "stock_fno"].reduce((n, k) => n + CARD.fno.top_response.classes[k].ideas.length, 0);
    await expect(page.getByTestId("mo-kpi-candidates-value")).toHaveText(String(CARD.cash.ideas_response.ideas.length + Math.min(fnoRows, 10)));
    await expect(page.getByTestId("mo-kpi-feed-value")).toHaveText("Closed");             // MOCK feed: mode "expired"
    const panel = page.getByTestId("mo-paper");
    await expect(panel.getByTestId("mo-paper-summary")).toHaveText("3 open positions · exposure ₹2,50,000 · open risk ₹12,000");
    await expect(panel.getByTestId("mo-paper-row")).toHaveCount(2);
    await expect(panel.getByTestId("mo-paper-more")).toContainText("1 more");
    await panel.locator('[data-testid="mo-paper-row"][data-symbol="INFY"]').click();
    await expect.poll(() => `${params(page).get("tab")}/${params(page).get("view")}`).toBe("trade/paper");
  });

  test("MO-26 no open positions", async ({ page }) => {
    await setup(page, { profile: { status: 200, body: CARD.risk_profile_default } });
    await page.goto(DESK);
    await expect(page.getByTestId("mo-kpi-risk-value")).toHaveText("0%", SLOW);
    await expect(page.getByTestId("mo-paper-summary")).toHaveText("No open positions");
    await expect(page.getByTestId("mo-paper-row")).toHaveCount(0);
  });

  test("MO-27 the risk profile failing says so in the KPIs and the panel; the panel link still works", async ({ page }) => {
    await setup(page, { profile: { status: 500, body: { detail: "MOCK: upstream" } } });
    await page.goto(DESK);
    await expect(page.getByTestId("mo-paper-error")).toContainText("Open positions didn’t load", SLOW);
    await expect(page.getByTestId("mo-kpi-equity-sub")).toContainText("the risk profile didn’t load");
    await page.getByTestId("mo-paper-all").click();
    await expect.poll(() => params(page).get("tab")).toBe("trade");
  });

  test("MO-28 this tab never reads GET /api/desk/paper-trades (it applies exits) or GET /api/desk/alerts (it fires alerts)", async ({ page }) => {
    const seen = await setup(page);
    await page.goto(DESK);
    await ready(stockRow(page).getByTestId("desk-top10-card"));
    await stockRow(page).getByTestId("desk-top10-stock-open").click();
    await ready(page.getByTestId("desk-top10-drawer-card"));
    await page.getByTestId("desk-top10-drawer-close").click();
    await page.getByTestId("desk-top10-switch-fno").click();
    await expect(page.getByTestId("desk-top10-fno-BANKNIFTY")).toBeVisible(SLOW);
    await expect(page.getByTestId("mo-paper-summary")).toBeVisible();
    expect(seen.paperGets).toEqual([]);
    expect(seen.alertGets).toEqual([]);
  });

  test("MO-29 wording: ideas and candidates, never picks, suggestions or recommended", async ({ page }) => {
    await setup(page);
    await page.goto(DESK);
    await ready(stockRow(page).getByTestId("desk-top10-card"));
    await expect(page.getByTestId("mo-event")).toHaveCount(1, SLOW);
    const text = (await panel(page).innerText()).replace(/\s+/g, " ");
    expect(text).not.toMatch(/\bpicks?\b/i);
    expect(text).not.toMatch(/suggest/i);
    expect(text).not.toMatch(/recommended/i);
    expect(text.replace(/not (a )?recommendations?/gi, "")).not.toMatch(/recommend/i);
    expect(text).toMatch(/not a prediction/);
  });
});

test.describe("MOCK — not real data: Market Overview · phone (390px)", () => {
  test("MO-30 no sideways scroll on the page or with the drawer open", async ({ page }) => {
    await setup(page, { phone: true });
    await page.goto(DESK);
    await ready(stockRow(page).getByTestId("desk-top10-card"));
    await expect(page.getByTestId("mo-index")).toHaveCount(3);
    const fits = () => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth);
    expect(await fits()).toBe(true);
    await stockRow(page).getByTestId("desk-top10-stock-open").click();
    const drawer = page.getByTestId("desk-top10-drawer");
    await ready(drawer.getByTestId("desk-top10-drawer-card"));
    const box = await drawer.boundingBox();
    expect(box && box.x >= 0 && box.x + box.width <= 390 + 0.5).toBe(true);
    expect(await fits()).toBe(true);
  });
});
