import React, { useEffect, useState, useCallback, useMemo } from "react";
import axios from "axios";
import { toast } from "sonner";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import {
  LayoutDashboard, TrendingUp, TrendingDown, Target, AlertTriangle, CheckCircle2,
  Calendar, Sparkles, ArrowRight, Activity, Scale, RefreshCw, Plus, Eye,
  ShieldCheck, Receipt, Share2, Mail, MessageSquare, StickyNote, Save, Copy,
  Wallet, IndianRupee, ChevronDown, ChevronRight, Zap, PieChart, Bot, Link2,
} from "lucide-react";
import NiveshCopilot from "./NiveshCopilot";
import TimeMachineStrip from "./TimeMachineStrip";
import ClientCasInviteModal from "./ClientCasInviteModal";
import CasTimeMachine from "./CasTimeMachine";
import HealthScoreInfo from "./HealthScoreInfo";
import ExportHoldingsButton from "@/components/ExportHoldingsButton";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

/**
 * Client 360 Snapshot — the "open client → see everything that matters"
 * screen. Shown only while the MFD is impersonating a client. Pulls
 * already-exposed endpoints (no new backend needed):
 *
 *   - /api/insights/analysis  → Portfolio Health + components
 *   - /api/goals              → goal tracking
 *   - /api/action-plan        → active action cards
 *
 * The goal is a single-screen answer to "What's happening with this
 * client?". Everything on this page is either a number or a CTA — no
 * secondary navigation needed.
 */

const fmtRs = (n) => {
  if (n == null) return "—";
  if (n >= 1e7) return `₹${(n / 1e7).toFixed(2)} Cr`;
  if (n >= 1e5) return `₹${(n / 1e5).toFixed(2)} L`;
  return `₹${Math.round(n).toLocaleString("en-IN")}`;
};

const fmtDaysAgo = (iso) => {
  if (!iso) return "Not yet";
  const d = Math.floor((Date.now() - new Date(iso).getTime()) / 86400000);
  if (d === 0) return "today";
  if (d === 1) return "yesterday";
  if (d < 30) return `${d} days ago`;
  if (d < 365) return `${Math.floor(d / 30)} mo ago`;
  return `${Math.floor(d / 365)} yr ago`;
};

const healthTone = (v) => (v == null ? "slate" : v >= 70 ? "emerald" : v >= 50 ? "amber" : "rose");

const TONE = {
  emerald: { text: "text-emerald-600", bar: "bg-emerald-500", ring: "text-emerald-500", bgSoft: "bg-emerald-50 dark:bg-emerald-900/20", border: "border-emerald-200 dark:border-emerald-800" },
  amber:   { text: "text-amber-600",   bar: "bg-amber-500",   ring: "text-amber-500",   bgSoft: "bg-amber-50 dark:bg-amber-900/20",     border: "border-amber-200 dark:border-amber-800" },
  rose:    { text: "text-rose-600",    bar: "bg-rose-500",    ring: "text-rose-500",    bgSoft: "bg-rose-50 dark:bg-rose-900/20",       border: "border-rose-200 dark:border-rose-800" },
  indigo:  { text: "text-indigo-600",  bar: "bg-indigo-500",  ring: "text-indigo-500",  bgSoft: "bg-indigo-50 dark:bg-indigo-900/20",   border: "border-indigo-200 dark:border-indigo-800" },
  slate:   { text: "text-slate-500",   bar: "bg-slate-400",   ring: "text-slate-400",   bgSoft: "bg-slate-100 dark:bg-slate-800",       border: "border-slate-200 dark:border-slate-700" },
};

// V3 plan actions use uppercase `type` values — lowercase for lookup.
const ACTION_VIEW = {
  exit:         { label: "Exit",         Icon: RefreshCw, tone: "rose"    },
  switch:       { label: "Switch",       Icon: RefreshCw, tone: "rose"    },
  reduce:       { label: "Reduce",       Icon: RefreshCw, tone: "rose"    },
  rebalance:    { label: "Rebalance",    Icon: Scale,     tone: "amber"   },
  increase_sip: { label: "Increase SIP", Icon: TrendingUp,tone: "indigo"  },
  add_more:     { label: "Add more",     Icon: Plus,      tone: "indigo"  },
  add:          { label: "Add more",     Icon: Plus,      tone: "indigo"  },
};

// ── Top issues + projected health ────────────────────────────────────
// Uses the pre-computed `risk_drivers` array from /insights/analysis. Each
// driver carries an `impact_points` value (improvement possible within its
// component). We multiply by component weight to project the portfolio-
// level delta, and cap the projection at 100.
const computeTopIssues = (health) => {
  if (!health?.risk_drivers?.length) return { issues: [], projected: null };
  const components = health.components || {};
  // Lookup weight by component name (drivers carry `component` like "Diversification").
  const weightByName = {};
  for (const c of Object.values(components)) {
    if (c?.name) weightByName[c.name] = c.weight || 0;
  }
  const issues = health.risk_drivers.slice(0, 3).map((d) => {
    const weight = weightByName[d.component] || 0;
    const portfolioDelta = (d.impact_points || 0) * weight;
    return {
      label: d.label,
      detail: d.detail,
      component: d.component,
      impact: portfolioDelta,
    };
  });
  const totalDelta = issues.reduce((s, x) => s + x.impact, 0);
  const projected = health.health_score != null
    ? Math.min(100, Math.round(health.health_score + totalDelta))
    : null;
  return { issues, projected, totalDelta };
};

// ── Wealth tier detection ─────────────────────────────────────────────
// HNI threshold set to ₹5 Cr as per product brief. Above this we show a
// subtle "Wealth tier" chip next to the client name and unlock the
// Rebalance All CTA / deeper tax narrative.
const wealthTierFor = (aumRs) => {
  if (aumRs == null) return { key: "unknown", label: null };
  if (aumRs >= 25e7) return { key: "uhni",    label: "UHNI · ₹25 Cr+" };
  if (aumRs >= 5e7)  return { key: "hni",     label: "HNI · ₹5 Cr+" };
  if (aumRs >= 1e7)  return { key: "mass",    label: "Mass affluent" };
  return { key: "retail", label: null };
};

// Estimate the gross rupee impact of the client's entire action plan
// (sum of `amount` across all open actions). Shown as the label inside
// the "Execute All" CTA so the MFD sees "₹1.2 Cr shifts" upfront.
const grossActionValue = (actions) =>
  (actions || []).reduce((s, a) => s + (a.amount || 0), 0);

// CIO-tone narrative — sharper + more specific than Pass-2 generic
// template. Same signature as buildNarrative so callers stay compatible.
const buildCioNarrative = ({ health, actions, tax, trend }) => {
  if (!health?.components) return null;
  const entries = Object.entries(health.components)
    .filter(([, c]) => c?.score != null)
    .map(([, c]) => ({ name: c.name, score: c.score, drivers: c.drivers || [] }));
  if (!entries.length) return null;
  const sorted   = [...entries].sort((a, b) => b.score - a.score);
  const weakest  = sorted[sorted.length - 1];
  const grade    = health.grade;
  const critical = actions.filter((a) => bucketFor(a) === "critical").length;

  // Line 1 — sharp framing
  const l1 = grade === "A"
    ? "Portfolio is structurally sound with consistent quality and performance."
    : grade === "B"
      ? `Portfolio is moderately strong but carries elevated ${weakest.name.toLowerCase()} risk.`
      : grade === "C"
        ? `Portfolio is underperforming its structure — ${weakest.name.toLowerCase()} is the primary drag.`
        : `Portfolio has material structural issues across ${weakest.name.toLowerCase()} and needs a full review.`;

  // Line 2 — performance statement (only if trend available)
  const l2 = trend?.percent_change != null
    ? `Since inception, corpus is ${trend.percent_change >= 0 ? "up" : "down"} ${Math.abs(trend.percent_change).toFixed(1)}% (${trend.percent_change >= 0 ? "+" : "-"}${fmtRs(Math.abs(trend.absolute_change_rs || 0))}).`
    : null;

  // Line 3 — tax + action pressure
  const taxLine = tax && Math.abs(tax.total_unrealized_rs || 0) > 50000
    ? ` Unrealized ${tax.total_unrealized_rs >= 0 ? "gain" : "loss"} is ${fmtRs(Math.abs(tax.total_unrealized_rs))} — rebalance needs a tax lens.`
    : "";
  const l3 = critical > 0
    ? `A targeted rebalance across ${critical} critical action${critical === 1 ? "" : "s"} can improve stability without compromising returns.${taxLine}`
    : `No urgent actions; monitor ${weakest.name.toLowerCase()} and keep allocations in band.${taxLine}`;

  return [l1, l2, l3].filter(Boolean).join(" ");
};

// Allocation-drift extractor — pulls the asset allocation sub-scores from
// the Diversification component so we can render the "Equity 68% (ideal
// 55%)" block without another backend endpoint. Returns null when the
// backend hasn't published allocation data.
const allocationDriftFor = (health) => {
  const c = Object.values(health?.components || {}).find((x) =>
    (x?.name || "").toLowerCase().includes("diversification"),
  );
  const alloc = c?.sub_scores?.allocation_breakdown
             || c?.allocation_breakdown
             || c?.sub_scores?.asset_allocation;
  if (!alloc || typeof alloc !== "object") return null;
  return alloc;   // { current: {equity, debt, ...}, target: {equity, debt, ...} }
};



