/**
 * One-screen Copilot app (/v5/app) — the portfolio screens: Portfolio analysis,
 * Recommendations, Action plan and Portfolio ledger.
 *
 * Covers the blocks wired after copilot-app-screens.spec.ts was written: the
 * target mix, plan outcomes, step status and rebuild, the ledger's source,
 * statements, transactions, SIPs and corrections, and the company / fund house
 * icons. Each block is checked with data, empty and failed.
 *
 * MOCK — not real data: every response is a fixture (e2e/fixtures/
 * copilot-portfolio-*.json) or an inline payload shaped like the real
 * endpoint, with invented names and figures. Expected values are worked out
 * from the payload beside each assertion, not copied from the screen.
 * Mocked APIs, production build — see pw.copilot-app.config.ts.
 */
import { test, expect, type Page, type Request } from "@playwright/test";
import fs from "fs";
import path from "path";
import { mockApi, mockSingleRoute } from "../helpers/api-mock";

const APP = "/v5/app";
const FX = path.join(process.cwd(), "e2e", "fixtures");
const load = (name: string) => JSON.parse(fs.readFileSync(path.join(FX, name), "utf-8"));

/** A failed request is retried before the screen gives up, so error states take a few seconds. */
const SLOW = { timeout: 15_000 };

const json = (page: Page, pattern: string | RegExp, body: unknown, status = 200) =>
  page.route(pattern, (route) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) }));

const fail = (page: Page, pattern: string | RegExp) => json(page, pattern, { detail: "fixture failure" }, 500);

// Real shape of GET /api/onboarding/state (backend/routes/onboarding_gmail.py); no month-end values, so the
// ledger's month chart reads the snapshot trend.
const ONBOARDING_STATE = { onboarding_completed: true, pan_on_file: true, gmail_connected: false, cas_statement_period: "Aug/2026", cas_portfolio_value_rs: 1000000, cas_statement_date: "31-Aug-2026" };

// Real shape of GET /api/portfolio/capital-gains-statement with nothing sold in the year.
const NO_SALES = {
  header: { fy: "FY 2026-27" },
  sections: {
    A_stcg_equity: { rows: [], total: { gain_rs: 0 } },
    B_ltcg_equity: { rows: [], total: { gain_rs: 0 } },
  },
  estimated_tax_rs: 0,
};

// Real shape of GET /api/portfolio/compare when there is no earlier snapshot.
const NO_EARLIER_SNAPSHOT = { new: {}, old: null, diff: { from_date: null, to_date: "2026-08-31", value_delta: null, value_pct_change: null, health_delta: null, holdings_added: [], holdings_removed: [] } };

/** Every /api call the four screens make, answered with the synthetic portfolio. */
async function portfolio(page: Page) {
  await mockApi(page, "populated");
  await mockSingleRoute(page, "**/api/markets/home", "markets-home.json");
  await page.route("**/api/chat/sessions", (route) => route.fulfill({ status: 200, contentType: "application/json", body: "[]" }));
  // Analysis
  await mockSingleRoute(page, "**/api/portfolio/holdings-enriched*", "copilot-portfolio-holdings.json");
  await mockSingleRoute(page, "**/api/portfolio/composition*", "copilot-portfolio-composition.json");
  await json(page, "**/api/user/risk-profile", { risk_profile: { score: 52, category: "Moderate", completed_at: "2026-06-01T10:00:00Z" } });
  await mockSingleRoute(page, "**/api/portfolio/exposure/fund-overlap/matrix*", "fund-overlap-matrix.json");
  await mockSingleRoute(page, "**/api/portfolio/exposure/remediation*", "exposure-remediation.json");
  await mockSingleRoute(page, "**/api/dashboards/performance*", "dashboards-performance-rich.json");
  await mockSingleRoute(page, "**/api/portfolio/value-history*", "portfolio-value-history.json");
  await mockSingleRoute(page, "**/api/portfolio/analytics*", "portfolio-analytics.json");
  // Recommendations and Action plan
  await mockSingleRoute(page, "**/api/plans/active", "copilot-portfolio-plan.json");
  await mockSingleRoute(page, "**/api/plans/history*", "copilot-portfolio-plan-history.json");
  await mockSingleRoute(page, "**/api/plans/active/health-projection", "copilot-portfolio-health-projection.json");
  await mockSingleRoute(page, "**/api/portfolio/trend*", "copilot-portfolio-trend.json");
  // Ledger
  await mockSingleRoute(page, "**/api/portfolio/holdings", "copilot-portfolio-holdings-raw.json");
  await mockSingleRoute(page, "**/api/portfolio/cas-snapshots*", "copilot-portfolio-statements.json");
  await mockSingleRoute(page, "**/api/portfolio/transactions*", "copilot-portfolio-transactions.json");
  await mockSingleRoute(page, "**/api/portfolio/sips", "copilot-portfolio-sips.json");
  await json(page, "**/api/portfolio/capital-gains-statement*", NO_SALES);
  await json(page, "**/api/portfolio/compare*", NO_EARLIER_SNAPSHOT);
  await json(page, "**/api/onboarding/state", ONBOARDING_STATE);
}

/** Captures what a screen hands to the Copilot. Returns the sent messages. */
async function mockAsk(page: Page): Promise<string[]> {
  const sent: string[] = [];
  await page.route("**/api/chat/sessions", (route) =>
    route.request().method() === "POST"
      ? route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ session_id: "asked1" }) })
      : route.fulfill({ status: 200, contentType: "application/json", body: "[]" }));
  await page.route("**/api/chat/messages*", (route) => route.fulfill({ status: 200, contentType: "application/json", body: "[]" }));
  await page.route("**/api/chat/stream", (route) => {
    sent.push((route.request().postDataJSON() as { message: string }).message);
    return route.fulfill({ status: 200, contentType: "text/event-stream", body: `data: ${JSON.stringify({ type: "done", content: "ok" })}\n\n` });
  });
  return sent;
}

const icon = (kind: "stock" | "fund-house") => `[data-testid="entity-icon"][data-kind="${kind}"]`;

