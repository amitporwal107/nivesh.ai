/**
 * One-screen Copilot app — Smart trading desk: the stock search (screens/tradingdesk/SymbolSearch.tsx, symbol-lookup-data.ts)
 * and what an unknown symbol now says (Chart tab "did you mean", Strategy Builder suggestions, `unknown_symbol` plans).
 *
 * MOCK — not real data. GET /api/markets/symbol-lookup (backend/routes/symbol_lookup.py) is answered here from a tiny
 * hand-made table in the shape the route sends; the strategy plan is e2e/fixtures/strategy-plan-insufficient.json with its
 * status reason replaced by the `unknown_symbol` reason the route builds (message and suggestions as
 * backend/tests/test_symbol_lookup.py asserts them). The scanner list is the lab spec's (TESTBRK, TESTPICK).
 *
 * Cases: SS-1 header: typing, highlight, tags, keys, selection · SS-2 debounce and stale answers · SS-3 recents ·
 * SS-4 empty box shows the scanner's top setups · SS-5 no match · SS-6 lookup failure keeps today's behaviour ·
 * SS-7 a question still goes to the Copilot · SS-8 F&O lab restricts to F&O · SS-9 chart 404 did-you-mean ·
 * SS-10 builder: unknown symbol is not sent · SS-11 builder: unknown_symbol plan, rebuild · SS-12 no suggestion ·
 * SS-13 persona wording · SS-14 390px · SS-15 screenshots (written to e2e/.shots, not committed).
 */
import { test, expect, type Page, type Route } from "@playwright/test";
import fs from "fs";
import path from "path";
import { mockApi, mockSingleRoute } from "../helpers/api-mock";

const DESK = "/v5/app/trader/desk";
const FX = path.join(process.cwd(), "e2e", "fixtures");
const load = (name: string) => JSON.parse(fs.readFileSync(path.join(FX, name), "utf-8"));
const json = (route: Route, body: unknown, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });

const WATCHLIST = { as_of_date: "2026-10-12", buckets: { breakout_confirmed: [{ nse_symbol: "TESTBRK", sector: "Capital Goods", close_price: 510.0, trigger_price: 500.0, stop_price: 477.5, atr_pct: 2.94, why: "Fixture reason" }], pre_breakout: [], true_accumulation: [], trend_continuation: [] } };
const PICKS = { signal_date: "2026-10-12", count: 1, picks: [{ nse_symbol: "TESTPICK", signal_date: "2026-10-12", final_score: 0.812, confidence: "HIGH", stage: "BREAKOUT", timeframe_days_min: 5, timeframe_days_max: 15, entry_price: 505.0, stoploss: 480.0, target_price: 555.0, risk_reward: 2.0, source_scans: ["btst.breakout_confirmation"], reasons: ["Fixture scanner reason"] }] };

// ── MOCK symbol lookup ───────────────────────────────────────────────────

type R = Record<string, unknown>;
const res = (symbol: string, name: string, o: R = {}): R => ({
  symbol, name, isin: null, sector: "Mock sector", industry: null, fno_eligible: false, in_scanner: false, last_price_date: "2026-10-19", has_prices: true,
  match: "prefix", matched_on: "symbol", highlight: { symbol: [], name: [] }, score: 90, ...o,
});
const RELIANCE = res("RELIANCE", "Reliance Industries Limited", { fno_eligible: true, in_scanner: true, sector: "Oil Gas", highlight: { symbol: [[0, 3]], name: [] } });
const RELIGARE = res("RELIGARE", "Religare Enterprises Limited", { highlight: { symbol: [[0, 3]], name: [] } });
const PCJ = res("PCJEWELLER", "PC Jeweller Limited", { match: "name_prefix", matched_on: "name", sector: "Textiles Apparels & Accessories", highlight: { symbol: [], name: [[0, 2], [3, 6]] } });
const PCJ_VARIANT = res("PCJEWELLER", "PC Jeweller Limited", { match: "variant", score: 85, highlight: { symbol: [[0, 10]], name: [] } });

