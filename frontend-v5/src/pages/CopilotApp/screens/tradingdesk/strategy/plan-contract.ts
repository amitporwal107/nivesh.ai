/**
 * Strategy Builder — the plan routes' contract (PRD §16.5, §16.11; backend/routes/strategy_plan.py,
 * services/strategy_plan/plan.py).
 *
 *   POST   /api/desk/strategy/plan              build a StrategyPlan (reads sources, writes nothing)
 *   POST   /api/desk/strategy/plans             save a built plan { plan } (immutable after save)
 *   GET    /api/desk/strategy/plans             the user's saved plans, newest first
 *   GET    /api/desk/strategy/plans/{id}        one saved plan
 *   DELETE /api/desk/strategy/plans/{id}        deletes only the saved copy
 *
 * The zod schemas are what the screen trusts. A number the route cannot know is null (never 0) and the
 * screen shows "—". A list the route always sends is required, so a body without it is a contract error and
 * never an empty plan. Unknown extra fields pass through (a saved plan is sent back to the route unchanged,
 * and the route checks its fingerprint, so nothing is stripped from it here).
 */
import { z } from "zod";
import { TradePlanOrNull } from "./trade-plan";
import { ExpirySchema, PreExpirySchema, CostsSchema, MarginSchema, type PayoffLeg } from "./strategy-contract";

const numOrNull = z.number().nullable().catch(null);
const strOrNull = z.string().nullable().catch(null);

export const STATUSES = ["plan", "wait", "no_trade", "insufficient_data"] as const;
export type PlanStatus = (typeof STATUSES)[number];
export const CANDIDATE_STATUSES = ["candidate", "wait", "no_trade", "avoid", "insufficient_data"] as const;
export type CandidateStatus = (typeof CANDIDATE_STATUSES)[number];

export const DIRECTIONS = ["bullish", "bearish", "neutral", "vol_expansion", "vol_contraction"] as const;
export type Direction = (typeof DIRECTIONS)[number];
export const HORIZONS = ["intraday", "positional", "longer_term"] as const;
export type Horizon = (typeof HORIZONS)[number];
export const INSTRUMENTS = ["all", "cash", "futures", "options", "combination"] as const;
export type Instrument = (typeof INSTRUMENTS)[number];

const ReasonSchema = z.object({ code: z.string(), message: z.string() }).passthrough();
export type Reason = z.infer<typeof ReasonSchema>;

/** The stocks an `unknown_symbol` reason offers instead (the route's lookup): symbol, name, whether it has prices. Empty for any other reason. */
export interface ReasonSuggestion { symbol: string; name: string | null }
export function reasonSuggestions(r: Reason): ReasonSuggestion[] {
  const raw = (r as { suggestions?: unknown }).suggestions;
  if (!Array.isArray(raw)) return [];
  return raw.flatMap((x) => (x && typeof x === "object" && typeof (x as { symbol?: unknown }).symbol === "string"
    ? [{ symbol: (x as { symbol: string }).symbol, name: typeof (x as { name?: unknown }).name === "string" ? (x as { name: string }).name : null }] : []));
}

export const PlanInputsSchema = z.object({
  underlying: z.string(),
  direction: z.string(),
  horizon: z.string(),
  horizon_days: numOrNull,
  instrument: z.string(),
  capital: numOrNull,
  risk_budget_inr: numOrNull,
  risk_pct: numOrNull,
  max_allocation_pct: numOrNull,
  min_reward_risk: numOrNull,
  avoid_events: z.boolean().catch(true),
  allow_multi_leg: z.boolean().catch(true),
  expiry: strOrNull,
  costs: z.object({ slippage_pct: z.number().optional(), brokerage_per_side: z.number().optional() }).nullable().catch(null),
  defaults_applied: z.array(z.string()).catch([]),
}).passthrough();
export type PlanInputs = z.infer<typeof PlanInputsSchema>;

