import React, { useState, useEffect, useMemo } from "react";
import axios from "axios";
import {
  Sparkles, RefreshCw, AlertTriangle, TrendingUp, TrendingDown,
  ArrowRight, Target, DollarSign, Shield, Layers, Building2,
  BarChart3, ArrowUpRight, ArrowDownRight, ChevronDown, ChevronUp, Filter, Zap,
  HelpCircle, Lightbulb,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { motion, AnimatePresence } from "framer-motion";
import { toast } from "sonner";
import {
  PieChart, Pie, Cell, ResponsiveContainer, Tooltip,
  BarChart, Bar, XAxis, YAxis, CartesianGrid,
} from "recharts";
import { useNumberFormat } from "@/context/NumberFormatContext";
import { InsightsSkeleton } from "@/components/ui/skeleton-loaders";
import AICopilotView from "@/components/copilot/AICopilotView";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
const API = `${BACKEND_URL}/api`;

const RISK_COLORS = { high: "#EF4444", medium: "#F59E0B", low: "#10B981" };
const CHART_COLORS = ["#059669", "#3B82F6", "#F59E0B", "#8B5CF6", "#EF4444", "#EC4899", "#14B8A6", "#F97316", "#6366F1", "#84CC16"];

const InsightsView = ({ insights: basicInsights, onRefresh, riskProfile, copilotEnabled = false }) => {
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
  const doNothing = analysis?.do_nothing_scenario;

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
      <div data-testid="insights-loading" className="space-y-6 bg-[#F8FAFC] dark:bg-[#09090B] -m-4 sm:-m-6 lg:-m-8 p-4 sm:p-6 lg:p-8 min-h-screen rounded-2xl">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
          <div>
            <h1 className="text-2xl sm:text-3xl font-bold tracking-tight text-slate-900 dark:text-white">
              Portfolio Analysis
            </h1>
            <p className="text-sm text-slate-500 dark:text-zinc-500 mt-1">Loading analysis...</p>
          </div>
        </div>
        <InsightsSkeleton />
      </div>
    );
  }

  return (
    <div data-testid="insights-view" className="space-y-6 bg-[#F8FAFC] dark:bg-[#09090B] -m-4 sm:-m-6 lg:-m-8 p-4 sm:p-6 lg:p-8 min-h-screen rounded-2xl">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        <div>
          <h1
            className="text-2xl sm:text-3xl font-bold tracking-tight text-slate-900 dark:text-white"
          >
            Portfolio Analysis
          </h1>
          <p className="text-sm text-slate-500 dark:text-zinc-500 mt-1">
            AI-powered deep analysis & recommendations
          </p>
        </div>
        <Button
          data-testid="generate-insights-button"
          onClick={generate}
          disabled={generating}
          className="bg-teal-600 hover:bg-teal-700 text-slate-900 dark:text-white rounded-xl border-0 w-full sm:w-auto"
        >
          {generating ? (
            <RefreshCw className="w-4 h-4 mr-2 animate-spin" />
          ) : (
            <Sparkles className="w-4 h-4 mr-2" />
          )}
          {generating ? "Analyzing..." : "Analyze Portfolio"}
        </Button>
      </div>

      {/* Tab Navigation — Dark Theme */}
      <div className="flex gap-1 bg-slate-100 dark:bg-[#1A1A1A] rounded-xl p-1 border border-slate-200 dark:border-white/5 overflow-x-auto scrollbar-hide" data-testid="insights-tabs">
        {tabs.map(tab => (
          <button
            key={tab.id}
            data-testid={`tab-${tab.id}`}
            onClick={() => setActiveTab(tab.id)}
            className={`flex-shrink-0 sm:flex-1 px-3 sm:px-4 py-2.5 text-xs sm:text-sm font-medium rounded-lg transition-all whitespace-nowrap ${
              activeTab === tab.id
                ? "bg-[#27272A] text-slate-900 dark:text-white shadow-sm"
                : "text-slate-500 dark:text-zinc-500 hover:text-slate-700 dark:text-zinc-300"
            }`}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {!analysis && ins.length === 0 && !deepAnalytics ? (
        <Card className="bg-white dark:bg-[#121212] border-slate-100 dark:border-slate-200 dark:border-white/5 rounded-2xl">
          <CardContent className="p-12 text-center">
            <Sparkles className="w-12 h-12 text-zinc-600 mx-auto mb-4" />
            <h3 className="text-lg font-medium text-slate-900 dark:text-white mb-2">
              No analysis yet
            </h3>
            <p className="text-sm text-slate-500 dark:text-zinc-500">
              Click "Analyze Portfolio" to get AI-powered insights and recommendations.
            </p>
          </CardContent>
        </Card>
      ) : (
        <>
          {/* ══════════════ TAB: AI COPILOT (gated) ══════════════ */}
          {activeTab === "overview" && (
            copilotEnabled ? (
              <AICopilotView riskProfile={riskProfile} />
            ) : (
              <OverviewTab
                pd={pd}
                gauge={gauge}
                ba={ba}
                cost={cost}
                ins={ins}
                funnel={funnel}
                doNothing={doNothing}
                fmt={fmt}
                analytics={deepAnalytics}
              />
            )
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
            <OverlapTab overlaps={overlapMatrix} duplication={deepAnalytics?.duplication} fmt={fmt} />
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
const SEVERITY_CONFIG = {
  critical: { color: "#EF4444", bg: "bg-red-500/10", border: "border-red-500/20", label: "Critical", icon: AlertTriangle },
  important: { color: "#F59E0B", bg: "bg-amber-500/10", border: "border-amber-500/20", label: "Important", icon: AlertTriangle },
  optimization: { color: "#3B82F6", bg: "bg-blue-500/10", border: "border-blue-500/20", label: "Optimize", icon: TrendingUp },
  positive: { color: "#10B981", bg: "bg-emerald-500/10", border: "border-emerald-500/20", label: "Good", icon: Target },
};

const OverviewTab = ({ pd, gauge, ba, cost, ins, funnel, doNothing, fmt, analytics }) => {
  const [expandedInsight, setExpandedInsight] = useState(null);
  const [completedActions, setCompletedActions] = useState({});
  const [simulation, setSimulation] = useState(null);
  const [simulating, setSimulating] = useState(false);
  const [showHealthExplain, setShowHealthExplain] = useState(false);
  const [showRiskExplain, setShowRiskExplain] = useState(false);
  const [activeIssueCategory, setActiveIssueCategory] = useState(null);

  const toggleAction = (step) => setCompletedActions(prev => ({ ...prev, [step]: !prev[step] }));
  const completedCount = Object.values(completedActions).filter(Boolean).length;

  // Helper: find holdings affected by an insight
  const getAffectedHoldings = (insight, perfCards) => {
    if (!perfCards || perfCards.length === 0) return [];
    const title = (insight.title || "").toLowerCase();
    const summary = (insight.summary || insight.description || "").toLowerCase();
    const action = (insight.action || "").toLowerCase();
    const allText = `${title} ${summary} ${action}`;

    return perfCards.filter(h => {
      const name = h.name.toLowerCase();
      const sector = (h.sector || "").toLowerCase();
      const type = (h.asset_type || "").toLowerCase();

      // Direct name mention
      if (allText.includes(name.slice(0, 15))) return true;

      // Category-based matching
      if (allText.includes("gold") && (sector.includes("gold") || type === "gold")) return true;
      if (allText.includes("debt") && (type.includes("debt") || sector.includes("debt"))) return true;
      if (allText.includes("small cap") && sector.includes("small cap")) return true;
      if (allText.includes("expense") && type === "mutual_fund") return true;
      if (allText.includes("equity") && type === "equity") return true;
      if (allText.includes("mutual fund") && type === "mutual_fund") return true;
      if (allText.includes("concentration") && type === "mutual_fund") return true;
      if (allText.includes("regular") && name.includes("regular")) return true;
      return false;
    }).slice(0, 15);
  };

  // Helper: find holdings for an issue category from the donut chart
  const getHoldingsForIssue = (category, perfCards, insights) => {
    if (!perfCards || perfCards.length === 0) return [];
    const cat = category.toLowerCase();

    if (cat.includes("risk")) {
      return perfCards.filter(h => h.pct_return < -5 || (h.sector || "").toLowerCase().includes("small")).slice(0, 10);
    }
    if (cat.includes("allocation")) {
      return perfCards.filter(h => h.weight > 5).sort((a, b) => b.weight - a.weight).slice(0, 10);
    }
    if (cat.includes("cost")) {
      return perfCards.filter(h => h.asset_type === "mutual_fund" && h.name.toLowerCase().includes("regular")).slice(0, 10);
    }
    if (cat.includes("redundancy")) {
      const sectorMap = {};
      perfCards.forEach(h => {
        const s = h.sector || "Other";
        if (!sectorMap[s]) sectorMap[s] = [];
        sectorMap[s].push(h);
      });
      const dupes = [];
      Object.values(sectorMap).forEach(arr => { if (arr.length > 2) dupes.push(...arr); });
      return dupes.slice(0, 10);
    }
    return perfCards.slice(0, 8);
  };

  // Compute confidence score from analytics data
  const totalHoldings = analytics?.performance_cards?.length || 0;
  const navMatched = analytics?.performance_cards?.filter(c => c.nav_source === "AMFI").length || 0;
  const livePriced = analytics?.performance_cards?.filter(c => c.nav_source === "yahoo_finance" || c.nav_source === "AMFI").length || 0;
  const confidencePct = totalHoldings > 0 ? Math.min(100, Math.round(((navMatched + livePriced) / totalHoldings) * 50 + 50)) : 0;

  const runSimulation = async () => {
    setSimulating(true);
    try {
      const res = await axios.get(`${API}/portfolio/simulate`, { withCredentials: true });
      if (res.data) setSimulation(res.data);
    } catch {
      toast.error("Failed to run simulation");
    } finally {
      setSimulating(false);
    }
  };

  return (
    <div className="space-y-6">
      {/* Section 1: Portfolio Health + Risk Assessment + Data Confidence */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {gauge && gauge.current > 0 && (
          <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }}>
            <Card className="bg-white dark:bg-[#121212] border-slate-100 dark:border-white/5 rounded-2xl h-full" data-testid="health-score-card">
              <CardContent className="p-6 text-center">
                <p className="text-[10px] font-bold tracking-wider uppercase text-slate-400 mb-3">Portfolio Health</p>
                <div className="relative w-24 h-24 mx-auto mb-3">
                  <svg viewBox="0 0 100 100" className="w-full h-full -rotate-90">
                    <circle cx="50" cy="50" r="42" fill="none" stroke="#F1F5F9" strokeWidth="8" className="dark:stroke-slate-700" />
                    <circle cx="50" cy="50" r="42" fill="none" strokeWidth="8" strokeDasharray={`${(100 - gauge.current) * 2.64} 264`} strokeLinecap="round"
                      stroke={gauge.current > 60 ? "#EF4444" : gauge.current > 35 ? "#F59E0B" : "#10B981"} />
                  </svg>
                  <div className="absolute inset-0 flex flex-col items-center justify-center">
                    <span className="text-2xl font-bold text-slate-900 dark:text-white" style={{ fontFamily: "'JetBrains Mono', monospace" }}>{100 - gauge.current}</span>
                    <span className="text-[9px] text-slate-400">/100</span>
                  </div>
                </div>
                <p className={`text-sm font-semibold ${gauge.current > 60 ? "text-red-500" : gauge.current > 35 ? "text-amber-500" : "text-emerald-600"}`}>
                  {gauge.current > 60 ? "Needs Attention" : gauge.current > 35 ? "Moderate" : "Healthy"}
                </p>
                <button onClick={() => setShowHealthExplain(!showHealthExplain)} className="mt-2 inline-flex items-center gap-1 text-[10px] text-slate-400 hover:text-emerald-600 transition-colors" data-testid="health-explain-toggle">
                  <HelpCircle className="w-3 h-3" /> {showHealthExplain ? "Hide" : "How is this calculated?"}
                </button>
                <AnimatePresence>
                  {showHealthExplain && (
                    <motion.div initial={{ height: 0, opacity: 0 }} animate={{ height: "auto", opacity: 1 }} exit={{ height: 0, opacity: 0 }} className="overflow-hidden">
                      <div className="mt-3 text-left p-3 bg-slate-100 dark:bg-[#1A1A1A] rounded-lg text-[11px] text-slate-600 dark:text-zinc-400 space-y-1">
                        <p className="font-semibold text-slate-700 dark:text-slate-200">Health = 30% Diversification + 25% Risk + 20% Cost + 25% Performance</p>
                        <p>Based on HHI concentration, asset types, sector spread, plan types, and returns.</p>
                      </div>
                    </motion.div>
                  )}
                </AnimatePresence>
              </CardContent>
            </Card>
          </motion.div>
        )}

        {gauge && gauge.current > 0 && (
          <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.05 }}>
            <Card className="bg-white dark:bg-[#121212] border-slate-100 dark:border-white/5 rounded-2xl h-full">
              <CardContent className="p-6">
                <p className="text-[10px] font-bold tracking-wider uppercase text-slate-400 mb-4">Risk Assessment</p>
                <div>
                  <div className="flex justify-between text-xs mb-1">
                    <span className="text-slate-500">Current</span>
                    <span className="font-semibold text-red-500">{gauge.current_label} ({gauge.current})</span>
                  </div>
                  <div className="w-full h-3 rounded-full bg-slate-50 dark:bg-zinc-800/50 overflow-hidden">
                    <div className="h-full rounded-full transition-all duration-700" style={{ width: `${gauge.current}%`, background: "linear-gradient(90deg, #10B981, #F59E0B, #EF4444)" }} />
                  </div>
                </div>
                <button onClick={() => setShowRiskExplain(!showRiskExplain)} className="mt-3 inline-flex items-center gap-1 text-[10px] text-slate-400 hover:text-emerald-600 transition-colors" data-testid="risk-explain-toggle">
                  <HelpCircle className="w-3 h-3" /> {showRiskExplain ? "Hide" : "Why is this high?"}
                </button>
                <AnimatePresence>
                  {showRiskExplain && (
                    <motion.div initial={{ height: 0, opacity: 0 }} animate={{ height: "auto", opacity: 1 }} exit={{ height: 0, opacity: 0 }} className="overflow-hidden">
                      <div className="mt-3 text-left p-3 bg-slate-100 dark:bg-[#1A1A1A] rounded-lg text-[11px] text-slate-600 dark:text-zinc-400 space-y-1">
                        <p className="font-semibold text-red-600 dark:text-red-400">Risk: {gauge.current}/100</p>
                        <ul className="list-disc pl-3 space-y-0.5">
                          {analytics?.overexposure?.fund_house?.filter(f => f.risk_level === "high").map(f => (
                            <li key={f.name}><strong>{f.name}</strong> AMC: {f.pct}%</li>
                          ))}
                          {analytics?.overexposure?.sector?.filter(s => s.risk_level === "high").map(s => (
                            <li key={s.name}><strong>{s.name}</strong>: {s.pct}%</li>
                          ))}
                        </ul>
                      </div>
                    </motion.div>
                  )}
                </AnimatePresence>
              </CardContent>
            </Card>
          </motion.div>
        )}

        <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.1 }}>
          <Card className="bg-white dark:bg-[#121212] border-slate-100 dark:border-white/5 rounded-2xl h-full" data-testid="confidence-card">
            <CardContent className="p-6">
              <p className="text-[10px] font-bold tracking-wider uppercase text-slate-400 mb-4">Data Confidence</p>
              <div className="text-center mb-3">
                <span className="text-3xl font-bold text-slate-900 dark:text-white" style={{ fontFamily: "'JetBrains Mono', monospace" }}>{confidencePct}%</span>
              </div>
              <div className="space-y-2 text-xs">
                <div className="flex items-center gap-2"><div className={`w-2 h-2 rounded-full ${totalHoldings > 0 ? "bg-emerald-500" : "bg-slate-300"}`} /><span className="text-slate-500 dark:text-zinc-500">{totalHoldings} holdings tracked</span></div>
                <div className="flex items-center gap-2"><div className={`w-2 h-2 rounded-full ${navMatched > 0 ? "bg-emerald-500" : "bg-amber-500"}`} /><span className="text-slate-500 dark:text-zinc-500">{navMatched} MFs with live NAV</span></div>
                {confidencePct < 70 && <p className="text-[10px] text-amber-500 mt-1">Some holdings use estimated prices.</p>}
              </div>
            </CardContent>
          </Card>
        </motion.div>
      </div>

      {/* Section 2: Issue Breakdown + Cost Leakage */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {pd.length > 0 && (
          <Card className="bg-white dark:bg-[#121212] border-slate-100 dark:border-white/5 rounded-2xl">
            <CardContent className="p-6">
              <p className="text-[10px] font-bold tracking-wider uppercase text-slate-400 mb-4">Issue Breakdown</p>
              <div className="h-36 cursor-pointer">
                <ResponsiveContainer width="100%" height="100%">
                  <PieChart><Pie data={pd} cx="50%" cy="50%" innerRadius={32} outerRadius={55} paddingAngle={2} dataKey="value" onClick={(_, idx) => setActiveIssueCategory(activeIssueCategory === pd[idx]?.name ? null : pd[idx]?.name)}>
                    {pd.map((d) => (<Cell key={`pie-${d.name}`} fill={d.color} stroke={activeIssueCategory === d.name ? "#1E293B" : "transparent"} strokeWidth={activeIssueCategory === d.name ? 2 : 0} style={{ cursor: "pointer", opacity: activeIssueCategory && activeIssueCategory !== d.name ? 0.4 : 1 }} />))}
                  </Pie><Tooltip formatter={v => `${v}%`} /></PieChart>
                </ResponsiveContainer>
              </div>
              <div className="space-y-1 mt-2">
                {pd.map(d => (
                  <div key={d.name}>
                    <div className={`flex items-center justify-between cursor-pointer rounded-lg px-2 py-1 transition-colors ${activeIssueCategory === d.name ? "bg-slate-100 dark:bg-zinc-800/50" : "hover:bg-slate-50 dark:hover:bg-zinc-800/30"}`} onClick={() => setActiveIssueCategory(activeIssueCategory === d.name ? null : d.name)} data-testid={`issue-${d.name.replace(/\s/g, '-').toLowerCase()}`}>
                      <div className="flex items-center gap-2"><div className="w-2.5 h-2.5 rounded-full" style={{ backgroundColor: d.color }} /><span className="text-xs text-slate-500 dark:text-zinc-500">{d.name}</span></div>
                      <span className="text-xs font-medium text-slate-900 dark:text-white">{d.value}%</span>
                    </div>
                    {d.reason && (
                      <p className="text-[10px] text-slate-400 dark:text-zinc-500 pl-5 -mt-0.5 mb-1">{d.reason}</p>
                    )}
                  </div>
                ))}
              </div>
              <AnimatePresence>
                {activeIssueCategory && analytics?.performance_cards?.length > 0 && (
                  <motion.div initial={{ height: 0, opacity: 0 }} animate={{ height: "auto", opacity: 1 }} exit={{ height: 0, opacity: 0 }} className="overflow-hidden">
                    <div className="mt-3 pt-3 border-t border-slate-200 dark:border-white/5">
                      <p className="text-[10px] font-bold tracking-wider uppercase text-slate-400 mb-2">Why \"{activeIssueCategory}\" \u2014 Affected Holdings</p>
                      <div className="space-y-1 max-h-40 overflow-y-auto">
                        {getHoldingsForIssue(activeIssueCategory, analytics.performance_cards, ins).map((h, idx) => (
                          <div key={`drill-${idx}`} className="flex items-center justify-between py-1.5 px-2 bg-slate-50 dark:bg-[#1A1A1A] rounded text-[11px]">
                            <span className="text-slate-700 dark:text-zinc-300 truncate flex-1">{h.name}</span>
                            <span className={`ml-2 font-medium ${h.pct_return >= 0 ? "text-emerald-600" : "text-red-500"}`}>{h.pct_return >= 0 ? "+" : ""}{h.pct_return}%</span>
                            <span className="ml-2 text-slate-400">{fmt(h.current_value)}</span>
                          </div>
                        ))}
                        {getHoldingsForIssue(activeIssueCategory, analytics.performance_cards, ins).length === 0 && (<p className="text-[10px] text-slate-400 py-2">No holdings data for this category.</p>)}
                      </div>
                    </div>
                  </motion.div>
                )}
              </AnimatePresence>
            </CardContent>
          </Card>
        )}

        <Card className="bg-white dark:bg-[#121212] border-slate-100 dark:border-white/5 rounded-2xl">
          <CardContent className="p-6">
            <p className="text-[10px] font-bold tracking-wider uppercase text-slate-400 mb-4">Cost Leakage</p>
            {cost && cost.annual_loss > 0 ? (<>
              <div className="text-center mb-4">
                <p className="text-3xl font-bold text-red-500" style={{ fontFamily: "'Outfit', sans-serif" }}>{fmt(cost.annual_loss)}</p>
                <p className="text-xs text-red-400 mt-1">lost per year ({cost.loss_pct}% of portfolio)</p>
              </div>
              <p className="text-xs text-slate-500 dark:text-zinc-500 text-center">{cost.detail}</p>
              <div className="mt-4 p-3 bg-emerald-50 dark:bg-emerald-900/15 rounded-lg text-center"><p className="text-xs text-emerald-600 font-medium">Switching to direct plans could save {fmt(cost.annual_loss)}/year</p></div>
            </>) : (
              <div className="text-center py-4"><p className="text-emerald-600 font-medium text-sm">No significant cost leakage</p><p className="text-xs text-slate-400 mt-1">All funds appear to be direct plans or data unavailable</p></div>
            )}
          </CardContent>
        </Card>
      </div>

      {/* Section 3: Actionable Insights */}
      {ins.length > 0 && (
        <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.15 }}>
          <div className="space-y-3" data-testid="actionable-insights">
            <h3 className="text-sm font-medium text-slate-900 dark:text-white">Actionable Insights ({ins.length})</h3>
            {ins.map((insight, i) => {
              const sev = SEVERITY_CONFIG[insight.severity] || SEVERITY_CONFIG[insight.type === "warning" ? "critical" : "important"] || SEVERITY_CONFIG.important;
              const SevIcon = sev.icon;
              const isExpanded = expandedInsight === i;
              return (
                <motion.div key={`insight-${insight.insight_id || i}`} initial={{ opacity: 0, x: -8 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: i * 0.03 }} className={`rounded-xl border ${sev.border} overflow-hidden`} data-testid={`insight-card-${i}`}>
                  <div className={`p-4 cursor-pointer ${sev.bg} hover:opacity-90 transition-opacity`} onClick={() => setExpandedInsight(isExpanded ? null : i)}>
                    <div className="flex items-start gap-3">
                      <SevIcon className="w-4 h-4 flex-shrink-0 mt-0.5" style={{ color: sev.color }} />
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2"><p className="text-sm font-semibold text-slate-900 dark:text-white">{insight.title}</p><span className="text-[9px] font-bold uppercase tracking-wider px-1.5 py-0.5 rounded" style={{ backgroundColor: `${sev.color}15`, color: sev.color }}>{sev.label}</span></div>
                        <p className="text-xs text-slate-500 dark:text-zinc-500 mt-0.5">{insight.description?.slice(0, 100)}{insight.description?.length > 100 ? "..." : ""}</p>
                      </div>
                      <ChevronDown className={`w-4 h-4 text-slate-400 flex-shrink-0 transition-transform ${isExpanded ? "rotate-180" : ""}`} />
                    </div>
                  </div>
                  {isExpanded && (
                    <div className="p-4 bg-white dark:bg-[#121212] border-t border-slate-100 dark:border-white/5 space-y-3">
                      {insight.description && (<div><p className="text-[10px] font-bold tracking-wider uppercase text-slate-400 mb-1">Details</p><p className="text-xs text-slate-600 dark:text-zinc-400 leading-relaxed">{insight.description}</p></div>)}
                      {insight.action && (
                        <div className="p-3 bg-emerald-50 dark:bg-emerald-900/15 rounded-lg border border-emerald-200 dark:border-emerald-500/20">
                          <p className="text-[10px] font-bold tracking-wider uppercase text-emerald-600 mb-1">Recommended Action</p>
                          <p className="text-xs text-emerald-700 dark:text-emerald-300 font-medium">{insight.action}</p>
                        </div>
                      )}
                      {insight.current_value && insight.target_value && (
                        <div className="flex gap-4">
                          <div className="flex-1 p-2 rounded-lg bg-red-50 dark:bg-red-500/5 border border-red-200 dark:border-red-500/20">
                            <p className="text-[9px] font-bold uppercase text-red-500">Current</p>
                            <p className="text-xs font-medium text-slate-700 dark:text-zinc-300 mt-0.5">{insight.current_value}</p>
                          </div>
                          <div className="flex-1 p-2 rounded-lg bg-emerald-50 dark:bg-emerald-500/5 border border-emerald-200 dark:border-emerald-500/20">
                            <p className="text-[9px] font-bold uppercase text-emerald-600">Target</p>
                            <p className="text-xs font-medium text-slate-700 dark:text-zinc-300 mt-0.5">{insight.target_value}</p>
                          </div>
                        </div>
                      )}
                      {insight.affected_funds?.length > 0 && (
                        <div>
                          <p className="text-[10px] font-bold tracking-wider uppercase text-slate-400 mb-1">Affected Funds</p>
                          <div className="flex flex-wrap gap-1.5">
                            {insight.affected_funds.map((f, fi) => (
                              <span key={`af-${fi}`} className="text-[10px] px-2 py-0.5 rounded-full bg-slate-100 dark:bg-zinc-800/50 text-slate-600 dark:text-zinc-400">{f}</span>
                            ))}
                          </div>
                        </div>
                      )}
                      {analytics?.performance_cards?.length > 0 && getAffectedHoldings(insight, analytics.performance_cards).length > 0 && (
                        <div><p className="text-[10px] font-bold tracking-wider uppercase text-slate-400 mb-2">Holdings Impact</p>
                          <div className="space-y-1 max-h-48 overflow-y-auto">
                            {getAffectedHoldings(insight, analytics.performance_cards).map((h, hi) => (
                              <div key={`aff-${hi}`} className="flex items-center justify-between py-1.5 px-2 bg-slate-50 dark:bg-[#1A1A1A] rounded-lg text-xs">
                                <span className="text-slate-700 dark:text-zinc-300 truncate flex-1">{h.name}</span>
                                <span className={`font-medium ml-2 ${h.pct_return >= 0 ? "text-emerald-600" : "text-red-500"}`}>{h.pct_return >= 0 ? "+" : ""}{h.pct_return}%</span>
                                <span className="text-slate-500 ml-2">{fmt(h.current_value)}</span>
                              </div>
                            ))}
                          </div>
                        </div>
                      )}
                    </div>
                  )}
                </motion.div>
              );
            })}
          </div>
        </motion.div>
      )}

      {/* Section 4: Action Plan */}
      {funnel.length > 0 && (
        <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.2 }}>
          <Card className="bg-white dark:bg-[#121212] border-slate-100 dark:border-white/5 rounded-2xl" data-testid="action-funnel">
            <CardContent className="p-6 md:p-8">
              <div className="flex items-center justify-between mb-6">
                <h3 className="text-sm font-medium text-slate-900 dark:text-white">Action Plan</h3>
                <div className="flex items-center gap-2">
                  <div className="w-20 h-2 rounded-full bg-slate-50 dark:bg-zinc-800/50 overflow-hidden"><div className="h-full rounded-full bg-emerald-500 transition-all" style={{ width: `${funnel.length > 0 ? (completedCount / funnel.length) * 100 : 0}%` }} /></div>
                  <span className="text-xs text-slate-400">{completedCount}/{funnel.length}</span>
                </div>
              </div>
              <div className="space-y-3">
                {funnel.map((step, i) => {
                  const done = completedActions[step.step];
                  const statusColors = { critical: "#EF4444", important: "#F59E0B", moderate: "#3B82F6", recommended: "#10B981" };
                  return (
                    <div key={`action-${i}`} className={`flex items-start gap-4 p-3 rounded-xl transition-all ${done ? "bg-emerald-50 dark:bg-emerald-900/20 opacity-70" : "hover:bg-slate-50 dark:hover:bg-zinc-800/30"}`}>
                      <button onClick={() => toggleAction(step.step)} className={`w-7 h-7 rounded-lg flex items-center justify-center flex-shrink-0 border-2 transition-all ${done ? "bg-emerald-500 border-emerald-500 text-white" : "border-slate-200 dark:border-zinc-700"}`} data-testid={`action-check-${i}`}>
                        {done ? <span className="text-xs font-bold">\u2713</span> : <span className="text-xs font-bold text-slate-400">{step.step}</span>}
                      </button>
                      <div className="flex-1"><p className={`text-sm font-medium ${done ? "line-through text-slate-400" : "text-slate-900 dark:text-white"}`}>{step.title}</p><p className="text-xs text-slate-500 dark:text-zinc-500 mt-0.5">{step.detail}</p>{step.rupee_impact && <p className="text-[10px] text-emerald-600 font-medium mt-1">{step.rupee_impact}</p>}</div>
                      <span className="text-[9px] font-bold uppercase tracking-wider px-2 py-0.5 rounded-full flex-shrink-0" style={{ backgroundColor: `${statusColors[step.status] || "#94A3B8"}15`, color: statusColors[step.status] || "#94A3B8" }}>{step.status}</span>
                    </div>
                  );
                })}
              </div>
            </CardContent>
          </Card>
        </motion.div>
      )}

      {/* Section 5: Simulate + Before/After */}
      <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.25 }}>
        <Card className="bg-gradient-to-r from-emerald-50 to-blue-50 dark:from-emerald-900/15 dark:to-blue-900/15 border-emerald-500/20 rounded-2xl" data-testid="simulate-card">
          <CardContent className="p-6">
            <div className="flex items-center justify-between mb-4">
              <div className="flex items-center gap-3">
                <div className="w-10 h-10 rounded-xl bg-emerald-100 dark:bg-emerald-900/30 flex items-center justify-center"><Zap className="w-5 h-5 text-emerald-600" strokeWidth={1.5} /></div>
                <div><h3 className="text-sm font-semibold text-slate-900 dark:text-white">Simulate Impact</h3><p className="text-[11px] text-slate-500 dark:text-zinc-500">See projected returns if action plan is implemented</p></div>
              </div>
              <Button data-testid="simulate-button" onClick={runSimulation} disabled={simulating} className="bg-emerald-600 hover:bg-emerald-700 text-white rounded-xl">
                {simulating ? <RefreshCw className="w-4 h-4 mr-2 animate-spin" /> : <Zap className="w-4 h-4 mr-2" />}{simulating ? "Simulating..." : "Run Simulation"}
              </Button>
            </div>
            <AnimatePresence>
              {simulation && (
                <motion.div initial={{ height: 0, opacity: 0 }} animate={{ height: "auto", opacity: 1 }} exit={{ height: 0, opacity: 0 }} className="overflow-hidden">
                  <div className="border-t border-emerald-500/20 pt-4 mt-2 space-y-4">
                    <p className="text-[10px] font-bold tracking-wider uppercase text-slate-400">If You Apply These Changes</p>
                    <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                      <div className="text-center p-3 bg-white dark:bg-[#121212] rounded-xl border border-slate-200 dark:border-white/5">
                        <p className="text-[9px] font-bold tracking-wider uppercase text-slate-400 mb-1">Current</p>
                        <p className="text-lg font-bold text-slate-700 dark:text-zinc-300" style={{ fontFamily: "'JetBrains Mono', monospace" }}>{simulation.current_returns_pct >= 0 ? "+" : ""}{simulation.current_returns_pct}%</p>
                      </div>
                      <div className="text-center p-3 bg-white dark:bg-[#121212] rounded-xl border border-slate-200 dark:border-white/5">
                        <p className="text-[9px] font-bold tracking-wider uppercase text-emerald-600 mb-1">After (1Y)</p>
                        <p className="text-lg font-bold text-emerald-600" style={{ fontFamily: "'JetBrains Mono', monospace" }}>+{simulation.optimized_returns_pct}%</p>
                      </div>
                      <div className="text-center p-3 bg-emerald-50 dark:bg-emerald-900/20 rounded-xl border border-emerald-500/20">
                        <p className="text-[9px] font-bold tracking-wider uppercase text-emerald-600 mb-1">Extra Returns</p>
                        <p className="text-xl font-bold text-emerald-600">+{fmt(simulation.additional_returns)}</p>
                      </div>
                      <div className="text-center p-3 bg-white dark:bg-[#121212] rounded-xl border border-slate-200 dark:border-white/5">
                        <p className="text-[9px] font-bold tracking-wider uppercase text-slate-400 mb-1">Actions</p>
                        <p className="text-lg font-bold text-slate-700 dark:text-zinc-300">{simulation.actions?.length || 0}</p>
                      </div>
                    </div>
                    {simulation.actions?.length > 0 && (<div className="space-y-2"><p className="text-[10px] font-bold tracking-wider uppercase text-slate-400">Breakdown</p>
                      {simulation.actions.map((a, i) => (
                        <div key={`sim-${i}`} className="flex items-center justify-between py-2 px-3 bg-white dark:bg-[#121212] rounded-lg border border-slate-200 dark:border-white/5">
                          <span className="text-xs text-slate-700 dark:text-zinc-300 truncate">{a.title}</span>
                          <span className="text-xs font-bold text-emerald-600 ml-2" style={{ fontFamily: "'JetBrains Mono', monospace" }}>{a.savings_1yr > 0 ? `+${fmt(a.savings_1yr)}/yr` : "\u2014"}</span>
                        </div>
                      ))}
                    </div>)}
                    <p className="text-[10px] text-slate-400 text-center pt-2 border-t border-emerald-500/10">Based on rule-based recommendations from portfolio data. Actual returns may vary.</p>
                  </div>
                </motion.div>
              )}
            </AnimatePresence>
          </CardContent>
        </Card>
      </motion.div>
    </div>
  );
};

