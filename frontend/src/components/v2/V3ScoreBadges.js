import React from 'react';

/**
 * V3 Engine score badge cluster — surfaces Quality / Health / Exit / Add
 * composite scores from `action.v3_scores`. Keeps visual weight low so it
 * doesn't crowd the PlanCard, but calls out low-confidence scores via the
 * missing_primitives count.
 */

const SCORE_COLOR = (v) => {
  if (v == null) return 'bg-slate-100 text-slate-500 border-slate-200';
  if (v >= 75) return 'bg-emerald-50 text-emerald-700 border-emerald-200';
  if (v >= 55) return 'bg-amber-50 text-amber-700 border-amber-200';
  return 'bg-rose-50 text-rose-700 border-rose-200';
};

function Pill({ label, value, missing = [], testid }) {
  const hasMissing = missing && missing.length > 0;
  return (
    <div
      data-testid={testid}
      className={`flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-[10px] font-semibold ${SCORE_COLOR(value)}`}
      title={hasMissing ? `Missing inputs: ${missing.join(', ')} — weights redistributed` : undefined}
    >
      <span className="uppercase tracking-wide">{label}</span>
      <span className="tabular-nums">{value == null ? '—' : Math.round(value)}</span>
      {hasMissing && <span className="text-[9px] opacity-70">·{missing.length}</span>}
    </div>
  );
}

export default function V3ScoreBadges({ scores, guardrails }) {
  if (!scores) return null;
  const { quality, health, exit: exitScore, add, quality_missing = [], health_missing = [] } = scores;
  return (
    <div className="flex flex-wrap items-center gap-1.5 mt-2" data-testid="v3-score-badges">
      <Pill testid="v3-quality" label="Q" value={quality} missing={quality_missing} />
      <Pill testid="v3-health" label="H" value={health} missing={health_missing} />
      <Pill testid="v3-exit" label="E" value={exitScore} />
      <Pill testid="v3-add" label="A" value={add} />
      {guardrails && guardrails.length > 0 && (
        <span
          data-testid="v3-guardrail-flag"
          className="ml-1 text-[10px] px-2 py-0.5 rounded-full bg-indigo-50 text-indigo-700 border border-indigo-200"
          title={`V3 Guardrails triggered: ${guardrails.join(', ')}`}
        >
          guardrail · {guardrails.length}
        </span>
      )}
    </div>
  );
}
