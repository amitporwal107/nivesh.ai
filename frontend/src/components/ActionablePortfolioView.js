import React, { useEffect, useMemo, useState } from "react";
import axios from "axios";
import { toast } from "sonner";
import {
  AlertTriangle, TrendingUp, TrendingDown, Shield, Zap, RefreshCw,
  Download, Filter, ChevronDown, ChevronRight, Info, X, Calendar,
} from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import DecisionCard from "./insights/DecisionCard";
import DiscoverInternationalView from "./insights/DiscoverInternationalView";
import PortfolioBuilderView from "./insights/PortfolioBuilderView";
import { Globe } from "lucide-react";
import PositionalPicks from "@/components/PositionalPicks";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;
const fmtINR = (n) => n == null ? "—" : `₹${Math.round(n).toLocaleString("en-IN")}`;
const fmtPct = (n, dp = 1) => n == null ? "—" : `${n.toFixed(dp)}%`;

// Normalise a fund name so two holdings of the same scheme but different
// plan / option / folio / abbreviation collapse to the same key. Used to
// flag duplicate holdings (Direct vs Regular vs Growth vs IDCW etc.).
const normaliseSchemeKey = (name) => {
  if (!name) return "";
  let n = ` ${String(name).toLowerCase()} `;
  // drop parenthetical notes ("(erstwhile…)", "(g)", etc.)
  n = n.replace(/\([^)]*\)/g, " ");
  // unify dashes / commas / dots / pipes / slashes to spaces
  n = n.replace(/[-,.|/]+/g, " ");
  // strip plan / option / dividend tokens
  const STRIP = [
    "direct plan", "regular plan", "direct", "regular",
    "growth option", "growth plan", "growth",
    "dividend reinvestment", "dividend payout", "dividend",
    "idcw payout", "idcw reinvestment", "idcw",
    "bonus", "annual", "quarterly", "monthly",
    "mutual fund", "fund of funds", "fund", "scheme",
  ];
  for (const tok of STRIP) {
    n = n.replace(new RegExp(`\\s${tok}\\s`, "g"), " ");
  }
  // common short suffixes left dangling
  n = n.replace(/\s(g|d|idcw|gr|gp)\s/g, " ");
  // drop leading 2-5 letter broker/CAS code: " dfg " / " mcog "
  n = n.replace(/^\s+[a-z]{2,5}\s+(?=[a-z])/, " ");
  return n.replace(/\s+/g, " ").trim();
};
const fmtSnapDate = (iso) => {
  if (!iso) return null;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" });
};

// Score band (Strong / Good / Average / Weak) — user-approved Feb 2026.
// `inverted` flips colours for Exit-score where LOW = GOOD.
const scoreBand = (v, inverted = false) => {
  if (v == null) return { label: "—", tone: "text-slate-400 bg-slate-50", hex: "#CBD5E1" };
  const good = inverted ? v < 20 : v >= 80;
  const ok   = inverted ? v < 40 : v >= 60;
  const avg  = inverted ? v < 60 : v >= 40;
  if (good) return { label: "Strong",  tone: "text-emerald-700 bg-emerald-50", hex: "#10B981" };
  if (ok)   return { label: "Good",    tone: "text-lime-700 bg-lime-50",       hex: "#84CC16" };
  if (avg)  return { label: "Average", tone: "text-amber-700 bg-amber-50",     hex: "#F59E0B" };
  return    { label: "Weak",     tone: "text-rose-700 bg-rose-50",      hex: "#EF4444" };
};

const BADGE_STYLE = {
  EXIT:   { bg: "bg-rose-100 text-rose-800 border-rose-200" },
  SWITCH: { bg: "bg-amber-100 text-amber-800 border-amber-200" },
  ADD:    { bg: "bg-emerald-100 text-emerald-800 border-emerald-200" },
  HOLD:   { bg: "bg-slate-100 text-slate-700 border-slate-200" },
  REVIEW: { bg: "bg-indigo-50 text-indigo-700 border-indigo-200" },
};

const ALERT_TONE = {
  danger:  "border-rose-200 bg-rose-50 text-rose-800",
  warning: "border-amber-200 bg-amber-50 text-amber-800",
  info:    "border-sky-200 bg-sky-50 text-sky-800",
};

const ASSET_TABS = [
  { id: "all",          label: "All",           test: () => true },
  { id: "mutual_fund",  label: "Mutual Funds",  test: (h) => h.asset_type === "mutual_fund" },
  { id: "equity",       label: "Stocks",        test: (h) => h.asset_type === "equity" },
  { id: "etf",          label: "ETFs",          test: (h) => h.asset_type === "etf" },
  { id: "gold",         label: "Gold / SGB",    test: (h) => h.asset_type === "gold" || /sgb|gold/i.test(h.name || "") },
  { id: "other",        label: "Other",         test: (h) => !["mutual_fund","equity","etf","gold"].includes(h.asset_type) },
];

const FILTERS = [
  { id: "all",   label: "All" },
  { id: "EXIT",  label: "🔴 Exit" },
  { id: "SWITCH",label: "🔁 Switch" },
  { id: "ADD",   label: "🟢 Add More" },
  { id: "HOLD",  label: "🟡 Hold" },
  { id: "WEAK",  label: "⚠️ Weak" },
  { id: "UNDERPERFORM", label: "📉 Underperformers" },
  { id: "REGULAR", label: "💸 Regular Plans" },
  { id: "UNSCORED", label: "⚠️ Unscored" },
];

const ScorePill = ({ value, inverted = false }) => {
  if (value == null) return <span className="text-slate-300">—</span>;
  const b = scoreBand(value, inverted);
  return (
    <span
      className={`inline-block px-2 py-0.5 rounded font-mono text-xs font-semibold ${b.tone}`}
      title={b.label}
    >
      {Math.round(value)}
    </span>
  );
};

// Star rating (1-5) from composite score. Shown as "Nivesh Rating" on each row.
const niveshStars = (composite) => {
  if (composite == null) return null;
  if (composite >= 80) return 5;
  if (composite >= 65) return 4;
  if (composite >= 50) return 3;
  if (composite >= 35) return 2;
  return 1;
};

const StarRating = ({ value, label = "Nivesh Rating", size = "sm", starColor = "text-amber-400" }) => {
  if (value == null) return null;
  const px = size === "sm" ? "text-[10px]" : "text-xs";
  const dull = "text-slate-200";
  return (
    <span className={`inline-flex items-center gap-0.5 ${px}`} title={`${label}: ${value}/5`} data-testid={`stars-${value}`}>
      {[1,2,3,4,5].map((n) => (
        <span key={n} className={n <= value ? starColor : dull}>★</span>
      ))}
    </span>
  );
};

// Dual rating pill — shows both Morningstar (if scraped) and Nivesh so users
// can compare third-party vs internal ratings side by side. When MS is missing
// we render a muted "—" so the layout stays stable.
const DualRating = ({ morningstar, nivesh }) => (
  <span className="inline-flex items-center gap-1.5 flex-shrink-0" data-testid="dual-rating">
    <span className="inline-flex items-center gap-0.5 text-[9px]"
          title={morningstar != null ? `Morningstar: ${morningstar}/5` : "Morningstar not yet scraped"}>
      <span className="text-slate-400 font-semibold mr-0.5">MS</span>
      {morningstar != null
        ? <StarRating value={morningstar} label="Morningstar Rating" starColor="text-sky-500" />
        : <span className="text-slate-300 italic">—</span>}
    </span>
    <span className="text-slate-200">·</span>
    <span className="inline-flex items-center gap-0.5 text-[9px]"
          title={nivesh != null ? `Nivesh (composite-derived): ${nivesh}/5` : "Not scored yet"}>
      <span className="text-emerald-600 font-semibold mr-0.5">N</span>
      {nivesh != null
        ? <StarRating value={nivesh} label="Nivesh Rating" starColor="text-amber-400" />
        : <span className="text-slate-300 italic">—</span>}
    </span>
  </span>
);

