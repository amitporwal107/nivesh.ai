/**
 * One-screen Copilot app — "Your lists" on the Watchlist screen: the user's own
 * watchlists (screens/workspace/PersonalLists.tsx, personal-lists.ts).
 *
 * MOCK — not real data: every /api/* answer below is a route mock, and no write
 * reaches a server. `watchlistServer` stands in for backend/routes/watchlists.py:
 * it keeps lists in memory and answers in that route's shapes and with its
 * rules (one example list per user, names unique whatever their case, the two
 * limits, a duplicate add answered as a no-op), as read from that file. The
 * fixtures (e2e/fixtures/copilot-watchlists-*.json) are made-up companies,
 * symbols and prices. Expected values are worked out from the fixtures, not
 * copied from the screen.
 *
 * What this proves is the screen against that contract. It does not prove the
 * route: backend/tests/test_watchlists.py does that, against a fake store.
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

const STORE = load("copilot-watchlists-store.json");            // limits, the example list, quotes, the symbol master
const MINE = load("copilot-watchlists-lists.json");             // two lists of a user who already has lists
const RW = load("copilot-workspace-research-watchlist.json");   // GET /api/public/research-watchlist
const SB = load("copilot-workspace-strategy-builder.json");     // /api/strategy-builder/*
const WX = load("copilot-workspace-alerts-levels.json");        // GET /api/filings/alerts, GET /api/positional/watchlist
const SV = load("copilot-workspace-saved.json");                // /api/screeners

const BANKS = "wl_fixturebanks";       // five stocks, one of each kind of quote
const READ_UP = "wl_fixturereadup";    // no stocks
const STARTER_NOTE = "Example list, copied from the research watchlist of 12 Oct 2026. It is yours to edit or delete. A research list is not a recommendation.";

const reply = (route: Route, body: unknown, status = 200) =>
  route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
const json = (page: Page, pattern: string | RegExp, body: unknown, status = 200) =>
  page.route(pattern, (route) => reply(route, body, status));

// ── the stand-in for backend/routes/watchlists.py ────────────────────────

interface Entry { symbol: string; company_name: string | null; added_at: string }
interface Stored {
  watchlist_id: string; name: string; is_starter: boolean; seeded_from: string | null;
  created_at: string; updated_at: string; stocks: Entry[];
}
type Op = "index" | "create" | "starter" | "detail" | "rename" | "delete" | "add" | "remove";

interface Server {
  lists: Stored[];
  /** The never-again marker: this user has had a list. */
  hadList: boolean;
  researchPublished: boolean;
  quotes: Record<string, unknown>;
  /** Answer this operation with a refusal, and change nothing. */
  refuse: Partial<Record<Op, { status: number; detail: string }>>;
  /** Answer this operation 200 with this body (for a body in the wrong shape). */
  body: Partial<Record<Op, unknown>>;
  /** Wait for this before answering the operation. */
  hold: Partial<Record<Op, Promise<void>>>;
  /** "METHOD /path" of every request, in order. */
  calls: string[];
  /** The body of every write, in order. */
  sent: Array<{ op: Op; body: unknown }>;
}

const NOW = "2026-10-13T10:00:00+00:00";
const summary = (l: Stored) => ({
  watchlist_id: l.watchlist_id, name: l.name, symbol_count: l.stocks.length, is_starter: l.is_starter,
  seeded_from: l.seeded_from, created_at: l.created_at, updated_at: l.updated_at,
});
const cleanName = (raw: unknown) => String(raw ?? "").split(/\s+/).filter(Boolean).join(" ");

function opOf(method: string, parts: string[]): Op | null {
  if (parts.length === 0) return method === "GET" ? "index" : method === "POST" ? "create" : null;
  if (parts.length === 1 && parts[0] === "starter") return method === "POST" ? "starter" : null;
  if (parts.length === 1) return method === "GET" ? "detail" : method === "PATCH" ? "rename" : method === "DELETE" ? "delete" : null;
  if (parts.length === 2 && parts[1] === "symbols" && method === "POST") return "add";
  if (parts.length === 3 && parts[1] === "symbols" && method === "DELETE") return "remove";
  return null;
}

async function watchlistServer(page: Page, start: { lists?: Stored[]; hadList?: boolean } = {}): Promise<Server> {
  const s: Server = {
    lists: structuredClone(start.lists ?? []),
    hadList: start.hadList ?? (start.lists?.length ?? 0) > 0,
    researchPublished: true,
    quotes: structuredClone(STORE.quotes),
    refuse: {}, body: {}, hold: {}, calls: [], sent: [],
  };
  let made = 0;

  await page.route(/\/api\/watchlists(?:[/?]|$)/, async (route) => {
    const req = route.request();
    const url = new URL(req.url());
    const parts = (url.pathname.split("/api/watchlists")[1] ?? "").split("/").filter(Boolean).map(decodeURIComponent);
    const op = opOf(req.method(), parts);
    s.calls.push(`${req.method()} ${url.pathname}`);
    if (!op) return reply(route, { detail: "Not Found" }, 404);
    const sent = req.postDataJSON() as { name?: unknown; symbol?: unknown } | null;
    if (req.method() !== "GET") s.sent.push({ op, body: sent });
    if (s.hold[op]) await s.hold[op];
    const refusal = s.refuse[op];
    if (refusal) return reply(route, { detail: refusal.detail }, refusal.status);
    if (op in s.body) return reply(route, s.body[op]);

    if (op === "index") {
      return reply(route, { lists: s.lists.map(summary), limits: STORE.limits, starter_pending: s.lists.length === 0 && !s.hadList });
    }
    if (op === "starter") {
      if (s.hadList || s.lists.length > 0) return reply(route, { created: false, reason: "already_had_a_list", watchlist: null });
      if (!s.researchPublished) return reply(route, { created: false, reason: "no_research_list", watchlist: null });
      const starter: Stored = {
        watchlist_id: "wl_fixturestarter", name: STORE.starter.name, is_starter: true, seeded_from: STORE.starter.seeded_from,
        created_at: NOW, updated_at: NOW,
        stocks: STORE.starter.stocks.map((x: { symbol: string; company_name: string }) => ({ ...x, added_at: NOW })),
      };
      s.lists.push(starter);
      s.hadList = true;
      return reply(route, { created: true, reason: null, watchlist: summary(starter) });
    }
    if (op === "create" || op === "rename") {
      const name = cleanName(sent?.name);
      const self = op === "rename" ? s.lists.find((l) => l.watchlist_id === parts[0]) : undefined;
      if (op === "rename" && !self) return reply(route, { detail: "List not found" }, 404);
      if (name.length < 1 || name.length > 60) return reply(route, { detail: "A list name needs 1 to 60 characters." }, 422);
      if (op === "create" && s.lists.length >= STORE.limits.max_lists) return reply(route, { detail: "You can keep up to 20 lists. Delete one to make another." }, 409);
      const clash = s.lists.find((l) => l !== self && l.name.toLowerCase() === name.toLowerCase());
      if (clash) return reply(route, { detail: `You already have a list called “${clash.name}”.` }, 409);
      if (self) {
        self.name = name;
        self.updated_at = NOW;
        return reply(route, summary(self));
      }
      made += 1;
      const fresh: Stored = { watchlist_id: `wl_made${made}`, name, is_starter: false, seeded_from: null, created_at: NOW, updated_at: NOW, stocks: [] };
      s.lists.push(fresh);
      s.hadList = true;
      return reply(route, summary(fresh));
    }

    const list = s.lists.find((l) => l.watchlist_id === parts[0]);
    if (!list) return reply(route, { detail: "List not found" }, 404);
    if (op === "detail") {
      const stocks = list.stocks.map((e) => ({ ...e, quote: s.quotes[e.symbol] ?? null }));
      const kind = (live: boolean) => stocks.filter((x) => x.quote && (x.quote as { is_live: boolean }).is_live === live).length;
      return reply(route, {
        ...summary(list), stocks,
        quotes: { live: kind(true), stored: kind(false), none: stocks.filter((x) => !x.quote).length, live_source: "yahoo_finance", stored_source: "nidp.prices_eod" },
      });
    }
    if (op === "delete") {
      s.lists = s.lists.filter((l) => l !== list);
      return reply(route, { status: "deleted", watchlist_id: list.watchlist_id });
    }
    if (op === "add") {
      const symbol = String(sent?.symbol ?? "").trim().toUpperCase();
      const existing = list.stocks.find((e) => e.symbol === symbol);
      if (existing) return reply(route, { added: false, reason: "already_in_list", stock: existing, watchlist: summary(list) });
      if (list.stocks.length >= STORE.limits.max_symbols) return reply(route, { detail: "A list holds up to 100 stocks. Remove one to add another." }, 409);
      // Known to the symbol master, or published in a research list (the route accepts either).
      const known: string | undefined =
        (STORE.companies as Array<{ symbol: string; name: string }>).find((c) => c.symbol === symbol)?.name
        ?? (RW.latest.items as Array<{ symbol: string; company_name: string }>).find((p) => p.symbol === symbol)?.company_name;
      if (known === undefined) return reply(route, { detail: `“${symbol}” is not a stock in the instrument list.` }, 422);
      const entry: Entry = { symbol, company_name: known, added_at: NOW };
      list.stocks.push(entry);
      list.updated_at = NOW;
      return reply(route, { added: true, reason: null, stock: entry, watchlist: summary(list) });
    }
    const symbol = (parts[2] ?? "").toUpperCase();
    const before = list.stocks.length;
    list.stocks = list.stocks.filter((e) => e.symbol !== symbol);
    return reply(route, { removed: list.stocks.length < before, symbol, watchlist: summary(list) });
  });
  return s;
}

