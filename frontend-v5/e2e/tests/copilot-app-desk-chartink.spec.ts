/**
 * One-screen Copilot app - Smart trading desk: the user's Chartink scans as opportunity sources
 * (screens/tradingdesk/chartink/*; settings at ?tab=more&view=chartink, merged into the Overview "Top AI opportunities" card,
 * the AI Scanner ("Chartink scans" category, "On Chartink" filter) and the Strategy Builder's ideas board).
 *
 * MOCK - not real data. Every /api/desk/chartink/* answer below is written by hand to the contract (chartink-contract.ts) while
 * the backend routes are built in parallel. The scan names, descriptions and stocks are INVENTED (public repo); they are not any
 * real Chartink scan or clause. The figures are HAND-COMPUTED so the screen is checked against known numbers:
 *
 *   Scans: 1001 "Volume Burst Sample" (bullish, on), 1002 "Gap Fill Sample" (neutral, on, intraday candles), 1003 "Custom Indicator
 *   Sample" (cannot run: private indicators), 1004 "Breadth Widget Sample" (market statistics), 1005 "Weak Close Sample" (bearish, on).
 *   Hits (symbols, by scans listing them):
 *     TESTBRK   1001 + 1002  (count 2)  in the AI scanner (the watchlist fixture's stock)
 *     QUBEX     1001 + 1005  (count 2)  not in the AI scanner, close 1,250.50, -1.2%
 *     ZEDCO     1001         (count 1)  not in the AI scanner, close 250.00, +2.4%, F&O
 *     WIDGETCO  1002         (count 1)  not in the AI scanner, close 88.40, +0.5%
 *     PLANETX   1001         (count 1)  not in the AI scanner, close 40.00, +3.1%
 *     MOONCORP  1001         (count 1)  not in the AI scanner, close 600.00, +1.0%
 *   Hits per scan: 1001 -> TESTBRK, QUBEX, ZEDCO, PLANETX, MOONCORP = 5; 1002 -> TESTBRK, WIDGETCO = 2; 1005 -> QUBEX = 1.
 *   Check: the symbols' counts add up to 2 + 2 + 1 + 1 + 1 + 1 = 8 = 5 + 2 + 1 (the per-scan hits).
 *   Stocks in the hits: 6; not in the AI scanner: 5; the Overview shows 4 of them (the route's order: QUBEX, ZEDCO, WIDGETCO, PLANETX), "1 more".
 *   TESTBRK's tag: "Also on Chartink: Volume Burst Sample (+1)" (first scan, plus one more).
 *   Refresh cooldown: retry_after_s 420 -> ceil(420 / 60) = 7 minutes.
 *
 * Cases: CK-1 connect (client checks, 422, success) · CK-2 scan table states · CK-3 toggles and direction PATCH bodies · CK-4 refresh and
 * cooldown · CK-5 disconnect confirmation · CK-6 honest states (error, unreachable, partial, no hits, not connected) · CK-7 Overview merge
 * (desktop) · CK-8 Overview degrades · CK-9 Overview phone · CK-10 Scanner chip, URL and filter · CK-11 ideas board source tags and switch ·
 * CK-12 plan evidence item and candidate label · CK-13 persona · CK-14 390px settings · CK-15 reads only, no order controls.
 */
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";
import { test, expect, type Page, type Route } from "@playwright/test";
import { mockApi, mockSingleRoute } from "../helpers/api-mock";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const DESK = "/v5/app/trader/desk";
const SETTINGS = `${DESK}?tab=more&view=chartink`;
const IDEAS = `${DESK}?tab=more&view=strategy`;
const json = (route: Route, body: unknown, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
const planFixture = (n: string) => JSON.parse(fs.readFileSync(path.join(__dirname, "..", "fixtures", `strategy-plan-${n}.json`), "utf-8"));
const SHOTS = process.env.SHOTS_DIR;
const shot = async (page: Page, name: string, w: number) => {
  if (!SHOTS) return;
  fs.mkdirSync(SHOTS, { recursive: true });
  await page.screenshot({ path: path.join(SHOTS, `ck-${name}-${w}.png`) });
};

// ── the MOCK payloads ────────────────────────────────────────────────────

const FETCHED = "2026-10-20T05:00:00+00:00"; // 10:30 IST
const URL_OK = "https://chartink.com/dashboard/900001";
const run = (hits: number) => ({ at: FETCHED, ok: true, hits, error: null, seconds: 2.4 });
const scan = (o: Record<string, unknown>) => ({ description: null, kind: "stock_scan", supported: true, unsupported_reason: null, uses_intraday_candles: false, enabled: true, direction: "bullish", last_run: null, ...o });
const SCANS = [
  scan({ id: "1001", name: "Volume Burst Sample", description: "Invented scan: volume far above its recent average", direction: "bullish", last_run: run(5) }),
  scan({ id: "1002", name: "Gap Fill Sample", description: "Invented scan: a gap that closed within the session", direction: "neutral", uses_intraday_candles: true, last_run: run(2) }),
  scan({ id: "1003", name: "Custom Indicator Sample", description: "Invented scan with a private indicator", supported: false, unsupported_reason: "uses custom indicators from your Chartink account, which the public endpoint cannot run", enabled: false }),
  scan({ id: "1004", name: "Breadth Widget Sample", description: "Invented market statistics widget", kind: "market_stats", supported: false, unsupported_reason: "Market statistics, not a stock list", enabled: false, direction: "neutral" }),
  scan({ id: "1005", name: "Weak Close Sample", description: "Invented scan: closes near the day's low", direction: "bearish", last_run: run(1) }),
];
const sourceDoc = (scans: unknown[] = SCANS, retryAfter: number | null = null) => ({
  dashboard_id: "900001", url: URL_OK, title: "Sample dashboard", fetched_at: FETCHED, scans,
  summary: { scans: scans.length, stock_scans: scans.filter((x) => (x as { kind: string }).kind === "stock_scan").length, supported: scans.filter((x) => (x as { supported: boolean }).supported).length, enabled: scans.filter((x) => (x as { enabled: boolean }).enabled).length },
  refresh: { last_started_at: retryAfter ? FETCHED : null, retry_after_s: retryAfter },
});
type Doc = ReturnType<typeof sourceDoc>;
/** The routes' typed error: {detail: {code, message, ...}} plus the envelope's status / error / code / message and the extras at the top level. */
const typed = (status: number, code: string, message: string, extra: Record<string, unknown> = {}) => ({ status, error: code, code, message, detail: { code, message, ...extra }, ...extra });
const sc = (id: string, name: string, direction: string) => ({ id, name, direction });
const S1001 = sc("1001", "Volume Burst Sample", "bullish");
const S1002 = sc("1002", "Gap Fill Sample", "neutral");
const S1005 = sc("1005", "Weak Close Sample", "bearish");
const hit = (o: Record<string, unknown>) => ({ name: null, volume: 100000, in_ai_scanner: false, ai_score: null, fno_eligible: null, ...o });
const HITS = {
  as_of_date: "2026-10-19", fetched_at: FETCHED, mode: "end_of_day_snapshot",
  scans: [
    { id: "1001", name: "Volume Burst Sample", direction: "bullish", hits: 5, ok: true, error: null, uses_intraday_candles: false },
    { id: "1002", name: "Gap Fill Sample", direction: "neutral", hits: 2, ok: true, error: null, uses_intraday_candles: true },
    { id: "1005", name: "Weak Close Sample", direction: "bearish", hits: 1, ok: true, error: null, uses_intraday_candles: false },
  ],
  symbols: [
    hit({ symbol: "TESTBRK", name: "Test Breakout Ltd", scans: [S1001, S1002], count: 2, close: 510, pct_change: 1.8, in_ai_scanner: true, ai_score: 71, fno_eligible: false }),
    hit({ symbol: "QUBEX", name: "Qubex Systems Ltd", scans: [S1001, S1005], count: 2, close: 1250.5, pct_change: -1.2, fno_eligible: false }),
    hit({ symbol: "ZEDCO", name: "Zed Industries Ltd", scans: [S1001], count: 1, close: 250, pct_change: 2.4, fno_eligible: true }),
    hit({ symbol: "WIDGETCO", name: "Widget Co Ltd", scans: [S1002], count: 1, close: 88.4, pct_change: 0.5, fno_eligible: null }),
    hit({ symbol: "PLANETX", name: null, scans: [S1001], count: 1, close: 40, pct_change: 3.1, fno_eligible: false }),
    hit({ symbol: "MOONCORP", name: "Moon Corp Ltd", scans: [S1001], count: 1, close: 600, pct_change: 1, fno_eligible: false }),
  ],
  is_today: false, age_days: 1, dashboard_id: "900001", empty_reason: null,
  unknown_symbols: [], source_failures: [],
};

const WATCHLIST = { as_of_date: "2026-10-19", buckets: {
  breakout_confirmed: [{ nse_symbol: "TESTBRK", sector: "Capital Goods", close_price: 510.0, trigger_price: 500.0, stop_price: 477.5, atr_pct: 2.94, why: "Fixture reason" }],
  pre_breakout: [], true_accumulation: [], trend_continuation: [] } };
const PICKS = { signal_date: "2026-10-19", count: 0, picks: [] };

// ── ideas (MOCK, contract-shaped; the same cash strategy shape as the ideas spec) ─

const strat = (o: Record<string, unknown>) => ({
  segment: "cash", family: "", status: "candidate", legs_text: "", max_loss: null, max_loss_basis: null, capital_at_risk: null, max_profit: null, profit_unbounded: false, breakeven: [],
  reward_risk_net: null, reward_risk_gross: null, actionable: false, liquidity_flags: [], why: null, flags: [],
  sizing: { status: null, quantity: null, lots: null, binding: null, unit: null, risk_budget_inr: null, risk_at_stop_inr: null, deployed_inr: null, missing: [] }, ...o,
  reasons: [],
});
const idea = (o: Record<string, unknown>) => ({
  rank: 1, name: null, direction: "bullish", fno_eligible: false, plan_id: null, plan_status: "plan", status_reasons: [{ code: "ok", message: "MOCK status reason" }], would_change_if: [],
  plan_inputs: { underlying: "TESTBRK", direction: "bullish", instrument: "cash" }, headline: {}, evidence_summary: {}, oi_view: null, preferred: null, strategies: [],
  scanner: { bucket: "breakout_confirmed", status: "confirmed", score: 71, close: 510, close_date: "2026-10-19", entry: 510, stop: 477.5, target: 570, reason: "MOCK", horizon_days: 10, liquidity_cr: 120, atr_pct: 2.9 },
  source: "ai_scanner", chartink: null, ...o,
});
const IDEA_BOTH = idea({ rank: 1, symbol: "TESTBRK", name: "Test Breakout Ltd", source: "both", chartink: { scans: [S1001, S1002], count: 2, fetched_at: FETCHED }, strategies: [strat({ id: "cash:breakout_continuation", label: "Buy shares on the breakout", legs_text: "Buy 100 shares at 510.00" })] });
const IDEA_AI = idea({ rank: 2, symbol: "AIONLY", name: "Ai Only Ltd", source: "ai_scanner", chartink: null, plan_inputs: { underlying: "AIONLY", direction: "bullish", instrument: "cash" } });
const IDEA_CK = idea({
  rank: 3, symbol: "QUBEX", name: "Qubex Systems Ltd", source: "chartink", chartink: { scans: [S1001, S1005], count: 2, fetched_at: FETCHED },
  // The real route: bucket, status, score, entry, stop and target are ALL null for a Chartink-only idea; in_watchlist / in_picks false.
  scanner: { bucket: null, status: null, score: null, close: 1250.5, close_date: "2026-10-19", entry: null, stop: null, target: null, reason: null, horizon_days: null, liquidity_cr: null, atr_pct: null, in_watchlist: false, in_picks: false },
  plan_inputs: { underlying: "QUBEX", direction: "bullish", instrument: "cash" },
  strategies: [strat({ id: "cash:chartink_screen_signal", family: "chartink_screen_signal", label: "Chartink scan signal (long)", legs_text: "Buy 10 shares at 1,250.50" })],
});
const SEL_CK = { included: true, state: "ok", reason: null, scan_date: "2026-10-19", fetched_at: FETCHED, mode: "end_of_day_snapshot", limit: 4, considered: 5, added: 1, excluded: [], note: "Chartink-only ideas are placed above the AI scanner's by how many of your scans list them.", rule: "MOCK rule", gates: [] };
const ideasBody = (ck: unknown = SEL_CK) => ({
  generated_at: "2026-10-20T05:00:00+00:00", data_as_of: { mode: "end_of_day", price: "2026-10-19", fno: "2026-10-19" }, caveats: [], rules_version: "strategy-rules-v2", calculation_version: "payoff-v1", sent_to_broker: false,
  ranking_note: "AI scanner ideas first, ranked by score. Chartink-only ideas follow, ranked by how many of your scans list them. Neither is a probability.",
  selection: { source: "positional_watchlist", scan_date: "2026-10-19", rule: "MOCK rule", considered: 3, selected: 3, excluded: [], limit: 8, empty_reason: null, gate: null, source_failures: [], chartink: ck },
  inputs: { defaults_applied: [] }, ideas: [IDEA_BOTH, IDEA_AI, IDEA_CK],
});

const RATE = "http_429: Chartink is rate limiting this server (429); try again later";
const REFRESH_OK = {
  ran_at: FETCHED, scan_date: "2026-10-19", dashboard_id: "900001", ok_count: 2, failed_count: 1, skipped_over_cap: [], uses_intraday_candles: true, degraded: null,
  scans: [
    { id: "1001", name: "Volume Burst Sample", direction: "bullish", ok: true, hits: 5, error: null, error_code: null, seconds: 2.4 },
    { id: "1002", name: "Gap Fill Sample", direction: "neutral", ok: false, hits: null, error: RATE, error_code: "http_429", seconds: 20 },
    { id: "1005", name: "Weak Close Sample", direction: "bearish", ok: true, hits: 1, error: null, error_code: null, seconds: 1.8 },
  ],
};

// ── page plumbing ────────────────────────────────────────────────────────

interface Opts {
  /** The ideas' selection.chartink block (default: state ok). */
  ideasChartink?: unknown;
  /** The saved dashboard: a document, null (not connected), or an error status. */
  source?: Doc | null | { status: number };
  hits?: typeof HITS | { status: number };
  put?: Array<{ status: number; body: unknown }>;
  refresh?: Array<{ status: number; body: unknown }>;
}
interface State { doc: Doc | null; puts: unknown[]; patches: Array<{ id: string; body: Record<string, unknown> }>; refreshes: number; deletes: number; ideas: Array<Record<string, unknown>>; builds: unknown[]; writes: string[]; sourceCalls: number; hitsCalls: number }

async function setup(page: Page, o: Opts = {}): Promise<State> {
  const st: State = { doc: null, puts: [], patches: [], refreshes: 0, deletes: 0, ideas: [], builds: [], writes: [], sourceCalls: 0, hitsCalls: 0 };
  const src = o.source === undefined ? sourceDoc() : o.source;
  const errored = src && "status" in src ? src : null;
  st.doc = src && !("status" in src) ? (JSON.parse(JSON.stringify(src)) as Doc) : null;
  const putQ = [...(o.put ?? [])];
  const refQ = [...(o.refresh ?? [])];
  await mockApi(page, "populated");
  await mockSingleRoute(page, "**/api/markets/home", "markets-home.json");
  page.on("request", (r) => {
    const p = new URL(r.url()).pathname;
    if (r.method() !== "GET" && /\/api\//.test(p) && !/\/api\/desk\/(chartink\/|strategy\/(ideas|plan|payoff)$)/.test(p)) st.writes.push(`${r.method()} ${p}`);
  });
  await page.route("**/api/positional/watchlist*", (r) => json(r, WATCHLIST));
  await page.route("**/api/positional/picks*", (r) => json(r, PICKS));
  await page.route("**/api/move-odds/**", (r) => json(r, { detail: "feature_not_enabled" }, 403));
  await page.route("**/api/desk/paper-trades*", (r) => json(r, { as_of: null, trades: [], summary: null }));
  await page.route("**/api/desk/alerts*", (r) => json(r, { as_of: null, alerts: [] }));
  await page.route("**/api/desk/strategy/plans*", (r) => json(r, { plans: [], count: 0, limit: 100, max_saved: 200 }));
  await page.route("**/api/desk/strategy/payoff", (r) => json(r, { detail: "not mocked here" }, 404));
  await page.route("**/api/research/chart-live/**", (r) => json(r, { detail: "not mocked here" }, 404));
  await page.route("**/api/chat/**", (r) => json(r, []));
  await page.route("**/api/watchlists", (r) => json(r, { lists: [], limits: { max_lists: 20, max_symbols: 50 }, starter_pending: false }));
  await page.route("**/api/desk/strategy/ideas", (r) => { st.ideas.push(r.request().postDataJSON() as Record<string, unknown>); return json(r, ideasBody(o.ideasChartink === undefined ? SEL_CK : o.ideasChartink)); });
  await page.route("**/api/desk/strategy/plan", (r) => { st.builds.push(r.request().postDataJSON()); return json(r, planFixture("all")); });

  await page.route("**/api/desk/chartink/source", async (r) => {
    const m = r.request().method();
    if (m === "GET") {
      st.sourceCalls += 1;
      if (errored) return json(r, { detail: "boom" }, errored.status);
      return json(r, { source: st.doc });
    }
    if (m === "PUT") {
      st.puts.push(r.request().postDataJSON());
      const next = putQ.shift() ?? { status: 200, body: { source: sourceDoc() } };
      if (next.status === 200) st.doc = (next.body as { source: Doc }).source;
      return json(r, next.body, next.status);
    }
    st.deletes += 1;
    st.doc = null;
    return json(r, { deleted: true, hits_deleted: 8 });
  });
  await page.route("**/api/desk/chartink/scans/*", (r) => {
    const id = decodeURIComponent(new URL(r.request().url()).pathname.split("/").pop() ?? "");
    const body = r.request().postDataJSON() as Record<string, unknown>;
    st.patches.push({ id, body });
    if (st.doc) st.doc = { ...st.doc, scans: st.doc.scans.map((s) => (s.id === id ? { ...s, ...body } : s)) };
    return json(r, { scan: st.doc?.scans.find((s) => s.id === id) ?? {} });
  });
  await page.route("**/api/desk/chartink/refresh", (r) => {
    st.refreshes += 1;
    const next = refQ.shift() ?? { status: 200, body: REFRESH_OK };
    return json(r, next.body, next.status);
  });
  await page.route("**/api/desk/chartink/hits", (r) => {
    st.hitsCalls += 1;
    const h = o.hits ?? HITS;
    return "status" in h ? json(r, { detail: "hits failed" }, h.status) : json(r, h);
  });
  return st;
}

async function open(page: Page, url: string, o: Opts = {}, width = 1440) {
  await page.setViewportSize({ width, height: 900 });
  const st = await setup(page, o);
  await page.goto(url);
  return st;
}
async function sideways(page: Page) {
  return page.evaluate(() => {
    const sc = document.querySelector('[data-testid="copilot-scroll"]') as HTMLElement | null;
    return { doc: document.documentElement.scrollWidth - window.innerWidth, scroll: sc ? sc.scrollWidth - sc.clientWidth : 0 };
  });
}
const row = (page: Page, id: string) => page.getByTestId(`ck-scan-${id}`);

test.describe("MOCK - not real data: Chartink scans as opportunity sources", () => {
  // ── CK-1 ─────────────────────────────────────────────────────────────

  test("CK-1 connect: the address is checked here first (https, chartink.com, /dashboard/<number>), the route's 422 problems are shown, and a good address connects", async ({ page }) => {
    const st = await open(page, SETTINGS, {
      source: null,
      put: [{ status: 422, body: typed(422, "dashboard_not_readable", "That dashboard has no scans the public endpoint can read.") }],
    });
    await expect(page.getByTestId("chartink-title")).toBeVisible();
    await expect(page.getByTestId("chartink-no-api")).toHaveText("Chartink has no official API. Nivesh reads your public dashboard and runs your scans through Chartink’s own page, at most a few times a day. Results are not validated signals.");
    await expect(page.getByTestId("chartink-not-connected")).toContainText("No Chartink dashboard connected");
    await expect(page.getByTestId("chartink-scans")).toHaveCount(0);

    const connect = page.getByTestId("chartink-connect-btn");
    const problems = page.getByTestId("chartink-connect-problems");
    const tryUrl = async (v: string) => { await page.getByTestId("chartink-url").fill(v); await connect.click(); };

    await tryUrl("");
    await expect(problems).toContainText("Paste the address");
    await tryUrl("http://chartink.com/dashboard/900001");
    await expect(problems).toContainText("must start with https://");
    await tryUrl("https://example.com/dashboard/900001");
    await expect(problems).toContainText("must be on chartink.com");
    await tryUrl("https://chartink.com/screener/volume-burst");
    await expect(problems).toContainText("/dashboard/");
    await tryUrl("not a url");
    await expect(problems).toContainText("not a web address");
    expect(st.puts).toEqual([]); // nothing reached the route

    // The route's 422 is shown as it came.
    await tryUrl(URL_OK);
    await expect(problems).toContainText("That dashboard has no scans the public endpoint can read.");
    expect(st.puts).toEqual([{ dashboard_url: URL_OK }]);

    // A good answer: the dashboard and its scans appear.
    await tryUrl(`  ${URL_OK}  `);
    await expect(page.getByTestId("chartink-scans")).toBeVisible();
    expect(st.puts[1]).toEqual({ dashboard_url: URL_OK });
    await expect(page.getByTestId("chartink-dashboard")).toContainText(URL_OK);
    await expect(page.getByTestId("chartink-not-connected")).toHaveCount(0);
    await expect(connect).toHaveText("Change dashboard");
  });

  // ── CK-2 ─────────────────────────────────────────────────────────────

  test("CK-2 the scan table: name, description, kind, can-run with the reason, intraday tag, switch, direction, last fetch and hits; market statistics listed but off", async ({ page }) => {
    await open(page, SETTINGS);
    await expect(page.getByTestId("chartink-scans")).toBeVisible();
    await expect(page.locator('[data-testid^="ck-scan-1"]')).toHaveCount(5);

    const a = row(page, "1001");
    await expect(a.getByTestId("ck-scan-name")).toHaveText("Volume Burst Sample");
    await expect(a.getByTestId("ck-scan-desc")).toContainText("volume far above its recent average");
    await expect(a.getByTestId("ck-scan-kind")).toHaveText("Stock scan");
    await expect(a.getByTestId("ck-scan-supported")).toContainText("Yes");
    await expect(a.getByTestId("ck-scan-intraday")).toHaveCount(0);
    await expect(a.getByTestId("ck-scan-enabled")).toHaveAttribute("aria-checked", "true");
    await expect(a.getByTestId("ck-scan-direction")).toHaveValue("bullish");
    await expect(a.getByTestId("ck-scan-hits")).toHaveText("5");
    await expect(a.getByTestId("ck-scan-fetched")).toContainText("10:30 IST");

    const b = row(page, "1002");
    await expect(b.getByTestId("ck-scan-intraday")).toContainText("Intraday candles");
    await expect(b.getByTestId("ck-scan-direction")).toHaveValue("neutral");
    await expect(b.getByTestId("ck-scan-hits")).toHaveText("2");

    const c = row(page, "1003");
    await expect(c.getByTestId("ck-scan-supported")).toContainText("uses custom indicators from your Chartink account, which the public endpoint cannot run");
    await expect(c.getByTestId("ck-scan-enabled")).toBeDisabled();
    await expect(c.getByTestId("ck-scan-enabled")).toHaveAttribute("aria-checked", "false");
    await expect(c.getByTestId("ck-scan-direction")).toBeDisabled();
    await expect(c.getByTestId("ck-scan-hits")).toHaveText("—");

    const d = row(page, "1004");
    await expect(d.getByTestId("ck-scan-kind")).toHaveText("Market statistics");
    await expect(d.getByTestId("ck-scan-reason")).toContainText("Market statistics, not a stock list");
    await expect(d.getByTestId("ck-scan-enabled")).toBeDisabled();

    // Accessible names: every switch and select says which scan it belongs to.
    await expect(page.getByRole("switch", { name: "Use Gap Fill Sample as an opportunity source" })).toBeVisible();
    await expect(page.getByRole("combobox", { name: "Direction of Weak Close Sample" })).toHaveValue("bearish");
    await expect(page.getByTestId("chartink-hit-summary")).toHaveText("6 stocks across your enabled scans; 1 also in the AI scan, 5 not.");
    await expect(page.getByTestId("chartink-trust")).toContainText("Chartink scans (your dashboard)");
    await expect(page.getByTestId("chartink-trust")).toContainText("Chartink fetched");
    await expect(page.getByTestId("chartink-trust")).toContainText("not validated");
    await expect(page.getByTestId("chartink-trust")).toHaveAttribute("data-mode", "eod");
    await shot(page, "settings", 1440);
  });

  // ── CK-3 ─────────────────────────────────────────────────────────────

  test("CK-3 the switch and the direction select PATCH the scan with only what changed, and the table shows the saved state", async ({ page }) => {
    const st = await open(page, SETTINGS);
    const w = row(page, "1005");
    await w.getByTestId("ck-scan-enabled").click();
    await expect.poll(() => st.patches.length).toBe(1);
    expect(st.patches[0]).toEqual({ id: "1005", body: { enabled: false } });
    await expect(w.getByTestId("ck-scan-enabled")).toHaveAttribute("aria-checked", "false");

    await row(page, "1001").getByTestId("ck-scan-direction").selectOption("bearish");
    await expect.poll(() => st.patches.length).toBe(2);
    expect(st.patches[1]).toEqual({ id: "1001", body: { direction: "bearish" } });
    await expect(row(page, "1001").getByTestId("ck-scan-direction")).toHaveValue("bearish");

    // From the keyboard: Space on a focused switch turns it back on.
    await w.getByTestId("ck-scan-enabled").focus();
    await page.keyboard.press("Space");
    await expect.poll(() => st.patches.length).toBe(3);
    expect(st.patches[2]).toEqual({ id: "1005", body: { enabled: true } });
  });

  // ── CK-4 ─────────────────────────────────────────────────────────────

  test("CK-4 Refresh now lists each scan's result in a polite live region; the cooldown 429 says how many minutes are left", async ({ page }) => {
    const st = await open(page, SETTINGS, {
      refresh: [
        { status: 200, body: { ...REFRESH_OK, degraded: "One scan failed; the AI scanner list is unaffected." } },
        { status: 429, body: typed(429, "refresh_cooldown", "Chartink was refreshed a few minutes ago.", { retry_after_s: 420 }) },
      ],
    });
    await expect(page.getByTestId("chartink-refresh-live")).toHaveAttribute("aria-live", "polite");
    await page.getByTestId("chartink-refresh").click();
    const res = page.getByTestId("chartink-refresh-scan");
    await expect(res).toHaveCount(3);
    await expect(res.nth(0)).toHaveText("Volume Burst Sample: 5 hits in 2.4 s");
    await expect(res.nth(1)).toHaveText(`Gap Fill Sample: failed (${RATE})`);
    await expect(res.nth(1)).toHaveAttribute("data-ok", "false");
    await expect(res.nth(2)).toHaveText("Weak Close Sample: 1 hit in 1.8 s");
    await expect(page.getByTestId("chartink-refresh-result")).toContainText("2 of 3 scans ran, 1 failed");
    await expect(page.getByTestId("chartink-degraded")).toHaveText("One scan failed; the AI scanner list is unaffected.");
    expect(st.refreshes).toBe(1);

    await page.getByTestId("chartink-refresh").click();
    await expect(page.getByTestId("chartink-cooldown")).toHaveText("Chartink was refreshed a moment ago. Try again in 7 minutes.");
    expect(st.refreshes).toBe(2);
    await expect(page.getByTestId("chartink-refresh-result")).toHaveCount(0);
  });

  // ── CK-5 ─────────────────────────────────────────────────────────────

  test("CK-5 Disconnect asks first: keeping it sends nothing; removing it deletes the saved dashboard and the screen goes back to not connected", async ({ page }) => {
    const st = await open(page, SETTINGS);
    await page.getByTestId("chartink-disconnect").click();
    const dlg = page.getByRole("alertdialog");
    await expect(dlg).toContainText("removes the saved dashboard and its results");
    await page.getByTestId("chartink-disconnect-no").click();
    await expect(dlg).toHaveCount(0);
    expect(st.deletes).toBe(0);

    await page.getByTestId("chartink-disconnect").click();
    await page.getByTestId("chartink-disconnect-yes").click();
    await expect(page.getByTestId("chartink-not-connected")).toBeVisible();
    expect(st.deletes).toBe(1);
    await expect(page.getByTestId("chartink-scans")).toHaveCount(0);
  });

  // ── CK-6 ─────────────────────────────────────────────────────────────

  test("CK-6 honest states: the source failing offers Retry; Chartink unreachable on connect says nothing was saved; one scan failing is named; no hits is said; the hits failing keeps the table", async ({ page }) => {
    // The dashboard fails to load, then loads on Retry.
    const st1 = await open(page, SETTINGS, { source: { status: 500 } });
    await expect(page.getByTestId("chartink-error")).toContainText("Your Chartink dashboard didn’t load");
    await expect(page.getByRole("button", { name: /Retry/ })).toBeVisible();
    expect(st1.sourceCalls).toBe(1);
    await page.getByRole("button", { name: /Retry/ }).click();
    await expect.poll(() => st1.sourceCalls).toBe(2);
  });

  test("CK-6b Chartink unreachable while connecting (a 502) is said, not shown as a validation problem", async ({ page }) => {
    await open(page, SETTINGS, { source: null, put: [{ status: 502, body: typed(502, "chartink_unreachable", "Chartink could not be reached (HTTP 503)") }] });
    await page.getByTestId("chartink-url").fill(URL_OK);
    await page.getByTestId("chartink-connect-btn").click();
    await expect(page.getByTestId("chartink-connect-failure")).toContainText("Chartink could not be reached just now (Chartink could not be reached (HTTP 503)). Nothing was changed.");
    await expect(page.getByTestId("chartink-connect-problems")).toHaveCount(0);
  });

  test("CK-6c a scan that failed on the last fetch is named and the others are still used; a hit symbol the route could not recognise is listed", async ({ page }) => {
    const failedRun = { at: FETCHED, ok: false, hits: null, error: RATE, seconds: 20 };
    const source = sourceDoc(SCANS.map((x) => ((x as { id: string }).id === "1002" ? { ...x, last_run: failedRun } : x)));
    const hits = { ...HITS, scans: [HITS.scans[0], { ...HITS.scans[1], ok: false, hits: null, error: RATE }, HITS.scans[2]],
      unknown_symbols: [{ symbol: "CASHIETF", scans: [S1001], count: 1, close: 100, pct_change: 0, suggestions: [], note: "Not in the NSE stock symbol master (an ETF or fund unit, or a code from Chartink that is not a ticker)" }] };
    await open(page, SETTINGS, { source, hits });
    await expect(page.getByTestId("chartink-partial")).toHaveText(`1 of 3 scans failed on the last fetch: Gap Fill Sample (${RATE}). The others are used.`);
    await expect(row(page, "1002").getByTestId("ck-scan-fetched")).toContainText("Failed: http_429");
    await expect(row(page, "1002").getByTestId("ck-scan-hits")).toHaveText("—");
    await expect(row(page, "1001").getByTestId("ck-scan-hits")).toHaveText("5");
    // ETFs and fund units are listed, collapsed, as "not shown as stocks"; never as opportunity rows, never dropped silently.
    await expect(page.getByTestId("chartink-unknown-toggle")).toHaveText("Not shown as stocks (1)");
    await expect(page.getByTestId("chartink-unknown-row")).toBeHidden();
    await page.getByTestId("chartink-unknown-toggle").click();
    await expect(page.getByTestId("chartink-unknown-row")).toContainText("CASHIETF: Not in the NSE stock symbol master (an ETF or fund unit");
  });

  test("CK-6d no hits and a failing hits call: the table stays, and each says so", async ({ page }) => {
    const zero = sourceDoc(SCANS.map((x) => ((x as { last_run: unknown }).last_run ? { ...x, last_run: run(0) } : x)));
    await open(page, SETTINGS, { source: zero, hits: { ...HITS, scans: HITS.scans.map((s) => ({ ...s, hits: 0 })), symbols: [], empty_reason: "Every enabled scan returned no stocks on the last refresh." } });
    await expect(page.getByTestId("chartink-no-hits")).toHaveText("Every enabled scan returned no stocks on the last refresh.");
    await expect(row(page, "1001").getByTestId("ck-scan-hits")).toHaveText("0");

    const page2 = await page.context().newPage();
    await open(page2, SETTINGS, { hits: { status: 500 } });
    await expect(page2.getByTestId("chartink-hits-error")).toContainText("The latest hits didn’t load");
    await expect(page2.getByTestId("chartink-scans")).toBeVisible();
    await expect(row(page2, "1001").getByTestId("ck-scan-hits")).toHaveText("5"); // the table reads the saved last run, not the hits call
  });

  // ── CK-7 ─────────────────────────────────────────────────────────────

  test("CK-7 Overview (desktop): the AI row is tagged, a separated sub-list shows the first four Chartink-only stocks with icon, price, % change, scans and F&O, and each opens its chart", async ({ page }) => {
    await open(page, DESK);
    const card = page.getByTestId("desk-opps-card");
    // AI rows are unchanged, with the tag.
    await expect(card.getByTestId("desk-opp")).toHaveCount(1);
    await expect(card.getByTestId("desk-opp-symbol")).toHaveText("TESTBRK");
    await expect(card.getByTestId("desk-opp").getByTestId("ck-tag")).toHaveText("Also on Chartink: Volume Burst Sample (+1)");
    await expect(card.getByTestId("desk-opp").getByTestId("ck-tag")).toHaveAttribute("title", "Volume Burst Sample; Gap Fill Sample");

    // The sub-list: 4 of the 5 Chartink-only stocks, in the route's order.
    await expect(page.getByTestId("desk-ck-title")).toHaveText("From your Chartink scans (not in the AI scan)");
    const only = card.getByTestId("ck-only");
    await expect(only).toHaveCount(4);
    await expect(only.locator('[data-testid="ck-only-symbol"]')).toHaveText(["QUBEX", "ZEDCO", "WIDGETCO", "PLANETX"]);
    const q = only.nth(0);
    await expect(q.getByTestId("ck-only-price")).toContainText("1,250.50");
    await expect(q.getByTestId("ck-only-change")).toContainText("1.2");
    await expect(q.getByTestId("ck-only-scans")).toHaveText("Chartink: Volume Burst Sample, Weak Close Sample");
    await expect(q.getByTestId("ck-only-score")).toHaveText("No AI score");
    await expect(q.getByTestId("ck-fno")).toHaveCount(0);
    await expect(q.locator("img, svg, [data-testid*='icon']").first()).toBeVisible();
    await expect(only.nth(1).getByTestId("ck-fno")).toHaveText("F&O"); // ZEDCO
    await expect(only.nth(2).getByTestId("ck-fno")).toHaveCount(0); // WIDGETCO: F&O unknown, so no tag
    await expect(page.getByTestId("desk-ck-more")).toHaveText("1 more in AI Scanner · Chartink scans.");

    // The trust line: source, mode as returned, "Chartink fetched <time IST>", not validated.
    const trust = page.getByTestId("desk-ck-trust");
    await expect(trust).toContainText("Chartink scans (your dashboard)");
    await expect(trust).toContainText("Chartink fetched");
    await expect(trust).toContainText("10:30 IST");
    await expect(trust).toContainText("not validated");
    await expect(trust).toHaveAttribute("data-mode", "eod");
    await card.getByTestId("desk-ck-title").scrollIntoViewIfNeeded();
    await card.evaluate((el) => el.scrollIntoView({ block: "start" }));
    await shot(page, "overview", 1440);

    // A row opens its Chart tab; the header link opens the settings.
    await only.nth(1).click();
    await expect(page).toHaveURL(/tab=market&view=research/); // the Chart tab is Market Desk › Stock Research since 2026-10-27
    await expect(page).toHaveURL(/sym=ZEDCO/);
    await page.goto(DESK);
    await page.getByTestId("desk-opps-chartink").click();
    await expect(page).toHaveURL(/section=chartink/);
    await expect(page.getByTestId("chartink-settings")).toBeVisible();
  });

  // ── CK-8 ─────────────────────────────────────────────────────────────

  test("CK-8 not connected: one line with a way in, and the AI rows are as before; a failing source or failing hits degrades to the AI scanner with one line", async ({ page }) => {
    await open(page, DESK, { source: null });
    await expect(page.getByTestId("desk-opp")).toHaveCount(1);
    await expect(page.getByTestId("ck-tag")).toHaveCount(0);
    await expect(page.getByTestId("desk-ck-connect")).toHaveText("Connect your Chartink dashboard to add your scans here ›");
    await expect(page.getByTestId("ck-only")).toHaveCount(0);
    await page.getByTestId("ck-connect-link").click();
    await expect(page).toHaveURL(/section=chartink/);

    const p2 = await page.context().newPage();
    const st = await open(p2, DESK, { hits: { status: 500 } });
    await expect(p2.getByTestId("desk-opp")).toHaveCount(1);
    await expect(p2.getByTestId("desk-ck-degraded")).toContainText("Your Chartink scans didn’t load, so only the AI scanner is shown.");
    await expect(p2.getByTestId("ck-tag")).toHaveCount(0);
    await expect(p2.getByTestId("desk-opp-symbol")).toHaveText("TESTBRK");
    expect(st.hitsCalls).toBe(1);

    const p3 = await page.context().newPage();
    await open(p3, DESK, { source: { status: 500 } });
    await expect(p3.getByTestId("desk-opp")).toHaveCount(1);
    await expect(p3.getByTestId("desk-ck-degraded")).toBeVisible();
  });

  test("CK-8b stale hits show the route's note on the Overview and the settings; an unreadable AI scanner (in_ai_scanner null) claims no overlap", async ({ page }) => {
    const stale = "These hits are from 2026-10-14, 6 day(s) before today: refresh to update them.";
    await open(page, DESK, { hits: { ...HITS, is_today: false, age_days: 6, stale_note: stale } as typeof HITS });
    await expect(page.getByTestId("desk-ck-stale")).toHaveText(stale);
    await expect(page.getByTestId("desk-ck-trust")).toHaveAttribute("data-status", "stale");

    const p2 = await page.context().newPage();
    const unsure = { ...HITS, symbols: HITS.symbols.map((x) => ({ ...x, in_ai_scanner: null, ai_score: null })), source_failures: ["The AI scanner could not be read"] } as unknown as typeof HITS;
    await open(p2, DESK, { hits: unsure });
    await expect(p2.getByTestId("ck-tag").first()).toBeVisible();
    await expect(p2.getByTestId("ck-only")).toHaveCount(0);
    await expect(p2.getByTestId("desk-ck-unsure")).toContainText("The AI scanner could not be read, so these stocks are not compared with it: The AI scanner could not be read.");
    await open(await page.context().newPage(), SETTINGS, { hits: unsure }).then(() => undefined);
  });

  // ── CK-9 ─────────────────────────────────────────────────────────────

  test("CK-9 Overview (phone, 390px): the same tag and sub-list, with no sideways page scroll", async ({ page }) => {
    await open(page, DESK, {}, 390);
    const card = page.getByTestId("desk-top-opps");
    await expect(card.getByTestId("desk-top-opp")).toHaveCount(1);
    await expect(card.getByTestId("ck-tag")).toHaveText("Also on Chartink: Volume Burst Sample (+1)");
    await expect(page.getByTestId("desk-top-ck-title")).toHaveText("From your Chartink scans (not in the AI scan)");
    await expect(card.getByTestId("ck-only")).toHaveCount(4);
    await expect(card.getByTestId("ck-only").nth(0).getByTestId("ck-only-score")).toHaveText("No AI score");
    await expect(page.getByTestId("desk-top-ck-trust")).toContainText("Chartink fetched");
    await card.evaluate((el) => el.scrollIntoView({ block: "start" }));
    const s = await sideways(page);
    expect(s.doc).toBeLessThanOrEqual(0);
    expect(s.scroll).toBeLessThanOrEqual(0);
    await shot(page, "overview", 390);

    const p2 = await page.context().newPage();
    await open(p2, DESK, { source: null }, 390);
    await expect(p2.getByTestId("desk-top-ck-connect")).toContainText("Connect your Chartink dashboard to add your scans here");
  });

  // ── CK-10 ────────────────────────────────────────────────────────────

  test("CK-10 AI Scanner: the Chartink scans chip lists the five Chartink-only stocks, most scans first, with no AI score; All includes them; the AI row is tagged; the On Chartink filter and the URL keep it", async ({ page }) => {
    await open(page, `${DESK}?tab=scanner`);
    const chip = page.getByTestId("desk-scan-cat-chartink");
    await expect(chip).toHaveText("Chartink scans");
    await chip.click();
    await expect(page).toHaveURL(/sc_cat=chartink/);
    const rows = page.locator('[data-testid^="desk-scan-row-"]');
    await expect(rows).toHaveCount(5);
    // Most scans first (QUBEX has two), then the largest % change: PLANETX +3.1, ZEDCO +2.4, MOONCORP +1.0, WIDGETCO +0.5.
    await expect(rows.evaluateAll((els) => els.map((e) => e.getAttribute("data-testid")))).resolves.toEqual(
      ["QUBEX", "PLANETX", "ZEDCO", "MOONCORP", "WIDGETCO"].map((s) => `desk-scan-row-${s}`));
    const q = page.getByTestId("desk-scan-row-QUBEX");
    await expect(q.getByTestId("desk-scan-ck-scans")).toContainText("Volume Burst Sample, Weak Close Sample");
    await expect(q).toContainText("1,250.50");
    await expect(q.getByTestId("desk-scan-change")).toContainText("1.2"); // the hit's % change, no rupee change
    await expect(q.getByTestId("desk-scan-ck-noscore")).toHaveText("No AI score");
    await expect(page.getByTestId("desk-scan-odds")).toHaveCount(0); // no probability slot on these rows
    await expect(page.getByTestId("desk-scan-ck-rule")).toContainText("no AI score or probability");
    await expect(page.getByTestId("desk-scan-trust-ck")).toContainText("Chartink fetched");
    await shot(page, "scanner", 1440);

    // Reload keeps the category.
    await page.reload();
    await expect(page.getByTestId("desk-scan-cat-chartink")).toHaveAttribute("aria-pressed", "true");

    // All: the AI setup (tagged) plus the five Chartink-only stocks.
    await page.getByTestId("desk-scan-cat-all").click();
    await expect(rows).toHaveCount(6);
    await expect(page.getByTestId("desk-scan-row-TESTBRK").getByTestId("ck-tag")).toHaveText("Also on Chartink: Volume Burst Sample (+1)");

    // The filter: On Chartink = yes keeps the AI row and the five; no keeps neither's opposite.
    await page.goto(`${DESK}?tab=scanner&sc_ck=yes`);
    await expect(rows).toHaveCount(6);
    await expect(page.getByTestId("desk-scan-fchip-ck")).toContainText("On Chartink");
    await page.goto(`${DESK}?tab=scanner&sc_ck=no`);
    await expect(page.getByTestId("desk-scan-cat-empty")).toBeVisible();
    await page.getByTestId("desk-scan-filters-toggle").click();
    await expect(page.getByTestId("desk-scan-f-ck")).toHaveValue("no");
    await page.getByTestId("desk-scan-f-ck").selectOption("yes");
    await expect(page).toHaveURL(/sc_ck=yes/);
    await expect(rows).toHaveCount(6);
  });

  test("CK-10b the category without Chartink: not connected says how to connect; a failing source degrades the rest of the scanner with a note", async ({ page }) => {
    await open(page, `${DESK}?tab=scanner&sc_cat=chartink`, { source: null });
    await expect(page.getByTestId("desk-scan-ck-connect")).toContainText("Connect your Chartink dashboard to list your scans here");
    await page.getByTestId("desk-scan-filters-toggle").click();
    await expect(page.getByTestId("desk-scan-f-ck")).toBeDisabled();
    await expect(page.getByTestId("desk-scan-f-ck-why")).toContainText("connect your Chartink dashboard");

    const p2 = await page.context().newPage();
    await open(p2, `${DESK}?tab=scanner`, { hits: { status: 500 } });
    await expect(p2.getByTestId("desk-scan-ck-note")).toContainText("Your Chartink scans didn’t load, so the AI scanner is shown alone.");
    await expect(p2.getByTestId("desk-scan-row-TESTBRK")).toBeVisible();
    await p2.getByTestId("desk-scan-cat-chartink").click();
    await expect(p2.getByTestId("desk-scan-ck-error")).toContainText("Your Chartink scans didn’t load");
  });

  test("CK-10c the Scanner on a phone (390px): the Chartink chip scrolls into reach, the rows are cards, nothing scrolls sideways", async ({ page }) => {
    await open(page, `${DESK}?tab=scanner&sc_cat=chartink`, {}, 390);
    await expect(page.getByTestId("desk-scan-table")).toHaveAttribute("data-layout", "ck-cards");
    await expect(page.locator('[data-testid^="desk-scan-row-"]')).toHaveCount(5);
    await expect(page.getByTestId("desk-scan-row-QUBEX").getByTestId("desk-scan-ck-noscore")).toBeVisible();
    const s = await sideways(page);
    expect(s.doc).toBeLessThanOrEqual(0);
    expect(s.scroll).toBeLessThanOrEqual(0);
  });

  // ── CK-11 ────────────────────────────────────────────────────────────

  test("CK-11 ideas board: each card says AI scanner, Chartink or Both and names the Chartink scans; the switch sets include_chartink; Chartink-only follow the AI ones", async ({ page }) => {
    const st = await open(page, IDEAS);
    await expect(page.getByTestId("ideas-view")).toBeVisible();
    // The first run is the route's default (include when connected): no flag sent yet.
    expect(st.ideas[0]).toEqual({ limit: 8, include_combinations: true });

    await expect(page.getByTestId("idea-TESTBRK").getByTestId("idea-source")).toHaveAttribute("data-source", "both");
    await expect(page.getByTestId("idea-TESTBRK").getByTestId("idea-source")).toContainText("AI scanner + Chartink");
    await expect(page.getByTestId("idea-TESTBRK").getByTestId("idea-ck-scans")).toContainText("Volume Burst Sample, Gap Fill Sample");
    await expect(page.getByTestId("idea-AIONLY").getByTestId("idea-source")).toHaveText("AI scanner");
    await expect(page.getByTestId("idea-AIONLY").getByTestId("idea-ck-scans")).toHaveCount(0);
    const q = page.getByTestId("idea-QUBEX");
    await expect(q.getByTestId("idea-source")).toHaveText("Chartink");
    await expect(q.getByTestId("idea-ck-scans")).toContainText("Volume Burst Sample, Weak Close Sample");
    await expect(q.getByTestId("idea-score")).toHaveText("No AI score");
    await expect(q.getByTestId("idea-scan-status")).toHaveText("Chartink scan"); // the route's status is null, never "forming"
    await expect(q.getByTestId("idea-setup")).toContainText("Chartink scan (not an AI scanner setup)");
    await expect(page.getByTestId("ideas-ck-state")).toContainText("Chartink: 5 considered, 1 added, scan 19 Oct 2026 (up to 4).");
    await expect(q.getByTestId("idea-strat-cash:chartink_screen_signal").getByTestId("idea-strat-ck-note")).toHaveText("Rule-based levels; the scan is the user's Chartink scan, not validated.");
    // Order: the AI ideas first, then the Chartink-only one.
    await expect(page.locator('[data-testid^="idea-"][data-rank]')).toHaveCount(3);
    await expect(page.locator('[data-testid^="idea-"][data-rank]').evaluateAll((els) => els.map((e) => e.getAttribute("data-symbol")))).resolves.toEqual(["TESTBRK", "AIONLY", "QUBEX"]);
    await expect(page.getByTestId("ideas-ranking")).toContainText("Chartink-only ideas follow");
    await expect(page.getByTestId("ideas-ck-trust")).toContainText("Chartink scans (your dashboard)");
    await expect(page.getByTestId("ideas-ck-trust")).toContainText("not validated");

    const sw = page.getByRole("switch", { name: "Include my Chartink scans" });
    await expect(sw).toHaveAttribute("aria-checked", "true");
    await sw.click();
    await expect.poll(() => st.ideas.length).toBe(2);
    expect(st.ideas[1]).toEqual({ limit: 8, include_combinations: true, include_chartink: false });
    await expect(sw).toHaveAttribute("aria-checked", "false");
    await sw.click();
    await expect.poll(() => st.ideas.length).toBe(3);
    expect(st.ideas[2]).toEqual({ limit: 8, include_combinations: true, include_chartink: true });
    // "Build ideas again" carries the switch too.
    await sw.click();
    await expect.poll(() => st.ideas.length).toBe(4);
    await page.getByTestId("build-ideas").click();
    await expect.poll(() => st.ideas.length).toBe(5);
    expect(st.ideas[4]).toEqual({ limit: 8, include_combinations: true, include_chartink: false });
  });

  test("CK-11c when the Chartink part could not be used the ideas are the scanner's alone and the route's reason is shown", async ({ page }) => {
    const reason = "Your Chartink scans have not been refreshed yet: press Refresh now in More, Chartink scans.";
    await open(page, IDEAS, { ideasChartink: { ...SEL_CK, included: true, state: "not_refreshed", reason, added: 0, considered: 0 } });
    await expect(page.getByTestId("ideas-ck-state")).toHaveAttribute("data-state", "not_refreshed");
    await expect(page.getByTestId("ideas-ck-state")).toContainText(`Chartink scans are not in this board: ${reason} The ideas are the AI scanner's alone.`);
  });

  test("CK-11b without a Chartink dashboard the switch is absent and the request is exactly as before", async ({ page }) => {
    const st = await open(page, IDEAS, { source: null });
    await expect(page.getByTestId("ideas-view")).toBeVisible();
    await expect(page.getByTestId("ideas-in-chartink")).toHaveCount(0);
    await page.getByTestId("build-ideas").click();
    await expect.poll(() => st.ideas.length).toBe(2);
    expect(st.ideas[1]).toEqual({ limit: 8, include_combinations: true });
  });

  // ── CK-12 ────────────────────────────────────────────────────────────

  test("CK-12 plan: the chartink_scans evidence item is in the ledger like any other, and a chartink_screen_signal candidate is labelled rule-based, not validated", async ({ page }) => {
    const plan = planFixture("all");
    const base = plan.candidates.find((c: { id: string }) => c.id === "cash:breakout_continuation");
    plan.candidates.push({ ...JSON.parse(JSON.stringify(base)), id: "cash:chartink_screen_signal", family: "chartink_screen_signal", label: "Chartink scan signal (long)" });
    plan.evidence.push({ group: "technical", key: "chartink_scans", value: { scans: ["Volume Burst Sample"], count: 1 }, interpretation: "Listed by your Chartink scan Volume Burst Sample. It is your own rule, not a validated signal.", direction: "supports", source: "Chartink scans (your dashboard)", source_as_of: "2026-10-20", version: null });
    plan.evidence_summary.technical.supports += 1;
    await page.setViewportSize({ width: 1440, height: 900 });
    await setup(page);
    await page.route("**/api/desk/strategy/plan", (r) => json(r, plan));
    await page.goto(`${IDEAS}&mode=stock&sym=TESTBRK&direction=bullish&instrument=cash&build=1&cand=cash:chartink_screen_signal`);
    await expect(page.getByTestId("candidate")).toHaveAttribute("data-id", "cash:chartink_screen_signal");
    await expect(page.getByTestId("cand-chartink-note")).toHaveText("Rule-based levels; the scan is the user's Chartink scan, not validated.");
    await page.getByTestId("ev-group-technical-toggle").click();
    const item = page.getByTestId("ev-technical-chartink_scans");
    await expect(item).toBeVisible();
    await expect(item.getByTestId("ev-direction")).toContainText("Supports");
    await expect(item.getByTestId("ev-interpretation")).toContainText("your own rule, not a validated signal");
    await expect(item.getByTestId("ev-source")).toContainText("Chartink scans (your dashboard) · as of 20 Oct 2026");
  });

  // ── CK-13 ────────────────────────────────────────────────────────────

  test("CK-13 persona: the investor wording on the settings view and the direction select; the trader wording by default", async ({ page }) => {
    await open(page, SETTINGS);
    await expect(page.getByTestId("chartink-title")).toContainText("Chartink scans");
    await expect(row(page, "1001").getByTestId("ck-scan-direction").locator("option:checked")).toHaveText("Bullish");
    await page.goto(`${SETTINGS}&persona=investor`);
    await expect(page.getByTestId("chartink-settings")).toHaveAttribute("data-persona", "investor");
    await expect(page.getByTestId("chartink-title")).toContainText("Add your Chartink ideas to the desk");
    await expect(row(page, "1001").getByTestId("ck-scan-direction").locator("option:checked")).toHaveText("Expect it to rise");
    await expect(row(page, "1005").getByTestId("ck-scan-direction").locator("option:checked")).toHaveText("Expect it to fall");
  });

  // ── CK-14 ────────────────────────────────────────────────────────────

  test("CK-14 settings at 390px: the table scrolls inside its own box, the page does not scroll sideways, and More lists the view", async ({ page }) => {
    await open(page, SETTINGS, {}, 390);
    await expect(page.getByTestId("chartink-scans")).toBeVisible();
    const region = page.getByRole("region", { name: /Your Chartink scans/ });
    await expect(region).toBeVisible();
    const inner = await region.evaluate((el) => ({ scroll: el.scrollWidth, client: el.clientWidth }));
    expect(inner.scroll).toBeGreaterThan(inner.client);
    const s = await sideways(page);
    expect(s.doc).toBeLessThanOrEqual(0);
    expect(s.scroll).toBeLessThanOrEqual(0);
    await shot(page, "settings", 390);

    // Desk redesign (2026-10-27): no More list; the old URL opens Market Desk › Screener's "Chartink sources".
    const p2 = await page.context().newPage();
    await open(p2, `${DESK}?tab=more&view=chartink`, {});
    await expect(p2).toHaveURL(/section=chartink/);
    await expect(p2.getByTestId("chartink-settings")).toBeVisible();
  });

  test("CK-16 a dashboard the size of a real one: 14 stock scans (7 with intraday candles), 3 widgets, 172 stocks of which 15 are also in the AI scan, a 13.5 s refresh, then the cooldown", async ({ page }) => {
    // MOCK, invented names, real shapes. Hits per scan, summed by hand: 0+3+5+7+12+18+24+31+40+52+61+70+80+86 = 489.
    const HITS_PER = [0, 3, 5, 7, 12, 18, 24, 31, 40, 52, 61, 70, 80, 86];
    expect(HITS_PER.reduce((a, b) => a + b, 0)).toBe(489);
    const stock = HITS_PER.map((h, i) => scan({ id: String(2000 + i), name: `Invented Scan ${String(i + 1).padStart(2, "0")}`, description: `Invented scan number ${i + 1}`, uses_intraday_candles: i % 2 === 0, last_run: run(h), direction: i % 3 === 0 ? "bearish" : "bullish" }));
    const widgets = [1, 2, 3].map((i) => scan({ id: String(3000 + i), name: `Invented Widget ${i}`, kind: "market_stats", supported: false, unsupported_reason: "Market statistics, not a stock list", enabled: false, direction: "neutral" }));
    const doc = sourceDoc([...stock, ...widgets]);
    const symbols = Array.from({ length: 172 }, (_, i) => hit({ symbol: `STK${String(i + 1).padStart(3, "0")}`, name: `Invented Stock ${i + 1}`, scans: [sc("2001", "Invented Scan 02", "bullish")], count: 1, close: 100 + i, pct_change: 0.1, in_ai_scanner: i < 15, ai_score: i < 15 ? 60 : null, fno_eligible: false }));
    const hits = { ...HITS, scans: stock.map((x, i) => ({ id: (x as { id: string }).id, name: (x as { name: string }).name, direction: "bullish", hits: HITS_PER[i], ok: true, error: null, uses_intraday_candles: i % 2 === 0 })), symbols,
      unknown_symbols: ["CASHIETF", "LIQUIDPLUS"].map((sym) => ({ symbol: sym, scans: [], count: 1, close: 10, pct_change: 0, suggestions: [], note: "Not in the NSE stock symbol master (an ETF or fund unit, or a code from Chartink that is not a ticker)" })) };
    const refreshBody = { ...REFRESH_OK, ok_count: 14, failed_count: 0, scans: stock.map((x, i) => ({ id: (x as { id: string }).id, name: (x as { name: string }).name, direction: "bullish", ok: true, hits: HITS_PER[i], error: null, error_code: null, seconds: i === 0 ? 13.5 : 1.2 })) };
    await open(page, SETTINGS, { source: doc, hits, refresh: [{ status: 200, body: refreshBody }, { status: 429, body: typed(429, "refresh_cooldown", "Wait.", { retry_after_s: 540 }) }] });
    await expect(page.locator('[data-testid^="ck-scan-"][data-kind]')).toHaveCount(17);
    await expect(page.locator('[data-testid="ck-scan-intraday"]')).toHaveCount(7);
    await expect(page.locator('[data-testid^="ck-scan-"][data-kind="market_stats"]')).toHaveCount(3);
    await expect(page.locator('[data-testid^="ck-scan-"][data-kind="market_stats"] [data-testid="ck-scan-enabled"]:disabled')).toHaveCount(3);
    await expect(row(page, "2013").getByTestId("ck-scan-hits")).toHaveText("86");
    await expect(row(page, "2000").getByTestId("ck-scan-hits")).toHaveText("0");
    await expect(page.getByTestId("chartink-hit-summary")).toHaveText("172 stocks across your enabled scans; 15 also in the AI scan, 157 not.");
    await expect(page.getByTestId("chartink-unknown-toggle")).toHaveText("Not shown as stocks (2)");
    await page.getByTestId("chartink-refresh").click();
    await expect(page.getByTestId("chartink-refresh-scan").first()).toHaveText("Invented Scan 01: 0 hits in 13.5 s");
    await expect(page.getByTestId("chartink-refresh-result")).toContainText("14 of 14 scans ran");
    await page.getByTestId("chartink-refresh").click();
    await expect(page.getByTestId("chartink-cooldown")).toHaveText("Chartink was refreshed a moment ago. Try again in 9 minutes.");
    // The Overview takes the first four of the 157 and says how many more.
    await page.goto(DESK);
    await expect(page.getByTestId("ck-only")).toHaveCount(4);
    await expect(page.getByTestId("desk-ck-more")).toHaveText("153 more in AI Scanner · Chartink scans.");
    await expect(page.getByTestId("desk-ck-unknown")).toContainText("2 codes from your scans are not shown as stocks");
  });

  // ── CK-15 ────────────────────────────────────────────────────────────

  test("CK-15 only the Chartink routes are written; nothing places an order", async ({ page }) => {
    const st = await open(page, SETTINGS);
    await row(page, "1005").getByTestId("ck-scan-enabled").click();
    await page.getByTestId("chartink-refresh").click();
    await expect(page.getByTestId("chartink-refresh-result")).toBeVisible();
    expect(st.writes).toEqual([]);
    await expect(page.getByRole("button", { name: /buy|sell|place order/i })).toHaveCount(0);
  });
});
