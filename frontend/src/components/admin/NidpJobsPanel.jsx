import React, { useEffect, useState, useCallback } from "react";
import axios from "axios";
import {
  PlayCircle, RefreshCw, Loader2, ChevronDown, ChevronRight,
  CheckCircle2, XCircle, AlertTriangle, Clock, FileText, ExternalLink,
} from "lucide-react";
import { toast } from "sonner";

const API = process.env.REACT_APP_BACKEND_URL;

// Verdict colour map mirrors the dump-script CASE statement so the UI
// shows the same status taxonomy admins already see in psql output.
const STATUS_STYLES = {
  OK:      { dot: "bg-emerald-500", text: "text-emerald-600 dark:text-emerald-400" },
  GREEN:   { dot: "bg-emerald-500", text: "text-emerald-600 dark:text-emerald-400" },
  PARTIAL: { dot: "bg-amber-500",   text: "text-amber-600 dark:text-amber-400" },
  SKIPPED: { dot: "bg-slate-400",   text: "text-slate-500 dark:text-slate-400" },
  FAILED:  { dot: "bg-red-500",     text: "text-red-600 dark:text-red-400" },
  RUNNING: { dot: "bg-indigo-500 animate-pulse", text: "text-indigo-600 dark:text-indigo-400" },
  null:    { dot: "bg-slate-300",   text: "text-slate-400" },
};

function relTime(iso) {
  if (!iso) return "—";
  const t = new Date(iso).getTime();
  const diff = (Date.now() - t) / 1000;
  if (diff < 60)       return `${Math.round(diff)}s ago`;
  if (diff < 3600)     return `${Math.round(diff / 60)}m ago`;
  if (diff < 86400)    return `${Math.round(diff / 3600)}h ago`;
  return `${Math.round(diff / 86400)}d ago`;
}

// Per-day cell color in the inline week strip + the expanded calendar.
const CAL_BG = {
  OK:      "bg-emerald-500",
  GREEN:   "bg-emerald-500",
  PARTIAL: "bg-amber-500",
  FAILED:  "bg-red-500",
  SKIPPED: "bg-slate-300 dark:bg-slate-600",
};

// Compact 7-day strip for the main row. Each cell is one day; today
// gets an indigo ring. Letters above are the day-of-week initial
// (S M T W T F S) in browser locale.
function WeekStrip({ days }) {
  if (!days || days.length === 0) {
    return <span className="text-slate-400 text-[10px]">—</span>;
  }
  return (
    <div className="flex gap-0.5 items-end">
      {days.map(d => {
        const dt = new Date(d.date + "T00:00:00");
        const letter = dt.toLocaleDateString(undefined, { weekday: "narrow" });
        const wd = dt.getUTCDay();
        const isWeekend = wd === 0 || wd === 6;
        let bg;
        let tip;
        if (d.status) {
          bg = CAL_BG[d.status];
          tip = `${d.date}${d.is_today ? " (today)" : ""} · ${d.status} · ${d.run_count || 0} run(s)`;
        } else if (isWeekend) {
          // Non-trading day — visibly muted with a dashed border so the
          // user doesn't read a missing weekend run as a failure.
          bg = "bg-slate-100 dark:bg-slate-800 border border-dashed border-slate-300 dark:border-slate-600";
          tip = `${d.date}${d.is_today ? " (today)" : ""} · Non-trading day (weekend)`;
        } else {
          bg = "bg-slate-200 dark:bg-slate-700";
          tip = `${d.date}${d.is_today ? " (today)" : ""} · no run`;
        }
        const ring = d.is_today ? "ring-2 ring-indigo-500 ring-offset-1 ring-offset-white dark:ring-offset-slate-800" : "";
        return (
          <div key={d.date} className="flex flex-col items-center" title={tip}>
            <div className={`w-3.5 h-3.5 rounded-sm ${bg} ${ring}`} />
            <div className={"text-[8px] mt-0.5 " + (d.is_today ? "text-indigo-600 dark:text-indigo-400 font-bold" : (isWeekend ? "text-slate-300 dark:text-slate-600" : "text-slate-400"))}>
              {letter}
            </div>
          </div>
        );
      })}
    </div>
  );
}

