/**
 * Chart Analysis v2 — the pure logic behind the OPTION CHAIN (design item 6) and the strategy cards (design item 9)
 * (test_reports/chart_analysis_v2_TESTCASES.md). No React, no request, no runtime import: only types, so the
 * Playwright logic spec can import this file in Node and test it directly.
 *
 *   option chain     which columns a mode shows, the grid template, OI change in percent, which live quote counts,
 *                    why a B / S button is off
 *   strategy cards   POST /api/desk/strategy/plan's candidates in the engine's own order, the card's tag, legs, reason
 *                    and figures, and the basket legs ADD TO BASKET writes
 *
 * Every figure comes from a route. Nothing here works out a payoff, a premium or a Greek; the one sum is the OI change in
 * percent, from the chain route's own OI and OI change. A figure the route did not send stays null and reads "—".
 */
import type { Alternative, Candidate, PlanLeg, StrategyPlan } from "../../../strategy/plan-contract";
import type { LiveAnswer, LiveLegRequest } from "../../../strategy/top-live";
import type { AnalysisChain, SideRow, StrikeRow } from "./chain-data";
import type { NewLeg } from "./basket";
import type { MarginBody } from "./presets";

// ── option chain ─────────────────────────────────────────────────────────

export type ChainMode = "oi" | "greeks";
export type ChainCell = "oi" | "oiPct" | "iv" | "vega" | "gamma" | "theta" | "delta";
export type OptionKind = "CE" | "PE";

export const CELL_LABEL: Record<ChainCell, string> = {
  oi: "OI", oiPct: "OI Δ%", iv: "IV", vega: "VEGA", gamma: "GAMMA", theta: "THETA", delta: "DELTA",
};

/** The call side's columns, left to right (the put side is the mirror). Phone: OI Δ% only, or THETA + DELTA only. */
export function callCells(mode: ChainMode, compact: boolean): ChainCell[] {
  if (mode === "oi") return compact ? ["oiPct"] : ["oi", "oiPct"];
  return compact ? ["theta", "delta"] : ["iv", "vega", "gamma", "theta", "delta"];
}

/** The put side's columns, left to right: the call side reversed (DELTA sits next to the put LTP). */
export const putCells = (mode: ChainMode, compact: boolean): ChainCell[] => [...callCells(mode, compact)].reverse();

const STRIKE_W = { phone: 52, wide: 66 } as const;
const BTN_W = 26;

/** The design's chCols: n call cells, call LTP, B, S, strike, B, S, put LTP, n put cells. */
export function chainTemplate(cellsPerSide: number, compact: boolean): string {
  const cells = Array.from({ length: cellsPerSide }, () => "1fr");
  const strike = compact ? STRIKE_W.phone : STRIKE_W.wide;
  return [...cells, "1fr", `${BTN_W}px`, `${BTN_W}px`, `${strike}px`, `${BTN_W}px`, `${BTN_W}px`, "1fr", ...cells].join(" ");
}

/** The narrowest the grid may get before its box scrolls sideways (the page itself never does). */
export function chainMinWidth(cellsPerSide: number, compact: boolean): number {
  const fr = compact ? 46 : 54;
  return (cellsPerSide * 2 + 2) * fr + 4 * BTN_W + (compact ? STRIKE_W.phone : STRIKE_W.wide) + 8;
}

/** OI change in percent of the previous session's OI: change / (OI − change) × 100. Null when either is missing or the
 *  previous OI is not above zero (a contract new that day has no base to measure against). */
export function oiChangePct(oi: number | null, change: number | null): number | null {
  if (oi == null || change == null || !Number.isFinite(oi) || !Number.isFinite(change)) return null;
  const prev = oi - change;
  if (!(prev > 0)) return null;
  return (change / prev) * 100;
}

/** The IST calendar day of a moment. */
export function istDayOf(at: Date): string {
  return new Date(at.getTime() + 330 * 60_000).toISOString().slice(0, 10);
}

/** The IST day of a Kite timestamp: Kite sends exchange times without a zone ("2026-10-29 10:15:02", IST); a time with
 *  a zone is converted. Null when it is not a time. */
export function kiteTradeDay(ts: string | null | undefined): string | null {
  if (!ts) return null;
  if (/^\d{4}-\d{2}-\d{2}([ T]\d{2}:\d{2}(:\d{2}(\.\d+)?)?)?$/.test(ts)) return ts.slice(0, 10);
  const t = new Date(ts);
  return Number.isFinite(t.getTime()) ? istDayOf(t) : null;
}

