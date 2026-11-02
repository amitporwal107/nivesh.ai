/**
 * One-screen Copilot app (/v5/app) — the F&O setups answer (owner, 31 Oct 2026): two sections (Index options, Stock F&O),
 * one row per underlying with its other structures folded under it ("+N more ›"), the lots, a bought option's profit that is
 * "Not capped" (its theoretical top only in a tooltip) with the profit at the expected move beside it, margin or a login
 * prompt, and live premiums marked "Live" while the ranking stays the close's. FE-1 … FE-8 of
 * test_reports/copilot_fno_board_20261031.md.
 *
 * Payloads: `e2e/fixtures/fno-board.mock.json` — MOCK, not real data: the real builder over the unit tests' invented inputs
 * (backend/tests/test_copilot_visual.py, FB-*). Every expected value is computed from the payload itself. The chat stream and
 * other routes are inline MOCKs in the real routes' shape. Mocked APIs, production build (pw.copilot-app.config.ts).
 */
import { test, expect, type Locator, type Page, type Route } from "@playwright/test";
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";
import { mockApi, mockSingleRoute } from "../helpers/api-mock";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const FIX = path.join(__dirname, "..", "fixtures");
type Payload = Record<string, any>;
const PAYLOADS: Record<string, Payload> = JSON.parse(fs.readFileSync(path.join(FIX, "fno-board.mock.json"), "utf-8")).payloads;
const CARD = JSON.parse(fs.readFileSync(path.join(FIX, "contract-decision-card.json"), "utf-8"));
const APP = "/v5/app";
const SLOW = { timeout: 15_000 };
const SHOTS = process.env.FNO_SHOTS ? path.join(__dirname, "..", ".shots", "fno-board") : null;

const MINUS = "−";
const nf = (n: number, min: number, max: number) => new Intl.NumberFormat("en-IN", { minimumFractionDigits: min, maximumFractionDigits: max }).format(n);
const fPrice = (n: number | null) => (n == null ? "—" : n < 0 ? `${MINUS}₹${nf(-n, 2, 2)}` : `₹${nf(n, 2, 2)}`);
const fX = (n: number | null) => (n == null ? "—" : `${nf(n, 1, 2)}×`);
const cellText = (v: unknown, fmt: string | undefined) => (v == null ? "—" : typeof v === "string" ? v : fmt === "price" ? fPrice(v as number) : fmt === "x" ? fX(v as number) : nf(v as number, 0, 2));

