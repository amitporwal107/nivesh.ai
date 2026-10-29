/**
 * Chart Analysis v2 — the chart (the owner's design of 29 Oct, "Nivesh Chart"): one SVG, one time axis, one cursor.
 *
 *   price pane      candles · EMA 20 · CALL WALL / PUT WALL / MAX PAIN dashed lines with tags · WATCH / READY markers on
 *                   top with a dotted drop line · RVOL marker · ✓ under a confirmed bar · event chips at the foot · trade
 *                   lines ENTRY / STOP / TGT (STOP and TGT drag) · the last price tag in the gutter
 *   FUTURES OI      the selected slot's OI per bar (line)
 *   OI Δ PER BAR    the OI change per bar (mint up, red down) around a zero line
 *   BUILD-UP        one tag per window (LB SB SC LU), from the route's own classification
 *   STRIKE LADDER   on the right, on the price axis: put bars to the left, call bars to the right, an OI-Δ tick under
 *                   each (bright = added, amber = cut), P / C on the walls; a click selects the strike
 *
 * Draws only what it is given; every figure comes from the page's routes. Pixel-sized (ResizeObserver) so text stays
 * crisp. Phone: no ladder (the chain below has the strikes) and the latest bars only.
 */
import { useEffect, useMemo, useRef, useState, type KeyboardEvent, type PointerEvent } from "react";
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
}

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
  const compact = p.compact;

  // ── geometry ──
  const ladderW = !compact && p.ladder ? Math.round(Math.min(240, Math.max(190, W * 0.22))) : 0;
  const gutter = compact ? 50 : 56;
  const plotL = compact ? 4 : 8;
  const plotR = W - ladderW - gutter - (ladderW ? 12 : 0);
  const plotW = Math.max(60, plotR - plotL);
  const topPad = 34;                                   // room for the WATCH / READY row and the RVOL row
  const priceH = compact ? 220 : 290;
  const priceBot = topPad + priceH;
  const oiTop = priceBot + 22, oiBot = oiTop + (compact ? 44 : 54);
  const dTop = oiBot + 22, dBot = dTop + (compact ? 44 : 54);
  const bTop = dBot + 8, bH = 16;
  const H = bTop + bH + 6;
  const font = compact ? 9.5 : 10;

  // the latest bars that fit
  const minSlot = compact ? 8 : 6;
  const fit = Math.max(8, Math.floor(plotW / minSlot));
  const start = Math.max(0, p.bars.length - fit);
  const bars = p.bars.slice(start);
  const n = bars.length;
  const slot = plotW / Math.max(1, n);
  const bodyW = Math.max(1.5, Math.min(12, slot * 0.62));
  const x = (i: number) => plotL + slot * (i - start) + slot / 2;   // i is the index in p.bars
  const inView = (i: number) => i >= start && i < p.bars.length;

  // ── price scale ──
  const { lo, hi } = useMemo(() => {
    let a = Infinity, b = -Infinity;
    bars.forEach((c) => { a = Math.min(a, c.low); b = Math.max(b, c.high); });
    if (!Number.isFinite(a)) { a = 0; b = 1; }
    const span = Math.max(b - a, b * 0.01);
    // a level is drawn when it is near the candles; one far away would squash them (it is listed in the legend instead)
    const near = (v: number) => v >= a - span * 0.6 && v <= b + span * 0.6;
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
    return i >= start && i < p.bars.length ? i : null;
  };
  const onMove = (e: PointerEvent<SVGSVGElement>) => {
    const pt = toLocal(e);
    if (drag.current && p.onDrag) { p.onDrag(drag.current, Math.round(pf(Math.min(priceBot, Math.max(topPad, pt.y))) * 20) / 20); return; }
    p.onActive(barAt(pt.x));
  };
  const onKey = (e: KeyboardEvent<SVGSVGElement>) => {
    if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
    e.preventDefault();
    const cur = p.active ?? p.bars.length - 1;
    p.onActive(Math.min(p.bars.length - 1, Math.max(start, cur + (e.key === "ArrowLeft" ? -1 : 1))));
  };

  // ── futures panes ──
  const oiVals = (p.fut?.oi ?? []).slice(start).filter(fin);
  const oiLo = oiVals.length ? Math.min(...oiVals) : 0, oiHi = oiVals.length ? Math.max(...oiVals) : 1;
  const oy = (v: number) => oiBot - 4 - ((v - oiLo) / ((oiHi - oiLo) || Math.abs(oiHi) || 1)) * (oiBot - oiTop - 14);
  const oiPath = (() => {
    if (!p.fut) return "";
    let d = "", pen = false;
    for (let i = start; i < p.bars.length; i += 1) {
      const v = p.fut.oi[i];
      if (!fin(v)) { pen = false; continue; }
      d += `${pen ? "L" : "M"}${x(i).toFixed(1)},${oy(v).toFixed(1)}`;
      pen = true;
    }
    return d;
  })();
  const chg = (p.fut?.change ?? []).slice(start);
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

  return (
    <div ref={ref} data-testid="ca-chart" data-bars={n} className="min-w-0" style={{ width: "100%", position: "relative" }}>
      <svg ref={svgRef} data-testid="ca-chart-svg" width={W} height={H} viewBox={`0 0 ${W} ${H}`} role="img" tabIndex={0}
        aria-label="Price, futures open interest, build-up and the strike ladder; use the left and right arrow keys to move the cursor"
        style={{ display: "block", touchAction: drag.current ? "none" : "pan-y", outline: "none", fontFamily: MONO }}
        onPointerMove={onMove} onPointerLeave={() => { if (!drag.current) p.onActive(null); }}
        onPointerUp={() => { drag.current = null; }} onPointerCancel={() => { drag.current = null; }} onKeyDown={onKey}>
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

        {/* candles */}
        {bars.map((c, k) => {
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

        {/* EMA 20 */}
        {(() => {
          let d = "", pen = false;
          for (let i = start; i < p.bars.length; i += 1) {
            const v = p.ema[i];
            if (!fin(v) || !onScale(v)) { pen = false; continue; }
            d += `${pen ? "L" : "M"}${x(i).toFixed(1)},${py(v).toFixed(1)}`;
            pen = true;
          }
          return d ? <path data-testid="ca-ema" d={d} fill="none" style={{ stroke: "var(--cp-indigo)" }} strokeWidth={1.4} opacity={0.8} /> : null;
        })()}

        {/* confirmation ✓ under the bar */}
        {p.confirms.filter(inView).map((i) => (
          <g key={`cf-${i}`} data-testid="ca-confirm" data-i={i}>
            <circle cx={x(i)} cy={Math.min(priceBot - 6, py(p.bars[i].low) + 11)} r={6} style={{ fill: "var(--bg-1)", stroke: "var(--mint)" }} />
            <text x={x(i)} y={Math.min(priceBot - 6, py(p.bars[i].low) + 11) + 3.5} textAnchor="middle" style={{ fontSize: 9, fontWeight: 600, fill: "var(--mint)" }}>✓</text>
          </g>
        ))}

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

        {/* clicks on the price pane set the entry (under the trade lines, so their drag handles win) */}
        <rect data-testid="ca-price-hit" x={plotL} y={topPad} width={plotW} height={priceH} fill="transparent" style={{ cursor: p.onPriceClick ? "crosshair" : "default" }}
          onClick={(e) => { if (p.onPriceClick) p.onPriceClick(Math.round(pf(toLocal(e).y) * 20) / 20); }} />

        {/* trade lines: ENTRY / STOP / TGT, the tag at the right of the plot; STOP and TGT drag */}
        {p.tradeLines.filter((t) => onScale(t.value)).map((t) => {
          const txt = `${t.label} ${fmtPx(t.value)}`;
          const w = txt.length * (font * 0.62) + 12;
          const y = py(t.value);
          return (
            <g key={`tl-${t.key}`} data-testid="ca-tradeline" data-key={t.key} data-value={t.value}>
              <line x1={plotL} x2={plotR} y1={y} y2={y} style={{ stroke: t.color, pointerEvents: "none" }} strokeWidth={1.3} strokeDasharray="6 4" />
              <rect x={plotR - w - 2} y={y - 7.5} width={w} height={15} rx={3} style={{ fill: t.color, pointerEvents: "none" }} />
              <text x={plotR - 2 - w / 2} y={y + 3.5} textAnchor="middle" style={{ fontSize: font - 1, fontWeight: 600, fill: "var(--bg-0)", pointerEvents: "none" }}>{txt}</text>
              {t.drag && p.onDrag && (
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
        {p.buildups.filter((b) => b.i1 >= start).map((b, k) => {
          const x0 = plotL + slot * (Math.max(b.i0, start) - start) + 1;
          const x1 = plotL + slot * (b.i1 - start + 1) - 1;
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
