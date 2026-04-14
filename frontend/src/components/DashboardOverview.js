import React, { useMemo, useState } from "react";
import { TrendingUp, TrendingDown, Wallet, AlertTriangle, RefreshCw, Calendar, Sparkles, ArrowUpRight, ArrowDownRight, BarChart3 } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import {
  PieChart, Pie, Cell, ResponsiveContainer, Tooltip,
  AreaChart, Area, XAxis, YAxis, CartesianGrid,
  BarChart, Bar,
  Treemap,
} from "recharts";
import { motion } from "framer-motion";
import { useNumberFormat } from "@/context/NumberFormatContext";
import DrilldownModal from "@/components/DrilldownModal";

const COLORS = ["#059669", "#3B82F6", "#F59E0B", "#8B5CF6", "#EF4444", "#EC4899", "#14B8A6", "#F97316", "#6366F1", "#84CC16"];

const ASSET_LABELS = {
  equity: "Equity", mutual_fund: "Mutual Funds", etf: "ETF",
  bond: "Bonds", gold: "Gold", fd: "Fixed Deposit", other: "Other",
};

// Custom Treemap content for heatmap
const HeatmapCell = ({ x, y, width, height, name, return_pct, value }) => {
  if (width < 4 || height < 4) return null;
  const isPositive = return_pct >= 0;
  const intensity = Math.min(Math.abs(return_pct) / 50, 1);
  const bg = isPositive
    ? `rgba(16, 185, 129, ${0.15 + intensity * 0.55})`
    : `rgba(239, 68, 68, ${0.15 + intensity * 0.55})`;
  const textColor = intensity > 0.4 ? "#fff" : isPositive ? "#065F46" : "#991B1B";
  const showName = width > 60 && height > 30;
  const showPct = width > 40 && height > 20;

  return (
    <g>
      <rect x={x} y={y} width={width} height={height} fill={bg} stroke="#F8FAFC" strokeWidth={2} rx={6} />
      {showName && (
        <text x={x + width / 2} y={y + height / 2 - (showPct ? 6 : 0)} textAnchor="middle" fill={textColor} fontSize={width > 100 ? 11 : 9} fontFamily="'Figtree', sans-serif" fontWeight={500}>
          {name?.length > (width > 100 ? 20 : 12) ? name.slice(0, width > 100 ? 20 : 12) + "..." : name}
        </text>
      )}
      {showPct && (
        <text x={x + width / 2} y={y + height / 2 + 12} textAnchor="middle" fill={textColor} fontSize={10} fontFamily="'JetBrains Mono', monospace" fontWeight={600}>
          {isPositive ? "+" : ""}{return_pct}%
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
        <div className="h-10 bg-white rounded-xl w-64 animate-pulse" />
        <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
          {[1, 2, 3, 4, 5].map(i => (
            <div key={i} className="bg-white rounded-2xl border border-slate-100 p-5 h-28 animate-pulse">
              <div className="h-3 bg-slate-100 rounded w-20 mb-3" />
              <div className="h-7 bg-slate-100 rounded w-28" />
            </div>
          ))}
        </div>
        <div className="bg-white rounded-2xl border border-slate-100 h-72 animate-pulse" />
      </div>
    );
  }

  const isEmpty = !analytics || analytics.holdings_count === 0;

  if (isEmpty) {
    return (
      <div data-testid="empty-dashboard">
        <div className="flex items-center justify-between mb-8">
          <div>
            <h1 className="text-2xl sm:text-3xl font-medium tracking-tight text-slate-900" style={{ fontFamily: "'Outfit', sans-serif" }}>Welcome to nivesh.ai</h1>
            <p className="text-sm text-slate-500 mt-1">Start by adding your holdings to get AI-powered insights.</p>
          </div>
        </div>
        <div className="bg-white rounded-2xl border border-slate-100 p-12 text-center">
          <div className="w-16 h-16 bg-emerald-50 rounded-2xl flex items-center justify-center mx-auto mb-6">
            <Wallet className="w-8 h-8 text-emerald-600" strokeWidth={1.5} />
          </div>
          <h2 className="text-xl font-medium text-slate-900 mb-2" style={{ fontFamily: "'Outfit', sans-serif" }}>No holdings yet</h2>
          <p className="text-sm text-slate-500 mb-6">Add your stocks, mutual funds, and other investments to get started.</p>
        </div>
      </div>
    );
  }

  const rPos = analytics.total_returns >= 0;
  const dPos = (analytics.day_change || 0) >= 0;
  const allocationData = analytics.asset_allocation.map(a => ({ ...a, label: ASSET_LABELS[a.name] || a.name }));

  return (
    <div data-testid="dashboard-overview" className="space-y-6">
      {/* ─── HEADER ─── */}
      <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} className="flex flex-col sm:flex-row sm:items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl sm:text-3xl font-medium tracking-tight text-slate-900" style={{ fontFamily: "'Outfit', sans-serif" }}>
            Portfolio Overview
          </h1>
          <div className="flex items-center gap-2 mt-1">
            <Calendar className="w-3.5 h-3.5 text-slate-400" strokeWidth={1.5} />
            <p className="text-sm text-slate-400">{today}</p>
            <span className="text-slate-300 mx-1">|</span>
            <p className="text-sm text-slate-500 font-medium">{analytics.holdings_count} holdings</p>
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
          { label: "Total Invested", value: fmt(analytics.total_invested), testid: "total-invested" },
          { label: "Current Value", value: fmt(analytics.current_value), testid: "current-value" },
          { label: "Total Returns", value: `${rPos ? "+" : ""}${fmt(Math.abs(analytics.total_returns))}`, sub: `${rPos ? "+" : ""}${analytics.returns_pct.toFixed(1)}%`, color: rPos ? "text-emerald-600" : "text-red-500", icon: rPos ? TrendingUp : TrendingDown, testid: "total-returns" },
          { label: "Day Change", value: `${dPos ? "+" : ""}${fmt(Math.abs(analytics.day_change || 0))}`, sub: `${dPos ? "+" : ""}${(analytics.day_change_pct || 0).toFixed(2)}%`, color: dPos ? "text-emerald-600" : "text-red-500", icon: dPos ? ArrowUpRight : ArrowDownRight, testid: "day-change" },
          { label: "Risk Score", value: analytics.risk_label, sub: `${analytics.risk_score}/100`, icon: AlertTriangle, color: analytics.risk_score < 30 ? "text-emerald-600" : analytics.risk_score < 60 ? "text-amber-500" : "text-red-500", testid: "risk-score", bar: analytics.risk_score },
        ].map((kpi, i) => (
          <motion.div key={kpi.label} initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i * 0.04 }}>
            <Card className="bg-white border-slate-100 rounded-2xl shadow-none hover:shadow-lg hover:border-slate-200 transition-all duration-300 h-full">
              <CardContent className="p-5">
                <p className="text-[10px] font-bold tracking-[0.15em] uppercase text-slate-400 mb-2">{kpi.label}</p>
                <div className="flex items-center gap-1.5">
                  {kpi.icon && <kpi.icon className={`w-4 h-4 ${kpi.color}`} strokeWidth={1.5} />}
                  <p className={`text-xl font-semibold ${kpi.color || "text-slate-900"}`} style={{ fontFamily: "'Outfit', sans-serif" }} data-testid={kpi.testid}>
                    {kpi.value}
                  </p>
                </div>
                {kpi.sub && <p className={`text-xs mt-0.5 ${kpi.color || "text-slate-500"}`}>{kpi.sub}</p>}
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

      {/* ─── PERFORMANCE TREND (FULL WIDTH LINE CHART) ─── */}
      {analytics.performance_trend?.length > 0 && (
        <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.22 }}>
          <Card className="bg-white border-slate-100 rounded-2xl shadow-none" data-testid="performance-trend-chart">
            <CardContent className="p-6 md:p-8">
              <div className="flex items-center justify-between mb-6">
                <h3 className="text-lg font-medium text-slate-900" style={{ fontFamily: "'Outfit', sans-serif" }}>
                  Portfolio Performance
                </h3>
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
                    <Tooltip
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
          <Card className="bg-white border-slate-100 rounded-2xl shadow-none h-full" data-testid="asset-allocation-chart">
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
                      <Tooltip formatter={(v) => fmt(v)} />
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
          <Card className="bg-white border-slate-100 rounded-2xl shadow-none h-full" data-testid="sector-exposure-chart">
            <CardContent className="p-6 md:p-8">
              <h3 className="text-lg font-medium text-slate-900 dark:text-white mb-1" style={{ fontFamily: "'Outfit', sans-serif" }}>Sector Exposure</h3>
              <p className="text-[10px] text-slate-400 mb-5">Click a bar to view holdings</p>
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
                      <Tooltip formatter={(v) => [`${v}%`, "Allocation"]} contentStyle={{ borderRadius: 12, border: "1px solid #E2E8F0", fontSize: 13 }} />
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
          <Card className="bg-white border-slate-100 rounded-2xl shadow-none" data-testid="stock-heatmap">
            <CardContent className="p-6 md:p-8">
              <div className="flex items-center justify-between mb-6">
                <h3 className="text-lg font-medium text-slate-900" style={{ fontFamily: "'Outfit', sans-serif" }}>
                  Holdings Heatmap
                </h3>
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
                  />
                </ResponsiveContainer>
              </div>
            </CardContent>
          </Card>
        </motion.div>
      )}

      {/* ─── AI INSIGHTS + RECOMMENDATIONS ─── */}
      <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.44 }}>
        <Card className="bg-white border-slate-100 rounded-2xl shadow-none" data-testid="insights-preview">
          <CardContent className="p-6 md:p-8">
            <div className="flex items-center justify-between mb-6">
              <h3 className="text-lg font-medium text-slate-900 flex items-center gap-2" style={{ fontFamily: "'Outfit', sans-serif" }}>
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

      {/* ─── TOP MOVERS ─── */}
      {(analytics.top_gainers?.length > 0 || analytics.top_losers?.length > 0) && (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          {analytics.top_gainers?.length > 0 && (
            <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.5 }}>
              <Card className="bg-white border-slate-100 rounded-2xl shadow-none">
                <CardContent className="p-6">
                  <h3 className="text-base font-medium text-slate-900 mb-4 flex items-center gap-2" style={{ fontFamily: "'Outfit', sans-serif" }}>
                    <TrendingUp className="w-4 h-4 text-emerald-600" /> Top Gainers
                  </h3>
                  <div className="space-y-2.5">
                    {analytics.top_gainers.map((g, i) => (
                      <div key={i} className="flex items-center justify-between py-1">
                        <span className="text-sm text-slate-600 truncate max-w-[200px]">{g.name}</span>
                        <div className="flex items-center gap-2">
                          <span className="text-xs text-slate-400">{fmt(g.value)}</span>
                          <span className="text-sm font-medium text-emerald-600 bg-emerald-50 px-2 py-0.5 rounded-lg">+{g.pct_change}%</span>
                        </div>
                      </div>
                    ))}
                  </div>
                </CardContent>
              </Card>
            </motion.div>
          )}
          {analytics.top_losers?.length > 0 && (
            <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.54 }}>
              <Card className="bg-white border-slate-100 rounded-2xl shadow-none">
                <CardContent className="p-6">
                  <h3 className="text-base font-medium text-slate-900 mb-4 flex items-center gap-2" style={{ fontFamily: "'Outfit', sans-serif" }}>
                    <TrendingDown className="w-4 h-4 text-red-500" /> Top Losers
                  </h3>
                  <div className="space-y-2.5">
                    {analytics.top_losers.map((l, i) => (
                      <div key={i} className="flex items-center justify-between py-1">
                        <span className="text-sm text-slate-600 truncate max-w-[200px]">{l.name}</span>
                        <div className="flex items-center gap-2">
                          <span className="text-xs text-slate-400">{fmt(l.value)}</span>
                          <span className="text-sm font-medium text-red-500 bg-red-50 px-2 py-0.5 rounded-lg">{l.pct_change}%</span>
                        </div>
                      </div>
                    ))}
                  </div>
                </CardContent>
              </Card>
            </motion.div>
          )}
        </div>
      )}

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

export default DashboardOverview;
