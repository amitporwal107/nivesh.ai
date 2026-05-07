import React, { useEffect, useState, useCallback } from "react";
import axios from "axios";
import {
  PlayCircle, RefreshCw, Loader2, ChevronDown, ChevronRight,
  CheckCircle2, XCircle, AlertTriangle, Clock, FileText,
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

  const fetchJobs = useCallback(async () => {
    setLoading(true);
    try {
      const r = await axios.get(`${API}/api/admin/nidp/jobs`, { withCredentials: true });
      setData(r.data);
    } catch (e) {
      toast.error(`Failed to load jobs: ${e?.response?.data?.detail || e.message}`);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchJobs(); }, [fetchJobs]);

  const triggerJob = useCallback(async (ingester) => {
    setActing(s => ({ ...s, [ingester]: "execute" }));
    toast.loading(`Triggering ${ingester}...`, { id: `trigger-${ingester}` });
    try {
      const r = await axios.post(
        `${API}/api/admin/nidp/jobs/${ingester}/execute`, {},
        { withCredentials: true, timeout: 45 * 1000 },
      );
      toast.success(`Started ${ingester} (execution: ${r.data?.execution_name || "ok"}). Refresh in ~30-60s for results.`, { id: `trigger-${ingester}` });
      // Auto-refresh in 30s — Cloud Run jobs typically finish in that window
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
      const r = await axios.get(
        `${API}/api/admin/nidp/jobs/${ingester}/runs?limit=10`,
        { withCredentials: true },
      );
      setExpanded(s => ({ ...s, [ingester]: { ...(s[ingester] || {}), runs: r.data?.runs || [] } }));
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
            NIDP Ingestion Jobs
          </h3>
          <p className="text-xs text-slate-500 dark:text-slate-400 mt-1 max-w-xl">
            All 13 NIDP Cloud Run jobs (11 ingesters + snapshot_builder + yfinance_backfill).
            Status comes from <code>nidp.v_feed_status</code>; Trigger fires <code>gcloud run jobs execute</code>.
            Expand a row to see recent runs and tail logs.
          </p>
        </div>
        <button
          type="button"
          onClick={fetchJobs}
          disabled={loading}
          className="inline-flex items-center gap-2 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 hover:bg-slate-50 dark:hover:bg-slate-700 text-slate-700 dark:text-slate-200 text-sm px-3 py-2 disabled:opacity-50"
        >
          {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <RefreshCw className="w-4 h-4" />}
          Refresh
        </button>
      </div>

      {!data && loading && (
        <div className="text-xs text-slate-500 py-4">Loading jobs…</div>
      )}

      {data && (
        <>
          <div className="text-[11px] text-slate-400 mb-2">
            project: <code>{data.project}</code> · region: <code>{data.region}</code>
          </div>
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
                  <th className="px-2 py-2">Status</th>
                  <th className="px-2 py-2">Streak</th>
                  <th className="px-2 py-2">Last run</th>
                  <th className="px-2 py-2">Rows in</th>
                  <th className="px-2 py-2">Image</th>
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
                        <td className="px-2 py-2 font-mono text-slate-900 dark:text-slate-100">{j.ingester}</td>
                        <td className="px-2 py-2 text-slate-500">{j.cadence}</td>
                        <td className="px-2 py-2">
                          <span className="inline-flex items-center gap-1.5">
                            <span className={`inline-block w-2 h-2 rounded-full ${style.dot}`} />
                            <span className={style.text + " font-medium"}>{j.last_run_status || "never"}</span>
                          </span>
                        </td>
                        <td className={"px-2 py-2 " + (streak > 0 ? "text-red-600 font-semibold" : "text-slate-500")}>
                          {streak}
                        </td>
                        <td className="px-2 py-2 text-slate-500" title={j.last_run_at || ""}>
                          {relTime(j.last_run_at)}
                        </td>
                        <td className="px-2 py-2 text-slate-500">{j.last_rows_inserted ?? "—"}</td>
                        <td className="px-2 py-2 text-[10px] text-slate-400 max-w-[200px] truncate" title={j.image || ""}>
                          {j.image ? j.image.split("/").pop() : "—"}
                        </td>
                        <td className="px-2 py-2 text-right">
                          <button
                            type="button"
                            onClick={() => triggerJob(j.ingester)}
                            disabled={triggering}
                            className="inline-flex items-center gap-1 rounded bg-indigo-600 hover:bg-indigo-700 disabled:bg-slate-300 dark:disabled:bg-slate-700 text-white text-xs px-2 py-1"
                          >
                            {triggering ? <Loader2 className="w-3 h-3 animate-spin" /> : <PlayCircle className="w-3 h-3" />}
                            Trigger
                          </button>
                        </td>
                      </tr>

                      {isOpen && (
                        <tr className="bg-slate-50/60 dark:bg-slate-900/40">
                          <td colSpan={9} className="px-2 py-3">
                            <ExpandedRow
                              ingester={j.ingester}
                              data={expanded[j.ingester] || {}}
                              acting={acting[j.ingester]}
                              onLoadLogs={() => loadLogs(j.ingester)}
                              onReloadRuns={() => loadRuns(j.ingester)}
                              lastError={j.last_error_message}
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
    </section>
  );
}

function ExpandedRow({ ingester, data, acting, onLoadLogs, onReloadRuns, lastError }) {
  const runs = data.runs || [];
  const logs = data.logs;

  return (
    <div className="space-y-3 pl-7 pr-2">
      {lastError && (
        <div className="rounded bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 px-3 py-2 text-[11px] text-red-700 dark:text-red-300 font-mono break-all">
          <strong className="font-sans">Last error:</strong> {lastError}
        </div>
      )}

      <div>
        <div className="flex items-center justify-between mb-1">
          <div className="text-[11px] uppercase tracking-wide text-slate-500 dark:text-slate-400">
            Recent runs (nidp.job_log)
          </div>
          <button onClick={onReloadRuns} disabled={acting === "runs"} className="text-[11px] text-slate-500 hover:text-slate-700 inline-flex items-center gap-1">
            {acting === "runs" ? <Loader2 className="w-3 h-3 animate-spin" /> : <RefreshCw className="w-3 h-3" />}
            reload
          </button>
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
              </tr>
            </thead>
            <tbody>
              {runs.map(r => (
                <tr key={r.run_id} className="border-t border-slate-200 dark:border-slate-700">
                  <td className="py-1 text-slate-600 dark:text-slate-300">{r.started_at?.replace("T", " ").slice(0, 19) || "—"}</td>
                  <td className="py-1">
                    <span className={(STATUS_STYLES[r.status] || STATUS_STYLES.null).text + " font-medium"}>
                      {r.status}
                    </span>
                  </td>
                  <td className="py-1 text-slate-500">{r.duration_ms ? `${(r.duration_ms / 1000).toFixed(1)}s` : "—"}</td>
                  <td className="py-1 text-slate-500">{r.rows_inserted ?? "—"} / {r.rows_skipped ?? "—"}</td>
                  <td className="py-1 text-red-600 dark:text-red-400 max-w-md truncate" title={r.error_message || ""}>
                    {r.error_class ? `[${r.error_class}] ` : ""}{r.error_message || ""}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <div>
        <div className="flex items-center justify-between mb-1">
          <div className="text-[11px] uppercase tracking-wide text-slate-500 dark:text-slate-400">
            Cloud Run logs (last 4h)
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