/** What the mocked route answers for a text. Anything not listed finds nothing. */
const TABLE: Record<string, R[]> = { rel: [RELIANCE, RELIGARE], re: [res("RESTALE", "Stale Answer Limited")], r: [res("RESTALE", "Stale Answer Limited")], "pc jew": [PCJ], pcjewellers: [PCJ_VARIANT], tcs: [res("TCS", "Tata Consultancy Services Limited", { match: "exact", fno_eligible: true })] };

interface Look { reqs: Array<{ q: string; fno: boolean; at: number }>; mode: "ok" | "fail"; delay: Record<string, number>; blind: Set<string> }

async function lookupRoute(page: Page): Promise<Look> {
  const st: Look = { reqs: [], mode: "ok", delay: {}, blind: new Set() };
  await page.route("**/api/markets/symbol-lookup*", async (route) => {
    const u = new URL(route.request().url());
    const q = (u.searchParams.get("q") ?? "").toLowerCase();
    st.reqs.push({ q, fno: u.searchParams.get("fno_only") === "true", at: Date.now() });
    if (st.mode === "fail") return json(route, { detail: "lookup_unavailable" }, 502);
    if (st.delay[q]) await new Promise((r) => setTimeout(r, st.delay[q]));
    const rows = st.blind.has(q) ? [] : (TABLE[q] ?? []);
    const fno = u.searchParams.get("fno_only") === "true";
    const results = fno ? rows.filter((r) => r.fno_eligible) : rows;
    return json(route, {
      query: q.toUpperCase(), exact: results.find((r) => r.match === "exact") ?? null, results, count: results.length,
      reason: results.length || !q ? null : `No NSE stock matches ${q.toUpperCase()}.`, popular: [], recent: [], source: "MOCK lookup", as_of: "2026-10-19", universe_size: 3000,
    });
  });
  return st;
}

async function base(page: Page) {
  await mockApi(page, "populated");
  await mockSingleRoute(page, "**/api/markets/home", "markets-home.json");
  await page.route("**/api/chat/sessions", (r) => (r.request().method() === "POST" ? json(r, { session_id: "desk1", id: "desk1" }) : json(r, [])));
  await page.route("**/api/chat/messages*", (r) => json(r, []));
  await page.route("**/api/positional/watchlist*", (r) => json(r, WATCHLIST));
  await page.route("**/api/positional/picks*", (r) => json(r, PICKS));
  await page.route("**/api/move-odds/latest*", (r) => json(r, { detail: "Feature not enabled for this account" }, 403));
  await page.route("**/api/move-odds/stocks/*", (r) => json(r, { detail: "x" }, 404));
  await page.route("**/api/positional/journal/summary/portfolio", (r) => json(r, { open_count: 0, closed_count: 0, gross_long_rs: 0, invested_rs: 0, realized_pnl_rs: 0, win_count: 0, loss_count: 0, win_rate_pct: null, needs_hedge: false, suggested_hedge: null }));
  await page.route("**/api/broker/**", (r) => json(r, { accounts: [], as_of: null }));
  await page.route("**/api/desk/paper-trades*", (r) => json(r, { as_of: null, trades: [], summary: null }));
  await page.route("**/api/desk/alerts*", (r) => json(r, { as_of: null, alerts: [] }));
  await page.route("**/api/watchlists", (r) => json(r, { lists: [], limits: { max_lists: 20, max_symbols: 50 }, starter_pending: false }));
  const streams: string[] = [];
  await page.route("**/api/chat/stream", (r) => {
    streams.push((r.request().postDataJSON() as { message: string }).message);
    const frames = [{ type: "token", content: "MOCK answer." }, { type: "done", content: "MOCK answer.", follow_ups: [] }];
    return r.fulfill({ status: 200, contentType: "text/event-stream", body: frames.map((f) => `data: ${JSON.stringify(f)}\n\n`).join("") });
  });
  const look = await lookupRoute(page);
  return { look, streams };
}

const search = (page: Page) => page.getByTestId("desk-search");
const listbox = (page: Page) => page.getByTestId("desk-search-listbox");
const opt = (page: Page, s: string) => page.getByTestId(`desk-search-option-${s}`);
const sideways = (page: Page) => page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);

