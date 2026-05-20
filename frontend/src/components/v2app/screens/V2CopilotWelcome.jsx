/**
 * V2CopilotWelcome.jsx — Persona-aware copilot empty state (v2 redesign)
 *
 * Implements the full UI/UX spec:
 * - Color-coded score with progress bar + trend
 * - Sub-metrics (Suitability / Diversification / Risk / Tax)
 * - KPI cards row for advisor personas
 * - Critical alerts section for advisor personas
 * - Reordered quick actions with time estimates + badges
 * - Improved AI suggestion chips
 */

import React, { useState, useEffect } from "react";
import { motion } from "framer-motion";
import {
  Bot, TrendingUp, Shield, BarChart3, Target, Users,
  Briefcase, LineChart, AlertTriangle, Globe, Microscope,
  Wallet, Zap, RefreshCw, FileText, Bell, Search,
  ArrowRight, Lightbulb, PieChart, BookOpen, Clock,
  TrendingDown, Activity, MessageSquare,
} from "lucide-react";
import { cn } from "@/lib/utils";

// ── Persona configs ───────────────────────────────────────────────────────────
const PERSONAS = {
  new_investor: {
    label: "New Investor", icon: BookOpen, color: "emerald",
    heroScore: "Investor Readiness Score",
    headline: "Let's build your investing foundation step by step.",
    actions: [
      { label: "Start my first SIP",    query: "Help me start my first SIP. What should I invest in and how much?",                icon: Zap,      time: "1 min"  },
      { label: "Set a financial goal",  query: "Help me set a financial goal. I want to understand goal-based investing.",          icon: Target,   time: "2 min"  },
      { label: "Build emergency fund",  query: "How do I build an emergency fund? How much should I keep and where?",              icon: Shield,   time: "1 min"  },
      { label: "Beginner's guide",      query: "Give me a beginner's guide to investing in India — mutual funds, SIPs, and risks.", icon: BookOpen, time: "3 min", badge: "Start here" },
    ],
  },
  retail_investor: {
    label: "Retail Investor", icon: TrendingUp, color: "indigo",
    heroScore: "Portfolio Health Score",
    headline: "Ask anything about your portfolio — rebalancing, tax, or returns.",
    actions: [
      { label: "Portfolio health check", query: "Run a full portfolio health check — quality, risk, overlap, and cost analysis.",    icon: BarChart3, time: "30s",  badge: "Popular" },
      { label: "Simulate rebalance",     query: "Simulate a rebalance for my portfolio. Show me the before and after allocation.",   icon: RefreshCw, time: "1 min", badge: "Recommended" },
      { label: "Optimise tax",           query: "How can I optimise tax on my portfolio? Show LTCG, STCG, and 80C opportunities.",   icon: Shield,    time: "45s"  },
      { label: "Generate report",        query: "Generate a detailed portfolio report with all key metrics and recommendations.",    icon: FileText,  time: "1 min" },
    ],
  },
  trader: {
    label: "Trader", icon: BarChart3, color: "amber",
    heroScore: "Signal Strength Score",
    headline: "Get real-time signals, setups, and position sizing guidance.",
    actions: [
      { label: "Show trade signals",  query: "Show me the strongest buy/sell signals in the market right now.",                   icon: Zap,      time: "30s",  badge: "Live"    },
      { label: "Options sentiment",   query: "What is the current options market sentiment? Show PCR, OI, and key strikes.",      icon: BarChart3, time: "45s"  },
      { label: "Position sizing",     query: "Help me with position sizing for my next trade. What is the ideal risk per trade?", icon: Target,    time: "1 min" },
      { label: "Set price alert",     query: "Help me set up a price alert strategy for my watchlist.",                          icon: Bell,      time: "1 min" },
    ],
  },
  mf_investor: {
    label: "Mutual Fund Investor", icon: PieChart, color: "indigo",
    heroScore: "Fund Suitability Score",
    headline: "Analyse fund quality, overlap, and find better alternatives.",
    actions: [
      { label: "Compare my funds",       query: "Compare the mutual funds in my portfolio. Show rolling returns, expense ratio, and overlap.", icon: BarChart3, time: "45s",  badge: "Popular" },
      { label: "Replace underperformer", query: "Which funds should I replace? Show me better alternatives in the same category.",            icon: RefreshCw, time: "1 min", badge: "Recommended" },
      { label: "Check fund overlap",     query: "Show me the overlap between my mutual funds at the stock level.",                            icon: Search,    time: "30s"  },
      { label: "Start a new SIP",        query: "Recommend the best funds to start a new SIP in right now based on my profile.",             icon: Zap,       time: "1 min" },
    ],
  },
  mfd: {
    label: "MF Distributor", icon: Users, color: "violet",
    heroScore: "Client Suitability Score",
    headline: "Manage your book — proposals, compliance, and client reviews.",
    isAdvisor: true,
    actions: [
      { label: "Client drift alerts",     query: "Which clients in my book have significant portfolio drift above 10%?",                 icon: AlertTriangle, time: "30s",  badge: "Urgent"  },
      { label: "Generate proposal",       query: "Generate a fund recommendation proposal for a client. Ask me for their details.",       icon: FileText,      time: "2 min", badge: "Popular" },
      { label: "Tax-loss harvesting",     query: "Identify tax-loss harvesting opportunities across my client book.",                    icon: Shield,        time: "1 min" },
      { label: "Simulate client SIP",     query: "Simulate a SIP plan for a client. What funds and amounts would you recommend?",        icon: RefreshCw,     time: "1 min" },
    ],
  },
  financial_advisor: {
    label: "Financial Advisor", icon: Briefcase, color: "violet",
    heroScore: "Advisory Recommendation Score",
    headline: "Your AI-powered advisory assistant for IPS, portfolio reviews, and client recommendations.",
    isAdvisor: true,
    actions: [
      { label: "Generate review report",      query: "Generate a quarterly portfolio review report for a client.",                             icon: BarChart3, time: "30s",  badge: "Popular"      },
      { label: "Rebalance recommendations",   query: "Generate rebalance recommendations for a client's portfolio with current drift.",      icon: RefreshCw, time: "1 min", badge: "Recommended"   },
      { label: "Suitability check",           query: "Run a suitability check for a recommended product against a client's risk profile.",    icon: Shield,    time: "45s"                          },
      { label: "Create IPS",                  query: "Help me create an Investment Policy Statement for a client.",                             icon: FileText,  time: "2 min"                        },
    ],
  },
  portfolio_analyst: {
    label: "Portfolio Analyst", icon: LineChart, color: "indigo",
    heroScore: "Portfolio Health Score",
    headline: "Attribution, diversification, and optimisation analysis.",
    actions: [
      { label: "Simulate rebalance",       query: "Simulate a portfolio rebalance showing attribution impact and risk-return change.",     icon: RefreshCw, time: "1 min", badge: "Popular" },
      { label: "Diversification analysis", query: "Run a diversification analysis — show sector, AMC, and market-cap concentration.",     icon: PieChart,   time: "45s"  },
      { label: "Compare alternatives",     query: "Compare current portfolio holdings against better alternatives in each category.",      icon: BarChart3,  time: "1 min" },
      { label: "Export report",            query: "Generate a full analytical report with alpha, beta, Sharpe ratio, and attribution.",   icon: FileText,   time: "2 min" },
    ],
  },
  portfolio_manager: {
    label: "Portfolio Manager", icon: Briefcase, color: "rose",
    heroScore: "Alpha & Risk Score",
    headline: "Monitor exposure, run scenarios, and generate order baskets.",
    actions: [
      { label: "Rebalance portfolio",    query: "Rebalance the portfolio — show target vs actual allocation and required trades.",       icon: RefreshCw,     time: "1 min", badge: "Recommended" },
      { label: "Run scenarios",          query: "Run a set of market scenarios — bull, bear, and base case — on the current portfolio.", icon: BarChart3,     time: "1 min" },
      { label: "Generate order basket",  query: "Generate an order basket for the rebalance with quantities and trade rationale.",      icon: FileText,      time: "2 min" },
      { label: "Exposure monitor",       query: "Show the current sector exposure, factor exposure, and contribution to risk.",         icon: AlertTriangle, time: "45s"  },
    ],
  },
  risk_analyst: {
    label: "Risk Analyst", icon: AlertTriangle, color: "rose",
    heroScore: "Overall Risk Score",
    headline: "Stress testing, limit monitoring, and correlation analysis.",
    actions: [
      { label: "Run stress test",         query: "Run a stress test on the portfolio — 2008 crash, COVID drop, and rate shock scenarios.", icon: AlertTriangle, time: "1 min", badge: "Recommended" },
      { label: "Correlation analysis",    query: "Show the correlation matrix of portfolio holdings and identify concentration risk.",    icon: BarChart3,     time: "45s"  },
      { label: "Simulate hedge",          query: "Suggest a hedging strategy for the current portfolio. Show options and cost.",          icon: Shield,        time: "1 min" },
      { label: "Generate risk report",    query: "Generate a comprehensive risk report with VaR, volatility, beta, and concentration.",  icon: FileText,      time: "2 min" },
    ],
  },
  market_analyst: {
    label: "Market Analyst", icon: Globe, color: "amber",
    heroScore: "Market Regime Score",
    headline: "Macro outlook, sector rotation, and weekly market intelligence.",
    actions: [
      { label: "Weekly market outlook",  query: "Generate a weekly market outlook — macro, FII/DII flows, and sector leadership.",        icon: Globe,    time: "1 min", badge: "Popular" },
      { label: "Sector rotation",        query: "Show the current sector rotation cycle and which sectors are leading vs lagging.",       icon: RefreshCw, time: "45s"  },
      { label: "FII/DII flow analysis",  query: "Analyse FII and DII flows this week. What are institutions buying and selling?",         icon: LineChart, time: "30s"  },
      { label: "Set market alerts",      query: "Help me set up alerts for key market events — VIX spikes, FII selling, circuit breaks.", icon: Bell,      time: "1 min" },
    ],
  },
  research_analyst: {
    label: "Research Analyst", icon: Microscope, color: "indigo",
    heroScore: "Research Conviction Score",
    headline: "Screen stocks, run factor analysis, and export research notes.",
    actions: [
      { label: "Screen stocks",        query: "Screen stocks using quality filters — ROCE >15%, low debt, earnings momentum.",          icon: Search,    time: "1 min", badge: "Popular" },
      { label: "Factor attribution",   query: "Run a factor attribution analysis — quality, value, momentum, and growth factors.",      icon: LineChart, time: "1 min" },
      { label: "Compare peers",        query: "Compare a company against its sector peers on valuation, returns, and growth.",          icon: BarChart3, time: "45s"  },
      { label: "Export research",      query: "Generate a research note with earnings momentum, ROCE trend, and valuation analysis.",   icon: FileText,  time: "2 min" },
    ],
  },
  wealth_manager: {
    label: "Wealth Manager", icon: Wallet, color: "emerald",
    heroScore: "Family Financial Health Score",
    headline: "Holistic wealth — family balance sheet, estate, and goal allocation.",
    actions: [
      { label: "Goal funding check",   query: "Check goal funding probability for all family goals — retirement, education, home.",       icon: Target,   time: "45s",  badge: "Recommended" },
      { label: "Optimise allocation",  query: "Optimise the asset allocation across the family portfolio for risk-adjusted returns.",     icon: PieChart, time: "1 min" },
      { label: "Family balance sheet", query: "Generate a family balance sheet showing assets, liabilities, and net worth.",             icon: FileText, time: "2 min" },
      { label: "Estate planning",      query: "Provide estate planning considerations for the current wealth and family structure.",      icon: Shield,   time: "2 min" },
    ],
  },
};

