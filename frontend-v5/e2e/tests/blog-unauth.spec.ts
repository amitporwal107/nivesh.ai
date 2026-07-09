/**
 * Blog — public marketing blog (no auth required).
 * Covers: homepage "From the blog" section, blog index (/blog), and the
 * article reader (/blog/:slug) for the seeded retail-losses post.
 * Filename matches the `unauthenticated` project's /homepage|login|unauth/ filter.
 */
import { test, expect } from "@playwright/test";

const SLUG = "why-indian-retail-investors-lose-money";
const TITLE_RE = /Why Indian retail investors lose money/i;
const MF_SLUG = "mutual-fund-investing-best-practices";
const MF_TITLE_RE = /Mutual fund investing/i;
// Newest posts (top of POSTS → shown in the homepage's top-3 slice).
const HEAL_SLUG = "self-healing-software-autonomous-fixes";
const HEAL_TITLE_RE = /Self-healing software/i;
const CLAUDE_SLUG = "how-we-build-with-claude";
const CLAUDE_TITLE_RE = /How we build with Claude/i;
// Conversational investor-education batch (now the newest → top of the homepage slice).
const TOP_SLUG = "types-of-mutual-funds-india";
const TOP_TITLE_RE = /Types of mutual funds/i;
const CONV = [
  { slug: "types-of-mutual-funds-india", re: /Types of mutual funds/i, phrase: /which one should I actually pick/i },
  { slug: "sip-vs-lumpsum", re: /SIP vs lump sum/i, phrase: /When SIP wins/i },
  { slug: "tax-harvesting-mutual-funds", re: /Tax harvesting/i, phrase: /loss harvesting/i },
  { slug: "direct-vs-regular-mutual-funds", re: /Direct vs regular/i, phrase: /How to move to Direct/i },
];

