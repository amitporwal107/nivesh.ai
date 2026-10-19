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

// ── broker routes (MOCK — not real data) ────────────────────────────────
// GET /api/broker/holdings (broker_connect.py :: get_all_holdings, rows from hub_reads._live_rows) and
// GET /api/broker/positions (get_all_positions) list every account of the user, each with ok / error.

/** When every live read below was made: 2026-10-12T10:15Z = 12 Oct 3:45 pm IST. */
const AS_OF = "2026-10-12T10:15:00+00:00";

type Acct = { account_id: string; broker: string; broker_display: string; label: string };
const ZERODHA: Acct = { account_id: "ba_fixture00001", broker: "zerodha", broker_display: "Zerodha", label: "Zerodha" };
const UPSTOX: Acct = { account_id: "ba_fixture00002", broker: "upstox", broker_display: "Upstox", label: "Upstox" };
const ICICI: Acct = { account_id: "ba_fixture00003", broker: "icicidirect", broker_display: "ICICI Direct", label: "ICICI Direct" };

/** A GET /api/broker/accounts row (broker_connect.py :: _public_account) for one of the accounts above, connected on the broker's own page. */
const accountRow = (a: Acct, over: Record<string, unknown> = {}) => ({
  ...load("copilot-trader-broker-accounts.json").accounts[0], ...a, openalgo_hosted: false, api_key_masked: null, native: true, needs_reconnect: false, ...over,
});

const readError = (code: string) => ({ code, message: `fixture: ${code}` });
const UNKNOWN_TOTALS = { invested_rs: null, value_rs: null, pnl_rs: null, pnl_pct: null };
/** An account the live holdings read could not (or, connected through OpenAlgo, cannot) read. */
const holdingsNotRead = (a: Acct, code: string) => ({ ...a, ok: false, error: readError(code), as_of: AS_OF, holdings: [], counts: { total: null }, totals: UNKNOWN_TOTALS });
const positionsNotRead = (a: Acct, code: string) => ({ ...a, ok: false, error: readError(code), as_of: AS_OF, positions: [], counts: { total: 0, fno: 0, intraday: 0 } });

type LiveRow = { symbol: string; invested_rs: number | null; value_rs: number | null; pnl_rs: number | null; [k: string]: unknown };
/** One live holding row, its value, cost and P&L worked out from quantity, average and price as the server does (null when an input is missing). */
function liveRow(symbol: string, name: string | null, quantity: number, avg: number | null, price: number | null, priceSource: "broker" | "masterdata" = "broker"): LiveRow {
  const invested = avg != null ? quantity * avg : null;
  const value = price != null ? quantity * price : null;
  const both = invested != null && value != null && avg != null && price != null;
  return {
    isin: null, symbol, name, exchange: "NSE", asset_type: "equity", sector: null, quantity, avg_price: avg, current_price: price,
    price_source: price != null ? priceSource : null, invested_rs: invested, value_rs: value, pnl_rs: both ? value - invested : null,
    pnl_pct: both ? Math.round(((price - avg) / avg) * 10_000) / 100 : null, source_id: `NSE:${symbol}`,
  };
}
/** The account totals as hub_reads.holdings_totals adds them up: null when any row lacks the figure. */
function totalsOf(rows: LiveRow[]) {
  const sum = (k: "invested_rs" | "value_rs" | "pnl_rs") => (rows.some((r) => r[k] == null) ? null : rows.reduce((s, r) => s + (r[k] as number), 0));
  const invested = sum("invested_rs");
  const pnl = sum("pnl_rs");
  return { invested_rs: invested, value_rs: sum("value_rs"), pnl_rs: pnl, pnl_pct: pnl != null && invested ? Math.round((pnl / invested) * 10_000) / 100 : null };
}
const liveAccount = (a: Acct, rows: LiveRow[]) => ({ ...a, ok: true, error: null, as_of: AS_OF, holdings: rows, counts: { total: rows.length }, totals: totalsOf(rows) });

const ALPHA = liveRow("FIXALPHA", "Fixture Alpha Ltd", 10, 100, 120); //            1,000 → 1,200: +₹200, +20.0%
const DELTA = liveRow("FIXDELTA", null, 4, 250, 225); //                             1,000 → 900: −₹100, −10.0%
const ECHO = liveRow("FIXECHO", "Fixture Echo Ltd", 2.5, 400, 410, "masterdata"); // 1,000 → 1,025: +₹25, +2.5%; the broker sent no price
const FOXTROT = liveRow("FIXFOXTROT", "Fixture Foxtrot Ltd", 100, null, 50); //       no average: value 5,000, no cost, no P&L
const GOLF = liveRow("FIXGOLF", "Fixture Golf Ltd", 10, 20, 30); //                  200 → 300: +₹100, +50.0%

