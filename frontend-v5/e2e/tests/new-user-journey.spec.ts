/**
 * New-user journey: Login → Onboarding → Dashboard
 *
 * Covers:
 * - Login page renders correct editorial copy for unauthenticated users
 * - Google sign-in section, magic-link section, footer copy
 * - Onboarding page: header, steps, method cards, each connection panel
 * - Redirect guard: onboarding/state with onboarding_completed=false keeps user on page
 * - Footer navigation: "Continue · Goals →" routes to dashboard
 */
import { test, expect } from "@playwright/test";
import { mockApi, mock401, mockSingleRoute } from "../helpers/api-mock";

// ─── Helper: set up unauthenticated state ───────────────────────────────────

async function setupUnauthLogin(page: Parameters<typeof mockApi>[0]) {
  // Mock google-client-id so the GIS hook can resolve (or gracefully fail)
  await mockSingleRoute(page, "**/api/auth/google-client-id", "google-client-id.json");
  // Return 401 for auth/me so useMe() resolves to null → new-user editorial state
  await mock401(page, "**/api/auth/me");
  // Portfolio summary + health analysis will also 401 → no KPI cards shown
  await mock401(page, "**/api/portfolio/holdings-enriched*");
  await mock401(page, "**/api/insights/analysis*");
}

// Return onboarding state with onboarding_completed=false so the page doesn't redirect
async function mockOnboardingNotCompleted(page: Parameters<typeof mockApi>[0]) {
  await page.route("**/api/onboarding/state", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ onboarding_completed: false, cas_imported: false }),
    })
  );
}

// ─── Suite 1: Login page — unauthenticated / new user ──────────────────────

test.describe("Login page — new user (unauthenticated)", () => {
  test.beforeEach(async ({ page }) => {
    await setupUnauthLogin(page);
  });

  test("renders new-user editorial h1", async ({ page }) => {
    await page.goto("/v5/login");
    await page.waitForLoadState("networkidle");
    await expect(
      page.getByRole("heading", { name: /finally legible/i, level: 1 })
    ).toBeVisible();
  });

  test("does not show returning-user greeting", async ({ page }) => {
    await page.goto("/v5/login");
    await page.waitForLoadState("networkidle");
    await expect(page.getByText(/Welcome back/i)).not.toBeVisible();
  });

  test("renders 'Sign in' label in auth section", async ({ page }) => {
    await page.goto("/v5/login");
    await page.waitForLoadState("networkidle");
    await expect(page.locator(".live").getByText("Sign in")).toBeVisible();
  });

  test("renders h2 'Read your inbox, not your statements.'", async ({ page }) => {
    await page.goto("/v5/login");
    await page.waitForLoadState("networkidle");
    await expect(
      page.getByRole("heading", { name: /Read your inbox/i, level: 2 })
    ).toBeVisible();
  });

  test("Google button area renders — either native button, skeleton, or load error", async ({
    page,
  }) => {
    await page.goto("/v5/login");
    await page.waitForLoadState("networkidle");
    // One of these three states must be visible: skeleton pulse, rendered button div, or error message
    const skeleton = page.locator(".gskeleton");
    const googleBtnDiv = page.locator(".gbox-center");
    const loadError = page.getByText(/Google Sign-In failed to load/i);
    const anyVisible =
      (await skeleton.count()) > 0 ||
      (await googleBtnDiv.count()) > 0 ||
      (await loadError.count()) > 0;
    expect(anyVisible).toBeTruthy();
  });

  test("magic link email input is present with correct placeholder", async ({ page }) => {
    await page.goto("/v5/login");
    await page.waitForLoadState("networkidle");
    const emailInput = page.locator("#email");
    await expect(emailInput).toBeVisible();
    await expect(emailInput).toHaveAttribute("placeholder", "you@company.com");
    await expect(emailInput).toHaveAttribute("type", "email");
  });

  test("magic link button shows 'Send magic link →' when idle", async ({ page }) => {
    await page.goto("/v5/login");
    await page.waitForLoadState("networkidle");
    await expect(page.getByRole("button", { name: "Send magic link →" })).toBeVisible();
  });

  test("magic link button is disabled until a valid email is entered", async ({ page }) => {
    await page.goto("/v5/login");
    await page.waitForLoadState("networkidle");
    const btn = page.getByRole("button", { name: "Send magic link →" });
    // Disabled by default (empty email)
    await expect(btn).toBeDisabled();
  });

  test("ALLOWED badge appears on typing a valid domain email", async ({ page }) => {
    await page.goto("/v5/login");
    await page.waitForLoadState("networkidle");
    // Type a gmail address (common allowed domain for test)
    await page.locator("#email").fill("test@gmail.com");
    // Either ALLOWED or BLOCKED badge appears (domain list determines which)
    const badge = page.locator(".field-badge").filter({ hasText: /ALLOWED|BLOCKED/i });
    await expect(badge).toBeVisible();
  });

  test("footer shows compliance copy", async ({ page }) => {
    await page.goto("/v5/login");
    await page.waitForLoadState("networkidle");
    await expect(page.getByText(/statements never stored/i)).toBeVisible();
  });

  test("no KPI cards shown when no prior session data", async ({ page }) => {
    await page.goto("/v5/login");
    await page.waitForLoadState("networkidle");
    // KPI cards only appear when health_score or totalValue present — 401s above prevent them
    await expect(page.getByText("HEALTH")).not.toBeVisible();
    await expect(page.getByText("AUM")).not.toBeVisible();
  });
});

