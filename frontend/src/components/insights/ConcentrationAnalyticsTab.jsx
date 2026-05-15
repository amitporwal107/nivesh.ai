/**
 * Diversification & Concentration Analytics tab content.
 *
 * Replaces the old "Fund Ratings & Rank + Fund Overlap + Overexposure"
 * sections beneath the Diversification Overview hero.
 *
 * Renders three exposure sections off a single backend call:
 *   - AMC Exposure       (which fund houses dominate your MF book)
 *   - Sector Exposure    (which sectors dominate via direct equity + MF look-through)
 *   - Company Exposure   (which underlying companies dominate, top 15)
 *
 * Each section is a top-N list + key metrics + an optional concentration
 * warning + "Ask Nivesh" CTA.
 *
 * Endpoint: GET /api/portfolio/exposure/concentration
 */
import React, { useEffect, useState, useMemo } from "react";
import axios from "axios";
import { motion } from "framer-motion";
import { AlertTriangle, Building2, Layers, Briefcase, MessageSquare, TrendingUp } from "lucide-react";
import { Card, CardContent } from "../ui/card";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

const fmtINR = (v) => {
  if (v == null) return "—";
  if (v >= 1e7) return `₹${(v / 1e7).toFixed(2)} Cr`;
  if (v >= 1e5) return `₹${(v / 1e5).toFixed(2)} L`;
  return `₹${Math.round(v).toLocaleString("en-IN")}`;
};

// 12-step palette per design tokens
const VIZ = [
  "#3D5AFE", "#1DE9B6", "#FFC400", "#FF4081", "#00BCD4", "#8BC34A",
  "#FF5722", "#9C27B0", "#03A9F4", "#FF9800", "#4CAF50", "#E91E63",
];

// ── Sub-component: a single exposure section ──────────────────────

