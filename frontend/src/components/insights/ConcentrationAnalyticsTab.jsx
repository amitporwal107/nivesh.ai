/**
 * Diversification & Concentration Analytics tab content.
 *
 * Sections (flat, no collapsibles):
 *   1. AMC Exposure       — fund houses that dominate your MF book
 *   2. Sector Exposure    — sectors after dissolving MFs into look-through
 *   3. Company Exposure   — top underlying companies across direct + MFs
 *   4. MF Category Overlap — categories with 2+ funds (potential redundancy)
 *
 * Every bar row is click-to-drilldown — expands an inline detail panel.
 *
 * Endpoint: GET /api/portfolio/exposure/concentration
 */
import React, { useEffect, useState, useMemo } from "react";
import axios from "axios";
import { motion, AnimatePresence } from "framer-motion";
import {
  AlertTriangle, Building2, Layers, Briefcase,
  MessageSquare, TrendingUp, ChevronDown, ChevronUp,
  CheckCircle,
} from "lucide-react";
import { Card, CardContent } from "../ui/card";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

const fmtINR = (v) => {
  if (v == null || v === 0) return "—";
  if (v >= 1e7) return `₹${(v / 1e7).toFixed(2)} Cr`;
  if (v >= 1e5) return `₹${(v / 1e5).toFixed(2)} L`;
  return `₹${Math.round(v).toLocaleString("en-IN")}`;
};

const VIZ = [
  "#3D5AFE", "#1DE9B6", "#FFC400", "#FF4081", "#00BCD4", "#8BC34A",
  "#FF5722", "#9C27B0", "#03A9F4", "#FF9800", "#4CAF50", "#E91E63",
];

// ── Metric chip ───────────────────────────────────────────────────

const Metric = ({ label, value, tone = "ok", hint, testId }) => {
  const cls = {
    ok:   "bg-emerald-50 dark:bg-emerald-900/20 border-emerald-100 dark:border-emerald-900 text-emerald-700 dark:text-emerald-300",
    warn: "bg-amber-50 dark:bg-amber-900/20 border-amber-100 dark:border-amber-900 text-amber-700 dark:text-amber-300",
    info: "bg-sky-50 dark:bg-sky-900/20 border-sky-100 dark:border-sky-900 text-sky-700 dark:text-sky-300",
  }[tone];
  return (
    <div data-testid={testId} className={`rounded-xl border px-3 py-2 ${cls}`} title={hint || ""}>
      <div className="text-[10px] uppercase font-medium opacity-70 mb-0.5 tracking-wide">{label}</div>
      <div className="text-sm font-bold tabular-nums" style={{ fontFamily: "'JetBrains Mono', monospace" }}>{value}</div>
    </div>
  );
};

// ── Drilldown detail panel ────────────────────────────────────────

const DrilldownPanel = ({ item, kind }) => {
  if (!item) return null;

  const funds  = item.funds  || [];
  const holdings = item.holdings || [];

  return (
    <motion.div
      initial={{ opacity: 0, height: 0 }}
      animate={{ opacity: 1, height: "auto" }}
      exit={{ opacity: 0, height: 0 }}
      transition={{ duration: 0.2 }}
      className="overflow-hidden"
    >
      <div className="mt-2 ml-4 pl-3 border-l-2 border-slate-200 dark:border-white/10 space-y-1 pb-1">
        {kind === "amc" && funds.length > 0 && (
          <>
            <p className="text-[10px] font-semibold uppercase tracking-wider text-slate-400 dark:text-zinc-500 mb-1">
              Funds ({funds.length})
            </p>
            {funds.map((f, i) => (
              <p key={i} className="text-xs text-slate-600 dark:text-zinc-400 truncate leading-relaxed">{f}</p>
            ))}
          </>
        )}

        {kind === "sector" && (
          <>
            {(item.via?.direct || 0) > 0 && (
              <p className="text-xs text-slate-500 dark:text-zinc-500">
                Direct equity: <span className="font-medium text-slate-700 dark:text-zinc-300">{fmtINR(item.via.direct)}</span>
              </p>
            )}
            {(item.via?.mf || 0) > 0 && (
              <p className="text-xs text-slate-500 dark:text-zinc-500">
                Via mutual funds: <span className="font-medium text-slate-700 dark:text-zinc-300">{fmtINR(item.via.mf)}</span>
              </p>
            )}
            {holdings.length > 0 && (
              <>
                <p className="text-[10px] font-semibold uppercase tracking-wider text-slate-400 dark:text-zinc-500 mt-2 mb-1">
                  Contributing holdings
                </p>
                {holdings.slice(0, 8).map((h, i) => (
                  <p key={i} className="text-xs text-slate-600 dark:text-zinc-400 truncate leading-relaxed">{h}</p>
                ))}
                {holdings.length > 8 && (
                  <p className="text-[10px] text-slate-400">+{holdings.length - 8} more</p>
                )}
              </>
            )}
          </>
        )}

        {kind === "company" && (
          <>
            {(item.via_direct_inr || 0) > 0 && (
              <p className="text-xs text-slate-500 dark:text-zinc-500">
                Direct equity: <span className="font-medium text-slate-700 dark:text-zinc-300">{fmtINR(item.via_direct_inr)}</span>
              </p>
            )}
            {(item.via_funds_count || 0) > 0 && (
              <p className="text-xs text-slate-500 dark:text-zinc-500">
                Held via <span className="font-medium text-slate-700 dark:text-zinc-300">{item.via_funds_count}</span> mutual fund{item.via_funds_count !== 1 ? "s" : ""}
              </p>
            )}
            {item.sector && (
              <p className="text-xs text-slate-500 dark:text-zinc-500">
                Sector: <span className="font-medium text-slate-700 dark:text-zinc-300">{item.sector}</span>
              </p>
            )}
          </>
        )}
      </div>
    </motion.div>
  );
};

