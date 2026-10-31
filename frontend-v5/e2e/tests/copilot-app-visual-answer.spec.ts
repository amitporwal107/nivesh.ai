/**
 * One-screen Copilot app (/v5/app) — the Daily Trader Copilot's visual answer (`visual_answer`,
 * src/components/chat/visual/VisualAnswer.tsx; contract docs/daily_trader_copilot/VISUAL_ANSWER_CONTRACT.md): VA-1 …
 * VA-16 of test_reports/dtc_visual_frontend_20261030.md.
 *
 * Payloads: `e2e/fixtures/contract-visual-answer.json` (the backend's real capture) when it exists, else
 * `e2e/fixtures/visual-answer.mock.json` — MOCK — not real data. Both are `{ about, payloads: { <intent>: payload } }`
 * (an array of payloads is accepted too). Every expected value below is computed from the payload itself with the
 * contract's formats, never copied from the screen. The chat stream and the other routes are inline MOCKs in the real
 * route's shape (backend/routes/chat.py stream_chat sends the payload as a `widget` frame); the trade plan is
 * `contract-decision-card.json`'s. Mocked APIs, production build (pw.copilot-app.config.ts).
 */
import { test, expect, type Locator, type Page, type Route } from "@playwright/test";
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";
import { mockApi, mockSingleRoute } from "../helpers/api-mock";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const FIX = path.join(__dirname, "..", "fixtures");
const REAL = path.join(FIX, "contract-visual-answer.json");
const SOURCE = fs.existsSync(REAL) ? REAL : path.join(FIX, "visual-answer.mock.json");
const RAW = JSON.parse(fs.readFileSync(SOURCE, "utf-8"));
type Payload = Record<string, any>;
const PAYLOADS: Record<string, Payload> = Array.isArray(RAW)
  ? Object.fromEntries(RAW.map((p: Payload) => [p.intent, p]))
  : Array.isArray(RAW.payloads) ? Object.fromEntries(RAW.payloads.map((p: Payload) => [p.intent, p])) : RAW.payloads;
const INTENTS = ["market_view", "smart_money", "top_opportunities", "breakouts", "unusual_volume", "stock_decision", "expected_move",
  "open_trades", "fno_setups", "trade_validity", "exit_options", "position_size", "daily_review", "sector_rotation", "results_calendar", "event_intelligence"]
  .filter((i) => PAYLOADS[i]);
const CARD = JSON.parse(fs.readFileSync(path.join(FIX, "contract-decision-card.json"), "utf-8"));
const PLANS: Record<string, unknown> = {
  [CARD.cash.trade_plan_response.plan.plan_id]: CARD.cash.trade_plan_response,
  [CARD.fno.trade_plan_response.plan.plan_id]: CARD.fno.trade_plan_response,
};
const APP = "/v5/app";
const DESK = `${APP}/trader/desk`;
const SLOW = { timeout: 15_000 };
// VA_SHOTS=1 writes to e2e/.shots/visual-answer; any other value names its own folder (visual-answer-<value>).
const SHOTS = process.env.VA_SHOTS ? path.join(__dirname, "..", ".shots", process.env.VA_SHOTS === "1" ? "visual-answer" : `visual-answer-${process.env.VA_SHOTS}`) : null;

// ── the contract's formats (written here from the contract, not imported from the app) ──────────────────────────────
const MINUS = "−";
const nf = (n: number, min: number, max: number) => new Intl.NumberFormat("en-IN", { minimumFractionDigits: min, maximumFractionDigits: max }).format(n);
const sign = (n: number) => (n > 0 ? "+" : n < 0 ? MINUS : "");
const fPrice = (n: number | null) => (n == null ? "—" : n < 0 ? `${MINUS}₹${nf(-n, 2, 2)}` : `₹${nf(n, 2, 2)}`);   // a loss: "−₹14,406.00", never "₹-14,406.00" (owner, 31 Oct)
const fPct = (n: number | null) => (n == null ? "—" : `${sign(n)}${nf(Math.abs(n), 2, 2)}%`);
const fX = (n: number | null) => (n == null ? "—" : `${n < 0 ? MINUS : ""}${nf(Math.abs(n), 1, 2)}×`);
const fInt = (n: number | null) => (n == null ? "—" : `${n < 0 ? MINUS : ""}${nf(Math.abs(Math.round(n)), 0, 0)}`);
const fCr = (n: number | null) => (n == null ? "—" : `${sign(n)}₹${nf(Math.abs(n), 2, 2)} Cr`);
const fRs = (n: number | null) => (n == null ? "—" : `${sign(n)}₹${nf(Math.abs(n), 2, 2)}`);
const fUnit = (n: number | null, unit: string) => unit === "₹" ? fRs(n) : unit === "₹ Cr" ? fCr(n) : unit === "%" ? fPct(n) : unit === "×" ? fX(n) : unit === "count" ? fInt(n)
  : n == null ? "—" : `${n < 0 ? MINUS : ""}${nf(Math.abs(n), 0, 2)} ${unit}`.trim();
