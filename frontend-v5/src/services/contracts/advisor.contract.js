/**
 * Advisor + MFD contracts — REAL backend (advisor.yaml v2.0.0).
 *
 * The mfd workspace is the source of truth — "advisor" endpoints are the
 * read-side analytics over the same client profile model.
 */
import { z } from "zod";
export const ClientProfileC = z.object({
    profile_id: z.string(),
    name: z.string(),
    email: z.string().nullable().optional(),
    mobile: z.string().nullable().optional(),
    pan: z.string().nullable().optional(),
    aum_rs: z.number().nullable().optional(),
    tags: z.array(z.string()).optional(),
    notes: z.string().nullable().optional(),
    is_self: z.boolean().optional(),
    priority_score: z.number().nullable().optional(),
    priority_bucket: z.enum(["high", "medium", "low"]).or(z.string()).nullable().optional(),
    health_score: z.number().nullable().optional(),
    last_reviewed_at: z.string().nullable().optional(),
    created_at: z.string().optional(),
}).passthrough();
export const ProfilesListRes = z.object({
    total: z.number().int(),
    profiles: z.array(ClientProfileC),
}).passthrough();
export const AdvisorClientRowC = z.object({
    profile_id: z.string(),
    name: z.string(),
    priority_score: z.number().optional(),
    health_score: z.number().optional(),
    aum_rs: z.number().optional(),
    top_reason: z.string().optional(),
    days_since_review: z.number().int().optional(),
}).passthrough();
export const AdvisorTodayRes = z.object({
    generated_at: z.string().optional(),
    high_priority: z.array(AdvisorClientRowC),
    medium_priority: z.array(AdvisorClientRowC),
    low_priority: z.array(AdvisorClientRowC),
    summary: z.object({
        total_clients: z.number().int(),
        high: z.number().int(),
        medium: z.number().int(),
        low: z.number().int(),
    }).passthrough(),
}).passthrough();
export const AdvisorAumRowC = z.object({
    profile_id: z.string(),
    name: z.string(),
    aum_rs: z.number(),
    aum_mom_change_rs: z.number().optional(),
    aum_mom_change_pct: z.number().optional(),
    rank: z.number().int().optional(),
}).passthrough();
export const AdvisorAumRes = z.object({
    total_aum_rs: z.number(),
    mom_change_pct: z.number().optional(),
    clients: z.array(AdvisorAumRowC),
}).passthrough();
export const AdvisorUnderperformersRes = z.object({
    benchmark: z.string(),
    benchmark_xirr_pct: z.number(),
    gap_threshold_pct: z.number(),
    underperformers: z.array(z.object({
        profile_id: z.string(),
        name: z.string(),
        portfolio_xirr_pct: z.number(),
        benchmark_xirr_pct: z.number(),
        gap_pct: z.number(),
        aum_rs: z.number().optional(),
        health_score: z.number().optional(),
        top_drag_fund: z.string().optional(),
    }).passthrough()),
}).passthrough();
export const AdvisorRebalanceRes = z.object({
    threshold_pp: z.number(),
    clients_needing_rebalance: z.number().int(),
    clients: z.array(z.object({
        profile_id: z.string(),
        name: z.string(),
        target_equity_pct: z.number(),
        current_equity_pct: z.number(),
        drift_pp: z.number(),
        aum_rs: z.number().optional(),
        rebalance_action: z.string().optional(),
    }).passthrough()),
}).passthrough();
export const MfdWorkspaceC = z.object({
    mode: z.enum(["INDIVIDUAL", "ADVISORY"]).or(z.string()),
    firm_name: z.string().optional(),
    advisor_name: z.string().optional(),
    advisor_email: z.string().optional(),
    advisor_mobile: z.string().optional(),
    arn_or_ria: z.string().optional(),
    client_count_range: z.string().optional(),
    mfd_onboarding_completed: z.boolean().optional(),
    profiles_count: z.number().int().optional(),
}).passthrough();
export const NeedsAttentionItemC = z.object({
    type: z.string(),
    priority: z.enum(["high", "medium", "low"]).or(z.string()).optional(),
    message: z.string().optional(),
    holding_name: z.string().nullable().optional(),
    due_date: z.string().nullable().optional(),
}).passthrough();
