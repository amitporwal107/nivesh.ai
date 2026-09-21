/**
 * The Lightweight Charts v5 workspace: candlesticks + volume, indicator overlays/panes, pattern overlays (native
 * price lines + markers), and the manual-drawing primitive (primitives.ts). One imperative chart instance per
 * mount; React state flows IN via props and OUT via callbacks — the library owns the canvas, not React.
 */
import { forwardRef, useEffect, useImperativeHandle, useRef } from "react";
import {
  createChart, CandlestickSeries, HistogramSeries, LineSeries, createSeriesMarkers,
  LineStyle, CrosshairMode,
  type IChartApi, type ISeriesApi, type Time, type SeriesMarker, type IPriceLine, type MouseEventParams,
} from "lightweight-charts";
import { DrawingsPrimitive, type DrawingPoint } from "./primitives";
import { resolveTheme, withAlpha, type ChartTheme } from "./theme";
import { type Bar, type IndicatorSeries, type Pattern, type Drawing, type DrawingType, type NewDrawing, patternVisualCategory, plotColumns } from "./contract";

export interface ChartCanvasHandle {
  fit: () => void;
  toggleFullscreen: () => void;
  cancelPending: () => void;
}

interface Props {
  symbol: string;
  bars: Bar[];
  indicators: Record<string, IndicatorSeries>;
  selectedIndicatorIds: string[];
  patterns: Pattern[];
  visiblePatternIds: Set<string>;
  drawings: Drawing[];
  activeTool: DrawingType | "select";
  selectedDrawingId: string | null;
  onSelectDrawing: (id: string | null) => void;
  onCreateDrawing: (d: NewDrawing) => void;
  onBarClick: (bar: Bar) => void;
}

