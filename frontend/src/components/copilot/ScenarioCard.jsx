import React from "react";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Shield, PieChart, PiggyBank, Sparkles, TrendingDown, ArrowRight, CheckCircle2 } from "lucide-react";

const ICON_MAP = {
  shield: Shield,
  pie: PieChart,
  savings: PiggyBank,
  broom: Sparkles,
  "trending-down": TrendingDown,
};

const CATEGORY_STYLES = {
  risk: {
    ring: "border-amber-200 dark:border-amber-900",
    iconBg: "bg-amber-50 dark:bg-amber-950/60 text-amber-600 dark:text-amber-400",
    chip: "bg-amber-100 dark:bg-amber-950 text-amber-700 dark:text-amber-400",
    label: "Risk fix",
  },
  cost: {
    ring: "border-red-200 dark:border-red-900",
    iconBg: "bg-red-50 dark:bg-red-950/60 text-red-600 dark:text-red-400",
    chip: "bg-red-100 dark:bg-red-950 text-red-700 dark:text-red-400",
    label: "Cost fix",
  },
  allocation: {
    ring: "border-blue-200 dark:border-blue-900",
    iconBg: "bg-blue-50 dark:bg-blue-950/60 text-blue-600 dark:text-blue-400",
    chip: "bg-blue-100 dark:bg-blue-950 text-blue-700 dark:text-blue-400",
    label: "Allocation",
  },
  optimization: {
    ring: "border-emerald-200 dark:border-emerald-900",
    iconBg: "bg-emerald-50 dark:bg-emerald-950/60 text-emerald-600 dark:text-emerald-400",
    chip: "bg-emerald-100 dark:bg-emerald-950 text-emerald-700 dark:text-emerald-400",
    label: "Optimization",
  },
};

const ScenarioCard = ({ scenario, onSimulate, simulating, selected }) => {
  const Icon = ICON_MAP[scenario.icon] || Shield;
  const style = CATEGORY_STYLES[scenario.category] || CATEGORY_STYLES.optimization;
  const testIdBase = `scenario-${scenario.id}`;

  return (
    <Card
      data-testid={testIdBase}
      className={`p-4 sm:p-5 rounded-2xl border transition-all bg-white dark:bg-slate-900 ${style.ring} ${
        selected ? "ring-2 ring-offset-2 ring-teal-500 dark:ring-offset-slate-950" : "hover:shadow-md"
      }`}
    >
      <div className="flex items-start justify-between gap-3 mb-3">
        <div className="flex items-center gap-3 min-w-0 flex-1">
          <div className={`w-10 h-10 rounded-xl flex items-center justify-center flex-shrink-0 ${style.iconBg}`}>
            <Icon className="w-5 h-5" strokeWidth={2} />
          </div>
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2 flex-wrap">
              <span className={`text-[10px] font-bold uppercase tracking-wider px-2 py-0.5 rounded ${style.chip}`}>
                {style.label}
              </span>
              {scenario.recommended && (
                <span className="inline-flex items-center gap-1 text-[10px] font-bold uppercase tracking-wider px-2 py-0.5 rounded bg-teal-100 dark:bg-teal-950 text-teal-700 dark:text-teal-400">
                  <CheckCircle2 className="w-3 h-3" strokeWidth={2.5} /> Recommended
                </span>
              )}
            </div>
            <h3 className="mt-1.5 font-semibold text-slate-900 dark:text-white text-sm sm:text-base truncate">
              {scenario.title}
            </h3>
            <p className="text-xs text-slate-500 dark:text-slate-400 mt-0.5">{scenario.subtitle}</p>
          </div>
        </div>
      </div>

      <div className="flex items-center gap-2 mb-3 text-xs">
        <span className="text-slate-400">Current</span>
        <span className="font-semibold text-slate-700 dark:text-slate-300">{scenario.current_value}</span>
        <ArrowRight className="w-3 h-3 text-slate-400" />
        <span className="text-slate-400">Target</span>
        <span className="font-semibold text-teal-600 dark:text-teal-400">{scenario.target_value}</span>
      </div>

      <div className="flex flex-wrap gap-1.5 mb-3" data-testid={`${testIdBase}-impact`}>
        {Object.entries(scenario.impact).map(([k, v]) => {
          const isNum = typeof v === "number";
          const positive = isNum ? v > 0 : v === "up" || v === "+1.0%";
          const negative = isNum ? v < 0 : v === "down";
          const tone = negative && k === "risk"
            ? "bg-emerald-50 dark:bg-emerald-950/60 text-emerald-700 dark:text-emerald-400"
            : positive
            ? "bg-emerald-50 dark:bg-emerald-950/60 text-emerald-700 dark:text-emerald-400"
            : negative
            ? "bg-red-50 dark:bg-red-950/60 text-red-700 dark:text-red-400"
            : "bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-400";
          const formatVal = () => {
            if (k === "cost_saving") return `₹${v}/yr saved`;
            if (isNum) return `${v > 0 ? "+" : ""}${v}%`;
            return v;
          };
          return (
            <span key={k} className={`text-[11px] font-medium px-2 py-1 rounded-md ${tone}`}>
              {k.replace(/_/g, " ")}: {formatVal()}
            </span>
          );
        })}
      </div>

      <p className="text-xs text-slate-500 dark:text-slate-400 leading-relaxed mb-4">{scenario.reason}</p>

      <Button
        data-testid={`${testIdBase}-simulate`}
        onClick={() => onSimulate(scenario)}
        disabled={simulating}
        className="w-full bg-slate-900 hover:bg-slate-800 dark:bg-white dark:text-slate-900 dark:hover:bg-slate-100 text-white rounded-xl text-sm"
      >
        {simulating && selected ? "Simulating…" : "Simulate"}
        {!(simulating && selected) && <ArrowRight className="w-4 h-4 ml-1.5" />}
      </Button>
    </Card>
  );
};

export default ScenarioCard;
