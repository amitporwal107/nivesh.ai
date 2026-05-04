import React, { useEffect, useState, useCallback } from "react";
import axios from "axios";
import { History, ArrowRight, RefreshCw } from "lucide-react";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

/**
 * WhatChanged — diff between today's macro state and the previous
 * trading day's. Shows regime-field changes (e.g. risk MEDIUM → HIGH)
 * and the top-5 sector tilt deltas, with tier-change tags ("BUY → STRONG BUY").
 *
 * Hidden when there's not enough history (need ≥ 2 days). Backend handles
 * the soft-failure path and we render nothing in that case so the layout
 * stays clean on first deploy.
 */
export default function WhatChanged() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await axios.get(`${API}/macro/changes`, { withCredentials: true });
      setData(res.data);
    } catch {
      setData(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  if (loading) return null;
  if (!data || data._uninitialised || data._error) return null;

  const regime = data.regime_changes || [];
  const sectors = data.sector_changes || [];
  // Don't render the strip if there's literally nothing to show
  if (regime.length === 0 && sectors.length === 0) {
    return null;
  }

  return (
    <div className="rounded-xl border border-slate-200 bg-white px-4 py-3" data-testid="what-changed">
      <div className="flex items-center justify-between gap-2 mb-2 flex-wrap">
        <div className="flex items-center gap-2">
          <History className="w-4 h-4 text-slate-500" />
          <span className="text-[10px] uppercase tracking-wider font-bold text-slate-500">
            What changed since yesterday
          </span>
          {data.previous_date && (
            <span className="text-[10.5px] text-slate-400 font-mono">
              {data.previous_date} → {data.today_date}
            </span>
          )}
        </div>
        <button
          onClick={load}
          className="text-[11px] text-slate-500 hover:text-slate-700 inline-flex items-center gap-1"
          title="Reload"
        >
          <RefreshCw className="w-3 h-3" /> Refresh
        </button>
      </div>

      {data.headline && (
        <div className="text-[12.5px] font-semibold text-slate-800 mb-2">{data.headline}</div>
      )}

      {regime.length > 0 && (
        <div className="mb-2 space-y-1">
          {regime.map((r) => (
            <div key={r.field} className="text-[12px] text-slate-700 flex items-center gap-2 flex-wrap">
              <span className="text-[10px] uppercase tracking-wider font-bold text-slate-500 w-20 flex-shrink-0">
                {r.field}
              </span>
              <span className="font-mono text-slate-500">{String(r.from)}</span>
              <ArrowRight className="w-3 h-3 text-slate-400" />
              <span className={`font-mono font-bold ${
                _changeTone(r.field, r.from, r.to)
              }`}>
                {String(r.to)}
              </span>
            </div>
          ))}
        </div>
      )}

      {sectors.length > 0 && (
        <div className="space-y-1">
          {sectors.map((s) => (
            <div key={s.sector} className="text-[12px] flex items-center gap-2 flex-wrap">
              <span className="font-semibold text-slate-800 w-24 flex-shrink-0">
                {s.sector.replace(/_/g, " ")}
              </span>
              <span className="font-mono text-slate-500">{Number(s.from).toFixed(1)}</span>
              <ArrowRight className="w-3 h-3 text-slate-400" />
              <span className={`font-mono font-bold ${
                Number(s.delta) > 0 ? "text-emerald-700" : "text-rose-700"
              }`}>
                {Number(s.to).toFixed(1)}
              </span>
              <span className={`text-[10px] font-mono ${
                Number(s.delta) > 0 ? "text-emerald-600" : "text-rose-600"
              }`}>
                ({Number(s.delta) > 0 ? "+" : ""}{Number(s.delta).toFixed(2)})
              </span>
              {s.tier_change && (
                <span className="text-[10.5px] uppercase tracking-wider font-bold px-1.5 py-0.5 rounded bg-amber-100 text-amber-800 border border-amber-200">
                  {s.tier_change}
                </span>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// Risk-bands move in opposite direction from market regimes for "good" colour.
function _changeTone(field, from, to) {
  if (field === "risk") {
    // LOW good → MEDIUM/HIGH bad
    if (from === "LOW" && to !== "LOW") return "text-rose-700";
    if (to === "LOW") return "text-emerald-700";
    if (to === "HIGH") return "text-rose-700";
    return "text-amber-700";
  }
  if (field === "market") {
    if (to === "BULL") return "text-emerald-700";
    if (to === "BEAR") return "text-rose-700";
    return "text-amber-700";
  }
  if (field === "inflation") {
    return to === "RISING" ? "text-rose-700" : "text-emerald-700";
  }
  if (field === "liquidity") {
    return to === "TIGHT" ? "text-rose-700" : "text-emerald-700";
  }
  if (field === "multiplier") {
    return Number(to) > Number(from) ? "text-emerald-700" : "text-rose-700";
  }
  return "text-slate-800";
}
