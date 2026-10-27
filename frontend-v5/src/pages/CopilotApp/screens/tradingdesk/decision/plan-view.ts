/**
 * Phase 3 decision cards — ONE view of a TradePlan for every surface (Top 10 stock and F&O rows, the AI watchlist,
 * the lab's focus panel, the Strategy Builder and the paper-trade record).
 *
 *   GET /api/desk/trade-plans/{plan_id}   the plan by id (React Query key PLAN_KEY(id), shared by every view), its status
 *                                         DERIVED from your paper trades, the versions you may open, and your newest
 *                                         universal-risk decision on it (`risk_decision`, or null)  (usePlanResponse)
 *   GET /api/risk/profile                 the account's equity basis for "% of equity" and the limits version a decision
 *                                         was made under (risk-profile.ts useRiskProfile)
 *   GET /api/risk/status                  whether the kill switch / halt is on now, so a block they caused stops
 *                                         applying once cleared (risk-controls.ts useRiskStatus)
 *
 * Nothing here computes a level or a size. The card shows the plan's own levels and, for the size, the rupee risk, the
 * costs and the % of equity, the route's `account_size`: the universal risk service's OWN sizing of this plan for the
 * signed-in account (backend services/risk_gate/plan_sizing.py), so the size shown is the size a submission is approved at
 * when no portfolio limit binds. A plan with no account size (the route could not size it) shows no size, never the plan's
 * own input-based number.
 *
 * Which plan is shown. A row is built with a plan (its snapshot, the same content as the stored plan with that id).
 * When a NEWER version of the plan that you may open exists, every view shows the newest one and says it changed; when a
 * surface receives a plan that names the one it `supersedes`, the older plan's cached reading is refreshed, so every view
 * that still holds the older id learns of the change.
 *
 * Risk approval (the seam, `riskFor`). Phase 1 decides at SUBMISSION (no preview). A plan is "risk-approved" only on a
 * real ALLOW decision made under the risk limits in force now; with no decision it is "provisional". A REDUCE says the
 * size the service allows. A BLOCK disables the paper-trade action while it still applies (same session, same limits,
 * and, when only the kill switch or halt caused it, while that control is still on).
 *
 * The action gate (`planActionGate`) is the one answer to "may this be paper traded now", used by the card's action line
 * and by every button (PlanPaperTrade, IdeaActions, the Builder's PlanActions). Ideas, not recommendations; nothing here
 * places an order.
 */
import { useEffect, useMemo } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { http } from "@/services/api/http";
import { ApiError } from "@/services/api/errors";
import { num } from "../desk-data";
import { orderReasons, readReasons, useRiskStatus, type RiskReason } from "../risk-controls";
import { useRiskProfile } from "../risk-profile";
import { TradePlanSchema, planBlocker, type TradePlan } from "../strategy/trade-plan";

type Raw = Record<string, unknown>;
const rec = (v: unknown): Raw => (v && typeof v === "object" && !Array.isArray(v) ? (v as Raw) : {});
const str = (v: unknown): string | null => (typeof v === "string" && v.trim() ? v.trim() : null);

export const PLAN_KEY = (id: string) => ["copilot", "desk", "trade-plan", id] as const;
export const PLAN_KEY_ALL = ["copilot", "desk", "trade-plan"] as const;

// ── GET /api/desk/trade-plans/{id} ───────────────────────────────────────

export interface PlanVersion { planId: string; version: number | null; createdAt: string | null; revalidationOk: boolean | null; supersedes: string | null }

export interface PlanRiskDecision {
  decisionId: string;
  outcome: "allow" | "reduce" | "block";
  at: string | null;
  requestedQty: number | null;
  approvedQty: number | null;
  requestedLots: number | null;
  approvedLots: number | null;
  reasons: Array<RiskReason & { check: string | null }>;
  estimatedRisk: { gross: number | null; costs: number | null; gapStress: number | null; total: number | null } | null;
  policyVersion: string | null;
  limitsVersion: string | null;
}

