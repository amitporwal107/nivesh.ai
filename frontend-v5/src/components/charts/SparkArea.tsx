import { AreaChart, Area, ResponsiveContainer, Tooltip, YAxis, XAxis } from "recharts";
import { formatINRCompact, formatDate } from "@/lib/formatters";
import type { NavPoint } from "@/types/portfolio";

interface SparkAreaProps {
  data: NavPoint[];
  height?: number;
  showAxis?: boolean;
}

/**
 * Single-series area sparkline using Recharts. The token-aware colors come
 * through inline so the chart respects light/dark theme switches.
 */
export function SparkArea({ data, height = 80, showAxis = false }: SparkAreaProps) {
  return (
    <ResponsiveContainer width="100%" height={height}>
      <AreaChart data={data} margin={{ top: 4, right: 4, bottom: 0, left: 0 }}>
        <defs>
          <linearGradient id="sparkArea" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="rgb(var(--accent))" stopOpacity={0.28} />
            <stop offset="100%" stopColor="rgb(var(--accent))" stopOpacity={0} />
          </linearGradient>
        </defs>
        {showAxis && (
          <>
            <XAxis
              dataKey="date"
              tickLine={false}
              axisLine={false}
              tick={{ fill: "rgb(var(--ink-3))", fontFamily: "var(--font-mono)", fontSize: 11 }}
              tickFormatter={(v) => new Date(v).toLocaleDateString("en-IN", { month: "short" })}
              minTickGap={32}
            />
            <YAxis hide />
          </>
        )}
        <Tooltip
          cursor={{ stroke: "rgb(var(--line) / 0.3)" }}
          contentStyle={{
            background: "rgb(var(--surface-1))",
            border: "1px solid rgb(var(--line) / 0.16)",
            borderRadius: 10,
            padding: "8px 12px",
            color: "rgb(var(--ink))",
            boxShadow: "0 12px 24px -8px rgb(15 23 42 / 0.12)",
          }}
          labelFormatter={(v) => formatDate(v as string)}
          formatter={(v) => [formatINRCompact((v as number) / 100), "Value"]}
        />
        <Area
          type="monotone"
          dataKey="value"
          stroke="rgb(var(--accent))"
          strokeWidth={2}
          fill="url(#sparkArea)"
          isAnimationActive={false}
        />
      </AreaChart>
    </ResponsiveContainer>
  );
}
