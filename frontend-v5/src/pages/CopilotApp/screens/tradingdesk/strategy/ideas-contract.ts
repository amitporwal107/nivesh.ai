/**
 * Strategy Builder, "From AI opportunities" - the ideas route's contract.
 *
 *   POST /api/desk/strategy/ideas   picks the scanner's top setups and lists the cash, futures, options and
 *                                   combination strategies for each (reads sources, writes nothing, sent_to_broker false)
 *
 * The zod schemas are what the screen trusts. A number the route cannot know is null (never 0) and the screen
 * shows "-". The `ideas` list is required: a body without it is a contract error and never an empty board.
 * Extra fields pass through. Nothing here recomputes a figure.
 */
import { z } from "zod";

const numOrNull = z.number().nullable().catch(null);
const strOrNull = z.string().nullable().catch(null);
const strList = z.array(z.string()).catch([]);
const ReasonSchema = z.object({ code: z.string().catch(""), message: z.string().catch("") }).passthrough();

export const ScannerSchema = z.object({
  bucket: strOrNull,
  status: strOrNull,
  score: numOrNull,
  close: numOrNull,
  close_date: strOrNull,
  entry: numOrNull,
  stop: numOrNull,
  target: numOrNull,
  reason: strOrNull,
  horizon_days: numOrNull,
  horizon_days_min: numOrNull,
  liquidity_cr: numOrNull,
  atr_pct: numOrNull,
  stage: strOrNull,
  confidence: strOrNull,
  risk_reward: numOrNull,
  reasons: strList,
  in_watchlist: z.boolean().nullable().catch(null),
  in_picks: z.boolean().nullable().catch(null),
  sector: strOrNull,
}).passthrough();
export type IdeaScanner = z.infer<typeof ScannerSchema>;

const Counts = z.object({ supports: z.number().catch(0), conflicts: z.number().catch(0), neutral: z.number().catch(0), unavailable: z.number().catch(0) }).passthrough();
export type EvidenceCounts = z.infer<typeof Counts>;
export const EVIDENCE_GROUPS = ["technical", "fundamental", "derivatives", "market_context", "catalysts", "validation", "portfolio"] as const;

export const OiViewSchema = z.object({
  buildup: z.unknown().nullable().catch(null),
  cash_confirmation: z.unknown().nullable().catch(null),
  pcr: numOrNull,
  max_pain: numOrNull,
  call_wall: numOrNull,
  put_wall: numOrNull,
  source_as_of: strOrNull,
  expected_move: numOrNull,
  chain_expiry: strOrNull,
  atm_iv: numOrNull,
  unavailable: strList,
}).passthrough();
export type OiView = z.infer<typeof OiViewSchema>;

export const SizingSchema = z.object({
  status: strOrNull, quantity: numOrNull, lots: numOrNull, binding: strOrNull, unit: strOrNull,
  risk_budget_inr: numOrNull, risk_at_stop_inr: numOrNull, deployed_inr: numOrNull, missing: strList,
}).passthrough();

export const IdeaStrategySchema = z.object({
  id: z.string(),
  segment: z.string(),
  family: z.string().catch(""),
  label: z.string(),
  status: z.string(),
  reasons: z.array(ReasonSchema).catch([]),
  legs_text: strOrNull,
  max_loss: numOrNull,
  max_loss_basis: strOrNull,
  capital_at_risk: numOrNull,
  max_profit: numOrNull,
  profit_unbounded: z.boolean().catch(false),
  breakeven: z.array(z.number()).catch([]),
  reward_risk_net: numOrNull,
  reward_risk_gross: numOrNull,
  actionable: z.boolean().catch(false),
  sizing: SizingSchema.nullable().catch(null),
  liquidity_flags: z.array(z.unknown()).catch([]),
  why: strOrNull,
  flags: z.array(z.unknown()).catch([]),
}).passthrough();
export type IdeaStrategy = z.infer<typeof IdeaStrategySchema>;

