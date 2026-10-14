/**
 * One-screen Copilot app (/v5/app) — Trader desk and Paper trades.
 *
 * MOCK — not real data: every /api response here is a fixture or an inline
 * payload in the shape the real route returns (source named beside each), with
 * synthetic values. Expected figures are worked out from the payload, not
 * copied from the screen. Mocked APIs, production build — see
 * pw.copilot-app.config.ts.
 *
 * Covers the blocks wired in screens/Trader.tsx, screens/Paper.tsx and
 * screens/desk/*: the broker block (holdings a broker read stored, its empty
 * and error states, open positions read live per account, the funds gap), the company icon on every row that
 * names a stock, the paper-trade summary and its "Full record" view, and a
 * 390px pass with no sideways page scroll.
 */
import { test, expect, type Page } from "@playwright/test";
import fs from "fs";
import path from "path";
import { mockApi, mockSingleRoute } from "../helpers/api-mock";

const APP = "/v5/app";
const FX = path.join(process.cwd(), "e2e", "fixtures");
const load = (name: string) => JSON.parse(fs.readFileSync(path.join(FX, name), "utf-8"));
const has = (name: string) => fs.existsSync(path.join(FX, name));

const json = (page: Page, pattern: string | RegExp, body: unknown, status = 200) =>
  page.route(pattern, (route) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) }));

/** A failed request is retried once by the client and once by the query, so an error block takes a few seconds. */
const SLOW = { timeout: 15_000 };

async function populated(page: Page) {
  await mockApi(page, "populated");
  await mockSingleRoute(page, "**/api/markets/home", "markets-home.json");
  await page.route("**/api/chat/sessions", (route) => route.fulfill({ status: 200, contentType: "application/json", body: "[]" }));
}

/** Captures what a screen hands to the Copilot. Returns the sent messages. */
async function mockAsk(page: Page): Promise<string[]> {
  const sent: string[] = [];
  await page.route("**/api/chat/sessions", (route) =>
    route.request().method() === "POST"
      ? route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ session_id: "asked1" }) })
      : route.fulfill({ status: 200, contentType: "application/json", body: "[]" }));
  await page.route("**/api/chat/messages*", (route) => route.fulfill({ status: 200, contentType: "application/json", body: "[]" }));
  await page.route("**/api/chat/stream", (route) => {
    sent.push((route.request().postDataJSON() as { message: string }).message);
    return route.fulfill({ status: 200, contentType: "text/event-stream", body: `data: ${JSON.stringify({ type: "done", content: "ok" })}\n\n` });
  });
  return sent;
}

/** One POST /api/chat/stream as the app sent it. `position` is present only when the request carried one. */
type AskBody = { message: string; persona?: string; position?: unknown };

/**
 * As `mockAsk`, but keeps each whole request: the question, the persona it was
 * asked in and, for a futures or options row, the reference to its contract.
 * `frame` is the stream's one frame; the default is a finished answer.
 */
async function mockAskBodies(page: Page, frame: Record<string, unknown> = { type: "done", content: "ok" }): Promise<AskBody[]> {
  const bodies: AskBody[] = [];
  await page.route("**/api/chat/sessions", (route) =>
    route.request().method() === "POST"
      ? route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ session_id: "asked1" }) })
      : route.fulfill({ status: 200, contentType: "application/json", body: "[]" }));
  await page.route("**/api/chat/messages*", (route) => route.fulfill({ status: 200, contentType: "application/json", body: "[]" }));
  await page.route("**/api/chat/stream", (route) => {
    const body = route.request().postDataJSON() as AskBody;
    bodies.push({ message: body.message, persona: body.persona, ...("position" in body ? { position: body.position } : {}) });
    return route.fulfill({ status: 200, contentType: "text/event-stream", body: `data: ${JSON.stringify(frame)}\n\n` });
  });
  return bodies;
}

// Shapes: backend/routes/positional_journal.py (list_trades, trade_summary), backend/routes/positional.py (get_watchlist, get_picks).
const JOURNAL_SUMMARY = { open_count: 1, closed_count: 2, gross_long_rs: 10000, invested_rs: 10000, realized_pnl_rs: 600, win_count: 1, loss_count: 1, win_rate_pct: 50.0, needs_hedge: false, suggested_hedge: null };
const JOURNAL = { count: 3, live: true, trades: [
  { nse_symbol: "TESTOPEN", status: "OPEN", plan_source: "MANUAL", stop_loss: 95, target: 120, opened_at: "2026-10-01T04:00:00+00:00", closed_at: null, live_price: 110, pnl: { qty_in: 100, qty_out: 0, held_qty: 100, avg_buy: 100, invested_rs: 10000, realized_pnl_rs: 0, unrealized_pnl_rs: 1000 } },
  { nse_symbol: "TESTWIN", status: "CLOSED", plan_source: "POSITIONAL_PICK", stop_loss: 190, target: 230, opened_at: "2026-09-01T04:00:00+00:00", closed_at: "2026-09-07T04:00:00+00:00", live_price: null, realized_pnl_rs: 1000, realized_pnl_pct: 10, pnl: { qty_in: 50, qty_out: 50, held_qty: 0, avg_buy: 200, invested_rs: 10000, realized_pnl_rs: 1000, unrealized_pnl_rs: 0 } },
  { nse_symbol: "TESTLOSS", status: "STOPPED", plan_source: "MANUAL", stop_loss: 96, target: 0, opened_at: "2026-09-10T04:00:00+00:00", closed_at: "2026-09-12T04:00:00+00:00", live_price: null, realized_pnl_rs: -400, realized_pnl_pct: -4, pnl: { qty_in: 100, qty_out: 100, held_qty: 0, avg_buy: 100, invested_rs: 10000, realized_pnl_rs: -400, unrealized_pnl_rs: 0 } },
] };
const WATCHLIST = { as_of_date: "2026-10-12", buckets: { breakout_confirmed: [{ nse_symbol: "TESTBRK", sector: "Capital Goods", close_price: 510.0, trigger_price: 500.0, stop_price: 477.5, atr_pct: 2.94, why: "Fixture reason" }], pre_breakout: [], true_accumulation: [], trend_continuation: [] } };
const PICKS = { signal_date: "2026-10-12", count: 1, picks: [{ nse_symbol: "TESTPICK", signal_date: "2026-10-12", final_score: 0.812, confidence: "HIGH", stage: "BREAKOUT", timeframe_days_min: 5, timeframe_days_max: 15, entry_price: 505.0, stoploss: 480.0, target_price: 555.0, risk_reward: 2.0, source_scans: ["btst.breakout_confirmation"], reasons: ["Fixture scanner reason"] }] };