test.describe("Portfolio analysis — target mix and icons", () => {
  test.beforeEach(async ({ page }) => { await portfolio(page); });

  test("the asset-class tab sets what is held against the target for the risk category", async ({ page }) => {
    const sent = await mockAsk(page);
    await page.goto(`${APP}/tool/analysis`);
    await page.getByTestId("analysis-tab-assets").click();
    const target = page.getByTestId("analysis-target");
    await expect(target).toBeVisible();
    await expect(page.getByTestId("analysis-target-not-connected")).toHaveCount(0);
    // risk profile: Moderate → target 50 / 30 / 10 / 10 (hooks/use-risk-profile TARGET_ALLOCATION)
    await expect(page.getByTestId("analysis-target-category")).toHaveText("Moderate");
    // copilot-portfolio-composition.json: Equity 66, Hybrid 15, Gold 10, Debt 9, no Cash
    await expect(page.getByTestId("analysis-target-equity-actual")).toHaveText("66.0%");
    await expect(page.getByTestId("analysis-target-equity-target")).toHaveText("50%");
    await expect(page.getByTestId("analysis-target-equity-drift")).toHaveText("+16.0 pts");
    await expect(page.getByTestId("analysis-target-debt-actual")).toHaveText("9.0%");
    await expect(page.getByTestId("analysis-target-debt-target")).toHaveText("30%");
    await expect(page.getByTestId("analysis-target-debt-drift")).toHaveText("−21.0 pts");
    await expect(page.getByTestId("analysis-target-gold-drift")).toHaveText("0.0 pts");
    // a class the user holds none of is 0% held, not missing
    await expect(page.getByTestId("analysis-target-cash-actual")).toHaveText("0.0%");
    await expect(page.getByTestId("analysis-target-cash-drift")).toHaveText("−10.0 pts");
    // hybrid is outside the four-class target: listed, with no target and no drift
    await expect(page.getByTestId("analysis-target-hybrid-actual")).toHaveText("15.0%");
    await expect(page.getByTestId("analysis-target-hybrid-target")).toHaveText("—");
    await expect(page.getByTestId("analysis-target-hybrid-drift")).toHaveText("—");
    await expect(page.getByTestId("analysis-target-outside")).toHaveText("Hybrid");
    // the class furthest from its target: debt, 21 points under
    await expect(page.getByTestId("analysis-target-headline")).toHaveText("Debt is 21.0 points below the target.");
    await expect(target.getByTestId("analysis-target-class")).toHaveText(["Equity", "Debt", "Gold", "Cash", "Hybrid"]);

    await target.getByRole("row").filter({ hasText: "Equity" }).click();
    await expect.poll(() => sent.length).toBe(1);
    expect(sent[0]).toContain("66.0%");
    expect(sent[0]).toContain("50%");
    expect(sent[0]).toContain("Moderate");
  });

  test("target mix: no risk profile, an unknown category and a failed request each say so", async ({ page }) => {
    await json(page, "**/api/user/risk-profile", { risk_profile: null });
    await page.goto(`${APP}/tool/analysis`);
    await page.getByTestId("analysis-tab-assets").click();
    await expect(page.getByTestId("analysis-target-empty")).toContainText("No target mix yet");
    await expect(page.getByTestId("analysis-target-empty").getByRole("button", { name: "Set up risk profile" })).toBeVisible();
    await expect(page.getByTestId("analysis-target")).toHaveCount(0);

    await json(page, "**/api/user/risk-profile", { risk_profile: { score: 10, category: "Speculative" } });
    await page.reload();
    await page.getByTestId("analysis-tab-assets").click();
    await expect(page.getByTestId("analysis-target-unmapped")).toContainText("Speculative");
    await expect(page.getByTestId("analysis-target")).toHaveCount(0);

    await fail(page, "**/api/user/risk-profile");
    await page.reload();
    await page.getByTestId("analysis-tab-assets").click();
    await expect(page.getByTestId("analysis-table-assets").getByRole("alert")).toContainText("Your target mix didn’t load", SLOW);
    await expect(page.getByTestId("analysis-target")).toHaveCount(0);
    // the asset-class table above it is unaffected
    await expect(page.getByTestId("analysis-asset-name")).toHaveCount(4);
  });

  test("company rows carry the company icon and fund rows the fund house icon", async ({ page }) => {
    // Shape of GET /api/portfolio/exposure/remediation; the first two contributors are holdings of the fixture portfolio.
    await json(page, "**/api/portfolio/exposure/remediation*", {
      recommendations: [{
        id: "fix-trim", action_kind: "trim_position", title: "Trim the largest position", why: "One holding dominates.", action: "Move part of it.",
        amount_rs: 50000, annual_saving_rs: null, leverage_score: 80, before_after: [], redeploy_to: "SBI Fixture Midcap Fund - Regular Growth", caveats: [],
        contributors: [
          { name: "Fixture Bank Ltd", pct_of_exposure: 60, value_rs: 200000 },
          { name: "Axis Fixture Bluechip Fund - Direct Growth", pct_of_exposure: 40, value_rs: 100000 },
          { name: "Not One Of The Holdings", pct_of_exposure: 0, value_rs: 0 },
        ],
      }],
      total_value: 1000000, empty: false,
    });
    await page.goto(`${APP}/tool/analysis`);

    // Companies (concentration.json): one company icon per row
    await page.getByTestId("analysis-tab-companies").click();
    const companies = page.getByTestId("analysis-table-companies");
    const companyCount = await companies.getByTestId("analysis-company-name").count();
    expect(companyCount).toBeGreaterThan(0);
    await expect(companies.locator(icon("stock"))).toHaveCount(companyCount);
    await expect(companies.locator(icon("fund-house"))).toHaveCount(0);

    // Fund houses: one fund house icon per row
    await page.getByTestId("analysis-tab-amc").click();
    const amc = page.getByTestId("analysis-table-amc");
    const amcCount = await amc.getByTestId("analysis-amc-name").count();
    expect(amcCount).toBeGreaterThan(0);
    await expect(amc.locator(icon("fund-house"))).toHaveCount(amcCount);

    // Funds: the fixture portfolio holds two mutual funds and one ETF
    await page.getByTestId("analysis-tab-funds").click();
    const funds = page.getByTestId("analysis-table-funds");
    await expect(funds.getByTestId("analysis-fund-name")).toHaveCount(3);
    await expect(funds.locator(icon("fund-house"))).toHaveCount(3);
    await expect(funds.locator(`${icon("fund-house")}[data-key="Axis"]`)).toHaveCount(1);
    await expect(funds.locator(`${icon("fund-house")}[data-key="Nippon India"]`)).toHaveCount(1);

    // Sectors name no stock or fund: no icon
    await page.getByTestId("analysis-tab-sectors").click();
    await expect(page.getByTestId("analysis-table-sectors").locator('[data-testid="entity-icon"]')).toHaveCount(0);

    // Overlap: both funds of each pair (fund-overlap-matrix.json has three pairs), and the stocks they share
    await page.getByTestId("analysis-section-tab-concentration").click();
    const pairs = page.getByTestId("analysis-overlap-pair");
    await expect(pairs).toHaveCount(3);
    await expect(pairs.first().locator(icon("fund-house"))).toHaveCount(2);
    const shared = pairs.first().getByTestId("analysis-overlap-shared");
    await expect(shared.first().locator(icon("stock"))).toHaveCount(1);

    // What to fix: a stock, a fund, and a name that is not a holding (no icon)
    await page.getByTestId("analysis-section-tab-fix").click();
    const drivers = page.getByTestId("analysis-remediation-contributor");
    await expect(drivers).toHaveCount(3);
    await expect(drivers.nth(0).locator(`${icon("stock")}[data-key="FIXBANK"]`)).toHaveCount(1);
    await expect(drivers.nth(1).locator(`${icon("fund-house")}[data-key="Axis"]`)).toHaveCount(1);
    await expect(drivers.nth(2).locator('[data-testid="entity-icon"]')).toHaveCount(0);
  });
});

