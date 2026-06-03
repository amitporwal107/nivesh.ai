/**
 * Work — issues dashboard at work.niveshcopilot.com
 *
 * Jira-style board: filter sidebar → issue cards → detail drawer.
 * Admin-only. Populated by error_triage.py (Cloud Logging → MongoDB)
 * and the diagnostics CLI tool.
 */
import { useState, useCallback } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Bug, Zap, AlertTriangle, CheckCircle2, Clock, RefreshCw,
  X, ChevronRight, Filter, BarChart2, Code2, GitPullRequest,
  ExternalLink, MessageSquare,
} from "lucide-react";
import { workAdapter, type IssuesFilter } from "@/services/adapters/work.adapter";
import type { WorkIssue, WorkStats } from "@/services/contracts/work.contract";
import { LoadingSkeleton } from "@/components/shared/LoadingSkeleton";
import { ErrorState } from "@/components/shared/ErrorState";

// ── Helpers ──────────────────────────────────────────────────────────────────

const PRIORITY_META: Record<string, { label: string; dot: string; bg: string; text: string }> = {
  P1: { label: "P1 Critical", dot: "bg-neg",  bg: "bg-[rgb(var(--neg)/0.08)]",  text: "text-neg"  },
  P2: { label: "P2 High",     dot: "bg-warm", bg: "bg-[rgb(var(--warm)/0.08)]", text: "text-warm" },
  P3: { label: "P3 Normal",   dot: "bg-ink-4",bg: "bg-surface-2",               text: "text-ink-3"},
};

const STATUS_META: Record<string, { label: string; icon: React.ReactNode; text: string }> = {
  open:        { label: "Open",        icon: <Bug className="h-3.5 w-3.5" />,          text: "text-neg"  },
  in_progress: { label: "In progress", icon: <Clock className="h-3.5 w-3.5" />,        text: "text-warm" },
  resolved:    { label: "Resolved",    icon: <CheckCircle2 className="h-3.5 w-3.5" />, text: "text-pos"  },
  wont_fix:    { label: "Won't fix",   icon: <X className="h-3.5 w-3.5" />,            text: "text-ink-3"},
};

function timeAgo(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 60)   return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24)    return `${hrs}h ago`;
  return `${Math.floor(hrs / 24)}d ago`;
}

function SourceChip({ source }: { source: string }) {
  const label = source === "cloud_logging" ? "Cloud Logs"
              : source === "diagnostic_tool" ? "Diagnostics"
              : "Manual";
  const cls = source === "cloud_logging" ? "text-accent bg-[rgb(var(--accent)/0.08)]"
            : source === "diagnostic_tool" ? "text-pos bg-[rgb(var(--pos)/0.08)]"
            : "text-ink-3 bg-surface-2";
  return (
    <span className={`font-mono text-[10px] px-1.5 py-0.5 rounded uppercase tracking-[.08em] ${cls}`}>
      {label}
    </span>
  );
}

// ── Stats bar ─────────────────────────────────────────────────────────────────

function StatsBar({ stats }: { stats: WorkStats }) {
  return (
    <div className="flex items-center gap-5 text-[12px]">
      <span className="text-neg font-semibold">{stats.by_priority["P1"] ?? 0} P1</span>
      <span className="text-warm font-semibold">{stats.by_priority["P2"] ?? 0} P2</span>
      <span className="text-ink-3">{stats.by_priority["P3"] ?? 0} P3</span>
      <span className="h-3 w-px bg-hairline mx-1" />
      <span className="text-ink-2">{stats.by_status["open"] ?? 0} open</span>
      <span className="text-pos">{stats.by_status["resolved"] ?? 0} resolved</span>
      <span className="text-ink-4 ml-auto font-mono">{stats.total} total</span>
    </div>
  );
}

// ── Issue card ────────────────────────────────────────────────────────────────

function IssueCard({ issue, onClick }: { issue: WorkIssue; onClick(): void }) {
  const pm = PRIORITY_META[issue.priority] ?? PRIORITY_META.P2;
  const sm = STATUS_META[issue.status] ?? STATUS_META.open;
  return (
    <button
      onClick={onClick}
      className={`w-full text-left rounded-xl border border-hairline p-4 transition-all hover:border-accent/40 hover:shadow-md ${pm.bg}`}
    >
      <div className="flex items-start gap-3">
        <span className={`mt-1.5 h-2 w-2 rounded-full shrink-0 ${pm.dot}`} />
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-1 flex-wrap">
            <span className="font-mono text-[10px] text-ink-4">{issue.issue_id}</span>
            <SourceChip source={issue.source} />
            {issue.applications.slice(0, 2).map(a => (
              <span key={a} className="font-mono text-[10px] text-ink-4 bg-surface-2 px-1.5 py-0.5 rounded">{a}</span>
            ))}
            <span className="ml-auto font-mono text-[10px] text-ink-4">{timeAgo(issue.last_seen)}</span>
          </div>
          <p className="text-[13px] font-medium text-ink truncate">{issue.title}</p>
          {issue.sample_message && (
            <p className="text-[11px] text-ink-3 truncate mt-0.5 font-mono">{issue.sample_message}</p>
          )}
          <div className="flex items-center gap-3 mt-2 text-[11px]">
            <span className={`flex items-center gap-1 ${sm.text}`}>
              {sm.icon}{sm.label}
            </span>
            <span className="text-ink-4">×{issue.count_24h} in 24h</span>
            {issue.rca && (
              <span className="text-pos flex items-center gap-1">
                <Zap className="h-3 w-3" />RCA ready
              </span>
            )}
            <ChevronRight className="h-3.5 w-3.5 text-ink-4 ml-auto" />
          </div>
        </div>
      </div>
    </button>
  );
}

