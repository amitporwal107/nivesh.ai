/**
 * One-screen Copilot app (/v5/app) — Watchlist & alerts · the AI scanner watchlist (screens/workspace/AiScannerWatchlist.tsx).
 * Cases F-1 … F-10 of test_reports/ai_scanner_watchlist_TESTCASES.md.
 *
 * MOCK — not real data, except where said: GET /api/desk/ai-watchlist, the live stream, POST /api/live/fno-quotes,
 * GET /api/fno/scan/buildup and the two write routes are answered by inline payloads in the real routes' shapes. The two F&O
 * ideas are taken from `desk-strategy-top.json`, a REAL staging capture of POST /api/desk/strategy/top (2026-10-21).
 * Expected figures are worked out from the payloads here, not copied from the screen.
 *
 * Stored levels (test_reports/fno_idea_paper_trade_TESTCASES.md F-9, F-10): the BANKNIFTY entry carries the
 * `strategy_levels` the nightly job stores (services/ai_watchlist_build.levels_for) with the real engine's answer for it
 * (`desk-strategy-levels-banknifty.json`); MPHASIS carries none, as a day stored before the job kept them. Its paper trade
 * is compared with the shared contract `contract-fno-idea-paper-trade.json` (sent through the real route by
 * backend/tests/test_fno_idea_paper_trade_contract.py).
 */
import { test, expect, type Page, type Route } from "@playwright/test";
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";
import { mockApi } from "../helpers/api-mock";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const APP = "/v5/app";
const PAGE = `${APP}/page/watchlist`;
const SLOW = { timeout: 15_000 };
const reply = (route: Route, body: unknown, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });

// ── the stored day (backend/routes/ai_watchlist.py) ───────────────────────

const fixture = (name: string) => JSON.parse(fs.readFileSync(path.join(__dirname, "..", "fixtures", name), "utf-8"));
const TOP = fixture("desk-strategy-top.json");
const CONTRACT = fixture("contract-fno-idea-paper-trade.json");
const LEVELS = fixture(CONTRACT.levels_reply_fixture);
const bank = TOP.classes.index_options.ideas.find((i: { underlying: string }) => i.underlying === "BANKNIFTY");
const mph = TOP.classes.stock_fno.ideas.find((i: { underlying: string }) => i.underlying === "MPHASIS");
/** What the nightly job stores on an F&O entry (services/ai_watchlist_build.levels_for). */
const STORED_LEVELS = { as_of: "2026-10-21", computed_at: "2026-10-21T14:45:00+00:00", refs: CONTRACT.levels_request.refs, result: LEVELS, error: null };
const FNO = [
  { ...mph, kind: "stock", rank: 1, earlier_list_dates: ["2026-10-23"], days_on_list: 2 },
  { ...bank, kind: "index", rank: 2, earlier_list_dates: [], days_on_list: 1, strategy_levels: STORED_LEVELS },
];
const ICICI = {
  rank: 1, symbol: "ICICIBANK", name: "ICICI Bank Ltd", sector: "Banks", direction: "bullish", fno_eligible: true, source: "ai_scanner",
  scanner: { bucket: "breakout_confirmed", status: "confirmed", score: 86, close: 1200, close_date: "2026-10-26", entry: 1200, stop: 1160, target: 1280, reasons: [], horizon_days: 15 },
  plan_status: "plan", status_reasons: [],
  preferred: { id: "options:bull_call_spread", segment: "options", label: "Bull call spread 1200/1250", status: "candidate", legs_text: "Buy 1,200 call at 52.00; sell 1,250 call at 38.00", max_loss: -7000, reward_risk_net: 2.4 },
  sized_shares: 208, plan_inputs: { underlying: "ICICIBANK", direction: "bullish", instrument: "all", capital: 1000000 },
  earlier_list_dates: ["2026-10-23"], days_on_list: 2,
};
const CRISIL = {
  rank: 2, symbol: "CRISIL", name: "CRISIL Ltd", sector: null, direction: "bullish", fno_eligible: false, source: "ai_scanner",
  scanner: { bucket: "pre_breakout", status: "awaiting", score: 81, close: 4500, close_date: "2026-10-26", entry: 4520, stop: 4380, target: 4800 },
  plan_status: "no_trade", status_reasons: ["3 items conflict with the bullish view against 3 that support it."], preferred: null, sized_shares: null,
  plan_inputs: {}, earlier_list_dates: [], days_on_list: 1,
};
const DATES = [{ list_date: "2026-10-26", cash: 2, fno: 2 }, { list_date: "2026-10-23", cash: 1, fno: 0 }, { list_date: "2026-10-22", cash: 3, fno: 3 }];
const NOTES = {
  cash_ranking: "Ranked by the scanner's rules-based score. It is not a probability of profit.", cash_caveats: [],
  fno_ranking: TOP.ranking_note, fno_gaps: TOP.gaps, fno_staleness: "The option chain is from 2026-10-26 but the market regime was last classified on 2026-10-23.",
  fno_chain_as_of: "2026-10-26", fno_rules_version: TOP.rules_version, fno_skipped: [], regime: { available: true, label: "Bearish", as_of: "2026-10-23", trend: "down", india_vix: 16.86 },
};
const RULES = { cash: "The AI scanner's merged setup list ranked by its evidence score, top 10.", fno: "NIFTY, BANKNIFTY and F&O stocks, one row per instrument, top 10." };
const DAY26 = { list_date: "2026-10-26", built_at: "2026-10-26T14:45:00+00:00", available_dates: DATES, cash: [ICICI, CRISIL], fno: FNO, notes: NOTES, rules: RULES, read_only: true };
const DAY23 = { ...DAY26, list_date: "2026-10-23", cash: [{ ...ICICI, days_on_list: 1, earlier_list_dates: [] }], fno: [] };

