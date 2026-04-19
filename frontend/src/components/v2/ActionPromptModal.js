import React, { useState, useEffect } from "react";
import axios from "axios";
import { CheckCircle2, Clock, TrendingDown, TrendingUp, X, ArrowRight } from "lucide-react";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { toast } from "sonner";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
const API = `${BACKEND_URL}/api`;

const ActionPromptModal = ({ open, onClose, onNavigateToPlanBoard }) => {
  const [plan, setPlan] = useState(null);
  const [loading, setLoading] = useState(true);
  const [updating, setUpdating] = useState(false);

  useEffect(() => {
    if (open) {
      fetchActivePlan();
    }
  }, [open]);

  const fetchActivePlan = async () => {
    try {
      setLoading(true);
      const res = await axios.get(`${API}/plans/active`, { withCredentials: true });
      if (res.data.has_plan) {
        setPlan(res.data.plan);
      } else {
        setPlan(null);
      }
    } catch (error) {
      console.error("Error fetching plan:", error);
      setPlan(null);
    } finally {
      setLoading(false);
    }
  };

  const markActionComplete = async (actionId) => {
    try {
      setUpdating(true);
      await axios.patch(
        `${API}/plans/${plan.plan_id}/actions/${actionId}`,
        { status: "COMPLETED" },
        { withCredentials: true }
      );
      await fetchActivePlan();
      toast.success("Action marked as completed!");
    } catch (error) {
      console.error("Error updating action:", error);
      toast.error("Failed to update action");
    } finally {
      setUpdating(false);
    }
  };

  if (loading) {
    return (
      <Dialog open={open} onOpenChange={onClose}>
        <DialogContent className="max-w-2xl">
          <div className="flex items-center justify-center py-8">
            <div className="text-center">
              <div className="w-8 h-8 border-4 border-slate-300 border-t-emerald-600 rounded-full animate-spin mx-auto mb-3"></div>
              <p className="text-sm text-slate-600">Checking for pending actions...</p>
            </div>
          </div>
        </DialogContent>
      </Dialog>
    );
  }

  if (!plan) {
    return null;
  }

  const pendingActions = plan.actions.filter(a => a.status === "PENDING");
  
  if (pendingActions.length === 0) {
    return null;
  }

  const formatAmount = (amount) => {
    return new Intl.NumberFormat('en-IN', { 
      style: 'currency', 
      currency: 'INR',
      maximumFractionDigits: 0 
    }).format(amount);
  };

  return (
    <Dialog open={open} onOpenChange={onClose}>
      <DialogContent className="max-w-3xl max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle className="text-2xl font-bold flex items-center gap-2">
            <Clock className="w-6 h-6 text-amber-600" />
            You have {pendingActions.length} pending action{pendingActions.length !== 1 ? 's' : ''}
          </DialogTitle>
        </DialogHeader>

        <div className="py-4">
          <p className="text-slate-600 mb-6">
            Your action plan requires attention. Review and mark actions as completed if you've already executed them.
          </p>

          {/* Progress */}
          <div className="mb-6 p-4 bg-slate-50 rounded-lg">
            <div className="flex items-center justify-between mb-2">
              <span className="text-sm font-semibold text-slate-700">Progress</span>
              <span className="text-lg font-bold text-slate-900">
                {plan.completion_pct.toFixed(0)}%
              </span>
            </div>
            <div className="h-2 bg-slate-200 rounded-full overflow-hidden">
              <div 
                className="h-full bg-emerald-600 transition-all duration-500"
                style={{ width: `${plan.completion_pct}%` }}
              ></div>
            </div>
            <p className="text-xs text-slate-600 mt-2">
              {plan.completed_actions} of {plan.total_actions} completed
            </p>
          </div>

          {/* Pending Actions */}
          <div className="space-y-3 max-h-96 overflow-y-auto">
            {pendingActions.map((action, idx) => (
              <div 
                key={action.action_id}
                className="p-4 border-2 border-slate-200 rounded-xl hover:border-slate-300 transition-colors"
              >
                <div className="flex items-start gap-3">
                  <div className="mt-1">
                    {action.type === "EXIT" ? (
                      <TrendingDown className="w-5 h-5 text-red-600" />
                    ) : (
                      <TrendingUp className="w-5 h-5 text-emerald-600" />
                    )}
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 mb-1">
                      <Badge className={action.type === "EXIT" ? "bg-red-600" : "bg-emerald-600"}>
                        {action.type}
                      </Badge>
                      <Badge variant="outline" className="text-xs">
                        Priority {idx + 1}
                      </Badge>
                    </div>
                    <h4 className="font-semibold text-slate-900 mb-1">
                      {action.asset_name}
                    </h4>
                    <p className="text-2xl font-black text-slate-900 mb-2">
                      {formatAmount(action.amount)}
                    </p>
                    <p className="text-sm text-slate-600 mb-3">
                      {action.reason_text}
                    </p>
                    <Button
                      onClick={() => markActionComplete(action.action_id)}
                      disabled={updating}
                      size="sm"
                      className="bg-emerald-600 hover:bg-emerald-700"
                    >
                      <CheckCircle2 className="w-4 h-4 mr-2" />
                      Mark as Done
                    </Button>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>

        <DialogFooter className="flex-col sm:flex-row gap-2">
          <Button
            variant="outline"
            onClick={onClose}
            className="w-full sm:w-auto"
          >
            Review Later
          </Button>
          <Button
            onClick={() => {
              onClose();
              onNavigateToPlanBoard();
            }}
            className="w-full sm:w-auto"
          >
            View All Plans
            <ArrowRight className="w-4 h-4 ml-2" />
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
};

export default ActionPromptModal;
