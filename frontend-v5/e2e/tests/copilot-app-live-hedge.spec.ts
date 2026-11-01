/**
 * Quick Hedge against the REAL deployed staging app and backend (LH-1 … LH-4). Not mocked.
 *
 * Skipped unless LIVE_TOKEN_FILE points at a file holding a staging session token (read from that file only, never logged; no response
 * body is printed, only statuses, counts and the text the screen shows). Point it at the DEPLOYED app, because staging refuses browser
 * writes from a page served at localhost:
 *
 *   LIVE_TOKEN_FILE=/secrets/token PW_BASE_URL=https://staging.niveshcopilot.com \
 *     npx playwright test --config pw.copilot-app.config.ts copilot-app-live-hedge
 *
 * The route only READS (holdings, prices, option chain) and stores nothing. LH-4 asks one real question in the Copilot, so each run adds
 * one thread to that account's chat history. The account must have the `portfolio_hedge` flag on and some equity-linked holdings.
 */
import { test, expect, type Page } from "@playwright/test";
import fs from "fs";
import path from "path";

const TOKEN_FILE = process.env.LIVE_TOKEN_FILE;
const OUT = process.env.SHOT_DIR;
const DESK = "/v5/app/trader/desk";
const inr = (n: number) => `${n < 0 ? "−" : ""}₹${new Intl.NumberFormat("en-IN").format(Math.round(Math.abs(n)))}`;
const shot = async (page: Page, name: string) => { if (OUT) await page.screenshot({ path: path.join(OUT, `${name}.png`) }); };
const BODY = { expected_fall_pct: 10, tenor: "1m", tolerance_pct: 5 };      // the desk screen's own first request

