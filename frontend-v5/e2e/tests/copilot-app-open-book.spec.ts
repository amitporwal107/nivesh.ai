/**
 * One-screen Copilot app (/v5/app) — "What are my open trades doing?" on the user's BROKER book (owner, 31 Oct 2026), FO-1 … FO-12 of
 * test_reports/copilot_broker_book_20261031.md: the connect prompt, the sign-in-again state with the last stored read dated, a live
 * book, and the page that keeps itself current every 5 seconds without ever asking faster, while hidden, off screen, after the
 * server says stop, or for an answer built on an earlier day — and that degrades to the read it has when the feed fails.
 *
 * Payloads: `e2e/fixtures/open-book.mock.json` — MOCK, not real data: the real builder and the real live route over the invented
 * world of backend/tests/test_open_book.py. Every expected value is read from the payload. The chat stream and the live route are
 * inline MOCKs in the real routes' shape. Time is Playwright's fake clock, so 5 s means 5 s without waiting.
 */
import { test, expect, type Locator, type Page, type Route } from "@playwright/test";
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";
import { mockApi, mockSingleRoute } from "../helpers/api-mock";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const FIX = path.join(__dirname, "..", "fixtures");
type Payload = Record<string, any>;
const F: Record<string, Payload> = JSON.parse(fs.readFileSync(path.join(FIX, "open-book.mock.json"), "utf-8"));
const CARD = JSON.parse(fs.readFileSync(path.join(FIX, "contract-decision-card.json"), "utf-8"));
const APP = "/v5/app";
const SLOW = { timeout: 15_000 };
const LIVE_PATH = "**/api/positions/book/live";
const SHOTS = process.env.OB_SHOTS ? path.join(__dirname, "..", ".shots", "open-book") : null;

