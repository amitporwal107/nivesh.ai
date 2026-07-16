/**
 * Feeds Live — a live, auto-refreshing tracker for every NIDP ingester,
 * with inline debugging (run history + log tail) per feed.
 *
 * Data:
 *   GET  /api/admin/nidp/feeds/live            — cheap, pollable rollup + per-feed health
 *   GET  /api/admin/nidp/jobs/{ing}/runs       — per-feed run history (job_log; authoritative RUNNING)
 *   GET  /api/admin/nidp/jobs/{ing}/logs        — per-feed VM log tail
 *   POST /api/admin/nidp/jobs/{ing}/execute     — trigger a run now
 *
 * "Is a job running right now" is read from job_log via the per-feed /runs
 * poll (the /feeds view only carries terminal status), surfaced when a feed
 * is expanded or right after it is triggered.
 */
import { useEffect, useMemo, useState } from "react";
import {
  Activity, PlayCircle, RefreshCw, Loader2, ChevronDown, ChevronRight,
  AlertTriangle, CheckCircle2, XCircle, Clock, Radio, Minus, ExternalLink,
} from "lucide-react";
import { Card, CardContent, CardLabel } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { http } from "@/services/api/http";
import { NidpError } from "./NidpError";
import { useToastStore } from "@/stores/toast.store";
import { useQuery, useQueryClient } from "@tanstack/react-query";

// ── Types (mirror the /feeds/live + /runs payloads) ──────────────────
type FreshnessState = "running" | "never_run" | "failing" | "stale" | "healthy";
interface FeedDay { date: string; is_today: boolean; status: string | null; run_count: number }
interface LiveFeed {
  ingester: string;
  source_class: string | null;
  expected_freq: string | null;
  schedule_cron: string | null;
  is_primary: boolean;
  last_run_status: string | null;
  consecutive_failures: number;
  last_run_at: string | null;
  last_success_at: string | null;
  last_failure_at: string | null;
  last_rows_inserted: number | null;
  last_run_duration_ms: number | null;
  success_count: number;
  failure_count: number;
  last_error_message: string | null;
  cloud_logs_url: string | null;
  last_7_days: FeedDay[];
  freshness_state: FreshnessState;
  hours_since_success: number | null;
  missed_last_trading_day: boolean;
}
interface Summary { total: number; healthy: number; failing: number; stale: number; never_run: number; running: number }
interface LiveData {
  generated_at: string;
  last_trading_day: string;
  summary: Summary;
  feeds: LiveFeed[];
  db_error: string | null;
}

interface Run {
  run_id: string;
  target_date: string | null;
  status: string;
  started_at: string | null;
  finished_at: string | null;
  duration_ms: number | null;
  rows_fetched: number | null;
  rows_inserted: number | null;
  rows_skipped: number | null;
  error_class: string | null;
  error_message: string | null;
  cloud_logs_url: string | null;
}
interface RunsData { ingester: string; runs: Run[]; error?: string }
interface LogsData { ingester: string; via?: string; log_path?: string | null; lines: string[]; error?: string | null }

const POLL_MS = 8_000;

// ── Small helpers ────────────────────────────────────────────────────
function relTime(iso?: string | null): string {
  if (!iso) return "—";
  const diff = (Date.now() - new Date(iso).getTime()) / 1000;
  if (diff < 0) return "just now";
  if (diff < 60) return `${Math.round(diff)}s ago`;
  if (diff < 3600) return `${Math.round(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.round(diff / 3600)}h ago`;
  return `${Math.round(diff / 86400)}d ago`;
}
function elapsed(iso?: string | null): string {
  if (!iso) return "0s";
  const s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (s < 60) return `${Math.round(s)}s`;
  if (s < 3600) return `${Math.floor(s / 60)}m ${Math.round(s % 60)}s`;
  return `${Math.floor(s / 3600)}h ${Math.floor((s % 3600) / 60)}m`;
}
function isRunning(r?: Run): boolean {
  return !!r && r.status === "RUNNING" && !r.finished_at;
}