// ── Issue drawer ──────────────────────────────────────────────────────────────

function IssueDrawer({ issue, onClose }: { issue: WorkIssue; onClose(): void }) {
  const qc = useQueryClient();
  const pm = PRIORITY_META[issue.priority] ?? PRIORITY_META.P2;

  const updateMutation = useMutation({
    mutationFn: (update: { status?: string; comment?: string }) =>
      workAdapter.update(issue.issue_id, update),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["work-issues"] });
      qc.invalidateQueries({ queryKey: ["work-stats"] });
    },
  });

  const [comment, setComment] = useState("");

  const submitComment = () => {
    if (!comment.trim()) return;
    updateMutation.mutate({ comment: comment.trim() });
    setComment("");
  };

  const setStatus = (s: string) => updateMutation.mutate({ status: s });

  return (
    <div className="fixed inset-0 z-50 flex">
      {/* backdrop */}
      <div className="flex-1 bg-black/40" onClick={onClose} />

      {/* drawer panel */}
      <aside className="w-full max-w-[640px] bg-bg border-l border-hairline flex flex-col h-full overflow-hidden">
        {/* header */}
        <div className="flex items-center gap-3 px-6 py-4 border-b border-hairline shrink-0">
          <span className={`h-2.5 w-2.5 rounded-full ${pm.dot}`} />
          <span className="font-mono text-[11px] text-ink-4">{issue.issue_id}</span>
          <span className={`font-mono text-[10px] px-1.5 py-0.5 rounded uppercase ${pm.bg} ${pm.text}`}>
            {pm.label}
          </span>
          <SourceChip source={issue.source} />
          <button onClick={onClose} className="ml-auto text-ink-4 hover:text-ink p-1">
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto px-6 py-5 space-y-6">
          {/* title + meta */}
          <div>
            <h2 className="text-[16px] font-semibold text-ink leading-snug">{issue.title}</h2>
            <div className="flex flex-wrap gap-x-4 gap-y-1 mt-2 text-[11px] text-ink-3">
              <span>First seen: <span className="font-mono">{new Date(issue.first_seen).toLocaleString()}</span></span>
              <span>Last seen: <span className="font-mono">{timeAgo(issue.last_seen)}</span></span>
              <span>Frequency: <b className="text-ink">{issue.count_24h}×</b> / 24h</span>
              {issue.exception_class && <span>Exception: <span className="font-mono text-warm">{issue.exception_class}</span></span>}
              {issue.endpoint && <span>Endpoint: <span className="font-mono">{issue.endpoint}</span></span>}
              {issue.http_status && <span>HTTP: <span className="font-mono text-neg">{issue.http_status}</span></span>}
            </div>
          </div>

          {/* status actions */}
          <div>
            <p className="text-[11px] font-mono uppercase tracking-[.1em] text-ink-4 mb-2">Status</p>
            <div className="flex gap-2 flex-wrap">
              {(["open", "in_progress", "resolved", "wont_fix"] as const).map(s => {
                const active = issue.status === s;
                return (
                  <button
                    key={s}
                    onClick={() => setStatus(s)}
                    disabled={active || updateMutation.isPending}
                    className={`text-[12px] px-3 py-1.5 rounded-lg border transition-colors ${
                      active
                        ? "bg-accent text-on-accent border-accent font-medium"
                        : "border-hairline text-ink-3 hover:text-ink hover:border-accent/40"
                    }`}
                  >
                    {STATUS_META[s]?.label}
                  </button>
                );
              })}
            </div>
          </div>

          {/* sample message */}
          {issue.sample_message && (
            <div>
              <p className="text-[11px] font-mono uppercase tracking-[.1em] text-ink-4 mb-2 flex items-center gap-1.5">
                <AlertTriangle className="h-3.5 w-3.5" />Sample message
              </p>
              <pre className="text-[11px] bg-surface-1 border border-hairline rounded-lg p-3 font-mono text-ink-2 overflow-x-auto whitespace-pre-wrap break-all">
                {issue.sample_message}
              </pre>
            </div>
          )}

          {/* traceback */}
          {issue.sample_traceback && (
            <div>
              <p className="text-[11px] font-mono uppercase tracking-[.1em] text-ink-4 mb-2 flex items-center gap-1.5">
                <Code2 className="h-3.5 w-3.5" />Stack trace
              </p>
              <pre className="text-[11px] bg-surface-1 border border-hairline rounded-lg p-3 font-mono text-neg overflow-x-auto whitespace-pre-wrap break-all max-h-48">
                {issue.sample_traceback}
              </pre>
            </div>
          )}

          {/* RCA */}
          {issue.rca ? (
            <div className="rounded-xl border border-pos/30 bg-[rgb(var(--pos)/0.04)] p-4 space-y-3">
              <p className="text-[11px] font-mono uppercase tracking-[.1em] text-pos flex items-center gap-1.5">
                <Zap className="h-3.5 w-3.5" />Root cause analysis
                <span className="ml-auto text-ink-4 normal-case tracking-normal">
                  via {issue.rca.source} · {Math.round((issue.rca.confidence ?? 0) * 100)}% confidence
                </span>
              </p>
              <div>
                <p className="text-[11px] text-ink-4 mb-1">Root cause</p>
                <p className="text-[13px] text-ink">{issue.rca.root_cause || "—"}</p>
              </div>
              {issue.rca.fix_suggestion && (
                <div>
                  <p className="text-[11px] text-ink-4 mb-1">Suggested fix</p>
                  <p className="text-[13px] text-ink">{issue.rca.fix_suggestion}</p>
                </div>
              )}
              {issue.rca.fix_file && (
                <div className="rounded-lg bg-surface-1 border border-hairline px-3 py-2">
                  <p className="text-[10px] text-ink-4 mb-0.5">File to change</p>
                  <p className="font-mono text-[11px] text-accent">{issue.rca.fix_file}</p>
                  {issue.rca.fix_description && (
                    <p className="text-[11px] text-ink-2 mt-1">{issue.rca.fix_description}</p>
                  )}
                </div>
              )}
            </div>
          ) : (
            <div className="rounded-xl border border-hairline p-4 text-[12px] text-ink-3 text-center">
              No RCA available yet. Run the diagnostic tool or wait for the next triage cycle.
            </div>
          )}

          {/* labels + apps */}
          <div className="flex flex-wrap gap-2">
            {issue.applications.map(a => (
              <span key={a} className="font-mono text-[10px] bg-surface-2 text-ink-3 px-2 py-1 rounded-md border border-hairline">{a}</span>
            ))}
            {issue.labels.map(l => (
              <span key={l} className="font-mono text-[10px] bg-accent/10 text-accent px-2 py-1 rounded-md">{l}</span>
            ))}
          </div>

          {/* comments */}
          {issue.comments.length > 0 && (
            <div>
              <p className="text-[11px] font-mono uppercase tracking-[.1em] text-ink-4 mb-3 flex items-center gap-1.5">
                <MessageSquare className="h-3.5 w-3.5" />Comments ({issue.comments.length})
              </p>
              <div className="space-y-3">
                {issue.comments.map((c, i) => (
                  <div key={i} className="rounded-lg bg-surface-1 border border-hairline p-3">
                    <div className="flex items-center gap-2 mb-1">
                      <span className="text-[11px] font-medium text-ink-2">{c.author}</span>
                      <span className="text-[10px] text-ink-4 ml-auto">{timeAgo(c.created_at)}</span>
                    </div>
                    <p className="text-[12px] text-ink">{c.body}</p>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* add comment */}
          <div>
            <p className="text-[11px] font-mono uppercase tracking-[.1em] text-ink-4 mb-2">Add comment</p>
            <textarea
              value={comment}
              onChange={e => setComment(e.target.value)}
              placeholder="Notes, context, or resolution steps…"
              rows={3}
              className="w-full rounded-lg bg-surface-1 border border-hairline px-3 py-2 text-[13px] text-ink placeholder-ink-4 resize-none focus:outline-none focus:border-accent/50"
            />
            <button
              onClick={submitComment}
              disabled={!comment.trim() || updateMutation.isPending}
              className="mt-2 px-4 py-1.5 rounded-lg bg-accent text-on-accent text-[13px] font-medium disabled:opacity-40 hover:opacity-90 transition-opacity"
            >
              Post
            </button>
          </div>
        </div>
      </aside>
    </div>
  );
}

// ── Filter sidebar ────────────────────────────────────────────────────────────

function FilterPanel({
  filter, onChange,
}: {
  filter: IssuesFilter;
  onChange(f: IssuesFilter): void;
}) {
  const btn = (key: keyof IssuesFilter, val: string | undefined, label: string) => {
    const active = filter[key] === val;
    return (
      <button
        key={label}
        onClick={() => onChange({ ...filter, [key]: val })}
        className={`w-full text-left px-3 py-1.5 rounded-lg text-[12px] transition-colors ${
          active ? "bg-accent/10 text-accent font-medium" : "text-ink-3 hover:text-ink hover:bg-surface-2"
        }`}
      >
        {label}
      </button>
    );
  };

  return (
    <aside className="w-44 shrink-0 space-y-5 text-[12px]">
      <div>
        <p className="font-mono text-[10px] uppercase tracking-[.12em] text-ink-4 mb-2">Priority</p>
        {btn("priority", undefined, "All priorities")}
        {btn("priority", "P1", "P1 Critical")}
        {btn("priority", "P2", "P2 High")}
        {btn("priority", "P3", "P3 Normal")}
      </div>
      <div>
        <p className="font-mono text-[10px] uppercase tracking-[.12em] text-ink-4 mb-2">Status</p>
        {btn("status", undefined, "All statuses")}
        {btn("status", "open", "Open")}
        {btn("status", "in_progress", "In progress")}
        {btn("status", "resolved", "Resolved")}
        {btn("status", "wont_fix", "Won't fix")}
      </div>
      <div>
        <p className="font-mono text-[10px] uppercase tracking-[.12em] text-ink-4 mb-2">Source</p>
        {btn("source", undefined, "All sources")}
        {btn("source", "cloud_logging", "Cloud Logs")}
        {btn("source", "diagnostic_tool", "Diagnostics")}
        {btn("source", "manual", "Manual")}
      </div>
    </aside>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function WorkPage() {
  const [filter, setFilter]       = useState<IssuesFilter>({ status: "open", limit: 100 });
  const [selected, setSelected]   = useState<WorkIssue | null>(null);
  const qc = useQueryClient();

  const { data: issueData, isLoading, isError, refetch } = useQuery({
    queryKey: ["work-issues", filter],
    queryFn:  () => workAdapter.list(filter),
  });

  const { data: stats } = useQuery({
    queryKey: ["work-stats"],
    queryFn:  workAdapter.stats,
  });

  const handleUpdate = useCallback((updated: WorkIssue) => {
    setSelected(updated);
    qc.invalidateQueries({ queryKey: ["work-issues"] });
  }, [qc]);

  const issues = issueData?.issues ?? [];

  return (
    <div className="flex flex-col h-full min-h-0">
      {/* topbar */}
      <div className="shrink-0 px-6 py-4 border-b border-hairline flex items-center gap-4 flex-wrap">
        <div className="flex items-center gap-2">
          <Bug className="h-5 w-5 text-neg" />
          <h1 className="text-[16px] font-semibold text-ink">Issues</h1>
        </div>
        {stats && <StatsBar stats={stats} />}
        <button
          onClick={() => refetch()}
          className="ml-auto flex items-center gap-1.5 text-[12px] text-ink-3 hover:text-ink px-3 py-1.5 rounded-lg border border-hairline hover:border-accent/40 transition-colors"
        >
          <RefreshCw className="h-3.5 w-3.5" />Refresh
        </button>
      </div>

      {/* body */}
      <div className="flex-1 min-h-0 flex gap-0">
        {/* filter panel */}
        <div className="shrink-0 w-52 border-r border-hairline px-4 py-5 overflow-y-auto">
          <FilterPanel filter={filter} onChange={setFilter} />
        </div>

        {/* issue list */}
        <div className="flex-1 min-w-0 px-5 py-5 overflow-y-auto">
          {isLoading && <LoadingSkeleton variant="list" />}
          {isError && <ErrorState title="Couldn't load issues" description="Check API auth or wait for backend to start." />}
          {!isLoading && !isError && issues.length === 0 && (
            <div className="flex flex-col items-center justify-center py-20 text-center text-ink-3">
              <CheckCircle2 className="h-10 w-10 text-pos mb-3" />
              <p className="text-[15px] font-medium text-ink">No issues match this filter</p>
              <p className="text-[12px] mt-1">Try a different status or priority, or wait for the next triage run.</p>
            </div>
          )}
          {issues.length > 0 && (
            <div className="space-y-2">
              {issues.map(issue => (
                <IssueCard
                  key={issue.issue_id}
                  issue={issue}
                  onClick={() => setSelected(issue)}
                />
              ))}
              <p className="text-center text-[11px] text-ink-4 pt-3">
                {issues.length} of {issueData?.total} issues
              </p>
            </div>
          )}
        </div>
      </div>

      {/* drawer */}
      {selected && (
        <IssueDrawer
          issue={selected}
          onClose={() => setSelected(null)}
        />
      )}
    </div>
  );
}
