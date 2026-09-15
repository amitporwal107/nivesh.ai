/**
 * Copilot Sprint 1 — C1 reveal pacing + skip, C2 agent ribbon / live steps /
 * follow-ups, C5 shared widget list (dock), C8 Stop, C11 plain-words copy,
 * A1 friendly error state, A2 phone header + login layout.
 *
 * Mocked UI tests against the local Vite dev server (see playwright.config.ts).
 * TC-2 and TC-4 need a stream that arrives over TIME (route.fulfill delivers a
 * body all at once), so they run against a tiny local SSE server and the
 * /api/chat/stream request is continued to it.
 */
import { test, expect } from "@playwright/test";
import http from "node:http";
import type { AddressInfo } from "node:net";
import { mockApi } from "../helpers/api-mock";

const SID = "sess_sprint1";
const sse = (frames: unknown[]) => frames.map((f) => `data: ${JSON.stringify(f)}\n\n`).join("");

const LONG_TEXT = Array.from({ length: 12 }, (_, i) =>
  `Sentence ${i + 1}: your two flexi-cap funds share ninety-seven percent of their holdings, so you pay two fees for one portfolio.`,
).join(" ") + " Final sentence: exit the duplicate fund first.";

const FOLLOW_UPS = ["Which fund should I exit first?", "How much tax would that trigger?", "Show me the overlap pairs"];

const RISK_WIDGET = {
  hero: { title: "Overall risk rating", rating: "Moderately high", tone: "warm", profile: "Moderately Aggressive" },
  kpis: [{ label: "Volatility", value: "14.2%" }, { label: "Max drawdown", value: "32.4%" }],
  caveat: "Educational, not investment advice.",
};

/** Chat endpoints: create session, list sessions, history for SID. */
async function mockChat(page: import("@playwright/test").Page, history: unknown[]) {
  await page.route("**/api/chat/sessions", (route) =>
    route.request().method() === "POST"
      ? route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ session_id: SID }) })
      : route.fulfill({ status: 200, contentType: "application/json", body: "[]" }),
  );
  await page.route("**/api/chat/messages*", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(history) }),
  );
}

// ── a real SSE server for the timing-sensitive cases ─────────────────────────
let server: http.Server;
let serverUrl = "";
test.beforeAll(async () => {
  server = http.createServer((req, res) => {
    res.writeHead(200, { "Content-Type": "text/event-stream", "Cache-Control": "no-cache", "Access-Control-Allow-Origin": "*" });
    const write = (f: unknown) => res.write(`data: ${JSON.stringify(f)}\n\n`);
    if (req.url?.startsWith("/slow-steps")) {
      write({ type: "meta", session_id: SID });
      write({ type: "route", agent: "risk_advisor", confidence: 0.92 });
      write({ type: "thinking", tool: "get_portfolio_holdings", status: "start" });
      setTimeout(() => write({ type: "thinking", tool: "get_portfolio_holdings", status: "end" }), 400);
      setTimeout(() => write({ type: "thinking", tool: "risk", status: "start" }), 500);
      setTimeout(() => write({ type: "thinking", tool: "risk", status: "end" }), 900);
      setTimeout(() => { write({ type: "token", content: "Your risk is driven by two small-cap funds." }); }, 1100);
      setTimeout(() => { write({ type: "done", follow_ups: FOLLOW_UPS }); res.end(); }, 1300);
    } else if (req.url?.startsWith("/stall")) {
      write({ type: "meta", session_id: SID });
      write({ type: "token", content: "Partial answer before the stall. " });
      // never finishes on its own — the test presses Stop
      setTimeout(() => { try { res.end(); } catch { /* closed */ } }, 15000);
    } else {
      write({ type: "done" }); res.end();
    }
  });
  await new Promise<void>((r) => server.listen(0, "127.0.0.1", () => r()));
  serverUrl = `http://127.0.0.1:${(server.address() as AddressInfo).port}`;
});
test.afterAll(async () => { await new Promise<void>((r) => server.close(() => r())); });

