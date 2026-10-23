/**
 * One-screen Copilot app (/v5/app) — Smart trading desk, tab 06 Options & futures
 * lab (screens/tradingdesk/FnoTab.tsx, fno-parts.tsx, FnoBuildup.tsx, fno-strategy.ts).
 *
 * MOCK — not real data: every /api response here is a fixture or an inline
 * payload in the shape the real route returns (route file named beside each),
 * with synthetic values. Expected figures are worked out from the payload in
 * this file (or the fixture it loads), not copied from the screen. Mocked APIs,
 * production build — see pw.copilot-app.config.ts.
 *
 * Covers design-spec §8 block by block: the header (eyebrow, pills, H1, the
 * spot with the bhavcopy day and India VIX), the underlying row (index chips,
 * ticker box checked against the F&O list, "<SYM> loaded", the Weekly / Monthly
 * expiry switch), the eight stats and the method note, the investor "Read
 * first" row, the four sub-tabs in order, TC-33 OI build-up (quadrant counts "of
 * N stocks", the scatter, the seven-column table, sort, filter, a dot or a row
 * loads the chain), TC-30 the NIFTY & BANKNIFTY cards, TC-31 the option chain
 * (columns, ATM / R / S / MP), TC-32 a stock by ticker, the paper strategies
 * (rules-based cards, only Cash · delivery posts to POST /api/desk/paper-trades,
 * the table for every underlying), the investor wording, and TC-7 at 390px.
 */
import { test, expect, type Page } from "@playwright/test";
import fs from "fs";
import path from "path";
import { mockApi, mockSingleRoute } from "../helpers/api-mock";

const DESK = "/v5/app/trader/desk";
const FX = path.join(process.cwd(), "e2e", "fixtures");
const load = (name: string) => JSON.parse(fs.readFileSync(path.join(FX, name), "utf-8"));

const json = (page: Page, pattern: string | RegExp, body: unknown, status = 200) =>
  page.route(pattern, (route) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) }));

// ── the desk's own reads (header) and the shell ─────────────────────────

// Shapes: backend/routes/positional.py (get_watchlist, get_picks), positional_journal.py (trade_summary).
const WATCHLIST = { as_of_date: "2026-10-12", buckets: { breakout_confirmed: [{ nse_symbol: "TESTBRK", sector: "Capital Goods", close_price: 510.0, trigger_price: 500.0, stop_price: 477.5, atr_pct: 2.94, why: "Fixture reason" }], pre_breakout: [], true_accumulation: [], trend_continuation: [] } };
const PICKS = { signal_date: "2026-10-12", count: 1, picks: [{ nse_symbol: "TESTPICK", signal_date: "2026-10-12", final_score: 0.812, confidence: "HIGH", stage: "BREAKOUT", timeframe_days_min: 5, timeframe_days_max: 15, entry_price: 505.0, stoploss: 480.0, target_price: 555.0, risk_reward: 2.0, source_scans: ["btst.breakout_confirmation"], reasons: ["Fixture scanner reason"] }] };
const JOURNAL_SUMMARY = { open_count: 1, closed_count: 2, gross_long_rs: 10000, invested_rs: 10000, realized_pnl_rs: 600, win_count: 1, loss_count: 1, win_rate_pct: 50.0, needs_hedge: false, suggested_hedge: null };
/** GET /api/broker/positions with no account signed in (broker_connect.py :: get_all_positions). */
const NO_LIVE_ACCOUNT = { as_of: "2026-10-12T10:15:00+00:00", kind: "net", segment: "all", accounts: [] };

async function deskBase(page: Page) {
  await mockApi(page, "populated");
  await mockSingleRoute(page, "**/api/markets/home", "markets-home.json");
  await page.route("**/api/chat/sessions", (route) => route.fulfill({ status: 200, contentType: "application/json", body: "[]" }));
  await json(page, "**/api/positional/watchlist*", WATCHLIST);
  await json(page, "**/api/positional/picks*", PICKS);
  await json(page, "**/api/move-odds/latest*", { detail: "Feature not enabled for this account" }, 403);
  await json(page, "**/api/positional/journal/summary/portfolio", JOURNAL_SUMMARY);
  await json(page, "**/api/broker/positions*", NO_LIVE_ACCOUNT);
  await json(page, "**/api/broker/accounts", load("copilot-trader-broker-accounts.json"));
  await json(page, "**/api/portfolio/holdings", load("copilot-trader-holdings.json"));
  // backend/routes/desk_trading.py: empty books, so the Portfolio tab and the dock stay quiet.
  await page.route("**/api/desk/paper-trades*", (route) => (route.request().method() === "GET"
    ? route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ as_of: "2026-10-13", trades: [], summary: null }) })
    : route.fallback()));
  await json(page, "**/api/desk/alerts*", { as_of: "2026-10-13", alerts: [] });
}

/** Sideways overflow of the page and of the shell's scroller: scrollWidth − innerWidth / clientWidth. */
async function sideways(page: Page) {
  return page.evaluate(() => {
    const sc = document.querySelector('[data-testid="copilot-scroll"]') as HTMLElement | null;
    return {
      doc: document.documentElement.scrollWidth - window.innerWidth,
      scroll: sc ? sc.scrollWidth - sc.clientWidth : 0,
    };
  });
}

// ── F&O payloads ─────────────────────────────────────────────────────────

/** The synthetic NIFTY chains (copilot-app-options.spec.ts): 27 Oct (future), 24 Nov (put-call parity), 30 Mar 2027. */
const NIFTY_CHAINS: Record<string, string> = {
  "2026-10-27": "copilot-options-chain.json",
  "2026-11-24": "copilot-options-chain-parity.json",
  "2027-03-30": "copilot-options-chain-carried.json",
};

const side = (close: number, oi: number, change_in_oi: number, iv: number | null = null) => ({
  close, settle: close, oi, change_in_oi, volume: Math.round(oi / 4), iv, iv_price: iv == null ? null : "settle",
  delta: null, gamma: null, theta: null, vega: null, change: null, change_pct: null, oi_buildup: null,
});

/**
 * BANKNIFTY in the shape of GET /api/fno/{symbol}/chain (backend/routes/fno.py :: chain), 11 strikes, all of the expiry.
 * Spot 52,040 → ATM 52,000. Call OI peaks at 52,500 (9.00 L) = R; put OI peaks at 51,500 (11.00 L) = S.
 * Totals: call 68,50,000, put 54,90,000 → PCR 0.8015 → 0.80.
 * Max pain = the strike K minimising Σ call OI × max(0, K − strike) + Σ put OI × max(0, strike − K):
 *   51,700 → 836.0 Cr, 51,800 → 716.0 Cr, 51,900 → 724.0 Cr → 51,800.
 * ATM straddle 690.20 + 520.20 = 1,210.40 = 2.33% of 52,040. ATM IV (14.10 + 14.40) / 2 = 14.25.
 */
const BN_STRIKES = [51500, 51600, 51700, 51800, 51900, 52000, 52100, 52200, 52300, 52400, 52500];
const BN_CALL = { oi: [400000, 450000, 500000, 520000, 560000, 600000, 640000, 700000, 760000, 820000, 900000], close: [1050.0, 975.5, 903.0, 823.4, 755.0, 690.2, 628.6, 570.5, 516.0, 465.3, 418.0], chg: [-5000, 0, 5000, 10000, 20000, 30000, 40000, 50000, 60000, 70000, 90000] };
const BN_PUT = { oi: [1100000, 980000, 860000, 760000, 600000, 450000, 300000, 200000, 120000, 80000, 40000], close: [335.0, 362.4, 392.0, 424.1, 459.4, 520.2, 560.0, 603.3, 650.1, 700.0, 752.5], chg: [80000, 60000, 50000, 40000, 20000, 10000, 0, -10000, -20000, -20000, -10000] };
const sum = (xs: number[]) => xs.reduce((a, b) => a + b, 0);
const BN_CHAIN = {
  symbol: "BANKNIFTY",
  summary: {
    as_of: "2026-10-12", expiry: "2026-10-28", spot: 52040.0, atm_strike: 52000,
    total_call_oi: sum(BN_CALL.oi), total_put_oi: sum(BN_PUT.oi), total_call_oi_change: sum(BN_CALL.chg), total_put_oi_change: sum(BN_PUT.chg),
    pcr: 0.8015, max_pain: 51800, max_call_oi: { strike: 52500, oi: 900000 }, max_put_oi: { strike: 51500, oi: 1100000 },
    days_to_expiry: 16, forward: 52160.0, forward_basis: "future", rate_pct: 5.75, atm_iv: 14.25, expected_move: 1210.4, expected_move_pct: 2.33,
  },
  strikes: BN_STRIKES.map((strike, i) => ({
    strike,
    call: side(BN_CALL.close[i], BN_CALL.oi[i], BN_CALL.chg[i], strike === 52000 ? 14.1 : null),
    put: side(BN_PUT.close[i], BN_PUT.oi[i], BN_PUT.chg[i], strike === 52000 ? 14.4 : null),
  })),
  strike_count: 11, strikes_returned: 11, lot_size: 30,
};
const BN_EXPIRIES = { symbol: "BANKNIFTY", as_of: "2026-10-12", expiries: [{ expiry: "2026-10-28", days_to_expiry: 16 }], count: 1 };
/** GET /api/fno/{symbol}/futures: settle 52,160 − spot 52,040 = +120.00 premium; OI change +84,000. */
const BN_FUTURES = { symbol: "BANKNIFTY", as_of: "2026-10-12", spot: 52040.0, lot_size: 30, futures: [{ expiry: "2026-10-28", close: 52161.0, settle: 52160.0, oi: 2100000, change_in_oi: 84000, volume: 900000, basis: 120.0 }], count: 1 };

/**
 * FIXFNO, a made-up F&O stock: five strikes, spot 1,502.50 → ATM 1,500. Totals call 16,00,000, put 15,00,000 → PCR 0.9375 → 0.94.
 * Max pain: 1,480 → 1.98 Cr, 1,500 → 1.32 Cr, 1,520 → 1.96 Cr → 1,500. Straddle 31.50 + 27.60 = 59.10 = 3.93% of 1,502.50.
 */
const FIX_STRIKES = [1460, 1480, 1500, 1520, 1540];
const FIX_CALL = { oi: [100000, 150000, 300000, 450000, 600000], close: [52.0, 41.2, 31.5, 23.1, 16.4], chg: [0, 10000, 20000, 30000, 40000] };
const FIX_PUT = { oi: [500000, 420000, 350000, 150000, 80000], close: [12.1, 18.9, 27.6, 39.0, 52.3], chg: [30000, 20000, 10000, 0, -5000] };
const FIX_CHAIN = {
  symbol: "FIXFNO",
  summary: {
    as_of: "2026-10-12", expiry: "2026-10-27", spot: 1502.5, atm_strike: 1500,
    total_call_oi: sum(FIX_CALL.oi), total_put_oi: sum(FIX_PUT.oi), total_call_oi_change: sum(FIX_CALL.chg), total_put_oi_change: sum(FIX_PUT.chg),
    pcr: 0.9375, max_pain: 1500, max_call_oi: { strike: 1540, oi: 600000 }, max_put_oi: { strike: 1460, oi: 500000 },
    days_to_expiry: 15, forward: 1509.6, forward_basis: "future", rate_pct: 5.75, atm_iv: 26.4, expected_move: 59.1, expected_move_pct: 3.93,
  },
  strikes: FIX_STRIKES.map((strike, i) => ({ strike, call: side(FIX_CALL.close[i], FIX_CALL.oi[i], FIX_CALL.chg[i]), put: side(FIX_PUT.close[i], FIX_PUT.oi[i], FIX_PUT.chg[i]) })),
  strike_count: 5, strikes_returned: 5, lot_size: 500,
};
const FIX_EXPIRIES = { symbol: "FIXFNO", as_of: "2026-10-12", expiries: [{ expiry: "2026-10-27", days_to_expiry: 15 }], count: 1 };
const FIX_FUTURES = { symbol: "FIXFNO", as_of: "2026-10-12", spot: 1502.5, lot_size: 500, futures: [{ expiry: "2026-10-27", close: 1510.0, settle: 1509.6, oi: 5400000, change_in_oi: -120000, volume: 2100000, basis: 7.1 }], count: 1 };

