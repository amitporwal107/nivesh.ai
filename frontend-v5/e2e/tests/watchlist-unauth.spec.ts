/**
 * Research Watchlist — public page at /watchlist on REAL staging (no auth).
 * No mocks, no login: a cold browser context hitting the live backend, same
 * as a visitor arriving from a direct link.
 *
 * Lists are dated snapshots. The 41-pick assertions are pinned to the list
 * first published on 2026-10-06 (`?list=`), so they hold whatever the newest
 * list is. Cases: test_reports/research_watchlist_functionality.md (TC-5/6/8)
 * and test_reports/research_watchlist_history_*.md (TC-11..TC-14).
 */
import { test, expect } from "@playwright/test";

const UI = "https://staging.niveshcopilot.com/v5/watchlist";
const API = "https://staging.niveshcopilot.com/api/public/research-watchlist";
const FIRST_LIST = "2026-10-06";
const FIRST_LIST_UI = `${UI}?list=${FIRST_LIST}`;

test.describe("Research Watchlist public page", () => {
  // TC-5 — reachable with no session, no redirect to /login, all 41 rows render.
  test("TC-5 renders unauthenticated with all picks", async ({ page }) => {
    await page.goto(FIRST_LIST_UI);
    await expect(page).not.toHaveURL(/\/login/);
    await expect(page.getByText(/Loading watchlist/i)).toHaveCount(0, { timeout: 15_000 });
    await expect(page.getByText(/41 of 41 picks shown/i)).toBeVisible();
    await expect(page.getByText("CUMMINSIND")).toBeVisible();
  });

  // TC-8 — live quote overlay: the LIVE badge shows, a row's price is a real
  // number, and expanding a row reveals the fundamental/technical deep-dive.
  test("TC-8 shows the LIVE badge and a row expands into the deep-dive", async ({ page }) => {
    await page.goto(FIRST_LIST_UI);
    await expect(page.getByText(/41 of 41 picks shown/i)).toBeVisible({ timeout: 15_000 });
    await expect(page.getByText("LIVE", { exact: true })).toBeVisible();
    const row = page.getByText("CUMMINSIND").locator("xpath=ancestor::button[1]");
    await expect(row).toContainText(/₹[\d,]+\.\d{2}/);
    await row.click();
    await expect(page.getByText(/Balance sheet/i)).toBeVisible();
  });

  // TC-6 — tier filter chips change the visible card count.
  test("TC-6 tier filter narrows the visible cards", async ({ page }) => {
    await page.goto(FIRST_LIST_UI);
    await expect(page.getByText(/41 of 41 picks shown/i)).toBeVisible({ timeout: 15_000 });
    await page.getByRole("button", { name: /^Speculative$/ }).click();
    const summary = page.getByText(/of 41 picks shown/i);
    await expect(summary).toBeVisible();
    const text = (await summary.textContent()) ?? "";
    const shown = Number(text.match(/(\d+) of 41/)?.[1] ?? "41");
    expect(shown).toBeLessThan(41);
  });
});

test.describe("Research Watchlist dated lists", () => {
  // TC-11 — the bare URL opens the newest list, and the picker offers every published date.
  test("TC-11 opens on the newest list with a list picker", async ({ page, request }) => {
    const meta = (await (await request.get(API)).json()).meta;
    await page.goto(UI);
    await expect(page).not.toHaveURL(/\/login/);
    await expect(page.getByText(new RegExp(`${meta.count} of ${meta.count} picks shown`))).toBeVisible({ timeout: 15_000 });
    const picker = page.getByLabel("Watchlist date");
    await expect(picker).toHaveValue(meta.list_date);
    await expect(picker.locator("option")).toHaveCount(meta.available_dates.length);
    await expect(picker.locator("option").first()).toContainText("latest");
  });

  // TC-13 — a date nothing was published on is a clear message with a way back, not a blank page.
  test("TC-13 unknown list date shows a message and a way back", async ({ page }) => {
    await page.goto(`${UI}?list=2020-01-01`);
    await expect(page.getByText(/No watchlist was published for 1 Jan 2020/i)).toBeVisible({ timeout: 15_000 });
    await page.getByRole("button", { name: /Show the latest list/i }).click();
    await expect(page).not.toHaveURL(/list=/);
    await expect(page.getByText(/picks shown/i)).toBeVisible({ timeout: 15_000 });
  });

  // TC-14 — choosing another date in the picker switches the list and the URL, and back again.
  test("TC-14 the picker switches between lists", async ({ page, request }) => {
    const meta = (await (await request.get(API)).json()).meta;
    test.skip(meta.available_dates.length < 2, "needs two published lists on staging");
    const older = meta.available_dates[meta.available_dates.length - 1];
    await page.goto(UI);
    const picker = page.getByLabel("Watchlist date");
    await expect(picker).toHaveValue(meta.list_date, { timeout: 15_000 });
    await picker.selectOption(older.list_date);
    await expect(page).toHaveURL(new RegExp(`list=${older.list_date}`));
    await expect(page.getByText(new RegExp(`${older.count} of ${older.count} picks shown`))).toBeVisible({ timeout: 15_000 });
    await expect(page.getByText(/earlier list/i)).toBeVisible();
    await picker.selectOption(meta.list_date);
    await expect(page).not.toHaveURL(/list=/);
    await expect(page.getByText(new RegExp(`${meta.count} of ${meta.count} picks shown`))).toBeVisible({ timeout: 15_000 });
  });
});
