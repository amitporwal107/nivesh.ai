import React, { useState, useEffect, useCallback, useMemo } from "react";
import axios from "axios";
import { toast } from "sonner";
import {
  Target, Plus, TrendingUp, Shield, Sparkles, X,
  CheckCircle2, AlertCircle, RefreshCw, PlayCircle,
  Home, GraduationCap, Briefcase, Wallet, Trash2,
  Layers, Calendar, IndianRupee, Flame,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Slider } from "@/components/ui/slider";
import SnapshotWizard from "./FinancialSnapshotWizard";
import GoalWizard from "./GoalCreateWizard";
import ScenarioSimulator from "./ScenarioSimulator";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

// Product constraint: at most 4 active goals at a time. Keeps the
// consolidated view legible + nudges the user to prioritise.
const MAX_GOALS = 4;

const GOAL_TYPE_META = {
  retirement: { label: "Retirement", icon: Briefcase, color: "bg-indigo-500" },
  education:  { label: "Education", icon: GraduationCap, color: "bg-emerald-500" },
  home:       { label: "Home", icon: Home, color: "bg-orange-500" },
  wealth:     { label: "Wealth Build-up", icon: Sparkles, color: "bg-purple-500" },
  custom:     { label: "Custom", icon: Target, color: "bg-slate-500" },
};

const fmtRs = (n) => {
  if (n == null) return "—";
  const abs = Math.abs(n);
  if (abs >= 1e7) return `₹${(n / 1e7).toFixed(2)} Cr`;
  if (abs >= 1e5) return `₹${(n / 1e5).toFixed(2)} L`;
  if (abs >= 1e3) return `₹${Math.round(n).toLocaleString("en-IN")}`;
  return `₹${Math.round(n).toLocaleString("en-IN")}`;
};

const onTrackTone = (pct) => {
  if (pct == null) return "bg-slate-200 text-slate-700";
  if (pct >= 85) return "bg-emerald-500 text-white";
  if (pct >= 60) return "bg-amber-500 text-white";
  return "bg-rose-500 text-white";
};

// ── GoalCard ───────────────────────────────────────────────────────────
const GoalCard = ({ goal, onOpen, onSimulate, onDelete, simulating, deleting }) => {
  const meta = GOAL_TYPE_META[goal.goal_type] || GOAL_TYPE_META.custom;
  const Icon = meta.icon;
  const sim = goal.last_simulation || {};
  const mc = sim.monte_carlo || {};
  const topAction = (sim.actions || [])[0];

  return (
    <Card
      className="rounded-2xl border border-slate-200 dark:border-slate-700 hover:shadow-lg transition-shadow cursor-pointer relative group"
      data-testid={`goal-card-${goal.goal_id}`}
      onClick={() => onOpen(goal)}
    >
      <CardContent className="p-5">
        <div className="flex items-start justify-between mb-3">
          <div className="flex items-center gap-3">
            <div className={`w-10 h-10 ${meta.color} rounded-xl flex items-center justify-center`}>
              <Icon className="w-5 h-5 text-white" />
            </div>
            <div>
              <div className="font-semibold text-slate-800 dark:text-slate-100">{goal.goal_name}</div>
              <div className="text-[11px] uppercase tracking-wider text-slate-500">
                {meta.label} · {goal.priority} priority
              </div>
            </div>
          </div>
          <div className="flex items-center gap-1.5">
            <Badge className={onTrackTone(goal.on_track_pct)}>
              {goal.on_track_pct != null ? `${goal.on_track_pct.toFixed(0)}% on track` : "—"}
            </Badge>
            <button
              onClick={(e) => { e.stopPropagation(); onDelete(goal); }}
              disabled={deleting === goal.goal_id}
              title="Delete goal"
              data-testid={`goal-delete-btn-${goal.goal_id}`}
              className="opacity-0 group-hover:opacity-100 transition-opacity p-1 rounded hover:bg-rose-50 dark:hover:bg-rose-900/30 text-slate-400 hover:text-rose-600"
            >
              <Trash2 className="w-3.5 h-3.5" />
            </button>
          </div>
        </div>

        <div className="grid grid-cols-3 gap-3 text-xs">
          <div>
            <div className="uppercase tracking-wider text-[9px] text-slate-500 mb-0.5">Target (today)</div>
            <div className="font-bold text-slate-800 dark:text-slate-100">{fmtRs(goal.target_amount_rs)}</div>
          </div>
          <div>
            <div className="uppercase tracking-wider text-[9px] text-slate-500 mb-0.5">Horizon</div>
            <div className="font-bold text-slate-800 dark:text-slate-100">{goal.horizon_years}y</div>
          </div>
          <div>
            <div className="uppercase tracking-wider text-[9px] text-slate-500 mb-0.5">Current SIP</div>
            <div className="font-bold text-slate-800 dark:text-slate-100">{fmtRs(goal.monthly_sip_rs)}/mo</div>
          </div>
        </div>

        <div className="mt-3 pt-3 border-t border-slate-100 dark:border-slate-800 flex items-center justify-between">
          <div className="text-[11px] text-slate-600 dark:text-slate-400">
            {mc.prob_success_pct != null ? (
              <>MC success prob: <b className="text-slate-800 dark:text-slate-200">{mc.prob_success_pct.toFixed(0)}%</b></>
            ) : "Run simulate to see success probability"}
          </div>
          <Button
            size="sm" variant="ghost"
            onClick={(e) => { e.stopPropagation(); onSimulate(goal.goal_id); }}
            disabled={simulating === goal.goal_id}
            data-testid={`goal-simulate-btn-${goal.goal_id}`}
          >
            {simulating === goal.goal_id ? <RefreshCw className="w-3 h-3 mr-1 animate-spin" /> : <PlayCircle className="w-3 h-3 mr-1" />}
            Simulate
          </Button>
        </div>

        {topAction && (
          <div className="mt-3 text-[11px] bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-800 rounded-md px-3 py-2"
               data-testid={`goal-action-${goal.goal_id}`}>
            <div className="font-semibold text-amber-900 dark:text-amber-200">{topAction.title}</div>
            <div className="text-amber-800 dark:text-amber-300">{topAction.detail}</div>
          </div>
        )}
      </CardContent>
    </Card>
  );
};

