import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { cn } from "@/lib/utils";
/**
 * Circular score indicator. Hand-rolled SVG (not Recharts) — this shape is
 * fixed and tiny; bringing in a chart lib here is overkill.
 */
export function ScoreRing({ score, size = 160, strokeWidth = 10, label = "/ 100", className, }) {
    const r = (size - strokeWidth - 4) / 2;
    const C = 2 * Math.PI * r;
    const dash = C * Math.min(1, Math.max(0, score / 100));
    const cx = size / 2;
    return (_jsxs("svg", { width: size, height: size, viewBox: `0 0 ${size} ${size}`, role: "img", "aria-label": `Health score ${score} out of 100`, className: cn(className), children: [_jsx("circle", { cx: cx, cy: cx, r: r, fill: "none", stroke: "rgb(var(--surface-2))", strokeWidth: strokeWidth }), _jsx("circle", { cx: cx, cy: cx, r: r, fill: "none", stroke: "rgb(var(--accent))", strokeWidth: strokeWidth, strokeLinecap: "round", strokeDasharray: `${dash} ${C - dash}`, transform: `rotate(-90 ${cx} ${cx})` }), _jsx("text", { x: cx, y: cx - 2, textAnchor: "middle", dominantBaseline: "middle", className: "fill-ink font-display", style: { fontSize: size * 0.34, letterSpacing: "-0.04em" }, children: score }), _jsx("text", { x: cx, y: cx + size * 0.20, textAnchor: "middle", className: "fill-ink-3 font-mono", style: { fontSize: size * 0.07, letterSpacing: 2 }, children: label })] }));
}
