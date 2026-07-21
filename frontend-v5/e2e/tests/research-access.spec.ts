/**
 * Research access-control — desktop (mocked layer).
 *
 * Covers the `research` / `research_only` feature entitlements:
 *   · a research-only user (research_only flag) is CONFINED to /research —
 *     every authenticated app route redirects there, and the surface offers a
 *     sign-out affordance (there is no app sidebar);
 *   · a full user with the `research` feature sees a Research nav entry and is
 *     NOT confined.
 *
 * Runs on desktop-chrome (1280×800). auth/me is mocked from fixtures, so no
 * session token is needed.
 */
import { test, expect } from "@playwright/test";
import { mockApi, mockAuthAs } from "../helpers/api-mock";

test.describe("Research-only user is confined to /research", () => {
  test.use({ viewport: { width: 1280, height: 800 } });

  const RESEARCH_ONLY = "user-profile-research-only.json";

  test("hitting /dashboard redirects to /research", async ({ page }) => {
    await mockAuthAs(page, RESEARCH_ONLY);
    await page.goto("/v5/dashboard");
    await expect(page).toHaveURL(/\/v5\/research$/);
  });

  test("hitting /onboarding redirects to /research (onboarding skipped)", async ({ page }) => {
    await mockAuthAs(page, RESEARCH_ONLY);
    await page.goto("/v5/onboarding");
    await expect(page).toHaveURL(/\/v5\/research$/);
  });

  test("hitting /lite redirects to /research", async ({ page }) => {
    await mockAuthAs(page, RESEARCH_ONLY);
    await page.goto("/v5/lite");
    await expect(page).toHaveURL(/\/v5\/research$/);
  });

  test("/research itself is reachable (not redirected)", async ({ page }) => {
    await mockAuthAs(page, RESEARCH_ONLY);
    await page.goto("/v5/research");
    await expect(page).toHaveURL(/\/v5\/research$/);
    // The Research surface rendered (its feed rail icon is present).
    await expect(page.getByTestId("rail-feed")).toBeVisible();
  });

  // Held back from this push: the Research-surface account/sign-out menu lives in
  // pages/Research/index.tsx, which is currently entangled with an unrelated
  // (BLOCKED) video-tour change from another session. Ships — and this test
  // un-skips — once that file can be committed cleanly. Nobody is confined yet
  // (research_only allowlist is empty), so no user is stranded meanwhile.
  test.skip("Research surface offers an account menu with email + Sign out", async ({ page }) => {
    await mockAuthAs(page, RESEARCH_ONLY);
    await page.goto("/v5/research");

    await page.getByTestId("research-account-btn").click();
    const menu = page.getByTestId("research-account-menu");
    await expect(menu).toBeVisible();
    await expect(menu.getByText("research.pilot@example.com")).toBeVisible();
    await expect(page.getByTestId("research-signout")).toBeVisible();
  });
});

test.describe("Full user with the research feature", () => {
  test.use({ viewport: { width: 1280, height: 800 } });

  test("desktop sidebar shows a Research nav link to /research", async ({ page }) => {
    await mockApi(page, "populated"); // onboarded fixture now carries features.research
    await page.goto("/v5/dashboard");

    const link = page.getByRole("link", { name: "Research" });
    await expect(link).toBeVisible();
    await expect(link).toHaveAttribute("href", /\/research$/);
  });

  test("is NOT confined — /dashboard stays on /dashboard", async ({ page }) => {
    await mockApi(page, "populated");
    await page.goto("/v5/dashboard");
    await expect(page).toHaveURL(/\/v5\/dashboard$/);
  });
});