test.describe("Smart trading desk — stock search (MOCK lookup)", () => {
  test("SS-1 typing opens ranked options with the matched part highlighted and tags; keys and Enter select; Escape closes; ARIA", async ({ page }) => {
    await base(page);
    await page.goto(`${DESK}?tab=overview`);
    const input = search(page);
    await expect(input).toHaveAttribute("role", "combobox");
    await expect(input).toHaveAttribute("aria-expanded", "false");
    await input.click();
    await input.pressSequentially("rel");
    await expect(listbox(page)).toBeVisible();
    await expect(listbox(page)).toHaveAttribute("role", "listbox");
    await expect(input).toHaveAttribute("aria-expanded", "true");
    const first = opt(page, "RELIANCE");
    await expect(first).toHaveAttribute("role", "option");
    await expect(first.getByTestId("symsearch-mark").first()).toHaveText("REL");
    await expect(first).toContainText("Reliance Industries Limited");
    await expect(first).toContainText("F&O");
    await expect(first).toContainText("In today’s scan");
    await expect(opt(page, "RELIGARE")).not.toContainText("F&O");
    // Arrow keys move the active option; aria-activedescendant follows it.
    await input.press("ArrowDown");
    await expect(first).toHaveAttribute("aria-selected", "true");
    const id = await first.getAttribute("id");
    await expect(input).toHaveAttribute("aria-activedescendant", id as string);
    await input.press("ArrowDown");
    await expect(opt(page, "RELIGARE")).toHaveAttribute("aria-selected", "true");
    await input.press("ArrowUp");
    await expect(first).toHaveAttribute("aria-selected", "true");
    // Escape closes the list and keeps the text.
    await input.press("Escape");
    await expect(listbox(page)).toHaveCount(0);
    await expect(input).toHaveAttribute("aria-expanded", "false");
    await expect(input).toHaveValue("rel");
    // Arrow reopens; Enter on the highlighted option opens its chart.
    await input.press("ArrowDown");
    await input.press("ArrowDown");
    await input.press("Enter");
    await expect(page).toHaveURL(/tab=chart/);
    await expect(page).toHaveURL(/sym=RELIANCE/);
    await expect(input).toHaveValue("");
  });

  test("SS-1b a click selects too, and Tab leaves without selecting", async ({ page }) => {
    await base(page);
    await page.goto(`${DESK}?tab=overview`);
    await search(page).fill("rel");
    await expect(opt(page, "RELIGARE")).toBeVisible();
    await search(page).press("Tab");
    await expect(listbox(page)).toHaveCount(0);
    await expect(page).not.toHaveURL(/sym=RELIGARE/);
    await search(page).fill("rel");
    await opt(page, "RELIGARE").click();
    await expect(page).toHaveURL(/sym=RELIGARE/);
  });

  test("SS-2 requests are debounced to one, and a slow answer for older text is never shown", async ({ page }) => {
    const { look } = await base(page);
    look.delay["re"] = 700;                       // the answer for "re" arrives after the one for "rel"
    await page.goto(`${DESK}?tab=overview`);
    const input = search(page);
    await input.click();
    await input.pressSequentially("rel", { delay: 20 });
    await expect(opt(page, "RELIANCE")).toBeVisible();
    expect(look.reqs.filter((r) => r.q).map((r) => r.q)).toEqual(["rel"]);                    // one request, not three
    // Slow "re" then a quick "rel": the stale "re" answer must not replace the "rel" rows.
    await input.fill("");
    look.reqs.length = 0;
    await input.pressSequentially("re");
    await page.waitForTimeout(250);               // past the 150 ms debounce: "re" is in flight
    await input.pressSequentially("l");
    await expect(opt(page, "RELIANCE")).toBeVisible();
    await page.waitForTimeout(900);
    await expect(opt(page, "RESTALE")).toHaveCount(0);
    await expect(opt(page, "RELIANCE")).toBeVisible();
  });

  test("SS-3 recents persist in this browser, show for an empty box, and clear", async ({ page }) => {
    await base(page);
    await page.goto(`${DESK}?tab=overview`);
    await search(page).fill("rel");
    await opt(page, "RELIANCE").click();
    expect(await page.evaluate(() => window.localStorage.getItem("nivesh.desk.symbol-recents"))).toContain("RELIANCE");
    await page.reload();
    await search(page).click();
    await expect(page.getByTestId("desk-search-section-recent")).toBeVisible();
    await expect(opt(page, "RELIANCE")).toContainText("Reliance Industries Limited");
    await page.getByTestId("desk-search-recent-clear").click();
    await expect(page.getByTestId("desk-search-section-recent")).toHaveCount(0);
    expect(await page.evaluate(() => window.localStorage.getItem("nivesh.desk.symbol-recents"))).toBeNull();
  });

  test("SS-3b blocked storage does not break the box", async ({ page }) => {
    await base(page);
    await page.addInitScript(() => { Object.defineProperty(window, "localStorage", { get() { throw new Error("blocked"); } }); });
    await page.goto(`${DESK}?tab=overview`);
    await search(page).fill("rel");
    await opt(page, "RELIANCE").click();
    await expect(page).toHaveURL(/sym=RELIANCE/);
  });

  test("SS-4 an empty box offers today's scanner setups, and one opens", async ({ page }) => {
    const { look } = await base(page);
    await page.goto(`${DESK}?tab=overview`);
    await search(page).click();
    await expect(page.getByTestId("desk-search-section-top")).toHaveText(/Top setups today/);
    await expect(opt(page, "TESTBRK")).toBeVisible();
    await expect(opt(page, "TESTPICK")).toBeVisible();
    expect(look.reqs).toEqual([]);                // the desk's own scanner list: no lookup request for an empty box
    await opt(page, "TESTPICK").click();
    await expect(page.getByTestId("desk-search-picked")).toContainText("TESTPICK selected");
  });

  test("SS-5 no match says so, with a hint", async ({ page }) => {
    await base(page);
    await page.goto(`${DESK}?tab=overview`);
    await search(page).fill("qqzz");
    await expect(page.getByTestId("desk-search-empty")).toContainText("No NSE stock matches “qqzz”");
    await expect(page.getByTestId("desk-search-empty")).toContainText("ISIN");
  });

  test("SS-6 when the lookup fails the box still works as before", async ({ page }) => {
    const { look } = await base(page);
    look.mode = "fail";
    await page.goto(`${DESK}?tab=overview`);
    await search(page).fill("testp");
    await expect(page.getByTestId("desk-search-error")).toContainText("Press Enter");
    await search(page).press("Enter");
    await expect(page.getByTestId("desk-search-picked")).toContainText("TESTPICK selected");
    await search(page).fill("ZZTOP");
    await search(page).press("Enter");
    await expect(page).toHaveURL(/tab=chart/);
    await expect(page).toHaveURL(/sym=ZZTOP/);
  });

  test("SS-7 text that is a question still goes to the Copilot, even with results showing", async ({ page }) => {
    const { streams } = await base(page);
    await page.goto(`${DESK}?tab=overview`);
    await search(page).fill("rel");
    await expect(opt(page, "RELIANCE")).toBeVisible();
    await search(page).fill("Is breadth improving?");
    await search(page).press("Enter");
    await expect.poll(() => streams).toEqual(["Is breadth improving?"]);
    await expect(page).not.toHaveURL(/tab=chart/);
  });

  test("SS-8 the lab's ticker box asks for F&O stocks only", async ({ page }) => {
    const { look } = await base(page);
    await page.route("**/api/fno/**", (r) => json(r, { detail: "MOCK: not served in this spec" }, 404));
    await page.goto(`${DESK}?tab=fno`);
    const input = page.getByTestId("desk-fno-symbol-input");
    await input.fill("rel");
    await expect(page.getByTestId("desk-fno-search-option-RELIANCE")).toBeVisible();
    await expect(page.getByTestId("desk-fno-search-option-RELIGARE")).toHaveCount(0);        // not in F&O: the route is asked fno_only
    expect(look.reqs.filter((r) => r.q === "rel").every((r) => r.fno)).toBe(true);
    await page.getByTestId("desk-fno-search-option-RELIANCE").click();
    await expect(page.getByTestId("desk-fno-loaded-sym")).toHaveText("RELIANCE loaded");
  });

  test("SS-9 Chart 404: did-you-mean chips switch the chart; no match says so", async ({ page }) => {
    const { look } = await base(page);
    const asked: string[] = [];
    await page.route("**/api/research/chart-live/*/ohlcv*", (r) => {
      const sym = new URL(r.request().url()).pathname.split("/")[4];
      asked.push(sym);
      return sym === "PCJEWELLERS" || sym === "QQZZ" ? json(r, { detail: "no_bars_for_symbol" }, 404) : json(r, { symbol: sym, timeframe: "1D", bars: [["2026-10-16", 10, 12, 9, 11, 1000], ["2026-10-19", 11, 13, 10, 12, 1200]], data_quality_status: "VALID", provenance: { provider: "MOCK" } });
    });
    await page.goto(`${DESK}?tab=chart&sym=PCJEWELLERS`);
    await expect(page.getByTestId("desk-chart-noprices")).toContainText("No daily prices on record for PCJEWELLERS");
    const chip = page.getByTestId("desk-chart-dym-PCJEWELLER");
    await expect(chip).toContainText("PC Jeweller Limited");
    await expect(page.getByTestId("desk-chart-dym")).toContainText("Did you mean");
    await chip.click();
    await expect(page).toHaveURL(/sym=PCJEWELLER(&|$)/);
    await expect.poll(() => asked).toContain("PCJEWELLER");
    await expect(page.getByTestId("desk-chart-noprices")).toHaveCount(0);
    // A symbol nothing resembles.
    await page.goto(`${DESK}?tab=chart&sym=QQZZ`);
    await expect(page.getByTestId("desk-chart-dym-none")).toContainText("No NSE stock matches QQZZ");
    // The lookup failing leaves the explanation alone.
    look.mode = "fail";
    await page.goto(`${DESK}?tab=chart&sym=PCJEWELLERS`);
    await expect(page.getByTestId("desk-chart-noprices")).toBeVisible();
    await expect(page.getByTestId("desk-chart-dym")).toHaveCount(0);
    await expect(page.getByTestId("desk-chart-dym-none")).toHaveCount(0);
  });
});

