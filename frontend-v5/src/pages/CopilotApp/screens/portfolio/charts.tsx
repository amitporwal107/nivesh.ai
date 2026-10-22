/**
 * Portfolio analysis — the three drawn pieces: a share bar, the portfolio
 * value line and the gain / loss scatter. Inline SVG and plain elements, no
 * chart library. Every value a chart shows on hover is also printed in a table
 * or list beside it.
 */
import { useState, type PointerEvent } from "react";
import { TONE_COLOR, fmtINR, fmtPct, type Tone } from "../../components/ui";
import { useCopilotShell } from "../../lib/shell-context";
import { axisRupees, type ScatterPoint, type ValueSeries } from "./performance-data";

// ── share bar ────────────────────────────────────────────────────────────

/** A thin bar filled to `pct` of `max`, with an optional tick at `markPct` (a cap or a target). */
export function ShareBar({ pct, max = 100, tone = "indigo", markPct, dim }: { pct: number | null; max?: number; tone?: Tone; markPct?: number | null; dim?: boolean }) {
  const width = pct != null && max > 0 ? Math.min(100, Math.max(0, (pct / max) * 100)) : 0;
  const mark = markPct != null && max > 0 ? Math.min(100, Math.max(0, (markPct / max) * 100)) : null;
  return (
    <span aria-hidden="true" style={{ position: "relative", display: "block", height: 6, borderRadius: 3, background: "var(--bg-3)" }}>
      <span style={{ display: "block", height: "100%", width: `${width}%`, borderRadius: 3, background: TONE_COLOR[tone], opacity: dim ? 0.3 : 1 }} />
      {mark != null && <span style={{ position: "absolute", top: -3, bottom: -3, left: `${mark}%`, width: 2, borderRadius: 1, background: "var(--cp-ink-3)" }} />}
    </span>
  );
}

// ── portfolio value over time ────────────────────────────────────────────

/**
 * One line with a light wash under it. Geometry follows the old page's chart:
 * the scale runs from 4% under the lowest value to 4% over the highest, with
 * four guide lines.
 */
export function ValueChart({ series }: { series: ValueSeries }) {
  const { mobile } = useCopilotShell();
  const [active, setActive] = useState<number | null>(null);
  const { points } = series;
  const W = mobile ? 360 : 720;
  const H = mobile ? 190 : 210;
  const pad = { t: 14, r: 14, b: 28, l: mobile ? 50 : 62 };
  const iW = W - pad.l - pad.r;
  const iH = H - pad.t - pad.b;

  const values = points.map((p) => p.valueRs);
  const minV = Math.min(...values) * 0.96;
  const range = Math.max(...values) * 1.04 - minV || 1;
  const x = (i: number) => pad.l + (i / Math.max(points.length - 1, 1)) * iW;
  const y = (v: number) => pad.t + iH - ((v - minV) / range) * iH;

  const line = points.map((p, i) => `${i === 0 ? "M" : "L"} ${x(i).toFixed(1)} ${y(p.valueRs).toFixed(1)}`).join(" ");
  const area = `${line} L ${x(points.length - 1).toFixed(1)} ${pad.t + iH} L ${x(0).toFixed(1)} ${pad.t + iH} Z`;
  const color = TONE_COLOR[series.changePct != null && series.changePct < 0 ? "danger" : "mint"];

  // Month labels: the first, the last and evenly spaced ones between.
  const labelCount = Math.min(points.length, mobile ? 4 : 7);
  const labelled = new Set(Array.from({ length: labelCount }, (_, k) => Math.round((k * (points.length - 1)) / Math.max(labelCount - 1, 1))));
  const ticks = [0, 0.33, 0.67, 1].map((f) => minV + f * range);

  const onMove = (e: PointerEvent<SVGSVGElement>) => {
    const box = e.currentTarget.getBoundingClientRect();
    if (box.width <= 0) return;
    const at = ((e.clientX - box.left) / box.width) * W;
    setActive(Math.min(points.length - 1, Math.max(0, Math.round(((at - pad.l) / iW) * (points.length - 1)))));
  };
  const shown = active != null ? points[active] : null;
  const axisText = { fill: "var(--cp-ink-3)", fontFamily: "var(--mono)", fontSize: 10 } as const;

  return (
    <div className="flex flex-col" style={{ gap: 6 }}>
      <span data-testid="analysis-value-readout" className="cp-mono-note" style={{ minHeight: 14, color: "var(--cp-ink-3)" }}>
        {shown ? `${shown.label} · ${fmtINR(shown.valueRs, { compact: true })}` : "Point at the line to read a month"}
      </span>
      <svg
        viewBox={`0 0 ${W} ${H}`}
        role="img"
        aria-label={`Portfolio value from ${points[0].label} to ${points[points.length - 1].label}`}
        style={{ display: "block", width: "100%", height: "auto", touchAction: "pan-y" }}
        onPointerMove={onMove}
        onPointerDown={onMove}
        onPointerLeave={() => setActive(null)}
      >
        {ticks.map((v) => (
          <g key={v}>
            <line x1={pad.l} y1={y(v)} x2={W - pad.r} y2={y(v)} style={{ stroke: "var(--line-2)" }} strokeWidth={1} />
            <text x={pad.l - 8} y={y(v) + 3} textAnchor="end" style={axisText}>{axisRupees(v)}</text>
          </g>
        ))}
        <path d={area} style={{ fill: color }} opacity={0.1} />
        <path d={line} fill="none" style={{ stroke: color }} strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />
        {points.map((p, i) => labelled.has(i) && (
          <text key={p.label} x={x(i)} y={H - 8} textAnchor={i === 0 ? "start" : i === points.length - 1 ? "end" : "middle"} style={axisText}>{p.label}</text>
        ))}
        {active != null && (
          <line x1={x(active)} y1={pad.t} x2={x(active)} y2={pad.t + iH} style={{ stroke: "var(--line-3)" }} strokeWidth={1} />
        )}
        <circle
          cx={x(active ?? points.length - 1)}
          cy={y(points[active ?? points.length - 1].valueRs)}
          r={4}
          style={{ fill: color, stroke: "var(--bg-1)" }}
          strokeWidth={2}
        />
      </svg>
    </div>
  );
}