export interface SizingReason { code: string | null; check: string | null; severity: string | null; message: string | null }

/** GET /trade-plans/{id} `account_size` (backend plan_sizing.size_for). */
export interface AccountSize {
  /** sized | not_confirmed | not_sizable | unavailable */
  status: string;
  reason: string | null;
  unit: string | null;
  quantity: number | null;
  lots: number | null;
  lotSize: number | null;
  requestedLots: number | null;
  estimatedRisk: { gross: number | null; costs: number | null; gapStress: number | null; total: number | null } | null;
  riskPctOfEquity: number | null;
  equityRs: number | null;
  perTradeBudgetRs: number | null;
  limitsVersion: string | null;
  binding: SizingReason[];
  factors: SizingReason[];
  blocking: SizingReason[];
  confirmSize: number | null;
  confirmReasons: SizingReason[];
  portfolioNote: string | null;
  portfolio: { outcome: string | null; sizeNow: number | null; reasons: SizingReason[]; remaining: Record<string, unknown> } | null;
  basis: string | null;
}

const readSizingReasons = (v: unknown): SizingReason[] => (Array.isArray(v) ? v : []).map((x) => {
  const r = rec(x);
  return { code: str(r.code), check: str(r.check), severity: str(r.severity), message: str(r.message) ?? str(r.code) };
});

export function readAccountSize(v: unknown): AccountSize | null {
  const d = rec(v);
  const status = str(d.status);
  if (!status) return null;
  const est = rec(d.estimated_risk_rs);
  const pf = rec(d.portfolio);
  return {
    status, reason: str(d.reason), unit: str(d.unit), quantity: num(d.quantity), lots: num(d.lots), lotSize: num(d.lot_size),
    requestedLots: num(d.requested_lots),
    estimatedRisk: Object.keys(est).length ? { gross: num(est.gross), costs: num(est.costs), gapStress: num(est.gap_stress), total: num(est.total) } : null,
    riskPctOfEquity: num(d.risk_pct_of_equity), equityRs: num(d.equity_rs), perTradeBudgetRs: num(d.per_trade_budget_rs),
    limitsVersion: str(d.limits_version),
    binding: readSizingReasons(d.binding), factors: readSizingReasons(d.factors), blocking: readSizingReasons(d.blocking),
    confirmSize: num(d.confirm_size), confirmReasons: readSizingReasons(d.confirm_reasons),
    portfolioNote: str(d.portfolio_note),
    portfolio: Object.keys(pf).length ? { outcome: str(pf.outcome), sizeNow: num(pf.size_now), reasons: readSizingReasons(pf.reasons), remaining: rec(pf.remaining) } : null,
    basis: str(d.basis),
  };
}

export interface PlanResponse {
  plan: TradePlan;
  /** proposed | approved | triggered | open | closed | rejected, derived from your trades. */
  status: string | null;
  versions: PlanVersion[];
  riskDecision: PlanRiskDecision | null;
  riskBasis: string | null;
  accountSize: AccountSize | null;
}

export function readRiskDecision(v: unknown): PlanRiskDecision | null {
  const d = rec(v);
  const outcome = str(d.outcome);
  const id = str(d.decision_id);
  if (!id || (outcome !== "allow" && outcome !== "reduce" && outcome !== "block")) return null;
  const raw = Array.isArray(d.reasons) ? d.reasons : [];
  const reasons = orderReasons(readReasons(raw)).map((r) => ({ ...r, check: str(rec(raw.find((x) => rec(x).code === r.code)).check) }));
  const est = rec(d.estimated_risk_rs);
  return {
    decisionId: id, outcome, at: str(d.at),
    requestedQty: num(d.requested_qty), approvedQty: num(d.approved_qty), requestedLots: num(d.requested_lots), approvedLots: num(d.approved_lots),
    reasons,
    estimatedRisk: Object.keys(est).length ? { gross: num(est.gross), costs: num(est.costs), gapStress: num(est.gap_stress), total: num(est.total) } : null,
    policyVersion: str(d.policy_version), limitsVersion: str(d.limits_version),
  };
}