const fCell = (v: unknown, format?: string) => v == null ? "—" : typeof v === "boolean" ? (v ? "Yes" : "No") : typeof v === "string" ? v
  : format === "price" ? fPrice(v as number) : format === "pct" ? fPct(v as number) : format === "x" ? fX(v as number) : format === "int" ? fInt(v as number) : nf(v as number, 0, 2);
const fDay = (iso: string) => new Date(`${iso}T12:00:00+05:30`).toLocaleDateString("en-IN", { timeZone: "Asia/Kolkata", day: "numeric", month: "short", year: "numeric" });
const MODE: Record<string, string> = { live: "Live", eod: "End of day", mixed: "Mixed: live and end of day" };
const LABEL: Record<string, string> = { setup_ready: "Setup ready", wait: "Wait", avoid: "Avoid", no_setup: "No setup yet", info: "For information" };
const heatTone = (v: number | null) => (v == null ? "none" : Math.abs(v) < 0.05 ? "flat" : v > 0 ? "up" : "down");
const barTone = (v: number | null, t?: string) => t ?? (v == null || v === 0 ? "neutral" : v > 0 ? "up" : "down");
const corner = (x: number, y: number) => (x >= 0 ? (y >= 0 ? "tr" : "br") : y >= 0 ? "tl" : "bl");

