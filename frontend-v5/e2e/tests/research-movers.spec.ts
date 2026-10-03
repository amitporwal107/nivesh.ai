/**
 * Research → Move odds → Movers view (mocked layer). Test cases TC-M09..TC-M21 in test_reports/TESTCASES_movers_screen.md.
 *
 * MOCK — not real data: every /api/movers response here is a hand-built fixture shaped like backend/routes/movers.py
 * (list_movers, mover_detail, mover_analysis). Unlike /api/move-odds/*, those endpoints return their payload at the TOP
 * LEVEL (no `{data: ...}` envelope), so the mocks below fulfil the un-enveloped shape. auth/me is mocked too, and the
 * Estimates/History views are fed by the existing move-odds fixtures. The staging run against real data is separate.
 */
import { test, expect, type Page, type Route } from "@playwright/test";
import fs from "fs";
import path from "path";
import { mockAuthAs } from "../helpers/api-mock";

const FX = path.join(process.cwd(), "e2e", "fixtures");
const load = (name: string) => JSON.parse(fs.readFileSync(path.join(FX, name), "utf-8"));
// Same banned vocabulary as the host screen, narrowed to what TC-M17 names.
const BANNED = /\b(buy|hold|sell|recommend\w*)\b/i;

// ── the ONE fixture ────────────────────────────────────────────────────────────────────────────────────────────────
// MOCK — not real data. 30 weekday sessions from 2026-09-01; the move session T is bar 20.
const N_BARS = 30;
const T_IDX = 20;
const DATES: string[] = (() => {
  const out: string[] = [];
  const d = new Date(Date.UTC(2026, 8, 1));
  while (out.length < N_BARS) {
    if (d.getUTCDay() !== 0 && d.getUTCDay() !== 6) out.push(d.toISOString().slice(0, 10));
    d.setUTCDate(d.getUTCDate() + 1);
  }
  return out;
})();
const SESSION = DATES[T_IDX];

type Json = Record<string, unknown>;
type Odds = Json;

// The list: CAUGHT, MISSED (scored, below cutoff), MISSED (not in scored universe), NO_MODEL_RUN.
const ODDS: Record<string, Odds> = {
  SUZLON: { state: "CAUGHT", score: 0.57, base_rate: 0.12, head: "p_up5_1d", run_session: DATES[T_IDX - 1], runs_in_window: 3, cutoff: 0.4, heads: { p_up5_1d: 0.57 } },
  KAYNES: { state: "MISSED", score: 0.22, base_rate: 0.1, head: "p_up5_1d", run_session: DATES[T_IDX - 1], runs_in_window: 3, cutoff: 0.4, heads: { p_up5_1d: 0.22 } },
  PGIL: { state: "MISSED", score: null, head: null, run_session: null, runs_in_window: 2, reason: "NOT_IN_SCORED_UNIVERSE", note: "2 run(s) covered this window but PGIL was not scored" },
  DIXON: { state: "NO_MODEL_RUN", score: null, head: null, run_session: null, runs_in_window: 0, note: `no final Move-odds run in the 20 days to ${SESSION}` },
};
const MOVERS = [
  { symbol: "SUZLON", pct: 8.4, close: 62.4, prev_close: 57.56 },
  { symbol: "KAYNES", pct: -6.1, close: 5120, prev_close: 5453 },
  { symbol: "PGIL", pct: 5.6, close: 410, prev_close: 388.3 },
  { symbol: "DIXON", pct: 5.2, close: 14800, prev_close: 14068 },
].map((m) => ({
  ...m, session: SESSION, open: m.prev_close, high: Math.max(m.close, m.prev_close) * 1.01, low: Math.min(m.close, m.prev_close) * 0.99,
  volume: 4_200_000, turnover: 8.1e8, ca_flag: null, ca_suspect: null, odds: ODDS[m.symbol],
}));
const LANES = [
  { key: "fil", label: "RESULTS / FILINGS" }, { key: "ca", label: "CORP ACTION" }, { key: "deal", label: "BULK / BLOCK" },
  { key: "ins", label: "INSIDER / SAST" }, { key: "mdl", label: "ODDS MODEL" },
];
const LIST: Json = {
  from: DATES[0], to: SESSION, count: MOVERS.length, withheld_ca_suspect: 2, lanes: LANES, ranges: ["1D", "T7", "1M", "3M", "1Y"],
  filters: { min_abs_pct: 5, direction: "both", min_turnover: 5e6, include_ca: false }, movers: MOVERS,
};

