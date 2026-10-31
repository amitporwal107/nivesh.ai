/**
 * One-screen Copilot app (/v5/app) — the broker contract chart card.
 *
 * MOCK — not real data: every /api response here is an inline payload in the
 * shape the real route returns (source named beside each), with synthetic
 * values. Expected figures are worked out from the payload, not copied from
 * the screen. Mocked APIs, production build — see pw.copilot-app.config.ts.
 *
 * The card (src/components/chat/BrokerContractChart.tsx) is the answer card of
 * a question asked from a futures or options position. Its widget carries only
 * the reference to the contract; the card reads the candles and the quote
 * itself, from
 *   GET /api/broker/accounts/{account_id}/contract-chart
 * so it is a live read on a fresh answer and on one reloaded from history.
 *
 * Covers: the card on a streamed answer and on a saved one, the header for an
 * option and for a future, every figure and where it says it is from, the
 * worked-out P&L for a long and for a short, the request the card makes, the
 * two views and "Read again", every state the read can end in, read-only,
 * India time in a browser set to another time zone, and a 390px pass.
 */
import { test, expect, type Page, type Route } from "@playwright/test";
import { mockApi, mockSingleRoute } from "../helpers/api-mock";

const APP = "/v5/app";
const CHART_ROUTE = "**/api/broker/accounts/*/contract-chart*";

type Frame = Record<string, unknown>;
const sse = (frames: Frame[]) => frames.map((f) => `data: ${JSON.stringify(f)}\n\n`).join("");
const reply = (route: Route, body: unknown, status = 200) =>
  route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });

async function setup(page: Page) {
  await mockApi(page, "populated");
  await mockSingleRoute(page, "**/api/markets/home", "markets-home.json");
}

// ── fixtures ────────────────────────────────────────────────────────────────

/** `data` of a broker_contract_chart widget (backend/routes/chat.py :: _position_chart_widget). */
interface Ref {
  account_id: string; broker: string; broker_display: string; symbol: string; exchange: string;
  instrument_type: "FUT" | "CE" | "PE"; expiry: string; strike: number | null; quantity: number | null; avg_price: number | null;
}
/** A long put: 550 at an average premium of ₹35.80. */
const OPTION: Ref = { account_id: "ba_fixture00001", broker: "icicidirect", broker_display: "ICICI Direct", symbol: "FIXOPT", exchange: "NFO", instrument_type: "PE", expiry: "2026-10-27", strike: 1760, quantity: 550, avg_price: 35.8 };
/** A short future: 275 sold at an average of ₹1,770.00. */
const FUTURE: Ref = { ...OPTION, symbol: "FIXFUT", instrument_type: "FUT", strike: null, quantity: -275, avg_price: 1770 };

const OPTION_TITLE = "FIXOPT 1,760 put · 27 Oct 2026";
const FUTURE_TITLE = "FIXFUT future · 27 Oct 2026";

const widgetOf = (data: unknown, title: string) => ({
  widget_type: "broker_contract_chart", title, data,
  freshness: { state: "live", last_updated: "2026-10-13T10:08:00+00:00", source: ["ICICI Direct"] },
  agent: { id: "broker", confidence: 100 },
});

interface Bar { time: string; open: number; high: number; low: number; close: number; volume: number | null; open_interest: number | null }

const SESSIONS = ["2026-10-08", "2026-10-09", "2026-10-12", "2026-10-13"];
const two = (n: number) => String(n).padStart(2, "0");
const paise = (n: number) => Math.round(n * 100) / 100;

/**
 * Bars of four whole 09:15–15:30 IST sessions, oldest first, each time with
 * its +05:30 offset as the route sends it. 5-minute: 75 a session, 300 in all,
 * the last one starting 13 Oct 15:25. 30-minute: 13 a session, 52 in all, the
 * last one starting 13 Oct 15:15. Every seventh bar has no trades (volume 0).
 */
function bars(stepMin: 5 | 30, base: number): Bar[] {
  const out: Bar[] = [];
  let prev = base;
  let i = 0;
  for (const day of SESSIONS) {
    for (let m = 9 * 60 + 15; m < 15 * 60 + 30; m += stepMin) {
      const close = paise(base * (1 + 0.06 * Math.sin(i / 9)));
      out.push({
        time: `${day}T${two(Math.floor(m / 60))}:${two(m % 60)}:00+05:30`,
        open: prev, high: paise(Math.max(prev, close) * 1.004), low: paise(Math.min(prev, close) * 0.996), close,
        volume: i % 7 === 0 ? 0 : 1200 + (i % 11) * 150,
        open_interest: 109450 + i * 25,
      });
      prev = close;
      i += 1;
    }
  }
  return out;
}

/** The latest quote of the put: last traded ₹21.80 at 15:28:34 IST on 13 Oct. */
const OPTION_QUOTE = { last_price: 21.8, last_traded_at: "2026-10-13T15:28:34+05:30", open: 34.1, high: 34.1, low: 19.1, previous_close: 22.05, change_pct: -1.13, spot_price: 1801.0, volume: 123456 };
const FUTURE_QUOTE = { last_price: 1765, last_traded_at: "2026-10-13T15:29:10+05:30", open: 1772, high: 1781.5, low: 1760.2, previous_close: 1774, change_pct: -0.51, spot_price: 1762.4, volume: 98000 };

