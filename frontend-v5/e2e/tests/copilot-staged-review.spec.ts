/**
 * Copilot chat staged review (/v5/chat) — the investor empty-state renders the
 * staged Portfolio Health Review. All five stages are live off REAL data:
 *   INTAKE (goal/risk/horizon + holdings) · ANALYSIS (health score + metrics +
 *   snapshot + flags) · OPTIONS (real remediation recs as paths) · RECOMMEND
 *   (ranked actions with exit/retain + ₹ impact) · ACTION (non-executable
 *   preview of the real EXIT/SELL lines — no orders are ever placed).
 *
 * Offline (mocked) coverage: structure, stage navigation, persona,
 * impersonation, intake capture, live health score + grade, live remediation
 * recs, the Action preview + its "not executable" guarantee, and honest empty
 * states. The full metric/flag/snapshot rendering off real feeds is proven
 * separately on LIVE staging.
 *
 * Route order matters: the catch-all api glob is registered FIRST so the
 * specific overrides (registered after) win — Playwright matches last-first.
 */
import { test, expect, Page } from "@playwright/test";

const ME = { user_id: "rv-user", email: "t@e.com", name: "T", is_admin: false, onboarding_completed: true, copilot_enabled: true };

const HEALTH = { portfolio_health: { health_score: 67, grade: "B", label: "healthy" } };

const REM = {
  total_value: 12373501,
  empty: false,
  recommendations: [
    {
      action_kind: "consolidation",
      title: "Consolidate 5 Small Cap funds into 1",
      action: "Exit: quant Small Cap, HDFC Small Cap, Nippon India Small Cap and 1 more. Retain: Nippon India Small Cap Direct. Capital to redeploy: ₹3,14,755.",
      amount_rs: 314755, annual_saving_rs: 4092, leverage_score: 80,
      contributors: [
        { name: "quant Small Cap Fund", pct_of_exposure: 42.8, value_rs: 134755 },
        { name: "HDFC Small Cap Fund", pct_of_exposure: 1, value_rs: 3151 },
      ],
      redeploy_to: "Redirect freed SIPs to under-allocated categories",
      before_after: [],
    },
    {
      action_kind: "trim_amc",
      title: "Reduce HDFC from 45% → 25%",
      action: "Trim HDFC across funds to bring single-house weight under 25%.",
      amount_rs: 3826795, annual_saving_rs: 0, leverage_score: 72, contributors: [], before_after: [],
    },
    {
      action_kind: "rebalance",
      title: "Portfolio drift: equity 82% vs target 60%",
      action: "SELL ₹27.5 L of equity to restore the 60/40 split.",
      amount_rs: 2746900, annual_saving_rs: 0, leverage_score: 65, contributors: [],
      before_after: [{ lens_label: "Equity", before_pct: 82, after_pct: 60 }],
    },
  ],
};

const setup = async (
  page: Page,
  opts: { me?: Record<string, unknown>; impersonateProfileId?: string; health?: unknown; rem?: unknown } = {},
) => {
  const { me = ME, impersonateProfileId, health = HEALTH, rem = REM } = opts;
  await page.route("**/api/**", (r) => r.fulfill({ status: 200, contentType: "application/json", body: "{}" }));
  await page.route("**/api/auth/me**", (r) => r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(me) }));
  await page.route("**/api/insights/analysis**", (r) => r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(health) }));
  await page.route("**/api/portfolio/exposure/remediation**", (r) => r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(rem) }));
  await page.route("**/api/chat/sessions**", (r) => r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ id: "rv-sid" }) }));
  await page.route("**/api/chat/messages**", (r) => r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ messages: [] }) }));
  await page.route("**/api/chat/stream**", (r) => r.fulfill({ status: 200, contentType: "text/event-stream", body: 'data: {"type":"meta","session_id":"rv-sid"}\n\n' }));
  if (impersonateProfileId) {
    await page.addInitScript((pid) => {
      localStorage.setItem("nivesh.impersonation", JSON.stringify({ state: { profileId: pid, name: "Client" }, version: 0 }));
    }, impersonateProfileId);
  }
  await page.goto("/v5/chat");
};

const rv = (page: Page) => page.getByTestId("copilot-review");

