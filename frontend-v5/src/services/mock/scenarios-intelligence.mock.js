const delay = (ms) => new Promise((r) => setTimeout(r, ms));
export const mockScenariosAdapter = {
    async suggest() {
        await delay(220);
        return [
            { id: "s_trim_financials", name: "Trim financials to 24%", description: "Lower bank-stock concentration", healthDelta: 4, savings: null, complexity: "low" },
            { id: "s_switch_direct", name: "Switch to direct plans", description: "Save ~₹14k/yr in fund fees", healthDelta: 3, savings: 14_000, complexity: "medium" },
            { id: "s_balance_midcap", name: "Rebalance mid-cap tilt", description: "Bring mid+small below 25%", healthDelta: 2, savings: null, complexity: "low" },
        ];
    },
    async simulate() {
        await delay(420);
        return { before: {}, after: {}, delta: { health_score: 5 }, summary: [] };
    },
    async rebalancePlan() {
        await delay(420);
        return { total_actions: 3, rebalance_amount_rs: 1_20_000, actions: [] };
    },
    async save(args) {
        await delay(220);
        return { saved_id: "scn_mock_1", name: args.name, saved_at: new Date().toISOString() };
    },
    async listSaved() { await delay(180); return []; },
    async deleteSaved() { await delay(120); },
    async apply() { await delay(380); return { pending_plan_id: "plan_mock_applied" }; },
    async listPending() { await delay(180); return []; },
    async deletePending() { await delay(120); },
    async completePending() { await delay(220); return { completed_at: new Date().toISOString() }; },
};
export const mockIntelligenceAdapter = {
    async portfolio() {
        await delay(280);
        return {
            look_through: { sectors: [], top_stocks: [] },
            stock_overlap: { hot_pairs: [] },
            narrative: "Your portfolio is moderately concentrated with one redundant fund pair.",
        };
    },
    async simulate() { await delay(380); return { score: 82, change_pp: 8 }; },
    async v3Score() { await delay(220); return { score: 76, primitives: {} }; },
    async sectorPeers() { await delay(200); return []; },
};
