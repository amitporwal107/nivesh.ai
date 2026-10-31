/**
 * One-screen Copilot app (/v5/app) — the sector rotation answer (owner, 31 Oct 2026: "its a sector rotation intent so load the
 * sector rotation heatmap", "show the top 5 stocks of each sector"): the heatmap first, leaders first; a tile with stocks is
 * selectable and shows its strongest stocks by the day's move under the grid (the leading sector's already open); a stock's
 * Ask › asks its trade plan. SE-1 … SE-6 of test_reports/copilot_sector_rotation_20261031.md.
 *
 * Payload: `e2e/fixtures/sector-rotation.mock.json` — MOCK, not real data: the real builder over the unit tests' invented inputs
 * (backend/tests/test_copilot_visual.py, SR-*). Every expected value is computed from the payload itself. Mocked APIs,
 * production build (pw.copilot-app.config.ts).
 */
import { test, expect, type Locator, type Page, type Route } from "@playwright/test";
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";
import { mockApi, mockSingleRoute } from "../helpers/api-mock";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const FIX = path.join(__dirname, "..", "fixtures");
type Payload = Record<string, any>;
const P: Payload = JSON.parse(fs.readFileSync(path.join(FIX, "sector-rotation.mock.json"), "utf-8")).payloads.sector_rotation;
const HEAT = P.blocks.find((b: any) => b.type === "heatmap");
const APP = "/v5/app";
const SLOW = { timeout: 15_000 };
const SHOTS = process.env.SR_SHOTS ? path.join(__dirname, "..", ".shots", "sector-rotation") : null;

const MINUS = "−";
const nf = (n: number, min: number, max: number) => new Intl.NumberFormat("en-IN", { minimumFractionDigits: min, maximumFractionDigits: max }).format(n);
const fPct = (n: number | null) => (n == null ? "—" : `${n > 0 ? "+" : n < 0 ? MINUS : ""}${nf(Math.abs(n), 2, 2)}%`);

