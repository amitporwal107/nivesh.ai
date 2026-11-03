/**
 * Copilot app — the Screener's "Add to a list" bar
 * (docs/plans_20261031/SCREENER_WATCHLIST_PLAN.md slice W3; cases in test_reports/screener_watchlist_TESTCASES.md, AL-1 … AL-12).
 *
 * MOCK — not real data: every /api answer is a route mock. The run response is the real route's shape
 * (e2e/fixtures/screener-run-examples.json, made-up stocks) with generated rows; /api/watchlists is a small in-spec store that
 * records every call, so "nothing is written before the press" is asserted on the calls, not on the screen.
 * The backend's own rules (the 100 limit, idempotence, ownership, the advisor guard) are tested in backend/tests/test_watchlists.py.
 */
import { test, expect, type Page } from "@playwright/test";
import fs from "fs";
import path from "path";
import { mockApi } from "../helpers/api-mock";

const APP = "/v5/app";
const EX = JSON.parse(fs.readFileSync(path.join(process.cwd(), "e2e", "fixtures", "screener-run-examples.json"), "utf-8"));

interface Call { method: string; path: string; body: unknown }
interface ListDoc { watchlist_id: string; name: string; symbol_count: number }

const summary = (l: ListDoc) => ({ ...l, is_starter: false, seeded_from: null, created_at: "2026-10-12T00:00:00+00:00", updated_at: "2026-10-12T00:00:00+00:00" });

/** A run answer with `n` generated stocks (FX000, FX001, … largest market cap first). */
function runBody(n: number, matched = n) {
  const body = JSON.parse(JSON.stringify(EX.matches));
  body.widget.universe = Array.from({ length: n }, (_, i) => ({
    name: `Fixture ${i}`, ticker: `FX${String(i).padStart(3, "0")}`, sector: "IT", mcap: 100000 - i, pe: 10 + (i % 5), roe: null,
  }));
  body.matched = matched;
  return body;
}

interface Opts {
  lists?: ListDoc[];
  /** The reply to a bulk add (default: everything added). */
  bulk?: (symbols: string[]) => { status?: number; body: unknown };
  create?: (name: string) => { status?: number; body: unknown } | undefined;
  delayMs?: number;
}

async function setup(page: Page, n: number, opts: Opts = {}) {
  const calls: Call[] = [];
  const lists = [...(opts.lists ?? [])];
  await mockApi(page, "populated");
  await page.route("**/api/chat/sessions", (r) => r.fulfill({ status: 200, contentType: "application/json", body: "[]" }));
  await page.route("**/api/screeners", (r) => r.fulfill({ status: 200, contentType: "application/json", body: "[]" }));
  await page.route("**/api/screeners/run", (r) => r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(runBody(n, n)) }));
  await page.route("**/api/watchlists**", async (route) => {
    const req = route.request();
    const url = new URL(req.url());
    const body = req.method() === "POST" ? req.postDataJSON() : null;
    if (req.method() !== "GET") calls.push({ method: req.method(), path: url.pathname, body });
    const reply = (status: number, json: unknown) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(json) });
    if (opts.delayMs && req.method() === "POST") await new Promise((r) => setTimeout(r, opts.delayMs));
    if (url.pathname.endsWith("/symbols/bulk")) {
      const id = url.pathname.split("/").slice(-3)[0];
      const symbols = (body as { symbols: string[] }).symbols;
      const custom = opts.bulk?.(symbols);
      if (custom) return reply(custom.status ?? 200, custom.body);
      const l = lists.find((x) => x.watchlist_id === id);
      if (l) l.symbol_count += symbols.length;
      return reply(200, { added: symbols.map((s) => ({ symbol: s, company_name: `${s} Limited` })), already: [], refused: [], watchlist: summary(l ?? { watchlist_id: id, name: "x", symbol_count: symbols.length }) });
    }
    if (url.pathname.endsWith("/api/watchlists") && req.method() === "POST") {
      const name = (body as { name: string }).name;
      const custom = opts.create?.(name);
      if (custom) return reply(custom.status ?? 200, custom.body);
      const made = { watchlist_id: `wl_new${lists.length + 1}`, name, symbol_count: 0 };
      lists.push(made);
      return reply(200, summary(made));
    }
    if (url.pathname.endsWith("/api/watchlists")) {
      return reply(200, { lists: lists.map(summary), limits: { max_lists: 20, max_symbols: 100 }, starter_pending: false });
    }
    return reply(200, { ...summary(lists[0] ?? { watchlist_id: "x", name: "x", symbol_count: 0 }), stocks: [], quotes: { live: 0, stored: 0, none: 0 } });
  });
  return { calls, lists };
}

