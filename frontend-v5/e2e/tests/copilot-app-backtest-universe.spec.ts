/**
 * Strategy builder backtest — the universe's survivorship status on the result (Phase 4.2; TC-LU-12 of
 * test_reports/p4_research_hardening_TESTCASES.md). The page is the original v5 builder mounted in the shell at
 * /v5/app/trader/strategy (screens/desk/StrategyBuilder.tsx).
 *
 * MOCK — not real data. Every /api reply is written here or read from e2e/fixtures/strategy-backtest-universe.json, whose
 * universe fields are the backend's own texts (backend/tests/test_liquid_universe.py asserts they still match
 * services/strategy_engine/market_data.SURVIVORSHIP_WARNING and liquid_universe.rule()). The backtest reply follows the
 * universe of the strategy the page last saved, the way the engine reports the basis it used.
 */
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";
import { test, expect, type Page, type Route } from "@playwright/test";
import { mockApi } from "../helpers/api-mock";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const FX = JSON.parse(fs.readFileSync(path.join(__dirname, "..", "fixtures", "strategy-backtest-universe.json"), "utf-8"));
const URL_ = "/v5/app/trader/strategy";
const ID = "11111111-2222-3333-4444-555555555555";
const json = (route: Route, body: unknown, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });

const TEMPLATES = { templates: [{ key: "fixture_trend", name: "Fixture trend", description: "MOCK template.",
  definition: { version: "1", asset_class: "STOCK", name: "Fixture trend", entry: { all_of: [{ feature: "rsi14", op: ">", value: 55 }] },
    exit: { stoploss_pct: 5, target_rr: 2, max_hold_days: 20 }, ranking: { by: "accumulation_score", order: "desc", limit: 3 }, rebalance: "daily" } }] };
const SCREEN = { candidates: [{ symbol: "RELIANCE", close: 1200, rsi14: 61, accumulation_score: 70, return_20d_pct: 3 }], count: 1,
  as_of_date: "2026-10-20", ranked_by: "accumulation_score", score_basis: "MOCK" };
const STORED = { strategy_id: ID, stored: false, schema_version: 1, initial_capital: 1000000, commission_pct: 0.05, pyramiding: 0,
  short_margin_pct: 100, symbols: [], symbols_source: "unavailable", updated_at: null, not_enforced_by_engine: ["pyramiding", "short_margin_pct"] };

interface St { saved: Array<{ method: string; universe: { type: string; ref: string } }>; runs: number }

async function setup(page: Page): Promise<St> {
  const st: St = { saved: [], runs: 0 };
  await mockApi(page, "populated");
  await page.route("**/api/strategy-builder/templates", (r) => json(r, TEMPLATES));
  await page.route("**/api/strategy-builder/universe-catalog", (r) => json(r, FX.catalog));
  await page.route("**/api/strategy-builder/universes*", (r) => json(r, { universes: [], count: 0 }));
  await page.route("**/api/strategy-builder/screen", (r) => json(r, SCREEN));
  await page.route("**/api/strategy-builder/config-schema", (r) => json(r, { detail: "MOCK: not served, the page uses its fallback" }, 404));
  await page.route("**/api/strategy-builder/strategies**", async (r) => {
    const req = r.request();
    const p = new URL(req.url()).pathname;
    if (p.endsWith("/config")) return json(r, { ...STORED, ...(req.method() === "PUT" ? req.postDataJSON() : {}) });
    if (p.endsWith("/backtest")) {
      st.runs += 1;
      const last = st.saved[st.saved.length - 1];
      return json(r, last?.universe.type === "index" ? FX.index_run : FX.liquid_run);
    }
    const body = req.postDataJSON() as { definition?: { universe?: { type: string; ref: string } } };
    st.saved.push({ method: req.method(), universe: body.definition?.universe ?? { type: "?", ref: "?" } });
    return json(r, { id: ID, name: "Fixture trend" });
  });
  return st;
}

/** Strategy → Screen → Bot details → Backtest, from the universe already chosen. */
async function toBacktest(page: Page) {
  await page.getByRole("button", { name: "Strategy →" }).click();
  await page.getByTestId("template-fixture_trend").click();
  await page.getByRole("button", { name: "Screen →" }).click();
  await page.getByTestId("run-screen").click();
  await expect(page.getByTestId("screen-results")).toBeVisible();
  await page.getByRole("button", { name: "Bot details →" }).click();
  await page.getByRole("button", { name: "Backtest →" }).click();
}

test.describe("Backtest universe — survivorship status", () => {
  test("the liquid point-in-time universe is first and chosen by default, and its run says it is point in time", async ({ page }) => {
    const st = await setup(page);
    await page.goto(URL_);
    const liquid = page.getByTestId("universe-card-LIQUID_EQ");
    await expect(liquid).toContainText("All liquid NSE stocks (point-in-time)");
    await expect(page.locator('[data-testid^="universe-card-"]').first()).toHaveAttribute("data-testid", "universe-card-LIQUID_EQ");
    await expect(liquid).toHaveAttribute("aria-pressed", "true");
    await expect(page.getByTestId("universe-card-NIFTY500")).toHaveAttribute("aria-pressed", "false");
    await toBacktest(page);
    await expect(page.getByTestId("backtest-universe-pit")).toBeVisible();
    await expect(page.getByTestId("backtest-survivorship-warning")).toHaveCount(0);
    await page.getByTestId("run-backtest").click();
    await expect(page.getByTestId("backtest-results")).toBeVisible();
    expect(st.saved[0].universe).toEqual({ type: "market", ref: "LIQUID_EQ" });
    await expect(page.getByTestId("backtest-universe-pit")).toContainText("liquid-eq-v1");
    await expect(page.getByTestId("backtest-universe-pit")).toContainText("no survivorship bias");
    await expect(page.getByTestId("backtest-survivorship-warning")).toHaveCount(0);
  });

  test("an index universe's run shows the engine's survivorship warning; switching to the liquid universe clears it", async ({ page }) => {
    const st = await setup(page);
    await page.goto(URL_);
    await page.getByTestId("universe-card-NIFTY500").click();
    await expect(page.getByTestId("universe-card-NIFTY500")).toHaveAttribute("aria-pressed", "true");
    await toBacktest(page);
    // before a run: the choice alone is warned
    await expect(page.getByTestId("backtest-survivorship-warning")).toContainText("Survivorship bias");
    await page.getByTestId("run-backtest").click();
    await expect(page.getByTestId("backtest-results")).toBeVisible();
    expect(st.saved[0].universe).toEqual({ type: "index", ref: "NIFTY500" });
    const warn = page.getByTestId("backtest-survivorship-warning");
    await expect(warn).toContainText(FX.index_run.metrics.universe_warning);
    await expect(warn).toHaveAttribute("role", "alert");
    await expect(page.getByTestId("backtest-universe-pit")).toHaveCount(0);
    // back to the universe step, choose the liquid universe, run again
    await page.getByTestId("step-tab-universe").click();
    await page.getByTestId("universe-card-LIQUID_EQ").click();
    await page.getByTestId("step-tab-backtest").click();
    await page.getByTestId("run-backtest").click();
    await expect.poll(() => st.runs).toBe(2);
    expect(st.saved[st.saved.length - 1].universe).toEqual({ type: "market", ref: "LIQUID_EQ" });
    await expect(page.getByTestId("backtest-universe-pit")).toContainText("liquid-eq-v1");
    await expect(page.getByTestId("backtest-survivorship-warning")).toHaveCount(0);
  });
});