// Windows: R == m_part + s_part + spec (beta 1.2, sector beta 0.4), as backend _decomp computes it.
function decomp(R: number, M: number, S: number): Json {
  const m_part = 1.2 * M, s_part = 0.4 * (S - M);
  return { R, M, S, m_part, s_part, spec: R - m_part - s_part, available: true, sector_leg: true };
}
const WINDOWS: Json[] = [
  { key: "BEFORE", label: "E-7 → E-1", decomp: decomp(0.021, 0.008, 0.012) },
  { key: "EVENT", label: "E-1 → E+1", decomp: decomp(0.084, 0.004, 0.015) },
  { key: "AFTER", label: "E+1 → E+7", decomp: decomp(-0.012, -0.006, -0.009) },
];
const REGRESSION: Json = {
  beta: 1.2, corr: 0.61, sbeta: 0.4, scorr: 0.33, sessions: 120, requested_sessions: 250, window: [DATES[0], DATES[16]], available: true,
  degraded: true, reason: "market index history covers 120 of the design's 250 sessions (nidp.index_eod starts 2026-02-06)",
};

// Five events across fil/ca/deal/ins; one with bar_index null; one with metrics.gap 0.031 carrying a GAP flag.
function events(symbol: string): Json[] {
  const base = { sentiment: null, impact_score: null as string | null, session_shifted: false };   // impact_score is a label (low|medium|high) or null
  const noMetrics = { re: null, gap: null, vol_pre: null, vol_post: null, flip: false };
  return [
    { ...base, impact_score: "medium", id: `ann:${symbol}:1001`, date: DATES[12], type: "res", lane: "fil", type_label: "RESULTS", glyph: "R", kind: "EARNINGS",
      kind_note: "Quarterly financial results approved by the board.", title: "Quarterly results approved by the board", sub: "Q1 FY27 results",
      bar_index: 12, metrics: { ...noMetrics, re: 0.012, gap: 0.004 }, flags: [] },
    { ...base, id: `ca:${symbol}:${DATES[15]}:DIVIDEND`, date: DATES[15], type: "ca", lane: "ca", type_label: "CORP ACTION", glyph: "C", kind: "DIVIDEND",
      kind_note: "Record date for cash payout; price adjusts ex-date.", title: "DIVIDEND", sub: "₹1.50 / share",
      bar_index: 15, metrics: { ...noMetrics, re: -0.003, gap: -0.002 }, flags: [] },
    { ...base, id: `deal:BLOCK:${symbol}:${SESSION}:ARCADIA FUND:1200000`, date: SESSION, type: "dealB", lane: "deal", type_label: "DEAL · BOUGHT", glyph: "▲",
      kind: "BLOCK DEAL", kind_note: "Pre-agreed trade on the block window; shows institutional conviction.", title: "Block deal",
      sub: "Arcadia Fund · 1,200,000 sh @ ₹62.10", bar_index: T_IDX,
      metrics: { re: 0.084, gap: 0.031, vol_pre: 1.4, vol_post: 2.6, flip: false },
      flags: [{ label: "GAP UP ≥3% · 3.1%", tone: "mint" }, { label: "VOL 2×+ POST", tone: "amber" }] },
    { ...base, id: `ins:${symbol}:${DATES[22]}:PROMOTER GROUP`, date: DATES[22], type: "ins", lane: "ins", type_label: "INSIDER", glyph: "I", action: "Acquisition",
      kind: "INSIDER TRADE", kind_note: "PIT Reg 7(2) promoter/director trade.", title: "Promoter buys 0.12%", sub: "Promoter Group · Reg 7(2)",
      bar_index: 22, metrics: { ...noMetrics, re: 0.006, gap: 0.001 }, flags: [] },
    { ...base, id: `ann:${symbol}:1005`, date: "2026-10-30", type: "news", lane: "fil", type_label: "FILING", glyph: "F", kind: "DISCLOSURE",
      kind_note: "Exchange filing.", title: "Filing dated beyond the charted window", sub: "Outside the bars returned", bar_index: null, metrics: null, flags: [] },
  ];
}

