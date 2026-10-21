/**
 * One-screen Copilot app (/v5/app) — the model estimates on the Options lab and
 * the Trader desk F&O card: implied volatility and the Greeks per strike, ATM
 * IV, the forward, the ATM straddle, the builder's net Greeks and its model
 * chance of profit.
 *
 * MOCK — not real data. The fixtures e2e/fixtures/copilot-options-*.json are
 * synthetic: they were produced by running the real routes (backend/routes/fno.py,
 * pricing in backend/services/option_pricing.py) over a made-up data-platform
 * payload whose option prices are Black-76 values at a made-up smile, rounded to
 * the 0.05 tick. backend/tests/test_fno_routes.py re-prices every contract in
 * copilot-options-chain.json and fails if the fixture and the model drift apart.
 * Mocked APIs, production build — see pw.copilot-app.config.ts.
 *
 * The chain (copilot-options-chain.json): NIFTY, data day 12 Oct 2026, expiry
 * 27 Oct 2026 → 15 calendar days, T = 15/365; spot 25,010; the 27 Oct future
 * settles at 25,060 → forward 25,060 ("future"); r = 5.75%; lot 65.
 *
 * The forward's three bases, one made-up expiry each:
 *   27 Oct 2026  "future"           the 27 Oct future settles at 25,060.00
 *   24 Nov 2026  "put-call parity"  (copilot-options-chain-parity.json) no future expires that day; every
 *                                   contract traded. The call and the put are closest at 25,200 (430.00 and
 *                                   400.20): F = 25,200 + (430.00 − 400.20) × e^(0.0575 × 43/365)
 *                                              = 25,200 + 29.80 × 1.0067969 = 25,230.00
 *                                   (the prices were made from a forward of 25,230; the carried spot is 25,179.99)
 *   30 Mar 2027  "carried spot"     (copilot-options-chain-carried.json) no future, and no put traded that
 *                                   day, so no strike has both sides traded:
 *                                   F = 25,010 × e^(0.0575 × 169/365) = 25,010 × 1.0269809 = 25,684.79
 *
 * Working for the ATM call (strike 25,000, settle 273.45) — the figures the
 * fixture carries, re-derived by hand from the Black-76 formulas:
 *   √T = 0.2027212   at σ = 12%: σ√T = 0.0243265, ln(F/K) = ln(25060/25000) = 0.0023971
 *   d1 = (0.0023971 + 0.0243265²/2)/0.0243265 = 0.110703      d2 = d1 − σ√T = 0.086376
 *   N(d1) = 0.544074   N(d2) = 0.534416   φ(d1) = 0.396505    DF = e^(−0.0575×15/365) = 0.997640
 *   call = DF × (25060×0.544074 − 25000×0.534416) = 273.44 → the 273.45 settle is σ = 12.00%   → iv 12.00
 *   delta = DF×N(d1) = 0.5428         gamma = DF×φ(d1)/(25060×0.0243265) = 0.00064888 → 0.00065
 *   vega  = DF×25060×φ(d1)×√T/100 = 20.0957 → 20.10          theta (fixture) −7.9956 → −8.00
 *   ATM put settles at 213.60, the price the same 12% gives (213.58) → iv 12.00, delta −0.4549 → −0.45
 *   ATM IV = (12.00 + 12.00)/2 = 12.00%       straddle = 273.45 + 213.60 = 487.05 = 1.95% of 25,010
 *
 * Chance of profit (trading/odds.ts): P(S ≤ x) = N(z), z = [ln(x/F) + σ²T/2]/(σ√T),
 * F = 25,060, σ = ATM IV 12%, σ√T = 0.0243265, σ²T/2 = 0.00029589:
 *   buy the 25,000 call at 273.45   profit above 25,273.45: z = (0.0084815 + 0.0002959)/0.0243265 = 0.36081
 *                                   1 − N(0.36081) = 0.3591                                    → 35.9%
 *   short strangle, sell 25,300 call at 131.30 and 24,700 put at 130.20 (credit 261.50)
 *                                   profit between 24,438.50 and 25,561.50: z = −1.02017 and 0.82668
 *                                   N(0.82668) − N(−1.02017) = 0.79579 − 0.15382 = 0.6420       → 64.2%
 *   buy a 25,300 put at 213.60      profit below 25,086.40: z = 0.05545, N = 0.5221             → 52.2%
 *
 * Net Greeks = Σ (buy +1, sell −1) × lots × 65 × the contract's Greek:
 *   buy 1 lot of the 25,000 call    delta 0.5428×65 = +35.28   gamma 0.00064885×65 = +0.0422
 *                                   theta −7.9956×65 = −519.71 → −₹520    vega 20.0957×65 = 1,306.22 → +₹1,306
 *   short strangle (1 lot each)     gamma −(0.00063417 + 0.00049824)×65 = −0.0736
 *                                   theta +(7.0693 + 7.9088)×65 = +973.58 → +₹974
 *                                   vega  −(18.6581 + 17.4895)×65 = −2,349.59 → −₹2,350
 */
