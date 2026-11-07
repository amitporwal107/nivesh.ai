/**
 * One-screen Copilot app (/v5/app) — Smart trading desk, Market Desk › Screener › Scan dashboard
 * (screens/tradingdesk/tabs/market-desk/scan-dashboard/; contract docs/scan_builder/DESIGN.md §8). Cases TC-DE1 … TC-DE7 of
 * test_reports/scan_builder_20261103_0431.md, for the simple realtime dashboard; TC-DE10 the strategy idea column (3 Nov);
 * TC-DE11 the second dashboard's tab, "Day trade" (Chartink 503347; test_reports/scan_dashboard_daytrade_20261103.md TC-11).
 * TC-DE11 (signals) … TC-DE13 the early signals: feed, row badges, browser alerts (DESIGN.md §10, 3 Nov).
 * TC-E1 … TC-E5 signal strength (DESIGN.md §11, 4 Nov; test_reports/scan_signal_strength_20261104.md): strong signals ≥ 70 with
 * the positional plan, the stocks below 70, alerts only for strong signals, wording, older answers.
 * TC-C1 … TC-C6 signals by company (DESIGN.md §11.1, 4 Nov): every company with a signal that day, searchable by symbol and
 * name (combobox with suggestions), each with its timeline; filters, sorts, paging; a backend without the route.
 *
 * MOCK — not real data. Every /api/scan-builder/market-dashboard answer below is hand-written to the contract: invented
 * symbols (ALPHA, BETA, GAMMA, DELTA), invented prices, invented index levels, invented day-trade widgets. Nothing here is
 * market data; the expected text is worked out from these fixtures, not copied from the screen. The mocked route reads the
 * request's `dashboard` query param to pick its answer. Production build, every /api mocked — see pw.copilot-app.config.ts.
 */
import { test, expect, type Page, type Route } from "@playwright/test";
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";
import { mockApi, mockSingleRoute } from "../helpers/api-mock";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const load = (name: string) => JSON.parse(fs.readFileSync(path.join(__dirname, "..", "fixtures", name), "utf-8"));

