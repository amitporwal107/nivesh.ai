import React, { useState } from "react";
import {
  Calendar, CheckCircle2, TrendingDown, TrendingUp, Sparkles,
  ChevronDown, ChevronUp, ThumbsUp, ThumbsDown, Minimize2, Maximize2,
  Play, AlertTriangle, RefreshCw, ArrowRight, Banknote, Info, LayoutGrid, List
} from "lucide-react";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import { Textarea } from "@/components/ui/textarea";
import { toast } from "sonner";
import axios from "axios";
import V3ScoreBadges from "./V3ScoreBadges";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
const API = `${BACKEND_URL}/api`;

// ── helpers ────────────────────────────────────────────────────────────────

const fmt = (n) =>
  new Intl.NumberFormat("en-IN", {
    style: "currency",
    currency: "INR",
    maximumFractionDigits: 0,
    notation: "compact",
  }).format(n);

const fmtFull = (n) =>
  "₹" + new Intl.NumberFormat("en-IN", { maximumFractionDigits: 0 }).format(n);

const fmtDate = (d) =>
  new Date(d).toLocaleDateString("en-IN", {
    day: "numeric",
    month: "short",
    year: "numeric",
  });

const RULE_MAP = {
  REGULAR_DIRECT_DUPLICATE: {
    label: "Rule 1 · Regular → Direct",
    className: "bg-indigo-50 text-indigo-700 border-indigo-200",
    tooltip: "Same fund exists as Direct plan. Exiting the Regular plan saves on expense ratio.",
  },
  COST_LEAK_SWITCH_TO_DIRECT: {
    label: "Rule 6 · Cost leak switch",
    className: "bg-amber-50 text-amber-700 border-amber-200",
    tooltip: "Switching to Direct saves ₹10K+/year in expense ratio.",
  },
  AMC_CONCENTRATION_EXIT: {
    label: "Rule 2 · AMC concentration",
    className: "bg-rose-50 text-rose-700 border-rose-200",
    tooltip: "This AMC exceeds the 15% limit. Exiting the highest exit-score fund to rebalance.",
  },
  UNDERPERFORMER_REPLACEMENT: {
    label: "Rule 3 · Underperformer swap",
    className: "bg-orange-50 text-orange-700 border-orange-200",
    tooltip: "Fund underperforms benchmark. Replacing with highest-rated fund in same category.",
  },
  OVERLAP_CONSOLIDATION: {
    label: "Rule 4 · Overlap consolidation",
    className: "bg-purple-50 text-purple-700 border-purple-200",
    tooltip: ">60% stock overlap detected. Exiting the higher exit-score duplicate.",
  },
  ALLOCATION_GAP: {
    label: "Rule 5 · Debt allocation gap",
    className: "bg-sky-50 text-sky-700 border-sky-200",
    tooltip: "Portfolio lacks debt. Adding a debt fund improves risk management.",
  },
};

const getRuleBadge = (action) => {
  const codes = action.reason_codes || [];
  for (const c of codes) if (RULE_MAP[c]) return { code: c, ...RULE_MAP[c] };
  return null;
};

const statusColors = {
  COMPLETED:   "text-emerald-600 bg-emerald-50 border-emerald-200",
  IN_PROGRESS: "text-blue-600 bg-blue-50 border-blue-200",
  SKIPPED:     "text-slate-600 bg-slate-100 border-slate-200",
  PENDING:     "text-amber-600 bg-amber-50 border-amber-200",
};
const statusLabel = { COMPLETED: "Done", IN_PROGRESS: "In Progress", SKIPPED: "Skipped", PENDING: "Pending" };

// ── Rebalancing strip for EXIT actions ─────────────────────────────────────