test.describe("Quick Hedge — live staging", () => {
  test.skip(!TOKEN_FILE, "set LIVE_TOKEN_FILE to run against staging");
  test.use({ viewport: { width: 1440, height: 900 } });
  test.describe.configure({ mode: "serial" });

  test.beforeEach(async ({ context, baseURL }) => {
    const token = fs.readFileSync(TOKEN_FILE as string, "utf-8").trim();
    const host = new URL(baseURL ?? "https://staging.niveshcopilot.com");
    await context.addCookies([{ name: "session_token", value: token, domain: host.hostname, path: "/", httpOnly: true, secure: host.protocol === "https:" }]);
  });

  test("LH-1 the route answers for the signed-in account, and refuses what it must", async ({ page }) => {
    const ok = await page.request.post("/api/portfolio/quick-hedge", { data: BODY });
    expect(ok.status()).toBe(200);
    const d = await ok.json();
    expect(d.status).toBe("ok");
    expect(d.modes.map((m: { mode: string }) => m.mode).sort()).toEqual(["balanced", "lowest_cost", "maximum"]);
    expect(d.exposure.executed_lots).toBeGreaterThanOrEqual(1);
    expect(d.exposure.executed_lots * d.exposure.lot_notional_rs).toBeLessThanOrEqual(d.exposure.beta_adjusted_exposure_rs + 1e-6);   // never over 100%
    expect(d.data.market.as_of).toBeTruthy();
    expect(d.disclosures.join(" ")).toContain("not guaranteed future performance");
    console.log(`LIVE ${JSON.stringify({ label: "route", status: d.status, confidence: d.confidence.level, r2: d.confidence.r2, lots: `${d.exposure.executed_lots} of ${d.exposure.required_lots.toFixed(2)}`, expiry: d.expiry, optionsAsOf: d.data.market.as_of })}`);
    expect((await page.request.post("/api/portfolio/quick-hedge", { data: { expected_fall_pct: 15 } })).status()).toBe(422);
    expect((await page.request.post("/api/portfolio/quick-hedge", { data: { ...BODY, expected_fall_pct: 80 } })).status()).toBe(422);
    expect((await page.request.post("/api/portfolio/quick-hedge", { data: { ...BODY, tenor: "5y" } })).status()).toBe(422);
  });

  test("LH-2 the desk offers Portfolio hedge last and shows the figures the route returns", async ({ page }) => {
    test.setTimeout(120_000);
    const api = await (await page.request.post("/api/portfolio/quick-hedge", { data: BODY })).json();
    const errors: string[] = [];
    page.on("pageerror", (e) => errors.push(e.message));
    await page.goto(`${DESK}?tab=risk&view=limits`);
    await expect(page.getByTestId("desk-view-hedge")).toBeVisible({ timeout: 45_000 });
    const keys = await page.getByTestId("desk-views").locator("button").evaluateAll((els) => els.map((e) => e.getAttribute("data-testid")));
    expect(keys[keys.length - 1]).toBe("desk-view-hedge");
    await page.getByTestId("desk-view-hedge").click();
    await expect(page).toHaveURL(/[?&]view=hedge(&|$)/);
    await expect(page.getByTestId("hedge-choices")).toBeVisible({ timeout: 60_000 });
    await expect(page.getByTestId("hedge-kpi-hedgeable-value")).toHaveText(inr(api.data.portfolio.hedgeable_value_rs));
    await expect(page.getByTestId("hedge-kpi-lots-value")).toHaveText(`${api.exposure.executed_lots} of ${api.exposure.required_lots.toFixed(2)}`);
    const bal = api.modes.find((m: { mode: string }) => m.mode === "balanced");
    await expect(page.getByTestId("hedge-choice-balanced-what")).toContainText(`${Math.round(bal.legs[0].strike).toLocaleString("en-IN")} put`);
    await expect(page.getByTestId("hedge-scenarios").locator("tbody tr")).toHaveCount(bal.scenario_rows.length);
    await expect(page.getByTestId("hedge-dates")).toContainText(`Nifty options as of ${api.data.market.as_of}`);
    await shot(page, "live-desk-balanced");
    await page.getByTestId("hedge-choice-lowest_cost").click();
    await expect(page.getByTestId("hedge-scenarios")).toHaveAttribute("data-mode", "lowest_cost");
    await shot(page, "live-desk-lowest-cost");
    expect(errors).toEqual([]);
  });

  test("LH-3 a changed question on the desk asks the server again with exactly those inputs", async ({ page }) => {
    test.setTimeout(120_000);
    await page.goto(`${DESK}?tab=risk&view=hedge`);
    await expect(page.getByTestId("hedge-choices")).toBeVisible({ timeout: 60_000 });
    const asked: Array<Record<string, unknown>> = [];
    page.on("request", (r) => { if (r.url().endsWith("/api/portfolio/quick-hedge") && r.method() === "POST") asked.push(r.postDataJSON()); });
    await page.getByTestId("hedge-fall-15").click();
    await page.getByTestId("hedge-tenor-2w").click();
    await page.getByTestId("hedge-run").click();
    await expect.poll(() => asked.length, { timeout: 30_000 }).toBe(1);
    expect(asked[0]).toEqual({ expected_fall_pct: 15, tenor: "2w", tolerance_pct: 5 });
    await expect(page.getByTestId("hedge-choices")).toBeVisible({ timeout: 60_000 });
    await expect(page.getByTestId("hedge-run")).toHaveText("Show my hedge choices", { timeout: 60_000 });
    await shot(page, "live-desk-15-2w");
  });

  test("LH-4 the Copilot answers a protection question with the hedge card", async ({ page }) => {
    test.setTimeout(240_000);
    await page.goto("/v5/app");
    const input = page.getByTestId("composer-input");
    await expect(input).toBeVisible({ timeout: 45_000 });
    await input.fill("Protect my portfolio against a 15% fall");
    await input.press("Enter");
    await expect(page).toHaveURL(/\/v5\/app\/t\/[^/]+$/, { timeout: 30_000 });
    const turn = page.getByTestId("thread-turn").last();
    await expect(turn.getByTestId("answer-widget")).toBeVisible({ timeout: 90_000 });       // the card is built before the explanation
    const widget = turn.getByTestId("answer-widget");
    await expect(widget).toContainText("Protect your portfolio");
    await expect(widget).toContainText("Your three choices");
    await expect(widget).toContainText("Balanced");
    await expect(widget).toContainText("what happens by expiry");
    await expect(widget).toContainText("Paper only");
    await expect(widget).toContainText("Because you did not say");                             // it names the defaults it used
    const text = (await widget.innerText()).replace(/\s+/g, " ");
    console.log(`LIVE ${JSON.stringify({ label: "chat-card", chars: text.length, start: text.slice(0, 220) })}`);
    await shot(page, "live-chat-card");
    await expect(turn).toHaveAttribute("data-state", /saved|error|stopped/, { timeout: 170_000 });
    console.log(`LIVE ${JSON.stringify({ label: "chat-turn", state: await turn.getAttribute("data-state") })}`);
  });
});
