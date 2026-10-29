/**
 * Chart Analysis v2 — the basket's pure logic (test_reports/chart_analysis_v2_TESTCASES.md, "Right:" and "Below:").
 *
 *   presets          Long straddle · Bull call spread · Bear put spread · Short strangle · Iron condor, as legs at the
 *                    chain's own strikes and end-of-day closes (the strike offsets of FnoBuilder.TEMPLATES, so the desk
 *                    builds a structure the same way everywhere; short strangle is long strangle's offsets sold)
 *   ADD Cash/Future  the leg for the underlying's LAST and for the future of the chain's expiry (else the near month)
 *   bodies           POST /api/desk/strategy/payoff, POST /api/fno/margin, POST /api/desk/paper-trades (kind "strategy",
 *                    and the share trade for a cash-only basket), built from the basket exactly as the routes take them
 *
 * Nothing here works out a payoff, Greek, margin or P&L figure: those come from the routes (basket-routes.ts). The only
 * readings made here are the family name of a structure, the direction from the payoff route's own position delta, and
 * whether a stop / target lies on the side of the reference the paper route requires. No hook and no fetch, so the
 * Playwright spec checks these bodies directly (only type imports besides ./basket).
 */
import { isOption, toRouteLeg, type BasketLeg, type BasketLevels, type NewLeg } from "./basket";
import type { AnalysisChain, StrikeRow } from "./chain-data";
import type { PayoffRequest } from "../../../strategy/strategy-contract";
import type { EntryRule, NewPaperTrade, NewStrategyPaperTrade, StrategyDirection } from "../../../desk-trading";

/** The signal's rule version and the share trade's strategy_version: this screen. */
export const RULE_VERSION = "chart-analysis-v2";

// ── small pure helpers ───────────────────────────────────────────────────

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** "2026-11-25" → "25 Nov" (the design's leg labels). */
export function fmtExpiry(iso: string): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso);
  return m ? `${Number(m[3])} ${MONTHS[Number(m[2]) - 1] ?? m[2]}` : iso;
}

/** The IST calendar day (YYYY-MM-DD) of an ISO time or date; a bare date is returned as it is. */
export function istDay(at: string | Date): string | null {
  if (typeof at === "string" && /^\d{4}-\d{2}-\d{2}$/.test(at)) return at;
  const t = typeof at === "string" ? Date.parse(at) : at.getTime();
  return Number.isFinite(t) ? new Date(t + 5.5 * 3600_000).toISOString().slice(0, 10) : null;
}

/** Today in IST, YYYY-MM-DD. */
export const istToday = (now: Date = new Date()): string => istDay(now) as string;

const CONTROL = /[\u0000-\u001f\u007f]+/g;
/** The routes refuse control characters and over-long text. */
export const clip = (s: string, n: number): string => {
  const t = s.replace(CONTROL, " ").replace(/\s+/g, " ").trim();
  return t.length > n ? `${t.slice(0, n - 1)}…` : t;
};

const inr = (n: number, digits = 2) => `₹${new Intl.NumberFormat("en-IN", { minimumFractionDigits: digits, maximumFractionDigits: digits }).format(n)}`;
const num = (n: number, digits = 2) => new Intl.NumberFormat("en-IN", { maximumFractionDigits: digits }).format(n);

export const units = (l: Pick<BasketLeg, "qty" | "lotSize">) => l.qty * l.lotSize;

/** The FUT / CASH legs (the chart draws their entry, stop and target lines). */
export function underlyingLegs(legs: BasketLeg[]): BasketLeg[] {
  return legs.filter((l) => l.kind === "FUT" || l.kind === "CASH");
}

export const onlyUnderlying = (legs: BasketLeg[]) => legs.length > 0 && legs.every((l) => l.kind === "FUT" || l.kind === "CASH");
export const cashOnly = (legs: BasketLeg[]) => legs.length > 0 && legs.every((l) => l.kind === "CASH");

