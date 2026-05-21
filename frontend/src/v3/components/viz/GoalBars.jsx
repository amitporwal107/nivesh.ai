import React from "react";

/**
 * 3-bar bar chart (progress / current / target) — spec §2.4 goal variant.
 */
export default function GoalBars({
  bars = [{ value: 14, color: "var(--v3-line-strong)" }, { value: 20, color: "var(--v3-saffron)" }, { value: 26, color: "var(--v3-saffron)", opacity: 0.4 }],
  size = 36,
}) {
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
