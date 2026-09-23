/**
 * The Lightweight Charts v5 workspace (§38.4–§38.7): the price pane with its in-chart legend and crosshair
 * tooltip, a volume pane, one pane per oscillator, pattern overlays, the S/R band layer and the manual-drawing
 * primitive. One imperative chart instance per mount; React state flows IN via props and OUT via callbacks — the
 * library owns the canvas, not React.
 *
 * Chart type (§38.7): the candlestick series is ALWAYS the primary series — it holds the data, the price scale,
 * the pattern/drawing primitives and the S/R price lines. Line, area and OHLC-bar types draw an extra series on
 * top and paint the candles transparent rather than swapping the primary series out, so nothing has to be
 * detached and re-attached (and a primitive can never end up pointing at a removed series). Heikin-Ashi is the
 * same candlestick series fed transformed bars, labelled in the UI as a transform (§38.7 P1).
 *
 * Panes (§38.5): the caller owns pane order, collapse state and heights; this component rebuilds the chart's
 * panes from that list whenever it changes. A collapsed pane is not created at all — it renders as a strip with a
 * sparkline instead, exactly as the 1A design shows.
 */
import { forwardRef, useCallback, useEffect, useImperativeHandle, useMemo, useRef, useState } from "react";
import {
  createChart, AreaSeries, BarSeries, CandlestickSeries, HistogramSeries, LineSeries,
  LineStyle, CrosshairMode, PriceScaleMode,
  type IChartApi, type ISeriesApi, type SeriesType, type Time, type IPriceLine, type MouseEventParams,
} from "lightweight-charts";
import { DrawingsPrimitive, type DrawingPoint } from "./primitives";
import { PatternsPrimitive } from "./patternLayer";
import { BandsPrimitive } from "./bandLayer";
import { resolveTheme, useAppTheme, withAlpha, type ChartTheme } from "./theme";
import Legend, { type LegendIndicatorRow } from "./workspace/Legend";
import { PaneControls, PaneDivider } from "./workspace/PaneControls";
import { magnetSnapToBar } from "./workspace/magnet";
import type { ChartType, ScaleMode } from "./workspace/types";
import type { VisibleRange } from "./workspace/ranges";
import {
  type Bar, type IndicatorSeries, type Pattern, type Drawing, type NewDrawing, type SrBand, type NearestLevel,
  plotColumns, patternWindow, patternTypeLabel, statusLabel, knownMarkerDate, heikinAshi, num as fmtNum, price as fmtPrice,
  type IndicatorCatalogue,
} from "./contract";

export interface ChartCanvasHandle {
  fit: () => void;
  toggleFullscreen: () => void;
  cancelPending: () => void;
}

/** One stacked pane, in display order. `price` is always first and is never removed (§38.5). */
export interface PaneSpec {
  id: string;
  title: string;
  kind: "price" | "volume" | "indicator";
  /** Indicator ids drawn in this pane (empty for price/volume). */
  indicatorIds: string[];
  collapsed: boolean;
  height: number;
}

export type ActiveTool = "select" | "trendline" | "horizontal_line";

interface Props {
  symbol: string;
  exchange: string;
  /** Display label for the legend, e.g. "1D". */
  timeframeLabel: string;
  bars: Bar[];
  /** Dates the API flagged as not-yet-complete (weekly/monthly trailing bar, §38.4). */
  incompleteDates: Set<string>;
  chartType: ChartType;
  scaleMode: ScaleMode;

  indicators: Record<string, IndicatorSeries>;
  /** Indicators the user has switched on, in the order they were switched on. */
  selectedIndicatorIds: string[];
  /** A subset of the above, temporarily hidden from the chart but still listed in the legend (§38.4). */
  hiddenIndicatorIds: string[];
  panes: PaneSpec[];
  onMovePane: (paneId: string, direction: -1 | 1) => void;
  onToggleMaximisePane: (paneId: string) => void;
  onTogglePaneCollapsed: (paneId: string) => void;
  onRemovePane: (paneId: string) => void;
  onPaneHeightChange: (paneId: string, height: number) => void;
  maximisedPaneId: string | null;

  /** Already filtered to the active chip (contract.ts matchesPatternFilter) — every one drawn automatically (AC18). */
  patterns: Pattern[];
  /** Whether the symbol has ANY chart pattern at all (independent of the active filter) — drives the on-chart empty state (AC22). */
  hasAnyPatterns: boolean;
  selectedPatternId: string | null;
  onSelectPattern: (hitIds: string[]) => void;
  onHoverPattern: (p: Pattern | null) => void;

  /** SUPPORT_RESISTANCE records, grouped into bands (contract.ts groupSrBands) and drawn by the S/R layer. */
  srBands: SrBand[];
  showLevels: boolean;
  selectedSrBandId: string | null;
  onSelectSrBand: (id: string | null) => void;
  /** §38.15 item 9 — rendered in the chart's right lane, as in the 1A design. */
  nearestLevel: NearestLevel | null;

  drawings: Drawing[];
  activeTool: ActiveTool;
  selectedDrawingId: string | null;
  onSelectDrawing: (id: string | null) => void;
  onCreateDrawing: (d: NewDrawing) => void;
  onBarClick: (bar: Bar) => void;
  magnetOn: boolean;
  drawingsHidden: boolean;
  drawingsLocked: boolean;

