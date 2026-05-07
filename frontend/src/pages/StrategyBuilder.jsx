/**
 * StrategyBuilder — multi-step wizard for authoring stock strategies.
 *
 *   Step 1 Universe → Step 2 Strategy → Step 3 Screen
 *                  → Step 4 Backtest → Step 5 Execute
 *
 * State machine:
 *   • universe        : { type, ref }
 *   • templateKey     : string | null
 *   • definition      : full DSL document (initialised from template, editable)
 *   • strategyName    : user-editable
 *   • strategyId      : null until first save (created on first backtest run)
 *   • lastResult      : last backtest response (used by Step 5 export)
 *   • currentStep     : key of step currently shown
 *   • furthestStep    : key of step the user has reached (gates jumps)
 *
 * Persistence: drafts auto-save to localStorage so a refresh doesn't
 * lose work. On strategy save (first backtest run), we mint a real
 * strategy_id and the localStorage draft can be discarded.
 */
import React, { useEffect, useMemo, useState } from "react";
import { Sparkles } from "lucide-react";

import Stepper, { STEPS } from "@/components/strategyBuilder/Stepper";
import StepUniverse from "@/components/strategyBuilder/StepUniverse";
import StepStrategy from "@/components/strategyBuilder/StepStrategy";
import StepScreen from "@/components/strategyBuilder/StepScreen";
import StepBacktest from "@/components/strategyBuilder/StepBacktest";
import StepExecute from "@/components/strategyBuilder/StepExecute";

const DRAFT_KEY = "strategy_builder_draft_v1";


export default function StrategyBuilder() {
  // ── Wizard state ──────────────────────────────────────────────────
  const [universe, setUniverse] = useState({ type: "index", ref: "NIFTY500" });
  const [templateKey, setTemplateKey] = useState(null);
  const [definition, setDefinition] = useState(null);
  const [strategyName, setStrategyName] = useState("");
  const [strategyDescription, setStrategyDescription] = useState("");
  const [strategyId, setStrategyId] = useState(null);
  const [lastResult, setLastResult] = useState(null);
  const [currentStep, setCurrentStep] = useState("universe");
  const [furthestStep, setFurthestStep] = useState("universe");
  const [draftLoaded, setDraftLoaded] = useState(false);

  // Hydrate from localStorage once on mount
  useEffect(() => {
    try {
      const raw = localStorage.getItem(DRAFT_KEY);
      if (raw) {
        const d = JSON.parse(raw);
        if (d.universe) setUniverse(d.universe);
        if (d.templateKey) setTemplateKey(d.templateKey);
        if (d.definition) setDefinition(d.definition);
        if (d.strategyName) setStrategyName(d.strategyName);
        if (d.strategyDescription) setStrategyDescription(d.strategyDescription);
        if (d.currentStep) setCurrentStep(d.currentStep);
        if (d.furthestStep) setFurthestStep(d.furthestStep);
      }
    } catch {
      // ignore corrupt draft
    }
    setDraftLoaded(true);
  }, []);

  // Persist on every change once hydrated
  useEffect(() => {
    if (!draftLoaded) return;
    try {
      localStorage.setItem(DRAFT_KEY, JSON.stringify({
        universe, templateKey, definition,
        strategyName, strategyDescription,
        currentStep, furthestStep,
      }));
    } catch {
      // localStorage may be full / disabled — don't surface
    }
  }, [draftLoaded, universe, templateKey, definition,
      strategyName, strategyDescription, currentStep, furthestStep]);

  // ── Step navigation ───────────────────────────────────────────────
  const stepIdx = useMemo(() => STEPS.findIndex((s) => s.key === currentStep), [currentStep]);
  const advanceTo = (key) => {
    setCurrentStep(key);
    const wantedIdx = STEPS.findIndex((s) => s.key === key);
    const farIdx = STEPS.findIndex((s) => s.key === furthestStep);
    if (wantedIdx > farIdx) setFurthestStep(key);
  };
  const next = () => {
    const nx = STEPS[stepIdx + 1]?.key;
    if (nx) advanceTo(nx);
  };
  const back = () => {
    const pv = STEPS[stepIdx - 1]?.key;
    if (pv) setCurrentStep(pv);
  };

  // ── Step 2 onChange: pick template ────────────────────────────────
  const handlePickTemplate = ({ key, definition: def }) => {
    setTemplateKey(key);
    setDefinition(def);
    if (!strategyName) setStrategyName(def?.name || "My Strategy");
    if (!strategyDescription) setStrategyDescription(def?.description || "");
  };

  // When the universe changes after a template is picked, splice it into
  // the working definition so backtest uses the right pool.
  useEffect(() => {
    if (definition && universe?.ref) {
      setDefinition((prev) => prev ? { ...prev, universe } : prev);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [universe?.type, universe?.ref]);

  // ── Reset draft (after explicit save) ─────────────────────────────
  const resetDraft = () => {
    try { localStorage.removeItem(DRAFT_KEY); } catch { /* ignore */ }
  };

  return (
    <div className="p-4 sm:p-6 max-w-6xl mx-auto" data-testid="strategy-builder-page">
      {/* Header */}
      <div className="flex items-start gap-3 mb-6">
        <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-amber-400 to-rose-500 flex items-center justify-center text-white flex-shrink-0">
          <Sparkles className="w-5 h-5" strokeWidth={2} />
        </div>
        <div className="flex-1">
          <h1 className="text-2xl font-bold text-slate-900 dark:text-white tracking-tight">
            Strategy Builder
          </h1>
          <p className="text-[12px] text-slate-500 dark:text-slate-400 mt-0.5">
            Universes, strategies, screening, backtest, and execution in one flow.
          </p>
        </div>
        <span className="hidden sm:inline-flex items-center gap-1 text-[10px] uppercase tracking-wider font-bold px-2 py-1 rounded bg-amber-100 text-amber-700 border border-amber-200 self-start">
          <Sparkles className="w-3 h-3" /> Phase 1
        </span>
      </div>

      {/* Stepper */}
      <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-700 rounded-2xl p-4 sm:p-5 mb-5">
        <Stepper currentStep={currentStep} furthestStep={furthestStep} onJump={advanceTo} />
      </div>

      {/* Active step */}
      <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-700 rounded-2xl p-4 sm:p-6">
        {currentStep === "universe" && (
          <StepUniverse value={universe} onChange={setUniverse} onNext={next} />
        )}
        {currentStep === "strategy" && (
          <StepStrategy
            universe={universe}
            value={{ key: templateKey, definition }}
            onChange={handlePickTemplate}
            onNext={next} onBack={back}
          />
        )}
        {currentStep === "screen" && (
          <StepScreen
            definition={definition} onChange={setDefinition}
            onNext={next} onBack={back}
          />
        )}
        {currentStep === "backtest" && (
          <StepBacktest
            strategyName={strategyName}
            strategyDescription={strategyDescription}
            definition={definition}
            strategyId={strategyId}
            setStrategyId={setStrategyId}
            onNext={(res) => { if (res) setLastResult(res); next(); }}
            onBack={back}
          />
        )}
        {currentStep === "execute" && (
          <StepExecute
            strategyName={strategyName} setStrategyName={setStrategyName}
            strategyDescription={strategyDescription} setStrategyDescription={setStrategyDescription}
            strategyId={strategyId}
            definition={definition}
            lastTrades={lastResult?.trades || []}
            onBack={back}
            onSaved={resetDraft}
          />
        )}
      </div>
    </div>
  );
}
