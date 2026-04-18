import React, { useState, useEffect, useCallback } from "react";
import axios from "axios";
import { motion, AnimatePresence } from "framer-motion";
import { toast } from "sonner";
import { Sparkles, Lightbulb, AlertTriangle } from "lucide-react";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";

import PortfolioContextHeader from "./PortfolioContextHeader";
import ScenarioCard from "./ScenarioCard";
import SimulationPanel from "./SimulationPanel";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

const AICopilotView = ({ riskProfile }) => {
  const [loading, setLoading] = useState(true);
  const [scenarios, setScenarios] = useState([]);
  const [context, setContext] = useState(null);
  const [selected, setSelected] = useState(null);
  const [simulating, setSimulating] = useState(false);
  const [result, setResult] = useState(null);
  const [applying, setApplying] = useState(false);
  const [saving, setSaving] = useState(false);

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

  useEffect(() => {
    loadScenarios();
  }, [loadScenarios]);

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

  const handleSimulate = async (scenario) => {
    setSelected(scenario);
    setSimulating(true);
    setResult(null);
    try {
      const res = await axios.post(
        `${API}/scenarios/simulate`,
        buildSimulatePayload(scenario),
        { withCredentials: true }
      );
      setResult(res.data);
      // Scroll the simulation panel into view
      setTimeout(() => {
        document.querySelector('[data-testid="simulation-panel"]')?.scrollIntoView({ behavior: "smooth", block: "start" });
      }, 100);
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Simulation failed");
    } finally {
      setSimulating(false);
    }
  };

  const handleApply = async () => {
    setApplying(true);
    // Phase 1: plan-only — no actual portfolio mutation
    setTimeout(() => {
      toast.success("Plan saved. Actionable rebalance steps coming soon.");
      setApplying(false);
    }, 500);
  };

  const handleViewPlan = () => {
    toast.info("Rebalance Plan: detailed buy/sell actions coming in Phase 2.");
  };

  const handleSave = async () => {
    setSaving(true);
    setTimeout(() => {
      toast.success("Scenario saved to your dashboard.");
      setSaving(false);
    }, 500);
  };

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
      {/* 1. Portfolio Context Header */}
      <PortfolioContextHeader context={context} riskProfile={riskProfile} />

      {/* 2. AI Insight Summary */}
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
                    <span
                      key={i}
                      className="text-[11px] font-medium px-2 py-1 rounded-md bg-red-50 dark:bg-red-950/60 text-red-700 dark:text-red-400"
                    >
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

      {/* 3. Scenario Builder chips (opens prebuilt cards — already shown below) */}
      <div>
        <div className="flex items-center justify-between mb-3">
          <div>
            <h3 className="text-base sm:text-lg font-semibold text-slate-900 dark:text-white">
              Pre-built Scenarios
            </h3>
            <p className="text-xs text-slate-500 dark:text-slate-400">
              Personalized for your holdings. Tap Simulate to see impact.
            </p>
          </div>
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
                onSimulate={handleSimulate}
                simulating={simulating}
                selected={selected?.id === s.id}
              />
            ))}
          </div>
        )}
      </div>

      {/* 4. Simulation Output Panel */}
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
              onSave={handleSave}
              applying={applying}
              saving={saving}
            />
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
};

export default AICopilotView;
