/**
 * The 44 px vertical drawing rail (§38.6, design-1a-reference.md item 3). W1 (§38.12) wires the two v1 tools —
 * trendline and horizontal line — plus select; every other §38.6 P0 tool is listed in the "More tools" menu,
 * disabled with its reason. The modifiers (magnet, stay-in-drawing-mode, lock all, hide all, remove all) are live
 * in W1 because they act on drawings that already exist.
 *
 * The three active tools keep the screen's original test ids (`chart-tool-select` / `-trendline` / `-horizontal`)
 * and the delete button keeps `chart-tool-delete`: the controls moved from a horizontal toolbar into this rail,
 * but they are the same controls.
 *
 * Below 1024 px the rail folds into a single "Draw" menu (§38.3).
 */
import { MenuButton, type MenuItem } from "./MenuButton";

export type DrawingTool =
  | "trendline" | "horizontal_line"
  | "ray" | "extended_line" | "horizontal_ray" | "vertical_line"
  | "rectangle" | "sr_zone"
  | "fib_retracement"
  | "text"
  | "measure_price" | "measure_date"
  | "target_line" | "invalidation_line";

const W3_REASON = "coming in W3";

/** Every §38.6 P0 tool that is not one of W1's two, listed so the rail shows the full set and says what is next. */
const LATER_TOOLS: Array<{ id: DrawingTool; label: string }> = [
  { id: "ray", label: "Ray" },
  { id: "extended_line", label: "Extended line" },
  { id: "horizontal_ray", label: "Horizontal ray" },
  { id: "vertical_line", label: "Vertical date marker" },
  { id: "rectangle", label: "Rectangle" },
  { id: "sr_zone", label: "Support/resistance zone" },
  { id: "fib_retracement", label: "Fibonacci retracement" },
  { id: "text", label: "Text" },
  { id: "measure_price", label: "Price range" },
  { id: "measure_date", label: "Date range" },
  { id: "target_line", label: "Manual target line" },
  { id: "invalidation_line", label: "Manual invalidation line" },
];

export type ActiveTool = "select" | "trendline" | "horizontal_line";

export interface DrawingRailProps {
  activeTool: ActiveTool;
  onToolChange: (tool: ActiveTool) => void;

  magnetOn: boolean;
  onToggleMagnet: () => void;
  stayInDrawingMode: boolean;
  onToggleStayInDrawingMode: () => void;
  allLocked: boolean;
  onToggleLockAll: () => void;
  allHidden: boolean;
  onToggleHideAll: () => void;
  /** Fires only after the caller's own confirmation step (§38.6: "remove all (asks for confirmation)"). */
  onRemoveAll: () => void;
  removeAllDisabled?: boolean;

  /** Deletes the currently selected drawing; disabled when nothing is selected. */
  onDeleteSelected: () => void;
  deleteDisabled?: boolean;

  compact?: boolean;
  className?: string;
}

