/**
 * F&O lab — data for the governance screens (Programs, Replay, Shadow, Live, Certification, Audit).
 *
 *   GET  /api/desk/strategy/templates   the strategy templates the payoff engine can price: legs, own parameters,
 *                                       calculation version; templates, not certified programs     (useStrategyTemplates)
 *   POST /api/desk/strategy/payoff      the dry run's pricing, a pure calculation (tradingdesk/strategy/usePayoff.ts)
 *   GET  /api/fno/forward-test          the forward test of a futures signal (tradingdesk/FnoForwardTest.tsx useForwardTest)
 *   GET  /api/risk/status, /api/risk/audit   kill switch, gate and live authorization; control changes (risk-controls.ts)
 *   GET  /api/risk/decisions?limit=200  every recorded risk decision with the fields the audit lineage shows: policy
 *                                       version, inputs hash, checks, mode, source, snapshot version (useAuditDecisions)
 *   GET  /api/risk/live-readiness       the twelve PRD §21 conditions, each pass / fail with its evidence (useLiveReadiness)
 *   GET  /api/risk/decisions/{id}/lineage   the ten lineage steps of one decision                (useDecisionLineage)
 *   POST /api/risk/decisions/{id}/replay    re-run the gate on the stored snapshot; writes nothing (useReplayDecision)
 *
 * The audit reader is separate from risk-controls.ts readRiskDecisions on purpose: that one keeps the six fields the
 * Risk Control Center lists; the lineage needs the rest of the stored row (inputs hash, checks, policy version), and
 * reads a longer list so a search by id can find older decisions. Reasons are read with the same readReasons.
 */
import { useMutation, useQuery } from "@tanstack/react-query";
import { http } from "@/services/api/http";
import { ApiError } from "@/services/api/errors";
import { useImpersonationStore } from "@/stores/impersonation.store";
import { num } from "../tradingdesk/desk-data";
import { readReasons, type RiskReason } from "../tradingdesk/risk-controls";
import type { PayoffRequest } from "../tradingdesk/strategy/strategy-contract";
import { legFromChain, type FnoChain } from "../trading/fno";

type Raw = Record<string, unknown>;
const rec = (v: unknown): Raw => (v && typeof v === "object" && !Array.isArray(v) ? (v as Raw) : {});
const str = (v: unknown): string | null => (typeof v === "string" && v.trim() ? v.trim() : null);

// ── templates ────────────────────────────────────────────────────────────

export interface TemplateLeg {
  side: "buy" | "sell";
  optionType: "call" | "put" | null;
  strikeParam: string | null;
}

export interface StrategyTemplate {
  name: string;
  label: string;
  kind: "option" | "future" | "cash";
  legs: TemplateLeg[];
  params: string[];
  calculationVersion: string | null;
}

export interface StrategyTemplates {
  templates: StrategyTemplate[];
  calculationVersion: string | null;
  readOnly: boolean;
}

export function readStrategyTemplates(body: unknown): StrategyTemplates {
  const d = rec(body);
  if (!Array.isArray(d.templates)) throw ApiError.contractDrift("strategy.templates: no templates list");
  const templates = d.templates.flatMap((v): StrategyTemplate[] => {
    const t = rec(v);
    const name = str(t.name);
    const kind = t.kind === "option" || t.kind === "future" || t.kind === "cash" ? t.kind : null;
    if (!name || !kind) return [];
    const legs = (Array.isArray(t.legs) ? t.legs : []).flatMap((x): TemplateLeg[] => {
      const l = rec(x);
      if (l.side !== "buy" && l.side !== "sell") return [];
      const ot = l.option_type === "call" || l.option_type === "put" ? l.option_type : null;
      return [{ side: l.side, optionType: ot, strikeParam: str(l.strike_param) }];
    });
    const params = Array.isArray(t.params) ? t.params.flatMap((p) => (str(p) ? [str(p) as string] : [])) : [];
    return [{ name, label: str(t.label) ?? name, kind, legs, params, calculationVersion: str(t.calculation_version) }];
  });
  return { templates, calculationVersion: str(d.calculation_version), readOnly: d.read_only === true };
}

export function useStrategyTemplates() {
  return useQuery<StrategyTemplates>({
    queryKey: ["copilot", "fnolab", "templates"],
    staleTime: 10 * 60_000,
    retry: false,
    queryFn: async ({ signal }) => readStrategyTemplates((await http({ path: "/api/desk/strategy/templates", signal, noRetry: true })).data),
  });
}

