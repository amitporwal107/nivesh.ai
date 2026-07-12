/**
 * Lite surface (/lite) — only the Copilot chat, no dashboard chrome.
 *
 * Verifies the URL-pattern-gated "lite" variant added in routes.tsx +
 * components/layout/LiteLayout.tsx:
 *
 *   - /lite renders the SAME self-contained Copilot ChatPage, but under
 *     LiteLayout, which mounts NONE of AppLayout's chrome — no Sidebar
 *     (<nav aria-label="Primary">), no GlobalTickerTape.
 *   - /chat is the CONTROL: identical page, but under AppLayout, so the
 *     sidebar IS present. This proves the missing sidebar on /lite is caused
 *     by the lite layout, not by the page failing to render.
 *
 * Runs against the local Vite dev server with mocked APIs (auth/me is faked
 * by mockApi → user-profile-onboarded.json), so no real session token needed.
 */
import { test, expect } from "@playwright/test";
import { mockApi, mockSingleRoute } from "../helpers/api-mock";

const SIDEBAR = 'nav[aria-label="Primary"]';

test.describe("Lite Copilot surface", () => {
  test.beforeEach(async ({ page }) => {
    await mockApi(page, "populated");
    // ChatPage may create/read a session; keep those calls from hanging.
    await page.route("**/api/chat/sessions", (route) =>
      route.fulfill({ status: 200, contentType: "application/json", body: "[]" }),
    );
  });

  test("/lite renders the Copilot", async ({ page }) => {
    await page.goto("/v5/lite");
    await page.waitForLoadState("networkidle");
    // The self-contained Copilot renders its own "New chat" control + composer.
    await expect(page.getByText("New chat").first()).toBeVisible();
  });

  test("/lite hides the dashboard sidebar (no app chrome)", async ({ page }) => {
    await page.goto("/v5/lite");
    await page.waitForLoadState("networkidle");
    await expect(page.locator(SIDEBAR)).toHaveCount(0);
  });

  test("NOT-onboarded user on /lite is routed to onboarding (CAS upload / Gmail sync)", async ({ page }) => {
    // Same mocks, but this user has NOT completed onboarding.
    await mockSingleRoute(page, "**/api/auth/me", "user-profile.json"); // onboarding_completed: false
    await page.goto("/v5/lite");
    // Gated → sent to onboarding instead of the empty Copilot.
    await expect(page).toHaveURL(/\/v5\/onboarding$/);
    // The Connect step exposes CAS upload + Gmail sync.
    await page.getByTestId("persona-individual").click();
    await expect(page.getByText("Bring your investments in.")).toBeVisible();
    await expect(page.getByText("Gmail CAS Import")).toBeVisible();
    await expect(page.getByText("CAS Upload · NSDL / CDSL")).toBeVisible();
  });

  test("CONTROL: /chat renders the SAME Copilot WITH the sidebar", async ({ page }) => {
    await page.goto("/v5/chat");
    await page.waitForLoadState("networkidle");
    // Same page renders...
    await expect(page.getByText("New chat").first()).toBeVisible();
    // ...but here the dashboard chrome IS present. AppLayout mounts two
    // aria-label="Primary" navs (desktop Sidebar + mobile bottom nav); at the
    // 1280px desktop viewport the Sidebar (first, `hidden lg:flex`) is visible.
    // Contrast: /lite has 0 of these (see the "hides the sidebar" test above).
    await expect(page.locator(SIDEBAR)).toHaveCount(2);
    await expect(page.locator(SIDEBAR).first()).toBeVisible();
  });
});
