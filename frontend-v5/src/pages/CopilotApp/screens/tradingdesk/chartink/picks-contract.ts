/**
 * Best picks from the user's Chartink scans - the route's contract.
 *
 *   GET /api/desk/chartink/picks?limit=&direction=   ranked picks with an evidence score (0-100, not a probability), the factor breakdown,
 *                                                    reasons for and against, a Wait / No trade list, and the Strategy Builder's strategies per pick
 *
 * Reads sources, writes nothing, sends nothing to a broker (`sent_to_broker` false). The zod schemas are what the screen trusts. The `picks` list is
 * required: a body without it is a contract error and never an empty list. A figure the route cannot know is null and shown as "-". Extra fields pass
 * through. Nothing here recomputes a score, a factor or a strategy figure.
 */
import { z } from "zod";
import { IdeaStrategySchema } from "../strategy/ideas-contract";
import { PayoffRequestSchema } from "../strategy/strategy-contract";

const numOrNull = z.number().nullable().catch(null);
const strOrNull = z.string().nullable().catch(null);
const strList = z.array(z.string()).catch([]);

export const FACTOR_STATES = ["supports", "neutral", "conflicts", "unavailable", "not_applicable"] as const;
export type FactorState = (typeof FACTOR_STATES)[number];

export const FactorSchema = z.object({
  key: z.string(),
  label: z.string(),
  weight: z.number().catch(0),
  points: z.number().catch(0),
  state: z.enum(FACTOR_STATES).catch("unavailable"),
  text: z.string().catch(""),
  value: z.unknown().optional(),
  source: strOrNull,
  as_of: strOrNull,
}).passthrough();
export type PickFactor = z.infer<typeof FactorSchema>;

export const ReasonSchema = z.object({ key: z.string(), label: z.string().catch(""), text: z.string().catch(""), points: numOrNull, weight: numOrNull, source: strOrNull, as_of: strOrNull }).passthrough();
export type PickReason = z.infer<typeof ReasonSchema>;

const ScanRef = z.object({ id: z.union([z.string(), z.number()]).transform(String), name: z.string(), direction: strOrNull }).passthrough();

/** A strategy of the plan (the ideas board's shape) plus the body that draws its payoff through POST /api/desk/strategy/payoff. */
export const PickStrategySchema = IdeaStrategySchema.extend({ payoff_request: PayoffRequestSchema.nullable().catch(null) });
export type PickStrategy = z.infer<typeof PickStrategySchema>;

export const OUTCOMES = ["pick", "wait", "no_trade"] as const;
export type PickOutcome = (typeof OUTCOMES)[number];

export const PickSchema = z.object({
  rank: numOrNull,
  symbol: z.string(),
  name: strOrNull,
  source: z.enum(["chartink", "both"]).nullable().catch(null),
  in_ai_scanner: z.boolean().nullable().catch(null),
  ai_score: numOrNull,
  direction: z.enum(["long", "short"]).nullable().catch(null),
  action: strOrNull,
  outcome: z.enum(OUTCOMES).catch("wait"),
  score: numOrNull,
  score_label: z.string().catch("evidence score — not a probability"),
  scans: z.object({ aligned: z.array(ScanRef).catch([]), opposed: z.array(ScanRef).catch([]), count: z.number().catch(0) }).passthrough()
    .catch({ aligned: [], opposed: [], count: 0 }),
  factors: z.array(FactorSchema).catch([]),
  available_weight_pct: numOrNull,
  reasons_for: z.array(ReasonSchema).catch([]),
  reasons_against: z.array(ReasonSchema).catch([]),
  unavailable: z.array(ReasonSchema).catch([]),
  wait_reasons: strList,
  plan_id: strOrNull,
  plan_status: strOrNull,
  preferred: strOrNull,
  strategies: z.array(PickStrategySchema).catch([]),
  data_as_of: z.record(z.unknown()).nullable().catch(null),
  fno_eligible: z.boolean().nullable().catch(null),
  close: numOrNull,
  plan_inputs: z.record(z.unknown()).nullable().catch(null),
}).passthrough();
export type Pick = z.infer<typeof PickSchema>;

export const PICK_STATES = ["ok", "no_source", "not_refreshed", "stale", "failed"] as const;
export type PicksState = (typeof PICK_STATES)[number];

export const PicksSchema = z.object({
  state: z.enum(PICK_STATES).catch("failed"),
  reason: strOrNull,
  label: z.string().catch("evidence score — not a probability"),
  generated_at: strOrNull,
  limit: numOrNull,
  direction_filter: strOrNull,
  dashboard_id: strOrNull.optional(),
  rules_version: strOrNull,
  ranking_note: strOrNull,
  data_as_of: z.object({
    mode: strOrNull, price: strOrNull, fno: strOrNull, scan_eligibility: strOrNull,
    chartink: z.object({ scan_date: strOrNull, fetched_at: strOrNull, mode: strOrNull }).passthrough().nullable().catch(null),
  }).passthrough().catch({ mode: null, price: null, fno: null, scan_eligibility: null, chartink: null }),
  considered: z.number().catch(0),
  evaluated: z.number().catch(0),
  not_evaluated: z.number().catch(0),
  qualified: z.number().catch(0),
  returned: z.number().catch(0),
  picks: z.array(PickSchema),
  wait: z.array(PickSchema).catch([]),
  excluded: z.array(z.object({ symbol: z.string(), code: strOrNull, reason: z.string().catch("") }).passthrough()).catch([]),
  empty_reason: strOrNull,
  shortfall_reason: strOrNull,
  coverage_note: strOrNull.optional().transform((v) => v ?? null),
  source_failures: z.array(z.unknown()).catch([]),
  caveats: strList,
  sent_to_broker: z.boolean().catch(false),
}).passthrough();
export type ChartinkPicks = z.infer<typeof PicksSchema>;
