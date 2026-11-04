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

// ── the desk with the flag and the route under test ─────────────────────────────────────────────────────────────────

interface Backend { calls: number; strategies: string[] }

async function desk(page: Page, o: {
  flag?: boolean; answer?: () => { status: number; body: unknown }; strategies?: (symbol: string) => { status: number; body: unknown };
} = {}): Promise<Backend> {
  const be: Backend = { calls: 0, strategies: [] };
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
    for (const id of ["mr-regime", "mr-sectors", "mr-candidates", "mr-excluded"]) {
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
