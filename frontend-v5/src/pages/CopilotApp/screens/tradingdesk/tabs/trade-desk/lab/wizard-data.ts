/**
 * Strategy Lab › Build a trade (the owner's four-step wizard) — the data and the pure rules behind it.
 *
 *   GET  /api/desk/strategy/templates          the 13 templates with intent, tags, direction, risk and their own mini payoff
 *                                              (`illustration`: the template's own function priced by the payoff engine)
 *   GET  /api/strategy-builder/strategies      your Strategy Builder strategies (the one store; Save version / Clone wait
 *                                              for its strategy_versions v2: strategy/instance-store.ts)
 *   GET  /api/desk/strategy/plans              your saved plans (immutable, v1)            (strategy/plan-data useSavedPlans)
 *   GET  /api/ai-trader/strategies             the AI Trader strategies: name, stage, version, runs
 *   GET  /api/desk/paper-trades                the paper book, read ONCE per load (it applies exits)   (desk-trading usePaperTrades)
 *   POST /api/desk/paper-trades/check          the risk service's decision for a structure on this account, nothing recorded
 *
 * Nothing here estimates a price, a payoff or a size: strikes and premiums come from the chain, the payoff from the
 * route, the decision from the risk service. Probability of profit is the one number worked out here, from the route's
 * own expiry curve and the chain's ATM IV, with its method stated (popOf).
 */
import { useQuery } from "@tanstack/react-query";
import { http } from "@/services/api/http";
import { ApiError } from "@/services/api/errors";
import type { FnoChain, FnoStrike } from "../../../../trading/fno";
import type { PayoffRequest } from "../../../strategy/strategy-contract";
import type { NewStrategyPaperTrade, StrategyPaperTrade } from "../../../desk-trading";

type Raw = Record<string, unknown>;
const rec = (v: unknown): Raw => (v && typeof v === "object" && !Array.isArray(v) ? (v as Raw) : {});
const str = (v: unknown): string | null => (typeof v === "string" && v.trim() ? v.trim() : null);
const num = (v: unknown): number | null => (typeof v === "number" && Number.isFinite(v) ? v : null);

// ── the template catalog ─────────────────────────────────────────────────

export const INTENTS = ["bullish", "bearish", "neutral", "income", "hedging", "volatility"] as const;
export type Intent = (typeof INTENTS)[number];
export const INTENT_LABEL: Record<Intent, string> = { bullish: "Bullish", bearish: "Bearish", neutral: "Neutral", income: "Income", hedging: "Hedging", volatility: "Volatility" };
export type Direction = "bullish" | "bearish" | "neutral";

export interface CatalogLeg { side: "buy" | "sell"; optionType: "call" | "put" | null; strikeParam: string | null; instrument: "option" | "future" | "cash" }
export interface Illustration { spot: number; points: Array<[number, number]>; basis: string | null; breakevens: number[] }
export interface CatalogTemplate {
  name: string;
  label: string;
  kind: "option" | "future" | "cash";
  legs: CatalogLeg[];
  params: string[];
  intent: string | null;
  tags: Intent[];
  direction: Direction | null;
  maxLoss: "defined" | "to_zero" | "unbounded" | null;
  riskNote: string | null;
  illustration: Illustration | null;
}
export interface Catalog { templates: CatalogTemplate[]; calculationVersion: string | null }