/** A stable signature of the basket's contracts, sides and sizes (a shown answer belongs to one basket). */
export function basketSignature(symbol: string, legs: BasketLeg[], levels: BasketLevels): string {
  return JSON.stringify([symbol, legs.map((l) => [l.kind, l.side, l.qty, l.strike, l.expiry, l.entry]), levels.stop, levels.target, levels.cashEntry]);
}

// ── presets ──────────────────────────────────────────────────────────────

export type PresetKey = "long_straddle" | "bull_call_spread" | "bear_put_spread" | "short_strangle" | "iron_condor";

interface PresetSpec { s: "B" | "S"; t: "CE" | "PE"; k: number }

export interface Preset {
  key: PresetKey;
  name: string;
  /** Strikes as steps from the ATM strike (FnoBuilder.TEMPLATES: spreads 2 steps wide, the condor's wings 4). */
  legs: PresetSpec[];
  /** Shown beside the preset (short strangle: the paper engine refuses it). */
  warning: string | null;
}

export const PRESETS: readonly Preset[] = [
  { key: "long_straddle", name: "Long straddle", legs: [{ s: "B", t: "CE", k: 0 }, { s: "B", t: "PE", k: 0 }], warning: null },
  { key: "bull_call_spread", name: "Bull call spread", legs: [{ s: "B", t: "CE", k: 0 }, { s: "S", t: "CE", k: 2 }], warning: null },
  { key: "bear_put_spread", name: "Bear put spread", legs: [{ s: "B", t: "PE", k: 0 }, { s: "S", t: "PE", k: -2 }], warning: null },
  { key: "short_strangle", name: "Short strangle", legs: [{ s: "S", t: "CE", k: 2 }, { s: "S", t: "PE", k: -2 }],
    warning: "Unlimited loss: the paper engine refuses it (unbounded loss, naked short put)." },
  { key: "iron_condor", name: "Iron condor", legs: [{ s: "S", t: "CE", k: 2 }, { s: "B", t: "CE", k: 4 }, { s: "S", t: "PE", k: -2 }, { s: "B", t: "PE", k: -4 }], warning: null },
];

export type Built = { ok: true; legs: NewLeg[] } | { ok: false; why: string };

/** Why the chain cannot price an option leg right now, or null. */
export function chainProblem(chain: AnalysisChain | null, notFno: string | null): string | null {
  if (notFno) return notFno;
  if (!chain) return "The option chain has not loaded.";
  if (!chain.tradable || !chain.expiry) return "Consolidated sums open interest over expiries and has no prices: pick Current, Next or Far to add legs.";
  if (chain.lotSize == null) return "The chain sent no lot size, so a leg's quantity is unknown.";
  return null;
}

const sideOf = (row: StrikeRow, t: "CE" | "PE") => (t === "CE" ? row.call : row.put);

/** The preset's legs at the chain's strikes and closes; refused with the reason when a strike or a close is missing. */
export function presetLegs(p: Preset, chain: AnalysisChain | null, notFno: string | null = null): Built {
  const problem = chainProblem(chain, notFno);
  if (problem || !chain || !chain.expiry || chain.lotSize == null) return { ok: false, why: problem ?? "The chain cannot price legs." };
  if (chain.atm == null) return { ok: false, why: `The chain for ${chain.expiry} has no ATM strike (no spot on ${chain.asOf}).` };
  const at = chain.rows.findIndex((r) => r.strike === chain.atm);
  if (at < 0) return { ok: false, why: `The ATM strike ${chain.atm} is not among the strikes the chain sent.` };
  const legs: NewLeg[] = [];
  for (const spec of p.legs) {
    const row = chain.rows[at + spec.k];
    if (!row) {
      const steps = Math.abs(spec.k);
      return { ok: false, why: `The chain has no strike ${steps} step${steps === 1 ? "" : "s"} ${spec.k > 0 ? "above" : "below"} the ATM strike ${chain.atm}.` };
    }
    const close = sideOf(row, spec.t)?.close ?? null;
    if (close == null || !(close > 0)) return { ok: false, why: `${row.strike} ${spec.t} has no close on ${chain.asOf}, so it cannot be priced.` };
    legs.push({
      kind: spec.t, side: spec.s, qty: 1, strike: row.strike, expiry: chain.expiry, entry: close,
      priceSource: `NSE F&O bhavcopy close, ${chain.asOf}`, lotSize: chain.lotSize,
    });
  }
  return { ok: true, legs };
}

