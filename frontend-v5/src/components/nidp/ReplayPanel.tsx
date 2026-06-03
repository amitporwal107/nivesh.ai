import { useState } from "react";
import { History, RefreshCw, Loader2, Play, ChevronDown, ChevronRight } from "lucide-react";
import { Card, CardContent, CardLabel } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { http } from "@/services/api/http";
import { useToastStore } from "@/stores/toast.store";
import { useQuery, useQueryClient } from "@tanstack/react-query";

interface ReplayRun {
  run_id: string;
  feed_name: string;
  started_at: string;
  completed_at?: string;
  status: string;
  days_replayed?: number;
  violations_found?: number;
  triggered_by?: string;
}

export function ReplayPanel() {
  const push = useToastStore((s) => s.push);
  const qc = useQueryClient();
  const [expanded, setExpanded] = useState<string | null>(null);
  const [selectedFeed, setSelectedFeed] = useState("");
  const [triggerDays, setTriggerDays] = useState(90);
  const [triggering, setTriggering] = useState(false);

  const { data, isFetching, refetch } = useQuery({
    queryKey: ["nidp", "replay"],
    queryFn: () => http<{ runs: ReplayRun[]; available_feeds: string[] }>({ path: "/api/admin/nidp/replay" }).then((r) => r.data).catch(() => ({ runs: [], available_feeds: [] })),
    staleTime: 60_000,
  });

  const triggerReplay = async () => {
    if (!selectedFeed) { push({ kind: "warn", title: "Select a feed first" }); return; }
    if (!window.confirm(`Run ${triggerDays}d replay for "${selectedFeed}"? This is a heavy operation.`)) return;
    setTriggering(true);
    try {
      await http({ method: "POST", path: "/api/admin/nidp/replay/trigger", body: { feed_name: selectedFeed, days: triggerDays } });
      push({ kind: "success", title: `Replay started for "${selectedFeed}"` });
      setTimeout(() => qc.invalidateQueries({ queryKey: ["nidp", "replay"] }), 2000);
    } catch { push({ kind: "error", title: "Replay trigger failed" }); }
    finally { setTriggering(false); }
  };

  const STATUS_TONE: Record<string, "good" | "neg" | "warm" | "default"> = {
    completed: "good", failed: "neg", running: "default", pending: "warm",
  };

  const inputCls = "rounded-md border border-hairline-2 bg-surface-1 px-3 py-2 text-sm text-ink focus:outline-none focus:ring-1 focus:ring-accent";

  return (
    <Card>
      <CardContent className="p-5">
        <div className="flex items-center gap-3 mb-5">
          <div className="w-10 h-10 rounded-lg bg-accent-soft flex items-center justify-center">
            <History className="w-5 h-5 text-accent" />
          </div>
          <div>
            <h2 className="text-base font-semibold text-ink">Replay (90d)</h2>
            <p className="text-xs text-ink-3">Re-run DQ governance for last N days · calibrate thresholds · simulate failures.</p>
          </div>
        </div>

        {/* Trigger */}
        <div className="bg-surface-1 rounded-lg border border-hairline p-4 mb-5">
          <CardLabel className="mb-3">Trigger New Replay</CardLabel>
          <div className="flex flex-wrap gap-3 items-end">
            <div>
              <label className="block text-xs text-ink-3 mb-1">Feed</label>
              <select value={selectedFeed} onChange={(e) => setSelectedFeed(e.target.value)} className={`${inputCls} w-48`}>
                <option value="">Select feed…</option>
                {(data?.available_feeds ?? []).map((f) => <option key={f} value={f}>{f}</option>)}
              </select>
            </div>
            <div>
              <label className="block text-xs text-ink-3 mb-1">Days</label>
              <select value={triggerDays} onChange={(e) => setTriggerDays(Number(e.target.value))} className={`${inputCls} w-24`}>
                {[7, 30, 60, 90].map((d) => <option key={d} value={d}>{d}d</option>)}
              </select>
            </div>
            <Button onClick={triggerReplay} disabled={triggering || !selectedFeed}>
              {triggering ? <><Loader2 className="w-3.5 h-3.5 animate-spin" /> Starting…</> : <><Play className="w-3.5 h-3.5" /> Run Replay</>}
            </Button>
          </div>
        </div>

        {/* History */}
        <div className="flex items-center justify-between mb-3">
          <CardLabel>Recent Replay Runs</CardLabel>
          <Button size="sm" variant="outline" onClick={() => refetch()} disabled={isFetching}>
            {isFetching ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <RefreshCw className="w-3.5 h-3.5" />}
          </Button>
        </div>

        <div className="space-y-2">
          {(data?.runs ?? []).map((run) => {
            const isExp = expanded === run.run_id;
            return (
              <div key={run.run_id} className="rounded-lg border border-hairline overflow-hidden">
                <button className="w-full flex items-center gap-3 px-3 py-3 text-left hover:bg-surface-1 transition-colors" onClick={() => setExpanded(isExp ? null : run.run_id)}>
                  {isExp ? <ChevronDown className="w-3.5 h-3.5 text-ink-3 shrink-0" /> : <ChevronRight className="w-3.5 h-3.5 text-ink-3 shrink-0" />}
                  <span className="font-mono text-sm text-ink flex-1">{run.feed_name}</span>
                  <Badge tone={STATUS_TONE[run.status] ?? "default"}>{run.status}</Badge>
                  <span className="text-xs text-ink-3 hidden sm:inline">{run.days_replayed ?? "?"}d replayed</span>
                </button>
                {isExp && (
                  <div className="border-t border-hairline bg-surface-1 px-4 py-3 text-xs text-ink-3 flex flex-wrap gap-4">
                    <span>Started: <strong className="text-ink-2">{new Date(run.started_at).toLocaleString()}</strong></span>
                    {run.completed_at && <span>Completed: <strong className="text-ink-2">{new Date(run.completed_at).toLocaleString()}</strong></span>}
                    {run.violations_found != null && <span>Violations: <strong className={run.violations_found > 0 ? "text-neg" : "text-pos"}>{run.violations_found}</strong></span>}
                    {run.triggered_by && <span>By: <strong className="text-ink-2">{run.triggered_by}</strong></span>}
                  </div>
                )}
              </div>
            );
          })}
          {!isFetching && (data?.runs ?? []).length === 0 && (
            <div className="text-center text-sm text-ink-3 py-6">No replay runs yet.</div>
          )}
        </div>
      </CardContent>
    </Card>
  );
}
