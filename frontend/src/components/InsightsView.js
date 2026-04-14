import React, { useState, useEffect } from "react";
import axios from "axios";
import { Sparkles, RefreshCw, AlertTriangle, TrendingUp, ArrowRight, Target, DollarSign, Shield, Layers } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { motion } from "framer-motion";
import { toast } from "sonner";
import { PieChart, Pie, Cell, ResponsiveContainer, Tooltip, BarChart, Bar, XAxis, YAxis, CartesianGrid } from "recharts";
import { useNumberFormat } from "@/context/NumberFormatContext";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
const API = `${BACKEND_URL}/api`;

const STATUS_COLORS = { critical: "#EF4444", important: "#F59E0B", moderate: "#3B82F6", recommended: "#10B981" };
const CATEGORY_ICONS = { risk: Shield, allocation: Layers, cost: DollarSign, redundancy: Layers, opportunity: TrendingUp, info: Sparkles };

const InsightsView = ({ insights: basicInsights, onRefresh }) => {
  const { fmt } = useNumberFormat();
  const [analysis, setAnalysis] = useState(null);
  const [generating, setGenerating] = useState(false);
  const [loading, setLoading] = useState(true);

  useEffect(() => { fetchAnalysis(); }, []);

  const fetchAnalysis = async () => {
    try {
      const res = await axios.get(`${API}/insights/analysis`, { withCredentials: true });
      if (res.data) setAnalysis(res.data);
    } catch {} finally { setLoading(false); }
  };

  const generate = async () => {
    setGenerating(true);
    try {
      const res = await axios.post(`${API}/insights/generate`, {}, { withCredentials: true });
      setAnalysis(res.data);
      toast.success("Analysis complete!");
      onRefresh();
    } catch { toast.error("Failed to generate"); } finally { setGenerating(false); }
  };

  const ins = analysis?.insights || basicInsights || [];
  const pd = analysis?.problem_distribution || [];
  const ba = analysis?.before_after;
  const funnel = analysis?.action_funnel || [];
  const overlaps = analysis?.overlap_pairs || [];
  const cost = analysis?.cost_leakage;
  const gauge = analysis?.risk_gauge;

  if (loading) return <div className="flex items-center justify-center h-64"><div className="w-8 h-8 border-2 border-emerald-600 border-t-transparent rounded-full animate-spin" /></div>;

  return (
    <div data-testid="insights-view" className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl sm:text-3xl font-medium tracking-tight text-slate-900 dark:text-white" style={{ fontFamily: "'Outfit', sans-serif" }}>AI Portfolio Analysis</h1>
          <p className="text-sm text-slate-500 dark:text-slate-400 mt-1">Deep analysis & actionable recommendations</p>
        </div>
        <Button data-testid="generate-insights-button" onClick={generate} disabled={generating} className="bg-emerald-600 hover:bg-emerald-700 text-white rounded-xl">
          {generating ? <RefreshCw className="w-4 h-4 mr-2 animate-spin" /> : <Sparkles className="w-4 h-4 mr-2" />}
          {generating ? "Analyzing..." : "Analyze Portfolio"}
        </Button>
      </div>

      {!analysis && ins.length === 0 ? (
        <Card className="bg-white dark:bg-slate-800 border-slate-100 dark:border-slate-700 rounded-2xl"><CardContent className="p-12 text-center">
          <Sparkles className="w-12 h-12 text-slate-300 mx-auto mb-4" />
          <h3 className="text-lg font-medium text-slate-900 dark:text-white mb-2" style={{ fontFamily: "'Outfit', sans-serif" }}>No analysis yet</h3>
          <p className="text-sm text-slate-500">Click "Analyze Portfolio" to get AI-powered insights and recommendations.</p>
        </CardContent></Card>
      ) : (
        <>
          {/* Row 1: Problem Donut + Risk Gauge + Before/After */}
          <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
            {/* Problem Distribution Donut */}
            {pd.length > 0 && (
              <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }}>
                <Card className="bg-white dark:bg-slate-800 border-slate-100 dark:border-slate-700 rounded-2xl h-full">
                  <CardContent className="p-6">
                    <h3 className="text-sm font-medium text-slate-900 dark:text-white mb-4" style={{ fontFamily: "'Outfit', sans-serif" }}>Portfolio Issues</h3>
                    <div className="h-40">
                      <ResponsiveContainer width="100%" height="100%">
                        <PieChart>
                          <Pie data={pd} cx="50%" cy="50%" innerRadius={35} outerRadius={60} paddingAngle={2} dataKey="value">
                            {pd.map((d, i) => <Cell key={i} fill={d.color} />)}
                          </Pie>
                          <Tooltip formatter={v => `${v}%`} />
                        </PieChart>
                      </ResponsiveContainer>
                    </div>
                    <div className="space-y-1.5 mt-2">
                      {pd.map(d => (
                        <div key={d.name} className="flex items-center justify-between">
                          <div className="flex items-center gap-2"><div className="w-2.5 h-2.5 rounded-full" style={{ backgroundColor: d.color }} /><span className="text-xs text-slate-600 dark:text-slate-400">{d.name}</span></div>
                          <span className="text-xs font-medium text-slate-900 dark:text-white">{d.value}%</span>
                        </div>
                      ))}
                    </div>
                  </CardContent>
                </Card>
              </motion.div>
            )}

            {/* Risk Gauge */}
            {gauge && gauge.current > 0 && (
              <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.05 }}>
                <Card className="bg-white dark:bg-slate-800 border-slate-100 dark:border-slate-700 rounded-2xl h-full">
                  <CardContent className="p-6">
                    <h3 className="text-sm font-medium text-slate-900 dark:text-white mb-4" style={{ fontFamily: "'Outfit', sans-serif" }}>Risk Assessment</h3>
                    <div className="space-y-5">
                      <div>
                        <div className="flex justify-between text-xs mb-1.5"><span className="text-slate-500">Current Risk</span><span className="font-medium text-red-500">{gauge.current_label} ({gauge.current}/100)</span></div>
                        <div className="w-full h-3 rounded-full bg-slate-100 dark:bg-slate-700 overflow-hidden">
                          <div className="h-full rounded-full transition-all duration-700" style={{ width: `${gauge.current}%`, background: "linear-gradient(90deg, #10B981, #F59E0B, #EF4444)" }} />
                        </div>
                      </div>
                      <div className="flex items-center justify-center text-slate-400"><ArrowRight className="w-4 h-4" /></div>
                      <div>
                        <div className="flex justify-between text-xs mb-1.5"><span className="text-slate-500">After Actions</span><span className="font-medium text-emerald-600">{gauge.target_label} ({gauge.target}/100)</span></div>
                        <div className="w-full h-3 rounded-full bg-slate-100 dark:bg-slate-700 overflow-hidden">
                          <div className="h-full rounded-full bg-emerald-500 transition-all duration-700" style={{ width: `${gauge.target}%` }} />
                        </div>
                      </div>
                    </div>
                    {cost && cost.annual_loss > 0 && (
                      <div className="mt-5 p-3 bg-red-50 dark:bg-red-900/20 rounded-xl border border-red-100 dark:border-red-800">
                        <p className="text-[10px] font-bold tracking-wider uppercase text-red-400 mb-1">Annual Cost Leakage</p>
                        <p className="text-lg font-semibold text-red-600 dark:text-red-400" style={{ fontFamily: "'Outfit', sans-serif" }}>{fmt(cost.annual_loss)}</p>
                        <p className="text-[10px] text-red-400 mt-0.5">{cost.detail}</p>
                      </div>
                    )}
                  </CardContent>
                </Card>
              </motion.div>
            )}

            {/* Before/After Impact */}
            {ba && ba.before.return_pct > 0 && (
              <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.1 }}>
                <Card className="bg-white dark:bg-slate-800 border-slate-100 dark:border-slate-700 rounded-2xl h-full">
                  <CardContent className="p-6">
                    <h3 className="text-sm font-medium text-slate-900 dark:text-white mb-4" style={{ fontFamily: "'Outfit', sans-serif" }}>Impact of Actions</h3>
                    <div className="h-48">
                      <ResponsiveContainer width="100%" height="100%">
                        <BarChart data={[
                          { name: "Returns %", before: ba.before.return_pct, after: ba.after.return_pct },
                          { name: "Risk Score", before: ba.before.risk_score, after: ba.after.risk_score },
                          { name: "Expense %", before: ba.before.expense_ratio * 10, after: ba.after.expense_ratio * 10 },
                        ]} margin={{ top: 5, right: 5, left: -15, bottom: 5 }}>
                          <CartesianGrid strokeDasharray="3 3" stroke="#F1F5F9" />
                          <XAxis dataKey="name" tick={{ fontSize: 10, fill: "#94A3B8" }} axisLine={false} tickLine={false} />
                          <YAxis tick={{ fontSize: 10, fill: "#94A3B8" }} axisLine={false} tickLine={false} />
                          <Tooltip contentStyle={{ borderRadius: 10, fontSize: 12, border: "1px solid #E2E8F0" }} />
                          <Bar dataKey="before" fill="#EF4444" radius={[4, 4, 0, 0]} barSize={20} name="Before" />
                          <Bar dataKey="after" fill="#10B981" radius={[4, 4, 0, 0]} barSize={20} name="After" />
                        </BarChart>
                      </ResponsiveContainer>
                    </div>
                    <div className="flex items-center justify-center gap-4 mt-2 text-[10px]">
                      <div className="flex items-center gap-1"><div className="w-2.5 h-2.5 rounded bg-red-500" />Before</div>
                      <div className="flex items-center gap-1"><div className="w-2.5 h-2.5 rounded bg-emerald-500" />After</div>
                    </div>
                  </CardContent>
                </Card>
              </motion.div>
            )}
          </div>

          {/* Priority Matrix */}
          {ins.length > 0 && (
            <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.15 }}>
              <Card className="bg-white dark:bg-slate-800 border-slate-100 dark:border-slate-700 rounded-2xl">
                <CardContent className="p-6 md:p-8">
                  <h3 className="text-lg font-medium text-slate-900 dark:text-white mb-6" style={{ fontFamily: "'Outfit', sans-serif" }}>Priority Matrix</h3>
                  <div className="relative border border-slate-200 dark:border-slate-700 rounded-xl overflow-hidden" style={{ minHeight: 360 }}>
                    {/* Axes labels */}
                    <div className="absolute left-2 top-1/2 -translate-y-1/2 -rotate-90 text-[10px] font-bold tracking-wider uppercase text-slate-400 whitespace-nowrap">Impact</div>
                    <div className="absolute bottom-2 left-1/2 -translate-x-1/2 text-[10px] font-bold tracking-wider uppercase text-slate-400">Effort</div>
                    {/* Grid */}
                    <div className="grid grid-cols-2 grid-rows-2 ml-6 mb-6" style={{ minHeight: 340 }}>
                      {/* High Impact / Low Effort (DO FIRST) */}
                      <div className="border-r border-b border-slate-100 dark:border-slate-700 p-3 bg-emerald-50/50 dark:bg-emerald-900/10">
                        <p className="text-[9px] font-bold tracking-wider uppercase text-emerald-600 mb-2">Do First</p>
                        <div className="space-y-2">
                          {ins.filter(i => i.impact === "high" && i.effort !== "high").map((i, idx) => (
                            <div key={idx} className="p-2.5 bg-white dark:bg-slate-800 rounded-lg border border-emerald-200 dark:border-emerald-800 shadow-sm">
                              <p className="text-xs font-medium text-slate-900 dark:text-white">{i.title}</p>
                              <p className="text-[10px] text-slate-500 mt-0.5 line-clamp-2">{i.description}</p>
                              {i.current_value && <p className="text-[10px] text-slate-400 mt-1">{i.current_value} → {i.target_value}</p>}
                            </div>
                          ))}
                        </div>
                      </div>
                      {/* High Impact / High Effort (PLAN) */}
                      <div className="border-b border-slate-100 dark:border-slate-700 p-3 bg-amber-50/50 dark:bg-amber-900/10">
                        <p className="text-[9px] font-bold tracking-wider uppercase text-amber-600 mb-2">Plan & Schedule</p>
                        <div className="space-y-2">
                          {ins.filter(i => i.impact === "high" && i.effort === "high").map((i, idx) => (
                            <div key={idx} className="p-2.5 bg-white dark:bg-slate-800 rounded-lg border border-amber-200 dark:border-amber-800 shadow-sm">
                              <p className="text-xs font-medium text-slate-900 dark:text-white">{i.title}</p>
                              <p className="text-[10px] text-slate-500 mt-0.5 line-clamp-2">{i.description}</p>
                            </div>
                          ))}
                        </div>
                      </div>
                      {/* Low Impact / Low Effort (QUICK WINS) */}
                      <div className="border-r border-slate-100 dark:border-slate-700 p-3 bg-blue-50/50 dark:bg-blue-900/10">
                        <p className="text-[9px] font-bold tracking-wider uppercase text-blue-600 mb-2">Quick Wins</p>
                        <div className="space-y-2">
                          {ins.filter(i => i.impact !== "high" && i.effort !== "high").map((i, idx) => (
                            <div key={idx} className="p-2.5 bg-white dark:bg-slate-800 rounded-lg border border-blue-200 dark:border-blue-800 shadow-sm">
                              <p className="text-xs font-medium text-slate-900 dark:text-white">{i.title}</p>
                              <p className="text-[10px] text-slate-500 mt-0.5 line-clamp-2">{i.description}</p>
                            </div>
                          ))}
                        </div>
                      </div>
                      {/* Low Impact / High Effort (DEFER) */}
                      <div className="p-3 bg-slate-50/50 dark:bg-slate-800/50">
                        <p className="text-[9px] font-bold tracking-wider uppercase text-slate-400 mb-2">Defer</p>
                        <div className="space-y-2">
                          {ins.filter(i => i.impact !== "high" && i.effort === "high").map((i, idx) => (
                            <div key={idx} className="p-2.5 bg-white dark:bg-slate-800 rounded-lg border border-slate-200 dark:border-slate-700 shadow-sm">
                              <p className="text-xs font-medium text-slate-900 dark:text-white">{i.title}</p>
                              <p className="text-[10px] text-slate-500 mt-0.5 line-clamp-2">{i.description}</p>
                            </div>
                          ))}
                        </div>
                      </div>
                    </div>
                  </div>
                </CardContent>
              </Card>
            </motion.div>
          )}

          {/* Action Funnel */}
          {funnel.length > 0 && (
            <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.2 }}>
              <Card className="bg-white dark:bg-slate-800 border-slate-100 dark:border-slate-700 rounded-2xl">
                <CardContent className="p-6 md:p-8">
                  <h3 className="text-lg font-medium text-slate-900 dark:text-white mb-6" style={{ fontFamily: "'Outfit', sans-serif" }}>Action Funnel</h3>
                  <div className="space-y-3">
                    {funnel.map((step, i) => (
                      <div key={i} className="flex items-start gap-4">
                        <div className="flex flex-col items-center">
                          <div className="w-8 h-8 rounded-full flex items-center justify-center text-white text-xs font-bold" style={{ backgroundColor: STATUS_COLORS[step.status] || "#94A3B8" }}>{step.step}</div>
                          {i < funnel.length - 1 && <div className="w-0.5 h-8 bg-slate-200 dark:bg-slate-700 mt-1" />}
                        </div>
                        <div className="flex-1 pb-2">
                          <p className="text-sm font-medium text-slate-900 dark:text-white">{step.title}</p>
                          <p className="text-xs text-slate-500 dark:text-slate-400 mt-0.5">{step.detail}</p>
                        </div>
                        <span className="text-[10px] font-bold uppercase tracking-wider px-2 py-0.5 rounded-full" style={{ backgroundColor: `${STATUS_COLORS[step.status]}15`, color: STATUS_COLORS[step.status] }}>{step.status}</span>
                      </div>
                    ))}
                    <div className="flex items-start gap-4">
                      <div className="w-8 h-8 rounded-full bg-emerald-500 flex items-center justify-center"><Target className="w-4 h-4 text-white" /></div>
                      <p className="text-sm font-medium text-emerald-600 pt-1.5">Optimized Portfolio</p>
                    </div>
                  </div>
                </CardContent>
              </Card>
            </motion.div>
          )}

          {/* Insight Cards with Progress Bars */}
          {ins.length > 0 && (
            <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.25 }}>
              <Card className="bg-white dark:bg-slate-800 border-slate-100 dark:border-slate-700 rounded-2xl">
                <CardContent className="p-6 md:p-8">
                  <h3 className="text-lg font-medium text-slate-900 dark:text-white mb-6" style={{ fontFamily: "'Outfit', sans-serif" }}>Detailed Insights</h3>
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    {ins.map((i, idx) => {
                      const Icon = CATEGORY_ICONS[i.category] || Sparkles;
                      const colors = { warning: "border-amber-200 bg-amber-50/80 dark:bg-amber-900/15 dark:border-amber-800", opportunity: "border-emerald-200 bg-emerald-50/80 dark:bg-emerald-900/15 dark:border-emerald-800", action: "border-blue-200 bg-blue-50/80 dark:bg-blue-900/15 dark:border-blue-800", info: "border-slate-200 bg-slate-50/80 dark:bg-slate-800/50 dark:border-slate-700" };
                      return (
                        <div key={idx} className={`p-4 rounded-xl border ${colors[i.type] || colors.info}`}>
                          <div className="flex items-start gap-3">
                            <Icon className="w-4 h-4 text-slate-500 mt-0.5 flex-shrink-0" strokeWidth={1.5} />
                            <div className="flex-1">
                              <p className="text-sm font-medium text-slate-900 dark:text-white">{i.title}</p>
                              <p className="text-xs text-slate-500 dark:text-slate-400 mt-1 leading-relaxed">{i.description}</p>
                              {(i.current_value || i.progress > 0) && (
                                <div className="mt-3">
                                  {i.current_value && <p className="text-[10px] text-slate-400 mb-1">Current: {i.current_value} → Target: {i.target_value}</p>}
                                  <div className="w-full h-1.5 rounded-full bg-slate-200 dark:bg-slate-700 overflow-hidden">
                                    <div className="h-full rounded-full bg-emerald-500 transition-all" style={{ width: `${Math.min(i.progress || 0, 100)}%` }} />
                                  </div>
                                  <p className="text-[10px] text-slate-400 mt-0.5">{i.progress || 0}% aligned</p>
                                </div>
                              )}
                            </div>
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </CardContent>
              </Card>
            </motion.div>
          )}

          {/* Fund Overlap Heatmap */}
          {overlaps.length > 0 && (
            <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.3 }}>
              <Card className="bg-white dark:bg-slate-800 border-slate-100 dark:border-slate-700 rounded-2xl">
                <CardContent className="p-6 md:p-8">
                  <h3 className="text-lg font-medium text-slate-900 dark:text-white mb-6" style={{ fontFamily: "'Outfit', sans-serif" }}>Fund Overlap Analysis</h3>
                  <div className="space-y-3">
                    {overlaps.map((o, i) => {
                      const high = o.overlap_pct >= 70;
                      const med = o.overlap_pct >= 40;
                      return (
                        <div key={i} className={`p-4 rounded-xl border ${high ? "border-red-200 bg-red-50/50 dark:bg-red-900/15 dark:border-red-800" : med ? "border-amber-200 bg-amber-50/50 dark:bg-amber-900/15 dark:border-amber-800" : "border-slate-200 bg-slate-50/50 dark:bg-slate-800/50 dark:border-slate-700"}`}>
                          <div className="flex items-center justify-between mb-2">
                            <div className="flex-1">
                              <p className="text-xs text-slate-900 dark:text-white font-medium">{o.fund_a}</p>
                              <p className="text-[10px] text-slate-400">overlaps with</p>
                              <p className="text-xs text-slate-900 dark:text-white font-medium">{o.fund_b}</p>
                            </div>
                            <div className={`text-lg font-bold ${high ? "text-red-500" : med ? "text-amber-500" : "text-slate-400"}`} style={{ fontFamily: "'JetBrains Mono', monospace" }}>{o.overlap_pct}%</div>
                          </div>
                          <div className="w-full h-2 rounded-full bg-slate-200 dark:bg-slate-700 overflow-hidden">
                            <div className={`h-full rounded-full ${high ? "bg-red-500" : med ? "bg-amber-500" : "bg-slate-400"}`} style={{ width: `${o.overlap_pct}%` }} />
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </CardContent>
              </Card>
            </motion.div>
          )}
        </>
      )}

      <p className="text-xs text-slate-400 text-center">AI-generated analysis for educational purposes. Consult a SEBI-registered advisor.</p>
    </div>
  );
};

export default InsightsView;