/**
 * GET /api/fno/scan/buildup (backend/nidp/services/daas_api/routers/desk_market.py :: fno_buildup, via routes/fno.py).
 * Rows come largest |OI chg %| first; the label is null when a change is missing (counted as no_data). FIXFNO is the
 * stock the lab can load (fnoData), so its row opens a real chain. FIXGEN01…20 fill the scatter (made-up values).
 */
const bu = (symbol: string, price: number | null, oiPct: number | null, label: string | null, extra: Record<string, unknown> = {}) => ({
  symbol, near_expiry: "2026-10-27", close: price == null ? null : 1000 * (1 + price / 100), prev_close: price == null ? null : 1000,
  price_chg_pct: price, oi: 1_000_000, oi_chg: oiPct == null ? null : Math.round((1_000_000 * oiPct) / (100 + oiPct)), oi_chg_pct: oiPct, expiries: 3, label, ...extra,
});
const labelFor = (p: number, o: number) => (p > 0 && o > 0 ? "long_buildup" : p < 0 && o > 0 ? "short_buildup" : p > 0 && o < 0 ? "short_covering" : p < 0 && o < 0 ? "long_unwinding" : "neutral");
const GEN = Array.from({ length: 20 }, (_, i) => {
  const p = Number((((i * 37) % 23) / 5 - 2.2).toFixed(2));
  const o = Number((((i * 53) % 29) / 6 - 2.4).toFixed(2));
  return bu(`FIXGEN${String(i + 1).padStart(2, "0")}`, p, o, labelFor(p, o));
});
const BUILDUP_ROWS = [
  // The PRD §10.6 fields on three rows (the rest send none, so they read "—"): cash close and change, the cash check,
  // vol_z20 with its date, futures contracts, the F&O master, days to expiry and the risk flags.
  bu("FIXFNO", 2.03, 12.5, "long_buildup", {
    close: 1510.0, prev_close: 1480.0, oi: 5_400_000, oi_chg: 600_000, days_to_expiry: 14, fut_contracts: 36223, fut_turnover_cr: 2734.5,
    cash_close: 1502.5, cash_prev_close: 1475.0, cash_chg_pct: 1.86, cash_volume: 4_100_000, cash_confirmation: "confirms",
    vol_z20: 1.42, vol_z20_date: "2026-10-12", fno_eligible: true, master_date: "2026-10-13", risk_flags: [],
  }),
  bu("FIXSHORT", -1.8, 9.2, "short_buildup", { cash_close: 99.1, cash_prev_close: 98.0, cash_chg_pct: 1.12, cash_confirmation: "diverges", fno_eligible: false, master_date: "2026-10-13", risk_flags: [] }),
  bu("FIXCOVER", 0.9, -7.4, "short_covering", { near_expiry: "2026-10-16", days_to_expiry: 3, risk_flags: ["expiry_week", "rollover", "no_cash_price"] }),
  bu("FIXUNWIND", -2.4, -5.1, "long_unwinding"),
  bu("FIXLONG2", 0.4, 4.9, "long_buildup", { expiries: 2 }),
  ...GEN.filter((r) => Math.abs(r.oi_chg_pct as number) >= 1).sort((a, b) => Math.abs(b.oi_chg_pct as number) - Math.abs(a.oi_chg_pct as number)),
  ...GEN.filter((r) => Math.abs(r.oi_chg_pct as number) < 1).sort((a, b) => Math.abs(b.oi_chg_pct as number) - Math.abs(a.oi_chg_pct as number)),
  bu("FIXFLAT", 0.0, 0.0, "neutral"),
  bu("FIXNODATA", null, null, null, { expiries: 1 }),
];
const countBy = (label: string | null) => BUILDUP_ROWS.filter((r) => r.label === label).length;
const RISK_FLAG_TEXT = {
  expiry_week: "The nearest contract expires within 7 calendar days: price and OI moves are distorted by expiry.",
  rollover: "Rollover: the next expiry now holds more open interest than the nearest, so positions are moving between contracts.",
  no_cash_price: "No cash-market close for the day, so the futures move cannot be checked against the cash market.",
};
const INTRADAY_REASON = "No intraday open interest is collected: the F&O data is the end-of-day bhavcopy, and the intraday bar collector stores no OI and no NFO contracts. A 15-minute confirmation cannot be worked out.";
/** NIFTY's index-futures row: its near future −0.82 % (22,648.50 vs 22,834.80), OI +0.69 %, the Nifty 50 close −0.44 %. */
const NIFTY_FUT = bu("NIFTY", -0.82, 0.69, "short_buildup", {
  close: 22648.5, prev_close: 22834.8, cash_close: 22622.7, cash_prev_close: 22721.95, cash_chg_pct: -0.44, cash_confirmation: "confirms",
  index_name: "Nifty 50", fno_eligible: true, risk_flags: [],
});
const BUILDUP = {
  as_of: "2026-10-13", source: "NSE F&O bhavcopy (nidp.fno_bhavcopy), stock futures", universe: BUILDUP_ROWS.length,
  counts: { long_buildup: countBy("long_buildup"), short_buildup: countBy("short_buildup"), short_covering: countBy("short_covering"), long_unwinding: countBy("long_unwinding"), neutral: countBy("neutral"), no_data: countBy(null) },
  rows: BUILDUP_ROWS,
  indices: [NIFTY_FUT],
  index_source: "NSE F&O bhavcopy (nidp.fno_bhavcopy), index futures; index close from nidp.index_eod",
  sources: {
    cash: "NSE equity bhavcopy (nidp.prices_eod) for the cash close and volume",
    rvol: "vol_z20 from nidp.stock_features_daily (technical indicator engine)",
    master: "NSE F&O lot-size master fo_mktlots.csv (nidp.security_reference_daily.fno_eligible)",
  },
  master: { as_of: "2026-10-13", eligible: 1, not_eligible: 1, unknown: BUILDUP_ROWS.length - 2 },
  risk_flag_text: RISK_FLAG_TEXT,
  setup_quality: "not_validated",
  intraday: { status: "unavailable", reason: INTRADAY_REASON },
};

/** Every /api/fno/* route. Returns the paths (with query) the page asked for. */
async function fnoData(page: Page, opts: { buildup?: unknown } = {}): Promise<string[]> {
  const asked: string[] = [];
  page.on("request", (r) => {
    const u = new URL(r.url());
    if (u.pathname.startsWith("/api/fno/")) asked.push(u.pathname + u.search);
  });
  await json(page, "**/api/fno/NIFTY/expiries", load("copilot-options-expiries.json"));
  await json(page, "**/api/fno/NIFTY/futures", load("copilot-options-futures.json"));
  await page.route("**/api/fno/NIFTY/chain*", (route) => {
    const expiry = new URL(route.request().url()).searchParams.get("expiry") ?? "2026-10-27";
    return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(load(NIFTY_CHAINS[expiry] ?? NIFTY_CHAINS["2026-10-27"])) });
  });
  await json(page, "**/api/fno/BANKNIFTY/expiries", BN_EXPIRIES);
  await json(page, "**/api/fno/BANKNIFTY/futures", BN_FUTURES);
  await json(page, "**/api/fno/BANKNIFTY/chain*", BN_CHAIN);
  await json(page, "**/api/fno/FIXFNO/expiries", FIX_EXPIRIES);
  await json(page, "**/api/fno/FIXFNO/futures", FIX_FUTURES);
  await json(page, "**/api/fno/FIXFNO/chain*", FIX_CHAIN);
  // backend/routes/fno.py answers 404 with no_data(sym) when the bhavcopy has no rows for the underlying
  await json(page, "**/api/fno/NOFNO/**", { detail: "No F&O data for NOFNO" }, 404);
  await json(page, "**/api/fno/scan/buildup*", opts.buildup ?? BUILDUP);
  return asked;
}

/** The FIXFNO chain, futures and expiries under another made-up ticker (for the short / neutral readings). */
async function stockFno(page: Page, sym: string) {
  await json(page, `**/api/fno/${sym}/expiries`, { ...FIX_EXPIRIES, symbol: sym });
  await json(page, `**/api/fno/${sym}/futures`, { ...FIX_FUTURES, symbol: sym });
  await json(page, `**/api/fno/${sym}/chain*`, { ...FIX_CHAIN, symbol: sym });
}

