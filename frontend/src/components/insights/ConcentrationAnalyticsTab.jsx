/**
 * Diversification & Concentration Analytics tab.
 *
 * Each widget uses a two-column layout:
 *   Left  — interactive chart (donut / treemap) + compact bar list
 *   Right — drilldown detail panel, shown only when a slice is clicked
 *
 * Clicking a pie slice, treemap tile, or bar row selects it and
 * populates the right panel. Clicking the same item again deselects.
 * Each card is self-contained with no internal scroll bar.
 *
 * Endpoint: GET /api/portfolio/exposure/concentration
 */
import React, { useEffect, useState, useMemo, useCallback } from "react";
import axios from "axios";
import { motion, AnimatePresence } from "framer-motion";
import {
  AlertTriangle, Building2, Layers, Briefcase,
  MessageSquare, TrendingUp, CheckCircle, Info,
  Users, Network, MousePointerClick,
} from "lucide-react";
import {
  PieChart, Pie, Cell, Sector, Tooltip, ResponsiveContainer, Treemap,
} from "recharts";
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

const AskNiveshBtn = ({ testId, onClick }) => (
  <button
    data-testid={testId}
    onClick={onClick}
    className="text-xs px-2.5 py-1 rounded-full border border-slate-200 dark:border-white/10 text-slate-500 dark:text-zinc-400 hover:text-teal-600 dark:hover:text-teal-400 hover:border-teal-300 dark:hover:border-teal-700 transition-colors flex items-center gap-1 flex-shrink-0"
  >
    <MessageSquare className="w-3 h-3" /> Ask Nivesh
  </button>
);

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

// ── Hero Insight banner ───────────────────────────────────────────

const HeroInsight = ({ insight, testId }) => {
  if (!insight) return null;
  const cls = {
    ok:   "bg-emerald-50 dark:bg-emerald-900/20 border-emerald-200 dark:border-emerald-800 text-emerald-700 dark:text-emerald-300",
    warn: "bg-amber-50 dark:bg-amber-900/20 border-amber-200 dark:border-amber-800 text-amber-700 dark:text-amber-300",
    bad:  "bg-rose-50 dark:bg-rose-900/20 border-rose-200 dark:border-rose-800 text-rose-700 dark:text-rose-300",
  }[insight.tone] || "";
  const Icon = insight.tone === "ok" ? CheckCircle : AlertTriangle;
  return (
    <div data-testid={testId} className={`flex items-start gap-2.5 mb-3 px-3 py-2.5 rounded-xl border ${cls}`}>
      <Icon className="w-4 h-4 flex-shrink-0 mt-0.5" />
      <div className="min-w-0">
        <p className="text-sm font-semibold leading-tight">{insight.headline}</p>
        <p className="text-xs leading-relaxed mt-0.5 opacity-90">{insight.detail}</p>
      </div>
    </div>
  );
};

// ── Cyclical vs Defensive split pills ─────────────────────────────

const CycleSplit = ({ split, testId }) => {
  if (!split) return null;
  const { cyclical_pct = 0, defensive_pct = 0, other_pct = 0 } = split;
  if (cyclical_pct + defensive_pct + other_pct < 1) return null;
  const Pill = ({ label, value, tone }) => (
    <div className={`flex-1 rounded-xl border px-2 py-1.5 text-center ${tone}`}>
      <div className="text-[9px] uppercase tracking-wide opacity-70">{label}</div>
      <div className="text-sm font-bold tabular-nums" style={{ fontFamily: "'JetBrains Mono', monospace" }}>
        {value.toFixed(1)}%
      </div>
    </div>
  );
  return (
    <div data-testid={testId} className="flex gap-1.5 mb-3">
      <Pill label="Cyclical"  value={cyclical_pct}  tone="bg-amber-50 dark:bg-amber-900/20 border-amber-200 dark:border-amber-800 text-amber-700 dark:text-amber-300" />
      <Pill label="Defensive" value={defensive_pct} tone="bg-emerald-50 dark:bg-emerald-900/20 border-emerald-200 dark:border-emerald-800 text-emerald-700 dark:text-emerald-300" />
      {other_pct > 0.5 && (
        <Pill label="Other" value={other_pct} tone="bg-slate-50 dark:bg-white/5 border-slate-200 dark:border-white/10 text-slate-600 dark:text-zinc-400" />
      )}
    </div>
  );
};

