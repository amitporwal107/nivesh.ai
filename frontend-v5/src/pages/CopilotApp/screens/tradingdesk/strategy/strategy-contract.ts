/**
 * Strategy Builder — the payoff calculation's contract (PRD §16.6; shared brief of the Strategy Builder wave).
 *
 *   POST /api/desk/strategy/payoff   pure calculation: no database write, nothing sent to a broker
 *
 * The zod schemas below are what the screen trusts. Nullability follows the route: a figure it cannot
 * know is null (never 0) and the screen shows "—"; a list the route always sends is required, so a body
 * without it is a contract error and never an empty chart. Unknown extra fields are allowed
 * (`passthrough`), so the route can grow without breaking the screen.
 */
import { z } from "zod";

// ── request ──────────────────────────────────────────────────────────────

export const LegKind = z.enum(["cash", "future", "option"]);
export type LegKind = z.infer<typeof LegKind>;

export const PayoffLegSchema = z.object({
  kind: LegKind,
  side: z.enum(["buy", "sell"]),
  /** Shares for cash; LOTS for a future or an option. */
  quantity: z.number(),
  /** 1 for cash; the contract multiplier otherwise. */
  lot_size: z.number(),
  /** Per share / unit; for an option the premium per unit. */
  entry_price: z.number(),
  expiry: z.string().nullable().optional(),
  strike: z.number().nullable().optional(),
  option_type: z.enum(["call", "put"]).nullable().optional(),
  price_source: z.string().nullable().optional(),
  iv_pct: z.number().nullable().optional(),
  underlying: z.string().optional(),
});
export type PayoffLeg = z.infer<typeof PayoffLegSchema>;

export const PayoffGridSchema = z.union([
  z.object({ min: z.number(), max: z.number(), points: z.number() }),
  z.object({ from_pct: z.number(), to_pct: z.number(), points: z.number() }),
]);
export type PayoffGrid = z.infer<typeof PayoffGridSchema>;

export const PayoffRequestSchema = z.object({
  underlying: z.string(),
  /** The underlying's last close. */
  reference_price: z.number(),
  /** YYYY-MM-DD, the date the entry prices belong to. */
  as_of: z.string().optional(),
  legs: z.array(PayoffLegSchema).min(1),
  grid: PayoffGridSchema.optional(),
  /** slippage_pct is in percent (0.05 means 0.05%). */
  costs: z.object({ slippage_pct: z.number().optional(), brokerage_per_side: z.number().optional() }).optional(),
  scenarios: z.array(z.object({ name: z.string(), underlying_price: z.number() })).optional(),
  pre_expiry: z.object({ date: z.string(), iv_shift_pct: z.number().optional(), rate_pct: z.number().optional() }).optional(),
});
export type PayoffRequest = z.infer<typeof PayoffRequestSchema>;

// ── response ─────────────────────────────────────────────────────────────

const numOrNull = z.number().nullable().catch(null);
const numList = z.array(z.number());

export const ProblemSchema = z.object({ field: z.string().nullable().optional(), code: z.string(), message: z.string() }).passthrough();
export const WarningSchema = z.object({ code: z.string(), message: z.string() }).passthrough();

export const PerLegSchema = z.object({
  index: z.number(),
  label: z.string(),
  gross: z.array(z.number().nullable()),
}).passthrough();

export const ScenarioPointSchema = z.object({
  name: z.string(),
  underlying_price: z.number(),
  gross: numOrNull,
  net: numOrNull,
}).passthrough();

export const ExpirySchema = z.object({
  grid: numList,
  gross: numList,
  net: numList,
  per_leg: z.array(PerLegSchema).catch([]),
  breakevens: numList.catch([]),
  max_profit: numOrNull,
  max_loss: numOrNull,
  profit_unbounded: z.boolean().catch(false),
  loss_unbounded: z.boolean().catch(false),
  net_premium: numOrNull,
  scenarios: z.array(ScenarioPointSchema).catch([]),
  /** The same extremes over the plotted grid only. */
  range_max_profit: numOrNull.optional(),
  range_max_loss: numOrNull.optional(),
  extremes_basis: z.string().nullable().catch(null).optional(),
}).passthrough();
export type PayoffExpiry = z.infer<typeof ExpirySchema>;

