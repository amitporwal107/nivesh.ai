/**
 * Simulator — shapes of the simulation API (backend/autodesk/routers/api.py + simulator/manager.py) beyond ../../types,
 * and pure helpers that turn events / results into what the design shows. Agent-written text (task summaries, errors,
 * reasons) is passed through as written.
 */
import { DASH, dateShort, humanize, num, rs } from "../../format";
import type { EventRow, SimulationRow, WorkflowRow } from "../../types";

/** One simulated session walks this schedule (contracts.CLOCK_SCHEDULE_IST): PREMARKET 08:30 … EOD 18:00. */
export const PHASES_PER_SESSION = 6;

export interface AgentResult { tasks: number; completed: number; failed: number; escalated: number; rejected: number; retried: number; avg_latency_ms: number | null }

/** GET /simulations/{sid}/results (SimulationManager.results). */
export interface SimResults {
  simulation_id: string;
  status: string;
  mode: string;
  sessions_total: number;
  phases_run: number;
  premarket: Record<string, number>;
  signals: { total: number; by_category: Record<string, number>; by_status: Record<string, number>; by_segment: Record<string, number> };
  plans: { total: number; by_status: Record<string, number>; by_strategy: Record<string, number> };
  approvals: { by_status: Record<string, number>; by_decider: Record<string, number> };
  agents: Record<string, AgentResult>;
  handoffs: number;
  policy_violation_attempts: number;
  versions: SimVersions | null;
  data: { first_session: string | null; last_session: string | null; universe: string | null; symbols: string[] | null };
  limitations: string[];
  execution: string;
}

export interface SimVersions {
  app?: string;
  agents?: Record<string, string>;
  market_view?: string;
  risk_engine?: string;
  scan_rules?: string;
  policy?: { policy_id: string; version: number; sha256: string };
  [k: string]: unknown;
}

/** GET /simulations/{sid}/agents. */
export interface SimAgents { simulation_id: string; versions: SimVersions | null; agents: Record<string, { tasks: number; by_state: Record<string, number> }> }

/** Rows of autodesk.simulation_clock_events. */
export interface ClockEventRow { simulation_id: string; seq: number; session_date: string; phase: string; sim_time: string; wall_time: string; workflows: string[] }

export interface TimelinePage { clock: ClockEventRow[]; events: EventRow[] }

/** GET /desk/workflows/{id}. */
export interface WorkflowDetail {
  workflow: WorkflowRow;
  tasks: { task_id: string; task_type: string; step: string | null; state: string; entity_id: string | null; result_summary: string | null; error: string | null; created_at: string }[];
  handoffs: { from_agent: string; to_agent: string; entity_id: string | null; created_at: string }[];
  children: unknown[];
}

export interface SimConfig {
  name?: string;
  description?: string;
  mode?: string;
  start_date?: string;
  end_date?: string;
  universe?: string;
  starting_capital_rs?: string | number;
  operating_mode?: string;
  max_proposals_per_session?: number;
  symbols?: string[] | null;
  seed?: number;
  speed?: string;
  sessions?: string[];
  [k: string]: unknown;
}

export const configOf = (s: SimulationRow | undefined): SimConfig => (s?.config ?? {}) as SimConfig;

export function sessionsOf(s: SimulationRow | undefined): string[] {
  const c = configOf(s);
  if (Array.isArray(c.sessions) && c.sessions.length) return c.sessions;
  return [c.start_date, c.end_date].filter((x): x is string => typeof x === "string");
}

export function rangeText(s: SimulationRow | undefined): string {
  const ss = sessionsOf(s);
  if (!ss.length) return DASH;
  const a = ss[0];
  const b = ss[ss.length - 1];
  return a === b ? dateShort(a) : `${dateShort(a)} – ${dateShort(b)}`;
}

// ── who's who ───────────────────────────────────────────────────────────────────────────────────────────────────────

export const AGENT_ORDER = ["AI_TRADER", "TRADING_ASSISTANT", "RISK_OPS", "MIDDLE_OFFICE", "TECH_SUPPORT"] as const;

