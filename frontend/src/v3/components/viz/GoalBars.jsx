import React from "react";

/**
 * 3-bar mini chart for goal progress (current / projected / target).
 *
 * Two ways to drive it:
 *   1. `goal` prop  — { current_amount, projected_amount, target_amount } —
 *      preferred path; we derive the three bar heights from the goal numbers.
 *   2. `bars`       — explicit array of { value, color, opacity? } for cases
 *      where the caller already has values they want to plot. Defaults to a
 *      neutral 3-bar pattern so unwired callers still render.
 *
 * The middle bar (projected) is rendered solid; the third (target) muted at
 * 0.4 opacity to suggest "still to go".
 */
export default function GoalBars({ goal = null, bars: barsProp = null, size = 36 }) {
  let bars = barsProp;
  if (!bars && goal) {
    const current   = Number(goal.current_amount_rs ?? goal.current_amount ?? 0);
    const projected = Number(goal.projected_amount_rs ?? goal.projected_amount ?? current);
    const target    = Number(goal.target_amount_rs ?? goal.target_amount ?? Math.max(current, projected, 1));
    bars = [
      { value: Math.max(current, 1),   color: "var(--v3-line-strong)" },
      { value: Math.max(projected, 1), color: "var(--v3-saffron)" },
      { value: Math.max(target, 1),    color: "var(--v3-saffron)", opacity: 0.4 },
    ];
  }
  if (!bars) {
    bars = [
      { value: 14, color: "var(--v3-line-strong)" },
      { value: 20, color: "var(--v3-saffron)" },
      { value: 26, color: "var(--v3-saffron)", opacity: 0.4 },
    ];
  }
  const max = Math.max(...bars.map((b) => b.value));
  return (
    <svg width={size} height={size} viewBox="0 0 36 36" aria-hidden role="img">
      {bars.map((b, i) => {
        const h = (b.value / max) * 28;
        return (
          <rect
            key={i}
            x={4 + i * 10}
            y={34 - h}
            width={6}
            height={h}
            rx={1}
            fill={b.color}
            opacity={b.opacity ?? 1}
          />
        );
      })}
    </svg>
  );
}
