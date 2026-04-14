import React from "react";
import { TrendingUp, TrendingDown, Wallet, BarChart3, AlertTriangle, RefreshCw } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { PieChart, Pie, Cell, ResponsiveContainer, Tooltip } from "recharts";
import { motion } from "framer-motion";

const COLORS = ["#059669", "#3B82F6", "#F59E0B", "#8B5CF6", "#EF4444", "#EC4899", "#14B8A6", "#F97316"];

const ASSET_LABELS = {
  equity: "Equity",
  mutual_fund: "Mutual Funds",
  etf: "ETF",
  bond: "Bonds",
  gold: "Gold",
  fd: "Fixed Deposit",
  other: "Other",
};

const formatCurrency = (val) => {
  if (val >= 10000000) return `₹${(val / 10000000).toFixed(2)} Cr`;
  if (val >= 100000) return `₹${(val / 100000).toFixed(2)} L`;
  if (val >= 1000) return `₹${(val / 1000).toFixed(1)}K`;
  return `₹${val.toFixed(0)}`;
};

const DashboardOverview = ({ analytics, insights, holdings, loading, onRefresh }) => {
  if (loading) {
    return (
      <div className="space-y-6">
        <div className="grid grid-cols-1 md:grid-cols-3 lg:grid-cols-4 gap-6">
          {[1, 2, 3, 4].map(i => (
            <div key={i} className="bg-white rounded-2xl border border-slate-100 p-6 h-32 animate-pulse">
              <div className="h-3 bg-slate-100 rounded w-24 mb-4" />
              <div className="h-6 bg-slate-100 rounded w-32" />
            </div>
          ))}
        </div>
      </div>
    );
  }

  const isEmpty = !analytics || analytics.holdings_count === 0;

  if (isEmpty) {
    return (
      <div data-testid="empty-dashboard">
        <div className="flex items-center justify-between mb-8">
          <div>
            <h1 className="text-2xl sm:text-3xl font-medium tracking-tight text-slate-900" style={{ fontFamily: "'Outfit', sans-serif" }}>
              Welcome to WealthPilot
            </h1>
            <p className="text-sm text-slate-500 mt-1">Start by adding your holdings to get AI-powered insights.</p>
          </div>
        </div>
        <div className="bg-white rounded-2xl border border-slate-100 p-12 text-center">
          <div className="w-16 h-16 bg-emerald-50 rounded-2xl flex items-center justify-center mx-auto mb-6">
            <Wallet className="w-8 h-8 text-emerald-600" strokeWidth={1.5} />
          </div>
          <h2 className="text-xl font-medium text-slate-900 mb-2" style={{ fontFamily: "'Outfit', sans-serif" }}>
            No holdings yet
          </h2>
          <p className="text-sm text-slate-500 mb-6">Add your stocks, mutual funds, and other investments to get started.</p>
          <p className="text-xs text-slate-400">Go to Portfolio tab to add your first holding</p>
        </div>
      </div>
    );
  }

  const returnsPositive = analytics.total_returns >= 0;
  const allocationData = analytics.asset_allocation.map(a => ({
    ...a,
    name: ASSET_LABELS[a.name] || a.name,
  }));
  const sectorData = analytics.sector_exposure.map(s => ({
    ...s,
    pct: analytics.current_value > 0 ? ((s.value / analytics.current_value) * 100).toFixed(1) : 0,
  }));

  return (
    <div data-testid="dashboard-overview">
      {/* Header */}
      <div className="flex items-center justify-between mb-8">
        <div>
          <h1 className="text-2xl sm:text-3xl font-medium tracking-tight text-slate-900" style={{ fontFamily: "'Outfit', sans-serif" }}>
            Portfolio Overview
          </h1>
          <p className="text-sm text-slate-500 mt-1">{analytics.holdings_count} holdings tracked</p>
        </div>
        <Button
          data-testid="refresh-button"
          variant="outline"
          onClick={onRefresh}
          className="rounded-xl border-slate-200 text-slate-600 hover:bg-slate-50"
        >
          <RefreshCw className="w-4 h-4 mr-2" strokeWidth={1.5} />
          Refresh
        </Button>
      </div>

      {/* Metric Cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6 mb-8">
        <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0 }}>
          <Card className="bg-white border-slate-100 rounded-2xl shadow-none hover:shadow-lg hover:border-slate-200 transition-all duration-300">
            <CardContent className="p-6">
              <p className="text-xs font-bold tracking-[0.15em] uppercase text-slate-400 mb-3">Total Invested</p>
              <p className="text-2xl font-semibold text-slate-900" style={{ fontFamily: "'Outfit', sans-serif" }} data-testid="total-invested">
                {formatCurrency(analytics.total_invested)}
              </p>
            </CardContent>
          </Card>
        </motion.div>

        <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.05 }}>
          <Card className="bg-white border-slate-100 rounded-2xl shadow-none hover:shadow-lg hover:border-slate-200 transition-all duration-300">
            <CardContent className="p-6">
              <p className="text-xs font-bold tracking-[0.15em] uppercase text-slate-400 mb-3">Current Value</p>
              <p className="text-2xl font-semibold text-slate-900" style={{ fontFamily: "'Outfit', sans-serif" }} data-testid="current-value">
                {formatCurrency(analytics.current_value)}
              </p>
            </CardContent>
          </Card>
        </motion.div>

        <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.1 }}>
          <Card className="bg-white border-slate-100 rounded-2xl shadow-none hover:shadow-lg hover:border-slate-200 transition-all duration-300">
            <CardContent className="p-6">
              <p className="text-xs font-bold tracking-[0.15em] uppercase text-slate-400 mb-3">Total Returns</p>
              <div className="flex items-center gap-2">
                {returnsPositive ? (
                  <TrendingUp className="w-5 h-5 text-emerald-600" strokeWidth={1.5} />
                ) : (
                  <TrendingDown className="w-5 h-5 text-red-500" strokeWidth={1.5} />
                )}
                <p
                  className={`text-2xl font-semibold ${returnsPositive ? "text-emerald-600" : "text-red-500"}`}
                  style={{ fontFamily: "'Outfit', sans-serif" }}
                  data-testid="total-returns"
                >
                  {returnsPositive ? "+" : ""}{formatCurrency(Math.abs(analytics.total_returns))}
                </p>
              </div>
              <p className={`text-sm mt-1 ${returnsPositive ? "text-emerald-500" : "text-red-400"}`}>
                {returnsPositive ? "+" : ""}{analytics.returns_pct.toFixed(1)}%
              </p>
            </CardContent>
          </Card>
        </motion.div>

        <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.15 }}>
          <Card className="bg-white border-slate-100 rounded-2xl shadow-none hover:shadow-lg hover:border-slate-200 transition-all duration-300">
            <CardContent className="p-6">
              <p className="text-xs font-bold tracking-[0.15em] uppercase text-slate-400 mb-3">Risk Score</p>
              <div className="flex items-center gap-2">
                <AlertTriangle className={`w-5 h-5 ${analytics.risk_score < 30 ? "text-emerald-600" : analytics.risk_score < 60 ? "text-amber-500" : "text-red-500"}`} strokeWidth={1.5} />
                <p className="text-2xl font-semibold text-slate-900" style={{ fontFamily: "'Outfit', sans-serif" }} data-testid="risk-score">
                  {analytics.risk_label}
                </p>
              </div>
              {/* Risk bar */}
              <div className="mt-3 w-full h-2 rounded-full bg-slate-100 overflow-hidden">
                <div
                  className="h-full rounded-full transition-all duration-500"
                  style={{
                    width: `${analytics.risk_score}%`,
                    background: `linear-gradient(90deg, #10B981 0%, #F59E0B 50%, #EF4444 100%)`,
                  }}
                  data-testid="risk-bar"
                />
              </div>
              <p className="text-xs text-slate-400 mt-1">{analytics.risk_score}/100</p>
            </CardContent>
          </Card>
        </motion.div>
      </div>

      {/* Charts Row */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-8">
        {/* Asset Allocation */}
        <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.2 }}>
          <Card className="bg-white border-slate-100 rounded-2xl shadow-none" data-testid="asset-allocation-chart">
            <CardContent className="p-6 md:p-8">
              <h3 className="text-lg font-medium text-slate-900 mb-6" style={{ fontFamily: "'Outfit', sans-serif" }}>
                Asset Allocation
              </h3>
              <div className="flex items-center gap-8">
                <div className="w-48 h-48">
                  <ResponsiveContainer width="100%" height="100%">
                    <PieChart>
                      <Pie data={allocationData} cx="50%" cy="50%" innerRadius={50} outerRadius={80} paddingAngle={2} dataKey="value">
                        {allocationData.map((_, i) => (
                          <Cell key={i} fill={COLORS[i % COLORS.length]} />
                        ))}
                      </Pie>
                      <Tooltip formatter={(val) => formatCurrency(val)} />
                    </PieChart>
                  </ResponsiveContainer>
                </div>
                <div className="flex-1 space-y-3">
                  {allocationData.map((a, i) => (
                    <div key={a.name} className="flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        <div className="w-3 h-3 rounded-full" style={{ backgroundColor: COLORS[i % COLORS.length] }} />
                        <span className="text-sm text-slate-600">{a.name}</span>
                      </div>
                      <span className="text-sm font-medium text-slate-900">{formatCurrency(a.value)}</span>
                    </div>
                  ))}
                </div>
              </div>
            </CardContent>
          </Card>
        </motion.div>

        {/* Sector Exposure */}
        <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.25 }}>
          <Card className="bg-white border-slate-100 rounded-2xl shadow-none" data-testid="sector-exposure-chart">
            <CardContent className="p-6 md:p-8">
              <h3 className="text-lg font-medium text-slate-900 mb-6" style={{ fontFamily: "'Outfit', sans-serif" }}>
                Sector Exposure
              </h3>
              <div className="space-y-4">
                {sectorData.map((s, i) => (
                  <div key={s.name}>
                    <div className="flex items-center justify-between mb-1">
                      <span className="text-sm text-slate-600">{s.name}</span>
                      <span className="text-sm font-medium text-slate-900">{s.pct}%</span>
                    </div>
                    <div className="w-full h-2 rounded-full bg-slate-100 overflow-hidden">
                      <div
                        className="h-full rounded-full transition-all duration-500"
                        style={{ width: `${s.pct}%`, backgroundColor: COLORS[i % COLORS.length] }}
                      />
                    </div>
                  </div>
                ))}
                {sectorData.length === 0 && (
                  <p className="text-sm text-slate-400 text-center py-6">No sector data available</p>
                )}
              </div>
            </CardContent>
          </Card>
        </motion.div>
      </div>

      {/* Insights Preview */}
      {insights.length > 0 && (
        <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.3 }}>
          <Card className="bg-white border-slate-100 rounded-2xl shadow-none" data-testid="insights-preview">
            <CardContent className="p-6 md:p-8">
              <div className="flex items-center justify-between mb-6">
                <h3 className="text-lg font-medium text-slate-900" style={{ fontFamily: "'Outfit', sans-serif" }}>
                  <BarChart3 className="w-5 h-5 inline-block mr-2 text-emerald-600" strokeWidth={1.5} />
                  AI Insights
                </h3>
              </div>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                {insights.slice(0, 4).map((ins) => (
                  <div
                    key={ins.insight_id}
                    className={`p-4 rounded-xl border ${
                      ins.type === "warning" ? "border-amber-200 bg-amber-50" :
                      ins.type === "opportunity" ? "border-emerald-200 bg-emerald-50" :
                      ins.type === "action" ? "border-blue-200 bg-blue-50" :
                      "border-slate-200 bg-slate-50"
                    }`}
                  >
                    <p className="text-sm font-medium text-slate-900 mb-1">{ins.title}</p>
                    <p className="text-xs text-slate-500 leading-relaxed">{ins.description}</p>
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>
        </motion.div>
      )}

      {/* Top Gainers / Losers */}
      {(analytics.top_gainers?.length > 0 || analytics.top_losers?.length > 0) && (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6 mt-8">
          {analytics.top_gainers?.length > 0 && (
            <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.35 }}>
              <Card className="bg-white border-slate-100 rounded-2xl shadow-none">
                <CardContent className="p-6">
                  <h3 className="text-base font-medium text-slate-900 mb-4 flex items-center gap-2" style={{ fontFamily: "'Outfit', sans-serif" }}>
                    <TrendingUp className="w-4 h-4 text-emerald-600" /> Top Gainers
                  </h3>
                  <div className="space-y-3">
                    {analytics.top_gainers.map(g => (
                      <div key={g.name} className="flex items-center justify-between">
                        <span className="text-sm text-slate-600">{g.name}</span>
                        <span className="text-sm font-medium text-emerald-600">+{g.pct_change}%</span>
                      </div>
                    ))}
                  </div>
                </CardContent>
              </Card>
            </motion.div>
          )}
          {analytics.top_losers?.length > 0 && (
            <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.4 }}>
              <Card className="bg-white border-slate-100 rounded-2xl shadow-none">
                <CardContent className="p-6">
                  <h3 className="text-base font-medium text-slate-900 mb-4 flex items-center gap-2" style={{ fontFamily: "'Outfit', sans-serif" }}>
                    <TrendingDown className="w-4 h-4 text-red-500" /> Top Losers
                  </h3>
                  <div className="space-y-3">
                    {analytics.top_losers.map(l => (
                      <div key={l.name} className="flex items-center justify-between">
                        <span className="text-sm text-slate-600">{l.name}</span>
                        <span className="text-sm font-medium text-red-500">{l.pct_change}%</span>
                      </div>
                    ))}
                  </div>
                </CardContent>
              </Card>
            </motion.div>
          )}
        </div>
      )}
    </div>
  );
};

export default DashboardOverview;
