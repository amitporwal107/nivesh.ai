import React from "react";
import { Globe2, Sparkles } from "lucide-react";
import MacroBar from "@/components/mfd/MacroBar";
import TodayStrategyCard from "@/components/mfd/TodayStrategyCard";
import SectorHeatmap from "@/components/mfd/SectorHeatmap";
import AlignedPicks from "@/components/mfd/AlignedPicks";
import WhatChanged from "@/components/mfd/WhatChanged";
import WeekendWatchlist from "@/components/mfd/WeekendWatchlist";
import MondayGamePlan from "@/components/mfd/MondayGamePlan";
import PositionalPicks from "@/components/PositionalPicks";

/**
 * MarketDashboard — global, market-wide signals + actionable trade ideas.
 *
 * Distinct from the Advisor dashboard (which is per-client) and the
 * Client Portfolio (which is one client's holdings). This page answers:
 *
 *   "What is the market doing right now, and what should I trade?"
 *
 * Composed entirely of existing components — no new data fetches.
 *
 *   ┌──────────────────────────────────────────────────────────────┐
 *   │ 🌍 Macro context  (regime + pre-open + values + confidence)   │
 *   ├──────────────────────────────────────────────────────────────┤
 *   │ 📊 Sector tilt heatmap                                        │
 *   ├──────────────────────────────────────────────────────────────┤
 *   │ ⚡ Positional trade ideas (5–30d)                             │
 *   └──────────────────────────────────────────────────────────────┘
 */
export default function MarketDashboard() {
  return (
    <div className="p-4 sm:p-6 space-y-4 max-w-6xl mx-auto" data-testid="market-dashboard">
      {/* Page header */}
      <div className="flex items-start gap-3 pb-2">
        <div className="w-12 h-12 rounded-xl bg-gradient-to-br from-indigo-500 to-emerald-500 flex items-center justify-center text-white">
          <Globe2 className="w-6 h-6" strokeWidth={2} />
        </div>
        <div className="flex-1">
          <h1 className="text-2xl sm:text-3xl font-bold text-slate-900 tracking-tight">
            Market Dashboard
          </h1>
          <p className="text-[12px] text-slate-500 mt-0.5">
            Macro regime, sector tilt, and positional trade ideas — refreshed daily after the 18:35 IST cron.
          </p>
        </div>
        <span className="hidden sm:inline-flex items-center gap-1 text-[10px] uppercase tracking-wider font-bold px-2 py-1 rounded bg-emerald-100 text-emerald-700 border border-emerald-200">
          <Sparkles className="w-3 h-3" /> Macro v1
        </span>
      </div>

      {/* 1. Macro context bar */}
      <MacroBar />

      {/* 1b. Today's actionable strategy — converts macro state into a
              "what should I do today?" answer. */}
      <TodayStrategyCard />

      {/* 2. Sector heatmap */}
      <SectorHeatmap />

      {/* 2b. Macro-aligned setups — preview of stocks in tailwind sectors. */}
      <AlignedPicks />

      {/* 2c. What changed since yesterday — diff vs prior trading day. */}
      <WhatChanged />

      {/* 2d. Monday game plan — synthesises macro + watchlist into a
              single "what to do on Monday" card. Auto-hides on a regular
              trading day; shows on weekends + Indian market holidays. */}
      <MondayGamePlan />

      {/* 3. Positional trade ideas — single umbrella for all positional
              content. On a weekend / Indian market holiday this renders
              the 4-bucket WeekendWatchlist (Friday's data). On a live
              trading day with signals, it renders today's actionable
              picks. PositionalPicks self-gates: it hides when there are
              no actionable picks AND we're in weekend mode (so we don't
              double up with WeekendWatchlist's empty bucket). */}
      <div className="rounded-xl border border-slate-200 bg-white">
        <div className="px-4 py-3 border-b border-slate-100">
          <div className="text-[10px] uppercase tracking-wider font-bold text-slate-500">
            Positional trade ideas
          </div>
          <div className="text-[12px] text-slate-700">
            5–30 day setups from the positional engine, scored against today&apos;s macro regime.
          </div>
        </div>
        <div className="p-4 space-y-3">
          <WeekendWatchlist />
          <PositionalPicks hideWhenWatchlistMode />
        </div>
      </div>
    </div>
  );
}
