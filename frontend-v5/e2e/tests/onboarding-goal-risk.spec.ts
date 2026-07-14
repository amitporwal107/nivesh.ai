/**
 * Onboarding — Goal & Risk as OPTIONAL steps, then land in the Copilot (/lite).
 *
 * Verifies the onboarding change:
 *   persona → connect → [Goal & Risk step] → /lite
 *
 * The Goal & Risk step reuses the shared ProfileWizardModal scoped to Risk +
 * Goal only (lastStep=1, so NO Snapshot step). Per product intent both are
 * OPTIONAL: every step is skippable, and skipping still completes onboarding
 * and drops the user into the Copilot at /lite.
 *
 * Runs against the local Vite dev server with mocked APIs (no real token).
 */
import { test, expect, type Page } from "@playwright/test";
import { mockApi } from "../helpers/api-mock";

test.describe("Onboarding — Goal & Risk steps (optional) → Copilot", () => {
  test.beforeEach(async ({ page }) => {
    await mockApi(page, "populated");
    // Brand-new user: NOT yet onboarded, so the flow isn't redirected away.
    await page.route("**/api/onboarding/state", (route) =>
      route.fulfill({ status: 200, contentType: "application/json",
        body: JSON.stringify({ onboarding_completed: false }) }));
    // The /lite landing surface reads chat sessions — keep it from hanging.
    await page.route("**/api/chat/sessions", (route) =>
      route.fulfill({ status: 200, contentType: "application/json", body: "[]" }));
  });

  // persona → connect → click "Continue · Goals & Risk" → the wizard is open.
  async function reachGoalRiskStep(page: Page) {
    await page.goto("/v5/onboarding");
    await page.getByTestId("persona-individual").click();
    await expect(page.getByText("Bring your investments in.")).toBeVisible();
    await page.getByTestId("onboarding-to-profile").click();
  }

  test("Goal & Risk appear as onboarding steps — Risk + Goal only (no Snapshot)", async ({ page }) => {
    await reachGoalRiskStep(page);
    // Wizard is open at the Risk step...
    await expect(page.getByText("Complete your profile")).toBeVisible();
    await expect(page.getByText("Risk profile")).toBeVisible();
    await expect(page.getByText("What's your risk tolerance?")).toBeVisible();
    // ...scoped to Risk + Goal ONLY — the Snapshot step is excluded (lastStep=1).
    await expect(page.getByText("Snapshot (optional)")).toHaveCount(0);
    // The Goal step itself is proven reachable + skippable by the next test.
  });

  test("Gmail import failure surfaces the REAL reason (not 'Import failed: 200')", async ({ page }) => {
    await page.route("**/api/onboarding/pan", (route) =>
      route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ ok: true }) }));
    // Backend returns HTTP 200 with ok:false and the reason in parse_error.
    await page.route("**/api/onboarding/gmail/auto-import", (route) =>
      route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({
        ok: false, scanned: 1,
        parse_error: { kind: "password", message: "The CAS statement couldn't be read.", detail: "wrong PAN" },
      }) }));
    // Arrive back from Gmail OAuth → the GmailPanel is in PAN-entry.
    await page.goto("/v5/onboarding?gmail_code=test123");
    const panInput = page.locator('input[placeholder="e.g. ABCDE1234F"]');
    await expect(panInput).toBeVisible();
    await panInput.fill("ABCDE1234F");
    await page.getByRole("button", { name: /Import my holdings/ }).click();
    // The actual reason is shown; the bare-status message is NOT.
    await expect(page.getByText("The CAS statement couldn't be read.")).toBeVisible();
    await expect(page.getByText(/Import failed: 200/)).toHaveCount(0);
  });

  test("CAS upload posts to the in-house parser (/api/onboarding/upload-cas) and imports holdings", async ({ page }) => {
    await page.route("**/api/onboarding/pan", (route) =>
      route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ ok: true }) }));
    let uploadUrl = "";
    await page.route("**/api/onboarding/upload-cas", (route) => {
      uploadUrl = route.request().url();
      return route.fulfill({ status: 200, contentType: "application/json",
        body: JSON.stringify({ ok: true, imported_holdings: 5 }) });
    });
    // Regression guard: the OLD (broken) path — /api/portfolio/upload 410s PDFs.
    await page.route("**/api/portfolio/upload", (route) =>
      route.fulfill({ status: 410, contentType: "application/json", body: JSON.stringify({ detail: "gone" }) }));

    await page.goto("/v5/onboarding");
    await page.getByTestId("persona-individual").click();
    await page.getByText("CAS Upload · NSDL / CDSL").click();
    await page.getByTestId("cas-pan").fill("ABCDE1234F");
    await page.locator('input[type="file"]').setInputFiles({
      name: "cas.pdf", mimeType: "application/pdf", buffer: Buffer.from("%PDF-1.4 test"),
    });
    await expect(page.getByText(/5 holdings imported/i)).toBeVisible();
    await expect(page.getByTestId("upload-continue")).toBeVisible();
    expect(uploadUrl).toContain("/api/onboarding/upload-cas");
  });

  test("CAS upload failure surfaces the real reason (422 detail)", async ({ page }) => {
    await page.route("**/api/onboarding/pan", (route) =>
      route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ ok: true }) }));
    await page.route("**/api/onboarding/upload-cas", (route) =>
      route.fulfill({ status: 422, contentType: "application/json", body: JSON.stringify({
        detail: "Couldn't parse this CAS PDF. Check that the PAN matches and the file is a recent statement.",
      }) }));

    await page.goto("/v5/onboarding");
    await page.getByTestId("persona-individual").click();
    await page.getByText("CAS Upload · NSDL / CDSL").click();
    await page.getByTestId("cas-pan").fill("ABCDE1234F");
    await page.locator('input[type="file"]').setInputFiles({
      name: "cas.pdf", mimeType: "application/pdf", buffer: Buffer.from("%PDF-1.4 test"),
    });
    await expect(page.getByText(/Couldn't parse this CAS PDF/)).toBeVisible();
  });

  test("Already-onboarded users hitting /onboarding are redirected to the Copilot (/lite)", async ({ page }) => {
    // Override: this user has already completed onboarding.
    await page.route("**/api/onboarding/state", (route) =>
      route.fulfill({ status: 200, contentType: "application/json",
        body: JSON.stringify({ onboarding_completed: true }) }));
    await page.goto("/v5/onboarding");
    await expect(page).toHaveURL(/\/v5\/lite$/);
    await expect(page.getByText("New chat").first()).toBeVisible();
  });

  test("NOT-onboarded user completes onboarding by skipping → lands in /lite, no loop", async ({ page }) => {
    // Stateful: the user starts NOT onboarded; POST /complete-onboarding flips it.
    let onboarded = false;
    await page.route("**/api/user/complete-onboarding", (route) => {
      onboarded = true;
      return route.fulfill({ status: 200, contentType: "application/json",
        body: JSON.stringify({ status: "ok", onboarding_completed: true }) });
    });
    const meBody = () => JSON.stringify({
      user_id: "u1", email: "new@user.com", email_norm: "new@user.com", name: "New User",
      is_admin: false, onboarding_completed: onboarded,
      created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z",
      _session_user_id: "u1", _active_profile_id: null,
    });
    await page.route("**/api/auth/me", (route) =>
      route.fulfill({ status: 200, contentType: "application/json", body: meBody() }));
    await page.route("**/api/onboarding/state", (route) =>
      route.fulfill({ status: 200, contentType: "application/json",
        body: JSON.stringify({ onboarding_completed: onboarded }) }));

    // Not onboarded → /lite bounces to onboarding.
    await page.goto("/v5/lite");
    await expect(page).toHaveURL(/\/v5\/onboarding$/);
    // Go through the flow skipping everything (connect, risk, goal).
    await page.getByTestId("persona-individual").click();
    await page.getByTestId("onboarding-to-profile").click();
    await page.getByRole("button", { name: "Skip", exact: true }).click();
    await page.getByRole("button", { name: /Skip for now/ }).click();
    await page.getByRole("button", { name: /View my action plan/ }).click();
    // finishOnboarding flips the flag + refreshes useMe → /lite now passes the gate.
    await expect(page).toHaveURL(/\/v5\/lite$/);
    await expect(page.getByText("New chat").first()).toBeVisible();
  });

  test("Both steps are OPTIONAL — skipping through lands in the Copilot (/lite)", async ({ page }) => {
    await reachGoalRiskStep(page);
    // Step 1 — Risk: skip.
    await expect(page.getByText("What's your risk tolerance?")).toBeVisible();
    await page.getByRole("button", { name: "Skip", exact: true }).click();
    // Step 2 — Goal: skip.
    await expect(page.getByText("Add your first goal")).toBeVisible();
    await page.getByRole("button", { name: /Skip for now/ }).click();
    // Finish → done screen → continue → the Copilot.
    await page.getByRole("button", { name: /View my action plan/ }).click();
    await expect(page).toHaveURL(/\/v5\/lite$/);
    await expect(page.getByText("New chat").first()).toBeVisible();
  });
});
