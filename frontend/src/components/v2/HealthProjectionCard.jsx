import React, { useState, useEffect } from "react";
import axios from "axios";
import { motion } from "framer-motion";
import { Card } from "@/components/ui/card";
import { TrendingUp, TrendingDown, Minus, Sparkles } from "lucide-react";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
const API = `${BACKEND_URL}/api`;

/**
 * Shows current vs projected Portfolio Health if all pending actions are
 * implemented. Data source: GET /api/plans/active/health-projection.
 */
const HealthProjectionCard = () => {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let mounted = true;
    (async () => {
      try {
        const res = await axios.get(`${API}/plans/active/health-projection`, { withCredentials: true });
        if (mounted) setData(res.data);
      } catch {
        if (mounted) setData({ available: false });
      } finally {
        if (mounted) setLoading(false);
      }
    })();
    return () => { mounted = false; };
  }, []);

  if (loading || !data?.available || !data.current) return null;

  const current = Math.round(data.current.health_score || 0);
  const projected = data.projected ? Math.round(data.projected.health_score || 0) : null;
  const delta = data.delta_total;
  const improving = delta !== null && delta > 0;
  const worsening = delta !== null && delta < 0;
  const Icon = improving ? TrendingUp : worsening ? TrendingDown : Minus;
  const tone = improving ? "emerald" : worsening ? "rose" : "slate";

  const TONE_CLASSES = {
    emerald: { ring: "ring-emerald-500/30", bg: "bg-emerald-50", text: "text-emerald-700", bar: "bg-emerald-500" },
    rose:    { ring: "ring-rose-500/30",    bg: "bg-rose-50",    text: "text-rose-700",    bar: "bg-rose-500" },
    slate:   { ring: "ring-slate-300",      bg: "bg-slate-50",   text: "text-slate-700",   bar: "bg-slate-500" },
  };
  const t = TONE_CLASSES[tone];

  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: 0.1 }}
      className="mb-6"
      data-testid="health-projection-card"
    >
      <Card className={`p-6 bg-white border ring-1 ${t.ring}`}>
        <div className="flex items-start justify-between gap-6 flex-wrap">
          <div className="flex items-center gap-4">
            <div className={`w-12 h-12 rounded-full ${t.bg} flex items-center justify-center`}>
              <Sparkles className={`w-5 h-5 ${t.text}`} />
            </div>
            <div>
              <h3 className="text-sm font-bold uppercase tracking-wider text-slate-500 mb-1">
                Plan Impact on Portfolio Health
              </h3>
              <p className="text-[13px] text-slate-600 max-w-xl" data-testid="health-projection-message">
                {data.message}
              </p>
            </div>
          </div>

          {/* Current → Projected */}
          <div className="flex items-center gap-3">
            <div className="text-center">
              <div className="text-[10px] uppercase tracking-wider text-slate-400 mb-1">Current</div>
              <div className="text-3xl font-black text-slate-900" data-testid="ph-current-score">{current}</div>
              <div className="text-[10px] text-slate-500">{data.current.grade}</div>
            </div>
            <div className={`flex items-center justify-center w-10 h-10 rounded-full ${t.bg}`}>
              <Icon className={`w-4 h-4 ${t.text}`} />
            </div>
            <div className="text-center">
              <div className="text-[10px] uppercase tracking-wider text-slate-400 mb-1">Projected</div>
              <div className={`text-3xl font-black ${t.text}`} data-testid="ph-projected-score">
                {projected != null ? projected : "—"}
              </div>
              <div className="text-[10px] text-slate-500">
                {data.projected?.grade || "—"}
                {delta !== null && (
                  <span className={`ml-1 font-semibold ${t.text}`} data-testid="ph-delta">
                    ({delta > 0 ? "+" : ""}{delta})
                  </span>
                )}
              </div>
            </div>
          </div>
        </div>

        {/* Per-component deltas */}
        {data.delta_by_component && Object.keys(data.delta_by_component).length > 0 && (
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mt-5 pt-5 border-t border-slate-100">
            {["diversification", "risk", "cost", "performance"].map((k) => {
              const d = data.delta_by_component[k];
              if (d === undefined) return null;
              const pos = d > 0; const neg = d < 0;
              const cls = pos ? "text-emerald-600" : neg ? "text-rose-500" : "text-slate-500";
              const arrow = pos ? "↑" : neg ? "↓" : "→";
              return (
                <div key={k} className="text-center" data-testid={`delta-${k}`}>
                  <div className="text-[10px] uppercase tracking-wider text-slate-400 mb-1 capitalize">{k}</div>
                  <div className={`text-base font-bold ${cls}`}>
                    {arrow} {Math.abs(d).toFixed(1)}
                  </div>
                </div>
              );
            })}
          </div>
        )}

        {/* Action progress */}
        <div className="mt-4 flex items-center justify-between text-[11px] text-slate-500">
          <span><strong className="text-slate-700">{data.completed_count}</strong> done · <strong className="text-slate-700">{data.pending_count}</strong> pending</span>
          {data.pending_count > 0 && data.completed_count >= 0 && (
            <div className="flex-1 mx-4 max-w-xs">
              <div className="w-full h-1.5 rounded-full bg-slate-100 overflow-hidden">
                <div
                  className={`h-full rounded-full ${t.bar} transition-all`}
                  style={{ width: `${(data.completed_count / (data.completed_count + data.pending_count)) * 100}%` }}
                />
              </div>
            </div>
          )}
        </div>
      </Card>
    </motion.div>
  );
};

export default HealthProjectionCard;
