import { PieChart, Pie, Cell, ResponsiveContainer, Tooltip } from "recharts";
import type { AllocationSlice } from "@/types/portfolio";

const COLORS: Record<AllocationSlice["assetClass"], string> = {
  equity:        "rgb(var(--accent))",
  debt:          "#A6A38E",
  hybrid:        "#8FAE9D",
  gold:          "rgb(var(--warm))",
  international: "#7A8298",
  cash:          "#CFCFC2",
};

interface AllocationDonutProps {
  slices: AllocationSlice[];
  size?: number;
}

export function AllocationDonut({ slices, size = 220 }: AllocationDonutProps) {
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
            <Cell key={s.assetClass} fill={COLORS[s.assetClass] ?? "#A6A38E"} />
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
          formatter={(v: number) => [`${v}%`, "Allocation"]}
        />
      </PieChart>
    </ResponsiveContainer>
  );
}

export const ALLOCATION_COLORS = COLORS;