// ── ConsolidatedOverview ──────────────────────────────────────────────
// A single card that rolls up every active goal into one portfolio-wide
// view. It recomputes whenever goals change (create / edit / delete /
// simulate) — the parent owns the goals[] list and re-renders this.
const ConsolidatedOverview = ({ goals }) => {
  const rollup = useMemo(() => {
    if (!goals.length) return null;
    const total_target = goals.reduce((s, g) => s + (g.target_amount_rs || 0), 0);
    const total_sip    = goals.reduce((s, g) => s + (g.monthly_sip_rs || 0), 0);
    const with_track   = goals.filter((g) => g.on_track_pct != null);
    // Weighted by target amount so a large goal dominates the portfolio %.
    const wOnTrack = with_track.length
      ? with_track.reduce((s, g) => s + (g.on_track_pct * (g.target_amount_rs || 1)), 0) /
        Math.max(1, with_track.reduce((s, g) => s + (g.target_amount_rs || 1), 0))
      : null;
    const maxHorizon = Math.max(0, ...goals.map((g) => g.horizon_years || 0));
    const minHorizon = Math.min(Infinity, ...goals.map((g) => g.horizon_years || Infinity));
    const atRisk     = goals.filter((g) => g.on_track_pct != null && g.on_track_pct < 60).length;
    const onTrack    = goals.filter((g) => g.on_track_pct != null && g.on_track_pct >= 85).length;
    return {
      total_target, total_sip, wOnTrack,
      maxHorizon, minHorizon: minHorizon === Infinity ? 0 : minHorizon,
      atRisk, onTrack,
    };
  }, [goals]);

  if (!rollup) return null;
  const tone = onTrackTone(rollup.wOnTrack);

  return (
    <Card
      className="rounded-2xl border-2 border-emerald-200 dark:border-emerald-800 bg-gradient-to-br from-emerald-50/80 via-white to-white dark:from-emerald-900/20 dark:via-slate-900 dark:to-slate-900"
      data-testid="goals-consolidated-view"
    >
      <CardContent className="p-5">
        <div className="flex items-center justify-between flex-wrap gap-3 mb-4">
          <div className="flex items-center gap-2.5">
            <div className="w-9 h-9 rounded-xl bg-emerald-100 dark:bg-emerald-900/40 flex items-center justify-center">
              <Layers className="w-5 h-5 text-emerald-600" />
            </div>
            <div>
              <div className="text-sm font-bold text-slate-800 dark:text-slate-100">
                All goals at a glance
              </div>
              <div className="text-[11px] text-slate-500">
                {goals.length} of {MAX_GOALS} goals tracked · updates live as you add, edit or remove
              </div>
            </div>
          </div>
          <Badge className={tone} data-testid="consolidated-on-track">
            {rollup.wOnTrack != null ? `${rollup.wOnTrack.toFixed(0)}% overall on track` : "Simulate goals to see rollup"}
          </Badge>
        </div>

        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <div data-testid="consolidated-target">
            <div className="flex items-center gap-1 text-[9px] uppercase tracking-wider text-slate-500 mb-1">
              <IndianRupee className="w-3 h-3" /> Combined target
            </div>
            <div className="text-xl font-bold text-slate-800 dark:text-slate-100 tabular-nums">
              {fmtRs(rollup.total_target)}
            </div>
            <div className="text-[10px] text-slate-500 mt-0.5">in today's rupees</div>
          </div>
          <div data-testid="consolidated-sip">
            <div className="flex items-center gap-1 text-[9px] uppercase tracking-wider text-slate-500 mb-1">
              <TrendingUp className="w-3 h-3" /> Total SIP
            </div>
            <div className="text-xl font-bold text-slate-800 dark:text-slate-100 tabular-nums">
              {fmtRs(rollup.total_sip)}/mo
            </div>
            <div className="text-[10px] text-slate-500 mt-0.5">across {goals.length} goals</div>
          </div>
          <div data-testid="consolidated-horizon">
            <div className="flex items-center gap-1 text-[9px] uppercase tracking-wider text-slate-500 mb-1">
              <Calendar className="w-3 h-3" /> Horizon span
            </div>
            <div className="text-xl font-bold text-slate-800 dark:text-slate-100">
              {rollup.minHorizon === rollup.maxHorizon
                ? `${rollup.maxHorizon}y`
                : `${rollup.minHorizon}–${rollup.maxHorizon}y`}
            </div>
            <div className="text-[10px] text-slate-500 mt-0.5">shortest to longest</div>
          </div>
          <div data-testid="consolidated-health">
            <div className="flex items-center gap-1 text-[9px] uppercase tracking-wider text-slate-500 mb-1">
              <Flame className="w-3 h-3" /> Goal health
            </div>
            <div className="flex items-baseline gap-2">
              <span className="text-xl font-bold text-emerald-600 tabular-nums">{rollup.onTrack}</span>
              <span className="text-[10px] text-slate-500">on track</span>
              {rollup.atRisk > 0 && (
                <>
                  <span className="text-slate-300">·</span>
                  <span className="text-xl font-bold text-rose-600 tabular-nums">{rollup.atRisk}</span>
                  <span className="text-[10px] text-slate-500">at risk</span>
                </>
              )}
            </div>
          </div>
        </div>

        {/* Per-goal mini-bars */}
        <div className="mt-4 pt-4 border-t border-slate-100 dark:border-slate-800 space-y-2">
          {goals.map((g) => {
            const meta = GOAL_TYPE_META[g.goal_type] || GOAL_TYPE_META.custom;
            const Icon = meta.icon;
            const pct = g.on_track_pct != null ? Math.min(100, Math.max(0, g.on_track_pct)) : 0;
            return (
              <div
                key={g.goal_id}
                data-testid={`consolidated-goal-row-${g.goal_id}`}
                className="flex items-center gap-3"
              >
                <div className={`w-6 h-6 ${meta.color} rounded-md flex items-center justify-center flex-shrink-0`}>
                  <Icon className="w-3 h-3 text-white" />
                </div>
                <div className="text-xs font-medium text-slate-700 dark:text-slate-300 flex-shrink-0 w-28 truncate">
                  {g.goal_name}
                </div>
                <div className="flex-1 h-1.5 rounded-full bg-slate-100 dark:bg-slate-800 overflow-hidden">
                  <div
                    className={`h-full rounded-full ${g.on_track_pct == null ? "bg-slate-300" : g.on_track_pct >= 85 ? "bg-emerald-500" : g.on_track_pct >= 60 ? "bg-amber-500" : "bg-rose-500"}`}
                    style={{ width: `${pct}%` }}
                  />
                </div>
                <div className="text-[11px] text-slate-500 tabular-nums w-14 text-right">
                  {g.on_track_pct != null ? `${g.on_track_pct.toFixed(0)}%` : "—"}
                </div>
                <div className="text-[11px] font-semibold text-slate-700 dark:text-slate-200 tabular-nums w-20 text-right">
                  {fmtRs(g.monthly_sip_rs)}/mo
                </div>
              </div>
            );
          })}
        </div>
      </CardContent>
    </Card>
  );
};

