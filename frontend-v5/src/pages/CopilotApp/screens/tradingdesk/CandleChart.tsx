/**
 * Daily candlesticks with traded volume in its own panel underneath, and
 * optional overlays: 20- and 50-day EMA, a 20-day volume-weighted average
 * price, and the scanner's levels (target, entry, stop) as dashed lines.
 * Inline SVG, no chart library (house style: screens/research/PriceChart.tsx).
 *
 * The data comes from the caller (ChartTab: GET /api/research/chart-live/
 * {symbol}/ohlcv, end of day). Pointing at the chart, or focusing it and
 * pressing ← / →, prints one session's open, high, low, close and volume in
 * the line above it; nothing is available on hover only.
 */
import { useState, type KeyboardEvent, type PointerEvent } from "react";
import { useCopilotShell } from "../../lib/shell-context";
import { fmtShares } from "../research/PriceChart";
import { dayLabel } from "../markets/format";
import { fmtDay, fmtPrice } from "../trading/parts";
import type { DailyBar, Series } from "./indicators";

const UP = "var(--mint)";
const DOWN = "var(--cp-danger)";
const EMA20 = "var(--cp-indigo)";
const EMA50 = "var(--amber)";
const VWAP = "var(--rose)";

export interface ChartLevels {
  target: number | null;
  entry: number | null;
  stop: number | null;
}

