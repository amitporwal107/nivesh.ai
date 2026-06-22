/**
 * Mock portfolio adapter — wraps existing mock-data with a small delay.
 * Matches `realPortfolioAdapter` signature exactly.
 */
import type { PortfolioAdapter } from "../adapters/portfolio.adapter";
import { mockPortfolio, mockNavHistory } from "@/mock-data/portfolio";
import { mockHoldings } from "@/mock-data/holdings";

const delay = (ms: number) => new Promise<void>((r) => setTimeout(r, ms));

export const mockPortfolioAdapter: PortfolioAdapter = {
  async listHoldings() {
    await delay(280);
    return structuredClone(mockHoldings);
  },
  async listHoldingsEnriched() {
    await delay(300);
    // Derive enriched rows from the basic mock holdings so the redesigned
    // Portfolio page (which renders the enriched shape) works in dev/mock mode.
    const BADGES = ["HOLD", "REVIEW", "REDUCE"];
    const totalValueRs = mockHoldings.reduce((s, h) => s + h.marketValue, 0) / 100;
    const holdings = mockHoldings.map((h, i) => {
      const valueRs = h.marketValue / 100;
      const investedRs = h.costBasis / 100;
      return {
        holding_id: h.id,
        name: h.fund.name,
        asset_type: "equity",
        quantity: h.units,
        current_price: h.fund.nav / 100,
        value_rs: valueRs,
        invested_rs: investedRs,
        pnl_rs: valueRs - investedRs,
        pnl_pct: h.unrealizedPnlPct * 100,
        xirr_pct: h.returns.cagr * 100,
        weight_pct: totalValueRs ? (valueRs / totalValueRs) * 100 : 0,
        isin: h.fund.isin,
        sector: null,
        category: h.fund.category,
        action_badge: BADGES[i % BADGES.length],
        amfi_matched: true,
      };
    });
    return {
      holdings,
      totals: {
        count: holdings.length,
        value_rs: totalValueRs,
        invested_rs: mockHoldings.reduce((s, h) => s + h.costBasis, 0) / 100,
        pnl_rs: mockHoldings.reduce((s, h) => s + h.unrealizedPnl, 0) / 100,
        pnl_pct: mockPortfolio.yearChange.pct,
        xirr_pct: 19.4,
      },
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
    return {
      total_monthly_sip_rs: 23_000,
      sips: [
        { isin: "INF879O01027", fund: "Parag Parikh Flexi Cap", folio: "1234567/89",
          monthly_amount_rs: 15_000, day_of_month: 5, last_transaction: "2026-05-05",
          next_expected: "2026-06-05", status: "active" },
        { isin: "INF769K01010", fund: "Mirae Asset Large Cap", folio: "2345678/90",
          monthly_amount_rs: 5_000, day_of_month: 10, last_transaction: "2026-05-10",
          next_expected: "2026-06-10", status: "active" },
        { isin: "INF846K01EQ4", fund: "Axis Bluechip Direct Growth", folio: "3456789/01",
          monthly_amount_rs: 3_000, day_of_month: 1, last_transaction: "2026-05-01",
          next_expected: "2026-06-01", status: "active" },
      ],
    };
  },
};