test.describe("Copilot staged review — investor", () => {
  test("1 · investor empty-state renders the staged review, INTAKE active", async ({ page }) => {
    await setup(page);
    await expect(rv(page)).toBeVisible({ timeout: 15000 });
    await expect(rv(page)).toHaveAttribute("data-role", "investor");
    await expect(rv(page).getByTestId("review-stagestrip")).toBeVisible();
    await expect(rv(page).getByTestId("stage-INTAKE")).toHaveAttribute("aria-current", "step");
    await expect(rv(page).getByTestId("intake-goals")).toBeVisible();
  });

  test("2 · INTAKE captures goal → risk → horizon and carries into ANALYSIS", async ({ page }) => {
    await setup(page);
    await expect(rv(page).getByTestId("intake-goals")).toBeVisible({ timeout: 15000 });
    await rv(page).getByRole("button", { name: "Reduce risk" }).click();
    await expect(rv(page).getByTestId("intake-risks")).toBeVisible();
    await rv(page).getByRole("button", { name: "Moderate" }).click();
    await expect(rv(page).getByTestId("intake-horizons")).toBeVisible();
    await expect(rv(page).getByText("Reduce risk", { exact: true }).first()).toBeVisible();
    await rv(page).getByTestId("intake-analyze").click();
    await expect(rv(page).getByTestId("stage-ANALYSIS")).toHaveAttribute("aria-current", "step");
    await expect(rv(page).getByTestId("analysis-context")).toContainText("RISK · MODERATE");
  });

  test("3 · ANALYSIS shows the live health score + grade, no fabricated risk", async ({ page }) => {
    await setup(page);
    await expect(rv(page)).toBeVisible({ timeout: 15000 });
    await rv(page).getByTestId("stage-ANALYSIS").click();
    await expect(rv(page).getByTestId("review-health-score")).toContainText("67");
    await expect(rv(page).getByTestId("metric-grade")).toContainText("B");
    await expect(rv(page).getByText("6.4")).toHaveCount(0);
  });

  test("4 · OPTIONS shows the real remediation recs as paths with ₹ impact", async ({ page }) => {
    await setup(page);
    await expect(rv(page)).toBeVisible({ timeout: 15000 });
    await rv(page).getByTestId("stage-OPTIONS").click();
    await expect(rv(page).getByTestId("option-0")).toContainText("Consolidate 5 Small Cap funds into 1");
    await expect(rv(page).getByTestId("option-0")).toContainText("₹4,092 saved/yr");
    await expect(rv(page).getByTestId("option-1")).toContainText("Reduce HDFC");
  });

  test("5 · RECOMMEND shows top recs with exit/retain + ₹ impact + now→target", async ({ page }) => {
    await setup(page);
    await expect(rv(page)).toBeVisible({ timeout: 15000 });
    await rv(page).getByTestId("stage-RECOMMEND").click();
    const row0 = rv(page).getByTestId("rec-row-0");
    await expect(row0).toContainText("Consolidate 5 Small Cap funds into 1");
    await expect(row0).toContainText("₹4,092 saved/yr");
    await expect(row0).toContainText("Retain: Nippon India Small Cap Direct");
    await expect(row0).toContainText("Capital to redeploy: ₹3,14,755");
    await expect(rv(page).getByText("ALLOCATION · NOW → TARGET")).toBeVisible();
    await expect(rv(page).getByText("82% → 60%")).toBeVisible();
  });

  test("6 · RECOMMEND CTA routes a real question into the copilot", async ({ page }) => {
    await setup(page);
    await rv(page).getByTestId("stage-RECOMMEND").click();
    const req = page.waitForRequest((r) => r.url().includes("/api/chat/stream") && r.method() === "POST", { timeout: 10000 });
    await rv(page).getByTestId("rec-cta").click();
    expect(JSON.parse((await req).postData() || "{}").message).toBe("Consolidate 5 Small Cap funds into 1");
  });

  test("7 · ACTION is a non-executable preview of real EXIT lines — no orders placed", async ({ page }) => {
    await setup(page);
    await rv(page).getByTestId("stage-ACTION").click();
    await expect(rv(page).getByTestId("review-action")).toContainText("Nothing is placed");
    // real per-fund EXIT line with a real ₹ value (from contributors.value_rs)
    await expect(rv(page).getByTestId("action-line-0")).toContainText("quant Small Cap Fund");
    await expect(rv(page).getByTestId("action-line-0")).toContainText("₹1,34,755");
    // the no-execution guarantee is loud
    await expect(rv(page).getByTestId("action-noexec")).toContainText("NO ORDERS ARE PLACED");
    // nothing fabricated: no est. cost, none of the mockup's invented stock sells
    await expect(rv(page).getByText("not computed")).toBeVisible();
    await expect(rv(page).getByText(/SELL · HDFC Bank/)).toHaveCount(0);
    await expect(rv(page).getByText("₹96,000")).toHaveCount(0);
  });

  test("8 · empty portfolio → honest states across stages, no crash", async ({ page }) => {
    await setup(page, { health: { portfolio_health: { health_score: 0, grade: "" } }, rem: { total_value: 0, empty: true, recommendations: [] } });
    await expect(rv(page)).toBeVisible({ timeout: 15000 });
    await rv(page).getByTestId("stage-ANALYSIS").click();
    await expect(rv(page).getByText("No live portfolio yet")).toBeVisible();
    await rv(page).getByTestId("stage-OPTIONS").click();
    await expect(rv(page).getByText("No options to weigh")).toBeVisible();
    await rv(page).getByTestId("stage-ACTION").click();
    await expect(rv(page).getByText("Nothing to preview")).toBeVisible();
  });
});

test.describe("Copilot staged review — advisor persona", () => {
  const ADVISOR_ME = { ...ME, workspace_type: "ADVISORY" };

  test("9 · advisor at book root shows the advisor tiles, NOT the review", async ({ page }) => {
    await setup(page, { me: ADVISOR_ME });
    await expect(page.getByTestId("copilot-workflows")).toHaveAttribute("data-role", "advisor", { timeout: 15000 });
    await expect(page.getByTestId("copilot-review")).toHaveCount(0);
  });

  test("10 · advisor viewing a client shows the staged review (investor)", async ({ page }) => {
    await setup(page, { me: ADVISOR_ME, impersonateProfileId: "client-97909" });
    await expect(rv(page)).toBeVisible({ timeout: 15000 });
    await expect(rv(page)).toHaveAttribute("data-role", "investor");
    await expect(page.getByTestId("copilot-workflows")).toHaveCount(0);
  });
});