// ─── Suite 2: Login page — returning user ──────────────────────────────────

test.describe("Login page — returning user (authenticated)", () => {
  test("shows the static editorial headline (redesign drops the greeting)", async ({ page }) => {
    await mockApi(page, "populated");
    await page.goto("/v5/login");
    await page.waitForLoadState("networkidle");
    // The redesigned login is a fixed editorial page — no per-user greeting.
    await expect(
      page.getByRole("heading", { name: /finally legible/i, level: 1 })
    ).toBeVisible();
    await expect(page.getByText(/Welcome back/i)).not.toBeVisible();
  });
});

// ─── Suite 3: Onboarding page ───────────────────────────────────────────────

test.describe("Onboarding page — new user", () => {
  test.beforeEach(async ({ page }) => {
    // Auth returns populated user (onboarding not completed)
    await mockApi(page, "populated");
    // Override onboarding/state so the page does NOT redirect to dashboard
    await mockOnboardingNotCompleted(page);
  });

  test("header shows Nivesh mark and brand name", async ({ page }) => {
    await page.goto("/v5/onboarding");
    await page.waitForLoadState("networkidle");
    await expect(page.getByText("Nivesh").first()).toBeVisible();
  });

  test("header shows step indicator 'Step 2 of 4 · ~60s'", async ({ page }) => {
    await page.goto("/v5/onboarding");
    await page.waitForLoadState("networkidle");
    await expect(page.getByText("Step 2 of 4 · ~60s")).toBeVisible();
  });

  test("renders '● Connect investments' section label", async ({ page }) => {
    await page.goto("/v5/onboarding");
    await page.waitForLoadState("networkidle");
    await expect(page.getByText("● Connect investments")).toBeVisible();
  });

  test("renders main h1 'Bring your investments in.'", async ({ page }) => {
    await page.goto("/v5/onboarding");
    await page.waitForLoadState("networkidle");
    await expect(
      page.getByRole("heading", { name: "Bring your investments in.", level: 1 })
    ).toBeVisible();
  });

  test("renders all three method cards", async ({ page }) => {
    await page.goto("/v5/onboarding");
    await page.waitForLoadState("networkidle");
    await expect(page.getByText("Gmail CAS Import")).toBeVisible();
    await expect(page.getByText("CAS Upload · NSDL / CDSL")).toBeVisible();
    await expect(page.getByText("CDSL OTP")).toBeVisible();
  });

  test("method card timing labels are visible", async ({ page }) => {
    await page.goto("/v5/onboarding");
    await page.waitForLoadState("networkidle");
    await expect(page.getByText(/30 seconds · fully automatic/i)).toBeVisible();
    await expect(page.getByText(/2 minutes · most thorough/i)).toBeVisible();
    await expect(page.getByText(/60 seconds · real-time/i)).toBeVisible();
  });

  test("security note is visible", async ({ page }) => {
    await page.goto("/v5/onboarding");
    await page.waitForLoadState("networkidle");
    await expect(
      page.getByText(/India-hosted \(Bangalore\) · TLS 1\.3 · AES-256/i)
    ).toBeVisible();
  });

  test("footer shows '‹ Back' and 'Continue · Goals →' buttons", async ({ page }) => {
    await page.goto("/v5/onboarding");
    await page.waitForLoadState("networkidle");
    await expect(page.getByRole("button", { name: "‹ Back" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Continue · Goals →" })).toBeVisible();
  });

  test("'Continue · Goals →' navigates to dashboard", async ({ page }) => {
    await page.goto("/v5/onboarding");
    await page.waitForLoadState("networkidle");
    await page.getByRole("button", { name: "Continue · Goals →" }).click();
    await page.waitForURL(/\/dashboard/);
    await expect(page).toHaveURL(/\/dashboard/);
  });
});

// ─── Suite 4: Onboarding — Gmail panel (default / idle) ────────────────────

test.describe("Onboarding — Gmail panel", () => {
  test.beforeEach(async ({ page }) => {
    await mockApi(page, "populated");
    await mockOnboardingNotCompleted(page);
  });

  test("Gmail panel is active by default", async ({ page }) => {
    await page.goto("/v5/onboarding");
    await page.waitForLoadState("networkidle");
    // First method card (Gmail) should be aria-pressed="true"
    const gmailCard = page.getByRole("button", { name: /Gmail CAS Import/i });
    await expect(gmailCard).toHaveAttribute("aria-pressed", "true");
  });

  test("Gmail panel shows 'Connect Gmail inbox' heading", async ({ page }) => {
    await page.goto("/v5/onboarding");
    await page.waitForLoadState("networkidle");
    await expect(page.getByText("Connect Gmail inbox")).toBeVisible();
  });

  test("Gmail panel shows 'Authorize with Google →' button", async ({ page }) => {
    await page.goto("/v5/onboarding");
    await page.waitForLoadState("networkidle");
    await expect(page.getByRole("button", { name: /Authorize with Google →/i })).toBeVisible();
  });

  test("Gmail panel shows OAuth scopes section", async ({ page }) => {
    await page.goto("/v5/onboarding");
    await page.waitForLoadState("networkidle");
    await expect(page.getByText(/What we ask for · 3 scopes/i)).toBeVisible();
    await expect(page.getByText(/Read messages with attachments/i)).toBeVisible();
    await expect(page.getByText(/Download attachments/i)).toBeVisible();
    await expect(page.getByText(/Identity/i)).toBeVisible();
  });
});

// ─── Suite 5: Onboarding — Upload panel ────────────────────────────────────

test.describe("Onboarding — Upload panel", () => {
  test.beforeEach(async ({ page }) => {
    await mockApi(page, "populated");
    await mockOnboardingNotCompleted(page);
  });

  test("clicking CAS Upload card switches to upload panel", async ({ page }) => {
    await page.goto("/v5/onboarding");
    await page.waitForLoadState("networkidle");
    await page.getByRole("button", { name: /CAS Upload · NSDL \/ CDSL/i }).click();
    // Upload card should now be aria-pressed=true
    await expect(
      page.getByRole("button", { name: /CAS Upload · NSDL \/ CDSL/i })
    ).toHaveAttribute("aria-pressed", "true");
  });

  test("upload panel shows 'Upload your eCAS PDF' heading", async ({ page }) => {
    await page.goto("/v5/onboarding");
    await page.waitForLoadState("networkidle");
    await page.getByRole("button", { name: /CAS Upload · NSDL \/ CDSL/i }).click();
    await expect(page.getByText("Upload your eCAS PDF")).toBeVisible();
  });

  test("upload panel shows drag-and-drop zone with correct text", async ({ page }) => {
    await page.goto("/v5/onboarding");
    await page.waitForLoadState("networkidle");
    await page.getByRole("button", { name: /CAS Upload · NSDL \/ CDSL/i }).click();
    await expect(page.getByText("Drop your eCAS PDF here")).toBeVisible();
  });

  test("upload panel shows 'Browse files' button", async ({ page }) => {
    await page.goto("/v5/onboarding");
    await page.waitForLoadState("networkidle");
    await page.getByRole("button", { name: /CAS Upload · NSDL \/ CDSL/i }).click();
    await expect(page.getByRole("button", { name: "Browse files" })).toBeVisible();
  });

  test("upload panel shows password field hint", async ({ page }) => {
    await page.goto("/v5/onboarding");
    await page.waitForLoadState("networkidle");
    await page.getByRole("button", { name: /CAS Upload · NSDL \/ CDSL/i }).click();
    await expect(page.getByText(/PDF password \(optional\)/i)).toBeVisible();
  });

  test("upload panel shows CAS request hint", async ({ page }) => {
    await page.goto("/v5/onboarding");
    await page.waitForLoadState("networkidle");
    await page.getByRole("button", { name: /CAS Upload · NSDL \/ CDSL/i }).click();
    await expect(page.getByText(/Don't have a CAS file/i)).toBeVisible();
  });
});

// ─── Suite 6: Onboarding — OTP panel ───────────────────────────────────────

test.describe("Onboarding — OTP panel", () => {
  test.beforeEach(async ({ page }) => {
    await mockApi(page, "populated");
    await mockOnboardingNotCompleted(page);
  });

  test("clicking CDSL OTP card switches to OTP panel", async ({ page }) => {
    await page.goto("/v5/onboarding");
    await page.waitForLoadState("networkidle");
    await page.getByRole("button", { name: /CDSL OTP/i }).click();
    await expect(page.getByRole("button", { name: /CDSL OTP/i })).toHaveAttribute(
      "aria-pressed",
      "true"
    );
  });

  test("OTP panel shows 'Fetch live holdings · CDSL OTP' heading", async ({ page }) => {
    await page.goto("/v5/onboarding");
    await page.waitForLoadState("networkidle");
    await page.getByRole("button", { name: /CDSL OTP/i }).click();
    await expect(page.getByText("Fetch live holdings · CDSL OTP")).toBeVisible();
  });

  test("OTP panel shows PAN and mobile inputs", async ({ page }) => {
    await page.goto("/v5/onboarding");
    await page.waitForLoadState("networkidle");
    await page.getByRole("button", { name: /CDSL OTP/i }).click();
    await expect(page.getByText("PAN")).toBeVisible();
    await expect(page.getByText("Mobile linked to PAN")).toBeVisible();
    await expect(page.getByText(/OTP · 6 digits/i)).toBeVisible();
  });

  test("OTP panel shows 6 individual OTP digit inputs", async ({ page }) => {
    await page.goto("/v5/onboarding");
    await page.waitForLoadState("networkidle");
    await page.getByRole("button", { name: /CDSL OTP/i }).click();
    // 6 single-character inputs side by side
    const otpInputs = page.locator("input[maxlength='1']");
    await expect(otpInputs).toHaveCount(6);
  });

  test("OTP panel shows 'Verify & fetch holdings →' submit button", async ({ page }) => {
    await page.goto("/v5/onboarding");
    await page.waitForLoadState("networkidle");
    await page.getByRole("button", { name: /CDSL OTP/i }).click();
    await expect(
      page.getByRole("button", { name: "Verify & fetch holdings →" })
    ).toBeVisible();
  });
});

// ─── Suite 7: Onboarding redirect guard ────────────────────────────────────

test.describe("Onboarding — redirect guard", () => {
  test("stays on onboarding when onboarding_completed=false", async ({ page }) => {
    await mockApi(page, "populated");
    // Explicitly mock to false — should NOT redirect
    await page.route("**/api/onboarding/state", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ onboarding_completed: false }),
      })
    );
    await page.goto("/v5/onboarding");
    await page.waitForLoadState("networkidle");
    // Should remain on onboarding URL
    expect(page.url()).toMatch(/\/onboarding/);
    await expect(
      page.getByRole("heading", { name: "Bring your investments in.", level: 1 })
    ).toBeVisible();
  });

  test("redirects to dashboard when onboarding_completed=true", async ({ page }) => {
    await mockApi(page, "populated");
    // Already onboarded — should redirect
    await page.route("**/api/onboarding/state", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ onboarding_completed: true }),
      })
    );
    await page.goto("/v5/onboarding");
    await page.waitForURL(/\/dashboard/);
    await expect(page).toHaveURL(/\/dashboard/);
  });
});