const WHO: Record<string, string> = {
  AI_TRADER: "AI Trader",
  TRADING_ASSISTANT: "Trading Assistant",
  RISK_OPS: "Risk & Operations",
  MIDDLE_OFFICE: "Middle Office",
  TECH_SUPPORT: "Tech Support",
  ORCHESTRATOR: "Orchestrator",
  SIMULATION_CLOCK: "Sim clock",
  SESSION_CLOSE: "Session close",
};

export function who(p: unknown): string {
  if (typeof p !== "string" || !p) return DASH;
  const key = p.split("@")[0];
  if (WHO[key]) return WHO[key];
  if (key.startsWith("user:")) return "Person";
  if (key.startsWith("SYSTEM:")) return humanize(key.slice(7));
  return humanize(key);
}

// ── events ──────────────────────────────────────────────────────────────────────────────────────────────────────────

export type Tone = "mint" | "amber" | "danger" | "indigo" | "ink";
export const TONE_COLOR: Record<Tone, string> = { mint: "var(--mint)", amber: "var(--amber)", danger: "var(--danger)", indigo: "var(--indigo)", ink: "var(--ink-2)" };

const TASK_SHOWN = new Set(["COMPLETED", "FAILED", "REJECTED", "ESCALATED", "RETRY_PENDING", "TIMED_OUT", "BLOCKED", "CANCELLED"]);
const TASK_EXC = new Set(["FAILED", "REJECTED", "ESCALATED", "RETRY_PENDING", "TIMED_OUT", "BLOCKED"]);
const HIDDEN = new Set(["TASK_CREATED", "WORKFLOW_STARTED", "WORKFLOW_STATE_CHANGED"]);

const P = (e: EventRow) => (e.payload ?? {}) as Record<string, unknown>;
const s = (v: unknown) => (v == null ? "" : String(v));

/** Shown in "Agent communication": domain events, handoffs and the end state of each agent task (not every hop). */
export function isShown(e: EventRow): boolean {
  if (HIDDEN.has(e.event_type)) return false;
  if (e.event_type === "TASK_STATE_CHANGED") return TASK_SHOWN.has(s(P(e).to));
  return true;
}

export function isException(e: EventRow): boolean {
  const p = P(e);
  if (e.event_type === "TASK_STATE_CHANGED") return TASK_EXC.has(s(p.to)) || (!!p.error && s(p.to) !== "COMPLETED");
  if (e.event_type === "SIMULATION_STATE_CHANGED") return s(p.to) === "FAILED";
  return e.event_type === "WORKFLOW_FAILED" || e.event_type === "PREMARKET_BLOCKED" || e.event_type === "MARKET_DATA_STALE";
}

function toneOf(status: string): Tone {
  if (["APPROVED", "PASS", "COMPLETED", "READY"].includes(status)) return "mint";
  if (["REJECTED", "FAIL", "FAILED", "BLOCKED", "SUSPENDED"].includes(status)) return "danger";
  if (["NEEDS_HUMAN_APPROVAL", "NEEDS_REVISION", "REDUCE", "RETRY_PENDING", "ESCALATED", "TIMED_OUT", "DEGRADED"].includes(status)) return "amber";
  return "ink";
}

export interface Described { route: string; type: string; text: string; tone: Tone }