/** 200 body of the chart route (backend/routes/broker_connect.py :: get_contract_chart). Read at 10:08 UTC = 3:38 pm IST. */
function chartBody(ref: Ref, interval: string, over: Record<string, unknown> = {}) {
  return {
    account_id: ref.account_id, broker: ref.broker, broker_display: ref.broker_display,
    contract: { symbol: ref.symbol, exchange: ref.exchange, instrument_type: ref.instrument_type, expiry: ref.expiry, strike: ref.strike },
    interval, as_of: "2026-10-13T10:08:00+00:00",
    candles: bars(interval === "30m" ? 30 : 5, ref.instrument_type === "FUT" ? 1768 : 24),
    quote: ref.instrument_type === "FUT" ? FUTURE_QUOTE : OPTION_QUOTE,
    ...over,
  };
}

/** The app's error envelope (backend/core/error_handlers.py), as the broker routes fill it. */
const envelope = (status: number, code: string, message: string) => ({ status, error: "ERROR", code, message, details: [{ broker: "icicidirect", account_id: "ba_fixture00001" }] });

// ── route mocks ─────────────────────────────────────────────────────────────

interface ChartMock { calls: URL[] }

/** Answers the chart route. `answer` gets the request URL and its number (1 = first); it may be async to hold a read open. */
async function mockChart(page: Page, answer: (url: URL, n: number) => { status?: number; body: unknown } | Promise<{ status?: number; body: unknown }>): Promise<ChartMock> {
  const state: ChartMock = { calls: [] };
  await page.route(CHART_ROUTE, async (route) => {
    const url = new URL(route.request().url());
    state.calls.push(url);
    const a = await answer(url, state.calls.length);
    return reply(route, a.body, a.status ?? 200);
  });
  return state;
}

/** The chart route answering each view of `ref` with its full body. */
const chartFor = (page: Page, ref: Ref) => mockChart(page, (url) => ({ body: chartBody(ref, url.searchParams.get("interval") ?? "") }));

/**
 * A saved thread ("hist1") whose one answer carries the card, as
 * GET /api/chat/messages?session_id= returns it (backend/routes/chat.py saves
 * the widget with the answer).
 */
async function savedThread(page: Page, data: unknown, title: string) {
  await page.route("**/api/chat/sessions", (route) => reply(route, [{ session_id: "hist1", title: "Contract chart", updated_at: "2026-10-13T10:08:00+00:00" }]));
  await page.route("**/api/chat/messages*", (route) => reply(route, [
    { message_id: "u1", session_id: "hist1", role: "user", content: "Show the chart of this position.", created_at: "2026-10-13T10:07:50+00:00" },
    { message_id: "a1", session_id: "hist1", role: "assistant", content: "This is the contract’s own price, read from your broker.", created_at: "2026-10-13T10:08:00+00:00", widget: widgetOf(data, title) },
  ]));
}

/** Opens the saved thread and returns the card. */
async function openSaved(page: Page, data: unknown, title: string) {
  await savedThread(page, data, title);
  await page.goto(`${APP}/t/hist1`);
  return page.getByTestId("contract-chart-card");
}

/**
 * Chat endpoints for a question asked in the app: the stream answers with the
 * card's widget frame, and — as the real backend does — the answer is saved
 * with it, so the refetch after the stream returns the saved copy.
 */
async function streamedThread(page: Page, data: unknown, title: string) {
  const saved: unknown[] = [];
  await page.route("**/api/chat/sessions", (route) =>
    route.request().method() === "POST" ? reply(route, { session_id: "new1", id: "new1" }) : reply(route, []));
  await page.route("**/api/chat/messages*", (route) => reply(route, saved));
  await page.route("**/api/chat/stream", (route) => {
    const body = route.request().postDataJSON() as { message: string };
    const text = "This is the contract’s own price, read from your broker.";
    saved.push(
      { message_id: "u1", session_id: "new1", role: "user", content: body.message, created_at: "2026-10-13T10:07:50+00:00" },
      { message_id: "ai1", session_id: "new1", role: "assistant", content: text, created_at: "2026-10-13T10:08:00+00:00", widget: widgetOf(data, title) },
    );
    return route.fulfill({ status: 200, contentType: "text/event-stream", body: sse([
      { type: "meta", session_id: "new1", ai_msg_id: "ai1", user_msg_id: "u1" },
      { type: "route", agent: "portfolio_analyst", confidence: 0.9 },
      { type: "widget", ...widgetOf(data, title) },
      { type: "token", content: text },
      { type: "done", content: text, follow_ups: [] },
    ]) });
  });
  await page.route("**/api/chat/suggest-queries*", (route) => reply(route, { suggestions: [] }));
  await page.route("**/api/chat/instrument-search*", (route) => reply(route, { stocks: [], funds: [] }));
}

/** Sideways overflow of the document and of the shell's scroll area, in px. */
async function sidewaysOverflow(page: Page) {
  return page.evaluate(() => {
    const sc = document.querySelector('[data-testid="copilot-scroll"]') as HTMLElement | null;
    return {
      doc: document.documentElement.scrollWidth - document.documentElement.clientWidth,
      scroll: sc ? sc.scrollWidth - sc.clientWidth : 0,
    };
  });
}

/** The colour of one pixel near the top-left of the chart's largest canvas (its plot area). */
async function plotPixel(page: Page): Promise<number[]> {
  return page.getByTestId("contract-chart-canvas").evaluate((host) => {
    const all = Array.from(host.querySelectorAll("canvas"));
    const plot = all.sort((a, b) => b.width * b.height - a.width * a.height)[0];
    const ctx = plot.getContext("2d");
    return ctx ? Array.from(ctx.getImageData(3, 3, 1, 1).data.slice(0, 3)) : [];
  });
}

