/**
 * PersonaOnboardingModal — one-time refinement modal for ambiguous personas.
 *
 * Shown when:
 *   - Backend persona confidence is < 0.6, OR
 *   - User has never explicitly accepted a persona, AND
 *   - localStorage doesn't have v2_persona_onboarded
 *
 * Captures the two signals CAS can't infer:
 *   1. NRI status (yes/no)
 *   2. Trader subtype (none / swing / intraday / options)
 *
 * Then POSTs the inferred persona to /api/user/persona to lock it in.
 */
import React, { useState } from "react";
import axios from "axios";
import { Globe, Crosshair, Timer, Activity, X, Check } from "lucide-react";
import { cn } from "@/lib/utils";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

const TRADER_OPTIONS = [
  { id: "none",          icon: Check,     label: "I don't actively trade", desc: "Long-term investor only" },
  { id: "swing",         icon: Activity,  label: "Swing Trader",            desc: "Days to weeks holding period" },
  { id: "intraday",      icon: Timer,     label: "Intraday Trader",         desc: "Buy and sell within the day" },
  { id: "options",       icon: Crosshair, label: "Options Trader",          desc: "F&O strategies" },
];

export default function PersonaOnboardingModal({
  currentPersona,
  onClose,
  onCommit,
}) {
  const [step, setStep] = useState(0);
  const [isNRI, setIsNRI] = useState(null);
  const [traderType, setTraderType] = useState(null);
  const [submitting, setSubmitting] = useState(false);

  // Decide the final persona key from the two answers
  function resolvePersona() {
    if (isNRI) return "nri_investor";
    if (traderType === "swing")    return "swing_trader";
    if (traderType === "intraday") return "intraday_trader";
    if (traderType === "options")  return "options_trader";
    // Fall back to the backend's existing inference
    return currentPersona?.persona || "retail_investor";
  }

  async function commit() {
    setSubmitting(true);
    const chosen = resolvePersona();
    try {
      await axios.post(`${API}/user/persona`, { persona: chosen }, { withCredentials: true });
      localStorage.setItem("v2_persona_onboarded", "1");
      onCommit?.(chosen);
    } catch (e) {
      // Best-effort; still mark onboarded so we don't keep nagging
      localStorage.setItem("v2_persona_onboarded", "1");
      onCommit?.(chosen);
    } finally {
      setSubmitting(false);
    }
  }

  function skip() {
    localStorage.setItem("v2_persona_onboarded", "1");
    onClose?.();
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70 backdrop-blur-sm animate-fadein">
      <div className="relative bg-[#1A1A1A] border border-indigo-500/20 rounded-3xl p-6 sm:p-8 max-w-lg w-full shadow-2xl">
        <button
          onClick={skip}
          className="absolute top-4 right-4 w-8 h-8 rounded-full bg-white/5 hover:bg-white/10 flex items-center justify-center transition-all"
          aria-label="Close"
        >
          <X className="w-4 h-4 text-white/40" />
        </button>

        <div className="mb-6">
          <p className="text-[9px] font-bold text-indigo-400 uppercase tracking-[0.2em] mb-2 font-mono">
            Step {step + 1} of 2
          </p>
          <h2 className="text-2xl font-black text-white tracking-tight">
            {step === 0 ? "Quick question…" : "How do you trade?"}
          </h2>
          <p className="text-sm text-white/40 mt-1">
            {step === 0
              ? "This helps us personalize your dashboard. Takes 10 seconds."
              : "Pick what describes you best — we'll tailor your tools and shortcuts."}
          </p>
        </div>

        {/* Step 0 — NRI status */}
        {step === 0 && (
          <div className="space-y-3">
            <div className="flex items-center gap-3 mb-2">
              <Globe className="w-4 h-4 text-sky-400" />
              <p className="text-sm font-bold text-white">Are you an NRI investor?</p>
            </div>
            {[
              { id: true,  label: "Yes, I'm an NRI", desc: "I invest from outside India" },
              { id: false, label: "No",              desc: "I'm a resident Indian" },
            ].map((opt) => (
              <button
                key={String(opt.id)}
                onClick={() => setIsNRI(opt.id)}
                className={cn(
                  "w-full text-left p-4 rounded-xl border transition-all flex items-center justify-between",
                  isNRI === opt.id
                    ? "bg-sky-500/10 border-sky-500/40"
                    : "bg-white/[0.02] border-white/5 hover:bg-white/5",
                )}
              >
                <div>
                  <p className="text-sm font-bold text-white">{opt.label}</p>
                  <p className="text-[11px] text-white/40">{opt.desc}</p>
                </div>
                {isNRI === opt.id && <Check className="w-4 h-4 text-sky-400" />}
              </button>
            ))}
          </div>
        )}

        {/* Step 1 — Trader subtype */}
        {step === 1 && (
          <div className="space-y-2.5">
            {TRADER_OPTIONS.map((opt) => {
              const Icon = opt.icon;
              return (
                <button
                  key={opt.id}
                  onClick={() => setTraderType(opt.id)}
                  className={cn(
                    "w-full text-left p-4 rounded-xl border transition-all flex items-center gap-3",
                    traderType === opt.id
                      ? "bg-indigo-500/10 border-indigo-500/40"
                      : "bg-white/[0.02] border-white/5 hover:bg-white/5",
                  )}
                >
                  <Icon className={cn("w-4 h-4 shrink-0", traderType === opt.id ? "text-indigo-400" : "text-white/40")} />
                  <div className="flex-1">
                    <p className="text-sm font-bold text-white">{opt.label}</p>
                    <p className="text-[11px] text-white/40">{opt.desc}</p>
                  </div>
                  {traderType === opt.id && <Check className="w-4 h-4 text-indigo-400" />}
                </button>
              );
            })}
          </div>
        )}

        <div className="mt-6 flex items-center justify-between gap-3">
          <button
            onClick={skip}
            className="text-[10px] font-bold text-white/40 hover:text-white/60 uppercase tracking-widest transition-colors"
          >
            Skip
          </button>
          <div className="flex items-center gap-2">
            {step > 0 && (
              <button
                onClick={() => setStep(step - 1)}
                className="px-4 py-2.5 text-xs font-bold text-white/60 hover:text-white bg-white/5 hover:bg-white/10 rounded-xl border border-white/10 uppercase tracking-widest transition-all"
              >
                Back
              </button>
            )}
            <button
              onClick={() => {
                if (step === 0) {
                  if (isNRI === null) return; // require answer
                  setStep(1);
                } else {
                  commit();
                }
              }}
              disabled={(step === 0 && isNRI === null) || (step === 1 && traderType === null) || submitting}
              className="px-5 py-2.5 text-xs font-bold text-white bg-indigo-500 hover:bg-indigo-400 rounded-xl uppercase tracking-widest disabled:opacity-40 disabled:cursor-not-allowed transition-all"
            >
              {submitting ? "Saving…" : step === 0 ? "Next" : "Finish"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

/**
 * Decides whether the modal should render based on persona + localStorage.
 * Use as: `if (shouldShowPersonaOnboarding(persona)) setShowModal(true)`
 */
export function shouldShowPersonaOnboarding(persona) {
  try {
    if (localStorage.getItem("v2_persona_onboarded") === "1") return false;
  } catch (_) { /* ignore */ }
  // Show when confidence is low or persona is missing
  if (!persona) return false;            // wait for load
  if (!persona.persona) return true;     // no persona at all
  if ((persona.confidence ?? 1) < 0.6) return true;
  return false;
}
