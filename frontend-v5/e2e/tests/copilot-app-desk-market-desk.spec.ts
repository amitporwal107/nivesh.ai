/**
 * One-screen Copilot app (/v5/app) — Smart trading desk redesign, step 5: tab 03 Market Desk (Market Intelligence ·
 * Smart Money · Sector Rotation · Stock Research · Screener, the owner's design, PLAN.md "1-REVISED") and the Idea
 * scorecard component (tradingdesk/scorecard, for Trade Desk › AI Scanner › Scorecard). Test cases:
 * test_reports/desk_market_desk_TESTCASES.md (MD-*, SC-*, W-1, P-1).
 *
 * MOCK — not real data: every /api response is mocked. The scorecard fixture e2e/fixtures/desk-idea-scorecard.json is
 * a copy of the body staging's GET /api/desk/idea-scorecard returned on 2026-10-27 (read-only); that route serves the
 * committed research/p4_adx_rs/results_20261027/result.json, so the figures are the study's. The other routes are inline
 * payloads in the shape the real route returns (named beside each), with synthetic values.
 *
 * Covers screens/tradingdesk/tabs/market-desk (MarketDesk.tsx, SectorReadout.tsx): the one frame every view shares
 * (view head, jump links, where related data lives), Market Intelligence's sector-rotation readout, Stock Research's
 * symbol strip, the redirect of the moved views (watchlists, scorecard) to Trade Desk, the wording and 390px; and
 * tradingdesk/scorecard (IdeaScorecard.tsx, scorecard-data.ts): study, verdict, RS63, each split's arms with nulls and
 * negatives as they are, the per-arm checks, the sources, and the 503 / failure / contract states. The scorecard cases
 * run where a tab mounts the component: set SCORECARD_URL below when Trade Desk does. The hosted screens keep their own
 * specs.
 */
import fs from "node:fs";
import path from "node:path";
import { test, expect, type Page, type Route } from "@playwright/test";
import { mockApi, mockSingleRoute } from "../helpers/api-mock";

const DESK = "/v5/app/trader/desk";
const SCORECARD = JSON.parse(fs.readFileSync(path.join(process.cwd(), "e2e", "fixtures", "desk-idea-scorecard.json"), "utf-8"));

const VIEWS = [
  { key: "intel", label: "Market Intelligence", panel: "desk-panel-intel" },
  { key: "smartmoney", label: "Smart Money", panel: "desk-panel-smartmoney" },
  { key: "sectors", label: "Sector Rotation", panel: "desk-panel-sectors" },
  { key: "research", label: "Stock Research", panel: "desk-panel-chart" },
  { key: "screener", label: "Screener", panel: "desk-panel-screener" },
];

/**
 * Where the Idea scorecard is mounted. Null until the Trade Desk tab (AI Scanner › Scorecard) mounts
 * tradingdesk/scorecard/IdeaScorecard.tsx; the SC-* cases are skipped while it is null.
 */
const SCORECARD_URL: string | null = null;
const needsScorecard = () => test.skip(!SCORECARD_URL, "The Idea scorecard is mounted by the Trade Desk tab (AI Scanner › Scorecard); set SCORECARD_URL");