const MINUS = "−";
const n2 = (n: number) => new Intl.NumberFormat("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(n);
const n0 = (n: number) => new Intl.NumberFormat("en-IN", { maximumFractionDigits: 0 }).format(n);
const signedPct = (v: number | null, d = 2) => (v == null ? "—" : `${v > 0 ? "+" : v < 0 ? MINUS : ""}${Math.abs(v).toFixed(d)}%`);
const dayY = (iso: string) => new Date(`${iso}T12:00:00+05:30`).toLocaleDateString("en-IN", { timeZone: "Asia/Kolkata", day: "numeric", month: "short", year: "numeric" });
const dayS = (iso: string) => new Date(`${iso}T12:00:00+05:30`).toLocaleDateString("en-IN", { timeZone: "Asia/Kolkata", day: "numeric", month: "short" });
const QUAD_RULE: Record<string, string> = { long_buildup: "Price up, OI up", short_buildup: "Price down, OI up", short_covering: "Price up, OI down", long_unwinding: "Price down, OI down", neutral: "Price or OI unchanged" };
const LABEL: Record<string, string> = { long_buildup: "Long build-up", short_buildup: "Short build-up", short_covering: "Short covering", long_unwinding: "Long unwinding", neutral: "Neutral" };
const chainRow = (page: Page, strike: number) => page.locator(`[data-testid="desk-fno-chain-row"][data-strike="${strike}"]`);
const tagsOf = async (page: Page, strike: number) => (await chainRow(page, strike).locator('[data-testid^="desk-fno-tag-"]').allTextContents()).join(" ");
const tileLabels = (page: Page) => page.getByTestId("desk-fno-stats").locator(".cp-eyebrow").allTextContents();
const kv = (page: Page, kind: string, k: string) => page.locator(`[data-testid="desk-fno-strat-${kind}-kv-value"][data-k="${k}"]`);

/** Weekly = the nearest upcoming expiry without a same-day future, before the farthest future; monthly = the nearest with one. */
function expectedSwitch(expiries: Array<{ expiry: string; days_to_expiry: number }>, futures: Array<{ expiry: string }>) {
  const up = expiries.filter((e) => e.days_to_expiry > 0);
  const fut = futures.map((f) => f.expiry);
  const last = [...fut].sort().pop() ?? null;
  return {
    weekly: up.find((e) => !fut.includes(e.expiry) && (last == null || e.expiry < last)) ?? null,
    monthly: up.find((e) => fut.includes(e.expiry)) ?? null,
  };
}

test.describe("Smart trading desk — Options & futures lab", () => {
  test.beforeEach(async ({ page }) => {
    await deskBase(page);
  });

  test("header, underlying row, expiry switch, the eight stats and the sub-tabs in the design's order", async ({ page }) => {
    const asked = await fnoData(page);
    const home = load("markets-home.json");
    const chain = load("copilot-options-chain.json");
    const exp = load("copilot-options-expiries.json");
    const fut = load("copilot-options-futures.json");
    await page.goto(`${DESK}?tab=fno`);

    const tab = page.getByTestId("desk-fno");
    await expect(tab).toContainText("Options & futures lab · NSE F&O");
    for (const p of ["Trader mode", "Analysis only", "End of day"]) await expect(tab.locator(".cp-pill", { hasText: p }).first()).toBeVisible();
    await expect(page.getByTestId("desk-fno-title")).toHaveText("Build, test and understand option trades.");
    await expect(page.getByTestId("desk-fno-title").locator("em")).toHaveText("option trades");

    // Right block: the chain's spot and day, India VIX from the markets tape (not live → its own day).
    await expect(page.getByTestId("desk-fno-spot")).toHaveText(n2(chain.summary.spot));
    await expect(page.getByTestId("desk-fno-asof")).toHaveText(`Bhavcopy ${dayY(chain.summary.as_of)} · end of day`);
    const vix = home.indices.find((i: { is_vix: boolean }) => i.is_vix);
    expect(home.is_live).toBe(false);
    await expect(page.getByTestId("desk-fno-vix")).toHaveText(`India VIX ${n2(vix.value)} · ${dayS(home.as_of.slice(0, 10))}`);

    // Underlying row: NIFTY on, no stock loaded, the ticker box.
    await expect(page.getByTestId("desk-fno-symbol-nifty")).toHaveAttribute("aria-pressed", "true");
    await expect(page.getByTestId("desk-fno-symbol-banknifty")).toHaveAttribute("aria-pressed", "false");
    await expect(page.getByTestId("desk-fno-loaded")).toHaveCount(0);
    await expect(page.getByTestId("desk-fno-symbol-input")).toHaveAttribute("placeholder", "Name or ticker, e.g. TCS");

    // Expiry switch from the expiry and futures lists; the nearest (monthly here) is on.
    const sw = expectedSwitch(exp.expiries, fut.futures);
    expect(sw.weekly && sw.monthly).toBeTruthy();
    await expect(page.getByTestId("desk-fno-expiry-weekly")).toHaveText(`Weekly · ${dayS(sw.weekly!.expiry)}`);
    await expect(page.getByTestId("desk-fno-expiry-monthly")).toHaveText(`Monthly · ${dayS(sw.monthly!.expiry)}`);
    await expect(page.getByTestId("desk-fno-expiry-monthly")).toHaveAttribute("aria-pressed", "true");
    await expect(page.getByTestId("desk-fno-expiry-weekly")).toBeEnabled();

    // The eight tiles, in the design's order and words.
    const near = fut.futures[0];
    expect(await tileLabels(page)).toEqual(["ATM implied volatility", "Expected move to expiry", `Futures · ${dayS(near.expiry)}`, "Days to expiry", "Put-call ratio · OI", "Max pain", "OI range", "Futures build-up"]);
    const s = chain.summary;
    await expect(page.getByTestId("desk-fno-atm-iv")).toHaveText(`${n2(s.atm_iv)}%`);
    await expect(page.getByTestId("desk-fno-expected-move")).toHaveText(`±${n2(s.expected_move)}`);
    await expect(page.getByTestId("desk-fno-stats")).toContainText(`${n2(s.expected_move_pct)}% of spot · ATM straddle at the close`);
    await expect(page.getByTestId("desk-fno-futures")).toHaveText(n2(near.settle));
    await expect(page.getByTestId("desk-fno-stats")).toContainText(`+${n2(near.basis)} premium to spot`);
    await expect(page.getByTestId("desk-fno-stats")).toContainText(`day +${n2(near.change)} (+${n2(near.change_pct)}%)`);
    await expect(page.getByTestId("desk-fno-days")).toHaveText(String(s.days_to_expiry));
    await expect(page.getByTestId("desk-fno-pcr")).toHaveText(n2(s.pcr));
    await expect(page.getByTestId("desk-fno-max-pain")).toHaveText(n0(s.max_pain));
    await expect(page.getByTestId("desk-fno-oi-range")).toHaveText(`${n0(s.max_put_oi.strike)} – ${n0(s.max_call_oi.strike)}`);
    // An index's build-up comes from the scan's index-futures row: price −0.82 %, OI +0.69 % → short build-up.
    await expect(page.getByTestId("desk-fno-buildup-tile")).toHaveText(LABEL[NIFTY_FUT.label as string]);
    await expect(page.getByTestId("desk-fno-stats")).toContainText(`Price ${signedPct(NIFTY_FUT.price_chg_pct)} · OI ${signedPct(NIFTY_FUT.oi_chg_pct)} · ${dayS(BUILDUP.as_of)}`);
    await expect(page.getByTestId("desk-fno-heuristic")).toContainText("heuristic readings of two figures, not proof of what traders intended");
    await expect(page.getByTestId("desk-fno-trust")).toContainText("NSE F&O bhavcopy · End of day");
    await expect(page.getByTestId("desk-fno-trust")).toHaveAttribute("data-mode", "eod");
    await expect(page.getByTestId("desk-fno-model-note")).toContainText(`Model estimate from end-of-day prices (Black-76), at an interest rate of ${n2(s.rate_pct)}% a year`);
    await expect(page.getByTestId("desk-fno-read-first")).toHaveCount(0);

    // Sub-tabs: the design's four, in order; OI build-up first and open.
    await expect(page.getByRole("tablist", { name: "Options and futures views" }).getByRole("tab")).toHaveText(["OI build-up · F&O stocks", "NIFTY & BANKNIFTY", "Option chain OI · NIFTY", "Paper strategies"]);
    await expect(page.getByTestId("desk-fno-view-buildup")).toHaveAttribute("aria-selected", "true");

    // Weekly: the other expiry's chain.
    const parity = load("copilot-options-chain-parity.json");
    await page.getByTestId("desk-fno-expiry-weekly").click();
    await expect(page.getByTestId("desk-fno-expiry-weekly")).toHaveAttribute("aria-pressed", "true");
    await expect(page.getByTestId("desk-fno-days")).toHaveText(String(parity.summary.days_to_expiry));
    await expect(page.getByTestId("desk-fno-expected-move")).toHaveText(`±${n2(parity.summary.expected_move)}`);
    expect(asked).toContain(`/api/fno/NIFTY/chain?expiry=${sw.weekly!.expiry}`);
  });

  test("TC-31 option chain OI: header, the seven columns in order, ATM / R / S / MP tags and the reading", async ({ page }) => {
    await fnoData(page);
    await page.goto(`${DESK}?tab=fno`);
    await page.getByTestId("desk-fno-view-chain").click();

    await expect(page.getByTestId("desk-fno-chain-head")).toHaveText("Option chain OI · NIFTY · 27 Oct 2026");
    await expect(page.getByTestId("desk-fno-chain")).toContainText("R call wall · S put wall · MP max pain");
    await expect(page.getByTestId("desk-fno-chain-header").getByRole("columnheader")).toHaveText(["Call OI chg", "Call OI", "Call close", "Strike", "Put close", "Put OI", "Put OI chg"]);
    // NIFTY: ATM 25,000 is also max pain; R (most call OI) 25,300; S (most put OI) 24,700
    await expect(page.getByTestId("desk-fno-chain-row")).toHaveCount(7);
    await expect(chainRow(page, 25000)).toHaveAttribute("data-atm", "true");
    expect(await tagsOf(page, 25000)).toBe("ATM MP");
    expect(await tagsOf(page, 25300)).toBe("R");
    expect(await tagsOf(page, 24700)).toBe("S");
    // the 25,300 call: OI 30,00,000 = 30.00 L, change +2,40,000 = +2.40 L, close 131.30
    await expect(chainRow(page, 25300).locator('[data-col="call-oi"]')).toHaveText("30.00 L");
    await expect(chainRow(page, 25300).locator('[data-col="call-oi-change"]')).toHaveText("+2.40 L");
    await expect(chainRow(page, 25300).locator('[data-col="call-close"]')).toHaveText("131.30");
    const read = page.getByTestId("desk-fno-chain-read");
    await expect(read).toContainText("the most call open interest is at 25,300 (30.00 L), the most put open interest at 24,700 (30.00 L), the put-call ratio on open interest is 0.96, max pain is 25,000.");
    await expect(read).toContainText("The end-of-day spot of 25,010.00 is between the two.");

    // BANKNIFTY: four different strikes — ATM 52,000, MP 51,800, R 52,500, S 51,500; the tab names it.
    await page.getByTestId("desk-fno-symbol-banknifty").click();
    await expect(page.getByTestId("desk-fno-view-chain")).toHaveText("Option chain OI · BANKNIFTY");
    await expect(page.getByTestId("desk-fno-chain-row")).toHaveCount(BN_STRIKES.length);
    expect(await tagsOf(page, 52000)).toBe("ATM");
    expect(await tagsOf(page, 51800)).toBe("MP");
    expect(await tagsOf(page, 52500)).toBe("R");
    expect(await tagsOf(page, 51500)).toBe("S");
    // BANKNIFTY lists one (monthly) expiry: weekly is off.
    await expect(page.getByTestId("desk-fno-expiry-weekly")).toBeDisabled();
    await expect(page.getByTestId("desk-fno-expiry-monthly")).toHaveText(`Monthly · ${dayS(BN_EXPIRIES.expiries[0].expiry)}`);
  });

  test("PRD 17.2 #4/#9: IV, Greeks and per-option OI build-up are collapsed by default, with units, model and the reason for a gap", async ({ page }) => {
    await fnoData(page);
    await page.goto(`${DESK}?tab=fno`);
    await page.getByTestId("desk-fno-view-chain").click();
    const chain = load("copilot-options-chain.json");
    const toggle = page.getByTestId("desk-fno-model-toggle");
    await expect(toggle).toHaveAttribute("aria-expanded", "false");
    await expect(page.getByTestId("desk-fno-model-row")).toHaveCount(0);
    await toggle.click();
    await expect(toggle).toHaveAttribute("aria-expanded", "true");
    await expect(page.getByTestId("desk-fno-model-row")).toHaveCount(chain.strikes.length);
    await expect(page.getByTestId("desk-fno-model-header").getByRole("columnheader")).toHaveText(["Strike", ...["IV %", "Delta", "Gamma", "Theta", "Vega", "Build-up"], ...["IV %", "Delta", "Gamma", "Theta", "Vega", "Build-up"]]);
    // 24,800 call from the fixture: IV 13.00, delta 0.6571, theta -7.9948 a day, vega 18.5977 a point, short covering.
    const row = page.locator('[data-testid="desk-fno-model-row"][data-strike="24800"]');
    const c = chain.strikes.find((r: { strike: number }) => r.strike === 24800).call;
    await expect(row.locator('[data-col="call-iv"]')).toHaveText(n2(c.iv));
    await expect(row.locator('[data-col="call-delta"]')).toHaveText("+0.6571");
    await expect(row.locator('[data-col="call-theta"]')).toHaveText(`${MINUS}7.9948`);
    await expect(row.locator('[data-col="call-vega"]')).toHaveText("18.5977");
    await expect(row.locator('[data-col="call-buildup"]')).toHaveText("short covering");
    // 24,700 call: close 355.00 is below the discounted intrinsic value of 25,060 - 24,700 -> no IV, "—" with the reason.
    const dead = page.locator('[data-testid="desk-fno-model-row"][data-strike="24700"]');
    await expect(dead.locator('[data-col="call-iv"]')).toHaveText("—");
    await expect(dead.locator('[data-col="call-iv"]')).toHaveAttribute("title", /at or below intrinsic value/);
    await expect(dead.locator('[data-col="call-delta"]')).toHaveText("—");
    // The model, rate, as-of and units are on screen.
    const a = page.getByTestId("desk-fno-model-assumptions");
    await expect(a).toContainText("Black-76");
    await expect(a).toContainText("5.75% a year");
    await expect(a).toContainText("12 Oct");
    await expect(a).toContainText("forward 25,060.00");
    const u = page.getByTestId("desk-fno-model-units");
    await expect(u).toContainText("theta is the price change over one calendar day");
    await expect(u).toContainText("vega is the price change per one volatility point");
    await expect(u).toContainText("per one-point move in the forward");
    await toggle.click();
    await expect(page.getByTestId("desk-fno-model-row")).toHaveCount(0);
  });

  test("TC-30 NIFTY & BANKNIFTY cards: head, spot, headline, OI range bar, five rows and the chain link", async ({ page }) => {
    await fnoData(page);
    await page.goto(`${DESK}?tab=fno`);
    await page.getByTestId("desk-fno-view-indices").click();

    const n = "desk-fno-card-NIFTY";
    await expect(page.getByTestId(`${n}-head`)).toHaveText("NIFTY27 Oct 2026 expiry");
    // Index futures build-up from the scan's index row; BANKNIFTY has none in the scan, so "—".
    await expect(page.getByTestId(`${n}-buildup`)).toHaveText(LABEL[NIFTY_FUT.label as string]);
    await expect(page.getByTestId(`${n}-fut-chg`)).toHaveText(`${signedPct(NIFTY_FUT.price_chg_pct)} · same way as the index`);
    await expect(page.getByTestId("desk-fno-card-BANKNIFTY-buildup")).toHaveText("Build-up —");
    await expect(page.getByTestId(`${n}-spot`)).toHaveText("25,010.00");
    // markets-home.json is for 13 Oct; the bhavcopy is 12 Oct — no same-session change.
    await expect(page.getByTestId(`${n}-change`)).toHaveText("change —");
    await expect(page.getByTestId(`${n}-headline`)).toHaveText("Spot sits between the 24,700 put wall and the 25,300 call wall.");
    await expect(page.getByTestId(n)).toContainText("OI range and expected move");
    await expect(page.getByTestId(`${n}-put-wall`)).toHaveText("24,700");
    await expect(page.getByTestId(`${n}-call-wall`)).toHaveText("25,300");
    await expect(page.getByTestId(`${n}-band`)).toHaveText(`${n2(25010 - 487.05)}–${n2(25010 + 487.05)}`);
    await expect(page.getByTestId(`${n}-futures`)).toHaveText("25,060.00 · +50.00 premium");
    await expect(page.getByTestId(`${n}-fut-oi-change`)).toHaveText(`${MINUS}2.50 L`);
    // PRD 17.2 #8: the futures route's previous close (25,020.00 here) gives the day change; BANKNIFTY's has none.
    await expect(page.getByTestId(`${n}-fut-day`)).toHaveText("+41.50 (+0.17%) · prev 25,020.00");
    await expect(page.getByTestId("desk-fno-card-BANKNIFTY-fut-day")).toHaveText("— · no previous close");
    await expect(page.getByTestId(`${n}-pcr`)).toHaveText("0.96");
    await expect(page.getByTestId(`${n}-max-pain`)).toHaveText("25,000");
    await expect(page.getByTestId(`${n}-move`)).toHaveText("12.00% · ±487.05 (1.95%)");

    const b = "desk-fno-card-BANKNIFTY";
    await expect(page.getByTestId(`${b}-spot`)).toHaveText("52,040.00");
    await expect(page.getByTestId(`${b}-headline`)).toHaveText("Spot sits between the 51,500 put wall and the 52,500 call wall.");
    await expect(page.getByTestId(`${b}-pcr`)).toHaveText("0.80");
    await expect(page.getByTestId(`${b}-max-pain`)).toHaveText("51,800");
    await expect(page.getByTestId(`${b}-move`)).toHaveText("14.25% · ±1,210.40 (2.33%)");
    await expect(page.getByTestId(`${b}-futures`)).toHaveText("52,160.00 · +120.00 premium");
    await expect(page.getByTestId(`${b}-fut-oi-change`)).toHaveText("+84,000");
    await expect(page.getByTestId(`${b}-band`)).toHaveText(`${n2(52040 - 1210.4)}–${n2(52040 + 1210.4)}`);

    await page.getByTestId(`${b}-open`).click();
    await expect(page.getByTestId(`${b}-open`)).toHaveCount(0);
    await expect(page.getByTestId("desk-fno-view-chain")).toHaveAttribute("aria-selected", "true");
    await expect(page.getByTestId("desk-fno-symbol-banknifty")).toHaveAttribute("aria-pressed", "true");
    await expect(page.getByTestId("desk-fno-chain-row")).toHaveCount(BN_STRIKES.length);
  });

  test("TC-30 an index card shows the day change only when the markets tape is the bhavcopy's own closed session", async ({ page }) => {
    await fnoData(page);
    const home = load("markets-home.json");
    const same = { ...home, as_of: "2026-10-12T16:00:00+05:30", is_live: false };
    await json(page, "**/api/markets/home", same);
    await page.goto(`${DESK}?tab=fno`);
    await page.getByTestId("desk-fno-view-indices").click();
    const nifty = home.indices.find((i: { name: string }) => i.name === "Nifty 50");
    const sgn = (v: number) => `${v > 0 ? "+" : v < 0 ? MINUS : ""}${n2(Math.abs(v))}`;
    await expect(page.getByTestId("desk-fno-card-NIFTY-change")).toHaveText(`${sgn(nifty.change)} (${sgn(nifty.change_pct)}%)`);
  });

  test("TC-32 a ticker loads that stock; the F&O list refuses an unknown one before any request", async ({ page }) => {
    const asked = await fnoData(page);
    await page.goto(`${DESK}?tab=fno`);
    await expect(page.getByTestId("desk-fno-pcr")).toHaveText("0.96");
    // The F&O list (the scan) has loaded.
    await expect(page.getByTestId("desk-buildup-row").first()).toBeVisible();

    await page.getByTestId("desk-fno-symbol-input").fill("fixfno ");
    await page.getByTestId("desk-fno-symbol-load").click();
    await expect(page.getByTestId("desk-fno-spot")).toHaveText("1,502.50");
    expect(asked).toContain("/api/fno/FIXFNO/expiries");
    const loaded = page.getByTestId("desk-fno-loaded");
    await expect(page.getByTestId("desk-fno-loaded-sym")).toHaveText("FIXFNO loaded");
    await expect(loaded.locator('[data-testid="entity-icon"][data-kind="stock"]')).toHaveAttribute("data-key", "FIXFNO");
    await expect(page.getByTestId("desk-fno-symbol-nifty")).toHaveAttribute("aria-pressed", "false");
    await expect(page.getByTestId("desk-fno-pcr")).toHaveText("0.94");
    await expect(page.getByTestId("desk-fno-expected-move")).toHaveText("±59.10");
    await expect(page.getByTestId("desk-fno-futures")).toHaveText("1,509.60");
    // A stock: only a monthly expiry (it shares the future's day), so weekly is off.
    await expect(page.getByTestId("desk-fno-expiry-weekly")).toBeDisabled();
    await expect(page.getByTestId("desk-fno-expiry-monthly")).toHaveAttribute("aria-pressed", "true");
    // The build-up tile: the scan's label and figures for FIXFNO.
    const f = BUILDUP_ROWS[0];
    await expect(page.getByTestId("desk-fno-buildup-tile")).toHaveText(LABEL[f.label as string]);
    await expect(page.getByTestId("desk-fno-stats")).toContainText(`Price ${signedPct(f.price_chg_pct)} · OI ${signedPct(f.oi_chg_pct)} · ${dayS(BUILDUP.as_of)}`);

    // Not in the F&O list: said plainly, nothing asked of the chain route.
    await page.getByTestId("desk-fno-symbol-input").fill("NOFNO");
    await page.getByTestId("desk-fno-symbol-load").click();
    await expect(page.getByTestId("desk-fno-symbol-unknown")).toHaveText(`NOFNO is not in NSE’s F&O list for ${dayY(BUILDUP.as_of)} (${BUILDUP.universe} stocks have futures), so it has no option chain to load.`);
    await expect(page.getByTestId("desk-fno-loaded-sym")).toHaveText("FIXFNO loaded");
    expect(asked.some((a) => a.startsWith("/api/fno/NOFNO"))).toBe(false);

    // A malformed ticker is refused before any request.
    await page.getByTestId("desk-fno-symbol-input").fill("BAD TICKER!");
    await page.getByTestId("desk-fno-symbol-load").click();
    await expect(page.getByTestId("desk-fno-symbol-error")).toBeVisible();

    // NIFTY again from its chip.
    await page.getByTestId("desk-fno-symbol-nifty").click();
    await expect(page.getByTestId("desk-fno-loaded")).toHaveCount(0);
    await expect(page.getByTestId("desk-fno-spot")).toHaveText("25,010.00");
  });

  test("TC-34 a company name is searched, then only F&O stocks load; several matches are listed; an exact ticker skips the search", async ({ page }) => {
    const asked = await fnoData(page);
    const searched: string[] = [];
    // GET /api/search/instruments?q → [{ name, ticker, type, sector }] (backend instrument search; MOCK — not real data)
    const HITS: Record<string, unknown[]> = {
      "fixture f&o": [{ name: "Fixture F&O Ltd", ticker: "FIXFNO", type: "equity", sector: "Auto" }],
      "fixf": [
        { name: "Fixture F&O Ltd", ticker: "FIXFNO", type: "equity", sector: "Auto" },
        { name: "Fixture Cash Only Ltd", ticker: "NOFNO", type: "equity", sector: "IT" },
      ],
      "cash only": [{ name: "Fixture Cash Only Ltd", ticker: "NOFNO", type: "equity", sector: "IT" }],
      "zzz corp": [],
    };
    await page.route("**/api/search/instruments*", (route) => {
      const q = (new URL(route.request().url()).searchParams.get("q") ?? "").toLowerCase();
      searched.push(q);
      return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(HITS[q] ?? []) });
    });
    await page.goto(`${DESK}?tab=fno`);
    await expect(page.getByTestId("desk-buildup-row").first()).toBeVisible();
    const input = page.getByTestId("desk-fno-symbol-input");
    const load = page.getByTestId("desk-fno-symbol-load");

    // An exact ticker never calls the search.
    await input.fill("FIXFNO");
    await load.click();
    await expect(page.getByTestId("desk-fno-loaded-sym")).toHaveText("FIXFNO loaded");
    expect(searched).toEqual([]);
    await page.getByTestId("desk-fno-symbol-nifty").click();
    await expect(page.getByTestId("desk-fno-loaded")).toHaveCount(0);

    // A name that matches one F&O stock loads it.
    await input.fill("Fixture F&O");
    await load.click();
    await expect(page.getByTestId("desk-fno-loaded-sym")).toHaveText("FIXFNO loaded");
    expect(searched).toEqual(["fixture f&o"]);
    await page.getByTestId("desk-fno-symbol-nifty").click();

    // Several matches: the F&O list's own tickers that contain the text (FIXFLAT) and the search's F&O hits (FIXFNO,
    // with its name) are offered together, once each; the search's non-F&O hit (NOFNO) is left out. Picking one loads it.
    await input.fill("fixf");
    await load.click();
    const offers = page.getByTestId("desk-fno-symbol-suggest");
    await expect(offers).toHaveCount(2);
    await expect(offers.nth(0)).toContainText("FIXFLAT");
    await expect(offers.nth(1)).toContainText("FIXFNO");
    await expect(offers.nth(1)).toContainText("Fixture F&O Ltd");
    await expect(page.locator("#desk-fno-symbol-problem")).not.toContainText("NOFNO");
    await offers.nth(1).click();
    await expect(page.getByTestId("desk-fno-loaded-sym")).toHaveText("FIXFNO loaded");
    await expect(offers).toHaveCount(0);
    await page.getByTestId("desk-fno-symbol-nifty").click();

    // Spaces and hyphens do not matter against the F&O list: "fix short" finds FIXSHORT with no help from the search.
    await input.fill("fix short");
    await load.click();
    await expect(page.getByTestId("desk-fno-loaded-sym")).toHaveText("FIXSHORT loaded");
    await expect.poll(() => asked).toContain("/api/fno/FIXSHORT/expiries");        // the chain route has no fixture for it; the request is the point
    await page.getByTestId("desk-fno-symbol-nifty").click();

    // A stock that is not in F&O is named and refused; no chain request is made for it.
    await input.fill("cash only");
    await load.click();
    await expect(page.getByTestId("desk-fno-symbol-unknown")).toHaveText(`Fixture Cash Only Ltd (NOFNO) is not in NSE’s F&O list for ${dayY(BUILDUP.as_of)} (${BUILDUP.universe} stocks have futures), so it has no option chain to load.`);
    expect(asked.some((a) => a.startsWith("/api/fno/NOFNO"))).toBe(false);

    // No match at all.
    await input.fill("zzz corp");
    await load.click();
    await expect(page.getByTestId("desk-fno-symbol-nomatch")).toHaveText("No stock matches “zzz corp”. Try the NSE ticker, e.g. RELIANCE.");
  });

  test("TC-34 when the stock search fails, the box says so and a typed ticker still works", async ({ page }) => {
    const asked = await fnoData(page);
    await json(page, "**/api/search/instruments*", { detail: "boom" }, 502);
    await page.goto(`${DESK}?tab=fno`);
    await expect(page.getByTestId("desk-buildup-row").first()).toBeVisible();
    await page.getByTestId("desk-fno-symbol-input").fill("fixture fno");
    await page.getByTestId("desk-fno-symbol-load").click();
    await expect(page.getByTestId("desk-fno-symbol-search-error")).toHaveText("Stock search is unavailable. Type the NSE ticker instead.");
    // A partial ticker still matches the F&O list itself, so it is offered even though the search failed.
    await page.getByTestId("desk-fno-symbol-input").fill("fixf");
    await page.getByTestId("desk-fno-symbol-load").click();
    await expect(page.getByTestId("desk-fno-symbol-suggest")).toHaveCount(2);
    await expect(page.getByTestId("desk-fno-symbol-search-error")).toHaveCount(0);
    await page.getByTestId("desk-fno-symbol-input").fill("FIXFNO");
    await page.getByTestId("desk-fno-symbol-load").click();
    await expect(page.getByTestId("desk-fno-loaded-sym")).toHaveText("FIXFNO loaded");
    expect(asked).toContain("/api/fno/FIXFNO/expiries");
  });

  test("TC-32 with the F&O list unavailable, the chain route answers for an unknown ticker", async ({ page }) => {
    const asked = await fnoData(page);
    await json(page, "**/api/fno/scan/buildup*", { detail: "upstream_unavailable" }, 502);
    await page.goto(`${DESK}?tab=fno`);
    await expect(page.getByTestId("desk-buildup-error")).toBeVisible({ timeout: 15_000 });
    await page.getByTestId("desk-fno-symbol-input").fill("NOFNO");
    await page.getByTestId("desk-fno-symbol-load").click();
    const none = page.getByTestId("desk-fno-stats-none");
    await expect(none).toContainText("No F&O rows for NOFNO on the latest day");
    await expect(none).toContainText("No F&O data for NOFNO");
    expect(asked).toContain("/api/fno/NOFNO/expiries");
  });

  test("TC-33 OI build-up: quadrant counts of N stocks, the scatter, the seven-column table, sort, filter, and a dot or a row loads the chain", async ({ page }) => {
    const asked = await fnoData(page);
    await page.goto(`${DESK}?tab=fno`);
    await expect(page.getByTestId("desk-fno-view-buildup")).toHaveAttribute("aria-selected", "true");

    for (const k of ["long_buildup", "short_buildup", "short_covering", "long_unwinding"] as const) {
      expect(BUILDUP.counts[k]).toBe(countBy(k));
      await expect(page.getByTestId(`desk-buildup-count-${k}`)).toHaveText(String(BUILDUP.counts[k]));
      await expect(page.getByTestId(`desk-buildup-of-${k}`)).toHaveText(`of ${BUILDUP.universe} stocks`);
    }
    await expect(page.getByTestId("desk-buildup-q-long_buildup")).toContainText("Price up, OI up");
    await expect(page.getByTestId("desk-buildup-neutral")).toHaveText(
      `${BUILDUP.counts.neutral} neutral (price or OI unchanged) · ${BUILDUP.counts.no_data} without a label (a change is missing) · ${BUILDUP.universe} F&O stocks scanned`,
    );

    // Scatter: the 24 largest OI moves either way among rows with both changes.
    const both = BUILDUP_ROWS.filter((r) => r.price_chg_pct != null && r.oi_chg_pct != null);
    const top = [...both].sort((a, b) => Math.abs(b.oi_chg_pct as number) - Math.abs(a.oi_chg_pct as number) || a.symbol.localeCompare(b.symbol)).slice(0, 24);
    await expect(page.getByTestId("desk-buildup-scatter-head")).toHaveText(`Price change vs futures OI change · ${top.length} largest OI moves`);
    await expect(page.getByTestId("desk-buildup-scatter")).toContainText("Click a dot to load its option chain");
    const dots = page.getByTestId("desk-buildup-dot");
    await expect(dots).toHaveCount(top.length);
    expect((await dots.evaluateAll((els) => els.map((e) => e.getAttribute("data-symbol")))).sort()).toEqual(top.map((r) => r.symbol).sort());
    await expect(page.locator('[data-testid="desk-buildup-dot"][data-selected="true"]')).toHaveCount(0);

    // Table: the design's columns in order, the route's order, count and sort note.
    await expect(page.getByTestId("desk-buildup-table").getByRole("columnheader")).toHaveText(
      ["Stock", "Price", "Futures OI", "Cash", "Cash check", "RVOL z", "Volume", "PCR", "IV", "Expiry · flags", "Quality", "Build-up"]);
    await expect(page.getByTestId("desk-buildup-table-head")).toContainText("Stock futures · OI build-up");
    await expect(page.getByTestId("desk-buildup-count")).toHaveText(`${BUILDUP_ROWS.length} stocks`);
    await expect(page.getByTestId("desk-buildup-sorted")).toHaveText("Sorted by OI change");
    const order = () => page.getByTestId("desk-buildup-row").evaluateAll((els) => els.map((e) => e.getAttribute("data-symbol")));
    expect(await order()).toEqual(BUILDUP_ROWS.map((r) => r.symbol));
    for (const r of BUILDUP_ROWS.slice(0, 6).concat(BUILDUP_ROWS.slice(-2))) {
      const row = page.locator(`[data-testid="desk-buildup-row"][data-symbol="${r.symbol}"]`);
      await expect(row.getByTestId("desk-buildup-symbol")).toHaveText(r.symbol);
      await expect(row.locator('[data-testid="entity-icon"]')).toHaveAttribute("data-key", r.symbol);
      await expect(row.getByTestId("desk-buildup-close")).toHaveText(r.close == null ? "—" : n2(r.close as number));
      await expect(row.getByTestId("desk-buildup-price")).toHaveText(signedPct(r.price_chg_pct));
      await expect(row.getByTestId("desk-buildup-oi")).toHaveText(signedPct(r.oi_chg_pct));
      await expect(row.getByTestId("desk-buildup-label")).toHaveText(r.label ? LABEL[r.label] : "—");
      await expect(row.getByTestId("desk-buildup-oi-cell")).toHaveAttribute("title", `Open interest ${(r.oi / 1e5).toFixed(2)} L, summed over ${r.expiries} ${r.expiries === 1 ? "expiry" : "expiries"}`);
      if (r.label) await expect(row.getByTestId("desk-buildup-desc")).toHaveText(QUAD_RULE[r.label]);
      // NIFTY is loaded: no stock has its own chain figures on screen. Volume is the scan's futures contracts.
      for (const c of ["pcr", "iv"]) await expect(row.getByTestId(`desk-buildup-${c}`)).toHaveText("—");
      const contracts = (r as { fut_contracts?: number }).fut_contracts;
      await expect(row.getByTestId("desk-buildup-volume")).toHaveText(contracts == null ? "—" : n0(contracts));
      await expect(row.getByTestId("desk-buildup-quality")).toHaveText("—");
    }

    // Sort by price change: high to low, then low to high; missing last both ways.
    const byPrice = (dir: 1 | -1) => [...BUILDUP_ROWS].sort((a, b) => {
      if (a.price_chg_pct == null) return 1;
      if (b.price_chg_pct == null) return -1;
      return dir * (a.price_chg_pct - b.price_chg_pct) || a.symbol.localeCompare(b.symbol);
    }).map((r) => r.symbol);
    await page.getByTestId("desk-buildup-sort-price").click();
    expect(await order()).toEqual(byPrice(-1));
    await expect(page.getByTestId("desk-buildup-sorted")).toHaveText("Sorted by price change, high to low");
    await page.getByTestId("desk-buildup-sort-price").click();
    expect(await order()).toEqual(byPrice(1));
    await page.getByTestId("desk-buildup-sort-symbol").click();
    expect(await order()).toEqual(BUILDUP_ROWS.map((r) => r.symbol).sort((a, b) => a.localeCompare(b)));

    // A quadrant filters the table and turns its own colour; again shows every row.
    await page.getByTestId("desk-buildup-q-short_buildup").click();
    await expect(page.getByTestId("desk-buildup-q-short_buildup")).toHaveAttribute("aria-pressed", "true");
    expect((await order()).sort()).toEqual(BUILDUP_ROWS.filter((r) => r.label === "short_buildup").map((r) => r.symbol).sort());
    await page.getByTestId("desk-buildup-q-short_buildup").click();
    await expect(page.getByTestId("desk-buildup-row")).toHaveCount(BUILDUP_ROWS.length);

    const src = page.getByTestId("desk-buildup-source");
    await expect(src).toContainText(`Source: ${BUILDUP.source}`);
    await expect(src).toContainText("end of day 13 Oct 2026");

    // A dot loads that stock's option chain.
    await page.locator('[data-testid="desk-buildup-dot"][data-symbol="FIXFNO"]').click();
    await expect(page.getByTestId("desk-fno-view-chain")).toHaveAttribute("aria-selected", "true");
    await expect(page.getByTestId("desk-fno-view-chain")).toHaveText("Option chain OI · FIXFNO");
    await expect(page.getByTestId("desk-fno-chain-row")).toHaveCount(FIX_STRIKES.length);
    expect(asked.some((a) => a.startsWith("/api/fno/FIXFNO/chain"))).toBe(true);

    // Back on the build-up: FIXFNO's dot is ringed and its row carries its own PCR and IV (volume is the scan's).
    await page.getByTestId("desk-fno-view-buildup").click();
    await expect(page.locator('[data-testid="desk-buildup-dot"][data-selected="true"]')).toHaveAttribute("data-symbol", "FIXFNO");
    const fixRow = page.locator('[data-testid="desk-buildup-row"][data-symbol="FIXFNO"]');
    // the scan's 36,223 contracts; FIX_CHAIN PCR 0.9375 → 0.94; ATM IV 26.4 → 26.4%
    await expect(fixRow.getByTestId("desk-buildup-volume")).toHaveText(n0(36223));
    await expect(fixRow.getByTestId("desk-buildup-pcr")).toHaveText("0.94");
    await expect(fixRow.getByTestId("desk-buildup-iv")).toHaveText("26.4%");
    await expect(page.getByTestId("desk-buildup-shown")).toContainText("(FIXFNO)");
  });

  test("PRD §10.2–§10.7: F&O master eligibility, cash check, RVOL, expiry and rollover flags, quality not validated, the 15-minute state unavailable", async ({ page }) => {
    await fnoData(page);
    await page.goto(`${DESK}?tab=fno`);
    const row = (sym: string) => page.locator(`[data-testid="desk-buildup-row"][data-symbol="${sym}"]`);
    const fix = BUILDUP_ROWS.find((r) => r.symbol === "FIXFNO") as (typeof BUILDUP_ROWS)[number] & Record<string, unknown>;
    // Cash close and change, the same-way check, vol_z20 with its date, contracts, the expiry and the flags.
    await expect(row("FIXFNO").getByTestId("desk-buildup-cash")).toContainText(n2(fix.cash_close as number));
    await expect(row("FIXFNO").getByTestId("desk-buildup-cash-chg")).toHaveText(signedPct(fix.cash_chg_pct as number));
    await expect(row("FIXFNO").getByTestId("desk-buildup-confirm")).toHaveText("Confirms");
    await expect(row("FIXFNO").getByTestId("desk-buildup-rvol")).toHaveText(`+${n2(fix.vol_z20 as number)}`);
    await expect(row("FIXFNO").getByTestId("desk-buildup-rvol")).toHaveAttribute("title", `vol_z20 for ${dayS("2026-10-12")} (the scan is for ${dayS(BUILDUP.as_of)})`);
    await expect(row("FIXFNO").getByTestId("desk-buildup-expiry")).toHaveText(`${dayS("2026-10-27")} · 14d`);
    // Futures down and cash up: the cash market does not confirm.
    await expect(row("FIXSHORT").getByTestId("desk-buildup-confirm")).toHaveText("Diverges");
    await expect(row("FIXSHORT").getByTestId("desk-buildup-confirm")).toHaveAttribute("data-state", "diverges");
    // Expiry week and rollover are disclosed with the route's own words (no-cash is said by the "—" cash check).
    const flags = row("FIXCOVER").getByTestId("desk-buildup-flag");
    await expect(flags).toHaveText(["Expiry week", "Rollover"]);
    await expect(flags.nth(0)).toHaveAttribute("title", RISK_FLAG_TEXT.expiry_week);
    await expect(row("FIXCOVER").getByTestId("desk-buildup-expiry")).toContainText(`${dayS("2026-10-16")} · 3d`);
    await expect(row("FIXCOVER").getByTestId("desk-buildup-confirm")).toHaveText("—");
    // Missing is not zero.
    await expect(row("FIXGEN01").getByTestId("desk-buildup-rvol")).toHaveText("—");
    await expect(row("FIXGEN01").getByTestId("desk-buildup-cash")).toContainText("—");
    // Quality: no validated model, so "—" with the reason; the §10.4 heuristic caveat; the master's count.
    await expect(row("FIXFNO").getByTestId("desk-buildup-quality")).toHaveAttribute("title", /no model of these readings has been tested/);
    await expect(page.getByTestId("desk-buildup-heuristic")).toHaveText(
      "These are heuristic readings of two figures, not proof of what traders intended. Rollovers, expiry, intraday noise and changes in who trades a contract can distort them.");
    await expect(page.getByTestId("desk-buildup-master")).toContainText(`F&O eligibility: 1 of ${BUILDUP.universe} scanned stocks are on the NSE F&O master (${dayS("2026-10-13")}) · 1 in the bhavcopy but not on the master`);
    // 15-minute confirmation: the route's state (unavailable) and its reason; never a made-up confirmed state.
    const intraday = page.getByTestId("desk-fno-intraday");
    await expect(intraday).toHaveAttribute("data-state", "unavailable");
    await expect(page.getByTestId("desk-fno-intraday-reason")).toContainText(INTRADAY_REASON);
    await expect(page.getByTestId("desk-fno-intraday-unavailable")).toContainText("current");
    await expect(page.getByTestId("desk-fno-intraday-confirmed")).not.toContainText("current");
    await expect(page.getByTestId("desk-buildup-trust")).toHaveAttribute("data-maker", "rules");
    await expect(page.getByTestId("desk-buildup-trust")).toContainText("End of day");
    // §10.2: a loaded stock says what the NSE F&O master says.
    await row("FIXFNO").click();
    await expect(page.getByTestId("desk-fno-eligible")).toHaveText(`F&O eligible · NSE F&O master ${dayS("2026-10-13")}`);
    await expect(page.getByTestId("desk-fno-eligible")).toHaveAttribute("data-eligible", "true");
  });

  test("TC-33 OI build-up: a failed scan shows an error with retry; the keyboard opens a row", async ({ page }) => {
    await fnoData(page);
    let failing = true;
    await page.route("**/api/fno/scan/buildup*", (route) => (failing
      ? route.fulfill({ status: 502, contentType: "application/json", body: JSON.stringify({ detail: "upstream_unavailable" }) })
      : route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(BUILDUP) })));
    await page.goto(`${DESK}?tab=fno`);
    const err = page.getByTestId("desk-buildup-error");
    await expect(err.getByRole("alert")).toContainText("OI build-up across F&O stocks didn’t load", { timeout: 15_000 });
    failing = false;
    await err.getByRole("button", { name: /Retry/ }).click();
    await expect(page.getByTestId("desk-buildup-row")).toHaveCount(BUILDUP_ROWS.length);
    await page.locator('[data-testid="desk-buildup-row"][data-symbol="FIXFNO"]').focus();
    await page.keyboard.press("Enter");
    await expect(page.getByTestId("desk-fno-loaded-sym")).toHaveText("FIXFNO loaded");
    await expect(page.getByTestId("desk-fno-view-chain")).toHaveAttribute("aria-selected", "true");
  });

  test("paper strategies: Build a strategy opens the Strategy Builder for the stock with the chain date as its source; an index has no such button", async ({ page }) => {
    await fnoData(page);
    await page.goto(`${DESK}?tab=fno`);
    await page.getByTestId("desk-fno-view-strategies").click();
    await expect(page.getByTestId("desk-fno-strat-build")).toHaveCount(0);       // NIFTY is an index: plans are for one stock
    await page.getByTestId("desk-fno-view-buildup").click();
    await page.locator('[data-testid="desk-buildup-row"][data-symbol="FIXFNO"]').focus();
    await page.keyboard.press("Enter");
    await expect(page.getByTestId("desk-fno-loaded-sym")).toHaveText("FIXFNO loaded");
    await page.getByTestId("desk-fno-view-strategies").click();
    await page.getByTestId("desk-fno-strat-build").click();
    await expect(page).toHaveURL(/view=strategy/);
    await expect(page).toHaveURL(/sym=FIXFNO/);
    await expect(page).toHaveURL(/src_kind=lab/);
    await expect(page).toHaveURL(/src_date=2026-10-12/);
    await expect(page.getByTestId("in-symbol")).toHaveValue("FIXFNO");
    await expect(page.getByTestId("builder-source")).toHaveText("Started from the Options & futures lab, chain as of 12 Oct 2026");
  });

  test("paper strategies: rules-based cards from build-up, walls and IV; only Cash · delivery posts a paper trade", async ({ page }) => {
    await fnoData(page);
    const posted: unknown[] = [];
    await page.route("**/api/desk/paper-trades*", (route) => {
      if (route.request().method() !== "POST") return route.fallback();
      const body = route.request().postDataJSON();
      posted.push(body);
      // backend/routes/desk_trading.py: 201 with the stored trade
      return route.fulfill({ status: 201, contentType: "application/json", body: JSON.stringify({ trade: { id: "t-lab-1", status: "open", ...body, opened_at: "2026-10-14T10:00:00+00:00" } }) });
    });
    await page.goto(`${DESK}?tab=fno`);

    // NIFTY (an index): its build-up is the scan's index-futures row, the same source as the stats tile (short build-up).
    await page.getByTestId("desk-fno-view-strategies").click();
    await expect(page.getByTestId("desk-fno-strat-title")).toHaveText("NIFTY · 27 Oct");
    await expect(page.getByTestId("desk-fno-strat-buildup")).toHaveText(LABEL[NIFTY_FUT.label as string]);
    await expect(page.getByTestId("desk-fno-strat-kind")).toHaveText("Rules-based · paper trading only");
    await expect(page.getByTestId("desk-fno-strat-futures-name")).toHaveText("Short futures");
    await expect(page.getByTestId("desk-fno-strat-options-name")).toHaveText("Bear put spread");
    await expect(page.getByTestId("desk-fno-strat-cash-name")).toHaveText("No trade suggested");
    await expect(page.getByTestId("desk-fno-strat-cash-text")).toHaveText("An index has no shares to hold for delivery.");
    await expect(page.getByTestId("desk-fno-strat-why")).toContainText(`${LABEL[NIFTY_FUT.label as string]} on `);
    // BANKNIFTY has no index row in the scan: nothing is named, and the view says why.
    await page.getByTestId("desk-fno-symbol-banknifty").click();
    await expect(page.getByTestId("desk-fno-strat-buildup")).toHaveText("Build-up —");
    for (const k of ["futures", "options", "cash"]) {
      await expect(page.getByTestId(`desk-fno-strat-${k}-name`)).toHaveText("No trade suggested");
      await expect(page.getByTestId(`desk-fno-strat-${k}-add`)).toBeDisabled();
    }
    await expect(page.getByTestId("desk-fno-strat-why")).toContainText("BANKNIFTY is an index: the build-up scan has no index-futures row");
    await page.getByTestId("desk-fno-symbol-nifty").click();

    // The table: every F&O underlying, names from build-up alone (the rule table, restated here).
    const NAMES: Record<string, [string, string, string]> = {
      long_buildup: ["Long futures", "Bull call spread", "Delivery long"],
      short_buildup: ["Short futures", "Bear put spread", "—"],
      short_covering: ["—", "Bull call spread", "—"],
      long_unwinding: ["—", "Bear put spread", "—"],
      neutral: ["—", "Iron condor", "—"],
    };
    const table = page.getByTestId("desk-fno-strat-table");
    await expect(table).toContainText("Paper strategy for every F&O underlying");
    await expect(table.getByRole("columnheader")).toHaveText(["Underlying", "Build-up", "Futures", "Options", "Cash"]);
    await page.getByTestId("desk-fno-strat-all").click();
    const rowSyms = await page.getByTestId("desk-fno-strat-row").evaluateAll((els) => els.map((e) => e.getAttribute("data-symbol")));
    expect(rowSyms).toEqual(["NIFTY", "BANKNIFTY", ...BUILDUP_ROWS.map((r) => r.symbol)]);
    for (const r of BUILDUP_ROWS) {
      const row = page.locator(`[data-testid="desk-fno-strat-row"][data-symbol="${r.symbol}"]`);
      const want = r.label ? NAMES[r.label] : ["—", "—", "—"];
      await expect(row.locator('[data-col="futures"]')).toHaveText(want[0]);
      await expect(row.locator('[data-col="options"]')).toHaveText(want[1]);
      await expect(row.locator('[data-col="cash"]')).toHaveText(want[2]);
    }

    // Load FIXFNO (long build-up) from its row: the three cards are worked out from its chain.
    await page.locator('[data-testid="desk-fno-strat-row"][data-symbol="FIXFNO"]').click();
    await expect(page.getByTestId("desk-fno-strat-title")).toHaveText("FIXFNO · 27 Oct");
    await expect(page.getByTestId("desk-fno-strat-buildup")).toHaveText("Long build-up");
    const S = FIX_CHAIN.summary;
    const put = S.max_put_oi.strike;   // 1,460
    const call = S.max_call_oi.strike; // 1,540
    const settle = FIX_FUTURES.futures[0].settle; // 1,509.60

    // Futures: long, entry at the settle, stop at the put wall, target at the call wall.
    await expect(page.getByTestId("desk-fno-strat-futures-name")).toHaveText("Long futures");
    await expect(page.getByTestId("desk-fno-strat-futures-legs")).toHaveText(`Long 1 lot (${FIX_CHAIN.lot_size}) · FIXFNO 27 Oct FUT @ ${n2(settle)}`);
    await expect(kv(page, "futures", "Entry · settle")).toHaveText(n2(settle));
    await expect(kv(page, "futures", "Stop")).toHaveText(n2(put));
    await expect(kv(page, "futures", "Target")).toHaveText(n2(call));
    await expect(kv(page, "futures", "Reward : risk")).toHaveText(`${((call - settle) / (settle - put)).toFixed(1)} : 1`);
    await expect(page.getByTestId("desk-fno-strat-futures-add")).toBeDisabled();
    await expect(page.getByTestId("desk-fno-strat-futures-note")).toHaveText("Paper trades hold shares only for now, so a futures idea cannot be recorded.");

    // Options: bull call spread, long the ATM call, short the call wall (inside the expected move).
    const atm = S.atm_strike;
    expect(call).toBeLessThanOrEqual(S.spot + S.expected_move);
    const cAtm = FIX_CALL.close[FIX_STRIKES.indexOf(atm)];
    const cWall = FIX_CALL.close[FIX_STRIKES.indexOf(call)];
    const debit = cAtm - cWall;
    await expect(page.getByTestId("desk-fno-strat-options-name")).toHaveText("Bull call spread");
    await expect(page.getByTestId("desk-fno-strat-options-legs")).toHaveText(`Long ${n0(atm)} CE @ ${n2(cAtm)} · 27 OctShort ${n0(call)} CE @ ${n2(cWall)} · 27 Oct`);
    await expect(kv(page, "options", "Net debit")).toHaveText(n2(debit));
    await expect(kv(page, "options", "Max profit")).toHaveText(n2(call - atm - debit));
    await expect(kv(page, "options", "Max loss")).toHaveText(n2(debit));
    await expect(kv(page, "options", "Breakeven")).toHaveText(n2(atm + debit));
    await expect(page.getByTestId("desk-fno-strat-options-add")).toBeDisabled();
    await expect(page.getByTestId("desk-fno-strat-options-note")).toContainText("Paper trades hold shares only for now");

    // Cash · delivery: one lot's worth of shares at the close, stop / target from the walls; it posts.
    await expect(page.getByTestId("desk-fno-strat-cash-name")).toHaveText("Delivery long");
    await expect(kv(page, "cash", "Entry · close")).toHaveText(n2(S.spot));
    await expect(kv(page, "cash", "Quantity")).toHaveText(n0(FIX_CHAIN.lot_size));
    const add = page.getByTestId("desk-fno-strat-cash-add");
    await expect(add).toBeEnabled();
    await expect(page.getByTestId("desk-fno-strat-cash-note")).toHaveText(`Simulated: ${n0(FIX_CHAIN.lot_size)} shares at ₹${n2(S.spot)}, stop ₹${n2(put)}, target ₹${n2(call)}. No order is placed; it is marked against end-of-day closes.`);
    await add.click();
    await expect(page.getByTestId("desk-fno-strat-cash-done")).toContainText(`Paper trade added: ${n0(FIX_CHAIN.lot_size)} FIXFNO at ₹${n2(S.spot)}. No order is placed.`);
    expect(posted).toEqual([{
      symbol: "FIXFNO", quantity: FIX_CHAIN.lot_size, entry_price: S.spot, stop_price: put, target_price: call,
      source: { kind: "fno-lab", bucket: "Cash · delivery · long build-up", signal_date: S.as_of },
    }]);

    // Why these: the build-up figures, the walls and the IV rule, from the payloads.
    const why = page.getByTestId("desk-fno-strat-why");
    const f = BUILDUP_ROWS[0];
    await expect(why).toContainText(`Long build-up on ${dayY(BUILDUP.as_of)}: the future’s price ${signedPct(f.price_chg_pct)}, its open interest ${signedPct(f.oi_chg_pct)} over every expiry.`);
    await expect(why).toContainText(`the most put open interest is at ${n0(put)} (stops for rising ideas) and the most call open interest at ${n0(call)} (targets)`);
    await expect(why).toContainText(`ATM implied volatility ${n2(S.atm_iv)}%: the ATM straddle prices a swing of ±${n2(S.expected_move)}`);
    await expect(page.getByTestId("desk-fno-strat-disclaimer")).toContainText("not a recommendation to buy or sell. 9 out of 10 individual traders in equity F&O incurred net losses (SEBI study). Nivesh cannot place orders.");
  });

  test("paper strategies: a short reading gives a bear put spread and nothing to record; a refused post keeps the server's words", async ({ page }) => {
    await fnoData(page);
    await stockFno(page, "FIXSHORT");
    await page.route("**/api/desk/paper-trades*", (route) => (route.request().method() === "POST"
      ? route.fulfill({ status: 409, contentType: "application/json", body: JSON.stringify({ detail: "open_trade_limit" }) })
      : route.fallback()));
    await page.goto(`${DESK}?tab=fno`);
    await page.getByTestId("desk-fno-view-strategies").click();
    await page.getByTestId("desk-fno-strat-all").click();
    await page.locator('[data-testid="desk-fno-strat-row"][data-symbol="FIXSHORT"]').click();
    await expect(page.getByTestId("desk-fno-strat-buildup")).toHaveText("Short build-up");
    const S = FIX_CHAIN.summary;
    const settle = FIX_FUTURES.futures[0].settle;
    await expect(page.getByTestId("desk-fno-strat-futures-name")).toHaveText("Short futures");
    await expect(kv(page, "futures", "Stop")).toHaveText(n2(S.max_call_oi.strike));
    await expect(kv(page, "futures", "Target")).toHaveText(n2(S.max_put_oi.strike));
    await expect(kv(page, "futures", "Reward : risk")).toHaveText(`${((settle - S.max_put_oi.strike) / (S.max_call_oi.strike - settle)).toFixed(1)} : 1`);
    // Bear put spread: long the ATM put, short the put wall (inside the expected move).
    const pAtm = FIX_PUT.close[FIX_STRIKES.indexOf(S.atm_strike)];
    const pWall = FIX_PUT.close[FIX_STRIKES.indexOf(S.max_put_oi.strike)];
    await expect(page.getByTestId("desk-fno-strat-options-name")).toHaveText("Bear put spread");
    await expect(kv(page, "options", "Net debit")).toHaveText(n2(pAtm - pWall));
    await expect(kv(page, "options", "Breakeven")).toHaveText(n2(S.atm_strike - (pAtm - pWall)));
    await expect(page.getByTestId("desk-fno-strat-cash-name")).toHaveText("No trade suggested");
    await expect(page.getByTestId("desk-fno-strat-cash-add")).toBeDisabled();
    await expect(page.getByTestId("desk-fno-strat-cash-text")).toHaveText("The rules take delivery only on long build-up (price and open interest both up).");

    // FIXFNO's cash idea against a refusing route: the server's words, nothing claimed as saved.
    await page.locator('[data-testid="desk-fno-strat-row"][data-symbol="FIXFNO"]').click();
    await page.getByTestId("desk-fno-strat-cash-add").click();
    await expect(page.getByTestId("desk-fno-strat-cash-error")).toHaveText("Not added — You have the most open paper trades allowed (100). Close one first. (open_trade_limit)");
    await expect(page.getByTestId("desk-fno-strat-cash-done")).toHaveCount(0);
  });

  test("paper strategies: a neutral reading names an iron condor, held back when the expected move reaches past a wall", async ({ page }) => {
    await fnoData(page);
    await stockFno(page, "FIXFLAT");
    await page.goto(`${DESK}?tab=fno`);
    await page.getByTestId("desk-fno-view-strategies").click();
    await page.getByTestId("desk-fno-strat-all").click();
    await expect(page.locator('[data-testid="desk-fno-strat-row"][data-symbol="FIXFLAT"] [data-col="options"]')).toHaveText("Iron condor");
    await page.locator('[data-testid="desk-fno-strat-row"][data-symbol="FIXFLAT"]').click();
    await expect(page.getByTestId("desk-fno-strat-buildup")).toHaveText("Neutral");
    const S = FIX_CHAIN.summary;
    // 1,540 − 1,502.50 = 37.50 < ±59.10: the call wall sits inside the expected move.
    expect(S.max_call_oi.strike - S.spot).toBeLessThan(S.expected_move);
    await expect(page.getByTestId("desk-fno-strat-options-name")).toHaveText("No trade suggested");
    await expect(page.getByTestId("desk-fno-strat-options-text")).toHaveText(`Neutral build-up, but the expected move (±${n2(S.expected_move)}) reaches past a wall (${n0(S.max_put_oi.strike)} – ${n0(S.max_call_oi.strike)}), so a range idea is not suggested.`);
    await expect(page.getByTestId("desk-fno-strat-futures-name")).toHaveText("No trade suggested");
  });

  test("investor wording: mode pill, plain stat names, the Read first warning and plain build-up text", async ({ page }) => {
    await fnoData(page);
    await page.goto(`${DESK}?tab=fno&persona=investor`);
    await expect(page.getByTestId("desk-fno").locator(".cp-pill", { hasText: "Investor mode" })).toBeVisible();
    await expect(page.getByTestId("desk-fno-pcr")).toHaveText("0.96");
    const labels = await tileLabels(page);
    expect(labels[0]).toBe("Expected volatility");
    expect(labels[1]).toBe("Expected swing");
    expect(labels[7]).toBe("Open bets (OI) change");
    // Same data under the plain names.
    await expect(page.getByTestId("desk-fno-atm-iv")).toHaveText("12.00%");
    const rf = page.getByTestId("desk-fno-read-first");
    await expect(rf).toContainText("Read first");
    await expect(rf).toContainText("9 out of 10 individual traders in equity F&O incurred net losses (SEBI study).");
    await expect(page.getByTestId("desk-buildup-q-long_buildup")).toContainText("Price rose and new bets were opened");
    await expect(page.getByTestId("desk-buildup-table").getByRole("columnheader")).toHaveText(["Stock", "Price", "Open bets (OI)", "Share price", "Agree?", "Activity", "Volume", "PCR", "IV", "Expiry · flags", "Quality", "Build-up"]);
    await page.getByTestId("desk-fno-view-indices").click();
    await expect(page.getByTestId("desk-fno-card-NIFTY-headline")).toHaveText("Most open bets sit between 24,700 and 25,300.");
    await expect(page.getByTestId("desk-fno-card-NIFTY")).toContainText("Expected volatility · swing");
  });
});