export function readCatalog(body: unknown): Catalog {
  const d = rec(body);
  if (!Array.isArray(d.templates)) throw ApiError.contractDrift("strategy.templates: no templates list");
  const templates = d.templates.flatMap((x): CatalogTemplate[] => {
    const t = rec(x);
    const name = str(t.name);
    const kind = t.kind === "option" || t.kind === "future" || t.kind === "cash" ? t.kind : null;
    if (!name || !kind) return [];
    const legs = (Array.isArray(t.legs) ? t.legs : []).flatMap((l): CatalogLeg[] => {
      const r = rec(l);
      const side = r.side === "buy" || r.side === "sell" ? r.side : null;
      const ot = r.option_type === "call" || r.option_type === "put" ? r.option_type : null;
      const inst = r.instrument === "option" || r.instrument === "future" || r.instrument === "cash" ? r.instrument : ot ? "option" : null;
      return side && inst ? [{ side, optionType: ot, strikeParam: str(r.strike_param), instrument: inst }] : [];
    });
    const risk = rec(t.risk);
    const ml = risk.max_loss === "defined" || risk.max_loss === "to_zero" || risk.max_loss === "unbounded" ? risk.max_loss : null;
    const il = rec(t.illustration);
    const pts = (Array.isArray(il.points) ? il.points : []).flatMap((p): Array<[number, number]> => (Array.isArray(p) && num(p[0]) != null && num(p[1]) != null ? [[p[0] as number, p[1] as number]] : []));
    const dir = t.direction === "bullish" || t.direction === "bearish" || t.direction === "neutral" ? t.direction : null;
    return [{
      name, label: str(t.label) ?? name, kind, legs,
      params: (Array.isArray(t.params) ? t.params : []).flatMap((p) => (typeof p === "string" ? [p] : [])),
      intent: str(t.intent),
      tags: (Array.isArray(t.tags) ? t.tags : []).flatMap((g): Intent[] => ((INTENTS as readonly string[]).includes(g as string) ? [g as Intent] : [])),
      direction: dir, maxLoss: ml, riskNote: str(risk.note),
      illustration: pts.length >= 2 && num(il.spot) != null
        ? { spot: il.spot as number, points: pts, basis: str(il.basis), breakevens: (Array.isArray(il.breakevens) ? il.breakevens : []).flatMap((b) => (num(b) != null ? [b as number] : [])) }
        : null,
    }];
  });
  return { templates, calculationVersion: str(d.calculation_version) };
}

export function useCatalog() {
  return useQuery<Catalog>({
    queryKey: ["copilot", "desk", "lab", "templates"],
    staleTime: 10 * 60_000,
    retry: false,
    queryFn: async ({ signal }) => readCatalog((await http({ path: "/api/desk/strategy/templates", signal, noRetry: true })).data),
  });
}

/** "2 legs · Defined risk", or the honest risk word for a template whose loss is not bounded by its options. */
export function riskWords(t: CatalogTemplate): string {
  const n = `${t.legs.length} leg${t.legs.length === 1 ? "" : "s"}`;
  const r = t.maxLoss === "defined" ? "Defined risk" : t.maxLoss === "to_zero" ? "Loss runs to a price of zero" : t.maxLoss === "unbounded" ? "Unbounded loss" : "Risk not stated";
  return `${n} · ${r}`;
}

// ── the wizard's legs ────────────────────────────────────────────────────

export type LegKind = "option" | "future" | "cash";
export interface WLeg {
  id: string;
  kind: LegKind;
  side: "buy" | "sell";
  optionType: "call" | "put" | null;
  strike: number | null;
  /** YYYY-MM-DD; null for a cash leg. */
  expiry: string | null;
  /** Lots for a future or option; shares for a cash leg. */
  lots: number;
  /** Per unit, from the chain (an option's close, a future's close, the underlying's price); null when it has none. */
  price: number | null;
  priceSource: string | null;
}

let seq = 1;
export const legId = () => `L${seq++}`;

export const closeOfSide = (row: FnoStrike | undefined, t: "call" | "put"): number | null => {
  const s = row?.[t];
  return s ? s.close ?? s.settle ?? null : null;
};

export function chainSource(chain: FnoChain): string {
  return `NSE F&O bhavcopy close, ${chain.summary.as_of}`;
}

/** An option leg at a chain strike, priced at that contract's close (null when the chain has none: never invented). */
export function optionLeg(chain: FnoChain, side: "buy" | "sell", t: "call" | "put", strike: number, lots: number): WLeg {
  const row = chain.strikes.find((r) => r.strike === strike);
  return { id: legId(), kind: "option", side, optionType: t, strike, expiry: chain.summary.expiry, lots, price: closeOfSide(row, t), priceSource: chainSource(chain) };
}

// ── step 2: the strike rule ─────────────────────────────────────────────

export type StrikeRule = "atm" | "otm" | "itm" | "delta" | "manual";
export interface BuildConfig {
  rule: StrikeRule;
  /** Strikes away from ATM for the leg that defines the position (OTM / ITM). */
  anchor: number;
  /** Strikes between a spread's legs. */
  width: number;
  /** Target |delta| for the defining leg (rule "delta"). */
  delta: number;
  lots: number;
}
export const DEFAULT_BUILD: BuildConfig = { rule: "atm", anchor: 1, width: 2, delta: 0.3, lots: 1 };

/**
 * Each template's strikes as steps from the anchor strike, by its own strike parameters: `anchor` is where the defining
 * leg sits (from the rule), `w` the width. `call` / `put` say which side's moneyness the anchor follows.
 */
