/**
 * Data and view model of the Agent command centre (design: docs/autodesk/design/prototype/TDAgents.dc.html).
 *
 * Sources (backend/autodesk/routers/api.py):
 *   GET /agents                               registry; the latest registered version of each agent is the current one
 *   GET /agents/{key}/activity?limit=…        task rows of one agent — the API mixes in simulation tasks, so rows with a
 *                                              simulation_id are dropped here (the desk shows the desk's own work)
 *   GET /desk/workflows/{id}                  workflow + full task rows + handoffs (the decision trace)
 *   GET /desk/workflows?account_id&kind=TRADE_PROPOSAL   proposal workflows per desk account (workflows in flight)
 *   GET /trade-plans, GET /signals/{id}       names of those workflows
 */
import { useQueries, useQuery } from "@tanstack/react-query";
import { deskGet } from "../../api";
import { agentName, humanize, rs } from "../../format";
import type { AgentKey, AgentRow, AgentStatus, AgentTaskRow, SignalRow, TradePlanRow, WorkflowRow } from "../../types";
import { shortId } from "../scanner/fmt";

export const AGENT_ORDER: AgentKey[] = ["AI_TRADER", "TRADING_ASSISTANT", "RISK_OPS", "MIDDLE_OFFICE", "TECH_SUPPORT"];

/** The design's role line under each agent's name (design labels). */
export const AGENT_ROLE: Record<AgentKey, string> = {
  AI_TRADER: "Opportunity hunter",
  TRADING_ASSISTANT: "Strategist and trader interface",
  RISK_OPS: "Risk guardian",
  MIDDLE_OFFICE: "Independent controller",
  TECH_SUPPORT: "Infrastructure guardian",
};

export const STATUSES: AgentStatus[] = ["IDLE", "BUSY", "SCALING", "DEGRADED", "MAINTENANCE", "QUARANTINED", "OFFLINE"];
export const STATUS_COLOR: Record<AgentStatus, string> = {
  IDLE: "var(--ink-2)", BUSY: "var(--mint)", SCALING: "var(--indigo)", DEGRADED: "var(--amber)",
  MAINTENANCE: "var(--ink-4)", QUARANTINED: "var(--rose)", OFFLINE: "var(--danger)",
};
/** Pill colours per status: [text, border, background], as the design's T table. */
export const STATUS_PILL: Record<AgentStatus, [string, string, string]> = {
  IDLE: ["var(--ink-2)", "var(--line-2)", "transparent"],
  BUSY: ["var(--mint)", "var(--mint-line)", "var(--mint-soft)"],
  SCALING: ["var(--indigo)", "var(--indigo-line)", "var(--indigo-soft)"],
  DEGRADED: ["var(--amber)", "var(--amber-line)", "var(--amber-soft)"],
  MAINTENANCE: ["var(--ink-4)", "var(--line-2)", "transparent"],
  QUARANTINED: ["var(--rose)", "var(--line-2)", "transparent"],
  OFFLINE: ["var(--danger)", "var(--danger-line)", "var(--danger-soft)"],
};
export const HEALTHY = new Set<string>(["IDLE", "BUSY"]);

/** Plain names of the task types the orchestrator hands out (contracts.TaskType). */
export const TASK_TITLE: Record<string, string> = {
  PREMARKET_HEALTH_CHECK: "Pre-market health check",
  SCAN_MARKET: "Market scan",
  GENERATE_STRATEGY: "Strategy for a signal",
  REVISE_STRATEGY: "Plan revision",
  ASSESS_RISK: "Risk assessment",
  REVIEW_FOR_APPROVAL: "Approval review",
};
export const taskTitle = (t: string): string => TASK_TITLE[t] ?? humanize(t);

const OPEN_TASK = new Set(["CREATED", "ASSIGNED", "ACCEPTED", "RUNNING", "RESULT_READY", "VALIDATED", "RETRY_PENDING", "TIMED_OUT", "BLOCKED"]);
const ERROR_TASK = new Set(["FAILED", "ESCALATED", "REJECTED", "TIMED_OUT", "BLOCKED"]);
export const ACTIVITY_LIMIT = 100;

