import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { cn } from "@/lib/utils";
import { RecommendationCard } from "@/components/shared/RecommendationCard";
export function Recommendations({ recs, filter, onFilter, onApply }) {
    // counts include unfiltered counts via this trick: the server can return filtered;
    // but for the UI we show "all" as the active set size.
    const counts = { all: recs.length, keep: 0, reduce: 0, add: 0 };
    recs.forEach((r) => { counts[r.action]++; });
    const filters = [
        { k: "all", label: "All" },
        { k: "keep", label: "Keep" },
        { k: "reduce", label: "Reduce" },
        { k: "add", label: "Add" },
    ];
    return (_jsxs("div", { className: "px-6 py-8 lg:px-10 lg:py-10 max-w-[1080px] mx-auto w-full", children: [_jsxs("div", { children: [_jsx("div", { className: "font-mono text-[11px] uppercase tracking-[.18em] text-ink-3", children: "Recommendations" }), _jsxs("h1", { className: "font-display text-3xl sm:text-4xl tracking-tightish leading-[1.05] mt-1.5", children: ["3 categories, ", recs.length, " moves."] }), _jsx("p", { className: "text-[15.5px] text-ink-2 mt-3 max-w-[580px] leading-relaxed", children: "We never push trades. Each card explains why, the benefit, and the risk impact before you apply." })] }), _jsx("div", { role: "tablist", className: "inline-flex gap-1 mt-7 p-1 rounded-md bg-surface-2 border border-hairline", children: filters.map((f) => {
                    const on = filter === f.k;
                    return (_jsxs("button", { role: "tab", "aria-selected": on, onClick: () => onFilter(f.k), className: cn("px-4 py-2 text-[13px] rounded-md transition-colors", on
                            ? "bg-surface-1 text-ink border border-hairline font-medium"
                            : "text-ink-2 hover:text-ink"), children: [f.label, " \u00B7 ", counts[f.k] ?? 0] }, f.k));
                }) }), _jsx("div", { className: "mt-6 flex flex-col gap-3", children: recs.map((r) => (_jsx(RecommendationCard, { rec: r, onApply: () => onApply(r.id), onLearnMore: () => { } }, r.id))) })] }));
}
