/**
 * One-screen Copilot app (/v5/app) — Smart trading desk, Market Desk › Scan Builder (screens/tradingdesk/tabs/market-desk/
 * scan-builder/; contract docs/scan_builder/DESIGN.md). Cases TC-E1 … TC-E8 of test_reports/scan_builder_20261103_0431.md.
 *
 * MOCK — not real data. Every /api/scan-builder answer below is hand-written to the contract (DESIGN.md §4): the catalog, the
 * run results (three invented stocks with invented prices) and an in-memory scan store. Nothing here is market data; the
 * expected text is worked out from these fixtures, not copied from the screen. Production build, every /api mocked — see
 * pw.copilot-app.config.ts.
 */
import { test, expect, type Page, type Route } from "@playwright/test";
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";
import { mockApi, mockSingleRoute } from "../helpers/api-mock";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const load = (name: string) => JSON.parse(fs.readFileSync(path.join(__dirname, "..", "fixtures", name), "utf-8"));

const DESK = "/v5/app/trader/desk";
const SB = `${DESK}?tab=market&view=scanbuilder`;
const INTEL = `${DESK}?tab=market&view=intel`;
const SLOW = { timeout: 15_000 };
const reply = (route: Route, body: unknown, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });

// ── MOCK — not real data: the catalog ────────────────────────────────────────────────────────────────────────────────

const close = (offset = 0) => ({ kind: "measure", tf: "1d", offset, measure: "close", params: {} });
const DEFAULT_SPEC = {
  version: 1, name: "New scan", description: "",
  filters: { id: "g_root", kind: "group", join: "all", universe: "cash", enabled: true, comment: "", children: [] },
  columns: [
    { id: "c_chg", alias: "% Change", enabled: true, format: "pct", expr: { terms: [{ op: null, operand: close() }, { op: "-", operand: close(1) }, { op: "/", operand: close(1) }, { op: "*", operand: { kind: "number", value: 100 } }] } },
    { id: "c_price", alias: "Price", enabled: true, format: "price", expr: { terms: [{ op: null, operand: close() }] } },
    { id: "c_vol", alias: "Volume", enabled: true, format: "volume", expr: { terms: [{ op: null, operand: { kind: "measure", tf: "1d", offset: 0, measure: "volume", params: {} } }] } },
  ],
  sort: { column: "c_chg", dir: "desc" },
  limit: 50,
};
const TEMPLATE_SPEC = {
  ...DEFAULT_SPEC, name: "RSI above 50 — daily and weekly",
  filters: {
    ...DEFAULT_SPEC.filters,
    children: [
      { id: "f_d", kind: "filter", enabled: true, comment: "", op: "gt", left: { terms: [{ op: null, operand: { kind: "measure", tf: "1d", offset: 0, measure: "rsi", params: { period: 14 } } }] }, right: { terms: [{ op: null, operand: { kind: "number", value: 50 } }] } },
      { id: "f_w", kind: "filter", enabled: true, comment: "", op: "gt", left: { terms: [{ op: null, operand: { kind: "measure", tf: "1w", offset: 0, measure: "rsi", params: { period: 14 } } }] }, right: { terms: [{ op: null, operand: { kind: "number", value: 50 } }] } },
    ],
  },
};
const P = (name: string, type: string, def: number | string, min?: number, max?: number) => ({ name, type, default: def, min: min ?? null, max: max ?? null });
const CATALOG = {
  measures: [
    { key: "open", label: "Open", group: "Price", params: [] },
    { key: "high", label: "High", group: "Price", params: [] },
    { key: "low", label: "Low", group: "Price", params: [] },
    { key: "close", label: "Close", group: "Price", params: [] },
    { key: "volume", label: "Volume", group: "Price", params: [] },
    { key: "sma", label: "SMA", group: "Moving averages", params: [P("source", "source", "close"), P("period", "int", 20, 1, 500)] },
    { key: "ema", label: "EMA", group: "Moving averages", params: [P("source", "source", "close"), P("period", "int", 20, 1, 500)] },
    { key: "rsi", label: "RSI", group: "Momentum", params: [P("period", "int", 14, 2, 100)] },
    { key: "supertrend", label: "Supertrend", group: "Trend", params: [P("period", "int", 7, 1, 100), P("multiplier", "float", 3, 0.1, 10)] },
  ],
  fundamentals: [{ key: "pe_ttm", label: "PE (TTM)", unit: "x" }, { key: "market_cap_cr", label: "Market cap (₹ cr)", unit: "₹ cr" }],
  operators: [
    { key: "gt", label: "Greater than" }, { key: "gte", label: "Greater than equal to" }, { key: "lt", label: "Less than" }, { key: "lte", label: "Less than equal to" },
    { key: "eq", label: "Equals" }, { key: "crosses_above", label: "Crossed above" }, { key: "crosses_below", label: "Crossed below" },
  ],
  universes: [{ key: "cash", label: "All NSE stocks", size: 2712 }, { key: "fno", label: "F&O stocks", size: 218 }, { key: "nifty50", label: "Nifty 50", size: 50 }],
  timeframes: [
    { key: "1d", label: "Daily", available: true }, { key: "1w", label: "Weekly", available: true }, { key: "1M", label: "Monthly", available: true },
    { key: "5m", label: "5 minute", available: false, reason: "Intraday candles are the next step" },
    { key: "15m", label: "15 minute", available: false, reason: "Intraday candles are the next step" },
    { key: "1h", label: "1 hour", available: false, reason: "Intraday candles are the next step" },
  ],
  templates: [{ key: "rsi_dw", name: "RSI above 50 — daily and weekly", description: "Daily and weekly RSI(14) both above 50", spec: TEMPLATE_SPEC }],
  refresh_seconds: 10,
  default_spec: DEFAULT_SPEC,
};