// ── Interactive Donut chart ────────────────────────────────────────

const ActivePieSlice = (props) => (
  <Sector
    {...props}
    outerRadius={props.outerRadius + 7}
    innerRadius={props.innerRadius - 2}
  />
);

const InteractiveDonut = ({ items, selectedIdx, onSelect, testId }) => {
  const top   = items.slice(0, 8);
  const rest  = items.slice(8).reduce((s, x) => s + (x.pct || 0), 0);
  const data  = rest > 0.01 ? [...top, { name: "Others", pct: rest }] : top;
  const sel   = selectedIdx != null && selectedIdx < items.length ? items[selectedIdx] : null;

  const handleClick = useCallback((_, index) => {
    onSelect(prev => prev === index ? null : index);
  }, [onSelect]);

  return (
    <div data-testid={testId} className="relative h-36 w-full">
      <ResponsiveContainer width="100%" height="100%">
        <PieChart>
          <Pie
            data={data}
            dataKey="pct"
            nameKey="name"
            cx="50%"
            cy="50%"
            innerRadius={38}
            outerRadius={60}
            paddingAngle={1}
            stroke="none"
            activeIndex={selectedIdx != null ? selectedIdx : undefined}
            activeShape={ActivePieSlice}
            onClick={handleClick}
            style={{ cursor: "pointer" }}
          >
            {data.map((_, i) => (
              <Cell
                key={i}
                fill={VIZ[i % VIZ.length]}
                opacity={selectedIdx == null || selectedIdx === i ? 1 : 0.4}
              />
            ))}
          </Pie>
          <Tooltip
            contentStyle={{
              background: "rgba(17,17,17,0.95)",
              border: "1px solid rgba(255,255,255,0.08)",
              borderRadius: 8, fontSize: 11, color: "#fff",
            }}
            formatter={(v, n) => [`${Number(v).toFixed(2)}%`, n]}
          />
        </PieChart>
      </ResponsiveContainer>

      {/* Center label */}
      <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
        {sel ? (
          <div className="text-center px-1">
            <p className="text-base font-bold tabular-nums text-slate-900 dark:text-white leading-none" style={{ fontFamily: "'JetBrains Mono', monospace" }}>
              {sel.pct.toFixed(1)}%
            </p>
            <p className="text-[9px] text-slate-500 dark:text-zinc-500 mt-0.5 leading-tight max-w-[64px] mx-auto" style={{ wordBreak: "break-word" }}>
              {sel.name.length > 12 ? sel.name.slice(0, 12) + "…" : sel.name}
            </p>
          </div>
        ) : (
          <p className="text-[9px] text-slate-400 dark:text-zinc-600 text-center leading-tight">
            click<br />a slice
          </p>
        )}
      </div>
    </div>
  );
};

// ── Interactive Treemap ───────────────────────────────────────────

const InteractiveTreemap = ({ items, selectedIdx, onSelect, testId }) => {
  const data = useMemo(
    () => items.slice(0, 20).map((it, i) => ({ name: it.name, pct: it.pct, size: it.value_inr, idx: i })),
    [items],
  );

  const renderTile = useCallback((props) => {
    const { x, y, width, height, name, pct, idx } = props;
    const isSelected = idx === selectedIdx;
    if (width < 10 || height < 10) return null;
    return (
      <g
        onClick={() => onSelect(prev => prev === idx ? null : idx)}
        style={{ cursor: "pointer" }}
      >
        <rect
          x={x} y={y} width={width} height={height}
          fill={VIZ[idx % VIZ.length]}
          opacity={selectedIdx == null || isSelected ? 1 : 0.45}
          stroke={isSelected ? "#fff" : "#000"}
          strokeWidth={isSelected ? 2 : 0.5}
          rx={2}
        />
        {width > 28 && height > 20 && (
          <text x={x + 5} y={y + 13} fill="#fff" fontSize={9} fontWeight={600} style={{ pointerEvents: "none" }}>
            {name.slice(0, Math.max(3, Math.floor(width / 8)))}
          </text>
        )}
        {width > 28 && height > 30 && (
          <text x={x + 5} y={y + 25} fill="#fff" fontSize={9} opacity={0.85} style={{ pointerEvents: "none" }}>
            {Number(pct || 0).toFixed(1)}%
          </text>
        )}
      </g>
    );
  }, [selectedIdx, onSelect]);

  return (
    <div data-testid={testId} className="h-44 w-full rounded-xl overflow-hidden">
      <ResponsiveContainer width="100%" height="100%">
        <Treemap data={data} dataKey="size" stroke="none" fill="#3D5AFE" content={renderTile} />
      </ResponsiveContainer>
    </div>
  );
};

