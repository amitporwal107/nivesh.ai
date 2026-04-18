import React from "react";
import { Card } from "@/components/ui/card";
import { AlertTriangle, Shield, PieChart, TrendingUp } from "lucide-react";

const StatPill = ({ label, value, tone = "neutral", icon: Icon, testId }) => {
  const tones = {
    neutral: "bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-300",
    warn: "bg-amber-50 dark:bg-amber-950/40 text-amber-700 dark:text-amber-400 border border-amber-200 dark:border-amber-900",
    danger: "bg-red-50 dark:bg-red-950/40 text-red-700 dark:text-red-400 border border-red-200 dark:border-red-900",
    good: "bg-emerald-50 dark:bg-emerald-950/40 text-emerald-700 dark:text-emerald-400 border border-emerald-200 dark:border-emerald-900",
  };
  return (
    <div
      data-testid={testId}
      className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs font-medium ${tones[tone]}`}
    >
      {Icon && <Icon className="w-3.5 h-3.5" strokeWidth={2} />}
      <span className="uppercase tracking-wide text-[10px] font-bold opacity-70">{label}</span>
      <span>{value}</span>
    </div>
  );
};

const PortfolioContextHeader = ({ context, riskProfile }) => {
  if (!context) return null;

  const { equity_pct, debt_pct, top_amc, top_amc_pct, annual_cost_leak, holdings_count } = context;
  const issues = [];
  if (equity_pct > 80) issues.push({ icon: TrendingUp, text: "High equity exposure", tone: "warn" });
  if (debt_pct < 5) issues.push({ icon: Shield, text: "No debt allocation", tone: "danger" });
  if (top_amc_pct > 30) issues.push({ icon: PieChart, text: `High ${top_amc} concentration`, tone: "warn" });
  if (annual_cost_leak > 10000) issues.push({ icon: AlertTriangle, text: `₹${Math.round(annual_cost_leak / 1000)}K/yr cost leak`, tone: "danger" });

  return (
    <Card
      data-testid="portfolio-context-header"
      className="p-4 sm:p-5 rounded-2xl border-slate-100 dark:border-slate-800 bg-gradient-to-br from-slate-50 to-white dark:from-slate-900 dark:to-slate-950"
    >
      <div className="flex flex-col sm:flex-row sm:items-start sm:justify-between gap-3">
        <div>
          <div className="text-[10px] font-bold tracking-[0.15em] uppercase text-slate-400 mb-2">
            Portfolio Snapshot
          </div>
          <div className="flex flex-wrap gap-1.5">
            <StatPill label="Risk" value={riskProfile || "Not set"} tone="neutral" testId="ctx-risk-profile" />
            <StatPill
              label="Equity"
              value={`${equity_pct}%`}
              tone={equity_pct > 80 ? "warn" : "neutral"}
              testId="ctx-equity"
            />
            <StatPill
              label="Debt"
              value={`${debt_pct}%`}
              tone={debt_pct < 5 ? "danger" : "neutral"}
              testId="ctx-debt"
            />
            {top_amc && (
              <StatPill
                label={`Top: ${top_amc}`}
                value={`${top_amc_pct}%`}
                tone={top_amc_pct > 30 ? "warn" : "neutral"}
                testId="ctx-top-amc"
              />
            )}
            <StatPill label="Holdings" value={holdings_count} tone="neutral" testId="ctx-holdings" />
          </div>
        </div>
      </div>

      {issues.length > 0 && (
        <div className="mt-4 pt-4 border-t border-slate-100 dark:border-slate-800">
          <div className="text-[10px] font-bold tracking-[0.15em] uppercase text-slate-400 mb-2">
            Detected Issues
          </div>
          <div className="flex flex-wrap gap-1.5" data-testid="ctx-issues">
            {issues.map((issue, i) => (
              <div
                key={i}
                className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs font-medium ${
                  issue.tone === "danger"
                    ? "bg-red-50 dark:bg-red-950/40 text-red-700 dark:text-red-400"
                    : "bg-amber-50 dark:bg-amber-950/40 text-amber-700 dark:text-amber-400"
                }`}
              >
                <issue.icon className="w-3.5 h-3.5" strokeWidth={2} />
                {issue.text}
              </div>
            ))}
          </div>
        </div>
      )}
    </Card>
  );
};

export default PortfolioContextHeader;
