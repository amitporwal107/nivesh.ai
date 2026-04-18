import React, { useState, useEffect, useCallback } from "react";
import axios from "axios";
import { motion, AnimatePresence } from "framer-motion";
import { toast } from "sonner";
import { Sparkles, Lightbulb, AlertTriangle, Sliders, Bookmark, Trash2, ClipboardList, CheckCircle2, ChevronDown, ChevronUp } from "lucide-react";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog";

import PortfolioContextHeader from "./PortfolioContextHeader";
import ScenarioCard from "./ScenarioCard";
import SimulationPanel from "./SimulationPanel";
import CustomScenarioBuilder from "./CustomScenarioBuilder";
import RebalancePlanDialog from "./RebalancePlanDialog";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

const AICopilotView = ({ riskProfile }) => {
  const [loading, setLoading] = useState(true);
  const [scenarios, setScenarios] = useState([]);
  const [context, setContext] = useState(null);
  const [selected, setSelected] = useState(null);
  const [selectedPayload, setSelectedPayload] = useState(null);
  const [simulating, setSimulating] = useState(false);
  const [result, setResult] = useState(null);
  const [applying, setApplying] = useState(false);
  const [saving, setSaving] = useState(false);

  // Phase 2
  const [showCustom, setShowCustom] = useState(false);
  const [planOpen, setPlanOpen] = useState(false);
  const [plan, setPlan] = useState(null);
  const [loadingPlan, setLoadingPlan] = useState(false);
  const [saveDialogOpen, setSaveDialogOpen] = useState(false);
  const [saveName, setSaveName] = useState("");
  const [savedList, setSavedList] = useState([]);
  const [pendingPlans, setPendingPlans] = useState([]);
  const [expandedPlan, setExpandedPlan] = useState(null);

  const loadScenarios = useCallback(async () => {
    setLoading(true);
    try {
      const res = await axios.get(`${API}/scenarios/suggest`, { withCredentials: true });
      setScenarios(res.data.scenarios || []);
      setContext(res.data.context || null);
    } catch (err) {
      toast.error("Couldn't load scenarios");
    } finally {
      setLoading(false);
    }
  }, []);

  const loadSaved = useCallback(async () => {
    try {
      const res = await axios.get(`${API}/scenarios/saved`, { withCredentials: true });
      setSavedList(res.data.saved || []);
    } catch (err) {
      // non-fatal
    }
  }, []);

  const loadPending = useCallback(async () => {
    try {
      const res = await axios.get(`${API}/scenarios/pending`, { withCredentials: true });
      setPendingPlans(res.data.pending || []);
    } catch (err) {
      // non-fatal
    }
  }, []);

  useEffect(() => {
    loadScenarios();
    loadSaved();
    loadPending();
  }, [loadScenarios, loadSaved, loadPending]);

  const buildSimulatePayload = (scenario) => {
    const alloc = scenario.target_allocation || {};
    const payload = { scenario_id: scenario.id };
    if (alloc.equity !== undefined) payload.target_equity = alloc.equity;
    if (alloc.debt !== undefined) payload.target_debt = alloc.debt;
    if (alloc.gold !== undefined) payload.target_gold = alloc.gold;
    if (alloc.amc_cap !== undefined) payload.target_amc_cap = alloc.amc_cap;
    if (alloc.small_cap !== undefined) payload.target_small_cap = alloc.small_cap;
    if (alloc.plan_type === "direct") payload.switch_to_direct = true;
    if (alloc.remove_dead) payload.remove_dead = true;
    return payload;
  };

  const runSimulate = async (scenario, payload) => {
    setSelected(scenario);
    setSelectedPayload(payload);
    setSimulating(true);
    setResult(null);
    try {
      const res = await axios.post(`${API}/scenarios/simulate`, payload, { withCredentials: true });
      setResult(res.data);
      setTimeout(() => {
        document.querySelector('[data-testid="simulation-panel"]')?.scrollIntoView({ behavior: "smooth", block: "start" });
      }, 100);
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Simulation failed");
    } finally {
      setSimulating(false);
    }
  };

  const handleSimulateCard = (scenario) => runSimulate(scenario, buildSimulatePayload(scenario));

  const handleRunCustom = async (payload) => {
    setShowCustom(false);
    await runSimulate(
      { id: "custom", title: "Custom Scenario", category: "optimization" },
      payload
    );
  };

  // --- Apply: persist pending actions ---
  const handleApply = async () => {
    if (!result || !selectedPayload) return;
    setApplying(true);
    try {
      // First build plan if not already built
      let planData = plan;
      if (!planData) {
        const r = await axios.post(`${API}/scenarios/rebalance-plan`, selectedPayload, { withCredentials: true });
        planData = r.data;
      }
      const res = await axios.post(
        `${API}/scenarios/apply`,
        {
          scenario_id: selected?.id || null,
          actions: planData?.actions || [],
          payload: selectedPayload,
        },
        { withCredentials: true }
      );
      toast.success(`${res.data.action_count} action(s) saved as pending plan.`);
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Apply failed");
    } finally {
      setApplying(false);
    }
  };

  // --- View Rebalance Plan ---
  const handleViewPlan = async () => {
    if (!selectedPayload) return;
    setLoadingPlan(true);
    setPlanOpen(true);
    try {
      const res = await axios.post(`${API}/scenarios/rebalance-plan`, selectedPayload, { withCredentials: true });
      setPlan(res.data);
    } catch (err) {
      toast.error("Couldn't build rebalance plan");
      setPlanOpen(false);
    } finally {
      setLoadingPlan(false);
    }
  };

  // --- Save scenario ---
  const openSaveDialog = () => {
    setSaveName(selected?.title || "My Scenario");
    setSaveDialogOpen(true);
  };

  const handleSave = async () => {
    if (!result || !selectedPayload || !saveName.trim()) return;
    setSaving(true);
    try {
      await axios.post(
        `${API}/scenarios/save`,
        {
          name: saveName.trim(),
          scenario_id: selected?.id || null,
          payload: selectedPayload,
          result,
        },
        { withCredentials: true }
      );
      toast.success(`"${saveName}" saved.`);
      setSaveDialogOpen(false);
      loadSaved();
    } catch (err) {
      toast.error("Couldn't save scenario");
    } finally {
      setSaving(false);
    }
  };

  const handleDeleteSaved = async (savedId) => {
    try {
      await axios.delete(`${API}/scenarios/saved/${savedId}`, { withCredentials: true });
      toast.success("Scenario deleted");
      loadSaved();
    } catch (err) {
      toast.error("Delete failed");
    }
  };

  const handleLoadSaved = async (s) => {
    await runSimulate(
      { id: s.scenario_id || "custom", title: s.name, category: "optimization" },
      s.payload
    );
  };

  // ---------- pending plans ----------
  const handleDeletePending = async (planId) => {
    try {
      await axios.delete(`${API}/scenarios/pending/${planId}`, { withCredentials: true });
      toast.success("Plan removed");
      loadPending();
    } catch (err) {
      toast.error("Delete failed");
    }
  };

  const handleCompletePending = async (planId) => {
    try {
      await axios.post(`${API}/scenarios/pending/${planId}/complete`, {}, { withCredentials: true });
      toast.success("Marked as completed");
      loadPending();
    } catch (err) {
      toast.error("Update failed");
    }
  };

  // ---------- render ----------
  if (loading) {
    return (
      <Card className="p-8 rounded-2xl border-slate-100 dark:border-slate-800 bg-white dark:bg-slate-900 text-center">
        <div className="inline-flex items-center gap-2 text-slate-500 dark:text-slate-400">
          <Sparkles className="w-5 h-5 animate-pulse" />
          <span className="text-sm">Analyzing your portfolio…</span>
        </div>
      </Card>
    );
  }

  if (!context) {
    return (
      <Card className="p-8 rounded-2xl border-slate-100 dark:border-slate-800 bg-white dark:bg-slate-900 text-center">
        <AlertTriangle className="w-10 h-10 mx-auto text-amber-400 mb-3" strokeWidth={1.5} />
        <p className="text-sm text-slate-500 dark:text-slate-400">
          Add holdings to get personalized AI Copilot scenarios.
        </p>
      </Card>
    );
  }

  const topProblems = [];
  if (context.equity_pct > 80) topProblems.push(`${context.equity_pct}% equity exposure`);
  if (context.annual_cost_leak > 10000) topProblems.push(`₹${Math.round(context.annual_cost_leak / 1000)}K/yr cost leakage`);
  if (context.top_amc_pct > 30) topProblems.push(`${context.top_amc_pct}% in ${context.top_amc}`);
  if (context.debt_pct < 5) topProblems.push("No debt allocation");

  return (
    <div data-testid="ai-copilot-view" className="space-y-5">
      <PortfolioContextHeader context={context} riskProfile={riskProfile} />

      {/* AI Insight Summary */}
      <Card
        data-testid="ai-insight-summary"
        className="p-4 sm:p-5 rounded-2xl border-slate-100 dark:border-slate-800 bg-white dark:bg-slate-900"
      >
        <div className="flex items-start gap-3">
          <div className="w-10 h-10 rounded-xl bg-amber-50 dark:bg-amber-950/60 text-amber-600 dark:text-amber-400 flex items-center justify-center flex-shrink-0">
            <Lightbulb className="w-5 h-5" strokeWidth={2} />
          </div>
          <div className="flex-1 min-w-0">
            <h3 className="font-semibold text-slate-900 dark:text-white text-sm sm:text-base">
              {topProblems.length > 0
                ? "Your portfolio is risk-heavy and cost inefficient"
                : "Your portfolio looks well-balanced"}
            </h3>
            {topProblems.length > 0 && (
              <>
                <div className="mt-2 flex flex-wrap gap-1.5" data-testid="top-problems">
                  {topProblems.map((p, i) => (
                    <span key={i} className="text-[11px] font-medium px-2 py-1 rounded-md bg-red-50 dark:bg-red-950/60 text-red-700 dark:text-red-400">
                      {p}
                    </span>
                  ))}
                </div>
                <p className="mt-3 text-xs text-slate-600 dark:text-slate-400">
                  <span className="font-semibold">Recommended direction: </span>
                  {context.debt_pct < 5 ? "Add debt allocation, " : ""}
                  {context.top_amc_pct > 30 ? "reduce AMC concentration, " : ""}
                  {context.annual_cost_leak > 10000 ? "switch to direct plans." : "stay the course."}
                </p>
              </>
            )}
          </div>
        </div>
      </Card>

      {/* Scenarios header with Custom builder CTA */}
      <div>
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2 mb-3">
          <div>
            <h3 className="text-base sm:text-lg font-semibold text-slate-900 dark:text-white">
              Pre-built Scenarios
            </h3>
            <p className="text-xs text-slate-500 dark:text-slate-400">
              Personalized for your holdings. Tap Simulate to see impact.
            </p>
          </div>
          <Button
            data-testid="open-custom-scenario-btn"
            variant="outline"
            onClick={() => setShowCustom(true)}
            className="rounded-xl border-teal-200 dark:border-teal-800 text-teal-700 dark:text-teal-400 hover:bg-teal-50 dark:hover:bg-teal-950/40"
          >
            <Sliders className="w-4 h-4 mr-2" /> Custom Scenario
          </Button>
        </div>

        {scenarios.length === 0 ? (
          <Card className="p-6 rounded-2xl text-center text-sm text-slate-500 dark:text-slate-400 bg-emerald-50/50 dark:bg-emerald-950/20 border-emerald-200 dark:border-emerald-900">
            No issues detected. Your portfolio is healthy.
          </Card>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3 sm:gap-4" data-testid="scenario-cards-grid">
            {scenarios.map((s) => (
              <ScenarioCard
                key={s.id}
                scenario={s}
                onSimulate={handleSimulateCard}
                simulating={simulating}
                selected={selected?.id === s.id}
              />
            ))}
          </div>
        )}
      </div>

      {/* Saved scenarios */}
      {savedList.length > 0 && (
        <Card className="p-4 sm:p-5 rounded-2xl border-slate-100 dark:border-slate-800 bg-white dark:bg-slate-900" data-testid="saved-scenarios">
          <div className="flex items-center gap-2 mb-3">
            <Bookmark className="w-4 h-4 text-slate-500" strokeWidth={2} />
            <h3 className="text-sm font-semibold text-slate-700 dark:text-slate-300">Saved Scenarios</h3>
            <span className="text-xs text-slate-400">({savedList.length})</span>
          </div>
          <div className="flex flex-wrap gap-2">
            {savedList.map((s) => (
              <div
                key={s.saved_id}
                data-testid={`saved-${s.saved_id}`}
                className="inline-flex items-center gap-2 px-3 py-1.5 rounded-lg border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800 hover:bg-slate-100 dark:hover:bg-slate-700 transition-colors"
              >
                <button
                  onClick={() => handleLoadSaved(s)}
                  className="text-xs font-medium text-slate-700 dark:text-slate-300"
                >
                  {s.name}
                </button>
                <button
                  onClick={() => handleDeleteSaved(s.saved_id)}
                  className="text-slate-400 hover:text-red-500"
                  data-testid={`delete-${s.saved_id}`}
                  aria-label="Delete"
                >
                  <Trash2 className="w-3.5 h-3.5" />
                </button>
              </div>
            ))}
          </div>
        </Card>
      )}

      {/* Pending Plans (applied scenarios awaiting execution) */}
      {pendingPlans.length > 0 && (
        <Card
          data-testid="pending-plans"
          className="p-4 sm:p-5 rounded-2xl border-amber-200 dark:border-amber-900 bg-amber-50/50 dark:bg-amber-950/20"
        >
          <div className="flex items-center gap-2 mb-3">
            <ClipboardList className="w-4 h-4 text-amber-600 dark:text-amber-400" strokeWidth={2} />
            <h3 className="text-sm font-semibold text-amber-900 dark:text-amber-300">
              Your Applied Action Plans
            </h3>
            <span className="text-xs text-amber-600 dark:text-amber-400">({pendingPlans.length} pending)</span>
          </div>
          <div className="space-y-2">
            {pendingPlans.map((p) => {
              const expanded = expandedPlan === p.plan_id;
              const createdDate = new Date(p.created_at).toLocaleString("en-IN", {
                day: "numeric", month: "short", hour: "numeric", minute: "numeric",
              });
              return (
                <div
                  key={p.plan_id}
                  data-testid={`plan-${p.plan_id}`}
                  className="rounded-xl border border-amber-200 dark:border-amber-900 bg-white dark:bg-slate-900 overflow-hidden"
                >
                  <div className="p-3 flex items-center justify-between gap-2">
                    <button
                      onClick={() => setExpandedPlan(expanded ? null : p.plan_id)}
                      className="flex-1 text-left flex items-center gap-2 min-w-0"
                    >
                      {expanded ? <ChevronUp className="w-4 h-4 text-slate-400 flex-shrink-0" /> : <ChevronDown className="w-4 h-4 text-slate-400 flex-shrink-0" />}
                      <div className="min-w-0">
                        <div className="font-medium text-sm text-slate-900 dark:text-white truncate">
                          {p.scenario_id ? p.scenario_id.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase()) : "Custom Plan"}
                        </div>
                        <div className="text-xs text-slate-500 dark:text-slate-400 flex items-center gap-2">
                          <span>{p.actions?.length || 0} actions</span>
                          <span>·</span>
                          <span>{createdDate}</span>
                        </div>
                      </div>
                    </button>
                    <div className="flex items-center gap-1 flex-shrink-0">
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => handleCompletePending(p.plan_id)}
                        data-testid={`complete-${p.plan_id}`}
                        className="text-emerald-600 hover:text-emerald-700 hover:bg-emerald-50 dark:hover:bg-emerald-950/40 h-8 px-2"
                      >
                        <CheckCircle2 className="w-4 h-4" />
                        <span className="sr-only">Mark done</span>
                      </Button>
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => handleDeletePending(p.plan_id)}
                        data-testid={`delete-plan-${p.plan_id}`}
                        className="text-slate-400 hover:text-red-500 hover:bg-red-50 dark:hover:bg-red-950/40 h-8 px-2"
                      >
                        <Trash2 className="w-4 h-4" />
                        <span className="sr-only">Delete</span>
                      </Button>
                    </div>
                  </div>
                  {expanded && p.actions?.length > 0 && (
                    <div className="px-3 pb-3 space-y-1.5 border-t border-amber-100 dark:border-amber-950 pt-3">
                      {p.actions.map((a, i) => (
                        <div key={i} className="flex items-start gap-2 text-xs">
                          <span
                            className={`inline-flex items-center px-1.5 py-0.5 rounded font-bold text-[10px] tracking-wider flex-shrink-0 ${
                              a.action === "REDUCE" ? "bg-amber-100 dark:bg-amber-950 text-amber-700 dark:text-amber-400" :
                              a.action === "EXIT" ? "bg-red-100 dark:bg-red-950 text-red-700 dark:text-red-400" :
                              a.action === "SWITCH" ? "bg-blue-100 dark:bg-blue-950 text-blue-700 dark:text-blue-400" :
                              "bg-emerald-100 dark:bg-emerald-950 text-emerald-700 dark:text-emerald-400"
                            }`}
                          >
                            {a.action}
                          </span>
                          <div className="flex-1 min-w-0">
                            <div className="font-medium text-slate-900 dark:text-white truncate">{a.holding_name}</div>
                            <div className="text-slate-500 dark:text-slate-400">{a.reason}</div>
                          </div>
                          {a.change_amount !== 0 && (
                            <span className={`font-bold flex-shrink-0 ${a.change_amount < 0 ? "text-red-600 dark:text-red-400" : "text-emerald-600 dark:text-emerald-400"}`}>
                              {a.change_amount < 0 ? "−" : "+"}₹{Math.abs(a.change_amount).toLocaleString("en-IN")}
                            </span>
                          )}
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </Card>
      )}

      {/* Simulation panel */}
      <AnimatePresence>
        {result && (
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: 20 }}
            transition={{ duration: 0.25 }}
          >
            <SimulationPanel
              result={result}
              scenario={selected}
              onApply={handleApply}
              onViewPlan={handleViewPlan}
              onSave={openSaveDialog}
              applying={applying}
              saving={saving}
            />
          </motion.div>
        )}
      </AnimatePresence>

      {/* Custom scenario dialog */}
      <CustomScenarioBuilder
        open={showCustom}
        onOpenChange={setShowCustom}
        onRun={handleRunCustom}
        running={simulating}
      />

      {/* Rebalance plan dialog */}
      <RebalancePlanDialog
        open={planOpen}
        onOpenChange={(v) => {
          setPlanOpen(v);
          if (!v) setPlan(null);
        }}
        plan={loadingPlan ? { actions: [], summary: {} } : plan}
        onApply={async () => {
          await handleApply();
          setPlanOpen(false);
        }}
        applying={applying}
      />

      {/* Save scenario dialog */}
      <Dialog open={saveDialogOpen} onOpenChange={setSaveDialogOpen}>
        <DialogContent className="sm:max-w-md rounded-2xl" data-testid="save-scenario-dialog">
          <DialogHeader>
            <DialogTitle>Save Scenario</DialogTitle>
          </DialogHeader>
          <Input
            data-testid="save-scenario-name"
            value={saveName}
            onChange={(e) => setSaveName(e.target.value)}
            placeholder="Give this scenario a name…"
            className="rounded-xl"
          />
          <DialogFooter className="flex-col sm:flex-row gap-2">
            <Button variant="outline" onClick={() => setSaveDialogOpen(false)} className="rounded-xl">
              Cancel
            </Button>
            <Button
              onClick={handleSave}
              disabled={saving || !saveName.trim()}
              data-testid="confirm-save-btn"
              className="bg-teal-600 hover:bg-teal-700 text-white rounded-xl"
            >
              {saving ? "Saving…" : "Save"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
};

export default AICopilotView;