test.describe("Contract chart card", () => {
  test.beforeEach(async ({ page }) => { await setup(page); });

  test("an answer whose stream carries the card shows the option's own chart, its figures and the worked-out P&L, from one read", async ({ page }) => {
    await streamedThread(page, OPTION, OPTION_TITLE);
    // The read is held open until the answer has been saved, so the loading state and the
    // hand-over from the streaming answer to its saved copy are both seen.
    let release: () => void = () => undefined;
    const held = new Promise<void>((r) => { release = r; });
    const chart = await mockChart(page, async (url) => { await held; return { body: chartBody(OPTION, url.searchParams.get("interval") ?? "") }; });

    await page.goto(APP);
    await page.getByTestId("composer-input").fill("Show the chart of my FIXOPT put");
    await page.getByTestId("composer-input").press("Enter");

    const card = page.getByTestId("contract-chart-card");
    await expect(card).toBeVisible();
    await expect(page.getByTestId("contract-chart-title")).toHaveText(OPTION_TITLE);
    await expect(page.getByTestId("contract-chart-loading")).toContainText("Reading this contract’s price from ICICI Direct");
    // What the position row gave is on the card before the broker has answered.
    await expect(page.getByTestId("contract-chart-average")).toHaveText("₹35.80");
    await expect(page.getByTestId("contract-chart-qty")).toHaveText("550");
    await expect(page.getByTestId("thread-turn")).toHaveAttribute("data-state", "saved");
    release();

    // Header: the contract in words, its company icon, the broker with its icon, and when it was read (10:08 UTC = 3:38 pm IST).
    await expect(card.locator('[data-testid="entity-icon"][data-kind="stock"]')).toHaveAttribute("data-key", "FIXOPT");
    const broker = page.getByTestId("contract-chart-broker");
    await expect(broker).toContainText("ICICI Direct");
    await expect(broker.locator('[data-testid="entity-icon"][data-kind="broker"]')).toHaveCount(1);
    await expect(page.getByTestId("contract-chart-asof")).toHaveText(/^Read 13 Oct, 3:38\s?pm$/i);

    // Last price is the broker's own last traded price, with the time of that trade (15:28:34 IST).
    await expect(page.getByTestId("contract-chart-last")).toHaveText("₹21.80");
    await expect(page.getByTestId("contract-chart-last-note")).toContainText("last traded price");
    await expect(page.getByTestId("contract-chart-last-note")).toContainText(/traded 13 Oct, 3:28\s?pm/i);
    // An option's average is a premium.
    await expect(page.getByTestId("contract-chart-average-label")).toHaveText("Average premium");
    await expect(page.getByTestId("contract-chart-average")).toHaveText("₹35.80");
    await expect(page.getByTestId("contract-chart-qty")).toHaveText("550");
    // (21.80 − 35.80) × 550 = −7,700: a long position that has lost. Worked out on the card, and it says so.
    await expect(page.getByTestId("contract-chart-pnl")).toHaveText("−₹7,700");
    await expect(page.getByTestId("contract-chart-pnl-note")).toContainText("(last price − average) × quantity");
    await expect(page.getByTestId("contract-chart-pnl-note")).toContainText("not the broker’s own P&L figure");
    await expect(page.getByTestId("contract-chart-range")).toHaveText("₹34.10 / ₹19.10");
    await expect(page.getByTestId("contract-chart-prev-close")).toHaveText("₹22.05");
    await expect(page.getByTestId("contract-chart-spot")).toHaveText("₹1,801.00");
    // Open interest is the last bar's own value (109450 + 299 × 25 = 116,925 = 1.17 L), never a sum.
    await expect(page.getByTestId("contract-chart-oi")).toHaveText("1.17 L");
    await expect(page.getByTestId("contract-chart-oi-note")).toContainText(/last candle.*13 Oct, 3:25\s?pm/i);

    // The chart: 300 five-minute candles, a line at the average, volume under it.
    const canvas = page.getByTestId("contract-chart-canvas");
    await expect(canvas).toHaveAttribute("data-bars", "300");
    await expect(canvas).toHaveAttribute("data-interval", "5m");
    await expect(canvas).toHaveAttribute("data-average", "35.8");
    await expect(canvas).toHaveAttribute("data-volume", "1");
    await expect(canvas.locator("canvas").first()).toBeVisible();
    await expect(page.getByTestId("contract-chart-caption")).toContainText(/300 candles · 5 min each · 8 Oct, 9:15\s?am to 13 Oct, 3:25\s?pm/i);
    await expect(page.getByTestId("contract-chart-caption")).toContainText("India time");
    await expect(page.getByTestId("contract-chart-caption")).toContainText("your average premium ₹35.80");
    await expect(page.getByTestId("contract-chart-source")).toContainText("this contract’s own");
    await expect(page.getByTestId("contract-chart-source")).toContainText("read from ICICI Direct");

    // Dark theme: the plot is drawn on the app's dark surface (--surface-1 in index.css, #0A0E1A), as the card is.
    expect(await page.evaluate(() => document.documentElement.getAttribute("data-theme"))).toBe("dark");
    expect(await plotPixel(page)).toEqual([10, 14, 26]);
    expect(await card.evaluate((el) => getComputedStyle(el).backgroundColor)).toBe("rgb(10, 14, 26)");

    // The streaming answer and its saved copy are one read at the broker, not two.
    expect(chart.calls).toHaveLength(1);
  });

  test("a future is named as one; a short is said in words and its P&L has the right sign", async ({ page }) => {
    const chart = await chartFor(page, FUTURE);
    const card = await openSaved(page, FUTURE, FUTURE_TITLE);

    await expect(page.getByTestId("contract-chart-title")).toHaveText(FUTURE_TITLE);
    await expect(card.locator('[data-testid="entity-icon"][data-kind="stock"]')).toHaveAttribute("data-key", "FIXFUT");
    await expect(page.getByTestId("contract-chart-last")).toHaveText("₹1,765.00");
    // A future's average is a price, not a premium.
    await expect(page.getByTestId("contract-chart-average-label")).toHaveText("Your average");
    await expect(page.getByTestId("contract-chart-average")).toHaveText("₹1,770.00");
    await expect(page.getByTestId("contract-chart-qty")).toHaveText("Short 275");
    // (1,765 − 1,770) × −275 = +1,375: a short gains when the price falls.
    await expect(page.getByTestId("contract-chart-pnl")).toHaveText("+₹1,375");
    await expect(page.getByTestId("contract-chart-range")).toHaveText("₹1,781.50 / ₹1,760.20");
    await expect(page.getByTestId("contract-chart-spot")).toHaveText("₹1,762.40");
    await expect(page.getByTestId("contract-chart-canvas")).toHaveAttribute("data-average", "1770");

    // The request names the future by its row's own values; a future has no strike, so none is sent.
    expect(chart.calls).toHaveLength(1);
    const q = chart.calls[0].searchParams;
    expect(chart.calls[0].pathname).toBe("/api/broker/accounts/ba_fixture00001/contract-chart");
    expect(Object.fromEntries(q)).toEqual({ symbol: "FIXFUT", exchange: "NFO", instrument_type: "FUT", expiry: "2026-10-27", interval: "5m" });
  });

  test("the card on an answer loaded from thread history reads the chart again, asking for that contract", async ({ page }) => {
    const chart = await chartFor(page, OPTION);
    const card = await openSaved(page, OPTION, OPTION_TITLE);

    await expect(card).toBeVisible();
    await expect(page.getByTestId("thread-turn")).toHaveAttribute("data-state", "saved");
    await expect(page.getByTestId("contract-chart-title")).toHaveText(OPTION_TITLE);
    await expect(page.getByTestId("contract-chart-canvas")).toHaveAttribute("data-bars", "300");
    await expect(page.getByTestId("contract-chart-last")).toHaveText("₹21.80");

    expect(chart.calls).toHaveLength(1);
    expect(chart.calls[0].pathname).toBe("/api/broker/accounts/ba_fixture00001/contract-chart");
    expect(Object.fromEntries(chart.calls[0].searchParams)).toEqual({ symbol: "FIXOPT", exchange: "NFO", instrument_type: "PE", expiry: "2026-10-27", strike: "1760", interval: "5m" });
  });

  test("two views, 5 min and 30 min: changing it reads the new one, Read again reads once more, and nothing reads on its own", async ({ page }) => {
    const chart = await chartFor(page, OPTION);
    const card = await openSaved(page, OPTION, OPTION_TITLE);
    const canvas = page.getByTestId("contract-chart-canvas");
    await expect(canvas).toHaveAttribute("data-bars", "300");

    // The endpoint has two views; no daily one is offered.
    const views = card.getByRole("group", { name: "Candle size" }).getByRole("button");
    await expect(views).toHaveText(["5 min", "30 min"]);
    await expect(page.getByTestId("contract-chart-interval-5m")).toHaveAttribute("aria-pressed", "true");
    await expect(page.getByTestId("contract-chart-interval-30m")).toHaveAttribute("aria-pressed", "false");
    await expect(card.getByRole("button", { name: /day|daily/i })).toHaveCount(0);

    await page.getByTestId("contract-chart-interval-30m").click();
    await expect(page.getByTestId("contract-chart-interval-30m")).toHaveAttribute("aria-pressed", "true");
    await expect(canvas).toHaveAttribute("data-interval", "30m");
    await expect(canvas).toHaveAttribute("data-bars", "52");
    await expect(page.getByTestId("contract-chart-caption")).toContainText(/52 candles · 30 min each · 8 Oct, 9:15\s?am to 13 Oct, 3:15\s?pm/i);
    expect(chart.calls.map((u) => u.searchParams.get("interval"))).toEqual(["5m", "30m"]);
    // The contract is the same in every request.
    expect(Object.fromEntries(chart.calls[1].searchParams)).toEqual({ symbol: "FIXOPT", exchange: "NFO", instrument_type: "PE", expiry: "2026-10-27", strike: "1760", interval: "30m" });

    // "Read again" is a new read of the view on screen.
    await page.getByTestId("contract-chart-refresh").click();
    await expect.poll(() => chart.calls.length).toBe(3);
    expect(chart.calls[2].searchParams.get("interval")).toBe("30m");
    await expect(page.getByTestId("contract-chart-refresh")).toHaveText("Read again ›");

    // Nothing polls: with the card left alone, and the window refocused, no further read is made.
    await page.evaluate(() => {
      window.dispatchEvent(new Event("focus"));
      window.dispatchEvent(new Event("visibilitychange"));
      document.dispatchEvent(new Event("visibilitychange"));
    });
    await page.waitForTimeout(1500);
    expect(chart.calls).toHaveLength(3);
  });

  test("candles but no quote: last price is the last candle's close and says so; day high / low, previous close and spot say Not sent", async ({ page }) => {
    // ICICI's quote call often fails while the candles come back: `quote` is then null.
    const candles = bars(5, 24);
    candles[candles.length - 1].close = 30.8;
    await mockChart(page, (url) => ({ body: chartBody(OPTION, url.searchParams.get("interval") ?? "", { candles, quote: null }) }));
    await openSaved(page, OPTION, OPTION_TITLE);

    await expect(page.getByTestId("contract-chart-canvas")).toHaveAttribute("data-bars", "300");
    await expect(page.getByTestId("contract-chart-last")).toHaveText("₹30.80");
    const note = page.getByTestId("contract-chart-last-note");
    await expect(note).toContainText("Close of the last candle");
    await expect(note).toContainText(/13 Oct, 3:25\s?pm/i);
    await expect(note).toContainText("ICICI Direct sent no quote");
    await expect(note).not.toContainText("last traded price");
    // (30.80 − 35.80) × 550 = −2,750, and the card says which price it used.
    await expect(page.getByTestId("contract-chart-pnl")).toHaveText("−₹2,750");
    await expect(page.getByTestId("contract-chart-pnl-note")).toContainText("(last candle’s close − average) × quantity");
    await expect(page.getByTestId("contract-chart-range")).toHaveText("Not sent");
    await expect(page.getByTestId("contract-chart-prev-close")).toHaveText("Not sent");
    await expect(page.getByTestId("contract-chart-spot")).toHaveText("Not sent");
    // What does not come from the quote is unaffected.
    await expect(page.getByTestId("contract-chart-average")).toHaveText("₹35.80");
    await expect(page.getByTestId("contract-chart-qty")).toHaveText("550");
    await expect(page.getByTestId("contract-chart-oi")).toHaveText("1.17 L");
    // No figure is filled in with a zero.
    await expect(page.getByTestId("contract-chart-figures")).not.toContainText("₹0.00");
  });

  test("changing the view keeps the figures that do not come from the quote, while it reads and after it fails", async ({ page }) => {
    let release: () => void = () => undefined;
    const held = new Promise<void>((r) => { release = r; });
    // 5 min answers in full; 30 min is held open, then comes back with candles and no quote.
    await mockChart(page, async (url) => {
      const interval = url.searchParams.get("interval") ?? "";
      if (interval === "30m") { await held; return { body: chartBody(OPTION, interval, { quote: null }) }; }
      return { body: chartBody(OPTION, interval) };
    });
    await openSaved(page, OPTION, OPTION_TITLE);
    await expect(page.getByTestId("contract-chart-last")).toHaveText("₹21.80");

    await page.getByTestId("contract-chart-interval-30m").click();
    // While the 30 min view is being read, the card says so and blanks nothing.
    await expect(page.getByTestId("contract-chart-reading")).toContainText("Reading the 30 min view from ICICI Direct");
    await expect(page.getByTestId("contract-chart-average")).toHaveText("₹35.80");
    await expect(page.getByTestId("contract-chart-qty")).toHaveText("550");
    await expect(page.getByTestId("contract-chart-last")).toHaveText("₹21.80");
    await expect(page.getByTestId("contract-chart-canvas")).toHaveAttribute("data-interval", "5m");
    release();

    // The 30 min read brought no quote: the quote's figures say so, the others stay.
    const last30 = bars(30, 24).at(-1)!.close;
    await expect(page.getByTestId("contract-chart-canvas")).toHaveAttribute("data-interval", "30m");
    await expect(page.getByTestId("contract-chart-reading")).toHaveCount(0);
    await expect(page.getByTestId("contract-chart-last")).toHaveText(`₹${last30.toFixed(2)}`);
    await expect(page.getByTestId("contract-chart-last-note")).toContainText("Close of the last candle");
    await expect(page.getByTestId("contract-chart-prev-close")).toHaveText("Not sent");
    await expect(page.getByTestId("contract-chart-average")).toHaveText("₹35.80");
    await expect(page.getByTestId("contract-chart-qty")).toHaveText("550");

    // A view that cannot be read at all still leaves the position's own figures on the card.
    await page.unroute(CHART_ROUTE);
    await mockChart(page, () => ({ status: 424, body: envelope(424, "BROKER_READ_FAILED", "fixture: the broker did not answer") }));
    await page.getByTestId("contract-chart-refresh").click();
    await expect(page.getByTestId("contract-chart-failed")).toBeVisible();
    await expect(page.getByTestId("contract-chart-average")).toHaveText("₹35.80");
    await expect(page.getByTestId("contract-chart-qty")).toHaveText("550");
    await expect(page.getByTestId("contract-chart-last")).toHaveCount(0);
    await expect(page.getByTestId("contract-chart-canvas")).toHaveCount(0);
  });

  test("a quote with fields missing says Not sent for each, never 0", async ({ page }) => {
    const quote = { ...OPTION_QUOTE, last_traded_at: null, low: null, previous_close: null, spot_price: null };
    // The last bar carries no open interest either.
    const candles = bars(5, 24);
    candles[candles.length - 1].open_interest = null;
    await mockChart(page, (url) => ({ body: chartBody(OPTION, url.searchParams.get("interval") ?? "", { candles, quote }) }));
    await openSaved(page, OPTION, OPTION_TITLE);

    await expect(page.getByTestId("contract-chart-last")).toHaveText("₹21.80");
    await expect(page.getByTestId("contract-chart-last-note")).toContainText("trade time not sent");
    await expect(page.getByTestId("contract-chart-range")).toHaveText("₹34.10 / Not sent");
    await expect(page.getByTestId("contract-chart-prev-close")).toHaveText("Not sent");
    await expect(page.getByTestId("contract-chart-spot")).toHaveText("Not sent");
    await expect(page.getByTestId("contract-chart-oi")).toHaveText("Not sent");
    await expect(page.getByTestId("contract-chart-figures")).not.toContainText("₹0.00");
  });

  test("a position with no average: the average says Not sent, the P&L is not worked out, and no line is drawn for it", async ({ page }) => {
    await chartFor(page, OPTION);
    await openSaved(page, { ...OPTION, avg_price: null }, OPTION_TITLE);

    await expect(page.getByTestId("contract-chart-last")).toHaveText("₹21.80");
    await expect(page.getByTestId("contract-chart-average")).toHaveText("Not sent");
    await expect(page.getByTestId("contract-chart-pnl")).toHaveText("Not worked out");
    await expect(page.getByTestId("contract-chart-pnl-note")).toContainText("your average");
    await expect(page.getByTestId("contract-chart-canvas")).toHaveAttribute("data-bars", "300");
    await expect(page.getByTestId("contract-chart-canvas")).toHaveAttribute("data-average", "");
  });

  test("no candles for the view: says so, draws nothing, and still shows what the quote gave", async ({ page }) => {
    await mockChart(page, (url) => ({ body: chartBody(OPTION, url.searchParams.get("interval") ?? "", { candles: [] }) }));
    await openSaved(page, OPTION, OPTION_TITLE);

    await expect(page.getByTestId("contract-chart-empty")).toContainText("ICICI Direct returned no candles for the 5 min view");
    await expect(page.getByTestId("contract-chart-canvas")).toHaveCount(0);
    await expect(page.getByTestId("contract-chart-last")).toHaveText("₹21.80");
    await expect(page.getByTestId("contract-chart-pnl")).toHaveText("−₹7,700");
    await expect(page.getByTestId("contract-chart-oi")).toHaveText("Not sent");
    await expect(page.getByTestId("contract-chart-asof")).toHaveText(/^Read 13 Oct, 3:38\s?pm$/i);

    // Neither candles nor a quote: there is no last price to show, and none is made up.
    await page.unroute(CHART_ROUTE);
    await mockChart(page, (url) => ({ body: chartBody(OPTION, url.searchParams.get("interval") ?? "", { candles: [], quote: null }) }));
    await page.getByTestId("contract-chart-refresh").click();
    await expect(page.getByTestId("contract-chart-last")).toHaveText("Not sent");
    await expect(page.getByTestId("contract-chart-pnl")).toHaveText("Not worked out");
    await expect(page.getByTestId("contract-chart-empty")).toBeVisible();
  });

  test("the broker session has ended: says to sign in again and links to Broker connections", async ({ page }) => {
    const chart = await mockChart(page, () => ({ status: 409, body: envelope(409, "BROKER_SESSION_EXPIRED", "fixture: the broker rejected the stored session") }));
    await openSaved(page, OPTION, OPTION_TITLE);

    const state = page.getByTestId("contract-chart-session-ended");
    await expect(state).toContainText("Your ICICI Direct session has ended. Sign in again from Broker connections");
    // The server's own sentence is not shown.
    await expect(page.getByTestId("contract-chart-card")).not.toContainText("fixture:");
    await expect(page.getByTestId("contract-chart-asof")).toHaveText("Not read");
    await expect(page.getByTestId("contract-chart-canvas")).toHaveCount(0);
    await expect(page.getByTestId("contract-chart-retry")).toHaveCount(0);
    // A refused read is not repeated on its own.
    await page.waitForTimeout(1200);
    expect(chart.calls).toHaveLength(1);

    await state.getByRole("link", { name: /Broker connections/ }).click();
    await expect(page).toHaveURL(/\/v5\/app\/page\/brokers$/);
  });

  test("not supported, not switched on, and an account that is not the caller's each say so", async ({ page }) => {
    // 400: this broker (or this kind of account) cannot serve a contract chart.
    await mockChart(page, () => ({ status: 400, body: envelope(400, "BROKER_READ_NOT_SUPPORTED", "fixture: no chart reader") }));
    await openSaved(page, OPTION, OPTION_TITLE);
    await expect(page.getByTestId("contract-chart-not-supported")).toContainText("cannot be read from this kind of ICICI Direct account");
    await expect(page.getByTestId("contract-chart-retry")).toHaveCount(0);
    await expect(page.getByTestId("contract-chart-canvas")).toHaveCount(0);

    // 403: reading from a broker is switched off for the user.
    await page.unroute(CHART_ROUTE);
    await mockChart(page, () => ({ status: 403, body: { status: 403, error: "FORBIDDEN", code: "AUTH-003", message: "feature_not_enabled", details: [] } }));
    await page.reload();
    await expect(page.getByTestId("contract-chart-not-enabled")).toContainText("not switched on for this account");

    // 404: the account is not one of the caller's.
    await page.unroute(CHART_ROUTE);
    await mockChart(page, () => ({ status: 404, body: envelope(404, "NOT_FOUND", "fixture: account not found") }));
    await page.reload();
    await expect(page.getByTestId("contract-chart-no-account")).toContainText("not among your connected broker accounts");
    await expect(page.getByTestId("contract-chart-canvas")).toHaveCount(0);
  });

  test("a failed read reports it once; Try again reads once more and draws the chart", async ({ page }) => {
    const chart = await mockChart(page, (url, n) => (n === 1
      ? { status: 424, body: envelope(424, "BROKER_READ_FAILED", "fixture: the broker did not answer") }
      : { body: chartBody(OPTION, url.searchParams.get("interval") ?? "") }));
    await openSaved(page, OPTION, OPTION_TITLE);

    const failed = page.getByTestId("contract-chart-failed");
    await expect(failed).toContainText("ICICI Direct did not return this contract’s chart");
    await expect(failed).toHaveAttribute("role", "alert");
    await expect(page.getByTestId("contract-chart-empty")).toHaveCount(0);
    // A read at the broker is not repeated behind the user's back.
    await page.waitForTimeout(1200);
    expect(chart.calls).toHaveLength(1);

    await page.getByTestId("contract-chart-retry").click();
    await expect(page.getByTestId("contract-chart-canvas")).toHaveAttribute("data-bars", "300");
    await expect(failed).toHaveCount(0);
    expect(chart.calls).toHaveLength(2);
  });

  test("a body in the wrong shape is an error, never an empty chart", async ({ page }) => {
    // A 200 that is not the documented body.
    await mockChart(page, () => ({ body: {} }));
    await openSaved(page, OPTION, OPTION_TITLE);
    const wrong = page.getByTestId("contract-chart-wrong-shape");
    await expect(wrong).toContainText("in a form this card cannot read");
    await expect(page.getByTestId("contract-chart-empty")).toHaveCount(0);
    await expect(page.getByTestId("contract-chart-canvas")).toHaveCount(0);
    await expect(page.getByTestId("contract-chart-last")).toHaveCount(0);
    await expect(page.getByTestId("contract-chart-retry")).toBeVisible();

    // A candle time with no UTC offset cannot be placed in India time, so it is not guessed at.
    await page.unroute(CHART_ROUTE);
    const candles = bars(5, 24);
    candles[10].time = "2026-10-08 10:05:00";
    await mockChart(page, (url) => ({ body: chartBody(OPTION, url.searchParams.get("interval") ?? "", { candles }) }));
    await page.reload();
    await expect(wrong).toBeVisible();
    await expect(page.getByTestId("contract-chart-canvas")).toHaveCount(0);

    // A view the card does not have: daily rows are not candles, and are not drawn as if they were.
    await page.unroute(CHART_ROUTE);
    await mockChart(page, () => ({ body: chartBody(OPTION, "1d") }));
    await page.reload();
    await expect(wrong).toBeVisible();
    await expect(page.getByTestId("contract-chart-canvas")).toHaveCount(0);
  });

  test("a candle that is not later than the one before it is left out, and the card says so", async ({ page }) => {
    // The same bar sent twice, and one bar sent before its turn.
    const candles = bars(5, 24);
    candles.splice(20, 0, { ...candles[19] });
    candles.splice(40, 0, { ...candles[30] });
    await mockChart(page, (url) => ({ body: chartBody(OPTION, url.searchParams.get("interval") ?? "", { candles }) }));
    await openSaved(page, OPTION, OPTION_TITLE);

    // 302 sent, 300 drawn in time order; nothing is moved to where it might fit.
    await expect(page.getByTestId("contract-chart-canvas")).toHaveAttribute("data-bars", "300");
    await expect(page.getByTestId("contract-chart-caption")).toContainText("2 candles were out of time order and are not drawn");
    await expect(page.getByTestId("contract-chart-wrong-shape")).toHaveCount(0);
  });

  test("a card that does not name one contract says so and reads nothing", async ({ page }) => {
    const chart = await chartFor(page, OPTION);
    // An option with no strike is not one contract.
    await savedThread(page, { ...OPTION, strike: null }, "FIXOPT put · 27 Oct 2026");
    await page.goto(`${APP}/t/hist1`);
    await expect(page.getByTestId("contract-chart-bad-reference")).toContainText("does not say which futures or options contract");
    await expect(page.getByTestId("contract-chart-card")).toHaveCount(0);
    await page.waitForLoadState("networkidle");
    expect(chart.calls).toHaveLength(0);
  });

  test("nothing on the card places, changes or closes a position", async ({ page }) => {
    await chartFor(page, FUTURE);
    const card = await openSaved(page, FUTURE, FUTURE_TITLE);
    await expect(page.getByTestId("contract-chart-canvas")).toHaveAttribute("data-bars", "300");

    const order = /place|order|square off|exit|buy|sell|close position|modify|cancel/i;
    await expect(card.getByRole("button", { name: order })).toHaveCount(0);
    await expect(card.getByRole("link", { name: order })).toHaveCount(0);
    // Its only controls are the two views and the re-read.
    await expect(card.getByRole("button")).toHaveText(["5 min", "30 min", "Read again ›"]);
    await expect(card.locator("input, select, textarea")).toHaveCount(0);
    await expect(page.getByTestId("contract-chart-source")).toContainText("Nivesh only reads");
  });
});

