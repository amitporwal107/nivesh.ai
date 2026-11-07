/**
 * Market commentary — the nightly Closing Bell editions (/v5/market-commentary) and their homepage entry points.
 *
 * Editions are static files the nightly job publishes at /downloads/closing-bell/ (outside the /v5/ app), so the
 * tests route those URLs:
 *   index.json / transcript.json  e2e/fixtures/closing-bell/ — the 27 Oct edition is the REAL output of
 *                                 tools/closing_bell/publish.py; the 26 Oct entry is synthetic (archive only).
 *   mp4 / poster / captions       the real built files when CB_MEDIA_DIR points at an edition folder
 *                                 (TC-15 is skipped without it, never faked).
 * Filename matches the `unauthenticated` project's /homepage/ filter. IDs match
 * test_reports/closing_bell_daily_20261028.md.
 */
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";
import { test, expect, type Page } from "@playwright/test";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const FIX = path.join(__dirname, "..", "fixtures", "closing-bell");
const INDEX = JSON.parse(fs.readFileSync(path.join(FIX, "index.json"), "utf8"));
const MEDIA = process.env.CB_MEDIA_DIR || "";

/** Serve a real file when it exists, otherwise 404 (the synthetic 26 Oct edition has no media). */
function serveFile(dir: string, contentType?: string) {
  return (r: import("@playwright/test").Route) => {
    const p = dir ? path.join(dir, path.basename(new URL(r.request().url()).pathname)) : "";
    return p && fs.existsSync(p) ? r.fulfill({ path: p, contentType }) : r.fulfill({ status: 404, body: "not found" });
  };
}

async function routeEditions(page: Page, index: "fixture" | 404 | 500 = "fixture") {
  await page.route("**/downloads/closing-bell/index.json", (r) =>
    index === "fixture" ? r.fulfill({ json: INDEX }) : r.fulfill({ status: index, body: index === 404 ? "not found" : "error" }));
  // transcript.json (English) and transcript_<lang>.json: served from the fixture file of the same name
  await page.route(/\/downloads\/closing-bell\/[^/]+\/transcript(_[a-z]{2})?\.json$/, serveFile(FIX, "application/json"));
  await page.route("**/downloads/closing-bell/*/poster.jpg", serveFile(MEDIA, "image/jpeg"));
  await page.route(/\/downloads\/closing-bell\/[^/]+\/captions(_[a-z]{2})?\.vtt$/, serveFile(MEDIA, "text/vtt"));
  await page.route(/\/downloads\/closing-bell\/[^/]+\/closing-bell-[^/]+\.mp4$/, serveFile(MEDIA, "video/mp4"));
}

