/**
 * NIDP Console → Feeds Live tab — /v5/nidp
 * Mocked layer: deterministic fixtures, no live API.
 *
 * Covers TC-6..TC-9 of test_reports/nidp_feeds_live_tracker.md:
 *   - live tracker renders (summary rollup + feed rows + attention banner)
 *   - expand a feed → run history + RUNNING indicator + log tail
 *   - trigger posts /execute and auto-expands the feed
 *   - db_error surfaces without crashing the page
 */
import { test, expect, Page } from "@playwright/test";
import { mockApi } from "../helpers/api-mock";
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const FIX = path.join(__dirname, "..", "fixtures");
const load = (f: string) => JSON.parse(fs.readFileSync(path.join(FIX, f), "utf-8"));

async function json(page: Page, pattern: string | RegExp, fixture: string) {
  await page.route(pattern, (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(load(fixture)) }),
  );
}

/** Wire the admin/nidp endpoints. Registered AFTER mockApi so they win LIFO. */
async function mockFeeds(page: Page, feedsFixture = "nidp-feeds-live.json") {
  await mockApi(page, "populated"); // auth/me → admin (is_admin: true) + catch-all
  await json(page, "**/api/admin/nidp/feeds/live", feedsFixture);
  await json(page, /\/api\/admin\/nidp\/jobs\/[^/]+\/runs/, "nidp-feed-runs-running.json");
  await json(page, /\/api\/admin\/nidp\/jobs\/[^/]+\/logs/, "nidp-feed-logs.json");
}

async function openFeedsLive(page: Page) {
  await page.goto("/v5/nidp");
  await page.getByRole("tab", { name: "Feeds Live" }).click();
  await expect(page.getByTestId("feeds-live-panel")).toBeVisible();
}

test.describe("NIDP Feeds Live (mocked)", () => {
  test("renders live tracker: summary rollup + feed rows + attention", async ({ page }) => {
    await mockFeeds(page);
    await openFeedsLive(page);

    // Summary rollup from /feeds/live
    await expect(page.getByTestId("feeds-live-summary")).toBeVisible();
    await expect(page.getByTestId("summary-total")).toHaveText("4");
    await expect(page.getByTestId("summary-failing")).toHaveText("1");
    await expect(page.getByTestId("summary-stale")).toHaveText("1");

    // Feed rows present (server sorts worst-first)
    await expect(page.getByTestId("feed-row-bhavcopy")).toBeVisible();
    await expect(page.getByTestId("feed-row-amfi_nav")).toBeVisible();
    await expect(page.getByTestId("feed-state-bhavcopy")).toHaveText("Failing");
    await expect(page.getByTestId("feed-state-amfi_nav")).toHaveText("Stale");

    // Attention banner lists the failing + stale feeds
    const attn = page.getByTestId("feeds-live-attention");
    await expect(attn).toBeVisible();
    await expect(attn).toContainText("bhavcopy");
    await expect(attn).toContainText("amfi_nav");
  });

  test("expand a feed → run history, RUNNING indicator, log tail", async ({ page }) => {
    await mockFeeds(page);
    await openFeedsLive(page);

    await page.getByTestId("feed-toggle-bhavcopy").click();
    await expect(page.getByTestId("feed-detail-bhavcopy")).toBeVisible();

    // Inline run history (from /jobs/{ing}/runs)
    await expect(page.getByTestId("feed-runs-bhavcopy")).toBeVisible();
    // Authoritative RUNNING signal surfaced from job_log
    await expect(page.getByTestId("feed-running-bhavcopy")).toContainText("RUNNING");
    // Inline log tail (from /jobs/{ing}/logs)
    await expect(page.getByTestId("feed-logs-bhavcopy")).toContainText("HTTP 403");
  });

  test("live toggle pauses auto-refresh", async ({ page }) => {
    await mockFeeds(page);
    await openFeedsLive(page);

    const toggle = page.getByTestId("feeds-live-toggle");
    await expect(toggle).toContainText("Live");
    await toggle.click();
    await expect(toggle).toContainText("Paused");
  });

  test("trigger posts /execute and auto-expands the feed", async ({ page }) => {
    await mockFeeds(page);
    let executed = "";
    await page.route(/\/api\/admin\/nidp\/jobs\/[^/]+\/execute/, (route, req) => {
      if (req.method() === "POST") executed = req.url();
      return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ ok: true, via: "vm" }) });
    });
    page.on("dialog", (d) => d.accept()); // window.confirm

    await openFeedsLive(page);
    await page.getByTestId("feed-trigger-bhavcopy").click();

    await expect.poll(() => executed).toContain("/jobs/bhavcopy/execute");
    // Auto-expands so the /runs poll surfaces the RUNNING row live
    await expect(page.getByTestId("feed-detail-bhavcopy")).toBeVisible();
  });

  test("db_error surfaces without crashing", async ({ page }) => {
    await mockFeeds(page, "nidp-feeds-live-error.json");
    await openFeedsLive(page);

    await expect(page.getByText("Query API reported:")).toBeVisible();
    await expect(page.getByText("v_feed_status unavailable")).toBeVisible();
    // Page still renders the panel (no white-screen)
    await expect(page.getByTestId("feeds-live-panel")).toBeVisible();
  });
});
