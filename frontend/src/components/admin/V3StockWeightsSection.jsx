import React, { useEffect, useState } from "react";
import axios from "axios";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { RefreshCw, Save, RotateCcw, AlertTriangle, CheckCircle2, Sliders } from "lucide-react";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

const DIMENSION_META = {
  quality: { color: "emerald", label: "Quality", desc: "Long-term strength — non-market dependent" },
  health:  { color: "sky",     label: "Health",  desc: "Current trajectory — momentum + stability" },
  exit:    { color: "rose",    label: "Exit",    desc: "Sell-signal — portfolio-aware friction" },
  add:     { color: "amber",   label: "Add",     desc: "Buy/top-up — portfolio-driven" },
};

const TONE = {
  emerald: "border-emerald-200 bg-emerald-50 text-emerald-800",
  sky:     "border-sky-200 bg-sky-50 text-sky-800",
  rose:    "border-rose-200 bg-rose-50 text-rose-800",
  amber:   "border-amber-200 bg-amber-50 text-amber-800",
};

const DimensionEditor = ({ dimension, weights, onChange }) => {
  // Exclude `reserved` padding from the sum display
  const entries = Object.entries(weights).filter(([k]) => k !== "reserved");
  const total = entries.reduce((s, [, v]) => s + Number(v || 0), 0);
  const valid = Math.abs(total - 100) <= 0.5 || Math.abs(Object.values(weights).reduce((a, b) => a + Number(b || 0), 0) - 100) <= 0.5;
  const meta = DIMENSION_META[dimension] || { color: "slate", label: dimension, desc: "" };

  return (
    <div className={`rounded-2xl border p-4 ${TONE[meta.color] || "border-slate-200 bg-slate-50"}`} data-testid={`stock-weight-editor-${dimension}`}>
      <div className="flex items-center justify-between mb-1">
        <div>
          <h4 className="text-sm font-bold uppercase tracking-wider">{meta.label}</h4>
          <p className="text-[11px] opacity-70">{meta.desc}</p>
        </div>
        <span className={`text-xs font-mono tabular-nums px-2 py-0.5 rounded ${valid ? "bg-emerald-100 text-emerald-700" : "bg-rose-100 text-rose-700"}`} data-testid={`stock-weight-total-${dimension}`}>
          Σ = {total}/100{!valid && " ⚠"}
        </span>
      </div>
      <div className="space-y-1.5 mt-3">
        {entries.map(([comp, v]) => (
          <div key={comp} className="flex items-center justify-between gap-3">
            <label className="text-xs text-slate-700 capitalize flex-1 truncate">
              {comp.replace(/_/g, " ")}
            </label>
            <input
              type="number"
              min={0}
              max={100}
              step={5}
              value={v}
              onChange={(e) => onChange(dimension, comp, Number(e.target.value || 0))}
              className="w-20 text-sm text-right font-mono rounded border border-slate-300 px-2 py-1 bg-white"
              data-testid={`stock-weight-${dimension}-${comp}`}
            />
          </div>
        ))}
      </div>
    </div>
  );
};