// Product cap — keep in sync with MAX_GOALS in GoalsView.jsx and backend.
const MAX_GOALS_CLIENT = 4;

const buildNarrative = ({ health, actions, goals }) => {
  if (!health?.components) return null;
  const entries = Object.entries(health.components)
    .filter(([, c]) => c?.score != null)
    .map(([, c]) => ({ name: c.name, score: c.score }));
  if (!entries.length) return null;
  const sorted = [...entries].sort((a, b) => b.score - a.score);
  const strongest = sorted[0];
  const weakest   = sorted[sorted.length - 1];
  const grade     = health.grade;
  const criticalCount = actions.filter((a) => bucketFor(a) === "critical").length;

  // Line 1 — grade-level framing
  const l1 = grade === "A"
    ? "This is a high-quality portfolio overall — solid fundamentals across the board."
    : grade === "B"
      ? "This portfolio is in decent shape overall but has one or two clear gaps worth fixing."
      : grade === "C"
        ? "This portfolio needs attention — several components are below target and are dragging the health score down."
        : "This portfolio has multiple structural issues that warrant an active review.";

  // Line 2 — strongest + weakest contrast
  const l2 = `Strongest area is ${strongest.name.toLowerCase()} (${Math.round(strongest.score)}/100)`
    + `; the weakest is ${weakest.name.toLowerCase()} (${Math.round(weakest.score)}/100).`;

  // Line 3 — fix pressure
  const l3 = criticalCount > 0
    ? `${criticalCount} critical action${criticalCount === 1 ? "" : "s"} are open — clearing ${criticalCount === 1 ? "it" : "them"} has the highest short-term impact on health.`
    : actions.length > 0
      ? `Open recommendations are all optimisations — no urgent fire to put out.`
      : `No open recommendations — portfolio is on autopilot.`;

  // Line 4 — goal context (only if any goals exist)
  const l4 = (goals || []).length
    ? `${goals.length} goal${goals.length === 1 ? "" : "s"} tracked; keep SIPs steady to stay on course.`
    : null;

  return [l1, l2, l3, l4].filter(Boolean).join(" ");
};


// ── Reason-code → human label + badge mapping ────────────────────────
const REASON_CODE_META = {
  AMC_CONCENTRATION_EXIT:     { label: "Cuts AMC concentration",    tone: "rose" },
  CATEGORY_CONCENTRATION_EXIT:{ label: "Cuts category concentration", tone: "rose" },
  OVERLAP_CONSOLIDATION:      { label: "Removes overlap",            tone: "amber" },
  REGULAR_DIRECT_DUPLICATE:   { label: "Switches to direct plan",    tone: "amber" },
  COST_LEAK_SWITCH_TO_DIRECT: { label: "Lowers expense ratio",       tone: "amber" },
  UNDERPERFORMER_REPLACEMENT: { label: "Replaces laggard",           tone: "rose" },
  recent_investment_lockout:  { label: "New investment — monitor",   tone: "slate" },
};

// V3 action.type → broad priority bucket. `priority` (1-5, lower = higher
// importance) is also factored in so a low-priority EXIT slips into
// Optimise rather than Critical.
const bucketFor = (action) => {
  const verb = (action.type || "").toUpperCase();
  const prio = action.priority ?? 5;
  if (verb === "EXIT"      && prio <= 2) return "critical";
  if (verb === "REDUCE"    && prio <= 2) return "critical";
  if (verb === "EXIT"      || verb === "REDUCE") return "optimise";
  if (verb === "SWITCH"    || verb === "REBALANCE") return "optimise";
  if (verb === "INCREASE_SIP" || verb === "ADD_MORE" || verb === "ADD") return "enhance";
  // Fallback — anything we don't recognise goes in optimise.
  return "optimise";
};

const BUCKET_META = {
  critical: { label: "Critical fixes",  sub: "Do these first",              tone: "rose",    Icon: AlertTriangle },
  optimise: { label: "Optimisations",   sub: "Portfolio-level improvements", tone: "amber",   Icon: Scale },
  enhance:  { label: "Enhancements",    sub: "Nice-to-have additions",       tone: "indigo",  Icon: Plus },
};

// Build impact badges per action. Each badge is a tiny pill ("+₹6L freed",
// "Cuts AMC concentration", "ST gain ₹31k") rendered next to the action
// title. Badges come from three sources:
//   - reason_codes: mapped via REASON_CODE_META
//   - amount: "Frees ₹X" (buy-side: "Deploys ₹X")
//   - tax_impact: only shown if material (> ₹1k)
const impactBadgesFor = (action) => {
  const out = [];
  const verb = (action.type || "").toUpperCase();

  // Amount badge
  if (action.amount) {
    const sign = (verb === "EXIT" || verb === "REDUCE") ? "Frees" : "Deploys";
    out.push({ tone: "slate", label: `${sign} ${fmtRs(action.amount)}` });
  }

  // Reason-code driven badges (primary signal).
  for (const code of (action.reason_codes || [])) {
    const meta = REASON_CODE_META[code];
    if (meta) out.push({ tone: meta.tone, label: meta.label });
  }

  // Confidence — only when non-default.
  if (action.confidence && action.confidence !== "MEDIUM") {
    out.push({
      tone: action.confidence === "HIGH" ? "emerald" : "slate",
      label: `${action.confidence} confidence`,
    });
  }

  // Tax impact — only if material.
  const ti = action.tax_impact;
  if (ti && ti.capital_gain && Math.abs(ti.capital_gain) >= 1000) {
    const isShort = !ti.is_long_term;
    out.push({
      tone: isShort ? "rose" : "slate",
      label: `${isShort ? "ST" : "LT"} gain ${fmtRs(Math.abs(ti.capital_gain))}`,
    });
  }

  return out;
};

// ── Score ring (SVG) ──────────────────────────────────────────────────
const ScoreRing = ({ value, tone, testId }) => {
  const t = TONE[tone] || TONE.slate;
  const v = value == null ? 0 : Math.max(0, Math.min(100, Math.round(value)));
  const C = 2 * Math.PI * 40;
  const off = C * (1 - v / 100);
  return (
    <div className="relative w-32 h-32 flex-shrink-0" data-testid={testId}>
      <svg viewBox="0 0 100 100" className="w-full h-full -rotate-90">
        <circle cx="50" cy="50" r="40" strokeWidth="8" stroke="currentColor" className="text-slate-100 dark:text-slate-800" fill="none" />
        <circle
          cx="50" cy="50" r="40" strokeWidth="8" stroke="currentColor"
          className={`${t.ring} transition-all`}
          fill="none" strokeLinecap="round"
          strokeDasharray={C} strokeDashoffset={value == null ? C : off}
        />
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center">
        {value == null ? (
          <span className="text-xs text-slate-400 italic">Calculating…</span>
        ) : (
          <>
            <span className={`text-3xl font-bold ${t.text} tabular-nums leading-none`}>{v}</span>
            <span className="text-[10px] uppercase tracking-wider text-slate-400 mt-1">/ 100</span>
          </>
        )}
      </div>
    </div>
  );
};

// ── Component bar ─────────────────────────────────────────────────────
const ComponentBar = ({ label, value, tone, testId }) => {
  const t = TONE[tone] || TONE.slate;
  const v = value == null ? 0 : Math.max(0, Math.min(100, Math.round(value)));
  return (
    <div data-testid={testId}>
      <div className="flex items-baseline justify-between mb-1">
        <span className="text-xs font-medium text-slate-600 dark:text-slate-300">{label}</span>
        <span className={`text-xs font-bold tabular-nums ${t.text}`}>
          {value == null ? "—" : v}
        </span>
      </div>
      <div className="h-1.5 rounded-full bg-slate-100 dark:bg-slate-800 overflow-hidden relative">
        <div className={`h-full rounded-full transition-all ${t.bar}`} style={{ width: `${v}%` }} />
      </div>
    </div>
  );
};

