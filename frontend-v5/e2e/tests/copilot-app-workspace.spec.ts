/**
 * One-screen Copilot app — Watchlist & alerts, Saved, and the Screener's
 * "Save as a watchlist".
 *
 * MOCK — not real data: every /api/* answer below is a route mock. The fixtures
 * (e2e/fixtures/copilot-workspace-*.json) have the shape of the real routes
 * (named beside each) with made-up companies, names and numbers. Expected
 * values are worked out from the fixtures, not copied from the screen. No write
 * reaches a server: POST / PUT / DELETE are answered here.
 *
 * Runs with the other Copilot specs — see pw.copilot-app.config.ts.
 */
import { test, expect, type Locator, type Page, type Route } from "@playwright/test";
import fs from "fs";
import path from "path";
import { mockApi } from "../helpers/api-mock";

const APP = "/v5/app";
const FX = path.join(process.cwd(), "e2e", "fixtures");
const load = (name: string) => JSON.parse(fs.readFileSync(path.join(FX, name), "utf-8"));

const RW = load("copilot-workspace-research-watchlist.json");   // GET /api/public/research-watchlist
const SB = load("copilot-workspace-strategy-builder.json");     // /api/strategy-builder/*
const WX = load("copilot-workspace-alerts-levels.json");        // GET /api/filings/alerts, GET /api/positional/watchlist
const SV = load("copilot-workspace-saved.json");                // /api/screeners, /api/chat/sessions, /api/thematic/prefs
const RUN = load("screener-run-examples.json");                 // POST /api/screeners/run (FIXALPHA, FIXBRAVO match P/E < 15)

const ALPHA = "Fixture Alpha Industries Ltd";
const BRAVO = "Fixture Bravo Pharma Ltd";
const CHARLIE = "Fixture Charlie Power Ltd";
const STRATEGY_ID: string = SB.strategy.id;

const reply = (route: Route, body: unknown, status = 200) =>
  route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
const json = (page: Page, pattern: string | RegExp, body: unknown, status = 200) =>
  page.route(pattern, (route) => reply(route, body, status));

/** Captures what a screen hands to the Copilot. */
async function mockAsk(page: Page): Promise<string[]> {
  const sent: string[] = [];
  await page.route("**/api/chat/sessions", (route) =>
    route.request().method() === "POST" ? reply(route, { session_id: "asked1" }) : reply(route, []));
  await json(page, "**/api/chat/messages*", []);
  await page.route("**/api/chat/stream", (route) => {
    sent.push((route.request().postDataJSON() as { message: string }).message);
    return route.fulfill({ status: 200, contentType: "text/event-stream", body: `data: ${JSON.stringify({ type: "done", content: "ok" })}\n\n` });
  });
  return sent;
}

/**
 * Every call the three screens make, answered with the fixtures. A test then
 * overrides the one it is about (the route registered last wins).
 */
async function open(page: Page) {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await mockApi(page, "populated");
  const sent = await mockAsk(page);
  await page.route("**/api/public/research-watchlist*", (route) =>
    reply(route, new URL(route.request().url()).searchParams.get("date") === "2026-10-05" ? RW.earlier : RW.latest));
  await json(page, "**/api/screeners", SV.screeners);
  await json(page, "**/api/screeners/run", RUN.matches);
  await json(page, "**/api/strategy-builder/templates", SB.templates);
  await json(page, "**/api/strategy-builder/strategies", SB.strategies);
  await json(page, "**/api/strategy-builder/strategies/*", SB.strategy);
  await json(page, "**/api/strategy-builder/screen", SB.screen);
  await json(page, "**/api/filings/alerts", WX.alerts);
  await json(page, "**/api/positional/watchlist*", WX.levels);
  await json(page, "**/api/thematic/prefs", SV.prefs);
  // GET /api/watchlists (backend/routes/watchlists.py): a user who has had lists and
  // has none now, so "Your lists" is in its empty state and asks for nothing more.
  // That section has its own spec: copilot-app-watchlists.spec.ts.
  await json(page, /\/api\/watchlists(?:[/?]|$)/, { lists: [], limits: { max_lists: 20, max_symbols: 100 }, starter_pending: false });
  return { sent, errors };
}

/** The thread list for the Saved screen, leaving "start a thread" (POST) working for a screen that asks the Copilot. */
const threads = (page: Page, list: unknown) =>
  page.route("**/api/chat/sessions", (route) => (route.request().method() === "POST" ? reply(route, { session_id: "asked1" }) : reply(route, list)));

/** The stocks whose icon is drawn inside `scope`, in order. */
const iconKeys = (scope: Locator) =>
  scope.locator('[data-testid="entity-icon"][data-kind="stock"]').evaluateAll((els) => els.map((e) => e.getAttribute("data-key")));

const sideways = (page: Page) => page.evaluate(() => {
  const sc = document.querySelector('[data-testid="copilot-scroll"]') as HTMLElement | null;
  return {
    doc: document.documentElement.scrollWidth - document.documentElement.clientWidth,
    scroll: sc ? sc.scrollWidth - sc.clientWidth : 0,
  };
});

// ─────────────────────────────────────────────────────────────────────────
// Watchlist & alerts
// ─────────────────────────────────────────────────────────────────────────