/** Detail payload for one symbol. KAYNES has 26 bars (not 30) so a switch is visible in the chart. */
function detail(symbol: string, range = "T7"): Json {
  const nBars = symbol === "KAYNES" ? 26 : N_BARS;
  const bars = DATES.slice(0, nBars).map((t, i) => {
    const c = 100 + i * 0.5 + (i === T_IDX ? 6 : 0) + (symbol === "KAYNES" ? 40 : 0);
    const prev = i === 0 ? c - 0.5 : 100 + (i - 1) * 0.5 + (i - 1 === T_IDX ? 6 : 0) + (symbol === "KAYNES" ? 40 : 0);
    return { t, o: prev + 0.2, h: c + 1.1, l: prev - 0.9, c, prev_c: prev, v: 1_000_000 + i * 10_000, turnover: 1.2e8 };
  });
  const series = bars.map((_, i) => (i === 9 ? null : 22000 + i * 15));      // a gap in the market series
  const sectorSeries = bars.map((_, i) => 9000 + i * 6);
  return {
    symbol, session: SESSION, range, from: DATES[0], to: DATES[nBars - 1],
    header: { pct: MOVERS.find((m) => m.symbol === symbol)?.pct ?? null, open: 99, high: 108, low: 98, close: 106.5, prev_close: 100, volume: 4_200_000, turnover: 8.1e8 },
    bars,
    market: { name: "Nifty 50", series, available: true },
    sector: { name: "Nifty Energy", series: sectorSeries, available: true, reason: null },
    regression: REGRESSION,
    rolling_beta: { before: { beta: 1.1, corr: 0.5, sessions: 19, se: 0.2 }, after: { beta: 1.3, corr: 0.55, sessions: 7, se: 0.3 }, available: true, reason: null },
    windows: WINDOWS,
    lanes: LANES,
    insider_lane: { available: true, reason: null, source: "trendlyne" },
    events: events(symbol),
    model: ODDS[symbol],
    bar_index_of_session: T_IDX,
  };
}
function analysis(symbol: string, eventId: string | null): Json {
  const pinned = eventId ? events(symbol).find((e) => e.id === eventId) ?? null : null;
  return {
    symbol, session: SESSION, market_index: "Nifty 50", sector_index: "Nifty Energy", regression: REGRESSION, pinned_event: pinned,
    anchor: { bar: SESSION, is_pinned_event: !!pinned }, windows: WINDOWS, rolling_beta: { before: null, after: null, available: false, reason: "ONE_SIDED" }, model: ODDS[symbol],
    disclaimer: "Attribution of realised return, not a causal claim: direction around events is not predictable in this dataset.",
  };
}
const clone = <T,>(v: T): T => JSON.parse(JSON.stringify(v));

// ── mocking ────────────────────────────────────────────────────────────────────────────────────────────────────────
type Reply = { status: number; body: unknown };
type MoversOpts = {
  list?: (url: URL) => Reply;
  detail?: (symbol: string, url: URL) => Reply;
  analysis?: (symbol: string, url: URL) => Reply;
};
const ok = (body: unknown): Reply => ({ status: 200, body });
const send = (route: Route, r: Reply) => route.fulfill({ status: r.status, contentType: "application/json", body: JSON.stringify(r.body) });

/** The existing /api/move-odds/* fixtures (enveloped) so the Estimates and History views still render. */
async function mockOddsBase(page: Page) {
  const reply = (file: string) => (route: Route) => send(route, ok(load(file)));
  await page.route("**/api/move-odds/profile**", reply("move-odds-profile.json"));
  await page.route("**/api/move-odds/history**", reply("move-odds-history.json"));
  await page.route("**/api/move-odds/diagnostics**", reply("move-odds-diagnostics.json"));
  await page.route("**/api/move-odds/live**", (route) => send(route, ok({ data: { quotes: [] } })));
  await page.route("**/api/move-odds/latest**", (route) => {
    const head = new URL(route.request().url()).searchParams.get("head") ?? "p_up5_1d";
    return send(route, ok(load(`move-odds-latest-${head}.json`)));
  });
  await page.route("**/api/move-odds/stocks/**", (route) => send(route, { status: 404, body: { detail: "not_found" } }));
}

