/**
 * Portfolio Intelligence — the new Fund Overlap tab.
 *
 * Replaces the old category-proxy OverlapTab with real stock-level overlap,
 * compression score, top-stock overexposure, redundancy suggestions, and
 * AI-narrated insights. Includes a what-if "Remove fund" simulator.
 */
import React, { useState, useEffect, useCallback, useMemo } from "react";
import { useNavigate } from "react-router-dom";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  Sparkles, TrendingUp, Layers, AlertTriangle, Target, Zap,
  RefreshCw, Minus, ChevronRight, Info, ExternalLink
} from "lucide-react";
import { toast } from "sonner";
import V3PortfolioInsights from "./V3PortfolioInsights";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

const fmt = (n) => {
  if (n == null) return "—";
  const v = Number(n);
  if (v >= 1e7) return `₹${(v / 1e7).toFixed(2)} Cr`;
  if (v >= 1e5) return `₹${(v / 1e5).toFixed(2)} L`;
  if (v >= 1e3) return `₹${(v / 1e3).toFixed(1)} K`;
  return `₹${Math.round(v)}`;
};

const colorFor = (pct) => {
  if (pct >= 60) return "bg-rose-500";
  if (pct >= 35) return "bg-amber-500";
  if (pct >= 15) return "bg-sky-500";
  return "bg-emerald-500";
};

// ── Hero compression card ────────────────────────────────────────────────
const CompressionHero = ({ narrative, compression }) => {
  const navigate = useNavigate();
  const score = compression?.score ?? 0;
  const tone = score >= 70 ? "emerald" : score >= 50 ? "sky" : score >= 30 ? "amber" : "rose";
  const toneCls = {
    emerald: "from-emerald-500/15 to-emerald-500/5 border-emerald-400/40 text-emerald-400",
    sky:     "from-sky-500/15 to-sky-500/5 border-sky-400/40 text-sky-400",
    amber:   "from-amber-500/15 to-amber-500/5 border-amber-400/40 text-amber-400",
    rose:    "from-rose-500/15 to-rose-500/5 border-rose-400/40 text-rose-400",
  }[tone];
  const label = score >= 70 ? "Efficient" : score >= 50 ? "Balanced" :
                score >= 30 ? "Concentrated" : "Highly Duplicated";
  return (
    <Card className={`bg-gradient-to-br ${toneCls} border rounded-2xl`}>
      <CardContent className="p-6 sm:p-8">
        <div className="flex flex-col sm:flex-row items-start gap-6">
          {/* Ring */}
          <div className="relative w-32 h-32 shrink-0" data-testid="pi-compression-ring">
            <svg viewBox="0 0 100 100" className="w-full h-full -rotate-90">
              <circle cx="50" cy="50" r="44" className="stroke-slate-200 dark:stroke-slate-800/40" strokeWidth="8" fill="none" />
              <circle
                cx="50" cy="50" r="44"
                className={`stroke-current transition-all duration-500`}
                strokeWidth="8" fill="none"
                strokeLinecap="round"
                strokeDasharray={`${(score / 100) * 276} 276`}
              />
            </svg>
            <div className="absolute inset-0 flex flex-col items-center justify-center">
              <div className="text-3xl font-bold text-slate-900 dark:text-white" data-testid="pi-compression-score">{score.toFixed(0)}</div>
              <div className="text-[10px] uppercase tracking-wider text-slate-600 dark:text-slate-300">Efficiency</div>
            </div>
          </div>
          <div className="flex-1 min-w-0">
            <div className="text-xs uppercase tracking-wider text-slate-600 dark:text-slate-300 mb-2">{label}</div>
            <h2 className="text-xl sm:text-2xl font-semibold text-slate-900 dark:text-white leading-snug mb-2">
              Your {fmt(narrative?.total_invested_rs)} portfolio behaves like {fmt(narrative?.behaves_like_rs)} due to overlap.
            </h2>
            <div className="text-sm text-slate-700 dark:text-slate-200/90">
              You hold <b>{narrative?.unique_stocks}</b> unique stocks, but risk-and-return effectively come from just{" "}
              <b>{compression?.effective_stocks}</b> of them.
            </div>
            <div className="grid grid-cols-2 gap-3 mt-4">
              <div className="bg-slate-100 dark:bg-black/20 rounded-xl px-3 py-2 border border-slate-200 dark:border-white/5">
                <div className="text-[10px] uppercase tracking-wider text-slate-500 dark:text-slate-400">Top 10 stocks</div>
                <div className="text-lg font-semibold text-slate-900 dark:text-white">{compression?.top_10_exposure_pct}%</div>
              </div>
              <div className="bg-slate-100 dark:bg-black/20 rounded-xl px-3 py-2 border border-slate-200 dark:border-white/5">
                <div className="text-[10px] uppercase tracking-wider text-slate-500 dark:text-slate-400">Top 20 stocks</div>
                <div className="text-lg font-semibold text-slate-900 dark:text-white">{compression?.top_20_exposure_pct}%</div>
              </div>
            </div>
            <Button 
              data-testid="view-action-plan-intel-btn"
              onClick={() => navigate('/dashboard#plan_board')}
              className="mt-4 bg-slate-100 dark:bg-white/10 hover:bg-slate-200 dark:hover:bg-white/20 text-slate-900 dark:text-white border border-slate-300 dark:border-white/20"
              size="sm"
            >
              <ExternalLink className="w-4 h-4 mr-2" />
              View Action Plan
            </Button>
          </div>
        </div>
      </CardContent>
    </Card>
  );
};

