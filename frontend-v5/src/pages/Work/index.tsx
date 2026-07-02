/**
 * Work — program tracker + issues dashboard at /v5/work
 *
 * Jira-like: Epic → Story → Task hierarchy across a Phase 1/2/3 timeline.
 * Three views (Roadmap default · Backlog · Board), a shared filter rail, and a
 * tabbed detail drawer (Overview / Design / Implementation / Tests / Artifacts /
 * Activity). Also still surfaces auto-filed error issues (they render as
 * unphased tasks under "Inbox"). Admin-only.
 */
import { useState, useMemo, useCallback } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Bug, Zap, AlertTriangle, CheckCircle2, Clock, RefreshCw, X, ChevronRight, ChevronDown,
  Code2, GitPullRequest, ExternalLink, MessageSquare, FlaskConical, Wrench, FileText,
  Camera, Layers, GitBranch, Circle, Calendar, ListTree, LayoutGrid, Palette, Paperclip,
  GitCommit, Target,
} from "lucide-react";
import { workAdapter, type IssuesFilter, type IssueUpdate } from "@/services/adapters/work.adapter";
import type { WorkIssue, WorkStats } from "@/services/contracts/work.contract";
import { LoadingSkeleton } from "@/components/shared/LoadingSkeleton";
import { ErrorState } from "@/components/shared/ErrorState";

// ── Meta maps ──────────────────────────────────────────────────────────────────

const PRIORITY_META: Record<string, { label: string; dot: string; bg: string; text: string }> = {
  P1: { label: "P1 Critical", dot: "bg-neg",  bg: "bg-[rgb(var(--neg)/0.08)]",  text: "text-neg"  },
  P2: { label: "P2 High",     dot: "bg-warm", bg: "bg-[rgb(var(--warm)/0.08)]", text: "text-warm" },
  P3: { label: "P3 Normal",   dot: "bg-ink-4",bg: "bg-surface-2",               text: "text-ink-3"},
};

const STATUS_META: Record<string, { label: string; icon: React.ReactNode; text: string }> = {
  open:        { label: "Open",        icon: <Bug className="h-3.5 w-3.5" />,           text: "text-neg"  },
  in_progress: { label: "In progress", icon: <Clock className="h-3.5 w-3.5" />,         text: "text-warm" },
  in_review:   { label: "In review",   icon: <GitPullRequest className="h-3.5 w-3.5" />,text: "text-accent"},
  testing_qa:  { label: "Testing / QA",icon: <FlaskConical className="h-3.5 w-3.5" />,  text: "text-accent"},
  resolved:    { label: "Resolved",    icon: <CheckCircle2 className="h-3.5 w-3.5" />,  text: "text-pos"  },
  wont_fix:    { label: "Won't fix",   icon: <X className="h-3.5 w-3.5" />,             text: "text-ink-3"},
};

const CLASSIFICATION_META: Record<string, { label: string; text: string; bg: string }> = {
  unclassified:        { label: "Unclassified",         text: "text-ink-4", bg: "bg-surface-2" },
  valid:               { label: "Valid issue",          text: "text-neg",   bg: "bg-[rgb(var(--neg)/0.08)]" },
  business_validation: { label: "Business validation",  text: "text-ink-3", bg: "bg-surface-2" },
  tbd:                 { label: "TBD — needs input",    text: "text-accent",bg: "bg-[rgb(var(--accent)/0.08)]" },
};

const TYPE_META: Record<string, { label: string; icon: React.ReactNode; text: string }> = {
  epic:  { label: "Epic",  icon: <Layers className="h-3.5 w-3.5" />,    text: "text-accent" },
  story: { label: "Story", icon: <GitBranch className="h-3.5 w-3.5" />, text: "text-pos" },
  task:  { label: "Task",  icon: <Circle className="h-3 w-3" />,        text: "text-ink-3" },
};

const PHASE_META: Record<string, { label: string; sub: string }> = {
  "phase-1": { label: "Phase 1", sub: "Internal foundations" },
  "phase-2": { label: "Phase 2", sub: "Transactional core" },
  "phase-3": { label: "Phase 3", sub: "Breadth" },
};
const PHASES = ["phase-1", "phase-2", "phase-3"] as const;

const WORKFLOWS = ["WF-01", "WF-02", "WF-03", "WF-04", "WF-05", "WF-06", "WF-07"] as const;

const WORK_STATUS_ORDER = ["open", "in_progress", "in_review", "testing_qa", "resolved", "wont_fix"] as const;

function timeAgo(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 60)   return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24)    return `${hrs}h ago`;
  return `${Math.floor(hrs / 24)}d ago`;
}

function TrackChip({ track }: { track?: string | null }) {
  if (!track) return null;
  const vendor = track === "vendor-gated";
  return (
    <span className={`font-mono text-[9px] px-1.5 py-0.5 rounded uppercase tracking-[.06em] ${
      vendor ? "text-warm bg-[rgb(var(--warm)/0.1)]" : "text-pos bg-[rgb(var(--pos)/0.08)]"
    }`}>
      {vendor ? "vendor-gated" : "internal"}
    </span>
  );
}