export function describe(e: EventRow): Described {
  const p = P(e);
  const from = who(e.producer);
  const reasons = Array.isArray(p.reasons) ? (p.reasons as unknown[]).map(String).join("; ") : "";
  switch (e.event_type) {
    case "HANDOFF_RECORDED":
      return { route: `${who(p.from_agent)} → ${who(p.to_agent)}`, type: "HANDOFF", text: s(p.entity_id), tone: "mint" };
    case "TASK_STATE_CHANGED":
      return { route: `${who(p.agent)} → ${who(e.producer === p.agent ? "ORCHESTRATOR" : e.producer)}`, type: `${s(p.task_type).replace(/_/g, " ")} · ${s(p.to)}`, text: s(p.summary) || s(p.error) || `${s(p.from)} → ${s(p.to)}`, tone: toneOf(s(p.to)) };
    case "SIGNAL_DETECTED":
      return { route: from, type: "SIGNAL", text: `${s(p.signal_id)} · ${s(p.instrument)} ${s(p.direction).toLowerCase()} · ${humanize(p.category)} · score ${num(p.signal_score) ?? s(p.signal_score)}`, tone: "mint" };
    case "SIGNAL_SUPPRESSED":
    case "SIGNAL_EXPIRED":
      return { route: from, type: e.event_type.replace("SIGNAL_", "SIGNAL "), text: [p.signal_id, p.reason].filter(Boolean).map(String).join(" · "), tone: "ink" };
    case "TRADE_PLAN_CREATED":
      return { route: from, type: "PLAN", text: `${s(p.trade_id)} v${s(p.version)} · ${s(p.instrument)} · ${humanize(p.strategy_type)} · max loss ${rs(p.max_loss_rs, { decimals: 2 })}`, tone: "mint" };
    case "TRADE_PLAN_REVISED":
      return { route: from, type: "PLAN REVISED", text: `${s(p.trade_id)} v${s(p.version)}${p.reason ? ` · ${s(p.reason)}` : ""}`, tone: "amber" };
    case "RISK_ASSESSMENT_COMPLETED": {
      const v = Array.isArray(p.violations) && p.violations.length ? ` · ${(p.violations as unknown[]).join(", ")}` : "";
      return { route: from, type: `RISK ${s(p.verdict)}`, text: `${s(p.assessment_id)} · ${s(p.trade_id)} v${s(p.plan_version)}${v}`, tone: toneOf(s(p.verdict)) };
    }
    case "APPROVAL_REQUESTED":
      return { route: from, type: "APPROVAL REQUESTED", text: `${s(p.trade_id)} v${s(p.plan_version)}`, tone: "ink" };
    case "APPROVAL_GRANTED":
    case "APPROVAL_REJECTED":
    case "APPROVAL_NEEDS_HUMAN":
    case "APPROVAL_EXPIRED":
      return { route: who(p.decided_by ?? e.producer), type: e.event_type === "APPROVAL_EXPIRED" ? "APPROVAL EXPIRED" : s(p.status).replace(/_/g, " "), text: `${s(p.approval_id)} · ${s(p.trade_id)} v${s(p.plan_version)}${reasons ? ` · ${reasons}` : ""}`, tone: e.event_type === "APPROVAL_EXPIRED" ? "ink" : toneOf(s(p.status)) };
    case "CLOCK_ADVANCED":
      return { route: "Sim clock", type: "CLOCK", text: `Step ${s(p.seq)} · ${dateShort(p.session_date)} · ${s(p.phase)}`, tone: "indigo" };
    case "PREMARKET_READY":
    case "PREMARKET_BLOCKED":
      return { route: from, type: e.event_type === "PREMARKET_READY" ? "PRE-MARKET READY" : "PRE-MARKET BLOCKED", text: `${dateShort(p.session_date)} · ${s(p.status)}${Array.isArray(p.allowed_segments) ? ` · segments ${(p.allowed_segments as unknown[]).join(", ") || "none"}` : ""}`, tone: e.event_type === "PREMARKET_READY" ? "mint" : "danger" };
    case "SIMULATION_CREATED":
      return { route: from, type: "CREATED", text: `${s(p.name)} · ${s(p.start_date)} → ${s(p.end_date)}`, tone: "indigo" };
    case "SIMULATION_STATE_CHANGED":
      return { route: from, type: "STATE", text: `${s(p.from)} → ${s(p.to)}${p.error ? ` · ${s(p.error)}` : ""}`, tone: s(p.to) === "FAILED" ? "danger" : "indigo" };
    case "WORKFLOW_FAILED":
      return { route: from, type: "WORKFLOW FAILED", text: s(p.error) || s(p.reason), tone: "danger" };
    case "MARKET_DATA_STALE":
      return { route: from, type: "DATA STALE", text: s(p.detail) || s(p.reason), tone: "amber" };
    default:
      return { route: from, type: e.event_type.replace(/_/g, " "), text: "", tone: "ink" };
  }
}

