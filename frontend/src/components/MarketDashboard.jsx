import React from "react";
import { Globe2, Sparkles } from "lucide-react";
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

/**
 * MarketDashboard — global, market-wide signals + actionable trade ideas.
 *
 * Reorganised May 2026 for readability. Three layers, top to bottom:
 *
 *   ┌──────────────────────────────────────────────────────────────┐
 *   │ 🎯 Today's Take (sticky)                                      │
 *   │   Bias · Top trade · Avoid                                    │
 *   ├──────────────────────────────────────────────────────────────┤
 *   │ Section nav (sticky below Take)                               │
 *   │   Macro · Strategy · Sectors · Trades                         │
 *   ├──────────────────────────────────────────────────────────────┤
 *   │ §1  THE MARKET   — Macro regime + values                      │
 *   │ §2  THE STRATEGY — bias + sizing + focus + avoid              │
 *   │ §3  THE SECTORS  — heatmap + aligned picks + what changed     │
 *   │ §4  THE TRADES   — top conviction + rails (Early/Active/...)  │
 *   └──────────────────────────────────────────────────────────────┘
 *
 * Container is max-w-5xl (was max-w-6xl) for shorter line lengths and
 * better scannability on desktop. Each section now has a numbered
 * header anchor so the nav can scroll to it.
 */

// Numbered section header — consistent visual rhythm across the page.
// Anchor id matches the nav link target so smooth-scroll works.
const Section = ({ n, id, title, subtitle, children }) => (
  <section id={id} className="scroll-mt-32">
    <div className="flex items-baseline gap-3 mb-3">
      <span className="text-[10px] font-mono font-bold uppercase tracking-wider text-slate-400 dark:text-slate-500">
        §{n}
      </span>
      <div className="flex-1">
        <h2 className="text-base font-semibold text-slate-900 dark:text-white tracking-tight">
          {title}
        </h2>
        {subtitle && (
          <p className="text-[11px] text-slate-500 dark:text-slate-400 mt-0.5">
            {subtitle}
          </p>
        )}
      </div>
    </div>
    <div className="space-y-3">
      {children}
    </div>
  </section>
);


const SectionNav = () => (
  <nav className="flex flex-wrap items-center gap-1 text-[11px] py-1" aria-label="Market sections">
    {[
      ["The Market",   "#section-market"],
      ["The Strategy", "#section-strategy"],
      ["The Sectors",  "#section-sectors"],
      ["The Trades",   "#section-trades"],
      ["Journal",      "#section-journal"],
    ].map(([label, href]) => (
      <a
        key={href}
        href={href}
        className="px-2 py-1 rounded-md text-slate-600 dark:text-slate-400 hover:text-emerald-700 dark:hover:text-emerald-400 hover:bg-emerald-50 dark:hover:bg-emerald-900/20 transition-colors"
      >
        {label}
      </a>
    ))}
  </nav>
);


export default function MarketDashboard() {
  return (
    <div className="p-4 sm:p-6 max-w-5xl mx-auto" data-testid="market-dashboard">
      {/* Sticky Today's Take strip — extends to page edges */}
      <MarketTodaysTake />

      {/* Section nav — sticks just below the Take strip */}
      <div className="sticky top-[72px] z-20 -mx-4 sm:-mx-6 px-4 sm:px-6 py-1 bg-white/85 dark:bg-slate-950/85 backdrop-blur-md border-b border-slate-100 dark:border-slate-800/50">
        <div className="max-w-5xl mx-auto">
          <SectionNav />
        </div>
      </div>

      {/* Page header */}
      <div className="flex items-start gap-3 pt-4 pb-6">
        <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-indigo-500 to-emerald-500 flex items-center justify-center text-white flex-shrink-0">
          <Globe2 className="w-5 h-5" strokeWidth={2} />
        </div>
        <div className="flex-1">
          <h1 className="text-2xl font-bold text-slate-900 dark:text-white tracking-tight">
            Market Dashboard
          </h1>
          <p className="text-[12px] text-slate-500 dark:text-slate-400 mt-0.5">
            Macro regime, sector tilt, and positional trade ideas — refreshed daily after the 18:35 IST cron.
          </p>
        </div>
        <span className="hidden sm:inline-flex items-center gap-1 text-[10px] uppercase tracking-wider font-bold px-2 py-1 rounded bg-emerald-100 text-emerald-700 border border-emerald-200 self-start">
          <Sparkles className="w-3 h-3" /> Macro v1
        </span>
      </div>

      {/* Sectioned content with consistent rhythm */}
      <div className="space-y-8">
        <Section
          n="1"
          id="section-market"
          title="The Market"
          subtitle="Today's regime — what the macro is doing"
        >
          <DeployVerdictStrip />
          <MacroBar />
        </Section>

        <Section
          n="2"
          id="section-strategy"
          title="The Strategy"
          subtitle="Translated into bias, sizing, and the sectors to favour or avoid"
        >
          <TodayStrategyCard />
        </Section>

        <Section
          n="3"
          id="section-sectors"
          title="The Sectors"
          subtitle="Macro tailwinds and headwinds with stock-level setups"
        >
          <SectorHeatmap />
          <AlignedPicks />
          <WhatChanged />
          <MondayGamePlan />
        </Section>

        <Section
          n="4"
          id="section-trades"
          title="The Trades"
          subtitle="Today's positional picks ranked by conviction · 5–30 day timeframe"
        >
          <PositionalTopPicks />
          <WeekendWatchlist />
          <PositionalPicks hideWhenWatchlistMode />
        </Section>

        <Section
          n="5"
          id="section-journal"
          title="Trade Journal"
          subtitle="Staged entries · exit ladder · live P&L · hedge guidance"
        >
          <TradeJournal />
        </Section>
      </div>
    </div>
  );
}
