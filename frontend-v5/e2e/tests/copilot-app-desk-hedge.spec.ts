/**
 * One-screen Copilot app (/v5/app) — Smart trading desk, Risk Desk › Portfolio hedge (Quick Hedge; screens/tradingdesk/tabs/risk-desk/
 * HedgeView.tsx, hedge-data.ts). Cases HG-1 … HG-10.
 *
 * MOCK — not real data. The POST /api/portfolio/quick-hedge answers are fixtures/quick-hedge-*.mock.json: produced by the real
 * backend code (services/quick_hedge: calculator, desk cost card) from an INVENTED portfolio (₹25 lakh, beta 1.0, R² 0.83) and an
 * INVENTED option chain; nothing here is market data. Expected text is worked out below from the fixture's numbers, not copied
 * from the screen. Production build, every /api mocked — see pw.copilot-app.config.ts.
 */
import { test, expect, type Page, type Route } from "@playwright/test";
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";
import { mockApi, mockSingleRoute } from "../helpers/api-mock";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const load = (name: string) => JSON.parse(fs.readFileSync(path.join(__dirname, "..", "fixtures", name), "utf-8"));

const HEDGE = "/v5/app/trader/desk?tab=risk&view=hedge";
const LIMITS = "/v5/app/trader/desk?tab=risk&view=limits";
const SLOW = { timeout: 15_000 };
const reply = (route: Route, body: unknown, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });

const OK = load("quick-hedge-ok.mock.json");
const inFmt = new Intl.NumberFormat("en-IN");
const inr = (n: number, signed = false) => `${n < 0 ? "−" : signed && n > 0 ? "+" : ""}₹${inFmt.format(Math.round(Math.abs(n)))}`;
const mode = (res: any, name: string) => res.modes.find((m: any) => m.mode === name);
const row = (m: any, move: number) => m.scenario_rows.find((r: any) => r.move_pct === move);

type Opts = { flag?: boolean; answer?: unknown; status?: number; calls?: Array<Record<string, unknown>> };

async function desk(page: Page, o: Opts = {}) {
  const calls = o.calls ?? [];
  await mockApi(page, "populated");
  await mockSingleRoute(page, "**/api/markets/home", "markets-home.json");
  await page.route("**/api/chat/sessions", (r) => reply(r, []));
  await page.route("**/api/move-odds/**", (r) => reply(r, { detail: "feature_not_enabled" }, 403));
  if (o.flag !== false) {
    const base = load("user-profile-onboarded.json");
    await page.route("**/api/auth/me", (r) => reply(r, { ...base, features: { ...(base.features ?? {}), portfolio_hedge: true } }));
  }
  await page.route("**/api/portfolio/quick-hedge", (r) => {
    calls.push(r.request().postDataJSON() as Record<string, unknown>);
    return reply(r, o.answer ?? OK, o.status ?? 200);
  });
  return calls;
}

async function noSideScroll(page: Page, where: string) {
  const o = await page.evaluate(() => {
    const sc = document.querySelector('[data-testid="copilot-scroll"]') as HTMLElement | null;
    return { doc: document.documentElement.scrollWidth - window.innerWidth, scroll: sc ? sc.scrollWidth - sc.clientWidth : 0 };
  });
  expect(o.doc, where).toBeLessThanOrEqual(1);
  expect(o.scroll, where).toBeLessThanOrEqual(1);
}

