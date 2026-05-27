import { jsxs as _jsxs, jsx as _jsx } from "react/jsx-runtime";
import { useGoals } from "@/hooks/use-goals";
import { Card, CardLabel } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
function formatRs(paise) {
    const rs = paise / 100;
    if (rs >= 1_00_00_000)
        return `₹${(rs / 1_00_00_000).toFixed(1)} Cr`;
    if (rs >= 1_00_000)
        return `₹${(rs / 1_00_000).toFixed(1)} L`;
    if (rs >= 1_000)
        return `₹${(rs / 1_000).toFixed(1)}k`;
    return `₹${rs.toLocaleString("en-IN")}`;
}
function GoalRow({ goal }) {
    const pct = Math.round(goal.progress * 100);
    return (_jsxs("li", { className: "grid grid-cols-[1.6fr_80px_1fr_90px_80px_40px] gap-3 items-center py-3 border-t border-[rgb(var(--line)/0.10)]", children: [_jsxs("div", { children: [_jsxs("div", { className: "text-[14px] font-medium", children: [goal.icon, " ", goal.name] }), _jsxs("div", { className: "font-mono text-[10px] text-ink-3 mt-0.5 tracking-tight", children: ["by ", goal.targetDate, " \u00B7 ", formatRs(goal.targetAmount)] })] }), _jsxs("div", { className: `font-mono num text-[13px] ${goal.onTrack ? "text-pos" : "text-warm"}`, children: [pct, "%"] }), _jsx("div", { className: "h-1.5 bg-surface-3 rounded-full overflow-hidden", children: _jsx("div", { className: "h-full rounded-full", style: { width: `${pct}%`, background: goal.onTrack ? "var(--color-pos)" : "var(--color-warm)" } }) }), _jsxs("div", { className: "font-mono num text-[12px] text-ink-2", children: [formatRs(goal.monthlySip), "/mo"] }), _jsx(Badge, { tone: goal.onTrack ? "good" : "warm", className: "text-[9px]", children: goal.progress >= 1 ? "DONE" : goal.onTrack ? "ON TRACK" : "BEHIND" }), _jsx("span", { className: "text-ink-3 text-right", children: "\u203A" })] }));
}
export default function GoalsPage() {
    const { data, isLoading, isError } = useGoals();
    if (isLoading) {
        return (_jsx("div", { className: "px-6 py-8 lg:px-10 lg:py-10 max-w-[1080px] mx-auto w-full", children: _jsx("div", { className: "h-64 flex items-center justify-center font-mono text-[12px] text-ink-3", children: "Loading goals\u2026" }) }));
    }
    if (isError || !data) {
        return (_jsx("div", { className: "px-6 py-8 lg:px-10 lg:py-10 max-w-[1080px] mx-auto w-full", children: _jsx("div", { className: "h-64 flex items-center justify-center font-mono text-[12px] text-neg", children: "Could not load goals. Try again later." }) }));
    }
    const { goals, totals } = data;
    const onTrackCount = totals.onTrack;
    const totalCount = totals.total;
    const totalTarget = goals.reduce((s, g) => s + g.targetAmount, 0);
    const totalCurrent = goals.reduce((s, g) => s + g.currentAmount, 0);
    const headlineStatus = onTrackCount === totalCount
        ? "All goals on track."
        : onTrackCount === 0
            ? "Goals need attention."
            : `${onTrackCount} of ${totalCount} goals on track.`;
    return (_jsxs("div", { className: "px-6 py-8 lg:px-10 lg:py-10 max-w-[1080px] mx-auto w-full", children: [_jsx("div", { className: "font-mono text-[11px] uppercase tracking-[.18em] text-ink-3", children: "Goals" }), _jsx("h1", { className: "font-display text-3xl sm:text-4xl tracking-tightish leading-[1.05] mt-1.5", children: headlineStatus }), _jsx("p", { className: "text-[15.5px] text-ink-2 mt-3 max-w-[600px] leading-relaxed", children: "Track your financial milestones \u2014 from home down-payments to retirement \u2014 with monthly SIP projections." }), _jsx("div", { className: "mt-7 grid grid-cols-2 sm:grid-cols-4 gap-3", children: [
                    { label: "On track", value: `${onTrackCount} / ${totalCount}`, sub: "goals", tone: "text-pos" },
                    { label: "Total target", value: formatRs(totalTarget), sub: "combined", tone: "text-ink" },
                    { label: "Current corpus", value: formatRs(totalCurrent), sub: "invested", tone: "text-ink" },
                    { label: "Gap", value: formatRs(Math.max(0, totalTarget - totalCurrent)), sub: "to raise", tone: "text-warm" },
                ].map((kpi) => (_jsxs("div", { className: "rounded-lg bg-surface-1 border border-hairline p-4", children: [_jsx("div", { className: "font-mono text-[10px] uppercase tracking-[.14em] text-ink-3", children: kpi.label }), _jsx("div", { className: `font-display text-2xl num mt-1 ${kpi.tone}`, children: kpi.value }), _jsx("div", { className: "font-mono text-[10px] text-ink-3 mt-0.5", children: kpi.sub })] }, kpi.label))) }), _jsxs(Card, { className: "mt-5 p-6", children: [_jsxs("div", { className: "flex items-center mb-2", children: [_jsx(CardLabel, { children: "All goals \u00B7 funded %" }), _jsx("button", { className: "ml-auto text-[12px] text-accent hover:underline underline-offset-4", children: "+ Add goal" })] }), goals.length === 0 ? (_jsx("div", { className: "py-12 text-center font-mono text-[12px] text-ink-3", children: "No goals yet. Add your first goal to get started." })) : (_jsx("ul", { children: goals.map((g) => _jsx(GoalRow, { goal: g }, g.id)) }))] }), totals.atRisk > 0 && (_jsxs("div", { className: "mt-4 rounded-lg bg-warm-soft border border-warm/20 p-4 text-[13.5px]", children: [_jsxs("span", { className: "font-medium text-warm", children: [totals.atRisk, " goal", totals.atRisk > 1 ? "s" : "", " at risk"] }), " — ", "consider a SIP top-up or extending the horizon to close the gap."] }))] }));
}