// backend/routes/markets.py :: GET /api/markets/sector-heatmap — synthetic: 8 sectors, the index's weighted change
// d +0.20 / w +1.00 / m +2.00, so a sector's 1M and 1W against the index are its own returns minus 2.00 and 1.00.
const HEAT_SECTORS: Array<[string, number, number, number]> = [
  // name,        1D,    1W,    1M
  ["Fin Alpha", 0.5, 2.0, 5.0], // vs index 1M +3.00, 1W +1.00 → leading
  ["IT Beta", -0.4, 0.5, 4.0], // +2.00, −0.50 → weakening
  ["Metal Gamma", 1.2, 1.5, 3.0], // +1.00, +0.50 → leading
  ["Auto Delta", 0.1, 1.0, 2.5], // +0.50 (4th of 8: not shown)
  ["Pharma Eps", -0.2, 0.9, 1.5], // −0.50 (5th of 8: not shown)
  ["Energy Zeta", 0.3, 2.5, 1.0], // −1.00, +1.50 → improving
  ["FMCG Eta", -0.6, 0.2, 0.0], // −2.00, −0.80 → lagging
  ["Realty Theta", -1.1, -1.0, -3.0], // −5.00, −2.00 → lagging
];
const heatStock = (symbol: string, sector: string, d: number) => ({
  symbol, name: symbol, sector, close: 100, weight_pct: 1, traded_value_cr: 10, returns: { d, w: 0, m: 0 }, index_impact_pct: { d: 0 }, rel_volume: 1,
});
const HEATMAP = {
  as_of: "2026-10-26", index: "NIFTY50", source: "nidp.warehouse", sessions: { d: 1, w: 5, m: 21 }, mode: "end_of_day",
  weight_basis: "market_cap", weight_note: "fixture",
  sectors: HEAT_SECTORS.map(([name, d, w, m]) => ({ name, stocks: 2, weight_pct: 12.5, returns: { d, w, m }, contribution_pct: { d: 0, w: 0, m: 0 } })),
  // Fin Alpha: 2 of 2 rose; FMCG Eta: 0 of 2; every other sector 1 of 2.
  stocks: HEAT_SECTORS.flatMap(([name]) => name === "Fin Alpha" ? [heatStock("FA1", name, 1), heatStock("FA2", name, 0.5)]
    : name === "FMCG Eta" ? [heatStock("FE1", name, -1), heatStock("FE2", name, -0.5)]
    : [heatStock(`${name}1`.replace(/\s/g, ""), name, 1), heatStock(`${name}2`.replace(/\s/g, ""), name, -1)]),
  breadth: { advances: 8, declines: 8, unchanged: 0 },
  weighted_change: { d: 0.2, w: 1.0, m: 2.0 },
  unavailable: [],
};

const json = (route: Route, body: unknown, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });

// backend/routes/positional.py (get_watchlist, get_picks): one setup, so the chart's fallback stock is TESTBRK.
const WATCHLIST = { as_of_date: "2026-10-12", buckets: {
  breakout_confirmed: [{ nse_symbol: "TESTBRK", sector: "Capital Goods", close_price: 510.0, trigger_price: 500.0, stop_price: 477.5, atr_pct: 2.94, why: "Fixture reason" }],
  pre_breakout: [], true_accumulation: [], trend_continuation: [] } };
const PICKS = { signal_date: "2026-10-12", count: 0, picks: [] };

async function deskApi(page: Page, scorecard: (route: Route) => unknown = (route) => json(route, SCORECARD)) {
  await mockApi(page, "populated");
  await mockSingleRoute(page, "**/api/markets/home", "markets-home.json");
  await page.route("**/api/positional/watchlist*", (route) => json(route, WATCHLIST));
  await page.route("**/api/positional/picks*", (route) => json(route, PICKS));
  await page.route("**/api/move-odds/**", (route) => json(route, { detail: "feature_not_enabled" }, 403));
  await page.route("**/api/markets/sector-returns", (route) => json(route, { as_of: "2026-10-13", source: "NSE index close (nidp.index_eod)", sessions: { "1d": 1, "1w": 5, "1m": 21 }, sectors: [] }));
  await page.route("**/api/desk/alerts*", (route) => json(route, { as_of: null, checked_through: null, marks_error: null, alerts: [] }));
  await page.route("**/api/chat/sessions", (route) => json(route, []));
  await page.route("**/api/desk/idea-scorecard", (route) => scorecard(route) as Promise<void>);
  await page.route("**/api/markets/sector-heatmap*", (route) => json(route, HEATMAP));
}

const params = (page: Page) => new URL(page.url()).searchParams;
async function expectAt(page: Page, view: string, extra: Record<string, string> = {}) {
  await expect.poll(() => params(page).get("tab")).toBe("market");
  await expect.poll(() => params(page).get("view")).toBe(view);
  for (const [k, v] of Object.entries(extra)) await expect.poll(() => params(page).get(k)).toBe(v);
}