import { test, expect, type Page } from "@playwright/test";
import fs from "fs";
import path from "path";
import { mockApi, mockSingleRoute } from "../helpers/api-mock";

const APP = "/v5/app";
const FX = path.join(process.cwd(), "e2e", "fixtures");
const load = (name: string) => JSON.parse(fs.readFileSync(path.join(FX, name), "utf-8"));

const MODEL_LABEL = "Model estimate from end-of-day prices (Black-76)";
const NOT_AVAILABLE = "Not available";

const json = (page: Page, pattern: string | RegExp, body: unknown, status = 200) =>
  page.route(pattern, (route) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) }));

async function populated(page: Page) {
  await mockApi(page, "populated");
  await mockSingleRoute(page, "**/api/markets/home", "markets-home.json");
  await page.route("**/api/chat/sessions", (route) => route.fulfill({ status: 200, contentType: "application/json", body: "[]" }));
}

/** The synthetic NIFTY chains, one per forward basis: 27 Oct (future), 24 Nov (put-call parity), 30 Mar 2027 (carried spot). */
const CHAIN_FILES: Record<string, string> = {
  "2026-10-27": "copilot-options-chain.json",
  "2026-11-24": "copilot-options-chain-parity.json",
  "2027-03-30": "copilot-options-chain-carried.json",
};

/** `only`: serve that expiry alone, so it is the one a screen with no expiry picker (the F&O card) shows. */
async function optionsData(page: Page, only?: string) {
  const expiries = load("copilot-options-expiries.json");
  if (only) expiries.expiries = expiries.expiries.filter((e: { expiry: string }) => e.expiry === only);
  await json(page, "**/api/fno/NIFTY/expiries", expiries);
  await json(page, "**/api/fno/NIFTY/futures", load("copilot-options-futures.json"));
  await page.route("**/api/fno/NIFTY/chain*", (route) => {
    const expiry = new URL(route.request().url()).searchParams.get("expiry") ?? only ?? "2026-10-27";
    return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(load(CHAIN_FILES[expiry] ?? CHAIN_FILES["2026-10-27"])) });
  });
}

const row = (page: Page, strike: number) => page.locator(`[data-testid="optlab-chain-row"][data-strike="${strike}"]`);
const cell = (page: Page, strike: number, col: string) => row(page, strike).locator(`[data-col="${col}"]`);

async function sidewaysScroll(page: Page) {
  return page.evaluate(() => {
    const sc = document.querySelector('[data-testid="copilot-scroll"]') as HTMLElement | null;
    return {
      doc: document.documentElement.scrollWidth - document.documentElement.clientWidth,
      scroll: sc ? sc.scrollWidth - sc.clientWidth : 0,
    };
  });
}

