import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { ArrowRight } from "lucide-react";
import { Button } from "@/components/ui/button";
export function ImproveCTA({ currentScore, targetScore, moves, onClick }) {
    return (_jsxs("div", { className: "mt-7 p-6 sm:p-7 rounded-lg bg-ink text-on-accent flex flex-col sm:flex-row gap-5 sm:items-center", children: [_jsxs("div", { className: "flex-1", children: [_jsx("div", { className: "text-[13px] tracking-[.04em] opacity-60", children: "The one thing" }), _jsxs("div", { className: "font-display text-2xl sm:text-[28px] tracking-tightish mt-1 leading-tight", children: ["Take your score from ", currentScore, " \u2192 ", targetScore, " in ", moves, " moves."] })] }), _jsxs(Button, { variant: "accent", size: "lg", onClick: onClick, className: "self-start sm:self-auto", children: ["Improve portfolio", _jsx(ArrowRight, { className: "h-4 w-4" })] })] }));
}