/** Zerodha and ICICI Direct, both read live. */
const TWO_ACCOUNTS = { accounts: [accountRow(ZERODHA), accountRow(ICICI, { created_at: "2026-09-01T05:00:00+00:00" })] };
const TWO_LIVE = { as_of: AS_OF, accounts: [liveAccount(ZERODHA, [ALPHA, DELTA, ECHO]), liveAccount(ICICI, [FOXTROT, GOLF])] };

/** The fixture account (copilot-trader-broker-accounts.json) is connected through OpenAlgo: listed, not read live. */
const OPENALGO_HOLDINGS = { as_of: AS_OF, accounts: [holdingsNotRead(ZERODHA, "BROKER_READ_NOT_SUPPORTED")] };
const OPENALGO_POSITIONS = { as_of: AS_OF, kind: "net", segment: "all", accounts: [positionsNotRead(ZERODHA, "BROKER_READ_NOT_SUPPORTED")] };

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

/** Zerodha (Upstox's session ended): accounts, live holdings and the stored rows, one of them Upstox's from its last sync. */
const ZU_ACCOUNTS = { accounts: [accountRow(ZERODHA), accountRow(UPSTOX, { status: "expired", needs_reconnect: true, session_ended_reason: "broker_rejected", created_at: "2026-09-01T05:00:00+00:00" })] };
const ZU_LIVE = { as_of: AS_OF, accounts: [liveAccount(ZERODHA, [ALPHA]), holdingsNotRead(UPSTOX, "BROKER_SESSION_EXPIRED")] };
/** Upstox's last sync stored one row: 7 × (60 − 50) = +₹70, +20.0%; read 2026-10-11T09:00Z = 11 Oct 2:30 pm IST. */
const UPSTOX_STORED = {
  holding_id: "hold_fixtureupx01", user_id: "user_fixture", portfolio_id: "", name: "Fixture Hotel Ltd", ticker: "FIXHOTEL", asset_type: "equity",
  quantity: 7.0, buy_price: 50.0, current_price: 60.0, sector: "Other", buy_date: null, source: "broker_native", source_id: "NSE:FIXHOTEL",
  broker: "upstox", broker_account_id: "ba_fixture00002", uploaded_at: "2026-10-11T09:00:00+00:00", created_at: "2026-10-11T09:00:00+00:00",
};

type Reply = unknown | ((call: number) => unknown);
const replyOf = (r: Reply, call: number) => (typeof r === "function" ? (r as (n: number) => unknown)(call) : r);

/**
 * Broker routes: GET /api/broker/accounts (broker_connect.py :: _public_account), GET /api/broker/holdings (live),
 * GET /api/broker/positions (live) and GET /api/portfolio/holdings (portfolio.py :: get_holdings — the stored rows).
 * A body may be a function of the call number (0 for the first). Returns the URLs each route was called with.
 */
async function brokerData(page: Page, opts: {
  accounts?: unknown; live?: Reply; liveStatus?: number; positions?: Reply; positionsStatus?: number; holdings?: unknown; holdingsStatus?: number;
} = {}) {
  const calls = { live: [] as string[], positions: [] as string[], stored: [] as string[] };
  await page.route("**/api/broker/positions*", (route) => {
    const body = replyOf(opts.positions ?? OPENALGO_POSITIONS, calls.positions.length);
    calls.positions.push(route.request().url());
    return route.fulfill({ status: opts.positionsStatus ?? 200, contentType: "application/json", body: JSON.stringify(body) });
  });
  await page.route("**/api/broker/holdings*", (route) => {
    const body = replyOf(opts.live ?? OPENALGO_HOLDINGS, calls.live.length);
    calls.live.push(route.request().url());
    return route.fulfill({ status: opts.liveStatus ?? 200, contentType: "application/json", body: JSON.stringify(body) });
  });
  await json(page, "**/api/broker/accounts", opts.accounts ?? load("copilot-trader-broker-accounts.json"));
  await page.route("**/api/portfolio/holdings", (route) => {
    calls.stored.push(route.request().url());
    return route.fulfill({ status: opts.holdingsStatus ?? 200, contentType: "application/json", body: JSON.stringify(opts.holdings ?? load("copilot-trader-holdings.json")) });
  });
  return calls;
}

