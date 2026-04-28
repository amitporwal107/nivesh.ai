import React, { useState, useEffect, useCallback, useMemo } from "react";
import axios from "axios";
import { toast } from "sonner";
import { useAuth } from "@/context/AuthContext";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import {
  Tooltip, TooltipContent, TooltipProvider, TooltipTrigger,
} from "@/components/ui/tooltip";
import {
  Users, Plus, ArrowRight, Activity, AlertTriangle, Search,
  Briefcase, Trash2, TrendingUp, Calendar,
  RefreshCw, Scale, Eye, CheckCircle2, Sparkles, ClipboardCheck,
  Bell, Zap,
} from "lucide-react";
import AddClientDialog from "./AddClientDialog";
import PriorityChip from "./PriorityChip";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

/**
 * MfdDashboard v2 — "Advisor Command Center".
 *
 * Layout (top → bottom):
 *   1. Personalised greeting + action sentence
 *   2. Today's Actions feed (default entry point, not the table)
 *   3. Smart summary strip — clickable issue tiles
 *   4. Issue-filter chip row + search + add
 *   5. Client table (action-first columns)
 *
 * All data is derived from `/api/mfd/profiles` — backend returns
 * `portfolio_score`, `risk_score`, `priority.factors`, `priority.reasons`,
 * `recommendation_count`. We combine quality + risk into a single Health
 * Score (north-star) while still exposing the sub-scores inline.
 */

const fmtRs = (n) => {
  if (n == null) return "—";
  if (n >= 1e7) return `₹${(n / 1e7).toFixed(2)} Cr`;
  if (n >= 1e5) return `₹${(n / 1e5).toFixed(2)} L`;
  return `₹${Math.round(n).toLocaleString("en-IN")}`;
};

const fmtDaysSince = (iso) => {
  if (!iso) return null;
  const d = Math.floor((Date.now() - new Date(iso).getTime()) / 86400000);
  if (d === 0) return "today";
  if (d === 1) return "yesterday";
  if (d < 30) return `${d}d ago`;
  if (d < 365) return `${Math.floor(d / 30)}mo ago`;
  return `${Math.floor(d / 365)}y ago`;
};

const greetingFor = (name) => {
  const h = new Date().getHours();
  const greeting = h < 5 ? "Hello" : h < 12 ? "Good morning" : h < 17 ? "Good afternoon" : "Good evening";
  const first = (name || "").split(" ")[0];
  return first ? `${greeting}, ${first}` : greeting;
};

// ── Derivations ────────────────────────────────────────────────────────
// Unified Health Score — single north-star. Blend of:
//   60% quality (portfolio_score, already 0-100 from V3 engine)
//   40% (100 - risk_score)  — inverted so high risk = low health
// Either input null → null (ScoreBar renders "Calculating…").
const deriveHealth = (p) => {
  const q = p.portfolio_score;
  const r = p.risk_score;
  if (q == null && r == null) return null;
  if (q == null) return Math.round(Math.max(0, 100 - r));
  if (r == null) return Math.round(q);
  return Math.round(0.6 * q + 0.4 * (100 - r));
};

const healthTone = (v) => (v == null ? "slate" : v >= 70 ? "emerald" : v >= 50 ? "amber" : "rose");
const qualityTone = (v) => (v == null ? "slate" : v >= 70 ? "emerald" : v >= 50 ? "amber" : "rose");
const riskTone    = (v) => (v == null ? "slate" : v < 40 ? "emerald" : v < 60 ? "amber" : "rose");

const deriveTopIssue = (p) => {
  const f = p.priority?.factors || {};
  const unreviewed = !p.last_reviewed_at;
  // Enrich "Over-risk" with the concrete risk number if known.
  if (f.risk >= 0.6) {
    const r = p.risk_score != null ? ` (${Math.round(p.risk_score)}/100)` : "";
    return { key: "over-risk", label: `Over-risk${r}`, tone: "rose" };
  }
  if (f.portfolio_weakness >= 0.4) {
    const q = p.portfolio_score != null ? ` (${Math.round(p.portfolio_score)}/100)` : "";
    return { key: "underperforming", label: `Underperforming${q}`, tone: "rose" };
  }
  if (f.recommendation_severity >= 0.7) return { key: "exit-switch", label: "Exit/Switch due", tone: "rose" };
  if (f.recommendation_severity >= 0.4) return { key: "rebalance",   label: "Rebalance pending", tone: "amber" };
  if (unreviewed)                       return { key: "unreviewed",  label: "Not reviewed yet",  tone: "amber" };
  if (f.recency >= 1.0)                 return { key: "stale",       label: "Review stale",      tone: "amber" };
  if ((p.recommendation_count || 0) > 0) return { key: "review",     label: "Review suggested",  tone: "slate" };
  return { key: "healthy", label: "Healthy", tone: "emerald" };
};

