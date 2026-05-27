import { jsx as _jsx, jsxs as _jsxs, Fragment as _Fragment } from "react/jsx-runtime";
/**
 * Plan Board — action kanban wired to plansService.getActive().
 */
import { useQuery } from "@tanstack/react-query";
import { plansService } from "@/services";
import { Card, CardLabel } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
function usePlan() {
    return useQuery({
        queryKey: ["plans", "active"],
        queryFn: () => plansService.getActive(),
    });
}
const COLUMNS = [
    { id: "pending", label: "To do", statuses: ["pending"] },
    { id: "done", label: "Done", statuses: ["done"] },
    { id: "skipped", label: "Skipped", statuses: ["skipped"] },
];
function actionTypeTone(type) {
    if (["sell", "switch"].includes(type))
        return "neg";
    if (["buy", "sip_increase"].includes(type))
        return "good";
    if (["sip_decrease"].includes(type))
        return "warm";
    return "accent";
}
function PlanActionCard({ action }) {
    const tone = actionTypeTone(String(action.action_type));
    const label = String(action.action_type).replace(/_/g, " ").toUpperCase();
    const impact = action.estimated_impact;
    return (_jsxs("div", { className: "rounded-lg bg-surface-1 border border-hairline p-3 mb-2", children: [_jsxs("div", { className: "flex items-center gap-2 mb-2", children: [_jsx(Badge, { tone: tone, className: "text-[9px]", children: label }), impact?.annual_savings_rs != null && (_jsxs("span", { className: "ml-auto font-mono num text-[11px] text-pos", children: ["+\u20B9", Number(impact.annual_savings_rs).toLocaleString("en-IN"), "/yr"] }))] }), _jsxs("div", { className: "text-[13px] font-medium leading-[1.35]", children: [action.holding_name ?? "Action", action.suggested_alternative ? ` → ${action.suggested_alternative}` : ""] }), action.rationale && (_jsx("p", { className: "mt-1 text-[12px] text-ink-3 leading-relaxed", children: action.rationale }))] }));
}
function EmptyPlan() {
    return (_jsxs("div", { className: "py-16 text-center", children: [_jsx("div", { className: "font-display text-xl text-ink-2 mb-2", children: "No active plan" }), _jsx("p", { className: "text-[14px] text-ink-3 max-w-[400px] mx-auto mb-6", children: "Generate an action plan from your portfolio analysis to see recommended moves here." }), _jsx("button", { className: "rounded-lg bg-accent text-white font-medium text-[13px] px-6 py-3 hover:bg-accent/90 transition-colors", children: "Generate plan \u2192" })] }));
}
function PlanKanban({ plan }) {
    const actions = plan.actions ?? [];
    const totalSavings = actions.reduce((s, a) => s + (a.estimated_impact?.annual_savings_rs ?? 0), 0);
    const scoreDelta = (plan.health_score_projected ?? plan.health_score_before ?? 0) - (plan.health_score_before ?? 0);
    return (_jsxs(_Fragment, { children: [_jsxs("div", { className: "mt-6 rounded-lg bg-surface-1 border border-hairline p-4 flex flex-wrap gap-6", children: [_jsxs("div", { children: [_jsx("div", { className: "font-mono text-[10px] uppercase tracking-[.12em] text-ink-3", children: "Total actions" }), _jsx("div", { className: "font-display text-2xl num mt-0.5", children: plan.actions_total ?? actions.length })] }), totalSavings > 0 && (_jsxs("div", { children: [_jsx("div", { className: "font-mono text-[10px] uppercase tracking-[.12em] text-ink-3", children: "Annual savings" }), _jsxs("div", { className: "font-display text-2xl num mt-0.5 text-pos", children: ["+\u20B9", totalSavings.toLocaleString("en-IN"), "/yr"] })] })), scoreDelta > 0 && (_jsxs("div", { children: [_jsx("div", { className: "font-mono text-[10px] uppercase tracking-[.12em] text-ink-3", children: "Health impact" }), _jsxs("div", { className: "font-display text-2xl num mt-0.5 text-pos", children: ["+", scoreDelta.toFixed(0), " pt"] })] })), _jsx("div", { className: "ml-auto flex items-center gap-2", children: _jsxs("span", { className: "font-mono text-[10px] text-ink-3", children: [plan.actions_done ?? 0, " done \u00B7 ", plan.actions_pending ?? 0, " pending"] }) })] }), _jsx("div", { className: "mt-5 grid grid-cols-1 md:grid-cols-3 gap-4", children: COLUMNS.map((col) => {
                    const colActions = actions.filter((a) => col.statuses.includes(String(a.status ?? "pending")));
                    return (_jsxs("div", { children: [_jsxs("div", { className: "flex items-center mb-3", children: [_jsx("div", { className: "font-mono text-[10px] uppercase tracking-[.16em] text-ink-3", children: col.label }), _jsxs("span", { className: "ml-2 font-mono text-[10px] text-ink-4", children: ["(", colActions.length, ")"] })] }), colActions.length === 0 ? (_jsx("div", { className: "rounded-lg border border-dashed border-hairline h-24 flex items-center justify-center text-[12px] text-ink-4 font-mono", children: "empty" })) : (colActions.map((a) => _jsx(PlanActionCard, { action: a }, a.action_id)))] }, col.id));
                }) })] }));
}
export default function PlanPage() {
    const { data: plan, isLoading, isError } = usePlan();
    return (_jsxs("div", { className: "px-6 py-8 lg:px-10 lg:py-10 max-w-[1080px] mx-auto w-full", children: [_jsx("div", { className: "font-mono text-[11px] uppercase tracking-[.18em] text-ink-3", children: "Workspace \u00B7 Plan board" }), _jsxs("div", { className: "flex items-start mt-1.5", children: [_jsx("h1", { className: "font-display text-3xl sm:text-4xl tracking-tightish leading-[1.05]", children: "Your plan, end-to-end." }), _jsx("button", { className: "ml-auto mt-1 rounded-lg bg-accent text-white font-medium text-[13px] px-5 py-2.5 hover:bg-accent/90 transition-colors", children: "Execute \u2192" })] }), isLoading && (_jsx("div", { className: "py-16 text-center font-mono text-[12px] text-ink-3", children: "Loading plan\u2026" })), isError && (_jsx("div", { className: "py-16 text-center font-mono text-[12px] text-neg", children: "Could not load plan." })), !isLoading && !isError && (plan ? _jsx(PlanKanban, { plan: plan }) : _jsx(EmptyPlan, {})), plan && (_jsxs(Card, { className: "mt-6 p-4", children: [_jsx(CardLabel, { children: "Action types" }), _jsx("div", { className: "flex flex-wrap gap-3 mt-3", children: [
                            { type: "sell / switch", tone: "neg" },
                            { type: "buy", tone: "good" },
                            { type: "sip_increase", tone: "good" },
                            { type: "sip_decrease", tone: "warm" },
                            { type: "hold", tone: "accent" },
                        ].map((e) => (_jsx("div", { className: "flex items-center gap-1.5", children: _jsx(Badge, { tone: e.tone, className: "text-[9px]", children: e.type.replace(/_/g, " ").toUpperCase() }) }, e.type))) })] }))] }));
}