// Map each alert.component → a contextual CTA. Returns null when no CTA.
const resolveAlertCta = (alert, ctx) => {
  const { triggerRefresh, refreshing, setAssetTab, setFilter, setSortBy, scrollToTable } = ctx;
  const c = (alert.component || "").toLowerCase();
  if (alert.action_hint === "refresh_stock_fundamentals" || c === "data_coverage") {
    return {
      label: refreshing ? "Refreshing…" : "Refresh",
      icon: RefreshCw, spinning: refreshing, disabled: refreshing,
      onClick: triggerRefresh, testid: "btn-refresh-fundamentals",
    };
  }
  if (c === "allocation") {
    // In-place: focus the biggest-weight holdings so user can rebalance.
    return {
      label: "Show biggest positions",
      icon: Zap,
      onClick: () => {
        setAssetTab("all"); setFilter("all");
        setSortBy({ key: "value_rs", dir: "desc" });
        scrollToTable();
      },
      testid: `cta-alert-allocation`,
    };
  }
  if (c === "risk_alignment") {
    return {
      label: "Retake profile",
      icon: Shield,
      onClick: () => { window.location.hash = "risk_profile"; },
      testid: `cta-alert-risk`,
    };
  }
  if (c === "overlap" || c === "health") {
    return {
      label: "Show switches",
      icon: RefreshCw,
      onClick: () => { setFilter("SWITCH"); setAssetTab("mutual_fund"); scrollToTable(); },
      testid: `cta-alert-${c}`,
    };
  }
  if (c === "diversification") {
    // In-place: filter to weakest scored holdings so user can review what's concentrated.
    return {
      label: "Show weak holdings",
      icon: Zap,
      onClick: () => {
        setAssetTab("all"); setFilter("WEAK"); scrollToTable();
      },
      testid: `cta-alert-diversification`,
    };
  }
  if (c === "cost") {
    return {
      label: "Show switches",
      icon: RefreshCw,
      onClick: () => { setFilter("REGULAR"); setAssetTab("mutual_fund"); scrollToTable(); },
      testid: `cta-alert-cost`,
    };
  }
  return null;
};

const SUB_STYLE = {
  Keep:        "bg-slate-100 text-slate-700 border-slate-200",
  Watch:       "bg-sky-50 text-sky-700 border-sky-200",
  Review:      "bg-amber-50 text-amber-700 border-amber-200",
  Rebalance:   "bg-indigo-50 text-indigo-700 border-indigo-200",
  // SWITCH sub-flavours — visually distinct so users don't confuse a
  // pure cost optimisation with a fund-quality concern.
  "To Direct": "bg-teal-50 text-teal-700 border-teal-200",     // good fund, cheaper plan
  "To Peer":   "bg-amber-100 text-amber-800 border-amber-200", // switch to different fund
  "Reduce":    "bg-orange-50 text-orange-700 border-orange-200", // diversification trim
};

