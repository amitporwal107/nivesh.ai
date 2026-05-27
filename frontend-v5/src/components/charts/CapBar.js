import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { cn } from "@/lib/utils";
/**
 * Horizontal bar with optional policy-cap tick.
 * Above cap → neg color, below → accent.
 */
export function CapBar({ pct, capPct, className, height = 8 }) {
    const over = capPct != null && pct > capPct;
    return (_jsxs("div", { className: cn("relative w-full rounded-full bg-surface-2 overflow-hidden", className), style: { height }, "aria-label": `${pct}%${capPct ? `, cap ${capPct}%` : ""}`, children: [_jsx("div", { className: cn("h-full rounded-full transition-all", over ? "bg-neg" : "bg-accent"), style: { width: `${Math.min(100, pct)}%` } }), capPct != null && (_jsx("div", { className: "absolute top-[-2px] bottom-[-2px] w-px bg-ink/40", style: { left: `${capPct}%` }, "aria-hidden": true }))] }));
}
