/**
 * Scenarios contracts — REAL backend (action-board.yaml v2.0.0).
 *
 * action-board.yaml is canonical (richer than recommendation.yaml).
 *
 * Simulate body is target_* parameters (allocation targets), NOT `{changes:[]}`.
 * The two specs disagree; action-board (which the user pointed to) wins.
 *
 * Endpoints documented:
 *   GET   /api/scenarios/suggest             → suggested scenarios
 *   POST  /api/scenarios/simulate            → before/after metrics
 *   POST  /api/scenarios/rebalance-plan      → step-by-step actions
 *   POST  /api/scenarios/save                → save for later
 *   GET   /api/scenarios/saved               → list saved
 *   DELETE /api/scenarios/saved/{id}
 *   POST  /api/scenarios/apply               → commit as pending plan
 *   GET   /api/scenarios/pending             → list pending
 *   DELETE /api/scenarios/pending/{id}
 *   POST  /api/scenarios/pending/{id}/complete
 */
import { z } from "zod";

export const ScenarioImpactC = z.object({
  health_score_delta: z.number().optional(),
  annual_savings_rs:  z.number().nullable().optional(),
}).passthrough();

export const ScenarioSuggestionC = z.object({
  scenario_id: z.string(),
  name: z.string().optional(),
  description: z.string().optional(),
  estimated_health_delta: z.number().optional(),
  annual_savings_rs: z.number().nullable().optional(),
  complexity: z.enum(["low", "medium", "high"]).or(z.string()).optional(),
}).passthrough();

export const ScenarioSuggestRes = z.object({
  scenarios: z.array(ScenarioSuggestionC),
}).passthrough();

/** Simulate / rebalance-plan share this body shape. */
export const ScenarioSimulateReqC = z.object({
  scenario_id:      z.string().nullable().optional(),
  target_equity:    z.number().nullable().optional(),
  target_debt:      z.number().nullable().optional(),
  target_gold:      z.number().nullable().optional(),
  target_amc_cap:   z.number().nullable().optional(),
  target_small_cap: z.number().nullable().optional(),
  switch_to_direct: z.boolean().nullable().optional(),
  remove_dead:      z.boolean().nullable().optional(),
});
export type ScenarioSimulateReqC = z.infer<typeof ScenarioSimulateReqC>;

export const ScenarioMetricsC = z.object({
  health_score:        z.number().optional(),
  equity_pct:          z.number().optional(),
  max_amc_pct:         z.number().optional(),
  max_overlap_pct:     z.number().optional(),
  avg_expense_ratio_pct: z.number().optional(),
}).passthrough();

export const ScenarioSimulateRes = z.object({
  scenario_id: z.string().optional(),
  before: ScenarioMetricsC,
  after:  ScenarioMetricsC,
  delta:  z.record(z.number()).optional(),
  summary: z.array(z.string()).optional(),
}).passthrough();

export const RebalanceActionC = z.object({
  step: z.number().int(),
  action_type: z.string(),
  fund: z.string(),
  isin: z.string().optional(),
  amount_rs: z.number(),
  reason: z.string().optional(),
}).passthrough();

export const RebalancePlanRes = z.object({
  scenario_id: z.string().optional(),
  total_actions: z.number().int(),
  rebalance_amount_rs: z.number(),
  actions: z.array(RebalanceActionC),
  summary: z.object({
    health_score_before: z.number().optional(),
    health_score_after:  z.number().optional(),
    annual_savings_rs:   z.number().nullable().optional(),
  }).passthrough().optional(),
}).passthrough();

export const SavedScenarioC = z.object({
  saved_id: z.string(),
  name: z.string(),
  health_score_delta: z.number().optional(),
  annual_savings_rs: z.number().nullable().optional(),
  saved_at: z.string(),
}).passthrough();

export const SavedScenariosRes = z.object({
  saved_scenarios: z.array(SavedScenarioC),
}).passthrough();

export const PendingPlanC = z.object({
  pending_plan_id: z.string(),
  scenario_id: z.string().optional(),
  actions_count: z.number().int(),
  status: z.string(),
  created_at: z.string(),
}).passthrough();

export const PendingPlansRes = z.object({
  pending_plans: z.array(PendingPlanC),
}).passthrough();

export type ScenarioSimulateRes = z.infer<typeof ScenarioSimulateRes>;
export type RebalancePlanRes = z.infer<typeof RebalancePlanRes>;
export type SavedScenariosRes = z.infer<typeof SavedScenariosRes>;
export type PendingPlansRes = z.infer<typeof PendingPlansRes>;