test.describe("Smart trading desk — Options & futures lab at 390px", () => {
  test.use({ viewport: { width: 390, height: 844 } });

  test("TC-7 the lab's composition on a phone, with no sideways scroll on any sub-tab", async ({ page }) => {
    await deskBase(page);
    await fnoData(page);
    await page.goto(`${DESK}?tab=fno`);
    await expect(page.getByTestId("desk-buildup-row")).toHaveCount(BUILDUP_ROWS.length);

    // Order on the page: title, spot, underlying row, stats, sub-tabs, the open view.
    const top = async (id: string) => (await page.getByTestId(id).boundingBox())?.y ?? -1;
    const ys = [await top("desk-fno-title"), await top("desk-fno-spot"), await top("desk-fno-symbol-input"), await top("desk-fno-stats"), await top("desk-fno-view-buildup"), await top("desk-buildup-scatter")];
    expect(ys.every((y, i) => y >= 0 && (i === 0 || y > ys[i - 1]))).toBe(true);
    // Two stat tiles a row, and two quadrant cards a row.
    const iv = await page.getByTestId("desk-fno-atm-iv").boundingBox();
    const mv = await page.getByTestId("desk-fno-expected-move").boundingBox();
    expect(Math.abs((iv?.y ?? 0) - (mv?.y ?? 1))).toBeLessThan(2);
    const q1 = await page.getByTestId("desk-buildup-q-long_buildup").boundingBox();
    const q2 = await page.getByTestId("desk-buildup-q-short_buildup").boundingBox();
    const q3 = await page.getByTestId("desk-buildup-q-short_covering").boundingBox();
    expect(Math.abs((q1?.y ?? 0) - (q2?.y ?? 1))).toBeLessThan(2);
    expect((q3?.y ?? 0)).toBeGreaterThan((q1?.y ?? 0) + 10);

    let o = await sideways(page);
    expect(o.doc).toBeLessThanOrEqual(1);
    expect(o.scroll).toBeLessThanOrEqual(1);

    await page.getByTestId("desk-fno-view-indices").click();
    await expect(page.getByTestId("desk-fno-card-BANKNIFTY-pcr")).toHaveText("0.80");
    o = await sideways(page);
    expect(o.doc).toBeLessThanOrEqual(1);
    expect(o.scroll).toBeLessThanOrEqual(1);

    await page.getByTestId("desk-fno-view-chain").click();
    await expect(page.getByTestId("desk-fno-chain-row")).toHaveCount(7);
    // the chain scrolls inside its own box, opened on the strike column
    const strikeBox = await chainRow(page, 25000).locator('[data-col="strike"]').boundingBox();
    expect(strikeBox?.x ?? -1).toBeGreaterThanOrEqual(0);
    expect((strikeBox?.x ?? 0) + (strikeBox?.width ?? 0)).toBeLessThanOrEqual(390);
    o = await sideways(page);
    expect(o.doc).toBeLessThanOrEqual(1);
    expect(o.scroll).toBeLessThanOrEqual(1);

    await page.getByTestId("desk-fno-view-strategies").click();
    await page.locator('[data-testid="desk-fno-strat-row"][data-symbol="FIXFNO"]').click();
    await expect(page.getByTestId("desk-fno-strat-cash-name")).toHaveText("Delivery long");
    // The three cards stack.
    const fc = await page.getByTestId("desk-fno-strat-futures").boundingBox();
    const oc = await page.getByTestId("desk-fno-strat-options").boundingBox();
    expect((oc?.y ?? 0)).toBeGreaterThan((fc?.y ?? 0) + (fc?.height ?? 0) - 1);
    o = await sideways(page);
    expect(o.doc).toBeLessThanOrEqual(1);
    expect(o.scroll).toBeLessThanOrEqual(1);
  });
});

