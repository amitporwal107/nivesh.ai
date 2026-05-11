import React from "react";
import FreshnessChip from "../shared/FreshnessChip";
import AgentRibbon from "../shared/AgentRibbon";

const SipPlanWidget = ({ envelope, onAction, testId }) => {
  if (!envelope) return null;
  const { title, freshness, agent, data = {}, primary_cta, suggestions = [] } = envelope;
  const { monthly_budget, allocations = [], why_these = [], counter_points = [] } = data;
  const total = allocations.reduce((acc, a) => acc + (Number(a.monthly_amount) || 0), 0);

  return (
    <div
      data-testid={testId || "widget-sip-plan"}
      className="rounded-[var(--cp-radius-lg)] border border-[color:var(--cp-border-subtle)] bg-[color:var(--cp-surface-base)] dark:bg-slate-800/60 overflow-hidden"
    >
      <header className="px-4 pt-3 pb-2 flex items-start justify-between gap-3 border-b border-[color:var(--cp-border-subtle)]">
        <div>
          <div className="text-sm font-semibold">{title}</div>
          <AgentRibbon agent={agent} compact />
        </div>
        <FreshnessChip state={freshness?.state || "cached"} source={freshness?.source || []} lastUpdated={freshness?.last_updated} />
      </header>
      <div className="px-4 py-3 space-y-2">
        {allocations.map((a, i) => {
          const pct = monthly_budget ? (a.monthly_amount / monthly_budget) * 100 : 0;
          return (
            <div key={i} data-testid={`sip-alloc-${i}`} className="flex items-center justify-between gap-3 text-xs">
              <div className="flex-1 min-w-0">
                <div className="font-medium truncate">{a.scheme_name}</div>
                <div className="text-[11px] text-slate-500">{a.rationale}</div>
              </div>
              <div className="text-right cp-num">
                <div className="font-semibold">₹{Math.round(a.monthly_amount).toLocaleString("en-IN")}</div>
                <div className="text-[10px] text-slate-500">{pct.toFixed(0)}%</div>
              </div>
            </div>
          );
        })}
        <div className="border-t border-[color:var(--cp-border-subtle)] pt-2 mt-2 flex justify-between text-xs">
          <span className="text-slate-500">Total</span>
          <span className="cp-num font-semibold">₹{Math.round(total).toLocaleString("en-IN")}/mo</span>
        </div>
      </div>
      {(why_these.length > 0 || counter_points.length > 0) && (
        <div className="px-4 py-3 border-t border-[color:var(--cp-border-subtle)] grid grid-cols-1 sm:grid-cols-2 gap-3 text-xs">
          {why_these.length > 0 && (
            <div>
              <div className="text-[10px] uppercase text-slate-500 mb-1">Why these</div>
              <ul className="list-disc pl-4 text-slate-700 dark:text-slate-200 space-y-0.5">{why_these.map((w, i) => <li key={i}>{w}</li>)}</ul>
            </div>
          )}
          {counter_points.length > 0 && (
            <div>
              <div className="text-[10px] uppercase text-slate-500 mb-1">Counter-points</div>
              <ul className="list-disc pl-4 italic text-slate-500 space-y-0.5">{counter_points.map((c, i) => <li key={i}>{c}</li>)}</ul>
            </div>
          )}
        </div>
      )}
      <footer className="px-4 py-3 border-t border-[color:var(--cp-border-subtle)] flex flex-wrap items-center gap-2">
        {primary_cta && (
          <button
            type="button"
            data-testid={`${testId || "widget-sip-plan"}-cta`}
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

export default SipPlanWidget;
