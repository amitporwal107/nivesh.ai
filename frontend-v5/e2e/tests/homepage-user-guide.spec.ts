/**
 * Homepage → User guide (owner, 5 Nov 2026: "Please provide the links in the homepage. A complete User Guide" and
 * "Where user can choose the preferred language and the video link changes").
 *
 * Public, frontend-only. The videos, captions and poster live on the staging host's /downloads (not served by the local
 * preview), so they are routed here: every mp4 request gets the repo's own 90-second WebM demo (Playwright's Chromium
 * has no H.264), which lets the seek and language-switch tests read a real currentTime. The written guide JSON is the
 * real file from public/user-guide. Filename matches the `unauthenticated` project's /homepage/ filter.
 * Test-case IDs match test_reports/user_guide_page_TESTCASES.md.
 */
import { test, expect, type Page } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";

const FILES = "/downloads/promo/nivesh-copilot-da8691abbb/";
const WEBM = fs.readFileSync(path.join(process.cwd(), "public", "nivesh-demo-90s.webm"));
const POSTER = fs.readFileSync(path.join(process.cwd(), "public", "nivesh-demo-poster.jpg"));
const LANGS = [
  { code: "en", label: "English" },
  { code: "hi", label: "हिंदी" },
  { code: "ta", label: "தமிழ்" },
  { code: "mr", label: "मराठी" },
  { code: "gu", label: "ગુજરાતી" },
] as const;
const DISCLAIMER: Record<string, string[]> = {
  en: ["not recommendations", "not investment advice"],
  hi: ["सिफ़ारिशें नहीं", "निवेश सलाह नहीं"],
  ta: ["பரிந்துரைகள் அல்ல", "முதலீட்டு ஆலோசனை அல்ல"],
  mr: ["शिफारसी नाहीत", "गुंतवणूक सल्ला नाही"],
  gu: ["ભલામણો નહીં", "રોકાણ સલાહ નથી"],
};

async function mockMedia(page: Page) {
  await page.route(`**${FILES}**`, async (route) => {
    const url = route.request().url();
    if (url.endsWith(".mp4")) {
      // Byte ranges, as the staging nginx serves them (206): a media element can only seek in a ranged resource.
      const m = /bytes=(\d+)-(\d*)/.exec(route.request().headers()["range"] ?? "");
      if (!m) return route.fulfill({ status: 200, contentType: "video/webm", headers: { "Accept-Ranges": "bytes" }, body: WEBM });
      const start = Number(m[1]);
      const end = m[2] ? Math.min(Number(m[2]), WEBM.length - 1) : WEBM.length - 1;
      return route.fulfill({
        status: 206,
        contentType: "video/webm",
        headers: { "Accept-Ranges": "bytes", "Content-Range": `bytes ${start}-${end}/${WEBM.length}` },
        body: WEBM.subarray(start, end + 1),
      });
    }
    if (url.endsWith(".vtt")) return route.fulfill({ status: 200, contentType: "text/vtt", body: "WEBVTT\n\n00:00:01.000 --> 00:00:04.000\ncaption\n" });
    if (url.endsWith(".jpg")) return route.fulfill({ status: 200, contentType: "image/jpeg", body: POSTER });
    return route.fulfill({ status: 404, body: "" });
  });
}

async function openGuide(page: Page, query = "") {
  await mockMedia(page);
  await page.goto(`/v5/user-guide${query}`);
  await expect(page.getByTestId("user-guide")).toBeVisible();
}

async function waitMetadata(page: Page) {
  await expect.poll(() => page.getByTestId("ug-video").evaluate((v: HTMLVideoElement) => v.readyState), { timeout: 15_000 }).toBeGreaterThanOrEqual(1);
}

