/**
 * V2BenchmarkScreen — Compare portfolio XIRR vs market indices.
 *
 * Data:
 *   GET /api/index/latest?name=NIFTY_50
 *   GET /api/index/history?name=NIFTY_50&period=1Y
 *   analytics.xirr (already loaded by parent)
 */
import React, { useEffect, useState } from "react";
import axios from "axios";
import {
  LineChart as LineChartIcon, TrendingUp, TrendingDown, Trophy, Target,
} from "lucide-react";
import { cn } from "@/lib/utils";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

const INDICES = [
  { name: "NIFTY_50",     label: "Nifty 50",      color: "indigo"  },
  { name: "NIFTY_500",    label: "Nifty 500",     color: "violet"  },
  { name: "SENSEX",       label: "Sensex",        color: "blue"    },
  { name: "NIFTY_MIDCAP_100", label: "Midcap 100",color: "amber"   },
];

export default function V2BenchmarkScreen({ analytics }) {
  const portfolioXirr = analytics?.xirr ?? null;
  const [indexData, setIndexData] = useState({});
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let alive = true;
    (async () => {
      const out = {};
      await Promise.all(
        INDICES.map(async (idx) => {
          try {
            const r = await axios.get(`${API}/index/latest`, {
              params: { name: idx.name },
              withCredentials: true,
            });
            out[idx.name] = r.data;
          } catch (_) {
            out[idx.name] = null;
          }
        }),
      );
      if (alive) {
        setIndexData(out);
        setLoading(false);
      }
    })();
    return () => { alive = false; };
  }, []);

  // Score: portfolio XIRR vs each index 1Y return
  const rows = INDICES.map((idx) => {
    const d = indexData[idx.name];
    const benchReturn = d?.returns_1y ?? d?.return_1y ?? d?.ytd_return ?? null;
    const delta = (portfolioXirr != null && benchReturn != null)
      ? portfolioXirr - benchReturn
      : null;
    return { ...idx, benchReturn, delta };
  });

  const winsCount = rows.filter((r) => r.delta != null && r.delta > 0).length;

  return (
    <div className="space-y-6 animate-fadein">
      <div>
        <h2 className="text-2xl font-black text-white tracking-tight flex items-center gap-3">
          <LineChartIcon className="w-6 h-6 text-blue-400" />
          Benchmark Performance
        </h2>
        <p className="text-sm text-white/40 mt-0.5">How your portfolio stacks up against the market.</p>
      </div>

      {/* Hero — portfolio XIRR */}
      <div className="bg-[#1A1A1A] border border-blue-500/20 rounded-2xl p-6 shadow-xl">
        <div className="flex items-baseline justify-between flex-wrap gap-3">
          <div>
            <p className="text-[9px] font-bold text-white/30 uppercase tracking-[0.2em] mb-2 font-mono">Your Portfolio XIRR</p>
            <div className="flex items-baseline gap-3">
              <span className={cn(
                "text-5xl font-black tracking-tighter",
                portfolioXirr > 0 ? "text-emerald-400" : portfolioXirr < 0 ? "text-rose-400" : "text-white/40",
              )}>
                {portfolioXirr != null ? `${portfolioXirr > 0 ? "+" : ""}${portfolioXirr.toFixed(1)}` : "—"}
              </span>
              <span className="text-xl text-white/30 font-bold">%</span>
            </div>
          </div>

          {!loading && portfolioXirr != null && (
            <div className="text-right">
              <p className="text-[9px] font-bold text-white/30 uppercase tracking-[0.2em] mb-2 font-mono">vs Indices</p>
              <div className="flex items-center gap-2 justify-end">
                <Trophy className={cn("w-5 h-5", winsCount >= 2 ? "text-amber-400" : "text-white/30")} />
                <span className="text-2xl font-black text-white">{winsCount}<span className="text-sm text-white/40">/{rows.length}</span></span>
              </div>
              <p className="text-[10px] text-white/40 mt-1">Beating</p>
            </div>
          )}
        </div>
      </div>

      {/* Per-index rows */}
      <div className="bg-[#1A1A1A] border border-white/5 rounded-2xl p-5 shadow-xl">
        <h3 className="text-sm font-bold text-white mb-1">Index Comparison · 1Y</h3>
        <p className="text-[11px] text-white/40 mb-4">Your XIRR vs trailing 1-year return.</p>

        {loading ? (
          <div className="space-y-3">
            {[1, 2, 3, 4].map((i) => <div key={i} className="h-14 bg-white/5 rounded-xl animate-pulse" />)}
          </div>
        ) : (
          <div className="space-y-2.5">
            {rows.map((r) => {
              const beat = r.delta != null && r.delta > 0;
              const lose = r.delta != null && r.delta < 0;
              return (
                <div
                  key={r.name}
                  className={cn(
                    "p-4 rounded-xl border flex items-center justify-between gap-4",
                    beat && "bg-emerald-500/5 border-emerald-500/15",
                    lose && "bg-rose-500/5 border-rose-500/15",
                    !beat && !lose && "bg-white/[0.02] border-white/5",
                  )}
                >
                  <div className="flex items-center gap-3 min-w-0">
                    <div className={cn(
                      "w-10 h-10 rounded-xl flex items-center justify-center shrink-0 border",
                      beat ? "bg-emerald-500/15 border-emerald-500/20 text-emerald-400"
                           : lose ? "bg-rose-500/15 border-rose-500/20 text-rose-400"
                                  : "bg-white/5 border-white/10 text-white/40",
                    )}>
                      {beat ? <TrendingUp className="w-4 h-4" />
                            : lose ? <TrendingDown className="w-4 h-4" />
                                   : <Target className="w-4 h-4" />}
                    </div>
                    <div className="min-w-0">
                      <p className="text-sm font-bold text-white">{r.label}</p>
                      <p className="text-[10px] text-white/40">
                        Index 1Y: {r.benchReturn != null ? `${r.benchReturn > 0 ? "+" : ""}${r.benchReturn.toFixed(1)}%` : "n/a"}
                      </p>
                    </div>
                  </div>

                  <div className="text-right shrink-0">
                    <p className={cn(
                      "text-base font-black",
                      beat ? "text-emerald-400" : lose ? "text-rose-400" : "text-white/40",
                    )}>
                      {r.delta != null ? `${r.delta > 0 ? "+" : ""}${r.delta.toFixed(1)}%` : "—"}
                    </p>
                    <p className="text-[9px] text-white/30 uppercase tracking-widest">
                      {beat ? "Outperform" : lose ? "Underperform" : "Match"}
                    </p>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>

      {/* Interpretation */}
      <div className="bg-[#1A1A1A] border border-white/5 rounded-2xl p-5 shadow-xl">
        <p className="text-[10px] font-bold text-white/40 uppercase tracking-widest mb-2">Interpretation</p>
        <p className="text-sm text-white/70 leading-relaxed">
          {portfolioXirr == null
            ? "Upload more transaction history to compute your XIRR and unlock benchmark comparison."
            : winsCount >= 3
              ? `Your portfolio is meaningfully outperforming ${winsCount} of ${rows.length} major indices — disciplined fund selection is showing up in the numbers.`
              : winsCount >= 2
                ? `You're holding your own against the market — beating ${winsCount} of ${rows.length} indices. Consider where the underperformance came from.`
                : `Your portfolio is trailing most indices. This is a signal to re-check fund quality, expense ratios, and whether direct-plan switches are overdue.`}
        </p>
      </div>
    </div>
  );
}