/** Something a test can hold a request on, then let go. */
function gate() {
  let open!: () => void;
  const wait = new Promise<void>((resolve) => { open = resolve; });
  return { wait, open };
}

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
 * The Watchlist screen with every call answered: the other sections from the
 * workspace fixtures, the user's lists from the stand-in. With no `start` the
 * user has never had a list.
 */
async function open(page: Page, start: { lists?: Stored[]; hadList?: boolean } = {}) {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await mockApi(page, "populated");
  const asked = await mockAsk(page);
  await page.route("**/api/public/research-watchlist*", (route) =>
    reply(route, new URL(route.request().url()).searchParams.get("date") === "2026-10-05" ? RW.earlier : RW.latest));
  await json(page, "**/api/screeners", SV.screeners);
  await json(page, "**/api/strategy-builder/strategies", SB.strategies);
  await json(page, "**/api/filings/alerts", WX.alerts);
  await json(page, "**/api/positional/watchlist*", WX.levels);
  // GET /api/filings/companies/search — the symbol master behind "Add a stock".
  const search = { fail: false, asked: [] as string[] };
  await page.route("**/api/filings/companies/search*", (route) => {
    const q = (new URL(route.request().url()).searchParams.get("q") ?? "").toUpperCase();
    search.asked.push(q);
    if (search.fail) return reply(route, { detail: "boom" }, 500);
    const hits = (STORE.companies as Array<{ symbol: string; name: string }>).filter((c) => c.symbol.includes(q) || c.name.toUpperCase().includes(q));
    return reply(route, { ok: true, companies: hits });
  });
  const server = await watchlistServer(page, start);
  return { server, asked, errors, search };
}

const mine = (): { lists: Stored[] } => ({ lists: structuredClone(MINE.lists) });
const starterCalls = (s: Server) => s.calls.filter((c) => c === "POST /api/watchlists/starter").length;
const writes = (s: Server) => s.calls.filter((c) => !c.startsWith("GET "));
const tabNames = (page: Page) => page.getByTestId("mylist-tab-name");
const tab = (page: Page, name: string) => page.getByTestId("mylist-tab").filter({ hasText: name });
const tabById = (page: Page, id: string) => page.locator(`[data-testid="mylist-tab"][data-list-id="${id}"]`);
const stock = (page: Page, symbol: string) => page.locator(`[data-testid="mylist-stock"][data-symbol="${symbol}"]`);
/** A name cell's text: the icon's monogram (the symbol's first two characters), then each line of the name. */
const nameCell = (symbol: string, ...lines: string[]) => `${symbol.replace(/[^A-Z0-9]/g, "").slice(0, 2)}${lines.join("")}`;
const symbolsShown = (page: Page) => page.getByTestId("mylist-stock").evaluateAll((els) => els.map((e) => e.getAttribute("data-symbol")));

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
// The example list
// ─────────────────────────────────────────────────────────────────────────

