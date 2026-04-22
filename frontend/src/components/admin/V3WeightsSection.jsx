import React, { useEffect, useState, useCallback } from "react";
import axios from "axios";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import {
  RefreshCw, Save, RotateCcw, AlertTriangle, CheckCircle2,
  ChevronDown, ChevronRight, Sliders,
} from "lucide-react";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

const CATEGORY_META = {
  equity:  { color: "emerald", label: "Equity", desc: "Large / Mid / Small / Flexi / ELSS / Focused" },
  hybrid:  { color: "amber",   label: "Hybrid", desc: "Balanced Advantage / Aggressive / Multi-Asset" },
  debt:    { color: "sky",     label: "Debt",   desc: "Short-term / Corporate Bond / Gilt / Credit" },
  liquid:  { color: "indigo",  label: "Liquid", desc: "Liquid / Overnight (scoring deferred)" },
};

const toneMap = {
  emerald: "border-emerald-200 dark:border-emerald-800 bg-emerald-50 dark:bg-emerald-900/20",
  amber:   "border-amber-200 dark:border-amber-800 bg-amber-50 dark:bg-amber-900/20",
  sky:     "border-sky-200 dark:border-sky-800 bg-sky-50 dark:bg-sky-900/20",
  indigo:  "border-indigo-200 dark:border-indigo-800 bg-indigo-50 dark:bg-indigo-900/20",
};
const headerToneMap = {
  emerald: "text-emerald-800 dark:text-emerald-200",
  amber:   "text-amber-800 dark:text-amber-200",
  sky:     "text-sky-800 dark:text-sky-200",
  indigo:  "text-indigo-800 dark:text-indigo-200",
};

const DimensionEditor = ({ category, dimension, weights, onChange }) => {
  const total = Object.values(weights).reduce((a, b) => a + Number(b || 0), 0);
  const valid = Math.abs(total - 100) <= 0.5;

  return (
    <div className="space-y-2" data-testid={`weight-editor-${category}-${dimension}`}>
      <div className="flex items-center justify-between">
        <span className="text-xs font-bold uppercase tracking-wider text-slate-700 dark:text-slate-200">
          {dimension}
        </span>
        <span className={`text-xs font-mono tabular-nums px-2 py-0.5 rounded ${
          valid ? "bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-300"
                : "bg-rose-100 text-rose-700 dark:bg-rose-900/40 dark:text-rose-300"
        }`} data-testid={`weight-total-${category}-${dimension}`}>
          Σ = {total.toFixed(0)}/100{!valid && " ⚠"}
        </span>
      </div>
      <div className="space-y-1.5">
        {Object.entries(weights).map(([comp, v]) => (
          <div key={comp} className="flex items-center gap-2 text-xs">
            <label className="flex-1 text-slate-700 dark:text-slate-300 capitalize truncate"
                   title={comp.replace(/_/g, " ")}>
              {comp.replace(/_/g, " ")}
            </label>
            <input
              type="number"
              min={0}
              max={100}
              step={1}
              value={v}
              onChange={e => onChange(category, dimension, comp, Number(e.target.value || 0))}
              className="w-16 px-2 py-1 text-right text-xs tabular-nums rounded border border-slate-300 dark:border-slate-600 bg-white dark:bg-slate-900 focus:outline-none focus:ring-2 focus:ring-emerald-500/40"
              data-testid={`weight-input-${category}-${dimension}-${comp}`}
            />
            <span className="text-[10px] text-slate-400">%</span>
          </div>
        ))}
      </div>
    </div>
  );
};