// ── Single exposure section ───────────────────────────────────────

const ExposureSection = ({
  title, subtitle, icon: Icon, accent,
  items, hhi, effectiveN, largestPct,
  warning, top10Pct, secondary,
  onAskNivesh, testId, kind,
}) => {
  const [expanded, setExpanded] = useState(null);

  if (!items || items.length === 0) return null;
  const maxPct = items[0]?.pct || 1;

  const toggle = (i) => setExpanded(prev => (prev === i ? null : i));

  return (
    <motion.section
      data-testid={testId}
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.25 }}
    >
      <Card className="bg-white dark:bg-[#111] border-slate-100 dark:border-white/5 rounded-2xl overflow-hidden">
        <CardContent className="p-5 md:p-6">
          {/* Header */}
          <div className="flex items-start justify-between gap-3 mb-4 flex-wrap">
            <div className="flex items-start gap-3 min-w-0">
              <div className={`flex-shrink-0 w-10 h-10 rounded-xl flex items-center justify-center ${accent}`}>
                <Icon className="w-5 h-5 text-white" strokeWidth={2} />
              </div>
              <div className="min-w-0">
                <h3 className="text-base font-bold text-slate-900 dark:text-white" style={{ fontFamily: "'Outfit', sans-serif" }}>
                  {title}
                </h3>
                <p className="text-xs text-slate-500 dark:text-zinc-500 mt-0.5">{subtitle}</p>
              </div>
            </div>
            {onAskNivesh && (
              <button
                data-testid={`${testId}-ask-nivesh`}
                onClick={onAskNivesh}
                className="text-xs px-2.5 py-1 rounded-full border border-slate-200 dark:border-white/10 text-slate-500 dark:text-zinc-400 hover:text-teal-600 dark:hover:text-teal-400 hover:border-teal-300 dark:hover:border-teal-700 transition-colors flex items-center gap-1 flex-shrink-0"
              >
                <MessageSquare className="w-3 h-3" /> Ask Nivesh
              </button>
            )}
          </div>

          {/* Metric chips */}
          <div className="grid grid-cols-3 gap-2 mb-4">
            <Metric label="Largest" value={`${largestPct?.toFixed(1) ?? "—"}%`} tone={largestPct > 30 ? "warn" : "ok"} testId={`${testId}-metric-largest`} />
            <Metric label="Effective #" value={effectiveN?.toFixed(1) ?? "—"} tone="info" testId={`${testId}-metric-effective-n`} hint="Equivalent equally-weighted count — higher is better" />
            <Metric label="HHI" value={hhi?.toFixed(3) ?? "—"} tone={hhi > 0.2 ? "warn" : "ok"} testId={`${testId}-metric-hhi`} hint="0 = perfectly diversified · 1 = single position" />
          </div>

          {/* Warning */}
          {warning && (
            <div data-testid={`${testId}-warning`} className="flex items-start gap-2 mb-4 px-3 py-2 rounded-xl bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-800 text-amber-700 dark:text-amber-300">
              <AlertTriangle className="w-4 h-4 flex-shrink-0 mt-0.5" />
              <p className="text-xs leading-relaxed">{warning}</p>
            </div>
          )}

          {/* Drillable bar list */}
          <div className="space-y-1" data-testid={`${testId}-items`}>
            {items.map((it, i) => {
              const wPct = Math.min(100, (it.pct / maxPct) * 100);
              const isOpen = expanded === i;
              const hasDrill = (it.funds?.length > 0) || (it.holdings?.length > 0) || (it.via_direct_inr > 0) || (it.via_funds_count > 0) || it.sector;
              return (
                <div key={`${it.name}-${i}`} data-testid={`${testId}-item-${i}`}>
                  <button
                    onClick={() => hasDrill && toggle(i)}
                    className={`w-full text-left group ${hasDrill ? "cursor-pointer" : "cursor-default"}`}
                  >
                    <div className="flex items-center justify-between gap-3 mb-1 py-1 rounded-lg px-1 -mx-1 hover:bg-slate-50 dark:hover:bg-white/[0.03] transition-colors">
                      <div className="flex items-center gap-2 min-w-0 flex-1">
                        <span className="inline-block w-2 h-2 rounded-full flex-shrink-0" style={{ background: VIZ[i % VIZ.length] }} />
                        <span className="text-sm font-medium text-slate-800 dark:text-zinc-200 truncate">{it.name}</span>
                        {it.sector && (
                          <span className="text-[10px] uppercase tracking-wider text-slate-400 dark:text-zinc-600 flex-shrink-0 hidden sm:inline">· {it.sector}</span>
                        )}
                        {it.count != null && (
                          <span className="text-[10px] text-slate-400 dark:text-zinc-600 flex-shrink-0">· {it.count} fund{it.count !== 1 ? "s" : ""}</span>
                        )}
                      </div>
                      <div className="flex items-center gap-2 flex-shrink-0">
                        <div className="text-right">
                          <span className="text-sm font-semibold text-slate-900 dark:text-white tabular-nums" style={{ fontFamily: "'JetBrains Mono', monospace" }}>
                            {it.pct.toFixed(2)}%
                          </span>
                          <span className="text-[10px] text-slate-400 dark:text-zinc-600 ml-1.5 tabular-nums hidden sm:inline">
                            {fmtINR(it.value_inr)}
                          </span>
                        </div>
                        {hasDrill && (
                          <span className="text-slate-400 dark:text-zinc-600 flex-shrink-0">
                            {isOpen ? <ChevronUp className="w-3.5 h-3.5" /> : <ChevronDown className="w-3.5 h-3.5" />}
                          </span>
                        )}
                      </div>
                    </div>
                    {/* Progress bar */}
                    <div className="h-1.5 rounded-full bg-slate-100 dark:bg-white/5 overflow-hidden mx-1">
                      <motion.div
                        initial={{ width: 0 }}
                        animate={{ width: `${wPct}%` }}
                        transition={{ duration: 0.55, delay: i * 0.03, ease: "easeOut" }}
                        className="h-full rounded-full"
                        style={{ background: VIZ[i % VIZ.length] }}
                      />
                    </div>
                  </button>

                  {/* Drilldown */}
                  <AnimatePresence>
                    {isOpen && <DrilldownPanel item={it} kind={kind} />}
                  </AnimatePresence>
                </div>
              );
            })}
          </div>

          {/* Footer */}
          {(top10Pct != null || secondary) && (
            <div className="mt-4 pt-3 border-t border-slate-100 dark:border-white/5 flex items-center justify-between text-xs text-slate-500 dark:text-zinc-500 flex-wrap gap-2">
              {top10Pct != null && (
                <span data-testid={`${testId}-top10`} className="flex items-center gap-1">
                  <TrendingUp className="w-3 h-3" />
                  Top 10 = <strong className="text-slate-700 dark:text-zinc-300 tabular-nums ml-1">{top10Pct.toFixed(1)}%</strong>
                </span>
              )}
              {secondary && <span className="text-[11px]">{secondary}</span>}
            </div>
          )}
        </CardContent>
      </Card>
    </motion.section>
  );
};

