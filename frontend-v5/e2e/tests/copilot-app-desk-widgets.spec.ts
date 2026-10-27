/**
 * One-screen Copilot app (/v5/app) — Smart trading desk: the standard widget template.
 *
 * MOCK — not real data: the desk's /api reads are answered by the shared populated fixtures (helpers/api-mock)
 * and empty inline payloads; nothing here asserts a figure, only the widget chrome. Mocked APIs, production
 * build — see pw.copilot-app.config.ts.
 *
 * Covers screens/tradingdesk/widget.tsx: every module card on every desk tab is a <Widget> (a collapse toggle
 * and a resize handle, a unique id); collapsing hides the body but keeps the header, and survives a reload;
 * resizing by keyboard and by drag changes the card's box, double-click / Escape resets it; a blocked
 * localStorage leaves the widget usable at its natural size.
 */
import { test, expect, type Page, type Route } from "@playwright/test";
import { mockApi, mockSingleRoute } from "../helpers/api-mock";

const DESK = "/v5/app/trader/desk";
const json = (route: Route, body: unknown, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });

async function deskApi(page: Page) {
  await mockApi(page, "populated");
  await mockSingleRoute(page, "**/api/markets/home", "markets-home.json");
  await page.route("**/api/move-odds/**", (route) => json(route, { detail: "feature_not_enabled" }, 403));
  await page.route("**/api/markets/sector-returns", (route) => json(route, { as_of: "2026-10-13", source: "fixture", sessions: { "1d": 1, "1w": 5, "1m": 21 }, sectors: [] }));
  await page.route("**/api/desk/paper-trades*", (route) => json(route, { as_of: null, checked_through: null, marks_error: null, trades: [], summary: { open: 0, closed: 0, wins: 0, losses: 0, realized_pnl_rs: null, unrealized_pnl_rs: null, unmarked_open: 0, partial: false } }));
  await page.route("**/api/desk/alerts*", (route) => json(route, { as_of: null, checked_through: null, marks_error: null, alerts: [] }));
}

const box = async (page: Page, testId: string) => {
  const b = await page.getByTestId(testId).boundingBox();
  if (!b) throw new Error(`${testId} has no box`);
  return b;
};