const DESK = "/v5/app/trader/desk";
const SCREENER = `${DESK}?tab=market&view=screener`;
const DASH = `${SCREENER}&sub=dashboard`;
const SLOW = { timeout: 15_000 };
const reply = (route: Route, body: unknown, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
const params = (page: Page) => new URL(page.url()).searchParams;

// ── MOCK — not real data: one dashboard answer ───────────────────────────────────────────────────────────────────────

const C = (text: string, o: { level?: number; applied?: boolean; note?: string } = {}) => ({ text, level: o.level ?? 0, applied: o.applied ?? true, note: o.note ?? null });
const STD_COLS = [
  { key: "symbol", label: "Symbol", format: "text" },
  { key: "chg", label: "% Change", format: "pct" },
  { key: "price", label: "Price", format: "price" },
  { key: "volume", label: "Volume", format: "volume" },
];

// MOCK — not real data: strategy ideas for the invented symbols. ALPHA and DELTA have one, BETA has none with a favorable
// reward : risk (null), GAMMA is still being built (no key).
const IDEAS = {
  ALPHA: { structure: "Bull call spread", family: "debit_spread", horizon: "1–3 weeks", reward_risk: 2.1, max_loss_inr: 12500,
           capital_at_risk_inr: 12500, legs_text: "NOV 820 CE / 860 CE", data_as_of: "2026-11-02" },
  BETA: null,
  DELTA: { structure: "Cash", family: "cash", horizon: "2–6 weeks", reward_risk: 1.6, max_loss_inr: 4100,
           capital_at_risk_inr: 41025, legs_text: "Cash, 100 shares", data_as_of: "2026-11-02" },
};
const IDEAS_META = { built: 3, pending: 1, note: "MOCK note: net reward : risk under the desk's rules.", source: "MOCK strategy builder", as_of: "2026-11-03T04:45:00Z" };

// MOCK — not real data: today's early signals for the invented symbols, newest first, each with its frozen plan.
type Sig = Record<string, unknown>;
const sig = (o: Sig): Sig => ({
  at_open: false, direction: "long", entry: null, stop_loss: null, target_1: null, target_2: null, risk_per_share: null,
  rr_1: null, rr_2: null, stop_basis: null, target_1_basis: null, plan_ok: false, plan_note: null, price_now: null, move_since_pct: null, ...o,
});
const SIG_ALPHA = sig({ id: "n50_gainers:ALPHA", widget_id: "n50_gainers", widget_title: "Nifty 50 Top Gainers", symbol: "ALPHA",
  first_seen: "2026-11-03T09:15:20+05:30", at_open: true, entry: 800, stop_loss: 785, target_1: 830, target_2: 845, risk_per_share: 15,
  rr_1: 2, rr_2: 3, stop_basis: "day low", target_1_basis: "2 × risk", plan_ok: true, price_now: 812.5, move_since_pct: 1.56 });
const SIG_DELTA = sig({ id: "oi_any:DELTA", widget_id: "oi_any", widget_title: "Open interest", symbol: "DELTA",
  first_seen: "2026-11-03T10:05:02+05:30", entry: 400, stop_loss: 392, target_1: 416, target_2: 424, risk_per_share: 8,
  rr_1: 2, rr_2: 3, stop_basis: "1 × ATR(14)", target_1_basis: "2 × risk", plan_ok: true, price_now: 410.25, move_since_pct: 2.56 });
const SIG_EPS = sig({ id: "oi_7:EPSILON", widget_id: "oi_7", widget_title: "Open interest 7", symbol: "EPSILON", direction: "short",
  first_seen: "2026-11-03T10:12:40+05:30", entry: 300, stop_loss: 309, target_1: 282, target_2: 273, risk_per_share: 9,
  rr_1: 2, rr_2: 3, stop_basis: "day high", target_1_basis: "2 × risk", plan_ok: true, price_now: 296.4, move_since_pct: -1.2 });
const SIG_BETA = sig({ id: "n50_gainers:BETA", widget_id: "n50_gainers", widget_title: "Nifty 50 Top Gainers", symbol: "BETA",
  first_seen: "2026-11-03T10:30:00+05:30", plan_note: "MOCK: reward : risk to Target 1 is 1.20, under 1.5, so no plan.", price_now: 1999.95, move_since_pct: 0.1 });
const SIGNALS = [SIG_BETA, SIG_EPS, SIG_DELTA, SIG_ALPHA];
const SIGNALS_META = { day: "2026-11-03", count: 4, recording: true,
  rules: "MOCK rules scan-plan-v1: Entry = the price when first seen; Stop loss = the lower of the day low and Entry − 1 × ATR(14); Target 1 = Entry + 2 × risk; Target 2 = Entry + 3 × risk.",
  caveat: "MOCK caveat: rules-based levels, not investment advice." };
const extra = (n: number, from = 0): Sig[] => Array.from({ length: n }, (_, i) => sig({
  id: `n50_gainers:X${from + i}`, widget_id: "n50_gainers", widget_title: "Nifty 50 Top Gainers", symbol: `X${from + i}`,
  first_seen: `2026-11-03T11:${String(10 + from + i).padStart(2, "0")}:00+05:30`, entry: 100, stop_loss: 98, target_1: 104, target_2: 106,
  rr_1: 2, rr_2: 3, plan_ok: true }));

// MOCK — not real data: signal strength (DESIGN.md §11). SAREGAMA's numbers follow the 4 Nov staging check (score 83 = Q26 T25
// R20 S5 P7; Entry 614.80, ATR(14) 18.99 → Stop loss 576.82, Target 1 690.76, Target 2 766.72; 20-day average 510.65) but are
// typed here by hand; ALPHA, BETA, EPSILON, SAKUMA and OILIETF are invented.
type Strong = Record<string, unknown>;
const P = (quality: number, trend: number, reason: number, size: number, participation: number, penalty = 0) => ({ quality, trend, reason, size, participation, penalty });
const L = (id: string, title: string) => ({ id, title });
const SCORES: Record<string, Record<string, unknown>> = {
  SAREGAMA: { score: 84, parts: P(26, 25, 20, 6, 7), reasons: ["Results filed today (positive)", "52-week-high breakout", "Debt/equity 0.04"], penalties: [],
    lists: [L("dt_52w_high", "52 week high"), L("early_movers", "Early movers")], note: null },
  ALPHA: { score: 76, parts: P(24, 22, 14, 15, 6, 5), reasons: ["Nifty 50", "Near the 52-week high"], penalties: [{ text: "1-year volatility 74 %", points: 5 }],
    lists: [L("n50_gainers", "Nifty 50 Top Gainers")], note: null },
  BETA: { score: 64, parts: P(20, 18, 6, 15, 5), reasons: ["Nifty 50", "Above 6 of 8 averages", "No filing today"], penalties: [],
    lists: [L("n50_gainers", "Nifty 50 Top Gainers")], note: null },
  SAKUMA: { score: 0, parts: P(12, 10, 4, 0, 0, 35), reasons: ["Above 3 of 8 averages"], penalties: [{ text: "market cap < ₹500 cr", points: 25 }, { text: "price < ₹20", points: 10 }],
    lists: [L("dt_vol_price_breakout", "Volume price breakout")], note: null },
  EPSILON: { score: null, parts: null, reasons: [], penalties: [], lists: [L("oi_7", "Open interest 7")], note: "Long only: a falling stock is not scored" },
  OILIETF: { score: null, parts: null, reasons: [], penalties: [], lists: [L("dt_multiyear", "Multi-year breakout")], note: "An ETF is not scored" },
};
const strongOf = (o: Strong): Strong => ({
  name: null, score_now: null, rules: "scan-plan-v3", rr_1: 2, rr_2: 4, plan_ok: true, plan_note: null, lists_at: [], reasons_at: [], parts_at: null,
  price_now: null, move_since_pct: null, ...o,
});
const STRONG_SAREGAMA = strongOf({ symbol: "SAREGAMA", name: "Saregama India Limited", first_strong: "2026-11-04T12:47:32+05:30", score_at: 83, score_now: 84,
  parts_at: P(26, 25, 20, 5, 7), reasons_at: ["Results filed today (positive)", "52-week-high breakout"], entry: 614.8, stop_loss: 576.82,
  target_1: 690.76, target_2: 766.72, risk_per_share: 37.98, atr: 18.99, sma20: 510.65,
  trend_exit: "a daily close below the 20-day average (510.65 on 3 Nov; it rises as the trend runs)",
  lists_at: [L("dt_52w_high", "52 week high")], price_now: 621.5, move_since_pct: 1.09 });
const STRONG_ALPHA = strongOf({ symbol: "ALPHA", first_strong: "2026-11-04T10:05:00+05:30", score_at: 76, score_now: 76, parts_at: P(24, 22, 14, 15, 6, 5),
  reasons_at: ["Nifty 50"], entry: 805, stop_loss: 781, target_1: 853, target_2: 901, risk_per_share: 24, atr: 12, sma20: 770,
  trend_exit: "a daily close below the 20-day average (770.00 on 3 Nov)", lists_at: [L("n50_gainers", "Nifty 50 Top Gainers")], price_now: 812.5, move_since_pct: 0.93 });
const SCORES_META = {
  threshold: 70, weights: { quality: 30, trend: 25, reason: 20, size: 15, participation: 10 },
  as_of: { fundamentals: "2026-11-03", eod: "2026-11-03", filings: "13:54 IST" },
  rules: "MOCK score rules: quality 30 + trend 25 + reason 20 + size 15 + participation 10, less penalties; set by hand, not back-tested.",
  plan_rules: "MOCK plan scan-plan-v3: Entry = the price when the score reached 70; Stop loss = Entry − 2 × ATR(14); Target 1 = 2 × risk; Target 2 = 4 × risk; trend exit on a daily close below the 20-day average.",
  caveat: "MOCK caveat: rule-based, not investment advice; a stop loss is a level, not a fill.",
  counts: { scored: 4, strong: 2, below: 4, not_scored: 2 }, warnings: [],
};

// MOCK — not real data: the day's signals by company (GET /signals/day, DESIGN.md §11.1). SAREGAMA's seven marks and its strong
// signal follow the 4 Nov staging check (10:49:22 at 575.25 … 13:05:03 at 617.60; 74 at 12:47:32) but are typed here by hand;
// every other company, mark and number is invented. Newest activity first, as the server sends them.
type Mark = { time: string; list: string; price: number | null; direction?: string };
const M = (time: string, list: string, price: number | null, direction = "long"): Mark => ({ time, list, price, direction });
const DAY_LISTS: Record<string, string> = {
  dt_52w_breakout: "52 week breakout", dt_52w_high: "52 week high", dt_short_breakouts: "Short term breakouts",
  dt_multiyear: "Multiyear breakout", dt_delivery_volume: "Delivery % + Volume", early_movers: "Early movers",
  dt_vol_price_breakout: "High volume and price breakout stocks", n50_gainers: "Nifty 50 Top Gainers", oi_7: "Open interest 7",
  cup_handle: "Cup and handle", rsi_dwm: "RSI daily weekly monthly",
};
const company = (o: Record<string, unknown> & { symbol: string; marks: Mark[] }) => ({
  name: "", score: null, parts: null, reasons: [], penalties: [], note: null, strong: null,
  first_seen: `2026-11-04T${o.marks[0].time}+05:30`, last_seen: `2026-11-04T${o.marks[o.marks.length - 1].time}+05:30`, n: o.marks.length, ...o,
});
const DAY_STRONG_SAREGAMA = { first_strong: "2026-11-04T12:47:32+05:30", score_at: 74, entry: 614.8, stop_loss: 576.82, target_1: 690.76, target_2: 766.72,
  risk_per_share: 37.98, rr_1: 2, rr_2: 4, atr: 18.99, sma20: 510.65, trend_exit: "A daily close below the 20-day average (₹510.65 on 2026-11-03; it rises as the trend runs)",
  plan_ok: true, plan_note: null, rules: "scan-plan-v3" };
const DAY_COMPANIES = [
  company({ symbol: "ZEN", name: "Zenith Mills Limited", score: 55, parts: P(20, 15, 10, 5, 5, 0),
    reasons: ["Above 6 of 8 daily averages", "Quality 20/30", "Size 5/15: outside Nifty 500"],
    marks: [M("09:20:00", "early_movers", 101), M("09:45:00", "dt_short_breakouts", 102.5), M("10:05:00", "dt_multiyear", 103),
      M("10:40:00", "cup_handle", 104.2), M("11:15:00", "dt_delivery_volume", 104.9), M("12:00:00", "rsi_dwm", 105.5),
      M("12:30:00", "dt_52w_high", 106), M("13:10:00", "dt_52w_breakout", 106.8), M("14:02:00", "dt_vol_price_breakout", 107.25)] }),
  company({ symbol: "SAREGAMA", name: "Saregama India Limited", score: 74, parts: P(26, 21, 20, 5, 7, -5),
    reasons: ["Results filing 04 Nov 12:31 IST (positive): Outcome of Board Meeting", "50-day average above the 200-day", "52-week-high breakout (prior high ₹574.50)"],
    penalties: [{ text: "26 % above its 20-day average (chasing)", points: 5 }], strong: DAY_STRONG_SAREGAMA,
    marks: [M("10:49:22", "dt_52w_breakout", 575.25), M("10:49:22", "dt_52w_high", 575.25), M("12:47:27", "dt_short_breakouts", 614.8),
      M("12:47:27", "dt_multiyear", 614.8), M("12:47:27", "dt_delivery_volume", 614.8), M("12:47:32", "early_movers", 614.8),
      M("13:05:03", "dt_vol_price_breakout", 617.6)] }),
  company({ symbol: "BETA", name: "Beta India Industries", score: 64, parts: P(20, 18, 6, 15, 5, 0),
    reasons: ["Nifty 50", "Above 6 of 8 averages", "No filing today"], marks: [M("12:10:00", "n50_gainers", 1999.95)] }),
  company({ symbol: "SAKUMA", name: "Sakuma Exports Limited", score: 0, parts: P(12, 10, 4, 0, 0, -35), reasons: ["Above 3 of 8 averages"],
    penalties: [{ text: "market cap < ₹500 cr", points: 25 }, { text: "price < ₹20", points: 10 }], marks: [M("11:00:00", "dt_vol_price_breakout", 2.73)] }),
  company({ symbol: "ALPHA", name: "Alpha Motors Limited", score: 76, parts: P(24, 22, 14, 15, 6, -5), reasons: ["Nifty 50"],
    penalties: [{ text: "1-year volatility 74 %", points: 5 }],
    strong: { ...DAY_STRONG_SAREGAMA, first_strong: "2026-11-04T10:05:00+05:30", score_at: 76, entry: 805, stop_loss: 781, target_1: 853, target_2: 901,
      risk_per_share: 24, atr: 12, sma20: 770, trend_exit: "A daily close below the 20-day average (₹770.00 on 2026-11-03)" },
    marks: [M("09:15:20", "n50_gainers", 800), M("10:30:00", "oi_7", 812.5)] }),
  company({ symbol: "EPSILON", name: "Epsilon Steel Limited", note: "Not scored: long only — this stock is in today's lists as a falling stock",
    marks: [M("10:12:40", "oi_7", 300, "short")] }),
  company({ symbol: "OILIETF", name: "Oil ETF", note: "Not scored: an ETF, not a company", marks: [M("09:40:00", "dt_multiyear", 9.87)] }),
];
const DAY = { ok: true, day: "2026-11-04", count: 22, companies_count: 7, threshold: 70, scores_as_of: "2026-11-04T14:40:12+05:30",
  lists: DAY_LISTS, warnings: [], companies: DAY_COMPANIES };
const dayOk = (body: unknown = DAY) => () => ({ status: 200, body });

/** A day answer grouped IN THE TEST from a dashboard answer's own `signals`, `scores` and `strong` (each signal's time = its IST
 *  first_seen; companies newest activity first). Used where the dashboard fixture is the source of truth (TC-E5, TC-RE2). */
function dayFrom(b: { signals?: Sig[] | null; scores?: Record<string, Record<string, unknown>> | null; strong?: Strong[] | null; signals_meta?: { day?: string } | null }) {
  type Co = { symbol: string; name: string; score: number | null; parts: unknown; reasons: string[]; penalties: unknown[]; note: string | null;
    strong: unknown; marks: Mark[]; iso: string[] };
  const by = new Map<string, Co>();
  const lists: Record<string, string> = {};
  const ensure = (sym: string): Co => {
    let c = by.get(sym);
    if (!c) by.set(sym, (c = { symbol: sym, name: "", score: null, parts: null, reasons: [], penalties: [], note: null, strong: null, marks: [], iso: [] }));
    return c;
  };
  for (const sg of b.signals ?? []) {
    const c = ensure(String(sg.symbol));
    const iso = String(sg.first_seen);
    c.marks.push(M(iso.slice(11, 19), String(sg.widget_id), (sg.entry as number | null) ?? null, String(sg.direction ?? "long")));
    c.iso.push(iso);
    if (sg.widget_title) lists[String(sg.widget_id)] = String(sg.widget_title);
  }
  for (const [sym, sc] of Object.entries(b.scores ?? {})) {
    const c = ensure(sym);
    c.name = String(sc.name ?? c.name ?? "");
    c.score = (sc.score as number | null) ?? null;
    c.parts = sc.parts ?? null;
    c.reasons = ((sc.reasons as string[]) ?? []).slice(0, 3);
    c.penalties = (sc.penalties as unknown[]) ?? [];
    c.note = (sc.note as string | null) ?? null;
    for (const l of (sc.lists as { id: string; title: string }[]) ?? []) lists[l.id] = lists[l.id] ?? l.title;
  }
  for (const st of b.strong ?? []) {
    const c = ensure(String(st.symbol));
    c.strong = st;
    c.name = c.name || String(st.name ?? "");
  }
  const companies = [...by.values()].map((c) => {
    const iso = [...c.iso].sort();
    return { symbol: c.symbol, name: c.name, score: c.score, parts: c.parts, reasons: c.reasons, penalties: c.penalties, note: c.note, strong: c.strong,
      first_seen: iso[0] ?? null, last_seen: iso[iso.length - 1] ?? null, n: c.marks.length, marks: [...c.marks].sort((x, y) => x.time.localeCompare(y.time)) };
  }).sort((x, y) => (y.last_seen ?? "").localeCompare(x.last_seen ?? "") || x.symbol.localeCompare(y.symbol));
  return { ok: true, day: b.signals_meta?.day ?? "", count: (b.signals ?? []).length, companies_count: companies.length, threshold: 70,
    scores_as_of: null, lists, warnings: [], companies };
}

function dashboard(o: { open?: boolean; bump?: number; warnings?: string[]; ideas?: boolean; signals?: Sig[] | false; recording?: boolean;
  strength?: boolean; strong?: Strong[]; scores?: Record<string, Record<string, unknown>>; day?: string } = {}) {
  const bump = o.bump ?? 0;
  const signals = o.signals === undefined ? SIGNALS : o.signals;
  return {
    ...(o.ideas === false ? {} : { ideas: IDEAS, ideas_meta: IDEAS_META }),
    ...(o.strength ? { scores: o.scores ?? SCORES, strong: o.strong ?? [STRONG_SAREGAMA, STRONG_ALPHA], scores_meta: SCORES_META } : {}),
    ...(signals === false ? {} : { signals, signals_meta: { ...SIGNALS_META, day: o.day ?? SIGNALS_META.day, count: signals.length, recording: o.recording ?? SIGNALS_META.recording } }),
    ok: true,
    run_at: "2026-11-03T04:45:30Z",                      // 10:15:30 IST
    elapsed_ms: 640,
    cached: false,
    basis: { mode: o.open === false ? "kite_close" : "live", day: "2026-11-03", eod_date: "2026-11-02", quote_as_of: "2026-11-03T04:45:29Z", text: "MOCK basis — Kite live 10:15:29 IST over NSE end-of-day bars to 02 Nov 2026" },
    market: { open: o.open !== false, refresh_seconds: 10 },
    counts: { cash: 2714, fno: 218, nifty50: 50, no_today_bar: 12 },
    sources: { prices: "MOCK prices source", today: "MOCK today source", fundamentals: "MOCK fundamentals source" },
    warnings: o.warnings ?? ["12 stocks had no live quote and are left out."],
    widgets: [
      {
        id: "mcap_ad", chartink_id: "3072994", title: "Marketcap Advances % / Declines", universe: "All NSE stocks", status: "ok", note: null,
        criteria: [
          C("Universe: All NSE stocks"),
          C("Grouped by market cap: rank 1–100 Largecap, 101–250 Midcap, 251+ Smallcap"),
          C("Advances = % of stocks with Close > 1 day ago Close"),
          C("Declines = % of stocks with Close < 1 day ago Close"),
        ],
        columns: [{ key: "group", label: "Marketcap", format: "text" }, { key: "adv", label: "Advances", format: "pct" }, { key: "dec", label: "Declines", format: "pct" }],
        rows: [["Midcap", 61.5, 37.25], ["Largecap", 55, 43], ["Smallcap", 48.25, 50.1]],
        row_kind: "group", count: 3, as_of: null,
      },
      {
        id: "index_stats", chartink_id: "3073022", title: "Index stats", universe: "Indices", status: "ok", note: null,
        criteria: [C("NIFTY 50 and NIFTY BANK: last price and % change against the previous close (Kite)")],
        columns: [{ key: "symbol", label: "Symbol", format: "text" }, { key: "ltp", label: "Ltp", format: "price" }, { key: "chg", label: "% chg", format: "pct" }],
        rows: [["BANKNIFTY", 50100.5, -0.42], ["NIFTY", 21000.25, 0.35]],
        row_kind: "index", count: 2, as_of: "2026-11-03T04:45:29Z",
      },
      {
        id: "n50_gainers", chartink_id: "2556934", title: "Nifty 50 Top Gainers", universe: "Nifty 50", status: "partial",
        note: "MOCK note: the two 15-minute conditions are not applied yet.",
        criteria: [
          C("Universe: Nifty 50"),
          C("Open > 1 day ago Close"),
          C("Close > 15 minute High of the first candle", { applied: false, note: "needs 15-minute candles" }),
          C("Volume > 200,000"),
          C("Close > 15 minute EMA(close, 21)", { applied: false, note: "needs 15-minute candles" }),
          C("RSI(14) > 55"),
        ],
        columns: STD_COLS,
        rows: [["ALPHA", 4.2, 812.5 + bump, 3250000], ["BETA", 1.1, 1999.95, 120000], ["GAMMA", -0.5, 55.1, null]],
        row_kind: "symbol", count: 3, as_of: null,
      },
      {
        id: "oi_any", chartink_id: "3044849", title: "Open interest", universe: "F&O stocks", status: "ok", note: null,
        criteria: [
          C("Universe: F&O stocks"),
          C("Volume > EMA(close, 10) × 5"),
          C("Any of:"),
          C("Close > 1 day ago Close × 1.05", { level: 1 }),
          C("Close < 1 day ago Close × 0.95", { level: 1 }),
        ],
        columns: STD_COLS,
        rows: [["DELTA", 6.1, 410.25, 2500000]],
        row_kind: "symbol", count: 1, as_of: null,
      },
      {
        id: "oi_7", chartink_id: "2854924", title: "Open interest 7", universe: "F&O stocks", status: "ok", note: null,
        criteria: [C("Universe: F&O stocks"), C("Volume > EMA(close, 8) × 5")],
        columns: STD_COLS, rows: [], row_kind: "symbol", count: 0, as_of: null,
      },
      {
        id: "good_results", chartink_id: "2737396", title: "Good quarter result stocks", universe: "All NSE stocks", status: "pending",
        note: "MOCK note: company results are loading (the first load of the day takes about a minute).",
        criteria: [C("Universe: All NSE stocks"), C("Net profit, latest quarter > Net profit, 1 quarter ago")],
        columns: STD_COLS, rows: [], row_kind: "symbol", count: null, as_of: null,
      },
      {
        id: "vol_10x_5min", chartink_id: "2653943", title: "10x volume first 5 min", universe: "All NSE stocks", status: "not_computed",
        note: "MOCK note: needs the count of trades initiated at the ask and at the bid, which no feed of ours carries.",
        criteria: [
          C("Universe: All NSE stocks"),
          C("5 minute Volume of the first candle > previous 5 minute SMA(volume, 1000) × 10", { applied: false, note: "needs 5-minute candles" }),
        ],
        columns: STD_COLS, rows: [], row_kind: "symbol", count: null, as_of: null,
      },
      {
        id: "triple_bottom", chartink_id: "2894893", title: "Triple bottom", universe: "F&O stocks", status: "error",
        note: "MOCK note: this widget could not be computed just now; it retries on the next refresh.",
        criteria: [C("Universe: F&O stocks"), C("RSI(14) > 50")],
        columns: STD_COLS, rows: [], row_kind: "symbol", count: 0, as_of: null,
      },
    ],
  };
}

// ── MOCK — not real data: the second dashboard ("Day trade"), and the new `dashboard` / `dashboards` fields ─────────────

const REFS = [
  { key: "atlas", title: "Atlas fresh", chartink_id: "247498" },
  { key: "daytrade", title: "Day trade", chartink_id: "503347" },
];
const ref = (key: string) => REFS.find((r) => r.key === key)!;

/** MOCK — the atlas answer of a backend that knows both dashboards (`dashboard()` alone is an older backend's answer). */
function atlas(o: Parameters<typeof dashboard>[0] = {}) {
  return { ...dashboard(o), dashboard: ref("atlas"), dashboards: REFS };
}

/** MOCK — invented day-trade widgets: one ok with rows, one not computed, one partial, one empty by definition. */
function dayTrade(o: { open?: boolean; bump?: number } = {}) {
  const bump = o.bump ?? 0;
  return {
    ...dashboard(o),
    dashboard: ref("daytrade"),
    dashboards: REFS,
    basis: { mode: o.open === false ? "kite_close" : "live", day: "2026-11-03", eod_date: "2026-11-02", quote_as_of: "2026-11-03T04:45:29Z", text: "MOCK basis — day trade: Kite live 10:15:29 IST over 15-minute candles" },
    warnings: [],
    widgets: [
      {
        id: "dt_day_high", chartink_id: "9100001", title: "Day high breakout", universe: "F&O stocks", status: "ok", note: null,
        criteria: [C("Universe: F&O stocks"), C("Close > 1 day ago High"), C("Volume > 500,000")],
        columns: STD_COLS,
        rows: [["ALPHA", 2.4, 830.1 + bump, 1500000], ["DELTA", 1.2, 415.5, 900000]],
        row_kind: "symbol", count: 2, as_of: null,
      },
      {
        id: "dt_12y_high", chartink_id: "9100002", title: "12-year high", universe: "All NSE stocks", status: "not_computed",
        note: "MOCK note: needs 12 years of daily bars; our history is shorter.",
        criteria: [C("Universe: All NSE stocks"), C("Close > 12 years ago Highest high", { applied: false, note: "needs 12 years of bars" })],
        columns: STD_COLS, rows: [], row_kind: "symbol", count: null, as_of: null,
      },
      {
        id: "dt_under_300", chartink_id: "9100003", title: "Under 300 above the 200-week line", universe: "All NSE stocks", status: "partial",
        note: "MOCK note: the 200-week line is not applied yet.",
        criteria: [C("Universe: All NSE stocks"), C("Close < 300"), C("Close > Weekly SMA(close, 200)", { applied: false, note: "needs 200 weeks of bars" })],
        columns: STD_COLS, rows: [["BETA", 0.8, 245, 410000]], row_kind: "symbol", count: 1, as_of: null,
      },
      {
        id: "dt_momentum", chartink_id: "9100004", title: "High momentum", universe: "F&O stocks", status: "ok",
        note: "MOCK note: always empty by definition — its two conditions can never hold together.",
        criteria: [C("Universe: F&O stocks"), C("RSI(14) > 80"), C("RSI(14) < 20")],
        columns: STD_COLS, rows: [], row_kind: "symbol", count: 0, as_of: null,
      },
    ],
  };
}
const DAY_TRADE_TITLES = ["Day high breakout", "12-year high", "Under 300 above the 200-week line", "High momentum"];
const ATLAS_TITLES = ["Marketcap Advances % / Declines", "Index stats", "Nifty 50 Top Gainers", "Open interest", "Open interest 7", "Good quarter result stocks", "10x volume first 5 min", "Triple bottom"];
const unknownDashboard = (key: string) => ({ status: 422, body: { detail: { code: "unknown_dashboard", message: `MOCK: there is no dashboard "${key}".` }, code: "unknown_dashboard" } });

/** MOCK — the default answer by the asked dashboard: atlas as an older backend answers it (no `dashboard` field, so the
 *  original cases keep testing that path), day trade from a backend that knows it, anything else 422 unknown_dashboard. */
function byDashboard(dash: string | null): { status: number; body: unknown } {
  if (dash === null || dash === "atlas") return { status: 200, body: dashboard() };
  if (dash === "daytrade") return { status: 200, body: dayTrade() };
  return unknownDashboard(dash);
}

// ── the mocked desk ──────────────────────────────────────────────────────────────────────────────────────────────────

interface Backend {
  calls: string[];
  /** The `dashboard` query param of every GET /market-dashboard, in order (null = absent). */
  asked: (string | null)[];
  answer: (n: number, dash: string | null) => { status: number; body: unknown };
  /** GET /signals/day (§11.1). Default: 404, as a backend from before the route answers — the panel stays hidden. */
  day: (n: number) => { status: number; body: unknown };
}

const NO_DAY_ROUTE = () => ({ status: 404, body: { detail: "Not Found" } });

async function desk(page: Page, o: { flag?: boolean; answer?: Backend["answer"]; day?: Backend["day"] } = {}): Promise<Backend> {
  const be: Backend = { calls: [], asked: [], answer: o.answer ?? ((_n, dash) => byDashboard(dash)), day: o.day ?? NO_DAY_ROUTE };
  await mockApi(page, "populated");
  await mockSingleRoute(page, "**/api/markets/home", "markets-home.json");
  await page.route("**/api/chat/sessions", (r) => reply(r, []));
  await page.route("**/api/move-odds/**", (r) => reply(r, { detail: "feature_not_enabled" }, 403));
  const base = load("user-profile-onboarded.json");
  await page.route("**/api/auth/me", (r) => reply(r, { ...base, features: { ...(base.features ?? {}), scan_builder: o.flag !== false } }));
  await page.route(/\/api\/scan-builder\//, async (r) => {
    const req = r.request();
    const url = new URL(req.url());
    const p = url.pathname.replace(/^.*\/api\/scan-builder/, "");
    be.calls.push(`${req.method()} ${p}`);
    if (p === "/market-dashboard" && req.method() === "GET") {
      const dash = url.searchParams.get("dashboard");
      be.asked.push(dash);
      const a = be.answer(be.calls.filter((c) => c === "GET /market-dashboard").length, dash);
      return reply(r, a.body, a.status);
    }
    if (p === "/signals/day" && req.method() === "GET") {
      const a = be.day(be.calls.filter((c) => c === "GET /signals/day").length);
      return reply(r, a.body, a.status);
    }
    return reply(r, { detail: { code: "unexpected", message: `unmocked ${req.method()} ${p}` } }, 500);
  });
  return be;
}