test.describe("Options lab — model estimates", () => {
  test.beforeEach(async ({ page }) => { await populated(page); });

  test("header: ATM IV, the expected move, the forward and the model label", async ({ page }) => {
    await optionsData(page);
    await page.goto(`${APP}/tool/optlab`);
    await expect(page.getByTestId("optlab-expiry")).toHaveValue("2026-10-27");
    await expect(page.getByTestId("optlab-atm-iv")).toHaveText("12.00%");
    // 273.45 + 213.60, and 487.05 / 25,010
    await expect(page.getByTestId("optlab-expected-move")).toHaveText("±487.05");
    await expect(page.getByTestId("optlab-expected-move-pct")).toHaveText("1.95%");
    await expect(page.getByTestId("optlab-forward")).toHaveText("25,060.00");
    await expect(page.getByTestId("optlab-forward-basis")).toHaveText("Same-expiry future’s settle price");
    await expect(page.getByTestId("optlab-days")).toHaveText("15");
    const label = page.getByTestId("optlab-model-label");
    await expect(label).toContainText(`${MODEL_LABEL}, at an interest rate of 5.75% a year.`);
    await expect(label).toContainText("Forward 25,060.00 · the 27 Oct 2026 future’s settle price.");
    await expect(label).toContainText("not a forecast");
  });

  test("an expiry no future expires with is priced on the forward its call and put prices imply, and says so", async ({ page }) => {
    await optionsData(page);
    await page.goto(`${APP}/tool/optlab`);
    await page.getByTestId("optlab-expiry").selectOption("2026-11-24");
    // 25,200 + (430.00 − 400.20) × e^(0.0575 × 43/365) = 25,230.00; the carried spot would have been 25,179.99
    await expect(page.getByTestId("optlab-forward")).toHaveText("25,230.00");
    await expect(page.getByTestId("optlab-forward-basis")).toHaveText("Implied from call and put prices");
    await expect(page.getByTestId("optlab-days")).toHaveText("43");
    await expect(page.getByTestId("optlab-atm-iv")).toHaveText("12.50%");
    // 550.85 + 322.40
    await expect(page.getByTestId("optlab-expected-move")).toHaveText("±873.25");
    const label = page.getByTestId("optlab-model-label");
    await expect(label).toContainText(`${MODEL_LABEL}, at an interest rate of 5.75% a year.`);
    await expect(label).toContainText("Forward 25,230.00 · implied from call and put prices, at the strike where the two are closest, because no future expires on 24 Nov 2026.");
    // On the forward the options imply, the call and the put at each strike show one IV: the smile the prices were made from.
    await page.getByTestId("optlab-tab-chain").click();
    await expect(page.getByTestId("optlab-chain-row")).toHaveCount(5);
    for (const [strike, iv] of [[24900, "12.80"], [25000, "12.50"], [25100, "12.30"], [25200, "12.10"], [25300, "12.00"]] as Array<[number, string]>) {
      await expect(cell(page, strike, "call-iv")).toHaveText(iv);
      await expect(cell(page, strike, "put-iv")).toHaveText(iv);
    }
    await expect(page.getByTestId("optlab-chain-model-label")).toContainText("Forward 25,230.00 · implied from call and put prices");
  });

  test("with no future and no strike traded on both sides, the spot is carried at the stated rate, and says so", async ({ page }) => {
    await optionsData(page);
    await page.goto(`${APP}/tool/optlab`);
    await page.getByTestId("optlab-expiry").selectOption("2027-03-30");
    // 25,010 × e^(0.0575 × 169/365) = 25,010 × 1.0269809 = 25,684.79
    await expect(page.getByTestId("optlab-forward")).toHaveText("25,684.79");
    await expect(page.getByTestId("optlab-forward-basis")).toHaveText("Spot carried to expiry");
    await expect(page.getByTestId("optlab-days")).toHaveText("169");
    await expect(page.getByTestId("optlab-atm-iv")).toHaveText("13.00%");
    const label = page.getByTestId("optlab-model-label");
    await expect(label).toContainText("Forward 25,684.79 · the spot carried to expiry at 5.75% a year, because no future expires on 30 Mar 2027 and no strike had both its call and its put traded.");
    await expect(label).toContainText("calls and puts at one strike show different IV");
    // a put that is held but did not trade is still given an IV, from its settle price
    await page.getByTestId("optlab-tab-chain").click();
    await expect(cell(page, 25000, "put-volume")).toHaveText("0");
    await expect(cell(page, 25000, "put-iv")).toHaveText("13.00");
  });

  test("chain: IV for each strike, and the Greeks view", async ({ page }) => {
    await optionsData(page);
    await page.goto(`${APP}/tool/optlab`);
    await page.getByTestId("optlab-tab-chain").click();
    await expect(page.getByTestId("optlab-chain-row")).toHaveCount(7);
    const atm = page.locator('[data-testid="optlab-chain-row"][data-atm="true"]');
    await expect(atm).toHaveAttribute("data-strike", "25000");
    await expect(atm.locator('[data-col="call-iv"]')).toHaveText("12.00");
    await expect(atm.locator('[data-col="put-iv"]')).toHaveText("12.00");
    // the smile the prices were made from comes back strike by strike
    await expect(cell(page, 24800, "call-iv")).toHaveText("13.00");
    await expect(cell(page, 24800, "put-iv")).toHaveText("13.00");
    await expect(cell(page, 25200, "call-iv")).toHaveText("11.50");
    // the exchange's own figures are still beside it
    await expect(atm.locator('[data-col="call-price"]')).toHaveText("273.45");
    await expect(atm.locator('[data-col="put-oi"]')).toHaveText("18.60 L");

    await page.getByTestId("optlab-chain-view-greeks").click();
    await expect(atm.locator('[data-col="call-delta"]')).toHaveText("0.54");
    await expect(atm.locator('[data-col="put-delta"]')).toHaveText("−0.45");
    await expect(atm.locator('[data-col="call-gamma"]')).toHaveText("0.00065");
    await expect(atm.locator('[data-col="call-theta"]')).toHaveText("−8.00");
    await expect(atm.locator('[data-col="call-vega"]')).toHaveText("20.10");
    await expect(atm.locator('[data-col="call-iv"]')).toHaveText("12.00");
    await expect(atm.locator('[data-col="call-oi"]')).toHaveCount(0);

    const label = page.getByTestId("optlab-chain-model-label");
    await expect(label).toContainText(MODEL_LABEL);
    await expect(label).toContainText("The exchange file carries neither");
    await expect(label).toContainText("Delta and gamma are per one-point move in the forward");
  });

  test("a contract the model gave no IV for reads “Not available”, never a number", async ({ page }) => {
    await optionsData(page);
    await page.goto(`${APP}/tool/optlab`);
    await page.getByTestId("optlab-tab-chain").click();
    // 25,300 put: no volume and no open interest. 24,700 call: its 355.00 is below intrinsic value (0.99764 × 360 = 359.15).
    await expect(cell(page, 25300, "put-iv")).toHaveText(NOT_AVAILABLE);
    await expect(cell(page, 24700, "call-iv")).toHaveText(NOT_AVAILABLE);
    await expect(page.getByTestId("optlab-iv-missing")).toHaveCount(2);
    // the other side of each strike is priced
    await expect(cell(page, 25300, "call-iv")).toHaveText("11.40");
    await expect(cell(page, 24700, "put-iv")).toHaveText("13.60");
    await page.getByTestId("optlab-chain-view-greeks").click();
    await expect(cell(page, 25300, "put-iv")).toHaveText(NOT_AVAILABLE);
    for (const greek of ["delta", "gamma", "theta", "vega"]) await expect(cell(page, 25300, `put-${greek}`)).toHaveText("—");
    await expect(page.getByTestId("optlab-chain-model-label")).toContainText("“Not available” marks a contract that did not trade and has no open interest");
  });

  test("a route that sends no model fields shows “Not available” everywhere a model figure would be", async ({ page }) => {
    // fno-nifty.json is the chain as the route sent it before the model estimates were added.
    const old = load("fno-nifty.json");
    await json(page, "**/api/fno/NIFTY/expiries", old.expiries);
    await json(page, "**/api/fno/NIFTY/chain*", old.chain);
    await page.goto(`${APP}/tool/optlab`);
    for (const id of ["optlab-atm-iv", "optlab-expected-move", "optlab-forward", "optlab-days"]) {
      await expect(page.getByTestId(id)).toHaveText(NOT_AVAILABLE);
    }
    await expect(page.getByTestId("optlab-model-label")).toContainText("The server did not send model estimates for this chain.");
    // the builder's legs are still filled from the chain, and their model figures are declared missing
    await expect(page.getByTestId("optlab-leg-0-premium")).toHaveValue("240.25");
    for (const id of ["optlab-chance", "optlab-net-delta", "optlab-net-gamma", "optlab-net-theta", "optlab-net-vega"]) {
      await expect(page.getByTestId(id)).toHaveText(NOT_AVAILABLE);
    }
    await expect(page.getByTestId("optlab-net-greeks-missing")).toContainText("25,000 CE");
    await page.getByTestId("optlab-tab-chain").click();
    await expect(page.getByTestId("optlab-chain-row")).toHaveCount(3);
    await expect(page.getByTestId("optlab-iv-missing")).toHaveCount(6);
    await page.getByTestId("optlab-chain-view-day").click();
    await expect(page.getByTestId("optlab-chain-day-missing")).toContainText(NOT_AVAILABLE);
    await expect(page.getByTestId("optlab-chain-row")).toHaveCount(0);
  });

  test("builder: net Greeks and the model chance of profit for the legs", async ({ page }) => {
    await optionsData(page);
    await page.goto(`${APP}/tool/optlab`);
    // "Buy call" is filled with the ATM strike and its close, and the lot from the contract file.
    await expect(page.getByTestId("optlab-leg-0-strike")).toHaveValue("25000");
    await expect(page.getByTestId("optlab-leg-0-premium")).toHaveValue("273.45");
    await expect(page.getByTestId("optlab-lot-size")).toHaveValue("65");
    await expect(page.getByTestId("optlab-chance")).toHaveText("35.9%");
    await expect(page.getByTestId("optlab-net-delta")).toHaveText("+35.28");
    await expect(page.getByTestId("optlab-net-gamma")).toHaveText("+0.0422");
    await expect(page.getByTestId("optlab-net-theta")).toHaveText("−₹520");
    await expect(page.getByTestId("optlab-net-vega")).toHaveText("+₹1,306");
    const label = page.getByTestId("optlab-leg-model-label");
    await expect(label).toContainText(MODEL_LABEL);
    await expect(label).toContainText("risk-neutral probability");
    await expect(label).toContainText("not how often such a trade has worked");
    await expect(page.getByTestId("optlab-leg-model")).toContainText("Model probability at expiry, at the ATM IV of 12.00%. Not a forecast");

    // Two lots double every net Greek and leave the chance where it was.
    await page.getByTestId("optlab-leg-0-lots").fill("2");
    await expect(page.getByTestId("optlab-net-delta")).toHaveText("+70.56");
    await expect(page.getByTestId("optlab-chance")).toHaveText("35.9%");

    await page.getByTestId("optlab-view-neutral").click();
    await page.getByTestId("optlab-structure").filter({ hasText: "Short strangle" }).click();
    await expect(page.getByTestId("optlab-leg-0-strike")).toHaveValue("25300");
    await expect(page.getByTestId("optlab-leg-0-premium")).toHaveValue("131.3");
    await expect(page.getByTestId("optlab-leg-1-strike")).toHaveValue("24700");
    await expect(page.getByTestId("optlab-leg-1-premium")).toHaveValue("130.2");
    await expect(page.getByTestId("optlab-breakevens")).toHaveText("24,438.50 · 25,561.50");
    await expect(page.getByTestId("optlab-chance")).toHaveText("64.2%");
    await expect(page.getByTestId("optlab-net-gamma")).toHaveText("−0.0736");
    await expect(page.getByTestId("optlab-net-theta")).toHaveText("+₹974");
    await expect(page.getByTestId("optlab-net-vega")).toHaveText("−₹2,350");
    await expect(page.getByTestId("optlab-net-greeks-missing")).toHaveCount(0);

    // A leg on a contract with no model estimate: no net Greeks, and the leg is named. The chance needs only the forward and the ATM IV.
    await page.getByTestId("optlab-view-bearish").click();
    await expect(page.getByTestId("optlab-leg-0-premium")).toHaveValue("213.6");
    await page.getByTestId("optlab-leg-0-strike").fill("25300");
    for (const id of ["optlab-net-delta", "optlab-net-gamma", "optlab-net-theta", "optlab-net-vega"]) {
      await expect(page.getByTestId(id)).toHaveText(NOT_AVAILABLE);
    }
    await expect(page.getByTestId("optlab-net-greeks-missing")).toContainText("25,300 PE");
    await expect(page.getByTestId("optlab-chance")).toHaveText("52.2%");
  });

  test("day change and OI build-up, when the route sends the previous close", async ({ page }) => {
    await optionsData(page);
    await page.goto(`${APP}/tool/optlab`);
    await page.getByTestId("optlab-tab-chain").click();
    await page.getByTestId("optlab-chain-view-day").click();
    // 25,100 call: close 217.35, previous close 230.40 → −13.05 = −5.66%, open interest up → short build-up
    await expect(cell(page, 25100, "call-change")).toHaveText("−13.05");
    await expect(cell(page, 25100, "call-change-pct")).toHaveText("−5.66%");
    await expect(cell(page, 25100, "call-buildup")).toHaveText("short build-up");
    // 25,100 put: +12.85 = +5.26%, open interest down → short covering
    await expect(cell(page, 25100, "put-change")).toHaveText("+12.85");
    await expect(cell(page, 25100, "put-buildup")).toHaveText("short covering");
    // 25,000 put: the price moved but open interest did not → no label
    await expect(cell(page, 25000, "put-change")).toHaveText("+4.25");
    await expect(cell(page, 25000, "put-buildup")).toHaveText("—");
    await expect(page.getByTestId("optlab-chain-model-label")).toContainText("It describes two figures, not who traded.");
  });

  test("what is still not connected is narrowed to margin, intraday prices and today’s curve; nothing offers an order", async ({ page }) => {
    await optionsData(page);
    await page.goto(`${APP}/tool/optlab`);
    const nc = page.getByTestId("optlab-analytics-not-connected");
    await expect(nc).toContainText("Margin, intraday prices and today’s payoff curve");
    await expect(nc).not.toContainText("Greeks");
    await expect(nc).not.toContainText("chance of profit");
    await expect(nc.getByTestId("not-connected-needs")).toContainText("SPAN"); // the fixture user is an admin
    await expect(page.getByTestId("screen-tool-optlab").getByRole("button", { name: /place|send order|buy now|sell now/i })).toHaveCount(0);
  });
});

