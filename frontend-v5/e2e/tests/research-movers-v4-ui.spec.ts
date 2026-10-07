/**
 * Research -> Move odds -> Movers: behaviour of the v4 design port (rail, pinning, flag-lift strip, calibration strip,
 * bottom row, honest-degradation states).
 *
 * MOCK - not real data: every /api/movers* response is a fixture shaped like the REAL API (see the example responses
 * in the mv4 fixtures: bar_index is RELATIVE to the plotted bars 0..n-1, impact_score is a label or null, flag-lift flags
 * carry by_decile x10 and the response carries decile_base, rolling_beta carries available/reason).
 * These cases verify the SCREEN, in particular that no withheld/absent number is ever turned into a zero.
 */
import { test, expect, type Page, type Route } from "@playwright/test";
import fs from "fs";
import path from "path";
import { mockAuthAs } from "../helpers/api-mock";

const FX = path.join(process.cwd(), "e2e", "fixtures");
const load = (n: string) => JSON.parse(fs.readFileSync(path.join(FX, n), "utf-8"));
type Json = Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any

const N = 30, T = 20, H = 3;
const DATES = Array.from({ length: N }, (_, i) => {
  const d = new Date(Date.UTC(2026, 8, 1)); d.setUTCDate(d.getUTCDate() + i); return d.toISOString().slice(0, 10);
});
const SESSION = DATES[T];
const bars = DATES.map((t, i) => {
  const base = 100 + i * 0.7, c = i === T ? base * 1.084 : base;
  return { t, o: base * 0.995, h: Math.max(base, c) * 1.012, l: Math.min(base, c) * 0.986, c, prev_c: base * 0.998, v: 900000 + i * 31000, turnover: 7.1e7 };
});
const LANES = [{ key: "fil", label: "RESULTS / FILINGS" }, { key: "ca", label: "CORP ACTION" }, { key: "deal", label: "BULK / BLOCK" },
               { key: "ins", label: "INSIDER / SAST" }, { key: "mdl", label: "ODDS MODEL" }];
const COST = 0.00628;
const exec = (out: "UP" | "DOWN" | "BOTH" | "NONE" | "PENDING", el = H) =>
  out === "PENDING"
    ? { gap: null, intra: null, re: 0.05, net: null, out, el, H, cost: COST }
    : { gap: 0.0311, intra: 0.0205, re: 0.07, net: 0.0205 - COST, out, el: H, H, cost: COST };

const caught = { state: "CAUGHT", score: 0.52, base_rate: 0.11, head: "p_up5_1d", run_session: DATES[T - 1], runs_in_window: 9, cutoff: 0.4 };
const missed = { ...caught, state: "MISSED", score: 0.22 };
const unscored = { state: "MISSED", score: null, head: null, run_session: null, runs_in_window: 9, reason: "NOT_IN_SCORED_UNIVERSE", note: "9 run(s) covered this window but the stock was not scored" };
const norun = { state: "NO_MODEL_RUN", score: null, head: null, run_session: null, runs_in_window: 0, note: "no final Move-odds run in the 20 days" };

const mover = (symbol: string, pct: number, odds: Json) => ({
  symbol, session: SESSION, pct, close: 112.4, prev_close: 103.7, open: 104.1, high: 113, low: 103.9, volume: 9e6, turnover: 9.9e8,
  ca_flag: null, ca_suspect: null, adjusted: false, odds,
});
const FIVE = [mover("UPONE", 8.4, caught), mover("UPTWO", 6.1, missed), mover("DOWNONE", -7.2, caught), mover("MISSDN", -5.5, missed),
              mover("NORUN", 5.2, norun), mover("NOTSCORED", 5.9, unscored)];

const ev = (id: string, o: Json = {}) => ({
  id, date: DATES[12], type: "res", lane: "fil", type_label: "RESULTS", glyph: "R", kind: "EARNINGS", kind_note: "Quarterly financial results approved by the board.",
  title: `Title ${id}`, sub: "sub", sentiment: null, impact_score: "medium", bar_index: 12, flags: [], exec: exec("NONE"),
  metrics: { re: 0.07, gap: 0.0311, vol_pre: 1.5, vol_post: 2.05, flip: false }, ...o,
});
const EV_ANN = ev("ann:1");
const EV_CA = ev("ca:1", { date: DATES[15], type: "ca", lane: "ca", type_label: "CORP ACTION", glyph: "C", kind: "DIVIDEND", title: "Dividend", bar_index: 15, exec: exec("UP") });

const decomp = (R: number, M: number, S: number) => {
  const m_part = 1.2 * M, s_part = 0.4 * (S - M);
  return { R, M, S, m_part, s_part, spec: R - m_part - s_part, available: true, sector_leg: true };
};
const windows = (eventR: number) => [
  { key: "BEFORE", label: "E-7 → E-1", decomp: decomp(0.021, 0.008, 0.012) },
  { key: "EVENT", label: "E-1 → E+1", decomp: decomp(eventR, 0.004, 0.015) },
  { key: "AFTER", label: "E+1 → E+7", decomp: decomp(-0.012, -0.006, -0.009) },
];
const REG = { beta: 1.2, corr: 0.61, sbeta: 0.4, scorr: 0.33, sessions: 120, requested_sessions: 250, window: [DATES[0], DATES[16]], available: true, degraded: true, reason: "SHORT_INDEX_HISTORY" };
const ROLL = { before: { beta: 1.1, corr: 0.6, sessions: 19, se: 0.18 }, after: { beta: 1.3, corr: 0.58, sessions: 19, se: 0.21 }, available: true, reason: null };