export interface ChartOverlays {
  /** Aligned to `bars`. */
  ema20?: Series;
  ema50?: Series;
  vwap20?: Series;
  levels?: ChartLevels | null;
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

/** A line through the non-null points of a series (a gap where the series has none). */
function seriesPath(series: Series, x: (i: number) => number, y: (v: number) => number): string {
  let d = "";
  let pen = false;
  series.forEach((v, i) => {
    if (v == null || !Number.isFinite(v)) { pen = false; return; }
    d += `${pen ? "L" : "M"} ${x(i).toFixed(1)} ${y(v).toFixed(1)} `;
    pen = true;
  });
  return d.trim();
}

export function LegendKey({ color, dashed, box, children }: { color: string; dashed?: boolean; box?: boolean; children: string }) {
  return (
    <span className="inline-flex items-center" style={{ gap: 6, fontSize: 12, color: "var(--cp-ink-2)" }}>
      <svg width={box ? 10 : 18} height={box ? 10 : 6} aria-hidden>
        {box
          ? <rect x={1} y={1} width={8} height={8} rx={1.5} style={{ fill: color }} />
          : <line x1={0} y1={3} x2={18} y2={3} style={{ stroke: color }} strokeWidth={2} strokeDasharray={dashed ? "5 3" : undefined} />}
      </svg>
      {children}
    </span>
  );
}

export function CandleChart({ bars, name, overlays }: { bars: DailyBar[]; name: string; overlays: ChartOverlays }) {
  const { mobile } = useCopilotShell();
  const [active, setActive] = useState<number | null>(null);
  const n = bars.length;

  const W = mobile ? 360 : 720;
  const priceH = mobile ? 200 : 250;
  const volH = 52;
  const gap = 14;
  const pad = { t: 12, r: mobile ? 62 : 74, b: 22, l: mobile ? 46 : 56 };
  const iW = W - pad.l - pad.r;
  const H = pad.t + priceH + gap + volH + pad.b;
  const volTop = pad.t + priceH + gap;

  const levels = overlays.levels ?? null;
  const levelList: Array<{ key: "target" | "entry" | "stop"; label: string; value: number; color: string }> = [];
  if (levels?.target != null) levelList.push({ key: "target", label: "Target", value: levels.target, color: UP });
  if (levels?.entry != null) levelList.push({ key: "entry", label: "Entry", value: levels.entry, color: "var(--cp-ink)" });
  if (levels?.stop != null) levelList.push({ key: "stop", label: "Stop", value: levels.stop, color: DOWN });

  const lineValues = [overlays.ema20, overlays.ema50, overlays.vwap20].flatMap((s) => (s ?? []).filter((v): v is number => v != null && Number.isFinite(v)));
  const lo = Math.min(...bars.map((b) => b.low), ...lineValues, ...levelList.map((l) => l.value));
  const hi = Math.max(...bars.map((b) => b.high), ...lineValues, ...levelList.map((l) => l.value));
  const room = (hi - lo || hi || 1) * 0.05;
  const min = lo - room;
  const range = hi + room - min;
  const maxVol = Math.max(...bars.map((b) => b.volume), 1);

  const slot = iW / Math.max(n, 1);
  const x = (i: number) => pad.l + (i + 0.5) * slot;
  const y = (v: number) => pad.t + priceH - ((v - min) / range) * priceH;
  const bodyW = Math.max(1, slot * 0.62);

  const ticks = niceTicks(lo, hi, 5);
  const labelCount = Math.min(n, mobile ? 3 : 5);
  const labelled = Array.from(new Set(Array.from({ length: labelCount }, (_, k) => Math.round((k * (n - 1)) / Math.max(labelCount - 1, 1)))));

  // Level labels sit at the right end of their line; labels closer than 12px are pushed apart.
  const placed = levelList.map((l) => ({ ...l, ly: y(l.value) })).sort((a, b) => a.ly - b.ly);
  for (let i = 1; i < placed.length; i++) placed[i].ly = Math.max(placed[i].ly, placed[i - 1].ly + 12);

  const onMove = (e: PointerEvent<SVGSVGElement>) => {
    const box = e.currentTarget.getBoundingClientRect();
    if (box.width <= 0 || n === 0) return;
    const at = ((e.clientX - box.left) / box.width) * W;
    setActive(Math.min(n - 1, Math.max(0, Math.floor((at - pad.l) / slot))));
  };
  const onKey = (e: KeyboardEvent<SVGSVGElement>) => {
    if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
    e.preventDefault();
    const from = active ?? n - 1;
    setActive(Math.min(n - 1, Math.max(0, from + (e.key === "ArrowLeft" ? -1 : 1))));
  };

  const at = active ?? n - 1;
  const shown = bars[at];
  const last = bars[n - 1];
  const prevClose = n > 1 ? bars[n - 2].close : null;
  const lastUp = prevClose == null || last.close >= prevClose;
  const axisText = { fill: "var(--cp-ink-3)", fontFamily: "var(--mono)", fontSize: 10 } as const;
  const tagH = 16;
  const lastY = y(last.close);
  const highest = Math.max(...bars.map((b) => b.high));
  const lowest = Math.min(...bars.map((b) => b.low));

  return (
    <div className="flex flex-col" style={{ gap: 8 }} data-testid="desk-chart">
      <span data-testid="desk-chart-readout" aria-live="polite" className="cp-num" style={{ fontSize: 12, color: "var(--cp-ink-2)", lineHeight: 1.5 }}>
        {fmtDay(shown.day)} · O {fmtPrice(shown.open)} · H {fmtPrice(shown.high)} · L {fmtPrice(shown.low)} · C {fmtPrice(shown.close)} · Vol {fmtShares(shown.volume)}
      </span>
      <svg
        data-testid="desk-chart-svg"
        viewBox={`0 0 ${W} ${H}`}
        role="img"
        tabIndex={0}
        aria-label={`${name}: ${n} daily candles from ${fmtDay(bars[0].day)} to ${fmtDay(last.day)}. Last close ${fmtPrice(last.close)}; highest ${fmtPrice(highest)}, lowest ${fmtPrice(lowest)}. Use the left and right arrow keys to read a session.`}
        style={{ display: "block", width: "100%", height: "auto", touchAction: "pan-y" }}
        onPointerMove={onMove}
        onPointerDown={onMove}
        onPointerLeave={() => setActive(null)}
        onKeyDown={onKey}
        onBlur={() => setActive(null)}
      >
        {/* price grid and axis */}
        {ticks.map((v) => (
          <g key={v}>
            <line x1={pad.l} y1={y(v)} x2={W - pad.r} y2={y(v)} style={{ stroke: "var(--line-2)" }} strokeWidth={1} />
            <text x={pad.l - 8} y={y(v) + 3} textAnchor="end" style={axisText}>{axisRupees(v)}</text>
          </g>
        ))}

        {/* candles */}
        {bars.map((b, i) => {
          const up = b.close >= b.open;
          const color = up ? UP : DOWN;
          const top = y(Math.max(b.open, b.close));
          const h = Math.max(1, Math.abs(y(b.open) - y(b.close)));
          return (
            <g key={b.day} data-testid="desk-candle" data-day={b.day} opacity={active != null && i !== active ? 0.75 : 1}>
              <line x1={x(i)} y1={y(b.high)} x2={x(i)} y2={y(b.low)} style={{ stroke: color }} strokeWidth={1} />
              <rect x={x(i) - bodyW / 2} y={top} width={bodyW} height={h} style={{ fill: color }} />
            </g>
          );
        })}

        {/* overlays */}
        {overlays.vwap20 && <path data-testid="desk-line-vwap" d={seriesPath(overlays.vwap20, x, y)} fill="none" style={{ stroke: VWAP }} strokeWidth={1.5} strokeDasharray="5 3" />}
        {overlays.ema50 && <path data-testid="desk-line-ema50" d={seriesPath(overlays.ema50, x, y)} fill="none" style={{ stroke: EMA50 }} strokeWidth={1.5} />}
        {overlays.ema20 && <path data-testid="desk-line-ema20" d={seriesPath(overlays.ema20, x, y)} fill="none" style={{ stroke: EMA20 }} strokeWidth={1.5} />}

        {/* levels */}
        {placed.map((l) => (
          <g key={l.key} data-testid={`desk-level-${l.key}`}>
            <line x1={pad.l} y1={y(l.value)} x2={W - pad.r} y2={y(l.value)} style={{ stroke: l.color }} strokeWidth={1} strokeDasharray="4 4" opacity={0.85} />
            <text x={W - pad.r - 4} y={l.ly - 4} textAnchor="end" style={{ ...axisText, fill: l.color, stroke: "var(--bg-1)", strokeWidth: 3, paintOrder: "stroke" }}>{l.label} {fmtPrice(l.value)}</text>
          </g>
        ))}

        {/* last-price tag in the right gutter */}
        <g data-testid="desk-last-tag">
          <line x1={pad.l} y1={lastY} x2={W - pad.r} y2={lastY} style={{ stroke: lastUp ? UP : DOWN }} strokeWidth={0.75} strokeDasharray="1 3" />
          <rect x={W - pad.r + 2} y={lastY - tagH / 2} width={pad.r - 4} height={tagH} rx={3} style={{ fill: lastUp ? UP : DOWN }} />
          <text x={W - pad.r + 2 + (pad.r - 4) / 2} y={lastY + 3.5} textAnchor="middle" style={{ fontFamily: "var(--mono)", fontSize: 10, fill: "var(--bg-0)" }}>
            {new Intl.NumberFormat("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(last.close)}
          </text>
        </g>

        {/* volume panel */}
        <line x1={pad.l} y1={volTop + volH} x2={W - pad.r} y2={volTop + volH} style={{ stroke: "var(--line-2)" }} strokeWidth={1} />
        <text x={pad.l - 8} y={volTop + 8} textAnchor="end" style={axisText}>{fmtShares(maxVol)}</text>
        <text x={pad.l - 8} y={volTop + volH} textAnchor="end" style={axisText}>Vol</text>
        {bars.map((b, i) => {
          const h = Math.max(b.volume > 0 ? 1 : 0, (b.volume / maxVol) * volH);
          return (
            <rect
              key={b.day}
              x={x(i) - bodyW / 2}
              y={volTop + volH - h}
              width={bodyW}
              height={h}
              style={{ fill: b.close >= b.open ? UP : DOWN }}
              opacity={i === active ? 0.95 : 0.45}
            />
          );
        })}

        {/* dates */}
        {labelled.map((i) => (
          <text key={i} x={x(i)} y={H - 6} textAnchor={i === 0 ? "start" : i === n - 1 ? "end" : "middle"} style={axisText}>
            {dayLabel(bars[i].day)}
          </text>
        ))}

        {/* cursor */}
        {active != null && (
          <line x1={x(active)} y1={pad.t} x2={x(active)} y2={volTop + volH} style={{ stroke: "var(--line-3)" }} strokeWidth={1} />
        )}
      </svg>
    </div>
  );
}

/** The legend under the chart; only the overlays that are drawn. */
export function CandleLegend({ ema, vwap, levels }: { ema: boolean; vwap: boolean; levels: boolean }) {
  return (
    <div data-testid="desk-chart-legend" className="flex flex-wrap" style={{ gap: "4px 16px" }}>
      <LegendKey color={UP} box>Up day</LegendKey>
      <LegendKey color={DOWN} box>Down day</LegendKey>
      {ema && <LegendKey color={EMA20}>EMA 20</LegendKey>}
      {ema && <LegendKey color={EMA50}>EMA 50</LegendKey>}
      {vwap && <LegendKey color={VWAP} dashed>VWAP 20D</LegendKey>}
      {levels && <LegendKey color={UP} dashed>Target</LegendKey>}
      {levels && <LegendKey color="var(--cp-ink)" dashed>Entry</LegendKey>}
      {levels && <LegendKey color={DOWN} dashed>Stop</LegendKey>}
    </div>
  );
}
