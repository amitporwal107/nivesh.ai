/**
 * Post-login destination — web vs native (mobile APK).
 *
 * The mobile build ships only the one-screen Copilot, so finishLogin() in
 * src/pages/Login/index.tsx sends a NATIVE sign-in to /app instead of
 * /dashboard. Web routing, the login screen and the homepage must be untouched.
 *
 * Capacitor 6 resolves the platform from `window.androidBridge`, so defining it
 * before the bundle loads is what makes isNativePlatform() true in a desktop
 * browser. Sign-in is driven through the email-OTP path — Google OAuth cannot
 * be automated.
 */
import { test, expect, type Page } from "@playwright/test";

type Profile = Record<string, unknown>;

const user: Profile = {
  user_id: "u-test-1",
  email: "test@gmail.com",
  name: "Test User",
  is_admin: false,
  workspace_type: null,
  onboarding_completed: true,
  copilot_enabled: true,
  features: {},
};

async function asNative(page: Page) {
  await page.addInitScript(() => {
    (window as unknown as { androidBridge: unknown }).androidBridge = {
      postMessage: () => {},
    };
  });
}

async function mockAuth(page: Page, profile: Profile = user) {
  // Order matters: Playwright matches routes in REVERSE registration order, so
  // the catch-all goes FIRST or it shadows the specific auth handlers below
  // (and an empty {} fails the OtpRequestRes / UserProfile zod parse).
  // Everything the destination screens ask for: answer, don't hang.
  await page.route("**/api/**", (r) => r.fulfill({ json: {} }));
  await page.route("**/api/auth/otp/request", (r) =>
    r.fulfill({ json: { message: "Code sent", expires_in_minutes: 10 } }),
  );
  await page.route("**/api/auth/otp/verify", (r) => r.fulfill({ json: profile }));
  await page.route("**/api/auth/me", (r) => r.fulfill({ json: profile }));
}

async function signInWithOtp(page: Page) {
  await page.goto("/v5/login");
  await page.getByPlaceholder(/you@company/i).fill("test@gmail.com");
  await page.getByRole("button", { name: /Send code/i }).click();
  await page.locator("#otp").fill("123456");
  await page.getByRole("button", { name: /Verify & sign in/i }).click();
}

test("TC-4 web sign-in still lands on /dashboard", async ({ page }) => {
  await mockAuth(page);
  await signInWithOtp(page);
  await expect(page).toHaveURL(/\/v5\/dashboard/);
});

test("TC-3 native sign-in lands on /app (one-screen Copilot)", async ({ page }) => {
  await asNative(page);
  await mockAuth(page);
  await signInWithOtp(page);
  await expect(page).toHaveURL(/\/v5\/app/);
});

test("TC-5 research-only user still lands on /research (native)", async ({ page }) => {
  await asNative(page);
  await mockAuth(page, { ...user, features: { research_only: true } });
  await signInWithOtp(page);
  await expect(page).toHaveURL(/\/v5\/research/);
});

test("TC-6 login screen is unchanged in the native build", async ({ page }) => {
  await asNative(page);
  await mockAuth(page);
  await page.goto("/v5/login");
  // Same email + OTP form the web build shows; nothing added or removed.
  await expect(page.getByPlaceholder(/you@company/i)).toBeVisible();
  await expect(page.getByRole("button", { name: /Send code/i })).toBeDisabled();
  await page.getByPlaceholder(/you@company/i).fill("test@gmail.com");
  await expect(page.getByRole("button", { name: /Send code/i })).toBeEnabled();
});

test("TC-7 homepage still renders at / in the native build", async ({ page }) => {
  await asNative(page);
  await mockAuth(page);
  await page.goto("/v5/");
  await expect(page.locator(".nvx-mark").first()).toBeVisible();
  await expect(page).toHaveURL(/\/v5\/$/);
});
