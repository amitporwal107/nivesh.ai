/**
 * Agent trace — one TRADE_PROPOSAL workflow of a run replayed as the messages the agents handed on.
 *
 * Source: GET /desk/workflows/{id} (workflow + full autodesk.agent_tasks rows + autodesk.agent_handoffs rows; types in
 * screens/agents/model). Step 1 is the AI Trader's handoff of the signal to the Trading Assistant (the inbound handoff
 * from the scan task of the session cycle, with the signal row); then one step per agent task in created order. Each step
 * carries the task's real fields: who → whom (the task's agent → the receiver of its outbound handoff, else the
 * orchestrator), input refs, structured output (`result`), `result_summary` / `error` as the agent wrote them, tool calls
 * with timings, validation, state, attempt, latency, sim time.
 */
import { DASH, dateShort, dateTimeIST, humanize, num, rs, timeIST } from "../../../format";
import { actorName, type HandoffRow, type TaskFull, type WorkflowDetail } from "../../../screens/agents/model";
import { secs, shortId } from "../../../screens/scanner/fmt";
import { SHADOW_LABEL, chipText, shadowScoresOf } from "../../../screens/scanner/shadow";
import type { SignalRow, TradePlanRow, WorkflowRow } from "../../../types";

export type TraceTask = TaskFull & { sim_time?: string | null };

export interface ToolLine { n: string; r: string; ms: string; ok: boolean }

export interface Step {
  key: string;
  fromKey: string;
  from: string;
  to: string;
  type: string;
  x: string;
  t: string;
  ms: string;
  verdict: string;
  tone: "mint" | "amber" | "danger" | "indigo";
  payload: [string, string][];
  tools: ToolLine[];
  moreTools: number;
  toolsNote: string | null;
  meta: [string, string][];
}

export const AGENT_COLOR: Record<string, string> = {
  AI_TRADER: "var(--mint)", TRADING_ASSISTANT: "var(--mint)", RISK_OPS: "var(--indigo)", MIDDLE_OFFICE: "var(--ink-2)",
  TECH_SUPPORT: "var(--amber)", ORCHESTRATOR: "var(--ink-2)",
};
export const colorOf = (key: string): string => AGENT_COLOR[key.split("@")[0]] ?? "var(--ink-2)";

/** Initials for the avatar: letters of the words of the name ("Risk & Operations" → "RO"). */
export const initials = (name: string): string => name.split(/\s+/).filter((w) => /^[A-Za-z]/.test(w)).map((w) => w[0]).join("").slice(0, 2).toUpperCase();

const s = (v: unknown): string => (v == null ? "" : String(v));
const obj = (v: unknown): Record<string, unknown> | null => (v && typeof v === "object" && !Array.isArray(v) ? (v as Record<string, unknown>) : null);
const arr = (v: unknown): unknown[] => (Array.isArray(v) ? v : []);

function fmtVal(k: string, v: unknown): string {
  if (v == null || v === "") return DASH;
  if (k.endsWith("_rs") && num(v) != null) return rs(v, { decimals: 2 });
  if (Array.isArray(v)) return v.length ? v.map((x) => (typeof x === "object" ? JSON.stringify(x) : String(x))).join(" · ") : "none";
  if (typeof v === "object") return JSON.stringify(v);
  if (typeof v === "string" && /^\d{4}-\d{2}-\d{2}T/.test(v)) return dateTimeIST(v);
  return String(v);
}

function legLine(l: Record<string, unknown>): string {
  const what = s(l.tradingsymbol) || [s(l.underlying), s(l.expiry), s(l.strike), s(l.kind)].filter(Boolean).join(" ");
  const lots = num(l.lots);
  return `${s(l.side)} ${lots != null ? `${lots}×${s(l.lot_size)}` : s(l.quantity)} ${what}${l.ref_price != null ? ` @ ${s(l.ref_price)}` : ""}`.trim();
}