// ── live (GET /api/live/stream; POST /api/live/fno-quotes) ────────────────

const LIVE_ICICI = 1236;
function stream(mode: "live" | "closed" | "expired") {
  const quotes = mode === "live" ? { ICICIBANK: { ltp: LIVE_ICICI, change: 10, change_pct: 0.82, open: 1225, high: 1240, low: 1220, close: 1226, volume: 1000, oi: null, ts: "2026-10-27T11:13:09+05:30" } } : {};
  return { as_of: "2026-10-27T05:43:10+00:00", data_at: "2026-10-27T05:43:09+00:00", age_seconds: 1, stale: mode !== "live", stale_after_seconds: 75, cadence_seconds: 30, mode,
    session: mode === "live" ? "open" : "closed", source: "ws", final: false, count: Object.keys(quotes).length, missing: [], quotes, read_only: true };
}
/** One price per requested leg, in request order: 1.25 × the list day's premium. */
const livePrice = (entry: number) => Math.round(entry * 1.25 * 100) / 100;

interface Seen { days: string[]; paper: Array<Record<string, unknown>>; paperKeys: Array<string | undefined>; payoff: number; fnoQuotes: number; levels: number }

async function open(page: Page, o: { feed?: "live" | "closed" | "expired"; day?: (date: string | null) => { status: number; body: unknown }; phone?: boolean } = {}): Promise<Seen> {
  const seen: Seen = { days: [], paper: [], paperKeys: [], payoff: 0, fnoQuotes: 0, levels: 0 };
  if (o.phone) await page.setViewportSize({ width: 390, height: 844 });
  await mockApi(page, "populated");
  await page.route("**/api/desk/ai-watchlist*", (route) => {
    const date = new URL(route.request().url()).searchParams.get("date");
    seen.days.push(date ?? "newest");
    if (o.day) { const r = o.day(date); return reply(route, r.body, r.status); }
    if (date === "2026-10-23") return reply(route, DAY23);
    if (date === "2026-10-22") return reply(route, { detail: { code: "not_stored" } }, 404);
    return reply(route, DAY26);
  });
  await page.route("**/api/live/**", (route) => {
    const p = new URL(route.request().url()).pathname;
    if (p.endsWith("/fno-quotes")) {
      seen.fnoQuotes += 1;
      const legs = (route.request().postDataJSON()?.legs ?? []) as unknown[];
      const flat = FNO.flatMap((i: { legs: Array<{ entry_price: number }> }) => i.legs);
      const quotes = Object.fromEntries(legs.map((_, i) => [String(i), { last_price: livePrice(flat[i].entry_price) }]));
      return reply(route, { available: true, quotes, unresolved: [] });
    }
    if (p.endsWith("/stream")) return route.fulfill({ status: 200, contentType: "text/event-stream", body: `retry: 100\n\nevent: snapshot\ndata: ${JSON.stringify(stream(o.feed ?? "expired"))}\n\n` });
    return reply(route, stream(o.feed ?? "expired"));
  });
  await page.route("**/api/fno/scan/buildup*", (route) => reply(route, { as_of: "2026-10-26", indices: [], counts: {}, sources: {}, master: {}, risk_flag_text: {}, rows: [
    { symbol: "MPHASIS", near_expiry: "2026-10-27", close: 2510, prev_close: 2560, price_chg_pct: -1.95, oi: 3_000_000, oi_chg: 175_000, oi_chg_pct: 6.2, expiries: 3,
      label: "short_buildup", days_to_expiry: 1, fut_contracts: 900, fut_turnover_cr: 812.4, cash_confirmation: "confirms", fno_eligible: true, risk_flags: [] },
  ] }));
  await page.route("**/api/desk/paper-trades*", (route) => {
    if (route.request().method() === "POST") {
      seen.paper.push(route.request().postDataJSON());
      seen.paperKeys.push(route.request().headers()["idempotency-key"]);
      return reply(route, { trade: { id: "t1" } }, 201);
    }
    return reply(route, { as_of: "2026-10-26", trades: [], summary: null });
  });
  // A stored day's levels are never asked for again: any call here is counted and answered with a MOCK not-valid reply.
  await page.route("**/api/desk/strategy/levels", (route) => { seen.levels += 1; return reply(route, { valid: false, problems: [{ code: "mock", message: "MOCK" }] }); });
  await page.route("**/api/desk/strategy/payoff", (route) => { seen.payoff += 1; return reply(route, { valid: false, problems: [{ code: "mock", message: "MOCK payoff not drawn" }], warnings: [] }); });
  await page.goto(PAGE);
  return seen;
}

