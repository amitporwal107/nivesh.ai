import React from "react";
import { motion } from "framer-motion";
import {
  ResponsiveContainer,
  BarChart, Bar,
  PieChart, Pie, Cell,
  LineChart, Line,
  XAxis, YAxis, CartesianGrid,
  Tooltip as RechartsTooltip, Legend,
} from "recharts";

// Renders a Copilot-emitted chart spec. Supports four chart types
// (bar, donut, line, stacked_bar) — narrow on purpose so the LLM
// prompt + parser stay simple. Falls back to a labelled HTML table
// if the spec is missing required fields.
//
// Spec shape (validated server-side):
//   { type, title, data: [{label, value, series?}], unit?, x_label?, y_label?, highlight? }
// Chromatically distinct palette — adjacent slices read as different
// colors on small donuts. We deliberately interleave cool/warm/neutral
// (indigo → emerald → amber → pink → cyan → violet → lime → slate) so
// neighbouring legend entries always contrast. Red is REMOVED from the
// palette and reserved as the highlight-only color, so a red slice
// always means "above threshold / over-concentrated".
const PALETTE = [
  "#6366f1", // indigo — cool blue-purple
  "#10b981", // emerald — green
  "#f59e0b", // amber — yellow
  "#ec4899", // pink
  "#06b6d4", // cyan
  "#8b5cf6", // violet
  "#84cc16", // lime
  "#64748b", // slate — neutral
];
const HIGHLIGHT_COLOR = "#ef4444"; // red — reserved for highlights only

function fmtValue(v, unit) {
  if (v == null || Number.isNaN(v)) return "";
  const n = Number(v);
  const rounded = Math.abs(n) >= 100 ? n.toFixed(0) : n.toFixed(1);
  return unit ? `${rounded}${unit}` : rounded;
}

