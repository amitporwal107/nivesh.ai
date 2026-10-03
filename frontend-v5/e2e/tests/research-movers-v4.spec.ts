/**
 * Research → Move odds → Movers, **v4** panels.
 * Cases TC-V14..TC-V22 of test_reports/TESTCASES_movers_v4.md.
 *
 * MOCK — not real data: every /api/movers* response here is a fixture shaped like backend/routes/movers.py.
 * The real-data verification of the v4 formulas is the staging SQL and the logic harness recorded in the
 * report; these cases verify the SCREEN, in particular that it never turns a withheld number into a zero.
 */
import { test, expect, type Page } from "@playwright/test";
import fs from "fs";
import path from "path";
import { mockAuthAs } from "../helpers/api-mock";

const FX = path.join(process.cwd(), "e2e", "fixtures");
const load = (n: string) => JSON.parse(fs.readFileSync(path.join(FX, n), "utf-8"));
const SESSION = "2026-09-29";
const N = 30, T = 20;
const DATES = Array.from({ length: N }, (_, i) => {
  const d = new Date(Date.UTC(2026, 8, 1)); d.setUTCDate(d.getUTCDate() + i); return d.toISOString().slice(0, 10);
});
const bars = DATES.map((t, i) => {
  const base = 100 + i * 0.7, c = i === T ? base * 1.084 : base;
  return { t, o: base * 0.995, h: Math.max(base, c) * 1.012, l: Math.min(base, c) * 0.986,
           c, prev_c: base * 0.998, v: 900000 + i * 31000, turnover: 7.1e7 };
});
// the exact figures the design's execOf would produce; `net` must equal intra - 0.00628
const EXEC = { gap: 0.0311, intra: 0.0205, re: 0.0700, net: 0.0205 - 0.00628,
               out: "NONE" as const, el: 3, H: 3, cost: 0.00628 };
const LANES = [{ key: "fil", label: "RESULTS / FILINGS" }, { key: "ca", label: "CORP ACTION" },
               { key: "deal", label: "BULK / BLOCK" }, { key: "ins", label: "INSIDER / SAST" },
               { key: "mdl", label: "ODDS MODEL" }];
const ev = (id: string, date: string, bi: number | null, exec: unknown) => ({
  id, date, type: "res", lane: "fil", type_label: "RESULTS", glyph: "R", kind: "EARNINGS",
  kind_note: "Quarterly financial results approved by the board.", title: "Quarterly results approved",
  sub: "", sentiment: null, impact_score: "medium", bar_index: bi, flags: [], exec,
  metrics: { re: 0.07, gap: 0.0311, vol_pre: 1.5, vol_post: 2.05, flip: false },
});

