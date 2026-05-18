/**
 * V2ScenarioSimScreen — What-if simulator.
 *
 * Data:
 *   GET  /api/scenarios/suggest   → 3-5 AI-picked scenarios
 *   POST /api/scenarios/simulate  → before/after metrics
 *
 * UX: user picks a suggested scenario OR drags allocation sliders;
 * clicks Run → backend returns before/after CAGR, risk, 5y projection.
 */
import React, { useEffect, useState } from "react";
import axios from "axios";
import {
  Beaker, Play, ArrowRight, TrendingUp, Shield, Wallet,
} from "lucide-react";
import { cn } from "@/lib/utils";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

const fmtRs = (n) => {
  if (n == null) return "—";
  if (Math.abs(n) >= 1e7) return `₹${(n / 1e7).toFixed(2)} Cr`;
  if (Math.abs(n) >= 1e5) return `₹${(n / 1e5).toFixed(1)} L`;
  return `₹${Math.round(n).toLocaleString("en-IN")}`;
};

export default function V2ScenarioSimScreen() {
  const [suggested, setSuggested] = useState([]);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState(null);
  const [result, setResult] = useState(null);
  const [running, setRunning] = useState(false);

  // Manual sliders
  const [targetEquity, setTargetEquity] = useState(70);
  const [targetDebt, setTargetDebt]     = useState(25);
  const [targetGold, setTargetGold]     = useState(5);
  const [switchDirect, setSwitchDirect] = useState(false);

  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const r = await axios.get(`${API}/scenarios/suggest`, { withCredentials: true });
        if (alive) setSuggested(r.data?.scenarios || []);
      } catch (_) { /* graceful */ }
      finally { if (alive) setLoading(false); }
    })();
    return () => { alive = false; };
  }, []);

  async function runSim(payload, suggestedScenario) {
    setRunning(true);
    setSelected(suggestedScenario || null);
    try {
      const r = await axios.post(`${API}/scenarios/simulate`, payload, { withCredentials: true });
      setResult(r.data);
    } catch (e) {
      setResult({ error: e.response?.data?.detail || "Simulation failed" });
    } finally {
      setRunning(false);
    }
  }

  return (
    <div className="space-y-6 animate-fadein">
      <div>
        <h2 className="text-2xl font-black text-white tracking-tight flex items-center gap-3">
          <Beaker className="w-6 h-6 text-violet-400" />
          Scenario Simulator
        </h2>
        <p className="text-sm text-white/40 mt-0.5">Try a what-if — see before/after risk, CAGR, and 5-year projection.</p>
      </div>

      {/* Suggested scenarios row */}
      <div className="bg-[#1A1A1A] border border-white/5 rounded-2xl p-5 shadow-xl">
        <h3 className="text-sm font-bold text-white mb-1">AI-Picked Scenarios</h3>
        <p className="text-[11px] text-white/40 mb-4">Personalized to your current portfolio.</p>
        {loading ? (
          <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
            {[1, 2, 3].map((i) => <div key={i} className="h-32 bg-white/5 rounded-xl animate-pulse" />)}
          </div>
        ) : suggested.length === 0 ? (
          <div className="py-4 text-center text-xs text-white/40">No scenarios available — upload holdings first.</div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
            {suggested.slice(0, 6).map((s) => (
              <button
                key={s.id}
                onClick={() => runSim({ scenario_id: s.id, ...(s.target_allocation || {}) }, s)}
                disabled={running}
                className={cn(
                  "text-left p-4 rounded-xl border transition-all group disabled:opacity-50",
                  selected?.id === s.id
                    ? "bg-violet-500/10 border-violet-500/40"
                    : "bg-white/[0.02] border-white/5 hover:bg-violet-500/5 hover:border-violet-500/20",
                )}
              >
                <p className="text-xs font-bold text-white">{s.title}</p>
                <p className="text-[10px] text-white/40 mt-1 line-clamp-2">{s.subtitle || s.reason}</p>
                <div className="mt-3 flex items-center justify-between">
                  <span className="text-[9px] font-bold text-white/30 uppercase tracking-widest">
                    {s.current_value} → {s.target_value}
                  </span>
                  <Play className="w-3 h-3 text-violet-400 group-hover:translate-x-0.5 transition-transform" />
                </div>
              </button>
            ))}
          </div>
        )}
      </div>

      {/* Manual sliders */}
      <div className="bg-[#1A1A1A] border border-white/5 rounded-2xl p-5 shadow-xl">
        <h3 className="text-sm font-bold text-white mb-1">Custom Allocation</h3>
        <p className="text-[11px] text-white/40 mb-4">Drag the sliders to define a target mix.</p>

        <div className="space-y-4">
          <Slider label="Equity"   value={targetEquity} onChange={setTargetEquity} color="indigo"  />
          <Slider label="Debt"     value={targetDebt}   onChange={setTargetDebt}   color="emerald" />
          <Slider label="Gold"     value={targetGold}   onChange={setTargetGold}   color="amber"   />

          <label className="flex items-center gap-2.5 cursor-pointer pt-2">
            <input
              type="checkbox"
              checked={switchDirect}
              onChange={(e) => setSwitchDirect(e.target.checked)}
              className="w-4 h-4 accent-violet-500"
            />
            <span className="text-xs text-white/70">Switch Regular plans → Direct (saves expense)</span>
          </label>
        </div>

        <button
          onClick={() => runSim({
            target_equity: targetEquity,
            target_debt: targetDebt,
            target_gold: targetGold,
            switch_to_direct: switchDirect,
          })}
          disabled={running}
          className="mt-5 px-5 py-2.5 bg-violet-500 hover:bg-violet-400 text-white font-bold text-xs rounded-xl uppercase tracking-widest disabled:opacity-50 transition-all flex items-center gap-2"
        >
          <Play className="w-3.5 h-3.5" /> {running ? "Running…" : "Run Simulation"}
        </button>
      </div>

      {/* Result */}
      {result && !result.error && (
        <div className="bg-[#1A1A1A] border border-violet-500/20 rounded-2xl p-5 shadow-xl animate-fadein">
          <h3 className="text-sm font-bold text-white mb-4 flex items-center gap-2">
            <Beaker className="w-4 h-4 text-violet-400" /> Before / After
          </h3>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <DeltaCard
              icon={TrendingUp}
              label="Expected CAGR"
              before={`${result.before?.expected_cagr?.toFixed(1) ?? "—"}%`}
              after={`${result.after?.expected_cagr?.toFixed(1) ?? "—"}%`}
              delta={`${result.delta?.cagr > 0 ? "+" : ""}${result.delta?.cagr?.toFixed(2)}%`}
              positive={result.delta?.cagr > 0}
            />
            <DeltaCard
              icon={Shield}
              label="Risk Score"
              before={`${result.before?.risk_score ?? "—"}`}
              after={`${result.after?.risk_score ?? "—"}`}
              delta={`${result.delta?.risk > 0 ? "+" : ""}${result.delta?.risk}`}
              positive={result.delta?.risk < 0}
            />
            <DeltaCard
              icon={Wallet}
              label="5-Yr Projection"
              before={fmtRs(result.before?.projected_5y)}
              after={fmtRs(result.after?.projected_5y)}
              delta={`${result.delta?.value_5y > 0 ? "+" : ""}${fmtRs(result.delta?.value_5y)}`}
              positive={result.delta?.value_5y > 0}
            />
          </div>

          {result.top_changes?.length > 0 && (
            <div className="mt-5 pt-5 border-t border-white/5">
              <p className="text-[10px] font-bold text-white/40 uppercase tracking-widest mb-3">Top Changes</p>
              <div className="space-y-1.5">
                {result.top_changes.slice(0, 4).map((c, i) => (
                  <div key={i} className="flex items-center gap-2 text-xs text-white/70">
                    <ArrowRight className="w-3 h-3 text-violet-400 shrink-0" />
                    <span>{typeof c === "string" ? c : c.label || c.description || c.title}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      {result?.error && (
        <div className="p-4 bg-rose-500/10 border border-rose-500/20 rounded-xl text-xs text-rose-300">
          {result.error}
        </div>
      )}
    </div>
  );
}

function Slider({ label, value, onChange, color }) {
  const COL = {
    indigo:  "accent-indigo-500 text-indigo-400",
    emerald: "accent-emerald-500 text-emerald-400",
    amber:   "accent-amber-500 text-amber-400",
  }[color] || "accent-indigo-500 text-indigo-400";
  const text = COL.split(" ")[1];
  return (
    <div>
      <div className="flex items-center justify-between mb-2">
        <span className="text-xs font-bold text-white/70">{label}</span>
        <span className={cn("text-sm font-black", text)}>{value}%</span>
      </div>
      <input
        type="range"
        min={0} max={100} step={1}
        value={value}
        onChange={(e) => onChange(parseInt(e.target.value, 10))}
        className={cn("w-full h-2 bg-white/5 rounded-lg appearance-none cursor-pointer", COL.split(" ")[0])}
      />
    </div>
  );
}

function DeltaCard({ icon: Icon, label, before, after, delta, positive }) {
  return (
    <div className="bg-white/[0.02] border border-white/5 rounded-xl p-4">
      <div className="flex items-center gap-2 mb-3">
        <Icon className="w-3.5 h-3.5 text-violet-400" />
        <p className="text-[9px] font-bold text-white/30 uppercase tracking-[0.2em] font-mono">{label}</p>
      </div>
      <div className="flex items-baseline gap-3">
        <span className="text-sm font-bold text-white/40 line-through">{before}</span>
        <ArrowRight className="w-3 h-3 text-white/30" />
        <span className="text-xl font-black text-white">{after}</span>
      </div>
      <p className={cn(
        "text-[10px] font-bold mt-2 uppercase tracking-widest",
        positive ? "text-emerald-400" : "text-rose-400",
      )}>
        {delta}
      </p>
    </div>
  );
}
