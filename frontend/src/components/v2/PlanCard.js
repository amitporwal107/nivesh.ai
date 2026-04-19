import React from "react";
import { useNavigate } from "react-router-dom";
import { Calendar, CheckCircle2, Clock, TrendingDown, TrendingUp, ArrowRight, Sparkles } from "lucide-react";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";

const PlanCard = ({ plan, isActive, onRefresh }) => {
  const navigate = useNavigate();

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
              {plan.completion_pct.toFixed(0)}%
            </span>
          </div>
          <Progress value={plan.completion_pct} className="h-2" />
          <p className="text-xs text-slate-600 mt-1">
            {plan.completed_actions}/{plan.total_actions} actions completed
          </p>
        </div>
      </div>

      {/* Actions Summary */}
      <div className="p-6 pt-4">
        <h3 className="text-sm font-semibold text-slate-700 mb-3">Actions</h3>
        <div className="space-y-2">
          {exitActions.length > 0 && (
            <div className="flex items-center justify-between p-3 bg-red-50 rounded-lg border border-red-100">
              <div className="flex items-center gap-2">
                <TrendingDown className="w-4 h-4 text-red-600" />
                <span className="text-sm font-medium text-slate-700">
                  {exitActions.length} EXIT
                </span>
              </div>
              <span className="text-sm font-bold text-red-600">
                {formatAmount(exitActions.reduce((sum, a) => sum + a.amount, 0))}
              </span>
            </div>
          )}
          {addActions.length > 0 && (
            <div className="flex items-center justify-between p-3 bg-emerald-50 rounded-lg border border-emerald-100">
              <div className="flex items-center gap-2">
                <TrendingUp className="w-4 h-4 text-emerald-600" />
                <span className="text-sm font-medium text-slate-700">
                  {addActions.length} ADD
                </span>
              </div>
              <span className="text-sm font-bold text-emerald-600">
                {formatAmount(addActions.reduce((sum, a) => sum + a.amount, 0))}
              </span>
            </div>
          )}
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
          onClick={() => navigate(`/dashboard/plan/${plan.plan_id}`)}
        >
          View Details
          <ArrowRight className="w-4 h-4 ml-2" />
        </Button>
      </div>
    </Card>
  );
};

export default PlanCard;
