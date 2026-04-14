import React, { useState, useEffect, useMemo } from "react";
import axios from "axios";
import {
  Sparkles, RefreshCw, AlertTriangle, TrendingUp, TrendingDown,
  ArrowRight, Target, DollarSign, Shield, Layers, Building2,
  BarChart3, ArrowUpRight, ArrowDownRight, ChevronDown, ChevronUp, Filter,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { motion } from "framer-motion";
import { toast } from "sonner";
import {
  PieChart, Pie, Cell, ResponsiveContainer, Tooltip,
  BarChart, Bar, XAxis, YAxis, CartesianGrid,
} from "recharts";
import { useNumberFormat } from "@/context/NumberFormatContext";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
const API = `${BACKEND_URL}/api`;

const STATUS_COLORS = { critical: "#EF4444", important: "#F59E0B", moderate: "#3B82F6", recommended: "#10B981" };
const CATEGORY_ICONS = { risk: Shield, allocation: Layers, cost: DollarSign, redundancy: Layers, opportunity: TrendingUp, info: Sparkles };
const RISK_COLORS = { high: "#EF4444", medium: "#F59E0B", low: "#10B981" };
const CHART_COLORS = ["#059669", "#3B82F6", "#F59E0B", "#8B5CF6", "#EF4444", "#EC4899", "#14B8A6", "#F97316", "#6366F1", "#84CC16"];

const InsightsView = ({ insights: basicInsights, onRefresh }) => {
  const { fmt } = useNumberFormat();
  const [analysis, setAnalysis] = useState(null);
  const [deepAnalytics, setDeepAnalytics] = useState(null);
  const [fundPerformance, setFundPerformance] = useState(null);
  const [generating, setGenerating] = useState(false);
  const [loadingBenchmark, setLoadingBenchmark] = useState(false);
  const [loading, setLoading] = useState(true);
  const [activeTab, setActiveTab] = useState("overview");
  const [perfSort, setPerfSort] = useState("pct_return");
  const [perfDir, setPerfDir] = useState("desc");
  const [perfFilter, setPerfFilter] = useState("all");

  useEffect(() => {
    Promise.all([fetchAnalysis(), fetchDeepAnalytics()]).finally(() => setLoading(false));
  }, []);

  const fetchAnalysis = async () => {
    try {
      const res = await axios.get(`${API}/insights/analysis`, { withCredentials: true });
      if (res.data) setAnalysis(res.data);
    } catch {}
  };

  const fetchDeepAnalytics = async () => {
    try {
      const res = await axios.get(`${API}/portfolio/deep-analytics`, { withCredentials: true });
      if (res.data) setDeepAnalytics(res.data);
    } catch {}
  };

  const fetchFundPerformance = async () => {
    setLoadingBenchmark(true);
    try {
      const res = await axios.get(`${API}/portfolio/fund-performance`, { withCredentials: true });
      if (res.data) setFundPerformance(res.data);
    } catch {} finally { setLoadingBenchmark(false); }
  };

  const generate = async () => {
    setGenerating(true);
    try {
      const [insRes] = await Promise.all([
        axios.post(`${API}/insights/generate`, {}, { withCredentials: true }),
        fetchDeepAnalytics(),
      ]);
      setAnalysis(insRes.data);
      toast.success("Analysis complete!");
      onRefresh();
    } catch {
      toast.error("Failed to generate");
    } finally {
      setGenerating(false);
    }
  };

  const ins = analysis?.insights || basicInsights || [];
  const pd = analysis?.problem_distribution || [];
  const ba = analysis?.before_after;
  const funnel = analysis?.action_funnel || [];
  const cost = analysis?.cost_leakage;
  const gauge = analysis?.risk_gauge;

  const overexposure = deepAnalytics?.overexposure || {};
  const overlapMatrix = deepAnalytics?.overlap_matrix || [];
  const perfCards = deepAnalytics?.performance_cards || [];

  // Sort/filter performance cards
  const sortedPerfCards = useMemo(() => {
    let filtered = perfCards;
    if (perfFilter !== "all") {
      filtered = filtered.filter(c => c.asset_type === perfFilter);
    }
    return [...filtered].sort((a, b) => {
      const mul = perfDir === "desc" ? -1 : 1;
      return mul * ((a[perfSort] || 0) - (b[perfSort] || 0));
    });
  }, [perfCards, perfSort, perfDir, perfFilter]);

  const tabs = [
    { id: "overview", label: "AI Overview" },
    { id: "benchmark", label: "Benchmark" },
    { id: "overexposure", label: "Overexposure" },
    { id: "overlap", label: "Fund Overlap" },
    { id: "performance", label: "Performance" },
  ];

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="w-8 h-8 border-2 border-emerald-600 border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  return (
    <div data-testid="insights-view" className="space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        <div>
          <h1
            className="text-2xl sm:text-3xl font-medium tracking-tight text-slate-900 dark:text-white"
            style={{ fontFamily: "'Outfit', sans-serif" }}
          >
            AI Portfolio Analysis
          </h1>
          <p className="text-sm text-slate-500 dark:text-slate-400 mt-1">
            Deep analysis & actionable recommendations
          </p>
        </div>
        <Button
          data-testid="generate-insights-button"
          onClick={generate}
          disabled={generating}
          className="bg-emerald-600 hover:bg-emerald-700 text-white rounded-xl"
        >
          {generating ? (
            <RefreshCw className="w-4 h-4 mr-2 animate-spin" />
          ) : (
            <Sparkles className="w-4 h-4 mr-2" />
          )}
          {generating ? "Analyzing..." : "Analyze Portfolio"}
        </Button>
      </div>

      {/* Tab Navigation */}
      <div className="flex gap-1 bg-slate-100 dark:bg-slate-800 rounded-xl p-1" data-testid="insights-tabs">
        {tabs.map(tab => (
          <button
            key={tab.id}
            data-testid={`tab-${tab.id}`}
            onClick={() => setActiveTab(tab.id)}
            className={`flex-1 px-4 py-2 text-sm font-medium rounded-lg transition-all ${
              activeTab === tab.id
                ? "bg-white dark:bg-slate-700 text-slate-900 dark:text-white shadow-sm"
                : "text-slate-500 dark:text-slate-400 hover:text-slate-700 dark:hover:text-slate-300"
            }`}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {!analysis && ins.length === 0 && !deepAnalytics ? (
        <Card className="bg-white dark:bg-slate-800 border-slate-100 dark:border-slate-700 rounded-2xl">
          <CardContent className="p-12 text-center">
            <Sparkles className="w-12 h-12 text-slate-300 mx-auto mb-4" />
            <h3
              className="text-lg font-medium text-slate-900 dark:text-white mb-2"
              style={{ fontFamily: "'Outfit', sans-serif" }}
            >
              No analysis yet
            </h3>
            <p className="text-sm text-slate-500">
              Click "Analyze Portfolio" to get AI-powered insights and recommendations.
            </p>
          </CardContent>
        </Card>
      ) : (
        <>
          {/* ══════════════ TAB: AI OVERVIEW ══════════════ */}
          {activeTab === "overview" && (
            <OverviewTab
              pd={pd}
              gauge={gauge}
              ba={ba}
              cost={cost}
              ins={ins}
              funnel={funnel}
              fmt={fmt}
            />
          )}

          {/* ══════════════ TAB: BENCHMARK ══════════════ */}
          {activeTab === "benchmark" && (
            <BenchmarkTab
              data={fundPerformance}
              loading={loadingBenchmark}
              onLoad={fetchFundPerformance}
              fmt={fmt}
            />
          )}

          {/* ══════════════ TAB: OVEREXPOSURE ══════════════ */}
          {activeTab === "overexposure" && (
            <OverexposureTab overexposure={overexposure} fmt={fmt} />
          )}

          {/* ══════════════ TAB: FUND OVERLAP ══════════════ */}
          {activeTab === "overlap" && (
            <OverlapTab overlaps={overlapMatrix} />
          )}

          {/* ══════════════ TAB: PERFORMANCE ══════════════ */}
          {activeTab === "performance" && (
            <PerformanceTab
              cards={sortedPerfCards}
              allCards={perfCards}
              sort={perfSort}
              dir={perfDir}
              filter={perfFilter}
              setSort={setPerfSort}
              setDir={setPerfDir}
              setFilter={setPerfFilter}
              fmt={fmt}
            />
          )}
        </>
      )}

      <p className="text-xs text-slate-400 text-center">
        AI-generated analysis for educational purposes. Consult a SEBI-registered advisor.
      </p>
    </div>
  );
};

// ════════════════════════════════════════
// OVERVIEW TAB (existing AI analysis)
// ════════════════════════════════════════
const OverviewTab = ({ pd, gauge, ba, cost, ins, funnel, fmt }) => (
  <div className="space-y-6">
    {/* Row 1: Problem Donut + Risk Gauge + Before/After */}
    <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
      {pd.length > 0 && (
        <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }}>
          <Card className="bg-white dark:bg-slate-800 border-slate-100 dark:border-slate-700 rounded-2xl h-full">
            <CardContent className="p-6">
              <h3 className="text-sm font-medium text-slate-900 dark:text-white mb-4" style={{ fontFamily: "'Outfit', sans-serif" }}>
                Portfolio Issues
              </h3>
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
                    <div className="flex items-center gap-2">
                      <div className="w-2.5 h-2.5 rounded-full" style={{ backgroundColor: d.color }} />
                      <span className="text-xs text-slate-600 dark:text-slate-400">{d.name}</span>
                    </div>
                    <span className="text-xs font-medium text-slate-900 dark:text-white">{d.value}%</span>
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>
        </motion.div>
      )}

      {gauge && gauge.current > 0 && (
        <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.05 }}>
          <Card className="bg-white dark:bg-slate-800 border-slate-100 dark:border-slate-700 rounded-2xl h-full">
            <CardContent className="p-6">
              <h3 className="text-sm font-medium text-slate-900 dark:text-white mb-4" style={{ fontFamily: "'Outfit', sans-serif" }}>
                Risk Assessment
              </h3>
              <div className="space-y-5">
                <div>
                  <div className="flex justify-between text-xs mb-1.5">
                    <span className="text-slate-500">Current Risk</span>
                    <span className="font-medium text-red-500">{gauge.current_label} ({gauge.current}/100)</span>
                  </div>
                  <div className="w-full h-3 rounded-full bg-slate-100 dark:bg-slate-700 overflow-hidden">
                    <div className="h-full rounded-full transition-all duration-700" style={{ width: `${gauge.current}%`, background: "linear-gradient(90deg, #10B981, #F59E0B, #EF4444)" }} />
                  </div>
                </div>
                <div className="flex items-center justify-center text-slate-400">
                  <ArrowRight className="w-4 h-4" />
                </div>
                <div>
                  <div className="flex justify-between text-xs mb-1.5">
                    <span className="text-slate-500">After Actions</span>
                    <span className="font-medium text-emerald-600">{gauge.target_label} ({gauge.target}/100)</span>
                  </div>
                  <div className="w-full h-3 rounded-full bg-slate-100 dark:bg-slate-700 overflow-hidden">
                    <div className="h-full rounded-full bg-emerald-500 transition-all duration-700" style={{ width: `${gauge.target}%` }} />
                  </div>
                </div>
              </div>
              {cost && cost.annual_loss > 0 && (
                <div className="mt-5 p-3 bg-red-50 dark:bg-red-900/20 rounded-xl border border-red-100 dark:border-red-800">
                  <p className="text-[10px] font-bold tracking-wider uppercase text-red-400 mb-1">Annual Cost Leakage</p>
                  <p className="text-lg font-semibold text-red-600 dark:text-red-400" style={{ fontFamily: "'Outfit', sans-serif" }}>
                    {fmt(cost.annual_loss)}
                  </p>
                  <p className="text-[10px] text-red-400 mt-0.5">{cost.detail}</p>
                </div>
              )}
            </CardContent>
          </Card>
        </motion.div>
      )}

      {ba && ba.before.return_pct > 0 && (
        <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.1 }}>
          <Card className="bg-white dark:bg-slate-800 border-slate-100 dark:border-slate-700 rounded-2xl h-full">
            <CardContent className="p-6">
              <h3 className="text-sm font-medium text-slate-900 dark:text-white mb-4" style={{ fontFamily: "'Outfit', sans-serif" }}>
                Impact of Actions
              </h3>
              <div className="h-48">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart
                    data={[
                      { name: "Returns %", before: ba.before.return_pct, after: ba.after.return_pct },
                      { name: "Risk Score", before: ba.before.risk_score, after: ba.after.risk_score },
                      { name: "Expense %", before: ba.before.expense_ratio * 10, after: ba.after.expense_ratio * 10 },
                    ]}
                    margin={{ top: 5, right: 5, left: -15, bottom: 5 }}
                  >
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
    {ins.length > 0 && <PriorityMatrix ins={ins} />}

    {/* Action Funnel */}
    {funnel.length > 0 && <ActionFunnel funnel={funnel} />}

    {/* Detailed Insight Cards */}
    {ins.length > 0 && <InsightCards ins={ins} />}
  </div>
);