export const EvidenceItemSchema = z.object({
  group: z.string(),
  key: z.string(),
  value: z.unknown().nullable().catch(null),
  interpretation: z.string().catch(""),
  direction: z.enum(["supports", "conflicts", "neutral", "unavailable"]).catch("unavailable"),
  source: strOrNull,
  source_as_of: strOrNull,
  version: strOrNull,
}).passthrough();
export type EvidenceItem = z.infer<typeof EvidenceItemSchema>;

const GroupCountsSchema = z.object({ supports: z.number(), conflicts: z.number(), neutral: z.number(), unavailable: z.number() }).partial();

const SizingSchema = z.object({
  status: z.string(),
  unit: strOrNull,
  formula: strOrNull,
  risk_budget_inr: numOrNull,
  capital_inr: numOrNull,
  max_allocation_pct: numOrNull,
  risk_per_unit: numOrNull,
  risk_basis: strOrNull,
  value_per_unit: numOrNull,
  lot_units: numOrNull,
  missing: z.array(z.string()).catch([]),
  quantity: numOrNull,
  units: numOrNull.optional(),
  by_risk_budget: numOrNull.optional(),
  by_allocation_cap: numOrNull.optional(),
  binding: strOrNull.optional(),
  risk_at_stop_inr: numOrNull.optional(),
  /** For a cash or futures candidate: the estimated round-trip costs at the stop and the loss at the stop after them
   *  (the quantity is sized on that, backend services/strategy_plan/candidates.size_position). */
  costs_at_stop_inr: numOrNull.optional(),
  /** Those costs by component (brokerage, STT, exchange, SEBI, stamp, GST, slippage; the desk cost card). */
  costs_breakdown_at_stop: z.record(z.number()).nullish(),
  risk_at_stop_net_inr: numOrNull.optional(),
  deployed_inr: numOrNull.optional(),
}).passthrough();
export type Sizing = z.infer<typeof SizingSchema>;

const LevelSchema = z.object({ name: z.string(), price: numOrNull, rule: z.string().catch(""), gate: z.boolean().catch(false) }).passthrough();
export type Level = z.infer<typeof LevelSchema>;

const RiskRewardSchema = z.object({
  gross: numOrNull, net: numOrNull, level: strOrNull.optional(), reward_gross: numOrNull.optional(), reward_net: numOrNull.optional(),
  risk_gross: numOrNull.optional(), risk_net: numOrNull.optional(), basis: strOrNull.optional(),
  by_level: z.record(z.object({ gross: numOrNull, net: numOrNull }).passthrough()).catch({}).optional(),
}).passthrough();
export type RiskReward = z.infer<typeof RiskRewardSchema>;

const LegSchema = z.object({
  kind: z.enum(["cash", "future", "option"]),
  side: z.enum(["buy", "sell"]),
  quantity: z.number(),
  lot_size: z.number(),
  entry_price: z.number(),
  expiry: strOrNull,
  strike: numOrNull.optional(),
  option_type: z.enum(["call", "put"]).nullable().catch(null).optional(),
  price_source: strOrNull,
  iv_pct: numOrNull.optional(),
}).passthrough();
export type PlanLeg = z.infer<typeof LegSchema>;

/** The candidate's own payoff block: the payoff route's answer for the sized legs. */
const CandidatePayoffSchema = z.object({
  valid: z.boolean().catch(false),
  problems: z.array(ReasonSchema.partial({ code: true }).passthrough()).catch([]),
  warnings: z.array(z.object({ code: z.string(), message: z.string() }).passthrough()).catch([]),
  calculation_version: strOrNull,
  expiry: ExpirySchema.nullable().optional(),
  pre_expiry: PreExpirySchema.nullable().optional(),
  costs: CostsSchema.nullable().optional(),
  margin: MarginSchema.nullable().optional(),
  margin_reason: strOrNull.optional(),
  capital_at_risk: numOrNull.optional(),
  capital_at_risk_basis: strOrNull.optional(),
  loss_can_exceed_margin: z.boolean().catch(false).optional(),
  underlying: z.string().optional(),
  reference_price: z.number().optional(),
  as_of: z.string().optional(),
  caveats: z.array(z.string()).catch([]),
  sent_to_broker: z.boolean().catch(false),
}).passthrough();
export type CandidatePayoff = z.infer<typeof CandidatePayoffSchema>;

