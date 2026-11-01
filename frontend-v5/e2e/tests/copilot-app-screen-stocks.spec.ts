/**
 * Copilot app (/v5/app) — the `screen_stocks` chat answer and "Open in Screener"
 * (docs/plans_20261031/SCREENER_WATCHLIST_PLAN.md slice W4; cases in test_reports/screener_watchlist_TESTCASES.md, VS-1 … VS-8).
 *
 * The chat payload is a REAL capture: the new builder run read-only over staging's data on 1 Nov 2026
 * (e2e/fixtures/contract-visual-answer.json → payloads.screen_stocks; real stocks, data as of 2026-10-30). Everything around it is a
 * mock (the chat stream, /api/screeners/run, /api/watchlists), so the titles say MOCK where a mock is what proves the case.
 * Mocked APIs, production build (pw.copilot-app.config.ts).
 */
import { test, expect, type Page, type Route } from "@playwright/test";
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";
import { mockApi, mockSingleRoute } from "../helpers/api-mock";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const FIX = path.join(__dirname, "..", "fixtures");
type Payload = Record<string, any>;
const REAL: Payload = JSON.parse(fs.readFileSync(path.join(FIX, "contract-visual-answer.json"), "utf-8")).payloads.screen_stocks;
const RANKED = REAL.blocks.find((b: any) => b.type === "ranked");
const EX = JSON.parse(fs.readFileSync(path.join(FIX, "screener-run-examples.json"), "utf-8"));
const APP = "/v5/app";
const SLOW = { timeout: 15_000 };
const json = (route: Route, body: unknown, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
const sse = (frames: Array<Record<string, unknown>>) => frames.map((f) => `data: ${JSON.stringify(f)}\n\n`).join("");
const ANSWER = "MOCK answer text, written from the payload's facts.";
const ASK = "Screen cheap large cap stocks with ROE over 20 and strong momentum";

async function chat(page: Page, payload: Payload) {
  const saved: unknown[] = [];
  const w = { widget_type: "visual_answer", title: payload.title, data: payload,
    freshness: { state: "end_of_day", last_updated: "2026-11-01T10:00:00+05:30", source: ["NIDP"] }, agent: { id: "market_analyst", confidence: null } };
  await page.route("**/api/chat/sessions", (r) => r.request().method() === "POST" ? json(r, { session_id: "new1", id: "new1" }) : json(r, []));
  await page.route("**/api/chat/messages*", (r) => json(r, saved));
  await page.route("**/api/chat/suggest-queries*", (r) => json(r, { suggestions: [] }));
  await page.route("**/api/chat/instrument-search*", (r) => json(r, { stocks: [], funds: [] }));
  await page.route("**/api/chat/stream", (r) => {
    const body = r.request().postDataJSON() as { message: string };
    saved.push({ message_id: "u1", session_id: "new1", role: "user", content: body.message, created_at: "2026-11-01T04:50:00+00:00" },
      { message_id: "a1", session_id: "new1", role: "assistant", content: ANSWER, created_at: "2026-11-01T04:50:05+00:00", widget: w });
    return r.fulfill({ status: 200, contentType: "text/event-stream", body: sse([
      { type: "meta", session_id: "new1", ai_msg_id: "a1", user_msg_id: "u1" }, { type: "route", agent: "market_analyst", confidence: 0.9 },
      { type: "widget", ...w }, { type: "token", content: ANSWER }, { type: "done", content: ANSWER, follow_ups: [] }]) });
  });
}

/** POST /api/screeners/run, answered with 3 made-up stocks in the real route's shape; every request body is recorded. */
async function screener(page: Page) {
  const runs: unknown[] = [];
  const body = JSON.parse(JSON.stringify(EX.matches));
  await page.route("**/api/screeners/run", (r) => { runs.push(r.request().postDataJSON()); return json(r, body); });
  await page.route("**/api/screeners", (r) => json(r, []));
  await page.route("**/api/watchlists**", (r) => json(r, { lists: [], limits: { max_lists: 20, max_symbols: 100 }, starter_pending: false }));
  return runs;
}

async function traderMode(page: Page) {
  await page.addInitScript(() => {
    try { window.localStorage.setItem("nivesh.copilot", JSON.stringify({ state: { mode: "trader" }, version: 0 })); } catch { /* blocked storage */ }
  });
}

async function ask(page: Page, payload: Payload = REAL) {
  await mockApi(page, "populated");
  await mockSingleRoute(page, "**/api/markets/home", "markets-home.json");
  await chat(page, payload);
  const runs = await screener(page);
  await page.goto(APP);
  await page.getByTestId("composer-input").fill(ASK);
  await page.getByTestId("composer-input").press("Enter");
  await expect(page.getByTestId("thread-turn").first()).toHaveAttribute("data-state", "saved", SLOW);
  const va = page.getByTestId("va").first();
  await expect(va).toBeVisible(SLOW);
  return { va, runs };
}

test.describe("Screen stocks in chat (real captured payload) and Open in Screener", () => {
  test("VS-1 the rules as understood come first, then what was not used, then the matches", async ({ page }) => {
    const { va } = await ask(page);
    const notices = va.getByTestId("va-notice");
    await expect(notices.nth(0)).toContainText("I read this as: Large cap · ROE over 20.");
    await expect(notices.nth(1)).toContainText("Not used: cheap, strong, momentum.");
    await expect(notices.nth(1)).toHaveAttribute("data-tone", "warn");
    await expect(va.getByTestId("va-block")).toHaveCount(REAL.blocks.length);
    const kpi = REAL.blocks.find((b: any) => b.type === "kpis");
    await expect(va.getByTestId("va-kpis").first()).toContainText(String(kpi.items[0].value));
    await expect(va.getByTestId("va-kpis").first()).toContainText("30 Oct");
  });

  test("VS-2 at most 25 rows, the first row is the real first match with Indian grouping, and the wording is a filter, not a pick", async ({ page }) => {
    const { va } = await ask(page);
    const rows = va.getByTestId("va-ranked-row");
    await expect(rows).toHaveCount(RANKED.rows.length);
    expect(RANKED.rows.length).toBeLessThanOrEqual(25);
    await expect(rows.first()).toContainText(RANKED.rows[0].symbol);
    await expect(rows.first()).toContainText(RANKED.rows[0].cells.mcap);
    expect(RANKED.rows[0].cells.mcap).toMatch(/^\d{1,2}(,\d{2})*,\d{3}$/);                 // 7,68,844 — Indian grouping
    await expect(va).toContainText("match your filters");
    await expect(va).toContainText("not recommendations");
    for (const word of ["top pick", "best stock", "buy these"]) await expect(va).not.toContainText(word);
  });

  test("VS-3 Investor mode: 'Open in Screener' goes to the Screener, runs the same rules once and tidies the address", async ({ page }) => {
    const { va, runs } = await ask(page);
    await va.getByTestId("va-notice-action-open_screener").click();
    await expect(page).toHaveURL(/\/v5\/app\/tool\/screener(\?|$)/);
    await expect(page.getByTestId("screener-results")).toHaveAttribute("data-state", "ready", SLOW);
    expect(runs).toEqual([{ conditions: [{ key: "roe", op: "over", value: "20" }], bucket: "large", include_funds: true }]);
    await expect(page.getByTestId("screener-rule-value").first()).toHaveValue("20");
    await expect(page.getByTestId("screener-results-query")).toContainText("ROE");
    await expect.poll(() => new URL(page.url()).searchParams.get("r")).toBeNull();            // the rules are out of the address: a refresh will not run them again
    await expect(page.getByTestId("screener-add")).toBeVisible();                              // and the Add-to-a-list bar is there
  });

  test("VS-4 Trader mode: the same action opens Market Desk › Screener", async ({ page }) => {
    await traderMode(page);
    const { va, runs } = await ask(page);
    await va.getByTestId("va-notice-action-open_screener").click();
    await expect(page).toHaveURL(/\/v5\/app\/trader\/desk\?tab=market&view=screener/);
    await expect(page.getByTestId("screener-results")).toHaveAttribute("data-state", "ready", SLOW);
    expect(runs).toHaveLength(1);
    await expect.poll(() => new URL(page.url()).searchParams.get("r")).toBeNull();
    expect(new URL(page.url()).searchParams.get("view")).toBe("screener");                     // only the rules were taken out
  });

  test("VS-5 a rule the page cannot load is filled in where possible but nothing is run (never a different screen)", async ({ page }) => {
    await mockApi(page, "populated");
    const runs = await screener(page);
    await page.goto(`${APP}/tool/screener?r=roe:over:20,nosuchmetric:over:5&b=large`);
    await expect(page.getByTestId("screen-tool-screener")).toBeVisible();
    await expect(page.getByTestId("screener-rule-value").first()).toHaveValue("20");
    await expect(page.getByTestId("screener-results")).toHaveAttribute("data-state", "idle");
    expect(runs).toEqual([]);
  });

  test("VS-6 a forged link in a payload is dropped: the action opens the Screener empty, with nothing in the address", async ({ page }) => {
    const forged = JSON.parse(JSON.stringify(REAL));
    forged.blocks[0].actions[0].query = "r=roe:over:20&x=<script>alert(1)</script>";
    const { va, runs } = await ask(page, forged);
    await va.getByTestId("va-notice-action-open_screener").click();
    await expect(page).toHaveURL(/\/v5\/app\/tool\/screener$/);
    expect(new URL(page.url()).search).toBe("");
    await expect(page.getByTestId("screener-results")).toHaveAttribute("data-state", "idle");
    expect(runs).toEqual([]);
  });

  test("VS-7 a row asks for its trade plan, as in the other ranked answers", async ({ page }) => {
    const { va } = await ask(page);
    await expect(va.getByTestId("va-ranked-row").first()).toBeVisible();
    expect(RANKED.rows[0].ask).toBe(`Trade plan for ${RANKED.rows[0].symbol}`);
  });

  test("VS-8 phone 390px: no sideways scroll for the page", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 900 });
    const { va } = await ask(page);
    await expect(va.getByTestId("va-ranked-row").first()).toBeVisible();
    const wide = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    expect(wide).toBeLessThanOrEqual(1);
  });
});
