/**
 * GoalsProgressPanel — compact goal progress widget for Home screen.
 *
 * Data: GET /api/goals
 *   → [{ id, name, target_amount_rs, on_track_pct, actual_monthly_sip_rs, sip_shortfall_rs }]
 *
 * Shows top 3 goals with progress bars and a CTA to the full Goals view.
 */
import React, { useEffect, useState } from "react";
import axios from "axios";
import { Target, ArrowRight, Plus } from "lucide-react";
import { cn } from "@/lib/utils";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

const fmtRs = (n) => {
  if (n == null || n === 0) return "₹0";
  if (Math.abs(n) >= 1e7) return `₹${(n / 1e7).toFixed(1)} Cr`;
  if (Math.abs(n) >= 1e5) return `₹${(n / 1e5).toFixed(1)} L`;
  return `₹${Math.round(n).toLocaleString("en-IN")}`;
};

export default function GoalsProgressPanel({ onNavigate }) {
  const [goals, setGoals] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const r = await axios.get(`${API}/goals`, { withCredentials: true });
        if (alive) setGoals(r.data?.goals || r.data || []);
      } catch (_) { /* graceful — render empty state */ }
      finally { if (alive) setLoading(false); }
    })();
    return () => { alive = false; };
  }, []);

  const topGoals = (goals || []).slice(0, 3);

  return (
    <div className="bg-[#1A1A1A] border border-white/5 rounded-2xl p-5 shadow-xl" data-testid="goals-panel">
      <div className="flex items-center justify-between mb-4">
        <h4 className="text-sm font-black text-white tracking-tight flex items-center gap-2">
          <Target className="w-4 h-4 text-rose-400" />
          Your Goals
        </h4>
        {topGoals.length > 0 && (
          <button
            onClick={onNavigate}
            className="text-[9px] font-bold text-indigo-400 uppercase tracking-[0.2em] hover:text-indigo-300 transition-colors"
          >
            View All
          </button>
        )}
      </div>

      {loading ? (
        <div className="space-y-3">
          {[1, 2, 3].map((i) => <div key={i} className="h-14 bg-white/5 rounded-xl animate-pulse" />)}
        </div>
      ) : topGoals.length === 0 ? (
        <button
          onClick={onNavigate}
          className="w-full py-8 px-4 bg-white/[0.02] border border-dashed border-white/10 rounded-xl text-center hover:border-rose-500/30 transition-all group"
        >
          <Plus className="w-6 h-6 text-white/30 mx-auto mb-2 group-hover:text-rose-400 transition-colors" />
          <p className="text-xs font-bold text-white/70 mb-0.5">Set your first goal</p>
          <p className="text-[10px] text-white/40">Retirement, home, kids' education…</p>
        </button>
      ) : (
        <div className="space-y-3">
          {topGoals.map((g) => {
            const pct = Math.max(0, Math.min(100, g.on_track_pct ?? 0));
            const tone = pct >= 80 ? "emerald" : pct >= 50 ? "amber" : "rose";
            const C = {
              emerald: { bar: "bg-emerald-500", text: "text-emerald-400" },
              amber:   { bar: "bg-amber-500",   text: "text-amber-400"   },
              rose:    { bar: "bg-rose-500",    text: "text-rose-400"    },
            }[tone];
            return (
              <button
                key={g.id || g._id || g.name}
                onClick={onNavigate}
                className="w-full text-left p-3 bg-white/[0.02] rounded-xl border border-white/5 hover:bg-white/5 transition-all group"
              >
                <div className="flex items-center justify-between mb-1.5 gap-2">
                  <p className="text-xs font-bold text-white truncate">{g.name || g.goal_name || "Goal"}</p>
                  <span className={cn("text-sm font-black shrink-0", C.text)}>{Math.round(pct)}%</span>
                </div>
                <div className="w-full h-1.5 bg-white/5 rounded-full overflow-hidden mb-1.5">
                  <div className={cn("h-full transition-all", C.bar)} style={{ width: `${pct}%` }} />
                </div>
                <div className="flex items-center justify-between gap-2">
                  <p className="text-[10px] text-white/40 truncate">
                    Target: {fmtRs(g.target_amount_rs || g.target_amount)}
                  </p>
                  {g.sip_shortfall_rs > 0 && (
                    <p className="text-[10px] font-bold text-amber-400 shrink-0">
                      +{fmtRs(g.sip_shortfall_rs)}/mo needed
                    </p>
                  )}
                </div>
              </button>
            );
          })}
        </div>
      )}

      {topGoals.length > 0 && (
        <button
          onClick={onNavigate}
          className="w-full mt-4 py-2 text-[10px] font-bold text-indigo-400 uppercase tracking-widest hover:bg-white/5 rounded-lg transition-all flex items-center justify-center gap-1.5"
        >
          Plan More <ArrowRight className="w-3 h-3" />
        </button>
      )}
    </div>
  );
}
