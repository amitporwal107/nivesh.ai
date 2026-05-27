import { jsx as _jsx } from "react/jsx-runtime";
import { InsightCard } from "@/components/shared/InsightCard";
export function TopInsightsList({ insights, onAction }) {
    return (_jsx("div", { className: "grid gap-3", children: insights.map((ins, i) => (_jsx(InsightCard, { insight: ins, rank: i + 1, onAction: onAction }, ins.id))) }));
}