// ── C2 / C1 / C8 on the chat page ────────────────────────────────────────────
test.describe("Chat page — stream frames become UI", () => {
  test("TC-1 route → agent ribbon, done.follow_ups → chips that send", async ({ page }) => {
    await mockApi(page, "populated");
    const history = [{ id: "m1", role: "user", content: "How risky is my portfolio?" }, { id: "m2", role: "assistant", content: "Your risk is driven by two small-cap funds." }];
    await mockChat(page, history);
    const streamBodies: string[] = [];
    await page.route("**/api/chat/stream", (route) => {
      streamBodies.push(route.request().postData() ?? "");
      return route.fulfill({
        status: 200, contentType: "text/event-stream",
        body: sse([{ type: "meta", session_id: SID }, { type: "route", agent: "risk_advisor", confidence: 0.92 }, { type: "token", content: "Your risk is driven by two small-cap funds." }, { type: "done", follow_ups: FOLLOW_UPS }]),
      });
    });
    await page.goto("/v5/chat");
    await page.getByLabel("Ask the copilot").fill("How risky is my portfolio?");
    await page.keyboard.press("Enter");

    await expect(page.getByTestId("agent-ribbon").first()).toContainText("Risk Advisor", { timeout: 10_000 });
    const chips = page.getByTestId("follow-ups").getByRole("button");
    await expect(chips).toHaveCount(3, { timeout: 10_000 });
    await expect(chips.nth(0)).toHaveText(/Which fund should I exit first\?/);

    await chips.nth(1).click();
    await expect.poll(() => streamBodies.length, { timeout: 5_000 }).toBe(2);
    expect(streamBodies[1]).toContain("How much tax would that trigger?");
  });

  test("TC-2 thinking frames render as a live step list before the text", async ({ page }) => {
    await mockApi(page, "populated");
    // Persisted copy of the answer: once the stream ends the page swaps the live
    // bubble for the refetched thread, so history must carry the final message.
    await mockChat(page, [{ id: "m1", role: "user", content: "How risky is my portfolio?" }, { id: "m2", role: "assistant", content: "Your risk is driven by two small-cap funds." }]);
    await page.route("**/api/chat/stream", (route) => route.continue({ url: `${serverUrl}/slow-steps` }));
    await page.goto("/v5/chat");
    await page.getByLabel("Ask the copilot").fill("How risky is my portfolio?");
    await page.keyboard.press("Enter");

    const steps = page.getByTestId("thinking-steps");
    await expect(steps).toBeVisible({ timeout: 5_000 });
    await expect(steps).toContainText("Reading your holdings");
    await expect(steps.locator("li").nth(1)).toContainText("Scoring risk", { timeout: 3_000 });
    // then the answer arrives and replaces the steps (live bubble, then the persisted copy)
    await expect(page.locator("body")).toContainText("two small-cap funds", { timeout: 5_000 });
    await expect(steps).toBeHidden({ timeout: 5_000 });
  });

  test("TC-3 a 700-char answer is fully visible within 2.5 s (was ~10 s)", async ({ page }) => {
    await mockApi(page, "populated");
    await mockChat(page, [{ id: "m1", role: "user", content: "q" }, { id: "m2", role: "assistant", content: LONG_TEXT }]);
    await page.route("**/api/chat/stream", (route) =>
      route.fulfill({ status: 200, contentType: "text/event-stream", body: sse([{ type: "meta", session_id: SID }, ...LONG_TEXT.split(/(?<=\s)/).map((w) => ({ type: "token", content: w })), { type: "done" }]) }),
    );
    await page.goto("/v5/chat");
    await page.getByLabel("Ask the copilot").fill("Why is my score 74?");
    const t0 = Date.now();
    await page.keyboard.press("Enter");
    await expect(page.locator("main, body").first()).toContainText("Final sentence: exit the duplicate fund first.", { timeout: 4_000 });
    const elapsed = Date.now() - t0;
    console.log(`TC-3 full answer visible after ${elapsed} ms`);
    expect(elapsed).toBeLessThan(2_500);
  });

  test("TC-4 Stop aborts a stalled stream and keeps the partial answer", async ({ page }) => {
    await mockApi(page, "populated");
    await mockChat(page, [{ id: "m1", role: "user", content: "Why is my score 74?" }]);
    await page.route("**/api/chat/stream", (route) => route.continue({ url: `${serverUrl}/stall` }));
    await page.goto("/v5/chat");
    await page.getByLabel("Ask the copilot").fill("Why is my score 74?");
    await page.keyboard.press("Enter");

    const stop = page.getByTestId("chat-stop");
    await expect(stop).toBeVisible({ timeout: 5_000 });
    await expect(page.getByTestId("streaming-answer")).toContainText("Partial answer before the stall.", { timeout: 5_000 });
    const t0 = Date.now();
    await stop.click();
    await expect(page.getByTestId("chat-send")).toBeVisible({ timeout: 1_500 });
    console.log(`TC-4 Send back after ${Date.now() - t0} ms`);
    const local = page.getByTestId("local-answer");
    await expect(local).toContainText("Partial answer before the stall.");
    await expect(local).toContainText("Stopped");
    await expect(local.getByRole("button", { name: "Try again" })).toBeVisible();
    await expect(page.getByLabel("Ask the copilot")).toBeEnabled();
  });

  test("TC-6 no internal 'NIDP' copy on the chat landing or sidebar", async ({ page }) => {
    await mockApi(page, "populated");
    await mockChat(page, []);
    await page.goto("/v5/chat");
    await expect(page.getByTestId("copilot-review")).toBeVisible();
    await expect(page.locator("body")).not.toContainText("NIDP");
    await expect(page.getByText("LIVE DATA")).toBeVisible();
  });
});