const COLOR_MAP = {
  emerald: { bg: "bg-emerald-500/10", border: "border-emerald-500/20", text: "text-emerald-400", badge: "bg-emerald-500/15 text-emerald-400 border-emerald-500/20" },
  indigo:  { bg: "bg-indigo-500/10",  border: "border-indigo-500/20",  text: "text-indigo-400",  badge: "bg-indigo-500/15 text-indigo-400 border-indigo-500/20"  },
  amber:   { bg: "bg-amber-500/10",   border: "border-amber-500/20",   text: "text-amber-400",   badge: "bg-amber-500/15 text-amber-400 border-amber-500/20"   },
  violet:  { bg: "bg-violet-500/10",  border: "border-violet-500/20",  text: "text-violet-400",  badge: "bg-violet-500/15 text-violet-400 border-violet-500/20"  },
  rose:    { bg: "bg-rose-500/10",    border: "border-rose-500/20",    text: "text-rose-400",    badge: "bg-rose-500/15 text-rose-400 border-rose-500/20"    },
};

// Score band → color
function scoreConfig(score) {
  if (score == null) return null;
  if (score >= 90) return { color: "text-emerald-400", ring: "border-emerald-500/40", bg: "bg-emerald-500/10", bar: "bg-emerald-500", label: "Excellent" };
  if (score >= 75) return { color: "text-violet-400",  ring: "border-violet-500/40",  bg: "bg-violet-500/10",  bar: "bg-violet-500",  label: "Good"      };
  if (score >= 60) return { color: "text-amber-400",   ring: "border-amber-500/40",   bg: "bg-amber-500/10",   bar: "bg-amber-500",   label: "Fair"      };
  return               { color: "text-rose-400",    ring: "border-rose-500/40",    bg: "bg-rose-500/10",    bar: "bg-rose-500",    label: "Needs Attention" };
}