const OptionsSelectionSchema = z.object({
  expiry: strOrNull,
  days_to_expiry: numOrNull,
  expiry_why: strOrNull,
  eligible_expiries: z.array(z.object({ expiry: z.string(), days_to_expiry: numOrNull }).passthrough()).catch([]),
  eligible_expiries_note: strOrNull,
  eligible_strikes: z.array(z.number()).catch([]),
  strikes_source: strOrNull,
  chosen: z.record(z.number().nullable()).catch({}),
  why: strOrNull,
  rule: strOrNull,
  alternatives: z.array(z.object({
    plan: z.record(z.number().nullable()).catch({}),
    why: strOrNull,
    blockers: z.array(z.unknown()).catch([]),
    flags: z.array(z.unknown()).catch([]),
    metrics: z.object({ max_loss: numOrNull, max_profit: numOrNull, breakevens: z.array(z.number()).catch([]), capital_at_risk: numOrNull, risk_reward: RiskRewardSchema.nullable().catch(null) }).passthrough().nullable().catch(null),
  }).passthrough()).catch([]),
  preferred_flags: z.array(z.unknown()).catch([]),
  preferred_leg_facts: z.array(z.object({
    strike: numOrNull, option_type: strOrNull, side: strOrNull, close: numOrNull, oi: numOrNull, volume: numOrNull, iv: numOrNull, delta: numOrNull,
    median_oi: numOrNull, median_volume: numOrNull,
  }).passthrough()).catch([]),
  liquidity_proxy: strOrNull,
  stale: z.boolean().catch(false),
  chain_as_of: strOrNull,
  reference_session: strOrNull,
}).passthrough();
export type OptionsSelection = z.infer<typeof OptionsSelectionSchema>;

export const CandidateSchema = z.object({
  id: z.string(),
  segment: z.enum(["cash", "futures", "options", "combination"]),
  family: z.string(),
  label: z.string(),
  direction: z.string(),
  status: z.enum(CANDIDATE_STATUSES),
  reasons: z.array(ReasonSchema).catch([]),
  why_qualifies: z.array(z.string()).catch([]),
  conflicts: z.array(z.unknown()).catch([]),
  missing: z.array(z.unknown()).catch([]),
  legs: z.array(LegSchema).catch([]),
  entry: z.object({ trigger: numOrNull, zone: z.unknown().nullable().catch(null), logic: strOrNull }).passthrough().nullable().catch(null),
  invalidation: z.object({
    technical: z.object({ price: numOrNull, basis: strOrNull, meaning: strOrNull }).passthrough().nullable().catch(null),
    execution_stop: z.object({ price: numOrNull, note: strOrNull }).passthrough().nullable().catch(null),
  }).passthrough().nullable().catch(null),
  targets: z.array(LevelSchema).catch([]),
  risk_reward: RiskRewardSchema.nullable().catch(null),
  sizing: SizingSchema.nullable().catch(null),
  options_selection: OptionsSelectionSchema.nullable().catch(null),
  payoff: CandidatePayoffSchema.nullable().catch(null),
  warnings: z.array(z.string()).catch([]),
  actionable: z.boolean().catch(false),
  sent_to_broker: z.boolean().catch(false),
  /** Phase 2.1: the candidate's canonical TradePlan; the paper trade cites it and records its levels. */
  trade_plan: TradePlanOrNull,
}).passthrough();
export type Candidate = z.infer<typeof CandidateSchema>;