// ── MOCK — not real data: a run result (three invented stocks) ───────────────────────────────────────────────────────

const BASIS_TEXT = "MOCK basis: Kite live at 10:15:32 IST over NSE end-of-day bars to 31 Oct 2026 (split/bonus adjusted).";
function runResult(o: { open?: boolean; bump?: number; nodes?: Record<string, { passed: number; unknown: number }> } = {}) {
  const b = o.bump ?? 0;
  return {
    ok: true, run_at: "2026-11-03T04:45:32Z", elapsed_ms: 231,
    basis: { mode: o.open === false ? "kite_close" : "live", day: "2026-11-03", eod_date: "2026-10-31", quote_as_of: "2026-11-03T04:45:30Z", text: BASIS_TEXT },
    sources: { prices: "NSE end-of-day, split/bonus adjusted (MOCK)", today: "Kite live (MOCK)", fundamentals: "NIDP feature store (MOCK)" },
    market: { open: o.open !== false, refresh_seconds: 10 },
    universe: { key: "cash", label: "All NSE stocks", size: 2712 },
    counts: { universe: 2712, evaluated: 2700, matched: 3, shown: 3, no_today_bar: 12, no_history: 120 },
    columns: [{ id: "c_chg", alias: "% Change", format: "pct" }, { id: "c_price", alias: "Price", format: "price" }, { id: "c_vol", alias: "Volume", format: "volume" }],
    rows: [
      { symbol: "ALPHA", name: "Alpha Industries (MOCK)", values: [4.2 + b, 812.5 + b, 3_250_000], today: "live" },
      { symbol: "BETA", name: "Beta Motors (MOCK)", values: [2.35, 1999.95, 845_000], today: "live" },
      { symbol: "GAMMA", name: "Gamma Labs (MOCK)", values: [-0.5, 95.1, null], today: "live" },
    ],
    nodes: o.nodes ?? {},
    warnings: ["MOCK warning: 12 stocks had no live quote and were left out."],
  };
}

// ── the mocked desk ──────────────────────────────────────────────────────────────────────────────────────────────────

