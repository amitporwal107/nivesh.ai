import React, { useState, useEffect, useCallback, useMemo } from "react";
import axios from "axios";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import {
  Tooltip, TooltipContent, TooltipProvider, TooltipTrigger,
} from "@/components/ui/tooltip";
import {
  Users, Plus, ArrowRight, Activity, AlertTriangle, Search,
  Briefcase, Trash2, TrendingUp, Calendar, Filter,
  RefreshCw, Scale, Eye, CheckCircle2, Sparkles, ClipboardCheck,
} from "lucide-react";
import AddClientDialog from "./AddClientDialog";
import PriorityChip from "./PriorityChip";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

/**
 * MfdDashboard — Multi-Client Operating View (v2: action-first).
 *
 * Every row is a decision: we derive a Top Issue tag and an Action verb
 * from `priority.factors` so MFDs never see blank columns or "which client
 * needs what" ambiguity. The Priority chip keeps the explainability
 * tooltip from PriorityChip.jsx.
 */

const fmtRs = (n) => {
  if (n == null) return "—";
  if (n >= 1e7) return `₹${(n / 1e7).toFixed(2)} Cr`;
  if (n >= 1e5) return `₹${(n / 1e5).toFixed(2)} L`;
  return `₹${Math.round(n).toLocaleString("en-IN")}`;
};

const fmtDaysSince = (iso) => {
  if (!iso) return "First review";
  const d = Math.floor((Date.now() - new Date(iso).getTime()) / 86400000);
  if (d === 0) return "today";
  if (d === 1) return "yesterday";
  if (d < 30) return `${d}d ago`;
  if (d < 365) return `${Math.floor(d / 30)}mo ago`;
  return `${Math.floor(d / 365)}y ago`;
};

// ── Issue + Action derivation ──────────────────────────────────────────
// These are intentionally simple ladders; once we have more MFD feedback
// we'll lift them into the backend priority_engine so the server-side
// notification system uses the same verbs.

const deriveTopIssue = (p) => {
  const f = p.priority?.factors || {};
  const unreviewed = !p.last_reviewed_at;
  if (f.risk >= 0.6) return { key: "over-risk", label: "Over-risk", tone: "rose" };
  if (f.portfolio_weakness >= 0.4) return { key: "underperforming", label: "Underperforming", tone: "rose" };
  if (f.recommendation_severity >= 0.7) return { key: "exit-switch", label: "Exit/Switch due", tone: "rose" };
  if (f.recommendation_severity >= 0.4) return { key: "rebalance", label: "Rebalance pending", tone: "amber" };
  if (unreviewed) return { key: "unreviewed", label: "Not reviewed yet", tone: "amber" };
  if (f.recency >= 1.0) return { key: "stale", label: "Review stale", tone: "amber" };
  if ((p.recommendation_count || 0) > 0) return { key: "review", label: "Review suggested", tone: "slate" };
  return { key: "healthy", label: "Healthy", tone: "emerald" };
};

const deriveAction = (p) => {
  const f = p.priority?.factors || {};
  const unreviewed = !p.last_reviewed_at;
  if (f.recommendation_severity >= 0.7) return { label: "Switch",       tone: "rose",    Icon: RefreshCw };
  if (f.recommendation_severity >= 0.4) return { label: "Rebalance",    tone: "amber",   Icon: Scale };
  if (f.portfolio_weakness >= 0.4)      return { label: "Rebalance",    tone: "amber",   Icon: Scale };
  if (unreviewed)                       return { label: "First review", tone: "indigo",  Icon: ClipboardCheck };
  if (f.recency >= 1.0)                 return { label: "Review",       tone: "amber",   Icon: Eye };
  if ((p.recommendation_count || 0) > 0) return { label: "Review",      tone: "slate",   Icon: Eye };
  return { label: "All good", tone: "emerald", Icon: CheckCircle2 };
};

