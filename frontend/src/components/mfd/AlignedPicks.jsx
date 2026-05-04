import React, { useEffect, useState, useCallback } from "react";
import axios from "axios";
import { Zap, ChevronRight, Sparkles, Activity } from "lucide-react";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

/**
 * AlignedPicks — preview of positional candidates whose sector aligns
 * with today's macro tailwinds. Shows BEFORE the actual positional
 * picks land for the day, so the user has anticipation rather than an
 * empty "no picks yet" state.
 *
 * Backend's /macro/aligned-picks endpoint:
 *   - Tries positional_signals (today's actionable list) first
 *   - Falls back to stock_technical_features (preview) when no signals
 *
 * Renders nothing when there are no tailwind sectors at all (avoids
 * adding a noisy empty card to the dashboard).
 */
export default function AlignedPicks() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await axios.get(`${API}/macro/aligned-picks?limit=5`, { withCredentials: true });
      setData(res.data);
    } catch {
      setData(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  if (loading) {
    return (
      <div className="rounded-xl border border-slate-200 bg-white px-4 py-3 text-[12px] text-slate-500" data-testid="aligned-picks-loading">
        Looking for setups in tailwind sectors…
      </div>
    );
  }
  if (!data || data._error) return null;

  const sectors = data.sectors || [];
  if (sectors.length === 0) return null;

  return (
    <div className="rounded-xl border border-emerald-200 bg-gradient-to-br from-emerald-50/40 to-white" data-testid="aligned-picks">
      <div className="px-4 py-3 border-b border-emerald-100 flex items-center gap-2 flex-wrap">
        <Zap className="w-4 h-4 text-emerald-600" />
        <span className="text-[10px] uppercase tracking-wider font-bold text-emerald-700">
          Macro-aligned opportunities
        </span>
        <span className="text-[11px] text-slate-500">
          Setups in today&apos;s tailwind sectors — {data.total_candidates} candidate{data.total_candidates !== 1 ? "s" : ""} across {sectors.length} sector{sectors.length !== 1 ? "s" : ""}
        </span>
      </div>
      <div className="p-3 space-y-2">
        {sectors.map((s) => <SectorBucket key={s.sector} bucket={s} />)}
      </div>
    </div>
  );
}

function SectorBucket({ bucket }) {
  const isPreview = (bucket.source || "").includes("preview");
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-3" data-testid={`aligned-bucket-${bucket.sector}`}>
      <div className="flex items-center justify-between gap-2 mb-1.5 flex-wrap">
        <div className="flex items-center gap-2">
          <Sparkles className="w-3.5 h-3.5 text-emerald-600" />
          <span className="text-[12.5px] font-semibold text-slate-900">
            {bucket.sector.replace(/_/g, " ")}
          </span>
          <span className="text-[10.5px] font-mono font-bold text-emerald-700">
            +{Number(bucket.macro_score).toFixed(1)} tilt
          </span>
        </div>
        {isPreview && (
          <span
            className="text-[9.5px] uppercase tracking-wider font-bold px-1.5 py-0.5 rounded bg-amber-100 text-amber-800 border border-amber-200"
            title="From stock_technical_features — actual positional signals haven't fired yet today"
          >
            Watchlist
          </span>
        )}
      </div>
      <div className="flex flex-wrap gap-1.5">
        {bucket.candidates.map((c) => (
          <span
            key={c.nse_symbol}
            className={`inline-flex items-center gap-1 px-2 py-0.5 rounded text-[11px] font-mono font-semibold border ${
              c.confidence === "HIGH" ? "bg-emerald-50 text-emerald-800 border-emerald-200" :
              c.confidence === "MEDIUM" ? "bg-indigo-50 text-indigo-800 border-indigo-200" :
              "bg-slate-50 text-slate-700 border-slate-200"
            }`}
            title={`${c.stage || "?"} · score ${c.final_score?.toFixed(2) ?? "?"}`}
          >
            <Activity className="w-2.5 h-2.5" />
            {c.nse_symbol}
            {c.final_score != null && (
              <span className="text-[9.5px] opacity-70">{(c.final_score * 100).toFixed(0)}</span>
            )}
          </span>
        ))}
        <ChevronRight className="w-3 h-3 text-slate-300 self-center" />
      </div>
    </div>
  );
}
