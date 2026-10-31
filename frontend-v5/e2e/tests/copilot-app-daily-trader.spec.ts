/**
 * The Daily Trader Copilot's entry point on the Trader home (components/DailyTraderPanel.tsx): the owner's six entry
 * points, the question box and "Explore this question" (owner, 30 Oct). DT-1 … DT-7 of
 * test_reports/daily_trader_home_20261030.md.
 *
 * Every /api response is an inline MOCK — not real data — in the real route's shape. Production build, mocked APIs
 * (pw.copilot-app.config.ts).
 */
import { test, expect, type Page, type Route } from "@playwright/test";
import { mockApi, mockSingleRoute } from "../helpers/api-mock";

const APP = "/v5/app";
const SLOW = { timeout: 15_000 };
const json = (route: Route, body: unknown, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
const sse = (frames: Array<Record<string, unknown>>) => frames.map((f) => `data: ${JSON.stringify(f)}\n\n`).join("");

const TILES = ["Market pulse", "Find opportunities", "My positions", "F&O strategies", "Manage risk", "Daily review"];
const LEAD: Record<string, string> = {
  pulse: "What is the market view today for Nifty and Bank Nifty?",
  opportunities: "Find today's top 5 trading opportunities with entry, stop-loss and targets",
  positions: "What are my open trades doing?",
  fno: "Which F&O setups are attractive?",
  risk: "How much should I risk?",
  review: "What did I learn from today's trades?",
};

async function setup(page: Page, mode: "trader" | "investor", width = 1280, promptUrls?: string[]) {
  await page.setViewportSize({ width, height: 900 });
  await page.addInitScript((m) => {
    try { localStorage.setItem("nivesh.copilot", JSON.stringify({ state: { mode: m, evidenceOpen: false }, version: 0 })); } catch { /* storage blocked */ }
  }, mode);
  await mockApi(page, "populated");
  await mockSingleRoute(page, "**/api/markets/home", "markets-home.json");
  await page.route("**/api/move-odds/**", (r) => json(r, { detail: "feature_not_enabled" }, 403));
  // MOCK: the stock being typed at the cursor.
  await page.route("**/api/chat/instrument-search*", (r) => {
    const q = new URL(r.request().url()).searchParams.get("q") ?? "";
    const m = /tvs mo$/i.exec(q);
    return json(r, m ? { stocks: [{ symbol: "TVSMOTOR", name: "TVS Motor Company Limited", sector: "Automobile", kind: "stock" }], funds: [], fragment: m[0], fragment_start: m.index }
      : { stocks: [], funds: [], fragment: null, fragment_start: null });
  });
  const streams: Array<Record<string, unknown>> = [];
  const saved: Array<Record<string, unknown>> = [];
  await page.route("**/api/chat/sessions", (r) => (r.request().method() === "POST" ? json(r, { session_id: "dt1", id: "dt1" }) : json(r, [])));
  await page.route("**/api/chat/messages*", (r) => json(r, saved));
  await page.route("**/api/chat/stream", (r) => {
    const body = r.request().postDataJSON() as Record<string, unknown>;
    streams.push(body);
    const now = new Date().toISOString();
    saved.push({ message_id: "u1", session_id: "dt1", role: "user", content: body.message, created_at: now },
      { message_id: "a1", session_id: "dt1", role: "assistant", content: "MOCK answer.", created_at: now });
    return r.fulfill({ status: 200, contentType: "text/event-stream", body: sse([
      { type: "meta", session_id: "dt1", ai_msg_id: "a1", user_msg_id: "u1" },
      { type: "token", content: "MOCK answer." }, { type: "done", content: "MOCK answer.", follow_ups: [] }]) });
  });
  if (promptUrls) {
    // MOCK, shaped like GET /api/copilot/suggested-prompts: an advisor-workspace account gets the client-book list
    // unless the app says it is in Trader mode.
    await page.route("**/api/copilot/suggested-prompts*", (r) => {
      const u = new URL(r.request().url());
      promptUrls.push(u.pathname + u.search);
      return json(r, u.searchParams.get("mode") === "trader"
        ? { mode: "trader", persona: "trader", prompts: [{ id: "trader_market_view", tier: "primary", intent_category: "market_pulse", label: "What is the market view today?",
            query: "What is the market view today?", outcome: "Direction, breadth, volatility, key levels", badge: null }] }
        : { mode: "advisor", prompts: [{ id: "advisor_call_today", tier: "primary", label: "Which clients should I call today?",
            query: "Give me my top 10 high-priority clients today.", outcome: "Top 10 high-priority clients with the recommended action for each.", badge: "Daily brief" }] });
    });
  }
  await page.goto(APP);
  return streams;
}

const OPPORTUNITY_SET = [
  "Find today's top 5 trading opportunities with entry, stop-loss and targets",
  "Which breakouts are confirmed?",
  "Which stocks have unusual volume?",
  "Is this stock a buy now?",
  "What is the entry, target and stop-loss for this stock?",
];

test.describe("MOCK — not real data: the Daily Trader home", () => {
  test("DT-1 Trader home: the owner's panel — six entry points, the lead question, Explore", async ({ page }) => {
    await setup(page, "trader");
    const panel = page.getByTestId("daily-trader");
    await expect(panel).toBeVisible(SLOW);
    await expect(panel.getByTestId("daily-eyebrow")).toContainText("Nivesh Copilot");
    await expect(panel.getByTestId("home-headline")).toHaveText("What would you like to know today?");
    await expect(panel).toContainText("Ask in plain English. Get evidence-backed insights and a clear trade plan.");
    await expect(panel.getByRole("radio")).toHaveText(TILES);
    await expect(panel.getByTestId("daily-tile-pulse")).toHaveAttribute("aria-checked", "true");
    await expect(panel.getByTestId("daily-question")).toHaveValue(LEAD.pulse);
    await expect(panel.getByTestId("daily-explore")).toHaveText("Explore this question");
    await expect(page.getByText("Try asking")).toHaveCount(0);
  });

  test("DT-2 each entry point puts its own lead question in the box", async ({ page }) => {
    await setup(page, "trader");
    for (const [key, q] of Object.entries(LEAD)) {
      await page.getByTestId(`daily-tile-${key}`).click();
      await expect(page.getByTestId(`daily-tile-${key}`)).toHaveAttribute("aria-checked", "true");
      await expect(page.getByTestId("daily-question")).toHaveValue(q);
    }
    await expect(page.locator('[data-testid^="daily-tile-"][aria-checked="true"]')).toHaveCount(1);
  });

  test("DT-3 'More in …' lists the entry point's other questions; 'this stock' is selected so a name replaces it", async ({ page }) => {
    await setup(page, "trader");
    await page.getByTestId("daily-tile-opportunities").click();
    const more = page.getByTestId("daily-more");
    await expect(more).toContainText("More in Find opportunities");
    await expect(more.getByTestId("daily-more-q")).toHaveText(["Which breakouts are confirmed?", "Which stocks have unusual volume?", "Is this stock a buy now?", "What is the entry, target and stop-loss for this stock?"]);
    await more.getByTestId("daily-more-q").filter({ hasText: "Is this stock a buy now?" }).click();
    const box = page.getByTestId("daily-question");
    await expect(box).toHaveValue("Is this stock a buy now?");
    const sel = await box.evaluate((el: HTMLTextAreaElement) => el.value.slice(el.selectionStart, el.selectionEnd));
    expect(sel).toBe("this stock");
  });

  test("DT-4 a typed name completes to the ticker (Tab), as in every ask box", async ({ page }) => {
    await setup(page, "trader");
    await page.getByTestId("daily-tile-opportunities").click();
    await page.getByTestId("daily-more-q").filter({ hasText: "Is this stock a buy now?" }).click();
    await page.keyboard.type("tvs mo");
    await expect(page.getByTestId("daily-complete-item")).toHaveText(/TVSMOTOR/, SLOW);
    await page.keyboard.press("Tab");
    await expect(page.getByTestId("daily-question")).toHaveValue("Is TVSMOTOR a buy now?");
  });

  test("DT-5 Explore asks the Copilot the question in the box, as a trader", async ({ page }) => {
    const streams = await setup(page, "trader");
    await page.getByTestId("daily-tile-fno").click();
    await page.getByTestId("daily-explore").click();
    await expect.poll(() => streams.length, SLOW).toBe(1);
    expect(streams[0]).toMatchObject({ message: LEAD.fno, persona: "trader" });
    await expect(page.getByText("MOCK answer.").first()).toBeVisible(SLOW);
  });

  test("DT-6 Investor mode keeps its home: no Daily Trader panel, the starter questions stay", async ({ page }) => {
    await setup(page, "investor");
    await expect(page.getByTestId("copilot-home")).toBeVisible(SLOW);
    await expect(page.getByTestId("daily-trader")).toHaveCount(0);
    await expect(page.getByText("Try asking")).toBeVisible();
  });

  test("DT-7 390 px: two columns of entry points, no sideways scroll", async ({ page }) => {
    await setup(page, "trader", 390);
    await expect(page.getByTestId("daily-trader")).toBeVisible(SLOW);
    const a = await page.getByTestId("daily-tile-pulse").boundingBox();
    const b = await page.getByTestId("daily-tile-opportunities").boundingBox();
    expect(Math.abs(a!.y - b!.y)).toBeLessThan(2);
    expect(b!.x).toBeGreaterThan(a!.x + a!.width - 1);
    expect(await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)).toBeLessThanOrEqual(0);
  });

  test("DT-8 Trader mode never shows the client-book list: the ask box asks for Trader mode and lists the trader questions", async ({ page }) => {
    const urls: string[] = [];
    await setup(page, "trader", 1280, urls);
    await expect(page.getByTestId("daily-trader")).toBeVisible(SLOW);
    await page.getByTestId("composer-input").click();
    await expect(page.getByText("What is the market view today?", { exact: true })).toBeVisible(SLOW);
    await expect(page.getByText("YOUR DAILY TRADING QUESTIONS")).toBeVisible();
    await expect(page.getByText("Which clients should I call today?")).toHaveCount(0);
    await expect(page.getByText("RANKED FOR YOUR CLIENT BOOK")).toHaveCount(0);
    expect(urls.length).toBeGreaterThan(0);
    expect(urls.every((u) => u.includes("mode=trader"))).toBe(true);
  });

  test("DT-9 the question sets stay after a question is asked: a strip under the answer, one set per entry point", async ({ page }) => {
    const streams = await setup(page, "trader");
    await page.getByTestId("daily-explore").click();
    await expect.poll(() => streams.length, SLOW).toBe(1);
    const bar = page.getByTestId("daily-bar");
    await expect(bar).toBeVisible(SLOW);
    await expect(page.getByTestId("daily-trader")).toHaveCount(0);          // the empty-state panel itself is gone
    await expect(bar.getByRole("button")).toHaveText(TILES);
    await expect(page.getByTestId("daily-bar-questions")).toHaveCount(0);
    await bar.getByTestId("daily-bar-opportunities").click();
    await expect(bar.getByTestId("daily-bar-opportunities")).toHaveAttribute("aria-expanded", "true");
    await expect(page.getByTestId("daily-bar-q")).toHaveText(OPPORTUNITY_SET);
    await page.getByTestId("daily-bar-q").filter({ hasText: "Which breakouts are confirmed?" }).click();
    await expect.poll(() => streams.length, SLOW).toBe(2);
    expect(streams[1]).toMatchObject({ message: "Which breakouts are confirmed?", persona: "trader" });
    await expect(page.getByTestId("daily-bar-questions")).toHaveCount(0);   // asking closes the list; the strip stays
    await expect(bar).toBeVisible();
  });

  test("DT-10 Investor mode has no Daily Trader strip in a thread", async ({ page }) => {
    const streams = await setup(page, "investor");
    await page.getByTestId("composer-input").fill("What is the market view today?");
    await page.getByTestId("composer-input").press("Enter");
    await expect.poll(() => streams.length, SLOW).toBe(1);
    await expect(page.getByText("MOCK answer.").first()).toBeVisible(SLOW);
    await expect(page.getByTestId("daily-bar")).toHaveCount(0);
  });

  test("DT-11 390 px: the strip scrolls inside itself, the page does not", async ({ page }) => {
    const streams = await setup(page, "trader", 390);
    await page.getByTestId("daily-explore").click();
    await expect.poll(() => streams.length, SLOW).toBe(1);
    await expect(page.getByTestId("daily-bar")).toBeVisible(SLOW);
    await page.getByTestId("daily-bar-fno").scrollIntoViewIfNeeded();
    await page.getByTestId("daily-bar-fno").click();
    await expect(page.getByTestId("daily-bar-q").first()).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)).toBeLessThanOrEqual(0);
  });
});