const VERB_VIEW = {
  exit:         { label: "Exit",         tone: "rose",   Icon: RefreshCw },
  switch:       { label: "Switch",       tone: "rose",   Icon: RefreshCw },
  reduce:       { label: "Reduce",       tone: "rose",   Icon: RefreshCw },
  rebalance:    { label: "Rebalance",    tone: "amber",  Icon: Scale },
  increase_sip: { label: "Increase SIP", tone: "indigo", Icon: TrendingUp },
  add_more:     { label: "Add more",     tone: "indigo", Icon: Plus },
  add:          { label: "Add more",     tone: "indigo", Icon: Plus },
};

const deriveAction = (p) => {
  // Prefer the backend-computed dominant verb when the client has any
  // active recommendation — keeps engine + UI in lockstep.
  const v = p.priority?.dominant_action;
  if (v && VERB_VIEW[v]) return VERB_VIEW[v];

  const f = p.priority?.factors || {};
  const unreviewed = !p.last_reviewed_at;
  if (f.recommendation_severity >= 0.7) return { label: "Switch",       tone: "rose",    Icon: RefreshCw };
  if (f.recommendation_severity >= 0.4) return { label: "Rebalance",    tone: "amber",   Icon: Scale };
  if (f.portfolio_weakness >= 0.4)      return { label: "Rebalance",    tone: "amber",   Icon: Scale };
  if (f.risk >= 0.6)                    return { label: "Rebalance",    tone: "rose",    Icon: Scale };
  if (unreviewed)                       return { label: "First review", tone: "indigo",  Icon: ClipboardCheck };
  if (f.recency >= 1.0)                 return { label: "Review",       tone: "amber",   Icon: Eye };
  if ((p.recommendation_count || 0) > 0) return { label: "Review",      tone: "slate",   Icon: Eye };
  return { label: "All good", tone: "emerald", Icon: CheckCircle2 };
};

const TONE = {
  rose:    { bg: "bg-rose-50 dark:bg-rose-900/20",       border: "border-rose-200 dark:border-rose-800",       text: "text-rose-700 dark:text-rose-300",       dot: "bg-rose-500",    btn: "bg-rose-600 hover:bg-rose-700 text-white" },
  amber:   { bg: "bg-amber-50 dark:bg-amber-900/20",     border: "border-amber-200 dark:border-amber-800",     text: "text-amber-700 dark:text-amber-300",     dot: "bg-amber-500",   btn: "bg-amber-500 hover:bg-amber-600 text-white" },
  indigo:  { bg: "bg-indigo-50 dark:bg-indigo-900/20",   border: "border-indigo-200 dark:border-indigo-800",   text: "text-indigo-700 dark:text-indigo-300",   dot: "bg-indigo-500",  btn: "bg-indigo-600 hover:bg-indigo-700 text-white" },
  slate:   { bg: "bg-slate-100 dark:bg-slate-800",       border: "border-slate-200 dark:border-slate-700",     text: "text-slate-600 dark:text-slate-300",     dot: "bg-slate-400",   btn: "bg-slate-600 hover:bg-slate-700 text-white" },
  emerald: { bg: "bg-emerald-50 dark:bg-emerald-900/20", border: "border-emerald-200 dark:border-emerald-800", text: "text-emerald-700 dark:text-emerald-300", dot: "bg-emerald-500", btn: "bg-emerald-600 hover:bg-emerald-700 text-white" },
};