type Saved = { id: string; spec: any; created_at: string; updated_at: string };
interface Backend {
  runs: any[];
  saves: Array<{ method: string; url: string; body: any }>;
  scans: Saved[];
  sbCalls: string[];
  runAnswer: (n: number) => { status: number; body: unknown };
}

async function desk(page: Page, o: { flag?: boolean; runAnswer?: Backend["runAnswer"]; scans?: Saved[] } = {}): Promise<Backend> {
  const be: Backend = { runs: [], saves: [], scans: o.scans ?? [], sbCalls: [], runAnswer: o.runAnswer ?? (() => ({ status: 200, body: runResult() })) };
  await mockApi(page, "populated");
  await mockSingleRoute(page, "**/api/markets/home", "markets-home.json");
  await page.route("**/api/chat/sessions", (r) => reply(r, []));
  await page.route("**/api/move-odds/**", (r) => reply(r, { detail: "feature_not_enabled" }, 403));
  const base = load("user-profile-onboarded.json");
  await page.route("**/api/auth/me", (r) => reply(r, { ...base, features: { ...(base.features ?? {}), scan_builder: o.flag !== false } }));
  let next = 1;
  await page.route(/\/api\/scan-builder\//, async (r) => {
    const req = r.request();
    const url = new URL(req.url());
    const p = url.pathname.replace(/^.*\/api\/scan-builder/, "");
    be.sbCalls.push(`${req.method()} ${p}`);
    if (p === "/catalog") return reply(r, CATALOG);
    if (p === "/run") {
      be.runs.push(req.postDataJSON());
      const a = be.runAnswer(be.runs.length);
      return reply(r, a.body, a.status);
    }
    if (p === "/scans" && req.method() === "GET") {
      return reply(r, { scans: [...be.scans].reverse().map((s) => ({ id: s.id, name: s.spec.name, description: s.spec.description, created_at: s.created_at, updated_at: s.updated_at })) });
    }
    if (p === "/scans" && req.method() === "POST") {
      const body = req.postDataJSON();
      be.saves.push({ method: "POST", url: p, body });
      const s = { id: `s${next++}`, spec: body.spec, created_at: "2026-11-03T04:40:00Z", updated_at: "2026-11-03T04:40:00Z" };
      be.scans.push(s);
      return reply(r, { scan: s });
    }
    const m = p.match(/^\/scans\/([^/]+)(\/copy)?$/);
    if (m) {
      const s = be.scans.find((x) => x.id === m[1]);
      if (!s) return reply(r, { detail: { code: "scan_not_found", message: "No such scan." } }, 404);
      if (m[2] && req.method() === "POST") {
        be.saves.push({ method: "POST", url: p, body: null });
        const c = { id: `s${next++}`, spec: { ...s.spec, name: `Copy of ${s.spec.name}` }, created_at: "2026-11-03T04:41:00Z", updated_at: "2026-11-03T04:41:00Z" };
        be.scans.push(c);
        return reply(r, { scan: c });
      }
      if (req.method() === "GET") return reply(r, { scan: s });
      if (req.method() === "PUT") {
        const body = req.postDataJSON();
        be.saves.push({ method: "PUT", url: p, body });
        s.spec = body.spec;
        s.updated_at = "2026-11-03T04:42:00Z";
        return reply(r, { scan: s });
      }
      if (req.method() === "DELETE") {
        be.saves.push({ method: "DELETE", url: p, body: null });
        be.scans = be.scans.filter((x) => x.id !== s.id);
        return reply(r, { ok: true });
      }
    }
    return reply(r, { detail: { code: "unexpected", message: `unmocked ${req.method()} ${p}` } }, 500);
  });
  return be;
}

const panel = (page: Page) => page.getByTestId("desk-panel-scanbuilder");

async function openBuilder(page: Page) {
  await page.goto(SB);
  await expect(panel(page).getByTestId("scan-builder")).toBeVisible(SLOW);
}

