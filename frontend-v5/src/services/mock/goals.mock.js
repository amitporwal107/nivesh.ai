import { mockGoals } from "@/mock-data/goals";
const delay = (ms) => new Promise((r) => setTimeout(r, ms));
const toGoalC = (g) => ({
    goal_id: g.id,
    goal_type: "wealth",
    goal_name: g.name,
    target_amount_rs: g.targetAmount / 100,
    horizon_years: 10,
    monthly_sip_rs: g.monthlySip / 100,
    on_track_pct: g.progress,
    status: "active",
});
export const mockGoalsAdapter = {
    async list() {
        await delay(280);
        const goals = structuredClone(mockGoals);
        return {
            goals,
            totals: { total: goals.length, onTrack: goals.filter((g) => g.onTrack).length, atRisk: goals.filter((g) => !g.onTrack).length },
        };
    },
    async get() { await delay(180); return toGoalC(mockGoals[0]); },
    async create() { await delay(380); return structuredClone(mockGoals[0]); },
    async update() { await delay(220); return {}; },
    async archive() { await delay(180); return { ok: true }; },
    async getSnapshot() { await delay(180); return {}; },
    async upsertSnapshot(body) { await delay(220); return body; },
    async simulate() {
        await delay(420);
        return {
            goal_id: "goal-mock",
            success_probability_pct: 62,
            on_track: true,
            corpus_projections: { p10_rs: 100_000, p50_rs: 200_000, p90_rs: 300_000 },
        };
    },
    async whatIf() {
        await delay(220);
        return {
            goal_id: "goal-mock",
            what_if_params: {},
            current_on_track_pct: 0.62,
            what_if_on_track_pct: 0.78,
            corpus_projections: { p10_rs: 120_000, p50_rs: 230_000, p90_rs: 340_000 },
            persisted: false,
        };
    },
    async fundShortlist() {
        await delay(280);
        return { bucket: "large_cap", min_quality: 55, funds: [] };
    },
    async copilotAsk() { await delay(420); return { answer: "Mock answer." }; },
    async copilotHistory() { await delay(180); return []; },
};