/** A live quote as the fno-quotes route sends it (`last_trade_time` is passed through from Kite when it has one). */
export interface ChainLiveQuote { last_price: number; last_trade_time?: string | null }

/** A quote is shown as live only if its contract last traded today (IST). Kite answers `last_price` for a contract that
 *  has not traded for days (its `last_trade_time` is then an older day, or 1970). */
export function liveQuoteCounts(q: ChainLiveQuote | null | undefined, todayIst: string): boolean {
  if (!q || !Number.isFinite(q.last_price) || !(q.last_price > 0)) return false;
  return kiteTradeDay(q.last_trade_time ?? null) === todayIst;
}

export const contractKey = (kind: OptionKind, strike: number) => `${kind}|${strike}`;

/** The legs one POST /api/live/fno-quotes asks for (every contract on the visible rows), and which contract each index is. */
export function liveLegsFor(symbol: string, expiry: string | null, rows: StrikeRow[]): { legs: LiveLegRequest[]; at: Array<{ kind: OptionKind; strike: number }> } {
  const legs: LiveLegRequest[] = [];
  const at: Array<{ kind: OptionKind; strike: number }> = [];
  if (!expiry) return { legs, at };
  for (const r of rows) {
    for (const kind of ["CE", "PE"] as const) {
      if (!(kind === "CE" ? r.call : r.put)) continue;
      legs.push({ underlying: symbol, kind: "option", expiry, strike: r.strike, option_type: kind === "CE" ? "call" : "put" });
      at.push({ kind, strike: r.strike });
    }
  }
  return { legs, at };
}

/** The quotes that count (traded today), by contract. Empty when the answer is unavailable. */
export function liveByContract(at: Array<{ kind: OptionKind; strike: number }>, answer: LiveAnswer | undefined, todayIst: string): Map<string, ChainLiveQuote> {
  const out = new Map<string, ChainLiveQuote>();
  if (!answer?.available) return out;
  at.forEach((c, i) => {
    const q = answer.quotes?.[String(i)] as ChainLiveQuote | undefined;
    if (liveQuoteCounts(q, todayIst)) out.set(contractKey(c.kind, c.strike), { last_price: (q as ChainLiveQuote).last_price, last_trade_time: q?.last_trade_time ?? null });
  });
  return out;
}

/** "the 4300 CE" */
export const contractName = (kind: OptionKind, strike: number) => `the ${strike} ${kind}`;

/** Why the B / S buttons of one contract are off, or null when it can be picked. */
export function pickBlock(o: {
  chain: Pick<AnalysisChain, "tradable" | "lotSize" | "asOf" | "expiry">;
  side: SideRow | null;
  kind: OptionKind;
  strike: number;
  /** The price shown (live or close). */
  price: number | null;
  live: boolean;
}): string | null {
  const name = contractName(o.kind, o.strike);
  if (!o.chain.tradable || !o.chain.expiry) return "Pick an expiry to trade: legs need one expiry.";
  if (!o.side) return `No ${o.strike} ${o.kind} contract is listed in this expiry.`;
  if (o.chain.lotSize == null) return "The chain gave no lot size, so a leg cannot be sized.";
  if (o.price == null || !(o.price > 0)) return `There is no close for ${name} on ${o.chain.asOf}, so there is no price to pick it at.`;
  if (!o.live && o.side.volume === 0) return `${name[0].toUpperCase()}${name.slice(1)} did not trade on ${o.chain.asOf}: its close is not a market price.`;
  return null;
}

// ── strategy cards (POST /api/desk/strategy/plan) ────────────────────────

/** The engine's ranking key (services/strategy_plan/plan.py: viable.sort, `preferred` = the first): net reward : risk,
 *  else gross, else last; ties by id. The plan sends its candidates unsorted with the rule in `ranking`, so the same rule
 *  is applied here, unchanged. */
const rankKey = (c: Candidate): number => {
  const rr = c.risk_reward;
  if (rr?.net != null) return rr.net;
  return rr?.gross ? rr.gross : -1e9;
};
const byId = (a: Candidate, b: Candidate) => (a.id < b.id ? -1 : a.id > b.id ? 1 : 0);

