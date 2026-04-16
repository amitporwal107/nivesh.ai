import React, { useMemo, useState } from "react";
import { TrendingUp, TrendingDown, Wallet, AlertTriangle, RefreshCw, Calendar, Sparkles, ArrowUpRight, ArrowDownRight, BarChart3, Info, Flag, ChevronDown } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import {
  PieChart, Pie, Cell, ResponsiveContainer, Tooltip as RechartsTooltip,
  AreaChart, Area, XAxis, YAxis, CartesianGrid,
  BarChart, Bar,
  Treemap,
} from "recharts";
import { motion } from "framer-motion";
import { useNumberFormat } from "@/context/NumberFormatContext";
import DrilldownModal from "@/components/DrilldownModal";

// ── InfoTooltip: hover to show explanation ──
const InfoTooltip = ({ text, children }) => {
  const [show, setShow] = useState(false);
  return (
    <span className="relative inline-flex items-center" onMouseEnter={() => setShow(true)} onMouseLeave={() => setShow(false)}>
      {children || <Info className="w-3.5 h-3.5 text-slate-400 hover:text-slate-600 dark:hover:text-slate-300 cursor-help ml-1" />}
      {show && (
        <span className="absolute z-50 bottom-full left-1/2 -translate-x-1/2 mb-2 w-64 p-3 text-[11px] leading-relaxed text-slate-700 dark:text-slate-200 bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-600 rounded-xl shadow-lg pointer-events-none">
          {text}
        </span>
      )}
    </span>
  );
};

// ── SimulatedBadge: red flag for simulated/assumed data ──
const SimulatedBadge = ({ label = "Simulated", tooltip }) => (
  <span className="inline-flex items-center gap-1 text-[9px] font-bold uppercase tracking-wider text-red-600 bg-red-50 dark:bg-red-900/30 dark:text-red-400 px-1.5 py-0.5 rounded-md ml-1.5" data-testid="simulated-badge">
    <Flag className="w-2.5 h-2.5" />
    {label}
    {tooltip && <InfoTooltip text={tooltip} />}
  </span>
);

const COLORS = ["#059669", "#3B82F6", "#F59E0B", "#8B5CF6", "#EF4444", "#EC4899", "#14B8A6", "#F97316", "#6366F1", "#84CC16"];

const ASSET_LABELS = {
  equity: "Equity", mutual_fund: "Mutual Funds", etf: "ETF",
  bond: "Bonds", gold: "Gold", fd: "Fixed Deposit", other: "Other",
};

// Custom Treemap content for heatmap - clickable with proper data access
const HeatmapCell = (props) => {
  const { x, y, width, height, depth, index } = props;
  if (width < 4 || height < 4 || depth !== 1) return null;
  
  // Recharts Treemap passes all data fields as direct props
  const name = props.name || "";
  const return_pct = typeof props.return_pct === "number" ? props.return_pct : 0;
  const value = props.value || 0;
  
  const isPositive = return_pct >= 0;
  const intensity = Math.min(Math.abs(return_pct) / 50, 1);
  const bg = isPositive
    ? `rgba(16, 185, 129, ${0.15 + intensity * 0.55})`
    : `rgba(239, 68, 68, ${0.15 + intensity * 0.55})`;
  const textColor = intensity > 0.4 ? "#fff" : isPositive ? "#065F46" : "#991B1B";
  const showName = width > 55 && height > 28;
  const showPct = width > 35 && height > 18;

  return (
    <g style={{ cursor: "pointer" }}>
      <rect x={x} y={y} width={width} height={height} fill={bg} stroke="#F8FAFC" strokeWidth={2} rx={6} />
      {showName && (
        <text x={x + width / 2} y={y + height / 2 - (showPct ? 7 : 0)} textAnchor="middle" fill={textColor} fontSize={width > 120 ? 11 : width > 80 ? 10 : 8} fontFamily="'Figtree', sans-serif" fontWeight={500} style={{ pointerEvents: "none" }}>
          {name.length > (width > 120 ? 22 : width > 80 ? 15 : 10) ? name.slice(0, width > 120 ? 22 : width > 80 ? 15 : 10) + "..." : name}
        </text>
      )}
      {showPct && (
        <text x={x + width / 2} y={y + height / 2 + (showName ? 10 : 0)} textAnchor="middle" fill={textColor} fontSize={width > 80 ? 11 : 9} fontFamily="'JetBrains Mono', monospace" fontWeight={600} style={{ pointerEvents: "none" }}>
          {isPositive ? "+" : ""}{return_pct.toFixed(1)}%
        </text>
      )}
    </g>
  );
};