test.describe("Blog", () => {
  // The homepage fires /api/insights/analysis + portfolio-summary on load. With no backend
  // in the local Playwright harness these requests HANG, and the open connections degrade
  // the shared dev server across the run → flaky homepage renders. Abort them so nothing
  // hangs (logged-out → the homepage falls back to its sample portfolio). Blog pages
  // (MarketingShell) make no API calls, so this only stabilises the homepage-touching tests.
  test.beforeEach(async ({ page }) => {
    // Predicate (not a glob) so we only touch real API endpoints — a glob like **/api/**
    // also matches Vite source modules such as /v5/src/services/api/http.ts and breaks the app.
    await page.route(
      (url) => url.pathname.startsWith("/api/") || url.pathname.startsWith("/v5/api/"),
      (route) => route.abort(),
    );
  });

  // Homepage shows POSTS.slice(0,3); the newest post (types-of-funds) is the top card.
  test("TC-1: homepage renders the 'From the blog' section with the newest article card", async ({ page }) => {
    await page.goto("/v5/");
    // Wait for the card (auto-waits through the homepage's reveal-on-scroll animation),
    // then assert the section + heading. Targeting the card mirrors TC-2, which is stable.
    const card = page.getByTestId(`blog-card-${TOP_SLUG}`);
    await card.waitFor({ state: "attached", timeout: 90000 });
    await card.scrollIntoViewIfNeeded();
    await expect(page.getByTestId("home-blog-section")).toBeVisible();
    await expect(page.getByRole("heading", { name: /From the blog/i })).toBeVisible();
    await expect(card).toBeVisible();
    await expect(page.getByText(TOP_TITLE_RE).first()).toBeVisible();
  });

  test("TC-2: clicking the homepage blog card opens the article", async ({ page }) => {
    await page.goto("/v5/");
    await page.getByTestId(`blog-card-${TOP_SLUG}`).click();
    await expect(page).toHaveURL(new RegExp(`/v5/blog/${TOP_SLUG}`));
    await expect(page.getByRole("heading", { level: 1 })).toContainText(TOP_TITLE_RE);
  });

  test("TC-3: /blog index lists the article", async ({ page }) => {
    await page.goto("/v5/blog");
    // /blog is compiled on first hit by the dev server — wait for the card before asserting.
    await page.getByTestId(`blog-card-${SLUG}`).waitFor({ state: "attached", timeout: 90000 });
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    await expect(page.getByTestId(`blog-card-${SLUG}`)).toBeVisible();
    await expect(page.getByText(TITLE_RE).first()).toBeVisible();
  });

  test("TC-4: article page renders key statistics, source and the Copilot mapping", async ({ page }) => {
    await page.goto(`/v5/blog/${SLUG}`);
    await page.getByTestId("blog-article").waitFor({ state: "attached", timeout: 90000 });
    await expect(page.getByRole("heading", { level: 1 })).toContainText(TITLE_RE);
    await expect(page.getByText("93%").first()).toBeVisible();
    await expect(page.getByText(/SEBI/).first()).toBeVisible();
    await expect(page.getByRole("heading", { level: 2, name: /How Nivesh Copilot helps/i })).toBeVisible();
  });

  test("TC-5: article CTA 'Check my portfolio free' navigates to /login", async ({ page }) => {
    await page.goto(`/v5/blog/${SLUG}`);
    await page.getByTestId("blog-article").waitFor({ state: "attached", timeout: 90000 });
    await page.getByRole("button", { name: "Check my portfolio free" }).click();
    await expect(page).toHaveURL(/\/v5\/login/);
  });

  test("TC-6: MF best-practices article renders its guidance + Copilot mapping", async ({ page }) => {
    await page.goto(`/v5/blog/${MF_SLUG}`);
    await page.getByTestId("blog-article").waitFor({ state: "attached", timeout: 90000 });
    await expect(page.getByRole("heading", { level: 1 })).toContainText(MF_TITLE_RE);
    await expect(page.getByText(/Direct plans over Regular/i).first()).toBeVisible();
    await expect(page.getByText(/asset allocation/i).first()).toBeVisible();
    await expect(page.getByRole("heading", { level: 2, name: /How Nivesh Copilot helps/i })).toBeVisible();
  });

  test("TC-7: /blog index lists the MF best-practices article", async ({ page }) => {
    await page.goto("/v5/blog");
    await page.getByTestId(`blog-card-${MF_SLUG}`).waitFor({ state: "attached", timeout: 90000 });
    await expect(page.getByTestId(`blog-card-${MF_SLUG}`)).toBeVisible();
    await expect(page.getByText(MF_TITLE_RE).first()).toBeVisible();
  });

  test("TC-8: self-healing article renders its pipeline, Phoenix + CTA to Copilot", async ({ page }) => {
    await page.goto(`/v5/blog/${HEAL_SLUG}`);
    await page.getByTestId("blog-article").waitFor({ state: "attached", timeout: 90000 });
    await expect(page.getByRole("heading", { level: 1 })).toContainText(HEAL_TITLE_RE);
    await expect(page.getByText(/Autonomy stops at the pull request/i).first()).toBeVisible();
    await expect(page.getByText(/Phoenix/).first()).toBeVisible();
    await page.getByRole("button", { name: "See the Copilot" }).click();
    await expect(page).toHaveURL(/\/v5\/copilot/);
  });

  test("TC-9: 'How we build with Claude' article renders its thesis + pillars", async ({ page }) => {
    await page.goto(`/v5/blog/${CLAUDE_SLUG}`);
    await page.getByTestId("blog-article").waitFor({ state: "attached", timeout: 90000 });
    await expect(page.getByRole("heading", { level: 1 })).toContainText(CLAUDE_TITLE_RE);
    await expect(page.getByText(/disciplined engineers/i).first()).toBeVisible();
    await expect(page.getByText(/Hooks/).first()).toBeVisible();
  });

  test("TC-10: /blog index lists both engineering articles", async ({ page }) => {
    await page.goto("/v5/blog");
    await page.getByTestId(`blog-card-${HEAL_SLUG}`).waitFor({ state: "attached", timeout: 90000 });
    await expect(page.getByTestId(`blog-card-${HEAL_SLUG}`)).toBeVisible();
    await expect(page.getByTestId(`blog-card-${CLAUDE_SLUG}`)).toBeVisible();
  });

  // The conversational investor-education batch — each renders with its chat teaser + CTA.
  for (const c of CONV) {
    test(`TC-11 [${c.slug}]: conversational article renders (chat teaser + content + CTA)`, async ({ page }) => {
      await page.goto(`/v5/blog/${c.slug}`);
      await page.getByTestId("blog-article").waitFor({ state: "attached", timeout: 90000 });
      await expect(page.getByRole("heading", { level: 1 })).toContainText(c.re);
      await expect(page.getByTestId("chat-teaser")).toBeVisible();
      await expect(page.getByText(c.phrase).first()).toBeVisible();
      await expect(page.getByRole("button", { name: "Ask Nivesh Copilot" })).toBeVisible();
    });
  }

  test("TC-12: /blog index lists all four new investor-education articles", async ({ page }) => {
    await page.goto("/v5/blog");
    await page.getByTestId(`blog-card-${TOP_SLUG}`).waitFor({ state: "attached", timeout: 90000 });
    for (const c of CONV) {
      await expect(page.getByTestId(`blog-card-${c.slug}`)).toBeVisible();
    }
  });
});
