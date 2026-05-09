/**
 * NIDP Certification Panel
 *
 * - 90-day calendar tracker (day-by-day pass/fail cells)
 * - Certification status table per domain
 * - Consecutive stable days counter
 * - Certification readiness assessment
 */
import React, { useEffect, useState, useCallback, useMemo } from "react";
import axios from "axios";
import {
  Loader2, RefreshCw, AlertTriangle, ShieldCheck, ShieldAlert,
  CheckCircle2, XCircle, Award,
} from "lucide-react";
import { toast } from "sonner";

const API = process.env.REACT_APP_BACKEND_URL;

const fmtScore = (v) => (v == null ? "—" : Number(v).toFixed(2));
const fmtDate  = (s) => (!s ? "—" : s.length > 10 ? s.slice(0, 10) : s);

// Certification tier order for sorting
const CERT_ORDER = { Platinum: 4, Gold: 3, Silver: 2, Bronze: 1, "Not Certified": 0, null: 0 };

const CERT_STYLES = {
  Platinum: {
    badge: "bg-purple-100 text-purple-700 dark:bg-purple-900/40 dark:text-purple-300 ring-1 ring-purple-300 dark:ring-purple-700",
    dot:   "bg-purple-500",
    row:   "bg-purple-50/30 dark:bg-purple-900/10",
  },
  Gold: {
    badge: "bg-yellow-100 text-yellow-700 dark:bg-yellow-900/40 dark:text-yellow-300 ring-1 ring-yellow-300 dark:ring-yellow-700",
    dot:   "bg-yellow-500",
    row:   "bg-yellow-50/30 dark:bg-yellow-900/10",
  },
  Silver: {
    badge: "bg-slate-100 text-slate-600 dark:bg-slate-700 dark:text-slate-300 ring-1 ring-slate-300",
    dot:   "bg-slate-400",
    row:   "",
  },
  Bronze: {
    badge: "bg-orange-100 text-orange-700 dark:bg-orange-900/40 dark:text-orange-300",
    dot:   "bg-orange-400",
    row:   "",
  },
  "Not Certified": {
    badge: "bg-slate-100 text-slate-500 dark:bg-slate-800 dark:text-slate-400",
    dot:   "bg-slate-300",
    row:   "",
  },
};

function certStyle(cert) {
  return CERT_STYLES[cert] || CERT_STYLES["Not Certified"];
}