test.describe("Watchlist — the research watchlist", () => {
  test("every stock has its icon, place, confidence, earlier-list badge, and a live or a stored price", async ({ page }) => {
    const { sent, errors } = await open(page);
    await page.goto(`${APP}/page/watchlist?wl=all`);
    await expect(page.getByTestId("watchlist-count")).toHaveText("Research watchlist · 3 stocks");
    await expect(page.getByTestId("watchlist-list-date")).toHaveText("List of 12 Oct 2026");
    await expect(page.getByTestId("watchlist-name")).toHaveText([ALPHA, BRAVO, CHARLIE]);
    await expect(page.getByTestId("watchlist-rank")).toHaveText(["#1", "#2", "#3"]);
    expect(await iconKeys(page.getByTestId("watchlist-list"))).toEqual(["FIXALPHA", "FIXBRAVO", "FIXCHARLIE"]);

    const rows = page.getByTestId("watchlist-item");
    // Alpha: live quote 213.00, +2.50 (+1.19%) today; added at 200.00 → +6.5%.
    await expect(rows.nth(0).getByTestId("watchlist-price")).toHaveText("₹213.00");
    await expect(rows.nth(0).getByTestId("watchlist-change")).toHaveText("+1.19%");
    await expect(rows.nth(0)).toContainText("+₹2.50");
    await expect(rows.nth(0).getByTestId("watchlist-since")).toHaveText("Since 12 Oct at ₹200.00 · +6.5%");
    await expect(rows.nth(0)).toContainText("High confidence");
    await expect(rows.nth(0).getByTestId("watchlist-carried")).toHaveCount(0);
    // Bravo: down today, below the price it was added at, and also in the 5 Oct list.
    await expect(rows.nth(1).getByTestId("watchlist-change")).toHaveText("−1.23%");
    await expect(rows.nth(1).getByTestId("watchlist-since")).toHaveText("Since 12 Oct at ₹500.00 · −4.0%");
    await expect(rows.nth(1).getByTestId("watchlist-carried")).toHaveText("Also in the 5 Oct list");
    await expect(rows.nth(1)).toContainText("Strong, with caveat");
    // Charlie: no live quote came back — the stored price and its date, and no day change.
    await expect(rows.nth(2).getByTestId("watchlist-price")).toHaveText("₹75.40");
    await expect(rows.nth(2).getByTestId("watchlist-noquote")).toHaveText("No quote today");
    await expect(rows.nth(2).getByTestId("watchlist-stored-price")).toHaveText("Stored price · 10 Oct");
    await expect(rows.nth(2).getByTestId("watchlist-change")).toHaveCount(0);

    await expect(page.getByTestId("watchlist-live")).toHaveText("Live prices · 2 of 3");
    await expect(page.getByTestId("watchlist-status")).toContainText("3 of 3 shown · 1 also in an earlier list");
    await expect(page.getByTestId("watchlist-disclaimer")).toHaveText("Fixture disclaimer: research for information only, not a recommendation.");

    await rows.nth(1).getByTestId("watchlist-row").click();
    await expect.poll(() => sent).toEqual([`Tell me about ${BRAVO}`]);
    expect(errors).toEqual([]);
  });

  test("the confidence filter and the sort work on the list that came back", async ({ page }) => {
    const { errors } = await open(page);
    await page.goto(`${APP}/page/watchlist?wl=all`);
    await expect(page.getByTestId("watchlist-tier-all")).toHaveText("All · 3");
    await expect(page.getByTestId("watchlist-tier-caveat")).toHaveText("Strong, with caveat · 1");

    await page.getByTestId("watchlist-tier-speculative").click();
    await expect(page.getByTestId("watchlist-name")).toHaveText([CHARLIE]);
    await expect(page.getByTestId("watchlist-status")).toContainText("1 of 3 shown");
    await expect(page.getByTestId("watchlist-count")).toHaveText("Research watchlist · 3 stocks");   // the list itself is unchanged

    await page.getByTestId("watchlist-tier-all").click();
    // −41.0, −22.4, −4.2 from the 52-week high
    await page.getByTestId("watchlist-sort").selectOption("high52");
    await expect(page.getByTestId("watchlist-name")).toHaveText([CHARLIE, BRAVO, ALPHA]);
    // +1.19%, −1.23%, no quote (last)
    await page.getByTestId("watchlist-sort").selectOption("change");
    await expect(page.getByTestId("watchlist-name")).toHaveText([ALPHA, BRAVO, CHARLIE]);
    await page.getByTestId("watchlist-sort").selectOption("rank");
    await expect(page.getByTestId("watchlist-rank")).toHaveText(["#1", "#2", "#3"]);
    expect(errors).toEqual([]);
  });

  test("a stock opens to the research behind it: the numbers that came back, the latest quarter and the notes", async ({ page }) => {
    const { sent, errors } = await open(page);
    await page.goto(`${APP}/page/watchlist?wl=all`);
    await expect(page.getByTestId("watchlist-detail")).toHaveCount(0);
    const rows = page.getByTestId("watchlist-item");

    await rows.nth(0).getByTestId("watchlist-row-toggle").click();
    const alpha = rows.nth(0).getByTestId("watchlist-detail");
    await expect(alpha.getByTestId("watchlist-metric")).toHaveText([
      "Revenue growth a year22.4%", "Profit growth a year28.1%", "Return on capital31.4%", "Cash flow to profit1.12×",
      "Debt to EBITDA0.40×", "Market value₹15.4K Cr", "Price to earnings32.4Sector median 28.9", "From the 52-week high−4.2%",
      "Against the 200-day average+9.8%", "Six-month return+18.6%", "Promoter holding58.2%", "Promoter shares pledged0.0%",
    ]);
    await expect(alpha.getByTestId("watchlist-quarter")).toHaveText("Latest quarter (Jun-26), against a year earlier: revenue +19.4% · profit +24.2% · the 3Y EPS CAGR is 28.1%");
    for (const note of ["Fixture stage note for Alpha: full research note written.", "Fixture thesis for Alpha: order inflows are growing faster than revenue.", "Fixture balance sheet note for Alpha.", "Fixture order book note for Alpha.", "Fixture expansion note for Alpha.", "Fixture management note for Alpha.", "Fixture technical note for Alpha."]) {
      await expect(alpha).toContainText(note);
    }
    await expect(alpha).toContainText("Research depth: complete");

    // Bravo carries fewer numbers: only those are drawn, and its growth window and source are named.
    await rows.nth(1).getByTestId("watchlist-row-toggle").click();
    const bravo = rows.nth(1).getByTestId("watchlist-detail");
    await expect(bravo.getByTestId("watchlist-metric")).toHaveCount(9);
    await expect(bravo).toContainText("Market value₹820 Cr");
    await expect(bravo).toContainText("Promoter shares pledged12.4%");
    await expect(bravo).not.toContainText("Sector median");
    await expect(bravo).not.toContainText("Balance sheet");
    await expect(bravo).toContainText("Growth figures: 3Y, annual (fixture window)");
    await expect(bravo).toContainText("Source: Fixture growth screen · Research depth: screen only");
    await expect(bravo.getByTestId("watchlist-quarter")).toHaveText("Latest quarter, against a year earlier: revenue +8.4% · profit −2.6% · the 3Y profit CAGR is 19.6%");

    await rows.nth(0).getByTestId("watchlist-row-toggle").click();
    await expect(page.getByTestId("watchlist-detail")).toHaveCount(1);
    await bravo.getByTestId("watchlist-detail-ask").click();
    await expect.poll(() => sent).toEqual([`Walk me through ${BRAVO} (FIXBRAVO): the business, the latest numbers, the risks and what to watch.`]);
    expect(errors).toEqual([]);
  });

  test("an earlier list is read from the same endpoint by date, and says its prices are today's", async ({ page }) => {
    const { errors } = await open(page);
    const dates: Array<string | null> = [];
    await page.route("**/api/public/research-watchlist*", (route) => {
      const date = new URL(route.request().url()).searchParams.get("date");
      dates.push(date);
      return reply(route, date === "2026-10-05" ? RW.earlier : RW.latest);
    });
    await page.goto(`${APP}/page/watchlist?wl=all`);
    const picker = page.getByTestId("watchlist-list-picker");
    await expect(picker.locator("option")).toHaveText(["12 Oct 2026 · 3 stocks · latest", "5 Oct 2026 · 1 stock"]);
    await expect(page.getByTestId("watchlist-historical")).toHaveCount(0);

    await picker.selectOption("2026-10-05");
    await expect(page.getByTestId("watchlist-count")).toHaveText("Research watchlist · 1 stock");
    await expect(page.getByTestId("watchlist-list-date")).toHaveText("List of 5 Oct 2026");
    await expect(page.getByTestId("watchlist-name")).toHaveText([BRAVO]);
    await expect(page.getByTestId("watchlist-since")).toHaveText("Since 5 Oct at ₹520.00 · −7.7%");
    await expect(page.getByTestId("watchlist-historical")).toBeVisible();
    expect(dates).toContain("2026-10-05");

    await picker.selectOption("2026-10-12");
    await expect(page.getByTestId("watchlist-count")).toHaveText("Research watchlist · 3 stocks");
    await expect(page.getByTestId("watchlist-historical")).toHaveCount(0);
    expect(dates.filter((d) => d !== null && d !== "2026-10-05")).toEqual([]);   // the newest list is asked for without a date
    expect(errors).toEqual([]);
  });

  test("empty and error states: nothing published, a failed load with a retry that works, and a body that is not a list", async ({ page }) => {
    const { errors } = await open(page);
    await json(page, "**/api/public/research-watchlist*", RW.empty);
    await page.goto(`${APP}/page/watchlist?wl=all`);
    const screen = page.getByTestId("screen-page-watchlist");
    await expect(screen).toContainText("No research list has been published yet");
    await expect(page.getByTestId("watchlist-count")).toHaveText("Research watchlist");
    await expect(page.getByTestId("watchlist-row")).toHaveCount(0);

    let fail = true;
    await page.route("**/api/public/research-watchlist*", (route) => (fail ? reply(route, { detail: "boom" }, 500) : reply(route, RW.latest)));
    await page.reload();
    await expect(screen).toContainText("The research watchlist didn’t load — the server reported an error", { timeout: 15_000 });
    await expect(page.getByTestId("watchlist-row")).toHaveCount(0);
    fail = false;
    await screen.getByRole("alert").filter({ hasText: "The research watchlist didn’t load" }).getByRole("button", { name: "Retry ›" }).click();
    await expect(page.getByTestId("watchlist-name")).toHaveText([ALPHA, BRAVO, CHARLIE]);

    await json(page, "**/api/public/research-watchlist*", {});
    await page.reload();
    await expect(screen).toContainText("The research watchlist didn’t load — the response was not in the expected shape");
    expect(errors).toEqual([]);
  });
});

