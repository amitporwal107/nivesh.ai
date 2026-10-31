/**
 * One-screen Copilot app (/v5/app/page/positions) — the Open Positions workspace
 * (src/pages/CopilotApp/screens/positions/, backend/routes/positions.py): OP-1 … OP-14 of
 * test_reports/r2_open_positions_20261031.md.
 *
 * Payload: e2e/fixtures/positions.mock.json — MOCK, not real broker data. Its two paper groups are the real staging
 * response of 30 Oct 2026; the broker groups are the real services/positions code run over CONSTRUCTED inputs, because
 * that account's broker sessions had ended. Every expected value is computed from the payload itself, never copied from
 * the screen. All /api calls are mocked; production build (pw.copilot-app.config.ts).
 */
import { test, expect, type Page, type Route } from "@playwright/test";
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";
import { mockApi, mockSingleRoute } from "../helpers/api-mock";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const BOOK = JSON.parse(fs.readFileSync(path.join(__dirname, "..", "fixtures", "positions.mock.json"), "utf-8"));
const PAGE = "/v5/app/page/positions";
const SLOW = { timeout: 15_000 };

const MINUS = "−";
const nf = (n: number, min = 0, max = 2) => new Intl.NumberFormat("en-IN", { minimumFractionDigits: min, maximumFractionDigits: max }).format(n);
const price = (n: number | null) => (n == null ? "—" : `₹${nf(n, 2, 2)}`);
const rupees = (n: number | null) => (n == null ? "—" : `${n < 0 ? MINUS : ""}₹${nf(Math.abs(n), 0, 0)}`);
const group = (key: string) => BOOK.groups.find((g: any) => g.key === key);

const json = (route: Route, body: unknown, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });

interface Seen { levelPuts: Array<{ url: string; body: any }>; levelDeletes: string[]; margins: any[]; scenarios: string[]; books: number }

async function open(page: Page, book: unknown = BOOK, status = 200): Promise<Seen> {
  const seen: Seen = { levelPuts: [], levelDeletes: [], margins: [], scenarios: [], books: 0 };
  await mockApi(page, "populated");
  await mockSingleRoute(page, "**/api/markets/home", "markets-home.json");
  await page.route("**/api/positions", (r) => { seen.books++; return json(r, book, status); });
  await page.route("**/api/positions/*/scenario*", (r) => {
    seen.scenarios.push(r.request().url());
    const u = new URL(r.request().url());
    const key = decodeURIComponent(u.pathname.split("/")[3]);
    const g = group(key);
    const iv = Number(u.searchParams.get("iv_shift") ?? 0);
    // MOCK: the server's own table, shifted so the test can tell the shifted read from the default one.
    return json(r, { key, as_of: BOOK.as_of, underlying: g.underlying, price: g.price, iv_shift: iv,
      days_forward: Number(u.searchParams.get("days_forward") ?? 0), gross: true, why: null,
      rows: g.analytics.scenario.map((x: any) => ({ ...x, today_pnl_rs: x.today_pnl_rs == null ? null : x.today_pnl_rs + 1000 * iv })) });
  });
  await page.route("**/api/positions/*/levels", async (r) => {
    const m = r.request().method();
    if (m === "PUT") { seen.levelPuts.push({ url: r.request().url(), body: r.request().postDataJSON() }); return json(r, { ok: true }); }
    seen.levelDeletes.push(r.request().url());
    return json(r, { deleted: true });
  });
  await page.route("**/api/fno/margin", (r) => {
    seen.margins.push(r.request().postDataJSON());
    return json(r, { required_margin: 41250.5, initial_margin: 38000, as_of: "2026-10-30", source: "MOCK Zerodha margin calculator" });
  });
  await page.goto(PAGE);
  return seen;
}