const ActionBadge = ({ badge }) => {
  if (!badge) return null;
  // HOLD or SWITCH → use sub_action label when present so the pill
  // communicates the actual flavour (Keep/Watch/Review/Rebalance for
  // HOLD; To Direct/To Peer/Reduce for SWITCH).
  const hasSub = !!badge.sub_action;
  const isHold = badge.action === "HOLD";
  const isSwitch = badge.action === "SWITCH";
  const showSub = hasSub && (isHold || isSwitch);
  const label = showSub ? badge.sub_action : badge.action;
  const style = showSub
    ? (SUB_STYLE[badge.sub_action] || (BADGE_STYLE[badge.action] || BADGE_STYLE.REVIEW).bg)
    : (BADGE_STYLE[badge.action] || BADGE_STYLE.REVIEW).bg;
  return (
    <span
      className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-md border text-[11px] font-semibold ${style}`}
      title={badge.reason || ""}
      data-testid={`action-badge-${badge.action}${showSub ? "-" + badge.sub_action.replace(/\s+/g, "-") : ""}`}
    >
      <span>{badge.emoji}</span>{label}
    </span>
  );
};

// Per-asset-type methodology shown in the Score Breakdown info popover.
// Mirrors the V3 weights from services/stock_scoring.py and v3 fund engine.
const METHODOLOGY = {
  equity: {
    title: "How we score stocks (V3 equity engine)",
    dims: [
      { label: "Fund Strength (Quality)", desc: "long-term durability",
        components: "ROE · 3y EPS growth · Earnings consistency · Debt/Equity · Promoter holding · Market-cap stability" },
      { label: "Performance Stability (Health)", desc: "current trajectory",
        components: "Revenue growth · Profit-margin trend · Debt trend · Earnings surprises · Volatility · Dividend yield" },
      { label: "Sell Pressure (Exit)", desc: "risk of holding longer",
        components: "PE overvaluation · Earnings decline · Quality deterioration · Debt spike · Liquidity risk · Tax impact" },
      { label: "Portfolio Fit (Add)", desc: "fit with your existing mix",
        components: "Sector gap · Low overlap · Relative valuation · Quality · Momentum · Dividend" },
    ],
    composite: "Composite = 40% Quality + 30% Health + 20% (100−Exit) + 10% Add",
    sources: "Data: Groww + Moneycontrol + Morningstar. Each primitive is normalised 0–100 and weighted.",
  },
  fund: {
    title: "How we score mutual funds (V3 fund engine)",
    dims: [
      { label: "Fund Strength (Quality)", desc: "manager skill + holdings quality",
        components: "5y rolling alpha · Sharpe · Holdings quality · Manager tenure · Expense efficiency" },
      { label: "Performance Stability (Health)", desc: "consistency across cycles",
        components: "1y/3y returns · Drawdown · Volatility · Category-relative momentum" },
      { label: "Sell Pressure (Exit)", desc: "reasons to switch out",
        components: "Underperformance · Mandate drift · Style mismatch · Plan-type cost · Fund age" },
      { label: "Portfolio Fit (Add)", desc: "incremental value to your portfolio",
        components: "Category gap · Overlap · Risk fit · Tax efficiency · Liquidity" },
    ],
    composite: "Composite = 40% Quality + 30% Health + 20% (100−Exit) + 10% Add",
    sources: "Data: AMFI NAV + Morningstar + AMC factsheets. Each primitive is normalised 0–100 and weighted.",
  },
};

const ScoringInfoPopover = ({ assetType }) => {
  const [open, setOpen] = useState(false);
  const meth = METHODOLOGY[assetType === "equity" ? "equity" : "fund"];
  return (
    <span className="relative inline-flex items-center">
      <button
        type="button"
        onClick={(e) => { e.stopPropagation(); setOpen((o) => !o); }}
        className="text-slate-400 hover:text-slate-600 transition-colors"
        aria-label="How scoring works"
        data-testid="scoring-info-toggle"
      >
        <Info className="w-3.5 h-3.5" />
      </button>
      {open && (
        <>
          <div
            className="fixed inset-0 z-30"
            onClick={(e) => { e.stopPropagation(); setOpen(false); }}
          />
          <div
            className="absolute left-0 top-5 z-40 w-[360px] bg-white border border-slate-200 rounded-lg shadow-lg p-3 text-[11px] text-slate-600 normal-case tracking-normal font-normal"
            onClick={(e) => e.stopPropagation()}
            data-testid="scoring-info-popover"
          >
            <div className="flex items-start justify-between mb-2">
              <strong className="text-slate-800 text-[12px]">{meth.title}</strong>
              <button
                type="button"
                onClick={() => setOpen(false)}
                className="text-slate-400 hover:text-slate-600 -mt-0.5"
                aria-label="Close"
              >
                <X className="w-3.5 h-3.5" />
              </button>
            </div>
            <ul className="space-y-2">
              {meth.dims.map((d) => (
                <li key={d.label}>
                  <div className="font-semibold text-slate-700">{d.label} <span className="text-slate-400 font-normal">— {d.desc}</span></div>
                  <div className="text-slate-500 leading-snug">{d.components}</div>
                </li>
              ))}
            </ul>
            <div className="mt-2 pt-2 border-t border-slate-100 text-slate-500 leading-snug">
              <div className="font-mono text-[10px] text-slate-700">{meth.composite}</div>
              <div className="mt-1">{meth.sources}</div>
            </div>
          </div>
        </>
      )}
    </span>
  );
};

const ExpandedRow = ({ h, onSwitch }) => {
  const s = h.scores || {};
  // Renamed labels per UX critique 2026-04-30: Quality→Fund Strength,
  // Health→Performance Stability, Exit→Sell Pressure, Add→Portfolio Fit.
  // Each chip now also exposes a one-line "why this matters" so users
  // don't need to know the engine internals to read the score.
  const subs = [
    { label: "Fund Strength",         value: s.quality, inverted: false,
      desc: "Long-term business quality of the fund's holdings",
      why: "A weak basket erodes returns over years of compounding." },
    { label: "Performance Stability", value: s.health,  inverted: false,
      desc: "Recent momentum + risk-adjusted consistency",
      why: "Stable performers reduce sequence-of-returns risk." },
    { label: "Sell Pressure",         value: s.exit,    inverted: true,
      desc: "How strongly the engine wants you out (lower = safer to keep)",
      why: "Higher = the fund is dragging the portfolio." },
    { label: "Portfolio Fit",         value: s.add,     inverted: false,
      desc: "How well a fresh allocation fits your current mix",
      why: "Higher = fills a gap, lower = duplicates exposure." },
  ];
  // Alpha-vs-benchmark numbers (live from /portfolio/holdings-enriched).
  const fundReturn = h.cagr_3y_pct ?? h.xirr_pct ?? null;
  const benchmarkReturn = h.benchmark_cagr_3y_pct ?? null;
  const benchmarkLabel = h.benchmark_label || h.benchmark_name || null;
  const expectedAlpha = h.expected_alpha_annual_pct ?? (h.switch_cost?.alpha_pct_annual ?? null);
  return (
    <tr className="bg-slate-50 border-b border-slate-100" data-testid={`row-expanded-${h.holding_id}`}>
      <td colSpan={11} className="p-5">
        {/* Hero card — single unified Decision Card answers the four
            questions (Why / What to do / Cost & Tax / Worth it?) in one
            place. Replaces the prior DecisionVerdict + SwitchCostPanel split.
            Stocks: parked until the equity engine is in place — show only
            score breakdown + returns/cost panels, no recommendation. */}
        {h.asset_type !== "equity" && <DecisionCard
          action={h.action_badge?.action}
          subAction={h.action_badge?.sub_action}
          scores={s}
          switchCost={h.switch_cost}
          investedRs={h.invested_rs}
          valueRs={h.value_rs}
          pnlRs={h.pnl_rs}
          buyDate={h.buy_date}
          isEquity={h.is_equity_fund != null ? h.is_equity_fund : !/(debt|liquid|bond|gilt|short term|low duration|money market)/i.test(h.category || h.name || "")}
          recommendationReason={h.recommendation_reason}
          allocationCurrent={h.weight_pct}
          allocationTarget={h.target_weight_pct}
          categoryRank={h.category_rank}
          categoryRankTotal={h.category_rank_total}
          categoryLabel={h.category}
          benchmarkLabel={benchmarkLabel}
          benchmarkReturn={benchmarkReturn}
          fundReturn={fundReturn}
          alphaAnnual={expectedAlpha}
          toFund={h.to_fund}
          toAllocationPct={h.to_allocation_pct}
        />}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
          <div className="lg:col-span-2">
            <h5 className="text-xs font-bold uppercase tracking-wider text-slate-500 mb-3 flex items-center gap-1.5">
              Score Breakdown
              <ScoringInfoPopover assetType={h.asset_type} />
            </h5>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
              {subs.map((x) => {
                const b = scoreBand(x.value, x.inverted);
                return (
                  <div key={x.label} className="bg-white rounded-xl p-3 border border-slate-100">
                    <div className="flex items-center justify-between mb-1.5">
                      <span className="text-xs font-semibold text-slate-600">{x.label}</span>
                      <ScorePill value={x.value} inverted={x.inverted} />
                    </div>
                    <div className="w-full h-1.5 rounded-full bg-slate-100 overflow-hidden">
                      <div className="h-full rounded-full transition-all"
                           style={{ width: `${x.value || 0}%`, background: b.hex }} />
                    </div>
                    <p className="text-[10px] text-slate-500 mt-1.5 leading-snug" title={x.why}>
                      <span className="font-semibold text-slate-600">{b.label}</span> · {x.desc}
                    </p>
                  </div>
                );
              })}
            </div>
            {h.recommendation_reason && (
              <div className="mt-3 text-[12px] text-slate-600 bg-white border border-slate-100 rounded-lg p-3">
                <strong className="text-slate-700">Why this action:</strong> {h.recommendation_reason}
              </div>
            )}
          </div>
          <div className="space-y-2">
            <h5 className="text-xs font-bold uppercase tracking-wider text-slate-500 mb-1">Returns / Cost</h5>
            <div className="text-[13px] bg-white rounded-xl p-3 border border-slate-100 space-y-1.5">
              <div className="flex justify-between">
                <span className="text-slate-500">
                  {h.xirr_source === "personal" ? "XIRR (avg-cost proxy)" :
                   h.xirr_source?.startsWith("cagr") ? `CAGR ${h.xirr_source.replace("cagr_","").toUpperCase()} (Groww)` : "Return"}
                </span>
                <span className={`font-mono font-semibold ${(h.xirr_pct || 0) >= 0 ? "text-emerald-600" : "text-rose-600"}`}>{fmtPct(h.xirr_pct, 2)}</span>
              </div>
              <div className="flex justify-between"><span className="text-slate-500">Abs. return</span><span className={`font-mono font-semibold ${(h.pnl_pct || 0) >= 0 ? "text-emerald-600" : "text-rose-600"}`}>{fmtPct(h.pnl_pct, 1)}</span></div>
              {h.cagr_3y_pct != null && h.xirr_source !== "cagr_3y" && (
                <div className="flex justify-between"><span className="text-slate-500">3y CAGR</span><span className="font-mono">{fmtPct(h.cagr_3y_pct, 1)}</span></div>
              )}
              {h.expense_ratio != null && (
                <div className="flex justify-between"><span className="text-slate-500">Expense ratio</span><span className="font-mono">{fmtPct(h.expense_ratio, 2)}</span></div>
              )}
              {h.is_regular_plan && (
                <div className="text-amber-700 text-[11px] flex items-center gap-1 pt-1">⚠ Regular plan — switch to Direct saves cost</div>
              )}
            </div>
            {h.asset_type !== "equity" && h.action_badge?.action === "SWITCH" && (
              <Button size="sm" className="w-full bg-amber-500 hover:bg-amber-600 text-white" onClick={() => onSwitch(h)} data-testid={`btn-open-switch-${h.holding_id}`}>
                <RefreshCw className="w-3.5 h-3.5 mr-1.5" />Explore switch options
              </Button>
            )}
          </div>
        </div>
      </td>
    </tr>
  );
};

const exportCSV = (rows) => {
  const headers = ["Name","Type","Sector","Qty","BuyPrice","CMP","Value","P&L","P&L%","XIRR%","Composite","Quality","Health","Exit","Add","Action","Reason"];
  const lines = [headers.join(",")];
  rows.forEach((h) => {
    const s = h.scores || {};
    const b = h.action_badge || {};
    lines.push([
      `"${(h.name || "").replace(/"/g, '""')}"`, h.asset_type, h.sector || "",
      h.quantity, h.buy_price, h.current_price, h.value_rs, h.pnl_rs, h.pnl_pct,
      h.xirr_pct ?? "", h.composite_score ?? "",
      s.quality ?? "", s.health ?? "", s.exit ?? "", s.add ?? "",
      b.action || "", `"${(b.reason || "").replace(/"/g, '""')}"`,
    ].join(","));
  });
  const blob = new Blob([lines.join("\n")], { type: "text/csv;charset=utf-8" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = `nivesh_portfolio_${new Date().toISOString().slice(0,10)}.csv`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
};

export default function ActionablePortfolioView() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [assetTab, setAssetTab] = useState("all");
  const [subCategory, setSubCategory] = useState("all");
  const [filter, setFilter] = useState("all");
  const [expanded, setExpanded] = useState(new Set());
  const [search, setSearch] = useState("");
  const [sortBy, setSortBy] = useState({ key: "value_rs", dir: "desc" });
  const [switchTarget, setSwitchTarget] = useState(null);
  const [refreshing, setRefreshing] = useState(false);
  const [snapInfo, setSnapInfo] = useState(null); // { current_snapshot_date, is_default_latest, latest_snapshot_date }
  const [discoverOpen, setDiscoverOpen] = useState(false);
  const tableRef = React.useRef(null);
  const scrollToTable = () => {
    tableRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  };

  const load = async () => {
    setLoading(true);
    try {
      const res = await axios.get(`${API}/portfolio/holdings-enriched`, { withCredentials: true });
      setData(res.data);
    } catch (e) { toast.error(e.response?.data?.detail || e.message); }
    finally { setLoading(false); }
  };
  const loadSnapInfo = async () => {
    try {
      const r = await axios.get(`${API}/portfolio/cas-snapshots`, {
        params: { limit: 1 }, withCredentials: true,
      });
      const d = r.data || {};
      const latest = (d.snapshots || [])[0]?.snapshot_date || null;
      setSnapInfo({
        current_snapshot_date: d.current_snapshot_date || latest,
        is_default_latest: d.is_default_latest !== false,
        latest_snapshot_date: latest,
      });
    } catch {
      setSnapInfo(null);
    }
  };
  useEffect(() => { load(); loadSnapInfo(); }, []);

  const triggerRefresh = async () => {
    setRefreshing(true);
    try {
      await axios.post(`${API}/portfolio/refresh-stock-fundamentals`, null, { withCredentials: true });
      toast.success("Fundamentals refresh started");
      setTimeout(load, 3000);
    } catch (e) { toast.error(e.message); }
    finally { setRefreshing(false); }
  };

  // Reset sub-category when asset tab changes so chips don't vanish mid-interaction.
  React.useEffect(() => { setSubCategory("all"); }, [assetTab]);

  // Derive sub-category chips from the CURRENT asset-tab-filtered rows.
  // Stocks → sector. MF/ETF/Gold → `category` (which now holds sub_category when
  // v3 sets it, e.g. "Flexi Cap", "Small Cap", "Dynamic Asset Allocation").
  const subCategoryOptions = useMemo(() => {
    if (!data || assetTab === "all") return [];
    const tab = ASSET_TABS.find((t) => t.id === assetTab) || ASSET_TABS[0];
    const rows = data.holdings.filter(tab.test);
    const useField = assetTab === "equity" ? "sector" : "category";
    const counts = {};
    for (const h of rows) {
      const key = h[useField] || "Uncategorised";
      counts[key] = (counts[key] || 0) + 1;
    }
    return Object.entries(counts)
      .sort((a, b) => b[1] - a[1])  // most-populated first
      .map(([label, count]) => ({ id: label, label, count }));
  }, [data, assetTab]);

  const assetCounts = useMemo(() => {
    const counts = {};
    if (!data) return counts;
    ASSET_TABS.forEach((t) => {
      counts[t.id] = data.holdings.filter(t.test).length;
    });
    return counts;
  }, [data]);

  // Map every duplicate-fund holding_id → metadata about the cluster it
  // belongs to (group size, total ₹ value across the cluster). Two holdings
  // are considered duplicates when their normalised scheme key matches AND
  // they are mutual funds / ETFs (stocks aren't grouped because the same
  // ticker appearing twice is genuinely the same holding, not a duplicate
  // pattern). Result is computed off the *unfiltered* holdings list so the
  // badge is stable when the user toggles tabs / filters.
  const duplicateInfo = useMemo(() => {
    const map = new Map();
    if (!data) return map;
    // Common AMC-prefix tokens that are NOT scheme-distinguishing on their
    // own. When the CAS parser truncates a name to just these, treat the
    // row as "name not granular enough" and skip clustering.
    const AMC_ONLY = new Set([
      "hdfc", "icici", "icici prudential", "sbi", "axis", "kotak",
      "uti", "nippon", "nippon india", "sundaram", "tata", "dsp",
      "mirae", "mirae asset", "aditya birla", "aditya birla sun life",
      "franklin", "franklin india", "quant", "edelweiss", "invesco",
      "motilal oswal", "ppfas", "parag parikh", "pgim", "canara robeco",
      "hsbc", "lic", "lic mf", "jm", "navi", "samco", "trust",
    ]);
    // Detect plan from the original (pre-normalised) name. Returns
    // "direct", "regular", or "" if neither token is present.
    const planOf = (name) => {
      const n = (name || "").toLowerCase();
      if (/\bdirect\b/.test(n)) return "direct";
      if (/\bregular\b/.test(n)) return "regular";
      return "";
    };
    const groups = new Map();   // key → [{id, ticker, plan}]
    const totals = new Map();   // key → cumulative ₹ value
    for (const h of data.holdings) {
      const at = (h.asset_type || "").toLowerCase();
      if (at !== "mutual_fund" && at !== "mutual fund" && at !== "etf") continue;
      const qty = Number(h.quantity || 0);
      const val = Number(h.value_rs || 0);
      if (qty <= 0 && val <= 0) continue;
      const key = normaliseSchemeKey(h.name);
      if (!key) continue;
      const tokens = key.split(/\s+/).filter(Boolean);
      if (tokens.length < 3 || key.length < 12 || AMC_ONLY.has(key)) continue;
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key).push({ id: h.holding_id, ticker: h.ticker, plan: planOf(h.name) });
      totals.set(key, (totals.get(key) || 0) + (h.value_rs || 0));
    }
    let groupIdx = 0;
    for (const [key, items] of groups.entries()) {
      if (items.length < 2) continue;
      // Real cross-plan duplicate = SAME normalised scheme present as BOTH
      // Direct and Regular. Multi-folio of the same plan (e.g. 3 Direct
      // folios of HDFC Balanced) is NOT a duplicate — those are legit
      // separate folios that share the same scheme. Same for distinct
      // ISINs sharing a short prefix.
      const plans = new Set(items.map((it) => it.plan).filter(Boolean));
      if (!(plans.has("direct") && plans.has("regular"))) continue;
      // Final guard: if all tickers (ISINs) are the same, it's the same
      // exact instrument bought twice — not a Direct/Regular pair (those
      // have different ISINs). Skip.
      const tickers = items.map((it) => (it.ticker || "").trim()).filter(Boolean);
      const uniqueTickers = new Set(tickers);
      if (uniqueTickers.size < 2) continue;
      groupIdx += 1;
      const meta = { group: groupIdx, count: items.length, total_value: totals.get(key) || 0, key };
      items.forEach((it) => map.set(it.id, meta));
    }
    return map;
  }, [data]);

  const filtered = useMemo(() => {
    if (!data) return [];
    let rows = data.holdings;
    // Hide fully-redeemed positions (qty == 0 AND value == 0) — they
    // clutter the table and falsely trigger the duplicate detector when
    // a Regular plan has been switched out but the row stuck around.
    rows = rows.filter((h) => {
      const q = Number(h.quantity || 0);
      const v = Number(h.value_rs || 0);
      return q > 0 || v > 0;
    });
    // Asset-type tab first
    const tab = ASSET_TABS.find((t) => t.id === assetTab) || ASSET_TABS[0];
    rows = rows.filter(tab.test);
    if (subCategory !== "all" && assetTab !== "all") {
      const useField = assetTab === "equity" ? "sector" : "category";
      rows = rows.filter((h) => (h[useField] || "Uncategorised") === subCategory);
    }
    if (search.trim()) {
      const q = search.toLowerCase();
      rows = rows.filter(h => (h.name || "").toLowerCase().includes(q) || (h.sector || "").toLowerCase().includes(q));
    }
    if (filter !== "all") {
      if (filter === "UNDERPERFORM") rows = rows.filter(h => (h.pnl_pct || 0) < 0);
      else if (filter === "REGULAR") rows = rows.filter(h => h.is_regular_plan);
      else if (filter === "UNSCORED") rows = rows.filter(h => !h.scores || h.scores.quality == null);
      else if (filter === "WEAK") rows = rows.filter(h => (h.composite_score || 100) < 50);
      // Action-based filters apply to funds only — stock recommendations
      // are parked, so equity rows must not match SWITCH/ADD/HOLD/EXIT.
      else rows = rows.filter(h => h.asset_type !== "equity" && h.action_badge?.action === filter);
    }
    rows = [...rows].sort((a, b) => {
      const A = a[sortBy.key]; const B = b[sortBy.key];
      if (A == null && B == null) return 0;
      if (A == null) return 1;
      if (B == null) return -1;
      return sortBy.dir === "asc" ? (A > B ? 1 : -1) : (A > B ? -1 : 1);
    });
    return rows;
  }, [data, assetTab, subCategory, filter, search, sortBy]);

  const toggleExpand = (id) => {
    const next = new Set(expanded);
    next.has(id) ? next.delete(id) : next.add(id);
    setExpanded(next);
  };

  const th = (label, key) => (
    <th className="p-2.5 text-xs font-bold uppercase tracking-wider text-slate-500 whitespace-nowrap cursor-pointer select-none"
        onClick={() => setSortBy({ key, dir: sortBy.key === key && sortBy.dir === "desc" ? "asc" : "desc" })}>
      {label}{sortBy.key === key && <span className="ml-1">{sortBy.dir === "desc" ? "↓" : "↑"}</span>}
    </th>
  );

  if (loading) return <div className="p-10 text-center text-slate-500">Loading portfolio…</div>;
  if (!data || !data.holdings.length) {
    // Empty state — show the AI Portfolio Builder so the advisor can
    // propose a starting portfolio while CAS upload is pending.
    return (
      <div className="p-4 sm:p-6 max-w-4xl mx-auto" data-testid="portfolio-empty-state">
        <div className="rounded-md border border-slate-200 bg-slate-50 px-4 py-3 mb-4 text-[12px] text-slate-600">
          No holdings yet. Upload a CAS to import existing investments — or use the AI Portfolio Builder below to propose a starting portfolio from the risk profile + goals on file.
        </div>
        <PortfolioBuilderView />
      </div>
    );
  }

  const t = data.totals || {};
  const lastRefreshed = new Date().toLocaleString("en-IN", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
  return (
    <div className="p-4 sm:p-6 space-y-5" data-testid="actionable-portfolio-view">
      {/* Page Header */}
      <div className="flex flex-wrap items-center justify-between gap-3 pb-2" data-testid="portfolio-header">
        <div>
          <div className="flex items-center gap-2 flex-wrap">
            <h1 className="text-2xl sm:text-3xl font-bold text-slate-900 tracking-tight">Portfolio</h1>
            {snapInfo?.current_snapshot_date && (
              <span
                className={`inline-flex items-center gap-1.5 text-[11px] font-semibold px-2 py-0.5 rounded-full border ${
                  snapInfo.is_default_latest
                    ? "bg-indigo-50 text-indigo-700 border-indigo-200"
                    : "bg-amber-50 text-amber-800 border-amber-200"
                }`}
                title={
                  snapInfo.is_default_latest
                    ? "Showing the latest CAS snapshot"
                    : `Showing an older snapshot. Latest is ${fmtSnapDate(snapInfo.latest_snapshot_date)}.`
                }
                data-testid="portfolio-snapshot-badge"
              >
                <Calendar className="w-3 h-3" />
                Snapshot · {fmtSnapDate(snapInfo.current_snapshot_date)}
                {!snapInfo.is_default_latest && <span className="ml-0.5">(historical)</span>}
              </span>
            )}
          </div>
          <p className="text-[12px] text-slate-500 mt-0.5">
            {t.count || 0} holdings across {Object.entries(assetCounts).filter(([k,v]) => k !== "all" && v > 0).length} asset classes
            <span className="mx-1.5 text-slate-300">·</span>
            Last refreshed {lastRefreshed}
            <span className="mx-1.5 text-slate-300">·</span>
            <span className={(data.coverage_pct || 0) >= 80 ? "text-emerald-600" : "text-amber-600"}>{fmtPct(data.coverage_pct)} scored</span>
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button
            size="sm"
            variant={discoverOpen ? "default" : "outline"}
            onClick={() => setDiscoverOpen((v) => !v)}
            data-testid="header-toggle-discover-intl"
            className={discoverOpen ? "bg-emerald-600 hover:bg-emerald-700 text-white" : ""}
          >
            <Globe className="w-3.5 h-3.5 mr-1" />
            {discoverOpen ? "Hide international" : "Discover international"}
          </Button>
          <Button size="sm" variant="outline" onClick={triggerRefresh} disabled={refreshing} data-testid="header-refresh-scores">
            <RefreshCw className={`w-3.5 h-3.5 mr-1 ${refreshing ? "animate-spin" : ""}`} />
            {refreshing ? "Scoring…" : "Refresh scores"}
          </Button>
          <Button size="sm" variant="outline"
            onClick={async () => {
              try {
                const API = process.env.REACT_APP_BACKEND_URL;
                const res = await fetch(`${API}/api/portfolio/refresh-stock-morningstar`, { method: "POST", credentials: "include" });
                const d = await res.json();
                alert(d.message || "Done");
                load();
              } catch (e) {
                alert("MS refresh failed: " + e.message);
              }
            }}
            data-testid="header-refresh-ms-ratings"
            title="Fetch Morningstar star ratings for all equity holdings"
          >
            <RefreshCw className="w-3.5 h-3.5 mr-1" />MS Ratings
          </Button>
          <Button size="sm" variant="outline" onClick={() => exportCSV(filtered)} data-testid="header-export-csv">
            <Download className="w-3.5 h-3.5 mr-1" />Export
          </Button>
          <Button size="sm" variant="outline" onClick={load} disabled={loading} data-testid="header-reload">
            <RefreshCw className={`w-3.5 h-3.5 mr-1 ${loading ? "animate-spin" : ""}`} />
            Reload
          </Button>
        </div>
      </div>

      {/* Discover International panel — toggles on demand. */}
      {discoverOpen && (
        <div className="border-t border-slate-200 pt-4" data-testid="discover-international-section">
          <DiscoverInternationalView />
        </div>
      )}

      {/* Hero totals */}
      <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
        <Card><CardContent className="p-4">
          <div className="text-[10px] uppercase text-slate-400 font-bold">Value</div>
          <div className="text-xl font-bold text-slate-900 mt-1">{fmtINR(t.value_rs)}</div>
        </CardContent></Card>
        <Card><CardContent className="p-4">
          <div className="text-[10px] uppercase text-slate-400 font-bold">Invested</div>
          <div className="text-xl font-bold text-slate-900 mt-1">{fmtINR(t.invested_rs)}</div>
        </CardContent></Card>
        <Card><CardContent className="p-4">
          <div className="text-[10px] uppercase text-slate-400 font-bold">P&L</div>
          <div className={`text-xl font-bold mt-1 ${(t.pnl_rs || 0) >= 0 ? "text-emerald-600" : "text-rose-600"}`}>{fmtINR(t.pnl_rs)} <span className="text-sm">({fmtPct(t.pnl_pct)})</span></div>
        </CardContent></Card>
        <Card><CardContent className="p-4">
          <div className="text-[10px] uppercase text-slate-400 font-bold flex items-center gap-1">
            XIRR
            <span title="Value-weighted average of per-holding returns. Uses personal XIRR where buy_date + avg cost are reliable; falls back to 3y CAGR from Groww for mutual funds.">
              <Info className="w-3 h-3 text-slate-300" />
            </span>
          </div>
          <div className={`text-xl font-bold mt-1 ${(t.xirr_pct || 0) >= 0 ? "text-emerald-600" : "text-rose-600"}`}>{fmtPct(t.xirr_pct, 2)}</div>
          <div className="text-[10px] text-slate-400 mt-0.5">value-weighted</div>
        </CardContent></Card>
        <Card><CardContent className="p-4">
          <div className="text-[10px] uppercase text-slate-400 font-bold flex items-center gap-1">
            Score Coverage
            <span title="% of mutual funds + equities with fundamentals scored. Low coverage? Click the Refresh button in the alert banner below.">
              <Info className="w-3 h-3 text-slate-300" />
            </span>
          </div>
          <div className="text-xl font-bold text-slate-900 mt-1">{fmtPct(data.coverage_pct)}</div>
          <div className="text-[10px] text-slate-400 mt-0.5">MFs + equities</div>
        </CardContent></Card>
      </div>

      {/* Score-band legend */}
      <div className="flex flex-wrap items-center gap-2 text-[11px] text-slate-500" data-testid="score-legend">
        <span className="font-semibold text-slate-500 uppercase tracking-wider">Score guide:</span>
        <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded bg-emerald-50 text-emerald-700 border border-emerald-100 font-mono">80+ Strong</span>
        <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded bg-lime-50 text-lime-700 border border-lime-100 font-mono">60–80 Good</span>
        <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded bg-amber-50 text-amber-700 border border-amber-100 font-mono">40–60 Average</span>
        <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded bg-rose-50 text-rose-700 border border-rose-100 font-mono">&lt;40 Weak</span>
        <span className="text-slate-400 italic ml-2">Exit score is inverted — lower is better.</span>
      </div>

      {/* Portfolio Impact Strip */}
      {data.portfolio_impact && data.portfolio_impact.pending_actions > 0 && (
        <motion.div
          initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }}
          className="rounded-xl border border-emerald-100 bg-gradient-to-r from-emerald-50 via-white to-sky-50 p-4"
          data-testid="impact-strip"
        >
          <div className="flex flex-wrap items-center gap-4 justify-between">
            <div className="flex items-center gap-3">
              <Zap className="w-5 h-5 text-emerald-600 flex-shrink-0" />
              <div>
                <div className="text-sm font-bold text-slate-800">
                  If you complete all {data.portfolio_impact.pending_actions} pending actions:
                </div>
                <div className="text-[12px] text-slate-600 mt-0.5 flex flex-wrap gap-x-4 gap-y-1">
                  {data.portfolio_impact.estimated_cost_savings_rs_per_yr > 0 && (
                    <span>💰 <strong className="text-emerald-700" data-testid="impact-cost-savings">₹{Math.round(data.portfolio_impact.estimated_cost_savings_rs_per_yr).toLocaleString("en-IN")}/yr</strong> cost savings</span>
                  )}
                  {data.portfolio_impact.estimated_value_freed_rs > 0 && (
                    <span>🔓 <strong className="text-sky-700" data-testid="impact-value-freed">{fmtINR(data.portfolio_impact.estimated_value_freed_rs)}</strong> freed for rebalancing</span>
                  )}
                  {data.portfolio_impact.health_delta != null && data.portfolio_impact.health_delta !== 0 && (
                    <span>📈 Health <strong className="text-indigo-700" data-testid="impact-health">{data.portfolio_impact.health_current}→{data.portfolio_impact.health_projected} ({data.portfolio_impact.health_delta > 0 ? "+" : ""}{data.portfolio_impact.health_delta})</strong></span>
                  )}
                  <span className="text-slate-500">{data.portfolio_impact.by_action.EXIT} Exit · {data.portfolio_impact.by_action.SWITCH} Switch · {data.portfolio_impact.by_action.ADD} Add</span>
                </div>
              </div>
            </div>
            <Button
              size="sm"
              className="bg-emerald-600 hover:bg-emerald-700 text-white"
              onClick={() => { window.location.hash = "plan_board"; }}
              data-testid="impact-open-plan"
            >
              Open Plan Board <ChevronRight className="w-3.5 h-3.5 ml-0.5" />
            </Button>
          </div>
        </motion.div>
      )}

      {/* Alerts banner */}
      {data.alerts?.length > 0 && (
        <div className="space-y-2" data-testid="portfolio-alerts">
          {data.alerts.map((a, i) => {
            const cta = resolveAlertCta(a, { triggerRefresh, refreshing, setAssetTab, setFilter, setSortBy, scrollToTable });
            return (
              <motion.div key={i} initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i * 0.05 }}
                          className={`flex items-start gap-3 p-3 rounded-xl border ${ALERT_TONE[a.severity] || ALERT_TONE.info}`}
                          data-testid={`alert-${a.component}`}>
                <AlertTriangle className="w-4 h-4 mt-0.5 flex-shrink-0" />
                <div className="flex-1 min-w-0">
                  <div className="font-semibold text-sm">{a.title}</div>
                  <div className="text-[12px] opacity-80">{a.detail}</div>
                </div>
                {cta && (
                  <Button
                    size="sm" variant="outline"
                    onClick={cta.onClick} disabled={cta.disabled}
                    data-testid={cta.testid}
                    className="flex-shrink-0"
                  >
                    {cta.icon && <cta.icon className={`w-3.5 h-3.5 mr-1 ${cta.spinning ? "animate-spin" : ""}`} />}
                    {cta.label}
                  </Button>
                )}
              </motion.div>
            );
          })}
        </div>
      )}

      {/* Asset-type tabs */}
      <div className="border-b border-slate-200" data-testid="asset-tabs">
        <div className="flex flex-wrap items-center gap-1">
          {ASSET_TABS.map((t) => {
            const count = assetCounts[t.id] || 0;
            if (t.id !== "all" && count === 0) return null;
            const active = assetTab === t.id;
            return (
              <button
                key={t.id}
                onClick={() => setAssetTab(t.id)}
                className={`px-4 py-2 text-sm font-semibold transition-all border-b-2 -mb-px ${
                  active
                    ? "border-emerald-500 text-emerald-700"
                    : "border-transparent text-slate-500 hover:text-slate-900"
                }`}
                data-testid={`asset-tab-${t.id}`}
              >
                {t.label} <span className={`ml-1 text-[11px] ${active ? "text-emerald-600" : "text-slate-400"}`}>({count})</span>
              </button>
            );
          })}
        </div>
      </div>

      {/* Sub-category chips — only visible for a specific asset tab */}
      {assetTab !== "all" && subCategoryOptions.length > 1 && (
        <div
          className="flex items-center gap-1.5 overflow-x-auto pb-1 -mt-1"
          data-testid="subcat-chips"
        >
          <span className="text-[10px] font-bold uppercase tracking-wider text-slate-400 mr-1 flex-shrink-0">
            {assetTab === "equity" ? "Sector" : "Category"}:
          </span>
          <button
            onClick={() => setSubCategory("all")}
            className={`flex-shrink-0 px-2.5 py-1 rounded-full text-[11px] font-semibold transition-all ${
              subCategory === "all"
                ? "bg-slate-900 text-white"
                : "bg-slate-100 text-slate-600 hover:bg-slate-200"
            }`}
            data-testid="subcat-all"
          >
            All ({subCategoryOptions.reduce((a, c) => a + c.count, 0)})
          </button>
          {subCategoryOptions.map((o) => (
            <button
              key={o.id}
              onClick={() => setSubCategory(o.id)}
              className={`flex-shrink-0 px-2.5 py-1 rounded-full text-[11px] font-semibold transition-all ${
                subCategory === o.id
                  ? "bg-slate-900 text-white"
                  : "bg-slate-100 text-slate-600 hover:bg-slate-200"
              }`}
              data-testid={`subcat-${o.id.toLowerCase().replace(/\s+/g, "-")}`}
            >
              {o.label} <span className={subCategory === o.id ? "text-slate-300" : "text-slate-400"}>({o.count})</span>
            </button>
          ))}
        </div>
      )}

      {/* Duplicate-funds rollup banner — only when at least one cluster
          exists. Tells the advisor at a glance how many duplicate
          mutual-fund holdings (Direct + Regular variants of the same
          scheme) are inflating the portfolio. */}
      {duplicateInfo.size > 0 && (() => {
        const groupCount = new Set([...duplicateInfo.values()].map((m) => m.group)).size;
        const totalValue = [...new Set([...duplicateInfo.entries()].map(([, m]) => `${m.group}:${m.total_value}`))]
          .reduce((s, kv) => s + parseFloat(kv.split(":")[1] || 0), 0);
        return (
          <div
            data-testid="duplicate-funds-banner"
            className="rounded-lg border-l-4 border-amber-400 bg-amber-50 px-3 py-2 flex items-start gap-2"
          >
            <span className="text-amber-600 text-sm leading-none mt-0.5">⚠</span>
            <div className="text-[12px] text-amber-900 leading-relaxed">
              <strong>{groupCount}</strong> duplicate fund {groupCount === 1 ? "scheme" : "schemes"} detected
              ({duplicateInfo.size} holdings · {fmtINR(totalValue)} total). Look for Regular vs Direct twins —
              consolidating into the Direct plan typically saves ~0.7-1% p.a. in expense ratio.
            </div>
          </div>
        );
      })()}

      {/* Positional Picks — 5–30 day technical trade ideas (Chartink + technical
          scoring). Stocks-only signal — irrelevant for the MF / ETF / Gold tabs,
          so we render it only when the user is viewing the Stocks tab. */}
      {assetTab === "equity" && <PositionalPicks />}

      {/* Filters + Search + Export */}
      <div className="flex flex-wrap items-center gap-2 justify-between">
        <div className="flex flex-wrap items-center gap-1.5">
          {FILTERS.map((f) => (
            <button key={f.id}
                    onClick={() => setFilter(f.id)}
                    className={`px-3 py-1.5 rounded-full text-xs font-semibold transition-all ${
                      filter === f.id ? "bg-slate-900 text-white" : "bg-slate-100 text-slate-700 hover:bg-slate-200"
                    }`}
                    data-testid={`filter-${f.id}`}>
              {f.label}
            </button>
          ))}
        </div>
        <div className="flex items-center gap-2">
          <input type="search" placeholder="Search holding…" value={search} onChange={(e) => setSearch(e.target.value)}
                 className="px-3 py-1.5 text-sm rounded border border-slate-200 bg-white w-48"
                 data-testid="portfolio-search" />
          <Button size="sm" variant="outline" onClick={() => exportCSV(filtered)} data-testid="btn-export-csv">
            <Download className="w-3.5 h-3.5 mr-1" />CSV
          </Button>
          <Button size="sm" variant="outline" onClick={load} disabled={loading}>
            <RefreshCw className={`w-3.5 h-3.5 mr-1 ${loading ? "animate-spin" : ""}`} />Refresh
          </Button>
        </div>
      </div>

      {/* Main table */}
      <Card ref={tableRef}>
        <div className="overflow-x-auto">
          <table className="min-w-full text-sm">
            <thead className="sticky top-0 z-10 bg-white shadow-sm border-b-2 border-slate-200">
              <tr>
                <th className="w-8"></th>
                {th("Holding", "name")}
                <th className="p-2.5 text-xs font-bold uppercase tracking-wider text-slate-500">Type</th>
                {th("Qty", "quantity")}
                {th("CMP", "current_price")}
                {th("Value", "value_rs")}
                {th("P&L%", "pnl_pct")}
                {th("XIRR", "xirr_pct")}
                {th("Score", "composite_score")}
                <th className="p-2.5 text-xs font-bold uppercase tracking-wider text-slate-500">Action</th>
              </tr>
            </thead>
            <tbody data-testid="portfolio-table-body">
              {filtered.map((h) => {
                const dup = duplicateInfo.get(h.holding_id);
                return (
                <React.Fragment key={h.holding_id}>
                  <tr className={`border-b border-slate-100 hover:bg-slate-50 cursor-pointer ${dup ? "bg-amber-50/40" : ""}`}
                      onClick={() => toggleExpand(h.holding_id)}
                      data-testid={`row-${h.holding_id}`}>
                    <td className="p-2.5 text-slate-400">{expanded.has(h.holding_id) ? <ChevronDown className="w-4 h-4" /> : <ChevronRight className="w-4 h-4" />}</td>
                    <td className="p-2.5">
                      <div className="flex items-center gap-2 max-w-xs">
                        <div
                          className="font-semibold text-slate-900 text-[13px] truncate flex-1"
                          title={`${h.name}${h.ticker ? `\nISIN: ${h.ticker}` : ""}${h.folio_number ? `\nFolio: ${h.folio_number}` : ""}`}
                          data-testid={`name-${h.holding_id}`}
                        >
                          {h.name}
                        </div>
                        <DualRating morningstar={h.morningstar_rating} nivesh={niveshStars(h.composite_score)} />
                      </div>
                      {dup && (
                        <div className="mt-0.5">
                          <span
                            className="inline-flex items-center gap-1 text-[9px] font-bold uppercase tracking-wider px-1.5 py-0.5 rounded bg-amber-100 text-amber-800 border border-amber-200"
                            title={`${dup.count} holdings of the same fund (Direct & Regular variants combined). Total ₹${Math.round(dup.total_value).toLocaleString("en-IN")} — consolidating into the Direct plan typically saves ~0.7-1% p.a.`}
                            data-testid={`dup-badge-${h.holding_id}`}
                          >
                            ⚠ Duplicate · {dup.count} variants
                          </span>
                        </div>
                      )}
                      <div className="text-[10px] text-slate-400 flex items-center gap-2 flex-wrap">
                        <span>{h.sector || h.nse_symbol || ""}</span>
                        {h.category_rank && h.category_rank_total && h.category_rank_total > 3 && (
                          <span
                            className={`px-1.5 py-0 rounded-sm font-mono text-[9px] font-semibold ${
                              h.category_rank <= Math.ceil(h.category_rank_total * 0.1)
                                ? "bg-emerald-50 text-emerald-700"
                                : h.category_rank <= Math.ceil(h.category_rank_total * 0.25)
                                ? "bg-lime-50 text-lime-700"
                                : h.category_rank <= Math.ceil(h.category_rank_total * 0.5)
                                ? "bg-amber-50 text-amber-700"
                                : "bg-rose-50 text-rose-700"
                            }`}
                            title={`Rank ${h.category_rank} of ${h.category_rank_total} in ${h.category || "category"} (by V3 Quality)`}
                            data-testid={`cat-rank-${h.holding_id}`}
                          >
                            #{h.category_rank}/{h.category_rank_total}
                          </span>
                        )}
                      </div>
                      {h.action_badge?.reason && (
                        <div className="text-[10px] text-slate-500 italic mt-0.5 truncate max-w-md"
                             title={h.action_badge.reason}
                             data-testid={`row-why-${h.holding_id}`}>
                          <span className="text-slate-400">Why:</span> {h.action_badge.reason}
                        </div>
                      )}
                    </td>
                    <td className="p-2.5 text-[11px] capitalize text-slate-500">{h.asset_type.replace("_", " ")}</td>
                    <td className="p-2.5 font-mono text-right">{h.quantity}</td>
                    <td className="p-2.5 font-mono text-right">{fmtINR(h.current_price)}</td>
                    <td className="p-2.5 font-mono text-right font-semibold">{fmtINR(h.value_rs)}</td>
                    <td className={`p-2.5 font-mono text-right ${(h.pnl_pct || 0) >= 0 ? "text-emerald-600" : "text-rose-600"}`}>{fmtPct(h.pnl_pct)}</td>
                    <td className={`p-2.5 font-mono text-right ${(h.xirr_pct || 0) >= 0 ? "text-emerald-600" : "text-rose-600"}`}>{fmtPct(h.xirr_pct, 1)}</td>
                    <td className="p-2.5 text-center"><ScorePill value={h.composite_score} /></td>
                    <td className="p-2.5">
                      <div className="flex items-center gap-1.5 flex-wrap">
                        <ActionBadge badge={h.action_badge} />
                        {h.asset_type !== "equity" && h.action_badge?.action === "SWITCH" && (
                          <button
                            onClick={(e) => { e.stopPropagation(); setSwitchTarget(h); }}
                            className="text-[10px] font-semibold text-amber-700 hover:text-amber-900 underline underline-offset-2"
                            data-testid={`inline-switch-${h.holding_id}`}
                          >
                            Switch →
                          </button>
                        )}
                      </div>
                    </td>
                  </tr>
                  <AnimatePresence>
                    {expanded.has(h.holding_id) && <ExpandedRow h={h} onSwitch={setSwitchTarget} />}
                  </AnimatePresence>
                </React.Fragment>
                );
              })}
            </tbody>
          </table>
          {filtered.length === 0 && (
            <div className="text-center py-12 text-slate-400 text-sm">No holdings match this filter.</div>
          )}
        </div>
      </Card>

      {/* Switch modal */}
      <AnimatePresence>
        {switchTarget && (
          <SwitchPanel holding={switchTarget} onClose={() => setSwitchTarget(null)} />
        )}
      </AnimatePresence>
    </div>
  );
}

