import React, { useState } from "react";
import axios from "axios";
import { toast } from "sonner";
import { Slider } from "@/components/ui/slider";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { TrendingUp, TrendingDown, AlertTriangle, CheckCircle2, Zap, RefreshCw } from "lucide-react";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

const fmtRs = (n) => {
  if (n == null) return "—";
  const abs = Math.abs(n);
  if (abs >= 1e7) return `₹${(n / 1e7).toFixed(2)} Cr`;
  if (abs >= 1e5) return `₹${(n / 1e5).toFixed(2)} L`;
  return `₹${Math.round(n).toLocaleString("en-IN")}`;
};

const SCENARIO_META = {
  base:   { label: "Base case", tone: "bg-blue-500", icon: TrendingUp },
  bull:   { label: "Bull case", tone: "bg-emerald-500", icon: TrendingUp },
  bear:   { label: "Bear case", tone: "bg-rose-500", icon: TrendingDown },
  stress: { label: "Stress",    tone: "bg-slate-700", icon: AlertTriangle },
};

const successTone = (pct) => {
  if (pct >= 85) return "text-emerald-600";
  if (pct >= 60) return "text-amber-600";
  return "text-rose-600";
};

export default function ScenarioSimulator({ goal, initialSimulation, onRefresh }) {
  const [sim, setSim] = useState(initialSimulation || {});
  const [whatIf, setWhatIf] = useState({
    monthly_sip_rs: goal.monthly_sip_rs || 0,
    horizon_years: goal.horizon_years || 0,
  });
  const [previewing, setPreviewing] = useState(false);
  const [preview, setPreview] = useState(null);

  const runWhatIf = async () => {
    setPreviewing(true);
    try {
      const res = await axios.post(`${API}/goals/${goal.goal_id}/what-if`, {
        monthly_sip_rs: Number(whatIf.monthly_sip_rs),
        horizon_years: Number(whatIf.horizon_years),
      }, { withCredentials: true });
      setPreview(res.data);
    } catch (e) {
      toast.error(e.response?.data?.detail || "What-if failed");
    } finally {
      setPreviewing(false);
    }
  };

  const commitWhatIf = async () => {
    try {
      await axios.patch(`${API}/goals/${goal.goal_id}`, {
        monthly_sip_rs: Number(whatIf.monthly_sip_rs),
        horizon_years: Number(whatIf.horizon_years),
      }, { withCredentials: true });
      await axios.post(`${API}/goals/${goal.goal_id}/simulate`, {}, { withCredentials: true });
      toast.success("Goal updated and simulated");
      onRefresh?.();
    } catch (e) {
      toast.error(e.response?.data?.detail || "Failed to apply");
    }
  };

  const scenarios = sim.scenarios || {};
  const mc = sim.monte_carlo || {};
  const actions = sim.actions || [];
  const selected = goal.selected_funds || {};

  return (
    <div className="space-y-5" data-testid="scenario-simulator">
      {/* Top summary */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <SummaryTile label="Target (FV)" value={fmtRs(sim.future_target_rs || goal.target_amount_rs)} sub="Inflation-adjusted" />
        <SummaryTile label="Required SIP" value={fmtRs(sim.required_sip_rs)} sub="To hit target" />
        <SummaryTile label="On track" value={`${(goal.on_track_pct ?? 0).toFixed(0)}%`} sub="Expected returns" tone={successTone(goal.on_track_pct)} />
        <SummaryTile label="MC success" value={`${mc.prob_success_pct ?? "—"}%`} sub={`Over ${mc.n_runs ?? 0} sims`} tone={successTone(mc.prob_success_pct)} />
      </div>

      {/* Scenarios table */}
      <div className="rounded-xl border border-slate-200 dark:border-slate-700 overflow-hidden">
        <div className="bg-slate-50 dark:bg-slate-800 px-4 py-2 text-xs font-semibold uppercase tracking-wider">
          Scenario matrix
        </div>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-0 divide-x divide-slate-200 dark:divide-slate-700" data-testid="scenario-grid">
          {Object.entries(scenarios).map(([k, v]) => {
            const m = SCENARIO_META[k] || SCENARIO_META.base;
            const Icon = m.icon;
            return (
              <div key={k} className="p-4" data-testid={`scenario-${k}`}>
                <div className="flex items-center gap-2 mb-2">
                  <div className={`w-6 h-6 ${m.tone} rounded-md flex items-center justify-center`}>
                    <Icon className="w-3 h-3 text-white" />
                  </div>
                  <div className="text-xs font-semibold">{m.label}</div>
                </div>
                <div className="text-lg font-bold text-slate-800 dark:text-slate-100">{fmtRs(v.corpus_rs)}</div>
                <div className="text-[10px] text-slate-500 mt-0.5">@ {v.return_pct}% return</div>
                <div className={`text-xs font-semibold mt-1 ${successTone(v.success_pct)}`}>
                  {v.success_pct.toFixed(0)}% of target
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* Monte Carlo */}
      {mc.prob_success_pct != null && (
        <div className="rounded-xl border border-slate-200 dark:border-slate-700 p-4">
          <div className="flex items-center justify-between mb-2">
            <div className="text-xs font-semibold uppercase tracking-wider">Monte-Carlo distribution</div>
            <Badge variant="outline" className="text-[10px]">{mc.n_runs} runs</Badge>
          </div>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-xs">
            <Stat label="Best-case (p95)" value={fmtRs(mc.p95_corpus_rs)} tone="text-emerald-600" />
            <Stat label="Median (p50)" value={fmtRs(mc.median_corpus_rs)} />
            <Stat label="Worst-case (p5)" value={fmtRs(mc.p5_corpus_rs)} tone="text-rose-600" />
            <Stat label="Expected shortfall" value={`${mc.expected_shortfall_pct}%`} tone="text-amber-600" />
          </div>
        </div>
      )}

      {/* Actions */}
      {actions.length > 0 && (
        <div className="rounded-xl border border-slate-200 dark:border-slate-700 bg-amber-50 dark:bg-amber-900/20 p-4 space-y-2"
             data-testid="goal-actions">
          <div className="text-xs font-semibold uppercase tracking-wider flex items-center gap-1.5 text-amber-900 dark:text-amber-200">
            <Zap className="w-3 h-3" /> Recommended actions
          </div>
          {actions.map((a, i) => (
            <div key={i} className="bg-white dark:bg-slate-900 rounded-md px-3 py-2 text-xs border border-amber-200 dark:border-amber-800">
              <div className="font-semibold text-slate-800 dark:text-slate-100">{a.title}</div>
              <div className="text-slate-600 dark:text-slate-400 mt-0.5">{a.detail}</div>
            </div>
          ))}
        </div>
      )}

      {/* Allocation & funds */}
      <div className="rounded-xl border border-slate-200 dark:border-slate-700 p-4">
        <div className="text-xs font-semibold uppercase tracking-wider mb-2">Allocation & auto-picked funds</div>
        <div className="grid grid-cols-3 gap-3 mb-3 text-xs">
          {Object.entries(goal.allocation || {}).map(([b, pct]) => (
            <div key={b} className="rounded bg-slate-50 dark:bg-slate-800/60 px-3 py-2">
              <div className="uppercase text-[9px] text-slate-500 tracking-wider">{b}</div>
              <div className="font-bold text-slate-800 dark:text-slate-100">{pct}%</div>
            </div>
          ))}
        </div>
        <div className="space-y-1.5" data-testid="selected-funds">
          {Object.entries(selected).map(([bucket, funds]) =>
            funds.map(f => (
              <div key={f.instrument_id} className="flex items-center justify-between text-xs border-b border-slate-100 dark:border-slate-800 pb-1.5 last:border-0">
                <div className="flex items-center gap-2 min-w-0">
                  <Badge variant="outline" className="text-[9px] uppercase">{bucket}</Badge>
                  <span className="truncate">{f.scheme_name}</span>
                </div>
                <div className="flex items-center gap-2 tabular-nums text-slate-500 text-[11px] shrink-0">
                  <span>Q={f.quality_score}</span>
                  <span>exp={f.expense_ratio}%</span>
                  <span>{f.weight_pct}%</span>
                </div>
              </div>
            ))
          )}
          {Object.keys(selected).length === 0 && (
            <div className="text-xs text-slate-500">Funds not yet selected — run Simulate.</div>
          )}
        </div>
      </div>

      {/* What-if */}
      <div className="rounded-xl border-2 border-dashed border-emerald-300 dark:border-emerald-800 bg-emerald-50/40 dark:bg-emerald-900/10 p-4" data-testid="what-if-panel">
        <div className="text-xs font-semibold uppercase tracking-wider mb-3 flex items-center gap-1.5 text-emerald-700 dark:text-emerald-300">
          <RefreshCw className="w-3 h-3" /> What-if simulator
        </div>
        <div className="grid grid-cols-2 gap-3 mb-3">
          <div>
            <Label className="text-xs flex justify-between">
              <span>SIP (₹/month)</span>
              <span className="tabular-nums text-slate-600">{Number(whatIf.monthly_sip_rs).toLocaleString("en-IN")}</span>
            </Label>
            <Slider
              min={0} max={200000} step={1000}
              value={[Number(whatIf.monthly_sip_rs)]}
              onValueChange={(v) => setWhatIf(w => ({ ...w, monthly_sip_rs: v[0] }))}
              className="mt-2"
              data-testid="whatif-sip-slider"
            />
          </div>
          <div>
            <Label className="text-xs flex justify-between">
              <span>Horizon (years)</span>
              <span className="tabular-nums text-slate-600">{whatIf.horizon_years}y</span>
            </Label>
            <Slider
              min={1} max={40} step={1}
              value={[Number(whatIf.horizon_years)]}
              onValueChange={(v) => setWhatIf(w => ({ ...w, horizon_years: v[0] }))}
              className="mt-2"
              data-testid="whatif-horizon-slider"
            />
          </div>
        </div>
        <div className="flex items-center gap-2">
          <Button size="sm" variant="outline" onClick={runWhatIf} disabled={previewing} data-testid="whatif-preview-btn">
            {previewing ? "Simulating…" : "Preview"}
          </Button>
          <Button size="sm" onClick={commitWhatIf} className="bg-emerald-600 hover:bg-emerald-700" data-testid="whatif-apply-btn">
            Apply & save
          </Button>
        </div>

        {preview && (
          <div className="mt-3 grid grid-cols-2 md:grid-cols-4 gap-2 text-xs" data-testid="whatif-result">
            <Stat label="Projected corpus" value={fmtRs(preview.projected_corpus_rs)} />
            <Stat label="Required SIP" value={fmtRs(preview.required_sip_rs)} />
            <Stat label="On-track" value={`${preview.on_track_pct?.toFixed(0)}%`} tone={successTone(preview.on_track_pct)} />
            <Stat label="MC prob" value={`${preview.monte_carlo?.prob_success_pct}%`} tone={successTone(preview.monte_carlo?.prob_success_pct)} />
          </div>
        )}
      </div>
    </div>
  );
}

const SummaryTile = ({ label, value, sub, tone = "text-slate-800 dark:text-slate-100" }) => (
  <div className="rounded-xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 p-3">
    <div className="text-[9px] uppercase tracking-wider text-slate-500 mb-0.5">{label}</div>
    <div className={`text-xl font-bold tabular-nums ${tone}`}>{value}</div>
    <div className="text-[10px] text-slate-500 mt-0.5">{sub}</div>
  </div>
);

const Stat = ({ label, value, tone = "text-slate-800 dark:text-slate-100" }) => (
  <div className="rounded bg-slate-50 dark:bg-slate-800/60 px-3 py-2">
    <div className="uppercase text-[9px] tracking-wider text-slate-500">{label}</div>
    <div className={`font-bold text-sm tabular-nums ${tone}`}>{value}</div>
  </div>
);
