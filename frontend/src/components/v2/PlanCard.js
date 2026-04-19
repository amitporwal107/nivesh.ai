import React, { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Calendar, CheckCircle2, Clock, TrendingDown, TrendingUp, ArrowRight, Sparkles, ChevronDown, ChevronUp } from "lucide-react";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";

const PlanCard = ({ plan, isActive, onRefresh }) => {
  const navigate = useNavigate();
  const [expanded, setExpanded] = useState(false);

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

  const exitActions = plan.actions.filter(a => a.type === "EXIT");
  const addActions = plan.actions.filter(a => a.type === "ADD");

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
        </div>
      </div>

      {/* Actions Summary */}
      <div className="p-6 pt-4">
        <h3 className="text-sm font-semibold text-slate-700 mb-3">Actions</h3>
        <div className="space-y-2">
          {exitActions.length > 0 && exitActions.map((action, idx) => (
            <div key={idx} className="flex items-start justify-between p-3 bg-red-50 rounded-lg border border-red-100">
              <div className="flex items-start gap-2 flex-1 min-w-0">
                <TrendingDown className="w-4 h-4 text-red-600 mt-0.5 flex-shrink-0" />
                <div className="flex-1 min-w-0">
                  <span className="text-sm font-medium text-slate-900 block">EXIT</span>
                  <span className="text-xs text-slate-600 line-clamp-1">{action.asset_name}</span>
                </div>
              </div>
              <span className="text-sm font-bold text-red-600 ml-2 flex-shrink-0">
                {formatAmount(action.amount)}
              </span>
            </div>
          ))}
          {addActions.length > 0 && addActions.map((action, idx) => (
            <div key={idx} className="flex items-start justify-between p-3 bg-emerald-50 rounded-lg border border-emerald-100">
              <div className="flex items-start gap-2 flex-1 min-w-0">
                <TrendingUp className="w-4 h-4 text-emerald-600 mt-0.5 flex-shrink-0" />
                <div className="flex-1 min-w-0">
                  <span className="text-sm font-medium text-slate-900 block">ADD</span>
                  <span className="text-xs text-slate-600 line-clamp-1">{action.asset_name}</span>
                </div>
              </div>
              <span className="text-sm font-bold text-emerald-600 ml-2 flex-shrink-0">
                {formatAmount(action.amount)}
              </span>
            </div>
          ))}
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
            {plan.actions.map((action, idx) => (
              <div key={idx} className="p-4 bg-slate-50 rounded-lg border border-slate-200">
                <div className="flex items-start justify-between mb-2">
                  <div className="flex items-center gap-2">
                    <Badge className={action.type === "EXIT" ? "bg-red-600" : "bg-emerald-600"}>
                      {action.type}
                    </Badge>
                    <span className="text-xs text-slate-600">Priority {action.priority}</span>
                  </div>
                  <span className="text-sm font-bold text-slate-900">
                    {formatAmount(action.amount)}
                  </span>
                </div>
                
                <h5 className="text-sm font-semibold text-slate-900 mb-2">{action.asset_name}</h5>
                
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
                
                <p className="text-xs text-slate-600 mt-2">
                  <span className="font-medium">Reason:</span> {action.reason_text}
                </p>
              </div>
            ))}
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