// ── dry run: a template's legs from the end-of-day chain ─────────────────

/**
 * Strike offsets from the ATM strike, in chain steps, for each option template the dry run can build. A spread uses the
 * ATM strike and two steps away; the condor's short legs sit two steps out and its wings four. Templates without an
 * entry (futures, cash) are not offered for a dry run.
 */
export const DRY_RUN_OFFSETS: Record<string, Record<string, number>> = {
  long_call: { strike: 0 },
  long_put: { strike: 0 },
  bull_call_spread: { long_strike: 0, short_strike: 2 },
  bear_put_spread: { long_strike: 0, short_strike: -2 },
  iron_condor: { long_put_strike: -4, short_put_strike: -2, short_call_strike: 2, long_call_strike: 4 },
};

export interface DryRunLeg {
  side: "buy" | "sell";
  optionType: "call" | "put";
  strike: number;
  premium: number;
}

export type DryRunBuild =
  | { ok: true; legs: DryRunLeg[]; request: PayoffRequest }
  | { ok: false; problem: string };

/**
 * The template's legs on the chain: each strike `offset` steps from the ATM strike, each premium the contract's
 * closing price. A missing strike, a contract with no close, a chain with no spot or no lot size is a problem, never a
 * guessed number.
 */
export function buildDryRun(t: StrategyTemplate, chain: FnoChain, lots = 1): DryRunBuild {
  const offsets = DRY_RUN_OFFSETS[t.name];
  if (!offsets || t.kind !== "option") return { ok: false, problem: `${t.label} has no dry run here: only option templates are built from the chain.` };
  const spot = chain.summary.spot;
  if (spot == null) return { ok: false, problem: "The chain has no underlying price, so the strikes around the money cannot be chosen." };
  const lot = chain.lot_size ?? null;
  if (lot == null) return { ok: false, problem: "The chain did not send a lot size, so the payoff cannot be worked out." };
  const legs: DryRunLeg[] = [];
  for (const l of t.legs) {
    if (!l.optionType || !l.strikeParam || offsets[l.strikeParam] == null) return { ok: false, problem: `${t.label}: a leg has no strike rule.` };
    const got = legFromChain(chain, l.optionType === "call" ? "CE" : "PE", offsets[l.strikeParam]);
    if (!got) return { ok: false, problem: `The chain has no strike ${offsets[l.strikeParam]} steps from the money for the ${l.optionType} leg.` };
    if (got.premium == null) return { ok: false, problem: `The ${got.strike} ${l.optionType} has no closing price above zero, so it is not priced.` };
    legs.push({ side: l.side, optionType: l.optionType, strike: got.strike, premium: got.premium });
  }
  const source = `NSE F&O bhavcopy close, ${chain.summary.as_of}`;
  const request: PayoffRequest = {
    underlying: chain.symbol,
    reference_price: spot,
    as_of: chain.summary.as_of,
    legs: legs.map((l) => ({
      kind: "option", side: l.side, quantity: lots, lot_size: lot, entry_price: l.premium, expiry: chain.summary.expiry,
      strike: l.strike, option_type: l.optionType, price_source: source,
    })),
  };
  return { ok: true, legs, request };
}

// ── audit: decisions with the fields the lineage shows ───────────────────

export interface GateCheck {
  check: string;
  status: string | null;
  detail: string | null;
}

export interface AuditDecision {
  id: string;
  at: string | null;
  /** "allow"/"allowed" or "block"/"blocked"; older rows may carry another word, kept as given. */
  outcome: string | null;
  path: string | null;
  action: string | null;
  mode: string | null;
  symbol: string | null;
  reasons: RiskReason[];
  correlationId: string | null;
  policyVersion: string | null;
  inputsHash: string | null;
  checks: GateCheck[];
  source: string | null;
  actorId: string | null;
  instrument: string | null;
  legs: number | null;
  capitalAtRiskRs: number | null;
  /** "decision-snapshot-v1" when the gate stored what it read; null on older rows (they cannot be replayed). */
  snapshotVersion: string | null;
  /** The universal risk service's fields (services/risk_gate/service.py _persist); null / empty on older rows. */
  limitsVersion: string | null;
  estimateVersion: string | null;
  requestedQty: number | null;
  approvedQty: number | null;
  requestedLots: number | null;
  approvedLots: number | null;
  /** est-risk-v1: loss at the stop (gross) + round-trip costs + gap stress = total; null when not sized. */
  estimate: { gross: number | null; costs: number | null; gapStress: number | null; total: number | null } | null;
  /** The budgets the decision was judged against, as recorded: rupees, percentages, counts (numbers only). */
  budget: Record<string, number>;
  /** The sector the decision used (detail.sector or budget.sector). */
  sector: string | null;
}