const writes = (calls: Call[]) => calls.filter((c) => c.method !== "GET");

async function runScreen(page: Page) {
  await page.goto(`${APP}/tool/screener`);
  await expect(page.getByTestId("screen-tool-screener")).toBeVisible();
  await page.getByTestId("screener-rule-value").nth(1).fill("15");
  await page.getByTestId("screener-run").click();
  await expect(page.getByTestId("screener-results")).toHaveAttribute("data-state", "ready");
}

const tick = async (page: Page, ...symbols: string[]) => { for (const s of symbols) await page.locator(`[data-testid="screener-select"][data-symbol="${s}"]`).check(); };
const bar = (page: Page) => page.getByTestId("screener-add");

test.describe("MOCK — not real data: Screener · Add to a list", () => {
  test("AL-1 / AL-2 each row has a box; the box does not open the stock; nothing is written until the button is pressed", async ({ page }) => {
    const { calls } = await setup(page, 3, { lists: [{ watchlist_id: "wl_a", name: "Tech ideas", symbol_count: 4 }] });
    await runScreen(page);
    await expect(page.getByTestId("screener-select")).toHaveCount(3);
    await expect(page.getByTestId("screener-add-count")).toHaveText("Tick the stocks you want, then choose a list.");
    await expect(page.getByTestId("screener-add-confirm")).toBeDisabled();
    await tick(page, "FX001");
    await expect(page.getByTestId("screener-stock-panel")).toHaveCount(0);                 // the box is not the row
    await expect(page.getByTestId("screener-add-count")).toHaveText("1 selected");
    await expect(page.getByTestId("screener-add-confirm")).toBeDisabled();                  // a list is still needed
    await page.getByTestId("screener-add-list").selectOption("wl_a");
    await expect(page.getByTestId("screener-add-confirm")).toBeEnabled();
    await expect(page.getByTestId("screener-add-confirm")).toHaveText("Add 1 stock");
    expect(writes(calls)).toEqual([]);                                                       // choosing wrote nothing
    await page.locator('[data-testid="screener-row"][data-symbol="FX000"]').click();       // the row still opens the stock
    await expect(page.getByTestId("screener-stock-panel")).toBeVisible();
  });

  test("AL-3 adding to an existing list: one call, the chosen stocks in table order, a result and a way to the list", async ({ page }) => {
    const { calls } = await setup(page, 3, { lists: [{ watchlist_id: "wl_a", name: "Tech ideas", symbol_count: 4 }] });
    await runScreen(page);
    await tick(page, "FX002", "FX000");                                                      // ticked out of order
    await page.getByTestId("screener-add-list").selectOption("wl_a");
    await page.getByTestId("screener-add-confirm").click();
    await expect(page.getByTestId("screener-add-added")).toHaveText("Added 2");
    expect(writes(calls)).toEqual([{ method: "POST", path: "/api/watchlists/wl_a/symbols/bulk", body: { symbols: ["FX000", "FX002"] } }]);
    await expect(page.getByTestId("screener-add-result")).toContainText("Tech ideas");
    await expect(page.getByTestId("screener-select").first()).not.toBeChecked();             // the selection is cleared
    await page.getByTestId("screener-add-open").click();
    await expect(page).toHaveURL(/\/v5\/app\/page\/watchlist\?wl=my-lists$/);
  });

  test("AL-4 a new list: made first, then one add; a name that is taken adds nothing", async ({ page }) => {
    const { calls } = await setup(page, 3, {
      create: (name) => (name === "Taken" ? { status: 409, body: { detail: "You already have a list called “Taken”." } } : undefined),
    });
    await runScreen(page);
    await tick(page, "FX000", "FX001");
    await expect(page.getByTestId("screener-add-list")).toHaveValue("__new__");              // no lists yet: a new one is the way
    await expect(page.getByTestId("screener-add-name")).toHaveValue("Screen · P/E under 15 · 2026-10-12");
    expect(((await page.getByTestId("screener-add-name").inputValue()).length)).toBeLessThanOrEqual(60);
    await page.getByTestId("screener-add-name").fill("Taken");
    await page.getByTestId("screener-add-confirm").click();
    await expect(page.getByTestId("screener-add-error")).toContainText("You already have a list called “Taken”.");
    expect(writes(calls).map((c) => c.path)).toEqual(["/api/watchlists"]);                    // the make was refused; no add followed
    await expect(page.getByTestId("screener-add-added")).toHaveCount(0);
    await page.getByTestId("screener-add-name").fill("Cheap IT");
    await page.getByTestId("screener-add-confirm").click();
    await expect(page.getByTestId("screener-add-added")).toHaveText("Added 2");
    expect(writes(calls).map((c) => [c.method, c.path])).toEqual([
      ["POST", "/api/watchlists"], ["POST", "/api/watchlists"], ["POST", "/api/watchlists/wl_new1/symbols/bulk"],
    ]);
    expect(writes(calls)[2].body).toEqual({ symbols: ["FX000", "FX001"] });
  });

  test("AL-5 'select all' on more than 100 matches takes the first 100 and says so", async ({ page }) => {
    const { calls } = await setup(page, 150, { lists: [{ watchlist_id: "wl_a", name: "Big", symbol_count: 0 }] });
    await runScreen(page);
    await expect(page.getByTestId("screener-select-all")).toHaveAttribute("aria-label", "Select the first 100 stocks");
    await page.getByTestId("screener-select-all").check();
    await expect(page.getByTestId("screener-add-count")).toHaveText("100 selected");
    await expect(page.getByTestId("screener-add-first100")).toContainText("150 stocks matched. A list holds 100, so the first 100 (largest by market cap) are selected.");
    // a 101st tick is ignored
    await page.locator('[data-testid="screener-select"][data-symbol="FX120"]').check({ force: true }).catch(() => undefined);
    await expect(page.getByTestId("screener-add-count")).toHaveText("100 selected");
    await page.getByTestId("screener-add-list").selectOption("wl_a");
    await expect(page.getByTestId("screener-add-confirm")).toHaveText("Add 100 stocks");
    await page.getByTestId("screener-add-confirm").click();
    await expect(page.getByTestId("screener-add-added")).toHaveText("Added 100");
    const sent = (writes(calls)[0].body as { symbols: string[] }).symbols;
    expect(sent).toHaveLength(100);
    expect(sent[0]).toBe("FX000");
    expect(sent[99]).toBe("FX099");
  });

  test("AL-6 / AL-7 a list with little room says so first; the answer names what was already there and what was refused", async ({ page }) => {
    await setup(page, 8, {
      lists: [{ watchlist_id: "wl_a", name: "Nearly full", symbol_count: 95 }],
      bulk: (symbols) => ({ body: {
        added: symbols.slice(0, 5).map((s) => ({ symbol: s, company_name: null })),
        already: [],
        refused: [
          { symbol: symbols[5], code: "list_full", detail: "A list holds up to 100 stocks." },
          { symbol: symbols[6], code: "not_in_instrument_list", detail: `“${symbols[6]}” is not a stock in the instrument list.` },
          { symbol: symbols[7], code: "list_full", detail: "A list holds up to 100 stocks." },
        ],
        watchlist: summary({ watchlist_id: "wl_a", name: "Nearly full", symbol_count: 100 }),
      } }),
    });
    await runScreen(page);
    await page.getByTestId("screener-select-all").check();
    await page.getByTestId("screener-add-list").selectOption("wl_a");
    await expect(page.getByTestId("screener-add-room")).toContainText("Only 5 more fit in that list. 3 of the 8 will be left out");
    await page.getByTestId("screener-add-confirm").click();
    await expect(page.getByTestId("screener-add-added")).toHaveText("Added 5");
    await expect(page.getByTestId("screener-add-refused-count")).toContainText("3 could not be added");
    await expect(page.getByTestId("screener-add-refused").locator("li")).toHaveCount(3);
    await expect(page.getByTestId("screener-add-refused")).toContainText("FX006 — “FX006” is not a stock in the instrument list.");
    await expect(page.getByTestId("screener-add-refused").locator('li[data-code="list_full"]')).toHaveCount(2);
  });

  test("AL-7b stocks that were already there are counted, not hidden", async ({ page }) => {
    await setup(page, 3, {
      lists: [{ watchlist_id: "wl_a", name: "Mine", symbol_count: 2 }],
      bulk: (symbols) => ({ body: { added: [{ symbol: symbols[2], company_name: null }], already: [symbols[0], symbols[1]], refused: [], watchlist: summary({ watchlist_id: "wl_a", name: "Mine", symbol_count: 3 }) } }),
    });
    await runScreen(page);
    await page.getByTestId("screener-select-all").check();
    await page.getByTestId("screener-add-list").selectOption("wl_a");
    await page.getByTestId("screener-add-confirm").click();
    await expect(page.getByTestId("screener-add-added")).toHaveText("Added 1");
    await expect(page.getByTestId("screener-add-already")).toContainText("2 were already there");
  });

  test("AL-8 a refusal from the server is shown in its own words and nothing claims success", async ({ page }) => {
    for (const [status, detail] of [
      [403, "You are viewing a client's account, so their lists cannot be changed from here. Switch back to your own account to change your lists."],
      [503, "The instrument list could not be checked just now, so nothing was added. Please try again."],
    ] as const) {
      const { calls } = await setup(page, 3, { lists: [{ watchlist_id: "wl_a", name: "Mine", symbol_count: 1 }], bulk: () => ({ status, body: { detail } }) });
      await runScreen(page);
      await tick(page, "FX000");
      await page.getByTestId("screener-add-list").selectOption("wl_a");
      await page.getByTestId("screener-add-confirm").click();
      await expect(page.getByTestId("screener-add-error")).toContainText(detail.slice(0, 40));
      await expect(page.getByTestId("screener-add-added")).toHaveCount(0);
      await expect(page.getByTestId("screener-add-count")).toHaveText("1 selected");              // the choice is kept for a retry
      expect(writes(calls)).toHaveLength(1);
      await page.unrouteAll({ behavior: "ignoreErrors" });
    }
  });

  test("AL-9 a double press adds once", async ({ page }) => {
    const { calls } = await setup(page, 3, { lists: [{ watchlist_id: "wl_a", name: "Mine", symbol_count: 0 }], delayMs: 600 });
    await runScreen(page);
    await tick(page, "FX000", "FX001");
    await page.getByTestId("screener-add-list").selectOption("wl_a");
    const btn = page.getByTestId("screener-add-confirm");
    await btn.click();
    await expect(btn).toBeDisabled();
    await btn.click({ force: true, timeout: 500 }).catch(() => undefined);
    await expect(page.getByTestId("screener-add-added")).toHaveText("Added 2");
    expect(writes(calls)).toHaveLength(1);
  });

  test("AL-10 the two meanings are labelled apart", async ({ page }) => {
    await setup(page, 3, { lists: [{ watchlist_id: "wl_a", name: "Mine", symbol_count: 0 }] });
    await runScreen(page);
    await expect(bar(page)).toContainText("a fixed snapshot");
    await expect(bar(page)).toContainText("not advice");
    await expect(page.getByTestId("screener-watchlist-save")).toHaveText("Keep this screen (re-runs daily)");
    await expect(page.getByTestId("screener-watchlist")).toContainText("the rules are saved and re-run each day");
  });

  test("AL-11 phone 390px: the bar stays inside the screen and its button is tall enough to press", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await setup(page, 3, { lists: [{ watchlist_id: "wl_a", name: "A list with a rather long name to wrap", symbol_count: 12 }] });
    await runScreen(page);
    await tick(page, "FX000");
    await page.getByTestId("screener-add-list").selectOption("wl_a");
    const box = await page.getByTestId("screener-add-confirm").boundingBox();
    expect(box!.height).toBeGreaterThanOrEqual(44);
    const barBox = await bar(page).boundingBox();
    expect(barBox!.x).toBeGreaterThanOrEqual(0);
    expect(barBox!.x + barBox!.width).toBeLessThanOrEqual(390 + 1);
    const wide = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    expect(wide).toBeLessThanOrEqual(1);
  });

  test("AL-12 a new run clears the ticks", async ({ page }) => {
    await setup(page, 3, { lists: [{ watchlist_id: "wl_a", name: "Mine", symbol_count: 0 }] });
    await runScreen(page);
    await tick(page, "FX000", "FX001");
    await expect(page.getByTestId("screener-add-count")).toHaveText("2 selected");
    await page.getByTestId("screener-run").click();
    await expect(page.getByTestId("screener-results")).toHaveAttribute("data-state", "ready");
    await expect(page.getByTestId("screener-add-count")).toHaveText("Tick the stocks you want, then choose a list.");
    await expect(page.locator('[data-testid="screener-select"]:checked')).toHaveCount(0);
  });
});