/** The viable candidates (status "candidate") in the engine's order, its `preferred` first. */
export function engineOrder(plan: Pick<StrategyPlan, "candidates" | "preferred">): Candidate[] {
  const viable = plan.candidates.filter((c) => c.status === "candidate");
  const out = [...viable].sort((a, b) => rankKey(b) - rankKey(a) || byId(a, b));
  const at = plan.preferred ? out.findIndex((c) => c.id === plan.preferred) : -1;
  if (at > 0) out.unshift(...out.splice(at, 1));
  return out;
}

/** The cards: the first `n` actionable candidates (viable and not priced off a delayed chain), in the engine's order. */
export function topActionable(plan: Pick<StrategyPlan, "candidates" | "preferred">, n = 3): Candidate[] {
  return engineOrder(plan).filter((c) => c.actionable).slice(0, n);
}

export type CardTag = "PRIMARY" | "ALTERNATE" | "DIRECTIONAL";

/** 1st PRIMARY, 2nd ALTERNATE, 3rd DIRECTIONAL for a futures or cash position, else ALTERNATE. */
export function cardTag(index: number, c: Pick<Candidate, "segment">): CardTag {
  if (index === 0) return "PRIMARY";
  if (index === 1) return "ALTERNATE";
  return c.segment === "futures" || c.segment === "cash" ? "DIRECTIONAL" : "ALTERNATE";
}

const legWord = (l: PlanLeg): string => {
  if (l.kind === "option") return `${l.strike ?? "—"} ${l.option_type === "call" ? "CE" : l.option_type === "put" ? "PE" : "—"}`;
  return l.kind === "future" ? "FUT" : "SHARES";
};

/** "BUY 4300 CE · SELL 4500 CE" (the design's legs line); "×2" on each leg when the legs' quantities differ. */
export function legsText(legs: PlanLeg[]): string {
  const same = new Set(legs.filter((l) => l.kind !== "cash").map((l) => l.quantity)).size <= 1;
  return legs.map((l) => `${l.side === "buy" ? "BUY" : "SELL"} ${legWord(l)}${!same && l.kind !== "cash" ? ` ×${l.quantity}` : ""}`).join(" · ");
}

/** The engine's reason as plain words: its why_qualifies (else the option selection's why), source-file references
 *  such as "(rule 3, FnoStrategies.tsx)" dropped, code words such as "long_buildup" spaced, the first one or two sentences. */