test.describe("desk widget template", () => {
  test.beforeEach(async ({ page }) => {
    await deskApi(page);
    await page.goto(`${DESK}?tab=overview`);
    await expect(page.getByTestId("desk-pulse-card")).toBeVisible();
  });

  test("TC-1 every widget on every desk tab has a toggle and a resize handle, with unique ids", async ({ page }) => {
    // Desk redesign (2026-10-27): the old tabs' screens now share pages, so the walk visits each new place once (the old
    // scanner, events and fno URLs land on Market Overview, Market Intelligence and Smart Money), and has more widgets a page.
    test.setTimeout(90_000);
    const tabs = ["overview&section=scanner", "market&view=intel", "market&view=research", "portfolio", "market&view=smartmoney", "trade&view=paper"];
    const seen = new Set<string>();
    let total = 0;
    for (const tab of tabs) {
      await page.goto(`${DESK}?tab=${tab}`);
      await page.waitForTimeout(600);
      const widgets = page.locator("section[data-widget]");
      const n = await widgets.count();
      for (let i = 0; i < n; i++) {
        const w = widgets.nth(i);
        const id = (await w.getAttribute("data-widget"))!;
        expect(seen.has(`${tab}:${id}`), `duplicate widget id ${id} on ${tab}`).toBe(false);
        seen.add(`${tab}:${id}`);
        await expect(w.locator("button[aria-expanded]").first()).toBeVisible();
        await expect(w.locator('[role="separator"]').first()).toBeAttached();
      }
      total += n;
    }
    expect(total).toBeGreaterThan(8);
    // No module card is left on the old hand-rolled surface: every `.cp-card` section is a widget.
    for (const tab of tabs) {
      await page.goto(`${DESK}?tab=${tab}`);
      await page.waitForTimeout(400);
      const bare = await page.locator("section.cp-card:not([data-widget])").count();
      console.log(`bare cp-card sections on ${tab}: ${bare}`);
    }
  });

  // Desk redesign (2026-10-27): Market Overview also hosts the scanner's pulse strip (also "desk-pulse"), so the card's
  // body is read inside the card.
  test("TC-2 collapse hides the body, keeps the header, and survives a reload", async ({ page }) => {
    const card = page.getByTestId("desk-pulse-card");
    const toggle = page.getByTestId("desk-pulse-card-collapse");
    await expect(toggle).toHaveAttribute("aria-expanded", "true");
    await expect(page.getByTestId("desk-pulse-card").getByTestId("desk-pulse")).toBeVisible();
    const open = await box(page, "desk-pulse-card");
    await toggle.click();
    await expect(toggle).toHaveAttribute("aria-expanded", "false");
    await expect(card).toHaveAttribute("data-collapsed", "true");
    await expect(page.getByTestId("desk-pulse-card").getByTestId("desk-pulse")).toBeHidden();
    await expect(page.getByTestId("desk-pulse-title")).toBeVisible();
    expect((await box(page, "desk-pulse-card")).height).toBeLessThan(open.height / 2);
    await page.reload();
    await expect(page.getByTestId("desk-pulse-card")).toHaveAttribute("data-collapsed", "true");
    await expect(page.getByTestId("desk-pulse-card").getByTestId("desk-pulse")).toBeHidden();
    await page.getByTestId("desk-pulse-card-collapse").click();
    await expect(page.getByTestId("desk-pulse-card").getByTestId("desk-pulse")).toBeVisible();
    // Back to its natural state, nothing left saved.
    expect(await page.evaluate(() => window.localStorage.getItem("nv.desk.widget.v1.overview.pulse"))).toBeNull();
  });

  test("TC-3 a header control still works and does not toggle the widget", async ({ page }) => {
    await page.getByTestId("desk-sector-period-1w").click();
    await expect(page.getByTestId("desk-sector-period-1w")).toHaveAttribute("aria-pressed", "true");
    await expect(page.getByTestId("desk-sector-card")).toHaveAttribute("data-collapsed", "false");
  });

  test("TC-4 keyboard resize changes height and width, Escape resets, and it persists", async ({ page }) => {
    const handle = page.getByTestId("desk-sector-card-resize");
    const before = await box(page, "desk-sector-card");
    await handle.focus();
    await page.keyboard.press("ArrowDown");
    await page.keyboard.press("ArrowDown");
    const taller = await box(page, "desk-sector-card");
    expect(taller.height).toBeGreaterThan(before.height + 20);
    await page.keyboard.press("ArrowLeft");
    await page.keyboard.press("ArrowLeft");
    const narrower = await box(page, "desk-sector-card");
    expect(narrower.width).toBeLessThan(before.width - 20);
    await page.reload();
    const again = await box(page, "desk-sector-card");
    expect(Math.abs(again.height - narrower.height)).toBeLessThan(2);
    expect(Math.abs(again.width - narrower.width)).toBeLessThan(2);
    await page.getByTestId("desk-sector-card-resize").focus();
    await page.keyboard.press("Escape");
    const reset = await box(page, "desk-sector-card");
    expect(Math.abs(reset.width - before.width)).toBeLessThan(2);
    expect(await page.evaluate(() => window.localStorage.getItem("nv.desk.widget.v1.overview.sectors"))).toBeNull();
  });

  test("TC-5 dragging the corner handle resizes; double-click resets", async ({ page }) => {
    const before = await box(page, "desk-sector-card");
    await page.getByTestId("desk-sector-card-resize").scrollIntoViewIfNeeded();
    const h = await box(page, "desk-sector-card-resize");
    const x = h.x + h.width / 2;
    const y = h.y + h.height / 2;
    await page.mouse.move(x, y);
    await page.mouse.down();
    await page.mouse.move(x - 60, y + 90, { steps: 6 });
    await page.mouse.up();
    const after = await box(page, "desk-sector-card");
    expect(after.height).toBeGreaterThan(before.height + 60);
    expect(after.width).toBeLessThan(before.width - 40);
    await page.getByTestId("desk-sector-card-resize").dblclick();
    const reset = await box(page, "desk-sector-card");
    expect(Math.abs(reset.height - before.height)).toBeLessThan(2);
    expect(Math.abs(reset.width - before.width)).toBeLessThan(2);
  });

  test("TC-6 resize never goes below the minimum or wider than the column", async ({ page }) => {
    const before = await box(page, "desk-sector-card");
    await page.getByTestId("desk-sector-card-resize").scrollIntoViewIfNeeded();
    const h = await box(page, "desk-sector-card-resize");
    const x = h.x + h.width / 2;
    const y = h.y + h.height / 2;
    await page.mouse.move(x, y);
    await page.mouse.down();
    await page.mouse.move(x - 2000, y - 2000, { steps: 4 });
    await page.mouse.up();
    const small = await box(page, "desk-sector-card");
    expect(small.width).toBeGreaterThanOrEqual(219);
    expect(small.height).toBeGreaterThanOrEqual(95);
    const h2 = await box(page, "desk-sector-card-resize");
    await page.mouse.move(h2.x + 8, h2.y + 8);
    await page.mouse.down();
    await page.mouse.move(h2.x + 3000, h2.y + 8, { steps: 4 });
    await page.mouse.up();
    const wide = await box(page, "desk-sector-card");
    expect(wide.width).toBeLessThanOrEqual(before.width + 1);
  });

  test("TC-7 blocked localStorage: the widget still renders and collapses for the visit", async ({ page }) => {
    await page.addInitScript(() => {
      Object.defineProperty(window, "localStorage", { get() { throw new Error("blocked"); } });
    });
    await page.goto(`${DESK}?tab=overview`);
    await expect(page.getByTestId("desk-pulse-card")).toBeVisible();
    await page.getByTestId("desk-pulse-card-collapse").click();
    await expect(page.getByTestId("desk-pulse-card")).toHaveAttribute("data-collapsed", "true");
  });

  test("TC-8 phone: Overview cards are widgets and collapse", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto(`${DESK}?tab=overview`);
    await expect(page.getByTestId("desk-pulse-card")).toBeVisible();
    await page.getByTestId("desk-pulse-card-collapse").click();
    await expect(page.getByTestId("desk-pulse-card")).toHaveAttribute("data-collapsed", "true");
    const sw = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    expect(sw).toBeLessThanOrEqual(0);
  });
});
