import React, { useEffect, useState, useCallback } from "react";
import axios from "axios";
import { Target, ArrowUp, ArrowDown, Info, Zap } from "lucide-react";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

/**
 * TodayStrategyCard — converts macro state into "what should I do today?".
 *
 * Fetches /api/macro/today on mount (independent of MacroBar so the card
 * works wherever it's dropped) and renders four bullets:
 *
 *   • Bias        — the directional stance for the day
 *   • Aggression  — multiplier × risk band
 *   • Focus       — top 3 macro-tailwind sectors (chips)
 *   • Avoid       — top 3 macro-headwind sectors (chips)
 *
 * Plus a one-line "thinking out loud" interpretation, the macro confidence
 * pill, and (when warranted) a red risk warning banner above the card.
 */
export default function TodayStrategyCard() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await axios.get(`${API}/macro/today`, { withCredentials: true });
      setData(res.data);
    } catch {
      // The MacroBar above this surfaces the actual error — we silently
      // degrade to the empty placeholder here so the user doesn't see
      // two error banners stacked.
      setData(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  if (loading) {
    return (
      <div className="rounded-xl border border-slate-200 bg-white px-4 py-3 text-[12px] text-slate-500" data-testid="today-strategy-loading">
        Computing today&apos;s strategy…
      </div>
    );
  }

  if (!data || data._uninitialised) {
    return (
      <div className="rounded-xl border border-slate-200 bg-slate-50 px-4 py-3 text-[12px] text-slate-500" data-testid="today-strategy-empty">
        <div className="flex items-center gap-2">
          <Target className="w-3.5 h-3.5" />
          <span className="text-[10px] uppercase tracking-wider font-bold text-slate-500">
            Today&apos;s strategy
          </span>
        </div>
        <div className="mt-1 italic">
          Macro layer initialising — strategy populates after first ingest.
        </div>
      </div>
    );
  }

  const s = data.strategy || {};
  const conf = data.confidence || {};
  const interp = data.interpretation;
  const warning = data.risk_warning;

  return (
    <div className="space-y-2" data-testid="today-strategy-card">
      {warning && (
        <div className="rounded-lg border-2 border-rose-300 bg-rose-50 px-3 py-2 text-[12px] font-semibold text-rose-900 flex items-start gap-2" data-testid="risk-warning-banner">
          <Zap className="w-4 h-4 flex-shrink-0 mt-0.5" />
          <span>{warning}</span>
        </div>
      )}
      <div className={`rounded-xl border-2 ${
        conf.label === "High" ? "border-emerald-300 bg-gradient-to-br from-emerald-50 to-emerald-100/40" :
        conf.label === "Moderate" ? "border-indigo-300 bg-gradient-to-br from-indigo-50 to-indigo-100/40" :
        "border-amber-300 bg-gradient-to-br from-amber-50 to-amber-100/40"
      } px-5 py-4`}>
        <div className="flex items-start justify-between gap-3 flex-wrap">
          <div className="flex items-center gap-2 min-w-0">
            <Target className="w-4 h-4 text-slate-700 flex-shrink-0" />
            <span className="text-[10px] uppercase tracking-wider font-bold text-slate-700">
              Today&apos;s strategy
            </span>
          </div>
          {conf.pct != null && (
            <span
              className={`text-[10.5px] font-mono px-2 py-0.5 rounded-full font-bold inline-flex items-center gap-1 ${
                conf.label === "High" ? "bg-emerald-600 text-white" :
                conf.label === "Moderate" ? "bg-indigo-600 text-white" :
                "bg-amber-600 text-white"
              }`}
              title="Macro confidence — derived from the composite risk score"
              data-testid="today-strategy-confidence"
            >
              Confidence: {Number(conf.pct).toFixed(0)}% · {conf.label}
            </span>
          )}
        </div>

        <ul className="mt-3 space-y-1.5 text-[12.5px] text-slate-800">
          <li className="flex items-start gap-2">
            <span className="text-slate-500 font-semibold w-20 flex-shrink-0">Bias:</span>
            <span className="font-semibold">{s.bias || "—"}</span>
          </li>
          <li className="flex items-start gap-2">
            <span className="text-slate-500 font-semibold w-20 flex-shrink-0">Aggression:</span>
            <span className="font-mono tabular-nums">{s.aggression || "—"}</span>
          </li>
          <li className="flex items-start gap-2">
            <span className="text-slate-500 font-semibold w-20 flex-shrink-0">Focus:</span>
            <span className="flex flex-wrap gap-1">
              {(s.focus_sectors || []).length === 0 ? (
                <span className="italic text-slate-500 text-[11px]">No strong tailwinds today</span>
              ) : s.focus_sectors.map((sec) => (
                <span key={sec} className="inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded bg-emerald-100 text-emerald-800 border border-emerald-200 text-[11px] font-semibold">
                  <ArrowUp className="w-2.5 h-2.5" />
                  {sec.replace(/_/g, " ")}
                </span>
              ))}
            </span>
          </li>
          <li className="flex items-start gap-2">
            <span className="text-slate-500 font-semibold w-20 flex-shrink-0">Avoid:</span>
            <span className="flex flex-wrap gap-1">
              {(s.avoid_sectors || []).length === 0 ? (
                <span className="italic text-slate-500 text-[11px]">No sector strongly penalised</span>
              ) : s.avoid_sectors.map((sec) => (
                <span key={sec} className="inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded bg-rose-100 text-rose-800 border border-rose-200 text-[11px] font-semibold">
                  <ArrowDown className="w-2.5 h-2.5" />
                  {sec.replace(/_/g, " ")}
                </span>
              ))}
            </span>
          </li>
        </ul>

        {interp && (
          <div className="mt-3 pt-3 border-t border-slate-200/60 text-[11.5px] text-slate-700 flex items-start gap-1.5">
            <Info className="w-3.5 h-3.5 text-slate-500 flex-shrink-0 mt-0.5" />
            <span><span className="font-semibold">Interpretation:</span> {interp}</span>
          </div>
        )}
      </div>
    </div>
  );
}
