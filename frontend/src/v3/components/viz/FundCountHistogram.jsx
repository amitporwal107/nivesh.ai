import React from "react";

/**
 * 13-bar histogram with ideal band (5–7) and YOU marker — spec §2.3 hero viz.
 * Defaults match the home screen design. Sized by `height` prop.
 */
export default function FundCountHistogram({
  count = 11,
  idealMin = 5,
  idealMax = 7,
  totalBars = 13,
  width = 320,
  height = 56,
  showYouLabel = false,
  showIdealLabel = false,
}) {
  // Compute bar geometry — auto-distribute across width with consistent gap.
  const barW = 14;
  const gap = (width - barW * totalBars) / (totalBars + 1);
  const startX = gap;

  // Heights ramp from short to tall per spec
  const heights = [24, 30, 34, 38, 44, 48, 52, 54, 56, 56, 56, 56, 56];
  // Color buckets: under-ideal grey, ideal moss, slight-over gold, way-over saffron→crimson
  const colorAt = (i) => {
    const n = i + 1;
    if (n < idealMin) return "#3d3832";
    if (n <= idealMax) return "var(--v3-moss)";
    if (n <= idealMax + 2) return "var(--v3-gold)";
    if (n <= idealMax + 4) return "var(--v3-saffron)";
    return "var(--v3-crimson)";
  };

  const idealLeft = startX + (idealMin - 1) * (barW + gap) - gap / 2;
  const idealRight = startX + (idealMax - 1) * (barW + gap) + barW + gap / 2;
  const youX = startX + (count - 1) * (barW + gap) + barW / 2;

  return (
    <svg
      width="100%"
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      preserveAspectRatio="none"
      aria-label={`You hold ${count} funds; ideal range is ${idealMin}-${idealMax}.`}
      role="img"
    >
      {/* Ideal band */}
      <rect x={idealLeft} y={0} width={idealRight - idealLeft} height={height} fill="var(--v3-moss-band)" />
      <line x1={idealLeft} y1={0} x2={idealLeft} y2={height} stroke="var(--v3-moss)" strokeDasharray="2,3" opacity={0.4} />
      <line x1={idealRight} y1={0} x2={idealRight} y2={height} stroke="var(--v3-moss)" strokeDasharray="2,3" opacity={0.4} />
      {/* Bars */}
      {heights.slice(0, totalBars).map((h, i) => {
        const scaled = (h / 56) * (height - 2);
        return (
          <rect
            key={i}
            x={startX + i * (barW + gap)}
            y={height - scaled}
            width={barW}
            height={scaled}
            rx={2}
            fill={colorAt(i)}
          />
        );
      })}
      {/* YOU marker */}
      <line x1={youX} y1={0} x2={youX} y2={height} stroke="var(--v3-saffron)" strokeWidth={1.5} />
      <circle cx={youX} cy={2} r={3} fill="var(--v3-saffron)" />
      {showYouLabel && (
        <text x={youX + 6} y={12} fill="var(--v3-saffron)" fontFamily="var(--v3-font-mono)" fontSize={9} letterSpacing="0.1em">
          YOU · {count}
        </text>
      )}
      {showIdealLabel && (
        <text
          x={(idealLeft + idealRight) / 2}
          y={height - 4}
          textAnchor="middle"
          fill="var(--v3-moss)"
          fontFamily="var(--v3-font-mono)"
          fontSize={9}
          letterSpacing="0.12em"
        >
          IDEAL
        </text>
      )}
    </svg>
  );
}