/** Time of an event in simulated time: its own sim_time, else the clock step it ran in (the next CLOCK_ADVANCED). */
export function simTimeOf(e: EventRow, clockSeqs: { seq: number; sim_time: string }[]): string | null {
  if (e.sim_time) return e.sim_time;
  const c = clockSeqs.find((x) => x.seq > e.seq);
  return c ? c.sim_time : null;
}

// ── incremental timeline state ──────────────────────────────────────────────────────────────────────────────────────

export interface ExceptionItem { key: string; at: string | null; seq: number; n: string; r: string; st: string; taskId?: string }

export interface TimelineState {
  clock: ClockEventRow[];
  shown: EventRow[];                 // display events, oldest first, newest kept (cap)
  clockSeqs: { seq: number; sim_time: string }[];
  exceptions: ExceptionItem[];
  completedTasks: string[];
  latestByAgent: Record<string, string>;
  lastSeq: number;
  total: number;
}

export const SHOWN_CAP = 300;

export const emptyTimeline = (): TimelineState => ({ clock: [], shown: [], clockSeqs: [], exceptions: [], completedTasks: [], latestByAgent: {}, lastSeq: 0, total: 0 });

export function mergeEvents(prev: TimelineState, events: EventRow[]): TimelineState {
  const st: TimelineState = { ...prev, shown: [...prev.shown], clockSeqs: [...prev.clockSeqs], exceptions: [...prev.exceptions], completedTasks: [...prev.completedTasks], latestByAgent: { ...prev.latestByAgent } };
  const done = new Set(st.completedTasks);
  for (const e of events) {
    if (e.seq <= st.lastSeq) continue;
    st.lastSeq = e.seq;
    st.total += 1;
    const p = P(e);
    if (e.event_type === "CLOCK_ADVANCED" && e.sim_time) st.clockSeqs.push({ seq: e.seq, sim_time: e.sim_time });
    if (e.event_type === "TASK_STATE_CHANGED") {
      if (s(p.to) === "COMPLETED") done.add(s(p.task_id));
      if (p.summary && typeof p.agent === "string") st.latestByAgent[p.agent] = s(p.summary);
    }
    if (isException(e)) {
      const d = describe(e);
      const taskId = e.event_type === "TASK_STATE_CHANGED" ? s(p.task_id) : undefined;
      const item: ExceptionItem = {
        key: taskId ? `task:${taskId}` : `ev:${e.seq}`, at: e.sim_time, seq: e.seq,
        n: e.event_type === "TASK_STATE_CHANGED" ? `${who(p.agent)} · ${humanize(p.task_type)}` : d.type.charAt(0) + d.type.slice(1).toLowerCase(),
        r: e.event_type === "TASK_STATE_CHANGED" ? s(p.error) || s(p.summary) || `${s(p.from)} → ${s(p.to)}` : d.text,
        st: e.event_type === "TASK_STATE_CHANGED" ? s(p.to) : e.event_type.replace(/_/g, " "),
        taskId,
      };
      const i = st.exceptions.findIndex((x) => x.key === item.key);
      if (i >= 0) st.exceptions[i] = item;
      else st.exceptions.push(item);
    }
    if (isShown(e)) st.shown.push(e);
  }
  if (st.shown.length > SHOWN_CAP) st.shown = st.shown.slice(-SHOWN_CAP);
  if (st.exceptions.length > 200) st.exceptions = st.exceptions.slice(-200);
  st.completedTasks = Array.from(done);
  return st;
}

// ── dependency graph (13 nodes of the design; the first five are drawn, the rest are recorded but not drawn yet) ────────────────────────────────────────

export const GRAPH_NODES = ["Signal", "Proposal", "Risk report", "Revision", "Authorization", "Reservation", "Execution intent", "Orders and fills", "Active position", "Risk events", "Position action", "Reconciliation", "Journal"];

export interface GraphNode { n: string; t: string; st: string; tone: Tone | "phase2" }