export const AlternativeSchema = z.object({
  id: z.string(),
  segment: z.string(),
  family: z.string(),
  label: z.string(),
  status: z.string(),
  max_loss: numOrNull,
  max_loss_basis: strOrNull,
  /** "stop": `max_loss` is the loss at the stop (cash, futures, and shares or a future with no long put under them, e.g. the
   *  covered call); "expiry": the expiry payoff's defined worst case. Absent from an engine older than 30 Oct 2026. */
  max_loss_at: z.enum(["stop", "expiry"]).nullable().catch(null).optional(),
  capital_at_risk: numOrNull,
  breakeven: z.array(z.number()).nullable().catch(null),
  reward_risk_net: numOrNull,
  reward_risk_gross: numOrNull,
  liquidity_flags: z.array(z.unknown()).catch([]),
  horizon_days: numOrNull,
  evidence_quality: z.object({ label: z.string().catch("—"), supports: z.number().catch(0), conflicts: z.number().catch(0), unavailable: z.number().catch(0) }).passthrough().nullable().catch(null),
  why_unsuitable: strOrNull,
}).passthrough();
export type Alternative = z.infer<typeof AlternativeSchema>;

const SnapshotSchema = z.object({
  key: z.string(), source: strOrNull, as_of: strOrNull, version: strOrNull, ok: z.boolean(), error: strOrNull, content_hash: strOrNull,
}).passthrough();
export type Snapshot = z.infer<typeof SnapshotSchema>;

export const PlanSchema = z.object({
  plan_id: z.string(),
  schema: z.string(),
  rules_version: z.string(),
  calculation_version: z.string(),
  generated_at: z.string(),
  data_as_of: z.object({ price: strOrNull, fno: strOrNull, reference_session: strOrNull, mode: strOrNull, fundamentals: strOrNull, regime: strOrNull }).passthrough(),
  inputs: PlanInputsSchema,
  inputs_hash: z.string(),
  rules: z.record(z.unknown()).catch({}),
  underlying: z.object({ symbol: z.string(), spot: numOrNull, spot_as_of: strOrNull, spot_source: strOrNull }).passthrough(),
  status: z.enum(STATUSES),
  status_reasons: z.array(ReasonSchema).catch([]),
  would_change_if: z.array(z.string()).catch([]),
  summary: z.object({
    underlying: z.string(), segment: z.string(), direction: z.string(), horizon: z.string(), horizon_days: numOrNull, family: strOrNull,
    preferred_segment: strOrNull, status: z.string(), generated_at: z.string(), data_as_of: strOrNull, end_of_day: z.boolean().catch(true),
  }).passthrough(),
  thesis: z.object({
    direction: z.string(),
    supports: z.array(z.object({ group: z.string(), key: z.string(), interpretation: z.string() }).passthrough()).catch([]),
    conflicts: z.array(z.object({ group: z.string(), key: z.string(), interpretation: z.string() }).passthrough()).catch([]),
    unavailable: z.array(z.string()).catch([]),
    note: strOrNull,
  }).passthrough(),
  evidence: z.array(EvidenceItemSchema),
  evidence_summary: z.record(GroupCountsSchema).catch({}),
  headline: z.object({
    technical_setup: z.object({ label: z.string(), counts: GroupCountsSchema.optional(), scanner_bucket: strOrNull, note: strOrNull }).passthrough(),
    fundamental_context: z.object({
      role: z.string().catch(""), available: z.record(z.unknown()).catch({}), missing: z.array(z.string()).catch([]), valuation_vs_peers: z.record(z.unknown()).nullable().catch(null),
    }).passthrough(),
    model_estimate: z.object({ status: z.string(), reason: strOrNull, value: z.unknown().nullable().catch(null) }).passthrough(),
    data_quality: z.object({
      label: z.string(), unavailable_items: z.number().catch(0), total_items: z.number().catch(0), unavailable: z.array(z.string()).catch([]),
      mode: strOrNull, price_as_of: strOrNull, reference_session: strOrNull,
    }).passthrough(),
    confidence: z.unknown().nullable().catch(null),
    confidence_note: strOrNull,
  }).passthrough(),
  candidates: z.array(CandidateSchema),
  preferred: strOrNull,
  ranking: strOrNull,
  alternatives: z.array(AlternativeSchema),
  failure_conditions: z.array(z.string()).catch([]),
  validation: z.object({
    status: z.string(),
    reasons: z.array(z.string()).catch([]),
    in_sample_record: z.object({
      rows: z.array(z.object({
        metric: z.string(), horizon_days: numOrNull, sample_count: numOrNull, moves_count: numOrNull, probability: numOrNull,
        ci95_lo: numOrNull, ci95_hi: numOrNull, avg_fwd_return: numOrNull, avg_fwd_drawdown: numOrNull,
      }).passthrough()).catch([]),
      source: strOrNull,
      label: strOrNull,
    }).passthrough().nullable().catch(null),
    label: strOrNull.optional(),
  }).passthrough(),
  scenarios: z.object({
    basis: strOrNull, horizon_days: numOrNull,
    origin: z.object({ as_of: strOrNull, price: numOrNull, source: strOrNull }).passthrough().nullable().catch(null),
    levels: z.array(LevelSchema).catch([]),
    from_candidate: strOrNull,
    model_path: z.object({ status: z.string(), reason: strOrNull }).passthrough().nullable().catch(null),
    label: strOrNull,
  }).passthrough(),
  lifecycle: z.object({ status: z.string(), states: z.array(z.string()).catch([]), note: strOrNull }).passthrough(),
  source_snapshots: z.array(SnapshotSchema),
  caveats: z.array(z.string()).catch([]),
  sent_to_broker: z.boolean().catch(false),
}).passthrough();
export type StrategyPlan = z.infer<typeof PlanSchema>;

