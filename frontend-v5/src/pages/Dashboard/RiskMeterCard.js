import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { CardLabel } from "@/components/ui/card";
import { RiskMeter } from "@/components/charts/RiskMeter";
const PRETTY = {
    "very-low": "Very low",
    low: "Low",
    moderate: "Moderate",
    high: "High",
    "very-high": "Very high",
};
export function RiskMeterCard({ level, bucket }) {
    return (_jsxs("div", { className: "md:pl-7", children: [_jsx(CardLabel, { children: "Risk level" }), _jsx("div", { className: "font-display text-2xl sm:text-[26px] tracking-tightish mt-2", children: PRETTY[bucket] }), _jsx(RiskMeter, { level: level, className: "mt-4", label: PRETTY[bucket].toUpperCase() }), _jsx("div", { className: "font-mono text-[10px] tracking-[.06em] text-ink-3 mt-2", children: "ALIGNED WITH YOUR PROFILE" })] }));
}
