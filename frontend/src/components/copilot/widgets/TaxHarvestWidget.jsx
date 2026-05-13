import React, { useState } from "react";
import FreshnessChip from "../shared/FreshnessChip";
import AgentRibbon from "../shared/AgentRibbon";

const fmt = (n) => n != null ? `₹${Math.round(n).toLocaleString("en-IN")}` : "—";

const TaxHarvestWidget = ({ envelope, onAction, testId }) => {
  const [simulating, setSimulating] = useState(false);
  if (!envelope) return null;
  const { title, freshness, agent, data = {}, primary_cta, suggestions = [] } = envelope;
  const candidates = data.candidates || [];
  const remaining = data.ltcg_remaining_rs ?? data.ltcg_limit_rs ?? 100000;
  const used = data.ltcg_used_rs ?? 0;
  const limit = data.ltcg_limit_rs ?? 100000;
  const usedPct = Math.min(100, Math.round((used / limit) * 100));

  return (
    <div
      data-testid={testId || "widget-tax-harvest"}
      className="rounded-[var(--cp-radius-lg)] border border-[color:var(--cp-border-subtle)] bg-[color:var(--cp-surface-base)] dark:bg-slate-800/60 overflow-hidden"
    >
      <header className="px-4 pt-3 pb-2 flex items-start justify-between gap-3 border-b border-[color:var(--cp-border-subtle)]">
        <div className="min-w-0">
          <div className="text-sm font-semibold text-[color:var(--cp-text-primary)] truncate">{title}</div>
          <div className="text-[11px] text-[color:var(--cp-text-secondary)] mt-0.5">
            LTCG exemption: {fmt(remaining)} remaining of {fmt(limit)}
          </div>
        </div>
        <FreshnessChip
          state={freshness?.state || "cached"}
          lastUpdated={freshness?.last_updated}
          source={freshness?.source || []}
        />
      </header>

      <div className="px-4 py-3 space-y-3">
        {/* Exemption progress bar */}
        <div>
          <div className="flex justify-between text-[10px] text-slate-500 mb-1">
            <span>Used {fmt(used)}</span>
            <span>{usedPct}% of ₹1L limit</span>
          </div>
          <div className="h-1.5 rounded-full bg-slate-100 dark:bg-slate-700 overflow-hidden">
            <div
              className="h-full rounded-full bg-emerald-500 transition-all"
              style={{ width: `${usedPct}%` }}
            />
          </div>
        </div>

        <AgentRibbon agent={agent} compact />

        {candidates.length === 0 ? (
          <p className="text-xs text-slate-500 py-2">No LTCG harvest candidates found in your portfolio.</p>
        ) : (
          <div className="space-y-1.5">
            <div className="grid grid-cols-[1fr_auto_auto_auto] gap-2 text-[10px] uppercase tracking-wide text-slate-400 px-1">
              <span>Fund</span>
              <span className="text-right">Gain</span>
              <span className="text-right">Days</span>
              <span className="text-right">Status</span>
            </div>
            {candidates.map((c, i) => (
              <div
                key={i}
                className={`grid grid-cols-[1fr_auto_auto_auto] gap-2 items-center p-2 rounded-lg text-xs ${
                  c.eligible
                    ? "bg-emerald-50 dark:bg-emerald-900/20 border border-emerald-100 dark:border-emerald-900/40"
                    : "bg-slate-50 dark:bg-slate-700/30 opacity-60"
                }`}
              >
                <span className="truncate font-medium text-[color:var(--cp-text-primary)]">{c.fund_name}</span>
                <span className="cp-num text-right text-emerald-700 dark:text-emerald-400 font-semibold">{fmt(c.gain_rs)}</span>
                <span className="cp-num text-right text-slate-500">{c.days_held ?? "—"}d</span>
                <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded-full ${
                  c.eligible
                    ? "bg-emerald-100 text-emerald-700 dark:bg-emerald-800/60 dark:text-emerald-300"
                    : "bg-slate-200 text-slate-500 dark:bg-slate-600 dark:text-slate-400"
                }`}>
                  {c.eligible ? "Harvest" : "Skip"}
                </span>
              </div>
            ))}
          </div>
        )}

        {data.warning && (
          <div className="text-[11px] text-amber-700 dark:text-amber-400 bg-amber-50 dark:bg-amber-900/20 rounded-lg px-3 py-2 border border-amber-100 dark:border-amber-900/40">
            ⚠ {data.warning}
          </div>
        )}
      </div>

      <footer className="px-4 py-3 border-t border-[color:var(--cp-border-subtle)] flex flex-wrap items-center gap-2">
        {primary_cta && (
          <button
            type="button"
            data-testid={`${testId || "widget-tax-harvest"}-cta`}
            disabled={simulating}
            onClick={() => {
              setSimulating(true);
              onAction && onAction(primary_cta.action, envelope);
              setTimeout(() => setSimulating(false), 1500);
            }}
            className="px-3 py-1.5 text-xs font-medium rounded-full text-white shadow-sm disabled:opacity-60"
            style={{ background: "var(--cp-accent-brand)" }}
          >
            {simulating ? "Simulating…" : primary_cta.label}
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

export default TaxHarvestWidget;