// ── full rows of GET /desk/workflows/{id} (SELECT * of agent_tasks / agent_handoffs) ───────────────────────────────

export interface ToolCallRow {
  tool: string;
  args?: Record<string, unknown>;
  as_of?: string | null;
  ok?: boolean;
  rows?: number | null;
  error?: string | null;
  ms?: number | null;
}

export interface TaskFull extends AgentTaskRow {
  tenant_id?: string;
  account_id?: string | null;
  from_agent: string;
  to_agent: string;
  input_refs: string[] | null;
  constraints?: Record<string, unknown> | null;
  required_output_schema: string;
  max_attempts?: number;
  result: Record<string, unknown> | null;
  evidence_refs: string[] | null;
  tool_calls: ToolCallRow[] | null;
  validation: { schema_ok?: boolean; domain_ok?: boolean; errors?: string[] } | null;
  model: string | null;
  prompt_version: string | null;
}

export interface HandoffRow {
  handoff_id: string;
  workflow_id: string;
  simulation_id: string | null;
  from_task_id: string;
  to_task_id: string;
  from_agent: string;
  to_agent: string;
  entity_id: string | null;
  created_at: string;
}

export interface WorkflowDetail {
  workflow: WorkflowRow;
  tasks: TaskFull[];
  handoffs: HandoffRow[];
  children: Pick<WorkflowRow, "workflow_id" | "kind" | "state" | "outcome" | "created_at">[];
}

// ── queries ─────────────────────────────────────────────────────────────────────────────────────────────────────────

export function useAgentRegistry() {
  return useQuery({ queryKey: ["desk", "agents", "registry"], queryFn: () => deskGet<AgentRow[]>("/agents"), refetchInterval: 30_000 });
}

/** One agent's desk tasks, newest first (the API orders by created_at DESC). Also used by the scanner. */
export function activityQuery(key: AgentKey) {
  return {
    queryKey: ["desk", "agents", "activity", key] as const,
    queryFn: async () => (await deskGet<AgentTaskRow[]>(`/agents/${key}/activity`, { limit: ACTIVITY_LIMIT })).filter((t) => !t.simulation_id),
    refetchInterval: 30_000,
  };
}

export function useAllActivity() {
  return useQueries({ queries: AGENT_ORDER.map((k) => activityQuery(k)) });
}

export function workflowQuery(id: string | null | undefined, poll?: (d: WorkflowDetail | undefined) => number | false) {
  return {
    queryKey: ["desk", "workflow", id ?? ""] as const,
    queryFn: () => deskGet<WorkflowDetail>(`/desk/workflows/${encodeURIComponent(id ?? "")}`),
    enabled: !!id,
    ...(poll ? { refetchInterval: (q: { state: { data: WorkflowDetail | undefined } }) => poll(q.state.data) } : {}),
  };
}

export function useWorkflowDetail(id: string | null | undefined) {
  return useQuery(workflowQuery(id));
}

/** TRADE_PROPOSAL workflows of every desk account (the API's list ascends by created_at; the newest sort first here). */
export function useProposalWorkflows(accountIds: string[]) {
  const qs = useQueries({
    queries: accountIds.map((a) => ({
      queryKey: ["desk", "workflows", a, "TRADE_PROPOSAL"] as const,
      queryFn: () => deskGet<WorkflowRow[]>("/desk/workflows", { account_id: a, kind: "TRADE_PROPOSAL", limit: 500 }),
      refetchInterval: 30_000,
    })),
  });
  const error = qs.find((q) => q.error)?.error ?? null;
  const loading = qs.some((q) => q.isLoading);
  const rows = qs.flatMap((q) => q.data ?? []).filter((w) => !w.simulation_id);
  rows.sort((a, b) => (b.created_at > a.created_at ? 1 : b.created_at < a.created_at ? -1 : 0));
  return { rows, error, loading, refetch: () => qs.forEach((q) => q.refetch()) };
}

export function useDeskPlans() {
  return useQuery({ queryKey: ["desk", "plans", "all"], queryFn: () => deskGet<TradePlanRow[]>("/trade-plans", { limit: 500 }) });
}

