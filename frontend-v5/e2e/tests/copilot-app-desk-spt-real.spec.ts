/**
 * Scanner-to-Paper Trading screens rendered from REAL staging response bodies (not mocks) — run on demand only.
 *
 * SPT_REAL_DIR points at a folder of JSON bodies saved from the deployed staging backend for a synthetic TEST user (the
 * integrator's scoped check writes them: accounts, opportunities, proposals, analytics, trades, risk, exposures, stress
 * test, allocation, orders, positions). Without SPT_REAL_DIR every case is skipped, so CI never needs real data and no
 * real data lives in the repo. Routes the deployed backend does not have are answered as it answers them (404).
 *
 * Proves: each of the six screens renders those real shapes with no page error and no error block, and shows figures that
 * come from the bodies (not from this file). It does NOT prove anything about live fills; that is the in-session check.
 */
import { test, expect, type Page, type Route } from "@playwright/test";
import * as fs from "fs";
import * as path from "path";
import { mockApi, mockSingleRoute } from "../helpers/api-mock";

const DIR = process.env.SPT_REAL_DIR || "";
const OUT = process.env.SPT_REAL_OUT || "";
const DESK = "/v5/app/trader/desk";
const SLOW = { timeout: 20_000 };
type Raw = Record<string, any>;

const body = (name: string): Raw => JSON.parse(fs.readFileSync(path.join(DIR, `${name}.json`), "utf8"));
const json = (route: Route, b: unknown, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(b) });