// ── Compact bar row ───────────────────────────────────────────────

const BarRow = ({ item, index, maxPct, isSelected, onClick }) => {
  const wPct = Math.min(100, (item.pct / maxPct) * 100);
  return (
    <button
      onClick={onClick}
      className={`w-full text-left px-1.5 py-1 rounded-lg transition-colors ${
        isSelected
          ? "bg-slate-100 dark:bg-white/10"
          : "hover:bg-slate-50 dark:hover:bg-white/[0.03]"
      }`}
    >
      <div className="flex items-center justify-between gap-2 mb-0.5">
        <div className="flex items-center gap-1.5 min-w-0 flex-1">
          <span className="inline-block w-1.5 h-1.5 rounded-full flex-shrink-0" style={{ background: VIZ[index % VIZ.length] }} />
          <span className="text-xs font-medium text-slate-800 dark:text-zinc-200 truncate">{item.name}</span>
          {item.count != null && (
            <span className="text-[9px] text-slate-400 dark:text-zinc-600 flex-shrink-0">·{item.count}f</span>
          )}
        </div>
        <span className="text-xs font-semibold text-slate-900 dark:text-white tabular-nums flex-shrink-0" style={{ fontFamily: "'JetBrains Mono', monospace" }}>
          {item.pct.toFixed(1)}%
        </span>
      </div>
      <div className="h-1 rounded-full bg-slate-100 dark:bg-white/5 overflow-hidden">
        <div
          className="h-full rounded-full transition-all duration-500"
          style={{ width: `${wPct}%`, background: VIZ[index % VIZ.length] }}
        />
      </div>
    </button>
  );
};

// ── Slice detail panel (right column) ────────────────────────────

