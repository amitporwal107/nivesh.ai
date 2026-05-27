import { mockConcentration } from "@/mock-data/concentration";
import { mockRisk } from "@/mock-data/risk";
import { mockGoals } from "@/mock-data/goals";
import { mockRecommendations } from "@/mock-data/recommendations";
const delay = (ms) => new Promise((r) => setTimeout(r, ms));
export const mockDashboardsAdapter = {
    async fetch(domain) {
        await delay(280);
        const recs = mockRecommendations.slice(0, 3).map((r) => ({
            id: r.id,
            source_domain: domain,
            verb: r.action,
            title: r.title,
            impact: r.benefit,
            trade_off: r.riskImpact,
            priority_label: "Closes most",
            exclusive: false,
        }));
        const envelopes = {
            concentration: {
                type: "concentration",
                badge: "ATTENTION",
                insight: `1 in 3 rupees in ${mockConcentration.sectors[0]?.name.toLowerCase()}`,
                stat_tiles: [
                    { label: "Top sector", value: `${mockConcentration.sectors[0]?.pct}%`, sub: mockConcentration.sectors[0]?.name, tone: "warm" },
                    { label: "Top stock", value: `${mockConcentration.topStockPct.toFixed(1)}%`, sub: mockConcentration.topStockName, tone: "warm" },
                    { label: "HHI", value: mockConcentration.herfindahl, sub: "Herfindahl", tone: "info" },
                ],
                breakdown: { sectors: mockConcentration.sectors },
                recommendations: recs,
            },
            diversification: {
                type: "diversification",
                badge: "INFO",
                insight: "3 redundant pairs",
                stat_tiles: [
                    { label: "Effective N", value: 11, tone: "warm" },
                    { label: "Avg ρ", value: "0.48" },
                ],
                breakdown: {},
                recommendations: recs,
            },
            risk: {
                type: "risk",
                badge: "ATTENTION",
                insight: `Worst-case 12-month loss: ${(mockRisk.vaR95Paise / 100 / 100000).toFixed(2)} L`,
                stat_tiles: [
                    { label: "VaR 95", value: `${(mockRisk.vaR95Pct * 100).toFixed(1)}%`, tone: "warm" },
                    { label: "Vol", value: `${(mockRisk.annualVolPct * 100).toFixed(1)}%` },
                    { label: "Beta", value: mockRisk.beta.toFixed(2) },
                ],
                breakdown: { drivers: mockRisk.riskDrivers, scenarios: mockRisk.stressScenarios },
                recommendations: recs,
            },
            performance: {
                type: "performance",
                badge: "HEALTHY",
                insight: "Beating benchmark by 2.1 pp",
                stat_tiles: [
                    { label: "XIRR", value: "+18.7%", tone: "good" },
                    { label: "Alpha", value: "+2.1 pp", tone: "good" },
                    { label: "Sharpe", value: "1.34" },
                ],
                breakdown: {},
                recommendations: recs,
            },
            goals: {
                type: "goals",
                badge: "WATCH",
                insight: `${mockGoals.filter((g) => g.onTrack).length} of ${mockGoals.length} on track`,
                stat_tiles: mockGoals.map((g) => ({
                    label: g.name,
                    value: `${Math.round(g.progress * 100)}%`,
                    tone: g.onTrack ? "good" : "warm",
                })),
                breakdown: { goals: mockGoals },
                recommendations: recs,
            },
            tax: {
                type: "tax",
                badge: "HEALTHY",
                insight: "₹11,520 in your hands if you act by Mar 31",
                stat_tiles: [
                    { label: "LTCG cap", value: "₹1.25L" },
                    { label: "Used", value: "₹0.86L" },
                    { label: "Days to FY end", value: 124, tone: "info" },
                ],
                breakdown: {},
                recommendations: recs,
            },
        };
        return structuredClone(envelopes[domain]);
    },
};