type Place = { defining: "call" | "put"; at: Record<string, (a: number, w: number) => number>; minAnchor?: number };
export const PLACEMENT: Record<string, Place> = {
  long_call: { defining: "call", at: { strike: (a) => a } },
  long_put: { defining: "put", at: { strike: (a) => a } },
  bull_call_spread: { defining: "call", at: { long_strike: (a) => a, short_strike: (a, w) => a + w } },
  bear_put_spread: { defining: "put", at: { long_strike: (a) => a, short_strike: (a, w) => a - w } },
  bull_put_spread: { defining: "put", at: { short_strike: (a) => a, long_strike: (a, w) => a - w } },
  bear_call_spread: { defining: "call", at: { short_strike: (a) => a, long_strike: (a, w) => a + w } },
  // The condor's short legs sit the anchor's distance either side of ATM (at least one strike, or it is a butterfly).
  iron_condor: { defining: "call", minAnchor: 1, at: { short_put_strike: (a) => -a, long_put_strike: (a, w) => -a - w, short_call_strike: (a) => a, long_call_strike: (a, w) => a + w } },
  covered_call: { defining: "call", minAnchor: 1, at: { call_strike: (a) => a } },
  protective_put: { defining: "put", at: { put_strike: (a) => a } },
  collar: { defining: "call", minAnchor: 1, at: { put_strike: (a) => -a, call_strike: (a) => a } },
};

/** The anchor in strike steps from ATM for the rule: + is higher strikes. OTM is above for a call, below for a put. */
function anchorSteps(rule: StrikeRule, anchor: number, defining: "call" | "put"): number {
  if (rule === "atm" || rule === "manual") return 0;
  const sign = defining === "call" ? 1 : -1;
  return rule === "otm" ? sign * anchor : -sign * anchor;
}

export type Built = { ok: true; legs: WLeg[]; note: string | null } | { ok: false; problem: string };

/** The template's legs on the chain for the step-2 settings. Strikes only from the chain; prices only its closes. */
export function buildLegs(t: CatalogTemplate, chain: FnoChain, cfg: BuildConfig, futurePrice: { price: number; expiry: string; source: string } | null): Built {
  const lots = Math.max(1, Math.floor(cfg.lots));
  const spot = chain.summary.spot;
  if (t.kind === "cash") {
    if (spot == null) return { ok: false, problem: "The chain has no underlying price, so the shares cannot be priced." };
    return { ok: true, legs: [{ id: legId(), kind: "cash", side: "buy", optionType: null, strike: null, expiry: null, lots, price: spot, priceSource: `NSE F&O bhavcopy underlying price, ${chain.summary.as_of}` }], note: "Lots are shares for a cash position." };
  }
  if (t.kind === "future") {
    if (!futurePrice) return { ok: false, problem: "No futures close is listed for this expiry, so the future cannot be priced." };
    const side = t.legs[0]?.side ?? "buy";
    return { ok: true, legs: [{ id: legId(), kind: "future", side, optionType: null, strike: null, expiry: futurePrice.expiry, lots, price: futurePrice.price, priceSource: futurePrice.source }], note: null };
  }
  const place = PLACEMENT[t.name];
  if (!place) return { ok: false, problem: `${t.label}: the wizard has no strike placement for this template yet.` };
  const strikes = chain.strikes;
  const atm = strikes.findIndex((r) => r.strike === chain.summary.atm_strike);
  if (atm < 0) return { ok: false, problem: "The chain has no ATM strike (no underlying price), so strikes cannot be placed." };
  let note: string | null = null;
  let a0: number;
  if (cfg.rule === "delta") {
    const side = place.defining;
    let best = -1;
    let gap = Infinity;
    strikes.forEach((r, i) => {
      const d = r[side]?.delta;
      if (d == null) return;
      const g = Math.abs(Math.abs(d) - cfg.delta);
      if (g < gap) { gap = g; best = i; }
    });
    if (best < 0) return { ok: false, problem: "The chain has no deltas for these contracts, so a delta rule cannot place the strikes." };
    a0 = best - atm;
    if (place.minAnchor && Math.abs(a0) < place.minAnchor) { a0 = place.defining === "call" ? place.minAnchor : -place.minAnchor; note = `${t.label} needs its short strike off ATM: moved one strike out.`; }
    if (t.name === "iron_condor" || t.name === "collar") a0 = Math.abs(a0);
    note = note ?? `Delta rule: the ${place.defining} nearest |Δ| ${cfg.delta.toFixed(2)} (chain model delta), ${fmtStrike(strikes[best].strike)}.`;
  } else {
    let a = Math.max(0, Math.floor(cfg.anchor));
    if (cfg.rule === "atm" || cfg.rule === "manual") a = 0;
    if (place.minAnchor && a < place.minAnchor) { a = place.minAnchor; note = `${t.label} needs its short strike(s) off ATM: placed ${a} strike${a === 1 ? "" : "s"} out.`; }
    a0 = t.name === "iron_condor" || t.name === "collar" ? a : anchorSteps(cfg.rule === "atm" || cfg.rule === "manual" ? (a > 0 ? "otm" : "atm") : cfg.rule, a, place.defining);
  }
  const w = Math.max(1, Math.floor(cfg.width));
  const legs: WLeg[] = [];
  for (const cl of t.legs) {
    if (cl.instrument === "cash") {
      if (spot == null) return { ok: false, problem: "The chain has no underlying price, so the shares cannot be priced." };
      if (chain.lot_size == null) return { ok: false, problem: "The contract's lot size is not available, so the covering shares cannot be sized." };
      legs.push({ id: legId(), kind: "cash", side: "buy", optionType: null, strike: null, expiry: null, lots: lots * chain.lot_size, price: spot, priceSource: `NSE F&O bhavcopy underlying price, ${chain.summary.as_of}` });
      continue;
    }
    const f = cl.strikeParam ? place.at[cl.strikeParam] : undefined;
    if (!f || !cl.optionType) return { ok: false, problem: `${t.label}: leg ${cl.strikeParam ?? "?"} has no placement.` };
    const i = atm + f(a0, w);
    if (i < 0 || i >= strikes.length) return { ok: false, problem: `${t.label}: a strike ${Math.abs(f(a0, w))} steps from ATM is outside the strikes the chain lists. Narrow the anchor or the width.` };
    legs.push(optionLeg(chain, cl.side, cl.optionType, strikes[i].strike, lots));
  }
  return { ok: true, legs, note };
}