const PriorityMatrix = ({ ins }) => (
  <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.15 }}>
    <Card className="bg-white dark:bg-slate-800 border-slate-100 dark:border-slate-700 rounded-2xl">
      <CardContent className="p-6 md:p-8">
        <h3 className="text-lg font-medium text-slate-900 dark:text-white mb-6" style={{ fontFamily: "'Outfit', sans-serif" }}>Priority Matrix</h3>
        <div className="relative border border-slate-200 dark:border-slate-700 rounded-xl overflow-hidden" style={{ minHeight: 360 }}>
          <div className="absolute left-2 top-1/2 -translate-y-1/2 -rotate-90 text-[10px] font-bold tracking-wider uppercase text-slate-400 whitespace-nowrap">Impact</div>
          <div className="absolute bottom-2 left-1/2 -translate-x-1/2 text-[10px] font-bold tracking-wider uppercase text-slate-400">Effort</div>
          <div className="grid grid-cols-2 grid-rows-2 ml-6 mb-6" style={{ minHeight: 340 }}>
            <div className="border-r border-b border-slate-100 dark:border-slate-700 p-3 bg-emerald-50/50 dark:bg-emerald-900/10">
              <p className="text-[9px] font-bold tracking-wider uppercase text-emerald-600 mb-2">Do First</p>
              <div className="space-y-2">
                {ins.filter(i => i.impact === "high" && i.effort !== "high").map((i, idx) => (
                  <MatrixCard key={idx} item={i} borderColor="border-emerald-200 dark:border-emerald-800" />
                ))}
              </div>
            </div>
            <div className="border-b border-slate-100 dark:border-slate-700 p-3 bg-amber-50/50 dark:bg-amber-900/10">
              <p className="text-[9px] font-bold tracking-wider uppercase text-amber-600 mb-2">Plan & Schedule</p>
              <div className="space-y-2">
                {ins.filter(i => i.impact === "high" && i.effort === "high").map((i, idx) => (
                  <MatrixCard key={idx} item={i} borderColor="border-amber-200 dark:border-amber-800" />
                ))}
              </div>
            </div>
            <div className="border-r border-slate-100 dark:border-slate-700 p-3 bg-blue-50/50 dark:bg-blue-900/10">
              <p className="text-[9px] font-bold tracking-wider uppercase text-blue-600 mb-2">Quick Wins</p>
              <div className="space-y-2">
                {ins.filter(i => i.impact !== "high" && i.effort !== "high").map((i, idx) => (
                  <MatrixCard key={idx} item={i} borderColor="border-blue-200 dark:border-blue-800" />
                ))}
              </div>
            </div>
            <div className="p-3 bg-slate-50/50 dark:bg-slate-800/50">
              <p className="text-[9px] font-bold tracking-wider uppercase text-slate-400 mb-2">Defer</p>
              <div className="space-y-2">
                {ins.filter(i => i.impact !== "high" && i.effort === "high").map((i, idx) => (
                  <MatrixCard key={idx} item={i} borderColor="border-slate-200 dark:border-slate-700" />
                ))}
              </div>
            </div>
          </div>
        </div>
      </CardContent>
    </Card>
  </motion.div>
);

