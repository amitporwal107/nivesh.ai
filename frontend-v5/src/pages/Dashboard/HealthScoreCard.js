import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { CardLabel } from "@/components/ui/card";
import { ScoreRing } from "@/components/charts/ScoreRing";
export function HealthScoreCard({ score, verdict }) {
    return (_jsxs("div", { className: "md:px-7 flex items-center gap-5", children: [_jsx(ScoreRing, { score: score, size: 132 }), _jsxs("div", { children: [_jsx(CardLabel, { children: "Health score" }), _jsx("p", { className: "text-[15px] mt-1.5 text-ink-2 max-w-[180px] leading-snug", children: verdict })] })] }));
}