test.describe("Watchlist — your screens as watchlists", () => {
  test("both kinds are listed from their own endpoints; opening one runs it and draws each stock with its icon", async ({ page }) => {
    const { sent, errors } = await open(page);
    const ruleRuns: unknown[] = [];
    await page.route("**/api/screeners/run", (route) => { ruleRuns.push(route.request().postDataJSON()); return reply(route, RUN.matches); });
    const strategyReads: string[] = [];
    await page.route("**/api/strategy-builder/strategies/*", (route) => { strategyReads.push(new URL(route.request().url()).pathname); return reply(route, SB.strategy); });
    const strategyRuns: Array<{ definition: unknown }> = [];
    await page.route("**/api/strategy-builder/screen", (route) => { strategyRuns.push(route.request().postDataJSON()); return reply(route, SB.screen); });
    await page.goto(`${APP}/page/watchlist?wl=all`);

    await expect(page.getByTestId("watchlist-screen-name")).toHaveText(["Fixture value screen"]);
    await expect(page.getByTestId("watchlist-strategy-name")).toHaveText(["Fixture uptrend watch"]);
    await expect(page.getByTestId("watchlist-screens-empty")).toHaveCount(0);
    expect(ruleRuns).toEqual([]);          // nothing runs until a watchlist is opened
    expect(strategyRuns).toEqual([]);

    await page.getByTestId("watchlist-screen-toggle").click();
    await expect(page.getByTestId("watchlist-screen-stock")).toHaveText(["FIXALPHA", "FIXBRAVO"]);
    expect(await iconKeys(page.getByTestId("watchlist-screens"))).toEqual(["FIXALPHA", "FIXBRAVO"]);
    await expect(page.getByTestId("watchlist-screen-count")).toHaveText("2 stocks today · data of 12 Oct 2026");
    expect(ruleRuns).toEqual([{ conditions: [{ key: "pe", op: "under", value: "15" }], bucket: "" }]);

    await page.getByTestId("watchlist-strategy-toggle").click();
    await expect(page.getByTestId("watchlist-strategy-stock")).toHaveText(["FIXALPHA", "FIXBRAVO"]);
    expect(await iconKeys(page.getByTestId("watchlist-strategies"))).toEqual(["FIXALPHA", "FIXBRAVO"]);
    await expect(page.getByTestId("watchlist-strategy-count")).toHaveText("2 stocks today · data of 12 Oct 2026");
    // The saved strategy's own definition is what is run.
    expect(strategyReads).toEqual([`/api/strategy-builder/strategies/${STRATEGY_ID}`]);
    expect(strategyRuns.map((r) => r.definition)).toEqual([SB.strategy.active_version.definition]);

    await page.getByTestId("watchlist-strategy-stock").first().click();
    await expect.poll(() => sent).toEqual(["Tell me about FIXALPHA"]);
    expect(errors).toEqual([]);
  });

  test("empty states: nothing saved at all, one kind only, and a screen nothing passes today", async ({ page }) => {
    const { errors } = await open(page);
    await json(page, "**/api/screeners", []);
    await json(page, "**/api/strategy-builder/strategies", SB.strategies_empty);
    await page.goto(`${APP}/page/watchlist?wl=all`);
    await expect(page.getByTestId("watchlist-screens-empty")).toContainText("Save a screen to make a watchlist");
    await expect(page.getByTestId("watchlist-screen")).toHaveCount(0);
    await expect(page.getByTestId("watchlist-strategy")).toHaveCount(0);

    await json(page, "**/api/strategy-builder/strategies", SB.strategies);
    await json(page, "**/api/strategy-builder/screen", SB.screen_empty);
    await page.reload();
    await expect(page.getByTestId("watchlist-screens-empty")).toHaveCount(0);
    await expect(page.getByTestId("watchlist-rules-none")).toBeVisible();
    await page.getByTestId("watchlist-strategy-toggle").click();
    await expect(page.getByTestId("watchlist-strategy-empty")).toHaveText("No stock passes this screen in the latest data (12 Oct 2026). Its rules are strict by design.");
    await expect(page.getByTestId("watchlist-strategy-stock")).toHaveCount(0);

    await json(page, "**/api/screeners", SV.screeners);
    await json(page, "**/api/screeners/run", RUN.no_match);
    await json(page, "**/api/strategy-builder/strategies", SB.strategies_empty);
    await page.reload();
    await expect(page.getByTestId("watchlist-strategies-none")).toBeVisible();
    await page.getByTestId("watchlist-screen-toggle").click();
    await expect(page.getByTestId("watchlist-screen-empty")).toContainText("No stock passes this screen in the latest data (12 Oct 2026)");
    expect(errors).toEqual([]);
  });

  test("error states: a list that fails, a list in the wrong shape, and a run that fails", async ({ page }) => {
    const { errors } = await open(page);
    await json(page, "**/api/screeners", { detail: "boom" }, 500);
    await json(page, "**/api/strategy-builder/strategies", {});            // 200, but not a list
    await page.goto(`${APP}/page/watchlist?wl=all`);
    const screen = page.getByTestId("screen-page-watchlist");
    await expect(screen).toContainText("Your saved screens didn’t load — the server reported an error", { timeout: 15_000 });
    await expect(page.getByTestId("watchlist-strategies-error")).toContainText("Your saved ready-made screens didn’t load — the server’s response was not in the expected format");
    await expect(page.getByTestId("watchlist-screens-empty")).toHaveCount(0);   // a failed load is not "nothing saved"

    await json(page, "**/api/screeners", SV.screeners);
    await json(page, "**/api/screeners/run", RUN.unreachable);
    await json(page, "**/api/strategy-builder/strategies", SB.strategies);
    await json(page, "**/api/strategy-builder/strategies/*", { id: STRATEGY_ID, name: "Fixture uptrend watch", active_version: null });
    await page.reload();
    await page.getByTestId("watchlist-screen-toggle").click();
    await expect(page.getByTestId("watchlist-screen")).toContainText("This watchlist didn’t load — the stock data source did not answer");
    await page.getByTestId("watchlist-strategy-toggle").click();
    await expect(page.getByTestId("watchlist-strategy")).toContainText("This watchlist didn’t load — the server’s response was not in the expected format");
    await expect(page.getByTestId("watchlist-strategy-stock")).toHaveCount(0);
    expect(errors).toEqual([]);
  });

  test("deleting a saved screen asks first, removes it when the delete succeeds, and says so when it fails", async ({ page }) => {
    const { errors } = await open(page);
    let rules: unknown[] = SV.screeners;
    let strategies: { strategies: unknown[]; count: number } = SB.strategies;
    let failing = true;
    const deletes: string[] = [];
    await page.route("**/api/screeners", (route) => reply(route, rules));
    await page.route("**/api/screeners/scr_*", (route) => {
      deletes.push(`${route.request().method()} ${new URL(route.request().url()).pathname}`);
      if (failing) return reply(route, { detail: "boom" }, 500);
      rules = [];
      return reply(route, { status: "deleted", screener_id: "scr_fixture01" });
    });
    await page.route("**/api/strategy-builder/strategies", (route) => reply(route, strategies));
    await page.route("**/api/strategy-builder/strategies/*", (route) => {
      if (route.request().method() !== "DELETE") return reply(route, SB.strategy);
      deletes.push(`DELETE ${new URL(route.request().url()).pathname}`);
      strategies = SB.strategies_empty;
      return reply(route, { ok: true, id: STRATEGY_ID, archived: true });
    });
    await page.goto(`${APP}/page/watchlist?wl=all`);

    // The first press only arms the delete; "Keep" backs out.
    await page.getByTestId("watchlist-screen-delete").click();
    await page.getByTestId("watchlist-screen").getByRole("button", { name: "Keep" }).click();
    expect(deletes).toEqual([]);

    await page.getByTestId("watchlist-screen-delete").click();
    await page.getByTestId("watchlist-screen-delete-confirm").click();
    await expect(page.getByTestId("watchlist-screen-delete-error")).toContainText("The screen wasn’t deleted — the server reported an error");
    await expect(page.getByTestId("watchlist-screen-name")).toHaveText(["Fixture value screen"]);   // still there

    failing = false;
    await page.getByTestId("watchlist-screen-delete").click();
    await page.getByTestId("watchlist-screen-delete-confirm").click();
    await expect(page.getByTestId("watchlist-screen")).toHaveCount(0);
    await expect(page.getByTestId("watchlist-rules-none")).toBeVisible();
    expect(new Set(deletes)).toEqual(new Set(["DELETE /api/screeners/scr_fixture01"]));

    await page.getByTestId("watchlist-strategy-delete").click();
    await page.getByTestId("watchlist-strategy-delete-confirm").click();
    await expect(page.getByTestId("watchlist-screens-empty")).toBeVisible();   // now nothing is saved
    expect(deletes).toContain(`DELETE /api/strategy-builder/strategies/${STRATEGY_ID}`);
    expect(errors).toEqual([]);
  });
});