async function noSideScroll(page: Page, where: string) {
  const o = await page.evaluate(() => {
    const sc = document.querySelector('[data-testid="copilot-scroll"]') as HTMLElement | null;
    const right = sc ? sc.getBoundingClientRect().right : window.innerWidth;
    // The outermost elements that reach past the right edge (a scroller's own content is clipped and not listed).
    const wide = (Array.from(document.querySelectorAll("*")) as HTMLElement[]).filter((el) => {
      const r = el.getBoundingClientRect();
      return r.width > 0 && r.right > right + 1 && !(el.parentElement && el.parentElement.getBoundingClientRect().right > right + 1);
    }).slice(0, 6).map((el) => `${el.tagName.toLowerCase()}[${el.getAttribute("data-testid") ?? el.className.toString().slice(0, 40)}] right=${Math.round(el.getBoundingClientRect().right)}`);
    return { doc: document.documentElement.scrollWidth - window.innerWidth, scroll: sc ? sc.scrollWidth - sc.clientWidth : 0, wide: wide.join(", ") };
  });
  expect(o.doc, `${where}: ${o.wide}`).toBeLessThanOrEqual(1);
  expect(o.scroll, `${where}: ${o.wide}`).toBeLessThanOrEqual(1);
}

const BANNED = /\bpick|recommended|suggest/i;
const row = (page: Page, split: string, arm: string) => page.getByTestId(`sc-row-${split}-${arm}`);

