import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { ChevronRight } from "lucide-react";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
const TONE_BY_CAT = {
    overlap: "neg",
    concentration: "warm",
    balance: "warm",
    cost: "accent",
    tax: "good",
    goal: "accent",
};
const TAG_BY_CAT = {
    overlap: "OVERLAP",
    concentration: "CONCENTRATION",
    balance: "BALANCE",
    cost: "COST",
    tax: "TAX",
    goal: "GOAL",
};
export function InsightCard({ insight, rank, onAction, className }) {
    const tone = TONE_BY_CAT[insight.category];
    const tag = TAG_BY_CAT[insight.category];
    return (_jsxs(Card, { className: cn("flex items-start gap-5 p-5 sm:p-6", className), children: [typeof rank === "number" && (_jsx("div", { className: "font-display text-3xl text-ink-4 tracking-tightish min-w-[40px]", children: rank })), _jsxs("div", { className: "flex-1 min-w-0", children: [_jsx("h3", { className: "font-display text-xl sm:text-2xl tracking-tightish leading-tight", children: insight.title }), _jsx("p", { className: "text-[14.5px] text-ink-2 mt-2 leading-relaxed", children: insight.detail }), insight.evidence && (_jsx("div", { className: "mt-3 flex flex-wrap gap-x-5 gap-y-1.5", children: insight.evidence.map((e) => (_jsxs("div", { className: "font-mono text-[11px] tracking-[.04em] text-ink-3", children: [_jsx("span", { className: "text-ink-3", children: e.label.toUpperCase() }), " · ", _jsx("span", { className: "text-ink-2 num", children: e.value })] }, e.label))) }))] }), _jsxs("div", { className: "flex flex-col items-end gap-3 shrink-0", children: [_jsx(Badge, { tone: tone, children: tag }), insight.cta && (_jsxs("button", { type: "button", onClick: () => onAction?.(insight.cta.recommendationId), className: "inline-flex items-center gap-1 text-[13px] text-accent hover:underline", children: [insight.cta.label, _jsx(ChevronRight, { className: "h-3.5 w-3.5" })] }))] })] }));
}