test.describe("SPT screens on real staging bodies", () => {
  test.skip(!DIR, "SPT_REAL_DIR not set: real-body render runs on demand only");

  async function real(page: Page): Promise<string[]> {
    const errors: string[] = [];
    page.on("pageerror", (e) => errors.push(String(e)));
    await page.route("**/api/**", (r) => json(r, { detail: "not part of this check" }, 404));
    await mockApi(page, "populated");
    await mockSingleRoute(page, "**/api/markets/home", "markets-home.json");
    await page.route("**/api/chat/sessions", (r) => json(r, []));
    await page.route("**/api/move-odds/**", (r) => json(r, { detail: "feature_not_enabled" }, 403));
    // REAL bodies from here on (SPT_REAL_DIR)
    await page.route(/\/api\/v1\/paper\/accounts(\?|$)/, (r) => json(r, body("accounts")));
    await page.route(/\/api\/v1\/paper\/accounts\/[^/?]+(\?|$)/, (r) => json(r, body("account_t1")));
    await page.route(/\/api\/v1\/opportunities(\?|$)/, (r) => {
      const q = new URL(r.request().url()).searchParams;
      return json(r, body(q.get("state") === "QUALIFIED" ? "opportunities_qualified" : "opportunities_all"));
    });
    await page.route(/\/api\/v1\/opportunities\/[^/?]+(\?|$)/, (r) => json(r, body("opportunity_detail")));
    await page.route(/\/api\/v1\/proposals(\?|$)/, (r) => json(r, body("proposals")));
    await page.route(/\/api\/v1\/analytics\/scanners(\?|$)/, (r) => json(r, body("analytics_scanners")));
    await page.route(/\/api\/v1\/paper\/trades(\?|$)/, (r) => json(r, body("paper_trades_t1")));
    await page.route(/\/api\/v1\/paper\/orders(\?|$)/, (r) => json(r, body("paper_orders")));
    await page.route(/\/api\/v1\/paper\/positions(\?|$)/, (r) => json(r, body("paper_positions")));
    await page.route(/\/api\/v1\/risk\/account\/[^/?]+(\?|$)/, (r) => json(r, body("risk_account")));
    await page.route(/\/api\/v1\/risk\/exposures\/[^/?]+(\?|$)/, (r) => json(r, body("risk_exposures")));
    await page.route(/\/api\/v1\/risk\/stress-test\/[^/?]+(\?|$)/, (r) => json(r, body("stress_test")));
    await page.route(/\/api\/v1\/allocation\/recommendations\/[^/?]+(\?|$)/, (r) => json(r, body("allocation_recs")));
    if (!fs.existsSync(path.join(DIR, "admin_settings.json"))) {
      // The deployed backend has no admin SPT routes yet (they come with PR #486): answer as FastAPI does.
      await page.route(/\/api\/admin\/spt\//, (r) => json(r, { detail: "Not Found" }, 404));
    } else {
      await page.route(/\/api\/admin\/spt\/settings$/, (r) => json(r, body("admin_settings")));
      await page.route(/\/api\/admin\/spt\/[^/]+\/config$/, (r) => json(r, body("admin_config_t1")));
    }
    return errors;
  }

  async function noErrorBlocks(page: Page, panel: string) {
    const p = page.getByTestId(panel);
    await expect(p).toBeVisible(SLOW);
    await page.waitForTimeout(1500);
    const errs = await p.locator('[data-testid$="-error"]').evaluateAll((els) => els.filter((e) => (e as HTMLElement).offsetParent !== null).map((e) => `${e.getAttribute("data-testid")}: ${e.textContent}`));
    expect(errs, "visible error blocks").toEqual([]);
  }

  async function shot(page: Page, name: string) {
    if (OUT) await page.screenshot({ path: path.join(OUT, `${name}.png`), fullPage: true });
  }

  test("REAL-1 Opportunities lists the real opportunities", async ({ page }) => {
    const errors = await real(page);
    const symbols = new Set([...body("opportunities_qualified").opportunities, ...body("opportunities_all").opportunities].map((o: Raw) => o.symbol));
    await page.goto(`${DESK}?tab=trade&view=paper&sub=opportunities`);
    await expect(page.getByTestId("spt-row").first()).toBeVisible(SLOW);
    const shown = await page.getByTestId("spt-row-symbol").allTextContents();
    expect(shown.length).toBeGreaterThan(0);
    expect(shown.filter((s) => !symbols.has(s.trim())), "every symbol on screen comes from the bodies").toEqual([]);
    await noErrorBlocks(page, "desk-panel-trade");
    await page.getByTestId("spt-row").first().click();
    await page.waitForTimeout(1000);
    await shot(page, "real-opportunities");
    expect(errors).toEqual([]);
  });

  test("REAL-2 Analytics renders the real outcome body", async ({ page }) => {
    const errors = await real(page);
    await page.goto(`${DESK}?tab=trade&view=paper&sub=analytics`);
    await noErrorBlocks(page, "desk-panel-trade");
    await shot(page, "real-analytics");
    expect(errors).toEqual([]);
  });

  test("REAL-3 Settings shows the real config (mode and limits)", async ({ page }) => {
    const errors = await real(page);
    const cfg = body("accounts").accounts[0].config;
    await page.goto(`${DESK}?tab=trade&view=paper&sub=settings`);
    await expect(page.getByTestId("desk-panel-trade")).toContainText(/Off/i, SLOW);
    expect(cfg.mode).toBe("off");
    await noErrorBlocks(page, "desk-panel-trade");
    await shot(page, "real-settings");
    expect(errors).toEqual([]);
  });

  test("REAL-4 Trading overview shows the real paper equity", async ({ page }) => {
    const errors = await real(page);
    const eq = Number(body("risk_account").equity_rs);
    await page.goto(`${DESK}?tab=risk&view=overview`);
    await expect(page.getByTestId("spt-kpi-equity-value")).toHaveText(`₹${new Intl.NumberFormat("en-IN").format(Math.round(eq))}`, SLOW);
    await noErrorBlocks(page, "desk-panel-risk");
    await shot(page, "real-overview");
    expect(errors).toEqual([]);
  });

  test("REAL-5 Capital allocation ranks the real opportunities", async ({ page }) => {
    const errors = await real(page);
    const first = body("allocation_recs").items[0].symbol as string;
    await page.goto(`${DESK}?tab=risk&view=allocation`);
    await expect(page.getByTestId("desk-panel-risk")).toContainText(first, SLOW);
    await noErrorBlocks(page, "desk-panel-risk");
    await shot(page, "real-allocation");
    expect(errors).toEqual([]);
  });

  test("REAL-6 Portfolio risk renders the real (empty) book", async ({ page }) => {
    const errors = await real(page);
    await page.goto(`${DESK}?tab=risk&view=portfolio`);
    await noErrorBlocks(page, "desk-panel-risk");
    await shot(page, "real-portfolio");
    expect(errors).toEqual([]);
  });
});