// ── Hierarchy assembly ───────────────────────────────────────────────────────

interface TaskNode  { issue: WorkIssue }
interface StoryNode { issue: WorkIssue; tasks: WorkIssue[] }
interface EpicNode  { issue: WorkIssue; stories: StoryNode[]; looseTasks: WorkIssue[] }

interface Tree {
  epics: EpicNode[];
  inbox: WorkIssue[]; // orphan tasks (e.g. auto-filed error issues) with no parent
}

function buildTree(issues: WorkIssue[]): Tree {
  const byId = new Map(issues.map(i => [i.issue_id, i]));
  const epics: EpicNode[] = issues.filter(i => i.issue_type === "epic").map(e => ({ issue: e, stories: [], looseTasks: [] }));
  const epicById = new Map(epics.map(e => [e.issue.issue_id, e]));

  const stories = issues.filter(i => i.issue_type === "story");
  const storyById = new Map<string, StoryNode>();
  for (const s of stories) {
    const node: StoryNode = { issue: s, tasks: [] };
    storyById.set(s.issue_id, node);
    const parentEpic = s.parent ? epicById.get(s.parent) : undefined;
    if (parentEpic) parentEpic.stories.push(node);
  }

  const inbox: WorkIssue[] = [];
  for (const t of issues.filter(i => i.issue_type === "task")) {
    const parent = t.parent ? byId.get(t.parent) : undefined;
    if (parent?.issue_type === "story") {
      storyById.get(t.parent!)?.tasks.push(t);
    } else if (parent?.issue_type === "epic") {
      epicById.get(t.parent!)?.looseTasks.push(t);
    } else {
      inbox.push(t); // no parent (error issues) or dangling parent
    }
  }
  // stories whose epic is missing → surface as pseudo-epics so they aren't lost
  for (const s of stories) {
    if (s.parent && !epicById.get(s.parent)) {
      const node = storyById.get(s.issue_id)!;
      epics.push({ issue: s, stories: [node], looseTasks: [] });
    }
  }
  return { epics, inbox };
}

function epicTasks(e: EpicNode): WorkIssue[] {
  return [...e.looseTasks, ...e.stories.flatMap(s => s.tasks)];
}
function progressOf(tasks: WorkIssue[]): { done: number; total: number; pct: number } {
  const total = tasks.length;
  const done = tasks.filter(t => t.status === "resolved").length;
  return { done, total, pct: total ? Math.round((done / total) * 100) : 0 };
}

// ── Filtering (keep ancestors of any surviving node) ──────────────────────────

interface Facets { phase?: string; issue_type?: string; workflow?: string; track?: string; status?: string; priority?: string }

function matches(i: WorkIssue, f: Facets): boolean {
  if (f.phase && i.phase !== f.phase) return false;
  if (f.issue_type && i.issue_type !== f.issue_type) return false;
  if (f.workflow && !(i.workflow ?? []).includes(f.workflow)) return false;
  if (f.track && i.track !== f.track) return false;
  if (f.status && i.status !== f.status) return false;
  if (f.priority && i.priority !== f.priority) return false;
  return true;
}

// ── Progress bar ──────────────────────────────────────────────────────────────

function ProgressBar({ pct, hatched }: { pct: number; hatched?: boolean }) {
  return (
    <div className="h-1.5 rounded-full bg-surface-2 overflow-hidden">
      <div
        className={`h-full rounded-full ${hatched ? "bg-warm/60" : "bg-accent"}`}
        style={{ width: `${Math.max(pct, 2)}%` }}
      />
    </div>
  );
}

// ── Stats bar ───────────────────────────────────────────────────────────────

function StatsBar({ stats, counts }: { stats: WorkStats; counts: { epics: number; stories: number; tasks: number } }) {
  return (
    <div className="flex items-center gap-4 text-[12px] flex-wrap">
      <span className="text-accent font-semibold">{counts.epics} epics</span>
      <span className="text-pos font-semibold">{counts.stories} stories</span>
      <span className="text-ink-2">{counts.tasks} tasks</span>
      <span className="h-3 w-px bg-hairline mx-1" />
      <span className="text-neg font-semibold">{stats.by_priority["P1"] ?? 0} P1</span>
      <span className="text-warm">{stats.by_priority["P2"] ?? 0} P2</span>
      <span className="text-ink-3">{stats.by_priority["P3"] ?? 0} P3</span>
      <span className="h-3 w-px bg-hairline mx-1" />
      <span className="text-pos">{stats.by_status["resolved"] ?? 0} done</span>
      <span className="text-ink-4 font-mono">{stats.total} total</span>
    </div>
  );
}

// ── View switcher ─────────────────────────────────────────────────────────────