/** The route's answer, or null when it is not a plan answer (an older route, a mocked `{}`): the row's own copy stands. */
export function readPlanResponse(body: unknown): PlanResponse | null {
  const d = rec(body);
  const parsed = TradePlanSchema.safeParse(d.plan);
  if (!parsed.success) return null;
  const versions = (Array.isArray(d.versions) ? d.versions : []).flatMap((x): PlanVersion[] => {
    const v = rec(x);
    const id = str(v.plan_id);
    return id ? [{ planId: id, version: num(v.version), createdAt: str(v.created_at), revalidationOk: typeof v.revalidation_ok === "boolean" ? v.revalidation_ok : null, supersedes: str(v.supersedes) }] : [];
  });
  return { plan: parsed.data, status: str(rec(d.lifecycle).status), versions, riskDecision: readRiskDecision(d.risk_decision),
    riskBasis: str(d.risk_decision_basis), accountSize: readAccountSize(d.account_size) };
}

export function usePlanResponse(id: string | null | undefined) {
  return useQuery<PlanResponse | null>({
    queryKey: PLAN_KEY(id ?? "none"),
    enabled: !!id,
    staleTime: 60_000,
    refetchOnWindowFocus: false,
    retry: (n, e) => !(e instanceof ApiError && (e.status === 404 || e.status === 401 || e.status === 403)) && n < 1,
    queryFn: async ({ signal }) => readPlanResponse((await http({ path: `/api/desk/trade-plans/${encodeURIComponent(id as string)}`, signal, noRetry: true })).data),
  });
}

// ── status ────────────────────────────────────────────────────────────────

export type CardStatus = "watch" | "eligible" | "rejected" | "triggered" | "open" | "closed" | "no_setup";

export const STATUS_TEXT: Record<CardStatus, string> = {
  watch: "Watch", eligible: "Eligible", rejected: "Rejected", triggered: "Triggered", open: "Open", closed: "Closed", no_setup: "No setup",
};

/** The lifecycle's status when a trade cites the plan (approved = a paper trade waits for its entry), else the plan's own
 *  proposed state: WAIT_FOR_CONFIRMATION is "watch", TRADE_ELIGIBLE "eligible". */
export function cardStatus(tp: TradePlan, derived: string | null): CardStatus {
  if (derived === "triggered" || derived === "open" || derived === "closed" || derived === "rejected") return derived;
  if (derived === "approved") return "eligible";
  const st = tp.eligibility.state;
  if (st === "REJECTED") return "rejected";
  if (st === "WAIT_FOR_CONFIRMATION") return "watch";
  if (st === "TRADE_ELIGIBLE") return "eligible";
  return "no_setup";
}

// ── equity (GET /api/risk/profile) ───────────────────────────────────────

export interface EquityBasis { rs: number | null; basis: string | null; label: string | null; effectiveFrom: string | null; limitsVersion: string | null; error: string | null }

function useEquity(): EquityBasis {
  const q = useRiskProfile();
  return useMemo(() => {
    if (q.isError) return { rs: null, basis: null, label: null, effectiveFrom: null, limitsVersion: null, error: "the risk profile could not be read" };
    const v = q.data;
    if (!v) return { rs: null, basis: null, label: null, effectiveFrom: null, limitsVersion: null, error: q.isPending ? "reading the risk profile" : "the risk profile could not be read" };
    return {
      rs: v.live?.equityRs ?? null,
      basis: v.profile.capitalBasisText,
      label: v.profile.startingCapitalLabel,
      effectiveFrom: v.profile.effectiveFrom,
      limitsVersion: v.profile.limitsVersion,
      error: v.live ? (v.live.equityRs == null ? (v.live.unknownReasons[0] ?? "paper equity is unknown") : null) : v.liveError ?? "the live equity basis was not sent",
    };
  }, [q.data, q.isError, q.isPending]);
}

// ── the risk seam ─────────────────────────────────────────────────────────

export type RiskState = "provisional" | "approved" | "reduce" | "block";