/** The structured output of a task, as rows of the schema's own field names. */
export function payloadRows(schema: string, r: Record<string, unknown> | null): [string, string][] {
  if (!r) return [];
  const out: [string, string][] = [];
  const add = (k: string, v: unknown) => { if (v !== undefined) out.push([k, fmtVal(k, v)]); };
  switch (schema) {
    case "strategy-proposal-v1": {
      add("decision", r.decision);
      const p = obj(r.plan);
      if (p) {
        add("instrument", p.segment ? `${s(p.instrument)} · ${s(p.segment)}` : p.instrument);
        add("strategy_type", humanize(p.strategy_type));
        const legs = arr(p.legs).map((l) => legLine(obj(l) ?? {}));
        if (legs.length) out.push(["legs", legs.join(" · ")]);
        add("max_loss_rs", p.max_loss_rs);
        if (p.max_profit_rs !== undefined) add("max_profit_rs", p.max_profit_rs);
        if (p.capital_required_rs !== undefined) add("capital_required_rs", p.capital_required_rs);
      }
      if (arr(r.reasons).length) add("reasons", arr(r.reasons).map(String).join("; "));
      if (arr(r.alternatives).length) out.push(["alternatives", `${arr(r.alternatives).length} considered`]);
      return out;
    }
    case "risk-assessment-v1": {
      add("verdict", r.verdict);
      const checks = arr(r.checks).map((c) => obj(c) ?? {});
      if (checks.length) {
        const n = (o: string) => checks.filter((c) => c.outcome === o).length;
        out.push(["checks", `${checks.length} · ${n("PASS")} pass · ${n("WARN")} warn · ${n("FAIL")} fail${n("SKIPPED") ? ` · ${n("SKIPPED")} skipped` : ""}`]);
      }
      out.push(["violations", arr(r.violations).length ? arr(r.violations).map(String).join(", ") : "none"]);
      if (arr(r.warnings).length) add("warnings", arr(r.warnings).map(String).join("; "));
      const sz = obj(r.sizing);
      if (sz) out.push(["sizing", Object.entries(sz).filter(([, v]) => v == null || typeof v !== "object").map(([k, v]) => `${k} ${fmtVal(k, v)}`).join(" · ") || DASH]);
      if (r.policy_id) out.push(["policy", `${shortId(s(r.policy_id))}${r.policy_version != null ? ` v${s(r.policy_version)}` : ""}`]);
      if (r.engine_version) add("engine_version", r.engine_version);
      return out;
    }
    case "approval-decision-v1": {
      add("status", r.status);
      if (r.decided_by) add("decided_by", r.decided_by);
      out.push(["reasons", arr(r.reasons).length ? arr(r.reasons).map(String).join("; ") : "none"]);
      const sc = obj(r.scope);
      if (sc) {
        if (sc.max_lots != null) add("max_lots", sc.max_lots);
        if (sc.max_risk_rs != null) add("max_risk_rs", sc.max_risk_rs);
        if (typeof sc.plan_hash === "string") out.push(["plan_hash", `${sc.plan_hash.slice(0, 4)}…${sc.plan_hash.slice(-4)}`]);
      }
      if (r.expires_at) add("expires_at", r.expires_at);
      return out;
    }
    default:
      for (const [k, v] of Object.entries(r)) {
        if (out.length >= 8) break;
        if (v == null || typeof v !== "object") add(k, v);
        else if (Array.isArray(v)) out.push([k, `${v.length} item${v.length === 1 ? "" : "s"}`]);
      }
      return out;
  }
}

const TONE_OF: Record<string, Step["tone"]> = {
  PASS: "mint", PLAN: "mint", APPROVED: "mint", COMPLETED: "mint", SIGNAL: "mint", PUBLISHED: "mint",
  REDUCE: "amber", NO_TRADE: "amber", NEEDS_HUMAN_APPROVAL: "amber", NEEDS_REVISION: "amber", RETRY_PENDING: "amber", ESCALATED: "amber", BLOCKED: "amber", SUSPENDED: "amber",
  FAIL: "danger", FAILED: "danger", REJECTED: "danger", TIMED_OUT: "danger", CANCELLED: "danger",
};
export const toneOf = (v: string): Step["tone"] => TONE_OF[v] ?? "indigo";
export const TONE_VAR: Record<Step["tone"], [string, string]> = {
  mint: ["var(--mint)", "var(--mint-line)"], amber: ["var(--amber)", "var(--amber-line)"], danger: ["var(--danger)", "var(--danger-line)"], indigo: ["var(--indigo)", "var(--indigo-line)"],
};

function typeAndVerdict(t: TraceTask): [string, string] {
  const r = t.result;
  if (t.state !== "COMPLETED" || !r) return [t.task_type.replace(/_/g, " "), t.state];
  switch (t.task_type) {
    case "GENERATE_STRATEGY":
    case "REVISE_STRATEGY": {
      const d = s(r.decision);
      if (d === "NO_TRADE") return ["NO TRADE", "NO_TRADE"];
      return [t.task_type === "REVISE_STRATEGY" ? "PLAN REVISED" : "PLAN", d || "PLAN"];
    }
    case "ASSESS_RISK":
      return [`RISK ${s(r.verdict)}`.trim(), s(r.verdict) || t.state];
    case "REVIEW_FOR_APPROVAL": {
      const st = s(r.status);
      return [st === "NEEDS_HUMAN_APPROVAL" ? "NEEDS HUMAN" : st.replace(/_/g, " ") || "DECISION", st || t.state];
    }
    default:
      return [t.task_type.replace(/_/g, " "), t.state];
  }
}

