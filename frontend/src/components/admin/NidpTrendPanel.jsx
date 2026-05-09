/**
 * NIDP Trend Analytics Panel
 *
 * Line charts for daily quality metrics over 30/90 days:
 * - Overall Quality Score
 * - Accuracy, Consistency, Completeness, Freshness
 * - Confidence Score
 * - Rule failure counts from consistency runs
 * - Certification progress heatmap
 *
 * Uses Recharts (already in package.json).
 */
import React, { useEffect, useState, useCallback, useMemo } from "react";
import axios from "axios";
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, ReferenceLine, Legend, BarChart, Bar,
} from "recharts";
import { Loader2, RefreshCw, AlertTriangle, TrendingUp } from "lucide-react";
import { toast } from "sonner";

const API = process.env.REACT_APP_BACKEND_URL;

const fmtScore = (v) => (v == null ? "—" : Number(v).toFixed(2));
const fmtDate  = (s) => (!s ? "—" : s.slice(5));  // "MM-DD"

// ── Chart helpers ──────────────────────────────────────────────────────────

const METRIC_LINES = [
  { key: "overall_score", label: "Overall Quality", color: "#6366f1", strokeWidth: 2.5 },
  { key: "accuracy",      label: "Accuracy",        color: "#10b981", strokeWidth: 1.5, strokeDasharray: "4 2" },
  { key: "consistency",   label: "Consistency",     color: "#f59e0b", strokeWidth: 1.5, strokeDasharray: "4 2" },
  { key: "completeness",  label: "Completeness",    color: "#3b82f6", strokeWidth: 1.5, strokeDasharray: "2 2" },
  { key: "freshness",     label: "Freshness",       color: "#8b5cf6", strokeWidth: 1.5, strokeDasharray: "2 2" },
  { key: "confidence",    label: "Confidence",      color: "#ec4899", strokeWidth: 1.5 },
];

const ACTIVE_METRICS = {
  overall:     ["overall_score"],
  all:         ["overall_score", "accuracy", "consistency", "completeness", "freshness", "confidence"],
  accuracy:    ["overall_score", "accuracy"],
  consistency: ["overall_score", "consistency"],
  confidence:  ["overall_score", "confidence"],
};

const THRESHOLDS = [
  { value: 99.99, label: "99.99%", color: "#10b981", dash: "4 2" },
  { value: 99,    label: "99%",    color: "#6366f1", dash: "4 2" },
  { value: 95,    label: "95%",    color: "#f59e0b", dash: "4 2" },
];

function CustomTooltip({ active, payload, label }) {
  if (!active || !payload?.length) return null;
  return (
    <div className="bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg shadow-lg px-3 py-2 text-xs">
      <div className="font-semibold text-slate-600 dark:text-slate-300 mb-1">{label}</div>
      {payload.map(p => (
        <div key={p.dataKey} className="flex items-center justify-between gap-4">
          <span style={{ color: p.color }}>{p.name}</span>
          <span className="font-mono font-semibold">{fmtScore(p.value)}</span>
        </div>
      ))}
    </div>
  );
}

// ── Quality Trend Chart ────────────────────────────────────────────────────