const RebalancingStrip = ({ exitAmount, addActions, taxImpact }) => {
  const netProceeds = taxImpact?.post_tax_proceeds ?? exitAmount;
  const totalExitInPlan = addActions.reduce((s, a) => s + (a.amount || 0), 0);

  if (!addActions.length) return null;

  return (
    <div className="mt-3 rounded-xl border border-emerald-200 bg-gradient-to-br from-emerald-50 to-teal-50 p-3">
      <div className="flex items-center gap-2 mb-2">
        <Banknote className="w-4 h-4 text-emerald-600 flex-shrink-0" />
        <span className="text-xs font-bold text-emerald-800 uppercase tracking-wide">
          Freed Capital Rebalancing Plan
        </span>
      </div>

      <p className="text-xs text-slate-700 mb-2">
        After this exit, <span className="font-semibold text-emerald-700">{fmtFull(netProceeds)}</span> in
        post-tax proceeds will be available. Based on your portfolio needs, this capital is earmarked for:
      </p>

      <div className="space-y-1.5">
        {addActions.map((a, i) => {
          const pct = totalExitInPlan > 0 ? Math.round((a.amount / totalExitInPlan) * 100) : 0;
          const rule = getRuleBadge(a);
          return (
            <div key={i} className="flex items-start gap-2 bg-white/60 rounded-lg px-2.5 py-1.5 border border-emerald-100">
              <ArrowRight className="w-3.5 h-3.5 text-emerald-600 flex-shrink-0 mt-0.5" />
              <div className="flex-1 min-w-0">
                <div className="flex items-center justify-between gap-2">
                  <span className="text-xs font-semibold text-slate-800 leading-tight">
                    {a.asset_name}
                  </span>
                  <span className="text-xs font-bold text-emerald-700 whitespace-nowrap">
                    {fmt(a.amount)} ({pct}%)
                  </span>
                </div>
                {rule && (
                  <span className={`mt-0.5 inline-block px-1.5 py-0.5 rounded-full text-[9px] font-semibold border ${rule.className}`}>
                    {rule.label}
                  </span>
                )}
              </div>
            </div>
          );
        })}
      </div>

      <div className="mt-2 flex items-start gap-1.5 text-[10px] text-slate-500">
        <Info className="w-3 h-3 flex-shrink-0 mt-0.5" />
        <span>
          Rebalancing allocations are based on V3 quality scoring, your risk profile, and portfolio gap analysis.
          Direct plans are preferred to minimise expense ratio.
        </span>
      </div>
    </div>
  );
};

// ── Expanded action detail panel ────────────────────────────────────────────

