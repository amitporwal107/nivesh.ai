/**
 * Pane controls (§38.5): "Each pane can be moved up or down, maximised and restored, collapsed or removed, and
 * resized with a draggable divider." Two pieces, both presentational:
 *   - `PaneControls` — the header button cluster for one pane (move up/down, maximise/restore, collapse, remove).
 *   - `PaneDivider` — the draggable handle between two panes; owns only pointer-drag arithmetic and reports the
 *     new height through `onHeightChange`, so the caller (ChartCanvas/W1b) decides how that height is stored and
 *     applied to the underlying lightweight-charts pane.
 */
import { useCallback, useEffect, useRef } from "react";

export interface PaneControlsProps {
  paneId: string;
  /** e.g. "Price", "RSI 14", "MACD 12/26/9" — whatever the legend row for this pane already shows. */
  title: string;
  /** This pane's position among the chart's panes, 0-based (price pane is conventionally 0). */
  index: number;
  /** Total pane count — move-up is disabled at index 0, move-down at the last index. */
  count: number;
  maximised: boolean;
  collapsed: boolean;
  onMoveUp: () => void;
  onMoveDown: () => void;
  onToggleMaximise: () => void;
  onToggleCollapse: () => void;
  /** Absent for the price pane, which cannot be removed the way an indicator pane can. */
  onRemove?: () => void;
  /** Overrides the index/count arithmetic when a pane may not move into every slot — the price pane is pinned
   *  first (§38.5), so the pane above it is not a legal target for the one below. Omitted = derive from index. */
  canMoveUp?: boolean;
  canMoveDown?: boolean;
  /** False for the price pane: collapsing the chart's own pane is not a thing the layout supports. */
  collapsible?: boolean;
  className?: string;
}

export function PaneControls(props: PaneControlsProps) {
  const {
    paneId, title, index, count, maximised, collapsed, onMoveUp, onMoveDown, onToggleMaximise, onToggleCollapse,
    onRemove, canMoveUp: canMoveUpProp, canMoveDown: canMoveDownProp, collapsible = true, className,
  } = props;
  const canMoveUp = (canMoveUpProp ?? index > 0) && !maximised;
  const canMoveDown = (canMoveDownProp ?? index < count - 1) && !maximised;

  return (
    <div
      data-testid={`chart-pane-controls-${paneId}`}
      className={className}
      role="group"
      aria-label={`${title} pane controls`}
      style={{ display: "flex", alignItems: "center", gap: 2 }}
    >
      <PaneIcon testId={`chart-pane-${paneId}-up`} label="Move pane up" icon="↑" onClick={onMoveUp} disabled={!canMoveUp} />
      <PaneIcon testId={`chart-pane-${paneId}-down`} label="Move pane down" icon="↓" onClick={onMoveDown} disabled={!canMoveDown} />
      <PaneIcon
        testId={`chart-pane-${paneId}-maximise`} label={maximised ? "Restore pane" : "Maximise pane"}
        icon={maximised ? "⤡" : "⤢"} onClick={onToggleMaximise} pressed={maximised}
      />
      {collapsible && (
        <PaneIcon
          testId={`chart-pane-${paneId}-collapse`} label={collapsed ? "Expand pane" : "Collapse pane"}
          icon={collapsed ? "▸" : "▾"} onClick={onToggleCollapse} pressed={collapsed} disabled={maximised}
        />
      )}
      {onRemove && (
        <PaneIcon testId={`chart-pane-${paneId}-remove`} label="Remove pane" icon="✕" onClick={onRemove} disabled={maximised} />
      )}
    </div>
  );
}

function PaneIcon({ testId, label, icon, onClick, disabled, pressed }: {
  testId: string; label: string; icon: string; onClick: () => void; disabled?: boolean; pressed?: boolean;
}) {
  return (
    <button
      type="button" data-testid={testId} aria-label={label} title={label} aria-pressed={pressed}
      onClick={onClick} disabled={disabled}
      className={`rail-ico${pressed ? " on" : ""}`}
      style={{ width: 22, height: 22, borderRadius: 6, fontSize: 11, opacity: disabled ? 0.35 : 1, cursor: disabled ? "not-allowed" : "pointer" }}
    >
      {icon}
    </button>
  );
}

export interface PaneDividerProps {
  paneId: string;
  height: number;
  minHeight?: number;
  maxHeight?: number;
  /** Called continuously while dragging (so the caller can live-resize) and once more on release with the final
   *  value — the caller decides whether to treat the final call specially (e.g. persist to a saved layout). */
  onHeightChange: (height: number) => void;
  className?: string;
}

/** The draggable resize handle between two panes. Pointer-based (not HTML5 drag-and-drop, which is a poor fit for
 *  continuous resize) — a `pointerdown` on the handle starts tracking `pointermove`/`pointerup` on `window`, so
 *  the drag keeps working even if the pointer leaves the thin handle strip. */
export function PaneDivider({ paneId, height, minHeight = 60, maxHeight = 2000, onHeightChange, className }: PaneDividerProps) {
  const startRef = useRef<{ y: number; height: number } | null>(null);

  const clamp = useCallback((h: number) => Math.min(maxHeight, Math.max(minHeight, h)), [minHeight, maxHeight]);

  useEffect(() => {
    const onMove = (e: PointerEvent) => {
      const start = startRef.current;
      if (!start) return;
      onHeightChange(clamp(start.height + (e.clientY - start.y)));
    };
    const onUp = (e: PointerEvent) => {
      const start = startRef.current;
      if (!start) return;
      onHeightChange(clamp(start.height + (e.clientY - start.y)));
      startRef.current = null;
    };
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
    return () => { window.removeEventListener("pointermove", onMove); window.removeEventListener("pointerup", onUp); };
  }, [clamp, onHeightChange]);

  return (
    <div
      data-testid={`chart-pane-divider-${paneId}`}
      className={className}
      role="separator"
      aria-orientation="horizontal"
      aria-label={`Resize ${paneId} pane`}
      title={`Resize ${paneId} pane`}
      aria-valuenow={height}
      aria-valuemin={minHeight}
      aria-valuemax={maxHeight}
      tabIndex={0}
      onPointerDown={(e) => { startRef.current = { y: e.clientY, height }; }}
      onKeyDown={(e) => {
        if (e.key === "ArrowUp") onHeightChange(clamp(height - 10));
        else if (e.key === "ArrowDown") onHeightChange(clamp(height + 10));
      }}
      style={{ height: 8, width: "100%", cursor: "row-resize", background: "transparent", touchAction: "none" }}
    >
      <div style={{ height: 2, marginTop: 3, borderRadius: 999, background: "var(--c-line-strong)" }} />
    </div>
  );
}
