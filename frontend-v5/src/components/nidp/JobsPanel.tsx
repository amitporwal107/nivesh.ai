import { useState } from "react";
import { PlayCircle, RefreshCw, Loader2, ChevronDown, ChevronRight, CheckCircle2, XCircle, Clock, AlertTriangle } from "lucide-react";
import { Card, CardContent, CardLabel } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { http } from "@/services/api/http";
import { useToastStore } from "@/stores/toast.store";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";

interface Job {
  job_name: string;
  display_name?: string;
  last_run_at?: string;
  last_status?: string;
  last_duration_seconds?: number;
  success_rate_7d?: number;
  description?: string;
}

function relTime(iso?: string) {
  if (!iso) return "—";
  const diff = (Date.now() - new Date(iso).getTime()) / 1000;
  if (diff < 60) return `${Math.round(diff)}s ago`;
  if (diff < 3600) return `${Math.round(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.round(diff / 3600)}h ago`;
  return `${Math.round(diff / 86400)}d ago`;
}

const STATUS_TONE: Record<string, "good" | "neg" | "warm" | "default"> = {
  OK: "good", SUCCESS: "good", PARTIAL: "warm", FAILED: "neg", RUNNING: "default", SKIPPED: "default",
};

export function JobsPanel() {
  const push = useToastStore((s) => s.push);
  const qc = useQueryClient();
  const [expanded, setExpanded] = useState<string | null>(null);
  const [triggering, setTriggering] = useState<Record<string, boolean>>({});

  const { data: jobs = [], isFetching, refetch } = useQuery({
    queryKey: ["nidp", "jobs"],
    queryFn: () => http<{ jobs: Job[] }>({ path: "/api/admin/nidp/jobs" }).then((r) => r.data.jobs),
    refetchInterval: 30_000,
  });

  const trigger = async (jobName: string) => {
    if (!window.confirm(`Trigger job "${jobName}"?`)) return;
    setTriggering((t) => ({ ...t, [jobName]: true }));
    try {
      await http({ method: "POST", path: `/api/admin/nidp/jobs/${encodeURIComponent(jobName)}/trigger`, body: {} });
      push({ kind: "success", title: `Job "${jobName}" triggered` });
      setTimeout(() => qc.invalidateQueries({ queryKey: ["nidp", "jobs"] }), 2000);
    } catch { push({ kind: "error", title: `Failed to trigger "${jobName}"` }); }
    finally { setTriggering((t) => ({ ...t, [jobName]: false })); }
  };

  return (
    <Card>
      <CardContent className="p-5">
        <div className="flex items-center justify-between mb-4">
          <CardLabel>Cloud Run Jobs ({jobs.length})</CardLabel>
          <Button size="sm" variant="outline" onClick={() => refetch()} disabled={isFetching}>
            {isFetching ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <RefreshCw className="w-3.5 h-3.5" />}
          </Button>
        </div>

        <div className="space-y-2">
          {jobs.map((j) => {
            const isExpanded = expanded === j.job_name;
            const tone = STATUS_TONE[j.last_status ?? ""] ?? "default";
            return (
              <div key={j.job_name} className="rounded-lg border border-hairline overflow-hidden">
                <div className="flex items-center gap-3 px-3 py-3">
                  {/* status dot */}
                  <div className={`w-2 h-2 rounded-full shrink-0 ${j.last_status === "RUNNING" ? "bg-accent animate-pulse" : j.last_status === "FAILED" ? "bg-neg" : j.last_status === "PARTIAL" ? "bg-warm" : "bg-pos"}`} />

                  <button className="flex-1 flex items-center gap-2 text-left min-w-0" onClick={() => setExpanded(isExpanded ? null : j.job_name)}>
                    <span className="text-sm font-medium text-ink truncate">{j.display_name || j.job_name}</span>
                    <code className="text-[10px] font-mono text-ink-3 hidden sm:inline">{j.job_name}</code>
                    {isExpanded ? <ChevronDown className="w-3.5 h-3.5 text-ink-3 shrink-0" /> : <ChevronRight className="w-3.5 h-3.5 text-ink-3 shrink-0" />}
                  </button>

                  <div className="flex items-center gap-3 shrink-0 text-[11px] text-ink-3">
                    {j.last_status && <Badge tone={tone}>{j.last_status}</Badge>}
                    <span className="hidden sm:inline">{relTime(j.last_run_at)}</span>
                    {j.success_rate_7d != null && (
                      <span className="hidden md:inline font-mono">{(j.success_rate_7d * 100).toFixed(0)}% 7d</span>
                    )}
                  </div>

                  <button
                    onClick={() => trigger(j.job_name)}
                    disabled={triggering[j.job_name] || j.last_status === "RUNNING"}
                    title="Trigger job"
                    className="h-8 w-8 flex items-center justify-center rounded-md border border-hairline text-ink-2 hover:text-accent hover:border-accent transition-colors disabled:opacity-40"
                  >
                    {triggering[j.job_name] ? <Loader2 className="w-4 h-4 animate-spin" /> : <PlayCircle className="w-4 h-4" />}
                  </button>
                </div>

                {isExpanded && (
                  <div className="border-t border-hairline bg-surface-1 px-4 py-3 text-xs text-ink-3 space-y-1">
                    {j.description && <p className="text-ink-2">{j.description}</p>}
                    <div className="flex gap-6">
                      <span>Last run: <strong className="text-ink-2">{relTime(j.last_run_at)}</strong></span>
                      {j.last_duration_seconds != null && <span>Duration: <strong className="text-ink-2">{j.last_duration_seconds.toFixed(1)}s</strong></span>}
                      {j.success_rate_7d != null && <span>7-day success: <strong className="text-ink-2">{(j.success_rate_7d * 100).toFixed(0)}%</strong></span>}
                    </div>
                  </div>
                )}
              </div>
            );
          })}
          {!isFetching && jobs.length === 0 && (
            <div className="text-center text-sm text-ink-3 py-8">No jobs found at <code>/api/admin/nidp/jobs</code>.</div>
          )}
        </div>
      </CardContent>
    </Card>
  );
}