const ActionDetailPanel = ({ action, planId, addActions, onRefresh }) => {
  const [updatingAction, setUpdatingAction] = useState(null);
  const [feedbackState, setFeedbackState] = useState(null);

  const handleStatus = async (newStatus) => {
    try {
      setUpdatingAction(newStatus);
      await axios.patch(
        `${API}/plans/${planId}/actions/${action.action_id}`,
        { status: newStatus },
        { withCredentials: true }
      );
      toast.success(`Marked as ${statusLabel[newStatus]}`);
      if (onRefresh) onRefresh();
    } catch {
      toast.error("Failed to update status");
    } finally {
      setUpdatingAction(null);
    }
  };

  const handleFeedback = async (useful) => {
    const comment = feedbackState?.comment || "";
    try {
      await axios.patch(
        `${API}/plans/${planId}/actions/${action.action_id}/feedback`,
        { useful, comment },
        { withCredentials: true }
      );
      toast.success("Feedback submitted!");
      setFeedbackState((p) => ({ ...p, submitted: true, useful }));
      if (onRefresh) onRefresh();
    } catch {
      toast.error("Failed to submit feedback");
    }
  };

  const cur = action.status || "PENDING";

  return (
    <div className="mt-2 space-y-3 animate-in slide-in-from-top-1 duration-200">
      {/* Full fund name */}
      <div className="rounded-lg bg-slate-50 border border-slate-200 px-3 py-2">
        <p className="text-[10px] font-semibold text-slate-500 uppercase tracking-wider mb-0.5">Fund / Asset</p>
        <p className="text-sm font-semibold text-slate-900 leading-snug">{action.asset_name}</p>
        <p className="text-xs text-slate-500 mt-0.5">Priority {action.priority}</p>
      </div>

      {/* Status controls */}
      <div className="rounded-lg border border-slate-200 bg-white px-3 py-2.5">
        <p className="text-[10px] font-semibold text-slate-500 uppercase tracking-wider mb-2">Update Status</p>
        <div className="flex gap-2 flex-wrap">
          {["IN_PROGRESS", "COMPLETED", "SKIPPED"].map((s) => (
            <button
              key={s}
              onClick={() => handleStatus(s)}
              disabled={updatingAction !== null}
              className={`flex-1 min-w-[80px] flex items-center justify-center gap-1 text-xs font-semibold px-3 py-1.5 rounded-full border transition-all
                ${cur === s
                  ? s === "COMPLETED" ? "bg-emerald-600 text-white border-emerald-600"
                  : s === "IN_PROGRESS" ? "bg-blue-600 text-white border-blue-600"
                  : "bg-slate-600 text-white border-slate-600"
                  : "bg-white text-slate-600 border-slate-300 hover:border-slate-400"
                }`}
              data-testid={`status-btn-${s.toLowerCase()}`}
            >
              {s === "IN_PROGRESS" && <Play className="w-2.5 h-2.5" />}
              {s === "COMPLETED" && <CheckCircle2 className="w-2.5 h-2.5" />}
              {s === "SKIPPED" && <span className="text-[10px]">✕</span>}
              {updatingAction === s ? "…" : statusLabel[s]}
            </button>
          ))}
        </div>
      </div>

      {/* Tax impact — EXIT only */}
      {action.type === "EXIT" && action.tax_impact && (
        <div className="rounded-lg border border-slate-200 bg-white px-3 py-2.5">
          <p className="text-[10px] font-semibold text-slate-500 uppercase tracking-wider mb-2 flex items-center gap-1">
            <span>Tax Calculation</span>
            <span className={`ml-auto px-2 py-0.5 rounded-full text-[9px] font-bold ${
              action.tax_impact.is_long_term ? "bg-blue-50 text-blue-600 border border-blue-200" : "bg-amber-50 text-amber-600 border border-amber-200"
            }`}>
              {action.tax_impact.is_long_term ? "LTCG 12.5%" : "STCG 20%"}
            </span>
          </p>
          <div className="space-y-1 text-xs">
            {[
              ["Current Value",    fmtFull(action.amount)],
              ["Invested Amount",  fmtFull((action.amount || 0) - (action.tax_impact.capital_gain || 0))],
              ["Capital Gain",     fmtFull(action.tax_impact.capital_gain || 0), "text-emerald-600"],
              ["Holding Period",   `${action.tax_impact.holding_period_days || 0} days (${((action.tax_impact.holding_period_days || 0)/365).toFixed(1)} yrs)`],
              ["Tax Liability",    fmtFull(action.tax_impact.tax_liability || 0), "text-red-600 font-semibold"],
              ["Post-tax Proceeds",fmtFull(action.tax_impact.post_tax_proceeds || 0), "text-emerald-600 font-bold"],
            ].map(([label, val, cls]) => (
              <div key={label} className="flex justify-between border-t border-slate-100 pt-1 first:border-0 first:pt-0">
                <span className="text-slate-500">{label}</span>
                <span className={cls || "font-medium text-slate-800"}>{val}</span>
              </div>
            ))}
          </div>
          <p className="mt-2 text-[10px] text-amber-700 bg-amber-50 border border-amber-200 rounded px-2 py-1">
            ⚠ Tax estimates are indicative. Actual liability depends on your income slab and total annual gains.
          </p>
          {action.tax_impact.exit_warning && (
            <p className="mt-1 text-[10px] text-red-700 bg-red-50 border border-red-200 rounded px-2 py-1">
              ⚠ {action.tax_impact.exit_warning}
            </p>
          )}
        </div>
      )}

      {/* Rebalancing strip — EXIT only */}
      {action.type === "EXIT" && addActions.length > 0 && (
        <RebalancingStrip
          exitAmount={action.amount}
          addActions={addActions}
          taxImpact={action.tax_impact}
        />
      )}

      {/* Fund details — ADD only */}
      {action.type === "ADD" && action.fund_details && (
        <div className="rounded-lg border border-slate-200 bg-white px-3 py-2.5 space-y-1 text-xs">
          <p className="text-[10px] font-semibold text-slate-500 uppercase tracking-wider mb-2">Fund Details</p>
          {[
            ["Fund Type",    action.fund_details.fund_type],
            ["Expense Ratio",`${action.fund_details.expense_ratio}%`],
            ["Rating",       action.fund_details.rating],
            ["3Y Returns",   action.fund_details.returns_3y, "text-emerald-600"],
          ].map(([l, v, cls]) => v ? (
            <div key={l} className="flex justify-between">
              <span className="text-slate-500">{l}</span>
              <span className={cls || "font-medium text-slate-800"}>{v}</span>
            </div>
          ) : null)}
        </div>
      )}

      {/* Reason text */}
      <div className="rounded-lg border border-slate-100 bg-slate-50 px-3 py-2">
        <p className="text-[10px] font-semibold text-slate-500 uppercase tracking-wider mb-1">Why this action?</p>
        <p className="text-xs text-slate-700 leading-relaxed">{action.reason_text}</p>
      </div>

      {/* V3 scores */}
      <V3ScoreBadges scores={action.v3_scores} guardrails={action.v3_guardrail_reasons} />

      {action.switch_score != null && (
        <p className="text-[11px] text-slate-600">
          <span className="font-semibold text-slate-800">Switch score:</span>{" "}
          <span className="text-emerald-700 tabular-nums">{Number(action.switch_score).toFixed(1)}</span>
          <span className="text-slate-400"> (threshold 2.0)</span>
        </p>
      )}

      {/* Feedback */}
      {!(feedbackState?.submitted || action.feedback) ? (
        <div className="rounded-lg border border-blue-200 bg-blue-50 px-3 py-2.5">
          <p className="text-xs font-semibold text-slate-700 mb-2">Was this recommendation useful?</p>
          <div className="flex gap-2 mb-2">
            <Button size="sm" variant="outline" onClick={() => handleFeedback(true)}
              className="flex-1 bg-white hover:bg-emerald-50 text-xs">
              <ThumbsUp className="w-3 h-3 mr-1" /> Useful
            </Button>
            <Button size="sm" variant="outline" onClick={() => handleFeedback(false)}
              className="flex-1 bg-white hover:bg-red-50 text-xs">
              <ThumbsDown className="w-3 h-3 mr-1" /> Not useful
            </Button>
          </div>
          <Textarea
            placeholder="Optional feedback…"
            className="text-xs h-14 resize-none"
            value={feedbackState?.comment || ""}
            onChange={(e) => setFeedbackState((p) => ({ ...p, comment: e.target.value }))}
          />
        </div>
      ) : (
        <p className="text-[11px] text-slate-500 italic">
          ✓ Feedback: {(feedbackState?.useful ?? action.feedback?.useful) ? "Useful" : "Not useful"}
        </p>
      )}
    </div>
  );
};