test.describe("Recommendations — the original page's figures, step status, rebuild", () => {
  test.beforeEach(async ({ page }) => { await portfolio(page); });

  test("filter counts, badges, tax breakdown, deferral, confidence tier and icons ← plans/active", async ({ page }) => {
    await page.goto(`${APP}/tool/recommend`);
    // copilot-portfolio-plan.json: 2 pending + 1 in progress are open; 1 completed and 1 skipped are not
    await expect(page.getByTestId("recommend-count")).toHaveText("Three");
    await expect(page.getByTestId("recommend-card")).toHaveCount(3);
    await expect(page.getByTestId("recommend-tier")).toHaveText("Risk-based plan · 70 of 100");
    await expect(page.getByTestId("recommend-read")).toContainText("based on your risk profile only"); // gate_flags.requires_goal
    // groups: TRIM and EXIT reduce, ADD adds, nothing to hold
    await expect(page.getByTestId("recommend-filter-tab-all")).toHaveText("All · 3");
    await expect(page.getByTestId("recommend-filter-tab-reduce")).toHaveText("Reduce · 2");
    await expect(page.getByTestId("recommend-filter-tab-add")).toHaveText("Add · 1");
    await expect(page.getByTestId("recommend-filter-tab-hold")).toHaveText("Hold or switch · 0");

    const trim = page.getByTestId("recommend-card").nth(0);
    await expect(trim.getByTestId("recommend-card-title")).toHaveText("Trim Axis Fixture Bluechip Fund - Direct Growth");
    await expect(trim.getByTestId("recommend-card-amount")).toHaveText("₹1.20 L");
    await expect(trim.getByTestId("recommend-card-verb")).toHaveText("TRIM");
    await expect(trim.getByTestId("recommend-card-severity")).toHaveText("Mismatch");
    await expect(trim.getByTestId("recommend-card-execution")).toHaveText("Stagger");
    // tax_impact: liability 1200, stcg 3000, ltcg 9600, exit load 150, held 412 days
    await expect(trim.getByTestId("recommend-card-tax")).toHaveText("Tax ₹1,200 · short-term gain ₹3,000 · long-term gain ₹9,600 · exit load ₹150 · held 412 days");
    await expect(trim.getByTestId("recommend-card-effect")).toHaveText("Score +3.5 pts · risk lower");
    await expect(trim.locator(`${icon("fund-house")}[data-key="Axis"]`)).toHaveCount(1);

    const add = page.getByTestId("recommend-card").nth(1);
    await expect(add.getByTestId("recommend-card-title")).toHaveText("Add Fixture Steel Ltd");
    await expect(add.getByTestId("recommend-card-execution")).toHaveText("Redirect new money");
    await expect(add.getByTestId("recommend-card-tax")).toHaveText("Tax not estimated");
    // the step names a stock; its symbol comes from the user's holdings
    await expect(add.locator(`${icon("stock")}[data-key="FIXSTEEL"]`)).toHaveCount(1);

    // the exit carries no asset type: the fund house icon comes from the matching holding
    const exit = page.getByTestId("recommend-card").nth(2);
    await expect(exit.getByTestId("recommend-card-title")).toHaveText("Exit SBI Fixture Midcap Fund - Regular Growth");
    await expect(exit.locator(`${icon("fund-house")}[data-key="SBI"]`)).toHaveCount(1);
    await expect(exit.getByTestId("recommend-card-deferred")).toHaveText("Flagged, not for now — Exit load applies until 30 Nov 2026.");
    // a deferred step cannot be decided or marked done, only declined or moved back
    await expect(exit.getByTestId("step-done")).toHaveCount(0);
    await expect(exit.getByTestId("step-decline")).toBeVisible();

    // plan-level tiles: tax 1200 with half the exits estimated, 2,70,000 freed; projection 64.5 → 70
    await expect(page.getByTestId("recommend-tax")).toHaveText("₹1,200");
    await expect(page.getByTestId("recommend-freed")).toHaveText("₹2.70 L");
    await expect(page.getByTestId("recommend-volatility")).toHaveText("14.2% → 13.1%");
    await expect(page.getByTestId("recommend-cost")).toHaveText("0.92% → 0.71%");

    await page.getByTestId("recommend-filter-tab-add").click();
    await expect(page.getByTestId("recommend-card")).toHaveCount(1);
    await expect(page.getByTestId("recommend-card-title")).toHaveText("Add Fixture Steel Ltd");
    await page.getByTestId("recommend-filter-tab-hold").click();
    await expect(page.getByTestId("recommend-card")).toHaveCount(0);
    await expect(page.getByTestId("recommend-filter-empty")).toBeVisible();
    await expect(page.getByTestId("recommend-count")).toHaveText("Three"); // the headline counts every open step
  });

  test("marking a step done asks first, sends the status the backend accepts, and the list updates", async ({ page }) => {
    const patches: Request[] = [];
    let done = false;
    await page.route("**/api/plans/active", (route) =>
      route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(load(done ? "copilot-portfolio-plan-step-done.json" : "copilot-portfolio-plan.json")) }));
    await page.route("**/api/plans/*/actions/*", (route) => {
      patches.push(route.request());
      done = true;
      // backend/routes/plans.py :: update_action_status answers { plan, message }
      return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ plan: load("copilot-portfolio-plan-step-done.json").plan, message: "ok" }) });
    });
    await page.goto(`${APP}/tool/recommend`);
    const trim = page.getByTestId("recommend-card").nth(0);
    await trim.getByTestId("step-done").click();
    // nothing is sent until the user confirms
    await expect(trim.getByTestId("step-confirm")).toContainText("Nivesh places no order");
    expect(patches).toHaveLength(0);
    await trim.getByTestId("step-confirm-cancel").click();
    await expect(trim.getByTestId("step-confirm")).toHaveCount(0);
    expect(patches).toHaveLength(0);

    await trim.getByTestId("step-done").click();
    await trim.getByTestId("step-note").fill("Redeemed through my broker");
    await trim.getByTestId("step-confirm-yes").click();
    await expect(page.getByTestId("recommend-count")).toHaveText("Two");
    expect(patches).toHaveLength(1);
    expect(patches[0].method()).toBe("PATCH");
    // the backend finds the step by action_id ("act_fix_1"), not by the display id ("rec_fix_1")
    expect(new URL(patches[0].url()).pathname).toBe("/api/plans/plan_fixture_v2/actions/act_fix_1");
    expect(patches[0].postDataJSON()).toEqual({ status: "COMPLETED", completion_note: "Redeemed through my broker" });
    await expect(page.getByTestId("recommend-card-title").first()).toHaveText("Add Fixture Steel Ltd");
  });

  test("a status change that fails says so and leaves the step where it was", async ({ page }) => {
    await fail(page, "**/api/plans/*/actions/*");
    await page.goto(`${APP}/tool/recommend`);
    const add = page.getByTestId("recommend-card").nth(1);
    await add.getByTestId("step-decline").click();
    await add.getByTestId("step-confirm-yes").click();
    await expect(add.getByTestId("step-error")).toContainText("That didn’t save", SLOW);
    await expect(page.getByTestId("recommend-count")).toHaveText("Three");
  });

  test("rebuild asks first, then posts the refresh; a failure is reported", async ({ page }) => {
    const posts: string[] = [];
    let ok = true;
    await page.route("**/api/plans/refresh", (route) => {
      posts.push(route.request().method());
      return ok
        ? route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ plan: load("copilot-portfolio-plan.json").plan, message: "Plan refreshed to version 3" }) })
        : route.fulfill({ status: 500, contentType: "application/json", body: JSON.stringify({ detail: "fixture failure" }) });
    });
    await page.goto(`${APP}/tool/recommend`);
    await page.getByTestId("recommend-rebuild").click();
    await expect(page.getByTestId("recommend-rebuild-confirm")).toContainText("Nothing changes in your accounts");
    expect(posts).toHaveLength(0);
    await page.getByTestId("recommend-rebuild-yes").click();
    await expect(page.getByTestId("recommend-rebuild-done")).toBeVisible();
    expect(posts).toEqual(["POST"]);

    ok = false;
    await page.getByTestId("recommend-rebuild").click();
    await page.getByTestId("recommend-rebuild-yes").click();
    await expect(page.getByTestId("recommend-rebuild-error")).toContainText("The plan could not be rebuilt", SLOW);
  });
});

