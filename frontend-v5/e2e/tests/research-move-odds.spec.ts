/**
 * Research → Move odds (mocked layer). Test cases TC-20..TC-27 in test_reports/move_odds_research_20260916_2351.md.
 *
 * MOCK — not real data: every /api/move-odds response here is a fixture (e2e/fixtures/move-odds-*.json, shaped like
 * backend/routes/move_odds.py, values copied from the 2026-09-17 v4 snapshot). auth/me is mocked too. The staging run
 * against real data is TC-28..TC-30.
 */
import { test, expect, type Page } from "@playwright/test";
import fs from "fs";
import path from "path";
import { mockAuthAs } from "../helpers/api-mock";

const FX = path.join(process.cwd(), "e2e", "fixtures");
const load = (name: string) => JSON.parse(fs.readFileSync(path.join(FX, name), "utf-8"));
const HEADS = ["p_up5_1d", "p_down5_1d", "p_up10_1d", "p_down10_1d"] as const;
const BANNED = /\b(buy|sell|invest|hold|entry|stop|target[_ ]price|conviction|position[_ ]size|multibagger|best|top pick)\b/i;
// MOCK — not real data: an extra media event so the withheld-headline path renders (the real PNCINFRA media report is de-duplicated).
const MOCK_MEDIA_EVENT = {
  ord: 2, event_time: "2026-09-15T10:13:00+05:30", source_label: "Economic Times", is_media: true, event_type: "REGULATORY",
  event_subtype: "order_win", direction: "negative", title: null, url: "https://example.com/mock-media", method: "rules",
};

type Reply = { status: number; body: unknown };
async function mockOdds(page: Page, latest?: (head: string) => Reply) {
  await page.route("**/api/move-odds/latest**", (route) => {
    const head = new URL(route.request().url()).searchParams.get("head") ?? "p_up5_1d";
    const r = latest ? latest(head) : { status: 200, body: load(`move-odds-latest-${head}.json`) };
    return route.fulfill({ status: r.status, contentType: "application/json", body: JSON.stringify(r.body) });
  });
  await page.route("**/api/move-odds/stocks/**", (route) => {
    const sym = decodeURIComponent(route.request().url().split("/stocks/")[1].split("?")[0]);
    const file = path.join(FX, `move-odds-stock-${sym}.json`);
    if (!fs.existsSync(file)) return route.fulfill({ status: 404, contentType: "application/json", body: '{"detail":"not_found"}' });
    const body = load(`move-odds-stock-${sym}.json`);
    if (sym === "PNCINFRA") body.data.events = [...body.data.events, MOCK_MEDIA_EVENT];
    return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
  });
}

function pct(p: number | null): string {
  if (p == null) return "—";
  const v = p * 100;
  return v < 0.1 ? "<0.1%" : `${v.toFixed(1)}%`;
}

async function openOdds(page: Page) {
  await page.goto("/v5/research");
  await page.getByTestId("rail-odds").click();
  await expect(page.getByTestId("move-odds-screen")).toBeVisible();
}

test.describe("Move odds — access", () => {
  test.use({ viewport: { width: 1280, height: 800 } });

  test("TC-20 without move_odds the rail item is absent", async ({ page }) => {
    await mockAuthAs(page, "user-profile-onboarded.json");
    await mockOdds(page);
    await page.goto("/v5/research");
    await expect(page.getByTestId("rail-feed")).toBeVisible();
    await expect(page.getByTestId("rail-odds")).toHaveCount(0);
    await expect(page.getByTestId("move-odds-screen")).toHaveCount(0);
  });

  test("TC-20 with move_odds the rail item opens the screen", async ({ page }) => {
    await mockAuthAs(page, "user-profile-move-odds.json");
    await mockOdds(page);
    await openOdds(page);
  });

  test("TC-25 a 403 shows the not-enabled state and no percentages", async ({ page }) => {
    await mockAuthAs(page, "user-profile-move-odds.json");
    await mockOdds(page, () => ({ status: 403, body: { detail: "feature_not_enabled" } }));
    await openOdds(page);
    await expect(page.getByTestId("mo-state-no_access")).toBeVisible();
    await expect(page.locator('[data-testid^="mo-pct-"]')).toHaveCount(0);
    expect(await page.getByTestId("move-odds-screen").innerText()).not.toMatch(/\d+\.\d%/);
  });
});

