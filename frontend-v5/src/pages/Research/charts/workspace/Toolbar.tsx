/**
 * The 56 px top bar (§38.3 item 1, design-1a-reference.md item 1): symbol and exchange, the last close with its
 * change, the data-quality/PIT pill, the interval group, chart type, indicators, and the window controls.
 * Presentational only — every value is a prop and every action a callback; ChartsScreen owns the state.
 *
 * Alert and Compare are rendered disabled with their reason (§38.19.2: no alert engine and no compare series
 * exist; alerts are step 7 of §38.19.3). No chart-theme control: the chart follows the app theme (D-6).
 *
 * Legacy test ids (`chart-timeframe-*`, `chart-fit`, `chart-fullscreen`, `chart-dataview-toggle`) are kept
 * deliberately — the controls moved into this bar, they did not change meaning, and the existing Playwright
 * suite addresses them by those ids.
 */
import { MenuButton, type MenuItem } from "./MenuButton";
import { CHART_TYPE_LABEL, TIMEFRAMES, type ChartType, type Timeframe } from "./types";

/** One interval button's availability. `reason` is required when `enabled` is false (§38.9 a11y). */
export interface TimeframeOption {
  id: Timeframe;
  enabled: boolean;
  reason?: string;
}

const TIMEFRAME_TESTID: Record<Timeframe, string> = {
  "1D": "chart-timeframe-daily", "1W": "chart-timeframe-weekly", "1M": "chart-timeframe-monthly",
};
const TIMEFRAME_SHORT: Record<Timeframe, string> = { "1D": "1D", "1W": "1W", "1M": "1M" };

export interface ToolbarProps {
  symbol: string;
  exchange: string;
  /** Opens the existing symbol search in the watchlist column; this button is only the trigger. */
  onOpenSymbolSearch: () => void;

  /** Last close of the series and its change against the previous bar. Null renders a dash, never a guess. */
  lastClose: number | null;
  change: number | null;
  changePct: number | null;

  /** The existing status chip element (PIT_UNVERIFIED etc.), rendered as-is. */
  statusBadge?: React.ReactNode;

  timeframe: Timeframe;
  timeframeOptions: TimeframeOption[];
  onTimeframeChange: (tf: Timeframe) => void;

  chartType: ChartType;
  onChartTypeChange: (t: ChartType) => void;

  indicatorCount: number;
  onOpenIndicators: () => void;

  canUndo: boolean;
  canRedo: boolean;
  onUndo: () => void;
  onRedo: () => void;

  /** §38.8: the open layout's name, or "Unnamed" before the chart has been saved once. */
  layoutName: string;
  /** Recent layouts, newest first, for the reopen list. */
  layouts: Array<{ id: string; name: string; symbol: string }>;
  layoutDirty: boolean;
  onSaveLayout: () => void;
  onSaveLayoutAs: () => void;
  onRenameLayout: () => void;
  onDeleteLayout: () => void;
  onOpenLayout: (id: string) => void;
  /** True once a layout is open, which is what makes rename and delete meaningful. */
  hasOpenLayout: boolean;

  onFit: () => void;
  dataViewOpen: boolean;
  onToggleDataView: () => void;
  isFullscreen: boolean;
  onToggleFullscreen: () => void;

  /** True when the caller has measured that not everything fits on one row (§38.3: "items that do not fit move
   *  into a More menu"). */
  compact?: boolean;
  className?: string;
}

const ALERT_REASON = "alerts need a live daily feed and an alert engine — neither is built";
const COMPARE_REASON = "comparing a second symbol is not built yet";

