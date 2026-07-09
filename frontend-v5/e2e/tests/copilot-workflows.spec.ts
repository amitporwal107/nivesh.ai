/**
 * Copilot chat workflow landing (/v5/chat) — replaces the old conversational
 * onboarding with a persona-aware workflow LIST (default) + a guided-tour
 * stepper through the full tiles. Clicking a row / tile runs the workflow on the
 * user's real portfolio via submitMessage → POST /api/chat/stream.
 *
 * Auth-gated page: we answer /api/auth/me with 200 (investor, or
 * workspace_type:"ADVISORY") to render it.
 *
 * Acceptance criteria:
 *  1. Fresh chat → the workflow landing renders as an investor list.
 *  2. Clicking a workflow row sends that workflow's prompt to /api/chat/stream.
 *  3. "Guided tour" opens the stepper; Next advances; "Run" sends the prompt.
 *  4. Advisor persona shows the advisor book workflows, not the investor ones.
 *  5. Advisor guided tour opens on the advisor's first workflow.
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

test.describe("Copilot chat workflow landing — investor", () => {
  test.beforeEach(async ({ page }) => { await setup(page); });

  test("1 · default landing is the investor workflow list", async ({ page }) => {
    await expect(wf(page)).toBeVisible({ timeout: 15000 });
    await expect(wf(page)).toHaveAttribute("data-role", "investor");
    await expect(wf(page).getByTestId("workflow-list")).toBeVisible();
    await expect(wf(page).getByText("Portfolio health review", { exact: true })).toBeVisible();
    await expect(wf(page).getByText("Too many funds?", { exact: true })).toBeVisible();
  });

  test("2 · clicking a workflow row runs it on the portfolio", async ({ page }) => {
    await expect(wf(page)).toBeVisible({ timeout: 15000 });
    const msg = await sentPrompt(page, () => wf(page).getByTestId("wf-row-health").click());
    expect(msg).toBe("What's the one thing I should fix first?");
  });

  test("3 · guided tour steps through tiles and Run sends the prompt", async ({ page }) => {
    await expect(wf(page)).toBeVisible({ timeout: 15000 });
    await wf(page).getByTestId("guided-tour").click();
    await expect(wf(page).getByTestId("tour-stepper")).toBeVisible();
    // step 1 tile = Portfolio health review, with the 4 stages
    await expect(wf(page).getByText("Portfolio health review", { exact: true })).toBeVisible();
    for (const s of ["ASK", "ANALYZE", "DECIDE", "ACT"]) {
      await expect(wf(page).getByText(s, { exact: true }).first()).toBeVisible();
    }
    await wf(page).getByTestId("tour-next").click(); // → workflow 02
    await expect(wf(page).getByText("Fund deep-dive", { exact: true })).toBeVisible();
    const msg = await sentPrompt(page, () => wf(page).getByRole("button", { name: /Run this on my portfolio/ }).click());
    expect(msg).toBe("Is HDFC Flexi Cap still worth holding?");
  });
});

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

test.describe("Copilot chat workflow landing — advisor viewing a client", () => {
  const ADVISOR_ME = { ...ME, workspace_type: "ADVISORY" };
  test.beforeEach(async ({ page }) => { await setup(page, ADVISOR_ME, "client-97909"); });

  test("6 · impersonating a client shows INVESTOR workflows, not the book", async ({ page }) => {
    // Advisor account, but "viewing a client" → the copilot answers in investor
    // mode for that portfolio, so the landing must show the investor workflows.
    await expect(wf(page)).toHaveAttribute("data-role", "investor", { timeout: 15000 });
    await expect(wf(page).getByText("Portfolio health review", { exact: true })).toBeVisible();
    await expect(wf(page).getByText("At-risk & churn", { exact: true })).toHaveCount(0);
  });
});