// ── AI insight card ──────────────────────────────────────────────────────
const ICONS_BY_TYPE = {
  compression: Zap, top_stock: Target, duplication: Layers,
  category_inefficiency: AlertTriangle, redundancy: Minus,
  sector_concentration: TrendingUp, risk_adjusted: Sparkles,
};

const InsightCard = ({ ins }) => {
  const Icon = ICONS_BY_TYPE[ins.type] || Sparkles;
  return (
    <div className="flex items-start gap-3 p-4 rounded-xl bg-slate-100 dark:bg-slate-800/50 border border-slate-200 dark:border-slate-700 hover:border-slate-300 dark:hover:border-slate-600 transition"
         data-testid={`pi-insight-${ins.type}`}>
      <div className="w-9 h-9 rounded-lg bg-indigo-500/20 flex items-center justify-center shrink-0">
        <Icon className="w-4 h-4 text-indigo-300" />
      </div>
      <div className="min-w-0 flex-1">
        <div className="text-sm font-medium text-slate-900 dark:text-white leading-snug">{ins.headline}</div>
        {ins.detail && <div className="text-xs text-slate-500 dark:text-slate-400 mt-1">{ins.detail}</div>}
      </div>
    </div>
  );
};

// ── Top stocks table ─────────────────────────────────────────────────────
const TopStocksPanel = ({ stocks }) => (
  <Card className="bg-white dark:bg-slate-900 border-slate-200 dark:border-slate-800 rounded-2xl">
    <CardContent className="p-5">
      <div className="flex items-center gap-2 mb-3">
        <Target className="w-4 h-4 text-amber-400" />
        <h3 className="text-sm font-semibold text-slate-900 dark:text-white">Top stock exposure (look-through)</h3>
      </div>
      <p className="text-xs text-slate-500 dark:text-slate-400 mb-4">
        Aggregate of every underlying stock across all your mutual funds.
      </p>
      {stocks.length === 0 ? (
        <div className="text-xs text-slate-500">No data.</div>
      ) : (
        <div className="space-y-2">
          {stocks.slice(0, 10).map((s, i) => (
            <div key={s.key} className="grid grid-cols-12 gap-2 items-center text-xs py-1.5 border-b border-slate-200 dark:border-slate-800 last:border-b-0"
                 data-testid={`pi-top-stock-${i}`}>
              <div className="col-span-5 min-w-0">
                <div className="text-slate-900 dark:text-white truncate font-medium">{s.name}</div>
                <div className="text-[10px] text-slate-500">{s.sector || "—"}</div>
              </div>
              <div className="col-span-5">
                <div className="h-2 w-full rounded-full bg-slate-200 dark:bg-slate-800 overflow-hidden">
                  <div className={`h-full ${colorFor(s.exposure_pct * 4)}`}
                       style={{ width: `${Math.min(s.exposure_pct * 10, 100)}%` }} />
                </div>
              </div>
              <div className="col-span-2 text-right">
                <div className="text-slate-900 dark:text-white font-mono">{s.exposure_pct.toFixed(2)}%</div>
                <div className="text-[10px] text-slate-500">{fmt(s.exposure_rs)} · {s.fund_count}f</div>
              </div>
            </div>
          ))}
        </div>
      )}
    </CardContent>
  </Card>
);

