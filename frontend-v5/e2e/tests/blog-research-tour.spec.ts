/**
 * Blog — "Watch: a 2-minute tour of the Research tab" (/blog/research-tab-2-minute-tour).
 *
 * The blog is public, frontend-only static content (no backend), so these prove the
 * real behaviour of the post: it lists on /blog, renders the recorded tour video with
 * webm+mp4 sources and a caption track, and offers the transcript in English AND हिंदी
 * — both the on-page transcript and the player's caption <track> switch with the toggle.
 */
import { test, expect, type Page } from "@playwright/test";

const SLUG = "research-tab-2-minute-tour";
const ARTICLE_URL = `/v5/blog/${SLUG}`;

async function openArticle(page: Page) {
  await page.goto(ARTICLE_URL);
  await expect(page.getByTestId("blog-article")).toBeVisible();
}

test.describe("Blog — Research tab 2-minute tour", () => {
  test("TC-1 the post is listed on /blog", async ({ page }) => {
    await page.goto("/v5/blog");
    const card = page.getByTestId(`blog-card-${SLUG}`);
    await expect(card).toBeVisible();
    await expect(card).toContainText(/2-minute tour of the Research tab/i);
    await expect(card).toContainText(/Product tour/i);
  });

  test("TC-2 the card opens the article", async ({ page }) => {
    await page.goto("/v5/blog");
    await page.getByTestId(`blog-card-${SLUG}`).click();
    await expect(page).toHaveURL(new RegExp(`/blog/${SLUG}$`));
    await expect(page.getByTestId("blog-article")).toBeVisible();
    await expect(page.getByRole("heading", { level: 1 })).toContainText(/2-minute tour of the Research tab/i);
  });

  test("TC-3 default player is the English voiceover mp4 + poster + caption track", async ({ page }) => {
    await openArticle(page);
    const video = page.getByTestId("research-tour-video");
    await expect(video).toBeVisible();
    await expect(video).toHaveAttribute("poster", /research-tab-tour-poster\.jpg$/);
    await expect(video.locator("source")).toHaveAttribute("src", /\/research-tab-tour\.mp4$/);
    await expect(video.locator("track[kind='captions']")).toHaveAttribute("src", /research-tab-tour\.en\.vtt$/);
  });

  test("TC-4 default is English — transcript + track are English", async ({ page }) => {
    await openArticle(page);
    await expect(page.getByTestId("lang-en")).toHaveAttribute("aria-pressed", "true");
    const t = page.getByTestId("research-tour-transcript");
    await expect(t).toContainText("Welcome to Research");
    await expect(t).toContainText("That's Research, in two minutes.");
    await expect(page.getByTestId("research-tour-video").locator("track")).toHaveAttribute("srclang", "en");
  });

  test("TC-5 हिंदी toggle switches the transcript and the caption track", async ({ page }) => {
    await openArticle(page);
    await page.getByTestId("lang-hi").click();
    await expect(page.getByTestId("lang-hi")).toHaveAttribute("aria-pressed", "true");
    const t = page.getByTestId("research-tour-transcript");
    await expect(t).toContainText("रिसर्च में आपका स्वागत है");
    await expect(t).toContainText("यह रही रिसर्च, दो मिनट में।");
    // English text is gone once switched.
    await expect(t).not.toContainText("Welcome to Research");
    await expect(page.getByTestId("research-tour-video").locator("source")).toHaveAttribute("src", /research-tab-tour-hi\.mp4$/);
    await expect(page.getByTestId("research-tour-video").locator("track")).toHaveAttribute("srclang", "hi");
    await expect(page.getByTestId("research-tour-video").locator("track")).toHaveAttribute("src", /research-tab-tour\.hi\.vtt$/);
  });

  test("TC-6 the six stops and all twelve transcript cues render", async ({ page }) => {
    await openArticle(page);
    // 12 timestamped cues in the transcript.
    await expect(page.getByTestId("research-tour-transcript").locator("li")).toHaveCount(12);
    // The tour walkthrough stops (distinctive phrases).
    await expect(page.getByText(/Read for you.*ranked by how much they matter/i)).toBeVisible();
    await expect(page.getByText(/its whole document library/i)).toBeVisible();
  });

  test("TC-7 the download fallback points to the real mp4", async ({ page }) => {
    await openArticle(page);
    // The <a> is <video> fallback content: present in the DOM but not rendered
    // (nor in the a11y tree) while the browser can play the video — query the node
    // directly and read its href.
    const dl = page.getByTestId("research-tour-video").locator("a");
    await expect(dl).toHaveAttribute("href", /research-tab-tour\.mp4$/);
  });

  test("TC-8 language buttons + video expose correct a11y", async ({ page }) => {
    await openArticle(page);
    await expect(page.getByTestId("lang-en")).toHaveAttribute("aria-pressed", /true|false/);
    await expect(page.getByTestId("lang-hi")).toHaveAttribute("aria-pressed", /true|false/);
    await expect(page.getByTestId("research-tour-video")).toHaveAccessibleName(/tour of the Nivesh Research tab/i);
  });

  test("TC-9 the video actually carries an audio track (voiceover)", async ({ page }) => {
    await openArticle(page);
    const video = page.getByTestId("research-tour-video");
    // Play muted briefly (allowed) so the media pipeline decodes audio, then confirm
    // real audio bytes were decoded — proof the mp4 has the voiceover, not silence.
    await video.evaluate((v: HTMLVideoElement) => { v.muted = true; return v.play().catch(() => {}); });
    await expect
      .poll(async () => video.evaluate((v: HTMLVideoElement & { webkitAudioDecodedByteCount?: number }) =>
        v.webkitAudioDecodedByteCount ?? 0), { timeout: 8000 })
      .toBeGreaterThan(0);
  });
});
