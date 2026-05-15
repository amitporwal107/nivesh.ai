import React, { useMemo } from "react";
import {
  ScatterChart, Scatter, XAxis, YAxis, ZAxis,
  CartesianGrid, Tooltip, ResponsiveContainer, ReferenceLine,
  BarChart, Bar, Cell, LabelList,
} from "recharts";
import { motion } from "framer-motion";
import { Card, CardContent } from "@/components/ui/card";
import {
  TrendingUp, TrendingDown, AlertTriangle, CheckCircle,
  Layers, Target, ArrowRight,
} from "lucide-react";

// ──────────────────────────────────────────────────────────
// HELPERS
// ──────────────────────────────────────────────────────────
const median = (arr) => {
  if (!arr.length) return 0;
  const s = [...arr].sort((a, b) => a - b);
  const m = Math.floor(s.length / 2);
  return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2;
};

const getFmtShort = (v) => {
  if (v == null) return "—";
  const abs = Math.abs(v);
  if (abs >= 1e7) return `₹${(v / 1e7).toFixed(1)} Cr`;
  if (abs >= 1e5) return `₹${(v / 1e5).toFixed(1)} L`;
  if (abs >= 1e3) return `₹${(v / 1e3).toFixed(0)} K`;
  return `₹${Math.round(v)}`;
};

// ──────────────────────────────────────────────────────────
// 1. PORTFOLIO / DIVERSIFICATION HEALTH GAUGE
// ──────────────────────────────────────────────────────────
export const PortfolioHealthGauge = ({ score, title = "Portfolio Quality Score", size = "md" }) => {
  const r = size === "sm" ? 65 : 82;
  const cx = size === "sm" ? 90 : 112;
  const cy = size === "sm" ? 85 : 105;
  const arc = Math.PI * r;
  const pct = Math.max(0, Math.min(100, score || 0));
  const filled = (pct / 100) * arc;
  const color = pct >= 75 ? "#10B981" : pct >= 55 ? "#F59E0B" : pct >= 35 ? "#F97316" : "#EF4444";
  const lbl = pct >= 75 ? "STRONG" : pct >= 55 ? "AVERAGE" : pct >= 35 ? "WEAK" : "CRITICAL";
  const pathD = `M ${cx - r} ${cy} A ${r} ${r} 0 0 1 ${cx + r} ${cy}`;
  const w = size === "sm" ? 180 : 224;
  const h = size === "sm" ? 100 : 120;

  return (
    <div className="flex flex-col items-center">
      <svg width={w} height={h} viewBox={`0 0 ${w} ${h}`} style={{ overflow: "visible" }}>
        {/* Background track */}
        <path d={pathD} fill="none" stroke="#1E293B" strokeWidth="13" strokeLinecap="round" />
        {/* Progress arc */}
        <path
          d={pathD}
          fill="none"
          stroke={color}
          strokeWidth="13"
          strokeLinecap="round"
          strokeDasharray={`${filled} ${arc}`}
          style={{ filter: `drop-shadow(0 0 7px ${color}aa)` }}
        />
        {/* Score number */}
        <text
          x={cx} y={cy - (size === "sm" ? 14 : 18)}
          textAnchor="middle" fill="white"
          fontSize={size === "sm" ? "28" : "34"}
          fontWeight="800"
          style={{ fontFamily: "'JetBrains Mono', monospace" }}
        >
          {score == null ? "—" : Math.round(pct)}
        </text>
        {/* Zone label */}
        <text x={cx} y={cy - (size === "sm" ? 2 : 3)} textAnchor="middle" fill={color}
          fontSize="9" fontWeight="700" letterSpacing="1.8">
          {score == null ? "NO DATA" : lbl}
        </text>
        {/* /100 */}
        <text x={cx} y={cy + (size === "sm" ? 10 : 12)} textAnchor="middle" fill="#475569" fontSize="8">
          out of 100
        </text>
        {/* Tick marks */}
        {[0, 25, 50, 75, 100].map(tick => {
          const angle = Math.PI - (tick / 100) * Math.PI;
          const x1 = cx + r * Math.cos(angle);
          const y1 = cy - r * Math.sin(angle);
          const x2 = cx + (r + 9) * Math.cos(angle);
          const y2 = cy - (r + 9) * Math.sin(angle);
          return <line key={tick} x1={Math.round(x1)} y1={Math.round(y1)} x2={Math.round(x2)} y2={Math.round(y2)} stroke="#2D3748" strokeWidth="1.5" />;
        })}
        <text x={cx - r - 12} y={cy + 4} fill="#334155" fontSize="7" textAnchor="middle">0</text>
        <text x={cx + r + 12} y={cy + 4} fill="#334155" fontSize="7" textAnchor="middle">100</text>
      </svg>
      <p className="text-[10px] text-slate-500 dark:text-zinc-500 -mt-0.5 text-center">{title}</p>
    </div>
  );
};

