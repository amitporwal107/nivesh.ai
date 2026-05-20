import React, { useMemo } from "react";
import {
  ScatterChart, Scatter, XAxis, YAxis, ZAxis,
  CartesianGrid, Tooltip, ResponsiveContainer, ReferenceLine,
  BarChart, Bar, Cell, LabelList,
} from "recharts";
import { motion } from "framer-motion";
import { Card, CardContent } from "@/components/ui/card";
import {
  TrendingDown, AlertTriangle, CheckCircle,
  Layers, ArrowRight, Repeat, Rocket, Receipt,
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
// 3. ACTION MATRIX — Priority board
//    Phase 1: Consolidate (overlap-driven) + Review / Exit / Increase / Core.
//    Buckets ranked by potential impact (₹ at risk / opportunity).
// ──────────────────────────────────────────────────────────
const BUCKET_CONFIG = {
  consolidate: { label: "Consolidate", sub: "Overlapping funds — merge into best performer", icon: Repeat,         color: "#A78BFA", border: "border-violet-500/25 bg-violet-500/5" },
  tax:         { label: "Tax Watch",   sub: "Exit candidates with material STCG cost or close to LTCG", icon: Receipt, color: "#FB923C", border: "border-orange-500/25 bg-orange-500/5" },
  review:      { label: "Review",      sub: "Heavy weight, weak return — evaluate alternatives", icon: AlertTriangle, color: "#F59E0B", border: "border-amber-500/25 bg-amber-500/5"  },
  exit:        { label: "Exit",        sub: "Low weight + weak return — trim clutter",          icon: TrendingDown,  color: "#EF4444", border: "border-red-500/25 bg-red-500/5"     },
  increase:    { label: "Increase",    sub: "Strong return, low weight — consider scaling up",  icon: Rocket,        color: "#38BDF8", border: "border-sky-500/25 bg-sky-500/5"     },
  core:        { label: "Core / Add",  sub: "Strong return, significant weight — keep / add",   icon: CheckCircle,   color: "#10B981", border: "border-emerald-500/25 bg-emerald-500/5" },
};

// Derive a short tax-status label + colour for an individual card row.
// Returns null when the tax payload is missing or the card is in a neutral
// state (already LTCG-eligible, or no buy_date). Never invents data.
const taxBadge = (card) => {
  const t = card?.tax;
  if (!t) return null;
  if (t.is_loss) return { text: "Loss", cls: "text-sky-400 bg-sky-500/10 border-sky-500/20" };
  if (t.tier === "LIKELY_STCG" && t.days_to_ltcg > 0 && t.days_to_ltcg <= 60) {
    return { text: `LTCG ${t.days_to_ltcg}d`, cls: "text-amber-400 bg-amber-500/10 border-amber-500/20" };
  }
  if (t.tier === "LIKELY_STCG" && (card.pct_return || 0) > 5) {
    return { text: "STCG", cls: "text-red-400 bg-red-500/10 border-red-500/20" };
  }
  return null;
};

// Impact score: how much money sits in this row × how far it strays from peers.
// Used to surface the highest-leverage rows inside each bucket.
const impactScore = (card, medR) => {
  const w = Math.max(0, card.weight || 0);
  const gap = Math.abs((card.pct_return || 0) - medR);
  return w * (gap + 1); // +1 keeps tie-broken by weight when at-median
};

const truncateName = (s, n = 26) => (s && s.length > n ? s.slice(0, n) + "…" : (s || ""));

export const ActionMatrix = ({ perfCards, overlapMatrix, fundPerformance }) => {
  // Map fund name → server-computed alternative payload. Populated only when
  // fundPerformance has been fetched (lazy in InsightsView). Null-safe.
  const altByName = useMemo(() => {
    const m = new Map();
    (fundPerformance?.fund_ratings || []).forEach(r => {
      if (r.alternative) m.set(r.name, r.alternative);
    });
    return m;
  }, [fundPerformance]);

  const totalUplift = fundPerformance?.total_uplift_per_year_rs || 0;

  const { buckets, medR, medW, totalValue } = useMemo(() => {
    const cards = (perfCards || []).filter(c => c.invested > 0);
    if (!cards.length) return { buckets: {}, medR: 0, medW: 0, totalValue: 0 };
    const medR = median(cards.map(c => c.pct_return || 0));
    const medW = median(cards.map(c => c.weight || 0));
    const totalValue = cards.reduce((s, c) => s + (c.current_value || 0), 0);

    // Index funds by name so overlap pairs can map back to underlying invested ₹.
    const byName = new Map();
    cards.forEach(c => byName.set(c.name, c));

    // Consolidate from real pairwise overlap (>= 40% is "high overlap" threshold
    // used elsewhere in this codebase — see services/copilot_tools/portfolio.py).
    const highPairs = (overlapMatrix || [])
      .filter(p => (p.overlap_pct || 0) >= 40)
      .slice(0, 12);
    const consolidateFundNames = new Set();
    let consolidateValue = 0;
    highPairs.forEach(p => {
      [p.fund_a, p.fund_b, p.fund1, p.fund2].forEach(n => {
        if (!n || consolidateFundNames.has(n)) return;
        consolidateFundNames.add(n);
        const c = byName.get(n);
        if (c) consolidateValue += (c.current_value || 0);
      });
    });

    const review = [], exit_ = [], increase = [], core = [];
    cards.forEach(c => {
      const r = c.pct_return || 0;
      const w = c.weight || 0;
      const highReturn = r >= medR;
      const highWeight = w >= medW;
      if (highReturn && highWeight) core.push(c);
      else if (highReturn && !highWeight) increase.push(c);
      else if (!highReturn && highWeight) review.push(c);
      else exit_.push(c);
    });

    const sortByImpact = (arr) => [...arr].sort((a, b) => impactScore(b, medR) - impactScore(a, medR));

    const bucketValue = (arr) => arr.reduce((s, c) => s + (c.current_value || 0), 0);

    // Tax Watch — overlay across Exit/Review surfacing high-tax-leverage rows.
    // Inclusion rule: holdings we'd otherwise tell the user to trim (in Exit
    // or Review) where exiting *now* triggers real STCG, OR they are close
    // enough to LTCG that waiting is materially cheaper.
    // Sort: "approaching LTCG" first (smallest days_to_ltcg), then by ₹ gain.
    const taxCandidates = [...exit_, ...review].filter(c => {
      const t = c.tax;
      if (!t || t.is_loss) return false;
      if (t.tier !== "LIKELY_STCG") return false;
      const gain = (c.current_value || 0) - (c.invested || 0);
      const approachingLtcg = t.days_to_ltcg > 0 && t.days_to_ltcg <= 60;
      const materialGain = gain > 5000 || (c.pct_return || 0) > 10;
      return approachingLtcg || materialGain;
    });
    const taxSorted = taxCandidates.sort((a, b) => {
      const da = a.tax?.days_to_ltcg ?? 99999;
      const db = b.tax?.days_to_ltcg ?? 99999;
      const aApproaching = da > 0 && da <= 60;
      const bApproaching = db > 0 && db <= 60;
      if (aApproaching !== bApproaching) return aApproaching ? -1 : 1;
      if (aApproaching && bApproaching) return da - db;
      // Otherwise rank by absolute ₹ gain
      const ag = (a.current_value || 0) - (a.invested || 0);
      const bg = (b.current_value || 0) - (b.invested || 0);
      return bg - ag;
    });

    return {
      buckets: {
        consolidate: {
          pairs: highPairs,
          fund_count: consolidateFundNames.size,
          value: consolidateValue,
        },
        tax:      { funds: taxSorted,              value: bucketValue(taxSorted) },
        review:   { funds: sortByImpact(review),   value: bucketValue(review) },
        exit:     { funds: sortByImpact(exit_),    value: bucketValue(exit_) },
        increase: { funds: sortByImpact(increase), value: bucketValue(increase) },
        core:     { funds: sortByImpact(core),     value: bucketValue(core) },
      },
      medR, medW, totalValue,
    };
  }, [perfCards, overlapMatrix]);

  const cards = (perfCards || []).filter(c => c.invested > 0);
  if (!cards.length) return <p className="text-sm text-slate-400 text-center py-8">No holdings data</p>;

  const pctOfPortfolio = (v) => totalValue > 0 ? ` · ${((v / totalValue) * 100).toFixed(0)}%` : "";

  // Only show tax badges + alternatives in buckets where exit/switch is a live recommendation.
  const renderFundBucket = (key) => {
    const cfg = BUCKET_CONFIG[key];
    const b = buckets[key] || { funds: [], value: 0 };
    const Icon = cfg.icon;
    const withBadges = key === "exit" || key === "review";
    const withAlts = key === "exit" || key === "review";
    return (
      <div key={key} className={`rounded-xl p-3 border ${cfg.border}`}>
        <div className="flex items-center gap-1.5 mb-1">
          <Icon className="w-3.5 h-3.5" style={{ color: cfg.color }} />
          <span className="text-xs font-bold text-slate-900 dark:text-white">{cfg.label}</span>
          <span className="ml-auto text-[10px] font-bold text-slate-400">{b.funds.length}</span>
        </div>
        <p className="text-[10px] font-bold mb-1" style={{ color: cfg.color, fontFamily: "'JetBrains Mono', monospace" }}>
          {getFmtShort(b.value)}{pctOfPortfolio(b.value)}
        </p>
        <p className="text-[9px] text-slate-400 mb-2">{cfg.sub}</p>
        <div className="space-y-1 max-h-[110px] overflow-y-auto">
          {b.funds.slice(0, 5).map((f, i) => {
            const badge = withBadges ? taxBadge(f) : null;
            const alt = withAlts ? altByName.get(f.name) : null;
            return (
              <div key={i} className="flex flex-col gap-px">
                <div className="flex items-center justify-between gap-1">
                  <p className="text-[9px] text-slate-500 dark:text-zinc-400 truncate flex-1">{truncateName(f.name, badge ? 18 : 24)}</p>
                  {badge && (
                    <span className={`text-[8px] font-semibold px-1 py-px rounded border ${badge.cls} flex-shrink-0`}>{badge.text}</span>
                  )}
                  <span className={`text-[9px] font-bold flex-shrink-0 ${f.pct_return >= 0 ? "text-emerald-500" : "text-red-400"}`}>
                    {f.pct_return >= 0 ? "+" : ""}{f.pct_return?.toFixed(0)}%
                  </span>
                </div>
                {alt && (
                  <div className="flex items-center gap-1 pl-2 -mt-px">
                    <ArrowRight className="w-2.5 h-2.5 text-emerald-500/80 flex-shrink-0" />
                    <p className="text-[8px] text-slate-500 dark:text-zinc-500 truncate flex-1" title={`${alt.name} · ${alt.confidence} confidence`}>
                      {truncateName(alt.name, 22)}
                    </p>
                    <span className="text-[8px] font-bold text-emerald-500 flex-shrink-0">+{getFmtShort(alt.uplift_per_year_rs)}/yr</span>
                  </div>
                )}
              </div>
            );
          })}
          {b.funds.length > 5 && (
            <p className="text-[9px] text-slate-500 text-center">+{b.funds.length - 5} more</p>
          )}
          {b.funds.length === 0 && (
            <p className="text-[9px] text-slate-500 text-center italic">None</p>
          )}
        </div>
      </div>
    );
  };

  // Tax Watch as a full-width priority row (only shown when candidates exist).
  const renderTaxRow = () => {
    const cfg = BUCKET_CONFIG.tax;
    const b = buckets.tax || { funds: [], value: 0 };
    if (!b.funds.length) return null;
    const Icon = cfg.icon;
    const approachingCount = b.funds.filter(f => {
      const d = f.tax?.days_to_ltcg ?? 0;
      return d > 0 && d <= 60;
    }).length;
    return (
      <div className={`rounded-xl p-3 border ${cfg.border} mb-2`}>
        <div className="flex items-center gap-1.5 mb-1">
          <Icon className="w-3.5 h-3.5" style={{ color: cfg.color }} />
          <span className="text-xs font-bold text-slate-900 dark:text-white">{cfg.label}</span>
          <span className="ml-auto text-[10px] font-bold text-slate-400">
            {b.funds.length} fund{b.funds.length === 1 ? "" : "s"}
            {approachingCount > 0 && ` · ${approachingCount} ≤ 60d to LTCG`}
          </span>
        </div>
        <p className="text-[10px] font-bold mb-1" style={{ color: cfg.color, fontFamily: "'JetBrains Mono', monospace" }}>
          {getFmtShort(b.value)}{pctOfPortfolio(b.value)} · stagger exits or wait for LTCG
        </p>
        <p className="text-[9px] text-slate-400 mb-2">{cfg.sub}</p>
        <div className="space-y-1 max-h-[80px] overflow-y-auto">
          {b.funds.slice(0, 4).map((f, i) => {
            const badge = taxBadge(f);
            return (
              <div key={i} className="flex items-center justify-between gap-1">
                <p className="text-[9px] text-slate-500 dark:text-zinc-400 truncate flex-1">{truncateName(f.name, 22)}</p>
                {badge && (
                  <span className={`text-[8px] font-semibold px-1 py-px rounded border ${badge.cls} flex-shrink-0`}>{badge.text}</span>
                )}
                <span className={`text-[9px] font-bold flex-shrink-0 ${f.pct_return >= 0 ? "text-emerald-500" : "text-red-400"}`}>
                  {f.pct_return >= 0 ? "+" : ""}{f.pct_return?.toFixed(0)}%
                </span>
              </div>
            );
          })}
          {b.funds.length > 4 && (
            <p className="text-[9px] text-slate-500 text-center">+{b.funds.length - 4} more</p>
          )}
        </div>
      </div>
    );
  };

  const con = buckets.consolidate || { pairs: [], fund_count: 0, value: 0 };
  const showConsolidate = con.pairs && con.pairs.length > 0;
  const conCfg = BUCKET_CONFIG.consolidate;
  const ConIcon = conCfg.icon;

  return (
    <div>
      <p className="text-[10px] text-slate-400 dark:text-zinc-500 mb-3">
        Ranked by potential impact. Median return {medR?.toFixed(1)}% · median weight {medW?.toFixed(1)}%
        {showConsolidate && ` · ${con.pairs.length} high-overlap pair${con.pairs.length === 1 ? "" : "s"}`}
      </p>

      {/* Aggregate uplift banner — sum of in-portfolio switch opportunities */}
      {totalUplift > 0 && (
        <div className="rounded-xl p-3 border border-emerald-500/25 bg-emerald-500/5 mb-2 flex items-center gap-3">
          <Rocket className="w-4 h-4 text-emerald-400 flex-shrink-0" />
          <div className="flex-1 min-w-0">
            <p className="text-xs font-bold text-slate-900 dark:text-white">Potential uplift</p>
            <p className="text-[9px] text-slate-400">
              If underperformers were re-allocated to better funds you already own (1Y category-rank basis)
            </p>
          </div>
          <p className="text-sm font-bold text-emerald-400 flex-shrink-0" style={{ fontFamily: "'JetBrains Mono', monospace" }}>
            +{getFmtShort(totalUplift)}/yr
          </p>
        </div>
      )}

      {/* Priority row: Consolidate (only shown when real overlap pairs exist) */}
      {showConsolidate && (
        <div className={`rounded-xl p-3 border ${conCfg.border} mb-2`}>
          <div className="flex items-center gap-1.5 mb-1">
            <ConIcon className="w-3.5 h-3.5" style={{ color: conCfg.color }} />
            <span className="text-xs font-bold text-slate-900 dark:text-white">{conCfg.label}</span>
            <span className="ml-auto text-[10px] font-bold text-slate-400">
              {con.pairs.length} pair{con.pairs.length === 1 ? "" : "s"} · {con.fund_count} fund{con.fund_count === 1 ? "" : "s"}
            </span>
          </div>
          <p className="text-[10px] font-bold mb-1" style={{ color: conCfg.color, fontFamily: "'JetBrains Mono', monospace" }}>
            {getFmtShort(con.value)}{pctOfPortfolio(con.value)} in overlapping funds
          </p>
          <p className="text-[9px] text-slate-400 mb-2">{conCfg.sub}</p>
          <div className="space-y-1 max-h-[80px] overflow-y-auto">
            {con.pairs.slice(0, 4).map((p, i) => {
              const a = p.fund_a || p.fund1 || "Fund A";
              const b = p.fund_b || p.fund2 || "Fund B";
              const pct = p.overlap_pct ?? 0;
              return (
                <div key={i} className="flex items-center justify-between gap-1">
                  <p className="text-[9px] text-slate-500 dark:text-zinc-400 truncate flex-1">
                    {truncateName(a, 18)} ↔ {truncateName(b, 18)}
                  </p>
                  <span className="text-[9px] font-bold flex-shrink-0 text-violet-400">
                    {pct.toFixed(0)}%
                  </span>
                </div>
              );
            })}
            {con.pairs.length > 4 && (
              <p className="text-[9px] text-slate-500 text-center">+{con.pairs.length - 4} more pairs</p>
            )}
          </div>
        </div>
      )}

      {/* Priority row 2: Tax Watch (only shown when STCG-cost candidates exist) */}
      {renderTaxRow()}

      {/* 2×2 grid: Review / Exit / Increase / Core */}
      <div className="grid grid-cols-2 gap-2">
        {(["review", "exit", "increase", "core"]).map(renderFundBucket)}
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
export const PerformanceAnalyticsCockpit = ({ perfCards, fundPerformance, portfolioHealth, overlapMatrix, fmt }) => {
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
                <ActionMatrix perfCards={cards} overlapMatrix={overlapMatrix} fundPerformance={fundPerformance} />
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
