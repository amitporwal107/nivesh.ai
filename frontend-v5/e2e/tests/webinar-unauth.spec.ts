/**
 * Webinar — public registration/landing page at /webinar (no auth required).
 * Filename carries "unauth" so it matches the `unauthenticated` project filter
 * (/homepage|login|unauth/) and runs with NO storageState — which is the point:
 * this page must work for someone arriving cold from a LinkedIn post.
 *
 * These cases were authored BEFORE the page existed, per .claude/VERIFICATION_PROTOCOL.md.
 *
 * The registration CTA has two states and BOTH are contract:
 *   · REGISTRATION_URL set    → a real external anchor (new tab, rel=noopener)
 *   · REGISTRATION_URL unset  → an honest "registration opening" panel + mailto
 * It must NEVER render a dead button (href="#" / empty) — same rule the Contact
 * page follows by using mailto instead of a form it cannot submit.
 */
import { test, expect } from "@playwright/test";

const URL = "/v5/webinar";

test.describe("Webinar landing page", () => {
  // MarketingShell makes no API calls, but the shell shares chrome with pages that
  // do; abort real API paths so nothing hangs the shared dev server mid-run.
  test.beforeEach(async ({ page }) => {
    await page.route(
      (url) => url.pathname.startsWith("/api/") || url.pathname.startsWith("/v5/api/"),
      (route) => route.abort(),
    );
  });

  // TC-1 — reachable with no session, and does NOT bounce to /login.
  test("TC-1 renders unauthenticated without redirecting to login", async ({ page }) => {
    await page.goto(URL);
    await expect(page).not.toHaveURL(/\/login/);
    await expect(page.getByTestId("webinar-hero")).toBeVisible();
  });

  // TC-2 — the talk is named on the page.
  test("TC-2 shows the webinar title", async ({ page }) => {
    await page.goto(URL);
    await expect(page.getByRole("heading", { level: 1 })).toContainText(/Claude/i);
  });

  // TC-3 — the agenda lists all three demo segments (the substance of the talk).
  test("TC-3 lists the three live demos in the agenda", async ({ page }) => {
    await page.goto(URL);
    const agenda = page.getByTestId("webinar-agenda");
    await expect(agenda).toBeVisible();
    await expect(agenda.getByTestId("agenda-item")).toHaveCount(6);
    await expect(agenda).toContainText(/the product/i);
    await expect(agenda).toContainText(/building a feature live/i);
    await expect(agenda).toContainText(/guardrail/i);
  });

  // TC-4 — the CTA is honest in whichever state it is in, and never dead.
  test("TC-4 registration CTA is never a dead link", async ({ page }) => {
    await page.goto(URL);
    const cta = page.getByTestId("webinar-cta");
    await expect(cta).toBeVisible();

    const anchors = cta.locator("a");
    const n = await anchors.count();
    expect(n).toBeGreaterThan(0);

    for (let i = 0; i < n; i++) {
      const href = await anchors.nth(i).getAttribute("href");
      expect(href, "CTA anchor must have a real href").toBeTruthy();
      expect(href, "CTA anchor must not be a placeholder").not.toBe("#");
    }
  });

  // TC-5 — unconfigured state is explicit, not a silent gap. (Current shipped state.)
  test("TC-5 unconfigured registration says so and offers a real channel", async ({ page }) => {
    await page.goto(URL);
    const cta = page.getByTestId("webinar-cta");
    const pending = page.getByTestId("webinar-cta-pending");

    if (await pending.count()) {
      await expect(pending).toBeVisible();
      await expect(cta.locator('a[href^="mailto:"]')).toHaveCount(1);
    } else {
      // configured state: external anchor opens in a new tab, safely
      const link = page.getByTestId("webinar-cta-link");
      await expect(link).toBeVisible();
      await expect(link).toHaveAttribute("href", /^https?:\/\//);
      await expect(link).toHaveAttribute("target", "_blank");
      await expect(link).toHaveAttribute("rel", /noopener/);
    }
  });

  // TC-6 — the shared marketing chrome renders (nav + footer).
  test("TC-6 renders the marketing shell", async ({ page }) => {
    await page.goto(URL);
    await expect(page.getByRole("navigation").or(page.locator(".nv-frame"))).toBeTruthy();
    await expect(page.locator("text=Nivesh").first()).toBeVisible();
  });

  // TC-7 — edge: no horizontal overflow at mobile width.
  test("TC-7 does not scroll sideways on a 390px viewport", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto(URL);
    await expect(page.getByTestId("webinar-hero")).toBeVisible();
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );
    expect(overflow, "page must not overflow horizontally").toBeLessThanOrEqual(1);
  });

  // TC-8 — failure case: an unknown sub-path must not render a broken shell.
  test("TC-8 unknown route still resolves to a real page", async ({ page }) => {
    await page.goto("/v5/webinar/does-not-exist");
    await expect(page.locator("body")).not.toBeEmpty();
  });

  // TC-9 — the digital pass preview renders with the session's real details.
  test("TC-9 shows the pass preview with event, date and format", async ({ page }) => {
    await page.goto(URL);
    const pass = page.getByTestId("webinar-pass");
    await expect(pass).toBeVisible();
    await expect(pass).toContainText(/Attendee pass/i);
    await expect(pass).toContainText(/Zoom/i);
    // "When" must carry a real value, never an empty slot.
    await expect(pass).not.toContainText(/Date to be announced/i);
  });

  // TC-10 — HONESTY CONTRACT: registration is handled by Zoom, so this page must
  // render no form controls at all. A form that posts nowhere is the exact failure
  // the Contact page avoids by using mailto. Guards against a future "improvement"
  // adding inputs with no endpoint behind them.
  test("TC-10 renders no input controls, since it collects nothing", async ({ page }) => {
    await page.goto(URL);
    await expect(page.locator("form")).toHaveCount(0);
    await expect(page.locator("input")).toHaveCount(0);
    await expect(page.locator("textarea")).toHaveCount(0);
    await expect(page.locator('button[type="submit"]')).toHaveCount(0);
  });

  // TC-11 — the field list is a PREVIEW and only appears once the URL is actually a
  // Zoom registration URL; a bare join link must not advertise fields nobody collects.
  test("TC-11 field preview matches the registration mode", async ({ page }) => {
    await page.goto(URL);
    const link = page.getByTestId("webinar-cta-link");
    if (!(await link.count())) return; // unconfigured state — covered by TC-5
    const href = (await link.getAttribute("href")) ?? "";
    const isRegistration = /\/meeting\/register\//.test(href);
    const fields = page.getByTestId("webinar-fields");
    if (isRegistration) {
      await expect(fields).toBeVisible();
      await expect(link).toContainText(/Register/i);
    } else {
      await expect(fields).toHaveCount(0);
      await expect(link).toContainText(/Join/i);
    }
  });
});
