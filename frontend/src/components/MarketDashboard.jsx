import React, { useRef, useState } from "react";
import { Globe2, Sparkles, GripVertical, ChevronDown, RotateCcw } from "lucide-react";
import MarketTodaysTake from "@/components/MarketTodaysTake";
import MacroBar from "@/components/mfd/MacroBar";
import TodayStrategyCard from "@/components/mfd/TodayStrategyCard";
import SectorHeatmap from "@/components/mfd/SectorHeatmap";
import AlignedPicks from "@/components/mfd/AlignedPicks";
import WhatChanged from "@/components/mfd/WhatChanged";
import WeekendWatchlist from "@/components/mfd/WeekendWatchlist";
import MondayGamePlan from "@/components/mfd/MondayGamePlan";
import PositionalPicks from "@/components/PositionalPicks";
import PositionalTopPicks from "@/components/PositionalTopPicks";
import DeployVerdictStrip from "@/components/DeployVerdictStrip";
import TradeJournal from "@/components/TradeJournal";
import LiveEventFeed from "@/components/mfd/LiveEventFeed";
import { useDashboardLayout } from "@/hooks/useDashboardLayout";

/**
 * MarketDashboard — global, market-wide signals + actionable trade ideas.
 *
 * Sections are collapsible (click header) and drag-to-reorder.
 * Layout is persisted to localStorage ("market_dashboard_layout_v1").
 */

// ── Section definitions ────────────────────────────────────────────────────
// Content is a render function so components aren't mounted when collapsed.
const SECTION_DEFS = {
  market: {
    title: "The Market",
    subtitle: "Today's regime — what the macro is doing",
    render: () => <><DeployVerdictStrip /><MacroBar /></>,
  },
  strategy: {
    title: "The Strategy",
    subtitle: "Translated into bias, sizing, and the sectors to favour or avoid",
    render: () => <TodayStrategyCard />,
  },
  events: {
    title: "Live Events",
    subtitle: "Corporate events · AI impact signals · breakout detection · D-1 briefings",
    render: () => <LiveEventFeed />,
  },
  sectors: {
    title: "The Sectors",
    subtitle: "Macro tailwinds and headwinds with stock-level setups",
    render: () => <><SectorHeatmap /><AlignedPicks /><WhatChanged /><MondayGamePlan /></>,
  },
  trades: {
    title: "The Trades",
    subtitle: "Today's positional picks ranked by conviction · 5–30 day timeframe",
    render: () => <><PositionalTopPicks /><WeekendWatchlist /><PositionalPicks hideWhenWatchlistMode /></>,
  },
  journal: {
    title: "Trade Journal",
    subtitle: "Staged entries · exit ladder · live P&L · hedge guidance",
    render: () => <TradeJournal />,
  },
};

// ── Collapsible section wrapper ────────────────────────────────────────────

function Section({ id, n, title, subtitle, collapsed, onToggle, onDragStart, onDragOver, onDrop, isDragOver, children }) {
  return (
    <section
      id={`section-${id}`}
      className={`scroll-mt-32 rounded-2xl border transition-colors ${
        isDragOver
          ? "border-indigo-300 bg-indigo-50 dark:border-indigo-700/50 dark:bg-indigo-900/20"
          : "border-slate-100 bg-white dark:border-slate-700 dark:bg-slate-800"
      }`}
      draggable
      onDragStart={onDragStart}
      onDragOver={onDragOver}
      onDrop={onDrop}
      onDragEnd={(e) => e.currentTarget.style.opacity = "1"}
    >
      {/* Header — click to collapse, grip to drag */}
      <div
        className="flex items-center gap-2 px-4 py-3 cursor-pointer select-none group"
        onClick={onToggle}
      >
        {/* Drag grip */}
        <div
          className="text-slate-300 dark:text-slate-600 group-hover:text-slate-400 dark:group-hover:text-slate-400 transition-colors cursor-grab active:cursor-grabbing flex-shrink-0"
          onClick={(e) => e.stopPropagation()}
          onMouseDown={(e) => e.stopPropagation()}
        >
          <GripVertical className="w-4 h-4" />
        </div>

        {/* Section number */}
        <span className="text-[10px] font-mono font-bold uppercase tracking-wider text-slate-400 flex-shrink-0">
          §{n}
        </span>

        {/* Title + subtitle */}
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <h2 className="text-[13px] font-semibold text-slate-900 dark:text-white tracking-tight">
              {title}
            </h2>
            {collapsed && subtitle && (
              <span className="text-[10px] text-slate-400 truncate hidden sm:inline">
                — {subtitle}
              </span>
            )}
          </div>
          {!collapsed && subtitle && (
            <p className="text-[11px] text-slate-500 dark:text-slate-400 mt-0.5">{subtitle}</p>
          )}
        </div>

        {/* Collapse chevron */}
        <ChevronDown
          className={`w-4 h-4 text-slate-400 flex-shrink-0 transition-transform duration-200 ${
            collapsed ? "-rotate-90" : ""
          }`}
        />
      </div>

      {/* Collapsible body — CSS grid trick for smooth animation */}
      <div
        className="grid transition-[grid-template-rows] duration-200 ease-out"
        style={{ gridTemplateRows: collapsed ? "0fr" : "1fr" }}
      >
        <div className="overflow-hidden">
          <div className="px-4 pb-4 space-y-3">
            {children}
          </div>
        </div>
      </div>
    </section>
  );
}