/** The desk's own data: a journal, watch levels and scanner picks. The broker routes are set per test. */
async function deskData(page: Page) {
  await json(page, "**/api/positional/journal/summary/portfolio", JOURNAL_SUMMARY);
  await json(page, /\/api\/positional\/journal(\?.*)?$/, JOURNAL);
  await json(page, "**/api/positional/watchlist*", WATCHLIST);
  await json(page, "**/api/positional/picks*", PICKS);
}

/** GET /api/broker/positions with no account signed in on a broker's own page (broker_connect.py :: get_all_positions). */
const NO_LIVE_ACCOUNT = { as_of: "2026-10-12T10:15:00+00:00", kind: "net", segment: "all", accounts: [] };

/**
 * Two accounts read live. Zerodha: a delivery holding, an intraday short the broker sent no price or P&L for,
 * and one option contract. Upstox: its session has ended, so it is reported and the other is still listed.
 */
const POSITIONS = { as_of: "2026-10-12T10:15:00+00:00", kind: "net", segment: "all", accounts: [
  { account_id: "ba_fixture00001", broker: "zerodha", label: "Zerodha", ok: true, error: null, as_of: "2026-10-12T10:15:00+00:00", counts: { total: 3, fno: 1, intraday: 1 }, positions: [
    { symbol: "FIXALPHA", name: "Fixture Alpha Ltd", exchange: "NSE", quantity: 50, avg_price: 200, last_price: 210, pnl: 500, product: "delivery", product_raw: "CNC", segment: "equity", is_intraday: false, instrument_type: null, expiry: null, strike: null, kind: "net" },
    { symbol: "FIXBETA", name: null, exchange: "NSE", quantity: -20, avg_price: 100, last_price: null, pnl: null, product: "intraday", product_raw: "MIS", segment: "equity", is_intraday: true, instrument_type: null, expiry: null, strike: null, kind: "net" },
    { symbol: "FIXIDX26OCT25000CE", name: "Fixture Index", exchange: "NFO", quantity: 65, avg_price: 240.25, last_price: 250.25, pnl: 650, product: "carryforward", product_raw: "NRML", segment: "fno", is_intraday: false, instrument_type: "CE", expiry: "2026-10-27", strike: 25000, kind: "net" },
  ] },
  { account_id: "ba_fixture00002", broker: "upstox", label: "Upstox", ok: false, error: { code: "BROKER_SESSION_EXPIRED", message: "fixture: the broker rejected the stored session" }, as_of: "2026-10-12T10:15:00+00:00", counts: { total: 0, fno: 0, intraday: 0 }, positions: [] },
] };

