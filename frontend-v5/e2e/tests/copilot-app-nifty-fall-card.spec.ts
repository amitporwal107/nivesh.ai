/**
 * "If Nifty falls 5%" on the last step of onboarding (components/NiftyFallCard.tsx, screens/Onboarding.tsx StepDone). Cases NF-1 … NF-9.
 *
 * MOCK — not real data. The POST /api/portfolio/quick-hedge answers are fixtures/quick-hedge-*.mock.json, produced by the real backend
 * code (services/quick_hedge) from an INVENTED portfolio (₹25 lakh, beta 1.0) and an INVENTED option chain. The onboarding state is the
 * account spec's fixture. Expected text is worked out here from the fixtures' numbers. Production build, every /api mocked.
 */
import { test, expect, type Page, type Route } from "@playwright/test";
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";
import { mockApi } from "../helpers/api-mock";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const load = (name: string) => JSON.parse(fs.readFileSync(path.join(__dirname, "..", "fixtures", name), "utf-8"));
const APP = "/v5/app";
const SLOW = { timeout: 15_000 };
const reply = (route: Route, body: unknown, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
const inr = (n: number) => `₹${new Intl.NumberFormat("en-IN").format(Math.round(Math.abs(n)))}`;

const STATE = load("copilot-account-onboarding-state.json");     // 5 holdings, 2 broker accounts
const FALL5 = load("quick-hedge-fall5.mock.json");
const row5 = (res: any, mode = "balanced") => res.modes.find((m: any) => m.mode === mode).scenario_rows.find((r: any) => r.is_expected_fall);

type Opts = { flag?: boolean; answer?: unknown; status?: number; state?: unknown };

async function setup(page: Page, o: Opts = {}) {
  const calls: Array<Record<string, unknown>> = [];
  await mockApi(page, "populated");
  const base = load("user-profile-onboarded.json");
  await page.route("**/api/auth/me", (r) => reply(r, { ...base, features: { ...(base.features ?? {}), portfolio_hedge: o.flag !== false } }));
  await page.route("**/api/onboarding/state", (r) => reply(r, o.state ?? STATE));
  await page.route("**/api/portfolio/quick-hedge", (r) => { calls.push(r.request().postDataJSON() as Record<string, unknown>); return reply(r, o.answer ?? FALL5, o.status ?? 200); });
  return calls;
}

async function toDone(page: Page) {
  await page.goto(`${APP}/onboarding`);
  await page.getByTestId("onboarding-next").click();
  await expect(page.getByTestId("onboarding-step-goals")).toBeVisible(SLOW);
  await page.getByTestId("onboarding-next").click();
  await expect(page.getByTestId("onboarding-step-portfolio")).toBeVisible(SLOW);
  await page.getByTestId("onboarding-next").click();
  await expect(page.getByTestId("onboarding-step-done")).toBeVisible(SLOW);
}

async function noSideScroll(page: Page, where: string) {
  const o = await page.evaluate(() => {
    const sc = document.querySelector('[data-testid="copilot-scroll"]') as HTMLElement | null;
    return { doc: document.documentElement.scrollWidth - window.innerWidth, scroll: sc ? sc.scrollWidth - sc.clientWidth : 0 };
  });
  expect(o.doc, where).toBeLessThanOrEqual(1);
  expect(o.scroll, where).toBeLessThanOrEqual(1);
}

test.describe("MOCK — not real data: onboarding · if Nifty falls 5%", () => {
  test("NF-1 the done step shows what a 5% fall does and how it can be hedged, from the server's figures", async ({ page }) => {
    const calls = await setup(page);
    await toDone(page);
    const card = page.getByTestId("nifty-fall-card");
    await expect(card).toHaveAttribute("data-state", "ok", SLOW);
    expect(calls).toEqual([{ expected_fall_pct: 5, tenor: "1m", tolerance_pct: 5 }]);
    // In this fixture a 5% fall takes Nifty from 23,000 to 21,850, exactly the Balanced put's strike: Balanced pays nothing there
    // (its "with hedge" is the loss plus its cost), so the card shows Maximum protection, the first choice that does pay.
    const r = row5(FALL5, "maximum"), pv = FALL5.data.portfolio.portfolio_value_rs;
    expect(row5(FALL5, "balanced").hedge_pnl_rs).toBeLessThan(0);
    expect(r.hedge_pnl_rs).toBeGreaterThan(0);
    const maxStrike = new Intl.NumberFormat("en-IN").format(FALL5.modes.find((m: any) => m.mode === "maximum").legs[0].strike);
    await expect(page.getByTestId("nifty-fall-without")).toHaveText(inr(r.without_hedge_rs));
    await expect(card).toContainText(`(${(Math.abs(r.without_hedge_rs) / pv * 100).toFixed(1)}% of your whole portfolio)`);
    await expect(page.getByTestId("nifty-fall-hedge")).toHaveAttribute("data-pays", "yes");
    await expect(page.getByTestId("nifty-fall-hedge")).toContainText(`How it can be hedged: buy 1 lot of the ${maxStrike} put (Maximum protection)`);
    await expect(page.getByTestId("nifty-fall-with")).toHaveText(inr(r.with_hedge_rs));
    expect(Math.abs(r.with_hedge_rs)).toBeLessThan(Math.abs(r.without_hedge_rs));            // "would cut it to" is true
    await expect(page.getByTestId("nifty-fall-note")).toContainText("An estimate");
    await expect(page.getByTestId("nifty-fall-note")).toContainText("Paper only");
    await expect(page.getByTestId("nifty-fall-stale")).toHaveCount(0);                      // the fixture's sources are current
    await page.getByTestId("nifty-fall-see-hedge").click();
    await expect(page).toHaveURL(/\/v5\/app\/trader\/desk\?tab=risk&view=hedge$/);
  });

  test("NF-2 with the flag off nothing is shown and nothing is asked", async ({ page }) => {
    const calls = await setup(page, { flag: false });
    await toDone(page);
    await expect(page.getByTestId("onboarding-holdings-count")).toBeVisible(SLOW);          // the step itself is intact
    await expect(page.getByTestId("nifty-fall-card")).toHaveCount(0);
    expect(calls).toEqual([]);
  });

  test("NF-3 a portfolio under one lot still gets the simulated loss, and says why no hedge is offered", async ({ page }) => {
    await setup(page, { answer: load("quick-hedge-fall5-small.mock.json") });
    await toDone(page);
    await expect(page.getByTestId("nifty-fall-card")).toHaveAttribute("data-state", "not_hedgeable", SLOW);
    await expect(page.getByTestId("nifty-fall-without")).toHaveText("₹50,000");              // 10,00,000 x beta 1.0 x 5%
    await expect(page.getByTestId("nifty-fall-nohedge")).toContainText("smaller than one efficient index-option hedge lot");
    await expect(page.getByTestId("nifty-fall-see-hedge")).toHaveCount(0);
    await expect(page.getByTestId("nifty-fall-ask")).toBeVisible();
  });

  test("NF-4 no equity-linked holdings: it says so and offers to connect a broker or upload a CAS", async ({ page }) => {
    await setup(page, { answer: load("quick-hedge-noholdings.mock.json") });
    await toDone(page);
    await expect(page.getByTestId("nifty-fall-card")).toHaveAttribute("data-state", "empty", SLOW);
    await page.getByTestId("nifty-fall-connect").click();
    await expect(page).toHaveURL(/\/v5\/app\/page\/brokers$/);
  });

  test("NF-5 out-of-date sources are flagged on the card, with a way to update the holdings", async ({ page }) => {
    await setup(page, { answer: load("quick-hedge-fall5-stale.mock.json") });
    await toDone(page);
    await expect(page.getByTestId("nifty-fall-stale")).toContainText("look out of date", SLOW);
    await page.getByTestId("nifty-fall-update").click();
    await expect(page).toHaveURL(/\/v5\/app\/page\/brokers$/);
  });

  test("NF-6 a 403 hides the card, a server error says so quietly, and the step itself stays", async ({ page }) => {
    await setup(page, { answer: { detail: "feature_not_enabled" }, status: 403 });
    await toDone(page);
    await expect(page.getByTestId("onboarding-holdings-count")).toBeVisible(SLOW);
    await expect(page.getByTestId("nifty-fall-card")).toHaveCount(0);
    const page2 = await page.context().newPage();
    await setup(page2, { answer: { detail: "boom" }, status: 500 });
    await toDone(page2);
    await expect(page2.getByTestId("nifty-fall-card")).toContainText("could not be run just now", SLOW);
    await expect(page2.getByTestId("onboarding-holdings-count")).toBeVisible();
  });

  test("NF-7 no holdings on file: no card, no request", async ({ page }) => {
    const calls = await setup(page, { state: { ...STATE, holdings_count: 0, broker_accounts: 0, broker_accounts_live: 0, cas_statement_period: null, cas_portfolio_value_rs: null, cas_statement_date: null } });
    await toDone(page);
    await expect(page.getByTestId("onboarding-step-done")).toContainText("No portfolio on file");
    await expect(page.getByTestId("nifty-fall-card")).toHaveCount(0);
    expect(calls).toEqual([]);
  });
});

test.describe("MOCK — not real data: onboarding · if Nifty falls 5% · phone 390px", () => {
  test.use({ viewport: { width: 390, height: 844 } });
  test("NF-8 no sideways scroll with the card and a stale-sources line", async ({ page }) => {
    await setup(page, { answer: load("quick-hedge-fall5-stale.mock.json") });
    await toDone(page);
    await expect(page.getByTestId("nifty-fall-stale")).toBeVisible(SLOW);
    await page.waitForTimeout(400);
    await noSideScroll(page, "onboarding done step with the card");
  });

  test("NF-9 when no choice pays at a 5% fall, it says where protection starts and never that the hedge cuts the loss", async ({ page }) => {
    // fixtures/quick-hedge-fall5-inside.mock.json: tolerance 10% of ₹20 lakh = ₹2,00,000. Balanced buys the 20,700 put (10.0% below
    // 23,000), Maximum the 21,850 put; a 5% fall reaches neither. Balanced first pays at the 15% row: 3,00,000 -> 2,29,382.
    const INSIDE = load("quick-hedge-fall5-inside.mock.json");
    for (const m of INSIDE.modes.filter((x: any) => x.available)) expect(row5(INSIDE, m.mode).hedge_pnl_rs).toBeLessThanOrEqual(0);
    const bal = INSIDE.modes.find((m: any) => m.mode === "balanced");
    const r15 = bal.scenario_rows.find((x: any) => x.move_pct === -15);
    await setup(page, { answer: INSIDE });
    await toDone(page);
    const hedge = page.getByTestId("nifty-fall-hedge");
    await expect(hedge).toHaveAttribute("data-pays", "no", SLOW);
    await expect(hedge).toContainText("How it can be hedged: buy 1 lot of the 20,700 put (Balanced)");
    await expect(hedge).toContainText("starts paying only below Nifty 20,700 (10.0% down), so at a 5% fall it pays nothing and only adds its cost.");
    await expect(hedge).toContainText(`At a 15% fall it would cut the loss from ${inr(r15.without_hedge_rs)} to`);
    await expect(page.getByTestId("nifty-fall-deeper")).toHaveText(inr(r15.with_hedge_rs));
    await expect(hedge).toContainText("To cover a 5% fall itself, choose a smaller tolerable loss in the hedge.");
    await expect(hedge).not.toContainText("would cut it to");
    await expect(page.getByTestId("nifty-fall-with")).toHaveCount(0);
    await expect(page.getByTestId("nifty-fall-see-hedge")).toBeVisible();
    await noSideScroll(page, "onboarding done step, hedge not reached");
  });
});