export function useSignalsById(ids: string[]) {
  return useQueries({
    queries: ids.map((id) => ({
      queryKey: ["desk", "signal", id] as const,
      queryFn: () => deskGet<SignalRow>(`/signals/${encodeURIComponent(id)}`),
      staleTime: 5 * 60_000,
    })),
  });
}

// ── view model ──────────────────────────────────────────────────────────────────────────────────────────────────────

/** The latest registered version of each agent (the registry lists agent_key, registered_at DESC). */
export function currentAgents(rows: AgentRow[]): Map<AgentKey, AgentRow> {
  const m = new Map<AgentKey, AgentRow>();
  for (const r of rows) {
    const cur = m.get(r.agent_key);
    if (!cur || r.registered_at > cur.registered_at) m.set(r.agent_key, r);
  }
  return m;
}

export const isOpenTask = (t: AgentTaskRow): boolean => OPEN_TASK.has(t.state);

export interface CardStats {
  open: AgentTaskRow | null;
  last: AgentTaskRow | null;
  lastSuccess: AgentTaskRow | null;
  decisions: AgentTaskRow[];
  errors: number;
  retries: number;
  escalated: number;
  latestError: string | null;
  window: number;
}

export function cardStats(tasks: AgentTaskRow[]): CardStats {
  const open = tasks.find(isOpenTask) ?? null;
  const done = tasks.filter((t) => !isOpenTask(t));
  const errs = tasks.filter((t) => ERROR_TASK.has(t.state));
  return {
    open,
    last: done[0] ?? null,
    lastSuccess: tasks.find((t) => t.state === "COMPLETED") ?? null,
    decisions: tasks.filter((t) => t.result_summary || t.error).slice(0, 3),
    errors: errs.length,
    retries: tasks.reduce((n, t) => n + Math.max((t.attempt ?? 1) - 1, 0), 0),
    escalated: tasks.filter((t) => t.state === "ESCALATED").length,
    latestError: errs.find((t) => t.error)?.error ?? null,
    window: tasks.length,
  };
}

export const actorName = (a: string | null | undefined): string =>
  !a ? "—" : a === "ORCHESTRATOR" ? "Desk Orchestrator" : a.startsWith("user:") ? "A person" : agentName(a.split("@")[0]);

export type TraceTone = "ink" | "mint" | "amber" | "danger";
export interface TraceRow { k: string; v: string; tone: TraceTone }

function arr(v: unknown): unknown[] {
  return Array.isArray(v) ? v : [];
}

/** One line for an agent's structured output, from the task's stored result (an output schema of contracts.py). */
export function outputLine(schema: string, r: Record<string, unknown> | null): string {
  if (!r) return "—";
  switch (schema) {
    case "premarket-report-v1":
      return `PREMARKET REPORT · ${String(r.status ?? "—")} · segments ${arr(r.allowed_segments).join(", ") || "none"}`;
    case "scan-report-v1":
      return `SCAN REPORT · ${arr(r.signals).length} signals · ${String(r.universe_size ?? "—")} instruments · ${arr(r.suppressed).length} suppressed or skipped`;
    case "strategy-proposal-v1": {
      const plan = (r.plan && typeof r.plan === "object" ? r.plan : null) as Record<string, unknown> | null;
      if (r.decision === "PLAN" && plan) {
        return `PLAN · ${humanize(plan.strategy_type)} · ${String(plan.instrument ?? "—")} · max loss ${rs(plan.max_loss_rs, { decimals: 2 })}`;
      }
      return `NO_TRADE · ${arr(r.reasons).length} reason${arr(r.reasons).length === 1 ? "" : "s"}`;
    }
    case "risk-assessment-v1": {
      const v = arr(r.violations);
      return `RISK ASSESSMENT · ${String(r.verdict ?? "—")} · ${arr(r.checks).length} checks · ${v.length ? `failed ${v.join(", ")}` : "no failed check"}`;
    }
    case "approval-decision-v1": {
      const scope = (r.scope && typeof r.scope === "object" ? r.scope : null) as Record<string, unknown> | null;
      const h = typeof scope?.plan_hash === "string" ? scope.plan_hash : null;
      return `APPROVAL DECISION · ${String(r.status ?? "—")}${h ? ` · binds plan hash ${h.slice(0, 4)}…${h.slice(-4)}` : ""}`;
    }
    default:
      return schema;
  }
}