// Badge color
const BADGE_COLORS = {
  "Popular":     "bg-indigo-500/15 text-indigo-400 border-indigo-500/20",
  "Recommended": "bg-violet-500/15 text-violet-300 border-violet-500/20",
  "Urgent":      "bg-rose-500/15 text-rose-400 border-rose-500/20",
  "Live":        "bg-emerald-500/15 text-emerald-400 border-emerald-500/20",
  "Start here":  "bg-amber-500/15 text-amber-400 border-amber-500/20",
  "New":         "bg-sky-500/15 text-sky-400 border-sky-500/20",
};

// ── Score count-up hook ───────────────────────────────────────────────────────
function useCountUp(target, duration = 900) {
  const [count, setCount] = useState(0);
  useEffect(() => {
    if (target == null) return;
    let start = 0;
    const step = Math.ceil(target / (duration / 16));
    const timer = setInterval(() => {
      start = Math.min(start + step, target);
      setCount(start);
      if (start >= target) clearInterval(timer);
    }, 16);
    return () => clearInterval(timer);
  }, [target, duration]);
  return count;
}

// ── detectPersona export ─────────────────────────────────────────────────────
export function detectPersona(workspace, holdings, userProfile) {
  const isAdvisory = workspace?.type === "ADVISORY";
  const hasPortfolio = Array.isArray(holdings) && holdings.length > 0;
  const journeyType = userProfile?.journey_type;

  if (isAdvisory) {
    if (journeyType === "mfd" || journeyType === "distributor") return "mfd";
    return "financial_advisor";
  }
  if (!hasPortfolio) return "new_investor";
  if (journeyType === "trader")           return "trader";
  if (journeyType === "mf_investor")      return "mf_investor";
  if (journeyType === "portfolio_manager") return "portfolio_manager";
  if (journeyType === "risk_analyst")     return "risk_analyst";
  if (journeyType === "market_analyst")   return "market_analyst";
  if (journeyType === "research_analyst") return "research_analyst";
  if (journeyType === "wealth_manager")   return "wealth_manager";
  if (journeyType === "portfolio_analyst") return "portfolio_analyst";
  return "retail_investor";
}