/** Broker routes: GET /api/broker/accounts (broker_connect.py :: _public_account), GET /api/portfolio/holdings (portfolio.py :: get_holdings) and GET /api/broker/positions. */
async function brokerData(page: Page, opts: { accounts?: unknown; holdings?: unknown; holdingsStatus?: number; positions?: unknown; positionsStatus?: number } = {}) {
  const holdingsCalls: string[] = [];
  await json(page, "**/api/broker/positions*", opts.positions ?? NO_LIVE_ACCOUNT, opts.positionsStatus ?? 200);
  await json(page, "**/api/broker/accounts", opts.accounts ?? load("copilot-trader-broker-accounts.json"));
  await page.route("**/api/portfolio/holdings", (route) => {
    holdingsCalls.push(route.request().url());
    return route.fulfill({ status: opts.holdingsStatus ?? 200, contentType: "application/json", body: JSON.stringify(opts.holdings ?? load("copilot-trader-holdings.json")) });
  });
  return holdingsCalls;
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

// Same routing as research-paper-trades.spec.ts, over the same captured fixtures (e2e/fixtures/paper-*.json).
async function mockPaper(page: Page, over: { portfolio?: { status: number; body: unknown }; evaluation?: { status: number; body: unknown } } = {}) {
  await page.route("**/api/paper-trades/**", (route) => {
    const u = new URL(route.request().url());
    const q = (k: string) => u.searchParams.get(k);
    const reply = (body: unknown, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
    if (u.pathname.endsWith("/portfolio")) {
      if (over.portfolio) return reply(over.portfolio.body, over.portfolio.status);
      const base = `paper-portfolio-${q("sample") ?? "forward"}-${q("portfolio") ?? "P5-NEXT"}`;
      const d = q("prediction_date");
      return reply(load(d && has(`${base}-${d}.json`) ? `${base}-${d}.json` : `${base}.json`));
    }
    if (u.pathname.endsWith("/evaluation")) {
      if (over.evaluation) return reply(over.evaluation.body, over.evaluation.status);
      const f = `paper-evaluation-${q("sample")}-${q("portfolio")}.json`;
      return reply(has(f) ? load(f) : { data: { status: "none", sample: q("sample"), portfolio: q("portfolio") } });
    }
    if (u.pathname.endsWith("/live")) {
      const f = `paper-live-${q("portfolio")}.json`;
      return reply(has(f) ? load(f) : { data: { status: "empty", portfolio: q("portfolio"), positions: [] } });
    }
    const m = u.pathname.match(/\/trades\/(\d+)$/);
    if (m && has(`paper-trade-${m[1]}.json`)) return reply(load(`paper-trade-${m[1]}.json`));
    return reply({ detail: "not_found" }, 404);
  });
}

test.describe("Trader desk — broker block", () => {
  test.beforeEach(async ({ page }) => {
    await populated(page);
    await deskData(page);
  });

  test("holdings a broker read stored are listed with quantity, average, last price, P&L and as-of time", async ({ page }) => {
    const sent = await mockAsk(page);
    await brokerData(page);
    await page.goto(`${APP}/trader`);

    const block = page.getByTestId("trader-broker-positions");
    await expect(page.getByTestId("trader-broker-status")).toHaveText("1 account connected");
    // copilot-trader-broker-accounts.json: active, 3 holdings, last read 2026-10-12T10:12Z = 12 Oct 3:42 pm IST
    const account = page.getByTestId("trader-broker-account");
    await expect(account).toHaveCount(1);
    await expect(account).toContainText("Zerodha");
    await expect(account).toContainText(/Connected · 3 holdings read 12 Oct, 3:42\s?pm/i);
    await expect(account.locator('[data-testid="entity-icon"][data-kind="broker"]')).toHaveCount(1);

    // copilot-trader-holdings.json: three rows carry a broker account, two statement rows do not
    const rows = page.getByTestId("broker-holding-row");
    await expect(rows).toHaveCount(3);
    await expect(rows.nth(0)).toContainText("Fixture Alpha Ltd");
    await expect(rows.nth(0)).toContainText("FIXALPHA");
    await expect(block).not.toContainText("FIXSTATEMENT");
    await expect(block).not.toContainText("Fixture Flexi Cap Fund");
    // every row names a stock, so every row has the company icon
    await expect(block.locator('[data-testid="broker-holding-row"] [data-testid="entity-icon"][data-kind="stock"]')).toHaveCount(3);
    await expect(rows.nth(0).locator('[data-testid="entity-icon"]')).toHaveAttribute("data-key", "FIXALPHA");

    // FIXALPHA: 10 × (120 − 100) = +₹200, +20.0%; price as of the read
    const alpha = block.getByRole("row").filter({ hasText: "FIXALPHA" });
    await expect(alpha).toContainText("₹100.00");
    await expect(alpha).toContainText("₹120.00");
    await expect(alpha.getByTestId("broker-holding-pnl")).toHaveText("+₹200 · +20.0%");
    await expect(alpha.getByTestId("broker-holding-asof")).toHaveText(/^12 Oct, 3:42\s?pm$/i);
    // FIXBRAVO: 5 × (380 − 400) = −₹100, −5.0%; price refreshed 2026-10-13T04:30Z = 13 Oct 10:00 am IST
    const bravo = block.getByRole("row").filter({ hasText: "FIXBRAVO" });
    await expect(bravo.getByTestId("broker-holding-pnl")).toHaveText("−₹100 · −5.0%");
    await expect(bravo.getByTestId("broker-holding-asof")).toHaveText(/^13 Oct, 10:00\s?am$/i);
    // FIXCHARLIE: the import had no average (stored 0), so no average and no P&L are shown
    const charlie = block.getByRole("row").filter({ hasText: "FIXCHARLIE" });
    await expect(charlie).toContainText("₹250.00");
    await expect(charlie.getByTestId("broker-holding-pnl")).toHaveText("—");

    // totals over the two priced rows: 10×120 + 5×380 = ₹3,100; +200 − 100 = +₹100
    await expect(page.getByTestId("broker-holdings-value")).toHaveText("₹3,100");
    await expect(page.getByTestId("broker-holdings-pnl")).toHaveText("+₹100");
    await expect(block).toContainText("2 of 3 priced");
    await expect(page.getByTestId("trader-broker-asof")).toHaveText(/^3 holdings · read 12 Oct, 3:42\s?pm$/i);

    // No account here is signed in on the broker's own page, so there are no live positions to read, and the block says so.
    await expect(page.getByTestId("trader-positions-no-live")).toContainText("None of your connected accounts is");
    // What is still not read from a broker is named.
    await expect(page.getByTestId("trader-positions-not-connected")).toContainText("Broker funds and day P&L are not read yet");
    await expect(page.getByTestId("trader-broker-none")).toHaveCount(0);

    await alpha.click();
    await expect.poll(() => sent).toEqual(["Show the FIXALPHA chart with support and resistance. My broker account holds 10 at an average of ₹100.00."]);
  });

  test("open positions are read live per account: instrument, how it is held, signed quantity and the broker's own P&L", async ({ page }) => {
    let reads = 0;
    await brokerData(page);
    await page.route("**/api/broker/positions*", (route) => {
      reads += 1;
      return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(POSITIONS) });
    });
    await page.goto(`${APP}/trader`);

    const block = page.getByTestId("trader-open-positions");
    // 2026-10-12T10:15Z = 12 Oct 3:45 pm IST
    await expect(page.getByTestId("trader-positions-asof")).toHaveText(/Read 12 Oct, 3:45\s?pm/i);
    const accounts = block.getByTestId("trader-positions-account");
    await expect(accounts).toHaveCount(2);

    const zerodha = accounts.nth(0);
    const rows = zerodha.getByTestId("broker-position-row");
    await expect(rows).toHaveCount(3);
    await expect(rows.nth(0)).toContainText("Fixture Alpha Ltd");
    await expect(zerodha.locator('[data-testid="broker-position-row"] [data-testid="entity-icon"][data-kind="stock"]')).toHaveCount(3);
    // A short is said in words, and a field the broker did not send is not turned into a number.
    await expect(zerodha.getByTestId("broker-position-qty").nth(1)).toHaveText("Short 20");
    await expect(zerodha.getByTestId("broker-position-pnl").nth(1)).toHaveText("Not sent");
    // The option contract is described from its expiry, strike and side.
    await expect(rows.nth(2)).toContainText("27 Oct 2026 · 25,000 call");
    await expect(zerodha.getByTestId("broker-position-qty").nth(2)).toHaveText("65");
    // The broker's own P&L: +500 and +650; the short carries none.
    await expect(zerodha.getByTestId("broker-positions-pnl")).toHaveText("+₹1,150");
    await expect(zerodha).toContainText("2 of 3 positions carry one");

    // The account whose session ended is reported; the other is still listed.
    const upstox = accounts.nth(1);
    await expect(upstox.getByTestId("trader-positions-account-error")).toContainText("Your Upstox session has ended. Sign in again from Broker connections");
    await expect(upstox.getByTestId("broker-position-row")).toHaveCount(0);

    // Filters count and narrow the readable accounts' positions.
    await expect(page.getByTestId("trader-positions-filter-all")).toHaveText("All · 3");
    await expect(page.getByTestId("trader-positions-filter-fno")).toHaveText("F&O · 1");
    await expect(page.getByTestId("trader-positions-filter-intraday")).toHaveText("Intraday · 1");
    await page.getByTestId("trader-positions-filter-fno").click();
    await expect(zerodha.getByTestId("broker-position-row")).toHaveCount(1);
    await expect(zerodha.getByTestId("broker-position-row")).toContainText("Fixture Index");
    await page.getByTestId("trader-positions-filter-intraday").click();
    await expect(zerodha.getByTestId("broker-position-qty")).toHaveText(["Short 20"]);

    // "Read again" is a new read at the broker; nothing polls on its own.
    const before = reads;
    await page.getByTestId("trader-positions-refresh").click();
    await expect.poll(() => reads).toBe(before + 1);
    // Read-only: nothing here offers to place, change or close a position.
    await expect(page.getByTestId("trader-broker-positions").getByRole("button", { name: /place|square off|exit position|buy|sell|close position/i })).toHaveCount(0);
  });

  test("a position row asks for its chart in the trader persona; an option or a future names its contract", async ({ page }) => {
    // The persona the question is asked in travels with it: the server answers an advisor
    // in the trader or investor persona from their own holdings and positions.
    await page.addInitScript(() => localStorage.setItem("nivesh.copilot", JSON.stringify({ state: { mode: "trader", evidenceOpen: null }, version: 0 })));
    const future = { symbol: "FIXGAMMA", name: null, exchange: "NFO", quantity: -275, avg_price: 1770, last_price: 1765, pnl: 1375, product: "carryforward", product_raw: "NRML", segment: "fno", is_intraday: false, instrument_type: "FUT", expiry: "2026-10-27", strike: null, kind: "net" };
    const withFuture = { ...POSITIONS, accounts: [{ ...POSITIONS.accounts[0], counts: { total: 4, fno: 2, intraday: 1 }, positions: [...POSITIONS.accounts[0].positions, future] }] };
    const asked = await mockAskBodies(page);
    await brokerData(page);
    await page.route("**/api/broker/positions*", (route) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(withFuture) }));

    const expected = [
      // A share: quantity and average, as before.
      "Show the FIXALPHA chart with support and resistance. My broker account has an open position of 50 at an average of ₹200.00.",
      "Show the FIXBETA chart with support and resistance. My broker account has a short position of 20 at an average of ₹100.00.",
      // An option: its strike, side and expiry, and the average is called a premium — it is not the share's price.
      "Show the FIXIDX26OCT25000CE chart with support and resistance. My broker account has an open position of 65 in a 25,000 call option expiring 27 Oct 2026, at an average premium of ₹240.25.",
      // A future: named as one, with its expiry.
      "Show the FIXGAMMA chart with support and resistance. My broker account has a short position of 275 in a future expiring 27 Oct 2026, at an average of ₹1,770.00.",
    ];
    for (let i = 0; i < expected.length; i += 1) {
      await page.goto(`${APP}/trader`);
      await page.getByTestId("trader-positions-account").nth(0).getByTestId("broker-position-row").nth(i).click();
      await expect.poll(() => asked.length).toBe(i + 1);
    }
    expect(asked.map((a) => a.message)).toEqual(expected);
    expect(asked.map((a) => a.persona)).toEqual(["trader", "trader", "trader", "trader"]);

    // A share row sends the question alone. An option or a future also sends a reference to
    // its contract — the account, the row's own symbol and exchange, the contract's details,
    // and the signed quantity and average as the broker gave them — so the answer can chart
    // the contract itself (POST /api/chat/stream `position`, backend/routes/chat.py).
    expect(asked[0]).not.toHaveProperty("position");
    expect(asked[1]).not.toHaveProperty("position");
    expect(asked[2].position).toEqual({ account_id: "ba_fixture00001", symbol: "FIXIDX26OCT25000CE", exchange: "NFO", instrument_type: "CE", expiry: "2026-10-27", strike: 25000, quantity: 65, avg_price: 240.25 });
    // A future has no strike, and a short keeps its sign.
    expect(asked[3].position).toEqual({ account_id: "ba_fixture00001", symbol: "FIXGAMMA", exchange: "NFO", instrument_type: "FUT", expiry: "2026-10-27", strike: null, quantity: -275, avg_price: 1770 });
  });

  test("an F&O row the broker did not describe fully asks without a contract reference", async ({ page }) => {
    // Some brokers send no expiry or strike for a derivative (services/brokers/groww.py), and a
    // row can lack its exchange. Such a row cannot name one contract, so it asks as a share row does.
    const base = { name: null, quantity: 10, avg_price: 12, last_price: 13, pnl: 10, product: "carryforward", product_raw: "NRML", segment: "fno", is_intraday: false, kind: "net" };
    const rows = [
      { ...base, symbol: "FIXNOEXP", exchange: "NFO", instrument_type: "CE", expiry: null, strike: null },
      { ...base, symbol: "FIXNOSTRIKE", exchange: "NFO", instrument_type: "PE", expiry: "2026-10-27", strike: null },
      { ...base, symbol: "FIXNOEXCH", exchange: null, instrument_type: "FUT", expiry: "2026-10-27", strike: null },
    ];
    const book = { ...POSITIONS, accounts: [{ ...POSITIONS.accounts[0], counts: { total: 3, fno: 3, intraday: 0 }, positions: rows }] };
    const asked = await mockAskBodies(page);
    await brokerData(page, { positions: book });

    for (let i = 0; i < rows.length; i += 1) {
      await page.goto(`${APP}/trader`);
      await page.getByTestId("trader-positions-account").nth(0).getByTestId("broker-position-row").nth(i).click();
      await expect.poll(() => asked.length).toBe(i + 1);
    }
    expect(asked.map((a) => a.message.split(" chart ")[0])).toEqual(["Show the FIXNOEXP", "Show the FIXNOSTRIKE", "Show the FIXNOEXCH"]);
    for (const a of asked) expect(a).not.toHaveProperty("position");
  });

  test("an answer that failed for a contract row is asked again about the same contract", async ({ page }) => {
    // The stream ends in an error, so the thread offers a retry. The retry is the same
    // question about the same position, and must not fall back to the share.
    const asked = await mockAskBodies(page, { type: "error", content: "fixture: the answer could not be finished" });
    await brokerData(page, { positions: POSITIONS });
    await page.goto(`${APP}/trader`);
    await page.getByTestId("trader-positions-account").nth(0).getByTestId("broker-position-row").nth(2).click();
    await expect.poll(() => asked.length).toBe(1);

    await page.getByTestId("answer-retry").click();
    await expect.poll(() => asked.length).toBe(2);
    const contract = { account_id: "ba_fixture00001", symbol: "FIXIDX26OCT25000CE", exchange: "NFO", instrument_type: "CE", expiry: "2026-10-27", strike: 25000, quantity: 65, avg_price: 240.25 };
    expect(asked[0].position).toEqual(contract);
    expect(asked[1].position).toEqual(contract);
    expect(asked[1].message).toBe(asked[0].message);

    // A different question typed into the same thread afterwards is not about that position.
    await expect(page.getByTestId("answer-retry")).toBeVisible();
    await page.getByTestId("composer-input").fill("What is the lot size?");
    await page.getByTestId("composer-input").press("Enter");
    await expect.poll(() => asked.length).toBe(3);
    expect(asked[2]).not.toHaveProperty("position");
  });

  test("open positions: an account with none, the feature switched off, a failed read and a wrong-shaped answer each say so", async ({ page }) => {
    const empty = { ...POSITIONS, accounts: [{ ...POSITIONS.accounts[0], positions: [], counts: { total: 0, fno: 0, intraday: 0 } }] };
    await brokerData(page, { positions: empty });
    await page.goto(`${APP}/trader`);
    await expect(page.getByTestId("trader-positions-none")).toHaveText("No open positions in this account.");

    // Switched off for the account: 403 from the server.
    await page.unroute("**/api/broker/positions*");
    await json(page, "**/api/broker/positions*", { status: 403, error: "FORBIDDEN", code: "AUTH-003", message: "feature_not_enabled", details: [] }, 403);
    await page.reload();
    await expect(page.getByTestId("trader-positions-off")).toContainText("not switched on for this account");
    await expect(page.getByTestId("broker-position-row")).toHaveCount(0);

    // The read fails: an error with a retry, never an empty book.
    await page.unroute("**/api/broker/positions*");
    await json(page, "**/api/broker/positions*", { detail: "boom" }, 500);
    await page.reload();
    await expect(page.getByTestId("trader-open-positions")).toContainText("Open positions", SLOW);
    await expect(page.getByTestId("trader-open-positions").getByRole("button", { name: /retry|again/i }).first()).toBeVisible(SLOW);
    await expect(page.getByTestId("trader-positions-none")).toHaveCount(0);

    // A 200 that is not the documented shape is an error too.
    await page.unroute("**/api/broker/positions*");
    await json(page, "**/api/broker/positions*", {});
    await page.reload();
    await expect(page.getByTestId("trader-positions-none")).toHaveCount(0);
    await expect(page.getByTestId("trader-positions-no-live")).toHaveCount(0);
    await expect(page.getByTestId("broker-position-row")).toHaveCount(0);
  });

  test("no broker account: says so, links to Broker connections, and does not fetch holdings", async ({ page }) => {
    const holdingsCalls = await brokerData(page, { accounts: { accounts: [] } });
    await page.goto(`${APP}/trader`);
    await expect(page.getByTestId("trader-broker-status")).toHaveText("No broker connected");
    const none = page.getByTestId("trader-broker-none");
    await expect(none).toContainText("No broker account is connected");
    await expect(page.getByTestId("broker-holding-row")).toHaveCount(0);
    await expect(page.getByTestId("trader-positions-not-connected")).toBeVisible();
    await page.waitForLoadState("networkidle");
    expect(holdingsCalls).toEqual([]);
    await none.getByRole("button", { name: "Broker connections" }).click();
    await expect(page).toHaveURL(/\/v5\/app\/page\/brokers$/);
  });

  test("account connected but nothing read yet: empty state names the broker", async ({ page }) => {
    const pending = { accounts: [{ ...load("copilot-trader-broker-accounts.json").accounts[0], status: "pending", last_sync_at: null, last_sync_count: 0 }] };
    // only statement rows come back: nothing from the broker is stored
    const statementOnly = (load("copilot-trader-holdings.json") as Array<{ broker_account_id?: string }>).filter((h) => !h.broker_account_id);
    await brokerData(page, { accounts: pending, holdings: statementOnly });
    await page.goto(`${APP}/trader`);
    await expect(page.getByTestId("trader-broker-account")).toContainText("Sign-in not finished · Nothing read yet");
    await expect(page.getByTestId("trader-broker-holdings-empty")).toContainText("Nothing has been read from Zerodha yet");
    await expect(page.getByTestId("broker-holding-row")).toHaveCount(0);
    await expect(page.getByTestId("trader-positions-not-connected")).toBeVisible();
  });

  test("broker connections fail: the block reports the error", async ({ page }) => {
    await json(page, "**/api/broker/accounts", { detail: "fixture failure" }, 500);
    await page.goto(`${APP}/trader`);
    const block = page.getByTestId("trader-broker-positions");
    await expect(block.getByRole("alert")).toContainText("Broker connections didn’t load", SLOW);
    await expect(page.getByTestId("broker-holding-row")).toHaveCount(0);
    await expect(page.getByTestId("trader-positions-not-connected")).toBeVisible();
  });

  test("holdings fail or come back in the wrong shape: error, never an empty list", async ({ page }) => {
    await brokerData(page, { holdings: { detail: "fixture failure" }, holdingsStatus: 500 });
    await page.goto(`${APP}/trader`);
    const block = page.getByTestId("trader-broker-positions");
    await expect(block.getByRole("alert")).toContainText("Holdings read from your broker didn’t load", SLOW);
    await expect(page.getByTestId("trader-broker-holdings-empty")).toHaveCount(0);

    // a 200 {} is not "no holdings"
    await brokerData(page, { holdings: {} });
    await page.reload();
    await expect(block.getByRole("alert")).toContainText("unexpected response shape", SLOW);
    await expect(page.getByTestId("trader-broker-holdings-empty")).toHaveCount(0);
    await expect(page.getByTestId("broker-holding-row")).toHaveCount(0);
  });

  test("journal, watch-level and scanner rows carry the company icon; risk limits stay declared missing", async ({ page }) => {
    await brokerData(page, { accounts: { accounts: [] } });
    await page.goto(`${APP}/trader`);
    // The marked element is the name alone, so its text is exactly the symbol.
    await expect(page.getByTestId("journal-open-row")).toHaveText(["TESTOPEN"]);
    await expect(page.getByTestId("journal-closed-row")).toHaveText(["TESTLOSS", "TESTWIN"]); // latest close first
    await expect(page.getByTestId("watch-row")).toHaveText(["TESTBRK"]);
    await expect(page.getByTestId("scanner-pick-symbol")).toHaveText(["TESTPICK"]);
    const iconIn = (rowText: string, key: string) =>
      page.getByRole("row").filter({ hasText: rowText }).locator(`[data-testid="entity-icon"][data-kind="stock"][data-key="${key}"]`);
    await expect(iconIn("TESTOPEN", "TESTOPEN")).toHaveCount(1);
    await expect(iconIn("TESTWIN", "TESTWIN")).toHaveCount(1);
    await expect(iconIn("TESTLOSS", "TESTLOSS")).toHaveCount(1);
    await expect(iconIn("TESTBRK", "TESTBRK")).toHaveCount(1);
    await expect(page.getByTestId("scanner-pick").locator('[data-testid="entity-icon"][data-key="TESTPICK"]')).toHaveCount(1);

    const risk = page.getByTestId("trader-risk-rules-not-connected");
    await expect(risk).toContainText("Risk limits are not stored yet");
    await expect(risk.getByTestId("not-connected-needs")).toBeVisible(); // the fixture user is an admin
  });
});