test.describe("Watchlist — price levels and filing alerts", () => {
  test("the scanner's levels are listed with each stock's icon; none, and a failed load, say so", async ({ page }) => {
    const { sent, errors } = await open(page);
    await page.goto(`${APP}/page/watchlist?wl=all`);
    await expect(page.getByTestId("watchlist-levels-count")).toHaveText("Price levels the scanner is watching · 2");
    const table = page.getByTestId("watchlist-levels");
    expect(await iconKeys(table)).toEqual(["FIXALPHA", "FIXBRAVO"]);
    const level = page.getByTestId("watchlist-level");
    await expect(level.nth(0)).toContainText("FIXALPHA");
    await expect(level.nth(0)).toContainText("Capital Goods");
    // close 510.00, level 500.00, stop 477.50, daily range 2.94%
    for (const text of ["₹510.00", "₹500.00", "₹477.50", "2.94%", "Breakout confirmed", "Near breakout"]) await expect(table).toContainText(text);
    await level.nth(1).click();
    await expect.poll(() => sent).toEqual(["Show the FIXBRAVO chart with support and resistance. Scanner note: Fixture reason: just below resistance"]);

    // What staging answers today: no technical data, so no levels.
    await page.goto(`${APP}/page/watchlist?wl=all`);
    await json(page, "**/api/positional/watchlist*", WX.levels_none);
    await page.reload();
    await expect(page.getByTestId("watchlist-levels-empty")).toContainText("No price levels to watch right now");
    await expect(page.getByTestId("watchlist-levels-empty")).toContainText("The scanner has no technical data to read yet");
    await expect(page.getByTestId("watchlist-level")).toHaveCount(0);

    await json(page, "**/api/positional/watchlist*", {});
    await page.reload();
    await expect(page.getByTestId("watchlist-levels-error")).toContainText("The levels to watch didn’t load");
    expect(errors).toEqual([]);
  });

  test("filing alerts: a switch saves the choice and moves only after the save; a failed save changes nothing", async ({ page }) => {
    const { errors } = await open(page);
    let stored = WX.alerts;
    let failing = false;
    const puts: unknown[] = [];
    await page.route("**/api/filings/alerts", (route) => {
      if (route.request().method() !== "PUT") return reply(route, stored);
      const body = route.request().postDataJSON() as { types: Record<string, boolean>; channels: Record<string, boolean> };
      puts.push(body);
      if (failing) return reply(route, { detail: "boom" }, 500);
      stored = { ...stored, types: body.types, channels: body.channels, updatedAt: "2026-10-13T08:00:00+00:00" };
      return reply(route, stored);
    });
    await page.goto(`${APP}/page/watchlist?wl=all`);

    const types = page.getByTestId("watchlist-alert-switch");
    await expect(page.getByTestId("watchlist-alert")).toHaveCount(4);
    await expect(page.getByTestId("watchlist-alerts-on")).toHaveText("3");           // three of four types are true
    await expect(types.nth(1)).toHaveAttribute("aria-checked", "false");             // annual reports
    await expect(page.getByTestId("watchlist-alerts-delivery")).toHaveText("Fixture delivery note: nothing is sent today.");
    await expect(page.getByTestId("watchlist-alert").nth(0)).toContainText("Saved · not sending");
    await expect(page.getByTestId("watchlist-alert").nth(1)).toContainText("Off");

    await page.getByRole("switch", { name: "Annual reports alerts" }).click();
    await expect(page.getByTestId("watchlist-alerts-on")).toHaveText("4");
    await expect(types.nth(1)).toHaveAttribute("aria-checked", "true");
    // The whole set is sent, with only that one type changed.
    expect(puts).toEqual([{ types: { concall_transcript: true, annual_report: true, investor_presentation: true, financial_results: true }, channels: { email: true, whatsapp: false } }]);

    const channels = page.getByTestId("watchlist-channel-switch");
    await expect(page.getByTestId("watchlist-alert-channel")).toHaveCount(2);
    await expect(channels.nth(1)).toHaveAttribute("aria-checked", "false");
    await page.getByRole("switch", { name: "Send filing alerts by WhatsApp" }).click();
    await expect(channels.nth(1)).toHaveAttribute("aria-checked", "true");
    expect(puts[1]).toEqual({ types: { concall_transcript: true, annual_report: true, investor_presentation: true, financial_results: true }, channels: { email: true, whatsapp: true } });

    failing = true;
    await page.getByRole("switch", { name: "Quarterly results alerts" }).click();
    await expect(page.getByTestId("watchlist-alerts-save-error")).toContainText("Your alert choice wasn’t saved, so nothing changed — the server reported an error", { timeout: 15_000 });
    await expect(types.nth(3)).toHaveAttribute("aria-checked", "true");              // unchanged
    await expect(page.getByTestId("watchlist-alerts-on")).toHaveText("4");
    expect(errors).toEqual([]);
  });

  test("filing alerts: no types to show, and a failed load", async ({ page }) => {
    const { errors } = await open(page);
    await json(page, "**/api/filings/alerts", { ok: true, types: {}, channels: {}, catalog: [], delivery: { active: false }, updatedAt: null });
    await page.goto(`${APP}/page/watchlist?wl=all`);
    const screen = page.getByTestId("screen-page-watchlist");
    await expect(screen).toContainText("No filing-alert types to show");
    await expect(page.getByTestId("watchlist-alert")).toHaveCount(0);

    await json(page, "**/api/filings/alerts", { detail: "boom" }, 500);
    await page.reload();
    await expect(screen).toContainText("Your alert preferences didn’t load — the server reported an error", { timeout: 15_000 });
    // What has no store stays declared, with its engineering notes for the admin fixture user.
    await expect(page.getByTestId("watchlist-alerts-nc")).toContainText("Price and volume alerts, and the sending of alerts, are not connected yet");
    await expect(page.getByTestId("watchlist-alerts-nc").getByTestId("not-connected-needs")).toContainText("Alert rules on price, volume");
    expect(errors).toEqual([]);
  });
});