// ── GoalsRollup — consolidated view for Client 360 ───────────────────
// Same shape as the retail /goals page but compact: stats strip + per-goal
// progress rows. Re-renders on every goals[] change (add / edit / delete).
const GoalsRollup = ({ goals }) => {
  const rollup = useMemo(() => {
    const total_target = goals.reduce((s, g) => s + (g.target_amount_rs || 0), 0);
    const total_sip    = goals.reduce((s, g) => s + (g.monthly_sip_rs || 0), 0);
    const with_track   = goals.filter((g) => g.on_track_pct != null);
    const wOnTrack = with_track.length
      ? with_track.reduce((s, g) => s + (g.on_track_pct * (g.target_amount_rs || 1)), 0) /
        Math.max(1, with_track.reduce((s, g) => s + (g.target_amount_rs || 1), 0))
      : null;
    const minH = Math.min(Infinity, ...goals.map((g) => g.horizon_years || Infinity));
    const maxH = Math.max(0, ...goals.map((g) => g.horizon_years || 0));
    return {
      total_target, total_sip, wOnTrack,
      minH: minH === Infinity ? 0 : minH, maxH,
      onTrack: goals.filter((g) => g.on_track_pct != null && g.on_track_pct >= 85).length,
      atRisk:  goals.filter((g) => g.on_track_pct != null && g.on_track_pct < 60).length,
    };
  }, [goals]);

  const tone = healthTone(rollup.wOnTrack);

  return (
    <div data-testid="client360-goals-rollup">
      {/* Summary strip */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 pb-4 border-b border-slate-100 dark:border-slate-800">
        <div data-testid="rollup-target">
          <div className="text-[9px] uppercase tracking-wider font-semibold text-slate-400">Combined target</div>
          <div className="text-lg font-bold text-slate-800 dark:text-slate-100 tabular-nums mt-0.5">
            {fmtRs(rollup.total_target)}
          </div>
        </div>
        <div data-testid="rollup-sip">
          <div className="text-[9px] uppercase tracking-wider font-semibold text-slate-400">Total SIP</div>
          <div className="text-lg font-bold text-slate-800 dark:text-slate-100 tabular-nums mt-0.5">
            {fmtRs(rollup.total_sip)}/mo
          </div>
        </div>
        <div data-testid="rollup-horizon">
          <div className="text-[9px] uppercase tracking-wider font-semibold text-slate-400">Horizon</div>
          <div className="text-lg font-bold text-slate-800 dark:text-slate-100 mt-0.5">
            {rollup.minH === rollup.maxH ? `${rollup.maxH}y` : `${rollup.minH}–${rollup.maxH}y`}
          </div>
        </div>
        <div data-testid="rollup-on-track">
          <div className="text-[9px] uppercase tracking-wider font-semibold text-slate-400">Overall</div>
          <div className={`text-lg font-bold ${TONE[tone].text} tabular-nums mt-0.5`}>
            {rollup.wOnTrack != null ? `${Math.round(rollup.wOnTrack)}%` : "Simulate"}
          </div>
          <div className="text-[9px] text-slate-500">
            {rollup.onTrack} on track · {rollup.atRisk} at risk
          </div>
        </div>
      </div>

      {/* Per-goal rows */}
      <div className="mt-3 space-y-2">
        {goals.map((g) => {
          const pct = g.on_track_pct != null ? Math.min(100, Math.max(0, g.on_track_pct)) : 0;
          const gTone = g.on_track_pct == null ? "slate" : g.on_track_pct >= 85 ? "emerald" : g.on_track_pct >= 60 ? "amber" : "rose";
          return (
            <div
              key={g.goal_id}
              data-testid={`rollup-goal-row-${g.goal_id}`}
              className="flex items-center gap-3"
            >
              <div className="text-xs font-semibold text-slate-800 dark:text-slate-100 w-32 truncate flex-shrink-0">
                {g.goal_name || "Untitled"}
              </div>
              <div className="hidden sm:block text-[10px] text-slate-500 w-16 flex-shrink-0 capitalize">
                {g.goal_type}
              </div>
              <div className="flex-1 h-1.5 rounded-full bg-slate-100 dark:bg-slate-800 overflow-hidden">
                <div
                  className={`h-full rounded-full ${TONE[gTone].bar}`}
                  style={{ width: `${pct}%` }}
                />
              </div>
              <div className={`text-xs font-bold tabular-nums w-12 text-right ${TONE[gTone].text}`}>
                {g.on_track_pct != null ? `${Math.round(g.on_track_pct)}%` : "—"}
              </div>
              <div className="hidden md:block text-[11px] text-slate-500 tabular-nums w-16 text-right flex-shrink-0">
                {g.horizon_years}y
              </div>
              <div className="text-[11px] font-semibold text-slate-700 dark:text-slate-200 tabular-nums w-20 text-right flex-shrink-0">
                {fmtRs(g.monthly_sip_rs)}/mo
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
};

export default function ClientSnapshot({ activeProfile, setActiveTab, onRefresh }) {
  const [loading, setLoading] = useState(true);
  const [health, setHealth] = useState(null);
  const [goals, setGoals] = useState([]);
  const [activePlan, setActivePlan] = useState(null);
  const [actions, setActions] = useState([]);
  const [updatingActionId, setUpdatingActionId] = useState(null);
  const [bulkUpdating, setBulkUpdating] = useState(false);
  const [collapsedBuckets, setCollapsedBuckets] = useState({ enhance: true }); // enhance starts collapsed
  const [trend, setTrend] = useState(null);
  const [tax, setTax] = useState(null);
  const [notes, setNotes] = useState({
    note: "", sip_amount_rs: "", sip_frequency: "monthly",
    next_sip_due: "", preferred_channel: "",
  });
  const [notesSaved, setNotesSaved] = useState(null);
  const [notesDirty, setNotesDirty] = useState(false);
  const [savingNotes, setSavingNotes] = useState(false);
  const [shareOpen, setShareOpen] = useState(false);
  const [copilotOpen, setCopilotOpen] = useState(false);
  const [inviteOpen, setInviteOpen] = useState(false);

  const profileId = activeProfile?.profile_id;

  const fetchAll = useCallback(async () => {
    if (!profileId) return;
    setLoading(true);
    try {
      const [hRes, gRes, pRes, tRes, nRes, xRes] = await Promise.all([
        axios.get(`${API}/insights/analysis`,    { withCredentials: true }).catch(() => null),
        axios.get(`${API}/goals`,                { withCredentials: true }).catch(() => null),
        axios.get(`${API}/plans/active`,         { withCredentials: true }).catch(() => null),
        axios.get(`${API}/mfd/profiles/${profileId}/portfolio-trend`, { withCredentials: true }).catch(() => null),
        axios.get(`${API}/mfd/profiles/${profileId}/notes`,           { withCredentials: true }).catch(() => null),
        axios.get(`${API}/mfd/profiles/${profileId}/tax-summary`,     { withCredentials: true }).catch(() => null),
      ]);
      setHealth(hRes?.data?.portfolio_health || null);
      setGoals(gRes?.data?.goals || gRes?.data || []);
      const plan = pRes?.data?.plan || null;
      setActivePlan(plan);
      // Top 5 open actions from the V3 engine's active plan.
      // V3 action shape: { action_id, type: "EXIT"|"SWITCH"|..., asset_name,
      // reason_text, priority (1=highest), status: "PENDING"|"COMPLETED"|"SKIPPED" }
      const list = (plan?.actions || [])
        .filter((a) => !["COMPLETED", "SKIPPED"].includes((a.status || "").toUpperCase()))
        .sort((a, b) => (a.priority || 99) - (b.priority || 99))
        .slice(0, 10);
      setActions(list);
      setTrend(tRes?.data || null);
      setTax(xRes?.data || null);
      if (nRes?.data) {
        setNotes({
          note: nRes.data.note || "",
          sip_amount_rs: nRes.data.sip_amount_rs ?? "",
          sip_frequency: nRes.data.sip_frequency || "monthly",
          next_sip_due: nRes.data.next_sip_due || "",
          preferred_channel: nRes.data.preferred_channel || "",
        });
        setNotesSaved(nRes.data.updated_at);
        setNotesDirty(false);
      }
    } finally {
      setLoading(false);
    }
  }, [profileId]);

  useEffect(() => { fetchAll(); }, [fetchAll]);

  const saveNotes = async () => {
    setSavingNotes(true);
    try {
      const payload = {
        note: notes.note || null,
        sip_amount_rs: notes.sip_amount_rs === "" ? null : Number(notes.sip_amount_rs),
        sip_frequency: notes.sip_frequency || null,
        next_sip_due: notes.next_sip_due || null,
        preferred_channel: notes.preferred_channel || null,
      };
      const res = await axios.put(
        `${API}/mfd/profiles/${profileId}/notes`,
        payload, { withCredentials: true },
      );
      setNotesSaved(res.data.updated_at);
      setNotesDirty(false);
      toast.success("Notes saved");
    } catch {
      toast.error("Could not save notes");
    } finally {
      setSavingNotes(false);
    }
  };

  // ── Plan / action management ────────────────────────────────────
  const updateActionStatus = async (action, newStatus) => {
    if (!activePlan) return;
    const actionId = action.action_id || action.id;
    setUpdatingActionId(actionId);
    try {
      const res = await axios.patch(
        `${API}/plans/${activePlan.plan_id || activePlan.id}/actions/${actionId}`,
        { status: newStatus },
        { withCredentials: true },
      );
      const updated = res.data?.plan || res.data;
      if (updated?.actions) {
        setActivePlan(updated);
        setActions(
          (updated.actions || [])
            .filter((a) => !["COMPLETED", "SKIPPED"].includes((a.status || "").toUpperCase()))
            .sort((a, b) => (a.priority || 99) - (b.priority || 99))
            .slice(0, 10),
        );
      } else {
        // Fallback — optimistic removal if the response shape is minimal.
        setActions((prev) => prev.filter((a) => (a.action_id || a.id) !== actionId));
      }
      toast.success(
        newStatus === "COMPLETED" ? "Marked as done" :
        newStatus === "SKIPPED"   ? "Dismissed" :
        "Updated",
      );
    } catch (e) {
      toast.error(e.response?.data?.detail || "Could not update action");
    } finally {
      setUpdatingActionId(null);
    }
  };

  const generatePlan = async () => {
    try {
      toast.loading("Generating action plan from V3 insights…", { id: "gen-plan" });
      await axios.post(`${API}/plans/generate`, {}, { withCredentials: true });
      await fetchAll();
      toast.success("Action plan ready", { id: "gen-plan" });
    } catch (e) {
      const detail = e.response?.data?.detail || e.message || "Could not generate plan";
      // Common case: SELF profile or new client with no portfolio yet —
      // give the MFD a precise next step instead of a generic toast.
      if (/no holdings/i.test(detail)) {
        toast.error(
          "No portfolio yet for this profile. Import a CAS PDF first via the client's profile page.",
          { id: "gen-plan", duration: 5000 },
        );
      } else {
        toast.error(detail, { id: "gen-plan" });
      }
    }
  };

  // Bulk "Mark all done" within a priority bucket.
  const bulkMarkBucket = async (bucketKey, bucketActions) => {
    if (!activePlan || !bucketActions.length) return;
    if (!window.confirm(
      `Mark all ${bucketActions.length} "${BUCKET_META[bucketKey].label}" actions as done?`,
    )) return;
    setBulkUpdating(true);
    try {
      const planId = activePlan.plan_id || activePlan.id;
      let latest = null;
      for (const a of bucketActions) {
        const res = await axios.patch(
          `${API}/plans/${planId}/actions/${a.action_id || a.id}`,
          { status: "COMPLETED" },
          { withCredentials: true },
        );
        latest = res.data?.plan || res.data || latest;
      }
      if (latest?.actions) {
        setActivePlan(latest);
        setActions(
          (latest.actions || [])
            .filter((x) => !["COMPLETED", "SKIPPED"].includes((x.status || "").toUpperCase()))
            .sort((x, y) => (x.priority || 99) - (y.priority || 99))
            .slice(0, 10),
        );
      }
      toast.success(`${bucketActions.length} action${bucketActions.length === 1 ? "" : "s"} marked done`);
    } catch (e) {
      toast.error(e.response?.data?.detail || "Bulk update failed");
    } finally {
      setBulkUpdating(false);
    }
  };

  const toggleBucket = (key) =>
    setCollapsedBuckets((c) => ({ ...c, [key]: !c[key] }));

  // Group actions by bucket for the card render.
  const groupedActions = useMemo(() => {
    const g = { critical: [], optimise: [], enhance: [] };
    for (const a of actions) g[bucketFor(a)].push(a);
    return g;
  }, [actions]);

  const patchNote = (field, value) => {
    setNotes((n) => ({ ...n, [field]: value }));
    setNotesDirty(true);
  };

  // Derive a concise summary — prefer backend-written one if present.
  const client = activeProfile || {};
  const aumLive = trend?.current_rs || client.portfolio_value_rs || client.aum_rs;
  // Health score with a friendly fallback: when the V3 health endpoint
  // hasn't returned yet (or failed), but the AI summary on the profile
  // already carries the score (e.g., "Fair portfolio — overall Health
  // 64/100 (Grade B)"), parse it so the score ring stops saying
  // "Scoring…" forever. Avoids the dead-state we kept seeing on the
  // advisor's snapshot view.
  const _aiSummary = health?.summary || client.ai_summary || "";
  const _scoreFromSummary = (() => {
    const m = _aiSummary.match(/(\d{1,3})\s*\/\s*100/);
    if (!m) return null;
    const v = parseInt(m[1], 10);
    return v >= 0 && v <= 100 ? v : null;
  })();
  const _gradeFromSummary = (() => {
    const m = _aiSummary.match(/Grade\s+([A-F][+-]?)/i);
    return m ? m[1].toUpperCase() : null;
  })();
  const hs = health?.health_score ?? _scoreFromSummary;
  const hsTone = healthTone(hs);
  const hsT = TONE[hsTone];

  const trendTone = (() => {
    const pct = trend?.percent_change;
    if (pct == null) return "slate";
    return pct >= 10 ? "emerald" : pct >= 0 ? "amber" : "rose";
  })();

  const riskAlignment = (() => {
    const rc = (health?.components || {}).risk;
    if (!rc) return { label: "No data", tone: "slate" };
    if (rc.score >= 70) return { label: "Well within profile", tone: "emerald" };
    if (rc.score >= 50) return { label: "Mild mismatch", tone: "amber" };
    return { label: "Risk higher than profile", tone: "rose" };
  })();

  // Pass 2 derivations — insight layer.
  const topIssues = useMemo(() => computeTopIssues(health), [health]);
  const narrative = useMemo(
    () => buildCioNarrative({ health, actions, tax, trend }),
    [health, actions, tax, trend],
  );

  // Pass 3 — HNI derivations
  const wealthTier = useMemo(() => wealthTierFor(aumLive), [aumLive]);
  const totalShift = useMemo(() => grossActionValue(actions), [actions]);

  // Today's brief — concise bulleted summary at the top of the snapshot.
  // Each bullet is a decision the MFD can act on today. Bullets are
  // derived from action buckets + biggest top-issue, not from static copy.
  const brief = useMemo(() => {
    const bullets = [];
    const grouped = { critical: [], optimise: [], enhance: [] };
    for (const a of actions) grouped[bucketFor(a)].push(a);
    if (grouped.critical.length) {
      bullets.push({
        icon: AlertTriangle, tone: "rose",
        text: `Fix ${grouped.critical.length} critical action${grouped.critical.length === 1 ? "" : "s"}`,
      });
    }
    if (grouped.optimise.length) {
      bullets.push({
        icon: Scale, tone: "amber",
        text: `Review ${grouped.optimise.length} optimisation${grouped.optimise.length === 1 ? "" : "s"}`,
      });
    }
    if (grouped.enhance.length) {
      bullets.push({
        icon: Plus, tone: "indigo",
        text: `Consider ${grouped.enhance.length} enhancement${grouped.enhance.length === 1 ? "" : "s"}`,
      });
    }
    if (topIssues.issues.length && topIssues.projected != null && topIssues.totalDelta >= 3) {
      bullets.push({
        icon: Sparkles, tone: "emerald",
        text: `Fix top 3 issues → lifts health ${Math.round(health?.health_score || 0)} → ${topIssues.projected}`,
      });
    }
    if (!goals.length) {
      bullets.push({
        icon: Target, tone: "slate",
        text: "Capture goals to unlock SIP-gap analysis",
      });
    }
    return bullets.slice(0, 4);
  }, [actions, topIssues, goals, health]);

  // ── Share ────────────────────────────────────────────────────────
  // We build a plain-text summary the MFD can paste into WhatsApp or
  // email. Intentionally no raw link for now (there's no public share
  // link yet); if the user clicks "Copy link" we give them the advisor
  // dashboard URL so they can paste into a client portal we ship later.
  const shareText = (() => {
    const parts = [`Portfolio snapshot for ${client.name || "client"}:`];
    if (hs != null) parts.push(`• Health: ${Math.round(hs)}/100${health?.grade ? ` (Grade ${health.grade})` : ""}`);
    if (trend?.current_rs)    parts.push(`• Current value: ${fmtRs(trend.current_rs)}`);
    if (trend?.percent_change != null) parts.push(`• Return: ${trend.percent_change >= 0 ? "+" : ""}${trend.percent_change}%`);
    if (goals.length)         parts.push(`• Goals tracked: ${goals.length}`);
    if (actions.length)       parts.push(`• Open actions: ${actions.length}`);
    parts.push("\nShared via nivesh.ai");
    return parts.join("\n");
  })();

  const shareViaWhatsApp = () => {
    const url = `https://wa.me/?text=${encodeURIComponent(shareText)}`;
    window.open(url, "_blank");
    setShareOpen(false);
  };
  const shareViaEmail = () => {
    const subj = encodeURIComponent(`Your portfolio snapshot — ${client.name || ""}`);
    const body = encodeURIComponent(shareText);
    window.location.href = `mailto:?subject=${subj}&body=${body}`;
    setShareOpen(false);
  };
  const copyShareText = async () => {
    try {
      await navigator.clipboard.writeText(shareText);
      toast.success("Summary copied — paste it into your client's chat");
      setShareOpen(false);
    } catch {
      toast.error("Could not copy — your browser blocked clipboard access");
    }
  };

  return (
    <div className="space-y-5" data-testid="client-snapshot">
      {/* ── Header strip ──────────────────────────────────────────── */}
      <div className="flex items-start justify-between flex-wrap gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <LayoutDashboard className="w-5 h-5 text-indigo-600" />
            <h2 className="text-xl font-bold text-slate-800 dark:text-slate-100" data-testid="snapshot-client-name">
              {client.name}
            </h2>
            <Badge variant="outline" className="text-[10px]">Snapshot</Badge>
            {wealthTier.label && (
              <span
                data-testid="snapshot-wealth-tier"
                className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-bold border ${
                  wealthTier.key === "uhni"
                    ? "bg-gradient-to-r from-amber-100 to-yellow-100 border-amber-300 text-amber-900"
                  : wealthTier.key === "hni"
                    ? "bg-gradient-to-r from-indigo-100 to-violet-100 border-indigo-300 text-indigo-900 dark:from-indigo-900/40 dark:to-violet-900/40 dark:border-indigo-700 dark:text-indigo-100"
                    : "bg-slate-100 border-slate-200 text-slate-600"
                }`}
              >
                <Sparkles className="w-2.5 h-2.5" />
                {wealthTier.label}
              </span>
            )}
          </div>
          <p className="text-xs text-slate-500 mt-1">
            {fmtRs(aumLive)} AUM · Last review {fmtDaysAgo(client.last_reviewed_at)}
          </p>
        </div>
        <div className="flex items-center gap-2 relative">
          <ExportHoldingsButton
            profileId={profileId}
            variant="outline"
            size="sm"
            className="h-8 text-xs rounded-lg"
            label="Export"
            testId="snapshot-export-btn"
          />
          <Button
            variant="outline" size="sm"
            onClick={() => setShareOpen(!shareOpen)}
            data-testid="snapshot-share-btn"
            className="h-8 text-xs"
          >
            <Share2 className="w-3.5 h-3.5 mr-1" /> Share with client
          </Button>
          {shareOpen && (
            <div
              className="absolute right-0 top-10 z-30 w-64 bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-700 rounded-xl shadow-lg p-2"
              data-testid="snapshot-share-menu"
            >
              <button
                type="button" onClick={shareViaWhatsApp}
                className="w-full flex items-center gap-2 px-3 py-2 rounded-lg hover:bg-slate-50 dark:hover:bg-slate-800 text-left text-sm"
                data-testid="share-whatsapp"
              >
                <MessageSquare className="w-4 h-4 text-emerald-600" />
                Send via WhatsApp
              </button>
              <button
                type="button" onClick={shareViaEmail}
                className="w-full flex items-center gap-2 px-3 py-2 rounded-lg hover:bg-slate-50 dark:hover:bg-slate-800 text-left text-sm"
                data-testid="share-email"
              >
                <Mail className="w-4 h-4 text-blue-600" />
                Send via Email
              </button>
              <button
                type="button" onClick={copyShareText}
                className="w-full flex items-center gap-2 px-3 py-2 rounded-lg hover:bg-slate-50 dark:hover:bg-slate-800 text-left text-sm"
                data-testid="share-copy"
              >
                <Copy className="w-4 h-4 text-slate-500" />
                Copy summary text
              </button>
            </div>
          )}
          <Button
            variant="outline" size="sm"
            onClick={() => setInviteOpen(true)}
            data-testid="snapshot-invite-client"
            className="h-8 text-xs"
          >
            <Link2 className="w-3.5 h-3.5 mr-1" /> Invite for CAS
          </Button>
          <Button
            variant="default" size="sm"
            onClick={() => setCopilotOpen(true)}
            data-testid="snapshot-open-copilot"
            className="h-8 text-xs bg-gradient-to-r from-indigo-600 to-violet-600 hover:from-indigo-700 hover:to-violet-700 text-white border-0"
          >
            <Bot className="w-3.5 h-3.5 mr-1" /> Copilot
          </Button>
          <Button
            variant="outline" size="sm"
            onClick={() => setActiveTab("portfolio")}
            data-testid="snapshot-open-portfolio"
            className="h-8 text-xs"
          >
            Open portfolio <ArrowRight className="w-3.5 h-3.5 ml-1" />
          </Button>
        </div>
      </div>

      {/* ── Time Machine strip ─────────────────────────────────────
          Sits directly below the header so the MFD sees "what
          changed" as the first thing after the client's name.      */}
      <TimeMachineStrip />

      {/* ── CAS History Time-Machine ────────────────────────────────
          Month-by-month portfolio snapshots from each CAS upload.
          Shows performance chart, SIP trend bars, and top transactions
          for the selected date range. MFD can "activate" any month
          to rewind Client 360 to that snapshot.                       */}
      <div data-testid="cas-history-section">
        <div className="flex items-center gap-2 mb-2 px-0.5">
          <span className="text-xs font-bold text-slate-400 uppercase tracking-wider">
            CAS Upload History &amp; Trends
          </span>
        </div>
        <CasTimeMachine
          profileId={profileId}
          onSnapshotActivated={() => {
            // Re-load this page's data when MFD activates a historical snapshot
            window.location.reload();
          }}
        />
      </div>

      {/* ── Today's brief banner ───────────────────────────────────
          Bullet list of "what to do today" for this client. Renders only
          when there's something actionable — otherwise stays silent so
          the MFD doesn't see empty cheerleader copy.                  */}
      {!loading && brief.length > 0 && (
        <Card
          className="p-4 border-indigo-200 dark:border-indigo-800 bg-gradient-to-r from-indigo-50/80 via-white to-white dark:from-indigo-900/20 dark:via-slate-900 dark:to-slate-900"
          data-testid="snapshot-daily-brief"
        >
          <div className="flex items-start gap-3">
            <div className="w-9 h-9 rounded-xl bg-indigo-600 text-white flex items-center justify-center flex-shrink-0">
              <Sparkles className="w-4 h-4" />
            </div>
            <div className="flex-1 min-w-0">
              <div className="text-[10px] uppercase tracking-wider font-bold text-indigo-600">
                Today's brief for {client.name}
              </div>
              <ul className="mt-1.5 grid grid-cols-1 md:grid-cols-2 gap-x-5 gap-y-1">
                {brief.map((b, i) => {
                  const bt = TONE[b.tone] || TONE.slate;
                  return (
                    <li
                      key={i}
                      data-testid={`brief-item-${i}`}
                      className="flex items-start gap-1.5 text-sm text-slate-700 dark:text-slate-200"
                    >
                      <b.icon className={`w-3.5 h-3.5 mt-0.5 flex-shrink-0 ${bt.text}`} />
                      <span>{b.text}</span>
                    </li>
                  );
                })}
              </ul>
            </div>
          </div>
        </Card>
      )}

      {/* ── Portfolio trend strip ─────────────────────────────────── */}
      {trend && trend.invested_rs > 0 && (
        <Card className="p-4" data-testid="snapshot-trend-strip">
          <div className="flex items-center gap-5 flex-wrap">
            <div className="flex items-center gap-2 text-slate-500">
              <div className="w-9 h-9 rounded-xl bg-slate-100 dark:bg-slate-800 flex items-center justify-center">
                <Wallet className="w-4 h-4 text-slate-500" />
              </div>
              <div>
                <div className="text-[10px] uppercase tracking-wider font-semibold text-slate-400">Invested</div>
                <div className="text-base font-bold text-slate-700 dark:text-slate-200 tabular-nums">
                  {fmtRs(trend.invested_rs)}
                </div>
              </div>
            </div>
            <div className="h-8 w-px bg-slate-200 dark:bg-slate-700" />
            <div className="flex items-center gap-2">
              <div className={`w-9 h-9 rounded-xl ${TONE[trendTone].bgSoft} flex items-center justify-center`}>
                <IndianRupee className={`w-4 h-4 ${TONE[trendTone].text}`} />
              </div>
              <div>
                <div className="text-[10px] uppercase tracking-wider font-semibold text-slate-400">Current value</div>
                <div className={`text-base font-bold tabular-nums ${TONE[trendTone].text}`}>
                  {fmtRs(trend.current_rs)}
                </div>
              </div>
            </div>
            <div className="h-8 w-px bg-slate-200 dark:bg-slate-700" />
            <div className="flex items-center gap-2">
              <div className={`w-9 h-9 rounded-xl ${TONE[trendTone].bgSoft} flex items-center justify-center`}>
                {trend.percent_change >= 0
                  ? <TrendingUp className={`w-4 h-4 ${TONE[trendTone].text}`} />
                  : <TrendingDown className={`w-4 h-4 ${TONE[trendTone].text}`} />}
              </div>
              <div>
                <div className="text-[10px] uppercase tracking-wider font-semibold text-slate-400">Since buy</div>
                <div className={`text-base font-bold tabular-nums ${TONE[trendTone].text}`}>
                  {trend.percent_change != null && `${trend.percent_change >= 0 ? "+" : ""}${trend.percent_change}%`}
                  <span className="text-xs font-medium ml-2">({fmtRs(trend.absolute_change_rs)})</span>
                </div>
              </div>
            </div>
            <div className="flex-1" />
            <div className="text-[10px] text-slate-400 italic hidden md:inline-flex items-center gap-1">
              <Activity className="w-3 h-3" /> 30-day sparkline coming soon
            </div>
          </div>
        </Card>
      )}

      {loading && (
        <div className="py-12 text-center text-xs text-slate-500">
          <Activity className="w-4 h-4 mx-auto animate-pulse mb-2" />
          Loading client snapshot…
        </div>
      )}

      {!loading && (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
          {/* ── Health + breakdown card (left, spans 2) ──────────── */}
          <Card className="lg:col-span-2 p-5" data-testid="snapshot-health-card">
            <div className="flex items-start gap-6 flex-wrap">
              <ScoreRing value={hs} tone={hsTone} testId="snapshot-health-ring" />
              <div className="flex-1 min-w-[220px]">
                <div className="text-[10px] uppercase tracking-wider font-bold text-slate-500 inline-flex items-center">
                  Portfolio Health
                  <HealthScoreInfo testId="snapshot-health-info-btn" />
                </div>
                <div className={`text-lg font-semibold mt-1 ${hsT.text}`} data-testid="snapshot-grade-label">
                  {hs != null && (health?.grade || _gradeFromSummary)
                    ? `Grade ${health?.grade || _gradeFromSummary} · ${Math.round(hs)}/100`
                    : hs != null
                      ? `${Math.round(hs)}/100`
                      : "Scoring…"}
                </div>
                <p className="text-sm text-slate-600 dark:text-slate-300 mt-2 leading-relaxed" data-testid="snapshot-health-summary">
                  {health?.summary || client.ai_summary || "No summary available yet."}
                </p>
                {/* riskAlignment stays below (same line) */}
                <div className="mt-4 inline-flex items-center gap-1.5 text-xs font-medium" data-testid="snapshot-risk-alignment">
                  <ShieldCheck className={`w-3.5 h-3.5 ${TONE[riskAlignment.tone].text}`} />
                  <span className={TONE[riskAlignment.tone].text}>
                    Risk vs profile: {riskAlignment.label}
                  </span>
                </div>
              </div>
            </div>

            {/* AI narrative — deterministic for now */}
            {narrative && (
              <div
                data-testid="snapshot-ai-narrative"
                className="mt-5 p-3 rounded-lg bg-slate-50 dark:bg-slate-800/50 border-l-4 border-indigo-400"
              >
                <div className="flex items-start gap-2">
                  <Sparkles className="w-3.5 h-3.5 text-indigo-600 mt-0.5 flex-shrink-0" />
                  <p className="text-[12px] text-slate-700 dark:text-slate-200 leading-relaxed">
                    {narrative}
                  </p>
                </div>
              </div>
            )}

            {/* Top issues + projected health */}
            {topIssues.issues.length > 0 && (
              <div
                data-testid="snapshot-top-issues"
                className="mt-4"
              >
                <div className="flex items-center justify-between mb-2">
                  <div className="text-[10px] uppercase tracking-wider font-bold text-rose-600 flex items-center gap-1.5">
                    <AlertTriangle className="w-3 h-3" /> Top issues hurting health
                  </div>
                  {topIssues.projected != null && hs != null && topIssues.totalDelta >= 3 && (
                    <div
                      data-testid="snapshot-projected-score"
                      className="text-[11px] font-bold text-emerald-700 dark:text-emerald-400 flex items-center gap-1"
                    >
                      <TrendingUp className="w-3 h-3" />
                      Fix all → {Math.round(hs)} → {topIssues.projected}
                    </div>
                  )}
                </div>
                <ul className="space-y-1.5">
                  {topIssues.issues.map((iss, i) => (
                    <li
                      key={i}
                      data-testid={`top-issue-${i}`}
                      className="flex items-start gap-2 text-xs rounded-md bg-rose-50/60 dark:bg-rose-900/20 border border-rose-100 dark:border-rose-800/50 p-2"
                    >
                      <span className="flex-shrink-0 w-4 h-4 rounded-full bg-rose-600 text-white text-[9px] font-bold flex items-center justify-center">
                        {i + 1}
                      </span>
                      <div className="flex-1 min-w-0">
                        <div className="font-semibold text-slate-800 dark:text-slate-100 truncate">
                          {iss.label}
                        </div>
                        <div className="text-[10px] text-slate-500 line-clamp-2">{iss.detail}</div>
                      </div>
                      <span
                        className="flex-shrink-0 text-[10px] font-bold text-emerald-700 dark:text-emerald-400 tabular-nums"
                        title="Projected health improvement if fixed"
                      >
                        +{iss.impact.toFixed(1)}
                      </span>
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {/* Component breakdown — component keys come from the backend
                response (diversification / risk / cost / performance) so we
                iterate the actual object rather than a hard-coded list. */}
            {health?.components && (
              <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mt-6 pt-5 border-t border-slate-100 dark:border-slate-800">
                {Object.entries(health.components).map(([k, c]) => {
                  const tone = c ? healthTone(c.score) : "slate";
                  const label = (c?.name || c?.label || k)
                    .replace(/_/g, " ")
                    .replace(/\b\w/g, (s) => s.toUpperCase());
                  return (
                    <ComponentBar
                      key={k}
                      label={label}
                      value={c?.score}
                      tone={tone}
                      testId={`snapshot-component-${k}`}
                    />
                  );
                })}
              </div>
            )}
          </Card>

          {/* ── V3 engine actions card (right) ───────────────────── */}
          <Card className="p-5" data-testid="snapshot-actions-card">
            <div className="flex items-center justify-between gap-2 mb-4">
              <div className="flex items-center gap-2 min-w-0">
                <div className="w-8 h-8 rounded-xl bg-indigo-100 dark:bg-indigo-900/40 flex items-center justify-center">
                  <Sparkles className="w-4 h-4 text-indigo-600" />
                </div>
                <div className="min-w-0">
                  <div className="text-sm font-bold text-slate-800 dark:text-slate-100">
                    Recommended actions
                  </div>
                  <div className="text-[11px] text-slate-500 truncate">
                    {activePlan
                      ? `V3 plan · ${actions.length} open`
                      : "No active plan yet"}
                  </div>
                </div>
              </div>
              {!activePlan && (
                <Button
                  size="sm"
                  onClick={generatePlan}
                  className="h-8 text-xs bg-indigo-600 hover:bg-indigo-700"
                  data-testid="snapshot-generate-plan"
                >
                  <Sparkles className="w-3.5 h-3.5 mr-1" /> Generate
                </Button>
              )}
            </div>

            {!activePlan ? (
              <div className="text-center py-6 text-xs text-slate-500" data-testid="snapshot-no-plan">
                <Sparkles className="w-5 h-5 mx-auto mb-1.5 opacity-40" />
                Tap <strong>Generate</strong> to create an action plan from the V3 engine.
              </div>
            ) : actions.length === 0 ? (
              <div className="text-center py-6 text-xs text-slate-500" data-testid="snapshot-actions-empty">
                <CheckCircle2 className="w-5 h-5 mx-auto mb-1.5 text-emerald-500" />
                All recommended actions completed. Nice work.
              </div>
            ) : (
              <div className="space-y-3" data-testid="snapshot-action-groups">
                {/* Execute All CTA — headline ₹ value, routes to Plan Board. */}
                {totalShift > 0 && (
                  <button
                    type="button"
                    onClick={() => setActiveTab("plan_board")}
                    data-testid="snapshot-execute-all"
                    className="w-full flex items-center justify-between rounded-lg bg-gradient-to-r from-indigo-600 to-violet-600 text-white px-3 py-2 hover:from-indigo-700 hover:to-violet-700 transition-colors shadow-sm"
                  >
                    <div className="flex items-center gap-2 text-left">
                      <Zap className="w-4 h-4" />
                      <div>
                        <div className="text-xs font-bold">Execute all</div>
                        <div className="text-[10px] opacity-90">
                          Rebalance portfolio — {fmtRs(totalShift)} in shifts
                        </div>
                      </div>
                    </div>
                    <ArrowRight className="w-4 h-4" />
                  </button>
                )}
                {["critical", "optimise", "enhance"].map((bucketKey) => {
                  const bucketActions = groupedActions[bucketKey];
                  if (!bucketActions.length) return null;
                  const meta = BUCKET_META[bucketKey];
                  const t = TONE[meta.tone];
                  const collapsed = collapsedBuckets[bucketKey];
                  return (
                    <div
                      key={bucketKey}
                      data-testid={`bucket-${bucketKey}`}
                      className={`rounded-lg border ${t.border}`}
                    >
                      {/* Bucket header */}
                      <div className={`flex items-center justify-between px-3 py-2 ${t.bgSoft}`}>
                        <button
                          type="button"
                          onClick={() => toggleBucket(bucketKey)}
                          data-testid={`bucket-toggle-${bucketKey}`}
                          className="flex items-center gap-2 flex-1 text-left"
                        >
                          {collapsed
                            ? <ChevronRight className={`w-3.5 h-3.5 ${t.text}`} />
                            : <ChevronDown  className={`w-3.5 h-3.5 ${t.text}`} />}
                          <meta.Icon className={`w-3.5 h-3.5 ${t.text}`} />
                          <span className={`text-xs font-bold ${t.text}`}>{meta.label}</span>
                          <span className={`text-[10px] ${t.text} opacity-80`}>· {bucketActions.length}</span>
                          <span className="text-[10px] text-slate-500 ml-2 truncate">{meta.sub}</span>
                        </button>
                        {bucketActions.length > 1 && (
                          <Button
                            size="sm" variant="ghost"
                            onClick={() => bulkMarkBucket(bucketKey, bucketActions)}
                            disabled={bulkUpdating}
                            data-testid={`bucket-bulk-done-${bucketKey}`}
                            className={`h-6 text-[10px] ${t.text} hover:opacity-80`}
                          >
                            Mark all done
                          </Button>
                        )}
                      </div>

                      {/* Actions in this bucket */}
                      {!collapsed && (
                        <ul className="divide-y divide-slate-100 dark:divide-slate-800">
                          {bucketActions.map((a, i) => {
                            const verb = (a.type || a.action_type || a.action || "").toLowerCase();
                            const view = ACTION_VIEW[verb] || { label: a.type || "Review", Icon: Eye, tone: meta.tone };
                            const actionId = a.action_id || a.id;
                            const isUpdating = actionId === updatingActionId || bulkUpdating;
                            const assetName = a.asset_name || a.fund_name || a.scheme_name;
                            const reason = a.reason_text || a.reason || a.rationale || a.description;
                            const badges = impactBadgesFor(a);
                            return (
                              <li
                                key={actionId || i}
                                data-testid={`snapshot-action-${bucketKey}-${i}`}
                                className="p-3"
                              >
                                <div className="flex items-start gap-2.5">
                                  <view.Icon className={`w-4 h-4 ${t.text} flex-shrink-0 mt-0.5`} />
                                  <div className="min-w-0 flex-1">
                                    <div className="text-sm font-semibold text-slate-800 dark:text-slate-100 line-clamp-2">
                                      {view.label}{assetName ? ` · ${assetName}` : ""}
                                    </div>
                                    {/* Impact badges — tone-mixed, concise */}
                                    {badges.length > 0 && (
                                      <div className="flex flex-wrap gap-1 mt-1.5" data-testid={`action-badges-${bucketKey}-${i}`}>
                                        {badges.map((b, bi) => {
                                          const bt = TONE[b.tone] || TONE.slate;
                                          return (
                                            <span
                                              key={bi}
                                              className={`inline-flex items-center rounded-full px-1.5 py-0.5 text-[10px] font-semibold border ${bt.bgSoft} ${bt.border} ${bt.text}`}
                                            >
                                              {b.label}
                                            </span>
                                          );
                                        })}
                                      </div>
                                    )}
                                    {reason && (
                                      <div className="text-[11px] text-slate-500 mt-1 line-clamp-2">
                                        {reason}
                                      </div>
                                    )}
                                  </div>
                                </div>
                                <div className="flex items-center justify-end gap-1 mt-2">
                                  <Button
                                    size="sm" variant="ghost"
                                    disabled={isUpdating}
                                    onClick={() => updateActionStatus(a, "COMPLETED")}
                                    className="h-6 text-[10px] text-emerald-700 hover:text-emerald-900 hover:bg-emerald-50 dark:hover:bg-emerald-900/30"
                                    data-testid={`snapshot-action-done-${bucketKey}-${i}`}
                                  >
                                    <CheckCircle2 className="w-3 h-3 mr-1" /> Mark done
                                  </Button>
                                  <Button
                                    size="sm" variant="ghost"
                                    disabled={isUpdating}
                                    onClick={() => updateActionStatus(a, "SKIPPED")}
                                    className="h-6 text-[10px] text-slate-500 hover:text-rose-600 hover:bg-rose-50 dark:hover:bg-rose-900/20"
                                    data-testid={`snapshot-action-skip-${bucketKey}-${i}`}
                                  >
                                    Dismiss
                                  </Button>
                                </div>
                              </li>
                            );
                          })}
                        </ul>
                      )}
                    </div>
                  );
                })}
              </div>
            )}

            <Button
              size="sm" variant="outline"
              onClick={() => setActiveTab("plan_board")}
              data-testid="snapshot-open-plan-board"
              className="w-full mt-4 h-8 text-xs"
            >
              Open full plan board <ArrowRight className="w-3.5 h-3.5 ml-1" />
            </Button>
          </Card>

          {/* ── Goals rollup (consolidated view, updates live) ───── */}
          <Card className="lg:col-span-3 p-5" data-testid="snapshot-goals-card">
            <div className="flex items-center justify-between mb-4 flex-wrap gap-2">
              <div className="flex items-center gap-2">
                <div className="w-8 h-8 rounded-xl bg-emerald-100 dark:bg-emerald-900/40 flex items-center justify-center">
                  <Target className="w-4 h-4 text-emerald-600" />
                </div>
                <div>
                  <div className="text-sm font-bold text-slate-800 dark:text-slate-100">Goal rollup</div>
                  <div className="text-[11px] text-slate-500">
                    {goals.length} of {MAX_GOALS_CLIENT} goals tracked
                  </div>
                </div>
              </div>
              <Button
                size="sm" variant="outline"
                onClick={() => setActiveTab("goals")}
                data-testid="snapshot-open-goals"
                className="h-8 text-xs"
              >
                Manage goals <ArrowRight className="w-3.5 h-3.5 ml-1" />
              </Button>
            </div>

            {goals.length === 0 ? (
              <div className="text-center py-8 text-xs text-slate-500" data-testid="snapshot-goals-empty">
                <Target className="w-6 h-6 mx-auto mb-1.5 opacity-40" />
                No goals captured yet. Add retirement / education / wealth goals to see progress here.
                <div className="mt-3">
                  <Button size="sm" onClick={() => setActiveTab("goals")}>
                    <Target className="w-3 h-3 mr-1" /> Add first goal
                  </Button>
                </div>
              </div>
            ) : (
              <GoalsRollup goals={goals} />
            )}
          </Card>

          {/* ── Tax layer (HNI) + Allocation drift ───────────────── */}
          {tax && (tax.total_invested_rs || 0) > 0 && (
            <Card className="lg:col-span-2 p-5" data-testid="snapshot-tax-card">
              <div className="flex items-center gap-2 mb-4">
                <div className="w-8 h-8 rounded-xl bg-violet-100 dark:bg-violet-900/40 flex items-center justify-center">
                  <IndianRupee className="w-4 h-4 text-violet-600" />
                </div>
                <div>
                  <div className="text-sm font-bold text-slate-800 dark:text-slate-100">
                    Tax snapshot
                  </div>
                  <div className="text-[11px] text-slate-500">
                    Unrealized gain / loss split — helps time the rebalance
                  </div>
                </div>
              </div>

              {/* Top row of big numbers */}
              <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                <div data-testid="tax-total-unrealized">
                  <div className="text-[9px] uppercase tracking-wider font-semibold text-slate-500">Unrealized gain</div>
                  <div className={`text-lg font-bold tabular-nums mt-0.5 ${tax.total_unrealized_rs >= 0 ? "text-emerald-600" : "text-rose-600"}`}>
                    {tax.total_unrealized_rs >= 0 ? "+" : "-"}{fmtRs(Math.abs(tax.total_unrealized_rs))}
                  </div>
                  <div className="text-[10px] text-slate-500">across all holdings</div>
                </div>
                <div data-testid="tax-stcg">
                  <div className="text-[9px] uppercase tracking-wider font-semibold text-slate-500">STCG exposure</div>
                  <div className="text-lg font-bold tabular-nums text-amber-600 mt-0.5">
                    {fmtRs(Math.max(0, tax.stcg_rs))}
                  </div>
                  <div className="text-[10px] text-slate-500">{tax.stcg_count} position{tax.stcg_count === 1 ? "" : "s"}</div>
                </div>
                <div data-testid="tax-ltcg">
                  <div className="text-[9px] uppercase tracking-wider font-semibold text-slate-500">LTCG exposure</div>
                  <div className="text-lg font-bold tabular-nums text-emerald-600 mt-0.5">
                    {fmtRs(Math.max(0, tax.ltcg_rs))}
                  </div>
                  <div className="text-[10px] text-slate-500">{tax.ltcg_count} position{tax.ltcg_count === 1 ? "" : "s"}</div>
                </div>
                <div data-testid="tax-est">
                  <div className="text-[9px] uppercase tracking-wider font-semibold text-slate-500">If realised today</div>
                  <div className="text-lg font-bold tabular-nums text-rose-600 mt-0.5">
                    {fmtRs(tax.est_tax_if_realized_rs)}
                  </div>
                  <div className="text-[10px] text-slate-500">indicative tax bill</div>
                </div>
              </div>

              {/* Coverage + undated caveat */}
              {tax.undated_count > 0 && (
                <div
                  data-testid="tax-coverage-note"
                  className="mt-3 flex items-start gap-2 p-2 rounded-md bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-800"
                >
                  <AlertTriangle className="w-3.5 h-3.5 text-amber-600 flex-shrink-0 mt-0.5" />
                  <div className="text-[11px] text-amber-800 dark:text-amber-300">
                    {tax.undated_count} holding{tax.undated_count === 1 ? " is" : "s are"} missing buy date
                    ({fmtRs(tax.undated_gain_rs)} gain not categorised). Re-import the latest CAS to split them into STCG / LTCG.
                  </div>
                </div>
              )}

              {/* Biggest positions by gain */}
              {tax.biggest_positions?.length > 0 && (
                <div className="mt-4 pt-4 border-t border-slate-100 dark:border-slate-800">
                  <div className="text-[10px] uppercase tracking-wider font-bold text-slate-500 mb-2">
                    Biggest positions by unrealized gain
                  </div>
                  <ul className="space-y-1.5">
                    {tax.biggest_positions.slice(0, 5).map((p, i) => (
                      <li
                        key={i}
                        data-testid={`tax-biggest-${i}`}
                        className="flex items-center gap-2 text-xs"
                      >
                        <span className={`flex-shrink-0 inline-flex items-center rounded-full px-1.5 py-0.5 text-[9px] font-bold uppercase ${
                          p.bucket === "ltcg" ? "bg-emerald-100 text-emerald-700" :
                          p.bucket === "stcg" ? "bg-amber-100 text-amber-700" :
                          "bg-slate-100 text-slate-500"
                        }`}>
                          {p.bucket}
                        </span>
                        <span className="flex-1 text-slate-700 dark:text-slate-200 truncate">
                          {p.name}
                        </span>
                        <span className={`font-bold tabular-nums flex-shrink-0 ${p.gain >= 0 ? "text-emerald-600" : "text-rose-600"}`}>
                          {p.gain >= 0 ? "+" : "-"}{fmtRs(Math.abs(p.gain))}
                        </span>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </Card>
          )}

          {/* ── Allocation drift (HNI) ───────────────────────────── */}
          {(() => {
            const drift = allocationDriftFor(health);
            if (!drift || !drift.current) return null;
            const buckets = Object.keys({ ...drift.current, ...(drift.target || {}) });
            return (
              <Card className="p-5" data-testid="snapshot-allocation-drift">
                <div className="flex items-center gap-2 mb-4">
                  <div className="w-8 h-8 rounded-xl bg-amber-100 dark:bg-amber-900/40 flex items-center justify-center">
                    <PieChart className="w-4 h-4 text-amber-600" />
                  </div>
                  <div>
                    <div className="text-sm font-bold text-slate-800 dark:text-slate-100">Allocation drift</div>
                    <div className="text-[11px] text-slate-500">Current vs target by asset class</div>
                  </div>
                </div>
                <ul className="space-y-2.5">
                  {buckets.map((b) => {
                    const cur = (drift.current || {})[b] || 0;
                    const tgt = (drift.target  || {})[b] || 0;
                    const delta = cur - tgt;
                    const absDelta = Math.abs(delta);
                    const tone = absDelta >= 10 ? "rose" : absDelta >= 5 ? "amber" : "emerald";
                    return (
                      <li key={b} data-testid={`drift-${b}`} className="space-y-1">
                        <div className="flex items-baseline justify-between text-xs">
                          <span className="font-semibold capitalize text-slate-700 dark:text-slate-200">{b}</span>
                          <span className="tabular-nums text-slate-600 dark:text-slate-300">
                            {cur.toFixed(1)}% <span className="text-slate-400 text-[10px]">/ target {tgt.toFixed(1)}%</span>
                          </span>
                        </div>
                        <div className="h-1.5 rounded-full bg-slate-100 dark:bg-slate-800 overflow-hidden relative">
                          <div className={`absolute top-0 h-full ${TONE[tone].bar}`} style={{ width: `${Math.min(100, cur)}%` }} />
                          <div className="absolute top-0 w-0.5 h-full bg-slate-600 dark:bg-slate-300" style={{ left: `${Math.min(100, tgt)}%` }} />
                        </div>
                        <div className={`text-[10px] font-medium ${TONE[tone].text}`}>
                          {delta >= 0 ? "+" : ""}{delta.toFixed(1)}pp vs target
                        </div>
                      </li>
                    );
                  })}
                </ul>
              </Card>
            );
          })()}

          {/* ── Recent purchases + Advisor notes side-by-side ──── */}
          <Card className="lg:col-span-1 p-5" data-testid="snapshot-recent-buys-card">
            <div className="flex items-center gap-2 mb-4">
              <div className="w-8 h-8 rounded-xl bg-amber-100 dark:bg-amber-900/40 flex items-center justify-center">
                <Receipt className="w-4 h-4 text-amber-600" />
              </div>
              <div>
                <div className="text-sm font-bold text-slate-800 dark:text-slate-100">Recent purchases</div>
                <div className="text-[11px] text-slate-500">Last 5 buys from CAS history</div>
              </div>
            </div>
            {(!trend?.recent_buys?.length) ? (
              <div className="text-center py-6 text-xs text-slate-500" data-testid="snapshot-recent-buys-empty">
                <Receipt className="w-5 h-5 mx-auto mb-1.5 opacity-40" />
                No dated transactions yet. Upload a CAS to populate history.
              </div>
            ) : (
              <ul className="space-y-2" data-testid="snapshot-recent-buys-list">
                {trend.recent_buys.map((b, i) => (
                  <li
                    key={i}
                    data-testid={`snapshot-recent-buy-${i}`}
                    className="flex items-center gap-2 py-1.5 border-b last:border-0 border-slate-100 dark:border-slate-800"
                  >
                    <div className="min-w-0 flex-1">
                      <div className="text-xs font-semibold text-slate-700 dark:text-slate-200 truncate">
                        {b.name}
                      </div>
                      <div className="text-[10px] text-slate-500">
                        {b.buy_date} · {b.quantity} units · {b.asset_type}
                      </div>
                    </div>
                    <div className="text-xs font-bold tabular-nums text-slate-700 dark:text-slate-200 text-right">
                      {fmtRs(b.value_rs)}
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </Card>

          <Card className="lg:col-span-2 p-5" data-testid="snapshot-notes-card">
            <div className="flex items-center justify-between mb-4 flex-wrap gap-2">
              <div className="flex items-center gap-2">
                <div className="w-8 h-8 rounded-xl bg-indigo-100 dark:bg-indigo-900/40 flex items-center justify-center">
                  <StickyNote className="w-4 h-4 text-indigo-600" />
                </div>
                <div>
                  <div className="text-sm font-bold text-slate-800 dark:text-slate-100">Advisor notes & SIP</div>
                  <div className="text-[11px] text-slate-500">
                    {notesSaved ? `Saved ${fmtDaysAgo(notesSaved)}` : "Only you (the advisor) can see this"}
                  </div>
                </div>
              </div>
              <Button
                size="sm"
                onClick={saveNotes}
                disabled={!notesDirty || savingNotes}
                data-testid="snapshot-save-notes"
                className="h-8 text-xs bg-indigo-600 hover:bg-indigo-700"
              >
                <Save className="w-3.5 h-3.5 mr-1" />
                {savingNotes ? "Saving…" : notesDirty ? "Save" : "Saved"}
              </Button>
            </div>

            {/* SIP structured fields */}
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 mb-3">
              <div>
                <label className="text-[10px] uppercase tracking-wider font-semibold text-slate-500 block mb-1">
                  SIP amount (₹/month)
                </label>
                <Input
                  type="number" min="0" step="500"
                  value={notes.sip_amount_rs}
                  placeholder="e.g. 25000"
                  onChange={(e) => patchNote("sip_amount_rs", e.target.value)}
                  data-testid="snapshot-sip-amount"
                  className="h-8 text-xs"
                />
              </div>
              <div>
                <label className="text-[10px] uppercase tracking-wider font-semibold text-slate-500 block mb-1">
                  Next SIP due
                </label>
                <Input
                  type="date"
                  value={notes.next_sip_due}
                  onChange={(e) => patchNote("next_sip_due", e.target.value)}
                  data-testid="snapshot-sip-due"
                  className="h-8 text-xs"
                />
              </div>
              <div>
                <label className="text-[10px] uppercase tracking-wider font-semibold text-slate-500 block mb-1">
                  Preferred channel
                </label>
                <select
                  value={notes.preferred_channel}
                  onChange={(e) => patchNote("preferred_channel", e.target.value)}
                  data-testid="snapshot-preferred-channel"
                  className="w-full h-8 text-xs rounded-md border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 px-2"
                >
                  <option value="">—</option>
                  <option value="whatsapp">WhatsApp</option>
                  <option value="email">Email</option>
                  <option value="phone">Phone</option>
                  <option value="meeting">In-person</option>
                </select>
              </div>
            </div>

            <Textarea
              value={notes.note}
              placeholder="Free-form notes about this client — risk temperament, life events, preferred funds, last call summary…"
              onChange={(e) => patchNote("note", e.target.value)}
              data-testid="snapshot-note-textarea"
              className="text-xs min-h-[96px]"
              maxLength={4000}
            />
            <div className="text-[10px] text-slate-400 text-right mt-1">
              {(notes.note || "").length}/4000
            </div>
          </Card>
        </div>
      )}

      {/* ── Flag strip ─────────────────────────────────────────────── */}
      {!loading && (
        <div className="flex flex-wrap items-center gap-2 text-[11px] text-slate-500 pt-1">
          <AlertTriangle className="w-3.5 h-3.5 text-amber-500" />
          Data on this page is computed live — no cache. Refresh via the button below for the latest.
          <Button
            size="sm" variant="ghost"
            onClick={() => { fetchAll(); onRefresh?.(); }}
            className="h-6 text-[11px]"
            data-testid="snapshot-refresh"
          >
            <RefreshCw className="w-3 h-3 mr-1" /> Refresh
          </Button>
        </div>
      )}

      {/* ── Nivesh Copilot drawer ──────────────────────────────────── */}
      <NiveshCopilot
        open={copilotOpen}
        onClose={() => setCopilotOpen(false)}
        clientName={client.name}
      />

      {/* ── Client CAS invite modal ───────────────────────────────── */}
      <ClientCasInviteModal
        open={inviteOpen}
        onClose={() => setInviteOpen(false)}
        profileId={profileId}
        profileName={client.name}
      />
    </div>
  );
}