const dashCalls = (be: Backend) => be.calls.filter((c) => c === "GET /market-dashboard").length;
const widget = (page: Page, id: string) => page.getByTestId(`sd-widget-${id}`);

/** The visible text of a test id's element without the signals' plan blocks ([data-plan-words]), where the owner allowed the
 *  words Entry · Stop loss · Target 1 · Target 2 on 3 Nov. */
async function textOutsidePlan(page: Page, testId: string): Promise<string> {
  return page.getByTestId(testId).evaluate((root) => {
    const clone = root.cloneNode(true) as HTMLElement;
    clone.querySelectorAll("[data-plan-words]").forEach((el) => el.remove());
    document.body.appendChild(clone);
    const text = clone.innerText;
    clone.remove();
    return text;
  });
}

async function openDashboard(page: Page, url = DASH) {
  await page.goto(url);
  await expect(page.getByTestId("scan-dashboard")).toBeVisible(SLOW);
}

const BANNED = /\b(buy\w*|sell\w*|target\w*|stop[ -]?loss|picks?|recommend\w*|entry|exit)\b/i;
const tab = (page: Page, key: string) => page.getByTestId(`sd-dash-${key}`);
const titlesOf = (page: Page) => page.getByTestId("sd-widget-title");

test.describe("MOCK — not real data: Market Desk › Screener › Scan dashboard", () => {
  test("TC-DE1a with the flag off only the Screener is offered (no switcher), and the dashboard URL asks nothing", async ({ page }) => {
    const be = await desk(page, { flag: false });
    await page.goto(SCREENER);
    await expect(page.getByTestId("desk-panel-screener")).toBeAttached(SLOW);
    await expect(page.getByTestId("desk-subviews")).toHaveCount(0);
    await expect(page.getByTestId("desk-sub-dashboard")).toHaveCount(0);
    await page.goto(DASH);
    await expect(page.getByTestId("sd-off")).toContainText("not enabled for your account", SLOW);
    await expect(page.getByTestId("scan-dashboard")).toHaveCount(0);
    expect(be.calls).toEqual([]);
  });

  test("TC-DE1b with the flag on the Screener has three sub-views; Scan dashboard opens from the switcher", async ({ page }) => {
    const be = await desk(page);
    await page.goto(SCREENER);
    await expect(page.getByTestId("desk-subviews")).toBeVisible(SLOW);
    await expect.poll(() => params(page).get("sub")).toBe("screens");
    const keys = await page.getByTestId("desk-subviews").locator("button").evaluateAll((els) => els.map((e) => e.getAttribute("data-testid")));
    expect(keys).toEqual(["desk-sub-screens", "desk-sub-dashboard", "desk-sub-builder"]);
    await expect(page.getByTestId("desk-subviews").getByRole("button")).toHaveText(["Screener", "Scan dashboard", "Scan builder"]);
    await expect(page.getByTestId("desk-panel-screener")).toBeAttached(SLOW);
    // the Market Desk views themselves: the Screener is still the last one, no separate Scan Builder view
    await expect(page.getByTestId("desk-views").getByRole("button")).toHaveText(["Market Intelligence", "Smart Money", "Sector Rotation", "Stock Research", "Screener"]);
    expect(dashCalls(be)).toBe(0);
    await page.getByTestId("desk-sub-dashboard").click();
    await expect.poll(() => params(page).get("sub")).toBe("dashboard");
    await expect(page.getByTestId("md-eyebrow")).toHaveText("Market Desk · Screener · Scan dashboard");
    await expect(page.getByTestId("scan-dashboard")).toBeVisible(SLOW);
    await expect(page.getByTestId("desk-sub-dashboard")).toHaveAttribute("aria-pressed", "true");
    expect(dashCalls(be)).toBe(1);
  });

  test("TC-DE1c the old Scan Builder URL lands on Screener › Scan builder and keeps the open scan", async ({ page }) => {
    await desk(page);
    await page.goto(`${DESK}?tab=market&view=scanbuilder&scan=s9`);
    await expect.poll(() => params(page).get("view"), SLOW).toBe("screener");
    expect(params(page).get("sub")).toBe("builder");
    expect(params(page).get("scan")).toBe("s9");
    await expect(page.getByTestId("desk-panel-scanbuilder")).toBeAttached(SLOW);
    await expect(page.getByTestId("md-eyebrow")).toHaveText("Market Desk · Screener · Scan builder");
  });

  test("TC-DE2 the cards: titles, criteria, statuses, rows and formats; the header's basis, counts and warnings", async ({ page }) => {
    await desk(page, { answer: () => ({ status: 200, body: dashboard({ warnings: ["W1 MOCK", "W2 MOCK", "W3 MOCK", "W4 MOCK"] }) }) });
    await openDashboard(page);
    // header
    await expect(page.getByTestId("sd-basis")).toHaveText("MOCK basis — Kite live 10:15:29 IST over NSE end-of-day bars to 02 Nov 2026");
    await expect(page.getByTestId("sd-updated")).toContainText("Updated 10:15:30 IST");
    await expect(page.getByTestId("sd-counts")).toHaveText("All NSE stocks 2,714 · F&O 218 · Nifty 50 50 · 12 without today’s candle (left out)");
    await expect(page.getByTestId("sd-warning")).toHaveCount(3);
    await page.getByTestId("sd-warnings-toggle").click();
    await expect(page.getByTestId("sd-warning")).toHaveCount(4);
    // every card, in the server's order
    const titles = page.getByTestId("sd-widget-title");
    await expect(titles).toHaveText(["Marketcap Advances % / Declines", "Index stats", "Nifty 50 Top Gainers", "Open interest", "Open interest 7", "Good quarter result stocks", "10x volume first 5 min", "Triple bottom"]);
    // a group widget: plain rows, no links, no stock count
    const ad = widget(page, "mcap_ad");
    await expect(ad.getByTestId("sd-row")).toHaveCount(3);
    await expect(ad.getByTestId("sd-sym")).toHaveCount(0);
    await expect(ad.getByTestId("sd-widget-count")).toHaveCount(0);
    await expect(ad.getByTestId("sd-row").nth(0)).toContainText("Midcap");
    await expect(ad.getByTestId("sd-row").nth(0)).toContainText("61.50%");
    await expect(ad.getByTestId("sd-criterion")).toHaveCount(4);
    // an index widget: plain rows, its own as-of
    const ix = widget(page, "index_stats");
    await expect(ix.getByTestId("sd-sym")).toHaveCount(0);
    await expect(ix.getByTestId("sd-row").nth(0)).toContainText("BANKNIFTY");
    await expect(ix.getByTestId("sd-row").nth(0)).toContainText("50,100.50");
    await expect(ix.getByTestId("sd-row").nth(0)).toContainText("-0.42%");
    await expect(ix.getByTestId("sd-widget-meta")).toContainText("as of 10:15:29 IST");
    // a partial widget: the badge, its note, and the criteria it could not apply dimmed with the reason
    const n50 = widget(page, "n50_gainers");
    await expect(n50).toHaveAttribute("data-status", "partial");
    await expect(n50.getByTestId("sd-widget-status")).toHaveText("Partial");
    await expect(n50.getByTestId("sd-widget-note")).toHaveText("MOCK note: the two 15-minute conditions are not applied yet.");
    await expect(n50.getByTestId("sd-widget-count")).toHaveText("3 stocks");
    await expect(n50.getByTestId("sd-criterion")).toHaveCount(6);
    await expect(n50.locator('[data-testid="sd-criterion"][data-applied="false"]')).toHaveCount(2);
    await expect(n50.locator('[data-testid="sd-criterion"][data-applied="false"]').nth(0)).toContainText("Close > 15 minute High of the first candle");
    await expect(n50.getByTestId("sd-criterion-note").nth(0)).toContainText("not applied — needs 15-minute candles");
    // rows: the server's order, formats, symbol links, missing values
    const rows = n50.getByTestId("sd-row");
    await expect(rows).toHaveCount(3);
    await expect(rows.nth(0)).toHaveAttribute("data-key", "ALPHA");
    await expect(rows.nth(0)).toContainText("4.20%");
    await expect(rows.nth(0)).toContainText("812.50");
    await expect(rows.nth(0)).toContainText("32,50,000");
    await expect(rows.nth(1)).toContainText("1,999.95");
    await expect(rows.nth(2)).toContainText("-0.50%");
    await expect(rows.nth(2).locator("td").nth(3)).toHaveText("–");
    await expect(n50.getByTestId("sd-sym").nth(0)).toHaveText("ALPHA ↗");
    // the first % column is coloured by sign: mint up, danger down
    const upColor = await rows.nth(0).locator("td").nth(1).evaluate((el) => getComputedStyle(el).color);
    const downColor = await rows.nth(2).locator("td").nth(1).evaluate((el) => getComputedStyle(el).color);
    expect(upColor).not.toBe(downColor);
    // nested criteria are indented
    const oi = widget(page, "oi_any");
    const pad = await oi.getByTestId("sd-criterion").nth(3).evaluate((el) => getComputedStyle(el).paddingLeft);
    expect(pad).toBe("14px");
    await expect(oi.getByTestId("sd-widget-count")).toHaveText("1 stock");
    // an empty widget, a pending one and a not computed one
    await expect(widget(page, "oi_7").getByTestId("sd-widget-empty")).toHaveText("No stock passes right now.");
    await expect(widget(page, "oi_7").getByTestId("sd-widget-count")).toHaveText("0 stocks");
    const pend = widget(page, "good_results");
    await expect(pend.getByTestId("sd-widget-status")).toHaveText("Pending");
    await expect(pend.getByTestId("sd-widget-note")).toHaveText("MOCK note: company results are loading (the first load of the day takes about a minute).");
    await expect(pend.getByTestId("sd-table")).toHaveCount(0);
    const nc = widget(page, "vol_10x_5min");
    await expect(nc.getByTestId("sd-widget-status")).toHaveText("Not computed");
    await expect(nc.getByTestId("sd-widget-note")).toHaveText("MOCK note: needs the count of trades initiated at the ask and at the bid, which no feed of ours carries.");
    await expect(nc.getByTestId("sd-table")).toHaveCount(0);
    await expect(nc.locator('[data-testid="sd-criterion"][data-applied="false"]')).toHaveCount(1);
  });

  test("TC-DE3 a header click sorts the card's rows, a second click reverses, missing values stay last", async ({ page }) => {
    await desk(page);
    await openDashboard(page);
    const n50 = widget(page, "n50_gainers");
    const rows = n50.getByTestId("sd-row");
    await n50.getByTestId("sd-sort-price").click();
    await expect(n50.locator("th", { has: page.getByTestId("sd-sort-price") })).toHaveAttribute("aria-sort", "descending");
    await expect(rows.nth(0)).toHaveAttribute("data-key", "BETA");
    await expect(rows.nth(2)).toHaveAttribute("data-key", "GAMMA");
    await n50.getByTestId("sd-sort-price").click();
    await expect(n50.locator("th", { has: page.getByTestId("sd-sort-price") })).toHaveAttribute("aria-sort", "ascending");
    await expect(rows.nth(0)).toHaveAttribute("data-key", "GAMMA");
    await expect(rows.nth(2)).toHaveAttribute("data-key", "BETA");
    // GAMMA has no volume: last whichever way
    await n50.getByTestId("sd-sort-volume").click();
    await expect(rows.nth(0)).toHaveAttribute("data-key", "ALPHA");
    await expect(rows.nth(2)).toHaveAttribute("data-key", "GAMMA");
    await n50.getByTestId("sd-sort-volume").click();
    await expect(rows.nth(0)).toHaveAttribute("data-key", "BETA");
    await expect(rows.nth(2)).toHaveAttribute("data-key", "GAMMA");
    // text columns sort A→Z first
    await n50.getByTestId("sd-sort-symbol").click();
    await expect(rows.nth(0)).toHaveAttribute("data-key", "ALPHA");
    await expect(rows.nth(2)).toHaveAttribute("data-key", "GAMMA");
  });

  test("TC-DE4 a symbol opens Trade Desk › Chart Analysis for it; the link also carries the chart URL for a new tab", async ({ page }) => {
    await desk(page);
    await openDashboard(page);
    const link = widget(page, "n50_gainers").getByTestId("sd-sym").nth(0);
    await expect(link).toHaveAttribute("href", "/v5/app/trader/desk?tab=trade&view=chart&sub=live&sym=ALPHA");
    await link.click();
    await expect.poll(() => params(page).get("tab"), SLOW).toBe("trade");
    expect(params(page).get("view")).toBe("chart");
    expect(params(page).get("sub")).toBe("live");
    expect(params(page).get("sym")).toBe("ALPHA");
  });

  test("TC-DE9 a widget that could not be computed says so and shows no empty table", async ({ page }) => {
    await desk(page);
    await openDashboard(page);
    const w = widget(page, "triple_bottom");
    await expect(w).toHaveAttribute("data-status", "error");
    await expect(w.getByTestId("sd-widget-status")).toHaveText("Unavailable");
    await expect(w.getByTestId("sd-widget-note")).toContainText("could not be computed just now");
    await expect(w.getByTestId("sd-widget-empty")).toHaveCount(0);
    await expect(w.getByTestId("sd-criteria")).toBeVisible();
  });

  test("TC-DE5 while the market is open the dashboard is asked again every 10 s and the new numbers are shown", async ({ page }) => {
    await page.clock.install({ time: new Date("2026-11-03T04:45:00Z") });
    const be = await desk(page, { answer: (n) => ({ status: 200, body: dashboard({ bump: n }) }) });
    await openDashboard(page);
    expect(dashCalls(be)).toBe(1);
    await expect(page.getByTestId("sd-live-chip")).toHaveAttribute("data-state", "live");
    await expect(page.getByTestId("sd-live-chip")).toHaveText("Live · every 10 s");
    const first = widget(page, "n50_gainers").getByTestId("sd-row").nth(0);
    await expect(first).toContainText("813.50");                                // 812.5 + bump 1
    await page.clock.runFor(10_500);
    await expect.poll(() => dashCalls(be), SLOW).toBe(2);
    await expect(first).toContainText("814.50", SLOW);                          // the refreshed answer is on screen
    await page.clock.runFor(10_500);
    await expect.poll(() => dashCalls(be), SLOW).toBe(3);
    await expect(first).toContainText("815.50", SLOW);
  });

  test("TC-DE5b with the market closed the dashboard is asked once and not again", async ({ page }) => {
    await page.clock.install({ time: new Date("2026-11-03T12:00:00Z") });
    const be = await desk(page, { answer: () => ({ status: 200, body: dashboard({ open: false }) }) });
    await openDashboard(page);
    await expect(page.getByTestId("sd-live-chip")).toHaveAttribute("data-state", "closed");
    await expect(page.getByTestId("sd-live-chip")).toHaveText("Market closed");
    await page.clock.runFor(60_000);
    expect(dashCalls(be)).toBe(1);
  });

  test("TC-DE6 data unavailable (503) offers Retry; a failed refresh keeps the last answer and says so", async ({ page }) => {
    await page.clock.install({ time: new Date("2026-11-03T04:45:00Z") });
    const answers = [
      { status: 503, body: { detail: { code: "data_unavailable", message: "MOCK: the price history could not be loaded from the data platform." } } },
      { status: 200, body: dashboard() },
      { status: 503, body: { detail: { code: "data_unavailable", message: "MOCK: refresh failed." } } },
      { status: 200, body: dashboard({ bump: 7 }) },
    ];
    const be = await desk(page, { answer: (n) => answers[Math.min(n, answers.length) - 1] });
    await page.goto(DASH);
    const err = page.getByTestId("sd-error");
    await expect(err).toHaveAttribute("data-code", "data_unavailable", SLOW);
    await expect(err).toContainText("The market data could not be loaded");
    await expect(err).toContainText("MOCK: the price history could not be loaded from the data platform.");
    await err.getByRole("button", { name: /Retry/ }).click();
    await expect(page.getByTestId("scan-dashboard")).toBeVisible(SLOW);
    expect(dashCalls(be)).toBe(2);
    // the next refresh fails: the cards stay, the header says the last refresh failed
    await page.clock.runFor(10_500);
    await expect.poll(() => dashCalls(be), SLOW).toBe(3);
    await expect(page.getByTestId("sd-refresh-problem")).toContainText("The last refresh failed (MOCK: refresh failed.)", SLOW);
    await expect(widget(page, "n50_gainers").getByTestId("sd-row")).toHaveCount(3);
    // and the one after recovers by itself
    await page.clock.runFor(10_500);
    await expect.poll(() => dashCalls(be), SLOW).toBe(4);
    await expect(widget(page, "n50_gainers").getByTestId("sd-row").nth(0)).toContainText("819.50", SLOW);
    await expect(page.getByTestId("sd-refresh-problem")).toHaveCount(0);
  });

  test("TC-DE7 the dashboard never says buy, sell, target, stop loss, picks, recommended, entry or exit — except the owner's plan words in the plans", async ({ page }) => {
    await desk(page);
    await openDashboard(page);
    await page.getByTestId("sd-sources").locator("summary").click();
    await expect(page.getByTestId("sd-idea").first()).toBeVisible();
    await expect(page.getByTestId("sd-signal-plan").first()).toBeVisible();
    const banned = /\b(buy\w*|sell\w*|target\w*|stop[ -]?loss|picks?|recommend\w*|entry|exit)\b/i;
    const panel = page.getByTestId("desk-panel-scandashboard");
    // Outside the plans (marked data-plan-words): every word on the page and in every tooltip stays barred.
    const outside = await panel.evaluate((root) => {
      const clone = root.cloneNode(true) as HTMLElement;
      clone.querySelectorAll("[data-plan-words]").forEach((e) => e.remove());
      const titles = Array.from(root.querySelectorAll("[title]")).filter((e) => !e.closest("[data-plan-words]")).map((e) => e.getAttribute("title") ?? "");
      return { text: clone.textContent ?? "", titles };
    });
    const texts = [await page.getByTestId("md-head").innerText(), outside.text, ...outside.titles];
    expect(outside.titles.some((t) => t.includes("max loss"))).toBe(true);   // the idea tooltips are among the checked strings
    for (const t of texts) expect(t).not.toMatch(banned);
    // Inside the plans: only the owner's words for this screen (3 Nov) — Entry, Stop loss, Target 1, Target 2 — nothing else barred.
    const plans = await panel.locator("[data-plan-words]").evaluateAll((els) => els.map((e) => `${e.textContent ?? ""} ${e.getAttribute("title") ?? ""}`));
    expect(plans.length).toBeGreaterThan(0);
    for (const t of plans) expect(t.replace(/\b(Entry|Stop loss|Target 1|Target 2)\b/g, "")).not.toMatch(banned);
  });

  test("TC-DE10 stock tables end with a Strategy idea column: an idea, none favorable, or still being built; group and index tables do not", async ({ page }) => {
    await desk(page);
    await openDashboard(page);
    // the header line from ideas_meta, with the fixed caveat
    await expect(page.getByTestId("sd-ideas-count")).toHaveText("Strategy ideas: 3 of 4 stocks checked");
    await expect(page.getByTestId("sd-ideas-note")).toHaveText("· MOCK note: net reward : risk under the desk's rules.");
    await expect(page.getByTestId("sd-ideas-caveat")).toHaveText("Rules-based fits from the strategy builder, not investment advice.");
    // a stock table: Chartink's columns unchanged, the idea column appended last
    const n50 = widget(page, "n50_gainers");
    await expect(n50.locator("thead th")).toHaveText(["Symbol", "% Change", "Price", "Volume", "Strategy idea"]);
    const idea = (sym: string) => n50.locator(`[data-testid="sd-row"][data-key="${sym}"] [data-testid="sd-idea"]`);
    await expect(idea("ALPHA")).toHaveAttribute("data-state", "idea");
    await expect(idea("ALPHA")).toHaveText("Bull call spread · R:R 2.10");
    await expect(idea("ALPHA")).toHaveAttribute("title", "NOV 820 CE / 860 CE · max loss ₹12,500 · capital at risk ₹12,500 · 1–3 weeks · data 2026-11-02");
    await expect(idea("BETA")).toHaveAttribute("data-state", "none");
    await expect(idea("BETA")).toHaveText("–");
    await expect(idea("BETA")).toHaveAttribute("title", "No structure with a favorable reward : risk");
    await expect(idea("GAMMA")).toHaveAttribute("data-state", "building");
    await expect(idea("GAMMA")).toHaveText("…");
    await expect(idea("GAMMA")).toHaveAttribute("title", "Being built");
    const oi = widget(page, "oi_any");
    await expect(oi.locator('[data-testid="sd-row"][data-key="DELTA"] [data-testid="sd-idea"]')).toHaveText("Cash · R:R 1.60");
    // group and index tables: no idea column
    for (const id of ["mcap_ad", "index_stats"]) {
      await expect(widget(page, id).getByTestId("sd-idea")).toHaveCount(0);
      await expect(widget(page, id).getByTestId("sd-sort-idea")).toHaveCount(0);
    }
    // sorting by the idea's reward : risk: stocks without a number stay last either way
    const rows = n50.getByTestId("sd-row");
    await n50.getByTestId("sd-sort-idea").click();
    await expect(n50.locator("th", { has: page.getByTestId("sd-sort-idea") })).toHaveAttribute("aria-sort", "descending");
    await expect(rows.nth(0)).toHaveAttribute("data-key", "ALPHA");
    await n50.getByTestId("sd-sort-idea").click();
    await expect(n50.locator("th", { has: page.getByTestId("sd-sort-idea") })).toHaveAttribute("aria-sort", "ascending");
    await expect(rows.nth(0)).toHaveAttribute("data-key", "ALPHA");
    await expect(n50.getByTestId("sd-sort-idea")).toHaveText("Strategy idea ↑");
  });

  test("TC-DE11 New signals: newest first, the plan in the owner's words, the strategy idea, price now; short and no-plan rows; scan filter; row badges", async ({ page }) => {
    await desk(page);
    await openDashboard(page);
    const panel = page.getByTestId("sd-signals");
    await expect(panel).toBeVisible();
    await expect(panel.getByTestId("sd-signals-count")).toHaveText("4 today");
    const rows = panel.getByTestId("sd-signal");
    await expect(rows).toHaveCount(4);
    expect(await rows.evaluateAll((els) => els.map((e) => e.getAttribute("data-id")))).toEqual(["n50_gainers:BETA", "oi_7:EPSILON", "oi_any:DELTA", "n50_gainers:ALPHA"]);
    const alpha = panel.locator('[data-testid="sd-signal"][data-id="n50_gainers:ALPHA"]');
    await expect(alpha.getByTestId("sd-signal-time")).toHaveText("09:15");
    await expect(alpha.getByTestId("sd-signal-open")).toHaveText("at open");
    await expect(alpha.getByTestId("sd-signal-dir")).toHaveText("Long");
    await expect(alpha.getByTestId("sd-signal-scan")).toHaveText("Nifty 50 Top Gainers");
    await expect(alpha.getByTestId("sd-signal-plan")).toHaveText("Entry 800.00 · Stop loss 785.00 · Target 1 830.00 · Target 2 845.00 · R:R 2.00/3.00");
    await expect(alpha.getByTestId("sd-signal-plan")).toHaveAttribute("title", "Stop loss: day low · Target 1: 2 × risk · risk 15.00 a share");
    await expect(alpha.getByTestId("sd-signal-idea")).toHaveText("Strategy idea: Bull call spread · R:R 2.10");
    await expect(alpha.getByTestId("sd-signal-now")).toHaveText("Now 812.50 · +1.56%");
    await expect(alpha.getByTestId("sd-signal-sym")).toHaveAttribute("href", "/v5/app/trader/desk?tab=trade&view=chart&sub=live&sym=ALPHA");
    const eps = panel.locator('[data-testid="sd-signal"][data-id="oi_7:EPSILON"]');
    await expect(eps).toHaveAttribute("data-direction", "short");
    await expect(eps.getByTestId("sd-signal-dir")).toHaveText("Short");
    await expect(eps.getByTestId("sd-signal-plan")).toHaveText("Entry 300.00 · Stop loss 309.00 · Target 1 282.00 · Target 2 273.00 · R:R 2.00/3.00");
    await expect(eps.getByTestId("sd-signal-now")).toHaveText("Now 296.40 · -1.20%");
    await expect(eps.getByTestId("sd-signal-open")).toHaveCount(0);
    const beta = panel.locator('[data-testid="sd-signal"][data-id="n50_gainers:BETA"]');
    await expect(beta).toHaveAttribute("data-plan", "false");
    await expect(beta.getByTestId("sd-signal-plan")).toHaveCount(0);
    await expect(beta.getByTestId("sd-signal-noplan")).toHaveText("MOCK: reward : risk to Target 1 is 1.20, under 1.5, so no plan.");
    await expect(beta.getByTestId("sd-signal-idea")).toHaveCount(0);                 // BETA's idea is null: none shown
    await expect(panel.getByTestId("sd-signals-rules")).toContainText("MOCK rules scan-plan-v1");
    await expect(panel.getByTestId("sd-signals-caveat")).toHaveText("MOCK caveat: rules-based levels, not investment advice.");
    // the scan filter
    await panel.getByTestId("sd-signals-filter-oi_7").click();
    await expect(rows).toHaveCount(1);
    await expect(rows.nth(0)).toHaveAttribute("data-id", "oi_7:EPSILON");
    await panel.getByTestId("sd-signals-filter-all").click();
    await expect(rows).toHaveCount(4);
    // a feed symbol opens the chart like a table link
    await alpha.getByTestId("sd-signal-sym").click();
    await expect.poll(() => params(page).get("sym"), SLOW).toBe("ALPHA");
  });

  test("TC-DE11b stock rows that entered their scan today carry a New hh:mm badge; others and group tables do not", async ({ page }) => {
    await desk(page);
    await openDashboard(page);
    const n50 = widget(page, "n50_gainers");
    const badge = (sym: string) => n50.locator(`[data-testid="sd-row"][data-key="${sym}"] [data-testid="sd-new"]`);
    await expect(badge("ALPHA")).toHaveText("New 09:15");
    await expect(badge("ALPHA")).toHaveAttribute("title", "Entered this scan at 09:15 IST today");
    await expect(badge("BETA")).toHaveText("New 10:30");
    await expect(badge("GAMMA")).toHaveCount(0);
    await expect(n50.getByTestId("sd-sym").nth(0)).toHaveText("ALPHA ↗");          // the link text is unchanged
    await expect(widget(page, "oi_any").locator('[data-testid="sd-row"][data-key="DELTA"] [data-testid="sd-new"]')).toHaveText("New 10:05");
    await expect(widget(page, "mcap_ad").getByTestId("sd-new")).toHaveCount(0);
    await expect(widget(page, "index_stats").getByTestId("sd-new")).toHaveCount(0);
  });

  test("TC-DE11c the feed shows 20 and a Show all toggle for the rest; an empty day says why", async ({ page }) => {
    await desk(page, { answer: () => ({ status: 200, body: dashboard({ signals: [...extra(25)].reverse() }) }) });
    await openDashboard(page);
    const panel = page.getByTestId("sd-signals");
    await expect(panel.getByTestId("sd-signal")).toHaveCount(20);
    await expect(panel.getByTestId("sd-signals-toggle")).toHaveText("Show all 25");
    await panel.getByTestId("sd-signals-toggle").click();
    await expect(panel.getByTestId("sd-signal")).toHaveCount(25);
    await expect(panel.getByTestId("sd-signals-toggle")).toHaveText("Show fewer");
  });

  test("TC-DE11d no signals yet: the panel says so, and after the close that they are recorded while the market is open", async ({ page }) => {
    await desk(page, { answer: () => ({ status: 200, body: dashboard({ signals: [], recording: false, open: false }) }) });
    await openDashboard(page);
    await expect(page.getByTestId("sd-signals-empty")).toHaveText("No signals yet today. Signals are recorded while the market is open.");
    await expect(page.getByTestId("sd-signal")).toHaveCount(0);
  });

  test("TC-DE12 browser alerts: none for what the page opened with; one per new signal; one grouped notification when more than 3 arrive", async ({ page }) => {
    await page.addInitScript(() => {
      const w = window as unknown as { __notes: { title: string; body: string; tag: string }[]; Notification: unknown };
      w.__notes = [];
      class FakeNotification {
        static permission = "granted";
        static requestPermission() { return Promise.resolve(FakeNotification.permission); }
        constructor(title: string, opts?: { body?: string; tag?: string }) { w.__notes.push({ title, body: opts?.body ?? "", tag: opts?.tag ?? "" }); }
      }
      w.Notification = FakeNotification;
    });
    await page.clock.install({ time: new Date("2026-11-03T04:45:00Z") });
    const zeta = sig({ id: "n50_gainers:ZETA", widget_id: "n50_gainers", widget_title: "Nifty 50 Top Gainers", symbol: "ZETA",
      first_seen: "2026-11-03T10:40:00+05:30", entry: 120, stop_loss: 117.5, target_1: 125, target_2: 127.5, rr_1: 2, rr_2: 3, plan_ok: true });
    const answers = [SIGNALS, [zeta, ...SIGNALS], [...extra(5).reverse(), zeta, ...SIGNALS]];
    await desk(page, { answer: (n) => ({ status: 200, body: dashboard({ signals: answers[Math.min(n, answers.length) - 1] }) }) });
    await openDashboard(page);
    await expect(page.getByTestId("sd-alerts")).toHaveAttribute("data-state", "on");
    await expect(page.getByTestId("sd-alerts")).toHaveText("Browser alerts on");
    const notes = () => page.evaluate(() => (window as unknown as { __notes: { title: string; body: string }[] }).__notes);
    expect(await notes()).toEqual([]);                                             // the page's first answer only seeds
    await page.clock.runFor(10_500);
    await expect.poll(async () => (await notes()).length, SLOW).toBe(1);
    expect((await notes())[0]).toMatchObject({ title: "ZETA · Nifty 50 Top Gainers", body: "Entry 120.00 · Stop loss 117.50 · Target 1 125.00" });
    await page.clock.runFor(10_500);
    await expect.poll(async () => (await notes()).length, SLOW).toBe(2);
    expect((await notes())[1].title).toBe("5 new signals: X0, X1, X2, X3, X4");
    // pausing stops them
    await page.getByTestId("sd-alerts").click();
    await expect(page.getByTestId("sd-alerts")).toHaveAttribute("data-state", "paused");
  });

  test("TC-DE12b browser alerts blocked: the panel says so and nothing is announced; not yet allowed: the button asks", async ({ page }) => {
    await page.addInitScript(() => {
      const w = window as unknown as { __notes: string[]; Notification: unknown; __perm: string };
      w.__notes = [];
      w.__perm = (window.localStorage.getItem("test.perm") as string) || "denied";
      class FakeNotification {
        static get permission() { return w.__perm; }
        static requestPermission() { w.__perm = "granted"; return Promise.resolve("granted"); }
        constructor(title: string) { w.__notes.push(title); }
      }
      w.Notification = FakeNotification;
    });
    await page.clock.install({ time: new Date("2026-11-03T04:45:00Z") });
    const more = sig({ id: "n50_gainers:ZETA", widget_id: "n50_gainers", widget_title: "Nifty 50 Top Gainers", symbol: "ZETA", first_seen: "2026-11-03T10:40:00+05:30" });
    await desk(page, { answer: (n) => ({ status: 200, body: dashboard({ signals: n === 1 ? SIGNALS : [more, ...SIGNALS] }) }) });
    await openDashboard(page);
    await expect(page.getByTestId("sd-alerts")).toHaveAttribute("data-state", "denied");
    await expect(page.getByTestId("sd-alerts")).toContainText("Browser alerts are blocked");
    await page.clock.runFor(10_500);
    await expect(page.getByTestId("sd-signal")).toHaveCount(5, SLOW);
    expect(await page.evaluate(() => (window as unknown as { __notes: string[] }).__notes)).toEqual([]);
    // permission not asked yet: the button asks and turns alerts on
    await page.evaluate(() => window.localStorage.setItem("test.perm", "default"));
    await page.reload();
    await expect(page.getByTestId("sd-alerts")).toHaveAttribute("data-state", "off", SLOW);
    await page.getByTestId("sd-alerts").click();
    await expect(page.getByTestId("sd-alerts")).toHaveAttribute("data-state", "on");
  });

  test("TC-DE13 an answer without signals (an older backend) shows no panel and no badges", async ({ page }) => {
    await desk(page, { answer: () => ({ status: 200, body: dashboard({ signals: false }) }) });
    await openDashboard(page);
    await expect(page.getByTestId("sd-signals")).toHaveCount(0);
    await expect(page.getByTestId("sd-new")).toHaveCount(0);
    await expect(widget(page, "n50_gainers").getByTestId("sd-row")).toHaveCount(3);
  });

  test("TC-DE10b an answer without ideas (an older backend) shows no idea column and no ideas line", async ({ page }) => {
    await desk(page, { answer: () => ({ status: 200, body: dashboard({ ideas: false }) }) });
    await openDashboard(page);
    await expect(widget(page, "n50_gainers").locator("thead th")).toHaveText(["Symbol", "% Change", "Price", "Volume"]);
    await expect(page.getByTestId("sd-idea")).toHaveCount(0);
    await expect(page.getByTestId("sd-ideas-line")).toHaveCount(0);
  });
});