test.describe("MOCK — not real data: Market Desk › Scan Builder", () => {
  test("TC-E1a with the flag off the view is not offered, and its URL asks the scan builder nothing", async ({ page }) => {
    const be = await desk(page, { flag: false });
    await page.goto(INTEL);
    await expect(page.getByTestId("desk-view-intel")).toBeVisible(SLOW);
    await expect(page.getByTestId("desk-view-scanbuilder")).toHaveCount(0);
    await page.goto(SB);
    await expect(page.getByTestId("sb-off")).toContainText("not enabled for your account", SLOW);
    await expect(page.getByTestId("scan-builder")).toHaveCount(0);
    expect(be.sbCalls).toEqual([]);
  });

  test("TC-E1b with the flag on the view is offered last, opens from the switcher, and reads the catalog", async ({ page }) => {
    const be = await desk(page);
    await page.goto(INTEL);
    await expect(page.getByTestId("desk-view-scanbuilder")).toBeVisible(SLOW);
    const keys = await page.getByTestId("desk-views").locator("button").evaluateAll((els) => els.map((e) => e.getAttribute("data-testid")));
    expect(keys).toEqual(["desk-view-intel", "desk-view-smartmoney", "desk-view-sectors", "desk-view-research", "desk-view-screener", "desk-view-scanbuilder"]);
    await expect(page.getByTestId("desk-view-scanbuilder")).toHaveText("Scan Builder");
    await page.getByTestId("desk-view-scanbuilder").click();
    await expect(page).toHaveURL(/[?&]view=scanbuilder(&|$)/);
    await expect(page.getByTestId("md-eyebrow")).toHaveText("Market Desk · Scan Builder");
    await expect(panel(page).getByTestId("scan-builder")).toBeVisible(SLOW);
    expect(be.sbCalls).toContain("GET /catalog");
    expect(be.sbCalls.filter((c) => c.startsWith("POST /run"))).toEqual([]);   // nothing runs until Run is pressed
  });

  test("TC-E2 + TC-E4 build a scan (filter, operation, toggle, duplicate, delete, an 'any' sub-group), save, change, copy, cancel", async ({ page }) => {
    const be = await desk(page);
    await openBuilder(page);
    // Columns: the default three
    await page.getByTestId("sb-rail-columns").click();
    await expect(page.getByTestId("sb-column-row")).toHaveCount(3);
    await expect(page.getByTestId("sb-alias").nth(0)).toHaveValue("% Change");
    await expect(page.getByTestId("sb-alias").nth(1)).toHaveValue("Price");
    await expect(page.getByTestId("sb-alias").nth(2)).toHaveValue("Volume");
    // Filters: the sentence and the segment
    await page.getByTestId("sb-rail-filters").click();
    const root = page.getByTestId("sb-group-root");
    await expect(root).toContainText("Stock passes");
    await expect(root).toContainText("segment:");
    await expect(root.getByTestId("sb-universe").first()).toHaveValue("cash");
    await expect(root.getByTestId("sb-universe").first().locator("option:checked")).toHaveText("All NSE stocks (2,712)");
    await expect(page.getByTestId("sb-group-empty")).toBeVisible();
    // + filter, then RSI(14) Greater than Number 55
    await page.getByTestId("sb-add-filter").first().click();
    const row = page.getByTestId("sb-filter-row");
    await expect(row).toHaveCount(1);
    await row.getByTestId("sb-measure-left-0").click();
    await page.getByTestId("sb-picker-search").fill("rsi");
    await expect(page.getByTestId("sb-picker-item-close")).toHaveCount(0);
    await page.getByTestId("sb-picker-item-rsi").click();
    await expect(row.getByTestId("sb-measure-left-0")).toHaveText("RSI");
    await expect(row.getByTestId("sb-param-period")).toHaveValue("14");
    await row.getByTestId("sb-op").selectOption("gt");
    await row.getByTestId("sb-number").fill("55");
    // an operation on the right side: × 2, then removed again
    await row.getByTestId("sb-filter-term").click();
    await expect(row.getByTestId("sb-arith")).toHaveCount(1);
    await row.getByTestId("sb-term-remove").click();
    await expect(row.getByTestId("sb-arith")).toHaveCount(0);
    // on/off
    const sw = row.getByTestId("sb-filter-toggle");
    await expect(sw).toHaveAttribute("aria-checked", "true");
    await sw.click();
    await expect(sw).toHaveAttribute("aria-checked", "false");
    await sw.click();
    await expect(sw).toHaveAttribute("aria-checked", "true");
    // duplicate, then delete the copy
    await row.first().getByTestId("sb-filter-duplicate").click();
    await expect(page.getByTestId("sb-filter-row")).toHaveCount(2);
    await page.getByTestId("sb-filter-row").nth(1).getByTestId("sb-filter-delete").click();
    await expect(page.getByTestId("sb-filter-row")).toHaveCount(1);
    // + group: an "any" group with one filter of its own
    await page.getByTestId("sb-add-group").first().click();
    const sub = page.getByTestId("sb-group");
    await expect(sub).toHaveCount(1);
    await expect(sub.getByTestId("sb-join")).toHaveValue("any");
    await expect(sub.getByTestId("sb-universe")).toHaveValue("");
    await sub.getByTestId("sb-add-filter").click();
    await expect(page.getByTestId("sb-filter-row")).toHaveCount(2);
    // name it and save (POST)
    await page.getByTestId("sb-name").fill("My RSI scan");
    await page.getByTestId("sb-save").click();
    await expect(page).toHaveURL(/[?&]scan=s1(&|$)/, SLOW);
    expect(be.saves.map((s) => `${s.method} ${s.url}`)).toEqual(["POST /scans"]);
    const saved = be.saves[0].body.spec;
    expect(saved.name).toBe("My RSI scan");
    expect(saved.filters.universe).toBe("cash");
    expect(saved.filters.children).toHaveLength(2);
    const f0 = saved.filters.children[0];
    expect(f0.kind).toBe("filter");
    expect(f0.left.terms).toEqual([{ op: null, operand: { kind: "measure", tf: "1d", offset: 0, measure: "rsi", params: { period: 14 } } }]);
    expect(f0.op).toBe("gt");
    expect(f0.right.terms).toEqual([{ op: null, operand: { kind: "number", value: 55 } }]);
    expect(f0.enabled).toBe(true);
    const g1 = saved.filters.children[1];
    expect(g1).toMatchObject({ kind: "group", join: "any", universe: null, enabled: true });
    expect(g1.children).toHaveLength(1);
    expect(new Set([saved.filters.id, f0.id, g1.id, g1.children[0].id]).size).toBe(4);
    await expect(page.getByTestId("sb-scan-s1")).toHaveText("My RSI scan");
    await expect(page.getByTestId("sb-dirty")).toHaveCount(0);
    // change and save again (PUT)
    await page.getByTestId("sb-name").fill("My RSI scan v2");
    await expect(page.getByTestId("sb-dirty")).toBeVisible();
    await page.getByTestId("sb-save").click();
    await expect(page.getByTestId("sb-dirty")).toHaveCount(0, SLOW);
    expect(be.saves[1].method).toBe("PUT");
    expect(be.saves[1].url).toBe("/scans/s1");
    expect(be.saves[1].body.spec.name).toBe("My RSI scan v2");
    // Cancel discards unsaved edits
    await page.getByTestId("sb-name").fill("throwaway name");
    await page.getByTestId("sb-cancel").click();
    await expect(page.getByTestId("sb-name")).toHaveValue("My RSI scan v2");
    await expect(page.getByTestId("sb-dirty")).toHaveCount(0);
    // Copy (nothing unsaved) → the copy endpoint, then the copy is open
    await page.getByTestId("sb-copy").click();
    await expect(page).toHaveURL(/[?&]scan=s2(&|$)/, SLOW);
    expect(be.saves[2]).toEqual({ method: "POST", url: "/scans/s1/copy", body: null });
    await expect(page.getByTestId("sb-name")).toHaveValue("Copy of My RSI scan v2");
  });

  test("TC-E4b ?scan=<id> opens that saved scan; deleting it from the list asks first, then starts a new scan", async ({ page }) => {
    const be = await desk(page, { scans: [{ id: "s9", spec: TEMPLATE_SPEC, created_at: "2026-11-02T10:00:00Z", updated_at: "2026-11-02T10:00:00Z" }] });
    await page.goto(`${SB}&scan=s9`);
    await expect(page.getByTestId("sb-name")).toHaveValue("RSI above 50 — daily and weekly", SLOW);
    await expect(page.getByTestId("sb-filter-row")).toHaveCount(2);
    await expect(page.getByTestId("sb-scan-s9")).toHaveAttribute("aria-current", "true");
    expect(be.sbCalls).toContain("GET /scans/s9");
    await page.getByTestId("sb-delete-s9").click();
    expect(be.saves).toEqual([]);                                                // nothing deleted until confirmed
    await page.getByTestId("sb-delete-confirm-s9").click();
    await expect(page.getByTestId("sb-list-empty")).toBeVisible(SLOW);
    expect(be.saves).toEqual([{ method: "DELETE", url: "/scans/s9", body: null }]);
    await expect(page.getByTestId("sb-name")).toHaveValue("New scan");
    await expect(page).not.toHaveURL(/[?&]scan=/);
  });

  test("TC-E3 Run sends the scan, shows the result, where it came from, the counts, and sorts by a column", async ({ page }) => {
    const be = await desk(page, { runAnswer: () => ({ status: 200, body: runResult({ nodes: { g_root: { passed: 3, unknown: 0 } } }) }) });
    await openBuilder(page);
    await page.getByTestId("sb-name").fill("Everything");
    await page.getByTestId("sb-run").click();
    await expect(page.getByTestId("sb-result-table")).toBeVisible(SLOW);
    expect(be.runs).toHaveLength(1);
    expect(be.runs[0].spec.name).toBe("Everything");
    expect(be.runs[0].spec.columns.map((c: any) => c.alias)).toEqual(["% Change", "Price", "Volume"]);
    await expect(page.getByTestId("sb-tab-result")).toHaveAttribute("aria-selected", "true");
    await expect(page.getByTestId("sb-basis")).toHaveText(BASIS_TEXT);
    await expect(page.getByTestId("sb-counts")).toContainText("All NSE stocks: 2,712 · evaluated 2,700 · matched 3");
    await expect(page.getByTestId("sb-counts")).toContainText("left out: 12 without today’s candle, 120 without enough data to decide");
    await expect(page.getByTestId("sb-warnings")).toContainText("12 stocks had no live quote");
    const rows = page.getByTestId("sb-result-row");
    await expect(rows).toHaveCount(3);
    // the server's order first (ALPHA, BETA, GAMMA), formatted: % signed with 2 digits, price with 2 decimals, volume in lakh / crore
    await expect(rows.nth(0)).toContainText("ALPHA");
    await expect(rows.nth(0)).toContainText("+4.20%");
    await expect(rows.nth(0)).toContainText("812.50");
    await expect(rows.nth(0)).toContainText("32.50 L");
    await expect(rows.nth(1)).toContainText("1,999.95");
    await expect(rows.nth(2)).toContainText("−0.50%");
    await expect(rows.nth(2)).toContainText("—");
    // sort by Price: descending, then ascending
    await page.getByTestId("sb-sort-c_price").click();
    await expect(page.locator("th", { has: page.getByTestId("sb-sort-c_price") })).toHaveAttribute("aria-sort", "descending");
    await expect(rows.nth(0)).toHaveAttribute("data-symbol", "BETA");
    await page.getByTestId("sb-sort-c_price").click();
    await expect(page.locator("th", { has: page.getByTestId("sb-sort-c_price") })).toHaveAttribute("aria-sort", "ascending");
    await expect(rows.nth(0)).toHaveAttribute("data-symbol", "GAMMA");
    // Volume ascending: the missing value stays last
    await page.getByTestId("sb-sort-c_vol").click();
    await page.getByTestId("sb-sort-c_vol").click();
    await expect(rows.nth(0)).toHaveAttribute("data-symbol", "BETA");
    await expect(rows.nth(2)).toHaveAttribute("data-symbol", "GAMMA");
    // the debug count on the root group, back on Design
    await page.getByTestId("sb-tab-design").click();
    await expect(page.getByTestId("sb-root-debug")).toContainText("3");
  });

  test("TC-E5 while the market is open the Result re-runs every 10 s; it pauses when the tab is hidden and resumes when shown", async ({ page }) => {
    await page.clock.install({ time: new Date("2026-11-03T04:45:00Z") });
    const be = await desk(page, { runAnswer: (n) => ({ status: 200, body: runResult({ bump: n }) }) });
    await openBuilder(page);
    await page.getByTestId("sb-run").click();
    await expect(page.getByTestId("sb-result-table")).toBeVisible(SLOW);
    expect(be.runs).toHaveLength(1);
    await expect(page.getByTestId("sb-live-chip")).toHaveAttribute("data-state", "live");
    await expect(page.getByTestId("sb-live-chip")).toContainText("refreshes every 10 s");
    await page.clock.runFor(10_500);
    await expect.poll(() => be.runs.length, SLOW).toBe(2);
    await expect(page.getByTestId("sb-result-row").nth(0)).toContainText("814.50", SLOW);   // 812.5 + bump 2: the refreshed answer is shown
    await page.clock.runFor(10_500);
    await expect.poll(() => be.runs.length, SLOW).toBe(3);
    // hide the tab: no more runs
    await page.evaluate(() => {
      Object.defineProperty(document, "visibilityState", { configurable: true, get: () => "hidden" });
      document.dispatchEvent(new Event("visibilitychange"));
    });
    await expect(page.getByTestId("sb-live-chip")).toHaveAttribute("data-state", "paused_hidden");
    await page.clock.runFor(35_000);
    expect(be.runs).toHaveLength(3);
    // show it again: refreshing resumes
    await page.evaluate(() => {
      Object.defineProperty(document, "visibilityState", { configurable: true, get: () => "visible" });
      document.dispatchEvent(new Event("visibilitychange"));
    });
    await page.clock.runFor(10_500);
    await expect.poll(() => be.runs.length, SLOW).toBe(4);
    // and the Design view stops it
    await page.getByTestId("sb-tab-design").click();
    await page.clock.runFor(30_000);
    expect(be.runs).toHaveLength(4);
  });

  test("TC-E5b with the market closed the Result runs once and does not refresh", async ({ page }) => {
    await page.clock.install({ time: new Date("2026-11-03T12:00:00Z") });
    const be = await desk(page, { runAnswer: () => ({ status: 200, body: runResult({ open: false }) }) });
    await openBuilder(page);
    await page.getByTestId("sb-run").click();
    await expect(page.getByTestId("sb-result-table")).toBeVisible(SLOW);
    await expect(page.getByTestId("sb-live-chip")).toHaveAttribute("data-state", "closed");
    await expect(page.getByTestId("sb-live-chip")).toHaveText("Market closed · not refreshing");
    await page.clock.runFor(60_000);
    expect(be.runs).toHaveLength(1);
  });

  test("TC-E6 a scan problem (422) shows where; data unavailable (503) offers Retry; a 429 waits retry_after_s and runs again", async ({ page }) => {
    await page.clock.install({ time: new Date("2026-11-03T04:45:00Z") });
    const answers: Array<{ status: number; body: unknown }> = [
      { status: 422, body: { detail: { code: "invalid_spec", message: "RSI period must be between 2 and 100.", path: "filters.children[0].left.terms[0].operand.params.period" } } },
      { status: 503, body: { detail: { code: "data_unavailable", message: "The price history could not be loaded from the data platform." } } },
      { status: 200, body: runResult() },
      { status: 429, body: { detail: { code: "run_too_soon", message: "One run every 4 seconds.", retry_after_s: 3 } } },
      { status: 200, body: runResult({ bump: 5 }) },
    ];
    const be = await desk(page, { runAnswer: (n) => answers[Math.min(n, answers.length) - 1] });
    await openBuilder(page);
    await page.getByTestId("sb-run").click();
    const err = page.getByTestId("sb-error");
    await expect(err).toHaveAttribute("data-code", "invalid_spec", SLOW);
    await expect(err).toContainText("RSI period must be between 2 and 100.");
    await expect(page.getByTestId("sb-error-path")).toHaveText("at filters.children[0].left.terms[0].operand.params.period");
    await page.clock.runFor(30_000);
    expect(be.runs).toHaveLength(1);                                            // a failed run is not retried by itself
    await page.getByTestId("sb-run").click();
    await expect(err).toHaveAttribute("data-code", "data_unavailable", SLOW);
    await expect(err).toContainText("The market data could not be loaded for this run");
    await err.getByRole("button", { name: /Retry/ }).click();
    await expect(page.getByTestId("sb-result-table")).toBeVisible(SLOW);
    expect(be.runs).toHaveLength(3);
    // the 10 s refresh meets a 429: the table stays, the note says wait, and it runs again after retry_after_s (3 s)
    await page.clock.runFor(10_500);
    await expect.poll(() => be.runs.length, SLOW).toBe(4);
    await expect(err).toHaveAttribute("data-code", "run_too_soon", SLOW);
    await expect(err).toContainText("Try again in 3 s.");
    await expect(page.getByTestId("sb-result-table")).toBeVisible();
    await page.clock.runFor(3_500);
    await expect.poll(() => be.runs.length, SLOW).toBe(5);
    await expect(page.getByTestId("sb-result-row").nth(0)).toContainText("817.50", SLOW);
  });

  test("TC-E7 the screen never says buy, sell, target, stop loss or picks", async ({ page }) => {
    await desk(page, { scans: [{ id: "s9", spec: TEMPLATE_SPEC, created_at: "2026-11-02T10:00:00Z", updated_at: "2026-11-02T10:00:00Z" }] });
    await openBuilder(page);
    const banned = /\b(buy|buying|sell|selling|target|targets|stop[ -]?loss|picks?)\b/i;
    const texts: string[] = [];
    texts.push(await page.getByTestId("md-head").innerText());
    for (const r of ["sb-rail-columns", "sb-rail-filters", "sb-rail-groupsort"]) {
      await page.getByTestId(r).click();
      texts.push(await panel(page).innerText());
    }
    await page.getByTestId("sb-run").click();
    await expect(page.getByTestId("sb-result-table")).toBeVisible(SLOW);
    texts.push(await panel(page).innerText());
    for (const t of texts) expect(t).not.toMatch(banned);
  });

  test("TC-E8 intraday timeframes are listed but cannot be chosen yet; a template opens as a new unsaved scan", async ({ page }) => {
    await desk(page);
    await openBuilder(page);
    await page.getByTestId("sb-template-rsi_dw").click();
    await expect(page.getByTestId("sb-name")).toHaveValue("RSI above 50 — daily and weekly");
    const rows = page.getByTestId("sb-filter-row");
    await expect(rows).toHaveCount(2);
    await expect(rows.nth(1).getByTestId("sb-tf")).toHaveValue("1w");
    const tf = rows.nth(0).getByTestId("sb-tf");
    for (const [key, label] of [["5m", "5 minute"], ["15m", "15 minute"], ["1h", "1 hour"]]) {
      const opt = tf.locator(`option[value="${key}"]`);
      await expect(opt).toBeDisabled();
      await expect(opt).toHaveText(`${label} — coming next`);
    }
    for (const key of ["1d", "1w", "1M"]) await expect(tf.locator(`option[value="${key}"]`)).toBeEnabled();
    await expect(page).not.toHaveURL(/[?&]scan=/);
    await expect(page.getByTestId("sb-save")).toBeEnabled();
  });
});
