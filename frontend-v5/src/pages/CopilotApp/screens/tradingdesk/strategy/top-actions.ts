/**
 * Strategy Builder, "Top by regime" — turning one ranked idea into a payoff request or a paper trade.
 *
 *   POST /api/desk/strategy/payoff     what-if payoff for the idea's legs (usePayoff, shared with the plan builder)
 *   POST /api/desk/paper-trades        a multi-leg strategy paper trade (kind "strategy")
 *
 * Both reuse what the desk already has rather than adding a second way to price or record a structure,
 * so an idea opened here and the same idea built in "One stock" cannot disagree.
 *
 * The paper-trade body carries the idea's `signal` (its data date, the board's rules version, the sources and the fit
 * reasons), which the route requires (services/desk_strategy_trades.clean_signal; without it every button was refused
 * with 422 invalid_signal). When the levels engine answered for the idea, the trade also records the underlying stop
 * and target 1 the row shows. The exact body is pinned by e2e/fixtures/contract-fno-idea-paper-trade.json, which the
 * Playwright specs compare against and backend/tests/test_fno_idea_paper_trade_contract.py sends through the real route.
 *
 * Nothing places a real order. The paper-trade route is the desk's own simulator and the Kite wrapper
 * behind the live feed exposes no order method at all.
 */
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { http } from "@/services/api/http";
import type { Levels } from "../FnoLevels";
import type { PayoffRequest } from "./strategy-contract";
import type { OptionIdeaCore as OptionIdea, TopBoard } from "./top-contract";
import { planBlocker, planRefOf, primaryTarget, type TradePlan } from "./trade-plan";

export const PAPER_TRADES_PATH = "/api/desk/paper-trades";

/** view -> the direction word the paper-trade route takes (services/desk_strategy_trades.DIRECTIONS). */
const DIRECTION: Record<string, "bullish" | "bearish" | "neutral"> = {
  up: "bullish", down: "bearish", flat: "neutral",
};

/** Families the paper-trade route accepts. Every structure this screen ranks is on that list; anything
 *  new that is not falls back to "custom", which the route still risk-checks. */
const KNOWN_FAMILIES = new Set([
  "long_future", "short_future", "long_call", "long_put", "bull_call_spread", "bear_put_spread",
  "bull_put_spread", "bear_call_spread", "long_straddle", "long_strangle", "iron_condor",
  "iron_butterfly", "covered_call", "protective_put", "collar", "hedged_future",
]);

/** The payoff request for one idea. The legs are the route's own, unchanged. */
export function payoffRequestFor(idea: OptionIdea): PayoffRequest | null {
  if (idea.reference_price == null || !idea.legs.length) return null;
  const asOf = idea.data_as_of?.chain ?? undefined;
  return {
    underlying: idea.underlying,
    reference_price: idea.reference_price,
    ...(asOf ? { as_of: asOf } : {}),
    legs: idea.legs.map((l) => ({
      kind: l.kind,
      side: l.side,
      quantity: l.quantity ?? undefined,
      lot_size: l.lot_size ?? undefined,
      entry_price: l.entry_price ?? undefined,
      expiry: l.expiry ?? undefined,
      strike: l.strike ?? undefined,
      option_type: l.option_type ?? undefined,
      price_source: l.price_source ?? undefined,
      iv_pct: l.iv_pct ?? undefined,
    })) as PayoffRequest["legs"],
  };
}

export interface LevelsRefs { put_wall: null; call_wall: null; expected_move: number | null }

/** The levels engine's references for an idea on a board: no open-interest walls (a board does not carry them) and the
 *  expected move the board measured for the underlying, the index class first. The nightly AI watchlist job sends the
 *  same (backend services/ai_watchlist_build.levels_refs_for), so a stored day's levels are the live row's levels. */
export function levelsRefsFor(board: Pick<TopBoard, "classes"> | null | undefined, underlying: string): LevelsRefs {
  let move: number | null = null;
  for (const cls of [board?.classes.index_options, board?.classes.stock_fno]) {
    for (const u of cls?.underlyings ?? []) {
      if (move == null && u.underlying === underlying && u.expected_move != null) move = u.expected_move;
    }
  }
  return { put_wall: null, call_wall: null, expected_move: move };
}

