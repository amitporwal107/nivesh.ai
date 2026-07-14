/**
 * Copilot chat workflow landing (/v5/chat) — the ADVISOR book landing.
 *
 * Note: investors (and advisors viewing a client) now get the staged Portfolio
 * Health Review instead of this tile list — that coverage lives in
 * copilot-staged-review.spec.ts. CopilotWorkflows now renders only for an
 * advisor at their own book root, so this spec covers just that persona.
 *
 * Auth-gated page: we answer /api/auth/me with 200 (workspace_type:"ADVISORY").
 *
 * Acceptance criteria:
 *  4. Advisor persona shows the advisor book workflows, not the investor ones.
 *  5. Advisor row runs a book-level prompt.
 */
import { test, expect, Page } from "@playwright/test";

const ME = { user_id: "wf-user", email: "t@e.com", name: "T", is_admin: false, onboarding_completed: true, copilot_enabled: true };

const setup = async (page: Page, me: Record<string, unknown> = ME, impersonateProfileId?: string) => {
  await page.route("**/api/**", (r) => r.fulfill({ status: 200, contentType: "application/json", body: "{}" }));
  await page.route("**/api/auth/me**", (r) => r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(me) }));
  await page.route("**/api/chat/sessions**", (r) => r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ id: "wf-sid" }) }));
  await page.route("**/api/chat/messages**", (r) => r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ messages: [] }) }));
  await page.route("**/api/chat/stream**", (r) => r.fulfill({ status: 200, contentType: "text/event-stream", body: 'data: {"type":"meta","session_id":"wf-sid"}\n\n' }));
  if (impersonateProfileId) {
    // Mirror the "viewing a client" state the impersonation store persists.
    await page.addInitScript((pid) => {
      localStorage.setItem("nivesh.impersonation", JSON.stringify({ state: { profileId: pid, name: "Client" }, version: 0 }));
    }, impersonateProfileId);
  }
  await page.goto("/v5/chat");
};

const wf = (page: Page) => page.getByTestId("copilot-workflows");
const sentPrompt = async (page: Page, click: () => Promise<void>): Promise<string> => {
  const req = page.waitForRequest((r) => r.url().includes("/api/chat/stream") && r.method() === "POST", { timeout: 10000 });
  await click();
  return JSON.parse((await req).postData() || "{}").message;
};

test.describe("Copilot chat workflow landing — advisor", () => {
  const ADVISOR_ME = { ...ME, workspace_type: "ADVISORY" };
  test.beforeEach(async ({ page }) => { await setup(page, ADVISOR_ME); });

  test("4 · advisor sees the book workflows, not investor ones", async ({ page }) => {
    await expect(wf(page)).toHaveAttribute("data-role", "advisor", { timeout: 15000 });
    await expect(wf(page).getByText("At-risk & churn", { exact: true })).toBeVisible();
    await expect(wf(page).getByText("AUM & book health", { exact: true })).toBeVisible();
    await expect(wf(page).getByText("Portfolio health review", { exact: true })).toHaveCount(0);
  });

  test("5 · advisor row runs a book-level prompt", async ({ page }) => {
    await expect(wf(page)).toBeVisible({ timeout: 15000 });
    const msg = await sentPrompt(page, () => wf(page).getByTestId("wf-row-churn").click());
    expect(msg).toBe("Which clients might leave?");
  });
});
