/**
 * V2RiskCenterScreen — Risk profile + drawdown + stress test.
 *
 * Data: analytics (passed from parent — already loaded)
 *   → risk_score, risk_label, risk_analysis, health_score, risk_drivers
 *
 * Also pulls /api/insights/v3-portfolio for top-3 risk drivers.
 */
import React, { useEffect, useState } from "react";
import axios from "axios";
import {
  Shield, AlertTriangle, TrendingDown, Activity, ArrowRight, Sparkles, Gauge,
} from "lucide-react";
import { cn } from "@/lib/utils";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

export default function V2RiskCenterScreen({ analytics, setScreen }) {
  const [drivers, setDrivers] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const r = await axios.get(`${API}/insights/v3-portfolio`, { withCredentials: true });
        if (alive) setDrivers(r.data?.risk_drivers || []);
      } catch (_) { /* graceful */ }
      finally { if (alive) setLoading(false); }
    })();
    return () => { alive = false; };
  }, []);

  const riskScore = analytics?.risk_score ?? 0;
  const riskLabel = analytics?.risk_label ?? "—";
  const riskAnalysis = analytics?.risk_analysis || {};
  const hs = analytics?.health_score || {};

  const band = riskScore >= 60 ? { label: "High Risk",     color: "rose"   }
             : riskScore >= 30 ? { label: "Moderate Risk", color: "amber"  }
                                : { label: "Conservative",  color: "emerald"};

  const askCopilot = (q) => {
    sessionStorage.setItem("v2_pending_chat_message", q);
    setScreen?.("copilot");
  };

  return (
    <div className="space-y-6 animate-fadein">
      <div>
        <h2 className="text-2xl font-black text-white tracking-tight flex items-center gap-3">
          <Shield className="w-6 h-6 text-amber-400" />
          Risk Center
        </h2>
        <p className="text-sm text-white/40 mt-0.5">Concentration, volatility, and stress-test outlook.</p>
      </div>

      {/* Gauge hero */}
      <div className={cn(
        "relative bg-[#1A1A1A] border rounded-2xl p-6 shadow-xl overflow-hidden",
        band.color === "rose"   && "border-rose-500/30",
        band.color === "amber"  && "border-amber-500/30",
        band.color === "emerald"&& "border-emerald-500/30",
      )}>
        <div className="absolute top-0 right-0 w-64 h-64 rounded-full blur-3xl -mr-32 -mt-32 opacity-30 bg-gradient-to-br from-current to-transparent" />
        <div className="relative z-10 flex items-center justify-between gap-6 flex-wrap">
          <div>
            <p className="text-[9px] font-bold text-white/30 uppercase tracking-[0.2em] mb-2 font-mono">Risk Score</p>
            <div className="flex items-baseline gap-3">
              <span className={cn(
                "text-6xl font-black tracking-tighter",
                band.color === "rose"   && "text-rose-400",
                band.color === "amber"  && "text-amber-400",
                band.color === "emerald"&& "text-emerald-400",
              )}>{Math.round(riskScore)}</span>
              <span className="text-xl text-white/30 font-bold">/ 100</span>
            </div>
            <p className={cn(
              "text-xs font-bold mt-2 uppercase tracking-widest",
              band.color === "rose"   && "text-rose-400",
              band.color === "amber"  && "text-amber-400",
              band.color === "emerald"&& "text-emerald-400",
            )}>{band.label} · {riskLabel}</p>
          </div>
          <button
            onClick={() => askCopilot("Run a stress test on my portfolio for a 2008-style crash, a rate-shock, and an inflation spike. What's the expected drawdown?")}
            className="px-4 py-2 text-[10px] font-bold text-white bg-white/5 hover:bg-white/10 rounded-xl border border-white/10 uppercase tracking-widest flex items-center gap-2 transition-all"
          >
            <AlertTriangle className="w-3.5 h-3.5" /> Stress Test
          </button>
        </div>
      </div>

      {/* 3 risk dimensions */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <Dimension
          icon={Gauge}
          label="Diversification"
          value={hs.diversification}
          inverse
          hint={hs.diversification < 50 ? "Concentrated — add breadth across sectors/AMCs" : "Adequately spread"}
        />
        <Dimension
          icon={Activity}
          label="Volatility (proxy)"
          value={riskScore}
          hint={riskScore >= 60 ? "Equity-heavy book swings with markets" : "Moderate volatility"}
        />
        <Dimension
          icon={TrendingDown}
          label="Drawdown sensitivity"
          value={hs.risk}
          inverse
          hint={hs.risk < 50 ? "Vulnerable to deep drawdowns" : "Risk well-managed"}
        />
      </div>

      {/* Risk drivers (real) */}
      <div className="bg-[#1A1A1A] border border-white/5 rounded-2xl p-5 shadow-xl">
        <h3 className="text-sm font-bold text-white mb-1">Top Risk Drivers</h3>
        <p className="text-[11px] text-white/40 mb-4">What's pushing your risk score up.</p>

        {loading ? (
          <div className="space-y-2">
            {[1, 2, 3].map((i) => <div key={i} className="h-12 bg-white/5 rounded-xl animate-pulse" />)}
          </div>
        ) : drivers.length === 0 ? (
          <div className="py-4 text-center text-xs text-white/40">
            {riskAnalysis?.warnings?.length
              ? riskAnalysis.warnings.slice(0, 3).map((w, i) => (
                  <p key={i} className="mb-1">{w}</p>
                ))
              : "No standout risk drivers — your portfolio is balanced."}
          </div>
        ) : (
          <div className="space-y-2">
            {drivers.slice(0, 5).map((d, i) => (
              <div key={i} className="flex items-start gap-3 p-3 rounded-xl bg-white/[0.02] border border-white/5 hover:bg-white/5 transition-all">
                <div className="w-7 h-7 rounded-lg bg-rose-500/10 border border-rose-500/15 flex items-center justify-center shrink-0">
                  <AlertTriangle className="w-3.5 h-3.5 text-rose-400" />
                </div>
                <div className="flex-1 min-w-0">
                  <p className="text-xs font-bold text-white">{d.driver || d.title || `Driver ${i + 1}`}</p>
                  <p className="text-[11px] text-white/50">{d.impact || d.description || ""}</p>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Stress scenarios CTA */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
        {[
          { title: "2008 Crash",         q: "What happens to my portfolio in a 2008-style 55% equity crash? Project the drawdown by holding." },
          { title: "Rate Shock",         q: "If RBI hikes rates 200bps in 6 months, how does my debt + equity book react? Quantify the hit." },
          { title: "Inflation Spike",    q: "Run a scenario where CPI spikes to 8% for 18 months. Which of my holdings get hurt most?" },
        ].map((s) => (
          <button
            key={s.title}
            onClick={() => askCopilot(s.q)}
            className="text-left bg-[#1A1A1A] border border-rose-500/15 rounded-2xl p-4 hover:border-rose-500/30 transition-all group"
          >
            <Sparkles className="w-4 h-4 text-rose-400 mb-2" />
            <p className="text-xs font-bold text-white">{s.title}</p>
            <p className="text-[10px] text-white/40 mt-1 line-clamp-2">{s.q}</p>
            <div className="mt-2 text-[9px] font-bold text-rose-400 uppercase tracking-widest flex items-center gap-1.5">
              Run <ArrowRight className="w-3 h-3 group-hover:translate-x-0.5 transition-transform" />
            </div>
          </button>
        ))}
      </div>
    </div>
  );
}

function Dimension({ icon: Icon, label, value, hint, inverse }) {
  const v = value ?? 0;
  // For dimension scores: 100 is best, 0 is worst, unless inverse=false (raw risk where higher = worse)
  const displayScore = inverse ? v : 100 - v;
  const tone = displayScore >= 70 ? "emerald" : displayScore >= 40 ? "amber" : "rose";
  const cTone = { emerald: "text-emerald-400 bg-emerald-500", amber: "text-amber-400 bg-amber-500", rose: "text-rose-400 bg-rose-500" }[tone];
  const text = cTone.split(" ")[0];
  const bar  = cTone.split(" ")[1];
  return (
    <div className="bg-[#1A1A1A] border border-white/5 rounded-2xl p-4 shadow-xl">
      <div className="flex items-center gap-2 mb-2">
        <Icon className={cn("w-3.5 h-3.5", text)} />
        <p className="text-[9px] font-bold text-white/30 uppercase tracking-[0.2em] font-mono">{label}</p>
      </div>
      <div className="flex items-baseline gap-2 mb-2">
        <span className={cn("text-2xl font-black", text)}>{Math.round(v)}</span>
        <span className="text-[10px] font-bold text-white/30">/100</span>
      </div>
      <div className="w-full h-1 bg-white/5 rounded-full overflow-hidden mb-2">
        <div className={cn("h-full transition-all", bar)} style={{ width: `${Math.min(v, 100)}%` }} />
      </div>
      <p className="text-[10px] text-white/40 leading-relaxed">{hint}</p>
    </div>
  );
}