export const fmtStrike = (n: number) => new Intl.NumberFormat("en-IN", { maximumFractionDigits: 2 }).format(n);

// ── the payoff request ───────────────────────────────────────────────────

export const GRID = { from_pct: -20, to_pct: 20, points: 161 } as const;

/** The payoff-v2 request for the legs, or the reason there is none (a leg with no price is never priced at a guess). */
export function payoffRequest(underlying: string, spot: number | null, asOf: string | null, lotSize: number | null, legs: WLeg[]): { req: PayoffRequest | null; problem: string | null } {
  if (!legs.length) return { req: null, problem: "No legs yet. Pick a template, or add a leg from the chain." };
  if (spot == null) return { req: null, problem: "The underlying has no price in the chain, so a payoff cannot be worked out." };
  const fo = legs.filter((l) => l.kind !== "cash");
  if (fo.length && lotSize == null) return { req: null, problem: "The contract's lot size is not available, so a payoff cannot be worked out." };
  const bad = legs.find((l) => !(l.price != null && l.price > 0));
  if (bad) return { req: null, problem: `${legLabel(bad)} has no price in the chain, so it cannot be priced (no price is invented). Change its strike or expiry, or remove it.` };
  if (legs.some((l) => !(l.lots >= 1))) return { req: null, problem: "Every leg needs at least one lot." };
  const expiries = fo.map((l) => l.expiry).filter((e): e is string => !!e).sort();
  const first = expiries[0] ?? null;
  const req: PayoffRequest = {
    underlying, reference_price: spot, ...(asOf ? { as_of: asOf } : {}),
    legs: legs.map((l) => ({
      kind: l.kind, side: l.side, quantity: l.lots, lot_size: l.kind === "cash" ? 1 : (lotSize as number), entry_price: l.price as number,
      expiry: l.kind === "cash" ? null : l.expiry, strike: l.kind === "option" ? l.strike : null, option_type: l.kind === "option" ? l.optionType : null,
      price_source: l.priceSource ?? "", underlying,
    })),
    grid: { ...GRID },
    ...(asOf && first && asOf < first && fo.some((l) => l.kind === "option") ? { pre_expiry: { date: asOf } } : {}),
  };
  return { req, problem: null };
}