const byDecile = (rows: Array<[number | null, number]>) =>
  rows.map(([lift, firings], i) => ({ decile: i + 1, firings, moved: lift == null ? 0 : Math.max(1, Math.round(firings * 0.2)), base_rate: 0.04 + i * 0.03, lift }));
const DECILE_BASE = Array.from({ length: 10 }, (_, i) => ({ decile: i + 1, n: 700, base_rate: 0.04 + i * 0.03 }));
const LIFT: Json = {
  from: DATES[0], to: DATES[N - 1], head: "p_up5_1d", horizon: H, population: 6975, deciles: 10, base_rate: 0.0671, decile_base: DECILE_BASE,
  flags: [
    // decile 1: 3 firings (thin, faded); decile 2: no firings and a NULL lift (empty cell, not a zero)
    { key: "gap2", label: "GAP ≥2%", available: true, reason: null, lift_uncond: 2.37, lift_within: 1.62, n: 912, verdict: "SURVIVES",
      by_decile: byDecile([[2.5, 3], [null, 0], [1.4, 90], [1.6, 90], [1.7, 90], [1.8, 90], [2.1, 90], [2.2, 90], [1.9, 90], [1.6, 90]]) },
    { key: "vol2", label: "VOL 2×+", available: true, reason: null, lift_uncond: 2.08, lift_within: 1.07, n: 744, verdict: "DECORATION",
      by_decile: byDecile(Array.from({ length: 10 }, () => [1.05, 74] as [number, number])) },
    { key: "ins", label: "INSIDER / SAST ±3D", available: false, reason: "NIDP_INSIDER_SAST_NOT_BACKFILLED", lift_uncond: null, lift_within: null, n: 0, verdict: null },
  ],
};
const CAL = (over: number | null = 0.83): Json => ({
  from: DATES[0], to: DATES[N - 1], head: "p_up5_1d", horizon: H, population: 8972, pending_excluded: 1995, resolved: 6975, min_band_n: 30,
  available: true, reason: null, over_prediction: over, scored_as: "the head's own event on the target session (p_up5_1d)",
  note: "Scored against what the head actually predicts.",
  bands: [
    { lo: 0.0, hi: 0.1, n: 5354, predicted: 0.05, realised: 0.0314 }, { lo: 0.1, hi: 0.2, n: 872, predicted: 0.15, realised: 0.1296 },
    { lo: 0.2, hi: 0.3, n: 135, predicted: 0.25, realised: 0.2593 }, { lo: 0.3, hi: 0.4, n: 10, predicted: 0.35, realised: null },
    { lo: 0.4, hi: null, n: 7, predicted: 0.45, realised: null },
  ],
});
const FLAGGED: Json = {
  from: DATES[0], to: DATES[N - 1], head: "p_up5_1d", horizon: H, cutoff: 0.4, count: 2, flagged_total: 7, moved_late: 3, available: true, reason: null,
  outcomes: { UP: 2, DOWN: 1, BOTH: 0, NONE: 2, PENDING: 2 },
  rows: [["RVNL", "NONE"], ["IRFC", "PENDING"]].map(([symbol, out], k) => ({
    symbol, session: SESSION, model_p: 0.73 - k * 0.05, model_head: "p_up5_1d", base_rate: 0.11, pct: 1.2 - k, close: 410, prev_close: 405, open: 406, high: 412, low: 404,
    volume: 1.4e7, turnover: 5.6e8, ca_flag: null, ca_suspect: null, exec: exec(out as "NONE" | "PENDING", 1),
    odds: { ...caught, score: 0.73 - k * 0.05 },
  })),
};

type Opts = {
  movers?: Json[]; events?: Json[]; model?: (symbol: string) => Json | undefined;
  market?: Json; sector?: Json; regression?: Json; insider?: Json;
  cal?: () => { status: number; body: unknown }; lift?: () => { status: number; body: unknown };
  analysisFor?: (symbol: string, eventId: string | null) => Json;
  forward?: Json;                                                   // GET /api/movers/forward; omitted = 404 (no forward run)
  tech?: Json; techState?: (eventId: string | null) => Json;      // v5: omit both to get a v4-shaped API
};
type Calls = { analysis: URL[]; cal: number; lift: number; detail: URL[] };

const send = (route: Route, status: number, body: unknown) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });

async function setup(page: Page, o: Opts = {}): Promise<Calls> {
  const calls: Calls = { analysis: [], cal: 0, lift: 0, detail: [] };
  const movers = o.movers ?? FIVE;
  const events = o.events ?? [EV_ANN, EV_CA];
  const market = o.market ?? { name: "Nifty 50", label: "Nifty 50", is_proxy: false, series: bars.map((_, i) => 24000 + i * 18), available: true, reason: null };
  const sector = o.sector ?? { name: "Nifty Energy", series: bars.map((_, i) => 38000 + i * 22), available: true, reason: null, coverage: { mapped: 1011, total: 1011 } };
  const regression = o.regression ?? REG;
  const modelOf = (s: string) => o.model?.(s) ?? (movers.find((m) => m.symbol === s)?.odds as Json) ?? caught;
  const analysisFor = o.analysisFor ?? ((symbol: string, eventId: string | null) => {
    const pinned = eventId ? events.find((e) => e.id === eventId) ?? null : null;
    return { symbol, session: SESSION, market_index: "Nifty 50", sector_index: "Nifty Energy", regression, pinned_event: pinned,
      anchor: { bar: pinned ? pinned.date : SESSION, is_pinned_event: !!pinned }, windows: windows(pinned ? 0.2 : 0.084), rolling_beta: ROLL,
      ...(o.techState ? { tech_state: o.techState(eventId) } : {}), model: modelOf(symbol), disclaimer: "Attribution of realised return, not a causal claim: direction around events is not predictable in this dataset." };
  });

  await mockAuthAs(page, "user-profile-move-odds.json");
  for (const [p, f] of [["profile", "move-odds-profile.json"], ["history", "move-odds-history.json"], ["diagnostics", "move-odds-diagnostics.json"]] as const)
    await page.route(`**/api/move-odds/${p}**`, (r) => send(r, 200, load(f)));
  await page.route("**/api/move-odds/latest**", (r) => send(r, 200, load(`move-odds-latest-${new URL(r.request().url()).searchParams.get("head") ?? "p_up5_1d"}.json`)));
  await page.route("**/api/move-odds/live**", (r) => send(r, 200, load("move-odds-live.json")));

  // one handler, routed by path (a generic /api/movers/* glob would swallow the static endpoints)
  await page.route("**/api/movers**", (route) => {
    const url = new URL(route.request().url());
    const parts = url.pathname.split("/").filter(Boolean); // api, movers, X?, analysis?
    if (parts.length === 2) {
      return send(route, 200, { from: DATES[0], to: SESSION, count: movers.length, withheld_ca_suspect: 0, lanes: LANES, ranges: ["1D", "T7", "1M", "3M", "1Y"],
        filters: { min_abs_pct: 5, direction: "both", min_turnover: 5e6, include_ca: false }, movers });
    }
    if (parts[2] === "calibration") { calls.cal++; const r = o.cal?.() ?? { status: 200, body: CAL() }; return send(route, r.status, r.body); }
    if (parts[2] === "flag-lift") { calls.lift++; const r = o.lift?.() ?? { status: 200, body: LIFT }; return send(route, r.status, r.body); }
    if (parts[2] === "flagged") return send(route, 200, FLAGGED);
    if (parts[2] === "forward") return o.forward ? send(route, 200, o.forward) : send(route, 404, { detail: "no forward run on record" });
    const symbol = decodeURIComponent(parts[2]);
    if (parts[3] === "analysis") { calls.analysis.push(url); return send(route, 200, analysisFor(symbol, url.searchParams.get("event_id"))); }
    calls.detail.push(url);
    return send(route, 200, {
      symbol, session: SESSION, range: "T7", from: DATES[0], to: DATES[N - 1], horizon: H,
      header: { pct: 8.42, open: 104.1, high: 113, low: 103.9, close: 112.4, prev_close: 103.7, volume: 9e6, turnover: 9.9e8 },
      bars, market, sector, regression, rolling_beta: ROLL, windows: windows(0.084), lanes: o.tech ? [...LANES, { key: "rt", label: "ROUND TRIP" }] : LANES,
      ...(o.tech ? { tech: o.tech } : {}), ...(o.techState ? { tech_state: o.techState(null) } : {}),
      insider_lane: o.insider ?? { available: false, reason: "NOT_BACKFILLED", note: "nidp.insider_sast not present", source: null },
      events, model: modelOf(symbol), bar_index_of_session: T,
    });
  });
  return calls;
}

async function openMovers(page: Page) {
  await page.goto("/v5/research");
  await page.getByTestId("rail-odds").click();
  await page.getByTestId("mo-view-movers").click();
  await expect(page.getByTestId("mv-view")).toBeVisible();
  await expect(page.getByTestId("mv-copilot")).toBeVisible();
}
const rows = (page: Page) => page.locator('[data-testid^="mv-rail-row-"]');
const symbols = async (page: Page) => (await rows(page).evaluateAll((els) => els.map((e) => (e.getAttribute("data-testid") ?? "").replace("mv-rail-row-", ""))));

test.use({ viewport: { width: 1420, height: 1100 } });