/** One future as GET /api/fno/{sym}/futures sends it (trading/fno.ts FnoFuture), with the file's day. */
export interface FutureRow { expiry: string; close: number | null; settle: number | null }

/** ＋ Future: the future expiring with the chain shown (the payoff route takes one expiry for every F&O leg), else the
 *  nearest still to come; priced at its close (its settle when it has no close, and the source says which). */
export function futureLeg(futures: FutureRow[], asOf: string, chain: AnalysisChain | null, notFno: string | null = null): Built {
  if (notFno) return { ok: false, why: notFno };
  const lot = chain?.tradable ? chain.lotSize : null;
  if (lot == null) return { ok: false, why: chain && !chain.tradable ? "Pick Current, Next or Far: the lot size comes from that expiry's chain." : "The lot size is not known yet (the option chain has not loaded)." };
  const ahead = futures.filter((f) => f.expiry > asOf).sort((a, b) => a.expiry.localeCompare(b.expiry));
  const f = (chain?.expiry ? futures.find((x) => x.expiry === chain.expiry) : undefined) ?? ahead[0];
  if (!f) return { ok: false, why: `No future still to come is listed on ${asOf}.` };
  const close = f.close != null && f.close > 0 ? f.close : null;
  const settle = f.settle != null && f.settle > 0 ? f.settle : null;
  const price = close ?? settle;
  if (price == null) return { ok: false, why: `The ${fmtExpiry(f.expiry)} future has no close or settle price on ${asOf}.` };
  return {
    ok: true,
    legs: [{ kind: "FUT", side: "B", qty: 1, strike: null, expiry: f.expiry, entry: price, lotSize: lot,
      priceSource: `NSE F&O bhavcopy ${close != null ? "close" : "settle price"}, ${asOf}` }],
  };
}

/** ＋ Cash: shares at the underlying's LAST, a lot's worth when the lot size is known. */
export function cashLeg(last: { price: number; at: string; source: string }, lotSize: number | null): NewLeg {
  return {
    kind: "CASH", side: "B", qty: lotSize != null && lotSize >= 1 ? lotSize : 1, strike: null, expiry: null, entry: last.price, lotSize: 1,
    priceSource: clip(`${last.source}, ${last.at}`, 200),
  };
}

// ── what the structure is (the paper route's `family`) ────────────────────

/** The paper route's family for the legs (services/desk_strategy_trades.FAMILIES), read from their shape; "custom" when it
 *  is none of them (the route still risk-checks a custom structure). */
export function familyOf(legs: BasketLeg[]): string {
  const opts = legs.filter(isOption).slice().sort((a, b) => (a.strike ?? 0) - (b.strike ?? 0));
  const und = legs.filter((l) => !isOption(l));
  const same = (xs: BasketLeg[]) => xs.every((l) => units(l) === units(xs[0]));
  const is = (l: BasketLeg | undefined, side: "B" | "S", kind: BasketLeg["kind"]) => !!l && l.side === side && l.kind === kind;
  if (!opts.length) {
    if (und.length === 1 && und[0].kind === "FUT") return und[0].side === "B" ? "long_future" : "short_future";
    return "custom";
  }
  if (!und.length) {
    if (opts.length === 1) return is(opts[0], "B", "CE") ? "long_call" : is(opts[0], "B", "PE") ? "long_put" : "custom";
    if (!same(opts)) return "custom";
    if (opts.length === 2) {
      const [a, b] = opts;
      if (a.kind === "CE" && b.kind === "CE" && a.strike !== b.strike) return a.side === "B" && b.side === "S" ? "bull_call_spread" : a.side === "S" && b.side === "B" ? "bear_call_spread" : "custom";
      if (a.kind === "PE" && b.kind === "PE" && a.strike !== b.strike) return a.side === "S" && b.side === "B" ? "bear_put_spread" : a.side === "B" && b.side === "S" ? "bull_put_spread" : "custom";
      const ce = opts.find((l) => l.kind === "CE");
      const pe = opts.find((l) => l.kind === "PE");
      if (ce && pe && ce.side === "B" && pe.side === "B") return ce.strike === pe.strike ? "long_straddle" : (ce.strike ?? 0) > (pe.strike ?? 0) ? "long_strangle" : "custom";
      return "custom";
    }
    if (opts.length === 4) {
      const [p1, p2, c1, c2] = opts;
      if (is(p1, "B", "PE") && is(p2, "S", "PE") && is(c1, "S", "CE") && is(c2, "B", "CE")) return p2.strike === c1.strike ? "iron_butterfly" : "iron_condor";
    }
    return "custom";
  }
  if (und.length === 1 && und[0].side === "B" && same([und[0], ...opts])) {
    const u = und[0];
    const sc = opts.filter((l) => is(l, "S", "CE"));
    const bp = opts.filter((l) => is(l, "B", "PE"));
    if (opts.length === 1 && sc.length === 1 && u.kind === "CASH") return "covered_call";
    if (opts.length === 1 && bp.length === 1) return u.kind === "CASH" ? "protective_put" : "hedged_future";
    if (opts.length === 2 && sc.length === 1 && bp.length === 1 && u.kind === "CASH") return "collar";
  }
  return "custom";
}

