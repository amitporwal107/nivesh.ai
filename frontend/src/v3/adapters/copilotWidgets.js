// Adapters for the existing /api/copilot/widgets/* endpoints.
// Each hook returns a V3 view-model that's safe to render even when the
// backend call fails (returns null fields, screens handle gracefully).

import { apiPost } from "./apiClient";
import { useAsync } from "../hooks/useAsync";

/**
 * Run a stress scenario (covid_2020, gfc_2008, drop_10/20/30, custom).
 * Returns: { scenarioId, dropPct, portfolioImpact, recoveryMonths }
 */
export function useStressTest(scenario = "drop_20") {
  return useAsync(async () => {
    const { data, error } = await apiPost("/copilot/widgets/stress_test", { scenario, layout: "insight_card" });
    if (error || !data) return { data: null, error };
    return {
      data: {
        scenarioId: data.scenario || scenario,
        dropPct: data.drop_pct ?? data.portfolio_drop ?? null,
        portfolioImpact: data.portfolio_impact ?? data.final_value ?? null,
        recoveryMonths: data.recovery_months ?? data.recovery_period ?? null,
        breakdown: data.asset_breakdown || data.holdings || [],
      },
      error: null,
    };
  }, [scenario]);
}

/**
 * Daily market brief — used by the Market dashboard screen.
 */
export function useMarketBrief() {
  return useAsync(async () => {
    const { data, error } = await apiPost("/copilot/widgets/market_brief", {});
    if (error || !data) return { data: null, error };
    return {
      data: {
        nifty: data.nifty || data.indices?.nifty || null,
        sensex: data.sensex || data.indices?.sensex || null,
        sectors: data.sectors || [],
        flows: data.flows || null,
        narrative: data.summary || data.narrative || null,
      },
      error: null,
    };
  }, []);
}

/**
 * Risk suitability for the current user — used by Risk Analysis screen.
 */
export function useRiskSuitability() {
  return useAsync(async () => {
    const { data, error } = await apiPost("/copilot/widgets/risk_suitability", {});
    if (error || !data) return { data: null, error };
    return {
      data: {
        profileScore: data.profile_score ?? null,
        suitabilityScore: data.suitability_score ?? null,
        equityActual: data.equity_actual ?? null,
        equityTarget: data.equity_target ?? null,
        debtActual: data.debt_actual ?? null,
        debtTarget: data.debt_target ?? null,
        suggestions: data.suggestions || [],
      },
      error: null,
    };
  }, []);
}