const CAL = {
  from: DATES[0], to: DATES[N - 1], head: "p_up5_1d", horizon: 3,
  population: 8972, pending_excluded: 1995, resolved: 6975, min_band_n: 30,
  available: true, reason: null, over_prediction: 0.83,
  scored_as: "the head's own event on the target session (p_up5_1d)",
  note: "Scored against what the head actually predicts — one session, one side, against the previous close.",
  bands: [
    { lo: 0.00, hi: 0.05, n: 5354, predicted: 0.025, realised: 0.0314 },
    { lo: 0.05, hi: 0.10, n: 2253, predicted: 0.075, realised: 0.0905 },
    { lo: 0.10, hi: 0.15, n: 872,  predicted: 0.125, realised: 0.1296 },
    { lo: 0.15, hi: 0.20, n: 288,  predicted: 0.175, realised: 0.2222 },
    { lo: 0.20, hi: 0.25, n: 135,  predicted: 0.225, realised: 0.2593 },
    { lo: 0.25, hi: 0.30, n: 45,   predicted: 0.275, realised: 0.1778 },
    // below the 30-row floor: realised is WITHHELD, and must never render as 0
    { lo: 0.30, hi: 0.35, n: 10,   predicted: 0.325, realised: null },
    { lo: 0.35, hi: 0.40, n: 7,    predicted: 0.375, realised: null },
    { lo: 0.40, hi: null, n: 7,    predicted: 0.425, realised: null },
  ],
};
const LIFT = {
  from: DATES[0], to: DATES[N - 1], head: "p_up5_1d", horizon: 3,
  population: 6975, deciles: 10, base_rate: 0.0671,
  flags: [
    { key: "gap2", label: "GAP ≥2%", available: true, reason: null, lift_uncond: 2.37, lift_within: 1.62, n: 912, verdict: "SURVIVES" },
    { key: "vol2", label: "VOL 2×+", available: true, reason: null, lift_uncond: 2.08, lift_within: 1.07, n: 744, verdict: "DECORATION" },
    { key: "leak", label: "PRE-DRIFT LEAK", available: true, reason: null, lift_uncond: 1.93, lift_within: 1.71, n: 388, verdict: "PRE-PRICED" },
    { key: "ins", label: "INSIDER / SAST ±3D", available: false, reason: "NIDP_INSIDER_SAST_NOT_BACKFILLED", lift_uncond: null, lift_within: null, n: 0, verdict: null },
    { key: "d1", label: "BULK DEAL D-1", available: false, reason: "TOO_FEW_FIRINGS", lift_uncond: null, lift_within: null, n: 12, verdict: null },
  ],
};
const FLAGGED = (horizon: number) => ({
  from: DATES[0], to: DATES[N - 1], head: "p_up5_1d", horizon, cutoff: 0.40,
  count: 2, flagged_total: 7, moved_late: 3, available: true, reason: null,
  outcomes: { UP: 2, DOWN: 1, BOTH: 0, NONE: 2, PENDING: 2 },
  rows: ["RVNL", "IRFC"].map((symbol, k) => ({
    symbol, session: SESSION, model_p: 0.73 - k * 0.05, model_head: "p_up5_1d", base_rate: 0.11,
    pct: 1.2 - k, close: 410, prev_close: 405, open: 406, high: 412, low: 404,
    volume: 1.4e7, turnover: 5.6e8, ca_flag: null, ca_suspect: null,
    exec: { ...EXEC, out: k === 0 ? "NONE" : "PENDING", H: horizon },
    odds: { state: "CAUGHT", score: 0.73 - k * 0.05, base_rate: 0.11, head: "p_up5_1d",
            run_session: SESSION, runs_in_window: 9, cutoff: 0.40 },
  })),
});

async function setup(page: Page, o: { cal?: unknown; lift?: unknown; status?: number } = {}) {
  await mockAuthAs(page, "user-profile-move-odds.json");
  for (const [p, f] of [["profile", "move-odds-profile.json"], ["history", "move-odds-history.json"],
                        ["diagnostics", "move-odds-diagnostics.json"]] as const)
    await page.route(`**/api/move-odds/${p}**`, (r) =>
      r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(load(f)) }));
  await page.route("**/api/move-odds/latest**", (r) => {
    const h = new URL(r.request().url()).searchParams.get("head") ?? "p_up5_1d";
    return r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(load(`move-odds-latest-${h}.json`)) });
  });
  await page.route("**/api/move-odds/live**", (r) =>
    r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(load("move-odds-live.json")) }));
  await page.route("**/api/movers?**", (r) => r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({
    from: DATES[0], to: DATES[N - 1], count: 1, withheld_ca_suspect: 0, lanes: LANES,
    ranges: ["1D", "T7", "1M", "3M", "1Y"],
    filters: { min_abs_pct: 5, direction: "both", min_turnover: 5e6, include_ca: false },
    movers: [{ symbol: "SUZLON", session: SESSION, pct: 8.42, close: 112.4, prev_close: 103.7, open: 104.1,
               high: 113, low: 103.9, volume: 9e6, turnover: 9.9e8, ca_flag: null, ca_suspect: null,
               odds: { state: "CAUGHT", score: 0.52, base_rate: 0.11, head: "p_up5_1d",
                       run_session: DATES[19], runs_in_window: 9, cutoff: 0.4 } }],
  }) }));
  await page.route("**/api/movers/*?**", (r) => {
    const h = Number(new URL(r.request().url()).searchParams.get("horizon") ?? 3);
    return r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({
      symbol: "SUZLON", session: SESSION, range: "T7", from: DATES[0], to: DATES[N - 1], horizon: h,
      header: { pct: 8.42, open: 104.1, high: 113, low: 103.9, close: 112.4, prev_close: 103.7, volume: 9e6, turnover: 9.9e8 },
      bars, market: { name: "Nifty 50", label: "Nifty 50", is_proxy: false, series: bars.map((_, i) => 24000 + i * 18), available: true },
      sector: { name: "Nifty Energy", series: bars.map((_, i) => 38000 + i * 22), available: true, reason: null,
                coverage: { mapped: 1011, total: 1011 } },
      regression: { beta: 1.2, corr: 0.61, sbeta: 0.8, scorr: 0.5, sessions: 120, requested_sessions: 250,
                    window: [DATES[0], DATES[19]], available: true, degraded: true, reason: "SHORT_INDEX_HISTORY" },
      rolling_beta: { before: { beta: 1.1, corr: 0.6, sessions: 19, se: 0.18 }, after: { beta: 1.3, corr: 0.58, sessions: 19, se: 0.21 } },
      windows: [{ key: "BEFORE", label: "E-7 → E-1", decomp: { R: 0.021, M: 0.0083, S: 0.011, m_part: 0.010, s_part: 0.002, spec: 0.009, available: true, sector_leg: true } },
                { key: "EVENT", label: "E-1 → E+1", decomp: { R: 0.084, M: 0.0042, S: 0.009, m_part: 0.005, s_part: 0.004, spec: 0.075, available: true, sector_leg: true } },
                { key: "AFTER", label: "E+1 → E+7", decomp: { R: -0.012, M: -0.0058, S: -0.007, m_part: -0.007, s_part: -0.001, spec: -0.004, available: true, sector_leg: true } }],
      lanes: LANES, insider_lane: { available: false, reason: "NOT_BACKFILLED", note: "nidp.insider_sast not present", source: null },
      events: [ev("ann:1", DATES[12], 12, { ...EXEC, H: h })],
      model: { state: "CAUGHT", score: 0.52, base_rate: 0.11, head: "p_up5_1d", run_session: DATES[19], runs_in_window: 9, cutoff: 0.4 },
      bar_index_of_session: T,
    }) });
  });

  // registered LAST on purpose: Playwright prefers the most recently added matching route, and
  // the generic "/api/movers/*?" above matches /api/movers/calibration too.
  await page.route("**/api/movers/calibration**", (r) =>
    r.fulfill({ status: o.status ?? 200, contentType: "application/json", body: JSON.stringify(o.cal ?? CAL) }));
  await page.route("**/api/movers/flag-lift**", (r) =>
    r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(o.lift ?? LIFT) }));
  await page.route("**/api/movers/flagged**", (r) => {
    const h = Number(new URL(r.request().url()).searchParams.get("horizon") ?? 3);
    return r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(FLAGGED(h)) });
  });
}