test.describe("Action plan — board, track record, expected and observed", () => {
  test.beforeEach(async ({ page }) => { await portfolio(page); });

  test("board, summary and track record ← plans/active and plans/history", async ({ page }) => {
    await page.goto(`${APP}/page/plan`);
    // copilot-portfolio-plan.json: 5 steps — 2 pending, 1 in progress, 1 completed, 1 skipped
    await expect(page.getByTestId("plan-total")).toHaveText("5");
    await expect(page.getByTestId("plan-count-considering")).toHaveText("2");
    await expect(page.getByTestId("plan-count-decided")).toHaveText("1");
    await expect(page.getByTestId("plan-count-done")).toHaveText("1");
    await expect(page.getByTestId("plan-declined")).toHaveText("1");
    await expect(page.getByTestId("plan-saving")).toHaveText("₹4,500"); // improvements.annual_cost_saving_rs
    await expect(page.getByTestId("plan-card")).toHaveCount(4); // the declined step is in the track record, not on the board

    const considering = page.getByTestId("plan-column-considering").getByTestId("plan-card");
    await expect(considering.nth(0).getByTestId("plan-card-title")).toHaveText("Trim Axis Fixture Bluechip Fund - Direct Growth");
    await expect(considering.nth(0).getByTestId("plan-card-severity")).toHaveText("Mismatch");
    await expect(considering.nth(0).getByTestId("plan-card-execution")).toHaveText("Stagger");
    await expect(considering.nth(0).getByTestId("plan-card-tax")).toContainText("long-term gain ₹9,600");
    await expect(considering.nth(0).locator(`${icon("fund-house")}[data-key="Axis"]`)).toHaveCount(1);
    await expect(considering.nth(1).locator(`${icon("stock")}[data-key="FIXSTEEL"]`)).toHaveCount(1);
    const doneCard = page.getByTestId("plan-column-done").getByTestId("plan-card");
    await expect(doneCard.getByTestId("plan-card-note")).toHaveText("Your note: Switched through my broker");
    await expect(doneCard.locator(`${icon("fund-house")}[data-key="Nippon India"]`)).toHaveCount(1);

    // history: this plan (1 done, 1 declined) and an archived one (1 done, 1 declined)
    await expect(page.getByTestId("plan-track-summary")).toHaveText("2 done · 2 declined · 2 plan versions");
    await expect(page.getByTestId("plan-decision-title")).toHaveCount(4);
    await expect(page.getByTestId("plan-decision-title").first()).toHaveText("Switch Nippon India ETF Fixture 50"); // the latest decision, 20 Jul
    await expect(page.getByTestId("plan-decision-note").first()).toHaveText("Switched through my broker");
    // only this plan's declined step can be reopened
    await expect(page.getByTestId("plan-declined-row")).toHaveCount(1);
    await expect(page.getByTestId("plan-declined-row").getByTestId("step-reopen")).toHaveText("Reopen");
  });

  test("deciding a step is one click and sends IN_PROGRESS for that step", async ({ page }) => {
    const patches: Request[] = [];
    await page.route("**/api/plans/*/actions/*", (route) => {
      patches.push(route.request());
      return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ plan: load("copilot-portfolio-plan.json").plan, message: "ok" }) });
    });
    await page.goto(`${APP}/page/plan`);
    await page.getByTestId("plan-column-considering").getByTestId("plan-card").nth(1).getByTestId("step-decide").click();
    await expect.poll(() => patches.length).toBe(1);
    expect(new URL(patches[0].url()).pathname).toBe("/api/plans/plan_fixture_v2/actions/act_fix_2");
    expect(patches[0].postDataJSON()).toEqual({ status: "IN_PROGRESS" });
  });

  test("expected and observed ← portfolio/trend, health-projection and the plan's own figures", async ({ page }) => {
    await page.goto(`${APP}/page/plan`);
    const out = page.getByTestId("plan-outcomes");
    await expect(out).toBeVisible();
    await expect(page.getByTestId("plan-outcomes-progress")).toHaveText("1 of 5 steps marked done");
    // plan built 10 Jul 2026. copilot-portfolio-trend.json: 1 Jul is the record on file then (health 60.0), 31 Aug the latest (64.5)
    await expect(page.getByTestId("plan-outcome-overall-start")).toHaveText("60.0");
    await expect(page.getByTestId("plan-outcome-overall-latest")).toHaveText("64.5");
    await expect(page.getByTestId("plan-outcome-overall-observed")).toHaveText("+4.5 pts");
    // health-projection: 64.5 today → 70.0 with the open steps applied
    await expect(page.getByTestId("plan-outcome-overall-expected")).toHaveText("+5.5 pts");
    // diversification 55 → 61 observed; 61 → 68 still expected. Risk 62 → 62 observed.
    await expect(page.getByTestId("plan-outcome-diversification-observed")).toHaveText("+6.0 pts");
    await expect(page.getByTestId("plan-outcome-diversification-expected")).toHaveText("+7.0 pts");
    await expect(page.getByTestId("plan-outcome-risk-observed")).toHaveText("0.0 pts");
    await expect(out.getByTestId("plan-outcome-measure")).toHaveText(["Health score", "Diversification", "Risk", "Cost", "Performance"]);
    await expect(page.getByTestId("plan-outcomes-window")).toContainText("31 Aug 2026");
    await expect(page.getByTestId("plan-outcomes-window")).toContainText("1 Jul 2026");
    await expect(page.getByTestId("plan-outcomes-expected-note")).toContainText("all 3 open steps");
    await expect(page.getByTestId("plan-outcomes-no-steps-done")).toHaveCount(0); // one step is done

    // the plan's own before → after: improvements and simulation
    await expect(page.getByTestId("plan-expected-overlap-before")).toHaveText("62.0%");
    await expect(page.getByTestId("plan-expected-overlap-after")).toHaveText("47.0%");
    await expect(page.getByTestId("plan-expected-overlap-change")).toHaveText("−15.0 pts");
    await expect(page.getByTestId("plan-expected-debt-change")).toHaveText("No change"); // 9.0 → 9.0
    await expect(page.getByTestId("plan-expected-fund-count-before")).toHaveText("9");
    await expect(page.getByTestId("plan-expected-fund-count-change")).toHaveText("−2");
    await expect(page.getByTestId("plan-expected-cost-after")).toHaveText("0.71%");
    await expect(page.getByTestId("plan-expected-saving")).toHaveText("₹4,500");
    // the simulation's ten-year projection is not shown as a figure
    await expect(out).not.toContainText("26.00 L");

    // what is still not measured is said, and its engineering list is for admins (the fixture user is one)
    await expect(page.getByTestId("plan-outcomes-not-connected")).toContainText("A result for each step is not measured yet");
  });

  test("observed: one record, no record and a failed request each say so; a plan without figures says so", async ({ page }) => {
    const trend = load("copilot-portfolio-trend.json");
    // only the record the plan started from
    await json(page, "**/api/portfolio/trend*", { ...trend, count: 1, series: [trend.series[1]] });
    await page.goto(`${APP}/page/plan`);
    await expect(page.getByTestId("plan-outcomes-observed-empty")).toContainText("The only record on file for this plan is from 1 Jul 2026");
    await expect(page.getByTestId("plan-outcome-overall-start")).toHaveText("60.0");
    await expect(page.getByTestId("plan-outcome-overall-latest")).toHaveText("—");
    await expect(page.getByTestId("plan-outcome-overall-observed")).toHaveText("—");
    await expect(page.getByTestId("plan-outcome-overall-expected")).toHaveText("+5.5 pts"); // the projection still stands

    // every record is from after the plan was built
    await json(page, "**/api/portfolio/trend*", { ...trend, count: 1, series: [trend.series[2]] });
    await page.reload();
    await expect(page.getByTestId("plan-outcomes-observed-empty")).toContainText("from after this plan was built");
    await expect(page.getByTestId("plan-outcome-overall-start")).toHaveText("—");

    await json(page, "**/api/portfolio/trend*", { days: 730, count: 0, series: [] });
    await page.reload();
    await expect(page.getByTestId("plan-outcomes-observed-empty")).toContainText("No record of your portfolio is on file yet");

    await fail(page, "**/api/portfolio/trend*");
    await page.reload();
    await expect(page.getByTestId("plan-outcomes").getByRole("alert")).toContainText("The record of your portfolio’s health didn’t load", SLOW);
    await expect(page.getByTestId("plan-outcome-overall-expected")).toHaveText("+5.5 pts");
    await expect(page.getByTestId("plan-outcome-overall-observed")).toHaveText("—");

    // no projection and no figures on the plan
    const plan = load("copilot-portfolio-plan.json");
    delete plan.plan.improvements;
    delete plan.plan.simulation;
    await json(page, "**/api/plans/active", plan);
    await json(page, "**/api/plans/active/health-projection", { available: false, reason: "No active plan or no holdings." });
    await json(page, "**/api/portfolio/trend*", trend);
    await page.reload();
    await expect(page.getByTestId("plan-expected-empty")).toContainText("The plan carries no expected figures");
    await expect(page.getByTestId("plan-outcomes-expected-note")).toHaveText("No projection is available for the open steps of this plan.");
    await expect(page.getByTestId("plan-outcome-overall-expected")).toHaveText("—");
    await expect(page.getByTestId("plan-outcome-overall-observed")).toHaveText("+4.5 pts"); // the record is still there
    await expect(page.getByTestId("plan-saving")).toHaveCount(0);
  });
});