// ── Section nav ────────────────────────────────────────────────────────────

function SectionNav({ order, collapsed, onToggle }) {
  return (
    <nav className="flex flex-wrap items-center gap-1 text-[11px] py-1" aria-label="Market sections">
      {order.map((id) => {
        const def = SECTION_DEFS[id];
        if (!def) return null;
        const isCollapsed = collapsed.includes(id);
        return (
          <a
            key={id}
            href={`#section-${id}`}
            onClick={(e) => {
              e.preventDefault();
              if (isCollapsed) {
                onToggle(id);
                setTimeout(() => {
                  document.getElementById(`section-${id}`)?.scrollIntoView({ behavior: "smooth", block: "start" });
                }, 220);
              } else {
                document.getElementById(`section-${id}`)?.scrollIntoView({ behavior: "smooth", block: "start" });
              }
            }}
            className={`px-2 py-1 rounded-md transition-colors ${
              isCollapsed
                ? "text-slate-400 line-through hover:text-slate-600 hover:no-underline hover:bg-slate-100"
                : "text-slate-600 dark:text-slate-400 hover:text-emerald-700 dark:hover:text-emerald-400 hover:bg-emerald-50 dark:hover:bg-emerald-900/20"
            }`}
          >
            {def.title}
          </a>
        );
      })}
    </nav>
  );
}

// ── Main component ─────────────────────────────────────────────────────────

export default function MarketDashboard() {
  const { order, collapsed, toggleCollapse, reorder, reset } = useDashboardLayout();
  const dragId = useRef(null);
  const [dragOverId, setDragOverId] = useState(null);

  function handleDragStart(id, e) {
    dragId.current = id;
    e.currentTarget.style.opacity = "0.5";
    e.dataTransfer.effectAllowed = "move";
  }

  function handleDragOver(id, e) {
    e.preventDefault();
    e.dataTransfer.dropEffect = "move";
    if (id !== dragOverId) setDragOverId(id);
  }

  function handleDrop(id, e) {
    e.preventDefault();
    setDragOverId(null);
    if (dragId.current) reorder(dragId.current, id);
    dragId.current = null;
  }

  function handleDragLeave() {
    setDragOverId(null);
  }

  return (
    <div
      className="p-4 sm:p-6 max-w-5xl mx-auto"
      data-testid="market-dashboard"
      onDragLeave={handleDragLeave}
      onDrop={() => { setDragOverId(null); dragId.current = null; }}
    >
      {/* Sticky Today's Take strip */}
      <MarketTodaysTake />

      {/* Sticky section nav */}
      <div className="sticky top-[72px] z-20 -mx-4 sm:-mx-6 px-4 sm:px-6 py-1 bg-[#F8FAFC] dark:bg-slate-950 border-b border-slate-100 dark:border-slate-800">
        <div className="max-w-5xl mx-auto flex items-center justify-between gap-2">
          <SectionNav order={order} collapsed={collapsed} onToggle={toggleCollapse} />
          <button
            onClick={reset}
            title="Reset layout"
            className="flex-shrink-0 p-1.5 text-slate-400 hover:text-indigo-600 hover:bg-indigo-50 rounded-lg transition-colors"
          >
            <RotateCcw className="w-3 h-3" />
          </button>
        </div>
      </div>

      {/* Page header */}
      <div className="flex items-start gap-3 pt-4 pb-5">
        <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-indigo-500 to-emerald-500 flex items-center justify-center text-white flex-shrink-0">
          <Globe2 className="w-5 h-5" strokeWidth={2} />
        </div>
        <div className="flex-1">
          <h1 className="text-2xl font-bold text-slate-900 dark:text-white tracking-tight">
            Market Dashboard
          </h1>
          <p className="text-[12px] text-slate-500 dark:text-slate-400 mt-0.5">
            Drag sections to reorder · click a header to collapse · reset to defaults with ↺
          </p>
        </div>
        <span className="hidden sm:inline-flex items-center gap-1 text-[10px] uppercase tracking-wider font-bold px-2 py-1 rounded bg-emerald-100 text-emerald-700 border border-emerald-200 self-start">
          <Sparkles className="w-3 h-3" /> Macro v1
        </span>
      </div>

      {/* Sections — rendered in user-defined order */}
      <div className="space-y-3">
        {order.map((id, idx) => {
          const def = SECTION_DEFS[id];
          if (!def) return null;
          const isCollapsed = collapsed.includes(id);
          return (
            <Section
              key={id}
              id={id}
              n={idx + 1}
              title={def.title}
              subtitle={def.subtitle}
              collapsed={isCollapsed}
              onToggle={() => toggleCollapse(id)}
              onDragStart={(e) => handleDragStart(id, e)}
              onDragOver={(e) => handleDragOver(id, e)}
              onDrop={(e) => handleDrop(id, e)}
              isDragOver={dragOverId === id}
            >
              {!isCollapsed && def.render()}
            </Section>
          );
        })}
      </div>
    </div>
  );
}