// ─────────────────────────────────────────────────────────────────────────
// Screener → "Save as a watchlist"
// ─────────────────────────────────────────────────────────────────────────

test.describe("Screener — save as a watchlist", () => {
  /** A stateful /api/screeners: GET lists what is stored, POST stores (or fails while `failing`). */
  async function screenerStore(page: Page) {
    const state = { rows: [...SV.screeners] as Array<Record<string, unknown>>, failing: false, posts: [] as unknown[] };
    await page.route("**/api/screeners", (route) => {
      if (route.request().method() !== "POST") return reply(route, state.rows);
      const body = route.request().postDataJSON() as Record<string, unknown>;
      state.posts.push(body);
      if (state.failing) return reply(route, { detail: "boom" }, 500);
      const saved = { screener_id: `scr_new${state.rows.length}`, user_id: "user_fixture", ...body, created_at: "2026-10-13T08:00:00+00:00", updated_at: "2026-10-13T08:00:00+00:00" };
      state.rows = [saved, ...state.rows];
      return reply(route, saved);
    });
    return state;
  }

  test("a rule screen that was run is saved with its rules, and then shows on the Watchlist", async ({ page }) => {
    const { errors } = await open(page);
    const store = await screenerStore(page);
    await page.goto(`${APP}/tool/screener`);
    await expect(page.getByTestId("screener-watchlist")).toHaveCount(0);           // nothing to keep before a run

    await page.getByTestId("screener-rule-value").nth(1).fill("15");              // second rule is P/E, "under" by default
    await page.getByTestId("screener-run").click();
    await expect(page.getByTestId("screener-results-count")).toHaveText("2 stocks match");
    await expect(page.getByTestId("screener-watchlist")).toBeVisible();
    await expect(page.getByTestId("screener-watchlist-save")).toBeDisabled();      // needs a name

    await page.getByTestId("screener-watchlist-name").fill("Fixture cheap stocks");
    await page.getByTestId("screener-watchlist-save").click();
    await expect(page.getByTestId("screener-watchlist-done")).toContainText("Saved as Fixture cheap stocks.");
    expect(store.posts).toEqual([{ name: "Fixture cheap stocks", query: "Screen stocks where P/E under 15", conditions: [{ key: "pe", op: "under", value: "15" }], bucket: "" }]);
    await expect(page.getByTestId("screener-watchlist-save")).toHaveCount(0);      // it cannot be saved twice by accident
    await expect(page.getByTestId("screener-saved-name")).toHaveText(["Fixture cheap stocks", "Fixture value screen"]);

    await page.getByTestId("screener-watchlist-open").click();
    await expect(page).toHaveURL(/\/v5\/app\/page\/watchlist\?wl=screens$/);
    await expect(page.getByTestId("watchlist-screen-name")).toHaveText(["Fixture cheap stocks", "Fixture value screen"]);
    await page.getByTestId("watchlist-screen-toggle").first().click();
    await expect(page.getByTestId("watchlist-screen-stock")).toHaveText(["FIXALPHA", "FIXBRAVO"]);
    expect(errors).toEqual([]);
  });

  test("a failed save says so and keeps the form; saving again works", async ({ page }) => {
    const { errors } = await open(page);
    const store = await screenerStore(page);
    store.failing = true;
    await page.goto(`${APP}/tool/screener`);
    await page.getByTestId("screener-rule-value").nth(1).fill("15");
    await page.getByTestId("screener-run").click();
    await page.getByTestId("screener-watchlist-name").fill("Fixture cheap stocks");
    await page.getByTestId("screener-watchlist-save").click();
    await expect(page.getByTestId("screener-watchlist-error")).toContainText("The watchlist wasn’t saved — the server reported an error", { timeout: 15_000 });
    await expect(page.getByTestId("screener-watchlist-done")).toHaveCount(0);
    await expect(page.getByTestId("screener-watchlist-name")).toHaveValue("Fixture cheap stocks");
    await expect(page.getByTestId("screener-saved-name")).toHaveText(["Fixture value screen"]);   // nothing was added

    store.failing = false;
    await page.getByTestId("screener-watchlist-save").click();
    await expect(page.getByTestId("screener-watchlist-done")).toContainText("Saved as Fixture cheap stocks.");
    await expect(page.getByTestId("screener-watchlist-error")).toHaveCount(0);
    expect(errors).toEqual([]);
  });

  test("a run that started from a saved screen is already a watchlist, and says where", async ({ page }) => {
    const { errors } = await open(page);
    const store = await screenerStore(page);
    await page.goto(`${APP}/tool/screener`);
    await page.getByTestId("screener-saved-run").click();
    await expect(page.getByTestId("screener-results-count")).toHaveText("2 stocks match");
    await expect(page.getByTestId("screener-watchlist-already")).toContainText("Fixture value screen is one of your saved screens, so it is already on your Watchlist.");
    await expect(page.getByTestId("screener-watchlist-save")).toHaveCount(0);
    await page.getByTestId("screener-watchlist-open").click();
    await expect(page).toHaveURL(/\/v5\/app\/page\/watchlist\?wl=screens$/);
    expect(store.posts).toEqual([]);
    expect(errors).toEqual([]);
  });

  test("a ready-made screen draws an icon on every row, is saved as a strategy, and then shows on the Watchlist", async ({ page }) => {
    const { errors } = await open(page);
    let strategies: { strategies: unknown[]; count: number } = SB.strategies_empty;
    const posts: unknown[] = [];
    await page.route("**/api/strategy-builder/strategies", (route) => {
      if (route.request().method() !== "POST") return reply(route, strategies);
      const body = route.request().postDataJSON() as { name: string };
      posts.push(body);
      const row = { ...SB.strategies.strategies[0], name: body.name };
      strategies = { strategies: [row], count: 1 };
      return reply(route, { ...SB.created, name: body.name });
    });
    await page.goto(`${APP}/tool/screener`);
    await page.getByTestId("screener-strategy-template").first().click();
    await expect(page.getByTestId("screener-strategy-results")).toHaveAttribute("data-state", "ready");
    await expect(page.getByTestId("screener-strategy-row")).toHaveText(["FIXALPHA", "FIXBRAVO"]);
    expect(await iconKeys(page.getByTestId("screener-strategy-results"))).toEqual(["FIXALPHA", "FIXBRAVO"]);

    await expect(page.getByTestId("screener-strategy-watchlist-name")).toHaveValue("Fixture Uptrend");   // the screen's own name, editable
    await page.getByTestId("screener-strategy-watchlist-name").fill("Fixture uptrend to follow");
    await page.getByTestId("screener-strategy-watchlist-save").click();
    await expect(page.getByTestId("screener-strategy-watchlist-done")).toContainText("Saved as Fixture uptrend to follow.");
    // The template's own definition is what is stored.
    expect(posts).toEqual([{ name: "Fixture uptrend to follow", description: "Fixture description of an uptrend screen.", asset_class: "STOCK", definition: SB.templates.templates[0].definition }]);

    await page.getByTestId("screener-strategy-watchlist-open").click();
    await expect(page).toHaveURL(/\/v5\/app\/page\/watchlist\?wl=screens$/);
    await expect(page.getByTestId("watchlist-strategy-name")).toHaveText(["Fixture uptrend to follow"]);
    await page.getByTestId("watchlist-strategy-toggle").click();
    await expect(page.getByTestId("watchlist-strategy-stock")).toHaveText(["FIXALPHA", "FIXBRAVO"]);
    expect(errors).toEqual([]);
  });

  test("a ready-made screen that is refused says why; one with no stocks today can still be kept", async ({ page }) => {
    const { errors } = await open(page);
    const posts: unknown[] = [];
    await page.route("**/api/strategy-builder/strategies", (route) => {
      if (route.request().method() !== "POST") return reply(route, SB.strategies_empty);
      posts.push(route.request().postDataJSON());
      // The route's own refusal shape: backend/routes/strategy_builder.py create_strategy
      return reply(route, { detail: { message: "invalid strategy spec", errors: ["fixture: entry rule is not known"] } }, 400);
    });
    await page.goto(`${APP}/tool/screener`);
    await page.getByTestId("screener-strategy-template").first().click();
    await page.getByTestId("screener-strategy-watchlist-save").click();
    await expect(page.getByTestId("screener-strategy-watchlist-error")).toContainText("The watchlist wasn’t saved — invalid strategy spec");
    await expect(page.getByTestId("screener-strategy-watchlist-done")).toHaveCount(0);
    expect(posts.length).toBe(1);

    await json(page, "**/api/strategy-builder/screen", SB.screen_empty);
    await page.getByTestId("screener-strategy-template").nth(1).click();
    await expect(page.getByTestId("screener-strategy-results")).toHaveAttribute("data-state", "empty");
    await expect(page.getByTestId("screener-strategy-watchlist-name")).toHaveValue("Fixture Squeeze");
    await expect(page.getByTestId("screener-strategy-watchlist-error")).toHaveCount(0);   // the earlier refusal belonged to the other screen
    expect(errors).toEqual([]);
  });
});

