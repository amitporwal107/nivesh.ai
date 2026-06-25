/**
 * Advisor + MFD contracts — REAL backend (backend/routes/advisor.py + mfd.py).
 *
 * IMPORTANT: an earlier version of this file was written against a
 * hypothetical `advisor.yaml v2.0.0` spec (bucketed `high_priority/...`,
 * `clients[]`, etc.). The DEPLOYED backend does not return those shapes — it
 * returns flat `rows[]` envelopes. These schemas are derived from the running
 * route handlers, which are the source of truth.
 */
import { z } from "zod";

// ── Priority (priority_engine.PriorityResult.to_dict) ───────────────────
export const PriorityFactorsC = z.object({
  portfolio_weakness:      z.number().optional(),
  risk:                    z.number().optional(),
  aum:                     z.number().optional(),
  recency:                 z.number().optional(),
  recommendation_severity: z.number().optional(),
}).passthrough();

export const PriorityC = z.object({
  score:           z.number().optional(),                 // 0..1
  bucket:          z.enum(["high", "medium", "low"]).or(z.string()).optional(),
  factors:         PriorityFactorsC.optional(),
  reasons:         z.array(z.string()).optional(),
  dominant_action: z.string().nullable().optional(),
}).passthrough();
export type PriorityC = z.infer<typeof PriorityC>;

// ── Client profile (mfd._profile_with_priority) ─────────────────────────
export const ClientProfileC = z.object({
  profile_id:           z.string(),
  shadow_user_id:       z.string().nullable().optional(),
  name:                 z.string(),
  type:                 z.string().optional(),            // SELF | CLIENT
  email:                z.string().nullable().optional(),
  mobile:               z.string().nullable().optional(),
  pan:                  z.string().nullable().optional(),
  aum_rs:               z.number().nullable().optional(),
  portfolio_value_rs:   z.number().nullable().optional(),
  portfolio_score:      z.number().nullable().optional(),
  risk_score:           z.number().nullable().optional(),
  ai_summary:           z.string().nullable().optional(),
  recommendation_count: z.number().nullable().optional(),
  priority:             PriorityC.nullable().optional(),
  tags:                 z.array(z.string()).nullable().optional(),
  notes:                z.string().nullable().optional(),
  last_reviewed_at:     z.string().nullable().optional(),
  created_at:           z.string().optional(),
}).passthrough();
export type ClientProfileC = z.infer<typeof ClientProfileC>;

// GET /api/mfd/profiles → { workspace, profiles, count }
export const ProfilesListRes = z.object({
  workspace: z.unknown().optional(),
  profiles:  z.array(ClientProfileC),
  count:     z.number().int().optional(),
}).passthrough();
export type ProfilesListRes = z.infer<typeof ProfilesListRes>;

// ── Advisor Home card rows share the slim profile projection ────────────
const SlimRowC = ClientProfileC.partial().extend({
  profile_id: z.string(),
  name:       z.string(),
}).passthrough();

// GET /api/advisor/today
export const AdvisorTodayRes = z.object({
  rows: z.array(SlimRowC.extend({
    priority_bucket: z.string().nullable().optional(),
    priority_score:  z.number().nullable().optional(),
    dominant_action: z.string().nullable().optional(),
    reasons:         z.array(z.string()).optional(),
  })),
  total_clients: z.number().int().optional(),
  shown:         z.number().int().optional(),
  buckets:       z.object({ high: z.number(), medium: z.number(), low: z.number() }).partial().optional(),
  headline:      z.string().optional(),
}).passthrough();
export type AdvisorTodayRes = z.infer<typeof AdvisorTodayRes>;

// GET /api/advisor/aum
export const AdvisorAumRes = z.object({
  rows: z.array(SlimRowC.extend({
    mom_pct:     z.number().nullable().optional(),
    mom_rs:      z.number().nullable().optional(),
    prev_aum_rs: z.number().nullable().optional(),
  })),
  total_aum_rs:      z.number().optional(),
  aggregate_mom_pct: z.number().nullable().optional(),
  headline:          z.string().optional(),
}).passthrough();
export type AdvisorAumRes = z.infer<typeof AdvisorAumRes>;

// GET /api/advisor/underperformers
export const AdvisorUnderperformersRes = z.object({
  rows: z.array(SlimRowC.extend({
    portfolio_return_pct: z.number().nullable().optional(),
    benchmark_return_pct: z.number().nullable().optional(),
    gap_pct:              z.number(),
  })),
  benchmark:           z.string().optional(),
  benchmark_return_pct:z.number().nullable().optional(),
  gap_threshold_pct:   z.number().optional(),
  _no_benchmark:       z.boolean().optional(),
  headline:            z.string().optional(),
}).passthrough();
export type AdvisorUnderperformersRes = z.infer<typeof AdvisorUnderperformersRes>;

// GET /api/advisor/rebalance
export const RebalanceDetailC = z.object({
  bucket:      z.string().optional(),
  current_pct: z.number().optional(),
  target_pct:  z.number().optional(),
  gap_pp:      z.number().optional(),
  direction:   z.string().optional(),
}).passthrough();

export const AdvisorRebalanceRes = z.object({
  rows: z.array(SlimRowC.extend({
    rebalance: RebalanceDetailC.nullable().optional(),
  })),
  gap_threshold_pp: z.number().optional(),
  headline:         z.string().optional(),
}).passthrough();
export type AdvisorRebalanceRes = z.infer<typeof AdvisorRebalanceRes>;

// ── Workspace (mfd.get_workspace) ───────────────────────────────────────
export const MfdWorkspaceC = z.object({
  workspace_id:               z.string().optional(),
  type:                       z.enum(["INDIVIDUAL", "ADVISORY"]).or(z.string()).optional(),
  mode:                       z.enum(["INDIVIDUAL", "ADVISORY"]).or(z.string()).optional(),
  firm_name:                  z.string().nullable().optional(),
  advisor_name:               z.string().nullable().optional(),
  advisor_email:              z.string().nullable().optional(),
  advisor_mobile:             z.string().nullable().optional(),
  arn_or_ria:                 z.string().nullable().optional(),
  client_count_range:         z.string().nullable().optional(),
  mfd_onboarding_completed:   z.boolean().optional(),
  active_profile_id:          z.string().nullable().optional(),
  profiles_count:             z.number().int().optional(),
}).passthrough();
export type MfdWorkspaceC = z.infer<typeof MfdWorkspaceC>;

// ── v4 needs-attention (unchanged) ──────────────────────────────────────
export const NeedsAttentionItemC = z.object({
  type:         z.string(),
  priority:     z.enum(["high", "medium", "low"]).or(z.string()).optional(),
  message:      z.string().optional(),
  holding_name: z.string().nullable().optional(),
  due_date:     z.string().nullable().optional(),
}).passthrough();
export type NeedsAttentionItemC = z.infer<typeof NeedsAttentionItemC>;