/** The position's Greeks at the reference price: delta per ₹1, theta per day, vega per vol point, rho per 1 pp of rate. */
export const GreeksSchema = z.object({ delta: numOrNull, gamma: numOrNull, theta: numOrNull, vega: numOrNull, rho: numOrNull }).passthrough();
export type Greeks = z.infer<typeof GreeksSchema>;

/** When the estimate was requested but an option leg cannot be priced, grid, gross, net and greeks are all null and `unavailable` says why. */
export const PreExpirySchema = z.object({
  date: z.string(),
  model: z.string(),
  assumptions: z.record(z.unknown()).catch({}),
  grid: numList.nullable().catch(null),
  gross: numList.nullable().catch(null),
  net: numList.nullable().catch(null),
  greeks: GreeksSchema.nullable().catch(null),
  per_leg_greeks: z.array(z.object({ leg: z.number(), label: z.string().optional(), greeks: GreeksSchema.nullable().catch(null) }).passthrough()).catch([]),
  unavailable: z.array(z.object({ leg: z.number(), reason: z.string() }).passthrough()).catch([]),
}).passthrough();
export type PayoffPreExpiry = z.infer<typeof PreExpirySchema>;

export const CostsSchema = z.object({
  model: z.string().nullable().catch(null),
  entry: numOrNull,
  exit_at_expiry: numOrNull,
  round_trip: numOrNull,
  excluded: z.array(z.string()).catch([]),
  exit_basis: z.string().nullable().catch(null).optional(),
  per_leg: z.array(z.object({ index: z.number(), entry: numOrNull, exit_at_expiry: numOrNull, round_trip: numOrNull }).passthrough()).catch([]).optional(),
}).passthrough();

export const MarginSchema = z.object({ estimate: numOrNull, source: z.string().nullable().catch(null) }).passthrough();

export const PayoffResponseSchema = z.object({
  valid: z.boolean(),
  problems: z.array(ProblemSchema).catch([]),
  warnings: z.array(WarningSchema).catch([]),
  calculation_version: z.string().nullable().catch(null),
  /** Absent when the structure was rejected (`valid` false). */
  expiry: ExpirySchema.nullable().optional(),
  pre_expiry: PreExpirySchema.nullable().optional(),
  costs: CostsSchema.nullable().optional(),
  margin: MarginSchema.nullable().optional(),
  /** The worst NET loss over all prices (conservative: every leg charged both sides); null when the loss is unbounded. */
  capital_at_risk: numOrNull.optional(),
  capital_at_risk_basis: z.string().nullable().catch(null).optional(),
  /** Null from the payoff route (it does not estimate margin); why is `margin_reason`. The F&O builder fills it from Zerodha's margin calculator. */
  margin_reason: z.string().nullable().catch(null).optional(),
  loss_can_exceed_margin: z.boolean().catch(false).optional(),
  underlying: z.string().optional(),
  reference_price: z.number().optional(),
  as_of: z.string().optional(),
  caveats: z.array(z.string()).catch([]),
  sent_to_broker: z.boolean().catch(false),
}).passthrough().superRefine((v, ctx) => {
  // A valid answer always carries the expiry payoff; without it the chart would be an empty success.
  if (v.valid && !v.expiry) ctx.addIssue({ code: z.ZodIssueCode.custom, path: ["expiry"], message: "a valid answer has no expiry payoff" });
});
export type PayoffResponse = z.infer<typeof PayoffResponseSchema>;
export type PayoffProblem = z.infer<typeof ProblemSchema>;
