import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { PieChart, Pie, Cell, ResponsiveContainer, Tooltip } from "recharts";
const COLORS = {
    equity: "rgb(var(--accent))",
    debt: "#A6A38E",
    gold: "rgb(var(--warm))",
    international: "#7A8298",
    cash: "#CFCFC2",
};
export function AllocationDonut({ slices, size = 220 }) {
    return (_jsx(ResponsiveContainer, { width: size, height: size, children: _jsxs(PieChart, { children: [_jsx(Pie, { data: slices, dataKey: "pct", nameKey: "label", innerRadius: size * 0.34, outerRadius: size * 0.46, startAngle: 90, endAngle: -270, stroke: "rgb(var(--surface-1))", strokeWidth: 2, isAnimationActive: false, children: slices.map((s) => (_jsx(Cell, { fill: COLORS[s.assetClass] }, s.assetClass))) }), _jsx(Tooltip, { contentStyle: {
                        background: "rgb(var(--surface-1))",
                        border: "1px solid rgb(var(--line) / 0.16)",
                        borderRadius: 10,
                        color: "rgb(var(--ink))",
                        fontSize: 12,
                    }, formatter: (v) => [`${v}%`, "Allocation"] })] }) }));
}
export const ALLOCATION_COLORS = COLORS;