test.describe("Trader desk F&O card — model estimates", () => {
  test.beforeEach(async ({ page }) => { await populated(page); });

  test("ATM IV and the expected move, labelled as a model estimate", async ({ page }) => {
    await optionsData(page);
    await page.goto(`${APP}/trader`);
    await expect(page.getByTestId("fno-atm-iv")).toHaveText("12.00%");
    await expect(page.getByTestId("fno-expected-move")).toHaveText("±487.05");
    await expect(page.getByTestId("fno-options")).toContainText("ATM straddle · 1.95% of spot · to 27 Oct 2026");
    const label = page.getByTestId("fno-model-label");
    await expect(label).toContainText(`${MODEL_LABEL}, at an interest rate of 5.75% a year.`);
    await expect(label).toContainText("Forward 25,060.00 · the 27 Oct 2026 future’s settle price.");
    await expect(label).toContainText("not a forecast");
    // the figures the card already had
    await expect(page.getByTestId("fno-futures-price")).toHaveText("25,060.00");
    await expect(page.getByTestId("fno-basis")).toHaveText("+50.00");
    await expect(page.getByTestId("fno-pcr")).toHaveText("0.96");
    const nc = page.getByTestId("fno-not-connected");
    await expect(nc).toContainText("Index internals and intraday F&O for Nifty 50");
    await expect(nc).not.toContainText("Implied volatility");
    await expect(page.getByTestId("fno-analyser").getByRole("button", { name: /place|send order|buy now|sell now/i })).toHaveCount(0);
  });

  // The card has no expiry picker: each case serves one expiry, so that is the chain it shows.
  for (const c of [
    { expiry: "2026-11-24", atmIv: "12.50%", move: "±873.25", says: "Forward 25,230.00 · implied from call and put prices, at the strike where the two are closest, because no future expires on 24 Nov 2026." },
    { expiry: "2027-03-30", atmIv: "13.00%", move: "±1,821.70", says: "Forward 25,684.79 · the spot carried to expiry at 5.75% a year, because no future expires on 30 Mar 2027 and no strike had both its call and its put traded." },
  ]) {
    test(`the card names the forward's basis in words: ${c.expiry}`, async ({ page }) => {
      await optionsData(page, c.expiry);
      await page.goto(`${APP}/trader`);
      await expect(page.getByTestId("fno-atm-iv")).toHaveText(c.atmIv);
      await expect(page.getByTestId("fno-expected-move")).toHaveText(c.move);
      const label = page.getByTestId("fno-model-label");
      await expect(label).toContainText(`${MODEL_LABEL}, at an interest rate of 5.75% a year.`);
      await expect(label).toContainText(c.says);
    });
  }

  test("a route that sends no model fields: “Not available”, not a figure", async ({ page }) => {
    const old = load("fno-nifty.json");
    await json(page, "**/api/fno/NIFTY/expiries", old.expiries);
    await json(page, "**/api/fno/NIFTY/chain*", old.chain);
    await json(page, "**/api/fno/NIFTY/futures", old.futures);
    await page.goto(`${APP}/trader`);
    await expect(page.getByTestId("fno-pcr")).toHaveText("0.52");
    await expect(page.getByTestId("fno-atm-iv")).toHaveText(NOT_AVAILABLE);
    await expect(page.getByTestId("fno-expected-move")).toHaveText(NOT_AVAILABLE);
    await expect(page.getByTestId("fno-model-label")).toContainText("The server did not send model estimates for this chain.");
  });
});

