/**
 * 02 · Agent command centre — built to the owner's design (docs/autodesk/design/prototype/TDAgents.dc.html):
 * header + status legend, five agent cards, the selected agent's decision trace with permissions / model / escalation,
 * and the workflows in flight against the 13-step proposal workflow.
 *
 * Every value comes from the desk API (see ./agents/model.ts). What Phase 1 does not have is shown as such: queue depth
 * and scaling need a worker pool (Phase 3); steps 6–13 of a proposal are recorded by paper execution but not drawn yet. Text the agents
 * wrote (result_summary, errors) is shown as written. Read-only: this screen sends no request body.
 */
import { useMemo, useState, type CSSProperties } from "react";
import { useQueries } from "@tanstack/react-query";
import { errorText } from "../api";
import { ago, agentName, dateShort, DASH, humanize, timeIST, todayIST } from "../format";
import { useAccounts, useIsMobile, useNow } from "../hooks";
import { screenById, screenNo } from "../nav";
import type { AgentKey, AgentRow, AgentStatus, AgentTaskRow, WorkflowRow } from "../types";
import { Empty, ErrorBox, Loading, PhaseNote } from "../ui";
import {
  AGENT_ORDER, AGENT_ROLE, ESCALATION, HEALTHY, PHASE1_STEPS, STATUSES, STATUS_COLOR, STATUS_PILL, STEPS, cardStats,
  currentAgents, flowView, isInFlight, taskTitle, traceRows, useAgentRegistry, useAllActivity, useDeskPlans,
  useProposalWorkflows, useSignalsById, useWorkflowDetail, workflowQuery, type CardStats, type TraceTone,
} from "./agents/model";
import { countWord, joinNames, secs, shortId } from "./scanner/fmt";

const monoLabel: CSSProperties = { fontFamily: "var(--mono)", fontSize: 9, letterSpacing: "0.08em", color: "var(--ink-3)" };
const TONE: Record<TraceTone, string> = { ink: "var(--ink)", mint: "var(--mint)", amber: "var(--amber)", danger: "var(--danger)" };
const FLOW_ROWS = 8;

function when(v: string | null | undefined, now: number): string {
  if (!v) return DASH;
  const t = timeIST(v);
  return todayIST(new Date(v)) === todayIST(new Date(now)) ? t : `${dateShort(v)} ${t}`;
}

// ── headline ────────────────────────────────────────────────────────────────────────────────────────────────────────

function Headline({ agents }: { agents: AgentRow[] }) {
  if (!agents.length) return <>No agents are registered yet.</>;
  const names = (rs: AgentRow[]) => joinNames(rs.map((r) => agentName(r.agent_key)));
  const bad = agents.filter((a) => !HEALTHY.has(a.status));
  const busy = agents.filter((a) => a.status === "BUSY");
  const total = countWord(agents.length).toLowerCase();
  if (!bad.length) {
    return (
      <>
        All {total} agents are healthy.{" "}
        {busy.length ? <><em style={{ color: "var(--mint)" }}>{names(busy)}</em> {busy.length > 1 ? "are" : "is"} busy right now.</> : "None is busy right now."}
      </>
    );
  }
  const ok = agents.length - bad.length;
  const same = bad.every((b) => b.status === bad[0].status);
  return (
    <>
      {countWord(ok)} agent{ok === 1 ? " is" : "s are"} healthy.{" "}
      <em style={{ color: "var(--amber)" }}>{names(bad)}</em>{" "}
      {same ? `${bad.length > 1 ? "are" : "is"} ${bad[0].status.toLowerCase()}.` : `are not healthy (${bad.map((b) => `${agentName(b.agent_key)} ${b.status.toLowerCase()}`).join(", ")}).`}
    </>
  );
}

// ── agent card ──────────────────────────────────────────────────────────────────────────────────────────────────────

function taskLine(s: CardStats, now: number): string {
  if (s.open) return `${taskTitle(s.open.task_type)}${s.open.entity_id ? ` · ${shortId(s.open.entity_id)}` : ""} · ${humanize(s.open.state).toLowerCase()}`;
  if (s.last) return `Idle · last: ${taskTitle(s.last.task_type)}${s.last.entity_id ? ` ${shortId(s.last.entity_id)}` : ""}, ${ago(s.last.completed_at ?? s.last.created_at, now)}`;
  return "No desk tasks yet";
}

