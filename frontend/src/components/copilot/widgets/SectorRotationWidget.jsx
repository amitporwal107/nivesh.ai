import React, { useState } from "react";
import FreshnessChip from "../shared/FreshnessChip";
import AgentRibbon from "../shared/AgentRibbon";

const QUADRANT_META = {
  Leading:   { bg: "bg-emerald-50 dark:bg-emerald-900/20",  border: "border-emerald-200 dark:border-emerald-800",  dot: "bg-emerald-500",  label: "Leading" },
  Improving: { bg: "bg-sky-50 dark:bg-sky-900/20",          border: "border-sky-200 dark:border-sky-800",          dot: "bg-sky-500",      label: "Improving" },
  Weakening: { bg: "bg-amber-50 dark:bg-amber-900/20",      border: "border-amber-200 dark:border-amber-800",      dot: "bg-amber-500",    label: "Weakening" },
  Lagging:   { bg: "bg-rose-50 dark:bg-rose-900/20",        border: "border-rose-200 dark:border-rose-800",        dot: "bg-rose-500",     label: "Lagging" },
};

const QUADRANT_ORDER = ["Leading", "Improving", "Weakening", "Lagging"];

const SectorRotationWidget = ({ envelope, onAction, testId }) => {
  const [active, setActive] = useState(null);
  if (!envelope) return null;
  const { title, freshness, agent, data = {}, primary_cta, suggestions = [] } = envelope;
  const sectors = data.sectors || [];

  const grouped = QUADRANT_ORDER.reduce((acc, q) => {
    acc[q] = sectors.filter((s) => s.quadrant === q);
    return acc;
  }, {});

  const activeSector = active ? sectors.find((s) => s.name === active) : null;

  return (
    <div
      data-testid={testId || "widget-sector-rotation"}
      className="rounded-[var(--cp-radius-lg)] border border-[color:var(--cp-border-subtle)] bg-[color:var(--cp-surface-base)] dark:bg-slate-800/60 overflow-hidden"
    >
      <header className="px-4 pt-3 pb-2 flex items-start justify-between gap-3 border-b border-[color:var(--cp-border-subtle)]">
        <div className="min-w-0">
          <div className="text-sm font-semibold text-[color:var(--cp-text-primary)] truncate">{title}</div>
          <div className="text-[11px] text-[color:var(--cp-text-secondary)] mt-0.5">
            Horizon: {data.horizon || "1M"} · tap a sector for detail
          </div>
        </div>
        <FreshnessChip
          state={freshness?.state || "cached"}
          lastUpdated={freshness?.last_updated}
          source={freshness?.source || []}
        />
      </header>

      <div className="px-4 py-3 space-y-3">
        <AgentRibbon agent={agent} compact />

        {/* RS Quadrant grid */}
        <div className="grid grid-cols-2 gap-2 text-xs">
          {QUADRANT_ORDER.map((q) => {
            const meta = QUADRANT_META[q];
            const items = grouped[q] || [];
            return (
              <div
                key={q}
                className={`rounded-lg border p-2.5 ${meta.bg} ${meta.border}`}
              >
                <div className="flex items-center gap-1.5 mb-1.5">
                  <span className={`w-2 h-2 rounded-full flex-shrink-0 ${meta.dot}`} />
                  <span className="text-[10px] font-semibold uppercase tracking-wide text-slate-600 dark:text-slate-300">
                    {meta.label}
                  </span>
                </div>
                {items.length === 0 ? (
                  <span className="text-slate-400 text-[10px]">—</span>
                ) : (
                  <div className="flex flex-wrap gap-1">
                    {items.map((s) => (
                      <button
                        key={s.name}
                        type="button"
                        onClick={() => setActive((v) => (v === s.name ? null : s.name))}
                        className={`px-1.5 py-0.5 rounded text-[11px] font-medium border transition-all ${
                          active === s.name
                            ? "bg-white dark:bg-slate-700 shadow-sm border-slate-300 dark:border-slate-500"
                            : "bg-transparent border-transparent hover:bg-white/70 dark:hover:bg-slate-700/50"
                        } text-slate-700 dark:text-slate-200`}
                      >
                        {s.name}
                      </button>
                    ))}
                  </div>
                )}
              </div>
            );
          })}
        </div>

        {/* Active sector detail */}
        {activeSector && (
          <div className="rounded-lg border border-[color:var(--cp-border-subtle)] bg-[color:var(--cp-surface-1)] p-3 text-xs space-y-1">
            <div className="font-semibold text-[color:var(--cp-text-primary)]">{activeSector.name}</div>
            <div className="grid grid-cols-3 gap-2 text-slate-500 cp-num">
              <div>
                <div className="text-[10px] uppercase">RS score</div>
                <div className="font-medium text-[color:var(--cp-text-primary)]">
                  {activeSector.rs_score != null ? activeSector.rs_score.toFixed(0) : "—"}
                </div>
              </div>
              <div>
                <div className="text-[10px] uppercase">1W</div>
                <div className={`font-medium ${(activeSector.week_change_pct ?? 0) >= 0 ? "text-emerald-600 dark:text-emerald-400" : "text-rose-600 dark:text-rose-400"}`}>
                  {activeSector.week_change_pct != null ? `${activeSector.week_change_pct > 0 ? "+" : ""}${activeSector.week_change_pct.toFixed(1)}%` : "—"}
                </div>
              </div>
              <div>
                <div className="text-[10px] uppercase">1M</div>
                <div className={`font-medium ${(activeSector.month_change_pct ?? 0) >= 0 ? "text-emerald-600 dark:text-emerald-400" : "text-rose-600 dark:text-rose-400"}`}>
                  {activeSector.month_change_pct != null ? `${activeSector.month_change_pct > 0 ? "+" : ""}${activeSector.month_change_pct.toFixed(1)}%` : "—"}
                </div>
              </div>
            </div>
            <button
              type="button"
              onClick={() => onAction && onAction("suggestion", { suggestion: `Which of my funds are heavy on ${activeSector.name}?`, envelope })}
              className="text-[11px] text-[color:var(--cp-accent-brand)] hover:underline mt-1 block"
            >
              Which of my funds are heavy on {activeSector.name}? →
            </button>
          </div>
        )}
      </div>

      <footer className="px-4 py-3 border-t border-[color:var(--cp-border-subtle)] flex flex-wrap items-center gap-2">
        {primary_cta && (
          <button
            type="button"
            data-testid={`${testId || "widget-sector-rotation"}-cta`}
            onClick={() => onAction && onAction(primary_cta.action, envelope)}
            className="px-3 py-1.5 text-xs font-medium rounded-full text-white shadow-sm"
            style={{ background: "var(--cp-accent-brand)" }}
          >
            {primary_cta.label}
          </button>
        )}
        {suggestions.map((s) => (
          <button
            key={s}
            type="button"
            onClick={() => onAction && onAction("suggestion", { suggestion: s, envelope })}
            className="px-2.5 py-1 text-[11px] rounded-full border border-[color:var(--cp-border-subtle)] text-slate-600 dark:text-slate-300 hover:border-[color:var(--cp-accent-brand)] hover:text-[color:var(--cp-accent-brand)]"
          >
            {s}
          </button>
        ))}
      </footer>
    </div>
  );
};

export default SectorRotationWidget;
