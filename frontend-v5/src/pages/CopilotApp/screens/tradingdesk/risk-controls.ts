/**
 * Smart trading desk — the user's risk controls (backend/routes/risk_controls.py, services/risk_controls.py).
 *
 *   GET /api/risk/status            kill switch and halt, who set them, when and why; the data modes; live
 *                                   authorization; whether the user may clear a control (can_reset) and whether the
 *                                   policy gate checks their paper writes                                (useRiskStatus)
 *   PUT /api/risk/kill-switch       { enabled, reason } — the reason is required both ways; clearing needs an admin
 *   PUT /api/risk/halt              { enabled, reason }                                     (useSetKillSwitch, useSetHalt)
 *   GET /api/risk/policy            the limits the gate applies and what is in use against them          (useRiskPolicy)
 *   GET /api/risk/audit?limit=      every control change, append only                                    (useRiskAudit)
 *   GET /api/risk/decisions?limit=  every allow / block the gate made                                    (useRiskDecisions)
 *
 * Scope, as the route states it: the controls block NEW paper positions. No order is placed anywhere in this system,
 * and open positions are untouched.
 *
 * A status body without a boolean `kill_switch` reads as unknown (`known: false`), never as "off": an unreadable kill
 * switch must not look like one that is off. The desk header shows its pill only for a known "on".
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { http } from "@/services/api/http";
import { ApiError } from "@/services/api/errors";
import { useImpersonationStore } from "@/stores/impersonation.store";
import { num } from "./desk-data";

type Raw = Record<string, unknown>;
const rec = (v: unknown): Raw => (v && typeof v === "object" && !Array.isArray(v) ? (v as Raw) : {});
const str = (v: unknown): string | null => (typeof v === "string" && v.trim() ? v.trim() : null);
const bool = (v: unknown): boolean | null => (typeof v === "boolean" ? v : null);

const isForbidden = (e: unknown) => e instanceof ApiError && (e.kind === "forbidden" || e.status === 403);
const retry = (count: number, e: unknown) => !isForbidden(e) && !(e instanceof ApiError && e.kind === "contract_drift") && count < 1;

const KEY = ["copilot", "desk", "risk"] as const;

/** Where the controls live in the app, for messages that send the user there. */
export const RISK_CONTROLS_PATH = "Desk › More › Risk controls";

// ── status ───────────────────────────────────────────────────────────────

export interface LiveAuthorization {
  granted: boolean;
  grantedBy: string | null;
  grantedAt: string | null;
  reason: string | null;
}

export interface RiskStatus {
  /** False when the body has no boolean kill_switch: the state is unknown, not off. */
  known: boolean;
  killSwitch: boolean;
  halted: boolean;
  reason: string | null;
  setBy: string | null;
  setAt: string | null;
  policyVersion: string | null;
  scope: string | null;
  notInScope: string | null;
  /** The server's word on whether this user may clear a control; only an admin may. */
  canReset: boolean;
  liveAuthorization: LiveAuthorization | null;
  modes: string[];
  liveExecutionAvailable: boolean;
  /** null when the route did not say. */
  gateEnabled: boolean | null;
  gatePolicyVersion: string | null;
}

export function readRiskStatus(body: unknown): RiskStatus {
  const d = rec(body);
  const kill = bool(d.kill_switch);
  const la = rec(d.live_authorization);
  const gate = rec(d.gate);
  return {
    known: kill != null,
    killSwitch: kill === true,
    halted: d.halted === true,
    reason: str(d.reason),
    setBy: str(d.set_by),
    setAt: str(d.set_at),
    policyVersion: str(d.policy_version),
    scope: str(d.scope),
    notInScope: str(d.not_in_scope),
    canReset: d.can_reset === true,
    liveAuthorization: Object.keys(la).length
      ? { granted: la.granted === true, grantedBy: str(la.granted_by), grantedAt: str(la.granted_at), reason: str(la.reason) }
      : null,
    modes: Array.isArray(d.modes) ? d.modes.flatMap((m) => (str(m) ? [str(m) as string] : [])) : [],
    liveExecutionAvailable: d.live_execution_available === true,
    gateEnabled: bool(gate.enabled),
    gatePolicyVersion: str(gate.policy_version),
  };
}

export function useRiskStatus() {
  const profile = useImpersonationStore((st) => st.profileId);
  return useQuery<RiskStatus>({
    queryKey: [...KEY, "status", profile ?? "self"],
    staleTime: 30_000,
    retry,
    queryFn: async ({ signal }) => readRiskStatus((await http({ path: "/api/risk/status", signal, noRetry: true })).data),
  });
}

// ── policy ───────────────────────────────────────────────────────────────