// ─────────────────────────────────────────────────────────────────────────
// Saved
// ─────────────────────────────────────────────────────────────────────────

test.describe("Saved", () => {
  test("both kinds of saved screen, starred questions and threads come from their endpoints", async ({ page }) => {
    const { sent, errors } = await open(page);
    await threads(page, SV.sessions);
    await page.goto(`${APP}/page/saved`);
    const screen = page.getByTestId("screen-page-saved");
    await expect(page.getByTestId("saved-screen-title")).toHaveText(["Fixture value screen"]);
    await expect(page.getByTestId("saved-screen")).toContainText("Rule screen · 1 rule");
    await expect(page.getByTestId("saved-strategy-title")).toHaveText(["Fixture uptrend watch"]);
    await expect(page.getByTestId("saved-strategy")).toContainText("Strategy screen · stocks");
    await expect(page.getByTestId("saved-strategy")).toContainText("Saved 11 Oct 2026");
    // Only the starred question — the one that is in history alone is not a saved item.
    await expect(page.getByTestId("saved-question-title")).toHaveText(["Fixture question about capital goods order books"]);
    await expect(page.getByTestId("saved-thread-title")).toHaveText(["Fixture thread one", "Fixture thread two"]);
    for (const heading of ["Screens · 2", "Starred research questions · 1", "Threads · most recent · 2"]) await expect(screen).toContainText(heading);
    await expect(page.getByTestId("saved-reports-nc")).toContainText("Saving a report is not connected yet");
    await expect(page.getByTestId("saved-export")).toBeVisible();

    await page.getByTestId("saved-strategy-watchlist").click();
    await expect(page).toHaveURL(/\/v5\/app\/page\/watchlist\?wl=screens$/);
    await expect(page.getByTestId("watchlist-strategy-name")).toHaveText(["Fixture uptrend watch"]);
    await page.goBack();
    await page.getByTestId("saved-question-ask").click();
    await expect.poll(() => sent).toEqual(["Fixture question about capital goods order books"]);
    expect(errors).toEqual([]);
  });

  test("the holdings file downloads under the server's file name; no holdings, and a failure, are said plainly", async ({ page }) => {
    const { errors } = await open(page);
    const asked: string[] = [];
    let mode: "ok" | "none" | "fail" = "ok";
    await page.route("**/api/portfolio/holdings/export*", (route) => {
      const format = new URL(route.request().url()).searchParams.get("format") ?? "";
      asked.push(format);
      if (mode === "none") return reply(route, { detail: "No holdings to export" }, 404);
      if (mode === "fail") return reply(route, { detail: "boom" }, 500);
      return route.fulfill({
        status: 200,
        contentType: format === "xlsx" ? "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" : "text/csv",
        headers: { "content-disposition": `attachment; filename="fixture_holdings.${format}"` },
        body: "Name,Units / Qty\nFixture Holding,10\n",
      });
    });
    await page.goto(`${APP}/page/saved`);

    const [csv] = await Promise.all([page.waitForEvent("download"), page.getByTestId("saved-export-csv").click()]);
    expect(csv.suggestedFilename()).toBe("fixture_holdings.csv");
    await expect(page.getByTestId("saved-export-done")).toHaveText("Sent fixture_holdings.csv to your downloads.");
    const [xlsx] = await Promise.all([page.waitForEvent("download"), page.getByTestId("saved-export-xlsx").click()]);
    expect(xlsx.suggestedFilename()).toBe("fixture_holdings.xlsx");
    expect(asked).toEqual(["csv", "xlsx"]);

    mode = "none";
    await page.getByTestId("saved-export-csv").click();
    await expect(page.getByTestId("saved-export-error")).toContainText("The file wasn’t downloaded — there are no holdings to export yet");
    await expect(page.getByTestId("saved-export-done")).toHaveCount(0);
    mode = "fail";
    await page.getByTestId("saved-export-xlsx").click();
    await expect(page.getByTestId("saved-export-error")).toContainText("The file wasn’t downloaded — the server reported an error");
    expect(errors).toEqual([]);
  });

  test("a star is removed only when the server confirms it; a thread is deleted after asking twice", async ({ page }) => {
    const { errors } = await open(page);
    let prefs = SV.prefs;
    let sessions: Array<{ session_id: string }> = SV.sessions;
    let failing = true;
    const writes: string[] = [];
    await page.route("**/api/thematic/prefs", (route) => reply(route, prefs));
    await page.route("**/api/thematic/favorites/toggle", (route) => {
      const body = route.request().postDataJSON() as { query: string };
      writes.push(`unstar ${body.query}`);
      if (failing) return reply(route, { detail: "boom" }, 500);
      prefs = { ...prefs, favorites: prefs.favorites.filter((f: string) => f !== body.query) };
      return reply(route, prefs);
    });
    await page.route("**/api/chat/sessions", (route) => reply(route, sessions));
    await page.route("**/api/chat/sessions/*", (route) => {
      const id = new URL(route.request().url()).pathname.split("/").pop() ?? "";
      writes.push(`${route.request().method()} thread ${id}`);
      if (failing) return reply(route, { detail: "boom" }, 500);
      sessions = sessions.filter((s) => s.session_id !== id);
      return reply(route, { message: "Session deleted" });
    });
    await page.goto(`${APP}/page/saved`);

    // Both writes fail first: the items stay and the failure is shown.
    await page.getByTestId("saved-question-unstar").click();
    await expect(page.getByTestId("saved-question-error")).toContainText("The star wasn’t removed — the server reported an error", { timeout: 15_000 });
    await expect(page.getByTestId("saved-question")).toHaveCount(1);
    await page.getByTestId("saved-thread-delete").first().click();
    expect(writes.filter((w) => w.includes("thread"))).toEqual([]);              // the first press only arms it
    await page.getByTestId("saved-thread-delete-confirm").click();
    await expect(page.getByTestId("saved-thread-delete-error")).toContainText("The thread wasn’t deleted — the server reported an error", { timeout: 15_000 });
    await expect(page.getByTestId("saved-thread-title")).toHaveText(["Fixture thread one", "Fixture thread two"]);

    failing = false;
    await page.getByTestId("saved-question-unstar").click();
    await expect(page.getByTestId("saved-questions-empty")).toContainText("No starred questions yet");
    await expect(page.getByTestId("saved-question")).toHaveCount(0);
    await page.getByTestId("saved-thread-delete").first().click();
    await page.getByTestId("saved-thread-delete-confirm").click();
    await expect(page.getByTestId("saved-thread-title")).toHaveText(["Fixture thread two"]);
    expect(writes).toContain("unstar Fixture question about capital goods order books");
    expect(writes).toContain("DELETE thread sess_fixture01");
    expect(errors).toEqual([]);
  });

  test("empty and error states for each group", async ({ page }) => {
    const { errors } = await open(page);
    await json(page, "**/api/screeners", []);
    await json(page, "**/api/strategy-builder/strategies", SB.strategies_empty);
    await json(page, "**/api/thematic/prefs", { history: [], favorites: [] });
    await page.goto(`${APP}/page/saved`);                                          // mockAsk answers the thread list with []
    const screen = page.getByTestId("screen-page-saved");
    await expect(page.getByTestId("saved-screens-empty")).toContainText("No saved screens yet");
    await expect(page.getByTestId("saved-questions-empty")).toContainText("No starred questions yet");
    await expect(screen).toContainText("No threads yet");
    for (const id of ["saved-screen", "saved-strategy", "saved-question", "saved-thread"]) await expect(page.getByTestId(id)).toHaveCount(0);

    await json(page, "**/api/screeners", { detail: "boom" }, 500);
    await json(page, "**/api/strategy-builder/strategies", {});
    await json(page, "**/api/thematic/prefs", { detail: "boom" }, 500);
    await json(page, "**/api/chat/sessions", { detail: "boom" }, 500);
    await page.reload();
    await expect(screen).toContainText("Saved screens didn’t load — the server reported an error", { timeout: 15_000 });
    await expect(page.getByTestId("saved-strategies-error")).toContainText("Saved ready-made screens didn’t load — the server’s response was not in the expected format");
    await expect(screen).toContainText("Starred questions didn’t load — the server reported an error", { timeout: 15_000 });
    await expect(screen).toContainText("Threads didn’t load — the server reported an error", { timeout: 15_000 });
    await expect(page.getByTestId("saved-screens-empty")).toHaveCount(0);          // a failed load is not "nothing saved"
    expect(errors).toEqual([]);
  });
});