function validationText(v: TraceTask["validation"]): string {
  if (!v) return DASH;
  return `Schema ${v.schema_ok ? "✓" : "×"} · domain ${v.domain_ok ? "✓" : "×"}${v.errors?.length ? ` · ${v.errors.join("; ")}` : ""}`;
}

const TOOL_CAP = 10;

/** The chain of one workflow as replayable steps (signal handoff first, then each task). */
export function buildSteps(d: WorkflowDetail, signal: SignalRow | null | undefined): Step[] {
  const tasks = [...(d.tasks as TraceTask[])].sort((a, b) => (a.created_at < b.created_at ? -1 : a.created_at > b.created_at ? 1 : 0));
  const ids = new Set(tasks.map((t) => t.task_id));
  const hs: HandoffRow[] = d.handoffs ?? [];
  const steps: Step[] = [];
  const wfTime = d.workflow.sim_time ?? d.workflow.created_at;

  // inbound handoffs from outside this workflow (the AI Trader's scan task of the session cycle)
  for (const h of hs.filter((x) => !ids.has(x.from_task_id))) {
    const sig = signal && signal.signal_id === h.entity_id ? signal : null;
    const score = sig ? num(sig.signal_score) : null;
    steps.push({
      key: h.handoff_id, fromKey: h.from_agent, from: actorName(h.from_agent), to: actorName(h.to_agent),
      type: h.from_agent === "AI_TRADER" ? "SIGNAL" : "HANDOFF",
      x: sig ? `${shortId(sig.signal_id)} · ${sig.instrument} · ${humanize(sig.category)} · score ${score ?? s(sig.signal_score)}` : `${shortId(h.entity_id)} handed on`,
      t: timeIST(wfTime), ms: DASH, verdict: sig ? sig.status : "HANDED ON", tone: "mint",
      payload: sig ? [
        ["signal_id", sig.signal_id], ["instrument", `${sig.instrument} · ${sig.exchange} ${sig.segment}`], ["direction", `${sig.direction} · ${sig.timeframe}`],
        ["category", sig.category], ["signal_score", s(sig.signal_score)], ["calibrated_probability", sig.calibrated_probability == null ? "not calibrated" : s(sig.calibrated_probability)],
        ["session_date", sig.session_date], ["data_as_of", dateTimeIST(sig.data_as_of)], ["rule_version", sig.rule_version],
        ...shadowScoresOf(sig).map((sh): [string, string] => [`shadow ${sh.version} · ${SHADOW_LABEL}`, `${chipText(sh)}${sh.tier ? ` · ${sh.tier}` : ""}${sh.primary_signal ? ` · primary ${sh.primary_signal}` : ""}`]),
      ] : [["entity_id", s(h.entity_id) || DASH]],
      tools: [], moreTools: 0, toolsNote: "The scan's tool calls belong to the market-scan workflow of the session.",
      meta: [["Produced by", `${actorName(h.from_agent)} · market scan`], ["Handoff", `${actorName(h.to_agent)} · ${shortId(h.entity_id)}`]],
    });
  }

  for (const t of tasks) {
    const out = hs.find((h) => h.from_task_id === t.task_id);
    const [type, verdict] = typeAndVerdict(t);
    const calls = t.tool_calls ?? [];
    const retries = Math.max((t.attempt ?? 1) - 1, 0);
    const meta: [string, string][] = [
      ["Inputs", (t.input_refs ?? []).join(" · ") || DASH],
      ["Validation", validationText(t.validation)],
      ["State · retries", `${t.state} · ${retries}`],
      ["Handoff", out ? `${actorName(out.to_agent)} · ${shortId(out.entity_id)}` : "None — the chain ends here"],
    ];
    if (t.error) meta.push(["Error", t.error]);
    if (t.agent_version) meta.push(["Agent version", t.agent_version]);
    steps.push({
      key: t.task_id, fromKey: t.to_agent, from: actorName(t.to_agent), to: out ? actorName(out.to_agent) : actorName("ORCHESTRATOR"),
      type, x: t.result_summary || t.error || `${t.task_type.replace(/_/g, " ").toLowerCase()} · ${t.state}`,
      t: timeIST(t.sim_time ?? t.created_at), ms: secs(t.latency_ms), verdict, tone: toneOf(verdict),
      payload: payloadRows(t.required_output_schema, t.result),
      tools: calls.slice(0, TOOL_CAP).map((c) => ({ n: c.tool, ok: c.ok !== false, r: c.ok === false ? (c.error || "failed") : c.rows != null ? `ok · ${c.rows} rows` : "ok", ms: secs(c.ms) })),
      moreTools: Math.max(calls.length - TOOL_CAP, 0), toolsNote: calls.length ? null : "No tool calls; deterministic decision on its inputs.",
      meta,
    });
  }
  return steps;
}

