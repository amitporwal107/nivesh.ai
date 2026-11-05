/**
 * Queries and pure helpers of the Desk overview (screen 01). Every figure comes from the desk API:
 *   - agent tasks:   GET /agents/{key}/activity  (newest first; includes simulation tasks, which the overview drops)
 *   - approvals:     GET /approvals?limit=…      (newest first; used to find the policy / scope of a Middle Office task)
 *   - plan versions: GET /trade-plans/{id}?version=n  (max loss of a pending approval's exact plan version)
 *   - assessments:   GET /risk/assessments/{id}  (policy + sizing of a Risk & Operations task)
 * Query keys start with "desk" so the shell's invalidate after a write refreshes them too.
 */
import { useQueries, useQuery } from "@tanstack/react-query";
import { deskGet } from "../../api";
import { dateTimeIST, timeIST, todayIST } from "../../format";
import type { AgentKey, AgentStatus, AgentTaskRow, ApprovalRow, DeskStatus, RiskAssessmentRow, TradePlanDetail } from "../../types";

/** The design's order of the agent cards (AI Trader, Trading Assistant, Risk, Middle Office, Tech Support). */
export const AGENT_ORDER: AgentKey[] = ["AI_TRADER", "TRADING_ASSISTANT", "RISK_OPS", "MIDDLE_OFFICE", "TECH_SUPPORT"];

/** Tasks fetched per agent. The API has no desk-only filter, so simulation tasks share this window. */
export const ACTIVITY_LIMIT = 50;
export const ACTIVITY_ROWS = 8;

export function useAgentActivities() {
  return useQueries({
    queries: AGENT_ORDER.map((k) => ({
      queryKey: ["desk", "agents", k, "activity", ACTIVITY_LIMIT],
      queryFn: () => deskGet<AgentTaskRow[]>(`/agents/${k}/activity`, { limit: ACTIVITY_LIMIT }),
      refetchInterval: 30_000,
    })),
  });
}

/** Recent approval rows (all kinds), only fetched when the activity table shows a Middle Office decision. */
export function useRecentApprovals(enabled: boolean) {
  return useQuery({
    queryKey: ["desk", "approvals", "recent", 100],
    queryFn: () => deskGet<ApprovalRow[]>("/approvals", { limit: 100 }),
    enabled,
    refetchInterval: 30_000,
  });
}

/** The plan version each pending approval asks about (its max loss ranks the "Needs you" rows). */
export function usePendingPlans(pending: ApprovalRow[]) {
  return useQueries({
    queries: pending.map((a) => ({
      queryKey: ["desk", "trade-plans", a.trade_id, a.plan_version],
      queryFn: () => deskGet<TradePlanDetail>(`/trade-plans/${encodeURIComponent(a.trade_id)}`, { version: a.plan_version }),
    })),
  });
}

export function useAssessments(ids: string[]) {
  return useQueries({
    queries: ids.map((id) => ({
      queryKey: ["desk", "risk", "assessments", id],
      queryFn: () => deskGet<RiskAssessmentRow>(`/risk/assessments/${encodeURIComponent(id)}`),
      staleTime: 5 * 60_000,       // an assessment row never changes
    })),
  });
}

// ── helpers ──────────────────────────────────────────────────────────────────────────────────────────────────────────

export const TASK_LABEL: Record<string, string> = {
  PREMARKET_HEALTH_CHECK: "Pre-market check",
  SCAN_MARKET: "Market scan",
  GENERATE_STRATEGY: "Plan drafting",
  REVISE_STRATEGY: "Plan revision",
  ASSESS_RISK: "Risk assessment",
  REVIEW_FOR_APPROVAL: "Approval review",
};

/** Task states that mean the agent is still on it. */
export const ACTIVE_STATES = new Set(["CREATED", "ASSIGNED", "ACCEPTED", "RUNNING", "RESULT_READY", "VALIDATED", "RETRY_PENDING"]);

export const taskTime = (t: AgentTaskRow): string => t.completed_at ?? t.created_at;

export const taskLabel = (t: AgentTaskRow): string =>
  `${TASK_LABEL[t.task_type] ?? t.task_type}${t.entity_id ? ` · ${t.entity_id}` : ""}`;

/** "approval://APR-1" → "APR-1"; "assessment://RSK-1" → "RSK-1"; anything else → null. */
export function refId(ref: string | null | undefined, scheme: string): string | null {
  const p = `${scheme}://`;
  if (!ref || !ref.startsWith(p)) return null;
  return ref.slice(p.length).split(/[?@]/)[0] || null;
}

/** 11:41 for today (IST), "4 Nov, 15:02" for another day. */
export function whenIST(v: string | null | undefined, now: number = Date.now()): string {
  if (!v) return "—";
  const d = new Date(v);
  if (Number.isNaN(d.getTime())) return "—";
  return todayIST(d) === todayIST(new Date(now)) ? timeIST(v, { seconds: false }) : dateTimeIST(v);
}

/** The registry can hold several versions of an agent (newest first per key): keep one row per agent. */
export function uniqueAgents(st: DeskStatus | undefined): DeskStatus["agents"] {
  const seen = new Set<string>();
  return (st?.agents ?? []).filter((a) => (seen.has(a.agent_key) ? false : (seen.add(a.agent_key), true)));
}

export const HEALTHY: AgentStatus[] = ["IDLE", "BUSY"];

export function agentCounts(st: DeskStatus | undefined): { total: number; healthy: number; degraded: number; offline: number } {
  const a = uniqueAgents(st);
  const healthy = a.filter((x) => HEALTHY.includes(x.status)).length;
  const offline = a.filter((x) => x.status === "OFFLINE").length;
  return { total: a.length, healthy, offline, degraded: a.length - healthy - offline };
}

/** The pre-market report inside a PREMARKET_CHECK workflow outcome ({premarket: {status, session_date, allowed_segments}}). */
export function premarketOf(st: DeskStatus | undefined): { status: string | null; sessionDate: string | null; allowed: string[] | null; reason: string | null } | null {
  const lp = st?.last_premarket;
  if (!lp) return null;
  const o = (lp.outcome ?? {}) as Record<string, unknown>;
  const r = (o.premarket && typeof o.premarket === "object" ? o.premarket : o) as Record<string, unknown>;
  return {
    status: typeof r.status === "string" ? r.status : null,
    sessionDate: (typeof r.session_date === "string" ? r.session_date : null) ?? lp.session_date ?? null,
    allowed: Array.isArray(r.allowed_segments) ? r.allowed_segments.map(String) : null,
    reason: typeof r.reason === "string" ? r.reason : null,
  };
}

/** Earliest expiry among pending approvals (null when none carries one). */
export function firstExpiry(pending: ApprovalRow[]): string | null {
  const ts = pending.map((a) => a.expires_at).filter((x): x is string => !!x && !Number.isNaN(new Date(x).getTime()));
  if (!ts.length) return null;
  return ts.reduce((a, b) => (new Date(a).getTime() <= new Date(b).getTime() ? a : b));
}

export const COUNT_WORD = ["No approvals", "One approval", "Two approvals", "Three approvals"];
export const countWord = (n: number): string => COUNT_WORD[n] ?? `${n} approvals`;

export const MODE_WORD: Record<string, string> = { RESEARCH: "Research", ASSISTED: "Assisted", AUTONOMOUS_PAPER: "Auto paper" };