test.describe("MOCK — not real data: Market Desk › Screener › Scan dashboard · signal strength (DESIGN.md §11)", () => {
  test("TC-E1 Strong signals: newest first; score when recorded and now; parts; reasons; penalties; the positional plan with its trend exit; lists; price now", async ({ page }) => {
    await desk(page, { answer: () => ({ status: 200, body: dashboard({ strength: true }) }) });
    await openDashboard(page);
    const panel = page.getByTestId("sd-strong");
    await expect(panel).toBeVisible();
    await expect(page.getByTestId("sd-signals")).toHaveCount(0);                     // the §10 feed is replaced
    await expect(panel.locator("h4")).toHaveText("Strong signals (score ≥ 70)");
    await expect(panel.getByTestId("sd-strong-count")).toHaveText("2 today");
    const items = panel.getByTestId("sd-strong-item");
    expect(await items.evaluateAll((els) => els.map((e) => e.getAttribute("data-symbol")))).toEqual(["SAREGAMA", "ALPHA"]);
    const sare = panel.locator('[data-testid="sd-strong-item"][data-symbol="SAREGAMA"]');
    await expect(sare.getByTestId("sd-strong-time")).toHaveText("12:47");
    await expect(sare.getByTestId("sd-strong-name")).toHaveText("Saregama India Limited");
    await expect(sare.getByTestId("sd-strong-score")).toHaveText("83/100");
    await expect(sare.getByTestId("sd-strong-score-now")).toHaveText("83 when recorded · 84 now");
    await expect(sare.getByTestId("sd-strong-parts")).toHaveText("Quality 26/30 · Trend 25/25 · Reason 20/20 · Size 6/15 · Participation 7/10");
    await expect(sare.getByTestId("sd-strong-reason")).toHaveText(["Results filed today (positive)", "52-week-high breakout", "Debt/equity 0.04"]);
    await expect(sare.getByTestId("sd-strong-penalty")).toHaveCount(0);
    await expect(sare.getByTestId("sd-strong-plan")).toHaveText("Entry 614.80 · Stop loss 576.82 · Target 1 690.76 · Target 2 766.72 · R:R 2 / 4");
    await expect(sare.getByTestId("sd-strong-plan")).toHaveAttribute("title", "ATR(14) 18.99 · risk 37.98 a share · rules scan-plan-v3");
    await expect(sare.getByTestId("sd-strong-exit")).toHaveText("Trend exit: a daily close below the 20-day average (510.65 on 3 Nov; it rises as the trend runs)");
    await expect(sare.getByTestId("sd-strong-lists")).toHaveText("In today's lists: 52 week high · Early movers");
    await expect(sare.getByTestId("sd-strong-now")).toHaveText("Now 621.50 · +1.09%");
    await expect(sare.getByTestId("sd-strong-sym")).toHaveAttribute("href", "/v5/app/trader/desk?tab=trade&view=chart&sub=live&sym=SAREGAMA");
    const alpha = panel.locator('[data-testid="sd-strong-item"][data-symbol="ALPHA"]');
    await expect(alpha.getByTestId("sd-strong-score")).toHaveText("76/100");
    await expect(alpha.getByTestId("sd-strong-score-now")).toHaveCount(0);           // unchanged since recorded
    await expect(alpha.getByTestId("sd-strong-parts")).toHaveText("Quality 24/30 · Trend 22/25 · Reason 14/20 · Size 15/15 · Participation 6/10 · Penalties −5");
    await expect(alpha.getByTestId("sd-strong-penalty")).toHaveText(["1-year volatility 74 % −5"]);
    await expect(alpha.getByTestId("sd-strong-idea")).toHaveText("Strategy idea: Bull call spread · R:R 2.10");
    await expect(panel.getByTestId("sd-strong-rules")).toContainText("MOCK score rules");
    await expect(panel.getByTestId("sd-strong-plan-rules")).toContainText("MOCK plan scan-plan-v3");
    await expect(panel.getByTestId("sd-strong-asof")).toHaveText("Data as of: fundamentals 2026-11-03 · eod 2026-11-03 · filings 13:54 IST");
    // the table rows carry the stock's score; 70 and above in mint
    const n50 = widget(page, "n50_gainers");
    await expect(n50.locator('[data-testid="sd-row"][data-key="ALPHA"] [data-testid="sd-score"]')).toHaveText("76");
    await expect(n50.locator('[data-testid="sd-row"][data-key="ALPHA"] [data-testid="sd-score"]')).toHaveAttribute("data-strong", "true");
    await expect(n50.locator('[data-testid="sd-row"][data-key="BETA"] [data-testid="sd-score"]')).toHaveAttribute("data-strong", "false");
    await expect(n50.locator('[data-testid="sd-row"][data-key="GAMMA"] [data-testid="sd-score"]')).toHaveCount(0);
    // a card's symbol opens the chart
    await sare.getByTestId("sd-strong-sym").click();
    await expect.poll(() => params(page).get("sym"), SLOW).toBe("SAREGAMA");
  });

  test("TC-E2 the stocks below 70 live in Signals by company now: Strong signals has no fold; the Below 70 filter lists them with score, reasons and penalties, no plan", async ({ page }) => {
    await desk(page, { answer: () => ({ status: 200, body: dashboard({ strength: true }) }), day: dayOk() });
    await openDashboard(page);
    await expect(page.getByTestId("sd-strong")).toBeVisible();
    await expect(page.getByTestId("sd-below-toggle")).toHaveCount(0);                   // the fold that sat here is gone
    const panel = page.getByTestId("sd-bycompany");
    await expect(panel).toBeVisible(SLOW);
    await panel.getByTestId("sd-bc-filter-below").click();
    await expect(panel.getByTestId("sd-bc-filter-below")).toHaveAttribute("aria-pressed", "true");
    const rows = panel.getByTestId("sd-bc-item");
    expect(await rows.evaluateAll((els) => els.map((e) => e.getAttribute("data-symbol")))).toEqual(["ZEN", "BETA", "SAKUMA"]);
    const beta = panel.locator('[data-testid="sd-bc-item"][data-symbol="BETA"]');
    await expect(beta.getByTestId("sd-bc-score")).toHaveText("64/100");
    await expect(beta.getByTestId("sd-bc-reason")).toHaveText(["Nifty 50", "Above 6 of 8 averages", "No filing today"]);
    const sakuma = panel.locator('[data-testid="sd-bc-item"][data-symbol="SAKUMA"]');
    await expect(sakuma.getByTestId("sd-bc-score")).toHaveText("0/100");
    await expect(sakuma.getByTestId("sd-bc-penalty")).toHaveText(["market cap < ₹500 cr −25", "price < ₹20 −10"]);
    await expect(panel.getByTestId("sd-bc-list").locator("[data-plan-words]")).toHaveCount(0);   // no plan below the line
    expect(await panel.getByTestId("sd-bc-list").innerText()).not.toMatch(/\b(Entry|Stop loss|Target)\b/);
    await panel.getByTestId("sd-bc-filter-unscored").click();
    expect(await rows.evaluateAll((els) => els.map((e) => e.getAttribute("data-symbol")))).toEqual(["EPSILON", "OILIETF"]);
    await expect(panel.locator('[data-testid="sd-bc-item"][data-symbol="OILIETF"] [data-testid="sd-bc-note"]')).toHaveText("Not scored: an ETF, not a company");
    await expect(panel.locator('[data-testid="sd-bc-item"][data-symbol="EPSILON"] [data-testid="sd-bc-score"]')).toHaveText("not scored");
  });

  test("TC-E3 browser alerts announce only new strong signals: not what the page opened with, never a list entry below 70; grouped above 3", async ({ page }) => {
    await page.addInitScript(() => {
      const w = window as unknown as { __notes: { title: string; body: string; tag: string }[]; Notification: unknown };
      w.__notes = [];
      class FakeNotification {
        static permission = "granted";
        static requestPermission() { return Promise.resolve(FakeNotification.permission); }
        constructor(title: string, opts?: { body?: string; tag?: string }) { w.__notes.push({ title, body: opts?.body ?? "", tag: opts?.tag ?? "" }); }
      }
      w.Notification = FakeNotification;
    });
    await page.clock.install({ time: new Date("2026-11-04T07:20:00Z") });
    const zeta = sig({ id: "n50_gainers:ZETA", widget_id: "n50_gainers", widget_title: "Nifty 50 Top Gainers", symbol: "ZETA", first_seen: "2026-11-04T12:49:00+05:30" });
    const more = Array.from({ length: 5 }, (_, i) => strongOf({ symbol: `S${i}`, first_strong: `2026-11-04T13:0${i}:00+05:30`, score_at: 71 + i,
      entry: 100, stop_loss: 96, target_1: 108, target_2: 116 }));
    const answers = [
      dashboard({ day: "2026-11-04", strength: true, strong: [STRONG_ALPHA] }),
      // a new list entry below 70 (ZETA) and a new strong signal (SAREGAMA)
      dashboard({ day: "2026-11-04", strength: true, strong: [STRONG_SAREGAMA, STRONG_ALPHA], signals: [zeta, ...SIGNALS], scores: { ...SCORES, ZETA: { score: 41, lists: [L("n50_gainers", "Nifty 50 Top Gainers")] } } }),
      dashboard({ day: "2026-11-04", strength: true, strong: [...more.reverse(), STRONG_SAREGAMA, STRONG_ALPHA] }),
    ];
    await desk(page, { answer: (n) => ({ status: 200, body: answers[Math.min(n, answers.length) - 1] }) });
    await openDashboard(page);
    await expect(page.getByTestId("sd-strong").getByTestId("sd-alerts")).toHaveAttribute("data-state", "on");
    const notes = () => page.evaluate(() => (window as unknown as { __notes: { title: string; body: string; tag: string }[] }).__notes);
    expect(await notes()).toEqual([]);                                             // the first answer only seeds
    await page.clock.runFor(10_500);
    await expect.poll(async () => (await notes()).length, SLOW).toBe(1);
    expect((await notes())[0]).toEqual({ title: "SAREGAMA · strong signal 83/100", body: "Entry 614.80 · Stop loss 576.82 · Target 1 690.76", tag: "strong:2026-11-04:SAREGAMA" });
    await page.clock.runFor(10_500);
    await expect.poll(async () => (await notes()).length, SLOW).toBe(2);
    expect((await notes())[1].title).toBe("5 strong signals: S0, S1, S2, S3, S4");
    expect((await notes()).some((n) => n.title.includes("ZETA"))).toBe(false);    // the list entry below 70 never alerted
  });

  test("TC-E4 outside the plan blocks the page never says buy, sell, target, stop loss, picks, recommend, entry or exit — every company's timeline open, tooltips included", async ({ page }) => {
    await desk(page, { answer: () => ({ status: 200, body: dashboard({ strength: true }) }), day: dayOk() });
    await openDashboard(page);
    await expect(page.getByTestId("sd-strong-plan").first()).toBeVisible();
    await expect(page.getByTestId("sd-bc-item").first()).toBeVisible(SLOW);
    for (let i = 0; i < 50 && (await page.getByTestId("sd-bc-more").count()) > 0; i++) await page.getByTestId("sd-bc-more").first().click();
    await expect(page.getByTestId("sd-bc-more")).toHaveCount(0);
    await page.getByTestId("sd-sources").locator("summary").click();
    const panel = page.getByTestId("desk-panel-scandashboard");
    const outside = await panel.evaluate((root) => {
      const clone = root.cloneNode(true) as HTMLElement;
      clone.querySelectorAll("[data-plan-words]").forEach((e) => e.remove());
      const titles = Array.from(root.querySelectorAll("[title]")).filter((e) => !e.closest("[data-plan-words]")).map((e) => e.getAttribute("title") ?? "");
      return { text: clone.textContent ?? "", titles };
    });
    expect(outside.text).toContain("Strong signals");
    for (const t of [await page.getByTestId("md-head").innerText(), outside.text, ...outside.titles]) expect(t).not.toMatch(BANNED);
    // inside the plan blocks only the owner's words for this screen (Entry, Stop loss, Target 1/2, Trend exit) besides the rest
    // innerText keeps the plan's lines apart (textContent would glue "R:R 2 / 4" to "Trend exit")
    const plans = await panel.locator("[data-plan-words]").evaluateAll((els) => els.map((e) => `${(e as HTMLElement).innerText} ${e.getAttribute("title") ?? ""}`));
    expect(plans.length).toBeGreaterThan(0);
    for (const t of plans) expect(t.replace(/\b(Entry|Stop loss|stop loss|Target 1|Target 2|Trend exit|trend exit)\b/g, "")).not.toMatch(BANNED);
  });

  test("TC-E5 none strong yet: the panel says so (and, after the close, when they are recorded); an older answer without scores keeps the §10 feed", async ({ page }) => {
    let mode: "none" | "old" = "none";
    const none = dashboard({ strength: true, strong: [], recording: false, open: false });
    const be = await desk(page, { answer: () => ({ status: 200, body: mode === "none" ? none : dashboard({ open: false }) }), day: () => ({ status: 200, body: dayFrom(none) }) });
    await openDashboard(page);
    await expect(page.getByTestId("sd-strong-empty")).toHaveText("No stock has reached 70 today. Strong signals are recorded while the market is open.");
    await expect(page.getByTestId("sd-strong-item")).toHaveCount(0);
    // at or above 70 after the close without a recorded strong signal: listed apart, without a plan, never under "Below 70"
    const unrec = page.getByTestId("sd-unrecorded-item");
    expect(await unrec.evaluateAll((els) => els.map((e) => e.getAttribute("data-symbol")))).toEqual(["SAREGAMA", "ALPHA"]);
    await expect(unrec.first().getByTestId("sd-unrecorded-note")).toHaveText("At or above 70 now, while no signals were being recorded (outside the session), so it carries no plan.");
    // the rest is in Signals by company (its day grouped in the test from this same answer): ALPHA and SAREGAMA at 70+, BETA and
    // SAKUMA below, DELTA (a list mark without a score), EPSILON and OILIETF not scored
    await expect(page.getByTestId("sd-bc-filter-high")).toHaveText("70+ (2)", SLOW);
    await expect(page.getByTestId("sd-bc-filter-below")).toHaveText("Below 70 (2)");
    await expect(page.getByTestId("sd-bc-filter-unscored")).toHaveText("Not scored (3)");
    const dayCalls = be.calls.filter((c) => c === "GET /signals/day").length;
    expect(dayCalls).toBeGreaterThan(0);
    mode = "old";
    await page.reload();
    await expect(page.getByTestId("sd-signals")).toBeVisible(SLOW);
    await expect(page.getByTestId("sd-strong")).toHaveCount(0);
    await expect(page.getByTestId("sd-score")).toHaveCount(0);
    await expect(page.getByTestId("sd-bycompany")).toHaveCount(0);
    await page.waitForTimeout(500);
    expect(be.calls.filter((c) => c === "GET /signals/day").length).toBe(dayCalls);   // an older answer: the day is never asked
  });
});