test.describe("Homepage — user guide links", () => {
  test.use({ viewport: { width: 1280, height: 800 } });

  test("TC-1 header 'User guide' link is a real anchor that opens the guide", async ({ page }) => {
    await mockMedia(page);
    await page.goto("/v5/");
    const link = page.getByTestId("home-user-guide-link");
    await expect(link).toBeVisible();
    await expect(link).toHaveText("User guide");
    await expect(link).toHaveAttribute("href", "/v5/user-guide");
    await link.focus();
    await page.keyboard.press("Enter");
    await expect(page).toHaveURL(/\/v5\/user-guide$/);
    await expect(page.getByTestId("user-guide")).toBeVisible();
  });

  test("TC-2 the guide section defaults to English: Watch and the direct video link", async ({ page }) => {
    await mockMedia(page);
    await page.goto("/v5/");
    const section = page.getByTestId("home-user-guide");
    await section.scrollIntoViewIfNeeded();
    await expect(section).toBeVisible();
    for (const l of LANGS) await expect(page.getByTestId(`home-guide-lang-${l.code}`)).toHaveText(l.label);
    await expect(page.getByTestId("home-guide-lang-en")).toHaveAttribute("aria-pressed", "true");
    await expect(page.getByTestId("home-guide-watch")).toHaveAttribute("href", "/v5/user-guide");
    await expect(page.getByTestId("home-guide-direct")).toHaveAttribute("href", `${FILES}nivesh-copilot-en.mp4`);
  });

  test("TC-3 choosing a language changes the Watch link and the video link", async ({ page }) => {
    await mockMedia(page);
    await page.goto("/v5/");
    for (const l of LANGS.slice(1)) {
      await page.getByTestId(`home-guide-lang-${l.code}`).click();
      await expect(page.getByTestId(`home-guide-lang-${l.code}`)).toHaveAttribute("aria-pressed", "true");
      await expect(page.getByTestId("home-guide-lang-en")).toHaveAttribute("aria-pressed", "false");
      await expect(page.getByTestId("home-guide-watch")).toHaveAttribute("href", `/v5/user-guide?lang=${l.code}`);
      await expect(page.getByTestId("home-guide-watch")).toContainText(l.label);
      await expect(page.getByTestId("home-guide-direct")).toHaveAttribute("href", `${FILES}nivesh-copilot-${l.code}.mp4`);
    }
  });

  test("TC-4 Tamil chosen on the homepage opens the Tamil guide", async ({ page }) => {
    await mockMedia(page);
    await page.goto("/v5/");
    await page.getByTestId("home-guide-lang-ta").click();
    await page.getByTestId("home-guide-watch").click();
    await expect(page).toHaveURL(/\/v5\/user-guide\?lang=ta$/);
    await expect(page.getByTestId("ug-lang-ta")).toHaveAttribute("aria-pressed", "true");
    await expect(page.getByTestId("ug-video")).toHaveAttribute("src", `${FILES}nivesh-copilot-ta.mp4`);
  });
});