const MatrixCard = ({ item, borderColor }) => (
  <div className={`p-2.5 bg-white dark:bg-slate-800 rounded-lg border ${borderColor} shadow-sm`}>
    <p className="text-xs font-medium text-slate-900 dark:text-white">{item.title}</p>
    <p className="text-[10px] text-slate-500 mt-0.5 line-clamp-2">{item.description}</p>
    {item.current_value && <p className="text-[10px] text-slate-400 mt-1">{item.current_value} → {item.target_value}</p>}
  </div>
);

const ActionFunnel = ({ funnel }) => (
  <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.2 }}>
    <Card className="bg-white dark:bg-slate-800 border-slate-100 dark:border-slate-700 rounded-2xl">
      <CardContent className="p-6 md:p-8">
        <h3 className="text-lg font-medium text-slate-900 dark:text-white mb-6" style={{ fontFamily: "'Outfit', sans-serif" }}>Action Funnel</h3>
        <div className="space-y-3">
          {funnel.map((step, i) => (
            <div key={i} className="flex items-start gap-4">
              <div className="flex flex-col items-center">
                <div className="w-8 h-8 rounded-full flex items-center justify-center text-white text-xs font-bold" style={{ backgroundColor: STATUS_COLORS[step.status] || "#94A3B8" }}>
                  {step.step}
                </div>
                {i < funnel.length - 1 && <div className="w-0.5 h-8 bg-slate-200 dark:bg-slate-700 mt-1" />}
              </div>
              <div className="flex-1 pb-2">
                <p className="text-sm font-medium text-slate-900 dark:text-white">{step.title}</p>
                <p className="text-xs text-slate-500 dark:text-slate-400 mt-0.5">{step.detail}</p>
              </div>
              <span className="text-[10px] font-bold uppercase tracking-wider px-2 py-0.5 rounded-full" style={{ backgroundColor: `${STATUS_COLORS[step.status]}15`, color: STATUS_COLORS[step.status] }}>
                {step.status}
              </span>
            </div>
          ))}
          <div className="flex items-start gap-4">
            <div className="w-8 h-8 rounded-full bg-emerald-500 flex items-center justify-center">
              <Target className="w-4 h-4 text-white" />
            </div>
            <p className="text-sm font-medium text-emerald-600 pt-1.5">Optimized Portfolio</p>
          </div>
        </div>
      </CardContent>
    </Card>
  </motion.div>
);