test.describe("MOCK — not real data: Market Desk › Screener › Scan dashboard · signals by company (DESIGN.md §11.1)", () => {
  const symbols = (page: Page) => page.getByTestId("sd-bc-item").evaluateAll((els) => els.map((e) => e.getAttribute("data-symbol")));

  test("TC-C1 by default every company with a signal today, newest activity first, with counts, score, strong chip and a timeline (6 marks, then 'n more')", async ({ page }) => {
    await desk(page, { answer: () => ({ status: 200, body: dashboard({ strength: true }) }), day: dayOk() });
    await openDashboard(page);
    const panel = page.getByTestId("sd-bycompany");
    await expect(panel).toBeVisible(SLOW);
    await expect(panel.locator("h4")).toHaveText("Signals by company");
    await expect(panel.getByTestId("sd-bc-head")).toHaveText("2026-11-04 · 22 signals · 7 companies · scores as of 14:40");
    expect(await symbols(page)).toEqual(["ZEN", "SAREGAMA", "BETA", "SAKUMA", "ALPHA", "EPSILON", "OILIETF"]);
    await expect(panel.getByTestId("sd-bc-filter-all")).toHaveText("All (7)");
    await expect(panel.getByTestId("sd-bc-filter-all")).toHaveAttribute("aria-pressed", "true");
    await expect(panel.getByTestId("sd-bc-filter-high")).toHaveText("70+ (2)");
    await expect(panel.getByTestId("sd-bc-filter-below")).toHaveText("Below 70 (3)");
    await expect(panel.getByTestId("sd-bc-filter-unscored")).toHaveText("Not scored (2)");
    const sare = panel.locator('[data-testid="sd-bc-item"][data-symbol="SAREGAMA"]');
    await expect(sare.getByTestId("sd-bc-name")).toHaveText("Saregama India Limited");
    await expect(sare.getByTestId("sd-bc-score")).toHaveText("74/100");
    await expect(sare.getByTestId("sd-bc-score")).toHaveAttribute("data-high", "true");
    await expect(sare.getByTestId("sd-bc-strong")).toHaveText("Strong signal 12:47");
    await expect(sare.getByTestId("sd-bc-n")).toHaveText("7 signals · 10:49–13:05");
    await expect(sare.getByTestId("sd-bc-penalty")).toHaveText(["26 % above its 20-day average (chasing) −5"]);
    // collapsed: the first 6 marks and the strong signal at its time; the 7th mark behind "1 more"
    const marks = sare.getByTestId("sd-bc-mark");
    expect(await marks.evaluateAll((els) => els.map((e) => `${e.getAttribute("data-kind")} ${e.getAttribute("data-time")}`))).toEqual([
      "mark 10:49:22", "mark 10:49:22", "mark 12:47:27", "mark 12:47:27", "mark 12:47:27", "mark 12:47:32", "strong 12:47:32"]);
    await expect(marks.first()).toHaveText("10:49:22 · 52 week breakout · ₹575.25");
    await expect(sare.getByTestId("sd-bc-more")).toHaveText("1 more");
    await sare.getByTestId("sd-bc-more").click();
    await expect(marks).toHaveCount(8);
    await expect(marks.last()).toHaveText("13:05:03 · High volume and price breakout stocks · ₹617.60");
    const zen = panel.locator('[data-testid="sd-bc-item"][data-symbol="ZEN"]');
    await expect(zen.getByTestId("sd-bc-mark")).toHaveCount(6);
    await expect(zen.getByTestId("sd-bc-more")).toHaveText("3 more");
    await expect(panel.locator('[data-testid="sd-bc-item"][data-symbol="BETA"] [data-testid="sd-bc-more"]')).toHaveCount(0);
    await expect(panel.locator('[data-testid="sd-bc-item"][data-symbol="EPSILON"] [data-testid="sd-bc-mark"]')).toHaveText("10:12:40 · Open interest 7 · ₹300.00 · falling");
    await expect(panel.locator('[data-testid="sd-bc-item"][data-symbol="BETA"] [data-testid="sd-bc-strong"]')).toHaveCount(0);
    // the symbol opens the chart
    await sare.getByTestId("sd-bc-sym").click();
    await expect.poll(() => params(page).get("sym"), SLOW).toBe("SAREGAMA");
  });

  test("TC-C2 search suggests by symbol and by a word of the name; a keyboard pick shows that company alone with its whole day in time order; × restores all", async ({ page }) => {
    await desk(page, { answer: () => ({ status: 200, body: dashboard({ strength: true }) }), day: dayOk() });
    await openDashboard(page);
    const panel = page.getByTestId("sd-bycompany");
    const box = panel.getByRole("combobox", { name: "Search a company by symbol or name" });
    await expect(box).toBeVisible(SLOW);
    await expect(box).toHaveAttribute("aria-expanded", "false");
    await box.fill("SAR");
    await expect(box).toHaveAttribute("aria-expanded", "true");
    const options = panel.getByTestId("sd-bc-listbox").getByRole("option");
    expect(await options.evaluateAll((els) => els.map((e) => e.getAttribute("data-symbol")))).toEqual(["SAREGAMA"]);
    await expect(options.first()).toContainText("SAREGAMA");
    await expect(options.first()).toContainText("Saregama India Limited");
    await expect(options.first()).toContainText("74");
    expect(await symbols(page)).toEqual(["SAREGAMA"]);                               // typing filters the list as you type
    // a word of the name, any case: "india" → Beta India Industries, Saregama India Limited (symbol order within the same rank)
    await box.fill("india");
    expect(await options.evaluateAll((els) => els.map((e) => e.getAttribute("data-symbol")))).toEqual(["BETA", "SAREGAMA"]);
    await box.fill("mills");
    expect(await options.evaluateAll((els) => els.map((e) => e.getAttribute("data-symbol")))).toEqual(["ZEN"]);
    await box.fill("india");
    await box.press("ArrowDown");
    await box.press("ArrowDown");
    const activeId = await box.getAttribute("aria-activedescendant");
    expect(activeId).toBeTruthy();
    await expect(panel.locator(`[id="${activeId}"]`)).toHaveAttribute("data-symbol", "SAREGAMA");
    await expect(panel.locator(`[id="${activeId}"]`)).toHaveAttribute("aria-selected", "true");
    await box.press("Enter");
    await expect(box).toHaveValue("SAREGAMA");
    await expect(box).toHaveAttribute("aria-expanded", "false");
    expect(await symbols(page)).toEqual(["SAREGAMA"]);
    await expect(panel.getByTestId("sd-bc-filter-all")).toHaveCount(0);              // one company: no filters
    const sare = panel.locator('[data-testid="sd-bc-item"][data-symbol="SAREGAMA"]');
    const marks = sare.getByTestId("sd-bc-mark");
    await expect(marks).toHaveCount(8);                                               // the whole day, no "more"
    const times = await marks.evaluateAll((els) => els.map((e) => e.getAttribute("data-time") ?? ""));
    expect(times).toEqual([...times].sort());
    const strong = sare.locator('[data-testid="sd-bc-mark"][data-kind="strong"]');
    await expect(strong).toContainText("12:47:32 · reached 74 — strong signal");
    await expect(strong.getByTestId("sd-bc-plan")).toHaveText("Entry 614.80 · Stop loss 576.82 · Target 1 690.76 · Target 2 766.72 · R:R 2 / 4");
    await expect(strong.getByTestId("sd-bc-plan")).toHaveAttribute("title", "ATR(14) 18.99 · risk 37.98 a share · rules scan-plan-v3");
    await expect(strong.getByTestId("sd-bc-exit")).toHaveText("Trend exit: A daily close below the 20-day average (₹510.65 on 2026-11-03; it rises as the trend runs)");
    await panel.getByTestId("sd-bc-clear").click();
    await expect(box).toHaveValue("");
    expect(await symbols(page)).toEqual(["ZEN", "SAREGAMA", "BETA", "SAKUMA", "ALPHA", "EPSILON", "OILIETF"]);
    // a search that matches nothing says so; Escape in an empty-result box clears it
    await box.fill("tcs");
    await expect(panel.getByTestId("sd-bc-empty")).toHaveText("No company with a signal today matches “tcs”.");
    await box.press("Escape");
    await expect(box).toHaveValue("");
    await expect(page.getByTestId("sd-bc-item")).toHaveCount(7);
  });

  test("TC-C3 filters (All / 70+ / Below 70 / Not scored) and sorts (Latest / Score / A–Z)", async ({ page }) => {
    await desk(page, { answer: () => ({ status: 200, body: dashboard({ strength: true }) }), day: dayOk() });
    await openDashboard(page);
    const panel = page.getByTestId("sd-bycompany");
    await expect(panel.getByTestId("sd-bc-item").first()).toBeVisible(SLOW);
    await panel.getByTestId("sd-bc-filter-high").click();
    expect(await symbols(page)).toEqual(["SAREGAMA", "ALPHA"]);
    await panel.getByTestId("sd-bc-filter-below").click();
    expect(await symbols(page)).toEqual(["ZEN", "BETA", "SAKUMA"]);
    await panel.getByTestId("sd-bc-filter-unscored").click();
    expect(await symbols(page)).toEqual(["EPSILON", "OILIETF"]);
    await panel.getByTestId("sd-bc-filter-all").click();
    await panel.getByTestId("sd-bc-sort").selectOption("score");
    expect(await symbols(page)).toEqual(["ALPHA", "SAREGAMA", "BETA", "ZEN", "SAKUMA", "EPSILON", "OILIETF"]);
    await panel.getByTestId("sd-bc-sort").selectOption("az");
    expect(await symbols(page)).toEqual(["ALPHA", "BETA", "EPSILON", "OILIETF", "SAKUMA", "SAREGAMA", "ZEN"]);
    // a search narrows the counts too
    await panel.getByTestId("sd-bc-search").fill("india");
    await expect(panel.getByTestId("sd-bc-filter-all")).toHaveText("All (2)");
    await expect(panel.getByTestId("sd-bc-filter-high")).toHaveText("70+ (1)");
    await expect(panel.getByTestId("sd-bc-filter-below")).toHaveText("Below 70 (1)");
  });

  test("TC-C4 a backend without the route (404) or with the feature off (403) shows no panel and the dashboard stands; another failure says so with a retry", async ({ page }) => {
    let status = 404;
    const be = await desk(page, { answer: () => ({ status: 200, body: dashboard({ strength: true }) }),
      day: () => (status === 200 ? { status: 200, body: DAY } : { status, body: { detail: status === 403 ? { code: "feature_disabled", message: "MOCK off" } : "Not Found" } }) });
    await openDashboard(page);
    await expect(page.getByTestId("sd-strong")).toBeVisible();
    await expect.poll(() => be.calls.filter((c) => c === "GET /signals/day").length, SLOW).toBeGreaterThan(0);
    await expect(page.getByTestId("sd-bycompany")).toHaveCount(0);
    await expect(page.locator('[data-testid^="sd-widget-"][data-status]').first()).toBeVisible();
    status = 403;
    await page.reload();
    await expect(page.getByTestId("sd-strong")).toBeVisible(SLOW);
    await expect.poll(() => be.calls.filter((c) => c === "GET /signals/day").length, SLOW).toBeGreaterThan(1);
    await expect(page.getByTestId("sd-bycompany")).toHaveCount(0);
    status = 500;
    await page.reload();
    await expect(page.getByTestId("sd-bc-error")).toBeVisible(SLOW);
    await expect(page.getByTestId("sd-bc-error")).toContainText("could not be read just now");
    await expect(page.getByTestId("sd-strong")).toBeVisible();
    status = 200;
    await page.getByTestId("sd-bc-retry").click();
    await expect(page.getByTestId("sd-bc-item")).toHaveCount(7, SLOW);
  });

  test("TC-C5 with every company's timeline open, no barred word outside the plan blocks (tooltips included)", async ({ page }) => {
    await desk(page, { answer: () => ({ status: 200, body: dashboard({ strength: true }) }), day: dayOk() });
    await openDashboard(page);
    const panel = page.getByTestId("sd-bycompany");
    await expect(panel.getByTestId("sd-bc-item").first()).toBeVisible(SLOW);
    for (let i = 0; i < 50 && (await panel.getByTestId("sd-bc-more").count()) > 0; i++) await panel.getByTestId("sd-bc-more").first().click();
    await expect(panel.getByTestId("sd-bc-more")).toHaveCount(0);
    await panel.getByTestId("sd-bc-search").fill("a");                                       // the suggestion list open too
    await expect(panel.getByTestId("sd-bc-listbox").getByRole("option").first()).toBeVisible();
    const outside = await panel.evaluate((root) => {
      const clone = root.cloneNode(true) as HTMLElement;
      clone.querySelectorAll("[data-plan-words]").forEach((e) => e.remove());
      const titles = Array.from(root.querySelectorAll("[title]")).filter((e) => !e.closest("[data-plan-words]")).map((e) => e.getAttribute("title") ?? "");
      document.body.appendChild(clone);
      const text = clone.innerText;
      clone.remove();
      return { text, titles };
    });
    expect(outside.text).toContain("Signals by company");
    for (const t of [outside.text, ...outside.titles]) expect(t).not.toMatch(BANNED);
    const plans = await panel.locator("[data-plan-words]").evaluateAll((els) => els.map((e) => `${(e as HTMLElement).innerText} ${e.getAttribute("title") ?? ""}`));
    expect(plans.length).toBe(2);                                                       // SAREGAMA's and ALPHA's strong signals
    for (const t of plans) expect(t.replace(/\b(Entry|Stop loss|stop loss|Target 1|Target 2|Trend exit|trend exit)\b/g, "")).not.toMatch(BANNED);
  });

  test("TC-C6 30 companies at a time, then 'Show more'", async ({ page }) => {
    const many = Array.from({ length: 45 }, (_, i) => company({ symbol: `CO${String(i).padStart(2, "0")}`, name: `Company ${i} Limited`, score: 40 + (i % 50),
      marks: [M(`10:${String(i).padStart(2, "0")}:00`, "dt_multiyear", 100 + i)] }));
    await desk(page, { answer: () => ({ status: 200, body: dashboard({ strength: true }) }),
      day: dayOk({ ...DAY, count: 45, companies_count: 45, companies: many }) });
    await openDashboard(page);
    const panel = page.getByTestId("sd-bycompany");
    await expect(panel.getByTestId("sd-bc-item")).toHaveCount(30, SLOW);
    expect((await symbols(page))[0]).toBe("CO44");                                     // newest activity first
    await expect(panel.getByTestId("sd-bc-showmore")).toHaveText("Show 15 more of 15");
    await panel.getByTestId("sd-bc-showmore").click();
    await expect(panel.getByTestId("sd-bc-item")).toHaveCount(45);
    await expect(panel.getByTestId("sd-bc-showmore")).toHaveCount(0);
  });
});