export interface RiskPolicy {
  policyVersion: string | null;
  maxLegs: number | null;
  maxLotsPerLeg: number | null;
  maxOpenStructures: number | null;
  maxCapitalAtRiskRs: number | null;
  requireDefinedRisk: boolean | null;
  /** null when the route sent no usage block. */
  usage: { openStructures: number | null; capitalAtRiskRs: number | null } | null;
}

export function readRiskPolicy(body: unknown): RiskPolicy {
  const d = rec(body);
  if (!d.limits || typeof d.limits !== "object" || Array.isArray(d.limits)) throw ApiError.contractDrift("risk.policy: no limits");
  const l = rec(d.limits);
  const u = rec(d.usage);
  return {
    policyVersion: str(d.policy_version),
    maxLegs: num(l.max_legs),
    maxLotsPerLeg: num(l.max_lots_per_leg),
    maxOpenStructures: num(l.max_open_structures),
    maxCapitalAtRiskRs: num(l.max_capital_at_risk_rs),
    requireDefinedRisk: bool(l.require_defined_risk),
    usage: Object.keys(u).length ? { openStructures: num(u.open_structures), capitalAtRiskRs: num(u.capital_at_risk_rs) } : null,
  };
}

export function useRiskPolicy() {
  const profile = useImpersonationStore((st) => st.profileId);
  return useQuery<RiskPolicy>({
    queryKey: [...KEY, "policy", profile ?? "self"],
    staleTime: 60_000,
    retry,
    queryFn: async ({ signal }) => readRiskPolicy((await http({ path: "/api/risk/policy", signal, noRetry: true })).data),
  });
}

// ── audit and decisions (append only) ────────────────────────────────────

const LIST_LIMIT = 50;

/** Newest first by `at`; a row without a readable time keeps its place after the dated ones. */
function newestFirst<T extends { at: string | null }>(rows: T[]): T[] {
  const t = (r: T) => (r.at ? new Date(r.at).getTime() : NaN);
  return rows
    .map((r, i) => ({ r, i, t: t(r) }))
    .sort((a, b) => {
      const an = Number.isFinite(a.t);
      const bn = Number.isFinite(b.t);
      if (an && bn && a.t !== b.t) return b.t - a.t;
      if (an !== bn) return an ? -1 : 1;
      return a.i - b.i;
    })
    .map((x) => x.r);
}

export interface RiskAuditEvent {
  id: string;
  at: string | null;
  actor: string | null;
  action: string | null;
  field: string | null;
  before: boolean | null;
  after: boolean | null;
  reason: string | null;
  policyVersion: string | null;
}

export interface RiskAudit {
  events: RiskAuditEvent[];
  appendOnly: boolean;
  policyVersion: string | null;
}

export function readRiskAudit(body: unknown): RiskAudit {
  const d = rec(body);
  if (!Array.isArray(d.events)) throw ApiError.contractDrift("risk.audit: no events list");
  const events = d.events.map((v, i): RiskAuditEvent => {
    const e = rec(v);
    return {
      id: str(e._id) ?? `event-${i}`, at: str(e.at), actor: str(e.actor), action: str(e.action), field: str(e.field),
      before: bool(e.before), after: bool(e.after), reason: str(e.reason), policyVersion: str(e.policy_version),
    };
  });
  return { events: newestFirst(events), appendOnly: d.append_only === true, policyVersion: str(d.policy_version) };
}

export function useRiskAudit() {
  const profile = useImpersonationStore((st) => st.profileId);
  return useQuery<RiskAudit>({
    queryKey: [...KEY, "audit", profile ?? "self"],
    staleTime: 30_000,
    retry,
    queryFn: async ({ signal }) => readRiskAudit((await http({ path: "/api/risk/audit", query: { limit: LIST_LIMIT }, signal, noRetry: true })).data),
  });
}

export interface RiskReason {
  code: string | null;
  message: string;
  /** The universal risk service's severity (block, halt, reject, defer, reduce, info); null on older shapes. */
  severity: string | null;
}

/** The severities that refuse an entry (backend/services/risk_gate/service.py BLOCKING). */
const BLOCKING = new Set(["block", "halt", "reject", "defer"]);

/**
 * Blocking reasons first, then the rest (a size reduction), each group in the order sent. A reason with no severity
 * (the older gate and kill-switch shapes) counts as blocking, so those keep their order. An `info` note is kept only
 * when nothing else was sent: it explains, it does not refuse.
 */
export function orderReasons(reasons: RiskReason[]): RiskReason[] {
  const rank = (r: RiskReason) => (r.severity == null || BLOCKING.has(r.severity) ? 0 : r.severity === "info" ? 2 : 1);
  const ranked = reasons.map((r, i) => ({ r, i, k: rank(r) })).sort((a, b) => a.k - b.k || a.i - b.i);
  const main = ranked.filter((x) => x.k < 2);
  return (main.length ? main : ranked).map((x) => x.r);
}

