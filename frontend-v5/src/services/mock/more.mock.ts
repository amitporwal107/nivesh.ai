/**
 * Mock adapters for advisor / mfd / chat / cas-upload — minimal stubs.
 */
import type { AdvisorAdapter } from "../adapters/advisor.adapter";
import type { MfdAdapter } from "../adapters/mfd.adapter";
import type { ChatAdapter } from "../adapters/chat.adapter";
import type { CasUploadAdapter } from "../adapters/cas-upload.adapter";

const delay = (ms: number) => new Promise<void>((r) => setTimeout(r, ms));

export const mockAdvisorAdapter: AdvisorAdapter = {
  async today()           { await delay(220); return { generated_at: new Date().toISOString(), high_priority: [], medium_priority: [], low_priority: [], summary: { total_clients: 87, high: 4, medium: 12, low: 71 } }; },
  async aum()             { await delay(220); return { total_aum_rs: 6_42_00_000, clients: [] }; },
  async underperformers() { await delay(220); return { benchmark: "nifty_50", benchmark_xirr_pct: 14.2, gap_threshold_pct: 5, underperformers: [] }; },
  async rebalance()       { await delay(220); return { threshold_pp: 10, clients_needing_rebalance: 0, clients: [] }; },
  async workspaceGet()    { await delay(180); return { mode: "ADVISORY" }; },
  async workspaceUpdate(body) { await delay(220); return { mode: "ADVISORY", ...body }; },
  async listProfiles()    { await delay(280); return []; },
  async createProfile(body) { await delay(320); return { profile_id: "p_mock", name: body.name, email: body.email ?? null }; },
  async getProfile()      { await delay(180); return {}; },
  async updateProfile(_id, body) { await delay(220); return { profile_id: _id, name: "Mock", ...body }; },
  async deleteProfile()   { await delay(140); return { ok: true }; },
  async activate(profileId) { await delay(140); return { ok: true, profile_id: profileId, name: "Mock" }; },
  async deactivate()      { await delay(120); return { ok: true }; },
  async getNotes()        { await delay(180); return {}; },
  async saveNotes()       { await delay(180); return {}; },
  async taxSummary()      { await delay(220); return {}; },
  async portfolioTrend()  { await delay(220); return {}; },
  async summary() {
    await delay(220);
    return { book_aum_rs: 6_42_00_000, avg_health_score: 79, needs_attention_count: 4, actions_open_count: 12, clients_total: 87 };
  },
  async sipBoard() {
    await delay(260);
    return { cycle: "2026-05", queues: { failed: [], expiring: [], step_up: [], healthy: [] } };
  },
  async sipBoardSummary() {
    await delay(220);
    return { monthly_inflow_rs: 14_20_000, active_sips_count: 148, failed_count: 4, mandate_at_risk_count: 6 };
  },
};

export const mockMfdAdapter: MfdAdapter = {
  async listProfiles()    { await delay(280); return []; },
  async activateProfile() { await delay(140); return { ok: true }; },
  async deactivateProfile(){await delay(120); return { ok: true }; },
  async needsAttention()  { await delay(220); return []; },
  async callLog()         { await delay(220); return { call_log_id: "cl_mock", occurred_at: new Date().toISOString() }; },
  async sipNudge()        { await delay(220); return { nudge_id: "nd_mock", queued_at: new Date().toISOString() }; },
  async reviewPackGenerate(){ await delay(420); return { task_id: "rp_mock_task", status: "QUEUED", estimated_seconds: 15 }; },
  async reviewPackPoll()  { await delay(180); return { task_id: "rp_mock_task", status: "COMPLETED", download_url: "/mock/review-pack.pdf" }; },
};

export const mockChatAdapter: ChatAdapter = {
  async send(_message) { await delay(420); return { reply: "This is a mocked reply.", sessionId: "sess_mock" }; },
  async listSessions() { await delay(180); return []; },
  async createSession(){ await delay(180); return { id: "sess_mock" }; },
  async getSession()   { await delay(220); return { messages: [] }; },
  async suggestedPrompts() {
    await delay(120);
    return ["Why is my score 74?", "Which funds overlap most?", "How risky is my portfolio?", "What should I reduce first?"];
  },
};

export const mockCasUploadAdapter: CasUploadAdapter = {
  async getActivePortfolio() { await delay(220); return {}; },
  async uploadFile()         { await delay(420); return { message: "Uploaded", count: 0, holdings: [] }; },
  async getConnectToken()    { await delay(180); return { access_token: "mock-token", expires_in: 300 }; },
  async sdkCallback()        { await delay(380); return { imported: true }; },
  async importConnect()      { await delay(380); return { imported: true }; },
  async status()             { await delay(220); return { task_id: "upl_mock_1", status: "COMPLETED", progress: 100 }; },
  async latestTask()         { await delay(180); return { task_id: "upl_mock_1", status: "COMPLETED" }; },
  async upload()             { await delay(420); return { task_id: "upl_mock_1" }; },
};