test.describe("Paper trades", () => {
  test.beforeEach(async ({ page }) => { await populated(page); });

  test("summary rows carry the company icon; the full record mounts the engine's own screen", async ({ page }) => {
    await mockPaper(page);
    await page.goto(`${APP}/page/paper`);
    // paper-portfolio-forward-P5-NEXT.json: five positions, none closed
    const rows = page.getByTestId("paper-open-row");
    await expect(rows).toHaveCount(5);
    const symbols = (load("paper-portfolio-forward-P5-NEXT.json").data.positions as Array<{ symbol: string }>).map((p) => p.symbol);
    expect(symbols).toHaveLength(5);
    for (const sym of symbols) {
      await expect(page.getByRole("row").filter({ hasText: sym }).locator(`[data-testid="entity-icon"][data-kind="stock"][data-key="${sym}"]`)).toHaveCount(1);
    }
    await expect(page.getByTestId("paper-view-summary")).toHaveAttribute("aria-pressed", "true");
    await expect(page.getByTestId("paper-engine")).toHaveCount(0);

    // Full record: the original Research → Paper screen, same endpoints
    await page.getByTestId("paper-view-record").click();
    const engine = page.getByTestId("paper-engine");
    await expect(engine.getByTestId("paper-screen")).toBeVisible();
    await expect(engine.getByTestId("pt-disclaimer")).toBeVisible();
    await expect(page.getByTestId("paper-open-row")).toHaveCount(0); // the summary tables are replaced, not stacked
    for (const sym of symbols) await expect(engine.getByTestId(`pt-row-${sym}`)).toBeVisible();
    await engine.getByTestId("pt-view-eval").click();
    await expect(engine.getByTestId("pt-eval-modes")).toBeVisible();
    await expect(engine.getByTestId("pt-eval-bench")).toBeVisible();

    await page.getByTestId("paper-view-summary").click();
    await expect(page.getByTestId("paper-open-row")).toHaveCount(5);
  });

  test("simulation lab view: offered only to accounts with the feature, and mounts the original lab screen", async ({ page }) => {
    await mockPaper(page);
    await page.goto(`${APP}/page/paper`);
    await expect(page.getByTestId("paper-view-record")).toBeVisible();
    await expect(page.getByTestId("paper-view-lab")).toHaveCount(0); // user-profile-onboarded.json has no sim_lab feature

    const me = load("user-profile-onboarded.json");
    await json(page, "**/api/auth/me", { ...me, features: { ...me.features, sim_lab: true } });
    // backend/routes/sim_lab.py refuses an account that is not on the allowlist, whatever the client believes
    await json(page, "**/api/sim-lab/**", { detail: "feature_not_enabled" }, 403);
    await page.reload();
    await page.getByTestId("paper-view-lab").click();
    const lab = page.getByTestId("paper-sim-lab");
    await expect(lab.getByTestId("sim-lab-screen")).toBeVisible();
    await expect(lab.getByTestId("sl-state-no_access")).toBeVisible();
    await expect(page.getByTestId("paper-open-row")).toHaveCount(0); // the summary is replaced, not stacked
  });

  test("nothing recorded yet: empty states, no figures", async ({ page }) => {
    // The bodies staging returns today (status only): portfolio "empty", evaluation "none", live "empty".
    await mockPaper(page, {
      portfolio: { status: 200, body: { data: { status: "empty", sample: "forward", portfolio: "P5-NEXT", dates: [] } } },
      evaluation: { status: 200, body: { data: { status: "none", sample: "forward", portfolio: "P5-NEXT" } } },
    });
    await page.goto(`${APP}/page/paper`);
    const screen = page.getByTestId("screen-page-paper");
    await expect(screen).toContainText("No evaluation yet");
    await expect(screen).toContainText("Nothing recorded yet");
    await expect(page.getByTestId("paper-open-row")).toHaveCount(0);
    await expect(page.getByTestId("paper-net-pnl")).toHaveCount(0);
    await expect(page.getByTestId("paper-disclaimer")).toBeVisible();
  });

  test("the engine is unreachable: both blocks report the error", async ({ page }) => {
    await mockPaper(page, {
      portfolio: { status: 502, body: { detail: "upstream_unavailable" } },
      evaluation: { status: 502, body: { detail: "upstream_unavailable" } },
    });
    await page.goto(`${APP}/page/paper`);
    const screen = page.getByTestId("screen-page-paper");
    await expect(screen.getByRole("alert").filter({ hasText: "The evaluation didn’t load" })).toBeVisible(SLOW);
    await expect(screen.getByRole("alert").filter({ hasText: "The paper portfolio didn’t load" })).toBeVisible(SLOW);
    await expect(page.getByTestId("paper-open-row")).toHaveCount(0);
  });

  test("an account without access sees only that", async ({ page }) => {
    await mockPaper(page, {
      portfolio: { status: 403, body: { detail: "feature_not_enabled" } },
      evaluation: { status: 403, body: { detail: "feature_not_enabled" } },
    });
    await page.goto(`${APP}/page/paper`);
    await expect(page.getByTestId("paper-no-access")).toBeVisible();
    await expect(page.getByTestId("paper-view-record")).toHaveCount(0);
    await expect(page.getByTestId("paper-disclaimer")).toHaveCount(0);
  });
});