test.describe("Portfolio ledger — holdings, what is on record, corrections", () => {
  test.beforeEach(async ({ page }) => { await portfolio(page); });

  test("holdings: icons, source, type filter, search and order ← holdings-enriched + holdings", async ({ page }) => {
    await page.goto(`${APP}/page/ledger`);
    // copilot-portfolio-holdings.json: 6 holdings worth 10,00,000; 8,24,221.40 invested (one has no cost basis)
    await expect(page.getByTestId("ledger-count")).toHaveText("6");
    await expect(page.getByTestId("ledger-total")).toHaveText("₹10.00 L");
    await expect(page.getByTestId("ledger-invested")).toHaveText("₹8.24 L");
    await expect(page.getByTestId("ledger-statement-period")).toHaveText("Holdings from the Aug/2026 statement");
    await expect(page.getByTestId("ledger-flagged-count")).toHaveText("2 flagged"); // no cost basis, and a review verdict

    const rows = page.getByTestId("ledger-holding");
    await expect(rows).toHaveCount(6);
    // needs-a-look order: the stock with no cost basis, the fund under review, then by value
    await expect(page.getByTestId("ledger-holding-name")).toHaveText([
      "Fixture Steel Ltd", "SBI Fixture Midcap Fund - Regular Growth", "Axis Fixture Bluechip Fund - Direct Growth",
      "Fixture Bank Ltd", "Nippon India ETF Fixture 50", "Sovereign Gold Bond Fixture 2030",
    ]);
    // a stock shows the company icon keyed by its symbol, a fund or ETF the fund house icon, a gold bond none
    await expect(rows.nth(0).locator(`${icon("stock")}[data-key="FIXSTEEL"]`)).toHaveCount(1);
    await expect(rows.nth(1).locator(`${icon("fund-house")}[data-key="SBI"]`)).toHaveCount(1);
    await expect(rows.nth(2).locator(`${icon("fund-house")}[data-key="Axis"]`)).toHaveCount(1);
    await expect(rows.nth(4).locator(`${icon("fund-house")}[data-key="Nippon India"]`)).toHaveCount(1);
    await expect(rows.nth(5).locator('[data-testid="entity-icon"]')).toHaveCount(0);
    // copilot-portfolio-holdings-raw.json: five rows tagged "cas", the bank read from a broker account
    await expect(rows.nth(0).getByTestId("ledger-holding-source")).toHaveText("From: CAS statement");
    await expect(rows.nth(3).getByTestId("ledger-holding-source")).toHaveText("From: Broker · Fixture Broker");
    // the original table's columns: gain, XIRR, return against the index (fund 12.0 − index 10.5 over 1Y)
    await expect(rows.nth(2).getByTestId("ledger-holding-gain")).toHaveText("+10.0%");
    await expect(rows.nth(2).getByTestId("ledger-holding-xirr")).toHaveText("11.5%");
    await expect(rows.nth(2).getByTestId("ledger-holding-benchmark")).toHaveText("+1.5 pts");
    await expect(rows.nth(0).getByTestId("ledger-holding-gain")).toHaveText("—"); // no cost basis, so no gain

    await expect(page.getByTestId("ledger-filter-all")).toHaveText("All · 6");
    await expect(page.getByTestId("ledger-filter-equity")).toHaveText("Stocks · 2");
    await expect(page.getByTestId("ledger-filter-mutual_fund")).toHaveText("Mutual funds · 2");
    await expect(page.getByTestId("ledger-filter-etf")).toHaveText("ETFs · 1");
    await expect(page.getByTestId("ledger-filter-gold_sgb")).toHaveText("Gold and SGB · 1");
    await page.getByTestId("ledger-filter-mutual_fund").click();
    await expect(page.getByTestId("ledger-holding-name")).toHaveText(["SBI Fixture Midcap Fund - Regular Growth", "Axis Fixture Bluechip Fund - Direct Growth"]);
    await page.getByTestId("ledger-filter-all").click();

    await page.getByTestId("ledger-search").fill("INE000FIX002"); // the bank's ISIN
    await expect(page.getByTestId("ledger-holding-name")).toHaveText(["Fixture Bank Ltd"]);
    await page.getByTestId("ledger-search").fill("no such holding");
    await expect(page.getByTestId("ledger-holdings-none")).toBeVisible();
    await page.getByTestId("ledger-search").fill("");

    await page.getByTestId("ledger-sort").selectOption("gain"); // bank +25, axis +10, gold +8, etf +2, sbi −4, steel has none
    await expect(page.getByTestId("ledger-holding-name")).toHaveText([
      "Fixture Bank Ltd", "Axis Fixture Bluechip Fund - Direct Growth", "Sovereign Gold Bond Fixture 2030",
      "Nippon India ETF Fixture 50", "SBI Fixture Midcap Fund - Regular Growth", "Fixture Steel Ltd",
    ]);
  });

  test("allocation by type, gainers and losers, statements, transactions and SIPs", async ({ page }) => {
    await page.goto(`${APP}/page/ledger`);
    // by value: stocks 3,00,000 · mutual funds 5,50,000 · ETF 1,00,000 · gold 50,000 of 10,00,000
    await expect(page.getByTestId("ledger-type-equity")).toContainText("30%");
    await expect(page.getByTestId("ledger-type-mutual_fund")).toContainText("55%");
    await expect(page.getByTestId("ledger-type-etf")).toContainText("10%");
    await expect(page.getByTestId("ledger-type-gold")).toContainText("5%");

    const gainers = page.getByTestId("ledger-gainers");
    await expect(gainers.getByTestId("ledger-mover-name")).toHaveText(["Fixture Bank Ltd", "Axis Fixture Bluechip Fund - Direct Growth", "Sovereign Gold Bond Fixture 2030", "Nippon India ETF Fixture 50"]);
    await expect(gainers.getByTestId("ledger-mover-pct").first()).toHaveText("+25.0%");
    await expect(gainers.getByTestId("ledger-mover").first().locator(`${icon("stock")}[data-key="FIXBANK"]`)).toHaveCount(1);
    const losers = page.getByTestId("ledger-losers");
    await expect(losers.getByTestId("ledger-mover-name")).toHaveText(["SBI Fixture Midcap Fund - Regular Growth"]);
    await expect(losers.getByTestId("ledger-mover-pct")).toHaveText("−4.0%");
    await expect(losers.locator(`${icon("fund-house")}[data-key="SBI"]`)).toHaveCount(1);

    // copilot-portfolio-statements.json: a statement import of 31 Aug and a daily record of 1 Jul
    await expect(page.getByTestId("ledger-statements-count")).toHaveText("2 on record · newest first");
    await expect(page.getByTestId("ledger-statement-date")).toHaveText(["31 Aug 2026", "1 Jul 2026"]);
    await expect(page.getByTestId("ledger-statement-value").first()).toHaveText("₹10.00 L");
    await expect(page.getByTestId("ledger-statements")).toContainText("Statement import");
    await expect(page.getByTestId("ledger-statements")).toContainText("Daily record");

    // copilot-portfolio-transactions.json: two SIP instalments of 5,000 and one redemption of 12,000
    await expect(page.getByTestId("ledger-transactions-count")).toHaveText("3");
    await expect(page.getByTestId("ledger-transactions-invested")).toHaveText("₹10.0k");
    await expect(page.getByTestId("ledger-transactions-redeemed")).toHaveText("₹12.0k");
    await expect(page.getByTestId("ledger-txn-type")).toHaveText(["SIP instalment", "Redemption", "SIP instalment"]);
    await expect(page.getByTestId("ledger-txn-amount").nth(1)).toHaveText("₹12,000");
    await expect(page.getByTestId("ledger-txn-scheme").first()).toContainText("Axis Fixture Bluechip Fund - Direct Growth");
    await expect(page.getByTestId("ledger-txn-scheme").first().locator(`${icon("fund-house")}[data-key="Axis"]`)).toHaveCount(1);

    // copilot-portfolio-sips.json: one active SIP of 5,000 a month, one paused
    await expect(page.getByTestId("ledger-sips-active")).toHaveText("1");
    await expect(page.getByTestId("ledger-sips-monthly")).toHaveText("₹5,000");
    await expect(page.getByTestId("ledger-sip-status")).toHaveText(["Active", "Paused"]);
    await expect(page.getByTestId("ledger-sip-amount").first()).toHaveText("₹5,000 / month");
    await expect(page.getByTestId("ledger-sip-scheme").nth(1).locator(`${icon("fund-house")}[data-key="SBI"]`)).toHaveCount(1);
  });

  test("nothing on record: statements, transactions and SIPs each say so", async ({ page }) => {
    await json(page, "**/api/portfolio/cas-snapshots*", { count: 0, snapshots: [], current_snapshot_date: null, is_default_latest: true });
    await json(page, "**/api/portfolio/transactions*", { transactions: [], count: 0, total_invested: 0, total_redeemed: 0 });
    await json(page, "**/api/portfolio/sips", { sips: [], count: 0, active_count: 0, monthly_sip_outflow: 0 });
    await json(page, "**/api/portfolio/holdings", []);
    await page.goto(`${APP}/page/ledger`);
    await expect(page.getByTestId("ledger-statements-empty")).toContainText("No statement on record");
    await expect(page.getByTestId("ledger-transactions-empty")).toContainText("No transactions on record");
    await expect(page.getByTestId("ledger-sips-empty")).toContainText("No recurring SIPs detected");
    await expect(page.getByTestId("ledger-statements")).toHaveCount(0);
    await expect(page.getByTestId("ledger-transactions")).toHaveCount(0);
    await expect(page.getByTestId("ledger-sips")).toHaveCount(0);
    // no record of where a holding came from: the holdings are still listed, with no source line
    await expect(page.getByTestId("ledger-holding")).toHaveCount(6);
    await expect(page.getByTestId("ledger-holding-source")).toHaveCount(0);
  });

  test("failed requests: each block reports its own failure and the holdings stay listed", async ({ page }) => {
    await fail(page, "**/api/portfolio/cas-snapshots*");
    await fail(page, "**/api/portfolio/transactions*");
    await fail(page, "**/api/portfolio/sips");
    await fail(page, "**/api/portfolio/holdings");
    await page.goto(`${APP}/page/ledger`);
    const screen = page.getByTestId("screen-page-ledger");
    await expect(screen.getByRole("alert").filter({ hasText: "Statements on record didn’t load" })).toBeVisible(SLOW);
    await expect(screen.getByRole("alert").filter({ hasText: "Transactions didn’t load" })).toBeVisible(SLOW);
    await expect(screen.getByRole("alert").filter({ hasText: "SIPs didn’t load" })).toBeVisible(SLOW);
    await expect(screen.getByRole("alert").filter({ hasText: "Where each holding came from didn’t load" })).toBeVisible(SLOW);
    await expect(page.getByTestId("ledger-holding")).toHaveCount(6);
    await expect(page.getByTestId("ledger-market-value")).toHaveText("₹10.00 L");
  });

  test("a correction is reviewed, saved with only the changed field, and the figures are read again", async ({ page }) => {
    const puts: Request[] = [];
    const reads: string[] = [];
    let corrected = false;
    await page.route("**/api/portfolio/holdings-enriched*", (route) => {
      reads.push(new URL(route.request().url()).search);
      return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(load(corrected ? "copilot-portfolio-holdings-corrected.json" : "copilot-portfolio-holdings.json")) });
    });
    await page.route("**/api/portfolio/holdings/*", (route) => {
      puts.push(route.request());
      corrected = true;
      // backend/routes/portfolio.py :: update_holding answers with the stored holding
      return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ ...load("copilot-portfolio-holdings-raw.json")[0], buy_price: 250 }) });
    });
    await page.goto(`${APP}/page/ledger`);
    const steel = page.getByTestId("ledger-holding").nth(0);
    await expect(steel).toContainText("No cost basis");
    await expect(steel.getByTestId("ledger-correct")).toHaveText("Add cost basis");
    await steel.getByTestId("ledger-correct").click();
    const form = steel.getByTestId("ledger-correct-form");
    await expect(form.getByLabel("Average buy price per share (₹)")).toHaveValue("");
    await expect(form.getByLabel("Shares held")).toHaveValue("400");
    await expect(form.getByTestId("ledger-correct-review")).toBeDisabled(); // nothing changed yet

    await form.getByTestId("ledger-correct-price").fill("-5");
    await expect(form.getByTestId("ledger-correct-problem")).toHaveText("The buy price must be a number above zero.");
    await expect(form.getByTestId("ledger-correct-review")).toBeDisabled();
    await form.getByTestId("ledger-correct-price").fill("250");
    await expect(form.getByTestId("ledger-correct-problem")).toHaveCount(0);
    await form.getByTestId("ledger-correct-review").click();
    // 400 shares × ₹250
    await expect(form.getByTestId("ledger-correct-summary")).toContainText("Average buy price per share: Not on record → ₹250");
    await expect(form.getByTestId("ledger-correct-invested")).toHaveText("₹1,00,000");
    await expect(form).toContainText("The next statement you import replaces your holdings");
    expect(puts).toHaveLength(0); // nothing is sent before the user saves

    const readsBefore = reads.length;
    await form.getByTestId("ledger-correct-save").click();
    const fixed = page.getByTestId("ledger-holding").filter({ hasText: "Fixture Steel Ltd" });
    await expect(fixed.getByTestId("ledger-correct-saved")).toBeVisible();
    expect(puts).toHaveLength(1);
    expect(puts[0].method()).toBe("PUT");
    expect(new URL(puts[0].url()).pathname).toBe("/api/portfolio/holdings/h_fix_steel");
    expect(puts[0].postDataJSON()).toEqual({ buy_price: 250 });
    // the holdings are read again past the backend's cache
    expect(reads.slice(readsBefore)).toContain("?fresh=true");
    // copilot-portfolio-holdings-corrected.json: the stock now has a cost basis, so it is no longer flagged
    await expect(fixed).not.toContainText("No cost basis");
    await expect(fixed.getByTestId("ledger-holding-gain")).toHaveText("0.0%");
    await expect(page.getByTestId("ledger-invested")).toHaveText("₹9.24 L");
    await expect(page.getByTestId("ledger-flagged-count")).toHaveText("1 flagged");
    // what the ledger still cannot do is said
    await expect(page.getByTestId("ledger-corrections-not-connected")).toContainText("A log of corrections is not kept");
  });

  test("a correction that fails says nothing was changed", async ({ page }) => {
    await fail(page, "**/api/portfolio/holdings/*");
    await page.goto(`${APP}/page/ledger`);
    const bank = page.getByTestId("ledger-holding").filter({ hasText: "Fixture Bank Ltd" });
    await bank.getByTestId("ledger-correct").click();
    const form = bank.getByTestId("ledger-correct-form");
    await expect(form.getByLabel("Average buy price per share (₹)")).toHaveValue("160");
    await form.getByTestId("ledger-correct-quantity").fill("0");
    await expect(form.getByTestId("ledger-correct-problem")).toHaveText("The number of shares must be above zero.");
    await form.getByTestId("ledger-correct-quantity").fill("1200");
    await form.getByTestId("ledger-correct-date").fill("2024-03-15");
    await form.getByTestId("ledger-correct-review").click();
    await expect(form.getByTestId("ledger-correct-summary")).toContainText("Shares: 1,000.000 → 1,200.000");
    await expect(form.getByTestId("ledger-correct-summary")).toContainText("Purchase date: Not on record → 15 Mar 2024");
    await expect(form.getByTestId("ledger-correct-invested")).toHaveText("₹1,92,000"); // 1,200 × ₹160
    await form.getByTestId("ledger-correct-save").click();
    await expect(form.getByTestId("ledger-correct-error")).toContainText("Nothing was changed", SLOW);
    await expect(bank.getByTestId("ledger-correct-saved")).toHaveCount(0);
    await form.getByTestId("ledger-correct-back").click();
    await form.getByTestId("ledger-correct-cancel").click();
    await expect(bank.getByTestId("ledger-correct-form")).toHaveCount(0);
  });
});