// ── MF Category Overlap section ───────────────────────────────────

const CategoryOverlapSection = ({ deepAnalytics }) => {
  const [expanded, setExpanded] = useState(null);

  const categories = useMemo(() => {
    const detail = deepAnalytics?.duplication?.category_detail || [];
    return [...detail]
      .sort((a, b) => b.fund_count - a.fund_count)
      .filter(d => d.fund_count > 0);
  }, [deepAnalytics]);

  if (categories.length === 0) return null;

  const overlapping = categories.filter(c => c.is_overlapping);

  return (
    <motion.section
      data-testid="category-overlap-section"
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.25 }}
    >
      <Card className="bg-white dark:bg-[#111] border-slate-100 dark:border-white/5 rounded-2xl overflow-hidden">
        <CardContent className="p-5 md:p-6">
          {/* Header */}
          <div className="flex items-start gap-3 mb-4">
            <div className="flex-shrink-0 w-10 h-10 rounded-xl flex items-center justify-center bg-gradient-to-br from-amber-500 to-orange-600">
              <Layers className="w-5 h-5 text-white" strokeWidth={2} />
            </div>
            <div>
              <h3 className="text-base font-bold text-slate-900 dark:text-white" style={{ fontFamily: "'Outfit', sans-serif" }}>
                MF Category Overlap
              </h3>
              <p className="text-xs text-slate-500 dark:text-zinc-500 mt-0.5">
                Categories with 2+ funds indicate redundancy — click any card to see which funds overlap
              </p>
            </div>
          </div>

          {/* Summary chips */}
          {overlapping.length > 0 && (
            <div className="flex items-start gap-2 mb-4 px-3 py-2 rounded-xl bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-800 text-amber-700 dark:text-amber-300">
              <AlertTriangle className="w-4 h-4 flex-shrink-0 mt-0.5" />
              <p className="text-xs leading-relaxed">
                <strong>{overlapping.length}</strong> categories have 2+ funds — consider consolidating to the best performer in each.
              </p>
            </div>
          )}

          {/* Category card grid */}
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-2.5" data-testid="category-overlap-grid">
            {categories.map((d, i) => {
              const isOverlapping = d.is_overlapping;
              const isOpen = expanded === i;
              return (
                <div key={`cat-${d.category}-${i}`}>
                  <button
                    onClick={() => setExpanded(isOpen ? null : i)}
                    className={`w-full text-left rounded-xl p-3.5 border transition-all hover:shadow-sm ${
                      isOverlapping
                        ? "border-amber-200 dark:border-amber-800 bg-amber-50 dark:bg-amber-900/20"
                        : "border-emerald-200 dark:border-emerald-800 bg-emerald-50 dark:bg-emerald-900/10"
                    }`}
                    data-testid={`cat-card-${i}`}
                  >
                    <div className="flex items-center justify-between mb-1.5">
                      <span className={`text-2xl font-bold tabular-nums ${isOverlapping ? "text-amber-600 dark:text-amber-400" : "text-emerald-600 dark:text-emerald-400"}`}
                        style={{ fontFamily: "'JetBrains Mono', monospace" }}>
                        {d.fund_count}
                      </span>
                      {isOverlapping
                        ? <AlertTriangle className="w-4 h-4 text-amber-400" strokeWidth={1.5} />
                        : <CheckCircle className="w-4 h-4 text-emerald-400" strokeWidth={1.5} />
                      }
                    </div>
                    <p className="text-xs font-semibold text-slate-700 dark:text-zinc-300 leading-tight">{d.category}</p>
                    <p className="text-[10px] text-slate-400 dark:text-zinc-500 mt-0.5">
                      {isOverlapping ? "Potential overlap" : "Single fund"}
                    </p>
                  </button>

                  {/* Inline drilldown */}
                  <AnimatePresence>
                    {isOpen && (d.funds || []).length > 0 && (
                      <motion.div
                        initial={{ opacity: 0, height: 0 }}
                        animate={{ opacity: 1, height: "auto" }}
                        exit={{ opacity: 0, height: 0 }}
                        transition={{ duration: 0.18 }}
                        className="overflow-hidden col-span-full"
                      >
                        <div className={`mt-1.5 rounded-xl border p-3 space-y-1 ${
                          isOverlapping
                            ? "border-amber-200 dark:border-amber-800 bg-amber-50/50 dark:bg-amber-900/10"
                            : "border-emerald-200 dark:border-emerald-800 bg-emerald-50/50 dark:bg-emerald-900/10"
                        }`}>
                          {d.funds.map((f, fi) => (
                            <p key={fi} className="text-xs text-slate-600 dark:text-zinc-400 truncate leading-relaxed">{f}</p>
                          ))}
                          {d.pct_of_mf != null && (
                            <p className="text-[10px] text-slate-400 dark:text-zinc-500 pt-1 border-t border-slate-200 dark:border-white/5">
                              {d.pct_of_mf.toFixed(1)}% of MF portfolio · {fmtINR(d.total_value)}
                            </p>
                          )}
                        </div>
                      </motion.div>
                    )}
                  </AnimatePresence>
                </div>
              );
            })}
          </div>
        </CardContent>
      </Card>
    </motion.section>
  );
};

