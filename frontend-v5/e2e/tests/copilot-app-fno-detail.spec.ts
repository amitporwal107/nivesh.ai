/**
 * One-screen Copilot app (/v5/app) — the F&O detail of a build-up stock (owner, 31 Oct 2026: "an option to show the OI chain and
 * the futures build-up for the stocks, may be a popup, and the user can open the chart analysis page under the trade desk to
 * create a paper trade if required"). FD-1 … FD-8 of test_reports/copilot_batch2_20261031.md.
 *
 * Payload: the smart_money answer of `e2e/fixtures/contract-visual-answer.json` — the REAL staging capture (its build-up blocks carry
 * `detail: "fno"`). The desk's F&O routes are inline MOCKs from `fno-nifty.json` (synthetic, not market data) in the real routes' shape.
 * Every expected value is computed from the payload. Mocked APIs, production build (pw.copilot-app.config.ts).
 */
import { test, expect, type Locator, type Page, type Route } from "@playwright/test";
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";
import { mockApi, mockSingleRoute } from "../helpers/api-mock";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const FIX = path.join(__dirname, "..", "fixtures");
type Payload = Record<string, any>;
const P: Payload = JSON.parse(fs.readFileSync(path.join(FIX, "contract-visual-answer.json"), "utf-8")).payloads.smart_money;
const F = JSON.parse(fs.readFileSync(path.join(FIX, "fno-nifty.json"), "utf-8"));
const QUAD = P.blocks.find((b: any) => b.type === "quadrant");
const RANKED = P.blocks.find((b: any) => b.type === "ranked" && b.id === "strongest");
const APP = "/v5/app";
const SLOW = { timeout: 15_000 };

