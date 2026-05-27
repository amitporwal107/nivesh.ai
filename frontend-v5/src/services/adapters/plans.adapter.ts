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
import type { Recommendation, RecAction } from "@/types/recommendation";

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
    return parsed.data.plan;
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

/**
 * Plan action (backend) → Recommendation card (UI).
 *   sell · switch · sip_decrease → REDUCE
 *   buy · sip_increase            → ADD
 *   hold                          → KEEP
 */
function mapActionToRecommendation(a: PlanActionC): Recommendation {
  const recAction: RecAction =
    a.action_type === "sell" || a.action_type === "switch" || a.action_type === "sip_decrease" ? "reduce" :
    a.action_type === "buy"  || a.action_type === "sip_increase" ? "add" :
    a.action_type === "hold" ? "keep" :
    "add";

  const annualSavingsRs = a.estimated_impact?.annual_savings_rs;
  const healthDelta = a.estimated_impact?.health_score_delta;

  return {
    id: a.action_id,
    action: recAction,
    title: a.holding_name ? `${verbLabel(String(a.action_type))} ${a.holding_name}` : verbLabel(String(a.action_type)),
    why: a.rationale ?? "",
    benefit: annualSavingsRs != null
      ? `Saves about ₹${Math.round(annualSavingsRs).toLocaleString("en-IN")} / year`
      : healthDelta != null
        ? `Lifts health score by ${healthDelta} points`
        : "Improves portfolio quality",
    riskImpact: "Neutral to lower",
    suggestedAction: a.suggested_alternative
      ? `${verbLabel(String(a.action_type))} → ${a.suggested_alternative}`
      : verbLabel(String(a.action_type)),
    estAnnualGain: annualSavingsRs != null ? annualSavingsRs * 100 : undefined,
    estHealthDelta: healthDelta ?? undefined,
  };
}

function verbLabel(at: string): string {
  switch (at) {
    case "sell": return "Sell";
    case "buy":  return "Buy";
    case "switch": return "Switch";
    case "sip_increase": return "Increase SIP in";
    case "sip_decrease": return "Decrease SIP in";
    case "hold": return "Hold";
    default: return at;
  }
}