function CertBadge({ label }) {
  const cls = certStyle(label).badge;
  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded text-[11px] font-semibold ${cls}`}>
      {label || "—"}
    </span>
  );
}

// ── 90-day Calendar ───────────────────────────────────────────────────────

function buildCalendar(certified, gate, days = 90) {
  const today = new Date();
  const calendar = [];
  for (let i = days - 1; i >= 0; i--) {
    const d = new Date(today);
    d.setDate(today.getDate() - i);
    const iso = d.toISOString().slice(0, 10);
    calendar.push({ date: iso, isToday: i === 0 });
  }

  const certDates = new Set((certified || []).map(c => c.target_date));
  const gateLookup = {};
  (gate || []).forEach(g => {
    const key = `${g.target_date}::${g.domain}`;
    gateLookup[key] = g.gate_decision;
  });

  return calendar.map(c => ({
    ...c,
    certified: certDates.has(c.date),
    // gate pass/fail if no certification record — approximate from gate decisions
    gateDecisions: Object.entries(gateLookup)
      .filter(([k]) => k.startsWith(c.date))
      .map(([, v]) => v),
  }));
}

function CalendarCell({ day }) {
  const allPass  = day.gateDecisions.length > 0 && day.gateDecisions.every(d => d === "PASS");
  const anyFail  = day.gateDecisions.some(d => d === "FAIL");
  const anyReview = day.gateDecisions.some(d => d === "REVIEW");
  const noData   = day.gateDecisions.length === 0;

  const bg =
    day.isToday     ? "ring-2 ring-indigo-500 ring-offset-1 ring-offset-white dark:ring-offset-slate-900 " :
    day.certified   ? "" : "";

  const fill =
    day.certified   ? "bg-emerald-500" :
    anyFail         ? "bg-red-400" :
    anyReview       ? "bg-amber-400" :
    allPass         ? "bg-emerald-300" :
    noData          ? "bg-slate-200 dark:bg-slate-700" :
    "bg-slate-300 dark:bg-slate-600";

  const tip =
    `${day.date}${day.isToday ? " (today)" : ""}` +
    (day.certified ? " · Certified" : "") +
    (day.gateDecisions.length ? ` · ${day.gateDecisions.join(", ")}` : " · No data");

  return (
    <div title={tip} className={`w-4 h-4 rounded-sm ${fill} ${bg} transition-colors`} />
  );
}

function CertCalendar({ certified, gate, domain }) {
  const calendar = useMemo(() => buildCalendar(certified, gate, 90), [certified, gate]);

  // Group by week
  const weeks = [];
  for (let i = 0; i < calendar.length; i += 7) {
    weeks.push(calendar.slice(i, i + 7));
  }

  const certCount = calendar.filter(d => d.certified).length;
  const passCount = calendar.filter(d => d.gateDecisions.some(g => g === "PASS")).length;
  const failCount = calendar.filter(d => d.gateDecisions.some(g => g === "FAIL")).length;

  // Consecutive days from today backwards
  let consecutivePass = 0;
  for (let i = calendar.length - 1; i >= 0; i--) {
    const d = calendar[i];
    if (d.certified || d.gateDecisions.some(g => g === "PASS")) {
      consecutivePass++;
    } else if (d.gateDecisions.length > 0) {
      break;
    }
  }

  const readiness = consecutivePass >= 90 ? "Eligible" : consecutivePass >= 60 ? "On Track" : "In Progress";
  const readinessColor =
    readiness === "Eligible" ? "text-emerald-600 dark:text-emerald-400" :
    readiness === "On Track" ? "text-amber-600 dark:text-amber-400" :
    "text-slate-500";

  return (
    <div className="space-y-3 p-4 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900">
      {/* Header */}
      <div className="flex items-center justify-between flex-wrap gap-2">
        <div>
          <div className="text-sm font-semibold text-slate-700 dark:text-slate-300 capitalize">{domain || "All"} Domain</div>
          <div className="text-[11px] text-slate-400">90-day certification tracker</div>
        </div>
        <div className="flex items-center gap-3 text-[11px]">
          <span className="flex items-center gap-1">
            <div className="w-3 h-3 rounded-sm bg-emerald-500" /> Certified
          </span>
          <span className="flex items-center gap-1">
            <div className="w-3 h-3 rounded-sm bg-emerald-300" /> Pass
          </span>
          <span className="flex items-center gap-1">
            <div className="w-3 h-3 rounded-sm bg-amber-400" /> Review
          </span>
          <span className="flex items-center gap-1">
            <div className="w-3 h-3 rounded-sm bg-red-400" /> Fail
          </span>
        </div>
      </div>

      {/* Calendar grid */}
      <div className="flex flex-wrap gap-1">
        {calendar.map(day => (
          <CalendarCell key={day.date} day={day} />
        ))}
      </div>

      {/* Summary stats */}
      <div className="flex items-center gap-4 flex-wrap pt-1 border-t border-slate-100 dark:border-slate-800">
        <div className="text-center">
          <div className="text-sm font-bold text-emerald-600 dark:text-emerald-400 tabular-nums">{certCount}</div>
          <div className="text-[10px] text-slate-400">Certified days</div>
        </div>
        <div className="text-center">
          <div className="text-sm font-bold text-emerald-500 dark:text-emerald-300 tabular-nums">{passCount}</div>
          <div className="text-[10px] text-slate-400">Gate pass</div>
        </div>
        <div className="text-center">
          <div className={`text-sm font-bold tabular-nums ${failCount > 0 ? "text-red-600 dark:text-red-400" : "text-slate-400"}`}>{failCount}</div>
          <div className="text-[10px] text-slate-400">Gate fail</div>
        </div>
        <div className="text-center">
          <div className="text-sm font-bold text-indigo-600 dark:text-indigo-400 tabular-nums">{consecutivePass}</div>
          <div className="text-[10px] text-slate-400">Consecutive pass</div>
        </div>
        <div className="ml-auto text-center">
          <div className={`text-sm font-bold ${readinessColor}`}>{readiness}</div>
          <div className="text-[10px] text-slate-400">Certification readiness</div>
        </div>
      </div>
    </div>
  );
}

// ── Certification Status Table ────────────────────────────────────────────

function CertStatusTable({ certified, quality }) {
  // Aggregate per domain — latest cert + stats
  const domains = useMemo(() => {
    const map = {};
    (certified || []).forEach(c => {
      if (!map[c.domain] || c.target_date > map[c.domain].lastDate) {
        map[c.domain] = {
          domain:      c.domain,
          lastDate:    c.target_date,
          lastCert:    c.certification,
          lastScore:   c.overall_score,
          certifiedAt: c.certified_at,
          count:       0,
        };
      }
      map[c.domain].count++;
    });

    // Merge latest quality data
    const qualityByDomain = {};
    (quality || []).forEach(q => {
      if (!qualityByDomain[q.domain]) qualityByDomain[q.domain] = q;
    });

    return Object.values(map)
      .map(d => ({
        ...d,
        ...(qualityByDomain[d.domain] || {}),
      }))
      .sort((a, b) => (CERT_ORDER[b.lastCert] || 0) - (CERT_ORDER[a.lastCert] || 0));
  }, [certified, quality]);

  if (!domains.length) {
    return (
      <div className="flex flex-col items-center justify-center py-10 text-slate-400 gap-2">
        <Award className="w-8 h-8" />
        <span className="text-sm">No datasets certified yet — certification requires 90 consecutive passing days</span>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <h3 className="text-sm font-semibold text-slate-700 dark:text-slate-300">Dataset Certification Status</h3>
      <div className="overflow-x-auto rounded-lg border border-slate-200 dark:border-slate-700">
        <table className="w-full text-xs">
          <thead>
            <tr className="bg-slate-50 dark:bg-slate-800/50 text-slate-500 dark:text-slate-400 uppercase tracking-wide text-[10px]">
              <th className="px-4 py-2 text-left">Domain</th>
              <th className="px-4 py-2 text-center">Certification</th>
              <th className="px-4 py-2 text-right">Score</th>
              <th className="px-4 py-2 text-right">Accuracy</th>
              <th className="px-4 py-2 text-right">Consistency</th>
              <th className="px-4 py-2 text-right">Confidence</th>
              <th className="px-4 py-2 text-right">Certified Days</th>
              <th className="px-4 py-2 text-left">Last Certified</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
            {domains.map((d) => {
              const style = certStyle(d.lastCert);
              return (
                <tr key={d.domain} className={`hover:bg-slate-50 dark:hover:bg-slate-800/40 ${style.row}`}>
                  <td className="px-4 py-2">
                    <div className="flex items-center gap-2">
                      <div className={`w-2 h-2 rounded-full ${style.dot} shrink-0`} />
                      <span className="font-medium text-slate-700 dark:text-slate-300 capitalize">{d.domain}</span>
                    </div>
                  </td>
                  <td className="px-4 py-2 text-center">
                    <CertBadge label={d.lastCert} />
                  </td>
                  <td className={`px-4 py-2 text-right font-semibold tabular-nums ${
                    d.overall_score >= 99 ? "text-emerald-600 dark:text-emerald-400" :
                    d.overall_score >= 95 ? "text-amber-600 dark:text-amber-400" :
                    "text-red-600 dark:text-red-400"
                  }`}>{fmtScore(d.lastScore || d.overall_score)}</td>
                  <td className="px-4 py-2 text-right tabular-nums text-slate-500">{fmtScore(d.accuracy)}</td>
                  <td className="px-4 py-2 text-right tabular-nums text-slate-500">{fmtScore(d.consistency)}</td>
                  <td className="px-4 py-2 text-right tabular-nums text-slate-500">{fmtScore(d.confidence)}</td>
                  <td className="px-4 py-2 text-right tabular-nums font-semibold text-indigo-600 dark:text-indigo-400">
                    {d.count}
                  </td>
                  <td className="px-4 py-2 text-slate-400 font-mono">{fmtDate(d.lastDate)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ── Certification Criteria Panel ──────────────────────────────────────────

function CertCriteria({ certified, exceptions, gate }) {
  const hasCritical = (exceptions || []).some(e => !e.resolved && e.outcome === "FAIL");
  const latestGate = (gate || [])[0] || {};
  const hasBlocks = (latestGate.consistency_blocks || 0) > 0;
  const score = latestGate.overall_score;
  const scoreOk = score != null && score >= 99;
  const confidence = latestGate.confidence_score;
  const confOk = confidence != null && confidence >= 98;
  const hasCertified = (certified || []).length > 0;

  const checks = [
    { label: "90+ certified days",                  ok: hasCertified },
    { label: "No unresolved critical issues",       ok: !hasCritical },
    { label: "Quality score ≥ 99",                  ok: scoreOk,  value: score != null ? `${fmtScore(score)}` : "—" },
    { label: "Confidence score ≥ 98",               ok: confOk,   value: confidence != null ? `${fmtScore(confidence)}` : "—" },
    { label: "Zero BLOCK consistency findings",     ok: !hasBlocks, value: `${latestGate.consistency_blocks ?? "—"} blocks` },
  ];

  const allGreen = checks.every(c => c.ok);

  return (
    <div className={`rounded-lg border p-4 bg-white dark:bg-slate-900 ${
      allGreen ? "border-emerald-200 dark:border-emerald-800" : "border-slate-200 dark:border-slate-700"
    }`}>
      <div className="flex items-center gap-2 mb-3">
        {allGreen
          ? <ShieldCheck className="w-5 h-5 text-emerald-500" />
          : <ShieldAlert className="w-5 h-5 text-amber-500" />}
        <h3 className="text-sm font-semibold text-slate-700 dark:text-slate-300">Certification Criteria</h3>
        {allGreen && (
          <span className="ml-auto px-2 py-0.5 rounded bg-emerald-100 dark:bg-emerald-900/40 text-emerald-700 dark:text-emerald-300 text-[11px] font-bold">
            ELIGIBLE
          </span>
        )}
      </div>
      <div className="space-y-2">
        {checks.map((c, i) => (
          <div key={i} className="flex items-center gap-2 text-sm">
            {c.ok
              ? <CheckCircle2 className="w-4 h-4 text-emerald-500 shrink-0" />
              : <XCircle className="w-4 h-4 text-red-500 shrink-0" />}
            <span className={c.ok ? "text-slate-700 dark:text-slate-300" : "text-red-600 dark:text-red-400"}>
              {c.label}
            </span>
            {c.value && (
              <span className="ml-auto text-[11px] text-slate-400 tabular-nums font-mono">{c.value}</span>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Main Component ────────────────────────────────────────────────────────

export default function NidpCertificationPanel() {
  const [data, setData]       = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError]     = useState(null);
  const [domain, setDomain]   = useState("all");

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const params = domain === "all" ? {} : { domain };
      const r = await axios.get(`${API}/api/admin/nidp/quality/summary`, {
        withCredentials: true,
        params,
      });
      setData(r.data);
    } catch (e) {
      const msg = e?.response?.data?.detail || e.message;
      setError(msg);
      toast.error(`Certification load failed: ${msg}`);
    } finally {
      setLoading(false);
    }
  }, [domain]);

  useEffect(() => { load(); }, [load]);

  const { quality = [], certified = [], gate = [], exceptions = [] } = data || {};

  return (
    <div className="space-y-4">
      {/* Toolbar */}
      <div className="flex items-center justify-between flex-wrap gap-2">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-[11px] text-slate-500 font-medium">Domain:</span>
          {["all", "mf", "equity"].map(d => (
            <button
              key={d}
              onClick={() => setDomain(d)}
              className={`px-2.5 py-1 text-[11px] font-semibold rounded-md transition-colors uppercase ${
                domain === d
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
          className="flex items-center gap-1.5 px-3 py-1.5 text-xs rounded-md bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-400 hover:bg-slate-200 dark:hover:bg-slate-700 disabled:opacity-50"
        >
          {loading ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <RefreshCw className="w-3.5 h-3.5" />}
          Refresh
        </button>
      </div>

      {error && (
        <div className="rounded-lg border border-red-200 dark:border-red-800 bg-red-50 dark:bg-red-900/20 px-4 py-3 text-sm text-red-700 dark:text-red-300 flex items-start gap-2">
          <AlertTriangle className="w-4 h-4 shrink-0 mt-0.5" />
          <span>{error}</span>
        </div>
      )}

      {loading && (
        <div className="flex items-center justify-center py-16">
          <Loader2 className="w-6 h-6 animate-spin text-indigo-500" />
        </div>
      )}

      {!loading && !error && (
        <div className="space-y-6">
          <CertCriteria certified={certified} exceptions={exceptions} gate={gate} />
          <CertCalendar certified={certified} gate={gate} domain={domain} />
          <CertStatusTable certified={certified} quality={quality} />
        </div>
      )}
    </div>
  );
}