test.describe("MOCK — not real data: Market Desk · the frame", () => {
  test.beforeEach(async ({ page }) => { await deskApi(page); });

  test("MD-1 the switcher lists the five views in the design's order; intel is the default", async ({ page }) => {
    await page.goto(`${DESK}?tab=market`);
    await expectAt(page, "intel");
    await expect(page.getByTestId("desk-views").getByRole("button")).toHaveText(VIEWS.map((v) => v.label));
    await expect(page.getByTestId("desk-view-intel")).toHaveAttribute("aria-pressed", "true");
  });

  test("MD-2 every view has the same head (eyebrow, one sentence) over its hosted panel", async ({ page }) => {
    test.setTimeout(120_000);
    for (const v of VIEWS) {
      await page.goto(`${DESK}?tab=market&view=${v.key}`);
      const head = page.getByTestId("md-head");
      await expect(head, v.key).toHaveAttribute("data-view", v.key);
      await expect(page.getByTestId("md-eyebrow"), v.key).toHaveText(`Market Desk · ${v.label}`);
      await expect(page.getByTestId("md-line"), v.key).not.toBeEmpty();
      await expect(page.getByTestId("desk-panel-market").getByTestId(v.panel).first(), v.key).toBeVisible({ timeout: 15_000 });
      await expect(page.getByTestId("desk-view-" + v.key)).toHaveAttribute("aria-pressed", "true");
    }
  });

  test("MD-3 / MD-5 the option chain lives in Smart Money only; its jump link sets section=fno", async ({ page }) => {
    test.setTimeout(120_000);
    for (const v of VIEWS.filter((x) => x.key !== "smartmoney")) {
      await page.goto(`${DESK}?tab=market&view=${v.key}`);
      await expect(page.getByTestId("md-head")).toBeVisible();
      await expect(page.getByTestId("desk-panel-fno"), v.key).toHaveCount(0);
    }
    await page.goto(`${DESK}?tab=market&view=smartmoney`);
    await expect(page.getByTestId("md-elsewhere")).toContainText("option chain and OI build-up live here only");
    await expect(page.getByTestId("desk-panel-smartmoney")).toBeVisible();
    await expect(page.getByTestId("desk-section-fno-title")).toHaveText("F&O · build-up, candidates, indices and option chain");
    await page.getByTestId("md-jump-fno").click();
    await expectAt(page, "smartmoney", { section: "fno" });
  });

  test("MD-4 Market Intelligence hosts the event list, the sector-rotation readout and the Events calendar", async ({ page }) => {
    await page.goto(`${DESK}?tab=market&view=intel`);
    await expect(page.getByTestId("desk-panel-intel")).toBeVisible();
    await expect(page.getByTestId("md-readout")).toBeVisible();
    await expect(page.getByTestId("desk-section-events-title")).toHaveText("Events calendar");
    await page.getByTestId("md-jump-events").click();
    await expectAt(page, "intel", { section: "events" });
  });

  test("MD-11 the readout: three strongest and three weakest by 1M vs the index, with the stated state rule", async ({ page }) => {
    await page.goto(`${DESK}?tab=market&view=intel`);
    const rows = page.getByTestId("md-readout-row");
    await expect(rows).toHaveCount(6);
    // Worked out from HEATMAP: 1M minus the index's +2.00, ranked; Auto Delta and Pharma Eps are 4th and 5th of 8.
    expect(await rows.evaluateAll((els) => els.map((e) => e.getAttribute("data-sector")))).toEqual(["Fin Alpha", "IT Beta", "Metal Gamma", "Energy Zeta", "FMCG Eta", "Realty Theta"]);
    expect(await rows.evaluateAll((els) => els.map((e) => e.getAttribute("data-state")))).toEqual(["leading", "weakening", "leading", "improving", "lagging", "lagging"]);
    const fin = page.locator('[data-testid="md-readout-row"][data-sector="Fin Alpha"]');
    await expect(fin.getByTestId("md-readout-rs")).toHaveText("+3.00 pts");
    await expect(fin.getByTestId("md-readout-d")).toHaveText("+0.50%");
    await expect(fin.getByTestId("md-readout-rose")).toHaveText("100%");
    await expect(fin.getByTestId("md-readout-state")).toHaveText("Leading");
    const realty = page.locator('[data-testid="md-readout-row"][data-sector="Realty Theta"]');
    await expect(realty.getByTestId("md-readout-rs")).toHaveText("−5.00 pts");
    await expect(page.locator('[data-testid="md-readout-row"][data-sector="FMCG Eta"]').getByTestId("md-readout-rose")).toHaveText("0%");
    await expect(page.getByTestId("md-readout")).toContainText("Nifty 50 · 2026-10-26");
    await page.getByTestId("md-readout-open").click();
    await expectAt(page, "sectors");
    await expect(page.getByTestId("desk-panel-sectors")).toBeVisible();
  });

  test("MD-12 the readout's failure and empty states say so; no rows are drawn", async ({ page }) => {
    await page.route("**/api/markets/sector-heatmap*", (route) => json(route, { detail: "boom" }, 500));
    await page.goto(`${DESK}?tab=market&view=intel`);
    await expect(page.getByTestId("md-readout-error")).toBeVisible({ timeout: 15_000 });
    await expect(page.getByTestId("md-readout-row")).toHaveCount(0);
    await page.unroute("**/api/markets/sector-heatmap*");
    await page.route("**/api/markets/sector-heatmap*", (route) => json(route, { ...HEATMAP, weighted_change: { d: null, w: null, m: null } }));
    await page.reload();
    await expect(page.getByTestId("md-readout-empty")).toBeVisible();
    await expect(page.getByTestId("md-readout-row")).toHaveCount(0);
  });

  test("MD-6 Sector Rotation hosts the heatmap", async ({ page }) => {
    await page.goto(`${DESK}?tab=market&view=sectors`);
    await expect(page.getByTestId("desk-panel-sectors").getByTestId("screen-tool-sector-heatmap")).toBeAttached({ timeout: 15_000 });
  });

  test("MD-7 Stock Research: the strip names ?sym=, opens its chain in Smart Money › F&O, and links the full chart workspace", async ({ page }) => {
    await page.goto(`${DESK}?tab=market&view=research&sym=INFY`);
    const strip = page.getByTestId("md-symbol");
    await expect(strip).toHaveAttribute("data-symbol", "INFY");
    await expect(strip).toHaveAttribute("data-from", "chosen");
    await expect(page.getByTestId("md-symbol-fullchart")).toHaveAttribute("href", "/v5/research?screen=charts&symbol=INFY");
    await page.getByTestId("md-symbol-chain").click();
    await expectAt(page, "smartmoney", { section: "fno", lab: "chain", lab_sym: "INFY" });
    await expect(page.getByTestId("desk-panel-fno")).toBeVisible();
  });

  test("MD-8 Stock Research without ?sym= names the scanner's first idea, as the chart does", async ({ page }) => {
    await page.goto(`${DESK}?tab=market&view=research`);
    const strip = page.getByTestId("md-symbol");
    await expect(strip).toHaveAttribute("data-symbol", "TESTBRK");
    await expect(strip).toHaveAttribute("data-from", "first-idea");
    await expect(strip).toContainText("the scanner’s first idea");
  });

  test("MD-9 Screener with its Chartink sources", async ({ page }) => {
    await page.goto(`${DESK}?tab=market&view=screener`);
    await expect(page.getByTestId("desk-panel-screener").getByTestId("screen-tool-screener")).toBeAttached({ timeout: 15_000 });
    await expect(page.getByTestId("desk-section-chartink-title")).toHaveText("Chartink sources");
    await page.getByTestId("md-jump-chartink").click();
    await expectAt(page, "screener", { section: "chartink" });
  });

  test("MD-10 watchlists and scorecard are Trade Desk's now: their Market Desk URLs open Trade Desk", async ({ page }) => {
    for (const v of ["watchlists", "scorecard"]) {
      await page.goto(`${DESK}?tab=market&view=${v}`);
      await expect.poll(() => params(page).get("tab"), v).toBe("trade");
      await expect(page.getByTestId("desk-tab-trade"), v).toHaveAttribute("aria-selected", "true");
      await expect(page.getByTestId("desk-view-watchlists")).toHaveCount(0);
      await expect(page.getByTestId("desk-view-scorecard")).toHaveCount(0);
    }
  });
});

