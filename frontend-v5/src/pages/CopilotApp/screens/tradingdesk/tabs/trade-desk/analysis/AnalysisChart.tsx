/**
 * Chart Analysis v2 — the chart (the owner's design of 29 Oct, "Nivesh Chart"): one SVG, one time axis, one cursor.
 *
 *   price pane      candles, a close line or an area (the toolbar) · EMA 20 · SMA 20 (toggle) · CALL WALL / PUT WALL /
 *                   MAX PAIN dashed lines with tags · WATCH / READY markers on top with a dotted drop line · RVOL marker · ✓
 *                   under a confirmed bar · bar-signal triangles (▲ under the bar, ▼ over it; bar-signals.ts) · event chips
 *                   at the foot · trade lines (STOP and TGT drag) · the user's drawings (trend, horizontal, vertical,
 *                   rectangle, Fib, measure; anchored to a bar's time and a price) · the crosshair's price tag and the last
 *                   price tag in the gutter
 *   VOLUME          the bar's volume, mint up / red down
 *   FUTURES OI      the selected slot's OI per bar (line)
 *   OI Δ PER BAR    the OI change per bar (mint up, red down) around a zero line
 *   BUILD-UP        one tag per window (LB SB SC LU), from the route's own classification
 *   STRIKE LADDER   on the right, on the price axis: put bars to the left, call bars to the right, an OI-Δ tick under
 *                   each (bright = added, amber = cut), P / C on the walls; a click selects the strike
 *
 * Draws only what it is given; every figure comes from the page's routes. Pixel-sized (ResizeObserver) so text stays
 * crisp. View: the latest bars that fit; the wheel over the price or volume pane zooms, a drag with the crosshair tool pans,
 * "Reset view" returns to the latest bars. Phone: no ladder (the chain below has the strikes) and no drawing tools.
 */
import { useEffect, useId, useMemo, useRef, useState, type KeyboardEvent, type PointerEvent } from "react";
import type { DailyBar } from "../../../indicators";

export type LadderMode = "oi" | "oichg" | "vol";

export interface LadderRow {
  strike: number;
  put: { oi: number | null; oiChange: number | null; volume: number | null } | null;
  call: { oi: number | null; oiChange: number | null; volume: number | null } | null;
}

export interface ChartLevel { key: string; value: number; label: string; color: string }
export interface TradeLine extends ChartLevel { drag?: string | null }
export interface ChartMark { i: number; label: string; color: string; title: string; row: 0 | 1 }
export interface BuildupTag { i0: number; i1: number; tag: "LB" | "SB" | "SC" | "LU"; color: string; soft: string; title: string }
export interface EventChip { i: number; glyph: string; color: string; title: string; kind: string }
/** One bar-signal triangle: under the bar (up) or over it. */
export interface SignalMark { i: number; key: string; color: string; up: boolean; title: string }
export type ChartType = "candles" | "line" | "area";
export type DrawTool = "cursor" | "trend" | "h" | "v" | "rect" | "fib" | "measure";
/** A drawing, anchored to bar times (`t1`, `t2`: a bar's `day`) and prices, so it stays put while bars arrive or the view moves. */
export interface Drawing { kind: Exclude<DrawTool, "cursor">; t1?: string; p1: number; t2?: string; p2?: number }
export const TWO_CLICK: ReadonlySet<DrawTool> = new Set(["trend", "rect", "fib", "measure"]);
export const FIB_LEVELS = [0, 0.236, 0.382, 0.5, 0.618, 0.786, 1];

export interface AnalysisChartProps {
  bars: DailyBar[];
  intraday: boolean;
  ema: Array<number | null>;
  marks: ChartMark[];
  confirms: number[];
  levels: ChartLevel[];
  tradeLines: TradeLine[];
  last: number | null;
  fut: { oi: Array<number | null>; change: Array<number | null>; label: string } | null;
  futEmpty: string | null;
  buildups: BuildupTag[];
  events: EventChip[];
  ladder: { rows: LadderRow[]; mode: LadderMode; selected: number | null; atm: number | null; putWall: number | null; callWall: number | null; onSelect: (strike: number) => void } | null;
  ladderEmpty: string | null;
  compact: boolean;
  active: number | null;
  onActive: (i: number | null) => void;
  onPriceClick?: (price: number) => void;
  onDrag?: (key: string, price: number) => void;
  chartType?: ChartType;
  /** SMA 20 on the same bars; null hides it */
  sma?: Array<number | null> | null;
  signals?: SignalMark[];
  tool?: DrawTool;
  drawings?: Drawing[];
  onDraw?: (d: Drawing) => void;
  /** a new value (another stock or timeframe) returns the view to the latest bars */
  viewKey?: string;
}

const MIN_SPAN = 10;

const MONO = "var(--mono)";
const fmtPx = (v: number) => v.toLocaleString("en-IN", { minimumFractionDigits: 1, maximumFractionDigits: v >= 1000 ? 1 : 2 });
const fmtAxis = (v: number) => v.toLocaleString("en-IN", { maximumFractionDigits: v >= 1000 ? 0 : 1 });
const fin = (v: number | null | undefined): v is number => v != null && Number.isFinite(v);

function useWidth(): [(el: HTMLDivElement | null) => void, number] {
  const [el, setEl] = useState<HTMLDivElement | null>(null);
  const [w, setW] = useState(900);
  useEffect(() => {
    if (!el || typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver((e) => { const v = e[0]?.contentRect.width; if (v) setW(Math.round(v)); });
    ro.observe(el);
    return () => ro.disconnect();
  }, [el]);
  return [setEl, w];
}

/** Nice round grid steps for a price range. */
function gridSteps(lo: number, hi: number, n: number): number[] {
  const raw = (hi - lo) / Math.max(1, n);
  const mag = 10 ** Math.floor(Math.log10(raw || 1));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= raw) ?? raw;
  const out: number[] = [];
  for (let v = Math.ceil(lo / step) * step; v <= hi; v += step) out.push(+v.toFixed(6));
  return out;
}