// ── Compact action row (clickable, expandable) ─────────────────────────────

const ActionRow = ({ action, planId, addActions, onRefresh }) => {
  const [open, setOpen] = useState(false);
  const rule  = getRuleBadge(action);
  const isExit = action.type === "EXIT";
  const cur  = action.status || "PENDING";

  return (
    <div
      className={`rounded-xl border transition-all duration-200 cursor-pointer
        ${isExit
          ? open ? "border-red-300 bg-red-50/80" : "border-red-100 bg-red-50 hover:border-red-200 hover:shadow-sm"
          : open ? "border-emerald-300 bg-emerald-50/80" : "border-emerald-100 bg-emerald-50 hover:border-emerald-200 hover:shadow-sm"
        }`}
      onClick={() => setOpen((p) => !p)}
      data-testid={`action-row-${action.action_id || action.type?.toLowerCase()}`}
    >
      {/* Summary row */}
      <div className="flex items-start gap-2.5 p-3">
        <div className={`mt-0.5 flex-shrink-0 ${isExit ? "text-red-600" : "text-emerald-600"}`}>
          {isExit ? <TrendingDown className="w-4 h-4" /> : <TrendingUp className="w-4 h-4" />}
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-baseline justify-between gap-2">
            <span className={`text-sm font-bold ${isExit ? "text-red-700" : "text-emerald-700"}`}>
              {action.type}
            </span>
            <span className={`text-sm font-extrabold flex-shrink-0 ${isExit ? "text-red-600" : "text-emerald-600"}`}>
              {fmt(action.amount)}
            </span>
          </div>

          {/* Full fund name — no truncation */}
          <p className="text-xs text-slate-700 font-medium mt-0.5 leading-snug">
            {action.asset_name}
          </p>

          <div className="flex items-center justify-between mt-1.5">
            <div className="flex items-center gap-1.5 flex-wrap">
              {rule && (
                <span
                  className={`px-2 py-0.5 rounded-full text-[10px] font-semibold border ${rule.className}`}
                  title={rule.tooltip}
                  data-testid={`rule-badge-${rule.code?.toLowerCase()}`}
                >
                  {rule.label}
                </span>
              )}
              <span className={`px-1.5 py-0.5 rounded-full text-[10px] font-semibold border ${statusColors[cur] || statusColors.PENDING}`}>
                {statusLabel[cur] || "Pending"}
              </span>
            </div>
            <div className={`ml-1 ${isExit ? "text-red-400" : "text-emerald-400"}`}>
              {open ? <ChevronUp className="w-3.5 h-3.5" /> : <ChevronDown className="w-3.5 h-3.5" />}
            </div>
          </div>
        </div>
      </div>

      {/* Expanded detail — stops propagation so inner buttons work */}
      {open && (
        <div
          className="px-3 pb-3 border-t border-slate-200/70"
          onClick={(e) => e.stopPropagation()}
        >
          <ActionDetailPanel
            action={action}
            planId={planId}
            addActions={addActions}
            onRefresh={onRefresh}
          />
        </div>
      )}
    </div>
  );
};

