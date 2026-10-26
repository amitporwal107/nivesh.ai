/**
 * Strategy Builder, "Top by regime" — turning one ranked idea into a payoff request or a paper trade.
 *
 *   POST /api/desk/strategy/payoff     what-if payoff for the idea's legs (usePayoff, shared with the plan builder)
 *   POST /api/desk/paper-trades        a multi-leg strategy paper trade (kind "strategy")
 *
 * Both reuse what the desk already has rather than adding a second way to price or record a structure,
 * so an idea opened here and the same idea built in "One stock" cannot disagree.
 *
 * Nothing places a real order. The paper-trade route is the desk's own simulator and the Kite wrapper
 * behind the live feed exposes no order method at all.
 */
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { http } from "@/services/api/http";
import type { PayoffRequest } from "./strategy-contract";
import type { OptionIdeaCore as OptionIdea } from "./top-contract";

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

/** The paper-trade body for one idea.
 *
 *  Two mappings the route requires and the idea does not already use:
 *    * the leg's `quantity` is the route's `lots`, and the route REFUSES an unknown leg field
 *      (LEG_FIELDS), so `iv_pct` is dropped rather than passed through;
 *    * the idea's view (up/down/flat) becomes bullish/bearish/neutral.
 *  No stop or target is sent: the route validates those against the reference price per direction, and
 *  a regime-fit idea carries neither, so inventing one here would be inventing a level the engine never
 *  produced. */
export function paperTradeBodyFor(idea: OptionIdea): Record<string, unknown> | null {
  if (idea.reference_price == null || !idea.legs.length) return null;
  const direction = DIRECTION[idea.view ?? ""] ?? null;
  if (!direction) return null;
  return {
    kind: "strategy",
    underlying: idea.underlying,
    direction,
    family: KNOWN_FAMILIES.has(idea.structure) ? idea.structure : "custom",
    reference_price: idea.reference_price,
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
    note: `Top by regime — fit ${idea.fit.score}`,
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