export function AnalysisChart(p: AnalysisChartProps) {
  const [ref, W] = useWidth();
  const svgRef = useRef<SVGSVGElement | null>(null);
  const drag = useRef<string | null>(null);
  const pan = useRef<{ x: number; off: number; moved: boolean } | null>(null);
  const justPanned = useRef(false);
  const uid = useId().replace(/[^a-zA-Z0-9]/g, "");
  const compact = p.compact;
  const tool: DrawTool = p.tool ?? "cursor";
  const chartType: ChartType = p.chartType ?? "candles";
  const [span, setSpan] = useState<number | null>(null);      // bars in view; null = as many as fit
  const [off, setOff] = useState(0);                           // bars hidden on the right (0 = the latest bar in view)
  const [hover, setHover] = useState<{ x: number; y: number } | null>(null);
  const [pending, setPending] = useState<{ t1: string; p1: number } | null>(null);
  useEffect(() => { setSpan(null); setOff(0); setPending(null); }, [p.viewKey]);
  useEffect(() => { setPending(null); }, [tool]);

  // ── geometry ──
  const ladderW = !compact && p.ladder ? Math.round(Math.min(240, Math.max(190, W * 0.22))) : 0;
  const gutter = compact ? 50 : 56;
  const plotL = compact ? 4 : 8;
  const plotR = W - ladderW - gutter - (ladderW ? 12 : 0);
  const plotW = Math.max(60, plotR - plotL);
  const topPad = 34;                                   // room for the WATCH / READY row and the RVOL row
  const priceH = compact ? 220 : 290;
  const priceBot = topPad + priceH;
  const vTop = priceBot + 20, vBot = vTop + (compact ? 34 : 44);
  const oiTop = vBot + 22, oiBot = oiTop + (compact ? 44 : 54);
  const dTop = oiBot + 22, dBot = dTop + (compact ? 44 : 54);
  const bTop = dBot + 8, bH = 16;
  const H = bTop + bH + 6;
  const font = compact ? 9.5 : 10;

  // ── the bars in view ──
  const len = p.bars.length;
  const minSlot = compact ? 8 : 6;
  const fit = Math.max(8, Math.floor(plotW / minSlot));
  const maxSpan = Math.max(MIN_SPAN, Math.floor(plotW / 1.5));
  const want = span == null ? Math.min(fit, len) : Math.max(MIN_SPAN, Math.min(span, maxSpan));
  const nView = Math.max(1, Math.min(len, want));
  const offC = Math.max(0, Math.min(off, len - nView));
  const end = len - offC;
  const start = Math.max(0, end - nView);
  const bars = p.bars.slice(start, end);
  const n = bars.length;
  const slot = plotW / Math.max(1, n);
  const bodyW = Math.max(1.5, Math.min(12, slot * 0.62));
  const x = (i: number) => plotL + slot * (i - start) + slot / 2;   // i is the index in p.bars
  const inView = (i: number) => i >= start && i < end;
  const idxOfT = useMemo(() => new Map(p.bars.map((b, i) => [b.day, i])), [p.bars]);

  // ── price scale ──
  const { lo, hi } = useMemo(() => {
    let a = Infinity, b = -Infinity;
    bars.forEach((c) => { a = Math.min(a, c.low); b = Math.max(b, c.high); });
    if (!Number.isFinite(a)) { a = 0; b = 1; }
    const span0 = Math.max(b - a, b * 0.01);
    // a level is drawn when it is near the candles; one far away would squash them (it is listed in the legend instead)
    const near = (v: number) => v >= a - span0 * 0.6 && v <= b + span0 * 0.6;
    [...p.levels, ...p.tradeLines].forEach((l) => { if (near(l.value)) { a = Math.min(a, l.value); b = Math.max(b, l.value); } });
    if (p.ladder?.atm != null && near(p.ladder.atm)) { a = Math.min(a, p.ladder.atm); b = Math.max(b, p.ladder.atm); }
    const pad = (b - a) * 0.06 || 1;
    return { lo: a - pad, hi: b + pad };
  }, [bars, p.levels, p.tradeLines, p.ladder?.atm]);
  const py = (v: number) => topPad + ((hi - v) / (hi - lo)) * priceH;
  const pf = (y: number) => hi - ((y - topPad) / priceH) * (hi - lo);
  const onScale = (v: number) => v >= lo && v <= hi;

  // ── pointer ──
  const toLocal = (e: { clientX: number; clientY: number }) => {
    const r = svgRef.current?.getBoundingClientRect();
    return r ? { x: ((e.clientX - r.left) / r.width) * W, y: ((e.clientY - r.top) / r.height) * H } : { x: 0, y: 0 };
  };
  const barAt = (lx: number) => {
    if (lx < plotL || lx > plotR) return null;
    const i = start + Math.floor((lx - plotL) / slot);
    return i >= start && i < end ? i : null;
  };
  const inPlot = (pt: { x: number; y: number }) => pt.x >= plotL && pt.x <= plotR && pt.y >= topPad && pt.y <= vBot;
  const onDown = (e: PointerEvent<SVGSVGElement>) => {
    justPanned.current = false;                                // a new press: the previous gesture's pan no longer swallows a click
    if (tool !== "cursor" || drag.current) return;
    const pt = toLocal(e);
    if (!inPlot(pt)) return;
    pan.current = { x: pt.x, off: offC, moved: false };
  };
  const onMove = (e: PointerEvent<SVGSVGElement>) => {
    const pt = toLocal(e);
    setHover(pt);
    if (drag.current && p.onDrag) { p.onDrag(drag.current, Math.round(pf(Math.min(priceBot, Math.max(topPad, pt.y))) * 20) / 20); return; }
    if (pan.current) {
      const dx = pt.x - pan.current.x;
      if (!pan.current.moved && Math.abs(dx) > 4) {
        pan.current.moved = true;
        try { svgRef.current?.setPointerCapture?.(e.pointerId); } catch { /* capture is best effort */ }
      }
      if (pan.current.moved) { setOff(Math.max(0, Math.min(len - nView, pan.current.off + Math.round(dx / slot)))); return; }
    }
    p.onActive(barAt(pt.x));
  };
  const onUp = () => {
    drag.current = null;
    if (pan.current?.moved) justPanned.current = true;
    pan.current = null;
  };
  const onKey = (e: KeyboardEvent<SVGSVGElement>) => {
    if (e.key === "Escape") { setPending(null); return; }
    if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
    e.preventDefault();
    const cur = p.active ?? end - 1;
    p.onActive(Math.min(end - 1, Math.max(start, cur + (e.key === "ArrowLeft" ? -1 : 1))));
  };
  const onPlotClick = (e: { clientX: number; clientY: number }) => {
    if (justPanned.current) { justPanned.current = false; return; }
    const pt = toLocal(e);
    const price = Math.round(pf(Math.min(priceBot, Math.max(topPad, pt.y))) * 100) / 100;
    if (tool === "cursor") { if (p.onPriceClick) p.onPriceClick(Math.round(price * 20) / 20); return; }
    const i = barAt(pt.x);
    if (i == null || !p.onDraw) return;
    const t = p.bars[i].day;
    if (tool === "h") p.onDraw({ kind: "h", p1: price });
    else if (tool === "v") p.onDraw({ kind: "v", t1: t, p1: price });
    else if (!pending) setPending({ t1: t, p1: price });
    else { p.onDraw({ kind: tool, t1: pending.t1, p1: pending.p1, t2: t, p2: price }); setPending(null); }
  };

  // the wheel zooms over the price and volume panes (a native listener: React's wheel handler cannot stop the page scroll)
  const geo = useRef({ inPlot, toLocal, nView, maxSpan });
  geo.current = { inPlot, toLocal, nView, maxSpan };
  useEffect(() => {
    const el = svgRef.current;
    if (!el) return;
    const wheel = (e: WheelEvent) => {
      const g = geo.current;
      if (!g.inPlot(g.toLocal(e)) || e.deltaY === 0) return;
      e.preventDefault();
      const next = Math.round(g.nView * (e.deltaY > 0 ? 1.15 : 1 / 1.15));
      setSpan(Math.max(MIN_SPAN, Math.min(g.maxSpan, next === g.nView ? g.nView + (e.deltaY > 0 ? 1 : -1) : next)));
    };
    el.addEventListener("wheel", wheel, { passive: false });
    return () => el.removeEventListener("wheel", wheel);
  }, []);

  // ── volume pane ──
  const volMax = Math.max(1, ...bars.map((c) => c.volume || 0));
  const vy = (v: number) => vBot - (v / volMax) * (vBot - vTop - 4);

  // ── futures panes ──
  const oiVals = (p.fut?.oi ?? []).slice(start, end).filter(fin);
  const oiLo = oiVals.length ? Math.min(...oiVals) : 0, oiHi = oiVals.length ? Math.max(...oiVals) : 1;
  const oy = (v: number) => oiBot - 4 - ((v - oiLo) / ((oiHi - oiLo) || Math.abs(oiHi) || 1)) * (oiBot - oiTop - 14);
  const lineOf = (vals: Array<number | null> | null | undefined, yOf: (v: number) => number, keep: (v: number) => boolean = () => true) => {
    if (!vals) return "";
    let d = "", pen = false;
    for (let i = start; i < end; i += 1) {
      const v = vals[i];
      if (!fin(v) || !keep(v)) { pen = false; continue; }
      d += `${pen ? "L" : "M"}${x(i).toFixed(1)},${yOf(v).toFixed(1)}`;
      pen = true;
    }
    return d;
  };
  const oiPath = p.fut ? lineOf(p.fut.oi, oy) : "";
  const chg = (p.fut?.change ?? []).slice(start, end);
  const chgMax = Math.max(...chg.filter(fin).map((v) => Math.abs(v)), 0) || 1;
  const dZero = (dTop + dBot) / 2 + 4;
  const dHalf = (dBot - dTop) / 2 - 6;

  // ── ladder ──
  const ladder = p.ladder;
  const lx0 = plotR + gutter + 12;
  const mid = lx0 + ladderW * 0.5;
  const putMax = ladderW * 0.36, callMax = ladderW * 0.36;
  const strikeHalf = ladderW * 0.12;
  const ladderRows = useMemo(() => {
    if (!ladder) return [];
    const rows = ladder.rows.filter((r) => onScale(r.strike));
    if (rows.length < 2) return rows;
    const gap = Math.abs(py(rows[0].strike) - py(rows[1].strike));
    const keepEvery = Math.max(1, Math.ceil(11 / Math.max(1, gap)));
    const must = new Set([ladder.atm, ladder.selected, ladder.putWall, ladder.callWall].filter(fin));
    return rows.filter((r, k) => k % keepEvery === 0 || must.has(r.strike));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ladder, lo, hi]);
  const pick = (r: LadderRow, side: "put" | "call") => {
    const s = r[side];
    if (!s || !ladder) return null;
    return ladder.mode === "oi" ? s.oi : ladder.mode === "oichg" ? s.oiChange : s.volume;
  };
  const ladderScale = Math.max(1, ...ladderRows.flatMap((r) => [pick(r, "put"), pick(r, "call")]).filter(fin).map((v) => Math.abs(v)));
  const tickScale = Math.max(1, ...ladderRows.flatMap((r) => [r.put?.oiChange, r.call?.oiChange]).filter(fin).map((v) => Math.abs(v)));
  const rowH = ladderRows.length > 1 ? Math.max(7, Math.min(18, Math.abs(py(ladderRows[0].strike) - py(ladderRows[1].strike)) * 0.86)) : 16;

  const grid = gridSteps(lo, hi, compact ? 4 : 5);
  const lastY = fin(p.last) && onScale(p.last) ? py(p.last) : null;
  const confirmSet = new Set(p.confirms);
  const closePath = chartType === "candles" ? "" : lineOf(p.bars.map((b) => b.close), py);
  const viewMoved = span != null || offC > 0;
  const cross = hover && hover.x >= plotL && hover.x <= plotR && hover.y >= topPad && hover.y <= priceBot ? hover : null;

  // a drawing's x: its bar's centre (null when that bar is no longer loaded)
  const xt = (t: string | undefined) => { const i = t != null ? idxOfT.get(t) : undefined; return i != null ? x(i) : null; };
  const drawing = (d: Drawing, key: string, preview = false) => {
    const col = d.kind === "h" || d.kind === "v" ? "var(--amber)" : "var(--cp-indigo)";
    const dash = preview ? "3 3" : undefined;
    const X1 = xt(d.t1), X2 = xt(d.t2);
    const Y1 = py(d.p1), Y2 = d.p2 != null ? py(d.p2) : Y1;
    const common = { "data-testid": preview ? "ca-draw-preview" : "ca-drawing", "data-kind": d.kind } as const;
    if (d.kind === "h") return (
      <g key={key} {...common}>
        <line x1={plotL} x2={plotR} y1={Y1} y2={Y1} style={{ stroke: col }} strokeWidth={1.2} strokeDasharray={dash ?? "5 4"} />
        <text x={plotR - 4} y={Y1 - 4} textAnchor="end" style={{ fontSize: font - 1, fill: col }}>{fmtPx(d.p1)}</text>
      </g>
    );
    if (X1 == null) return null;
    if (d.kind === "v") return <g key={key} {...common}><line x1={X1} x2={X1} y1={topPad} y2={priceBot} style={{ stroke: col }} strokeWidth={1.2} strokeDasharray={dash ?? "5 4"} /></g>;
    if (X2 == null || d.p2 == null) return null;
    if (d.kind === "trend") return (
      <g key={key} {...common}>
        <line x1={X1} x2={X2} y1={Y1} y2={Y2} style={{ stroke: col }} strokeWidth={1.4} strokeDasharray={dash} />
        <circle cx={X1} cy={Y1} r={3} style={{ fill: col }} /><circle cx={X2} cy={Y2} r={3} style={{ fill: col }} />
      </g>
    );
    if (d.kind === "rect") return (
      <g key={key} {...common}>
        <rect x={Math.min(X1, X2)} y={Math.min(Y1, Y2)} width={Math.abs(X2 - X1)} height={Math.abs(Y2 - Y1)} style={{ fill: col, stroke: col }} fillOpacity={0.12} strokeDasharray={dash} />
      </g>
    );
    if (d.kind === "fib") {
      const x0 = Math.min(X1, X2);
      return (
        <g key={key} {...common}>
          {FIB_LEVELS.map((r) => {
            const v = d.p1 + (d.p2! - d.p1) * r;
            const y = py(v);
            const edge = r === 0 || r === 1;
            return (
              <g key={r} data-testid="ca-fib-level" data-ratio={r} data-value={Math.round(v * 100) / 100}>
                <line x1={x0} x2={plotR} y1={y} y2={y} style={{ stroke: edge ? col : "var(--cp-ink-3)" }} strokeWidth={1} strokeDasharray={dash} />
                <text x={x0 + 4} y={y - 3} style={{ fontSize: font - 1.5, fill: "var(--cp-ink-3)" }}>{`${(r * 100).toFixed(1)}%  ${fmtPx(v)}`}</text>
              </g>
            );
          })}
        </g>
      );
    }
    // measure
    const up = d.p2 >= d.p1;
    const c = up ? "var(--mint)" : "var(--cp-danger)";
    const dv = d.p2 - d.p1;
    const nb = (idxOfT.get(d.t2!) ?? 0) - (idxOfT.get(d.t1!) ?? 0);
    const label = `${dv >= 0 ? "+" : "−"}${fmtPx(Math.abs(dv))} (${dv >= 0 ? "+" : "−"}${Math.abs((dv / d.p1) * 100).toFixed(2)}%) · ${Math.abs(nb)} ${Math.abs(nb) === 1 ? "bar" : "bars"}`;
    const lw = label.length * (font * 0.6) + 14;
    const lx = Math.min(plotR - lw, Math.max(plotL, (X1 + X2) / 2 - lw / 2));
    const ly = Math.max(topPad, Math.min(Y1, Y2) - 22);
    return (
      <g key={key} {...common}>
        <rect x={Math.min(X1, X2)} y={Math.min(Y1, Y2)} width={Math.abs(X2 - X1)} height={Math.abs(Y2 - Y1)} style={{ fill: c }} fillOpacity={0.14} />
        <line x1={X1} x2={X2} y1={Y1} y2={Y2} style={{ stroke: c }} strokeWidth={1.3} strokeDasharray={dash} />
        <g data-testid="ca-measure-label" data-change={Math.round(dv * 100) / 100} data-bars={Math.abs(nb)}>
          <rect x={lx} y={ly} width={lw} height={17} rx={3} style={{ fill: c }} />
          <text x={lx + lw / 2} y={ly + 12} textAnchor="middle" style={{ fontSize: font - 1, fontWeight: 600, fill: "var(--bg-0)" }}>{label}</text>
        </g>
      </g>
    );
  };
  const preview: Drawing | null = pending && hover && TWO_CLICK.has(tool) && tool !== "cursor" ? (() => {
    const i = barAt(hover.x);
    return i == null ? null : { kind: tool as Drawing["kind"], t1: pending.t1, p1: pending.p1, t2: p.bars[i].day, p2: pf(Math.min(priceBot, Math.max(topPad, hover.y))) };
  })() : null;

  return (
    <div ref={ref} data-testid="ca-chart" data-bars={n} data-start={start} data-end={end} data-tool={tool} data-type={chartType} className="min-w-0" style={{ width: "100%", position: "relative" }}>
      <svg ref={svgRef} data-testid="ca-chart-svg" width={W} height={H} viewBox={`0 0 ${W} ${H}`} role="img" tabIndex={0}
        aria-label="Price, volume, futures open interest, build-up and the strike ladder; use the left and right arrow keys to move the cursor"
        style={{ display: "block", touchAction: drag.current ? "none" : "pan-y", outline: "none", fontFamily: MONO, cursor: tool === "cursor" ? undefined : "crosshair" }}
        onPointerDown={onDown} onPointerMove={onMove} onPointerLeave={() => { setHover(null); if (!drag.current) p.onActive(null); }}
        onPointerUp={onUp} onPointerCancel={onUp} onKeyDown={onKey}>
        <defs>
          <clipPath id={`${uid}-plot`}><rect x={plotL} y={topPad} width={plotW} height={priceH} /></clipPath>
          <linearGradient id={`${uid}-area`} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" style={{ stopColor: "var(--mint)", stopOpacity: 0.28 }} />
            <stop offset="100%" style={{ stopColor: "var(--mint)", stopOpacity: 0 }} />
          </linearGradient>
        </defs>
        {/* grid + price axis */}
        {grid.map((g) => (
          <g key={`g-${g}`}>
            <line x1={plotL} x2={plotR} y1={py(g)} y2={py(g)} style={{ stroke: "var(--cp-line)" }} />
            <text x={plotR + gutter - 4} y={py(g) + 3.5} textAnchor="end" style={{ fontSize: font - 0.5, fill: "var(--cp-ink-4)" }}>{fmtAxis(g)}</text>
          </g>
        ))}

        {/* walls and max pain (their tags are drawn after the trade lines, so a line at the same price never crosses them) */}
        {p.levels.filter((l) => onScale(l.value)).map((l) => (
          <g key={`lv-${l.key}`} data-testid="ca-level" data-key={l.key} data-value={l.value}>
            <line x1={plotL} x2={plotR} y1={py(l.value)} y2={py(l.value)} style={{ stroke: l.color }} strokeDasharray="2 4" />
          </g>
        ))}

        {/* pattern / RVOL markers: a pill on top, a dotted drop line to the bar */}
        {p.marks.filter((m) => inView(m.i)).map((m, k) => {
          const w = m.label.length * (font * 0.62) + 12;
          const cx = Math.min(plotR - w / 2, Math.max(plotL + w / 2, x(m.i)));
          const y0 = 3 + m.row * 15;
          const bar = p.bars[m.i];
          return (
            <g key={`mk-${k}`} data-testid="ca-mark" data-label={m.label} data-i={m.i}>
              <title>{m.title}</title>
              <line x1={x(m.i)} x2={x(m.i)} y1={y0 + 13} y2={bar ? py(bar.high) - 3 : priceBot} style={{ stroke: m.color }} strokeOpacity={0.7} strokeDasharray="1.5 3" />
              <rect x={cx - w / 2} y={y0} width={w} height={13} rx={6.5} style={{ fill: "var(--bg-1)", stroke: m.color }} />
              <text x={cx} y={y0 + 9.5} textAnchor="middle" style={{ fontSize: font - 1.5, fontWeight: 600, fill: m.color, letterSpacing: "0.06em" }}>{m.label}</text>
            </g>
          );
        })}

        {/* candles, or the close as a line / an area */}
        {chartType === "candles" && bars.map((c, k) => {
          const i = start + k;
          const up = c.close >= c.open;
          const col = up ? "var(--mint)" : "var(--cp-danger)";
          const yTop = py(Math.max(c.open, c.close));
          return (
            <g key={`c-${i}`} data-testid="ca-candle" data-i={i} opacity={p.active != null && p.active !== i ? 0.78 : 1}>
              <line x1={x(i)} x2={x(i)} y1={py(c.high)} y2={py(c.low)} style={{ stroke: col }} />
              <rect x={x(i) - bodyW / 2} y={yTop} width={bodyW} height={Math.max(1, Math.abs(py(c.open) - py(c.close)))} style={{ fill: col }} />
            </g>
          );
        })}
        {chartType === "area" && closePath && n > 0 && (
          <path data-testid="ca-area" d={`${closePath}L${x(end - 1).toFixed(1)},${priceBot}L${x(start).toFixed(1)},${priceBot}Z`} style={{ fill: `url(#${uid}-area)` }} />
        )}
        {chartType !== "candles" && closePath && <path data-testid="ca-line" d={closePath} fill="none" style={{ stroke: "var(--mint)" }} strokeWidth={1.7} />}

        {/* EMA 20 */}
        {(() => {
          const d = lineOf(p.ema, py, onScale);
          return d ? <path data-testid="ca-ema" d={d} fill="none" style={{ stroke: "var(--cp-indigo)" }} strokeWidth={1.4} opacity={0.8} /> : null;
        })()}
        {/* SMA 20 */}
        {p.sma && (() => {
          const d = lineOf(p.sma, py, onScale);
          return d ? <path data-testid="ca-sma" d={d} fill="none" style={{ stroke: "var(--amber)" }} strokeWidth={1.4} opacity={0.9} /> : null;
        })()}

        {/* confirmation ✓ under the bar */}
        {p.confirms.filter(inView).map((i) => (
          <g key={`cf-${i}`} data-testid="ca-confirm" data-i={i}>
            <circle cx={x(i)} cy={Math.min(priceBot - 6, py(p.bars[i].low) + 11)} r={6} style={{ fill: "var(--bg-1)", stroke: "var(--mint)" }} />
            <text x={x(i)} y={Math.min(priceBot - 6, py(p.bars[i].low) + 11) + 3.5} textAnchor="middle" style={{ fontSize: 9, fontWeight: 600, fill: "var(--mint)" }}>✓</text>
          </g>
        ))}

        {/* bar signals: ▲ under the bar, ▼ over it, stacked when a bar has several */}
        {(() => {
          const below = new Map<number, number>(), above = new Map<number, number>();
          const z = compact ? 3.6 : 4.4;
          return (p.signals ?? []).filter((s) => inView(s.i)).map((s, k) => {
            const bar = p.bars[s.i];
            const stack = s.up ? below : above;
            const kk = stack.get(s.i) ?? 0;
            stack.set(s.i, kk + 1);
            const cx = x(s.i);
            const cy = s.up
              ? Math.min(priceBot - z, py(bar.low) + (confirmSet.has(s.i) ? 24 : 9) + kk * (z * 2 + 2))
              : Math.max(topPad + z, py(bar.high) - 9 - kk * (z * 2 + 2));
            const d = s.up ? `M${cx},${cy - z}L${cx - z},${cy + z}L${cx + z},${cy + z}Z` : `M${cx},${cy + z}L${cx - z},${cy - z}L${cx + z},${cy - z}Z`;
            return (
              <path key={`sg-${k}`} data-testid="ca-signal" data-key={s.key} data-i={s.i} d={d} style={{ fill: s.color }}>
                <title>{s.title}</title>
              </path>
            );
          });
        })()}

        {/* market events at the foot of the price pane */}
        {(() => {
          const stack = new Map<number, number>();
          return p.events.filter((e) => inView(e.i)).map((e, k) => {
            const s = stack.get(e.i) ?? 0;
            stack.set(e.i, s + 1);
            const cy = priceBot - 8 - s * 12;
            return (
              <g key={`ev-${k}`} data-testid="ca-event" data-kind={e.kind} data-i={e.i}>
                <title>{e.title}</title>
                <rect x={x(e.i) - 5.5} y={cy - 5.5} width={11} height={11} rx={2.5} style={{ fill: "var(--bg-1)", stroke: e.color }} />
                <text x={x(e.i)} y={cy + 3} textAnchor="middle" style={{ fontSize: 7.5, fontWeight: 600, fill: e.color }}>{e.glyph}</text>
              </g>
            );
          });
        })()}

        {/* clicks on the price pane: the cash entry (crosshair tool) or a drawing point (under the trade lines, so their drag handles win) */}
        <rect data-testid="ca-price-hit" x={plotL} y={topPad} width={plotW} height={priceH} fill="transparent"
          style={{ cursor: tool !== "cursor" ? "crosshair" : p.onPriceClick ? "crosshair" : "default" }} onClick={onPlotClick} />

        {/* the user's drawings, clipped to the price pane */}
        <g clipPath={`url(#${uid}-plot)`} style={{ pointerEvents: "none" }}>
          {(p.drawings ?? []).map((d, k) => drawing(d, `dw-${k}`))}
          {preview && drawing(preview, "dw-preview", true)}
        </g>

        {/* trade lines, the tag at the right of the plot; STOP and TGT drag (with the crosshair tool only) */}
        {p.tradeLines.filter((t) => onScale(t.value)).map((t) => {
          const txt = `${t.label} ${fmtPx(t.value)}`;
          const w = txt.length * (font * 0.62) + 12;
          const y = py(t.value);
          return (
            <g key={`tl-${t.key}`} data-testid="ca-tradeline" data-key={t.key} data-value={t.value}>
              <line x1={plotL} x2={plotR} y1={y} y2={y} style={{ stroke: t.color, pointerEvents: "none" }} strokeWidth={1.3} strokeDasharray="6 4" />
              <rect x={plotR - w - 2} y={y - 7.5} width={w} height={15} rx={3} style={{ fill: t.color, pointerEvents: "none" }} />
              <text x={plotR - 2 - w / 2} y={y + 3.5} textAnchor="middle" style={{ fontSize: font - 1, fontWeight: 600, fill: "var(--bg-0)", pointerEvents: "none" }}>{txt}</text>
              {t.drag && p.onDrag && tool === "cursor" && (
                <rect data-testid="ca-tradeline-handle" data-key={t.key} x={plotL} y={y - 6} width={plotW} height={12} fill="transparent" style={{ cursor: "ns-resize" }}
                  onPointerDown={(e) => { drag.current = t.drag ?? null; try { (e.currentTarget.ownerSVGElement ?? e.currentTarget).setPointerCapture?.(e.pointerId); } catch { /* capture is best effort */ } e.stopPropagation(); }} />
              )}
            </g>
          );
        })}

        {/* the walls' and max pain's tags, on top of every line */}
        {p.levels.filter((l) => onScale(l.value)).map((l) => {
          const t = `${l.label} ${fmtAxis(l.value)}`;
          const w = t.length * (font * 0.62) + 12;
          return (
            <g key={`lvt-${l.key}`} data-testid="ca-level-tag" data-key={l.key} style={{ pointerEvents: "none" }}>
              <rect x={plotL + 2} y={py(l.value) - 8} width={w} height={15} rx={3} style={{ fill: "var(--bg-1)", stroke: l.color }} strokeOpacity={0.5} />
              <text x={plotL + 8} y={py(l.value) + 3.5} style={{ fontSize: font - 1, fill: l.color, letterSpacing: "0.06em" }}>{t}</text>
            </g>
          );
        })}

        {/* last price */}
        {lastY != null && fin(p.last) && (
          <g data-testid="ca-last-tag" data-value={p.last} style={{ pointerEvents: "none" }}>
            <line x1={plotL} x2={plotR} y1={lastY} y2={lastY} style={{ stroke: "var(--cp-ink-2)" }} strokeWidth={0.8} strokeDasharray="2 3" />
            <rect x={plotR + 2} y={lastY - 8} width={gutter - 4} height={16} rx={3} style={{ fill: "var(--mint)" }} />
            <text x={plotR + gutter / 2} y={lastY + 3.5} textAnchor="middle" style={{ fontSize: font - 0.5, fontWeight: 600, fill: "var(--bg-0)" }}>{fmtPx(p.last)}</text>
          </g>
        )}

        {/* crosshair: the price under the pointer, tagged in the gutter */}
        {cross && (
          <g data-testid="ca-crosshair" style={{ pointerEvents: "none" }}>
            <line x1={plotL} x2={plotR} y1={cross.y} y2={cross.y} style={{ stroke: "var(--cp-ink-2)" }} strokeOpacity={0.55} strokeDasharray="4 4" />
            <rect x={plotR + 2} y={cross.y - 8} width={gutter - 4} height={16} rx={3} style={{ fill: "var(--cp-ink)" }} />
            <text data-testid="ca-cross-price" data-value={Math.round(pf(cross.y) * 100) / 100} x={plotR + gutter / 2} y={cross.y + 3.5} textAnchor="middle" style={{ fontSize: font - 0.5, fontWeight: 600, fill: "var(--bg-0)" }}>{fmtPx(pf(cross.y))}</text>
          </g>
        )}

        {/* VOLUME */}
        <text x={plotL} y={vTop - 6} style={{ fontSize: font - 1, fill: "var(--cp-ink-3)", letterSpacing: "0.1em" }}>VOLUME</text>
        {bars.map((c, k) => {
          const i = start + k;
          const v = c.volume || 0;
          if (v <= 0) return null;
          return <rect key={`v-${i}`} data-testid="ca-vol" data-i={i} x={x(i) - bodyW / 2} y={vy(v)} width={bodyW} height={vBot - vy(v)} style={{ fill: c.close >= c.open ? "var(--mint)" : "var(--cp-danger)" }} opacity={0.45} />;
        })}
        {n > 0 && <text x={plotR + gutter - 4} y={vTop + 8} textAnchor="end" style={{ fontSize: font - 1, fill: "var(--cp-ink-3)" }}>{fmtLakh(bars[n - 1].volume)}</text>}

        {/* FUTURES OI */}
        <text x={plotL} y={oiTop - 7} style={{ fontSize: font - 1, fill: "var(--cp-ink-3)", letterSpacing: "0.1em" }}>{`FUTURES OI${p.fut ? ` · ${p.fut.label.toUpperCase()}` : ""}`}</text>
        {p.fut && oiPath ? (
          <>
            <path data-testid="ca-fut-oi" d={oiPath} fill="none" style={{ stroke: "var(--cp-indigo)" }} strokeWidth={1.5} />
            {oiVals.length > 0 && (
              <text x={plotR + gutter - 4} y={oy(oiVals[oiVals.length - 1]) + 3.5} textAnchor="end" style={{ fontSize: font - 1, fill: "var(--cp-indigo)" }}>{fmtLakh(oiVals[oiVals.length - 1])}</text>
            )}
          </>
        ) : <text data-testid="ca-fut-empty" x={plotL} y={oiTop + 18} style={{ fontSize: font, fill: "var(--cp-ink-3)", fontFamily: "var(--sans)" }}>{p.futEmpty ?? "No futures OI for these bars."}</text>}

        {/* OI Δ PER BAR */}
        <text x={plotL} y={dTop - 7} style={{ fontSize: font - 1, fill: "var(--cp-ink-3)", letterSpacing: "0.1em" }}>OI Δ PER BAR</text>
        <line x1={plotL} x2={plotR} y1={dZero} y2={dZero} style={{ stroke: "var(--line-3)" }} />
        {p.fut && chg.map((v, k) => {
          if (!fin(v)) return null;
          const i = start + k;
          const h = Math.max(0.6, (Math.abs(v) / chgMax) * dHalf);
          return <rect key={`d-${i}`} data-testid="ca-fut-chg" data-i={i} data-value={v} x={x(i) - bodyW / 2} y={v >= 0 ? dZero - h : dZero} width={bodyW} height={h} style={{ fill: v >= 0 ? "var(--mint)" : "var(--cp-danger)" }} />;
        })}

        {/* BUILD-UP row */}
        {p.buildups.filter((b) => b.i1 >= start && b.i0 < end).map((b, k) => {
          const x0 = plotL + slot * (Math.max(b.i0, start) - start) + 1;
          const x1 = plotL + slot * (Math.min(b.i1, end - 1) - start + 1) - 1;
          const w = Math.max(6, x1 - x0);
          return (
            <g key={`b-${k}`} data-testid="ca-buildup" data-tag={b.tag} data-i0={b.i0} data-i1={b.i1}>
              <title>{b.title}</title>
              <rect x={x0} y={bTop} width={w} height={bH} rx={3} style={{ fill: b.soft, stroke: b.color }} strokeOpacity={0.5} />
              {w >= 16 && <text x={x0 + w / 2} y={bTop + 11.5} textAnchor="middle" style={{ fontSize: font - 1, fill: b.color }}>{b.tag}</text>}
            </g>
          );
        })}

        {/* cursor */}
        {p.active != null && inView(p.active) && <line x1={x(p.active)} x2={x(p.active)} y1={topPad} y2={bTop + bH} style={{ stroke: "var(--line-3)", pointerEvents: "none" }} />}

        {/* STRIKE LADDER */}
        {ladder && ladderW > 0 && (
          <g data-testid="ca-ladder" data-mode={ladder.mode}>
            <line x1={lx0 - 6} x2={lx0 - 6} y1={topPad - 14} y2={H - 6} style={{ stroke: "var(--cp-line)" }} />
            <text x={mid - strikeHalf} y={topPad - 18} textAnchor="end" style={{ fontSize: font - 1, fill: "var(--mint)", letterSpacing: "0.08em" }}>{`PUT ${MODE_NAME[ladder.mode]}`}</text>
            <text x={mid + strikeHalf} y={topPad - 18} style={{ fontSize: font - 1, fill: "var(--cp-danger)", letterSpacing: "0.08em" }}>{`CALL ${MODE_NAME[ladder.mode]}`}</text>
            {ladderRows.map((r) => {
              const y = py(r.strike);
              const pv = pick(r, "put"), cv = pick(r, "call");
              const pw = fin(pv) ? (Math.abs(pv) / ladderScale) * putMax : 0;
              const cw = fin(cv) ? (Math.abs(cv) / ladderScale) * callMax : 0;
              const signed = ladder.mode === "oichg";
              const pc = signed && fin(pv) && pv < 0 ? "var(--amber)" : "var(--mint)";
              const cc = signed && fin(cv) && cv < 0 ? "var(--amber)" : "var(--cp-danger)";
              const strong = (s: number | null) => (s != null && s === ladder.putWall) || (s != null && s === ladder.callWall);
              const pt = ladder.mode !== "oichg" && r.put?.oiChange != null ? (Math.abs(r.put.oiChange) / tickScale) * putMax : 0;
              const ct = ladder.mode !== "oichg" && r.call?.oiChange != null ? (Math.abs(r.call.oiChange) / tickScale) * callMax : 0;
              const sel = r.strike === ladder.selected;
              const tag = r.strike === ladder.putWall ? " P" : r.strike === ladder.callWall ? " C" : "";
              return (
                <g key={`l-${r.strike}`} data-testid="ca-ladder-row" data-strike={r.strike} data-put={pv ?? ""} data-call={cv ?? ""} data-selected={sel ? "true" : "false"}
                  style={{ cursor: "pointer" }} onClick={() => ladder.onSelect(r.strike)}>
                  <title>{`${r.strike} · put ${ladderTxt(r.put, ladder.mode)} · call ${ladderTxt(r.call, ladder.mode)}`}</title>
                  <rect x={lx0} y={y - rowH / 2} width={ladderW - 6} height={rowH} style={{ fill: sel ? "var(--indigo-soft)" : r.strike === ladder.atm ? "var(--cp-line)" : "transparent" }} />
                  <rect x={mid - strikeHalf - pw} y={y - rowH * 0.3} width={pw} height={rowH * 0.56} rx={1.5} style={{ fill: pc }} opacity={signed ? 0.9 : strong(r.strike) && r.strike === ladder.putWall ? 1 : 0.45} />
                  <rect x={mid + strikeHalf} y={y - rowH * 0.3} width={cw} height={rowH * 0.56} rx={1.5} style={{ fill: cc }} opacity={signed ? 0.9 : strong(r.strike) && r.strike === ladder.callWall ? 1 : 0.45} />
                  {pt > 0 && <rect x={mid - strikeHalf - pt} y={y + rowH * 0.3} width={pt} height={2.5} style={{ fill: (r.put?.oiChange ?? 0) >= 0 ? "var(--mint)" : "var(--amber)" }} />}
                  {ct > 0 && <rect x={mid + strikeHalf} y={y + rowH * 0.3} width={ct} height={2.5} style={{ fill: (r.call?.oiChange ?? 0) >= 0 ? "var(--cp-danger)" : "var(--amber)" }} />}
                  <text x={mid} y={y + 3.5} textAnchor="middle" style={{ fontSize: Math.min(font, rowH * 0.8), fontWeight: r.strike === ladder.atm ? 600 : 400, fill: r.strike === ladder.atm ? "var(--cp-ink)" : "var(--cp-ink-2)" }}>{`${fmtAxis(r.strike)}${tag}`}</text>
                </g>
              );
            })}
            {ladder.mode !== "oichg" && <text x={lx0} y={H - 18} style={{ fontSize: font - 1.5, fill: "var(--cp-ink-3)", fontFamily: "var(--sans)" }}>Bright tick = OI added · amber = OI cut</text>}
            <text x={lx0} y={H - 6} style={{ fontSize: font - 1.5, fill: "var(--cp-ink-4)", fontFamily: "var(--sans)" }}>Buy or sell from the option chain below</text>
          </g>
        )}
        {!ladder && !compact && p.ladderEmpty && (
          <text data-testid="ca-ladder-empty" x={W - 8} y={topPad + 12} textAnchor="end" style={{ fontSize: font - 0.5, fill: "var(--cp-ink-3)", fontFamily: "var(--sans)" }}>{p.ladderEmpty}</text>
        )}
      </svg>
      {viewMoved && (
        <button type="button" data-testid="ca-view-reset" onClick={() => { setSpan(null); setOff(0); }}
          style={{ position: "absolute", top: topPad + 4, left: plotL + 4, cursor: "pointer", fontFamily: "var(--mono)", fontSize: 10.5, letterSpacing: "0.08em", color: "var(--cp-ink-2)", background: "var(--bg-2)", border: "1px solid var(--line-3)", borderRadius: 6, padding: "4px 8px" }}>
          RESET VIEW
        </button>
      )}
    </div>
  );
}

const MODE_NAME: Record<LadderMode, string> = { oi: "OI", oichg: "OI Δ", vol: "VOLUME" };

/** Open interest and volume in lakh (1 L = 1,00,000), the design's unit. */
export function fmtLakh(v: number | null | undefined, signed = false): string {
  if (!fin(v)) return "—";
  const l = v / 1e5;
  const a = Math.abs(l);
  const t = a >= 100 ? a.toFixed(0) : a >= 10 ? a.toFixed(1) : a.toFixed(2);
  return `${signed ? (l >= 0 ? "+" : "−") : l < 0 ? "−" : ""}${t} L`;
}

function ladderTxt(s: LadderRow["put"], mode: LadderMode): string {
  if (!s) return "—";
  return mode === "oi" ? `OI ${fmtLakh(s.oi)}` : mode === "oichg" ? `OI Δ ${fmtLakh(s.oiChange, true)}` : `vol ${fmtLakh(s.volume)}`;
}