test.describe("MOCK — not real data: Market Desk › Screener › Scan dashboard · two dashboards (Atlas fresh | Day trade)", () => {
  test("TC-DE11a the default tab is Atlas fresh: no dash= in the URL, the request asks atlas, the tab row is an accessible tablist", async ({ page }) => {
    const be = await desk(page, { answer: (_n, dash) => (dash === "daytrade" ? { status: 200, body: dayTrade() } : { status: 200, body: atlas() }) });
    await openDashboard(page);
    const list = page.getByRole("tablist", { name: "Scan dashboards" });
    await expect(list.getByRole("tab")).toHaveText(["Atlas fresh", "Day trade"]);
    await expect(tab(page, "atlas")).toHaveAttribute("aria-selected", "true");
    await expect(tab(page, "daytrade")).toHaveAttribute("aria-selected", "false");
    await expect(tab(page, "atlas")).toHaveAttribute("tabindex", "0");
    await expect(tab(page, "daytrade")).toHaveAttribute("tabindex", "-1");
    await expect(tab(page, "atlas").locator("[title]")).toHaveAttribute("title", "Chartink dashboard 247498");
    await expect(tab(page, "daytrade").locator("[title]")).toHaveAttribute("title", "Chartink dashboard 503347");
    expect(params(page).get("dash")).toBeNull();
    expect(be.asked.length).toBeGreaterThanOrEqual(1);
    for (const a of be.asked) expect([null, "atlas"]).toContain(a);
    await expect(page.getByTestId("scan-dashboard")).toHaveAttribute("data-dashboard", "atlas");
    await expect(titlesOf(page)).toHaveText(ATLAS_TITLES);
  });

  test("TC-DE11b Day trade: dash=daytrade in the URL (tab, view, sub kept), the request asks daytrade, its widgets and statuses render; arrow keys switch back", async ({ page }) => {
    const be = await desk(page);
    await openDashboard(page);
    await tab(page, "daytrade").click();
    await expect.poll(() => params(page).get("dash")).toBe("daytrade");
    expect(params(page).get("tab")).toBe("market");
    expect(params(page).get("view")).toBe("screener");
    expect(params(page).get("sub")).toBe("dashboard");
    await expect(tab(page, "daytrade")).toHaveAttribute("aria-selected", "true");
    await expect(tab(page, "atlas")).toHaveAttribute("aria-selected", "false");
    await expect.poll(() => be.asked[be.asked.length - 1], SLOW).toBe("daytrade");
    await expect(page.getByTestId("scan-dashboard")).toHaveAttribute("data-dashboard", "daytrade", SLOW);
    await expect(page.getByTestId("sd-basis")).toHaveText("MOCK basis — day trade: Kite live 10:15:29 IST over 15-minute candles");
    await expect(titlesOf(page)).toHaveText(DAY_TRADE_TITLES);
    await expect(widget(page, "mcap_ad")).toHaveCount(0);
    // ok with rows (and the strategy idea column)
    const hi = widget(page, "dt_day_high");
    await expect(hi.getByTestId("sd-widget-count")).toHaveText("2 stocks");
    await expect(hi.getByTestId("sd-row").nth(0)).toContainText("830.10");
    await expect(hi.locator('[data-testid="sd-row"][data-key="ALPHA"] [data-testid="sd-idea"]')).toHaveText("Bull call spread · R:R 2.10");
    // not computed: its note, no table, the criterion it cannot apply dimmed
    const y12 = widget(page, "dt_12y_high");
    await expect(y12.getByTestId("sd-widget-status")).toHaveText("Not computed");
    await expect(y12.getByTestId("sd-widget-note")).toHaveText("MOCK note: needs 12 years of daily bars; our history is shorter.");
    await expect(y12.getByTestId("sd-table")).toHaveCount(0);
    await expect(y12.locator('[data-testid="sd-criterion"][data-applied="false"]')).toHaveCount(1);
    // partial: badge, note, rows
    const u3 = widget(page, "dt_under_300");
    await expect(u3.getByTestId("sd-widget-status")).toHaveText("Partial");
    await expect(u3.getByTestId("sd-widget-note")).toHaveText("MOCK note: the 200-week line is not applied yet.");
    await expect(u3.getByTestId("sd-row")).toHaveCount(1);
    // empty by definition: its note says why, then "No stock passes right now."
    const mo = widget(page, "dt_momentum");
    await expect(mo.getByTestId("sd-widget-note")).toHaveText("MOCK note: always empty by definition — its two conditions can never hold together.");
    await expect(mo.getByTestId("sd-widget-empty")).toHaveText("No stock passes right now.");
    // the owner's wording rule holds on this tab too
    const panel = page.getByTestId("desk-panel-scandashboard");
    const tips = await panel.locator("[title]").evaluateAll((els) => els.filter((e) => !e.closest("[data-plan-words]")).map((e) => e.getAttribute("title") ?? ""));
    // The owner's plan words (Entry · Stop loss · Target 1 · Target 2) are allowed only inside [data-plan-words] (the signals' plans).
    for (const t of [await page.getByTestId("md-head").innerText(), await textOutsidePlan(page, "desk-panel-scandashboard"), ...tips]) expect(t).not.toMatch(BANNED);
    // keyboard: ArrowLeft from Day trade opens Atlas fresh, focus follows, dash= leaves the URL
    await tab(page, "daytrade").focus();
    await page.keyboard.press("ArrowLeft");
    await expect(tab(page, "atlas")).toHaveAttribute("aria-selected", "true");
    await expect(tab(page, "atlas")).toBeFocused();
    await expect.poll(() => params(page).get("dash")).toBeNull();
    expect(params(page).get("sub")).toBe("dashboard");
    await expect(titlesOf(page)).toHaveText(ATLAS_TITLES, SLOW);
    // ArrowRight goes to Day trade again
    await page.keyboard.press("ArrowRight");
    await expect(tab(page, "daytrade")).toHaveAttribute("aria-selected", "true");
    await expect.poll(() => params(page).get("dash")).toBe("daytrade");
  });

  test("TC-DE11c a link or a reload with dash=daytrade opens Day trade and never asks atlas", async ({ page }) => {
    const be = await desk(page);
    await openDashboard(page, `${DASH}&dash=daytrade`);
    await expect(tab(page, "daytrade")).toHaveAttribute("aria-selected", "true");
    await expect(titlesOf(page)).toHaveText(DAY_TRADE_TITLES);
    await page.reload();
    await expect(page.getByTestId("scan-dashboard")).toHaveAttribute("data-dashboard", "daytrade", SLOW);
    await expect(tab(page, "daytrade")).toHaveAttribute("aria-selected", "true");
    await expect(titlesOf(page)).toHaveText(DAY_TRADE_TITLES);
    expect(params(page).get("dash")).toBe("daytrade");
    expect(be.asked.length).toBeGreaterThanOrEqual(2);
    for (const a of be.asked) expect(a).toBe("daytrade");
  });

  test("TC-DE11d guard: an answer for atlas when daytrade was asked shows 'not available on the server yet' and none of its widgets", async ({ page }) => {
    // MOCK — a backend that answers atlas (with dashboard.key "atlas") whatever it is asked
    const be = await desk(page, { answer: () => ({ status: 200, body: atlas() }) });
    await page.goto(`${DASH}&dash=daytrade`);
    const un = page.getByTestId("sd-unavailable");
    await expect(un).toBeVisible(SLOW);
    await expect(un).toContainText("This dashboard is not available on the server yet.");
    await expect(un).toHaveAttribute("data-asked", "daytrade");
    await expect(un).toHaveAttribute("data-served", "atlas");
    expect(be.asked).toContain("daytrade");
    await expect(page.getByTestId("scan-dashboard")).toHaveCount(0);
    await expect(page.locator('[data-testid^="sd-widget-"][data-status]')).toHaveCount(0);
    for (const t of ATLAS_TITLES) await expect(page.getByText(t, { exact: true })).toHaveCount(0);
    await expect(tab(page, "daytrade")).toHaveAttribute("aria-selected", "true");
    expect(await textOutsidePlan(page, "desk-panel-scandashboard")).not.toMatch(BANNED);
    // asking again asks daytrade again, and still shows nothing of atlas
    const before = be.asked.length;
    await page.getByTestId("sd-unavailable-retry").click();
    await expect.poll(() => be.asked.length, SLOW).toBeGreaterThan(before);
    expect(be.asked[be.asked.length - 1]).toBe("daytrade");
    await expect(page.getByTestId("sd-unavailable")).toBeVisible();
    // the Atlas tab draws that same answer, since it is for atlas
    await tab(page, "atlas").click();
    await expect(page.getByTestId("scan-dashboard")).toHaveAttribute("data-dashboard", "atlas", SLOW);
    await expect(titlesOf(page)).toHaveText(ATLAS_TITLES);
  });

  test("TC-DE11e guard, older backend: no `dashboard` field — Atlas fresh renders as before, Day trade says not available", async ({ page }) => {
    // MOCK — an older backend: ignores ?dashboard= and answers 247498 without the new fields
    await desk(page, { answer: () => ({ status: 200, body: dashboard() }) });
    await openDashboard(page);
    await expect(titlesOf(page)).toHaveText(ATLAS_TITLES);
    await expect(page.getByRole("tablist", { name: "Scan dashboards" }).getByRole("tab")).toHaveText(["Atlas fresh", "Day trade"]);   // the static pair
    await tab(page, "daytrade").click();
    await expect(page.getByTestId("sd-unavailable")).toBeVisible(SLOW);
    await expect(page.getByTestId("sd-unavailable")).toHaveAttribute("data-served", "atlas");
    await expect(page.locator('[data-testid^="sd-widget-"][data-status]')).toHaveCount(0);
  });

  test("TC-DE11f the 10 s refresh asks only the open dashboard", async ({ page }) => {
    await page.clock.install({ time: new Date("2026-11-03T04:45:00Z") });
    const be = await desk(page, { answer: (n, dash) => (dash === "daytrade" ? { status: 200, body: dayTrade({ bump: n }) } : { status: 200, body: atlas({ bump: n }) }) });
    await openDashboard(page, `${DASH}&dash=daytrade`);
    await expect(page.getByTestId("sd-live-chip")).toHaveAttribute("data-state", "live");
    const n0 = be.asked.length;
    await page.clock.runFor(10_500);
    await expect.poll(() => be.asked.length, SLOW).toBe(n0 + 1);
    await page.clock.runFor(10_500);
    await expect.poll(() => be.asked.length, SLOW).toBe(n0 + 2);
    for (const a of be.asked) expect(a).toBe("daytrade");
    await expect(widget(page, "dt_day_high").getByTestId("sd-row").nth(0)).toContainText(`${(830.1 + n0 + 2).toFixed(2)}`, SLOW);
    // switch: from now on only atlas is asked
    await tab(page, "atlas").click();
    await expect(page.getByTestId("scan-dashboard")).toHaveAttribute("data-dashboard", "atlas", SLOW);
    const n1 = be.asked.length;
    await page.clock.runFor(10_500);
    await expect.poll(() => be.asked.length, SLOW).toBe(n1 + 1);
    await page.clock.runFor(10_500);
    await expect.poll(() => be.asked.length, SLOW).toBe(n1 + 2);
    for (const a of be.asked.slice(n1 - 1)) expect(a).toBe("atlas");
  });

  test("TC-DE11g an unknown dash= is asked as is; the server's 422 unknown_dashboard says so, with no Retry, and the tabs stay", async ({ page }) => {
    const be = await desk(page);
    await page.goto(`${DASH}&dash=nope`);
    const err = page.getByTestId("sd-error");
    await expect(err).toHaveAttribute("data-code", "unknown_dashboard", SLOW);
    await expect(err).toContainText("This dashboard is not available on the server");
    await expect(err.getByRole("button", { name: /Retry/ })).toHaveCount(0);
    expect(be.asked).toEqual(["nope"]);
    await tab(page, "daytrade").click();
    await expect(titlesOf(page)).toHaveText(DAY_TRADE_TITLES, SLOW);
  });

  test("TC-DE11h a tab or view change drops dash=", async ({ page }) => {
    await desk(page);
    await openDashboard(page, `${DASH}&dash=daytrade`);
    await page.getByTestId("desk-sub-builder").click();
    await expect.poll(() => params(page).get("sub")).toBe("builder");
    expect(params(page).get("dash")).toBeNull();
  });
});

