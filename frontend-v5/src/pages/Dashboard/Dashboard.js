import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { useNavigate } from "react-router-dom";
import { PortfolioValueCard } from "./PortfolioValueCard";
import { HealthScoreCard } from "./HealthScoreCard";
import { RiskMeterCard } from "./RiskMeterCard";
import { TopInsightsList } from "./TopInsightsList";
import { ImproveCTA } from "./ImproveCTA";
function healthLabel(score) {
    if (score >= 85)
        return { phrase: "in great shape", tone: "text-pos" };
    if (score >= 70)
        return { phrase: "mostly healthy", tone: "text-accent" };
    if (score >= 55)
        return { phrase: "needs some work", tone: "text-warm" };
    return { phrase: "needs attention", tone: "text-neg" };
}
/**
 * Dashboard — main view (data already resolved at this point).
 */
export function Dashboard({ summary, navHistory }) {
    const navigate = useNavigate();
    const { phrase, tone } = healthLabel(summary.healthScore);
    const insightCount = summary.topInsights.length;
    // Target score = current + expected gain from applying all insights (capped at 99)
    const targetScore = Math.min(99, Math.round(summary.healthScore + insightCount * 2.5));
    // Derive verdict from score
    const verdict = summary.healthScore >= 85
        ? "Excellent — keep it up."
        : summary.healthScore >= 70
            ? "Good — with a couple of fixes."
            : summary.healthScore >= 55
                ? "Fair — a few changes needed."
                : "Needs work — start with the top insight.";
    return (_jsxs("div", { className: "px-6 py-8 lg:px-10 lg:py-10 max-w-[1080px] mx-auto w-full", children: [_jsx("div", { className: "font-mono text-[11px] uppercase tracking-[.18em] text-ink-3", children: "Dashboard" }), _jsxs("h1", { className: "font-display text-3xl sm:text-4xl tracking-tightish leading-[1.05] mt-1.5", children: ["Your portfolio is", " ", _jsx("span", { className: tone, children: phrase }), "."] }), _jsx("p", { className: "text-[15.5px] sm:text-base text-ink-2 mt-3 leading-relaxed max-w-[600px]", children: summary.topInsights[0]?.title ??
                    "Connect your investments to see what to fix first." }), _jsx("div", { className: "mt-7 rounded-lg bg-surface-1 border border-hairline shadow-card", children: _jsxs("div", { className: "grid grid-cols-1 md:grid-cols-3 gap-y-7 md:divide-x md:divide-[rgb(var(--line)/0.10)] p-6 sm:p-7", children: [_jsx(PortfolioValueCard, { value: summary.totalValue, yearChangePct: summary.yearChange.pct, navHistory: navHistory }), _jsx(HealthScoreCard, { score: summary.healthScore, verdict: verdict }), _jsx(RiskMeterCard, { level: summary.riskBucketIndex, bucket: summary.riskBucket })] }) }), _jsxs("div", { className: "mt-9 mb-3 flex items-center", children: [_jsx("h2", { className: "font-mono text-[11px] uppercase tracking-[.18em] text-ink-3", children: "Top insights" }), insightCount > 0 && (_jsxs("span", { className: "ml-auto text-[12px] text-ink-3", children: [insightCount, " insight", insightCount !== 1 ? "s" : "", " \u00B7 plain English"] }))] }), _jsx(TopInsightsList, { insights: summary.topInsights, onAction: (recId) => navigate(`/recommendations?focus=${recId}`) }), _jsx(ImproveCTA, { currentScore: summary.healthScore, targetScore: targetScore, moves: insightCount, onClick: () => navigate("/recommendations") })] }));
}
