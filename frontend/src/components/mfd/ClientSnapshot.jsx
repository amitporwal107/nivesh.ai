import React, { useEffect, useState, useCallback } from "react";
import axios from "axios";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  LayoutDashboard, TrendingUp, Target, AlertTriangle, CheckCircle2,
  Calendar, Sparkles, ArrowRight, Activity, Scale, RefreshCw, Plus, Eye,
  ShieldCheck,
} from "lucide-react";

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

const ACTION_VIEW = {
  exit:         { label: "Exit",         Icon: RefreshCw, tone: "rose"    },
  switch:       { label: "Switch",       Icon: RefreshCw, tone: "rose"    },
  reduce:       { label: "Reduce",       Icon: RefreshCw, tone: "rose"    },
  rebalance:    { label: "Rebalance",    Icon: Scale,     tone: "amber"   },
  increase_sip: { label: "Increase SIP", Icon: TrendingUp,tone: "indigo"  },
  add_more:     { label: "Add more",     Icon: Plus,      tone: "indigo"  },
  add:          { label: "Add more",     Icon: Plus,      tone: "indigo"  },
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

export default function ClientSnapshot({ activeProfile, setActiveTab, onRefresh }) {
  const [loading, setLoading] = useState(true);
  const [health, setHealth] = useState(null);
  const [goals, setGoals] = useState([]);
  const [actions, setActions] = useState([]);

  const fetchAll = useCallback(async () => {
    setLoading(true);
    try {
      const [hRes, gRes, aRes] = await Promise.all([
        axios.get(`${API}/insights/analysis`, { withCredentials: true }).catch(() => null),
        axios.get(`${API}/goals`,             { withCredentials: true }).catch(() => null),
        axios.get(`${API}/action-plan`,       { withCredentials: true }).catch(() => null),
      ]);
      setHealth(hRes?.data?.portfolio_health || null);
      setGoals(gRes?.data?.goals || gRes?.data || []);
      const list = aRes?.data?.items || aRes?.data?.plans || aRes?.data || [];
      setActions((Array.isArray(list) ? list : [])
        .filter((a) => (a.status || "").toLowerCase() !== "archived")
        .slice(0, 3));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchAll(); }, [fetchAll]);

  // Derive a concise summary — prefer backend-written one if present.
  const client = activeProfile || {};
  const aumLive = client.portfolio_value_rs || client.aum_rs;
  const hs = health?.health_score;
  const hsTone = healthTone(hs);
  const hsT = TONE[hsTone];

  const riskAlignment = (() => {
    const rc = (health?.components || {}).risk;
    if (!rc) return { label: "No data", tone: "slate" };
    if (rc.score >= 70) return { label: "Well within profile", tone: "emerald" };
    if (rc.score >= 50) return { label: "Mild mismatch", tone: "amber" };
    return { label: "Risk higher than profile", tone: "rose" };
  })();

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
          </div>
          <p className="text-xs text-slate-500 mt-1">
            {fmtRs(aumLive)} AUM · Last review {fmtDaysAgo(client.last_reviewed_at)}
          </p>
        </div>
        <Button
          variant="outline" size="sm"
          onClick={() => setActiveTab("overview")}
          data-testid="snapshot-open-portfolio"
          className="h-8 text-xs"
        >
          Open full portfolio <ArrowRight className="w-3.5 h-3.5 ml-1" />
        </Button>
      </div>

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
                <div className="text-[10px] uppercase tracking-wider font-bold text-slate-500">
                  Portfolio Health
                </div>
                <div className={`text-lg font-semibold mt-1 ${hsT.text}`}>
                  {health?.grade ? `Grade ${health.grade}` : "Scoring…"}
                </div>
                <p className="text-sm text-slate-600 dark:text-slate-300 mt-2 leading-relaxed" data-testid="snapshot-health-summary">
                  {health?.summary || client.ai_summary || "No summary available yet."}
                </p>
                <div className="mt-4 inline-flex items-center gap-1.5 text-xs font-medium" data-testid="snapshot-risk-alignment">
                  <ShieldCheck className={`w-3.5 h-3.5 ${TONE[riskAlignment.tone].text}`} />
                  <span className={TONE[riskAlignment.tone].text}>
                    Risk vs profile: {riskAlignment.label}
                  </span>
                </div>
              </div>
            </div>

            {/* Component breakdown */}
            {health?.components && (
              <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mt-6 pt-5 border-t border-slate-100 dark:border-slate-800">
                {["quality", "risk", "diversification", "performance"].map((k) => {
                  const c = health.components[k];
                  const tone = c ? healthTone(c.score) : "slate";
                  return (
                    <ComponentBar
                      key={k}
                      label={(c?.label || k).replace(/_/g, " ").replace(/\b\w/g, (s) => s.toUpperCase())}
                      value={c?.score}
                      tone={tone}
                      testId={`snapshot-component-${k}`}
                    />
                  );
                })}
              </div>
            )}
          </Card>

          {/* ── Top 3 actions card (right) ───────────────────────── */}
          <Card className="p-5" data-testid="snapshot-actions-card">
            <div className="flex items-center gap-2 mb-4">
              <div className="w-8 h-8 rounded-xl bg-indigo-100 dark:bg-indigo-900/40 flex items-center justify-center">
                <Sparkles className="w-4 h-4 text-indigo-600" />
              </div>
              <div>
                <div className="text-sm font-bold text-slate-800 dark:text-slate-100">
                  Recommended actions
                </div>
                <div className="text-[11px] text-slate-500">Top priorities for this client</div>
              </div>
            </div>

            {actions.length === 0 ? (
              <div className="text-center py-6 text-xs text-slate-500" data-testid="snapshot-actions-empty">
                <CheckCircle2 className="w-5 h-5 mx-auto mb-1.5 text-emerald-500" />
                No open actions right now.
              </div>
            ) : (
              <ul className="space-y-2.5">
                {actions.map((a, i) => {
                  const verb = (a.action || a.type || "").toLowerCase();
                  const view = ACTION_VIEW[verb] || { label: a.action || a.type || "Review", Icon: Eye, tone: "slate" };
                  const t = TONE[view.tone] || TONE.slate;
                  return (
                    <li
                      key={a.id || i}
                      data-testid={`snapshot-action-${i}`}
                      className={`flex items-start gap-2.5 p-3 rounded-lg border ${t.border} ${t.bgSoft}`}
                    >
                      <view.Icon className={`w-4 h-4 ${t.text} flex-shrink-0 mt-0.5`} />
                      <div className="min-w-0 flex-1">
                        <div className="text-sm font-semibold text-slate-800 dark:text-slate-100">
                          {view.label}{a.fund_name ? ` · ${a.fund_name}` : a.scheme_name ? ` · ${a.scheme_name}` : ""}
                        </div>
                        {a.reason && (
                          <div className="text-[11px] text-slate-500 mt-0.5 line-clamp-2">
                            {a.reason}
                          </div>
                        )}
                      </div>
                    </li>
                  );
                })}
              </ul>
            )}

            <Button
              size="sm" variant="outline"
              onClick={() => setActiveTab("plan_board")}
              data-testid="snapshot-open-plan-board"
              className="w-full mt-4 h-8 text-xs"
            >
              Open action plan <ArrowRight className="w-3.5 h-3.5 ml-1" />
            </Button>
          </Card>

          {/* ── Goals grid (full width below) ────────────────────── */}
          <Card className="lg:col-span-3 p-5" data-testid="snapshot-goals-card">
            <div className="flex items-center justify-between mb-4 flex-wrap gap-2">
              <div className="flex items-center gap-2">
                <div className="w-8 h-8 rounded-xl bg-emerald-100 dark:bg-emerald-900/40 flex items-center justify-center">
                  <Target className="w-4 h-4 text-emerald-600" />
                </div>
                <div>
                  <div className="text-sm font-bold text-slate-800 dark:text-slate-100">Goal progress</div>
                  <div className="text-[11px] text-slate-500">{goals.length || 0} goal{goals.length === 1 ? "" : "s"} tracked</div>
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
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
                {goals.slice(0, 6).map((g) => {
                  const pct = g.progress_percent ?? g.progress ?? (g.current_value && g.target_value ? (g.current_value / g.target_value) * 100 : 0);
                  const onTrack = pct >= 90;
                  const tone = onTrack ? "emerald" : pct >= 60 ? "amber" : "rose";
                  const t = TONE[tone];
                  return (
                    <div
                      key={g.id || g._id || g.name}
                      data-testid={`snapshot-goal-${g.id || g.name}`}
                      className="rounded-xl border border-slate-100 dark:border-slate-800 p-3"
                    >
                      <div className="flex items-center justify-between mb-1.5">
                        <div className="text-sm font-semibold text-slate-800 dark:text-slate-100 truncate">
                          {g.name || g.title || "Untitled"}
                        </div>
                        <span className={`text-xs font-bold tabular-nums ${t.text}`}>
                          {Math.round(pct)}%
                        </span>
                      </div>
                      <div className="h-1.5 rounded-full bg-slate-100 dark:bg-slate-800 overflow-hidden">
                        <div className={`h-full rounded-full ${t.bar}`} style={{ width: `${Math.min(100, Math.max(0, pct))}%` }} />
                      </div>
                      <div className="flex items-center justify-between text-[10px] text-slate-500 mt-1.5">
                        <span>
                          <Calendar className="w-3 h-3 inline -mt-0.5 mr-0.5" />
                          {g.target_year || g.horizon_years ? `${g.target_year || `${g.horizon_years}y`}` : "—"}
                        </span>
                        <span>Target {fmtRs(g.target_value)}</span>
                      </div>
                      {g.monthly_sip_required && (
                        <div className="text-[10px] text-indigo-600 font-medium mt-1">
                          SIP {fmtRs(g.monthly_sip_required)}/mo needed
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            )}
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
    </div>
  );
}