// ── the direction the paper trade records ────────────────────────────────

export type DirectionReading = { direction: StrategyDirection; why: string } | { direction: null; why: string };

/** From the payoff route's POSITION delta (pre_expiry.greeks.delta, shares-equivalent at the reference price): above zero
 *  bullish, below bearish, and neutral when its size is under 10% of the largest leg's units. The largest leg, not the sum
 *  of every leg: a 2-leg spread's units double while its delta does not, so 10% of the total would read an ordinary bull
 *  call spread as neutral. */
export function directionOf(delta: number | null | undefined, legs: BasketLeg[]): DirectionReading {
  if (delta == null || !Number.isFinite(delta)) return { direction: null, why: "The payoff route sent no position delta, so the direction cannot be read." };
  if (!legs.length) return { direction: null, why: "The basket is empty." };
  const largest = Math.max(...legs.map(units));
  const d = `${delta > 0 ? "+" : delta < 0 ? "−" : ""}${num(Math.abs(delta), 2)}`;
  if (Math.abs(delta) < 0.1 * largest) {
    return { direction: "neutral", why: `Position delta ${d} (payoff route) is within 10% of the largest leg's ${num(largest, 0)} units: recorded as neutral, with no stop or target.` };
  }
  return delta > 0
    ? { direction: "bullish", why: `Position delta ${d} (payoff route): the position gains as the stock rises, so it is recorded as bullish.` }
    : { direction: "bearish", why: `Position delta ${d} (payoff route): the position gains as the stock falls, so it is recorded as bearish.` };
}

/** The underlying stop and target the paper route takes for the direction, and what is wrong with them (each must lie on
 *  the loss / profit side of the reference). A neutral position sends none. */
export function levelsFor(direction: StrategyDirection, reference: number, levels: Pick<BasketLevels, "stop" | "target">):
  { stop_underlying?: number; target_underlying?: number; problems: string[]; dropped: string | null } {
  const problems: string[] = [];
  if (direction === "neutral") {
    const any = levels.stop != null || levels.target != null;
    return { problems, dropped: any ? "A neutral position records no stop or target on the underlying, so the levels set are not sent." : null };
  }
  const up = direction === "bullish";
  const out: { stop_underlying?: number; target_underlying?: number; problems: string[]; dropped: string | null } = { problems, dropped: null };
  if (levels.stop != null) {
    if (up ? levels.stop < reference : levels.stop > reference) out.stop_underlying = levels.stop;
    else problems.push(`For a ${direction} position the stop (${inr(levels.stop, 1)}) must be ${up ? "below" : "above"} the reference ${inr(reference, 1)}.`);
  }
  if (levels.target != null) {
    if (up ? levels.target > reference : levels.target < reference) out.target_underlying = levels.target;
    else problems.push(`For a ${direction} position the target (${inr(levels.target, 1)}) must be ${up ? "above" : "below"} the reference ${inr(reference, 1)}.`);
  }
  return out;
}

