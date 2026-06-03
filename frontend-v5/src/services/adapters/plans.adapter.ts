/**
 * Plans adapter — REAL backend (action-board.yaml v2.0.0).
 *
 * `GET /api/plans/active` returns the full `Plan` with actions array AND
 * counters in a single shape. No two-step fetch needed.
 */
import { http } from "@/services/api/http";
import { ApiError } from "@/services/api/errors";
import {
  PlanC,
  PlanActiveRes,
  PlanGenerateRes,
  PlanActionUpdateRes,
  PlanHealthProjectionRes,
  SignalsRes,
  type PlanActionC,
} from "@/services/contracts/plan.contract";
import type { Recommendation, RecAction, Severity, ExecutionPath, TaxImpact, ExpectedEffect } from "@/types/recommendation";

export interface PlansAdapter {
  getActive(): Promise<PlanC | null>;
  getPlan(planId: string): Promise<PlanC>;
  generate(): Promise<PlanC>;
  refresh(): Promise<PlanC>;
  savePreview(planId: string): Promise<{ planId: string; status: string }>;
  simulate(planId: string): Promise<{ before: Record<string, unknown>; after: Record<string, unknown>; improvements: string[] }>;
  healthProjection(): Promise<import("@/services/contracts/plan.contract").PlanHealthProjectionRes>;
  history(limit?: number, skip?: number): Promise<{ total: number; plans: PlanC[] }>;
  getRecommendations(sourceDomain?: string): Promise<Recommendation[]>;
  updateActionStatus(planId: string, actionId: string, status: "pending" | "done" | "skipped", note?: string): Promise<import("@/services/contracts/plan.contract").PlanActionUpdateRes>;
  submitActionFeedback(planId: string, actionId: string, useful: boolean, comment?: string): Promise<{ ok: true }>;
  archiveActive(): Promise<{ ok: true; planId: string }>;
  generateSignals(): Promise<import("@/services/contracts/plan.contract").SignalsRes>;
  refreshFundamentals(): Promise<{ holdingsRefreshed: number; refreshedAt: string }>;
}

export const realPlansAdapter: PlansAdapter = {
  async getActive() {
    const res = await http({ path: "/api/plans/active" });
    const parsed = PlanActiveRes.safeParse(res.data);
    if (!parsed.success) throw ApiError.contractDrift(`plans.active: ${parsed.error.message}`);
    const plan = parsed.data.plan;
    if (plan) {
      // Backend may return total_actions/completed_actions/pending_actions
      const raw = plan as Record<string, unknown>;
      if (plan.actions_total == null && raw.total_actions != null) plan.actions_total = Number(raw.total_actions);
      if (plan.actions_done == null && raw.completed_actions != null) plan.actions_done = Number(raw.completed_actions);
      if (plan.actions_pending == null && raw.pending_actions != null) plan.actions_pending = Number(raw.pending_actions);
    }
    return plan;
  },

  async getPlan(planId) {
    const res = await http({ path: `/api/plans/${encodeURIComponent(planId)}` });
    const parsed = PlanC.safeParse(res.data);
    if (!parsed.success) throw ApiError.contractDrift(`plans.getPlan: ${parsed.error.message}`);
    return parsed.data;
  },

  async generate() {
    const res = await http({ method: "POST", path: "/api/plans/generate" });
    const parsed = PlanGenerateRes.safeParse(res.data);
    if (!parsed.success) throw ApiError.contractDrift(`plans.generate: ${parsed.error.message}`);
    return parsed.data.plan;
  },

  async refresh() {
    const res = await http({ method: "POST", path: "/api/plans/refresh" });
    const flat = PlanC.safeParse(res.data);
    if (flat.success) return flat.data;
    const wrapped = PlanGenerateRes.safeParse(res.data);
    if (wrapped.success) return wrapped.data.plan;
    throw ApiError.contractDrift(`plans.refresh: ${flat.error.message}`);
  },

  async savePreview(planId) {
    const res = await http({ method: "POST", path: `/api/plans/${encodeURIComponent(planId)}/save` });
    const obj = res.data as { plan_id?: string; status?: string };
    return { planId: obj.plan_id ?? planId, status: obj.status ?? "active" };
  },

  async simulate(planId) {
    const res = await http({ method: "POST", path: `/api/plans/${encodeURIComponent(planId)}/simulate` });
    const obj = res.data as { before?: Record<string, unknown>; after?: Record<string, unknown>; improvements?: string[] };
    return { before: obj.before ?? {}, after: obj.after ?? {}, improvements: obj.improvements ?? [] };
  },

  async healthProjection() {
    const res = await http({ path: "/api/plans/active/health-projection" });
    const parsed = PlanHealthProjectionRes.safeParse(res.data);
    if (!parsed.success) throw ApiError.contractDrift(`plans.healthProjection: ${parsed.error.message}`);
    return parsed.data;
  },

  async history(limit = 10, skip = 0) {
    const res = await http({ path: "/api/plans/history", query: { limit, skip } });
    const obj = res.data as { total?: number; plans?: unknown[] };
    return {
      total: obj.total ?? 0,
      plans: (obj.plans ?? []).map((p) => PlanC.parse(p)),
    };
  },

  async getRecommendations(_sourceDomain) {
    const plan = await this.getActive();
    if (!plan?.actions) return [];
    return plan.actions.map(mapActionToRecommendation);
  },

  async updateActionStatus(planId, actionId, status, completion_note) {
    const res = await http({
      method: "PATCH",
      path: `/api/plans/${encodeURIComponent(planId)}/actions/${encodeURIComponent(actionId)}`,
      body: { status, completion_note },
    });
    const parsed = PlanActionUpdateRes.safeParse(res.data);
    if (!parsed.success) throw ApiError.contractDrift(`plans.updateActionStatus: ${parsed.error.message}`);
    return parsed.data;
  },

  async submitActionFeedback(planId, actionId, useful, comment) {
    await http({
      method: "PATCH",
      path: `/api/plans/${encodeURIComponent(planId)}/actions/${encodeURIComponent(actionId)}/feedback`,
      body: { useful, comment },
    });
    return { ok: true };
  },

  async archiveActive() {
    const res = await http({ method: "DELETE", path: "/api/plans/active" });
    const obj = res.data as { plan_id?: string };
    return { ok: true, planId: obj.plan_id ?? "" };
  },

  async generateSignals() {
    const res = await http({ path: "/api/signals/generate" });
    const parsed = SignalsRes.safeParse(res.data);
    if (!parsed.success) throw ApiError.contractDrift(`signals.generate: ${parsed.error.message}`);
    return parsed.data;
  },

  async refreshFundamentals() {
    const res = await http({ method: "POST", path: "/api/plans/refresh-fundamentals" });
    const obj = res.data as { holdings_refreshed?: number; refreshed_at?: string };
    return {
      holdingsRefreshed: obj.holdings_refreshed ?? 0,
      refreshedAt: obj.refreshed_at ?? new Date().toISOString(),
    };
  },
};

