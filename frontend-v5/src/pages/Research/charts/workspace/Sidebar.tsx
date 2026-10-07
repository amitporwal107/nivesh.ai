/**
 * The right sidebar shell (§38.3 item 6, design-1a-reference.md item 8): collapsible, three tabs —
 * LEVELS / INDICATORS / PATTERNS, with Patterns open by default. Below 1024 px it becomes a bottom sheet
 * (§38.3: "the sidebar becomes a bottom sheet").
 *
 * This component owns only the shell (tabs + collapse/expand + the sheet/panel chrome). The per-tab content and
 * the permanent footer (the "your drawings" list, which the design keeps below the tabs rather than inside one)
 * are supplied by the caller and rendered verbatim; Sidebar never inspects them.
 *
 * Provenance is deliberately not a tab: §38.2 keeps it one click away behind the status pill, and the drawer is
 * already built. A user-editable watchlist is still P1, so the left column lists the snapshot's symbols instead
 * of a tab here.
 */
import type { SidebarTab } from "./types";
import { SIDEBAR_TABS } from "./types";

const TAB_LABEL: Record<SidebarTab, string> = { levels: "Levels", indicators: "Indicators", patterns: "Patterns" };

export interface SidebarProps {
  activeTab: SidebarTab;
  onTabChange: (tab: SidebarTab) => void;
  collapsed: boolean;
  onToggleCollapsed: () => void;
  /** One ReactNode per tab, rendered only when that tab is active. */
  panels: Partial<Record<SidebarTab, React.ReactNode>>;
  /** Rendered under the active panel on every tab (the design's "YOUR DRAWINGS · n" list). */
  footer?: React.ReactNode;
  /** True below the 1024 px breakpoint — renders as a bottom sheet instead of a right rail. The breakpoint check
   *  itself belongs to the caller (same convention as Toolbar/DrawingRail's `compact`). */
  compact?: boolean;
  className?: string;
}

export default function Sidebar(props: SidebarProps) {
  const { activeTab, onTabChange, collapsed, onToggleCollapsed, panels, footer, compact, className } = props;

  const tabsRow = (
    <div role="tablist" aria-label="Chart sidebar sections" data-testid="chart-sidebar-tabs" style={{ display: "flex", gap: 2, padding: "8px 8px 0" }}>
      {SIDEBAR_TABS.map((tab) => (
        <button
          key={tab}
          type="button"
          role="tab"
          data-testid={`chart-sidebar-tab-${tab}`}
          aria-selected={activeTab === tab}
          aria-label={TAB_LABEL[tab]}
          title={TAB_LABEL[tab]}
          onClick={() => onTabChange(tab)}
          style={{
            flex: "1 1 0", minWidth: 0, padding: "7px 4px", fontSize: 11, fontFamily: "var(--sans)",
            border: 0, borderBottom: activeTab === tab ? "2px solid var(--mint)" : "2px solid transparent",
            background: "none", color: activeTab === tab ? "var(--c-ink)" : "var(--c-ink-3)",
            cursor: "pointer", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis",
            letterSpacing: ".06em", textTransform: "uppercase",
          }}
        >
          {TAB_LABEL[tab]}
        </button>
      ))}
    </div>
  );

  const collapseButton = (
    <button
      type="button" data-testid="chart-sidebar-collapse" onClick={onToggleCollapsed}
      aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"} aria-pressed={collapsed}
      title={collapsed ? "Expand sidebar" : "Collapse sidebar — gives the chart the full width"}
      className="rail-ico" style={{ width: 28, height: 28, borderRadius: 8, flex: "none" }}
    >
      {compact ? (collapsed ? "▲" : "▼") : (collapsed ? "◂" : "▸")}
    </button>
  );

  const body = (
    <div data-testid="chart-sidebar-panel" style={{ padding: compact ? 10 : 12, overflowY: "auto", flex: 1, display: "grid", gap: 12, alignContent: "start" }}>
      {panels[activeTab]}
      {footer}
    </div>
  );

  if (compact) {
    return (
      <div
        data-testid="chart-sidebar-sheet" className={className}
        style={{
          background: "var(--bg-1)", borderTop: "1px solid var(--c-line-strong)",
          maxHeight: collapsed ? 44 : "50vh", overflow: "hidden", display: "flex", flexDirection: "column",
          transition: "max-height .18s ease",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", padding: "4px 8px 0" }}>
          <span style={{ flex: 1, minWidth: 0 }}>{!collapsed && tabsRow}</span>
          {collapseButton}
        </div>
        {!collapsed && body}
      </div>
    );
  }

  return (
    <div
      data-testid="chart-sidebar" className={className}
      style={{
        width: collapsed ? 40 : 300, minWidth: collapsed ? 40 : 260, borderLeft: "1px solid var(--c-line)",
        background: "var(--bg-1)", display: "flex", flexDirection: "column", transition: "width .15s ease", overflow: "hidden",
      }}
    >
      <div style={{ display: "flex", alignItems: "center", padding: "6px 6px 0", justifyContent: collapsed ? "center" : "flex-end" }}>
        {collapseButton}
      </div>
      {!collapsed && (
        <>
          {tabsRow}
          {body}
        </>
      )}
    </div>
  );
}