function AgentCard({ k, row, tasks, loading, error, selected, onPick, onPickTask, now }: {
  k: AgentKey; row: AgentRow | undefined; tasks: AgentTaskRow[] | undefined; loading: boolean; error: unknown;
  selected: boolean; onPick: () => void; onPickTask: (t: AgentTaskRow) => void; now: number;
}) {
  const st: AgentStatus = row?.status ?? "OFFLINE";
  const [c, line, soft] = STATUS_PILL[st] ?? STATUS_PILL.OFFLINE;
  const s = cardStats(tasks ?? []);
  const errC = s.errors ? "var(--amber)" : "var(--ink-3)";
  return (
    <div
      data-testid={`agent-card-${k}`}
      onClick={onPick}
      className="ad-hover-line"
      aria-pressed={selected}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => { if (e.target === e.currentTarget && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); onPick(); } }}
      style={{ cursor: "pointer", display: "flex", flexDirection: "column", gap: 12, padding: "16px 18px", borderRadius: 14, border: `1px solid ${selected ? "var(--line-3)" : "var(--line)"}`, background: "var(--bg-1)", boxShadow: "var(--shadow-card)", transition: "all .15s ease", minWidth: 0 }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <span className="nv-pill" data-testid="agent-status" style={{ color: c, borderColor: line, background: soft }}>
          <span className="nv-dot" style={{ background: c }} />{row ? st : "NOT REGISTERED"}
        </span>
        <span style={{ flex: 1 }} />
        <span className="nv-num" data-testid="agent-heartbeat" title="Last status change recorded in the agent registry" style={{ fontFamily: "var(--mono)", fontSize: 10, color: "var(--ink-3)" }}>
          ♥ {row?.last_heartbeat ? ago(row.last_heartbeat, now) : DASH}
        </span>
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
        <span style={{ fontFamily: "var(--display)", fontSize: 24, lineHeight: 1.05 }}>{agentName(k)}</span>
        <span className="nv-eyebrow" style={{ fontSize: 9.5 }}>{AGENT_ROLE[k]}</span>
      </div>
      {error ? (
        <span role="alert" data-testid="agent-activity-error" style={{ fontSize: 12.5, lineHeight: 1.45, color: "var(--danger)" }}>
          Activity could not be loaded: {errorText(error)}
        </span>
      ) : loading ? (
        <span style={{ fontSize: 13.5, color: "var(--ink-3)" }}>Loading tasks…</span>
      ) : (
        <span data-testid="agent-task" style={{ fontSize: 13.5, lineHeight: 1.45, color: "var(--ink-2)", overflowWrap: "anywhere" }}>{taskLine(s, now)}</span>
      )}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(2,minmax(0,1fr))", gap: 8 }}>
        <div style={{ display: "flex", flexDirection: "column", gap: 2 }} title="Queue depth needs a worker pool, which comes with Phase 3">
          <span style={monoLabel}>QUEUE</span>
          <span className="nv-num" data-testid="agent-queue" style={{ fontFamily: "var(--display)", fontSize: 22, lineHeight: 1 }}>{DASH}</span>
          <span style={{ fontFamily: "var(--mono)", fontSize: 9, color: "var(--ink-4)" }}>PHASE 3 · NO WORKER POOL</span>
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: 2, minWidth: 0 }}>
          <span style={monoLabel}>LAST SUCCESS</span>
          <span className="nv-num" data-testid="agent-last-success" title={s.lastSuccess?.entity_id ?? s.lastSuccess?.task_id ?? undefined} style={{ fontSize: 12.5, overflowWrap: "anywhere" }}>
            {s.lastSuccess ? `${when(s.lastSuccess.completed_at, now)} · ${shortId(s.lastSuccess.entity_id ?? s.lastSuccess.task_id)}` : DASH}
          </span>
        </div>
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 5, paddingTop: 10, borderTop: "1px solid var(--line)" }}>
        <span style={monoLabel}>RECENT DECISIONS</span>
        {!error && !loading && s.decisions.length === 0 && <span style={{ fontSize: 12, color: "var(--ink-3)" }}>None yet</span>}
        {s.decisions.map((t) => (
          <span
            key={t.task_id}
            data-testid={`decision-${t.task_id}`}
            role="button"
            tabIndex={0}
            onClick={(e) => { e.stopPropagation(); onPickTask(t); }}
            onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); e.stopPropagation(); onPickTask(t); } }}
            className="ad-hover"
            title="Show this decision's trace"
            style={{ fontSize: 12, lineHeight: 1.45, color: t.error && !t.result_summary ? "var(--amber)" : "var(--ink-2)", borderRadius: 6, overflowWrap: "anywhere" }}
          >
            <span className="nv-num" style={{ fontFamily: "var(--mono)", fontSize: 10.5, color: "var(--ink-3)" }}>{timeIST(t.completed_at ?? t.created_at, { seconds: false })}</span>{" "}
            {t.result_summary ?? t.error}
          </span>
        ))}
      </div>
      <span data-testid="agent-errors" style={{ fontSize: 11.5, color: errC, overflowWrap: "anywhere" }}>
        {error || loading ? "" : `${s.errors} error${s.errors === 1 ? "" : "s"} · ${s.retries} retr${s.retries === 1 ? "y" : "ies"} in the last ${s.window} desk task${s.window === 1 ? "" : "s"}${s.latestError ? ` · ${s.latestError}` : ""}`}
      </span>
    </div>
  );
}

