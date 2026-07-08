/**
 * In-chat guided onboarding (/v5/chat) — the copilot walks a new user through
 * what it can do, then hands off into a REAL copilot answer.
 *
 * The chat page is auth-gated, so we answer /api/auth/me with a 200 (a logged-in
 * user) and stub the chat data endpoints so the landing renders; the onboarding
 * itself is a self-contained client-side stepper.
 *
 * Acceptance criteria:
 *  1. On a fresh chat, the guided onboarding auto-opens (welcome bubble).
 *  2. "Show me" advances to the "how I think" step.
 *  3. "Next" advances to the "pick a job" step with workflow chips.
 *  4. Clicking a workflow chip hands off to the copilot — its prompt is sent
 *     (appears as a user message in the thread).
 *  5. "Maybe later" dismisses the onboarding.
 *  6. The "Take the tour" launcher chip re-opens it.
 */
import { test, expect, Page } from "@playwright/test";

const ME = {
  user_id: "onb-user",
  email: "test@example.com",
  name: "Test User",
  is_admin: false,
  onboarding_completed: true,
  copilot_enabled: true,
};

const setup = async (page: Page) => {
  // Playwright matches routes last-registered-first, so register the broad
  // catch-all FIRST and the specific overrides AFTER (they win).
  await page.route("**/api/**", (r) =>
    r.fulfill({ status: 200, contentType: "application/json", body: "{}" }),
  );
  await page.route("**/api/auth/me**", (r) =>
    r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(ME) }),
  );
  // Fresh chat: create-session + stream are answered so the handoff send runs.
  await page.route("**/api/chat/sessions**", (r) =>
    r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ id: "onb-sid" }) }),
  );
  await page.route("**/api/chat/messages**", (r) =>
    r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ messages: [] }) }),
  );
  await page.route("**/api/chat/stream**", (r) =>
    r.fulfill({ status: 200, contentType: "text/event-stream", body: 'data: {"type":"meta","session_id":"onb-sid"}\n\n' }),
  );
  // Ensure the first-visit auto-open fires (clear the "seen" flag).
  await page.addInitScript(() => localStorage.removeItem("nv-copilot-onboarding-seen"));
  await page.goto("/v5/chat");
};

const onb = (page: Page) => page.getByTestId("copilot-onboarding");

test.describe("In-chat guided onboarding", () => {
  test.beforeEach(async ({ page }) => {
    await setup(page);
  });

  test("1 · auto-opens on a fresh chat", async ({ page }) => {
    await expect(onb(page)).toBeVisible({ timeout: 15000 });
    await expect(onb(page)).toContainText("one thing to fix first");
  });

  test("2-3 · steps through welcome → how-I-think → pick-a-job", async ({ page }) => {
    await onb(page).getByTestId("onb-start").click();
    await expect(onb(page)).toContainText("ground every answer");
    await onb(page).getByTestId("onb-next").click();
    await expect(onb(page).getByText("Portfolio health review", { exact: true })).toBeVisible();
    await expect(onb(page).getByText("Tax-loss harvesting", { exact: true })).toBeVisible();
  });

  test("4 · picking a workflow hands off to the real copilot", async ({ page }) => {
    await onb(page).getByTestId("onb-start").click();
    await onb(page).getByTestId("onb-next").click();
    // The handoff = a real send: clicking a job POSTs /api/chat/stream carrying
    // the workflow's prompt (mock-independent proof the copilot was invoked).
    const sendReq = page.waitForRequest(
      (r) => r.url().includes("/api/chat/stream") && r.method() === "POST",
      { timeout: 10000 },
    );
    await onb(page).getByText("Portfolio health review", { exact: true }).click();
    const body = JSON.parse((await sendReq).postData() || "{}");
    expect(body.message).toBe("What's the one thing I should fix first?");
    // Onboarding closes once the conversation starts.
    await expect(onb(page)).toHaveCount(0);
  });

  test("5-6 · dismiss then re-open via the launcher chip", async ({ page }) => {
    await expect(onb(page)).toBeVisible({ timeout: 15000 });
    await onb(page).getByTestId("onb-dismiss").click();
    await expect(onb(page)).toHaveCount(0);
    await page.getByTestId("onb-launcher").click();
    await expect(onb(page)).toBeVisible();
  });
});