const STATE_META: Record<FreshnessState, { label: string; tone: "good" | "neg" | "warm" | "accent" | "default"; dot: string }> = {
  running:   { label: "Running",   tone: "accent",  dot: "bg-accent" },
  failing:   { label: "Failing",   tone: "neg",     dot: "bg-neg" },
  stale:     { label: "Stale",     tone: "warm",    dot: "bg-warm" },
  never_run: { label: "Never run", tone: "default", dot: "bg-ink-4" },
  healthy:   { label: "Healthy",   tone: "good",    dot: "bg-pos" },
};
const RUN_TONE: Record<string, "good" | "neg" | "warm" | "accent" | "default"> = {
  OK: "good", SUCCESS: "good", FAILED: "neg", PARTIAL: "warm", RUNNING: "accent", SKIPPED: "default",
};

// ── Summary chips ─────────────────────────────────────────────────────
function SummaryChips({ s }: { s: Summary }) {
  const chips: { label: string; val: number; cls: string }[] = [
    { label: "Total",     val: s.total,     cls: "text-ink-2 bg-surface-2 border-hairline" },
    { label: "Healthy",   val: s.healthy,   cls: "text-pos bg-[rgb(var(--pos)/0.08)] border-[rgb(var(--pos)/0.2)]" },
    { label: "Failing",   val: s.failing,   cls: "text-neg bg-[rgb(var(--neg)/0.08)] border-[rgb(var(--neg)/0.2)]" },
    { label: "Stale",     val: s.stale,     cls: "text-warm bg-[rgb(var(--warm)/0.08)] border-[rgb(var(--warm)/0.2)]" },
    { label: "Never run", val: s.never_run, cls: "text-ink-4 bg-surface-2 border-hairline" },
  ];
  return (
    <div className="flex flex-wrap gap-2.5" data-testid="feeds-live-summary">
      {chips.map((c) => (
        <div key={c.label} className={`px-3 py-2 rounded-xl border text-[11px] font-medium ${c.cls}`}>
          <span className="text-[18px] font-bold block leading-none mb-0.5" data-testid={`summary-${c.label.toLowerCase().replace(" ", "-")}`}>{c.val}</span>
          {c.label}
        </div>
      ))}
    </div>
  );
}

