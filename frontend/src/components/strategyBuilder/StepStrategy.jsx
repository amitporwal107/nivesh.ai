/**
 * Step 2: Strategy.
 *
 * Show the 5 builtin templates as cards. Selecting a template clones
 * its DSL into the wizard's `definition` state. The user can rename
 * before saving in Step 5.
 */
import React, { useEffect, useState } from "react";
import { Settings, Check, Zap, Target, Layers, TrendingUp, Wind } from "lucide-react";
import { Button } from "@/components/ui/button";
import { listTemplates } from "@/api/strategyBuilder";

// Map template key → icon. Falls back to Settings for unknown keys.
const ICONS = {
  momentum_breakout:           Zap,
  accumulation:                Layers,
  mean_reversion:              Target,
  volatility_breakout:         Wind,
  strong_uptrend_continuation: TrendingUp,
};


export default function StepStrategy({ universe, value, onChange, onNext, onBack }) {
  const [templates, setTemplates] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    listTemplates()
      .then((r) => { if (!cancelled) setTemplates(r?.templates || []); })
      .catch(() => { if (!cancelled) setTemplates([]); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, []);

  const handlePick = (t) => {
    // Splice the chosen universe into the template definition so the
    // user's Step-1 selection isn't overwritten by the template default.
    const def = { ...t.definition, universe };
    onChange({ key: t.key, definition: def });
  };

  return (
    <div data-testid="step-strategy-content">
      <div className="mb-4">
        <h2 className="text-lg font-semibold text-slate-900 dark:text-white">Pick a strategy template</h2>
        <p className="text-[12px] text-slate-500 dark:text-slate-400 mt-0.5">
          Each template encodes a proven setup. Tweak conditions in the next step.
        </p>
      </div>

      {loading ? (
        <div className="text-xs text-slate-400">Loading templates…</div>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          {templates.map((t) => {
            const Icon = ICONS[t.key] || Settings;
            const sel = value?.key === t.key;
            const predicateCount = (t.definition?.entry?.all_of?.length || 0)
                                 + (t.definition?.entry?.any_of?.length || 0);
            return (
              <button
                key={t.key} type="button"
                onClick={() => handlePick(t)}
                className={`text-left p-4 rounded-xl border transition-all ${
                  sel
                    ? "border-emerald-500 bg-emerald-50/60 dark:bg-emerald-900/20 ring-2 ring-emerald-500/20"
                    : "border-slate-200 dark:border-slate-700 hover:border-emerald-300 dark:hover:border-emerald-700 bg-white dark:bg-slate-900"
                }`}
                data-testid={`strategy-card-${t.key}`}
              >
                <div className="flex items-start justify-between mb-2">
                  <div className={`w-8 h-8 rounded-lg flex items-center justify-center ${
                    sel ? "bg-emerald-500 text-white" : "bg-slate-100 dark:bg-slate-800 text-slate-500 dark:text-slate-400"
                  }`}>
                    <Icon className="w-4 h-4" />
                  </div>
                  {sel && <Check className="w-4 h-4 text-emerald-600" />}
                </div>
                <div className="font-semibold text-slate-900 dark:text-white text-sm mb-1">{t.name}</div>
                <p className="text-[11px] text-slate-500 dark:text-slate-400 leading-snug mb-2">
                  {t.description}
                </p>
                <div className="flex items-center gap-2 text-[10px] text-slate-400">
                  <span className="px-1.5 py-0.5 rounded bg-slate-100 dark:bg-slate-800">
                    {predicateCount} conditions
                  </span>
                  <span className="px-1.5 py-0.5 rounded bg-slate-100 dark:bg-slate-800 capitalize">
                    {t.definition?.rebalance || "daily"}
                  </span>
                </div>
              </button>
            );
          })}
        </div>
      )}

      <div className="flex justify-between mt-6">
        <Button variant="outline" onClick={onBack}>← Back</Button>
        <Button onClick={onNext} disabled={!value?.definition} data-testid="step-strategy-next">
          Next → Screen
        </Button>
      </div>
    </div>
  );
}