// ── Helpers ───────────────────────────────────────────────────────────────────
function formatRelativeTime(dateStr) {
  if (!dateStr) return "";
  const diff = Date.now() - new Date(dateStr);
  if (diff < 3600000)  return `${Math.floor(diff / 60000)}m ago`;
  if (diff < 86400000) return `${Math.floor(diff / 3600000)}h ago`;
  return new Date(dateStr).toLocaleDateString([], { month: "short", day: "numeric" });
}

// ── Sub-components ────────────────────────────────────────────────────────────

function KPICard({ label, value, icon: KIcon, color, onClick }) {
  const c = COLOR_MAP[color] || COLOR_MAP.indigo;
  return (
    <motion.button
      whileHover={{ scale: 1.02 }}
      onClick={onClick}
      className={cn(
        "flex flex-col items-start gap-2 p-3.5 rounded-xl border text-left transition-all hover:border-white/20",
        c.bg, c.border
      )}
    >
      <div className={cn("w-7 h-7 rounded-lg flex items-center justify-center border", c.bg, c.border)}>
        <KIcon className={cn("w-3.5 h-3.5", c.text)} strokeWidth={1.5} />
      </div>
      <div>
        <p className={cn("text-lg font-black tabular-nums leading-none", c.text)}>{value}</p>
        <p className="text-[10px] text-white/40 mt-0.5 leading-tight">{label}</p>
      </div>
    </motion.button>
  );
}

