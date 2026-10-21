/**
 * One-screen Copilot (/v5/app) — thread bookmark, tag, clear and the 2-day
 * rail window. Test-case ids (TC-T*) match test_reports/copilot_threads_*.md.
 * Every /api/* call is a route mock; PATCH/DELETE mutate the mocked list.
 */
import { test, expect, type Page } from "@playwright/test";
import { mockApi, mockSingleRoute } from "../helpers/api-mock";

const APP = "/v5/app";
const DAY = 24 * 60 * 60 * 1000;
const ago = (ms: number) => new Date(Date.now() - ms).toISOString();

interface Sess { session_id: string; title: string; updated_at: string; bookmarked?: boolean; tags?: string[] }
interface Calls { patches: Array<{ id: string; body: Record<string, unknown> }>; deletes: string[] }

async function setup(page: Page, initial: Sess[]): Promise<Calls> {
  await mockApi(page, "populated");
  await mockSingleRoute(page, "**/api/markets/home", "markets-home.json");
  const calls: Calls = { patches: [], deletes: [] };
  let sessions = [...initial];
  const json = (body: unknown) => ({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
  await page.route("**/api/chat/sessions", (route) => route.fulfill(json(sessions)));
  await page.route("**/api/chat/sessions/*", (route) => {
    const id = decodeURIComponent(new URL(route.request().url()).pathname.split("/").pop() ?? "");
    const m = route.request().method();
    if (m === "PATCH") {
      const body = route.request().postDataJSON() as Record<string, unknown>;
      calls.patches.push({ id, body });
      sessions = sessions.map((s) => (s.session_id === id ? { ...s, ...body } as Sess : s));
      return route.fulfill(json({ session_id: id, ...body }));
    }
    if (m === "DELETE") {
      calls.deletes.push(id);
      sessions = sessions.filter((s) => s.session_id !== id);
      return route.fulfill(json({ message: "Session deleted" }));
    }
    return route.fulfill(json([]));
  });
  await page.route("**/api/chat/messages*", (route) => route.fulfill(json([])));
  return calls;
}

const rowFor = (page: Page, title: string) => page.getByTestId("thread-row-wrap").filter({ hasText: title });

test.describe("Copilot threads — bookmark, tag, clear, 2-day window", () => {
  test("TC-T1 rail shows only threads from the last 2 days; older ones sit under Past conversations", async ({ page }) => {
    await setup(page, [
      { session_id: "s1", title: "Fresh question", updated_at: ago(60_000) },
      { session_id: "s2", title: "One day old", updated_at: ago(DAY) },
      { session_id: "s3", title: "Three days old", updated_at: ago(3 * DAY) },
      { session_id: "s4", title: "Old but bookmarked", updated_at: ago(9 * DAY), bookmarked: true },
    ]);
    await page.goto(APP);
    await expect(page.getByTestId("thread-row")).toHaveCount(2);
    await expect(page.getByTestId("copilot-rail")).not.toContainText("Three days old");
    await expect(page.getByTestId("copilot-rail")).not.toContainText("Old but bookmarked");
    await expect(page.getByTestId("past-conversations")).toContainText("2");
    await page.getByTestId("past-conversations").click();
    await expect(page).toHaveURL(/\/v5\/app\/page\/history$/);
    const screen = page.getByTestId("screen-page-history");
    await expect(screen).toContainText("Three days old");
    await expect(screen).toContainText("Old but bookmarked");
    await expect(screen).not.toContainText("Fresh question");
    await page.getByTestId("history-search").fill("three");
    await expect(screen.getByTestId("thread-row")).toHaveCount(1);
  });

  test("TC-T2 bookmark sends PATCH, floats the thread to the top and filters", async ({ page }) => {
    const calls = await setup(page, [
      { session_id: "s1", title: "Newest", updated_at: ago(60_000) },
      { session_id: "s2", title: "Older one", updated_at: ago(DAY) },
    ]);
    await page.goto(APP);
    await rowFor(page, "Older one").getByTestId("thread-bookmark").click();
    await expect.poll(() => calls.patches).toEqual([{ id: "s2", body: { bookmarked: true } }]);
    await expect(page.getByTestId("thread-row").first()).toContainText("Older one");
    await page.getByTestId("thread-filter").getByRole("button", { name: "★ saved" }).click();
    await expect(page.getByTestId("thread-row")).toHaveCount(1);
  });

  test("TC-T3 tags: add with Enter, show as a chip, filter by it, remove it", async ({ page }) => {
    const calls = await setup(page, [{ session_id: "s1", title: "Banks thread", updated_at: ago(60_000) }]);
    await page.goto(APP);
    const row = rowFor(page, "Banks thread");
    await row.hover();
    await row.getByTestId("thread-tag").click();
    await page.getByTestId("thread-tag-input").fill("Banking");
    await page.getByTestId("thread-tag-input").press("Enter");
    await expect.poll(() => calls.patches.at(-1)).toEqual({ id: "s1", body: { tags: ["banking"] } });
    await expect(page.getByTestId("thread-tag-chip")).toContainText("banking");
    await expect(page.getByTestId("thread-filter")).toContainText("#banking");
    await page.getByRole("button", { name: "Remove tag banking" }).click();
    await expect.poll(() => calls.patches.at(-1)).toEqual({ id: "s1", body: { tags: [] } });
    await expect(page.getByTestId("thread-tag-chip")).toHaveCount(0);
  });

  test("TC-T4 clear asks first; Keep cancels, Clear sends DELETE and removes the row", async ({ page }) => {
    const calls = await setup(page, [
      { session_id: "s1", title: "Keep me", updated_at: ago(60_000) },
      { session_id: "s2", title: "Clear me", updated_at: ago(120_000) },
    ]);
    await page.goto(APP);
    const row = rowFor(page, "Clear me");
    await row.hover();
    await row.getByTestId("thread-clear").click();
    await page.getByRole("button", { name: "Keep", exact: true }).click();
    expect(calls.deletes).toEqual([]);
    await row.hover();
    await row.getByTestId("thread-clear").click();
    await page.getByTestId("thread-clear-confirm").click();
    await expect.poll(() => calls.deletes).toEqual(["s2"]);
    await expect(page.getByTestId("thread-row")).toHaveCount(1);
    await expect(page.getByTestId("copilot-rail")).not.toContainText("Clear me");
  });

  test("TC-T5 clearing the open thread returns to home", async ({ page }) => {
    await setup(page, [{ session_id: "s1", title: "Open thread", updated_at: ago(60_000) }]);
    await page.goto(`${APP}/t/s1`);
    const row = rowFor(page, "Open thread");
    await row.hover();
    await row.getByTestId("thread-clear").click();
    await page.getByTestId("thread-clear-confirm").click();
    await expect(page).toHaveURL(/\/v5\/app$/);
  });
});
