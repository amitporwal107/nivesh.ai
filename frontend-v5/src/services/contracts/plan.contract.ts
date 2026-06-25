/**
 * Plans contracts — REAL backend (action-board.yaml v2.0.0).
 *
 * action-board.yaml is canonical; recommendation.yaml is its older sibling
 * (similar shape, fewer fields). Reconciled to action-board's superset.
 *
 * Key shape:
 * - `Plan` carries counters AND full actions array together
 *   (no separate "active summary" vs "full plan" — they're one shape)
 * - `PlanAction` adds: `rule_triggered`, `holding_id`, `suggested_alternative_isin`, `completion_note`
 */
import { z } from "zod";

export const ActionTypeC = z.enum([
  "sell", "buy", "switch", "sip_increase", "sip_decrease", "hold",
  "TRIM", "EXIT", "SWITCH", "ADD", "KEEP", "REDUCE", "SIP_INCREASE", "SIP_DECREASE",
]);
export type ActionTypeC = z.infer<typeof ActionTypeC>;

export const ActionStatusC = z.enum(["pending", "done", "skipped", "PENDING", "COMPLETED", "SKIPPED"]);

export const EstimatedImpactC = z.object({
  health_score_delta: z.number().nullable().optional(),
  annual_savings_rs:  z.number().nullable().optional(),
}).passthrough();

/** PRD §8 severity tiers */
export const ActionSeverityC = z.enum(["aligned", "minor", "mismatch", "severe"]).or(z.string());
/** PRD §9 tax-aware execution path */
export const ExecutionPathC = z.enum(["redirect", "harvest", "stagger", "sell-now"]).or(z.string());

const TaxImpactC = z.object({
  tax_liability:        z.number().nullable().optional(),
  stcg:                 z.number().nullable().optional(),
  ltcg:                 z.number().nullable().optional(),
  exit_load_rs:         z.number().nullable().optional(),
  holding_period_days:  z.number().nullable().optional(),
  lock_in:              z.boolean().nullable().optional(),
}).passthrough();

const ExpectedEffectC = z.object({
  risk_band_delta:            z.enum(["lower", "higher", "neutral"]).or(z.string()),
  score_delta_pct:            z.number(),
  funding_probability_delta:  z.number(),
}).passthrough();

export const PlanActionC = z.object({
  // PRD §12 canonical field names
  id:          z.string().optional(),
  action:      z.string().optional(),
  magnitude:   z.number().optional(),
  execution:   ExecutionPathC.optional(),
  // Legacy aliases (kept for backward compat; adapter reads both)
  action_id:   z.string(),
  action_type: ActionTypeC.or(z.string()).optional(),
  amount_rs:   z.number().optional(),
  // Shared fields
  priority:     z.union([z.number(), z.string().transform(Number)]).optional(),
  rule_triggered: z.string().optional(),
  holding_name: z.string().optional(),
  asset_name:   z.string().optional(),
  holding_id:   z.string().nullable().optional(),
  rationale:    z.string().optional(),
  reason_text:  z.string().optional(),
  suggested_alternative:      z.string().nullable().optional(),
  suggested_alternative_isin: z.string().nullable().optional(),
  estimated_impact: EstimatedImpactC.nullable().optional(),
  status:       ActionStatusC.or(z.string()).optional(),
  completion_note: z.string().nullable().optional(),
  // PRD §12 output contract fields
  severity:              ActionSeverityC.optional(),
  execution_path:        ExecutionPathC.optional(),
  requires_confirmation: z.boolean().optional(),
  tax_impact:            TaxImpactC.nullable().optional(),
  expected_effect:       ExpectedEffectC.nullable().optional(),
  engine_name:           z.string().optional(),
  source_domain:         z.string().optional(),
  goal_id:               z.string().optional(),
  goal_name:             z.string().optional(),
}).passthrough();
export type PlanActionC = z.infer<typeof PlanActionC>;
export type ActionSeverity = z.infer<typeof ActionSeverityC>;
export type ExecutionPath = z.infer<typeof ExecutionPathC>;

export const GateFlagsC = z.object({
  requires_persona:          z.boolean().optional(),
  requires_goal:             z.boolean().optional(),
  capacity_tolerance_diverged: z.boolean().optional(),
}).passthrough();
export type GateFlagsC = z.infer<typeof GateFlagsC>;

export const PlanC = z.object({
  plan_id:                z.string(),
  version:                z.union([z.string(), z.number()]).optional(),
  status:                 z.enum(["preview", "active", "archived"]).or(z.string()),
  health_score_before:    z.number().optional(),
  health_score_projected: z.number().optional(),
  actions_total:    z.number().optional(),
  actions_done:     z.number().optional(),
  actions_pending:  z.number().optional(),
  actions_skipped:  z.number().optional(),
  actions:          z.array(PlanActionC).optional(),
  created_at:       z.string().optional(),
  last_updated_at:  z.string().optional(),
  gate_flags:       GateFlagsC.optional(),
}).passthrough();
export type PlanC = z.infer<typeof PlanC>;

export const PlanActiveRes = z.object({
  has_plan: z.boolean(),
  plan:     PlanC.nullable(),
});

export const PlanGenerateRes = z.object({
  plan:    PlanC,
  message: z.string().optional(),
});

/** PATCH action returns counters — NOT the full plan. */
export const PlanActionUpdateRes = z.object({
  plan_id:    z.string(),
  action_id:  z.string(),
  new_status: ActionStatusC.or(z.string()),
  actions_done:    z.number().optional(),
  actions_pending: z.number().optional(),
  actions_skipped: z.number().optional(),
}).passthrough();

export const PlanHealthProjectionRes = z.object({
  current_score:   z.number(),
  projected_score: z.number(),
  projected_grade: z.string().optional(),
  actions_impact:  z.array(z.object({
    action_id:    z.string(),
    action_type:  z.string(),
    holding_name: z.string().optional(),
    score_delta:  z.number(),
  }).passthrough()).optional(),
}).passthrough();

export const SignalC = z.object({
  type:     z.string(),
  priority: z.number().int().optional(),
  holding_name: z.string().optional(),
  message:  z.string(),
  health_score_impact: z.number().optional(),
}).passthrough();

export const SignalsRes = z.object({
  signals: z.array(SignalC),
  summary: z.object({
    critical_signals: z.number().optional(),
    warning_signals:  z.number().optional(),
    portfolio_health: z.number().optional(),
  }).passthrough().optional(),
}).passthrough();

export type PlanHealthProjectionRes = z.infer<typeof PlanHealthProjectionRes>;
export type PlanActionUpdateRes = z.infer<typeof PlanActionUpdateRes>;
export type SignalsRes = z.infer<typeof SignalsRes>;
