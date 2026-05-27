import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { cn } from "@/lib/utils";
/** 5-step risk meter, ascending. Only the active bucket and prior buckets fill. */
export function RiskMeter({ level, className, label }) {
    return (_jsxs("div", { className: cn("flex flex-col gap-2", className), "aria-label": label ?? `Risk level ${level} of 5`, children: [_jsx("div", { className: "flex gap-1.5", children: [1, 2, 3, 4, 5].map((i) => (_jsx("div", { className: cn("h-2 flex-1 rounded-full transition-colors", i <= level ? "bg-accent" : "bg-surface-2") }, i))) }), label && (_jsxs("div", { className: "font-mono text-[10px] uppercase tracking-[.08em] text-ink-3", children: [label, " \u00B7 ", level, " of 5"] }))] }));
}
