/**
 * Twelve months of daily closes with the 200-session average, and the day's
 * traded volume in its own panel underneath (two panels, one scale each — the
 * two measures never share an axis). Inline SVG, no chart library.
 *
 * Pointing at the chart, or focusing it and pressing ← / →, reads one session
 * out in the line above it; the headline figures are printed as tiles by the
 * caller, so nothing is available on hover only.
 */
import { useState, type KeyboardEvent, type PointerEvent } from "react";
import { useCopilotShell } from "../../lib/shell-context";
import { dayLabel, fmtPrice } from "../markets/format";
import type { PricePoint } from "./data";

const PRICE = "var(--cp-indigo)";
const AVERAGE = "var(--amber)";

/** Shares traded, in Indian units: "1.25 Cr", "4.80 L", "12,400". */
export function fmtShares(n: number | null | undefined): string {
  if (n == null || !Number.isFinite(n)) return "—";
  if (n >= 1_00_00_000) return `${(n / 1_00_00_000).toFixed(2)} Cr`;
  if (n >= 1_00_000) return `${(n / 1_00_000).toFixed(2)} L`;
  return new Intl.NumberFormat("en-IN", { maximumFractionDigits: 0 }).format(n);
}

/** Round tick values covering [min, max], about `count` of them. */
function niceTicks(min: number, max: number, count: number): number[] {
  const span = max - min || Math.abs(max) || 1;
  const rough = span / Math.max(1, count - 1);
  const mag = 10 ** Math.floor(Math.log10(rough));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= rough) ?? 10 * mag;
  const out: number[] = [];
  for (let v = Math.ceil(min / step) * step; v <= max + step * 1e-6; v += step) out.push(Number(v.toFixed(6)));
  return out;
}

function axisRupees(v: number): string {
  return `₹${new Intl.NumberFormat("en-IN", { maximumFractionDigits: v < 100 ? 2 : 0 }).format(v)}`;
}

function path(points: Array<[number, number]>): string {
  return points.map(([px, py], i) => `${i === 0 ? "M" : "L"} ${px.toFixed(1)} ${py.toFixed(1)}`).join(" ");
}

function LegendKey({ color, dashed, children }: { color: string; dashed?: boolean; children: string }) {
  return (
    <span className="inline-flex items-center" style={{ gap: 6, fontSize: 12, color: "var(--cp-ink-2)" }}>
      <svg width={18} height={6} aria-hidden>
        <line x1={0} y1={3} x2={18} y2={3} style={{ stroke: color }} strokeWidth={2} strokeDasharray={dashed ? "5 3" : undefined} />
      </svg>
      {children}
    </span>
  );
}