// ════════════════════════════════════════
// ALLOCATION ANALYSIS DISPLAY — MOS-style sector overexposure + company drill-down
// ════════════════════════════════════════
const AllocationAnalysisDisplay = ({ allocation, fmt }) => {
  const [view, setView] = useState("sectors");
  const [expandedSector, setExpandedSector] = useState(null);

  const sectors = allocation.sector_allocation || allocation.top_5_sectors || [];
  const companies = allocation.top_10_companies || allocation.company_allocation?.slice(0, 15) || [];
  const flags = allocation.concentration_flags || [];
  const topSector = sectors[0];
  const hasOverexposure = topSector && topSector.weight > 0.25;

  return (
    <div className="space-y-5" data-testid="allocation-display">
      {/* Alert Banner — MOS style */}
      {hasOverexposure ? (
        <div className="rounded-xl bg-red-50 dark:bg-red-500/10 border border-red-200 dark:border-red-500/20 p-4">
          <div className="flex items-start gap-3">
            <div className="w-8 h-8 rounded-lg bg-red-100 dark:bg-red-500/20 flex items-center justify-center flex-shrink-0">
              <AlertTriangle className="w-4 h-4 text-red-500" />
            </div>
            <div>
              <p className="text-sm font-semibold text-slate-900 dark:text-white">
                {topSector.sector} Sector Overexposure
              </p>
              <p className="text-xs text-slate-600 dark:text-zinc-400 mt-1">
                Your portfolio is concentrated in <strong>{topSector.sector} ({(topSector.weight * 100).toFixed(1)}%)</strong>.
                If this sector faces challenges, your entire portfolio suffers. Diversification is recommended.
              </p>
            </div>
          </div>
          {/* Stacked allocation bar */}
          <div className="mt-3 flex h-7 rounded-lg overflow-hidden">
            {sectors.slice(0, 5).map((sec, i) => {
              const pct = sec.weight * 100;
              const colors = ["#3B82F6", "#F59E0B", "#10B981", "#8B5CF6", "#EC4899"];
              return pct > 1 ? (
                <div key={sec.sector} className="flex items-center justify-center text-[9px] font-bold text-white" style={{ width: `${pct}%`, backgroundColor: colors[i % colors.length], minWidth: pct > 5 ? 0 : 20 }}>
                  {pct > 5 ? `${pct.toFixed(0)}%` : ""}
                </div>
              ) : null;
            })}
            <div className="flex-1 flex items-center justify-center text-[9px] font-bold text-slate-400 bg-slate-200 dark:bg-zinc-700">
              Others
            </div>
          </div>
        </div>
      ) : (
        <div className="rounded-xl bg-emerald-50 dark:bg-emerald-500/10 border border-emerald-200 dark:border-emerald-500/20 p-4">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 rounded-lg bg-emerald-100 dark:bg-emerald-500/20 flex items-center justify-center">
              <TrendingUp className="w-4 h-4 text-emerald-500" />
            </div>
            <div>
              <p className="text-sm font-semibold text-slate-900 dark:text-white">Well-Balanced Sector Allocation</p>
              <p className="text-xs text-slate-600 dark:text-zinc-400 mt-0.5">No single sector dominates your portfolio. Good diversification.</p>
            </div>
          </div>
        </div>
      )}

      {/* Concentration Flags */}
      {flags.length > 0 && (
        <div className="space-y-2">
          {flags.slice(0, 3).map((flag, i) => (
            <div key={`cflag-${i}`} className={`flex items-center gap-3 px-4 py-2.5 rounded-xl border ${flag.severity === "high" ? "bg-red-50 dark:bg-red-500/10 border-red-200 dark:border-red-500/20" : "bg-amber-50 dark:bg-amber-500/10 border-amber-200 dark:border-amber-500/20"}`}>
              <AlertTriangle className={`w-4 h-4 flex-shrink-0 ${flag.severity === "high" ? "text-red-500" : "text-amber-500"}`} />
              <p className="text-xs text-slate-700 dark:text-zinc-300">
                <span className="font-semibold">{flag.name}</span> — {flag.type} at <span className="font-bold">{(flag.weight * 100).toFixed(1)}%</span>
              </p>
            </div>
          ))}
        </div>
      )}

      {/* Toggle: Sectors / Companies */}
      <div className="flex gap-1 bg-slate-100 dark:bg-slate-100 dark:bg-[#1A1A1A] rounded-xl p-1">
        <button onClick={() => setView("sectors")} className={`flex-1 px-4 py-2 text-xs font-medium rounded-lg transition-all ${view === "sectors" ? "bg-white dark:bg-[#27272A] text-slate-900 dark:text-white shadow-sm" : "text-slate-500 dark:text-zinc-500"}`}>
          Sector Allocation
        </button>
        <button onClick={() => setView("companies")} className={`flex-1 px-4 py-2 text-xs font-medium rounded-lg transition-all ${view === "companies" ? "bg-white dark:bg-[#27272A] text-slate-900 dark:text-white shadow-sm" : "text-slate-500 dark:text-zinc-500"}`}>
          Company Exposure
        </button>
      </div>

      {view === "sectors" ? (
        <div className="space-y-2">
          {sectors.map((sec, i) => {
            const pct = sec.weight * 100;
            const isExpanded = expandedSector === i;
            const isHigh = pct > 25;
            const relatedCompanies = companies.filter(c => c.sector === sec.sector);
            return (
              <div key={`sec-card-${sec.sector}`}>
                <div
                  className={`flex items-center gap-3 px-4 py-3 rounded-xl border cursor-pointer transition-all ${isHigh ? "border-red-200 dark:border-red-500/20 bg-red-50/50 dark:bg-red-500/5" : "border-slate-200 dark:border-white/5 bg-white dark:bg-[#121212]"}`}
                  onClick={() => setExpandedSector(isExpanded ? null : i)}
                >
                  <div className="w-1 h-8 rounded-full" style={{ backgroundColor: ["#3B82F6", "#F59E0B", "#10B981", "#8B5CF6", "#EC4899", "#EF4444", "#06B6D4", "#D946EF"][i % 8] }} />
                  <span className="text-sm text-slate-900 dark:text-white flex-1 font-medium">{sec.sector}</span>
                  <span className="text-sm font-bold text-slate-900 dark:text-white" style={{ fontFamily: "'JetBrains Mono', monospace" }}>{pct.toFixed(1)}%</span>
                  <ChevronDown className={`w-4 h-4 text-slate-400 transition-transform ${isExpanded ? "rotate-180" : ""}`} />
                </div>
                <AnimatePresence>
                  {isExpanded && relatedCompanies.length > 0 && (
                    <motion.div initial={{ height: 0, opacity: 0 }} animate={{ height: "auto", opacity: 1 }} exit={{ height: 0, opacity: 0 }} className="overflow-hidden">
                      <div className="ml-6 pl-4 border-l-2 border-slate-200 dark:border-zinc-700 py-2 space-y-1.5">
                        {relatedCompanies.map((c, ci) => (
                          <div key={`comp-drill-${ci}`} className="flex items-center justify-between">
                            <span className="text-xs text-slate-600 dark:text-zinc-400">{c.name}</span>
                            <span className="text-xs font-bold text-slate-700 dark:text-zinc-300" style={{ fontFamily: "'JetBrains Mono', monospace" }}>{(c.weight * 100).toFixed(2)}%</span>
                          </div>
                        ))}
                      </div>
                    </motion.div>
                  )}
                </AnimatePresence>
              </div>
            );
          })}
        </div>
      ) : (
        <div className="space-y-1.5">
          {companies.slice(0, 15).map((comp, i) => {
            const pct = comp.weight * 100;
            const isHigh = pct >= 10;
            return (
              <div key={`comp-card-${comp.name}`} className={`flex items-center gap-3 px-4 py-2.5 rounded-xl border ${isHigh ? "border-red-200 dark:border-red-500/20 bg-red-50/50 dark:bg-red-500/5" : "border-slate-100 dark:border-white/5"}`}>
                <span className={`text-[10px] w-6 h-6 rounded-lg flex items-center justify-center flex-shrink-0 font-bold ${isHigh ? "bg-red-100 dark:bg-red-900/30 text-red-500" : "bg-slate-100 dark:bg-zinc-800 text-slate-500 dark:text-zinc-400"}`}>{i + 1}</span>
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-medium text-slate-900 dark:text-white truncate">{comp.name}</p>
                  <p className="text-[10px] text-slate-400">{comp.sector}</p>
                </div>
                <span className={`text-sm font-bold flex-shrink-0 ${isHigh ? "text-red-500" : "text-slate-700 dark:text-zinc-300"}`} style={{ fontFamily: "'JetBrains Mono', monospace" }}>
                  {pct.toFixed(1)}%
                </span>
              </div>
            );
          })}
        </div>
      )}

      {/* Data Quality */}
      {allocation.data_quality && (
        <p className="text-[10px] text-slate-400 text-center pt-2 border-t border-slate-200 dark:border-white/5">
          AI-estimated. {allocation.data_quality.estimated_funds || 0} MF holdings estimated, {allocation.data_quality.direct_equity_count || 0} direct equities.
        </p>
      )}
    </div>
  );
};