// ─────────────────────────────────────────────────────────────────────────
// Phone
// ─────────────────────────────────────────────────────────────────────────

test.describe("Workspace screens — phone (390×844)", () => {
  test.use({ viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true });

  test("Watchlist, Saved and the Screener's save forms fit the phone without sideways page scroll", async ({ page }) => {
    const { errors } = await open(page);
    await threads(page, SV.sessions);

    await page.goto(`${APP}/page/watchlist?wl=all`);
    await expect(page.getByTestId("watchlist-name")).toHaveText([ALPHA, BRAVO, CHARLIE]);
    await page.getByTestId("watchlist-row-toggle").first().click();               // the widest block: a stock's research
    await expect(page.getByTestId("watchlist-detail")).toBeVisible();
    await page.getByTestId("watchlist-screen-toggle").click();
    await expect(page.getByTestId("watchlist-screen-stock")).toHaveCount(2);
    await page.getByTestId("watchlist-strategy-toggle").click();
    await expect(page.getByTestId("watchlist-strategy-stock")).toHaveCount(2);
    await expect(page.getByTestId("watchlist-level")).toHaveCount(2);
    await expect(page.getByTestId("watchlist-alert")).toHaveCount(4);
    expect(await sideways(page)).toEqual({ doc: 0, scroll: 0 });
    // The levels table is wider than the phone and scrolls inside its own box.
    expect(await page.getByTestId("watchlist-levels").locator('[role="table"]').evaluate((el) => el.scrollWidth > el.clientWidth)).toBe(true);

    await page.goto(`${APP}/page/saved`);
    await expect(page.getByTestId("saved-thread-title")).toHaveCount(2);
    await expect(page.getByTestId("saved-strategy-title")).toHaveCount(1);
    await expect(page.getByTestId("saved-question-title")).toHaveCount(1);
    expect(await sideways(page)).toEqual({ doc: 0, scroll: 0 });

    await page.goto(`${APP}/tool/screener`);
    await page.getByTestId("screener-strategy-template").first().click();
    await expect(page.getByTestId("screener-strategy-watchlist-name")).toBeVisible();
    await page.getByTestId("screener-rule-value").nth(1).fill("15");
    await page.getByTestId("screener-run").click();
    await expect(page.getByTestId("screener-watchlist-name")).toBeVisible();
    expect(await sideways(page)).toEqual({ doc: 0, scroll: 0 });
    expect(errors).toEqual([]);
  });
});