export function PriceChart({ points, name }: { points: PricePoint[]; name: string }) {
  const { mobile } = useCopilotShell();
  const [active, setActive] = useState<number | null>(null);
  const n = points.length;

  const W = mobile ? 360 : 720;
  const priceH = mobile ? 170 : 200;
  const volH = 48;
  const gap = 14;
  const pad = { t: 10, r: 12, b: 22, l: mobile ? 48 : 58 };
  const iW = W - pad.l - pad.r;
  const H = pad.t + priceH + gap + volH + pad.b;
  const volTop = pad.t + priceH + gap;

  const averages = points.flatMap((p) => (p.avg200 != null ? [p.avg200] : []));
  const lo = Math.min(...points.map((p) => p.close), ...averages);
  const hi = Math.max(...points.map((p) => p.close), ...averages);
  const room = (hi - lo || hi || 1) * 0.06;
  const min = lo - room;
  const range = hi + room - min;
  const maxVol = Math.max(...points.map((p) => p.volume), 1);

  const x = (i: number) => pad.l + (n > 1 ? (i / (n - 1)) * iW : iW / 2);
  const y = (v: number) => pad.t + priceH - ((v - min) / range) * priceH;
  const barW = Math.max(1, (iW / Math.max(n, 1)) * 0.7);

  const closeLine = path(points.map((p, i) => [x(i), y(p.close)]));
  const avgLine = path(points.flatMap((p, i): Array<[number, number]> => (p.avg200 != null ? [[x(i), y(p.avg200)]] : [])));
  const ticks = niceTicks(lo, hi, 4);
  const labelCount = Math.min(n, mobile ? 4 : 6);
  const labelled = Array.from(new Set(Array.from({ length: labelCount }, (_, k) => Math.round((k * (n - 1)) / Math.max(labelCount - 1, 1)))));

  const onMove = (e: PointerEvent<SVGSVGElement>) => {
    const box = e.currentTarget.getBoundingClientRect();
    if (box.width <= 0 || n === 0) return;
    const at = ((e.clientX - box.left) / box.width) * W;
    setActive(Math.min(n - 1, Math.max(0, Math.round(((at - pad.l) / iW) * (n - 1)))));
  };
  const onKey = (e: KeyboardEvent<SVGSVGElement>) => {
    if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
    e.preventDefault();
    const from = active ?? n - 1;
    setActive(Math.min(n - 1, Math.max(0, from + (e.key === "ArrowLeft" ? -1 : 1))));
  };

  const at = active ?? n - 1;
  const shown = points[at];
  const axisText = { fill: "var(--cp-ink-3)", fontFamily: "var(--mono)", fontSize: 10 } as const;
  const hasAverage = averages.length > 0;

  return (
    <div className="flex flex-col" style={{ gap: 8 }} data-testid="research-price-chart">
      <div className="flex flex-wrap items-center justify-between" style={{ gap: "6px 16px" }}>
        <span className="flex flex-wrap" style={{ gap: "4px 16px" }}>
          <LegendKey color={PRICE}>Close</LegendKey>
          {hasAverage && <LegendKey color={AVERAGE} dashed>200-day average</LegendKey>}
        </span>
        <span data-testid="research-price-readout" aria-live="polite" className="cp-num" style={{ fontSize: 12, color: "var(--cp-ink-2)" }}>
          {dayLabel(shown.day, { year: true })} · Close {fmtPrice(shown.close)}
          {shown.avg200 != null ? ` · 200-day average ${fmtPrice(shown.avg200)}` : ""} · Volume {fmtShares(shown.volume)}
        </span>
      </div>
      <svg
        viewBox={`0 0 ${W} ${H}`}
        role="img"
        tabIndex={0}
        aria-label={`${name}: daily closing price and traded volume from ${dayLabel(points[0].day, { year: true })} to ${dayLabel(points[n - 1].day, { year: true })}. Use the left and right arrow keys to read a session.`}
        style={{ display: "block", width: "100%", height: "auto", touchAction: "pan-y" }}
        onPointerMove={onMove}
        onPointerDown={onMove}
        onPointerLeave={() => setActive(null)}
        onKeyDown={onKey}
        onBlur={() => setActive(null)}
      >
        {/* price panel */}
        {ticks.map((v) => (
          <g key={v}>
            <line x1={pad.l} y1={y(v)} x2={W - pad.r} y2={y(v)} style={{ stroke: "var(--line-2)" }} strokeWidth={1} />
            <text x={pad.l - 8} y={y(v) + 3} textAnchor="end" style={axisText}>{axisRupees(v)}</text>
          </g>
        ))}
        {hasAverage && <path d={avgLine} fill="none" style={{ stroke: AVERAGE }} strokeWidth={1.5} strokeDasharray="5 3" strokeLinejoin="round" />}
        <path d={closeLine} fill="none" style={{ stroke: PRICE }} strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />

        {/* volume panel */}
        <line x1={pad.l} y1={volTop + volH} x2={W - pad.r} y2={volTop + volH} style={{ stroke: "var(--line-2)" }} strokeWidth={1} />
        <text x={pad.l - 8} y={volTop + 8} textAnchor="end" style={axisText}>{fmtShares(maxVol)}</text>
        <text x={pad.l - 8} y={volTop + volH} textAnchor="end" style={axisText}>Volume</text>
        {points.map((p, i) => {
          const h = Math.max(p.volume > 0 ? 1 : 0, (p.volume / maxVol) * volH);
          return (
            <rect
              key={p.day}
              x={x(i) - barW / 2}
              y={volTop + volH - h}
              width={barW}
              height={h}
              style={{ fill: i === active ? "var(--cp-ink)" : "var(--cp-ink-3)" }}
              opacity={i === active ? 1 : 0.55}
            />
          );
        })}

        {/* dates */}
        {labelled.map((i) => (
          <text key={i} x={x(i)} y={H - 6} textAnchor={i === 0 ? "start" : i === n - 1 ? "end" : "middle"} style={axisText}>
            {dayLabel(points[i].day, { year: true }).replace(/^\d+\s/, "")}
          </text>
        ))}

        {/* crosshair */}
        {active != null && (
          <line x1={x(active)} y1={pad.t} x2={x(active)} y2={volTop + volH} style={{ stroke: "var(--line-3)" }} strokeWidth={1} />
        )}
        <circle cx={x(at)} cy={y(shown.close)} r={4} style={{ fill: PRICE, stroke: "var(--bg-1)" }} strokeWidth={2} />
      </svg>
    </div>
  );
}