// ── decision trace + side panels ────────────────────────────────────────────────────────────────────────────────────

function DecisionTrace({ agent, task, pad }: { agent: AgentKey; task: AgentTaskRow | null; pad: string }) {
  const detail = useWorkflowDetail(task?.workflow_id);
  const full = detail.data?.tasks?.find((t) => t.task_id === task?.task_id);
  const rows = full && detail.data ? traceRows(full, detail.data.workflow, detail.data.handoffs ?? [], secs) : [];
  return (
    <div data-testid="decision-trace" style={{ display: "flex", flexDirection: "column", gap: 14, padding: pad, borderRadius: 16, border: "1px solid var(--line-2)", background: "var(--bg-1)", boxShadow: "var(--shadow-card)", minWidth: 0 }}>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 8, alignItems: "center" }}>
        <span className="nv-eyebrow" data-testid="trace-eyebrow">Decision trace · {agentName(agent)}</span>
        {task && <span className="nv-pill" data-testid="trace-ref" title={task.entity_id ?? task.task_id} style={{ textTransform: "none" }}>{shortId(task.entity_id ?? task.task_id)}</span>}
      </div>
      {!task ? (
        <Empty testId="trace-empty">No desk task for {agentName(agent)} yet. Its decisions appear here once a session cycle has run.</Empty>
      ) : (
        <>
          <span data-testid="trace-title" style={{ fontFamily: "var(--display)", fontSize: 26, lineHeight: 1.15, overflowWrap: "anywhere" }}>
            {task.result_summary ?? task.error ?? `${taskTitle(task.task_type)} · ${task.state}`}
          </span>
          {detail.error ? (
            <ErrorBox error={detail.error} what="this decision's trace" onRetry={() => detail.refetch()} />
          ) : detail.isLoading ? (
            <Loading label="Loading the trace" rows={2} />
          ) : !full ? (
            <Empty>This task is not in its workflow's record ({shortId(task.workflow_id)}).</Empty>
          ) : (
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(min(100%,240px),1fr))", gap: 1, borderRadius: 12, overflow: "hidden", border: "1px solid var(--line)", background: "var(--line)" }}>
              {rows.map((t) => (
                <div key={t.k} data-testid={`trace-${t.k.toLowerCase().replace(/[^a-z]+/g, "-")}`} style={{ display: "flex", flexDirection: "column", gap: 4, padding: "11px 14px", background: "var(--bg-1)", minWidth: 0 }}>
                  <span style={{ fontFamily: "var(--mono)", fontSize: 9.5, letterSpacing: "0.08em", textTransform: "uppercase", color: "var(--ink-3)" }}>{t.k}</span>
                  <span style={{ fontSize: 13, lineHeight: 1.45, color: TONE[t.tone], overflowWrap: "anywhere" }}>{t.v}</span>
                </div>
              ))}
            </div>
          )}
        </>
      )}
      <span style={{ fontSize: 11.5, color: "var(--ink-3)" }}>A concise decision record with structured evidence and policy checks. Hidden model reasoning is neither stored nor shown.</span>
    </div>
  );
}

