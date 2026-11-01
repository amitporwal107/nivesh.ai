/**
 * Copilot app (/v5/app) — the `screen_stocks` chat answer and "Open in Screener"
 * (docs/plans_20261031/SCREENER_WATCHLIST_PLAN.md slice W4; cases in test_reports/screener_watchlist_TESTCASES.md, VS-1 … VS-8).
 *
 * The chat payload is a REAL capture: the new builder run read-only over staging's data on 1 Nov 2026
 * (e2e/fixtures/contract-visual-answer.json → payloads.screen_stocks; real stocks, data as of 2026-10-30). Everything around it is a
 * mock (the chat stream, /api/screeners/run, /api/watchlists), so the titles say MOCK where a mock is what proves the case.
 * Mocked APIs, production build (pw.copilot-app.config.ts).
 */
import { test, expect, type Locator, type Page, type Route } from "@playwright/test";
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

interface Call { method: string; path: string; body: unknown }
interface ListDoc { watchlist_id: string; name: string; symbol_count: number }
interface Wl {
  lists?: ListDoc[];
  bulk?: (symbols: string[]) => { status?: number; body: unknown };
  create?: (name: string) => { status?: number; body: unknown } | undefined;
  delayMs?: number;
}
const summary = (l: ListDoc) => ({ ...l, is_starter: false, seeded_from: null, created_at: "2026-11-01T00:00:00+00:00", updated_at: "2026-11-01T00:00:00+00:00" });

/** POST /api/screeners/run (3 made-up stocks, the real route's shape; bodies recorded) and a small /api/watchlists store that records every write. */
async function screener(page: Page, wl: Wl = {}) {
  const runs: unknown[] = [];
  const calls: Call[] = [];
  const lists = [...(wl.lists ?? [])];
  const body = JSON.parse(JSON.stringify(EX.matches));
  await page.route("**/api/screeners/run", (r) => { runs.push(r.request().postDataJSON()); return json(r, body); });
  await page.route("**/api/screeners", (r) => json(r, []));
  await page.route("**/api/watchlists**", async (route) => {
    const req = route.request();
    const url = new URL(req.url());
    const data = req.method() === "POST" ? req.postDataJSON() : null;
    if (req.method() !== "GET") calls.push({ method: req.method(), path: url.pathname, body: data });
    if (wl.delayMs && req.method() === "POST") await new Promise((r) => setTimeout(r, wl.delayMs));
    if (url.pathname.endsWith("/symbols/bulk")) {
      const id = url.pathname.split("/").slice(-3)[0];
      const symbols = (data as { symbols: string[] }).symbols;
      const custom = wl.bulk?.(symbols);
      if (custom) return json(route, custom.body, custom.status ?? 200);
      const l = lists.find((x) => x.watchlist_id === id);
      if (l) l.symbol_count += symbols.length;
      return json(route, { added: symbols.map((x) => ({ symbol: x, company_name: `${x} Limited` })), already: [], refused: [], watchlist: summary(l ?? { watchlist_id: id, name: "x", symbol_count: symbols.length }) });
    }
    if (url.pathname.endsWith("/api/watchlists") && req.method() === "POST") {
      const name = (data as { name: string }).name;
      const custom = wl.create?.(name);
      if (custom) return json(route, custom.body, custom.status ?? 200);
      const made = { watchlist_id: `wl_new${lists.length + 1}`, name, symbol_count: 0 };
      lists.push(made);
      return json(route, summary(made));
    }
    if (url.pathname.endsWith("/api/watchlists")) return json(route, { lists: lists.map(summary), limits: { max_lists: 20, max_symbols: 100 }, starter_pending: false });
    return json(route, { ...summary(lists[0] ?? { watchlist_id: "x", name: "x", symbol_count: 0 }), stocks: [], quotes: { live: 0, stored: 0, none: 0 } });
  });
  return { runs, calls };
}

async function traderMode(page: Page) {
  await page.addInitScript(() => {
    try { window.localStorage.setItem("nivesh.copilot", JSON.stringify({ state: { mode: "trader" }, version: 0 })); } catch { /* blocked storage */ }
  });
}

