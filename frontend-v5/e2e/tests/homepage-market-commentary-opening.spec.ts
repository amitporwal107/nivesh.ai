/**
 * Market commentary — the morning Opening Bell (/v5/market-commentary?show=opening) beside the nightly Closing Bell,
 * and its homepage card.
 *
 * Opening editions are static files published at /downloads/opening-bell/ (outside the /v5/ app); the tests route:
 *   opening index.json / transcript*.json   e2e/fixtures/opening-bell/ — REAL output of tools/closing_bell/publish.py
 *                                           for the staging dry run of 3 Nov 2026 (edition built, not published)
 *   closing index.json / transcript.json    e2e/fixtures/closing-bell/ (the evening spec's real 27 Oct edition)
 *   mp4 / poster / captions                 404 (players are checked by their src; media is checked on staging)
 * Filename matches the `unauthenticated` project's /homepage/ filter. IDs match test_reports/opening_bell_20261102.md.
 */
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";
import { test, expect, type Page } from "@playwright/test";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const FIX = path.join(__dirname, "..", "fixtures");
const OPEN = JSON.parse(fs.readFileSync(path.join(FIX, "opening-bell", "index.json"), "utf8"));
const CLOSE = JSON.parse(fs.readFileSync(path.join(FIX, "closing-bell", "index.json"), "utf8"));
const ED = OPEN.editions[0];

function serveJson(dir: string) {
  return (r: import("@playwright/test").Route) => {
    const p = path.join(dir, path.basename(new URL(r.request().url()).pathname));
    return fs.existsSync(p) ? r.fulfill({ path: p, contentType: "application/json" }) : r.fulfill({ status: 404, body: "not found" });
  };
}

async function route(page: Page, opening: "fixture" | 404 = "fixture") {
  await page.route("**/downloads/opening-bell/index.json", (r) =>
    opening === "fixture" ? r.fulfill({ json: OPEN }) : r.fulfill({ status: 404, body: "not found" }));
  await page.route(/\/downloads\/opening-bell\/[^/]+\/transcript(_[a-z]{2})?\.json$/, serveJson(path.join(FIX, "opening-bell")));
  await page.route("**/downloads/closing-bell/index.json", (r) => r.fulfill({ json: CLOSE }));
  await page.route(/\/downloads\/closing-bell\/[^/]+\/transcript(_[a-z]{2})?\.json$/, serveJson(path.join(FIX, "closing-bell")));
  await page.route(/\/downloads\/(opening|closing)-bell\/[^/]+\/[^/]+\.(mp4|jpg|vtt)$/, (r) => r.fulfill({ status: 404, body: "not found" }));
}