test.describe("MOCK — not real data: Market Desk › Screener › Scan dashboard · phone 390px", () => {
  test.use({ viewport: { width: 390, height: 844 } });

  test("TC-DE8 one card per row, no sideways page scroll; a wide table scrolls inside its card", async ({ page }) => {
    await desk(page);
    await openDashboard(page);
    const o = await page.evaluate(() => {
      const sc = document.querySelector('[data-testid="copilot-scroll"]') as HTMLElement | null;
      const cards = Array.from(document.querySelectorAll('[data-testid^="sd-widget-"][data-status]')) as HTMLElement[];
      const lefts = new Set(cards.map((c) => Math.round(c.getBoundingClientRect().left)));
      return {
        doc: document.documentElement.scrollWidth - window.innerWidth,
        scroll: sc ? sc.scrollWidth - sc.clientWidth : 0,
        columns: lefts.size,
        cards: cards.length,
      };
    });
    expect(o.cards).toBe(8);
    expect(o.columns).toBe(1);
    expect(o.doc).toBeLessThanOrEqual(1);
    expect(o.scroll).toBeLessThanOrEqual(1);
  });

  test("TC-DE11i the dashboard tabs fit a phone: both visible, Day trade opens, no sideways page scroll", async ({ page }) => {
    await desk(page);
    await openDashboard(page);
    for (const k of ["atlas", "daytrade"]) {
      await expect(tab(page, k)).toBeVisible();
      const b = await tab(page, k).boundingBox();
      expect(b).not.toBeNull();
      expect(b!.x).toBeGreaterThanOrEqual(0);
      expect(b!.x + b!.width).toBeLessThanOrEqual(390);
    }
    await tab(page, "daytrade").click();
    await expect(titlesOf(page)).toHaveText(DAY_TRADE_TITLES, SLOW);
    const o = await page.evaluate(() => {
      const sc = document.querySelector('[data-testid="copilot-scroll"]') as HTMLElement | null;
      return { doc: document.documentElement.scrollWidth - window.innerWidth, scroll: sc ? sc.scrollWidth - sc.clientWidth : 0 };
    });
    expect(o.doc).toBeLessThanOrEqual(1);
    expect(o.scroll).toBeLessThanOrEqual(1);
  });
});


