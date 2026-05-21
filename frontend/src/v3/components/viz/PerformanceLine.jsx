import React from "react";

/**
 * Line + benchmark dashed line — spec §2.4 performance variant.
 */
export default function PerformanceLine({
  points = [2, 28, 8, 22, 14, 26, 20, 16, 26, 18, 32, 8],
  benchmark = [2, 32, 8, 30, 14, 32, 20, 30, 26, 32, 32, 28],
  color = "var(--v3-gold)",
  size = 36,
}) {
  return (
    <svg width={size} height={size} viewBox="0 0 36 36" aria-hidden role="img">
      <polyline
        points={chunkPoints(points)}
        fill="none"
        stroke={color}
        strokeWidth={2}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <polyline
        points={chunkPoints(benchmark)}
        fill="none"
        stroke="var(--v3-ink-3)"
        strokeWidth={1.5}
        strokeDasharray="2,2"
      />
    </svg>
  );
}

function chunkPoints(arr) {
  let out = [];
  for (let i = 0; i < arr.length; i += 2) out.push(`${arr[i]},${arr[i + 1]}`);
  return out.join(" ");
}
