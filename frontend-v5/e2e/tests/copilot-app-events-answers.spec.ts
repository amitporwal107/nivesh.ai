/**
 * One-screen Copilot app (/v5/app) — the results and market-research event answers (owner, 31 Oct 2026): "Which companies report
 * results this week?", "Any order wins this week?", "How were TCS results?" as `briefs` cards (company, the STORED AI summary,
 * management-commentary points on request, source-filing links to download), a "still to report" table, and "Open in Market
 * Intelligence ›". EA-1 … EA-12 of test_reports/copilot_events_answers_20261031.md.
 *
 * Payloads: `e2e/fixtures/events-answers.mock.json` — MOCK, not real data: the real builders (services/copilot_visual/
 * events_builders.py) over the unit tests' invented inputs (tests/test_copilot_events.py). The real staging capture of the same
 * builders is in `contract-visual-answer.json` and is drawn by copilot-app-visual-answer.spec.ts. Every expected value is computed
 * from the payload itself. The chat stream and the other routes are inline MOCKs in the real routes' shape. Mocked APIs,
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
const MOCK: Record<string, Payload> = JSON.parse(fs.readFileSync(path.join(FIX, "events-answers.mock.json"), "utf-8")).payloads;
const APP = "/v5/app";
const SLOW = { timeout: 15_000 };
const SHOTS = process.env.EV_SHOTS ? path.join(__dirname, "..", ".shots", "events-answers") : null;

const json = (route: Route, body: unknown, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
const sse = (frames: Array<Record<string, unknown>>) => frames.map((f) => `data: ${JSON.stringify(f)}\n\n`).join("");
const ANSWER = "MOCK answer text, written from the payload's facts.";
const clone = (p: Payload): Payload => JSON.parse(JSON.stringify(p));
const block = (p: Payload, id: string) => p.blocks.find((b: any) => b.id === id);

async function open(page: Page, p: Payload, opts: { width?: number; question?: string } = {}): Promise<{ va: Locator; asked: string[] }> {
  if (opts.width) await page.setViewportSize({ width: opts.width, height: 900 });
  await mockApi(page, "populated");
  await mockSingleRoute(page, "**/api/markets/home", "markets-home.json");
  const asked: string[] = [];
  const saved: unknown[] = [];
  const w = { widget_type: "visual_answer", title: p.title, data: p,
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
  await page.goto(APP);
  await page.getByTestId("composer-input").fill(opts.question ?? "Which companies report results this week?");
  await page.getByTestId("composer-input").press("Enter");
  await expect(page.getByTestId("thread-turn").first()).toHaveAttribute("data-state", "saved", SLOW);
  const va = page.getByTestId("va").first();
  await expect(va).toBeVisible(SLOW);
  return { va, asked };
}

const frame = (va: Locator, id: string) => va.locator(`[data-testid="va-block"][data-block-id="${id}"]`).first();
const cardOf = (va: Locator, symbol: string) => va.locator(`[data-testid="va-brief"][data-symbol="${symbol}"]`).first();