export function legLabel(l: WLeg): string {
  if (l.kind === "cash") return `${l.side === "buy" ? "Bought" : "Sold"} shares`;
  if (l.kind === "future") return `${l.side === "buy" ? "Long" : "Short"} future${l.expiry ? ` ${shortDay(l.expiry)}` : ""}`;
  return `The ${l.strike != null ? fmtStrike(l.strike) : "?"} ${l.optionType === "call" ? "CE" : "PE"}${l.expiry ? ` ${shortDay(l.expiry)}` : ""}`;
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
/** "27 Nov" from YYYY-MM-DD. */
export function shortDay(d: string): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(d);
  return m ? `${Number(m[3])} ${MONTHS[Number(m[2]) - 1]}` : d;
}

/** The design's legs line: "B 1680 CE 27 Nov · S 1720 CE 27 Nov", "B CASH · S 1580 CE 27 Nov", "B FUT 27 Nov". */
export function legsSummary(legs: Array<Pick<WLeg, "kind" | "side" | "optionType" | "strike" | "expiry">>): string {
  return legs.map((l) => {
    const s = l.side === "buy" ? "B" : "S";
    if (l.kind === "cash") return `${s} CASH`;
    if (l.kind === "future") return `${s} FUT${l.expiry ? ` ${shortDay(l.expiry)}` : ""}`;
    return `${s} ${l.strike != null ? fmtStrike(l.strike).replace(/,/g, "") : "?"} ${l.optionType === "call" ? "CE" : "PE"}${l.expiry ? ` ${shortDay(l.expiry)}` : ""}`;
  }).join(" · ");
}

// ── probability of profit (model) ────────────────────────────────────────

/** Standard normal CDF (Abramowitz–Stegun 7.1.26 via erf, |error| < 1.5e-7). */
export function normCdf(x: number): number {
  const t = 1 / (1 + 0.3275911 * Math.abs(x) / Math.SQRT2);
  const y = 1 - (((((1.061405429 * t - 1.453152027) * t) + 1.421413741) * t - 0.284496736) * t + 0.254829592) * t * Math.exp(-(x * x) / 2);
  return x >= 0 ? 0.5 * (1 + y) : 0.5 * (1 - y);
}

export interface Pop { value: number; basis: string }

/**
 * P(net P/L at expiry > 0) when the underlying at expiry is lognormal: ln S_T ~ N(ln S0 + (r − σ²/2)T, σ²T), σ the chain's
 * ATM implied volatility, T the calendar days to expiry / 365, r the chain's rate. The profit region is read off the
 * route's own net curve at expiry (payoff-v2, costs included) on its grid; beyond the grid's ends the sign of the last
 * point is carried out. Null when an input is missing: then the screen says "not available".
 */
export function popOf(grid: number[], net: number[], spot: number, ivPct: number | null, days: number | null, ratePct: number | null): Pop | null {
  if (ivPct == null || !(ivPct > 0) || days == null || !(days > 0) || grid.length < 2 || grid.length !== net.length || !(spot > 0)) return null;
  const sigma = ivPct / 100;
  const T = days / 365;
  const r = (ratePct ?? 0) / 100;
  const mu = Math.log(spot) + (r - sigma * sigma / 2) * T;
  const sd = sigma * Math.sqrt(T);
  const cdf = (x: number) => (x <= 0 ? 0 : normCdf((Math.log(x) - mu) / sd));
  let p = 0;
  if (net[0] > 0) p += cdf(grid[0]);
  for (let i = 0; i < grid.length - 1; i++) {
    const a = net[i];
    const b = net[i + 1];
    if (a > 0 && b > 0) p += cdf(grid[i + 1]) - cdf(grid[i]);
    else if ((a > 0) !== (b > 0) && a !== b) {
      const x0 = grid[i] + (grid[i + 1] - grid[i]) * (a / (a - b));          // the breakeven between the two points
      p += a > 0 ? cdf(x0) - cdf(grid[i]) : cdf(grid[i + 1]) - cdf(x0);
    }
  }
  if (net[net.length - 1] > 0) p += 1 - cdf(grid[grid.length - 1]);
  const value = Math.min(1, Math.max(0, p));
  return { value, basis: `lognormal at the chain's ATM IV ${ivPct.toFixed(1)}%, ${days} days, drift ${(r * 100).toFixed(2)}%; profit region from the payoff-v2 net curve at expiry` };
}

/** Linear read of a curve at x (the route's own points; beyond the ends, the end value). */
export function at(xs: number[], ys: number[] | null | undefined, x: number): number | null {
  if (!ys || xs.length < 2 || ys.length !== xs.length) return null;
  if (x <= xs[0]) return ys[0];
  if (x >= xs[xs.length - 1]) return ys[ys.length - 1];
  let i = 1;
  while (i < xs.length && xs[i] < x) i++;
  const f = (x - xs[i - 1]) / (xs[i] - xs[i - 1]);
  return ys[i - 1] + (ys[i] - ys[i - 1]) * f;
}

