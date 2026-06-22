import { PieChart, Pie, Cell, ResponsiveContainer, Tooltip } from "recharts";

export interface DonutSlice {
  label: string;
  pct: number;     // 0..100
  color: string;   // any CSS colour
}

interface BreakdownDonutProps {
  slices: DonutSlice[];
  size?: number;
}

/** Generic donut keyed by an explicit per-slice colour — unlike AllocationDonut,
 *  which is hard-bound to the fixed AssetClass palette. Used for the instrument
 *  "split across types" view (Equity / Mutual funds / Gold & SGB / …). */
export function BreakdownDonut({ slices, size = 220 }: BreakdownDonutProps) {
  return (
    <ResponsiveContainer width={size} height={size}>
      <PieChart>
        <Pie
          data={slices}
          dataKey="pct"
          nameKey="label"
          innerRadius={size * 0.34}
          outerRadius={size * 0.46}
          startAngle={90}
          endAngle={-270}
          stroke="rgb(var(--surface-1))"
          strokeWidth={2}
          isAnimationActive={false}
        >
          {slices.map((s) => (
            <Cell key={s.label} fill={s.color} />
          ))}
        </Pie>
        <Tooltip
          contentStyle={{
            background: "rgb(var(--surface-1))",
            border: "1px solid rgb(var(--line) / 0.16)",
            borderRadius: 10,
            color: "rgb(var(--ink))",
            fontSize: 12,
          }}
          formatter={(v: number, label: string) => [`${v.toFixed(1)}%`, label]}
        />
      </PieChart>
    </ResponsiveContainer>
  );
}
