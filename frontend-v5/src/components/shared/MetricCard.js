import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { Card, CardLabel } from "@/components/ui/card";
import { cn } from "@/lib/utils";
export function MetricCard({ label, value, subtext, tone = "default", className }) {
    const toneCls = {
        default: "text-ink",
        pos: "text-pos",
        neg: "text-neg",
        warm: "text-warm",
        accent: "text-accent",
    };
    return (_jsxs(Card, { className: cn("p-5", className), children: [_jsx(CardLabel, { children: label }), _jsx("div", { className: cn("font-display num text-3xl tracking-tightish mt-2", toneCls[tone]), children: value }), subtext && _jsx("div", { className: "font-mono text-[10px] text-ink-3 mt-1 tracking-[.04em]", children: subtext })] }));
}