// ── Strategy Builder ─────────────────────────────────────────────────────

const UNKNOWN_REASON = (sugg: R[], suggested: string | null, message: string) => ({
  code: "unknown_symbol", message, suggestions: sugg, suggested, lookup_source: "MOCK lookup",
});
function unknownPlan(sym: string, reason: R) {
  const p = load("strategy-plan-insufficient.json");
  p.inputs = { ...p.inputs, underlying: sym };
  p.underlying = { ...p.underlying, symbol: sym, spot: null, spot_as_of: null };
  p.summary = { ...p.summary, underlying: sym, data_as_of: null };
  p.data_as_of = { ...p.data_as_of, price: null };
  p.status = "insufficient_data";
  p.status_reasons = [reason];
  p.would_change_if = ["unknown_symbol: An NSE symbol with price history on record: use one of the suggestions, or check the ticker."];
  p.candidates = [];
  p.preferred = null;
  p.symbol_suggestions = (reason.suggestions as R[]) ?? [];
  return p;
}
const SUGG_PCJ = [{ symbol: "PCJEWELLER", name: "PC Jeweller Limited", isin: "INE785M01021", match: "variant", has_prices: true }];

async function builder(page: Page, plan: (sym: string) => unknown) {
  const b = await base(page);
  const builds: Array<Record<string, unknown>> = [];
  await page.route("**/api/desk/strategy/plan", (r) => { const body = r.request().postDataJSON() as { underlying: string }; builds.push(body); return json(r, plan(body.underlying)); });
  await page.route("**/api/desk/strategy/plans", (r) => json(r, { plans: [], count: 0, limit: 100, max_saved: 200 }));
  await page.route("**/api/desk/strategy/ideas", (r) => json(r, { ideas: [] }));
  return { ...b, builds };
}
const BUILDER = `${DESK}?tab=more&view=strategy&mode=stock`;