test.describe("Trader desk and Paper trades — phone (390×844)", () => {
  test.use({ viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true });

  test.beforeEach(async ({ page }) => { await populated(page); });

  test("the desk with broker holdings does not scroll sideways; the table scrolls inside itself", async ({ page }) => {
    await deskData(page);
    await brokerData(page);
    await page.goto(`${APP}/trader`);
    await expect(page.getByTestId("broker-holding-row")).toHaveCount(3);
    await page.waitForLoadState("networkidle");
    const over = await sidewaysOverflow(page);
    expect(over.doc, "page scrolls sideways").toBeLessThanOrEqual(1);
    expect(over.scroll, "content area scrolls sideways").toBeLessThanOrEqual(1);
    // the holdings table is wider than the phone and scrolls in its own container
    const table = page.getByTestId("trader-broker-positions").getByRole("table");
    const inner = await table.evaluate((el) => ({ scroll: el.scrollWidth, client: el.clientWidth }));
    expect(inner.scroll).toBeGreaterThan(inner.client);
    expect(inner.client).toBeLessThanOrEqual(390);
  });

  test("paper trades, summary and full record, do not scroll sideways", async ({ page }) => {
    await mockPaper(page);
    await page.goto(`${APP}/page/paper`);
    await expect(page.getByTestId("paper-open-row")).toHaveCount(5);
    await page.waitForLoadState("networkidle");
    let over = await sidewaysOverflow(page);
    expect(over.doc, "summary: page scrolls sideways").toBeLessThanOrEqual(1);
    expect(over.scroll, "summary: content area scrolls sideways").toBeLessThanOrEqual(1);

    await page.getByTestId("paper-view-record").click();
    await expect(page.getByTestId("paper-engine").getByTestId("pt-table")).toBeVisible();
    await page.waitForLoadState("networkidle");
    over = await sidewaysOverflow(page);
    expect(over.doc, "full record: page scrolls sideways").toBeLessThanOrEqual(1);
    expect(over.scroll, "full record: content area scrolls sideways").toBeLessThanOrEqual(1);
  });
});

