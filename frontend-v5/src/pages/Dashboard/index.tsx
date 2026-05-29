/**
 * Dashboard — route entry.
 *
 * Owns: react-query data fetch + loading/empty/error gates.
 * Doesn't own: layout chrome.
 *
 * Parallel fetches (all non-blocking on summary + navHistory):
 *   - V3 health score (ETag-aware)
 *   - Risk profile (user preferences)
 *   - Insights list (intelligence feed)
 *   - Holdings count (empty-state gate)
 */
import { useNavigate } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { usePortfolioSummary, usePortfolioNavHistory, useHoldings } from "@/hooks/use-portfolio";
import { useHealthAnalysis, useInsightsList } from "@/hooks/use-insights";
import { useRiskProfile } from "@/hooks/use-risk-profile";
import { LoadingSkeleton } from "@/components/shared/LoadingSkeleton";
import { ErrorState } from "@/components/shared/ErrorState";
import { EmptyState } from "@/components/shared/EmptyState";
import { Dashboard } from "./Dashboard";

export default function DashboardPage() {
  const navigate = useNavigate();
  const qc = useQueryClient();

  // Blocking — needed before rendering the hero
  const summary    = usePortfolioSummary();
  const navHistory = usePortfolioNavHistory("1y");

  // Non-blocking — augment the UI as they resolve
  const holdings    = useHoldings();
  const healthQuery = useHealthAnalysis();
  const insightsQ   = useInsightsList();
  const riskProfileQ = useRiskProfile();

  if (summary.isPending || navHistory.isPending) {
    return (
      <div className="px-6 py-8 lg:px-10 lg:py-10 max-w-[1080px] mx-auto w-full">
        <LoadingSkeleton variant="dashboard" />
      </div>
    );
  }

  if (summary.isError || navHistory.isError) {
    return (
      <ErrorState
        title="Couldn't load your dashboard"
        error={summary.error ?? navHistory.error}
        onRetry={() => { summary.refetch(); navHistory.refetch(); }}
      />
    );
  }

  const hasHoldings = (holdings.data?.length ?? 0) > 0;
  if (!summary.data && !hasHoldings) {
    return (
      <EmptyState
        title="Connect your investments to begin"
        description="Upload a CAS PDF, a broker statement, or an Excel/CSV file. We parse it, score it, and surface what to do next."
        action={{ label: "Upload a statement", onClick: () => navigate("/onboarding") }}
      />
    );
  }

  const nav = navHistory.data ?? [];

  // Prefer V3 health score; fall back to summary score
  const healthData = healthQuery.data && !healthQuery.isError ? healthQuery.data : null;
  let dashSummary = healthData
    ? { ...summary.data!, healthScore: healthData.health.health_score || healthData.health.score || summary.data!.healthScore }
    : summary.data!;

  // Portfolio value fallback: use last trend data point when enriched totals aren't ready yet
  if (dashSummary.totalValue === 0 && nav.length > 0) {
    dashSummary = { ...dashSummary, totalValue: nav[nav.length - 1].value };
  }

  // Health breakdown sub-scores from V3 analysis
  const breakdown = healthData?.health.breakdown
    ? {
        return_quality:  healthData.health.breakdown.return_quality,
        diversification: healthData.health.breakdown.diversification,
        risk_adjusted:   healthData.health.breakdown.risk_adjusted,
        cost_efficiency: healthData.health.breakdown.cost_efficiency,
      }
    : undefined;

  return (
    <Dashboard
      summary={dashSummary}
      navHistory={nav}
      healthBreakdown={breakdown}
      insights={insightsQ.data?.insights ?? []}
      riskProfile={riskProfileQ.data ?? null}
      holdingsCount={holdings.data?.length ?? 0}
      onRiskProfileSaved={() => {
        qc.invalidateQueries({ queryKey: ["user", "risk-profile"] });
        qc.invalidateQueries({ queryKey: ["onboarding", "state"] });
      }}
    />
  );
}
