/**
 * Goals contracts — REAL backend (goals.yaml v2.0.0).
 *
 * Matches the documented Goal schema exactly:
 * - priority enum (high/medium/low)
 * - on_track_pct, projected_corpus_rs, sip_gap_rs at top level
 * - selected_funds array, manual_fund_override boolean
 * - status enum (active/completed/archived)
 */
import { z } from "zod";

export const GoalTypeC = z.enum([
  "retirement", "education", "home", "emergency", "wealth", "other",
]);

export const PriorityC = z.enum(["high", "medium", "low"]);

export const FinancialSnapshotC = z.object({
  age:                  z.number().int().optional(),
  marital_status:       z.enum(["single", "married", "divorced", "widowed"]).or(z.string()).optional(),
  dependents:           z.number().int().optional(),
  monthly_income_rs:    z.number().optional(),
  income_growth_pct:    z.number().optional(),
  monthly_expenses_rs:  z.number().optional(),
  inflation_pct:        z.number().optional(),
  current_corpus_rs:    z.number().optional(),
  total_liabilities_rs: z.number().optional(),
  risk_profile:         z.enum(["conservative", "moderate", "aggressive"]).or(z.string()).optional(),
  behavior_score:       z.number().nullable().optional(),
  updated_at:           z.string().optional(),
}).passthrough();
export type FinancialSnapshotC = z.infer<typeof FinancialSnapshotC>;

export const GoalC = z.object({
  goal_id:             z.string(),
  goal_type:           GoalTypeC.or(z.string()),
  goal_name:           z.string(),
  target_amount_rs:    z.number(),
  // Backend stores horizon_years as numeric/float (e.g. 20.0) — coerce to int
  horizon_years:       z.number().transform(Math.round),
  priority:            PriorityC.or(z.string()).optional(),
  monthly_sip_rs:      z.number(),
  current_corpus_rs:   z.number().optional(),
  inflation_pct:       z.number().optional(),
  on_track_pct:        z.number().nullable().optional(),
  projected_corpus_rs: z.number().nullable().optional(),
  sip_gap_rs:          z.number().nullable().optional(),
  selected_funds:      z.array(z.string()).optional(),
  manual_fund_override: z.boolean().optional(),
  status:              z.enum(["active", "completed", "archived", "abandoned"]).or(z.string()),
  created_at:          z.string().optional(),
}).passthrough();
export type GoalC = z.infer<typeof GoalC>;

export const GoalsListRes = z.object({
  total:                     z.number().nullable().optional().transform(v => v ?? 0),
  on_track:                  z.number().nullable().optional().transform(v => v ?? 0),
  at_risk:                   z.number().nullable().optional().transform(v => v ?? 0),
  total_target_rs:           z.number().optional(),
  monthly_sip_required_rs:   z.number().optional(),
  monthly_sip_current_rs:    z.number().optional(),
  goals:                     z.array(GoalC),
}).passthrough();
export type GoalsListRes = z.infer<typeof GoalsListRes>;

export const GoalCreateReq = z.object({
  goal_type:         GoalTypeC,
  goal_name:         z.string(),
  target_amount_rs:  z.number(),
  horizon_years:     z.number().transform(Math.round),
  priority:          PriorityC,
  inflation_pct:     z.number().optional(),
  current_corpus_rs: z.number().optional(),
  monthly_sip_rs:    z.number().optional(),
  manual_allocation: z.record(z.number()).nullable().optional(),
});

export const MonteCarloRes = z.object({
  goal_id:                 z.string(),
  goal_name:               z.string().optional(),
  target_amount_rs:        z.number().optional(),
  horizon_years:           z.number().int().optional(),
  monthly_sip_rs:          z.number().optional(),
  current_corpus_rs:       z.number().optional(),
  success_probability_pct: z.number(),
  on_track:                z.boolean(),
  corpus_projections: z.object({
    p10_rs: z.number(),
    p50_rs: z.number(),
    p90_rs: z.number(),
  }).passthrough(),
  sip_recommendations: z.object({
    sip_for_70pct_success_rs: z.number().optional(),
    sip_for_80pct_success_rs: z.number().optional(),
    sip_for_90pct_success_rs: z.number().optional(),
  }).passthrough().optional(),
  year_by_year: z.array(z.object({
    year: z.number().int(),
    median_corpus_rs: z.number(),
  })).optional(),
  simulation_runs: z.number().int().optional(),
  simulated_at:    z.string().optional(),
}).passthrough();
export type MonteCarloRes = z.infer<typeof MonteCarloRes>;

export const WhatIfReq = z.object({
  monthly_sip_rs:       z.number().optional(),
  horizon_years:        z.number().int().optional(),
  current_corpus_rs:    z.number().optional(),
  allocation_override:  z.record(z.number()).optional(),
});

export const WhatIfRes = z.object({
  goal_id:                z.string(),
  what_if_params:         z.record(z.unknown()),
  current_on_track_pct:   z.number(),
  what_if_on_track_pct:   z.number(),
  delta_on_track_pct:     z.number().optional(),
  corpus_projections: z.object({
    p10_rs: z.number(),
    p50_rs: z.number(),
    p90_rs: z.number(),
  }).passthrough(),
  verdict:    z.string().optional(),
  persisted:  z.literal(false),
}).passthrough();

export const FundBucketC = z.enum([
  "large_cap","mid_cap","small_cap","flexi_cap","hybrid",
  "debt_short","debt_medium","elss","international","gold",
]);

export const FundShortlistRes = z.object({
  bucket:      z.string(),
  min_quality: z.number(),
  funds:       z.array(z.object({
    isin:              z.string(),
    name:              z.string(),
    amc:               z.string().optional(),
    v3_score:          z.number(),
    expense_ratio_pct: z.number().optional(),
    xirr_3y_pct:       z.number().optional(),
    nav:               z.number().optional(),
    aum_cr:            z.number().optional(),
    suggested:         z.boolean().optional(),
  }).passthrough()),
}).passthrough();

export type WhatIfReq = z.infer<typeof WhatIfReq>;
export type WhatIfRes = z.infer<typeof WhatIfRes>;
export type FundShortlistRes = z.infer<typeof FundShortlistRes>;
