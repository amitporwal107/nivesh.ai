/**
 * Insights contracts — REAL backend shape (insights.yaml v2.0.0).
 *
 * ⚠ Two distinct endpoints, two distinct responses:
 *
 *   1. /api/insights/analysis          → Portfolio HEALTH SCORE (the trust number)
 *      Returns { portfolio_health: { score, grade, label, breakdown, trend, ... }, ... }
 *
 *   2. /api/insights/v3-portfolio      → Per-FUND V3 scoring (0-100 per fund)
 *      Returns { portfolio_v3_score, coverage_pct, funds_below_gate, fund_scores: [...] }
 *
 * Earlier draft mixed the two — this corrects that.
 */
import { z } from "zod";
export const HealthScoreBreakdownC = z.object({
    return_quality: z.number().optional(),
    diversification: z.number().optional(),
    risk_adjusted: z.number().optional(),
    cost_efficiency: z.number().optional(),
    goal_alignment: z.number().optional(),
    overlap_penalty: z.number().optional(),
}).passthrough();
export const PortfolioHealthC = z.object({
    score: z.number(),
    grade: z.string(),
    label: z.string().optional(),
    breakdown: HealthScoreBreakdownC.optional(),
    trend: z.string().optional(),
    previous_score: z.number().optional(),
}).passthrough();
export const InsightsAnalysisRes = z.object({
    portfolio_health: PortfolioHealthC,
    summary: z.object({
        total_holdings: z.number().optional(),
        total_value_rs: z.number().optional(),
        xirr_pct: z.number().optional(),
        benchmark_xirr_pct: z.number().optional(),
        outperformance_pct: z.number().optional(),
        expense_ratio_avg_pct: z.number().optional(),
    }).passthrough().optional(),
    top_actions: z.array(z.string()).optional(),
    insights_summary: z.object({
        critical: z.number().optional(),
        warning: z.number().optional(),
        info: z.number().optional(),
    }).passthrough().optional(),
}).passthrough();
/** Per-fund V3 score row. */
export const V3FundScoreC = z.object({
    instrument_id: z.string(),
    name: z.string(),
    v3_score: z.number(),
    coverage_pct: z.number().optional(),
    weight_pct: z.number().optional(),
    below_gate: z.boolean().optional(),
}).passthrough();
export const V3PortfolioRes = z.object({
    portfolio_v3_score: z.number(),
    coverage_pct: z.number().optional(),
    funds_below_gate: z.number().optional(),
    fund_scores: z.array(V3FundScoreC).optional(),
    generated_at: z.string().optional(),
}).passthrough();
/** /api/insights list item. */
export const InsightItemC = z.object({
    insight_id: z.string(),
    category: z.enum(["overlap", "concentration", "underperformer", "cost", "diversification", "goal_drift"]).or(z.string()),
    severity: z.enum(["critical", "warning", "info"]).or(z.string()),
    title: z.string(),
    description: z.string().optional(),
    affected_holdings: z.array(z.string()).optional(),
    action_hint: z.string().optional(),
}).passthrough();
export const InsightsListRes = z.object({
    total_count: z.number().optional(),
    critical_count: z.number().optional(),
    warning_count: z.number().optional(),
    info_count: z.number().optional(),
    last_generated_at: z.string().optional(),
    risk_gauge: z.object({
        portfolio_beta: z.number().optional(),
        volatility_pct: z.number().optional(),
        risk_label: z.string().optional(),
    }).passthrough().optional(),
    insights: z.array(InsightItemC),
}).passthrough();