const MINUS = "−";
const nf = (n: number, min: number, max: number) => new Intl.NumberFormat("en-IN", { minimumFractionDigits: min, maximumFractionDigits: max }).format(n);
const fPrice = (n: number | null) => (n == null ? "—" : n < 0 ? `${MINUS}₹${nf(-n, 2, 2)}` : `₹${nf(n, 2, 2)}`);
const json = (route: Route, body: unknown, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
const sse = (frames: Array<Record<string, unknown>>) => frames.map((f) => `data: ${JSON.stringify(f)}\n\n`).join("");
const ANSWER = "MOCK answer text, written from the payload's facts.";
const blockOf = (p: Payload, id: string) => p.blocks.find((b: any) => b.id === id);
const rowOf = (b: any, symbol: string) => b.rows.find((r: any) => r.cells.symbol === symbol);

/** The payload as the chat sends it, built "now" so the page treats it as today's answer. */
function fresh(p: Payload, builtAt: Date = new Date()): Payload {
  return { ...p, generated_at: builtAt.toISOString() };
}

async function chat(page: Page, p: Payload) {
  const saved: unknown[] = [];
  const w = { widget_type: "visual_answer", title: p.title, data: p, freshness: { state: "end_of_day", last_updated: p.generated_at, source: ["Broker"] },
    agent: { id: "market_analyst", confidence: null } };
  await page.route("**/api/desk/trade-plans/*", (r) => json(r, CARD.fno.trade_plan_response));
  await page.route("**/api/desk/paper-account", (r) => json(r, { ...CARD.paper_account, stored: true }));
  await page.route("**/api/risk/profile", (r) => json(r, CARD.risk_profile_default));
  await page.route("**/api/chat/sessions", (r) => r.request().method() === "POST" ? json(r, { session_id: "new1", id: "new1" }) : json(r, []));
  await page.route("**/api/chat/messages*", (r) => json(r, saved));
  await page.route("**/api/chat/suggest-queries*", (r) => json(r, { suggestions: [] }));
  await page.route("**/api/chat/instrument-search*", (r) => json(r, { stocks: [], funds: [] }));
  await page.route("**/api/chat/stream", (r) => {
    const body = r.request().postDataJSON() as { message: string };
    saved.push({ message_id: "u1", session_id: "new1", role: "user", content: body.message, created_at: p.generated_at },
      { message_id: "a1", session_id: "new1", role: "assistant", content: ANSWER, created_at: p.generated_at, widget: w });
    return r.fulfill({ status: 200, contentType: "text/event-stream", body: sse([
      { type: "meta", session_id: "new1", ai_msg_id: "a1", user_msg_id: "u1" }, { type: "route", agent: "market_analyst", confidence: 0.9 },
      { type: "widget", ...w }, { type: "token", content: ANSWER }, { type: "done", content: ANSWER, follow_ups: [] }]) });
  });
}

/** Opens the app, asks the question, waits for the answer. `live` serves the page's asks (counted in `asks`). */
async function open(page: Page, p: Payload, opts: { width?: number; live?: (n: number, route: Route) => unknown; pause?: boolean } = {}) {
  const asks = { n: 0, at: [] as number[] };
  if (opts.width) await page.setViewportSize({ width: opts.width, height: 900 });
  await page.clock.install({ time: new Date() });
  await mockApi(page, "populated");
  await mockSingleRoute(page, "**/api/markets/home", "markets-home.json");
  await chat(page, p);
  await page.route(LIVE_PATH, (route) => {
    asks.n += 1;
    return opts.live ? opts.live(asks.n, route) : json(route, F.tick);
  });
  await page.goto(APP);
  await page.getByTestId("composer-input").fill("What are my open trades doing?");
  await page.getByTestId("composer-input").press("Enter");
  await expect(page.getByTestId("thread-turn").first()).toHaveAttribute("data-state", "saved", SLOW);
  const va = page.getByTestId("va").first();
  await expect(va).toBeVisible(SLOW);
  if (opts.pause !== false) await page.clock.pauseAt(new Date(Date.now() + 1_000));    // from here only runFor() moves time
  return { va, asks };
}

const block = (va: Locator, id: string) => va.locator(`[data-testid="va-block"][data-block-id="${id}"]`).first();
const chip = (va: Locator) => va.getByTestId("va-live");

test.describe("Open trades on the broker book (MOCK payloads from the real builder)", () => {
  test("FO-1 no broker connected: one prompt with a Connect action, the paper trades still there, nothing live", async ({ page }) => {
    const p = fresh(F.no_broker);
    const { va } = await open(page, p);
    const n = blockOf(p, "no-broker");
    const notice = va.getByTestId("va-notice").filter({ hasText: n.text.slice(0, 30) });
    await expect(notice.getByTestId("va-notice-text")).toHaveText(n.text);
    await notice.getByTestId("va-notice-action-connect_broker").click();
    await expect(page).toHaveURL(/\/app\/page\/brokers/);
  });

  test("FO-1b with no broker the paper table is shown and labelled Paper; there is no live chip", async ({ page }) => {
    const p = fresh(F.no_broker);
    const { va } = await open(page, p);
    await expect(block(va, "trades").getByTestId("va-ranked-row")).toHaveCount(blockOf(p, "trades").rows.length);
    await expect(block(va, "trades").getByTestId("va-block-note")).toContainText("Paper");
    await expect(va.getByTestId("va-live")).toHaveCount(0);
    await expect(va).toHaveAttribute("data-live", "static");
  });

  test("FO-2 session ended: 'Sign in again', the last stored read dated, rows marked 'As of', funds 'Not available', never live", async ({ page }) => {
    const p = fresh(F.ended);
    const { va, asks } = await open(page, p);
    const n = p.blocks.find((b: any) => String(b.id).startsWith("ended-"));
    const notice = va.getByTestId("va-notice").filter({ hasText: "session has ended" });
    await expect(notice.getByTestId("va-notice-text")).toHaveText(n.text);
    await expect(notice.getByTestId("va-notice-action-connect_broker")).toHaveText(n.actions[0].label);
    const rows = blockOf(p, "positions").rows;
    await expect(block(va, "positions").getByTestId("va-ranked-row")).toHaveCount(rows.length);
    for (let i = 0; i < rows.length; i++) await expect(block(va, "positions").getByTestId("va-ranked-row").nth(i).getByTestId("va-row-badge")).toHaveText(rows[i].badge);
    expect(rows.every((r: any) => /^As of /.test(r.badge))).toBe(true);
    const acc = block(va, "accounts").getByTestId("va-ranked-row").first();
    await expect(acc.getByTestId("va-cell-avail")).toHaveText("Not available");
    await expect(acc.getByTestId("va-cell-state")).toHaveText("Session ended");
    await page.clock.runFor(30_000);
    expect(asks.n).toBe(0);                                                 // a stored read is never polled
    await expect(va.getByTestId("va-live")).toHaveCount(0);
  });

  test("FO-3 a live book: positions with the broker's P&L, stops with the loss at the stop, margin, and each account's funds", async ({ page }) => {
    const p = fresh(F.live);
    const { va } = await open(page, p);
    const pos = blockOf(p, "positions");
    const row = block(va, "positions").getByTestId("va-ranked-row").filter({ hasText: "EXIDEIND" }).first();
    const exide = rowOf(pos, "EXIDEIND");
    await expect(row.getByTestId("va-cell-pnl")).toHaveText(fPrice(exide.cells.pnl));
    await expect(row.getByTestId("va-cell-ltp")).toHaveText(fPrice(exide.cells.ltp));
    await expect(row.getByTestId("va-cell-pnl")).toHaveAttribute("title", exide.tips.pnl);
    const lv = rowOf(blockOf(p, "levels"), "EXIDEIND");
    const lrow = block(va, "levels").getByTestId("va-ranked-row").filter({ hasText: "EXIDEIND" }).first();
    await expect(lrow.getByTestId("va-cell-stop")).toHaveText(fPrice(lv.cells.stop));
    await expect(lrow.getByTestId("va-cell-risk")).toHaveText(fPrice(lv.cells.risk));
    const ad = rowOf(blockOf(p, "levels"), "ADANIPORTS");
    await expect(block(va, "levels").getByTestId("va-ranked-row").filter({ hasText: "ADANIPORTS" }).first().getByTestId("va-cell-margin")).toHaveText(fPrice(ad.cells.margin));
    const acc = rowOf(blockOf(p, "accounts"), "ICICI Direct");
    await expect(block(va, "accounts").getByTestId("va-cell-avail").first()).toHaveText(fPrice(acc.cells.avail));
    await expect(block(va, "accounts").getByTestId("va-cell-used").first()).toHaveText(fPrice(acc.cells.used));
    for (const it of blockOf(p, "commentary").items) await expect(block(va, "commentary")).toContainText(it.text.slice(0, 40));
  });

  test("FO-4 the page asks every 5 s, never sooner, and swaps in the server's blocks; the chip counts the seconds", async ({ page }) => {
    const p = fresh(F.live);
    const { va, asks } = await open(page, p);
    await expect(chip(va)).toHaveAttribute("data-state", "live");
    await expect(chip(va)).toContainText("Live · updated");
    await page.clock.runFor(4_000);
    expect(asks.n).toBe(0);
    await page.clock.runFor(1_500);
    await expect.poll(() => asks.n).toBe(1);
    const exide = rowOf(blockOf(F.tick, "positions"), "EXIDEIND");
    const row = block(va, "positions").getByTestId("va-ranked-row").filter({ hasText: "EXIDEIND" }).first();
    await expect(row.getByTestId("va-cell-ltp")).toHaveText(fPrice(exide.cells.ltp), SLOW);
    await expect(row.getByTestId("va-cell-pnl")).toHaveText(fPrice(exide.cells.pnl));
    await expect(chip(va)).toHaveText("Live · updated 0s ago");
    await page.clock.runFor(3_000);
    await expect(chip(va)).toHaveText("Live · updated 3s ago");
    expect(asks.n).toBe(1);
    await page.clock.runFor(2_500);
    await expect.poll(() => asks.n).toBe(2);
    // the stop breach the tick carries is on screen in the levels and the checks
    const t = F.tick;
    for (const it of blockOf(t, "commentary").items.filter((i: any) => /past your stop/.test(i.text))) await expect(block(va, "commentary")).toContainText(it.text.slice(0, 50));
  });

  test("FO-5 hidden tab or an answer scrolled away: no asks; back in view: one ask at once", async ({ page }) => {
    const p = fresh(F.live);
    const { va, asks } = await open(page, p);
    await page.evaluate(() => { Object.defineProperty(document, "visibilityState", { configurable: true, get: () => "hidden" }); document.dispatchEvent(new Event("visibilitychange")); });
    await page.clock.runFor(30_000);
    expect(asks.n).toBe(0);
    await expect(chip(va)).toHaveAttribute("data-state", "paused");
    await expect(chip(va)).toContainText("Paused while you are away");
    await page.evaluate(() => { Object.defineProperty(document, "visibilityState", { configurable: true, get: () => "visible" }); document.dispatchEvent(new Event("visibilitychange")); });
    await expect.poll(() => asks.n).toBe(1);
    await expect(chip(va)).toHaveAttribute("data-state", "live");
  });

  test("FO-6 the server says the market is closed: the page stops asking and says when it last had the book", async ({ page }) => {
    const p = fresh(F.live);
    const { va, asks } = await open(page, p, { live: (_n, route) => json(route, F.tick_closed) });
    await page.clock.runFor(5_500);
    await expect(chip(va)).toHaveAttribute("data-state", "closed", SLOW);
    await expect(chip(va)).toContainText("Updates stopped: the market is closed");
    await page.clock.runFor(60_000);
    expect(asks.n).toBe(1);
    await expect(va).toHaveAttribute("data-mode", "eod");
  });

  test("FO-7 the feed fails: the blocks already shown stay, the chip says the feed was lost, it backs off and gives up after three", async ({ page }) => {
    const p = fresh(F.live);
    const { va, asks } = await open(page, p, { live: (_n, route) => json(route, { detail: "book_unavailable" }, 502) });
    const exide = rowOf(blockOf(p, "positions"), "EXIDEIND");
    await page.clock.runFor(5_500);
    await expect(chip(va)).toHaveAttribute("data-state", "lost", SLOW);
    await expect(chip(va)).toContainText("Live feed lost · showing the read of");
    await expect(block(va, "positions").getByTestId("va-ranked-row").filter({ hasText: "EXIDEIND" }).first().getByTestId("va-cell-pnl")).toHaveText(fPrice(exide.cells.pnl));
    await page.clock.runFor(10_000);                                          // the second wait is 10 s
    await expect.poll(() => asks.n).toBe(2);
    await page.clock.runFor(20_000);                                          // the third is 20 s
    await expect.poll(() => asks.n).toBe(3);
    await page.clock.runFor(120_000);
    expect(asks.n).toBe(3);
  });

  test("FO-8 an answer built on an earlier day is a record, not a live page", async ({ page }) => {
    const yesterday = new Date(Date.now() - 36 * 3600 * 1000);
    const p = fresh(F.live, yesterday);
    const { va, asks } = await open(page, p);
    await page.clock.runFor(60_000);
    expect(asks.n).toBe(0);
    await expect(chip(va)).toHaveAttribute("data-state", "static");
    await expect(chip(va)).toHaveText("As of the time it was built");
  });

  test("FO-9 a block the server sends that does not parse leaves the block already shown", async ({ page }) => {
    const p = fresh(F.live);
    const bad = { ...F.tick, blocks: [{ type: "ranked", id: "positions", title: "x", columns: [], rows: "nope" }] };
    const { va, asks } = await open(page, p, { live: (_n, route) => json(route, bad) });
    const exide = rowOf(blockOf(p, "positions"), "EXIDEIND");
    await page.clock.runFor(5_500);
    await expect.poll(() => asks.n).toBe(1);
    await expect(block(va, "positions").getByTestId("va-ranked-row").filter({ hasText: "EXIDEIND" }).first().getByTestId("va-cell-ltp")).toHaveText(fPrice(exide.cells.ltp));
  });

  test("FO-10 on a phone the tables are cards, the chip fits and nothing scrolls sideways", async ({ page }) => {
    const p = fresh(F.live);
    const { va } = await open(page, p, { width: 390 });
    await expect(block(va, "positions").getByTestId("va-ranked")).toHaveAttribute("data-layout", "cards");
    await expect(chip(va)).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
    if (SHOTS) { fs.mkdirSync(SHOTS, { recursive: true }); await va.screenshot({ path: path.join(SHOTS, "live-phone.png") }); }
  });

  test("FO-11 wide: positions and accounts are tables; money prints with a true minus", async ({ page }) => {
    const p = fresh(F.live);
    const { va } = await open(page, p);
    await va.evaluate((el) => { (el as HTMLElement).style.width = "1100px"; (el as HTMLElement).style.maxWidth = "none"; });
    await expect(block(va, "positions").getByTestId("va-ranked")).toHaveAttribute("data-layout", "table", SLOW);
    expect(await va.innerText()).not.toContain("₹-");
    if (SHOTS) { fs.mkdirSync(SHOTS, { recursive: true }); await va.screenshot({ path: path.join(SHOTS, "live-wide.png") }); }
  });

  test("FO-12 the written answer is nothing but ideas to review: the page offers no order button", async ({ page }) => {
    const p = fresh(F.live);
    const { va } = await open(page, p);
    const text = (await va.innerText()).toLowerCase();
    for (const w of ["place order", "buy now", "sell now", "square off"]) expect(text).not.toContain(w);
    await expect(va.getByTestId("va-notice").filter({ hasText: "cannot place, modify or cancel an order" })).toBeVisible();
  });
});