test.describe("Contract chart card — browser in another time zone", () => {
  test.use({ timezoneId: "America/New_York" });

  test("times are India time on the card and on the chart's axis", async ({ page }) => {
    await setup(page);
    await chartFor(page, OPTION);
    await openSaved(page, OPTION, OPTION_TITLE);

    // 10:08 UTC is 6:08 am in New York and 3:38 pm in India.
    await expect(page.getByTestId("contract-chart-asof")).toHaveText(/^Read 13 Oct, 3:38\s?pm$/i);
    await expect(page.getByTestId("contract-chart-last-note")).toContainText(/traded 13 Oct, 3:28\s?pm/i);
    await expect(page.getByTestId("contract-chart-caption")).toContainText(/8 Oct, 9:15\s?am to 13 Oct, 3:25\s?pm/i);
    // The wall-clock time handed to the chart's axis for the first and the last bar: 09:15 and 15:25 IST.
    const canvas = page.getByTestId("contract-chart-canvas");
    await expect(canvas).toHaveAttribute("data-first-bar", "2026-10-08T09:15");
    await expect(canvas).toHaveAttribute("data-last-bar", "2026-10-13T15:25");
    // The expiry is a calendar day and stays 27 Oct.
    await expect(page.getByTestId("contract-chart-title")).toHaveText(OPTION_TITLE);
  });
});

