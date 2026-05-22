import React from "react";

/**
 * Tax pyramid — the outer triangle is the total taxable gains envelope; the
 * filled inner triangle scales with the harvestable / unrealised LTCG share.
 *
 * Props:
 *   filled  — number in [0, 1]. 0 = empty pyramid, 1 = fully filled.
 *             Pass `harvestable / unrealizedLtcg` (clamped) to drive it.
 *   color   — accent color (default indigo).
 *   warn    — when true, switch fill to crimson (e.g. STCG > LTCG).
 *   size    — px square (default 36, matches CompactCard icon scale).
 */
export default function TaxPyramid({
  filled = null,
  color = "var(--v3-indigo)",
  warn = false,
  size = 36,
}) {
  const accent = warn ? "var(--v3-crimson)" : color;
  // Map filled (0..1) → apex Y of inner triangle (8 = full, 22 = empty).
  // Default to ~0.5 if no data so the icon still has a recognisable shape.
  const f = filled == null ? 0.5 : Math.max(0, Math.min(1, filled));
  const apexY = 22 - 14 * f;
  const halfBase = 7 * f;
  return (
    <svg width={size} height={size} viewBox="0 0 36 36" aria-hidden role="img">
      <path
        d="M6 30 L18 6 L30 30 Z"
        fill="none"
        stroke={accent}
        strokeWidth={2}
        strokeLinejoin="round"
      />
      {f > 0 && (
        <path
          d={`M${18 - halfBase} 22 L18 ${apexY} L${18 + halfBase} 22 Z`}
          fill={accent}
          opacity={0.35}
        />
      )}
    </svg>
  );
}
