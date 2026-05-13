import React, { useState } from "react";
import FreshnessChip from "../shared/FreshnessChip";
import AgentRibbon from "../shared/AgentRibbon";

const fmt = (n) => n != null ? `₹${Math.round(n).toLocaleString("en-IN")}` : "—";

const StressTestWidget = ({ envelope, onAction, testId }) => {
  const [expanded, setExpanded] = useState(false);
  if (!envelope) return null;
  const { title, freshness, agent, data = {}, primary_cta, suggestions = [] } = envelope;
  const drop = data.drop_pct ?? 0;
  const isPositive = drop >= 0;
  const dropColor = isPositive ? "text-emerald-600 dark:text-emerald-400" : "text-rose-600 dark:text-rose-400";
  const barWidth = Math.min(100, Math.abs(drop));

  return (
    <div
      data-testid={testId || "widget-stress-test"}
      className="rounded-[var(--cp-radius-lg)] border border-[color:var(--cp-border-subtle)] bg-[color:var(--cp-surface-base)] dark:bg-slate-800/60 overflow-hidden"
    >
      <header className="px-4 pt-3 pb-2 flex items-start justify-between gap-3 border-b border-[color:var(--cp-border-subtle)]">
        <div className="min-w-0">
          <div className="text-sm font-semibold text-[color:var(--cp-text-primary)] truncate">{title}</div>
          {data.scenario_description && (
            <div className="text-[11px] text-[color:var(--cp-text-secondary)] mt-0.5 line-clamp-1">
              {data.scenario_description}
            </div>
          )}
        </div>
        <FreshnessChip
          state={freshness?.state || "cached"}
          lastUpdated={freshness?.last_updated}
          source={freshness?.source || []}
        />
      </header>

      <div className="px-4 py-3 space-y-3">
        <AgentRibbon agent={agent} compact />

        {/* Impact summary */}
        <div className="grid grid-cols-3 gap-3 text-center">
          <div>
            <div className="text-[10px] uppercase tracking-wide text-slate-400 mb-0.5">Current</div>
            <div className="text-sm font-semibold cp-num text-[color:var(--cp-text-primary)]">{fmt(data.current_value_rs)}</div>
          </div>
          <div>
            <div className="text-[10px] uppercase tracking-wide text-slate-400 mb-0.5">Stressed</div>
            <div className={`text-sm font-semibold cp-num ${dropColor}`}>{fmt(data.stressed_value_rs)}</div>
          </div>
          <div>
            <div className="text-[10px] uppercase tracking-wide text-slate-400 mb-0.5">Drop</div>
            <div className={`text-sm font-semibold cp-num ${dropColor}`}>
              {drop != null ? `${drop > 0 ? "+" : ""}${drop.toFixed(1)}%` : "—"}
            </div>
          </div>
        </div>

        {/* Visual drop bar */}
        {data.drop_pct != null && (
          <div>
            <div className="h-2 rounded-full bg-slate-100 dark:bg-slate-700 overflow-hidden">
              <div
                className="h-full rounded-full bg-rose-400 transition-all"
                style={{ width: `${barWidth}%` }}
              />
            </div>
            {data.recovery_years != null && (
              <div className="text-[11px] text-slate-500 mt-1">
                Historical recovery: ~{data.recovery_years} year{data.recovery_years !== 1 ? "s" : ""}
              </div>
            )}
          </div>
        )}

        {data.insight && (
          <div className="text-xs text-slate-600 dark:text-slate-300 bg-[color:var(--cp-surface-1)] rounded-lg p-2.5">
            {data.insight}
          </div>
        )}

        {/* Fund breakdown */}
        {data.breakdown?.length > 0 && (
          <>
            <button
              type="button"
              onClick={() => setExpanded((v) => !v)}
              className="text-[11px] text-[color:var(--cp-accent-brand)] hover:underline"
            >
              {expanded ? "▲ Hide fund breakdown" : `▸ Show fund breakdown (${data.breakdown.length})`}
            </button>
            {expanded && (
              <div className="space-y-1.5">
                {data.breakdown.map((b, i) => (
                  <div
                    key={i}
                    className="flex items-center gap-2 text-xs"
                  >
                    <span className="flex-1 truncate text-[color:var(--cp-text-primary)]">{b.fund_name}</span>
                    <span className="cp-num text-slate-500 flex-shrink-0">{fmt(b.current_value_rs)}</span>
                    <span className="cp-num text-rose-600 dark:text-rose-400 flex-shrink-0 w-14 text-right">
                      {b.drop_pct != null ? `${b.drop_pct.toFixed(1)}%` : "—"}
                    </span>
                  </div>
                ))}
              </div>
            )}
          </>
        )}
      </div>

      <footer className="px-4 py-3 border-t border-[color:var(--cp-border-subtle)] flex flex-wrap items-center gap-2">
        {primary_cta && (
          <button
            type="button"
            data-testid={`${testId || "widget-stress-test"}-cta`}
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

export default StressTestWidget;