// ── Main PlanCard ──────────────────────────────────────────────────────────

const PlanCard = ({ plan, isActive, onRefresh, compactMode = false }) => {
  const [minimized, setMinimized] = useState(false);

  const addActions  = plan.actions.filter((a) => a.type === "ADD");
  const exitActions = plan.actions.filter((a) => a.type === "EXIT");
  const allActions  = [...exitActions, ...addActions];

  if (minimized || compactMode) {
    return (
      <Card className={`overflow-hidden hover:shadow-md transition-all duration-200 ${isActive ? "ring-2 ring-emerald-600" : ""}`}>
        <div className="p-4 bg-gradient-to-br from-slate-50 to-white flex items-center justify-between">
          <div className="flex items-center gap-3">
            <Badge className={plan.status === "active" ? "bg-emerald-600" : "bg-slate-500"}>
              {plan.status === "active" ? "Active" : plan.status}
            </Badge>
            <span className="text-sm text-slate-600">{fmtDate(plan.created_at)}</span>
            <span className="text-sm font-semibold text-slate-900">
              {(plan.completion_pct || 0).toFixed(0)}% complete
            </span>
          </div>
          <Button variant="ghost" size="sm" onClick={() => setMinimized(false)}>
            <Maximize2 className="w-4 h-4" />
          </Button>
        </div>
      </Card>
    );
  }

  return (
    <Card className={`overflow-hidden transition-all duration-300 hover:shadow-lg ${isActive ? "ring-2 ring-emerald-600 shadow-emerald-100" : ""}`}>
      {/* ── Card header ── */}
      <div className="p-5 pb-3 bg-gradient-to-br from-slate-50 to-white">
        <div className="flex items-start justify-between mb-3">
          <div className="flex items-center gap-2 flex-wrap">
            <Badge className={plan.status === "active" ? "bg-emerald-600" : plan.status === "completed" ? "bg-blue-600" : "bg-slate-500"}>
              {plan.status === "active" ? "Active" : plan.status === "completed" ? "Completed" : "Archived"}
            </Badge>
            <Badge variant="outline" className="text-xs">v{plan.version}</Badge>
            {isActive && <Sparkles className="w-3.5 h-3.5 text-emerald-600" />}
          </div>
          <Button variant="ghost" size="sm" onClick={() => setMinimized(true)} className="-mt-1 -mr-1">
            <Minimize2 className="w-3.5 h-3.5" />
          </Button>
        </div>

        <div className="flex items-center gap-1.5 text-xs text-slate-500 mb-3">
          <Calendar className="w-3.5 h-3.5" />
          {fmtDate(plan.created_at)}
        </div>

        {/* Progress */}
        <div>
          <div className="flex items-center justify-between mb-1">
            <span className="text-xs font-semibold text-slate-600">Progress</span>
            <span className="text-sm font-bold text-slate-900">{(plan.completion_pct || 0).toFixed(0)}%</span>
          </div>
          <Progress value={plan.completion_pct || 0} className="h-1.5" />
          <p className="text-xs text-slate-500 mt-1">
            {plan.completed_actions || 0}/{plan.total_actions || plan.actions?.length || 0} actions completed
          </p>
        </div>

        {/* Stale-plan alert */}
        {(plan.completion_pct >= 100 || (plan.completed_actions + plan.skipped_actions) >= plan.actions?.length) &&
          plan.signals?.length > 0 && (
          <div className="mt-3 p-2.5 bg-amber-50 border border-amber-200 rounded-lg flex items-start gap-2">
            <AlertTriangle className="w-3.5 h-3.5 text-amber-600 flex-shrink-0 mt-0.5" />
            <div>
              <p className="text-[11px] font-semibold text-amber-900">
                {plan.signals.length} signal{plan.signals.length > 1 ? "s" : ""} still pending
              </p>
              <Button size="sm" onClick={onRefresh}
                className="mt-1.5 h-6 text-[11px] bg-amber-600 hover:bg-amber-700 px-2">
                <RefreshCw className="w-2.5 h-2.5 mr-1" /> Regenerate plan
              </Button>
            </div>
          </div>
        )}
      </div>

      {/* ── Action rows — each individually expandable ── */}
      <div className="px-4 pb-4 space-y-2.5">
        <h3 className="text-xs font-bold text-slate-500 uppercase tracking-wider pt-1 pb-0.5">
          Actions — click any card for details &amp; rebalancing plan
        </h3>

        {allActions.map((action, idx) => (
          <ActionRow
            key={action.action_id || idx}
            action={action}
            planId={plan.plan_id}
            addActions={action.type === "EXIT" ? addActions : []}
            onRefresh={onRefresh}
          />
        ))}

        {/* Signals summary */}
        {plan.signals?.length > 0 && (
          <div className="mt-1 p-2.5 bg-amber-50 rounded-xl border border-amber-100">
            <div className="flex items-center gap-1.5 mb-1">
              <div className="w-2 h-2 bg-amber-500 rounded-full" />
              <span className="text-xs font-bold text-amber-800">
                {plan.signals.length} signal{plan.signals.length > 1 ? "s" : ""} detected
              </span>
            </div>
            <p className="text-xs text-amber-700">{plan.signals[0]?.title?.substring(0, 60)}…</p>
          </div>
        )}

        {/* Tax summary */}
        {plan.total_tax_impact && (
          <div className="mt-1 p-3 bg-blue-50 border border-blue-200 rounded-xl">
            <p className="text-[10px] font-bold text-slate-600 uppercase tracking-wider mb-1.5">Tax Summary</p>
            <div className="space-y-1 text-xs">
              {[
                ["LTCG Tax",  fmtFull(plan.total_tax_impact.ltcg_tax  || 0)],
                ["STCG Tax",  fmtFull(plan.total_tax_impact.stcg_tax  || 0)],
                ["Total Tax", fmtFull(plan.total_tax_impact.total_tax || 0), "font-bold text-red-600"],
              ].map(([l, v, cls]) => (
                <div key={l} className="flex justify-between">
                  <span className="text-slate-500">{l}</span>
                  <span className={cls || "font-medium text-slate-800"}>{v}</span>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </Card>
  );
};

export default PlanCard;
