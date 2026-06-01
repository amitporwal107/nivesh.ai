import { useState } from "react";
import { PlayCircle, RefreshCw, Loader2, ChevronDown, ChevronRight, AlertTriangle } from "lucide-react";
import { Card, CardContent, CardLabel } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { http } from "@/services/api/http";
import { NidpError } from "./NidpError";
import { useToastStore } from "@/stores/toast.store";
import { useQuery, useQueryClient } from "@tanstack/react-query";

interface FeedDay { date: string; is_today: boolean; status: string | null; run_count: number }
interface Job {
  ingester: string;
  cadence: string;
  job_name: string;
  source_class: string;
  expected_freq: string;
  schedule_cron: string | null;
  is_primary: boolean;
  last_run_status: string | null;
  consecutive_failures: number;
  last_run_at: string | null;
  last_success_at: string | null;
  last_failure_at: string | null;
  last_target_date: string | null;
  last_rows_inserted: number | null;
  last_run_duration_ms: number | null;
  success_count: number;
  failure_count: number;
  last_error_message: string | null;
  cloud_logs_url: string | null;
  last_7_days: FeedDay[];
}

interface JobsData {
  jobs: Job[];
  project: string;
  region: string;
  last_trading_day: string;
}

const STATUS_TONE: Record<string, "good" | "neg" | "warm" | "default"> = {
  OK: "good", SUCCESS: "good", FAILED: "neg", PARTIAL: "warm", RUNNING: "default", SKIPPED: "default",
};
const DAY_COLOR: Record<string, string> = {
  OK: "bg-pos", SUCCESS: "bg-pos", FAILED: "bg-neg", PARTIAL: "bg-warm",
};

function relTime(iso?: string | null) {
  if (!iso) return "—";
  const diff = (Date.now() - new Date(iso).getTime()) / 1000;
  if (diff < 60) return `${Math.round(diff)}s ago`;
  if (diff < 3600) return `${Math.round(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.round(diff / 3600)}h ago`;
  return `${Math.round(diff / 86400)}d ago`;
}