const TONE_CLASSES = {
  rose:    { bg: "bg-rose-50 dark:bg-rose-900/20",       border: "border-rose-200 dark:border-rose-800",       text: "text-rose-700 dark:text-rose-300",       dot: "bg-rose-500",    btn: "bg-rose-600 hover:bg-rose-700 text-white" },
  amber:   { bg: "bg-amber-50 dark:bg-amber-900/20",     border: "border-amber-200 dark:border-amber-800",     text: "text-amber-700 dark:text-amber-300",     dot: "bg-amber-500",   btn: "bg-amber-500 hover:bg-amber-600 text-white" },
  indigo:  { bg: "bg-indigo-50 dark:bg-indigo-900/20",   border: "border-indigo-200 dark:border-indigo-800",   text: "text-indigo-700 dark:text-indigo-300",   dot: "bg-indigo-500",  btn: "bg-indigo-600 hover:bg-indigo-700 text-white" },
  slate:   { bg: "bg-slate-100 dark:bg-slate-800",       border: "border-slate-200 dark:border-slate-700",     text: "text-slate-600 dark:text-slate-300",     dot: "bg-slate-400",   btn: "bg-slate-600 hover:bg-slate-700 text-white" },
  emerald: { bg: "bg-emerald-50 dark:bg-emerald-900/20", border: "border-emerald-200 dark:border-emerald-800", text: "text-emerald-700 dark:text-emerald-300", dot: "bg-emerald-500", btn: "bg-emerald-600 hover:bg-emerald-700 text-white" },
};

// Score bar tone derived from the value itself. ≥70 is healthy; 50-69
// is amber; <50 is rose. For risk we invert the semantics (high risk = rose)
// but present the same bar width.
const qualityTone = (v) => (v == null ? "slate" : v >= 70 ? "emerald" : v >= 50 ? "amber" : "rose");
const riskTone    = (v) => (v == null ? "slate" : v < 40 ? "emerald" : v < 60 ? "amber" : "rose");