const ChartCanvas = forwardRef<ChartCanvasHandle, Props>(function ChartCanvas(props, ref) {
  const { bars, indicators, selectedIndicatorIds, patterns, visiblePatternIds, drawings, activeTool, selectedDrawingId } = props;
  const containerRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candleRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const volumeRef = useRef<ISeriesApi<"Histogram"> | null>(null);
  const primitiveRef = useRef<DrawingsPrimitive | null>(null);
  const themeRef = useRef<ChartTheme | null>(null);
  const pendingFirstRef = useRef<DrawingPoint | null>(null);
  // Always-current props for the click handler, which is bound once at chart-creation time.
  const propsRef = useRef(props);
  propsRef.current = props;

  // ── create the chart once per mount ─────────────────────────────────────
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const theme = resolveTheme(el);
    themeRef.current = theme;

    const chart = createChart(el, {
      autoSize: true,
      layout: { background: { color: theme.bg1 }, textColor: theme.ink3 },
      grid: { vertLines: { color: theme.line }, horzLines: { color: theme.line } },
      crosshair: { mode: CrosshairMode.Normal },
      rightPriceScale: { borderColor: theme.line },
      timeScale: { borderColor: theme.line },
      handleScroll: true,
      handleScale: true,
    });
    chartRef.current = chart;

    const candle = chart.addSeries(CandlestickSeries, {
      upColor: theme.mint, downColor: theme.danger, borderVisible: false,
      wickUpColor: theme.mint, wickDownColor: theme.danger,
    });
    candleRef.current = candle;

    // Volume shares the price pane (pane 0) on its own price scale, squeezed into the bottom 18% — the
    // conventional Lightweight Charts volume pattern; addPane() is reserved for indicator panes (task item 3).
    const volume = chart.addSeries(HistogramSeries, { priceFormat: { type: "volume" }, priceScaleId: "chart-volume", color: theme.ink4 });
    volume.priceScale().applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } });
    volumeRef.current = volume;

    const primitive = new DrawingsPrimitive();
    primitive.setTheme(theme.ink, theme.mint);
    candle.attachPrimitive(primitive);
    primitiveRef.current = primitive;

    const clickHandler = (param: MouseEventParams<Time>) => {
      const p = propsRef.current;
      if (!param.point) return;

      if (p.activeTool !== "select") {
        if (!param.time) return;
        const priceVal = candle.coordinateToPrice(param.point.y);
        if (priceVal == null) return;
        if (p.activeTool === "HORIZONTAL_LINE") {
          p.onCreateDrawing({ symbol: p.symbol, timeframe: "daily", drawing_type: "HORIZONTAL_LINE", anchor_points: [{ date: String(param.time), price: priceVal }] });
          return;
        }
        // TRENDLINE needs two clicks — the first is held as a live pending preview.
        if (!pendingFirstRef.current) {
          pendingFirstRef.current = { time: param.time, price: priceVal };
          primitive.setPending({ type: "TRENDLINE", points: [pendingFirstRef.current] });
        } else {
          const first = pendingFirstRef.current;
          pendingFirstRef.current = null;
          primitive.setPending(null);
          p.onCreateDrawing({
            symbol: p.symbol, timeframe: "daily", drawing_type: "TRENDLINE",
            anchor_points: [{ date: String(first.time), price: first.price }, { date: String(param.time), price: priceVal }],
          });
        }
        return;
      }

      // Select mode: hit-test the manual drawings first, then fall back to opening the provenance drawer for the bar.
      const hitId = primitive.hitTestDrawing(param.point.x, param.point.y);
      if (hitId) { p.onSelectDrawing(hitId); return; }
      p.onSelectDrawing(null);
      if (param.time) {
        const bar = p.bars.find((b) => b[0] === param.time);
        if (bar) p.onBarClick(bar);
      }
    };
    chart.subscribeClick(clickHandler);

    return () => {
      chart.unsubscribeClick(clickHandler);
      chart.remove();
      chartRef.current = null; candleRef.current = null; volumeRef.current = null; primitiveRef.current = null;
    };
    // Intentionally mount-only: the chart instance is created once and reused across symbol/data changes below.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useImperativeHandle(ref, () => ({
    fit: () => chartRef.current?.timeScale().fitContent(),
    toggleFullscreen: () => {
      const el = containerRef.current;
      if (!el) return;
      if (document.fullscreenElement) void document.exitFullscreen();
      else void el.requestFullscreen?.();
    },
    cancelPending: () => { pendingFirstRef.current = null; primitiveRef.current?.setPending(null); },
  }), []);

  // ── candle + volume data ────────────────────────────────────────────────
  useEffect(() => {
    const candle = candleRef.current, volume = volumeRef.current, theme = themeRef.current;
    if (!candle || !volume || !theme) return;
    candle.setData(bars.map(([date, o, h, l, c]) => ({ time: date as Time, open: o, high: h, low: l, close: c })));
    volume.setData(bars.map(([date, o, , , c, v]) => ({ time: date as Time, value: v, color: withAlpha(c >= o ? theme.mint : theme.danger, 0.55) })));
    chartRef.current?.timeScale().fitContent();
  }, [bars]);

  // ── indicator overlays / panes ───────────────────────────────────────────
  // Full rebuild on every change rather than incremental diffing — indicator counts are small (a handful of
  // toggles), and rebuild keeps pane-index bookkeeping (which shifts on removePane) simple and correct.
  useEffect(() => {
    const chart = chartRef.current, theme = themeRef.current;
    if (!chart || !theme) return;
    const createdSeries: ISeriesApi<"Line" | "Histogram">[] = [];
    const createdPanes: number[] = [];
    const paneByName = new Map<string, number>();
    const palette = [theme.mint, theme.amber, theme.danger, theme.ink3];
    let colourIdx = 0;

    for (const id of selectedIndicatorIds) {
      const ind = indicators[id];
      if (!ind) continue;
      const colour = palette[colourIdx++ % palette.length];
      let paneIdx = 0;
      if (ind.pane !== "price") {
        let idx = paneByName.get(ind.pane);
        if (idx === undefined) {
          idx = chart.addPane().paneIndex();
          paneByName.set(ind.pane, idx);
          createdPanes.push(idx);
        }
        paneIdx = idx;
      }
      // One series per plotted output field — bollinger draws mid/upper/lower, macd draws macd/signal + hist bars.
      const columns = plotColumns(ind);
      columns.forEach(({ field, col }, k) => {
        const title = columns.length > 1 ? `${id}:${field}` : id;
        const points = ind.values
          .filter((row) => typeof row[col] === "number" && Number.isFinite(row[col] as number))
          .map((row) => ({ time: row[0] as Time, value: row[col] as number }));
        const series = field === "hist"
          ? chart.addSeries(HistogramSeries, { color: withAlpha(colour, 0.5), title, lastValueVisible: false }, paneIdx)
          : chart.addSeries(LineSeries, { color: colour, lineWidth: k === 0 ? 2 : 1, lineStyle: k === 0 ? LineStyle.Solid : LineStyle.Dashed, title, lastValueVisible: true }, paneIdx);
        series.setData(points);
        createdSeries.push(series);
      });
    }

    // Test/debug hook: the titles of the indicator series actually drawn. A canvas cannot be inspected, and
    // counting <canvas> elements proves a pane exists, not how many lines are inside it.
    const container = containerRef.current;
    if (container) container.dataset.renderedSeries = createdSeries.map((x) => x.options().title).join(",");

    return () => {
      if (container) container.dataset.renderedSeries = "";
      for (const s of createdSeries) { try { chart.removeSeries(s); } catch { /* chart may already be torn down */ } }
      for (const idx of [...createdPanes].sort((a, b) => b - a)) { try { chart.removePane(idx); } catch { /* already gone */ } }
    };
  }, [selectedIndicatorIds, indicators]);

  // ── pattern overlays: price lines for levels, markers for pivots/events — B4 visual scheme ──────────────
  useEffect(() => {
    const chart = chartRef.current, candle = candleRef.current, theme = themeRef.current;
    if (!chart || !candle || !theme) return;
    const lines: IPriceLine[] = [];
    const markers: SeriesMarker<Time>[] = [];

    for (const p of patterns.filter((x) => visiblePatternIds.has(x.pattern_id))) {
      const cat = patternVisualCategory(p);
      const style = cat === "invalidated" ? LineStyle.Dotted : cat === "forming" ? LineStyle.Dashed : LineStyle.Solid;
      const stageAlpha = p.stage === "S1" ? 0.4 : p.stage === "S2" ? 0.65 : 0.9;
      const colour = cat === "confirmed" ? theme.mint : cat === "forming" ? withAlpha(theme.mint, stageAlpha) : theme.ink4;

      for (const [label, val] of [
        ["support", p.levels?.support], ["resistance", p.levels?.resistance],
        ["breakout", p.levels?.breakout_level], ["invalidation", p.levels?.invalidation_level],
      ] as const) {
        if (val == null) continue;
        lines.push(candle.createPriceLine({
          price: val, color: colour, lineWidth: cat === "confirmed" ? 2 : 1, lineStyle: style,
          axisLabelVisible: true, title: `${p.pattern_type} ${label}${p.stage ? ` ${p.stage}` : ""}`,
        }));
      }
      for (const piv of p.pivots ?? []) {
        markers.push({
          time: piv.date as Time, position: piv.kind === "LOW" ? "belowBar" : "aboveBar",
          color: colour, shape: piv.kind === "LOW" ? "arrowUp" : "arrowDown",
          text: cat === "forming" && p.stage ? p.stage : undefined,
        });
      }
      for (const ev of p.events ?? []) {
        const t = (ev.event_type || "").toUpperCase();
        if (t.includes("CONFIRM")) markers.push({ time: ev.date as Time, position: "aboveBar", color: theme.mint, shape: p.direction === "BEARISH" ? "arrowDown" : "arrowUp", text: "confirmed" });
        else if (t.includes("FAIL")) markers.push({ time: ev.date as Time, position: "aboveBar", color: theme.ink4, shape: "circle", text: "✕" });
        else if (t.includes("INVALID")) markers.push({ time: ev.date as Time, position: "aboveBar", color: theme.ink4, shape: "circle", text: "⊘" });
      }
    }
    const markersApi = createSeriesMarkers(candle, markers);

    return () => {
      for (const l of lines) { try { candle.removePriceLine(l); } catch { /* series may already be gone */ } }
      try { markersApi.setMarkers([]); } catch { /* series may already be gone */ }
    };
  }, [patterns, visiblePatternIds]);

  // ── drawings → primitive ────────────────────────────────────────────────
  useEffect(() => {
    primitiveRef.current?.setSegments(drawings.map((d) => ({
      id: d.drawing_id, type: d.drawing_type, points: d.anchor_points.map((a) => ({ time: a.date as Time, price: a.price })),
    })));
  }, [drawings]);
  useEffect(() => { primitiveRef.current?.setSelected(selectedDrawingId); }, [selectedDrawingId]);
  useEffect(() => {
    if (activeTool === "select") { pendingFirstRef.current = null; primitiveRef.current?.setPending(null); }
  }, [activeTool]);

  return (
    <div style={{ position: "relative", width: "100%", height: 480, borderRadius: 12, overflow: "hidden", border: "1px solid var(--c-line)" }}>
      <div ref={containerRef} data-testid="chart-canvas" style={{ width: "100%", height: "100%" }} />
      {/* Required by the Lightweight Charts licence — a visible attribution in the chart area (TC-21). */}
      <a
        href="https://www.tradingview.com/" target="_blank" rel="noreferrer" data-testid="chart-tv-attribution"
        style={{
          position: "absolute", left: 8, bottom: 6, fontSize: 10.5, fontFamily: "var(--mono)", color: "var(--c-ink-4)",
          textDecoration: "none", background: "var(--bg-1)", padding: "2px 6px", borderRadius: 6, opacity: 0.85, zIndex: 2,
        }}
      >
        Charts by TradingView
      </a>
    </div>
  );
});

export default ChartCanvas;
