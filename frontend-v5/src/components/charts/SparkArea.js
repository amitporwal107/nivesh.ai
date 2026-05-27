import { jsx as _jsx, jsxs as _jsxs, Fragment as _Fragment } from "react/jsx-runtime";
import { AreaChart, Area, ResponsiveContainer, Tooltip, YAxis, XAxis } from "recharts";
import { formatINRCompact, formatDate } from "@/lib/formatters";
/**
 * Single-series area sparkline using Recharts. The token-aware colors come
 * through inline so the chart respects light/dark theme switches.
 */
export function SparkArea({ data, height = 80, showAxis = false }) {
    return (_jsx(ResponsiveContainer, { width: "100%", height: height, children: _jsxs(AreaChart, { data: data, margin: { top: 4, right: 4, bottom: 0, left: 0 }, children: [_jsx("defs", { children: _jsxs("linearGradient", { id: "sparkArea", x1: "0", y1: "0", x2: "0", y2: "1", children: [_jsx("stop", { offset: "0%", stopColor: "rgb(var(--accent))", stopOpacity: 0.28 }), _jsx("stop", { offset: "100%", stopColor: "rgb(var(--accent))", stopOpacity: 0 })] }) }), showAxis && (_jsxs(_Fragment, { children: [_jsx(XAxis, { dataKey: "date", tickLine: false, axisLine: false, tick: { fill: "rgb(var(--ink-3))", fontFamily: "var(--font-mono)", fontSize: 11 }, tickFormatter: (v) => new Date(v).toLocaleDateString("en-IN", { month: "short" }), minTickGap: 32 }), _jsx(YAxis, { hide: true })] })), _jsx(Tooltip, { cursor: { stroke: "rgb(var(--line) / 0.3)" }, contentStyle: {
                        background: "rgb(var(--surface-1))",
                        border: "1px solid rgb(var(--line) / 0.16)",
                        borderRadius: 10,
                        padding: "8px 12px",
                        color: "rgb(var(--ink))",
                        boxShadow: "0 12px 24px -8px rgb(15 23 42 / 0.12)",
                    }, labelFormatter: (v) => formatDate(v), formatter: (v) => [formatINRCompact(v / 100), "Value"] }), _jsx(Area, { type: "monotone", dataKey: "value", stroke: "rgb(var(--accent))", strokeWidth: 2, fill: "url(#sparkArea)", isAnimationActive: false })] }) }));
}