function taskNode(tasks: WorkflowDetail["tasks"], step: string, wfDone: boolean): { st: string; tone: Tone } {
  const ts = tasks.filter((t) => t.step === step);
  const last = ts[ts.length - 1];
  if (!last) return wfDone ? { st: "NOT RUN", tone: "ink" } : { st: "WAITING", tone: "ink" };
  if (last.state === "COMPLETED") return { st: ts.length > 1 ? `DONE ×${ts.length}` : "DONE", tone: "mint" };
  if (["FAILED", "REJECTED", "CANCELLED"].includes(last.state)) return { st: last.state, tone: "danger" };
  if (["ESCALATED", "TIMED_OUT", "BLOCKED", "RETRY_PENDING"].includes(last.state)) return { st: last.state, tone: "amber" };
  return { st: "ACTIVE", tone: "indigo" };
}

export function graphNodes(d: WorkflowDetail | undefined): GraphNode[] {
  const wf = d?.workflow;
  const tasks = d?.tasks ?? [];
  const wfDone = !!wf && ["COMPLETED", "FAILED", "CANCELLED", "BLOCKED"].includes(wf.state);
  const out = (wf?.outcome ?? {}) as Record<string, unknown>;
  const result = s(out.result);
  const auth: { st: string; tone: Tone } = wf?.state === "WAITING_HUMAN" ? { st: "WAITING ON A PERSON", tone: "amber" }
    : result === "APPROVED_NO_EXECUTION" || result === "APPROVED" ? { st: "APPROVED", tone: "mint" }
    : result && ["REJECTED", "NEEDS_REVISION", "SUSPENDED", "REJECTED_BY_PERSON", "REVISION_REQUESTED", "EXPIRED", "ENTRIES_STOPPED", "FAILED"].includes(result) ? { st: result.replace(/_/g, " "), tone: result === "NEEDS_REVISION" || result === "REVISION_REQUESTED" ? "amber" : "danger" }
    : taskNode(tasks, "approval", wfDone);
  const sig = (wf?.input as Record<string, unknown> | undefined)?.signal_id;
  const rev = tasks.some((t) => t.step === "revise") ? taskNode(tasks, "revise", wfDone)
    : tasks.some((t) => t.step === "approval") || wfDone ? { st: "NOT NEEDED", tone: "ink" as Tone } : { st: "WAITING", tone: "ink" as Tone };
  const first: { st: string; tone: Tone }[] = [
    sig ? { st: "DONE", tone: "mint" } : { st: "—", tone: "ink" },
    taskNode(tasks, "plan", wfDone),
    taskNode(tasks, "risk", wfDone),
    rev,
    auth,
  ];
  return GRAPH_NODES.map((t, i) => ({
    n: String(i + 1).padStart(2, "0"),
    t,
    st: i < 5 ? first[i].st : "NOT SHOWN YET",
    tone: i < 5 ? first[i].tone : "phase2",
  }));
}

/** "Bull call spread 3 · Bear put spread 3" from a {KEY: n} map. */
export function countsText(m: Record<string, number> | undefined, lower = false): string {
  const e = Object.entries(m ?? {}).filter(([, v]) => v);
  if (!e.length) return DASH;
  return e.map(([k, v]) => `${lower ? humanize(k).toLowerCase() : humanize(k)} ${v}`).join(" · ");
}

export const sum = (m: Record<string, number> | undefined): number => Object.values(m ?? {}).reduce((a, b) => a + (b || 0), 0);

// ── form defaults ───────────────────────────────────────────────────────────────────────────────────────────────────

function shift(iso: string, days: number): string {
  const d = new Date(`${iso}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + days);
  return d.toISOString().slice(0, 10);
}

/** The weekday before `iso` (holidays are the API's to skip; it refuses a range with no session). */
export function previousWeekday(iso: string): string {
  let d = shift(iso, -1);
  for (let i = 0; i < 3; i++) {
    const wd = new Date(`${d}T00:00:00Z`).getUTCDay();
    if (wd !== 0 && wd !== 6) break;
    d = shift(d, -1);
  }
  return d;
}