function AlertChip({ type, text, onAsk }) {
  const styles = {
    critical:    "bg-rose-500/10 border-rose-500/20 text-rose-400",
    warning:     "bg-amber-500/10 border-amber-500/20 text-amber-400",
    opportunity: "bg-emerald-500/10 border-emerald-500/20 text-emerald-400",
    info:        "bg-sky-500/10 border-sky-500/20 text-sky-400",
  };
  const icons = { critical: AlertTriangle, warning: Bell, opportunity: TrendingUp, info: Activity };
  const AlertIcon = icons[type] || Activity;
  return (
    <button
      onClick={() => onAsk(`Tell me more about this: ${text}`)}
      className={cn(
        "flex items-center gap-2 px-3 py-2 rounded-lg border text-xs font-medium transition-all hover:opacity-80 text-left",
        styles[type] || styles.info
      )}
    >
      <AlertIcon className="w-3.5 h-3.5 shrink-0" strokeWidth={1.5} />
      <span>{text}</span>
    </button>
  );
}

function SubMetric({ label, value, trend }) {
  const up = trend > 0;
  return (
    <div className="flex flex-col gap-0.5 p-3 bg-white/[0.03] rounded-xl border border-white/5">
      <p className="text-[9px] font-bold uppercase tracking-widest text-white/30">{label}</p>
      <div className="flex items-end gap-1.5">
        <p className="text-base font-black text-white tabular-nums">{value}%</p>
        {trend != null && (
          <span className={cn("text-[9px] font-bold mb-0.5", up ? "text-emerald-400" : "text-rose-400")}>
            {up ? "▲" : "▼"}{Math.abs(trend)}
          </span>
        )}
      </div>
    </div>
  );
}

