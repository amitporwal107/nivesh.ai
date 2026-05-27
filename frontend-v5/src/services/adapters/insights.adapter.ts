/**
 * Insights adapter — REAL backend (insights.yaml v2.0.0).
 *
 * Three distinct calls:
 *   /api/insights/analysis      → portfolio Health Score (0-100) + breakdown
 *   /api/insights/v3-portfolio  → per-fund V3 scores (0-100 per holding)
 *   /api/insights               → cached insights list (categories/severity)
 *   POST /api/insights/generate → force-refresh insights cache
 */
import { http } from "@/services/api/http";
import { ApiError } from "@/services/api/errors";
import {
  InsightsAnalysisRes,
  V3PortfolioRes,
  InsightsListRes,
  type PortfolioHealthC,
} from "@/services/contracts/insights.contract";
import type { PortfolioInsight } from "@/types/portfolio";

export interface InsightsAdapter {
  analysis(): Promise<{
    health: PortfolioHealthC;
    summary?: Record<string, unknown>;
    topActions?: string[];
  }>;
  v3Portfolio(refreshStocks?: boolean): Promise<{
    portfolioScore: number;
    coveragePct?: number;
    fundScores: Array<{ id: string; name: string; score: number; coverage?: number; weight?: number; belowGate?: boolean }>;
  }>;
  list(): Promise<{
    insights: PortfolioInsight[];
    counts: { critical?: number; warning?: number; info?: number; total?: number };
    riskGauge?: { beta?: number; volatilityPct?: number; label?: string };
  }>;
  regenerate(): Promise<unknown>;
}

export const realInsightsAdapter: InsightsAdapter = {
  async analysis() {
    const res = await http({ path: "/api/insights/analysis" });
    const parsed = InsightsAnalysisRes.safeParse(res.data);
    if (!parsed.success) throw ApiError.contractDrift(`insights.analysis: ${parsed.error.message}`);
    return {
      health: parsed.data.portfolio_health,
      summary: parsed.data.summary,
      topActions: parsed.data.top_actions,
    };
  },

  async v3Portfolio(refreshStocks = false) {
    const res = await http({
      path: "/api/insights/v3-portfolio",
      query: { refresh_stocks: refreshStocks },
    });
    const parsed = V3PortfolioRes.safeParse(res.data);
    if (!parsed.success) throw ApiError.contractDrift(`insights.v3Portfolio: ${parsed.error.message}`);
    return {
      portfolioScore: parsed.data.portfolio_v3_score,
      coveragePct: parsed.data.coverage_pct,
      fundScores: (parsed.data.fund_scores ?? []).map((f) => ({
        id: f.instrument_id,
        name: f.name,
        score: f.v3_score,
        coverage: f.coverage_pct,
        weight: f.weight_pct,
        belowGate: f.below_gate,
      })),
    };
  },

  async list() {
    const res = await http({ path: "/api/insights" });
    const parsed = InsightsListRes.safeParse(res.data);
    if (!parsed.success) throw ApiError.contractDrift(`insights.list: ${parsed.error.message}`);
    return {
      insights: parsed.data.insights.map(mapInsightItem),
      counts: {
        total:    parsed.data.total_count,
        critical: parsed.data.critical_count,
        warning:  parsed.data.warning_count,
        info:     parsed.data.info_count,
      },
      riskGauge: parsed.data.risk_gauge && {
        beta:          parsed.data.risk_gauge.portfolio_beta,
        volatilityPct: parsed.data.risk_gauge.volatility_pct,
        label:         parsed.data.risk_gauge.risk_label,
      },
    };
  },

  async regenerate() {
    const res = await http({ method: "POST", path: "/api/insights/generate" });
    return res.data;
  },
};

function mapInsightItem(c: import("@/services/contracts/insights.contract").InsightItemC | unknown): PortfolioInsight {
  const item = c as {
    insight_id: string;
    category: string;
    severity: string;
    title: string;
    description?: string;
    affected_holdings?: string[];
    action_hint?: string;
  };
  const sev = item.severity?.toLowerCase();
  const severity: PortfolioInsight["severity"] =
    sev === "critical" ? "fix" :
    sev === "warning"  ? "watch" :
    sev === "info"     ? "info" :
    "info";
  const cat = item.category?.toLowerCase();
  const category: PortfolioInsight["category"] =
    cat === "overlap"        ? "overlap" :
    cat === "concentration"  ? "concentration" :
    cat === "cost"           ? "cost" :
    cat === "goal_drift"     ? "goal" :
    cat === "diversification"? "balance" :
    cat === "underperformer" ? "balance" :
    "balance";
  return {
    id: item.insight_id,
    severity,
    category,
    title: item.title,
    detail: item.description ?? "",
  };
}
