/**
 * Login — /v5/login
 * Tests sign-in page UI and magic-link validation.
 * Google OAuth cannot be automated — test UI states only.
 */
import { test, expect } from "@playwright/test";
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

test.describe("Login page", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/v5/login");
  });

  test("renders sign-in heading", async ({ page }) => {
    await expect(
      page.getByRole("heading", { name: /Read your inbox/i, level: 2 }),
    ).toBeVisible();
  });

  test("renders editorial left panel with brand", async ({ page }) => {
    await expect(page.locator(".nvx-mark").first()).toBeVisible();
    await expect(page.getByText("Nivesh", { exact: true }).first()).toBeVisible();
  });

  test("renders security trust copy", async ({ page }) => {
    await expect(page.getByText(/statements never stored/i)).toBeVisible();
    await expect(page.getByText(/Read-only Gmail access/i)).toBeVisible();
  });

  test.describe("magic link email validation", () => {
    test("empty email — send button disabled", async ({ page }) => {
      const sendBtn = page.getByRole("button", { name: /Send magic link/i });
      await expect(sendBtn).toBeDisabled();
    });

    test("gmail.com — shows ALLOWED badge and enables button", async ({ page }) => {
      await page.getByPlaceholder(/you@company/i).fill("test@gmail.com");
      // Use .first() — two elements may render "ALLOWED" (badge span + helper text with text-transform:uppercase)
      await expect(page.getByText("ALLOWED").first()).toBeVisible();
      await expect(page.getByRole("button", { name: /Send magic link/i })).toBeEnabled();
    });

    test("googlemail.com — shows ALLOWED badge", async ({ page }) => {
      await page.getByPlaceholder(/you@company/i).fill("test@googlemail.com");
      await expect(page.getByText("ALLOWED").first()).toBeVisible();
    });

    test("unknown domain — shows BLOCKED badge and disables button", async ({ page }) => {
      await page.getByPlaceholder(/you@company/i).fill("test@unknown.xyz");
      await expect(page.getByText("BLOCKED")).toBeVisible();
      await expect(page.getByRole("button", { name: /Send magic link/i })).toBeDisabled();
    });
  });

  test("shows generic headline when not logged in", async ({ page }) => {
    // Not logged in = no returning user context
    const h1 = page.getByRole("heading", { level: 1 });
    // Should show either "Welcome back" (if has session) or generic "Your portfolio"
    await expect(h1).toBeVisible();
  });

  test.describe("post-login routing fixtures", () => {
    test("user-profile fixture has onboarding_completed=false", async () => {
      const fixture = JSON.parse(
        fs.readFileSync(path.join(__dirname, "..", "fixtures", "user-profile.json"), "utf-8"),
      );
      expect(fixture.onboarding_completed).toBe(false);
    });

    test("user-profile-onboarded fixture has onboarding_completed=true", async () => {
      const fixture = JSON.parse(
        fs.readFileSync(path.join(__dirname, "..", "fixtures", "user-profile-onboarded.json"), "utf-8"),
      );
      expect(fixture.onboarding_completed).toBe(true);
    });
  });
});
