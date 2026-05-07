/**
 * Step 1: Universe.
 *
 * Phase-1 surface:
 *   • 4 prebuilt index universes (Nifty 50 / 100 / 200 / 500)
 *   • User's saved custom universes (My Universes)
 *   • "Create custom" dialog — paste tickers, save, instantly available
 *
 * Selection writes back to the wizard's `universe` state:
 *   { type: "index"|"custom", ref: "NIFTY50" | <uuid> }
 */
import React, { useEffect, useState } from "react";
import { Globe2, Lock, Plus, X, Check } from "lucide-react";
import { Button } from "@/components/ui/button";
import { listUniverses, createUniverse } from "@/api/strategyBuilder";

const PREBUILT_INDEXES = [
  { ref: "NIFTY50",  name: "Nifty 50",  blurb: "Largest 50 stocks — most liquid, lowest volatility." },
  { ref: "NIFTY100", name: "Nifty 100", blurb: "Top 100 by free-float mcap." },
  { ref: "NIFTY200", name: "Nifty 200", blurb: "Broader large+midcap mix." },
  { ref: "NIFTY500", name: "Nifty 500", blurb: "Full breadth — small/mid/large." },
];


function CustomUniverseDialog({ open, onClose, onCreated }) {
  const [name, setName] = useState("");
  const [tickers, setTickers] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);

  if (!open) return null;
  const handleSave = async () => {
    setError(null);
    const symbols = tickers.split(/[\s,]+/).map((t) => t.trim().toUpperCase()).filter(Boolean);
    if (symbols.length === 0) { setError("Enter at least one ticker"); return; }
    if (!name.trim()) { setError("Name is required"); return; }
    setSaving(true);
    try {
      const u = await createUniverse({ name, asset_class: "STOCK", symbols });
      onCreated(u);
      onClose();
      setName(""); setTickers("");
    } catch (e) {
      setError(e?.response?.data?.detail || "Failed to save universe");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm" onClick={onClose}>
      <div className="bg-white dark:bg-slate-900 rounded-2xl shadow-xl border border-slate-200 dark:border-slate-700 w-full max-w-md p-5 mx-4" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-base font-semibold text-slate-900 dark:text-white">New Custom Universe</h3>
          <button onClick={onClose} className="text-slate-400 hover:text-slate-600">
            <X className="w-4 h-4" />
          </button>
        </div>
        <div className="space-y-3">
          <div>
            <label className="text-[11px] font-medium uppercase tracking-wide text-slate-500">Name</label>
            <input
              type="text" value={name} onChange={(e) => setName(e.target.value)}
              placeholder="e.g. My Watchlist"
              className="w-full mt-1 px-3 py-2 text-sm rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-900 dark:text-white"
              data-testid="universe-name-input"
            />
          </div>
          <div>
            <label className="text-[11px] font-medium uppercase tracking-wide text-slate-500">
              NSE tickers (comma or whitespace separated)
            </label>
            <textarea
              value={tickers} onChange={(e) => setTickers(e.target.value)}
              placeholder="RELIANCE, HDFCBANK, INFY, TCS, ASIANPAINT"
              rows={4}
              className="w-full mt-1 px-3 py-2 text-sm rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-900 dark:text-white font-mono"
              data-testid="universe-tickers-input"
            />
          </div>
          {error && (
            <div className="text-xs text-rose-600 bg-rose-50 dark:bg-rose-900/20 rounded p-2">{error}</div>
          )}
          <div className="flex justify-end gap-2 pt-2">
            <Button variant="outline" size="sm" onClick={onClose}>Cancel</Button>
            <Button size="sm" onClick={handleSave} disabled={saving} data-testid="universe-save-btn">
              {saving ? "Saving…" : "Create"}
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}


export default function StepUniverse({ value, onChange, onNext }) {
  const [customs, setCustoms] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showDialog, setShowDialog] = useState(false);

  const reload = async () => {
    setLoading(true);
    try {
      const res = await listUniverses("STOCK");
      setCustoms(res?.universes || []);
    } catch {
      setCustoms([]);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { reload(); }, []);

  const isSelectedIndex = (ref) => value?.type === "index" && value?.ref === ref;
  const isSelectedCustom = (id) => value?.type === "custom" && value?.ref === id;

  return (
    <div data-testid="step-universe-content">
      <div className="mb-4">
        <h2 className="text-lg font-semibold text-slate-900 dark:text-white">Select your stock universe</h2>
        <p className="text-[12px] text-slate-500 dark:text-slate-400 mt-0.5">
          The pool the strategy screens against. Smaller, focused universes backtest faster and produce sharper signals.
        </p>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 mb-5">
        {PREBUILT_INDEXES.map((u) => {
          const sel = isSelectedIndex(u.ref);
          return (
            <button
              key={u.ref}
              type="button"
              onClick={() => onChange({ type: "index", ref: u.ref })}
              className={`text-left p-3 rounded-xl border transition-all ${
                sel
                  ? "border-emerald-500 bg-emerald-50/60 dark:bg-emerald-900/20 ring-2 ring-emerald-500/20"
                  : "border-slate-200 dark:border-slate-700 hover:border-emerald-300 dark:hover:border-emerald-700 bg-white dark:bg-slate-900"
              }`}
              data-testid={`universe-card-${u.ref}`}
            >
              <div className="flex items-center justify-between mb-1">
                <div className="flex items-center gap-2">
                  <Globe2 className={`w-4 h-4 ${sel ? "text-emerald-600" : "text-slate-400"}`} />
                  <span className="font-semibold text-slate-900 dark:text-white">{u.name}</span>
                </div>
                {sel && <Check className="w-4 h-4 text-emerald-600" />}
              </div>
              <p className="text-[11px] text-slate-500 dark:text-slate-400 leading-snug">{u.blurb}</p>
            </button>
          );
        })}
      </div>

      <div className="flex items-center justify-between mb-2">
        <h3 className="text-sm font-semibold text-slate-700 dark:text-slate-300 flex items-center gap-1.5">
          <Lock className="w-3.5 h-3.5" /> My Universes
        </h3>
        <Button
          variant="outline"
          size="sm"
          onClick={() => setShowDialog(true)}
          className="text-xs h-7"
          data-testid="universe-create-btn"
        >
          <Plus className="w-3 h-3 mr-1" /> Create custom
        </Button>
      </div>
      {loading ? (
        <div className="text-xs text-slate-400">Loading…</div>
      ) : customs.length === 0 ? (
        <div className="text-xs text-slate-400 dark:text-slate-500 italic p-3 rounded-lg border border-dashed border-slate-200 dark:border-slate-700">
          No custom universes yet — click "Create custom" to add one.
        </div>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
          {customs.map((u) => {
            const sel = isSelectedCustom(u.id);
            return (
              <button
                key={u.id} type="button"
                onClick={() => onChange({ type: "custom", ref: u.id })}
                className={`text-left p-2.5 rounded-lg border ${
                  sel
                    ? "border-emerald-500 bg-emerald-50/60 dark:bg-emerald-900/20"
                    : "border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900"
                }`}
                data-testid={`universe-card-custom-${u.id}`}
              >
                <div className="flex items-center justify-between">
                  <span className="font-medium text-sm text-slate-900 dark:text-white truncate">{u.name}</span>
                  <span className="text-[10px] text-slate-400">{(u.symbols || []).length} stocks</span>
                </div>
              </button>
            );
          })}
        </div>
      )}

      <div className="flex justify-end mt-6">
        <Button onClick={onNext} disabled={!value?.ref} data-testid="step-universe-next">
          Next → Strategy
        </Button>
      </div>

      <CustomUniverseDialog
        open={showDialog}
        onClose={() => setShowDialog(false)}
        onCreated={(u) => { setCustoms((prev) => [u, ...prev]); onChange({ type: "custom", ref: u.id }); }}
      />
    </div>
  );
}
