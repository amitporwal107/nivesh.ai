import React, { useState, useEffect } from "react";
import axios from "axios";
import { RefreshCw, TrendingUp, AlertTriangle, CheckCircle2, XCircle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import ActionCard from "./ActionCard";
import SignalsWidget from "./SignalsWidget";
import PlanSummary from "./PlanSummary";
import { toast } from "sonner";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
const API = `${BACKEND_URL}/api`;

const ActionPlanView = () => {
  const [plan, setPlan] = useState(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

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
      console.error("Error fetching active plan:", error);
      toast.error("Failed to load action plan");
    } finally {
      setLoading(false);
    }
  };

  const generateNewPlan = async () => {
    try {
      setLoading(true);
      toast.info("Generating your action plan...");
      
      const res = await axios.post(`${API}/plans/generate`, {}, { withCredentials: true });
      const newPlan = res.data.plan;
      
      // Auto-save as active
      await axios.post(`${API}/plans/${newPlan.plan_id}/save`, {}, { withCredentials: true });
      
      await fetchActivePlan();
      toast.success("Action plan generated successfully!");
    } catch (error) {
      console.error("Error generating plan:", error);
      toast.error(error.response?.data?.detail || "Failed to generate plan");
    } finally {
      setLoading(false);
    }
  };

  const refreshPlan = async () => {
    try {
      setRefreshing(true);
      toast.info("Refreshing your plan...");
      
      const res = await axios.post(`${API}/plans/refresh`, {}, { withCredentials: true });
      setPlan(res.data.plan);
      toast.success(`Plan refreshed to version ${res.data.plan.version}`);
    } catch (error) {
      console.error("Error refreshing plan:", error);
      toast.error("Failed to refresh plan");
    } finally {
      setRefreshing(false);
    }
  };

  const updateActionStatus = async (actionId, status, note = null) => {
    try {
      const payload = { status };
      if (note) payload.completion_note = note;
      
      const res = await axios.patch(
        `${API}/plans/${plan.plan_id}/actions/${actionId}`,
        payload,
        { withCredentials: true }
      );
      
      setPlan(res.data.plan);
      
      if (status === "COMPLETED") {
        toast.success("Action marked as completed!");
      } else if (status === "SKIPPED") {
        toast.info("Action skipped");
      }
    } catch (error) {
      console.error("Error updating action:", error);
      toast.error("Failed to update action");
    }
  };

  useEffect(() => {
    fetchActivePlan();
  }, []);

  if (loading) {
    return (
      <div className="min-h-screen bg-[#FAF9F6] flex items-center justify-center">
        <div className="text-center">
          <RefreshCw className="w-8 h-8 animate-spin mx-auto text-slate-600 mb-2" />
          <p className="text-slate-600">Loading your action plan...</p>
        </div>
      </div>
    );
  }

  // No active plan - show empty state
  if (!plan) {
    return (
      <div className="min-h-screen bg-[#FAF9F6] py-8 px-4">
        <div className="max-w-md mx-auto">
          <Card className="p-8 text-center">
            <div className="w-16 h-16 bg-slate-100 rounded-full flex items-center justify-center mx-auto mb-4">
              <TrendingUp className="w-8 h-8 text-slate-600" />
            </div>
            <h2 className="text-2xl font-bold text-slate-900 mb-2">
              No Action Plan Yet
            </h2>
            <p className="text-slate-600 mb-6">
              Generate a personalized action plan based on your portfolio analysis.
            </p>
            <Button
              onClick={generateNewPlan}
              size="lg"
              className="min-h-[56px] text-lg w-full"
              disabled={loading}
            >
              <TrendingUp className="w-5 h-5 mr-2" />
              Generate My Action Plan
            </Button>
          </Card>
        </div>
      </div>
    );
  }

  const completionPercentage = plan.completion_pct || 0;
  const pendingActions = plan.actions.filter(a => a.status === "PENDING");
  const completedActions = plan.actions.filter(a => a.status === "COMPLETED");

  return (
    <div className="min-h-screen bg-[#FAF9F6] pb-32 pt-8">
      <div className="max-w-md mx-auto px-4">
        {/* Header */}
        <div className="mb-6">
          <h1 className="text-3xl font-black tracking-tight text-slate-900 mb-2">
            Your Action Plan
          </h1>
          <p className="text-sm text-slate-600">
            Updated: {new Date(plan.updated_at).toLocaleDateString()} • Plan v{plan.version}
          </p>
        </div>

        {/* Progress Tracker */}
        <Card className="p-6 mb-6 border-slate-200">
          <div className="mb-4">
            <div className="flex items-center justify-between mb-2">
              <span className="text-sm font-semibold text-slate-600">Progress</span>
              <span className="text-2xl font-black tracking-tighter text-slate-900">
                {completionPercentage.toFixed(0)}%
              </span>
            </div>
            <Progress value={completionPercentage} className="h-3" />
          </div>
          <p className="text-sm text-slate-600">
            {plan.completed_actions} of {plan.total_actions} actions completed
          </p>
        </Card>

        {/* Actions List */}
        <div className="space-y-4 mb-6">
          {plan.actions.map((action, index) => (
            <ActionCard
              key={action.action_id}
              action={action}
              priority={index + 1}
              onComplete={(note) => updateActionStatus(action.action_id, "COMPLETED", note)}
              onSkip={() => updateActionStatus(action.action_id, "SKIPPED")}
            />
          ))}
        </div>

        {/* Plan Summary */}
        <PlanSummary plan={plan} />

        {/* Signals Widget */}
        {plan.signals && plan.signals.length > 0 && (
          <SignalsWidget signals={plan.signals} />
        )}

        {/* Actions Bar */}
        <div className="fixed bottom-0 left-0 right-0 bg-white border-t border-slate-200 p-4 md:hidden">
          <div className="max-w-md mx-auto flex gap-3">
            <Button
              variant="outline"
              onClick={refreshPlan}
              disabled={refreshing}
              className="flex-1 min-h-[56px]"
            >
              <RefreshCw className={`w-5 h-5 mr-2 ${refreshing ? 'animate-spin' : ''}`} />
              Refresh Plan
            </Button>
          </div>
        </div>

        {/* Desktop Actions */}
        <div className="hidden md:block mt-6">
          <Button
            variant="outline"
            onClick={refreshPlan}
            disabled={refreshing}
            className="w-full min-h-[56px]"
          >
            <RefreshCw className={`w-5 h-5 mr-2 ${refreshing ? 'animate-spin' : ''}`} />
            Refresh Plan
          </Button>
        </div>
      </div>
    </div>
  );
};

export default ActionPlanView;