const json = (route: Route, body: unknown, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
const sse = (frames: Array<Record<string, unknown>>) => frames.map((f) => `data: ${JSON.stringify(f)}\n\n`).join("");
const ANSWER = "MOCK answer text, written from the payload's facts.";
const symOf = (route: Route) => decodeURIComponent(new URL(route.request().url()).pathname.split("/api/fno/")[1].split("/")[0]);

async function open(page: Page, opts: { width?: number; noRows?: string } = {}): Promise<Locator> {
  if (opts.width) await page.setViewportSize({ width: opts.width, height: 900 });
  await mockApi(page, "populated");
  await mockSingleRoute(page, "**/api/markets/home", "markets-home.json");
  const saved: unknown[] = [];
  const w = { widget_type: "visual_answer", title: P.title, data: P, freshness: { state: "end_of_day", last_updated: "2026-10-30T04:50:00+05:30", source: ["NIDP"] }, agent: { id: "market_analyst", confidence: null } };
  await page.route("**/api/fno/*/expiries", (r) => opts.noRows ? json(r, { detail: opts.noRows }, 404) : json(r, { ...F.expiries, symbol: symOf(r) }));
  await page.route("**/api/fno/*/chain*", (r) => json(r, { ...F.chain, symbol: symOf(r) }));
  await page.route("**/api/fno/*/futures", (r) => opts.noRows ? json(r, { detail: opts.noRows }, 404) : json(r, { ...F.futures, symbol: symOf(r) }));
  await page.route("**/api/chat/sessions", (r) => r.request().method() === "POST" ? json(r, { session_id: "new1", id: "new1" }) : json(r, []));
  await page.route("**/api/chat/messages*", (r) => json(r, saved));
  await page.route("**/api/chat/suggest-queries*", (r) => json(r, { suggestions: [] }));
  await page.route("**/api/chat/instrument-search*", (r) => json(r, { stocks: [], funds: [] }));
  await page.route("**/api/chat/stream", (r) => {
    const body = r.request().postDataJSON() as { message: string };
    saved.push({ message_id: "u1", session_id: "new1", role: "user", content: body.message, created_at: "2026-10-30T04:50:00+00:00" },
      { message_id: "a1", session_id: "new1", role: "assistant", content: ANSWER, created_at: "2026-10-30T04:50:05+00:00", widget: w });
    return r.fulfill({ status: 200, contentType: "text/event-stream", body: sse([
      { type: "meta", session_id: "new1", ai_msg_id: "a1", user_msg_id: "u1" }, { type: "route", agent: "market_analyst", confidence: 0.9 },
      { type: "widget", ...w }, { type: "token", content: ANSWER }, { type: "done", content: ANSWER, follow_ups: [] }]) });
  });
  await page.goto(APP);
  await page.getByTestId("composer-input").fill("Where is smart money moving?");
  await page.getByTestId("composer-input").press("Enter");
  await expect(page.getByTestId("thread-turn").first()).toHaveAttribute("data-state", "saved", SLOW);
  const va = page.getByTestId("va").first();
  await expect(va).toBeVisible(SLOW);
  return va;
}

const corner = (x: number, y: number) => (x >= 0 ? (y >= 0 ? "tr" : "br") : y >= 0 ? "tl" : "bl");
const dialog = (page: Page) => page.getByTestId("va-fno-dialog");

test.describe("F&O detail of a build-up stock (real smart_money capture, mocked desk F&O routes)", () => {
  test("FD-1 the payload asks for it: both build-up blocks carry detail fno, every point and row names a stock", async () => {
    expect(QUAD.detail).toBe("fno");
    expect(RANKED.detail).toBe("fno");
    expect(QUAD.points.length).toBeGreaterThan(0);
    expect(RANKED.rows.every((r: any) => !!r.symbol)).toBe(true);
  });

  test("FD-2 a table row's Details › opens that stock's dialog, with where it sits in the answer, the OI chain first", async ({ page }) => {
    const va = await open(page);
    const first = QUAD.points[0];
    const row = va.getByTestId("va-quadrant-row").filter({ has: page.locator(`td:text-is("${first.label}")`) }).first();
    await row.getByTestId("va-quadrant-detail").click();
    await expect(dialog(page)).toBeVisible(SLOW);
    await expect(dialog(page)).toHaveAttribute("data-symbol", first.label);
    await expect(page.getByTestId("va-fno-dialog-title")).toHaveText(`${first.label} · futures and options`);
    await expect(page.getByTestId("va-fno-dialog-context")).toContainText(QUAD.quadrants[corner(first.x, first.y)]);       // the quadrant it sits in
    await expect(page.getByTestId("va-fno-chain")).toBeVisible(SLOW);
    await expect(page.getByTestId("desk-fno-chain")).toBeVisible();                          // the desk's own OI table, read-only
  });

  test("FD-3 a chart point opens the same dialog, from the keyboard too", async ({ page }) => {
    const va = await open(page);
    const first = QUAD.points[1];
    const point = va.locator(`[data-testid="va-quadrant-point"][data-label="${first.label}"]`);
    await expect(point).toHaveAttribute("role", "button");
    await point.focus();
    await page.keyboard.press("Enter");
    await expect(dialog(page)).toHaveAttribute("data-symbol", first.label, SLOW);
  });

  test("FD-4 the futures tab lists each contract with its build-up; the chain tab comes back", async ({ page }) => {
    const va = await open(page);
    await va.getByTestId("va-quadrant-detail").first().click();
    await expect(page.getByTestId("va-fno-chain")).toBeVisible(SLOW);
    await page.getByRole("tab", { name: "Futures build-up" }).click();
    await expect(page.getByTestId("va-fno-future")).toHaveCount(F.futures.futures.length, SLOW);
    await expect(page.getByTestId("va-fno-future").first()).toHaveAttribute("data-expiry", F.futures.futures[0].expiry);
    await page.getByRole("tab", { name: "Option chain · OI" }).click();
    await expect(page.getByTestId("va-fno-chain")).toBeVisible();
  });

  test("FD-5 Escape and a click outside close it; focus returns to the button that opened it", async ({ page }) => {
    const va = await open(page);
    const btn = va.getByTestId("va-quadrant-detail").first();
    await btn.click();
    await expect(dialog(page)).toBeVisible(SLOW);
    await page.keyboard.press("Escape");
    await expect(dialog(page)).toHaveCount(0);
    await expect(btn).toBeFocused();
    await btn.click();
    await page.getByTestId("va-fno-dialog-scrim").click({ position: { x: 4, y: 4 } });
    await expect(dialog(page)).toHaveCount(0);
  });

  test("FD-6 'Open in Chart Analysis ›' goes to Trade Desk › Chart Analysis for that stock and closes the dialog", async ({ page }) => {
    const va = await open(page);
    const first = QUAD.points[0];
    await va.getByTestId("va-quadrant-detail").first().click();
    await page.getByTestId("va-fno-open-chart").click();
    await expect(page).toHaveURL(new RegExp(`/app/trader/desk\\?tab=trade&view=chart&sym=${first.label}`));
    await expect(dialog(page)).toHaveCount(0);
  });

  test("FD-7 the ranked list's Details › opens it too, saying which build-up and the moves", async ({ page }) => {
    const va = await open(page);
    const row0 = RANKED.rows[0];
    await va.locator(`[data-testid="va-ranked-row"][data-symbol="${row0.symbol}"]`).first().getByTestId("va-row-detail").click();
    await expect(dialog(page)).toHaveAttribute("data-symbol", row0.symbol, SLOW);
    await expect(page.getByTestId("va-fno-dialog-context")).toContainText(row0.cells.buildup);
  });

  test("FD-8 a stock with no F&O rows says so and keeps the dialog usable; on a phone it is a sheet with no sideways scroll", async ({ page }) => {
    const va = await open(page, { width: 390, noRows: "No F&O data for this symbol" });
    await va.getByTestId("va-quadrant-detail").first().click();
    await expect(dialog(page)).toBeVisible(SLOW);
    await expect(page.getByTestId("va-fno-chain-none")).toBeVisible(SLOW);
    await page.getByRole("tab", { name: "Futures build-up" }).click();
    await expect(page.getByTestId("va-fno-futures-none")).toBeVisible(SLOW);
    await expect(page.getByTestId("va-fno-open-chart")).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
    await page.getByTestId("va-fno-close").click();
    await expect(dialog(page)).toHaveCount(0);
  });

  // FD_SHOTS=1 writes screenshots to e2e/.shots/fno-detail (looked at by hand; not an assertion).
  test("FD-9 screenshots (only with FD_SHOTS=1)", async ({ page }) => {
    test.skip(!process.env.FD_SHOTS, "set FD_SHOTS=1");
    const dir = path.join(__dirname, "..", ".shots", "fno-detail");
    fs.mkdirSync(dir, { recursive: true });
    const va = await open(page, { width: 1300 });
    await va.getByTestId("va-quadrant-detail").first().click();
    await expect(page.getByTestId("desk-fno-chain")).toBeVisible(SLOW);
    await page.screenshot({ path: path.join(dir, "chain.png") });
    await page.getByRole("tab", { name: "Futures build-up" }).click();
    await expect(page.getByTestId("va-fno-future").first()).toBeVisible(SLOW);
    await page.screenshot({ path: path.join(dir, "futures.png") });
  });
});
