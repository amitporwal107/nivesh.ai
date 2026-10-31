/**
 * One-screen Copilot app (/v5/app) — stock autocomplete in the ask box and in the trading desk's Copilot panel
 * (src/pages/CopilotApp/lib/stock-completion.tsx): SC-12 … SC-16 of test_reports/copilot_stock_autocomplete_20261029.md.
 *
 * GET /api/chat/instrument-search is an inline MOCK — not real data — in the route's real shape (backend/routes/chat.py
 * chat_instrument_search; services/stock_search.py tail_search): with `tail=1` it answers the fragment at the end of the
 * text before the cursor and where it starts, as the real route does for these texts (checked against the staging symbol
 * master on 29 Oct: "…for tvs mo" → TVSMOTOR, "infy" → INFY). Mocked APIs, production build (pw.copilot-app.config.ts).
 */
import { test, expect, type Page, type Route } from "@playwright/test";
import { mockApi, mockSingleRoute } from "../helpers/api-mock";

const APP = "/v5/app";
const DESK = `${APP}/trader/desk`;
const SLOW = { timeout: 15_000 };
const json = (route: Route, body: unknown, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
const sse = (frames: Array<Record<string, unknown>>) => frames.map((f) => `data: ${JSON.stringify(f)}\n\n`).join("");

const MASTER = {  // MOCK rows
  TVSMOTOR: { symbol: "TVSMOTOR", name: "TVS Motor Company Limited", sector: "Automobile", kind: "stock" },
  INFY: { symbol: "INFY", name: "Infosys Limited", sector: "IT", kind: "stock" },
};
const FRAGMENTS: Array<[string, Array<keyof typeof MASTER>]> = [["tvs mo", ["TVSMOTOR"]], ["infy", ["INFY"]]];

interface Seen { tail: string[]; streams: string[] }

async function routes(page: Page): Promise<Seen> {
  const seen: Seen = { tail: [], streams: [] };
  await page.route("**/api/chat/instrument-search*", (r) => {
    const u = new URL(r.request().url());
    const q = u.searchParams.get("q") ?? "";
    if (u.searchParams.get("tail")) {
      seen.tail.push(q);
      for (const [frag, syms] of FRAGMENTS) {
        if (q.toLowerCase().endsWith(frag)) {
          const start = q.length - frag.length;
          return json(r, { stocks: syms.map((s) => MASTER[s]), funds: [], fragment: q.slice(start), fragment_start: start });
        }
      }
      return json(r, { stocks: [], funds: [], fragment: null, fragment_start: null });
    }
    return json(r, q.trim().toLowerCase() === "infy" ? { stocks: [MASTER.INFY], funds: [] } : { stocks: [], funds: [] });
  });
  await page.route("**/api/chat/suggest-queries*", (r) => json(r, { suggestions: [] }));
  await page.route("**/api/chat/sessions", (r) => r.request().method() === "POST" ? json(r, { session_id: "new1", id: "new1" }) : json(r, []));
  await page.route("**/api/chat/messages*", (r) => json(r, []));
  await page.route("**/api/chat/stream", (r) => {
    seen.streams.push((r.request().postDataJSON() as { message: string }).message);
    return r.fulfill({ status: 200, contentType: "text/event-stream", body: sse([
      { type: "meta", session_id: "new1", ai_msg_id: "a1", user_msg_id: "u1" },
      { type: "token", content: "MOCK answer." }, { type: "done", content: "MOCK answer.", follow_ups: [] }]) });
  });
  return seen;
}

async function app(page: Page) {
  await mockApi(page, "populated");
  await mockSingleRoute(page, "**/api/markets/home", "markets-home.json");
  const seen = await routes(page);
  await page.goto(APP);
  return seen;
}

const caretAt = (page: Page, testId: string) => page.getByTestId(testId).evaluate((el) => (el as HTMLInputElement).selectionStart);

test.describe("MOCK — not real data: stock autocomplete in the Copilot", () => {
  test("SC-12 the stock being typed is offered first; Tab completes it with the ticker and sends nothing", async ({ page }) => {
    const seen = await app(page);
    const input = page.getByTestId("composer-input");
    await input.click();
    await input.pressSequentially("Plan a breakout trade for tvs mo", { delay: 5 });
    const first = page.getByTestId("composer-suggest-item").first();
    await expect(first).toHaveAttribute("data-kind", "stock-completion", SLOW);
    await expect(first).toContainText("TVSMOTOR");
    await expect(first).toContainText("TVS Motor Company Limited · Automobile");
    expect(seen.tail.at(-1)).toBe("Plan a breakout trade for tvs mo");
    await input.press("Tab");
    await expect(input).toHaveValue("Plan a breakout trade for TVSMOTOR ");
    expect(await caretAt(page, "composer-input")).toBe("Plan a breakout trade for TVSMOTOR ".length);
    await expect(input).toBeFocused();
    expect(seen.streams).toEqual([]);
  });

  test("SC-13 arrow + Enter, or a click, completes; the next Enter asks the completed question", async ({ page }) => {
    const seen = await app(page);
    const input = page.getByTestId("composer-input");
    await input.click();
    await input.pressSequentially("Plan a breakout trade for tvs mo", { delay: 5 });
    await expect(page.getByTestId("composer-suggest-item").first()).toHaveAttribute("data-kind", "stock-completion", SLOW);
    await input.press("ArrowDown");
    await input.press("Enter");
    await expect(input).toHaveValue("Plan a breakout trade for TVSMOTOR ");
    expect(seen.streams).toEqual([]);
    await input.press("Enter");
    await expect.poll(() => seen.streams).toEqual(["Plan a breakout trade for TVSMOTOR"]);

    await input.click();
    await input.pressSequentially("entry for tvs mo", { delay: 5 });
    await page.getByTestId("composer-suggest-item").first().click(SLOW);
    await expect(input).toHaveValue("entry for TVSMOTOR ");
  });

  test("SC-14 the words after the cursor are kept", async ({ page }) => {
    await app(page);
    const input = page.getByTestId("composer-input");
    await input.click();
    await input.pressSequentially("trade tvs mo on breakout", { delay: 5 });
    for (let i = 0; i < " on breakout".length; i++) await input.press("ArrowLeft");
    await expect(page.getByTestId("composer-suggest-item").first()).toHaveAttribute("data-kind", "stock-completion", SLOW);
    await input.press("Tab");
    await expect(input).toHaveValue("trade TVSMOTOR on breakout");
    expect(await caretAt(page, "composer-input")).toBe("trade TVSMOTOR".length);
  });

  test("SC-15 a name on its own also keeps 'Research …', which asks", async ({ page }) => {
    const seen = await app(page);
    const input = page.getByTestId("composer-input");
    await input.click();
    await input.pressSequentially("infy", { delay: 5 });
    const items = page.getByTestId("composer-suggest-item");
    await expect(items.first()).toHaveAttribute("data-kind", "stock-completion", SLOW);
    await expect(items.first()).toContainText("INFY");
    await expect(page.getByTestId("composer-suggest")).toContainText("Research Infosys Limited");
    await page.getByTestId("composer-suggest-item").filter({ hasText: "Research Infosys Limited" }).click();
    await expect.poll(() => seen.streams).toEqual(["Tell me about Infosys Limited"]);
  });

  test("SC-16 the trading desk's Copilot panel completes the same way", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });                       // the Copilot docks from 1400px
    await mockApi(page, "populated");
    await mockSingleRoute(page, "**/api/markets/home", "markets-home.json");
    await page.route("**/api/move-odds/**", (r) => json(r, { detail: "feature_not_enabled" }, 403));
    await page.route("**/api/desk/paper-trades*", (r) => json(r, { as_of: null, checked_through: null, marks_error: null, trades: [], summary: { open: 0, closed: 0, wins: 0, losses: 0, realized_pnl_rs: null, unrealized_pnl_rs: null, unmarked_open: 0, partial: false } }));
    await page.route("**/api/desk/alerts*", (r) => json(r, { as_of: null, checked_through: null, marks_error: null, alerts: [] }));
    const seen = await routes(page);
    await page.goto(DESK);
    const input = page.getByTestId("dock-input");
    await input.click();
    await input.pressSequentially("Plan a trade on tvs mo", { delay: 5 });
    await expect(page.getByTestId("dock-complete-item")).toHaveText([/TVSMOTOR/], SLOW);
    await input.press("Tab");
    await expect(input).toHaveValue("Plan a trade on TVSMOTOR ");
    await expect(page.getByTestId("dock-complete")).toHaveCount(0);
    expect(seen.streams).toEqual([]);
    await input.press("Enter");
    await expect.poll(() => seen.streams).toEqual(["Plan a trade on TVSMOTOR"]);
  });
});
