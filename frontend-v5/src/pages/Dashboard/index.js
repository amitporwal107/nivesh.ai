import { jsx as _jsx } from "react/jsx-runtime";
/**
 * Dashboard — route entry.
 *
 * Owns: react-query data fetch + loading/empty/error gates.
 * Doesn't own: layout chrome.
 *
 * V3 health score is fetched in parallel (separate hook, ETag-aware) so a
 * score-only refetch doesn't invalidate holdings / nav-history.
 */
import { useNavigate } from "react-router-dom";
import { usePortfolioSummary, usePortfolioNavHistory } from "@/hooks/use-portfolio";
import { useV3Portfolio } from "@/hooks/use-insights";
import { LoadingSkeleton } from "@/components/shared/LoadingSkeleton";
import { ErrorState } from "@/components/shared/ErrorState";
import { EmptyState } from "@/components/shared/EmptyState";
import { Dashboard } from "./Dashboard";
export default function DashboardPage() {
    const navigate = useNavigate();
    const summary = usePortfolioSummary();
    const navHistory = usePortfolioNavHistory("1y");
    const v3 = useV3Portfolio(); // independent; not blocking
    if (summary.isPending || navHistory.isPending) {
        return (_jsx("div", { className: "px-6 py-8 lg:px-10 lg:py-10 max-w-[1080px] mx-auto w-full", children: _jsx(LoadingSkeleton, { variant: "dashboard" }) }));
    }
    if (summary.isError || navHistory.isError) {
        return (_jsx(ErrorState, { title: "Couldn't load your dashboard", error: summary.error ?? navHistory.error, onRetry: () => {
                summary.refetch();
                navHistory.refetch();
            } }));
    }
    if (!summary.data || summary.data.totalValue === 0) {
        return (_jsx(EmptyState, { title: "Connect your investments to begin", description: "Upload a CAS PDF, a broker statement, or an Excel/CSV file. We parse it, score it, and surface what to do next.", action: { label: "Upload a statement", onClick: () => navigate("/onboarding") } }));
    }
    // Prefer canonical /insights/analysis health score when resolved.
    const dashSummary = v3.data && !v3.isError
        ? { ...summary.data, healthScore: v3.data.health.score || summary.data.healthScore }
        : summary.data;
    return _jsx(Dashboard, { summary: dashSummary, navHistory: navHistory.data ?? [] });
}