test.describe("Open positions workspace (MOCK payload)", () => {
  test("OP-1 headline, tiles and sources come from the payload", async ({ page }) => {
    await open(page);
    const s = BOOK.summary;
    await expect(page.getByTestId("screen-page-positions")).toBeVisible(SLOW);
    await expect(page.getByTestId("positions-headline")).toContainText(`${s.near_stop} ${s.near_stop === 1 ? "position is" : "positions are"} near their stops`);
    await expect(page.getByTestId("positions-open-risk")).toHaveText(rupees(s.open_risk_at_stops_rs));
    await expect(page.getByTestId("positions-near")).toHaveText(String(s.near_stop + s.stop_breached));
    await expect(page.getByTestId("positions-day-realised")).toHaveText("—");
    await expect(page.getByTestId("positions-source-broker")).toHaveCount(BOOK.sources.filter((x: any) => x.source === "broker").length);
    await expect(page.getByTestId("positions-source-paper")).toContainText("Paper");
    await expect(page.getByTestId("positions-read-only")).toHaveText("Nivesh reads positions; it cannot place orders.");
  });

  test("OP-2 broker and paper tables list every group, labelled, with the design's columns", async ({ page }) => {
    await open(page);
    const broker = BOOK.groups.filter((g: any) => g.source === "broker" && g.kind !== "unmapped");
    const paper = BOOK.groups.filter((g: any) => g.source === "paper");
    await expect(page.getByTestId("positions-broker-table").getByTestId("positions-row")).toHaveCount(broker.length, SLOW);
    await expect(page.getByTestId("positions-paper-table").getByTestId("positions-row")).toHaveCount(paper.length);
    for (const h of ["Position", "Qty", "Avg", "LTP", "P&L", "Stop", "Target", "Risk left"]) {
      await expect(page.getByTestId("positions-broker-table").getByRole("columnheader", { name: h, exact: true })).toBeVisible();
    }
    const son = group("broker:SONACOMS");
    const row = page.getByTestId("positions-broker-table").getByRole("row").filter({ has: page.locator('[data-key="broker:SONACOMS"]') });
    await expect(row).toContainText(price(son.price.spot));
    await expect(row).toContainText(price(son.levels.effective_stop));
    await expect(row).toContainText(rupees(son.analytics.payoff.risk_to_stop_rs));
  });

  test("OP-3 a row near its stop is flagged", async ({ page }) => {
    await open(page);
    await expect(page.locator('[data-key="broker:SONACOMS"]').getByTestId("positions-row-flag")).toBeVisible(SLOW);
    await expect(page.locator('[data-key="broker:RELIANCE"]').getByTestId("positions-row-flag")).toHaveCount(0);
  });

  test("OP-4 a futures group shows the loss at the user's stop, never a to-zero figure", async ({ page }) => {
    await open(page);
    await page.locator('[data-key="broker:SONACOMS"]').click();
    const g = group("broker:SONACOMS");
    await expect(page.getByTestId("positions-detail")).toHaveAttribute("data-key", "broker:SONACOMS", SLOW);
    await expect(page.getByTestId("positions-loss-at-stop")).toHaveText(rupees(g.analytics.payoff.loss_at_stop_rs));
    await expect(page.getByTestId("positions-max-loss")).toHaveCount(0);
    await expect(page.getByTestId("positions-warnings").locator('[data-code="near_stop"]')).toBeVisible();
  });

  test("OP-5 shares with no stop say so instead of showing a loss", async ({ page }) => {
    await open(page);
    await page.locator('[data-key="broker:RELIANCE"]').click();
    await expect(page.getByTestId("positions-loss-at-stop-none")).toContainText("Set a stop");
    await expect(page.getByTestId("positions-warnings").locator('[data-code="no_stop"]')).toBeVisible();
  });

  test("OP-6 an options spread shows legs, Greeks, max loss at expiry, breakeven and the payoff chart", async ({ page }) => {
    await open(page);
    await page.locator('[data-key="broker:NIFTY"]').click();
    const g = group("broker:NIFTY");
    await expect(page.getByTestId("positions-leg")).toHaveCount(g.legs.length, SLOW);
    await expect(page.getByTestId("positions-max-loss")).toHaveText(rupees(-g.analytics.payoff.max_loss));
    await expect(page.getByTestId("positions-risk")).toContainText(nf(g.analytics.payoff.breakevens[0], 2, 2));
    await expect(page.getByTestId("positions-greeks")).toContainText(nf(g.analytics.greeks.delta, 2, 2));
    await expect(page.getByTestId("positions-payoff")).toBeVisible();
    await expect(page.getByTestId("positions-payoff-expiry")).toHaveCount(1);
    await expect(page.getByTestId("positions-payoff-today")).toHaveCount(1);
    await expect(page.getByTestId("positions-payoff-spot")).toHaveAttribute("data-value", String(g.price.spot));
  });

  test("OP-7 the scenario table shows the server's rows; a volatility shift asks the server again", async ({ page }) => {
    const seen = await open(page);
    await page.locator('[data-key="broker:NIFTY"]').click();
    const g = group("broker:NIFTY");
    await expect(page.getByTestId("positions-scenario").getByRole("row")).toHaveCount(g.analytics.scenario.length + 1, SLOW);
    expect(seen.scenarios).toHaveLength(0);
    await page.getByTestId("positions-iv-shift").selectOption("3");
    await expect.poll(() => seen.scenarios.length, SLOW).toBe(1);
    expect(seen.scenarios[0]).toContain("iv_shift=3");
    expect(decodeURIComponent(seen.scenarios[0])).toContain("/api/positions/broker:NIFTY/scenario");
  });

  test("OP-8 saving levels sends exactly the body the route takes; a bad number is refused before sending", async ({ page }) => {
    const seen = await open(page);
    await page.locator('[data-key="broker:RELIANCE"]').click();
    await page.getByTestId("positions-stop-input").fill("1300");
    await page.getByTestId("positions-target-input").fill("1500");
    await page.getByTestId("positions-levels-save").click();
    await expect.poll(() => seen.levelPuts.length, SLOW).toBe(1);
    expect(seen.levelPuts[0].url).toContain("/api/positions/RELIANCE/levels");
    expect(seen.levelPuts[0].body).toEqual({ stop: 1300, target: 1500, trail_pct: null });
    await page.getByTestId("positions-stop-input").fill("-4");
    await expect(page.getByTestId("positions-levels-save")).toBeDisabled();
    expect(seen.levelPuts).toHaveLength(1);
  });

  test("OP-9 removing the user's levels calls DELETE; a paper group's levels are read-only", async ({ page }) => {
    const seen = await open(page);
    await page.locator('[data-key="broker:SONACOMS"]').click();
    await page.getByTestId("positions-levels-remove").click();
    await expect.poll(() => seen.levelDeletes.length, SLOW).toBe(1);
    expect(seen.levelDeletes[0]).toContain("/api/positions/SONACOMS/levels");
    await page.locator(`[data-key="${BOOK.groups.find((g: any) => g.source === "paper").key}"]`).click();
    await expect(page.getByTestId("positions-levels-paper")).toBeVisible();
    await expect(page.getByTestId("positions-levels")).toHaveCount(0);
  });

  test("OP-10 margin is asked from Zerodha's calculator with the group's own legs, and shown as a calculation", async ({ page }) => {
    const seen = await open(page);
    await page.locator('[data-key="broker:NIFTY"]').click();
    await page.getByTestId("positions-margin-btn").click();
    await expect(page.getByTestId("positions-margin-value")).toContainText(rupees(41250.5), SLOW);
    expect(seen.margins).toEqual([group("broker:NIFTY").margin_request]);
    await expect(page.getByTestId("positions-margin-value")).toContainText("nothing is placed");
  });

  test("OP-11 Paper and Broker are labelled apart; an unmapped row is listed, not valued", async ({ page }) => {
    await open(page);
    await page.locator('[data-key="broker:RELIANCE"]').click();
    await expect(page.getByTestId("positions-detail-title")).toHaveAttribute("data-source", "broker", SLOW);
    await expect(page.getByTestId("positions-detail-title").getByText("Broker", { exact: true })).toBeVisible();
    const paperKey = BOOK.groups.find((g: any) => g.source === "paper").key;
    await page.locator(`[data-key="${paperKey}"]`).click();
    await expect(page.getByTestId("positions-detail-title")).toHaveAttribute("data-source", "paper");
    await expect(page.getByTestId("positions-detail-title").getByText("Paper", { exact: true })).toBeVisible();
    await expect(page.getByTestId("positions-unmapped")).toContainText("ZZZQQQ");
  });

  test("OP-12 an ended broker session says so with a Reconnect that opens the broker connections", async ({ page }) => {
    const ended = structuredClone(BOOK);
    ended.sources = [{ source: "broker", account_id: "ba1", broker: "icicidirect", broker_display: "ICICI Direct", ok: false,
      error: { code: "BROKER_SESSION_EXPIRED", message: "Your ICICI Direct session has ended. Reconnect the account to continue." }, read_at: null, rows: 0 }, ...BOOK.sources.filter((x: any) => x.source === "paper")];
    ended.groups = BOOK.groups.filter((g: any) => g.source === "paper");
    ended.summary = { ...BOOK.summary, broker_positions: 0, groups: 2, positions: 2, near_stop: 0, stop_breached: 0, without_stop: 0, unmapped_rows: 0 };
    await open(page, ended);
    await expect(page.getByTestId("positions-source-broker")).toContainText("session has ended", SLOW);
    await expect(page.getByTestId("positions-broker-empty")).toContainText("No broker positions could be read");
    await page.getByTestId("positions-reconnect").click();
    await expect(page).toHaveURL(/\/app\/page\/brokers/);
  });

  test("OP-13 no positions anywhere is an empty state, not zero values; a failed read is an error with retry", async ({ page }) => {
    const empty = { ...structuredClone(BOOK), groups: [], summary: { ...BOOK.summary, groups: 0, positions: 0, broker_positions: 0, paper_positions: 0, near_stop: 0, stop_breached: 0, without_stop: 0, unmapped_rows: 0, open_risk_at_stops_rs: null, unrealised_pnl_rs: null, exposure_rs: null } };
    empty.sources = [{ source: "paper", ok: true, error: null, as_of: "2026-10-30" }];
    await open(page, empty);
    await expect(page.getByText("No open positions").first()).toBeVisible(SLOW);
    await expect(page.getByTestId("positions-open-risk")).toHaveCount(0);
    await page.unroute("**/api/positions");
    await page.route("**/api/positions", (r) => json(r, { detail: "boom" }, 500));
    await page.getByTestId("positions-refresh").click();
    await expect(page.getByText("Your positions didn’t load")).toBeVisible(SLOW);
  });

  test("OP-14 the portfolio ledger shows the open-position count and links here; 390 px has no sideways scroll", async ({ page }) => {
    const seen = await open(page);
    await page.goto("/v5/app/page/ledger");
    await expect(page.getByTestId("ledger-open-positions")).toHaveText(String(BOOK.summary.positions), SLOW);
    await page.getByTestId("ledger-open-positions-link").click();
    await expect(page).toHaveURL(/\/app\/page\/positions/);
    expect(seen.books).toBeGreaterThan(0);
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto(PAGE);
    await page.locator('[data-key="broker:NIFTY"]').click();
    await expect(page.getByTestId("positions-payoff")).toBeVisible(SLOW);
    const { sw, cw } = await page.evaluate(() => ({ sw: document.documentElement.scrollWidth, cw: document.documentElement.clientWidth }));
    expect(sw, "page is wider than the screen").toBeLessThanOrEqual(cw);
  });
});