test.describe("MOCK — not real data: Idea scorecard (fixture = staging's real body)", () => {
  test.beforeEach(() => { needsScorecard(); });

  test("SC-1 / SC-2 / SC-3 / SC-13 the verdict, the study and the disclaimer", async ({ page }) => {
    await deskApi(page);
    await page.goto(SCORECARD_URL as string);
    await expect(page.getByTestId("sc-verdict")).toHaveText("keep B0; the current ranking shows no measurable skill");
    await expect(page.getByTestId("sc-study-verdict")).toContainText("keep B0 (no arm met every pre-registered condition)");
    await expect(page.getByTestId("sc-decision")).toContainText("no arm adopted");
    await expect(page.getByTestId("sc-registration")).toHaveText("4c408401");
    await expect(page.getByTestId("sc-code")).toHaveText("4c408401+run_study(uncommitted)");
    await expect(page.getByTestId("sc-run-date")).toHaveText("27 Oct 2026");
    await expect(page.getByTestId("sc-signal-dates")).toHaveText("385");
    await expect(page.getByTestId("sc-outcome")).toHaveText("10-session excess return, entry at the next session's open");
    await expect(page.getByTestId("sc-disclaimer")).toHaveText(SCORECARD.disclaimer);
    await expect(page.getByTestId("sc-body")).not.toContainText(/beats the (random )?baseline|precision@/i);
  });

  test("SC-4 / SC-5 three splits, four arms each; B0's Δ is the baseline; negatives stay negative", async ({ page }) => {
    await deskApi(page);
    await page.goto(SCORECARD_URL as string);
    for (const sp of SCORECARD.splits as Array<{ name: string; arms: Array<{ arm: string }> }>) {
      await expect(page.getByTestId(`sc-split-${sp.name}`)).toBeVisible();
      await expect(page.getByTestId(`sc-split-${sp.name}`).locator("tbody tr")).toHaveCount(sp.arms.length);
    }
    await expect(page.getByTestId("sc-split-discovery")).toContainText("17 Feb 2025 – 11 Feb 2026");
    await expect(page.getByTestId("sc-split-test")).toContainText("16 Jun 2026 – 9 Oct 2026");
    // B0 test: IC 0.0075 (t 0.41), no Δ (baseline), top decile −0.99% net, hit 44.9%
    const b0 = row(page, "test", "B0");
    await expect(b0).toHaveAttribute("data-baseline", "true");
    await expect(b0.getByTestId("sc-ic")).toHaveText("+0.0075 · t 0.41");
    await expect(b0.getByTestId("sc-delta")).toHaveText("— baseline");
    await expect(b0.getByTestId("sc-net")).toHaveText("−0.99%");
    await expect(b0.getByTestId("sc-hit")).toHaveText("44.9%");
    // A3 discovery: a negative IC and a negative Δ, shown as they are
    const a3 = row(page, "discovery", "A3");
    await expect(a3.getByTestId("sc-ic")).toHaveText("−0.0039 · t −0.19");
    await expect(a3.getByTestId("sc-delta")).toHaveText("−0.0124 · t −3.24 · p 0.997");
    // A2 validation: Δ +0.0109, t 2.75, p 0.035
    await expect(row(page, "validation", "A2").getByTestId("sc-delta")).toHaveText("+0.0109 · t 2.75 · p 0.035");
    // A1 validation: a negative net return
    await expect(row(page, "validation", "A1").getByTestId("sc-net")).toHaveText("−0.06%");
  });

  test("SC-6 / SC-7 / SC-8 RS63, the per-arm checks and the sources with sha256 and present yes / no", async ({ page }) => {
    await deskApi(page);
    await page.goto(SCORECARD_URL as string);
    await expect(page.getByTestId("sc-rs63-status")).toHaveText("promising, awaiting its pre-registered confirmation");
    await expect(page.getByTestId("sc-rs63")).toContainText("RS63 vs Nifty 50 replaces the sector term");
    await expect(page.getByTestId("sc-rs63")).toContainText("not adopted");
    await expect(page.getByTestId("sc-rs63")).toContainText("docs/ai_research/P4_RS63_CONFIRMATION_PREREGISTRATION.md");
    for (const arm of ["A1", "A2", "A3"]) {
      await expect(page.getByTestId(`sc-check-${arm}`).getByTestId("sc-check-adopt")).toHaveText("not adopted");
    }
    await expect(page.getByTestId("sc-check-A2").locator('[data-check="a_validation"]')).toHaveAttribute("data-pass", "true");
    await expect(page.getByTestId("sc-check-A2").locator('[data-check="d_test_same_sign_both_regimes"]')).toHaveAttribute("data-pass", "false");
    const sources = page.getByTestId("sc-source");
    await expect(sources).toHaveCount(SCORECARD.sources.length);
    await expect(sources.nth(0)).toContainText("research/p4_adx_rs/results_20261027/result.json");
    await expect(sources.nth(0)).toHaveAttribute("data-present", "true");
    await expect(sources.nth(0).getByTestId("sc-source-sha")).toHaveText(`${SCORECARD.sources[0].sha256.slice(0, 12)}…`);
    await expect(sources.nth(0).getByTestId("sc-source-sha")).toHaveAttribute("title", SCORECARD.sources[0].sha256);
    await expect(sources.nth(0).getByTestId("sc-source-present")).toContainText("yes");
    for (let i = 1; i < SCORECARD.sources.length; i++) {
      await expect(sources.nth(i)).toHaveAttribute("data-present", "false");
      await expect(sources.nth(i).getByTestId("sc-source-present")).toContainText("no");
      await expect(sources.nth(i).getByTestId("sc-source-present")).toContainText("not readable here (FileNotFoundError)");
      await expect(sources.nth(i).getByTestId("sc-source-sha")).toHaveText("—");
    }
  });

  for (const code of ["scorecard_unavailable", "scorecard_out_of_date"]) {
    test(`SC-9 / SC-10 a 503 ${code} shows the route's own reason and no figures`, async ({ page }) => {
      const reason = code === "scorecard_unavailable"
        ? "research/p4_adx_rs/results_20261027/result.json is missing (FileNotFoundError)"
        : "the committed results no longer support the served verdict: arm A2 is adopted";
      await deskApi(page, (route) => json(route, { detail: { code, reason, study_id: "p4_adx_rs" } }, 503));
      await page.goto(SCORECARD_URL as string);
      const err = page.getByTestId("sc-error");
      await expect(err).toHaveAttribute("data-code", code);
      await expect(page.getByTestId("sc-error-reason")).toHaveText(reason);
      await expect(page.getByTestId("sc-error-code")).toHaveText(code);
      await expect(page.getByTestId("sc-body")).toHaveCount(0);
      await expect(page.getByTestId("sc-retry")).toHaveCount(0);
    });
  }

  test("SC-11 a 500 says it didn't load, offers Retry, and the retry shows the scorecard", async ({ page }) => {
    let fail = true;
    await deskApi(page, (route) => (fail ? json(route, { detail: "boom" }, 500) : json(route, SCORECARD)));
    await page.goto(SCORECARD_URL as string);
    await expect(page.getByTestId("sc-error")).toHaveAttribute("data-code", "error", { timeout: 15_000 });
    await expect(page.getByTestId("sc-error")).toContainText("The scorecard didn’t load");
    await expect(page.getByTestId("sc-body")).toHaveCount(0);
    fail = false;
    await page.getByTestId("sc-retry").click();
    await expect(page.getByTestId("sc-verdict")).toHaveText("keep B0; the current ranking shows no measurable skill");
  });

  test("SC-12 a body without splits or a verdict is a contract error, never an empty result", async ({ page }) => {
    const { splits: _s, ...noSplits } = SCORECARD;
    await deskApi(page, (route) => json(route, noSplits));
    await page.goto(SCORECARD_URL as string);
    await expect(page.getByTestId("sc-error")).toHaveAttribute("data-code", "contract");
    await expect(page.getByTestId("sc-error-reason")).toHaveText("The scorecard answer had no splits.");
    await page.unroute("**/api/desk/idea-scorecard");
    await page.route("**/api/desk/idea-scorecard", (route) => json(route, { ...SCORECARD, decision: { ...SCORECARD.decision, verdict: null } }));
    await page.reload();
    await expect(page.getByTestId("sc-error-reason")).toHaveText("The scorecard answer had no verdict.");
    await expect(page.getByTestId("sc-body")).toHaveCount(0);
  });
});