test.describe("Smart trading desk — Strategy Builder symbol checks (MOCK)", () => {
  test("SS-10 an unknown symbol shows suggestions inline and sends no plan request; Use fixes the box", async ({ page }) => {
    const { builds } = await builder(page, () => load("strategy-plan-cash.json"));
    await page.goto(BUILDER);
    const input = page.getByTestId("in-symbol");
    await input.fill("pcjewellers");
    await page.getByTestId("in-direction-bullish").click();
    await page.getByRole("button", { name: /build the plan/i }).click();
    const hint = page.getByTestId("symbol-hint");
    await expect(hint).toContainText("PCJEWELLERS is not a known NSE symbol");
    await expect(page.getByTestId("symbol-hint-use-PCJEWELLER")).toContainText("PC Jeweller Limited");
    expect(builds).toEqual([]);
    await page.getByTestId("symbol-hint-use-PCJEWELLER").click();
    await expect(input).toHaveValue("PCJEWELLER");
    await expect(hint).toHaveCount(0);
  });

  test("SS-10b leaving the box checks the symbol after a pause", async ({ page }) => {
    await builder(page, () => load("strategy-plan-cash.json"));
    await page.goto(BUILDER);
    await page.getByTestId("in-symbol").fill("pcjewellers");
    await page.getByTestId("in-direction-bullish").click();            // focus leaves the box
    await expect(page.getByTestId("symbol-hint")).toBeVisible();
  });

  test("SS-10c a symbol the lookup cannot see, or a failing lookup, still builds", async ({ page }) => {
    const { look, builds } = await builder(page, () => load("strategy-plan-cash.json"));
    look.blind.add("pcjewellers");
    await page.goto(BUILDER);
    await page.getByTestId("in-symbol").fill("pcjewellers");
    await page.getByTestId("in-direction-bullish").click();
    await page.getByRole("button", { name: /build the plan/i }).click();
    await expect.poll(() => builds.length).toBe(1);
    look.mode = "fail";
    await page.getByTestId("in-symbol").fill("RELIANCE");
    await page.getByRole("button", { name: /build the plan/i }).click();
    await expect.poll(() => builds.length).toBe(2);
  });

  test("SS-11 an unknown_symbol plan shows the message, suggestions and a one-click rebuild that rewrites ?sym=", async ({ page }) => {
    const msg = "No price history for PCJEWELLERS. Did you mean PCJEWELLER (PC Jeweller Limited)?";
    const { look, builds } = await builder(page, (sym) => (sym === "PCJEWELLERS" ? unknownPlan(sym, UNKNOWN_REASON(SUGG_PCJ, "PCJEWELLER", msg)) : load("strategy-plan-cash.json")));
    look.blind.add("pcjewellers");                 // the lookup cannot see it, so the build goes to the route, which answers unknown_symbol
    await page.goto(BUILDER);
    await page.getByTestId("in-symbol").fill("PCJEWELLERS");
    await page.getByTestId("in-direction-bullish").click();
    await page.getByRole("button", { name: /build the plan/i }).click();
    const reasons = page.getByTestId("plan-status-reasons");
    await expect(reasons).toContainText(msg);
    await expect(reasons).toContainText("unknown_symbol");
    expect(builds.map((b) => b.underlying)).toEqual(["PCJEWELLERS"]);     // the input was kept, not substituted
    await expect(page.getByTestId("plan-status")).toContainText(/insufficient/i);
    const rebuild = page.getByTestId("rebuild-for-PCJEWELLER");
    await expect(rebuild).toContainText("Rebuild for PCJEWELLER");
    await rebuild.click();
    await expect.poll(() => builds.map((b) => b.underlying)).toEqual(["PCJEWELLERS", "PCJEWELLER"]);
    await expect(page).toHaveURL(/sym=PCJEWELLER(&|$)/);
    await expect(page.getByTestId("in-symbol")).toHaveValue("PCJEWELLER");
  });

  test("SS-12 an unknown_symbol plan with no suggestion says to check the ticker", async ({ page }) => {
    const { look } = await builder(page, (sym) => unknownPlan(sym, UNKNOWN_REASON([], null, `No price history for ${sym}. No NSE stock matches ${sym}.`)));
    look.blind.add("qqzz");
    await page.goto(BUILDER);
    await page.getByTestId("in-symbol").fill("QQZZ");
    await page.getByTestId("in-direction-bullish").click();
    await page.getByRole("button", { name: /build the plan/i }).click();
    await expect(page.getByTestId("plan-status-reasons")).toContainText("No NSE stock matches QQZZ");
    await expect(page.getByTestId("unknown-symbol-none")).toContainText("Check the ticker");
    await expect(page.locator('[data-testid^="rebuild-for-"]')).toHaveCount(0);
  });

  test("SS-13 investor wording: box, hint and empty states", async ({ page }) => {
    await builder(page, () => load("strategy-plan-cash.json"));
    await page.goto(`${BUILDER}&persona=investor`);
    await page.getByTestId("in-symbol").fill("pcjewellers");
    await page.getByTestId("in-direction-bullish").click();
    await page.getByTestId("build-plan").click();
    await expect(page.getByTestId("symbol-hint-text")).toContainText("We could not find “PCJEWELLERS”");
    await page.goto(`${DESK}?tab=overview&persona=investor`);
    await expect(search(page)).toHaveAttribute("placeholder", "Search a company, or ask Nivesh…");
    await search(page).fill("rel");
    await expect(opt(page, "RELIANCE")).toContainText("Options available");
    await expect(opt(page, "RELIANCE")).toContainText("On today’s AI list");
  });
});