function SidePanels({ agent, row, stats }: { agent: AgentKey; row: AgentRow | undefined; stats: CardStats }) {
  const d = row?.descriptor ?? {};
  const allow = [...(d.task_types ?? []).map((t) => taskTitle(String(t))), ...(d.tools ?? []).map(String)];
  const deny = (d.prohibited ?? []).map(String);
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12, minWidth: 0 }}>
      <div data-testid="agent-permissions" style={{ display: "flex", flexDirection: "column", gap: 10, padding: "16px 18px", borderRadius: 14, border: "1px solid var(--line)", background: "var(--bg-1)" }}>
        <span className="nv-eyebrow">Permissions and tool access</span>
        {row ? (
          <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
            {allow.map((p) => <span key={`a-${p}`} data-testid="perm-allow" className="nv-pill nv-pill-mint" style={{ fontSize: 9.5, textTransform: "none" }}>✓ {p}</span>)}
            {deny.map((p) => <span key={`d-${p}`} data-testid="perm-deny" className="nv-pill" style={{ fontSize: 9.5, color: "var(--ink-3)", textTransform: "none" }}>× {p}</span>)}
          </div>
        ) : <span style={{ fontSize: 13, color: "var(--ink-3)" }}>Not in the agent registry.</span>}
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 8, padding: "16px 18px", borderRadius: 14, border: "1px solid var(--line)", background: "var(--bg-1)" }}>
        <span className="nv-eyebrow">Model and config</span>
        <span className="nv-num" data-testid="agent-model" style={{ fontFamily: "var(--mono)", fontSize: 12, color: "var(--ink-2)", overflowWrap: "anywhere" }}>
          {row ? `${row.version} · ${row.kind.toLowerCase().replace("_", " ")} · model ${row.model ?? DASH} · prompt ${row.prompt_version ?? DASH}` : DASH}
        </span>
        <span className="nv-eyebrow" style={{ paddingTop: 8 }}>Human escalation</span>
        <span data-testid="agent-escalation" style={{ fontSize: 13, lineHeight: 1.5, color: "var(--ink-2)" }}>
          {ESCALATION[agent]} {stats.escalated} escalated task{stats.escalated === 1 ? "" : "s"} in the last {stats.window} desk task{stats.window === 1 ? "" : "s"}.
        </span>
      </div>
    </div>
  );
}

// ── workflows in flight ─────────────────────────────────────────────────────────────────────────────────────────────

const tradeOf = (w: WorkflowRow): string | null => {
  const t = (w.outcome as Record<string, unknown> | null)?.trade_id;
  return typeof t === "string" ? t : null;
};
const signalOf = (w: WorkflowRow): string => {
  const s = (w.input ?? {}).signal_id;
  return typeof s === "string" ? s : "";
};

