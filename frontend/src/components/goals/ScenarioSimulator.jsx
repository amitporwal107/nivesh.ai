import React, { useState, useMemo } from "react";
import axios from "axios";
import { toast } from "sonner";
import { Slider } from "@/components/ui/slider";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import {
  TrendingUp, TrendingDown, AlertTriangle, CheckCircle2, Zap,
  RefreshCw, ArrowRight, ArrowUpRight, Clock, Flame, Target,
} from "lucide-react";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

/**
 * ScenarioSimulator — Goal Decision Engine
 *
 * Product philosophy (per user critique):
 *   1. Lead with a verdict ("You are OFF TRACK"), not raw numbers.
 *   2. Always show a delta: current → required → gap.
 *   3. Explain WHY the plan is behind, not just that it is.
 *   4. Offer 3 concrete recovery paths with projected success %.
 *   5. Colour every number by severity (red/amber/green) for instant read.
 *
 * Sections (top to bottom):
 *   A. Verdict banner        — health badge + one-line summary
 *   B. Headline metric row   — Target, SIP delta, Return delta, Success prob
 *   C. Why you're behind     — rule-based reasons from goal_engine.build_why_behind
 *   D. Recovery paths        — 3 "do this" cards with projected outcomes
 *   E. Scenario matrix       — base/bull/bear/stress (kept from v1)
 *   F. Monte-Carlo band      — p5/p50/p95 + expected shortfall
 *   G. Allocation + funds
 *   H. What-if sliders
 */

// ── helpers ─────────────────────────────────────────────────────────────
const fmtRs = (n) => {
  if (n == null || isNaN(n)) return "—";
  const abs = Math.abs(n);
  if (abs >= 1e7) return `₹${(n / 1e7).toFixed(2)} Cr`;
  if (abs >= 1e5) return `₹${(n / 1e5).toFixed(2)} L`;
  return `₹${Math.round(n).toLocaleString("en-IN")}`;
};

const fmtPctTone = (pct) => {
  if (pct == null) return { label: "—", tone: "text-slate-500" };
  if (pct < 5)  return { label: `${pct.toFixed(0)}% · Very Low`,  tone: "text-rose-700" };
  if (pct < 40) return { label: `${pct.toFixed(0)}% · Low`,       tone: "text-rose-600" };
  if (pct < 70) return { label: `${pct.toFixed(0)}% · Moderate`,  tone: "text-amber-600" };
  if (pct < 95) return { label: `${pct.toFixed(0)}% · Strong`,    tone: "text-emerald-600" };
  return { label: `${pct.toFixed(0)}% · Very High`, tone: "text-emerald-700" };
};

const HEALTH_META = {
  critical: {
    label: "CRITICAL",
    tone: "bg-rose-50 border-rose-300 text-rose-800",
    icon: AlertTriangle,
    verdict: "You are OFF TRACK",
    accent: "border-rose-400 ring-1 ring-rose-200",
  },
  at_risk: {
    label: "AT RISK",
    tone: "bg-amber-50 border-amber-300 text-amber-800",
    icon: AlertTriangle,
    verdict: "Your plan is at risk",
    accent: "border-amber-400 ring-1 ring-amber-200",
  },
  on_track: {
    label: "ON TRACK",
    tone: "bg-emerald-50 border-emerald-300 text-emerald-800",
    icon: CheckCircle2,
    verdict: "You're on track",
    accent: "border-emerald-400 ring-1 ring-emerald-200",
  },
  ahead: {
    label: "AHEAD",
    tone: "bg-indigo-50 border-indigo-300 text-indigo-800",
    icon: TrendingUp,
    verdict: "You're ahead of the plan",
    accent: "border-indigo-400 ring-1 ring-indigo-200",
  },
};

const SCENARIO_META = {
  base:   { label: "Base case",   tone: "bg-blue-500",     icon: TrendingUp },
  bull:   { label: "Bull case",   tone: "bg-emerald-500",  icon: TrendingUp },
  bear:   { label: "Bear case",   tone: "bg-rose-500",     icon: TrendingDown },
  stress: { label: "Stress",      tone: "bg-slate-700",    icon: AlertTriangle },
};

const RECOVERY_META = {
  increase_sip:    { icon: ArrowUpRight, tone: "emerald", verb: "Increase SIP" },
  extend_horizon:  { icon: Clock,        tone: "blue",    verb: "Extend horizon" },
  increase_risk:   { icon: Flame,        tone: "orange",  verb: "Increase risk" },
};