test.describe("Contract chart card — phone (390×844)", () => {
  test.use({ viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true });

  test("the card and its chart fit the screen without sideways scroll, in every view and state", async ({ page }) => {
    await setup(page);
    await chartFor(page, FUTURE);
    const card = await openSaved(page, FUTURE, FUTURE_TITLE);
    const canvas = page.getByTestId("contract-chart-canvas");
    await expect(canvas).toHaveAttribute("data-bars", "300");
    await page.waitForLoadState("networkidle");

    let over = await sidewaysOverflow(page);
    expect(over.doc, "page scrolls sideways").toBeLessThanOrEqual(1);
    expect(over.scroll, "content area scrolls sideways").toBeLessThanOrEqual(1);
    const box = await card.boundingBox();
    expect(box!.x).toBeGreaterThanOrEqual(0);
    expect(box!.x + box!.width).toBeLessThanOrEqual(390);
    // The chart is as wide as the card allows and no wider.
    const inner = await canvas.evaluate((el) => ({ scroll: el.scrollWidth, client: el.clientWidth }));
    expect(inner.scroll).toBeLessThanOrEqual(inner.client + 1);
    expect(inner.client).toBeGreaterThan(200);
    await expect(page.getByTestId("contract-chart-qty")).toHaveText("Short 275");

    await page.getByTestId("contract-chart-interval-30m").click();
    await expect(canvas).toHaveAttribute("data-bars", "52");
    over = await sidewaysOverflow(page);
    expect(over.doc, "30 min: page scrolls sideways").toBeLessThanOrEqual(1);
    expect(over.scroll, "30 min: content area scrolls sideways").toBeLessThanOrEqual(1);

    await page.unroute(CHART_ROUTE);
    await mockChart(page, () => ({ status: 409, body: envelope(409, "BROKER_SESSION_EXPIRED", "fixture: the broker rejected the stored session") }));
    await page.getByTestId("contract-chart-refresh").click();
    await expect(page.getByTestId("contract-chart-session-ended")).toBeVisible();
    over = await sidewaysOverflow(page);
    expect(over.doc, "session ended: page scrolls sideways").toBeLessThanOrEqual(1);
    expect(over.scroll, "session ended: content area scrolls sideways").toBeLessThanOrEqual(1);
  });
});

