import React, { useState } from "react";
import FreshnessChip from "../shared/FreshnessChip";
import AgentRibbon from "../shared/AgentRibbon";

/** Returns block — small 5-col line of return labels/values. */
const ReturnsRow = ({ returns }) => {
  const labels = ["1Y", "3Y", "5Y", "7Y", "Since incep."];
  const keys = ["1Y", "3Y", "5Y", "7Y", "since_inception"];
  return (
    <div className="grid grid-cols-5 gap-2 cp-num text-xs">
      {keys.map((k, i) => {
        const v = (returns || {})[k];
        return (
          <div key={k} className="text-center">
            <div className="text-[10px] uppercase tracking-wide text-slate-500">{labels[i]}</div>
            <div className="font-semibold">{typeof v === "number" ? `${v.toFixed(1)}%` : "—"}</div>
          </div>
        );
      })}
    </div>
  );
};

const verdictTone = (v) => ({
  "Strong Buy": "bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-300",
  "Buy":        "bg-sky-100 text-sky-700 dark:bg-sky-900/40 dark:text-sky-300",
  "Hold":       "bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-300",
  "Sell":       "bg-rose-100 text-rose-700 dark:bg-rose-900/40 dark:text-rose-300",
})[v] || "bg-slate-100 text-slate-700";

/**
 * FundCardWidget — Doc 03 §3.2.
 * Renders identically inside Chat / Insights / Holding drawer.
 */
const FundCardWidget = ({ envelope, onAction, embedded = "chat", testId }) => {
  const [expanded, setExpanded] = useState(false);
  if (!envelope) return null;
  const { title, freshness, agent, data = {}, primary_cta, suggestions = [] } = envelope;

  return (
    <div
      data-testid={testId || "widget-fund-card"}
      className="rounded-[var(--cp-radius-lg)] border border-[color:var(--cp-border-subtle)] bg-[color:var(--cp-surface-base)] dark:bg-slate-800/60 overflow-hidden"
    >
      <header className="px-4 pt-3 pb-2 flex items-start justify-between gap-3 border-b border-[color:var(--cp-border-subtle)]">
        <div className="min-w-0">
          <div className="text-sm font-semibold text-[color:var(--cp-text-primary)] truncate">{title}</div>
          <div className="text-[11px] text-[color:var(--cp-text-secondary)] mt-0.5">
            {[data.category, data.plan_type, data.risk_label].filter(Boolean).join(" · ")}
            {data.aum_cr ? ` · AUM ₹${Math.round(data.aum_cr).toLocaleString("en-IN")} Cr` : ""}
            {data.nav ? ` · NAV ₹${Number(data.nav).toFixed(2)}` : ""}
          </div>
        </div>
        <FreshnessChip
          state={freshness?.state || "cached"}
          lastUpdated={freshness?.last_updated}
          source={freshness?.source || []}
          confidence={freshness?.confidence}
        />
      </header>

      <div className="px-4 py-3 space-y-3">
        <div className="flex items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            <span className={`px-2 py-0.5 text-[11px] font-semibold rounded-full ${verdictTone(data.verdict)}`}>
              {data.verdict || "—"}
            </span>
            {data.verdict_score != null && (
              <span className="text-[11px] text-slate-500 cp-num">· {data.verdict_score}/100</span>
            )}
          </div>
          <AgentRibbon agent={agent} compact />
        </div>

        {(data.why?.length || data.watch_outs?.length) && (
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 text-xs">
            {data.why?.length > 0 && (
              <div>
                <div className="text-[10px] uppercase tracking-wide text-slate-500 mb-1">Why</div>
                <ul className="list-disc pl-4 space-y-0.5 text-slate-700 dark:text-slate-200">
                  {data.why.map((w, i) => <li key={i}>{w}</li>)}
                </ul>
              </div>
            )}
            {data.watch_outs?.length > 0 && (
              <div>
                <div className="text-[10px] uppercase tracking-wide text-slate-500 mb-1">Watch-outs</div>
                <ul className="list-disc pl-4 space-y-0.5 text-slate-700 dark:text-slate-200">
                  {data.watch_outs.map((w, i) => <li key={i}>{w}</li>)}
                </ul>
              </div>
            )}
          </div>
        )}

        <div>
          <div className="text-[10px] uppercase tracking-wide text-slate-500 mb-1">Performance</div>
          <ReturnsRow returns={data.returns} />
          {data.benchmark && data.alpha != null && (
            <div className="text-[11px] text-slate-500 cp-num mt-1">
              vs {data.benchmark}: {data.alpha > 0 ? "+" : ""}{data.alpha.toFixed(1)}% alpha
            </div>
          )}
        </div>

        <button
          type="button"
          data-testid={`${testId || "widget-fund-card"}-expand`}
          onClick={() => setExpanded((v) => !v)}
          className="text-[11px] text-[color:var(--cp-accent-brand)] hover:underline"
        >
          ▸ {expanded ? "Hide" : "Show"} rolling returns · risk · top holdings · manager
        </button>
        {expanded && (
          <div className="text-xs text-slate-600 dark:text-slate-300 grid grid-cols-2 sm:grid-cols-3 gap-3 pt-2 border-t border-[color:var(--cp-border-subtle)]">
            <div>
              <div className="text-[10px] uppercase text-slate-500">Expense</div>
              <div className="cp-num">{data.expense_ratio != null ? `${data.expense_ratio.toFixed(2)}%` : "—"}</div>
            </div>
            <div>
              <div className="text-[10px] uppercase text-slate-500">Manager tenure</div>
              <div className="cp-num">{data.manager_tenure_years != null ? `${data.manager_tenure_years} yr` : "—"}</div>
            </div>
            <div>
              <div className="text-[10px] uppercase text-slate-500">Scheme code</div>
              <div className="cp-num">{data.scheme_code || "—"}</div>
            </div>
          </div>
        )}
      </div>

      <footer className="px-4 py-3 border-t border-[color:var(--cp-border-subtle)] flex flex-wrap items-center gap-2">
        {primary_cta && (
          <button
            type="button"
            data-testid={`${testId || "widget-fund-card"}-cta`}
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

export default FundCardWidget;
