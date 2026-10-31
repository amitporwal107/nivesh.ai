/**
 * Strategy Builder, "Top by regime" — the shape of POST /api/desk/strategy/top.
 *
 * Written against the live staging response (schema desk.strategy.top.v1, rules regime-fit-v1), not
 * from the route source, so a drift between the two is caught here rather than rendered as blanks.
 *
 * The cash class is deliberately a different shape from the option classes: it is the desk's existing
 * "From AI opportunities" answer kept unchanged, so its ideas carry the scanner's evidence rank and
 * have NO fit score. `ranking_note_cash` on the envelope says so. The screen shows the two side by
 * side rather than pretending one ranking covers both.
 */
import { z } from "zod";
import { TradePlanOrNull } from "./trade-plan";

const Num = z.number().nullable().optional();

export const FitFactorSchema = z.object({
  factor: z.string(),
  state: z.enum(["supports", "neutral", "conflicts"]).catch("neutral"),
  text: z.string(),
});

export const LegSchema = z.object({
  kind: z.string(),
  side: z.string(),
  quantity: Num,
  lot_size: Num,
  entry_price: Num,
  expiry: z.string().nullable().optional(),
  strike: Num,
  option_type: z.string().nullable().optional(),
  iv_pct: Num,
  price_source: z.string().nullable().optional(),
});

const OptionIdeaBase = z.object({
  rank: z.number().nullable().optional(),
  underlying: z.string(),
  /** The spot the legs were priced against; a payoff request and a paper trade both need it. */
  reference_price: Num,
  structure: z.string(),
  name: z.string(),
  view: z.string().nullable().optional(),
  premium_flow: z.string().nullable().optional(),
  expiry: z.string().nullable().optional(),
  days_to_expiry: Num,
  placement: z.string().nullable().optional(),
  legs: z.array(LegSchema).default([]),
  net_greeks: z.object({ delta: Num, gamma: Num, theta: Num, vega: Num }).partial().default({}),
  max_profit: Num,
  max_loss: Num,
  profit_unbounded: z.boolean().nullable().optional(),
  loss_unbounded: z.boolean().nullable().optional(),
  breakevens: z.array(z.number()).default([]),
  net_premium: Num,
  capital_at_risk: Num,
  capital_at_risk_basis: z.string().nullable().optional(),
  /** Net P&L at the chain's own expected move over capital at risk. The ranking number. */
  reward_risk: Num,
  /** The payoff at an underlying price of zero. Shown for reference; never ranked on. */
  reward_risk_theoretical: Num,
  reward_risk_basis: z.string().nullable().optional(),
  net_at_expected_move: Num,
  margin: Num,
  margin_reason: z.string().nullable().optional(),
  caveats: z.array(z.string()).default([]),
  fit: z.object({ score: z.number(), because: z.array(FitFactorSchema).default([]) }),
  data_as_of: z.record(z.string(), z.string().nullable()).nullable().optional(),
  price_source: z.string().nullable().optional(),
  /** Phase 2.1: the idea's canonical TradePlan; the paper trade cites it (plan_ref) and records its levels. */
  trade_plan_id: z.string().nullable().optional(),
  trade_plan: TradePlanOrNull,
  /** N13: a bearish structure on a stock that is a bullish cash setup the same day; not tradeable today. */
  conflicts_with_cash_setup: z.object({ message: z.string().nullable().optional(), cash_direction: z.string().nullable().optional() })
    .passthrough().nullable().optional().catch(null),
});

/** With `distinct: true` each idea is the best structure of its underlying, and the next ones (best first, no rank of
 *  their own) ride along under `alternatives`. Without it the list is empty. */
export const OptionIdeaSchema = OptionIdeaBase.extend({
  alternatives: z.array(OptionIdeaBase).default([]),
});

/** A cash idea comes from the ideas engine untouched, so only the fields the board needs are pinned. */
export const CashIdeaSchema = z.object({
  rank: z.number().nullable().optional(),
  symbol: z.string().nullable().optional(),
  name: z.string().nullable().optional(),
  direction: z.string().nullable().optional(),
  plan_status: z.string().nullable().optional(),
  preferred: z.unknown().nullable().optional(),
}).passthrough();

export const UnavailableSchema = z.object({
  underlying: z.string().nullable().optional(),
  reason: z.string().nullable().optional(),
});

export const UnderlyingContextSchema = z.object({
  underlying: z.string().nullable().optional(),
  spot: Num,
  expiry: z.string().nullable().optional(),
  atm_strike: Num,
  atm_iv: Num,
  pcr: Num,
  max_pain: Num,
  expected_move: Num,
  expected_move_pct: Num,
});

export const OptionClassSchema = z.object({
  as_of: z.string().nullable().optional(),
  ideas: z.array(OptionIdeaSchema).default([]),
  considered: z.number().nullable().optional(),
  underlyings: z.array(UnderlyingContextSchema).default([]),
  unavailable: z.array(UnavailableSchema).default([]),
  /** One row per underlying (the request's `distinct`). */
  distinct: z.boolean().nullable().optional(),
  universe: z.object({
    source: z.string().nullable().optional(),
    symbols_tried: z.array(z.string()).default([]),
    /** `distinct` only: scanner names passed over before any chain read, with the reason (not F&O-listed). */
    skipped: z.array(UnavailableSchema).default([]),
  }).nullable().optional(),
});

export const CashClassSchema = z.object({
  as_of: z.string().nullable().optional(),
  ideas: z.array(CashIdeaSchema).default([]),
  considered: z.number().nullable().optional(),
  unavailable: z.array(UnavailableSchema).default([]),
  ranking: z.string().nullable().optional(),
  source: z.string().nullable().optional(),
  data_as_of: z.unknown().nullable().optional(),
});

export const RegimeSchema = z.object({
  available: z.boolean(),
  key: z.string().nullable().optional(),
  label: z.string().nullable().optional(),
  as_of: z.string().nullable().optional(),
  trend: z.string().nullable().optional(),
  india_vix: Num,
  vix_high_threshold: Num,
  volatility: z.string().nullable().optional(),
  breadth: z.string().nullable().optional(),
  advancing_share_pct: Num,
  nifty_vs_average_pct: Num,
  rule_version: z.string().nullable().optional(),
  source: z.string().nullable().optional(),
  reason: z.string().nullable().optional(),
});

export const TopSchema = z.object({
  schema: z.string(),
  rules_version: z.string(),
  generated_at: z.string().nullable().optional(),
  limit: z.number().nullable().optional(),
  distinct: z.boolean().nullable().optional(),
  regime: RegimeSchema,
  staleness_note: z.string().nullable().optional(),
  classes: z.object({
    index_options: OptionClassSchema.optional(),
    stock_fno: OptionClassSchema.optional(),
    cash: CashClassSchema.optional(),
  }),
  ranking_note: z.string(),
  ranking_note_cash: z.string().nullable().optional(),
  gaps: z.array(z.string()).default([]),
  sent_to_broker: z.boolean().nullable().optional(),
});

export type TopBoard = z.infer<typeof TopSchema>;
export type OptionIdea = z.infer<typeof OptionIdeaSchema>;
/** An idea without its alternatives: what an alternative itself is. Every OptionIdea is one too. */
export type OptionIdeaCore = z.infer<typeof OptionIdeaBase>;
export type OptionClass = z.infer<typeof OptionClassSchema>;
export type CashClass = z.infer<typeof CashClassSchema>;
export type FitFactor = z.infer<typeof FitFactorSchema>;
export type Regime = z.infer<typeof RegimeSchema>;