// ── GoalDetailModal ────────────────────────────────────────────────────
const GoalDetailModal = ({ goal, open, onOpenChange, onRefresh }) => {
  if (!goal) return null;
  const sim = goal.last_simulation || {};

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-5xl max-h-[90vh] overflow-y-auto" data-testid="goal-detail-modal">
        <DialogHeader>
          <DialogTitle>{goal.goal_name}</DialogTitle>
        </DialogHeader>
        <ScenarioSimulator goal={goal} initialSimulation={sim} onRefresh={onRefresh} />
      </DialogContent>
    </Dialog>
  );
};

// ── Main view ──────────────────────────────────────────────────────────
export default function GoalsView() {
  const [snapshot, setSnapshot] = useState(null);
  const [goals, setGoals] = useState([]);
  const [loading, setLoading] = useState(true);
  const [snapshotOpen, setSnapshotOpen] = useState(false);
  const [wizardOpen, setWizardOpen] = useState(false);
  const [selectedGoal, setSelectedGoal] = useState(null);
  const [simulating, setSimulating] = useState(null);
  const [deleting, setDeleting] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [snap, gs] = await Promise.all([
        axios.get(`${API}/goals/snapshot`, { withCredentials: true }),
        axios.get(`${API}/goals`, { withCredentials: true }),
      ]);
      setSnapshot(snap.data.snapshot);
      setGoals((gs.data.goals || []).filter(g => g.status === "active"));
    } catch (e) {
      toast.error(e.response?.data?.detail || "Failed to load goals");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const simulate = async (goal_id) => {
    setSimulating(goal_id);
    try {
      await axios.post(`${API}/goals/${goal_id}/simulate`, {}, { withCredentials: true });
      toast.success("Simulation refreshed");
      await load();
    } catch (e) {
      toast.error(e.response?.data?.detail || "Simulation failed");
    } finally {
      setSimulating(null);
    }
  };

  const openGoal = async (goal) => {
    // Fetch fresh detail with latest simulation
    try {
      const res = await axios.get(`${API}/goals/${goal.goal_id}`, { withCredentials: true });
      setSelectedGoal(res.data);
    } catch (e) {
      setSelectedGoal(goal);
    }
  };

  const deleteGoal = async (goal) => {
    if (!window.confirm(
      `Delete "${goal.goal_name}"? This can't be undone — your SIP targets and simulations for this goal will be removed.`,
    )) return;
    setDeleting(goal.goal_id);
    try {
      await axios.delete(`${API}/goals/${goal.goal_id}`, { withCredentials: true });
      toast.success(`${goal.goal_name} removed`);
      await load();
    } catch (e) {
      toast.error(e.response?.data?.detail || "Delete failed");
    } finally {
      setDeleting(null);
    }
  };

  const needsSnapshot = !snapshot;
  const atGoalLimit = goals.length >= MAX_GOALS;

  return (
    <div className="px-4 sm:px-6 lg:px-8 py-6 max-w-7xl mx-auto space-y-6" data-testid="goals-view">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold text-slate-800 dark:text-slate-100 flex items-center gap-2">
            <Target className="w-7 h-7 text-emerald-600" /> Goals
          </h1>
          <p className="text-sm text-slate-600 dark:text-slate-400 mt-1">
            Outcome-first planning — convert life goals into quantified, actionable investment plans.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button
            variant="outline" size="sm"
            onClick={() => setSnapshotOpen(true)}
            data-testid="goals-snapshot-btn"
          >
            <Shield className="w-4 h-4 mr-2" />
            {snapshot ? "Edit financial snapshot" : "Set up your snapshot"}
          </Button>
          <Button
            size="sm"
            onClick={() => setWizardOpen(true)}
            disabled={needsSnapshot || atGoalLimit}
            title={atGoalLimit ? `You can track up to ${MAX_GOALS} goals at a time. Delete one to add another.` : undefined}
            data-testid="goals-create-btn"
            className="bg-emerald-600 hover:bg-emerald-700"
          >
            <Plus className="w-4 h-4 mr-2" />
            {atGoalLimit ? `${goals.length} / ${MAX_GOALS} — limit reached` : "New goal"}
          </Button>
        </div>
      </div>

      {/* Snapshot summary */}
      {snapshot ? (
        <Card className="rounded-2xl border border-slate-200 dark:border-slate-700 bg-gradient-to-br from-emerald-50 to-white dark:from-emerald-900/20 dark:to-transparent">
          <CardContent className="p-4 grid grid-cols-2 md:grid-cols-5 gap-3 text-xs">
            <div>
              <div className="uppercase tracking-wider text-[9px] text-slate-500 mb-0.5">Risk profile</div>
              <div className="font-bold capitalize text-slate-800 dark:text-slate-100">{snapshot.risk_profile}</div>
            </div>
            <div>
              <div className="uppercase tracking-wider text-[9px] text-slate-500 mb-0.5">Monthly income</div>
              <div className="font-bold text-slate-800 dark:text-slate-100">{fmtRs(snapshot.monthly_income_rs)}</div>
            </div>
            <div>
              <div className="uppercase tracking-wider text-[9px] text-slate-500 mb-0.5">Expenses</div>
              <div className="font-bold text-slate-800 dark:text-slate-100">{fmtRs(snapshot.monthly_expenses_rs)}</div>
            </div>
            <div>
              <div className="uppercase tracking-wider text-[9px] text-slate-500 mb-0.5">Current corpus</div>
              <div className="font-bold text-slate-800 dark:text-slate-100">{fmtRs(snapshot.current_corpus_rs)}</div>
            </div>
            <div>
              <div className="uppercase tracking-wider text-[9px] text-slate-500 mb-0.5">Dependents</div>
              <div className="font-bold text-slate-800 dark:text-slate-100">{snapshot.dependents ?? 0}</div>
            </div>
          </CardContent>
        </Card>
      ) : (
        <Card className="rounded-2xl border border-amber-300 dark:border-amber-800 bg-amber-50 dark:bg-amber-900/20">
          <CardContent className="p-4 flex items-start gap-3">
            <AlertCircle className="w-5 h-5 text-amber-600 mt-0.5" />
            <div className="flex-1">
              <div className="font-semibold text-amber-900 dark:text-amber-200">Tell us about yourself first</div>
              <div className="text-xs text-amber-800 dark:text-amber-300 mt-1">
                A one-time financial snapshot powers every goal recommendation — age, income, expenses, existing corpus, and risk appetite. Takes 30 seconds.
              </div>
            </div>
            <Button
              size="sm"
              onClick={() => setSnapshotOpen(true)}
              className="bg-amber-600 hover:bg-amber-700 text-white"
              data-testid="goals-snapshot-cta"
            >
              Get started
            </Button>
          </CardContent>
        </Card>
      )}

      {/* Consolidated at-a-glance view (updates live as goals change) */}
      {!loading && goals.length > 0 && <ConsolidatedOverview goals={goals} />}

      {/* Goals grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4" data-testid="goals-grid">
        {loading && <div className="col-span-full text-center text-sm text-slate-500 py-12">Loading…</div>}
        {!loading && goals.length === 0 && (
          <div className="col-span-full text-center py-16">
            <Target className="w-12 h-12 text-slate-300 mx-auto mb-3" />
            <div className="font-semibold text-slate-700 dark:text-slate-300">No goals yet</div>
            <div className="text-xs text-slate-500 mt-1">Create your first goal — retirement, education, home, or a custom wealth target.</div>
            {!needsSnapshot && (
              <Button onClick={() => setWizardOpen(true)} className="mt-4 bg-emerald-600 hover:bg-emerald-700">
                <Plus className="w-4 h-4 mr-2" /> Create your first goal
              </Button>
            )}
          </div>
        )}
        {goals.map(g => (
          <GoalCard
            key={g.goal_id}
            goal={g}
            onOpen={openGoal}
            onSimulate={simulate}
            onDelete={deleteGoal}
            simulating={simulating}
            deleting={deleting}
          />
        ))}
      </div>

      {/* Modals */}
      {snapshotOpen && (
        <SnapshotWizard
          open={snapshotOpen}
          onOpenChange={setSnapshotOpen}
          initial={snapshot}
          onSaved={() => { setSnapshotOpen(false); load(); }}
        />
      )}
      {wizardOpen && (
        <GoalWizard
          open={wizardOpen}
          onOpenChange={setWizardOpen}
          onCreated={() => { setWizardOpen(false); load(); }}
        />
      )}
      <GoalDetailModal
        goal={selectedGoal}
        open={!!selectedGoal}
        onOpenChange={(open) => !open && setSelectedGoal(null)}
        onRefresh={load}
      />
    </div>
  );
}