export default function Toolbar(props: ToolbarProps) {
  const {
    symbol, exchange, onOpenSymbolSearch, lastClose, change, changePct, statusBadge,
    timeframe, timeframeOptions, onTimeframeChange, chartType, onChartTypeChange,
    indicatorCount, onOpenIndicators, canUndo, canRedo, onUndo, onRedo,
    layoutName, layouts, layoutDirty, onSaveLayout, onSaveLayoutAs, onRenameLayout, onDeleteLayout,
    onOpenLayout, hasOpenLayout,
    onFit, dataViewOpen, onToggleDataView, isFullscreen, onToggleFullscreen, compact, className,
  } = props;

  const chartTypeItems: MenuItem[] = (Object.keys(CHART_TYPE_LABEL) as ChartType[]).map((ct) => ({
    id: ct,
    label: ct === "heikin_ashi" ? `${CHART_TYPE_LABEL[ct]} (transform)` : CHART_TYPE_LABEL[ct],
    selected: chartType === ct,
    onSelect: () => onChartTypeChange(ct),
    testId: `chart-toolbar-charttype-${ct}`,
  }));

  const moreItems: MenuItem[] = [
    { id: "fit", label: "Fit to data", onSelect: onFit, testId: "chart-toolbar-more-fit" },
    { id: "dataview", label: dataViewOpen ? "Hide data view" : "Data view", onSelect: onToggleDataView, testId: "chart-toolbar-more-dataview" },
    { id: "fullscreen", label: isFullscreen ? "Exit full screen" : "Full screen", onSelect: onToggleFullscreen, testId: "chart-toolbar-more-fullscreen" },
  ];

  const layoutItems: MenuItem[] = [
    { id: "save", label: hasOpenLayout ? "Save" : "Save…", onSelect: onSaveLayout, testId: "chart-layout-save" },
    { id: "save_as", label: "Save as…", onSelect: onSaveLayoutAs, testId: "chart-layout-save-as" },
    {
      id: "rename", label: "Rename…", onSelect: onRenameLayout, disabled: !hasOpenLayout,
      disabledReason: "save the layout first", testId: "chart-layout-rename",
    },
    {
      id: "delete", label: "Delete", onSelect: onDeleteLayout, disabled: !hasOpenLayout,
      disabledReason: "save the layout first", testId: "chart-layout-delete",
    },
    ...(layouts.length
      ? layouts.map((l) => ({
          id: `open:${l.id}`,
          label: `${l.name} · ${l.symbol}`,
          onSelect: () => onOpenLayout(l.id),
          testId: `chart-layout-open-${l.id}`,
        }))
      : [{ id: "none", label: "No saved layouts yet", disabled: true, disabledReason: "nothing saved yet", testId: "chart-layout-empty" }]),
  ];

  const up = change != null ? change >= 0 : null;
  const changeColor = up == null ? "var(--c-ink-3)" : up ? "var(--mint)" : "var(--danger-hex)";

  return (
    <div
      role="toolbar"
      aria-label="Chart toolbar"
      data-testid="chart-toolbar"
      className={className}
      style={{
        height: 56, minHeight: 56, display: "flex", alignItems: "center", gap: 6, padding: "0 10px",
        borderBottom: "1px solid var(--c-line)", background: "var(--bg-1)", flexWrap: "nowrap", overflow: "hidden",
      }}
    >
      <button
        type="button" data-testid="chart-toolbar-symbol" onClick={onOpenSymbolSearch}
        aria-label={`Change symbol — currently ${symbol || "none"}`} title="Change symbol"
        style={{ display: "flex", alignItems: "baseline", gap: 6, background: "none", border: 0, cursor: "pointer", padding: "0 2px", flex: "none" }}
      >
        <span style={{ fontSize: 17, fontWeight: 600, letterSpacing: "-.01em", color: "var(--c-ink)" }}>{symbol || "—"}</span>
        <span className="nv-mono" style={{ fontSize: 10, color: "var(--c-ink-4)" }}>{exchange}</span>
      </button>

      <span data-testid="chart-toolbar-price" className="nv-mono nv-num" style={{ fontSize: 20, fontWeight: 500, color: "var(--c-ink)", flex: "none" }}>
        {lastClose != null ? lastClose.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 }) : "—"}
      </span>
      <span data-testid="chart-toolbar-change" className="nv-mono nv-num" style={{ fontSize: 12, color: changeColor, flex: "none", whiteSpace: "nowrap" }}>
        {change != null ? `${change >= 0 ? "+" : ""}${change.toFixed(2)}` : "—"}
        {changePct != null ? ` (${changePct >= 0 ? "+" : ""}${changePct.toFixed(2)}%)` : ""}
      </span>

      {statusBadge}

      <div style={{ width: 1, alignSelf: "stretch", margin: "14px 4px", background: "var(--c-line)" }} />

      <div role="group" aria-label="Interval" data-testid="chart-timeframe-group" style={{ display: "flex", gap: 2, flex: "none" }}>
        {TIMEFRAMES.map((tf) => {
          const opt = timeframeOptions.find((o) => o.id === tf) ?? { id: tf, enabled: true };
          const active = timeframe === tf;
          return (
            <button
              key={tf}
              type="button"
              data-testid={TIMEFRAME_TESTID[tf]}
              onClick={() => opt.enabled && onTimeframeChange(tf)}
              disabled={!opt.enabled}
              aria-disabled={!opt.enabled || undefined}
              aria-pressed={active}
              aria-label={opt.enabled ? `${TIMEFRAME_SHORT[tf]} interval` : `${TIMEFRAME_SHORT[tf]} interval — disabled, ${opt.reason}`}
              title={opt.enabled ? `${TIMEFRAME_SHORT[tf]} interval` : `${TIMEFRAME_SHORT[tf]} — ${opt.reason}`}
              style={{
                padding: "5px 10px", borderRadius: 7, border: "1px solid transparent", fontSize: 11.5, fontFamily: "var(--mono)",
                background: active ? "var(--bg-4, var(--bg-3))" : "transparent",
                color: !opt.enabled ? "var(--c-ink-4)" : active ? "var(--c-ink)" : "var(--c-ink-2)",
                cursor: opt.enabled ? "pointer" : "not-allowed",
              }}
            >
              {TIMEFRAME_SHORT[tf]}
            </button>
          );
        })}
      </div>
      <MenuButton
        label={<>{CHART_TYPE_LABEL[chartType]} <Chevron /></>}
        ariaLabel="Chart type" title="Chart type" items={chartTypeItems} testId="chart-toolbar-charttype"
      />

      <button
        type="button" data-testid="chart-toolbar-indicators" onClick={onOpenIndicators}
        aria-label="Indicators" title="Add or edit indicators" className="nv-btn" style={{ flex: "none" }}
      >
        Indicators{indicatorCount > 0 ? <span className="nv-mono" data-testid="chart-toolbar-indicators-count" style={{ marginLeft: 6, fontSize: 10, color: "var(--c-ink-4)" }}>{indicatorCount}</span> : null}
      </button>

      <button
        type="button" data-testid="chart-toolbar-alert" disabled aria-disabled="true"
        aria-label={`Alert — disabled, ${ALERT_REASON}`} title={`Alert — ${ALERT_REASON}`}
        className="nv-btn" style={{ opacity: 0.45, cursor: "not-allowed", flex: "none" }}
      >
        Alert
      </button>
      <button
        type="button" data-testid="chart-toolbar-compare" disabled aria-disabled="true"
        aria-label={`Compare — disabled, ${COMPARE_REASON}`} title={`Compare — ${COMPARE_REASON}`}
        className="nv-btn" style={{ opacity: 0.45, cursor: "not-allowed", flex: "none" }}
      >
        Compare
      </button>

      <div style={{ width: 1, alignSelf: "stretch", margin: "14px 4px", background: "var(--c-line)" }} />

      <button
        type="button" data-testid="chart-toolbar-undo" onClick={onUndo} disabled={!canUndo}
        aria-label="Undo" title={canUndo ? "Undo (Ctrl+Z)" : "Nothing to undo"} className="rail-ico"
        style={{ width: 32, height: 32, borderRadius: 9, flex: "none", opacity: canUndo ? 1 : 0.4, cursor: canUndo ? "pointer" : "not-allowed" }}
      >
        ↶
      </button>
      <button
        type="button" data-testid="chart-toolbar-redo" onClick={onRedo} disabled={!canRedo}
        aria-label="Redo" title={canRedo ? "Redo (Ctrl+Shift+Z)" : "Nothing to redo"} className="rail-ico"
        style={{ width: 32, height: 32, borderRadius: 9, flex: "none", opacity: canRedo ? 1 : 0.4, cursor: canRedo ? "pointer" : "not-allowed" }}
      >
        ↷
      </button>

      <div style={{ width: 1, alignSelf: "stretch", margin: "14px 4px", background: "var(--c-line)" }} />

      <MenuButton
        label={<><span data-testid="chart-toolbar-layout-name">{layoutName}</span>{layoutDirty ? <span data-testid="chart-toolbar-layout-dirty" title="Unsaved changes" aria-label="Unsaved changes" style={{ marginLeft: 4, color: "var(--amber)" }}>•</span> : null} <Chevron /></>}
        ariaLabel="Layouts" title="Saved layouts" testId="chart-toolbar-layouts"
        items={layoutItems}
      />

      <span style={{ marginLeft: "auto" }} />

      {!compact && (
        <>
          <button type="button" data-testid="chart-fit" onClick={onFit} aria-label="Fit to data" title="Fit to data" className="rail-ico" style={{ width: 32, height: 32, borderRadius: 9, flex: "none" }}>⤢</button>
          <button
            type="button" data-testid="chart-dataview-toggle" onClick={onToggleDataView} aria-pressed={dataViewOpen}
            aria-label="Data view" title="Data view — the same bars as a table" className="rail-ico"
            style={{ width: 32, height: 32, borderRadius: 9, flex: "none" }}
          >
            ▤
          </button>
          <button
            type="button" data-testid="chart-fullscreen" onClick={onToggleFullscreen} aria-pressed={isFullscreen}
            aria-label={isFullscreen ? "Exit full screen" : "Full screen"} title={isFullscreen ? "Exit full screen" : "Full screen"}
            className="rail-ico" style={{ width: 32, height: 32, borderRadius: 9, flex: "none" }}
          >
            ⛶
          </button>
        </>
      )}
      {compact && (
        <MenuButton label="More" ariaLabel="More toolbar actions" title="More" items={moreItems} testId="chart-toolbar-more" />
      )}
    </div>
  );
}

function Chevron() {
  return <span aria-hidden="true" style={{ fontSize: 9, marginLeft: 4, opacity: 0.7 }}>▾</span>;
}
