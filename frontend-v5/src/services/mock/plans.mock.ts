/**
 * Mock plans adapter.
 */
import type { PlansAdapter } from "../adapters/plans.adapter";
import { mockRecommendations } from "@/mock-data/recommendations";

const delay = (ms: number) => new Promise<void>((r) => setTimeout(r, ms));

const stubPlan = {
  plan_id: "plan-mock-1",
  version: "v1",
  status: "active" as const,
  actions: [],
  created_at: new Date().toISOString(),
};

export const mockPlansAdapter: PlansAdapter = {
  async getActive()   { await delay(280); return stubPlan; },
  async getPlan()     { await delay(220); return stubPlan; },
  async generate()    { await delay(420); return stubPlan; },
  async refresh()     { await delay(360); return stubPlan; },
  async savePreview(planId) { await delay(180); return { planId, status: "active" }; },
  async simulate()    { await delay(320); return { before: {}, after: {}, improvements: [] }; },
  async healthProjection() {
    await delay(220);
    return { current_score: 74, projected_score: 82 };
  },
  async history()     { await delay(280); return { total: 1, plans: [stubPlan] }; },
  async getRecommendations(sourceDomain) {
    await delay(260);
    const all = structuredClone(mockRecommendations);
    if (!sourceDomain) return all;
    return all;
  },
  async updateActionStatus() {
    await delay(180);
    return { plan_id: "plan-mock-1", action_id: "act-mock", new_status: "done" };
  },
  async submitActionFeedback() { await delay(140); return { ok: true }; },
  async archiveActive()        { await delay(220); return { ok: true, planId: "plan-mock-1" }; },
  async generateSignals()      { await delay(280); return { signals: [] }; },
  async refreshFundamentals()  { await delay(320); return { holdingsRefreshed: 0, refreshedAt: new Date().toISOString() }; },
};
