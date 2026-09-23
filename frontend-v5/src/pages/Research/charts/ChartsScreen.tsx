/**
 * Research → Charts. Read-only over the committed chart snapshot (research/charting/SNAPSHOT_SCHEMA.md) — nothing
 * on this screen is computed client-side except the two declared display transforms (Heikin-Ashi candles and the
 * S/R banding); a field the snapshot doesn't have renders as "—", never a guess (the SimulationLabScreen
 * convention). Kite-derived data, owner-only (NI-1): gated by `require_feature("charting")`.
 *
 * Layout (§38.3–§38.8, `.claude/workspace/charting-pattern-engine/design-1a-reference.md`): a watchlist column, a
 * 56 px top bar, a 44 px drawing rail, the chart with its in-pane legend and stacked panes, a 38 px bottom bar
 * and a 300 px LEVELS / INDICATORS / PATTERNS sidebar with the drawings list as its footer. Below 1024 px the
 * columns fold: the rail becomes a Draw menu and the sidebar a sheet under the chart.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import ChartCanvas, { type ChartCanvasHandle, type PaneSpec } from "./ChartCanvas";
import DataView from "./DataView";
import PatternDetails from "./PatternDetails";
import Toolbar, { type TimeframeOption } from "./workspace/Toolbar";
import DrawingRail, { type ActiveTool } from "./workspace/DrawingRail";
import BottomBar from "./workspace/BottomBar";
import Sidebar from "./workspace/Sidebar";
import IndicatorDialog from "./workspace/IndicatorDialog";
import { DrawingHistory, type DrawingCommand } from "./workspace/drawingHistory";
import { useChartShortcuts } from "./workspace/keyboard";
import { resolveRange, type RangePreset, type VisibleRange } from "./workspace/ranges";
import { TIMEFRAMES, type ChartType, type ScaleMode, type SidebarTab, type Timeframe } from "./workspace/types";
import {
  chartApi, drawingsApi, combinedStatus, statusTone, patternVisualCategory, isLevelPattern, statusLabel, patternTypeLabel,
  matchesPatternFilter, patternFamilies, groupSrBands, nearestLevelReadout, lastIndicatorValue, levelCards, splitBars,
  isUnknownTimeframe, layoutsApi, catalogueApi, DASH, txt, price as fmtPrice, num as fmtNum,
  type Result, type RunPayload, type ManifestSymbolEntry, type OhlcvPayload, type IndicatorsPayload,
  type PatternsPayload, type Pattern, type Drawing, type NewDrawing, type Bar, type PatternFilter,
  type ChartLayout, type NewChartLayout, type LayoutIndicator, type LayoutPane, type IndicatorCatalogue,
} from "./contract";

const PATTERN_FILTER_CHIPS: Array<{ id: PatternFilter; label: string }> = [
  { id: "ALL", label: "All" }, { id: "ACTIVE", label: "Active" }, { id: "CONFIRMED", label: "Confirmed" },
  { id: "FAILED", label: "Failed" }, { id: "INVALIDATED", label: "Invalidated" },
];

/** The token a drawing is stored under per timeframe (§38.6: "drawings are saved per symbol and timeframe").
 *  This screen has always written "daily", while the API's own default for the field is "1D", so both spellings
 *  can exist in the store — `drawingTimeframeOf` reads either. */
const DRAWING_TIMEFRAME: Record<Timeframe, string> = { "1D": "daily", "1W": "weekly", "1M": "monthly" };
const DRAWING_TIMEFRAME_ALIASES: Record<string, Timeframe> = {
  daily: "1D", "1D": "1D", weekly: "1W", "1W": "1W", monthly: "1M", "1M": "1M",
};
/** Which chart a stored drawing belongs to. An unrecognised token reads as daily rather than vanishing: a
 *  drawing the user saved must never be silently invisible on every interval. */
function drawingTimeframeOf(d: Drawing): Timeframe {
  return DRAWING_TIMEFRAME_ALIASES[d.timeframe] ?? "1D";
}
const TIMEFRAME_UNSUPPORTED = "coming with W2 resampling";
const COMPACT_WIDTH = 1024;
const DEFAULT_PANE_HEIGHT = { volume: 70, indicator: 96 };

/** One shared fetch/40x/503 state block, echoing SimulationLabScreen's `Pending`. */
function Pending<T>({ result, label, children }: { result: Result<T> | null; label: string; children: (d: T) => React.ReactNode }) {
  if (result === null) return <p aria-busy="true" style={{ fontSize: 12.5, color: "var(--c-ink-3)", margin: 0, padding: 12 }}>Loading {label}…</p>;
  if (result.kind === "unavailable") return <p role="alert" style={{ fontSize: 12.5, color: "var(--c-ink-2)", margin: 0, padding: 12 }}>{label} unavailable.</p>;
  if (result.kind === "not_found") return <p role="alert" style={{ fontSize: 12.5, color: "var(--c-ink-2)", margin: 0, padding: 12 }}>Not found.</p>;
  if (result.kind === "error") return <p role="alert" style={{ fontSize: 12.5, color: "var(--c-ink-2)", margin: 0, padding: 12 }}>Could not load {label} ({result.message}).</p>;
  if (result.kind === "no_access") return null;
  return <>{children(result.data)}</>;
}

function resultMessage(r: Result<unknown>): string {
  if (r.kind === "error") return r.message;
  if (r.kind === "not_found") return "not found";
  if (r.kind === "unavailable") return "unavailable";
  return "the change could not be saved";
}

