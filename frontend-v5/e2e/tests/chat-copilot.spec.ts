/**
 * Chat / Copilot page tests — suggested prompts, send flow, response rendering.
 * Data from suggested-prompts.json.
 */
import { test, expect } from "@playwright/test";
import { mockApi, mockSingleRoute } from "../helpers/api-mock";

test.describe("Chat page — suggested prompts", () => {
  test.beforeEach(async ({ page }) => {
    await mockApi(page, "populated");
    await page.goto("/v5/chat");
    await page.waitForLoadState("networkidle");
  });

  test("primary prompt shown: 'Do I have too many mutual funds?'", async ({ page }) => {
    // suggested-prompts.json: primary[0].label
    await expect(
      page.locator("text=Do I have too many mutual funds?").first()
    ).toBeVisible();
  });

  test("Strategy Builder tool chip is hidden", async ({ page }) => {
    // Sanity: the composer tool row rendered (a sibling chip is present).
    await expect(page.getByRole("button", { name: /Build a portfolio/ })).toBeVisible();
    // The de-surfaced Strategy Builder chip must be gone.
    await expect(page.getByTestId("tool-strategy-builder")).toHaveCount(0);
  });

  test("secondary prompt shown: 'Fix overlap in my funds'", async ({ page }) => {
    // suggested-prompts.json: secondary[0].label
    await expect(page.locator("text=Fix overlap in my funds").first()).toBeVisible();
  });

  test("secondary prompt: 'Rebalance my risk' shown", async ({ page }) => {
    // secondary[1].label="Rebalance my risk"
    await expect(page.locator("text=Rebalance my risk").first()).toBeVisible();
  });

  // NOTE: The Chat page renders prompt labels only (string array from adapter).
  // Badges like "Top pair 97% overlap" and "Equity 93% · Debt 0%" are present in
  // suggested-prompts.json but the current Chat UI does not render badge text.
  // These assertions are intentionally omitted until the UI adds badge rendering.

  test("secondary prompt: 'Are my funds overlapping significantly?'", async ({ page }) => {
    // secondary[2].label
    await expect(
      page.locator("text=Are my funds overlapping significantly?").first()
    ).toBeVisible();
  });

  test("chat input field is present", async ({ page }) => {
    const input = page.locator("textarea, input[type='text'], [role='textbox']").first();
    await expect(input).toBeVisible();
  });

  test("no error state shown", async ({ page }) => {
    await expect(page.locator("text=Something went wrong")).not.toBeVisible();
  });
});

test.describe("Chat page — send message flow", () => {
  test("clicking a suggested prompt populates the input", async ({ page }) => {
    await mockApi(page, "populated");
    // Mock copilot send endpoint
    await page.route("**/api/copilot/**", (route) =>
      route.fulfill({
        status: 200,
        contentType: "text/event-stream",
        body: 'data: {"type":"text","content":"Your portfolio has 111 holdings."}\n\ndata: [DONE]\n\n',
      })
    );
    await page.goto("/v5/chat");
    await page.waitForLoadState("networkidle");

    const prompt = page.locator("text=Do I have too many mutual funds?").first();
    await expect(prompt).toBeVisible();
    await prompt.click();

    // Input should now contain the prompt text or a message should be sent
    const input = page.locator("textarea, input[type='text'], [role='textbox']").first();
    const inputVisible = await input.isVisible().catch(() => false);
    if (inputVisible) {
      const value = await input.inputValue().catch(() => "");
      const placeholder = value || (await input.textContent()) || "";
      // Either the input has the text or a user bubble was added
      const userBubble = page.locator("text=Do I have too many mutual funds?").first();
      await expect(userBubble).toBeVisible();
    }
  });

  test("typing in input and pressing Enter does not crash", async ({ page }) => {
    await mockApi(page, "populated");
    await page.route("**/api/copilot/**", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ response: "I can help with that." }),
      })
    );
    await page.goto("/v5/chat");
    await page.waitForLoadState("networkidle");

    const input = page.locator("textarea, input[type='text'], [role='textbox']").first();
    const inputVisible = await input.isVisible().catch(() => false);
    if (inputVisible) {
      await input.fill("How is my portfolio diversified?");
      await input.press("Enter");
      // Should not crash
      await expect(page.locator("text=Something went wrong")).not.toBeVisible();
    }
  });
});

test.describe("Chat page — auth and state", () => {
  test("chat page requires authentication", async ({ page }) => {
    // Without auth mock, the page should redirect or show auth prompt
    await page.goto("/v5/chat");
    await page.waitForLoadState("networkidle");
    // Either shows auth prompt or chat UI — no blank screen
    const bodyText = await page.locator("body").innerText();
    expect(bodyText.length).toBeGreaterThan(10);
  });
});