// ── C5 in the dock ───────────────────────────────────────────────────────────
test.describe("Copilot dock — shared widget list", () => {
  test("TC-5 a risk_assessment widget answer renders in the dock (no blank turn)", async ({ page }) => {
    await mockApi(page, "populated");
    await mockChat(page, [
      { id: "m1", role: "user", content: "How risky is this?" },
      { id: "m2", role: "assistant", content: "", widget: { widget_type: "risk_assessment", data: RISK_WIDGET } },
    ]);
    await page.route("**/api/chat/stream", (route) =>
      route.fulfill({ status: 200, contentType: "text/event-stream", body: sse([{ type: "meta", session_id: SID }, { type: "widget", widget_type: "risk_assessment", data: RISK_WIDGET }, { type: "done" }]) }),
    );
    await page.goto("/v5/risk");
    await page.getByRole("button", { name: "Open AI copilot" }).click();
    const dock = page.getByRole("dialog", { name: "AI copilot" });
    await dock.getByLabel(/Ask the copilot/).fill("How risky is this?");
    await page.keyboard.press("Enter");
    await expect(dock).toContainText("Overall risk rating", { timeout: 10_000 });
    await expect(dock).toContainText("Moderately high");
  });
});

// ── A1 error copy ────────────────────────────────────────────────────────────
test.describe("Error state", () => {
  test("TC-7 contract drift shows a plain message; the raw dump is behind Details", async ({ page }) => {
    await mockApi(page, "populated"); // markets.home gets {} → Zod contract failure
    await page.goto("/v5/markets");
    const alert = page.getByRole("alert");
    await expect(alert).toBeVisible({ timeout: 10_000 });
    await expect(alert).toContainText("We received data in a shape we didn't expect");
    await expect(alert.getByRole("button", { name: "Try again" })).toBeVisible();
    const details = alert.getByTestId("error-details");
    await expect(details.locator("pre")).toBeHidden();
    await details.locator("summary").click();
    await expect(details.locator("pre")).toBeVisible();
    await expect(details.locator("pre")).toContainText("invalid_type");
  });
});

// ── A2 phone layouts (public pages) ──────────────────────────────────────────
test.describe("Phone layouts", () => {
  test.use({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true });

  test("TC-8 homepage header: brand, Sign in and CTA stay on one line, no overflow", async ({ page }) => {
    await mockApi(page, "populated");
    await page.goto("/v5/");
    const brand = page.locator(".nvx-home .nav-inner .nvx-brand");
    const signin = page.locator(".nvx-home .nav-right .signin");
    const cta = page.locator(".nvx-home .nav-right .btn-primary");
    await expect(brand).toBeVisible();
    for (const el of [brand, cta]) {
      const box = await el.boundingBox();
      expect(box, "element has a box").not.toBeNull();
      expect(box!.height, "one line tall").toBeLessThanOrEqual(44);
      expect(box!.x + box!.width, "inside the viewport").toBeLessThanOrEqual(390);
    }
    if (await signin.isVisible()) {
      const box = await signin.boundingBox();
      expect(box!.height).toBeLessThanOrEqual(30);
    }
    const scrollWidth = await page.evaluate(() => document.documentElement.scrollWidth);
    expect(scrollWidth).toBeLessThanOrEqual(390);
  });

  test("TC-9 login stacks to one column with the showcase hidden", async ({ page }) => {
    await mockApi(page, "populated");
    await page.goto("/v5/login");
    await expect(page.locator(".nvx-login .auth h2")).toBeVisible();
    // The desktop product tour (and its floating "Ask the copilot" demo pill)
    // must not render on a phone. Both elements exist in the DOM on desktop.
    await expect(page.locator(".nvx-login .stage .tour-wrap")).toHaveCount(1);
    await expect(page.locator(".nvx-login .stage .tour-wrap")).toBeHidden();
    await expect(page.locator(".cp-launch")).toBeHidden();
    const scrollWidth = await page.evaluate(() => document.documentElement.scrollWidth);
    expect(scrollWidth).toBeLessThanOrEqual(390);
    // The eyebrow text must WRAP, not overflow its box (the stage clips overflow,
    // so a bounding-box check alone would pass while the text is cut off).
    const eyebrow = page.locator(".nvx-login .stage .eyebrow");
    const box = await eyebrow.boundingBox();
    expect(box!.x + box!.width).toBeLessThanOrEqual(390);
    const overflow = await eyebrow.evaluate((el) => ({ scroll: el.scrollWidth, client: el.clientWidth }));
    expect(overflow.scroll, "eyebrow text fits its box").toBeLessThanOrEqual(overflow.client + 1);
    for (const el of await page.locator(".nvx-login .stage .lede h1, .nvx-login .stage .lede p").all()) {
      const o = await el.evaluate((n) => ({ scroll: n.scrollWidth, client: n.clientWidth, text: (n.textContent ?? "").slice(0, 30) }));
      expect(o.scroll, `"${o.text}" fits its box`).toBeLessThanOrEqual(o.client + 1);
    }
  });
});