test.describe("Your lists — the example list", () => {
  test("a first visit makes the example list once, says where it came from, and prices each stock", async ({ page }) => {
    const { server, asked, errors } = await open(page);
    await page.goto(`${APP}/page/watchlist`);

    await expect(tabNames(page)).toHaveText(["Multibagger"]);
    expect(starterCalls(server)).toBe(1);
    expect(server.sent).toEqual([{ op: "starter", body: null }]);
    await expect(page.getByTestId("mylists-count")).toHaveText("Your lists · 1 of 20");
    await expect(page.getByTestId("mylist-tab-count")).toHaveText(["3"]);
    await expect(tab(page, "Multibagger")).toHaveAttribute("aria-selected", "true");

    const panel = page.getByTestId("mylist-open");
    await expect(panel.getByTestId("mylist-name")).toHaveText("Multibagger");
    await expect(panel.locator(".cp-pill", { hasText: /^Example$/ })).toBeVisible();
    await expect(page.getByTestId("mylist-starter-note")).toHaveText(STARTER_NOTE);
    await expect(page.getByTestId("mylist-size")).toHaveText("3 stocks of 100");

    // The research list's three stocks, in its order, each with its icon, name and symbol.
    expect(await symbolsShown(page)).toEqual(["FIXALPHA", "FIXBRAVO", "FIXCHARLIE"]);
    expect(await iconKeys(page.getByTestId("mylist-stocks"))).toEqual(["FIXALPHA", "FIXBRAVO", "FIXCHARLIE"]);
    await expect(page.getByTestId("mylist-stock-name")).toHaveText([
      nameCell("FIXALPHA", "Fixture Alpha Industries Ltd", "FIXALPHA"),
      nameCell("FIXBRAVO", "Fixture Bravo Pharma Ltd", "FIXBRAVO"),
      nameCell("FIXCHARLIE", "Fixture Charlie Power Ltd", "FIXCHARLIE"),
    ]);
    // Alpha: live 213.00, +2.50 (+1.19%). Bravo: live, down 6.00 (−1.23%).
    await expect(stock(page, "FIXALPHA").getByTestId("mylist-price")).toHaveText("₹213.00");
    await expect(stock(page, "FIXALPHA").getByTestId("mylist-change")).toHaveText("+1.19%");
    await expect(stock(page, "FIXALPHA")).toContainText("+₹2.50");
    await expect(stock(page, "FIXALPHA").getByTestId("mylist-stored")).toHaveCount(0);
    await expect(stock(page, "FIXBRAVO").getByTestId("mylist-change")).toHaveText("−1.23%");
    await expect(stock(page, "FIXBRAVO")).toContainText("−₹6.00");
    // Charlie: no live quote, so the stored close of 10 Oct and that day's move.
    await expect(stock(page, "FIXCHARLIE").getByTestId("mylist-price")).toHaveText("₹75.40");
    await expect(stock(page, "FIXCHARLIE").getByTestId("mylist-stored")).toHaveText("Stored price · 10 Oct");
    await expect(stock(page, "FIXCHARLIE").getByTestId("mylist-change")).toHaveText("+0.67%");
    await expect(page.getByTestId("mylist-quotes")).toContainText("Live prices · 2 of 3");
    await expect(page.getByTestId("mylist-quotes-checked")).toHaveText(/^Fetched \d{1,2}:\d{2}/);
    await expect(panel).toContainText("A list is your own note of stocks to follow, not advice to buy or sell.");

    // The rest of the screen is as it was.
    await expect(page.getByTestId("watchlist-name")).toHaveText(["Fixture Alpha Industries Ltd", "Fixture Bravo Pharma Ltd", "Fixture Charlie Power Ltd"]);

    // Coming back does not make it again: the list is there.
    await page.reload();
    await expect(tabNames(page)).toHaveText(["Multibagger"]);
    await expect(page.getByTestId("mylist-stock")).toHaveCount(3);
    expect(starterCalls(server)).toBe(1);
    expect(writes(server)).toEqual(["POST /api/watchlists/starter"]);

    await stock(page, "FIXBRAVO").getByTestId("mylist-stock-ask").click();
    await expect.poll(() => asked).toEqual(["Tell me about Fixture Bravo Pharma Ltd"]);
    expect(errors).toEqual([]);
  });

  test("deleting the example list asks first, and it is not made again", async ({ page }) => {
    const { server, errors } = await open(page);
    await page.goto(`${APP}/page/watchlist`);
    await expect(tabNames(page)).toHaveText(["Multibagger"]);

    // The first press only asks; "Keep" backs out.
    await page.getByTestId("mylist-delete").click();
    await expect(page.getByTestId("mylist-open")).toContainText("Delete this list and its 3 stocks?");
    await page.getByTestId("mylist-delete-keep").click();
    await expect(page.getByTestId("mylist-delete-confirm")).toHaveCount(0);
    expect(writes(server)).toEqual(["POST /api/watchlists/starter"]);

    await page.getByTestId("mylist-delete").click();
    await page.getByTestId("mylist-delete-confirm").click();
    await expect(page.getByTestId("mylists-empty")).toContainText("You have no lists yet");
    await expect(page.getByTestId("mylists-empty")).toContainText("Make a list, then add the stocks you want to follow.");
    await expect(page.getByTestId("mylists-count")).toHaveText("Your lists · 0 of 20");
    await expect(page.getByTestId("mylist-tab")).toHaveCount(0);
    await expect(page.getByTestId("mylist-open")).toHaveCount(0);
    expect(writes(server)).toEqual(["POST /api/watchlists/starter", "DELETE /api/watchlists/wl_fixturestarter"]);

    await page.reload();
    await expect(page.getByTestId("mylists-empty")).toBeVisible();
    await expect(page.getByTestId("mylist-tab")).toHaveCount(0);
    expect(starterCalls(server)).toBe(1);                                  // not asked for a second time
    expect(errors).toEqual([]);
  });

  test("with no research list published nothing is made and the screen says why; a failed attempt can be tried again", async ({ page }) => {
    const { server, errors } = await open(page);
    server.researchPublished = false;
    await page.goto(`${APP}/page/watchlist`);
    await expect(page.getByTestId("mylists-empty")).toContainText("no research list has been published yet");
    await expect(page.getByTestId("mylists-empty")).toContainText("You can make your own list now.");
    await expect(page.getByTestId("mylist-tab")).toHaveCount(0);
    await expect(page.getByTestId("mylist-new")).toBeEnabled();
    expect(starterCalls(server)).toBe(1);

    server.refuse.starter = { status: 500, detail: "boom" };
    await page.reload();
    await expect(page.getByTestId("mylists-starter-error")).toContainText("Your example list wasn’t made — the server reported an error");
    await expect(page.getByTestId("mylists-empty")).toBeVisible();          // a list can still be made by hand
    await expect(page.getByTestId("mylist-tab")).toHaveCount(0);

    server.researchPublished = true;
    delete server.refuse.starter;
    await page.getByTestId("mylists-starter-error").getByRole("button", { name: "Retry ›" }).click();
    await expect(tabNames(page)).toHaveText(["Multibagger"]);
    await expect(page.getByTestId("mylists-starter-error")).toHaveCount(0);
    await expect(page.getByTestId("mylist-starter-note")).toHaveText(STARTER_NOTE);
    expect(errors).toEqual([]);
  });

  test("a user who has had a list before is not given the example, and an empty answer is not an error", async ({ page }) => {
    const { server, errors } = await open(page, { lists: [], hadList: true });
    await page.goto(`${APP}/page/watchlist`);
    await expect(page.getByTestId("mylists-empty")).toContainText("You have no lists yet");
    await expect(page.getByTestId("mylists-count")).toHaveText("Your lists · 0 of 20");
    await expect(page.getByTestId("mylists-error")).toHaveCount(0);
    await expect(page.getByTestId("watchlist-name")).toHaveCount(3);          // the page has settled
    expect(writes(server)).toEqual([]);
    expect(errors).toEqual([]);
  });
});

// ─────────────────────────────────────────────────────────────────────────
// Lists: create, rename, delete
// ─────────────────────────────────────────────────────────────────────────