test.describe("MOCK — not real data: Risk Desk › Portfolio hedge", () => {
  test("HG-1 with the flag off the view is not offered, and its URL asks nothing", async ({ page }) => {
    const calls = await desk(page, { flag: false });
    await page.goto(LIMITS);
    await expect(page.getByTestId("desk-view-limits")).toBeVisible(SLOW);
    await expect(page.getByTestId("desk-view-hedge")).toHaveCount(0);
    await page.goto(HEDGE);
    await expect(page.getByTestId("hedge-off")).toContainText("not enabled for your account", SLOW);
    await expect(page.getByTestId("hedge-form")).toHaveCount(0);
    expect(calls).toEqual([]);
  });

  test("HG-2 with the flag on the view is offered last, opens from the switcher, and runs once with the defaults", async ({ page }) => {
    const calls = await desk(page);
    await page.goto(LIMITS);
    await expect(page.getByTestId("desk-view-hedge")).toBeVisible(SLOW);             // the switcher has rendered (evaluateAll does not wait)
    const keys = await page.getByTestId("desk-views").locator("button").evaluateAll((els) => els.map((e) => e.getAttribute("data-testid")));
    expect(keys).toEqual(["desk-view-limits", "desk-view-controls", "desk-view-log", "desk-view-hedge"]);
    await expect(page.getByTestId("desk-view-hedge")).toHaveText("Portfolio hedge");
    await page.getByTestId("desk-view-hedge").click();
    await expect(page).toHaveURL(/[?&]view=hedge(&|$)/);
    const panel = page.getByTestId("desk-panel-risk");
    await expect(panel.locator("h1")).toHaveCount(1);
    await expect(panel.getByTestId("hedge-choices")).toBeVisible(SLOW);
    expect(calls).toEqual([{ expected_fall_pct: 10, tenor: "1m", tolerance_pct: 5 }]);
    await expect(panel).toContainText("Risk Desk · Portfolio hedge");
    await expect(page.getByTestId("rd-paper-only")).toContainText("Nothing is sent to a broker");
  });

  test("HG-3 the figures are the server's: portfolio, size, the three choices and the Balanced scenario table", async ({ page }) => {
    await desk(page);
    await page.goto(HEDGE);
    await expect(page.getByTestId("hedge-choices")).toBeVisible(SLOW);
    const ex = OK.exposure, d = OK.data.portfolio;
    await expect(page.getByTestId("hedge-kpi-hedgeable-value")).toHaveText(inr(d.hedgeable_value_rs));
    await expect(page.getByTestId("hedge-kpi-beta-value")).toHaveText(d.beta.toFixed(2));
    await expect(page.getByTestId("hedge-kpi-fit-value")).toHaveText(`R² ${OK.confidence.r2.toFixed(2)}`);
    await expect(page.getByTestId("hedge-kpi-lots-value")).toHaveText(`${ex.executed_lots} of ${ex.required_lots.toFixed(2)}`);
    await expect(page.getByTestId("hedge-kpi-covered-value")).toHaveText(`${Math.round(ex.protected_pct)}%`);
    const bal = mode(OK, "balanced");
    const card = page.getByTestId("hedge-choice-balanced");
    await expect(card).toHaveAttribute("aria-pressed", "true");
    await expect(page.getByTestId("hedge-choice-balanced-what")).toContainText(`${bal.legs[0].strike.toLocaleString("en-IN")} put`);
    await expect(card).toContainText(`after a ${inr(bal.deductible_rs)} loss`);
    await expect(page.getByTestId("hedge-choice-balanced-cost")).toContainText(inr(bal.cost.total_rs));
    const t = page.getByTestId("hedge-scenarios");
    await expect(t).toHaveAttribute("data-mode", "balanced");
    await expect(t.locator("tbody tr")).toHaveCount(bal.scenario_rows.length);
    for (const move of [10, 0, -10]) {
      const r = row(bal, move), tr = page.getByTestId(`hedge-row-${move}`);
      await expect(tr).toContainText(inr(r.without_hedge_rs, true));
      await expect(tr).toContainText(inr(r.hedge_pnl_rs, true));
      await expect(tr).toContainText(inr(r.with_hedge_rs, true));
    }
    await expect(page.getByTestId("hedge-row--10")).toHaveAttribute("data-fear", "true");
    await expect(page.getByTestId("hedge-row-0")).toHaveAttribute("data-fear", "false");
  });

  test("HG-4 choosing another choice shows its own scenarios, and the put spread names its two legs", async ({ page }) => {
    await desk(page);
    await page.goto(HEDGE);
    await expect(page.getByTestId("hedge-choices")).toBeVisible(SLOW);
    await page.getByTestId("hedge-choice-maximum").click();
    await expect(page.getByTestId("hedge-scenarios")).toHaveAttribute("data-mode", "maximum");
    await expect(page.getByTestId("hedge-choice-maximum")).toHaveAttribute("aria-pressed", "true");
    await expect(page.getByTestId("hedge-choice-balanced")).toHaveAttribute("aria-pressed", "false");
    const low = mode(OK, "lowest_cost");
    await expect(page.getByTestId("hedge-choice-lowest_cost-what")).toContainText(`${low.legs[0].strike.toLocaleString("en-IN")} put, sell the ${low.legs[1].strike.toLocaleString("en-IN")} put`);
    await page.getByTestId("hedge-choice-lowest_cost").click();
    await expect(page.getByTestId("hedge-scenarios")).toHaveAttribute("data-mode", "lowest_cost");
    await expect(page.getByTestId("hedge-row--20")).toContainText(inr(row(low, -20).hedge_pnl_rs, true));
  });

  test("HG-5 changing the inputs asks the server with exactly those inputs", async ({ page }) => {
    const calls = await desk(page);
    await page.goto(HEDGE);
    await expect(page.getByTestId("hedge-choices")).toBeVisible(SLOW);
    await page.getByTestId("hedge-fall-15").click();
    await page.getByTestId("hedge-tenor-2w").click();
    await page.getByTestId("hedge-tol-rs").click();
    await page.getByTestId("hedge-tol-input").fill("100000");
    await page.getByTestId("hedge-run").click();
    await expect.poll(() => calls.length, SLOW).toBe(2);
    expect(calls[1]).toEqual({ expected_fall_pct: 15, tenor: "2w", tolerance_rs: 100000 });
  });

  test("HG-6 an input that cannot be right is refused on the screen and asks nothing", async ({ page }) => {
    const calls = await desk(page);
    await page.goto(HEDGE);
    await expect(page.getByTestId("hedge-choices")).toBeVisible(SLOW);
    await page.getByTestId("hedge-tol-input").fill("abc");
    await page.getByTestId("hedge-run").click();
    await expect(page.getByTestId("hedge-input-error")).toContainText("between 0 and 100 percent");
    await page.getByTestId("hedge-tol-input").fill("5");
    await page.getByTestId("hedge-fall-input").fill("80");
    await page.getByTestId("hedge-run").click();
    await expect(page.getByTestId("hedge-input-error")).toContainText("between 1 and 50 percent");
    expect(calls.length).toBe(1);                                          // only the automatic first run
  });

  test("HG-7 a portfolio under one lot is told so, with no choices and no table", async ({ page }) => {
    await desk(page, { answer: load("quick-hedge-small.mock.json") });
    await page.goto(HEDGE);
    await expect(page.getByTestId("hedge-reason-smaller_than_one_lot")).toContainText("smaller than one efficient index-option hedge lot", SLOW);
    await expect(page.getByTestId("hedge-choices")).toHaveCount(0);
    await expect(page.getByTestId("hedge-scenarios")).toHaveCount(0);
    await expect(page.getByTestId("hedge-kpi-hedgeable")).toBeVisible();
  });

  test("HG-8 a poor fit to Nifty shows the scenarios but says the hedge cannot be placed", async ({ page }) => {
    await desk(page, { answer: load("quick-hedge-poorfit.mock.json") });
    await page.goto(HEDGE);
    await expect(page.getByTestId("hedge-scenarios")).toBeVisible(SLOW);
    await expect(page.getByTestId("hedge-kpi-fit-value")).toHaveText("R² 0.18");
    await expect(page.getByTestId("hedge-no-place")).toContainText("poor hedge");
  });

  test("HG-9 missing market data is said as the reason, never as a hedge; a 403 is 'not enabled', not an outage", async ({ page }) => {
    await desk(page, { answer: load("quick-hedge-down.mock.json") });
    await page.goto(HEDGE);
    await expect(page.getByTestId("hedge-reason-market_data_unavailable")).toContainText("data platform is unavailable", SLOW);
    await expect(page.getByTestId("hedge-choices")).toHaveCount(0);
    await expect(page.getByTestId("hedge-reason-missing_spot")).toHaveCount(0);
    const p2 = await page.context().newPage();
    await desk(p2, { answer: { detail: "feature_not_enabled" }, status: 403 });
    await p2.goto(HEDGE);
    await expect(p2.getByTestId("hedge-error")).toHaveText("Portfolio hedge is not enabled for your account.", SLOW);
  });

  test("HG-10 the dates, the disclosures and the paper-only wording are on the screen", async ({ page }) => {
    await desk(page);
    await page.goto(HEDGE);
    await expect(page.getByTestId("hedge-dates")).toContainText(`Holdings as of ${OK.data.portfolio.as_of}`, SLOW);
    await expect(page.getByTestId("hedge-dates")).toContainText(`Nifty options as of ${OK.data.market.as_of}`);
    await expect(page.getByTestId("hedge-disclosures")).toContainText("not guaranteed future performance");
    await expect(page.getByTestId("hedge-disclosures")).toContainText("does not eliminate");
    await expect(page.getByTestId("hedge-estimate-note")).toContainText("Estimated scenario, not guaranteed future performance");
    await expect(page.getByTestId("hedge-place-note")).toContainText("not part of this release");
  });
});

test.describe("MOCK — not real data: Portfolio hedge · phone 390px", () => {
  test.use({ viewport: { width: 390, height: 844 } });

  test("HG-11 no sideways scroll with the table and the three choices", async ({ page }) => {
    await desk(page);
    await page.goto(HEDGE);
    await expect(page.getByTestId("hedge-scenarios")).toBeVisible(SLOW);
    await page.waitForTimeout(400);
    await noSideScroll(page, "hedge view");
    await page.getByTestId("hedge-choice-lowest_cost").click();
    await page.waitForTimeout(300);
    await noSideScroll(page, "hedge view, put spread");
  });
});