const SliceDetailPanel = ({ item, kind, color }) => {
  if (!item) {
    return (
      <div className="h-full flex flex-col items-center justify-center gap-2 text-slate-400 dark:text-zinc-600 text-center px-4">
        <MousePointerClick className="w-6 h-6 opacity-50" />
        <p className="text-xs leading-relaxed">Click a slice or row<br />to see details</p>
      </div>
    );
  }

  const funds    = item.funds    || [];
  const holdings = item.holdings || [];

  return (
    <motion.div
      key={item.name}
      initial={{ opacity: 0, x: 8 }}
      animate={{ opacity: 1, x: 0 }}
      transition={{ duration: 0.18 }}
      className="h-full flex flex-col gap-3 pl-4 border-l border-slate-100 dark:border-white/5"
    >
      {/* Name + pct header */}
      <div className="flex items-start gap-2">
        <span className="inline-block w-3 h-3 rounded-full flex-shrink-0 mt-0.5" style={{ background: color }} />
        <div className="min-w-0">
          <p className="text-sm font-bold text-slate-900 dark:text-white leading-tight truncate">{item.name}</p>
          <p className="text-xs text-slate-500 dark:text-zinc-500 tabular-nums">
            {item.pct?.toFixed(2)}% · {fmtINR(item.value_inr)}
          </p>
        </div>
      </div>

      {/* Kind-specific detail */}
      <div className="flex flex-col gap-1.5 text-xs overflow-y-auto" style={{ maxHeight: "160px" }}>
        {kind === "amc" && (
          <>
            {funds.length > 0 && (
              <>
                <p className="text-[10px] font-semibold uppercase tracking-wider text-slate-400 dark:text-zinc-500">
                  Funds ({funds.length})
                </p>
                {funds.slice(0, 8).map((f, i) => (
                  <p key={i} className="text-slate-600 dark:text-zinc-400 truncate leading-relaxed pl-1 border-l border-slate-200 dark:border-white/10">{f}</p>
                ))}
                {funds.length > 8 && <p className="text-slate-400 dark:text-zinc-600">+{funds.length - 8} more</p>}
              </>
            )}
          </>
        )}

        {kind === "sector" && (
          <>
            {(item.via?.direct || 0) > 0 && (
              <div className="flex items-center justify-between">
                <span className="text-slate-500 dark:text-zinc-500">Direct equity</span>
                <span className="font-medium text-slate-700 dark:text-zinc-300 tabular-nums">{fmtINR(item.via.direct)}</span>
              </div>
            )}
            {(item.via?.mf || 0) > 0 && (
              <div className="flex items-center justify-between">
                <span className="text-slate-500 dark:text-zinc-500">Via mutual funds</span>
                <span className="font-medium text-slate-700 dark:text-zinc-300 tabular-nums">{fmtINR(item.via.mf)}</span>
              </div>
            )}
            {item.cycle && (
              <div className="flex items-center justify-between">
                <span className="text-slate-500 dark:text-zinc-500">Type</span>
                <span className={`font-medium capitalize ${
                  item.cycle === "cyclical" ? "text-amber-600 dark:text-amber-400"
                  : item.cycle === "defensive" ? "text-emerald-600 dark:text-emerald-400"
                  : "text-slate-500 dark:text-zinc-500"
                }`}>{item.cycle}</span>
              </div>
            )}
            {holdings.length > 0 && (
              <>
                <p className="text-[10px] font-semibold uppercase tracking-wider text-slate-400 dark:text-zinc-500 mt-1">
                  Holdings ({holdings.length})
                </p>
                {holdings.slice(0, 6).map((h, i) => (
                  <p key={i} className="text-slate-600 dark:text-zinc-400 truncate pl-1 border-l border-slate-200 dark:border-white/10">{h}</p>
                ))}
                {holdings.length > 6 && <p className="text-slate-400 dark:text-zinc-600">+{holdings.length - 6} more</p>}
              </>
            )}
          </>
        )}

        {kind === "company" && (
          <>
            {(item.via_direct_inr || 0) > 0 && (
              <div className="flex items-center justify-between">
                <span className="text-slate-500 dark:text-zinc-500">Direct equity</span>
                <span className="font-medium text-slate-700 dark:text-zinc-300 tabular-nums">{fmtINR(item.via_direct_inr)}</span>
              </div>
            )}
            {(item.via_funds_count || 0) > 0 && (
              <div className="flex items-center justify-between">
                <span className="text-slate-500 dark:text-zinc-500">Via MF look-through</span>
                <span className="font-medium text-slate-700 dark:text-zinc-300 tabular-nums">{item.via_funds_count} fund{item.via_funds_count !== 1 ? "s" : ""}</span>
              </div>
            )}
            {item.sector && (
              <div className="flex items-center justify-between">
                <span className="text-slate-500 dark:text-zinc-500">Sector</span>
                <span className="font-medium text-slate-700 dark:text-zinc-300">{item.sector}</span>
              </div>
            )}
            {item.group && (
              <div className="flex items-center justify-between">
                <span className="text-slate-500 dark:text-zinc-500">Group</span>
                <span className="font-medium text-violet-600 dark:text-violet-400">{item.group}</span>
              </div>
            )}
            {item.cross_held && (
              <p className="text-[10px] px-2 py-1 rounded-lg bg-sky-50 dark:bg-sky-900/20 border border-sky-200 dark:border-sky-800 text-sky-700 dark:text-sky-300 mt-1">
                Held via {item.routes_count} routes — check Hidden Overlap below
              </p>
            )}
          </>
        )}

        {kind === "group" && (
          <>
            {(item.companies || []).length > 0 && (
              <>
                <p className="text-[10px] font-semibold uppercase tracking-wider text-slate-400 dark:text-zinc-500">
                  Companies ({item.company_count})
                </p>
                {item.companies.slice(0, 8).map((c, i) => (
                  <p key={i} className="text-slate-600 dark:text-zinc-400 truncate pl-1 border-l border-slate-200 dark:border-white/10">{c}</p>
                ))}
                {item.company_count > 8 && <p className="text-slate-400 dark:text-zinc-600">+{item.company_count - 8} more</p>}
              </>
            )}
          </>
        )}
      </div>
    </motion.div>
  );
};

// ── Section card shell ────────────────────────────────────────────