function FallbackTable({ spec }) {
  const data = Array.isArray(spec?.data) ? spec.data : [];
  return (
    <div className="my-3 border border-slate-200 dark:border-slate-700 rounded-lg overflow-hidden">
      {spec?.title && (
        <div className="text-[11px] font-semibold uppercase tracking-wider text-slate-600 dark:text-slate-300 px-3 py-1.5 bg-slate-50 dark:bg-slate-800">
          {spec.title}
        </div>
      )}
      <table className="w-full text-xs">
        <tbody>
          {data.map((d, i) => (
            <tr key={i} className="border-t border-slate-100 dark:border-slate-800">
              <td className="px-3 py-1.5 text-slate-700 dark:text-slate-200">{d.label}</td>
              <td className="px-3 py-1.5 text-right font-mono text-slate-900 dark:text-slate-100">
                {fmtValue(d.value, spec?.unit)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ChartHeader({ spec }) {
  if (!spec?.title) return null;
  return (
    <div className="text-[11px] font-semibold uppercase tracking-wider text-slate-600 dark:text-slate-300 mb-1.5 px-1">
      {spec.title}
    </div>
  );
}

function tooltipFormatter(unit) {
  return (val, name) => [fmtValue(val, unit), name];
}

function highlightSet(spec) {
  return new Set(Array.isArray(spec?.highlight) ? spec.highlight : []);
}

function pivotForStacked(data) {
  // data: [{label, value, series}, ...] → [{label, [series_a]: v, [series_b]: v, ...}]
  const seriesNames = new Set();
  const byLabel = new Map();
  data.forEach((d) => {
    seriesNames.add(d.series || "value");
    const row = byLabel.get(d.label) || { label: d.label };
    row[d.series || "value"] = Number(d.value) || 0;
    byLabel.set(d.label, row);
  });
  return { rows: Array.from(byLabel.values()), seriesNames: Array.from(seriesNames) };
}

export default function ChartBlock({ spec }) {
  // Hard guards — match server-side validator but be defensive on the
  // client too, so a stale cached response with an old schema doesn't
  // crash the chat.
  if (!spec || typeof spec !== "object") return null;
  const data = Array.isArray(spec.data) ? spec.data : [];
  if (data.length < 2) return <FallbackTable spec={spec} />;
  const type = spec.type;
  const unit = spec.unit;
  const hSet = highlightSet(spec);

  return (
    <motion.div
      initial={{ opacity: 0, y: 8, scale: 0.985 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      transition={{ duration: 0.35, ease: [0.16, 1, 0.3, 1], delay: 0.1 }}
      className="my-3 rounded-xl border border-slate-200/80 dark:border-slate-700/60 bg-gradient-to-b from-white to-slate-50/30 dark:from-slate-900 dark:to-slate-900/80 px-3 py-3 shadow-sm hover:shadow-md transition-shadow"
      data-testid="copilot-chart-block"
    >
      <ChartHeader spec={spec} />
      <div style={{ width: "100%", height: 220 }}>
        <ResponsiveContainer width="100%" height="100%">
          {type === "bar" ? (
            <BarChart data={data} margin={{ top: 8, right: 8, left: 0, bottom: 8 }}>
              <CartesianGrid strokeDasharray="3 3" opacity={0.3} />
              <XAxis dataKey="label" tick={{ fontSize: 10 }} interval={0} angle={data.length > 4 ? -20 : 0} textAnchor={data.length > 4 ? "end" : "middle"} height={data.length > 4 ? 50 : 30} />
              <YAxis tick={{ fontSize: 10 }} tickFormatter={(v) => fmtValue(v, unit)} />
              <RechartsTooltip formatter={tooltipFormatter(unit)} />
              <Bar dataKey="value" radius={[4, 4, 0, 0]}>
                {data.map((d, i) => (
                  <Cell key={i} fill={hSet.has(d.label) ? HIGHLIGHT_COLOR : PALETTE[i % PALETTE.length]} />
                ))}
              </Bar>
            </BarChart>
          ) : type === "donut" ? (
            <PieChart>
              <Pie
                data={data}
                dataKey="value"
                nameKey="label"
                cx="50%"
                cy="50%"
                innerRadius="55%"
                outerRadius="85%"
                paddingAngle={2}
                stroke="none"
              >
                {data.map((d, i) => (
                  <Cell key={i} fill={hSet.has(d.label) ? HIGHLIGHT_COLOR : PALETTE[i % PALETTE.length]} />
                ))}
              </Pie>
              <RechartsTooltip formatter={tooltipFormatter(unit)} />
              <Legend wrapperStyle={{ fontSize: 10 }} iconSize={8} />
            </PieChart>
          ) : type === "line" ? (
            <LineChart data={data} margin={{ top: 8, right: 8, left: 0, bottom: 8 }}>
              <CartesianGrid strokeDasharray="3 3" opacity={0.3} />
              <XAxis dataKey="label" tick={{ fontSize: 10 }} />
              <YAxis tick={{ fontSize: 10 }} tickFormatter={(v) => fmtValue(v, unit)} />
              <RechartsTooltip formatter={tooltipFormatter(unit)} />
              <Line type="monotone" dataKey="value" stroke={PALETTE[0]} strokeWidth={2} dot={{ r: 3 }} />
            </LineChart>
          ) : type === "stacked_bar" ? (() => {
            const { rows, seriesNames } = pivotForStacked(data);
            return (
              <BarChart data={rows} margin={{ top: 8, right: 8, left: 0, bottom: 8 }}>
                <CartesianGrid strokeDasharray="3 3" opacity={0.3} />
                <XAxis dataKey="label" tick={{ fontSize: 10 }} interval={0} />
                <YAxis tick={{ fontSize: 10 }} tickFormatter={(v) => fmtValue(v, unit)} />
                <RechartsTooltip formatter={tooltipFormatter(unit)} />
                <Legend wrapperStyle={{ fontSize: 10 }} iconSize={8} />
                {seriesNames.map((s, i) => (
                  <Bar key={s} dataKey={s} stackId="a" fill={PALETTE[i % PALETTE.length]} radius={i === seriesNames.length - 1 ? [4, 4, 0, 0] : 0} />
                ))}
              </BarChart>
            );
          })() : (
            <div />
          )}
        </ResponsiveContainer>
      </div>
      {(spec.x_label || spec.y_label) && (
        <div className="text-[10px] text-slate-500 dark:text-slate-400 mt-1 px-1">
          {spec.x_label && <span>x: {spec.x_label}</span>}
          {spec.x_label && spec.y_label && <span> · </span>}
          {spec.y_label && <span>y: {spec.y_label}</span>}
        </div>
      )}
    </motion.div>
  );
}