// ── POST /api/desk/strategy/payoff ────────────────────────────────────────

export const RANGES = [5, 10, 15] as const;
export type RangePct = (typeof RANGES)[number];
/** Points on the curve: 61 over ±r puts every scenario step (r / 5) on a grid point. */
export const GRID_POINTS = 61;

/** The 11 scenario steps of a range, in percent: −r … 0 … +r in steps of r / 5. */
export const scenarioPcts = (r: number): number[] => Array.from({ length: 11 }, (_, i) => Math.round(((i - 5) * r) / 5 * 1e6) / 1e6);
/** The scenario's name in the request and the answer ("-15%", "0%", "+3%"). */
export const scenarioName = (pct: number) => `${pct > 0 ? "+" : ""}${pct}%`;
export const STOP_SCENARIO = "stop";
export const TARGET_SCENARIO = "target";

/** Why the payoff cannot carry a "today" curve for these legs, or null: the date must be on or after the entry prices'
 *  day and not after the nearest expiry (the route refuses the whole request otherwise). */
export function todayProblem(legs: BasketLeg[], asOf: string, today: string): string | null {
  if (today < asOf) return `The entry prices are dated ${asOf}, after today ${today}.`;
  const first = legs.map((l) => l.expiry).filter((e): e is string => !!e).sort()[0];
  if (first && today > first) return `The ${fmtExpiry(first)} expiry has passed, so there is no today curve.`;
  return null;
}

export interface PayoffInput {
  symbol: string;
  legs: BasketLeg[];
  refPrice: number;
  asOf: string;
  today: string;
  rangePct: number;
  levels: Pick<BasketLevels, "stop" | "target">;
}

/** The payoff request for the basket: the legs as the route takes them, the reference (LAST), the curve over ±r, the 11
 *  scenario prices (and the stop / target when the basket holds only cash and futures), and the "today" curve. */
export function payoffRequestOf(i: PayoffInput): PayoffRequest | null {
  if (!i.legs.length || !(i.refPrice > 0)) return null;
  const scenarios = scenarioPcts(i.rangePct).map((p) => ({ name: scenarioName(p), underlying_price: Math.round(i.refPrice * (1 + p / 100) * 100) / 100 }));
  if (onlyUnderlying(i.legs)) {
    if (i.levels.stop != null && i.levels.stop > 0) scenarios.push({ name: STOP_SCENARIO, underlying_price: i.levels.stop });
    if (i.levels.target != null && i.levels.target > 0) scenarios.push({ name: TARGET_SCENARIO, underlying_price: i.levels.target });
  }
  return {
    underlying: i.symbol,
    reference_price: i.refPrice,
    as_of: i.asOf,
    legs: i.legs.map((l) => toRouteLeg(l, i.symbol)),
    grid: { from_pct: -i.rangePct, to_pct: i.rangePct, points: GRID_POINTS },
    scenarios,
    ...(todayProblem(i.legs, i.asOf, i.today) ? {} : { pre_expiry: { date: i.today } }),
  };
}

// ── POST /api/fno/margin ──────────────────────────────────────────────────

export interface MarginBody {
  underlying: string;
  legs: Array<{ side: "buy" | "sell"; option_type: "call" | "put" | "future"; expiry: string; strike: number | null; lots: number }>;
}

/** The option and future legs as Zerodha's calculator route takes them (backend routes/fno.py MarginLeg); cash has no margin
 *  there. Null when the basket has no option or future leg. */
export function marginBodyOf(symbol: string, legs: BasketLeg[]): MarginBody | null {
  const fno = legs.filter((l) => l.kind !== "CASH" && l.expiry);
  if (!fno.length) return null;
  return {
    underlying: symbol,
    legs: fno.map((l) => ({
      side: l.side === "B" ? "buy" : "sell",
      option_type: l.kind === "CE" ? "call" : l.kind === "PE" ? "put" : "future",
      expiry: l.expiry as string,
      strike: l.kind === "FUT" ? null : l.strike,
      lots: l.qty,
    })),
  };
}

