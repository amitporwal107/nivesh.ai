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
