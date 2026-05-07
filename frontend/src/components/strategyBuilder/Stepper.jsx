/**
 * Stepper — 5-step header rail (Universe → Strategy → Screen → Backtest → Execute).
 *
 * Steps are clickable when they are ≤ furthest reached step (so users can
 * go back without losing state) but disabled when they are ahead of progress.
 */
import React from "react";
import { Globe2, Settings, Search, FlaskConical, Zap, Check } from "lucide-react";

export const STEPS = [
  { key: "universe", label: "Universe",  icon: Globe2 },
  { key: "strategy", label: "Strategy",  icon: Settings },
  { key: "screen",   label: "Screen",    icon: Search },
  { key: "backtest", label: "Backtest",  icon: FlaskConical },
  { key: "execute",  label: "Execute",   icon: Zap },
];

export default function Stepper({ currentStep, furthestStep, onJump }) {
  const currentIdx = STEPS.findIndex((s) => s.key === currentStep);
  const furthestIdx = Math.max(currentIdx,
    STEPS.findIndex((s) => s.key === furthestStep));

  return (
    <div className="relative" data-testid="strategy-stepper">
      <div className="flex items-center justify-between gap-1">
        {STEPS.map((step, i) => {
          const Icon = step.icon;
          const reachable = i <= furthestIdx;
          const active = i === currentIdx;
          const done = i < furthestIdx || (i === furthestIdx && currentIdx > i);
          return (
            <React.Fragment key={step.key}>
              <button
                type="button"
                disabled={!reachable}
                onClick={() => reachable && onJump?.(step.key)}
                className={`relative flex flex-col items-center gap-1.5 flex-1 min-w-0 ${
                  reachable ? "cursor-pointer" : "cursor-not-allowed opacity-40"
                }`}
                data-testid={`step-${step.key}`}
              >
                <div
                  className={`w-9 h-9 rounded-full flex items-center justify-center border-2 transition-colors ${
                    active
                      ? "bg-emerald-500 border-emerald-500 text-white shadow-md shadow-emerald-500/30"
                      : done
                        ? "bg-emerald-50 border-emerald-300 text-emerald-700 dark:bg-emerald-900/40 dark:border-emerald-600 dark:text-emerald-300"
                        : "bg-white border-slate-200 text-slate-400 dark:bg-slate-900 dark:border-slate-700"
                  }`}
                >
                  {done ? <Check className="w-4 h-4" /> : <Icon className="w-4 h-4" />}
                </div>
                <div className={`text-[11px] font-medium ${
                  active ? "text-slate-900 dark:text-white"
                    : done ? "text-emerald-700 dark:text-emerald-400"
                    : "text-slate-400 dark:text-slate-500"
                }`}>
                  Step {i + 1}/5
                </div>
                <div className={`text-[12px] ${
                  active ? "font-semibold text-slate-900 dark:text-white"
                    : "text-slate-500 dark:text-slate-400"
                }`}>
                  {step.label}
                </div>
              </button>
              {i < STEPS.length - 1 && (
                <div
                  className={`flex-shrink-0 h-0.5 w-6 sm:w-12 -mt-8 transition-colors ${
                    i < furthestIdx ? "bg-emerald-300 dark:bg-emerald-700" : "bg-slate-200 dark:bg-slate-800"
                  }`}
                />
              )}
            </React.Fragment>
          );
        })}
      </div>
    </div>
  );
}