// ── gain / loss scatter ──────────────────────────────────────────────────

/** Round tick values covering [min, max], about `count` of them. */
function niceTicks(min: number, max: number, count: number): number[] {
  const span = max - min || 1;
  const rough = span / Math.max(1, count - 1);
  const mag = 10 ** Math.floor(Math.log10(rough));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= rough) ?? 10 * mag;
  const out: number[] = [];
  for (let v = Math.floor(min / step) * step; v <= max + step * 0.999; v += step) out.push(Number(v.toFixed(6)));
  return out;
}

/**
 * X = invested, Y = return %, dot size = current value, as on the old page
 * (dot area runs from 30 to 700 square pixels across the value range). Each
 * dot is a button; hovering or focusing one prints its figures under the plot.
 */
export function ScatterPlot({ points, onPick }: { points: ScatterPoint[]; onPick: (name: string) => void }) {
  const { mobile } = useCopilotShell();
  const [active, setActive] = useState<number | null>(null);
  if (points.length === 0) return null;
  // Largest first, so a small dot is never hidden under a large one.
  const dots = [...points].sort((a, b) => b.valueRs - a.valueRs);

  const xTicks = niceTicks(0, Math.max(...dots.map((d) => d.investedRs)), mobile ? 3 : 5);
  const yTicks = niceTicks(Math.min(0, ...dots.map((d) => d.returnPct)), Math.max(0, ...dots.map((d) => d.returnPct)), 6);
  const xMax = xTicks[xTicks.length - 1] || 1;
  const yMin = yTicks[0];
  const ySpan = yTicks[yTicks.length - 1] - yMin || 1;
  const zMin = Math.min(...dots.map((d) => d.valueRs));
  const zSpan = Math.max(...dots.map((d) => d.valueRs)) - zMin;
  const left = (v: number) => (v / xMax) * 100;
  const top = (v: number) => 100 - ((v - yMin) / ySpan) * 100;
  const radius = (v: number) => Math.max(4, Math.sqrt((30 + (zSpan > 0 ? (v - zMin) / zSpan : 0.5) * 670) / Math.PI));

  const shown = active != null ? dots[active] : null;
  const axis = { position: "absolute", fontFamily: "var(--mono)", fontSize: 10, color: "var(--cp-ink-3)", whiteSpace: "nowrap" } as const;

  return (
    <div className="flex flex-col" style={{ gap: 8 }}>
      <div style={{ position: "relative", height: mobile ? 260 : 320, margin: "6px 8px 24px 44px" }}>
        {yTicks.map((v) => (
          <div key={`y${v}`} aria-hidden="true" style={{ position: "absolute", left: 0, right: 0, top: `${top(v)}%`, height: 1, background: v === 0 ? "var(--line-3)" : "var(--line-2)" }}>
            <span style={{ ...axis, right: "100%", top: -6, paddingRight: 8 }}>{fmtPct(v, { digits: 0 })}</span>
          </div>
        ))}
        {xTicks.map((v, i) => (
          <span key={`x${v}`} aria-hidden="true" style={{ ...axis, top: "100%", paddingTop: 8, left: `${left(v)}%`, transform: i === 0 ? undefined : i === xTicks.length - 1 ? "translateX(-100%)" : "translateX(-50%)" }}>
            {v === 0 ? "₹0" : `₹${axisRupees(v)}`}
          </span>
        ))}
        {dots.map((d, i) => {
          const r = radius(d.valueRs);
          const hit = Math.max(24, r * 2);
          return (
            <button
              key={`${d.name}-${i}`}
              type="button"
              data-testid="analysis-scatter-dot"
              title={d.name}
              aria-label={`${d.name}: invested ${fmtINR(d.investedRs, { compact: true })}, return ${fmtPct(d.returnPct, { signed: true })}, current value ${fmtINR(d.valueRs, { compact: true })}`}
              onClick={() => onPick(d.name)}
              onPointerEnter={() => setActive(i)}
              onPointerLeave={() => setActive(null)}
              onFocus={() => setActive(i)}
              onBlur={() => setActive(null)}
              style={{ position: "absolute", left: `${left(d.investedRs)}%`, top: `${top(d.returnPct)}%`, width: hit, height: hit, transform: "translate(-50%,-50%)", display: "grid", placeItems: "center", padding: 0, background: "none", border: 0, cursor: "pointer", zIndex: active === i ? 1 : undefined }}
            >
              <span style={{ width: r * 2, height: r * 2, borderRadius: "50%", background: TONE_COLOR[d.returnPct >= 0 ? "mint" : "danger"], opacity: active == null || active === i ? 0.85 : 0.35, boxShadow: "0 0 0 2px var(--bg-1)" }} />
            </button>
          );
        })}
      </div>
      <span data-testid="analysis-scatter-readout" style={{ minHeight: 18, fontSize: 12, lineHeight: 1.5, color: "var(--cp-ink-2)" }}>
        {shown
          ? `${shown.name} · invested ${fmtINR(shown.investedRs, { compact: true })} · return ${fmtPct(shown.returnPct, { signed: true })} · current ${fmtINR(shown.valueRs, { compact: true })}`
          : "Point at a dot to read it, or select it to open the holding."}
      </span>
    </div>
  );
}