test.describe("Your lists — create, rename, delete", () => {
  test("a list is made, renamed and deleted, each shown only once the server has it", async ({ page }) => {
    const { server, errors } = await open(page, mine());
    await page.goto(`${APP}/page/watchlist`);
    await expect(tabNames(page)).toHaveText(["Fixture banks", "Fixture to read up on"]);
    await expect(page.getByTestId("mylist-tab-count")).toHaveText(["5", "0"]);
    await expect(page.getByTestId("mylist-name")).toHaveText("Fixture banks");       // the first list is open
    await expect(page.getByTestId("mylist-starter-note")).toHaveCount(0);            // an ordinary list carries no example note

    // Create: the name is needed, and the request is held to show nothing is drawn early.
    await page.getByTestId("mylist-new").click();
    await expect(page.getByTestId("mylist-new-save")).toBeDisabled();
    await page.getByTestId("mylist-new-name").fill("  Fixture energy  ");
    const making = gate();
    server.hold.create = making.wait;
    await page.getByTestId("mylist-new-save").click();
    await expect(page.getByTestId("mylist-new-save")).toHaveText("Making…");
    await expect(tabNames(page)).toHaveText(["Fixture banks", "Fixture to read up on"]);
    making.open();
    delete server.hold.create;
    await expect(tabNames(page)).toHaveText(["Fixture banks", "Fixture to read up on", "Fixture energy"]);
    await expect(tab(page, "Fixture energy")).toHaveAttribute("aria-selected", "true");   // the new list opens
    await expect(page.getByTestId("mylist-name")).toHaveText("Fixture energy");
    await expect(page.getByTestId("mylist-size")).toHaveText("0 stocks of 100");
    await expect(page.getByTestId("mylist-empty")).toHaveText("No stocks in this list yet. Search above to add one.");
    await expect(page.getByTestId("mylists-count")).toHaveText("Your lists · 3 of 20");
    await expect(page.getByTestId("mylist-new-form")).toHaveCount(0);

    // Rename: starts from the current name; an unchanged name cannot be saved.
    await page.getByTestId("mylist-rename").click();
    await expect(page.getByTestId("mylist-rename-name")).toHaveValue("Fixture energy");
    await expect(page.getByTestId("mylist-rename-save")).toBeDisabled();
    await page.getByTestId("mylist-rename-name").fill("Fixture power");
    await page.getByTestId("mylist-rename-save").click();
    await expect(page.getByTestId("mylist-name")).toHaveText("Fixture power");
    await expect(tabNames(page)).toHaveText(["Fixture banks", "Fixture to read up on", "Fixture power"]);
    await expect(page.getByTestId("mylist-rename-form")).toHaveCount(0);

    // Delete asks first; afterwards the first list is the open one.
    await page.getByTestId("mylist-delete").click();
    await expect(page.getByTestId("mylist-open")).toContainText("Delete this list and its 0 stocks?");
    await page.getByTestId("mylist-delete-confirm").click();
    await expect(tabNames(page)).toHaveText(["Fixture banks", "Fixture to read up on"]);
    await expect(page.getByTestId("mylist-name")).toHaveText("Fixture banks");
    await expect(page.getByTestId("mylists-count")).toHaveText("Your lists · 2 of 20");

    expect(server.sent).toEqual([
      { op: "create", body: { name: "Fixture energy" } },
      { op: "rename", body: { name: "Fixture power" } },
      { op: "delete", body: null },
    ]);
    expect(writes(server)).toEqual(["POST /api/watchlists", "PATCH /api/watchlists/wl_made1", "DELETE /api/watchlists/wl_made1"]);
    expect(starterCalls(server)).toBe(0);
    expect(errors).toEqual([]);
  });

  test("switching lists shows that list's stocks", async ({ page }) => {
    const { errors } = await open(page, mine());
    await page.goto(`${APP}/page/watchlist`);
    await expect(page.getByTestId("mylist-stock")).toHaveCount(5);
    await tab(page, "Fixture to read up on").click();
    await expect(page.getByTestId("mylist-name")).toHaveText("Fixture to read up on");
    await expect(page.getByTestId("mylist-empty")).toBeVisible();
    await expect(page.getByTestId("mylist-stock")).toHaveCount(0);
    await expect(page.getByTestId("mylist-quotes")).toHaveCount(0);              // no prices line for an empty list
    await tab(page, "Fixture banks").click();
    await expect(page.getByTestId("mylist-stock")).toHaveCount(5);
    expect(errors).toEqual([]);
  });

  test("a refused or failed list write is said beside its control and changes nothing", async ({ page }) => {
    const { server, errors } = await open(page, mine());
    await page.goto(`${APP}/page/watchlist`);
    await expect(tabNames(page)).toHaveText(["Fixture banks", "Fixture to read up on"]);

    // A name already used, whatever its case: the route's own sentence is shown.
    await page.getByTestId("mylist-new").click();
    await page.getByTestId("mylist-new-name").fill("fixture BANKS");
    await page.getByTestId("mylist-new-save").click();
    await expect(page.getByTestId("mylist-new-error")).toContainText("The list wasn’t made, so nothing changed — You already have a list called “Fixture banks”.");
    await expect(page.getByTestId("mylist-new-name")).toHaveValue("fixture BANKS");   // the form keeps what was typed
    await expect(tabNames(page)).toHaveText(["Fixture banks", "Fixture to read up on"]);

    // The server fails outright.
    server.refuse.create = { status: 500, detail: "boom" };
    await page.getByTestId("mylist-new-name").fill("Fixture energy");
    await page.getByTestId("mylist-new-save").click();
    await expect(page.getByTestId("mylist-new-error")).toContainText("The list wasn’t made, so nothing changed — the server reported an error");
    await expect(tabNames(page)).toHaveText(["Fixture banks", "Fixture to read up on"]);
    await page.getByTestId("mylist-new-cancel").click();
    await expect(page.getByTestId("mylist-new-form")).toHaveCount(0);

    // Rename to the other list's name, then a failed rename.
    await page.getByTestId("mylist-rename").click();
    await page.getByTestId("mylist-rename-name").fill("Fixture to read up on");
    await page.getByTestId("mylist-rename-save").click();
    await expect(page.getByTestId("mylist-rename-error")).toContainText("The name wasn’t changed — You already have a list called “Fixture to read up on”.");
    await expect(tabNames(page)).toHaveText(["Fixture banks", "Fixture to read up on"]);
    server.refuse.rename = { status: 500, detail: "boom" };
    await page.getByTestId("mylist-rename-name").fill("Fixture lenders");
    await page.getByTestId("mylist-rename-save").click();
    await expect(page.getByTestId("mylist-rename-error")).toContainText("The name wasn’t changed — the server reported an error");
    await expect(page.getByTestId("mylist-rename-name")).toHaveValue("Fixture lenders");
    await page.getByTestId("mylist-rename-cancel").click();
    await expect(page.getByTestId("mylist-name")).toHaveText("Fixture banks");
    await expect(page.getByTestId("mylist-rename-error")).toHaveCount(0);

    // A failed delete leaves the list and its stocks.
    server.refuse.delete = { status: 500, detail: "boom" };
    await page.getByTestId("mylist-delete").click();
    await page.getByTestId("mylist-delete-confirm").click();
    await expect(page.getByTestId("mylist-delete-error")).toContainText("The list wasn’t deleted — the server reported an error");
    await expect(tabNames(page)).toHaveText(["Fixture banks", "Fixture to read up on"]);
    await expect(page.getByTestId("mylist-stock")).toHaveCount(5);
    expect(server.lists.map((l) => l.name)).toEqual(["Fixture banks", "Fixture to read up on"]);
    expect(errors).toEqual([]);
  });
});

// ─────────────────────────────────────────────────────────────────────────
// Stocks in a list
// ─────────────────────────────────────────────────────────────────────────

