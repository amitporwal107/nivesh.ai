/**
 * NIDP Data Quality Dashboard
 *
 * Implements the full PRD: Executive Summary, Feed Quality, Rule Failures,
 * Consistency Findings, Exception Queue, Publish Gate, and Trend Analytics.
 *
 * Sub-tabs: Overview · Consistency · Exceptions · Gate
 * Trend + Certification live in their own sibling panels (see NidpConsole.jsx).
 */
import React, { useEffect, useState, useCallback, useMemo } from "react";
import axios from "axios";
import {
  RefreshCw, Loader2, AlertTriangle, CheckCircle2, XCircle,
  ShieldCheck, ShieldAlert, ShieldX, Activity, Clock,
  BarChart2, ChevronDown, ChevronRight,
  Eye, Info, ThumbsUp, ThumbsDown, SkipForward, ArrowUpCircle,
  Lock,
} from "lucide-react";
import { toast } from "sonner";

const API = process.env.REACT_APP_BACKEND_URL;

// ── Helpers ───────────────────────────────────────────────────────────────

const fmtScore = (v) => (v == null ? "—" : Number(v).toFixed(2));
const fmtDate  = (s) => (!s ? "—" : s.length > 10 ? s.slice(0, 10) : s);

function relTime(iso) {
  if (!iso) return "—";
  const diff = (Date.now() - new Date(iso).getTime()) / 1000;
  if (diff < 60)    return `${Math.round(diff)}s ago`;
  if (diff < 3600)  return `${Math.round(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.round(diff / 3600)}h ago`;
  return `${Math.round(diff / 86400)}d ago`;
}

// ── Score colouring (PRD §24) ─────────────────────────────────────────────

function scoreColor(v, type = "quality") {
  if (v == null) return "text-slate-400";
  const thresholds = type === "confidence"
    ? { green: 98, yellow: 95 }
    : type === "accuracy"
      ? { green: 99.99, yellow: 99.9 }
      : { green: 99, yellow: 95 };
  if (v >= thresholds.green)  return "text-emerald-600 dark:text-emerald-400";
  if (v >= thresholds.yellow) return "text-amber-600 dark:text-amber-400";
  return "text-red-600 dark:text-red-400";
}

function scoreBg(v, type = "quality") {
  if (v == null) return "bg-slate-100 dark:bg-slate-800";
  const thresholds = type === "confidence"
    ? { green: 98, yellow: 95 }
    : { green: 99, yellow: 95 };
  if (v >= thresholds.green)  return "bg-emerald-50 dark:bg-emerald-900/20 border-emerald-200 dark:border-emerald-800";
  if (v >= thresholds.yellow) return "bg-amber-50 dark:bg-amber-900/20 border-amber-200 dark:border-amber-800";
  return "bg-red-50 dark:bg-red-900/20 border-red-200 dark:border-red-800";
}

// ── Certification badge ────────────────────────────────────────────────────

const CERT_STYLES = {
  Platinum: "bg-purple-100 text-purple-700 dark:bg-purple-900/40 dark:text-purple-300 ring-1 ring-purple-300 dark:ring-purple-700",
  Gold:     "bg-yellow-100 text-yellow-700 dark:bg-yellow-900/40 dark:text-yellow-300 ring-1 ring-yellow-300 dark:ring-yellow-700",
  Silver:   "bg-slate-100 text-slate-600 dark:bg-slate-700 dark:text-slate-300 ring-1 ring-slate-300 dark:ring-slate-600",
  Bronze:   "bg-orange-100 text-orange-700 dark:bg-orange-900/40 dark:text-orange-300 ring-1 ring-orange-300 dark:ring-orange-700",
  "Not Certified": "bg-slate-100 text-slate-500 dark:bg-slate-800 dark:text-slate-400",
  REVIEW:   "bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-300",
  PASS:     "bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-400",
  FAIL:     "bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-400",
};