  /** Set by a bottom-bar range preset; re-applied whenever the object identity changes. */
  visibleRange: VisibleRange | null;

  /** The catalogue this snapshot was built with. Only used for the reference bands an indicator
   *  defines (§38.5) — the chart never invents a level. */
  catalogue: IndicatorCatalogue | null;

  statusBadge?: React.ReactNode;
  onHideIndicator: (id: string) => void;
  onRemoveIndicator: (id: string) => void;
  onOpenIndicatorProvenance: (id: string) => void;
}

const TOOL_TO_DRAWING = { trendline: "TRENDLINE", horizontal_line: "HORIZONTAL_LINE" } as const;
const INDICATOR_PALETTE_KEYS = ["mint", "amber", "danger", "ink3"] as const;

const ChartCanvas = forwardRef<ChartCanvasHandle, Props>(function ChartCanvas(props, ref) {
  const {
    bars, incompleteDates, chartType, scaleMode, indicators, selectedIndicatorIds, hiddenIndicatorIds, panes,
    patterns, hasAnyPatterns, selectedPatternId, srBands, showLevels, selectedSrBandId, nearestLevel,
    drawings, activeTool, selectedDrawingId, drawingsHidden, drawingsLocked, visibleRange, maximisedPaneId,
    catalogue,
  } = props;

  const containerRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candleRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const primitiveRef = useRef<DrawingsPrimitive | null>(null);
  const patternsPrimitiveRef = useRef<PatternsPrimitive | null>(null);
  const themeRef = useRef<ChartTheme | null>(null);
  const pendingFirstRef = useRef<DrawingPoint | null>(null);
  const [hover, setHover] = useState<{ pattern: Pattern; x: number; y: number } | null>(null);
  const [crosshair, setCrosshair] = useState<{ date: string; x: number; y: number } | null>(null);
  const [legendCollapsed, setLegendCollapsed] = useState(false);

  // Always-current props for the handlers, which are bound once at chart-creation time.
  const propsRef = useRef(props);
  propsRef.current = props;

  const { colors } = useAppTheme();

  /** The bars actually drawn: Heikin-Ashi is a display transform over the same served bars (§38.7). */
  const drawnBars = useMemo(() => (chartType === "heikin_ashi" ? heikinAshi(bars) : bars), [bars, chartType]);

  /** The bar the legend/tooltip describes: the crosshair's bar, else the last one (§38.4). */
  const activeBar = useMemo(() => {
    if (crosshair) {
      const found = bars.find((b) => b[0] === crosshair.date);
      if (found) return found;
    }
    return bars.length ? bars[bars.length - 1] : null;
  }, [bars, crosshair]);

  const previousClose = useMemo(() => {
    if (!activeBar) return null;
    const i = bars.findIndex((b) => b[0] === activeBar[0]);
    return i > 0 ? bars[i - 1][4] : null;
  }, [bars, activeBar]);

  /** seriesId -> the reference bands its catalogue entry defines, if any (§38.5). */
  const bandsBySeries = useMemo(() => {
    const out = new Map<string, { bands: Array<{ value: number; label: string }>; fill: { from: number; to: number } | null }>();
    for (const ind of catalogue?.indicators ?? []) {
      if (!ind.reference_bands?.length && !ind.band_fill) continue;
      for (const preset of ind.presets) {
        out.set(preset.series_id, { bands: ind.reference_bands ?? [], fill: ind.band_fill ?? null });
      }
    }
    return out;
  }, [catalogue]);

  const indicatorColour = useCallback((id: string): string => {
    const i = selectedIndicatorIds.indexOf(id);
    const key = INDICATOR_PALETTE_KEYS[(i < 0 ? 0 : i) % INDICATOR_PALETTE_KEYS.length];
    return colors[key];
  }, [selectedIndicatorIds, colors]);

  /** Value(s) of one indicator at a date — the same rows the chart plots, never a recomputation. */
  const indicatorValuesAt = useCallback((id: string, date: string | null): Array<{ label?: string; value: string }> => {
    const ind = indicators[id];
    if (!ind || !ind.values.length) return [];
    const row = (date ? ind.values.find((r) => r[0] === date) : undefined) ?? ind.values[ind.values.length - 1];
    const cols = plotColumns(ind);
    return cols.map(({ field, col }) => ({
      label: cols.length > 1 ? field.replace(/^bb_/, "") : undefined,
      value: fmtNum(row[col]),
    }));
  }, [indicators]);

  const legendRows: LegendIndicatorRow[] = useMemo(() => selectedIndicatorIds.map((id) => {
    const hidden = hiddenIndicatorIds.includes(id);
    return {
      id,
      name: id,
      params: hidden ? "hidden" : undefined,
      values: indicatorValuesAt(id, activeBar?.[0] ?? null),
      color: hidden ? undefined : indicatorColour(id),
    };
  }), [selectedIndicatorIds, hiddenIndicatorIds, indicatorValuesAt, activeBar, indicatorColour]);

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

    const primitive = new DrawingsPrimitive();
    primitive.setTheme(theme.ink, theme.mint);
    candle.attachPrimitive(primitive);
    primitiveRef.current = primitive;

    const patternsPrimitive = new PatternsPrimitive();
    patternsPrimitive.setTheme(theme);
    candle.attachPrimitive(patternsPrimitive);
    patternsPrimitiveRef.current = patternsPrimitive;

    /** A clicked band within HIT_PX of its drawn price line — a price-space tolerance derived from the two nearby
     *  pixel rows, since S/R bands are native createPriceLine (full-width) rather than a hand-drawn primitive. */
    const hitTestSrBand = (y: number): string | null => {
      const p = propsRef.current;
      if (!p.showLevels || !p.srBands.length) return null;
      const priceAtHitPx = candle.coordinateToPrice(y - 8);
      const priceAtY = candle.coordinateToPrice(y);
      if (priceAtHitPx == null || priceAtY == null) return null;
      const tolerance = Math.abs(priceAtHitPx - priceAtY);
      let best: { id: string; d: number } | null = null;
      for (const b of p.srBands) {
        const d = Math.abs(b.price - priceAtY);
        if (d <= tolerance && (!best || d < best.d)) best = { id: b.id, d };
      }
      return best?.id ?? null;
    };

    const clickHandler = (param: MouseEventParams<Time>) => {
      const p = propsRef.current;
      if (!param.point) return;
      // The click may land in an indicator pane; drawings and patterns live in the price pane only.
      if (param.paneIndex != null && param.paneIndex !== 0) return;

      if (p.activeTool !== "select") {
        if (p.drawingsLocked) return;
        if (!param.time) return;
        const rawPrice = candle.coordinateToPrice(param.point.y);
        if (rawPrice == null) return;
        const date = String(param.time);
        // §38.6 magnet: snap the anchor to the nearest O/H/L/C of the bar under the pointer. The snap uses the
        // SERVED bar, never the Heikin-Ashi transform, so a saved anchor always refers to a real traded price.
        const barAt = p.bars.find((b) => b[0] === date);
        const priceVal = p.magnetOn && barAt ? magnetSnapToBar(barAt, rawPrice).price : rawPrice;

        if (p.activeTool === "horizontal_line") {
          p.onCreateDrawing({
            symbol: p.symbol, timeframe: "daily", drawing_type: TOOL_TO_DRAWING.horizontal_line,
            anchor_points: [{ date, price: priceVal }],
          });
          return;
        }
        // A trendline needs two clicks — the first is held as a live pending preview.
        if (!pendingFirstRef.current) {
          pendingFirstRef.current = { time: param.time, price: priceVal };
          primitive.setPending({ type: "TRENDLINE", points: [pendingFirstRef.current] });
        } else {
          const first = pendingFirstRef.current;
          pendingFirstRef.current = null;
          primitive.setPending(null);
          p.onCreateDrawing({
            symbol: p.symbol, timeframe: "daily", drawing_type: TOOL_TO_DRAWING.trendline,
            anchor_points: [{ date: String(first.time), price: first.price }, { date, price: priceVal }],
          });
        }
        return;
      }

      // Select mode, in priority order: manual drawings, then chart-pattern shapes (§38.15 click-to-select), then
      // S/R bands (AC24), and only then the existing bar-provenance fallback for a genuinely empty click.
      if (!p.drawingsLocked && !p.drawingsHidden) {
        const hitId = primitive.hitTestDrawing(param.point.x, param.point.y);
        if (hitId) { p.onSelectDrawing(hitId); return; }
      }

      const patternHits = patternsPrimitive.hitTestPatterns(param.point.x, param.point.y);
      if (patternHits.length) { p.onSelectPattern(patternHits); return; }

      const bandId = hitTestSrBand(param.point.y);
      if (bandId) { p.onSelectSrBand(bandId); return; }

      p.onSelectDrawing(null);
      p.onSelectPattern([]);
      p.onSelectSrBand(null);
      if (param.time) {
        const bar = p.bars.find((b) => b[0] === param.time);
        if (bar) p.onBarClick(bar);
      }
    };
    chart.subscribeClick(clickHandler);

    const crosshairHandler = (param: MouseEventParams<Time>) => {
      const p = propsRef.current;
      if (!param.point || !param.time) {
        setCrosshair(null);
        setHover(null);
        p.onHoverPattern(null);
        return;
      }
      setCrosshair({ date: String(param.time), x: param.point.x, y: param.point.y });
      const inPricePane = param.paneIndex == null || param.paneIndex === 0;
      const hits = inPricePane ? patternsPrimitive.hitTestPatterns(param.point.x, param.point.y) : [];
      const pattern = hits.length ? p.patterns.find((x) => x.pattern_id === hits[0]) ?? null : null;
      if (pattern) { setHover({ pattern, x: param.point.x, y: param.point.y }); p.onHoverPattern(pattern); }
      else { setHover(null); p.onHoverPattern(null); }
    };
    chart.subscribeCrosshairMove(crosshairHandler);

    // Test hook: the chart's own visible time range, so a Playwright test can assert a selected pattern actually
    // zoomed the view (§38.15 "the view zooms to the pattern's window") without reaching into canvas pixels.
    // Time may come back as a plain "YYYY-MM-DD" string OR a {year,month,day} BusinessDay object depending on how
    // the library classified the series' time values -- normalised to "YYYY-MM-DD" either way so a test can compare
    // it lexicographically, same as every other ISO date string on this screen.
    const timeToIso = (t: Time | undefined): string => {
      if (t == null) return "";
      if (typeof t === "string") return t;
      if (typeof t === "number") return String(t);
      const bd = t as { year: number; month: number; day: number };
      return `${bd.year}-${String(bd.month).padStart(2, "0")}-${String(bd.day).padStart(2, "0")}`;
    };
    const updateVisibleRange = () => {
      const range = chart.timeScale().getVisibleRange();
      const c = containerRef.current;
      if (c) { c.dataset.visibleFrom = range ? timeToIso(range.from) : ""; c.dataset.visibleTo = range ? timeToIso(range.to) : ""; }
    };
    chart.timeScale().subscribeVisibleTimeRangeChange(updateVisibleRange);
    updateVisibleRange();

    return () => {
      chart.unsubscribeClick(clickHandler);
      chart.unsubscribeCrosshairMove(crosshairHandler);
      chart.timeScale().unsubscribeVisibleTimeRangeChange(updateVisibleRange);
      chart.remove();
      chartRef.current = null; candleRef.current = null; primitiveRef.current = null; patternsPrimitiveRef.current = null;
    };
    // Intentionally mount-only: the chart instance is created once and reused across symbol/data changes below.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useImperativeHandle(ref, () => ({
    fit: () => chartRef.current?.timeScale().fitContent(),
    toggleFullscreen: () => {
      const el = containerRef.current?.parentElement;
      if (!el) return;
      if (document.fullscreenElement) void document.exitFullscreen();
      else void el.requestFullscreen?.();
    },
    cancelPending: () => { pendingFirstRef.current = null; primitiveRef.current?.setPending(null); },
  }), []);

  // ── D-6: follow the app theme live, without remounting the chart (AC12) ──
  useEffect(() => {
    const chart = chartRef.current, candle = candleRef.current;
    if (!chart || !candle) return;
    themeRef.current = colors;
    chart.applyOptions({
      layout: { background: { color: colors.bg1 }, textColor: colors.ink3 },
      grid: { vertLines: { color: colors.line }, horzLines: { color: colors.line } },
      rightPriceScale: { borderColor: colors.line },
      timeScale: { borderColor: colors.line },
    });
    primitiveRef.current?.setTheme(colors.ink, colors.mint);
    patternsPrimitiveRef.current?.setTheme(colors);
    const c = containerRef.current;
    if (c) c.dataset.chartBg = colors.bg1;
  }, [colors]);

  // ── candle data + chart-type styling ────────────────────────────────────
  useEffect(() => {
    const candle = candleRef.current;
    if (!candle) return;
    candle.setData(drawnBars.map(([date, o, h, l, c]) => ({ time: date as Time, open: o, high: h, low: l, close: c })));
    chartRef.current?.timeScale().fitContent();
  }, [drawnBars]);

  useEffect(() => {
    const candle = candleRef.current;
    if (!candle) return;
    const t = colors;
    // Line/area/OHLC-bar types draw their own series (below) and paint the candles out — the candlestick series
    // stays as the data + primitive host so nothing is ever detached from a removed series.
    const invisible = chartType === "line" || chartType === "area" || chartType === "bars";
    if (invisible) {
      candle.applyOptions({
        upColor: "rgba(0,0,0,0)", downColor: "rgba(0,0,0,0)", borderVisible: false,
        wickUpColor: "rgba(0,0,0,0)", wickDownColor: "rgba(0,0,0,0)", lastValueVisible: false, priceLineVisible: false,
      });
    } else if (chartType === "hollow_candles") {
      candle.applyOptions({
        upColor: "rgba(0,0,0,0)", downColor: t.danger, borderVisible: true,
        borderUpColor: t.mint, borderDownColor: t.danger,
        wickUpColor: t.mint, wickDownColor: t.danger, lastValueVisible: true, priceLineVisible: true,
      });
    } else {
      candle.applyOptions({
        upColor: t.mint, downColor: t.danger, borderVisible: false,
        wickUpColor: t.mint, wickDownColor: t.danger, lastValueVisible: true, priceLineVisible: true,
      });
    }
    const c = containerRef.current;
    if (c) c.dataset.seriesType = chartType;
  }, [chartType, colors]);

  // ── the extra series for line / area / OHLC bars ─────────────────────────
  useEffect(() => {
    const chart = chartRef.current;
    if (!chart) return;
    if (chartType !== "line" && chartType !== "area" && chartType !== "bars") return;
    let series: ISeriesApi<SeriesType> | null = null;
    if (chartType === "bars") {
      const s = chart.addSeries(BarSeries, { upColor: colors.mint, downColor: colors.danger, thinBars: false }, 0);
      s.setData(drawnBars.map(([date, o, h, l, c]) => ({ time: date as Time, open: o, high: h, low: l, close: c })));
      series = s;
    } else if (chartType === "line") {
      const s = chart.addSeries(LineSeries, { color: colors.mint, lineWidth: 2 }, 0);
      s.setData(drawnBars.map(([date, , , , c]) => ({ time: date as Time, value: c })));
      series = s;
    } else {
      const s = chart.addSeries(AreaSeries, { lineColor: colors.mint, topColor: withAlpha(colors.mint, 0.28), bottomColor: withAlpha(colors.mint, 0.02), lineWidth: 2 }, 0);
      s.setData(drawnBars.map(([date, , , , c]) => ({ time: date as Time, value: c })));
      series = s;
    }
    return () => { if (series) { try { chart.removeSeries(series); } catch { /* chart may already be torn down */ } } };
  }, [chartType, drawnBars, colors]);

  // ── price-scale mode (§38.7) ─────────────────────────────────────────────
  useEffect(() => {
    const chart = chartRef.current;
    if (!chart) return;
    const mode = scaleMode === "log" ? PriceScaleMode.Logarithmic : scaleMode === "percent" ? PriceScaleMode.Percentage : PriceScaleMode.Normal;
    try { chart.priceScale("right").applyOptions({ mode, autoScale: true }); } catch { /* scale may not exist yet */ }
    const c = containerRef.current;
    if (c) c.dataset.scaleMode = scaleMode;
  }, [scaleMode]);

  // ── a bottom-bar range preset ────────────────────────────────────────────
  useEffect(() => {
    const chart = chartRef.current;
    if (!chart || !visibleRange) return;
    try { chart.timeScale().setVisibleRange({ from: visibleRange.from as Time, to: visibleRange.to as Time }); } catch { /* out-of-range dates */ }
  }, [visibleRange]);

  // ── panes: volume + indicator panes, rebuilt from the caller's ordered list ──
  // Full rebuild on every change rather than incremental diffing — pane counts are small, and rebuilding keeps
  // pane-index bookkeeping (which shifts on removePane) simple and correct.
  useEffect(() => {
    const chart = chartRef.current, theme = themeRef.current;
    if (!chart || !theme) return;
    const createdSeries: ISeriesApi<SeriesType>[] = [];
    const createdPanes: number[] = [];
    const createdBands: Array<{ series: ISeriesApi<SeriesType>; primitive: BandsPrimitive }> = [];
    const visible = selectedIndicatorIds.filter((id) => !hiddenIndicatorIds.includes(id));

    const addIndicator = (id: string, paneIdx: number) => {
      const ind = indicators[id];
      if (!ind) return;
      const colour = indicatorColour(id);
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
    };

    // The panes that actually exist in the chart, in chart-pane-index order: price is always index 0, then each
    // non-collapsed pane in the caller's order. Keeping this list is what makes maximise and resize address the
    // right pane — a collapsed pane has no chart pane at all, so indices would otherwise drift.
    const live: PaneSpec[] = [];
    for (const spec of panes) {
      if (spec.kind === "price") {
        for (const id of spec.indicatorIds) if (visible.includes(id)) addIndicator(id, 0);
        live.push(spec);
        continue;
      }
      if (spec.collapsed) continue;
      if (spec.kind === "indicator" && !spec.indicatorIds.some((id) => visible.includes(id))) continue;
      let paneIdx: number;
      try { paneIdx = chart.addPane().paneIndex(); } catch { continue; }
      createdPanes.push(paneIdx);
      if (spec.kind === "volume") {
        const volume = chart.addSeries(HistogramSeries, { priceFormat: { type: "volume" }, color: theme.ink4, title: "Volume" }, paneIdx);
        volume.setData(bars.map(([date, o, , , c, v]) => ({ time: date as Time, value: v, color: withAlpha(c >= o ? theme.mint : theme.danger, 0.55) })));
        createdSeries.push(volume);
      } else {
        for (const id of spec.indicatorIds) if (visible.includes(id)) addIndicator(id, paneIdx);
        // §38.5 reference bands, drawn inside this pane only. Attached to the pane's first series,
        // since a series primitive draws in the pane its series belongs to.
        const banded = spec.indicatorIds.find((id) => visible.includes(id) && bandsBySeries.has(id));
        const paneSeries = banded ? createdSeries[createdSeries.length - 1] : null;
        if (banded && paneSeries) {
          const def = bandsBySeries.get(banded)!;
          const primitive = new BandsPrimitive();
          try {
            paneSeries.attachPrimitive(primitive);
            primitive.set(def.bands, def.fill, withAlpha(theme.ink4, 0.85), withAlpha(theme.ink4, 0.10));
            createdBands.push({ series: paneSeries, primitive });
          } catch { /* a pane the library refused to build has nothing to band */ }
        }
      }
      live.push(spec);
    }

    // Sizing, after every pane exists: maximise is a stretch-factor split (the library owns the arithmetic),
    // a normal layout uses each pane's own pixel height and lets the price pane take what is left.
    const chartPanes = chart.panes();
    live.forEach((spec, idx) => {
      const pane = chartPanes[idx];
      if (!pane) return;
      try {
        if (maximisedPaneId) pane.setStretchFactor(spec.id === maximisedPaneId ? 20 : 1);
        else if (spec.kind !== "price") pane.setHeight(spec.height);
      } catch { /* the library refuses impossible heights — the pane still renders at its own size */ }
    });

    // Test/debug hook: the titles of the indicator series actually drawn. A canvas cannot be inspected, and
    // counting <canvas> elements proves a pane exists, not how many lines are inside it.
    const container = containerRef.current;
    if (container) {
      container.dataset.renderedSeries = createdSeries.map((x) => x.options().title).filter((t) => t && t !== "Volume").join(",");
      container.dataset.paneIds = live.map((p) => p.id).join(",");
      // Test hook: which panes drew catalogue reference bands, and at which levels.
      container.dataset.bandLevels = JSON.stringify(
        createdBands.length ? [...bandsBySeries].filter(([id]) => visible.includes(id)).map(([id, d]) => [id, d.bands.map((b) => b.value)]) : [],
      );
      // Test hook: the price pane's own pixel height, so a test that must click at a PRICE can convert a
      // fraction of the price pane into a page coordinate instead of guessing against the whole host.
      try { container.dataset.pricePaneHeight = String(Math.round(chartPanes[0]?.getHeight() ?? 0)); } catch { /* pane not ready */ }
    }

    return () => {
      if (container) { container.dataset.renderedSeries = ""; container.dataset.paneIds = ""; container.dataset.pricePaneHeight = "0"; container.dataset.bandLevels = "[]"; }
      for (const b of createdBands) { try { b.series.detachPrimitive(b.primitive); } catch { /* series already removed */ } }
      for (const s of createdSeries) { try { chart.removeSeries(s); } catch { /* chart may already be torn down */ } }
      for (const idx of [...createdPanes].sort((a, b) => b - a)) { try { chart.removePane(idx); } catch { /* already gone */ } }
    };
  }, [panes, indicators, selectedIndicatorIds, hiddenIndicatorIds, bars, maximisedPaneId, indicatorColour, bandsBySeries, colors]);

  // ── pattern overlays: PatternsPrimitive draws each pattern over its own dates (§38.15, AC19) ──────────────
  useEffect(() => {
    patternsPrimitiveRef.current?.setPatterns(patterns);
    const container = containerRef.current;
    // Test hook (AC18): number of chart patterns actually drawn — must equal the API's count for the active filter,
    // exactly as `data-rendered-levels` already does for S/R lines.
    if (container) container.dataset.renderedPatterns = String(patterns.length);
    // Test hook (AC23): each drawn pattern's own "Known" marker date, as JSON {pattern_id: date} — a canvas
    // dotted line cannot be pixel-inspected, and this is drawn from the same contract.ts knownMarkerDate() the
    // primitive itself uses, so the test asserts the real computed date, not a re-implementation of it.
    if (container) {
      const known: Record<string, string | null> = {};
      for (const p of patterns) known[p.pattern_id] = knownMarkerDate(p);
      container.dataset.knownMarkers = JSON.stringify(known);
    }
    return () => { if (container) { container.dataset.renderedPatterns = "0"; container.dataset.knownMarkers = "{}"; } };
  }, [patterns]);
  useEffect(() => { patternsPrimitiveRef.current?.setSelected(selectedPatternId); }, [selectedPatternId]);

  // ── zoom to the selected pattern's window (formation start -> last event), with a margin (§38.15) ──────────
  useEffect(() => {
    const chart = chartRef.current;
    if (!chart || !selectedPatternId) return;
    const pattern = patterns.find((p) => p.pattern_id === selectedPatternId);
    if (!pattern) return;
    const { start, end } = patternWindow(pattern);
    const idxStart = bars.findIndex((b) => b[0] === start);
    const idxEnd = bars.findIndex((b) => b[0] === end);
    if (idxStart === -1 || idxEnd === -1) return;
    const MARGIN_BARS = 3;
    chart.timeScale().setVisibleLogicalRange({
      from: Math.max(0, idxStart - MARGIN_BARS),
      to: Math.min(bars.length - 1, idxEnd + MARGIN_BARS),
    });
  }, [selectedPatternId, patterns, bars]);

  // ── support & resistance layer: one line per GROUPED band (§38.15 item 8), on by default ─────────────────
  useEffect(() => {
    const candle = candleRef.current, theme = themeRef.current, container = containerRef.current;
    if (!candle || !theme) return;
    const lines: IPriceLine[] = [];
    if (showLevels) {
      for (const b of srBands) {
        const colour = b.kind === "SUPPORT" ? theme.mint : b.kind === "RESISTANCE" ? theme.danger : theme.amber;
        const dim = selectedSrBandId != null && selectedSrBandId !== b.id;
        const countLabel = b.records.length > 1 ? ` · ${b.records.length} levels` : "";
        lines.push(candle.createPriceLine({
          price: b.price, color: withAlpha(colour, dim ? 0.25 : 0.9), lineWidth: selectedSrBandId === b.id ? 2 : 1,
          lineStyle: LineStyle.Solid, axisLabelVisible: true,
          title: `${b.kind === "SUPPORT" ? "S" : b.kind === "RESISTANCE" ? "R" : "S/R"} ${b.price.toFixed(2)}${countLabel}`,
        }));
      }
    }
    // Test/debug hook: how many band lines are drawn (a canvas cannot be inspected).
    if (container) container.dataset.renderedLevels = String(lines.length);
    return () => {
      if (container) container.dataset.renderedLevels = "0";
      for (const l of lines) { try { candle.removePriceLine(l); } catch { /* series may already be gone */ } }
    };
  }, [srBands, showLevels, selectedSrBandId, colors]);

  // ── drawings → primitive ────────────────────────────────────────────────
  useEffect(() => {
    primitiveRef.current?.setSegments(drawings.map((d) => ({
      id: d.drawing_id, type: d.drawing_type, points: d.anchor_points.map((a) => ({ time: a.date as Time, price: a.price })),
    })));
  }, [drawings]);
  useEffect(() => { primitiveRef.current?.setSelected(selectedDrawingId); }, [selectedDrawingId]);
  useEffect(() => { primitiveRef.current?.setHidden(drawingsHidden); }, [drawingsHidden]);
  useEffect(() => {
    if (activeTool === "select") { pendingFirstRef.current = null; primitiveRef.current?.setPending(null); }
  }, [activeTool]);

  const incomplete = activeBar ? incompleteDates.has(activeBar[0]) : false;
  const rsiRow = indicatorValuesAt("rsi_14", activeBar?.[0] ?? null);
  const collapsedPanes = panes.filter((p) => p.collapsed);

  return (
    <div style={{ position: "relative", flex: 1, minHeight: 0, display: "flex", flexDirection: "column", background: "var(--bg-1)" }}>
      <div style={{ position: "relative", flex: 1, minHeight: 0 }}>
        <div ref={containerRef} data-testid="chart-canvas" style={{ width: "100%", height: "100%" }} />

        <Legend
          symbol={props.symbol}
          timeframe={props.timeframeLabel}
          exchange={props.exchange}
          statusBadge={props.statusBadge}
          bar={activeBar}
          previousClose={previousClose}
          incomplete={incomplete}
          indicators={legendRows}
          onHideIndicator={props.onHideIndicator}
          onOpenIndicatorSettings={props.onOpenIndicatorProvenance}
          onRemoveIndicator={props.onRemoveIndicator}
          onOpenIndicatorProvenance={props.onOpenIndicatorProvenance}
          collapsed={legendCollapsed}
          onToggleCollapsed={() => setLegendCollapsed((v) => !v)}
        />

        {/* §38.15 item 9: nearest S/R level or pattern boundary to the last close — a fact, not a signal. In the
            chart's right lane, as in the 1A design, so it can never reflow the toolbar row above the canvas. */}
        {nearestLevel && (
          <div
            data-testid="chart-nearest-level" className="nv-mono"
            style={{
              position: "absolute", top: 8, right: 10, zIndex: 4, fontSize: 10.5, color: "var(--c-ink-3)",
              background: "var(--bg-glass)", border: "1px solid var(--c-line)", borderRadius: 8, padding: "3px 8px",
              pointerEvents: "none", whiteSpace: "nowrap",
            }}
          >
            Nearest: <span data-testid="chart-nearest-level-role">{nearestLevel.role === "SUPPORT" ? "Support" : "Resistance"}</span>{" "}
            ₹<span data-testid="chart-nearest-level-price">{fmtNum(nearestLevel.price)}</span>{" "}
            (<span data-testid="chart-nearest-level-distance-rupees">₹{fmtNum(nearestLevel.distanceRupees)}</span>
            {nearestLevel.distanceAtr != null && <> · <span data-testid="chart-nearest-level-distance-atr">{fmtNum(nearestLevel.distanceAtr)}</span> ATR</>})
          </div>
        )}

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

        {chartType === "heikin_ashi" && (
          <span
            data-testid="chart-transform-badge" className="nv-mono"
            style={{
              position: "absolute", right: 10, bottom: 6, zIndex: 2, fontSize: 9.5, color: "var(--amber)",
              border: "1px solid var(--amber-line)", borderRadius: 999, padding: "1px 7px", background: "var(--bg-1)",
            }}
          >
            HEIKIN-ASHI · CLIENT-SIDE TRANSFORM
          </span>
        )}

        {/* §38.15 / AC22: a symbol with no chart patterns says so ON THE CHART, naming the families checked. */}
        {!hasAnyPatterns && (
          <div
            data-testid="chart-patterns-onchart-empty" role="status"
            style={{
              position: "absolute", bottom: 26, left: 10, maxWidth: 420, fontSize: 11.5, lineHeight: 1.5,
              color: "var(--c-ink-3)", background: "var(--bg-1)", border: "1px solid var(--c-line)", borderRadius: 8,
              padding: "8px 10px", zIndex: 2, pointerEvents: "none",
            }}
          >
            No chart patterns detected — checked: support/resistance, rectangle, higher-high/higher-low
          </div>
        )}

        {/* §38.4: the crosshair tooltip — O/H/L/C, volume and RSI at the hovered bar, from the served payloads.
            It is shown whenever the crosshair is on the chart, including over a pattern shape: §38.4 wants the
            bar readout and §38.15 wants the shape's name, so both are shown and the pattern label is offset
            below this one rather than replacing it. */}
        {crosshair && activeBar && (
          <div
            data-testid="chart-crosshair-tooltip" role="tooltip"
            style={{
              position: "absolute", left: Math.min(crosshair.x + 14, 9999), top: Math.max(crosshair.y - 8, 4), width: 190,
              fontSize: 11, lineHeight: 1.5, color: "var(--c-ink)", background: "var(--bg-glass)",
              border: "1px solid var(--c-line-strong)", borderRadius: 10, padding: "7px 9px", zIndex: 4,
              pointerEvents: "none", backdropFilter: "blur(6px)", fontFamily: "var(--mono)",
            }}
          >
            <div style={{ color: "var(--c-ink-3)", fontSize: 10 }}>{activeBar[0]}</div>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "1px 10px", marginTop: 3 }}>
              <span>O <span data-testid="chart-crosshair-o">{fmtPrice(activeBar[1])}</span></span>
              <span>H <span data-testid="chart-crosshair-h">{fmtPrice(activeBar[2])}</span></span>
              <span>L <span data-testid="chart-crosshair-l">{fmtPrice(activeBar[3])}</span></span>
              <span>C <span data-testid="chart-crosshair-c">{fmtPrice(activeBar[4])}</span></span>
            </div>
            <div style={{ color: "var(--c-ink-3)", marginTop: 3 }}>
              VOL <span data-testid="chart-crosshair-vol">{Math.round(activeBar[5]).toLocaleString("en-IN")}</span>
            </div>
            {rsiRow.length > 0 && (
              <div style={{ color: "var(--c-ink-3)" }}>RSI <span data-testid="chart-crosshair-rsi">{rsiRow[0].value}</span></div>
            )}
          </div>
        )}

        {/* §38.15 "Hovering a shape shows its name, status and dates." */}
        {hover && (
          <div
            data-testid="chart-pattern-hover-tooltip" role="tooltip"
            style={{
              // Offset below the crosshair tooltip when both are on screen, so neither covers the other.
              position: "absolute", left: Math.min(hover.x + 12, 9999),
              top: Math.max(hover.y - 10, 0) + (crosshair ? 120 : 0), maxWidth: 260,
              fontSize: 11, lineHeight: 1.5, color: "var(--c-ink)", background: "var(--bg-2)", border: "1px solid var(--c-line-strong)",
              borderRadius: 8, padding: "6px 9px", zIndex: 5, pointerEvents: "none", boxShadow: "var(--shadow-pop)",
            }}
          >
            <b>{patternTypeLabel(hover.pattern.pattern_type)} · {statusLabel(hover.pattern)}</b>
            <div className="nv-mono" style={{ color: "var(--c-ink-3)" }}>{hover.pattern.formation_start} → {hover.pattern.formation_end}</div>
          </div>
        )}
      </div>

      {/* §38.5 pane controls + the 1A design's collapsed strips. The controls sit in a bar under the chart
          rather than floating inside each pane: a pane's own DOM element belongs to the charting library, and
          reaching into it to host React controls is the kind of coupling that breaks on a library upgrade. */}
      <div data-testid="chart-pane-bar" style={{ borderTop: "1px solid var(--c-line)", background: "var(--bg-1)", display: "grid" }}>
        {panes.map((spec, i) => (
          <div key={spec.id} data-testid={`chart-pane-row-${spec.id}`} style={{ display: "flex", alignItems: "center", gap: 8, padding: "3px 8px", minHeight: 26, borderBottom: i < panes.length - 1 ? "1px solid var(--c-line)" : undefined }}>
            <span className="nv-mono" style={{ fontSize: 10, color: "var(--c-ink-3)", letterSpacing: ".06em", textTransform: "uppercase", minWidth: 74 }}>{spec.title}</span>
            {spec.collapsed && (
              <Sparkline
                values={sparkValues(spec, bars, indicators)}
                color={spec.kind === "volume" ? colors.ink4 : indicatorColour(spec.indicatorIds[0] ?? "")}
                testId={`chart-pane-sparkline-${spec.id}`}
              />
            )}
            <span style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 6 }}>
              {!spec.collapsed && spec.kind !== "price" && (
                <span style={{ display: "block", width: 34, flex: "none" }} title={`Drag to resize the ${spec.title} pane`}>
                  <PaneDivider
                    paneId={spec.id} height={spec.height} minHeight={40} maxHeight={400}
                    onHeightChange={(h) => props.onPaneHeightChange(spec.id, h)}
                    className="chart-pane-divider"
                  />
                </span>
              )}
              <PaneControls
                paneId={spec.id}
                title={spec.title}
                index={i}
                count={panes.length}
                maximised={maximisedPaneId === spec.id}
                collapsed={spec.collapsed}
                canMoveUp={spec.kind !== "price" && i > 1}
                canMoveDown={spec.kind !== "price" && i < panes.length - 1}
                collapsible={spec.kind !== "price"}
                onMoveUp={() => props.onMovePane(spec.id, -1)}
                onMoveDown={() => props.onMovePane(spec.id, 1)}
                onToggleMaximise={() => props.onToggleMaximisePane(spec.id)}
                onToggleCollapse={() => props.onTogglePaneCollapsed(spec.id)}
                onRemove={spec.kind === "indicator" ? () => props.onRemovePane(spec.id) : undefined}
              />
            </span>
          </div>
        ))}
      </div>
      {collapsedPanes.length > 0 && <span className="sr-only" data-testid="chart-collapsed-panes">{collapsedPanes.map((p) => p.id).join(",")}</span>}
    </div>
  );
});

/** The last 40 plotted values of a collapsed pane, for its strip sparkline (design item 6). */
function sparkValues(spec: PaneSpec, bars: Bar[], indicators: Record<string, IndicatorSeries>): number[] {
  if (spec.kind === "volume") return bars.slice(-40).map((b) => b[5]);
  const id = spec.indicatorIds[0];
  const ind = id ? indicators[id] : undefined;
  if (!ind) return [];
  const col = plotColumns(ind)[0]?.col ?? 1;
  return ind.values.slice(-40).map((r) => r[col]).filter((v): v is number => typeof v === "number" && Number.isFinite(v));
}

function Sparkline({ values, color, testId }: { values: number[]; color: string; testId: string }) {
  if (values.length < 2) return null;
  const min = Math.min(...values), max = Math.max(...values);
  const span = max - min || 1;
  const points = values.map((v, i) => `${(i / (values.length - 1)) * 60},${14 - ((v - min) / span) * 12}`).join(" ");
  return (
    <svg data-testid={testId} width={60} height={16} viewBox="0 0 60 16" aria-hidden="true" style={{ flex: "none" }}>
      <polyline points={points} fill="none" stroke={color} strokeWidth={1.2} />
    </svg>
  );
}

export default ChartCanvas;