test.describe("Move odds — final estimates", () => {
  test.use({ viewport: { width: 1280, height: 800 } });

  test.beforeEach(async ({ page }) => {
    await mockAuthAs(page, "user-profile-move-odds.json");
    await mockOdds(page);
    await openOdds(page);
    await expect(page.getByTestId("mo-row-PNCINFRA")).toBeVisible();
  });

  test("TC-21 disclaimer above the numbers, provenance, four tabs with base rates", async ({ page }) => {
    const disc = await page.getByTestId("mo-disclaimer").boundingBox();
    const table = await page.locator(".mo-table").boundingBox();
    expect(disc && table && disc.y + disc.height <= table.y).toBeTruthy();
    await expect(page.getByTestId("mo-disclaimer")).toContainText("does not constitute investment advice");
    const prov = page.getByTestId("mo-provenance");
    await expect(prov).toContainText("Wed 16 Sep");
    await expect(prov).toContainText("Thu 17 Sep");
    await expect(prov).toContainText("994 of 1,000 stocks scored");
    for (const h of HEADS) {
      const base = load(`move-odds-latest-${h}.json`).data.base_rate;
      await expect(page.getByTestId(`mo-tab-${h}`)).toContainText(`base rate ${pct(base)}`);
    }
  });

  test("TC-22 sorted by estimate, no rank column, 50 per page, search filters", async ({ page }) => {
    const headers = (await page.locator(".mo-table thead th").allInnerTexts()).map((t) => t.trim());
    expect(headers.join("|")).not.toMatch(/#|rank/i);
    const rows = page.locator('tbody tr[data-testid^="mo-row-"]');
    await expect(rows).toHaveCount(50);
    const shown = await page.locator('[data-testid^="mo-pct-"]').allInnerTexts();
    const values = load("move-odds-latest-p_up5_1d.json").data.rows.map((r: { p: number }) => r.p);
    const sorted = [...values].sort((a, b) => b - a);
    expect(shown).toEqual(sorted.slice(0, 50).map(pct));
    await page.getByTestId("mo-page-next").click();
    await expect(rows).toHaveCount(10);
    await page.getByTestId("mo-search").fill("antelopus");
    await expect(page.getByTestId("mo-count")).toHaveText("1 stocks");
    await expect(page.getByTestId("mo-row-ANTELOPUS")).toBeVisible();
    await page.getByTestId("mo-tab-p_down5_1d").click();
    await expect(page.getByTestId("mo-tab-p_down5_1d")).toHaveAttribute("aria-selected", "true");
  });

  test("TC-23 details show dated inputs, events, a withheld media headline and the stock's band", async ({ page }) => {
    await page.getByTestId("mo-details-PNCINFRA").click();
    const detail = page.getByTestId("mo-detail-PNCINFRA");
    await expect(detail).toBeVisible();
    const inputs = page.getByTestId("mo-inputs");
    await expect(inputs).toContainText("Close vs previous close");
    await expect(inputs).toContainText("Delivery");
    await expect(inputs).toContainText("Tue 15 Sep · published a day late");
    const events = page.getByTestId("mo-events");
    await expect(events).toContainText("PNCINFRA: Action(s) taken or orders passed");
    await expect(events).toContainText("Media report · headline not shown");
    await expect(page.locator(".mo-bands tr.here")).toContainText("30–40%");
  });

  test("TC-26 rendered text carries no recommendation vocabulary", async ({ page }) => {
    await page.getByTestId("mo-details-PNCINFRA").click();
    await expect(page.getByTestId("mo-detail-PNCINFRA")).toBeVisible();
    const text = await page.getByTestId("move-odds-screen").innerText();
    const hit = text.match(BANNED);
    expect(hit, `banned word: ${hit?.[0]}`).toBeNull();
  });

  test("TC-27 every shown percentage equals the API value at one decimal", async ({ page }) => {
    const data = load("move-odds-latest-p_up5_1d.json").data;
    for (const r of data.rows.slice(0, 50)) {
      await expect(page.getByTestId(`mo-pct-${r.symbol}`)).toHaveText(pct(r.p));
    }
  });
});

test.describe("Move odds — no numbers when there is nothing valid to show", () => {
  test.use({ viewport: { width: 1280, height: 800 } });

  test("TC-24 not published", async ({ page }) => {
    await mockAuthAs(page, "user-profile-move-odds.json");
    await mockOdds(page, (head) => ({ status: 200, body: { data: { status: "not_published", head, expected_session: "2026-09-18", last_published_for: "2026-09-17", rows: [] } } }));
    await openOdds(page);
    await expect(page.getByTestId("mo-state-not_published")).toContainText("Fri 18 Sep");
    await expect(page.locator('[data-testid^="mo-pct-"]')).toHaveCount(0);
    await expect(page.getByTestId("mo-provenance")).toHaveCount(0);
  });

  test("TC-24 withheld", async ({ page }) => {
    await mockAuthAs(page, "user-profile-move-odds.json");
    await mockOdds(page, () => ({ status: 503, body: { detail: "withheld: stale_data", data: { status: "withheld", reason: "stale_data", detail: { rows: 812 }, target_session: "2026-09-18" } } }));
    await openOdds(page);
    await expect(page.getByTestId("mo-state-withheld")).toContainText("stale_data");
    await expect(page.locator('[data-testid^="mo-pct-"]')).toHaveCount(0);
  });

  test("an upstream failure offers a retry and shows no numbers", async ({ page }) => {
    await mockAuthAs(page, "user-profile-move-odds.json");
    await mockOdds(page, () => ({ status: 502, body: { detail: "upstream_unavailable" } }));
    await openOdds(page);
    await expect(page.getByTestId("mo-state-error")).toBeVisible();
    await expect(page.getByTestId("mo-retry")).toBeVisible();
    await expect(page.locator('[data-testid^="mo-pct-"]')).toHaveCount(0);
  });
});

test.describe("Move odds — mobile", () => {
  test.use({ viewport: { width: 390, height: 844 } });

  test("TC-20 the mobile tab bar carries Odds and the table fits the screen", async ({ page }) => {
    await mockAuthAs(page, "user-profile-move-odds.json");
    await mockOdds(page);
    await page.goto("/v5/research");
    await page.getByTestId("mnav-odds").click();
    await expect(page.getByTestId("mo-row-PNCINFRA")).toBeVisible();
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    expect(overflow).toBeLessThanOrEqual(1);
  });
});
