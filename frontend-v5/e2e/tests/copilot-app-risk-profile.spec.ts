/**
 * One-screen Copilot app (/v5/app) — "How much should I risk?" with and without a saved risk profile, and what the chat says when
 * the assistant is out of capacity (owner, 31 Oct 2026). RP-1 … RP-4 of test_reports/copilot_batch2_20261031.md.
 *
 * Payloads: `e2e/fixtures/risk-profile.mock.json` — MOCK, not real data: the real builder over the unit tests' invented inputs
 * (backend/tests/test_copilot_visual.py, PS-*), and the usage-limit message from the real classifier (services/chat_errors.py)
 * on the gateway's real error text. Every expected value is computed from the payload itself. Mocked APIs, production build
 * (pw.copilot-app.config.ts).
 */
import { test, expect, type Page, type Route } from "@playwright/test";
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";
import { mockApi, mockSingleRoute } from "../helpers/api-mock";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const FIX = path.join(__dirname, "..", "fixtures");
type Payload = Record<string, any>;
const DOC = JSON.parse(fs.readFileSync(path.join(FIX, "risk-profile.mock.json"), "utf-8"));
const PAYLOADS: Record<string, Payload> = DOC.payloads;
const LIMIT_MESSAGE: string = DOC.usage_limit_message;
const APP = "/v5/app";
const SLOW = { timeout: 15_000 };

const json = (route: Route, body: unknown, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
const sse = (frames: Array<Record<string, unknown>>) => frames.map((f) => `data: ${JSON.stringify(f)}\n\n`).join("");
const ANSWER = "MOCK answer text, written from the payload's facts.";

async function chat(page: Page, p: Payload | null, errorText?: string) {
  const saved: unknown[] = [];
  const w = p ? { widget_type: "visual_answer", title: p.title, data: p,
    freshness: { state: "end_of_day", last_updated: "2026-10-30T04:50:00+05:30", source: ["NIDP"] }, agent: { id: "market_analyst", confidence: null } } : null;
  await page.route("**/api/chat/sessions", (r) => r.request().method() === "POST" ? json(r, { session_id: "new1", id: "new1" }) : json(r, []));
  await page.route("**/api/chat/messages*", (r) => json(r, saved));
  await page.route("**/api/chat/suggest-queries*", (r) => json(r, { suggestions: [] }));
  await page.route("**/api/chat/instrument-search*", (r) => json(r, { stocks: [], funds: [] }));
  await page.route("**/api/chat/stream", (r) => {
    const body = r.request().postDataJSON() as { message: string };
    const head = [{ type: "meta", session_id: "new1", ai_msg_id: "a1", user_msg_id: "u1" }, { type: "route", agent: "market_analyst", confidence: 0.9 }];
    if (errorText) {            // the gateway's usage limit: the dashboard was already sent, then the model fails
      return r.fulfill({ status: 200, contentType: "text/event-stream", body: sse([...head, ...(w ? [{ type: "widget", ...w }] : []), { type: "error", content: errorText }]) });
    }
    saved.push({ message_id: "u1", session_id: "new1", role: "user", content: body.message, created_at: "2026-10-30T04:50:00+00:00" },
      { message_id: "a1", session_id: "new1", role: "assistant", content: ANSWER, created_at: "2026-10-30T04:50:05+00:00", widget: w });
    return r.fulfill({ status: 200, contentType: "text/event-stream", body: sse([...head, { type: "widget", ...w }, { type: "token", content: ANSWER }, { type: "done", content: ANSWER, follow_ups: [] }]) });
  });
}

async function ask(page: Page, p: Payload | null, errorText?: string) {
  await mockApi(page, "populated");
  await mockSingleRoute(page, "**/api/markets/home", "markets-home.json");
  await chat(page, p, errorText);
  await page.goto(APP);
  await page.getByTestId("composer-input").fill("How much should I risk?");
  await page.getByTestId("composer-input").press("Enter");
  if (!errorText) await expect(page.getByTestId("thread-turn").first()).toHaveAttribute("data-state", "saved", SLOW);
  return page.getByTestId("va").first();
}

test.describe("How much should I risk? and the usage-limit message (MOCK payloads from the real builder)", () => {
  test("RP-1 with no saved profile: no stale warning, the defaults say they are defaults, and the ask comes first", async ({ page }) => {
    const p = PAYLOADS.none;
    const va = await ask(page, p);
    await expect(va).toBeVisible(SLOW);
    expect(p.data_quality.stale).toBe(false);
    const text = await va.innerText();
    expect(text.toLowerCase()).not.toContain("unknown date");
    expect(text.toLowerCase()).not.toContain("older than");
    const blocks = va.getByTestId("va-block");
    await expect(blocks.nth(0)).toHaveAttribute("data-type", "notice");                    // the ask comes before the figures
    await expect(blocks.nth(1)).toHaveAttribute("data-type", "kpis");
    const kpiBlock = va.locator('[data-testid="va-block"][data-block-id="limits"]');
    await expect(kpiBlock.getByTestId("va-block-title")).toHaveText(p.blocks.find((b: any) => b.id === "limits").title);
    await expect(kpiBlock.getByTestId("va-block-note")).toHaveText(p.blocks.find((b: any) => b.id === "limits").note);
    await expect(va.getByTestId("va-headline")).toContainText("You have no saved risk profile");
    const notice = va.getByTestId("va-notice").filter({ hasText: "have not set a risk profile" });
    await expect(notice.getByTestId("va-notice-action-set_risk_profile")).toHaveText("Set up your risk profile");
  });

  test("RP-2 the action opens the Risk Desk's limits and profile", async ({ page }) => {
    const va = await ask(page, PAYLOADS.none);
    await expect(va).toBeVisible(SLOW);
    await va.getByTestId("va-notice-action-set_risk_profile").click();
    await expect(page).toHaveURL(/\/app\/trader\/desk\?tab=risk&view=limits/);
  });

  test("RP-3 a saved profile is not stale, however old: its title and the date it was set, and no ask", async ({ page }) => {
    const p = PAYLOADS.saved;
    const va = await ask(page, p);
    await expect(va).toBeVisible(SLOW);
    const limits = p.blocks.find((b: any) => b.id === "limits");
    const frame = va.locator('[data-testid="va-block"][data-block-id="limits"]');
    await expect(frame.getByTestId("va-block-title")).toHaveText("Your risk limits");
    await expect(frame.getByTestId("va-block-note")).toHaveText(limits.note);
    expect(limits.note).toContain("set 15 Jul 2026");
    await expect(va.getByTestId("va-notice-action-set_risk_profile")).toHaveCount(0);
    expect((await va.innerText()).toLowerCase()).not.toContain("older than");
  });

  test("RP-4 when the assistant is out of capacity the answer says so, with the reset time, and keeps the dashboard", async ({ page }) => {
    const va = await ask(page, PAYLOADS.saved, LIMIT_MESSAGE);
    const banner = page.getByTestId("answer-banner-danger");
    await expect(banner).toContainText("usage limit", SLOW);
    await expect(banner).toContainText("10:50 AM IST");
    await expect(banner).not.toContainText("trouble connecting");
    await expect(banner).not.toContainText("502");
    await expect(va).toBeVisible(SLOW);                                              // the figures arrived before the failure
  });
});
