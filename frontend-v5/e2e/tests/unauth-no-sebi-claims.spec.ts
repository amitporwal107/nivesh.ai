/**
 * Compliance P0-1 (test_reports/compliance_p0_TESTCASES.md, TC-1): Nivesh holds no SEBI registration,
 * so no public page may describe it as "SEBI-aligned" / "SEBI-compliant". Citations of SEBI data and
 * "consult a SEBI-registered adviser" remain allowed.
 *
 * Runs in the `unauthenticated` project (filename matches /unauth/). No API is needed for these pages.
 */
import { expect, test } from "@playwright/test";

const CLAIM = /SEBI[-\s]?(aligned|compliant|approved|certified)/i;

const PAGES: { path: string; keeps?: (string | RegExp)[] }[] = [
  { path: "/v5/", keeps: ["ARN-128459", "Read-only access"] },
  { path: "/v5/about", keeps: ["ARN-128459", /subject to market risk/i] },
  { path: "/v5/contact", keeps: ["ARN-128459"] },
  { path: "/v5/product", keeps: ["Read-only access"] },
  { path: "/v5/security", keeps: ["ARN-128459"] },
  { path: "/v5/login", keeps: ["ARN-128459"] },
  { path: "/v5/blog/nivesh-copilot-2-minute-tour", keeps: ["Read-only analysis"] },
  { path: "/v5/blog/mutual-fund-investing-best-practices", keeps: ["Read-only analysis"] },
  { path: "/v5/blog/why-indian-retail-investors-lose-money", keeps: ["Read-only analysis"] },
];

for (const p of PAGES) {
  test(`no SEBI-status claim on ${p.path}`, async ({ page }) => {
    await page.goto(p.path);
    const body = page.locator("body");
    for (const k of p.keeps ?? []) {
      await expect(body).toContainText(k);          // the page rendered, and kept what it should
    }
    await expect(body).not.toContainText(CLAIM);
  });
}