test.describe("Your lists — stocks", () => {
  test("each stock shows a live price, a stored price with its date, or that there is no quote", async ({ page }) => {
    const { errors } = await open(page, mine());
    await page.goto(`${APP}/page/watchlist`);
    await expect(page.getByTestId("mylist-stock")).toHaveCount(5);
    expect(await symbolsShown(page)).toEqual(["FIXALPHA", "FIXCHARLIE", "FIXDELTA", "FIXECHO", "FIXNAMELESS"]);
    expect(await iconKeys(page.getByTestId("mylist-stocks"))).toEqual(["FIXALPHA", "FIXCHARLIE", "FIXDELTA", "FIXECHO", "FIXNAMELESS"]);
    await expect(page.getByTestId("mylist-size")).toHaveText("5 stocks of 100");

    // Live: price and today's move, no "stored" tag.
    await expect(stock(page, "FIXALPHA").getByTestId("mylist-price")).toHaveText("₹213.00");
    await expect(stock(page, "FIXALPHA").getByTestId("mylist-change")).toHaveText("+1.19%");
    await expect(stock(page, "FIXALPHA").getByTestId("mylist-stored")).toHaveCount(0);
    // Stored, with the move of that day.
    await expect(stock(page, "FIXCHARLIE").getByTestId("mylist-stored")).toHaveText("Stored price · 10 Oct");
    await expect(stock(page, "FIXCHARLIE").getByTestId("mylist-change")).toHaveText("+0.67%");
    // No quote at all: the words, and no figure — never a zero.
    await expect(stock(page, "FIXDELTA").getByTestId("mylist-noquote")).toHaveText("No quote today");
    await expect(stock(page, "FIXDELTA").getByTestId("mylist-price")).toHaveCount(0);
    await expect(stock(page, "FIXDELTA").getByTestId("mylist-change")).toHaveCount(0);
    await expect(stock(page, "FIXDELTA")).not.toContainText("₹");
    // Stored, with no previous close to measure a move from.
    await expect(stock(page, "FIXECHO").getByTestId("mylist-price")).toHaveText("₹1,520.00");
    await expect(stock(page, "FIXECHO").getByTestId("mylist-stored")).toHaveText("Stored price · 12 Oct");
    await expect(stock(page, "FIXECHO").getByTestId("mylist-change")).toHaveCount(0);
    // No company name on record: the symbol stands alone, and is not repeated.
    await expect(stock(page, "FIXNAMELESS").getByTestId("mylist-stock-name")).toHaveText(nameCell("FIXNAMELESS", "FIXNAMELESS"));
    await expect(stock(page, "FIXNAMELESS").getByTestId("mylist-noquote")).toBeVisible();

    await expect(page.getByTestId("mylist-quotes")).toContainText("Live prices · 1 of 5");
    expect(errors).toEqual([]);
  });

  test("the prices line says when none of the prices are live, and when there are none", async ({ page }) => {
    const { server, errors } = await open(page, mine());
    server.quotes.FIXALPHA = { price: 210.5, day_change: 1.5, day_change_pct: 0.72, as_of: "2026-10-12", is_live: false };
    await page.goto(`${APP}/page/watchlist`);
    await expect(page.getByTestId("mylist-quotes")).toContainText("Last stored prices");
    await expect(page.getByTestId("mylist-quotes-checked")).toHaveCount(0);
    await expect(stock(page, "FIXALPHA").getByTestId("mylist-stored")).toHaveText("Stored price · 12 Oct");

    server.quotes = {};
    await page.reload();
    await expect(page.getByTestId("mylist-noquote")).toHaveCount(5);
    await expect(page.getByTestId("mylist-quotes")).toContainText("No prices today");
    await expect(page.getByTestId("mylist-price")).toHaveCount(0);
    expect(errors).toEqual([]);
  });

  test("add a stock: the symbol master is searched, and the stock appears only after the server has it", async ({ page }) => {
    const { server, search, errors } = await open(page, mine());
    await page.goto(`${APP}/page/watchlist`);
    await tab(page, "Fixture to read up on").click();
    await expect(page.getByTestId("mylist-empty")).toBeVisible();

    const box = page.getByTestId("mylist-add-search");
    await box.fill("d");                                                    // one letter asks nothing
    await expect(page.getByTestId("mylist-add-results")).toHaveCount(0);
    await box.fill("delta");
    const hit = page.getByTestId("mylist-add-result");
    await expect(hit).toHaveCount(1);
    await expect(hit).toContainText("Fixture Delta Finance Limited");
    await expect(hit).toContainText("FIXDELTA · Finance");
    expect(await iconKeys(page.getByTestId("mylist-add-results"))).toEqual(["FIXDELTA"]);
    expect(search.asked).toEqual(["DELTA"]);

    const adding = gate();
    server.hold.add = adding.wait;
    await hit.click();
    await expect(hit).toContainText("Adding…");
    await expect(page.getByTestId("mylist-stock")).toHaveCount(0);          // not drawn ahead of the server
    await expect(tab(page, "Fixture to read up on").getByTestId("mylist-tab-count")).toHaveText("0");
    adding.open();
    delete server.hold.add;

    await expect(page.getByTestId("mylist-add-done")).toHaveText("Added Fixture Delta Finance Limited to Fixture to read up on.");
    expect(await symbolsShown(page)).toEqual(["FIXDELTA"]);
    await expect(stock(page, "FIXDELTA").getByTestId("mylist-stock-name")).toHaveText(nameCell("FIXDELTA", "Fixture Delta Finance Limited", "FIXDELTA"));
    await expect(stock(page, "FIXDELTA").getByTestId("mylist-noquote")).toHaveText("No quote today");
    await expect(tab(page, "Fixture to read up on").getByTestId("mylist-tab-count")).toHaveText("1");
    await expect(page.getByTestId("mylist-size")).toHaveText("1 stock of 100");
    await expect(box).toHaveValue("");                                      // ready for the next one
    await expect(page.getByTestId("mylist-add-results")).toHaveCount(0);

    // A symbol with "&" in it goes out and comes back whole.
    await box.fill("fox");
    await expect(page.getByTestId("mylist-add-done")).toHaveCount(0);       // a new search clears the last result line
    await page.getByTestId("mylist-add-result").click();
    await expect(page.getByTestId("mylist-add-done")).toHaveText("Added Fixture & Fox Retail Limited to Fixture to read up on.");
    expect(await symbolsShown(page)).toEqual(["FIXDELTA", "FIX&FOX"]);
    await expect(stock(page, "FIX&FOX").getByTestId("mylist-price")).toHaveText("₹64.25");
    await expect(stock(page, "FIX&FOX").getByTestId("mylist-change")).toHaveText("0.00%");   // a real, unchanged quote

    expect(server.sent).toEqual([{ op: "add", body: { symbol: "FIXDELTA" } }, { op: "add", body: { symbol: "FIX&FOX" } }]);
    expect(writes(server)).toEqual([`POST /api/watchlists/${READ_UP}/symbols`, `POST /api/watchlists/${READ_UP}/symbols`]);
    expect(errors).toEqual([]);
  });

  test("an add that is refused, fails or finds the stock already there says so and changes nothing", async ({ page }) => {
    const { server, search, errors } = await open(page, mine());
    await page.goto(`${APP}/page/watchlist`);
    await expect(page.getByTestId("mylist-stock")).toHaveCount(5);
    const box = page.getByTestId("mylist-add-search");

    // A stock already in the open list is marked, and cannot be pressed.
    await box.fill("alpha");
    await expect(page.getByTestId("mylist-add-result")).toContainText("In this list");
    await expect(page.getByTestId("mylist-add-result")).toBeDisabled();

    // The server does not know the symbol (the master changed under the search).
    server.refuse.add = { status: 422, detail: "“FIXBRAVO” is not a stock in the instrument list." };
    await box.fill("bravo");
    await page.getByTestId("mylist-add-result").click();
    await expect(page.getByTestId("mylist-add-error")).toContainText("FIXBRAVO wasn’t added, so nothing changed — “FIXBRAVO” is not a stock in the instrument list.");
    await expect(page.getByTestId("mylist-add-done")).toHaveCount(0);
    await expect(page.getByTestId("mylist-stock")).toHaveCount(5);
    await expect(box).toHaveValue("bravo");                                 // the search stays, to try again

    // The master could not be asked: the route's sentence is the useful part.
    server.refuse.add = { status: 503, detail: "The instrument list could not be checked just now, so nothing was added. Please try again." };
    await page.getByTestId("mylist-add-result").click();
    await expect(page.getByTestId("mylist-add-error")).toContainText("FIXBRAVO wasn’t added, so nothing changed — The instrument list could not be checked just now, so nothing was added. Please try again.");

    // The list filled up elsewhere.
    server.refuse.add = { status: 409, detail: "A list holds up to 100 stocks. Remove one to add another." };
    await page.getByTestId("mylist-add-result").click();
    await expect(page.getByTestId("mylist-add-error")).toContainText("— A list holds up to 100 stocks. Remove one to add another.");

    server.refuse.add = { status: 500, detail: "boom" };
    await page.getByTestId("mylist-add-result").click();
    await expect(page.getByTestId("mylist-add-error")).toContainText("FIXBRAVO wasn’t added, so nothing changed — the server reported an error");
    await expect(page.getByTestId("mylist-stock")).toHaveCount(5);
    await expect(tab(page, "Fixture banks").getByTestId("mylist-tab-count")).toHaveText("5");

    // Already there (added from another tab since this page loaded): a no-op answer, not an error.
    delete server.refuse.add;
    server.lists[0].stocks.push({ symbol: "FIXBRAVO", company_name: "Fixture Bravo Pharma Limited", added_at: NOW });
    await page.getByTestId("mylist-add-result").click();
    await expect(page.getByTestId("mylist-add-done")).toHaveText("Fixture Bravo Pharma Limited is already in Fixture banks, so nothing changed.");
    await expect(page.getByTestId("mylist-add-error")).toHaveCount(0);
    expect(server.lists[0].stocks.filter((e) => e.symbol === "FIXBRAVO")).toHaveLength(1);
    await expect(page.getByTestId("mylist-stock")).toHaveCount(6);          // the list was read again and now shows it

    // Search states: nothing matches, and the search itself failing.
    await box.fill("zzzz");
    await expect(page.getByTestId("mylist-add-none")).toHaveText("No stock matches “zzzz”. Try the company’s name or its NSE symbol.");
    search.fail = true;
    await box.fill("echo");
    await expect(page.getByTestId("mylist-add-search-error")).toContainText("Search didn’t work — the server reported an error", { timeout: 15_000 });
    search.fail = false;
    await page.getByTestId("mylist-add-search-error").getByRole("button", { name: "Retry ›" }).click();
    await expect(page.getByTestId("mylist-add-result")).toContainText("Fixture Echo Motors Limited");
    expect(errors).toEqual([]);
  });

  test("remove a stock: it goes only after the server has removed it, and a failed remove changes nothing", async ({ page }) => {
    const { server, errors } = await open(page, mine());
    server.lists[0].stocks.push({ symbol: "FIX&FOX", company_name: "Fixture & Fox Retail Limited", added_at: NOW });
    await page.goto(`${APP}/page/watchlist`);
    await expect(page.getByTestId("mylist-stock")).toHaveCount(6);

    const removing = gate();
    server.hold.remove = removing.wait;
    await page.getByRole("button", { name: "Remove Fixture Charlie Power Limited from Fixture banks" }).click();
    await expect(page.getByTestId("mylist-remove").first()).toBeDisabled();  // one remove at a time
    await expect(stock(page, "FIXCHARLIE")).toBeVisible();                   // still there while the request is out
    removing.open();
    delete server.hold.remove;
    await expect(stock(page, "FIXCHARLIE")).toHaveCount(0);
    expect(await symbolsShown(page)).toEqual(["FIXALPHA", "FIXDELTA", "FIXECHO", "FIXNAMELESS", "FIX&FOX"]);
    await expect(tab(page, "Fixture banks").getByTestId("mylist-tab-count")).toHaveText("5");
    await expect(page.getByTestId("mylist-size")).toHaveText("5 stocks of 100");

    // "&" travels percent-encoded in the path; a stock with no name is named by its symbol.
    await page.getByRole("button", { name: "Remove Fixture & Fox Retail Limited from Fixture banks" }).click();
    await expect(stock(page, "FIX&FOX")).toHaveCount(0);
    expect(writes(server)).toEqual([`DELETE /api/watchlists/${BANKS}/symbols/FIXCHARLIE`, `DELETE /api/watchlists/${BANKS}/symbols/FIX%26FOX`]);
    await expect(page.getByRole("button", { name: "Remove FIXNAMELESS from Fixture banks" })).toBeVisible();

    server.refuse.remove = { status: 500, detail: "boom" };
    await page.getByRole("button", { name: "Remove Fixture Alpha Industries Limited from Fixture banks" }).click();
    await expect(page.getByTestId("mylist-remove-error")).toContainText("FIXALPHA wasn’t removed, so nothing changed — the server reported an error");
    expect(await symbolsShown(page)).toEqual(["FIXALPHA", "FIXDELTA", "FIXECHO", "FIXNAMELESS"]);
    await expect(tab(page, "Fixture banks").getByTestId("mylist-tab-count")).toHaveText("4");

    delete server.refuse.remove;
    await page.getByRole("button", { name: "Remove Fixture Alpha Industries Limited from Fixture banks" }).click();
    await expect(stock(page, "FIXALPHA")).toHaveCount(0);
    await expect(page.getByTestId("mylist-remove-error")).toHaveCount(0);
    expect(errors).toEqual([]);
  });
});