/** Where an idea came from: the AI scanner, the user's Chartink scans, or both. Absent on an older route. */
export const IDEA_SOURCES = ["ai_scanner", "chartink", "both"] as const;
export type IdeaSource = (typeof IDEA_SOURCES)[number];
export const IdeaChartinkSchema = z.object({
  scans: z.array(z.object({ id: z.union([z.string(), z.number()]).transform(String), name: z.string(), direction: strOrNull }).passthrough()).catch([]),
  count: z.number().catch(0),
  fetched_at: strOrNull,
}).passthrough();
export type IdeaChartink = z.infer<typeof IdeaChartinkSchema>;

export const IdeaSchema = z.object({
  rank: z.number().catch(0),
  source: z.enum(IDEA_SOURCES).nullable().catch(null),
  chartink: IdeaChartinkSchema.nullable().catch(null),
  symbol: z.string(),
  name: strOrNull,
  scanner: ScannerSchema.catch(() => ScannerSchema.parse({})),
  direction: z.string().catch(""),
  fno_eligible: z.boolean().catch(false),
  plan_id: strOrNull,
  plan_status: z.string().catch("insufficient_data"),
  status_reasons: z.array(ReasonSchema).catch([]),
  would_change_if: strList,
  plan_inputs: z.record(z.unknown()).catch({}),
  headline: z.unknown().optional(),
  evidence_summary: z.record(Counts).catch({}),
  oi_view: OiViewSchema.nullable().catch(null),
  preferred: strOrNull,
  strategies: z.array(IdeaStrategySchema),
}).passthrough();
export type Idea = z.infer<typeof IdeaSchema>;

/** How the Chartink part of the board went: any state but "ok" means the ideas are the scanner's alone, and `reason` says why. */
export const SelectionChartinkSchema = z.object({
  included: z.boolean().nullable().catch(null),
  state: strOrNull,
  reason: strOrNull,
  scan_date: strOrNull,
  fetched_at: strOrNull,
  mode: strOrNull,
  limit: numOrNull,
  considered: numOrNull,
  added: numOrNull,
  excluded: z.array(z.unknown()).catch([]),
  note: strOrNull,
  rule: strOrNull,
}).passthrough();
export type SelectionChartink = z.infer<typeof SelectionChartinkSchema>;

export const SelectionSchema = z.object({
  chartink: SelectionChartinkSchema.nullable().catch(null),
  source: strOrNull,
  scan_date: strOrNull,
  rule: strOrNull,
  considered: z.number().catch(0),
  selected: z.number().catch(0),
  excluded: z.array(z.object({ symbol: z.string(), reason: z.string().catch(""), code: strOrNull }).passthrough()).catch([]),
  excluded_note: strOrNull,
  empty_reason: strOrNull,
  gate: strOrNull,
  source_failures: strList,
  limit: numOrNull,
}).passthrough();

export const IdeasSchema = z.object({
  generated_at: strOrNull,
  data_as_of: z.object({ price: strOrNull, fno: strOrNull, scanner_watchlist: strOrNull, scanner_picks: strOrNull, scan_eligibility: strOrNull, mode: strOrNull }).passthrough()
    .catch({ price: null, fno: null, scanner_watchlist: null, scanner_picks: null, scan_eligibility: null, mode: null }),
  caveats: strList,
  rules_version: strOrNull,
  calculation_version: strOrNull,
  sent_to_broker: z.boolean().catch(false),
  ranking_note: strOrNull,
  selection: SelectionSchema,
  inputs: z.object({ defaults_applied: strList }).passthrough().catch({ defaults_applied: [] }),
  ideas: z.array(IdeaSchema),
}).passthrough();
export type IdeasBoard = z.infer<typeof IdeasSchema>;

export const SEGMENT_ORDER = ["cash", "futures", "options", "combination"] as const;