// ════════════════════════════════════════
// OVEREXPOSURE TAB
// ════════════════════════════════════════
const OverexposureTab = ({ overexposure, fmt }) => {
  const fundHouse = overexposure?.fund_house || [];
  const sectors = overexposure?.sector || [];
  const [expandedFH, setExpandedFH] = useState(0);
  const [expandedSec, setExpandedSec] = useState(0);
  const [allocation, setAllocation] = useState(null);
  const [loadingAllocation, setLoadingAllocation] = useState(false);

  const fetchAllocation = async () => {
    setLoadingAllocation(true);
    try {
      const res = await axios.get(`${API}/portfolio/allocation-analysis`, { withCredentials: true });
      if (!res.data.error) setAllocation(res.data);
    } catch (err) {
      console.error("Allocation analysis failed", err);
    } finally {
      setLoadingAllocation(false);
    }
  };

  useEffect(() => {
    if (fundHouse.length > 0 && !allocation) fetchAllocation();
  }, [fundHouse.length]);  // eslint-disable-line react-hooks/exhaustive-deps

  if (!fundHouse.length && !sectors.length) {
    return (
      <Card className="bg-white dark:bg-[#121212] border-slate-100 dark:border-slate-200 dark:border-white/5 rounded-2xl">
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
          <Card className="bg-white dark:bg-[#121212] border-slate-100 dark:border-slate-200 dark:border-white/5 rounded-2xl">
            <CardContent className="p-6 md:p-8">
              <div className="flex items-center gap-3 mb-6">
                <div className="w-10 h-10 rounded-xl bg-violet-50 dark:bg-violet-900/20 flex items-center justify-center">
                  <Building2 className="w-5 h-5 text-violet-600" strokeWidth={1.5} />
                </div>
                <div>
                  <h3 className="text-lg font-medium text-slate-900 dark:text-white" style={{ fontFamily: "'Outfit', sans-serif" }}>
                    Fund House Concentration
                  </h3>
                  <p className="text-xs text-slate-500 dark:text-zinc-500">
                    AMC-level exposure across your mutual fund portfolio
                  </p>
                </div>
              </div>

              {/* Stacked Allocation Chart — Current vs Ideal */}
              <div className="mb-6" data-testid="fund-house-chart">
                <div className="flex gap-6 items-end justify-center">
                  {/* Current Allocation Bar */}
                  <div className="flex flex-col items-center">
                    <p className="text-[10px] font-bold tracking-wider uppercase text-slate-400 mb-3">Current</p>
                    <div className="w-24 h-64 rounded-xl overflow-hidden flex flex-col-reverse border border-slate-200 dark:border-zinc-800">
                      {fundHouse.slice(0, 6).map((fh, i) => (
                        <div
                          key={`cur-${fh.name}`}
                          className="relative flex items-center justify-center transition-all hover:opacity-90 cursor-pointer"
                          style={{ height: `${Math.max(fh.pct, 3)}%`, backgroundColor: CHART_COLORS[i % CHART_COLORS.length] }}
                          title={`${fh.name}: ${fh.pct}%`}
                          onClick={() => setExpandedFH(expandedFH === i ? null : i)}
                        >
                          {fh.pct >= 8 && (
                            <span className="text-[10px] font-bold text-slate-900 dark:text-white drop-shadow-sm">{fh.pct}%</span>
                          )}
                        </div>
                      ))}
                    </div>
                  </div>

                  {/* Arrow */}
                  <div className="flex flex-col items-center gap-2 pb-24">
                    <ArrowRight className="w-5 h-5 text-slate-300" />
                    <p className="text-[9px] text-slate-400 font-medium">Ideal</p>
                  </div>

                  {/* Ideal Allocation Bar (balanced) */}
                  <div className="flex flex-col items-center">
                    <p className="text-[10px] font-bold tracking-wider uppercase text-slate-400 mb-3">Balanced</p>
                    <div className="w-24 h-64 rounded-xl overflow-hidden flex flex-col-reverse border border-slate-200 dark:border-zinc-800">
                      {(() => {
                        const idealPct = Math.round(100 / Math.max(fundHouse.length, 1));
                        return fundHouse.slice(0, 6).map((fh, i) => (
                          <div
                            key={`ideal-${fh.name}`}
                            className="relative flex items-center justify-center"
                            style={{ height: `${idealPct}%`, backgroundColor: CHART_COLORS[i % CHART_COLORS.length], opacity: 0.7 }}
                          >
                            {idealPct >= 8 && (
                              <span className="text-[10px] font-bold text-slate-900 dark:text-white drop-shadow-sm">{idealPct}%</span>
                            )}
                          </div>
                        ));
                      })()}
                    </div>
                  </div>
                </div>

                {/* Legend */}
                <div className="flex flex-wrap gap-3 mt-4 justify-center">
                  {fundHouse.slice(0, 6).map((fh, i) => (
                    <div key={fh.name} className="flex items-center gap-1.5 text-[10px] text-slate-500">
                      <div className="w-2.5 h-2.5 rounded" style={{ backgroundColor: CHART_COLORS[i % CHART_COLORS.length] }} />
                      {fh.name}
                    </div>
                  ))}
                </div>
              </div>

              {/* Fund House Detail Cards */}
              <div className="space-y-2" data-testid="fund-house-details">
                {fundHouse.map((fh, i) => (
                  <div
                    key={fh.name}
                    className={`rounded-xl border transition-all ${
                      fh.risk_level === "high"
                        ? "border-red-500/20 bg-red-500/10"
                        : fh.risk_level === "medium"
                        ? "border-amber-500/20 bg-amber-500/10"
                        : "border-slate-200 bg-slate-100 dark:bg-[#1A1A1A]"
                    }`}
                  >
                    <div
                      className="flex items-center justify-between p-4 cursor-pointer"
                      onClick={() => setExpandedFH(expandedFH === i ? null : i)}
                    >
                      <div className="flex items-center gap-3">
                        <div className="w-8 h-8 rounded-lg flex items-center justify-center text-xs font-bold text-slate-900 dark:text-white" style={{ backgroundColor: CHART_COLORS[i % CHART_COLORS.length] }}>
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
                      <div className="px-4 pb-4 border-t border-slate-200 dark:border-white/5 pt-3">
                        <p className="text-[10px] font-bold tracking-wider uppercase text-slate-400 mb-2">Funds under {fh.name}</p>
                        <div className="space-y-1">
                          {fh.funds.map((f, fi) => (
                            <p key={fi} className="text-xs text-slate-600 dark:text-zinc-400 flex items-center gap-2">
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

      {/* AI-Powered True Sector & Company Allocation */}
      <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.1 }}>
        <Card className="bg-white dark:bg-[#121212] border-slate-100 dark:border-white/5 rounded-2xl">
          <CardContent className="p-6 md:p-8">
            <div className="flex items-center justify-between mb-5">
              <div className="flex items-center gap-3">
                <div className="w-10 h-10 rounded-xl bg-blue-50 dark:bg-blue-900/20 flex items-center justify-center">
                  <BarChart3 className="w-5 h-5 text-blue-600" strokeWidth={1.5} />
                </div>
                <div>
                  <h3 className="text-lg font-medium text-slate-900 dark:text-white">True Sector & Company Allocation</h3>
                  <p className="text-xs text-slate-500 dark:text-zinc-500">AI look-through across MFs + direct equity</p>
                </div>
              </div>
              <Button variant="outline" size="sm" onClick={fetchAllocation} disabled={loadingAllocation} className="rounded-xl text-xs h-8">
                <RefreshCw className={`w-3 h-3 mr-1 ${loadingAllocation ? "animate-spin" : ""}`} /> {loadingAllocation ? "Analyzing..." : "Refresh"}
              </Button>
            </div>

            {loadingAllocation && !allocation ? (
              <div className="space-y-4 py-4 animate-pulse">
                <div className="h-10 bg-slate-100 dark:bg-zinc-800/50 rounded-xl" />
                <div className="space-y-2">
                  {[1,2,3,4,5].map(i => <div key={`skel-alloc-${i}`} className="h-8 bg-slate-100 dark:bg-zinc-800/50 rounded" />)}
                </div>
              </div>
            ) : allocation ? (
              <AllocationAnalysisDisplay allocation={allocation} fmt={fmt} />
            ) : (
              <div className="text-center py-8">
                <BarChart3 className="w-10 h-10 text-slate-300 mx-auto mb-3" />
                <p className="text-sm text-slate-500 dark:text-zinc-500">Click Refresh to run AI allocation analysis.</p>
              </div>
            )}
          </CardContent>
        </Card>
      </motion.div>
    </div>
  );
};

// ════════════════════════════════════════
// FUND OVERLAP TAB
// ════════════════════════════════════════
const OverlapTab = ({ overlaps, duplication, fmt }) => {
  const dup = duplication || {};
  const score = dup.score || 0;
  const level = dup.level || "low";
  const insights = dup.insights || [];
  const categoryDetail = dup.category_detail || [];
  const sectorOverlaps = dup.sector_overlaps || [];
  const [expandedCat, setExpandedCat] = useState(null);

  if (!overlaps.length && !categoryDetail.length) {
    return (
      <Card className="bg-white dark:bg-[#121212] border-slate-100 dark:border-slate-200 dark:border-white/5 rounded-2xl">
        <CardContent className="p-12 text-center">
          <Layers className="w-12 h-12 text-slate-300 mx-auto mb-4" />
          <h3 className="text-lg font-medium text-slate-900 dark:text-white mb-2" style={{ fontFamily: "'Outfit', sans-serif" }}>
            No fund overlap detected
          </h3>
          <p className="text-sm text-slate-500">Add 2 or more mutual funds to see overlap analysis.</p>
        </CardContent>
      </Card>
    );
  }

  const scoreColor = level === "high" ? "text-red-500" : level === "moderate" ? "text-amber-500" : "text-emerald-600";
  const scoreBg = level === "high" ? "bg-red-50 dark:bg-red-500/10 border-red-200 dark:border-red-500/20" : level === "moderate" ? "bg-amber-50 dark:bg-amber-500/10 border-amber-200 dark:border-amber-500/20" : "bg-emerald-50 dark:bg-emerald-900/15 border-emerald-500/20";

  return (
    <div className="space-y-6">
      {/* ── Screen 1: Duplication Score + AI Insights ── */}
      <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }}>
        <Card className={`rounded-2xl border ${scoreBg}`}>
          <CardContent className="p-6 md:p-8">
            <div className="flex flex-col md:flex-row items-center gap-6">
              {/* Score Circle */}
              <div className="flex-shrink-0 text-center">
                <div className="relative w-28 h-28 mx-auto">
                  <svg viewBox="0 0 100 100" className="w-full h-full -rotate-90">
                    <circle cx="50" cy="50" r="42" fill="none" stroke="#E2E8F0" strokeWidth="8" className="dark:stroke-slate-700" />
                    <circle cx="50" cy="50" r="42" fill="none" strokeWidth="8" strokeDasharray={`${score * 2.64} 264`} strokeLinecap="round"
                      stroke={level === "high" ? "#EF4444" : level === "moderate" ? "#F59E0B" : "#10B981"} />
                  </svg>
                  <div className="absolute inset-0 flex flex-col items-center justify-center">
                    <span className={`text-2xl font-bold ${scoreColor}`} style={{ fontFamily: "'JetBrains Mono', monospace" }}>{score}%</span>
                    <span className="text-[9px] text-slate-400 font-medium">Overlap</span>
                  </div>
                </div>
                <p className={`text-sm font-semibold mt-2 ${scoreColor}`}>
                  {level === "high" ? "High Duplication" : level === "moderate" ? "Moderate Overlap" : "Well Diversified"}
                </p>
              </div>

              {/* Main Message */}
              <div className="flex-1 text-center md:text-left">
                <h3 className="text-xl font-medium text-slate-900 dark:text-white" style={{ fontFamily: "'Outfit', sans-serif" }}>
                  {score > 25
                    ? `Your MF portfolio has ${score}% duplication`
                    : `Your portfolio is ${score < 10 ? "well" : "fairly"} diversified`}
                </h3>
                <p className="text-sm text-slate-500 dark:text-zinc-500 mt-1">
                  {fmt(dup.overlapping_value || 0)} of {fmt(dup.mf_total || 0)} is invested in overlapping categories
                </p>
              </div>
            </div>
          </CardContent>
        </Card>
      </motion.div>

      {/* ── AI Insights with Action Buttons ── */}
      {insights.length > 0 && (
        <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.05 }}>
          <Card className="bg-white dark:bg-[#121212] border-slate-100 dark:border-slate-200 dark:border-white/5 rounded-2xl">
            <CardContent className="p-6 md:p-8">
              <div className="flex items-center gap-3 mb-5">
                <div className="w-10 h-10 rounded-xl bg-violet-50 dark:bg-violet-900/20 flex items-center justify-center">
                  <Sparkles className="w-5 h-5 text-violet-600" strokeWidth={1.5} />
                </div>
                <h3 className="text-lg font-medium text-slate-900 dark:text-white" style={{ fontFamily: "'Outfit', sans-serif" }}>
                  Overlap Insights
                </h3>
              </div>
              <div className="space-y-3">
                {insights.map((ins, i) => (
                  <div
                    key={`ins-${i}`}
                    className={`rounded-xl p-4 border ${
                      ins.type === "warning" ? "bg-amber-50 dark:bg-amber-500/10 border-amber-200 dark:border-amber-500/20" :
                      ins.type === "alert" ? "bg-red-50 dark:bg-red-500/10 border-red-200 dark:border-red-500/20" :
                      ins.type === "success" ? "bg-emerald-50 dark:bg-emerald-500/10 border-emerald-200 dark:border-emerald-500/20" :
                      "bg-slate-100 dark:bg-[#1A1A1A]"
                    }`}
                  >
                    <div className="flex items-start gap-3">
                      <div className="flex-shrink-0 mt-0.5">
                        {ins.type === "warning" && <AlertTriangle className="w-4 h-4 text-amber-500" />}
                        {ins.type === "alert" && <Shield className="w-4 h-4 text-red-500" />}
                        {ins.type === "success" && <TrendingUp className="w-4 h-4 text-emerald-500" />}
                        {ins.type === "info" && <Lightbulb className="w-4 h-4 text-blue-500" />}
                      </div>
                      <div className="flex-1">
                        <p className="text-sm font-medium text-slate-900 dark:text-white">{ins.text}</p>
                        <p className="text-xs text-slate-500 dark:text-zinc-500 mt-1">{ins.detail}</p>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>
        </motion.div>
      )}

      {/* ── Screen 2: Category View — Stacked Bars (₹ overlap vs unique) ── */}
      {categoryDetail.length > 0 && (
        <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.1 }}>
          <Card className="bg-white dark:bg-[#121212] border-slate-100 dark:border-slate-200 dark:border-white/5 rounded-2xl">
            <CardContent className="p-6 md:p-8">
              <div className="flex items-center gap-3 mb-5">
                <div className="w-10 h-10 rounded-xl bg-amber-50 dark:bg-amber-900/20 flex items-center justify-center">
                  <Layers className="w-5 h-5 text-amber-600" strokeWidth={1.5} />
                </div>
                <div>
                  <h3 className="text-lg font-medium text-slate-900 dark:text-white" style={{ fontFamily: "'Outfit', sans-serif" }}>
                    Category-Level Overlap
                  </h3>
                  <p className="text-xs text-slate-500 dark:text-zinc-500">
                    Amount invested per category — unique vs overlapping allocation
                  </p>
                </div>
              </div>

              <div className="space-y-3">
                {categoryDetail.filter(c => c.total_value > 0).map((cat, i) => {
                  const maxVal = categoryDetail[0]?.total_value || 1;
                  const barWidth = Math.max((cat.total_value / maxVal) * 100, 8);
                  const uniquePct = cat.total_value > 0 ? (cat.unique_value / cat.total_value * 100) : 100;
                  const isExpanded = expandedCat === i;

                  return (
                    <div key={`cat-bar-${cat.category}`} className="group">
                      <div
                        className="flex items-center gap-3 cursor-pointer py-1.5 hover:bg-slate-100 dark:bg-[#1A1A1A] -mx-2 px-2 rounded-lg transition-colors"
                        onClick={() => setExpandedCat(isExpanded ? null : i)}
                      >
                        <span className="text-xs text-slate-600 dark:text-zinc-400 w-24 flex-shrink-0 truncate">{cat.category}</span>
                        <div className="flex-1 h-7 rounded-lg overflow-hidden flex bg-slate-50 dark:bg-zinc-800/50" style={{ width: `${barWidth}%` }}>
                          <div
                            className="h-full flex items-center justify-center transition-all"
                            style={{ width: `${uniquePct}%`, backgroundColor: "#10B981" }}
                          >
                            {uniquePct > 20 && <span className="text-[9px] font-bold text-slate-900 dark:text-white">{fmt(cat.unique_value)}</span>}
                          </div>
                          {cat.overlap_value > 0 && (
                            <div
                              className="h-full flex items-center justify-center transition-all"
                              style={{ width: `${100 - uniquePct}%`, backgroundColor: "#F59E0B" }}
                            >
                              {(100 - uniquePct) > 20 && <span className="text-[9px] font-bold text-slate-900 dark:text-white">{fmt(cat.overlap_value)}</span>}
                            </div>
                          )}
                        </div>
                        <span className="text-xs font-bold text-slate-700 dark:text-zinc-300 w-8 text-right" style={{ fontFamily: "'JetBrains Mono', monospace" }}>
                          {cat.fund_count}
                        </span>
                        {cat.is_overlapping ? <ChevronDown className="w-3.5 h-3.5 text-slate-400" /> : <div className="w-3.5" />}
                      </div>

                      {/* Expanded fund list */}
                      <AnimatePresence>
                        {isExpanded && cat.funds.length > 0 && (
                          <motion.div initial={{ height: 0, opacity: 0 }} animate={{ height: "auto", opacity: 1 }} exit={{ height: 0, opacity: 0 }} className="overflow-hidden">
                            <div className="ml-28 pl-3 border-l-2 border-slate-200 dark:border-zinc-800 py-2 space-y-1">
                              {cat.funds.map((f, fi) => (
                                <p key={fi} className="text-[11px] text-slate-500 dark:text-zinc-500">{f}</p>
                              ))}
                            </div>
                          </motion.div>
                        )}
                      </AnimatePresence>
                    </div>
                  );
                })}
              </div>

              <div className="flex items-center gap-4 mt-4 text-[10px] font-bold tracking-wider uppercase">
                <div className="flex items-center gap-1"><div className="w-3 h-3 rounded bg-emerald-500" />Unique allocation</div>
                <div className="flex items-center gap-1"><div className="w-3 h-3 rounded bg-amber-500" />Overlapping</div>
                <span className="text-slate-400 ml-auto font-normal normal-case">Count = funds per category</span>
              </div>
            </CardContent>
          </Card>
        </motion.div>
      )}

      {/* ── Screen 3: Sector Exposure ── */}
      {sectorOverlaps.length > 0 && (
        <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.15 }}>
          <Card className="bg-white dark:bg-[#121212] border-slate-100 dark:border-slate-200 dark:border-white/5 rounded-2xl">
            <CardContent className="p-6 md:p-8">
              <div className="flex items-center gap-3 mb-5">
                <div className="w-10 h-10 rounded-xl bg-indigo-50 dark:bg-indigo-900/20 flex items-center justify-center">
                  <BarChart3 className="w-5 h-5 text-indigo-600" strokeWidth={1.5} />
                </div>
                <div>
                  <h3 className="text-lg font-medium text-slate-900 dark:text-white" style={{ fontFamily: "'Outfit', sans-serif" }}>
                    Sector Exposure Across Funds
                  </h3>
                  <p className="text-xs text-slate-500 dark:text-zinc-500">
                    Categories where multiple funds concentrate — indicates hidden overlap
                  </p>
                </div>
              </div>

              <div className="space-y-2">
                {sectorOverlaps.filter(s => s.fund_count >= 2).map((sec, i) => (
                  <div key={`sec-${sec.sector}`} className="flex items-center gap-3">
                    <span className="text-xs text-slate-500 w-28 flex-shrink-0 truncate">{sec.sector}</span>
                    <div className="flex-1 h-5 bg-slate-50 dark:bg-zinc-800/50 rounded-full overflow-hidden">
                      <div
                        className="h-full rounded-full transition-all"
                        style={{
                          width: `${Math.min(sec.pct * 2, 100)}%`,
                          backgroundColor: sec.risk_level === "high" ? "#EF4444" : sec.risk_level === "moderate" ? "#F59E0B" : "#3B82F6",
                        }}
                      />
                    </div>
                    <span className={`text-xs font-bold w-12 text-right ${sec.risk_level === "high" ? "text-red-500" : sec.risk_level === "moderate" ? "text-amber-500" : "text-blue-500"}`} style={{ fontFamily: "'JetBrains Mono', monospace" }}>
                      {sec.pct}%
                    </span>
                    <span className="text-[10px] text-slate-400 w-16 text-right">{sec.fund_count} funds</span>
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>
        </motion.div>
      )}

      {/* ── Fund Overlap Heatmap (existing, cleaned up) ── */}
      {overlaps.length > 0 && (
        <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.2 }}>
          <Card className="bg-white dark:bg-[#121212] border-slate-100 dark:border-slate-200 dark:border-white/5 rounded-2xl">
            <CardContent className="p-6 md:p-8">
              <div className="flex items-center gap-3 mb-6">
                <div className="w-10 h-10 rounded-xl bg-indigo-50 dark:bg-indigo-900/20 flex items-center justify-center">
                  <Layers className="w-5 h-5 text-indigo-600" strokeWidth={1.5} />
                </div>
                <div>
                  <h3 className="text-lg font-medium text-slate-900 dark:text-white" style={{ fontFamily: "'Outfit', sans-serif" }}>
                    Fund-to-Fund Overlap
                  </h3>
                  <p className="text-xs text-slate-500 dark:text-zinc-500">
                    Pairwise similarity between your mutual funds
                  </p>
                </div>
              </div>
              <div className="space-y-2" data-testid="overlap-matrix">
                {overlaps.slice(0, 10).map((o, i) => {
                  const isHigh = o.overlap_pct >= 60;
                  const isMed = o.overlap_pct >= 30;
                  return (
                    <div
                      key={`overlap-${i}`}
                      className={`rounded-xl p-4 border flex items-center gap-4 ${
                        isHigh ? "border-red-500/20 bg-red-500/10"
                        : isMed ? "border-amber-500/20 bg-amber-500/10"
                        : "border-slate-200 dark:border-white/5 bg-slate-100 dark:bg-[#1A1A1A]"
                      }`}
                    >
                      <div className="flex-1 min-w-0">
                        <p className="text-xs font-medium text-slate-900 dark:text-white truncate">{o.fund_a}</p>
                        <p className="text-[10px] text-slate-400 my-0.5">overlaps with</p>
                        <p className="text-xs font-medium text-slate-900 dark:text-white truncate">{o.fund_b}</p>
                        {o.reasons?.length > 0 && (
                          <div className="flex flex-wrap gap-1 mt-2">
                            {o.reasons.map((r, ri) => (
                              <span key={ri} className="text-[9px] px-1.5 py-0.5 rounded-full bg-slate-50 dark:bg-zinc-800/50 text-slate-500">{r}</span>
                            ))}
                          </div>
                        )}
                      </div>
                      <div className={`text-xl font-bold flex-shrink-0 ${isHigh ? "text-red-500" : isMed ? "text-amber-500" : "text-emerald-600"}`} style={{ fontFamily: "'JetBrains Mono', monospace" }}>
                        {o.overlap_pct}%
                      </div>
                    </div>
                  );
                })}
              </div>
            </CardContent>
          </Card>
        </motion.div>
      )}
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
      <Card className="bg-white dark:bg-[#121212] border-slate-100 dark:border-slate-200 dark:border-white/5 rounded-2xl">
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
        <Card className="bg-white dark:bg-[#121212] border-slate-100 dark:border-slate-200 dark:border-white/5 rounded-2xl">
          <CardContent className="p-4">
            <p className="text-[10px] font-bold tracking-wider uppercase text-slate-400">Total Invested</p>
            <p className="text-lg font-semibold text-slate-900 dark:text-white mt-1" style={{ fontFamily: "'Outfit', sans-serif" }} data-testid="perf-total-invested">{fmt(totalInvested)}</p>
          </CardContent>
        </Card>
        <Card className="bg-white dark:bg-[#121212] border-slate-100 dark:border-slate-200 dark:border-white/5 rounded-2xl">
          <CardContent className="p-4">
            <p className="text-[10px] font-bold tracking-wider uppercase text-slate-400">Current Value</p>
            <p className="text-lg font-semibold text-slate-900 dark:text-white mt-1" style={{ fontFamily: "'Outfit', sans-serif" }} data-testid="perf-total-current">{fmt(totalCurrent)}</p>
          </CardContent>
        </Card>
        <Card className={`border rounded-2xl ${totalReturn >= 0 ? "bg-emerald-50 dark:bg-emerald-500/10 border-emerald-200 dark:border-emerald-500/20" : "bg-red-50 dark:bg-red-500/10 border-red-200 dark:border-red-500/20"}`}>
          <CardContent className="p-4">
            <p className="text-[10px] font-bold tracking-wider uppercase text-slate-400">Total P&L</p>
            <p className={`text-lg font-semibold mt-1 ${totalReturn >= 0 ? "text-emerald-600" : "text-red-500"}`} style={{ fontFamily: "'Outfit', sans-serif" }} data-testid="perf-total-return">
              {totalReturn >= 0 ? "+" : ""}{fmt(Math.abs(totalReturn))}
            </p>
          </CardContent>
        </Card>
        <Card className={`border rounded-2xl ${totalReturnPct >= 0 ? "bg-emerald-50 dark:bg-emerald-500/10 border-emerald-200 dark:border-emerald-500/20" : "bg-red-50 dark:bg-red-500/10 border-red-200 dark:border-red-500/20"}`}>
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
                ? "bg-emerald-600 text-slate-900 dark:text-white"
                : "bg-slate-50 dark:bg-zinc-800/50 text-slate-600 dark:text-zinc-400 hover:bg-slate-200 dark:hover:bg-slate-600"
            }`}
            data-testid={`filter-${at}`}
          >
            {at === "all" ? "All" : ASSET_LABELS[at] || at}
          </button>
        ))}
      </div>

      {/* Performance Cards Table */}
      <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }}>
        <Card className="bg-white dark:bg-[#121212] border-slate-100 dark:border-slate-200 dark:border-white/5 rounded-2xl overflow-hidden">
          <CardContent className="p-0">
            <div className="overflow-x-auto">
              <table className="w-full" data-testid="performance-table">
                <thead>
                  <tr className="border-b border-slate-200 dark:border-white/5">
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
                        className="border-b border-slate-50 dark:border-slate-200 dark:border-zinc-800 hover:bg-slate-50 dark:bg-zinc-800/50 transition-colors"
                        data-testid={`perf-row-${i}`}
                      >
                        <td className="p-4">
                          <div className="flex items-center gap-3">
                            {/* Mini return indicator bar */}
                            <div className="w-1 h-10 rounded-full flex-shrink-0" style={{ backgroundColor: isPos ? "#10B981" : "#EF4444", opacity: Math.min(0.3 + Math.abs(c.pct_return) / 100, 1) }} />
                            <div>
                              <p className="text-sm font-medium text-slate-900 dark:text-white max-w-[250px] truncate">{c.name}</p>
                              <div className="flex items-center gap-2 mt-0.5">
                                <span className="text-[10px] px-1.5 py-0.5 rounded bg-slate-50 dark:bg-zinc-800/50 text-slate-500 dark:text-zinc-500 font-medium">
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
                          <p className="text-sm text-slate-700 dark:text-zinc-300" style={{ fontFamily: "'JetBrains Mono', monospace" }}>{fmt(c.invested)}</p>
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
                            <div className="w-16 h-1.5 rounded-full bg-slate-50 dark:bg-zinc-800/50 overflow-hidden">
                              <div className="h-full rounded-full bg-indigo-500" style={{ width: `${Math.min(c.weight, 100)}%` }} />
                            </div>
                            <span className="text-xs text-slate-600 dark:text-zinc-400 w-10 text-right" style={{ fontFamily: "'JetBrains Mono', monospace" }}>{c.weight}%</span>
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
// FUND BENCHMARK DRILLDOWN - Grouped by AMC
// ════════════════════════════════════════
const FundBenchmarkDrilldown = ({ ratings, fmt }) => {
  const [expandedAmc, setExpandedAmc] = useState(null);

  // Group funds by AMC
  const amcGroups = useMemo(() => {
    const groups = {};
    const knownHouses = [
      "HDFC", "ICICI Prudential", "ICICI", "SBI", "Axis", "Kotak",
      "Aditya Birla Sun Life", "Aditya Birla", "Nippon India", "Nippon",
      "UTI", "DSP", "Mirae Asset", "Mirae", "Tata", "Canara Robeco",
      "Parag Parikh", "PPFAS", "Quant", "Bandhan", "Edelweiss",
      "Invesco", "Sundaram", "PGIM", "Groww", "Motilal Oswal",
    ];

    (ratings || []).forEach(r => {
      const name = r.name || "";
      let amc = "Other";
      for (const house of knownHouses) {
        if (name.toLowerCase().includes(house.toLowerCase())) {
          amc = house;
          break;
        }
      }
      if (!groups[amc]) groups[amc] = { funds: [], totalReturn: 0, count: 0 };
      groups[amc].funds.push(r);
      if (r.return_1y !== null) {
        groups[amc].totalReturn += r.return_1y;
        groups[amc].count += 1;
      }
    });

    return Object.entries(groups)
      .map(([name, data]) => ({
        name,
        funds: data.funds,
        avgReturn: data.count > 0 ? (data.totalReturn / data.count) : null,
        outperforming: data.funds.filter(f => f.rating === "outperforming").length,
        underperforming: data.funds.filter(f => f.rating === "underperforming").length,
      }))
      .sort((a, b) => b.funds.length - a.funds.length);
  }, [ratings]);

  if (!amcGroups.length) return <p className="text-sm text-slate-400 text-center py-6">No fund data available</p>;

  return (
    <div className="space-y-2" data-testid="fund-benchmark-drilldown">
      {amcGroups.map((amc) => {
        const isExpanded = expandedAmc === amc.name;
        return (
          <div key={amc.name} className="rounded-xl border border-slate-200 dark:border-zinc-800 overflow-hidden">
            <button
              onClick={() => setExpandedAmc(isExpanded ? null : amc.name)}
              className="w-full flex items-center justify-between p-4 hover:bg-slate-50 dark:hover:bg-zinc-800/30 transition-colors"
              data-testid={`amc-group-${amc.name}`}
            >
              <div className="flex items-center gap-3">
                <div className="w-8 h-8 rounded-lg bg-slate-50 dark:bg-zinc-800/50 flex items-center justify-center text-sm font-bold text-slate-600 dark:text-zinc-400">
                  {amc.name.charAt(0)}
                </div>
                <div className="text-left">
                  <p className="text-sm font-medium text-slate-900 dark:text-white">{amc.name}</p>
                  <p className="text-[10px] text-slate-500">{amc.funds.length} fund{amc.funds.length > 1 ? "s" : ""}</p>
                </div>
              </div>
              <div className="flex items-center gap-3">
                {amc.outperforming > 0 && (
                  <span className="text-[9px] font-bold uppercase tracking-wider text-emerald-600 bg-emerald-50 dark:bg-emerald-900/30 px-1.5 py-0.5 rounded">
                    {amc.outperforming} outperforming
                  </span>
                )}
                {amc.underperforming > 0 && (
                  <span className="text-[9px] font-bold uppercase tracking-wider text-red-500 bg-red-50 dark:bg-red-900/30 px-1.5 py-0.5 rounded">
                    {amc.underperforming} underperforming
                  </span>
                )}
                {amc.avgReturn !== null && (
                  <span className={`text-xs font-bold ${amc.avgReturn >= 0 ? "text-emerald-600" : "text-red-500"}`} style={{ fontFamily: "'JetBrains Mono', monospace" }}>
                    {amc.avgReturn >= 0 ? "+" : ""}{amc.avgReturn.toFixed(1)}%
                  </span>
                )}
                <ChevronDown className={`w-4 h-4 text-slate-400 transition-transform duration-200 ${isExpanded ? "rotate-180" : ""}`} />
              </div>
            </button>
            <AnimatePresence>
              {isExpanded && (
                <motion.div
                  initial={{ height: 0, opacity: 0 }}
                  animate={{ height: "auto", opacity: 1 }}
                  exit={{ height: 0, opacity: 0 }}
                  transition={{ duration: 0.2 }}
                  className="overflow-hidden"
                >
                  <div className="border-t border-slate-200 dark:border-white/5 p-4 space-y-3">
                    {amc.funds.map((r, i) => {
                      const cfg = RATING_CONFIG[r.rating] || RATING_CONFIG.no_data;
                      const RIcon = cfg.icon;
                      return (
                        <div key={i} className={`rounded-lg border ${cfg.border} ${cfg.bg} p-3`} data-testid={`fund-rating-${amc.name}-${i}`}>
                          <div className="flex items-start justify-between gap-3">
                            <div className="flex-1 min-w-0">
                              <div className="flex items-center gap-2 mb-0.5">
                                <RIcon className="w-3.5 h-3.5 flex-shrink-0" style={{ color: cfg.color }} />
                                <p className="text-xs font-medium text-slate-900 dark:text-white truncate">{r.name}</p>
                              </div>
                              <p className="text-[10px] text-slate-500">{r.sector} {r.scheme_category ? `| ${r.scheme_category}` : ""}</p>
                            </div>
                            <span className="text-[9px] font-bold uppercase tracking-wider px-1.5 py-0.5 rounded" style={{ backgroundColor: `${cfg.color}15`, color: cfg.color }}>
                              {cfg.label}
                            </span>
                          </div>
                          <div className="mt-2 grid grid-cols-3 gap-3">
                            <div>
                              <p className="text-[9px] text-slate-400">1Y Return</p>
                              <p className={`text-sm font-bold ${(r.return_1y || 0) >= 0 ? "text-emerald-600" : "text-red-500"}`} style={{ fontFamily: "'JetBrains Mono', monospace" }}>
                                {r.return_1y !== null ? `${r.return_1y >= 0 ? "+" : ""}${r.return_1y}%` : "—"}
                              </p>
                            </div>
                            <div>
                              <p className="text-[9px] text-slate-400">Benchmark</p>
                              <p className="text-sm font-medium text-slate-600 dark:text-zinc-400" style={{ fontFamily: "'JetBrains Mono', monospace" }}>
                                {r.benchmark_return !== null ? `${r.benchmark_return >= 0 ? "+" : ""}${r.benchmark_return}%` : "—"}
                              </p>
                            </div>
                            <div>
                              <p className="text-[9px] text-slate-400">Alpha</p>
                              <p className={`text-sm font-bold ${(r.alpha || 0) >= 0 ? "text-emerald-600" : "text-red-500"}`} style={{ fontFamily: "'JetBrains Mono', monospace" }}>
                                {r.alpha !== null ? `${r.alpha >= 0 ? "+" : ""}${r.alpha}%` : "—"}
                              </p>
                            </div>
                          </div>
                          {r.benchmark_name && (
                            <p className="text-[9px] text-slate-400 mt-1">Benchmark: {r.benchmark_name}</p>
                          )}
                        </div>
                      );
                    })}
                  </div>
                </motion.div>
              )}
            </AnimatePresence>
          </div>
        );
      })}
    </div>
  );
};

// ════════════════════════════════════════
// FUND HEATMAP — treemap visualization of fund performance
// ════════════════════════════════════════
const FundHeatmap = ({ ratings, fmt }) => {
  const [selectedFund, setSelectedFund] = useState(null);

  const heatmapData = useMemo(() => {
    if (!ratings?.length) return [];
    return ratings
      .filter(r => r.invested > 0)
      .map(r => {
        const pnl = (r.current_value || 0) - (r.invested || 0);
        const pnlPct = r.invested > 0 ? (pnl / r.invested * 100) : 0;
        return {
          name: r.name.length > 22 ? r.name.slice(0, 22) + ".." : r.name,
          fullName: r.name,
          size: Math.max(r.invested, 1000),
          pnl,
          pnlPct,
          invested: r.invested,
          current_value: r.current_value,
          sector: r.sector,
        };
      })
      .sort((a, b) => b.size - a.size);
  }, [ratings]);

  const getColor = (pnlPct) => {
    if (pnlPct > 30) return "#047857";
    if (pnlPct > 15) return "#059669";
    if (pnlPct > 5) return "#10B981";
    if (pnlPct > 0) return "#6EE7B7";
    if (pnlPct > -10) return "#FCA5A5";
    return "#EF4444";
  };

  if (!heatmapData.length) return <p className="text-sm text-slate-400 text-center py-6">No fund data</p>;

  const maxSize = heatmapData[0]?.size || 1;

  return (
    <div data-testid="fund-heatmap">
      <div className="grid gap-1" style={{ gridTemplateColumns: `repeat(auto-fill, minmax(140px, 1fr))` }}>
        {heatmapData.map((fund, i) => {
          const isSelected = selectedFund === i;
          const bgColor = getColor(fund.pnlPct);
          const sizeRatio = fund.size / maxSize;
          return (
            <div
              key={`heatmap-${i}`}
              data-testid={`heatmap-cell-${i}`}
              onClick={() => setSelectedFund(isSelected ? null : i)}
              className={`cursor-pointer rounded-lg p-3 transition-all hover:ring-2 hover:ring-white/30 ${isSelected ? "ring-2 ring-slate-900 dark:ring-white" : ""}`}
              style={{
                backgroundColor: bgColor,
                minHeight: Math.max(72, Math.min(100, sizeRatio * 100)),
                opacity: selectedFund !== null && !isSelected ? 0.45 : 1,
              }}
            >
              <p className="text-[10px] font-medium text-slate-900 dark:text-white/90 leading-tight truncate">{fund.name}</p>
              <p className="text-lg font-bold text-slate-900 dark:text-white mt-1.5" style={{ fontFamily: "'JetBrains Mono', monospace" }}>
                {fund.pnlPct >= 0 ? "+" : ""}{fund.pnlPct.toFixed(1)}%
              </p>
              <div className="flex items-center justify-between mt-1.5">
                <span className="text-[9px] text-slate-900 dark:text-white/60">{fmt(fund.invested)}</span>
                <span className="text-[9px] text-slate-900 dark:text-white/80 font-medium">{fund.pnl >= 0 ? "+" : ""}{fmt(fund.pnl)}</span>
              </div>
            </div>
          );
        })}
      </div>

      {/* Selected fund detail */}
      <AnimatePresence>
        {selectedFund !== null && heatmapData[selectedFund] && (
          <motion.div initial={{ height: 0, opacity: 0 }} animate={{ height: "auto", opacity: 1 }} exit={{ height: 0, opacity: 0 }} className="overflow-hidden">
            <div className="mt-4 p-5 bg-slate-100 dark:bg-[#1A1A1A] rounded-xl border border-slate-200 dark:border-zinc-700">
              <div className="flex justify-between items-start mb-4">
                <div>
                  <p className="text-sm font-medium text-slate-900 dark:text-white">{heatmapData[selectedFund].fullName}</p>
                  <p className="text-[10px] text-slate-500 mt-0.5">{heatmapData[selectedFund].sector}</p>
                </div>
                <button onClick={() => setSelectedFund(null)} className="text-xs text-slate-400 hover:text-slate-600 bg-slate-200 dark:bg-slate-600 px-2 py-1 rounded-lg">Close</button>
              </div>
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 sm:gap-4">
                <div>
                  <p className="text-[9px] font-bold uppercase tracking-wider text-slate-400">P&L</p>
                  <p className={`text-base font-bold mt-1 ${heatmapData[selectedFund].pnlPct >= 0 ? "text-emerald-600" : "text-red-500"}`} style={{ fontFamily: "'JetBrains Mono', monospace" }}>
                    {heatmapData[selectedFund].pnlPct >= 0 ? "+" : ""}{heatmapData[selectedFund].pnlPct.toFixed(1)}%
                  </p>
                </div>
                <div>
                  <p className="text-[9px] font-bold uppercase tracking-wider text-slate-400">Invested</p>
                  <p className="text-base font-medium text-slate-700 dark:text-zinc-300 mt-1">{fmt(heatmapData[selectedFund].invested)}</p>
                </div>
                <div>
                  <p className="text-[9px] font-bold uppercase tracking-wider text-slate-400">Current</p>
                  <p className="text-base font-medium text-slate-700 dark:text-zinc-300 mt-1">{fmt(heatmapData[selectedFund].current_value)}</p>
                </div>
                <div>
                  <p className="text-[9px] font-bold uppercase tracking-wider text-slate-400">Gain/Loss</p>
                  <p className={`text-base font-bold mt-1 ${heatmapData[selectedFund].pnl >= 0 ? "text-emerald-600" : "text-red-500"}`} style={{ fontFamily: "'JetBrains Mono', monospace" }}>
                    {heatmapData[selectedFund].pnl >= 0 ? "+" : ""}{fmt(heatmapData[selectedFund].pnl)}
                  </p>
                </div>
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      <div className="flex items-center gap-3 mt-3 text-[10px] text-slate-400">
        <span className="font-medium">Color = Portfolio P&L:</span>
        <div className="flex items-center gap-1"><div className="w-3 h-3 rounded" style={{backgroundColor:"#047857"}} /> &gt;30%</div>
        <div className="flex items-center gap-1"><div className="w-3 h-3 rounded" style={{backgroundColor:"#10B981"}} /> 5-30%</div>
        <div className="flex items-center gap-1"><div className="w-3 h-3 rounded" style={{backgroundColor:"#6EE7B7"}} /> 0-5%</div>
        <div className="flex items-center gap-1"><div className="w-3 h-3 rounded" style={{backgroundColor:"#FCA5A5"}} /> -10 to 0%</div>
        <div className="flex items-center gap-1"><div className="w-3 h-3 rounded" style={{backgroundColor:"#EF4444"}} /> &lt;-10%</div>
      </div>
    </div>
  );
};

// ════════════════════════════════════════
// BENCHMARK TAB - MF Benchmark Ratings, Performance Pie, Category Overlap Bar
// ════════════════════════════════════════
const RATING_CONFIG = {
  overperforming: { label: "Outperforming", color: "#10B981", bg: "bg-emerald-50 dark:bg-emerald-900/15", border: "border-emerald-500/20", icon: TrendingUp },
  meeting: { label: "Meeting Benchmark", color: "#3B82F6", bg: "bg-blue-50 dark:bg-blue-900/15", border: "border-blue-200 dark:border-blue-800", icon: ArrowRight },
  underperforming: { label: "Underperforming", color: "#EF4444", bg: "bg-red-50 dark:bg-red-900/15", border: "border-red-200 dark:border-red-800", icon: TrendingDown },
  no_data: { label: "No Benchmark Data", color: "#94A3B8", bg: "bg-slate-50 dark:bg-zinc-800/50", border: "border-slate-200 dark:border-zinc-800", icon: BarChart3 },
};

const BenchmarkTab = ({ data, loading, onLoad, fmt }) => {
  const [drilldownRating, setDrilldownRating] = useState(null);
  const [showAllTop, setShowAllTop] = useState(false);
  const [showAllBottom, setShowAllBottom] = useState(false);

  useEffect(() => {
    if (!data && !loading) onLoad();
  }, []);

  if (loading) {
    return (
      <Card className="bg-white dark:bg-[#121212] border-slate-100 dark:border-slate-200 dark:border-white/5 rounded-2xl">
        <CardContent className="p-12 text-center">
          <div className="relative w-16 h-16 mx-auto mb-4">
            <div className="w-16 h-16 border-3 border-emerald-100 dark:border-emerald-900/30 rounded-full" />
            <div className="absolute inset-0 w-16 h-16 border-3 border-emerald-600 border-t-transparent rounded-full animate-spin" />
          </div>
          <h3 className="text-lg font-medium text-slate-900 dark:text-white mb-2" style={{ fontFamily: "'Outfit', sans-serif" }}>
            Fetching Benchmark Data...
          </h3>
          <p className="text-sm text-slate-500 dark:text-zinc-500 mb-4">Fetching 1-year historical NAVs from AMFI for each mutual fund.</p>
          <div className="max-w-xs mx-auto">
            <div className="w-full h-2 rounded-full bg-slate-50 dark:bg-zinc-800/50 overflow-hidden">
              <div className="h-full rounded-full bg-emerald-500 animate-pulse" style={{ width: "60%", transition: "width 2s ease" }} />
            </div>
            <p className="text-[10px] text-slate-400 mt-2">Processing up to 30 funds — typically takes 10-20 seconds</p>
          </div>
        </CardContent>
      </Card>
    );
  }

  if (!data || !data.fund_ratings?.length) {
    return (
      <Card className="bg-white dark:bg-[#121212] border-slate-100 dark:border-slate-200 dark:border-white/5 rounded-2xl">
        <CardContent className="p-12 text-center">
          <BarChart3 className="w-12 h-12 text-slate-300 mx-auto mb-4" />
          <h3 className="text-lg font-medium text-slate-900 dark:text-white mb-2" style={{ fontFamily: "'Outfit', sans-serif" }}>
            No mutual fund data
          </h3>
          <p className="text-sm text-slate-500 mb-4">Add mutual fund holdings to see benchmark analysis.</p>
          <Button onClick={onLoad} className="bg-emerald-600 hover:bg-emerald-700 text-slate-900 dark:text-white rounded-xl" data-testid="load-benchmark-btn">
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
    { name: "Outperforming", value: dist.overperforming || 0, color: "#10B981", ratingKey: "overperforming" },
    { name: "Meeting Benchmark", value: dist.meeting || 0, color: "#3B82F6", ratingKey: "meeting" },
    { name: "Underperforming", value: dist.underperforming || 0, color: "#EF4444", ratingKey: "underperforming" },
    { name: "No Data", value: dist.no_data || 0, color: "#CBD5E1", ratingKey: "no_data" },
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
          <Card className="bg-white dark:bg-[#121212] border-slate-100 dark:border-slate-200 dark:border-white/5 rounded-2xl h-full">
            <CardContent className="p-6">
              <div className="flex items-center justify-between mb-4">
                <h3 className="text-sm font-medium text-slate-900 dark:text-white" style={{ fontFamily: "'Outfit', sans-serif" }}>
                  MF Performance vs Benchmark
                </h3>
                <Button variant="ghost" size="sm" onClick={onLoad} className="h-7 text-xs text-slate-500" data-testid="refresh-benchmark">
                  <RefreshCw className="w-3 h-3 mr-1" /> Refresh
                </Button>
              </div>
              <div className="flex flex-col sm:flex-row items-center gap-4 sm:gap-6">
                <div className="w-40 h-40 flex-shrink-0" data-testid="benchmark-pie">
                  <ResponsiveContainer width="100%" height="100%">
                    <PieChart>
                      <Pie data={pieData} cx="50%" cy="50%" innerRadius={38} outerRadius={62} paddingAngle={2} dataKey="value"
                        onClick={(entry) => {
                          if (entry?.ratingKey) setDrilldownRating(entry.ratingKey);
                        }}
                        style={{ cursor: "pointer" }}
                      >
                        {pieData.map((d, i) => <Cell key={i} fill={d.color} className="cursor-pointer hover:opacity-80 transition-opacity" />)}
                      </Pie>
                      <Tooltip formatter={(v, name) => [`${v} funds — click to view`, name]} />
                    </PieChart>
                  </ResponsiveContainer>
                </div>
                <div className="flex-1 w-full space-y-2.5">
                  {pieData.map(d => (
                    <div key={d.name} className="flex items-center justify-between cursor-pointer hover:bg-slate-100 dark:bg-[#1A1A1A] rounded-lg px-2 py-1 -mx-2 transition-colors"
                      onClick={() => setDrilldownRating(d.ratingKey)}
                    >
                      <div className="flex items-center gap-2">
                        <div className="w-3 h-3 rounded-full" style={{ backgroundColor: d.color }} />
                        <span className="text-xs text-slate-600 dark:text-zinc-400">{d.name}</span>
                      </div>
                      <span className="text-sm font-bold text-slate-900 dark:text-white" style={{ fontFamily: "'JetBrains Mono', monospace" }}>{d.value}</span>
                    </div>
                  ))}
                  <div className="pt-2 border-t border-slate-200 dark:border-white/5">
                    <p className="text-[10px] text-slate-400">
                      {summary.matched || 0} of {summary.total_mf || 0} funds matched with AMFI data
                    </p>
                    <p className="text-[9px] text-slate-400 mt-0.5">Click a segment or label to see funds in that category</p>
                  </div>
                </div>
              </div>

              {/* Drilldown: show funds for clicked rating */}
              {drilldownRating && (() => {
                const ratingMap = { overperforming: "overperforming", meeting: "meeting", underperforming: "underperforming", no_data: "no_data" };
                const ratingLabel = { overperforming: "Outperforming", meeting: "Meeting Benchmark", underperforming: "Underperforming", no_data: "No Data" };
                const drillFunds = ratings.filter(r => r.rating === ratingMap[drilldownRating]);
                return (
                  <div className="mt-4 border-t border-slate-200 dark:border-white/5 pt-4">
                    <div className="flex items-center justify-between mb-3">
                      <p className="text-xs font-medium text-slate-900 dark:text-white">
                        {ratingLabel[drilldownRating]} Funds ({drillFunds.length})
                      </p>
                      <button onClick={() => setDrilldownRating(null)} className="text-[10px] text-slate-400 hover:text-slate-600">Close</button>
                    </div>
                    <div className="space-y-2 max-h-48 overflow-y-auto">
                      {drillFunds.length > 0 ? drillFunds.map((r, i) => (
                        <div key={i} className="flex items-center justify-between text-xs py-1.5 px-2 rounded-lg bg-slate-100 dark:bg-[#1A1A1A]">
                          <span className="text-slate-700 dark:text-zinc-300 truncate flex-1 mr-2">{r.name}</span>
                          <div className="flex items-center gap-3 flex-shrink-0">
                            <span className={`font-bold ${(r.return_1y || 0) >= 0 ? "text-emerald-600" : "text-red-500"}`}>
                              {r.return_1y !== null ? `${r.return_1y >= 0 ? "+" : ""}${r.return_1y}%` : "—"}
                            </span>
                            {r.benchmark_return !== null && (
                              <span className="text-slate-400">vs {r.benchmark_return >= 0 ? "+" : ""}{r.benchmark_return}%</span>
                            )}
                          </div>
                        </div>
                      )) : (
                        <p className="text-xs text-slate-400 text-center py-3">No funds in this category</p>
                      )}
                    </div>
                  </div>
                );
              })()}
            </CardContent>
          </Card>
        </motion.div>

        {/* Top & Bottom Performers */}
        <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.05 }}>
          <Card className="bg-white dark:bg-[#121212] border-slate-100 dark:border-slate-200 dark:border-white/5 rounded-2xl h-full">
            <CardContent className="p-6">
              <h3 className="text-sm font-medium text-slate-900 dark:text-white mb-4" style={{ fontFamily: "'Outfit', sans-serif" }}>
                Best & Worst Performers (1Y Return)
              </h3>
              <div className="space-y-1">
                {(showAllTop ? topPerf : topPerf.slice(0, 5)).map((p, i) => (
                  <div key={`top-${i}`} className="flex items-center justify-between py-1.5 px-2 rounded-lg hover:bg-emerald-50/50 dark:hover:bg-emerald-900/10 transition-colors">
                    <div className="flex items-center gap-2 flex-1 min-w-0">
                      <div className="w-5 h-5 rounded-full bg-emerald-100 dark:bg-emerald-900/30 flex items-center justify-center flex-shrink-0">
                        <TrendingUp className="w-3 h-3 text-emerald-600" />
                      </div>
                      <span className="text-xs text-slate-700 dark:text-zinc-300 truncate">{p.name}</span>
                    </div>
                    <span className="text-xs font-bold text-emerald-600 ml-2" style={{ fontFamily: "'JetBrains Mono', monospace" }}>
                      +{p.return_1y?.toFixed(1)}%
                    </span>
                  </div>
                ))}
                {topPerf.length > 5 && (
                  <button
                    onClick={() => setShowAllTop(!showAllTop)}
                    className="w-full text-[10px] font-medium text-emerald-600 hover:text-emerald-700 py-1 text-center"
                    data-testid="show-more-top-performers"
                  >
                    {showAllTop ? "Show Less" : `Show All ${topPerf.length}`}
                  </button>
                )}

                <div className="border-t border-slate-200 dark:border-white/5 my-2" />

                {(showAllBottom ? bottomPerf : bottomPerf.slice(0, 5)).map((p, i) => (
                  <div key={`bottom-${i}`} className="flex items-center justify-between py-1.5 px-2 rounded-lg hover:bg-red-50/50 dark:hover:bg-red-50 dark:bg-red-900/10 transition-colors">
                    <div className="flex items-center gap-2 flex-1 min-w-0">
                      <div className="w-5 h-5 rounded-full bg-red-100 dark:bg-red-900/30 flex items-center justify-center flex-shrink-0">
                        <TrendingDown className="w-3 h-3 text-red-500" />
                      </div>
                      <span className="text-xs text-slate-700 dark:text-zinc-300 truncate">{p.name}</span>
                    </div>
                    <span className="text-xs font-bold text-red-500 ml-2" style={{ fontFamily: "'JetBrains Mono', monospace" }}>
                      {p.return_1y?.toFixed(1)}%
                    </span>
                  </div>
                ))}
                {bottomPerf.length > 5 && (
                  <button
                    onClick={() => setShowAllBottom(!showAllBottom)}
                    className="w-full text-[10px] font-medium text-red-500 hover:text-red-600 py-1 text-center"
                    data-testid="show-more-bottom-performers"
                  >
                    {showAllBottom ? "Show Less" : `Show All ${bottomPerf.length}`}
                  </button>
                )}
              </div>
            </CardContent>
          </Card>
        </motion.div>
      </div>

      {/* MF Category Overlap — Visual Card Grid */}
      {overlapBarData.length > 0 && (
        <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.1 }}>
          <Card className="bg-white dark:bg-[#121212] border-slate-100 dark:border-slate-200 dark:border-white/5 rounded-2xl">
            <CardContent className="p-6 md:p-8">
              <div className="flex items-center gap-3 mb-6">
                <div className="w-10 h-10 rounded-xl bg-amber-50 dark:bg-amber-900/20 flex items-center justify-center">
                  <Layers className="w-5 h-5 text-amber-600" strokeWidth={1.5} />
                </div>
                <div>
                  <h3 className="text-lg font-medium text-slate-900 dark:text-white" style={{ fontFamily: "'Outfit', sans-serif" }}>
                    MF Category Overlap
                  </h3>
                  <p className="text-xs text-slate-500 dark:text-zinc-500">
                    Categories with 2+ funds indicate potential overlap and redundancy
                  </p>
                </div>
              </div>

              <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-3" data-testid="category-overlap-chart">
                {overlapBarData.map((d, i) => {
                  const isOverlapping = d.overlapping;
                  return (
                    <div
                      key={`cat-${d.name}`}
                      className={`rounded-xl p-4 border transition-all hover:shadow-sm ${
                        isOverlapping
                          ? "border-amber-200 bg-amber-50/50 dark:bg-amber-50 dark:bg-amber-900/10 dark:border-amber-800"
                          : "border-emerald-200 bg-emerald-50/50 dark:bg-emerald-900/10 dark:border-emerald-800"
                      }`}
                    >
                      <div className="flex items-center justify-between mb-2">
                        <span className={`text-2xl font-bold ${isOverlapping ? "text-amber-600" : "text-emerald-600"}`} style={{ fontFamily: "'JetBrains Mono', monospace" }}>
                          {d.count}
                        </span>
                        {isOverlapping && (
                          <AlertTriangle className="w-4 h-4 text-amber-500" strokeWidth={1.5} />
                        )}
                      </div>
                      <p className="text-xs font-medium text-slate-700 dark:text-zinc-300">{d.fullName || d.name}</p>
                      <p className="text-[10px] text-slate-400 mt-0.5">
                        {isOverlapping ? "Potential overlap" : "Unique category"}
                      </p>
                    </div>
                  );
                })}
              </div>

              <div className="flex items-center gap-4 mt-4 text-[10px] font-bold tracking-wider uppercase">
                <div className="flex items-center gap-1"><div className="w-3 h-3 rounded bg-amber-500" />Overlapping (2+ funds)</div>
                <div className="flex items-center gap-1"><div className="w-3 h-3 rounded bg-emerald-500" />Unique</div>
              </div>
            </CardContent>
          </Card>
        </motion.div>
      )}

      {/* Fund-by-Fund Benchmark Heatmap */}
      <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.15 }}>
        <Card className="bg-white dark:bg-[#121212] border-slate-100 dark:border-slate-200 dark:border-white/5 rounded-2xl">
          <CardContent className="p-6 md:p-8">
            <h3 className="text-lg font-medium text-slate-900 dark:text-white mb-2" style={{ fontFamily: "'Outfit', sans-serif" }}>
              Portfolio Performance Heatmap
            </h3>
            <p className="text-xs text-slate-500 dark:text-zinc-500 mb-4">Size = invested value. Color = portfolio P&L (green = profit, red = loss). Click any fund to view details.</p>
            <FundHeatmap ratings={ratings} fmt={fmt} />
          </CardContent>
        </Card>
      </motion.div>
    </div>
  );
};