// ─────────────────────────────────────────────────────────────────────────
// Screenshots for the design-fidelity check: taken only when the folder
// playwright-report/fidelity-lab exists (gitignored); its TAG file names the
// set ("before" / "after"). All data on them is the fixtures above (test data).
// ─────────────────────────────────────────────────────────────────────────
const SHOT_DIR = path.join(process.cwd(), "playwright-report", "fidelity-lab");
const SHOT_TAG = process.env.SHOT_TAG ?? (fs.existsSync(path.join(SHOT_DIR, "TAG")) ? fs.readFileSync(path.join(SHOT_DIR, "TAG"), "utf-8").trim() : "shot");

test.describe("Options & futures lab — screenshots", () => {
  test.skip(!fs.existsSync(SHOT_DIR), "create playwright-report/fidelity-lab to capture screenshots");

  for (const size of [{ name: "desktop", width: 1440, height: 900 }, { name: "mobile", width: 390, height: 844 }]) {
    test(`screenshots ${size.name}`, async ({ page }) => {
      await page.setViewportSize({ width: size.width, height: size.height });
      await deskBase(page);
      await fnoData(page);
      await page.goto(`${DESK}?tab=fno`);
      await expect(page.getByTestId("desk-fno-spot")).toBeVisible();
      await page.waitForLoadState("networkidle");
      // The shell scrolls inside its own box, so the viewport grows to the content's height for one full picture.
      const shot = async (name: string) => {
        const h = await page.evaluate(() => {
          const sc = document.querySelector('[data-testid="copilot-scroll"]') as HTMLElement | null;
          if (sc) sc.scrollTop = 0;
          return sc ? sc.scrollHeight + (window.innerHeight - sc.clientHeight) : document.documentElement.scrollHeight;
        });
        await page.setViewportSize({ width: size.width, height: Math.min(Math.max(size.height, h), 6000) });
        await page.waitForTimeout(250);
        await page.screenshot({ path: path.join(SHOT_DIR, `fidelity-lab-${SHOT_TAG}-${size.name}${name}.png`) });
        await page.setViewportSize({ width: size.width, height: size.height });
      };
      await shot("");
      for (const v of ["buildup", "indices", "chain", "strategies"]) {
        const tab = page.getByTestId(`desk-fno-view-${v}`);
        if (await tab.count()) {
          await tab.click();
          await page.waitForLoadState("networkidle");
          await page.waitForTimeout(300);
          await shot(`-${v}`);
        }
      }
      // A stock loaded: its strategies, and the build-up with its dot ringed.
      const stockRow = page.locator('[data-testid="desk-fno-strat-row"][data-symbol="FIXFNO"]');
      if (await stockRow.count()) {
        await stockRow.click();
        await page.waitForLoadState("networkidle");
        await shot("-strategies-stock");
        await page.getByTestId("desk-fno-view-buildup").click();
        await page.waitForTimeout(300);
        await shot("-buildup-stock");
      }
      // The investor wording.
      await page.goto(`${DESK}?tab=fno&persona=investor`);
      await expect(page.getByTestId("desk-fno-spot")).toBeVisible();
      await page.waitForLoadState("networkidle");
      await shot("-investor");
    });
  }
});