export function toolLine(calls: ToolCallRow[] | null | undefined): string {
  const c = calls ?? [];
  if (!c.length) return "None";
  const failed = c.filter((x) => x.ok === false).length;
  if (c.length <= 4) {
    return c.map((x) => `${x.tool}${x.ms != null ? ` ${(x.ms / 1000).toFixed(1)} s` : ""}${x.ok === false ? " (failed)" : ""}`).join(" · ");
  }
  const by = new Map<string, number>();
  for (const x of c) by.set(x.tool, (by.get(x.tool) ?? 0) + 1);
  const top = [...by.entries()].sort((a, b) => b[1] - a[1]).slice(0, 3).map(([t, n]) => `${t} ×${n}`);
  return `${c.length} calls${failed ? ` · ${failed} failed` : ""} · ${top.join(" · ")}${by.size > 3 ? ` · +${by.size - 3} more` : ""}`;
}

const DECISION_TONE: Record<string, TraceTone> = { COMPLETED: "mint", ESCALATED: "amber", BLOCKED: "amber", RETRY_PENDING: "amber", FAILED: "danger", REJECTED: "danger", TIMED_OUT: "danger", CANCELLED: "danger" };

/** The ten fields of the design's decision trace (PRD §32.4), from one task row and its workflow's handoffs. */
export function traceRows(task: TaskFull, wf: WorkflowRow, handoffs: HandoffRow[], secsFmt: (ms: unknown) => string): TraceRow[] {
  const inbound = handoffs.find((h) => h.to_task_id === task.task_id);
  const outbound = handoffs.find((h) => h.from_task_id === task.task_id);
  const v = task.validation;
  const valOk = !!v && v.schema_ok === true && v.domain_ok === true;
  return [
    { k: "Requesting", tone: "ink", v: inbound ? `${actorName(inbound.from_agent)} · handoff of ${shortId(inbound.entity_id)}` : `${actorName(task.from_agent)} · ${humanize(wf.kind)} ${shortId(wf.workflow_id)}` },
    { k: "Receiving", tone: "ink", v: outbound ? actorName(outbound.to_agent) : "Desk Orchestrator" },
    { k: "Input references", tone: "ink", v: (task.input_refs ?? []).join(" · ") || "—" },
    { k: "Structured output", tone: "ink", v: outputLine(task.required_output_schema, task.result) },
    { k: "Evidence", tone: "ink", v: (task.evidence_refs ?? []).join(" · ") || "—" },
    { k: "Tool calls", tone: "ink", v: toolLine(task.tool_calls) },
    {
      k: "Validation",
      tone: !v ? "ink" : valOk ? "mint" : "danger",
      v: !v ? "—" : `Schema ${v.schema_ok ? "✓" : "×"} · domain ${v.domain_ok ? "✓" : "×"}${v.errors?.length ? ` · ${v.errors.join("; ")}` : ""}`,
    },
    { k: "Time · retries", tone: "ink", v: `${secsFmt(task.latency_ms)} · ${Math.max((task.attempt ?? 1) - 1, 0)}` },
    { k: "Handoff", tone: "ink", v: outbound ? `${actorName(outbound.to_agent)} · ${shortId(outbound.entity_id)}` : "None recorded in this workflow" },
    { k: "Decision", tone: DECISION_TONE[task.state] ?? "ink", v: `${task.state}${task.result_summary ? ` · ${task.result_summary}` : task.error ? ` · ${task.error}` : ""}` },
  ];
}

/** What escalates to a person, per agent — as the Phase 1 code does it (orchestrator/engine.py, agents/*.py). */
export const ESCALATION: Record<AgentKey, string> = {
  AI_TRADER: "None for signals: a signal only feeds planning, and every plan goes through Risk & Operations and the Middle Office.",
  TRADING_ASSISTANT: "None directly: its plans go to Risk & Operations, never straight to approval. A plan that still fails risk after two revisions is dropped.",
  RISK_OPS: "A failed hard check can never become an approval, whoever asks. The plan is revised at most twice, then dropped.",
  MIDDLE_OFFICE: "On an assisted account a person approves every plan. On an autonomous paper account, plans outside the policy's autonomy rules go to a person.",
  TECH_SUPPORT: "A blocked pre-market check ends the session cycle: no plan is proposed that session.",
};