// ── Score bar (replaces "—") ───────────────────────────────────────────
const ScoreBar = ({ value, tone, testId, label }) => {
  const t = TONE_CLASSES[tone] || TONE_CLASSES.slate;
  if (value == null) {
    return (
      <div className="w-full" data-testid={testId}>
        <div className="flex items-center justify-between text-[9px] uppercase tracking-wider font-semibold text-slate-400 mb-0.5">
          <span>{label}</span>
          <span className="italic">Calculating…</span>
        </div>
        <div className="h-1.5 rounded-full bg-slate-100 dark:bg-slate-800 relative overflow-hidden">
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

// ── Issue tag pill ─────────────────────────────────────────────────────
const IssueTag = ({ issue }) => {
  const t = TONE_CLASSES[issue.tone] || TONE_CLASSES.slate;
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

// ── Summary tile ───────────────────────────────────────────────────────
const SummaryTile = ({ label, count, tone, icon: Icon, testId, active, onClick }) => {
  const t = TONE_CLASSES[tone] || TONE_CLASSES.slate;
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

export default function MfdDashboard({ onEnterProfile }) {
  const [workspace, setWorkspace] = useState(null);
  const [profiles, setProfiles] = useState([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [bucketFilter, setBucketFilter] = useState("all");
  const [issueFilter, setIssueFilter] = useState("all");
  const [addOpen, setAddOpen] = useState(false);
  const [activating, setActivating] = useState(null);

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

  const activateProfile = async (profile) => {
    setActivating(profile.profile_id);
    try {
      await axios.post(`${API}/mfd/profiles/${profile.profile_id}/activate`, {},
                       { withCredentials: true });
      toast.success(`Opened ${profile.name}'s portfolio`);
      onEnterProfile?.(profile);
    } catch (e) {
      toast.error("Could not open profile");
    } finally {
      setActivating(null);
    }
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

  // ── Decorate each profile with derived Top Issue + Action ─────────────
  const decorated = useMemo(() => profiles.map((p) => ({
    ...p,
    _issue: deriveTopIssue(p),
    _action: deriveAction(p),
  })), [profiles]);

  // ── Counts for summary strip & filter pills ──────────────────────────
  const counts = useMemo(() => {
    const c = {
      actionNeeded: 0, overRisk: 0, underperforming: 0,
      rebalance: 0, stale: 0, healthy: 0,
      high: 0, medium: 0, low: 0,
    };
    for (const p of decorated) {
      if (p.priority?.bucket === "high") c.high++;
      else if (p.priority?.bucket === "medium") c.medium++;
      else c.low++;
      if (p._issue.key === "over-risk") c.overRisk++;
      if (p._issue.key === "underperforming") c.underperforming++;
      if (p._issue.key === "rebalance" || p._issue.key === "exit-switch") c.rebalance++;
      if (p._issue.key === "stale" || p._issue.key === "unreviewed") c.stale++;
      if (p._issue.key === "healthy") c.healthy++;
      if (p._action.label !== "All good") c.actionNeeded++;
    }
    return c;
  }, [decorated]);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    return decorated.filter((p) => {
      if (q && !p.name.toLowerCase().includes(q)) return false;
      if (bucketFilter !== "all" && p.priority.bucket !== bucketFilter) return false;
      if (issueFilter !== "all") {
        if (issueFilter === "over-risk"        && p._issue.key !== "over-risk") return false;
        if (issueFilter === "underperforming"  && p._issue.key !== "underperforming") return false;
        if (issueFilter === "rebalance"        && p._issue.key !== "rebalance" && p._issue.key !== "exit-switch") return false;
        if (issueFilter === "stale"            && p._issue.key !== "stale" && p._issue.key !== "unreviewed") return false;
        if (issueFilter === "healthy"          && p._issue.key !== "healthy") return false;
      }
      return true;
    });
  }, [decorated, search, bucketFilter, issueFilter]);

  const totalAum = useMemo(
    () => profiles.reduce((acc, p) => acc + (p.aum_rs || 0), 0),
    [profiles],
  );

  // ── ADVISORY-mode gate (unchanged)
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

  // ── Actionable header sentence ───────────────────────────────────────
  const headerSentence =
    counts.actionNeeded === 0
      ? "All clients are on track — no action needed today."
      : `${counts.actionNeeded} ${counts.actionNeeded === 1 ? "client needs" : "clients need"} action today.`;

  return (
    <div className="space-y-4" data-testid="mfd-dashboard">
      {/* ── Header ─────────────────────────────────────────────────── */}
      <div className="flex items-start justify-between flex-wrap gap-3">
        <div>
          <div className="flex items-center gap-2">
            <Users className="w-5 h-5 text-indigo-600" />
            <h2 className="text-xl font-bold text-slate-800 dark:text-slate-100">
              Advisor Dashboard
            </h2>
            <Badge variant="outline" className="text-[10px]">{workspace?.type}</Badge>
          </div>
          <p
            className={`text-sm mt-1 font-medium ${counts.actionNeeded > 0 ? "text-rose-700 dark:text-rose-400" : "text-emerald-700 dark:text-emerald-400"}`}
            data-testid="mfd-header-sentence"
          >
            {headerSentence}
          </p>
          <p className="text-xs text-slate-500">
            Book: {profiles.filter((p) => p.type === "CLIENT").length} clients · AUM {fmtRs(totalAum)}
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

      {/* ── Quick summary strip — 4 action-tiles ───────────────────── */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3" data-testid="mfd-summary-strip">
        <SummaryTile
          testId="summary-over-risk"
          label="Over-risk"
          count={counts.overRisk}
          tone="rose"
          icon={AlertTriangle}
          active={issueFilter === "over-risk"}
          onClick={() => setIssueFilter(issueFilter === "over-risk" ? "all" : "over-risk")}
        />
        <SummaryTile
          testId="summary-underperforming"
          label="Underperforming"
          count={counts.underperforming}
          tone="rose"
          icon={TrendingUp}
          active={issueFilter === "underperforming"}
          onClick={() => setIssueFilter(issueFilter === "underperforming" ? "all" : "underperforming")}
        />
        <SummaryTile
          testId="summary-rebalance"
          label="Rebalance pending"
          count={counts.rebalance}
          tone="amber"
          icon={Scale}
          active={issueFilter === "rebalance"}
          onClick={() => setIssueFilter(issueFilter === "rebalance" ? "all" : "rebalance")}
        />
        <SummaryTile
          testId="summary-stale"
          label="Review stale"
          count={counts.stale}
          tone="amber"
          icon={Calendar}
          active={issueFilter === "stale"}
          onClick={() => setIssueFilter(issueFilter === "stale" ? "all" : "stale")}
        />
      </div>

      {/* ── Search + bucket + issue filter chips ──────────────────── */}
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
        <div className="flex items-center gap-1" data-testid="mfd-bucket-filter">
          <Filter className="w-3.5 h-3.5 text-slate-400" />
          {["all", "high", "medium", "low"].map((b) => (
            <Button
              key={b}
              size="sm"
              variant={bucketFilter === b ? "default" : "outline"}
              className="h-7 text-[11px] capitalize"
              onClick={() => setBucketFilter(b)}
              data-testid={`mfd-filter-${b}`}
            >
              {b}
              {b !== "all" && counts[b] ? ` · ${counts[b]}` : ""}
            </Button>
          ))}
        </div>
        {issueFilter !== "all" && (
          <Button
            size="sm"
            variant="ghost"
            onClick={() => setIssueFilter("all")}
            className="h-7 text-[11px] text-slate-500 hover:text-slate-700"
            data-testid="mfd-clear-issue-filter"
          >
            Clear issue filter ×
          </Button>
        )}
      </div>

      {/* ── Client table ──────────────────────────────────────────── */}
      <Card className="overflow-hidden" data-testid="mfd-client-table">
        {/* Header row — 12-col grid tuned for action-first layout */}
        <div className="grid grid-cols-12 gap-2 px-4 py-2 bg-slate-50 dark:bg-slate-800 text-[10px] uppercase tracking-wider font-semibold text-slate-500 border-b dark:border-slate-700">
          <div className="col-span-3">Client</div>
          <div className="col-span-2">Top issue</div>
          <div className="col-span-2">Scores</div>
          <div className="col-span-1 text-right">AUM</div>
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
            {search || bucketFilter !== "all" || issueFilter !== "all" ? (
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
            const actionTone = TONE_CLASSES[p._action.tone] || TONE_CLASSES.slate;
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
                    <div
                      className="w-8 h-8 rounded-full bg-indigo-100 text-indigo-700 dark:bg-indigo-900/40 dark:text-indigo-300 flex items-center justify-center text-[11px] font-bold flex-shrink-0"
                      aria-hidden
                    >
                      {p.name?.slice(0, 1).toUpperCase() || "?"}
                    </div>
                    <div className="min-w-0">
                      <div className="text-sm font-semibold text-slate-800 dark:text-slate-100 truncate flex items-center gap-1.5">
                        {p.name}
                        {p.type === "SELF" && (
                          <Badge variant="outline" className="text-[8px] h-4 px-1">YOU</Badge>
                        )}
                      </div>
                      <div className="text-[10px] text-slate-500 truncate">
                        {(p.tags || []).join(" · ") || "—"}
                      </div>
                    </div>
                  </div>
                </button>

                {/* Top issue */}
                <div className="col-span-2">
                  <IssueTag issue={p._issue} />
                </div>

                {/* Score bars */}
                <div className="col-span-2 space-y-1.5 min-w-0">
                  <ScoreBar
                    testId={`quality-bar-${p.profile_id}`}
                    label="Quality"
                    value={p.portfolio_score}
                    tone={qualityTone(p.portfolio_score)}
                  />
                  <ScoreBar
                    testId={`risk-bar-${p.profile_id}`}
                    label="Risk"
                    value={p.risk_score}
                    tone={riskTone(p.risk_score)}
                  />
                </div>

                {/* AUM */}
                <div className="col-span-1 text-right tabular-nums text-sm font-medium text-slate-700 dark:text-slate-300">
                  {fmtRs(p.aum_rs)}
                </div>

                {/* Review (replaces "never" wording) */}
                <div className="col-span-1 text-right text-[11px]">
                  {p.last_reviewed_at ? (
                    <div className="inline-flex items-center gap-1 text-slate-500">
                      <Calendar className="w-3 h-3" /> {fmtDaysSince(p.last_reviewed_at)}
                    </div>
                  ) : (
                    <span className="inline-flex items-center gap-1 text-amber-700 dark:text-amber-400 font-medium">
                      <Sparkles className="w-3 h-3" /> Needs first review
                    </span>
                  )}
                </div>

                {/* Priority chip (with existing tooltip) */}
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
                          onClick={() => activateProfile(p)}
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
