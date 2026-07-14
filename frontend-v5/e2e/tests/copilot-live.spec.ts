/**
 * Copilot tour — "make the demo live" wiring (/v5/copilot).
 *
 * The tour is a public, static marketing page. This suite verifies the change
 * that turns its mockups into live controls that route into the REAL copilot
 * at /chat, carrying the question as a `?q=` deep-link.
 *
 * Technique: the app boots behind an auth check, so we answer `/api/auth/me`
 * with a 401 (a logged-out visitor) — the public tour still renders. Clicking a
 * live control then navigates to `/chat?q=...`; because /chat is auth-gated,
 * RequireAuth immediately redirects a logged-out visitor to /login, so the
 * final URL is /login. To read the exact question that was carried, we
 * instrument history.pushState/replaceState and capture the transient
 * `/chat?q=...` entry before the redirect (see `openedCopilot`).
 *
 * Acceptance criteria:
 *  1. The tour still renders (hero + sticky sub-nav) — no regression.
 *  2. The desktop "Ask" composer is a real input; typing + send opens
 *     /chat?q=<the typed question>.
 *  3. An Intake quick-chip opens /chat?q=<chip text> (tick stripped).
 *  4. An investor workflow card opens /chat?q=<its prompt>.
 *  5. An advisor workflow card opens /chat?q=<its prompt>.
 *  6. An all-flows ASK bubble opens /chat?q=<its question>.
 *  7. The mobile composer opens /chat?q=<typed question>.
 *  8. A mobile primary CTA opens the real copilot (/chat), then /login.
 *  9. The mobile viewport has no horizontal body overflow (the layout fix).
 */
import { test, expect, Page } from "@playwright/test";

const setup = async (page: Page) => {
  // Record every SPA navigation so we can read the transient /chat?q=... target
  // even though RequireAuth then redirects a logged-out visitor to /login.
  await page.addInitScript(() => {
    (window as any).__nav = [];
    for (const m of ["pushState", "replaceState"] as const) {
      const orig = (history as any)[m].bind(history);
      (history as any)[m] = (...a: any[]) => {
        const r = orig(...a);
        (window as any).__nav.push(location.pathname + location.search);
        return r;
      };
    }
  });
  // Logged-out visitor: the public tour renders; protected /chat bounces to /login.
  await page.route("**/api/auth/me**", (r) =>
    r.fulfill({ status: 401, contentType: "application/json", body: '{"code":"AUTH-001","message":"Invalid session"}' }),
  );
  await page.goto("/v5/copilot");
  await page.locator(".copilot-tour").waitFor({ state: "attached", timeout: 30000 });
};

/** Wait for a click to open the copilot; return the question it carried (or null). */
const openedCopilot = async (page: Page): Promise<{ opened: boolean; q: string | null }> => {
  await page.waitForFunction(() => ((window as any).__nav || []).some((u: string) => u.includes("/chat")), undefined, {
    timeout: 8000,
  });
  const nav: string[] = await page.evaluate(() => (window as any).__nav);
  const entry = nav.find((u) => u.includes("/chat")) || "";
  const q = entry.includes("?q=")
    ? decodeURIComponent(new URLSearchParams(entry.split("?")[1]).get("q") || "")
    : null;
  return { opened: !!entry, q };
};

test.describe("Copilot tour — live wiring", () => {
  test.beforeEach(async ({ page }) => {
    await setup(page);
  });

  test("1 · tour still renders (hero + sub-nav)", async ({ page }) => {
    await expect(page.getByRole("heading", { level: 1 })).toContainText("one thing to fix first");
    await expect(page.locator(".ct-subnav")).toBeVisible();
  });

  test("2 · desktop composer routes typed question into /chat", async ({ page }) => {
    const screens = page.locator("#ct-screens");
    const input = screens.locator("input").first();
    await input.scrollIntoViewIfNeeded();
    await input.fill("Am I too concentrated in banks?");
    await screens.getByRole("button", { name: "Ask" }).first().click();
    expect(await openedCopilot(page)).toEqual({ opened: true, q: "Am I too concentrated in banks?" });
  });

  test("3 · intake quick-chip opens copilot with the chip text", async ({ page }) => {
    const chip = page.locator("#ct-screens").getByText("Grow wealth", { exact: true }).first();
    await chip.scrollIntoViewIfNeeded();
    await chip.click();
    expect(await openedCopilot(page)).toEqual({ opened: true, q: "Grow wealth" });
  });

  test("4 · investor workflow card opens copilot with its prompt", async ({ page }) => {
    const card = page.locator("#ct-workflows .ct-wf").first();
    await card.scrollIntoViewIfNeeded();
    await card.click();
    expect(await openedCopilot(page)).toEqual({ opened: true, q: "What's the one thing I should fix first?" });
  });

  test("5 · advisor workflow card opens copilot with its prompt", async ({ page }) => {
    const card = page.locator("#ct-advisor .ct-wf").first();
    await card.scrollIntoViewIfNeeded();
    await card.click();
    expect(await openedCopilot(page)).toEqual({ opened: true, q: "How's my book doing this quarter?" });
  });

  test("6 · all-flows ASK bubble opens copilot with its question", async ({ page }) => {
    const ask = page.locator("#ct-allflows .ct-pb").first();
    await ask.scrollIntoViewIfNeeded();
    await ask.click();
    expect(await openedCopilot(page)).toEqual({ opened: true, q: "What's the one thing I should fix first?" });
  });

  test("8 · mobile primary CTA enters the real copilot", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    const cta = page.locator("#ct-mobile").getByText("Review & apply", { exact: false }).first();
    await cta.scrollIntoViewIfNeeded();
    await cta.click();
    const res = await openedCopilot(page);
    expect(res.opened).toBe(true);
    expect(res.q).toBe("Review and apply my top 3 actions");
  });

  test("9 · mobile viewport has no horizontal body overflow", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.waitForTimeout(300);
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );
    expect(overflow).toBeLessThanOrEqual(2);
  });
});

test.describe("Copilot tour — mobile composer", () => {
  test.use({ viewport: { width: 390, height: 844 } });
  test.beforeEach(async ({ page }) => {
    await setup(page);
  });

  test("7 · mobile composer routes typed question into /chat", async ({ page }) => {
    const input = page.locator("#ct-mobile input").first();
    await input.scrollIntoViewIfNeeded();
    await input.fill("What should I fix first?");
    await input.press("Enter");
    expect(await openedCopilot(page)).toEqual({ opened: true, q: "What should I fix first?" });
  });
});