function WorkflowsInFlight({ mobile }: { mobile: boolean }) {
  const accounts = useAccounts();
  const deskIds = (accounts.data ?? []).filter((a) => a.kind !== "SIMULATION").map((a) => a.account_id);
  const flows = useProposalWorkflows(deskIds);
  const plans = useDeskPlans();
  const shown = useMemo(() => [...flows.rows.filter(isInFlight), ...flows.rows.filter((w) => !isInFlight(w))].slice(0, FLOW_ROWS), [flows.rows]);
  const planOf = new Map((plans.data ?? []).map((p) => [p.trade_id, p]));
  const needSignal = [...new Set(shown.filter((w) => !planOf.get(tradeOf(w) ?? "")).map(signalOf).filter(Boolean))];
  const sigs = useSignalsById(needSignal);
  const sigOf = new Map(sigs.filter((q) => q.data).map((q) => [q.data!.signal_id, q.data!]));
  const running = shown.filter((w) => w.state === "RUNNING");
  const runDetails = useQueries({ queries: running.map((w) => ({ ...workflowQuery(w.workflow_id), refetchInterval: 5000 })) });
  const tasksOf = new Map(runDetails.filter((q) => q.data).map((q) => [q.data!.workflow.workflow_id, q.data!.tasks]));
  const cols = mobile ? "minmax(0,1fr)" : "minmax(180px,240px) minmax(0,1fr) 220px";

  const name = (w: WorkflowRow): string => {
    const p = planOf.get(tradeOf(w) ?? "");
    if (p) return `${p.instrument} · ${humanize(p.strategy_type)}`;
    const s = sigOf.get(signalOf(w));
    if (s) return `${s.instrument} · ${humanize(s.category)} signal`;
    return signalOf(w) ? `Signal ${shortId(signalOf(w))}` : `Proposal ${shortId(w.workflow_id)}`;
  };

  let body;
  if (accounts.error) body = <div style={{ padding: 14 }}><ErrorBox error={accounts.error} what="the desk accounts" /></div>;
  else if (flows.error) body = <div style={{ padding: 14 }}><ErrorBox error={flows.error} what="the proposal workflows" onRetry={flows.refetch} /></div>;
  else if (accounts.isLoading || flows.loading) body = <div style={{ padding: 14 }}><Loading label="Loading workflows" rows={2} /></div>;
  else if (!shown.length) {
    body = <Empty testId="flows-empty">No trade proposal workflows on the desk yet. They start when a session cycle runs (Opportunity scanner › Run session cycle).</Empty>;
  } else {
    body = shown.map((w, i) => {
      const f = flowView(w, tasksOf.get(w.workflow_id));
      const trade = tradeOf(w);
      return (
        <div key={w.workflow_id} data-testid={`flow-${w.workflow_id}`} data-state={w.state} style={{ display: "grid", gridTemplateColumns: cols, gap: "8px 16px", alignItems: "center", padding: "12px 18px", borderTop: `1px solid ${i ? "var(--line)" : "transparent"}` }}>
          <div style={{ display: "flex", flexDirection: "column", gap: 2, minWidth: 0 }}>
            <span data-testid="flow-name" style={{ fontSize: 13.5, fontWeight: 500, overflowWrap: "anywhere" }}>{name(w)}</span>
            <span title={`${w.workflow_id}${trade ? ` · ${trade}` : ""}`} style={{ fontFamily: "var(--mono)", fontSize: 10, color: "var(--ink-3)" }}>{shortId(w.workflow_id)}{trade ? ` · ${shortId(trade)}` : ""}</span>
          </div>
          <div data-testid="flow-steps" style={{ display: "grid", gridTemplateColumns: "repeat(13,minmax(0,1fr))", gap: 3 }}>
            {STEPS.map((t, k) => {
              const done = k < f.done;
              const cur = f.cur === k;
              const title = k >= PHASE1_STEPS ? `${t} · not shown yet` : k === 3 && !f.revised && (done || cur) ? `${t} · not needed` : t;
              return <span key={t} data-step={k + 1} data-fill={cur ? "current" : done ? "done" : "none"} title={title} style={{ height: 8, borderRadius: 2, background: cur ? f.color : done ? "var(--mint-line)" : "var(--bg-3)" }} />;
            })}
          </div>
          <span data-testid="flow-at" style={{ fontSize: 12, lineHeight: 1.4, color: f.color }}>{f.label}</span>
        </div>
      );
    });
  }

  return (
    <section style={{ display: "flex", flexDirection: "column", gap: 10 }}>
      <span className="nv-eyebrow">Workflows in flight · 13-step trade proposal workflow</span>
      <div data-testid="workflows-in-flight" style={{ border: "1px solid var(--line)", borderRadius: 14, background: "var(--bg-1)", overflow: "hidden" }}>{body}</div>
      <PhaseNote label="Not shown yet" testId="flows-phase-note">
        Steps 6–13 (capital reservation, execution intent, orders and fills, the active position, risk events, position actions,
        reconciliation, journal) are not drawn here yet. For an approved plan the desk now records the reservation, the intent, paper
        orders and fills, the position and the journal, and it closes and reconciles positions; those steps are not drawn here yet.
      </PhaseNote>
    </section>
  );
}

// ── the screen ──────────────────────────────────────────────────────────────────────────────────────────────────────