// ── Compact score bar ─────────────────────────────────────────────────
const ScoreBar = ({ value, tone, testId, label }) => {
  const t = TONE[tone] || TONE.slate;
  if (value == null) {
    return (
      <div className="w-full" data-testid={testId}>
        <div className="flex items-center justify-between text-[9px] uppercase tracking-wider font-semibold text-slate-400 mb-0.5">
          <span>{label}</span>
          <span className="italic">Calculating…</span>
        </div>
        <div className="h-1.5 rounded-full bg-slate-100 dark:bg-slate-800 overflow-hidden relative">
          <div className="absolute inset-0 bg-gradient-to-r from-transparent via-slate-200 dark:via-slate-700 to-transparent animate-pulse" />
        </div>
      </div>
    );
  }
  const v = Math.max(0, Math.min(100, Math.round(value)));
  return (
    <div className="w-full" data-testid={testId}>
      <div className="flex items-center justify-between text-[9px] uppercase tracking-wider font-semibold text-slate-400 mb-0.5">
        <span>{label}</span>
        <span className={`tabular-nums ${t.text}`}>{v}</span>
      </div>
      <div className="h-1.5 rounded-full bg-slate-100 dark:bg-slate-800 overflow-hidden">
        <div className={`h-full rounded-full ${t.dot}`} style={{ width: `${v}%` }} />
      </div>
    </div>
  );
};