// ─────────────────────────────────────────────────────────────────────────
// Limits, empty and error states
// ─────────────────────────────────────────────────────────────────────────

test.describe("Your lists — limits and states", () => {
  test("at 20 lists no more can be made, and a list of 100 stocks takes no more", async ({ page }) => {
    // Generated from the fixture's empty list: 20 lists, the first holding 100 made-up stocks.
    const lists: Stored[] = Array.from({ length: 20 }, (_, i) => ({
      ...structuredClone(MINE.lists[1]), watchlist_id: `wl_gen${i + 1}`, name: `Fixture list ${i + 1}`,
    }));
    lists[0].stocks = Array.from({ length: 100 }, (_, i) => ({ symbol: `FIXGEN${i + 1}`, company_name: `Fixture Generated ${i + 1} Limited`, added_at: NOW }));
    const { server, errors } = await open(page, { lists });
    await page.goto(`${APP}/page/watchlist`);

    await expect(page.getByTestId("mylists-count")).toHaveText("Your lists · 20 of 20");
    await expect(page.getByTestId("mylist-tab")).toHaveCount(20);
    await expect(page.getByTestId("mylist-new")).toBeDisabled();
    await expect(page.getByTestId("mylist-limit")).toHaveText("You have 20 lists, the most you can keep. Delete one to make another.");

    await expect(page.getByTestId("mylist-size")).toHaveText("100 stocks of 100");
    await expect(page.getByTestId("mylist-stock")).toHaveCount(100);
    await expect(page.getByTestId("mylist-add-search")).toBeDisabled();
    await expect(page.getByTestId("mylist-full")).toHaveText("This list has 100 stocks, the most a list holds. Remove one to add another.");
    await expect(page.getByTestId("mylist-quotes")).toContainText("No prices today");   // none of the generated symbols has a quote
    await expect(page.getByTestId("mylist-noquote")).toHaveCount(100);

    // Another list still takes stocks, and deleting one frees a place.
    await tabById(page, "wl_gen2").click();
    await expect(page.getByTestId("mylist-name")).toHaveText("Fixture list 2");
    await expect(page.getByTestId("mylist-add-search")).toBeEnabled();
    await expect(page.getByTestId("mylist-full")).toHaveCount(0);
    await page.getByTestId("mylist-delete").click();
    await page.getByTestId("mylist-delete-confirm").click();
    await expect(page.getByTestId("mylists-count")).toHaveText("Your lists · 19 of 20");
    await expect(page.getByTestId("mylist-new")).toBeEnabled();
    await expect(page.getByTestId("mylist-limit")).toHaveCount(0);
    expect(writes(server)).toEqual(["DELETE /api/watchlists/wl_gen2"]);
    expect(errors).toEqual([]);
  });

  test("a limit the screen did not know about is said in the server's words", async ({ page }) => {
    const { server, errors } = await open(page, mine());
    server.refuse.create = { status: 409, detail: "You can keep up to 20 lists. Delete one to make another." };
    await page.goto(`${APP}/page/watchlist`);
    await page.getByTestId("mylist-new").click();
    await page.getByTestId("mylist-new-name").fill("Fixture one too many");
    await page.getByTestId("mylist-new-save").click();
    await expect(page.getByTestId("mylist-new-error")).toContainText("The list wasn’t made, so nothing changed — You can keep up to 20 lists. Delete one to make another.");
    await expect(tabNames(page)).toHaveText(["Fixture banks", "Fixture to read up on"]);
    expect(errors).toEqual([]);
  });

  test("the lists failing to load, loading in the wrong shape, and one list failing are each said, with a retry that works", async ({ page }) => {
    const { server, errors } = await open(page, mine());
    server.refuse.index = { status: 500, detail: "boom" };
    await page.goto(`${APP}/page/watchlist`);
    await expect(page.getByTestId("mylists-error")).toContainText("Your lists didn’t load — the server reported an error", { timeout: 15_000 });
    await expect(page.getByTestId("mylists-count")).toHaveText("Your lists");          // no count is claimed
    await expect(page.getByTestId("mylist-tab")).toHaveCount(0);
    await expect(page.getByTestId("mylists-empty")).toHaveCount(0);                    // a failed load is not "no lists"
    await expect(page.getByTestId("watchlist-add-to-list")).toHaveCount(0);            // nothing to add to
    await expect(page.getByTestId("watchlist-name")).toHaveCount(3);                   // the other sections still load
    delete server.refuse.index;
    await page.getByTestId("mylists-error").getByRole("button", { name: "Retry ›" }).click();
    await expect(tabNames(page)).toHaveText(["Fixture banks", "Fixture to read up on"]);

    // 200 with a body that is not the lists: an error, and the example list is not asked for.
    server.body.index = {};
    await page.reload();
    await expect(page.getByTestId("mylists-error")).toContainText("Your lists didn’t load — the server’s response was not in the expected format");
    delete server.body.index;

    // The lists load, the open list does not.
    server.refuse.detail = { status: 500, detail: "boom" };
    await page.reload();
    await expect(tabNames(page)).toHaveText(["Fixture banks", "Fixture to read up on"]);
    await expect(page.getByTestId("mylist-load-error")).toContainText("This list didn’t load — the server reported an error", { timeout: 15_000 });
    await expect(page.getByTestId("mylist-stock")).toHaveCount(0);
    await expect(page.getByTestId("mylist-empty")).toHaveCount(0);                     // a failed load is not "no stocks"
    await expect(page.getByTestId("mylist-name")).toHaveText("Fixture banks");         // the list can still be renamed or deleted
    delete server.refuse.detail;
    await page.getByTestId("mylist-load-error").getByRole("button", { name: "Retry ›" }).click();
    await expect(page.getByTestId("mylist-stock")).toHaveCount(5);

    server.body.detail = { watchlist_id: BANKS, stocks: "not a list" };
    await page.reload();
    await expect(page.getByTestId("mylist-load-error")).toContainText("This list didn’t load — the server’s response was not in the expected format");
    expect(starterCalls(server)).toBe(0);
    expect(errors).toEqual([]);
  });

  test("a price refresh that fails keeps the list on screen and says the prices may be out of date", async ({ page }) => {
    await page.clock.install();
    const { server, errors } = await open(page, mine());
    await page.goto(`${APP}/page/watchlist`);
    await expect(page.getByTestId("mylist-stock")).toHaveCount(5);
    await expect(stock(page, "FIXALPHA").getByTestId("mylist-price")).toHaveText("₹213.00");
    const reads = () => server.calls.filter((c) => c === `GET /api/watchlists/${BANKS}`).length;
    expect(reads()).toBe(1);

    // The list is read again every 30 seconds: a new price shows without a reload.
    server.quotes.FIXALPHA = { price: 214.1, day_change: 3.6, day_change_pct: 1.71, as_of: "2026-10-13T09:51:00+00:00", is_live: true };
    await page.clock.fastForward(31_000);
    await expect(stock(page, "FIXALPHA").getByTestId("mylist-price")).toHaveText("₹214.10");
    expect(reads()).toBe(2);

    server.refuse.detail = { status: 500, detail: "boom" };
    await page.clock.fastForward(31_000);
    await expect(page.getByTestId("mylist-stale")).toContainText("The prices could not be checked again, so these may be out of date", { timeout: 20_000 });
    await expect(page.getByTestId("mylist-stock")).toHaveCount(5);                     // the last good read stays
    await expect(stock(page, "FIXALPHA").getByTestId("mylist-price")).toHaveText("₹214.10");
    expect(errors).toEqual([]);
  });
});