// ── the paper-trade body and the risk check ─────────────────────────────

export const WIZARD_RULES = "strategy-lab-wizard-v1";

export function paperBody(o: {
  underlying: string; direction: Direction; family: string; spot: number; legs: WLeg[]; lotSize: number | null;
  template: string | null; templateLabel: string | null; stop: number | null; asOf: string | null;
}): NewStrategyPaperTrade {
  return {
    kind: "strategy",
    underlying: o.underlying,
    direction: o.direction,
    family: o.family,
    reference_price: o.spot,
    stop_underlying: o.direction === "neutral" ? null : o.stop,
    target_underlying: null,
    legs: o.legs.map((l) => ({
      kind: l.kind, side: l.side, lots: l.lots, lot_size: l.kind === "cash" ? 1 : (o.lotSize ?? 1), entry_price: l.price as number,
      expiry: l.kind === "cash" ? null : l.expiry, strike: l.kind === "option" ? l.strike : null, option_type: l.kind === "option" ? l.optionType : null,
      price_source: l.priceSource ?? "chain close",
    })),
    signal: {
      signal_at: new Date().toISOString(),
      rule_version: WIZARD_RULES,
      source_refs: o.template ? [{ kind: "strategy_template", ref: o.template, as_of: o.asOf }] : [],
      evidence_summary: `Built by hand in Strategy Lab${o.templateLabel ? ` from the ${o.templateLabel} template` : ""}: your structure, not a model signal.`,
    },
  };
}

export interface CheckAnswer {
  outcome: "allow" | "reduce" | "block";
  reasons: Array<{ code: string; message: string; severity: string }>;
  requestedLots: number | null;
  approvedLots: number | null;
  estimatedRiskRs: number | null;
  duplicate: { tradeId: string | null; message: string | null } | null;
  basis: string | null;
}
export type CheckState = { kind: "answer"; a: CheckAnswer } | { kind: "refused"; code: string; message: string };

function readCheck(body: unknown): CheckAnswer {
  const d = rec(body);
  const o = d.outcome;
  if (o !== "allow" && o !== "reduce" && o !== "block") throw ApiError.contractDrift("paper-trades.check: no outcome");
  const dup = rec(d.duplicate);
  const est = rec(d.estimated_risk_rs);
  return {
    outcome: o,
    reasons: (Array.isArray(d.reasons) ? d.reasons : []).flatMap((x) => {
      const r = rec(x);
      const message = str(r.message);
      return message ? [{ code: str(r.code) ?? "", message, severity: str(r.severity) ?? "" }] : [];
    }),
    requestedLots: num(d.requested_lots), approvedLots: num(d.approved_lots),
    estimatedRiskRs: num(est.total) ?? num(d.estimated_risk_rs),
    duplicate: Object.keys(dup).length ? { tradeId: str(dup.existing_trade_id), message: str(dup.message) } : null,
    basis: str(d.basis),
  };
}

/** Plain words for the desk's own 422 codes on a structure (the check and the POST answer the same codes). */
export const INPUT_WORDS: Record<string, string> = {
  short_futures_not_supported: "Short futures-only structures are not supported for paper trades yet.",
  futures_stop_required: "A structure with a futures leg needs a stop on the underlying.",
  naked_short_option: "A short option with no cover is not allowed: the loss is not defined.",
  invalid_leg_count: "A structure has 1 to 4 legs.",
  lot_size_mismatch: "A leg's lot size is not the exchange's lot size.",
  mixed_expiries_not_supported: "Legs on different expiries (a calendar) are not supported yet.",
  stop_not_below_reference: "The stop must be below the underlying's price for a bullish structure.",
  stop_not_above_reference: "The stop must be above the underlying's price for a bearish structure.",
};

export function refusalOf(e: unknown): { code: string; message: string } {
  if (e instanceof ApiError) {
    const raw = rec(e.body).detail;
    const det = rec(raw);
    const code = str(det.code) ?? (typeof raw === "string" ? raw : null) ?? e.kind;
    const message = str(det.message) ?? INPUT_WORDS[code] ?? (typeof raw === "string" ? raw.replace(/_/g, " ") : null) ?? e.detail ?? e.message;
    return { code, message };
  }
  return { code: "error", message: e instanceof Error ? e.message : "The check did not answer." };
}

