// Risk analytics adapter — calls GET /api/portfolio/risk-analytics.
//
// Backend computes weighted beta/sharpe/volatility from NIDP V3 primitives
// (real fund-level + stock-level analytics), plus asset-class split and a
// ranked list of risk drivers. No client-side math — single source of truth.
//
// Shape (matches backend exactly):
//   { empty, total_value,
//     risk_score (0-10), risk_rating (LOW|MEDIUM|HIGH|VERY_HIGH|UNKNOWN),
//     weighted_beta, weighted_sharpe, weighted_volatility,
//     equity_pct, debt_pct, gold_pct, other_pct,
//     risk_drivers: [{type, label, detail, impact}],
//     top_contributors: [{name, weight_pct, volatility_1y}],
//     fund_breakdown: [...], stock_breakdown: [...],
//     coverage_pct, data_source }

import { apiGet } from "./apiClient";
import { useAsync } from "../hooks/useAsync";

const PLACEHOLDER = {
  empty: true,
  total_value: 0,
  risk_score: null,
  risk_rating: "UNKNOWN",
  weighted_beta: null,
  weighted_sharpe: null,
  weighted_volatility: null,
  equity_pct: 0, debt_pct: 0, gold_pct: 0, other_pct: 0,
  risk_drivers: [],
  top_contributors: [],
  fund_breakdown: [],
  stock_breakdown: [],
  coverage_pct: 0,
  data_source: null,
};

export function useRiskAnalysis() {
  return useAsync(
    async () => {
      const { data, error } = await apiGet("/portfolio/risk-analytics");
      if (error) return { data: PLACEHOLDER, error };
      if (!data) return { data: PLACEHOLDER, error: null };
      return { data, error: null };
    },
    [],
    { initialData: PLACEHOLDER }
  );
}