const json = (route: Route, body: unknown, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
const sse = (frames: Array<Record<string, unknown>>) => frames.map((f) => `data: ${JSON.stringify(f)}\n\n`).join("");
const ANSWER = "MOCK answer text, written from the payload's facts.";

async function chat(page: Page, asked: string[]) {
  const saved: unknown[] = [];
  const w = { widget_type: "visual_answer", title: P.title, data: P,
    freshness: { state: "end_of_day", last_updated: "2026-10-30T04:50:00+05:30", source: ["NIDP"] }, agent: { id: "market_analyst", confidence: null } };
  await page.route("**/api/chat/sessions", (r) => r.request().method() === "POST" ? json(r, { session_id: "new1", id: "new1" }) : json(r, []));
  await page.route("**/api/chat/messages*", (r) => json(r, saved));
  await page.route("**/api/chat/suggest-queries*", (r) => json(r, { suggestions: [] }));
  await page.route("**/api/chat/instrument-search*", (r) => json(r, { stocks: [], funds: [] }));
  await page.route("**/api/chat/stream", (r) => {
    const body = r.request().postDataJSON() as { message: string };
    asked.push(body.message);
    const n = asked.length;
    saved.push({ message_id: `u${n}`, session_id: "new1", role: "user", content: body.message, created_at: "2026-10-30T04:50:00+00:00" },
      { message_id: `a${n}`, session_id: "new1", role: "assistant", content: ANSWER, created_at: "2026-10-30T04:50:05+00:00", widget: w });
    return r.fulfill({ status: 200, contentType: "text/event-stream", body: sse([
      { type: "meta", session_id: "new1", ai_msg_id: `a${n}`, user_msg_id: `u${n}` }, { type: "route", agent: "market_analyst", confidence: 0.9 },
      { type: "widget", ...w }, { type: "token", content: ANSWER }, { type: "done", content: ANSWER, follow_ups: [] }]) });
  });
}

async function open(page: Page, width?: number): Promise<{ va: Locator; asked: string[] }> {
  if (width) await page.setViewportSize({ width, height: 900 });
  await mockApi(page, "populated");
  await mockSingleRoute(page, "**/api/markets/home", "markets-home.json");
  const asked: string[] = [];
  await chat(page, asked);
  await page.goto(APP);
  await page.getByTestId("composer-input").fill("Which sectors are leading and lagging?");
  await page.getByTestId("composer-input").press("Enter");
  await expect(page.getByTestId("thread-turn").first()).toHaveAttribute("data-state", "saved", SLOW);
  const va = page.getByTestId("va").first();
  await expect(va).toBeVisible(SLOW);
  return { va, asked };
}

const tile = (va: Locator, label: string) => va.locator(`[data-testid="va-heat-cell"][data-label="${label}"]`);
const membersOf = (label: string) => HEAT.cells.find((c: any) => c.label === label).members as Array<{ label: string; value: number; sub?: string; ask?: string }>;

test.describe("Sector rotation (MOCK payload from the real builder)", () => {
  test("SE-1 the heatmap comes first (after the leaders strip), tiles best first with their 1d and 1m beside them", async ({ page }) => {
    const { va } = await open(page);
    await expect(va.getByTestId("va-block")).toHaveCount(P.blocks.length);
    await expect(va.getByTestId("va-block").nth(0)).toHaveAttribute("data-type", "kpis");
    await expect(va.getByTestId("va-block").nth(1)).toHaveAttribute("data-type", "heatmap");
    await expect(va.getByTestId("va-heat-label")).toHaveText(HEAT.cells.map((c: any) => c.label));
    await expect(va.getByTestId("va-heat-value")).toHaveText(HEAT.cells.map((c: any) => fPct(c.value)));
    for (const c of HEAT.cells) if (c.sub) await expect(tile(va, c.label)).toContainText(c.sub);
    await expect(va.getByTestId("va-block-note")).toHaveText(HEAT.note);
    await expect(va.getByTestId("va-kpi-label")).toHaveText(P.blocks[0].items.map((i: any) => i.label));
    await expect(va.getByTestId("va-kpi-value")).toHaveText(P.blocks[0].items.map((i: any) => i.value));
  });

  test("SE-2 the leading sector's strongest stocks are on the screen without a click", async ({ page }) => {
    const { va } = await open(page);
    const lead = HEAT.cells[0];
    const panel = va.getByTestId("va-heat-members");
    await expect(panel).toHaveAttribute("data-sector", lead.label);
    await expect(panel).toContainText(`Top ${lead.members.length} in ${lead.label} · by the day's move`);
    await expect(panel.getByTestId("va-heat-member-label")).toHaveText(lead.members.map((m: any) => m.label));
    await expect(panel.getByTestId("va-heat-member-value")).toHaveText(lead.members.map((m: any) => fPct(m.value)));
    await expect(tile(va, lead.label)).toHaveAttribute("data-selected", "1");
  });

  test("SE-3 selecting another sector shows its five; selecting it again hides them; Enter works from the keyboard", async ({ page }) => {
    const { va } = await open(page);
    const other = HEAT.cells.find((c: any, i: number) => i > 0 && c.members?.length);
    await tile(va, other.label).click();
    await expect(va.getByTestId("va-heat-members")).toHaveAttribute("data-sector", other.label);
    await expect(va.getByTestId("va-heat-member-label")).toHaveText(membersOf(other.label).map((m) => m.label));
    expect(membersOf(other.label).length).toBeLessThanOrEqual(5);
    await tile(va, other.label).click();
    await expect(va.getByTestId("va-heat-members")).toHaveCount(0);
    await tile(va, other.label).focus();
    await page.keyboard.press("Enter");
    await expect(va.getByTestId("va-heat-members")).toHaveAttribute("data-sector", other.label);
  });

  test("SE-4 a stock's Ask › asks its trade plan; a sector with no stocks read is a plain tile", async ({ page }) => {
    const { va, asked } = await open(page);
    const lead = HEAT.cells[0];
    await va.getByTestId("va-heat-member-ask").first().click();
    await expect.poll(() => asked.length, SLOW).toBe(2);
    expect(asked[1]).toBe(lead.members[0].ask);
    const plain = HEAT.cells.find((c: any) => !c.members?.length);
    expect(plain).toBeTruthy();
    await expect(tile(va, plain.label)).toHaveAttribute("data-selectable", "0");
    await expect(tile(va, plain.label)).not.toHaveAttribute("role", "button");
  });

  test("SE-5 on a phone the tiles and the stock list fit and nothing scrolls sideways", async ({ page }) => {
    const { va } = await open(page, 390);
    await expect(va.getByTestId("va-heat-members")).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
    if (SHOTS) { fs.mkdirSync(SHOTS, { recursive: true }); await va.screenshot({ path: path.join(SHOTS, "phone.png") }); }
  });

  test("SE-6 screenshot at desktop width (only with SR_SHOTS=1)", async ({ page }) => {
    test.skip(!SHOTS, "set SR_SHOTS=1");
    const { va } = await open(page, 1500);
    fs.mkdirSync(SHOTS as string, { recursive: true });
    await va.screenshot({ path: path.join(SHOTS as string, "desktop.png") });
  });
});