/** /api/movers* — payloads at the TOP LEVEL (no `data` envelope). Returns every request URL seen, by endpoint. */
async function mockMovers(page: Page, o: MoversOpts = {}) {
  const calls = { list: [] as URL[], detail: [] as URL[], analysis: [] as URL[] };
  await page.route("**/api/movers**", (route) => {
    const url = new URL(route.request().url());
    const parts = url.pathname.split("/").filter(Boolean);          // ["api","movers", SYMBOL?, "analysis"?]
    if (parts.length === 2) {
      calls.list.push(url);
      return send(route, o.list ? o.list(url) : ok(LIST));
    }
    // v4 added three STATIC endpoints under the same prefix. They are not symbols, and counting them
    // as detail calls is what made TC-M11 see a first call with no `range`. Serve them as
    // "unavailable" here: these v1 cases are not about them, and an unavailable panel is a real state.
    if (parts[2] === "forward") return route.fulfill({ status: 404, contentType: "application/json", body: JSON.stringify({ detail: "no forward run on record" }) });
    const V4 = new Set(["calibration", "flag-lift", "flagged"]);
    if (V4.has(parts[2])) {
      const base = { from: "2026-09-01", to: "2026-09-30", available: false, reason: "NO_FINAL_RUN_IN_WINDOW" };
      const body = parts[2] === "calibration"
        ? { ...base, head: "p_up5_1d", population: 0, pending_excluded: 0, over_prediction: null, bands: [] }
        : parts[2] === "flag-lift"
          ? { ...base, population: 0, deciles: 10, flags: [] }
          : { ...base, horizon: 3, cutoff: 0.4, count: 0, flagged_total: 0, moved_late: 0,
              outcomes: { UP: 0, DOWN: 0, BOTH: 0, NONE: 0, PENDING: 0 }, rows: [] };
      return send(route, ok(body));
    }
    const symbol = decodeURIComponent(parts[2]).toUpperCase();
    if (parts[3] === "analysis") {
      calls.analysis.push(url);
      return send(route, o.analysis ? o.analysis(symbol, url) : ok(analysis(symbol, url.searchParams.get("event_id"))));
    }
    calls.detail.push(url);
    return send(route, o.detail ? o.detail(symbol, url) : ok(detail(symbol, url.searchParams.get("range") ?? "T7")));
  });
  return calls;
}

async function setup(page: Page, o: MoversOpts = {}) {
  await mockAuthAs(page, "user-profile-move-odds.json");
  await mockOddsBase(page);
  return mockMovers(page, o);
}

async function openMovers(page: Page) {
  await page.goto("/v5/research");
  await page.getByTestId("rail-odds").click();
  await expect(page.getByTestId("move-odds-screen")).toBeVisible();
  await page.getByTestId("mo-view-movers").click();
  await expect(page.getByTestId("mv-view")).toBeVisible();
}

/** Click a rail row and wait for that symbol's chart to be drawn. */
async function selectRow(page: Page, symbol: string, lastBar = N_BARS - 1) {
  await page.getByTestId(`mv-rail-row-${symbol}`).click();
  await expect(page.getByTestId(`mv-rail-row-${symbol}`)).toHaveAttribute("aria-current", /^(?!false$).+/);
  await expect(page.getByTestId(`mv-candle-${lastBar}`)).toBeVisible();
}

const centreX = async (loc: ReturnType<Page["getByTestId"]>) => {
  const b = await loc.boundingBox();
  expect(b, "element has a bounding box").not.toBeNull();
  return b!.x + b!.width / 2;
};
const rangeOf = (u: URL) => u.searchParams.get("range");

