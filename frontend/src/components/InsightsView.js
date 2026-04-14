import React, { useState } from "react";
import axios from "axios";
import { Lightbulb, AlertTriangle, TrendingUp, Info, RefreshCw, Sparkles } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { motion } from "framer-motion";
import { toast } from "sonner";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
const API = `${BACKEND_URL}/api`;

const typeConfig = {
  warning: { icon: AlertTriangle, bg: "bg-amber-50", border: "border-amber-200", iconColor: "text-amber-500" },
  opportunity: { icon: TrendingUp, bg: "bg-emerald-50", border: "border-emerald-200", iconColor: "text-emerald-600" },
  action: { icon: Sparkles, bg: "bg-blue-50", border: "border-blue-200", iconColor: "text-blue-500" },
  info: { icon: Info, bg: "bg-slate-50", border: "border-slate-200", iconColor: "text-slate-500" },
};

const priorityBadge = {
  high: "bg-red-100 text-red-700",
  medium: "bg-amber-100 text-amber-700",
  low: "bg-emerald-100 text-emerald-700",
};

const InsightsView = ({ insights, onRefresh }) => {
  const [generating, setGenerating] = useState(false);

  const generateInsights = async () => {
    setGenerating(true);
    try {
      const res = await axios.post(`${API}/insights/generate`, {}, { withCredentials: true });
      if (res.data.message) {
        toast.info(res.data.message);
      } else {
        toast.success("Insights generated!");
      }
      onRefresh();
    } catch {
      toast.error("Failed to generate insights");
    } finally {
      setGenerating(false);
    }
  };

  return (
    <div data-testid="insights-view">
      {/* Header */}
      <div className="flex items-center justify-between mb-8">
        <div>
          <h1 className="text-2xl sm:text-3xl font-medium tracking-tight text-slate-900" style={{ fontFamily: "'Outfit', sans-serif" }}>
            AI Insights
          </h1>
          <p className="text-sm text-slate-500 mt-1">Personalized recommendations for your portfolio</p>
        </div>
        <Button
          data-testid="generate-insights-button"
          onClick={generateInsights}
          disabled={generating}
          className="bg-emerald-600 hover:bg-emerald-700 text-white rounded-xl"
        >
          {generating ? (
            <RefreshCw className="w-4 h-4 mr-2 animate-spin" strokeWidth={1.5} />
          ) : (
            <Sparkles className="w-4 h-4 mr-2" strokeWidth={1.5} />
          )}
          {generating ? "Analyzing..." : "Generate Insights"}
        </Button>
      </div>

      {/* Insights Grid */}
      {insights.length === 0 ? (
        <Card className="bg-white border-slate-100 rounded-2xl shadow-none">
          <CardContent className="p-12 text-center">
            <div className="w-14 h-14 bg-emerald-50 rounded-2xl flex items-center justify-center mx-auto mb-6">
              <Lightbulb className="w-7 h-7 text-emerald-600" strokeWidth={1.5} />
            </div>
            <h3 className="text-lg font-medium text-slate-900 mb-2" style={{ fontFamily: "'Outfit', sans-serif" }}>
              No insights yet
            </h3>
            <p className="text-sm text-slate-500 mb-6">
              Add holdings to your portfolio, then click "Generate Insights" for AI-powered recommendations.
            </p>
          </CardContent>
        </Card>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          {insights.map((ins, i) => {
            const config = typeConfig[ins.type] || typeConfig.info;
            const Icon = config.icon;
            return (
              <motion.div
                key={ins.insight_id}
                initial={{ opacity: 0, y: 12 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: i * 0.08 }}
              >
                <Card className={`${config.bg} ${config.border} border rounded-2xl shadow-none hover:shadow-md transition-all duration-300`}>
                  <CardContent className="p-6">
                    <div className="flex items-start gap-4">
                      <div className={`w-10 h-10 rounded-xl bg-white flex items-center justify-center flex-shrink-0`}>
                        <Icon className={`w-5 h-5 ${config.iconColor}`} strokeWidth={1.5} />
                      </div>
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2 mb-2">
                          <h3 className="text-base font-medium text-slate-900" style={{ fontFamily: "'Outfit', sans-serif" }}>
                            {ins.title}
                          </h3>
                          <span className={`text-[10px] font-bold uppercase tracking-wider px-2 py-0.5 rounded-full ${priorityBadge[ins.priority] || priorityBadge.medium}`}>
                            {ins.priority}
                          </span>
                        </div>
                        <p className="text-sm text-slate-600 leading-relaxed">{ins.description}</p>
                      </div>
                    </div>
                  </CardContent>
                </Card>
              </motion.div>
            );
          })}
        </div>
      )}

      {/* Disclaimer */}
      <p className="text-xs text-slate-400 text-center mt-8">
        These insights are AI-generated for educational purposes. Always consult a SEBI-registered investment advisor before making decisions.
      </p>
    </div>
  );
};

export default InsightsView;