/** What a paper trade needs besides the idea: the board's rules version, and the levels the row shows (if any). */
export interface PaperContext {
  /** The board's `rules_version` (a stored list's `notes.fno_rules_version`). */
  rulesVersion: string | null | undefined;
  /** The levels engine's answer for this idea, when the row shows one. Without it no level is recorded. */
  levels?: Levels | null;
}

type Direction = "bullish" | "bearish" | "neutral";
const CONTROL = /[\u0000-\u001f\u007f]+/g;
/** The route refuses control characters and over-long text (desk_strategy_trades._text). */
const clip = (s: string, n: number) => {
  const t = s.replace(CONTROL, " ").trim();
  return t.length > n ? `${t.slice(0, n - 1)}…` : t;
};

/** The underlying stop and target 1 from the levels engine, as the route takes them (stop_underlying /
 *  target_underlying). Only when the engine answered for this idea, its view is the idea's own direction, and each level
 *  lies on the side of the reference price the route requires (bullish: stop below, target above; bearish: the
 *  reverse). A neutral idea, no answer or a level on the wrong side records nothing: no level is ever made up. */
export function tradeLevels(direction: Direction, reference: number, levels: Levels | null | undefined): { stop_underlying?: number; target_underlying?: number } {
  if (!levels?.valid || direction === "neutral" || levels.underlying.view !== direction) return {};
  const { stop, target } = levels.underlying;
  const out: { stop_underlying?: number; target_underlying?: number } = {};
  const up = direction === "bullish";
  if (stop != null && stop > 0 && (up ? stop < reference : stop > reference)) out.stop_underlying = stop;
  if (target != null && target > 0 && (up ? target > reference : target < reference)) out.target_underlying = target;
  return out;
}

/** The underlying stop and target 1 of the idea's TradePlan (Phase 2.1), as the route takes them, and the levels
 *  engine version they came from. The plan's levels are the strategy-levels engine's own (computed with the same
 *  request and references the row's levels call sends), so the row and the trade cannot differ. */
export function planLevels(tp: TradePlan, direction: Direction, reference: number): { levels: { stop_underlying?: number; target_underlying?: number }; version: string | null } {
  const out: { stop_underlying?: number; target_underlying?: number } = {};
  if (direction !== "neutral") {
    const up = direction === "bullish";
    const stop = tp.stop.method === "underlying" ? tp.stop.price : null;
    const target = primaryTarget(tp)?.price ?? null;
    if (stop != null && stop > 0 && (up ? stop < reference : stop > reference)) out.stop_underlying = stop;
    if (target != null && target > 0 && (up ? target > reference : target < reference)) out.target_underlying = target;
  }
  const opt = (tp.exit_plan as { options?: { version?: string | null } } | undefined)?.options;
  return { levels: out, version: opt?.version ?? null };
}

/** Why an idea cannot be recorded as a paper trade, or null when it can. */
export function paperTradeProblem(idea: OptionIdea, rulesVersion: string | null | undefined): string | null {
  if (idea.conflicts_with_cash_setup) return idea.conflicts_with_cash_setup.message ?? "This view conflicts with the stock's cash setup today.";
  if (idea.trade_plan) {
    const blocked = planBlocker(idea.trade_plan);
    if (blocked) return blocked;
  }
  if (idea.reference_price == null || !idea.legs.length) return "This idea has no priced legs to record.";
  if (!DIRECTION[idea.view ?? ""]) return "This idea has no direction to record.";
  if (!idea.data_as_of?.chain) return "This idea has no data date, so it cannot be recorded with its signal.";
  if (!rulesVersion?.trim()) return "The board sent no rules version, so the idea cannot be recorded with its signal.";
  return null;
}

/** The signal the route requires (services/desk_strategy_trades.clean_signal): when (the chain's data date), by which
 *  rules (the board's version), from what (the board, the chain, the regime, and the levels engine when its levels are
 *  recorded) and why (the fit score and its reasons). */
