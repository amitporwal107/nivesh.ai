import { jsx as _jsx, jsxs as _jsxs, Fragment as _Fragment } from "react/jsx-runtime";
import { Treemap, ResponsiveContainer, Tooltip } from "recharts";
/**
 * Sector exposure treemap. Boxes scale by allocation %; sectors over the
 * policy cap render in the accent color, others in muted neutral.
 */
export function SectorTreemap({ data, height = 320 }) {
    return (_jsx(ResponsiveContainer, { width: "100%", height: height, children: _jsx(Treemap, { data: data, dataKey: "size", stroke: "rgb(var(--surface-1))", isAnimationActive: false, content: _jsx(TreemapCell, {}), children: _jsx(Tooltip, { contentStyle: {
                    background: "rgb(var(--surface-1))",
                    border: "1px solid rgb(var(--line) / 0.16)",
                    borderRadius: 10,
                    color: "rgb(var(--ink))",
                    fontSize: 12,
                }, formatter: (v) => [`${v}%`, "Sector"] }) }) }));
}
function TreemapCell(props) {
    const { x, y, width, height, name, size, over } = props;
    if (width < 2 || height < 2)
        return null;
    const fill = over ? "rgb(var(--accent))" : "#7A8298";
    const opacity = over ? 0.9 : 0.55;
    return (_jsxs("g", { children: [_jsx("rect", { x: x, y: y, width: width, height: height, fill: fill, fillOpacity: opacity, stroke: "rgb(var(--surface-1))", strokeWidth: 3 }), width > 80 && height > 50 && (_jsxs(_Fragment, { children: [_jsx("text", { x: x + 12, y: y + 22, fontFamily: "var(--font-sans)", fontWeight: 500, fontSize: 13, fill: "#FFFFFF", children: name }), _jsxs("text", { x: x + 12, y: y + 42, fontFamily: "var(--font-display)", fontSize: 22, letterSpacing: "-0.02em", fill: "#FFFFFF", children: [size, "%"] })] }))] }));
}
