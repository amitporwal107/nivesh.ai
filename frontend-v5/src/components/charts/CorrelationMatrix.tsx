import { cn } from "@/lib/utils";
import type { CorrelationMatrix as CM } from "@/types/diversification";

interface Props {
  matrix: CM;
  size?: number;       // cell size in px
  className?: string;
}

/**
 * 8x8 correlation heatmap. Red for ρ ≥ 0.7 (redundant), warm for 0.5–0.7,
 * cool/neutral for < 0.5 (diversifying).
 */
export function CorrelationMatrix({ matrix, size = 44, className }: Props) {
  const { tickers, values, hotPairs } = matrix;
  const hot = new Set(hotPairs.map((p) => [p.a, p.b].sort().join("|")));
  const off = 70;
  const W = off + size * tickers.length + 10;
  const H = off + size * tickers.length + 10;

  return (
    <svg viewBox={`0 0 ${W} ${H}`} className={cn("max-w-full h-auto", className)} role="img" aria-label="Correlation matrix">
      {tickers.map((t, i) => (
        <text key={`col-${t}`} x={off + i * size + size / 2} y={off - 8} textAnchor="middle" fontFamily="var(--font-mono)" fontSize={10} fill="rgb(var(--ink-3))" letterSpacing=".05em">{t}</text>
      ))}
      {tickers.map((t, i) => (
        <text key={`row-${t}`} x={off - 8} y={off + i * size + size / 2 + 3} textAnchor="end" fontFamily="var(--font-mono)" fontSize={10} fill="rgb(var(--ink-3))" letterSpacing=".05em">{t}</text>
      ))}
      {values.map((row, r) =>
        row.map((v, c) => {
          const diag = r === c;
          const intensity = Math.abs(v);
          const key = [tickers[r], tickers[c]].sort().join("|");
          const isHot = hot.has(key) && !diag;
          let fill: string;
          if (diag) fill = "rgb(var(--surface-3))";
          else if (isHot) fill = `rgba(163, 85, 58, ${0.18 + intensity * 0.5})`;
          else if (v >= 0.5) fill = `rgba(181, 132, 31, ${0.12 + intensity * 0.32})`;
          else fill = `rgba(67, 56, 202, ${0.06 + (1 - intensity) * 0.16})`;
          const stroke = isHot ? "rgb(var(--neg))" : "transparent";
          return (
            <g key={`${r}-${c}`}>
              <rect x={off + c * size} y={off + r * size} width={size - 2} height={size - 2} fill={fill} stroke={stroke} strokeWidth={1.5} rx={3} />
              <text x={off + c * size + size / 2 - 1} y={off + r * size + size / 2 + 4} textAnchor="middle" fontFamily="var(--font-mono)" fontSize={10}
                fill={diag ? "rgb(var(--ink-3))" : isHot ? "rgb(var(--ink))" : "rgb(var(--ink-2))"}
                fontWeight={isHot ? 600 : 400}>
                {v.toFixed(2).replace("0.", ".")}
              </text>
            </g>
          );
        })
      )}
    </svg>
  );
}
