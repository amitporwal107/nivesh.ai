/**
 * OAuth branding fixes — /v5/
 * Verifies the fixes for Google's OAuth branding-verification rejection:
 *  1+2) The raw /v5/ HTML (fetched WITHOUT running JS, as Google's branding
 *       crawler does) exposes the app name, its purpose, its Gmail data use,
 *       and links to the privacy/terms pages — so it no longer reads as
 *       "behind a login page" / "does not explain the purpose".
 *   -)  The Privacy page states the required Google API Services "Limited Use"
 *       disclosure (blocks the restricted-scope review otherwise).
 */
import { test, expect } from "@playwright/test";

test.describe("OAuth branding — crawlable landing shell (non-JS fetch)", () => {
  test("raw /v5/ HTML carries a purpose-bearing meta description", async ({ page }) => {
    const res = await page.request.get("/v5/");
    expect(res.ok()).toBeTruthy();
    const html = await res.text();
    expect(html).toContain('name="description"');
    expect(html).toMatch(/portfolio-intelligence copilot for Indian investors/i);
  });

  test("raw /v5/ HTML has a <noscript> fallback describing the app + legal links", async ({ page }) => {
    const html = await (await page.request.get("/v5/")).text();
    expect(html).toContain("<noscript>");
    // purpose
    expect(html).toMatch(/reads every[\s\S]{0,40}holding/i);
    // Gmail data use, read-only
    expect(html).toContain("read-only");
    expect(html).toMatch(/Gmail/);
    expect(html).toMatch(/CAS statements/);
    // public legal links, viewable without login
    expect(html).toContain('href="/v5/privacy"');
    expect(html).toContain('href="/v5/terms"');
  });
});

test.describe("OAuth branding — Privacy Limited Use disclosure", () => {
  test("privacy page renders the Google API Services Limited Use text + link", async ({ page }) => {
    await page.goto("/v5/privacy");
    await expect(page.getByText(/Limited Use requirements/i)).toBeVisible();
    const link = page.getByRole("link", { name: /Google API Services User Data Policy/i });
    await expect(link).toBeVisible();
    await expect(link).toHaveAttribute(
      "href",
      "https://developers.google.com/terms/api-services-user-data-policy",
    );
  });
});
