/**
 * Advisor + MFD adapter — REAL backend (advisor.yaml v2.0.0).
 *
 * Key correction: /api/advisor/today returns bucketed
 * { high_priority, medium_priority, low_priority, summary } — NOT a flat list.
 */
import { http } from "@/services/api/http";
import { ApiError } from "@/services/api/errors";
import { ClientProfileC, ProfilesListRes, AdvisorTodayRes, AdvisorAumRes, AdvisorUnderperformersRes, AdvisorRebalanceRes, MfdWorkspaceC, } from "@/services/contracts/advisor.contract";
export const realAdvisorAdapter = {
    async today(limit = 100) {
        const res = await http({ path: "/api/advisor/today", query: { limit } });
        const parsed = AdvisorTodayRes.safeParse(res.data);
        if (!parsed.success)
            throw ApiError.contractDrift(`advisor.today: ${parsed.error.message}`);
        return parsed.data;
    },
    async aum(limit = 100) {
        const res = await http({ path: "/api/advisor/aum", query: { limit } });
        const parsed = AdvisorAumRes.safeParse(res.data);
        if (!parsed.success)
            throw ApiError.contractDrift(`advisor.aum: ${parsed.error.message}`);
        return parsed.data;
    },
    async underperformers(gap_pct = 5, benchmark = "nifty_50") {
        const res = await http({ path: "/api/advisor/underperformers", query: { gap_pct, benchmark } });
        const parsed = AdvisorUnderperformersRes.safeParse(res.data);
        if (!parsed.success)
            throw ApiError.contractDrift(`advisor.underperformers: ${parsed.error.message}`);
        return parsed.data;
    },
    async rebalance(gap_pp = 10) {
        const res = await http({ path: "/api/advisor/rebalance", query: { gap_pp } });
        const parsed = AdvisorRebalanceRes.safeParse(res.data);
        if (!parsed.success)
            throw ApiError.contractDrift(`advisor.rebalance: ${parsed.error.message}`);
        return parsed.data;
    },
    async workspaceGet() {
        const res = await http({ path: "/api/mfd/workspace" });
        const parsed = MfdWorkspaceC.safeParse(res.data);
        if (!parsed.success)
            throw ApiError.contractDrift(`advisor.workspaceGet: ${parsed.error.message}`);
        return parsed.data;
    },
    async workspaceUpdate(body) {
        const res = await http({ method: "PATCH", path: "/api/mfd/workspace", body });
        const parsed = MfdWorkspaceC.safeParse(res.data);
        if (!parsed.success)
            throw ApiError.contractDrift(`advisor.workspaceUpdate: ${parsed.error.message}`);
        return parsed.data;
    },
    async listProfiles(include_self = true) {
        const res = await http({ path: "/api/mfd/profiles", query: { include_self } });
        const parsed = ProfilesListRes.safeParse(res.data);
        if (!parsed.success)
            throw ApiError.contractDrift(`advisor.listProfiles: ${parsed.error.message}`);
        return parsed.data.profiles;
    },
    async createProfile(body) {
        const res = await http({ method: "POST", path: "/api/mfd/profiles", body });
        const parsed = ClientProfileC.safeParse(res.data);
        if (!parsed.success)
            throw ApiError.contractDrift(`advisor.createProfile: ${parsed.error.message}`);
        return parsed.data;
    },
    async getProfile(profileId) {
        const res = await http({ path: `/api/mfd/profiles/${encodeURIComponent(profileId)}` });
        return res.data;
    },
    async updateProfile(profileId, body) {
        const res = await http({ method: "PATCH", path: `/api/mfd/profiles/${encodeURIComponent(profileId)}`, body });
        const parsed = ClientProfileC.safeParse(res.data);
        if (!parsed.success)
            throw ApiError.contractDrift(`advisor.updateProfile: ${parsed.error.message}`);
        return parsed.data;
    },
    async deleteProfile(profileId) {
        await http({ method: "DELETE", path: `/api/mfd/profiles/${encodeURIComponent(profileId)}` });
        return { ok: true };
    },
    async activate(profileId) {
        const res = await http({ method: "POST", path: `/api/mfd/profiles/${encodeURIComponent(profileId)}/activate` });
        const obj = res.data;
        return { ok: true, profile_id: obj.profile_id ?? profileId, name: obj.name ?? "" };
    },
    async deactivate() {
        await http({ method: "POST", path: "/api/mfd/profiles/deactivate" });
        return { ok: true };
    },
    async getNotes(profileId) {
        const res = await http({ path: `/api/mfd/profiles/${encodeURIComponent(profileId)}/notes` });
        return res.data;
    },
    async saveNotes(profileId, body) {
        const res = await http({ method: "PUT", path: `/api/mfd/profiles/${encodeURIComponent(profileId)}/notes`, body });
        return res.data;
    },
    async taxSummary(profileId) {
        const res = await http({ path: `/api/mfd/profiles/${encodeURIComponent(profileId)}/tax-summary` });
        return res.data;
    },
    async portfolioTrend(profileId) {
        const res = await http({ path: `/api/mfd/profiles/${encodeURIComponent(profileId)}/portfolio-trend` });
        return res.data;
    },
    async summary() {
        const res = await http({ path: "/api/advisor/summary" });
        const obj = res.data;
        return {
            book_aum_rs: obj.book_aum_rs ?? 0,
            avg_health_score: obj.avg_health_score ?? 0,
            needs_attention_count: obj.needs_attention_count ?? 0,
            actions_open_count: obj.actions_open_count ?? 0,
            clients_total: obj.clients_total ?? 0,
        };
    },
    async sipBoard(state = "all", cycle = "current") {
        const res = await http({ path: "/api/advisor/sip-board", query: { state, cycle } });
        const obj = res.data;
        return {
            cycle: obj.cycle ?? cycle,
            queues: {
                failed: obj.queues?.failed ?? [],
                expiring: obj.queues?.expiring ?? [],
                step_up: obj.queues?.step_up ?? [],
                healthy: obj.queues?.healthy ?? [],
            },
        };
    },
    async sipBoardSummary() {
        const res = await http({ path: "/api/advisor/sip-board/summary" });
        const obj = res.data;
        return {
            monthly_inflow_rs: obj.monthly_inflow_rs ?? 0,
            active_sips_count: obj.active_sips_count ?? 0,
            failed_count: obj.failed_count ?? 0,
            mandate_at_risk_count: obj.mandate_at_risk_count ?? 0,
        };
    },
};