// ── Run-history + running indicator (inline debug, top half) ──────────
function RunHistory({ ingester, expanded }: { ingester: string; expanded: boolean }) {
  const { data, error, isFetching } = useQuery({
    queryKey: ["nidp", "runs", ingester],
    queryFn: () => http<RunsData>({ path: `/api/admin/nidp/jobs/${encodeURIComponent(ingester)}/runs`, query: { limit: 8 } }).then((r) => r.data),
    enabled: expanded,
    refetchInterval: expanded ? 6_000 : false,
    refetchIntervalInBackground: false,
  });
  const runs = data?.runs ?? [];
  const running = isRunning(runs[0]);

  // Tick every second while a run is live so the elapsed timer feels live.
  const [, setTick] = useState(0);
  useEffect(() => {
    if (!running) return;
    const id = setInterval(() => setTick((t) => t + 1), 1_000);
    return () => clearInterval(id);
  }, [running]);

  return (
    <div data-testid={`feed-runs-${ingester}`}>
      <div className="flex items-center justify-between mb-1.5">
        <span className="text-[10px] font-mono uppercase tracking-[.1em] text-ink-4">Run history</span>
        {running ? (
          <span className="flex items-center gap-1.5 text-[11px] font-semibold text-accent" data-testid={`feed-running-${ingester}`}>
            <Radio className="w-3.5 h-3.5 animate-pulse" /> RUNNING · {elapsed(runs[0].started_at)}
          </span>
        ) : isFetching ? (
          <Loader2 className="w-3 h-3 animate-spin text-ink-4" />
        ) : null}
      </div>
      {error && <div className="text-[11px] text-neg font-mono">{data?.error ?? "failed to load runs"}</div>}
      {!error && runs.length === 0 && <div className="text-[11px] text-ink-4">No runs recorded.</div>}
      {runs.length > 0 && (
        <div className="overflow-x-auto rounded-lg border border-hairline">
          <table className="w-full text-left border-collapse min-w-[560px]">
            <thead>
              <tr className="bg-surface-1 border-b border-hairline">
                {["Status", "Started", "Duration", "Rows", "Error"].map((h) => (
                  <th key={h} className="px-2.5 py-1.5 font-mono text-[9px] uppercase tracking-[.08em] text-ink-4 font-normal">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {runs.map((r) => (
                <tr key={r.run_id} className="border-b border-hairline/40">
                  <td className="px-2.5 py-1.5"><Badge tone={RUN_TONE[r.status] ?? "default"}>{r.status}</Badge></td>
                  <td className="px-2.5 py-1.5 font-mono text-[10px] text-ink-3" title={r.started_at ?? ""}>{relTime(r.started_at)}</td>
                  <td className="px-2.5 py-1.5 font-mono text-[10px] text-ink-3">{r.duration_ms != null ? `${(r.duration_ms / 1000).toFixed(1)}s` : (isRunning(r) ? "…" : "—")}</td>
                  <td className="px-2.5 py-1.5 font-mono text-[10px] text-ink-3">{r.rows_inserted != null ? r.rows_inserted.toLocaleString() : "—"}</td>
                  <td className="px-2.5 py-1.5 font-mono text-[10px] text-neg max-w-[220px] truncate" title={r.error_message ?? ""}>
                    {r.error_class ? `[${r.error_class}] ` : ""}{r.error_message ? r.error_message.slice(0, 80) : ""}
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

// ── Log tail (inline debug, bottom half) ──────────────────────────────
function LogTail({ ingester, expanded }: { ingester: string; expanded: boolean }) {
  const { data, error, isFetching } = useQuery({
    queryKey: ["nidp", "logs", ingester],
    queryFn: () => http<LogsData>({ path: `/api/admin/nidp/jobs/${encodeURIComponent(ingester)}/logs`, query: { limit: 200 }, timeoutMs: 30_000 }).then((r) => r.data),
    enabled: expanded,
    refetchInterval: expanded ? 10_000 : false,
    refetchIntervalInBackground: false,
  });
  const lines = data?.lines ?? [];
  return (
    <div data-testid={`feed-logs-${ingester}`}>
      <div className="flex items-center justify-between mb-1.5">
        <span className="text-[10px] font-mono uppercase tracking-[.1em] text-ink-4">
          Log tail{data?.via ? ` · ${data.via}` : ""}{data?.log_path ? ` · ${data.log_path}` : ""}
        </span>
        {isFetching && <Loader2 className="w-3 h-3 animate-spin text-ink-4" />}
      </div>
      {error && <div className="text-[11px] text-neg font-mono">failed to load logs</div>}
      {data?.error && <div className="text-[11px] text-warm font-mono">{data.error}</div>}
      {!error && !data?.error && (
        lines.length === 0
          ? <div className="text-[11px] text-ink-4">No recent log lines.</div>
          : (
            <pre className="max-h-56 overflow-auto rounded-lg border border-hairline bg-surface-1 p-2.5 text-[10px] leading-relaxed font-mono text-ink-2 whitespace-pre-wrap break-all">
              {lines.join("\n")}
            </pre>
          )
      )}
    </div>
  );
}

// ── One feed row (collapsed summary + expandable debug) ───────────────
function FeedRow({ feed, expanded, onToggle, onTrigger, triggering }: {
  feed: LiveFeed;
  expanded: boolean;
  onToggle: () => void;
  onTrigger: () => void;
  triggering: boolean;
}) {
  const meta = STATE_META[feed.freshness_state] ?? STATE_META.never_run;
  const freshness = feed.last_success_at
    ? (feed.missed_last_trading_day
        ? <span className="text-warm">no success since {feed.last_success_at.slice(0, 10)}</span>
        : <span className="text-ink-3">ran {relTime(feed.last_success_at)}</span>)
    : <span className="text-ink-4">never succeeded</span>;

  return (
    <div className="rounded-lg border border-hairline overflow-hidden" data-testid={`feed-row-${feed.ingester}`}>
      <div className="flex items-center gap-2 px-3 py-2.5">
        <button className="flex-1 flex items-center gap-2 text-left min-w-0" onClick={onToggle} data-testid={`feed-toggle-${feed.ingester}`}>
          {expanded ? <ChevronDown className="w-3.5 h-3.5 text-ink-3 shrink-0" /> : <ChevronRight className="w-3.5 h-3.5 text-ink-3 shrink-0" />}
          <span className={`h-1.5 w-1.5 rounded-full shrink-0 ${meta.dot}`} />
          <span className="font-mono text-xs text-ink-2 truncate">{feed.ingester}</span>
          {feed.expected_freq && <span className="text-[9px] text-ink-4 hidden md:inline">{feed.expected_freq}</span>}
        </button>

        <div className="flex items-center gap-2 shrink-0">
          <span className="text-[10px] hidden sm:inline">{freshness}</span>
          {feed.consecutive_failures > 0 && <span className="text-[10px] font-bold text-neg">{feed.consecutive_failures}✗</span>}
          <Badge tone={meta.tone} data-testid={`feed-state-${feed.ingester}`}>{meta.label}</Badge>
        </div>

        <button
          onClick={onTrigger}
          disabled={triggering}
          title="Trigger this feed now on the VM"
          data-testid={`feed-trigger-${feed.ingester}`}
          className="h-7 w-7 flex items-center justify-center rounded border border-hairline text-ink-2 hover:text-accent hover:border-accent transition-colors disabled:opacity-40"
        >
          {triggering ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <PlayCircle className="w-3.5 h-3.5" />}
        </button>
      </div>

      {expanded && (
        <div className="border-t border-hairline bg-surface-1 px-4 py-3 space-y-3" data-testid={`feed-detail-${feed.ingester}`}>
          <div className="flex flex-wrap gap-x-5 gap-y-1 text-[11px] text-ink-3">
            {feed.source_class && <span>Source: <strong className="text-ink-2">{feed.source_class}</strong></span>}
            {feed.schedule_cron && <span>Cron: <code className="text-ink-2 bg-surface-2 px-1 rounded">{feed.schedule_cron}</code></span>}
            <span>Last run: <strong className="text-ink-2">{relTime(feed.last_run_at)}</strong></span>
            {feed.last_run_duration_ms != null && <span>Duration: <strong className="text-ink-2">{(feed.last_run_duration_ms / 1000).toFixed(1)}s</strong></span>}
            {feed.last_rows_inserted != null && <span>Rows: <strong className="text-ink-2">{feed.last_rows_inserted.toLocaleString()}</strong></span>}
            <span>✓ {feed.success_count} / ✗ {feed.failure_count}</span>
            {feed.cloud_logs_url && (
              <a href={feed.cloud_logs_url} target="_blank" rel="noreferrer" className="text-accent hover:underline inline-flex items-center gap-0.5">
                <ExternalLink className="w-3 h-3" /> GCP logs
              </a>
            )}
          </div>
          {feed.last_error_message && (
            <div className="text-neg font-mono text-[10px] bg-[rgb(var(--neg)/0.06)] rounded p-2 break-all">{feed.last_error_message}</div>
          )}
          <RunHistory ingester={feed.ingester} expanded={expanded} />
          <LogTail ingester={feed.ingester} expanded={expanded} />
        </div>
      )}
    </div>
  );
}

// ── Panel ─────────────────────────────────────────────────────────────
export function FeedsLivePanel() {
  const push = useToastStore((s) => s.push);
  const qc = useQueryClient();
  const [live, setLive] = useState(true);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [triggering, setTriggering] = useState<Record<string, boolean>>({});

  const { data, isFetching, refetch, error, dataUpdatedAt } = useQuery({
    queryKey: ["nidp", "feeds-live"],
    queryFn: () => http<LiveData>({ path: "/api/admin/nidp/feeds/live", timeoutMs: 30_000 }).then((r) => r.data),
    refetchInterval: live ? POLL_MS : false,
    refetchIntervalInBackground: false,
  });

  const feeds = useMemo(() => data?.feeds ?? [], [data]);
  const summary = data?.summary;
  const attention = feeds.filter((f) => f.freshness_state === "failing" || f.freshness_state === "stale");

  const trigger = async (ingester: string) => {
    if (!window.confirm(`Trigger "${ingester}" now? This runs immediately on the NIDP VM.`)) return;
    setTriggering((t) => ({ ...t, [ingester]: true }));
    try {
      await http({ method: "POST", path: `/api/admin/nidp/jobs/${encodeURIComponent(ingester)}/execute`, body: {} });
      push({ kind: "success", title: `"${ingester}" triggered — watch it run below` });
      setExpanded(ingester); // auto-expand so the /runs poll surfaces the RUNNING row live
      setTimeout(() => {
        qc.invalidateQueries({ queryKey: ["nidp", "runs", ingester] });
        qc.invalidateQueries({ queryKey: ["nidp", "feeds-live"] });
      }, 2_500);
    } catch (e: unknown) {
      push({ kind: "error", title: `Failed to trigger "${ingester}"`, description: e instanceof Error ? e.message : undefined });
    } finally {
      setTriggering((t) => ({ ...t, [ingester]: false }));
    }
  };

  return (
    <div className="space-y-4" data-testid="feeds-live-panel">
      {/* Header */}
      <Card>
        <CardContent className="p-5 space-y-4">
          <div className="flex items-center justify-between gap-3 flex-wrap">
            <div>
              <CardLabel>
                <span className="inline-flex items-center gap-1.5"><Activity className="w-3.5 h-3.5" /> Feeds Live — {feeds.length} ingesters</span>
              </CardLabel>
              <div className="text-[10px] text-ink-3 mt-0.5">
                {data?.last_trading_day && <>Last trading day: {data.last_trading_day} · </>}
                {live ? "auto-refresh on" : "auto-refresh paused"}
                {dataUpdatedAt ? ` · updated ${relTime(new Date(dataUpdatedAt).toISOString())}` : ""}
              </div>
            </div>
            <div className="flex items-center gap-2">
              <button
                onClick={() => setLive((v) => !v)}
                data-testid="feeds-live-toggle"
                className={`inline-flex items-center gap-1.5 h-8 px-3 rounded-lg border text-[11px] font-medium transition-colors ${live ? "border-accent text-accent bg-[rgb(var(--accent)/0.08)]" : "border-hairline text-ink-3"}`}
              >
                <Radio className={`w-3.5 h-3.5 ${live ? "animate-pulse" : ""}`} /> {live ? "Live" : "Paused"}
              </button>
              <button
                onClick={() => refetch()}
                disabled={isFetching}
                data-testid="feeds-live-refresh"
                className="h-8 w-8 flex items-center justify-center rounded-lg border border-hairline text-ink-2 hover:text-accent hover:border-accent transition-colors disabled:opacity-40"
              >
                {isFetching ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <RefreshCw className="w-3.5 h-3.5" />}
              </button>
            </div>
          </div>

          {summary && <SummaryChips s={summary} />}
          {data?.db_error && (
            <div className="flex items-start gap-2 rounded-lg border border-[rgb(var(--warm)/0.25)] bg-[rgb(var(--warm)/0.06)] px-4 py-3">
              <AlertTriangle className="w-4 h-4 text-warm shrink-0 mt-0.5" />
              <div className="text-xs text-ink-2"><strong className="text-warm">Query API reported:</strong> {data.db_error}</div>
            </div>
          )}
          {error && <NidpError err={error} />}
        </CardContent>
      </Card>

      {/* Needs attention */}
      {attention.length > 0 && (
        <div className="flex items-start gap-2 rounded-lg border border-[rgb(var(--neg)/0.25)] bg-[rgb(var(--neg)/0.06)] px-4 py-3" data-testid="feeds-live-attention">
          <AlertTriangle className="w-4 h-4 text-neg shrink-0 mt-0.5" />
          <div className="text-sm text-ink-2">
            <strong className="text-neg">{attention.length} feed{attention.length > 1 ? "s" : ""} need attention:</strong>{" "}
            {attention.map((f) => f.ingester).join(", ")}
          </div>
        </div>
      )}

      {/* Feed list (server-sorted worst-first) */}
      <Card>
        <CardContent className="p-5">
          <div className="space-y-1">
            {feeds.map((f) => (
              <FeedRow
                key={f.ingester}
                feed={f}
                expanded={expanded === f.ingester}
                onToggle={() => setExpanded(expanded === f.ingester ? null : f.ingester)}
                onTrigger={() => trigger(f.ingester)}
                triggering={!!triggering[f.ingester]}
              />
            ))}
            {!isFetching && feeds.length === 0 && !error && (
              <div className="text-center text-sm text-ink-3 py-8 flex flex-col items-center gap-2">
                <Minus className="w-5 h-5 text-ink-4" />
                No feeds returned{data?.db_error ? " (see Query API message above)" : ""}.
              </div>
            )}
          </div>
        </CardContent>
      </Card>

      {/* Legend */}
      <div className="flex flex-wrap gap-3 text-[10px] text-ink-4 px-1">
        <span className="inline-flex items-center gap-1"><CheckCircle2 className="w-3 h-3 text-pos" /> healthy</span>
        <span className="inline-flex items-center gap-1"><XCircle className="w-3 h-3 text-neg" /> failing</span>
        <span className="inline-flex items-center gap-1"><Clock className="w-3 h-3 text-warm" /> stale (missed last trading day)</span>
        <span className="inline-flex items-center gap-1"><Radio className="w-3 h-3 text-accent" /> running now (expand or trigger a feed to watch)</span>
      </div>
    </div>
  );
}