test.describe("Options lab — phone (390×844)", () => {
  test.use({ viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true });

  test("the model figures fit at 390px without sideways page scroll", async ({ page }) => {
    await populated(page);
    await optionsData(page);
    const check = async (where: string) => {
      const over = await sidewaysScroll(page);
      expect.soft(over.doc, `${where}: page scrolls sideways`).toBeLessThanOrEqual(1);
      expect.soft(over.scroll, `${where}: content area scrolls sideways`).toBeLessThanOrEqual(1);
    };
    await page.goto(`${APP}/tool/optlab`);
    await expect(page.getByTestId("optlab-atm-iv")).toHaveText("12.00%");
    await expect(page.getByTestId("optlab-chance")).toHaveText("35.9%");
    await expect(page.getByTestId("optlab-net-vega")).toHaveText("+₹1,306");
    await check("builder");
    await page.getByTestId("optlab-tab-chain").click();
    await expect(page.locator('[data-testid="optlab-chain-row"][data-atm="true"] [data-col="call-iv"]')).toHaveText("12.00");
    await check("chain");
    await page.getByTestId("optlab-chain-view-greeks").click();
    await expect(page.locator('[data-testid="optlab-chain-row"][data-atm="true"] [data-col="put-delta"]')).toHaveText("−0.45");
    await check("chain, Greeks");
    await page.getByTestId("optlab-chain-view-day").click();
    await expect(cell(page, 25100, "call-buildup")).toHaveText("short build-up");
    await check("chain, day change");
    await page.goto(`${APP}/trader`);
    await expect(page.getByTestId("fno-atm-iv")).toHaveText("12.00%");
    await expect(page.getByTestId("fno-model-label")).toContainText(MODEL_LABEL);
    await check("trader desk");
  });
});