export default function AgentsScreen() {
  const mobile = useIsMobile();
  const now = useNow(30_000);
  const def = screenById("agents");
  const registry = useAgentRegistry();
  const activity = useAllActivity();
  const [sel, setSel] = useState<AgentKey | null>(null);
  const [selTask, setSelTask] = useState<string | null>(null);

  const current = useMemo(() => currentAgents(registry.data ?? []), [registry.data]);
  const curRows = AGENT_ORDER.map((k) => current.get(k)).filter((r): r is AgentRow => !!r);
  const extra = [...current.values()].filter((r) => !AGENT_ORDER.includes(r.agent_key));
  const allCurrent = [...curRows, ...extra];

  // Default selection: the agent with the most recent desk task.
  let latestAgent: AgentKey = "AI_TRADER";
  let latestAt = "";
  for (let i = 0; i < AGENT_ORDER.length; i++) {
    const t = activity[i]?.data?.[0];
    if (t && t.created_at > latestAt) { latestAt = t.created_at; latestAgent = AGENT_ORDER[i]; }
  }
  const agent: AgentKey = sel ?? latestAgent;
  const agentQ = activity[AGENT_ORDER.indexOf(agent)];
  const agentTasks = agentQ?.data ?? [];
  const task = (selTask ? agentTasks.find((t) => t.task_id === selTask) : null) ?? agentTasks[0] ?? null;
  const counts = Object.fromEntries(STATUSES.map((s) => [s, allCurrent.filter((a) => a.status === s).length])) as Record<AgentStatus, number>;
  const versions = registry.data?.length ?? 0;

  return (
    <div data-testid="screen-agents" style={{ display: "flex", flexDirection: "column", gap: 22, fontFamily: "var(--sans)", color: "var(--ink)" }}>
      <section style={{ display: "flex", flexDirection: "column", gap: 12 }}>
        <div style={{ display: "flex", flexWrap: "wrap", gap: 8, alignItems: "center" }}>
          <span className="nv-eyebrow">{screenNo("agents")} · {def.label}</span>
          <span className="nv-pill nv-pill-indigo">Desk Orchestrator · deterministic</span>
          {registry.data && <span className="nv-pill" data-testid="agents-count">{allCurrent.length} agents · {versions} registered version{versions === 1 ? "" : "s"}</span>}
        </div>
        <h1 data-testid="agents-headline" style={{ margin: 0, fontFamily: "var(--display)", fontWeight: 400, fontSize: mobile ? 30 : 44, lineHeight: 1.06, letterSpacing: "-0.02em", textWrap: "pretty", maxWidth: 900 } as CSSProperties}>
          {registry.data ? <Headline agents={allCurrent} /> : def.label}
        </h1>
        <p style={{ margin: 0, fontSize: 14.5, lineHeight: 1.55, color: "var(--ink-3)", maxWidth: 700 }}>
          Agents discover, plan and explain. Deterministic services validate and control; execution is paper only, so
          no order reaches a broker. Every handoff is a structured record with a correlation ID; free-form text is never authoritative.
        </p>
      </section>

      {registry.error ? (
        <ErrorBox error={registry.error} what="the agent registry" onRetry={() => registry.refetch()} />
      ) : registry.isLoading ? (
        <Loading label="Loading agents" />
      ) : (
        <>
          <section data-testid="agent-legend" style={{ display: "flex", flexWrap: "wrap", gap: "6px 16px", fontFamily: "var(--mono)", fontSize: 10.5, letterSpacing: "0.06em", color: "var(--ink-3)" }}>
            {STATUSES.map((s) => (
              <span key={s} data-testid={`legend-${s}`} style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
                <span className="nv-dot" style={{ background: STATUS_COLOR[s] }} />{s} <span style={{ color: "var(--ink)" }}>{counts[s]}</span>
              </span>
            ))}
          </section>

          {curRows.length === 0 && <Empty testId="agents-empty">No agents are registered yet. The desk API registers its agents when it starts.</Empty>}

          <section style={{ display: "grid", gridTemplateColumns: `repeat(auto-fill,minmax(${mobile ? "100%" : "230px"},1fr))`, gap: 12 }}>
            {AGENT_ORDER.map((k, i) => (
              <AgentCard
                key={k}
                k={k}
                row={current.get(k)}
                tasks={activity[i]?.data}
                loading={!!activity[i]?.isLoading}
                error={activity[i]?.error}
                selected={k === agent}
                now={now}
                onPick={() => { setSel(k); setSelTask(null); }}
                onPickTask={(t) => { setSel(k); setSelTask(t.task_id); }}
              />
            ))}
          </section>

          <section style={{ display: "grid", gridTemplateColumns: mobile ? "minmax(0,1fr)" : "minmax(0,1.6fr) minmax(260px,1fr)", gap: 16, alignItems: "start" }}>
            {agentQ?.error ? (
              <ErrorBox error={agentQ.error} what={`${agentName(agent)}'s tasks`} />
            ) : (
              <DecisionTrace agent={agent} task={task} pad={mobile ? "18px 16px" : "20px 22px"} />
            )}
            <SidePanels agent={agent} row={current.get(agent)} stats={cardStats(agentTasks)} />
          </section>
        </>
      )}

      <WorkflowsInFlight mobile={mobile} />
    </div>
  );
}