const CategoryCard = ({ category, dims, onChange, defaults }) => {
  const meta = CATEGORY_META[category] || CATEGORY_META.equity;
  const [open, setOpen] = useState(true);
  const isCustom = defaults
    ? JSON.stringify(dims) !== JSON.stringify(defaults)
    : false;

  return (
    <div
      className={`rounded-xl border ${toneMap[meta.color]} p-4`}
      data-testid={`weight-card-${category}`}
    >
      <button
        type="button"
        onClick={() => setOpen(x => !x)}
        className="w-full flex items-center justify-between mb-3"
        data-testid={`weight-card-toggle-${category}`}
      >
        <div className="flex items-center gap-2">
          {open ? <ChevronDown className="w-4 h-4" /> : <ChevronRight className="w-4 h-4" />}
          <h3 className={`text-sm font-bold ${headerToneMap[meta.color]}`}>{meta.label}</h3>
          <span className="text-[11px] text-slate-500 dark:text-slate-400">— {meta.desc}</span>
          {isCustom && (
            <span className="text-[10px] px-1.5 py-0.5 rounded bg-amber-200 text-amber-900 dark:bg-amber-800/80 dark:text-amber-100 ml-1">
              modified
            </span>
          )}
        </div>
      </button>
      {open && (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {Object.entries(dims).map(([dim, wmap]) => (
            <DimensionEditor
              key={dim}
              category={category}
              dimension={dim}
              weights={wmap}
              onChange={onChange}
            />
          ))}
        </div>
      )}
    </div>
  );
};