// ── live near-month futures from Kite (GET /api/live/snapshot?universe=futures) ──────────────────────────────
// MOCK — not real data: invented quotes in the shape backend/routes/live_quotes.py serves for the `futures` set
// (the quote keys are the contract tradingsymbols; each names its underlying, expiry and OI).
const LIVE_FUT = (mode: string, quotes: Record<string, Record<string, unknown>>) => ({
  as_of: "2026-10-23T09:00:10+00:00", data_at: "2026-10-23T09:00:09+00:00", age_seconds: 1.2, stale: mode !== "live", stale_after_seconds: 75, cadence_seconds: 30,
  mode, session: mode === "live" ? "open" : "closed", source: "ws", final: false, count: Object.keys(quotes).length, missing: [], quotes, read_only: true,
});
const FIX_FUT_QUOTE = { ltp: 1512.4, change: 12.4, change_pct: 0.8266, open: 1500, high: 1520, low: 1498, close: 1500, volume: 123456, oi: 5_600_000, oi_high: 5_800_000, oi_low: 5_400_000, instrument: "FUT", underlying: "FIXFNO", expiry: "2026-10-27", ts: "2026-10-23T14:30:00+05:30" };

test.describe("OI build-up — live futures from Kite", () => {
  test.beforeEach(async ({ page }) => { await deskBase(page); });

  test("while the feed is live the table gains Live fut and Live OI for each stock, and a stock Kite sent nothing for shows —", async ({ page }) => {
    await fnoData(page);
    const asked: string[] = [];
    await page.route("**/api/live/snapshot*", (route) => {
      asked.push(new URL(route.request().url()).search);
      return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(LIVE_FUT("live", { FIXFNO26OCTFUT: FIX_FUT_QUOTE })) });
    });
    await page.goto(`${DESK}?tab=fno`);
    await expect(page.getByTestId("desk-buildup-live-head")).toBeVisible();
    const fix = page.locator('[data-testid="desk-buildup-row"]', { hasText: "FIXFNO" }).first();
    await expect(fix.getByTestId("desk-buildup-live-price")).toContainText("1,512.40");
    await expect(fix.getByTestId("desk-buildup-live-chg")).toHaveText("+0.83%");
    await expect(fix.getByTestId("desk-buildup-live-oi")).toContainText("56");          // 5,600,000 contracts, in lakh
    const other = page.locator('[data-testid="desk-buildup-row"]', { hasText: "FIXSHORT" }).first();
    await expect(other.getByTestId("desk-buildup-live-price")).toHaveText("——");
    await expect(page.getByTestId("desk-buildup-shown")).toContainText("not comparable");
    expect(asked.some((s) => s.includes("universe=futures"))).toBe(true);
    // The end-of-day columns are untouched.
    await expect(fix.getByTestId("desk-buildup-oi")).toHaveText("+12.50%");
  });

  for (const mode of ["closed", "delayed", "expired", "not_connected"]) {
    test(`no live columns when the feed is ${mode}: the end-of-day table alone, never stale prices`, async ({ page }) => {
      await fnoData(page);
      await json(page, "**/api/live/snapshot*", LIVE_FUT(mode, { FIXFNO26OCTFUT: FIX_FUT_QUOTE }));
      await page.goto(`${DESK}?tab=fno`);
      await expect(page.getByTestId("desk-buildup-row").first()).toBeVisible();
      await expect(page.getByTestId("desk-buildup-live-head")).toHaveCount(0);
      await expect(page.getByTestId("desk-buildup-live-price")).toHaveCount(0);
    });
  }

  test("a live read that fails leaves the table as it was", async ({ page }) => {
    await fnoData(page);
    await json(page, "**/api/live/snapshot*", { detail: "snapshot_unavailable" }, 503);
    await page.goto(`${DESK}?tab=fno`);
    await expect(page.getByTestId("desk-buildup-row").first()).toBeVisible();
    await expect(page.getByTestId("desk-buildup-live-head")).toHaveCount(0);
    await expect(page.getByTestId("desk-buildup-error")).toHaveCount(0);
  });
});