export interface RiskView {
  state: RiskState;
  decision: PlanRiskDecision | null;
  /** True when a block decision still applies (and so disables the paper-trade action). */
  blocking: boolean;
  /** Why the decision does not decide the badge any more (an older session, another limits version, a control cleared). */
  staleWhy: string | null;
}

const IST_DAY = (iso: string | null | undefined): string | null => {
  if (!iso) return null;
  const t = new Date(iso);
  return Number.isNaN(t.getTime()) ? null : t.toLocaleDateString("en-CA", { timeZone: "Asia/Kolkata" });
};

/**
 * THE seam between a plan and the universal risk service (Phase 1, #363). Only a real decision on a submission that cited
 * the plan counts; with none the plan is provisional. `now` and the current limits version decide whether the decision
 * still applies.
 */
export function riskFor(decision: PlanRiskDecision | null, ctx: { limitsVersion: string | null; controlsOn: boolean | null; now?: Date }): RiskView {
  if (!decision) return { state: "provisional", decision: null, blocking: false, staleWhy: null };
  const nowDay = IST_DAY((ctx.now ?? new Date()).toISOString());
  let staleWhy: string | null = null;
  if (ctx.limitsVersion && decision.limitsVersion && ctx.limitsVersion !== decision.limitsVersion) {
    staleWhy = `decided under risk limits ${decision.limitsVersion}; your risk profile has changed since (now ${ctx.limitsVersion})`;
  } else if (decision.outcome === "block" && IST_DAY(decision.at) !== nowDay) {
    staleWhy = "decided in an earlier session";
  } else if (decision.outcome === "block") {
    const blockingReasons = decision.reasons.filter((r) => r.severity == null || ["block", "halt", "reject", "defer"].includes(r.severity));
    const onlyControls = blockingReasons.length > 0 && blockingReasons.every((r) => r.check === "controls");
    if (onlyControls && ctx.controlsOn === false) staleWhy = "the kill switch or halt that caused it is now off";
  }
  if (staleWhy) return { state: "provisional", decision, blocking: false, staleWhy };
  if (decision.outcome === "allow") return { state: "approved", decision, blocking: false, staleWhy: null };
  if (decision.outcome === "reduce") return { state: "reduce", decision, blocking: false, staleWhy: null };
  return { state: "block", decision, blocking: true, staleWhy: null };
}

// ── the view ──────────────────────────────────────────────────────────────

export interface PlanView {
  /** The plan the row was built with. */
  rowPlan: TradePlan;
  /** The plan shown: the newest version you may open (the row's own when none is newer or the store was not read). */
  plan: TradePlan;
  /** Set when `plan` is a newer version than the row's. */
  changed: { fromVersion: number | null; toVersion: number | null; fromId: string; toId: string } | null;
  status: CardStatus;
  /** The derived lifecycle status was read from the store (else the plan's own proposed state). */
  statusFromLifecycle: boolean;
  /** "read" | "pending" | "unread" — whether GET /trade-plans/{id} answered with the plan. */
  store: "read" | "pending" | "unread";
  risk: RiskView;
  riskBasis: string | null;
  equity: EquityBasis;
  /** The risk service's sizing of the shown plan for this account (null: the route did not size it). */
  accountSize: AccountSize | null;
  /** Why the paper-trade action is off, or null when the backend would take the request (planActionGate). */
  gate: string | null;
}

/** Why a paper trade of this view cannot be submitted now, or null. The plan's own eligibility first (planBlocker: not
 *  stored, rejected, no setup), then a changed plan the row cannot record, then a risk block that still applies. */
const why = (rs: SizingReason[]) => rs.filter((r) => r.severity !== "info").map((r) => r.message).filter(Boolean).slice(0, 2).join("; ");

