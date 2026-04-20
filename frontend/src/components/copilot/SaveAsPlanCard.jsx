import React, { useState } from "react";
import axios from "axios";
import { Wrench, Loader2, Check, ArrowRight, Sparkles } from "lucide-react";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
const API = `${BACKEND_URL}/api`;

/**
 * CTA card injected at the end of high-intent assistant replies.
 * Lets the user one-click generate an Action Plan and jump to the Plan Board.
 *
 * Only renders when the response looks like it recommends actions (via
 * `shouldShowSavePlan` heuristics).
 */
export const shouldShowSavePlan = (content, userQuery) => {
  const src = ((content || "") + " " + (userQuery || "")).toLowerCase();
  if (!src.trim()) return false;
  const intent = [
    "fix my portfolio",
    "top 3 actions",
    "rebalance",
    "exit",
    "switch to direct",
    "cost leak",
    "overlap",
    "concentration",
    "action plan",
    "underperform",
  ];
  return intent.some((k) => src.includes(k));
};

const SaveAsPlanCard = ({ onNavigateToPlanBoard }) => {
  const [status, setStatus] = useState("idle"); // idle | loading | success | error
  const [error, setError] = useState("");
  const [plan, setPlan] = useState(null);

  const handleGenerate = async () => {
    setStatus("loading");
    setError("");
    try {
      const res = await axios.post(`${API}/plans/generate`, {}, { withCredentials: true });
      setPlan(res.data?.plan || null);
      setStatus("success");
    } catch (e) {
      setError(e?.response?.data?.detail || "Failed to generate plan");
      setStatus("error");
    }
  };

  const handleGoToBoard = () => {
    if (onNavigateToPlanBoard) {
      onNavigateToPlanBoard();
    } else {
      // Hash-based fallback (Dashboard.js reads location.hash)
      window.location.hash = "plan_board";
    }
  };

  const actionCount = plan?.actions?.length || 0;
  const taxImpact = plan?.tax_impact?.total_tax_liability || 0;

  return (
    <div
      data-testid="copilot-save-as-plan"
      className="mt-3 rounded-xl border-2 border-emerald-200 dark:border-emerald-900/60 bg-gradient-to-br from-emerald-50 via-white to-emerald-50 dark:from-emerald-950/30 dark:via-slate-900 dark:to-emerald-950/20 p-3"
    >
      <div className="flex items-start gap-3">
        <div className="w-9 h-9 rounded-lg bg-gradient-to-br from-emerald-500 to-emerald-700 flex items-center justify-center flex-shrink-0 shadow-sm">
          <Sparkles className="w-4 h-4 text-white" strokeWidth={2} />
        </div>
        <div className="flex-1 min-w-0">
          <p className="text-sm font-bold text-emerald-900 dark:text-emerald-200">
            Turn this into a trackable plan
          </p>
          <p className="text-[11px] text-emerald-700 dark:text-emerald-400/80 mt-0.5">
            We'll create a Plan Board with these actions, estimated tax, and fund replacements.
          </p>

          {status === "idle" && (
            <button
              data-testid="copilot-save-as-plan-btn"
              onClick={handleGenerate}
              className="mt-2.5 inline-flex items-center gap-1.5 text-xs font-semibold px-3 py-1.5 rounded-lg bg-emerald-600 hover:bg-emerald-700 text-white transition-colors shadow-sm"
            >
              <Wrench className="w-3.5 h-3.5" strokeWidth={2} />
              Save as Plan
              <ArrowRight className="w-3 h-3" strokeWidth={2} />
            </button>
          )}

          {status === "loading" && (
            <div className="mt-2.5 inline-flex items-center gap-2 text-xs font-medium px-3 py-1.5 rounded-lg bg-white dark:bg-slate-800 text-emerald-700 dark:text-emerald-300 border border-emerald-200 dark:border-emerald-800">
              <Loader2 className="w-3.5 h-3.5 animate-spin" />
              Generating plan…
            </div>
          )}

          {status === "success" && plan && (
            <div className="mt-2.5 space-y-2">
              <div className="flex items-center gap-2 flex-wrap">
                <span className="inline-flex items-center gap-1 text-[10px] font-bold uppercase tracking-wider px-1.5 py-0.5 rounded bg-emerald-100 dark:bg-emerald-900/40 text-emerald-700 dark:text-emerald-300">
                  <Check className="w-3 h-3" strokeWidth={2.5} />
                  Plan ready
                </span>
                <span className="text-[11px] font-semibold text-slate-700 dark:text-slate-200 tabular-nums">
                  {actionCount} actions
                </span>
                {taxImpact > 0 && (
                  <span className="text-[11px] text-slate-500 dark:text-slate-400 tabular-nums">
                    · est. tax ₹{Math.round(taxImpact / 1000)}k
                  </span>
                )}
              </div>
              <button
                data-testid="copilot-goto-plan-board-btn"
                onClick={handleGoToBoard}
                className="inline-flex items-center gap-1.5 text-xs font-semibold px-3 py-1.5 rounded-lg bg-emerald-600 hover:bg-emerald-700 text-white transition-colors shadow-sm"
              >
                Open Plan Board
                <ArrowRight className="w-3 h-3" strokeWidth={2} />
              </button>
            </div>
          )}

          {status === "error" && (
            <div className="mt-2.5 space-y-1.5">
              <p className="text-[11px] text-red-600 dark:text-red-400">{error}</p>
              <button
                onClick={handleGenerate}
                className="text-[11px] font-semibold text-emerald-700 dark:text-emerald-300 hover:underline"
              >
                Try again
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

export default SaveAsPlanCard;