// ── Loading / Empty states ────────────────────────────────────────

const LoadingState = () => (
  <div className="space-y-4">
    {[1, 2, 3, 4].map((i) => (
      <div key={i} className="h-56 rounded-2xl bg-slate-100 dark:bg-white/5 animate-pulse" />
    ))}
  </div>
);

const EmptyState = () => (
  <Card className="bg-white dark:bg-[#111] border-slate-100 dark:border-white/5 rounded-2xl">
    <CardContent className="p-10 text-center">
      <Building2 className="w-10 h-10 mx-auto mb-3 text-slate-300 dark:text-zinc-700" />
      <h3 className="text-sm font-bold text-slate-800 dark:text-zinc-200 mb-1">No holdings yet</h3>
      <p className="text-xs text-slate-500 dark:text-zinc-500">
        Upload a CAS statement or add holdings to see AMC, sector, and company exposure.
      </p>
    </CardContent>
  </Card>
);

// ── Main export ───────────────────────────────────────────────────

const ConcentrationAnalyticsTab = ({ onOpenChat, deepAnalytics }) => {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState(null);

  useEffect(() => {
    let alive = true;
    axios
      .get(`${API}/portfolio/exposure/concentration`, { withCredentials: true })
      .then((r) => { if (alive) setData(r.data); })
      .catch((e) => { if (alive) setErr(e?.response?.data?.detail || e.message); })
      .finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, []);

  const ask = (topic) => {
    const prompts = {
      amc:     "Which AMC am I most concentrated in, and what should I do about it?",
      sector:  "Which sector has the highest concentration in my portfolio and how should I rebalance?",
      company: "Which underlying companies dominate my portfolio across direct stocks and mutual funds?",
    };
    if (onOpenChat) onOpenChat(prompts[topic]);
  };

  if (loading) return <LoadingState />;
  if (err) return (
    <div className="rounded-2xl border border-rose-200 dark:border-rose-800 bg-rose-50 dark:bg-rose-900/20 p-4 text-sm text-rose-700 dark:text-rose-300">
      Could not load concentration analytics: {err}
    </div>
  );
  if (!data || data.empty || (data.holdings_count || 0) === 0) return <EmptyState />;

  return (
    <div className="space-y-5" data-testid="concentration-analytics-tab">
      {/* AMC Exposure */}
      <ExposureSection
        testId="exposure-amc"
        kind="amc"
        title="AMC Exposure"
        subtitle="Concentration by fund house across your mutual fund portfolio"
        icon={Building2}
        accent="bg-gradient-to-br from-purple-500 to-indigo-600"
        items={data.amc?.items || []}
        hhi={data.amc?.hhi}
        effectiveN={data.amc?.effective_n}
        largestPct={data.amc?.largest_pct}
        warning={data.amc?.warning}
        secondary={`${data.amc?.all_items_count || 0} AMCs in portfolio`}
        onAskNivesh={() => ask("amc")}
      />

      {/* Sector Exposure */}
      <ExposureSection
        testId="exposure-sector"
        kind="sector"
        title="Sector Exposure"
        subtitle="Sector weights after dissolving mutual funds into their underlying holdings"
        icon={Layers}
        accent="bg-gradient-to-br from-emerald-500 to-teal-600"
        items={data.sector?.items || []}
        hhi={data.sector?.hhi}
        effectiveN={data.sector?.effective_n}
        largestPct={data.sector?.largest_pct}
        warning={data.sector?.warning}
        secondary={`Look-through coverage: ${data.lookthrough_coverage ?? 0}%`}
        onAskNivesh={() => ask("sector")}
      />

      {/* Company Exposure */}
      <ExposureSection
        testId="exposure-company"
        kind="company"
        title="Company Exposure"
        subtitle="Top single-company exposures across direct equity + mutual fund look-through"
        icon={Briefcase}
        accent="bg-gradient-to-br from-rose-500 to-pink-600"
        items={data.company?.items || []}
        hhi={data.company?.hhi}
        effectiveN={data.company?.effective_n}
        largestPct={data.company?.largest_pct}
        warning={data.company?.warning}
        top10Pct={data.company?.top10_pct}
        secondary={`${data.company?.all_items_count || 0} unique companies`}
        onAskNivesh={() => ask("company")}
      />

      {/* MF Category Overlap — uses deep-analytics duplication data */}
      <CategoryOverlapSection deepAnalytics={deepAnalytics} />
    </div>
  );
};

export default ConcentrationAnalyticsTab;