export default function DrawingRail(props: DrawingRailProps) {
  const {
    activeTool, onToolChange, magnetOn, onToggleMagnet, stayInDrawingMode, onToggleStayInDrawingMode,
    allLocked, onToggleLockAll, allHidden, onToggleHideAll, onRemoveAll, removeAllDisabled,
    onDeleteSelected, deleteDisabled, compact, className,
  } = props;

  const laterItems: MenuItem[] = LATER_TOOLS.map((t) => ({
    id: t.id, label: t.label, disabled: true, disabledReason: W3_REASON, testId: `chart-rail-tool-${t.id}`,
  }));

  if (compact) {
    const items: MenuItem[] = [
      { id: "select", label: "Select", selected: activeTool === "select", onSelect: () => onToolChange("select"), testId: "chart-tool-select" },
      { id: "trendline", label: "Trendline", selected: activeTool === "trendline", onSelect: () => onToolChange("trendline"), testId: "chart-tool-trendline" },
      { id: "horizontal_line", label: "Horizontal line", selected: activeTool === "horizontal_line", onSelect: () => onToolChange("horizontal_line"), testId: "chart-tool-horizontal" },
      ...laterItems,
    ];
    return (
      <div className={className} data-testid="chart-rail-compact" style={{ display: "flex", alignItems: "center", gap: 6, padding: "4px 8px" }}>
        <MenuButton label="Draw" ariaLabel="Drawing tools" items={items} testId="chart-rail-draw-button" />
        <button
          type="button" data-testid="chart-tool-delete" onClick={onDeleteSelected} disabled={deleteDisabled}
          aria-label="Delete selected drawing" title="Delete the selected drawing" className="nv-btn"
          style={{ opacity: deleteDisabled ? 0.45 : 1 }}
        >
          Delete
        </button>
      </div>
    );
  }

  return (
    <div
      role="toolbar"
      aria-label="Drawing tools"
      aria-orientation="vertical"
      data-testid="chart-rail"
      className={className}
      style={{ width: 44, minWidth: 44, display: "flex", flexDirection: "column", alignItems: "center", gap: 2, padding: "8px 0", borderRight: "1px solid var(--c-line)", background: "var(--bg-1)", overflowY: "auto" }}
    >
      <RailIcon icon="↖" label="Select" active={activeTool === "select"} onClick={() => onToolChange("select")} testId="chart-tool-select" />
      <RailIcon icon="／" label="Trendline" active={activeTool === "trendline"} onClick={() => onToolChange("trendline")} testId="chart-tool-trendline" title="Trendline (Alt+T) — two clicks" />
      <RailIcon icon="—" label="Horizontal line" active={activeTool === "horizontal_line"} onClick={() => onToolChange("horizontal_line")} testId="chart-tool-horizontal" title="Horizontal line (Alt+H) — one click" />

      <MenuButton
        bare
        label={<span aria-hidden="true" style={{ display: "inline-flex", alignItems: "center", justifyContent: "center", width: 36, height: 30, fontSize: 13, color: "var(--c-ink-3)" }}>⋯</span>}
        ariaLabel="More drawing tools" title="More drawing tools" items={laterItems} testId="chart-rail-more-tools"
      />

      <div style={{ height: 1, width: 28, background: "var(--c-line)", margin: "6px 0" }} />

      <RailIcon icon="⊹" label="Magnet" active={magnetOn} onClick={onToggleMagnet} testId="chart-rail-magnet" title={magnetOn ? "Magnet on — snaps anchors to O/H/L/C" : "Magnet off"} />
      <RailIcon icon="✎" label="Stay in drawing mode" active={stayInDrawingMode} onClick={onToggleStayInDrawingMode} testId="chart-rail-stay" title={stayInDrawingMode ? "Stays in the tool after each drawing" : "Returns to Select after each drawing"} />
      <RailIcon icon={allLocked ? "🔒" : "🔓"} label={allLocked ? "Unlock all drawings" : "Lock all drawings"} active={allLocked} onClick={onToggleLockAll} testId="chart-rail-lock-all" title={allLocked ? "Drawings are locked — unlock to edit" : "Lock all drawings"} />
      <RailIcon icon={allHidden ? "🙈" : "👁"} label={allHidden ? "Show all drawings" : "Hide all drawings"} active={allHidden} onClick={onToggleHideAll} testId="chart-rail-hide-all" title={allHidden ? "Drawings are hidden — nothing was deleted" : "Hide all drawings (nothing is deleted)"} />

      <div style={{ height: 1, width: 28, background: "var(--c-line)", margin: "6px 0" }} />

      <RailIcon icon="✕" label="Delete selected drawing" active={false} disabled={deleteDisabled} onClick={onDeleteSelected} testId="chart-tool-delete" title="Delete the selected drawing (Del)" />
      <RailIcon icon="🗑" label="Remove all drawings" active={false} disabled={removeAllDisabled} onClick={onRemoveAll} testId="chart-rail-remove-all" title="Remove all drawings — asks for confirmation" />
    </div>
  );
}

function RailIcon({ icon, label, active, disabled, onClick, testId, title }: {
  icon: string; label: string; active: boolean; disabled?: boolean; onClick: () => void; testId: string; title?: string;
}) {
  return (
    <button
      type="button" data-testid={testId} onClick={onClick} disabled={disabled}
      aria-label={label} aria-pressed={active} title={title ?? label}
      className={`rail-ico${active ? " on" : ""}`}
      style={{
        width: 34, height: 34, borderRadius: 9, fontSize: 14, flex: "none",
        opacity: disabled ? 0.4 : 1, cursor: disabled ? "not-allowed" : "pointer",
        background: active ? "var(--mint-soft)" : undefined, color: active ? "var(--mint)" : undefined,
      }}
    >
      {icon}
    </button>
  );
}
