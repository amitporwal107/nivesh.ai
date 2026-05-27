/**
 * Goals adapter — REAL backend (goals.yaml v2.0.0).
 */
import { http } from "@/services/api/http";
import { ApiError } from "@/services/api/errors";
import { GoalC, GoalsListRes, GoalCreateReq, FinancialSnapshotC, MonteCarloRes, WhatIfReq, WhatIfRes, FundShortlistRes, } from "@/services/contracts/goal.contract";
import { mapGoals } from "@/services/mappers/goal.mapper";
export const realGoalsAdapter = {
    async list() {
        const res = await http({ path: "/api/goals" });
        const parsed = GoalsListRes.safeParse(res.data);
        if (!parsed.success)
            throw ApiError.contractDrift(`goals.list: ${parsed.error.message}`);
        return {
            goals: mapGoals(parsed.data.goals),
            totals: { total: parsed.data.total, onTrack: parsed.data.on_track, atRisk: parsed.data.at_risk },
        };
    },
    async get(goalId) {
        const res = await http({ path: `/api/goals/${encodeURIComponent(goalId)}` });
        const parsed = GoalC.safeParse(res.data);
        if (!parsed.success)
            throw ApiError.contractDrift(`goals.get: ${parsed.error.message}`);
        return parsed.data;
    },
    async create(input) {
        const body = GoalCreateReq.parse({
            goal_type: input.goal_type,
            goal_name: input.goal_name,
            target_amount_rs: input.target_amount_rs,
            horizon_years: input.horizon_years,
            priority: input.priority ?? "medium",
            inflation_pct: input.inflation_pct,
            current_corpus_rs: input.current_corpus_rs,
            monthly_sip_rs: input.monthly_sip_rs,
        });
        const res = await http({ method: "POST", path: "/api/goals", body });
        const parsed = GoalC.safeParse(res.data);
        if (!parsed.success)
            throw ApiError.contractDrift(`goals.create: ${parsed.error.message}`);
        return mapGoals([parsed.data])[0];
    },
    async update(goalId, body) {
        const res = await http({ method: "PATCH", path: `/api/goals/${encodeURIComponent(goalId)}`, body });
        return res.data;
    },
    async archive(goalId) {
        await http({ method: "DELETE", path: `/api/goals/${encodeURIComponent(goalId)}` });
        return { ok: true };
    },
    async getSnapshot() {
        const res = await http({ path: "/api/goals/snapshot" });
        if (res.data == null)
            return null;
        const parsed = FinancialSnapshotC.safeParse(res.data);
        return parsed.success ? parsed.data : null;
    },
    async upsertSnapshot(body) {
        const res = await http({ method: "PUT", path: "/api/goals/snapshot", body });
        const parsed = FinancialSnapshotC.safeParse(res.data);
        if (!parsed.success)
            throw ApiError.contractDrift(`goals.upsertSnapshot: ${parsed.error.message}`);
        return parsed.data;
    },
    async simulate(goalId) {
        const res = await http({ method: "POST", path: `/api/goals/${encodeURIComponent(goalId)}/simulate` });
        const parsed = MonteCarloRes.safeParse(res.data);
        if (!parsed.success)
            throw ApiError.contractDrift(`goals.simulate: ${parsed.error.message}`);
        return parsed.data;
    },
    async whatIf(goalId, body) {
        const req = WhatIfReq.parse(body);
        const res = await http({ method: "POST", path: `/api/goals/${encodeURIComponent(goalId)}/what-if`, body: req });
        const parsed = WhatIfRes.safeParse(res.data);
        if (!parsed.success)
            throw ApiError.contractDrift(`goals.whatIf: ${parsed.error.message}`);
        return parsed.data;
    },
    async fundShortlist(bucket, n = 15, min_quality = 55) {
        const res = await http({
            path: `/api/goals/fund-shortlist/${encodeURIComponent(bucket)}`,
            query: { n, min_quality },
        });
        const parsed = FundShortlistRes.safeParse(res.data);
        if (!parsed.success)
            throw ApiError.contractDrift(`goals.fundShortlist: ${parsed.error.message}`);
        return parsed.data;
    },
    async copilotAsk(goalId, query) {
        const res = await http({
            method: "POST",
            path: `/api/goals/${encodeURIComponent(goalId)}/copilot`,
            body: { query },
        });
        const obj = res.data;
        return { answer: obj.answer ?? "", engineOutput: obj.engine_output };
    },
    async copilotHistory(goalId) {
        const res = await http({ path: `/api/goals/${encodeURIComponent(goalId)}/copilot/history` });
        const obj = res.data;
        return obj.history ?? [];
    },
};