export function JobsPanel() {
  const push = useToastStore((s) => s.push);
  const qc = useQueryClient();
  const [expanded, setExpanded] = useState<string | null>(null);
  const [triggering, setTriggering] = useState<Record<string, boolean>>({});

  const { data, isFetching, refetch, error } = useQuery({
    queryKey: ["nidp", "jobs"],
    queryFn: () => http<JobsData>({ path: "/api/admin/nidp/jobs", timeoutMs: 30_000 }).then((r) => r.data),
    staleTime: 60_000,
  });

  const jobs = data?.jobs ?? [];
  const failedJobs = jobs.filter((j) => j.last_run_status === "FAILED" || j.consecutive_failures > 0);

  const trigger = async (ingester: string) => {
    if (!window.confirm(`Trigger "${ingester}" now? This runs immediately on the NIDP VM via cron.`)) return;
    setTriggering((t) => ({ ...t, [ingester]: true }));
    try {
      await http({ method: "POST", path: `/api/admin/nidp/jobs/${encodeURIComponent(ingester)}/execute`, body: {} });
      push({ kind: "success", title: `"${ingester}" triggered on VM` });
      setTimeout(() => qc.invalidateQueries({ queryKey: ["nidp", "jobs"] }), 3000);
    } catch (e: unknown) {
      push({ kind: "error", title: `Failed to trigger "${ingester}"`, description: e instanceof Error ? e.message : undefined });
    } finally {
      setTriggering((t) => ({ ...t, [ingester]: false }));
    }
  };

  return (
    <div className="space-y-4">
      {/* Failures banner */}
      {failedJobs.length > 0 && (
        <div className="flex items-start gap-2 rounded-lg border border-[rgb(var(--neg)/0.25)] bg-[rgb(var(--neg)/0.06)] px-4 py-3">
          <AlertTriangle className="w-4 h-4 text-neg shrink-0 mt-0.5" />
          <div className="text-sm text-ink-2">
            <strong className="text-neg">{failedJobs.length} ingester{failedJobs.length > 1 ? "s" : ""} failing:</strong>{" "}
            {failedJobs.map((j) => j.ingester).join(", ")}
          </div>
        </div>
      )}

      <Card>
        <CardContent className="p-5">
          <div className="flex items-center justify-between mb-4">
            <div>
              <CardLabel>NIDP Ingesters — cron on VM ({jobs.length} total)</CardLabel>
              {data?.last_trading_day && (
                <div className="text-[10px] text-ink-3 mt-0.5">Last trading day: {data.last_trading_day}</div>
              )}
            </div>
            <Button size="sm" variant="outline" onClick={() => refetch()} disabled={isFetching}>
              {isFetching ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <RefreshCw className="w-3.5 h-3.5" />}
            </Button>
          </div>

          {error && <NidpError err={error} />}

          <div className="space-y-1">
            {jobs.map((j) => {
              const isExp = expanded === j.ingester;
              const tone = STATUS_TONE[j.last_run_status ?? ""] ?? "default";
              return (
                <div key={j.ingester} className="rounded-lg border border-hairline overflow-hidden">
                  <div className="flex items-center gap-2 px-3 py-2.5">
                    <button
                      className="flex-1 flex items-center gap-2 text-left min-w-0"
                      onClick={() => setExpanded(isExp ? null : j.ingester)}
                    >
                      {isExp ? <ChevronDown className="w-3.5 h-3.5 text-ink-3 shrink-0" /> : <ChevronRight className="w-3.5 h-3.5 text-ink-3 shrink-0" />}
                      <span className="font-mono text-xs text-ink-2 truncate">{j.ingester}</span>
                      {!j.is_primary && <span className="text-[9px] text-ink-3 border border-hairline rounded px-1">secondary</span>}
                    </button>

                    {/* 7-day sparkbar */}
                    <div className="hidden sm:flex items-end gap-px h-4 shrink-0">
                      {(j.last_7_days ?? []).map((day, i) => (
                        <div
                          key={i}
                          title={`${day.date}: ${day.status ?? "no run"}`}
                          className={`w-2 rounded-sm ${day.status ? (DAY_COLOR[day.status] ?? "bg-surface-2") : "bg-surface-2"} ${day.is_today ? "ring-1 ring-accent" : ""} opacity-80`}
                          style={{ height: day.run_count > 0 ? "14px" : "4px" }}
                        />
                      ))}
                    </div>

                    <div className="flex items-center gap-2 shrink-0">
                      {j.last_run_status && <Badge tone={tone}>{j.last_run_status}</Badge>}
                      <span className="text-[10px] text-ink-3 hidden sm:inline">{relTime(j.last_run_at)}</span>
                      {j.consecutive_failures > 0 && (
                        <span className="text-[10px] font-bold text-neg">{j.consecutive_failures}✗</span>
                      )}
                    </div>

                    <button
                      onClick={() => trigger(j.ingester)}
                      disabled={triggering[j.ingester]}
                      title="Trigger now on VM"
                      className="h-7 w-7 flex items-center justify-center rounded border border-hairline text-ink-2 hover:text-accent hover:border-accent transition-colors disabled:opacity-40"
                    >
                      {triggering[j.ingester] ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <PlayCircle className="w-3.5 h-3.5" />}
                    </button>
                  </div>

                  {isExp && (
                    <div className="border-t border-hairline bg-surface-1 px-4 py-3 text-[11px] text-ink-3 space-y-2">
                      <div className="flex flex-wrap gap-x-5 gap-y-1">
                        <span>Source: <strong className="text-ink-2">{j.source_class}</strong></span>
                        <span>Freq: <strong className="text-ink-2">{j.expected_freq}</strong></span>
                        {j.schedule_cron && <span>Cron: <code className="text-ink-2 bg-surface-2 px-1 rounded">{j.schedule_cron}</code></span>}
                        <span>Cadence: <strong className="text-ink-2">{j.cadence}</strong></span>
                        <span>Last run: <strong className="text-ink-2">{relTime(j.last_run_at)}</strong></span>
                        {j.last_target_date && <span>Target date: <strong className="text-ink-2">{j.last_target_date}</strong></span>}
                        {j.last_run_duration_ms != null && <span>Duration: <strong className="text-ink-2">{(j.last_run_duration_ms / 1000).toFixed(1)}s</strong></span>}
                        {j.last_rows_inserted != null && <span>Rows inserted: <strong className="text-ink-2">{j.last_rows_inserted.toLocaleString()}</strong></span>}
                        <span>✓ {j.success_count} runs / ✗ {j.failure_count} fails</span>
                      </div>
                      {j.last_error_message && (
                        <div className="text-neg font-mono text-[10px] bg-[rgb(var(--neg)/0.06)] rounded p-2 break-all">{j.last_error_message}</div>
                      )}
                      {j.cloud_logs_url && (
                        <a href={j.cloud_logs_url} target="_blank" rel="noreferrer" className="text-accent hover:underline text-[10px]">
                          View GCP logs →
                        </a>
                      )}
                    </div>
                  )}
                </div>
              );
            })}
            {!isFetching && jobs.length === 0 && !error && (
              <div className="text-center text-sm text-ink-3 py-8">No ingesters returned.</div>
            )}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