test.describe("Market commentary page (desktop)", () => {
  test.use({ viewport: { width: 1280, height: 800 } });

  test("TC-12 latest edition: title, player, headlines, disclaimer, transcript, archive", async ({ page }) => {
    await routeEditions(page);
    await page.goto("/v5/market-commentary");
    await expect(page.getByTestId("market-commentary")).toBeVisible();
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("Closing Bell — Tuesday, 27 October 2026");
    const v = page.getByTestId("mc-video");
    await expect(v).toHaveAttribute("poster", "/downloads/closing-bell/2026-10-27/poster.jpg");
    await expect(v.locator("source")).toHaveAttribute("src", "/downloads/closing-bell/2026-10-27/closing-bell-2026-10-27.mp4");
    await expect(v.locator("track[kind='captions']")).toHaveAttribute("src", "/downloads/closing-bell/2026-10-27/captions.vtt");
    await expect(v).toHaveAccessibleName(/Closing Bell market commentary for Tuesday, 27 October 2026/);
    const heads = page.getByTestId("mc-headlines");
    await expect(heads.locator(".nv-card")).toHaveCount(INDEX.editions[0].headlines.length);
    await expect(heads).toContainText(INDEX.editions[0].headlines[1].small);
    await expect(page.getByTestId("mc-disclaimer")).toContainText("Market information and education, not investment advice.");
    await expect(page.getByTestId("mc-disclaimer")).toContainText("The Top 10 ideas are for review, not recommendations");
    const tr = page.getByTestId("mc-transcript");
    await expect(tr.locator("h3")).toHaveCount(8);
    const cues = JSON.parse(fs.readFileSync(path.join(FIX, "transcript.json"), "utf8"));
    await expect(tr.locator("li")).toHaveCount(cues.cue_count);
    await expect(tr).toContainText(cues.sections[0].cues[0].text);
    await expect(page.getByTestId("mc-credit")).toContainText("“The Complex” by Kevin MacLeod");
    await expect(page.getByTestId("mc-archive-2026-10-26")).toBeVisible();
  });

  test("TC-13 archive link and direct date URL open that edition; unknown date says so", async ({ page }) => {
    await routeEditions(page);
    await page.goto("/v5/market-commentary");
    await page.getByTestId("mc-archive-2026-10-26").click();
    await expect(page).toHaveURL(/\/v5\/market-commentary\/2026-10-26$/);
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("Closing Bell — Monday, 26 October 2026");
    await expect(page.getByTestId("mc-archive-2026-10-27")).toBeVisible();
    await page.goto("/v5/market-commentary/2026-10-27");
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("Closing Bell — Tuesday, 27 October 2026");
    await page.goto("/v5/market-commentary/2026-10-11");
    await expect(page.getByTestId("mc-not-found")).toContainText("No edition for 2026-10-11");
    await page.getByTestId("mc-not-found").getByRole("link", { name: /latest edition/ }).click();
    await expect(page).toHaveURL(/\/v5\/market-commentary$/);
  });

  test("TC-14 no editions yet → empty notice; feed error → error notice; no sample data", async ({ page }) => {
    await routeEditions(page, 404);
    await page.goto("/v5/market-commentary");
    await expect(page.getByTestId("mc-empty")).toContainText("The first edition is on its way");
    await expect(page.getByTestId("mc-video")).toHaveCount(0);
    await page.unrouteAll({ behavior: "ignoreErrors" });
    await routeEditions(page, 500);
    await page.goto("/v5/market-commentary");
    await expect(page.getByTestId("mc-error")).toBeVisible({ timeout: 15000 });
    await expect(page.getByTestId("mc-video")).toHaveCount(0);
  });

  test("TC-15 the real built edition plays for its published length, with audio", async ({ page }) => {
    test.skip(!MEDIA, "CB_MEDIA_DIR not set — real media check runs only against a built edition");
    await routeEditions(page);
    await page.goto("/v5/market-commentary/2026-10-27");
    const v = page.getByTestId("mc-video");
    const want = INDEX.editions[0].duration_s;
    await expect.poll(() => v.evaluate((el: HTMLVideoElement) => el.duration || 0), { timeout: 20000 }).toBeGreaterThan(want - 2);
    expect(await v.evaluate((el: HTMLVideoElement) => el.duration)).toBeLessThan(want + 2);
    await v.evaluate((el: HTMLVideoElement) => { el.muted = true; return el.play().catch(() => {}); });
    await expect
      .poll(() => v.evaluate((el: HTMLVideoElement & { webkitAudioDecodedByteCount?: number }) => el.webkitAudioDecodedByteCount ?? 0), { timeout: 15000 })
      .toBeGreaterThan(0);
  });

  test("TC-16 homepage: header link goes to the page; Closing Bell card opens the latest edition", async ({ page }) => {
    await routeEditions(page);
    await page.goto("/v5/");
    const link = page.getByTestId("home-market-commentary-link");
    await expect(link).toHaveAttribute("href", "/v5/market-commentary");
    const card = page.getByTestId("home-closing-bell-card");
    await card.scrollIntoViewIfNeeded();
    // toBeVisible() accepts opacity 0; the reveal-on-scroll must actually fade the card in (29 Oct live bug).
    await expect.poll(() => card.evaluate((el) => getComputedStyle(el).opacity), { timeout: 5000 }).toBe("1");
    await expect(card).toContainText("Tuesday, 27 October 2026");
    await expect(card).toContainText("Market information, not investment advice");
    await card.click();
    await expect(page).toHaveURL(/\/v5\/market-commentary\/2026-10-27$/);
    await expect(page.getByTestId("mc-video")).toBeVisible();
    await page.goto("/v5/");
    await page.getByTestId("home-market-commentary-link").click();
    await expect(page).toHaveURL(/\/v5\/market-commentary$/);
  });

  test("TC-16 homepage hides the Closing Bell card when nothing is published", async ({ page }) => {
    await routeEditions(page, 404);
    await page.goto("/v5/");
    await expect(page.getByTestId("home-blog-section")).toBeVisible();
    await expect(page.getByTestId("home-closing-bell")).toHaveCount(0);
  });
});