// ─────────────────────────────────────────────────────────────────────────
// The rest of the screen
// ─────────────────────────────────────────────────────────────────────────

test.describe("Your lists — with the rest of the Watchlist screen", () => {
  test("a research stock can be added to one of the user's lists", async ({ page }) => {
    const { server, errors } = await open(page, mine());
    await page.goto(`${APP}/page/watchlist`);
    await expect(tabNames(page)).toHaveText(["Fixture banks", "Fixture to read up on"]);
    const bravo = page.locator('[data-testid="watchlist-item"][data-symbol="FIXBRAVO"]');
    await expect(page.getByTestId("watchlist-add-to-list")).toHaveCount(3);            // one on each research stock

    await bravo.getByTestId("watchlist-add-to-list").click();
    const pick = bravo.getByTestId("watchlist-add-to-list-pick");
    await expect(pick.locator("option")).toHaveText(["Fixture banks", "Fixture to read up on"]);
    await expect(bravo.getByTestId("watchlist-add-to-list-form")).toContainText("Add FIXBRAVO to");
    await pick.selectOption(READ_UP);
    await bravo.getByTestId("watchlist-add-to-list-save").click();
    await expect(bravo.getByTestId("watchlist-add-to-list-done")).toHaveText("Added to Fixture to read up on.");
    // "Your lists" above shows it, from the server's own answer.
    await expect(tab(page, "Fixture to read up on").getByTestId("mylist-tab-count")).toHaveText("1");
    expect(server.sent).toEqual([{ op: "add", body: { symbol: "FIXBRAVO" } }]);
    expect(writes(server)).toEqual([`POST /api/watchlists/${READ_UP}/symbols`]);

    // Again: already there, said as such.
    await bravo.getByTestId("watchlist-add-to-list-save").click();
    await expect(bravo.getByTestId("watchlist-add-to-list-done")).toHaveText("Already in Fixture to read up on, so nothing changed.");
    expect(server.lists[1].stocks.map((e) => e.symbol)).toEqual(["FIXBRAVO"]);

    // A failed add says so; the list is unchanged.
    server.refuse.add = { status: 500, detail: "boom" };
    await pick.selectOption(BANKS);
    await bravo.getByTestId("watchlist-add-to-list-save").click();
    await expect(bravo.getByTestId("watchlist-add-to-list-error")).toHaveText("Not added, so nothing changed — the server reported an error");
    await expect(tab(page, "Fixture banks").getByTestId("mylist-tab-count")).toHaveText("5");
    await bravo.getByTestId("watchlist-add-to-list-close").click();
    await expect(bravo.getByTestId("watchlist-add-to-list")).toBeVisible();

    // The row still does what it did: it opens its research.
    await bravo.getByTestId("watchlist-row-toggle").click();
    await expect(bravo.getByTestId("watchlist-detail")).toBeVisible();
    expect(errors).toEqual([]);
  });

  test("with no list to add to, the research row says to make one first", async ({ page }) => {
    const { server, errors } = await open(page, { lists: [], hadList: true });
    await page.goto(`${APP}/page/watchlist`);
    await expect(page.getByTestId("mylists-empty")).toBeVisible();
    const alpha = page.locator('[data-testid="watchlist-item"][data-symbol="FIXALPHA"]');
    await alpha.getByTestId("watchlist-add-to-list").click();
    await expect(alpha.getByTestId("watchlist-add-to-list-none")).toHaveText("Make a list under “Your lists” first, then add Fixture Alpha Industries Ltd to it.");
    expect(writes(server)).toEqual([]);
    expect(errors).toEqual([]);
  });

  test("what is still not connected is alerts on a price or a volume, and the sending of alerts", async ({ page }) => {
    const { errors } = await open(page, mine());
    await page.goto(`${APP}/page/watchlist`);
    const block = page.getByTestId("watchlist-alerts-nc");
    await expect(block).toContainText("Price and volume alerts, and the sending of alerts, are not connected yet");
    await expect(block).toContainText("You can keep your own lists of stocks above.");
    await expect(block).toContainText("the filing alerts you choose here are saved but not sent");
    await expect(block).not.toContainText("Hand-picked lists");
    // The admin fixture user sees what engineering still has to build: no longer a watchlist store.
    const needs = block.getByTestId("not-connected-needs");
    await expect(needs.locator("li")).toHaveCount(3);
    await expect(needs).toContainText("Alert rules on price, volume");
    await expect(needs).toContainText("A delivery job for filing alerts");
    await expect(needs).not.toContainText("watchlist store");
    // The header names the new section first.
    await expect(page.getByTestId("screen-page-watchlist")).toContainText("Your own lists, the research watchlist with live prices");
    expect(errors).toEqual([]);
  });
});