// ── POST /api/desk/paper-trades ───────────────────────────────────────────

/** One leg in words for the evidence: "BUY 1 lot 4300 CE 25 Nov at ₹62.00 (NSE F&O bhavcopy close, 2026-10-28)". */
export function legWords(l: BasketLeg): string {
  const side = l.side === "B" ? "BUY" : "SELL";
  const size = l.kind === "CASH" ? `${num(l.qty, 0)} share${l.qty === 1 ? "" : "s"}` : `${num(l.qty, 0)} lot${l.qty === 1 ? "" : "s"} of ${num(l.lotSize, 0)}`;
  const what = l.kind === "CASH" ? "cash" : l.kind === "FUT" ? `future ${l.expiry ? fmtExpiry(l.expiry) : ""}` : `${l.strike} ${l.kind} ${l.expiry ? fmtExpiry(l.expiry) : ""}`;
  return `${side} ${size} ${what.trim()} at ${inr(l.entry)} (${l.priceSource})`;
}

/** The leg as the paper route takes it (LEG_FIELDS: lots, not quantity; no underlying, no iv). */
export function paperLeg(l: BasketLeg, symbol: string): NewStrategyPaperTrade["legs"][number] {
  const r = toRouteLeg(l, symbol);
  return {
    kind: r.kind, side: r.side, lots: r.quantity, lot_size: r.lot_size, entry_price: r.entry_price,
    expiry: r.expiry, strike: r.strike, option_type: r.option_type, price_source: clip(r.price_source, 200),
  };
}

export interface StrategyInput {
  symbol: string;
  legs: BasketLeg[];
  refPrice: number;
  last: { price: number; at: string; source: string };
  /** The chain day the option / future prices are from. */
  fnoAsOf: string | null;
  /** The payoff route's position delta (pre_expiry.greeks.delta). */
  delta: number | null | undefined;
  levels: Pick<BasketLevels, "stop" | "target">;
  planId: string | null;
  now: Date;
}

export type BodyResult<T> = { ok: true; body: T; notes: string[] } | { ok: false; problems: string[] };

/** kind "strategy": the basket's option / future (and cash) legs, the family of their shape, the direction from the
 *  payoff route's delta, the levels on the right side of the reference, and the signal the route requires
 *  (services/desk_strategy_trades.clean_signal: when, by which rules, from what, why in plain words). */
export function strategyBodyOf(i: StrategyInput): BodyResult<NewStrategyPaperTrade> {
  const dir = directionOf(i.delta, i.legs);
  if (!dir.direction) return { ok: false, problems: [dir.why] };
  const lv = levelsFor(dir.direction, i.refPrice, i.levels);
  if (lv.problems.length) return { ok: false, problems: lv.problems };
  const { problems: _p, dropped, ...levels } = lv;
  const fno = i.legs.filter((l) => l.kind !== "CASH");
  const expiry = fno.map((l) => l.expiry).filter((e): e is string => !!e).sort()[0] ?? null;
  const refs: Array<{ kind: string; ref: string; as_of?: string | null }> = [];
  if (fno.length && i.fnoAsOf) refs.push({ kind: "option_chain", ref: clip(`NSE F&O bhavcopy, ${i.symbol}${expiry ? ` ${expiry}` : ""}`, 120), as_of: i.fnoAsOf });
  refs.push({ kind: "live_chart", ref: clip(`${i.symbol} last ${i.last.source}`, 120), as_of: clip(i.last.at, 40) });
  if (i.planId) refs.push({ kind: "trade_plan", ref: clip(i.planId, 120) });
  const family = familyOf(i.legs);
  const evidence = clip(
    `${i.symbol} paper basket from Trade Desk › Chart Analysis (${family.replace(/_/g, " ")}): ${i.legs.map(legWords).join("; ")}. `
    + `Reference ${inr(i.refPrice)} (${i.last.source}, ${i.last.at}). ${dir.why}`
    + `${levels.stop_underlying != null ? ` Stop on the underlying ${inr(levels.stop_underlying, 1)}.` : ""}`
    + `${levels.target_underlying != null ? ` Target ${inr(levels.target_underlying, 1)}.` : ""}`, 1000);
  const body: NewStrategyPaperTrade = {
    kind: "strategy",
    underlying: i.symbol,
    direction: dir.direction,
    family,
    reference_price: i.refPrice,
    ...levels,
    legs: i.legs.map((l) => paperLeg(l, i.symbol)),
    signal: { signal_at: i.now.toISOString(), rule_version: RULE_VERSION, source_refs: refs, evidence_summary: evidence },
    note: clip(`Chart Analysis basket · ${i.legs.length} leg${i.legs.length === 1 ? "" : "s"}`, 500),
    ...(i.planId ? { plan_ref: { plan_id: i.planId } } : {}),
  };
  return { ok: true, body, notes: [dir.why, ...(dropped ? [dropped] : [])] };
}