/**
 * MOCK — not real data: an invented Kite live snapshot (stream and polling) with one quote per symbol given.
 * Shape: backend/routes/live_quotes.py. `mode` is the feed's own word: only "live" shows live prices.
 */
async function liveFeed(page: Page, ltps: Record<string, number>, mode = "live") {
  const quotes = Object.fromEntries(Object.entries(ltps).map(([s, ltp]) => [s, { ltp, change: 1.5, change_pct: 1.5, open: ltp, high: ltp, low: ltp, close: ltp - 1.5, volume: 1000, oi: null, ts: "2026-10-23T11:13:09+05:30" }]));
  const snapshot = {
    as_of: "2026-10-23T05:43:10+00:00", data_at: "2026-10-23T05:43:09+00:00", age_seconds: 1.2, stale: mode !== "live", stale_after_seconds: 75, cadence_seconds: 30,
    mode, session: mode === "live" ? "open" : "closed", source: "ws", final: false, count: Object.keys(quotes).length, missing: [], quotes, read_only: true,
  };
  await page.route("**/api/live/**", (route) => route.fulfill(
    new URL(route.request().url()).pathname.endsWith("/stream")
      ? { status: 200, contentType: "text/event-stream", body: `retry: 100\n\nevent: snapshot\ndata: ${JSON.stringify(snapshot)}\n\n` }
      : { status: 200, contentType: "application/json", body: JSON.stringify(snapshot) }));
}

