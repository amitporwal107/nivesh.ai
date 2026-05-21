import React from "react";

/**
 * Solid score gauge (0–100) — spec §2.4 health variant.
 * Color picks moss → gold → crimson by score.
 */
export default function HealthGauge({ score = 72, size = 36 }) {
  const color = score >= 75 ? "var(--v3-moss)" : score >= 50 ? "var(--v3-gold)" : "var(--v3-crimson)";
  const r = 14;
  const c = Math.PI * r; // half circle
  const offset = c * (1 - Math.min(100, Math.max(0, score)) / 100);
  return (
    <svg width={size} height={size} viewBox="0 0 36 36" aria-label={`Score ${score}`} role="img">
      <path d="M4 22 A14 14 0 0 1 32 22" fill="none" stroke="var(--v3-line)" strokeWidth={4} strokeLinecap="round" />
      <path
        d="M4 22 A14 14 0 0 1 32 22"
        fill="none"
        stroke={color}
        strokeWidth={4}
        strokeLinecap="round"
        strokeDasharray={c}
        strokeDashoffset={offset}
      />
      <text x={18} y={26} textAnchor="middle" fill="var(--v3-ink-1)" fontFamily="var(--v3-font-mono)" fontSize={10} fontWeight={600}>
        {score}
      </text>
    </svg>
  );
}