// ──────────────────────────────────────────────────────────
// 2. RISK vs RETURN BUBBLE CHART
// ──────────────────────────────────────────────────────────
const RiskReturnTooltip = ({ active, payload, fmt }) => {
  if (!active || !payload?.length) return null;
  const d = payload[0]?.payload;
  if (!d) return null;
  const isPos = d.pct_return >= 0;
  return (
    <div className="bg-slate-900 border border-slate-700 rounded-xl p-3 shadow-xl text-xs max-w-[220px]">
      <p className="font-semibold text-white mb-2 leading-snug">{d.fullName}</p>
      <p className={`font-bold ${isPos ? "text-emerald-400" : "text-red-400"}`}>
        Return: {isPos ? "+" : ""}{d.pct_return?.toFixed(1)}%
      </p>
      <p className="text-slate-300 mt-0.5">Weight: {d.weight?.toFixed(1)}%</p>
      <p className="text-slate-400 mt-0.5">Invested: {fmt ? fmt(d.invested) : getFmtShort(d.invested)}</p>
      <p className="text-slate-500 mt-0.5 text-[10px]">{d.asset_type}</p>
    </div>
  );
};

export const RiskReturnBubble = ({ perfCards, fmt }) => {
  const { strong, moderate, weak, negative } = useMemo(() => {
    const toPoint = c => ({
      x: Math.max(-120, Math.min(320, c.pct_return || 0)),
      y: Math.max(0, c.weight || 0),
      z: Math.max(20, Math.log(Math.max(c.invested, 1000)) * 4),
      pct_return: c.pct_return,
      weight: c.weight,
      invested: c.invested,
      asset_type: c.asset_type,
      fullName: c.name,
    });
    const cards = (perfCards || []).filter(c => c.invested > 0);
    return {
      strong:   cards.filter(c => c.pct_return >= 15).map(toPoint),
      moderate: cards.filter(c => c.pct_return >= 0 && c.pct_return < 15).map(toPoint),
      weak:     cards.filter(c => c.pct_return < 0 && c.pct_return >= -15).map(toPoint),
      negative: cards.filter(c => c.pct_return < -15).map(toPoint),
    };
  }, [perfCards]);

  const all = [...strong, ...moderate, ...weak, ...negative];
  if (!all.length) return <p className="text-sm text-slate-400 text-center py-8">No holdings data</p>;

  const TooltipWrapper = (props) => <RiskReturnTooltip {...props} fmt={fmt} />;

  return (
    <div>
      <p className="text-[10px] text-slate-400 dark:text-zinc-500 mb-3">
        Bubble size ≈ invested amount. X = total return %. Y = portfolio weight %.
      </p>
      <ResponsiveContainer width="100%" height={240}>
        <ScatterChart margin={{ top: 8, right: 16, bottom: 24, left: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#1E293B" />
          <XAxis
            type="number" dataKey="x" name="Return %"
            domain={["auto", "auto"]}
            tick={{ fill: "#64748B", fontSize: 9 }}
            tickFormatter={v => `${v}%`}
            label={{ value: "Return %", position: "insideBottom", offset: -10, fill: "#64748B", fontSize: 10 }}
          />
          <YAxis
            type="number" dataKey="y" name="Weight %"
            tick={{ fill: "#64748B", fontSize: 9 }}
            tickFormatter={v => `${v}%`}
            label={{ value: "Weight %", angle: -90, position: "insideLeft", offset: 14, fill: "#64748B", fontSize: 10 }}
          />
          <ZAxis type="number" dataKey="z" range={[30, 320]} />
          <ReferenceLine x={0} stroke="#475569" strokeDasharray="4 3" />
          <Tooltip content={<TooltipWrapper />} />
          <Scatter name="+15%+" data={strong} fill="#10B981" fillOpacity={0.8} />
          <Scatter name="0–15%" data={moderate} fill="#34D399" fillOpacity={0.7} />
          <Scatter name="-15 to 0" data={weak} fill="#F59E0B" fillOpacity={0.75} />
          <Scatter name="<-15%" data={negative} fill="#EF4444" fillOpacity={0.8} />
        </ScatterChart>
      </ResponsiveContainer>
      <div className="flex flex-wrap gap-3 mt-1 text-[9px] text-slate-400">
        {[
          { color: "#10B981", label: "+15%+" },
          { color: "#34D399", label: "0–15%" },
          { color: "#F59E0B", label: "−15 to 0%" },
          { color: "#EF4444", label: "< −15%" },
        ].map(l => (
          <div key={l.label} className="flex items-center gap-1">
            <div className="w-2.5 h-2.5 rounded-full" style={{ backgroundColor: l.color }} />
            {l.label}
          </div>
        ))}
      </div>
    </div>
  );
};

// ──────────────────────────────────────────────────────────
// 3. ACTION MATRIX (2×2 Quadrant)
// ──────────────────────────────────────────────────────────
const QUADRANT_CONFIG = {
  keep:    { label: "Keep", sub: "Strong return, significant weight", color: "emerald", icon: CheckCircle, badge: "bg-emerald-500/15 text-emerald-400 border-emerald-500/25" },
  monitor: { label: "Monitor", sub: "Good return, lower weight", color: "sky", icon: Target, badge: "bg-sky-500/15 text-sky-400 border-sky-500/25" },
  review:  { label: "Review", sub: "Heavy weight, weak return", color: "amber", icon: AlertTriangle, badge: "bg-amber-500/15 text-amber-400 border-amber-500/25" },
  exit:    { label: "Exit", sub: "Low weight + weak return", color: "red", icon: TrendingDown, badge: "bg-red-500/15 text-red-400 border-red-500/25" },
};

const QUADRANT_BORDER = {
  keep:    "border-emerald-500/20 bg-emerald-500/5",
  monitor: "border-sky-500/20 bg-sky-500/5",
  review:  "border-amber-500/20 bg-amber-500/5",
  exit:    "border-red-500/20 bg-red-500/5",
};

export const ActionMatrix = ({ perfCards }) => {
  const { quadrants, medR, medW } = useMemo(() => {
    const cards = (perfCards || []).filter(c => c.invested > 0);
    if (!cards.length) return { quadrants: {}, medR: 0, medW: 0 };
    const medR = median(cards.map(c => c.pct_return || 0));
    const medW = median(cards.map(c => c.weight || 0));
    const q = { keep: [], monitor: [], review: [], exit: [] };
    cards.forEach(c => {
      const highReturn = (c.pct_return || 0) >= medR;
      const highWeight = (c.weight || 0) >= medW;
      if (highReturn && highWeight) q.keep.push(c);
      else if (highReturn && !highWeight) q.monitor.push(c);
      else if (!highReturn && highWeight) q.review.push(c);
      else q.exit.push(c);
    });
    return { quadrants: q, medR, medW };
  }, [perfCards]);

  const cards = (perfCards || []).filter(c => c.invested > 0);
  if (!cards.length) return <p className="text-sm text-slate-400 text-center py-8">No holdings data</p>;

  return (
    <div>
      <p className="text-[10px] text-slate-400 dark:text-zinc-500 mb-3">
        Based on return vs portfolio weight. Median return: {medR?.toFixed(1)}% · Median weight: {medW?.toFixed(1)}%
      </p>
      <div className="grid grid-cols-2 gap-2">
        {(["keep", "review", "monitor", "exit"]).map(key => {
          const cfg = QUADRANT_CONFIG[key];
          const funds = quadrants[key] || [];
          const Icon = cfg.icon;
          return (
            <div key={key} className={`rounded-xl p-3 border ${QUADRANT_BORDER[key]}`}>
              <div className="flex items-center gap-1.5 mb-2">
                <Icon className="w-3.5 h-3.5" style={{ color: key === "keep" ? "#10B981" : key === "monitor" ? "#38BDF8" : key === "review" ? "#F59E0B" : "#EF4444" }} />
                <span className="text-xs font-bold text-slate-900 dark:text-white">{cfg.label}</span>
                <span className="ml-auto text-[10px] font-bold text-slate-400">{funds.length}</span>
              </div>
              <p className="text-[9px] text-slate-400 mb-2">{cfg.sub}</p>
              <div className="space-y-1 max-h-[90px] overflow-y-auto">
                {funds.slice(0, 5).map((f, i) => (
                  <div key={i} className="flex items-center justify-between gap-1">
                    <p className="text-[9px] text-slate-500 dark:text-zinc-400 truncate flex-1">{f.name.length > 22 ? f.name.slice(0, 22) + "…" : f.name}</p>
                    <span className={`text-[9px] font-bold flex-shrink-0 ${f.pct_return >= 0 ? "text-emerald-500" : "text-red-400"}`}>
                      {f.pct_return >= 0 ? "+" : ""}{f.pct_return?.toFixed(0)}%
                    </span>
                  </div>
                ))}
                {funds.length > 5 && (
                  <p className="text-[9px] text-slate-500 text-center">+{funds.length - 5} more</p>
                )}
              </div>
            </div>
          );
        })}
      </div>
      <div className="grid grid-cols-2 gap-0.5 mt-2 text-[8px] text-slate-500">
        <span className="text-center">← High weight / Low weight →</span>
        <span />
        <span className="text-center">↑ High return</span>
        <span />
      </div>
    </div>
  );
};

// ──────────────────────────────────────────────────────────
// 4. CONTRIBUTION WATERFALL (Top Gainers + Losers)
// ──────────────────────────────────────────────────────────
const WaterfallTooltip = ({ active, payload, fmt }) => {
  if (!active || !payload?.length) return null;
  const d = payload[0]?.payload;
  if (!d) return null;
  return (
    <div className="bg-slate-900 border border-slate-700 rounded-xl p-3 shadow-xl text-xs">
      <p className="font-semibold text-white mb-1">{d.fullName}</p>
      <p className={`font-bold ${d.value >= 0 ? "text-emerald-400" : "text-red-400"}`}>
        {d.value >= 0 ? "+" : ""}{fmt ? fmt(Math.abs(d.value)) : getFmtShort(Math.abs(d.value))}
      </p>
      <p className="text-slate-400 mt-0.5">{d.pct_return?.toFixed(1)}% total return</p>
    </div>
  );
};

export const ContributionWaterfall = ({ perfCards, fmt }) => {
  const chartData = useMemo(() => {
    const cards = (perfCards || []).filter(c => c.invested > 0 && c.abs_return != null);
    const gainers = [...cards].sort((a, b) => b.abs_return - a.abs_return).slice(0, 6);
    const losers  = [...cards].filter(c => c.abs_return < 0).sort((a, b) => a.abs_return - b.abs_return).slice(0, 4);
    return [...gainers, ...losers].map(c => ({
      name: c.name.length > 20 ? c.name.slice(0, 20) + "…" : c.name,
      fullName: c.name,
      value: c.abs_return,
      pct_return: c.pct_return,
    })).sort((a, b) => b.value - a.value);
  }, [perfCards]);

  if (!chartData.length) return <p className="text-sm text-slate-400 text-center py-8">No return data</p>;

  const TooltipWrapper = (props) => <WaterfallTooltip {...props} fmt={fmt} />;

  return (
    <div>
      <p className="text-[10px] text-slate-400 dark:text-zinc-500 mb-3">
        Absolute gain/loss contribution per holding. Top 6 winners · Top 4 losers.
      </p>
      <ResponsiveContainer width="100%" height={Math.max(180, chartData.length * 26)}>
        <BarChart data={chartData} layout="vertical" margin={{ top: 0, right: 60, bottom: 0, left: 4 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#1E293B" horizontal={false} />
          <XAxis
            type="number"
            tick={{ fill: "#64748B", fontSize: 9 }}
            tickFormatter={v => getFmtShort(v)}
          />
          <YAxis
            type="category" dataKey="name" width={120}
            tick={{ fill: "#94A3B8", fontSize: 9 }}
          />
          <ReferenceLine x={0} stroke="#475569" />
          <Tooltip content={<TooltipWrapper />} />
          <Bar dataKey="value" radius={[0, 4, 4, 0]}>
            {chartData.map((d, i) => (
              <Cell key={i} fill={d.value >= 0 ? "#10B981" : "#EF4444"} fillOpacity={0.85} />
            ))}
            <LabelList
              dataKey="value"
              position="right"
              formatter={v => (v >= 0 ? "+" : "") + getFmtShort(v)}
              style={{ fill: "#94A3B8", fontSize: 9 }}
            />
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
};

// ──────────────────────────────────────────────────────────
// 5. PERFORMANCE ANALYTICS COCKPIT
//    (Hero section for Performance & Benchmark tab)
// ──────────────────────────────────────────────────────────
export const PerformanceAnalyticsCockpit = ({ perfCards, fundPerformance, portfolioHealth, fmt }) => {
  const cards = (perfCards || []).filter(c => c.invested > 0);
  const dist = fundPerformance?.performance_distribution || {};
  const score = portfolioHealth?.health_score ?? null;

  const positiveCount  = cards.filter(c => c.pct_return >= 0).length;
  const outperforming  = dist.overperforming || 0;
  const topQ           = Math.round(outperforming * 0.7); // approximation if v3 not loaded
  const toReview       = (dist.underperforming || 0) + Math.max(0, cards.filter(c => c.pct_return < -5).length - (dist.underperforming || 0));
  const totalReturn    = cards.reduce((s, c) => s + (c.abs_return || 0), 0);

  const chips = [
    { label: "Positive Returns", value: `${positiveCount} / ${cards.length}`, color: "emerald" },
    { label: "Outperforming Benchmark", value: outperforming > 0 ? `${outperforming} funds` : "—", color: "sky" },
    { label: "Need Review", value: toReview > 0 ? `${toReview} funds` : "0", color: toReview > 3 ? "amber" : "slate" },
    { label: "Total Gain", value: (totalReturn >= 0 ? "+" : "") + (fmt ? fmt(Math.abs(totalReturn)) : getFmtShort(Math.abs(totalReturn))), color: totalReturn >= 0 ? "emerald" : "red" },
  ];

  const chipStyle = {
    emerald: "bg-emerald-50 dark:bg-emerald-500/10 text-emerald-700 dark:text-emerald-400 border-emerald-200 dark:border-emerald-500/20",
    sky:     "bg-sky-50 dark:bg-sky-500/10 text-sky-700 dark:text-sky-400 border-sky-200 dark:border-sky-500/20",
    amber:   "bg-amber-50 dark:bg-amber-500/10 text-amber-700 dark:text-amber-400 border-amber-200 dark:border-amber-500/20",
    red:     "bg-red-50 dark:bg-red-500/10 text-red-700 dark:text-red-400 border-red-200 dark:border-red-500/20",
    slate:   "bg-slate-100 dark:bg-zinc-800 text-slate-600 dark:text-zinc-400 border-slate-200 dark:border-zinc-700",
  };

  return (
    <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} className="space-y-4">
      {/* Hero Row: Gauge + Chips */}
      <Card className="bg-white dark:bg-[#111] border-slate-100 dark:border-white/5 rounded-2xl">
        <CardContent className="p-5 md:p-6">
          <div className="flex flex-col md:flex-row items-center gap-6">
            {/* Gauge */}
            <div className="flex-shrink-0">
              <PortfolioHealthGauge score={score} title="Portfolio Health Score" />
            </div>
            {/* Divider */}
            <div className="hidden md:block w-px h-28 bg-slate-100 dark:bg-white/5" />
            {/* Chips + CTA */}
            <div className="flex-1 w-full">
              <h3 className="text-base font-bold text-slate-900 dark:text-white mb-1" style={{ fontFamily: "'Outfit', sans-serif" }}>
                Performance Snapshot
              </h3>
              <p className="text-xs text-slate-400 mb-4">
                {cards.length} holdings · {score == null ? "Run analysis for health score" : score >= 75 ? "Portfolio is performing strongly" : score >= 55 ? "Portfolio needs moderate attention" : "Several holdings need review"}
              </p>
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
                {chips.map(ch => (
                  <div key={ch.label} className={`rounded-xl border px-3 py-2.5 ${chipStyle[ch.color]}`}>
                    <p className="text-[10px] font-medium opacity-75 mb-0.5">{ch.label}</p>
                    <p className="text-sm font-bold" style={{ fontFamily: "'JetBrains Mono', monospace" }}>{ch.value}</p>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Charts Row: Risk/Return + Action Matrix */}
      {cards.length > 0 && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.05 }}>
            <Card className="bg-white dark:bg-[#111] border-slate-100 dark:border-white/5 rounded-2xl h-full">
              <CardContent className="p-5">
                <h3 className="text-sm font-semibold text-slate-900 dark:text-white mb-1" style={{ fontFamily: "'Outfit', sans-serif" }}>
                  Risk vs Return
                </h3>
                <RiskReturnBubble perfCards={cards} fmt={fmt} />
              </CardContent>
            </Card>
          </motion.div>

          <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.1 }}>
            <Card className="bg-white dark:bg-[#111] border-slate-100 dark:border-white/5 rounded-2xl h-full">
              <CardContent className="p-5">
                <h3 className="text-sm font-semibold text-slate-900 dark:text-white mb-1" style={{ fontFamily: "'Outfit', sans-serif" }}>
                  Action Matrix
                </h3>
                <ActionMatrix perfCards={cards} />
              </CardContent>
            </Card>
          </motion.div>
        </div>
      )}

      {/* Contribution Waterfall */}
      {cards.length > 0 && (
        <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.15 }}>
          <Card className="bg-white dark:bg-[#111] border-slate-100 dark:border-white/5 rounded-2xl">
            <CardContent className="p-5">
              <h3 className="text-sm font-semibold text-slate-900 dark:text-white mb-1" style={{ fontFamily: "'Outfit', sans-serif" }}>
                Top Contributors &amp; Detractors
              </h3>
              <ContributionWaterfall perfCards={cards} fmt={fmt} />
            </CardContent>
          </Card>
        </motion.div>
      )}
    </motion.div>
  );
};