/**
 * Admin → Infra & Data → NIDP Jobs
 *
 * Per-ingester control plane. Lists all 13 NIDP Cloud Run jobs with
 * status badge + last-run summary. Each row expands to show recent
 * runs (from nidp.job_log) and a Tail logs action (from Cloud Logging).
 *
 * Backend: /api/admin/nidp/jobs[/{ingester}/(execute|runs|logs)]
 */
export default function NidpJobsPanel() {
  const [data, setData]       = useState(null);
  const [loading, setLoading] = useState(true);
  const [expanded, setExpanded] = useState({});       // ingester -> {runs, logs, ...}
  const [acting, setActing]   = useState({});          // ingester -> "execute" | "logs" | "runs"
  // Run-date for Trigger and inline calendar fetches. Default = the
  // backend-supplied `last_trading_day` (Mon–Fri shy of weekends);
  // user can override per-trigger from the header date input.
  const [runDate, setRunDate] = useState(null);
  const [archive, setArchive] = useState(null);        // {ingester, payload} or null

  const fetchJobs = useCallback(async () => {
    setLoading(true);
    try {
      const r = await axios.get(`${API}/api/admin/nidp/jobs`, { withCredentials: true });
      setData(r.data);
      // Initialise run-date to last trading day on first load only — never override
      // a date the user has typed.
      setRunDate(d => d || r.data?.last_trading_day || null);
    } catch (e) {
      toast.error(`Failed to load jobs: ${e?.response?.data?.detail || e.message}`);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchJobs(); }, [fetchJobs]);

  const triggerJob = useCallback(async (ingester) => {
    setActing(s => ({ ...s, [ingester]: "execute" }));
    toast.loading(`Triggering ${ingester} for ${runDate || "default date"}...`, { id: `trigger-${ingester}` });
    try {
      const r = await axios.post(
        `${API}/api/admin/nidp/jobs/${ingester}/execute`,
        {},
        {
          withCredentials: true,
          timeout: 45 * 1000,
          params: runDate ? { target_date: runDate } : {},
        },
      );
      const via = r.data?.via || "vm";
      const detail = via === "vm"
        ? `(spawned on nidp-stack-vm)`
        : `(execution: ${r.data?.execution_name || "ok"})`;
      toast.success(`Started ${ingester} ${detail}. Refresh in ~30-60s for results.`, { id: `trigger-${ingester}` });
      // Auto-refresh in 30s — VM jobs typically finish within that window
      setTimeout(fetchJobs, 30 * 1000);
    } catch (e) {
      toast.error(`Trigger failed: ${e?.response?.data?.detail || e.message}`, { id: `trigger-${ingester}` });
    } finally {
      setActing(s => ({ ...s, [ingester]: null }));
    }
  }, [fetchJobs]);

  const loadRuns = useCallback(async (ingester) => {
    setActing(s => ({ ...s, [ingester]: "runs" }));
    try {
      const [runsR, calR] = await Promise.all([
        axios.get(`${API}/api/admin/nidp/jobs/${ingester}/runs?limit=20`, { withCredentials: true }),
        axios.get(`${API}/api/admin/nidp/jobs/${ingester}/calendar?days=7`, { withCredentials: true }),
      ]);
      setExpanded(s => ({
        ...s,
        [ingester]: {
          ...(s[ingester] || {}),
          runs:     runsR.data?.runs || [],
          job_name: runsR.data?.job_name,
          calendar: calR.data?.calendar || [],
        },
      }));
    } catch (e) {
      toast.error(`Runs fetch failed: ${e?.response?.data?.detail || e.message}`);
    } finally {
      setActing(s => ({ ...s, [ingester]: null }));
    }
  }, []);

  const loadLogs = useCallback(async (ingester) => {
    setActing(s => ({ ...s, [ingester]: "logs" }));
    try {
      const r = await axios.get(
        `${API}/api/admin/nidp/jobs/${ingester}/logs?window=4h&limit=80`,
        { withCredentials: true, timeout: 60 * 1000 },
      );
      setExpanded(s => ({ ...s, [ingester]: { ...(s[ingester] || {}), logs: r.data?.lines || [] } }));
    } catch (e) {
      toast.error(`Logs fetch failed: ${e?.response?.data?.detail || e.message}`);
    } finally {
      setActing(s => ({ ...s, [ingester]: null }));
    }
  }, []);

  const toggleExpand = useCallback((ingester) => {
    setExpanded(s => {
      const isOpen = !!s[ingester]?._open;
      const next = { ...s, [ingester]: { ...(s[ingester] || {}), _open: !isOpen } };
      return next;
    });
    // Lazy-load runs on first expand
    if (!expanded[ingester]?.runs) loadRuns(ingester);
  }, [expanded, loadRuns]);

  // ── Render ────────────────────────────────────────────────────────
  return (
    <section
      data-testid="admin-nidp-jobs"
      className="rounded-2xl border border-slate-100 dark:border-slate-700 bg-white dark:bg-slate-800 p-5"
    >
      <div className="flex items-start justify-between gap-4 mb-4">
        <div>
          <h3 className="text-base font-semibold text-slate-900 dark:text-white">
            NIDP Ingestion Jobs {data ? <span className="text-slate-400 font-normal">({(data.jobs || []).length})</span> : null}
          </h3>
          <p className="text-xs text-slate-500 dark:text-slate-400 mt-1 max-w-xl">
            All NIDP services registered in <code>NIDP_INGESTERS</code> (admin_nidp.py).
            Status comes from <code>nidp.v_feed_status</code> on the VM TimescaleDB;
            Trigger spawns <code>run_service.sh</code> on <code>nidp-stack-vm</code> via cron pipeline.
            Expand a row to see recent runs and tail logs.
          </p>
        </div>
        <div className="flex items-center gap-2">
          {/* Run-date picker — controls the date passed to Trigger and
              defaults to last_trading_day from the backend. */}
          <label className="flex items-center gap-1.5 text-xs text-slate-500 dark:text-slate-400">
            <Clock className="w-3.5 h-3.5" />
            Run date
            <input
              type="date"
              value={runDate || ""}
              onChange={e => setRunDate(e.target.value || null)}
              data-testid="admin-nidp-run-date"
              max={new Date().toISOString().slice(0, 10)}
              className="rounded-md border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 text-slate-700 dark:text-slate-200 text-xs px-2 py-1.5"
              title="Date passed to every Trigger button. Default is the last trading day."
            />
          </label>
          {data?.grafana_url && (
            <a
              href={data.grafana_url}
              target="_blank"
              rel="noopener noreferrer"
              data-testid="admin-nidp-grafana-link"
              className="inline-flex items-center gap-2 rounded-lg border border-indigo-200 dark:border-indigo-700 bg-indigo-50 dark:bg-indigo-900/30 hover:bg-indigo-100 dark:hover:bg-indigo-900/50 text-indigo-700 dark:text-indigo-300 text-sm px-3 py-2"
              title="Open NIDP Job Health dashboard in Grafana"
            >
              <ExternalLink className="w-4 h-4" />
              Grafana
            </a>
          )}
          <button
            type="button"
            onClick={fetchJobs}
            disabled={loading}
            data-testid="admin-nidp-jobs-refresh"
            className="inline-flex items-center gap-2 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 hover:bg-slate-50 dark:hover:bg-slate-700 text-slate-700 dark:text-slate-200 text-sm px-3 py-2 disabled:opacity-50"
          >
            {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <RefreshCw className="w-4 h-4" />}
            Refresh
          </button>
        </div>
      </div>

      {!data && loading && (
        <div className="text-xs text-slate-500 py-4">Loading jobs…</div>
      )}

      {data && (
        <>
          <div className="text-[11px] text-slate-400 mb-2">
            project: <code>{data.project}</code> · region: <code>{data.region}</code>
          </div>
          {data.drift && (data.drift.missing_from_db?.length > 0 || data.drift.unregistered_in_canonical?.length > 0) && (
            <div className="mb-3 rounded bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-800 px-3 py-2 text-[11px] text-amber-800 dark:text-amber-200 space-y-1">
              <div className="font-semibold">Feed registration drift</div>
              {data.drift.missing_from_db?.length > 0 && (
                <div>
                  <span className="font-semibold">Not in v_feed_status ({data.drift.missing_from_db.length}):</span>{" "}
                  {data.drift.missing_from_db.join(", ")} — these jobs are deployed but their <code>nidp.source_registry</code> row is missing or never ran. Trigger them once or seed the registry.
                </div>
              )}
              {data.drift.unregistered_in_canonical?.length > 0 && (
                <div>
                  <span className="font-semibold">In DB, not in canonical list ({data.drift.unregistered_in_canonical.length}):</span>{" "}
                  {data.drift.unregistered_in_canonical.join(", ")} — these run but the Console doesn't know about them. Add to <code>NIDP_INGESTERS</code> in <code>admin_nidp.py</code>.
                </div>
              )}
            </div>
          )}
          {data.db_error && (
            <div className="mb-3 rounded bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-800 px-3 py-2 text-[11px] text-amber-800 dark:text-amber-200">
              <strong>v_feed_status unavailable:</strong> <code>{data.db_error}</code>
              <div className="mt-1 text-[10px] text-amber-700 dark:text-amber-300">
                Status / streak / rows columns will be blank. Apply migration <code>022_nidp_feed_management.sql</code> on the env's Postgres to fix.
              </div>
            </div>
          )}

          <div className="overflow-x-auto">
            <table className="min-w-full text-xs">
              <thead>
                <tr className="text-left border-b border-slate-200 dark:border-slate-700 text-slate-500 dark:text-slate-400">
                  <th className="px-2 py-2 w-6"></th>
                  <th className="px-2 py-2">Ingester</th>
                  <th className="px-2 py-2">Cadence</th>
                  <th className="px-2 py-2">This week</th>
                  <th className="px-2 py-2">Status</th>
                  <th className="px-2 py-2">Streak</th>
                  <th className="px-2 py-2">Last run</th>
                  <th className="px-2 py-2">Last success</th>
                  <th className="px-2 py-2">Rows in</th>
                  <th className="px-2 py-2 text-right">Actions</th>
                </tr>
              </thead>
              <tbody>
                {(data.jobs || []).map(j => {
                  const isOpen = expanded[j.ingester]?._open;
                  const style  = STATUS_STYLES[j.last_run_status] || STATUS_STYLES.null;
                  const streak = j.consecutive_failures || 0;
                  const triggering = acting[j.ingester] === "execute";

                  return (
                    <React.Fragment key={j.ingester}>
                      <tr className="border-b border-slate-100 dark:border-slate-700 hover:bg-slate-50 dark:hover:bg-slate-900/40">
                        <td className="px-2 py-2">
                          <button
                            type="button"
                            onClick={() => toggleExpand(j.ingester)}
                            className="text-slate-400 hover:text-slate-600 dark:hover:text-slate-200"
                          >
                            {isOpen ? <ChevronDown className="w-4 h-4" /> : <ChevronRight className="w-4 h-4" />}
                          </button>
                        </td>
                        <td className="px-2 py-2 font-mono text-slate-900 dark:text-slate-100">
                          {j.ingester}
                          {j.registered_in_db === false && (
                            <span
                              className="ml-2 align-middle inline-block px-1 py-0 rounded text-[9px] font-sans font-semibold bg-amber-100 dark:bg-amber-900/40 text-amber-700 dark:text-amber-300"
                              title="Job is deployed but has no row in nidp.source_registry — has it ever run?"
                            >
                              not in DB
                            </span>
                          )}
                        </td>
                        <td className="px-2 py-2 text-slate-500">{j.expected_freq || j.cadence}</td>
                        <td className="px-2 py-2">
                          <WeekStrip days={j.last_7_days || []} />
                          {j.schedule_cron && (
                            <div className="text-[9px] text-slate-400 font-mono mt-0.5" title={j.schedule_cron}>
                              {j.schedule_cron}
                            </div>
                          )}
                        </td>
                        <td className="px-2 py-2">
                          <span className="inline-flex items-center gap-1.5">
                            <span className={`inline-block w-2 h-2 rounded-full ${style.dot}`} />
                            <span className={style.text + " font-medium"}>
                              {j.last_run_status
                                ? j.last_run_status
                                : (j.expected_freq === "manual"
                                    ? "manual"
                                    : (j.expected_freq === "event"
                                        ? "event-driven"
                                        : "never"))}
                            </span>
                          </span>
                        </td>
                        <td className={"px-2 py-2 " + (streak > 0 ? "text-red-600 font-semibold" : "text-slate-500")}>
                          {streak}
                        </td>
                        <td className="px-2 py-2 text-slate-500" title={j.last_run_at || ""}>
                          {relTime(j.last_run_at)}
                        </td>
                        <td className="px-2 py-2 text-slate-500" title={j.last_success_at || ""}>
                          {relTime(j.last_success_at)}
                        </td>
                        <td className="px-2 py-2 text-slate-500">{j.last_rows_inserted ?? "—"}</td>
                        <td className="px-2 py-2 text-right">
                          <div className="inline-flex items-center gap-1 justify-end">
                            <button
                              type="button"
                              onClick={() => setArchive({ ingester: j.ingester })}
                              data-testid={`admin-nidp-archive-${j.ingester}`}
                              className="inline-flex items-center gap-1 rounded border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 hover:bg-slate-50 dark:hover:bg-slate-700 text-slate-700 dark:text-slate-200 text-xs px-2 py-1"
                              title="Browse archived raw feed files for this ingester"
                            >
                              <FileText className="w-3 h-3" />
                              Files
                            </button>
                            <button
                              type="button"
                              onClick={() => triggerJob(j.ingester)}
                              disabled={triggering}
                              data-testid={`admin-nidp-trigger-${j.ingester}`}
                              className="inline-flex items-center gap-1 rounded bg-indigo-600 hover:bg-indigo-700 disabled:bg-slate-300 dark:disabled:bg-slate-700 text-white text-xs px-2 py-1"
                              title={runDate ? `Trigger ${j.ingester} for ${runDate}` : `Trigger ${j.ingester}`}
                            >
                              {triggering ? <Loader2 className="w-3 h-3 animate-spin" /> : <PlayCircle className="w-3 h-3" />}
                              Trigger
                            </button>
                          </div>
                        </td>
                      </tr>

                      {isOpen && (
                        <tr className="bg-slate-50/60 dark:bg-slate-900/40">
                          <td colSpan={10} className="px-2 py-3">
                            <ExpandedRow
                              ingester={j.ingester}
                              data={expanded[j.ingester] || {}}
                              acting={acting[j.ingester]}
                              onLoadLogs={() => loadLogs(j.ingester)}
                              onReloadRuns={() => loadRuns(j.ingester)}
                              lastError={j.last_error_message}
                              lastErrorLogsUrl={j.cloud_logs_url}
                              recentLogsUrl={j.cloud_logs_url_24h}
                            />
                          </td>
                        </tr>
                      )}
                    </React.Fragment>
                  );
                })}
              </tbody>
            </table>
          </div>
        </>
      )}

      {archive && (
        <ArchiveModal
          ingester={archive.ingester}
          onClose={() => setArchive(null)}
        />
      )}
    </section>
  );
}

// ─────────────────────────────────────────────────────────────────
// Archive modal — lists every raw file the VM has saved for an
// ingester (per-date) and provides an authenticated download link.
// ─────────────────────────────────────────────────────────────────
function ArchiveModal({ ingester, onClose }) {
  const [data,   setData]   = useState(null);
  const [loading, setLoading] = useState(true);
  const [error,  setError]  = useState(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      setError(null);
      try {
        const r = await axios.get(
          `${API}/api/admin/nidp/archive/${ingester}`,
          { withCredentials: true },
        );
        if (!cancelled) setData(r.data);
      } catch (e) {
        if (!cancelled) setError(e?.response?.data?.detail || e.message);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [ingester]);

  const dl = (date, filename) =>
    `${API}/api/admin/nidp/archive/${ingester}/${date}/${filename}`;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/60 backdrop-blur-sm"
      onClick={onClose}
      data-testid="admin-nidp-archive-modal"
    >
      <div
        className="w-full max-w-3xl max-h-[85vh] overflow-y-auto rounded-xl bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 shadow-2xl"
        onClick={e => e.stopPropagation()}
      >
        <div className="px-5 py-3 border-b border-slate-100 dark:border-slate-700 flex items-center justify-between">
          <div>
            <h3 className="text-sm font-semibold text-slate-900 dark:text-white">
              Raw feed archive · <code>{ingester}</code>
            </h3>
            <p className="text-[11px] text-slate-500 dark:text-slate-400 mt-0.5">
              All raw downloads stored on <code>nidp-stack-vm</code>{" "}
              under <code>/opt/nidp/archive/{ingester}/&lt;date&gt;/</code>.
            </p>
          </div>
          <button
            onClick={onClose}
            data-testid="admin-nidp-archive-close"
            className="text-slate-400 hover:text-slate-600 dark:hover:text-slate-200 text-xs"
          >
            Close ✕
          </button>
        </div>

        <div className="p-5">
          {loading && (
            <div className="flex items-center gap-2 text-xs text-slate-500">
              <Loader2 className="w-4 h-4 animate-spin" /> Loading…
            </div>
          )}

          {error && (
            <div className="text-xs text-rose-700 bg-rose-50 dark:bg-rose-900/20 dark:text-rose-300 rounded p-3">
              {String(error)}
            </div>
          )}

          {!loading && !error && data && !data.exists && (
            <div className="text-xs text-slate-500 italic">
              No archived files yet for this ingester. Trigger a run with a Run date selected — the next download will land here automatically.
            </div>
          )}

          {!loading && !error && data?.dates?.length > 0 && (
            <div className="space-y-4">
              {data.dates.map(d => (
                <div key={d.target_date} className="rounded-lg border border-slate-100 dark:border-slate-700">
                  <div className="px-3 py-2 bg-slate-50 dark:bg-slate-900/40 text-xs font-mono text-slate-700 dark:text-slate-200 border-b border-slate-100 dark:border-slate-700 flex items-center justify-between">
                    <span>{d.target_date}</span>
                    <span className="text-slate-400">
                      {d.file_count} file{d.file_count === 1 ? "" : "s"} ·{" "}
                      {(d.total_bytes / 1024).toLocaleString(undefined, { maximumFractionDigits: 1 })} KB
                    </span>
                  </div>
                  <div className="divide-y divide-slate-100 dark:divide-slate-800">
                    {(d.files || []).map(f => (
                      <a
                        key={f.filename}
                        href={dl(d.target_date, f.filename)}
                        target="_blank"
                        rel="noopener noreferrer"
                        data-testid={`admin-nidp-archive-dl-${ingester}-${d.target_date}-${f.filename}`}
                        className="flex items-center justify-between px-3 py-2 text-xs hover:bg-indigo-50 dark:hover:bg-indigo-900/20 group"
                      >
                        <span className="font-mono text-slate-700 dark:text-slate-200 truncate group-hover:text-indigo-700 dark:group-hover:text-indigo-300">
                          {f.filename}
                        </span>
                        <span className="text-slate-400 ml-3 shrink-0">
                          {(f.size_bytes / 1024).toLocaleString(undefined, { maximumFractionDigits: 1 })} KB · download ↓
                        </span>
                      </a>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function CalendarStrip({ calendar }) {
  if (!calendar || calendar.length === 0) {
    return <div className="text-[11px] text-slate-400 italic">No history.</div>;
  }
  // Render oldest → newest left → right (calendar is desc; reverse).
  const cells = [...calendar].reverse();
  // Indian markets are closed on Saturday (6) & Sunday (0). When a cell
  // has no run on a weekend, that's expected — show it as an explicitly
  // muted "non-trading day" tile so the user doesn't read it as a miss.
  const isWeekend = (iso) => {
    const d = new Date(`${iso}T00:00:00`);
    const wd = d.getUTCDay(); // iso parses as UTC; weekday is correct
    return wd === 0 || wd === 6;
  };
  return (
    <div className="flex items-center gap-1" data-testid="calendar-strip">
      {cells.map(c => {
        const weekend = isWeekend(c.date);
        let cls;
        let tip;
        if (c.status) {
          cls = CAL_BG[c.status];
          tip = `${c.date} · ${c.status} · ${c.run_count} run(s) · ${c.rows_total ?? 0} rows`;
        } else if (weekend) {
          // Diagonal-stripe pattern via Tailwind to clearly distinguish
          // a non-trading day from a missed run on a weekday.
          cls = "bg-slate-100 dark:bg-slate-800 border border-dashed border-slate-300 dark:border-slate-600";
          tip = `${c.date} · Non-trading day (weekend)`;
        } else {
          cls = "bg-slate-200 dark:bg-slate-700";
          tip = `${c.date} · no run`;
        }
        return (
          <div
            key={c.date}
            title={tip}
            data-testid={`calendar-cell-${c.date}`}
            className={`h-5 flex-1 rounded ${cls}`}
            style={{ minWidth: "20px" }}
          />
        );
      })}
    </div>
  );
}

function ExpandedRow({ ingester, data, acting, onLoadLogs, onReloadRuns, lastError, lastErrorLogsUrl, recentLogsUrl }) {
  const runs = data.runs || [];
  const logs = data.logs;
  const calendar = data.calendar || [];

  return (
    <div className="space-y-3 pl-7 pr-2">
      {/* 7-day calendar strip */}
      <div>
        <div className="flex items-center justify-between mb-1">
          <div className="text-[11px] uppercase tracking-wide text-slate-500 dark:text-slate-400">
            Last 7 days
          </div>
          <div className="text-[10px] text-slate-400">oldest → today · dashed = non-trading day · hover for details</div>
        </div>
        <CalendarStrip calendar={calendar} />
      </div>

      {/* Last-error banner with direct Cloud Logs deep-link */}
      {lastError && (
        <div className="rounded bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 px-3 py-2 text-[11px] text-red-700 dark:text-red-300 font-mono break-words whitespace-pre-wrap">
          <div className="font-sans font-semibold mb-1 flex items-center justify-between">
            <span>Last error</span>
            {lastErrorLogsUrl && (
              <a
                href={lastErrorLogsUrl}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-1 text-red-700 dark:text-red-300 hover:underline text-[11px]"
              >
                <ExternalLink className="w-3 h-3" />
                Open in Cloud Console
              </a>
            )}
          </div>
          {lastError}
        </div>
      )}

      {/* Recent runs table — Cloud Logs link per row */}
      <div>
        <div className="flex items-center justify-between mb-1">
          <div className="text-[11px] uppercase tracking-wide text-slate-500 dark:text-slate-400">
            Recent runs (nidp.job_log)
          </div>
          <div className="flex items-center gap-3">
            {recentLogsUrl && (
              <a
                href={recentLogsUrl}
                target="_blank"
                rel="noopener noreferrer"
                className="text-[11px] text-slate-500 hover:text-slate-700 inline-flex items-center gap-1"
              >
                <ExternalLink className="w-3 h-3" />
                last 24h logs
              </a>
            )}
            <button onClick={onReloadRuns} disabled={acting === "runs"} className="text-[11px] text-slate-500 hover:text-slate-700 inline-flex items-center gap-1">
              {acting === "runs" ? <Loader2 className="w-3 h-3 animate-spin" /> : <RefreshCw className="w-3 h-3" />}
              reload
            </button>
          </div>
        </div>
        {runs.length === 0 && (
          <div className="text-[11px] text-slate-400 italic">No runs found in job_log.</div>
        )}
        {runs.length > 0 && (
          <table className="w-full text-[11px]">
            <thead>
              <tr className="text-left text-slate-400">
                <th className="py-1">Started</th>
                <th className="py-1">Status</th>
                <th className="py-1">Duration</th>
                <th className="py-1">Rows in / skip</th>
                <th className="py-1">Error</th>
                <th className="py-1 text-right">Logs</th>
              </tr>
            </thead>
            <tbody>
              {runs.map(r => {
                const isFailed = r.status === "FAILED" || r.status === "PARTIAL";
                return (
                  <tr key={r.run_id} className="border-t border-slate-200 dark:border-slate-700 align-top">
                    <td className="py-1 text-slate-600 dark:text-slate-300 whitespace-nowrap">{r.started_at?.replace("T", " ").slice(0, 19) || "—"}</td>
                    <td className="py-1">
                      <span className={(STATUS_STYLES[r.status] || STATUS_STYLES.null).text + " font-medium"}>
                        {r.status}
                      </span>
                    </td>
                    <td className="py-1 text-slate-500 whitespace-nowrap">{r.duration_ms ? `${(r.duration_ms / 1000).toFixed(1)}s` : "—"}</td>
                    <td className="py-1 text-slate-500 whitespace-nowrap">{r.rows_inserted ?? "—"} / {r.rows_skipped ?? "—"}</td>
                    <td className={"py-1 max-w-xl break-words whitespace-pre-wrap " + (isFailed ? "text-red-600 dark:text-red-400" : "text-slate-500")}>
                      {r.error_class ? <span className="font-mono text-[10px]">[{r.error_class}] </span> : null}
                      {r.error_message || ""}
                    </td>
                    <td className="py-1 text-right">
                      {r.cloud_logs_url ? (
                        <a
                          href={r.cloud_logs_url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="inline-flex items-center gap-1 text-indigo-600 dark:text-indigo-400 hover:underline whitespace-nowrap"
                          title="Open Cloud Logs filtered to this run window"
                        >
                          <ExternalLink className="w-3 h-3" />
                          GCP
                        </a>
                      ) : "—"}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>

      {/* Inline tail (VM /opt/nidp/logs/<ingester>/<ingester>.log) */}
      <div>
        <div className="flex items-center justify-between mb-1">
          <div className="text-[11px] uppercase tracking-wide text-slate-500 dark:text-slate-400">
            VM logs (inline tail · /opt/nidp/logs/{"{ingester}"}/{"{ingester}"}.log)
          </div>
          <button onClick={onLoadLogs} disabled={acting === "logs"} className="text-[11px] text-slate-500 hover:text-slate-700 inline-flex items-center gap-1">
            {acting === "logs" ? <Loader2 className="w-3 h-3 animate-spin" /> : <FileText className="w-3 h-3" />}
            {logs ? "reload logs" : "tail logs"}
          </button>
        </div>
        {logs && logs.length === 0 && (
          <div className="text-[11px] text-slate-400 italic">No log lines in window.</div>
        )}
        {logs && logs.length > 0 && (
          <pre className="max-h-72 overflow-auto bg-slate-900 dark:bg-black text-slate-200 text-[10px] font-mono p-2 rounded leading-relaxed">
            {logs.join("\n")}
          </pre>
        )}
      </div>
    </div>
  );
}