// ── Issue tag pill ────────────────────────────────────────────────────
const IssueTag = ({ issue }) => {
  const t = TONE[issue.tone] || TONE.slate;
  return (
    <span
      data-testid={`issue-tag-${issue.key}`}
      className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] font-semibold whitespace-nowrap ${t.bg} ${t.border} ${t.text}`}
    >
      <span className={`w-1.5 h-1.5 rounded-full ${t.dot}`} />
      {issue.label}
    </span>
  );
};

// ── Summary tile (clickable filter) ────────────────────────────────────
const SummaryTile = ({ label, count, tone, icon: Icon, testId, active, onClick }) => {
  const t = TONE[tone] || TONE.slate;
  return (
    <button
      type="button"
      onClick={onClick}
      data-testid={testId}
      className={`text-left rounded-xl border p-3 transition-all hover:-translate-y-0.5 ${t.bg} ${t.border} ${active ? "ring-2 ring-offset-1 ring-indigo-400 dark:ring-indigo-500" : ""}`}
    >
      <div className="flex items-center gap-2">
        <div className={`w-7 h-7 rounded-md flex items-center justify-center ${t.dot} text-white`}>
          <Icon className="w-3.5 h-3.5" />
        </div>
        <div className="text-[10px] uppercase tracking-wider font-bold text-slate-500">{label}</div>
      </div>
      <div className={`mt-2 text-2xl font-bold tabular-nums ${t.text}`}>{count}</div>
    </button>
  );
};

// ── Filter chip (header segmentation) ──────────────────────────────────
const FilterChip = ({ id, label, count, tone, active, onClick, testId }) => {
  const t = TONE[tone] || TONE.slate;
  const activeCls = `${t.bg} ${t.border} ${t.text} border`;
  return (
    <button
      type="button"
      onClick={onClick}
      data-testid={testId}
      className={`inline-flex items-center gap-1.5 rounded-full h-7 px-3 text-[11px] font-semibold transition-colors ${
        active ? activeCls : "bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-700 text-slate-600 hover:border-slate-300"
      }`}
    >
      {label}
      {count != null && (
        <span className={`tabular-nums ${active ? "opacity-90" : "text-slate-400"}`}>· {count}</span>
      )}
    </button>
  );
};

export default function MfdDashboard({ onEnterProfile }) {
  const { user } = useAuth();
  const [workspace, setWorkspace] = useState(null);
  const [profiles, setProfiles] = useState([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [filter, setFilter] = useState("all");   // unified issue/priority filter
  const [addOpen, setAddOpen] = useState(false);
  const [activating, setActivating] = useState(null);
  const [feedExpanded, setFeedExpanded] = useState(false);

  const fetchProfiles = useCallback(async () => {
    setLoading(true);
    try {
      const res = await axios.get(`${API}/mfd/profiles`, { withCredentials: true });
      setWorkspace(res.data.workspace);
      setProfiles(res.data.profiles || []);
    } catch (e) {
      toast.error(e.response?.data?.detail || "Could not load profiles");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchProfiles(); }, [fetchProfiles]);

  const upgradeToAdvisory = async () => {
    try {
      await axios.patch(`${API}/mfd/workspace`,
        { mode: "ADVISORY", mfd_onboarding_completed: false },
        { withCredentials: true });
      toast.success("Welcome to Advisor mode — let's set up your practice");
      fetchProfiles();
    } catch (e) {
      toast.error(e.response?.data?.detail || "Could not switch mode");
    }
  };

  const activateProfile = async (profile, opts) => {
    setActivating(profile.profile_id);
    try {
      await axios.post(`${API}/mfd/profiles/${profile.profile_id}/activate`, {},
                       { withCredentials: true });
      toast.success(`Opened ${profile.name}'s portfolio`);
      onEnterProfile?.(profile, opts);
    } catch (e) {
      toast.error("Could not open profile");
    } finally {
      setActivating(null);
    }
  };

  // Route the action verbs to the right screen:
  //   Exit / Switch / Reduce / Rebalance → Plan Board (action cards live there)
  //   Increase SIP / Add more            → Goals (SIP plan lives there)
  //   Review / First review / All good   → Overview snapshot
  const openAction = (p) => {
    const actionLabel = p._action?.label || "";
    let tab = "snapshot";
    if (["Exit", "Switch", "Reduce", "Rebalance"].includes(actionLabel)) tab = "plan_board";
    else if (["Increase SIP", "Add more"].includes(actionLabel)) tab = "goals";
    activateProfile(p, { tab });
  };

  const removeProfile = async (profile, e) => {
    e.stopPropagation();
    if (!window.confirm(`Delete ${profile.name} and all associated data?`)) return;
    try {
      await axios.delete(`${API}/mfd/profiles/${profile.profile_id}`,
                         { withCredentials: true });
      toast.success(`${profile.name} removed`);
      fetchProfiles();
    } catch (e2) {
      toast.error(e2.response?.data?.detail || "Delete failed");
    }
  };

  // ── Decorate ────────────────────────────────────────────────────────
  // In ADVISORY mode the advisor's OWN portfolio (the SELF profile)
  // should not be treated as a client — it polluted health counters,
  // priority queues, and the action feed (e.g., "Priyanka Mantri ·
  // Underperforming · 39") even though there's nothing to advise on
  // your own book. We filter it out at the source so every downstream
  // memo (counts, filtered, todaysFeed, totalAum) is clean.
  const decorated = useMemo(() => profiles
    .filter((p) => p.type !== "SELF")
    .map((p) => ({
      ...p,
      // Prefer live portfolio value (holdings × price). Fall back to the
      // manually-entered AUM — used only for newly-onboarded clients before
      // CAS upload completes.
      _aum: (p.portfolio_value_rs && p.portfolio_value_rs > 0) ? p.portfolio_value_rs : p.aum_rs,
      _issue: deriveTopIssue(p),
      _action: deriveAction(p),
      _health: deriveHealth(p),
    })), [profiles]);

  const counts = useMemo(() => {
    const c = {
      total: decorated.length,
      actionNeeded: 0, overRisk: 0, underperforming: 0,
      rebalance: 0, stale: 0, healthy: 0,
      high: 0,
    };
    for (const p of decorated) {
      if (p.priority?.bucket === "high") c.high++;
      if (p._issue.key === "over-risk") c.overRisk++;
      if (p._issue.key === "underperforming") c.underperforming++;
      if (p._issue.key === "rebalance" || p._issue.key === "exit-switch") c.rebalance++;
      if (p._issue.key === "stale" || p._issue.key === "unreviewed") c.stale++;
      if (p._issue.key === "healthy") c.healthy++;
      if (p._action.label !== "All good") c.actionNeeded++;
    }
    return c;
  }, [decorated]);

  // Clients shown in the "Today's Actions" feed — anything that needs
  // action and is ranked high or medium. Sorted by priority score desc.
  const todaysFeed = useMemo(() => {
    const list = decorated
      .filter((p) => p._action.label !== "All good" && p.type === "CLIENT")
      .sort((a, b) => (b.priority?.score || 0) - (a.priority?.score || 0));
    return list;
  }, [decorated]);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    return decorated.filter((p) => {
      if (q && !p.name.toLowerCase().includes(q)) return false;
      if (filter === "all") return true;
      if (filter === "needs-action")    return p._action.label !== "All good";
      if (filter === "over-risk")       return p._issue.key === "over-risk";
      if (filter === "underperforming") return p._issue.key === "underperforming";
      if (filter === "rebalance")       return p._issue.key === "rebalance" || p._issue.key === "exit-switch";
      if (filter === "stale")           return p._issue.key === "stale" || p._issue.key === "unreviewed";
      if (filter === "healthy")         return p._issue.key === "healthy";
      return true;
    });
  }, [decorated, search, filter]);

  const totalAum = useMemo(
    () => decorated.reduce((acc, p) => acc + (p._aum || 0), 0),
    [decorated],
  );

  // ── ADVISORY-mode gate (unchanged) ──────────────────────────────────
  if (workspace && workspace.type === "INDIVIDUAL") {
    return (
      <div data-testid="mfd-upgrade-card" className="max-w-xl mx-auto mt-16">
        <Card className="p-6 border-2 border-dashed border-indigo-300">
          <Briefcase className="w-8 h-8 text-indigo-600 mb-3" />
          <div className="text-lg font-bold text-slate-800 dark:text-slate-100">
            Switch to Advisor mode
          </div>
          <p className="text-sm text-slate-600 dark:text-slate-400 mt-2">
            Manage multiple client portfolios from a single dashboard. Your
            personal portfolio stays intact — you'll just gain a client list,
            priority queue, and one-click "open client" view. You can switch
            back anytime.
          </p>
          <Button
            onClick={upgradeToAdvisory}
            className="mt-4 bg-indigo-600 hover:bg-indigo-700"
            data-testid="mfd-upgrade-btn"
          >
            Enable Advisor mode <ArrowRight className="w-4 h-4 ml-1" />
          </Button>
        </Card>
      </div>
    );
  }

  const clientCount = profiles.filter((p) => p.type === "CLIENT").length;
  const feedShown = feedExpanded ? todaysFeed : todaysFeed.slice(0, 3);

  return (
    <div className="space-y-4" data-testid="mfd-dashboard">
      {/* ── 1. Header / greeting ─────────────────────────────────── */}
      <div className="flex items-start justify-between flex-wrap gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <Users className="w-5 h-5 text-indigo-600" />
            <h2 className="text-xl font-bold text-slate-800 dark:text-slate-100" data-testid="mfd-greeting">
              {greetingFor(user?.name)}
            </h2>
            <Badge variant="outline" className="text-[10px]">{workspace?.type}</Badge>
          </div>
          {counts.actionNeeded > 0 ? (
            <div className="mt-1.5 flex items-center gap-2 flex-wrap" data-testid="mfd-header-action-sentence">
              <Zap className="w-4 h-4 text-rose-600" />
              <span className="text-sm font-semibold text-rose-700 dark:text-rose-400">
                {counts.actionNeeded} {counts.actionNeeded === 1 ? "client needs" : "clients need"} action today
              </span>
              {(counts.overRisk + counts.underperforming + counts.rebalance + counts.stale) > 0 && (
                <span className="text-xs text-slate-500">
                  {[
                    counts.overRisk        && `${counts.overRisk} over-risk`,
                    counts.underperforming && `${counts.underperforming} underperforming`,
                    counts.rebalance       && `${counts.rebalance} rebalance`,
                    counts.stale           && `${counts.stale} review stale`,
                  ].filter(Boolean).join(" · ")}
                </span>
              )}
            </div>
          ) : (
            <div className="mt-1.5 inline-flex items-center gap-2 text-sm font-semibold text-emerald-700 dark:text-emerald-400" data-testid="mfd-header-action-sentence">
              <CheckCircle2 className="w-4 h-4" /> All clients on track today
            </div>
          )}
          <p className="text-xs text-slate-500 mt-0.5">
            Book: ₹{fmtRs(totalAum).replace("₹", "")} · {clientCount} {clientCount === 1 ? "active client" : "active clients"}
          </p>
        </div>
        <Button
          onClick={() => setAddOpen(true)}
          data-testid="mfd-add-client-btn"
          className="bg-indigo-600 hover:bg-indigo-700"
        >
          <Plus className="w-4 h-4 mr-1" /> Add client
        </Button>
      </div>

      {/* ── 2. Today's Actions feed ──────────────────────────────── */}
      <Card className="p-4 border-indigo-100 dark:border-indigo-900/40" data-testid="mfd-action-feed">
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-2">
            <div className="w-8 h-8 rounded-xl bg-indigo-100 dark:bg-indigo-900/40 flex items-center justify-center">
              <Bell className="w-4 h-4 text-indigo-600" />
            </div>
            <div>
              <div className="text-sm font-bold text-slate-800 dark:text-slate-100">Today's actions</div>
              <div className="text-[11px] text-slate-500">
                {todaysFeed.length === 0 ? "Nothing urgent — enjoy the calm." : "Act on the highest-priority client first."}
              </div>
            </div>
          </div>
          {todaysFeed.length > 3 && (
            <Button
              size="sm"
              variant="ghost"
              onClick={() => setFeedExpanded(!feedExpanded)}
              className="text-xs text-indigo-600 hover:text-indigo-800"
              data-testid="mfd-feed-toggle"
            >
              {feedExpanded ? "Show top 3" : `Show all ${todaysFeed.length}`}
            </Button>
          )}
        </div>
        {todaysFeed.length === 0 ? (
          <div className="text-center py-6 text-xs text-slate-500" data-testid="mfd-feed-empty">
            <CheckCircle2 className="w-6 h-6 mx-auto mb-1.5 text-emerald-500" />
            Every active client is on track. Great work.
          </div>
        ) : (
          <div className="space-y-2">
            {feedShown.map((p) => {
              const t = TONE[p._action.tone] || TONE.slate;
              const ActionIcon = p._action.Icon;
              const reason = p.priority?.reasons?.[0] || p._issue.label;
              return (
                <div
                  key={p.profile_id}
                  data-testid={`feed-row-${p.profile_id}`}
                  className="flex items-center gap-3 p-3 rounded-lg bg-slate-50 dark:bg-slate-800/50 hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors"
                >
                  <PriorityChip priority={p.priority} />
                  <div className="flex-1 min-w-0">
                    <div className="text-sm font-semibold text-slate-800 dark:text-slate-100 truncate">
                      {p.name}
                    </div>
                    <div className="text-[11px] text-slate-500 truncate">
                      → {reason}
                    </div>
                  </div>
                  <button
                    type="button"
                    onClick={() => openAction(p)}
                    disabled={activating === p.profile_id}
                    data-testid={`feed-action-${p.profile_id}`}
                    className={`inline-flex items-center gap-1.5 rounded-lg px-3 h-8 text-[11px] font-semibold transition-all disabled:opacity-60 flex-shrink-0 ${t.btn}`}
                  >
                    <ActionIcon className="w-3.5 h-3.5" />
                    {p._action.label}
                  </button>
                </div>
              );
            })}
          </div>
        )}
      </Card>

      {/* ── 3. Smart summary strip ───────────────────────────────── */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3" data-testid="mfd-summary-strip">
        <SummaryTile
          testId="summary-over-risk" label="Risk issues" count={counts.overRisk} tone="rose" icon={AlertTriangle}
          active={filter === "over-risk"} onClick={() => setFilter(filter === "over-risk" ? "all" : "over-risk")}
        />
        <SummaryTile
          testId="summary-underperforming" label="Underperformance" count={counts.underperforming} tone="rose" icon={TrendingUp}
          active={filter === "underperforming"} onClick={() => setFilter(filter === "underperforming" ? "all" : "underperforming")}
        />
        <SummaryTile
          testId="summary-rebalance" label="Rebalance needed" count={counts.rebalance} tone="amber" icon={Scale}
          active={filter === "rebalance"} onClick={() => setFilter(filter === "rebalance" ? "all" : "rebalance")}
        />
        <SummaryTile
          testId="summary-healthy" label="Healthy" count={counts.healthy} tone="emerald" icon={CheckCircle2}
          active={filter === "healthy"} onClick={() => setFilter(filter === "healthy" ? "all" : "healthy")}
        />
      </div>

      {/* ── 4. Intelligent filter bar + search ───────────────────── */}
      <div className="flex items-center gap-2 flex-wrap">
        <div className="relative flex-1 max-w-sm">
          <Search className="w-3.5 h-3.5 absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
          <Input
            placeholder="Search client by name…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="pl-9 h-9 text-xs"
            data-testid="mfd-search"
          />
        </div>
        <div className="flex items-center gap-1.5 flex-wrap" data-testid="mfd-filter-row">
          <FilterChip id="all"             label="All"              count={counts.total}           tone="slate"   active={filter === "all"}             onClick={() => setFilter("all")}              testId="mfd-filter-all" />
          <FilterChip id="needs-action"    label="Needs action"     count={counts.actionNeeded}    tone="indigo"  active={filter === "needs-action"}    onClick={() => setFilter("needs-action")}     testId="mfd-filter-needs-action" />
          <FilterChip id="over-risk"       label="High risk"        count={counts.overRisk}        tone="rose"    active={filter === "over-risk"}       onClick={() => setFilter("over-risk")}        testId="mfd-filter-over-risk" />
          <FilterChip id="underperforming" label="Underperforming"  count={counts.underperforming} tone="rose"    active={filter === "underperforming"} onClick={() => setFilter("underperforming")} testId="mfd-filter-underperforming" />
          <FilterChip id="rebalance"       label="Rebalance"        count={counts.rebalance}       tone="amber"   active={filter === "rebalance"}       onClick={() => setFilter("rebalance")}        testId="mfd-filter-rebalance" />
          <FilterChip id="stale"           label="Review stale"     count={counts.stale}           tone="amber"   active={filter === "stale"}           onClick={() => setFilter("stale")}            testId="mfd-filter-stale" />
        </div>
      </div>

      {/* ── 5. Client table (action-first) ───────────────────────── */}
      <Card className="overflow-hidden" data-testid="mfd-client-table">
        <div className="grid grid-cols-12 gap-2 px-4 py-2 bg-slate-50 dark:bg-slate-800 text-[10px] uppercase tracking-wider font-semibold text-slate-500 border-b dark:border-slate-700">
          <div className="col-span-3">Client</div>
          <div className="col-span-1 text-right">AUM</div>
          <div className="col-span-2">Health</div>
          <div className="col-span-2">Top issue</div>
          <div className="col-span-1 text-right">Review</div>
          <div className="col-span-1 text-right">Priority</div>
          <div className="col-span-2 text-right">Action</div>
        </div>

        {loading && (
          <div className="py-10 text-center text-xs text-slate-500">
            <Activity className="w-4 h-4 mx-auto animate-pulse mb-2" />
            Loading client book…
          </div>
        )}

        {!loading && filtered.length === 0 && (
          <div className="py-10 text-center text-xs text-slate-500" data-testid="mfd-empty-state">
            {search || filter !== "all" ? (
              <>No clients match your filters.</>
            ) : (
              <>
                <Users className="w-8 h-8 mx-auto mb-2 opacity-40" />
                No clients yet — add your first client to begin.
                <div className="mt-3">
                  <Button size="sm" onClick={() => setAddOpen(true)}>
                    <Plus className="w-3 h-3 mr-1" /> Add first client
                  </Button>
                </div>
              </>
            )}
          </div>
        )}

        <div className="divide-y dark:divide-slate-800">
          {filtered.map((p) => {
            const actionTone = TONE[p._action.tone] || TONE.slate;
            const healthT = TONE[healthTone(p._health)];
            const ActionIcon = p._action.Icon;
            return (
              <div
                key={p.profile_id}
                data-testid={`mfd-client-row-${p.profile_id}`}
                className="grid grid-cols-12 gap-2 px-4 py-3 items-center hover:bg-slate-50 dark:hover:bg-slate-800/60 transition-colors"
              >
                {/* Client */}
                <button
                  type="button"
                  onClick={() => activateProfile(p)}
                  disabled={activating === p.profile_id}
                  className="col-span-3 min-w-0 text-left disabled:opacity-60"
                  data-testid={`mfd-client-name-${p.profile_id}`}
                >
                  <div className="flex items-center gap-2">
                    <div className="w-8 h-8 rounded-full bg-indigo-100 text-indigo-700 dark:bg-indigo-900/40 dark:text-indigo-300 flex items-center justify-center text-[11px] font-bold flex-shrink-0" aria-hidden>
                      {p.name?.slice(0, 1).toUpperCase() || "?"}
                    </div>
                    <div className="min-w-0">
                      <div className="text-sm font-semibold text-slate-800 dark:text-slate-100 truncate flex items-center gap-1.5">
                        {p.name}
                        {p.type === "SELF" && (<Badge variant="outline" className="text-[8px] h-4 px-1">YOU</Badge>)}
                      </div>
                      {p.ai_summary ? (
                        <div
                          className="text-[10px] text-slate-500 truncate"
                          title={p.ai_summary}
                          data-testid={`ai-summary-${p.profile_id}`}
                        >
                          <Sparkles className="w-2.5 h-2.5 inline -mt-0.5 mr-0.5 text-indigo-500" />
                          {p.ai_summary}
                        </div>
                      ) : (
                        <div className="text-[10px] text-slate-500 truncate">
                          {(p.tags || []).join(" · ") || "—"}
                        </div>
                      )}
                    </div>
                  </div>
                </button>

                {/* AUM — live portfolio value */}
                <div className="col-span-1 text-right tabular-nums text-sm font-medium text-slate-700 dark:text-slate-300">
                  {fmtRs(p._aum)}
                </div>

                {/* Health score — north star + sub-scores inline */}
                <div className="col-span-2 min-w-0">
                  {p._health == null ? (
                    <ScoreBar testId={`health-bar-${p.profile_id}`} label="Health" value={null} tone="slate" />
                  ) : (
                    <TooltipProvider delayDuration={150}>
                      <Tooltip>
                        <TooltipTrigger asChild>
                          <div className="cursor-default" data-testid={`health-score-${p.profile_id}`}>
                            <div className="flex items-baseline gap-1.5">
                              <span className={`text-lg font-bold tabular-nums ${healthT.text}`}>
                                {p._health}
                              </span>
                              <span className="text-[10px] text-slate-400">/100</span>
                              <span className={`w-2 h-2 rounded-full ${healthT.dot} ml-0.5`} />
                            </div>
                            <div className="text-[9px] uppercase tracking-wider text-slate-400">
                              Q {p.portfolio_score != null ? Math.round(p.portfolio_score) : "—"}
                              {" · "}
                              R {p.risk_score != null ? Math.round(p.risk_score) : "—"}
                            </div>
                          </div>
                        </TooltipTrigger>
                        <TooltipContent side="top" className="text-xs max-w-[220px]">
                          <div className="font-bold mb-1">Health score</div>
                          <div className="text-[11px] text-slate-600 dark:text-slate-300">
                            Blend of Quality ({p.portfolio_score != null ? Math.round(p.portfolio_score) : "—"}) and inverted Risk
                            ({p.risk_score != null ? Math.round(p.risk_score) : "—"}). Higher = stronger portfolio.
                          </div>
                        </TooltipContent>
                      </Tooltip>
                    </TooltipProvider>
                  )}
                </div>

                {/* Top issue */}
                <div className="col-span-2">
                  <IssueTag issue={p._issue} />
                </div>

                {/* Review */}
                <div className="col-span-1 text-right text-[11px]">
                  {p.last_reviewed_at ? (
                    <div className="inline-flex items-center gap-1 text-slate-500">
                      <Calendar className="w-3 h-3" /> {fmtDaysSince(p.last_reviewed_at)}
                    </div>
                  ) : (
                    <span className="inline-flex items-center gap-1 text-amber-700 dark:text-amber-400 font-medium">
                      <Sparkles className="w-3 h-3" /> First review
                    </span>
                  )}
                </div>

                {/* Priority chip */}
                <div className="col-span-1 flex justify-end">
                  <PriorityChip priority={p.priority} />
                </div>

                {/* Action */}
                <div className="col-span-2 flex items-center justify-end gap-1.5">
                  <TooltipProvider delayDuration={150}>
                    <Tooltip>
                      <TooltipTrigger asChild>
                        <button
                          type="button"
                          onClick={() => openAction(p)}
                          disabled={activating === p.profile_id}
                          data-testid={`mfd-action-btn-${p.profile_id}`}
                          className={`inline-flex items-center gap-1.5 rounded-lg px-3 h-8 text-[11px] font-semibold transition-all disabled:opacity-60 ${actionTone.btn}`}
                        >
                          <ActionIcon className="w-3.5 h-3.5" />
                          {p._action.label}
                        </button>
                      </TooltipTrigger>
                      <TooltipContent side="left" className="text-xs max-w-xs">
                        Open {p.name}'s portfolio to {p._action.label.toLowerCase()}.
                      </TooltipContent>
                    </Tooltip>
                  </TooltipProvider>
                  {p.type === "CLIENT" && (
                    <button
                      onClick={(e) => removeProfile(p, e)}
                      className="p-1 rounded hover:bg-rose-50 dark:hover:bg-rose-900/30 text-slate-400 hover:text-rose-600"
                      data-testid={`mfd-delete-${p.profile_id}`}
                      aria-label="Delete"
                    >
                      <Trash2 className="w-3.5 h-3.5" />
                    </button>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      </Card>

      <AddClientDialog
        open={addOpen}
        onClose={() => setAddOpen(false)}
        onCreated={() => { setAddOpen(false); fetchProfiles(); }}
      />
    </div>
  );
}
