/**
 * Mock insights adapter.
 */
import type { InsightsAdapter } from "../adapters/insights.adapter";
import { mockPortfolio } from "@/mock-data/portfolio";

const delay = (ms: number) => new Promise<void>((r) => setTimeout(r, ms));

export const mockInsightsAdapter: InsightsAdapter = {
  async analysis() {
    await delay(200);
    return {
      health: { health_score: mockPortfolio.healthScore, score: mockPortfolio.healthScore, grade: "B+", label: "Good" },
      summary: {},
      topActions: [],
    };
  },
  async v3Portfolio() {
    await delay(200);
    return {
      portfolioScore: mockPortfolio.healthScore,
      coveragePct: 92,
      fundScores: [],
    };
  },
  async list() {
    await delay(220);
    return {
      insights: structuredClone(mockPortfolio.topInsights),
      counts: { total: mockPortfolio.topInsights.length },
    };
  },
  async regenerate() { await delay(380); return { ok: true }; },
};