// ─────────────────────────────────────────────────────────────────────────
// Screenshots for a by-eye check, as copilot-app-shots.spec.ts does: skipped
// unless SHOT_DIR is set. All data on them is the fixtures above (test data).
//
//   SHOT_DIR=/out npx playwright test --config pw.copilot-app.config.ts copilot-app-contract-chart
// ─────────────────────────────────────────────────────────────────────────
const SHOT_DIR = process.env.SHOT_DIR;

test.describe("Contract chart card — screenshots", () => {
  test.skip(!SHOT_DIR, "set SHOT_DIR to capture screenshots");

  for (const size of [{ name: "desktop", width: 1280, height: 1500 }, { name: "phone", width: 390, height: 1700 }]) {
    test(`${size.name}: the card loaded, with no quote, and with the session ended`, async ({ page }) => {
      await page.setViewportSize({ width: size.width, height: size.height });
      await setup(page);
      const shot = (name: string) => page.screenshot({ path: `${SHOT_DIR}/contract-chart-${size.name}-${name}.png` });

      await chartFor(page, OPTION);
      await openSaved(page, OPTION, OPTION_TITLE);
      await expect(page.getByTestId("contract-chart-canvas")).toHaveAttribute("data-bars", "300");
      await page.waitForLoadState("networkidle");
      await shot("option-5min");
      await page.getByTestId("contract-chart-interval-30m").click();
      await expect(page.getByTestId("contract-chart-canvas")).toHaveAttribute("data-bars", "52");
      await shot("option-30min");

      await page.unroute(CHART_ROUTE);
      await mockChart(page, (url) => ({ body: chartBody(OPTION, url.searchParams.get("interval") ?? "", { quote: null }) }));
      await page.getByTestId("contract-chart-refresh").click();
      await expect(page.getByTestId("contract-chart-prev-close")).toHaveText("Not sent");
      await shot("option-no-quote");

      await page.unroute(CHART_ROUTE);
      await mockChart(page, () => ({ status: 409, body: envelope(409, "BROKER_SESSION_EXPIRED", "fixture: the broker rejected the stored session") }));
      await page.getByTestId("contract-chart-refresh").click();
      await expect(page.getByTestId("contract-chart-session-ended")).toBeVisible();
      await shot("session-ended");
    });
  }
});