// ── Pairwise heatmap with drill-down ────────────────────────────────────
const PairsHeatmap = ({ pairs, catalog }) => {
  const [expandedPair, setExpandedPair] = useState(null);
  const top = pairs.slice(0, 15);
  
  const togglePair = (pairKey) => {
    setExpandedPair(expandedPair === pairKey ? null : pairKey);
  };

  const getHoldingDetails = (mfId, stockKey) => {
    const fund = catalog?.[mfId];
    if (!fund) return null;
    const holding = fund.holdings?.find(
      h => (h.holding_stock_slug || h.holding_name || "").toLowerCase() === stockKey
    );
    return holding;
  };

  return (
    <Card className="bg-white dark:bg-slate-900 border-slate-200 dark:border-slate-800 rounded-2xl">
      <CardContent className="p-5">
        <div className="flex items-center gap-2 mb-3">
          <Layers className="w-4 h-4 text-indigo-400" />
          <h3 className="text-sm font-semibold text-slate-900 dark:text-white">Fund-to-fund overlap (real stock-level)</h3>
        </div>
        <p className="text-xs text-slate-500 dark:text-slate-400 mb-4">
          Overlap(A,B) = Σ min(weight_A, weight_B). Red pairs are candidates for consolidation. Click to see details.
        </p>
        {top.length === 0 ? (
          <div className="text-xs text-slate-500">Need 2+ resolved funds.</div>
        ) : (
          <div className="space-y-2">
            {top.map((p, i) => {
              const pairKey = `${p.a}-${p.b}`;
              const isExpanded = expandedPair === pairKey;
              return (
                <div key={pairKey} data-testid={`pi-pair-${i}`}>
                  <button
                    onClick={() => togglePair(pairKey)}
                    className="w-full grid grid-cols-12 gap-2 items-center text-xs py-1.5 border-b border-slate-200 dark:border-slate-800 hover:bg-slate-100 dark:bg-slate-800/30 transition cursor-pointer"
                  >
                    <div className="col-span-5 min-w-0 text-slate-900 dark:text-white truncate text-left">{p.a_name}</div>
                    <div className="col-span-1 text-center text-slate-500">↔</div>
                    <div className="col-span-4 min-w-0 text-slate-900 dark:text-white truncate text-left">{p.b_name}</div>
                    <div className="col-span-2 text-right">
                      <span className={`inline-block px-2 py-0.5 rounded-full text-[10px] font-semibold ${colorFor(p.overlap_pct)} text-slate-900 dark:text-white`}>
                        {p.overlap_pct.toFixed(1)}%
                      </span>
                      <div className="text-[10px] text-slate-500 mt-0.5">{p.shared_count} shared</div>
                    </div>
                  </button>
                  
                  {/* Drill-down details */}
                  {isExpanded && (
                    <div className="mt-2 p-3 rounded-xl bg-slate-100 dark:bg-slate-800/40 border border-slate-200 dark:border-slate-700 space-y-2"
                         data-testid={`pi-pair-drilldown-${i}`}>
                      <div className="text-xs font-medium text-indigo-300 mb-2">
                        Shared stocks ({p.shared_count}):
                      </div>
                      {p.top_shared?.slice(0, 10).map((stock, idx) => {
                        const holdingA = getHoldingDetails(p.a, stock.key);
                        const holdingB = getHoldingDetails(p.b, stock.key);
                        const isDeadA = holdingA?.holding_type?.toLowerCase() === "dead";
                        const isDeadB = holdingB?.holding_type?.toLowerCase() === "dead";
                        
                        return (
                          <div key={idx} className="grid grid-cols-12 gap-2 text-[10px] py-1.5 border-b border-slate-200 dark:border-slate-700 last:border-0">
                            <div className="col-span-5 text-slate-200">
                              {stock.key}
                              {(isDeadA || isDeadB) && (
                                <span className="ml-1 text-rose-400 font-semibold">💀 DEAD</span>
                              )}
                            </div>
                            <div className="col-span-3 text-right">
                              <span className="text-sky-300">{stock.w_a.toFixed(2)}%</span>
                              <span className="text-slate-500 ml-1 text-[9px]">
                                ({holdingA?.holding_type?.includes("Direct") ? "Direct" : "Regular"})
                              </span>
                            </div>
                            <div className="col-span-3 text-right">
                              <span className="text-amber-300">{stock.w_b.toFixed(2)}%</span>
                              <span className="text-slate-500 ml-1 text-[9px]">
                                ({holdingB?.holding_type?.includes("Direct") ? "Direct" : "Regular"})
                              </span>
                            </div>
                            <div className="col-span-1 text-right text-slate-500 dark:text-slate-400">
                              {stock.shared_w.toFixed(1)}
                            </div>
                          </div>
                        );
                      })}
                      
                      {p.reasons && p.reasons.length > 0 && (
                        <div className="mt-2 pt-2 border-t border-slate-200 dark:border-slate-700">
                          <div className="text-[10px] text-amber-300">
                            ⚠️ {p.reasons.join(" · ")}
                          </div>
                        </div>
                      )}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </CardContent>
    </Card>
  );
};

// ── Redundancy suggestions ──────────────────────────────────────────────
const RedundancyPanel = ({ items, onSimulate, simulating, simRemoved }) => (
  <Card className="bg-white dark:bg-slate-900 border-slate-200 dark:border-slate-800 rounded-2xl">
    <CardContent className="p-5">
      <div className="flex items-center gap-2 mb-3">
        <Minus className="w-4 h-4 text-rose-400" />
        <h3 className="text-sm font-semibold text-slate-900 dark:text-white">Redundancy — remove to optimise</h3>
      </div>
      <p className="text-xs text-slate-500 dark:text-slate-400 mb-4">
        Click a fund to simulate removing it. Lower sector drift = safer removal.
      </p>
      {items.length === 0 ? (
        <div className="text-xs text-slate-500">Need 3+ mutual funds to suggest.</div>
      ) : (
        <div className="space-y-2">
          {items.map((r) => {
            const active = simRemoved.includes(r.remove_id);
            return (
              <button
                key={r.remove_id}
                onClick={() => onSimulate(r.remove_id)}
                disabled={simulating}
                className={`w-full text-left p-3 rounded-xl border transition ${
                  active
                    ? "bg-rose-500/10 border-rose-400/50"
                    : "bg-slate-100 dark:bg-slate-800/50 border-slate-200 dark:border-slate-700 hover:border-slate-500"
                } disabled:opacity-50`}
                data-testid={`pi-redund-${r.remove_id}`}
              >
                <div className="flex items-center justify-between gap-2">
                  <div className="min-w-0 flex-1">
                    <div className="text-sm text-slate-900 dark:text-white font-medium truncate">
                      {active ? "Removed · " : ""}{r.remove_name}
                    </div>
                    <div className="text-[10px] text-slate-500 dark:text-slate-400 mt-0.5">
                      {fmt(r.remove_amount_rs)} · sector drift {r.sector_l1_drift_pct}%
                    </div>
                  </div>
                  <div className="text-right shrink-0">
                    <div className="text-sm font-semibold text-rose-300">
                      −{r.overlap_reduced_pp} pp
                    </div>
                    <div className="text-[10px] text-slate-500">overlap</div>
                  </div>
                </div>
              </button>
            );
          })}
        </div>
      )}
    </CardContent>
  </Card>
);

// ── Category & sector strips ────────────────────────────────────────────
const CategoryStrip = ({ items, ratings }) => {
  const ratingByCat = Object.fromEntries((ratings || []).map(r => [r.category, r]));
  return (
    <Card className="bg-white dark:bg-slate-900 border-slate-200 dark:border-slate-800 rounded-2xl">
      <CardContent className="p-5">
        <div className="flex items-center gap-2 mb-3">
          <AlertTriangle className="w-4 h-4 text-amber-400" />
          <h3 className="text-sm font-semibold text-slate-900 dark:text-white">Category ratings & efficiency</h3>
        </div>
        {(items.length === 0 && (ratings?.length || 0) === 0) ? (
          <div className="text-xs text-slate-500">No category data yet.</div>
        ) : (
          <div className="space-y-3">
            {(ratings || items.map(i => ({ category: i.category, rating: 3, funds_count: i.funds_count, avg_pair_overlap: i.avg_pair_overlap, invested_rs: i.invested_rs, reason: "" }))).map((r) => {
              const cat = items.find(i => i.category === r.category) || {};
              const stars = "★".repeat(r.rating) + "☆".repeat(5 - r.rating);
              const tone = r.rating >= 4 ? "text-emerald-400" :
                           r.rating >= 3 ? "text-sky-400" :
                           r.rating >= 2 ? "text-amber-400" : "text-rose-400";
              return (
                <div key={r.category}
                     className="border-b border-slate-200 dark:border-slate-800 last:border-b-0 pb-3 last:pb-0"
                     data-testid={`pi-cat-${r.category}`}>
                  <div className="flex items-center justify-between gap-2">
                    <div className="min-w-0">
                      <div className="text-sm text-slate-900 dark:text-white font-medium">{r.category}</div>
                      <div className="text-[10px] text-slate-500">
                        {r.funds_count} funds · {fmt(r.invested_rs)}
                        {r.avg_pair_overlap != null && ` · ${r.avg_pair_overlap}% avg overlap`}
                      </div>
                    </div>
                    <div className={`text-sm font-semibold ${tone} tracking-wider shrink-0`}>{stars}</div>
                  </div>
                  {r.reason && <div className="text-[11px] text-slate-500 dark:text-slate-400 mt-1.5 leading-snug">{r.reason}</div>}
                </div>
              );
            })}
          </div>
        )}
      </CardContent>
    </Card>
  );
};

const SectorStrip = ({ items }) => (
  <Card className="bg-white dark:bg-slate-900 border-slate-200 dark:border-slate-800 rounded-2xl">
    <CardContent className="p-5">
      <div className="flex items-center gap-2 mb-3">
        <TrendingUp className="w-4 h-4 text-sky-400" />
        <h3 className="text-sm font-semibold text-slate-900 dark:text-white">Look-through sector exposure</h3>
      </div>
      <div className="space-y-1.5">
        {items.slice(0, 8).map((s) => (
          <div key={s.sector} className="grid grid-cols-12 gap-2 items-center text-xs" data-testid={`pi-sec-${s.sector}`}>
            <div className="col-span-4 truncate text-slate-900 dark:text-white">{s.sector}</div>
            <div className="col-span-6">
              <div className="h-2 rounded-full bg-slate-200 dark:bg-slate-800 overflow-hidden">
                <div className="h-full bg-sky-500" style={{ width: `${Math.min(s.pct * 3, 100)}%` }} />
              </div>
            </div>
            <div className="col-span-2 text-right text-slate-600 dark:text-slate-300 font-mono">{s.pct.toFixed(1)}%</div>
          </div>
        ))}
      </div>
    </CardContent>
  </Card>
);

// ── Main tab ────────────────────────────────────────────────────────────
export default function PortfolioIntelligenceTab() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [simulating, setSimulating] = useState(false);
  const [simRemoved, setSimRemoved] = useState([]);
  const [simData, setSimData] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await fetch(`${API}/intelligence/portfolio?narrate=true`, { credentials: "include" });
      if (!r.ok) throw new Error(r.statusText);
      const d = await r.json();
      setData(d);
    } catch (e) {
      toast.error(`Intelligence load failed: ${e.message}`);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const runSimulate = async (id) => {
    const next = simRemoved.includes(id)
      ? simRemoved.filter((x) => x !== id)
      : [...simRemoved, id];
    setSimRemoved(next);
    if (next.length === 0) { setSimData(null); return; }
    setSimulating(true);
    try {
      const r = await fetch(`${API}/intelligence/simulate`, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ remove_mf_ids: next }),
      });
      const d = await r.json();
      setSimData(d);
      toast.success(`Removed ${next.length} fund(s) — overlap ${data?.compression?.score} → ${d?.compression?.score}`);
    } catch (e) {
      toast.error(`Simulation failed: ${e.message}`);
    } finally {
      setSimulating(false);
    }
  };

  const view = useMemo(() => {
    if (!data) return null;
    if (simData) {
      return {
        narrative: simData.narrative,
        compression: simData.compression,
        pairs: simData.pairwise_overlap || [],
        top: simData.top_stocks || [],
        cats: simData.category_inefficiency || [],
        sectors: simData.sector_exposure || [],
        ai_insights: data.ai_insights || [],
        redundancy: data.redundancy_suggestions || [],
        ratings: data.category_ratings || [],
        catalog: data.catalog || {},
      };
    }
    return {
      narrative: data.narrative,
      compression: data.compression,
      pairs: data.pairwise_overlap || [],
      top: data.top_stocks || [],
      cats: data.category_inefficiency || [],
      sectors: data.sector_exposure || [],
      ai_insights: data.ai_insights || [],
      redundancy: data.redundancy_suggestions || [],
      ratings: data.category_ratings || [],
      catalog: data.catalog || {},
    };
  }, [data, simData]);

  if (loading && !data) {
    return <div className="flex justify-center py-12"><div className="w-8 h-8 border-2 border-indigo-500 border-t-transparent rounded-full animate-spin" /></div>;
  }

  if (data?.empty) {
    return (
      <Card className="bg-white dark:bg-slate-900 border-slate-200 dark:border-slate-800 rounded-2xl">
        <CardContent className="p-10 text-center">
          <Info className="w-8 h-8 text-slate-500 mx-auto mb-2" />
          <div className="text-sm text-slate-600 dark:text-slate-300">{data.reason || "No mutual fund data yet."}</div>
          <div className="text-xs text-slate-500 mt-1">Upload your CAS statement to unlock portfolio intelligence.</div>
        </CardContent>
      </Card>
    );
  }

  if (!view) {
    return <div className="flex justify-center py-12"><div className="w-8 h-8 border-2 border-indigo-500 border-t-transparent rounded-full animate-spin" /></div>;
  }

  return (
    <div className="space-y-5" data-testid="portfolio-intelligence-tab">
      {/* Sim banner */}
      {simRemoved.length > 0 && (
        <div className="flex items-center justify-between p-3 rounded-xl bg-rose-500/10 border border-rose-400/30 text-sm"
             data-testid="pi-sim-banner">
          <span className="text-rose-200">
            <Minus className="w-4 h-4 inline mr-1" />
            Simulating removal of {simRemoved.length} fund(s) — click again to restore
          </span>
          <Button variant="ghost" size="sm" onClick={() => { setSimRemoved([]); setSimData(null); }}>
            Reset
          </Button>
        </div>
      )}

      <CompressionHero narrative={view?.narrative} compression={view?.compression} />

      {/* AI insights */}
      {view?.ai_insights?.length > 0 && (
        <Card className="bg-white dark:bg-slate-900 border-slate-200 dark:border-slate-800 rounded-2xl">
          <CardContent className="p-5">
            <div className="flex items-center gap-2 mb-4">
              <Sparkles className="w-4 h-4 text-indigo-400" />
              <h3 className="text-sm font-semibold text-slate-900 dark:text-white">AI Insights</h3>
              <Badge variant="outline" className="ml-auto text-[10px]">GPT-4o</Badge>
              <Button variant="ghost" size="sm" onClick={load} data-testid="pi-refresh">
                <RefreshCw className="w-3.5 h-3.5" />
              </Button>
            </div>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              {view?.ai_insights?.map((ins, i) => <InsightCard key={i} ins={ins} />)}
            </div>
          </CardContent>
        </Card>
      )}

      {/* 2-col grid */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
        <TopStocksPanel stocks={view?.top || []} />
        <PairsHeatmap pairs={view?.pairs || []} catalog={view?.catalog || {}} />
        <RedundancyPanel items={view?.redundancy || []} onSimulate={runSimulate}
                         simulating={simulating} simRemoved={simRemoved} />
        <div className="space-y-5">
          <CategoryStrip items={view?.cats || []} ratings={view?.ratings || []} />
          <SectorStrip items={view?.sectors || []} />
        </div>
      </div>

      {/* V3 Engine — fund-level composite scoring (Quality/Health/Exit/Add) */}
      <div data-testid="pi-v3-section">
        <V3PortfolioInsights />
      </div>
    </div>
  );
}

// silence unused icons
void ChevronRight;
