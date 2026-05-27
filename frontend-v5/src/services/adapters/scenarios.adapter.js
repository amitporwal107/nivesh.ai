/**
 * Scenarios adapter — REAL backend (action-board.yaml v2.0.0).
 *
 * Full surface: suggest · simulate · rebalance-plan · save · saved list ·
 * saved delete · apply · pending list · pending delete · pending complete.
 *
 * Simulate / rebalance-plan accept ALLOCATION TARGETS (target_equity, etc.)
 * — not weight changes per holding. This reverts an earlier mis-correction.
 */
import { http } from "@/services/api/http";
import { ApiError } from "@/services/api/errors";
import { ScenarioSuggestRes, ScenarioSimulateReqC, ScenarioSimulateRes, RebalancePlanRes, SavedScenariosRes, PendingPlansRes, } from "@/services/contracts/scenarios.contract";
export const realScenariosAdapter = {
    async suggest() {
        const res = await http({ path: "/api/scenarios/suggest" });
        const parsed = ScenarioSuggestRes.safeParse(res.data);
        if (!parsed.success)
            throw ApiError.contractDrift(`scenarios.suggest: ${parsed.error.message}`);
        return parsed.data.scenarios.map((s) => ({
            id: s.scenario_id,
            name: s.name,
            description: s.description,
            healthDelta: s.estimated_health_delta,
            savings: s.annual_savings_rs ?? null,
            complexity: s.complexity,
        }));
    },
    async simulate(body) {
        const req = ScenarioSimulateReqC.parse(body);
        const res = await http({ method: "POST", path: "/api/scenarios/simulate", body: req });
        const parsed = ScenarioSimulateRes.safeParse(res.data);
        if (!parsed.success)
            throw ApiError.contractDrift(`scenarios.simulate: ${parsed.error.message}`);
        return parsed.data;
    },
    async rebalancePlan(body) {
        const req = ScenarioSimulateReqC.parse(body);
        const res = await http({ method: "POST", path: "/api/scenarios/rebalance-plan", body: req });
        const parsed = RebalancePlanRes.safeParse(res.data);
        if (!parsed.success)
            throw ApiError.contractDrift(`scenarios.rebalancePlan: ${parsed.error.message}`);
        return parsed.data;
    },
    async save(args) {
        const res = await http({ method: "POST", path: "/api/scenarios/save", body: args });
        const obj = res.data;
        return {
            saved_id: obj.saved_id ?? "",
            name: obj.name ?? args.name,
            saved_at: obj.saved_at ?? new Date().toISOString(),
        };
    },
    async listSaved() {
        const res = await http({ path: "/api/scenarios/saved" });
        const parsed = SavedScenariosRes.safeParse(res.data);
        if (!parsed.success)
            throw ApiError.contractDrift(`scenarios.listSaved: ${parsed.error.message}`);
        return parsed.data.saved_scenarios;
    },
    async deleteSaved(id) {
        await http({ method: "DELETE", path: `/api/scenarios/saved/${encodeURIComponent(id)}` });
    },
    async apply(args) {
        const res = await http({ method: "POST", path: "/api/scenarios/apply", body: args });
        const obj = res.data;
        return { pending_plan_id: obj.pending_plan_id ?? "" };
    },
    async listPending() {
        const res = await http({ path: "/api/scenarios/pending" });
        const parsed = PendingPlansRes.safeParse(res.data);
        if (!parsed.success)
            throw ApiError.contractDrift(`scenarios.listPending: ${parsed.error.message}`);
        return parsed.data.pending_plans;
    },
    async deletePending(planId) {
        await http({ method: "DELETE", path: `/api/scenarios/pending/${encodeURIComponent(planId)}` });
    },
    async completePending(planId) {
        const res = await http({ method: "POST", path: `/api/scenarios/pending/${encodeURIComponent(planId)}/complete` });
        const obj = res.data;
        return { completed_at: obj.completed_at ?? new Date().toISOString() };
    },
};
