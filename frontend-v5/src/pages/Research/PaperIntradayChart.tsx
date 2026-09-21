/**
 * Intraday session chart for one paper position: 5-minute candles with the PRE-REGISTERED levels drawn on them
 * (entry, stop, target), so the session can be read against the rules that were frozen before it started.
 *
 * The levels are a frozen experiment, not advice. Their measured result travels with them everywhere they are
 * shown (see PaperEvidence and docs/ai_research/tpd3/v5_net_return/): over 402 walk-forward sessions the rules
 * returned -0.19% per trade after costs and FAILED their pre-registered test. The chart exists to show what the
 * experiment did, including when it went wrong — RATNAVEER on 2026-09-18 touched its target intraday and still
 * closed below its entry, which is exactly the behaviour a close-only record hides.
 */
import { useMemo } from "react";
import type { PaperBar, PaperLivePosition } from "@/services/adapters/paperTrades.adapter";
import { price } from "./paperMath";

const W = 560, H = 190, PAD_L = 4, PAD_R = 52, PAD_T = 8, VOL_H = 0;

export default function PaperIntradayChart({ p }: { p: PaperLivePosition }) {
  const bars: PaperBar[] = p.bars ?? [];
  const geom = useMemo(() => {
    if (bars.length < 2) return null;
    const levels = [p.entry, p.stop, p.target].filter((x): x is number => x != null);
    const lo = Math.min(...bars.map((b) => b.l), ...levels);
    const hi = Math.max(...bars.map((b) => b.h), ...levels);
    const span = hi - lo || 1;
    const plotH = H - PAD_T - VOL_H - 16;
    const y = (v: number) => PAD_T + plotH - ((v - lo) / span) * plotH;
    const plotW = W - PAD_L - PAD_R;
    const x = (i: number) => PAD_L + (i / Math.max(1, bars.length - 1)) * plotW;
    const bw = Math.max(1.2, (plotW / bars.length) * 0.62);
    return { x, y, bw, lo, hi, plotH };
  }, [bars, p.entry, p.stop, p.target]);

  if (!geom) {
    return <div className="pt-note" data-testid={`pt-chart-empty-${p.symbol}`}>No intraday bars yet for this session.</div>;
  }
  const { x, y, bw } = geom;
  const lines: Array<[number | null, string, string]> = [
    [p.entry, "var(--c-ink-3)", "entry"],
    [p.target, "var(--mint)", "target"],
    [p.stop, "var(--danger-hex)", "stop"],
  ];
  return (
    <svg className="pt-chart" viewBox={`0 0 ${W} ${H}`} role="img" data-testid={`pt-chart-${p.symbol}`}
         aria-label={`${p.symbol} five-minute session chart with the pre-registered entry, stop and target levels`}>
      {lines.map(([v, colour, label]) =>
        v == null ? null : (
          <g key={label}>
            <line x1={PAD_L} x2={W - PAD_R} y1={y(v)} y2={y(v)} stroke={colour} strokeWidth="1"
                  strokeDasharray={label === "entry" ? "" : "4 3"} opacity={label === "entry" ? 0.9 : 0.75} />
            <text x={W - PAD_R + 5} y={y(v) + 3.5} fill={colour} fontSize="9" fontFamily="var(--mono)">
              {label} {price(v)}
            </text>
          </g>
        ))}
      {bars.map((b, i) => {
        const up = b.c >= b.o;
        const colour = up ? "var(--mint-2)" : "var(--danger-hex)";
        const yO = y(b.o), yC = y(b.c);
        return (
          <g key={b.t}>
            <line x1={x(i)} x2={x(i)} y1={y(b.h)} y2={y(b.l)} stroke={colour} strokeWidth="0.8" opacity="0.85" />
            <rect x={x(i) - bw / 2} y={Math.min(yO, yC)} width={bw} height={Math.max(1, Math.abs(yC - yO))}
                  fill={colour} opacity="0.9" />
          </g>
        );
      })}
      <text x={PAD_L} y={H - 3} fontSize="9" fill="var(--c-ink-4)" fontFamily="var(--mono)">{bars[0].t.slice(11, 16)}</text>
      <text x={W - PAD_R} y={H - 3} fontSize="9" fill="var(--c-ink-4)" fontFamily="var(--mono)" textAnchor="end">
        {bars[bars.length - 1].t.slice(11, 16)}
      </text>
    </svg>
  );
}