// ─────────────────────────────────────────────────────────────────────────
// Phone
// ─────────────────────────────────────────────────────────────────────────

test.describe("Your lists — phone (390×844)", () => {
  test.use({ viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true });

  test("the lists, their forms, the search and a research row's picker fit the phone without sideways page scroll", async ({ page }) => {
    const longName = "Fixture list with a name that runs to the sixty letter limit";
    expect(longName.length).toBe(60);
    const lists = mine().lists;
    lists.push({ ...structuredClone(MINE.lists[1]), watchlist_id: "wl_fixturelong", name: longName });
    const { errors } = await open(page, { lists });
    await page.goto(`${APP}/page/watchlist`);
    await expect(page.getByTestId("mylist-stock")).toHaveCount(5);
    expect(await sideways(page)).toEqual({ doc: 0, scroll: 0 });

    // Every part of a row is inside the screen: the name, the price and the remove button.
    const width = page.viewportSize()!.width;
    for (const symbol of ["FIXALPHA", "FIXCHARLIE", "FIXDELTA"]) {
      const row = stock(page, symbol);
      const rowBox = (await row.boundingBox())!;
      const removeBox = (await row.getByTestId("mylist-remove").boundingBox())!;
      expect(rowBox.x).toBeGreaterThanOrEqual(0);
      expect(removeBox.x + removeBox.width).toBeLessThanOrEqual(width);
      expect((await row.getByTestId("mylist-stock-name").boundingBox())!.width).toBeGreaterThan(60);
    }
    // The rupee move is dropped on a phone; the percent stays.
    await expect(stock(page, "FIXALPHA").getByTestId("mylist-change")).toHaveText("+1.19%");
    await expect(stock(page, "FIXALPHA")).not.toContainText("+₹2.50");

    await page.getByTestId("mylist-new").click();
    await page.getByTestId("mylist-new-name").fill(longName);
    await expect(page.getByTestId("mylist-new-save")).toBeVisible();
    expect(await sideways(page)).toEqual({ doc: 0, scroll: 0 });
    await page.getByTestId("mylist-new-cancel").click();

    await page.getByTestId("mylist-rename").click();
    await expect(page.getByTestId("mylist-rename-save")).toBeVisible();
    await page.getByTestId("mylist-rename-cancel").click();
    await page.getByTestId("mylist-delete").click();
    await expect(page.getByTestId("mylist-delete-confirm")).toBeVisible();
    expect(await sideways(page)).toEqual({ doc: 0, scroll: 0 });
    await page.getByTestId("mylist-delete-keep").click();

    await page.getByTestId("mylist-add-search").fill("fixture");
    await expect(page.getByTestId("mylist-add-result")).toHaveCount(5);
    expect(await sideways(page)).toEqual({ doc: 0, scroll: 0 });
    await page.getByTestId("mylist-add-search").fill("");

    // The longest name a list can have, open, and in a research row's picker.
    await tab(page, longName).click();
    await expect(page.getByTestId("mylist-name")).toHaveText(longName);
    const charlie = page.locator('[data-testid="watchlist-item"][data-symbol="FIXCHARLIE"]');
    await charlie.getByTestId("watchlist-add-to-list").click();
    await charlie.getByTestId("watchlist-add-to-list-pick").selectOption("wl_fixturelong");
    await charlie.getByTestId("watchlist-add-to-list-save").click();
    await expect(charlie.getByTestId("watchlist-add-to-list-done")).toHaveText(`Added to ${longName}.`);
    expect(await sideways(page)).toEqual({ doc: 0, scroll: 0 });
    expect(errors).toEqual([]);
  });

  test("the example list and its note fit the phone", async ({ page }) => {
    const { errors } = await open(page);
    await page.goto(`${APP}/page/watchlist`);
    await expect(page.getByTestId("mylist-starter-note")).toHaveText(STARTER_NOTE);
    await expect(page.getByTestId("mylist-stock")).toHaveCount(3);
    await expect(stock(page, "FIXCHARLIE").getByTestId("mylist-stored")).toBeVisible();
    expect(await sideways(page)).toEqual({ doc: 0, scroll: 0 });
    expect(errors).toEqual([]);
  });
});