// ──────────────────────────────────────────────────────────
// 6. DIVERSIFICATION HERO
//    (Hero section for Diversification & Consolidation tab)
// ──────────────────────────────────────────────────────────
const SimplificationFunnel = ({ stages }) => {
  if (!stages?.length) return null;
  const maxVal = stages[0]?.value || 1;
  return (
    <div className="space-y-2">
      {stages.map((s, i) => {
        const pct = Math.max(20, (s.value / maxVal) * 100);
        return (
          <div key={i} className="flex items-center gap-3">
            <div className="w-28 text-right">
              <p className="text-[10px] text-slate-400 leading-tight">{s.label}</p>
            </div>
            <div className="flex-1 relative h-7 flex items-center" style={{ paddingLeft: `${(100 - pct) / 2}%`, paddingRight: `${(100 - pct) / 2}%` }}>
              <div
                className="h-full rounded-lg flex items-center justify-center w-full transition-all"
                style={{ backgroundColor: s.color + "30", border: `1px solid ${s.color}50` }}
              >
                <span className="text-[10px] font-bold" style={{ color: s.color, fontFamily: "'JetBrains Mono', monospace" }}>
                  {s.value}
                </span>
              </div>
              {i < stages.length - 1 && (
                <div className="absolute -bottom-2 left-1/2 -translate-x-1/2 text-slate-500">
                  <ArrowRight className="w-3 h-3 rotate-90" />
                </div>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
};

export const DiversificationHero = ({ perfCards, fundPerformance }) => {
  const mfCards     = (perfCards || []).filter(c => c.asset_type === "mutual_fund");
  const catOverlap  = fundPerformance?.category_overlap || [];
  const dist        = fundPerformance?.performance_distribution || {};
  const totalMF     = fundPerformance?.summary?.total_mf ?? mfCards.length;
  const overlapping = catOverlap.filter(c => c.is_overlapping).length;
  const uniqueCats  = catOverlap.filter(c => !c.is_overlapping).length;
  const matched     = fundPerformance?.summary?.matched || 0;

  // Diversification score: penalise for overlapping categories and excess funds
  const overlapPenalty = Math.min(40, overlapping * 3.5);
  const fundExcess     = Math.min(35, Math.max(0, totalMF - 18) * 1.2);
  const uniqueBonus    = Math.min(15, uniqueCats * 2);
  const divScore       = catOverlap.length > 0
    ? Math.round(Math.max(5, Math.min(100, 100 - overlapPenalty - fundExcess + uniqueBonus)))
    : null;

  const chips = [
    { label: "Total MF Funds", value: totalMF, color: "slate" },
    { label: "Overlapping Categories", value: overlapping, color: overlapping > 5 ? "red" : overlapping > 2 ? "amber" : "emerald" },
    { label: "Unique Categories", value: uniqueCats, color: "emerald" },
    { label: "Ideal Portfolio", value: "18 funds", color: "sky" },
  ];

  const chipStyle = {
    emerald: "bg-emerald-50 dark:bg-emerald-500/10 text-emerald-700 dark:text-emerald-400 border-emerald-200 dark:border-emerald-500/20",
    sky:     "bg-sky-50 dark:bg-sky-500/10 text-sky-700 dark:text-sky-400 border-sky-200 dark:border-sky-500/20",
    amber:   "bg-amber-50 dark:bg-amber-500/10 text-amber-700 dark:text-amber-400 border-amber-200 dark:border-amber-500/20",
    red:     "bg-red-50 dark:bg-red-500/10 text-red-700 dark:text-red-400 border-red-200 dark:border-red-500/20",
    slate:   "bg-slate-100 dark:bg-zinc-800 text-slate-600 dark:text-zinc-400 border-slate-200 dark:border-zinc-700",
  };

  // Simplification funnel stages
  const withData = matched || mfCards.filter(c => c.nav_source === "AMFI").length;
  const topQuartile = Math.round((dist.overperforming || 0) * 0.85);
  const toReview = dist.underperforming || 0;
  const funnelStages = [
    { label: "Total Funds", value: totalMF, color: "#6366F1" },
    { label: "Benchmark Data", value: withData || totalMF, color: "#3B82F6" },
    { label: "Top Performers", value: topQuartile || Math.round(totalMF * 0.2), color: "#10B981" },
    { label: "Need Review", value: toReview || Math.round(totalMF * 0.1), color: "#F59E0B" },
  ].filter(s => s.value > 0);

  return (
    <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }}>
      <Card className="bg-white dark:bg-[#111] border-slate-100 dark:border-white/5 rounded-2xl">
        <CardContent className="p-5 md:p-6">
          <div className="flex flex-col md:flex-row items-center gap-6">
            {/* Gauge */}
            <div className="flex-shrink-0">
              <PortfolioHealthGauge score={divScore} title="Diversification Score" />
            </div>
            {/* Divider */}
            <div className="hidden md:block w-px h-28 bg-slate-100 dark:bg-white/5" />
            {/* Chips */}
            <div className="flex-1 w-full">
              <div className="flex items-center gap-2 mb-1">
                <Layers className="w-4 h-4 text-purple-500" />
                <h3 className="text-base font-bold text-slate-900 dark:text-white" style={{ fontFamily: "'Outfit', sans-serif" }}>
                  Diversification Overview
                </h3>
              </div>
              <p className="text-xs text-slate-400 mb-4">
                {divScore == null
                  ? "Load benchmark data to compute diversification score"
                  : divScore >= 70
                  ? "Well-diversified portfolio with minimal category overlap"
                  : divScore >= 45
                  ? `${overlapping} overlapping categories — consider consolidating`
                  : `Significantly over-diversified — reducing to 18 core funds recommended`}
              </p>
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
                {chips.map(ch => (
                  <div key={ch.label} className={`rounded-xl border px-3 py-2.5 ${chipStyle[ch.color]}`}>
                    <p className="text-[10px] font-medium opacity-75 mb-0.5">{ch.label}</p>
                    <p className="text-sm font-bold" style={{ fontFamily: "'JetBrains Mono', monospace" }}>{ch.value}</p>
                  </div>
                ))}
              </div>
            </div>
            {/* Funnel (hidden on mobile) */}
            {funnelStages.length > 1 && (
              <>
                <div className="hidden lg:block w-px h-28 bg-slate-100 dark:bg-white/5" />
                <div className="hidden lg:block flex-shrink-0 w-52">
                  <p className="text-[10px] font-bold uppercase tracking-wider text-slate-400 mb-3 text-center">Simplification Funnel</p>
                  <SimplificationFunnel stages={funnelStages} />
                </div>
              </>
            )}
          </div>
        </CardContent>
      </Card>
    </motion.div>
  );
};