type View = "roadmap" | "backlog" | "board";
function ViewSwitcher({ view, onChange }: { view: View; onChange(v: View): void }) {
  const items: { key: View; label: string; icon: React.ReactNode }[] = [
    { key: "roadmap", label: "Roadmap", icon: <Calendar className="h-3.5 w-3.5" /> },
    { key: "backlog", label: "Backlog", icon: <ListTree className="h-3.5 w-3.5" /> },
    { key: "board",   label: "Board",   icon: <LayoutGrid className="h-3.5 w-3.5" /> },
  ];
  return (
    <div className="flex items-center gap-1 rounded-lg border border-hairline p-0.5">
      {items.map(it => (
        <button
          key={it.key}
          onClick={() => onChange(it.key)}
          className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md text-[12px] transition-colors ${
            view === it.key ? "bg-accent text-on-accent font-medium" : "text-ink-3 hover:text-ink"
          }`}
        >
          {it.icon}{it.label}
        </button>
      ))}
    </div>
  );
}

// ── Roadmap view (default) ──────────────────────────────────────────────────

function EpicBar({ epic, onOpen }: { epic: EpicNode; onOpen(i: WorkIssue): void }) {
  const tasks = epicTasks(epic);
  const prog = progressOf(tasks);
  const vendor = epic.issue.track === "vendor-gated";
  const pm = PRIORITY_META[epic.issue.priority] ?? PRIORITY_META.P2;
  return (
    <button
      onClick={() => onOpen(epic.issue)}
      className="w-full text-left rounded-xl border border-hairline p-3 hover:border-accent/40 hover:shadow-md transition-all bg-surface-1"
    >
      <div className="flex items-center gap-2 mb-1.5">
        <Layers className="h-3.5 w-3.5 text-accent shrink-0" />
        <span className="font-mono text-[10px] text-ink-4">{epic.issue.issue_id}</span>
        <span className={`ml-auto h-2 w-2 rounded-full ${pm.dot}`} />
      </div>
      <p className="text-[12px] font-medium text-ink leading-snug line-clamp-2">{epic.issue.title}</p>
      <div className="flex items-center gap-2 mt-2 flex-wrap">
        <TrackChip track={epic.issue.track} />
        {(epic.issue.workflow ?? []).slice(0, 3).map(w => (
          <span key={w} className="font-mono text-[9px] text-ink-4 bg-surface-2 px-1 rounded">{w}</span>
        ))}
      </div>
      <div className="mt-2">
        <ProgressBar pct={prog.pct} hatched={vendor} />
        <p className="text-[10px] text-ink-4 mt-1 font-mono">{prog.done}/{prog.total} tasks{epic.issue.estimate ? ` · ${epic.issue.estimate}` : ""}</p>
      </div>
    </button>
  );
}

function RoadmapView({ epics, onOpen }: { epics: EpicNode[]; onOpen(i: WorkIssue): void }) {
  return (
    <div className="grid grid-cols-1 md:grid-cols-3 gap-4 min-h-0">
      {PHASES.map(ph => {
        const inPhase = epics.filter(e => e.issue.phase === ph);
        const meta = PHASE_META[ph];
        return (
          <div key={ph} className="flex flex-col min-w-0">
            <div className="sticky top-0 bg-bg pb-2 mb-1 border-b border-hairline">
              <p className="text-[13px] font-semibold text-ink">{meta.label}</p>
              <p className="text-[11px] text-ink-4">{meta.sub} · {inPhase.length} epics</p>
            </div>
            <div className="space-y-2">
              {inPhase.length === 0 && (
                <p className="text-[11px] text-ink-4 italic py-4 text-center">No epics in this phase</p>
              )}
              {inPhase.map(e => <EpicBar key={e.issue.issue_id} epic={e} onOpen={onOpen} />)}
            </div>
          </div>
        );
      })}
      <div className="col-span-full text-[10px] text-ink-4 font-mono pt-2 flex gap-4">
        <span><span className="inline-block h-2 w-4 rounded bg-accent align-middle" /> internal build</span>
        <span><span className="inline-block h-2 w-4 rounded bg-warm/60 align-middle" /> vendor-gated</span>
      </div>
    </div>
  );
}

// ── Backlog (hierarchy) view ──────────────────────────────────────────────────

function TypeGlyph({ type }: { type: string }) {
  const m = TYPE_META[type] ?? TYPE_META.task;
  return <span className={m.text}>{m.icon}</span>;
}

function TaskRow({ issue, depth, onOpen }: { issue: WorkIssue; depth: number; onOpen(i: WorkIssue): void }) {
  const sm = STATUS_META[issue.status] ?? STATUS_META.open;
  const pm = PRIORITY_META[issue.priority] ?? PRIORITY_META.P2;
  return (
    <button
      onClick={() => onOpen(issue)}
      className="w-full text-left flex items-center gap-2 py-1.5 px-2 rounded-lg hover:bg-surface-2 transition-colors"
      style={{ paddingLeft: 8 + depth * 20 }}
    >
      <TypeGlyph type={issue.issue_type} />
      <span className="font-mono text-[10px] text-ink-4 shrink-0">{issue.issue_id}</span>
      <span className="text-[12px] text-ink truncate">{issue.title}</span>
      <span className={`ml-auto flex items-center gap-1 text-[10px] shrink-0 ${sm.text}`}>{sm.icon}{sm.label}</span>
      <span className={`h-2 w-2 rounded-full shrink-0 ${pm.dot}`} title={pm.label} />
    </button>
  );
}

function StoryRow({ node, depth, onOpen }: { node: StoryNode; depth: number; onOpen(i: WorkIssue): void }) {
  const [open, setOpen] = useState(true);
  const prog = progressOf(node.tasks);
  return (
    <div>
      <div className="flex items-center gap-2 py-1.5 px-2 rounded-lg hover:bg-surface-2" style={{ paddingLeft: 8 + depth * 20 }}>
        <button onClick={() => setOpen(o => !o)} className="text-ink-4 shrink-0">
          {node.tasks.length ? (open ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />) : <span className="inline-block w-3.5" />}
        </button>
        <TypeGlyph type="story" />
        <button onClick={() => onOpen(node.issue)} className="flex items-center gap-2 min-w-0 flex-1 text-left">
          <span className="font-mono text-[10px] text-ink-4 shrink-0">{node.issue.issue_id}</span>
          <span className="text-[12px] font-medium text-ink truncate">{node.issue.title}</span>
        </button>
        <span className="text-[10px] text-ink-4 font-mono shrink-0">{prog.done}/{prog.total}</span>
        <span className="w-16 shrink-0"><ProgressBar pct={prog.pct} /></span>
      </div>
      {open && node.tasks.map(t => <TaskRow key={t.issue_id} issue={t} depth={depth + 1} onOpen={onOpen} />)}
    </div>
  );
}

function EpicRow({ node, onOpen }: { node: EpicNode; onOpen(i: WorkIssue): void }) {
  const [open, setOpen] = useState(true);
  const tasks = epicTasks(node);
  const prog = progressOf(tasks);
  const pm = PRIORITY_META[node.issue.priority] ?? PRIORITY_META.P2;
  const children = node.stories.length + node.looseTasks.length;
  return (
    <div className="rounded-xl border border-hairline overflow-hidden">
      <div className={`flex items-center gap-2 py-2.5 px-3 ${pm.bg}`}>
        <button onClick={() => setOpen(o => !o)} className="text-ink-3 shrink-0">
          {children ? (open ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />) : <span className="inline-block w-4" />}
        </button>
        <Layers className="h-4 w-4 text-accent shrink-0" />
        <button onClick={() => onOpen(node.issue)} className="flex items-center gap-2 min-w-0 flex-1 text-left">
          <span className="font-mono text-[10px] text-ink-4 shrink-0">{node.issue.issue_id}</span>
          <span className="text-[13px] font-semibold text-ink truncate">{node.issue.title}</span>
        </button>
        {node.issue.phase && <span className="text-[10px] text-ink-4 shrink-0">{PHASE_META[node.issue.phase]?.label}</span>}
        <TrackChip track={node.issue.track} />
        <span className="text-[10px] text-ink-4 font-mono shrink-0">{prog.done}/{prog.total}</span>
        <span className="w-20 shrink-0"><ProgressBar pct={prog.pct} hatched={node.issue.track === "vendor-gated"} /></span>
      </div>
      {open && (
        <div className="py-1">
          {node.stories.map(s => <StoryRow key={s.issue.issue_id} node={s} depth={1} onOpen={onOpen} />)}
          {node.looseTasks.map(t => <TaskRow key={t.issue_id} issue={t} depth={1} onOpen={onOpen} />)}
          {children === 0 && <p className="text-[11px] text-ink-4 italic px-3 py-2">No stories/tasks yet</p>}
        </div>
      )}
    </div>
  );
}

function BacklogView({ tree, onOpen }: { tree: Tree; onOpen(i: WorkIssue): void }) {
  return (
    <div className="space-y-3">
      {tree.epics.map(e => <EpicRow key={e.issue.issue_id} node={e} onOpen={onOpen} />)}
      {tree.inbox.length > 0 && (
        <div className="rounded-xl border border-hairline overflow-hidden">
          <div className="flex items-center gap-2 py-2.5 px-3 bg-surface-2">
            <Bug className="h-4 w-4 text-ink-4" />
            <span className="text-[13px] font-semibold text-ink-3">Inbox — unassigned / auto-filed</span>
            <span className="ml-auto text-[10px] text-ink-4 font-mono">{tree.inbox.length}</span>
          </div>
          <div className="py-1">
            {tree.inbox.map(t => <TaskRow key={t.issue_id} issue={t} depth={1} onOpen={onOpen} />)}
          </div>
        </div>
      )}
      {tree.epics.length === 0 && tree.inbox.length === 0 && (
        <div className="flex flex-col items-center justify-center py-20 text-center text-ink-3">
          <CheckCircle2 className="h-10 w-10 text-pos mb-3" />
          <p className="text-[15px] font-medium text-ink">Nothing matches this filter</p>
        </div>
      )}
    </div>
  );
}

// ── Board (kanban) view ─────────────────────────────────────────────────────

function BoardCard({ issue, onOpen }: { issue: WorkIssue; onOpen(i: WorkIssue): void }) {
  const pm = PRIORITY_META[issue.priority] ?? PRIORITY_META.P2;
  return (
    <button onClick={() => onOpen(issue)} className={`w-full text-left rounded-lg border border-hairline p-2.5 hover:border-accent/40 transition-all ${pm.bg}`}>
      <div className="flex items-center gap-1.5 mb-1">
        <TypeGlyph type={issue.issue_type} />
        <span className="font-mono text-[9px] text-ink-4">{issue.issue_id}</span>
        <span className={`ml-auto h-1.5 w-1.5 rounded-full ${pm.dot}`} />
      </div>
      <p className="text-[11px] text-ink leading-snug line-clamp-3">{issue.title}</p>
    </button>
  );
}

function BoardView({ issues, onOpen }: { issues: WorkIssue[]; onOpen(i: WorkIssue): void }) {
  const cols = WORK_STATUS_ORDER.filter(s => s !== "wont_fix");
  return (
    <div className="flex gap-3 overflow-x-auto h-full pb-2">
      {cols.map(col => {
        const items = issues.filter(i => i.status === col && i.issue_type !== "epic");
        return (
          <div key={col} className="w-64 shrink-0 flex flex-col">
            <div className="flex items-center gap-1.5 mb-2 px-1">
              {STATUS_META[col].icon}
              <span className="text-[12px] font-medium text-ink">{STATUS_META[col].label}</span>
              <span className="ml-auto text-[10px] text-ink-4 font-mono">{items.length}</span>
            </div>
            <div className="space-y-2 overflow-y-auto">
              {items.map(i => <BoardCard key={i.issue_id} issue={i} onOpen={onOpen} />)}
            </div>
          </div>
        );
      })}
    </div>
  );
}

// ── Detail drawer (tabbed) ────────────────────────────────────────────────────

type Tab = "overview" | "design" | "impl" | "tests" | "artifacts" | "activity";

function MdBlock({ text }: { text?: string | null }) {
  if (!text) return <p className="text-[12px] text-ink-4 italic">Not documented yet.</p>;
  return (
    <pre className="text-[12px] bg-surface-1 border border-hairline rounded-lg p-3 text-ink-2 whitespace-pre-wrap break-words">{text}</pre>
  );
}

function IssueDrawer({ issue, allById, onClose, onOpen }: {
  issue: WorkIssue; allById: Map<string, WorkIssue>; onClose(): void; onOpen(i: WorkIssue): void;
}) {
  const qc = useQueryClient();
  const pm = PRIORITY_META[issue.priority] ?? PRIORITY_META.P2;
  const tm = TYPE_META[issue.issue_type] ?? TYPE_META.task;
  const [tab, setTab] = useState<Tab>("overview");
  const [comment, setComment] = useState("");

  const updateMutation = useMutation({
    mutationFn: (u: IssueUpdate) => workAdapter.update(issue.issue_id, u),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["work-issues"] });
      qc.invalidateQueries({ queryKey: ["work-stats"] });
    },
  });
  const fixMutation = useMutation({
    mutationFn: () => workAdapter.triggerFix(issue.issue_id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["work-issues"] }),
  });

  const setStatus = (s: string) => updateMutation.mutate({ status: s });
  const submitComment = () => { if (comment.trim()) { updateMutation.mutate({ comment: comment.trim() }); setComment(""); } };

  const parent = issue.parent ? allById.get(issue.parent) : undefined;
  const grandparent = parent?.parent ? allById.get(parent.parent) : undefined;
  const rem = issue.remediation;
  const fixInFlight = rem?.status === "queued" || rem?.status === "running";

  const TABS: { key: Tab; label: string; icon: React.ReactNode }[] = [
    { key: "overview",  label: "Overview",       icon: <Target className="h-3.5 w-3.5" /> },
    { key: "design",    label: "Design",         icon: <Palette className="h-3.5 w-3.5" /> },
    { key: "impl",      label: "Implementation", icon: <Code2 className="h-3.5 w-3.5" /> },
    { key: "tests",     label: "Tests",          icon: <FlaskConical className="h-3.5 w-3.5" /> },
    { key: "artifacts", label: "Artifacts",      icon: <Paperclip className="h-3.5 w-3.5" /> },
    { key: "activity",  label: "Activity",       icon: <MessageSquare className="h-3.5 w-3.5" /> },
  ];

  return (
    <div className="fixed inset-0 z-50 flex">
      <div className="flex-1 bg-black/40" onClick={onClose} />
      <aside className="w-full max-w-[680px] bg-bg border-l border-hairline flex flex-col h-full overflow-hidden">
        {/* header */}
        <div className="px-6 py-4 border-b border-hairline shrink-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className={tm.text}>{tm.icon}</span>
            <span className="font-mono text-[11px] text-ink-4">{issue.issue_id}</span>
            <span className={`font-mono text-[10px] px-1.5 py-0.5 rounded uppercase ${pm.bg} ${pm.text}`}>{pm.label}</span>
            {issue.phase && <span className="text-[10px] text-ink-3">{PHASE_META[issue.phase]?.label}</span>}
            <TrackChip track={issue.track} />
            {(issue.workflow ?? []).map(w => <span key={w} className="font-mono text-[9px] text-ink-4 bg-surface-2 px-1 rounded">{w}</span>)}
            <button onClick={onClose} className="ml-auto text-ink-4 hover:text-ink p-1"><X className="h-4 w-4" /></button>
          </div>
          {(grandparent || parent) && (
            <div className="flex items-center gap-1 mt-2 text-[10px] text-ink-4 font-mono">
              {grandparent && <><button className="hover:text-accent" onClick={() => onOpen(grandparent)}>{grandparent.issue_id}</button><ChevronRight className="h-3 w-3" /></>}
              {parent && <><button className="hover:text-accent" onClick={() => onOpen(parent)}>{parent.issue_id}</button><ChevronRight className="h-3 w-3" /></>}
              <span className="text-ink-3">{issue.issue_id}</span>
            </div>
          )}
          <h2 className="text-[16px] font-semibold text-ink leading-snug mt-2">{issue.title}</h2>
        </div>

        {/* tab bar */}
        <div className="flex items-center gap-1 px-4 border-b border-hairline shrink-0 overflow-x-auto">
          {TABS.map(t => (
            <button key={t.key} onClick={() => setTab(t.key)}
              className={`flex items-center gap-1.5 px-3 py-2.5 text-[12px] border-b-2 -mb-px transition-colors whitespace-nowrap ${
                tab === t.key ? "border-accent text-ink font-medium" : "border-transparent text-ink-4 hover:text-ink-2"
              }`}>
              {t.icon}{t.label}
            </button>
          ))}
        </div>

        <div className="flex-1 overflow-y-auto px-6 py-5 space-y-6">
          {tab === "overview" && (
            <>
              <div>
                <p className="text-[11px] font-mono uppercase tracking-[.1em] text-ink-4 mb-2">Requirements</p>
                <MdBlock text={issue.requirements_md || issue.sample_message} />
              </div>
              <div className="flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-ink-3">
                {issue.estimate && <span>Size: <b className="text-ink">{issue.estimate}</b></span>}
                {issue.endpoint && <span>Endpoint: <span className="font-mono">{issue.endpoint}</span></span>}
                {issue.exception_class && <span>Exception: <span className="font-mono text-warm">{issue.exception_class}</span></span>}
              </div>
              <div>
                <p className="text-[11px] font-mono uppercase tracking-[.1em] text-ink-4 mb-2">Status</p>
                <div className="flex gap-2 flex-wrap">
                  {WORK_STATUS_ORDER.map(s => (
                    <button key={s} onClick={() => setStatus(s)} disabled={issue.status === s || updateMutation.isPending}
                      className={`text-[12px] px-3 py-1.5 rounded-lg border flex items-center gap-1.5 transition-colors ${
                        issue.status === s ? "bg-accent text-on-accent border-accent font-medium" : "border-hairline text-ink-3 hover:text-ink hover:border-accent/40"
                      }`}>
                      {STATUS_META[s]?.icon}{STATUS_META[s]?.label}
                    </button>
                  ))}
                </div>
              </div>
              {issue.classification === "valid" && (
                <div className="rounded-xl border border-accent/30 bg-[rgb(var(--accent)/0.04)] p-4 flex items-center gap-2">
                  <Wrench className="h-4 w-4 text-accent shrink-0" />
                  <p className="text-[12px] text-ink-3 flex-1">Fix agent — isolated clone, opens a PR (never auto-merges).</p>
                  <button onClick={() => fixMutation.mutate()} disabled={fixInFlight || fixMutation.isPending}
                    className="px-3 py-1.5 rounded-lg bg-accent text-on-accent text-[12px] font-medium disabled:opacity-40">
                    {fixInFlight ? "Fixing…" : "Fix it"}
                  </button>
                </div>
              )}
            </>
          )}

          {tab === "design" && (
            <>
              <div>
                <p className="text-[11px] font-mono uppercase tracking-[.1em] text-ink-4 mb-2 flex items-center gap-1.5"><Palette className="h-3.5 w-3.5" />Design elements</p>
                <MdBlock text={issue.design_md} />
              </div>
              {issue.screens && issue.screens.length > 0 && (
                <div>
                  <p className="text-[11px] font-mono uppercase tracking-[.1em] text-ink-4 mb-2">Screens ({issue.screens.length})</p>
                  <div className="grid grid-cols-2 gap-2">
                    {issue.screens.map((s: any, i: number) => (
                      <a key={i} href={s?.url || "#"} target="_blank" rel="noreferrer" className="rounded-lg border border-hairline p-2 hover:border-accent/40 text-[11px] text-ink-2 truncate">{s?.name || s?.url || `screen ${i + 1}`}</a>
                    ))}
                  </div>
                </div>
              )}
            </>
          )}

          {tab === "impl" && (
            <>
              <div>
                <p className="text-[11px] font-mono uppercase tracking-[.1em] text-ink-4 mb-2 flex items-center gap-1.5"><Code2 className="h-3.5 w-3.5" />Core implementation</p>
                <MdBlock text={issue.implementation_md} />
              </div>
              <div>
                <p className="text-[11px] font-mono uppercase tracking-[.1em] text-ink-4 mb-2 flex items-center gap-1.5"><GitCommit className="h-3.5 w-3.5" />GitHub</p>
                {issue.github?.commit || issue.github?.pr_url || rem?.pr_url ? (
                  <div className="flex flex-wrap gap-3 text-[12px]">
                    {issue.github?.commit && <span className="font-mono text-ink-2">commit {issue.github.commit.slice(0, 10)}</span>}
                    {(issue.github?.pr_url || rem?.pr_url) && (
                      <a href={(issue.github?.pr_url || rem?.pr_url)!} target="_blank" rel="noreferrer" className="flex items-center gap-1 text-accent hover:underline">
                        <GitPullRequest className="h-3.5 w-3.5" />View PR<ExternalLink className="h-3 w-3" />
                      </a>
                    )}
                    {issue.github?.branch && <span className="font-mono text-ink-4">{issue.github.branch}</span>}
                  </div>
                ) : <p className="text-[12px] text-ink-4 italic">No commit/PR yet.</p>}
              </div>
              {issue.sample_traceback && (
                <div>
                  <p className="text-[11px] font-mono uppercase tracking-[.1em] text-ink-4 mb-2">Stack trace</p>
                  <pre className="text-[11px] bg-surface-1 border border-hairline rounded-lg p-3 font-mono text-neg whitespace-pre-wrap break-all max-h-48">{issue.sample_traceback}</pre>
                </div>
              )}
            </>
          )}

          {tab === "tests" && (
            <>
              <div>
                <p className="text-[11px] font-mono uppercase tracking-[.1em] text-ink-4 mb-2 flex items-center gap-1.5"><FlaskConical className="h-3.5 w-3.5" />Test cases</p>
                <MdBlock text={issue.test_doc_md || issue.test_document} />
              </div>
              {issue.rca && (
                <div className="rounded-xl border border-pos/30 bg-[rgb(var(--pos)/0.04)] p-4">
                  <p className="text-[11px] font-mono uppercase text-pos flex items-center gap-1.5 mb-1"><Zap className="h-3.5 w-3.5" />RCA</p>
                  <p className="text-[13px] text-ink">{issue.rca.root_cause || "—"}</p>
                </div>
              )}
            </>
          )}

          {tab === "artifacts" && (
            <>
              {issue.artifacts && issue.artifacts.length > 0 ? (
                <div className="space-y-2">
                  {issue.artifacts.map((a: any, i: number) => (
                    <a key={i} href={a?.url || "#"} target="_blank" rel="noreferrer" className="flex items-center gap-2 rounded-lg border border-hairline p-2.5 hover:border-accent/40 text-[12px] text-ink-2">
                      <Paperclip className="h-3.5 w-3.5 text-ink-4" />{a?.kind || "artifact"}<span className="ml-auto text-ink-4 font-mono truncate max-w-[50%]">{a?.url}</span>
                    </a>
                  ))}
                </div>
              ) : <p className="text-[12px] text-ink-4 italic">No implementation artifacts yet (PR, coverage, screenshots, deploy logs appear here once implemented).</p>}
              {issue.screenshots && issue.screenshots.length > 0 && (
                <div className="grid grid-cols-2 gap-2">
                  {issue.screenshots.map((src, i) => (
                    <a key={i} href={src} target="_blank" rel="noreferrer" className="rounded-lg border border-hairline overflow-hidden hover:border-accent/40">
                      <img src={src} alt={`shot ${i + 1}`} loading="lazy" className="w-full h-auto" />
                    </a>
                  ))}
                </div>
              )}
            </>
          )}

          {tab === "activity" && (
            <>
              {issue.comments.length > 0 ? (
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
              ) : <p className="text-[12px] text-ink-4 italic">No activity yet.</p>}
              <div>
                <textarea value={comment} onChange={e => setComment(e.target.value)} placeholder="Add a comment…" rows={3}
                  className="w-full rounded-lg bg-surface-1 border border-hairline px-3 py-2 text-[13px] text-ink placeholder-ink-4 resize-none focus:outline-none focus:border-accent/50" />
                <button onClick={submitComment} disabled={!comment.trim() || updateMutation.isPending}
                  className="mt-2 px-4 py-1.5 rounded-lg bg-accent text-on-accent text-[13px] font-medium disabled:opacity-40">Post</button>
              </div>
            </>
          )}
        </div>
      </aside>
    </div>
  );
}

// ── Filter rail ─────────────────────────────────────────────────────────────

function FilterPanel({ facets, onChange }: { facets: Facets; onChange(f: Facets): void }) {
  const grp = (key: keyof Facets, opts: { val: string | undefined; label: string }[], title: string) => (
    <div>
      <p className="font-mono text-[10px] uppercase tracking-[.12em] text-ink-4 mb-2">{title}</p>
      {opts.map(o => (
        <button key={o.label} onClick={() => onChange({ ...facets, [key]: o.val })}
          className={`w-full text-left px-3 py-1.5 rounded-lg text-[12px] transition-colors ${
            facets[key] === o.val ? "bg-accent/10 text-accent font-medium" : "text-ink-3 hover:text-ink hover:bg-surface-2"
          }`}>{o.label}</button>
      ))}
    </div>
  );
  return (
    <aside className="space-y-5 text-[12px]">
      {grp("phase", [{ val: undefined, label: "All phases" }, ...PHASES.map(p => ({ val: p, label: PHASE_META[p].label }))], "Phase")}
      {grp("issue_type", [{ val: undefined, label: "All types" }, { val: "epic", label: "Epics" }, { val: "story", label: "Stories" }, { val: "task", label: "Tasks" }], "Type")}
      {grp("track", [{ val: undefined, label: "All tracks" }, { val: "internal", label: "Internal" }, { val: "vendor-gated", label: "Vendor-gated" }], "Track")}
      {grp("workflow", [{ val: undefined, label: "All workflows" }, ...WORKFLOWS.map(w => ({ val: w, label: w }))], "Workflow")}
      {grp("priority", [{ val: undefined, label: "All" }, { val: "P1", label: "P1" }, { val: "P2", label: "P2" }, { val: "P3", label: "P3" }], "Priority")}
      {grp("status", [{ val: undefined, label: "All" }, ...WORK_STATUS_ORDER.map(s => ({ val: s, label: STATUS_META[s].label }))], "Status")}
    </aside>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function WorkPage() {
  const [view, setView]     = useState<View>("roadmap");
  const [facets, setFacets] = useState<Facets>({});
  const [selected, setSelected] = useState<WorkIssue | null>(null);

  const filter: IssuesFilter = { limit: 500 };
  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ["work-issues", filter],
    queryFn:  () => workAdapter.list(filter),
  });
  const { data: stats } = useQuery({ queryKey: ["work-stats"], queryFn: workAdapter.stats });

  const all = useMemo(() => data?.issues ?? [], [data]);
  const allById = useMemo(() => new Map(all.map(i => [i.issue_id, i])), [all]);

  // Facet filter: keep an item if it matches OR is an ancestor/descendant on the kept path.
  const filtered = useMemo(() => {
    const active = Object.values(facets).some(Boolean);
    if (!active) return all;
    const keep = new Set<string>();
    for (const i of all) {
      if (matches(i, facets)) {
        keep.add(i.issue_id);
        let p = i.parent ? allById.get(i.parent) : undefined;
        while (p) { keep.add(p.issue_id); p = p.parent ? allById.get(p.parent) : undefined; }
      }
    }
    return all.filter(i => keep.has(i.issue_id));
  }, [all, facets, allById]);

  const tree = useMemo(() => buildTree(filtered), [filtered]);
  const counts = useMemo(() => ({
    epics:   all.filter(i => i.issue_type === "epic").length,
    stories: all.filter(i => i.issue_type === "story").length,
    tasks:   all.filter(i => i.issue_type === "task").length,
  }), [all]);

  const onOpen = useCallback((i: WorkIssue) => setSelected(i), []);

  return (
    <div className="flex flex-col h-full min-h-0">
      <div className="shrink-0 px-6 py-4 border-b border-hairline flex items-center gap-4 flex-wrap">
        <div className="flex items-center gap-2">
          <Target className="h-5 w-5 text-accent" />
          <h1 className="text-[16px] font-semibold text-ink">Work Tracker</h1>
        </div>
        {stats && <StatsBar stats={stats} counts={counts} />}
        <div className="ml-auto flex items-center gap-3">
          <ViewSwitcher view={view} onChange={setView} />
          <button onClick={() => refetch()} className="flex items-center gap-1.5 text-[12px] text-ink-3 hover:text-ink px-3 py-1.5 rounded-lg border border-hairline hover:border-accent/40">
            <RefreshCw className="h-3.5 w-3.5" />Refresh
          </button>
        </div>
      </div>

      <div className="flex-1 min-h-0 flex">
        <div className="shrink-0 w-48 border-r border-hairline px-4 py-5 overflow-y-auto">
          <FilterPanel facets={facets} onChange={setFacets} />
        </div>
        <div className="flex-1 min-w-0 px-5 py-5 overflow-y-auto">
          {isLoading && <LoadingSkeleton variant="list" />}
          {isError && <ErrorState title="Couldn't load work items" description="Check API auth or wait for backend to start." />}
          {!isLoading && !isError && (
            <>
              {view === "roadmap" && <RoadmapView epics={tree.epics} onOpen={onOpen} />}
              {view === "backlog" && <BacklogView tree={tree} onOpen={onOpen} />}
              {view === "board"   && <BoardView issues={filtered} onOpen={onOpen} />}
            </>
          )}
        </div>
      </div>

      {selected && <IssueDrawer issue={selected} allById={allById} onClose={() => setSelected(null)} onOpen={onOpen} />}
    </div>
  );
}