const InsightCards = ({ ins }) => (
  <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.25 }}>
    <Card className="bg-white dark:bg-slate-800 border-slate-100 dark:border-slate-700 rounded-2xl">
      <CardContent className="p-6 md:p-8">
        <h3 className="text-lg font-medium text-slate-900 dark:text-white mb-6" style={{ fontFamily: "'Outfit', sans-serif" }}>Detailed Insights</h3>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {ins.map((i, idx) => {
            const Icon = CATEGORY_ICONS[i.category] || Sparkles;
            const colors = {
              warning: "border-amber-200 bg-amber-50/80 dark:bg-amber-900/15 dark:border-amber-800",
              opportunity: "border-emerald-200 bg-emerald-50/80 dark:bg-emerald-900/15 dark:border-emerald-800",
              action: "border-blue-200 bg-blue-50/80 dark:bg-blue-900/15 dark:border-blue-800",
              info: "border-slate-200 bg-slate-50/80 dark:bg-slate-800/50 dark:border-slate-700",
            };
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
);

// ════════════════════════════════════════
// OVEREXPOSURE TAB
// ════════════════════════════════════════
const OverexposureTab = ({ overexposure, fmt }) => {
  const fundHouse = overexposure?.fund_house || [];
  const sectors = overexposure?.sector || [];
  const [expandedFH, setExpandedFH] = useState(null);
  const [expandedSec, setExpandedSec] = useState(null);

  if (!fundHouse.length && !sectors.length) {
    return (
      <Card className="bg-white dark:bg-slate-800 border-slate-100 dark:border-slate-700 rounded-2xl">
        <CardContent className="p-12 text-center">
          <Building2 className="w-12 h-12 text-slate-300 mx-auto mb-4" />
          <h3 className="text-lg font-medium text-slate-900 dark:text-white mb-2" style={{ fontFamily: "'Outfit', sans-serif" }}>No overexposure data</h3>
          <p className="text-sm text-slate-500">Add holdings to see concentration analysis.</p>
        </CardContent>
      </Card>
    );
  }

  return (
    <div className="space-y-6">
      {/* Fund House / AMC Concentration */}
      {fundHouse.length > 0 && (
        <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }}>
          <Card className="bg-white dark:bg-slate-800 border-slate-100 dark:border-slate-700 rounded-2xl">
            <CardContent className="p-6 md:p-8">
              <div className="flex items-center gap-3 mb-6">
                <div className="w-10 h-10 rounded-xl bg-violet-50 dark:bg-violet-900/20 flex items-center justify-center">
                  <Building2 className="w-5 h-5 text-violet-600" strokeWidth={1.5} />
                </div>
                <div>
                  <h3 className="text-lg font-medium text-slate-900 dark:text-white" style={{ fontFamily: "'Outfit', sans-serif" }}>
                    Fund House Concentration
                  </h3>
                  <p className="text-xs text-slate-500 dark:text-slate-400">
                    AMC-level exposure across your mutual fund portfolio
                  </p>
                </div>
              </div>

              {/* Bar Chart */}
              <div className="h-56 mb-6" data-testid="fund-house-chart">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={fundHouse.slice(0, 8)} layout="vertical" margin={{ top: 0, right: 20, left: 0, bottom: 0 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#F1F5F9" horizontal={false} />
                    <XAxis type="number" axisLine={false} tickLine={false} tick={{ fontSize: 10, fill: "#94A3B8" }} tickFormatter={v => `${v}%`} domain={[0, "auto"]} />
                    <YAxis type="category" dataKey="name" axisLine={false} tickLine={false} tick={{ fontSize: 11, fill: "#64748B" }} width={120} />
                    <Tooltip
                      formatter={(v, name, { payload }) => [`${v}% (${payload.count} funds)`, "Allocation"]}
                      contentStyle={{ borderRadius: 12, border: "1px solid #E2E8F0", fontSize: 12 }}
                    />
                    <Bar dataKey="pct" radius={[0, 6, 6, 0]} barSize={20}>
                      {fundHouse.slice(0, 8).map((fh, i) => (
                        <Cell key={i} fill={RISK_COLORS[fh.risk_level] || CHART_COLORS[i % CHART_COLORS.length]} />
                      ))}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              </div>

              {/* Fund House Detail Cards */}
              <div className="space-y-2" data-testid="fund-house-details">
                {fundHouse.map((fh, i) => (
                  <div
                    key={fh.name}
                    className={`rounded-xl border transition-all ${
                      fh.risk_level === "high"
                        ? "border-red-200 bg-red-50/40 dark:bg-red-900/10 dark:border-red-800"
                        : fh.risk_level === "medium"
                        ? "border-amber-200 bg-amber-50/40 dark:bg-amber-900/10 dark:border-amber-800"
                        : "border-slate-200 bg-slate-50/40 dark:bg-slate-800/50 dark:border-slate-700"
                    }`}
                  >
                    <div
                      className="flex items-center justify-between p-4 cursor-pointer"
                      onClick={() => setExpandedFH(expandedFH === i ? null : i)}
                    >
                      <div className="flex items-center gap-3">
                        <div className="w-8 h-8 rounded-lg flex items-center justify-center text-xs font-bold text-white" style={{ backgroundColor: CHART_COLORS[i % CHART_COLORS.length] }}>
                          {fh.name.charAt(0)}
                        </div>
                        <div>
                          <p className="text-sm font-medium text-slate-900 dark:text-white">{fh.name}</p>
                          <p className="text-xs text-slate-500">{fh.count} fund{fh.count > 1 ? "s" : ""} — {fmt(fh.value)}</p>
                        </div>
                      </div>
                      <div className="flex items-center gap-3">
                        <div className="text-right">
                          <span className={`text-base font-bold ${fh.risk_level === "high" ? "text-red-500" : fh.risk_level === "medium" ? "text-amber-500" : "text-emerald-600"}`} style={{ fontFamily: "'JetBrains Mono', monospace" }}>
                            {fh.pct}%
                          </span>
                          {fh.risk_level === "high" && (
                            <span className="ml-2 text-[9px] font-bold uppercase tracking-wider text-red-500 bg-red-100 dark:bg-red-900/30 px-1.5 py-0.5 rounded">Overexposed</span>
                          )}
                        </div>
                        {expandedFH === i ? <ChevronUp className="w-4 h-4 text-slate-400" /> : <ChevronDown className="w-4 h-4 text-slate-400" />}
                      </div>
                    </div>
                    {expandedFH === i && fh.funds.length > 0 && (
                      <div className="px-4 pb-4 border-t border-slate-100 dark:border-slate-700 pt-3">
                        <p className="text-[10px] font-bold tracking-wider uppercase text-slate-400 mb-2">Funds under {fh.name}</p>
                        <div className="space-y-1">
                          {fh.funds.map((f, fi) => (
                            <p key={fi} className="text-xs text-slate-600 dark:text-slate-400 flex items-center gap-2">
                              <span className="w-1.5 h-1.5 rounded-full flex-shrink-0" style={{ backgroundColor: CHART_COLORS[i % CHART_COLORS.length] }} />
                              {f}
                            </p>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>
        </motion.div>
      )}

      {/* Sector Concentration */}
      {sectors.length > 0 && (
        <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.1 }}>
          <Card className="bg-white dark:bg-slate-800 border-slate-100 dark:border-slate-700 rounded-2xl">
            <CardContent className="p-6 md:p-8">
              <div className="flex items-center gap-3 mb-6">
                <div className="w-10 h-10 rounded-xl bg-blue-50 dark:bg-blue-900/20 flex items-center justify-center">
                  <BarChart3 className="w-5 h-5 text-blue-600" strokeWidth={1.5} />
                </div>
                <div>
                  <h3 className="text-lg font-medium text-slate-900 dark:text-white" style={{ fontFamily: "'Outfit', sans-serif" }}>
                    Sector Concentration
                  </h3>
                  <p className="text-xs text-slate-500 dark:text-slate-400">
                    Category-level exposure across all holdings
                  </p>
                </div>
              </div>

              <div className="h-56 mb-6" data-testid="sector-concentration-chart">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={sectors.slice(0, 10)} layout="vertical" margin={{ top: 0, right: 20, left: 0, bottom: 0 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#F1F5F9" horizontal={false} />
                    <XAxis type="number" axisLine={false} tickLine={false} tick={{ fontSize: 10, fill: "#94A3B8" }} tickFormatter={v => `${v}%`} domain={[0, "auto"]} />
                    <YAxis type="category" dataKey="name" axisLine={false} tickLine={false} tick={{ fontSize: 11, fill: "#64748B" }} width={120} />
                    <Tooltip
                      formatter={(v, name, { payload }) => [`${v}% (${payload.count} holdings)`, "Allocation"]}
                      contentStyle={{ borderRadius: 12, border: "1px solid #E2E8F0", fontSize: 12 }}
                    />
                    <Bar dataKey="pct" radius={[0, 6, 6, 0]} barSize={20}>
                      {sectors.slice(0, 10).map((sec, i) => (
                        <Cell key={i} fill={RISK_COLORS[sec.risk_level] || CHART_COLORS[i % CHART_COLORS.length]} />
                      ))}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              </div>

              <div className="space-y-2" data-testid="sector-details">
                {sectors.slice(0, 10).map((sec, i) => (
                  <div
                    key={sec.name}
                    className={`rounded-xl border transition-all ${
                      sec.risk_level === "high"
                        ? "border-red-200 bg-red-50/40 dark:bg-red-900/10 dark:border-red-800"
                        : sec.risk_level === "medium"
                        ? "border-amber-200 bg-amber-50/40 dark:bg-amber-900/10 dark:border-amber-800"
                        : "border-slate-200 bg-slate-50/40 dark:bg-slate-800/50 dark:border-slate-700"
                    }`}
                  >
                    <div
                      className="flex items-center justify-between p-4 cursor-pointer"
                      onClick={() => setExpandedSec(expandedSec === i ? null : i)}
                    >
                      <div className="flex items-center gap-3">
                        <div className="w-3 h-8 rounded-sm" style={{ backgroundColor: CHART_COLORS[i % CHART_COLORS.length] }} />
                        <div>
                          <p className="text-sm font-medium text-slate-900 dark:text-white">{sec.name}</p>
                          <p className="text-xs text-slate-500">{sec.count} holding{sec.count > 1 ? "s" : ""} — {fmt(sec.value)}</p>
                        </div>
                      </div>
                      <div className="flex items-center gap-3">
                        <span className={`text-base font-bold ${sec.risk_level === "high" ? "text-red-500" : sec.risk_level === "medium" ? "text-amber-500" : "text-emerald-600"}`} style={{ fontFamily: "'JetBrains Mono', monospace" }}>
                          {sec.pct}%
                        </span>
                        {expandedSec === i ? <ChevronUp className="w-4 h-4 text-slate-400" /> : <ChevronDown className="w-4 h-4 text-slate-400" />}
                      </div>
                    </div>
                    {expandedSec === i && sec.holdings.length > 0 && (
                      <div className="px-4 pb-4 border-t border-slate-100 dark:border-slate-700 pt-3">
                        <div className="space-y-1">
                          {sec.holdings.map((h, hi) => (
                            <p key={hi} className="text-xs text-slate-600 dark:text-slate-400 flex items-center gap-2">
                              <span className="w-1.5 h-1.5 rounded-full flex-shrink-0" style={{ backgroundColor: CHART_COLORS[i % CHART_COLORS.length] }} />
                              {h}
                            </p>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>
        </motion.div>
      )}
    </div>
  );
};

// ════════════════════════════════════════
// FUND OVERLAP TAB
// ════════════════════════════════════════
const OverlapTab = ({ overlaps }) => {
  if (!overlaps.length) {
    return (
      <Card className="bg-white dark:bg-slate-800 border-slate-100 dark:border-slate-700 rounded-2xl">
        <CardContent className="p-12 text-center">
          <Layers className="w-12 h-12 text-slate-300 mx-auto mb-4" />
          <h3 className="text-lg font-medium text-slate-900 dark:text-white mb-2" style={{ fontFamily: "'Outfit', sans-serif" }}>
            No fund overlap detected
          </h3>
          <p className="text-sm text-slate-500">
            Add 2 or more mutual funds to see overlap analysis.
          </p>
        </CardContent>
      </Card>
    );
  }

  const highOverlaps = overlaps.filter(o => o.overlap_pct >= 60);
  const medOverlaps = overlaps.filter(o => o.overlap_pct >= 30 && o.overlap_pct < 60);
  const lowOverlaps = overlaps.filter(o => o.overlap_pct < 30 && o.overlap_pct > 0);

  return (
    <div className="space-y-6">
      {/* Summary Stats */}
      <div className="grid grid-cols-3 gap-4">
        <Card className="bg-red-50 dark:bg-red-900/15 border-red-200 dark:border-red-800 rounded-2xl">
          <CardContent className="p-5 text-center">
            <p className="text-2xl font-bold text-red-600" style={{ fontFamily: "'Outfit', sans-serif" }} data-testid="high-overlap-count">{highOverlaps.length}</p>
            <p className="text-xs text-red-500 mt-1 font-medium">High Overlap (60%+)</p>
          </CardContent>
        </Card>
        <Card className="bg-amber-50 dark:bg-amber-900/15 border-amber-200 dark:border-amber-800 rounded-2xl">
          <CardContent className="p-5 text-center">
            <p className="text-2xl font-bold text-amber-600" style={{ fontFamily: "'Outfit', sans-serif" }} data-testid="medium-overlap-count">{medOverlaps.length}</p>
            <p className="text-xs text-amber-500 mt-1 font-medium">Moderate (30-60%)</p>
          </CardContent>
        </Card>
        <Card className="bg-emerald-50 dark:bg-emerald-900/15 border-emerald-200 dark:border-emerald-800 rounded-2xl">
          <CardContent className="p-5 text-center">
            <p className="text-2xl font-bold text-emerald-600" style={{ fontFamily: "'Outfit', sans-serif" }} data-testid="low-overlap-count">{lowOverlaps.length}</p>
            <p className="text-xs text-emerald-500 mt-1 font-medium">Low (&lt;30%)</p>
          </CardContent>
        </Card>
      </div>

      {/* Overlap Heatmap Grid */}
      <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }}>
        <Card className="bg-white dark:bg-slate-800 border-slate-100 dark:border-slate-700 rounded-2xl">
          <CardContent className="p-6 md:p-8">
            <div className="flex items-center gap-3 mb-6">
              <div className="w-10 h-10 rounded-xl bg-indigo-50 dark:bg-indigo-900/20 flex items-center justify-center">
                <Layers className="w-5 h-5 text-indigo-600" strokeWidth={1.5} />
              </div>
              <div>
                <h3 className="text-lg font-medium text-slate-900 dark:text-white" style={{ fontFamily: "'Outfit', sans-serif" }}>
                  Fund Overlap Matrix
                </h3>
                <p className="text-xs text-slate-500 dark:text-slate-400">
                  Based on category, mandate, and fund house similarity
                </p>
              </div>
              <div className="ml-auto flex items-center gap-3 text-[10px] font-bold tracking-wider uppercase">
                <div className="flex items-center gap-1"><div className="w-3 h-3 rounded bg-red-500/70" />High</div>
                <div className="flex items-center gap-1"><div className="w-3 h-3 rounded bg-amber-500/70" />Medium</div>
                <div className="flex items-center gap-1"><div className="w-3 h-3 rounded bg-emerald-500/70" />Low</div>
              </div>
            </div>

            <div className="space-y-3" data-testid="overlap-matrix">
              {overlaps.map((o, i) => {
                const isHigh = o.overlap_pct >= 60;
                const isMed = o.overlap_pct >= 30;
                return (
                  <motion.div
                    key={i}
                    initial={{ opacity: 0, x: -8 }}
                    animate={{ opacity: 1, x: 0 }}
                    transition={{ delay: i * 0.03 }}
                    className={`rounded-xl border overflow-hidden ${
                      isHigh
                        ? "border-red-200 dark:border-red-800"
                        : isMed
                        ? "border-amber-200 dark:border-amber-800"
                        : "border-slate-200 dark:border-slate-700"
                    }`}
                  >
                    {/* Color intensity bar across top */}
                    <div
                      className="h-1"
                      style={{
                        background: isHigh
                          ? `linear-gradient(90deg, #EF4444 0%, #EF4444 ${o.overlap_pct}%, #F1F5F9 ${o.overlap_pct}%)`
                          : isMed
                          ? `linear-gradient(90deg, #F59E0B 0%, #F59E0B ${o.overlap_pct}%, #F1F5F9 ${o.overlap_pct}%)`
                          : `linear-gradient(90deg, #10B981 0%, #10B981 ${o.overlap_pct}%, #F1F5F9 ${o.overlap_pct}%)`,
                      }}
                    />

                    <div className={`p-4 ${isHigh ? "bg-red-50/30 dark:bg-red-900/10" : isMed ? "bg-amber-50/30 dark:bg-amber-900/10" : "bg-slate-50/30 dark:bg-slate-800/50"}`}>
                      <div className="flex items-center justify-between">
                        <div className="flex-1 min-w-0 space-y-1">
                          <p className="text-sm font-medium text-slate-900 dark:text-white truncate">{o.fund_a}</p>
                          <div className="flex items-center gap-2">
                            <div className="w-16 h-[2px] bg-slate-300 dark:bg-slate-600" />
                            <span className="text-[10px] text-slate-400 font-medium whitespace-nowrap">overlaps with</span>
                            <div className="w-16 h-[2px] bg-slate-300 dark:bg-slate-600" />
                          </div>
                          <p className="text-sm font-medium text-slate-900 dark:text-white truncate">{o.fund_b}</p>
                        </div>
                        <div className="flex-shrink-0 ml-4 text-center">
                          <div
                            className={`text-2xl font-bold ${isHigh ? "text-red-500" : isMed ? "text-amber-500" : "text-emerald-600"}`}
                            style={{ fontFamily: "'JetBrains Mono', monospace" }}
                          >
                            {o.overlap_pct}%
                          </div>
                          <p className="text-[9px] font-bold uppercase tracking-wider text-slate-400 mt-0.5">overlap</p>
                        </div>
                      </div>

                      {o.reasons && o.reasons.length > 0 && (
                        <div className="mt-3 flex flex-wrap gap-1.5">
                          {o.reasons.map((r, ri) => (
                            <span key={ri} className="text-[10px] px-2 py-0.5 rounded-full bg-slate-100 dark:bg-slate-700 text-slate-600 dark:text-slate-400">
                              {r}
                            </span>
                          ))}
                        </div>
                      )}
                    </div>
                  </motion.div>
                );
              })}
            </div>
          </CardContent>
        </Card>
      </motion.div>
    </div>
  );
};

// ════════════════════════════════════════
// PERFORMANCE TAB
// ════════════════════════════════════════
const ASSET_LABELS = {
  equity: "Equity", mutual_fund: "Mutual Funds", etf: "ETF",
  bond: "Bonds", gold: "Gold", fd: "Fixed Deposit", other: "Other",
};

const PerformanceTab = ({ cards, allCards, sort, dir, filter, setSort, setDir, setFilter, fmt }) => {
  const assetTypes = useMemo(() => {
    const types = new Set(allCards.map(c => c.asset_type));
    return ["all", ...Array.from(types)];
  }, [allCards]);

  const totalInvested = cards.reduce((s, c) => s + c.invested, 0);
  const totalCurrent = cards.reduce((s, c) => s + c.current_value, 0);
  const totalReturn = totalCurrent - totalInvested;
  const totalReturnPct = totalInvested > 0 ? (totalReturn / totalInvested * 100) : 0;

  const toggleSort = (col) => {
    if (sort === col) {
      setDir(dir === "desc" ? "asc" : "desc");
    } else {
      setSort(col);
      setDir("desc");
    }
  };

  const SortIcon = ({ col }) => {
    if (sort !== col) return null;
    return dir === "desc" ? <ChevronDown className="w-3 h-3 inline" /> : <ChevronUp className="w-3 h-3 inline" />;
  };

  if (!cards.length && !allCards.length) {
    return (
      <Card className="bg-white dark:bg-slate-800 border-slate-100 dark:border-slate-700 rounded-2xl">
        <CardContent className="p-12 text-center">
          <BarChart3 className="w-12 h-12 text-slate-300 mx-auto mb-4" />
          <h3 className="text-lg font-medium text-slate-900 dark:text-white mb-2" style={{ fontFamily: "'Outfit', sans-serif" }}>No holdings</h3>
          <p className="text-sm text-slate-500">Add holdings to see performance analysis.</p>
        </CardContent>
      </Card>
    );
  }

  return (
    <div className="space-y-6">
      {/* Summary Bar */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <Card className="bg-white dark:bg-slate-800 border-slate-100 dark:border-slate-700 rounded-2xl">
          <CardContent className="p-4">
            <p className="text-[10px] font-bold tracking-wider uppercase text-slate-400">Total Invested</p>
            <p className="text-lg font-semibold text-slate-900 dark:text-white mt-1" style={{ fontFamily: "'Outfit', sans-serif" }} data-testid="perf-total-invested">{fmt(totalInvested)}</p>
          </CardContent>
        </Card>
        <Card className="bg-white dark:bg-slate-800 border-slate-100 dark:border-slate-700 rounded-2xl">
          <CardContent className="p-4">
            <p className="text-[10px] font-bold tracking-wider uppercase text-slate-400">Current Value</p>
            <p className="text-lg font-semibold text-slate-900 dark:text-white mt-1" style={{ fontFamily: "'Outfit', sans-serif" }} data-testid="perf-total-current">{fmt(totalCurrent)}</p>
          </CardContent>
        </Card>
        <Card className={`border rounded-2xl ${totalReturn >= 0 ? "bg-emerald-50/50 dark:bg-emerald-900/10 border-emerald-200 dark:border-emerald-800" : "bg-red-50/50 dark:bg-red-900/10 border-red-200 dark:border-red-800"}`}>
          <CardContent className="p-4">
            <p className="text-[10px] font-bold tracking-wider uppercase text-slate-400">Total P&L</p>
            <p className={`text-lg font-semibold mt-1 ${totalReturn >= 0 ? "text-emerald-600" : "text-red-500"}`} style={{ fontFamily: "'Outfit', sans-serif" }} data-testid="perf-total-return">
              {totalReturn >= 0 ? "+" : ""}{fmt(Math.abs(totalReturn))}
            </p>
          </CardContent>
        </Card>
        <Card className={`border rounded-2xl ${totalReturnPct >= 0 ? "bg-emerald-50/50 dark:bg-emerald-900/10 border-emerald-200 dark:border-emerald-800" : "bg-red-50/50 dark:bg-red-900/10 border-red-200 dark:border-red-800"}`}>
          <CardContent className="p-4">
            <p className="text-[10px] font-bold tracking-wider uppercase text-slate-400">Return %</p>
            <p className={`text-lg font-semibold mt-1 flex items-center gap-1 ${totalReturnPct >= 0 ? "text-emerald-600" : "text-red-500"}`} style={{ fontFamily: "'Outfit', sans-serif" }} data-testid="perf-return-pct">
              {totalReturnPct >= 0 ? <ArrowUpRight className="w-4 h-4" /> : <ArrowDownRight className="w-4 h-4" />}
              {totalReturnPct >= 0 ? "+" : ""}{totalReturnPct.toFixed(1)}%
            </p>
          </CardContent>
        </Card>
      </div>

      {/* Filters */}
      <div className="flex items-center gap-2 flex-wrap" data-testid="perf-filters">
        <Filter className="w-4 h-4 text-slate-400" />
        {assetTypes.map(at => (
          <button
            key={at}
            onClick={() => setFilter(at)}
            className={`px-3 py-1.5 text-xs font-medium rounded-lg transition-all ${
              filter === at
                ? "bg-emerald-600 text-white"
                : "bg-slate-100 dark:bg-slate-700 text-slate-600 dark:text-slate-400 hover:bg-slate-200 dark:hover:bg-slate-600"
            }`}
            data-testid={`filter-${at}`}
          >
            {at === "all" ? "All" : ASSET_LABELS[at] || at}
          </button>
        ))}
      </div>

      {/* Performance Cards Table */}
      <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }}>
        <Card className="bg-white dark:bg-slate-800 border-slate-100 dark:border-slate-700 rounded-2xl overflow-hidden">
          <CardContent className="p-0">
            <div className="overflow-x-auto">
              <table className="w-full" data-testid="performance-table">
                <thead>
                  <tr className="border-b border-slate-100 dark:border-slate-700">
                    <th className="text-left p-4 text-[10px] font-bold tracking-wider uppercase text-slate-400">Holding</th>
                    <th className="text-right p-4 text-[10px] font-bold tracking-wider uppercase text-slate-400 cursor-pointer hover:text-slate-600 select-none" onClick={() => toggleSort("invested")}>
                      Invested <SortIcon col="invested" />
                    </th>
                    <th className="text-right p-4 text-[10px] font-bold tracking-wider uppercase text-slate-400 cursor-pointer hover:text-slate-600 select-none" onClick={() => toggleSort("current_value")}>
                      Current <SortIcon col="current_value" />
                    </th>
                    <th className="text-right p-4 text-[10px] font-bold tracking-wider uppercase text-slate-400 cursor-pointer hover:text-slate-600 select-none" onClick={() => toggleSort("pct_return")}>
                      Return % <SortIcon col="pct_return" />
                    </th>
                    <th className="text-right p-4 text-[10px] font-bold tracking-wider uppercase text-slate-400 cursor-pointer hover:text-slate-600 select-none" onClick={() => toggleSort("weight")}>
                      Weight <SortIcon col="weight" />
                    </th>
                    <th className="text-right p-4 text-[10px] font-bold tracking-wider uppercase text-slate-400 cursor-pointer hover:text-slate-600 select-none" onClick={() => toggleSort("cagr")}>
                      CAGR <SortIcon col="cagr" />
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {cards.map((c, i) => {
                    const isPos = c.pct_return >= 0;
                    return (
                      <tr
                        key={i}
                        className="border-b border-slate-50 dark:border-slate-700/50 hover:bg-slate-50/50 dark:hover:bg-slate-700/20 transition-colors"
                        data-testid={`perf-row-${i}`}
                      >
                        <td className="p-4">
                          <div className="flex items-center gap-3">
                            {/* Mini return indicator bar */}
                            <div className="w-1 h-10 rounded-full flex-shrink-0" style={{ backgroundColor: isPos ? "#10B981" : "#EF4444", opacity: Math.min(0.3 + Math.abs(c.pct_return) / 100, 1) }} />
                            <div>
                              <p className="text-sm font-medium text-slate-900 dark:text-white max-w-[250px] truncate">{c.name}</p>
                              <div className="flex items-center gap-2 mt-0.5">
                                <span className="text-[10px] px-1.5 py-0.5 rounded bg-slate-100 dark:bg-slate-700 text-slate-500 dark:text-slate-400 font-medium">
                                  {ASSET_LABELS[c.asset_type] || c.asset_type}
                                </span>
                                <span className="text-[10px] text-slate-400">{c.sector}</span>
                                {c.nav_source === "AMFI" && (
                                  <span className="text-[9px] px-1 py-0.5 rounded bg-emerald-100 dark:bg-emerald-900/30 text-emerald-600 font-medium">LIVE NAV</span>
                                )}
                              </div>
                            </div>
                          </div>
                        </td>
                        <td className="p-4 text-right">
                          <p className="text-sm text-slate-700 dark:text-slate-300" style={{ fontFamily: "'JetBrains Mono', monospace" }}>{fmt(c.invested)}</p>
                          <p className="text-[10px] text-slate-400 mt-0.5">{c.quantity} × {fmt(c.buy_price)}</p>
                        </td>
                        <td className="p-4 text-right">
                          <p className="text-sm font-medium text-slate-900 dark:text-white" style={{ fontFamily: "'JetBrains Mono', monospace" }}>{fmt(c.current_value)}</p>
                          <p className="text-[10px] text-slate-400 mt-0.5">{fmt(c.current_price)}/unit</p>
                        </td>
                        <td className="p-4 text-right">
                          <div className="flex items-center justify-end gap-1">
                            {isPos ? <ArrowUpRight className="w-3.5 h-3.5 text-emerald-600" /> : <ArrowDownRight className="w-3.5 h-3.5 text-red-500" />}
                            <span className={`text-sm font-bold ${isPos ? "text-emerald-600" : "text-red-500"}`} style={{ fontFamily: "'JetBrains Mono', monospace" }}>
                              {isPos ? "+" : ""}{c.pct_return}%
                            </span>
                          </div>
                          <p className={`text-[10px] mt-0.5 ${isPos ? "text-emerald-500" : "text-red-400"}`}>
                            {isPos ? "+" : ""}{fmt(Math.abs(c.abs_return))}
                          </p>
                        </td>
                        <td className="p-4 text-right">
                          <div className="flex items-center justify-end gap-2">
                            <div className="w-16 h-1.5 rounded-full bg-slate-100 dark:bg-slate-700 overflow-hidden">
                              <div className="h-full rounded-full bg-indigo-500" style={{ width: `${Math.min(c.weight, 100)}%` }} />
                            </div>
                            <span className="text-xs text-slate-600 dark:text-slate-400 w-10 text-right" style={{ fontFamily: "'JetBrains Mono', monospace" }}>{c.weight}%</span>
                          </div>
                        </td>
                        <td className="p-4 text-right">
                          {c.cagr !== null ? (
                            <span className={`text-sm font-medium ${c.cagr >= 0 ? "text-emerald-600" : "text-red-500"}`} style={{ fontFamily: "'JetBrains Mono', monospace" }}>
                              {c.cagr >= 0 ? "+" : ""}{c.cagr}%
                            </span>
                          ) : (
                            <span className="text-xs text-slate-400">—</span>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            {cards.length === 0 && (
              <div className="p-8 text-center text-sm text-slate-400">
                No holdings match the selected filter.
              </div>
            )}
          </CardContent>
        </Card>
      </motion.div>
    </div>
  );
};

export default InsightsView;

// ════════════════════════════════════════
// BENCHMARK TAB - MF Benchmark Ratings, Performance Pie, Category Overlap Bar
// ════════════════════════════════════════
const RATING_CONFIG = {
  overperforming: { label: "Outperforming", color: "#10B981", bg: "bg-emerald-50 dark:bg-emerald-900/15", border: "border-emerald-200 dark:border-emerald-800", icon: TrendingUp },
  meeting: { label: "Meeting Benchmark", color: "#3B82F6", bg: "bg-blue-50 dark:bg-blue-900/15", border: "border-blue-200 dark:border-blue-800", icon: ArrowRight },
  underperforming: { label: "Underperforming", color: "#EF4444", bg: "bg-red-50 dark:bg-red-900/15", border: "border-red-200 dark:border-red-800", icon: TrendingDown },
  no_data: { label: "No Benchmark Data", color: "#94A3B8", bg: "bg-slate-50 dark:bg-slate-800/50", border: "border-slate-200 dark:border-slate-700", icon: BarChart3 },
};

const BenchmarkTab = ({ data, loading, onLoad, fmt }) => {
  useEffect(() => {
    if (!data && !loading) onLoad();
  }, []);

  if (loading) {
    return (
      <Card className="bg-white dark:bg-slate-800 border-slate-100 dark:border-slate-700 rounded-2xl">
        <CardContent className="p-12 text-center">
          <RefreshCw className="w-8 h-8 text-emerald-600 mx-auto mb-4 animate-spin" />
          <h3 className="text-lg font-medium text-slate-900 dark:text-white mb-2" style={{ fontFamily: "'Outfit', sans-serif" }}>
            Fetching Benchmark Data...
          </h3>
          <p className="text-sm text-slate-500">Loading 1-year historical NAVs from AMFI for each mutual fund. This may take 15-30 seconds.</p>
        </CardContent>
      </Card>
    );
  }

  if (!data || !data.fund_ratings?.length) {
    return (
      <Card className="bg-white dark:bg-slate-800 border-slate-100 dark:border-slate-700 rounded-2xl">
        <CardContent className="p-12 text-center">
          <BarChart3 className="w-12 h-12 text-slate-300 mx-auto mb-4" />
          <h3 className="text-lg font-medium text-slate-900 dark:text-white mb-2" style={{ fontFamily: "'Outfit', sans-serif" }}>
            No mutual fund data
          </h3>
          <p className="text-sm text-slate-500 mb-4">Add mutual fund holdings to see benchmark analysis.</p>
          <Button onClick={onLoad} className="bg-emerald-600 hover:bg-emerald-700 text-white rounded-xl" data-testid="load-benchmark-btn">
            <RefreshCw className="w-4 h-4 mr-2" /> Load Benchmark Data
          </Button>
        </CardContent>
      </Card>
    );
  }

  const dist = data.performance_distribution || {};
  const ratings = data.fund_ratings || [];
  const topPerf = data.top_performers || [];
  const bottomPerf = data.bottom_performers || [];
  const catOverlap = data.category_overlap || [];
  const summary = data.summary || {};

  const pieData = [
    { name: "Outperforming", value: dist.overperforming || 0, color: "#10B981" },
    { name: "Meeting Benchmark", value: dist.meeting || 0, color: "#3B82F6" },
    { name: "Underperforming", value: dist.underperforming || 0, color: "#EF4444" },
    { name: "No Data", value: dist.no_data || 0, color: "#CBD5E1" },
  ].filter(d => d.value > 0);

  const overlapBarData = catOverlap
    .filter(c => c.count > 0)
    .slice(0, 12)
    .map(c => ({
      name: c.category.length > 18 ? c.category.slice(0, 18) + ".." : c.category,
      fullName: c.category,
      count: c.count,
      overlapping: c.is_overlapping,
    }));

  return (
    <div className="space-y-6">
      {/* Summary + Distribution Row */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {/* Performance Distribution Donut */}
        <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }}>
          <Card className="bg-white dark:bg-slate-800 border-slate-100 dark:border-slate-700 rounded-2xl h-full">
            <CardContent className="p-6">
              <div className="flex items-center justify-between mb-4">
                <h3 className="text-sm font-medium text-slate-900 dark:text-white" style={{ fontFamily: "'Outfit', sans-serif" }}>
                  MF Performance vs Benchmark
                </h3>
                <Button variant="ghost" size="sm" onClick={onLoad} className="h-7 text-xs text-slate-500" data-testid="refresh-benchmark">
                  <RefreshCw className="w-3 h-3 mr-1" /> Refresh
                </Button>
              </div>
              <div className="flex items-center gap-6">
                <div className="w-40 h-40 flex-shrink-0" data-testid="benchmark-pie">
                  <ResponsiveContainer width="100%" height="100%">
                    <PieChart>
                      <Pie data={pieData} cx="50%" cy="50%" innerRadius={38} outerRadius={62} paddingAngle={2} dataKey="value">
                        {pieData.map((d, i) => <Cell key={i} fill={d.color} />)}
                      </Pie>
                      <Tooltip formatter={(v, name) => [`${v} funds`, name]} />
                    </PieChart>
                  </ResponsiveContainer>
                </div>
                <div className="flex-1 space-y-2.5">
                  {pieData.map(d => (
                    <div key={d.name} className="flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        <div className="w-3 h-3 rounded-full" style={{ backgroundColor: d.color }} />
                        <span className="text-xs text-slate-600 dark:text-slate-400">{d.name}</span>
                      </div>
                      <span className="text-sm font-bold text-slate-900 dark:text-white" style={{ fontFamily: "'JetBrains Mono', monospace" }}>{d.value}</span>
                    </div>
                  ))}
                  <div className="pt-2 border-t border-slate-100 dark:border-slate-700">
                    <p className="text-[10px] text-slate-400">
                      {summary.matched || 0} of {summary.total_mf || 0} funds matched with AMFI data
                    </p>
                  </div>
                </div>
              </div>
            </CardContent>
          </Card>
        </motion.div>

        {/* Top & Bottom Performers */}
        <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.05 }}>
          <Card className="bg-white dark:bg-slate-800 border-slate-100 dark:border-slate-700 rounded-2xl h-full">
            <CardContent className="p-6">
              <h3 className="text-sm font-medium text-slate-900 dark:text-white mb-4" style={{ fontFamily: "'Outfit', sans-serif" }}>
                Best & Worst Performers (1Y Return)
              </h3>
              <div className="space-y-1">
                {topPerf.slice(0, 3).map((p, i) => (
                  <div key={`top-${i}`} className="flex items-center justify-between py-1.5 px-2 rounded-lg hover:bg-emerald-50/50 dark:hover:bg-emerald-900/10">
                    <div className="flex items-center gap-2 flex-1 min-w-0">
                      <div className="w-5 h-5 rounded-full bg-emerald-100 dark:bg-emerald-900/30 flex items-center justify-center flex-shrink-0">
                        <TrendingUp className="w-3 h-3 text-emerald-600" />
                      </div>
                      <span className="text-xs text-slate-700 dark:text-slate-300 truncate">{p.name}</span>
                    </div>
                    <span className="text-xs font-bold text-emerald-600 ml-2" style={{ fontFamily: "'JetBrains Mono', monospace" }}>
                      +{p.return_1y?.toFixed(1)}%
                    </span>
                  </div>
                ))}

                <div className="border-t border-slate-100 dark:border-slate-700 my-2" />

                {bottomPerf.slice(0, 3).map((p, i) => (
                  <div key={`bottom-${i}`} className="flex items-center justify-between py-1.5 px-2 rounded-lg hover:bg-red-50/50 dark:hover:bg-red-900/10">
                    <div className="flex items-center gap-2 flex-1 min-w-0">
                      <div className="w-5 h-5 rounded-full bg-red-100 dark:bg-red-900/30 flex items-center justify-center flex-shrink-0">
                        <TrendingDown className="w-3 h-3 text-red-500" />
                      </div>
                      <span className="text-xs text-slate-700 dark:text-slate-300 truncate">{p.name}</span>
                    </div>
                    <span className="text-xs font-bold text-red-500 ml-2" style={{ fontFamily: "'JetBrains Mono', monospace" }}>
                      {p.return_1y?.toFixed(1)}%
                    </span>
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>
        </motion.div>
      </div>

      {/* Category Overlap Bar Graph */}
      {overlapBarData.length > 0 && (
        <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.1 }}>
          <Card className="bg-white dark:bg-slate-800 border-slate-100 dark:border-slate-700 rounded-2xl">
            <CardContent className="p-6 md:p-8">
              <div className="flex items-center gap-3 mb-6">
                <div className="w-10 h-10 rounded-xl bg-amber-50 dark:bg-amber-900/20 flex items-center justify-center">
                  <Layers className="w-5 h-5 text-amber-600" strokeWidth={1.5} />
                </div>
                <div>
                  <h3 className="text-lg font-medium text-slate-900 dark:text-white" style={{ fontFamily: "'Outfit', sans-serif" }}>
                    Category Overlap
                  </h3>
                  <p className="text-xs text-slate-500 dark:text-slate-400">
                    Number of funds per sector/category — multiple funds in the same category indicates overlap
                  </p>
                </div>
              </div>
              <div className="h-64" data-testid="category-overlap-chart">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={overlapBarData} layout="vertical" margin={{ top: 0, right: 20, left: 0, bottom: 0 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#F1F5F9" horizontal={false} />
                    <XAxis type="number" axisLine={false} tickLine={false} tick={{ fontSize: 10, fill: "#94A3B8" }} allowDecimals={false} />
                    <YAxis type="category" dataKey="name" axisLine={false} tickLine={false} tick={{ fontSize: 11, fill: "#64748B" }} width={140} />
                    <Tooltip
                      formatter={(v, name, { payload }) => [`${v} fund${v > 1 ? "s" : ""}${payload.overlapping ? " (overlapping)" : ""}`, "Funds"]}
                      contentStyle={{ borderRadius: 12, border: "1px solid #E2E8F0", fontSize: 12 }}
                    />
                    <Bar dataKey="count" radius={[0, 6, 6, 0]} barSize={20}>
                      {overlapBarData.map((d, i) => (
                        <Cell key={i} fill={d.overlapping ? "#F59E0B" : "#10B981"} />
                      ))}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              </div>
              <div className="flex items-center gap-4 mt-3 text-[10px] font-bold tracking-wider uppercase">
                <div className="flex items-center gap-1"><div className="w-3 h-3 rounded bg-amber-500" />Overlapping (2+ funds)</div>
                <div className="flex items-center gap-1"><div className="w-3 h-3 rounded bg-emerald-500" />Unique</div>
              </div>
            </CardContent>
          </Card>
        </motion.div>
      )}

      {/* Fund-by-Fund Benchmark Ratings */}
      <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.15 }}>
        <Card className="bg-white dark:bg-slate-800 border-slate-100 dark:border-slate-700 rounded-2xl">
          <CardContent className="p-6 md:p-8">
            <h3 className="text-lg font-medium text-slate-900 dark:text-white mb-6" style={{ fontFamily: "'Outfit', sans-serif" }}>
              Fund-by-Fund Benchmark Comparison
            </h3>
            <div className="space-y-3" data-testid="fund-ratings-list">
              {ratings.map((r, i) => {
                const cfg = RATING_CONFIG[r.rating] || RATING_CONFIG.no_data;
                const RIcon = cfg.icon;
                return (
                  <motion.div
                    key={i}
                    initial={{ opacity: 0, x: -8 }}
                    animate={{ opacity: 1, x: 0 }}
                    transition={{ delay: i * 0.02 }}
                    className={`rounded-xl border ${cfg.border} ${cfg.bg} p-4`}
                    data-testid={`fund-rating-${i}`}
                  >
                    <div className="flex items-start justify-between gap-4">
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2 mb-1">
                          <RIcon className="w-4 h-4 flex-shrink-0" style={{ color: cfg.color }} />
                          <p className="text-sm font-medium text-slate-900 dark:text-white truncate">{r.name}</p>
                        </div>
                        <div className="flex items-center gap-3 text-xs text-slate-500 dark:text-slate-400">
                          <span>{r.sector}</span>
                          {r.scheme_category && <span className="text-[10px] px-1.5 py-0.5 rounded bg-slate-100 dark:bg-slate-700">{r.scheme_category}</span>}
                        </div>
                      </div>

                      <div className="flex-shrink-0 text-right">
                        <span className="text-xs font-bold uppercase tracking-wider px-2 py-1 rounded-lg" style={{ backgroundColor: `${cfg.color}15`, color: cfg.color }}>
                          {cfg.label}
                        </span>
                      </div>
                    </div>

                    {/* Return comparison bar */}
                    <div className="mt-3 grid grid-cols-3 gap-4">
                      <div>
                        <p className="text-[10px] text-slate-400 mb-0.5">1Y Return</p>
                        <p className={`text-sm font-bold ${(r.return_1y || 0) >= 0 ? "text-emerald-600" : "text-red-500"}`} style={{ fontFamily: "'JetBrains Mono', monospace" }}>
                          {r.return_1y !== null ? `${r.return_1y >= 0 ? "+" : ""}${r.return_1y}%` : "—"}
                        </p>
                      </div>
                      <div>
                        <p className="text-[10px] text-slate-400 mb-0.5">Benchmark</p>
                        <p className="text-sm font-medium text-slate-700 dark:text-slate-300" style={{ fontFamily: "'JetBrains Mono', monospace" }}>
                          {r.benchmark_return !== null ? `${r.benchmark_return >= 0 ? "+" : ""}${r.benchmark_return}%` : "—"}
                        </p>
                        {r.benchmark_name && <p className="text-[9px] text-slate-400">{r.benchmark_name}</p>}
                      </div>
                      <div>
                        <p className="text-[10px] text-slate-400 mb-0.5">Alpha</p>
                        <p className={`text-sm font-bold ${(r.alpha || 0) >= 0 ? "text-emerald-600" : "text-red-500"}`} style={{ fontFamily: "'JetBrains Mono', monospace" }}>
                          {r.alpha !== null ? `${r.alpha >= 0 ? "+" : ""}${r.alpha}%` : "—"}
                        </p>
                      </div>
                    </div>

                    {/* Visual bar: fund return vs benchmark */}
                    {r.return_1y !== null && r.benchmark_return !== null && (
                      <div className="mt-2">
                        <div className="flex items-center gap-2">
                          <div className="flex-1 h-2 rounded-full bg-slate-100 dark:bg-slate-700 overflow-hidden relative">
                            <div className="h-full rounded-full absolute top-0 left-0" style={{ width: `${Math.min(Math.max(((r.return_1y + 20) / 60) * 100, 5), 95)}%`, backgroundColor: cfg.color, opacity: 0.7 }} />
                          </div>
                          <span className="text-[9px] text-slate-400 w-8 text-right">Fund</span>
                        </div>
                        <div className="flex items-center gap-2 mt-0.5">
                          <div className="flex-1 h-2 rounded-full bg-slate-100 dark:bg-slate-700 overflow-hidden relative">
                            <div className="h-full rounded-full absolute top-0 left-0 bg-slate-400" style={{ width: `${Math.min(Math.max(((r.benchmark_return + 20) / 60) * 100, 5), 95)}%` }} />
                          </div>
                          <span className="text-[9px] text-slate-400 w-8 text-right">Avg</span>
                        </div>
                      </div>
                    )}
                  </motion.div>
                );
              })}
            </div>
          </CardContent>
        </Card>
      </motion.div>
    </div>
  );
};