// ── REAL snapshot replayed (not a hand-made fixture) ─────────────────────────────────────────────────────────────────
// e2e/fixtures/scan-dashboard-real/dashboard_20261103_close.json is the backend's own answer, computed in the staging backend
// container on 3 Nov 2026 after the close (Kite close over NSE end-of-day bars, signals recorded as if each listed stock had just
// appeared, strategy ideas for 12 stocks). Only the transport is mocked: this checks the page against what the backend really sends.
test.describe("REAL snapshot (staging, 3 Nov 2026 close) replayed: Scan dashboard", () => {
  const real = JSON.parse(fs.readFileSync(path.join(__dirname, "../fixtures/scan-dashboard-real/dashboard_20261103_close.json"), "utf8"));

  test("TC-RE1 the real answer renders: 17 cards, the signals feed with plans, ideas, no page error, no barred words", async ({ page }) => {
    const errors: string[] = [];
    page.on("pageerror", (e) => errors.push(e.message));
    await desk(page, { answer: () => ({ status: 200, body: real }) });
    await openDashboard(page);
    await expect(page.locator('[data-testid^="sd-widget-"][data-status]')).toHaveCount(17, SLOW);
    await expect(page.getByTestId("sd-signals")).toBeVisible();
    const n = real.signals.length as number;
    await expect(page.getByTestId("sd-signals-count")).toContainText(String(n));
    await expect(page.getByTestId("sd-signal")).toHaveCount(20);
    await page.getByTestId("sd-signals-toggle").click();
    await expect(page.getByTestId("sd-signal")).toHaveCount(n);
    const withPlan = page.locator('[data-testid="sd-signal"][data-plan="true"]').first();
    await expect(withPlan).toContainText("Entry");
    await expect(withPlan).toContainText("Stop loss");
    await expect(withPlan).toContainText("Target 1");
    await expect(page.locator('[data-testid="sd-signal"][data-plan="false"]').first()).toContainText("no plan is shown");
    await expect(page.getByTestId("sd-ideas-count")).toContainText(`${real.ideas_meta.built} of`);
    expect(await page.locator('[data-testid="sd-idea"][data-state="idea"]').count()).toBeGreaterThan(0);
    const outsidePlan = await page.evaluate(() => {
      const root = document.querySelector('[data-testid="scan-dashboard"]') as HTMLElement;
      const clone = root.cloneNode(true) as HTMLElement;
      clone.querySelectorAll("[data-plan-words]").forEach((el) => el.remove());
      return clone.innerText;
    });
    expect(outsidePlan).not.toMatch(/\b(buy\w*|sell\w*|target\w*|stop ?loss|recommend\w*|picks?)\b/i);
    expect(errors).toEqual([]);
  });
});

// ── REAL signal strength (4 Nov 2026, live) replayed ─────────────────────────────────────────────────────────────────
// e2e/fixtures/scan-dashboard-real/dashboard_20261104_scores.json: the widgets are the 3 Nov close answer above; signals,
// scores, strong signals and scores_meta are REAL — today's 300 list marks scored at 14:15 IST in the staging backend container
// by the branch's signal_strength.py (live Kite prices, screener fundamentals, snapshot, exchange filings), shaped as the
// branch's market_dashboard sends them. Only the transport is mocked: this checks the page against real reason and penalty texts.
test.describe("REAL signal strength (staging, 4 Nov 2026 14:15 IST) replayed: Scan dashboard", () => {
  const real = JSON.parse(fs.readFileSync(path.join(__dirname, "../fixtures/scan-dashboard-real/dashboard_20261104_scores.json"), "utf8"));

  test("TC-RE2 real scores render: strong cards with plans, every company in Signals by company (Below 70 filter), no page error, no barred words outside plans", async ({ page }) => {
    const errors: string[] = [];
    page.on("pageerror", (e) => errors.push(e.message));
    // The day endpoint's real answer was not captured; its answer here is grouped IN THE TEST (dayFrom) from this same fixture's
    // real signals, scores and strong signals, so the texts on screen are the real ones.
    const day = dayFrom(real);
    await desk(page, { answer: () => ({ status: 200, body: real }), day: () => ({ status: 200, body: day }) });
    await openDashboard(page);
    await expect(page.getByTestId("sd-strong")).toBeVisible(SLOW);
    const strongN = real.strong.length as number;
    expect(strongN).toBeGreaterThan(0);
    await expect(page.getByTestId("sd-strong-count")).toContainText(String(strongN));
    const sare = real.strong.find((s: { symbol: string }) => s.symbol === "SAREGAMA");
    if (sare) {
      const card = page.locator('[data-testid="sd-strong-item"][data-symbol="SAREGAMA"]');
      if ((await card.count()) === 0) await page.getByTestId("sd-strong-toggle").click();
      await expect(card).toContainText(`${sare.score_at}/100`);
      await expect(card.getByTestId("sd-strong-plan")).toContainText("Stop loss");
      await expect(card.getByTestId("sd-strong-exit")).toContainText("20-day average");
    }
    await expect(page.getByTestId("sd-below-toggle")).toHaveCount(0);
    const panel = page.getByTestId("sd-bycompany");
    await expect(panel).toBeVisible(SLOW);
    const scored = Object.values(real.scores) as { score: number | null }[];
    const belowN = scored.filter((s) => typeof s.score === "number" && s.score < 70).length;
    await expect(panel.getByTestId("sd-bc-filter-all")).toHaveText(`All (${day.companies.length.toLocaleString("en-IN")})`);
    await expect(panel.getByTestId("sd-bc-filter-below")).toHaveText(`Below 70 (${belowN.toLocaleString("en-IN")})`);
    await panel.getByTestId("sd-bc-filter-below").click();
    await expect(panel.getByTestId("sd-bc-item")).toHaveCount(Math.min(30, belowN));
    await expect(panel.getByTestId("sd-bc-list").locator("[data-plan-words]")).toHaveCount(0);
    if (sare) {
      await panel.getByTestId("sd-bc-search").fill("SAREGAMA");
      await panel.getByTestId("sd-bc-search").press("Enter");
      const one = panel.locator('[data-testid="sd-bc-item"][data-symbol="SAREGAMA"]');
      await expect(one.locator('[data-testid="sd-bc-mark"][data-kind="strong"]')).toContainText(`reached ${sare.score_at}`);
      const times = await one.getByTestId("sd-bc-mark").evaluateAll((els) => els.map((e) => e.getAttribute("data-time") ?? ""));
      expect(times).toEqual([...times].sort());
      await panel.getByTestId("sd-bc-clear").click();
    }
    for (let i = 0; i < 50 && (await panel.getByTestId("sd-bc-more").count()) > 0; i++) await panel.getByTestId("sd-bc-more").first().click();
    const outsidePlan = await page.evaluate(() => {
      const root = document.querySelector('[data-testid="scan-dashboard"]') as HTMLElement;
      const clone = root.cloneNode(true) as HTMLElement;
      clone.querySelectorAll("[data-plan-words]").forEach((el) => el.remove());
      return clone.innerText;
    });
    expect(outsidePlan).not.toMatch(BANNED);
    expect(errors).toEqual([]);
  });
});

// ── REAL day answer (GET /signals/day, 4 Nov 2026 14:51 IST) replayed ────────────────────────────────────────────────
// e2e/fixtures/scan-dashboard-real/day_20261104.json is the branch backend's own day answer, built in the staging backend container
// from today's REAL 2,148 list marks (signals.day_view over an in-memory copy of the marks and the scores the leader stores;
// the branch's signal_strength.py on live Kite prices). The dashboard answer is the 4 Nov scores fixture above. Only the
// transport is mocked.
test.describe("REAL day answer (staging, 4 Nov 2026 14:51 IST) replayed: Signals by company", () => {
  const real = JSON.parse(fs.readFileSync(path.join(__dirname, "../fixtures/scan-dashboard-real/dashboard_20261104_scores.json"), "utf8"));
  const day = JSON.parse(fs.readFileSync(path.join(__dirname, "../fixtures/scan-dashboard-real/day_20261104.json"), "utf8"));

  test("TC-RE3 the real day: counts, 30 shown, search finds SAREGAMA by symbol and name, its real timeline in time order, no barred words", async ({ page }) => {
    const errors: string[] = [];
    page.on("pageerror", (e) => errors.push(e.message));
    type Co = { symbol: string; name: string; score: number | null; marks: { time: string }[] };
    const companies = day.companies as Co[];
    expect(companies.length).toBeGreaterThan(500);
    await desk(page, { answer: () => ({ status: 200, body: real }), day: () => ({ status: 200, body: day }) });
    await openDashboard(page);
    const head = page.getByTestId("sd-bc-head");
    await expect(head).toContainText(`${(day.count as number).toLocaleString("en-IN")} signals`, SLOW);
    await expect(head).toContainText(`${companies.length.toLocaleString("en-IN")} companies`);
    await expect(page.getByTestId("sd-bc-item")).toHaveCount(30);
    const high = companies.filter((c) => typeof c.score === "number" && c.score >= 70).length;
    await expect(page.getByTestId("sd-bc-filter-high")).toContainText(String(high));
    const sare = companies.find((c) => c.symbol === "SAREGAMA");
    expect(sare).toBeTruthy();
    for (const q of ["SAREG", "saregama india"]) {
      await page.getByTestId("sd-bc-search").fill(q);
      await expect(page.getByTestId("sd-bc-option").filter({ hasText: "SAREGAMA" })).toHaveCount(1);
    }
    await page.getByTestId("sd-bc-option").filter({ hasText: "SAREGAMA" }).click();
    const card = page.getByTestId("sd-bc-item");
    await expect(card).toHaveCount(1);
    await expect(card).toHaveAttribute("data-symbol", "SAREGAMA");
    const more = card.getByTestId("sd-bc-more");
    if (await more.count()) await more.first().click();
    const times = await card.locator('[data-testid="sd-bc-mark"][data-kind="mark"]').evaluateAll((els) => els.map((e) => (e as HTMLElement).dataset.time));
    expect(times).toEqual(sare!.marks.map((m) => m.time));
    expect(times[0]).toBe(sare!.marks[0].time);
    await page.getByTestId("sd-bc-clear").click();
    await expect(page.getByTestId("sd-bc-item")).toHaveCount(30);
    const outsidePlan = await page.evaluate(() => {
      const root = document.querySelector('[data-testid="scan-dashboard"]') as HTMLElement;
      const clone = root.cloneNode(true) as HTMLElement;
      clone.querySelectorAll("[data-plan-words]").forEach((el) => el.remove());
      return clone.innerText;
    });
    expect(outsidePlan).not.toMatch(BANNED);
    expect(errors).toEqual([]);
  });
});