/**
 * MOCK — not real data: an invented Kite live snapshot (stream and polling) with one quote per symbol given.
 * Shape: backend/routes/live_quotes.py. `mode` is the feed's own word: only "live" shows live prices.
 */
async function liveFeed(page: Page, ltps: Record<string, number>, mode = "live") {
  const quotes = Object.fromEntries(Object.entries(ltps).map(([s, ltp]) => [s, { ltp, change: 1.5, change_pct: 1.5, open: ltp, high: ltp, low: ltp, close: ltp - 1.5, volume: 1000, oi: null, ts: "2026-10-23T11:13:09+05:30" }]));
  const snapshot = {
    as_of: "2026-10-23T05:43:10+00:00", data_at: "2026-10-23T05:43:09+00:00", age_seconds: 1.2, stale: mode !== "live", stale_after_seconds: 75, cadence_seconds: 30,
    mode, session: mode === "live" ? "open" : "closed", source: "ws", final: false, count: Object.keys(quotes).length, missing: [], quotes, read_only: true,
  };
  await page.route("**/api/live/**", (route) => route.fulfill(
    new URL(route.request().url()).pathname.endsWith("/stream")
      ? { status: 200, contentType: "text/event-stream", body: `retry: 100\n\nevent: snapshot\ndata: ${JSON.stringify(snapshot)}\n\n` }
      : { status: 200, contentType: "application/json", body: JSON.stringify(snapshot) }));
}

test.describe("Watchlist — price levels · live price", () => {
  test("a Live column appears only while the feed is live; a stock Kite has no quote for shows —", async ({ page }) => {
    await open(page);
    await liveFeed(page, { FIXALPHA: 512.25 });
    await page.goto(`${APP}/page/watchlist?wl=all`);
    const cells = page.getByTestId("watchlist-level-live");
    await expect(cells).toHaveCount(2);
    await expect(cells.nth(0)).toHaveText("₹512.25");
    await expect(cells.nth(1)).toHaveText("—");
    await expect(page.getByTestId("watchlist-levels")).toContainText("Live · Kite");
  });

  test("no Live column when the feed is closed", async ({ page }) => {
    await open(page);
    await liveFeed(page, { FIXALPHA: 512.25 }, "closed");
    await page.goto(`${APP}/page/watchlist?wl=all`);
    await expect(page.getByTestId("watchlist-levels")).toContainText("Level to cross");
    await expect(page.getByTestId("watchlist-level-live")).toHaveCount(0);
  });
});

/**
 * MOCK — not real data: the feed's final snapshot after a close (mode "closed", final true), invented prices, every quote
 * stamped with the trading `day`. A day far in the future stands for "newer than the end-of-day data on the screen", a day
 * far in the past for "the end-of-day data has caught up". Shape: backend/routes/live_quotes.py.
 */
async function closeFeed(page: Page, quotes: Record<string, Record<string, unknown>>, day: string) {
  const full = Object.fromEntries(Object.entries(quotes).map(([s, q]) => [s, { change: 1.5, change_pct: 1.5, open: 1, high: 1, low: 1, close: 1, volume: 1000, oi: null, ...q, ts: `${day}T15:29:58+05:30` }]));
  const snapshot = {
    as_of: `${day}T10:01:10+00:00`, data_at: `${day}T10:00:10+00:00`, age_seconds: 5, stale: false, stale_after_seconds: 75, cadence_seconds: 30,
    mode: "closed", session: "closed", source: "rest", final: true, count: Object.keys(full).length, missing: [], quotes: full, read_only: true,
  };
  await page.route("**/api/live/**", (route) => route.fulfill(
    new URL(route.request().url()).pathname.endsWith("/stream")
      ? { status: 200, contentType: "text/event-stream", body: `retry: 100\n\nevent: snapshot\ndata: ${JSON.stringify(snapshot)}\n\n` }
      : { status: 200, contentType: "application/json", body: JSON.stringify(snapshot) }));
}
const NEWER = "2026-12-31";
const OLDER = "2020-01-02";

test.describe("Watchlist — price levels · Kite's close", () => {
  test("after the close a Close · Kite column shows while the scanner's day is older", async ({ page }) => {
    await open(page);
    await closeFeed(page, { FIXALPHA: { ltp: 512.25 } }, NEWER);
    await page.goto(`${APP}/page/watchlist?wl=all`);
    await expect(page.getByTestId("watchlist-levels")).toContainText("Close · Kite");
    await expect(page.getByTestId("watchlist-level-live").nth(0)).toHaveText("₹512.25");
    await expect(page.getByTestId("watchlist-level-live").nth(1)).toHaveText("—");
  });

  test("no extra column once the scanner's day has caught up", async ({ page }) => {
    await open(page);
    await closeFeed(page, { FIXALPHA: { ltp: 512.25 } }, OLDER);
    await page.goto(`${APP}/page/watchlist?wl=all`);
    await expect(page.getByTestId("watchlist-levels")).toContainText("Level to cross");
    await expect(page.getByTestId("watchlist-level-live")).toHaveCount(0);
  });
});