function signalFor(idea: OptionIdea, rulesVersion: string, levels: Pick<Levels, "version"> | null): Record<string, unknown> {
  const chain = idea.data_as_of?.chain as string;
  const refs: Array<{ kind: string; ref: string; as_of: string }> = [
    { kind: "regime_fit_board", ref: clip(`${idea.underlying} ${idea.structure}${idea.expiry ? ` ${idea.expiry}` : ""}`, 120), as_of: chain },
    { kind: "option_chain", ref: clip(idea.price_source ?? "NSE F&O bhavcopy close", 120), as_of: chain },
  ];
  const regimeAt = idea.data_as_of?.regime;
  if (regimeAt) refs.push({ kind: "market_regime", ref: "desk market regime", as_of: clip(regimeAt, 40) });
  if (levels) refs.push({ kind: "strategy_levels", ref: clip(levels.version ?? "strategy levels", 120), as_of: chain });
  const why = idea.fit.because.map((f) => `${f.state}: ${f.text}`).join(" ");
  return {
    signal_at: chain,
    rule_version: rulesVersion.trim(),
    source_refs: refs,
    evidence_summary: clip(`Fit ${idea.fit.score} to the measured regime.${why ? ` ${why}` : ""}`, 1000),
  };
}

/** The paper-trade body for one idea, or null when it cannot be recorded (paperTradeProblem says why).
 *
 *  Mappings the route requires and the idea does not already use:
 *    * the leg's `quantity` is the route's `lots`, and the route REFUSES an unknown leg field
 *      (LEG_FIELDS), so `iv_pct` is dropped rather than passed through;
 *    * the idea's view (up/down/flat) becomes bullish/bearish/neutral;
 *    * the `signal` (signalFor) is built from the idea and the board.
 *  The stop and target are the levels engine's (tradeLevels), only when the row shows its answer; otherwise none is
 *  sent and the trade exits at expiry or by hand. */
export function paperTradeBodyFor(idea: OptionIdea, ctx: PaperContext): Record<string, unknown> | null {
  if (paperTradeProblem(idea, ctx.rulesVersion)) return null;
  const direction = DIRECTION[idea.view ?? ""];
  const reference = idea.reference_price as number;
  // With a TradePlan the trade records the PLAN's levels and cites it; without one (an older route) the row's levels.
  const fromPlan = idea.trade_plan ? planLevels(idea.trade_plan, direction, reference) : null;
  const levels = fromPlan ? fromPlan.levels : tradeLevels(direction, reference, ctx.levels);
  const recorded = Object.keys(levels).length ? (fromPlan ? { version: fromPlan.version ?? "strategy levels" } : (ctx.levels as Levels)) : null;
  return {
    kind: "strategy",
    underlying: idea.underlying,
    direction,
    family: KNOWN_FAMILIES.has(idea.structure) ? idea.structure : "custom",
    reference_price: reference,
    ...levels,
    legs: idea.legs.map((l) => ({
      kind: l.kind,
      side: l.side,
      lots: l.quantity,
      lot_size: l.lot_size,
      entry_price: l.entry_price,
      expiry: l.expiry ?? null,
      strike: l.strike ?? null,
      option_type: l.option_type ?? null,
      price_source: l.price_source ?? null,
    })),
    signal: signalFor(idea, ctx.rulesVersion as string, recorded),
    note: `Top by regime — fit ${idea.fit.score}`,
    ...(idea.trade_plan ? { plan_ref: planRefOf(idea.trade_plan) } : {}),
  };
}

export interface PaperTradeResult { trade?: { id?: string } }

export function usePaperTradeIdea() {
  const qc = useQueryClient();
  return useMutation<PaperTradeResult, unknown, Record<string, unknown>>({
    mutationFn: async (body) => {
      const res = await http({ method: "POST", path: PAPER_TRADES_PATH, body, noRetry: true });
      return res.data as PaperTradeResult;
    },
    onSuccess: () => { void qc.invalidateQueries({ queryKey: ["copilot", "desk", "paper-trades"] }); },
  });
}
