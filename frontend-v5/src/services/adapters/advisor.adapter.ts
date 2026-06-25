/**
 * Advisor + MFD adapter — REAL backend (backend/routes/advisor.py + mfd.py).
 *
 * Card endpoints (/advisor/today, /aum, /underperformers, /rebalance) return
 * flat `rows[]` envelopes; /mfd/profiles returns { workspace, profiles, count }.
 * Contracts in advisor.contract.ts mirror the running handlers exactly.
 */
import { http } from "@/services/api/http";
import { ApiError } from "@/services/api/errors";
import {
  ClientProfileC,
  ProfilesListRes,
  AdvisorTodayRes,
  AdvisorAumRes,
  AdvisorUnderperformersRes,
  AdvisorRebalanceRes,
  MfdWorkspaceC,
  type ClientProfileC as ClientProfile,
  type ProfilesListRes as ProfilesList,
  type AdvisorTodayRes as TodayRes,
  type AdvisorAumRes as AumRes,
  type AdvisorUnderperformersRes as UnderRes,
  type AdvisorRebalanceRes as RebalanceRes,
  type MfdWorkspaceC as Workspace,
} from "@/services/contracts/advisor.contract";

export interface AdvisorAdapter {
  today(limit?: number): Promise<TodayRes>;
  aum(limit?: number): Promise<AumRes>;
  underperformers(gapPct?: number, benchmark?: string): Promise<UnderRes>;
  rebalance(gapPp?: number): Promise<RebalanceRes>;

  workspaceGet(): Promise<Workspace>;
  workspaceUpdate(body: Partial<Workspace>): Promise<Workspace>;

  /** GET /api/mfd/profiles → { workspace, profiles } (the advisor book). */
  listProfiles(includeSelf?: boolean): Promise<ProfilesList>;
  createProfile(body: { name: string; email?: string; mobile?: string; pan?: string; aum_rs?: number | null; tags?: string[] | null; notes?: string | null }): Promise<ClientProfile>;
  getProfile(profileId: string): Promise<unknown>;
  updateProfile(profileId: string, body: Record<string, unknown>): Promise<ClientProfile>;
  deleteProfile(profileId: string): Promise<{ ok: true }>;

  activate(profileId: string): Promise<{ ok: true; profile_id: string; name: string }>;
  deactivate(): Promise<{ ok: true }>;

  summary(): Promise<{ book_aum_rs: number; avg_health_score: number; needs_attention_count: number; actions_open_count: number; clients_total: number }>;
  sipBoard(state?: string, cycle?: string): Promise<{ cycle: string; queues: { failed: unknown[]; expiring: unknown[]; step_up: unknown[]; healthy: unknown[] } }>;
  sipBoardSummary(): Promise<{ monthly_inflow_rs: number; active_sips_count: number; failed_count: number; mandate_at_risk_count: number }>;

  refreshIndex(name: string): Promise<{ ok?: boolean; reason?: string }>;
}