// ── Switch Panel (Phase 2) ──
const SwitchPanel = ({ holding, onClose }) => {
  const [loading, setLoading] = useState(true);
  const [data, setData] = useState(null);
  useEffect(() => {
    let m = true;
    (async () => {
      try {
        const res = await axios.get(`${API}/portfolio/switch-candidates`, {
          params: { holding_id: holding.holding_id }, withCredentials: true,
        });
        if (m) setData(res.data);
      } catch (e) { if (m) setData({ candidates: [] }); }
      finally { if (m) setLoading(false); }
    })();
    return () => { m = false; };
  }, [holding.holding_id]);

  return (
    <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
                className="fixed inset-0 z-50 bg-black/50 backdrop-blur-sm flex items-center justify-center p-4"
                onClick={onClose} data-testid="switch-panel">
      <motion.div initial={{ scale: 0.95, y: 20 }} animate={{ scale: 1, y: 0 }} exit={{ scale: 0.95 }}
                  onClick={(e) => e.stopPropagation()}
                  className="bg-white rounded-2xl shadow-xl w-full max-w-3xl max-h-[85vh] overflow-auto">
        <div className="sticky top-0 bg-white z-10 p-5 border-b flex items-center justify-between">
          <div>
            <h3 className="text-lg font-bold">Switch from <span className="text-amber-600">{holding.name}</span></h3>
            <p className="text-xs text-slate-500 mt-0.5">Top replacement candidates in the same category</p>
          </div>
          <button onClick={onClose} className="p-1.5 hover:bg-slate-100 rounded" data-testid="switch-close"><X className="w-4 h-4" /></button>
        </div>
        <div className="p-5 space-y-3">
          {loading && <p className="text-sm text-slate-500 text-center py-6">Finding alternatives…</p>}
          {!loading && (!data?.candidates || data.candidates.length === 0) && (
            <p className="text-sm text-slate-500 text-center py-6">No suitable replacements found in this category.</p>
          )}
          {!loading && data?.candidates?.map((c, i) => {
            const ss = c.switch_score || {};
            // Tier the Switch Score colour so a low score (32, 38) never
            // renders in the same emerald as a strong one (70+). The
            // unified emerald-on-everything was misleading users.
            const score = ss.switch_score;
            const scoreColour = score == null ? "text-slate-400"
              : score >= 60 ? "text-emerald-600"
              : score >= 45 ? "text-amber-600"
              : "text-rose-600";
            // Honest cost framing: when expense_ratio_new is missing we
            // can't compute a cost gain; when it's higher than the old
            // ER we show the *extra cost* in red instead of clamping to 0%.
            const costSigned = ss.cost_gain_pct_signed;
            const costNode = costSigned == null
              ? <span className="text-slate-400">—</span>
              : costSigned > 0
                ? <span className="text-emerald-700">+{costSigned.toFixed(1)}%</span>
                : costSigned < 0
                  ? <span className="text-rose-600">{costSigned.toFixed(1)}% (extra cost)</span>
                  : <span className="text-slate-500">0%</span>;
            const expenseNode = ss.expense_ratio_new == null
              ? <span className="text-slate-400">— vs {ss.expense_ratio_old?.toFixed(2)}%</span>
              : <>{ss.expense_ratio_new.toFixed(2)}% vs {ss.expense_ratio_old?.toFixed(2)}%</>;
            const exitNode = ss.exit_load_pct > 0
              ? `${ss.exit_load_pct.toFixed(1)}%`
              : <span className="text-slate-400">None</span>;
            return (
              <div key={i} className="border rounded-xl p-4 hover:border-emerald-300 transition-colors" data-testid={`switch-candidate-${i}`}>
                <div className="flex items-start justify-between gap-3 mb-2">
                  <div>
                    <div className="font-semibold text-slate-900">{c.name}</div>
                    <div className="text-[11px] text-slate-500">{c.category} · {c.amc || ""}</div>
                  </div>
                  <div className="text-right">
                    <div className="text-[10px] uppercase text-slate-400">Switch Score</div>
                    <div className={`text-2xl font-bold ${scoreColour}`}>{score?.toFixed(0) || "—"}</div>
                  </div>
                </div>
                <div className="grid grid-cols-2 md:grid-cols-4 gap-2 text-[11px] mt-3">
                  <div className="bg-slate-50 rounded p-2">
                    <div className="text-slate-400">Δ Quality</div>
                    <div className={`font-semibold ${ss.delta_quality > 0 ? "text-emerald-600" : ss.delta_quality < 0 ? "text-rose-600" : "text-slate-500"}`}>
                      {ss.delta_quality > 0 ? "+" : ""}{ss.delta_quality?.toFixed(1)}
                      {ss.delta_quality === 0 && <span className="text-[10px] text-slate-400 ml-1">same</span>}
                    </div>
                  </div>
                  <div className="bg-slate-50 rounded p-2">
                    <div className="text-slate-400">Expense</div>
                    <div className="font-semibold">{expenseNode}</div>
                  </div>
                  <div className="bg-slate-50 rounded p-2">
                    <div className="text-slate-400">Cost gain</div>
                    <div className="font-semibold">{costNode}</div>
                  </div>
                  <div className="bg-slate-50 rounded p-2">
                    <div className="text-slate-400">Exit load</div>
                    <div className="font-semibold">{exitNode}</div>
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      </motion.div>
    </motion.div>
  );
};