/** Plan action (backend) → Recommendation card (UI) using PRD §12 field names. */
function mapActionToRecommendation(a: PlanActionC): Recommendation {
  // `action` field (new name) takes priority; fall back to `action_type` (legacy)
  const rawAction = String((a as Record<string, unknown>)["action"] ?? a.action_type ?? "").toUpperCase();
  const recAction = normaliseAction(rawAction);

  const displayName = a.holding_name ?? a.asset_name ?? "";
  const at = rawAction.toLowerCase();

  // `magnitude` (new name) takes priority; fall back to `amount_rs` (legacy)
  const magnitude = (a as Record<string, unknown>)["magnitude"] as number | undefined
    ?? a.amount_rs;

  // `execution` (new name) takes priority; fall back to `execution_path` (legacy)
  const execution = ((a as Record<string, unknown>)["execution"] as ExecutionPath | undefined)
    ?? (a.execution_path as ExecutionPath | undefined);

  const severity = (a.severity as Severity | undefined) ?? "minor";
  const taxImpact = (a as Record<string, unknown>)["tax_impact"] as TaxImpact | undefined;
  const expectedEffect = (a as Record<string, unknown>)["expected_effect"] as ExpectedEffect | undefined;

  return {
    id: (a as Record<string, unknown>)["id"] as string ?? a.action_id,
    action: recAction,
    title: displayName ? `${verbLabel(at)} ${displayName}` : verbLabel(at),
    reason: a.reason_text ?? a.rationale ?? "",
    suggestedAction: a.suggested_alternative
      ? `${verbLabel(at)} → ${a.suggested_alternative}`
      : verbLabel(at),
    severity,
    execution,
    magnitude,
    taxImpact,
    requiresConfirmation: a.requires_confirmation,
    expectedEffect,
    confidence: (a as Record<string, unknown>)["confidence"] as Recommendation["confidence"] | undefined,
    convictionText: (a as Record<string, unknown>)["conviction_text"] as string | null | undefined,
    confidenceTier: (a as Record<string, unknown>)["confidence_tier"] as Recommendation["confidenceTier"],
    confidenceLabel: (a as Record<string, unknown>)["confidence_label"] as string | null | undefined,
    planConfidenceScore: (a as Record<string, unknown>)["plan_confidence_score"] as number | null | undefined,
    deferReason: (a as Record<string, unknown>)["defer_reason"] as string | null | undefined,
    executionDate: (a as Record<string, unknown>)["execution_date"] as string | null | undefined,
  };
}

function normaliseAction(raw: string): RecAction {
  switch (raw) {
    case "EXIT":  case "SELL":  case "REDUCE": return "EXIT";
    case "TRIM":  case "SIP_DECREASE":         return "TRIM";
    case "CONSOLIDATE":                         return "CONSOLIDATE";
    case "ADD":   case "BUY":   case "SIP_INCREASE": return "ADD";
    case "REDIRECT":                            return "REDIRECT";
    case "DIVERSIFY":                           return "DIVERSIFY";
    case "HOLD":  case "KEEP":  case "SWITCH":  return "HOLD";
    default:                                    return "ADD";
  }
}

function verbLabel(at: string): string {
  const lower = at.toLowerCase();
  switch (lower) {
    case "sell":  case "exit":   return "Sell";
    case "buy":   case "add":    return "Buy";
    case "switch":               return "Switch";
    case "sip_increase":         return "Increase SIP in";
    case "sip_decrease":         return "Decrease SIP in";
    case "hold":  case "keep":   return "Hold";
    case "trim":  case "reduce": return "Reduce";
    default: return at;
  }
}
