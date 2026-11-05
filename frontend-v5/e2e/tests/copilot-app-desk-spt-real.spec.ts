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
 *
 * Paper Trading v2 (owner, 5 Nov 2026; docs/scanner_paper_trading/UI_DESIGN_V2.md): REAL-1 … REAL-6 now open the v2 views
 * (02 Scanner opportunities, 06 Strategy analytics, the account card's mode, 01 Overview, 03 Capital allocation, 04 Portfolio
 * risk). The v2 routes are read from OPTIONAL bodies — paper_overview, analytics_account, paper_policy, risk_correlation,
 * paper_fno_structures, desk_pnl, desk_pnl_timeseries (.json in SPT_REAL_DIR); a body that is missing is answered 404, as a
 * backend without that route answers, and the case then expects the view's honest error block for it instead of figures.
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
const has = (name: string) => !!DIR && fs.existsSync(path.join(DIR, `${name}.json`));
const inr = (n: number) => {
  const a = Math.abs(n), sign = n < 0 ? "−" : "";
  if (a >= 1_00_00_000) return `${sign}₹${(a / 1_00_00_000).toFixed(2)} Cr`;
  if (a >= 1_00_000) return `${sign}₹${(a / 1_00_000).toFixed(2)} L`;
  return `${sign}₹${new Intl.NumberFormat("en-IN").format(Math.round(a))}`;
};
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
    // Paper Trading v2 routes (UI_DESIGN_V2.md §7): optional bodies; a missing one answers 404 as a backend without the route does.
    const optional = (re: RegExp, name: string) => page.route(re, (r) => (has(name) ? json(r, body(name)) : json(r, { detail: "Not Found" }, 404)));
    await optional(/\/api\/v1\/paper\/overview(\?|$)/, "paper_overview");
    await optional(/\/api\/v1\/analytics\/account\/[^/?]+(\?|$)/, "analytics_account");
    await optional(/\/api\/v1\/paper\/accounts\/[^/]+\/policy(\?|$)/, "paper_policy");
    await optional(/\/api\/v1\/risk\/correlation\/[^/?]+(\?|$)/, "risk_correlation");
    await optional(/\/api\/v1\/paper\/fno-structures(\?|$)/, "paper_fno_structures");
    await optional(/\/api\/desk\/pnl(\?|$)/, "desk_pnl");
    await optional(/\/api\/desk\/pnl\/timeseries(\?|$)/, "desk_pnl_timeseries");
    if (!fs.existsSync(path.join(DIR, "admin_settings.json"))) {
      // The deployed backend has no admin SPT routes yet (they come with PR #486): answer as FastAPI does.
      await page.route(/\/api\/admin\/spt\//, (r) => json(r, { detail: "Not Found" }, 404));
    } else {
      await page.route(/\/api\/admin\/spt\/settings$/, (r) => json(r, body("admin_settings")));
      await page.route(/\/api\/admin\/spt\/[^/]+\/config$/, (r) => json(r, body("admin_config_t1")));
    }
    return errors;
  }

  /** No visible error block in the panel, except the ones named in `allowed` (a v2 route whose body was not saved). */
  async function noErrorBlocks(page: Page, panel: string, allowed: string[] = []) {
    const p = page.getByTestId(panel);
    await expect(p).toBeVisible(SLOW);
    await page.waitForTimeout(1500);
    const errs = await p.locator('[data-testid$="-error"]').evaluateAll((els) => els.filter((e) => (e as HTMLElement).offsetParent !== null).map((e) => `${e.getAttribute("data-testid")}: ${e.textContent}`));
    expect(errs.filter((e) => !allowed.some((a) => e.startsWith(`${a}:`))), "visible error blocks").toEqual([]);
  }

  async function shot(page: Page, name: string) {
    if (OUT) await page.screenshot({ path: path.join(OUT, `${name}.png`), fullPage: true });
  }

  test("REAL-1 02 Scanner opportunities lists the real opportunities", async ({ page }) => {
    const errors = await real(page);
    const symbols = new Set([...body("opportunities_all").opportunities, ...body("proposals").items].map((o: Raw) => o.symbol));
    await page.goto(`${DESK}?tab=trade&view=paper&sub=opportunities`);
    await expect(page.getByTestId("pv2-opps")).toBeVisible(SLOW);
    const rows = page.getByTestId("pv2-opp-row");
    if (await rows.count()) {
      const shown = await page.getByTestId("pv2-opp-symbol").allTextContents();
      expect(shown.filter((x) => !symbols.has(x.trim())), "every symbol on screen comes from the bodies").toEqual([]);
      await rows.first().click();
      await expect(page.getByTestId("pv2-opp-detail")).toBeVisible();
    } else {
      await expect(page.getByTestId("pv2-opps-empty")).toBeVisible();
    }
    await noErrorBlocks(page, "desk-panel-trade", has("paper_overview") ? [] : ["pv2-ov-error"]);
    await page.waitForTimeout(500);
    await shot(page, "real-v2-opportunities");
    expect(errors).toEqual([]);
  });

  test("REAL-2 06 Strategy analytics renders the real bodies", async ({ page }) => {
    const errors = await real(page);
    await page.goto(`${DESK}?tab=trade&view=paper&sub=analytics`);
    await expect(page.getByTestId("pv2-analytics")).toBeVisible(SLOW);
    if (has("analytics_account")) {
      const a = body("analytics_account");
      await expect(page.getByTestId("pv2-an-trades-value")).toHaveText(a.trades == null ? "—" : Number(a.trades).toLocaleString("en-IN"), SLOW);
    } else {
      await expect(page.getByTestId("pv2-an-error")).toBeVisible(SLOW);       // the route is not on this backend: said, not invented
    }
    await noErrorBlocks(page, "desk-panel-trade", has("analytics_account") ? [] : ["pv2-an-error"]);
    await shot(page, "real-v2-analytics");
    expect(errors).toEqual([]);
  });

  test("REAL-3 the account card shows the real mode and starting capital", async ({ page }) => {
    const errors = await real(page);
    const acc = body("accounts").accounts[0];
    await page.goto(`${DESK}?tab=trade&view=paper&sub=overview`);
    await expect(page.getByTestId("pv2-mode-pill")).toHaveAttribute("data-mode", String(acc.config?.mode ?? ""), SLOW);
    if (acc.account?.starting_capital_rs != null) await expect(page.getByTestId("pv2-account-capital")).toHaveText(inr(Number(acc.account.starting_capital_rs)));
    await page.getByTestId("pv2-mode-pill").click();
    await expect(page.getByTestId("pv2-mode-chooser")).toBeVisible();
    await shot(page, "real-v2-account");
    expect(errors).toEqual([]);
  });

  test("REAL-4 01 Overview shows the real paper equity", async ({ page }) => {
    const errors = await real(page);
    await page.goto(`${DESK}?tab=trade&view=paper&sub=overview`);
    await expect(page.getByTestId("pv2-overview")).toBeVisible(SLOW);
    if (has("paper_overview")) {
      const eq = body("paper_overview").kpis?.equity_rs;
      await expect(page.getByTestId("pv2-kpi-equity-value")).toHaveText(eq == null ? "—" : inr(Number(eq)), SLOW);
      await expect(page.getByTestId("pv2-status")).toHaveAttribute("data-state", "ok");
      await noErrorBlocks(page, "desk-panel-trade");
    } else {
      await expect(page.getByTestId("pv2-ov-error")).toBeVisible(SLOW);
      await expect(page.getByTestId("pv2-status")).toHaveAttribute("data-state", "error");
      await noErrorBlocks(page, "desk-panel-trade", ["pv2-ov-error"]);
    }
    await shot(page, "real-v2-overview");
    expect(errors).toEqual([]);
  });

  test("REAL-5 03 Capital allocation renders on the real bodies (builder B's view)", async ({ page }) => {
    const errors = await real(page);
    await page.goto(`${DESK}?tab=trade&view=paper&sub=allocation`);
    await expect(page.getByTestId("td-tab")).toHaveAttribute("data-sub", "allocation", SLOW);
    await page.waitForTimeout(2000);
    await shot(page, "real-v2-allocation");
    expect(errors).toEqual([]);
  });

  test("REAL-6 04 Portfolio risk renders on the real bodies (builder B's view)", async ({ page }) => {
    const errors = await real(page);
    await page.goto(`${DESK}?tab=trade&view=paper&sub=risk`);
    await expect(page.getByTestId("td-tab")).toHaveAttribute("data-sub", "risk", SLOW);
    await page.waitForTimeout(2000);
    await shot(page, "real-v2-risk");
    expect(errors).toEqual([]);
  });
});
