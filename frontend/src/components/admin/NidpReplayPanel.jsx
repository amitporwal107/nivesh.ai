import React, { useEffect, useState, useCallback, useMemo } from "react";
import axios from "axios";
import {
  Loader2, Play, RefreshCw, History, Sparkles, AlertTriangle,
  CheckCircle2, AlertCircle, XCircle, Clock, BarChart3, Trash2,
  ChevronDown, ChevronRight, FlaskConical,
} from "lucide-react";

const API = process.env.REACT_APP_BACKEND_URL;
const REPLAY = `${API}/api/admin/nidp/replay`;

const cls = (...xs) => xs.filter(Boolean).join(" ");

const STATUS_CHIP = {
  RUNNING:   "bg-amber-100 text-amber-800",
  SUCCESS:   "bg-emerald-100 text-emerald-700",
  FAILED:    "bg-rose-100 text-rose-700",
  CANCELLED: "bg-slate-100 text-slate-600",
};

const GATE_CHIP = {
  PASS:   { cls: "bg-emerald-100 text-emerald-700", icon: CheckCircle2 },
  REVIEW: { cls: "bg-amber-100 text-amber-700",     icon: AlertCircle },
  FAIL:   { cls: "bg-rose-100 text-rose-700",       icon: XCircle },
};

const CERT_CHIP = {
  GOLD:     "bg-yellow-100 text-yellow-800",
  SILVER:   "bg-slate-200 text-slate-700",
  REVIEW:   "bg-amber-100 text-amber-700",
  REJECTED: "bg-rose-100 text-rose-700",
  PLATINUM: "bg-indigo-100 text-indigo-700",
};


/**
 * NIDP 90-Day Historical Replay & Backtesting Panel
 *
 * Tabs:
 *  1) Start Run    — config + launch a replay invocation
 *  2) Run History  — list all past replays with summary stats
 *  3) Run Detail   — per-(date, domain) outcomes, failures, distribution
 *  4) Policies     — registered scoring policies (read-only here)
 */
export default function NidpReplayPanel() {
  const [tab, setTab] = useState("start");
  const [activeReplayId, setActiveReplayId] = useState(null);

  const onStarted = (replayId) => {
    setActiveReplayId(replayId);
    setTab("detail");
  };

  return (
    <div className="space-y-4" data-testid="replay-panel">
      <div className="flex items-center gap-2 border-b border-slate-200 dark:border-slate-700">
        {[
          { id: "start",    label: "Start Run",   icon: Play },
          { id: "history",  label: "Run History", icon: History },
          { id: "detail",   label: "Run Detail",  icon: BarChart3 },
          { id: "policies", label: "Policies",    icon: Sparkles },
        ].map(t => (
          <button
            key={t.id}
            data-testid={`replay-tab-${t.id}`}
            onClick={() => setTab(t.id)}
            className={cls(
              "flex items-center gap-1.5 px-4 py-2 -mb-px text-sm border-b-2 transition",
              tab === t.id
                ? "border-indigo-500 text-indigo-600 font-medium"
                : "border-transparent text-slate-500 hover:text-slate-800",
            )}
          >
            <t.icon className="w-4 h-4" /> {t.label}
          </button>
        ))}
      </div>

      {tab === "start"    && <StartRunTab onStarted={onStarted} />}
      {tab === "history"  && <HistoryTab onSelect={(id) => { setActiveReplayId(id); setTab("detail"); }} />}
      {tab === "detail"   && <DetailTab replayId={activeReplayId} setReplayId={setActiveReplayId} />}
      {tab === "policies" && <PoliciesTab />}
    </div>
  );
}


