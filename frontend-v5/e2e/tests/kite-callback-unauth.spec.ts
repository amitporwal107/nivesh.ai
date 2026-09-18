import { test, expect } from "@playwright/test";

/**
 * /v5/kite-callback — the page Kite Connect redirects to after a Zerodha login.
 *
 * Runs in the `unauthenticated` project (filename matches /unauth/): the operator
 * returning from Kite may not hold a Nivesh session, so the page must render without
 * one and must not bounce to /login (which would drop the single-use token).
 */

const TOKEN = "CFBFWfOtCzkBZK9yQMF65aMLADT2Ug6xTESTONLY";

test.describe("Kite callback page", () => {
  test("TC-KC1 shows the request_token when Kite reports success", async ({ page }) => {
    await page.goto(`/v5/kite-callback?request_token=${TOKEN}&action=login&status=success`);
    await expect(page.getByText("Kite login complete")).toBeVisible();
    await expect(page.getByTestId("kite-request-token")).toHaveText(TOKEN);
    await expect(page.getByTestId("kite-callback-error")).toHaveCount(0);
  });

  test("TC-KC2 shows an error and no token when the callback carries none", async ({ page }) => {
    await page.goto("/v5/kite-callback?status=error&error_description=User%20cancelled%20login");
    await expect(page.getByText("Kite login failed")).toBeVisible();
    await expect(page.getByTestId("kite-callback-error")).toHaveText("User cancelled login");
    await expect(page.getByTestId("kite-request-token")).toHaveCount(0);
  });

  test("TC-KC3 renders without a session and keeps the query string (no /login bounce)", async ({ page }) => {
    await page.goto(`/v5/kite-callback?request_token=${TOKEN}&action=login&status=success`);
    await expect(page.getByTestId("kite-request-token")).toBeVisible();
    const url = new URL(page.url());
    expect(url.pathname).toBe("/v5/kite-callback");
    expect(url.searchParams.get("request_token")).toBe(TOKEN);
  });

  test("TC-KC4 never writes the token to browser storage", async ({ page }) => {
    await page.goto(`/v5/kite-callback?request_token=${TOKEN}&action=login&status=success`);
    await expect(page.getByTestId("kite-request-token")).toBeVisible();
    const stored = await page.evaluate(() => {
      const dump = (s: Storage) => Array.from({ length: s.length }, (_, i) => s.getItem(s.key(i)!) ?? "").join("|");
      return dump(window.localStorage) + "||" + dump(window.sessionStorage);
    });
    expect(stored).not.toContain(TOKEN);
  });

  test("TC-KC5 copy button puts the exact token on the clipboard", async ({ page, context }) => {
    await context.grantPermissions(["clipboard-read", "clipboard-write"]);
    await page.goto(`/v5/kite-callback?request_token=${TOKEN}&action=login&status=success`);
    await page.getByTestId("kite-copy-token").click();
    await expect(page.getByTestId("kite-copy-token")).toHaveText("Copied");
    expect(await page.evaluate(() => navigator.clipboard.readText())).toBe(TOKEN);
  });

  test("TC-KC6 a long token wraps at phone width (no horizontal scroll)", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto(`/v5/kite-callback?request_token=${TOKEN.repeat(3)}&action=login&status=success`);
    await expect(page.getByTestId("kite-request-token")).toBeVisible();
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    expect(overflow).toBeLessThanOrEqual(0);
  });
});
