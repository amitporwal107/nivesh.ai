import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { Card } from "@/components/ui/card";
import { StatusBadge } from "@/components/shared/StatusBadge";
import { Button } from "@/components/ui/button";
import { ArrowRight } from "lucide-react";
import { formatINR } from "@/lib/formatters";
import { cn } from "@/lib/utils";
/**
 * Single recommendation card showing the four contract fields:
 * Why this matters · Expected benefit · Risk impact · Suggested action.
 */
export function RecommendationCard({ rec, onApply, onLearnMore, className }) {
    return (_jsxs(Card, { className: cn("p-6", className), children: [_jsxs("div", { className: "flex items-center gap-3", children: [_jsx(StatusBadge, { action: rec.action }), _jsx("span", { className: "font-mono text-[10.5px] tracking-[.06em] text-ink-3", children: rec.suggestedAction }), rec.estAnnualGain != null && (_jsxs("span", { className: "ml-auto font-mono text-[12px] text-pos num", children: ["+", formatINR(rec.estAnnualGain, { compact: true }), "/yr"] }))] }), _jsx("h3", { className: "font-display text-xl sm:text-[22px] tracking-tightish mt-3 leading-snug", children: rec.title }), _jsxs("div", { className: "grid grid-cols-1 sm:grid-cols-3 gap-x-5 gap-y-4 mt-5 pt-4 border-t border-hairline", children: [_jsx(Field, { label: "Why this matters", body: rec.why }), _jsx(Field, { label: "Expected benefit", body: rec.benefit, tone: "pos" }), _jsx(Field, { label: "Risk impact", body: rec.riskImpact })] }), _jsxs("div", { className: "flex gap-2 mt-5", children: [_jsxs(Button, { variant: "accent", size: "sm", onClick: onApply, children: ["Apply ", _jsx(ArrowRight, { className: "h-3.5 w-3.5" })] }), _jsx(Button, { variant: "outline", size: "sm", onClick: onLearnMore, children: "Learn more" })] })] }));
}
function Field({ label, body, tone = "default" }) {
    return (_jsxs("div", { children: [_jsx("div", { className: "font-mono text-[10px] uppercase tracking-[.12em] text-ink-3", children: label }), _jsx("div", { className: cn("text-[13.5px] mt-1.5 leading-relaxed", tone === "pos" ? "text-pos font-medium" : "text-ink-2"), children: body })] }));
}