// Pictures for a reviewer, written only when SHOT_DIR is set (as in copilot-app-shots.spec.ts). No assertions.
test.describe("Options lab — pictures", () => {
  const DIR = process.env.SHOT_DIR;
  const shot = (page: Page, testId: string, name: string) => page.getByTestId(testId).first().screenshot({ path: path.join(DIR as string, `options-${name}.png`) });

  for (const size of [{ tag: "desktop", width: 1280, height: 800 }, { tag: "phone", width: 390, height: 844 }]) {
    test(`${size.tag}: header strip, chain views, the legs' model figures and the F&O card`, async ({ page }) => {
      test.skip(!DIR, "set SHOT_DIR to capture screenshots");
      await page.setViewportSize({ width: size.width, height: size.height });
      await populated(page);
      await optionsData(page);
      await page.goto(`${APP}/tool/optlab`);
      await expect(page.getByTestId("optlab-chance")).toHaveText("35.9%");
      await shot(page, "optlab-model", `${size.tag}-header`);
      await shot(page, "optlab-leg-model", `${size.tag}-legs`);
      await shot(page, "optlab-analytics-not-connected", `${size.tag}-not-connected`);
      await page.getByTestId("optlab-tab-chain").click();
      await expect(page.getByTestId("optlab-chain-row")).toHaveCount(7);
      await shot(page, "optlab-chain", `${size.tag}-chain-prices`);
      await page.getByTestId("optlab-chain-view-greeks").click();
      await shot(page, "optlab-chain", `${size.tag}-chain-greeks`);
      await page.getByTestId("optlab-chain-view-day").click();
      await shot(page, "optlab-chain", `${size.tag}-chain-day`);
      await page.goto(`${APP}/trader`);
      await expect(page.getByTestId("fno-atm-iv")).toHaveText("12.00%");
      await shot(page, "fno-options", `${size.tag}-fno-card`);
    });
  }
});