async function openMovers(page: Page) {
  await page.goto("/v5/research");
  await page.getByTestId("rail-odds").click();
  await page.getByTestId("mo-view-movers").click();
  await expect(page.getByTestId("mv-view")).toBeVisible();
}

test.use({ viewport: { width: 1420, height: 1100 } });

test.describe("Move odds — Movers v4", () => {
  test("TC-V14 an event shows four returns, with net after costs in ink and close-to-close dimmed", async ({ page }) => {
    await setup(page); await openMovers(page);
    await page.getByTestId("mv-evt-ann:1").click();
    const ex = page.getByTestId("mv-exec");
    await expect(ex).toBeVisible();
    for (const id of ["mv-exec-re", "mv-exec-gap", "mv-exec-intra", "mv-exec-net"])
      await expect(page.getByTestId(id)).toBeVisible();
    // net == open-to-close minus the stated cost
    await expect(page.getByTestId("mv-exec-net")).toContainText("1.4%");
    await expect(page.getByTestId("mv-exec-re")).toContainText(/reference/i);
    await expect(ex).toContainText(/0\.628/);                        // TC-V21: costs are named
  });

  test("TC-V15 the outcome is a state, and NONE never reads as a zero return", async ({ page }) => {
    await setup(page); await openMovers(page);
    await page.getByTestId("mv-evt-ann:1").click();
    const pill = page.getByTestId("mv-exec-out");
    await expect(pill).toHaveText("NONE");
    await expect(page.getByTestId("mv-exec")).toContainText(/reached neither/i);
    await expect(page.getByTestId("mv-exec")).not.toContainText(/outcome.*0\.0%/i);
  });

  test("TC-V16 the mirror switch shows the flags that did not move, and how they turned out", async ({ page }) => {
    await setup(page); await openMovers(page);
    await page.getByTestId("mv-mode-flagged").click();
    await expect(page.getByTestId("mv-flagged-shares")).toContainText("7");
    await expect(page.getByTestId("mv-flagged-shares")).toContainText(/none/i);
    await expect(page.getByTestId("mv-rail-row-RVNL")).toBeVisible();
    await expect(page.getByTestId("mv-mode-flagged")).toContainText("2");       // label counts the list shown
    await page.getByTestId("mv-mode-movers").click();
    await expect(page.getByTestId("mv-rail-row-SUZLON")).toBeVisible();
  });

  test("TC-V17 the horizon switch re-derives the flagged list", async ({ page }) => {
    await setup(page); await openMovers(page);
    await page.getByTestId("mv-mode-flagged").click();
    const seen: string[] = [];
    page.on("request", (r) => { if (r.url().includes("/api/movers/flagged")) seen.push(r.url()); });
    await page.getByTestId("mv-hz-20").click();
    await expect.poll(() => seen.some((u) => u.includes("horizon=20"))).toBe(true);
  });

  test("TC-V18 calibration: predicted vs realised, and an empty band is not a zero bar", async ({ page }) => {
    await setup(page); await openMovers(page);
    await expect(page.getByTestId("mv-cal")).toBeVisible();
    await expect(page.getByTestId("mv-cal-over")).toContainText(/0\.83/);
    await expect(page.getByTestId("mv-cal-over")).toContainText(/under/i);      // 0.83 < 1 = under-states
    await expect(page.getByTestId("mv-cal")).toContainText(/too few/i);         // the withheld bands say so
    const table = page.getByTestId("mv-cal-table");
    await expect(table).toBeVisible();
    await expect(table).not.toContainText(/0\.0%\s*$/);
  });

  test("TC-V18b calibration unavailable renders a reason, never an empty chart", async ({ page }) => {
    await setup(page, { cal: { ...CAL, available: false, reason: "NO_FINAL_RUN_IN_WINDOW", bands: [], over_prediction: null } });
    await openMovers(page);
    await expect(page.getByTestId("mv-cal-unavailable")).toBeVisible();
    await expect(page.getByTestId("mv-cal")).toHaveCount(0);
  });

  test("TC-V19 flag lift shows the uncontrolled figure struck through beside the within-volatility one", async ({ page }) => {
    await setup(page); await openMovers(page);
    await expect(page.getByTestId("mv-lift")).toBeVisible();
    await expect(page.getByTestId("mv-lift-gap2")).toContainText("1.62");
    await expect(page.getByTestId("mv-lift-gap2")).toContainText("SURVIVES");
    await expect(page.getByTestId("mv-lift-vol2")).toContainText("DECORATION");
    await expect(page.getByTestId("mv-lift-leak")).toContainText("PRE-PRICED");
    await expect(page.getByTestId("mv-lift")).toContainText(/similar volatility/i);
  });

  test("TC-V19b a flag with no source shows its reason, not a number", async ({ page }) => {
    await setup(page); await openMovers(page);
    const na = page.getByTestId("mv-lift-na-ins");
    await expect(na).toBeVisible();
    await expect(na).toContainText(/insider/i);
    await expect(page.getByTestId("mv-lift-ins")).not.toContainText(/\d+\.\d+×/);
    await expect(page.getByTestId("mv-lift-na-d1")).toContainText(/rarely|too few/i);
  });

  test("TC-V20 no value from v4's sample LIFT table appears on screen", async ({ page }) => {
    await setup(page); await openMovers(page);
    await expect(page.getByTestId("mv-lift")).toBeVisible();
    const txt = (await page.getByTestId("mv-view").innerText()).replace(/\s+/g, " ");
    // v4 ships these as sample constants; the backend computes instead, so none may appear as a lift
    for (const v of ["2.1×", "1.3×", "2.6×", "1.4×", "2.4×", "1.05×", "2.9×", "1.1×", "2.2×", "1.8×", "4.4×", "4.0×", "1.6×", "1.15×"])
      expect(txt, `v4 sample constant ${v} rendered`).not.toContain(v);
  });

  test("TC-V22 the v1 rules still hold across the new panels", async ({ page }) => {
    await setup(page); await openMovers(page);
    await expect(page.getByTestId("mv-cal")).toBeVisible();
    const txt = await page.getByTestId("mv-view").innerText();
    expect(txt).not.toMatch(/\b(buy|hold|sell|recommend\w*)\b/i);
    const disc = await page.getByTestId("mo-disclaimer").boundingBox();
    const view = await page.getByTestId("mv-view").boundingBox();
    expect(disc && view && disc.y).toBeLessThan(view!.y);
  });
});