export interface RiskDecision {
  id: string;
  at: string | null;
  action: string | null;
  /** "allow" or "block"; older rows may carry another word, kept as given. */
  outcome: string | null;
  path: string | null;
  mode: string | null;
  symbol: string | null;
  reasons: RiskReason[];
  correlationId: string | null;
}

export interface RiskDecisions {
  decisions: RiskDecision[];
  policyVersion: string | null;
}

/** Reasons as the routes send them: `{code, message}` objects or plain strings. A code with no message is shown as the code. */
export function readReasons(v: unknown): RiskReason[] {
  if (!Array.isArray(v)) return [];
  return v.flatMap((x): RiskReason[] => {
    if (typeof x === "string") return x.trim() ? [{ code: null, message: x.trim(), severity: null }] : [];
    const r = rec(x);
    const code = str(r.code);
    const message = str(r.message) ?? code;
    return message ? [{ code, message, severity: str(r.severity)?.toLowerCase() ?? null }] : [];
  });
}

export function readRiskDecisions(body: unknown): RiskDecisions {
  const d = rec(body);
  if (!Array.isArray(d.decisions)) throw ApiError.contractDrift("risk.decisions: no decisions list");
  const decisions = d.decisions.map((v, i): RiskDecision => {
    const r = rec(v);
    return {
      // The contract names the id `_id`; the current route renames it `event_id`.
      id: str(r._id) ?? str(r.event_id) ?? `decision-${i}`, at: str(r.at), action: str(r.action), outcome: str(r.outcome),
      path: str(r.path), mode: str(r.mode), symbol: str(r.symbol), reasons: readReasons(r.reasons), correlationId: str(r.correlation_id),
    };
  });
  return { decisions: newestFirst(decisions), policyVersion: str(d.policy_version) };
}

export function useRiskDecisions() {
  const profile = useImpersonationStore((st) => st.profileId);
  return useQuery<RiskDecisions>({
    queryKey: [...KEY, "decisions", profile ?? "self"],
    staleTime: 30_000,
    retry,
    queryFn: async ({ signal }) => readRiskDecisions((await http({ path: "/api/risk/decisions", query: { limit: LIST_LIMIT }, signal, noRetry: true })).data),
  });
}

// ── writes ───────────────────────────────────────────────────────────────

export interface RiskControlChange {
  enabled: boolean;
  /** Required both ways; recorded with the change. */
  reason: string;
}

function useSetControl(path: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (body: RiskControlChange): Promise<RiskStatus> =>
      readRiskStatus((await http({ method: "PUT", path, body, noRetry: true })).data),
    // Status, audit and decisions all change with a control: re-read them from the server.
    onSuccess: () => qc.invalidateQueries({ queryKey: KEY }),
  });
}

export const useSetKillSwitch = () => useSetControl("/api/risk/kill-switch");
export const useSetHalt = () => useSetControl("/api/risk/halt");

/** The `detail` object of an error body, if the route sent one. */
export function detailOf(e: unknown): Raw {
  return e instanceof ApiError ? rec(rec(e.body).detail) : {};
}

/** A reason without its own closing full stop, so a joined sentence ends with exactly one. */
export const bareReason = (t: string) => t.replace(/[.\s]+$/, "");

/**
 * A 409 `risk_blocked` from any paper write, in plain words, pointing to the controls; null for any other error.
 * The universal risk service and the gate send `reasons` (listed blocking first, orderReasons); the older
 * kill-switch refusal sends `message` and the stored `reason` instead.
 */
export function riskBlockedText(e: unknown): string | null {
  const d = detailOf(e);
  if (d.code !== "risk_blocked") return null;
  const bare = bareReason;
  const reasons = orderReasons(readReasons(d.reasons)).map((r) => bare(r.message));
  const msg = str(d.message);
  const message = msg ? bare(msg) : null;
  const stored = str(d.reason);
  let why = reasons.length ? reasons.join("; ") : message ?? "a risk control is on";
  if (!reasons.length && stored) why += ` (reason given: “${stored}”)`;
  return `Blocked by your risk controls: ${why}. See ${RISK_CONTROLS_PATH}. (risk_blocked)`;
}

/** A failed control change in words: who may clear a control, a missing reason, else the server's own words. */
export function controlProblem(e: unknown): string {
  const d = detailOf(e);
  if (d.code === "admin_required") return "Only an admin can turn this off. (admin_required)";
  if (d.code === "invalid_input") return `${str(d.message) ?? "The change was not accepted."} (invalid_input)`;
  if (e instanceof ApiError) {
    if (e.kind === "network") return "The network request failed. Nothing was changed.";
    if (e.kind === "timeout") return "The request took too long. Check the status before trying again.";
    if (e.kind === "forbidden") return "This account cannot change risk controls.";
    if (e.detail) return e.detail;
    return e.message || `HTTP ${e.status ?? "error"}`;
  }
  return e instanceof Error && e.message ? e.message : "The request failed.";
}