const params = (page: Page) => new URL(page.url()).searchParams;

test.describe("AI scanner watchlist", () => {
  test("F-1 / F-2 the block comes first, with the dateline newest first and the newest day picked", async ({ page }) => {
    await open(page);
    const block = page.getByTestId("ai-scanner-watchlist");
    await expect(block).toBeVisible(SLOW);
    await expect(page.getByTestId("aiw-title")).toHaveText("AI scanner watchlist · Mon, 26 Oct");
    const chips = page.getByTestId("aiw-dateline").getByRole("button");
    await expect(chips).toHaveCount(3);
    expect(await chips.evaluateAll((els) => els.map((e) => e.getAttribute("data-testid")))).toEqual(["aiw-day-2026-10-26", "aiw-day-2026-10-23", "aiw-day-2026-10-22"]);
    await expect(page.getByTestId("aiw-day-2026-10-26")).toHaveAttribute("aria-pressed", "true");
    await expect(page.getByTestId("aiw-day-2026-10-26")).toContainText("latest");
    await expect(page.getByTestId("aiw-day-2026-10-23")).toContainText("1 cash · 0 F&O");
    // First on the page: above the research watchlist block (and every block after it).
    const research = page.getByTestId("watchlist-count");
    await expect(research).toBeVisible();
    expect((await block.boundingBox())!.y).toBeLessThan((await research.boundingBox())!.y);
  });

  test("F-2 a day chip loads that day; a day with nothing stored says so and offers the latest", async ({ page }) => {
    const seen = await open(page);
    await page.getByTestId("aiw-day-2026-10-23").click(SLOW);
    await expect(page.getByTestId("aiw-title")).toHaveText("AI scanner watchlist · Fri, 23 Oct");
    await expect(page.getByTestId("aiw-day-2026-10-23")).toHaveAttribute("aria-pressed", "true");
    expect(seen.days).toContain("2026-10-23");
    await expect(page.getByTestId("aiw-cash-ICICIBANK").getByTestId("aiw-days-on")).toHaveText("New on this list");
    await page.getByTestId("aiw-day-2026-10-22").click();
    await expect(page.getByTestId("aiw-not-stored")).toContainText("No list is stored for");
    await page.getByTestId("aiw-not-stored").getByRole("button", { name: "Show the latest list" }).click();
    await expect(page.getByTestId("aiw-title")).toHaveText("AI scanner watchlist · Mon, 26 Oct");
  });

  test("F-3 a cash idea: setup, score, list-day close, strategy that fits or the plan's reason, days on the list", async ({ page }) => {
    await open(page);
    const icici = page.getByTestId("aiw-cash-ICICIBANK");
    await expect(icici).toBeVisible(SLOW);
    await expect(icici).toContainText("Score 86/100");
    await expect(icici).toContainText("Breakout confirmed");
    await expect(icici.getByTestId("aiw-cash-listed")).toContainText("1,200");
    await expect(icici.getByTestId("aiw-cash-strategy")).toContainText("Bull call spread 1200/1250");
    await expect(icici.getByTestId("aiw-cash-strategy")).toContainText("2.40 : 1");
    await expect(icici.getByTestId("aiw-days-on")).toHaveText("2 days on the list");
    await expect(icici.getByTestId("aiw-oi")).toContainText("not in the end-of-day scan");      // ICICIBANK has no row in the mocked scan
    const crisil = page.getByTestId("aiw-cash-CRISIL");
    await expect(crisil.getByTestId("aiw-cash-strategy")).toContainText("3 items conflict with the bullish view");
    await expect(crisil.getByTestId("aiw-days-on")).toHaveText("New on this list");
    await expect(crisil.getByTestId("aiw-cash-latest")).toHaveAttribute("data-kind", "none");
  });

  test("F-4 while the feed is live, the cash price is Kite's and the change since the list day is worked out from it", async ({ page }) => {
    await open(page, { feed: "live" });
    const latest = page.getByTestId("aiw-cash-ICICIBANK").getByTestId("aiw-cash-latest");
    await expect(latest).toHaveAttribute("data-kind", "live", SLOW);
    await expect(latest).toContainText("Live · Kite");
    await expect(latest).toContainText("1,236");
    await expect(page.getByTestId("aiw-cash-ICICIBANK").getByTestId("aiw-cash-since")).toHaveText(`+${(((LIVE_ICICI - 1200) / 1200) * 100).toFixed(2)}% since the list`);
    await expect(page.getByTestId("aiw-price-mode")).toContainText("Live prices · Kite");
  });

  test("F-5 cash links open the desk's chart, the plan and the chain; a paper trade posts the scanner's levels", async ({ page }) => {
    const seen = await open(page);
    const icici = page.getByTestId("aiw-cash-ICICIBANK");
    await expect(page.getByTestId("aiw-cash-CRISIL").getByTestId("aiw-cash-chain")).toHaveCount(0, SLOW);  // not F&O
    await icici.getByTestId("aiw-cash-paper").click();
    await expect(icici.getByTestId("aiw-paper-qty")).toHaveValue("208");
    await icici.getByTestId("aiw-paper-add").click();
    await expect(icici.getByTestId("aiw-paper-done")).toContainText("208 ICICIBANK");
    // paper_fills_pnl TESTCASES ER-3: entry 1200 at the list's close 1200 fills at once.
    // p2_exits_backtest TC-70: the scanner's holding window (horizon_days 15) is sent as the time exit.
    expect(seen.paper).toEqual([{ symbol: "ICICIBANK", quantity: 208, entry_price: 1200, stop_price: 1160, target_price: 1280,
      source: { kind: "scanner", bucket: "breakout_confirmed", signal_date: "2026-10-26" }, entry_rule: "at_once", max_hold_sessions: 15 }]);
    await expect(icici).toContainText("exits after 15 sessions held");
    // desk_paper_safety TESTCASES UI-4: the submission carries one Idempotency-Key (a UUID).
    expect(seen.paperKeys).toHaveLength(1);
    expect(seen.paperKeys[0]).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);

    await icici.getByTestId("aiw-cash-plan").click();
    await expect(page).toHaveURL(/\/v5\/app\/trader\/desk\?/);
    const p = params(page);
    expect([p.get("tab"), p.get("view"), p.get("mode"), p.get("build"), p.get("sym"), p.get("cand"), p.get("src_kind"), p.get("src_date")])
      .toEqual(["more", "strategy", "stock", "1", "ICICIBANK", "options:bull_call_spread", "ideas", "2026-10-26"]);
    await page.goBack();
    await page.getByTestId("aiw-cash-ICICIBANK").getByTestId("aiw-cash-chart").click(SLOW);
    expect([params(page).get("tab"), params(page).get("sym")]).toEqual(["chart", "ICICIBANK"]);
    await page.goBack();
    await page.getByTestId("aiw-cash-ICICIBANK").getByTestId("aiw-cash-chain").click(SLOW);
    expect([params(page).get("tab"), params(page).get("lab"), params(page).get("lab_sym")]).toEqual(["fno", "chain", "ICICIBANK"]);
  });

  test("F-6 an F&O idea: legs, net Greeks and the underlying's OI build-up; payoff only once asked; paper trade as a strategy", async ({ page }) => {
    const seen = await open(page);
    await page.getByTestId("aiw-seg-fno").click(SLOW);
    const rows = page.getByTestId("aiw-fno-list").locator(":scope > li");
    expect(await rows.evaluateAll((els) => els.map((e) => [e.getAttribute("data-testid"), e.getAttribute("data-kind")]))).toEqual([["aiw-fno-MPHASIS", "stock"], ["aiw-fno-BANKNIFTY", "index"]]);
    const m = page.getByTestId("aiw-fno-MPHASIS");
    await expect(m.getByTestId("aiw-fno-strategy")).toContainText(mph.name);
    await expect(m.getByTestId("aiw-fno-legs").locator("tbody tr")).toHaveCount(mph.legs.length);
    await expect(m.getByTestId("aiw-fno-greeks")).toContainText("Net delta");
    await expect(m.getByTestId("aiw-fno-greeks")).toContainText(mph.net_greeks.delta.toFixed(2));
    await expect(m.getByTestId("aiw-oi")).toHaveAttribute("data-label", "short_buildup");
    await expect(m.getByTestId("aiw-oi")).toContainText("OI +6.2%");
    await expect(m.getByTestId("aiw-fno-live")).toHaveAttribute("data-state", "off");
    expect(seen.payoff).toBe(0);
    await m.getByTestId("idea-payoff-toggle").click();
    await expect.poll(() => seen.payoff).toBe(1);
    await m.getByTestId("idea-paper-trade").click();
    await expect(m.getByTestId("idea-paper-trade")).toHaveText("Added to paper trades");
    expect(seen.paper[0]).toMatchObject({ kind: "strategy", underlying: "MPHASIS", family: mph.structure });
    expect((seen.paper[0].legs as unknown[]).length).toBe(mph.legs.length);
  });

  test("F-6 live: each leg's live premium and the change since the list day, per the listed lots", async ({ page }) => {
    const seen = await open(page, { feed: "live" });
    await page.getByTestId("aiw-seg-fno").click(SLOW);
    const m = page.getByTestId("aiw-fno-MPHASIS");
    await expect(m.getByTestId("aiw-fno-live")).toHaveAttribute("data-state", "live", SLOW);
    expect(seen.fnoQuotes).toBeGreaterThan(0);
    const legs = mph.legs as Array<{ side: string; entry_price: number; quantity: number; lot_size: number }>;
    const liveNet = Math.round(legs.reduce((a, l) => a + (l.side === "sell" ? 1 : -1) * livePrice(l.entry_price) * l.quantity * l.lot_size, 0) * 100) / 100;
    const change = Math.round((mph.net_premium - liveNet) * 100) / 100;
    await expect(m.getByTestId("aiw-fno-change")).toContainText(Math.abs(change).toLocaleString("en-IN", { maximumFractionDigits: 0 }));
    await expect(m.getByTestId("aiw-fno-leg-live").first()).toHaveText(livePrice(legs[0].entry_price).toFixed(2));
  });

  test("F-7 F&O links: the lab with the idea in focus (Candidates for a stock, the index workspace for an index)", async ({ page }) => {
    await open(page);
    await page.getByTestId("aiw-seg-fno").click(SLOW);
    await page.getByTestId("aiw-fno-MPHASIS").getByTestId("aiw-fno-lab").click();
    expect([params(page).get("tab"), params(page).get("lab"), params(page).get("lab_sym"), params(page).get("lab_focus")]).toEqual(["fno", "candidates", "MPHASIS", "MPHASIS"]);
    await page.goBack();
    await page.getByTestId("aiw-seg-fno").click(SLOW);
    await page.getByTestId("aiw-fno-BANKNIFTY").getByTestId("aiw-fno-lab").click();
    expect([params(page).get("lab"), params(page).get("lab_focus")]).toEqual(["indices", "BANKNIFTY"]);
    await page.goBack();
    await page.getByTestId("aiw-seg-fno").click(SLOW);
    await page.getByTestId("aiw-fno-MPHASIS").getByTestId("aiw-fno-buildup").click();
    expect([params(page).get("tab"), params(page).get("lab"), params(page).get("lab_sym")]).toEqual(["fno", null, "MPHASIS"]);
  });

  test("L-1 an F&O idea with levels stored with the day: shown labelled and dated, and its paper trade posts the contract body", async ({ page }) => {
    const seen = await open(page);
    await page.getByTestId("aiw-seg-fno").click(SLOW);
    const row = page.getByTestId("aiw-fno-BANKNIFTY");
    const lv = row.getByTestId("idea-levels");
    await expect(lv).toHaveAttribute("data-state", "ok");
    await expect(lv.getByTestId("idea-levels-label")).toHaveText("Provisional · research levels");
    await expect(lv.getByTestId("idea-levels-asof")).toHaveText("end-of-day chain of 21 Oct 2026 · worked out on the list day (21 Oct 2026)");
    const f2 = (n: number) => n.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    await expect(lv.getByTestId("idea-levels-stop")).toContainText(`(BANKNIFTY ${f2(LEVELS.underlying.stop)})`);
    await expect(lv.locator("button")).toHaveCount(1);
    await lv.getByTestId("idea-levels-plan").click();
    await expect(lv.getByTestId("desk-levels")).toBeVisible();
    await row.getByTestId("idea-paper-trade").click();
    await expect(row.getByTestId("idea-paper-trade")).toHaveText("Added to paper trades");
    expect(seen.paper).toEqual([CONTRACT.body_with_levels]);
    expect(seen.levels).toBe(0);
  });

  test("L-2 an F&O idea from a day stored without levels says so, asks for none, and records none", async ({ page }) => {
    const seen = await open(page);
    await page.getByTestId("aiw-seg-fno").click(SLOW);
    const row = page.getByTestId("aiw-fno-MPHASIS");
    await expect(row.getByTestId("idea-levels")).toHaveAttribute("data-state", "not-stored");
    await expect(row.getByTestId("idea-levels")).toContainText("not stored with this day’s list");
    await row.getByTestId("idea-paper-trade").click();
    await expect(row.getByTestId("idea-paper-trade")).toHaveText("Added to paper trades");
    const body = seen.paper[0] as Record<string, any>;
    expect(body).not.toHaveProperty("stop_underlying");
    expect(body).not.toHaveProperty("target_underlying");
    expect(body.signal).toMatchObject({ signal_at: mph.data_as_of.chain, rule_version: TOP.rules_version });
    await page.waitForTimeout(300);
    expect(seen.levels).toBe(0);
  });

  test("F-8 nothing stored yet says when the job runs; a failing route offers a retry and the page stays", async ({ page }) => {
    await open(page, { day: () => ({ status: 200, body: { list_date: null, available_dates: [], cash: [], fno: [], notes: {}, rules: {}, empty_reason: "No list is stored yet. The job runs each weekday at 20:15 IST, after the AI scanner's 19:45 run, and keeps every day's list." } }) });
    await expect(page.getByTestId("aiw-empty")).toContainText("20:15 IST", SLOW);
    await page.unrouteAll({ behavior: "ignoreErrors" });
    await open(page, { day: () => ({ status: 500, body: { detail: "boom" } }) });
    await expect(page.getByTestId("aiw-error")).toBeVisible({ timeout: 20_000 });
    await expect(page.getByTestId("aiw-error").getByRole("button", { name: /retry/i })).toBeVisible();
    await expect(page.getByTestId("screen-page-watchlist")).toBeVisible();
  });

  test("F-9 the block says ideas, never picks or suggestions, and keeps the routes' notes on screen", async ({ page }) => {
    await open(page);
    await expect(page.getByTestId("aiw-cash-list")).toBeVisible(SLOW);
    let text = await page.getByTestId("ai-scanner-watchlist").innerText();
    await page.getByTestId("aiw-seg-fno").click();
    await expect(page.getByTestId("aiw-regime")).toContainText("measured Fri, 23 Oct");
    text += await page.getByTestId("ai-scanner-watchlist").innerText();
    expect(text).not.toMatch(/\bpicks?\b/i);
    expect(text).not.toMatch(/\bsuggested\b/i);
    expect(text.replace(/not recommendations?/gi, "")).not.toMatch(/recommend/i);
    await expect(page.getByTestId("aiw-ranking-note")).toContainText("not a forecast");
    await expect(page.getByTestId("aiw-disclaimer")).toContainText("not recommendations");
  });
});