test.describe("User guide page", () => {
  test.use({ viewport: { width: 1280, height: 800 } });

  test("TC-5 opens in English with the English video, captions and poster", async ({ page }) => {
    await openGuide(page);
    await expect(page.getByTestId("ug-lang-en")).toHaveAttribute("aria-pressed", "true");
    const video = page.getByTestId("ug-video");
    await expect(video).toHaveAttribute("src", `${FILES}nivesh-copilot-en.mp4`);
    await expect(video).toHaveAttribute("poster", `${FILES}poster.jpg`);
    const track = page.getByTestId("ug-captions");
    await expect(track).toHaveAttribute("src", `${FILES}nivesh-copilot-en.vtt`);
    await expect(track).toHaveAttribute("srclang", "en");
    await expect(page.getByTestId("ug-direct")).toHaveAttribute("href", `${FILES}nivesh-copilot-en.mp4`);
  });

  test("TC-6 switching to Marathi changes the URL, video, captions, links and the written guide", async ({ page }) => {
    await openGuide(page);
    await expect(page.getByTestId("ug-guide")).toBeVisible();
    await page.getByTestId("ug-lang-mr").click();
    await expect(page).toHaveURL(/\/v5\/user-guide\?lang=mr$/);
    await expect(page.getByTestId("ug-lang-mr")).toHaveAttribute("aria-pressed", "true");
    await expect(page.getByTestId("ug-video")).toHaveAttribute("src", `${FILES}nivesh-copilot-mr.mp4`);
    await expect(page.getByTestId("ug-captions")).toHaveAttribute("src", `${FILES}nivesh-copilot-mr.vtt`);
    await expect(page.getByTestId("ug-direct")).toHaveAttribute("href", `${FILES}nivesh-copilot-mr.mp4`);
    await expect(page.getByTestId("ug-share-url")).toHaveText(/\/v5\/user-guide\?lang=mr$/);
    const guide = page.getByTestId("ug-guide");
    await expect(guide).toHaveAttribute("lang", "mr");
    await expect(page.getByTestId("ug-text-s06")).toHaveText(/[ऀ-ॿ]/);
  });

  test("TC-7 deep link opens Gujarati; an unknown code falls back to English", async ({ page }) => {
    await openGuide(page, "?lang=gu");
    await expect(page.getByTestId("ug-lang-gu")).toHaveAttribute("aria-pressed", "true");
    await expect(page.getByTestId("ug-video")).toHaveAttribute("src", `${FILES}nivesh-copilot-gu.mp4`);
    await expect(page.getByTestId("ug-text-s06")).toHaveText(/[઀-૿]/);
    await page.goto("/v5/user-guide?lang=xx");
    await expect(page.getByTestId("ug-lang-en")).toHaveAttribute("aria-pressed", "true");
    await expect(page.getByTestId("ug-video")).toHaveAttribute("src", `${FILES}nivesh-copilot-en.mp4`);
  });

  test("TC-8 chapters list with times, and a section's time seeks the video", async ({ page }) => {
    await openGuide(page);
    await expect(page.getByTestId("ug-chapters").locator("li")).toHaveCount(5);
    await expect(page.getByTestId("ug-chapter-0")).toContainText("0:00");
    await expect(page.getByTestId("ug-chapter-2")).toContainText("2:40");
    await waitMetadata(page);
    // s02's narration starts at 0:42 (42.1 s) — inside the 90-second stand-in video
    await expect(page.getByTestId("ug-seek-s02")).toContainText("0:42");
    await page.getByTestId("ug-seek-s02").click();
    await expect.poll(() => page.getByTestId("ug-video").evaluate((v: HTMLVideoElement) => v.currentTime)).toBeGreaterThan(41.5);
  });

  test("TC-9 the playback position carries over a language switch", async ({ page }) => {
    await openGuide(page);
    await waitMetadata(page);
    await page.getByTestId("ug-video").evaluate((v: HTMLVideoElement) => { v.muted = true; v.currentTime = 20; });
    await expect.poll(() => page.getByTestId("ug-video").evaluate((v: HTMLVideoElement) => v.currentTime)).toBeGreaterThan(19);
    await page.getByTestId("ug-lang-hi").click();
    await expect(page.getByTestId("ug-video")).toHaveAttribute("data-lang", "hi");
    await expect.poll(() => page.getByTestId("ug-video").evaluate((v: HTMLVideoElement) => v.currentTime), { timeout: 15_000 }).toBeGreaterThan(19);
  });

  test("TC-10 the complete written guide: all 43 sections, English uses P&L and F&O", async ({ page }) => {
    await openGuide(page);
    await expect(page.getByTestId("ug-guide")).toBeVisible();
    await expect(page.locator("[data-testid^='ug-section-']")).toHaveCount(43);
    await expect(page.getByTestId("ug-section-s09")).toContainText("Signal strength score");
    await expect(page.getByTestId("ug-section-s18")).toContainText("Multi-leg strategies");
    await expect(page.getByTestId("ug-section-s21")).toContainText("P&L");
    const text = await page.getByTestId("ug-guide").innerText();
    expect(text).not.toMatch(/P and L|F and O|M and A/);
    await expect(page.getByTestId("ug-open-s30")).toHaveAttribute("href", "/v5/app/trader/desk?tab=risk&view=hedge");
    await expect(page.getByTestId("ug-open-s32")).toHaveAttribute("href", "/v5/app");
    await expect(page.getByTestId("ug-open-s01")).toHaveCount(0);
  });

  test("TC-11 Copy link puts the language's page URL on the clipboard", async ({ page, context }) => {
    await context.grantPermissions(["clipboard-read", "clipboard-write"]);
    await openGuide(page, "?lang=hi");
    await page.getByTestId("ug-copy").click();
    await expect(page.getByTestId("ug-copy")).toHaveText("Copied");
    const copied = await page.evaluate(() => navigator.clipboard.readText());
    expect(copied).toMatch(/^http:\/\/localhost:\d+\/v5\/user-guide\?lang=hi$/);
  });

  test("TC-12 the disclaimer is in the chosen language", async ({ page }) => {
    await openGuide(page);
    for (const l of LANGS) {
      await page.getByTestId(`ug-lang-${l.code}`).click();
      const d = page.getByTestId("ug-disclaimer");
      for (const phrase of DISCLAIMER[l.code]) await expect(d).toContainText(phrase);
    }
  });

  test("TC-13 when the written guide fails to load, the video and languages still work", async ({ page }) => {
    await page.route("**/user-guide/*.json", (route) => route.abort());
    await openGuide(page);
    await expect(page.getByTestId("ug-guide-error")).toBeVisible({ timeout: 15_000 });
    await page.getByTestId("ug-lang-ta").click();
    await expect(page.getByTestId("ug-video")).toHaveAttribute("src", `${FILES}nivesh-copilot-ta.mp4`);
    await expect(page.getByTestId("ug-chapters").locator("li")).toHaveCount(5);
  });

  test("TC-15 compliance: no SEBI-status claim, and no trading-call words in our own copy", async ({ page }) => {
    await openGuide(page);
    await expect(page.getByTestId("ug-guide")).toBeVisible();
    const body = await page.locator("body").innerText();
    expect(body).not.toMatch(/SEBI[-\s]?(aligned|compliant|approved|certified)/i);
    // the closing section is the disclaimer itself ("ideas, not recommendations"): that phrase is required, not a call
    const guide = (await page.getByTestId("ug-guide").innerText()).replace(/not recommendations/gi, "");
    expect(guide).toContain("For education and research only");
    expect(guide).not.toMatch(/\b(buy|sell|stop[- ]?loss|targets?|recommend\w*|picks?)\b/i);
  });
});

test.describe("Phone width", () => {
  test.use({ viewport: { width: 390, height: 844 } });

  test("TC-14 the guide page and the homepage section fit a phone", async ({ page }) => {
    await openGuide(page, "?lang=hi");
    await expect(page.getByTestId("ug-langs")).toBeVisible();
    const over = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    expect(over).toBeLessThanOrEqual(1);
    await page.goto("/v5/");
    const section = page.getByTestId("home-user-guide");
    await section.scrollIntoViewIfNeeded();
    await expect(section).toBeVisible();
    await page.getByTestId("home-guide-lang-gu").click();
    await expect(page.getByTestId("home-guide-watch")).toHaveAttribute("href", "/v5/user-guide?lang=gu");
    const over2 = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    expect(over2).toBeLessThanOrEqual(1);
  });
});
