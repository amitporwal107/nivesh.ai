import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { ArrowUpRight } from "lucide-react";
import { CardLabel } from "@/components/ui/card";
import { SparkArea } from "@/components/charts/SparkArea";
import { formatINR, formatPct } from "@/lib/formatters";
export function PortfolioValueCard({ value, yearChangePct, navHistory }) {
    return (_jsxs("div", { className: "md:pr-7", children: [_jsx(CardLabel, { children: "Portfolio value" }), _jsx("div", { className: "font-display num text-[44px] sm:text-[52px] leading-none tracking-tightish mt-2", children: formatINR(value) }), _jsxs("div", { className: "flex items-center gap-1.5 mt-2 text-[12px] text-pos", children: [_jsx(ArrowUpRight, { className: "h-3.5 w-3.5" }), _jsxs("span", { children: [formatPct(yearChangePct, { signed: true }), " over the last year"] })] }), _jsx("div", { className: "mt-3 -mx-2", children: _jsx(SparkArea, { data: navHistory, height: 56 }) })] }));
}