test.describe("Smart trading desk — stock search at 390px and screenshots (MOCK)", () => {
  test.use({ hasTouch: true });

  test("SS-14 at 390px the list fits, rows are tap-sized, nothing scrolls sideways", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await base(page);
    await page.goto(`${DESK}?tab=overview`);
    await page.getByTestId("desk-search-toggle").click();
    await search(page).fill("rel");
    await expect(opt(page, "RELIANCE")).toBeVisible();
    const box = await opt(page, "RELIANCE").boundingBox();
    expect(box?.height ?? 0).toBeGreaterThanOrEqual(44);
    const list = await listbox(page).boundingBox();
    expect((list?.x ?? -1)).toBeGreaterThanOrEqual(0);
    expect((list?.x ?? 0) + (list?.width ?? 999)).toBeLessThanOrEqual(390);
    expect(await sideways(page)).toBeLessThanOrEqual(0);
    await opt(page, "RELIANCE").tap();
    await expect(page).toHaveURL(/sym=RELIANCE/);
  });

  for (const w of [1440, 390] as const) {
    test(`SS-15 screenshots at ${w}`, async ({ page }) => {
      await page.setViewportSize({ width: w, height: w === 390 ? 844 : 900 });
      const { look } = await builder(page, () => load("strategy-plan-cash.json"));
      await page.route("**/api/fno/**", (r) => json(r, { detail: "MOCK: not served in this spec" }, 404));
      const dir = path.join(process.cwd(), "e2e", ".shots");
      fs.mkdirSync(dir, { recursive: true });
      await page.goto(`${DESK}?tab=overview`);
      if (w === 390) await page.getByTestId("desk-search-toggle").click();
      await search(page).fill("rel");
      await expect(opt(page, "RELIANCE")).toBeVisible();
      await search(page).press("ArrowDown");
      await page.screenshot({ path: path.join(dir, `ss-header-${w}.png`) });
      await page.goto(BUILDER);
      await page.getByTestId("in-symbol").fill("rel");
      await expect(page.getByTestId("in-symbol-option-RELIANCE")).toBeVisible();
      await page.screenshot({ path: path.join(dir, `ss-builder-${w}.png`) });
      look.reqs.length = 0;
      await page.goto(`${DESK}?tab=fno`);
      await page.getByTestId("desk-fno-symbol-input").fill("rel");
      await expect(page.getByTestId("desk-fno-search-option-RELIANCE")).toBeVisible();
      await page.screenshot({ path: path.join(dir, `ss-lab-${w}.png`) });
    });
  }
});
