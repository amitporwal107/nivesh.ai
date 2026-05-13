import React, { useState } from "react";
import FreshnessChip from "../shared/FreshnessChip";
import AgentRibbon from "../shared/AgentRibbon";

const ACTION_STYLES = {
  BUY:    "bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-300",
  SELL:   "bg-rose-100 text-rose-700 dark:bg-rose-900/40 dark:text-rose-300",
  SWITCH: "bg-sky-100 text-sky-700 dark:bg-sky-900/40 dark:text-sky-300",
  HOLD:   "bg-slate-100 text-slate-600 dark:bg-slate-700 dark:text-slate-300",
};

const RebalancePlanWidget = ({ envelope, onAction, testId }) => {
  const [showAll, setShowAll] = useState(false);
  if (!envelope) return null;
  const { title, freshness, agent, data = {}, primary_cta, suggestions = [] } = envelope;
  const actions = data.actions || [];
  const visible = showAll ? actions : actions.slice(0, 4);

  return (
    <div
      data-testid={testId || "widget-rebalance-plan"}
      className="rounded-[var(--cp-radius-lg)] border border-[color:var(--cp-border-subtle)] bg-[color:var(--cp-surface-base)] dark:bg-slate-800/60 overflow-hidden"
    >
      <header className="px-4 pt-3 pb-2 flex items-start justify-between gap-3 border-b border-[color:var(--cp-border-subtle)]">
        <div className="min-w-0">
          <div className="text-sm font-semibold text-[color:var(--cp-text-primary)] truncate">{title}</div>
          {data.current_value_rs != null && (
            <div className="text-[11px] text-[color:var(--cp-text-secondary)] mt-0.5 cp-num">
              Portfolio value ₹{Math.round(data.current_value_rs).toLocaleString("en-IN")}
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
        <div className="flex items-center justify-between gap-2">
          <AgentRibbon agent={agent} compact />
          {data.summary && (
            <span className="text-[11px] text-slate-500 dark:text-slate-400 truncate max-w-[60%]">
              {data.summary}
            </span>
          )}
        </div>

        {actions.length === 0 ? (
          <p className="text-xs text-slate-500 py-2">No rebalance actions needed right now.</p>
        ) : (
          <div className="space-y-2">
            {visible.map((a, i) => (
              <div
                key={i}
                className="flex items-start gap-3 p-2.5 rounded-lg bg-[color:var(--cp-surface-1)] dark:bg-slate-700/40"
              >
                <span className={`text-[10px] font-bold px-2 py-0.5 rounded-full flex-shrink-0 mt-0.5 ${ACTION_STYLES[a.action] || ACTION_STYLES.HOLD}`}>
                  {a.action}
                </span>
                <div className="flex-1 min-w-0">
                  <div className="text-xs font-medium text-[color:var(--cp-text-primary)] truncate">{a.fund_name}</div>
                  {a.reason && <div className="text-[11px] text-slate-500 mt-0.5">{a.reason}</div>}
                </div>
                {a.amount_rs != null && (
                  <div className="text-xs font-semibold cp-num text-[color:var(--cp-text-primary)] flex-shrink-0">
                    ₹{Math.round(a.amount_rs).toLocaleString("en-IN")}
                  </div>
                )}
              </div>
            ))}
            {actions.length > 4 && (
              <button
                type="button"
                onClick={() => setShowAll((v) => !v)}
                className="text-[11px] text-[color:var(--cp-accent-brand)] hover:underline"
              >
                {showAll ? "▲ Show less" : `▸ Show ${actions.length - 4} more actions`}
              </button>
            )}
          </div>
        )}
      </div>

      <footer className="px-4 py-3 border-t border-[color:var(--cp-border-subtle)] flex flex-wrap items-center gap-2">
        {primary_cta && (
          <button
            type="button"
            data-testid={`${testId || "widget-rebalance-plan"}-cta`}
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

export default RebalancePlanWidget;