const json = (route: Route, body: unknown, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
const sse = (frames: Array<Record<string, unknown>>) => frames.map((f) => `data: ${JSON.stringify(f)}\n\n`).join("");
const ANSWER = "MOCK answer text, written from the payload's facts.";
const widget = (p: Payload) => ({ widget_type: "visual_answer", title: p.title, data: p,
  freshness: { state: "end_of_day", last_updated: "2026-10-30T04:50:00+05:30", source: ["NIDP"] }, agent: { id: "market_analyst", confidence: null } });

interface Seen { streams: Array<{ message: string; persona?: string; surface?: string }> }

/** Chat routes, stateful like the real backend; every question is answered with `payload()`. */
async function chat(page: Page, payload: () => unknown): Promise<Seen> {
  const seen: Seen = { streams: [] };
  const saved: unknown[] = [];
  await page.route("**/api/desk/trade-plans/*", (r) => {
    const id = decodeURIComponent(new URL(r.request().url()).pathname.split("/").pop() as string);
    if (PLANS[id]) return json(r, PLANS[id]);
    // The real capture's plan ids (staging's own TradePlans) are served the decision-card fixture's plan under the asked
    // id — MOCK, not that plan's data: the card's content is covered by copilot-app-desk-decision-cards.spec.ts, and
    // here only the payload's plan_id → card link is checked.
    if (SOURCE === REAL && /^tp_[0-9a-f]{16}$/.test(id)) {
      const own = CARD.cash.trade_plan_response.plan.plan_id as string;
      return json(r, JSON.parse(JSON.stringify(CARD.cash.trade_plan_response).split(own).join(id)));
    }
    return json(r, { detail: "plan_not_found" }, 404);
  });
  await page.route("**/api/desk/paper-account", (r) => json(r, { ...CARD.paper_account, stored: true }));
  await page.route("**/api/risk/profile", (r) => json(r, CARD.risk_profile_default));
  await page.route("**/api/chat/sessions", (r) => r.request().method() === "POST" ? json(r, { session_id: "new1", id: "new1" }) : json(r, []));
  await page.route("**/api/chat/messages*", (r) => json(r, saved));
  await page.route("**/api/chat/suggest-queries*", (r) => json(r, { suggestions: [] }));
  await page.route("**/api/chat/instrument-search*", (r) => json(r, { stocks: [], funds: [] }));
  await page.route("**/api/chat/stream", (r) => {
    const body = r.request().postDataJSON() as { message: string; persona?: string; surface?: string };
    seen.streams.push(body);
    const n = seen.streams.length;
    const p = payload() as Payload;
    const w = widget(p);
    saved.push({ message_id: `u${n}`, session_id: "new1", role: "user", content: body.message, created_at: "2026-10-30T04:50:00+00:00" },
      { message_id: `a${n}`, session_id: "new1", role: "assistant", content: ANSWER, created_at: "2026-10-30T04:50:05+00:00", widget: w });
    return r.fulfill({ status: 200, contentType: "text/event-stream", body: sse([
      { type: "meta", session_id: "new1", ai_msg_id: `a${n}`, user_msg_id: `u${n}` },
      { type: "route", agent: "market_analyst", confidence: 0.9 },
      { type: "widget", ...w },
      { type: "token", content: ANSWER },
      { type: "done", content: ANSWER, follow_ups: [] },
    ]) });
  });
  return seen;
}

async function askInThread(page: Page, payload: unknown, question = "What is the market view today?") {
  await mockApi(page, "populated");
  await mockSingleRoute(page, "**/api/markets/home", "markets-home.json");
  const seen = await chat(page, () => payload);
  await page.goto(APP);
  await page.getByTestId("composer-input").fill(question);
  await page.getByTestId("composer-input").press("Enter");
  await expect(page.getByTestId("thread-turn").first()).toHaveAttribute("data-state", "saved", SLOW);
  await expect(page.getByTestId("va").first()).toBeVisible(SLOW);
  return seen;
}

/** Every block of the payload, in order, drawn with the payload's own numbers. */
async function expectBlocks(va: Locator, p: Payload) {
  const frames = va.getByTestId("va-block");
  await expect(frames).toHaveCount(p.blocks.length);
  for (let i = 0; i < p.blocks.length; i++) {
    const b = p.blocks[i];
    const f = frames.nth(i);
    await expect(f, `block ${i} (${b.type})`).toHaveAttribute("data-type", b.type);
    if (b.title) await expect(f.getByTestId("va-block-title")).toHaveText(b.title);
    switch (b.type) {
      case "kpis":
        await expect(f.getByTestId("va-kpi-label")).toHaveText(b.items.map((it: any) => it.label));
        await expect(f.getByTestId("va-kpi-value")).toHaveText(b.items.map((it: any) => (it.value == null || it.value === "" ? "—" : typeof it.value === "number" ? nf(it.value, 0, 2) : it.value)));
        break;
      case "candles": {
        await expect(f.getByTestId("desk-candle")).toHaveCount(b.bars.length);
        const last = b.bars[b.bars.length - 1];
        await expect(f.getByTestId("va-candles-history")).toHaveText(
          `History: ${b.bars.length} daily candles of ${b.symbol}, ${fDay(b.bars[0].d)} to ${fDay(last.d)}; last close ${fPrice(last.c)}.`);
        const levels = b.levels ?? [];
        // A label that already carries its price is not followed by it again.
        await expect(f.getByTestId("va-level-price")).toHaveText(levels.filter((l: any) => !(l.label ?? "").includes(fPrice(l.price).replace(/^₹/, ""))).map((l: any) => fPrice(l.price)));
        for (let k = 0; k < levels.length; k++) {
          await expect(f.getByTestId(`desk-level-${levels[k].kind}-${k}`)).toHaveAttribute("data-value", String(levels[k].price));
        }
        if (b.band) {
          await expect(f.getByTestId("desk-band")).toHaveAttribute("data-low", String(b.band.low));
          await expect(f.getByTestId("desk-band")).toHaveAttribute("data-high", String(b.band.high));
          await expect(f.getByTestId("va-band-range")).toHaveText(`${fPrice(b.band.low)} – ${fPrice(b.band.high)}`);
        } else {
          await expect(f.getByTestId("desk-band")).toHaveCount(0);
        }
        for (const e of ["ema20", "ema50", "ema200"]) {
          const has = (b.overlays?.[e] ?? []).some((v: number | null) => v != null);
          await expect(f.getByTestId(`desk-line-${e}`)).toHaveCount(has ? 1 : 0);
        }
        break;
      }
      case "bars": {
        await expect(f.getByTestId("va-bar")).toHaveCount(b.items.length);
        await expect(f.getByTestId("va-bar-value")).toHaveText(b.items.map((it: any) => fUnit(it.value, b.unit)));
        await expect(f.getByTestId("va-bars")).toHaveAttribute("data-orientation", b.orientation);
        for (let k = 0; k < b.items.length; k++) {
          await expect(f.getByTestId("va-bar").nth(k)).toHaveAttribute("data-tone", barTone(b.items[k].value, b.items[k].tone));
        }
        await expect(f.getByTestId("va-bars-baseline")).toHaveCount(b.baseline != null && b.baseline !== 0 ? 1 : 0);
        break;
      }
      case "heatmap":
        await expect(f.getByTestId("va-heat-label")).toHaveText(b.cells.map((c: any) => c.label));
        await expect(f.getByTestId("va-heat-value")).toHaveText(b.cells.map((c: any) => fUnit(c.value, b.unit)));
        for (let k = 0; k < b.cells.length; k++) {
          await expect(f.getByTestId("va-heat-cell").nth(k)).toHaveAttribute("data-tone", heatTone(b.cells[k].value));
        }
        break;
      case "quadrant": {
        await expect(f.getByTestId("va-quadrant-point")).toHaveCount(b.points.length);
        for (const c of ["tr", "tl", "br", "bl"]) await expect(f.locator(`[data-testid="va-quadrant-name"][data-corner="${c}"]`)).toHaveText(b.quadrants[c]);
        await expect(f.getByTestId("va-quadrant-row")).toHaveCount(b.points.length);
        for (const pt of b.points) {
          const row = f.locator(`[data-testid="va-quadrant-group"][data-corner="${corner(pt.x, pt.y)}"] [data-testid="va-quadrant-row"][data-label="${pt.label}"]`);
          await expect(row.getByTestId("va-quadrant-x")).toHaveText(fUnit(pt.x, b.x.unit));
          await expect(row.getByTestId("va-quadrant-y")).toHaveText(fUnit(pt.y, b.y.unit));
        }
        break;
      }
      case "ranked": {
        const rows = f.getByTestId("va-ranked-row");
        await expect(rows).toHaveCount(b.rows.length);
        const cards = (await f.getByTestId("va-ranked").getAttribute("data-layout")) === "cards";
        for (let k = 0; k < b.rows.length; k++) {
          for (const c of b.columns) {
            if (cards && c.key === "symbol") continue;          // a card shows the symbol as its heading
            await expect(rows.nth(k).getByTestId(`va-cell-${c.key}`), `${b.id} row ${k} ${c.key}`).toHaveText(fCell(b.rows[k].cells[c.key], c.format));
          }
          if (cards && b.rows[k].symbol) await expect(rows.nth(k).locator("strong").first()).toHaveText(b.rows[k].symbol);
          await expect(rows.nth(k).getByTestId("va-row-ask")).toHaveCount(b.rows[k].ask ? 1 : 0);
          await expect(rows.nth(k).getByTestId("va-row-plan")).toHaveCount(b.rows[k].plan_id ? 1 : 0);
        }
        break;
      }
      case "trade_plan":
        await expect(f.getByTestId("va-plan")).toHaveAttribute("data-plan-id", b.plan_id, SLOW);
        await expect(f.getByTestId("va-plan")).toHaveAttribute("data-variant", "row");
        break;
      case "list":
        await expect(f.getByTestId("va-list-text")).toHaveText(b.items.map((it: any) => `${it.tone === "warn" ? "Warning: " : ""}${it.text}`));
        break;
      case "briefs": {
        const cards = f.getByTestId("va-brief");
        await expect(cards).toHaveCount(b.items.length);
        for (let k = 0; k < b.items.length; k++) {
          const it = b.items[k];
          await expect(cards.nth(k).getByTestId("va-brief-title")).toHaveText(it.title);
          if (it.body) await expect(cards.nth(k).getByTestId("va-brief-body")).toHaveText(it.body);   // the stored summary, verbatim
          else await expect(cards.nth(k).getByTestId("va-brief-empty")).toHaveText(it.body_note || "Not analysed yet");
          await expect(cards.nth(k).getByTestId("va-brief-link")).toHaveCount((it.links ?? []).length);
          for (let j = 0; j < (it.links ?? []).length; j++) await expect(cards.nth(k).getByTestId("va-brief-link").nth(j)).toHaveAttribute("href", it.links[j].url);
        }
        break;
      }
      case "notice":
        await expect(f.getByTestId("va-notice")).toHaveAttribute("data-tone", b.tone);
        await expect(f.getByTestId("va-notice-text")).toHaveText(b.text);
        break;
    }
    if (b.note) await expect(f.getByTestId("va-block-note")).toHaveText(b.note);
  }
}

async function expectAnswer(va: Locator, p: Payload) {
  await expect(va).toHaveAttribute("data-intent", p.intent);
  await expect(va.getByTestId("va-title")).toHaveText(p.title);
  if (p.as_of) await expect(va.getByTestId("va-asof-day")).toHaveText(fDay(p.as_of));
  if (p.mode) await expect(va.getByTestId("va-mode")).toHaveText(MODE[p.mode]);
  if (p.headline) await expect(va.getByTestId("va-headline")).toHaveText(p.headline.text);
  // decision
  if (p.decision) {
    const d = p.decision;
    await expect(va.getByTestId("va-decision")).toHaveAttribute("data-status", d.status);
    await expect(va.getByTestId("va-decision-label")).toHaveText(d.label || LABEL[d.status]);
    if (d.reason) await expect(va.getByTestId("va-decision-reason")).toHaveText(d.reason);
    await expect(va.getByTestId("va-condition")).toHaveCount((d.conditions ?? []).length);
    for (let k = 0; k < (d.conditions ?? []).length; k++) {
      const c = d.conditions[k];
      await expect(va.getByTestId("va-condition-state").nth(k)).toHaveText(`(${c.met === true ? "met" : c.met === false ? "not met" : "not known"})`);
    }
    if (d.invalidation) await expect(va.getByTestId("va-invalidation")).toHaveText(`Wrong if: ${d.invalidation}`);
  } else {
    await expect(va.getByTestId("va-decision")).toHaveCount(0);
  }
  await expectBlocks(va, p);
  // evidence, data quality, follow-ups, caveat
  await expect(va.getByTestId("va-evidence-value")).toHaveText((p.evidence ?? []).map((e: any) => (e.value == null ? "—" : String(e.value))));
  const sources = p.data_quality?.sources ?? [];
  await expect(va.getByTestId("va-source-name")).toHaveText(sources.map((s: any) => s.name));
  await expect(va.getByTestId("va-source-asof")).toHaveText(sources.map((s: any) => (s.as_of ? fDay(s.as_of) : "no date")));
  await expect(va.getByTestId("va-source")).toHaveText(sources.map((s: any) => new RegExp(`^.{0,3}${{ fresh: "Fresh", stale: "Stale", missing: "Missing" }[s.status as string] ?? s.status}`)));
  const stale = !!p.data_quality?.stale || sources.some((s: any) => s.status === "stale");
  await expect(va).toHaveAttribute("data-stale", String(stale));
  await expect(va.getByTestId("va-stale-banner")).toHaveCount(stale ? 1 : 0);
  for (const s of sources.filter((x: any) => x.status === "stale")) await expect(va.getByTestId("va-stale-banner")).toContainText(`${s.name} (${s.as_of ? fDay(s.as_of) : "date unknown"})`);
  await expect(va.getByTestId("va-missing-item")).toHaveText(p.data_quality?.missing ?? []);
  await expect(va.getByTestId("va-followup")).toHaveText((p.follow_ups ?? []).map((f: any) => `${f.label} ›`));
  if (p.caveat) await expect(va.getByTestId("va-caveat")).toHaveText(p.caveat);
  await expect(va.getByTestId("va-block-unsupported")).toHaveCount(0);
  await expect(va.getByTestId("va-block-bad")).toHaveCount(0);
  await expect(va.getByTestId("va-block-failed")).toHaveCount(0);
  await expect(va).not.toContainText(/\b(buy now|strong buy|recommended|pick)\b/i);
}

/** Review screenshots, one per part of the answer: each part is scrolled to the middle of the thread first, so a tall
 *  answer is not clipped by its scrolling container or hidden under a sticky header. */
async function shootParts(va: Locator, prefix: string) {
  if (!SHOTS) return;
  const parts = va.locator(':scope > header, :scope > [data-testid="va-stale-banner"], :scope > [data-testid="va-decision"], :scope > [data-testid="va-block"], :scope > [data-testid="va-data-quality"]');
  const n = await parts.count();
  for (let i = 0; i < n; i++) {
    const part = parts.nth(i);
    await part.evaluate((e) => e.scrollIntoView({ block: "center" }));
    const name = (await part.getAttribute("data-type")) ?? (await part.getAttribute("data-testid")) ?? "header";
    await part.screenshot({ path: path.join(SHOTS, `${prefix}-${String(i).padStart(2, "0")}-${name}.png`) });
  }
}

async function noSideScroll(page: Page) {
  const { sw, cw } = await page.evaluate(() => ({ sw: document.documentElement.scrollWidth, cw: document.documentElement.clientWidth }));
  expect(sw, "page is wider than the screen").toBeLessThanOrEqual(cw);
}

test.describe(`visual answer (${path.basename(SOURCE)}${SOURCE === REAL ? "" : ": MOCK — not real data"})`, () => {
  for (const intent of INTENTS) {
    test(`VA-1…11/16 ${intent}: every part of the payload, with the payload's own numbers`, async ({ page }) => {
      const p = PAYLOADS[intent];
      await askInThread(page, p);
      await expectAnswer(page.getByTestId("va"), p);
      await expect(page.getByTestId("answer-text")).toContainText(ANSWER);
    });
  }

  test("VA-12 a follow-up button asks its question; a ranked row's Ask asks the row's question", async ({ page }) => {
    const p = PAYLOADS.smart_money ?? PAYLOADS[INTENTS[0]];
    const seen = await askInThread(page, p, "Where is smart money moving?");
    const asks: string[] = ["Where is smart money moving?"];
    if (p.follow_ups?.length) {
      await page.getByTestId("va-followup").first().click();
      asks.push(p.follow_ups[0].query);
      await expect.poll(() => seen.streams.map((s) => s.message), SLOW).toEqual(asks);
      await expect(page.getByTestId("thread-turn")).toHaveCount(2, SLOW);
      await expect(page.getByTestId("thread-turn").nth(1)).toHaveAttribute("data-state", "saved", SLOW);
    }
    const ranked = p.blocks.find((b: any) => b.type === "ranked" && b.rows.some((r: any) => r.ask));
    if (ranked) {
      const k = ranked.rows.findIndex((r: any) => r.ask);
      const turn = page.getByTestId("thread-turn").last();
      await turn.locator(`[data-testid="va-block"][data-block-id="${ranked.id}"]`).getByTestId("va-ranked-row").nth(k).getByTestId("va-row-ask").click();
      asks.push(ranked.rows[k].ask);
      await expect.poll(() => seen.streams.map((s) => s.message), SLOW).toEqual(asks);
    }
  });

  test("VA-7 a ranked row with a plan id opens the desk's plan card for that id", async ({ page }) => {
    const intent = INTENTS.find((i) => PAYLOADS[i].blocks.some((b: any) => b.type === "ranked" && b.rows.some((r: any) => r.plan_id)));
    test.skip(!intent, "no ranked row with a plan id in these payloads");
    const p = PAYLOADS[intent as string];
    const ranked = p.blocks.find((b: any) => b.type === "ranked" && b.rows.some((r: any) => r.plan_id));
    const k = ranked.rows.findIndex((r: any) => r.plan_id);
    await askInThread(page, p);
    const row = page.locator(`[data-testid="va-block"][data-block-id="${ranked.id}"]`).getByTestId("va-ranked-row").nth(k);
    await row.getByTestId("va-row-plan").click();
    await expect(page.getByTestId("va-row-plan-card")).toHaveAttribute("data-plan-id", ranked.rows[k].plan_id, SLOW);
    await row.getByTestId("va-row-plan").click();
    await expect(page.getByTestId("va-row-plan-card")).toHaveCount(0);
  });

  test("VA-13 an unknown block says 'not supported yet', a bad one says it could not be shown, and the rest still renders", async ({ page }) => {
    const p = structuredClone(PAYLOADS[INTENTS[0]]);
    const good = p.blocks.length;
    p.blocks.splice(1, 0, { type: "gauge", id: "g", title: "Fear gauge", note: null, value: 42 });
    p.blocks.push({ type: "bars", id: "broken", title: "Broken bars", note: null, unit: "%", orientation: "h", items: "not a list" });
    await askInThread(page, p);
    const va = page.getByTestId("va");
    await expect(va.getByTestId("va-block-unsupported")).toHaveText("Fear gauge: this part of the answer (“gauge”) is not supported yet.");
    await expect(va.getByTestId("va-block-bad")).toContainText("Broken bars: this part of the answer could not be shown");
    await expect(va.getByTestId("va-block")).toHaveCount(good);
    await expect(va.getByTestId("va-title")).toHaveText(p.title);
  });

  test("VA-13b a payload that is not visual-answer-v1 shows a short note; the written answer still shows", async ({ page }) => {
    await mockApi(page, "populated");
    await mockSingleRoute(page, "**/api/markets/home", "markets-home.json");
    await chat(page, () => ({ schema: "visual-answer-v0", title: "Old" }));
    await page.goto(APP);
    await page.getByTestId("composer-input").fill("What is the market view today?");
    await page.getByTestId("composer-input").press("Enter");
    await expect(page.getByTestId("thread-turn").first()).toHaveAttribute("data-state", "saved", SLOW);
    await expect(page.getByTestId("va-invalid")).toContainText("This visual answer could not be shown");
    await expect(page.getByTestId("answer-text")).toContainText(ANSWER);
  });

  test("VA-20 a ₹ bars block (the daily review's equity curve) prints signed rupees, on the axis too — MOCK block", async ({ page }) => {
    // The real capture's account has no closed paper trade, so its daily_review has no curve; this block is the shape
    // backend/services/copilot_visual/builders.py daily_review sends (MOCK — not real data: invented values).
    const p = structuredClone(PAYLOADS.daily_review ?? PAYLOADS[INTENTS[0]]);
    p.blocks.push({ type: "bars", id: "curve", title: "Equity curve: cumulative realised P&L", unit: "₹", orientation: "v",
      note: "MOCK — not real data.", items: [{ label: "20 Oct", value: 95 }, { label: "28 Oct", value: 131 }, { label: "30 Oct", value: -40.5 }] });
    await askInThread(page, p);
    const va = page.getByTestId("va");
    await expectBlocks(va, p);
    const curve = va.locator('[data-testid="va-block"][data-block-id="curve"]');
    await expect(curve.getByTestId("va-bar-value")).toHaveText(["+₹95.00", "+₹131.00", `${MINUS}₹40.50`]);
    await expect(curve.getByTestId("va-bars")).toHaveAttribute("data-unit", "₹");
    await expect(curve.getByTestId("va-bars-svg")).toContainText("₹");
  });

  for (const intent of INTENTS) {
    test(`VA-14 390 px, ${intent}: no sideways scroll; charts drawn at their real width`, async ({ page }) => {
      await page.setViewportSize({ width: 390, height: 844 });
      const p = PAYLOADS[intent];
      await askInThread(page, p);
      const va = page.getByTestId("va");
      await expectBlocks(va, p);
      await noSideScroll(page);
      const vaBox = await va.boundingBox();
      expect(vaBox!.x + vaBox!.width).toBeLessThanOrEqual(390);
      for (const svg of await va.locator('[data-testid="va-bars-svg"], [data-testid="va-quadrant-svg"]').all()) {
        const box = await svg.boundingBox();
        const vb = Number(((await svg.getAttribute("viewBox")) ?? "").split(" ")[2]);
        expect(Math.abs(vb - Math.max(240, box!.width)), "viewBox width = drawn width").toBeLessThanOrEqual(2);
      }
      for (const c of await va.getByTestId("desk-chart-svg").all()) await expect(c).toHaveAttribute("data-compact", "true");
      if (await va.getByTestId("va-ranked").count()) await expect(va.getByTestId("va-ranked").first()).toHaveAttribute("data-layout", "cards");
      await va.page().waitForTimeout(300);
      await shootParts(va, `390-${intent}`);
    });
  }

  test("VA-15 on the trading desk the Copilot dock shows the visual answer inline, compact; its follow-up asks again from the desk", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });                       // the Copilot docks from 1400px
    await mockApi(page, "populated");
    await mockSingleRoute(page, "**/api/markets/home", "markets-home.json");
    await page.route("**/api/move-odds/**", (r) => json(r, { detail: "feature_not_enabled" }, 403));
    await page.route("**/api/desk/paper-trades*", (r) => json(r, { as_of: null, checked_through: null, marks_error: null, trades: [], summary: { open: 0, closed: 0, wins: 0, losses: 0, realized_pnl_rs: null, unrealized_pnl_rs: null, unmarked_open: 0, partial: false } }));
    await page.route("**/api/desk/alerts*", (r) => json(r, { as_of: null, checked_through: null, marks_error: null, alerts: [] }));
    const p = PAYLOADS.stock_decision ?? PAYLOADS[INTENTS[0]];
    const seen = await chat(page, () => p);
    await page.goto(DESK);
    await page.getByTestId("dock-input").fill("Entry, target and stop-loss for ICICIBANK?");
    await page.getByTestId("dock-send").click();
    const dock = page.getByTestId("dock-turn").first();
    const va = dock.getByTestId("va");
    await expect(va).toBeVisible(SLOW);
    await expect(va).toHaveAttribute("data-compact", "true");
    await expectAnswer(va, p);
    await expect(dock).not.toContainText("This answer has a result card");
    expect(seen.streams[0].surface).toBe("trading_desk");
    const dockBox = await page.getByTestId("desk-dock").boundingBox();
    const vaBox = await va.boundingBox();
    expect(vaBox!.x + vaBox!.width).toBeLessThanOrEqual(dockBox!.x + dockBox!.width);
    await shootParts(va, `dock-1440-${p.intent}`);
    if (p.follow_ups?.length) {
      await va.getByTestId("va-followup").first().click();
      await expect.poll(() => seen.streams.map((s) => s.message), SLOW).toEqual(["Entry, target and stop-loss for ICICIBANK?", p.follow_ups[0].query]);
      expect(seen.streams[1].surface).toBe("trading_desk");
    }
  });

  test("VA-19 screenshots at 1440 px (only with VA_SHOTS=1)", async ({ page }) => {
    test.skip(!SHOTS, "set VA_SHOTS=1 to write the review screenshots");
    await page.setViewportSize({ width: 1440, height: 900 });
    let next = INTENTS[0];
    await mockApi(page, "populated");
    await mockSingleRoute(page, "**/api/markets/home", "markets-home.json");
    await chat(page, () => PAYLOADS[next]);
    await page.goto(APP);
    for (let i = 0; i < INTENTS.length; i++) {
      next = INTENTS[i];
      await page.getByTestId("composer-input").fill(`Question ${i + 1}`);
      await page.getByTestId("composer-input").press("Enter");
      const turn = page.getByTestId("thread-turn").nth(i);
      await expect(turn).toHaveAttribute("data-state", "saved", SLOW);
      const va = turn.getByTestId("va");
      await expect(va).toHaveAttribute("data-intent", next, SLOW);
      await page.waitForTimeout(300);                                                // let the charts measure their boxes
      await shootParts(va, `1440-${next}`);
    }
    await noSideScroll(page);
  });
});