const ExposureSection = ({
  title, subtitle, icon: Icon, accent, items, hhi, effectiveN, largestPct,
  warning, top10Pct, secondary, onAskNivesh, testId,
}) => {
  if (!items || items.length === 0) return null;
  const maxPct = items[0]?.pct || 1;

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
                <h3
                  className="text-base font-bold text-slate-900 dark:text-white"
                  style={{ fontFamily: "'Outfit', sans-serif" }}
                >
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
          <div className="grid grid-cols-3 md:grid-cols-3 gap-2 mb-4">
            <Metric label="Largest" value={`${largestPct?.toFixed(1) ?? "—"}%`} tone={largestPct > 30 ? "warn" : "ok"} testId={`${testId}-metric-largest`} />
            <Metric label="Effective #" value={effectiveN?.toFixed(1) ?? "—"} tone="info" testId={`${testId}-metric-effective-n`} />
            <Metric label="HHI" value={hhi?.toFixed(3) ?? "—"} tone={hhi > 0.2 ? "warn" : "ok"} testId={`${testId}-metric-hhi`} hint="0 = perfect · 1 = single position" />
          </div>

          {/* Warning */}
          {warning && (
            <div
              data-testid={`${testId}-warning`}
              className="flex items-start gap-2 mb-4 px-3 py-2 rounded-xl bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-800 text-amber-700 dark:text-amber-300"
            >
              <AlertTriangle className="w-4 h-4 flex-shrink-0 mt-0.5" />
              <p className="text-xs leading-relaxed">{warning}</p>
            </div>
          )}

          {/* Top-N list as horizontal bars */}
          <div className="space-y-2" data-testid={`${testId}-items`}>
            {items.map((it, i) => {
              const wPct = Math.min(100, (it.pct / maxPct) * 100);
              return (
                <div key={`${it.name}-${i}`} className="group" data-testid={`${testId}-item-${i}`}>
                  <div className="flex items-center justify-between gap-3 mb-1">
                    <div className="flex items-center gap-2 min-w-0 flex-1">
                      <span
                        className="inline-block w-1.5 h-1.5 rounded-full flex-shrink-0"
                        style={{ background: VIZ[i % VIZ.length] }}
                      />
                      <span className="text-sm font-medium text-slate-800 dark:text-zinc-200 truncate">
                        {it.name}
                      </span>
                      {it.sector && (
                        <span className="text-[10px] uppercase tracking-wider text-slate-400 dark:text-zinc-600 flex-shrink-0">
                          · {it.sector}
                        </span>
                      )}
                      {it.count != null && (
                        <span className="text-[10px] text-slate-400 dark:text-zinc-600 flex-shrink-0">
                          · {it.count} fund{it.count !== 1 ? "s" : ""}
                        </span>
                      )}
                      {it.via_funds_count > 0 && it.via_direct_inr === 0 && (
                        <span className="text-[10px] text-slate-400 dark:text-zinc-600 flex-shrink-0">
                          · via {it.via_funds_count} MF{it.via_funds_count !== 1 ? "s" : ""}
                        </span>
                      )}
                      {it.via_funds_count > 0 && it.via_direct_inr > 0 && (
                        <span className="text-[10px] text-slate-400 dark:text-zinc-600 flex-shrink-0">
                          · direct + {it.via_funds_count} MF{it.via_funds_count !== 1 ? "s" : ""}
                        </span>
                      )}
                    </div>
                    <div className="flex items-baseline gap-2 flex-shrink-0">
                      <span
                        className="text-sm font-semibold text-slate-900 dark:text-white tabular-nums"
                        style={{ fontFamily: "'JetBrains Mono', monospace" }}
                      >
                        {it.pct.toFixed(2)}%
                      </span>
                      <span className="text-[10px] text-slate-400 dark:text-zinc-600 tabular-nums">
                        {fmtINR(it.value_inr)}
                      </span>
                    </div>
                  </div>
                  <div className="h-1.5 rounded-full bg-slate-100 dark:bg-white/5 overflow-hidden">
                    <motion.div
                      initial={{ width: 0 }}
                      animate={{ width: `${wPct}%` }}
                      transition={{ duration: 0.6, delay: i * 0.03, ease: "easeOut" }}
                      className="h-full rounded-full"
                      style={{ background: VIZ[i % VIZ.length] }}
                    />
                  </div>
                </div>
              );
            })}
          </div>

          {/* Footer: secondary line (e.g. top10_pct) */}
          {(top10Pct != null || secondary) && (
            <div className="mt-4 pt-3 border-t border-slate-100 dark:border-white/5 flex items-center justify-between text-xs text-slate-500 dark:text-zinc-500 flex-wrap gap-2">
              {top10Pct != null && (
                <span data-testid={`${testId}-top10`} className="flex items-center gap-1">
                  <TrendingUp className="w-3 h-3" />
                  Top 10 = <strong className="text-slate-700 dark:text-zinc-300 tabular-nums">{top10Pct.toFixed(1)}%</strong>
                </span>
              )}
              {secondary && <span>{secondary}</span>}
            </div>
          )}
        </CardContent>
      </Card>
    </motion.section>
  );
};

const Metric = ({ label, value, tone = "ok", hint, testId }) => {
  const toneClass = {
    ok:   "bg-emerald-50 dark:bg-emerald-900/20 border-emerald-100 dark:border-emerald-900 text-emerald-700 dark:text-emerald-300",
    warn: "bg-amber-50 dark:bg-amber-900/20 border-amber-100 dark:border-amber-900 text-amber-700 dark:text-amber-300",
    info: "bg-sky-50 dark:bg-sky-900/20 border-sky-100 dark:border-sky-900 text-sky-700 dark:text-sky-300",
  }[tone];
  return (
    <div data-testid={testId} className={`rounded-xl border px-3 py-2 ${toneClass}`} title={hint || ""}>
      <div className="text-[10px] uppercase font-medium opacity-80 mb-0.5">{label}</div>
      <div className="text-sm font-bold tabular-nums" style={{ fontFamily: "'JetBrains Mono', monospace" }}>{value}</div>
    </div>
  );
};