const V3StockWeightsSection = () => {
  const [weights, setWeights] = useState(null);
  const [defaults, setDefaults] = useState(null);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [error, setError] = useState(null);

  const load = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await axios.get(`${API}/admin/v3-stock-weights`, { withCredentials: true });
      setWeights(res.data.weights);
      setDefaults(res.data.defaults);
      setDirty(false);
    } catch (e) {
      setError(e.response?.data?.detail || e.message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, []);

  const onChange = (dim, comp, val) => {
    setWeights((prev) => ({
      ...prev,
      [dim]: { ...prev[dim], [comp]: val },
    }));
    setDirty(true);
  };

  const onSave = async () => {
    setSaving(true);
    try {
      await axios.put(`${API}/admin/v3-stock-weights`, { weights }, { withCredentials: true });
      toast.success("Stock weights saved");
      setDirty(false);
    } catch (e) {
      toast.error(`Save failed: ${e.response?.data?.detail || e.message}`);
    } finally {
      setSaving(false);
    }
  };

  const onReset = async () => {
    if (!window.confirm("Reset Equity weights to the V3 framework defaults?")) return;
    setSaving(true);
    try {
      const res = await axios.post(`${API}/admin/v3-stock-weights/reset`, {}, { withCredentials: true });
      setWeights(res.data.weights);
      setDirty(false);
      toast.success("Equity weights reset to defaults");
    } catch (e) {
      toast.error(`Reset failed: ${e.message}`);
    } finally {
      setSaving(false);
    }
  };

  if (error && !weights) {
    return (
      <div className="rounded-2xl border border-rose-200 bg-rose-50 p-4 text-sm text-rose-700" data-testid="stock-weights-error">
        Failed to load: {error}
        <Button size="sm" variant="outline" className="ml-3" onClick={load}>Retry</Button>
      </div>
    );
  }
  if (!weights) {
    return (
      <div className="rounded-2xl border border-slate-200 p-10 text-center text-sm text-slate-500" data-testid="stock-weights-loading">
        <RefreshCw className="w-5 h-5 animate-spin inline-block mr-2" />Loading Stock V3 weights…
      </div>
    );
  }

  return (
    <div className="space-y-4" data-testid="v3-stock-weights-section">
      <div className="rounded-2xl border border-slate-200 bg-white p-5">
        <div className="flex items-center justify-between flex-wrap gap-3">
          <div>
            <h2 className="text-base font-semibold text-slate-900 flex items-center gap-2">
              <Sliders className="w-4 h-4" />
              Equity V3 Weights — Quality / Health / Exit / Add
            </h2>
            <p className="text-xs text-slate-500 mt-0.5">
              Per-dimension weight profile for direct equity scoring. PE-band
              and Beta intentionally removed (valuation ≠ quality; beta noisy
              for retail). Add score is portfolio-aware: Sector gap + Low overlap +
              Relative valuation dominate.
            </p>
          </div>
          <div className="flex items-center gap-2">
            <Button size="sm" variant="outline" onClick={load} disabled={loading} data-testid="stock-weights-refresh">
              <RefreshCw className={`w-4 h-4 mr-1 ${loading ? "animate-spin" : ""}`} />Refresh
            </Button>
            <Button size="sm" variant="outline" onClick={onReset} disabled={saving} data-testid="stock-weights-reset">
              <RotateCcw className="w-4 h-4 mr-1" />Reset
            </Button>
            <Button size="sm" onClick={onSave} disabled={saving || !dirty}
                    className="bg-emerald-600 hover:bg-emerald-700 text-white" data-testid="stock-weights-save">
              <Save className="w-4 h-4 mr-1" />{saving ? "Saving…" : dirty ? "Save" : "Saved"}
            </Button>
          </div>
        </div>
        {dirty && (
          <div className="mt-3 flex items-center gap-2 text-xs text-amber-700">
            <AlertTriangle className="w-3.5 h-3.5" /> Unsaved changes — click Save.
          </div>
        )}
        {!dirty && !loading && (
          <div className="mt-3 flex items-center gap-2 text-xs text-emerald-700">
            <CheckCircle2 className="w-3.5 h-3.5" /> In sync with MongoDB.
          </div>
        )}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
        {["quality", "health", "exit", "add"].map((dim) => (
          <DimensionEditor
            key={dim}
            dimension={dim}
            weights={weights[dim] || {}}
            onChange={onChange}
          />
        ))}
      </div>

      <div className="rounded-xl border border-slate-200 bg-slate-50 p-3 text-[11px] text-slate-600" data-testid="stock-weights-note">
        <strong>Stock primitive sources:</strong> Market cap + cap-bucket from Groww (daily refresh, 24h cache).
        Fundamentals (ROE, D/E, promoter holding, margins, revenue growth) are scraped on-demand during
        portfolio refresh. Primitives that are unavailable default to neutral (50) and are marked
        <em> low-confidence</em> in the score bundle.
      </div>
    </div>
  );
};

export default V3StockWeightsSection;
