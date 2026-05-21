import React from "react";

/**
 * Donut with center percentage. Spec §2.4 risk variant.
 * `value` in 0–100, `color` is the ring color.
 */
export default function OverlapDonut({ value = 71, color = "var(--v3-crimson)", size = 36, label }) {
  const r = 14;
  const c = 2 * Math.PI * r;
  const offset = c * (1 - Math.min(100, Math.max(0, value)) / 100);
  return (
    <svg width={size} height={size} viewBox="0 0 36 36" aria-label={label || `${value}%`} role="img">
      <circle cx={18} cy={18} r={r} fill="none" stroke="var(--v3-line)" strokeWidth={4} />
      <circle
        cx={18}
        cy={18}
        r={r}
        fill="none"
        stroke={color}
        strokeWidth={4}
        strokeDasharray={c}
        strokeDashoffset={offset}
        strokeLinecap="round"
        transform="rotate(-90 18 18)"
      />
      <text
        x={18}
        y={21}
        textAnchor="middle"
        fill="var(--v3-ink-1)"
        fontFamily="var(--v3-font-mono)"
        fontSize={9}
        fontWeight={600}
      >
        {Math.round(value)}%
      </text>
    </svg>
  );
}