// ─────────────────────────────────────────────────────────────────────────
// Strategy builder — screens/desk/StrategyBuilder.tsx mounts the original v5
// page. It becomes reachable only once "trader/strategy" is in the screen
// registry (screens/index.ts), a file this spec's owner does not edit, so the
// case is skipped until that line exists and runs by itself afterwards.
// ─────────────────────────────────────────────────────────────────────────
const REGISTRY = fs.readFileSync(path.join(process.cwd(), "src", "pages", "CopilotApp", "screens", "index.ts"), "utf-8");
const STRATEGY_REGISTERED = REGISTRY.includes('"trader/strategy"');

test.describe("Strategy builder mounted in the shell", () => {
  test.skip(!STRATEGY_REGISTERED, 'screens/index.ts has no "trader/strategy" entry yet');

  test("the original strategy builder renders inside the shell with its templates and universes", async ({ page }) => {
    await populated(page);
    // Shapes: backend/routes/strategy_builder.py (list_templates, universe-catalog, list universes)
    await mockSingleRoute(page, "**/api/strategy-builder/templates", "copilot-trader-strategy-templates.json");
    await mockSingleRoute(page, "**/api/strategy-builder/universe-catalog", "copilot-trader-strategy-catalog.json");
    await json(page, "**/api/strategy-builder/universes*", { universes: [], count: 0 });
    await page.goto(`${APP}/trader/strategy`);
    const screen = page.getByTestId("screen-trader-strategy");
    await expect(screen.getByTestId("strategy-builder-page")).toBeVisible();
    await expect(screen).toContainText("Fixture Broad 500");
    await expect(page.getByTestId("composer-input")).toBeVisible(); // the shell stays around it
    // The page's own flow: choose a universe, then move on to the Strategy step.
    await screen.locator('[data-testid^="universe-card-"]').first().click();
    await screen.getByRole("button", { name: /Strategy →/ }).click();
    await expect(screen.getByTestId("template-fixture_trend")).toContainText("Fixture trend template");
  });
});