async function ask(page: Page, payload: Payload = REAL, wl: Wl = {}) {
  await mockApi(page, "populated");
  await mockSingleRoute(page, "**/api/markets/home", "markets-home.json");
  await chat(page, payload);
  const { runs, calls } = await screener(page, wl);
  await page.goto(APP);
  await page.getByTestId("composer-input").fill(ASK);
  await page.getByTestId("composer-input").press("Enter");
  await expect(page.getByTestId("thread-turn").first()).toHaveAttribute("data-state", "saved", SLOW);
  const va = page.getByTestId("va").first();
  await expect(va).toBeVisible(SLOW);
  return { va, runs, calls };
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
    const { runs } = await screener(page);
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

  // ── W5: the confirmation card (the chat never writes; the button does) ──
  const CARD = REAL.blocks.find((b: any) => b.type === "watchlist_add");
  const card = (va: Locator) => va.getByTestId("va-add");
  const LIST: ListDoc = { watchlist_id: "wl_a", name: "My IT ideas", symbol_count: 4 };

  test("VS-9 the card comes last, names what would be added, and seeing it or choosing a list writes nothing", async ({ page }) => {
    const { va, calls } = await ask(page, REAL, { lists: [LIST] });
    expect(REAL.blocks[REAL.blocks.length - 1].type).toBe("watchlist_add");
    await expect(va.locator('[data-testid="va-block"][data-type="watchlist_add"]')).toHaveCount(1);
    await expect(card(va)).toBeVisible();
    const n = CARD.symbols.length;
    await expect(page.getByTestId("va-add-count")).toHaveText(`${n} stocks: ${CARD.symbols.slice(0, 4).join(", ")} and ${n - 4} more`);
    await expect(va).toContainText("Nothing is added until you press the button");
    await expect(page.getByTestId("va-add-confirm")).toBeDisabled();
    await page.getByTestId("va-add-list").selectOption("wl_a");
    await expect(page.getByTestId("va-add-confirm")).toBeEnabled();
    await expect(page.getByTestId("va-add-confirm")).toHaveText(`Add ${n} stocks`);
    expect(calls).toEqual([]);                                                              // not one write call so far
  });

  test("VS-10 pressing adds the card's stocks, in order, in one call; the result replaces the form", async ({ page }) => {
    const { va, calls } = await ask(page, REAL, { lists: [LIST] });
    await page.getByTestId("va-add-list").selectOption("wl_a");
    await page.getByTestId("va-add-confirm").click();
    await expect(page.getByTestId("va-add-added")).toHaveText(`Added ${CARD.symbols.length}`);
    expect(calls).toEqual([{ method: "POST", path: "/api/watchlists/wl_a/symbols/bulk", body: { symbols: CARD.symbols } }]);
    await expect(page.getByTestId("va-add-result")).toContainText("My IT ideas");
    await expect(page.getByTestId("va-add-confirm")).toHaveCount(0);                        // done: no second press by accident
    await page.getByTestId("va-add-open").click();
    await expect(page).toHaveURL(/\/v5\/app\/page\/watchlist\?wl=my-lists$/);
  });

  test("VS-11 a new list: made first with a default name, then one add; a taken name adds nothing", async ({ page }) => {
    const { calls } = await ask(page, REAL, { create: (name) => (name === "Taken" ? { status: 409, body: { detail: "You already have a list called “Taken”." } } : undefined) });
    await expect(page.getByTestId("va-add-list")).toHaveValue("__new__");
    await expect(page.getByTestId("va-add-name")).toHaveValue("Screen · Large cap · ROE over 20 · 2026-10-30");
    await page.getByTestId("va-add-name").fill("Taken");
    await page.getByTestId("va-add-confirm").click();
    await expect(page.getByTestId("va-add-error")).toContainText("You already have a list called “Taken”.");
    expect(calls.map((c) => c.path)).toEqual(["/api/watchlists"]);
    await page.getByTestId("va-add-name").fill("Quality large caps");
    await page.getByTestId("va-add-confirm").click();
    await expect(page.getByTestId("va-add-added")).toHaveText(`Added ${CARD.symbols.length}`);
    expect(calls.map((c) => [c.method, c.path])).toEqual([["POST", "/api/watchlists"], ["POST", "/api/watchlists"], ["POST", "/api/watchlists/wl_new1/symbols/bulk"]]);
  });

  test("VS-12 the server's own refusal is shown (an advisor viewing a client; the instrument list down) and nothing claims success", async ({ page }) => {
    for (const [status, detail] of [
      [403, "You are viewing a client's account, so their lists cannot be changed from here. Switch back to your own account to change your lists."],
      [503, "The instrument list could not be checked just now, so nothing was added. Please try again."],
    ] as const) {
      const { calls } = await ask(page, REAL, { lists: [LIST], bulk: () => ({ status, body: { detail } }) });
      await page.getByTestId("va-add-list").selectOption("wl_a");
      await page.getByTestId("va-add-confirm").click();
      await expect(page.getByTestId("va-add-error")).toContainText(detail.slice(0, 45));
      await expect(page.getByTestId("va-add-added")).toHaveCount(0);
      await expect(page.getByTestId("va-add-confirm")).toBeEnabled();                       // can try again
      expect(calls).toHaveLength(1);
      await page.unrouteAll({ behavior: "ignoreErrors" });
    }
  });

  test("VS-13 a double press adds once", async ({ page }) => {
    const { calls } = await ask(page, REAL, { lists: [LIST], delayMs: 600 });
    await page.getByTestId("va-add-list").selectOption("wl_a");
    const btn = page.getByTestId("va-add-confirm");
    await btn.click();
    await expect(btn).toBeDisabled();
    await btn.click({ force: true, timeout: 500 }).catch(() => undefined);
    await expect(page.getByTestId("va-add-added")).toBeVisible();
    expect(calls).toHaveLength(1);
  });

  test("VS-14 more matches than a list holds: the card says it carries the first 100", async ({ page }) => {
    const many = JSON.parse(JSON.stringify(REAL));
    const c = many.blocks.find((b: any) => b.type === "watchlist_add");
    c.symbols = Array.from({ length: 100 }, (_, i) => `SYM${i}`);
    c.matched = 150;
    await ask(page, many, { lists: [LIST] });
    await expect(page.getByTestId("va-add-first100")).toContainText("150 stocks matched. A list holds 100, so the first 100 (largest by market cap) are selected.");
    await expect(page.getByTestId("va-add-count")).toHaveText("100 stocks: SYM0, SYM1, SYM2, SYM3 and 96 more");
  });

  test("VS-15 a forged card (a symbol that is not a symbol) is not drawn, and the rest of the answer still reads", async ({ page }) => {
    const forged = JSON.parse(JSON.stringify(REAL));
    forged.blocks.find((b: any) => b.type === "watchlist_add").symbols = ["TCS", "<img src=x onerror=alert(1)>"];
    const { va, calls } = await ask(page, forged, { lists: [LIST] });
    await expect(va.getByTestId("va-block-bad")).toBeVisible();
    await expect(va.getByTestId("va-add")).toHaveCount(0);
    await expect(va.getByTestId("va-ranked-row").first()).toBeVisible();
    expect(calls).toEqual([]);
  });

  test("VS-16 phone 390px: the card stays inside the screen and its button is tall enough", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 900 });
    await ask(page, REAL, { lists: [LIST] });
    await page.getByTestId("va-add-list").selectOption("wl_a");
    const box = await page.getByTestId("va-add-confirm").boundingBox();
    expect(box!.height).toBeGreaterThanOrEqual(44);
    const c = await page.getByTestId("va-add").boundingBox();
    expect(c!.x).toBeGreaterThanOrEqual(0);
    expect(c!.x + c!.width).toBeLessThanOrEqual(391);
    const wide = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    expect(wide).toBeLessThanOrEqual(1);
  });
});