// ── main ────────────────────────────────────────────────────────────────
export default function ScenarioSimulator({ goal, initialSimulation, onRefresh }) {
  const [sim, setSim] = useState(initialSimulation || {});
  const [whatIf, setWhatIf] = useState({
    monthly_sip_rs: goal.monthly_sip_rs || 0,
    horizon_years: goal.horizon_years || 0,
  });
  const [previewing, setPreviewing] = useState(false);
  const [preview, setPreview] = useState(null);
  const [applyingId, setApplyingId] = useState(null);

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

  // Apply a recovery-path option: patch goal with the tweak, re-simulate,
  // and refresh the parent view.
  const applyRecovery = async (path) => {
    setApplyingId(path.id);
    try {
      const patch = {};
      const apply = path.apply || {};
      if (apply.monthly_sip_rs != null) patch.monthly_sip_rs = apply.monthly_sip_rs;
      if (apply.horizon_years != null)  patch.horizon_years  = apply.horizon_years;
      if (apply.allocation_override)    patch.allocation     = apply.allocation_override;
      if (Object.keys(patch).length) {
        await axios.patch(`${API}/goals/${goal.goal_id}`, patch, { withCredentials: true });
      }
      await axios.post(`${API}/goals/${goal.goal_id}/simulate`, {}, { withCredentials: true });
      toast.success(`Applied: ${path.title}`);
      onRefresh?.();
    } catch (e) {
      toast.error(e.response?.data?.detail || "Could not apply");
    } finally {
      setApplyingId(null);
    }
  };

  // ── derived ----------------------------------------------------------
  const scenarios = sim.scenarios || {};
  const mc = sim.monte_carlo || {};
  const actions = sim.actions || [];
  const whyBehind = sim.why_behind || [];
  const recovery = sim.recovery_paths || [];
  const selected = goal.selected_funds || {};
  const health = sim.goal_health || "on_track";
  const feasibility = sim.feasibility || "ok";
  const H = HEALTH_META[health] || HEALTH_META.on_track;

  const currentSip = goal.monthly_sip_rs || 0;
  const requiredSip = sim.required_sip_rs || 0;
  const sipGap = Math.max(0, requiredSip - currentSip);
  const requiredReturn = sim.required_return_pct ?? null;
  const expectedReturn = sim.expected_return_pct ?? null;
  const returnGap = (requiredReturn != null && expectedReturn != null)
    ? requiredReturn - expectedReturn
    : null;

  const successTile = useMemo(() => fmtPctTone(mc.prob_success_pct), [mc.prob_success_pct]);

  // ── render -----------------------------------------------------------
  return (
    <div className="space-y-5" data-testid="scenario-simulator">
      {/* A. VERDICT BANNER ─────────────────────────────────────────── */}
      <div
        data-testid="verdict-banner"
        className={`rounded-xl border-2 ${H.accent} ${H.tone} p-4 flex items-start gap-3`}
      >
        <div className="w-10 h-10 rounded-full bg-white/70 flex items-center justify-center flex-shrink-0">
          <H.icon className="w-5 h-5" />
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <div className="text-lg font-bold">{H.verdict}</div>
            <Badge className={`text-[10px] uppercase tracking-wider font-bold ${H.tone} border`}>
              {H.label}
            </Badge>
            {feasibility === "unrealistic" && (
              <Badge className="text-[10px] uppercase bg-rose-100 text-rose-800 border border-rose-300">
                Unrealistic return needed
              </Badge>
            )}
            {feasibility === "stretch" && (
              <Badge className="text-[10px] uppercase bg-amber-100 text-amber-800 border border-amber-300">
                Stretch plan
              </Badge>
            )}
          </div>
          <div className="text-xs mt-1 opacity-80">
            {successTile.label.includes("—")
              ? `${(sim.on_track_pct || 0).toFixed(0)}% on-track under expected returns.`
              : `${successTile.label.split(" · ")[0]} chance of hitting target · `}
            {sim.shortfall_rs > 0
              ? `shortfall ${fmtRs(sim.shortfall_rs)}.`
              : "no projected shortfall."}
          </div>
        </div>
      </div>

      {/* B. HEADLINE METRIC ROW ─────────────────────────────────────── */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-3" data-testid="headline-metrics">
        <MetricCard
          testId="metric-target"
          label="Target (future value)"
          value={fmtRs(sim.future_target_rs || goal.target_amount_rs)}
          sub={sim.shortfall_rs > 0 ? `Shortfall ${fmtRs(sim.shortfall_rs)}` : "On track"}
          subTone={sim.shortfall_rs > 0 ? "text-rose-600" : "text-emerald-600"}
          icon={Target}
        />
        <DeltaCard
          testId="metric-sip-delta"
          label="Monthly SIP"
          current={fmtRs(currentSip)}
          required={fmtRs(requiredSip)}
          gap={sipGap > 0 ? `+${fmtRs(sipGap)}` : "—"}
          gapTone={sipGap > 0 ? "text-rose-600" : "text-emerald-600"}
        />
        <DeltaCard
          testId="metric-return-delta"
          label="Annual return"
          current={expectedReturn != null ? `${expectedReturn.toFixed(2)}%` : "—"}
          required={requiredReturn != null ? `${requiredReturn.toFixed(2)}%` : "—"}
          gap={returnGap != null ? `${returnGap >= 0 ? "+" : ""}${returnGap.toFixed(2)} pp` : "—"}
          gapTone={returnGap > 1 ? "text-rose-600" : returnGap < -1 ? "text-emerald-600" : "text-slate-600"}
          currentLabel="Expected"
          requiredLabel="Required"
        />
        <MetricCard
          testId="metric-success-prob"
          label="Success probability"
          value={successTile.label}
          valueTone={successTile.tone}
          sub={mc.n_runs ? `Monte-Carlo · ${mc.n_runs} sims` : "Run Simulate"}
        />
      </div>

      {/* C. WHY YOU'RE BEHIND ───────────────────────────────────────── */}
      {whyBehind.length > 0 && (
        <div
          data-testid="why-behind"
          className="rounded-xl border border-rose-200 bg-rose-50/60 dark:bg-rose-900/10 dark:border-rose-800 p-4"
        >
          <div className="flex items-center gap-2 mb-3">
            <AlertTriangle className="w-4 h-4 text-rose-600" />
            <span className="text-sm font-bold text-rose-900 dark:text-rose-300">
              Why you're behind
            </span>
          </div>
          <div className="space-y-2">
            {whyBehind.map((r) => (
              <div
                key={r.code}
                data-testid={`why-reason-${r.code}`}
                className="bg-white dark:bg-slate-900 rounded-lg px-3 py-2 border border-rose-100 dark:border-rose-900/60 flex items-start gap-2"
              >
                <Badge
                  className={`text-[9px] uppercase tracking-wider font-bold shrink-0 mt-0.5 ${
                    r.severity === "high"
                      ? "bg-rose-100 text-rose-800 border-rose-300"
                      : "bg-amber-100 text-amber-800 border-amber-300"
                  }`}
                >
                  {r.severity}
                </Badge>
                <div className="min-w-0 flex-1">
                  <div className="text-xs font-semibold text-slate-800 dark:text-slate-100">
                    {r.label}
                  </div>
                  <div className="text-[11px] leading-snug text-slate-600 dark:text-slate-400 mt-0.5">
                    {r.detail}
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* D. RECOVERY PATHS ──────────────────────────────────────────── */}
      {recovery.length > 0 && (
        <div data-testid="recovery-paths">
          <div className="flex items-center gap-2 mb-3">
            <Zap className="w-4 h-4 text-indigo-600" />
            <span className="text-sm font-bold text-slate-800 dark:text-slate-100">
              Recovery paths — pick one
            </span>
            <span className="text-[11px] text-slate-500">
              Each option re-simulates the full plan with the tweak applied.
            </span>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
            {recovery.map((p) => (
              <RecoveryCard
                key={p.id}
                path={p}
                onApply={() => applyRecovery(p)}
                applying={applyingId === p.id}
              />
            ))}
          </div>
        </div>
      )}

      {/* E. SCENARIO MATRIX ─────────────────────────────────────────── */}
      <div className="rounded-xl border border-slate-200 dark:border-slate-700 overflow-hidden">
        <div className="bg-slate-50 dark:bg-slate-800 px-4 py-2 text-xs font-semibold uppercase tracking-wider">
          Scenario matrix
        </div>
        <div
          className="grid grid-cols-2 md:grid-cols-4 gap-0 divide-x divide-slate-200 dark:divide-slate-700"
          data-testid="scenario-grid"
        >
          {Object.entries(scenarios).map(([k, v]) => {
            const m = SCENARIO_META[k] || SCENARIO_META.base;
            const Icon = m.icon;
            const tone = v.success_pct >= 90 ? "text-emerald-600"
                       : v.success_pct >= 60 ? "text-amber-600"
                       : "text-rose-600";
            return (
              <div key={k} className="p-4" data-testid={`scenario-${k}`}>
                <div className="flex items-center gap-2 mb-2">
                  <div className={`w-6 h-6 ${m.tone} rounded-md flex items-center justify-center`}>
                    <Icon className="w-3 h-3 text-white" />
                  </div>
                  <div className="text-xs font-semibold">{m.label}</div>
                </div>
                <div className="text-lg font-bold text-slate-800 dark:text-slate-100">
                  {fmtRs(v.corpus_rs)}
                </div>
                <div className="text-[10px] text-slate-500 mt-0.5">@ {v.return_pct}% return</div>
                <div className={`text-xs font-semibold mt-1 ${tone}`}>
                  {v.success_pct.toFixed(0)}% of target
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* F. MONTE CARLO ─────────────────────────────────────────────── */}
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

      {/* G. ACTIONS + ALLOCATION ────────────────────────────────────── */}
      {actions.length > 0 && (
        <div
          className="rounded-xl border border-slate-200 dark:border-slate-700 bg-amber-50 dark:bg-amber-900/20 p-4 space-y-2"
          data-testid="goal-actions"
        >
          <div className="text-xs font-semibold uppercase tracking-wider flex items-center gap-1.5 text-amber-900 dark:text-amber-200">
            <Zap className="w-3 h-3" /> Recommended actions
          </div>
          {actions.map((a, i) => (
            <div
              key={i}
              className="bg-white dark:bg-slate-900 rounded-md px-3 py-2 text-xs border border-amber-200 dark:border-amber-800"
            >
              <div className="font-semibold text-slate-800 dark:text-slate-100">{a.title}</div>
              <div className="text-slate-600 dark:text-slate-400 mt-0.5">{a.detail}</div>
            </div>
          ))}
        </div>
      )}

      <div className="rounded-xl border border-slate-200 dark:border-slate-700 p-4">
        <div className="text-xs font-semibold uppercase tracking-wider mb-2">
          Allocation & auto-picked funds
        </div>
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
            funds.map((f) => (
              <div
                key={f.instrument_id}
                className="flex items-center justify-between text-xs border-b border-slate-100 dark:border-slate-800 pb-1.5 last:border-0"
              >
                <div className="flex items-center gap-2 min-w-0">
                  <Badge variant="outline" className="text-[9px] uppercase">
                    {bucket}
                  </Badge>
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

      {/* H. WHAT-IF SLIDERS ─────────────────────────────────────────── */}
      <div
        className="rounded-xl border-2 border-dashed border-emerald-300 dark:border-emerald-800 bg-emerald-50/40 dark:bg-emerald-900/10 p-4"
        data-testid="what-if-panel"
      >
        <div className="text-xs font-semibold uppercase tracking-wider mb-3 flex items-center gap-1.5 text-emerald-700 dark:text-emerald-300">
          <RefreshCw className="w-3 h-3" /> What-if simulator (manual tweak)
        </div>
        <div className="grid grid-cols-2 gap-3 mb-3">
          <div>
            <Label className="text-xs flex justify-between">
              <span>SIP (₹/month)</span>
              <span className="tabular-nums text-slate-600">
                {Number(whatIf.monthly_sip_rs).toLocaleString("en-IN")}
              </span>
            </Label>
            <Slider
              min={0} max={500000} step={1000}
              value={[Number(whatIf.monthly_sip_rs)]}
              onValueChange={(v) => setWhatIf((w) => ({ ...w, monthly_sip_rs: v[0] }))}
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
              onValueChange={(v) => setWhatIf((w) => ({ ...w, horizon_years: v[0] }))}
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
            <Stat label="On-track" value={`${preview.on_track_pct?.toFixed(0)}%`}
                  tone={fmtPctTone(preview.on_track_pct).tone} />
            <Stat label="MC prob" value={`${preview.monte_carlo?.prob_success_pct}%`}
                  tone={fmtPctTone(preview.monte_carlo?.prob_success_pct).tone} />
          </div>
        )}
      </div>
    </div>
  );
}

// ── Sub-components ──────────────────────────────────────────────────────

const MetricCard = ({ testId, label, value, sub, subTone, valueTone, icon: Icon }) => (
  <div
    data-testid={testId}
    className="rounded-xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 p-3"
  >
    <div className="flex items-center justify-between mb-0.5">
      <div className="text-[9px] uppercase tracking-wider text-slate-500">{label}</div>
      {Icon && <Icon className="w-3.5 h-3.5 text-slate-400" />}
    </div>
    <div className={`text-xl font-bold tabular-nums ${valueTone || "text-slate-800 dark:text-slate-100"}`}>
      {value}
    </div>
    <div className={`text-[10px] mt-0.5 ${subTone || "text-slate-500"}`}>{sub}</div>
  </div>
);

const DeltaCard = ({
  testId, label, current, required, gap, gapTone,
  currentLabel = "Current", requiredLabel = "Required",
}) => (
  <div
    data-testid={testId}
    className="rounded-xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 p-3"
  >
    <div className="text-[9px] uppercase tracking-wider text-slate-500 mb-1">{label}</div>
    <div className="flex items-baseline justify-between gap-1 text-sm">
      <span className="text-slate-500 text-[10px]">{currentLabel}</span>
      <span className="tabular-nums font-semibold text-slate-700 dark:text-slate-200">{current}</span>
    </div>
    <div className="flex items-baseline justify-between gap-1 text-sm">
      <span className="text-slate-500 text-[10px]">{requiredLabel}</span>
      <span className="tabular-nums font-semibold text-slate-700 dark:text-slate-200">{required}</span>
    </div>
    <div className="mt-1 pt-1 border-t border-slate-100 dark:border-slate-800 flex items-baseline justify-between">
      <span className="text-slate-500 text-[10px] uppercase font-semibold">Gap</span>
      <span className={`tabular-nums font-bold ${gapTone || "text-slate-800"}`}>{gap}</span>
    </div>
  </div>
);

const RecoveryCard = ({ path, onApply, applying }) => {
  const meta = RECOVERY_META[path.id] || RECOVERY_META.increase_sip;
  const Icon = meta.icon;
  const sp = fmtPctTone(path.prob_success_pct);
  const toneMap = {
    emerald: "border-emerald-200 bg-emerald-50/60 dark:bg-emerald-900/10 dark:border-emerald-800",
    blue:    "border-blue-200    bg-blue-50/60    dark:bg-blue-900/10    dark:border-blue-800",
    orange:  "border-orange-200  bg-orange-50/60  dark:bg-orange-900/10  dark:border-orange-800",
  };
  const iconTone = {
    emerald: "text-emerald-600 bg-emerald-100 dark:bg-emerald-900/40",
    blue:    "text-blue-600 bg-blue-100 dark:bg-blue-900/40",
    orange:  "text-orange-600 bg-orange-100 dark:bg-orange-900/40",
  };
  return (
    <div
      data-testid={`recovery-card-${path.id}`}
      className={`rounded-xl border p-4 flex flex-col ${toneMap[meta.tone]}`}
    >
      <div className="flex items-center gap-2 mb-2">
        <div className={`w-8 h-8 rounded-lg flex items-center justify-center ${iconTone[meta.tone]}`}>
          <Icon className="w-4 h-4" />
        </div>
        <div className="min-w-0">
          <div className="text-xs font-bold text-slate-800 dark:text-slate-100 leading-tight">
            {path.title}
          </div>
          <div className="text-[10px] text-slate-500">{path.delta_text}</div>
        </div>
      </div>
      <div className="text-[11px] text-slate-700 dark:text-slate-300 bg-white/60 dark:bg-slate-900/40 rounded-md px-2 py-1.5 mb-3 font-mono">
        {path.tweak_label}
      </div>
      <div className="grid grid-cols-2 gap-2 mb-3">
        <div className="bg-white dark:bg-slate-900 rounded-md px-2 py-1.5">
          <div className="text-[9px] uppercase tracking-wider text-slate-500">On-track</div>
          <div className={`text-sm font-bold tabular-nums ${fmtPctTone(path.on_track_pct).tone}`}>
            {path.on_track_pct?.toFixed(0)}%
          </div>
        </div>
        <div className="bg-white dark:bg-slate-900 rounded-md px-2 py-1.5">
          <div className="text-[9px] uppercase tracking-wider text-slate-500">MC success</div>
          <div className={`text-sm font-bold tabular-nums ${sp.tone}`}>
            {sp.label.split(" · ")[0]}
          </div>
        </div>
      </div>
      <Button
        size="sm"
        onClick={onApply}
        disabled={applying}
        data-testid={`recovery-apply-${path.id}`}
        className="mt-auto h-7 text-xs"
      >
        {applying ? "Applying…" : (
          <>
            Apply this plan <ArrowRight className="w-3 h-3 ml-1" />
          </>
        )}
      </Button>
    </div>
  );
};

const Stat = ({ label, value, tone = "text-slate-800 dark:text-slate-100" }) => (
  <div className="rounded bg-slate-50 dark:bg-slate-800/60 px-3 py-2">
    <div className="uppercase text-[9px] tracking-wider text-slate-500">{label}</div>
    <div className={`font-bold text-sm tabular-nums ${tone}`}>{value}</div>
  </div>
);