// ── the run's proposal workflows ────────────────────────────────────────────────────────────────────────────────────

export const proposalsOf = (wfs: WorkflowRow[] | undefined): WorkflowRow[] =>
  (wfs ?? []).filter((w) => w.kind === "TRADE_PROPOSAL").sort((a, b) => (a.created_at < b.created_at ? -1 : a.created_at > b.created_at ? 1 : 0));

const outcome = (w: WorkflowRow) => (w.outcome ?? {}) as Record<string, unknown>;
export const tradeIdOf = (w: WorkflowRow): string | null => (typeof outcome(w).trade_id === "string" ? (outcome(w).trade_id as string) : null);
export const signalIdOf = (w: WorkflowRow): string | null => {
  const v = (w.input ?? {}) as Record<string, unknown>;
  return typeof v.signal_id === "string" ? v.signal_id : null;
};

/** The chain shown first: a revised plan (the longest hand-on), else one waiting on a person, else an approval, else the first. */
export function defaultWorkflow(list: WorkflowRow[]): string | null {
  const by = (f: (w: WorkflowRow) => boolean) => list.find(f)?.workflow_id;
  return by((w) => Number(outcome(w).plan_version ?? 1) > 1) ?? by((w) => w.state === "WAITING_HUMAN") ?? by((w) => outcome(w).result === "APPROVED_NO_EXECUTION" || outcome(w).result === "APPROVED") ?? list[0]?.workflow_id ?? null;
}

const RESULT_LABEL: Record<string, string> = {
  APPROVED_NO_EXECUTION: "approved", APPROVED: "approved", WAITING_HUMAN: "waiting on a person", NO_TRADE: "no plan", RESEARCH_ONLY: "research only",
  REJECTED: "rejected", REJECTED_BY_PERSON: "rejected by a person", NEEDS_REVISION: "revision asked", REVISION_REQUESTED: "revision asked",
  ENTRIES_STOPPED: "held back · stop control on", EXPIRED: "expired", SUSPENDED: "suspended", FAILED: "failed",
};
export const resultLabel = (w: WorkflowRow): string => {
  const r = outcome(w).result;
  if (typeof r === "string") return RESULT_LABEL[r] ?? humanize(r).toLowerCase();
  return humanize(w.state).toLowerCase();
};

export interface CardText { id: string; title: string; sub: string }

export function cardText(w: WorkflowRow, plan: TradePlanRow | undefined, signal: SignalRow | undefined): CardText {
  const tid = tradeIdOf(w);
  const inst = plan?.instrument ?? signal?.instrument ?? shortId(signalIdOf(w));
  const strat = plan ? humanize(plan.strategy_type) : null;
  return {
    id: shortId(tid ?? w.workflow_id),
    title: strat ? `${inst} · ${strat}` : inst,
    sub: `${w.session_date ? dateShort(w.session_date) : DASH} · ${resultLabel(w)}`,
  };
}

/** Steps of a detail without its signal row (for the card's "N STEPS"). */
export const stepCount = (d: WorkflowDetail): number => {
  const ids = new Set(d.tasks.map((t) => t.task_id));
  return d.tasks.length + (d.handoffs ?? []).filter((h) => !ids.has(h.from_task_id)).length;
};

/** "Workflow COMPLETED · approved" + the API's note / reasons for the end of the chain. */
export function outcomeText(w: WorkflowRow): { head: string; detail: string | null; approvalPath: boolean } {
  const o = outcome(w);
  const r = typeof o.result === "string" ? o.result : null;
  const reasons = arr(o.reasons).map(String).join("; ");
  const detail = s(o.note) || s(o.reason) || reasons || s(w.error) || null;
  return { head: `Workflow ${w.state}${r ? ` · ${r.replace(/_/g, " ")}` : ""}`, detail, approvalPath: r === "APPROVED_NO_EXECUTION" || r === "APPROVED" || r === "WAITING_HUMAN" };
}
