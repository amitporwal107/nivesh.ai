import React, { useEffect, useState, useCallback } from "react";
import axios from "axios";
import {
  PlayCircle, PauseCircle, Loader2, RefreshCw,
  CheckCircle2, XCircle, AlertTriangle,
} from "lucide-react";
import { toast } from "sonner";

const API = process.env.REACT_APP_BACKEND_URL;

/**
 * Admin → Infra & Data → Pipeline Runner
 *
 * One-click full-pipeline orchestration. Replaces the global stale-data
 * banner — admins now manage the pipeline from a dedicated panel instead
 * of getting prompts on every page.
 */
export default function PipelineRunner() {
  const [summary, setSummary] = useState(null);
  const [runState, setRunState] = useState(null);
  const [paused, setPaused] = useState(false);
  const [running, setRunning] = useState(false);

  const fetchAll = useCallback(async () => {
    try {
      const [s, p, r] = await Promise.all([
        axios.get(`${API}/api/data-health/summary`, { withCredentials: true }),
        axios.get(`${API}/api/data-health/pause-status`, { withCredentials: true }),
        axios.get(`${API}/api/data-health/run-status`, { withCredentials: true }),
      ]);
      setSummary(s.data);
      setPaused(!!p.data?.paused);
      setRunState(r.data);
      if (r.data?.running) setRunning(true);
    } catch (e) { /* silent */ }
  }, []);

  useEffect(() => {
    fetchAll();
    const t = setInterval(fetchAll, running ? 4000 : 30000);
    return () => clearInterval(t);
  }, [fetchAll, running]);

  const runPipeline = useCallback(async () => {
    if (running) return;
    setRunning(true);
    toast.loading("Pipeline started — running in background...", { id: "pipeline-run" });
    try {
      await axios.post(`${API}/api/data-health/run-all`, {}, {
        withCredentials: true, timeout: 30 * 1000,
      });
      // Polling loop — fetchAll handles re-render every 4s while running
      const startedAt = Date.now();
      const HARD_CAP_MS = 10 * 60 * 1000;
      while (Date.now() - startedAt < HARD_CAP_MS) {
        await new Promise((r) => setTimeout(r, 4000));
        let st;
        try {
          const sr = await axios.get(`${API}/api/data-health/run-status`, { withCredentials: true });
          st = sr.data;
          setRunState(st);
        } catch { continue; }
        if (st?.running) {
          const cs = st.current_step || "starting";
          const done = (st.steps || []).length;
          toast.loading(`Pipeline running — step ${done + 1} (${cs})...`, { id: "pipeline-run" });
        } else if (st?.finished_at) {
          const failed = (st.steps || []).filter((s) => !s.ok);
          if (st.ok) {
            toast.success(`Pipeline complete — all ${(st.steps || []).length} steps green. Cron paused.`,
              { id: "pipeline-run", duration: 8000 });
            setPaused(true);
          } else {
            toast.error(`Pipeline finished with ${failed.length} failure(s): ${failed.map((s) => s.step).join(", ")}`,
              { id: "pipeline-run", duration: 10000 });
          }
          await fetchAll();
          break;
        }
      }
    } catch (e) {
      toast.error(e?.response?.status === 403
        ? "Admin only — only admins can trigger the pipeline."
        : `Pipeline run failed: ${e?.message || "network error"}`,
        { id: "pipeline-run", duration: 8000 });
    } finally {
      setRunning(false);
    }
  }, [running, fetchAll]);

  const togglePause = useCallback(async () => {
    try {
      if (paused) {
        await axios.post(`${API}/api/data-health/resume`, {}, { withCredentials: true });
        toast.success("Cron schedule resumed.");
        setPaused(false);
      } else {
        // No "pause without run" endpoint — just send the resume opposite
        await axios.post(`${API}/api/data-health/resume`, {}, { withCredentials: true });
        toast.info("Pause flag controlled by pipeline run. Run pipeline to auto-pause on success.");
      }
      await fetchAll();
    } catch { toast.error("Failed to toggle cron schedule."); }
  }, [paused, fetchAll]);

  const issues = summary?.issues || [];
  const status = summary?.status || "ok";
  const steps = runState?.steps || [];
  const isRunningNow = runState?.running;

  // Status pill (top)
  let pillTone = "bg-slate-100 text-slate-700 border-slate-200";
  let pillLabel = "Healthy";
  let PillIcon = CheckCircle2;
  if (paused) {
    pillTone = "bg-emerald-100 text-emerald-800 border-emerald-200";
    pillLabel = "Paused (data fresh)";
    PillIcon = PauseCircle;
  } else if (status === "error") {
    pillTone = "bg-rose-100 text-rose-800 border-rose-200";
    pillLabel = `Errors (${issues.filter((i) => i.severity === "error").length})`;
    PillIcon = XCircle;
  } else if (status === "warn") {
    pillTone = "bg-amber-100 text-amber-800 border-amber-200";
    pillLabel = `Warnings (${issues.length})`;
    PillIcon = AlertTriangle;
  }

  return (
    <div
      className="rounded-xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 p-5"
      data-testid="admin-pipeline-runner"
    >
      <div className="flex items-start justify-between gap-3 mb-4 flex-wrap">
        <div>
          <h3 className="text-base font-bold text-slate-900 dark:text-white">Pipeline Runner</h3>
          <p className="text-xs text-slate-500 dark:text-slate-400 mt-0.5">
            Run AMFI NAV ingestion → analytics sweep → V3 rescore → MS ratings → scrape cleanup → mirror.
            On success the cron schedule is paused automatically.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <span
            className={`inline-flex items-center gap-1 px-2.5 py-1 rounded-md text-[11px] font-semibold border ${pillTone}`}
            data-testid="pipeline-status-pill"
          >
            <PillIcon className="w-3.5 h-3.5" />{pillLabel}
          </span>
          <button
            onClick={fetchAll}
            className="p-1.5 rounded-md hover:bg-slate-100 dark:hover:bg-slate-800"
            title="Refresh"
            data-testid="pipeline-refresh"
          >
            <RefreshCw className="w-4 h-4 text-slate-500" />
          </button>
        </div>
      </div>

      {/* Issue list */}
      {issues.length > 0 && !paused && (
        <div className="mb-4 space-y-1.5" data-testid="pipeline-issues">
          {issues.map((i, idx) => {
            const tone = i.severity === "error"
              ? "border-rose-200 bg-rose-50 text-rose-800 dark:bg-rose-900/20 dark:text-rose-300"
              : "border-amber-200 bg-amber-50 text-amber-800 dark:bg-amber-900/20 dark:text-amber-300";
            const Icon = i.severity === "error" ? XCircle : AlertTriangle;
            return (
              <div
                key={idx}
                className={`text-[12.5px] flex items-start gap-2 px-3 py-2 rounded-md border ${tone}`}
                data-testid={`pipeline-issue-${i.job}`}
              >
                <Icon className="w-3.5 h-3.5 mt-0.5 flex-shrink-0" />
                <div className="flex-1">
                  <span className="font-semibold">{i.label}:</span>{" "}
                  <span className="opacity-90">{i.message}</span>
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* Action row */}
      <div className="flex items-center gap-2 flex-wrap mb-4">
        <button
          onClick={runPipeline}
          disabled={running || isRunningNow}
          className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md text-[12.5px] font-semibold ${
            running || isRunningNow
              ? "bg-slate-200 text-slate-500 cursor-not-allowed"
              : "bg-emerald-600 hover:bg-emerald-700 text-white"
          }`}
          data-testid="pipeline-run-now"
        >
          {running || isRunningNow ? (
            <><Loader2 className="w-3.5 h-3.5 animate-spin" />Running...</>
          ) : (
            <><PlayCircle className="w-3.5 h-3.5" />Run pipeline now</>
          )}
        </button>
        {paused && (
          <button
            onClick={togglePause}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md text-[12.5px] font-semibold border border-slate-300 dark:border-slate-700 hover:bg-slate-100 dark:hover:bg-slate-800 text-slate-700 dark:text-slate-300"
            data-testid="pipeline-resume-cron"
          >
            <PlayCircle className="w-3.5 h-3.5" />Resume cron
          </button>
        )}
      </div>

      {/* Last run summary */}
      {(steps.length > 0 || isRunningNow) && (
        <div data-testid="pipeline-last-run" className="border-t border-slate-200 dark:border-slate-700 pt-3">
          <div className="flex items-center justify-between mb-2">
            <span className="text-[10px] uppercase tracking-wider font-bold text-slate-500 dark:text-slate-400">
              {isRunningNow ? "Current run" : "Last run"}
            </span>
            {runState?.finished_at && (
              <span className="text-[10px] text-slate-400">
                Finished {new Date(runState.finished_at).toLocaleString()}
              </span>
            )}
          </div>
          <div className="space-y-1">
            {steps.map((s, idx) => (
              <div
                key={idx}
                className="flex items-center justify-between text-[12px] gap-2"
                data-testid={`pipeline-step-${s.step}`}
              >
                <div className="flex items-center gap-2 min-w-0">
                  {s.ok
                    ? <CheckCircle2 className="w-3.5 h-3.5 text-emerald-600 flex-shrink-0" />
                    : <XCircle className="w-3.5 h-3.5 text-rose-600 flex-shrink-0" />}
                  <span className="font-medium text-slate-800 dark:text-slate-200">{s.step}</span>
                  {s.error && (
                    <span className="text-[11px] text-rose-600 truncate">— {s.error}</span>
                  )}
                </div>
                <span className="text-[11px] font-mono tabular-nums text-slate-500 dark:text-slate-400 flex-shrink-0">
                  {(s.duration_s || 0).toFixed(1)}s
                </span>
              </div>
            ))}
            {isRunningNow && runState?.current_step && (
              <div className="flex items-center gap-2 text-[12px] text-slate-600 dark:text-slate-300 mt-1">
                <Loader2 className="w-3.5 h-3.5 animate-spin text-emerald-600" />
                <span className="font-medium">{runState.current_step}</span>
                <span className="text-[11px] text-slate-400">running...</span>
              </div>
            )}
          </div>
          {runState?.message && !isRunningNow && (
            <div className="mt-2 text-[11px] text-slate-500 dark:text-slate-400 italic">
              {runState.message}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