/** The risk service's decision for this structure on your account now (POST /api/desk/paper-trades/check): nothing recorded. */
export function useRiskCheck(body: NewStrategyPaperTrade | null) {
  // signal_at changes every render; the decision does not depend on it, so it is left out of the key.
  const key = body ? JSON.stringify({ ...body, signal: { ...body.signal, signal_at: "" } }) : null;
  return useQuery<CheckState>({
    queryKey: ["copilot", "desk", "lab", "risk-check", key],
    enabled: !!body,
    staleTime: 30_000,
    retry: false,
    queryFn: async ({ signal }) => {
      try {
        const res = await http({ method: "POST", path: "/api/desk/paper-trades/check", body: body as NewStrategyPaperTrade, noRetry: true, signal });
        return { kind: "answer", a: readCheck(res.data) };
      } catch (e) {
        if (e instanceof ApiError && e.status === 422) return { kind: "refused", ...refusalOf(e) };
        throw e;
      }
    },
  });
}

// ── AI Trader strategies ─────────────────────────────────────────────────

export interface AiStrategy {
  id: string;
  name: string | null;
  stage: string | null;
  version: number | null;
  template: string | null;
  runs: number;
  passedBacktest: boolean;
  paperNetRs: number | null;
}

export function readAiStrategies(body: unknown): AiStrategy[] {
  const d = rec(body);
  if (!Array.isArray(d.strategies)) throw ApiError.contractDrift("ai-trader.strategies: no list");
  return d.strategies.flatMap((x): AiStrategy[] => {
    const s = rec(x);
    const id = str(s.id);
    if (!id) return [];
    const history = Array.isArray(s.stage_history) ? s.stage_history.map(rec) : [];
    // "Passed": the strategy was promoted to backtested with every gate passed (the promotion's own gate rows).
    const passed = history.some((h) => h.stage === "backtested" && Array.isArray(h.gates) && h.gates.length > 0 && h.gates.every((g) => rec(g).passed === true));
    const ps = rec(s.paper_stats);
    return [{
      id, name: str(s.name), stage: str(s.stage), version: num(s.version), template: str(s.template),
      runs: Array.isArray(s.runs) ? s.runs.length : 0, passedBacktest: passed,
      paperNetRs: num(ps.net_pnl_rs) ?? num(ps.net_rs),
    }];
  });
}

export function useAiStrategies() {
  return useQuery<AiStrategy[]>({
    queryKey: ["copilot", "desk", "lab", "ai-strategies"],
    staleTime: 60_000,
    retry: false,
    queryFn: async ({ signal }) => readAiStrategies((await http({ path: "/api/ai-trader/strategies", signal, noRetry: true })).data),
  });
}

// ── existing strategies · AI and yours ───────────────────────────────────

export type RowStatus = "PAPER LIVE" | "BACKTEST PASSED" | "BACKTESTED" | "DRAFT" | "SAVED";
export interface ExistingRow {
  key: string;
  source: "AI" | "YOU";
  name: string;
  ref: string;
  legs: WLeg[];
  /** No legs to load (an AI Trader rule set): the reason. */
  noLegs: string | null;
  underlying: string;
  status: RowStatus;
  statusWhy: string;
  version: number | null;
  pnlRs: number | null;
  /** The open paper trade it is cited by, when one is. */
  tradeId: string | null;
  template: string | null;
  instanceId: string | null;
  kind: "plan" | "ai" | "builder" | "trade";
}

/** Strategy-trade legs as wizard legs (the price is the trade's own entry price). */
export function tradeLegs(t: StrategyPaperTrade): WLeg[] {
  return t.legs.map((l) => {
    return {
      id: legId(), kind: l.kind, side: l.side, optionType: l.optionType, strike: l.strike, expiry: l.expiry, lots: l.lots, price: l.entry, priceSource: l.priceSource,
    };
  });
}

/** Whether a trade came from an AI source (the scanner, an AI idea, a model): its signal says so. */
function aiTrade(t: StrategyPaperTrade): boolean {
  if (t.signal.modelVersion) return true;
  if (t.tradePlanId) return true;
  return t.signal.sourceRefs.some((r) => /scanner|idea|ai|candidate|fno/i.test(r.kind));
}