// ─── Start Run ──────────────────────────────────────────────────────
function StartRunTab({ onStarted }) {
  const today    = new Date();
  const ninetyAgo = new Date(today.getTime() - 90 * 24 * 3600 * 1000);

  const [policies, setPolicies] = useState([]);
  const [form, setForm] = useState({
    start_date:      ninetyAgo.toISOString().slice(0, 10),
    end_date:        today.toISOString().slice(0, 10),
    domains:         ["mf", "equity"],
    policy_version:  "v1",
    parallel:        4,
    inject_failures: false,
    reset_data:      false,
    failure_seed:    null,
    failure_rate:    0.10,
    skip_weekends:   true,
  });
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    axios.get(`${REPLAY}/policies`, { withCredentials: true })
      .then(r => setPolicies(r.data.policies || []))
      .catch(() => setPolicies([]));
  }, []);

  const tradingDayEstimate = useMemo(() => {
    const s = new Date(form.start_date);
    const e = new Date(form.end_date);
    if (e < s) return 0;
    let d = 0;
    for (let cur = new Date(s); cur <= e; cur.setDate(cur.getDate() + 1)) {
      if (!form.skip_weekends || (cur.getDay() !== 0 && cur.getDay() !== 6)) d++;
    }
    return d;
  }, [form.start_date, form.end_date, form.skip_weekends]);

  const submit = async () => {
    setSubmitting(true); setError(null);
    try {
      const r = await axios.post(`${REPLAY}/start`, form, { withCredentials: true });
      onStarted(r.data.replay_id);
    } catch (e) {
      setError(e?.response?.data?.detail || e.message);
    } finally {
      setSubmitting(false);
    }
  };

  const toggleDomain = (d) => {
    setForm(f => {
      const s = new Set(f.domains);
      if (s.has(d)) s.delete(d); else s.add(d);
      return { ...f, domains: [...s] };
    });
  };

  return (
    <div className="space-y-4 max-w-3xl">
      <div className="p-4 border rounded-md bg-white dark:bg-slate-900 space-y-3">
        <h3 className="text-sm font-medium text-slate-800 dark:text-slate-100">
          Replay window
        </h3>
        <div className="grid grid-cols-2 gap-3">
          <label className="text-xs text-slate-600 dark:text-slate-300 space-y-1">
            <span>Start date</span>
            <input type="date" value={form.start_date}
                   data-testid="replay-start-date"
                   onChange={e => setForm({ ...form, start_date: e.target.value })}
                   className="w-full px-2 py-1.5 border rounded-md text-sm dark:bg-slate-800" />
          </label>
          <label className="text-xs text-slate-600 dark:text-slate-300 space-y-1">
            <span>End date</span>
            <input type="date" value={form.end_date}
                   data-testid="replay-end-date"
                   onChange={e => setForm({ ...form, end_date: e.target.value })}
                   className="w-full px-2 py-1.5 border rounded-md text-sm dark:bg-slate-800" />
          </label>
        </div>
        <div className="text-xs text-slate-500">
          Estimated trading days in window: <b>{tradingDayEstimate}</b>
          {form.skip_weekends ? " (weekdays only)" : " (all days)"}
        </div>
      </div>

      <div className="p-4 border rounded-md bg-white dark:bg-slate-900 space-y-3">
        <h3 className="text-sm font-medium text-slate-800 dark:text-slate-100">
          Domains & policy
        </h3>
        <div className="flex items-center gap-2">
          {["mf", "equity"].map(d => (
            <label key={d} className="flex items-center gap-1.5 text-xs cursor-pointer">
              <input type="checkbox" checked={form.domains.includes(d)}
                     data-testid={`replay-domain-${d}`}
                     onChange={() => toggleDomain(d)} />
              {d.toUpperCase()}
            </label>
          ))}
        </div>
        <label className="text-xs text-slate-600 dark:text-slate-300 space-y-1 block">
          <span>Scoring policy</span>
          <select value={form.policy_version}
                  data-testid="replay-policy"
                  onChange={e => setForm({ ...form, policy_version: e.target.value })}
                  className="w-full px-2 py-1.5 border rounded-md text-sm dark:bg-slate-800">
            {policies.map(p => (
              <option key={p.version} value={p.version}>
                {p.version} — {p.description}
              </option>
            ))}
            {policies.length === 0 && (
              <>
                <option value="v1">v1 — PRD spec (0.30A + 0.25C + 0.20L + 0.15F + 0.10K)</option>
                <option value="legacy">legacy — pre-replay weights</option>
              </>
            )}
          </select>
        </label>
      </div>

      <div className="p-4 border rounded-md bg-white dark:bg-slate-900 space-y-3">
        <h3 className="text-sm font-medium text-slate-800 dark:text-slate-100">
          Execution
        </h3>
        <div className="grid grid-cols-2 gap-3">
          <label className="text-xs text-slate-600 dark:text-slate-300 space-y-1">
            <span>Parallel workers</span>
            <input type="number" value={form.parallel} min={1} max={32}
                   data-testid="replay-parallel"
                   onChange={e => setForm({ ...form, parallel: parseInt(e.target.value, 10) || 1 })}
                   className="w-full px-2 py-1.5 border rounded-md text-sm dark:bg-slate-800" />
          </label>
          <label className="text-xs text-slate-600 dark:text-slate-300 space-y-1">
            <span>Failure injection rate</span>
            <input type="number" value={form.failure_rate} step={0.05} min={0} max={1}
                   data-testid="replay-failure-rate"
                   onChange={e => setForm({ ...form, failure_rate: parseFloat(e.target.value) || 0 })}
                   className="w-full px-2 py-1.5 border rounded-md text-sm dark:bg-slate-800" />
          </label>
        </div>
        <div className="flex flex-col gap-1.5 text-xs">
          <label className="flex items-center gap-2 cursor-pointer">
            <input type="checkbox" checked={form.inject_failures}
                   data-testid="replay-inject"
                   onChange={e => setForm({ ...form, inject_failures: e.target.checked })} />
            Inject synthetic failures (FR-11) — for calibration
          </label>
          <label className="flex items-center gap-2 cursor-pointer">
            <input type="checkbox" checked={form.reset_data}
                   data-testid="replay-reset"
                   onChange={e => setForm({ ...form, reset_data: e.target.checked })} />
            Reset window — wipe quality_scores / exception_queue / quarantine_log for the replay range
          </label>
          <label className="flex items-center gap-2 cursor-pointer">
            <input type="checkbox" checked={form.skip_weekends}
                   onChange={e => setForm({ ...form, skip_weekends: e.target.checked })} />
            Skip weekends (recommended for trading-day replays)
          </label>
        </div>
      </div>

      {error && (
        <div className="flex items-center gap-2 px-3 py-2 bg-rose-50 border border-rose-200 rounded text-xs text-rose-700">
          <AlertTriangle className="w-4 h-4 shrink-0" /> {String(error)}
        </div>
      )}

      <div className="flex items-center gap-3">
        <button data-testid="replay-start-btn" disabled={submitting || form.domains.length === 0} onClick={submit}
                className="flex items-center gap-2 px-4 py-2 bg-indigo-600 text-white rounded-md hover:bg-indigo-700 disabled:opacity-50">
          {submitting ? <Loader2 className="w-4 h-4 animate-spin" /> : <Play className="w-4 h-4" />}
          Start Replay
        </button>
        {form.reset_data && (
          <span className="text-xs text-amber-700 flex items-center gap-1">
            <AlertTriangle className="w-3.5 h-3.5" /> reset_data=ON — existing rows in window will be wiped first
          </span>
        )}
      </div>
    </div>
  );
}