/** One account's card in the broker block. */
const card = (page: Page, a: Acct) => page.locator(`[data-testid="broker-account-card"][data-account-id="${a.account_id}"]`);

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

  test("an account that is not read live says why; its holdings stored at the last sync are listed as such, never as live", async ({ page }) => {
    const sent = await mockAsk(page);
    const calls = await brokerData(page);
    await page.goto(`${APP}/trader`);

    await expect(page.getByTestId("trader-broker-status")).toHaveText("1 account connected");
    // copilot-trader-broker-accounts.json: one Zerodha account, connected through OpenAlgo, so the live read lists it as not readable
    const zerodha = card(page, ZERODHA);
    await expect(page.getByTestId("broker-account-card")).toHaveCount(1);
    await expect(zerodha.getByTestId("trader-broker-account")).toContainText("Zerodha");
    await expect(zerodha.locator('[data-testid="trader-broker-account"] [data-testid="entity-icon"][data-kind="broker"]')).toHaveCount(1);
    await expect(zerodha.getByTestId("broker-live-status")).toHaveText("Not read live");
    await expect(zerodha.getByTestId("broker-live-holdings-error")).toContainText("Holdings cannot be read live from this Zerodha connection");
    await expect(zerodha.getByTestId("broker-reconnect")).toHaveCount(0);
    await expect(zerodha.getByTestId("broker-live-retry")).toHaveCount(0);
    await expect(zerodha.getByTestId("broker-live-row")).toHaveCount(0);

    // copilot-trader-holdings.json: three rows carry this broker account, two statement rows do not
    const stored = zerodha.getByTestId("broker-stored-holdings");
    await expect(stored).toContainText("Stored at the last sync · not live");
    await expect(zerodha.getByTestId("broker-stored-asof")).toHaveText(/^3 holdings · as of last sync 12 Oct, 3:42\s?pm$/i);
    const rows = zerodha.getByTestId("broker-stored-row");
    await expect(rows).toHaveCount(3);
    await expect(rows.nth(0)).toContainText("Fixture Alpha Ltd");
    await expect(rows.nth(0)).toContainText("FIXALPHA");
    await expect(zerodha).not.toContainText("FIXSTATEMENT");
    await expect(zerodha).not.toContainText("Fixture Flexi Cap Fund");
    // every row names a stock, so every row has the company icon
    await expect(zerodha.locator('[data-testid="broker-stored-row"] [data-testid="entity-icon"][data-kind="stock"]')).toHaveCount(3);
    await expect(rows.nth(0).locator('[data-testid="entity-icon"]')).toHaveAttribute("data-key", "FIXALPHA");

    // FIXALPHA: 10 × (120 − 100) = +₹200, +20.0%; price as of the sync
    const alpha = stored.getByRole("row").filter({ hasText: "FIXALPHA" });
    await expect(alpha).toContainText("₹100.00");
    await expect(alpha).toContainText("₹120.00");
    await expect(alpha.getByTestId("broker-stored-pnl")).toHaveText("+₹200 · +20.0%");
    await expect(alpha.getByTestId("broker-stored-price-asof")).toHaveText(/^12 Oct, 3:42\s?pm$/i);
    // FIXBRAVO: 5 × (380 − 400) = −₹100, −5.0%; price refreshed 2026-10-13T04:30Z = 13 Oct 10:00 am IST
    const bravo = stored.getByRole("row").filter({ hasText: "FIXBRAVO" });
    await expect(bravo.getByTestId("broker-stored-pnl")).toHaveText("−₹100 · −5.0%");
    await expect(bravo.getByTestId("broker-stored-price-asof")).toHaveText(/^13 Oct, 10:00\s?am$/i);
    // FIXCHARLIE: the import had no average (stored 0), so no average and no P&L are shown
    const charlie = stored.getByRole("row").filter({ hasText: "FIXCHARLIE" });
    await expect(charlie).toContainText("₹250.00");
    await expect(charlie.getByTestId("broker-stored-pnl")).toHaveText("—");
    // totals over the two priced rows: 10×120 + 5×380 = ₹3,100; +200 − 100 = +₹100
    await expect(zerodha.getByTestId("broker-stored-value")).toHaveText("₹3,100");
    await expect(zerodha.getByTestId("broker-stored-total-pnl")).toHaveText("+₹100");
    await expect(stored).toContainText("2 of 3 priced");

    // Positions are not read from this connection either, and the block says so.
    await expect(zerodha.getByTestId("trader-positions-account-error")).toContainText("Open positions cannot be read live from this Zerodha connection.");
    await expect(zerodha.getByTestId("broker-position-row")).toHaveCount(0);
    // What is still not read from a broker is named.
    // Cash is now read (GET /api/broker/funds); day P&L and a stop or target per position still are not.
    await expect(page.getByTestId("trader-positions-not-connected")).toContainText("Day P&L and a stop or target per position are not read");
    await expect(page.getByTestId("trader-broker-none")).toHaveCount(0);
    expect(calls.live.length).toBe(1);

    await alpha.click();
    await expect.poll(() => sent).toEqual(["Show the FIXALPHA chart with support and resistance. My broker account holds 10 at an average of ₹100.00."]);
  });

  test("holdings are read live per account: quantity, average, last price, value, P&L and P&L %, with the read time and the account's totals", async ({ page }) => {
    const sent = await mockAsk(page);
    const positions = { as_of: AS_OF, kind: "net", segment: "all", accounts: [POSITIONS.accounts[0], { ...ICICI, ok: true, error: null, as_of: AS_OF, positions: [], counts: { total: 0, fno: 0, intraday: 0 } }] };
    const calls = await brokerData(page, { accounts: TWO_ACCOUNTS, live: TWO_LIVE, positions });
    await page.goto(`${APP}/trader`);

    await expect(page.getByTestId("trader-broker-status")).toHaveText("2 accounts connected");
    await expect(page.getByTestId("broker-account-card")).toHaveCount(2);
    const zerodha = card(page, ZERODHA);
    const icici = card(page, ICICI);
    // the broker's icon and name, and when it was read: 2026-10-12T10:15Z = 12 Oct 3:45 pm IST
    await expect(zerodha.getByTestId("trader-broker-account")).toContainText("Zerodha");
    await expect(icici.getByTestId("trader-broker-account")).toContainText("ICICI Direct");
    await expect(page.locator('[data-testid="trader-broker-account"] [data-testid="entity-icon"][data-kind="broker"]')).toHaveCount(2);
    await expect(zerodha.getByTestId("broker-live-status")).toHaveText(/^Live · read 12 Oct, 3:45\s?pm$/i);
    await expect(icici.getByTestId("broker-live-status")).toHaveText(/^Live · read 12 Oct, 3:45\s?pm$/i);

    // Zerodha: three live rows, each with the company icon
    const rows = zerodha.getByTestId("broker-live-row");
    await expect(rows).toHaveCount(3);
    await expect(zerodha.locator('[data-testid="broker-live-row"] [data-testid="entity-icon"][data-kind="stock"]')).toHaveCount(3);
    await expect(rows.nth(0).locator('[data-testid="entity-icon"]')).toHaveAttribute("data-key", "FIXALPHA");
    await expect(rows.nth(0)).toContainText("Fixture Alpha Ltd");
    await expect(rows.nth(1)).toContainText("FIXDELTA");                    // no company name: the symbol alone
    // FIXALPHA: 10 at 100, last 120 → value 1,200, +₹200, +20.0%
    const alpha = zerodha.getByRole("row").filter({ hasText: "FIXALPHA" });
    await expect(alpha.getByTestId("broker-live-qty")).toHaveText("10");
    await expect(alpha).toContainText("₹100.00");
    await expect(alpha.getByTestId("broker-live-last")).toHaveText("₹120.00");
    await expect(alpha.getByTestId("broker-live-value")).toHaveText("₹1,200");
    await expect(alpha.getByTestId("broker-live-pnl")).toHaveText("+₹200");
    await expect(alpha.getByTestId("broker-live-pnl-pct")).toHaveText("+20.0%");
    // FIXDELTA: 4 at 250, last 225 → −₹100, −10.0%
    const delta = zerodha.getByRole("row").filter({ hasText: "FIXDELTA" });
    await expect(delta.getByTestId("broker-live-pnl")).toHaveText("−₹100");
    await expect(delta.getByTestId("broker-live-pnl-pct")).toHaveText("−10.0%");
    // FIXECHO: a fractional quantity, and a price the broker did not send (the stored close stands in, and says so)
    const echo = zerodha.getByRole("row").filter({ hasText: "FIXECHO" });
    await expect(echo.getByTestId("broker-live-qty")).toHaveText("2.50");
    await expect(echo.getByTestId("broker-live-last")).toHaveText("₹410.00 · not live");
    await expect(echo.getByTestId("broker-live-value")).toHaveText("₹1,025");
    // The account's totals, from the payload: invested 3 × 1,000 = ₹3,000; value 1,200 + 900 + 1,025 = ₹3,125;
    // P&L 200 − 100 + 25 = +₹125, 125 / 3,000 = +4.17% (shown to one place).
    expect(TWO_LIVE.accounts[0].totals).toEqual({ invested_rs: 3000, value_rs: 3125, pnl_rs: 125, pnl_pct: 4.17 });
    await expect(zerodha.getByTestId("broker-live-total-value")).toHaveText("₹3,125");
    await expect(zerodha.getByTestId("broker-live-total-invested")).toHaveText("₹3,000");
    await expect(zerodha.getByTestId("broker-live-total-pnl")).toHaveText("+₹125 · +4.2%");
    await expect(zerodha.getByTestId("broker-live-totals-note")).toHaveCount(0);

    // ICICI Direct: FIXFOXTROT has no average, so its cost and P&L are not known — shown as such, never as zero.
    const foxtrot = icici.getByRole("row").filter({ hasText: "FIXFOXTROT" });
    await expect(foxtrot.getByTestId("broker-live-value")).toHaveText("₹5,000");
    await expect(foxtrot.getByTestId("broker-live-pnl")).toHaveText("—");
    await expect(foxtrot.getByTestId("broker-live-pnl-pct")).toHaveText("—");
    // A total needs every row: value 5,000 + 300 = ₹5,300 is known; cost and P&L are not.
    expect(TWO_LIVE.accounts[1].totals).toEqual({ invested_rs: null, value_rs: 5300, pnl_rs: null, pnl_pct: null });
    await expect(icici.getByTestId("broker-live-total-value")).toHaveText("₹5,300");
    await expect(icici.getByTestId("broker-live-total-invested")).toHaveText("—");
    await expect(icici.getByTestId("broker-live-total-pnl")).toHaveText("—");
    // The one row with both (FIXGOLF: 10 × 30 = 300, +₹100) is summed apart and labelled.
    await expect(icici.getByTestId("broker-live-totals-note")).toHaveText(
      "1 of 2 holdings has no price or no average from ICICI Direct, so the account totals are not added up. The 1 holding with both: value ₹300 · P&L +₹100.");
    await expect(icici.getByTestId("trader-positions-none")).toHaveText("No open positions in this account.");

    // Every account was read live, so nothing stored is fetched or shown.
    await page.waitForLoadState("networkidle");
    expect(calls.stored).toEqual([]);
    await expect(page.getByTestId("broker-stored-holdings")).toHaveCount(0);
    await expect(page.getByTestId("trader-broker-live-asof")).toHaveText(/^Holdings and positions read live 12 Oct, 3:45\s?pm$/i);

    // Read-only: nothing offers to place, change or close anything.
    await expect(page.getByTestId("trader-broker-positions").getByRole("button", { name: /place|square off|exit position|buy|sell|close position|order/i })).toHaveCount(0);

    await alpha.click();
    await expect.poll(() => sent).toEqual(["Show the FIXALPHA chart with support and resistance. My broker account holds 10 at an average of ₹100.00."]);
  });

  test("open positions are read live per account, with an All / F&O switch; F&O rows keep their contract", async ({ page }) => {
    await brokerData(page, { accounts: ZU_ACCOUNTS, live: ZU_LIVE, positions: POSITIONS, holdings: [...load("copilot-trader-holdings.json"), UPSTOX_STORED] });
    await page.goto(`${APP}/trader`);

    const zerodha = card(page, ZERODHA);
    const positions = zerodha.getByTestId("trader-positions-account");
    await expect(positions).toContainText("Open positions · live");
    const rows = positions.getByTestId("broker-position-row");
    await expect(rows).toHaveCount(3);
    await expect(rows.nth(0)).toContainText("Fixture Alpha Ltd");
    await expect(positions.locator('[data-testid="broker-position-row"] [data-testid="entity-icon"][data-kind="stock"]')).toHaveCount(3);
    // A short is said in words, and a field the broker did not send is not turned into a number.
    await expect(positions.getByTestId("broker-position-qty").nth(1)).toHaveText("Short 20");
    await expect(positions.getByTestId("broker-position-pnl").nth(1)).toHaveText("Not sent");
    // The option contract is described from its expiry, strike and side.
    await expect(rows.nth(2)).toContainText("27 Oct 2026 · 25,000 call");
    await expect(positions.getByTestId("broker-position-qty").nth(2)).toHaveText("65");
    // The broker's own P&L: +500 and +650; the short carries none.
    await expect(positions.getByTestId("broker-positions-pnl")).toHaveText("+₹1,150");
    await expect(positions).toContainText("2 of 3 positions carry one");

    // The switch counts the account's positions: 3 in all, 1 F&O, 1 intraday.
    await expect(positions.getByTestId("trader-positions-filter-all")).toHaveText("All · 3");
    await expect(positions.getByTestId("trader-positions-filter-fno")).toHaveText("F&O · 1");
    await expect(positions.getByTestId("trader-positions-filter-intraday")).toHaveText("Intraday · 1");
    await positions.getByTestId("trader-positions-filter-fno").click();
    await expect(positions.getByTestId("trader-positions-filter-fno")).toHaveAttribute("aria-pressed", "true");
    await expect(rows).toHaveCount(1);
    await expect(rows.nth(0)).toContainText("Fixture Index");
    await expect(rows.nth(0)).toContainText("27 Oct 2026 · 25,000 call");
    await positions.getByTestId("trader-positions-filter-intraday").click();
    await expect(positions.getByTestId("broker-position-qty")).toHaveText(["Short 20"]);
    await positions.getByTestId("trader-positions-filter-all").click();
    await expect(rows).toHaveCount(3);

    // The account whose session ended is reported in its own card; the other is still listed.
    const upstox = card(page, UPSTOX);
    await expect(upstox.getByTestId("trader-positions-account-error")).toContainText("Your Upstox session has ended. Sign in again from Broker connections");
    await expect(upstox.getByTestId("broker-position-row")).toHaveCount(0);
  });

  test("an account whose session ended says so, offers Reconnect, and lists its stored rows as of the last sync", async ({ page }) => {
    const calls = await brokerData(page, { accounts: ZU_ACCOUNTS, live: ZU_LIVE, positions: POSITIONS, holdings: [...load("copilot-trader-holdings.json"), UPSTOX_STORED] });
    await page.goto(`${APP}/trader`);

    const upstox = card(page, UPSTOX);
    await expect(upstox.getByTestId("trader-broker-account")).toContainText("Upstox");
    await expect(upstox.getByTestId("broker-live-status")).toHaveText("Session ended · reconnect to read live");
    await expect(upstox.getByTestId("broker-live-holdings-error")).toContainText("Your Upstox session has ended, so this account’s holdings and positions cannot be read live.");
    await expect(upstox.getByTestId("broker-live-row")).toHaveCount(0);
    // Its stored row, labelled with the time of the last sync (2026-10-11T09:00Z = 11 Oct 2:30 pm IST) and as not live.
    await expect(upstox.getByTestId("broker-stored-holdings")).toContainText("Stored at the last sync · not live");
    await expect(upstox.getByTestId("broker-stored-asof")).toHaveText(/^1 holding · as of last sync 11 Oct, 2:30\s?pm$/i);
    await expect(upstox.getByTestId("broker-stored-row")).toHaveCount(1);
    await expect(upstox.getByTestId("broker-stored-row")).toContainText("Fixture Hotel Ltd");
    // 7 × (60 − 50) = +₹70, +20.0%
    await expect(upstox.getByTestId("broker-stored-pnl")).toHaveText("+₹70 · +20.0%");
    expect(calls.stored.length).toBeGreaterThan(0);

    // The account read live shows only its live rows; another account's stored rows are not mixed in.
    const zerodha = card(page, ZERODHA);
    await expect(zerodha.getByTestId("broker-live-status")).toHaveText(/^Live · read 12 Oct, 3:45\s?pm$/i);
    await expect(zerodha.getByTestId("broker-live-row")).toHaveCount(1);
    await expect(zerodha.getByTestId("broker-stored-holdings")).toHaveCount(0);
    await expect(zerodha).not.toContainText("FIXHOTEL");
    await expect(zerodha).not.toContainText("FIXBRAVO");

    await upstox.getByTestId("broker-reconnect").click();
    await expect(page).toHaveURL(/\/v5\/app\/page\/brokers$/);
  });

  test("a failed live read says why with Try again; Refresh reads holdings and positions again, together, and nothing polls", async ({ page }) => {
    const failed = { as_of: AS_OF, accounts: [holdingsNotRead(ZERODHA, "BROKER_READ_FAILED")] };
    const ok = { as_of: AS_OF, accounts: [liveAccount(ZERODHA, [ALPHA])] };
    const positions = { ...POSITIONS, accounts: [POSITIONS.accounts[0]] };
    const calls = await brokerData(page, { accounts: { accounts: [accountRow(ZERODHA)] }, live: (n: number) => (n === 0 ? failed : ok), positions });
    await page.goto(`${APP}/trader`);

    const zerodha = card(page, ZERODHA);
    await expect(zerodha.getByTestId("broker-live-status")).toHaveText("Live read failed");
    await expect(zerodha.getByTestId("broker-live-holdings-error")).toContainText("Zerodha did not return its holdings just now. Try again in a little while.");
    // Until it is read, the rows stored at the last sync are shown, labelled as such.
    await expect(zerodha.getByTestId("broker-stored-asof")).toHaveText(/^3 holdings · as of last sync 12 Oct, 3:42\s?pm$/i);
    await expect(zerodha.getByTestId("broker-live-row")).toHaveCount(0);
    await page.waitForLoadState("networkidle");
    expect([calls.live.length, calls.positions.length]).toEqual([1, 1]);

    // Try again reads the account again: now it answers, and the stored rows give way to the live ones.
    await zerodha.getByTestId("broker-live-retry").click();
    await expect.poll(() => [calls.live.length, calls.positions.length]).toEqual([2, 2]);
    await expect(zerodha.getByTestId("broker-live-row")).toHaveCount(1);
    await expect(zerodha.getByTestId("broker-stored-holdings")).toHaveCount(0);
    await expect(zerodha.getByTestId("broker-live-status")).toHaveText(/^Live · read 12 Oct, 3:45\s?pm$/i);

    // One Refresh reads both routes again.
    await expect(page.getByTestId("trader-broker-refresh")).toHaveText("Refresh");
    await page.getByTestId("trader-broker-refresh").click();
    await expect.poll(() => [calls.live.length, calls.positions.length]).toEqual([3, 3]);
    await expect(page.getByTestId("trader-broker-refresh")).toBeEnabled();

    // Nothing reads on its own: no polling, no re-read on focus.
    await page.waitForTimeout(2_500);
    await page.evaluate(() => window.dispatchEvent(new Event("focus")));
    await page.waitForTimeout(500);
    expect([calls.live.length, calls.positions.length]).toEqual([3, 3]);
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
    await brokerData(page, { accounts: { accounts: [accountRow(ZERODHA)] }, live: { as_of: AS_OF, accounts: [liveAccount(ZERODHA, [ALPHA])] }, positions: empty });
    await page.goto(`${APP}/trader`);
    await expect(page.getByTestId("trader-positions-none")).toHaveText("No open positions in this account.");
    await expect(page.getByTestId("trader-positions-filter-fno")).toHaveText("F&O · 0");

    // Switched off for the account: 403 from the server. The holdings read live are still shown.
    await page.unroute("**/api/broker/positions*");
    await json(page, "**/api/broker/positions*", { status: 403, error: "FORBIDDEN", code: "AUTH-003", message: "feature_not_enabled", details: [] }, 403);
    await page.reload();
    await expect(page.getByTestId("trader-positions-off")).toContainText("not switched on for this account");
    await expect(page.getByTestId("broker-position-row")).toHaveCount(0);
    await expect(page.getByTestId("broker-live-row")).toHaveCount(1);

    // The read fails: an error with a retry, never an empty book.
    await page.unroute("**/api/broker/positions*");
    await json(page, "**/api/broker/positions*", { detail: "boom" }, 500);
    await page.reload();
    const problem = page.getByTestId("trader-positions-problem");
    await expect(problem).toContainText("Open positions didn’t load", SLOW);
    await expect(problem.getByRole("button", { name: /retry|again/i }).first()).toBeVisible(SLOW);
    await expect(page.getByTestId("trader-positions-none")).toHaveCount(0);

    // A 200 that is not the documented shape is an error too.
    await page.unroute("**/api/broker/positions*");
    await json(page, "**/api/broker/positions*", {});
    await page.reload();
    await expect(page.getByTestId("trader-positions-problem")).toContainText("unexpected response shape", SLOW);
    await expect(page.getByTestId("trader-positions-none")).toHaveCount(0);
    await expect(page.getByTestId("broker-position-row")).toHaveCount(0);
  });

  test("live holdings: the feature switched off, a failed read and a wrong-shaped answer each say so, and the stored rows stay labelled", async ({ page }) => {
    await brokerData(page, { live: { status: 403, error: "FORBIDDEN", code: "AUTH-003", message: "feature_not_enabled", details: [] }, liveStatus: 403 });
    await page.goto(`${APP}/trader`);
    const zerodha = card(page, ZERODHA);
    await expect(page.getByTestId("trader-holdings-off")).toContainText("Reading holdings live from a broker is not switched on for this account.");
    // The stored rows are shown, as of the last sync — never as live.
    await expect(zerodha.getByTestId("broker-stored-asof")).toHaveText(/^3 holdings · as of last sync 12 Oct, 3:42\s?pm$/i);
    await expect(zerodha.getByTestId("broker-live-status")).toHaveText("Live read failed");
    await expect(page.getByTestId("broker-live-row")).toHaveCount(0);

    // The read fails: an error with a retry, and still the stored rows.
    await page.unroute("**/api/broker/holdings*");
    await json(page, "**/api/broker/holdings*", { detail: "boom" }, 500);
    await page.reload();
    const problem = page.getByTestId("trader-holdings-problem");
    await expect(problem).toContainText("Live holdings didn’t load", SLOW);
    await expect(problem.getByRole("button", { name: /retry|again/i }).first()).toBeVisible(SLOW);
    await expect(zerodha.getByTestId("broker-stored-row")).toHaveCount(3);

    // A 200 that is not the documented shape is an error too, never "no holdings".
    await page.unroute("**/api/broker/holdings*");
    await json(page, "**/api/broker/holdings*", {});
    await page.reload();
    await expect(page.getByTestId("trader-holdings-problem")).toContainText("unexpected response shape", SLOW);
    await expect(page.getByTestId("broker-live-holdings-empty")).toHaveCount(0);
    await expect(page.getByTestId("broker-live-row")).toHaveCount(0);
  });

  test("no broker account: says so, links to Broker connections, and reads nothing", async ({ page }) => {
    const calls = await brokerData(page, { accounts: { accounts: [] } });
    await page.goto(`${APP}/trader`);
    await expect(page.getByTestId("trader-broker-status")).toHaveText("No broker connected");
    const none = page.getByTestId("trader-broker-none");
    await expect(none).toContainText("No broker account is connected");
    await expect(page.getByTestId("broker-account-card")).toHaveCount(0);
    await expect(page.getByTestId("trader-positions-not-connected")).toBeVisible();
    await page.waitForLoadState("networkidle");
    expect(calls).toEqual({ live: [], positions: [], stored: [] });
    await none.getByRole("button", { name: "Broker connections" }).click();
    await expect(page).toHaveURL(/\/v5\/app\/page\/brokers$/);
  });

  test("an account read live that holds nothing says so; an account not read with nothing stored says so too", async ({ page }) => {
    const accounts = { accounts: [accountRow(ZERODHA), accountRow(UPSTOX, { native: false, openalgo_hosted: true, status: "pending", last_sync_at: null, last_sync_count: 0, created_at: "2026-09-01T05:00:00+00:00" })] };
    const live = { as_of: AS_OF, accounts: [liveAccount(ZERODHA, []), holdingsNotRead(UPSTOX, "BROKER_READ_NOT_SUPPORTED")] };
    const positions = { ...POSITIONS, accounts: [{ ...POSITIONS.accounts[0], positions: [], counts: { total: 0, fno: 0, intraday: 0 } }, positionsNotRead(UPSTOX, "BROKER_READ_NOT_SUPPORTED")] };
    // only statement rows come back: nothing from either broker is stored
    const statementOnly = (load("copilot-trader-holdings.json") as Array<{ broker_account_id?: string }>).filter((h) => !h.broker_account_id);
    await brokerData(page, { accounts, live, positions, holdings: statementOnly });
    await page.goto(`${APP}/trader`);

    const zerodha = card(page, ZERODHA);
    await expect(zerodha.getByTestId("broker-live-holdings-empty")).toHaveText("No holdings at Zerodha.");
    // Read, and nothing held: no totals line made of zeros.
    await expect(zerodha.getByTestId("broker-live-totals")).toHaveCount(0);
    await expect(zerodha.getByTestId("trader-positions-none")).toHaveText("No open positions in this account.");

    const upstox = card(page, UPSTOX);
    await expect(upstox.getByTestId("broker-live-holdings-error")).toContainText("Holdings cannot be read live from this Upstox connection");
    await expect(upstox.getByTestId("broker-stored-none")).toHaveText("No holdings from this account are stored from an earlier sync either.");
    await expect(page.getByTestId("broker-live-row")).toHaveCount(0);
    await expect(page.getByTestId("broker-stored-row")).toHaveCount(0);
    await expect(page.getByTestId("trader-positions-not-connected")).toBeVisible();
  });

  test("broker connections fail: the block reports the error", async ({ page }) => {
    await json(page, "**/api/broker/accounts", { detail: "fixture failure" }, 500);
    await page.goto(`${APP}/trader`);
    const block = page.getByTestId("trader-broker-positions");
    await expect(block.getByRole("alert")).toContainText("Broker connections didn’t load", SLOW);
    await expect(page.getByTestId("broker-account-card")).toHaveCount(0);
    await expect(page.getByTestId("trader-positions-not-connected")).toBeVisible();
  });

  test("stored rows fail or come back in the wrong shape: error, never an empty list", async ({ page }) => {
    await brokerData(page, { holdings: { detail: "fixture failure" }, holdingsStatus: 500 });
    await page.goto(`${APP}/trader`);
    const zerodha = card(page, ZERODHA);
    await expect(zerodha.getByRole("alert").filter({ hasText: "didn’t load" })).toContainText("Holdings stored at the last sync didn’t load", SLOW);
    await expect(zerodha.getByTestId("broker-stored-none")).toHaveCount(0);

    // a 200 {} is not "nothing stored"
    await page.unroute("**/api/portfolio/holdings");
    await json(page, "**/api/portfolio/holdings", {});
    await page.reload();
    await expect(zerodha.getByRole("alert").filter({ hasText: "didn’t load" })).toContainText("unexpected response shape", SLOW);
    await expect(zerodha.getByTestId("broker-stored-none")).toHaveCount(0);
    await expect(zerodha.getByTestId("broker-stored-row")).toHaveCount(0);
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

  test("the desk with live holdings, positions and stored rows does not scroll sideways; each table scrolls inside itself", async ({ page }) => {
    await deskData(page);
    const accounts = { accounts: [...TWO_ACCOUNTS.accounts, accountRow(UPSTOX, { status: "expired", created_at: "2026-08-01T05:00:00+00:00" })] };
    const live = { as_of: AS_OF, accounts: [...TWO_LIVE.accounts, holdingsNotRead(UPSTOX, "BROKER_SESSION_EXPIRED")] };
    const positions = { ...POSITIONS, accounts: [POSITIONS.accounts[0], positionsNotRead(ICICI, "BROKER_READ_FAILED"), POSITIONS.accounts[1]] };
    await brokerData(page, { accounts, live, positions, holdings: [...load("copilot-trader-holdings.json"), UPSTOX_STORED] });
    await page.goto(`${APP}/trader`);
    await expect(page.getByTestId("broker-live-row")).toHaveCount(5);
    await expect(page.getByTestId("broker-position-row")).toHaveCount(3);
    await expect(page.getByTestId("broker-stored-row")).toHaveCount(1);
    await page.waitForLoadState("networkidle");
    const over = await sidewaysOverflow(page);
    expect(over.doc, "page scrolls sideways").toBeLessThanOrEqual(1);
    expect(over.scroll, "content area scrolls sideways").toBeLessThanOrEqual(1);
    // every table (live holdings, positions, stored rows) is wider than the phone and scrolls in its own container
    const tables = page.getByTestId("trader-broker-positions").getByRole("table");
    expect(await tables.count()).toBe(4);
    for (const inner of await tables.evaluateAll((els) => els.map((el) => ({ scroll: el.scrollWidth, client: el.clientWidth })))) {
      expect(inner.scroll).toBeGreaterThan(inner.client);
      expect(inner.client).toBeLessThanOrEqual(390);
    }
    // The Refresh button and the F&O switch stay on screen.
    const refresh = await page.getByTestId("trader-broker-refresh").boundingBox();
    expect((refresh?.x ?? 0) + (refresh?.width ?? 0)).toBeLessThanOrEqual(390);
    const fno = await card(page, ZERODHA).getByTestId("trader-positions-filter-fno").boundingBox();
    expect((fno?.x ?? 0) + (fno?.width ?? 0)).toBeLessThanOrEqual(390);
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
