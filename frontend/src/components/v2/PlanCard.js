import React, { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Calendar, CheckCircle2, Clock, TrendingDown, TrendingUp, ArrowRight, Sparkles, ChevronDown, ChevronUp, ThumbsUp, ThumbsDown, Minimize2, Maximize2, Play, AlertTriangle, RefreshCw } from "lucide-react";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { toast } from "sonner";
import axios from "axios";
import V3ScoreBadges from "./V3ScoreBadges";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
const API = `${BACKEND_URL}/api`;

const PlanCard = ({ plan, isActive, onRefresh, compactMode = false }) => {
  const navigate = useNavigate();
  const [expanded, setExpanded] = useState(false);
  const [minimized, setMinimized] = useState(false);
  const [feedbackStates, setFeedbackStates] = useState({});
  const [updatingAction, setUpdatingAction] = useState(null);

  const formatDate = (dateStr) => {
    return new Date(dateStr).toLocaleDateString('en-IN', {
      day: 'numeric',
      month: 'short',
      year: 'numeric'
    });
  };

  const formatAmount = (amount) => {
    return new Intl.NumberFormat('en-IN', { 
      style: 'currency', 
      currency: 'INR',
      maximumFractionDigits: 0,
      notation: 'compact'
    }).format(amount);
  };

  const getStatusColor = () => {
    if (plan.status === "active") return "bg-emerald-600";
    if (plan.status === "completed") return "bg-blue-600";
    return "bg-slate-500";
  };

  const getStatusLabel = () => {
    if (plan.status === "active") return "Active";
    if (plan.status === "completed") return "Completed";
    if (plan.status === "archived") return "Archived";
    return "Preview";
  };

  // Map action reason_codes → rule provenance badge (shows WHY this action was recommended)
  const getRuleBadge = (action) => {
    const codes = action.reason_codes || [];
    // Priority order: rule-level codes first, then fallback codes
    const ruleMap = {
      REGULAR_DIRECT_DUPLICATE: {
        label: "Rule 1 · Regular → Direct",
        className: "bg-indigo-50 text-indigo-700 border-indigo-200",
        tooltip: "Same fund exists as Direct plan in your portfolio. Exiting the Regular plan saves on expense ratio.",
      },
      COST_LEAK_SWITCH_TO_DIRECT: {
        label: "Rule 6 · Cost leak switch",
        className: "bg-amber-50 text-amber-700 border-amber-200",
        tooltip: "Switching to Direct plan saves ₹10K+/year in expense ratio.",
      },
      AMC_CONCENTRATION_EXIT: {
        label: "Rule 2 · AMC concentration",
        className: "bg-rose-50 text-rose-700 border-rose-200",
        tooltip: "This AMC exceeds the 15% concentration limit. Exiting the highest exit-score fund to rebalance.",
      },
      UNDERPERFORMER_REPLACEMENT: {
        label: "Rule 3 · Underperformer swap",
        className: "bg-orange-50 text-orange-700 border-orange-200",
        tooltip: "Fund is underperforming its benchmark. Replacing with highest-rated fund in same category.",
      },
      OVERLAP_CONSOLIDATION: {
        label: "Rule 4 · Overlap consolidation",
        className: "bg-purple-50 text-purple-700 border-purple-200",
        tooltip: "Two funds have >60% stock-level overlap. Exiting the one with higher exit score to reduce duplication.",
      },
      ALLOCATION_GAP: {
        label: "Rule 5 · Debt allocation gap",
        className: "bg-sky-50 text-sky-700 border-sky-200",
        tooltip: "Your portfolio lacks debt allocation. Adding a debt fund improves risk management.",
      },
    };
    for (const code of codes) {
      if (ruleMap[code]) return { code, ...ruleMap[code] };
    }
    return null;
  };

  const exitActions = plan.actions.filter(a => a.type === "EXIT");

  const handleStatusUpdate = async (actionId, newStatus) => {
    try {
      setUpdatingAction(actionId);
      await axios.patch(
        `${API}/plans/${plan.plan_id}/actions/${actionId}`,
        { status: newStatus },
        { withCredentials: true }
      );
      toast.success(`Action marked as ${newStatus}`);
      if (onRefresh) onRefresh();
    } catch (error) {
      console.error("Error updating action status:", error);
      toast.error("Failed to update action status");
    } finally {
      setUpdatingAction(null);
    }
  };

  const handleFeedback = async (actionId, useful) => {
    const comment = feedbackStates[actionId]?.comment || "";
    try {
      await axios.patch(
        `${API}/plans/${plan.plan_id}/actions/${actionId}/feedback`,
        { useful, comment },
        { withCredentials: true }
      );
      toast.success("Thank you for your feedback!");
      setFeedbackStates(prev => ({ ...prev, [actionId]: { submitted: true, useful } }));
      if (onRefresh) onRefresh();
    } catch (error) {
      console.error("Error submitting feedback:", error);
      toast.error("Failed to submit feedback");
    }
  };

  const getActionStatusColor = (status) => {
    switch(status) {
      case "COMPLETED": return "text-emerald-600 bg-emerald-50";
      case "IN_PROGRESS": return "text-blue-600 bg-blue-50";
      case "SKIPPED": return "text-slate-600 bg-slate-100";
      default: return "text-amber-600 bg-amber-50";
    }
  };

  const getActionStatusLabel = (status) => {
    switch(status) {
      case "COMPLETED": return "Done";
      case "IN_PROGRESS": return "In Progress";
      case "SKIPPED": return "Skipped";
      default: return "Pending";
    }
  };

  const addActions = plan.actions.filter(a => a.type === "ADD");

  // If minimized or compact, show minimal card
  if (minimized || compactMode) {
    return (
      <Card className={`overflow-hidden hover:shadow-md transition-all duration-300 ${
        isActive ? 'ring-2 ring-emerald-600 shadow-emerald-100' : ''
      }`}>
        <div className="p-4 bg-gradient-to-br from-slate-50 to-white">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3 flex-1">
              <Badge className={getStatusColor()}>
                {getStatusLabel()}
              </Badge>
              <span className="text-sm text-slate-600">{formatDate(plan.created_at)}</span>
              <span className="text-sm font-semibold text-slate-900">
                {(plan.completion_pct || 0).toFixed(0)}% complete
              </span>
            </div>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setMinimized(false)}
            >
              <Maximize2 className="w-4 h-4" />
            </Button>
          </div>
        </div>
      </Card>
    );
  }

  return (
    <Card className={`overflow-hidden hover:shadow-lg transition-all duration-300 ${
      isActive ? 'ring-2 ring-emerald-600 shadow-emerald-100' : ''
    }`}>
      {/* Header with Status Badge */}
      <div className="p-6 pb-4 bg-gradient-to-br from-slate-50 to-white">
        <div className="flex items-start justify-between mb-3">
          <div>
            <div className="flex items-center gap-2 mb-2">
              <Badge className={getStatusColor()}>
                {getStatusLabel()}
              </Badge>
              <Badge variant="outline" className="text-xs">
                v{plan.version}
              </Badge>
              {isActive && (
                <Sparkles className="w-4 h-4 text-emerald-600" />
              )}
            </div>
            <div className="flex items-center gap-2 text-sm text-slate-600">
              <Calendar className="w-4 h-4" />
              {formatDate(plan.created_at)}
            </div>
          </div>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => setMinimized(true)}
            className="ml-2"
          >
            <Minimize2 className="w-4 h-4" />
          </Button>
        </div>

        {/* Progress */}
        <div className="mt-4">
          <div className="flex items-center justify-between mb-2">
            <span className="text-xs font-semibold text-slate-600">Progress</span>
            <span className="text-sm font-bold text-slate-900">
              {(plan.completion_pct || 0).toFixed(0)}%
            </span>
          </div>
          <Progress value={plan.completion_pct || 0} className="h-2" />
          <p className="text-xs text-slate-600 mt-1">
            {plan.completed_actions || 0}/{plan.total_actions || plan.actions?.length || 0} actions completed
          </p>
          
          {/* Auto-regeneration prompt when complete but signals still exist */}
          {(plan.completion_pct >= 100 || (plan.completed_actions + plan.skipped_actions) === plan.actions.length) && 
           plan.signals && plan.signals.length > 0 && (
            <div className="mt-3 p-3 bg-amber-50 border border-amber-200 rounded-lg">
              <div className="flex items-start gap-2">
                <AlertTriangle className="w-4 h-4 text-amber-600 mt-0.5" />
                <div className="flex-1">
                  <p className="text-xs font-semibold text-amber-900">
                    Actions complete, but {plan.signals.length} signal{plan.signals.length !== 1 ? 's' : ''} still detected
                  </p>
                  <p className="text-xs text-amber-700 mt-1">
                    Generate a new plan to address remaining portfolio issues
                  </p>
                  <Button
                    size="sm"
                    onClick={onRefresh}
                    className="mt-2 h-7 text-xs bg-amber-600 hover:bg-amber-700"
                  >
                    <RefreshCw className="w-3 h-3 mr-1" />
                    Generate New Plan
                  </Button>
                </div>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Actions Summary */}
      <div className="p-6 pt-4">
        <h3 className="text-sm font-semibold text-slate-700 mb-3">Actions</h3>
        <div className="space-y-2">
          {exitActions.length > 0 && exitActions.map((action, idx) => {
            const rule = getRuleBadge(action);
            return (
            <div key={idx} className="flex items-start justify-between p-3 bg-red-50 rounded-lg border border-red-100" data-testid={`plan-action-exit-${idx}`}>
              <div className="flex items-start gap-2 flex-1 min-w-0">
                <TrendingDown className="w-4 h-4 text-red-600 mt-0.5 flex-shrink-0" />
                <div className="flex-1 min-w-0">
                  <span className="text-sm font-medium text-slate-900 block">EXIT</span>
                  <span className="text-xs text-slate-600 line-clamp-1">{action.asset_name}</span>
                  {rule && (
                    <span
                      title={rule.tooltip}
                      data-testid={`rule-badge-${rule.code.toLowerCase()}`}
                      className={`inline-block mt-1.5 px-2 py-0.5 rounded-full text-[10px] font-semibold border ${rule.className}`}
                    >
                      {rule.label}
                    </span>
                  )}
                </div>
              </div>
              <span className="text-sm font-bold text-red-600 ml-2 flex-shrink-0">
                {formatAmount(action.amount)}
              </span>
            </div>
          );})}
          {addActions.length > 0 && addActions.map((action, idx) => {
            const rule = getRuleBadge(action);
            return (
            <div key={idx} className="flex items-start justify-between p-3 bg-emerald-50 rounded-lg border border-emerald-100" data-testid={`plan-action-add-${idx}`}>
              <div className="flex items-start gap-2 flex-1 min-w-0">
                <TrendingUp className="w-4 h-4 text-emerald-600 mt-0.5 flex-shrink-0" />
                <div className="flex-1 min-w-0">
                  <span className="text-sm font-medium text-slate-900 block">ADD</span>
                  <span className="text-xs text-slate-600 line-clamp-1">{action.asset_name}</span>
                  {rule && (
                    <span
                      title={rule.tooltip}
                      data-testid={`rule-badge-${rule.code.toLowerCase()}`}
                      className={`inline-block mt-1.5 px-2 py-0.5 rounded-full text-[10px] font-semibold border ${rule.className}`}
                    >
                      {rule.label}
                    </span>
                  )}
                </div>
              </div>
              <span className="text-sm font-bold text-emerald-600 ml-2 flex-shrink-0">
                {formatAmount(action.amount)}
              </span>
            </div>
          );})}
        </div>

        {/* Signals */}
        {plan.signals && plan.signals.length > 0 && (
          <div className="mt-4 p-3 bg-amber-50 rounded-lg border border-amber-100">
            <div className="flex items-center gap-2">
              <div className="w-2 h-2 bg-amber-600 rounded-full"></div>
              <span className="text-xs font-semibold text-amber-800">
                {plan.signals.length} signal{plan.signals.length !== 1 ? 's' : ''} detected
              </span>
            </div>
            <p className="text-xs text-amber-700 mt-1">
              {plan.signals[0]?.title?.substring(0, 40)}...
            </p>
          </div>
        )}
      </div>

      {/* Footer */}
      <div className="px-6 pb-6">
        <Button 
          variant="outline"
          className="w-full"
          onClick={() => setExpanded(!expanded)}
        >
          {expanded ? "Hide Details" : "View Details"}
          {expanded ? <ChevronUp className="w-4 h-4 ml-2" /> : <ChevronDown className="w-4 h-4 ml-2" />}
        </Button>
      </div>

      {/* Expanded Details */}
      {expanded && (
        <div className="px-6 pb-6 border-t border-slate-200 pt-4">
          <h4 className="text-sm font-semibold text-slate-900 mb-3">Action Details</h4>
          <div className="space-y-3">
            {plan.actions.map((action, idx) => {
              const rule = getRuleBadge(action);
              return (
              <div key={idx} className="p-4 bg-white rounded-lg border border-slate-200 shadow-sm" data-testid={`plan-action-detail-${idx}`}>
                {/* Action Header */}
                <div className="flex items-start justify-between mb-3">
                  <div className="flex items-center gap-2 flex-wrap">
                    <Badge className={action.type === "EXIT" ? "bg-red-600" : "bg-emerald-600"}>
                      {action.type}
                    </Badge>
                    <Badge className={getActionStatusColor(action.status || "PENDING")} variant="outline">
                      {getActionStatusLabel(action.status || "PENDING")}
                    </Badge>
                    <span className="text-xs text-slate-600">Priority {action.priority}</span>
                    {rule && (
                      <span
                        title={rule.tooltip}
                        data-testid={`rule-badge-detail-${rule.code.toLowerCase()}`}
                        className={`px-2 py-0.5 rounded-full text-[10px] font-semibold border ${rule.className}`}
                      >
                        {rule.label}
                      </span>
                    )}
                  </div>
                  <span className="text-sm font-bold text-slate-900">
                    {formatAmount(action.amount)}
                  </span>
                </div>
                
                <h5 className="text-sm font-semibold text-slate-900 mb-3 break-words">{action.asset_name}</h5>
                
                {/* Status Control */}
                <div className="mb-3 p-3 bg-slate-50 rounded-lg border border-slate-200">
                  <label className="text-xs font-semibold text-slate-700 mb-2 block">Update Status</label>
                  <div className="flex gap-2 flex-wrap">
                    <Button
                      size="sm"
                      variant={action.status === "IN_PROGRESS" ? "default" : "outline"}
                      onClick={() => handleStatusUpdate(action.action_id, "IN_PROGRESS")}
                      disabled={updatingAction === action.action_id}
                      className="flex-1 min-w-[100px]"
                    >
                      <Play className="w-3 h-3 mr-1" />
                      In Progress
                    </Button>
                    <Button
                      size="sm"
                      variant={action.status === "COMPLETED" ? "default" : "outline"}
                      onClick={() => handleStatusUpdate(action.action_id, "COMPLETED")}
                      disabled={updatingAction === action.action_id}
                      className="flex-1 min-w-[100px] bg-emerald-600 hover:bg-emerald-700"
                    >
                      <CheckCircle2 className="w-3 h-3 mr-1" />
                      Done
                    </Button>
                    <Button
                      size="sm"
                      variant={action.status === "SKIPPED" ? "default" : "outline"}
                      onClick={() => handleStatusUpdate(action.action_id, "SKIPPED")}
                      disabled={updatingAction === action.action_id}
                      className="flex-1 min-w-[100px]"
                    >
                      Skip
                    </Button>
                  </div>
                </div>
                
                {action.type === "EXIT" && action.tax_impact && (
                  <div className="space-y-1 text-xs text-slate-600 mb-2">
                    <h6 className="font-semibold text-slate-900 text-sm mb-2 flex items-center gap-2">
                      💰 Tax Calculation (STCG/LTCG)
                    </h6>
                    
                    <div className="bg-slate-50 p-3 rounded border border-slate-200 space-y-1.5">
                      <div className="flex justify-between">
                        <span>Current Value:</span>
                        <span className="font-medium">₹{action.amount?.toLocaleString('en-IN', {maximumFractionDigits: 0})}</span>
                      </div>
                      <div className="flex justify-between">
                        <span>Invested Amount:</span>
                        <span className="font-medium">₹{((action.amount || 0) - (action.tax_impact.capital_gain || 0)).toLocaleString('en-IN', {maximumFractionDigits: 0})}</span>
                      </div>
                      <div className="flex justify-between border-t border-slate-300 pt-1.5">
                        <span className="font-medium">Capital Gain:</span>
                        <span className="font-semibold text-emerald-600">₹{action.tax_impact.capital_gain?.toLocaleString('en-IN', {maximumFractionDigits: 0})}</span>
                      </div>
                      
                      <div className="flex justify-between mt-2 pt-2 border-t border-slate-300">
                        <span>Holding Period:</span>
                        <span className="font-medium">{action.tax_impact.holding_period_days || 0} days ({((action.tax_impact.holding_period_days || 0) / 365).toFixed(1)} years)</span>
                      </div>
                      <div className="flex justify-between">
                        <span>Tax Type:</span>
                        <span className="font-semibold text-blue-600">
                          {action.tax_impact.is_long_term ? 'LTCG' : 'STCG'} ({(action.tax_impact.tax_rate * 100).toFixed(0)}%)
                        </span>
                      </div>
                      
                      <div className="flex justify-between mt-2 pt-2 border-t border-slate-300">
                        <span className="font-medium">Tax Liability:</span>
                        <span className="font-semibold text-red-600">₹{action.tax_impact.tax_liability?.toLocaleString('en-IN', {maximumFractionDigits: 0})}</span>
                      </div>
                      <div className="flex justify-between">
                        <span className="font-semibold">Post-tax Proceeds:</span>
                        <span className="font-bold text-emerald-600">₹{action.tax_impact.post_tax_proceeds?.toLocaleString('en-IN', {maximumFractionDigits: 0})}</span>
                      </div>
                      
                      {action.tax_impact.break_even_years && (
                        <div className="flex justify-between mt-2 pt-2 border-t border-slate-300">
                          <span>Break-even Period:</span>
                          <span className="font-medium">{action.tax_impact.break_even_years.toFixed(1)} years</span>
                        </div>
                      )}
                    </div>
                    
                    <div className="mt-2 p-2 bg-amber-50 border border-amber-200 rounded text-xs text-amber-800">
                      ⚠️ <span className="font-semibold">Disclaimer:</span> This calculation does not consider your individual tax bracket. Actual tax liability may vary based on your total income and applicable tax slab.
                    </div>
                    
                    {action.tax_impact.exit_warning && (
                      <div className="mt-2 p-2 bg-red-50 border border-red-200 rounded text-xs text-red-800">
                        ⚠️ {action.tax_impact.exit_warning}
                      </div>
                    )}
                  </div>
                )}
                
                {action.type === "ADD" && action.fund_details && (
                  <div className="space-y-1 text-xs text-slate-600 mb-2">
                    <div className="flex justify-between">
                      <span>Fund Type:</span>
                      <span className="font-medium">{action.fund_details.fund_type}</span>
                    </div>
                    <div className="flex justify-between">
                      <span>Expense Ratio:</span>
                      <span className="font-medium">{action.fund_details.expense_ratio}%</span>
                    </div>
                    <div className="flex justify-between">
                      <span>Rating:</span>
                      <span className="font-medium">{action.fund_details.rating}</span>
                    </div>
                    <div className="flex justify-between">
                      <span>3Y Returns:</span>
                      <span className="font-medium text-emerald-600">{action.fund_details.returns_3y}</span>
                    </div>
                  </div>
                )}
                
                <p className="text-xs text-slate-600 mt-2 mb-3">
                  <span className="font-medium">Reason:</span> {action.reason_text}
                </p>

                {/* V3 Engine score badges (Quality/Health/Exit/Add + guardrails) */}
                <V3ScoreBadges scores={action.v3_scores} guardrails={action.v3_guardrail_reasons} />

                {action.switch_score != null && (
                  <div
                    data-testid="switch-score-indicator"
                    className="mt-2 text-[11px] text-slate-600"
                  >
                    <span className="font-semibold text-slate-800">Switch score:</span>{' '}
                    <span className="tabular-nums text-emerald-700">
                      {Number(action.switch_score).toFixed(1)}
                    </span>{' '}
                    <span className="text-slate-500">
                      (threshold 2.0 — higher = stronger net benefit)
                    </span>
                  </div>
                )}
                
                {/* Feedback Section */}
                {!feedbackStates[action.action_id]?.submitted && !action.feedback ? (
                  <div className="mt-3 p-3 bg-blue-50 rounded-lg border border-blue-200">
                    <p className="text-xs font-semibold text-slate-700 mb-2">Was this recommendation useful?</p>
                    <div className="flex gap-2 mb-2">
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={() => handleFeedback(action.action_id, true)}
                        className="flex-1 bg-white hover:bg-emerald-50 hover:border-emerald-300"
                      >
                        <ThumbsUp className="w-3 h-3 mr-1" />
                        Yes, useful
                      </Button>
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={() => handleFeedback(action.action_id, false)}
                        className="flex-1 bg-white hover:bg-red-50 hover:border-red-300"
                      >
                        <ThumbsDown className="w-3 h-3 mr-1" />
                        Not useful
                      </Button>
                    </div>
                    <Textarea
                      placeholder="Optional: Add your feedback..."
                      className="text-xs h-16 resize-none"
                      value={feedbackStates[action.action_id]?.comment || ""}
                      onChange={(e) => setFeedbackStates(prev => ({
                        ...prev,
                        [action.action_id]: { ...prev[action.action_id], comment: e.target.value }
                      }))}
                    />
                  </div>
                ) : (
                  <div className="mt-3 p-3 bg-slate-100 rounded-lg border border-slate-200">
                    <p className="text-xs text-slate-600">
                      ✓ Feedback submitted: {
                        (feedbackStates[action.action_id]?.useful ?? action.feedback?.useful) 
                          ? "Useful" 
                          : "Not useful"
                      }
                    </p>
                    {(feedbackStates[action.action_id]?.comment || action.feedback?.comment) && (
                      <p className="text-xs text-slate-500 mt-1">
                        "{feedbackStates[action.action_id]?.comment || action.feedback?.comment}"
                      </p>
                    )}
                  </div>
                )}
              </div>
            );})}
          </div>

          {/* Total Tax Impact */}
          {plan.total_tax_impact && (
            <div className="mt-4 p-4 bg-blue-50 border border-blue-200 rounded-lg">
              <h5 className="text-sm font-semibold text-slate-900 mb-2">Tax Summary</h5>
              <div className="space-y-1 text-xs text-slate-700">
                <div className="flex justify-between">
                  <span>LTCG Tax:</span>
                  <span className="font-medium">₹{plan.total_tax_impact.ltcg_tax?.toLocaleString('en-IN')}</span>
                </div>
                <div className="flex justify-between">
                  <span>STCG Tax:</span>
                  <span className="font-medium">₹{plan.total_tax_impact.stcg_tax?.toLocaleString('en-IN')}</span>
                </div>
                <div className="flex justify-between font-semibold text-sm border-t border-blue-300 pt-1 mt-1">
                  <span>Total Tax:</span>
                  <span className="text-red-600">₹{plan.total_tax_impact.total_tax?.toLocaleString('en-IN')}</span>
                </div>
              </div>
            </div>
          )}
        </div>
      )}
    </Card>
  );
};

export default PlanCard;