// ── Main component ────────────────────────────────────────────────────────────
export default function V2CopilotWelcome({
  personaId = "retail_investor",
  analytics,
  workspace,
  onAsk,
  onSwitchSession,
  recentSessions = [],
  suggestedPrompts = [],
  suggestionsLoading = false,
  streaming = false,
}) {
  const persona  = PERSONAS[personaId] || PERSONAS.retail_investor;
  const colors   = COLOR_MAP[persona.color] || COLOR_MAP.indigo;
  const Icon     = persona.icon;
  const isAdvisor = Boolean(persona.isAdvisor);

  // Raw score from analytics
  const rawScore = (() => {
    const s = analytics?.health_score?.overall ?? analytics?.healthScore ?? analytics?.advisory_score;
    return s != null ? Math.round(s) : null;
  })();

  const animScore = useCountUp(rawScore);
  const sc = scoreConfig(rawScore);

  // Sub-metrics — only shown when real analytics fields are present (no fabricated fallbacks)
  const subMetrics = (() => {
    const candidates = [
      { label: "Suitability",     value: analytics?.suitability_score,    trend: analytics?.suitability_trend     ?? null },
      { label: "Diversification", value: analytics?.diversification_score, trend: analytics?.diversification_trend ?? null },
      { label: "Risk Alignment",  value: analytics?.risk_alignment_score,  trend: analytics?.risk_alignment_trend  ?? null },
      { label: "Tax Efficiency",  value: analytics?.tax_efficiency_score,  trend: null },
    ];
    return candidates.some(m => m.value != null) ? candidates : [];
  })();

  // KPI cards for advisor personas
  const clientCount   = workspace?.client_count   ?? analytics?.total_clients   ?? null;
  const reviewsDue    = analytics?.reviews_due     ?? analytics?.review_count    ?? null;
  const rebalanceOpp  = analytics?.rebalance_opportunity_cr ?? null;
  const revenuePot    = analytics?.revenue_potential_l ?? null;

  const kpis = isAdvisor ? [
    { label: "Clients to Contact", value: clientCount != null ? clientCount : "—", icon: Users,      color: "indigo"  },
    { label: "Reviews Due",        value: reviewsDue  != null ? reviewsDue  : "—", icon: FileText,   color: "amber"   },
    { label: "Rebalance Opp.",     value: rebalanceOpp != null ? `₹${rebalanceOpp}Cr` : "—", icon: RefreshCw, color: "violet"  },
    { label: "Revenue Potential",  value: revenuePot  != null ? `₹${revenuePot}L` : "—", icon: TrendingUp, color: "emerald" },
  ] : [];

  // Alerts for advisor personas (derive from analytics or show placeholders)
  const alerts = isAdvisor ? [
    analytics?.clients_needing_review > 0 && { type: "critical",    text: `${analytics.clients_needing_review} clients need portfolio review` },
    analytics?.unsuitable_portfolios  > 0 && { type: "critical",    text: `${analytics.unsuitable_portfolios} portfolios are unsuitable` },
    rebalanceOpp != null               && { type: "opportunity", text: `₹${rebalanceOpp} Cr rebalance opportunity available` },
    analytics?.sip_stoppage_risk      > 0 && { type: "warning",     text: `${analytics.sip_stoppage_risk} clients have SIP stoppage risk` },
  ].filter(Boolean) : [];

  // Sync timestamp (cosmetic)
  const syncLabel = analytics ? "Synced just now" : "Connecting…";

  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4, ease: [0.16, 1, 0.3, 1] }}
      className="flex flex-col items-center justify-start h-full py-8 px-4 overflow-y-auto"
      style={{ scrollbarWidth: "thin", scrollbarColor: "rgba(255,255,255,0.06) transparent" }}
    >
      <div className="w-full max-w-5xl space-y-5">

        {/* ── Header ── */}
        <div className="flex items-start justify-between gap-3">
          <div className="flex items-center gap-3 min-w-0">
            <div className={cn("w-10 h-10 rounded-xl flex items-center justify-center border shrink-0", colors.bg, colors.border)}>
              <Bot className={cn("w-5 h-5", colors.text)} strokeWidth={1.5} />
            </div>
            <div className="min-w-0">
              <h2 className="text-base font-bold text-white tracking-tight">Nivesh Copilot</h2>
              <p className="text-xs text-white/40 leading-snug">{persona.headline}</p>
              {isAdvisor && (
                <p className="text-[10px] text-white/20 mt-1 flex items-center gap-1.5">
                  {clientCount != null && <><span className="font-semibold text-white/30">{clientCount.toLocaleString()} Clients</span><span>·</span></>}
                  <span>{syncLabel}</span>
                  <span>·</span>
                  <span className="text-emerald-500/60">● All systems operational</span>
                </p>
              )}
            </div>
          </div>
          <span className={cn(
            "flex items-center gap-1.5 text-[9px] font-bold uppercase tracking-widest px-2.5 py-1.5 rounded-lg border shrink-0",
            colors.badge
          )}>
            <Icon className="w-3 h-3" strokeWidth={2} />
            {persona.label}
          </span>
        </div>

        {/* ── Hero Score card ── */}
        <div className={cn(
          "p-5 rounded-2xl border",
          sc ? `${sc.bg} ${sc.ring}` : `${colors.bg} ${colors.border}`
        )}>
          <div className="flex items-start justify-between gap-4">
            {/* Left */}
            <div className="flex-1 min-w-0">
              <p className="text-[9px] font-bold uppercase tracking-[0.2em] text-white/30 mb-1">Hero Metric</p>
              <p className="text-sm font-bold text-white leading-tight">{persona.heroScore}</p>
              {sc && (
                <p className={cn("text-[10px] font-semibold mt-1", sc.color)}>{sc.label}</p>
              )}
              {/* Progress bar */}
              {rawScore != null && (
                <div className="mt-3 space-y-1">
                  <div className="h-1.5 bg-white/5 rounded-full overflow-hidden">
                    <motion.div
                      className={cn("h-full rounded-full", sc?.bar || "bg-violet-500")}
                      initial={{ width: 0 }}
                      animate={{ width: `${rawScore}%` }}
                      transition={{ duration: 0.9, ease: [0.16, 1, 0.3, 1] }}
                    />
                  </div>
                  <div className="flex items-center gap-1.5">
                    {analytics?.score_trend != null && (
                      <span className={cn(
                        "text-[9px] font-bold flex items-center gap-0.5",
                        analytics.score_trend > 0 ? "text-emerald-400" : "text-rose-400"
                      )}>
                        {analytics.score_trend > 0 ? <TrendingUp className="w-2.5 h-2.5" /> : <TrendingDown className="w-2.5 h-2.5" />}
                        {analytics.score_trend > 0 ? "+" : ""}{analytics.score_trend} vs last review
                      </span>
                    )}
                  </div>
                </div>
              )}
            </div>

            {/* Right — score or CTA */}
            {rawScore != null ? (
              <div className="text-right shrink-0">
                <motion.p
                  className={cn("text-5xl font-black tabular-nums leading-none", sc?.color || colors.text)}
                >
                  {animScore}
                </motion.p>
                <p className="text-[10px] text-white/30 mt-1">out of 100</p>
              </div>
            ) : (
              <button
                onClick={() => onAsk(`Compute my ${persona.heroScore} and give me a detailed breakdown.`)}
                disabled={streaming}
                className={cn(
                  "flex items-center gap-1.5 px-3.5 py-2 rounded-xl text-xs font-bold border transition-all hover:opacity-80 disabled:opacity-40 shrink-0",
                  colors.badge
                )}
              >
                <Zap className="w-3.5 h-3.5" strokeWidth={2} />
                Compute Score
              </button>
            )}
          </div>

          {/* Sub-metrics row */}
          {subMetrics.length > 0 && (
            <div className="grid grid-cols-4 gap-2 mt-4 pt-4 border-t border-white/5">
              {subMetrics.map((m) => (
                <SubMetric key={m.label} {...m} />
              ))}
            </div>
          )}
        </div>

        {/* ── KPI cards (advisor only) ── */}
        {isAdvisor && (
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2.5">
            {kpis.map((k) => (
              <KPICard
                key={k.label}
                {...k}
                onClick={() => onAsk(`Show me details about ${k.label.toLowerCase()}.`)}
              />
            ))}
          </div>
        )}

        {/* ── Alerts (advisor only, when data available) ── */}
        {isAdvisor && alerts.length > 0 && (
          <div>
            <p className="text-[9px] font-bold uppercase tracking-[0.2em] text-white/30 mb-2">Critical Alerts</p>
            <div className="flex flex-col gap-1.5">
              {alerts.map((a, i) => (
                <AlertChip key={i} {...a} onAsk={onAsk} />
              ))}
            </div>
          </div>
        )}

        {/* ── Quick action cards ── */}
        <div>
          <p className="text-[9px] font-bold uppercase tracking-[0.2em] text-white/30 mb-3">Quick Actions</p>
          <div className="grid grid-cols-2 gap-2.5">
            {persona.actions.map((action, i) => {
              const ActionIcon = action.icon;
              return (
                <motion.button
                  key={action.label}
                  initial={{ opacity: 0, y: 8 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: 0.05 * i, duration: 0.3 }}
                  whileHover={{ scale: 1.015, transition: { duration: 0.15 } }}
                  onClick={() => onAsk(action.query)}
                  disabled={streaming}
                  className="flex items-start gap-3 p-4 bg-white/[0.03] hover:bg-white/[0.06] border border-white/10 hover:border-white/25 rounded-xl text-left transition-all group disabled:opacity-40 relative"
                >
                  <div className={cn(
                    "w-8 h-8 rounded-lg flex items-center justify-center shrink-0 border mt-0.5 transition-all group-hover:scale-105",
                    colors.bg, colors.border
                  )}>
                    <ActionIcon className={cn("w-4 h-4", colors.text)} strokeWidth={1.5} />
                  </div>
                  <div className="flex-1 min-w-0">
                    <p className="text-xs font-semibold text-white/80 group-hover:text-white transition-colors leading-snug">
                      {action.label}
                    </p>
                    {action.time && (
                      <p className="text-[9px] text-white/25 mt-0.5 flex items-center gap-1">
                        <Clock className="w-2.5 h-2.5" strokeWidth={1.5} />
                        {action.time}
                      </p>
                    )}
                  </div>
                  {action.badge && (
                    <span className={cn(
                      "text-[8px] font-bold uppercase tracking-wide px-1.5 py-0.5 rounded-full border shrink-0",
                      BADGE_COLORS[action.badge] || BADGE_COLORS.New
                    )}>
                      {action.badge}
                    </span>
                  )}
                  <ArrowRight className="w-3.5 h-3.5 text-white/10 group-hover:text-white/40 transition-colors shrink-0 mt-1 absolute right-3.5 bottom-3.5" />
                </motion.button>
              );
            })}
          </div>
        </div>

        {/* ── Recent Activity ── */}
        {recentSessions.length > 0 && onSwitchSession && (
          <div>
            <p className="text-[9px] font-bold uppercase tracking-[0.2em] text-white/30 mb-2">Recent Activity</p>
            <div className="space-y-1">
              {recentSessions.slice(0, 3).map((session) => (
                <motion.button
                  key={session.session_id}
                  whileHover={{ x: 2, transition: { duration: 0.15 } }}
                  onClick={() => onSwitchSession(session.session_id)}
                  disabled={streaming}
                  className="w-full flex items-center gap-3 px-3 py-2.5 bg-white/[0.02] hover:bg-white/[0.05] border border-white/5 hover:border-white/10 rounded-xl text-left transition-all group disabled:opacity-40"
                >
                  <MessageSquare className="w-3.5 h-3.5 text-white/20 group-hover:text-white/40 shrink-0" strokeWidth={1.5} />
                  <div className="flex-1 min-w-0">
                    <p className="text-xs text-white/55 group-hover:text-white/80 truncate transition-colors">
                      {session.title || "Untitled conversation"}
                    </p>
                    <p className="text-[9px] text-white/20 mt-0.5">
                      {formatRelativeTime(session.updated_at || session.created_at)}
                    </p>
                  </div>
                  <ArrowRight className="w-3 h-3 text-white/10 group-hover:text-white/30 shrink-0 transition-colors" />
                </motion.button>
              ))}
            </div>
          </div>
        )}

        {/* ── AI-driven suggestion chips ── */}
        {(suggestionsLoading || suggestedPrompts.length > 0) && (
          <div>
            <div className="flex items-center gap-3 mb-3">
              <div className="h-px flex-1 bg-white/5" />
              <p className="text-[9px] font-bold uppercase tracking-[0.2em] text-white/20">
                {suggestionsLoading ? "Analysing portfolio…" : "AI Suggested"}
              </p>
              <div className="h-px flex-1 bg-white/5" />
            </div>
            {suggestionsLoading ? (
              <div className="flex items-center justify-center gap-2 text-white/20 text-xs py-2">
                <RefreshCw className="w-3.5 h-3.5 animate-spin" />
                Loading personalised suggestions…
              </div>
            ) : (
              <div
                className="flex flex-wrap gap-2 pb-1"
              >
                {suggestedPrompts.slice(0, 8).map((p) => (
                  <button
                    key={p.id}
                    onClick={() => onAsk(p.query)}
                    disabled={streaming}
                    className="flex items-center gap-1.5 px-3 py-1.5 bg-white/5 hover:bg-white/[0.09] border border-white/10 hover:border-indigo-500/30 rounded-full text-xs text-white/50 hover:text-white transition-all disabled:opacity-40 whitespace-nowrap"
                  >
                    <Lightbulb className="w-3 h-3 text-indigo-400 shrink-0" strokeWidth={1.5} />
                    {p.label}
                  </button>
                ))}
              </div>
            )}
          </div>
        )}

        {/* ── Compliance footnote ── */}
        <p className="text-[9px] text-white/15 text-center pt-1">
          AI-generated guidance for informational purposes only. Past performance is not indicative of future results.
        </p>

      </div>
    </motion.div>
  );
}
