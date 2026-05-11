import React from "react";
import FreshnessChip from "../shared/FreshnessChip";
import AgentRibbon from "../shared/AgentRibbon";
import DiffTable from "../shared/DiffTable";

const mapRows = (rows = []) => rows.map((r) => ({
  metric: r.metric,
  values: r.values,
  bestIndex: r.best_index,
  worstIndex: r.worst_index,
  higherIsBetter: r.higher_is_better,
}));

const CompareTableWidget = ({ envelope, onAction, testId }) => {
  if (!envelope) return null;
  const { title, freshness, agent, data = {}, primary_cta, suggestions = [] } = envelope;

  return (
    <div
      data-testid={testId || "widget-compare-table"}
      className="rounded-[var(--cp-radius-lg)] border border-[color:var(--cp-border-subtle)] bg-[color:var(--cp-surface-base)] dark:bg-slate-800/60 overflow-hidden"
    >
      <header className="px-4 pt-3 pb-2 flex items-start justify-between gap-3 border-b border-[color:var(--cp-border-subtle)]">
        <div>
          <div className="text-sm font-semibold">{title}</div>
          <AgentRibbon agent={agent} compact />
        </div>
        <FreshnessChip
          state={freshness?.state || "cached"}
          lastUpdated={freshness?.last_updated}
          source={freshness?.source || []}
        />
      </header>
      <div className="p-3">
        <DiffTable
          columns={data.funds || []}
          rows={mapRows(data.rows || [])}
          verdict={data.verdict}
          onlyDifferencesDefault={!!data.differences_only_default}
        />
      </div>
      <footer className="px-4 py-3 border-t border-[color:var(--cp-border-subtle)] flex flex-wrap items-center gap-2">
        {primary_cta && (
          <button
            type="button"
            data-testid={`${testId || "widget-compare-table"}-cta`}
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

export default CompareTableWidget;