// ─── History ────────────────────────────────────────────────────────
function HistoryTab({ onSelect }) {
  const [runs, setRuns] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const reload = useCallback(async () => {
    setLoading(true); setError(null);
    try {
      const r = await axios.get(`${REPLAY}/runs?limit=50`, { withCredentials: true });
      setRuns(r.data.runs || []);
    } catch (e) {
      setError(e?.response?.data?.detail || e.message);
    } finally {
      setLoading(false);
    }
  }, []);
  useEffect(() => { reload(); }, [reload]);

  const remove = async (id) => {
    if (!window.confirm("Delete this replay run and all its dates?")) return;
    await axios.delete(`${REPLAY}/runs/${id}`, { withCredentials: true });
    reload();
  };

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2">
        <button data-testid="replay-history-reload" onClick={reload}
                className="px-2 py-1.5 text-sm border rounded-md flex items-center gap-1">
          <RefreshCw className="w-3.5 h-3.5" /> reload
        </button>
        <span className="text-xs text-slate-400 ml-auto">{runs.length} runs</span>
      </div>

      {error && (
        <div className="flex items-center gap-2 px-3 py-2 bg-rose-50 border border-rose-200 rounded text-xs text-rose-700">
          <AlertTriangle className="w-4 h-4" /> {String(error)}
        </div>
      )}

      {loading && <Loader2 className="w-5 h-5 animate-spin text-slate-400 mx-auto my-6" />}

      {!loading && runs.length === 0 && (
        <div className="text-center py-8 text-slate-400 text-sm">no replays yet — start one</div>
      )}

      {!loading && runs.length > 0 && (
        <div className="border rounded-md overflow-hidden">
          <table className="w-full text-xs">
            <thead className="bg-slate-50 dark:bg-slate-800 text-left">
              <tr>
                <th className="px-2 py-1.5">Started</th>
                <th className="px-2 py-1.5">Window</th>
                <th className="px-2 py-1.5">Policy</th>
                <th className="px-2 py-1.5">Status</th>
                <th className="px-2 py-1.5">Progress</th>
                <th className="px-2 py-1.5">Avg Q</th>
                <th className="px-2 py-1.5">Pass / Review / Fail</th>
                <th className="px-2 py-1.5 w-24">Actions</th>
              </tr>
            </thead>
            <tbody>
              {runs.map(r => (
                <tr key={r.replay_id} className="border-t hover:bg-slate-50 dark:hover:bg-slate-800"
                    data-testid={`replay-run-row-${r.replay_id}`}>
                  <td className="px-2 py-1.5 font-mono text-[11px]">
                    {(r.started_at || "").replace("T", " ").slice(0, 16)}
                  </td>
                  <td className="px-2 py-1.5 font-mono text-[11px]">
                    {r.start_date} → {r.end_date}
                  </td>
                  <td className="px-2 py-1.5">
                    <span className="px-1.5 py-0.5 rounded bg-indigo-50 text-indigo-700 text-[10px]">{r.policy_version}</span>
                  </td>
                  <td className="px-2 py-1.5">
                    <span className={cls("px-1.5 py-0.5 rounded text-[10px]", STATUS_CHIP[r.status] || "")}>{r.status}</span>
                  </td>
                  <td className="px-2 py-1.5 text-[11px]">
                    {r.dates_processed || 0} / {r.dates_total || 0}
                    {(r.dates_failed || 0) > 0 && <span className="text-rose-500"> · {r.dates_failed} failed</span>}
                  </td>
                  <td className="px-2 py-1.5 font-mono">
                    {r.avg_overall_score != null ? Number(r.avg_overall_score).toFixed(2) : "—"}
                  </td>
                  <td className="px-2 py-1.5 font-mono text-[11px]">
                    <span className="text-emerald-600">{r.pass_count || 0}</span> /
                    <span className="text-amber-600"> {r.review_count || 0}</span> /
                    <span className="text-rose-600"> {r.fail_count || 0}</span>
                  </td>
                  <td className="px-2 py-1.5">
                    <div className="flex gap-1">
                      <button data-testid={`replay-view-${r.replay_id}`} onClick={() => onSelect(r.replay_id)}
                              className="text-indigo-600 hover:text-indigo-800">
                        <BarChart3 className="w-3.5 h-3.5" />
                      </button>
                      <button onClick={() => remove(r.replay_id)} className="text-slate-500 hover:text-rose-600">
                        <Trash2 className="w-3.5 h-3.5" />
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}


// ─── Detail ─────────────────────────────────────────────────────────
function DetailTab({ replayId, setReplayId }) {
  const [status, setStatus] = useState(null);
  const [dates, setDates]   = useState([]);
  const [failures, setFailures] = useState({ failures: [], total: 0, detected: 0, detection_rate: null });
  const [loading, setLoading] = useState(false);
  const [showFailures, setShowFailures] = useState(false);
  const [error, setError] = useState(null);
  const [domainFilter, setDomainFilter]       = useState("");
  const [outcomeFilter, setOutcomeFilter]     = useState("");

  const reload = useCallback(async () => {
    if (!replayId) return;
    setLoading(true); setError(null);
    try {
      const [s, d, f] = await Promise.all([
        axios.get(`${REPLAY}/status/${replayId}`, { withCredentials: true }),
        axios.get(`${REPLAY}/runs/${replayId}/dates?${domainFilter ? `domain=${domainFilter}&` : ""}${outcomeFilter ? `gate_outcome=${outcomeFilter}&` : ""}limit=1000`, { withCredentials: true }),
        axios.get(`${REPLAY}/runs/${replayId}/failures?limit=500`, { withCredentials: true }),
      ]);
      setStatus(s.data);
      setDates(d.data.dates || []);
      setFailures(f.data || {});
    } catch (e) {
      setError(e?.response?.data?.detail || e.message);
    } finally {
      setLoading(false);
    }
  }, [replayId, domainFilter, outcomeFilter]);

  useEffect(() => { reload(); }, [reload]);

  // Auto-refresh while RUNNING
  useEffect(() => {
    if (status?.run?.status !== "RUNNING") return;
    const t = setInterval(reload, 5000);
    return () => clearInterval(t);
  }, [status?.run?.status, reload]);

  if (!replayId) {
    return (
      <div className="text-center py-8 text-slate-400 text-sm">
        Select a replay from <b>Run History</b> or start a new one.
      </div>
    );
  }

  if (loading && !status) return <Loader2 className="w-5 h-5 animate-spin text-slate-400 mx-auto my-6" />;

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2">
        <button data-testid="replay-detail-reload" onClick={reload} className="px-2 py-1.5 text-sm border rounded-md flex items-center gap-1">
          <RefreshCw className="w-3.5 h-3.5" /> reload
        </button>
        <button onClick={() => setReplayId(null)} className="px-2 py-1.5 text-sm border rounded-md text-slate-500">clear</button>
        <span className="text-[11px] text-slate-400 font-mono ml-auto">{replayId}</span>
      </div>

      {error && (
        <div className="flex items-center gap-2 px-3 py-2 bg-rose-50 border border-rose-200 rounded text-xs text-rose-700">
          <AlertTriangle className="w-4 h-4" /> {String(error)}
        </div>
      )}

      {status && <StatusHeader status={status} />}
      {status?.statistics && <StatsGrid stats={status.statistics} />}

      {failures.total > 0 && (
        <div className="border rounded-md bg-white dark:bg-slate-900 p-3" data-testid="replay-failures">
          <button onClick={() => setShowFailures(!showFailures)} className="flex items-center gap-2 text-sm font-medium text-slate-700 dark:text-slate-200">
            {showFailures ? <ChevronDown className="w-4 h-4" /> : <ChevronRight className="w-4 h-4" />}
            <FlaskConical className="w-4 h-4" />
            Synthetic Failures: <b>{failures.detected}/{failures.total}</b> detected ({failures.detection_rate != null ? `${(failures.detection_rate * 100).toFixed(1)}%` : "—"})
          </button>
          {showFailures && (
            <table className="w-full text-[11px] mt-3">
              <thead className="bg-slate-50 dark:bg-slate-800 text-left">
                <tr>
                  <th className="px-2 py-1">Date</th>
                  <th className="px-2 py-1">Domain</th>
                  <th className="px-2 py-1">Type</th>
                  <th className="px-2 py-1">Table</th>
                  <th className="px-2 py-1">Rows</th>
                  <th className="px-2 py-1">Detected</th>
                </tr>
              </thead>
              <tbody>
                {failures.failures.map(f => (
                  <tr key={f.failure_id} className="border-t">
                    <td className="px-2 py-1 font-mono">{f.target_date}</td>
                    <td className="px-2 py-1">{f.domain}</td>
                    <td className="px-2 py-1">{f.failure_type}</td>
                    <td className="px-2 py-1 font-mono text-[10px]">{f.target_table}</td>
                    <td className="px-2 py-1">{f.rows_affected}</td>
                    <td className="px-2 py-1">{f.detected ? <CheckCircle2 className="w-3.5 h-3.5 text-emerald-600 inline" /> : <XCircle className="w-3.5 h-3.5 text-rose-600 inline" />}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}

      <div className="border rounded-md bg-white dark:bg-slate-900">
        <div className="px-3 py-2 border-b bg-slate-50 dark:bg-slate-800 flex items-center gap-3">
          <span className="text-sm font-medium">Per-date outcomes</span>
          <select value={domainFilter} onChange={e => setDomainFilter(e.target.value)} className="text-xs px-2 py-1 border rounded">
            <option value="">all domains</option>
            <option value="mf">mf</option>
            <option value="equity">equity</option>
          </select>
          <select value={outcomeFilter} onChange={e => setOutcomeFilter(e.target.value)} className="text-xs px-2 py-1 border rounded">
            <option value="">all outcomes</option>
            <option value="PASS">PASS</option>
            <option value="REVIEW">REVIEW</option>
            <option value="FAIL">FAIL</option>
          </select>
          <span className="text-[11px] text-slate-400 ml-auto">{dates.length} rows</span>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead className="bg-white dark:bg-slate-900 text-left">
              <tr>
                <th className="px-2 py-1.5">Date</th>
                <th className="px-2 py-1.5">Domain</th>
                <th className="px-2 py-1.5">Q</th>
                <th className="px-2 py-1.5">A</th>
                <th className="px-2 py-1.5">C</th>
                <th className="px-2 py-1.5">L</th>
                <th className="px-2 py-1.5">F</th>
                <th className="px-2 py-1.5">K</th>
                <th className="px-2 py-1.5">Cert</th>
                <th className="px-2 py-1.5">Decision</th>
                <th className="px-2 py-1.5">Gate</th>
                <th className="px-2 py-1.5">Blocks</th>
              </tr>
            </thead>
            <tbody>
              {dates.map(d => (
                <tr key={`${d.target_date}-${d.domain}`} className="border-t" data-testid={`replay-date-${d.target_date}-${d.domain}`}>
                  <td className="px-2 py-1 font-mono text-[11px]">{d.target_date}</td>
                  <td className="px-2 py-1">{d.domain}</td>
                  <td className="px-2 py-1 font-mono">{d.overall_score != null ? Number(d.overall_score).toFixed(2) : "—"}</td>
                  <td className="px-2 py-1 font-mono text-[11px]">{fmt(d.accuracy)}</td>
                  <td className="px-2 py-1 font-mono text-[11px]">{fmt(d.consistency)}</td>
                  <td className="px-2 py-1 font-mono text-[11px]">{fmt(d.completeness)}</td>
                  <td className="px-2 py-1 font-mono text-[11px]">{fmt(d.freshness)}</td>
                  <td className="px-2 py-1 font-mono text-[11px]">{fmt(d.confidence_score ?? d.auditability)}</td>
                  <td className="px-2 py-1">
                    {d.certification && <span className={cls("px-1.5 py-0.5 rounded text-[10px]", CERT_CHIP[d.certification] || "")}>{d.certification}</span>}
                  </td>
                  <td className="px-2 py-1 text-[11px]">{d.publish_decision || "—"}</td>
                  <td className="px-2 py-1">
                    {d.gate_outcome && <GateChip outcome={d.gate_outcome} />}
                  </td>
                  <td className="px-2 py-1 font-mono text-[11px]">{d.block_findings || 0}</td>
                </tr>
              ))}
              {dates.length === 0 && !loading && (
                <tr><td colSpan={12} className="text-center py-6 text-slate-400">no rows</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}


function GateChip({ outcome }) {
  const cfg = GATE_CHIP[outcome] || {};
  const Icon = cfg.icon || Clock;
  return <span className={cls("inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px]", cfg.cls)}>
    <Icon className="w-3 h-3" /> {outcome}
  </span>;
}


function StatusHeader({ status }) {
  const r = status.run || {};
  const live = status.live || {};
  return (
    <div className="border rounded-md bg-white dark:bg-slate-900 p-4 flex items-center gap-4 flex-wrap" data-testid="replay-status-header">
      <div>
        <div className="text-[11px] text-slate-500">window</div>
        <div className="text-sm font-mono">{r.start_date} → {r.end_date}</div>
      </div>
      <div>
        <div className="text-[11px] text-slate-500">policy</div>
        <div className="text-sm">{r.policy_version}</div>
      </div>
      <div>
        <div className="text-[11px] text-slate-500">status</div>
        <span className={cls("inline-block px-1.5 py-0.5 rounded text-[10px]", STATUS_CHIP[r.status] || "")}>{r.status}</span>
      </div>
      <div>
        <div className="text-[11px] text-slate-500">progress</div>
        <div className="text-sm font-mono">{live.rows_persisted || 0} / {r.dates_total || 0}</div>
      </div>
      <div>
        <div className="text-[11px] text-slate-500">parallel</div>
        <div className="text-sm font-mono">{r.parallel}</div>
      </div>
      {r.inject_failures && (
        <div>
          <div className="text-[11px] text-slate-500">injection</div>
          <span className="text-[10px] px-1.5 py-0.5 rounded bg-amber-100 text-amber-700">on</span>
        </div>
      )}
      {r.error && (
        <div className="text-xs text-rose-600 ml-auto" title={r.error}>error: {String(r.error).slice(0, 100)}…</div>
      )}
    </div>
  );
}


function StatsGrid({ stats }) {
  const tiles = [
    { label: "Avg Q", value: stats.avg_overall_score != null ? Number(stats.avg_overall_score).toFixed(2) : "—" },
    { label: "P50 Q", value: stats.p50_overall_score != null ? Number(stats.p50_overall_score).toFixed(2) : "—" },
    { label: "P10 Q", value: stats.p10_overall_score != null ? Number(stats.p10_overall_score).toFixed(2) : "—" },
    { label: "Pass", value: stats.pass_count, cls: "text-emerald-600" },
    { label: "Review", value: stats.review_count, cls: "text-amber-600" },
    { label: "Fail", value: stats.fail_count, cls: "text-rose-600" },
    { label: "Gold", value: stats.cert_gold },
    { label: "Silver", value: stats.cert_silver },
    { label: "Review (cert)", value: stats.cert_review },
    { label: "Rejected", value: stats.cert_rejected, cls: "text-rose-600" },
  ];
  return (
    <div className="grid grid-cols-2 sm:grid-cols-5 gap-2" data-testid="replay-stats-grid">
      {tiles.map(t => (
        <div key={t.label} className="px-3 py-2 border rounded-md bg-white dark:bg-slate-900">
          <div className="text-[11px] text-slate-500">{t.label}</div>
          <div className={cls("text-base font-semibold font-mono", t.cls || "")}>{t.value ?? "—"}</div>
        </div>
      ))}
    </div>
  );
}


function fmt(v) {
  return v != null ? Number(v).toFixed(1) : "—";
}


// ─── Policies ───────────────────────────────────────────────────────
function PoliciesTab() {
  const [policies, setPolicies] = useState([]);
  const [loading, setLoading]   = useState(true);
  const [error, setError]       = useState(null);

  useEffect(() => {
    axios.get(`${REPLAY}/policies`, { withCredentials: true })
      .then(r => setPolicies(r.data.policies || []))
      .catch(e => setError(e?.response?.data?.detail || e.message))
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <Loader2 className="w-5 h-5 animate-spin text-slate-400 mx-auto my-6" />;
  if (error) return <div className="px-3 py-2 bg-rose-50 border border-rose-200 rounded text-xs text-rose-700">{error}</div>;

  return (
    <div className="grid sm:grid-cols-2 gap-3">
      {policies.map(p => (
        <div key={p.version} className="border rounded-md p-4 bg-white dark:bg-slate-900" data-testid={`replay-policy-${p.version}`}>
          <div className="flex items-baseline justify-between">
            <h3 className="text-sm font-semibold text-slate-800 dark:text-slate-100">{p.version}</h3>
            <span className="text-[10px] text-slate-400">Q = w_A·A + w_C·C + w_L·L + w_F·F + w_K·K</span>
          </div>
          <p className="text-xs text-slate-500 dark:text-slate-300 mt-1">{p.description}</p>
          <table className="w-full text-[11px] mt-3">
            <tbody>
              <tr><td className="text-slate-500 py-0.5">w_accuracy</td><td className="font-mono text-right">{p.w_accuracy}</td></tr>
              <tr><td className="text-slate-500 py-0.5">w_consistency</td><td className="font-mono text-right">{p.w_consistency}</td></tr>
              <tr><td className="text-slate-500 py-0.5">w_completeness</td><td className="font-mono text-right">{p.w_completeness}</td></tr>
              <tr><td className="text-slate-500 py-0.5">w_freshness</td><td className="font-mono text-right">{p.w_freshness}</td></tr>
              <tr><td className="text-slate-500 py-0.5">w_confidence</td><td className="font-mono text-right">{p.w_confidence}</td></tr>
              <tr className="border-t"><td className="text-slate-500 py-0.5">cert thresholds</td><td className="font-mono text-right">{p.cert_gold}/{p.cert_silver}/{p.cert_review}</td></tr>
              <tr><td className="text-slate-500 py-0.5">publish/review</td><td className="font-mono text-right">{p.publish_min}/{p.review_min}</td></tr>
              <tr><td className="text-slate-500 py-0.5">conf min</td><td className="font-mono text-right">{p.confidence_min}</td></tr>
            </tbody>
          </table>
        </div>
      ))}
      {policies.length === 0 && (
        <div className="text-center py-8 text-slate-400 text-sm col-span-2">no policies registered — apply migration 044</div>
      )}
    </div>
  );
}
