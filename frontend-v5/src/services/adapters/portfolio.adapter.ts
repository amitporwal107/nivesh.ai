/**
 * Portfolio adapter — composes PortfolioSummary from real endpoints.
 *
 * Real endpoints (portfolio.yaml v2.0.0):
 *   GET  /api/portfolios                          → Portfolio[]
 *   GET  /api/portfolio/holdings                  → Holding[]
 *   POST /api/portfolio/holdings                  → Holding
 *   PUT  /api/portfolio/holdings/{id}             → Holding
 *   DELETE /api/portfolio/holdings/{id}
 *   GET  /api/portfolio/holdings-enriched         → enriched with V3 / badges
 *   GET  /api/search/instruments?q
 *   GET  /api/portfolio/trend?days                → {series:[{date, value_rs}]}
 *   GET  /api/portfolio/sips                      → detected SIPs
 *   GET  /api/portfolio/exposure/concentration    → AMC/sector/company breakdown
 *
 * Pairs with /api/insights/analysis for the health score.
 */
import { http } from "@/services/api/http";
import { ApiError } from "@/services/api/errors";
import {
  HoldingsListRes,
  TrendRes,
  EnrichedHoldingsRes,
  InstrumentSearchRes,
  SipsListRes,
} from "@/services/contracts/portfolio.contract";
import { mapHoldings } from "@/services/mappers/portfolio.mapper";
import { realInsightsAdapter } from "./insights.adapter";
import type { Holding } from "@/types/fund";
import type { PortfolioSummary, NavPoint } from "@/types/portfolio";

export interface PortfolioAdapter {
  listHoldings(portfolioId?: string, assetType?: string): Promise<Holding[]>;
  listHoldingsEnriched(fresh?: boolean): Promise<import("@/services/contracts/portfolio.contract").EnrichedHoldingsRes>;
  getSummary(): Promise<PortfolioSummary>;
  getNavHistory(range: "1m" | "3m" | "6m" | "1y" | "all"): Promise<NavPoint[]>;
  searchInstruments(q: string): Promise<import("@/services/contracts/portfolio.contract").InstrumentSearchRes>;
  listSips(): Promise<import("@/services/contracts/portfolio.contract").SipsListRes>;
}

const DAYS_BY_RANGE: Record<string, number> = {
  "1m": 31, "3m": 92, "6m": 183, "1y": 365, "all": 365 * 5,
};

export const realPortfolioAdapter: PortfolioAdapter = {
  async listHoldings(portfolioId, assetType) {
    const res = await http({
      path: "/api/portfolio/holdings",
      query: { portfolio_id: portfolioId, asset_type: assetType },
    });
    const parsed = HoldingsListRes.safeParse(res.data);
    if (!parsed.success) throw ApiError.contractDrift(`portfolio.listHoldings: ${parsed.error.message}`);
    return mapHoldings(parsed.data);
  },

  async listHoldingsEnriched(fresh = false) {
    const res = await http({ path: "/api/portfolio/holdings-enriched", query: { fresh } });
    const parsed = EnrichedHoldingsRes.safeParse(res.data);
    if (!parsed.success) throw ApiError.contractDrift(`portfolio.enriched: ${parsed.error.message}`);
    return parsed.data;
  },

  async getSummary() {
    // Compose: enriched-holdings (totals) + insights/analysis (health score)
    // + CAS statement summary (fallback when enrichment prices aren't fetched yet).
    const [enriched, health, casState] = await Promise.all([
      this.listHoldingsEnriched().catch(() => null),
      realInsightsAdapter.analysis().catch(() => null),
      fetch("/api/onboarding/state", { credentials: "include" })
        .then((r) => r.ok ? r.json() as Promise<{ cas_portfolio_value_rs?: number | null; cas_statement_date?: string | null }> : null)
        .catch(() => null),
    ]);

    // Use CAS summary value when holdings-enriched hasn't fetched live NAVs yet
    const enrichedValue = (enriched?.totals?.value_rs ?? 0) * 100;
    const casValue      = (casState?.cas_portfolio_value_rs ?? 0) * 100;
    const totalValue    = enrichedValue > 0 ? enrichedValue : casValue;

    const totalCost  = (enriched?.totals?.invested_rs ?? 0) * 100;
    const pnl    = totalValue - totalCost;
    const pnlPct = totalCost === 0 ? 0 : pnl / totalCost;

    return {
      asOf: casState?.cas_statement_date ?? new Date().toISOString(),
      totalValue,
      dayChange:  { abs: 0, pct: 0 },
      weekChange: { abs: 0, pct: 0 },
      yearChange: { abs: pnl, pct: pnlPct },
      healthScore: health?.health.health_score ?? health?.health.score ?? 0,
      riskBucket: "moderate" as const,
      riskBucketIndex: 3,
      allocation: [],
      topInsights: [],
    };
  },

  async getNavHistory(range) {
    const days = DAYS_BY_RANGE[range] ?? 365;
    const [trendRes, casState] = await Promise.all([
      http({ path: "/api/portfolio/trend", query: { days } }),
      fetch("/api/onboarding/state", { credentials: "include" })
        .then((r) => r.ok ? r.json() as Promise<{ cas_portfolio_value_rs?: number | null; cas_statement_date?: string | null }> : null)
        .catch(() => null),
    ]);
    const parsed = TrendRes.safeParse(trendRes.data);
    if (!parsed.success) throw ApiError.contractDrift(`portfolio.getNavHistory: ${parsed.error.message}`);
    const series = parsed.data.series.map((p) => ({
      date:  p.snapshot_date,
      value: Math.round(p.total_value * 100),
    }));
    // If no trend history, synthesise a single point from the CAS statement date + value
    if (series.length === 0 && casState?.cas_statement_date && casState?.cas_portfolio_value_rs) {
      return [{ date: casState.cas_statement_date, value: Math.round(casState.cas_portfolio_value_rs * 100) }];
    }
    return series;
  },

  async searchInstruments(q) {
    if (!q || q.length < 2) return [];
    const res = await http({ path: "/api/search/instruments", query: { q } });
    const parsed = InstrumentSearchRes.safeParse(res.data);
    if (!parsed.success) throw ApiError.contractDrift(`portfolio.searchInstruments: ${parsed.error.message}`);
    return parsed.data;
  },

  async listSips() {
    const res = await http({ path: "/api/portfolio/sips" });
    const parsed = SipsListRes.safeParse(res.data);
    if (!parsed.success) throw ApiError.contractDrift(`portfolio.listSips: ${parsed.error.message}`);
    return parsed.data;
  },
};