test.describe("Market commentary in five languages (desktop)", () => {
  test.use({ viewport: { width: 1280, height: 800 } });
  const LANGS = [["en", "English"], ["hi", "हिंदी"], ["ta", "தமிழ்"], ["mr", "मराठी"], ["gu", "ગુજરાતી"]] as const;

  test("TC-19 switcher lists the five languages; English is the default", async ({ page }) => {
    await routeEditions(page);
    await page.goto("/v5/market-commentary/2026-10-27");
    for (const [code, label] of LANGS) await expect(page.getByTestId(`mc-lang-${code}`)).toHaveText(label);
    await expect(page.getByTestId("mc-lang-en")).toHaveAttribute("aria-pressed", "true");
    await expect(page.getByTestId("mc-video").locator("source")).toHaveAttribute("src", "/downloads/closing-bell/2026-10-27/closing-bell-2026-10-27.mp4");
    await expect(page.getByTestId("mc-transcript")).toHaveAttribute("lang", "en");
  });

  for (const [code] of LANGS.slice(1)) {
    test(`TC-20 [${code}] switching swaps the video, captions, transcript and disclaimer`, async ({ page }) => {
      const tr = JSON.parse(fs.readFileSync(path.join(FIX, `transcript_${code}.json`), "utf8"));
      await routeEditions(page);
      await page.goto("/v5/market-commentary/2026-10-27");
      await page.getByTestId(`mc-lang-${code}`).click();
      await expect(page).toHaveURL(new RegExp(`/v5/market-commentary/2026-10-27\\?lang=${code}$`));
      await expect(page.getByTestId(`mc-lang-${code}`)).toHaveAttribute("aria-pressed", "true");
      const v = page.getByTestId("mc-video");
      await expect(v.locator("source")).toHaveAttribute("src", `/downloads/closing-bell/2026-10-27/closing-bell-2026-10-27-${code}.mp4`);
      await expect(v.locator("track")).toHaveAttribute("srclang", code);
      await expect(v.locator("track")).toHaveAttribute("src", `/downloads/closing-bell/2026-10-27/captions_${code}.vtt`);
      const t = page.getByTestId("mc-transcript");
      await expect(t).toHaveAttribute("lang", code);
      await expect(t.locator("li")).toHaveCount(tr.cue_count);
      await expect(t).toContainText(tr.sections[0].cues[0].text);
      await expect(t.locator("h3").first()).toContainText(tr.sections[0].tag);
      await expect(page.getByTestId("mc-disclaimer")).toHaveAttribute("data-testid", "mc-disclaimer");
      await expect(page.getByTestId("mc-disclaimer").locator(`p[lang="${code}"]`).first()).toBeVisible();
    });
  }

  test("TC-21 a shared link opens in its language; an unknown ?lang falls back to English", async ({ page }) => {
    await routeEditions(page);
    await page.goto("/v5/market-commentary/2026-10-27?lang=ta");
    await expect(page.getByTestId("mc-lang-ta")).toHaveAttribute("aria-pressed", "true");
    await expect(page.getByTestId("mc-transcript")).toHaveAttribute("lang", "ta");
    await page.goto("/v5/market-commentary/2026-10-27?lang=xx");
    await expect(page.getByTestId("mc-lang-en")).toHaveAttribute("aria-pressed", "true");
  });

  test("TC-22 an edition published before the languages is English only, without a switcher", async ({ page }) => {
    await routeEditions(page);
    await page.goto("/v5/market-commentary/2026-10-26");
    await expect(page.getByTestId("mc-video")).toBeVisible();
    await expect(page.getByTestId("mc-langs")).toHaveCount(0);
  });

  test("TC-23 [hi] the real Hindi edition plays with audio", async ({ page }) => {
    test.skip(!MEDIA, "CB_MEDIA_DIR not set — real media check runs only against a built edition");
    await routeEditions(page);
    await page.goto("/v5/market-commentary/2026-10-27?lang=hi");
    const v = page.getByTestId("mc-video");
    await expect.poll(() => v.evaluate((el: HTMLVideoElement) => el.duration || 0), { timeout: 20000 }).toBeGreaterThan(300);
    await v.evaluate((el: HTMLVideoElement) => { el.muted = true; return el.play().catch(() => {}); });
    await expect
      .poll(() => v.evaluate((el: HTMLVideoElement & { webkitAudioDecodedByteCount?: number }) => el.webkitAudioDecodedByteCount ?? 0), { timeout: 15000 })
      .toBeGreaterThan(0);
  });
});

test.describe("Market commentary on a phone", () => {
  test.use({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true });

  test("TC-16 phone: the homepage card is the way in; page fits without sideways scroll", async ({ page }) => {
    await routeEditions(page);
    await page.goto("/v5/");
    await expect(page.getByTestId("home-market-commentary-link")).toBeHidden();
    const card = page.getByTestId("home-closing-bell-card");
    await card.scrollIntoViewIfNeeded();
    await expect.poll(() => card.evaluate((el) => getComputedStyle(el).opacity), { timeout: 5000 }).toBe("1");
    await card.click();
    await expect(page).toHaveURL(/\/v5\/market-commentary\/2026-10-27$/);
    const v = page.getByTestId("mc-video");
    await expect(v).toBeVisible();
    const box = await v.boundingBox();
    expect(box!.x).toBeGreaterThanOrEqual(0);
    expect(box!.x + box!.width).toBeLessThanOrEqual(390);
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    expect(overflow).toBeLessThanOrEqual(0);
  });
});