export function planActionGate(v: Pick<PlanView, "plan" | "changed" | "risk" | "accountSize">, opts: { recordsShownPlan: boolean }): string | null {
  const own = planBlocker(v.plan);
  if (own) return own;
  if (v.changed && !opts.recordsShownPlan) {
    return `This plan changed after the row was built (version ${v.changed.toVersion ?? "?"} replaces version ${v.changed.fromVersion ?? "?"}). Rank again or rebuild to record the current version.`;
  }
  const a = v.accountSize;
  if (a?.status === "not_sizable") return `The risk service would refuse this plan for your account${why(a.blocking) ? `: ${why(a.blocking)}` : "."}`;
  if (a?.status === "not_confirmed") {
    return `The risk service would not take this size as it is: it cuts it again${a.confirmSize != null ? ` to ${a.confirmSize}` : ""}${why(a.confirmReasons) ? ` (${why(a.confirmReasons)})` : ""}. Nothing can be recorded at a size it allows until that is fixed.`;
  }
  if (a?.status === "sized" && a.lots != null && a.requestedLots != null && a.lots < a.requestedLots) {
    return `Your per-trade budget allows ${a.lots} lot(s) per leg; this row records ${a.requestedLots}, which the risk service would refuse.`;
  }
  if (v.risk.blocking && v.risk.decision) {
    const why = v.risk.decision.reasons.filter((r) => r.severity !== "info").map((r) => r.message).slice(0, 2).join("; ");
    return `Blocked by the risk service${why ? `: ${why}` : ""}. Nothing can be recorded until that changes.`;
  }
  return null;
}

/**
 * The view of a row's plan. `recordsShownPlan`: the surface's paper trade is built from the plan alone (a share trade,
 * PlanPaperTrade), so it can record whichever version is shown; a structure or a Builder candidate records its own legs
 * and cannot.
 */
export function usePlanView(rowPlan: TradePlan | null | undefined, opts: { recordsShownPlan?: boolean } = {}): PlanView | null {
  const qc = useQueryClient();
  const id = rowPlan?.plan_id ?? null;
  const own = usePlanResponse(id);
  const newestId = useMemo(() => {
    const vs = own.data?.versions ?? [];
    const last = vs.length ? vs[vs.length - 1] : null;
    return last && last.planId !== id ? last.planId : null;
  }, [own.data, id]);
  const newer = usePlanResponse(newestId);
  const equity = useEquity();
  const status = useRiskStatus();
  const supersedes = (rowPlan as { supersedes?: unknown } | null | undefined)?.supersedes;

  // A plan that names the one it supersedes: every view still holding the older plan reads it again and learns of this one.
  useEffect(() => {
    if (typeof supersedes === "string" && supersedes) void qc.invalidateQueries({ queryKey: PLAN_KEY(supersedes) });
  }, [qc, supersedes]);

  return useMemo(() => {
    if (!rowPlan) return null;
    const shownResp = newestId && newer.data ? newer.data : own.data ?? null;
    const plan = shownResp?.plan ?? rowPlan;
    const changed = newestId && newer.data
      ? { fromVersion: own.data?.plan.version ?? rowPlan.version ?? null, toVersion: newer.data.plan.version ?? null, fromId: rowPlan.plan_id, toId: newer.data.plan.plan_id }
      : null;
    const store = own.data ? "read" : own.isPending && !!id ? "pending" : "unread";
    const risk = riskFor(shownResp?.riskDecision ?? null, {
      limitsVersion: equity.limitsVersion, controlsOn: status.data?.known ? status.data.killSwitch || status.data.halted : null,
    });
    const accountSize = shownResp?.accountSize ?? null;
    const base = { plan, changed, risk, accountSize };
    return {
      rowPlan, plan, changed,
      status: cardStatus(plan, shownResp?.status ?? null),
      statusFromLifecycle: !!shownResp?.status && shownResp.status !== "proposed",
      store,
      risk,
      riskBasis: shownResp?.riskBasis ?? null,
      equity,
      accountSize,
      gate: planActionGate(base, { recordsShownPlan: !!opts.recordsShownPlan }),
    };
  }, [rowPlan, newestId, newer.data, own.data, own.isPending, id, equity, status.data, opts.recordsShownPlan]);
}