test.describe("AI scanner watchlist · phone", () => {
  test("F-10 390px: the dateline scrolls inside itself; no sideways scroll on the page", async ({ page }) => {
    await open(page, { phone: true });
    await expect(page.getByTestId("aiw-cash-ICICIBANK")).toBeVisible(SLOW);
    await page.getByTestId("aiw-seg-fno").click();
    await expect(page.getByTestId("aiw-fno-MPHASIS")).toBeVisible();
    const over = await page.evaluate(() => {
      const sc = document.querySelector('[data-testid="copilot-scroll"]') as HTMLElement | null;
      return Math.max(document.documentElement.scrollWidth - window.innerWidth, sc ? sc.scrollWidth - sc.clientWidth : 0);
    });
    expect(over).toBeLessThanOrEqual(0);
  });
});


// ── Phase 2.1: a stored row records its TradePlan (test_reports/p2_trade_plan_lifecycle_TESTCASES.md UI-2) ──────────
// The plan is the shared contract fixture's (contract-trade-plan-paper.json; MOCK — the RELIANCE-like world of
// backend/tests/test_strategy_plan.py), stored on the row as the nightly job stores it (ai_watchlist_build.cash_entry).
const PLANS = fixture("contract-trade-plan-paper.json");
test.describe("AI scanner watchlist — trade plans (Phase 2.1)", () => {
  test("UI-2 a stored cash row records the stored plan's levels with plan_ref; a day stored before plans keeps the scanner's", async ({ page }) => {
    const withPlan = { ...ICICI, trade_plan_id: PLANS.cash.trade_plan.plan_id, trade_plan: PLANS.cash.trade_plan };
    const seen = await open(page, { day: () => ({ status: 200, body: { ...DAY26, cash: [withPlan, CRISIL] } }) });
    const icici = page.getByTestId("aiw-cash-ICICIBANK");
    await icici.getByTestId("aiw-cash-paper").click(SLOW);
    await expect(icici.getByTestId("aiw-paper-plan")).toHaveAttribute("data-plan-id", PLANS.cash.trade_plan.plan_id);
    await expect(icici.getByTestId("aiw-paper-qty")).toHaveValue("208");
    await icici.getByTestId("aiw-paper-add").click();
    await expect(icici.getByTestId("aiw-paper-done")).toContainText("208 ICICIBANK");
    // The contract body, with the row's own quantity and list date (both informational to the route).
    expect(seen.paper).toEqual([{ ...PLANS.cash.body, quantity: 208, source: { ...PLANS.cash.body.source, signal_date: "2026-10-26" } }]);
    // CRISIL was stored without a plan (a day before plans existed): it still records the scanner's levels, as before.
    const crisil = page.getByTestId("aiw-cash-CRISIL");
    await crisil.getByTestId("aiw-cash-paper").click();
    await expect(crisil.getByTestId("aiw-paper-plan")).toHaveCount(0);
  });
});