export const realAdvisorAdapter: AdvisorAdapter = {
  async today(limit = 10) {
    const res = await http({ path: "/api/advisor/today", query: { limit } });
    const parsed = AdvisorTodayRes.safeParse(res.data);
    if (!parsed.success) throw ApiError.contractDrift(`advisor.today: ${parsed.error.message}`);
    return parsed.data;
  },
  async aum(limit = 10) {
    const res = await http({ path: "/api/advisor/aum", query: { limit } });
    const parsed = AdvisorAumRes.safeParse(res.data);
    if (!parsed.success) throw ApiError.contractDrift(`advisor.aum: ${parsed.error.message}`);
    return parsed.data;
  },
  async underperformers(gap_pct = 5, benchmark = "nifty_50") {
    const res = await http({ path: "/api/advisor/underperformers", query: { gap_pct, benchmark } });
    const parsed = AdvisorUnderperformersRes.safeParse(res.data);
    if (!parsed.success) throw ApiError.contractDrift(`advisor.underperformers: ${parsed.error.message}`);
    return parsed.data;
  },
  async rebalance(gap_pp = 10) {
    const res = await http({ path: "/api/advisor/rebalance", query: { gap_pp } });
    const parsed = AdvisorRebalanceRes.safeParse(res.data);
    if (!parsed.success) throw ApiError.contractDrift(`advisor.rebalance: ${parsed.error.message}`);
    return parsed.data;
  },

  async workspaceGet() {
    const res = await http({ path: "/api/mfd/workspace" });
    const parsed = MfdWorkspaceC.safeParse(res.data);
    if (!parsed.success) throw ApiError.contractDrift(`advisor.workspaceGet: ${parsed.error.message}`);
    return parsed.data;
  },
  async workspaceUpdate(body) {
    const res = await http({ method: "PATCH", path: "/api/mfd/workspace", body });
    const parsed = MfdWorkspaceC.safeParse(res.data);
    if (!parsed.success) throw ApiError.contractDrift(`advisor.workspaceUpdate: ${parsed.error.message}`);
    return parsed.data;
  },

  async listProfiles(include_self = true) {
    const res = await http({ path: "/api/mfd/profiles", query: { include_self } });
    const parsed = ProfilesListRes.safeParse(res.data);
    if (!parsed.success) throw ApiError.contractDrift(`advisor.listProfiles: ${parsed.error.message}`);
    return parsed.data;
  },
  async createProfile(body) {
    const res = await http({ method: "POST", path: "/api/mfd/profiles", body });
    const parsed = ClientProfileC.safeParse(res.data);
    if (!parsed.success) throw ApiError.contractDrift(`advisor.createProfile: ${parsed.error.message}`);
    return parsed.data;
  },
  async getProfile(profileId) {
    const res = await http({ path: `/api/mfd/profiles/${encodeURIComponent(profileId)}` });
    return res.data;
  },
  async updateProfile(profileId, body) {
    const res = await http({ method: "PATCH", path: `/api/mfd/profiles/${encodeURIComponent(profileId)}`, body });
    const parsed = ClientProfileC.safeParse(res.data);
    if (!parsed.success) throw ApiError.contractDrift(`advisor.updateProfile: ${parsed.error.message}`);
    return parsed.data;
  },
  async deleteProfile(profileId) {
    await http({ method: "DELETE", path: `/api/mfd/profiles/${encodeURIComponent(profileId)}` });
    return { ok: true };
  },

  async activate(profileId) {
    const res = await http({ method: "POST", path: `/api/mfd/profiles/${encodeURIComponent(profileId)}/activate` });
    const obj = res.data as { profile_id?: string; name?: string; active_profile_id?: string };
    return { ok: true, profile_id: obj.active_profile_id ?? obj.profile_id ?? profileId, name: obj.name ?? "" };
  },
  async deactivate() {
    await http({ method: "POST", path: "/api/mfd/profiles/deactivate" });
    return { ok: true };
  },

  async summary() {
    const res = await http({ path: "/api/advisor/summary" });
    const obj = res.data as { book_aum_rs?: number; avg_health_score?: number; needs_attention_count?: number; actions_open_count?: number; clients_total?: number };
    return {
      book_aum_rs:           obj.book_aum_rs ?? 0,
      avg_health_score:      obj.avg_health_score ?? 0,
      needs_attention_count: obj.needs_attention_count ?? 0,
      actions_open_count:    obj.actions_open_count ?? 0,
      clients_total:         obj.clients_total ?? 0,
    };
  },

  async sipBoard(state = "all", cycle = "current") {
    const res = await http({ path: "/api/advisor/sip-board", query: { state, cycle } });
    const obj = res.data as { cycle?: string; queues?: { failed?: unknown[]; expiring?: unknown[]; step_up?: unknown[]; healthy?: unknown[] } };
    return {
      cycle: obj.cycle ?? cycle,
      queues: {
        failed:   obj.queues?.failed   ?? [],
        expiring: obj.queues?.expiring ?? [],
        step_up:  obj.queues?.step_up  ?? [],
        healthy:  obj.queues?.healthy  ?? [],
      },
    };
  },

  async sipBoardSummary() {
    const res = await http({ path: "/api/advisor/sip-board/summary" });
    const obj = res.data as { monthly_inflow_rs?: number; active_sips_count?: number; failed_count?: number; mandate_at_risk_count?: number };
    return {
      monthly_inflow_rs:     obj.monthly_inflow_rs     ?? 0,
      active_sips_count:     obj.active_sips_count     ?? 0,
      failed_count:          obj.failed_count           ?? 0,
      mandate_at_risk_count: obj.mandate_at_risk_count ?? 0,
    };
  },

  // Admin-only benchmark cache refresh that backs the Underperformers card.
  async refreshIndex(name) {
    const res = await http({ method: "POST", path: "/api/index/refresh", query: { name } });
    return (res.data ?? {}) as { ok?: boolean; reason?: string };
  },
};