export default function ChartsScreen() {
  const [noAccess, setNoAccess] = useState(false);
  const [reload, setReload] = useState(0);
  const [runRes, setRunRes] = useState<Result<RunPayload> | null>(null);
  const [symbolsRes, setSymbolsRes] = useState<Result<ManifestSymbolEntry[]> | null>(null);
  const [search, setSearch] = useState("");
  const [symbol, setSymbol] = useState<string | null>(null);

  const [ohlcvRes, setOhlcvRes] = useState<Result<OhlcvPayload> | null>(null);
  const [indicatorsRes, setIndicatorsRes] = useState<Result<IndicatorsPayload> | null>(null);
  const [patternsRes, setPatternsRes] = useState<Result<PatternsPayload> | null>(null);
  const [drawingsRes, setDrawingsRes] = useState<Result<Drawing[]> | null>(null);

  const [selectedIndicatorIds, setSelectedIndicatorIds] = useState<string[]>([]);
  const [hiddenIndicatorIds, setHiddenIndicatorIds] = useState<string[]>([]);
  // Support & resistance levels are a chart layer, not patterns — shown by default (owner, 2026-09-22).
  const [showLevels, setShowLevels] = useState(true);

  // §38.15 W0: chart patterns are ALWAYS auto-drawn (no per-row visibility toggle) — the filter chip decides which
  // subset is drawn/listed. Selection is either a single row click ([id]) or a chart-shape click that may hit
  // several overlapping patterns at once (overlapIds, most-recent-first) — Previous/Next step through the rest.
  const [patternFilter, setPatternFilter] = useState<PatternFilter>("ALL");
  const [selectedPatternId, setSelectedPatternId] = useState<string | null>(null);
  const [overlapIds, setOverlapIds] = useState<string[]>([]);
  const [overlapIndex, setOverlapIndex] = useState(0);
  const [selectedSrBandId, setSelectedSrBandId] = useState<string | null>(null);

  const [tool, setTool] = useState<ActiveTool>("select");
  const [selectedDrawingId, setSelectedDrawingId] = useState<string | null>(null);
  const [drawingError, setDrawingError] = useState<string | null>(null);
  const [magnetOn, setMagnetOn] = useState(false);
  const [stayInDrawingMode, setStayInDrawingMode] = useState(false);
  const [drawingsLocked, setDrawingsLocked] = useState(false);
  const [drawingsHidden, setDrawingsHidden] = useState(false);

  const [timeframe, setTimeframe] = useState<Timeframe>("1D");
  const [timeframeSupported, setTimeframeSupported] = useState(true);
  const [chartType, setChartType] = useState<ChartType>("candles");
  const [scaleMode, setScaleMode] = useState<ScaleMode>("auto");
  const [activeRange, setActiveRange] = useState<RangePreset | null>(null);
  const [visibleRange, setVisibleRange] = useState<VisibleRange | null>(null);
  const [goToDate, setGoToDate] = useState("");

  const [sidebarTab, setSidebarTab] = useState<SidebarTab>("patterns");
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [isFullscreen, setIsFullscreen] = useState(false);
  const [compact, setCompact] = useState(() => (typeof window !== "undefined" ? window.innerWidth < COMPACT_WIDTH : false));

  const [paneOrder, setPaneOrder] = useState<string[]>([]);
  const [collapsedPaneIds, setCollapsedPaneIds] = useState<string[]>([]);
  const [paneHeights, setPaneHeights] = useState<Record<string, number>>({});
  const [maximisedPaneId, setMaximisedPaneId] = useState<string | null>(null);

  // ── saved layouts (§38.8, AC 9) ──────────────────────────────────────────
  const [layouts, setLayouts] = useState<ChartLayout[]>([]);
  const [openLayout, setOpenLayout] = useState<{ id: string; name: string } | null>(null);
  const [layoutDirty, setLayoutDirty] = useState(false);
  const [layoutError, setLayoutError] = useState<string | null>(null);
  /** A layout chosen from the menu, held as STATE until its symbol's payloads have loaded — applying pane and
   *  indicator state before then would be undone by the per-symbol reset effect. State, not a ref, because
   *  choosing a layout whose symbol and interval already match changes nothing else: a ref would leave the
   *  apply effect's dependencies untouched and the layout would never be applied at all. */
  const [pendingLayout, setPendingLayout] = useState<ChartLayout | null>(null);
  /** The workspace signature that is already on the server. Autosave writes only when the live signature differs
   *  from it, which is what stops applying a layout from writing that same layout straight back. */
  const lastSyncedSignatureRef = useRef<string | null>(null);
  /** Bumped when a layout has been applied. The autosave pass that sees a new value records the resulting
   *  signature as synced instead of saving it — the applied state lands on the following commit, so a ref set
   *  during the apply would be read one commit too early. */
  const [primeTick, setPrimeTick] = useState(0);
  const primedTickRef = useRef(-1);

  // ── indicator preset catalogue (§38.5, D-3) ──────────────────────────────
  // Fetched once per session, not per symbol: it describes the snapshot, not a symbol.
  const [catalogue, setCatalogue] = useState<Result<IndicatorCatalogue> | null>(null);
  const [indicatorDialogOpen, setIndicatorDialogOpen] = useState(false);

  const [showDataView, setShowDataView] = useState(false);
  type DrawerCtx =
    | { kind: "status" }
    | { kind: "bar"; bar: Bar }
    | { kind: "indicator"; id: string }
    | { kind: "rule"; pattern: Pattern; ruleId: string };
  const [drawer, setDrawer] = useState<DrawerCtx | null>(null);

  const canvasRef = useRef<ChartCanvasHandle | null>(null);
  const searchRef = useRef<HTMLInputElement | null>(null);
  const historyRef = useRef(new DrawingHistory());
  const [historyTick, setHistoryTick] = useState(0);

  const denyAll = useCallback(() => {
    setRunRes(null); setSymbolsRes(null); setOhlcvRes(null); setIndicatorsRes(null); setPatternsRes(null); setDrawingsRes(null);
    setNoAccess(true);
  }, []);

  // ── viewport / fullscreen ────────────────────────────────────────────────
  useEffect(() => {
    const onResize = () => setCompact(window.innerWidth < COMPACT_WIDTH);
    const onFs = () => setIsFullscreen(!!document.fullscreenElement);
    window.addEventListener("resize", onResize);
    document.addEventListener("fullscreenchange", onFs);
    return () => { window.removeEventListener("resize", onResize); document.removeEventListener("fullscreenchange", onFs); };
  }, []);

  // ── run + symbol list ────────────────────────────────────────────────────
  useEffect(() => {
    let cancelled = false;
    setRunRes(null); setSymbolsRes(null); setNoAccess(false);
    chartApi.run().then((r) => { if (!cancelled) { if (r.kind === "no_access") denyAll(); else setRunRes(r); } });
    chartApi.symbols().then((r) => {
      if (cancelled) return;
      if (r.kind === "no_access") { denyAll(); return; }
      setSymbolsRes(r);
      if (r.kind === "ok" && r.data.length) setSymbol((cur) => cur ?? r.data[0].symbol);
    });
    return () => { cancelled = true; };
  }, [reload, denyAll]);

  // ── per-symbol payloads that do not depend on the interval ───────────────
  useEffect(() => {
    if (!symbol) return;
    let cancelled = false;
    setPatternsRes(null); setDrawingsRes(null);
    setSelectedIndicatorIds([]); setHiddenIndicatorIds([]);
    setPatternFilter("ALL"); setSelectedPatternId(null); setOverlapIds([]); setOverlapIndex(0);
    setSelectedSrBandId(null); setShowLevels(true);
    setSelectedDrawingId(null); setTool("select"); setDrawer(null); setDrawingError(null);
    setPaneOrder([]); setCollapsedPaneIds([]); setPaneHeights({}); setMaximisedPaneId(null);
    setActiveRange(null); setVisibleRange(null); setGoToDate("");
    // Drawings are saved per symbol and timeframe, so an undo step from one chart must never replay on another.
    historyRef.current.clear(); setHistoryTick((n) => n + 1);

    chartApi.patterns(symbol).then((r) => { if (!cancelled) { if (r.kind === "no_access") denyAll(); else setPatternsRes(r); } });
    drawingsApi.list(symbol).then((r) => { if (!cancelled) { if (r.kind === "no_access") denyAll(); else setDrawingsRes(r); } });
    return () => { cancelled = true; };
  }, [symbol, denyAll]);

  // ── bars + indicators for the chosen interval (§38.7, §38.11) ────────────
  useEffect(() => {
    if (!symbol) return;
    let cancelled = false;
    setOhlcvRes(null); setIndicatorsRes(null);
    chartApi.ohlcv(symbol, timeframe).then((r) => {
      if (cancelled) return;
      if (r.kind === "no_access") { denyAll(); return; }
      // A backend deployed before the weekly/monthly export answers `unknown_timeframe`. That is a capability
      // gap, not a failure of this screen: fall back to daily and disable the interval with its reason, rather
      // than showing the generic error state (§38.19.2).
      if (isUnknownTimeframe(r) && timeframe !== "1D") { setTimeframeSupported(false); setTimeframe("1D"); return; }
      setOhlcvRes(r);
    });
    chartApi.indicators(symbol, undefined, timeframe).then((r) => {
      if (cancelled) return;
      if (r.kind === "no_access") { denyAll(); return; }
      if (isUnknownTimeframe(r) && timeframe !== "1D") return;
      setIndicatorsRes(r);
    });
    return () => { cancelled = true; };
  }, [symbol, timeframe, denyAll]);

  const ohlcv = ohlcvRes?.kind === "ok" ? ohlcvRes.data : null;
  const { bars, incomplete: incompleteDates } = useMemo(() => splitBars(ohlcv?.bars), [ohlcv]);
  const indicators = useMemo(() => (indicatorsRes?.kind === "ok" ? indicatorsRes.data.indicators : {}), [indicatorsRes]);
  const patterns = useMemo(() => (patternsRes?.kind === "ok" ? patternsRes.data.patterns : []), [patternsRes]);
  const chartPatterns = useMemo(() => patterns.filter((p) => !isLevelPattern(p)), [patterns]);
  const levelPatterns = useMemo(() => patterns.filter(isLevelPattern), [patterns]);
  const drawingTimeframe = DRAWING_TIMEFRAME[timeframe];
  const allDrawings = useMemo(() => (drawingsRes?.kind === "ok" ? drawingsRes.data : []), [drawingsRes]);
  const drawings = useMemo(
    () => allDrawings.filter((d) => drawingTimeframeOf(d) === timeframe),
    [allDrawings, timeframe],
  );
  const fixture = runRes?.kind === "ok" ? runRes.data.fixture : false;

  const status = ohlcv ? combinedStatus(ohlcv.data_quality_status, ohlcv.pit_status) : null;
  const pitStatus = ohlcv ? ohlcv.pit_status : null;

  // §38.15 W0 derived state — pure functions over fields the snapshot already carries (contract.ts).
  const atr14 = lastIndicatorValue(indicators["atr_14"]);
  const relativeVolume = lastIndicatorValue(indicators["relative_volume"]);
  const srBands = useMemo(() => groupSrBands(levelPatterns, atr14), [levelPatterns, atr14]);
  const patternFamilyChips = useMemo(() => patternFamilies(chartPatterns), [chartPatterns]);
  const filteredChartPatterns = useMemo(
    () => chartPatterns.filter((p) => matchesPatternFilter(p, patternFilter)),
    [chartPatterns, patternFilter],
  );
  // Detection is daily-only (§38.7): a pattern's window is a run of daily sessions, so it is not drawn over
  // weekly or monthly bars. The Patterns panel says so rather than leaving an unexplained empty chart.
  const patternsForChart = timeframe === "1D" ? filteredChartPatterns : [];
  const lastClose = bars.length ? bars[bars.length - 1][4] : null;
  const prevClose = bars.length > 1 ? bars[bars.length - 2][4] : null;
  const change = lastClose != null && prevClose != null ? lastClose - prevClose : null;
  const changePct = change != null && prevClose ? (change / prevClose) * 100 : null;
  const nearestLevel = useMemo(
    () => nearestLevelReadout(lastClose, chartPatterns, srBands, atr14),
    [lastClose, chartPatterns, srBands, atr14],
  );
  const cards = useMemo(() => levelCards(srBands, lastClose), [srBands, lastClose]);
  const engineVersion = runRes?.kind === "ok" ? runRes.data.engine_version : null;

  // ── panes (§38.5) ────────────────────────────────────────────────────────
  const panes: PaneSpec[] = useMemo(() => {
    const paneOf = (id: string) => indicators[id]?.pane ?? "price";
    const pricePane: PaneSpec = {
      id: "price", title: "Price", kind: "price",
      indicatorIds: selectedIndicatorIds.filter((id) => paneOf(id) === "price"),
      collapsed: false, height: 0,
    };
    const volumePane: PaneSpec = {
      id: "volume", title: "Volume", kind: "volume", indicatorIds: [],
      collapsed: collapsedPaneIds.includes("volume"), height: paneHeights.volume ?? DEFAULT_PANE_HEIGHT.volume,
    };
    const names: string[] = [];
    for (const id of selectedIndicatorIds) {
      const pane = paneOf(id);
      if (pane !== "price" && !names.includes(pane)) names.push(pane);
    }
    const indicatorPanes: PaneSpec[] = names.map((name) => {
      const id = `ind:${name}`;
      return {
        id, title: name, kind: "indicator" as const,
        indicatorIds: selectedIndicatorIds.filter((x) => paneOf(x) === name),
        collapsed: collapsedPaneIds.includes(id), height: paneHeights[id] ?? DEFAULT_PANE_HEIGHT.indicator,
      };
    });
    const rest = [volumePane, ...indicatorPanes];
    rest.sort((a, b) => {
      const ia = paneOrder.indexOf(a.id), ib = paneOrder.indexOf(b.id);
      if (ia === -1 && ib === -1) return 0;
      if (ia === -1) return 1;
      if (ib === -1) return -1;
      return ia - ib;
    });
    return [pricePane, ...rest];
  }, [indicators, selectedIndicatorIds, collapsedPaneIds, paneHeights, paneOrder]);

  const movePane = useCallback((paneId: string, direction: -1 | 1) => {
    const ids = panes.slice(1).map((p) => p.id);
    setPaneOrder((cur) => {
      const base = cur.length === ids.length && ids.every((id) => cur.includes(id)) ? [...cur] : ids;
      const from = base.indexOf(paneId);
      if (from === -1) return base;
      const to = from + direction;
      if (to < 0 || to >= base.length) return base;   // the price pane always stays first (§38.5)
      const next = [...base];
      next.splice(to, 0, next.splice(from, 1)[0]);
      return next;
    });
  }, [panes]);

  const togglePaneCollapsed = useCallback((paneId: string) => {
    setCollapsedPaneIds((cur) => (cur.includes(paneId) ? cur.filter((x) => x !== paneId) : [...cur, paneId]));
  }, []);

  const removePane = useCallback((paneId: string) => {
    const spec = panes.find((p) => p.id === paneId);
    if (!spec) return;
    setSelectedIndicatorIds((cur) => cur.filter((id) => !spec.indicatorIds.includes(id)));
  }, [panes]);

  // ── drawing create / delete, through the undo/redo history (§38.6, AC5) ──
  const applyAdd = useCallback((d: Drawing) => {
    setDrawingsRes((cur) => ({ kind: "ok", data: [...(cur?.kind === "ok" ? cur.data : []), d] }));
  }, []);
  const applyRemove = useCallback((id: string) => {
    setDrawingsRes((cur) => (cur?.kind === "ok" ? { kind: "ok", data: cur.data.filter((x) => x.drawing_id !== id) } : cur));
    setSelectedDrawingId((cur) => (cur === id ? null : cur));
  }, []);

  /** Throws on any non-ok result, so the history stack stays untouched and the error is surfaced (§38.6). */
  const unwrap = useCallback(function <T>(r: Result<T>): T {
    if (r.kind === "ok") return r.data;
    if (r.kind === "no_access") { denyAll(); throw new Error("charts is not enabled for your account"); }
    throw new Error(resultMessage(r));
  }, [denyAll]);

  const createCommand = useCallback((payload: NewDrawing): DrawingCommand<Drawing> => {
    let created: Drawing | null = null;
    return {
      label: `create ${payload.drawing_type}`,
      do: async () => {
        const d = unwrap(await drawingsApi.create(payload));
        created = d; applyAdd(d); return d;
      },
      undo: async () => {
        if (!created) throw new Error("nothing to undo");
        const id = created.drawing_id;
        unwrap(await drawingsApi.remove(id));
        applyRemove(id);
        return created;
      },
    };
  }, [unwrap, applyAdd, applyRemove]);

  const deleteCommand = useCallback((drawing: Drawing): DrawingCommand<Drawing> => {
    let current = drawing;
    return {
      label: `delete ${drawing.drawing_type}`,
      do: async () => {
        unwrap(await drawingsApi.remove(current.drawing_id));
        applyRemove(current.drawing_id);
        return current;
      },
      undo: async () => {
        const d = unwrap(await drawingsApi.create({
          symbol: current.symbol, timeframe: current.timeframe, drawing_type: current.drawing_type,
          anchor_points: current.anchor_points, style: current.style ?? null,
        }));
        current = d; applyAdd(d); return d;
      },
    };
  }, [unwrap, applyAdd, applyRemove]);

  const onHistoryError = useCallback((message: string) => { setDrawingError(message); }, []);
  const bump = useCallback(() => setHistoryTick((n) => n + 1), []);

  const onCreateDrawing = useCallback(async (d: NewDrawing) => {
    setDrawingError(null);
    await historyRef.current.run(createCommand({ ...d, timeframe: drawingTimeframe }), onHistoryError);
    bump();
    if (!stayInDrawingMode) setTool("select");
  }, [createCommand, drawingTimeframe, onHistoryError, bump, stayInDrawingMode]);

  const deleteSelected = useCallback(async (idOverride?: string) => {
    const id = idOverride ?? selectedDrawingId;
    if (!id) return;
    const drawing = allDrawings.find((d) => d.drawing_id === id);
    if (!drawing) return;
    setDrawingError(null);
    await historyRef.current.run(deleteCommand(drawing), onHistoryError);
    bump();
  }, [selectedDrawingId, allDrawings, deleteCommand, onHistoryError, bump]);

  const removeAllDrawings = useCallback(async () => {
    if (!drawings.length) return;
    if (typeof window !== "undefined" && !window.confirm(`Remove all ${drawings.length} drawings on ${symbol}?`)) return;
    setDrawingError(null);
    for (const d of [...drawings]) await historyRef.current.run(deleteCommand(d), onHistoryError);
    bump();
  }, [drawings, symbol, deleteCommand, onHistoryError, bump]);

  const undo = useCallback(async () => { setDrawingError(null); await historyRef.current.undo(onHistoryError); bump(); }, [onHistoryError, bump]);
  const redo = useCallback(async () => { setDrawingError(null); await historyRef.current.redo(onHistoryError); bump(); }, [onHistoryError, bump]);

  // ── saved layouts: capture, apply, autosave (§38.8, AC 9) ────────────────
  /** The current workspace as the API's layout shape. The price pane is deliberately left out of
   *  `panes`: it is always first and the API requires a height above zero, while the price pane's height
   *  is simply whatever the others leave. */
  const captureLayout = useCallback((name: string): NewChartLayout => {
    const nonPrice = panes.filter((p) => p.kind !== "price");
    const layoutPanes: LayoutPane[] = nonPrice.map((p, i) => ({
      pane_id: p.id, order: i, height: Math.max(1, Math.round(p.height)), collapsed: p.collapsed,
    }));
    const layoutIndicators: LayoutIndicator[] = selectedIndicatorIds.map((id) => {
      const paneId = (indicators[id]?.pane ?? "price") === "price" ? "price" : `ind:${indicators[id].pane}`;
      const idx = panes.findIndex((p) => p.id === paneId);
      return {
        instance_id: id,
        indicator_id: id,
        // No preset catalogue yet (§38.5, W2): every instance uses the parameters the snapshot's own
        // indicator contract fixes, and "default" names exactly that.
        preset_id: "default",
        pane_index: idx < 0 ? 0 : idx,
        visible: !hiddenIndicatorIds.includes(id),
      };
    });
    return {
      name,
      symbol: symbol ?? "",
      timeframe,
      chart_type: chartType,
      indicators: layoutIndicators,
      panes: layoutPanes,
      visible_range: visibleRange ? { from_date: visibleRange.from, to_date: visibleRange.to } : null,
      // The rail hides drawings all at once rather than one by one, so "hidden" is recorded as every
      // current drawing being hidden. A drawing added after the layout was saved is not in the map, and
      // the chart then opens with drawings shown — visible, never silently missing.
      drawing_visibility: drawingsHidden ? Object.fromEntries(drawings.map((d) => [d.drawing_id, false])) : {},
      sidebar_state: { collapsed: sidebarCollapsed, active_tab: sidebarTab },
    };
  }, [panes, selectedIndicatorIds, hiddenIndicatorIds, indicators, symbol, timeframe, chartType,
      visibleRange, drawingsHidden, drawings, sidebarCollapsed, sidebarTab]);

  /** The change detector: the captured workspace itself, minus the name — a rename is its own explicit call, and
   *  including it here would make renaming look like a workspace edit. */
  const layoutSignature = JSON.stringify(captureLayout(""));

  const refreshLayouts = useCallback(async () => {
    const r = await layoutsApi.list();
    if (r.kind === "ok") setLayouts(r.data);
    else if (r.kind === "no_access") denyAll();
    // Any other outcome leaves the list as it was: a layout menu that cannot be read is an empty menu, not a
    // blocking error — the rest of the chart works without it.
  }, [denyAll]);

  useEffect(() => { void refreshLayouts(); }, [refreshLayouts]);

  useEffect(() => {
    let cancelled = false;
    void catalogueApi.get().then((r) => {
      if (cancelled) return;
      if (r.kind === "no_access") { denyAll(); return; }
      setCatalogue(r);
    });
    return () => { cancelled = true; };
  }, [denyAll]);

  /** Applies a chosen layout once its symbol's payloads have arrived (see `pendingLayout`). */
  useEffect(() => {
    const l = pendingLayout;
    if (!l || !symbol || symbol !== l.symbol) return;
    if (ohlcvRes?.kind !== "ok" || indicatorsRes?.kind !== "ok") return;
    setPendingLayout(null);
    setPrimeTick((t) => t + 1);

    setChartType(l.chart_type as ChartType);
    const wanted = l.indicators.filter((i) => indicators[i.indicator_id]);
    setSelectedIndicatorIds(wanted.map((i) => i.indicator_id));
    setHiddenIndicatorIds(wanted.filter((i) => !i.visible).map((i) => i.indicator_id));
    setPaneOrder([...l.panes].sort((a, b) => a.order - b.order).map((p) => p.pane_id));
    setPaneHeights(Object.fromEntries(l.panes.map((p) => [p.pane_id, p.height])));
    setCollapsedPaneIds(l.panes.filter((p) => p.collapsed).map((p) => p.pane_id));
    setVisibleRange(l.visible_range ? { from: l.visible_range.from_date, to: l.visible_range.to_date } : null);
    const hiddenIds = Object.entries(l.drawing_visibility).filter(([, v]) => v === false).map(([k]) => k);
    setDrawingsHidden(hiddenIds.length > 0);
    if (l.sidebar_state) {
      setSidebarCollapsed(l.sidebar_state.collapsed);
      const tab = l.sidebar_state.active_tab;
      if (tab === "levels" || tab === "indicators" || tab === "patterns") setSidebarTab(tab);
    }
    setLayoutDirty(false);
  }, [pendingLayout, symbol, ohlcvRes, indicatorsRes, indicators]);

  const onOpenLayout = useCallback((id: string) => {
    const l = layouts.find((x) => x.layout_id === id);
    if (!l) return;
    setLayoutError(null);
    setPendingLayout(l);
    setOpenLayout({ id: l.layout_id, name: l.name });
    if (l.timeframe === "1D" || l.timeframe === "1W" || l.timeframe === "1M") setTimeframe(l.timeframe);
    if (l.symbol !== symbol) setSymbol(l.symbol);
  }, [layouts, symbol]);

  const onSaveLayoutAs = useCallback(async () => {
    const name = typeof window !== "undefined" ? window.prompt("Name this layout", openLayout?.name ?? "Unnamed") : null;
    if (!name) return;
    setLayoutError(null);
    const r = await layoutsApi.create(captureLayout(name));
    if (r.kind === "ok") {
      setOpenLayout({ id: r.data.layout_id, name: r.data.name });
      lastSyncedSignatureRef.current = layoutSignature;
      setLayoutDirty(false);
      await refreshLayouts();
    } else if (r.kind === "no_access") denyAll();
    else setLayoutError(resultMessage(r));
  }, [openLayout, captureLayout, refreshLayouts, denyAll]);

  const onSaveLayout = useCallback(async () => {
    if (!openLayout) { await onSaveLayoutAs(); return; }
    setLayoutError(null);
    const r = await layoutsApi.update(openLayout.id, captureLayout(openLayout.name));
    if (r.kind === "ok") { lastSyncedSignatureRef.current = layoutSignature; setLayoutDirty(false); await refreshLayouts(); }
    else if (r.kind === "no_access") denyAll();
    else setLayoutError(resultMessage(r));
  }, [openLayout, captureLayout, onSaveLayoutAs, refreshLayouts, denyAll, layoutSignature]);

  const onRenameLayout = useCallback(async () => {
    if (!openLayout) return;
    const name = typeof window !== "undefined" ? window.prompt("Rename layout", openLayout.name) : null;
    if (!name || name === openLayout.name) return;
    setLayoutError(null);
    const r = await layoutsApi.update(openLayout.id, { name });
    if (r.kind === "ok") { setOpenLayout({ id: r.data.layout_id, name: r.data.name }); await refreshLayouts(); }
    else if (r.kind === "no_access") denyAll();
    else setLayoutError(resultMessage(r));
  }, [openLayout, refreshLayouts, denyAll]);

  const onDeleteLayout = useCallback(async () => {
    if (!openLayout) return;
    if (typeof window !== "undefined" && !window.confirm(`Delete the layout "${openLayout.name}"?`)) return;
    setLayoutError(null);
    const r = await layoutsApi.remove(openLayout.id);
    if (r.kind === "ok") { setOpenLayout(null); setLayoutDirty(false); await refreshLayouts(); }
    else if (r.kind === "no_access") denyAll();
    else setLayoutError(resultMessage(r));
  }, [openLayout, refreshLayouts, denyAll]);

  /** §38.8 "layouts autosave after changes": once a layout is open, a change marks it dirty and is written
   *  back after a pause. Nothing autosaves before the chart has been saved once — an unnamed chart has no
   *  row to write to, and creating one silently would litter the list. */
  useEffect(() => {
    // Nothing to save before the chart has been saved once, and nothing to save while a chosen layout is still
    // being applied — what is on screen at that moment is a half-applied layout, not a user's workspace.
    if (!openLayout || pendingLayout) return;
    // The first pass after a layout was applied or saved records what is already on the server rather than
    // writing it back: the chart now holds exactly what was just read from or sent to it.
    if (primedTickRef.current !== primeTick) {
      primedTickRef.current = primeTick;
      lastSyncedSignatureRef.current = layoutSignature;
      setLayoutDirty(false);
      return;
    }
    if (lastSyncedSignatureRef.current === layoutSignature) return;
    setLayoutDirty(true);
    const id = window.setTimeout(() => {
      void (async () => {
        const r = await layoutsApi.update(openLayout.id, captureLayout(openLayout.name));
        if (r.kind === "ok") { lastSyncedSignatureRef.current = layoutSignature; setLayoutDirty(false); }
        else if (r.kind === "no_access") denyAll();
        else setLayoutError(resultMessage(r));
      })();
    }, 1500);
    return () => window.clearTimeout(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [layoutSignature, openLayout?.id, pendingLayout, primeTick]);

  // ── selection helpers ────────────────────────────────────────────────────
  const clearSelection = useCallback(() => {
    canvasRef.current?.cancelPending();
    setTool("select");
    setSelectedDrawingId(null);
    setSelectedPatternId(null); setOverlapIds([]); setOverlapIndex(0);
    setSelectedSrBandId(null);
  }, []);

  useChartShortcuts({
    onTrendline: () => setTool("trendline"),
    onHorizontalLine: () => setTool("horizontal_line"),
    onCancel: clearSelection,
    onDelete: () => { if (selectedDrawingId) void deleteSelected(); },
    onUndo: () => void undo(),
    onRedo: () => void redo(),
  });

  const toggleIndicator = (id: string) =>
    setSelectedIndicatorIds((cur) => (cur.includes(id) ? cur.filter((x) => x !== id) : [...cur, id]));

  /** A row click in the Patterns list — always a single-candidate selection (no overlap to step through). */
  const selectPatternRow = (p: Pattern) => {
    setOverlapIds([p.pattern_id]); setOverlapIndex(0); setSelectedPatternId(p.pattern_id);
    setSelectedSrBandId(null);
  };

  /** A click on the chart — the primitive's hit test, already sorted most-recent-formation_end-first (§38.15). */
  const onSelectPatternFromChart = (hitIds: string[]) => {
    if (!hitIds.length) { setSelectedPatternId(null); setOverlapIds([]); setOverlapIndex(0); return; }
    setOverlapIds(hitIds); setOverlapIndex(0); setSelectedPatternId(hitIds[0]);
    setSelectedSrBandId(null);
    setSidebarTab("patterns");
  };

  const stepOverlap = (dir: 1 | -1) => {
    if (!overlapIds.length) return;
    const next = (overlapIndex + dir + overlapIds.length) % overlapIds.length;
    setOverlapIndex(next); setSelectedPatternId(overlapIds[next]);
  };

  const onSelectSrBand = (id: string | null) => {
    setSelectedSrBandId(id);
    if (id) { setSelectedPatternId(null); setOverlapIds([]); setOverlapIndex(0); setSidebarTab("levels"); }
  };

  const onSelectRange = (preset: RangePreset) => {
    setActiveRange(preset);
    setVisibleRange(resolveRange(preset, bars));
  };

  const onGoToDate = (dateISO: string) => {
    setGoToDate(dateISO);
    if (!dateISO || !bars.length) return;
    setActiveRange(null);
    setVisibleRange({ from: dateISO < bars[0][0] ? bars[0][0] : dateISO, to: bars[bars.length - 1][0] });
  };

  const symbolRows = useMemo(() => {
    const list = symbolsRes?.kind === "ok" ? symbolsRes.data : [];
    const q = search.trim().toUpperCase();
    return q ? list.filter((s) => s.symbol.toUpperCase().includes(q)) : list;
  }, [symbolsRes, search]);

  const selectedPattern = patterns.find((p) => p.pattern_id === selectedPatternId) ?? null;
  const selectedSrBand = srBands.find((b) => b.id === selectedSrBandId) ?? null;

  const timeframeOptions: TimeframeOption[] = TIMEFRAMES.map((tf) => ({
    id: tf,
    enabled: tf === "1D" || timeframeSupported,
    reason: tf === "1D" || timeframeSupported ? undefined : TIMEFRAME_UNSUPPORTED,
  }));

  /* ── access / top-level states ──────────────────────────────────────────── */
  if (noAccess) {
    return (
      <Shell>
        <div className="nv-card" role="status" data-testid="charts-state-no_access" style={{ padding: 22 }}>
          <h3 className="nv-serif" style={{ fontSize: 20, margin: 0 }}>Charts is not enabled for your account</h3>
          <p style={{ fontSize: 13.5, color: "var(--c-ink-2)", margin: "8px 0 0" }}>
            It is an internal research surface over Kite-derived prices, open to invited accounts only.
          </p>
        </div>
      </Shell>
    );
  }
  if (runRes === null || symbolsRes === null) {
    return (
      <Shell>
        <div className="nv-card" aria-busy="true" data-testid="charts-state-loading" style={{ padding: 22, display: "grid", gap: 10 }}>
          {Array.from({ length: 5 }).map((_, i) => (
            <div key={i} style={{ height: 14, borderRadius: 6, background: "var(--bg-3)", width: `${90 - i * 8}%` }} />
          ))}
          <span className="sr-only">Loading the chart snapshot…</span>
        </div>
      </Shell>
    );
  }
  if (runRes.kind === "unavailable" || symbolsRes.kind === "unavailable") {
    return (
      <Shell>
        <div className="nv-card" role="alert" data-testid="charts-state-unavailable" style={{ padding: 22 }}>
          <h3 className="nv-serif" style={{ fontSize: 20, margin: 0 }}>Chart snapshot unavailable</h3>
          <p style={{ fontSize: 13.5, color: "var(--c-ink-2)", margin: "8px 0 0" }}>
            The published snapshot is missing or did not match the expected schema, so nothing is shown.
          </p>
          <button type="button" className="nv-btn" data-testid="charts-retry" style={{ marginTop: 14 }} onClick={() => setReload((n) => n + 1)}>
            Try again
          </button>
        </div>
      </Shell>
    );
  }
  if (runRes.kind === "error" || symbolsRes.kind === "error") {
    const msg = runRes.kind === "error" ? runRes.message : symbolsRes.kind === "error" ? symbolsRes.message : "unknown error";
    return (
      <Shell>
        <div className="nv-card" role="alert" data-testid="charts-state-error" style={{ padding: 22 }}>
          <h3 className="nv-serif" style={{ fontSize: 20, margin: 0 }}>The chart snapshot could not be loaded</h3>
          <p style={{ fontSize: 13.5, color: "var(--c-ink-2)", margin: "8px 0 0" }}>The service did not answer ({msg}).</p>
          <button type="button" className="nv-btn" data-testid="charts-retry" style={{ marginTop: 14 }} onClick={() => setReload((n) => n + 1)}>
            Try again
          </button>
        </div>
      </Shell>
    );
  }
  if (runRes.kind !== "ok" || symbolsRes.kind !== "ok") return null;
  const run = runRes.data;
  const allSymbols = symbolsRes.data;

  if (allSymbols.length === 0) {
    return (
      <Shell>
        <div className="nv-card" data-testid="charts-state-empty" style={{ padding: 22 }}>
          <h3 className="nv-serif" style={{ fontSize: 20, margin: 0 }}>No symbols in this snapshot</h3>
          <p style={{ fontSize: 13.5, color: "var(--c-ink-2)", margin: "8px 0 0" }}>The published run carries an empty universe.</p>
        </div>
      </Shell>
    );
  }

  const symEntry = allSymbols.find((s) => s.symbol === symbol) ?? null;
  const ohlcvNotFound = ohlcvRes?.kind === "not_found";
  const exchange = run.source.provider === "kite" ? "NSE · EQ" : `${txt(run.source.provider)} · EQ`;

  const statusBadge = status ? (
    <button
      type="button" data-testid="chart-status-chip" onClick={() => setDrawer({ kind: "status" })}
      className={`nv-pill nv-pill-${statusTone(status)}`} style={{ cursor: "pointer", border: 0, flex: "none" }}
      title="Data quality and point-in-time status — opens the provenance drawer"
    >
      {status}
    </button>
  ) : null;

  /* ── sidebar panels ─────────────────────────────────────────────────────── */
  const levelsPanel = (
    <div className="nv-card" data-testid="chart-levels-panel" style={{ padding: 12 }}>
      <label style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 12.5, color: "var(--c-ink-2)", cursor: "pointer", marginBottom: 10 }}>
        <input type="checkbox" data-testid="chart-sr-toggle" checked={showLevels} onChange={() => setShowLevels((v) => !v)} />
        <span>Support &amp; resistance</span>
        <span data-testid="chart-sr-count" style={{ color: "var(--c-ink-4)", fontSize: 10.5 }}>
          {patternsRes?.kind === "ok" ? `${levelPatterns.length} level${levelPatterns.length === 1 ? "" : "s"}` : ""}
        </span>
      </label>

      {/* §38.15 item 8: near-duplicate S/R records grouped into bands; click a band to list every record (AC24).
          There is deliberately no 1–5 strength score — the record carries `scores: null`, so the card shows the
          touch count and HOLDING/BROKEN instead of an invented number (§11/§16). */}
      {showLevels && cards.length > 0 && (
        <div data-testid="chart-sr-bands" style={{ display: "grid", gap: 6 }}>
          {cards.map((c) => {
            const tone = c.kind === "SUPPORT" ? "var(--mint)" : c.kind === "RESISTANCE" ? "var(--danger-hex)" : "var(--amber)";
            return (
              <button
                key={c.id} type="button" data-testid={`chart-sr-band-${c.id}`}
                onClick={() => onSelectSrBand(selectedSrBandId === c.id ? null : c.id)}
                aria-pressed={selectedSrBandId === c.id}
                style={{
                  display: "grid", gap: 3, width: "100%", textAlign: "left", padding: "8px 9px", borderRadius: 9,
                  border: `1px solid ${selectedSrBandId === c.id ? "var(--c-line-strong)" : "var(--c-line)"}`,
                  cursor: "pointer", background: selectedSrBandId === c.id ? "var(--bg-2)" : "transparent",
                }}
              >
                <span style={{ display: "flex", alignItems: "baseline", gap: 8 }}>
                  <span className="nv-mono" style={{ fontSize: 15, color: tone }}>₹{fmtNum(c.price)}</span>
                  <span className="nv-mono" style={{ fontSize: 9.5, color: "var(--c-ink-4)", letterSpacing: ".06em" }}>{c.kind}</span>
                  <span
                    data-testid={`chart-sr-band-state-${c.id}`} className="nv-mono"
                    style={{ marginLeft: "auto", fontSize: 9, letterSpacing: ".06em", padding: "1px 6px", borderRadius: 999, border: "1px solid var(--c-line)", color: c.state === "BROKEN" ? "var(--c-ink-4)" : tone }}
                  >
                    {c.state}
                  </span>
                </span>
                <span className="nv-mono" style={{ fontSize: 10.5, color: "var(--c-ink-3)", display: "flex", gap: 10, flexWrap: "wrap" }}>
                  <span data-testid={`chart-sr-band-touches-${c.id}`}>{c.touches} touch{c.touches === 1 ? "" : "es"}</span>
                  <span data-testid={`chart-sr-band-distance-${c.id}`}>
                    {c.distanceRupees != null ? `${c.distanceRupees >= 0 ? "+" : ""}₹${fmtNum(c.distanceRupees)}` : DASH}
                    {c.distancePct != null ? ` · ${c.distancePct >= 0 ? "+" : ""}${fmtNum(c.distancePct)}%` : ""}
                  </span>
                  {c.records.length > 1 && <span data-testid={`chart-sr-band-count-${c.id}`}>{c.records.length} levels</span>}
                </span>
              </button>
            );
          })}
        </div>
      )}
      {showLevels && cards.length === 0 && (
        <p data-testid="chart-levels-empty" style={{ margin: 0, fontSize: 12.5, color: "var(--c-ink-3)" }}>No support or resistance levels in this snapshot.</p>
      )}

      {selectedSrBand && (
        <div data-testid="chart-srband-drawer" className="nv-card" style={{ padding: 10, marginTop: 10, background: "var(--bg-2)" }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 6 }}>
            <p className="nv-eyebrow" style={{ margin: 0 }}>Band records · {selectedSrBand.records.length}</p>
            <button type="button" data-testid="chart-srband-close" onClick={() => onSelectSrBand(null)} className="rail-ico" style={{ width: 18, height: 18, borderRadius: 999 }} aria-label="Close band records">✕</button>
          </div>
          <ul style={{ listStyle: "none", margin: 0, padding: 0, display: "grid", gap: 3 }}>
            {selectedSrBand.records.map((r) => (
              <li key={r.pattern_id} data-testid={`chart-srband-record-${r.pattern_id}`} style={{ display: "flex", justifyContent: "space-between", fontSize: 11.5 }}>
                <span>{r.levels?.kind === "SUPPORT" ? "Support" : r.levels?.kind === "RESISTANCE" ? "Resistance" : txt(r.levels?.kind)}</span>
                <span className="nv-mono">₹{fmtNum(r.levels?.level)}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );

  const indicatorsPanel = (
    <div className="nv-card" data-testid="chart-indicators-panel" style={{ padding: 12 }}>
      <Pending result={indicatorsRes} label="indicators">
        {(d) => {
          const ids = Object.keys(d.indicators);
          if (!ids.length) return <p style={{ margin: 0, fontSize: 12.5, color: "var(--c-ink-3)" }}>No indicators in this snapshot.</p>;
          return (
            <div style={{ display: "grid", gap: 6 }}>
              {ids.map((id) => (
                <div key={id} style={{ display: "flex", alignItems: "center", gap: 8 }}>
                  <label style={{ display: "flex", alignItems: "center", gap: 8, flex: 1, minWidth: 0, fontSize: 12.5, color: "var(--c-ink-2)", cursor: "pointer" }}>
                    <input
                      type="checkbox" data-testid={`chart-indicator-toggle-${id}`}
                      checked={selectedIndicatorIds.includes(id)} onChange={() => toggleIndicator(id)}
                    />
                    <span className="nv-mono">{id}</span>
                    <span style={{ color: "var(--c-ink-4)", fontSize: 10.5 }}>{d.indicators[id].pane === "price" ? "overlay" : `pane · ${d.indicators[id].pane}`}</span>
                  </label>
                  <button
                    type="button" data-testid={`chart-indicator-info-${id}`} aria-label={`${id} provenance`}
                    onClick={() => setDrawer({ kind: "indicator", id })} className="rail-ico" style={{ width: 20, height: 20, borderRadius: 999, fontSize: 10 }}
                  >
                    i
                  </button>
                </div>
              ))}
            </div>
          );
        }}
      </Pending>
    </div>
  );

  const patternsPanel = (
    <div className="nv-card" data-testid="chart-patterns-panel" style={{ padding: 12 }}>
      {timeframe !== "1D" && (
        <p data-testid="chart-patterns-daily-only" style={{ margin: "0 0 8px", fontSize: 11.5, color: "var(--c-ink-3)" }}>
          Detection is daily-only, so patterns are listed here but not drawn on the {timeframe === "1W" ? "weekly" : "monthly"} chart.
        </p>
      )}

      {/* §38.15 filter chips: All / Active / Confirmed / Failed / Invalidated + one per family. Default All. */}
      {chartPatterns.length > 0 && (
        <div role="group" aria-label="Pattern filter" style={{ display: "flex", flexWrap: "wrap", gap: 4, marginBottom: 10 }}>
          {PATTERN_FILTER_CHIPS.map((c) => (
            <button
              key={c.id} type="button" data-testid={`chart-pattern-filter-${c.id.toLowerCase()}`}
              aria-pressed={patternFilter === c.id} onClick={() => setPatternFilter(c.id)}
              className="nv-btn" style={{ fontSize: 11, padding: "3px 9px", ...(patternFilter === c.id ? { borderColor: "var(--mint-line)", color: "var(--mint)", background: "var(--mint-soft)" } : {}) }}
            >
              {c.label}
            </button>
          ))}
          {patternFamilyChips.map((fam) => {
            const id = `FAMILY:${fam}` as const;
            return (
              <button
                key={fam} type="button" data-testid={`chart-pattern-filter-family-${fam}`}
                aria-pressed={patternFilter === id} onClick={() => setPatternFilter(id)}
                className="nv-btn" style={{ fontSize: 11, padding: "3px 9px", ...(patternFilter === id ? { borderColor: "var(--mint-line)", color: "var(--mint)", background: "var(--mint-soft)" } : {}) }}
              >
                {patternTypeLabel(fam)}
              </button>
            );
          })}
        </div>
      )}

      <Pending result={patternsRes} label="patterns">
        {() => {
          const rows = filteredChartPatterns;
          return chartPatterns.length === 0 ? (
            <p data-testid="chart-patterns-empty" style={{ margin: 0, fontSize: 12.5, color: "var(--c-ink-3)" }}>
              No chart patterns found.
            </p>
          ) : rows.length === 0 ? (
            <p data-testid="chart-patterns-filter-empty" style={{ margin: 0, fontSize: 12.5, color: "var(--c-ink-3)" }}>
              No patterns match this filter.
            </p>
          ) : (
            <div style={{ display: "grid", gap: 6 }}>
              {rows.map((p) => {
                const cat = patternVisualCategory(p);
                return (
                  <div key={p.pattern_id} data-testid={`chart-pattern-row-${p.pattern_id}`} style={{ display: "flex", alignItems: "center", gap: 8, padding: "6px 8px", borderRadius: 8, background: selectedPatternId === p.pattern_id ? "var(--bg-2)" : "transparent" }}>
                    <button type="button" onClick={() => selectPatternRow(p)} style={{ flex: 1, minWidth: 0, textAlign: "left", background: "none", border: 0, cursor: "pointer", padding: 0 }}>
                      <span style={{ fontSize: 12.5, color: "var(--c-ink)" }}>{patternTypeLabel(p.pattern_type)}</span>{" "}
                      <span className="nv-mono" data-testid={`chart-pattern-status-${p.pattern_id}`} data-category={cat} style={{ fontSize: 10, color: "var(--c-ink-4)" }}>{statusLabel(p)}</span>
                    </button>
                  </div>
                );
              })}
            </div>
          );
        }}
      </Pending>

      {selectedPattern && (
        <>
          <PatternDetails
            pattern={selectedPattern}
            atr14={atr14}
            relativeVolume={relativeVolume}
            pitStatus={pitStatus}
            engineVersion={engineVersion}
            overlapCount={overlapIds.length}
            overlapIndex={overlapIndex}
            onPrev={() => stepOverlap(-1)}
            onNext={() => stepOverlap(1)}
            onOpenRule={(ruleId) => setDrawer({ kind: "rule", pattern: selectedPattern, ruleId })}
            onClose={() => { setSelectedPatternId(null); setOverlapIds([]); setOverlapIndex(0); }}
          />
          <p className="nv-eyebrow" style={{ margin: "0 0 6px" }}>Scores</p>
          {selectedPattern.scores ? (
            <div data-testid="chart-scores" style={{ display: "grid", gap: 8 }}>
              {(["formation", "readiness", "confirmation", "failure_risk"] as const).map((k) => {
                const v = selectedPattern.scores![k];
                const label = k === "failure_risk" ? "Failure risk" : k[0].toUpperCase() + k.slice(1);
                return (
                  <div key={k} data-testid={`chart-score-${k}`}>
                    <div style={{ display: "flex", justifyContent: "space-between", fontSize: 11, color: "var(--c-ink-3)" }}>
                      <span>{label}</span><span className="nv-mono">{fmtNum(v, 0)}</span>
                    </div>
                    <div style={{ height: 6, borderRadius: 999, background: "var(--bg-3)", overflow: "hidden" }}>
                      <div style={{ height: "100%", width: `${Math.max(0, Math.min(100, v))}%`, background: "var(--mint)" }} />
                    </div>
                  </div>
                );
              })}
              <p style={{ margin: "2px 0 0", fontSize: 10.5, color: "var(--c-ink-4)" }}>Each is a score, not a probability — never summed into one number.</p>
            </div>
          ) : (
            <p style={{ margin: 0, fontSize: 11.5, color: "var(--c-ink-4)" }}>No scores in this snapshot.</p>
          )}
        </>
      )}
    </div>
  );

  const drawingsFooter = (
    <div className="nv-card" data-testid="chart-drawings-list" style={{ padding: 12 }}>
      <p className="nv-eyebrow" style={{ margin: "0 0 8px" }}>Your drawings · {drawings.length}</p>
      {drawingError && <p role="alert" data-testid="chart-drawing-error" style={{ margin: "0 0 8px", fontSize: 11.5, color: "var(--danger-hex)" }}>{drawingError}</p>}
      {layoutError && <p role="alert" data-testid="chart-layout-error" style={{ margin: "0 0 8px", fontSize: 11.5, color: "var(--danger-hex)" }}>Layout: {layoutError}</p>}
      {drawings.length === 0 ? (
        <p style={{ margin: 0, fontSize: 12.5, color: "var(--c-ink-3)" }}>No drawings on {symbol} yet — pick a tool in the rail and click the chart.</p>
      ) : (
        <ul style={{ listStyle: "none", margin: 0, padding: 0, display: "grid", gap: 4 }}>
          {drawings.map((d) => (
            <li
              key={d.drawing_id} data-testid={`chart-drawing-row-${d.drawing_id}`}
              onClick={() => setSelectedDrawingId(d.drawing_id)}
              style={{
                display: "flex", alignItems: "center", gap: 8, fontSize: 12, padding: "6px 8px", borderRadius: 8, cursor: "pointer",
                background: selectedDrawingId === d.drawing_id ? "var(--bg-2)" : "transparent",
              }}
            >
              <span className="nv-mono" style={{ color: "var(--c-ink-3)" }}>{d.drawing_type === "TRENDLINE" ? "Trendline" : "Horizontal line"}</span>
              <span style={{ flex: 1, minWidth: 0, color: "var(--c-ink-4)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                {d.anchor_points.map((a) => `${a.date}@${fmtPrice(a.price)}`).join(" → ")}
              </span>
              <button
                type="button" data-testid={`chart-drawing-delete-${d.drawing_id}`}
                onClick={(e) => { e.stopPropagation(); void deleteSelected(d.drawing_id); }}
                aria-label="Delete drawing" className="rail-ico" style={{ width: 22, height: 22, borderRadius: 999 }}
              >
                ✕
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );

  const watchlist = (
    <div
      data-testid="chart-symbol-list"
      className={compact ? "nv-card" : undefined}
      style={{
        width: compact ? "auto" : 216, minWidth: compact ? 0 : 216, padding: 10, overflowY: "auto",
        maxHeight: compact ? 220 : undefined, background: "var(--bg-1)",
        borderRight: compact ? undefined : "1px solid var(--c-line)",
      }}
    >
      <input
        ref={searchRef}
        value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search symbol…"
        aria-label="Filter symbols" data-testid="chart-symbol-search"
        style={{ width: "100%", marginBottom: 8, padding: "7px 10px", borderRadius: 8, border: "1px solid var(--line-2)", background: "var(--bg-2)", color: "var(--c-ink)", fontSize: 12.5 }}
      />
      <p className="nv-eyebrow" style={{ margin: "0 0 6px" }}>Watchlist · {symbolRows.length}</p>
      {symbolRows.map((s) => {
        const active = symbol === s.symbol;
        return (
          <button
            key={s.symbol} type="button" data-testid={`chart-symbol-${s.symbol}`}
            onClick={() => setSymbol(s.symbol)}
            aria-current={active ? "true" : undefined}
            style={{
              display: "flex", justifyContent: "space-between", alignItems: "center", width: "100%", textAlign: "left",
              padding: "7px 8px", borderRadius: 8, border: 0, borderLeft: `2px solid ${active ? "var(--mint)" : "transparent"}`,
              cursor: "pointer", marginBottom: 2, fontSize: 12.5,
              background: active ? "var(--mint-soft)" : "transparent",
              color: active ? "var(--mint)" : "var(--c-ink-2)",
            }}
          >
            <span className="nv-mono">{s.symbol}</span>
            {active && lastClose != null ? (
              <span className="nv-mono" data-testid="chart-watchlist-active-price" style={{ fontSize: 10.5 }}>{fmtNum(lastClose)}</span>
            ) : (
              s.n_patterns > 0 ? <span className="nv-mono" style={{ fontSize: 10, color: "var(--c-ink-4)" }}>{s.n_patterns}</span> : null
            )}
          </button>
        );
      })}
      {symbolRows.length === 0 && <p style={{ fontSize: 12, color: "var(--c-ink-4)", margin: "6px 2px" }}>No symbol matches "{search}".</p>}
    </div>
  );

  const toolbar = (
    <Toolbar
      symbol={symbol ?? ""}
      exchange={exchange}
      onOpenSymbolSearch={() => searchRef.current?.focus()}
      lastClose={lastClose}
      change={change}
      changePct={changePct}
      statusBadge={statusBadge}
      timeframe={timeframe}
      timeframeOptions={timeframeOptions}
      onTimeframeChange={setTimeframe}
      chartType={chartType}
      onChartTypeChange={setChartType}
      indicatorCount={selectedIndicatorIds.length}
      onOpenIndicators={() => setIndicatorDialogOpen(true)}
      canUndo={historyRef.current.canUndo}
      canRedo={historyRef.current.canRedo}
      onUndo={() => void undo()}
      onRedo={() => void redo()}
      layoutName={openLayout?.name ?? "Unnamed"}
      layouts={layouts.map((l) => ({ id: l.layout_id, name: l.name, symbol: l.symbol }))}
      layoutDirty={layoutDirty}
      hasOpenLayout={!!openLayout}
      onSaveLayout={() => void onSaveLayout()}
      onSaveLayoutAs={() => void onSaveLayoutAs()}
      onRenameLayout={() => void onRenameLayout()}
      onDeleteLayout={() => void onDeleteLayout()}
      onOpenLayout={onOpenLayout}
      onFit={() => canvasRef.current?.fit()}
      dataViewOpen={showDataView}
      onToggleDataView={() => setShowDataView((v) => !v)}
      isFullscreen={isFullscreen}
      onToggleFullscreen={() => canvasRef.current?.toggleFullscreen()}
      compact={compact}
    />
  );

  const rail = (
    <DrawingRail
      activeTool={tool}
      onToolChange={(t) => { setTool(t); canvasRef.current?.cancelPending(); }}
      magnetOn={magnetOn}
      onToggleMagnet={() => setMagnetOn((v) => !v)}
      stayInDrawingMode={stayInDrawingMode}
      onToggleStayInDrawingMode={() => setStayInDrawingMode((v) => !v)}
      allLocked={drawingsLocked}
      onToggleLockAll={() => setDrawingsLocked((v) => !v)}
      allHidden={drawingsHidden}
      onToggleHideAll={() => setDrawingsHidden((v) => !v)}
      onRemoveAll={() => void removeAllDrawings()}
      removeAllDisabled={drawings.length === 0 || drawingsLocked}
      onDeleteSelected={() => void deleteSelected()}
      deleteDisabled={!selectedDrawingId || drawingsLocked}
      compact={compact}
    />
  );

  const bottomBar = (
    <BottomBar
      activeRange={activeRange}
      onSelectRange={onSelectRange}
      goToDateValue={goToDate}
      onGoToDate={onGoToDate}
      minDate={bars.length ? bars[0][0] : undefined}
      maxDate={bars.length ? bars[bars.length - 1][0] : undefined}
      adjOn
      onToggleAdj={() => { /* disabled: no raw series is exported yet (§38.7) */ }}
      adjDisabledReason="Kite daily bars are back-adjusted and no raw series is exported yet (§38.7)"
      scaleMode={scaleMode}
      onScaleModeChange={setScaleMode}
    />
  );

  const chartArea = (
    <Pending result={ohlcvRes} label="OHLCV">
      {() => (
        <ChartCanvas
          ref={canvasRef}
          symbol={symbol ?? ""}
          exchange={exchange}
          timeframeLabel={timeframe}
          bars={bars}
          incompleteDates={incompleteDates}
          chartType={chartType}
          scaleMode={scaleMode}
          indicators={indicators}
          selectedIndicatorIds={selectedIndicatorIds}
          hiddenIndicatorIds={hiddenIndicatorIds}
          panes={panes}
          onMovePane={movePane}
          onToggleMaximisePane={(id) => setMaximisedPaneId((cur) => (cur === id ? null : id))}
          onTogglePaneCollapsed={togglePaneCollapsed}
          onRemovePane={removePane}
          onPaneHeightChange={(id, h) => setPaneHeights((cur) => ({ ...cur, [id]: h }))}
          maximisedPaneId={maximisedPaneId}
          patterns={patternsForChart}
          hasAnyPatterns={chartPatterns.length > 0}
          selectedPatternId={selectedPatternId}
          onSelectPattern={onSelectPatternFromChart}
          onHoverPattern={() => { /* the tooltip lives in the canvas; the screen needs no hover state */ }}
          srBands={srBands}
          showLevels={showLevels}
          selectedSrBandId={selectedSrBandId}
          onSelectSrBand={onSelectSrBand}
          nearestLevel={nearestLevel}
          drawings={drawings}
          activeTool={tool}
          selectedDrawingId={selectedDrawingId}
          onSelectDrawing={setSelectedDrawingId}
          onCreateDrawing={(d) => void onCreateDrawing(d)}
          onBarClick={(bar) => setDrawer({ kind: "bar", bar })}
          magnetOn={magnetOn}
          drawingsHidden={drawingsHidden}
          drawingsLocked={drawingsLocked}
          visibleRange={visibleRange}
          catalogue={catalogue?.kind === "ok" ? catalogue.data : null}
          onHideIndicator={(id) => setHiddenIndicatorIds((cur) => (cur.includes(id) ? cur.filter((x) => x !== id) : [...cur, id]))}
          onRemoveIndicator={(id) => setSelectedIndicatorIds((cur) => cur.filter((x) => x !== id))}
          onOpenIndicatorProvenance={(id) => setDrawer({ kind: "indicator", id })}
        />
      )}
    </Pending>
  );

  const sidebar = (
    <Sidebar
      activeTab={sidebarTab}
      onTabChange={setSidebarTab}
      collapsed={sidebarCollapsed}
      onToggleCollapsed={() => setSidebarCollapsed((v) => !v)}
      panels={{ levels: levelsPanel, indicators: indicatorsPanel, patterns: patternsPanel }}
      footer={drawingsFooter}
      compact={compact}
    />
  );

  return (
    <Shell>
      {/* One provenance strip rather than a stack of full-width banners: on a charting screen the
          chart has to own the viewport, so the page heading and both notices share a single row.
          The wording is unchanged and stays in the DOM (and in the title/aria text) — the pill is
          what carries the weight visually, which makes the warning louder, not quieter. */}
      <div style={{ display: "flex", alignItems: "center", gap: 8, minWidth: 0 }}>
        <h2 className="nv-eyebrow" style={{ margin: 0, flex: "none" }}>Charts</h2>
        {fixture && (
          <div
            role="alert" data-testid="chart-banner-fixture"
            title="This snapshot is placeholder data for building the page — not real market data. No number here may be quoted, reported or acted on."
            style={{
              display: "flex", alignItems: "baseline", gap: 7, minWidth: 0, flex: "0 1 auto",
              border: "1px solid var(--danger-line)", background: "var(--danger-soft)", borderRadius: 999,
              padding: "3px 11px", color: "var(--c-ink)", fontSize: 11.5,
            }}
          >
            <b className="nv-mono" style={{ fontSize: 9.5, letterSpacing: ".1em", color: "var(--danger-hex)", flex: "none" }}>SYNTHETIC DEVELOPMENT DATA</b>
            <span style={{ minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", color: "var(--c-ink-2)" }}>
              This snapshot is placeholder data for building the page — <b>not real market data</b>. No number here may be quoted, reported or acted on.
            </span>
          </div>
        )}
        <div
          role="note"
          title={`Kite-derived prices, frozen research run ${txt(run.run_id)}. Not for redistribution, and not investment advice.`}
          style={{
            display: "flex", alignItems: "baseline", gap: 7, minWidth: 0, flex: "0 1 auto",
            border: "1px solid var(--c-line-strong)", background: "var(--bg-1)", borderRadius: 999,
            padding: "3px 11px", color: "var(--c-ink-2)", fontSize: 11.5,
          }}
        >
          <b className="nv-mono" style={{ fontSize: 9.5, letterSpacing: ".1em", color: "var(--c-ink)", flex: "none" }}>INTERNAL ONLY</b>
          <span style={{ minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
            Kite-derived prices, frozen research run {txt(run.run_id)}. Not for redistribution, and not investment advice.
          </span>
        </div>
      </div>

      {compact ? (
        <div data-testid="chart-workspace" style={{ display: "grid", gap: 10, minWidth: 0 }}>
          {toolbar}
          {rail}
          <div style={{ display: "flex", flexDirection: "column", height: 360, border: "1px solid var(--c-line)", borderRadius: 12, overflow: "hidden", minWidth: 0 }}>
            {chartArea}
          </div>
          {bottomBar}
          {watchlist}
          {sidebar}
        </div>
      ) : (
        <div
          data-testid="chart-workspace"
          style={{
            display: "flex", minWidth: 0, border: "1px solid var(--c-line)", borderRadius: 14, overflow: "hidden",
            height: "calc(100vh - 132px)", minHeight: 420, maxHeight: 900, background: "var(--bg-1)",
          }}
        >
          {watchlist}
          <div style={{ flex: 1, minWidth: 0, display: "flex", flexDirection: "column" }}>
            {toolbar}
            <div style={{ flex: 1, minHeight: 0, display: "flex", minWidth: 0 }}>
              {rail}
              <div style={{ flex: 1, minWidth: 0, display: "flex", flexDirection: "column" }}>{chartArea}</div>
            </div>
            {bottomBar}
          </div>
          {sidebar}
        </div>
      )}

      {ohlcvNotFound && (
        <div className="nv-card" role="alert" data-testid="charts-state-not_found" style={{ padding: 16 }}>
          <p style={{ margin: 0, fontSize: 13.5, color: "var(--c-ink-2)" }}>Unknown symbol.</p>
        </div>
      )}

      {showDataView && <DataView symbol={symbol ?? ""} bars={bars} patterns={chartPatterns} levels={showLevels ? levelPatterns : []} />}

      <IndicatorDialog
        open={indicatorDialogOpen}
        onClose={() => setIndicatorDialogOpen(false)}
        catalogue={catalogue}
        activeSeriesIds={selectedIndicatorIds}
        availableSeries={Object.fromEntries(Object.entries(indicators).map(([id, v]) => [id, v.values.length]))}
        onToggle={toggleIndicator}
        onShowProvenance={(id) => setDrawer({ kind: "indicator", id })}
      />

      {/* ── provenance drawer (B6) ── */}
      {drawer && symEntry && (
        <ProvenanceDrawer
          ctx={drawer} onClose={() => setDrawer(null)}
          runId={run.run_id} configHash={run.config_hash} generatedAt={run.generated_at}
          source={run.source} symEntry={symEntry}
          provenance={ohlcv ? ohlcv.provenance : null}
          indicators={indicators}
        />
      )}
      <span className="sr-only" data-testid="chart-history-state" data-undo={historyRef.current.canUndo ? "1" : "0"} data-redo={historyRef.current.canRedo ? "1" : "0"}>{historyTick}</span>
    </Shell>
  );
}

function Shell({ children }: { children: React.ReactNode }) {
  return (
    <div data-testid="charts-screen" className="px-4 pt-3 pb-4 lg:px-6" style={{ display: "grid", gap: 8, maxWidth: 1600, margin: "0 auto", minWidth: 0 }}>
      {children}
    </div>
  );
}
/* ── provenance drawer ───────────────────────────────────────────────────── */
function ProvenanceDrawer({ ctx, onClose, runId, configHash, generatedAt, source, symEntry, provenance, indicators }: {
  ctx: { kind: "status" } | { kind: "bar"; bar: Bar } | { kind: "indicator"; id: string } | { kind: "rule"; pattern: Pattern; ruleId: string };
  onClose: () => void; runId: string; configHash: string; generatedAt: string;
  source: RunPayload["source"]; symEntry: ManifestSymbolEntry; provenance: Record<string, unknown> | null;
  indicators: Record<string, IndicatorsPayload["indicators"][string]>;
}) {
  const title = ctx.kind === "status" ? "Provenance · data quality & PIT" : ctx.kind === "bar" ? `Provenance · ${ctx.bar[0]}` : ctx.kind === "indicator" ? `Provenance · ${ctx.id}` : `Provenance · rule ${ctx.ruleId}`;
  return (
    <>
      <div onClick={onClose} style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,.42)", zIndex: 60 }} />
      <aside
        data-testid="chart-provenance-drawer" role="dialog" aria-label={title}
        style={{ position: "fixed", top: 0, right: 0, bottom: 0, width: "min(420px, 94vw)", background: "var(--bg-1)", borderLeft: "1px solid var(--c-line)", boxShadow: "var(--shadow-pop)", zIndex: 61, display: "flex", flexDirection: "column" }}
      >
        <div style={{ padding: "16px 18px", borderBottom: "1px solid var(--c-line)", display: "flex", alignItems: "center", gap: 12 }}>
          <h3 className="nv-serif" style={{ fontSize: 16, margin: 0, flex: 1 }}>{title}</h3>
          <button onClick={onClose} aria-label="Close" className="rail-ico" style={{ width: 28, height: 28, borderRadius: 999 }}>✕</button>
        </div>
        <div style={{ padding: "14px 18px", overflowY: "auto", flex: 1, display: "grid", gap: 10, fontSize: 12.5 }}>
          <Row label="Provider" value={txt(source.provider)} testid="chart-provenance-provider" />
          <Row label="Series" value={txt(source.series)} />
          <Row label="Adjustment status" value={txt(source.adjustment_status)} testid="chart-provenance-adjustment" />
          <Row label="Run ID" value={txt(runId)} testid="chart-provenance-run" />
          <Row label="Config hash" value={txt(configHash)} testid="chart-provenance-confighash" />
          <Row label="Generated at" value={txt(generatedAt)} />
          <Row label="Data quality status" value={txt(symEntry.data_quality_status)} testid="chart-provenance-dq" />
          <Row label="PIT status" value={txt(symEntry.pit_status)} testid="chart-provenance-pit" />
          {provenance && Object.entries(provenance).map(([k, v]) => <Row key={k} label={k} value={txt(v)} />)}
          {ctx.kind === "bar" && (
            <>
              <div className="nv-hr" />
              <Row label="Open" value={fmtPrice(ctx.bar[1])} />
              <Row label="High" value={fmtPrice(ctx.bar[2])} />
              <Row label="Low" value={fmtPrice(ctx.bar[3])} />
              <Row label="Close" value={fmtPrice(ctx.bar[4])} />
              <Row label="Volume" value={String(ctx.bar[5])} />
            </>
          )}
          {ctx.kind === "indicator" && indicators[ctx.id] && (
            <>
              <div className="nv-hr" />
              <Row label="Warmup period" value={txt(indicators[ctx.id].contract.warmup_period)} />
              <Row label="Calculation version" value={txt(indicators[ctx.id].contract.calculation_version)} />
              <Row label="Missing-data policy" value={txt(indicators[ctx.id].contract.missing_data_policy)} />
              <Row label="Pane" value={txt(indicators[ctx.id].pane)} />
            </>
          )}
          {ctx.kind === "rule" && (
            <>
              <div className="nv-hr" />
              {(() => {
                const r = ctx.pattern.rules.find((x) => x.rule_id === ctx.ruleId);
                if (!r) return <p style={{ margin: 0, color: "var(--c-ink-4)" }}>Rule not found.</p>;
                return (
                  <>
                    <Row label="Result" value={txt(r.result)} />
                    <Row label="Observed" value={txt(r.observed)} />
                    <Row label="Threshold" value={txt(r.threshold)} />
                  </>
                );
              })()}
            </>
          )}
        </div>
      </aside>
    </>
  );
}

function Row({ label, value, testid }: { label: string; value: string; testid?: string }) {
  return (
    <div data-testid={testid} style={{ display: "grid", gridTemplateColumns: "minmax(110px, max-content) 1fr", gap: 10 }}>
      <span className="nv-mono" style={{ fontSize: 10, letterSpacing: ".05em", textTransform: "uppercase", color: "var(--c-ink-3)" }}>{label}</span>
      <span style={{ color: "var(--c-ink)", wordBreak: "break-word" }}>{value}</span>
    </div>
  );
}
