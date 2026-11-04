/**
 * Market Desk › Market Recovery (owner, 3 Nov 2026; docs/market_recovery/DESIGN.md test cases TC-E1..TC-E6).
 *
 * Every /api/* call is answered by route mocks. The answer below is MOCK — not real data: invented numbers, dates, symbols
 * (FIX*) and neutral sentences in the shape of GET /api/market-recovery, so what these cases check is the SCREEN (where each
 * figure goes, what opens, what each failure says), never a market reading. The real answer is checked against the warehouse
 * in the backend's own tests and the staging report.
 *
 * TC-E5 is the page's wording lint. The desk-wide lint (copilot-app-compliance-wording.spec.ts) bans trading-call words on
 * every desk place; on THIS view the owner chose the standard plan words (3 Nov, AskUserQuestion: "Entry zone · Stop loss ·
 * Target 1 / Target 2"), so the lint here removes exactly those four labels and nothing else, then expects no banned word.
 */
import { test, expect, type Page, type Route } from "@playwright/test";
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";
import { mockApi, mockSingleRoute } from "../helpers/api-mock";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const load = (name: string) => JSON.parse(fs.readFileSync(path.join(__dirname, "..", "fixtures", name), "utf-8"));

const DESK = "/v5/app/trader/desk";
const MARKET = `${DESK}?tab=market`;
const RECOVERY = `${DESK}?tab=market&view=recovery`;
const SLOW = { timeout: 15_000 };
const reply = (route: Route, body: unknown, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
const params = (page: Page) => new URL(page.url()).searchParams;

// ── MOCK — not real data ─────────────────────────────────────────────────────────────────────────────────────────────

const AS_OF = "2026-10-30";
const series = Array.from({ length: 30 }, (_, i) => {
  const d = new Date(Date.UTC(2026, 8, 18) + i * 86_400_000).toISOString().slice(0, 10);
  return { date: d, above20_pct: 30 + i * 1.2, above50_pct: 38 + i * 0.6, advancers_pct: 45 + (i % 5) * 3, nifty_close: 24_800 + i * 30 };
});
const part = (label: string, points: number, max: number, value: string, ok: boolean | null = points > 0) => ({ label, points, max, value, ok });
const components = (k: number) => [
  { key: "relative_strength", label: "Relative strength", points: 20 * k, max: 25, rescaled: false,
    parts: [part("vs Nifty 500, 20 sessions", 10 * k, 12.5, "+8.0 pp"), part("vs own sector, 20 sessions", 10 * k, 12.5, "+6.0 pp")] },
  { key: "technical", label: "Technical recovery", points: 20 * k, max: 25, rescaled: false,
    parts: [part("Close above 20-day EMA", 5, 5, "+3.1%"), part("Close above 50-day EMA", 5, 5, "+6.0%"), part("EMA gap widening", 5, 5, "+0.4 pp"),
      part("RSI 14 in 50–70", 5 * k, 5, "61.2"), part("Higher lows", 0, 5, "no", false)] },
  { key: "volume_delivery", label: "Volume and delivery", points: 15 * k, max: 20, rescaled: false,
    parts: [part("Volume ratio 5D / 50D", 7, 7, "1.6×"), part("Up-day vs down-day volume", 6 * k, 6, "1.4×"), part("Delivery 5D vs 20D", 2, 7, "1.03×")] },
  { key: "fundamental", label: "Fundamental quality", points: 16 * k, max: 20, rescaled: true,
    parts: [part("ROCE", 5, 5, "24%"), part("Debt to equity", 5, 5, "0.1"), part("PAT growth", 5 * k, 5, "+14%"), part("CFO / PAT", 0, 5, "—", null)] },
  { key: "smart_money", label: "Smart money", points: 6 * k, max: 10, rescaled: false,
    parts: [part("FII stake change", 2, 4, "+0.5 pp"), part("Accumulation score", 2 * k, 3, "66"), part("Up days on high volume", 2, 3, "2 of 5")] },
];
const accel = [
  { key: "rs", label: "Relative strength vs Nifty 500 (20D)", unit: "pp", then: -3.0, now: 2.0, improving: true },
  { key: "rsi", label: "RSI 14", unit: "rsi", then: 39, now: 54, improving: true },
  { key: "ema20", label: "Distance from the 20-day EMA", unit: "pct", then: -7.0, now: 1.0, improving: true },
  { key: "volume", label: "Volume ratio", unit: "ratio", then: 0.7, now: 1.8, improving: true },
  { key: "delivery", label: "Delivery trend", unit: "pp", then: -0.4, now: 0.6, improving: true },
  { key: "sector", label: "Sector relative strength (20D)", unit: "pp", then: 1.0, now: 0.5, improving: false },
];
const candidate = (rank: number, symbol: string, sector: string, score: number, k: number, plan: boolean) => ({
  rank, symbol, name: `${symbol} Ltd`, sector, sector_rank: rank, sector_state: "leadership", close: 1000 + rank * 10,
  score, meets_priority: score >= 75,
  components: components(k),
  acceleration: { score: 78 - rank, improving: 5, of: 6, rows: accel },
  setup: { key: rank === 1 ? "breakout" : "pullback", label: rank === 1 ? "Early breakout" : "Pullback in an uptrend", why: "Closed above its 20-session high on 1.8× its usual volume." },
  plan: plan ? { entry_low: 990.5, entry_high: 1010, stop_loss: 951.25, target_1: 1105, target_2: 1186.25, rr_1: 1.6, rr_2: 3.0, risk_pct: 5.8,
    basis: "recovery-plan-v1 (MOCK basis text)" } : null,
  metrics: { rs_vs_index_20d: 8, rs_vs_sector_20d: 6, rsi14: 61.2, volume_ratio: 1.6, pct_vs_ema20: 3.1, deliv_5d: 52, deliv_20d: 47, atr14: 25,
    traded_value_cr_20d: 210, market_cap_cr: 112_000, roce: 24, roe: 19, de: 0.1, pat_growth: 14, cfo_pat: null, fii_change_qoq: 0.5 },
  reasons: ["Outperformed Nifty 500 by 8.0 pp over 20 sessions", "Sector ranked in the top five"],
  cautions: ["Results due in 6 days"],
  gaps: ["Cash flow (CFO/PAT) not available"],
});
const SECTOR_NAMES = ["Capital Goods", "Realty", "Financial Services", "Healthcare", "Automobile and Auto Components", "Information Technology"];
const ANSWER = {
  method: "recovery-radar-v1",
  as_of: AS_OF,
  computed_at: "2026-10-30T13:40:02Z",
  universe: { name: "Nifty 500", members: 501, members_as_of: "2026-10-28", scored: 470, left_out: { no_bar: 8, liquidity: 12, market_cap: 3, history: 2 } },
  regime: {
    status: "underway", label: "Recovery under way", line: "MOCK line: the index is above its 20-day average and breadth widened over 5 sessions.",
    passed: 4, total: 5,
    checks: [
      { id: "nifty_above_20dma", label: "Nifty 50 above its 20-day average", importance: "high", pass: true, value: "25,812 vs 25,410 (+1.6%)" },
      { id: "nifty_20dma_rising", label: "Nifty 50 20-day average rising", importance: "high", pass: true, value: "25,410 vs 25,301" },
      { id: "advancers_60", label: "60% or more of Nifty 500 advanced", importance: "high", pass: false, value: "54%" },
      { id: "breadth_expanding", label: "More Nifty 500 stocks above their 20-day average", importance: "very_high", pass: true, value: "64% vs 48%" },
      { id: "vix_falling", label: "India VIX falling", importance: "medium", pass: true, value: "12.1 vs 13.4" },
    ],
    nifty: { index: "Nifty 50", close: 25_812.4, sma20: 25_410.2, sma20_5ago: 25_301, pct_vs_sma20: 1.58 },
    breadth: { counted: 493, advancers_pct: 54, advancers_pct_5d_avg: 56, above20_pct: 64.2, above20_pct_5ago: 48.3, above50_pct: 51, above50_pct_5ago: 44.9 },
    vix: { close: 12.1, close_5ago: 13.4, change_pct: -9.7 },
    caps: [
      { key: "large", label: "Nifty 100", members: 100, above20_pct: 70, above20_pct_5ago: 52, above50_pct: 58 },
      { key: "mid", label: "Nifty Midcap 150", members: 150, above20_pct: 63, above20_pct_5ago: 47, above50_pct: 50 },
      { key: "small", label: "Nifty Smallcap 250", members: 250, above20_pct: 58, above20_pct_5ago: 44, above50_pct: 47 },
    ],
  },
  breadth_series: series,
  sectors: SECTOR_NAMES.map((s, i) => ({
    sector: s, members: 30 - i, ret_5d: 3 - i, ret_10d: 5 - i, ret_20d: 8 - i * 2, rs_5d: 1.2 - i * 0.5, rs_10d: 2 - i * 0.6, rs_20d: 3.4 - i * 1.4,
    rs_20d_5ago: 1.1 - i, rs_change: 2.3 - i * 0.4, above20_pct: 78 - i * 8, above50_pct: 66 - i * 7, delivery_up_pct: 55 - i * 4,
    state: ["leadership", "leadership", "recovery", "emerging", "neutral", "weak"][i], state_label: ["Leadership", "Leadership", "Recovery", "Emerging", "Neutral", "Weak — avoid for now"][i],
    rank: i + 1, leader: i < 5,
  })),
  leaders: SECTOR_NAMES.slice(0, 5),
  candidates: [candidate(1, "FIXA", "Capital Goods", 86.4, 1, true), candidate(2, "FIXB", "Realty", 71.0, 0.8, true)],
  others: [candidate(1, "FIXC", "Information Technology", 68.2, 0.7, false)],
  excluded: [
    { symbol: "FIXD", name: "FIXD Ltd", sector: "Realty", score: 81, trap: "dead_cat", label: "Dead-cat bounce", reason: "Up 6.2% in 5 sessions but below a falling 50-day and its 200-day average." },
    { symbol: "FIXE", name: "FIXE Ltd", sector: "Capital Goods", score: 79, trap: "short_covering", label: "Short covering", reason: "Futures price up 2.1% while open interest fell 6.0%." },
  ],
  thresholds: { priority_score: 75, min_traded_value_cr: 5, min_market_cap_cr: 1000 },
  sources: [
    { what: "Daily prices", source: "NSE end-of-day bars (split/bonus adjusted), NIDP warehouse", as_of: AS_OF },
    { what: "Index levels", source: "NSE index closes, NIDP warehouse", as_of: AS_OF },
  ],
  notes: ["MOCK note: weights are the proposal's; thresholds untuned."],
  warnings: ["MOCK warning: delivery data is one session behind prices."],
};

// ── strategies with protection (DESIGN §8) — MOCK — not real data ──────────────────────────────────────────────────

const LOT = 500;
const grid = (c: number) => Array.from({ length: 41 }, (_, i) => Math.round((c * (0.7 + (0.6 * i) / 40)) * 100) / 100);
const payoff = (f: (s: number) => number) => grid(1010).map((s) => [s, Math.round(f(s) * 100) / 100]);
const putV = (k: number, s: number) => Math.max(k - s, 0);
const callV = (k: number, s: number) => Math.max(s - k, 0);
const leg = (action: string, instrument: string, strike: number | null, lots: number, price: number, flags: string[] = [], basis = "close") => ({
  action, instrument, strike, lots, units: lots * LOT, price, price_basis: basis, oi: instrument === "Shares" ? null : 120_000,
  volume: instrument === "Shares" ? null : 300, flags,
});
const chk = (id: string, label: string, pass: boolean | null, detail: string | null = null) => ({ id, label, pass, detail });
const scen = (pp: (s: number) => number, shares: boolean) => [["At the Stop loss", 951.25], ["Unchanged at the close", 1010], ["At Target 1", 1105], ["At Target 2", 1186.25]]
  .map(([label, px]) => ({ label, price: px, pnl: Math.round(pp(px as number) * 100) / 100, ...(shares ? { pnl_unhedged: ((px as number) - 1010) * LOT } : {}) }));
const ppF = (s: number) => (s - 1010) * LOT + (putV(1000, s) - 22.5) * LOT;
const bcsF = (s: number) => (callV(1010, s) - 30 - callV(1100, s) + 8) * LOT;
const colF = (s: number) => (s - 1010) * LOT + (putV(950, s) - 6) * LOT - (callV(1100, s) - 8) * LOT;
const bpsF = (s: number) => (14 - putV(990, s) + putV(950, s) - 6) * LOT;
const OPTIONS_ANSWER = (symbol: string) => ({
  symbol, kind: "options", as_of: AS_OF, expiry: "2026-11-24", days_to_expiry: 25, lot_size: LOT, spot: 1010,
  plan: { entry_low: 990.5, close: 1010, stop_loss: 951.25, target_1: 1105, target_2: 1186.25 },
  strategies: [
    { key: "protective_put", label: "Protective Put", best_when: "MOCK: bullish, but concerned about a market correction.", status: "passes", why: null,
      legs: [leg("Buy", "Shares", null, 1, 1010), leg("Buy", "Put", 1000, 1, 22.5)],
      net_premium: -11_250, net_premium_per_share: -22.5, outlay: -516_250, max_profit: null, profit_unbounded: true, max_loss: -16_250,
      max_loss_with_costs: -16_900, breakevens: [1032.5], reward_risk: 2.9, costs_round_trip: 640, scenarios: scen(ppF, true),
      checks: [chk("liquid", "Every option leg traded on 30 Oct", true), chk("reward_risk", "Reward : risk at least 1.5", true, "2.9 : 1")], payoff: payoff(ppF) },
    { key: "bull_call_spread", label: "Bull Call Spread", best_when: "MOCK: expecting a moderate rise.", status: "passes", why: null,
      legs: [leg("Buy", "Call", 1010, 1, 30), leg("Sell", "Call", 1100, 1, 8)],
      net_premium: -11_000, net_premium_per_share: -22, outlay: -11_000, max_profit: 34_000, profit_unbounded: false, max_loss: -11_000,
      max_loss_with_costs: -11_420, breakevens: [1032], reward_risk: 3.1, costs_round_trip: 420, scenarios: scen(bcsF, false),
      checks: [chk("liquid", "Every option leg traded on 30 Oct", true), chk("reward_risk", "Reward : risk at least 1.5", true, "3.1 : 1")], payoff: payoff(bcsF) },
    { key: "collar", label: "Collar", best_when: "MOCK: protecting shares at low cost, giving up gains above the call strike.", status: "passes", why: null,
      legs: [leg("Buy", "Shares", null, 1, 1010), leg("Buy", "Put", 950, 1, 6), leg("Sell", "Call", 1100, 1, 8)],
      net_premium: 1000, net_premium_per_share: 2, outlay: -504_000, max_profit: 46_000, profit_unbounded: false, max_loss: -29_000,
      max_loss_with_costs: -29_800, breakevens: [1008], reward_risk: 1.6, costs_round_trip: 800, scenarios: scen(colF, true),
      checks: [chk("liquid", "Every option leg traded on 30 Oct", true), chk("reward_risk", "Reward : risk at least 1.5", true, "1.6 : 1")], payoff: payoff(colF) },
    { key: "bull_put_spread", label: "Bull Put Credit Spread", best_when: "MOCK: moderately bullish or neutral-bullish.", status: "fails",
      why: "Credit at least a third of the strike width: ₹4,000 against a ₹20,000 width (MOCK)",
      legs: [leg("Sell", "Put", 990, 1, 14), leg("Buy", "Put", 950, 1, 6, ["low_oi"], "settlement")],
      net_premium: 4000, net_premium_per_share: 8, outlay: 4000, max_profit: 4000, profit_unbounded: false, max_loss: -16_000,
      max_loss_with_costs: -16_380, breakevens: [982], reward_risk: 0.25, costs_round_trip: 380, scenarios: scen(bpsF, false),
      checks: [chk("liquid", "Every option leg traded on 30 Oct", true), chk("reward_risk", "Reward : risk at least 1.5", false, "0.25 : 1"),
        chk("credit", "Credit at least a third of the strike width", false, "₹4,000 against ₹20,000")], payoff: payoff(bpsF) },
    { key: "put_ratio_backspread", label: "Put Ratio Backspread", best_when: "MOCK: bullish but expecting volatility; a loss zone between the strikes.",
      status: "unavailable", why: "MOCK: no put is listed near the Stop loss below the ATM strike.", legs: [], reward_risk: null,
      checks: [chk("strikes", "The strikes the rule needs are listed", false, "MOCK: no lower put strike"),
        chk("reward_risk", "Reward : risk", null, "Not applied: a volatility hedge, judged by its loss zone between the strikes.")] },
  ],
  index_hedge: null,
  notes: ["MOCK note: one lot each, figures at expiry from end-of-day prices.",
    "MOCK note: exchange margin for written options (credit spreads, the collar's call, the backspread) is not estimated here."],
  sources: [{ what: "Option prices", source: "NSE F&O bhavcopy, NIDP warehouse", as_of: AS_OF }],
  warnings: [],
});
const HEDGE_ANSWER = (symbol: string) => ({
  symbol, kind: "index_hedge", as_of: AS_OF, expiry: "2026-11-24", days_to_expiry: 25, lot_size: null, spot: null,
  plan: { entry_low: 990.5, close: 1010, stop_loss: 951.25, target_1: 1105, target_2: 1186.25 },
  strategies: [],
  index_hedge: {
    index: "NIFTY", expiry: "2026-11-24", days_to_expiry: 25, lot_size: 65, spot: 25_812.4, beta: 1.12, put_strike: 24_900, premium: 110.5,
    price_basis: "close", oi: 82_000, volume: 5_400, cost_per_lot: 7_182.5, hedged_value: 1_498_058, cost_pct: 0.48, fall_used_pct: 4.2,
    scenarios: [{ label: "Nifty -5%", nifty_move_pct: -5, put_pnl: 3_300, stock_loss: -83_900 }, { label: "Nifty -10%", nifty_move_pct: -10, put_pnl: 87_200, stock_loss: -167_800 },
      { label: "Nifty -15%", nifty_move_pct: -15, put_pnl: 171_100, stock_loss: -251_700 }],
    checks: [chk("liquid", "The put traded with open interest of at least 500", true, "open interest 82,000, volume 5,400")],
    caveat: `MOCK caveat: a Nifty put protects against a market-wide fall only. A fall in ${symbol} alone is not covered.`,
    status: "passes", why: null, sizing: "MOCK sizing: one Nifty lot hedges about ₹14,98,058 of this stock at a beta of 1.12.",
  },
  notes: ["MOCK note: one lot, end-of-day prices."],
  sources: [{ what: "Nifty option prices", source: "NSE F&O bhavcopy, NIDP warehouse", as_of: AS_OF }],
  warnings: [],
});

// MOCK — not real data: GET /api/market-recovery/indices (§9). Invented index levels, expiries, open interest and premiums; the
// sentences are neutral placeholders in the server's shape. Four Nifty expiries (two weeklies, a monthly, a too-thin weekly) so
// the per-expiry table and the setups grouped by expiry are exercised; Bank Nifty has one monthly.
const ixOi = (pairs: Array<[number, number]>) => pairs.map(([strike, v]) => ({ strike, oi: v }));
const ixChg = (pairs: Array<[number, number]>) => pairs.map(([strike, v]) => ({ strike, change: v }));
const ixLeg = (action: string, instrument: string, strike: number, px: number, extra: Record<string, unknown> = {}) =>
  ({ action, instrument, strike, lots: 1, price: px, price_basis: "close", oi: 500000, volume: 90000, flags: [], ...extra });
const ixOk = (id: string, label: string, detail: string) => ({ id, label, pass: true, detail });
const ixExpiry = (e: string, days: number, kind: string, liquidity: string, pcr: number, maxPain: number, lo: number, hi: number, read: string) => ({
  expiry: e, days, kind, liquidity, volume: liquidity === "too_thin" ? 20000 : liquidity === "thin" ? 600000 : 12000000,
  pcr, call_oi: 80000000, put_oi: Math.round(80000000 * pcr), max_pain: maxPain, atm: 24850, atm_call: 160.5, atm_put: 150.25,
  straddle: (hi - lo) / 2, move_pct: ((hi - lo) / 2 / 24850.5) * 100, range_lo: lo, range_hi: hi, call_wall: 25000, put_wall: 24600,
  call_oi_top: ixOi([[25000, 5500000], [25500, 4100000], [26000, 3900000]]), put_oi_top: ixOi([[24600, 6100000], [24000, 5200000], [23500, 4000000]]),
  call_adds: ixChg([[25500, 1900000], [25200, 1500000], [25000, 1200000]]), put_adds: ixChg([[24600, 2800000], [24700, 2100000], [24500, 1700000]]),
  call_cuts: ixChg([[24500, -400000]]), put_cuts: ixChg([[24000, -120000]]), read,
});
const NIFTY_BLOCK = {
  symbol: "NIFTY", name: "Nifty 50", close: 24850.5, change: 210.25, change_pct: 0.85, open: 24700, high: 24880, low: 24650.75,
  up_streak: 3, ret_5d: 2.1, ret_20d: 3.4,
  technicals: {
    ema20: 24400.1, ema50: 24300.2, ema200: 24950.3, vs_ema20_pct: 1.84, vs_ema50_pct: 2.26, vs_ema200_pct: -0.4, rsi14: 61.2, rsi14_5ago: 48.9,
    macd: 40.5, macd_signal: -12.3, macd_hist: 52.8, macd_hist_prev: 31.0, atr14: 280.4, atr_pct: 1.13, high20: 24880, low20: 23900,
    high52: 26100, low52: 23100, from_high52_pct: -4.79, from_low52_pct: 7.58, sessions: 640,
  },
  pivots: { p: 24793.75, r1: 24937.5, r2: 25024.5, r3: 25168.25, s1: 24706.75, s2: 24563, s3: 24476 },
  futures: [
    { expiry: "2026-11-24", close: 24880, change_pct: 0.9, oi: 13000000, oi_change: -900000, oi_change_pct: -6.5, basis: 29.5, buildup: "short_covering" },
    { expiry: "2026-12-29", close: 25010, change_pct: 0.88, oi: 1200000, oi_change: 40000, oi_change_pct: 3.4, basis: 159.5, buildup: "long_buildup" },
  ],
  levels: {
    above: [{ level: 24937.5, label: "Floor pivot R1" }, { level: 24950.3, label: "200-day average (EMA)" }, { level: 25000, label: "Call wall, 3 Nov" }],
    below: [{ level: 24793.75, label: "Floor pivot" }, { level: 24600, label: "Put wall, 3 Nov" }, { level: 24400.1, label: "20-day average (EMA)" }],
  },
  expiries: [
    ixExpiry("2026-11-03", 4, "weekly", "active", 1.21, 24700, 24540, 25161, "Fresh put writing at 24,600–24,700 under the close; the largest call open interest is at 25,000."),
    ixExpiry("2026-11-10", 11, "weekly", "thin", 1.05, 24800, 24410, 25291, "Thin series: the at-the-money put traded about 90 contracts."),
    ixExpiry("2026-11-24", 25, "monthly", "active", 1.34, 24500, 24228, 25473, "The heaviest put open interest sits at 24,600; calls at 24,500 are being closed."),
    ixExpiry("2026-12-01", 32, "weekly", "too_thin", 1.18, 24600, 24100, 25601, "Too little open interest to read."),
  ],
  setups: [
    { expiry: "2026-11-03", kind: "weekly", key: "bull_call_spread", label: "Bull Call Spread", when: "If it rises toward 25,000", lot_size: 65,
      legs: [ixLeg("Buy", "Call", 24850, 160.5), ixLeg("Sell", "Call", 25000, 95.25)], net_premium: -4241.25, max_gain: 5508.75, max_loss: -4241.25,
      reward_risk: 1.3, breakevens: [24915.25], status: "fails", why: "Reward : risk at least 1.5: 1.30 : 1",
      checks: [ixOk("liquid", "Every leg traded on 30 Oct", "Each leg has a premium, open interest and trades."),
               { id: "reward_risk", label: "Reward : risk at least 1.5", pass: false, detail: "1.30 : 1" }] },
    { expiry: "2026-11-03", kind: "weekly", key: "bear_put_spread", label: "Bear Put Spread", when: "If it breaks below 24,600", lot_size: 65,
      legs: [ixLeg("Buy", "Put", 24850, 150.25), ixLeg("Sell", "Put", 24600, 70.5)], net_premium: -5183.75, max_gain: 11066.25, max_loss: -5183.75,
      reward_risk: 2.13, breakevens: [24770.25], status: "passes", why: null,
      checks: [ixOk("liquid", "Every leg traded on 30 Oct", "Each leg has a premium, open interest and trades."),
               ixOk("reward_risk", "Reward : risk at least 1.5", "2.13 : 1")] },
    { expiry: "2026-11-10", kind: "weekly", key: "iron_condor", label: "Iron Condor", when: "If it stays 24,600–25,000", lot_size: 65,
      legs: [ixLeg("Sell", "Put", 24600, 98.0), ixLeg("Buy", "Put", 24350, 52.0), ixLeg("Sell", "Call", 25000, 120.0), ixLeg("Buy", "Call", 25250, 61.5)],
      net_premium: 6727.5, max_gain: 6727.5, max_loss: -9522.5, reward_risk: 0.71, breakevens: [24496.5, 25103.5], status: "passes", why: null,
      checks: [ixOk("liquid", "Every leg traded on 30 Oct", "thin series: use limit orders"),
               ixOk("credit", "Credit at least a third of the wider wing", "credit ₹6,728 vs wing ₹16,250")] },
    { expiry: "2026-11-24", kind: "monthly", key: "hedge_put_spread", label: "Hedge Put Spread", when: "To protect long stocks", lot_size: 65,
      legs: [ixLeg("Buy", "Put", 24600, 210.0), ixLeg("Sell", "Put", 24250, 120.75)], net_premium: -5801.25, max_gain: 16948.75, max_loss: -5801.25,
      reward_risk: null, breakevens: [24510.75], status: "passes", why: null,
      checks: [ixOk("liquid", "Every leg traded on 30 Oct", "Each leg has a premium, open interest and trades.")] },
  ],
  read: [
    "Nifty 50 closed +0.85% at 24,850.50, up 3 sessions in a row.",
    "The close is 0.4% under the 200-day average (24,950.30).",
    "Near-month futures: short covering (price +0.90%, open interest −6.5%).",
  ],
};
const BANK_BLOCK = {
  symbol: "BANKNIFTY", name: "Bank Nifty", close: 56120.4, change: -80.6, change_pct: -0.14, open: 56300, high: 56410.2, low: 55980,
  up_streak: 0, ret_5d: 0.9, ret_20d: -1.2,
  technicals: { ema20: 55900.5, ema50: 56200.1, ema200: 56900.9, vs_ema20_pct: 0.39, vs_ema50_pct: -0.14, vs_ema200_pct: -1.37, rsi14: 51.4, rsi14_5ago: 44.0,
    macd: -120.2, macd_signal: -180.4, macd_hist: 60.2, macd_hist_prev: 72.9, atr14: 700.1, atr_pct: 1.25, high20: 56800, low20: 54900,
    high52: 61000, low52: 50100, from_high52_pct: -8.0, from_low52_pct: 12.02, sessions: 640 },
  pivots: { p: 56170.2, r1: 56360.4, r2: 56600.6, r3: 56790.8, s1: 55930, s2: 55740, s3: 55500 },
  futures: [{ expiry: "2026-11-24", close: 56190, change_pct: -0.12, oi: 2100000, oi_change: 30000, oi_change_pct: 1.4, basis: 69.6, buildup: "short_buildup" }],
  levels: { above: [{ level: 56200.1, label: "50-day average (EMA)" }], below: [{ level: 56000, label: "Put wall, 24 Nov" }] },
  expiries: [ixExpiry("2026-11-24", 25, "monthly", "active", 0.93, 56300, 54700, 57540, "Calls are stacked at 57,000; the put wall is 56,000.")],
  setups: [
    { expiry: "2026-11-24", kind: "monthly", key: "bull_call_spread", label: "Bull Call Spread", when: "If it rises toward 57,000", lot_size: 30,
      legs: [ixLeg("Buy", "Call", 56100, 780.0), ixLeg("Sell", "Call", 57000, 410.5)], net_premium: -11085, max_gain: 15915, max_loss: -11085,
      reward_risk: 1.44, breakevens: [56469.5], status: "fails", why: "Reward : risk at least 1.5: 1.44 : 1",
      checks: [{ id: "reward_risk", label: "Reward : risk at least 1.5", pass: false, detail: "1.44 : 1" }] },
  ],
  read: ["Bank Nifty closed −0.14% at 56,120.40 and is under its 50- and 200-day averages."],
};
const INDICES_ANSWER = {
  as_of: AS_OF, indices: [NIFTY_BLOCK, BANK_BLOCK],
  vix: { close: 14.2, change_pct: -2.1, close_5ago: 15.0, change_5d_pct: -5.33, up_streak: 0 },
  relative: { bank_minus_nifty_1d: -0.99, bank_minus_nifty_5d: -1.2, bank_minus_nifty_20d: -4.6 },
  flows: { as_of: AS_OF, fii_5d: 9800.5, fii_buy_days_5: 4, days: [
    { date: "2026-10-30", fii: 3120.4, dii: -1250.2 }, { date: "2026-10-29", fii: -820.1, dii: 1900.5 }, { date: "2026-10-28", fii: 2900.0, dii: -300.0 },
    { date: "2026-10-27", fii: 2400.2, dii: 150.0 }, { date: "2026-10-26", fii: 2200.0, dii: -410.4 } ] },
  together: [
    "24,600 is the common floor: put writers added there in 3 expiries.",
    "The 3 Nov call wall at 25,000 is the near ceiling.",
    "The 24 Nov max pain (24,500) sits under the close.",
  ],
  notes: ["Open interest is in units (shares), not contracts.", "Setups are rule-based and not back-tested; for research, not advice."],
  sources: [{ what: "Index closes", source: "NSE index closes, NIDP warehouse", as_of: AS_OF },
            { what: "Option chains and futures", source: "NSE F&O bhavcopy via /api/fno", as_of: AS_OF }],
  warnings: [],
};

// ── the desk with the flag and the route under test ─────────────────────────────────────────────────────────────────

interface Backend { calls: number; strategies: string[]; indices: number }

async function desk(page: Page, o: {
  flag?: boolean; answer?: () => { status: number; body: unknown }; strategies?: (symbol: string) => { status: number; body: unknown };
  indices?: () => { status: number; body: unknown };
} = {}): Promise<Backend> {
  const be: Backend = { calls: 0, strategies: [], indices: 0 };
  await mockApi(page, "populated");
  await mockSingleRoute(page, "**/api/markets/home", "markets-home.json");
  await page.route("**/api/chat/sessions", (r) => reply(r, []));
  await page.route("**/api/move-odds/**", (r) => reply(r, { detail: "feature_not_enabled" }, 403));
  const base = load("user-profile-onboarded.json");
  await page.route("**/api/auth/me", (r) => reply(r, { ...base, features: { ...(base.features ?? {}), market_recovery: o.flag !== false } }));
  await page.route("**/api/market-recovery", (r) => {
    be.calls += 1;
    const a = o.answer ? o.answer() : { status: 200, body: ANSWER };
    return reply(r, a.body, a.status);
  });
  // A stock's strategies (§8): FIXC has no stock options (index hedge); every other stock gets the five strategies.
  await page.route("**/api/market-recovery/strategies/*", (r) => {
    const symbol = decodeURIComponent(new URL(r.request().url()).pathname.split("/").pop() ?? "");
    be.strategies.push(symbol);
    const a = o.strategies ? o.strategies(symbol) : { status: 200, body: symbol === "FIXC" ? HEDGE_ANSWER(symbol) : OPTIONS_ANSWER(symbol) };
    return reply(r, a.body, a.status);
  });
  // Part 2 (§9): Nifty and Bank Nifty by expiry, its own read.
  await page.route("**/api/market-recovery/indices", (r) => {
    be.indices += 1;
    const a = o.indices ? o.indices() : { status: 200, body: INDICES_ANSWER };
    return reply(r, a.body, a.status);
  });
  return be;
}

async function openRecovery(page: Page) {
  await page.goto(RECOVERY);
  await expect(page.getByTestId("mr-ready")).toBeVisible(SLOW);
}

const price = (v: number) => v.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

// The desk-wide banned words (copilot-app-compliance-wording.spec.ts LINT), and the page's only exception.
const LINT = new RegExp(
  "\\b(buy|buys|buying|bought|sell|sells|selling|sold|stop[- ]?loss(?:es)?|sl|stops?|targets?|t1|t2|entry|entries|exit|exits|" +
    "exited|book(?:ing)?\\s+profits?|profit[- ]booking|accumulate|trim|upside|downside|recommend\\w*|picks?|price\\s+targets?|" +
    "suggested\\s+(?:trade|trades|strateg(?:y|ies)))\\b",
  "gi",
);
const ALLOW = [
  /\bexit\s+load\b/gi, /\b(?:long|short)\s+build[- ]?ups?\b/gi, /\bstop\s+(?:the\s+answer|generating)\b/gi, /\b(?:you\s+)?stopped\s+this\s+answer\b/gi,
  /\bupdates\s+stopped\b/gi,
];
/** The owner's plan words for this page (3 Nov) — exactly these four labels, nothing broader. Case-insensitive only because the
 *  table headers are upper-cased by CSS ("ENTRY ZONE" in innerText). */
const PLAN_LABELS = [/\bEntry zone\b/gi, /\bStop loss\b/gi, /\bTarget 1\b/gi, /\bTarget 2\b/gi];
/** The owner's leg verbs for this page (4 Nov): "Buy" / "Sell" only as a strategy leg, which always reads "<Buy|Sell> <n> lot(s)".
 *  Case-sensitive and anchored to the lot count, so "buy now", "Sell above 1010" or "Buy" in a sentence still fail. */
const LEG_VERBS = /\b(?:Buy|Sell)\b(?= \d+ lots?\b)/g;
function hits(text: string): string[] {
  let t = text;
  for (const a of [...ALLOW, ...PLAN_LABELS, LEG_VERBS]) t = t.replace(a, " ");
  return [...t.matchAll(LINT)].map((m) => m[0]);
}

test.describe("MOCK — not real data: Market Desk › Market Recovery", () => {
  test("TC-E1 with the flag on the switcher offers Market Recovery last; the view shows the check, breadth, sectors and candidates", async ({ page }) => {
    const be = await desk(page);
    await page.goto(MARKET);
    await expect(page.getByTestId("desk-views")).toBeVisible(SLOW);
    await expect(page.getByTestId("desk-views").getByRole("button")).toHaveText(
      ["Market Intelligence", "Smart Money", "Sector Rotation", "Stock Research", "Screener", "Market Recovery"]);
    expect(be.calls).toBe(0);                                                  // nothing is asked until the view opens
    await page.getByTestId("desk-view-recovery").click();
    await expect.poll(() => params(page).get("view")).toBe("recovery");
    await expect(page.getByTestId("desk-view-recovery")).toHaveAttribute("aria-pressed", "true");
    await expect(page.getByTestId("md-eyebrow")).toHaveText("Market Desk · Market Recovery");
    await expect(page.getByTestId("md-line")).not.toBeEmpty();
    await expect(page.getByTestId("mr-ready")).toBeVisible(SLOW);
    await expect(page.getByTestId("mr-ready")).toHaveAttribute("data-as-of", AS_OF);
    await expect(page.getByTestId("mr-asof")).toContainText("470 of 501 Nifty 500 stocks scored");
    await expect(page.getByTestId("mr-left-out")).toContainText("12 below ₹5 cr average traded value");
    await expect(page.getByTestId("mr-warnings")).toContainText("delivery data is one session behind");

    // 1. the recovery check
    await expect(page.getByTestId("mr-regime-status")).toHaveAttribute("data-status", "underway");
    await expect(page.getByTestId("mr-regime-status")).toContainText("Recovery under way");
    await expect(page.getByTestId("mr-regime-passed")).toHaveText("4 of 5 checks pass");
    await expect(page.getByTestId("mr-check")).toHaveCount(5);
    await expect(page.locator('[data-testid="mr-check"][data-pass="false"]')).toHaveAttribute("data-check", "advancers_60");
    await expect(page.locator('[data-testid="mr-check"][data-check="breadth_expanding"]')).toContainText("64% vs 48%");
    await expect(page.getByTestId("mr-figures")).toContainText("25,812.40");
    await expect(page.getByTestId("mr-cap-row")).toHaveCount(3);
    await expect(page.locator('[data-testid="mr-cap-row"][data-cap="small"]')).toContainText("Nifty Smallcap 250");
    await expect(page.getByTestId("mr-breadth-chart")).toBeVisible();
    await expect(page.getByTestId("mr-breadth-legend")).toContainText("Above 20-day avg");
    await expect(page.getByTestId("mr-breadth-legend")).toContainText("Above 50-day avg");

    // 2. sectors: six rows, the top five marked leading
    await expect(page.getByTestId("mr-sector-row")).toHaveCount(6);
    await expect(page.locator('[data-testid="mr-sector-row"][data-leader="true"]')).toHaveCount(5);
    await expect(page.locator('[data-testid="mr-sector-row"]').first()).toHaveAttribute("data-sector", "Capital Goods");
    await expect(page.locator('[data-testid="mr-sector-row"][data-sector="Information Technology"]')).toContainText("Weak — avoid for now");

    // 3. candidates and others; 4. excluded; the footer
    const lead = page.getByTestId("mr-candidates");
    await expect(lead.getByTestId("mr-cand-row")).toHaveCount(2);
    await expect(lead.locator('[data-testid="mr-cand-row"]').first()).toHaveAttribute("data-symbol", "FIXA");
    await expect(lead.locator('[data-testid="mr-cand-row"][data-symbol="FIXA"]').getByTestId("mr-priority")).toBeVisible();
    await expect(lead.locator('[data-testid="mr-cand-row"][data-symbol="FIXB"]').getByTestId("mr-priority")).toHaveCount(0);
    await expect(lead.locator('[data-testid="mr-cand-row"][data-symbol="FIXA"]').getByTestId("mr-stop")).toHaveText(price(951.25));
    await expect(lead.locator('[data-testid="mr-cand-row"][data-symbol="FIXA"]').getByTestId("mr-t1")).toHaveText(price(1105));
    await expect(page.getByTestId("mr-others").getByTestId("mr-cand-row")).toHaveCount(1);
    await expect(page.getByTestId("mr-others").getByTestId("mr-no-plan")).toHaveText("No plan for this stock");
    await expect(page.getByTestId("mr-excluded-row")).toHaveCount(2);
    await expect(page.locator('[data-testid="mr-excluded-row"][data-trap="dead_cat"]')).toContainText("Dead-cat bounce");
    await expect(page.getByTestId("mr-sources")).toContainText(`as of ${AS_OF}`);
    await expect(page.getByTestId("mr-disclaimer")).toContainText("not investment advice");
    await expect(page.getByTestId("mr-disclaimer")).toContainText("have not been back-tested yet");
    expect(be.calls).toBe(1);
  });

  test("TC-E2 a candidate opens its detail: five components, the 5-session table, the plan with its standard labels, reasons", async ({ page }) => {
    await desk(page);
    await openRecovery(page);
    const row = page.getByTestId("mr-candidates").locator('[data-testid="mr-cand-row"][data-symbol="FIXA"]');
    const toggle = row.getByTestId("mr-cand-toggle");
    await expect(toggle).toHaveAttribute("aria-expanded", "false");
    await toggle.click();
    await expect(toggle).toHaveAttribute("aria-expanded", "true");
    const detail = page.locator('[data-testid="mr-cand-detail"][data-symbol="FIXA"]');
    await expect(detail).toBeVisible();
    for (const label of ["Relative strength", "Technical recovery", "Volume and delivery", "Fundamental quality", "Smart money"]) {
      await expect(detail.getByTestId("mr-detail-components")).toContainText(label);
    }
    await expect(detail.getByTestId("mr-detail-components")).toContainText("rescaled over the parts with data");
    await expect(detail.getByTestId("mr-accel-row")).toHaveCount(6);
    await expect(detail.locator('[data-testid="mr-accel-row"][data-key="rsi"]')).toContainText("39.0");
    await expect(detail.locator('[data-testid="mr-accel-row"][data-key="rsi"]')).toContainText("54.0");
    await expect(detail.locator('[data-testid="mr-accel-row"][data-key="volume"]')).toContainText("1.80×");
    await expect(detail.locator('[data-testid="mr-accel-row"][data-key="sector"]')).toHaveAttribute("data-improving", "false");
    const plan = detail.getByTestId("mr-detail-plan");
    for (const label of ["Entry zone", "Stop loss", "Target 1", "Target 2"]) await expect(plan).toContainText(label);
    await expect(plan).toContainText(`${price(990.5)}–${price(1010)}`);
    await expect(plan).toContainText("5.8% below the close");
    await expect(detail.getByTestId("mr-plan-basis")).toContainText("recovery-plan-v1");
    await expect(detail.getByTestId("mr-detail-reasons")).toContainText("Outperformed Nifty 500 by 8.0 pp");
    await expect(detail.getByTestId("mr-detail-cautions")).toContainText("Results due in 6 days");
    const gaps = detail.getByTestId("mr-detail-gaps");
    await expect(gaps).toHaveAttribute("data-count", "1");
    await expect(gaps.locator("summary")).toHaveText("1 figure not available");
    await gaps.locator("summary").click();
    await expect(gaps).toContainText("Cash flow (CFO/PAT) not available");
    await expect(detail.getByTestId("mr-detail-setup")).toContainText("Early breakout");
    await toggle.click();
    await expect(detail).toHaveCount(0);

    // The chart's readout: hover finds a session, and so does the keyboard.
    const chart = page.getByTestId("mr-breadth-chart");
    await chart.hover({ position: { x: 60, y: 60 } });
    await expect(page.getByTestId("mr-breadth-hover")).toContainText("above 20-day");
    await page.mouse.move(0, 0);
    await chart.focus();
    await page.keyboard.press("ArrowLeft");
    await expect(page.getByTestId("mr-breadth-hover")).toContainText(series[28].date);
  });

  test("TC-E3 with the flag off the switcher has five views, and the URL says the view is not enabled without asking the API", async ({ page }) => {
    const be = await desk(page, { flag: false });
    await page.goto(MARKET);
    await expect(page.getByTestId("desk-views")).toBeVisible(SLOW);
    await expect(page.getByTestId("desk-views").getByRole("button")).toHaveText(["Market Intelligence", "Smart Money", "Sector Rotation", "Stock Research", "Screener"]);
    await expect(page.getByTestId("desk-view-recovery")).toHaveCount(0);
    await page.goto(RECOVERY);
    await expect(page.getByTestId("mr-off")).toContainText("not enabled for your account", SLOW);
    await expect(page.getByTestId("mr-ready")).toHaveCount(0);
    expect(be.calls).toBe(0);
  });

  test("TC-E4 a 503 shows the server's own message; a 403 reads as not enabled; no candidates shows the empty state", async ({ page }) => {
    let mode: "stale" | "forbidden" | "empty" = "stale";
    await desk(page, {
      answer: () => mode === "stale"
        ? { status: 503, body: { detail: { code: "stale_data", message: "MOCK: the newest end-of-day prices are from 2026-10-20." }, status: 503, code: "stale_data" } }
        : mode === "forbidden"
          ? { status: 403, body: { detail: "Feature not enabled" } }
          : { status: 200, body: { ...ANSWER, candidates: [], others: [], excluded: [] } },
    });
    await page.goto(RECOVERY);
    const err = page.getByTestId("mr-error");
    await expect(err).toBeVisible(SLOW);
    await expect(err).toHaveAttribute("data-code", "stale_data");
    await expect(err).toContainText("The latest prices are too old to score");
    await expect(err).toContainText("the newest end-of-day prices are from 2026-10-20");

    mode = "forbidden";
    await page.reload();
    await expect(page.getByTestId("mr-off")).toContainText("not enabled for your account", SLOW);

    mode = "empty";
    await page.reload();
    await expect(page.getByTestId("mr-ready")).toBeVisible(SLOW);
    await expect(page.getByTestId("mr-candidates-empty")).toContainText("No stock in the leading sectors passed the gates");
    await expect(page.getByTestId("mr-others-empty")).toBeVisible();
    await expect(page.getByTestId("mr-excluded-empty")).toBeVisible();
    await expect(page.getByTestId("mr-regime-status")).toBeVisible();
  });

  test("TC-E5 wording: with details open, the page shows no trading-call word beyond the owner's plan labels and leg verbs", async ({ page }) => {
    await desk(page);
    await openRecovery(page);
    await expect(page.getByTestId("mr-indices-ready")).toBeVisible(SLOW);       // part 2 (§9) is on the page too, with its setups' legs
    await page.getByTestId("mr-candidates").locator('[data-testid="mr-cand-row"][data-symbol="FIXA"]').getByTestId("mr-cand-toggle").click();
    await expect(page.locator('[data-testid="mr-cand-detail"][data-symbol="FIXA"]')).toBeVisible();
    // the strategies (Buy / Sell legs) and, in the other table, the Nifty hedge are on the page too
    await expect(page.locator('[data-testid="mr-strats"][data-symbol="FIXA"]').getByTestId("mr-strat")).toHaveCount(5, SLOW);
    await page.getByTestId("mr-others").locator('[data-testid="mr-cand-row"][data-symbol="FIXC"]').getByTestId("mr-cand-toggle").click();
    await expect(page.getByTestId("mr-hedge")).toBeVisible(SLOW);
    const lines: string[] = await page.evaluate(() => {
      const out = [document.body.innerText];
      for (const el of Array.from(document.querySelectorAll("[aria-label],[title],[placeholder]"))) {
        for (const a of ["aria-label", "title", "placeholder"]) {
          const v = el.getAttribute(a);
          if (v) out.push(v);
        }
      }
      return out.join("\n").split("\n").map((s) => s.trim()).filter(Boolean);
    });
    // the exception is exercised: the four labels are on the page …
    const all = lines.join("\n");
    for (const label of ["Entry zone", "Stop loss", "Target 1", "Target 2"]) expect(all, label).toContain(label);
    // … and nothing else trips the lint
    const found = lines.flatMap((line) => { const w = hits(line); return w.length ? [{ line: line.slice(0, 160), words: w }] : []; });
    expect(found).toEqual([]);
    // the lint itself: a broader word still fails it
    expect(hits("Stop at 950")).not.toEqual([]);
    expect(hits("Buy above 1010")).not.toEqual([]);
    expect(hits("Target 3")).not.toEqual([]);
    expect(hits("Entry")).not.toEqual([]);
    expect(hits("STOP")).not.toEqual([]);
    // the leg verbs pass only in a leg
    expect(all).toMatch(/\bBuy 1 lot\b/);
    expect(all).toMatch(/\bSell 1 lot\b/);
    expect(hits("Buy 1 lot · 1,000 Put @ 22.50")).toEqual([]);
    expect(hits("Sell 2 lots · 950 Put @ 6.00")).toEqual([]);
    expect(hits("buy 1 lot")).not.toEqual([]);
    expect(hits("Sell now")).not.toEqual([]);
    expect(hits("Buy the dip")).not.toEqual([]);
  });
});

test.describe("MOCK — not real data: Market Desk › Market Recovery · strategies with protection (§8)", () => {
  const KEYS = ["protective_put", "bull_call_spread", "collar", "bull_put_spread", "put_ratio_backspread"];

  test("TC-S8 a detail asks for its stock's strategies once: five strategies, Buy / Sell legs, failing ones greyed with the reason", async ({ page }) => {
    const be = await desk(page);
    await openRecovery(page);
    expect(be.strategies).toEqual([]);                                         // nothing is asked until a detail opens
    const row = page.getByTestId("mr-candidates").locator('[data-testid="mr-cand-row"][data-symbol="FIXA"]');
    await row.getByTestId("mr-cand-toggle").click();
    const strats = page.locator('[data-testid="mr-strats"][data-symbol="FIXA"]');
    await expect(strats.getByTestId("mr-strat")).toHaveCount(5, SLOW);
    expect(be.strategies).toEqual(["FIXA"]);
    expect(await strats.getByTestId("mr-strat").evaluateAll((els) => els.map((e) => e.getAttribute("data-key")))).toEqual(KEYS);
    await expect(strats.getByTestId("mr-strats-title")).toContainText("protection against a fall");
    const head = strats.getByTestId("mr-strats-header");
    await expect(head).toContainText("Expiry 24 Nov 2026 · 25 days");
    await expect(head).toContainText("lot 500");
    await expect(head).toContainText("end-of-day prices of 30 Oct 2026");

    const pp = strats.locator('[data-testid="mr-strat"][data-key="protective_put"]');
    await expect(pp).toHaveAttribute("data-status", "passes");
    await expect(pp.getByTestId("mr-strat-status")).toContainText("Passes the checks");
    await expect(pp.getByTestId("mr-strat-leg")).toHaveText(["Buy 1 lot · 500 shares @ 1,010.00", "Buy 1 lot · 1,000 Put @ 22.50"]);
    await expect(pp.getByTestId("mr-strat-max-profit")).toHaveText("Unlimited");
    await expect(pp.getByTestId("mr-strat-max-loss")).toContainText("−₹16,250.00");
    await expect(pp.getByTestId("mr-strat-max-loss")).toContainText("−₹16,900.00 with costs");
    await expect(pp.getByTestId("mr-strat-premium")).toHaveText("₹11,250.00 debit (₹22.50 a share)");
    await expect(pp.getByTestId("mr-strat-rr")).toHaveText("2.90 : 1");
    await expect(pp.getByTestId("mr-strat-scenarios")).toContainText("Shares alone");
    await expect(pp.getByTestId("mr-strat-scenarios").locator("tbody tr")).toHaveCount(4);
    await expect(pp.getByTestId("mr-strat-scenarios")).toContainText("At the Stop loss");

    const bcs = strats.locator('[data-testid="mr-strat"][data-key="bull_call_spread"]');
    await expect(bcs.getByTestId("mr-strat-leg")).toHaveText(["Buy 1 lot · 1,010 Call @ 30.00", "Sell 1 lot · 1,100 Call @ 8.00"]);
    await expect(bcs.getByTestId("mr-strat-max-profit")).toHaveText("+₹34,000.00");
    await expect(bcs.getByTestId("mr-strat-scenarios")).not.toContainText("Shares alone");
    const col = strats.locator('[data-testid="mr-strat"][data-key="collar"]');
    await expect(col.getByTestId("mr-strat-premium")).toHaveText("₹1,000.00 credit (₹2.00 a share)");

    const bps = strats.locator('[data-testid="mr-strat"][data-key="bull_put_spread"]');
    await expect(bps).toHaveAttribute("data-status", "fails");
    await expect(bps.getByTestId("mr-strat-status")).toContainText("Fails a check");
    await expect(bps.getByTestId("mr-strat-why")).toContainText("a third of the strike width");
    await expect(bps.getByTestId("mr-strat-body")).toHaveCSS("opacity", "0.62");               // greyed …
    await expect(bps.getByTestId("mr-strat-why")).toBeVisible();                                // … the reason at full strength
    await expect(bps.locator('[data-testid="mr-strat-check"][data-id="credit"]')).toHaveAttribute("data-pass", "false");
    await expect(bps.locator('[data-testid="mr-strat-check"][data-id="reward_risk"]')).toHaveAttribute("data-pass", "false");
    await expect(bps).toContainText("settlement price");
    await expect(bps).toContainText("low open interest");

    const back = strats.locator('[data-testid="mr-strat"][data-key="put_ratio_backspread"]');
    await expect(back).toHaveAttribute("data-status", "unavailable");
    await expect(back.getByTestId("mr-strat-status")).toContainText("Not available");
    await expect(back.getByTestId("mr-strat-why")).toContainText("no put is listed near the Stop loss");
    await expect(back.getByTestId("mr-strat-leg")).toHaveCount(0);
    await expect(back.getByTestId("mr-strat-rr")).toHaveText("Not applied");
    await expect(back.locator('[data-testid="mr-strat-check"][data-id="reward_risk"]')).toHaveAttribute("data-pass", "unknown");
    await expect(back.locator('[data-testid="mr-strat-check"][data-id="reward_risk"]')).toContainText("judged by its loss zone");

    await expect(strats.getByTestId("mr-strats-notes")).toContainText("exchange margin for written options");
    await expect(strats.getByTestId("mr-strats-sources")).toContainText("NSE F&O bhavcopy");

    // The payoff reads by keyboard, from the point nearest the close.
    const chart = pp.getByTestId("mr-strat-payoff").locator("svg");
    await chart.focus();
    await page.keyboard.press("ArrowRight");
    await expect(pp.getByTestId("mr-strat-payoff")).toContainText("at expiry:");

    // Closing and reopening the row reuses the answer: still one request.
    await row.getByTestId("mr-cand-toggle").click();
    await expect(strats).toHaveCount(0);
    await row.getByTestId("mr-cand-toggle").click();
    await expect(page.locator('[data-testid="mr-strats"][data-symbol="FIXA"]').getByTestId("mr-strat")).toHaveCount(5, SLOW);
    expect(be.strategies).toEqual(["FIXA"]);
  });

  test("TC-S8 a stock without stock options shows the Nifty put hedge, its sizing and the caveat", async ({ page }) => {
    const be = await desk(page);
    await openRecovery(page);
    await page.getByTestId("mr-others").locator('[data-testid="mr-cand-row"][data-symbol="FIXC"]').getByTestId("mr-cand-toggle").click();
    const hedge = page.getByTestId("mr-hedge");
    await expect(hedge).toBeVisible(SLOW);
    expect(be.strategies).toEqual(["FIXC"]);
    const strats = page.locator('[data-testid="mr-strats"][data-symbol="FIXC"]');
    await expect(strats.getByTestId("mr-strat")).toHaveCount(0);
    await expect(strats.getByTestId("mr-strats-header")).toContainText("Expiry 24 Nov 2026 · 25 days");
    await expect(hedge).toHaveAttribute("data-status", "passes");
    await expect(hedge).toContainText("FIXC has no stock options on NSE");
    await expect(hedge.getByTestId("mr-strat-leg")).toHaveText("Buy 1 lot · NIFTY 24,900 Put @ 110.50");
    await expect(hedge.getByTestId("mr-hedge-covers")).toContainText("One lot hedges about ₹14,98,058 of FIXC (beta 1.12)");
    await expect(hedge.getByTestId("mr-hedge-cost")).toContainText("₹7,182.50 · 0.48% of the value it hedges");
    await expect(hedge.getByTestId("mr-hedge-scenarios").locator("tbody tr")).toHaveCount(3);
    await expect(hedge.getByTestId("mr-hedge-scenarios")).toContainText("−₹1,67,800.00");
    await expect(hedge.getByTestId("mr-hedge-caveat")).toContainText("market-wide fall only");
    await expect(hedge.getByTestId("mr-hedge-sizing")).toContainText("MOCK sizing");
  });

  test("TC-S8 a failed strategies answer shows the server's message inside the detail; the rest of the detail stays", async ({ page }) => {
    await desk(page, {
      strategies: () => ({ status: 503, body: { detail: { code: "chain_unavailable", message: "MOCK: FIXA has stock options, but no current chain for 30 Oct." }, status: 503, code: "chain_unavailable" } }),
    });
    await openRecovery(page);
    await page.getByTestId("mr-candidates").locator('[data-testid="mr-cand-row"][data-symbol="FIXA"]').getByTestId("mr-cand-toggle").click();
    const err = page.locator('[data-testid="mr-strats"][data-symbol="FIXA"]').getByTestId("mr-strats-error");
    await expect(err).toBeVisible(SLOW);
    await expect(err).toHaveAttribute("data-code", "chain_unavailable");
    await expect(err).toContainText("no current chain for 30 Oct");
    await expect(page.locator('[data-testid="mr-cand-detail"][data-symbol="FIXA"]').getByTestId("mr-detail-plan")).toBeVisible();
  });
});

test.describe("MOCK — not real data: Market Desk › Market Recovery · phone 390px", () => {
  test.use({ viewport: { width: 390, height: 844 } });

  test("TC-E6 at 390 px the page does not scroll sideways; the tables scroll inside their own box", async ({ page }) => {
    await desk(page);
    await openRecovery(page);
    await page.getByTestId("mr-candidates").locator('[data-testid="mr-cand-row"][data-symbol="FIXA"]').getByTestId("mr-cand-toggle").click();
    await expect(page.locator('[data-testid="mr-cand-detail"][data-symbol="FIXA"]')).toBeVisible();
    const over = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    expect(over).toBeLessThanOrEqual(1);
    await expect(page.getByTestId("mr-indices-ready")).toBeVisible(SLOW);
    for (const id of ["mr-regime", "mr-indices", "mr-sectors", "mr-candidates", "mr-excluded"]) {
      const b = await page.getByTestId(id).boundingBox();
      expect(b, id).not.toBeNull();
      expect(b!.x + b!.width, id).toBeLessThanOrEqual(391);
    }
    const scrolls = await page.getByTestId("mr-candidates").locator(".cp-scroll").first().evaluate((el) => el.scrollWidth > el.clientWidth);
    expect(scrolls).toBe(true);
  });

  test("TC-S8 at 390 px the strategies stack in one column and the page does not scroll sideways", async ({ page }) => {
    await desk(page);
    await openRecovery(page);
    await page.getByTestId("mr-candidates").locator('[data-testid="mr-cand-row"][data-symbol="FIXA"]').getByTestId("mr-cand-toggle").click();
    const strats = page.locator('[data-testid="mr-strats"][data-symbol="FIXA"]');
    await expect(strats.getByTestId("mr-strat")).toHaveCount(5, SLOW);
    const over = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    expect(over).toBeLessThanOrEqual(1);
    const boxes = await strats.getByTestId("mr-strat").evaluateAll((els) => els.map((e) => { const r = e.getBoundingClientRect(); return { x: Math.round(r.x), right: r.right }; }));
    for (const b of boxes) expect(b.right).toBeLessThanOrEqual(391);
    expect(new Set(boxes.map((b) => b.x)).size).toBe(1);                       // stacked: one column
  });
});

test.describe("MOCK — not real data: Market Desk › Market Recovery · 2 · Nifty and Bank Nifty (§9)", () => {
  test.use({ viewport: { width: 1440, height: 900 } });

  test("TC-I9 each expiry on its own row, setups grouped by expiry with Buy / Sell legs, levels, futures and flows; Bank Nifty on its tab", async ({ page }) => {
    const be = await desk(page);
    await openRecovery(page);
    const part = page.getByTestId("mr-indices");
    await expect(part.getByRole("heading")).toHaveText("2 · Nifty and Bank Nifty · each expiry");
    await expect(page.getByTestId("mr-indices-ready")).toBeVisible(SLOW);
    expect(be.indices).toBe(1);
    // the later parts are renumbered
    await expect(page.getByTestId("mr-sectors").getByRole("heading")).toHaveText("3 · Sector leaders");
    await expect(page.getByTestId("mr-excluded").getByRole("heading")).toHaveText("5 · Left out — possible false signals");
    // Nifty first
    await expect(part.getByTestId("mr-idx-tab")).toHaveText(["Nifty 50", "Bank Nifty"]);
    const nifty = part.locator('[data-testid="mr-idx"][data-symbol="NIFTY"]');
    await expect(nifty.getByTestId("mr-idx-snapshot")).toContainText("24,850.50");
    await expect(nifty.getByTestId("mr-idx-change")).toHaveText("+210.25 (+0.85%)");
    await expect(nifty.getByTestId("mr-idx-streak")).toHaveText("Up 3 sessions in a row");
    await expect(nifty.getByTestId("mr-idx-tech")).toContainText("24,950.3");
    await expect(nifty.getByTestId("mr-idx-tech")).toContainText("48.9 five sessions ago");
    await expect(nifty.getByTestId("mr-idx-pivots")).toContainText("R1 24,937.5");
    await expect(nifty.getByTestId("mr-idx-levels-above").getByTestId("mr-idx-level")).toHaveCount(3);
    await expect(nifty.getByTestId("mr-idx-levels-above")).toContainText("200-day average (EMA)");
    await expect(nifty.getByTestId("mr-idx-levels-below")).toContainText("Put wall, 3 Nov");
    await expect(nifty.locator('[data-testid="mr-fut-row"][data-buildup="short_covering"]')).toContainText("Short covering");
    await expect(nifty.locator('[data-testid="mr-fut-row"][data-buildup="short_covering"]')).toContainText("−9.0L (−6.50%)");
    // every expiry on its own row: weeklies and the monthly apart, each with its own figures
    const rows = nifty.getByTestId("mr-exp-row");
    await expect(rows).toHaveCount(4);
    const wk = nifty.locator('[data-testid="mr-exp-row"][data-expiry="2026-11-03"]');
    const mo = nifty.locator('[data-testid="mr-exp-row"][data-expiry="2026-11-24"]');
    await expect(wk).toHaveAttribute("data-kind", "weekly");
    await expect(mo).toHaveAttribute("data-kind", "monthly");
    await expect(wk.getByTestId("mr-exp-pcr")).toHaveText("1.21");
    await expect(mo.getByTestId("mr-exp-pcr")).toHaveText("1.34");
    await expect(wk.getByTestId("mr-exp-maxpain")).toHaveText("24,700");
    await expect(mo.getByTestId("mr-exp-maxpain")).toHaveText("24,500");
    await expect(wk.getByTestId("mr-exp-range")).toContainText("24,540–25,161");
    await expect(wk.getByTestId("mr-exp-calls")).toContainText("25,000 55.0L");
    await expect(wk.getByTestId("mr-exp-puts")).toContainText("fresh 24,600 +28.0L");
    await expect(wk.getByTestId("mr-exp-cuts")).toContainText("Calls 24,500 −4.0L");
    await expect(nifty.locator('[data-testid="mr-exp-row"][data-expiry="2026-11-10"]')).toContainText("Thin");
    await expect(nifty.locator('[data-testid="mr-exp-row"][data-expiry="2026-12-01"]')).toContainText("Too thin");
    await expect(nifty.locator('[data-testid="mr-exp-read"][data-expiry="2026-11-03"]')).toContainText("Fresh put writing at 24,600–24,700");
    await expect(nifty.getByTestId("mr-idx-expiries")).toContainText("lakh units (shares), not contracts");
    await expect(nifty.getByTestId("mr-idx-together")).toContainText("24,600 is the common floor");
    // setups grouped by expiry; the too-thin expiry has none and says so
    const groups = nifty.getByTestId("mr-setup-group");
    await expect(groups).toHaveCount(3);
    await expect(groups.nth(0)).toHaveAttribute("data-expiry", "2026-11-03");
    await expect(nifty.locator('[data-testid="mr-setup-group"][data-expiry="2026-12-01"]')).toHaveCount(0);
    await expect(nifty.getByTestId("mr-setups-skipped")).toContainText("1 Dec 2026");
    await expect(nifty.locator('[data-testid="mr-setup-group"][data-expiry="2026-11-10"]')).toContainText("thin: use limit orders");
    const bcs = nifty.locator('[data-testid="mr-setup"][data-key="bull_call_spread"][data-expiry="2026-11-03"]');
    await expect(bcs.getByTestId("mr-setup-leg")).toHaveText(["Buy 1 lot · 24,850 Call @ 160.50", "Sell 1 lot · 25,000 Call @ 95.25"]);
    await expect(bcs).toHaveAttribute("data-status", "fails");
    await expect(bcs.getByTestId("mr-setup-why")).toHaveText("Reward : risk at least 1.5: 1.30 : 1");
    await expect(bcs.getByTestId("mr-setup-premium")).toContainText("₹4,241.25 paid per lot");
    const ic = nifty.locator('[data-testid="mr-setup"][data-key="iron_condor"]');
    await expect(ic.getByTestId("mr-setup-leg")).toHaveCount(4);
    await expect(ic.getByTestId("mr-setup-premium")).toContainText("₹6,727.50 received per lot");
    await expect(nifty.locator('[data-testid="mr-setup"][data-key="hedge_put_spread"]').getByTestId("mr-setup-rr")).toHaveText("—");
    // shared: VIX, relative strength, flows, the disclaimer
    await expect(part.getByTestId("mr-idx-vix")).toContainText("14.2");
    await expect(part.getByTestId("mr-idx-relative")).toContainText("−4.60 pp");
    await expect(part.getByTestId("mr-flow-row")).toHaveCount(5);
    await expect(part.getByTestId("mr-idx-flows")).toContainText("net positive on 4 of the last 5 sessions");
    await expect(part.getByTestId("mr-idx-disclaimer")).toContainText("not investment advice");
    // Bank Nifty: its own monthly, no "Across expiries"
    await part.locator('[data-testid="mr-idx-tab"][data-symbol="BANKNIFTY"]').click();
    const bank = part.locator('[data-testid="mr-idx"][data-symbol="BANKNIFTY"]');
    await expect(bank.getByTestId("mr-exp-row")).toHaveCount(1);
    await expect(bank.getByTestId("mr-exp-pcr")).toHaveText("0.93");
    await expect(bank.getByTestId("mr-idx-streak")).toHaveText("Fell on the session");
    await expect(bank.getByTestId("mr-idx-together")).toHaveCount(0);
    await expect(bank.getByTestId("mr-setup-leg")).toHaveText(["Buy 1 lot · 56,100 Call @ 780.00", "Sell 1 lot · 57,000 Call @ 410.50"]);
    // the part's own text, Bank Nifty open: only the leg verbs are allowed
    const text = (await part.innerText()).split("\n").map((l) => l.trim()).filter(Boolean);
    const found = text.flatMap((line) => { const w = hits(line); return w.length ? [{ line, words: w }] : []; });
    expect(found).toEqual([]);
    expect(be.indices).toBe(1);                                                // the tab switch reads nothing new
  });

  test("TC-I9 a failed index read shows the server's message inside part 2; the rest of the page stays", async ({ page }) => {
    await desk(page, { indices: () => ({ status: 503, body: { detail: { code: "data_unavailable", message: "The Nifty option chains could not be read." } } }) });
    await openRecovery(page);
    const err = page.getByTestId("mr-indices").getByTestId("mr-idx-error");
    await expect(err).toBeVisible(SLOW);
    await expect(err).toHaveAttribute("data-code", "data_unavailable");
    await expect(err).toContainText("The Nifty option chains could not be read.");
    await expect(page.getByTestId("mr-sectors")).toBeVisible();
    await expect(page.getByTestId("mr-candidates")).toBeVisible();
  });
});

test.describe("MOCK — not real data: Market Desk › Market Recovery · 2 · Nifty and Bank Nifty · phone 390px", () => {
  test.use({ viewport: { width: 390, height: 844 } });

  test("TC-I9 at 390 px part 2 stays inside the screen: its tables scroll in their own box, the setups stack", async ({ page }) => {
    await desk(page);
    await openRecovery(page);
    await expect(page.getByTestId("mr-indices-ready")).toBeVisible(SLOW);
    const over = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    expect(over).toBeLessThanOrEqual(1);
    const b = await page.getByTestId("mr-indices").boundingBox();
    expect(b!.x + b!.width).toBeLessThanOrEqual(391);
    const scrolls = await page.getByTestId("mr-idx-expiries").locator(".cp-scroll").first().evaluate((el) => el.scrollWidth > el.clientWidth);
    expect(scrolls).toBe(true);
    const cards = await page.locator('[data-testid="mr-setup-group"][data-expiry="2026-11-03"] [data-testid="mr-setup"]')
      .evaluateAll((els) => els.map((e) => { const r = e.getBoundingClientRect(); return { x: Math.round(r.x), right: r.right }; }));
    expect(cards.length).toBe(2);
    for (const c of cards) expect(c.right).toBeLessThanOrEqual(391);
    expect(new Set(cards.map((c) => c.x)).size).toBe(1);                        // stacked: one column
  });
});