const SectionCard = ({ testId, children, accent, icon: Icon, title, subtitle, onAskNivesh, askTestId }) => (
  <motion.section
    data-testid={testId}
    initial={{ opacity: 0, y: 8 }}
    animate={{ opacity: 1, y: 0 }}
    transition={{ duration: 0.25 }}
  >
    <Card className="bg-white dark:bg-[#111] border-slate-100 dark:border-white/5 rounded-2xl overflow-hidden">
      <CardContent className="p-4 md:p-5">
        {/* Header */}
        <div className="flex items-start justify-between gap-3 mb-3 flex-wrap">
          <div className="flex items-start gap-3 min-w-0">
            <div className={`flex-shrink-0 w-9 h-9 rounded-xl flex items-center justify-center ${accent}`}>
              <Icon className="w-4.5 h-4.5 text-white" strokeWidth={2} />
            </div>
            <div className="min-w-0">
              <h3 className="text-sm font-bold text-slate-900 dark:text-white" style={{ fontFamily: "'Outfit', sans-serif" }}>
                {title}
              </h3>
              <p className="text-[11px] text-slate-500 dark:text-zinc-500 mt-0.5 leading-tight">{subtitle}</p>
            </div>
          </div>
          {onAskNivesh && <AskNiveshBtn testId={askTestId} onClick={onAskNivesh} />}
        </div>
        {children}
      </CardContent>
    </Card>
  </motion.section>
);

// ── Main exposure section (AMC / Sector / Company) ────────────────