/** The share trade's body (POST /api/desk/paper-trades without kind), with `source.kind` naming this screen: the route
 *  takes any kind matching ^[A-Za-z0-9_-]{1,40}$ (services/desk_trading.clean_source); desk-trading's NewPaperTrade types
 *  only the two the older screens send. */
export type ChartCashTrade = Omit<NewPaperTrade, "source"> & { source: { kind: "chart_analysis"; signal_date?: string } };

export interface CashInput {
  symbol: string;
  leg: BasketLeg;
  levels: BasketLevels;
  /** The paper engine's entry rule for this entry (desk-trading entryRuleFor against the LAST). */
  rule: EntryRule;
  planId: string | null;
  now: Date;
}

/** A cash-only basket is the share trade the cash ticket sends: long only, entry (the cash entry level, else the leg's
 *  price), a stop below it (required), a target above it (optional), the entry rule, the signal time and this screen. */
export function cashBodyOf(i: CashInput): BodyResult<ChartCashTrade> {
  const entry = i.levels.cashEntry ?? i.leg.entry;
  const problems: string[] = [];
  if (i.leg.side === "S") problems.push("A share paper trade is long only: selling shares is not recorded. Flip the cash leg to BUY.");
  if (i.levels.stop == null) problems.push("Set a stop below the entry: a share paper trade needs one.");
  else if (!(i.levels.stop < entry)) problems.push(`The stop (${inr(i.levels.stop, 1)}) must be below the entry (${inr(entry, 1)}).`);
  if (i.levels.target != null && !(i.levels.target > entry)) problems.push(`The target (${inr(i.levels.target, 1)}) must be above the entry (${inr(entry, 1)}).`);
  if (!Number.isInteger(i.leg.qty) || i.leg.qty < 1) problems.push("The share quantity must be a whole number of at least 1.");
  if (problems.length) return { ok: false, problems };
  const body: ChartCashTrade = {
    symbol: i.symbol,
    quantity: i.leg.qty,
    entry_price: entry,
    stop_price: i.levels.stop as number,
    target_price: i.levels.target ?? null,
    source: { kind: "chart_analysis", ...(istDay(i.now) ? { signal_date: istDay(i.now) as string } : {}) },
    entry_rule: i.rule,
    signal_at: i.now.toISOString(),
    strategy_version: RULE_VERSION,
    rationale: clip(`${i.symbol} share paper trade from Trade Desk › Chart Analysis: ${num(i.leg.qty, 0)} shares, entry ${inr(entry)} (${i.levels.cashEntry != null ? "level set on the chart" : i.leg.priceSource}), stop ${inr(i.levels.stop as number)}${i.levels.target != null ? `, target ${inr(i.levels.target)}` : ""}.`, 500),
    ...(i.planId ? { plan_ref: { plan_id: i.planId } } : {}),
  };
  return { ok: true, body, notes: [] };
}

/** A tick for the − / + steppers: about 0.1% of the price, rounded to a step a trader would type. */
export function priceStep(price: number): number {
  const rough = Math.abs(price) * 0.001;
  return [0.05, 0.1, 0.2, 0.5, 1, 2, 5, 10, 20, 50, 100].find((s) => s >= rough) ?? 100;
}