// ── workflows in flight: the 13-step proposal workflow of the PRD (§7.1) ────────────────────────────────────────────

export const STEPS = ["Signal", "Proposal", "Risk report", "Revision", "Authorization", "Capital reservation", "Execution intent",
  "Orders and fills", "Active position", "Risk events", "Position action", "Reconciliation", "Journal"];
export const PHASE1_STEPS = 5;

export interface FlowView { done: number; cur: number | null; color: string; label: string; revised: boolean }

const IN_FLIGHT = new Set(["CREATED", "RUNNING", "WAITING_HUMAN"]);
export const isInFlight = (w: WorkflowRow): boolean => IN_FLIGHT.has(w.state);

const RUNNING_STEP: Record<string, number> = { GENERATE_STRATEGY: 1, ASSESS_RISK: 2, REVISE_STRATEGY: 3, REVIEW_FOR_APPROVAL: 4 };

/** Where a TRADE_PROPOSAL workflow stands, from its state + outcome (and, while it runs, its latest task). */
export function flowView(w: WorkflowRow, tasks?: TaskFull[]): FlowView {
  const o = (w.outcome ?? {}) as Record<string, unknown>;
  const result = typeof o.result === "string" ? o.result : null;
  const revised = Number(o.plan_version ?? 1) > 1 || !!tasks?.some((t) => t.task_type === "REVISE_STRATEGY");
  const at = (i: number, color: string, label: string): FlowView => ({ done: i, cur: i, color, label, revised });
  if (w.state === "WAITING_HUMAN") return at(4, "var(--amber)", "Step 5 · waiting on you");
  if (w.state === "CREATED") return at(1, "var(--indigo)", "Step 2 · starting");
  if (w.state === "RUNNING") {
    const latest = [...(tasks ?? [])].sort((a, b) => (a.created_at < b.created_at ? 1 : -1))[0];
    const i = latest ? RUNNING_STEP[latest.task_type] ?? 1 : 1;
    const who = latest ? actorName(latest.to_agent) : "Trading Assistant";
    return at(i, "var(--mint)", `Step ${i + 1} · ${who} ${latest && latest.state !== "COMPLETED" ? "working" : "next"}`);
  }
  if (w.state === "FAILED") {
    const why = String(w.error ?? o.reason ?? "");
    const i = why.startsWith("risk") ? 2 : why.startsWith("revision") ? 3 : why.startsWith("approval") ? 4 : 1;
    return at(i, "var(--danger)", `Step ${i + 1} · failed`);
  }
  switch (result) {
    case "APPROVED_NO_EXECUTION":
      return { done: PHASE1_STEPS, cur: null, color: "var(--mint)", label: "Approved · Phase 1 ends at step 5", revised };
    case "APPROVED":
      return { done: PHASE1_STEPS, cur: null, color: "var(--mint)", label: "Approved · handed to paper execution", revised };
    case "NO_TRADE": {
      const i = o.stage === "risk" ? 2 : o.stage === "revision" ? 3 : 1;
      return at(i, "var(--ink-3)", `Step ${i + 1} · no plan (${result})`);
    }
    case "RESEARCH_ONLY":
      return at(4, "var(--ink-3)", "Step 5 · research only, not authorized");
    case "ENTRIES_STOPPED":
      return at(4, "var(--danger)", "Step 5 · held back by Stop new entries");
    case "REJECTED":
    case "REJECTED_BY_PERSON":
    case "SUSPENDED":
      return at(4, "var(--danger)", `Step 5 · ${humanize(result).toLowerCase()}`);
    case "NEEDS_REVISION":
    case "REVISION_REQUESTED":
      return at(4, "var(--amber)", "Step 5 · revision requested");
    case "EXPIRED":
      return at(4, "var(--ink-3)", "Step 5 · expired at the session close");
    default:
      return at(1, "var(--ink-3)", `${humanize(w.state)}${result ? ` · ${result}` : ""}`);
  }
}