export default function V3WeightsSection() {
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [weights, setWeights] = useState(null);
  const [defaults, setDefaults] = useState(null);
  const [error, setError] = useState(null);
  const [dirty, setDirty] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const r = await axios.get(`${API}/admin/v3-weights`, {
        withCredentials: true,
        headers: { "Cache-Control": "no-store" },
      });
      setWeights(r.data.weights);
      setDefaults(r.data.defaults);
      setDirty(false);
    } catch (e) {
      setError(e.response?.data?.detail || e.message);
      toast.error("Failed to load V3 weights");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const onChange = (cat, dim, comp, value) => {
    setWeights(prev => ({
      ...prev,
      [cat]: {
        ...prev[cat],
        [dim]: { ...prev[cat][dim], [comp]: value },
      },
    }));
    setDirty(true);
  };

  const onSave = async () => {
    // Pre-validate locally
    const issues = [];
    Object.entries(weights).forEach(([cat, dims]) => {
      Object.entries(dims).forEach(([dim, wmap]) => {
        const sum = Object.values(wmap).reduce((a, b) => a + Number(b || 0), 0);
        if (Math.abs(sum - 100) > 0.5) issues.push(`${cat}.${dim} sums to ${sum}, expected 100`);
      });
    });
    if (issues.length) {
      toast.error(`Fix weights first — ${issues.length} issue(s)`, {
        description: issues.slice(0, 3).join(" · "),
      });
      return;
    }
    setSaving(true);
    try {
      await axios.put(`${API}/admin/v3-weights`, { weights }, { withCredentials: true });
      toast.success("V3 weights saved — rescore will apply on next analytics sweep");
      setDirty(false);
    } catch (e) {
      const detail = e.response?.data?.detail;
      toast.error("Save failed", {
        description: typeof detail === "object"
          ? (detail.issues || []).join(" · ")
          : detail || e.message,
      });
    } finally {
      setSaving(false);
    }
  };

  const onReset = async () => {
    if (!window.confirm("Reset all weights to defaults from the V3.1 PRD?")) return;
    setSaving(true);
    try {
      const r = await axios.post(`${API}/admin/v3-weights/reset`, {}, { withCredentials: true });
      setWeights(r.data.weights);
      toast.success("Weights reset to defaults");
      setDirty(false);
    } catch (e) {
      toast.error(`Reset failed: ${e.message}`);
    } finally {
      setSaving(false);
    }
  };

  if (error && !weights) {
    return (
      <div className="rounded-2xl border border-rose-200 bg-rose-50 dark:bg-rose-900/20 p-4 text-sm text-rose-700 dark:text-rose-300"
           data-testid="v3-weights-error">
        Failed to load: {error}
        <Button size="sm" variant="outline" className="ml-3" onClick={load}>Retry</Button>
      </div>
    );
  }
  if (!weights) {
    return (
      <div className="rounded-2xl border border-slate-200 dark:border-slate-700 p-10 text-center text-sm text-slate-500 dark:text-slate-400"
           data-testid="v3-weights-loading">
        <RefreshCw className="w-5 h-5 animate-spin inline-block mr-2" />Loading V3 weights…
      </div>
    );
  }
  if (error) {
    return (
      <div className="rounded-2xl border border-rose-200 bg-rose-50 dark:bg-rose-900/20 p-4 text-sm text-rose-700 dark:text-rose-300"
           data-testid="v3-weights-error">
        Failed to load: {error}
        <Button size="sm" variant="outline" className="ml-3" onClick={load}>Retry</Button>
      </div>
    );
  }

  return (
    <div className="space-y-4" data-testid="v3-weights-section">
      {/* Header */}
      <div className="rounded-2xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 p-5">
        <div className="flex items-center justify-between flex-wrap gap-3">
          <div>
            <h2 className="text-base font-semibold text-slate-900 dark:text-slate-100 flex items-center gap-2">
              <Sliders className="w-4 h-4" />
              V3.1 Category-Aware Weights
            </h2>
            <p className="text-xs text-slate-500 dark:text-slate-400 mt-0.5">
              Per-category weight profiles for Quality &amp; Health scores. Applied
              live on every scoring call — no rescore needed for the V3 Master
              admin view. Persistence to Neon via saved scores happens on the
              next NAV-analytics sweep.
            </p>
          </div>
          <div className="flex items-center gap-2">
            <Button size="sm" variant="outline" onClick={load} disabled={loading}
                    data-testid="v3-weights-refresh">
              <RefreshCw className={`w-4 h-4 mr-1 ${loading ? "animate-spin" : ""}`} />Refresh
            </Button>
            <Button size="sm" variant="outline" onClick={onReset} disabled={saving}
                    data-testid="v3-weights-reset">
              <RotateCcw className="w-4 h-4 mr-1" />Reset to defaults
            </Button>
            <Button size="sm" onClick={onSave} disabled={saving || !dirty}
                    className="bg-emerald-600 hover:bg-emerald-700 text-white"
                    data-testid="v3-weights-save">
              <Save className="w-4 h-4 mr-1" />
              {saving ? "Saving…" : dirty ? "Save changes" : "Saved"}
            </Button>
          </div>
        </div>

        {dirty && (
          <div className="mt-3 flex items-center gap-2 text-xs text-amber-700 dark:text-amber-400">
            <AlertTriangle className="w-3.5 h-3.5" />
            Unsaved changes — click <span className="font-semibold">Save changes</span> to persist to MongoDB.
          </div>
        )}
        {!dirty && !loading && (
          <div className="mt-3 flex items-center gap-2 text-xs text-emerald-700 dark:text-emerald-400">
            <CheckCircle2 className="w-3.5 h-3.5" />
            In sync with MongoDB
          </div>
        )}
      </div>

      {/* Category cards */}
      <div className="space-y-3">
        {Object.entries(weights).map(([cat, dims]) => (
          <CategoryCard
            key={cat}
            category={cat}
            dims={dims}
            defaults={defaults?.[cat]}
            onChange={onChange}
          />
        ))}
      </div>

      {/* Note about liquid */}
      <div className="rounded-xl border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800/60 p-3 text-[11px] text-slate-600 dark:text-slate-400"
           data-testid="v3-weights-note">
        <strong>Note on Liquid funds:</strong> per current product decision, Liquid /
        Overnight funds are classified but not yet scored via a custom weight
        profile — they fall through to Equity weights with partial primitives.
        Debt-specific components (credit_quality, yield_vs_category, duration_risk,
        credit_concentration, liquidity) require a Value Research /
        Morningstar scrape pass to populate primitives; those components
        currently show as "missing" and renormalise over what's available.
      </div>
    </div>
  );
}
