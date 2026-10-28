/**
 * Homepage → "Market commentary" (the Closing Bell bulletin for 27 Oct 2026).
 *
 * The blog is public, frontend-only static content (no backend). These prove the homepage
 * link and the post it opens: the header link and the "From the blog" card both reach
 * /blog/closing-bell-27-oct-2026, the player is wired to the real mp4 + poster + captions,
 * the media is the real 6:51 bulletin with audio, and the transcript, disclaimers and
 * music credit render. Filename matches the `unauthenticated` project's /homepage/ filter.
 * Test-case IDs match test_reports/home_market_commentary_20261028.md.
 */
import { test, expect, type Page } from "@playwright/test";

const SLUG = "closing-bell-27-oct-2026";
const ARTICLE_URL = `/v5/blog/${SLUG}`;

async function openArticle(page: Page) {
  await page.goto(ARTICLE_URL);
  await expect(page.getByTestId("blog-article")).toBeVisible();
}

test.describe("Homepage — market commentary link (desktop)", () => {
  test.use({ viewport: { width: 1280, height: 800 } });

  test("TC-1 header 'Market commentary' link opens the Closing Bell post", async ({ page }) => {
    await page.goto("/v5/");
    const link = page.getByTestId("home-market-commentary-link");
    await expect(link).toBeVisible();
    await expect(link).toHaveText("Market commentary");
    await link.click();
    await expect(page).toHaveURL(new RegExp(`/v5/blog/${SLUG}$`));
    await expect(page.getByTestId("blog-article")).toBeVisible();
    await expect(page.getByRole("heading", { level: 1 })).toContainText(/Closing Bell/);
  });

  test("TC-2 the link is a real anchor, reachable by keyboard", async ({ page }) => {
    await page.goto("/v5/");
    const link = page.getByTestId("home-market-commentary-link");
    await expect(link).toHaveAttribute("href", `/v5/blog/${SLUG}`);
    await link.focus();
    await expect(link).toBeFocused();
    await page.keyboard.press("Enter");
    await expect(page).toHaveURL(new RegExp(`/v5/blog/${SLUG}$`));
  });

  test("TC-3 'From the blog' leads with the Closing Bell card, which opens the post", async ({ page }) => {
    await page.goto("/v5/");
    const section = page.getByTestId("home-blog-section");
    await expect(section).toBeVisible();
    const first = section.locator("[data-testid^='blog-card-']").first();
    await expect(first).toHaveAttribute("data-testid", `blog-card-${SLUG}`);
    await expect(first).toContainText(/Market commentary/);
    await first.click();
    await expect(page).toHaveURL(new RegExp(`/v5/blog/${SLUG}$`));
  });

  test("TC-4 the post is listed on /blog as Market commentary", async ({ page }) => {
    await page.goto("/v5/blog");
    const card = page.getByTestId(`blog-card-${SLUG}`);
    await expect(card).toBeVisible();
    await expect(card).toContainText(/Closing Bell/);
    await expect(card).toContainText(/Market commentary/);
  });

  test("TC-5 player: poster, mp4 source, English captions, accessible name, download fallback", async ({ page }) => {
    await openArticle(page);
    const video = page.getByTestId("closing-bell-video");
    await expect(video).toBeVisible();
    await expect(video).toHaveAttribute("poster", /\/v5\/closing-bell-27oct2026-poster\.jpg$/);
    await expect(video.locator("source")).toHaveAttribute("src", /\/v5\/closing-bell-27oct2026\.mp4$/);
    await expect(video.locator("source")).toHaveAttribute("type", "video/mp4");
    const track = video.locator("track[kind='captions']");
    await expect(track).toHaveAttribute("src", /\/v5\/closing-bell-27oct2026\.en\.vtt$/);
    await expect(track).toHaveAttribute("srclang", "en");
    await expect(video).toHaveAccessibleName(/Closing Bell market commentary/i);
    await expect(video.locator("a")).toHaveAttribute("href", /closing-bell-27oct2026\.mp4$/);
  });

  test("TC-6 the media is the real 6:51 bulletin and carries audio", async ({ page }) => {
    await openArticle(page);
    const video = page.getByTestId("closing-bell-video");
    await expect
      .poll(async () => video.evaluate((v: HTMLVideoElement) => v.duration || 0), { timeout: 15000 })
      .toBeGreaterThan(411);
    expect(await video.evaluate((v: HTMLVideoElement) => v.duration)).toBeLessThan(413);
    await video.evaluate((v: HTMLVideoElement) => { v.muted = true; return v.play().catch(() => {}); });
    await expect
      .poll(async () => video.evaluate((v: HTMLVideoElement & { webkitAudioDecodedByteCount?: number }) =>
        v.webkitAudioDecodedByteCount ?? 0), { timeout: 10000 })
      .toBeGreaterThan(0);
    const assets = await page.evaluate(async () => {
      const head = async (u: string) => {
        const r = await fetch(u, { headers: { Range: "bytes=0-1023" } });
        return { status: r.status, type: r.headers.get("content-type") };
      };
      return { mp4: await head("/v5/closing-bell-27oct2026.mp4"), vtt: await head("/v5/closing-bell-27oct2026.en.vtt") };
    });
    expect([200, 206]).toContain(assets.mp4.status);
    expect(assets.mp4.type).toContain("video/mp4");
    expect([200, 206]).toContain(assets.vtt.status);
  });

  test("TC-7 transcript: 8 sections, 36 lines, exact first and last line", async ({ page }) => {
    await openArticle(page);
    const t = page.getByTestId("closing-bell-transcript");
    await expect(t.locator("h3")).toHaveCount(8);
    await expect(t.locator("li")).toHaveCount(36);
    await expect(t.locator("li").first()).toContainText(
      "Calm on the Nifty, fireworks underneath. Good evening, and welcome to Closing Bell on the Nivesh Desk.",
    );
    await expect(t.locator("li").last()).toContainText("Market information and education, not investment advice. Good night.");
    await expect(t).toContainText("FIIs bought a net 4,240 crore rupees");
  });

  test("TC-8 date, disclaimers and music credit are visible", async ({ page }) => {
    await openArticle(page);
    await expect(page.getByText(/Tuesday, 27 October 2026 · 6:51/)).toBeVisible();
    const d = page.getByTestId("closing-bell-disclaimer");
    await expect(d).toContainText("Market information and education, not investment advice.");
    await expect(d).toContainText("The Top 10 ideas are for review, not recommendations");
    await expect(d).toContainText(/9 out of 10 individual traders in equity F&O incurred net losses/);
    await expect(page.getByTestId("closing-bell-credit")).toContainText(/“The Complex” by Kevin MacLeod/);
    await expect(page.getByTestId("closing-bell-credit").getByRole("link")).toHaveAttribute(
      "href",
      "https://creativecommons.org/licenses/by/3.0/",
    );
  });
});

test.describe("Homepage — market commentary on a phone", () => {
  test.use({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true });

  test("TC-9 phone: blog card opens the post, the video fits and nothing scrolls sideways", async ({ page }) => {
    await page.goto("/v5/");
    // The header nav is hidden at <=920px by the existing homepage rule, so the blog card is the way in.
    await expect(page.getByTestId("home-market-commentary-link")).toBeHidden();
    const card = page.getByTestId(`blog-card-${SLUG}`);
    await card.scrollIntoViewIfNeeded();
    await expect(card).toBeVisible();
    await card.click();
    await expect(page).toHaveURL(new RegExp(`/v5/blog/${SLUG}$`));
    const video = page.getByTestId("closing-bell-video");
    await expect(video).toBeVisible();
    const box = await video.boundingBox();
    expect(box!.x).toBeGreaterThanOrEqual(0);
    expect(box!.x + box!.width).toBeLessThanOrEqual(390);
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    expect(overflow).toBeLessThanOrEqual(0);
  });
});