test.describe("MOCK — not real data: Market Desk · wording", () => {
  test("W-1 no pick / recommended / suggest in any Market Desk view's head or readout", async ({ page }) => {
    test.setTimeout(120_000);
    await deskApi(page);
    for (const v of VIEWS) {
      await page.goto(`${DESK}?tab=market&view=${v.key}`);
      await expect(page.getByTestId("md-head")).toBeVisible();
      expect(await page.getByTestId("md-head").innerText(), v.key).not.toMatch(BANNED);
    }
    await page.goto(`${DESK}?tab=market&view=intel`);
    await expect(page.getByTestId("md-readout-row").first()).toBeVisible();
    expect(await page.getByTestId("md-readout").innerText()).not.toMatch(BANNED);
  });

  test("W-1 (scorecard) no pick / recommended / suggest in the scorecard", async ({ page }) => {
    needsScorecard();
    await deskApi(page);
    await page.goto(SCORECARD_URL as string);
    await expect(page.getByTestId("sc-body")).toBeVisible();
    expect(await page.getByTestId("sc-body").innerText()).not.toMatch(BANNED);
  });
});

test.describe("MOCK — not real data: Market Desk · phone 390px", () => {
  test.use({ viewport: { width: 390, height: 844 } });

  test("P-1 no sideways page scroll on any of the five views", async ({ page }) => {
    test.setTimeout(120_000);
    await deskApi(page);
    for (const v of VIEWS) {
      await page.goto(`${DESK}?tab=market&view=${v.key}`);
      await expect(page.getByTestId("md-head"), v.key).toBeVisible();
      await page.waitForTimeout(300);
      await noSideScroll(page, v.key);
    }
  });

  test("P-1 (scorecard) no sideways page scroll; the split tables scroll inside their own box", async ({ page }) => {
    needsScorecard();
    await deskApi(page);
    await page.goto(SCORECARD_URL as string);
    await expect(page.getByTestId("sc-split-test")).toBeVisible();
    await noSideScroll(page, "scorecard");
    const box = await page.getByTestId("sc-split-test").locator(".cp-scroll").first().evaluate((el) => ({ sw: el.scrollWidth, cw: el.clientWidth }));
    expect(box.sw).toBeGreaterThan(box.cw);
  });
});