export const isBlocked = (outcome: string | null) => outcome === "block" || outcome === "blocked" || outcome === "denied";

export function readAuditDecisions(body: unknown): AuditDecision[] {
  const d = rec(body);
  if (!Array.isArray(d.decisions)) throw ApiError.contractDrift("risk.decisions: no decisions list");
  const rows = d.decisions.map((v, i): AuditDecision => {
    const r = rec(v);
    const detail = rec(r.detail);
    const est = rec(r.estimated_risk_rs);
    const budget = rec(r.budget);
    const checks = (Array.isArray(r.checks) ? r.checks : []).flatMap((x): GateCheck[] => {
      const c = rec(x);
      const check = str(c.check);
      return check ? [{ check, status: str(c.status), detail: str(c.detail) }] : [];
    });
    return {
      id: str(r._id) ?? str(r.event_id) ?? `decision-${i}`, at: str(r.at), outcome: str(r.outcome), path: str(r.path),
      action: str(r.action), mode: str(r.mode), symbol: str(r.symbol), reasons: readReasons(r.reasons),
      correlationId: str(r.correlation_id), policyVersion: str(r.policy_version) ?? str(r.limits_version),
      inputsHash: str(r.inputs_hash), checks, source: str(r.source), actorId: str(r.actor_id),
      instrument: str(detail.instrument), legs: num(detail.legs), capitalAtRiskRs: num(detail.capital_at_risk_rs),
      snapshotVersion: str(r.snapshot_version),
      limitsVersion: str(r.limits_version), estimateVersion: str(r.estimate_version),
      requestedQty: num(r.requested_qty), approvedQty: num(r.approved_qty),
      requestedLots: num(r.requested_lots), approvedLots: num(r.approved_lots),
      estimate: Object.keys(est).length
        ? { gross: num(est.gross), costs: num(est.costs), gapStress: num(est.gap_stress), total: num(est.total) }
        : null,
      budget: Object.fromEntries(Object.entries(budget).flatMap(([k, v]) => (num(v) != null ? [[k, num(v) as number]] : []))),
      sector: str(detail.sector) ?? str(budget.sector),
    };
  });
  const t = (x: AuditDecision) => (x.at ? new Date(x.at).getTime() : NaN);
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

export function useAuditDecisions() {
  const profile = useImpersonationStore((st) => st.profileId);
  return useQuery<AuditDecision[]>({
    queryKey: ["copilot", "fnolab", "audit-decisions", profile ?? "self"],
    staleTime: 30_000,
    retry: false,
    queryFn: async ({ signal }) => readAuditDecisions((await http({ path: "/api/risk/decisions", query: { limit: 200 }, signal, noRetry: true })).data),
  });
}

/** Search by decision id or correlation id: case-insensitive substring of either. */
export function matchesDecision(d: AuditDecision, q: string): boolean {
  const s = q.trim().toLowerCase();
  if (!s) return true;
  return d.id.toLowerCase().includes(s) || (d.correlationId ?? "").toLowerCase().includes(s);
}

// ── live readiness (PRD §21) ─────────────────────────────────────────────

export interface LiveCondition {
  id: string;
  label: string;
  /** Anything other than "pass" from the server reads as fail: an unknown is never a pass. */
  status: "pass" | "fail";
  evidence: string;
  backlog: string | null;
}

export interface LiveReadiness {
  conditions: LiveCondition[];
  count: number;
  enforceable: number;
  liveExecutionAvailable: boolean;
  policyVersion: string | null;
  readAt: string | null;
}

export function readLiveReadiness(body: unknown): LiveReadiness {
  const d = rec(body);
  if (!Array.isArray(d.conditions)) throw ApiError.contractDrift("risk.live-readiness: no conditions list");
  const conditions = d.conditions.flatMap((v): LiveCondition[] => {
    const c = rec(v);
    const id = str(c.id);
    const label = str(c.label);
    if (!id || !label) return [];
    return [{ id, label, status: c.status === "pass" ? "pass" : "fail", evidence: str(c.evidence) ?? "No evidence given", backlog: str(c.backlog) }];
  });
  return {
    conditions, count: conditions.length, enforceable: conditions.filter((c) => c.status === "pass").length,
    liveExecutionAvailable: d.live_execution_available === true, policyVersion: str(d.policy_version), readAt: str(d.read_at),
  };
}

export function useLiveReadiness() {
  const profile = useImpersonationStore((st) => st.profileId);
  return useQuery<LiveReadiness>({
    queryKey: ["copilot", "fnolab", "live-readiness", profile ?? "self"],
    staleTime: 30_000,
    retry: false,
    queryFn: async ({ signal }) => readLiveReadiness((await http({ path: "/api/risk/live-readiness", signal, noRetry: true })).data),
  });
}

// ── decision lineage and replay ──────────────────────────────────────────

export type LineageStatus = "recorded" | "not_recorded" | "not_reached" | "not_applicable";

export interface LineageStep {
  step: string;
  label: string;
  status: LineageStatus;
  detail: string;
  /** A record id, a list of ids, or a field path on the decision row. */
  ref: string | null;
  backlog: string | null;
}

export interface DecisionLineage {
  decisionId: string;
  steps: LineageStep[];
  recorded: number;
  replayable: boolean;
}

const STATUSES: LineageStatus[] = ["recorded", "not_recorded", "not_reached", "not_applicable"];

export function readLineage(body: unknown): DecisionLineage {
  const d = rec(body);
  if (!Array.isArray(d.steps)) throw ApiError.contractDrift("risk.lineage: no steps list");
  const steps = d.steps.flatMap((v): LineageStep[] => {
    const s = rec(v);
    const step = str(s.step);
    const label = str(s.label);
    if (!step || !label) return [];
    const status = STATUSES.includes(s.status as LineageStatus) ? (s.status as LineageStatus) : "not_recorded";
    const ref = Array.isArray(s.ref) ? s.ref.map(String).join(", ") || null : s.ref == null ? null : String(s.ref);
    return [{ step, label, status, detail: str(s.detail) ?? "", ref, backlog: str(s.backlog) }];
  });
  return { decisionId: str(d.decision_id) ?? "", steps, recorded: steps.filter((s) => s.status === "recorded").length, replayable: d.replayable === true };
}

export function useDecisionLineage(id: string) {
  const profile = useImpersonationStore((st) => st.profileId);
  return useQuery<DecisionLineage>({
    queryKey: ["copilot", "fnolab", "lineage", profile ?? "self", id],
    staleTime: 60_000,
    retry: false,
    queryFn: async ({ signal }) => readLineage((await http({ path: `/api/risk/decisions/${encodeURIComponent(id)}/lineage`, signal, noRetry: true })).data),
  });
}

export type DecisionReplay =
  | { replayable: false; reason: string }
  | {
      replayable: true; match: boolean; outcomeThen: string | null; outcomeNow: string | null;
      reasonsThen: string[]; reasonsNow: string[]; inputsHashMatch: boolean; snapshotHashMatch: boolean;
      policyThen: string | null; policyNow: string | null; capitalThen: number | null; capitalNow: number | null;
      differences: string[]; replayedOn: string | null;
    };

const strings = (v: unknown): string[] => (Array.isArray(v) ? v.map(String) : []);

export function readReplay(body: unknown): DecisionReplay {
  const d = rec(body);
  if (d.replayable === false) return { replayable: false, reason: str(d.reason) ?? "The server gave no reason." };
  if (d.replayable !== true || typeof d.match !== "boolean") throw ApiError.contractDrift("risk.replay: no replayable/match");
  return {
    replayable: true, match: d.match, outcomeThen: str(d.outcome_then), outcomeNow: str(d.outcome_now),
    reasonsThen: strings(d.reasons_then), reasonsNow: strings(d.reasons_now),
    inputsHashMatch: d.inputs_hash_match === true, snapshotHashMatch: d.snapshot_hash_match === true,
    policyThen: str(d.policy_version_then), policyNow: str(d.policy_version_now),
    capitalThen: num(d.capital_at_risk_then), capitalNow: num(d.capital_at_risk_now),
    differences: strings(d.differences), replayedOn: str(d.replayed_on),
  };
}

/** POST because the server computes on demand; it writes nothing. */
export function useReplayDecision() {
  return useMutation<DecisionReplay, Error, string>({
    mutationFn: async (id) => readReplay((await http({ method: "POST", path: `/api/risk/decisions/${encodeURIComponent(id)}/replay`, noRetry: true })).data),
  });
}