test.describe("results and event answers (MOCK payloads from the real builders)", () => {
  test("EA-1 the calendar: title, counts and one card per declared result, each the stored summary verbatim", async ({ page }) => {
    const p = MOCK.calendar;
    const { va } = await open(page, p);
    await expect(va).toHaveAttribute("data-intent", "results_calendar");
    await expect(va.getByTestId("va-title")).toHaveText(p.title);
    await expect(va.getByTestId("va-headline")).toHaveText(p.headline.text);
    const kp = block(p, "counts").items;
    await expect(frame(va, "counts").getByTestId("va-kpi-label")).toHaveText(kp.map((i: any) => i.label));
    await expect(frame(va, "counts").getByTestId("va-kpi-value")).toHaveText(kp.map((i: any) => i.value));
    const items = block(p, "declared").items;
    const cards = frame(va, "declared").getByTestId("va-brief");
    await expect(cards).toHaveCount(items.length);
    for (let i = 0; i < items.length; i++) {
      const c = cards.nth(i);
      await expect(c.getByTestId("va-brief-title")).toHaveText(items[i].title);
      await expect(c.getByTestId("va-brief-sub")).toHaveText(items[i].sub);
      await expect(c.getByTestId("va-brief-badge")).toHaveText(new RegExp(items[i].badge.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")));
      await expect(c.getByTestId("va-brief-badge")).toHaveAttribute("data-tone", items[i].tone);
      if (items[i].body) {
        await expect(c.getByTestId("va-brief-body")).toHaveText(items[i].body);
        await expect(c.getByTestId("va-brief-note")).toHaveText(items[i].body_note);
        await expect(c.getByTestId("va-brief-note")).toContainText("Not a recommendation");
      } else {
        await expect(c.getByTestId("va-brief-empty")).toHaveText("Not analysed yet");
      }
    }
    await expect(frame(va, "declared").getByTestId("va-block-note")).toContainText("no analyst consensus");
  });

  test("EA-2 source filings open the exchange's PDF in a new tab, safely, with a label that says what opens", async ({ page }) => {
    const p = MOCK.calendar;
    const { va } = await open(page, p);
    const reli = block(p, "declared").items.find((i: any) => i.symbol === "RELI");
    expect(reli.links.length).toBeGreaterThanOrEqual(2);
    const links = cardOf(va, "RELI").getByTestId("va-brief-link");
    await expect(links).toHaveCount(reli.links.length);
    for (let i = 0; i < reli.links.length; i++) {
      const a = links.nth(i);
      await expect(a).toHaveAttribute("href", reli.links[i].url);
      await expect(a).toHaveAttribute("target", "_blank");
      await expect(a).toHaveAttribute("rel", /noopener/);
      await expect(a).toHaveAttribute("rel", /noreferrer/);
      await expect(a).toContainText(`${reli.links[i].label} ›`);
      expect(reli.links[i].url).toMatch(/^https:\/\/nsearchives\.nseindia\.com\//);
    }
    await expect(links.first()).toContainText("Results filing (PDF) ›");
    // a card with no analysis still carries its filing link (when the data had one) and says so in words
    const empty = block(p, "declared").items.find((i: any) => !i.body);
    expect(empty).toBeTruthy();
    await expect(cardOf(va, empty.symbol).getByTestId("va-brief-empty")).toHaveText("Not analysed yet");
  });

  test("EA-3 management commentary is folded until asked for, then listed with its tone in words", async ({ page }) => {
    const p = MOCK.calendar;
    const { va } = await open(page, p);
    const reli = block(p, "declared").items.find((i: any) => i.symbol === "RELI");
    const card = cardOf(va, "RELI");
    await expect(card.getByTestId("va-brief-points")).toHaveCount(0);
    const btn = card.getByTestId("va-brief-more");
    await expect(btn).toHaveText(`Show commentary (${reli.points.length}) ›`);
    await expect(btn).toHaveAttribute("aria-expanded", "false");
    await btn.click();
    await expect(btn).toHaveAttribute("aria-expanded", "true");
    await expect(btn).toHaveText("Show less");
    const pts = card.getByTestId("va-brief-point");
    await expect(pts).toHaveCount(reli.points.length);
    for (let i = 0; i < reli.points.length; i++) {
      await expect(pts.nth(i)).toHaveAttribute("data-tone", reli.points[i].tone);
      await expect(pts.nth(i)).toContainText(reli.points[i].text);
    }
    expect(await pts.nth(1).innerText()).toContain("Positive");                              // GRM up: said in words, not colour alone
    await btn.click();
    await expect(card.getByTestId("va-brief-points")).toHaveCount(0);
  });

  test("EA-4 a long summary is clamped and expands in place", async ({ page }) => {
    const p = clone(MOCK.calendar);
    const long = "The company reported higher revenue and wider margins in the quarter. ".repeat(12).trim();
    const it = block(p, "declared").items.find((i: any) => i.symbol === "ALPHA");
    it.body = long;
    it.points = [];
    const { va } = await open(page, p);
    const card = cardOf(va, "ALPHA");
    const body = card.getByTestId("va-brief-body");
    const clamped = await body.evaluate((e) => e.scrollHeight > e.clientHeight + 2);
    expect(clamped).toBe(true);
    await card.getByTestId("va-brief-more").click();
    expect(await body.evaluate((e) => e.scrollHeight <= e.clientHeight + 2)).toBe(true);
    await expect(body).toHaveText(long);
  });

  test("EA-5 'still to report' lists F&O names first and each row asks for the company's latest results", async ({ page }) => {
    const p = MOCK.calendar;
    const { va, asked } = await open(page, p);
    const due = block(p, "due");
    const rows = frame(va, "due").getByTestId("va-ranked-row");
    await expect(rows).toHaveCount(due.rows.length);
    expect(await rows.evaluateAll((els) => els.map((e) => e.getAttribute("data-symbol")))).toEqual(due.rows.map((r: any) => r.symbol));
    await rows.first().getByTestId("va-row-ask").click();
    await expect.poll(() => asked.length, SLOW).toBe(2);
    expect(asked[1]).toBe(due.rows[0].ask);
  });

  test("EA-6 'Open in Market Intelligence ›' says what was left out and opens the desk's intel view", async ({ page }) => {
    const p = MOCK.calendar;
    const { va } = await open(page, p);
    const n = block(p, "more");
    await expect(frame(va, "more").getByTestId("va-notice-text")).toHaveText(n.text);
    const act = frame(va, "more").getByTestId("va-notice-action-open_market_intel");
    await expect(act).toHaveText("Open in Market Intelligence");
    await act.click();
    await expect(page).toHaveURL(/\/app\/trader\/desk\?tab=market&view=intel/);
  });

  test("EA-7 a link that is not https on an exchange host is never drawn, whatever the payload says", async ({ page }) => {
    const p = clone(MOCK.calendar);
    const it = block(p, "declared").items.find((i: any) => i.symbol === "RELI");
    const good = it.links.length;
    it.links.push(
      { label: "Forged http", url: "http://nsearchives.nseindia.com/corporate/x.pdf", kind: "pdf" },
      { label: "Look-alike", url: "https://nseindia.com.evil.io/x.pdf", kind: "pdf" },
      { label: "Script", url: "javascript:alert(1)", kind: "pdf" },
      { label: "User info", url: "https://nsearchives.nseindia.com@evil.io/x.pdf", kind: "pdf" },
    );
    const { va } = await open(page, p);
    await expect(cardOf(va, "RELI").getByTestId("va-brief-link")).toHaveCount(good);
    for (const bad of ["evil", "javascript", "Forged", "Look-alike"]) expect(await va.innerHTML()).not.toContain(bad);
  });

  test("EA-8 order wins: cards from the feed, the classifier's tone in words, 'Not analysed yet' keeps its link", async ({ page }) => {
    const p = MOCK.orders;
    const { va } = await open(page, p, { question: "Any order wins this week?" });
    await expect(va).toHaveAttribute("data-intent", "event_intelligence");
    await expect(va.getByTestId("va-title")).toHaveText(p.title);
    const items = block(p, "events").items;
    const cards = frame(va, "events").getByTestId("va-brief");
    await expect(cards).toHaveCount(items.length);
    const first = items[0];
    await expect(cards.first().getByTestId("va-brief-badge")).toHaveText(new RegExp(first.badge.replace(" · ", " · ")));
    await expect(cards.first().getByTestId("va-brief-body")).toHaveText(first.body);
    const unread = items.find((i: any) => !i.body);
    expect(unread).toBeTruthy();
    const c = cardOf(va, unread.symbol);
    await expect(c.getByTestId("va-brief-empty")).toHaveText("Not analysed yet");
    await expect(c.getByTestId("va-brief-link")).toHaveAttribute("href", unread.links[0].url);
    await expect(c.getByTestId("va-brief-link")).toContainText("Source filing (PDF) ›");
    await expect(frame(va, "more").getByTestId("va-notice-text")).toHaveText(block(p, "more").text);
  });

  test("EA-9 one company's results: summary, badge from the desk's verdict, links in order, commentary on request", async ({ page }) => {
    const p = MOCK.tcs;
    const { va } = await open(page, p, { question: "How were TCS results?" });
    const it = block(p, "events").items[0];
    await expect(va.getByTestId("va-title")).toHaveText(p.title);
    await expect(va.getByTestId("va-brief")).toHaveCount(1);
    await expect(va.getByTestId("va-brief-body")).toHaveText(it.body);
    await expect(va.getByTestId("va-brief-badge")).toContainText("Meets expectation");
    await expect(va.getByTestId("va-brief-sub")).toHaveText(it.sub);
    await expect(va.getByTestId("va-brief-link")).toContainText(it.links.map((l: any) => `${l.label} ›`));
    await va.getByTestId("va-brief-more").click();
    await expect(va.getByTestId("va-brief-point")).toHaveCount(it.points.length);
  });

  test("EA-10 the card's Ask › sends its follow-up question", async ({ page }) => {
    const p = MOCK.tcs;
    const { va, asked } = await open(page, p, { question: "How were TCS results?" });
    await va.getByTestId("va-brief-ask").click();
    await expect.poll(() => asked.length, SLOW).toBe(2);
    expect(asked[1]).toBe(block(p, "events").items[0].ask);
  });

  test("EA-11 on a phone every card, link and table fits: nothing scrolls sideways and links are tappable", async ({ page }) => {
    const p = MOCK.calendar;
    const { va } = await open(page, p, { width: 390 });
    await expect(frame(va, "due").getByTestId("va-ranked")).toHaveAttribute("data-layout", "cards");
    for (const sel of ["va-brief-link", "va-brief-more"]) {
      const box = await va.getByTestId(sel).first().boundingBox();
      expect(box && box.height >= 32).toBe(true);
    }
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
    const cardBox = await va.getByTestId("va-brief").first().boundingBox();
    expect(cardBox && cardBox.width <= 390).toBe(true);
    if (SHOTS) { fs.mkdirSync(SHOTS, { recursive: true }); await va.screenshot({ path: path.join(SHOTS, "calendar-phone.png") }); }
  });

  test("EA-13 a result is rated Below, Meets or Above expectation, and the counts strip says what expectation means", async ({ page }) => {
    const p = MOCK.calendar;
    const { va } = await open(page, p);
    const cards = block(p, "declared").items;
    for (const it of cards) {
      expect(["Above expectation", "Well above expectation", "Meets expectation", "Below expectation", "Well below expectation", "Not rated"]).toContain(it.badge);
      await expect(cardOf(va, it.symbol).getByTestId("va-brief-badge")).toContainText(it.badge);
      if (it.badge === "Not rated") await expect(cardOf(va, it.symbol).getByTestId("va-brief-sub")).toContainText("Not rated:");
    }
    const strip = block(p, "counts").items.find((i: any) => i.label === "Above · meets · below");
    expect(strip.sub).toContain("expectation");
    expect(strip.sub).toContain("not analyst consensus");
    await expect(frame(va, "counts")).toContainText("Above · meets · below");
  });

  test("EA-14 each analysed card shows the five-line AI commentary with its signal, impact and confidence", async ({ page }) => {
    const p = MOCK.calendar;
    const { va } = await open(page, p);
    const withC = block(p, "declared").items.filter((it: any) => it.commentary);
    expect(withC.length).toBeGreaterThan(0);
    for (const it of withC) {
      const box = cardOf(va, it.symbol).getByTestId("va-brief-commentary");
      await expect(box).toHaveAttribute("data-tone", it.commentary.signal.tone);
      const sig = [it.commentary.signal.label, it.commentary.signal.impact ? `${it.commentary.signal.impact} impact` : null,
        it.commentary.signal.confidence != null ? `confidence ${it.commentary.signal.confidence}%` : null].filter(Boolean).join(" · ");
      await expect(box.getByTestId("va-brief-signal")).toHaveText(sig);
      await expect(box.getByTestId("va-brief-line")).toHaveCount(5);
      await expect(box.getByTestId("va-brief-line")).toHaveText(it.commentary.lines.map((l: any) => `${l.label}: ${l.text}`));
      expect(it.commentary.lines.map((l: any) => l.label)).toEqual(["What happened", "Why it matters", "Market impact", "What to watch", "AI take"]);
    }
    // a card with no stored AI read has no commentary and says so
    const none = block(p, "declared").items.find((it: any) => !it.commentary && it.body == null);
    if (none) {
      await expect(cardOf(va, none.symbol).getByTestId("va-brief-commentary")).toHaveCount(0);
      await expect(cardOf(va, none.symbol).getByTestId("va-brief-empty")).toBeVisible();
    }
  });

  test("EA-15 a line the stored read does not support is printed as 'Not stated', and an order win gets the five lines too", async ({ page }) => {
    const p = MOCK.orders;
    const { va } = await open(page, p, { question: "Any order wins this week?" });
    const it = block(p, "events").items.find((x: any) => x.commentary);
    expect(it).toBeTruthy();
    const box = cardOf(va, it.symbol).getByTestId("va-brief-commentary").first();
    await expect(box.getByTestId("va-brief-line")).toHaveCount(5);
    const stated = it.commentary.lines.filter((l: any) => l.text === "Not stated in the stored AI read.");
    expect(stated.length).toBeGreaterThan(0);                                          // the classifier stores no factors or open questions
    for (const l of stated) await expect(box.locator(`[data-label="${l.label}"]`)).toContainText("Not stated in the stored AI read.");
  });

  test("EA-16 the commentary fits a phone: nothing scrolls sideways and the five lines stay in order", async ({ page }) => {
    const p = MOCK.calendar;
    const { va } = await open(page, p, { width: 390 });
    const it = block(p, "declared").items.find((x: any) => x.commentary);
    const box = cardOf(va, it.symbol).getByTestId("va-brief-commentary");
    await expect(box).toBeVisible();
    await expect(box.getByTestId("va-brief-line")).toHaveCount(5);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
  });

  test("EA-12 screenshots at desktop width (only with EV_SHOTS=1)", async ({ page }) => {
    test.skip(!SHOTS, "set EV_SHOTS=1");
    const { va } = await open(page, MOCK.calendar, { width: 1500 });
    fs.mkdirSync(SHOTS as string, { recursive: true });
    await cardOf(va, "RELI").getByTestId("va-brief-more").click();
    await va.screenshot({ path: path.join(SHOTS as string, "calendar-desktop.png") });
  });
});