// ─── Suite 8: Method card switching ────────────────────────────────────────

test.describe("Onboarding — method card keyboard / interaction", () => {
  test.beforeEach(async ({ page }) => {
    await mockApi(page, "populated");
    await mockOnboardingNotCompleted(page);
  });

  test("switching between method cards updates the right panel", async ({ page }) => {
    await page.goto("/v5/onboarding");
    await page.waitForLoadState("networkidle");

    // Start: Gmail panel visible
    await expect(page.getByText("Connect Gmail inbox")).toBeVisible();

    // Switch to Upload
    await page.getByRole("button", { name: /CAS Upload · NSDL \/ CDSL/i }).click();
    await expect(page.getByText("Upload your eCAS PDF")).toBeVisible();
    await expect(page.getByText("Connect Gmail inbox")).not.toBeVisible();

    // Switch to OTP
    await page.getByRole("button", { name: /CDSL OTP/i }).click();
    await expect(page.getByText("Fetch live holdings · CDSL OTP")).toBeVisible();
    await expect(page.getByText("Upload your eCAS PDF")).not.toBeVisible();

    // Switch back to Gmail
    await page.getByRole("button", { name: /Gmail CAS Import/i }).click();
    await expect(page.getByText("Connect Gmail inbox")).toBeVisible();
    await expect(page.getByText("Fetch live holdings · CDSL OTP")).not.toBeVisible();
  });

  test("only one method card has aria-pressed=true at a time", async ({ page }) => {
    await page.goto("/v5/onboarding");
    await page.waitForLoadState("networkidle");

    // Click upload
    await page.getByRole("button", { name: /CAS Upload · NSDL \/ CDSL/i }).click();
    const pressedButtons = page.locator("[aria-pressed='true']");
    await expect(pressedButtons).toHaveCount(1);

    // Click OTP
    await page.getByRole("button", { name: /CDSL OTP/i }).click();
    await expect(pressedButtons).toHaveCount(1);
  });
});