function CertBadge({ label }) {
  const cls = CERT_STYLES[label] || "bg-slate-100 text-slate-500";
  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded text-[11px] font-semibold ${cls}`}>
      {label || "—"}
    </span>
  );
}

// ── Severity badge ─────────────────────────────────────────────────────────

const SEV_STYLES = {
  CRITICAL: "bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-400 ring-1 ring-red-300",
  ERROR:    "bg-orange-100 text-orange-700 dark:bg-orange-900/40 dark:text-orange-300",
  WARN:     "bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-300",
  INFO:     "bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-300",
};

function SevBadge({ sev }) {
  const cls = SEV_STYLES[sev] || "bg-slate-100 text-slate-500";
  return (
    <span className={`inline-flex px-1.5 py-0.5 rounded text-[10px] font-bold ${cls}`}>
      {sev}
    </span>
  );
}

// ── Domain pill ────────────────────────────────────────────────────────────

const DOMAIN_COLORS = {
  mf:     "bg-indigo-100 text-indigo-700 dark:bg-indigo-900/30 dark:text-indigo-300",
  equity: "bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-300",
  all:    "bg-slate-100 text-slate-600 dark:bg-slate-700 dark:text-slate-300",
};

function DomainPill({ domain }) {
  return (
    <span className={`inline-flex px-1.5 py-0.5 rounded text-[10px] font-semibold uppercase ${DOMAIN_COLORS[domain] || DOMAIN_COLORS.all}`}>
      {domain}
    </span>
  );
}

// ── Score progress bar ─────────────────────────────────────────────────────

function ScoreBar({ value, type = "quality" }) {
  if (value == null) return <div className="h-1.5 bg-slate-100 rounded-full" />;
  const pct = Math.min(100, Math.max(0, value));
  const color =
    value >= (type === "confidence" ? 98 : 99)  ? "bg-emerald-500" :
    value >= (type === "confidence" ? 95 : 95)  ? "bg-amber-500" :
    "bg-red-500";
  return (
    <div className="h-1.5 bg-slate-100 dark:bg-slate-700 rounded-full overflow-hidden">
      <div className={`h-full rounded-full transition-all ${color}`} style={{ width: `${pct}%` }} />
    </div>
  );
}

// ── KPI card ──────────────────────────────────────────────────────────────

function KpiCard({ label, value, sub, icon: Icon, colorClass, border }) {
  return (
    <div className={`rounded-lg border p-4 flex flex-col gap-1 ${border || "border-slate-200 dark:border-slate-700"} bg-white dark:bg-slate-900`}>
      <div className="flex items-center justify-between">
        <span className="text-[11px] text-slate-500 dark:text-slate-400 font-medium uppercase tracking-wide">
          {label}
        </span>
        {Icon && <Icon className={`w-4 h-4 ${colorClass || "text-slate-400"}`} />}
      </div>
      <div className={`text-2xl font-bold tabular-nums ${colorClass || "text-slate-900 dark:text-slate-100"}`}>
        {value}
      </div>
      {sub && <div className="text-[11px] text-slate-400">{sub}</div>}
    </div>
  );
}

// ── Executive Summary ─────────────────────────────────────────────────────

function ExecutiveSummary({ quality, certified, gate, exceptions }) {
  const latest = quality?.[0] || {};
  const latestMf = quality?.find(q => q.domain === "mf") || {};
  const latestEq = quality?.find(q => q.domain === "equity") || {};

  const openCritical = exceptions?.filter(e => !e.resolved && e.outcome === "FAIL").length || 0;
  const inReview     = exceptions?.filter(e => !e.resolved && e.outcome === "REVIEW").length || 0;
  const certCount    = certified?.length || 0;
  const gatePass     = gate?.filter(g => g.gate_decision === "PASS").length || 0;
  const gateFail     = gate?.filter(g => g.gate_decision === "FAIL").length || 0;

  const overallScore = latest.overall_score;

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold text-slate-700 dark:text-slate-300">Executive Summary</h2>
        <span className="text-[11px] text-slate-400">{fmtDate(latest.target_date) || "No data"}</span>
      </div>

      {/* Top KPI row */}
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3">
        <KpiCard
          label="Overall Quality"
          value={fmtScore(overallScore)}
          sub={latest.certification || "—"}
          icon={overallScore >= 99 ? ShieldCheck : overallScore >= 95 ? ShieldAlert : ShieldX}
          colorClass={scoreColor(overallScore)}
          border={overallScore >= 99
            ? "border-emerald-200 dark:border-emerald-800"
            : overallScore >= 95
              ? "border-amber-200 dark:border-amber-800"
              : "border-red-200 dark:border-red-800"}
        />
        <KpiCard
          label="Accuracy"
          value={fmtScore(latest.accuracy)}
          sub="vs golden source"
          icon={Activity}
          colorClass={scoreColor(latest.accuracy, "accuracy")}
        />
        <KpiCard
          label="Consistency"
          value={fmtScore(latest.consistency)}
          sub="cross-source agreement"
          icon={BarChart2}
          colorClass={scoreColor(latest.consistency)}
        />
        <KpiCard
          label="Completeness"
          value={fmtScore(latest.completeness)}
          sub="required fields"
          icon={CheckCircle2}
          colorClass={scoreColor(latest.completeness)}
        />
        <KpiCard
          label="Freshness"
          value={fmtScore(latest.freshness)}
          sub="within SLA"
          icon={Clock}
          colorClass={scoreColor(latest.freshness)}
        />
      </div>

      {/* Secondary KPI row */}
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3">
        <KpiCard
          label="Certified Datasets"
          value={certCount}
          sub="last 90 days"
          icon={ShieldCheck}
          colorClass={certCount > 0 ? "text-emerald-600 dark:text-emerald-400" : "text-slate-400"}
        />
        <KpiCard
          label="Open Critical Issues"
          value={openCritical}
          sub="unresolved FAILs"
          icon={XCircle}
          colorClass={openCritical > 0 ? "text-red-600 dark:text-red-400" : "text-emerald-600 dark:text-emerald-400"}
          border={openCritical > 1 ? "border-red-300 dark:border-red-800" : undefined}
        />
        <KpiCard
          label="In Review"
          value={inReview}
          sub="awaiting manual review"
          icon={Eye}
          colorClass={inReview > 0 ? "text-amber-600 dark:text-amber-400" : "text-emerald-600 dark:text-emerald-400"}
        />
        <KpiCard
          label="Gate PASS"
          value={gatePass}
          sub="recent decisions"
          icon={CheckCircle2}
          colorClass="text-emerald-600 dark:text-emerald-400"
        />
        <KpiCard
          label="Gate FAIL"
          value={gateFail}
          sub="recent decisions"
          icon={XCircle}
          colorClass={gateFail > 0 ? "text-red-600 dark:text-red-400" : "text-slate-400"}
        />
      </div>

      {/* Domain breakdown */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        {[
          { label: "Mutual Funds (MF)", data: latestMf },
          { label: "Equity",            data: latestEq },
        ].map(({ label, data }) => (
          <div key={label}
            className={`rounded-lg border p-4 bg-white dark:bg-slate-900 ${scoreBg(data.overall_score)}`}
          >
            <div className="flex items-center justify-between mb-2">
              <span className="text-sm font-medium text-slate-700 dark:text-slate-300">{label}</span>
              <div className="flex items-center gap-1.5">
                <CertBadge label={data.certification || "—"} />
                <CertBadge label={data.publish_decision || "—"} />
              </div>
            </div>
            <div className="grid grid-cols-4 gap-2 text-center">
              {[
                { k: "Quality",     v: data.overall_score },
                { k: "Accuracy",    v: data.accuracy },
                { k: "Consistency", v: data.consistency },
                { k: "Confidence",  v: data.confidence, type: "confidence" },
              ].map(({ k, v, type }) => (
                <div key={k}>
                  <div className={`text-base font-bold tabular-nums ${scoreColor(v, type)}`}>
                    {fmtScore(v)}
                  </div>
                  <div className="text-[10px] text-slate-400 mt-0.5">{k}</div>
                  <ScoreBar value={v} type={type} />
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Quality Metrics Table ─────────────────────────────────────────────────

function QualityMetricsTable({ quality }) {
  if (!quality?.length) {
    return <EmptyState message="No quality scores yet" />;
  }

  return (
    <div className="space-y-3">
      <h3 className="text-sm font-semibold text-slate-700 dark:text-slate-300">Quality Score History</h3>
      <div className="overflow-x-auto rounded-lg border border-slate-200 dark:border-slate-700">
        <table className="w-full text-xs">
          <thead>
            <tr className="bg-slate-50 dark:bg-slate-800/50 text-slate-500 dark:text-slate-400 uppercase tracking-wide text-[10px]">
              <th className="px-3 py-2 text-left">Date</th>
              <th className="px-3 py-2 text-left">Domain</th>
              <th className="px-3 py-2 text-right">Overall</th>
              <th className="px-3 py-2 text-right">Accuracy</th>
              <th className="px-3 py-2 text-right">Consistency</th>
              <th className="px-3 py-2 text-right">Completeness</th>
              <th className="px-3 py-2 text-right">Freshness</th>
              <th className="px-3 py-2 text-right">Confidence</th>
              <th className="px-3 py-2 text-center">Certification</th>
              <th className="px-3 py-2 text-center">Decision</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
            {quality.map((r, i) => (
              <tr key={i} className="hover:bg-slate-50 dark:hover:bg-slate-800/40">
                <td className="px-3 py-2 font-mono text-slate-600 dark:text-slate-300">{fmtDate(r.target_date)}</td>
                <td className="px-3 py-2"><DomainPill domain={r.domain} /></td>
                <td className={`px-3 py-2 text-right font-semibold tabular-nums ${scoreColor(r.overall_score)}`}>
                  {fmtScore(r.overall_score)}
                </td>
                <td className={`px-3 py-2 text-right tabular-nums ${scoreColor(r.accuracy, "accuracy")}`}>
                  {fmtScore(r.accuracy)}
                </td>
                <td className={`px-3 py-2 text-right tabular-nums ${scoreColor(r.consistency)}`}>
                  {fmtScore(r.consistency)}
                </td>
                <td className={`px-3 py-2 text-right tabular-nums ${scoreColor(r.completeness)}`}>
                  {fmtScore(r.completeness)}
                </td>
                <td className={`px-3 py-2 text-right tabular-nums ${scoreColor(r.freshness)}`}>
                  {fmtScore(r.freshness)}
                </td>
                <td className={`px-3 py-2 text-right tabular-nums ${scoreColor(r.confidence, "confidence")}`}>
                  {fmtScore(r.confidence)}
                </td>
                <td className="px-3 py-2 text-center">
                  <CertBadge label={r.certification} />
                </td>
                <td className="px-3 py-2 text-center">
                  <CertBadge label={r.publish_decision} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ── Publish Gate table ────────────────────────────────────────────────────

function PublishGateTable({ gate }) {
  if (!gate?.length) return <EmptyState message="No gate decisions yet" />;

  return (
    <div className="space-y-3">
      <h3 className="text-sm font-semibold text-slate-700 dark:text-slate-300">Publish Gate Decisions</h3>
      <div className="overflow-x-auto rounded-lg border border-slate-200 dark:border-slate-700">
        <table className="w-full text-xs">
          <thead>
            <tr className="bg-slate-50 dark:bg-slate-800/50 text-slate-500 dark:text-slate-400 uppercase tracking-wide text-[10px]">
              <th className="px-3 py-2 text-left">Date</th>
              <th className="px-3 py-2 text-left">Domain</th>
              <th className="px-3 py-2 text-right">Score</th>
              <th className="px-3 py-2 text-right">Confidence</th>
              <th className="px-3 py-2 text-center">Certification</th>
              <th className="px-3 py-2 text-right">Block Findings</th>
              <th className="px-3 py-2 text-center">Gate Decision</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
            {gate.map((r, i) => (
              <tr key={i} className="hover:bg-slate-50 dark:hover:bg-slate-800/40">
                <td className="px-3 py-2 font-mono text-slate-600 dark:text-slate-300">{fmtDate(r.target_date)}</td>
                <td className="px-3 py-2"><DomainPill domain={r.domain} /></td>
                <td className={`px-3 py-2 text-right font-semibold tabular-nums ${scoreColor(r.overall_score)}`}>
                  {fmtScore(r.overall_score)}
                </td>
                <td className={`px-3 py-2 text-right tabular-nums ${scoreColor(r.confidence_score, "confidence")}`}>
                  {fmtScore(r.confidence_score)}
                </td>
                <td className="px-3 py-2 text-center"><CertBadge label={r.certification} /></td>
                <td className={`px-3 py-2 text-right font-mono ${r.consistency_blocks > 0 ? "text-red-600 dark:text-red-400 font-bold" : "text-slate-500"}`}>
                  {r.consistency_blocks ?? 0}
                </td>
                <td className="px-3 py-2 text-center"><CertBadge label={r.gate_decision} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ── Consistency Runs ──────────────────────────────────────────────────────

function ConsistencyRunsTable({ runs }) {
  if (!runs?.length) return <EmptyState message="No consistency runs yet" />;

  return (
    <div className="space-y-3">
      <h3 className="text-sm font-semibold text-slate-700 dark:text-slate-300">Consistency Runs</h3>
      <div className="overflow-x-auto rounded-lg border border-slate-200 dark:border-slate-700">
        <table className="w-full text-xs">
          <thead>
            <tr className="bg-slate-50 dark:bg-slate-800/50 text-slate-500 dark:text-slate-400 uppercase tracking-wide text-[10px]">
              <th className="px-3 py-2 text-left">Date</th>
              <th className="px-3 py-2 text-left">Domain</th>
              <th className="px-3 py-2 text-center">Status</th>
              <th className="px-3 py-2 text-right">Rules Run</th>
              <th className="px-3 py-2 text-right">Rules Failed</th>
              <th className="px-3 py-2 text-right">Findings</th>
              <th className="px-3 py-2 text-center">Has BLOCK</th>
              <th className="px-3 py-2 text-left">Started</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
            {runs.map((r, i) => (
              <tr key={i} className="hover:bg-slate-50 dark:hover:bg-slate-800/40">
                <td className="px-3 py-2 font-mono text-slate-600 dark:text-slate-300">{fmtDate(r.target_date)}</td>
                <td className="px-3 py-2"><DomainPill domain={r.domain} /></td>
                <td className="px-3 py-2 text-center">
                  <CertBadge label={r.status === "DONE" ? "PASS" : r.status} />
                </td>
                <td className="px-3 py-2 text-right tabular-nums">{r.rules_run ?? "—"}</td>
                <td className={`px-3 py-2 text-right tabular-nums font-semibold ${
                  r.rules_failed > 0 ? "text-red-600 dark:text-red-400" : "text-emerald-600 dark:text-emerald-400"
                }`}>{r.rules_failed ?? 0}</td>
                <td className={`px-3 py-2 text-right tabular-nums ${
                  r.findings_count > 0 ? "text-amber-600 dark:text-amber-400" : "text-slate-400"
                }`}>{r.findings_count ?? 0}</td>
                <td className="px-3 py-2 text-center">
                  {r.has_block
                    ? <XCircle className="w-4 h-4 text-red-500 mx-auto" />
                    : <CheckCircle2 className="w-4 h-4 text-emerald-500 mx-auto" />}
                </td>
                <td className="px-3 py-2 text-slate-400">{relTime(r.started_at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ── Rule Failure Analytics ────────────────────────────────────────────────

function RuleFailureAnalytics({ findings }) {
  const counts = useMemo(() => {
    const map = {};
    (findings || []).forEach(f => {
      const key = f.rule_name || "unknown";
      if (!map[key]) map[key] = { rule: key, count: 0, critical: 0, domains: new Set() };
      map[key].count++;
      if (f.severity === "CRITICAL" || f.failure_class === "BLOCK") map[key].critical++;
      if (f.domain) map[key].domains.add(f.domain);
    });
    return Object.values(map)
      .map(r => ({ ...r, domains: [...r.domains] }))
      .sort((a, b) => b.count - a.count)
      .slice(0, 20);
  }, [findings]);

  const maxCount = counts[0]?.count || 1;

  if (!counts.length) return <EmptyState message="No rule failures — everything passing" />;

  return (
    <div className="space-y-3">
      <h3 className="text-sm font-semibold text-slate-700 dark:text-slate-300">
        Top Failing Rules ({counts.length} total)
      </h3>
      <div className="space-y-1.5">
        {counts.map((r) => (
          <div key={r.rule} className="flex items-center gap-3 rounded-md px-3 py-2 bg-white dark:bg-slate-900 border border-slate-100 dark:border-slate-800">
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2 mb-1">
                <span className="text-xs font-mono font-medium text-slate-700 dark:text-slate-300 truncate">
                  {r.rule}
                </span>
                {r.critical > 0 && (
                  <span className="text-[10px] font-bold text-red-600 dark:text-red-400 shrink-0">
                    {r.critical} BLOCK
                  </span>
                )}
                {r.domains.map(d => <DomainPill key={d} domain={d} />)}
              </div>
              <div className="flex items-center gap-2">
                <div className="flex-1 h-1.5 bg-slate-100 dark:bg-slate-700 rounded-full overflow-hidden">
                  <div
                    className={`h-full rounded-full ${r.critical > 0 ? "bg-red-500" : "bg-amber-500"}`}
                    style={{ width: `${(r.count / maxCount) * 100}%` }}
                  />
                </div>
                <span className={`text-[11px] font-bold tabular-nums shrink-0 ${
                  r.critical > 0 ? "text-red-600 dark:text-red-400" : "text-amber-600 dark:text-amber-400"
                }`}>{r.count}</span>
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Consistency Findings Table ────────────────────────────────────────────

function ConsistencyFindingsTable({ findings }) {
  const [expanded, setExpanded] = useState(null);
  const [sevFilter, setSevFilter] = useState("ALL");

  const filtered = useMemo(() => {
    if (sevFilter === "ALL") return findings || [];
    return (findings || []).filter(f => f.severity === sevFilter);
  }, [findings, sevFilter]);

  if (!findings?.length) return <EmptyState message="No consistency findings" />;

  const severities = ["ALL", "CRITICAL", "ERROR", "WARN", "INFO"];

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between flex-wrap gap-2">
        <h3 className="text-sm font-semibold text-slate-700 dark:text-slate-300">
          Consistency Findings ({filtered.length})
        </h3>
        <div className="flex items-center gap-1">
          {severities.map(s => (
            <button
              key={s}
              onClick={() => setSevFilter(s)}
              className={`px-2 py-0.5 text-[10px] font-bold rounded transition-colors ${
                sevFilter === s
                  ? "bg-indigo-600 text-white"
                  : "bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-400 hover:bg-slate-200 dark:hover:bg-slate-700"
              }`}
            >
              {s}
            </button>
          ))}
        </div>
      </div>

      <div className="overflow-x-auto rounded-lg border border-slate-200 dark:border-slate-700">
        <table className="w-full text-xs">
          <thead>
            <tr className="bg-slate-50 dark:bg-slate-800/50 text-slate-500 dark:text-slate-400 uppercase tracking-wide text-[10px]">
              <th className="px-3 py-2 text-left">Date</th>
              <th className="px-3 py-2 text-left">Domain</th>
              <th className="px-3 py-2 text-left">Dimension</th>
              <th className="px-3 py-2 text-left">Rule</th>
              <th className="px-3 py-2 text-center">Severity</th>
              <th className="px-3 py-2 text-left">Entity</th>
              <th className="px-3 py-2 text-left">Field</th>
              <th className="px-3 py-2 text-right">Deviation</th>
              <th className="px-3 py-2 w-6"></th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
            {filtered.slice(0, 100).map((f, i) => (
              <React.Fragment key={i}>
                <tr
                  className={`hover:bg-slate-50 dark:hover:bg-slate-800/40 cursor-pointer ${
                    f.failure_class === "BLOCK" ? "bg-red-50/30 dark:bg-red-900/10" : ""
                  }`}
                  onClick={() => setExpanded(expanded === i ? null : i)}
                >
                  <td className="px-3 py-2 font-mono text-slate-500">{fmtDate(f.target_date)}</td>
                  <td className="px-3 py-2"><DomainPill domain={f.domain} /></td>
                  <td className="px-3 py-2 text-slate-500 text-[10px]">{f.dimension}</td>
                  <td className="px-3 py-2 font-mono font-medium text-slate-700 dark:text-slate-300 max-w-[160px] truncate">{f.rule_name}</td>
                  <td className="px-3 py-2 text-center"><SevBadge sev={f.severity} /></td>
                  <td className="px-3 py-2 text-slate-500 max-w-[100px] truncate">{f.entity_id || "—"}</td>
                  <td className="px-3 py-2 text-slate-500 max-w-[80px] truncate">{f.field_name || "—"}</td>
                  <td className={`px-3 py-2 text-right tabular-nums font-mono ${
                    f.deviation_pct != null && Math.abs(f.deviation_pct) > 5
                      ? "text-red-600 dark:text-red-400 font-bold"
                      : "text-slate-500"
                  }`}>
                    {f.deviation_pct != null ? `${Number(f.deviation_pct).toFixed(2)}%` : "—"}
                  </td>
                  <td className="px-3 py-2 text-slate-400">
                    {expanded === i ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
                  </td>
                </tr>
                {expanded === i && (
                  <tr className="bg-slate-50 dark:bg-slate-900/50">
                    <td colSpan={9} className="px-4 py-3">
                      <div className="grid grid-cols-2 gap-4 text-[11px]">
                        <div className="space-y-1.5">
                          <div className="font-semibold text-slate-500 uppercase tracking-wide text-[10px]">Source A ({f.source_a})</div>
                          <div className="font-mono bg-white dark:bg-slate-800 rounded p-2 text-slate-700 dark:text-slate-300 break-all">{f.value_a ?? "—"}</div>
                        </div>
                        <div className="space-y-1.5">
                          <div className="font-semibold text-slate-500 uppercase tracking-wide text-[10px]">Source B ({f.source_b})</div>
                          <div className="font-mono bg-white dark:bg-slate-800 rounded p-2 text-slate-700 dark:text-slate-300 break-all">{f.value_b ?? "—"}</div>
                        </div>
                        {f.message && (
                          <div className="col-span-2 text-slate-600 dark:text-slate-400 italic">{f.message}</div>
                        )}
                      </div>
                    </td>
                  </tr>
                )}
              </React.Fragment>
            ))}
          </tbody>
        </table>
        {filtered.length > 100 && (
          <div className="px-4 py-2 text-[11px] text-slate-400 bg-slate-50 dark:bg-slate-800/50 border-t border-slate-100 dark:border-slate-700">
            Showing 100 of {filtered.length} findings. Use severity filter to narrow.
          </div>
        )}
      </div>
    </div>
  );
}

// ── Exception Queue ───────────────────────────────────────────────────────

const RESOLVE_ACTIONS = [
  { id: "APPROVE",   label: "Approve",  icon: ThumbsUp,       cls: "text-emerald-600 dark:text-emerald-400 hover:bg-emerald-50 dark:hover:bg-emerald-900/30" },
  { id: "REJECT",    label: "Reject",   icon: ThumbsDown,     cls: "text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-900/30" },
  { id: "OVERRIDE",  label: "Override", icon: SkipForward,    cls: "text-amber-600 dark:text-amber-400 hover:bg-amber-50 dark:hover:bg-amber-900/30" },
  { id: "ESCALATE",  label: "Escalate", icon: ArrowUpCircle,  cls: "text-indigo-600 dark:text-indigo-400 hover:bg-indigo-50 dark:hover:bg-indigo-900/30" },
];

function ExceptionQueueTable({ exceptions, onResolved }) {
  const [acting, setActing]   = useState(null); // queue_id being actioned
  const [note, setNote]       = useState("");
  const [showResolved, setShowResolved] = useState(false);

  const visible = showResolved ? exceptions : (exceptions || []).filter(e => !e.resolved);

  async function doResolve(queueId, action) {
    setActing(queueId);
    try {
      await axios.patch(
        `${API}/api/admin/nidp/quality/exceptions/${queueId}`,
        null,
        { withCredentials: true, params: { action, resolution_note: note } },
      );
      toast.success(`Exception ${action.toLowerCase()}d`);
      setNote("");
      onResolved?.();
    } catch (e) {
      toast.error(e?.response?.data?.detail || e.message);
    } finally {
      setActing(null);
    }
  }

  if (!exceptions?.length) {
    return (
      <div className="text-center py-8 text-slate-400 text-sm">
        <CheckCircle2 className="w-8 h-8 mx-auto mb-2 text-emerald-500" />
        No open exceptions — quality gate passing
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between flex-wrap gap-2">
        <h3 className="text-sm font-semibold text-slate-700 dark:text-slate-300">
          Exception Queue
          <span className="ml-2 text-[11px] font-normal text-slate-400">
            {(exceptions || []).filter(e => !e.resolved).length} open
            · {(exceptions || []).filter(e => e.resolved).length} resolved
          </span>
        </h3>
        <label className="flex items-center gap-1.5 text-[11px] text-slate-500 cursor-pointer">
          <input
            type="checkbox"
            checked={showResolved}
            onChange={e => setShowResolved(e.target.checked)}
            className="rounded"
          />
          Show resolved
        </label>
      </div>

      <div className="space-y-2">
        {visible.map((e) => (
          <div
            key={e.queue_id || e.target_date + e.domain}
            className={`rounded-lg border p-3 bg-white dark:bg-slate-900 ${
              e.resolved
                ? "border-slate-200 dark:border-slate-700 opacity-70"
                : e.outcome === "FAIL" || e.block_findings > 0
                  ? "border-red-200 dark:border-red-800"
                  : "border-amber-200 dark:border-amber-800"
            }`}
          >
            {/* Header row */}
            <div className="flex items-start justify-between gap-2 flex-wrap">
              <div className="flex items-center gap-2 flex-wrap">
                <CertBadge label={e.outcome} />
                <DomainPill domain={e.domain} />
                <span className="text-xs font-mono text-slate-500">{fmtDate(e.target_date)}</span>
                {e.block_findings > 0 && (
                  <span className="text-[10px] font-bold text-red-600 dark:text-red-400">
                    {e.block_findings} BLOCK
                  </span>
                )}
              </div>
              <div className="text-xs text-slate-400">
                {e.resolved
                  ? <span className="flex items-center gap-1 text-emerald-600 dark:text-emerald-400">
                      <CheckCircle2 className="w-3 h-3" /> Resolved {relTime(e.resolved_at)}
                    </span>
                  : <span className="text-amber-600 dark:text-amber-400">Open · {relTime(e.created_at)}</span>}
              </div>
            </div>

            {/* Reason */}
            <div className="mt-2 text-xs text-slate-600 dark:text-slate-400">{e.reason}</div>

            {/* Score row */}
            <div className="mt-1.5 flex items-center gap-4 text-[11px] text-slate-400 flex-wrap">
              <span>Quality: <span className={`font-semibold ${scoreColor(e.quality_score)}`}>{fmtScore(e.quality_score)}</span></span>
              <span>Confidence: <span className={`font-semibold ${scoreColor(e.confidence, "confidence")}`}>{fmtScore(e.confidence)}</span></span>
              <span>Block findings: <span className={`font-semibold ${e.block_findings > 0 ? "text-red-600 dark:text-red-400" : "text-slate-400"}`}>{e.block_findings ?? 0}</span></span>
            </div>

            {/* Resolution note if already resolved */}
            {e.resolution_note && (
              <div className="mt-1.5 text-[11px] text-slate-500 italic border-t border-slate-100 dark:border-slate-800 pt-1.5">
                {e.resolution_note}
              </div>
            )}

            {/* Action row — only for unresolved items */}
            {!e.resolved && (
              <div className="mt-3 pt-2 border-t border-slate-100 dark:border-slate-800 space-y-2">
                <input
                  type="text"
                  placeholder="Resolution note (optional)…"
                  value={note}
                  onChange={ev => setNote(ev.target.value)}
                  className="w-full text-xs px-2 py-1.5 rounded border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800 text-slate-700 dark:text-slate-300 placeholder:text-slate-400 focus:outline-none focus:ring-1 focus:ring-indigo-400"
                />
                <div className="flex items-center gap-1.5 flex-wrap">
                  {RESOLVE_ACTIONS.map(({ id, label, icon: Icon, cls }) => (
                    <button
                      key={id}
                      disabled={acting === e.queue_id}
                      onClick={() => doResolve(e.queue_id, id)}
                      className={`inline-flex items-center gap-1 px-2.5 py-1 rounded text-[11px] font-semibold border border-transparent transition-colors disabled:opacity-50 ${cls}`}
                    >
                      {acting === e.queue_id
                        ? <Loader2 className="w-3 h-3 animate-spin" />
                        : <Icon className="w-3 h-3" />}
                      {label}
                    </button>
                  ))}
                </div>
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Quarantine Log ────────────────────────────────────────────────────────

function QuarantineLog({ quarantine }) {
  if (!quarantine?.length) {
    return (
      <div className="text-center py-6 text-slate-400 text-sm">
        <CheckCircle2 className="w-6 h-6 mx-auto mb-1 text-emerald-500" />
        No quarantined dates — no FAIL outcomes recorded
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2">
        <Lock className="w-4 h-4 text-red-500" />
        <h3 className="text-sm font-semibold text-slate-700 dark:text-slate-300">
          Quarantine Log
          <span className="ml-2 text-[11px] font-normal text-slate-400">{quarantine.length} condemned date(s)</span>
        </h3>
      </div>
      <div className="overflow-x-auto rounded-lg border border-red-200 dark:border-red-900">
        <table className="w-full text-xs">
          <thead>
            <tr className="bg-red-50 dark:bg-red-900/20 text-red-700 dark:text-red-400 uppercase tracking-wide text-[10px]">
              <th className="px-3 py-2 text-left">Date</th>
              <th className="px-3 py-2 text-left">Domain</th>
              <th className="px-3 py-2 text-right">Quality</th>
              <th className="px-3 py-2 text-right">Confidence</th>
              <th className="px-3 py-2 text-right">Blocks</th>
              <th className="px-3 py-2 text-left">Reason</th>
              <th className="px-3 py-2 text-left">Quarantined</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-red-100 dark:divide-red-900/30">
            {quarantine.map((q) => (
              <tr key={q.quarantine_id} className="hover:bg-red-50/50 dark:hover:bg-red-900/10">
                <td className="px-3 py-2 font-mono text-slate-600 dark:text-slate-300">{fmtDate(q.target_date)}</td>
                <td className="px-3 py-2"><DomainPill domain={q.domain} /></td>
                <td className={`px-3 py-2 text-right font-semibold tabular-nums ${scoreColor(q.quality_score)}`}>
                  {fmtScore(q.quality_score)}
                </td>
                <td className={`px-3 py-2 text-right tabular-nums ${scoreColor(q.confidence, "confidence")}`}>
                  {fmtScore(q.confidence)}
                </td>
                <td className="px-3 py-2 text-right font-bold text-red-600 dark:text-red-400 tabular-nums">
                  {q.block_findings}
                </td>
                <td className="px-3 py-2 text-slate-500 text-[11px] max-w-[240px] truncate" title={q.reason}>
                  {q.reason}
                </td>
                <td className="px-3 py-2 text-slate-400 text-[11px]">{relTime(q.quarantined_at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ── Empty state ───────────────────────────────────────────────────────────

function EmptyState({ message }) {
  return (
    <div className="flex flex-col items-center justify-center py-10 text-slate-400 gap-2">
      <Info className="w-6 h-6" />
      <span className="text-sm">{message}</span>
    </div>
  );
}

// ── Error card ────────────────────────────────────────────────────────────

function ErrorCard({ message }) {
  return (
    <div className="rounded-lg border border-red-200 dark:border-red-800 bg-red-50 dark:bg-red-900/20 px-4 py-3 text-sm text-red-700 dark:text-red-300 flex items-start gap-2">
      <AlertTriangle className="w-4 h-4 shrink-0 mt-0.5" />
      <span>{message}</span>
    </div>
  );
}

// ── SLA Monitor ───────────────────────────────────────────────────────────

const SLA_TARGETS = [
  { label: "Accuracy",         target: 99.99, key: "accuracy",     type: "accuracy" },
  { label: "Consistency",      target: 99.99, key: "consistency",  type: "quality" },
  { label: "Completeness",     target: 99.90, key: "completeness", type: "quality" },
  { label: "Freshness",        target: 99.90, key: "freshness",    type: "quality" },
  { label: "Overall Quality",  target: 99.00, key: "overall_score",type: "quality" },
];

function SlaMonitor({ quality }) {
  const latest = quality?.[0] || {};
  return (
    <div className="space-y-3">
      <h3 className="text-sm font-semibold text-slate-700 dark:text-slate-300">SLA Monitor</h3>
      <div className="rounded-lg border border-slate-200 dark:border-slate-700 overflow-hidden">
        <table className="w-full text-xs">
          <thead>
            <tr className="bg-slate-50 dark:bg-slate-800/50 text-slate-500 dark:text-slate-400 uppercase tracking-wide text-[10px]">
              <th className="px-4 py-2 text-left">SLA</th>
              <th className="px-4 py-2 text-right">Target</th>
              <th className="px-4 py-2 text-right">Current</th>
              <th className="px-4 py-2 text-left w-40">Status</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
            {SLA_TARGETS.map(s => {
              const current = latest[s.key];
              const met = current != null && current >= s.target;
              const close = current != null && current >= s.target * 0.9995;
              return (
                <tr key={s.key} className="hover:bg-slate-50 dark:hover:bg-slate-800/40">
                  <td className="px-4 py-2 font-medium text-slate-700 dark:text-slate-300">{s.label}</td>
                  <td className="px-4 py-2 text-right tabular-nums text-slate-500">{s.target.toFixed(2)}%</td>
                  <td className={`px-4 py-2 text-right tabular-nums font-semibold ${scoreColor(current, s.type)}`}>
                    {current != null ? `${Number(current).toFixed(3)}%` : "—"}
                  </td>
                  <td className="px-4 py-2">
                    {current == null ? (
                      <span className="text-slate-400">No data</span>
                    ) : met ? (
                      <span className="flex items-center gap-1 text-emerald-600 dark:text-emerald-400">
                        <CheckCircle2 className="w-3 h-3" /> Met
                      </span>
                    ) : close ? (
                      <span className="flex items-center gap-1 text-amber-600 dark:text-amber-400">
                        <AlertTriangle className="w-3 h-3" /> Warning
                      </span>
                    ) : (
                      <span className="flex items-center gap-1 text-red-600 dark:text-red-400">
                        <XCircle className="w-3 h-3" /> Breach
                      </span>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <p className="text-[11px] text-slate-400">Based on latest available quality score.</p>
    </div>
  );
}

// ── Confidence Score Distribution ─────────────────────────────────────────

const CONF_TIERS = [
  { label: "Platinum (≥99)",   min: 99,  max: 100,  color: "bg-purple-500", badge: "Platinum" },
  { label: "Gold (98–99)",     min: 98,  max: 99,   color: "bg-yellow-500", badge: "Gold" },
  { label: "Silver (95–98)",   min: 95,  max: 98,   color: "bg-slate-400",  badge: "Silver" },
  { label: "Review (<95)",     min: 0,   max: 95,   color: "bg-red-500",    badge: "Review" },
];

function ConfidenceDistribution({ quality }) {
  const scored = (quality || []).filter(q => q.confidence != null);
  if (!scored.length) return <EmptyState message="No confidence scores yet" />;

  const tiers = CONF_TIERS.map(t => ({
    ...t,
    count: scored.filter(q => q.confidence >= t.min && q.confidence < t.max).length,
  }));
  const total = scored.length;

  return (
    <div className="space-y-3">
      <h3 className="text-sm font-semibold text-slate-700 dark:text-slate-300">Confidence Score Distribution</h3>
      <div className="space-y-2">
        {tiers.map(t => (
          <div key={t.badge} className="flex items-center gap-3">
            <div className="w-32 text-[11px] text-slate-600 dark:text-slate-400 shrink-0">{t.label}</div>
            <div className="flex-1 h-5 bg-slate-100 dark:bg-slate-700 rounded overflow-hidden">
              <div
                className={`h-full ${t.color} transition-all`}
                style={{ width: total > 0 ? `${(t.count / total) * 100}%` : "0%" }}
              />
            </div>
            <div className="w-16 text-right text-[11px] font-mono text-slate-500 shrink-0">
              {t.count} ({total > 0 ? Math.round((t.count / total) * 100) : 0}%)
            </div>
          </div>
        ))}
      </div>
      <p className="text-[11px] text-slate-400">Across {total} quality score records.</p>
    </div>
  );
}

// ── Main Component ────────────────────────────────────────────────────────

export default function NidpQualityDashboard() {
  const [summary,     setSummary]     = useState(null);
  const [consistency, setConsistency] = useState(null);
  const [quarantine,  setQuarantine]  = useState([]);
  const [loading,     setLoading]     = useState(true);
  const [error,       setError]       = useState(null);
  const [subTab,      setSubTab]      = useState("overview");
  const [domainFilter, setDomainFilter] = useState("all");

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const domain = domainFilter === "all" ? undefined : domainFilter;
      const params = domain ? { domain } : {};

      // summary + consistency are load-bearing; quarantine is best-effort
      const [sumR, conR] = await Promise.all([
        axios.get(`${API}/api/admin/nidp/quality/summary`,     { withCredentials: true, params }),
        axios.get(`${API}/api/admin/nidp/quality/consistency`, { withCredentials: true, params }),
      ]);
      setSummary(sumR.data);
      setConsistency(conR.data);

      // quarantine endpoint may not exist on older Query API deployments — swallow 404
      try {
        const quarR = await axios.get(`${API}/api/admin/nidp/quality/quarantine`,
          { withCredentials: true, params });
        setQuarantine(quarR.data?.quarantine || []);
      } catch {
        setQuarantine([]);
      }
    } catch (e) {
      const msg = e?.response?.data?.detail || e.message;
      setError(msg);
      toast.error(`Quality API error: ${msg}`);
    } finally {
      setLoading(false);
    }
  }, [domainFilter]);

  useEffect(() => { load(); }, [load]);

  const { quality = [], certified = [], gate = [], exceptions = [] } = summary || {};
  const { runs = [], findings = [] } = consistency || {};

  const openExceptions = exceptions.filter(e => !e.resolved).length;
  const quarantineCount = quarantine.length;

  const anySummaryError = summary?.errors &&
    Object.values(summary.errors).some(Boolean);

  // Sub-tabs with live badge counts
  const SUB_TABS = [
    { id: "overview",     label: "Overview" },
    { id: "quality",      label: "Quality Metrics" },
    { id: "consistency",  label: "Consistency" },
    { id: "exceptions",   label: "Exceptions", badge: openExceptions || null, badgeCls: "bg-amber-500" },
    { id: "quarantine",   label: "Quarantine",  badge: quarantineCount || null, badgeCls: "bg-red-500" },
    { id: "gate",         label: "Publish Gate" },
    { id: "sla",          label: "SLA" },
  ];

  return (
    <div className="space-y-4">
      {/* Toolbar */}
      <div className="flex items-center justify-between flex-wrap gap-2">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-[11px] text-slate-500 font-medium">Domain:</span>
          {["all", "mf", "equity"].map(d => (
            <button
              key={d}
              onClick={() => setDomainFilter(d)}
              className={`px-2.5 py-1 text-[11px] font-semibold rounded-md transition-colors uppercase ${
                domainFilter === d
                  ? "bg-indigo-600 text-white"
                  : "bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-400 hover:bg-slate-200 dark:hover:bg-slate-700"
              }`}
            >
              {d}
            </button>
          ))}
        </div>
        <button
          onClick={load}
          disabled={loading}
          className="flex items-center gap-1.5 px-3 py-1.5 text-xs rounded-md bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-400 hover:bg-slate-200 dark:hover:bg-slate-700 disabled:opacity-50 transition-colors"
        >
          {loading ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <RefreshCw className="w-3.5 h-3.5" />}
          Refresh
        </button>
      </div>

      {/* Sub-tabs */}
      <div className="flex items-center gap-1 flex-wrap">
        {SUB_TABS.map(t => (
          <button
            key={t.id}
            onClick={() => setSubTab(t.id)}
            className={`relative px-3 py-1.5 text-xs font-medium rounded-md transition-colors whitespace-nowrap ${
              subTab === t.id
                ? "bg-indigo-600 text-white shadow-sm"
                : "text-slate-600 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-800"
            }`}
          >
            {t.label}
            {t.badge != null && (
              <span className={`ml-1.5 inline-flex items-center justify-center min-w-[16px] h-4 px-1 rounded-full text-[10px] font-bold text-white ${t.badgeCls}`}>
                {t.badge}
              </span>
            )}
          </button>
        ))}
      </div>

      {/* Error banner */}
      {error && <ErrorCard message={error} />}
      {!error && anySummaryError && (
        <ErrorCard message={`Partial data: ${Object.entries(summary.errors).filter(([,v]) => v).map(([k, v]) => `${k}: ${v}`).join("; ")}`} />
      )}

      {/* Loading */}
      {loading && (
        <div className="flex items-center justify-center py-16">
          <Loader2 className="w-6 h-6 animate-spin text-indigo-500" />
        </div>
      )}

      {/* Content */}
      {!loading && !error && (
        <div className="space-y-6">
          {subTab === "overview" && (
            <>
              <ExecutiveSummary quality={quality} certified={certified} gate={gate} exceptions={exceptions} />
              <ConfidenceDistribution quality={quality} />
              <RuleFailureAnalytics findings={findings} />
            </>
          )}

          {subTab === "quality" && (
            <>
              <QualityMetricsTable quality={quality} />
              <SlaMonitor quality={quality} />
            </>
          )}

          {subTab === "consistency" && (
            <>
              <ConsistencyRunsTable runs={runs} />
              <ConsistencyFindingsTable findings={findings} />
            </>
          )}

          {subTab === "exceptions" && (
            <ExceptionQueueTable
              exceptions={exceptions}
              onResolved={load}
            />
          )}

          {subTab === "quarantine" && (
            <QuarantineLog quarantine={quarantine} />
          )}

          {subTab === "gate" && (
            <PublishGateTable gate={gate} />
          )}

          {subTab === "sla" && (
            <SlaMonitor quality={quality} />
          )}
        </div>
      )}
    </div>
  );
}