// ── Loading + Empty states ────────────────────────────────────────

const LoadingState = () => (
  <div className="space-y-4">
    {[1, 2, 3].map((i) => (
      <div key={i} className="h-64 rounded-2xl bg-slate-100 dark:bg-white/5 animate-pulse" />
    ))}
  </div>
);

const EmptyState = () => (
  <Card className="bg-white dark:bg-[#111] border-slate-100 dark:border-white/5 rounded-2xl">
    <CardContent className="p-10 text-center">
      <Building2 className="w-10 h-10 mx-auto mb-3 text-slate-300 dark:text-zinc-700" />
      <h3 className="text-sm font-bold text-slate-800 dark:text-zinc-200 mb-1">No holdings yet</h3>
      <p className="text-xs text-slate-500 dark:text-zinc-500">
        Upload a CAS statement or connect your broker to see your AMC, sector,
        and company exposure.
      </p>
    </CardContent>
  </Card>
);

// ── Main tab content ──────────────────────────────────────────────

const ConcentrationAnalyticsTab = ({ onOpenChat }) => {
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

  const askNivesh = (topic) => {
    const prompt = {
      amc:     "Which AMC am I most concentrated in, and what should I do about it?",
      sector:  "Which sector has the highest concentration in my portfolio and how should I rebalance?",
      company: "Which underlying companies dominate my portfolio across direct stocks and mutual funds?",
    }[topic];
    if (onOpenChat) onOpenChat(prompt);
  };

  const sections = useMemo(() => {
    if (!data) return null;
    return [
      {
        key: "amc",
        title: "AMC Exposure",
        subtitle: "Concentration by fund house across your mutual fund book",
        icon: Building2,
        accent: "bg-gradient-to-br from-purple-500 to-indigo-600",
        section: data.amc,
        onAsk: () => askNivesh("amc"),
        secondary: `${data.amc?.all_items_count || 0} AMCs in portfolio`,
      },
      {
        key: "sector",
        title: "Sector Exposure",
        subtitle: "Sector weights after dissolving mutual funds into their underlying holdings",
        icon: Layers,
        accent: "bg-gradient-to-br from-emerald-500 to-teal-600",
        section: data.sector,
        onAsk: () => askNivesh("sector"),
        secondary: `Look-through coverage: ${data.lookthrough_coverage ?? 0}%`,
      },
      {
        key: "company",
        title: "Company Exposure",
        subtitle: "Top single-company exposures across direct equity + mutual fund look-through",
        icon: Briefcase,
        accent: "bg-gradient-to-br from-rose-500 to-pink-600",
        section: data.company,
        onAsk: () => askNivesh("company"),
        showTop10: true,
        secondary: `${data.company?.all_items_count || 0} unique companies`,
      },
    ];
  }, [data]);

  if (loading) return <LoadingState />;
  if (err) {
    return (
      <div className="rounded-2xl border border-rose-200 dark:border-rose-800 bg-rose-50 dark:bg-rose-900/20 p-4 text-sm text-rose-700 dark:text-rose-300">
        Could not load concentration analytics: {err}
      </div>
    );
  }
  if (!data || data.empty || (data.holdings_count || 0) === 0) return <EmptyState />;

  return (
    <div className="space-y-5" data-testid="concentration-analytics-tab">
      {sections.map((s) => (
        <ExposureSection
          key={s.key}
          testId={`exposure-${s.key}`}
          title={s.title}
          subtitle={s.subtitle}
          icon={s.icon}
          accent={s.accent}
          items={s.section?.items || []}
          hhi={s.section?.hhi}
          effectiveN={s.section?.effective_n}
          largestPct={s.section?.largest_pct}
          warning={s.section?.warning}
          top10Pct={s.showTop10 ? s.section?.top10_pct : null}
          secondary={s.secondary}
          onAskNivesh={s.onAsk}
        />
      ))}
    </div>
  );
};

export default ConcentrationAnalyticsTab;
