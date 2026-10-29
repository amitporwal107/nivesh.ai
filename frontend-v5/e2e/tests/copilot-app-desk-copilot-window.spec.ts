/**
 * Trading desk — the Copilot as a window: locked in the right column (default) or floating over the desk, dragged by its
 * header and resized from its corner, remembered per browser (screens/tradingdesk/copilot-window.tsx). FW-1 … FW-8 of
 * test_reports/copilot_floating_window_20261029.md.
 *
 * Every /api response is an inline MOCK — not real data — in the real route's shape; nothing here is read from a server.
 * Mocked APIs, production build (pw.copilot-app.config.ts).
 */
import { test, expect, type Page, type Route } from "@playwright/test";
import { mockApi, mockSingleRoute } from "../helpers/api-mock";

const DESK = "/v5/app/trader/desk";
const SLOW = { timeout: 15_000 };
const json = (route: Route, body: unknown, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
const sse = (frames: Array<Record<string, unknown>>) => frames.map((f) => `data: ${JSON.stringify(f)}\n\n`).join("");

async function desk(page: Page, width = 1440) {
  await page.setViewportSize({ width, height: 900 });
  await mockApi(page, "populated");
  await mockSingleRoute(page, "**/api/markets/home", "markets-home.json");
  await page.route("**/api/move-odds/**", (r) => json(r, { detail: "feature_not_enabled" }, 403));
  await page.route("**/api/desk/paper-trades*", (r) => json(r, { as_of: null, checked_through: null, marks_error: null, trades: [], summary: { open: 0, closed: 0, wins: 0, losses: 0, realized_pnl_rs: null, unrealized_pnl_rs: null, unmarked_open: 0, partial: false } }));
  await page.route("**/api/desk/alerts*", (r) => json(r, { as_of: null, checked_through: null, marks_error: null, alerts: [] }));
  await page.route("**/api/chat/instrument-search*", (r) => json(r, { stocks: [], funds: [], fragment: null, fragment_start: null }));
  await page.route("**/api/chat/suggest-queries*", (r) => json(r, { suggestions: [] }));
  await page.route("**/api/chat/sessions", (r) => r.request().method() === "POST" ? json(r, { session_id: "desk1", id: "desk1" }) : json(r, []));
  // The thread is re-read after an answer is saved, so the mock keeps what was asked and answered.
  const saved: Array<Record<string, unknown>> = [];
  await page.route("**/api/chat/messages*", (r) => json(r, saved));
  const streams: Array<{ message: string; surface?: string }> = [];
  await page.route("**/api/chat/stream", (r) => {
    const body = r.request().postDataJSON() as { message: string; surface?: string };
    streams.push(body);
    const now = new Date().toISOString();
    saved.push({ message_id: `u${streams.length}`, session_id: "desk1", role: "user", content: body.message, created_at: now },
      { message_id: `a${streams.length}`, session_id: "desk1", role: "assistant", content: "MOCK answer from the floating Copilot.", created_at: now });
    return r.fulfill({ status: 200, contentType: "text/event-stream", body: sse([
      { type: "meta", session_id: "desk1", ai_msg_id: "a1", user_msg_id: "u1" },
      { type: "token", content: "MOCK answer from the floating Copilot." }, { type: "done", content: "MOCK answer from the floating Copilot.", follow_ups: [] }]) });
  });
  await page.goto(DESK);
  await expect(page.getByTestId("desk-dock")).toBeVisible(SLOW);
  return streams;
}

const box = async (page: Page, testId: string) => (await page.getByTestId(testId).boundingBox())!;

async function dragBy(page: Page, testId: string, dx: number, dy: number, at: "center" | "header-left" = "center") {
  const b = await box(page, testId);
  const x = at === "center" ? b.x + b.width / 2 : b.x + 70;
  const y = b.y + b.height / 2;
  await page.mouse.move(x, y);
  await page.mouse.down();
  await page.mouse.move(x + dx / 2, y + dy / 2, { steps: 4 });
  await page.mouse.move(x + dx, y + dy, { steps: 4 });
  await page.mouse.up();
}

test.describe("MOCK — not real data: the desk Copilot window", () => {
  test("FW-1 first visit: locked in the right column; the button offers Float", async ({ page }) => {
    await desk(page);
    await expect(page.getByTestId("desk-dock")).toHaveAttribute("data-window", "locked");
    await expect(page.getByTestId("desk-dock-float")).toHaveCount(0);
    await expect(page.getByTestId("dock-window-toggle")).toHaveText("Float");
    await expect(page.getByTestId("desk-docked-note")).toHaveText("Copilot docked right");
    expect(Math.abs((await box(page, "desk-dock")).width - 384)).toBeLessThanOrEqual(1);
  });

  test("FW-2 Float: a window over the desk, which takes the full width", async ({ page }) => {
    await desk(page);
    const before = await box(page, "desk-panel-overview").catch(() => null);
    await page.getByTestId("dock-window-toggle").click();
    await expect(page.getByTestId("desk-dock-float")).toBeVisible();
    await expect(page.getByTestId("desk-dock")).toHaveAttribute("data-window", "floating");
    await expect(page.getByTestId("dock-window-toggle")).toHaveText("Lock");
    await expect(page.getByTestId("desk-docked-note")).toHaveText("Copilot floating");
    const f = await box(page, "desk-dock-float");
    expect(f.width).toBe(400);
    expect(await page.getByTestId("desk-dock-float").evaluate((el) => getComputedStyle(el).position)).toBe("fixed");
    if (before) expect((await box(page, "desk-panel-overview")).width).toBeGreaterThan(before.width + 300);
  });

  test("FW-3 drag by the header moves it; it never leaves the screen; a header button is not a handle", async ({ page }) => {
    await desk(page);
    await page.getByTestId("dock-window-toggle").click();
    const a = await box(page, "desk-dock-float");
    await dragBy(page, "dock-header", -300, 120, "header-left");
    const b = await box(page, "desk-dock-float");
    expect(Math.round(b.x - a.x)).toBe(-300);
    expect(Math.round(b.y - a.y)).toBe(120);
    await dragBy(page, "dock-header", 5000, 5000, "header-left");
    const c = await box(page, "desk-dock-float");
    expect(c.x).toBeLessThanOrEqual(1440 - 140);
    expect(c.y).toBeLessThanOrEqual(900 - 56);
    // Dragging from the Lock button does not move the window (it is a button, and a click on it locks).
    const d0 = await box(page, "desk-dock-float");
    const t = await box(page, "dock-window-toggle");
    await page.mouse.move(t.x + t.width / 2, t.y + t.height / 2);
    await page.mouse.down();
    await page.mouse.move(t.x - 200, t.y + 50, { steps: 4 });
    await page.mouse.up();
    const d1 = await box(page, "desk-dock-float");
    expect([d1.x, d1.y]).toEqual([d0.x, d0.y]);
  });

  test("FW-4 the corner handle resizes, down to the minimum size", async ({ page }) => {
    await desk(page);
    await page.getByTestId("dock-window-toggle").click();
    await dragBy(page, "dock-header", -500, 0, "header-left");          // room to grow
    const a = await box(page, "desk-dock-float");
    await dragBy(page, "dock-resize", 120, -80);
    const b = await box(page, "desk-dock-float");
    expect(Math.round(b.width - a.width)).toBe(120);
    expect(Math.round(b.height - a.height)).toBe(-80);
    await dragBy(page, "dock-resize", -2000, -2000);
    const c = await box(page, "desk-dock-float");
    expect([Math.round(c.width), Math.round(c.height)]).toEqual([340, 420]);
  });

  test("FW-5 / FW-6 floating, its place and size survive a reload; Lock puts it back, and that survives too", async ({ page }) => {
    await desk(page);
    await page.getByTestId("dock-window-toggle").click();
    await dragBy(page, "dock-header", -260, 60, "header-left");
    await dragBy(page, "dock-resize", 60, 40);
    const a = await box(page, "desk-dock-float");
    await page.reload();
    await expect(page.getByTestId("desk-dock-float")).toBeVisible(SLOW);
    const b = await box(page, "desk-dock-float");
    expect([Math.round(b.x), Math.round(b.y), Math.round(b.width), Math.round(b.height)]).toEqual([Math.round(a.x), Math.round(a.y), Math.round(a.width), Math.round(a.height)]);
    await page.getByTestId("dock-window-toggle").click();
    await expect(page.getByTestId("desk-dock")).toHaveAttribute("data-window", "locked");
    await page.reload();
    await expect(page.getByTestId("desk-dock")).toHaveAttribute("data-window", "locked", SLOW);
    await expect(page.getByTestId("desk-dock-float")).toHaveCount(0);
  });

  test("FW-7 asking from the floating window works as before", async ({ page }) => {
    const streams = await desk(page);
    await page.getByTestId("dock-window-toggle").click();
    const float = page.getByTestId("desk-dock-float");
    await float.getByTestId("dock-input").fill("How is the market today?");
    await float.getByTestId("dock-send").click();
    await expect(float.getByTestId("dock-answer")).toHaveText("MOCK answer from the floating Copilot.", SLOW);
    expect(streams[0]).toMatchObject({ message: "How is the market today?", surface: "trading_desk" });
  });

  test("FW-8 below 1400px nothing changes: the Copilot button, no Float", async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 800 });
    await mockApi(page, "populated");
    await mockSingleRoute(page, "**/api/markets/home", "markets-home.json");
    await page.route("**/api/move-odds/**", (r) => json(r, { detail: "feature_not_enabled" }, 403));
    await page.goto(DESK);
    await expect(page.getByTestId("desk-copilot-button")).toBeVisible(SLOW);
    await expect(page.getByTestId("dock-window-toggle")).toHaveCount(0);
    await expect(page.getByTestId("desk-dock-float")).toHaveCount(0);
  });
});