const json = (route: Route, body: unknown, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
const sse = (frames: Array<Record<string, unknown>>) => frames.map((f) => `data: ${JSON.stringify(f)}\n\n`).join("");
const ANSWER = "MOCK answer text, written from the payload's facts.";

async function chat(page: Page, p: Payload) {
  const saved: unknown[] = [];
  const w = { widget_type: "visual_answer", title: p.title, data: p,
    freshness: { state: "end_of_day", last_updated: "2026-10-30T04:50:00+05:30", source: ["NIDP"] }, agent: { id: "market_analyst", confidence: null } };
  await page.route("**/api/desk/trade-plans/*", (r) => json(r, CARD.fno.trade_plan_response));
  await page.route("**/api/desk/paper-account", (r) => json(r, { ...CARD.paper_account, stored: true }));
  await page.route("**/api/risk/profile", (r) => json(r, CARD.risk_profile_default));
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
}

async function open(page: Page, p: Payload, opts: { admin?: boolean; width?: number } = {}) {
  if (opts.width) await page.setViewportSize({ width: opts.width, height: 900 });
  await mockApi(page, "populated");
  await mockSingleRoute(page, "**/api/markets/home", "markets-home.json");
  if (opts.admin === false) {                                   // the onboarded user the app mocks, but not an admin
    const me = { ...JSON.parse(fs.readFileSync(path.join(FIX, "user-profile-onboarded.json"), "utf-8")), is_admin: false };
    await page.route("**/api/auth/me", (r) => json(r, me));
  }
  await chat(page, p);
  await page.goto(APP);
  await page.getByTestId("composer-input").fill("Which F&O setups are attractive?");
  await page.getByTestId("composer-input").press("Enter");
  await expect(page.getByTestId("thread-turn").first()).toHaveAttribute("data-state", "saved", SLOW);
  const va = page.getByTestId("va").first();
  await expect(va).toBeVisible(SLOW);
  return va;
}

const ranked = (va: Locator, id: string) => va.locator(`[data-testid="va-block"][data-block-id="${id}"]`).first();
const blockOf = (p: Payload, id: string) => p.blocks.find((b: any) => b.id === id);

test.describe("F&O setups board (MOCK payloads from the real builder)", () => {
  test("FE-1 two sections, one row per underlying, leads only; the title and rows come from the payload", async ({ page }) => {
    const p = PAYLOADS.eod_login;
    const va = await open(page, p);
    for (const id of ["fno_index", "fno_stock"]) {
      const b = blockOf(p, id);
      const f = ranked(va, id);
      await expect(f.getByTestId("va-block-title")).toHaveText(b.title);
      await expect(f.getByTestId("va-ranked-row")).toHaveCount(b.rows.length);
      const symbols = await f.getByTestId("va-ranked-row").evaluateAll((els) => els.map((e) => e.getAttribute("data-symbol")));
      expect(symbols).toEqual(b.rows.map((r: any) => r.symbol));
      await expect(f.getByTestId("va-ranked-alt")).toHaveCount(0);                       // alternatives start folded
    }
    expect(blockOf(p, "fno_index").rows.map((r: any) => r.symbol)).toEqual(["BANKNIFTY", "NIFTY"]);
    expect(blockOf(p, "fno_stock").rows.map((r: any) => r.symbol)).toEqual(["RELIANCE", "TCS"]);   // stock F&O is on the answer
  });

  test("FE-2 a lead's other structures sit behind '+N more ›' in the same columns, and fold away again", async ({ page }) => {
    const p = PAYLOADS.eod_login;
    const va = await open(page, p);
    const f = ranked(va, "fno_index");
    const lead = blockOf(p, "fno_index").rows[0];
    const btn = f.getByTestId("va-row-alts").first();
    await expect(btn).toHaveText(`+${lead.alternatives.length} more ›`);
    await btn.click();
    await expect(f.getByTestId("va-ranked-alt")).toHaveCount(lead.alternatives.length);
    const cols = blockOf(p, "fno_index").columns;
    const cards = (await f.getByTestId("va-ranked").getAttribute("data-layout")) === "cards";      // a card shows the symbol as its heading
    for (let i = 0; i < lead.alternatives.length; i++) {
      const row = f.getByTestId("va-ranked-alt").nth(i);
      for (const c of cols) if (!(cards && c.key === "symbol")) await expect(row.getByTestId(`va-cell-${c.key}`)).toContainText(cellText(lead.alternatives[i].cells[c.key], c.format).replace(/^—$/, "—"));
    }
    await expect(btn).toHaveText("Hide others");
    await btn.click();
    await expect(f.getByTestId("va-ranked-alt")).toHaveCount(0);
  });

  test("FE-3 lots, and a bought put reads 'Not capped' with the theoretical top only in its tooltip", async ({ page }) => {
    const p = PAYLOADS.eod_login;
    const va = await open(page, p);
    const f = ranked(va, "fno_index");
    const lead = blockOf(p, "fno_index").rows[0];
    await expect(f.getByTestId("va-ranked-row").first().getByTestId("va-cell-lots")).toHaveText(lead.cells.lots);
    await f.getByTestId("va-row-alts").first().click();
    const put = lead.alternatives.findIndex((a: any) => a.cells.maxprofit === "Not capped");
    expect(put).toBeGreaterThanOrEqual(0);
    const alt = f.getByTestId("va-ranked-alt").nth(put);
    await expect(alt.getByTestId("va-cell-maxprofit")).toHaveText("Not capped");
    await expect(alt.getByTestId("va-cell-maxprofit")).toHaveAttribute("title", lead.alternatives[put].tips.maxprofit);
    await expect(alt.getByTestId("va-cell-atmove")).toHaveText(fPrice(lead.alternatives[put].cells.atmove));
    // the to-zero figure is nowhere in the visible text of the row
    const top = String(lead.alternatives[put].tips.maxprofit).match(/₹[\d,]+\.\d\d/)?.[0] as string;
    expect(await alt.innerText()).not.toContain(top);
    // a capped spread keeps its real maximum
    await expect(f.getByTestId("va-ranked-row").first().getByTestId("va-cell-maxprofit")).toHaveText(fPrice(lead.cells.maxprofit));
  });

  test("FE-4 a loss prints with a true minus: '−₹14,406.00', never '₹-14,406.00'", async ({ page }) => {
    const p = PAYLOADS.eod_login;
    const va = await open(page, p);
    const lead = blockOf(p, "fno_index").rows[0];
    const cell = ranked(va, "fno_index").getByTestId("va-ranked-row").first().getByTestId("va-cell-maxloss");
    await expect(cell).toHaveText(fPrice(lead.cells.maxloss));
    expect(await cell.innerText()).toMatch(/^−₹/);
    expect(await va.innerText()).not.toContain("₹-");
  });

  test("FE-5 with no calculator the margin cell says 'Needs login' and the notice offers the login actions", async ({ page }) => {
    const p = PAYLOADS.eod_login;
    const va = await open(page, p);
    const n = blockOf(p, "login");
    await expect(ranked(va, "fno_index").getByTestId("va-ranked-row").first().getByTestId("va-cell-margin")).toHaveText("Needs login");
    const notice = va.getByTestId("va-notice").filter({ hasText: n.text.slice(0, 30) });
    await expect(notice.getByTestId("va-notice-text")).toHaveText(n.text);
    await expect(notice.getByTestId("va-notice-action-kite_login")).toBeVisible();            // the default mock user is an admin
    await expect(notice.getByTestId("va-notice-action-connect_broker")).toBeVisible();
    await notice.getByTestId("va-notice-action-connect_broker").click();
    await expect(page).toHaveURL(/\/app\/page\/brokers/);
  });

  test("FE-6 a non-admin gets no platform Kite login button, only connect-a-broker", async ({ page }) => {
    const p = PAYLOADS.eod_login;
    const va = await open(page, p, { admin: false });
    const notice = va.getByTestId("va-notice").filter({ hasText: blockOf(p, "login").text.slice(0, 30) });
    await expect(notice.getByTestId("va-notice-action-connect_broker")).toBeVisible();
    await expect(notice.getByTestId("va-notice-action-kite_login")).toHaveCount(0);
  });

  test("FE-7 live: a repriced row is marked Live, the others keep their close's date; margin shows the figure", async ({ page }) => {
    const p = PAYLOADS.live;
    const va = await open(page, p);
    const f = ranked(va, "fno_index");
    const rows = blockOf(p, "fno_index").rows;
    await expect(f.getByTestId("va-ranked-row").nth(0).getByTestId("va-row-badge")).toHaveText(rows[0].badge);
    expect(rows[0].badge).toBe("Live");
    await expect(f.getByTestId("va-ranked-row").nth(0).getByTestId("va-row-badge")).toHaveAttribute("data-live", "1");
    await expect(f.getByTestId("va-ranked-row").nth(1).getByTestId("va-row-badge")).toHaveText(rows[1].badge);
    await expect(f.getByTestId("va-ranked-row").nth(0).getByTestId("va-cell-margin")).toHaveText(fPrice(rows[0].cells.margin));
    await expect(f.getByTestId("va-block-note")).toContainText("Premiums live at");
    expect(p.mode).toBe("mixed");
  });

  test("FE-8 on a phone the rows are cards, the toggle still works and nothing scrolls sideways", async ({ page }) => {
    const p = PAYLOADS.eod_login;
    const va = await open(page, p, { width: 390 });
    const f = ranked(va, "fno_index");
    await expect(f.getByTestId("va-ranked")).toHaveAttribute("data-layout", "cards");
    await f.getByTestId("va-row-alts").first().click();
    await expect(f.getByTestId("va-ranked-alt").first()).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
  });

  test("FE-10 in a wide box the board is a table: ten columns, badge by the symbol, alternatives as rows under their lead", async ({ page }) => {
    const p = PAYLOADS.eod_login;
    const va = await open(page, p);
    await va.evaluate((el) => { (el as HTMLElement).style.width = "1300px"; (el as HTMLElement).style.maxWidth = "none"; });   // the thread column is capped near 800 px in this harness
    const f = ranked(va, "fno_index");
    await expect(f.getByTestId("va-ranked")).toHaveAttribute("data-layout", "table", SLOW);
    const cols = blockOf(p, "fno_index").columns;
    expect(cols.length).toBe(10);
    await expect(f.locator("thead th")).toHaveText([...cols.map((c: any) => c.label), "Actions"]);
    const lead = f.getByTestId("va-ranked-row").first();
    await expect(lead.getByTestId("va-row-badge")).toHaveText(blockOf(p, "fno_index").rows[0].badge);
    await expect(lead.getByTestId("va-cell-maxloss")).toHaveText(fPrice(blockOf(p, "fno_index").rows[0].cells.maxloss));
    expect(await lead.getByTestId("va-cell-maxloss").evaluate((e) => getComputedStyle(e).whiteSpace)).toBe("nowrap");        // a figure never breaks in two
    await f.getByTestId("va-row-alts").first().click();
    const alt = f.locator("tbody tr[data-testid='va-ranked-alt']").first();
    await expect(alt).toBeVisible();
    await expect(alt.getByTestId("va-cell-maxprofit")).toHaveAttribute("title", /theoretical/);
    await expect(alt.getByTestId("va-row-plan")).toBeVisible();                                                              // an alternative opens its own plan
    if (SHOTS) await va.screenshot({ path: path.join(SHOTS, "table-eod.png") });
  });

  // FNO_SHOTS=1 writes screenshots to e2e/.shots/fno-board (looked at by hand; not an assertion).
  test("FE-9 screenshots (only with FNO_SHOTS=1)", async ({ page }) => {
    test.skip(!process.env.FNO_SHOTS, "set FNO_SHOTS=1");
    const dir = path.join(__dirname, "..", ".shots", "fno-board");
    fs.mkdirSync(dir, { recursive: true });
    for (const [name, key, width] of [["desktop-eod", "eod_login", 1500], ["desktop-live", "live", 1500], ["mid-eod", "eod_login", 1100], ["wide-eod", "eod_login", 2200], ["phone-eod", "eod_login", 390]] as const) {
      const va = await open(page, PAYLOADS[key], { width });
      await ranked(va, "fno_index").getByTestId("va-row-alts").first().click();
      const lay = ranked(va, "fno_index").getByTestId("va-ranked");
      console.log(`${name}: width ${width} -> layout ${await lay.getAttribute("data-layout")}, box ${Math.round((await lay.boundingBox())?.width ?? 0)}px`);
      await va.screenshot({ path: path.join(dir, `${name}.png`) });
      await page.unroute("**/api/chat/stream");
      await page.goto("about:blank");
    }
  });
});