test.describe("Move odds — Movers v4 UI behaviour", () => {
  test("TC-U01 pinning an event refetches /analysis with event_id and the Copilot + sensitivity cards change; unpinning restores", async ({ page }) => {
    const calls = await setup(page);
    await openMovers(page);
    await expect.poll(() => calls.analysis.length).toBeGreaterThan(0);
    expect(calls.analysis[0].searchParams.get("event_id")).toBeNull();            // default anchor = the move day
    await expect(page.getByTestId("mv-copilot-type")).toContainText("MOVE DAY");
    await expect(page.getByTestId("mv-attr")).toContainText("+8.4%");
    await expect(page.getByTestId("mv-attr")).not.toContainText("+20.0%");
    const before = calls.analysis.length;

    await page.getByTestId("mv-evt-ann:1").click();
    await expect.poll(() => calls.analysis.slice(before).map((u) => u.searchParams.get("event_id"))).toContain("ann:1");
    await expect(page.getByTestId("mv-copilot-type")).toContainText("RESULTS");
    await expect(page.getByTestId("mv-copilot")).toContainText(/PINNED EVENT/);
    await expect(page.getByTestId("mv-copilot")).toContainText("Title ann:1");
    await expect(page.getByTestId("mv-attr")).toContainText("+20.0%");           // the pinned anchor's decomposition, not the move day's
    await expect(page.getByTestId("mv-attr")).not.toContainText("+8.4%");
    await expect(page.getByTestId("mv-pin-line")).toBeVisible();

    // pin a different event: another request with that id, another card
    await page.getByTestId("mv-evt-ca:1").click();
    await expect(page.getByTestId("mv-copilot-type")).toContainText("CORP ACTION");
    expect(calls.analysis.map((u) => u.searchParams.get("event_id"))).toContain("ca:1");

    // clicking the pinned marker again returns to the move day (and refetches without event_id)
    const n = calls.analysis.length;
    await page.getByTestId("mv-evt-ca:1").click();
    await expect.poll(() => calls.analysis.slice(n).some((u) => u.searchParams.get("event_id") === null)).toBe(true);
    await expect(page.getByTestId("mv-copilot-type")).toContainText("MOVE DAY");
    await expect(page.getByTestId("mv-pin-line")).toHaveCount(0);
  });

  test("TC-U02 rail filter tabs ALL/UP/DOWN/MISSED and the Movers/Flagged mode switch with its counts", async ({ page }) => {
    await setup(page);
    await openMovers(page);
    await expect(page.getByTestId("mv-mode-movers")).toContainText("MOVERS · RECALL · 6");
    await expect(page.getByTestId("mv-rail-meta")).toContainText(/6 MOVERS SHOWN/);
    expect((await symbols(page)).sort()).toEqual(["DOWNONE", "MISSDN", "NORUN", "NOTSCORED", "UPONE", "UPTWO"]);

    await page.getByTestId("mv-filter-up").click();
    expect((await symbols(page)).sort()).toEqual(["NORUN", "NOTSCORED", "UPONE", "UPTWO"]);
    await page.getByTestId("mv-filter-down").click();
    expect((await symbols(page)).sort()).toEqual(["DOWNONE", "MISSDN"]);
    // MISSED = scored and below the cut-off ONLY: a coverage gap (no run / not scored) is not a miss
    await page.getByTestId("mv-filter-missed").click();
    expect((await symbols(page)).sort()).toEqual(["MISSDN", "UPTWO"]);
    await expect(page.getByTestId("mv-filter-missed")).toHaveAttribute("aria-pressed", "true");
    await page.getByTestId("mv-filter-all").click();
    expect(await rows(page).count()).toBe(6);

    await page.getByTestId("mv-mode-flagged").click();
    await expect(page.getByTestId("mv-mode-flagged")).toContainText("FLAGGED · NONE / PENDING · 2");   // label counts the list shown
    await expect(page.getByTestId("mv-flagged-shares")).toContainText(/OF 7 FLAGGED/);
    expect((await symbols(page)).sort()).toEqual(["IRFC", "RVNL"]);
    // the filter set changes with the side, and resets to ALL
    await expect(page.getByTestId("mv-filter-up")).toHaveCount(0);
    await page.getByTestId("mv-filter-none").click();
    expect(await symbols(page)).toEqual(["RVNL"]);
    await page.getByTestId("mv-filter-pending").click();
    expect(await symbols(page)).toEqual(["IRFC"]);
    await page.getByTestId("mv-mode-movers").click();
    await expect(page.getByTestId("mv-filter-all")).toHaveAttribute("aria-pressed", "true");
    expect(await rows(page).count()).toBe(6);
  });

  test("TC-U03 the rail scrolls inside its own container; 100 rows do not make the page taller", async ({ page }) => {
    const hundred = Array.from({ length: 100 }, (_, i) => mover(`SYM${String(i).padStart(3, "0")}`, i % 2 ? -5.5 - i / 100 : 5.5 + i / 100, i % 3 ? caught : missed));
    await setup(page, { movers: FIVE });
    await openMovers(page);
    const pageH5 = await page.evaluate(() => document.documentElement.scrollHeight);

    const p2 = await page.context().newPage();
    await p2.setViewportSize({ width: 1420, height: 1100 });
    await setup(p2, { movers: hundred });
    await openMovers(p2);
    await expect(rows(p2)).toHaveCount(100);
    const m = await p2.evaluate(() => {
      const rail = document.querySelector('[data-testid="mv-rail-scroll"]') as HTMLElement;
      const before = rail.scrollTop; rail.scrollTop = 1500;
      return { sh: rail.scrollHeight, ch: rail.clientHeight, moved: rail.scrollTop - before, page: document.documentElement.scrollHeight, vh: window.innerHeight };
    });
    expect(m.sh, "the rail content is far taller than its box").toBeGreaterThan(m.ch * 2);
    expect(m.ch, "the rail box is capped at the viewport").toBeLessThanOrEqual(m.vh);
    expect(m.moved, "the rail itself scrolled").toBeGreaterThan(0);
    expect(m.page, `page height with 100 rows (${m.page}) vs 6 rows (${pageH5})`).toBeLessThanOrEqual(pageH5 + 40);
    await p2.close();
  });

  test("TC-U04 flag-lift strip: 10 cells per flag, thin cells faded, a null lift is an empty cell and never a 0", async ({ page }) => {
    await setup(page);
    await openMovers(page);
    await expect(page.getByTestId("mv-lift")).toBeVisible();
    const cellsOf = (key: string) => page.getByTestId(`mv-lift-${key}`).locator('span[title^="D"]');
    await expect(cellsOf("gap2")).toHaveCount(10);
    await expect(cellsOf("vol2")).toHaveCount(10);
    await expect(page.getByTestId("mv-lift-base").locator('span[title^="D"]')).toHaveCount(10);   // BASE row: decile_base x10
    // the 3-firing cell is faded and says so; a 90-firing cell is not
    const thin = cellsOf("gap2").nth(0);
    await expect(thin).toHaveAttribute("data-thin", "1");
    await expect(thin).toHaveAttribute("title", /thin \(fewer than 5 firings\)/);
    await expect(thin).toHaveCSS("opacity", "0.4");
    const firm = cellsOf("gap2").nth(2);
    await expect(firm).not.toHaveAttribute("data-thin", "1");
    await expect(firm).toHaveCSS("opacity", "1");
    // the null-lift cell: a dashed empty box whose tooltip says "no lift", with no 0.00x anywhere in it
    const empty = cellsOf("gap2").nth(1);
    await expect(empty).toHaveAttribute("title", /no lift/);
    await expect(empty).not.toHaveAttribute("title", /0\.00×|0×/);
    await expect(empty).toHaveCSS("border-top-style", "dashed");
    await expect(empty).toHaveCSS("background-color", "rgba(0, 0, 0, 0)");
    await expect(empty).toHaveText("");
    // the legend names both treatments
    await expect(page.getByTestId("mv-lift")).toContainText(/faded = fewer than 5 firings/);
    await expect(page.getByTestId("mv-lift")).toContainText(/empty = no lift/);
  });

  test("TC-U05 calibration strip shows the real ratio and how the head was scored", async ({ page }) => {
    await setup(page, { cal: () => ({ status: 200, body: CAL(1.4) }) });
    await openMovers(page);
    await expect(page.getByTestId("mv-cal-over")).toContainText("OVER-PREDICTS 1.4×");
    await expect(page.getByTestId("mv-cal-over")).toHaveAttribute("title", /1\.40/);
    await expect(page.getByTestId("mv-cal-foot")).toContainText(/Scored as the head's own event on the target session \(p_up5_1d\)/);
    await expect(page.getByTestId("mv-cal")).toContainText(/6,975 RESOLVED STOCK-DAYS/);
    // a null ratio is NOT MEASURED, never 0.00x
    const p2 = await page.context().newPage();
    await setup(p2, { cal: () => ({ status: 200, body: CAL(null) }) });
    await openMovers(p2);
    await expect(p2.getByTestId("mv-cal-over")).toContainText("NOT MEASURED");
    await expect(p2.getByTestId("mv-cal")).not.toContainText(/0\.00×/);
    await p2.close();
  });

  test("TC-U06 bottom row: NO_MODEL_RUN is a coverage gap, never NOT CAUGHT or MOVE MISSED", async ({ page }) => {
    await setup(page);
    await openMovers(page);
    await page.getByTestId("mv-rail-row-NORUN").click();
    await expect(page.getByTestId("mv-model-pill")).toHaveText("NO MODEL RUN");
    await expect(page.getByTestId("mv-model-pill")).toHaveAttribute("data-state", "NO_MODEL_RUN");
    await expect(page.getByTestId("mv-model-sub")).toContainText(/coverage gap, not a miss/i);
    const panel = page.getByTestId("mv-model-panel");
    await expect(panel).not.toContainText(/NOT CAUGHT/);
    await expect(panel).not.toContainText(/MOVE MISSED/);
    await expect(panel).not.toContainText(/PEAK SCORE/);
    await expect(panel).toContainText("NOT COVERED");
    // outside the scored universe: a different coverage gap, also not a miss
    await page.getByTestId("mv-rail-row-NOTSCORED").click();
    await expect(page.getByTestId("mv-model-pill")).toHaveText("NOT SCORED");
    await expect(panel).not.toContainText(/NOT CAUGHT|MOVE MISSED/);
    // a real miss IS a miss and shows its real score
    await page.getByTestId("mv-rail-row-UPTWO").click();
    await expect(page.getByTestId("mv-model-pill")).toHaveText("NOT CAUGHT");
    await expect(panel).toContainText("MOVE MISSED");
    await expect(panel).toContainText("0.22");
    // caught
    await page.getByTestId("mv-rail-row-UPONE").click();
    await expect(page.getByTestId("mv-model-pill")).toHaveText("CAUGHT EARLY");
    await expect(panel).toContainText("0.52");
  });

  test("TC-U07 log rows: NONE prints the word, PENDING prints PEND x/H, no outcome prints a dash; count line states each", async ({ page }) => {
    const events = [
      ev("e-up", { exec: exec("UP"), bar_index: 5, date: DATES[5] }),
      ev("e-none", { exec: exec("NONE"), bar_index: 8, date: DATES[8] }),
      ev("e-pend", { exec: exec("PENDING", 1), bar_index: 18, date: DATES[18] }),
      ev("e-noexec", { exec: null, bar_index: 19, date: DATES[19] }),
    ];
    await setup(page, { events });
    await openMovers(page);
    await expect(page.getByTestId("mv-log-out-e-up")).toHaveText("UP");
    await expect(page.getByTestId("mv-log-out-e-none")).toHaveText("NONE");
    await expect(page.getByTestId("mv-log-out-e-none")).toHaveAttribute("title", /neither \+5% nor -5%/);
    await expect(page.getByTestId("mv-log-out-e-pend")).toHaveText("PEND 1/3");
    await expect(page.getByTestId("mv-log-out-e-noexec")).toHaveText("—");
    // pending / no-exec rows carry dashes for the executable figures, not +0.0%
    await expect(page.getByTestId("mv-log-e-pend")).not.toContainText("+0.0%");
    await expect(page.getByTestId("mv-log-e-noexec")).not.toContainText(/[+-]0\.0%/);
    const count = page.getByTestId("mv-log-count");
    await expect(count).toContainText("4 EVENTS");
    await expect(count).toContainText("50% OF 2 RESOLVED HIT ±5% / 3S");   // UP + NONE resolved: 1 of 2
    await expect(count).toContainText("1 PENDING");
    await expect(count).toContainText("1 NO OUTCOME");
    // a log row pins the event too
    await page.getByTestId("mv-log-e-none").click();
    await expect(page.getByTestId("mv-log-e-none")).toHaveAttribute("aria-pressed", "true");
    await expect(page.getByTestId("mv-pin-line")).toBeVisible();
  });

  test("TC-U08 no sector index: the reason is shown and no sector number is a zero", async ({ page }) => {
    await setup(page, { sector: { name: null, series: [], available: false, reason: "NO_SECTOR_MAPPING", coverage: { mapped: 2345, total: 2695 } } });
    await openMovers(page);
    await expect(page.getByTestId("mv-nosector")).toContainText(/NO SECTOR INDEX/);
    await expect(page.getByTestId("mv-nosector")).toContainText("2,345 / 2,695");
    const attr = page.getByTestId("mv-attr");
    await expect(attr).toContainText(/No sector (leg|mapping)|No sector index/i);
    await expect(attr).toContainText(/SECTOR · NO SECTOR INDEX/);
    await expect(attr).toContainText("No sector mapping for this symbol");           // BETA · SECTOR tile
    await expect(attr).not.toContainText(/SECTOR[^|]*[+-]0\.0%/);
  });

  test("TC-U09 no market index: beta is not estimated, the card says why, and no market figure is a zero", async ({ page }) => {
    await setup(page, {
      market: { name: "Nifty 50", label: "Nifty 50", is_proxy: false, series: [], available: false, reason: "NO_INDEX_SERIES" },
      regression: { ...REG, beta: null, corr: null, sbeta: null, scorr: null, available: false, degraded: false, reason: "NO_INDEX_HISTORY" },
    });
    await openMovers(page);
    const attr = page.getByTestId("mv-attr");
    await expect(attr).toBeVisible();
    await expect(page.getByTestId("mv-reg")).toContainText(/No market index series is available/);
    await expect(page.getByTestId("mv-reg")).toContainText(/Beta could not be estimated/);
    await expect(attr).toContainText(/Not estimated/);
    await expect(attr).not.toContainText(/BETA · NIFTY 50\s*0\.00/);
    await expect(page.getByTestId("mv-reg-degraded")).toHaveCount(0);
  });

  test("TC-U10 no insider source: the lane says so instead of drawing an empty lane", async ({ page }) => {
    await setup(page);
    await openMovers(page);
    await expect(page.getByTestId("mv-lane-ins")).toBeVisible();
    await expect(page.getByTestId("mv-lane-ins-note")).toBeVisible();
    await expect(page.getByTestId("mv-lane-ins-note")).toHaveAttribute("title", /not available for this stock yet/);
    // when the source exists the note is gone
    const p2 = await page.context().newPage();
    await setup(p2, { insider: { available: true, reason: null, source: "trendlyne" } });
    await openMovers(p2);
    await expect(p2.getByTestId("mv-lane-ins")).toBeVisible();
    await expect(p2.getByTestId("mv-lane-ins-note")).toHaveCount(0);
    await p2.close();
  });

  test("TC-U11 calibration error shows the reason and a Retry that refetches and recovers", async ({ page }) => {
    let fail = true;
    const calls = await setup(page, { cal: () => (fail ? { status: 500, body: { detail: "internal_error" } } : { status: 200, body: CAL() }) });
    await openMovers(page);
    const err = page.getByTestId("mv-cal-error");
    await expect(err).toBeVisible();
    await expect(err).toContainText(/could not be loaded/i);
    await expect(page.getByTestId("mv-cal")).toHaveCount(0);                      // no chart, no figure
    await expect(err).not.toContainText(/0\.00×|0%/);
    const retry = err.getByRole("button", { name: /retry|try again/i });
    await expect(retry, "the calibration error offers a retry button").toBeVisible();
    fail = false;
    const n = calls.cal;
    await retry.click();
    await expect.poll(() => calls.cal).toBeGreaterThan(n);
    await expect(page.getByTestId("mv-cal")).toBeVisible();
    await expect(page.getByTestId("mv-cal-error")).toHaveCount(0);
  });

  test("TC-U12 flag-lift error shows the reason and a Try again that refetches and recovers", async ({ page }) => {
    let fail = true;
    const calls = await setup(page, { lift: () => (fail ? { status: 500, body: { detail: "internal_error" } } : { status: 200, body: LIFT }) });
    await openMovers(page);
    const card = page.getByTestId("mv-lift");
    await expect(card).toContainText(/Could not load the flag comparison/);
    await expect(page.locator('[data-testid^="mv-lift-gap2"]')).toHaveCount(0);   // no row, no number
    await expect(card).not.toContainText(/×/);
    fail = false;
    const n = calls.lift;
    await card.getByRole("button", { name: /try again|retry/i }).click();
    await expect.poll(() => calls.lift).toBeGreaterThan(n);
    await expect(page.getByTestId("mv-lift-gap2")).toContainText("1.62");
    await expect(page.getByTestId("mv-lift-na-ins")).toContainText(/insider/i);
  });
});


// ── v5: technical state ──────────────────────────────────────────────────────────────────────────────────────────────
// MOCK - not real data: indicator values are fixtures shaped like the real API (null until the indicator has its sessions).
const ser = (f: (i: number) => number, nulls = 0) => bars.map((_, i) => (i < nulls ? null : f(i)));
const TECH: Json = {
  available: true,
  series: { ema20: ser((i) => 100 + i * 0.6, 3), ema50: ser((i) => 99 + i * 0.5, 6), rsi: ser((i) => 45 + i, 2), adx: ser((i) => 15 + i * 0.5, 5), pdi: ser(() => 30, 2), mdi: ser(() => 15, 2) },
  per_bar: bars.map((_, i) => ({ score: i < 5 ? null : i % 11, max: i < 5 ? null : 10, rvol: 1.2, rsi: 45 + i, adx: 15 + i * 0.5, rt: i >= 13 && i <= 19 })),
  // two overlapping round trips by different counterparties: the lane merges them into one span and says so
  round_trips: [{ b: 10, s: 13, days: 3, cp: "Alpha Fincap Limited", qty_b: 1000, qty_s: 1000 }, { b: 12, s: 15, days: 3, cp: "Beta Securities", qty_b: 500, qty_s: 500 }],
  delivery_coverage: { sessions: 27, total: 30 },
};
const row = (k: string, v: string, on: boolean | null) => ({ k, v, on });
const STATE = (score: number, anchor = SESSION, rt = false): Json => ({
  available: true, anchor, score, max: 9, bucket: score >= 7 ? "VERY STRONG" : "MODERATE", round_trip: rt,
  round_trip_detail: rt ? { cp: "Alpha Fincap Limited", days: 3, sold: anchor } : null,
  pts: [row("CLOSE > EMA20", "", true), row("RSI14 > 55", "", true), row("20D RS > NIFTY", "", null), row("RVOL20 > 1.5", "", false)].map(({ k, on }) => ({ k, on })),
  families: [
    { name: "1 · TREND STRUCTURE", rows: [row("CLOSE > EMA20", "112.40 / 108.20", true), row("EMA20 > EMA50", "108.20 / 105.00", true)] },
    { name: "3 · VOLUME / PARTICIPATION", rows: [row("RVOL20 > 1.5", "1.20×", false), row("DELIVERY % > 20D AVG", "NOT IN THE DELIVERY FEED FOR THIS SESSION", null)] },
    { name: "5 · RELATIVE STRENGTH · VS NIFTY", rows: [row("20D EXCESS RETURN", "—", null)] },
  ],
});

test.describe("Move odds — Movers v5 technical state", () => {
  test("TC-T01 EMA lines, RSI/ADX panel, merged round-trip lane and the hover tech line", async ({ page }) => {
    await setup(page, { tech: TECH, techState: (id) => (id ? STATE(8, DATES[12]) : STATE(5)) });
    await openMovers(page);
    await expect(page.getByTestId("mv-tech-overlay")).toBeVisible();
    for (const id of ["mv-ema20", "mv-ema50", "mv-rsi", "mv-adx"]) await expect(page.getByTestId(id)).toHaveAttribute("d", /^M/);
    await expect(page.getByTestId("mv-tech-panel")).toContainText("RSI14");
    if (process.env.V5_SHOT) { await page.getByTestId("mv-chart").screenshot({ path: process.env.V5_SHOT + "-chart.png" }); await page.getByTestId("mv-tech").screenshot({ path: process.env.V5_SHOT + "-tech.png" }); }
    // two overlapping round trips -> ONE span, labelled with the count, never two stacked boxes
    await expect(page.getByTestId("mv-rt-span")).toHaveCount(1);
    await expect(page.getByTestId("mv-rt-span")).toHaveAttribute("title", /2 round trips merged/);
    await page.getByTestId("mv-chart-scroll").scrollIntoViewIfNeeded();
    const box = await page.getByTestId("mv-chart-scroll").boundingBox();
    await page.mouse.move(box!.x + ((box!.width - 84) / N) * 14.5, box!.y + 120);
    await expect(page.getByTestId("mv-chart-header-tech")).toContainText(/TECH (\d+\/10|—) · RSI \d+ · ADX \d+ · ROUND TRIP/);
  });

  test("TC-T02 score, ten points, six-group rows; an unevaluable condition is informational and uncounted; pinning re-anchors", async ({ page }) => {
    const calls = await setup(page, { tech: TECH, techState: (id) => (id ? STATE(8, DATES[12], true) : STATE(5)) });
    await openMovers(page);
    await expect(page.getByTestId("mv-tech-score")).toContainText("5/9");
    await expect(page.getByTestId("mv-tech")).toContainText("MOVE DAY");
    await expect(page.getByTestId("mv-tech-pt")).toHaveCount(4);
    await expect(page.getByTestId("mv-tech-pt").nth(2)).toHaveAttribute("data-on", "null");        // RS vs Nifty: not evaluable, not "failed"
    await expect(page.getByTestId("mv-tech")).toContainText("1 condition could not be evaluated and is not counted");
    await expect(page.getByTestId("mv-tech")).toContainText("NOT IN THE DELIVERY FEED FOR THIS SESSION");
    await expect(page.getByTestId("mv-tech-family")).toHaveCount(3);
    await expect(page.getByTestId("mv-tech-rt")).toContainText("NO ROUND TRIP");
    await expect(page.getByTestId("mv-tech-delivery-note")).toContainText("27 OF 30");

    await page.getByTestId("mv-evt-ann:1").click();
    await expect.poll(() => calls.analysis.map((u) => u.searchParams.get("event_id"))).toContain("ann:1");
    await expect(page.getByTestId("mv-tech-score")).toContainText("8/9");
    await expect(page.getByTestId("mv-tech")).toContainText("PINNED EVENT");
    await expect(page.getByTestId("mv-tech-rt")).toContainText("ROUND TRIP · ALPHA FINCAP LIMITED · 3D");
  });

  test("TC-T03 not enough history: no score is invented, and the chart says the indicators are unavailable", async ({ page }) => {
    await setup(page, { tech: { available: false, reason: "NO_BARS" }, techState: () => ({ available: false, reason: "NEEDS_50_SESSIONS_OF_HISTORY", anchor: SESSION }) });
    await openMovers(page);
    await expect(page.getByTestId("mv-tech-unavailable")).toBeVisible();
    await expect(page.getByTestId("mv-tech-unavailable-card")).toContainText("THE SCORE NEEDS 50 SESSIONS");
    await expect(page.getByTestId("mv-tech-score")).toHaveCount(0);
    await expect(page.getByTestId("mv-ema20")).toHaveCount(0);
    await expect(page.getByTestId("mv-lane-rt")).toContainText("ROUND-TRIP DETECTION UNAVAILABLE");
  });

  test("TC-T04 a v4-shaped API (no tech fields) still renders and shows no technical card", async ({ page }) => {
    await setup(page);
    await openMovers(page);
    await expect(page.getByTestId("mv-chart")).toBeVisible();
    await expect(page.getByTestId("mv-tech")).toHaveCount(0);
  });
});


// ── forward lists: official run beside the labelled preview ─────────────────────────────────────────────────────────────
// MOCK - not real data: shaped like GET /api/movers/forward.
const fr = (symbol: string, up: number, down: number, inOff?: boolean) => ({ symbol, name: `${symbol} Limited`, up, down, either: up + down, ...(inOff === undefined ? {} : { in_official_universe: inOff }) });
const FWD: Json = {
  session: "2026-10-05",
  official: { available: true, run_id: 13, data_as_of: "2026-10-01", scored: 997, label: "OFFICIAL · FROZEN · COUNTS TOWARD THE VERDICT", avg_either: 0.091, rows: [fr("DELTACORP", 0.313, 0.341), fr("RATNAVEER", 0.252, 0.283)] },
  preview: { available: true, label: "NEW-UNIVERSE PREVIEW", data_as_of: "2026-10-01", git_sha: "2ef4ecb8", universe_size: 1449, scored: 1418,
    note: "Scored with newer model code than the frozen nightly. Not graded, never counts toward the verdict.", graded: false, counts_toward_verdict: false, avg_either: 0.103, top_overlap: 1,
    rows: [fr("THOMASCOTT", 0.42, 0.384, false), fr("DELTACORP", 0.326, 0.303, true)] },
  disclaimer: "Volatility odds only: direction is not predictable in this dataset.",
};

test.describe("Move odds — Movers forward lists", () => {
  test("TC-F01 the official run and the preview sit side by side; the preview is labelled, dashed and never presented as graded", async ({ page }) => {
    await setup(page, { forward: FWD });
    await openMovers(page);
    await page.getByTestId("mv-mode-forward").click();
    await expect(page.getByTestId("mv-forward")).toContainText("SESSION 05 OCT 2026");
    await expect(page.getByTestId("mv-fwd-official")).toContainText("OFFICIAL · FROZEN · COUNTS TOWARD THE VERDICT");
    await expect(page.getByTestId("mv-fwd-official")).toContainText("RUN 13");
    await expect(page.getByTestId("mv-fwd-preview-badge")).toHaveText("NEW-UNIVERSE PREVIEW · NOT GRADED");
    await expect(page.getByTestId("mv-fwd-preview")).toContainText("Not graded, never counts toward the verdict");
    await expect(page.getByTestId("mv-fwd-preview")).toContainText("1 OF THE TOP 2 ALSO IN THE OFFICIAL TOP 2");
    await expect(page.getByTestId("mv-fwd-official-row")).toHaveCount(2);
    await expect(page.getByTestId("mv-fwd-preview-row")).toHaveCount(2);
    await expect(page.getByTestId("mv-fwd-preview-row").first()).toContainText("NEWLY SCORED");   // THOMASCOTT is outside the official universe
    await expect(page.getByTestId("mv-fwd-preview-row").first()).toContainText("80%");           // 0.42 + 0.384 = 0.804, rounded
    await expect(page.getByTestId("mv-fwd-preview-row").nth(1)).not.toContainText("NEWLY SCORED");
    await expect(page.getByTestId("mv-fwd-official")).not.toContainText("NEWLY SCORED");
  });

  test("TC-F02 no preview on record: the preview column says so and shows no rows", async ({ page }) => {
    await setup(page, { forward: { ...FWD, preview: { ...FWD.preview, available: false, label: null, rows: [], scored: 0, top_overlap: 0 } } });
    await openMovers(page);
    await page.getByTestId("mv-mode-forward").click();
    await expect(page.getByTestId("mv-fwd-preview")).toContainText("No preview is on record for this session");
    await expect(page.getByTestId("mv-fwd-preview-row")).toHaveCount(0);
    await expect(page.getByTestId("mv-fwd-official-row")).toHaveCount(2);
  });

  test("TC-F03 no forward run at all (404): no card and no error text, the page is unchanged", async ({ page }) => {
    await setup(page);
    await openMovers(page);
    await page.getByTestId("mv-mode-forward").click();
    await expect(page.getByTestId("mv-forward")).toHaveCount(0);
    await expect(page.getByTestId("mv-fwd-error")).toHaveCount(0);
  });

  test("TC-F04 three tabs; a forward candidate opens the same detail view as a mover", async ({ page }) => {
    await setup(page, { forward: FWD, tech: TECH, techState: () => STATE });
    await openMovers(page);
    for (const id of ["mv-mode-movers", "mv-mode-flagged", "mv-mode-forward"]) await expect(page.getByTestId(id)).toBeVisible();
    await expect(page.getByTestId("mv-mode-forward")).toContainText("FORWARD · NEXT SESSION · 5 Oct 2026");
    await expect(page.getByTestId("mv-forward")).toHaveCount(0);   // the comparison card belongs to the forward tab only
    await page.getByTestId("mv-mode-forward").click();
    await expect(page.getByTestId("mv-forward")).toBeVisible();
    await expect(rows(page)).toHaveCount(2);        // OFFICIAL filter by default
    await expect(rows(page).first()).toContainText("OFFICIAL");
    await rows(page).first().click();
    await expect(page.getByTestId("mv-hero-synthesis")).toContainText("frozen official run");
    await expect(page.getByTestId("mv-hero-synthesis")).toContainText("It has not moved yet");
    await expect(page.getByTestId("mv-chart")).toBeVisible();
    await expect(page.getByTestId("mv-tech-panel")).toBeVisible();
    await expect(page.getByTestId("mv-hero-synthesis")).not.toContainText(/buy|sell|recommend|hold/i);
  });
});