export function cardWhy(c: Pick<Candidate, "why_qualifies" | "options_selection">, sentences = 2): string {
  const raw = (c.why_qualifies.length ? c.why_qualifies.join(" ") : c.options_selection?.why ?? "").trim();
  const clean = raw
    .replace(/\s*\([^()]*\.(?:tsx?|py)\b[^()]*\)/g, "")
    .replace(/\b[a-z]+(?:_[a-z]+)+\b/g, (code) => code.replace(/_/g, " "))   // "long_buildup" → "long buildup"
    .replace(/\s{2,}/g, " ")
    .trim();
  if (!clean) return "";
  const parts = clean.split(/(?<=[.!?])\s+(?=[A-Z₹(])/);
  return parts.slice(0, sentences).join(" ");
}

export type Figure = { kind: "value"; value: number | null } | { kind: "unlimited" };

export interface CardFigures {
  maxProfit: Figure;
  /** "LOSS AT STOP" for cash, futures, and a structure whose comparison row says `max_loss_at: "stop"` (shares with no long
   *  put under them, e.g. the covered call: at expiry they have no floor but zero, and the plan exits at its stop);
   *  "MAX LOSS" for the rest (the expiry payoff's defined worst case). */
  lossLabel: "MAX LOSS" | "LOSS AT STOP";
  maxLoss: Figure;
  lossBasis: string | null;
  /** The stop the LOSS AT STOP is priced at (the candidate's invalidation level); null for MAX LOSS. */
  stop: number | null;
  /** Reward : risk, after costs when the engine has it, else before costs. */
  rr: { value: number; basis: "after costs" | "before costs" } | null;
  breakevens: number[];
  /** Options: the net premium (debit or credit) of the legs. Futures / cash: the entry price. */
  premium:
    | { kind: "debit" | "credit"; value: number; optionsOnly: boolean }
    | { kind: "flat" }
    | { kind: "entry"; value: number | null }
    | { kind: "unknown" };
  /** "1 LOT", "2 LOTS", "250 SHARES", "LOTS VARY". */
  size: string;
  /** The shares of a combination ("plus 250 shares at ₹1,200.00" is drawn from these). */
  shares: { quantity: number; price: number } | null;
}

const plural = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`;

/** The card's figures, read from the candidate's payoff block and the plan's own comparison row (`alternatives`, same id).
 *  Nothing is computed: "Unlimited" exactly where the payoff says the profit or loss is unbounded. */
export function cardFigures(plan: Pick<StrategyPlan, "alternatives">, c: Candidate): CardFigures {
  const ex = c.payoff?.expiry ?? null;
  const alt: Alternative | null = plan.alternatives.find((a) => a.id === c.id) ?? null;
  const linear = c.segment === "cash" || c.segment === "futures";
  const atStop = linear || alt?.max_loss_at === "stop";
  const maxProfit: Figure = ex?.profit_unbounded ? { kind: "unlimited" } : { kind: "value", value: ex?.max_profit ?? null };
  let maxLoss: Figure;
  if (atStop) maxLoss = { kind: "value", value: alt?.max_loss ?? c.risk_reward?.risk_net ?? null };
  else if (ex?.loss_unbounded) maxLoss = { kind: "unlimited" };
  else maxLoss = { kind: "value", value: alt?.max_loss ?? ex?.max_loss ?? null };
  const rr = c.risk_reward?.net != null ? { value: c.risk_reward.net, basis: "after costs" as const }
    : c.risk_reward?.gross != null ? { value: c.risk_reward.gross, basis: "before costs" as const } : null;
  const breakevens = ex?.breakevens?.length ? ex.breakevens : alt?.breakeven ?? [];

  const opts = c.legs.filter((l) => l.kind === "option");
  const cash = c.legs.find((l) => l.kind === "cash") ?? null;
  const lots = new Set(c.legs.filter((l) => l.kind !== "cash").map((l) => l.quantity));
  let size: string;
  if (c.segment === "cash") size = cash ? plural(cash.quantity, "SHARE", "SHARES") : "—";
  else if (lots.size === 1) size = plural([...lots][0], "LOT", "LOTS");
  else size = lots.size ? "LOTS VARY" : "—";

  let premium: CardFigures["premium"];
  if (linear) premium = { kind: "entry", value: c.legs[0]?.entry_price ?? null };
  else if (!opts.length || ex?.net_premium == null) premium = { kind: "unknown" };
  else if (ex.net_premium < 0) premium = { kind: "debit", value: Math.abs(ex.net_premium), optionsOnly: c.segment === "combination" };
  else if (ex.net_premium > 0) premium = { kind: "credit", value: ex.net_premium, optionsOnly: c.segment === "combination" };
  else premium = { kind: "flat" };

  return {
    maxProfit, maxLoss, lossLabel: atStop ? "LOSS AT STOP" : "MAX LOSS", lossBasis: alt?.max_loss_basis ?? null,
    stop: atStop ? c.invalidation?.technical?.price ?? null : null,
    rr, breakevens, premium, size,
    shares: c.segment === "combination" && cash ? { quantity: cash.quantity, price: cash.entry_price } : null,
  };
}

/** The shares a card buys (a cash idea or a combination's shares leg), else null. */
export function cardShares(c: Pick<Candidate, "legs">): { quantity: number; price: number } | null {
  const cash = c.legs.find((l) => l.kind === "cash" && l.side === "buy");
  return cash ? { quantity: cash.quantity, price: cash.entry_price } : null;
}

/** POST /api/fno/margin's body for a card (Zerodha's calculator through the platform Kite session): its option and future
 *  legs, lots as the candidate has them. Shares have no F&O margin (bought for delivery, paid in full), so a cash-only card
 *  asks nothing (null). */
export function cardMarginBody(symbol: string, legs: PlanLeg[]): MarginBody | null {
  const fno = legs.filter((l) => (l.kind === "option" || l.kind === "future") && l.expiry);
  if (!fno.length) return null;
  return {
    underlying: symbol,
    legs: fno.map((l) => ({
      side: l.side,
      option_type: l.kind === "future" ? "future" : l.option_type === "put" ? "put" : "call",
      expiry: l.expiry as string,
      strike: l.kind === "future" ? null : l.strike ?? null,
      lots: l.quantity,
    })),
  };
}

/** The expiry a card's F&O legs share, else null (cash only, or legs on different expiries). */
export function cardExpiry(c: Pick<Candidate, "legs">): string | null {
  const days = new Set(c.legs.filter((l) => l.kind !== "cash").map((l) => l.expiry ?? ""));
  if (days.size !== 1) return null;
  return [...days][0] || null;
}

export const CHAIN_CLOSE_NOTE = "priced at the chain close";

/** The basket legs ADD TO BASKET writes: each leg's kind, side, strike, expiry, lots, entry price and price source as the
 *  candidate has them. An option leg without an entry price takes the chain row's close for its strike when the chain on
 *  screen is that leg's expiry ("priced at the chain close"); a leg with no price at all is not added (`problem`). */
export function candidateLegs(c: Pick<Candidate, "legs">, chain: AnalysisChain | null): { legs: NewLeg[]; chainPriced: boolean; problem: string | null } {
  const legs: NewLeg[] = [];
  let chainPriced = false;
  if (!c.legs.length) return { legs, chainPriced, problem: "The strategy has no legs." };
  for (const l of c.legs) {
    const kind = l.kind === "cash" ? "CASH" : l.kind === "future" ? "FUT" : l.option_type === "call" ? "CE" : l.option_type === "put" ? "PE" : null;
    if (kind == null) return { legs: [], chainPriced, problem: "An option leg has no call or put type." };
    const strike = kind === "CE" || kind === "PE" ? l.strike ?? null : null;
    if ((kind === "CE" || kind === "PE") && strike == null) return { legs: [], chainPriced, problem: "An option leg has no strike." };
    const expiry = kind === "CASH" ? null : l.expiry ?? null;
    if (kind !== "CASH" && !expiry) return { legs: [], chainPriced, problem: "A futures or option leg has no expiry." };
    let entry: number | null = Number.isFinite(l.entry_price) && l.entry_price > 0 ? l.entry_price : null;
    let source = l.price_source ?? null;
    if (entry == null && (kind === "CE" || kind === "PE") && chain?.tradable && chain.expiry === expiry) {
      const row = chain.rows.find((r) => r.strike === strike);
      const close = (kind === "CE" ? row?.call?.close : row?.put?.close) ?? null;
      if (close != null && close > 0) {
        entry = close;
        source = `NSE F&O bhavcopy close, ${chain.asOf} (${CHAIN_CLOSE_NOTE})`;
        chainPriced = true;
      }
    }
    const label = kind === "CASH" ? "share" : kind === "FUT" ? "future" : `${strike} ${kind}`;
    if (entry == null) return { legs: [], chainPriced, problem: `The ${label} leg has no price, so the strategy cannot be added.` };
    const lotSize = kind === "CASH" ? 1 : l.lot_size > 0 ? l.lot_size : chain?.lotSize ?? null;
    if (lotSize == null) return { legs: [], chainPriced, problem: `The ${label} leg has no lot size, so it cannot be sized.` };
    legs.push({
      kind, side: l.side === "buy" ? "B" : "S", qty: l.quantity, strike, expiry, entry,
      priceSource: source ?? "the strategy engine's price (no source named)", lotSize,
    });
  }
  return { legs, chainPriced, problem: null };
}

/** One line on why fewer than three cards show: the other candidates the engine checked and its first reason for each
 *  (a delayed chain for a viable one it would not act on). Null when nothing else was checked. */
export function notQualifying(plan: Pick<StrategyPlan, "candidates">, shown: Candidate[], max = 3): string | null {
  const ids = new Set(shown.map((c) => c.id));
  const rest = plan.candidates.filter((c) => !ids.has(c.id));
  if (!rest.length) return null;
  const why = (c: Candidate) => {
    if (c.status === "candidate" && !c.actionable) return "the option chain is delayed, so its strikes are not current";
    const r = c.reasons[0]?.message;
    return r ? r.replace(/\.$/, "") : c.status.replace(/_/g, " ");
  };
  const items = rest.slice(0, max).map((c) => `${c.label}: ${why(c)}`);
  const more = rest.length > max ? `; and ${rest.length - max} more` : "";
  return `Not qualifying: ${items.join("; ")}${more}.`;
}

/** The engine's reasons when nothing qualifies: the plan's status reasons, else the candidates' first reasons; distinct,
 *  at most `max`. */
export function noTradeReasons(plan: Pick<StrategyPlan, "status_reasons" | "candidates">, max = 3): string[] {
  const all = [...plan.status_reasons.map((r) => r.message), ...plan.candidates.map((c) => c.reasons[0]?.message ?? "")];
  return [...new Set(all.filter((m) => m && m.trim()))].slice(0, max);
}