test.describe("Portfolio screens — phone (390×844)", () => {
  test.use({ viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true });

  test("the new blocks fit without sideways page scroll", async ({ page }) => {
    test.setTimeout(90_000);
    await portfolio(page);
    const sideways = () => page.evaluate(() => {
      const sc = document.querySelector('[data-testid="copilot-scroll"]') as HTMLElement | null;
      return {
        doc: document.documentElement.scrollWidth - document.documentElement.clientWidth,
        scroll: sc ? sc.scrollWidth - sc.clientWidth : 0,
      };
    });
    const check = async (what: string) => {
      await page.waitForLoadState("networkidle");
      const over = await sideways();
      expect.soft(over.doc, `${what}: page scrolls sideways`).toBeLessThanOrEqual(1);
      expect.soft(over.scroll, `${what}: content area scrolls sideways`).toBeLessThanOrEqual(1);
    };

    await page.goto(`${APP}/tool/analysis`);
    await page.getByTestId("analysis-tab-assets").click();
    await expect(page.getByTestId("analysis-target")).toBeVisible();
    await check("analysis · target mix");
    await page.getByTestId("analysis-tab-funds").click();
    await expect(page.getByTestId("analysis-fund-name").first()).toBeVisible();
    await check("analysis · funds");

    await page.goto(`${APP}/tool/recommend`);
    await expect(page.getByTestId("recommend-card")).toHaveCount(3);
    await page.getByTestId("recommend-card").first().getByTestId("step-done").click();
    await expect(page.getByTestId("step-confirm")).toBeVisible();
    await check("recommendations · confirm open");

    await page.goto(`${APP}/page/plan`);
    await expect(page.getByTestId("plan-outcomes")).toBeVisible();
    await check("action plan");

    await page.goto(`${APP}/page/ledger`);
    await expect(page.getByTestId("ledger-holding")).toHaveCount(6);
    await expect(page.getByTestId("ledger-sips")).toBeVisible();
    await page.getByTestId("ledger-holding").first().getByTestId("ledger-correct").click();
    await expect(page.getByTestId("ledger-correct-form")).toBeVisible();
    await check("ledger · correction open");
  });
});