test.describe("Move odds — Movers view", () => {
  test.use({ viewport: { width: 1440, height: 900 } });

  test("TC-M09 the toggle offers Movers and it renders the rail + chart; Estimates and History still work", async ({ page }) => {
    await setup(page);
    await page.goto("/v5/research");
    await page.getByTestId("rail-odds").click();
    await expect(page.getByTestId("mo-view-estimates")).toBeVisible();
    await expect(page.getByTestId("mo-view-history")).toBeVisible();
    await expect(page.getByTestId("mo-view-movers")).toBeVisible();
    await page.getByTestId("mo-view-movers").click();
    await expect(page.getByTestId("mv-view")).toBeVisible();
    await expect(page.getByTestId("mv-rail")).toBeVisible();
    for (const m of MOVERS) await expect(page.getByTestId(`mv-rail-row-${m.symbol}`)).toBeVisible();
    await expect(page.getByTestId("mv-chart")).toBeVisible();
    await page.getByTestId("mo-view-estimates").click();
    await expect(page.getByTestId("mo-row-PNCINFRA")).toBeVisible();
    await expect(page.getByTestId("mv-view")).toHaveCount(0);
    await page.getByTestId("mo-view-history").click();
    await expect(page.getByTestId("mo-history")).toBeVisible();
    await expect(page.getByTestId("mv-view")).toHaveCount(0);
  });

  test("TC-M10 clicking a rail row loads that symbol's detail; the row is aria-current; the chart updates", async ({ page }) => {
    const calls = await setup(page);
    await openMovers(page);
    await selectRow(page, "SUZLON");
    await expect(page.getByTestId("mv-candle-29")).toBeVisible();                        // SUZLON has 30 bars
    const before = calls.detail.length;
    await page.getByTestId("mv-rail-row-KAYNES").click();
    await expect.poll(() => calls.detail.slice(before).some((u) => u.pathname.endsWith("/api/movers/KAYNES"))).toBeTruthy();
    expect(calls.detail.slice(before).find((u) => u.pathname.endsWith("/KAYNES"))!.searchParams.get("session")).toBe(SESSION);
    await expect(page.getByTestId("mv-rail-row-KAYNES")).toHaveAttribute("aria-current", /^(?!false$).+/);
    await expect(page.getByTestId("mv-rail-row-SUZLON")).not.toHaveAttribute("aria-current", /^(?!false$).+/);
    await expect(page.getByTestId("mv-candle-25")).toBeVisible();                        // KAYNES has 26 bars: the chart redrew
    await expect(page.getByTestId("mv-candle-29")).toHaveCount(0);
    await expect(page.getByTestId("mv-attr")).toBeVisible();
    await expect(page.getByTestId("mv-lane-fil")).toBeVisible();
  });

  test("TC-M11 each of 1D/T7/1M/3M/1Y refetches with that range; T7 is the default", async ({ page }) => {
    const calls = await setup(page);
    await openMovers(page);
    await selectRow(page, "SUZLON");
    expect(rangeOf(calls.detail[0])).toBe("T7");                                          // default on first load
    for (const r of ["1D", "1M", "3M", "1Y", "T7"]) {
      const before = calls.detail.length;
      await page.getByTestId(`mv-range-${r}`).click();
      await expect.poll(() => calls.detail.slice(before).map(rangeOf), { message: `range ${r}` }).toContain(r);
      await expect(page.getByTestId("mv-chart")).toBeVisible();
    }
  });

  test("TC-M12 every event marker is centred on its price bar (±1.5px)", async ({ page }) => {
    await setup(page);
    await openMovers(page);
    await selectRow(page, "SUZLON");
    const placed = (events("SUZLON") as Array<{ id: string; bar_index: number | null }>).filter((e) => e.bar_index !== null);
    expect(placed.length).toBe(4);
    for (const e of placed) {
      const marker = page.getByTestId(`mv-evt-${e.id}`);
      await expect(marker, e.id).toBeVisible();
      const mx = await centreX(marker);
      const cx = await centreX(page.getByTestId(`mv-candle-${e.bar_index}`));
      expect(Math.abs(mx - cx), `${e.id} marker x ${mx} vs candle ${e.bar_index} x ${cx}`).toBeLessThanOrEqual(1.5);
    }
    // the session marker sits on T's bar too
    await expect(page.getByTestId("mv-session-marker")).toBeVisible();
    expect(Math.abs((await centreX(page.getByTestId("mv-session-marker"))) - (await centreX(page.getByTestId(`mv-candle-${T_IDX}`))))).toBeLessThanOrEqual(1.5);
  });

  test("TC-M13 the three badge states render three distinct sentences; NO_MODEL_RUN is not a failure", async ({ page }) => {
    await setup(page);
    await openMovers(page);
    // The badge is read from the selected mover's detail panel, or from its rail row when the row carries one.
    const badgeText = async (symbol: string) => {
      await page.getByTestId(`mv-rail-row-${symbol}`).click();
      await expect(page.getByTestId(`mv-rail-row-${symbol}`)).toHaveAttribute("aria-current", /^(?!false$).+/);
      await expect(page.getByTestId("mv-chart")).toBeVisible();
      const inRow = page.getByTestId(`mv-rail-row-${symbol}`).getByTestId("mv-badge");
      const badge = (await inRow.count()) > 0 ? inRow.first() : page.getByTestId("mv-badge").first();
      await expect(badge).toBeVisible();
      return (await badge.innerText()).replace(/\s+/g, " ").trim();
    };
    const caught = await badgeText("SUZLON");
    const missed = await badgeText("KAYNES");
    const noRun = await badgeText("DIXON");
    const unscored = await badgeText("PGIL");
    expect(new Set([caught, missed, noRun]).size, `${caught} | ${missed} | ${noRun}`).toBe(3);
    expect(unscored).not.toBe(missed);                                                     // not-in-universe reads differently from below-cutoff
    expect(noRun).not.toMatch(/\b(missed|failed|failure)\b/i);                             // a coverage gap, not a model failure
    expect(caught).toMatch(/caught/i);
    expect(missed).toMatch(/missed/i);
    expect(noRun).toMatch(/no model run/i);
    await expect(page.getByTestId("mv-badge-state").first()).toBeVisible();
  });

  test("TC-M14 the attribution card shows three windows split market / sector / stock-specific; a null decomp is not a zero", async ({ page }) => {
    // identity of the fixture itself: R == m_part + s_part + spec
    for (const w of WINDOWS as Array<{ decomp: { R: number; m_part: number; s_part: number; spec: number } }>) {
      expect(w.decomp.m_part + w.decomp.s_part + w.decomp.spec).toBeCloseTo(w.decomp.R, 9);
    }
    await setup(page);
    await openMovers(page);
    await selectRow(page, "SUZLON");
    await expect(page.getByTestId("mv-attr")).toBeVisible();
    for (const k of ["BEFORE", "EVENT", "AFTER"]) {
      const w = page.getByTestId(`mv-attr-${k}`);
      await expect(w, k).toBeVisible();
      await expect(w).toContainText(k);                                                  // the column header names its window
    }
    // v4 port: mv-attr-<WINDOW> is now a COLUMN of the BEFORE vs AFTER table; the market / sector / stock-specific split
    // lives in its rows and in the event-day decomposition, so assert those on the card itself.
    const attr = page.getByTestId("mv-attr");
    await expect(attr).toContainText(/MARKET/);
    await expect(attr).toContainText(/SECTOR/);
    await expect(attr).toContainText(/STOCK-SPECIFIC/);
    // the EVENT column carries the fixture's numbers: R = +8.4%
    await expect(attr).toContainText("+8.4%");
    await expect(page.getByTestId("mv-attr-na")).toHaveCount(0);                           // every decomp present: no "not available"
    await expect(page.getByTestId("mv-attr")).toContainText(/not a causal claim|attribution/i);

    // variant: the EVENT window has no decomp (a missing leg) -> "not available", never 0.0%
    const withGap = (sym: string) => {
      const d = clone(detail(sym)) as { windows: Array<{ key: string; decomp: unknown }> };
      d.windows.find((w) => w.key === "EVENT")!.decomp = null;
      return d;
    };
    const page2 = await page.context().newPage();
    await mockAuthAs(page2, "user-profile-move-odds.json");
    await mockOddsBase(page2);
    await mockMovers(page2, {
      detail: (s) => ok(withGap(s)),
      analysis: (s) => ok({ ...analysis(s, null), windows: (withGap(s) as { windows: unknown }).windows }),
    });
    await openMovers(page2);
    await selectRow(page2, "SUZLON");
    const ev = page2.getByTestId("mv-attr-EVENT");
    await expect(ev.getByTestId("mv-attr-na")).toBeVisible();
    await expect(ev).toContainText(/not available/i);
    await expect(ev).not.toContainText(/0\.0+%/);
    await expect(page2.getByTestId("mv-attr-BEFORE").getByTestId("mv-attr-na")).toHaveCount(0);
    await page2.close();
  });

  test("TC-M15 withheld_ca_suspect names the count; including them refetches with include_ca=true", async ({ page }) => {
    const calls = await setup(page);
    await openMovers(page);
    const w = page.getByTestId("mv-withheld");
    await expect(w).toBeVisible();
    await expect(w).toContainText("2");
    expect(calls.list[0].searchParams.get("include_ca")).not.toBe("true");
    const before = calls.list.length;
    await page.getByTestId("mv-include-ca").click();
    await expect.poll(() => calls.list.slice(before).map((u) => u.searchParams.get("include_ca"))).toContain("true");
  });

  test("TC-M16 the page disclaimer precedes every number in the Movers view", async ({ page }) => {
    await setup(page);
    await openMovers(page);
    await selectRow(page, "SUZLON");
    await expect(page.getByTestId("mo-disclaimer")).toBeVisible();
    const res = await page.evaluate(() => {
      const disc = document.querySelector('[data-testid="mo-disclaimer"]') as HTMLElement;
      const view = document.querySelector('[data-testid="mv-view"]') as HTMLElement;
      const walker = document.createTreeWalker(view, NodeFilter.SHOW_TEXT);
      let numbers = 0;
      const early: string[] = [];
      for (let n = walker.nextNode(); n; n = walker.nextNode()) {
        const t = (n.textContent ?? "").trim();
        if (!/\d/.test(t)) continue;
        numbers++;
        // the text node must come AFTER the disclaimer in document order
        if (!(disc.compareDocumentPosition(n) & Node.DOCUMENT_POSITION_FOLLOWING)) early.push(t);
      }
      const ids = ["mv-rail", "mv-chart", "mv-attr"].map((id) => {
        const el = document.querySelector(`[data-testid="${id}"]`);
        return [id, !!el && !!(disc.compareDocumentPosition(el) & Node.DOCUMENT_POSITION_FOLLOWING)] as const;
      });
      return { numbers, early, ids };
    });
    expect(res.numbers).toBeGreaterThan(10);
    expect(res.early, `numbers rendered before the disclaimer: ${res.early.join(" | ")}`).toEqual([]);
    for (const [id, after] of res.ids) expect(after, `${id} follows the disclaimer`).toBe(true);
  });

  test("TC-M17 no buy / hold / sell / recommend anywhere in the Movers view", async ({ page }) => {
    await setup(page);
    await openMovers(page);
    await selectRow(page, "SUZLON");
    await page.getByTestId(`mv-evt-${(events("SUZLON")[2] as { id: string }).id}`).hover();   // open a tooltip too, if the view has one
    const { text, labels } = await page.evaluate(() => {
      const view = document.querySelector('[data-testid="mv-view"]') as HTMLElement;
      const attrs = Array.from(view.querySelectorAll("[aria-label],[title]")).flatMap((e) => [e.getAttribute("aria-label"), e.getAttribute("title")]);
      return { text: view.innerText, labels: attrs.filter((a): a is string => !!a).join(" | ") };
    });
    for (const [what, s] of [["text", text], ["aria-label/title", labels]] as const) {
      const hit = s.match(BANNED);
      expect(hit, `banned word in ${what}: ${hit?.[0]}`).toBeNull();
    }
  });

  test("TC-M18 degraded beta shows sessions used vs requested (120 of 250)", async ({ page }) => {
    await setup(page);
    await openMovers(page);
    await selectRow(page, "SUZLON");
    await expect(page.getByTestId("mv-reg")).toBeVisible();
    const d = page.getByTestId("mv-reg-degraded");
    await expect(d).toBeVisible();
    await expect(d).toContainText("120");
    await expect(d).toContainText("250");
  });

  test("TC-M19 empty list shows an empty state; detail 404 shows a message; detail 500 offers a working retry", async ({ page }) => {
    // empty window
    await setup(page, { list: () => ok({ ...LIST, count: 0, movers: [], withheld_ca_suspect: 0 }) });
    await openMovers(page);
    await expect(page.getByTestId("mv-rail-empty")).toBeVisible();
    await expect(page.locator('[data-testid^="mv-rail-row-"]')).toHaveCount(0);

    // detail 404
    const p404 = await page.context().newPage();
    await mockAuthAs(p404, "user-profile-move-odds.json");
    await mockOddsBase(p404);
    await mockMovers(p404, { detail: (s) => ({ status: 404, body: { detail: `no EQ price history for ${s}` } }) });
    await openMovers(p404);
    await p404.getByTestId("mv-rail-row-SUZLON").click();
    await expect(p404.getByTestId("mv-view")).toContainText(/no price history/i);
    await expect(p404.locator('[data-testid^="mv-candle-"]')).toHaveCount(0);
    await p404.close();

    // detail 500, then recovery via retry
    const p500 = await page.context().newPage();
    await mockAuthAs(p500, "user-profile-move-odds.json");
    await mockOddsBase(p500);
    let fail = true;
    await mockMovers(p500, { detail: (s) => (fail ? { status: 500, body: { detail: "internal_error" } } : ok(detail(s))) });
    await openMovers(p500);
    await p500.getByTestId("mv-rail-row-SUZLON").click();
    await expect(p500.getByTestId("mv-detail-error")).toBeVisible();
    await expect(p500.getByTestId("mv-detail-retry")).toBeVisible();
    fail = false;
    await p500.getByTestId("mv-detail-retry").click();
    await expect(p500.getByTestId("mv-candle-0")).toBeVisible();
    await expect(p500.getByTestId("mv-detail-error")).toHaveCount(0);
    await p500.close();
  });

  test("TC-M20 a 403 on the movers list drops into the not-enabled state and shows no numbers", async ({ page }) => {
    await setup(page, { list: () => ({ status: 403, body: { detail: "feature_not_enabled" } }) });
    await openMovers(page).catch(() => undefined);                                         // mv-view may be replaced by the state itself
    await expect(page.getByTestId("mo-state-no_access")).toBeVisible();
    await expect(page.locator('[data-testid^="mv-rail-row-"]')).toHaveCount(0);
    await expect(page.locator('[data-testid^="mv-candle-"]')).toHaveCount(0);
    await expect(page.locator('[data-testid^="mo-big-"]')).toHaveCount(0);
  });

  test("TC-M21 rail rows and range buttons work by keyboard; markers are named by their title, not colour alone", async ({ page }) => {
    const calls = await setup(page);
    await openMovers(page);
    await selectRow(page, "SUZLON");

    const row = page.getByTestId("mv-rail-row-PGIL");
    await row.focus();
    await expect(row).toBeFocused();
    await page.keyboard.press("Enter");
    await expect(row).toHaveAttribute("aria-current", /^(?!false$).+/);
    const dixon = page.getByTestId("mv-rail-row-DIXON");
    await dixon.focus();
    await expect(dixon).toBeFocused();
    await page.keyboard.press("Space");
    await expect(dixon).toHaveAttribute("aria-current", /^(?!false$).+/);
    await expect.poll(() => calls.detail.some((u) => u.pathname.endsWith("/DIXON"))).toBeTruthy();

    for (const [r, key] of [["1M", "Enter"], ["3M", "Space"]] as const) {
      const btn = page.getByTestId(`mv-range-${r}`);
      await btn.focus();
      await expect(btn).toBeFocused();
      const before = calls.detail.length;
      await page.keyboard.press(key);
      await expect.poll(() => calls.detail.slice(before).map(rangeOf), { message: `${r} via ${key}` }).toContain(r);
    }

    // identity is not colour-alone: the marker's accessible name carries its title, and a text list repeats every event
    await selectRow(page, "SUZLON");
    for (const e of events("SUZLON") as Array<{ id: string; title: string; bar_index: number | null }>) {
      if (e.bar_index !== null) {
        await expect(page.getByTestId(`mv-evt-${e.id}`)).toHaveAccessibleName(new RegExp(e.title.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"), "i"));
      }
      await expect(page.getByTestId("mv-evt-list")).toContainText(e.title);                 // incl. the event with bar_index null
    }
  });
});
