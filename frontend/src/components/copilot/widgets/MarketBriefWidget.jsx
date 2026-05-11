import React from "react";
import FreshnessChip from "../shared/FreshnessChip";
import AgentRibbon from "../shared/AgentRibbon";
import LiveValue from "../shared/LiveValue";

const sectorTone = (tone) => ({
  HOT:  "bg-emerald-500/20 text-emerald-700 dark:text-emerald-300",
  WARM: "bg-amber-400/20 text-amber-700 dark:text-amber-300",
  COOL: "bg-sky-400/20 text-sky-700 dark:text-sky-300",
  COLD: "bg-rose-500/20 text-rose-700 dark:text-rose-300",
})[(tone || "").toUpperCase()] || "bg-slate-200/40 text-slate-600 dark:text-slate-300";

/**
 * MarketBriefWidget — Doc 04 §4.2.
 * Reads the NIDP market snapshot envelope. Phase B renders the
 * indices + bullets + breadth + FII/DII; portfolio impact lands in
 * Phase C once the user-portfolio bridge is wired.
 */
const MarketBriefWidget = ({ envelope, onAction, testId }) => {
  if (!envelope) return null;
  const { title, freshness, agent, data = {}, primary_cta, suggestions = [] } = envelope;
  const { indices = [], sector_heatmap = [], breadth, fii_dii, summary_bullets = [] } = data;

  return (
    <div
      data-testid={testId || "widget-market-brief"}
      className="rounded-[var(--cp-radius-lg)] border border-[color:var(--cp-border-subtle)] bg-[color:var(--cp-surface-base)] dark:bg-slate-800/60 overflow-hidden"
    >
      <header className="px-4 pt-3 pb-2 flex items-start justify-between gap-3 border-b border-[color:var(--cp-border-subtle)]">
        <div>
          <div className="text-sm font-semibold">{title}</div>
          <div className="text-[11px] text-[color:var(--cp-text-secondary)] mt-0.5">
            <AgentRibbon agent={agent} compact />
          </div>
        </div>
        <FreshnessChip
          state={freshness?.state || "cached"}
          lastUpdated={freshness?.last_updated}
          source={freshness?.source || []}
        />
      </header>

      {indices.length > 0 && (
        <div className="px-4 py-3 flex flex-wrap gap-3 border-b border-[color:var(--cp-border-subtle)]">
          {indices.map((idx) => (
            <div key={idx.name} className="flex flex-col" data-testid={`market-index-${idx.name.replace(/\s+/g,'-')}`}>
              <span className="text-[10px] uppercase text-slate-500">{idx.name}</span>
              <LiveValue
                value={idx.value}
                format={(v) => v.toLocaleString("en-IN", { maximumFractionDigits: 2 })}
                delta={idx.change_pct}
                className="text-sm font-semibold"
              />
            </div>
          ))}
        </div>
      )}

      {sector_heatmap.length > 0 && (
        <div className="px-4 py-3 border-b border-[color:var(--cp-border-subtle)]">
          <div className="text-[10px] uppercase tracking-wide text-slate-500 mb-1.5">Sectors</div>
          <div className="flex flex-wrap gap-1.5">
            {sector_heatmap.slice(0, 12).map((s) => (
              <span
                key={s.name}
                className={`px-2 py-0.5 rounded-full text-[10px] font-medium ${sectorTone(s.tone)}`}
              >
                {s.name} {typeof s.change_pct === "number" ? `${s.change_pct > 0 ? "+" : ""}${s.change_pct.toFixed(1)}%` : ""}
              </span>
            ))}
          </div>
        </div>
      )}

      {(breadth || fii_dii) && (
        <div className="px-4 py-3 grid grid-cols-2 gap-4 border-b border-[color:var(--cp-border-subtle)] text-xs">
          {breadth && (
            <div>
              <div className="text-[10px] uppercase text-slate-500">Breadth</div>
              <div className="cp-num text-slate-700 dark:text-slate-200">
                A {breadth.advancing ?? "—"} · D {breadth.declining ?? "—"} · U {breadth.unchanged ?? "—"}
              </div>
            </div>
          )}
          {fii_dii && (
            <div>
              <div className="text-[10px] uppercase text-slate-500">FII / DII (₹ Cr)</div>
              <div className="cp-num text-slate-700 dark:text-slate-200">
                FII {fii_dii.fii_cr >= 0 ? "+" : ""}{Math.round(fii_dii.fii_cr).toLocaleString("en-IN")} · DII {fii_dii.dii_cr >= 0 ? "+" : ""}{Math.round(fii_dii.dii_cr).toLocaleString("en-IN")}
              </div>
            </div>
          )}
        </div>
      )}

      {summary_bullets.length > 0 && (
        <div className="px-4 py-3 border-b border-[color:var(--cp-border-subtle)]">
          <div className="text-[10px] uppercase tracking-wide text-slate-500 mb-1">AI Summary</div>
          <ul className="text-xs text-slate-700 dark:text-slate-200 list-disc pl-4 space-y-0.5">
            {summary_bullets.map((b, i) => <li key={i}>{b}</li>)}
          </ul>
        </div>
      )}

      <footer className="px-4 py-3 flex flex-wrap items-center gap-2">
        {primary_cta && (
          <button
            type="button"
            data-testid={`${testId || "widget-market-brief"}-cta`}
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

export default MarketBriefWidget;
