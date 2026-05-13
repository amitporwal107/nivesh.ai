import React from "react";
import FreshnessChip from "../shared/FreshnessChip";
import AgentRibbon from "../shared/AgentRibbon";

const overlapColor = (pct) => {
  if (pct == null) return "text-slate-400";
  if (pct > 50) return "text-rose-600 dark:text-rose-400";
  if (pct > 25) return "text-amber-600 dark:text-amber-400";
  return "text-emerald-600 dark:text-emerald-400";
};

const OverlapRevealWidget = ({ envelope, onAction, testId }) => {
  if (!envelope) return null;
  const { title, freshness, agent, data = {}, primary_cta, suggestions = [] } = envelope;
  const funds = data.funds || [];
  const matrix = data.overlap_matrix;
  const stocks = data.top_common_stocks || [];

  return (
    <div
      data-testid={testId || "widget-overlap-reveal"}
      className="rounded-[var(--cp-radius-lg)] border border-[color:var(--cp-border-subtle)] bg-[color:var(--cp-surface-base)] dark:bg-slate-800/60 overflow-hidden"
    >
      <header className="px-4 pt-3 pb-2 flex items-start justify-between gap-3 border-b border-[color:var(--cp-border-subtle)]">
        <div className="min-w-0">
          <div className="text-sm font-semibold text-[color:var(--cp-text-primary)] truncate">{title}</div>
          {data.overlap_pct != null && (
            <div className={`text-[11px] mt-0.5 font-semibold cp-num ${overlapColor(data.overlap_pct)}`}>
              {data.overlap_pct.toFixed(1)}% stock overlap
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

        {/* Pairwise overlap bar (2 funds) */}
        {data.overlap_pct != null && (
          <div>
            <div className="h-2 rounded-full bg-slate-100 dark:bg-slate-700 overflow-hidden">
              <div
                className={`h-full rounded-full transition-all ${
                  data.overlap_pct > 50 ? "bg-rose-400" : data.overlap_pct > 25 ? "bg-amber-400" : "bg-emerald-400"
                }`}
                style={{ width: `${Math.min(100, data.overlap_pct)}%` }}
              />
            </div>
            <div className="flex justify-between text-[10px] text-slate-400 mt-1">
              <span>0% overlap</span>
              <span>100%</span>
            </div>
          </div>
        )}

        {/* Matrix (3–4 funds) */}
        {matrix && funds.length > 2 && (
          <div className="overflow-x-auto">
            <table className="text-[11px] border-collapse w-full">
              <thead>
                <tr>
                  <th className="text-left pb-1 pr-2 text-slate-400 font-normal">Fund</th>
                  {funds.map((f, i) => (
                    <th key={i} className="pb-1 px-1 text-slate-400 font-normal text-center max-w-[80px] truncate" title={f}>
                      {f.split(" ")[0]}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {matrix.map((row, ri) => (
                  <tr key={ri}>
                    <td className="pr-2 py-1 text-[color:var(--cp-text-primary)] truncate max-w-[100px]" title={funds[ri]}>
                      {funds[ri]?.split(" ")[0]}
                    </td>
                    {row.map((val, ci) => (
                      <td
                        key={ci}
                        className={`text-center px-1 py-1 cp-num rounded ${
                          ri === ci
                            ? "text-slate-300 dark:text-slate-600"
                            : overlapColor(val)
                        } font-medium`}
                      >
                        {ri === ci ? "—" : `${val.toFixed(0)}%`}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {/* Verdict */}
        {data.verdict && (
          <div className="text-xs text-slate-600 dark:text-slate-300 bg-[color:var(--cp-surface-1)] rounded-lg p-2.5">
            {data.verdict}
          </div>
        )}

        {/* Common stocks */}
        {stocks.length > 0 && (
          <div>
            <div className="text-[10px] uppercase tracking-wide text-slate-400 mb-1.5">
              Top common stocks ({stocks.length})
            </div>
            <div className="flex flex-wrap gap-1.5">
              {stocks.map((s, i) => (
                <span
                  key={i}
                  title={`Held by: ${s.funds?.join(", ")}`}
                  className="px-2 py-0.5 text-[11px] rounded-full bg-[color:var(--cp-surface-1)] border border-[color:var(--cp-border-subtle)] text-[color:var(--cp-text-secondary)]"
                >
                  {s.stock_name}
                </span>
              ))}
            </div>
          </div>
        )}

        {funds.length === 0 && (
          <p className="text-xs text-slate-500 py-2">No fund data found. Add holdings or specify scheme codes.</p>
        )}
      </div>

      <footer className="px-4 py-3 border-t border-[color:var(--cp-border-subtle)] flex flex-wrap items-center gap-2">
        {primary_cta && (
          <button
            type="button"
            data-testid={`${testId || "widget-overlap-reveal"}-cta`}
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

export default OverlapRevealWidget;