const ExposureSection = ({
  title, subtitle, icon, accent, testId, kind,
  items, hhi, effectiveN, largestPct,
  heroInsight, viz, cycleSplit, top10Pct, secondary,
  onAskNivesh,
}) => {
  const [selected, setSelected] = useState(null);

  if (!items || items.length === 0) return null;
  const maxPct = items[0]?.pct || 1;
  const selectedItem = selected != null ? items[selected] : null;
  const selectedColor = selected != null ? VIZ[selected % VIZ.length] : undefined;

  return (
    <SectionCard
      testId={testId} accent={accent} icon={icon}
      title={title} subtitle={subtitle}
      onAskNivesh={onAskNivesh} askTestId={`${testId}-ask-nivesh`}
    >
      {/* Hero insight */}
      <HeroInsight insight={heroInsight} testId={`${testId}-hero`} />

      {/* Metric chips */}
      <div className="grid grid-cols-3 gap-2 mb-3">
        <Metric label="Largest" value={`${largestPct?.toFixed(1) ?? "—"}%`} tone={largestPct > 30 ? "warn" : "ok"} testId={`${testId}-metric-largest`} />
        <Metric label="Effective #" value={effectiveN?.toFixed(1) ?? "—"} tone="info" testId={`${testId}-metric-effective-n`} hint="Equivalent equally-weighted count — higher is better" />
        <Metric label="HHI" value={hhi?.toFixed(3) ?? "—"} tone={hhi > 0.2 ? "warn" : "ok"} testId={`${testId}-metric-hhi`} hint="0 = perfectly diversified · 1 = single position" />
      </div>

      {/* Cyclical / Defensive pills (sector only) */}
      {cycleSplit && <CycleSplit split={cycleSplit} testId={`${testId}-cycle-split`} />}

      {/* Two-column body: chart + bar list | detail panel */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">

        {/* Left: chart + compact bar list */}
        <div className="flex flex-col gap-2" data-testid={`${testId}-left`}>
          {viz === "donut" && (
            <InteractiveDonut
              items={items}
              selectedIdx={selected}
              onSelect={setSelected}
              testId={`${testId}-donut`}
            />
          )}
          {viz === "treemap" && (
            <InteractiveTreemap
              items={items}
              selectedIdx={selected}
              onSelect={setSelected}
              testId={`${testId}-treemap`}
            />
          )}

          {/* Compact scrollable bar list */}
          <div className="overflow-y-auto space-y-0.5" style={{ maxHeight: "160px" }} data-testid={`${testId}-items`}>
            {items.map((it, i) => (
              <BarRow
                key={`${it.name}-${i}`}
                item={it}
                index={i}
                maxPct={maxPct}
                isSelected={selected === i}
                onClick={() => setSelected(prev => prev === i ? null : i)}
              />
            ))}
          </div>
        </div>

        {/* Right: detail panel */}
        <div className="min-h-[180px]" data-testid={`${testId}-detail`}>
          <AnimatePresence mode="wait">
            <SliceDetailPanel
              key={selected ?? "empty"}
              item={selectedItem}
              kind={kind}
              color={selectedColor}
            />
          </AnimatePresence>
        </div>
      </div>

      {/* Footer */}
      {(top10Pct != null || secondary) && (
        <div className="mt-3 pt-2.5 border-t border-slate-100 dark:border-white/5 flex items-center justify-between text-xs text-slate-500 dark:text-zinc-500 flex-wrap gap-2">
          {top10Pct != null && (
            <span data-testid={`${testId}-top10`} className="flex items-center gap-1">
              <TrendingUp className="w-3 h-3" />
              Top 10 = <strong className="text-slate-700 dark:text-zinc-300 tabular-nums ml-1">{top10Pct.toFixed(1)}%</strong>
            </span>
          )}
          {secondary && <span className="text-[11px]">{secondary}</span>}
        </div>
      )}
    </SectionCard>
  );
};

// ── Group Exposure section ────────────────────────────────────────

const GroupExposureSection = ({ data, onAskNivesh }) => {
  const [selected, setSelected] = useState(null);
  const items = data?.items || [];
  if (items.length === 0) return null;

  const maxPct     = items[0]?.pct || 1;
  const selectedItem  = selected != null ? items[selected] : null;
  const selectedColor = selected != null ? VIZ[selected % VIZ.length] : undefined;

  return (
    <SectionCard
      testId="exposure-group"
      accent="bg-gradient-to-br from-violet-500 to-fuchsia-600"
      icon={Users}
      title="Group Exposure"
      subtitle="Combined exposure to business groups across direct equity + MF look-through"
      onAskNivesh={onAskNivesh}
      askTestId="exposure-group-ask-nivesh"
    >
      <HeroInsight insight={data?.hero_insight} testId="exposure-group-hero" />

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {/* Left: bar list */}
        <div className="overflow-y-auto space-y-0.5" style={{ maxHeight: "220px" }} data-testid="exposure-group-items">
          {items.map((it, i) => (
            <BarRow
              key={`grp-${it.name}-${i}`}
              item={it}
              index={i}
              maxPct={maxPct}
              isSelected={selected === i}
              onClick={() => setSelected(prev => prev === i ? null : i)}
            />
          ))}
        </div>

        {/* Right: detail panel */}
        <div className="min-h-[160px]">
          <AnimatePresence mode="wait">
            <SliceDetailPanel
              key={selected ?? "empty"}
              item={selectedItem}
              kind="group"
              color={selectedColor}
            />
          </AnimatePresence>
        </div>
      </div>
    </SectionCard>
  );
};

// ── Hidden Overlap section ────────────────────────────────────────

const HiddenOverlapSection = ({ data, onAskNivesh }) => {
  const items = data?.items || [];
  if (items.length === 0) return null;

  return (
    <SectionCard
      testId="exposure-hidden-overlap"
      accent="bg-gradient-to-br from-cyan-500 to-blue-600"
      icon={Network}
      title="Hidden Overlap"
      subtitle="Companies held through multiple routes (direct + funds, or across 2+ funds)"
      onAskNivesh={onAskNivesh}
      askTestId="exposure-hidden-overlap-ask-nivesh"
    >
      <div className="flex items-start gap-2 mb-3 px-3 py-2 rounded-xl bg-sky-50 dark:bg-sky-900/20 border border-sky-200 dark:border-sky-800 text-sky-700 dark:text-sky-300">
        <Info className="w-3.5 h-3.5 flex-shrink-0 mt-0.5" />
        <p className="text-xs leading-relaxed">
          <strong>{items.length}</strong> {items.length === 1 ? "company is" : "companies are"} held via 2+ routes — effective exposure may be larger than any single fund line shows.
        </p>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-x-6 gap-y-1" data-testid="exposure-hidden-overlap-items">
        {items.map((it, i) => (
          <div
            key={`ov-${it.name}-${i}`}
            className="flex items-center justify-between gap-2 py-1.5 px-2 rounded-lg hover:bg-slate-50 dark:hover:bg-white/[0.03] transition-colors"
          >
            <div className="flex items-center gap-1.5 min-w-0 flex-1">
              <span className="inline-block w-1.5 h-1.5 rounded-full flex-shrink-0" style={{ background: VIZ[i % VIZ.length] }} />
              <span className="text-xs font-medium text-slate-800 dark:text-zinc-200 truncate">{it.name}</span>
            </div>
            <div className="flex items-center gap-2 flex-shrink-0">
              <span className="text-[10px] text-slate-400 dark:text-zinc-600">
                {it.via_direct_inr > 0 ? "direct" : ""}
                {it.via_direct_inr > 0 && it.via_funds_count > 0 ? " + " : ""}
                {it.via_funds_count > 0 ? `${it.via_funds_count}f` : ""}
              </span>
              <span className="text-xs font-semibold text-slate-900 dark:text-white tabular-nums" style={{ fontFamily: "'JetBrains Mono', monospace" }}>
                {Number(it.pct || 0).toFixed(2)}%
              </span>
            </div>
          </div>
        ))}
      </div>
    </SectionCard>
  );
};

// ── MF Category Overlap section ───────────────────────────────────

const CategoryOverlapSection = ({ deepAnalytics }) => {
  const [expanded, setExpanded] = useState(null);

  const categories = useMemo(() => {
    const detail = deepAnalytics?.duplication?.category_detail || [];
    return [...detail].sort((a, b) => b.fund_count - a.fund_count).filter(d => d.fund_count > 0);
  }, [deepAnalytics]);

  if (categories.length === 0) return null;
  const overlapping = categories.filter(c => c.is_overlapping);

  return (
    <SectionCard
      testId="category-overlap-section"
      accent="bg-gradient-to-br from-amber-500 to-orange-600"
      icon={Layers}
      title="MF Category Overlap"
      subtitle="Categories with 2+ funds indicate redundancy — click a card to see which funds overlap"
    >
      {overlapping.length > 0 && (
        <div className="flex items-start gap-2 mb-3 px-3 py-2 rounded-xl bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-800 text-amber-700 dark:text-amber-300">
          <AlertTriangle className="w-3.5 h-3.5 flex-shrink-0 mt-0.5" />
          <p className="text-xs leading-relaxed">
            <strong>{overlapping.length}</strong> categories have 2+ funds — consider consolidating to the best performer in each.
          </p>
        </div>
      )}

      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-2" data-testid="category-overlap-grid">
        {categories.map((d, i) => {
          const isOverlapping = d.is_overlapping;
          const isOpen = expanded === i;
          return (
            <div key={`cat-${d.category}-${i}`}>
              <button
                onClick={() => setExpanded(isOpen ? null : i)}
                className={`w-full text-left rounded-xl p-3 border transition-all hover:shadow-sm ${
                  isOverlapping
                    ? "border-amber-200 dark:border-amber-800 bg-amber-50 dark:bg-amber-900/20"
                    : "border-emerald-200 dark:border-emerald-800 bg-emerald-50 dark:bg-emerald-900/10"
                }`}
                data-testid={`cat-card-${i}`}
              >
                <div className="flex items-center justify-between mb-1">
                  <span className={`text-xl font-bold tabular-nums ${isOverlapping ? "text-amber-600 dark:text-amber-400" : "text-emerald-600 dark:text-emerald-400"}`}
                    style={{ fontFamily: "'JetBrains Mono', monospace" }}>
                    {d.fund_count}
                  </span>
                  {isOverlapping
                    ? <AlertTriangle className="w-3.5 h-3.5 text-amber-400" strokeWidth={1.5} />
                    : <CheckCircle className="w-3.5 h-3.5 text-emerald-400" strokeWidth={1.5} />
                  }
                </div>
                <p className="text-xs font-semibold text-slate-700 dark:text-zinc-300 leading-tight">{d.category}</p>
                <p className="text-[10px] text-slate-400 dark:text-zinc-500 mt-0.5">
                  {isOverlapping ? "Potential overlap" : "Single fund"}
                </p>
              </button>

              <AnimatePresence>
                {isOpen && (d.funds || []).length > 0 && (
                  <motion.div
                    initial={{ opacity: 0, height: 0 }}
                    animate={{ opacity: 1, height: "auto" }}
                    exit={{ opacity: 0, height: 0 }}
                    transition={{ duration: 0.18 }}
                    className="overflow-hidden"
                  >
                    <div className={`mt-1 rounded-xl border p-2.5 space-y-1 ${
                      isOverlapping
                        ? "border-amber-200 dark:border-amber-800 bg-amber-50/50 dark:bg-amber-900/10"
                        : "border-emerald-200 dark:border-emerald-800 bg-emerald-50/50 dark:bg-emerald-900/10"
                    }`}>
                      {d.funds.map((f, fi) => (
                        <p key={fi} className="text-xs text-slate-600 dark:text-zinc-400 truncate">{f}</p>
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
    </SectionCard>
  );
};

// ── Loading / Empty states ────────────────────────────────────────

const LoadingState = () => (
  <div className="space-y-4">
    {[1, 2, 3].map(i => (
      <div key={i} className="h-48 rounded-2xl bg-slate-100 dark:bg-white/5 animate-pulse" />
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
  const [data, setData]       = useState(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr]         = useState(null);

  useEffect(() => {
    let alive = true;
    axios
      .get(`${API}/portfolio/exposure/concentration`, { withCredentials: true })
      .then(r  => { if (alive) setData(r.data); })
      .catch(e => { if (alive) setErr(e?.response?.data?.detail || e.message); })
      .finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, []);

  const ask = (topic) => {
    const prompts = {
      amc:     "Which AMC am I most concentrated in, and what should I do about it?",
      sector:  "Which sector has the highest concentration in my portfolio and how should I rebalance?",
      company: "Which underlying companies dominate my portfolio across direct stocks and mutual funds?",
      group:   "What is my exposure to business groups like HDFC, Reliance, or Tata, and is it too concentrated?",
      overlap: "Which companies do I hold through multiple routes, and how does that affect my effective exposure?",
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
    <div className="space-y-4" data-testid="concentration-analytics-tab">
      <ExposureSection
        testId="exposure-amc" kind="amc" viz="donut"
        title="AMC Exposure"
        subtitle="Concentration by fund house across your mutual fund portfolio"
        icon={Building2}
        accent="bg-gradient-to-br from-purple-500 to-indigo-600"
        items={data.amc?.items || []}
        hhi={data.amc?.hhi}
        effectiveN={data.amc?.effective_n}
        largestPct={data.amc?.largest_pct}
        warning={data.amc?.warning}
        heroInsight={data.amc?.hero_insight}
        secondary={`${data.amc?.all_items_count || 0} AMCs in portfolio`}
        onAskNivesh={() => ask("amc")}
      />

      <ExposureSection
        testId="exposure-sector" kind="sector" viz="donut"
        title="Sector Exposure"
        subtitle="Sector weights after dissolving mutual funds into their underlying holdings"
        icon={Layers}
        accent="bg-gradient-to-br from-emerald-500 to-teal-600"
        items={data.sector?.items || []}
        hhi={data.sector?.hhi}
        effectiveN={data.sector?.effective_n}
        largestPct={data.sector?.largest_pct}
        warning={data.sector?.warning}
        heroInsight={data.sector?.hero_insight}
        cycleSplit={data.sector?.cycle_split}
        secondary={`Look-through coverage: ${data.lookthrough_coverage ?? 0}%`}
        onAskNivesh={() => ask("sector")}
      />

      <ExposureSection
        testId="exposure-company" kind="company" viz="treemap"
        title="Company Exposure"
        subtitle="Top single-company exposures across direct equity + mutual fund look-through"
        icon={Briefcase}
        accent="bg-gradient-to-br from-rose-500 to-pink-600"
        items={data.company?.items || []}
        hhi={data.company?.hhi}
        effectiveN={data.company?.effective_n}
        largestPct={data.company?.largest_pct}
        warning={data.company?.warning}
        heroInsight={data.company?.hero_insight}
        top10Pct={data.company?.top10_pct}
        secondary={`${data.company?.all_items_count || 0} unique companies`}
        onAskNivesh={() => ask("company")}
      />

      <GroupExposureSection data={data.group} onAskNivesh={() => ask("group")} />

      <HiddenOverlapSection data={data.company?.hidden_overlap} onAskNivesh={() => ask("overlap")} />

      <CategoryOverlapSection deepAnalytics={deepAnalytics} />
    </div>
  );
};

export default ConcentrationAnalyticsTab;
