import { mockPortfolio, mockNavHistory } from "@/mock-data/portfolio";
import { mockHoldings } from "@/mock-data/holdings";
const delay = (ms) => new Promise((r) => setTimeout(r, ms));
export const mockPortfolioAdapter = {
    async listHoldings() {
        await delay(280);
        return structuredClone(mockHoldings);
    },
    async listHoldingsEnriched() {
        await delay(300);
        return {
            portfolio_id: "port-mock-1",
            total_value_rs: mockPortfolio.totalValue / 100,
            total_invested_rs: (mockPortfolio.totalValue - mockPortfolio.yearChange.abs) / 100,
            total_gain_pct: mockPortfolio.yearChange.pct,
            holdings: [],
        };
    },
    async getSummary() {
        await delay(320);
        return structuredClone(mockPortfolio);
    },
    async getNavHistory() {
        await delay(220);
        return structuredClone(mockNavHistory);
    },
    async searchInstruments() {
        await delay(180);
        return [];
    },
    async listSips() {
        await delay(220);
        return { total_monthly_sip_rs: 38_100, sips: [] };
    },
};