function QualityTrendChart({ quality, days }) {
  const [view, setView] = useState("overall");

  const data = useMemo(() => {
    const sorted = [...(quality || [])]
      .filter(q => q.domain !== "all")
      .sort((a, b) => a.target_date?.localeCompare(b.target_date));

    // Collapse duplicates by averaging per date (multiple domains)
    const byDate = {};
    sorted.forEach(q => {
      if (!byDate[q.target_date]) {
        byDate[q.target_date] = { date: q.target_date, _count: 0 };
        METRIC_LINES.forEach(m => { byDate[q.target_date][m.key] = null; });
      }
      const entry = byDate[q.target_date];
      entry._count++;
      METRIC_LINES.forEach(m => {
        const v = q[m.key] ?? q[m.key === "overall_score" ? "overall_score" : m.key];
        if (v != null) entry[m.key] = entry[m.key] == null ? v : (entry[m.key] + v) / 2;
      });
    });

    return Object.values(byDate)
      .slice(-days)
      .map(d => ({ ...d, label: fmtDate(d.date) }));
  }, [quality, days]);

  const activeLines = ACTIVE_METRICS[view] || ACTIVE_METRICS.overall;
  const minY = data.reduce((min, d) => {
    activeLines.forEach(k => { if (d[k] != null && d[k] < min) min = d[k]; });
    return min;
  }, 100);
  const domainMin = Math.max(Math.floor(minY) - 2, 0);

  if (!data.length) {
    return (
      <div className="flex items-center justify-center py-12 text-slate-400 text-sm">
        <TrendingUp className="w-5 h-5 mr-2" /> No trend data available yet
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between flex-wrap gap-2">
        <h3 className="text-sm font-semibold text-slate-700 dark:text-slate-300">Quality Score Trend ({days} days)</h3>
        <div className="flex items-center gap-1">
          {[
            { id: "overall",     label: "Overall" },
            { id: "all",         label: "All Metrics" },
            { id: "accuracy",    label: "+ Accuracy" },
            { id: "consistency", label: "+ Consistency" },
            { id: "confidence",  label: "+ Confidence" },
          ].map(v => (
            <button
              key={v.id}
              onClick={() => setView(v.id)}
              className={`px-2 py-0.5 text-[10px] font-semibold rounded transition-colors ${
                view === v.id
                  ? "bg-indigo-600 text-white"
                  : "bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-400 hover:bg-slate-200 dark:hover:bg-slate-700"
              }`}
            >
              {v.label}
            </button>
          ))}
        </div>
      </div>

      <div className="rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 p-4">
        <ResponsiveContainer width="100%" height={260}>
          <LineChart data={data} margin={{ top: 4, right: 8, left: -16, bottom: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" strokeOpacity={0.5} />
            <XAxis
              dataKey="label"
              tick={{ fontSize: 10, fill: "#94a3b8" }}
              tickLine={false}
              axisLine={false}
              interval={Math.floor(data.length / 8)}
            />
            <YAxis
              domain={[domainMin, 100]}
              tick={{ fontSize: 10, fill: "#94a3b8" }}
              tickLine={false}
              axisLine={false}
              tickFormatter={v => `${v}`}
            />
            <Tooltip content={<CustomTooltip />} />
            <Legend
              iconType="circle"
              iconSize={6}
              wrapperStyle={{ fontSize: 10, paddingTop: 8 }}
            />
            {THRESHOLDS.map(t => (
              <ReferenceLine
                key={t.value}
                y={t.value}
                stroke={t.color}
                strokeDasharray={t.dash}
                strokeOpacity={0.5}
                label={{ value: t.label, position: "right", fontSize: 9, fill: t.color }}
              />
            ))}
            {METRIC_LINES.filter(m => activeLines.includes(m.key)).map(m => (
              <Line
                key={m.key}
                type="monotone"
                dataKey={m.key}
                name={m.label}
                stroke={m.color}
                strokeWidth={m.strokeWidth}
                strokeDasharray={m.strokeDasharray}
                dot={false}
                activeDot={{ r: 4 }}
                connectNulls
              />
            ))}
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

// ── Rule Failure Trend ─────────────────────────────────────────────────────

function RuleFailureTrend({ runs, days }) {
  const data = useMemo(() => {
    return [...(runs || [])]
      .sort((a, b) => a.target_date?.localeCompare(b.target_date))
      .slice(-days)
      .map(r => ({
        label:        fmtDate(r.target_date),
        rules_failed: r.rules_failed || 0,
        findings:     r.findings_count || 0,
      }));
  }, [runs, days]);

  if (!data.length) return null;

  return (
    <div className="space-y-3">
      <h3 className="text-sm font-semibold text-slate-700 dark:text-slate-300">Rule Failures per Day</h3>
      <div className="rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 p-4">
        <ResponsiveContainer width="100%" height={180}>
          <BarChart data={data} margin={{ top: 4, right: 8, left: -16, bottom: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" strokeOpacity={0.5} />
            <XAxis
              dataKey="label"
              tick={{ fontSize: 10, fill: "#94a3b8" }}
              tickLine={false}
              axisLine={false}
              interval={Math.floor(data.length / 8)}
            />
            <YAxis
              tick={{ fontSize: 10, fill: "#94a3b8" }}
              tickLine={false}
              axisLine={false}
              allowDecimals={false}
            />
            <Tooltip
              contentStyle={{ fontSize: 11, borderRadius: 6 }}
              cursor={{ fill: "#f1f5f9", fillOpacity: 0.5 }}
            />
            <Legend iconType="circle" iconSize={6} wrapperStyle={{ fontSize: 10 }} />
            <Bar dataKey="rules_failed" name="Rules Failed" fill="#f59e0b" radius={[2, 2, 0, 0]} />
            <Bar dataKey="findings"     name="Findings"     fill="#6366f1" radius={[2, 2, 0, 0]} />
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

// ── Certification Progress ─────────────────────────────────────────────────

function CertProgressChart({ certified, days }) {
  const data = useMemo(() => {
    // Cumulative certified days over time
    const certSet = new Set((certified || []).map(c => c.target_date));
    const result = [];
    const today = new Date();
    let cumulative = 0;

    for (let i = days - 1; i >= 0; i--) {
      const d = new Date(today);
      d.setDate(today.getDate() - i);
      const iso = d.toISOString().slice(0, 10);
      if (certSet.has(iso)) cumulative++;
      result.push({
        label:       fmtDate(iso),
        certified:   certSet.has(iso) ? 1 : 0,
        cumulative,
      });
    }
    return result;
  }, [certified, days]);

  if (!certified?.length) return null;

  return (
    <div className="space-y-3">
      <h3 className="text-sm font-semibold text-slate-700 dark:text-slate-300">Certification Progress</h3>
      <div className="rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 p-4">
        <ResponsiveContainer width="100%" height={160}>
          <LineChart data={data} margin={{ top: 4, right: 8, left: -16, bottom: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" strokeOpacity={0.5} />
            <XAxis
              dataKey="label"
              tick={{ fontSize: 10, fill: "#94a3b8" }}
              tickLine={false}
              axisLine={false}
              interval={Math.floor(data.length / 8)}
            />
            <YAxis
              tick={{ fontSize: 10, fill: "#94a3b8" }}
              tickLine={false}
              axisLine={false}
            />
            <Tooltip contentStyle={{ fontSize: 11, borderRadius: 6 }} />
            <ReferenceLine
              y={90}
              stroke="#10b981"
              strokeDasharray="4 2"
              label={{ value: "90-day threshold", position: "insideTopRight", fontSize: 9, fill: "#10b981" }}
            />
            <Line
              type="monotone"
              dataKey="cumulative"
              name="Cumulative certified days"
              stroke="#6366f1"
              strokeWidth={2}
              dot={false}
              activeDot={{ r: 4 }}
            />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

// ── Main Component ────────────────────────────────────────────────────────

export default function NidpTrendPanel() {
  const [summary, setSummary]       = useState(null);
  const [consistency, setConsistency] = useState(null);
  const [loading, setLoading]       = useState(true);
  const [error, setError]           = useState(null);
  const [days, setDays]             = useState(30);
  const [domain, setDomain]         = useState("all");

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const params = domain === "all" ? {} : { domain };

      const [sumR, conR] = await Promise.all([
        axios.get(`${API}/api/admin/nidp/quality/summary`, {
          withCredentials: true, params,
        }),
        axios.get(`${API}/api/admin/nidp/quality/consistency`, {
          withCredentials: true, params: { ...params, limit: 90 },
        }),
      ]);

      setSummary(sumR.data);
      setConsistency(conR.data);
    } catch (e) {
      const msg = e?.response?.data?.detail || e.message;
      setError(msg);
      toast.error(`Trend data error: ${msg}`);
    } finally {
      setLoading(false);
    }
  }, [domain]);

  useEffect(() => { load(); }, [load]);

  const { quality = [], certified = [] } = summary || {};
  const { runs = [] } = consistency || {};

  return (
    <div className="space-y-4">
      {/* Toolbar */}
      <div className="flex items-center justify-between flex-wrap gap-2">
        <div className="flex items-center gap-3 flex-wrap">
          <div className="flex items-center gap-1">
            <span className="text-[11px] text-slate-500 font-medium">Domain:</span>
            {["all", "mf", "equity"].map(d => (
              <button
                key={d}
                onClick={() => setDomain(d)}
                className={`px-2.5 py-1 text-[11px] font-semibold rounded-md transition-colors uppercase ${
                  domain === d
                    ? "bg-indigo-600 text-white"
                    : "bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-400 hover:bg-slate-200"
                }`}
              >
                {d}
              </button>
            ))}
          </div>
          <div className="flex items-center gap-1">
            <span className="text-[11px] text-slate-500 font-medium">Period:</span>
            {[
              { v: 7,  label: "7d" },
              { v: 30, label: "30d" },
              { v: 90, label: "90d" },
            ].map(p => (
              <button
                key={p.v}
                onClick={() => setDays(p.v)}
                className={`px-2.5 py-1 text-[11px] font-semibold rounded-md transition-colors ${
                  days === p.v
                    ? "bg-indigo-600 text-white"
                    : "bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-400 hover:bg-slate-200"
                }`}
              >
                {p.label}
              </button>
            ))}
          </div>
        </div>
        <button
          onClick={load}
          disabled={loading}
          className="flex items-center gap-1.5 px-3 py-1.5 text-xs rounded-md bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-400 hover:bg-slate-200 disabled:opacity-50"
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
        <div className="space-y-8">
          <QualityTrendChart quality={quality} days={days} />
          <RuleFailureTrend runs={runs} days={days} />
          <CertProgressChart certified={certified} days={days} />
        </div>
      )}
    </div>
  );
}