test.describe("Opening Bell on the commentary page (desktop)", () => {
  test.use({ viewport: { width: 1280, height: 800 } });

  test("OB-17 ?show=opening: title, player files, headlines, levels disclaimer, transcript", async ({ page }) => {
    await route(page);
    await page.goto("/v5/market-commentary?show=opening");
    await expect(page.getByRole("heading", { level: 1 })).toHaveText(`Opening Bell — ${ED.day_long}`);
    await expect(page.getByTestId("mc-show-opening")).toHaveAttribute("aria-current", "page");
    const v = page.getByTestId("mc-video");
    await expect(v).toHaveAttribute("poster", `/downloads/opening-bell/${ED.date}/poster.jpg`);
    await expect(v.locator("source")).toHaveAttribute("src", `/downloads/opening-bell/${ED.date}/opening-bell-${ED.date}.mp4`);
    await expect(v.locator("track[kind='captions']")).toHaveAttribute("src", `/downloads/opening-bell/${ED.date}/captions.vtt`);
    await expect(v).toHaveAccessibleName(new RegExp(`Opening Bell market commentary for ${ED.day_long}`));
    await expect(page.getByTestId("mc-headlines").locator(".nv-card")).toHaveCount(ED.headlines.length);
    await expect(page.getByTestId("mc-disclaimer")).toContainText("not investment advice");
    await expect(page.getByTestId("mc-levels-note")).toHaveText("Ranges and levels are what the options market prices, not forecasts.");
    await expect(page.getByTestId("mc-sources")).toContainText("NSE pre-open");
    const tr = JSON.parse(fs.readFileSync(path.join(FIX, "opening-bell", "transcript.json"), "utf8"));
    await expect(page.getByTestId("mc-transcript").locator("h3")).toHaveCount(tr.sections.length);
    await expect(page.getByTestId("mc-transcript").locator("li")).toHaveCount(tr.cue_count);
    await expect(page.getByTestId("mc-transcript")).toContainText(tr.sections[0].cues[0].text);
  });

  test("OB-18 the show switch moves between the two shows; the Closing Bell stays the default", async ({ page }) => {
    await route(page);
    await page.goto("/v5/market-commentary");
    await expect(page.getByRole("heading", { level: 1 })).toHaveText(`Closing Bell — ${CLOSE.editions[0].day_long}`);
    await expect(page.getByTestId("mc-show-closing")).toHaveAttribute("aria-current", "page");
    await expect(page.getByTestId("mc-levels-note")).toHaveCount(0);
    await page.getByTestId("mc-show-opening").click();
    await expect(page).toHaveURL(/\/v5\/market-commentary\?show=opening$/);
    await expect(page.getByRole("heading", { level: 1 })).toHaveText(`Opening Bell — ${ED.day_long}`);
    await page.getByTestId("mc-show-closing").click();
    await expect(page).toHaveURL(/\/v5\/market-commentary$/);
    await expect(page.getByRole("heading", { level: 1 })).toHaveText(`Closing Bell — ${CLOSE.editions[0].day_long}`);
  });

  test("OB-19 [hi] the language switch keeps the morning show and shows the Hindi levels line", async ({ page }) => {
    await route(page);
    await page.goto(`/v5/market-commentary/${ED.date}?show=opening`);
    await page.getByTestId("mc-lang-hi").click();
    await expect(page).toHaveURL(new RegExp(`/v5/market-commentary/${ED.date}\\?show=opening&lang=hi$`));
    await expect(page.getByTestId("mc-video").locator("source")).toHaveAttribute("src", `/downloads/opening-bell/${ED.date}/opening-bell-${ED.date}-hi.mp4`);
    await expect(page.getByTestId("mc-levels-note")).toHaveText("रेंज और लेवल ऑप्शंस बाज़ार के आंके गए भाव हैं, पूर्वानुमान नहीं।");
    const tr = JSON.parse(fs.readFileSync(path.join(FIX, "opening-bell", "transcript_hi.json"), "utf8"));
    await expect(page.getByTestId("mc-transcript")).toContainText(tr.sections[0].cues[0].text);
  });

  test("OB-20 no morning edition yet → the morning empty notice, no player", async ({ page }) => {
    await route(page, 404);
    await page.goto("/v5/market-commentary?show=opening");
    await expect(page.getByTestId("mc-empty")).toContainText("Opening Bell is published on trading days right after the 9:00–9:08 pre-open");
    await expect(page.getByTestId("mc-video")).toHaveCount(0);
  });

  test("OB-21 homepage: the Opening Bell card opens the latest morning edition; hidden when none", async ({ page }) => {
    await route(page);
    await page.goto("/v5/");
    const card = page.getByTestId("home-opening-bell-card");
    await card.scrollIntoViewIfNeeded();
    await expect(card).toBeVisible();
    await expect(card).toContainText(`${ED.day_long}: before the open`);
    await expect(card).toContainText("not forecasts");
    await expect(page.getByTestId("home-closing-bell-card")).toHaveCount(1);
    await card.click();
    await expect(page).toHaveURL(new RegExp(`/v5/market-commentary/${ED.date}\\?show=opening$`));
    await expect(page.getByRole("heading", { level: 1 })).toHaveText(`Opening Bell — ${ED.day_long}`);
    await page.unrouteAll({ behavior: "ignoreErrors" });
    await route(page, 404);
    await page.goto("/v5/");
    await expect(page.getByTestId("home-blog-section")).toBeVisible();
    await expect(page.getByTestId("home-opening-bell")).toHaveCount(0);
  });
});