test.describe("Options & futures lab · live spot", () => {
  test.beforeEach(async ({ page }) => { await deskBase(page); });

  test("the headline spot is Kite's live Nifty 50 while the feed is live, and says the chain figures are the bhavcopy's", async ({ page }) => {
    await fnoData(page);
    await liveFeed(page, { "NIFTY 50": 22700.5 });
    await page.goto(`${DESK}?tab=fno`);
    await expect(page.getByTestId("desk-fno-spot")).toHaveText("22,700.50");
    await expect(page.getByTestId("desk-fno-spot")).toHaveAttribute("data-live", "true");
    await expect(page.getByTestId("desk-fno-live")).toContainText("Live · Kite");
    await expect(page.getByTestId("desk-fno-asof")).toContainText("Chain figures: bhavcopy");
  });

  test("the bhavcopy spot is unchanged when the feed is closed", async ({ page }) => {
    await fnoData(page);
    await liveFeed(page, { "NIFTY 50": 22700.5 }, "closed");
    await page.goto(`${DESK}?tab=fno`);
    await expect(page.getByTestId("desk-fno-spot")).toBeVisible();
    await expect(page.getByTestId("desk-fno-spot")).not.toHaveAttribute("data-live", "true");
    await expect(page.getByTestId("desk-fno-live")).toHaveCount(0);
    await expect(page.getByTestId("desk-fno-asof")).toContainText("end of day");
  });
});

/**
 * MOCK — not real data: the feed's final snapshot after a close (mode "closed", final true), invented prices, every quote
 * stamped with the trading `day`. A day far in the future stands for "newer than the end-of-day data on the screen", a day
 * far in the past for "the end-of-day data has caught up". Shape: backend/routes/live_quotes.py.
 */
async function closeFeed(page: Page, quotes: Record<string, Record<string, unknown>>, day: string) {
  const full = Object.fromEntries(Object.entries(quotes).map(([s, q]) => [s, { change: 1.5, change_pct: 1.5, open: 1, high: 1, low: 1, close: 1, volume: 1000, oi: null, ...q, ts: `${day}T15:29:58+05:30` }]));
  const snapshot = {
    as_of: `${day}T10:01:10+00:00`, data_at: `${day}T10:00:10+00:00`, age_seconds: 5, stale: false, stale_after_seconds: 75, cadence_seconds: 30,
    mode: "closed", session: "closed", source: "rest", final: true, count: Object.keys(full).length, missing: [], quotes: full, read_only: true,
  };
  await page.route("**/api/live/**", (route) => route.fulfill(
    new URL(route.request().url()).pathname.endsWith("/stream")
      ? { status: 200, contentType: "text/event-stream", body: `retry: 100\n\nevent: snapshot\ndata: ${JSON.stringify(snapshot)}\n\n` }
      : { status: 200, contentType: "application/json", body: JSON.stringify(snapshot) }));
}
const NEWER = "2026-12-31";
const OLDER = "2020-01-02";

test.describe("Options & futures lab · Kite's closing quotes", () => {
  test.beforeEach(async ({ page }) => { await deskBase(page); });

  test("after the close the build-up table shows Kite's closing futures quote while the bhavcopy of that day is not loaded", async ({ page }) => {
    await fnoData(page);
    await closeFeed(page, { FIXFNO26OCTFUT: { ...FIX_FUT_QUOTE } }, NEWER);
    await page.goto(`${DESK}?tab=fno`);
    await expect(page.getByTestId("desk-buildup-live-head")).toHaveText("Close fut");
    await expect(page.getByTestId("desk-buildup-live-head")).toHaveAttribute("data-kind", "close");
    const fix = page.locator('[data-testid="desk-buildup-row"]', { hasText: "FIXFNO" }).first();
    await expect(fix.getByTestId("desk-buildup-live-price")).toContainText("1,512.40");
    await expect(page.getByTestId("desk-buildup-shown")).toContainText("at Kite's close");
  });

  test("the closing quote is dropped once the end-of-day data has caught up with its day", async ({ page }) => {
    await fnoData(page);
    await closeFeed(page, { FIXFNO26OCTFUT: { ...FIX_FUT_QUOTE } }, OLDER);
    await page.goto(`${DESK}?tab=fno`);
    await expect(page.getByTestId("desk-buildup-row").first()).toBeVisible();
    await expect(page.getByTestId("desk-buildup-live-head")).toHaveCount(0);
  });

  test("the headline spot shows Kite's close, labelled so, until the bhavcopy of that day is loaded", async ({ page }) => {
    await fnoData(page);
    await closeFeed(page, { "NIFTY 50": { ltp: 22700.5 } }, NEWER);
    await page.goto(`${DESK}?tab=fno`);
    await expect(page.getByTestId("desk-fno-spot")).toHaveText("22,700.50");
    await expect(page.getByTestId("desk-fno-spot")).toHaveAttribute("data-kind", "close");
    await expect(page.getByTestId("desk-fno-live")).toContainText("Close ·");
    await expect(page.getByTestId("desk-fno-live")).not.toContainText("Live");
  });

  test("a closing quote older than the bhavcopy leaves the bhavcopy spot", async ({ page }) => {
    await fnoData(page);
    await closeFeed(page, { "NIFTY 50": { ltp: 22700.5 } }, OLDER);
    await page.goto(`${DESK}?tab=fno`);
    await expect(page.getByTestId("desk-fno-spot")).toBeVisible();
    await expect(page.getByTestId("desk-fno-live")).toHaveCount(0);
  });
});