export const SavedPlanSchema = z.object({ id: z.string(), saved_at: z.string(), plan: PlanSchema, sent_to_broker: z.boolean().catch(false) }).passthrough();
export type SavedPlan = z.infer<typeof SavedPlanSchema>;

export const SavedSummarySchema = z.object({
  id: z.string(), plan_id: z.string(), saved_at: z.string(), underlying: strOrNull, direction: strOrNull, horizon: strOrNull, segment: strOrNull,
  family: strOrNull, status: strOrNull, data_as_of: strOrNull, rules_version: strOrNull, lifecycle: strOrNull,
}).passthrough();
export type SavedSummary = z.infer<typeof SavedSummarySchema>;

export const SavedListSchema = z.object({
  plans: z.array(SavedSummarySchema), count: z.number(), limit: z.number().catch(100), max_saved: z.number().catch(200),
}).passthrough();
export type SavedList = z.infer<typeof SavedListSchema>;

export const DeleteAnswerSchema = z.object({ deleted: z.boolean(), id: z.string(), note: strOrNull }).passthrough();

// ── helpers the screen shares ────────────────────────────────────────────

export const GROUPS = ["market_context", "technical", "fundamental", "catalysts", "derivatives", "validation", "portfolio_fit"] as const;
export type Group = (typeof GROUPS)[number];

export const GROUP_TITLE: Record<string, { trader: string; plain: string }> = {
  market_context: { trader: "Market context", plain: "The market around it" },
  technical: { trader: "Technical", plain: "The price chart" },
  fundamental: { trader: "Fundamental", plain: "The business" },
  catalysts: { trader: "Catalysts and event risk", plain: "News and dates that could move it" },
  derivatives: { trader: "Derivatives", plain: "Futures and options activity" },
  validation: { trader: "Validation", plain: "How well this has worked before" },
  portfolio_fit: { trader: "Portfolio fit", plain: "How it fits what you hold" },
};

/** The plan's legs as payoff-route legs (the shape usePayoff takes): the same numbers the plan was built with. */
export function payoffLegs(legs: PlanLeg[]): PayoffLeg[] {
  return legs.map((l) => ({
    kind: l.kind, side: l.side, quantity: l.quantity, lot_size: l.lot_size, entry_price: l.entry_price, expiry: l.expiry ?? null,
    strike: l.strike ?? null, option_type: l.option_type ?? null, price_source: l.price_source ?? null, iv_pct: l.iv_pct ?? null,
  }));
}

/** "weeks" of the route's problems keyed by field, for the inputs form. */
export interface FieldProblem { field: string; code: string; message: string }