export function existingRows(o: {
  builder: Array<{ id: string; name: string; assetClass: string | null }>; plans: Array<{ id: string; underlying: string | null; family: string | null; legs: WLeg[] | null }>;
  ai: AiStrategy[]; trades: StrategyPaperTrade[]; labelOf: (template: string | null) => string | null;
}): ExistingRow[] {
  const open = o.trades.filter((t) => t.status === "open");
  const used = new Set<string>();
  const rows: ExistingRow[] = [];
  for (const p of o.plans) {
    const t = open.find((x) => x.strategyPlanId === p.id);
    if (t) used.add(t.id);
    rows.push({
      key: `plan:${p.id}`, source: "YOU", name: `${p.underlying ?? "?"} ${o.labelOf(p.family) ?? (p.family ?? "plan").replace(/_/g, " ")}`, ref: p.id.slice(0, 8).toUpperCase(),
      legs: p.legs ?? [], noLegs: p.legs && p.legs.length ? null : "This saved plan has no legs to load (a no-trade or wait plan, or one still loading).",
      underlying: p.underlying ?? "—", status: t ? "PAPER LIVE" : "SAVED", statusWhy: t ? `Open paper trade ${t.id} cites it.` : "Saved plan (immutable, v1); no open paper trade cites it.",
      version: 1, pnlRs: t?.netRs ?? null, tradeId: t?.id ?? null, template: p.family, instanceId: null, kind: "plan",
    });
  }
  for (const s of o.ai) {
    const stage = s.stage ?? "draft";
    let status: RowStatus;
    let why: string;
    if (stage === "paper" || stage === "assisted") { status = "PAPER LIVE"; why = `AI Trader stage “${stage}”: it paper trades.`; }
    else if (stage === "backtested") { status = s.passedBacktest ? "BACKTEST PASSED" : "BACKTESTED"; why = s.passedBacktest ? "Promoted to backtested with every gate passed." : "Stage backtested."; }
    else if (stage === "draft" && s.runs > 0) { status = "BACKTESTED"; why = `Draft with ${s.runs} backtest run${s.runs === 1 ? "" : "s"}, not promoted.`; }
    else if (stage === "retired") { status = "SAVED"; why = "Retired: kept on record, not trading."; }
    else { status = "DRAFT"; why = "AI Trader stage “draft”."; }
    rows.push({
      key: `ai:${s.id}`, source: "AI", name: s.name ?? `AI ${s.template ?? "strategy"}`, ref: s.id.slice(0, 8).toUpperCase(),
      legs: [], noLegs: `An AI Trader strategy is a rule set${s.template ? ` (${s.template.replace(/_/g, " ")})` : ""} over a universe of shares, not a structure with legs: there is nothing to load into the leg editor.`,
      underlying: "Universe", status, statusWhy: why, version: s.version, pnlRs: status === "PAPER LIVE" ? s.paperNetRs : null, tradeId: null, template: null, instanceId: null, kind: "ai",
    });
  }
  for (const b of o.builder) {
    rows.push({
      key: `sb:${b.id}`, source: "YOU", name: b.name, ref: b.id.slice(0, 8).toUpperCase(),
      legs: [], noLegs: `A Strategy Builder strategy is a rule set over ${b.assetClass === "MF" ? "mutual funds" : "shares"} (DSL v1), not a structure with legs: there is nothing to load into the leg editor.`,
      underlying: b.assetClass === "MF" ? "Funds" : "Universe", status: "SAVED",
      statusWhy: "Saved in the Strategy Builder. Its list does not report backtest runs or a version yet; BACKTESTED / PASSED come with the shared store's list.",
      version: null, pnlRs: null, tradeId: null, template: null, instanceId: null, kind: "builder",
    });
  }
  for (const t of open) {
    if (used.has(t.id)) continue;
    rows.push({
      key: `trade:${t.id}`, source: aiTrade(t) ? "AI" : "YOU", name: `${aiTrade(t) ? "AI " : ""}${t.familyName ?? t.family ?? "Structure"}`, ref: t.id.slice(0, 8).toUpperCase(),
      legs: tradeLegs(t), noLegs: null, underlying: t.underlying, status: "PAPER LIVE", statusWhy: `Open paper trade ${t.id}.`,
      version: null, pnlRs: t.netRs, tradeId: t.id, template: t.family, instanceId: null, kind: "trade",
    });
  }
  return rows;
}

/** A leg whose expiry is before the chain's day: the contract no longer trades. */
export function expiredLegs(legs: WLeg[], asOf: string | null): WLeg[] {
  return asOf ? legs.filter((l) => l.kind !== "cash" && l.expiry != null && l.expiry < asOf) : [];
}
