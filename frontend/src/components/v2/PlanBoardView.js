import React, { useState, useEffect } from "react";
import axios from "axios";
import { Calendar, CheckCircle2, Clock, TrendingUp, RefreshCw, Plus, Filter, LayoutGrid, List } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { toast } from "sonner";
import PlanCard from "./PlanCard";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
const API = `${BACKEND_URL}/api`;

const PlanBoardView = () => {
  const [plans, setPlans] = useState([]);
  const [activePlan, setActivePlan] = useState(null);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState("active"); // Default to "active" to hide archived plans
  const [generating, setGenerating] = useState(false);
  const [compactView, setCompactView] = useState(false);

  useEffect(() => {
    fetchPlans();
  }, []);

  const fetchPlans = async () => {
    try {
      setLoading(true);
      const [historyRes, activeRes] = await Promise.all([
        axios.get(`${API}/plans/history?limit=20`, { withCredentials: true }),
        axios.get(`${API}/plans/active`, { withCredentials: true })
      ]);
      
      const allPlans = historyRes.data.plans || [];
      const active = activeRes.data.plan;
      
      // Combine active plan if it exists and not in history
      if (active && !allPlans.find(p => p.plan_id === active.plan_id)) {
        allPlans.unshift(active);
      }
      
      setPlans(allPlans);
      setActivePlan(active);
    } catch (error) {
      console.error("Error fetching plans:", error);
      toast.error("Failed to load plans");
    } finally {
      setLoading(false);
    }
  };

  const generateNewPlan = async () => {
    try {
      setGenerating(true);
      toast.info("Generating your action plan...");
      
      const res = await axios.post(`${API}/plans/generate`, {}, { withCredentials: true });
      const newPlan = res.data.plan;
      
      // Auto-save as active
      await axios.post(`${API}/plans/${newPlan.plan_id}/save`, {}, { withCredentials: true });
      
      await fetchPlans();
      toast.success("New plan generated successfully!");
    } catch (error) {
      console.error("Error generating plan:", error);
      toast.error(error.response?.data?.detail || "Failed to generate plan");
    } finally {
      setGenerating(false);
    }
  };

  const filteredPlans = plans.filter(plan => {
    if (filter === "all") return true;
    if (filter === "active") return plan.status === "active";
    if (filter === "completed") return plan.status === "completed";
    if (filter === "archived") return plan.status === "archived";
    return true;
  });

  if (loading) {
    return (
      <div className="min-h-screen bg-[#FAF9F6] flex items-center justify-center">
        <div className="text-center">
          <RefreshCw className="w-8 h-8 animate-spin mx-auto text-slate-600 mb-2" />
          <p className="text-slate-600">Loading your plans...</p>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-[#FAF9F6] py-8">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        {/* Header */}
        <div className="mb-8">
          <div className="flex items-center justify-between mb-4">
            <div>
              <h1 className="text-4xl font-black tracking-tight text-slate-900 mb-2">
                Plan Action Board
              </h1>
              <p className="text-slate-600">
                Manage all your investment action plans in one place
              </p>
            </div>
            <Button
              onClick={generateNewPlan}
              disabled={generating}
              size="lg"
              className="min-h-[48px] bg-emerald-600 hover:bg-emerald-700"
            >
              {generating ? (
                <RefreshCw className="w-5 h-5 mr-2 animate-spin" />
              ) : (
                <Plus className="w-5 h-5 mr-2" />
              )}
              Generate New Plan
            </Button>
          </div>

          {/* Filters */}
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-4">
              <div className="flex items-center gap-2">
                <Filter className="w-4 h-4 text-slate-600" />
                <span className="text-sm font-medium text-slate-700">Filter:</span>
              </div>
              <Select value={filter} onValueChange={setFilter}>
                <SelectTrigger className="w-40">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">All Plans</SelectItem>
                  <SelectItem value="active">Active</SelectItem>
                  <SelectItem value="completed">Completed</SelectItem>
                  <SelectItem value="archived">Archived</SelectItem>
                </SelectContent>
              </Select>
              <Badge variant="outline" className="text-sm">
                {filteredPlans.length} plan{filteredPlans.length !== 1 ? 's' : ''}
              </Badge>
            </div>
            
            {/* Compact View Toggle */}
            <Button
              variant="outline"
              size="sm"
              onClick={() => setCompactView(!compactView)}
              className="flex items-center gap-2"
            >
              {compactView ? (
                <>
                  <LayoutGrid className="w-4 h-4" />
                  Detailed View
                </>
              ) : (
                <>
                  <List className="w-4 h-4" />
                  Compact View
                </>
              )}
            </Button>
          </div>
        </div>

        {/* Plans Grid */}
        {filteredPlans.length === 0 ? (
          <Card className="p-12 text-center">
            <div className="w-16 h-16 bg-slate-100 rounded-full flex items-center justify-center mx-auto mb-4">
              <TrendingUp className="w-8 h-8 text-slate-400" />
            </div>
            <h3 className="text-xl font-bold text-slate-900 mb-2">
              No Plans Found
            </h3>
            <p className="text-slate-600 mb-6">
              {filter === "all" 
                ? "Generate your first action plan to get started"
                : `No ${filter} plans found`
              }
            </p>
            {filter === "all" && (
              <Button onClick={generateNewPlan} disabled={generating}>
                <Plus className="w-4 h-4 mr-2" />
                Generate Your First Plan
              </Button>
            )}
          </Card>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
            {filteredPlans.map(plan => (
              <PlanCard
                key={plan.plan_id}
                plan={plan}
                isActive={activePlan?.plan_id === plan.plan_id}
                onRefresh={fetchPlans}
                compactMode={compactView}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  );
};

export default PlanBoardView;