const DashboardOverview = ({ analytics, insights, holdings, loading, onRefresh }) => {
  const { fmt, fmtShort, displayMode, setDisplayMode } = useNumberFormat();
  const [drilldown, setDrilldown] = useState(null);
  const today = new Date().toLocaleDateString("en-IN", { weekday: "long", year: "numeric", month: "long", day: "numeric" });

  // Sector bar chart data
  const sectorBarData = useMemo(() => {
    if (!analytics?.sector_exposure) return [];
    const total = analytics.current_value || 1;
    return analytics.sector_exposure
      .map(s => ({ name: s.name.length > 14 ? s.name.slice(0, 14) + ".." : s.name, value: s.value, pct: parseFloat(((s.value / total) * 100).toFixed(1)) }))
      .sort((a, b) => b.pct - a.pct)
      .slice(0, 10);
  }, [analytics]);

  if (loading) {
    return (
      <div className="space-y-6">
        <div className="h-10 bg-white dark:bg-slate-800 rounded-xl w-64 animate-pulse" />
        <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
          {[1, 2, 3, 4, 5].map(i => (
            <div key={i} className="bg-white dark:bg-slate-800 rounded-2xl border border-slate-100 dark:border-slate-700 p-5 h-28 animate-pulse">
              <div className="h-3 bg-slate-100 dark:bg-slate-700 rounded w-20 mb-3" />
              <div className="h-7 bg-slate-100 dark:bg-slate-700 rounded w-28" />
            </div>
          ))}
        </div>
        <div className="bg-white dark:bg-slate-800 rounded-2xl border border-slate-100 dark:border-slate-700 h-72 animate-pulse" />
      </div>
    );
  }

  const isEmpty = !analytics || analytics.holdings_count === 0;

  if (isEmpty) {
    return (
      <div data-testid="empty-dashboard">
        <div className="flex items-center justify-between mb-8">
          <div>
            <h1 className="text-2xl sm:text-3xl font-medium tracking-tight text-slate-900 dark:text-white" style={{ fontFamily: "'Outfit', sans-serif" }}>Welcome to nivesh.ai</h1>
            <p className="text-sm text-slate-500 dark:text-slate-400 mt-1">Start by adding your holdings to get AI-powered insights.</p>
          </div>
        </div>
        <div className="bg-white dark:bg-slate-800 rounded-2xl border border-slate-100 dark:border-slate-700 p-12 text-center">
          <div className="w-16 h-16 bg-emerald-50 dark:bg-emerald-900/20 rounded-2xl flex items-center justify-center mx-auto mb-6">
            <Wallet className="w-8 h-8 text-emerald-600" strokeWidth={1.5} />
          </div>
          <h2 className="text-xl font-medium text-slate-900 dark:text-white mb-2" style={{ fontFamily: "'Outfit', sans-serif" }}>No holdings yet</h2>
          <p className="text-sm text-slate-500 dark:text-slate-400 mb-6">Add your stocks, mutual funds, and other investments to get started.</p>
        </div>
      </div>
    );
  }

  const rPos = analytics.total_returns >= 0;
  const dPos = (analytics.day_change || 0) >= 0;
  const allocationData = analytics.asset_allocation.map(a => ({ ...a, label: ASSET_LABELS[a.name] || a.name }));
  const flags = analytics.data_flags || {};
  const explanations = flags.explanations || {};

  return (
    <div data-testid="dashboard-overview" className="space-y-6">
      {/* ─── HEADER ─── */}
      <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} className="flex flex-col sm:flex-row sm:items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl sm:text-3xl font-medium tracking-tight text-slate-900 dark:text-white" style={{ fontFamily: "'Outfit', sans-serif" }}>
            Portfolio Overview
          </h1>
          <div className="flex items-center gap-2 mt-1">
            <Calendar className="w-3.5 h-3.5 text-slate-400" strokeWidth={1.5} />
            <p className="text-sm text-slate-400">{today}</p>
            <span className="text-slate-300 mx-1">|</span>
            <p className="text-sm text-slate-500 font-medium">{analytics.holdings_count} holdings</p>
            {flags.missing_cmp_count > 0 && (
              <span className="text-[10px] text-amber-600 bg-amber-50 dark:bg-amber-900/20 px-1.5 py-0.5 rounded-md font-medium">
                {flags.missing_cmp_count} missing CMP
              </span>
            )}
          </div>
        </div>
        <div className="flex items-center gap-2">
          <Select value={displayMode} onValueChange={setDisplayMode}>
            <SelectTrigger data-testid="format-toggle" className="w-24 h-9 rounded-xl border-slate-200 dark:border-slate-700 text-xs"><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value="auto">Auto</SelectItem>
              <SelectItem value="l">Lakhs</SelectItem>
              <SelectItem value="cr">Crores</SelectItem>
            </SelectContent>
          </Select>
          <Button data-testid="refresh-button" variant="outline" onClick={onRefresh} className="rounded-xl border-slate-200 text-slate-600 hover:bg-slate-50 h-9 text-sm">
            <RefreshCw className="w-3.5 h-3.5 mr-1.5" strokeWidth={1.5} />Refresh
          </Button>
        </div>
      </motion.div>

      {/* ─── KPI CARDS (5 across) ─── */}
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-4">
        {[
          { label: "Total Invested", value: fmt(analytics.total_invested), testid: "total-invested",
            flag: flags.assumed_cost_count > 0 ? "assumed" : null,
            flagTooltip: explanations.missing_cmp },
          { label: "Current Value", value: fmt(analytics.current_value), testid: "current-value" },
          { label: "Total Returns", value: `${rPos ? "+" : ""}${fmt(Math.abs(analytics.total_returns))}`, sub: `${rPos ? "+" : ""}${analytics.returns_pct.toFixed(1)}%`, color: rPos ? "text-emerald-600" : "text-red-500", icon: rPos ? TrendingUp : TrendingDown, testid: "total-returns",
            flag: flags.assumed_cost_count > 0 ? "assumed" : null,
            flagTooltip: explanations.missing_cmp },
          { label: "Day Change", value: `${dPos ? "+" : ""}${fmt(Math.abs(analytics.day_change || 0))}`, sub: `${dPos ? "+" : ""}${(analytics.day_change_pct || 0).toFixed(2)}%`, color: dPos ? "text-emerald-600" : "text-red-500", icon: dPos ? ArrowUpRight : ArrowDownRight, testid: "day-change",
            flag: "simulated",
            flagTooltip: explanations.day_change },
          { label: "Risk Score", value: analytics.risk_label, sub: `${analytics.risk_score}/100`, icon: AlertTriangle, color: analytics.risk_score < 30 ? "text-emerald-600" : analytics.risk_score < 60 ? "text-amber-500" : "text-red-500", testid: "risk-score", bar: analytics.risk_score,
            infoTooltip: explanations.risk_score },
        ].map((kpi, i) => (
          <motion.div key={kpi.label} initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i * 0.04 }}>
            <Card className="bg-white dark:bg-slate-800 border-slate-100 dark:border-slate-700 rounded-2xl shadow-none hover:shadow-lg hover:border-slate-200 dark:hover:border-slate-600 transition-all duration-300 h-full">
              <CardContent className="p-5">
                <div className="flex items-center gap-1">
                  <p className="text-[10px] font-bold tracking-[0.15em] uppercase text-slate-400 mb-2">{kpi.label}</p>
                  {kpi.infoTooltip && <InfoTooltip text={kpi.infoTooltip}><Info className="w-3 h-3 text-slate-400 hover:text-slate-600 cursor-help mb-2" /></InfoTooltip>}
                </div>
                <div className="flex items-center gap-1.5">
                  {kpi.icon && <kpi.icon className={`w-4 h-4 ${kpi.color}`} strokeWidth={1.5} />}
                  <p className={`text-xl font-semibold ${kpi.color || "text-slate-900 dark:text-white"}`} style={{ fontFamily: "'Outfit', sans-serif" }} data-testid={kpi.testid}>
                    {kpi.value}
                  </p>
                </div>
                {kpi.sub && <p className={`text-xs mt-0.5 ${kpi.color || "text-slate-500"}`}>{kpi.sub}</p>}
                {kpi.flag && (
                  <SimulatedBadge
                    label={kpi.flag === "simulated" ? "Simulated" : "Needs Data"}
                    tooltip={kpi.flagTooltip}
                  />
                )}
                {kpi.bar !== undefined && (
                  <div className="mt-2 w-full h-1.5 rounded-full bg-slate-100 overflow-hidden">
                    <div className="h-full rounded-full" style={{ width: `${kpi.bar}%`, background: "linear-gradient(90deg, #10B981 0%, #F59E0B 50%, #EF4444 100%)" }} data-testid="risk-bar" />
                  </div>
                )}
              </CardContent>
            </Card>
          </motion.div>
        ))}
      </div>

      {/* ─── HEALTH SCORE + RECOMMENDATIONS ─── */}
      {analytics.health_score && analytics.health_score.overall > 0 && (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          {/* Health Score */}
          <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.2 }}>
            <Card className="bg-white dark:bg-slate-800 border-slate-100 dark:border-slate-700 rounded-2xl shadow-none h-full" data-testid="health-score-card">
              <CardContent className="p-6">
                <div className="flex items-center gap-1">
                  <h3 className="text-sm font-medium text-slate-900 dark:text-white mb-4" style={{ fontFamily: "'Outfit', sans-serif" }}>Portfolio Health</h3>
                  <InfoTooltip text={explanations.health_overall || "Overall portfolio health score based on diversification, risk management, cost efficiency, and performance."}>
                    <Info className="w-3.5 h-3.5 text-slate-400 hover:text-slate-600 cursor-help mb-4 ml-1" />
                  </InfoTooltip>
                </div>
                <div className="flex items-center justify-center mb-4">
                  <div className="relative w-28 h-28">
                    <svg className="w-28 h-28 transform -rotate-90" viewBox="0 0 100 100">
                      <circle cx="50" cy="50" r="42" fill="none" stroke="#E2E8F0" strokeWidth="8" />
                      <circle cx="50" cy="50" r="42" fill="none" stroke={analytics.health_score.overall >= 70 ? "#10B981" : analytics.health_score.overall >= 50 ? "#F59E0B" : "#EF4444"} strokeWidth="8" strokeLinecap="round"
                        strokeDasharray={`${analytics.health_score.overall * 2.64} 264`} />
                    </svg>
                    <div className="absolute inset-0 flex flex-col items-center justify-center">
                      <span className="text-2xl font-bold text-slate-900 dark:text-white" style={{ fontFamily: "'Outfit', sans-serif" }}>{analytics.health_score.grade}</span>
                      <span className="text-[10px] text-slate-400">{analytics.health_score.overall}/100</span>
                    </div>
                  </div>
                </div>
                <div className="space-y-2">
                  {[
                    { label: "Diversification", val: analytics.health_score.diversification, color: "#3B82F6", tooltip: explanations.health_diversification },
                    { label: "Risk Management", val: analytics.health_score.risk, color: "#10B981", tooltip: explanations.health_risk },
                    { label: "Cost Efficiency", val: analytics.health_score.cost_efficiency, color: "#F59E0B", tooltip: explanations.health_cost },
                    { label: "Performance", val: analytics.health_score.performance, color: "#8B5CF6", tooltip: explanations.health_performance },
                  ].map(item => (
                    <div key={item.label}>
                      <div className="flex justify-between text-[10px] mb-0.5">
                        <span className="text-slate-500 dark:text-slate-400 flex items-center gap-0.5">
                          {item.label}
                          {item.tooltip && <InfoTooltip text={item.tooltip}><Info className="w-2.5 h-2.5 text-slate-400 hover:text-slate-600 cursor-help" /></InfoTooltip>}
                        </span>
                        <span className="font-medium text-slate-700 dark:text-slate-300">{item.val}</span>
                      </div>
                      <div className="w-full h-1.5 rounded-full bg-slate-100 dark:bg-slate-700 overflow-hidden">
                        <div className="h-full rounded-full transition-all duration-700" style={{ width: `${item.val}%`, backgroundColor: item.color }} />
                      </div>
                    </div>
                  ))}
                </div>
              </CardContent>
            </Card>
          </motion.div>

          {/* Risk Warnings */}
          {analytics.risk_analysis && (analytics.risk_analysis.warnings?.length > 0 || analytics.risk_analysis.risk_factors?.length > 0) && (
            <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.24 }}>
              <Card className="bg-white dark:bg-slate-800 border-slate-100 dark:border-slate-700 rounded-2xl shadow-none h-full">
                <CardContent className="p-6">
                  <h3 className="text-sm font-medium text-slate-900 dark:text-white mb-4 flex items-center gap-2" style={{ fontFamily: "'Outfit', sans-serif" }}>
                    <AlertTriangle className="w-4 h-4 text-amber-500" /> Risk Analysis
                    <InfoTooltip text={explanations.risk_score || "Risk factors detected in your portfolio"}>
                      <Info className="w-3 h-3 text-slate-400 hover:text-slate-600 cursor-help" />
                    </InfoTooltip>
                  </h3>
                  {/* Risk Factors with drilldown */}
                  {analytics.risk_analysis.risk_factors?.length > 0 && (
                    <div className="space-y-2 mb-3">
                      {analytics.risk_analysis.risk_factors.map((rf, i) => (
                        <div key={i}
                          className={`p-2.5 rounded-lg border cursor-pointer transition-all hover:shadow-sm ${
                            rf.severity === "high" ? "border-red-200 bg-red-50/50 dark:bg-red-900/10 dark:border-red-800" :
                            "border-amber-200 bg-amber-50/50 dark:bg-amber-900/10 dark:border-amber-800"
                          }`}
                          onClick={() => {
                            if (rf.holdings?.length > 0) {
                              const matched = holdings.filter(h => rf.holdings.some(rh => h.name.startsWith(rh.name?.slice(0, 20))));
                              if (matched.length > 0) setDrilldown({ title: rf.factor, holdings: matched });
                            }
                          }}
                        >
                          <div className="flex items-center justify-between">
                            <span className="text-xs font-medium text-slate-900 dark:text-white">{rf.factor}</span>
                            <span className={`text-[9px] font-bold uppercase tracking-wider px-1.5 py-0.5 rounded ${
                              rf.severity === "high" ? "bg-red-100 text-red-600 dark:bg-red-900/30 dark:text-red-400" : "bg-amber-100 text-amber-600 dark:bg-amber-900/30 dark:text-amber-400"
                            }`}>{rf.severity}</span>
                          </div>
                          <p className="text-[10px] text-slate-500 dark:text-slate-400 mt-1">{rf.description}</p>
                          {rf.holdings?.length > 0 && (
                            <p className="text-[9px] text-slate-400 mt-1">{rf.holdings.length} holding(s) — click to view</p>
                          )}
                        </div>
                      ))}
                    </div>
                  )}
                  {/* Warning list */}
                  <div className="space-y-2">
                    {analytics.risk_analysis.warnings?.map((w, i) => (
                      <div key={i} className="flex items-start gap-2.5 text-sm">
                        <div className="w-1.5 h-1.5 rounded-full bg-amber-500 mt-1.5 flex-shrink-0" />
                        <p className="text-slate-600 dark:text-slate-400 text-xs leading-relaxed">{w}</p>
                      </div>
                    ))}
                  </div>
                </CardContent>
              </Card>
            </motion.div>
          )}

          {/* Smart Recommendations */}
          {analytics.recommendations?.length > 0 && (
            <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.28 }}>
              <Card className="bg-white dark:bg-slate-800 border-slate-100 dark:border-slate-700 rounded-2xl shadow-none h-full">
                <CardContent className="p-6">
                  <h3 className="text-sm font-medium text-slate-900 dark:text-white mb-4 flex items-center gap-2" style={{ fontFamily: "'Outfit', sans-serif" }}>
                    <Sparkles className="w-4 h-4 text-emerald-600" /> Recommendations
                  </h3>
                  <div className="space-y-3">
                    {analytics.recommendations.map((r, i) => (
                      <div key={i} className={`p-3 rounded-xl border ${r.priority === "high" ? "border-red-200 bg-red-50/50 dark:bg-red-900/10 dark:border-red-800" : "border-slate-200 bg-slate-50/50 dark:bg-slate-800/50 dark:border-slate-700"}`}>
                        <div className="flex items-center justify-between mb-1">
                          <span className="text-xs font-medium text-slate-900 dark:text-white">{r.title}</span>
                          <span className="text-[9px] font-bold uppercase tracking-wider text-emerald-600 bg-emerald-50 dark:bg-emerald-900/30 px-1.5 py-0.5 rounded">{r.impact}</span>
                        </div>
                        <p className="text-[10px] text-slate-500 dark:text-slate-400 leading-relaxed">{r.description?.slice(0, 120)}{r.description?.length > 120 ? "..." : ""}</p>
                      </div>
                    ))}
                  </div>
                </CardContent>
              </Card>
            </motion.div>
          )}
        </div>
      )}

      {/* ─── PERFORMANCE TREND (FULL WIDTH LINE CHART) ─── */}
      {analytics.performance_trend?.length > 0 && (
        <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.22 }}>
          <Card className="bg-white dark:bg-slate-800 border-slate-100 dark:border-slate-700 rounded-2xl shadow-none" data-testid="performance-trend-chart">
            <CardContent className="p-6 md:p-8">
              <div className="flex items-center justify-between mb-6">
                <div className="flex items-center gap-2">
                  <h3 className="text-lg font-medium text-slate-900 dark:text-white" style={{ fontFamily: "'Outfit', sans-serif" }}>
                    Portfolio Performance
                  </h3>
                  {flags.performance_trend_simulated && (
                    <SimulatedBadge label="Modeled" tooltip={explanations.performance_trend} />
                  )}
                </div>
                <span className="text-xs text-slate-400 font-medium">Last 30 days</span>
              </div>
              <div className="h-64">
                <ResponsiveContainer width="100%" height="100%">
                  <AreaChart data={analytics.performance_trend} margin={{ top: 5, right: 10, left: 10, bottom: 0 }}>
                    <defs>
                      <linearGradient id="trendGrad" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="5%" stopColor="#059669" stopOpacity={0.15} />
                        <stop offset="95%" stopColor="#059669" stopOpacity={0} />
                      </linearGradient>
                    </defs>
                    <CartesianGrid strokeDasharray="3 3" stroke="#F1F5F9" vertical={false} />
                    <XAxis dataKey="date" axisLine={false} tickLine={false} tick={{ fontSize: 11, fill: "#94A3B8" }} interval="preserveStartEnd" />
                    <YAxis axisLine={false} tickLine={false} tick={{ fontSize: 11, fill: "#94A3B8" }} tickFormatter={(v) => fmtShort(v)} width={55} />
                    <RechartsTooltip
                      contentStyle={{ borderRadius: 12, border: "1px solid #E2E8F0", boxShadow: "0 4px 12px rgba(0,0,0,0.08)", fontFamily: "'Figtree', sans-serif", fontSize: 13 }}
                      formatter={(v) => [fmt(v), "Value"]}
                    />
                    <Area type="monotone" dataKey="value" stroke="#059669" strokeWidth={2.5} fill="url(#trendGrad)" dot={false} activeDot={{ r: 5, fill: "#059669", strokeWidth: 0 }} />
                  </AreaChart>
                </ResponsiveContainer>
              </div>
            </CardContent>
          </Card>
        </motion.div>
      )}

      {/* ─── ASSET ALLOCATION (DONUT) | SECTOR EXPOSURE (BAR) ─── */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.28 }}>
          <Card className="bg-white dark:bg-slate-800 border-slate-100 dark:border-slate-700 rounded-2xl shadow-none h-full" data-testid="asset-allocation-chart">
            <CardContent className="p-6 md:p-8">
              <h3 className="text-lg font-medium text-slate-900 dark:text-white mb-1" style={{ fontFamily: "'Outfit', sans-serif" }}>Asset Allocation</h3>
              <p className="text-[10px] text-slate-400 mb-5">Click a segment to view details</p>
              <div className="flex items-center gap-6">
                <div className="w-44 h-44 flex-shrink-0 cursor-pointer">
                  <ResponsiveContainer width="100%" height="100%">
                    <PieChart>
                      <Pie data={allocationData} cx="50%" cy="50%" innerRadius={48} outerRadius={72} paddingAngle={3} dataKey="value" nameKey="label"
                        onClick={(data) => {
                          const assetKey = data?.name || data?.payload?.name;
                          const filtered = holdings.filter(h => h.asset_type === assetKey || ASSET_LABELS[h.asset_type] === assetKey);
                          if (filtered.length > 0) setDrilldown({ title: ASSET_LABELS[assetKey] || assetKey, holdings: filtered });
                        }}>
                        {allocationData.map((_, i) => <Cell key={i} fill={COLORS[i % COLORS.length]} className="cursor-pointer hover:opacity-80 transition-opacity" />)}
                      </Pie>
                      <RechartsTooltip formatter={(v) => fmt(v)} />
                    </PieChart>
                  </ResponsiveContainer>
                </div>
                <div className="flex-1 space-y-2.5">
                  {allocationData.map((a, i) => {
                    const pct = analytics.current_value > 0 ? ((a.value / analytics.current_value) * 100).toFixed(1) : 0;
                    return (
                      <div key={a.name} className="flex items-center justify-between cursor-pointer hover:bg-slate-50 dark:hover:bg-slate-800 rounded-lg px-2 py-1 -mx-2 transition-colors"
                        onClick={() => {
                          const filtered = holdings.filter(h => h.asset_type === a.name);
                          if (filtered.length > 0) setDrilldown({ title: a.label, holdings: filtered });
                        }}>
                        <div className="flex items-center gap-2">
                          <div className="w-2.5 h-2.5 rounded-full" style={{ backgroundColor: COLORS[i % COLORS.length] }} />
                          <span className="text-sm text-slate-600 dark:text-slate-400">{a.label}</span>
                        </div>
                        <div className="text-right">
                          <span className="text-sm font-medium text-slate-900 dark:text-white">{pct}%</span>
                          <span className="text-xs text-slate-400 ml-2">{fmt(a.value)}</span>
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>
            </CardContent>
          </Card>
        </motion.div>

        <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.32 }}>
          <Card className="bg-white dark:bg-slate-800 border-slate-100 dark:border-slate-700 rounded-2xl shadow-none h-full" data-testid="sector-exposure-chart">
            <CardContent className="p-6 md:p-8">
              <h3 className="text-lg font-medium text-slate-900 dark:text-white mb-1" style={{ fontFamily: "'Outfit', sans-serif" }}>Sector Exposure</h3>
              <p className="text-[10px] text-slate-400 mb-5">Equity holdings only &middot; Click a bar to view holdings</p>
              {sectorBarData.length > 0 ? (
                <div className="h-64 cursor-pointer">
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={sectorBarData} layout="vertical" margin={{ top: 0, right: 10, left: 0, bottom: 0 }}
                      onClick={(data) => {
                        if (data?.activePayload?.[0]) {
                          const sectorName = data.activePayload[0].payload.name;
                          const filtered = holdings.filter(h => (h.sector || "Other").startsWith(sectorName.replace("..","")));
                          if (filtered.length > 0) setDrilldown({ title: `Sector: ${sectorName}`, holdings: filtered });
                        }
                      }}>
                      <CartesianGrid strokeDasharray="3 3" stroke="#F1F5F9" horizontal={false} />
                      <XAxis type="number" axisLine={false} tickLine={false} tick={{ fontSize: 10, fill: "#94A3B8" }} tickFormatter={(v) => `${v}%`} />
                      <YAxis type="category" dataKey="name" axisLine={false} tickLine={false} tick={{ fontSize: 11, fill: "#64748B" }} width={100} />
                      <RechartsTooltip formatter={(v) => [`${v}%`, "Allocation"]} contentStyle={{ borderRadius: 12, border: "1px solid #E2E8F0", fontSize: 13 }} />
                      <Bar dataKey="pct" radius={[0, 6, 6, 0]} barSize={18} className="cursor-pointer">
                        {sectorBarData.map((_, i) => <Cell key={i} fill={COLORS[i % COLORS.length]} />)}
                      </Bar>
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              ) : (
                <p className="text-sm text-slate-400 text-center py-10">No sector data</p>
              )}
            </CardContent>
          </Card>
        </motion.div>
      </div>

      {/* ─── STOCK HEATMAP (FULL WIDTH TREEMAP) ─── */}
      {analytics.heatmap_data?.length > 0 && (
        <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.38 }}>
          <Card className="bg-white dark:bg-slate-800 border-slate-100 dark:border-slate-700 rounded-2xl shadow-none" data-testid="stock-heatmap">
            <CardContent className="p-6 md:p-8">
              <div className="flex items-center justify-between mb-6">
                <div>
                  <h3 className="text-lg font-medium text-slate-900 dark:text-white" style={{ fontFamily: "'Outfit', sans-serif" }}>
                    Holdings Heatmap
                  </h3>
                  <p className="text-[10px] text-slate-400 mt-0.5">Click a holding to view details</p>
                </div>
                <div className="flex items-center gap-3 text-[10px] font-bold tracking-wider uppercase">
                  <div className="flex items-center gap-1"><div className="w-3 h-3 rounded bg-red-400/60" />Loss</div>
                  <div className="flex items-center gap-1"><div className="w-3 h-3 rounded bg-emerald-400/40" />Low</div>
                  <div className="flex items-center gap-1"><div className="w-3 h-3 rounded bg-emerald-500/80" />High</div>
                </div>
              </div>
              <div className="h-80 rounded-xl overflow-hidden">
                <ResponsiveContainer width="100%" height="100%">
                  <Treemap
                    data={analytics.heatmap_data}
                    dataKey="value"
                    nameKey="name"
                    content={<HeatmapCell />}
                    animationDuration={400}
                    onClick={(node) => {
                      if (node?.name) {
                        const matched = holdings.filter(h => h.name.startsWith(node.name.replace("...", "").slice(0, 20)));
                        if (matched.length > 0) {
                          setDrilldown({ title: matched[0].name, holdings: matched });
                        } else {
                          // Show single holding detail
                          const h = analytics.heatmap_data.find(d => d.name === node.name);
                          if (h) {
                            const assetHoldings = holdings.filter(hld => hld.asset_type === h.asset_type);
                            setDrilldown({ title: `${ASSET_LABELS[h.asset_type] || h.asset_type} Holdings`, holdings: assetHoldings });
                          }
                        }
                      }
                    }}
                  >
                    <RechartsTooltip 
                      content={({ payload }) => {
                        if (!payload?.[0]?.payload) return null;
                        const d = payload[0].payload;
                        const rp = d.return_pct ?? 0;
                        const pos = rp >= 0;
                        return (
                          <div className="bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-xl shadow-lg p-3 text-xs">
                            <p className="font-medium text-slate-900 dark:text-white mb-1">{d.name}</p>
                            {d.ticker && <p className="text-slate-400 text-[10px] mb-1">{d.ticker}</p>}
                            <p className="text-slate-600 dark:text-slate-300">Value: {fmt(d.value)}</p>
                            <p className={pos ? "text-emerald-600" : "text-red-500"}>Return: {pos ? "+" : ""}{rp}%</p>
                            <p className="text-slate-400">{d.sector} &middot; {ASSET_LABELS[d.asset_type] || d.asset_type}</p>
                          </div>
                        );
                      }}
                    />
                  </Treemap>
                </ResponsiveContainer>
              </div>
            </CardContent>
          </Card>
        </motion.div>
      )}

      {/* ─── AI INSIGHTS + RECOMMENDATIONS ─── */}
      <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.44 }}>
        <Card className="bg-white dark:bg-slate-800 border-slate-100 dark:border-slate-700 rounded-2xl shadow-none" data-testid="insights-preview">
          <CardContent className="p-6 md:p-8">
            <div className="flex items-center justify-between mb-6">
              <h3 className="text-lg font-medium text-slate-900 dark:text-white flex items-center gap-2" style={{ fontFamily: "'Outfit', sans-serif" }}>
                <Sparkles className="w-5 h-5 text-emerald-600" strokeWidth={1.5} />
                AI Insights & Recommendations
              </h3>
              {insights.length === 0 && (
                <p className="text-xs text-slate-400">Go to Insights tab to generate</p>
              )}
            </div>
            {insights.length > 0 ? (
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                {insights.slice(0, 4).map((ins) => (
                  <div
                    key={ins.insight_id}
                    className={`p-4 rounded-xl border transition-all duration-200 hover:shadow-md ${
                      ins.type === "warning" ? "border-amber-200 bg-amber-50/80" :
                      ins.type === "opportunity" ? "border-emerald-200 bg-emerald-50/80" :
                      ins.type === "action" ? "border-blue-200 bg-blue-50/80" :
                      "border-slate-200 bg-slate-50/80"
                    }`}
                  >
                    <div className="flex items-start gap-3">
                      <div className={`w-6 h-6 rounded-lg flex items-center justify-center flex-shrink-0 mt-0.5 ${
                        ins.type === "warning" ? "bg-amber-100" : ins.type === "opportunity" ? "bg-emerald-100" : ins.type === "action" ? "bg-blue-100" : "bg-slate-100"
                      }`}>
                        {ins.type === "warning" ? <AlertTriangle className="w-3.5 h-3.5 text-amber-600" /> :
                         ins.type === "opportunity" ? <TrendingUp className="w-3.5 h-3.5 text-emerald-600" /> :
                         ins.type === "action" ? <BarChart3 className="w-3.5 h-3.5 text-blue-600" /> :
                         <Sparkles className="w-3.5 h-3.5 text-slate-500" />}
                      </div>
                      <div>
                        <p className="text-sm font-medium text-slate-900 mb-0.5">{ins.title}</p>
                        <p className="text-xs text-slate-500 leading-relaxed">{ins.description}</p>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <div className="text-center py-8">
                <p className="text-sm text-slate-400">Add holdings and generate AI insights from the Insights tab</p>
              </div>
            )}
          </CardContent>
        </Card>
      </motion.div>

      {/* ─── BEST & WORST (Separated by Equity/MF with Show More) ─── */}
      <BestWorstSection analytics={analytics} holdings={holdings} fmt={fmt} setDrilldown={setDrilldown} />

      {/* Drilldown Modal */}
      <DrilldownModal
        open={!!drilldown}
        onClose={() => setDrilldown(null)}
        title={drilldown?.title || ""}
        holdings={drilldown?.holdings || []}
      />
    </div>
  );
};

// ── Best & Worst Section with Equity/MF tabs and Show More ──
const BestWorstSection = ({ analytics, holdings, fmt, setDrilldown }) => {
  const [moverTab, setMoverTab] = useState("all");
  const [showAllGainers, setShowAllGainers] = useState(false);
  const [showAllLosers, setShowAllLosers] = useState(false);

  const allGainers = analytics.top_gainers || [];
  const allLosers = analytics.top_losers || [];

  const filteredGainers = useMemo(() => {
    if (moverTab === "all") return allGainers;
    if (moverTab === "equity") return allGainers.filter(g => g.asset_type === "equity");
    return allGainers.filter(g => g.asset_type === "mutual_fund");
  }, [allGainers, moverTab]);

  const filteredLosers = useMemo(() => {
    if (moverTab === "all") return allLosers;
    if (moverTab === "equity") return allLosers.filter(l => l.asset_type === "equity");
    return allLosers.filter(l => l.asset_type === "mutual_fund");
  }, [allLosers, moverTab]);

  const INITIAL_COUNT = 5;
  const visibleGainers = showAllGainers ? filteredGainers : filteredGainers.slice(0, INITIAL_COUNT);
  const visibleLosers = showAllLosers ? filteredLosers : filteredLosers.slice(0, INITIAL_COUNT);

  if (allGainers.length === 0 && allLosers.length === 0) return null;

  const MoverRow = ({ item, positive }) => (
    <div
      className={`flex items-center justify-between py-1.5 cursor-pointer rounded-lg px-2 -mx-2 transition-colors ${
        positive ? "hover:bg-emerald-50 dark:hover:bg-emerald-900/10" : "hover:bg-red-50 dark:hover:bg-red-900/10"
      }`}
      onClick={() => {
        const matched = holdings.filter(h => h.name === item.name);
        if (matched.length) setDrilldown({ title: item.name, holdings: matched });
      }}
      data-testid={`mover-${positive ? "gainer" : "loser"}-${item.name?.slice(0,10)}`}
    >
      <div className="flex items-center gap-2 flex-1 min-w-0">
        <span className="text-sm text-slate-600 dark:text-slate-300 truncate">{item.name}</span>
        <span className="text-[9px] font-medium bg-slate-100 dark:bg-slate-700 text-slate-500 px-1.5 py-0.5 rounded-full flex-shrink-0 uppercase">
          {item.asset_type === "mutual_fund" ? "MF" : item.asset_type === "equity" ? "EQ" : item.asset_type?.toUpperCase()?.slice(0,3)}
        </span>
      </div>
      <div className="flex items-center gap-2 flex-shrink-0 ml-2">
        <span className="text-xs text-slate-400">{fmt(item.value)}</span>
        <span className={`text-sm font-medium px-2 py-0.5 rounded-lg ${
          positive ? "text-emerald-600 bg-emerald-50 dark:bg-emerald-900/20" : "text-red-500 bg-red-50 dark:bg-red-900/20"
        }`}>
          {positive ? "+" : ""}{item.pct_change}%
        </span>
      </div>
    </div>
  );

  return (
    <div>
      {/* Tab filter */}
      <div className="flex items-center gap-2 mb-4" data-testid="movers-tabs">
        {[
          { id: "all", label: "All" },
          { id: "equity", label: "Equity" },
          { id: "mutual_fund", label: "Mutual Funds" },
        ].map(t => (
          <button
            key={t.id}
            onClick={() => { setMoverTab(t.id); setShowAllGainers(false); setShowAllLosers(false); }}
            className={`px-3 py-1.5 text-xs font-medium rounded-lg transition-all ${
              moverTab === t.id
                ? "bg-slate-900 dark:bg-white text-white dark:text-slate-900 shadow-sm"
                : "text-slate-500 hover:text-slate-700 dark:hover:text-slate-300 bg-slate-100 dark:bg-slate-800"
            }`}
            data-testid={`movers-tab-${t.id}`}
          >
            {t.label}
          </button>
        ))}
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {/* Gainers */}
        {filteredGainers.length > 0 && (
          <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.5 }}>
            <Card className="bg-white dark:bg-slate-800 border-slate-100 dark:border-slate-700 rounded-2xl shadow-none">
              <CardContent className="p-6">
                <h3 className="text-base font-medium text-slate-900 dark:text-white mb-4 flex items-center gap-2" style={{ fontFamily: "'Outfit', sans-serif" }}>
                  <TrendingUp className="w-4 h-4 text-emerald-600" /> Best Performers
                  <span className="text-[10px] text-slate-400 font-normal ml-auto">{filteredGainers.length} holdings</span>
                </h3>
                <div className="space-y-1" data-testid="gainers-list">
                  {visibleGainers.map((g, i) => <MoverRow key={i} item={g} positive />)}
                </div>
                {filteredGainers.length > INITIAL_COUNT && (
                  <button
                    onClick={() => setShowAllGainers(!showAllGainers)}
                    className="mt-3 w-full flex items-center justify-center gap-1 text-xs font-medium text-emerald-600 hover:text-emerald-700 py-1.5 rounded-lg hover:bg-emerald-50 dark:hover:bg-emerald-900/10 transition-colors"
                    data-testid="show-more-gainers"
                  >
                    {showAllGainers ? "Show Less" : `Show All ${filteredGainers.length}`}
                    <ChevronDown className={`w-3.5 h-3.5 transition-transform ${showAllGainers ? "rotate-180" : ""}`} />
                  </button>
                )}
              </CardContent>
            </Card>
          </motion.div>
        )}

        {/* Losers */}
        {filteredLosers.length > 0 && (
          <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.54 }}>
            <Card className="bg-white dark:bg-slate-800 border-slate-100 dark:border-slate-700 rounded-2xl shadow-none">
              <CardContent className="p-6">
                <h3 className="text-base font-medium text-slate-900 dark:text-white mb-4 flex items-center gap-2" style={{ fontFamily: "'Outfit', sans-serif" }}>
                  <TrendingDown className="w-4 h-4 text-red-500" /> Worst Performers
                  <span className="text-[10px] text-slate-400 font-normal ml-auto">{filteredLosers.length} holdings</span>
                </h3>
                <div className="space-y-1" data-testid="losers-list">
                  {visibleLosers.map((l, i) => <MoverRow key={i} item={l} positive={false} />)}
                </div>
                {filteredLosers.length > INITIAL_COUNT && (
                  <button
                    onClick={() => setShowAllLosers(!showAllLosers)}
                    className="mt-3 w-full flex items-center justify-center gap-1 text-xs font-medium text-red-500 hover:text-red-600 py-1.5 rounded-lg hover:bg-red-50 dark:hover:bg-red-900/10 transition-colors"
                    data-testid="show-more-losers"
                  >
                    {showAllLosers ? "Show Less" : `Show All ${filteredLosers.length}`}
                    <ChevronDown className={`w-3.5 h-3.5 transition-transform ${showAllLosers ? "rotate-180" : ""}`} />
                  </button>
                )}
              </CardContent>
            </Card>
          </motion.div>
        )}

        {/* Empty state for filtered view */}
        {filteredGainers.length === 0 && filteredLosers.length === 0 && (
          <div className="col-span-2 text-center py-6 text-sm text-slate-400">
            No {moverTab === "equity" ? "equity" : "mutual fund"} holdings with P&L data
          </div>
        )}
      </div>
    </div>
  );
};

export default DashboardOverview;
