import React, { useState, useEffect, useMemo } from "react";
import axios from "axios";
import {
  Sparkles, RefreshCw, AlertTriangle, TrendingUp, TrendingDown,
  ArrowRight, Target, DollarSign, Shield, Layers, Building2,
  BarChart3, ArrowUpRight, ArrowDownRight, ChevronDown, ChevronUp, Filter, Zap,
  HelpCircle,
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

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
const API = `${BACKEND_URL}/api`;

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
      <div data-testid="insights-loading" className="space-y-6">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
          <div>
            <h1 className="text-2xl sm:text-3xl font-medium tracking-tight text-slate-900 dark:text-white" style={{ fontFamily: "'Outfit', sans-serif" }}>
              AI Portfolio Analysis
            </h1>
            <p className="text-sm text-slate-500 dark:text-slate-400 mt-1">Loading analysis...</p>
          </div>
        </div>
        <InsightsSkeleton />
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
              doNothing={doNothing}
              fmt={fmt}
              analytics={deepAnalytics}
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
const SEVERITY_CONFIG = {
  critical: { color: "#EF4444", bg: "bg-red-50 dark:bg-red-900/15", border: "border-red-200 dark:border-red-800", label: "Critical", icon: AlertTriangle },
  important: { color: "#F59E0B", bg: "bg-amber-50 dark:bg-amber-900/15", border: "border-amber-200 dark:border-amber-800", label: "Important", icon: AlertTriangle },
  optimization: { color: "#3B82F6", bg: "bg-blue-50 dark:bg-blue-900/15", border: "border-blue-200 dark:border-blue-800", label: "Optimize", icon: TrendingUp },
  positive: { color: "#10B981", bg: "bg-emerald-50 dark:bg-emerald-900/15", border: "border-emerald-200 dark:border-emerald-800", label: "Good", icon: Target },
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
  const confidencePct = totalHoldings > 0 ? Math.round(((navMatched + livePriced) / totalHoldings) * 50 + 50) : 0;

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
      {/* ── Row 1: Health Score + Risk Gauge + Data Confidence ── */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {/* Portfolio Health Score */}
        {gauge && gauge.current > 0 && (
          <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }}>
            <Card className="bg-white dark:bg-slate-800 border-slate-100 dark:border-slate-700 rounded-2xl h-full" data-testid="health-score-card">
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
                <button
                  onClick={() => setShowHealthExplain(!showHealthExplain)}
                  className="mt-2 inline-flex items-center gap-1 text-[10px] text-slate-400 hover:text-emerald-600 transition-colors"
                  data-testid="health-explain-toggle"
                >
                  <HelpCircle className="w-3 h-3" /> {showHealthExplain ? "Hide" : "How is this calculated?"}
                </button>
                <AnimatePresence>
                  {showHealthExplain && (
                    <motion.div
                      initial={{ height: 0, opacity: 0 }}
                      animate={{ height: "auto", opacity: 1 }}
                      exit={{ height: 0, opacity: 0 }}
                      className="overflow-hidden"
                    >
                      <div className="mt-3 text-left p-3 bg-slate-50 dark:bg-slate-700/50 rounded-lg text-[11px] text-slate-600 dark:text-slate-300 space-y-1.5">
                        <p className="font-semibold text-slate-700 dark:text-slate-200">Health = inverse of risk score (100 - {gauge.current} = {100 - gauge.current})</p>
                        <p>Risk score factors:</p>
                        <ul className="list-disc pl-3 space-y-0.5">
                          <li><strong>Concentration risk:</strong> Single asset class &gt;80% of portfolio = +30 points</li>
                          <li><strong>Low diversification:</strong> Fewer than 5 holdings = +15-30 points</li>
                          <li><strong>Sector concentration:</strong> One sector &gt;50% = +25 points</li>
                          <li><strong>Equity overweight:</strong> Equity &gt;80% = +15 points</li>
                        </ul>
                        <p className="text-emerald-600 dark:text-emerald-400 font-medium">Lower risk score = higher health score</p>
                      </div>
                    </motion.div>
                  )}
                </AnimatePresence>
              </CardContent>
            </Card>
          </motion.div>
        )}

        {/* Risk Gauge Current → Target */}
        {gauge && gauge.current > 0 && (
          <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.05 }}>
            <Card className="bg-white dark:bg-slate-800 border-slate-100 dark:border-slate-700 rounded-2xl h-full">
              <CardContent className="p-6">
                <p className="text-[10px] font-bold tracking-wider uppercase text-slate-400 mb-4">Risk Assessment</p>
                <div className="space-y-4">
                  <div>
                    <div className="flex justify-between text-xs mb-1">
                      <span className="text-slate-500">Now</span>
                      <span className="font-semibold text-red-500">{gauge.current_label} ({gauge.current})</span>
                    </div>
                    <div className="w-full h-3 rounded-full bg-slate-100 dark:bg-slate-700 overflow-hidden">
                      <div className="h-full rounded-full transition-all duration-700" style={{ width: `${gauge.current}%`, background: "linear-gradient(90deg, #10B981, #F59E0B, #EF4444)" }} />
                    </div>
                  </div>
                  <div className="flex justify-center"><ArrowRight className="w-4 h-4 text-slate-300" /></div>
                  <div>
                    <div className="flex justify-between text-xs mb-1">
                      <span className="text-slate-500">After Actions</span>
                      <span className="font-semibold text-emerald-600">{gauge.target_label} ({gauge.target})</span>
                    </div>
                    <div className="w-full h-3 rounded-full bg-slate-100 dark:bg-slate-700 overflow-hidden">
                      <div className="h-full rounded-full bg-emerald-500 transition-all duration-700" style={{ width: `${gauge.target}%` }} />
                    </div>
                  </div>
                </div>
                <button
                  onClick={() => setShowRiskExplain(!showRiskExplain)}
                  className="mt-3 inline-flex items-center gap-1 text-[10px] text-slate-400 hover:text-emerald-600 transition-colors"
                  data-testid="risk-explain-toggle"
                >
                  <HelpCircle className="w-3 h-3" /> {showRiskExplain ? "Hide details" : "Why is this high?"}
                </button>
                <AnimatePresence>
                  {showRiskExplain && (
                    <motion.div
                      initial={{ height: 0, opacity: 0 }}
                      animate={{ height: "auto", opacity: 1 }}
                      exit={{ height: 0, opacity: 0 }}
                      className="overflow-hidden"
                    >
                      <div className="mt-3 text-left p-3 bg-slate-50 dark:bg-slate-700/50 rounded-lg text-[11px] text-slate-600 dark:text-slate-300 space-y-1.5">
                        <p className="font-semibold text-red-600 dark:text-red-400">Current Risk: {gauge.current}/100 ({gauge.current_label})</p>
                        <p>Key risk drivers for your portfolio:</p>
                        <ul className="list-disc pl-3 space-y-0.5">
                          {analytics?.overexposure?.fund_house?.filter(f => f.risk_level === "high").map(f => (
                            <li key={f.name}><strong>{f.name}</strong> concentration: {f.pct}% ({f.count} funds)</li>
                          ))}
                          {analytics?.overexposure?.sector?.filter(s => s.risk_level === "high").map(s => (
                            <li key={s.name}><strong>{s.name}</strong> sector: {s.pct}% of portfolio</li>
                          ))}
                          <li>100% equity exposure with no debt/gold buffer</li>
                        </ul>
                        <p className="text-emerald-600 dark:text-emerald-400 font-medium mt-1">Target: {gauge.target}/100 ({gauge.target_label}) — achievable by diversifying</p>
                      </div>
                    </motion.div>
                  )}
                </AnimatePresence>
              </CardContent>
            </Card>
          </motion.div>
        )}

        {/* Data Confidence */}
        <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.1 }}>
          <Card className="bg-white dark:bg-slate-800 border-slate-100 dark:border-slate-700 rounded-2xl h-full" data-testid="confidence-card">
            <CardContent className="p-6">
              <p className="text-[10px] font-bold tracking-wider uppercase text-slate-400 mb-4">Data Confidence</p>
              <div className="text-center mb-3">
                <span className="text-3xl font-bold text-slate-900 dark:text-white" style={{ fontFamily: "'JetBrains Mono', monospace" }}>{confidencePct}%</span>
              </div>
              <div className="space-y-2 text-xs">
                <div className="flex items-center gap-2">
                  <div className={`w-2 h-2 rounded-full ${totalHoldings > 0 ? "bg-emerald-500" : "bg-slate-300"}`} />
                  <span className="text-slate-500 dark:text-slate-400">{totalHoldings} holdings tracked</span>
                </div>
                <div className="flex items-center gap-2">
                  <div className={`w-2 h-2 rounded-full ${navMatched > 0 ? "bg-emerald-500" : "bg-amber-500"}`} />
                  <span className="text-slate-500 dark:text-slate-400">{navMatched} MFs with live NAV</span>
                </div>
                <div className="flex items-center gap-2">
                  <div className={`w-2 h-2 rounded-full ${confidencePct > 50 ? "bg-emerald-500" : "bg-amber-500"}`} />
                  <span className="text-slate-500 dark:text-slate-400">{confidencePct > 70 ? "High accuracy" : confidencePct > 40 ? "Some estimates" : "Limited data"}</span>
                </div>
              </div>
            </CardContent>
          </Card>
        </motion.div>
      </div>

      {/* ── Impact of Actions (expanded) ── */}
      {ba && ba.before && (
        <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.15 }}>
          <Card className="bg-gradient-to-r from-slate-50 to-emerald-50/30 dark:from-slate-800 dark:to-emerald-900/10 border-slate-100 dark:border-slate-700 rounded-2xl" data-testid="impact-card">
            <CardContent className="p-6 md:p-8">
              <h3 className="text-sm font-medium text-slate-900 dark:text-white mb-5" style={{ fontFamily: "'Outfit', sans-serif" }}>
                If You Apply These Changes
              </h3>
              <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                <div className="text-center p-4 bg-white dark:bg-slate-800 rounded-xl border border-slate-100 dark:border-slate-700">
                  <p className="text-[10px] font-bold tracking-wider uppercase text-slate-400 mb-1">Risk Score</p>
                  <p className="text-lg text-red-500 line-through opacity-60" style={{ fontFamily: "'JetBrains Mono', monospace" }}>{ba.before.risk_score}</p>
                  <p className="text-2xl font-bold text-emerald-600" style={{ fontFamily: "'JetBrains Mono', monospace" }}>{ba.after.risk_score}</p>
                </div>
                <div className="text-center p-4 bg-white dark:bg-slate-800 rounded-xl border border-slate-100 dark:border-slate-700">
                  <p className="text-[10px] font-bold tracking-wider uppercase text-slate-400 mb-1">Returns</p>
                  <p className="text-lg text-slate-400 line-through opacity-60" style={{ fontFamily: "'JetBrains Mono', monospace" }}>{ba.before.return_pct}%</p>
                  <p className="text-2xl font-bold text-emerald-600" style={{ fontFamily: "'JetBrains Mono', monospace" }}>+{ba.after.return_pct}%</p>
                </div>
                <div className="text-center p-4 bg-white dark:bg-slate-800 rounded-xl border border-slate-100 dark:border-slate-700">
                  <p className="text-[10px] font-bold tracking-wider uppercase text-slate-400 mb-1">Annual Cost</p>
                  <p className="text-lg text-red-500 line-through opacity-60">{ba.before.annual_cost ? fmt(ba.before.annual_cost) : `${ba.before.expense_ratio}%`}</p>
                  <p className="text-2xl font-bold text-emerald-600">{ba.after.annual_cost ? fmt(ba.after.annual_cost) : `${ba.after.expense_ratio}%`}</p>
                </div>
                {ba.after.wealth_10y_gain && (
                  <div className="text-center p-4 bg-emerald-50 dark:bg-emerald-900/20 rounded-xl border border-emerald-200 dark:border-emerald-800">
                    <p className="text-[10px] font-bold tracking-wider uppercase text-emerald-600 mb-1">10Y Wealth Gain</p>
                    <p className="text-2xl font-bold text-emerald-600" style={{ fontFamily: "'Outfit', sans-serif" }}>+{fmt(ba.after.wealth_10y_gain)}</p>
                    <p className="text-[10px] text-emerald-500 mt-1">additional wealth</p>
                  </div>
                )}
              </div>
            </CardContent>
          </Card>
        </motion.div>
      )}

      {/* ── "Do Nothing" Scenario ── */}
      {doNothing && doNothing.headline && (
        <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.2 }}>
          <Card className="bg-red-50/50 dark:bg-red-900/10 border-red-200 dark:border-red-800 rounded-2xl" data-testid="do-nothing-card">
            <CardContent className="p-6">
              <div className="flex items-start gap-4">
                <div className="w-10 h-10 rounded-xl bg-red-100 dark:bg-red-900/30 flex items-center justify-center flex-shrink-0">
                  <AlertTriangle className="w-5 h-5 text-red-500" strokeWidth={1.5} />
                </div>
                <div>
                  <h3 className="text-sm font-semibold text-red-700 dark:text-red-400 mb-1" style={{ fontFamily: "'Outfit', sans-serif" }}>
                    What Happens If You Do Nothing?
                  </h3>
                  <p className="text-sm text-red-600 dark:text-red-300 font-medium">{doNothing.headline}</p>
                  <div className="flex flex-wrap gap-4 mt-3 text-xs">
                    {doNothing.annual_cost_leak > 0 && (
                      <span className="text-red-500">Annual leak: <strong>{fmt(doNothing.annual_cost_leak)}</strong></span>
                    )}
                    {doNothing.risk_remains && (
                      <span className="text-red-500">Risk: <strong>{doNothing.risk_remains}</strong></span>
                    )}
                    {doNothing.ten_year_loss && (
                      <span className="text-red-500">10Y cost: <strong>{doNothing.ten_year_loss}</strong></span>
                    )}
                  </div>
                </div>
              </div>
            </CardContent>
          </Card>
        </motion.div>
      )}

      {/* ── Actionable Insight Cards (Collapsible) ── */}
      {ins.length > 0 && (
        <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.25 }}>
          <div className="space-y-3" data-testid="actionable-insights">
            <h3 className="text-sm font-medium text-slate-900 dark:text-white" style={{ fontFamily: "'Outfit', sans-serif" }}>
              Actionable Insights ({ins.length})
            </h3>
            {ins.map((insight, i) => {
              const sev = SEVERITY_CONFIG[insight.severity] || SEVERITY_CONFIG[insight.type === "warning" ? "critical" : insight.type === "opportunity" ? "optimization" : "important"] || SEVERITY_CONFIG.important;
              const SevIcon = sev.icon;
              const isExpanded = expandedInsight === i;

              return (
                <motion.div
                  key={i}
                  initial={{ opacity: 0, x: -8 }}
                  animate={{ opacity: 1, x: 0 }}
                  transition={{ delay: i * 0.03 }}
                  className={`rounded-xl border ${sev.border} overflow-hidden`}
                  data-testid={`insight-card-${i}`}
                >
                  {/* Level 1: Scannable */}
                  <div
                    className={`p-4 cursor-pointer ${sev.bg} hover:opacity-90 transition-opacity`}
                    onClick={() => setExpandedInsight(isExpanded ? null : i)}
                  >
                    <div className="flex items-start gap-3">
                      <SevIcon className="w-4 h-4 flex-shrink-0 mt-0.5" style={{ color: sev.color }} />
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2">
                          <p className="text-sm font-semibold text-slate-900 dark:text-white">{insight.title}</p>
                          <span className="text-[9px] font-bold uppercase tracking-wider px-1.5 py-0.5 rounded" style={{ backgroundColor: `${sev.color}15`, color: sev.color }}>
                            {sev.label}
                          </span>
                        </div>
                        <p className="text-xs text-slate-500 dark:text-slate-400 mt-0.5">
                          {insight.summary || insight.description?.slice(0, 80)}
                        </p>
                      </div>
                      <div className="flex items-center gap-2 flex-shrink-0">
                        {insight.current_value && (
                          <span className="text-xs text-slate-400" style={{ fontFamily: "'JetBrains Mono', monospace" }}>
                            {insight.current_value} → {insight.target_value}
                          </span>
                        )}
                        {isExpanded ? <ChevronUp className="w-4 h-4 text-slate-400" /> : <ChevronDown className="w-4 h-4 text-slate-400" />}
                      </div>
                    </div>
                  </div>

                  {/* Level 2: Expanded detail */}
                  {isExpanded && (
                    <div className="p-4 bg-white dark:bg-slate-800 border-t border-slate-100 dark:border-slate-700 space-y-3">
                      {/* Why it matters */}
                      {(insight.why_it_matters || insight.description) && (
                        <div>
                          <p className="text-[10px] font-bold tracking-wider uppercase text-slate-400 mb-1">Why It Matters</p>
                          <p className="text-xs text-slate-600 dark:text-slate-300 leading-relaxed">{insight.why_it_matters || insight.description}</p>
                        </div>
                      )}

                      {/* Recommended Action */}
                      {insight.action && (
                        <div className="p-3 bg-emerald-50 dark:bg-emerald-900/15 rounded-lg border border-emerald-200 dark:border-emerald-800">
                          <p className="text-[10px] font-bold tracking-wider uppercase text-emerald-600 mb-1">Recommended Action</p>
                          <p className="text-xs text-emerald-700 dark:text-emerald-300 font-medium">{insight.action}</p>
                        </div>
                      )}

                      {/* Affected Holdings */}
                      {analytics?.performance_cards?.length > 0 && (
                        <div>
                          <p className="text-[10px] font-bold tracking-wider uppercase text-slate-400 mb-2">Affected Holdings</p>
                          <div className="space-y-1 max-h-48 overflow-y-auto">
                            {getAffectedHoldings(insight, analytics.performance_cards).map((h, hi) => (
                              <div key={`affected-${hi}`} className="flex items-center justify-between py-1.5 px-2 bg-slate-50 dark:bg-slate-700/30 rounded-lg text-xs">
                                <div className="flex items-center gap-2 min-w-0 flex-1">
                                  <div className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${h.pct_return >= 0 ? "bg-emerald-500" : "bg-red-500"}`} />
                                  <span className="text-slate-700 dark:text-slate-300 truncate">{h.name}</span>
                                </div>
                                <div className="flex items-center gap-3 flex-shrink-0 ml-2">
                                  <span className="text-slate-400">{h.sector}</span>
                                  <span className={`font-medium ${h.pct_return >= 0 ? "text-emerald-600" : "text-red-500"}`} style={{ fontFamily: "'JetBrains Mono', monospace" }}>
                                    {h.pct_return >= 0 ? "+" : ""}{h.pct_return}%
                                  </span>
                                  <span className="text-slate-500" style={{ fontFamily: "'JetBrains Mono', monospace" }}>{fmt(h.current_value)}</span>
                                </div>
                              </div>
                            ))}
                          </div>
                        </div>
                      )}

                      {/* Expected Impact */}
                      <div className="flex gap-4">
                        {insight.expected_impact && (
                          <div className="flex-1">
                            <p className="text-[10px] font-bold tracking-wider uppercase text-slate-400 mb-1">Expected Impact</p>
                            <p className="text-xs text-slate-600 dark:text-slate-300">{insight.expected_impact}</p>
                          </div>
                        )}
                        {insight.rupee_impact && (
                          <div className="flex-shrink-0 text-right">
                            <p className="text-[10px] font-bold tracking-wider uppercase text-slate-400 mb-1">Value</p>
                            <p className="text-sm font-bold text-emerald-600" style={{ fontFamily: "'JetBrains Mono', monospace" }}>{insight.rupee_impact}</p>
                          </div>
                        )}
                      </div>
                    </div>
                  )}
                </motion.div>
              );
            })}
          </div>
        </motion.div>
      )}

      {/* ── Simulate Optimized Portfolio Button ── */}
      <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.3 }}>
        <Card className="bg-gradient-to-r from-emerald-50 to-blue-50 dark:from-emerald-900/15 dark:to-blue-900/15 border-emerald-200 dark:border-emerald-800 rounded-2xl" data-testid="simulate-card">
          <CardContent className="p-6">
            <div className="flex items-center justify-between mb-4">
              <div className="flex items-center gap-3">
                <div className="w-10 h-10 rounded-xl bg-emerald-100 dark:bg-emerald-900/30 flex items-center justify-center">
                  <Zap className="w-5 h-5 text-emerald-600" strokeWidth={1.5} />
                </div>
                <div>
                  <h3 className="text-sm font-semibold text-slate-900 dark:text-white" style={{ fontFamily: "'Outfit', sans-serif" }}>
                    Simulate Optimized Portfolio
                  </h3>
                  <p className="text-[11px] text-slate-500 dark:text-slate-400">
                    See projected returns if all recommendations are implemented
                  </p>
                </div>
              </div>
              <Button
                data-testid="simulate-button"
                onClick={runSimulation}
                disabled={simulating}
                className="bg-emerald-600 hover:bg-emerald-700 text-white rounded-xl"
              >
                {simulating ? <RefreshCw className="w-4 h-4 mr-2 animate-spin" /> : <Zap className="w-4 h-4 mr-2" />}
                {simulating ? "Simulating..." : "Run Simulation"}
              </Button>
            </div>

            {/* Simulation Results */}
            <AnimatePresence>
              {simulation && (
                <motion.div
                  initial={{ height: 0, opacity: 0 }}
                  animate={{ height: "auto", opacity: 1 }}
                  exit={{ height: 0, opacity: 0 }}
                  transition={{ duration: 0.3 }}
                  className="overflow-hidden"
                >
                  <div className="border-t border-emerald-200 dark:border-emerald-800 pt-4 mt-2">
                    {/* Key metrics row */}
                    <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-4">
                      <div className="text-center p-3 bg-white dark:bg-slate-800 rounded-xl border border-slate-100 dark:border-slate-700">
                        <p className="text-[9px] font-bold tracking-wider uppercase text-slate-400 mb-1">Current Returns</p>
                        <p className="text-lg font-bold text-slate-700 dark:text-slate-300" style={{ fontFamily: "'JetBrains Mono', monospace" }}>
                          {simulation.current_returns_pct >= 0 ? "+" : ""}{simulation.current_returns_pct}%
                        </p>
                        <p className="text-[10px] text-slate-400">{fmt(simulation.current_returns)}</p>
                      </div>
                      <div className="text-center p-3 bg-white dark:bg-slate-800 rounded-xl border border-slate-100 dark:border-slate-700">
                        <p className="text-[9px] font-bold tracking-wider uppercase text-emerald-600 mb-1">Optimized (1Y)</p>
                        <p className="text-lg font-bold text-emerald-600" style={{ fontFamily: "'JetBrains Mono', monospace" }}>
                          +{simulation.optimized_returns_pct}%
                        </p>
                        <p className="text-[10px] text-emerald-500">{fmt(simulation.optimized_value_1yr)}</p>
                      </div>
                      <div className="text-center p-3 bg-emerald-50 dark:bg-emerald-900/20 rounded-xl border border-emerald-200 dark:border-emerald-800">
                        <p className="text-[9px] font-bold tracking-wider uppercase text-emerald-600 mb-1">Additional Returns</p>
                        <p className="text-xl font-bold text-emerald-600" style={{ fontFamily: "'Outfit', sans-serif" }}>
                          +{fmt(simulation.additional_returns)}
                        </p>
                        <p className="text-[10px] text-emerald-500">+{simulation.additional_returns_pct}% extra p.a.</p>
                      </div>
                      <div className="text-center p-3 bg-white dark:bg-slate-800 rounded-xl border border-slate-100 dark:border-slate-700">
                        <p className="text-[9px] font-bold tracking-wider uppercase text-slate-400 mb-1">Actions</p>
                        <p className="text-lg font-bold text-slate-700 dark:text-slate-300" style={{ fontFamily: "'JetBrains Mono', monospace" }}>
                          {simulation.actions?.length || 0}
                        </p>
                        <p className="text-[10px] text-slate-400">to implement</p>
                      </div>
                    </div>

                    {/* Action breakdown */}
                    {simulation.actions?.length > 0 && (
                      <div className="space-y-2">
                        <p className="text-[10px] font-bold tracking-wider uppercase text-slate-400">Action Breakdown</p>
                        {simulation.actions.map((a, i) => (
                          <div key={i} className="flex items-center justify-between py-2 px-3 bg-white dark:bg-slate-800 rounded-lg border border-slate-100 dark:border-slate-700">
                            <div className="flex items-center gap-2 flex-1 min-w-0">
                              <div className={`w-5 h-5 rounded-full flex items-center justify-center flex-shrink-0 ${
                                a.action === "sell" ? "bg-red-100 dark:bg-red-900/30" :
                                a.action === "buy" ? "bg-emerald-100 dark:bg-emerald-900/30" :
                                a.action === "switch" ? "bg-blue-100 dark:bg-blue-900/30" :
                                "bg-amber-100 dark:bg-amber-900/30"
                              }`}>
                                {a.action === "sell" ? <ArrowDownRight className="w-3 h-3 text-red-500" /> :
                                 a.action === "buy" ? <ArrowUpRight className="w-3 h-3 text-emerald-600" /> :
                                 <ArrowRight className="w-3 h-3 text-amber-600" />}
                              </div>
                              <span className="text-xs text-slate-700 dark:text-slate-300 truncate">{a.title}</span>
                            </div>
                            <span className="text-xs font-bold text-emerald-600 ml-2 flex-shrink-0" style={{ fontFamily: "'JetBrains Mono', monospace" }}>
                              {a.savings_1yr > 0 ? `+${fmt(a.savings_1yr)}/yr` : "—"}
                            </span>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                </motion.div>
              )}
            </AnimatePresence>
          </CardContent>
        </Card>
      </motion.div>

      {/* ── Problem Distribution + Cost Leakage ── */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {pd.length > 0 && (
          <Card className="bg-white dark:bg-slate-800 border-slate-100 dark:border-slate-700 rounded-2xl">
            <CardContent className="p-6">
              <p className="text-[10px] font-bold tracking-wider uppercase text-slate-400 mb-4">Issue Breakdown</p>
              <div className="h-36 cursor-pointer">
                <ResponsiveContainer width="100%" height="100%">
                  <PieChart>
                    <Pie data={pd} cx="50%" cy="50%" innerRadius={32} outerRadius={55} paddingAngle={2} dataKey="value"
                      onClick={(_, idx) => setActiveIssueCategory(activeIssueCategory === pd[idx]?.name ? null : pd[idx]?.name)}
                    >
                      {pd.map((d, i) => (
                        <Cell key={`pie-${d.name}`} fill={d.color} stroke={activeIssueCategory === d.name ? "#1E293B" : "transparent"} strokeWidth={activeIssueCategory === d.name ? 2 : 0}
                          style={{ cursor: "pointer", opacity: activeIssueCategory && activeIssueCategory !== d.name ? 0.4 : 1 }}
                        />
                      ))}
                    </Pie>
                    <Tooltip formatter={v => `${v}%`} />
                  </PieChart>
                </ResponsiveContainer>
              </div>
              <div className="space-y-1 mt-2">
                {pd.map(d => (
                  <div
                    key={d.name}
                    className={`flex items-center justify-between cursor-pointer rounded-lg px-2 py-1 transition-colors ${activeIssueCategory === d.name ? "bg-slate-100 dark:bg-slate-700" : "hover:bg-slate-50 dark:hover:bg-slate-700/50"}`}
                    onClick={() => setActiveIssueCategory(activeIssueCategory === d.name ? null : d.name)}
                    data-testid={`issue-${d.name.replace(/\s/g, '-').toLowerCase()}`}
                  >
                    <div className="flex items-center gap-2">
                      <div className="w-2.5 h-2.5 rounded-full" style={{ backgroundColor: d.color }} />
                      <span className="text-xs text-slate-500 dark:text-slate-400">{d.name}</span>
                    </div>
                    <span className="text-xs font-medium text-slate-900 dark:text-white">{d.value}%</span>
                  </div>
                ))}
              </div>
              {/* Drill-down: show related holdings when a category is clicked */}
              <AnimatePresence>
                {activeIssueCategory && analytics?.performance_cards?.length > 0 && (
                  <motion.div initial={{ height: 0, opacity: 0 }} animate={{ height: "auto", opacity: 1 }} exit={{ height: 0, opacity: 0 }} className="overflow-hidden">
                    <div className="mt-3 pt-3 border-t border-slate-100 dark:border-slate-700">
                      <p className="text-[10px] font-bold tracking-wider uppercase text-slate-400 mb-2">
                        Holdings related to "{activeIssueCategory}"
                      </p>
                      <div className="space-y-1 max-h-40 overflow-y-auto">
                        {getHoldingsForIssue(activeIssueCategory, analytics.performance_cards, ins).map((h, idx) => (
                          <div key={`drill-${idx}`} className="flex items-center justify-between py-1.5 px-2 bg-slate-50 dark:bg-slate-700/30 rounded text-[11px]">
                            <span className="text-slate-700 dark:text-slate-300 truncate flex-1">{h.name}</span>
                            <span className={`ml-2 font-medium ${h.pct_return >= 0 ? "text-emerald-600" : "text-red-500"}`}>
                              {h.pct_return >= 0 ? "+" : ""}{h.pct_return}%
                            </span>
                            <span className="ml-2 text-slate-400">{fmt(h.current_value)}</span>
                          </div>
                        ))}
                      </div>
                    </div>
                  </motion.div>
                )}
              </AnimatePresence>
            </CardContent>
          </Card>
        )}

        {cost && cost.annual_loss > 0 && (
          <Card className="bg-white dark:bg-slate-800 border-slate-100 dark:border-slate-700 rounded-2xl">
            <CardContent className="p-6">
              <p className="text-[10px] font-bold tracking-wider uppercase text-slate-400 mb-4">Cost Leakage</p>
              <div className="text-center mb-4">
                <p className="text-3xl font-bold text-red-500" style={{ fontFamily: "'Outfit', sans-serif" }}>{fmt(cost.annual_loss)}</p>
                <p className="text-xs text-red-400 mt-1">lost per year ({cost.loss_pct}% of portfolio)</p>
              </div>
              <p className="text-xs text-slate-500 dark:text-slate-400 text-center">{cost.detail}</p>
              <div className="mt-4 p-3 bg-emerald-50 dark:bg-emerald-900/15 rounded-lg text-center">
                <p className="text-xs text-emerald-600 font-medium">Switching to direct plans could save {fmt(cost.annual_loss)}/year</p>
              </div>
            </CardContent>
          </Card>
        )}
      </div>

      {/* ── Interactive Action Funnel ── */}
      {funnel.length > 0 && (
        <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.3 }}>
          <Card className="bg-white dark:bg-slate-800 border-slate-100 dark:border-slate-700 rounded-2xl" data-testid="action-funnel">
            <CardContent className="p-6 md:p-8">
              <div className="flex items-center justify-between mb-6">
                <h3 className="text-sm font-medium text-slate-900 dark:text-white" style={{ fontFamily: "'Outfit', sans-serif" }}>
                  Action Plan
                </h3>
                <div className="flex items-center gap-2">
                  <div className="w-20 h-2 rounded-full bg-slate-100 dark:bg-slate-700 overflow-hidden">
                    <div className="h-full rounded-full bg-emerald-500 transition-all" style={{ width: `${funnel.length > 0 ? (completedCount / funnel.length) * 100 : 0}%` }} />
                  </div>
                  <span className="text-xs text-slate-400">{completedCount}/{funnel.length}</span>
                </div>
              </div>
              <div className="space-y-3">
                {funnel.map((step, i) => {
                  const done = completedActions[step.step];
                  const statusColors = { critical: "#EF4444", important: "#F59E0B", moderate: "#3B82F6", recommended: "#10B981" };
                  return (
                    <div key={i} className={`flex items-start gap-4 p-3 rounded-xl transition-all ${done ? "bg-emerald-50/50 dark:bg-emerald-900/10 opacity-70" : "hover:bg-slate-50 dark:hover:bg-slate-800"}`}>
                      <button
                        onClick={() => toggleAction(step.step)}
                        className={`w-7 h-7 rounded-lg flex items-center justify-center flex-shrink-0 border-2 transition-all ${
                          done ? "bg-emerald-500 border-emerald-500 text-white" : "border-slate-200 dark:border-slate-600 hover:border-emerald-400"
                        }`}
                        data-testid={`action-check-${i}`}
                      >
                        {done ? <span className="text-xs font-bold">✓</span> : <span className="text-xs font-bold text-slate-400">{step.step}</span>}
                      </button>
                      <div className="flex-1">
                        <p className={`text-sm font-medium ${done ? "line-through text-slate-400" : "text-slate-900 dark:text-white"}`}>{step.title}</p>
                        <p className="text-xs text-slate-500 dark:text-slate-400 mt-0.5">{step.detail}</p>
                        {step.rupee_impact && <p className="text-[10px] text-emerald-600 font-medium mt-1">{step.rupee_impact}</p>}
                      </div>
                      <span className="text-[9px] font-bold uppercase tracking-wider px-2 py-0.5 rounded-full flex-shrink-0" style={{ backgroundColor: `${statusColors[step.status] || "#94A3B8"}15`, color: statusColors[step.status] || "#94A3B8" }}>
                        {step.status}
                      </span>
                    </div>
                  );
                })}
                <div className="flex items-center gap-4 p-3">
                  <div className="w-7 h-7 rounded-lg bg-emerald-500 flex items-center justify-center flex-shrink-0">
                    <Target className="w-4 h-4 text-white" />
                  </div>
                  <p className="text-sm font-medium text-emerald-600">Optimized Portfolio</p>
                </div>
              </div>
            </CardContent>
          </Card>
        </motion.div>
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

              {/* Stacked Allocation Chart — Current vs Ideal */}
              <div className="mb-6" data-testid="fund-house-chart">
                <div className="flex gap-6 items-end justify-center">
                  {/* Current Allocation Bar */}
                  <div className="flex flex-col items-center">
                    <p className="text-[10px] font-bold tracking-wider uppercase text-slate-400 mb-3">Current</p>
                    <div className="w-24 h-64 rounded-xl overflow-hidden flex flex-col-reverse border border-slate-200 dark:border-slate-700">
                      {fundHouse.slice(0, 6).map((fh, i) => (
                        <div
                          key={`cur-${fh.name}`}
                          className="relative flex items-center justify-center transition-all hover:opacity-90 cursor-pointer"
                          style={{ height: `${Math.max(fh.pct, 3)}%`, backgroundColor: CHART_COLORS[i % CHART_COLORS.length] }}
                          title={`${fh.name}: ${fh.pct}%`}
                          onClick={() => setExpandedFH(expandedFH === i ? null : i)}
                        >
                          {fh.pct >= 8 && (
                            <span className="text-[10px] font-bold text-white drop-shadow-sm">{fh.pct}%</span>
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
                    <div className="w-24 h-64 rounded-xl overflow-hidden flex flex-col-reverse border border-slate-200 dark:border-slate-700">
                      {(() => {
                        const idealPct = Math.round(100 / Math.max(fundHouse.length, 1));
                        return fundHouse.slice(0, 6).map((fh, i) => (
                          <div
                            key={`ideal-${fh.name}`}
                            className="relative flex items-center justify-center"
                            style={{ height: `${idealPct}%`, backgroundColor: CHART_COLORS[i % CHART_COLORS.length], opacity: 0.7 }}
                          >
                            {idealPct >= 8 && (
                              <span className="text-[10px] font-bold text-white drop-shadow-sm">{idealPct}%</span>
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
                    Sector Composition
                  </h3>
                  <p className="text-xs text-slate-500 dark:text-slate-400">
                    Equity sector exposure + MF category distribution across your holdings
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
          <div key={amc.name} className="rounded-xl border border-slate-200 dark:border-slate-700 overflow-hidden">
            <button
              onClick={() => setExpandedAmc(isExpanded ? null : amc.name)}
              className="w-full flex items-center justify-between p-4 hover:bg-slate-50 dark:hover:bg-slate-800/50 transition-colors"
              data-testid={`amc-group-${amc.name}`}
            >
              <div className="flex items-center gap-3">
                <div className="w-8 h-8 rounded-lg bg-slate-100 dark:bg-slate-700 flex items-center justify-center text-sm font-bold text-slate-600 dark:text-slate-300">
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
                  <div className="border-t border-slate-100 dark:border-slate-700 p-4 space-y-3">
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
                              <p className="text-sm font-medium text-slate-600 dark:text-slate-400" style={{ fontFamily: "'JetBrains Mono', monospace" }}>
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
              <p className="text-[10px] font-medium text-white/90 leading-tight truncate">{fund.name}</p>
              <p className="text-lg font-bold text-white mt-1.5" style={{ fontFamily: "'JetBrains Mono', monospace" }}>
                {fund.pnlPct >= 0 ? "+" : ""}{fund.pnlPct.toFixed(1)}%
              </p>
              <div className="flex items-center justify-between mt-1.5">
                <span className="text-[9px] text-white/60">{fmt(fund.invested)}</span>
                <span className="text-[9px] text-white/80 font-medium">{fund.pnl >= 0 ? "+" : ""}{fmt(fund.pnl)}</span>
              </div>
            </div>
          );
        })}
      </div>

      {/* Selected fund detail */}
      <AnimatePresence>
        {selectedFund !== null && heatmapData[selectedFund] && (
          <motion.div initial={{ height: 0, opacity: 0 }} animate={{ height: "auto", opacity: 1 }} exit={{ height: 0, opacity: 0 }} className="overflow-hidden">
            <div className="mt-4 p-5 bg-slate-50 dark:bg-slate-700/50 rounded-xl border border-slate-200 dark:border-slate-600">
              <div className="flex justify-between items-start mb-4">
                <div>
                  <p className="text-sm font-medium text-slate-900 dark:text-white">{heatmapData[selectedFund].fullName}</p>
                  <p className="text-[10px] text-slate-500 mt-0.5">{heatmapData[selectedFund].sector}</p>
                </div>
                <button onClick={() => setSelectedFund(null)} className="text-xs text-slate-400 hover:text-slate-600 bg-slate-200 dark:bg-slate-600 px-2 py-1 rounded-lg">Close</button>
              </div>
              <div className="grid grid-cols-4 gap-4">
                <div>
                  <p className="text-[9px] font-bold uppercase tracking-wider text-slate-400">P&L</p>
                  <p className={`text-base font-bold mt-1 ${heatmapData[selectedFund].pnlPct >= 0 ? "text-emerald-600" : "text-red-500"}`} style={{ fontFamily: "'JetBrains Mono', monospace" }}>
                    {heatmapData[selectedFund].pnlPct >= 0 ? "+" : ""}{heatmapData[selectedFund].pnlPct.toFixed(1)}%
                  </p>
                </div>
                <div>
                  <p className="text-[9px] font-bold uppercase tracking-wider text-slate-400">Invested</p>
                  <p className="text-base font-medium text-slate-700 dark:text-slate-300 mt-1">{fmt(heatmapData[selectedFund].invested)}</p>
                </div>
                <div>
                  <p className="text-[9px] font-bold uppercase tracking-wider text-slate-400">Current</p>
                  <p className="text-base font-medium text-slate-700 dark:text-slate-300 mt-1">{fmt(heatmapData[selectedFund].current_value)}</p>
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
  overperforming: { label: "Outperforming", color: "#10B981", bg: "bg-emerald-50 dark:bg-emerald-900/15", border: "border-emerald-200 dark:border-emerald-800", icon: TrendingUp },
  meeting: { label: "Meeting Benchmark", color: "#3B82F6", bg: "bg-blue-50 dark:bg-blue-900/15", border: "border-blue-200 dark:border-blue-800", icon: ArrowRight },
  underperforming: { label: "Underperforming", color: "#EF4444", bg: "bg-red-50 dark:bg-red-900/15", border: "border-red-200 dark:border-red-800", icon: TrendingDown },
  no_data: { label: "No Benchmark Data", color: "#94A3B8", bg: "bg-slate-50 dark:bg-slate-800/50", border: "border-slate-200 dark:border-slate-700", icon: BarChart3 },
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
      <Card className="bg-white dark:bg-slate-800 border-slate-100 dark:border-slate-700 rounded-2xl">
        <CardContent className="p-12 text-center">
          <div className="relative w-16 h-16 mx-auto mb-4">
            <div className="w-16 h-16 border-3 border-emerald-100 dark:border-emerald-900/30 rounded-full" />
            <div className="absolute inset-0 w-16 h-16 border-3 border-emerald-600 border-t-transparent rounded-full animate-spin" />
          </div>
          <h3 className="text-lg font-medium text-slate-900 dark:text-white mb-2" style={{ fontFamily: "'Outfit', sans-serif" }}>
            Fetching Benchmark Data...
          </h3>
          <p className="text-sm text-slate-500 dark:text-slate-400 mb-4">Fetching 1-year historical NAVs from AMFI for each mutual fund.</p>
          <div className="max-w-xs mx-auto">
            <div className="w-full h-2 rounded-full bg-slate-100 dark:bg-slate-700 overflow-hidden">
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
                <div className="flex-1 space-y-2.5">
                  {pieData.map(d => (
                    <div key={d.name} className="flex items-center justify-between cursor-pointer hover:bg-slate-50 dark:hover:bg-slate-800 rounded-lg px-2 py-1 -mx-2 transition-colors"
                      onClick={() => setDrilldownRating(d.ratingKey)}
                    >
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
                  <div className="mt-4 border-t border-slate-100 dark:border-slate-700 pt-4">
                    <div className="flex items-center justify-between mb-3">
                      <p className="text-xs font-medium text-slate-900 dark:text-white">
                        {ratingLabel[drilldownRating]} Funds ({drillFunds.length})
                      </p>
                      <button onClick={() => setDrilldownRating(null)} className="text-[10px] text-slate-400 hover:text-slate-600">Close</button>
                    </div>
                    <div className="space-y-2 max-h-48 overflow-y-auto">
                      {drillFunds.length > 0 ? drillFunds.map((r, i) => (
                        <div key={i} className="flex items-center justify-between text-xs py-1.5 px-2 rounded-lg bg-slate-50 dark:bg-slate-700/50">
                          <span className="text-slate-700 dark:text-slate-300 truncate flex-1 mr-2">{r.name}</span>
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
          <Card className="bg-white dark:bg-slate-800 border-slate-100 dark:border-slate-700 rounded-2xl h-full">
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
                      <span className="text-xs text-slate-700 dark:text-slate-300 truncate">{p.name}</span>
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

                <div className="border-t border-slate-100 dark:border-slate-700 my-2" />

                {(showAllBottom ? bottomPerf : bottomPerf.slice(0, 5)).map((p, i) => (
                  <div key={`bottom-${i}`} className="flex items-center justify-between py-1.5 px-2 rounded-lg hover:bg-red-50/50 dark:hover:bg-red-900/10 transition-colors">
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
          <Card className="bg-white dark:bg-slate-800 border-slate-100 dark:border-slate-700 rounded-2xl">
            <CardContent className="p-6 md:p-8">
              <div className="flex items-center gap-3 mb-6">
                <div className="w-10 h-10 rounded-xl bg-amber-50 dark:bg-amber-900/20 flex items-center justify-center">
                  <Layers className="w-5 h-5 text-amber-600" strokeWidth={1.5} />
                </div>
                <div>
                  <h3 className="text-lg font-medium text-slate-900 dark:text-white" style={{ fontFamily: "'Outfit', sans-serif" }}>
                    MF Category Overlap
                  </h3>
                  <p className="text-xs text-slate-500 dark:text-slate-400">
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
                          ? "border-amber-200 bg-amber-50/50 dark:bg-amber-900/10 dark:border-amber-800"
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
                      <p className="text-xs font-medium text-slate-700 dark:text-slate-300">{d.fullName || d.name}</p>
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
        <Card className="bg-white dark:bg-slate-800 border-slate-100 dark:border-slate-700 rounded-2xl">
          <CardContent className="p-6 md:p-8">
            <h3 className="text-lg font-medium text-slate-900 dark:text-white mb-2" style={{ fontFamily: "'Outfit', sans-serif" }}>
              Portfolio Performance Heatmap
            </h3>
            <p className="text-xs text-slate-500 dark:text-slate-400 mb-4">Size = invested value. Color = portfolio P&L (green = profit, red = loss). Click any fund to view details.</p>
            <FundHeatmap ratings={ratings} fmt={fmt} />
          </CardContent>
        </Card>
      </motion.div>
    </div>
  );
};
