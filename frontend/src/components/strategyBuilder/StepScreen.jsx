/**
 * Step 3: Screen.
 *
 * Phase-1 surface: read-only display of the selected template's
 * predicates with raw JSON view + delete-individual-predicate. Editing
 * (drag-add new predicates with numeric controls) lands in Phase 2.
 *
 * The user can still tweak limits/sl/tg via the right-hand "tunables" panel.
 */
import React, { useState } from "react";
import { Search, Trash2, Code2, Eye } from "lucide-react";
import { Button } from "@/components/ui/button";


// Render a predicate as human-friendly inline text
const renderPredicate = (p) => {
  if (p.sector) {
    const op = p.op === "in" ? "in" : "not in";
    return <>sector <strong>{op}</strong> [{(p.value || []).join(", ")}]</>;
  }
  const ns = ["feature", "fundamental", "shareholding", "institutional", "mf"].find((k) => k in p);
  if (!ns) return JSON.stringify(p);
  const field = p[ns];
  if (p.compare_to) {
    return <>{field} <strong>{p.op}</strong> {p.compare_to}</>;
  }
  return <>{field} <strong>{p.op}</strong> {p.value}</>;
};


export default function StepScreen({ definition, onChange, onNext, onBack }) {
  const [showJson, setShowJson] = useState(false);
  const allOf = definition?.entry?.all_of || [];
  const anyOf = definition?.entry?.any_of || [];
  const exit_ = definition?.exit || {};
  const ranking = definition?.ranking || {};

  const removePredicate = (kind, idx) => {
    const next = JSON.parse(JSON.stringify(definition));
    if (kind === "all") next.entry.all_of.splice(idx, 1);
    if (kind === "any") next.entry.any_of.splice(idx, 1);
    onChange(next);
  };

  const updateExit = (key, val) => {
    const next = JSON.parse(JSON.stringify(definition));
    next.exit = { ...next.exit, [key]: val };
    onChange(next);
  };
  const updateRanking = (key, val) => {
    const next = JSON.parse(JSON.stringify(definition));
    next.ranking = { ...next.ranking, [key]: val };
    onChange(next);
  };

  return (
    <div data-testid="step-screen-content">
      <div className="flex items-start justify-between mb-4">
        <div>
          <h2 className="text-lg font-semibold text-slate-900 dark:text-white">Screen conditions</h2>
          <p className="text-[12px] text-slate-500 dark:text-slate-400 mt-0.5">
            Review the entry rules and tune exit / ranking. Drag-add of new conditions ships in Phase 2.
          </p>
        </div>
        <button
          type="button"
          onClick={() => setShowJson((s) => !s)}
          className="text-[11px] text-slate-500 hover:text-slate-700 inline-flex items-center gap-1"
          data-testid="toggle-json-view"
        >
          {showJson ? <Eye className="w-3 h-3" /> : <Code2 className="w-3 h-3" />}
          {showJson ? "Visual" : "JSON"}
        </button>
      </div>

      {showJson ? (
        <pre className="bg-slate-900 text-slate-100 rounded-lg p-3 text-[11px] font-mono overflow-x-auto max-h-96">
          {JSON.stringify(definition, null, 2)}
        </pre>
      ) : (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
          {/* Entry predicates */}
          <div className="lg:col-span-2 space-y-3">
            <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-700 rounded-xl p-3">
              <div className="flex items-center gap-2 mb-2">
                <Search className="w-3.5 h-3.5 text-emerald-600" />
                <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-700 dark:text-slate-300">
                  Entry — all_of (must match)
                </h3>
                <span className="text-[10px] text-slate-400">{allOf.length} conditions</span>
              </div>
              {allOf.length === 0 ? (
                <div className="text-xs text-slate-400 italic">No entry conditions.</div>
              ) : (
                <ul className="space-y-1.5">
                  {allOf.map((p, i) => (
                    <li key={i} className="flex items-center justify-between text-[12px] py-1.5 px-2 rounded bg-slate-50 dark:bg-slate-800/60 font-mono text-slate-700 dark:text-slate-200">
                      <span>{renderPredicate(p)}</span>
                      <button
                        onClick={() => removePredicate("all", i)}
                        className="text-slate-400 hover:text-rose-500 ml-2"
                        title="Remove this condition"
                        data-testid={`remove-pred-${i}`}
                      >
                        <Trash2 className="w-3 h-3" />
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </div>

            {anyOf.length > 0 && (
              <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-700 rounded-xl p-3">
                <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-700 dark:text-slate-300 mb-2">
                  Entry — any_of (any match)
                </h3>
                <ul className="space-y-1.5">
                  {anyOf.map((p, i) => (
                    <li key={i} className="text-[12px] py-1.5 px-2 rounded bg-slate-50 dark:bg-slate-800/60 font-mono">
                      {renderPredicate(p)}
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>

          {/* Tunables */}
          <div className="space-y-3">
            <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-700 rounded-xl p-3">
              <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-700 dark:text-slate-300 mb-2">Exit rules</h3>
              <NumericTunable label="Stoploss %" suffix="%" value={exit_.stoploss_pct} step={0.5} min={1} max={50} onChange={(v) => updateExit("stoploss_pct", v)} testid="exit-sl" />
              <NumericTunable label="Target R:R" value={exit_.target_rr} step={0.1} min={0.5} max={10} onChange={(v) => updateExit("target_rr", v)} testid="exit-rr" />
              <NumericTunable label="Max hold (days)" value={exit_.max_hold_days} step={1} min={1} max={120} onChange={(v) => updateExit("max_hold_days", v)} testid="exit-hold" />
              {exit_.trailing_atr_mult !== undefined && (
                <NumericTunable label="Trail × ATR" value={exit_.trailing_atr_mult} step={0.1} min={0.5} max={5} onChange={(v) => updateExit("trailing_atr_mult", v)} testid="exit-trail" />
              )}
            </div>

            <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-700 rounded-xl p-3">
              <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-700 dark:text-slate-300 mb-2">Ranking</h3>
              <div className="text-[11px] text-slate-500 dark:text-slate-400 mb-1">By</div>
              <div className="font-mono text-[12px] mb-2">{ranking.by} ({ranking.order || "desc"})</div>
              <NumericTunable label="Top N picks" value={ranking.limit} step={1} min={1} max={50} onChange={(v) => updateRanking("limit", v)} testid="ranking-limit" />
            </div>
          </div>
        </div>
      )}

      <div className="flex justify-between mt-6">
        <Button variant="outline" onClick={onBack}>← Back</Button>
        <Button onClick={onNext} data-testid="step-screen-next">Next → Backtest</Button>
      </div>
    </div>
  );
}


function NumericTunable({ label, value, step, min, max, suffix, onChange, testid }) {
  return (
    <div className="flex items-center justify-between gap-3 mb-1.5">
      <label className="text-[11px] text-slate-600 dark:text-slate-400 flex-1">{label}</label>
      <input
        type="number"
        value={value ?? ""}
        step={step}
        min={min}
        max={max}
        onChange={(e) => onChange(parseFloat(e.target.value))}
        className="w-20 px-2 py-1 text-xs text-right tabular-nums rounded border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800"
        data-testid={testid}
      />
      {suffix && <span className="text-[10px] text-slate-400 -ml-1">{suffix}</span>}
    </div>
  );
}
